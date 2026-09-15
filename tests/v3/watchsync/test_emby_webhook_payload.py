"""WatchSync V3 插件：真实 Emby webhook 载荷契约单测。

用例里的两份载荷都来自线上同一个播放会话（Emby 4.9.5.0 → MoviePilot），用来把插件对
真实载荷形态的假设钉住：

- ``EMBY_PLAYBACK_START``（``playback.start``）：播放位置只出现在
  ``PlaybackInfo.PositionTicks``，``Session`` 里**没有**这个字段。事件指纹与播放处理都
  依赖这条回退，任何一处删掉回退都会让去重/进度同步静默退化；
- ``playback.start`` 不是同步触发点（同步发生在 pause / stop），这类事件不得产生同步；
- ``EMBY_PLAYBACK_STOP``（``playback.stop``）：用户看了 2 秒就停，Emby **既不发
  ``Session.PositionTicks`` 也不发 ``PlayDurationTicks``**，于是时长门槛实际是拿
  **最终播放位置**去比 ``min_watch_time`` —— 这是非显然的行为，容易被误当成 bug；
- 两份载荷的 ``Item.ProviderIds`` 都为空，即 Emby 侧拿不到 Tmdb 号，匹配只能退回按名称
  搜索 —— 这是模糊匹配链路的真实前提。

为控制篇幅，去掉了载荷中插件不读取的 ``MediaStreams`` 数组，其余字段与线上一致。
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any, Optional

from app.plugins.watchsync import SyncLoopProtector, WatchSync

EMBY_PLAYBACK_START: dict[str, Any] = {
    "Title": "strm 在 Mac 上开始播放 杀手妈咪 - S1, Ep13 - 第 13 集",
    "Date": "2026-09-15T05:38:26.6705894Z",
    "Event": "playback.start",
    "Severity": "Info",
    "User": {"Name": "strm", "Id": "57b7904db33348f08fa6353bd0ff32ba"},
    "Item": {
        "Name": "第 13 集",
        "ServerId": "707a947126f84de5a227863ac85e1c4e",
        "Id": "96838",
        "DateCreated": "2026-09-12T18:41:42.0000000Z",
        "DateModified": "2026-09-12T18:41:42.0000000Z",
        "PresentationUniqueKey": "464930-zh-CN-a0ce65a0e27a4abe81e6dd566afe63ff-001 - 0013",
        "Container": "mkv",
        "PremiereDate": "2026-09-11T00:00:00.0000000Z",
        "ExternalUrls": [],
        "Path": (
            "/data/HomeTheater/strms/TV/日韩剧/杀手妈咪 (2026) {tmdbid=294095}"
            "/Season 01/杀手妈咪 S01E13.WEB-DL.1080p.H264.AAC 2.0.strm"
        ),
        "Overview": (
            "A new murder case occurs, and it confuses the police, but they are sure that it "
            "was done by Kingfisher. Bo-na realizes she's framed, and the real culprit is "
            "Leila, her old colleague who is resentful toward Bo-na for past condemnation. "
            "The appearance of Leila makes Bo-na fearful for her family’s safety."
        ),
        "Taglines": [],
        "Genres": [],
        "RunTimeTicks": 38578540000,
        "Size": 4732939567,
        "FileName": "杀手妈咪 S01E13.WEB-DL.1080p.H264.AAC 2.0.strm",
        "Bitrate": 9814657,
        "ProductionYear": 2026,
        "IndexNumber": 13,
        "ParentIndexNumber": 1,
        "ProviderIds": {},
        "IsFolder": False,
        "ParentId": "92586",
        "Type": "Episode",
        "Studios": [],
        "GenreItems": [],
        "ParentLogoItemId": "92585",
        "ParentBackdropItemId": "92585",
        "ParentBackdropImageTags": ["1b26fa81ce1d692eb971da7ca3ad9481"],
        "SeriesName": "杀手妈咪",
        "SeriesId": "92585",
        "SeasonId": "92586",
        "PrimaryImageAspectRatio": 1.7777777777777777,
        "SeriesPrimaryImageTag": "2e80d82fd31334442c759c52f437cb6e",
        "SeasonName": "第 1 季",
        "ImageTags": {"Primary": "072f7f44ed3e67498e0d9c064de42c1a"},
        "BackdropImageTags": [],
        "ParentLogoImageTag": "8e50e262e73e8acadd7bc15cd8d58759",
        "Chapters": [
            {"StartPositionTicks": 0, "Name": "Start", "MarkerType": "Chapter", "ChapterIndex": 0},
            {"StartPositionTicks": 90000000, "Name": "Header", "MarkerType": "Chapter", "ChapterIndex": 1},
            {"StartPositionTicks": 37640000000, "Name": "Tailer", "MarkerType": "Chapter", "ChapterIndex": 2},
        ],
        "MediaType": "Video",
        "Width": 1920,
        "Height": 1080,
    },
    "Server": {
        "Name": "BearFamily Emby",
        "Id": "707a947126f84de5a227863ac85e1c4e",
        "Version": "4.9.5.0",
    },
    "Session": {
        "RemoteEndPoint": "223.167.211.8",
        "Client": "SenPlayer",
        "DeviceName": "Mac",
        "DeviceId": "BF9A0427-10C7-424D-90CD-FA5008934D28",
        "ApplicationVersion": "6.2.0",
        "Id": "18ee499e4987217b6ee4d051e9ad12bd",
    },
    "PlaybackInfo": {
        "PositionTicks": 0,
        "PlaylistIndex": 0,
        "PlaylistLength": 1,
        "PlaySessionId": "b8798fc0d80c41639e01bf0566dd49bc",
        "MediaSource": {
            "Chapters": [],
            "Protocol": "Http",
            "Id": "mediasource_96838",
            "Path": (
                "https://mp.20220727.xyz/api/v1/plugin/P115StrmHelper/redirect_url"
                "?pickcode=ak71yzyji2ddkhsqh"
            ),
            "Type": "Default",
            "Container": "mkv",
            "Size": 4732939567,
            "Name": "杀手妈咪 S01E13.WEB-DL.1080p.H264.AAC 2.0",
            "IsRemote": True,
            "HasMixedProtocols": False,
            "RunTimeTicks": 38578540000,
            "SupportsTranscoding": True,
            "SupportsDirectStream": True,
            "SupportsDirectPlay": True,
            "IsInfiniteStream": False,
            "RequiresOpening": False,
            "RequiresClosing": False,
            "RequiresLooping": False,
            "SupportsProbing": True,
            "Bitrate": 9814657,
            "RequiredHttpHeaders": {},
            "AddApiKeyToDirectStreamUrl": False,
            "ReadAtNativeFramerate": False,
            "ItemId": "96838",
        },
    },
}

# 同一个播放会话的 playback.stop（真实事件）：用户看了 2 秒就停。
# 注意 Emby 既没发 Session.PositionTicks，也没发 PlayDurationTicks。
EMBY_PLAYBACK_STOP: dict[str, Any] = {
    "Title": "Mac 上 strm 已停止播放 杀手妈咪 - S1, Ep13 - 第 13 集",
    "Date": "2026-09-15T05:39:30.6901198Z",
    "Event": "playback.stop",
    "Severity": "Info",
    "User": {"Name": "strm", "Id": "57b7904db33348f08fa6353bd0ff32ba"},
    "Item": {
        "Name": "第 13 集",
        "ServerId": "707a947126f84de5a227863ac85e1c4e",
        "Id": "96838",
        "DateCreated": "2026-09-12T18:41:42.0000000Z",
        "DateModified": "2026-09-12T18:41:42.0000000Z",
        "Container": "mkv",
        "SortName": "第 13 集",
        "PremiereDate": "2026-09-11T00:00:00.0000000Z",
        "ExternalUrls": [],
        "Path": (
            "/data/HomeTheater/strms/TV/日韩剧/杀手妈咪 (2026) {tmdbid=294095}"
            "/Season 01/杀手妈咪 S01E13.WEB-DL.1080p.H264.AAC 2.0.strm"
        ),
        "Overview": (
            "A new murder case occurs, and it confuses the police, but they are sure that it "
            "was done by Kingfisher. Bo-na realizes she's framed, and the real culprit is "
            "Leila, her old colleague who is resentful toward Bo-na for past condemnation. "
            "The appearance of Leila makes Bo-na fearful for her family’s safety."
        ),
        "Taglines": [],
        "Genres": [],
        "RunTimeTicks": 38578540000,
        "Size": 4732939567,
        "FileName": "杀手妈咪 S01E13.WEB-DL.1080p.H264.AAC 2.0.strm",
        "Bitrate": 9814657,
        "ProductionYear": 2026,
        "IndexNumber": 13,
        "ParentIndexNumber": 1,
        "RemoteTrailers": [],
        "ProviderIds": {},
        "IsFolder": False,
        "ParentId": "92586",
        "Type": "Episode",
        "Studios": [],
        "GenreItems": [],
        "TagItems": [],
        "ParentLogoItemId": "92585",
        "ParentBackdropItemId": "92585",
        "ParentBackdropImageTags": ["1b26fa81ce1d692eb971da7ca3ad9481"],
        "SeriesName": "杀手妈咪",
        "SeriesId": "92585",
        "SeasonId": "92586",
        "PrimaryImageAspectRatio": 1.7777777777777777,
        "SeriesPrimaryImageTag": "2e80d82fd31334442c759c52f437cb6e",
        "SeasonName": "第 1 季",
        "ImageTags": {"Primary": "072f7f44ed3e67498e0d9c064de42c1a"},
        "BackdropImageTags": [],
        "ParentLogoImageTag": "8e50e262e73e8acadd7bc15cd8d58759",
        "MediaType": "Video",
        "Width": 1920,
        "Height": 1080,
    },
    "Server": {
        "Name": "BearFamily Emby",
        "Id": "707a947126f84de5a227863ac85e1c4e",
        "Version": "4.9.5.0",
    },
    "Session": {
        "RemoteEndPoint": "223.167.211.8",
        "Client": "SenPlayer",
        "DeviceName": "Mac",
        "DeviceId": "BF9A0427-10C7-424D-90CD-FA5008934D28",
        "ApplicationVersion": "6.2.0",
        "Id": "18ee499e4987217b6ee4d051e9ad12bd",
    },
    "PlaybackInfo": {
        "PlayedToCompletion": False,
        "PositionTicks": 20000000,
        "PlaylistIndex": 0,
        "PlaylistLength": 0,
        "PlaySessionId": "b8798fc0d80c41639e01bf0566dd49bc",
        "MediaSource": {
            "Chapters": [],
            "Protocol": "Http",
            "Id": "mediasource_96838",
            "Path": (
                "https://mp.20220727.xyz/api/v1/plugin/P115StrmHelper/redirect_url"
                "?pickcode=ak71yzyji2ddkhsqh"
            ),
            "Type": "Default",
            "Container": "mkv",
            "Size": 4732939567,
            "Name": "杀手妈咪 S01E13.WEB-DL.1080p.H264.AAC 2.0",
            "IsRemote": True,
            "HasMixedProtocols": False,
            "RunTimeTicks": 38578540000,
            "SupportsTranscoding": True,
            "SupportsDirectStream": True,
            "SupportsDirectPlay": True,
            "IsInfiniteStream": False,
            "RequiresOpening": False,
            "RequiresClosing": False,
            "RequiresLooping": False,
            "SupportsProbing": True,
            "Formats": [],
            "Bitrate": 9814657,
            "RequiredHttpHeaders": {},
            "AddApiKeyToDirectStreamUrl": False,
            "ReadAtNativeFramerate": False,
            "ItemId": "96838",
        },
    },
}

EMBY_SERVER_NAME = "BearFamily Emby"
EMBY_USER_NAME = "strm"
EMBY_ITEM_ID = "96838"
# 线上另一次真实报错里出现过的播放位置（约 1743 秒），同时是超出 32 位整型的取值。
REAL_POSITION_TICKS = 17431791950
# playback.stop 的真实取值：只看了 2 秒。
REAL_STOP_POSITION_TICKS = 20000000
# 配置项 min_watch_time 的默认值（秒）。
DEFAULT_MIN_WATCH_TIME = 300
# 低于同步门槛的短时观看（60 秒）。
SHORT_WATCH_TICKS = 60 * 10000000


def _payload(
    event_name: str = "playback.start",
    position_ticks: Optional[int] = None,
    template: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """取一份载荷副本（播放处理会就地改写 ``Session``，必须深拷贝）。"""
    data = copy.deepcopy(template if template is not None else EMBY_PLAYBACK_START)
    data["Event"] = event_name
    if position_ticks is not None:
        data["PlaybackInfo"]["PositionTicks"] = position_ticks
    return data


def _webhook_data(event_name: str, payload: dict[str, Any]) -> SimpleNamespace:
    """构造 ``WebhookEventInfo`` 替身。"""
    return SimpleNamespace(
        channel="emby",
        event=event_name,
        server_name=EMBY_SERVER_NAME,
        json_object=payload,
    )


def _event(event_name: str, payload: dict[str, Any]) -> SimpleNamespace:
    """构造宿主 ``EventType.WebhookMessage`` 替身。"""
    return SimpleNamespace(event_data=_webhook_data(event_name, payload))


def _plugin(**attrs: Any) -> WatchSync:
    """绕过 ``__init__`` 构造插件实例，只注入被测逻辑需要的状态。"""
    plugin = object.__new__(WatchSync)
    for name, value in attrs.items():
        setattr(plugin, name, value)
    return plugin


def _handler_plugin(**attrs: Any) -> WatchSync:
    """带事件处理最小状态的插件实例。"""
    base: dict[str, Any] = {
        "_enabled": True,
        "_sync_movies": True,
        "_sync_tv": True,
        "_min_watch_time": 60,
        "_sync_metrics": {
            "total_events": 0,
            "successful_syncs": 0,
            "failed_syncs": 0,
            "duplicate_events": 0,
            "api_errors": {},
            "last_sync_time": None,
        },
        "_loop_protector": SyncLoopProtector(ttl_seconds=30),
        "_event_timestamps": {},
    }
    base.update(attrs)
    return _plugin(**base)


def _record_sync_calls(monkeypatch: Any, plugin: WatchSync) -> list[tuple]:
    """把 ``_sync_to_group_users`` 换成记录调用参数的替身。"""
    calls: list[tuple] = []

    def _fake(server: str, user: str, item: dict, ticks: int) -> None:
        calls.append((server, user, item.get("Id"), ticks))

    monkeypatch.setattr(plugin, "_sync_to_group_users", _fake)
    return calls


def test_real_payload_carries_position_only_in_playback_info() -> None:
    """真实载荷的 ``Session`` 里没有 ``PositionTicks``，位置只在 ``PlaybackInfo`` 下。

    事件指纹与播放处理都依赖这条回退，删掉任一处都会静默改变行为，故在此钉住。
    """
    payload = _payload()

    assert "PositionTicks" not in payload["Session"]
    assert payload["PlaybackInfo"]["PositionTicks"] == 0
    assert payload["Item"]["Type"] == "Episode"


def test_playback_start_triggers_no_sync(monkeypatch: Any) -> None:
    """``playback.start`` 只是开始播放，不是同步触发点，不得产生任何同步。"""
    plugin = _handler_plugin()
    calls = _record_sync_calls(monkeypatch, plugin)

    plugin.handle_webhook_message(_event("playback.start", _payload()))

    assert calls == []
    # 事件本身被收到了，只是没有继续往下走。
    assert plugin._sync_metrics["total_events"] == 1


def test_playback_stop_syncs_the_real_position_from_playback_info(monkeypatch: Any) -> None:
    """同一份载荷换成 ``playback.stop`` 后，必须用真实的播放位置去同步。"""
    plugin = _handler_plugin()
    calls = _record_sync_calls(monkeypatch, plugin)

    plugin.handle_webhook_message(
        _event("playback.stop", _payload("playback.stop", REAL_POSITION_TICKS))
    )

    # 服务器名取自载荷的 Server.Name，位置取自 PlaybackInfo 的回退。
    assert calls == [(EMBY_SERVER_NAME, EMBY_USER_NAME, EMBY_ITEM_ID, REAL_POSITION_TICKS)]


def test_short_watch_is_filtered_by_min_watch_time(monkeypatch: Any) -> None:
    """观看时长低于门槛时不同步（载荷无 PlayDurationTicks，时长回退为位置）。"""
    plugin = _handler_plugin(_min_watch_time=300)
    calls = _record_sync_calls(monkeypatch, plugin)

    plugin.handle_webhook_message(_event("playback.stop", _payload("playback.stop", SHORT_WATCH_TICKS)))

    assert calls == []


def test_event_fingerprint_uses_playback_info_position() -> None:
    """指纹要取到 ``PlaybackInfo`` 里的位置：同位置同指纹，位置不同则不同。"""
    plugin = _plugin()

    same_a = plugin._generate_event_fingerprint(
        _event("playback.stop", _payload("playback.stop", REAL_POSITION_TICKS)).event_data
    )
    same_b = plugin._generate_event_fingerprint(
        _event("playback.stop", _payload("playback.stop", REAL_POSITION_TICKS)).event_data
    )
    other = plugin._generate_event_fingerprint(
        _event(
            "playback.stop", _payload("playback.stop", REAL_POSITION_TICKS + 100000000)
        ).event_data
    )

    assert same_a == same_b
    assert same_a != other


def test_real_episode_payload_has_no_tmdb_id_and_falls_back_to_names() -> None:
    """这份载荷没有 Tmdb 号，匹配只能退回按名称搜索。"""
    payload = _payload()
    plugin = _plugin()

    assert payload["Item"]["ProviderIds"] == {}
    # 剧集先搜剧名；剧名归一后与剧名本身相同，所以去重后只剩两个检索词。
    assert plugin._get_media_search_terms(payload["Item"]) == ["杀手妈咪", "第 13 集"]


def test_real_stop_payload_has_no_session_position_nor_play_duration() -> None:
    """``playback.stop`` 同样只在 ``PlaybackInfo`` 给位置，且不带 ``PlayDurationTicks``。

    这决定了下一条用例的行为：时长门槛实际是拿**最终播放位置**去比 ``min_watch_time``。
    这里取载荷副本断言 —— 播放处理会就地往 ``Session`` 写 ``PositionTicks``，直接读模板
    容易被改写污染。
    """
    payload = _payload("playback.stop", template=EMBY_PLAYBACK_STOP)
    playback_info = payload["PlaybackInfo"]

    assert "PositionTicks" not in payload["Session"]
    assert "PlayDurationTicks" not in payload["Session"]
    assert "PlayDurationTicks" not in playback_info
    assert playback_info["PositionTicks"] == REAL_STOP_POSITION_TICKS
    assert REAL_STOP_POSITION_TICKS / 10000000 < DEFAULT_MIN_WATCH_TIME


def test_real_stop_payload_below_min_watch_time_is_not_synced(monkeypatch: Any) -> None:
    """真实那条「看了 2 秒就停」的停止事件不应触发同步。"""
    plugin = _handler_plugin(_min_watch_time=DEFAULT_MIN_WATCH_TIME)
    calls = _record_sync_calls(monkeypatch, plugin)

    plugin.handle_webhook_message(
        _event("playback.stop", _payload("playback.stop", template=EMBY_PLAYBACK_STOP))
    )

    assert calls == []


def test_real_stop_payload_above_min_watch_time_is_synced(monkeypatch: Any) -> None:
    """把位置换成看够门槛的取值，同一份停止事件就必须同步这个位置。

    证明门槛用的是**播放位置**（Emby 不给 ``PlayDurationTicks`` 时的回退），而不是会话时长 ——
    否则这类事件会静默地不同步。
    """
    plugin = _handler_plugin(_min_watch_time=DEFAULT_MIN_WATCH_TIME)
    calls = _record_sync_calls(monkeypatch, plugin)

    plugin.handle_webhook_message(
        _event(
            "playback.stop",
            _payload("playback.stop", REAL_POSITION_TICKS, template=EMBY_PLAYBACK_STOP),
        )
    )

    assert calls == [(EMBY_SERVER_NAME, EMBY_USER_NAME, EMBY_ITEM_ID, REAL_POSITION_TICKS)]
