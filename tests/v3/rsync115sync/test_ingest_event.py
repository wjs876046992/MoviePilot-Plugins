"""
入库事件处理单测：整理完成后哪些文件会进入冷却队列。

Tests for ingest-event handling — the entry point of the whole sync chain. If a
file fails to enqueue here it is never uploaded, and nothing anywhere reports an
error: the file simply never appears. That silence is why these cases matter.
"""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.plugins.rsync115sync import Rsync115Sync


def _plugin(src_root, *, delay_hours=2.0, media_extensions="mkv,srt",
            all_ext=False, pair_name="TV"):
    """构造只带事件处理所需状态的最小实例。"""
    plugin = Rsync115Sync.__new__(Rsync115Sync)
    plugin.plugin_version = "test"
    plugin._enabled = True
    plugin._listen_transfer = True
    plugin._delay_hours = delay_hours
    plugin._media_extensions = media_extensions
    plugin._sync_pairs = [{
        "name": pair_name, "src": src_root, "dest": "/dest/TV",
        "all_ext": all_ext, "strm_dir": "",
    }]
    plugin._pending_queue = {}
    plugin._missed_queue = {}
    plugin._ignored_rules = []
    plugin._last_status = {}
    plugin.saved = {}
    plugin.save_data = lambda k, v: plugin.saved.__setitem__(k, v)
    return plugin


def _event(paths, *, field="file_list_new"):
    """构造一个带 TransferComplete 形状 payload 的事件对象。"""
    transfer = SimpleNamespace()
    setattr(transfer, field, paths)
    return SimpleNamespace(
        event_type=SimpleNamespace(value="transfer.complete"),
        event_data={"transferinfo": transfer},
    )


# --------------------------------------------------------------------------
# 基本入队
# --------------------------------------------------------------------------

