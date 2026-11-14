"""
批次出队结算（`_settle_candidate_batch`）：ready / retry 共用的台账行结算。

v0.8.7 修复 2026-11-14 生产缺陷的回归守卫。

## 缺陷形态（用户实测）

看板「批量直接同步」走 `/sync_item` → `mode="retry"` + custom_files，并先把所选
key 从队列**缓存**摘掉（台账行仍是 candidate）。修复前 retry 轮的结算只有
`_strm_arm_watch`，而 arm_watch 对**非视频文件直接跳过** —— 16 个 nfo/jpg 传完
后既没落终态、也没人再碰这一行；行不在缓存 → ready 巡检永远取不到件 → 它们以
candidate 挂死在「冷却队列」里，直到插件重载缓存重建才被自愈。

修复把 ready 分支的出队结算抽成 `_settle_candidate_batch`，ready 与 retry 调用
**同一实现** —— 两处不可能再分叉。

本文件不依赖后端：store.py 只用标准库，业务侧用最小桩实例（真实 StrmOpsMixin）
在 tmp_path 台账上跑。哨兵断言检查 `__init__.py` 的结算确实收口到了共享方法。
"""

import ast
import importlib.util
import os
import time

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_PLUGIN_DIR = os.path.join(_REPO, "plugins.v3", "rsync115sync")


