"""
看板只有**一个**取数入口，返回一行一个文件 + 一个 `state` 字段。

One dashboard data source: one row per file, one `state` field.

## v0.7.0 的结构变化（本文件同步更新）

- `ignored` **不再是文件状态**：忽略的真相源是 `_ignored_rules`（规则），
  台账里不再有 `status='ignored'` 的行。
- 对账失败**不再与台账正交**：缺失/残缺就是 `status='failed'`（`fail_reason`
  区分成因），由台账直接透出，不再从 `_last_status` 的两份数组叠加。
  只有台账不可用时才退回读 `_last_status` 投影。
- 对外仍叫 `state = "broken"`：看板失败标签一直用这个名字，改名只会让
  前端与既有断言一起失效，而用户看到的东西没有区别。

本用例钉五件事：

1. 五种 `state` 都能出现，且与台账 status 的对应关系正确；
2. `cooling` / `ready` 是**同一个 status 按冷却时间拆的**，判据必须与
   `_count_queue` / `_execute_sync` 一致（三处漂移会让看板说"可传"而同步不传）；
3. 失败行只出现**一次**，并带上 `detail`（缺失/残缺）；
4. 台账可用时不再读 `_last_status`（避免同一事实两份来源）；
5. 台账不可用时降级为 `_last_status` 投影，不炸整个看板。

⚠️ 需要 MoviePilot 后端，本机 skip。
"""

import os
import time

import pytest


def _plugin_and_store():
    try:
        import importlib
        mod = importlib.import_module("app.plugins.rsync115sync")
        store = importlib.import_module("app.plugins.rsync115sync.store")
    except Exception as exc:
        pytest.skip(f"无法导入（{exc.__class__.__name__}）")
    return mod, store


def _plugin(tmp_path, *, missing=None, corrupt=None):
    mod, store = _plugin_and_store()
    ledger = store.Store(os.path.join(str(tmp_path), "ledger.sqlite3"))
    p = mod.Rsync115Sync.__new__(mod.Rsync115Sync)
    p._ledger = ledger
    p._delay_hours = 4.0
    p._last_status = {"missing_files": list(missing or []),
                      "corrupt_files": list(corrupt or [])}
    p.save_data = lambda k, v: None
    p.get_data = lambda k: None
    return p, ledger, store


def test_all_five_states_are_representable(tmp_path):
    """五种 state 都要能表达出来 —— 这是"一个列表顶五个清单"的前提。"""
    p, led, st = _plugin(tmp_path)
    now = time.time()
    led.upsert("电视剧:cool.mkv", st.STATUS_CANDIDATE, pair="电视剧",
               rel_path="cool.mkv", enqueued_at=now - 60)
    led.upsert("电视剧:ready.mkv", st.STATUS_CANDIDATE, pair="电视剧",
               rel_path="ready.mkv", enqueued_at=now - 5 * 3600)
    led.upsert("电视剧:watch.mkv", st.STATUS_PENDING_VERIFY, pair="电视剧",
               rel_path="watch.mkv", enqueued_at=now - 60)
    led.upsert("电视剧:susp.mkv", st.STATUS_SUSPECT, pair="电视剧",
               rel_path="susp.mkv", origin="watch")
    led.upsert("电视剧:bad.mkv", st.STATUS_FAILED, pair="电视剧",
               rel_path="bad.mkv", fail_reason=st.FAIL_MISSING)

    data = p._api_get_items()["data"]
    assert set(data["states"]) == {"cooling", "ready", "watching",
                                   "suspect", "broken"}, data["states"]


def test_cooling_and_ready_split_by_the_same_predicate_as_the_sync(tmp_path):
    """
    `cooling` / `ready` 由**冷却时间**拆分，判据必须与同步侧一致。

    ⚠️ 三处（本方法 / `_count_queue` / `_execute_sync`）一旦漂移，看板就会出现
    「显示可传、点同步却什么都不传」这类无从解释的状态。
    """
    p, led, st = _plugin(tmp_path)
    now = time.time()
    led.upsert("电视剧:cool.mkv", st.STATUS_CANDIDATE, pair="电视剧",
               rel_path="cool.mkv", enqueued_at=now - 60)          # 1 分钟
    led.upsert("电视剧:ready.mkv", st.STATUS_CANDIDATE, pair="电视剧",
               rel_path="ready.mkv", enqueued_at=now - 5 * 3600)   # 5 小时 > 4h

    items = {it["key"]: it for it in p._api_get_items()["data"]["items"]}
    assert items["电视剧:cool.mkv"]["state"] == "cooling"
    assert items["电视剧:cool.mkv"]["remaining_seconds"] > 0
    assert items["电视剧:ready.mkv"]["state"] == "ready"
    assert items["电视剧:ready.mkv"]["remaining_seconds"] == 0


def test_pending_verify_is_exposed_as_watching(tmp_path):
    """
    对外用 `watching`，不用台账的实现语言 `pending_verify`。

    状态名不统一正是"五个清单"那套留下的毛病 —— 界面不该出现两个词指同一件事。
    """
    p, led, st = _plugin(tmp_path)
    led.upsert("电视剧:w.mkv", st.STATUS_PENDING_VERIFY, pair="电视剧",
               rel_path="w.mkv", enqueued_at=time.time() - 30)
    items = p._api_get_items()["data"]["items"]
    assert [it["state"] for it in items] == ["watching"]


def test_failed_rows_are_one_row_with_a_reason(tmp_path):
    """失败行只出现一次，并带 detail —— 不再从两份数组叠加。"""
    p, led, st = _plugin(tmp_path)
    led.upsert("电视剧:gone.mkv", st.STATUS_FAILED, pair="电视剧",
               rel_path="gone.mkv", fail_reason=st.FAIL_MISSING)
    led.upsert("电视剧:cut.mkv", st.STATUS_FAILED, pair="电视剧",
               rel_path="cut.mkv", fail_reason=st.FAIL_CORRUPT)

    items = p._api_get_items()["data"]["items"]
    keys = [it["key"] for it in items]
    assert keys.count("电视剧:gone.mkv") == 1
    by_key = {it["key"]: it for it in items}
    assert by_key["电视剧:gone.mkv"]["state"] == "broken"
    assert by_key["电视剧:gone.mkv"]["detail"] == "缺失"
    assert by_key["电视剧:cut.mkv"]["detail"] == "残缺"


def test_ledger_mode_ignores_the_legacy_arrays(tmp_path):
    """
    台账可用时 `_last_status` 的两份数组不再参与取数。

    ⚠️ 这正是 v0.7.0 要消灭的重复真相源：此前同一件事一份在台账、一份在
    `_last_status`，看板与命令各读各的，取消忽略/恢复后两边对不上。
    """
    p, led, st = _plugin(tmp_path, missing=["电视剧:legacy_only.mkv"])
    data = p._api_get_items()["data"]
    # 台账里没有 failed 行 → 即使旧数组里有，也不该出现
    assert data["items"] == []
    assert data["states"] == {}


def test_missing_ledger_degrades_to_reconciliation_only(tmp_path):
    """台账不可用时降级：只返回对账那部分，不抛异常（看板不能整块白掉）。"""
    mod, store = _plugin_and_store()
    p = mod.Rsync115Sync.__new__(mod.Rsync115Sync)
    p._ledger = None
    p._delay_hours = 4.0
    p._last_status = {"missing_files": ["电视剧:x.mkv"], "corrupt_files": []}
    data = p._api_get_items()["data"]
    assert data["states"] == {"broken": 1}
