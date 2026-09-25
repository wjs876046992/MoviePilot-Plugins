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


# --------------------------------------------------------------------------
# 源端扫描节奏：cron 表达式（2026-09-25 从"间隔秒数"改来）
# --------------------------------------------------------------------------

def test_source_scan_uses_cron_trigger():
    """
    扫描 service 必须用 **CronTrigger**，且表达式来自配置。

    ⚠️ 原先这里是 `IntervalTrigger(seconds=...)`。改动理由：固定间隔表达不了
    "只在夜里扫"这类需求，而大库的整树遍历有成本；cron 在本插件另一处
    （定时检查）已被用户熟悉。这条用例钉住"触发器类型"这一层 ——
    只断言"表达式出现在源码里"会漏掉"用 IntervalTrigger 去接一个 cron 字符串"
    这种写法（那会静默抛错或退化成默认节奏）。
    """
    src = _method_source("get_service")
    assert "CronTrigger.from_crontab" in src, (
        "源端扫描 service 必须用 CronTrigger.from_crontab（cron 表达式），"
        "不是 IntervalTrigger(seconds=...)"
    )
    assert "self._source_scan_cron" in src, "cron 表达式必须来自配置"


def test_source_scan_interval_legacy_key_is_migrated():
    """
    旧配置 `source_scan_interval`（秒）必须被换算，而不是静默丢弃。

    老用户升级后若静默回落到默认 10 分钟，表现是"扫描节奏突然变了" ——
    对把间隔调大到 1 小时的用户，等于凭空多出 6 倍的目录遍历。
    """
    # ⚠️ 断言里不要绑引号样式：`ast.unparse` 输出的是单引号，而源码里是双引号。
    # 第一版就是这么写错的，结果一条正确的实现对它报了假红 —— 与 §4.0f 里
    # 那两条"grep 命中注释"的哨兵同源：**断言应针对语义，不针对表面格式**。
    src = _method_source("_read_source_scan_cron")
    assert "source_scan_interval" in src, (
        "必须读取旧的 source_scan_interval 并换算，否则老用户升级后节奏静默变化"
    )
    assert "source_scan_cron" in src, "新键必须优先于旧键"


def test_grace_unit_is_minutes_everywhere():
    """
    宽限期的单位是**分钟**，且旧键（小时）不得被静默换算。

    单位改动是这类配置里最容易出错的一种：同一个 `6` 从小时变分钟会把 6 小时
    的需求悄悄变成 6 分钟 —— 而 6 分钟正是最坏的表现（strm 还没生成就大面积
    误报"疑似上传异常"，用户随后开始无视这个功能）。
    因此代码里必须能找到"明确提示旧键已废弃"的处理，且新状态字段叫 minutes。
    """
    src = SOURCE
    assert "_strm_grace_minutes" in src, "状态字段必须叫 _strm_grace_minutes"
    assert "self._strm_grace_hours" not in src, (
        "不得再存在 _strm_grace_hours —— 单位已改为分钟"
    )
    assert "_warn_on_legacy_grace_unit" in src, (
        "必须显式提示旧的 strm_grace_hours 已废弃，不能静默换个单位解释同一个数"
    )


def test_grace_zero_is_clamped_not_defaulted():
    """
    `strm_grace_minutes` 填 0 应夹到下限（1），而**不是**回落到默认（5）。

    区别看着小、方向是反的：用户填 0 表达的是"越小越好"，回落到 5 给了他一个
    比意图大 5 倍的值，而屏幕上那个输入框显示的正是他自己填的 0。
    这类 `config.get(k) or default` 吞掉 0 的写法在本项目已出现过多次，
    所以单独钉一条。
    """
    src = _method_source("_read_grace_minutes")
    # ⚠️ 这条断言踩过两次坑，都值得记下来：
    #   1. 不能按"函数体里有没有 `or`"判 —— `raw is None or raw == ''` 是**正确的**
    #      缺失判定，它自己就含 `or`；
    #   2. 不能按"哪一行含 config.get(" 判 —— `ast.unparse` **包含 docstring**，
    #      而 docstring 里正好在解释"不要用 `config.get(k) or default`"，
    #      于是第一个匹配到的是**注释里的反例**。
    # 这与 §4.0f 里那两条"grep 源码命中注释"的哨兵是同一类错误。
    # 正确做法：**精确定位赋值语句本身**。
    #   ❌  int(config.get("strm_grace_minutes") or 5)      ← 0 变成 5
    #   ✅  raw = config.get("strm_grace_minutes")          ← 0 保留，随后夹到 1
    assign = [ln.strip() for ln in src.splitlines() if ln.strip().startswith("raw =")]
    assert assign, "未找到 `raw = ...` 取值行"
    assert " or " not in assign[0], (
        f"读取宽限期的取值语句不得用 `... or default`（实际：{assign[0]}）—— "
        "它会把显式的 0 与'没填'当成同一件事"
    )
    assert "MIN_GRACE_MINUTES" in src, "填 0 必须夹到下限，而不是回落到默认"
