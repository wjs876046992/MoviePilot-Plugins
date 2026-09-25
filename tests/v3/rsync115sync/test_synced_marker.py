"""
`synced_at` 的写入契约：同步成功的那一刻必须留痕。

The `synced_at` write contract: a successful sync must leave a trace.

**为什么单独一组**：用户需求原话是「所有映射目录里的视频，同时也可以一份台账…
**便于区分已成功的**」（C1）。而这一列在本次验证之前**没有任何写入者** ——
台账建了三批，`synced_at` 一直是空的，`/status` 的 `ledger.synced_files`
永远是 0。这与 `events` 表那次是同一类问题：**有列、有查询、有测试，但没数据**。

⚠️ 它与 `status` **正交**，不能用状态代替：一个文件可以既同步成功过、又处于
待处理 —— 那正是"传过、但这一轮没传成"的形态，是有用的事实而非矛盾。
"""

import importlib
import os


def _plugin(root):
    module = importlib.import_module("app.plugins.rsync115sync")
    src = os.path.join(root, "src")
    os.makedirs(src, exist_ok=True)
    with open(os.path.join(src, "a.mkv"), "wb") as fh:
        fh.write(b"x")

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{
        "name": "电视剧", "src": src, "dest": "/115/TV",
        "strm_dir": os.path.join(root, "strm"), "all_ext": False,
    }]
    plugin._strm_watch = {}
    plugin._strm_suspects = {}
    plugin._strm_gen_requested = {}
    plugin._ignored_rules = []
    plugin._exclude_patterns = ""
    plugin._media_extensions = "mkv"
    plugin._strm_notified = False
    plugin._ledger = module.store.Store(root / "ledger.sqlite3") \
        if hasattr(module, "store") else None
    if plugin._ledger is None:
        from app.plugins.rsync115sync.store import Store, STATUS_PENDING_VERIFY
        plugin._ledger = Store(root / "ledger.sqlite3")
    plugin.save_data = lambda k, v: None
    return plugin, module


def test_arming_a_watch_records_the_synced_moment(tmp_path):
    """
    rsync 报成功 ⇒ 登记观察的同时写下 `synced_at`。

    ⚠️ 措辞是"rsync 报成功"，不是"已验证可用" —— 后者要等 .strm 出现。
    因此这一列允许与"后来转成待处理"并存。
    """
    plugin, _ = _plugin(tmp_path)
    key = "电视剧:a.mkv"

    plugin._strm_arm_watch([key])

    row = plugin._ledger.get(key)
    assert row is not None, "登记观察后台账里必须有这一行"
    assert row["synced_at"] is not None, (
        "同步成功没有写下 synced_at —— 台账就答不出「哪些是已成功的」"
    )


def test_missing_ledger_does_not_break_arming(tmp_path):
    """
    台账不可用时登记观察必须照常完成。

    ⚠️ 台账是辅助设施，它出问题绝不能让同步流程中断 —— 而 `_mark_synced`
    正是插在同步路径里的一步。这也是它用 `getattr` 取 `_ledger` 的原因：
    本插件有大量 `__new__` 构造的最小实例，它们没有 `init_plugin` 建的那些属性。
    """
    plugin, _ = _plugin(tmp_path)
    plugin._ledger = None

    armed = plugin._strm_arm_watch(["电视剧:a.mkv"])

    assert armed == 1, "台账没了也必须照常登记"
    assert "电视剧:a.mkv" in plugin._strm_watch


def test_missing_ledger_attribute_does_not_raise(tmp_path):
    """`__new__` 实例上连 `_ledger` 属性都没有 —— 不得抛 AttributeError。"""
    plugin, _ = _plugin(tmp_path)
    del plugin.__dict__["_ledger"]      # 模拟从未跑过 init_plugin 的实例

    assert plugin._strm_arm_watch(["电视剧:a.mkv"]) == 1
