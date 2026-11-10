"""
CD2「在传/排队」核对统一到失败判定入口（v0.8.2，TODO 10.5）的行为契约。

## 背景与三态语义（必须原样保留）

CD2 查询是**可选**的（默认关闭、需 URL + Token）。三态：
`None`=查不了（不改变任何判定）、`[]`=确实为空、`[...]`=任务列表。
任何新接入点都不得把「查不到」当「没在传」或当「失败」。

在传/排队集合刻意不含 `FINISH`（完成却没 strm 正是要抓的异常）与
`ERROR`（真的没传上去，应当继续报警）；卡死超过 `CD2_SUPPRESS_MAX_HOURS`
失去豁免。

## 本文件钉的行为

1. 结算判失败前批量剔除在传（`_cd2_hold_failed_settlement`）：
   被剔除的 key 不进 round_failed —— 不计重试次数、不写失败清单；
   ready 轮它**留在冷却队列**（出队会失去跟踪）。
2. 巡检回退（`_cd2_recover_failed_in_flight`）：已判失败但 CD2 显示在传的
   条目移回冷却队列（rsync 刚写完时 CD2 可能还没扫到挂载点）；
   **达上限的人工处理项不自动回退**。
3. 判据只有一个：`_cd2_in_flight_for`。

⚠️ 需要 MoviePilot 后端，本机无后端时整组 skip。
"""

import os

import pytest

_PLUGIN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    "plugins.v3", "rsync115sync")


