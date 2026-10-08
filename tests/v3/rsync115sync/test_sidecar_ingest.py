"""
入库伴生外挂字幕与同级文件联动补偿测试。

验证：
1. 普通映射下，扫描或 Webhook 发现视频文件时，同目录同主名的伴生外挂字幕（.srt/.ass 等）
   自动一并入队，即使字幕文件的 mtime 较旧；
2. 伴生外挂字幕的冷却基准时间强制继承主媒体视频，保证同一批冷却结束并一同上传；
3. 同目录下的其他集（如 ep2.mkv）绝不会被顺手拉入（杜绝整季连坐）；
4. 被忽略规则命中的伴生字幕安全跳过；
5. all_ext 映射下同级兄弟文件一并继承主媒体的冷却基准时间。
"""

import os
import sys
import time
import types
from pathlib import Path
import pytest

# 构造无宿主环境桩
for mod in [
    "app", "app.core", "app.core.event", "app.plugins", "app.sdk",
    "app.sdk.logging", "app.schemas", "app.schemas.types",
    "app.schemas.mediaserver", "app.sdk.scheduler", "app.sdk.plugins",
    "apscheduler", "apscheduler.triggers", "apscheduler.triggers.cron"
]:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)

sys.modules["app.plugins"]._PluginBase = object
sys.modules["app.core.event"].Event = object
sys.modules["app.core.event"].EventType = types.SimpleNamespace(
    CommandExcute=1, PluginReload=2, MessageAction=3, PluginAction=4,
    TransferComplete=5, SubtitleTransferComplete=6, AudioTransferComplete=7,
    WebhookMessage=8
)
sys.modules["app.core.event"].eventmanager = types.SimpleNamespace(
    send_event=lambda *a, **kw: None,
    register=lambda *a, **kw: (lambda fn: fn)
)
sys.modules["app.sdk.logging"].logger = types.SimpleNamespace(
    info=lambda *a, **kw: None, debug=lambda *a, **kw: None,
    warning=lambda *a, **kw: None, error=lambda *a, **kw: None
)
sys.modules["apscheduler.triggers.cron"].CronTrigger = object

import importlib.util
_plugin_dir = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                 "plugins.v3", "rsync115sync")
)
_pkg_name = "rsync115sync_test_pkg"
_pkg = types.ModuleType(_pkg_name)
_pkg.__path__ = [_plugin_dir]
_pkg.__file__ = os.path.join(_plugin_dir, "__init__.py")
sys.modules[_pkg_name] = _pkg

_spec = importlib.util.spec_from_file_location(
    _pkg_name, _pkg.__file__, submodule_search_locations=[_plugin_dir]
)
_mod = importlib.util.module_from_spec(_spec)
_mod.__package__ = _pkg_name
sys.modules[_pkg_name] = _mod
_spec.loader.exec_module(_mod)

Rsync115Sync = _mod.Rsync115Sync
_is_video_file = _mod._is_video_file


def _create_plugin(src_dir, all_ext=False, delay_hours=2.0, ignore_rules=None):
    plugin = Rsync115Sync.__new__(Rsync115Sync)
    plugin.plugin_version = "0.5.1-test"
    plugin._enabled = True
    plugin._listen_transfer = True
    plugin._sync_pairs = [{
        "name": "电视剧",
        "src": str(src_dir),
        "dest": "/dest/TV",
        "all_ext": all_ext,
        "strm_dir": ""
    }]
    plugin._media_extensions = Rsync115Sync.DEFAULT_MEDIA_EXTENSIONS
    plugin._delay_hours = delay_hours
    plugin._pending_queue = {}
    plugin._ignored_rules = list(ignore_rules or [])
    plugin._source_cursor = {}
    plugin.save_data = lambda *a, **kw: None
    return plugin


def test_is_video_file_predicate():
    assert _is_video_file("test.mkv") is True
    assert _is_video_file("test.mp4") is True
    assert _is_video_file("test.ts") is True
    assert _is_video_file("test.zh.srt") is False
    assert _is_video_file("test.ass") is False
    assert _is_video_file("test.nfo") is False
    assert _is_video_file("test.jpg") is False


