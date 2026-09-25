"""
台账替身**绝不能交给宿主的 JSON 列** —— 这是一次真机事故的护栏。

A ledger-backed mapping must never reach the host's JSON column.

## 事故经过（本次的 102 = 102 就是这个）

第 2 批把四类状态切成台账替身后，代码里约 19 处
`self.save_data("strm_watch", self._strm_watch)` 一类调用没有清掉。
真实宿主的 `save_data` 把它们写进 SQLAlchemy 的 **JSON 列**，于是抛：

    TypeError: Object of type LedgerMapping is not JSON serializable

而它抛在 `_execute_sync → _strm_arm_watch` 这个极其要命的位置 ——
实机日志里是「同步过程发生异常」，**整轮同步就此终止**。
于是 102 个文件一个也没传成，它们又都留在冷却队列里，
看板上「入库延迟」与「异常清单」就显示成同一个数字。

## 为什么单测当时抓不到

本仓自建的桩宿主里 `save_data` 只是 `self._store[k] = v`，**什么对象都收得下**。
真实宿主才会当 JSON 序列化。这条用例因此做两件事：
① 让桩变成 JSON 严格（忠实复现宿主）；
② 明确断言"把替身交给 save_data 不抛异常、且不会真的写进宿主"。
"""

import importlib


def _status(name):
    """按名字取台账里的 STATUS_* 常量（避免在文件顶部硬编码一串 import）。"""
    from app.plugins.rsync115sync import store
    return getattr(store, f"STATUS_{name}")


def _plugin_with_ledger(root):
    """构造一个**已绑定台账替身**的实例（这是本组的重点：属性是替身不是 dict）。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    from app.plugins.rsync115sync.store import (
        LedgerMapping, STATUS_CANDIDATE, STATUS_PENDING_VERIFY, Store,
    )

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    ledger = Store(root / "ledger.sqlite3")
    plugin._ledger = ledger
    plugin._pending_queue = LedgerMapping(ledger, STATUS_CANDIDATE)
    plugin._strm_watch = LedgerMapping(ledger, STATUS_PENDING_VERIFY)
    plugin._strm_suspects = LedgerMapping(
        ledger, module.store.STATUS_SUSPECT,
        ts_field="verified_at", extra_from_value={"origin": "origin"})
    plugin._strm_gen_requested = module.store.LedgerFieldMap(
        ledger, "gen_requested_at")
    plugin._host_saved = {}
    return plugin, ledger


def test_ledger_mapping_never_reaches_host_storage(tmp_path):
    """
    `save_data(<替身>)` 必须被静默跳过 —— 既不能抛异常，也不能写进宿主。

    桩的 `save_data` 是 JSON 严格的（与真实宿主一致），因此若覆盖点失效，
    这里会直接抛 TypeError，而不是悄悄放过。
    """
    plugin, ledger = _plugin_with_ledger(tmp_path)
    plugin._strm_watch["电视剧:a.mkv"] = 1.0

    # 必须不抛
    assert plugin.save_data("strm_watch", plugin._strm_watch) is True

    # 且不得真的交给宿主持久化（桩把内容记在 _store 里，这里用同名键检查）
    assert plugin.get_data("strm_watch") is None, (
        "替身被写进了宿主存储 —— 在真实宿主上这一步会因 JSON 序列化而抛异常"
    )


def test_degraded_path_still_persists_plain_dicts(tmp_path):
    """
    ⚠️ 台账**不可用**时，属性是普通 dict，那时 `save_data` 就是唯一的持久化手段
    —— 覆盖点必须放行，否则降级路径会丢数据。

    这正是"跳过"的判据用 `isinstance(值, 替身类)` 而不是"台账可不可用"的理由：
    两种情形各走各的路，调用点不需要任何分支。
    """
    plugin, _ = _plugin_with_ledger(tmp_path)
    plugin._strm_watch = {"电视剧:a.mkv": 1.0}      # 降级为普通 dict

    assert plugin.save_data("strm_watch", plugin._strm_watch) is True
    assert plugin.get_data("strm_watch") == {"电视剧:a.mkv": 1.0}


def test_clearing_keeps_the_mapping_object_not_a_plain_dict(tmp_path):
    """
    `_api_strm_clear` 必须用 `.clear()`，不得 `self._strm_watch = {}`。

    后者会把台账替身整个换回普通 dict —— 之后所有写入只进内存、重建即丢，
    而台账里那些行永远留着。表现是"点了清空、刷新又回来了"。
    """
    plugin, ledger = _plugin_with_ledger(tmp_path)
    from app.plugins.rsync115sync.store import LedgerMapping

    plugin._strm_watch["电视剧:a.mkv"] = 1.0
    plugin._strm_suspects["电视剧:b.mkv"] = {"ts": 1.0, "origin": "scan"}
    plugin._strm_gen_requested["电视剧:b.mkv"] = 1.0
    plugin._sync_pairs = []
    plugin._strm_notified = False

    plugin._api_strm_clear()

    assert isinstance(plugin._strm_watch, LedgerMapping), \
        "清空把台账替身换成了普通 dict —— 此后写入不再进台账"
    assert isinstance(plugin._strm_suspects, LedgerMapping)
    assert len(plugin._strm_watch) == 0
    assert len(plugin._strm_suspects) == 0
    # 台账侧也必须真的空了（否则刷新后条目会"复活"）
    assert ledger.by_status(_status("PENDING_VERIFY")) == []
    assert ledger.by_status(_status("SUSPECT")) == []
    assert plugin._strm_gen_requested.get("电视剧:b.mkv") is None
