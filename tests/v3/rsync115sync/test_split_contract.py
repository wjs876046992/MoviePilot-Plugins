"""
阶段 2 拆分契约：Mixin 组合与版本字段在位。

Stage-2 split contract: mixin composition and the version literal stay intact.

**为什么有这条测试**：拆分的两类静默失败都无法靠编译发现 ——
  1. Mixin 组合漏了（类仍可实例化、测试可能全绿，但宿主按名字找不到方法）；
  2. plugin_version 字面量离开 __init__.py（版本门禁直接失败）。
DEVELOPMENT.md 8.5 的教训：只有真正实例化 + 属性访问才能发现拆分引入的
AttributeError，语法检查一概无效。
"""
import ast
import importlib
import os
from pathlib import Path

import pytest


def _plugin_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "plugins.v3" / "rsync115sync"
        if (candidate / "__init__.py").is_file():
            return candidate
    pytest.skip("rsync115sync 源码目录未找到")


def test_version_literal_still_in_init():
    """版本门禁从 __init__.py 读 plugin_version；主类搬家会直接炸 CI。"""
    tree = ast.parse((_plugin_dir() / "__init__.py").read_text(encoding="utf-8"))
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
               and n.name == "Rsync115Sync")
    assigned = set()
    for node in cls.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned.add(t.id)
    assert "plugin_version" in assigned, "plugin_version 必须留在 __init__.py 的主类上"


def test_mixins_are_stateless():
    """
    Mixin 不得在类体/模块级持有可变状态（DEVELOPMENT.md 8.1 的宿主约束）。

    状态若放进模块级全局量，插件自行导入的模块在宿主按实例重新执行时
    **不会被重置**，两个虚拟分身会共用同一份清单/队列。因此拆分红线是：
    Mixin 里只允许方法定义与导入。
    """
    for name in ("strm_ops", "sync_ops", "commands", "cd2_ops"):
        tree = ast.parse((_plugin_dir() / f"{name}.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                raise AssertionError(
                    f"{name}.py 模块级出现赋值语句 —— Mixin 必须保持无状态"
                )
            if isinstance(node, ast.ClassDef) and node.name.endswith("Mixin"):
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        raise AssertionError(
                            f"{name}.Mixin 类体出现赋值 —— 状态必须留在插件实例上"
                        )


def test_combined_class_exposes_full_surface():
    """组合后的类必须仍然提供宿主与看板依赖的全部方法。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    cls = module.Rsync115Sync
    surface = [
        # 基类契约
        "init_plugin", "get_state", "get_api", "get_form", "get_page",
        "stop_service", "get_command", "get_service", "get_render_mode",
        # 事件入口
        "on_webhook_message", "handle_command",
        # strm（strm_ops）
        "_strm_check", "_strm_scan", "check_one", "_check_watch_now",
        "_api_strm_clear", "_api_strm_prune", "_api_strm_ignore",
        "_api_strm_retry", "_api_strm_generate",
        # 限流 / 补传（sync_ops）
        "_rate_limit_allows", "_consume_upload_quota",
        "_api_backfill_scan", "_api_backfill_start",
        # 回复通道（commands）
        "_post_reply", "_plugin_mtype",
    ]
    for name in surface:
        assert callable(getattr(cls, name, None)), f"组合后的类缺少 {name}"


def test_instantiation_smoke(tmp_path):
    """
    真实实例化 + 关键路径冒烟（8.5 节：只有实例化才能发现 AttributeError）。

    ⚠️ **绝不能碰生产数据**（2026-11-10 实测事故）：这里原来直接
    `plugin = Rsync115Sync()` 再调 `_api_strm_ignore` —— 而真实实例的
    `save_data` 写的是宿主配置库。在 NAS 容器里跑真实后端套件后，生产忽略
    清单里真的多了一条 `电视剧:a.mkv`（`created_by=Web`、`source=strm_dashboard`），
    用户随后收到「上传失败自动重试已停止」告警时还以为是测试数据没清干净。

    根因：mock 的实例帮不上忙（要测的就是真实实例），但可以选择**把持久化
    与台账都指向 tmp_path**。`_ignored_rules` 是普通列表，`save_data`/
    `get_data` 换成内存字典，`_ledger` 指向 tmp 下的 sqlite —— 真实代码路径
    全走，落盘目标全隔离。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    store = importlib.import_module("app.plugins.rsync115sync.store")
    plugin = module.Rsync115Sync()
    # ---- 隔离持久化：任何 save_data/get_data 都落在本用例的字典里 ----
    saved: dict = {}
    plugin.save_data = lambda k, v, *a, **kw: saved.__setitem__(k, v)
    plugin.get_data = lambda k, *a, **kw: saved.get(k)
    plugin.del_data = lambda k, *a, **kw: saved.pop(k, None)
    plugin._ledger = store.Store(os.path.join(str(tmp_path), "ledger.sqlite3"))
    plugin._strm_suspects = store.LedgerMapping(
        plugin._ledger, store.STATUS_SUSPECT, ts_field="verified_at",
        extra_from_value={"origin": "origin"})
    plugin._strm_watch = store.LedgerMapping(
        plugin._ledger, store.STATUS_PENDING_VERIFY, ts_field="enqueued_at")
    plugin._strm_gen_requested = store.LedgerFieldMap(
        plugin._ledger, "gen_requested_at")
    plugin._pending_queue = store.LedgerMapping(
        plugin._ledger, store.STATUS_CANDIDATE, ts_field="enqueued_at")
    plugin._failed_files = store.LedgerMapping(
        plugin._ledger, store.STATUS_FAILED, ts_field="verified_at",
        extra_from_value={"reason": "fail_reason", "count": "retry_count",
                          "exhausted_at": "exhausted_at"})
    plugin._ignored_rules = []
    plugin._last_status = {"missing_files": [], "corrupt_files": []}
    plugin._strm_notified = False
    # 类体别名是承重的（8.5 节）
    # 注：`_MISSED_SCAN_*` 已随源端补齐扫描一起被 `_SOURCE_SCAN_*` 取代
    # （2026-09-25），别名同步更名 —— 这条断言的价值正在于它会跟着旧名字一起
    # 失败，提醒改名时要更新这处清单，而不是悄悄地少断言一项。
    for attr in ("_SOURCE_SCAN_ENABLED_DEFAULT", "_SOURCE_SCAN_CRON_DEFAULT",
                 "_SOURCE_SCAN_INTERVAL_LEGACY_DEFAULT",
                 "_SOURCE_CURSOR_OVERLAP_SECS", "_LEGACY_DEFAULTS",
                 "_LEGACY_DEFAULTS_ALL", "_TOLERATED_EXIT_CODES", "_SIDECAR_EXTS"):
        assert hasattr(plugin, attr), f"实例缺少类体别名 {attr}"
    # 关键路径跑一次（落点全在 tmp_path / saved 里）
    plugin._strm_suspects["电视剧:a.mkv"] = {"dest": "ok"}
    res = plugin._api_strm_ignore({"keys": ["电视剧:a.mkv"]})
    assert res["success"] is True
    assert "电视剧:a.mkv" not in plugin._strm_suspects
    # 反向保护：这条规则确实写进了**本用例的**存储，而不是生产的
    assert any(r.get("rule") == "电视剧:a.mkv"
               for r in saved.get("ignored_files", [])), (
        "忽略规则没有落到隔离存储 —— 说明持久化仍指向生产")