def test_video_ingest_attaches_same_stem_sidecar_subtitles(tmp_path):
    """主媒体入库时，同目录同主名的伴生外挂字幕（即使 mtime 很早）自动联动入队。"""
    src_dir = tmp_path / "TV"
    show_dir = src_dir / "国产剧" / "测试剧" / "Season 01"
    show_dir.mkdir(parents=True)

    video = show_dir / "测试剧 S01E01.mkv"
    video.write_text("video")
    sub1 = show_dir / "测试剧 S01E01.zh.srt"
    sub1.write_text("sub1")
    sub2 = show_dir / "测试剧 S01E01.ass"
    sub2.write_text("sub2")

    # 另一集及其字幕，绝不应被连坐拉入
    other_video = show_dir / "测试剧 S01E02.mkv"
    other_video.write_text("video2")
    other_sub = show_dir / "测试剧 S01E02.zh.srt"
    other_sub.write_text("sub_other")

    # 模拟伴生字幕文件 mtime 停留在很早之前（例如做种时的旧时间戳）
    old_time = time.time() - 86400
    os.utime(str(sub1), (old_time, old_time))
    os.utime(str(sub2), (old_time, old_time))

    plugin = _create_plugin(src_dir, all_ext=False)

    # 模拟定时扫描只发现了视频文件 E01
    counts = plugin._enqueue_ingest_paths([str(video)], source="源端扫描", from_scan=True, event_desc="测试")

    # E01 视频 + 两个伴生字幕均应入队（总计 3 个）
    assert counts["added"] == 3

    key_video = "电视剧:国产剧/测试剧/Season 01/测试剧 S01E01.mkv"
    key_sub1 = "电视剧:国产剧/测试剧/Season 01/测试剧 S01E01.zh.srt"
    key_sub2 = "电视剧:国产剧/测试剧/Season 01/测试剧 S01E01.ass"
    key_other_video = "电视剧:国产剧/测试剧/Season 01/测试剧 S01E02.mkv"

    assert key_video in plugin._pending_queue
    assert key_sub1 in plugin._pending_queue
    assert key_sub2 in plugin._pending_queue
    assert key_other_video not in plugin._pending_queue, "其他集被误拉入队列（整季连坐）"

    # 验证冷却基准对齐：伴生字幕必须继承主视频的冷却基准，不能因自身旧 mtime 提前到期
    video_basis = plugin._pending_queue[key_video]
    assert plugin._pending_queue[key_sub1] == video_basis
    assert plugin._pending_queue[key_sub2] == video_basis


def test_ignored_sidecar_is_skipped(tmp_path):
    """如果伴生字幕被忽略规则命中，安全跳过，不强行入队。"""
    src_dir = tmp_path / "TV"
    show_dir = src_dir / "国产剧" / "Season 01"
    show_dir.mkdir(parents=True)

    video = show_dir / "ep.mkv"
    video.write_text("video")
    sub = show_dir / "ep.zh.srt"
    sub.write_text("sub")

    ignored_rule = "电视剧:国产剧/Season 01/ep.zh.srt"
    plugin = _create_plugin(src_dir, all_ext=False, ignore_rules=[{"rule": ignored_rule, "match": "exact"}])

    counts = plugin._enqueue_ingest_paths([str(video)], source="源端扫描", from_scan=True, event_desc="测试")
    assert counts["added"] == 1
    assert "电视剧:国产剧/Season 01/ep.mkv" in plugin._pending_queue
    assert ignored_rule not in plugin._pending_queue


def test_standalone_subtitle_does_not_trigger_sidecar_search(tmp_path):
    """独立入库的字幕文件（如用户单独后补）自身入队，不触发反向搜索。"""
    src_dir = tmp_path / "TV"
    show_dir = src_dir / "国产剧" / "Season 01"
    show_dir.mkdir(parents=True)

    sub = show_dir / "ep.zh.srt"
    sub.write_text("sub")

    plugin = _create_plugin(src_dir, all_ext=False)
    counts = plugin._enqueue_ingest_paths([str(sub)], source="源端扫描", from_scan=True, event_desc="测试")
    assert counts["added"] == 1
    assert "电视剧:国产剧/Season 01/ep.zh.srt" in plugin._pending_queue


def test_all_ext_siblings_inherit_main_basis(tmp_path):
    """all_ext 映射下，同目录下的所有同级文件（nfo, jpg 等）继承主视频的冷却基准。"""
    src_dir = tmp_path / "9KG"
    media_dir = src_dir / "MovieA"
    media_dir.mkdir(parents=True)

    video = media_dir / "movie.mp4"
    video.write_text("mp4")
    nfo = media_dir / "movie.nfo"
    nfo.write_text("nfo")
    jpg = media_dir / "poster.jpg"
    jpg.write_text("jpg")

    # 附属文件时间戳早于当前
    old_time = time.time() - 3600
    os.utime(str(nfo), (old_time, old_time))
    os.utime(str(jpg), (old_time, old_time))

    plugin = _create_plugin(src_dir, all_ext=True)
    plugin._sync_pairs[0]["name"] = "9KG"

    counts = plugin._enqueue_ingest_paths([str(video)], source="源端扫描", from_scan=True, event_desc="测试")
    assert counts["added"] == 3

    key_video = "9KG:MovieA/movie.mp4"
    key_nfo = "9KG:MovieA/movie.nfo"
    key_jpg = "9KG:MovieA/poster.jpg"

    assert key_video in plugin._pending_queue
    assert key_nfo in plugin._pending_queue
    assert key_jpg in plugin._pending_queue

    main_basis = plugin._pending_queue[key_video]
    assert plugin._pending_queue[key_nfo] == main_basis
    assert plugin._pending_queue[key_jpg] == main_basis