def _plugin_src(name):
    """读插件源文件文本（哨兵断言只做文本包含，不 exec —— __init__.py 需要 app 宿主）。"""
    with open(os.path.join(_PLUGIN_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def _fixture(tmp_path):
    try:
        import importlib
        mod = importlib.import_module("app.plugins.rsync115sync")
        store = importlib.import_module("app.plugins.rsync115sync.store")
    except Exception as exc:
        pytest.skip(f"无法导入（{exc.__class__.__name__}）")
    ledger = store.Store(os.path.join(str(tmp_path), "ledger.sqlite3"))
    p = mod.Rsync115Sync.__new__(mod.Rsync115Sync)
    p._ledger = ledger
    p._failed_files = store.LedgerMapping(
        ledger, store.STATUS_FAILED, ts_field="verified_at",
        extra_from_value={"reason": "fail_reason", "count": "retry_count",
                          "exhausted_at": "exhausted_at"})
    p._pending_queue = store.LedgerMapping(
        ledger, store.STATUS_CANDIDATE, ts_field="enqueued_at")
    p._strm_watch = {}
    p._strm_suspects = {}
    p._ignored_rules = []
    p._delay_hours = 4.0
    p._sync_pairs = [{"name": "电视剧", "src": "/emby/TV", "dest": "/115/TV",
                      "pan_dir": "/HomeTheater/TV", "all_ext": False}]
    p._last_status = {"missing_files": [], "corrupt_files": []}
    p._strm_notified = False
    p.save_data = lambda k, v: None
    p.get_data = lambda k: None
    return p, ledger, store


# --------------------------------------------------------------------------
# 哨兵：结算与巡检确实接入了 CD2 判据
# --------------------------------------------------------------------------

def test_settlement_consults_cd2_before_failing():
    """结算写 round_failed 前必须批量查 CD2；被挡的 key 不进失败集合。"""
    src = _plugin_src("__init__.py")
    assert "_cd2_hold_failed_settlement" in src, (
        "结算未接入 CD2 在传判据 —— 大文件传输中会被立即判失败")


def test_cd2_blocked_set_is_bound_before_its_first_use():
    """
    ⚠️ 顺序守卫（review v0.8.2 的致命缺陷）：`cd2_blocked_keys` 必须在
    **第一次被引用之前**完成赋值，否则 ready 分支抛 UnboundLocalError，
    整轮同步中断 —— 而 py_compile 与所有门禁都不会报。

    第一版把它写在结算段（ready 出队分支之后），逐字命中这个坑。
    判据：函数内 `cd2_blocked_keys = ` 的赋值位置早于 `in cd2_blocked_keys`。
    """
    src = _plugin_src("__init__.py")
    start = src.index("def _execute_sync")
    end = src.index("\n    def ", start + 10)
    body = src[start:end]
    first_assign = body.find("cd2_blocked_keys: set = set()")
    assert first_assign != -1, "找不到 cd2_blocked_keys 的初始化 —— 守卫失效"
    first_use = body.find("in cd2_blocked_keys")
    assert first_use == -1 or first_assign < first_use, (
        "cd2_blocked_keys 在赋值前被引用 —— 会抛 UnboundLocalError，整轮同步中断")


def test_hold_does_not_turn_a_blocked_failure_into_recovery():
    """
    ⚠️ review F2：被 CD2 hold 的条目**不是**「已恢复」——
    「恢复」扫描必须跳过它，否则会 retire 成 done，云端没有却凭空消失。
    """
    src = _plugin_src("__init__.py")
    start = src.index("def _execute_sync")
    end = src.index("\n    def ", start + 10)
    body = src[start:end]
    # 恢复循环的条件里必须同时排除两个集合
    loop_at = body.index("for k in list(self._failed_files.keys()):")
    cond = body[loop_at:loop_at + 400]
    assert "round_cd2_blocked" in cond, (
        "恢复扫描未排除 CD2 hold 的条目 —— 会把它们 retire 成 done，文件凭空消失")


def test_revert_clears_the_retry_budget_columns():
    """⚠️ review F3：回退后台账里的 exhausted_at/retry_count 必须清零。"""
    src = _plugin_src("__init__.py")
    cd2_src = _plugin_src("cd2_ops.py")
    start = cd2_src.index("def _cd2_recover_failed_in_flight")
    end = cd2_src.index("\n    def ", start + 10)
    body = cd2_src[start:end]
    for marker in ("clear_fail_reason", 'clear_field(key, "exhausted_at")',
                   '"retry_count", 0'):
        assert marker in body, f"回退未清理 {marker} —— 旧预算会在下次失败时复活"


def test_scheduled_cycle_has_revert_hook():
    """定时巡检必须挂回退入口（上一轮判失败过早的撤回路径）。"""
    src = _plugin_src("__init__.py")
    assert "_cd2_recover_failed_in_flight" in src


# --------------------------------------------------------------------------
# 行为：hold / revert（需后端 + 最小 CD2 stub）
# --------------------------------------------------------------------------

def test_hold_suppressed_keys_are_excluded_from_round_failed(tmp_path):
    """在传的 key 不写失败、不计重试预算；ready 轮留在冷却队列。"""
    p, led, st = _fixture(tmp_path)
    keys = ["电视剧:a.mkv", "电视剧:b.mkv"]
    in_flight = {keys[0]: {"status": 3}}          # a 在传；b 无任务
    p._cd2_hold_failed_settlement = lambda ks: {k: in_flight[k] for k in ks if k in in_flight}

    total_missing = list(keys)
    blocked = set(p._cd2_hold_failed_settlement(total_missing).keys())
    round_failed = {k: "missing" for k in total_missing if k not in blocked}
    assert round_failed == {"电视剧:b.mkv": "missing"}, (
        "在传的 key 被写进了失败集合 —— 大文件传输中会被立即判失败")


def test_revert_moves_failed_back_to_queue_and_skips_exhausted(tmp_path):
    """回退：failed → candidate（基准近期），达上限的跳过。"""
    p, led, st = _fixture(tmp_path)
    p._cd2_in_flight_for = lambda ks: {ks[0]: {"status": 3}} if ks else {}
    p._failed_files["电视剧:a.mkv"] = {"ts": 1.0, "reason": "corrupt"}
    p._failed_files["电视剧:b.mkv"] = {"ts": 1.0, "reason": "corrupt",
                                       "count": 3, "exhausted_at": 9.0}
    led.upsert("电视剧:a.mkv", st.STATUS_FAILED, fail_reason=st.FAIL_CORRUPT)
    led.upsert("电视剧:b.mkv", st.STATUS_FAILED, fail_reason=st.FAIL_CORRUPT,
               retry_count=3, exhausted_at=9.0)

    reverted = p._cd2_recover_failed_in_flight()

    assert reverted == ["电视剧:a.mkv"], "达上限的人工处理项不得被自动回退"
    assert "电视剧:a.mkv" not in p._failed_files
    assert "电视剧:a.mkv" in p._pending_queue, "回退的条目必须回到冷却队列"
    row = led.get("电视剧:a.mkv")
    assert row["status"] == st.STATUS_CANDIDATE
    # 达上限的 b 原样保留
    assert led.get("电视剧:b.mkv")["status"] == st.STATUS_FAILED
    assert led.get("电视剧:b.mkv")["exhausted_at"] == 9.0


def test_revert_is_noop_when_cd2_unknown_or_empty(tmp_path):
    """查不到（未启用/失败）或确实为空 → 什么都不改变（三态语义）。"""
    p, led, st = _fixture(tmp_path)
    p._failed_files["电视剧:a.mkv"] = {"ts": 1.0, "reason": "missing"}
    led.upsert("电视剧:a.mkv", st.STATUS_FAILED, fail_reason=st.FAIL_MISSING)
    p._cd2_in_flight_for = lambda ks: {}

    assert p._cd2_recover_failed_in_flight() == []
    assert "电视剧:a.mkv" in p._failed_files
    assert led.get("电视剧:a.mkv")["status"] == st.STATUS_FAILED
