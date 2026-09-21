"""
配置保存后必须让**运行时**跟着变，而不只是写进数据库。

Tests that saving config actually takes effect at runtime, not merely in storage.

**为什么需要这组测试**：宿主有两条保存路径，只有一条会重建调度 ——
`PUT /plugin/{id}` 会调 `refresh_registrations()`，而插件自己的
`POST /plugin/<id>/config` 不会。配置页用的正是后者，于是「cron 改成每 5 分钟」
只会写库，APScheduler 里跑的还是旧表达式，表现为「再也看不到执行日志」。
这类问题没有任何报错，只能靠契约测试拦。
"""

import ast
from pathlib import Path

import pytest


def _plugin_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "plugins.v3" / "rsync115sync" / "__init__.py"
        if candidate.is_file():
            return candidate.parent
    try:
        import importlib
        return Path(importlib.import_module("app.plugins.rsync115sync").__file__).parent
    except Exception:
        pytest.skip("未找到插件源码目录")


PLUGIN_DIR = _plugin_dir()
SOURCE = (PLUGIN_DIR / "__init__.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef))


def _method(name):
    for m in CLASS.body:
        if isinstance(m, ast.FunctionDef) and m.name == name:
            return m
    raise AssertionError(f"缺少方法 {name}")


def _method_source(name) -> str:
    return ast.unparse(_method(name))


def test_save_config_refreshes_scheduler_job():
    """保存配置必须重建定时任务，否则 cron 改动只在数据库里生效。"""
    src = _method_source("_api_save_config")
    assert "_refresh_scheduled_job" in src, (
        "_api_save_config 未调用 _refresh_scheduled_job："
        "改 cron 后 APScheduler 仍跑旧表达式，用户看不到任何执行日志。"
    )


def test_refresh_calls_host_sdk_facade():
    """必须调用宿主公开的 SDK 门面，而不是内部模块。"""
    src = _method_source("_refresh_scheduled_job")
    assert "_update_plugin_job" in src
    assert "app.sdk.scheduler" in SOURCE, "应使用 app.sdk.scheduler 公开门面"
    # 不得深入宿主内部模块
    for forbidden in ("app.application.scheduling", "app.scheduler."):
        assert f"from {forbidden}" not in SOURCE, f"不得导入宿主内部模块 {forbidden}"


def test_scheduler_import_failure_is_tolerated():
    """
    旧宿主可能没有该 SDK；导入失败只能降级，不能让插件加载失败。
    """
    assert "_update_plugin_job = None" in SOURCE, "导入失败应有 None 降级分支"
    start = SOURCE.index("from app.sdk.scheduler import")
    context = SOURCE[max(0, start - 400):start + 100]
    assert "except Exception" in context, "SDK 导入必须被 try/except 包住"


def test_save_config_reports_refresh_failure_without_failing_save():
    """
    配置已保存成功、仅调度重建失败时，不能把整体判为失败 ——
    否则用户会重复保存，也无从知道「其实已经存进去了」。
    """
    src = _method_source("_api_save_config")
    assert "success" in src and "True" in src
    assert "重载插件" in src, "失败时应提示用户手动重载"


def test_get_service_registers_cron_trigger():
    """定时服务的注册结构必须符合宿主的服务合同（trigger/func/kwargs）。"""
    src = _method_source("get_service")
    # 注意：ast.unparse 会把字符串统一成单引号，断言不能写死引号形态
    for key in ("trigger", "func", "kwargs", "id", "name"):
        assert f"'{key}'" in src or f'"{key}"' in src, f"服务定义缺少 {key} 字段"
    assert "CronTrigger.from_crontab" in src, "cron 表达式必须转成触发器"
    assert "_scheduled_sync" in src, "服务应指向 _scheduled_sync"


def test_get_service_requires_enabled():
    """插件被停用时不得注册定时任务，否则停用形同虚设。"""
    src = _method_source("get_service")
    assert "_enabled" in src, "get_service 必须检查 _enabled"
    assert "_cron" in src, "get_service 必须检查 _cron 非空"


def test_service_registration_errors_are_caught():
    """cron 表达式非法时不得抛出到宿主（会让整个服务注册失败）。"""
    src = _method_source("get_service")
    assert "except" in src, "CronTrigger 解析必须兜底"
