"""站点刷流 V3 插件：动态删种作用域判定与诊断单测。

背景（生产实测）：用户以为任务选了「跟随下载器」的动态删种，磁盘满了却
一颗种子都不删。原因之一是作用域在若干处会**静默回落**成「按条件删除」，
而回落过程没有任何日志，从外部完全看不出差别。

本用例锁住 ``_task_delete_scope_detail`` 的判定与原因文案，确保每种回落
都给出可读原因（而不是无声变成 none）。
"""
import threading

from app.plugins.brushflow import BrushFlow, BrushTaskConfig


def _make_task(config=None):
    """构造一个绑定到 qb 的任务配置"""
    return BrushTaskConfig(
        {
            "id": "aabbccdd00112233",
            "name": "聆音刷流",
            "site_id": 1,
            "downloader": "qb",
            **(config or {}),
        }
    )


def _make_plugin(task, *, global_enabled=False, global_range=None, downloader_limits=None):
    """构造不经过 __init__ 的插件实例，只注入作用域判定所需状态"""
    plugin = object.__new__(BrushFlow)
    plugin._task_configs = {task.id: task}
    plugin._task_locks = {}
    plugin._runtime = {}
    plugin._runtime_lock = threading.Lock()
    plugin._task_context = threading.local()
    plugin._task_context.task_id = task.id
    plugin._global_proxy_delete = global_enabled
    plugin._global_delete_size_range = global_range
    plugin._downloader_limits = downloader_limits or {}
    return plugin


class TestDeleteScopeDetail:
    """_task_delete_scope_detail：作用域与回落原因"""

    def test_disabled_returns_none_with_reason(self):
        """未启用动态删种时说明为「按条件删除」"""
        task = _make_task({"proxy_delete": False})
        scope, reason = _make_plugin(task)._task_delete_scope_detail(task)
        assert scope == "none"
        assert "未启用动态删种" in reason

    def test_task_scope_without_range_falls_back(self):
        """选了本任务阈值但没填，必须给出原因而不是静默 none"""
        task = _make_task({"proxy_delete": True, "dynamic_delete_scope": "task"})
        scope, reason = _make_plugin(task)._task_delete_scope_detail(task)
        assert scope == "none"
        assert "未填写阈值" in reason

    def test_task_scope_with_range_is_effective(self):
        """填了本任务阈值时按任务级生效"""
        task = _make_task(
            {"proxy_delete": True, "dynamic_delete_scope": "task", "delete_size_range": "50-100"}
        )
        scope, reason = _make_plugin(task)._task_delete_scope_detail(task)
        assert scope == "task"
        assert "50-100" in reason

    def test_global_scope_requires_global_enabled(self):
        """选了跟随全局但全局未开，回落并说明原因"""
        task = _make_task({"proxy_delete": True, "dynamic_delete_scope": "global"})
        scope, reason = _make_plugin(task, global_enabled=False)._task_delete_scope_detail(task)
        assert scope == "none"
        assert "全局" in reason

    def test_global_scope_effective_when_enabled(self):
        """全局开关与阈值齐备时按全局生效"""
        task = _make_task({"proxy_delete": True, "dynamic_delete_scope": "global"})
        plugin = _make_plugin(task, global_enabled=True, global_range="100")
        scope, reason = plugin._task_delete_scope_detail(task)
        assert scope == "global"
        assert "100" in reason

    def test_downloader_scope_requires_matching_name(self):
        """下载器名不匹配是最隐蔽的失效：原因里必须带上已配置的下载器名"""
        task = _make_task({"proxy_delete": True, "dynamic_delete_scope": "downloader"})
        plugin = _make_plugin(
            task,
            downloader_limits={"qBittorrent": {"proxy_delete": True, "delete_size_range": "80"}},
        )
        scope, reason = plugin._task_delete_scope_detail(task)
        assert scope == "none"
        assert "qb" in reason
        assert "qBittorrent" in reason  # 提示实际配置了哪个名字

    def test_downloader_scope_effective_on_name_match(self):
        """名字逐字符一致且阈值齐备时按下载器级生效"""
        task = _make_task({"proxy_delete": True, "dynamic_delete_scope": "downloader"})
        plugin = _make_plugin(
            task,
            downloader_limits={"qb": {"proxy_delete": True, "delete_size_range": "80"}},
        )
        scope, reason = plugin._task_delete_scope_detail(task)
        assert scope == "downloader"
        assert "80" in reason

    def test_downloader_scope_without_range_falls_back(self):
        """下载器条目存在但未填阈值时也要说明"""
        task = _make_task({"proxy_delete": True, "dynamic_delete_scope": "downloader"})
        plugin = _make_plugin(
            task, downloader_limits={"qb": {"proxy_delete": True, "delete_size_range": None}}
        )
        scope, reason = plugin._task_delete_scope_detail(task)
        assert scope == "none"
        assert "未单独配置" in reason

    def test_scope_helper_is_consistent_with_public_method(self):
        """_task_delete_scope 与 detail 必须给出同一个作用域"""
        task = _make_task(
            {"proxy_delete": True, "dynamic_delete_scope": "task", "delete_size_range": "10-20"}
        )
        plugin = _make_plugin(task)
        assert plugin._task_delete_scope(task) == plugin._task_delete_scope_detail(task)[0]
