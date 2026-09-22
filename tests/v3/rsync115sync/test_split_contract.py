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
    for name in ("strm_ops", "sync_ops", "commands"):
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
        "on_transfer_complete", "handle_command",
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


def test_instantiation_smoke():
    """真实实例化 + 关键路径冒烟（8.5 节：只有实例化才能发现 AttributeError）。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = module.Rsync115Sync()
    # 类体别名是承重的（8.5 节）
    for attr in ("_MISSED_SCAN_ENABLED_DEFAULT", "_LEGACY_DEFAULTS",
                 "_MISSED_SCAN_INTERVAL", "_TOLERATED_EXIT_CODES", "_SIDECAR_EXTS"):
        assert hasattr(plugin, attr), f"实例缺少类体别名 {attr}"
    # 关键路径跑一次
    plugin._strm_suspects["电视剧:a.mkv"] = {"dest": "ok"}
    res = plugin._api_strm_ignore({"keys": ["电视剧:a.mkv"]})
    assert res["success"] is True
    assert "电视剧:a.mkv" not in plugin._strm_suspects
