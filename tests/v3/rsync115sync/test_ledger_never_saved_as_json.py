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
    """
    构造一个**已绑定台账替身**的实例（这是本组的重点：属性是替身不是 dict）。

    ⚠️ 必须补 `plugindata`（2026-11-10 修）：本组用 `__new__` 跳过基类
    `__init__`，而真实后端的 `_PluginBase.get_data` 访问 `self.plugindata`
    → `AttributeError`。桩宿主里基类没有该属性，所以本机跑是绿的、**一搬到
    真实后端就红**。这里补一个最小替身：只提供本组用到的
    `get_data/set_data/del_data`，语义与宿主一致（键存在才返回）。

    为什么不是「把断言改成不调 get_data」：那条断言本身有价值 ——
    它验证「替身被覆盖点拦下、**没有**落到宿主存储」。去掉就只剩
    「不抛异常」，漏掉真正的事故形态（静默写进去）。
    """
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

    class _HostData:
        """
        宿主 `plugindata` 的最小替身 —— **签名必须与真实宿主一致**。

        ⚠️ 第一版写错了（2026-11-10）：用的是 `get_data(key)` / `save_data(key, value)`，
        而真实 `_PluginBase` 调的是：

            self.plugindata.save(plugin_id, key, value)
            self.plugindata.get_data(plugin_id, key)
            self.plugindata.del_data(plugin_id, key)

        —— **plugin_id 在前**，且写入方法叫 `save` 不是 `save_data`。
        签名不符时不是断言失败，而是 `AttributeError: '_HostData' object has
        no attribute 'save'`，看起来像产品 bug、实则是替身写歪了。
        照着 `app/sdk/plugin/base.py:366-425` 抄，别凭印象。

        `save` 刻意**不做 JSON 校验**：本组判据是「替身根本没被交给宿主」，
        不是「交过去会不会炸」。交给它就会留下键，断言立刻能看见。
        """

        def __init__(self):
            self._d = {}

        def save(self, plugin_id, key, value):
            self._d[(plugin_id, key)] = value
            return True

        def get_data(self, plugin_id, key=None):
            return self._d.get((plugin_id, key))

        def del_data(self, plugin_id, key):
            self._d.pop((plugin_id, key), None)
            return True

    plugin.plugindata = _HostData()
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

    ⚠️ 不要断言返回值是 `True`（2026-11-10 修）：插件自己的 `save_data` 覆盖点
    在**跳过**分支返回 `True`，放行分支 `return super().save_data(...)`
    —— 而真实宿主的签名是 `-> None`，于是放行时返回 `None`。
    桩环境里它恰好返回 True，断言因此一直绿；换到真实后端就红。
    本用例的判据是**值真的被持久化**，返回值不是契约。
    """
    plugin, _ = _plugin_with_ledger(tmp_path)
    plugin._strm_watch = {"电视剧:a.mkv": 1.0}      # 降级为普通 dict

    plugin.save_data("strm_watch", plugin._strm_watch)      # 不得抛
    assert plugin.get_data("strm_watch") == {"电视剧:a.mkv": 1.0}, (
        "降级路径必须真的把普通 dict 写进宿主存储 —— 否则重载后队列丢失")


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