def _load_store():
    path = os.path.join(_PLUGIN_DIR, "store.py")
    spec = importlib.util.spec_from_file_location("_rsync_store_settle", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_strm_ops(store_mod):
    """按文件路径加载 strm_ops.py（注入桩 app.* 后可用 importlib）。"""
    import sys
    import types
    for m in ["app", "app.core", "app.core.event", "app.sdk", "app.sdk.logging"]:
        if m not in sys.modules:
            sys.modules[m] = types.ModuleType(m)
    ev = sys.modules["app.core.event"]
    if not getattr(ev, "Event", None):
        class _Ev:
            def __init__(self, event_type=None, event_data=None):
                self.event_type = event_type
                self.event_data = event_data or {}
        ev.Event = _Ev
        ev.EventType = types.SimpleNamespace(PluginAction=1, MessageAction=2)
        ev.eventmanager = types.SimpleNamespace(register=lambda *a, **kw: (lambda f: f))
    lg = sys.modules["app.sdk.logging"]
    if not getattr(lg, "logger", None):
        lg.logger = types.SimpleNamespace(
            info=lambda *a, **kw: None, debug=lambda *a, **kw: None,
            warning=lambda *a, **kw: None, error=lambda *a, **kw: None)
    path = os.path.join(_PLUGIN_DIR, "strm_ops.py")
    spec = importlib.util.spec_from_file_location("_rsync_strm_ops_settle", path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "_rsync_strm_ops_settle"
    sys.modules["_rsync_strm_ops_settle"] = mod
    # 相对导入的兄弟模块（constants / paths / store / strm / cd2）手工接上
    def _load_sibling(name, alias):
        p = os.path.join(_PLUGIN_DIR, f"{name}.py")
        s = importlib.util.spec_from_file_location(f"_rsync_strm_ops_settle.{name}", p)
        m = importlib.util.module_from_spec(s)
        m.__package__ = f"_rsync_strm_ops_settle"
        sys.modules[f"_rsync_strm_ops_settle.{name}"] = m
        sys.modules[alias] = m
        s.loader.exec_module(m)
        return m
    _load_sibling("constants", "_rsync_strm_ops_settle.constants")
    _load_sibling("paths", "_rsync_strm_ops_settle.paths")
    sys.modules["_rsync_strm_ops_settle.store"] = store_mod
    _load_sibling("strm", "_rsync_strm_ops_settle.strm")
    _load_sibling("cd2", "_rsync_strm_ops_settle.cd2")
    spec.loader.exec_module(mod)
    return mod


store = _load_store()
NOW = time.time()


def _plugin_src(name):
    with open(os.path.join(_PLUGIN_DIR, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture()
def p(tmp_path):
    """最小桩插件：真实 StrmOpsMixin + tmp 台账 + 三视图（与生产绑定同构）。"""
    try:
        so = _load_strm_ops(store)
    except Exception as exc:      # pragma: no cover
        pytest.skip(f"strm_ops 加载失败（{exc.__class__.__name__}）")
    led = store.Store(os.path.join(str(tmp_path), "ledger.sqlite3"))
    assert led.usable

    class FakePlugin(so.StrmOpsMixin):
        def _strm_watchable(self, key):
            ext = key.rsplit(".", 1)[-1].lower()
            if ext in ("mp4", "mkv"):
                return True, "", ""
            return False, "non_video", "非视频"

        def _is_ignored(self, key):
            return key in self._ignored_rules

        def save_data(self, k, v):
            pass

    inst = FakePlugin()
    inst._ledger = led
    inst._pending_queue = store.LedgerMapping(
        led, store.STATUS_CANDIDATE, ts_field="enqueued_at")
    inst._strm_watch = store.LedgerMapping(
        led, store.STATUS_PENDING_VERIFY, ts_field="enqueued_at")
    inst._strm_suspects = store.LedgerMapping(
        led, store.STATUS_SUSPECT, ts_field="verified_at",
        extra_from_value={"origin": "origin"})
    inst._strm_gen_requested = {}
    inst._ignored_rules = []
    inst._sync_pairs = [{"name": "9KG", "src": "/src", "dest": "/115",
                         "strm_dir": "/strm", "all_ext": True}]
    inst._strm_notified = False
    return inst


def _enqueue(p, keys):
    for k in keys:
        p._pending_queue[k] = NOW - 40000


# --------------------------------------------------------------------------
# 哨兵：结算收口到共享方法，retry 不再有独立结算路径
# --------------------------------------------------------------------------

def test_execute_sync_has_no_per_mode_settlement_split():
    """
    `_execute_sync` 的 ready/retry 结算必须走同一个 `_settle_candidate_batch`。

    缺陷的根因是结算写在 `mode == "ready"` 分支里、retry 只调 arm_watch。
    收口后 `__init__.py` 里不应再出现 `if mode == "ready"` 的结算块。
    """
    src = _plugin_src("__init__.py")
    assert "_settle_candidate_batch" in src, "结算未收口到共享方法"
    assert 'if mode in ("ready", "retry"):' in src, (
        "ready/retry 结算没有合并成同一分支")


def test_retry_settlement_covers_non_video(p):
    """
    ⚠️ 核心缺陷断言（生产实测）：retry 批、缓存已被摘（/sync_item 的行为）、
    行仍是 candidate —— 非视频文件传完后必须落终态 done，而不是挂死 candidate。
    """
    vids = [f"9KG:剧/E{n:02d}.mkv" for n in range(1, 5)]
    nonv = [f"9KG:剧/E{n:02d}.nfo" for n in range(1, 17)]
    _enqueue(p, vids + nonv)
    # /sync_item 摘缓存：行保持 candidate
    from _rsync_strm_ops_settle.store import forget_key
    for k in vids + nonv:
        forget_key(p._pending_queue, k)

    pair_files = [k.split(":", 1)[1] for k in vids + nonv]
    watchable = p._settle_candidate_batch("9KG", pair_files, [], [], set())

    assert set(watchable) == set(vids), f"可观察清单错: {watchable}"
    for k in nonv:
        row = p._ledger.get(k)
        assert row["status"] == store.STATUS_DONE, (
            f"非视频行必须落 done（缺陷场景核心断言），实际 {row['status']}: {k}")
        assert row["synced_at"] is not None
    # 可观察行留在 candidate，等 arm_watch 改写（调用方职责）
    for k in vids:
        assert p._ledger.get(k)["status"] == store.STATUS_CANDIDATE


def test_ready_path_semantics_unchanged(p):
    """ready 正常路径（行在缓存）：可观察→摘缓存待 arm；非视频→done。"""
    vids = ["9KG:a/E01.mkv"]
    nonv = ["9KG:a/fanart.jpg"]
    _enqueue(p, vids + nonv)

    watchable = p._settle_candidate_batch(
        "9KG", ["a/E01.mkv", "a/fanart.jpg"], [], [], set())
    assert watchable == vids
    assert p._ledger.get(vids[0])["status"] == store.STATUS_CANDIDATE
    assert p._ledger.get(nonv[0])["status"] == store.STATUS_DONE
    assert vids[0] not in p._pending_queue
    assert nonv[0] not in p._pending_queue


def test_audit_failure_leaves_queue_and_cd2_hold_stays(p):
    """对账失败只摘缓存（failed 由结算末尾写）；CD2 hold 留在队列继续跟踪。"""
    fail_k, hold_k, ok_k = "9KG:bad/E01.mkv", "9KG:big/E01.mkv", "9KG:ok/E01.mkv"
    _enqueue(p, [fail_k, hold_k, ok_k])
    m_list = [fail_k, hold_k]

    watchable = p._settle_candidate_batch(
        "9KG", ["bad/E01.mkv", "big/E01.mkv", "ok/E01.mkv"], m_list, [], {hold_k})

    assert watchable == [ok_k]
    assert fail_k not in p._pending_queue, "失败行应摘缓存"
    assert hold_k in p._pending_queue, "CD2 hold 必须留在队列"
    assert p._ledger.get(fail_k)["status"] == store.STATUS_CANDIDATE, "摘缓存不删行"


def test_ignored_file_retires_to_done(p):
    """成功但已忽略的文件同样落 done（与 ready 分支旧语义一致）。"""
    k = "9KG:skip/E01.mkv"
    p._ignored_rules = [k]
    _enqueue(p, [k])
    watchable = p._settle_candidate_batch("9KG", ["skip/E01.mkv"], [], [], set())
    assert watchable == []
    assert p._ledger.get(k)["status"] == store.STATUS_DONE


def test_never_downgrades_a_non_candidate_row(p):
    """
    行已处于 pending_verify（例如上一轮 arm_watch 已改写）而缓存被摘时，
    不得被倒退覆盖成 done —— 写前查现 status 是这条断言的执行点。
    """
    k = "9KG:x/E01.mkv"
    p._ledger.upsert(k, store.STATUS_PENDING_VERIFY, synced_at=NOW - 100)
    p._settle_candidate_batch("9KG", ["x/E01.mkv"], [], [], set())
    row = p._ledger.get(k)
    assert row["status"] == store.STATUS_PENDING_VERIFY
    assert row["synced_at"] == NOW - 100