def test_existing_media_file_is_enqueued(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "S01E01.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._handle_transfer_event(_event([str(f)]))

    assert list(plugin._pending_queue) == ["TV:S01E01.mkv"]
    assert plugin.saved.get("pending_queue") == plugin._pending_queue


def test_nested_path_is_stored_relative_to_src(tmp_path):
    """队列 key 用**相对路径**，绝对路径在不同容器/挂载下不通用。"""
    src = tmp_path / "TV"
    (src / "剧集" / "Season 01").mkdir(parents=True)
    f = src / "剧集" / "Season 01" / "S01E03.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._handle_transfer_event(_event([str(f)]))

    assert list(plugin._pending_queue) == ["TV:剧集/Season 01/S01E03.mkv"]


def test_extension_filter_skips_non_media(tmp_path):
    """.nfo/.jpg 等不在扩展名白名单内的文件不入队（同步它们无意义且浪费配额）。"""
    src = tmp_path / "TV"
    src.mkdir()
    mkv = src / "a.mkv"
    nfo = src / "a.nfo"
    mkv.write_bytes(b"x")
    nfo.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._handle_transfer_event(_event([str(mkv), str(nfo)]))

    assert list(plugin._pending_queue) == ["TV:a.mkv"]


def test_all_ext_pair_enqueues_every_extension(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    nfo = src / "a.nfo"
    nfo.write_bytes(b"x")

    plugin = _plugin(str(src), all_ext=True)
    plugin._handle_transfer_event(_event([str(nfo)]))

    assert list(plugin._pending_queue) == ["TV:a.nfo"]


def test_subtitle_extension_is_enqueued(tmp_path):
    """字幕必须入队：冷却期的设计目的就是「等外挂字幕下载完再上传」。"""
    src = tmp_path / "TV"
    src.mkdir()
    srt = src / "S01E01.zh.srt"
    srt.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._handle_transfer_event(_event([str(srt)]))

    assert list(plugin._pending_queue) == ["TV:S01E01.zh.srt"]


# --------------------------------------------------------------------------
# 映射归属（决定「会不会被同步」）
# --------------------------------------------------------------------------

def test_path_outside_any_mapping_is_not_enqueued(tmp_path):
    """下载器源路径通常不在媒体库映射内，绝不能错误入队。"""
    src = tmp_path / "TV"
    src.mkdir()
    other = tmp_path / "downloads" / "a.mkv"
    other.parent.mkdir()
    other.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._handle_transfer_event(_event([str(other)]))

    assert plugin._pending_queue == {}


def test_sibling_prefix_is_not_attributed_to_wrong_mapping(tmp_path):
    """
    关键回归：`/media/TV` 不得吞掉 `/media/TV2/...`。

    一旦归属错映射，文件会被上传到**另一个** 115 目标目录 —— 静默的破坏性后果。
    """
    tv = tmp_path / "TV"
    tv2 = tmp_path / "TV2"
    tv.mkdir()
    tv2.mkdir()
    f = tv2 / "a.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(tv))
    plugin._handle_transfer_event(_event([str(f)]))

    assert plugin._pending_queue == {}


def test_file_owned_by_mapping_but_unreadable_is_not_enqueued(tmp_path):
    """路径前缀匹配但容器内读不到（宿主/容器挂载不一致）→ 不入队。"""
    src = tmp_path / "TV"
    src.mkdir()

    plugin = _plugin(str(src))
    plugin._handle_transfer_event(_event([str(src / "不存在的文件.mkv")]))

    assert plugin._pending_queue == {}


# --------------------------------------------------------------------------
# 幂等（事件走 durable outbox，at-least-once）
# --------------------------------------------------------------------------

def test_duplicate_delivery_keeps_original_timestamp(tmp_path):
    """
    重复投递**不得刷新冷却计时**。

    若无条件覆盖时间戳，每次重投都会把冷却重新计时，表现为
    「明明是 1 小时前入库的文件，冷却永远走不完、永远不同步」。
    """
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    with patch("app.plugins.rsync115sync.time.time", return_value=1000.0):
        plugin._handle_transfer_event(_event([str(f)]))
    first_ts = plugin._pending_queue["TV:a.mkv"]

    with patch("app.plugins.rsync115sync.time.time", return_value=9999.0):
        plugin._handle_transfer_event(_event([str(f)]))

    assert plugin._pending_queue["TV:a.mkv"] == first_ts == 1000.0


def test_enqueue_clears_entry_from_missed_queue(tmp_path):
    """事件补上后要从「错过待补扫」清单移除，否则下一轮会被重复判定。"""
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._missed_queue = {"TV:a.mkv": 1.0}
    plugin._handle_transfer_event(_event([str(f)]))

    assert plugin._missed_queue == {}


def test_multiple_files_in_one_event_all_enqueued(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    files = []
    for i in range(3):
        p = src / f"e{i}.mkv"
        p.write_bytes(b"x")
        files.append(str(p))

    plugin = _plugin(str(src))
    plugin._handle_transfer_event(_event(files))

    assert sorted(plugin._pending_queue) == ["TV:e0.mkv", "TV:e1.mkv", "TV:e2.mkv"]


# --------------------------------------------------------------------------
# 路径来源回退（file_list_new 可能为空：宿主 28 个构造点里 25 个不赋值）
# --------------------------------------------------------------------------

def test_falls_back_to_file_list_when_file_list_new_empty(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._handle_transfer_event(_event([str(f)], field="file_list"))

    assert list(plugin._pending_queue) == ["TV:a.mkv"]


def test_falls_back_to_fileitem_path(tmp_path):
    """
    最终兜底：fileitem.path 是**下载器源路径**，通常不在映射内，
    因此这条路径多半不会入队 —— 但不该抛异常，也不该错误入队。
    """
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")

    transfer = SimpleNamespace(file_list_new=[], file_list=[])
    event = SimpleNamespace(
        event_type=SimpleNamespace(value="transfer.complete"),
        event_data={"transferinfo": transfer, "fileitem": SimpleNamespace(path=str(f))},
    )
    plugin = _plugin(str(src))
    plugin._handle_transfer_event(event)

    assert list(plugin._pending_queue) == ["TV:a.mkv"]


def test_downloader_source_path_outside_mapping_is_ignored(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    outside = tmp_path / "downloads" / "a.mkv"
    outside.parent.mkdir()
    outside.write_bytes(b"x")

    transfer = SimpleNamespace(file_list_new=[], file_list=[])
    event = SimpleNamespace(
        event_type=SimpleNamespace(value="transfer.complete"),
        event_data={"transferinfo": transfer, "fileitem": SimpleNamespace(path=str(outside))},
    )
    plugin = _plugin(str(src))
    plugin._handle_transfer_event(event)

    assert plugin._pending_queue == {}


# --------------------------------------------------------------------------
# 守卫：缺 payload / 开关关闭
# --------------------------------------------------------------------------

def test_missing_transferinfo_is_ignored_silently(tmp_path):
    """没有 transferinfo 时不得抛异常：宿主在线程池里跑处理器，异常会被记为插件错误。"""
    plugin = _plugin(str(tmp_path))
    plugin._handle_transfer_event(SimpleNamespace(
        event_type=SimpleNamespace(value="transfer.complete"), event_data={}))

    assert plugin._pending_queue == {}


def test_disabled_plugin_does_not_enqueue(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._enabled = False
    plugin._handle_transfer_event(_event([str(f)]))

    assert plugin._pending_queue == {}


def test_listen_transfer_off_does_not_enqueue(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._listen_transfer = False
    plugin._handle_transfer_event(_event([str(f)]))

    assert plugin._pending_queue == {}


def test_empty_path_entries_are_skipped(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._handle_transfer_event(_event(["", None, str(f)]))

    assert list(plugin._pending_queue) == ["TV:a.mkv"]
