"""生活事件合并通知：计数与正文渲染单测。

背景：生活事件通知原来只说「生成STRM文件 N 个」，N=1 时用户无从知道是哪个文件。
现在正文会列出文件路径，但大目录事件可能一次展开上千个文件，所以「计数」和
「展示条数」必须分开：计数照常累加，路径只保留前若干条，其余折成一行汇总。

这些用例锁住三条边界：
1. 少量文件时逐条列出，不出现汇总行；
2. 超过展示上限时只列前 N 条，并准确报出省略数量；
3. 批量场景下 ``count`` 大于实际传入的路径数时，汇总行按 ``count`` 计算。
"""

import importlib.util
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugins.v3" / "p115strmhelper"
MODULE_PATH = PLUGIN_DIR / "helper" / "life" / "notification.py"


def _load_module():
    """按文件路径加载通知模块，避开插件的宿主依赖。"""
    spec = importlib.util.spec_from_file_location(
        "p115strmhelper_life_notification", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


notification = _load_module()


def test_empty_batch_renders_nothing():
    """没有事件时不生成正文，调用方据此跳过推送。"""
    batch = notification.NotificationBatch()
    assert batch.empty
    assert batch.render() == ""


def test_single_file_is_listed_by_path():
    """单个文件时正文要带出完整路径，而不只是数量。"""
    batch = notification.NotificationBatch()
    batch.add_one("strm_items", "/media/动画/灵境行者/Season 1/E01.strm")
    assert not batch.empty
    assert batch.render() == (
        "📄 生成STRM文件 1 个\n  - /media/动画/灵境行者/Season 1/E01.strm"
    )


def test_items_over_limit_are_summarised():
    """超过展示上限时只列前 N 条，其余折成一行并给出准确数量。"""
    batch = notification.NotificationBatch(item_limit=3)
    for index in range(5):
        batch.add_one("strm_items", f"/media/S01E{index:02d}.strm")
    lines = batch.render().splitlines()
    assert lines[0] == "📄 生成STRM文件 5 个"
    assert len(lines) == 1 + 3 + 1
    assert lines[-1] == "  ... 还有 2 个"


def test_bulk_count_can_exceed_listed_paths():
    """批量事件只收集了少量路径，但计数仍按真实处理数量展示。"""
    batch = notification.NotificationBatch(item_limit=2)
    batch.add("strm_items", ["/media/a.strm", "/media/b.strm"], count=500)
    lines = batch.render().splitlines()
    assert lines[0] == "📄 生成STRM文件 500 个"
    assert lines[-1] == "  ... 还有 498 个"


def test_both_buckets_render_in_order():
    """STRM 与媒体文件两个类别同时存在时按固定顺序输出。"""
    batch = notification.NotificationBatch()
    batch.add_one("strm_items", "/media/a.strm")
    batch.add_one("mediainfo_items", "/media/a.nfo")
    lines = batch.render().splitlines()
    assert lines[0].startswith("📄 生成STRM文件 1 个")
    assert lines[1] == "  - /media/a.strm"
    assert lines[2].startswith("⬇️ 下载媒体文件 1 个")
    assert lines[3] == "  - /media/a.nfo"


def test_limit_of_zero_still_counts():
    """展示上限为 0 时只剩数量与汇总行，不至于丢失计数。"""
    batch = notification.NotificationBatch(item_limit=0)
    batch.add_one("strm_items", "/media/a.strm")
    assert batch.render() == "📄 生成STRM文件 1 个\n  ... 还有 1 个"


def test_unknown_bucket_is_rejected():
    """未知类别直接报错，避免静默丢弃本该通知的内容。"""
    batch = notification.NotificationBatch()
    try:
        batch.add("bogus", ["/media/a.strm"])
    except ValueError as error:
        assert "bogus" in str(error)
    else:  # pragma: no cover - 只有实现回退时才走到这里
        raise AssertionError("未知类别应抛出 ValueError")
