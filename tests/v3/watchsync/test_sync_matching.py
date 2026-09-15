"""WatchSync V3 插件：同步目标匹配与防循环纯逻辑单测。

这些方法决定「谁同步给谁」「源媒体对应目标媒体的哪一项」以及「刚同步过的事件
不要再被当成新事件回流」，因此都在 V3 迁移中原样保留。测试通过 ``object.__new__``
绕过 ``__init__``，只注入被测逻辑需要的状态。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

from app.plugins.watchsync import SyncLoopProtector, WatchSync


class _EmbyInstance:
    """占位 Emby 实例。"""


class _ZSpaceInstance:
    """占位极影视实例：带旧实现约定的标记属性。"""

    _is_watchsync_zspace = True


def _plugin(**attrs) -> WatchSync:
    """绕过 ``__init__`` 构造插件实例，只注入被测逻辑需要的状态。"""
    plugin = object.__new__(WatchSync)
    for name, value in attrs.items():
        setattr(plugin, name, value)
    return plugin


def _plugin_with_servers() -> WatchSync:
    """构造已加载两台 Emby + 一台极影视的插件实例。"""
    return _plugin(
        _emby_instances={
            "客厅Emby": _EmbyInstance(),
            "卧室Emby": _EmbyInstance(),
            "极影视": _ZSpaceInstance(),
        },
        _zspace_instances={"极影视": _ZSpaceInstance()},
        _server_types={"客厅Emby": "emby", "卧室Emby": "emby", "极影视": "zspace"},
        _sync_groups=[
            {
                "name": "家庭组",
                "enabled": True,
                "users": [
                    {"server": "客厅Emby", "username": "alice"},
                    {"server": "卧室Emby", "username": "bob"},
                    {"server": "极影视", "username": "carol"},
                ],
            },
            {
                "name": "已停用组",
                "enabled": False,
                "users": [
                    {"server": "客厅Emby", "username": "alice"},
                    {"server": "卧室Emby", "username": "dave"},
                ],
            },
        ],
    )


def test_coerce_int_falls_back_and_applies_floor() -> None:
    """配置值非法时回落默认值，合法值仍受下限约束。"""
    assert WatchSync._coerce_int("45", 30, 10) == 45
    assert WatchSync._coerce_int("abc", 30, 10) == 30
    assert WatchSync._coerce_int(None, 30, 10) == 30
    assert WatchSync._coerce_int(1, 30, 10) == 10


def test_normalize_series_name_strips_vendor_season_suffixes() -> None:
    """极影视会把季尾缀并入剧名，匹配前必须归一。"""
    assert WatchSync._normalize_series_name("某剧 第 2 季") == "某剧"
    assert WatchSync._normalize_series_name("Show Season 3") == "Show"
    assert WatchSync._normalize_series_name("Show S03") == "Show"
    assert WatchSync._normalize_series_name("流浪地球") == "流浪地球"
    assert WatchSync._normalize_series_name(None) == ""


def test_generic_server_alias_only_matches_its_own_type() -> None:
    """配置写通用名时只匹配同类型实例，避免 Emby 误同步到极影视。"""
    plugin = _plugin_with_servers()

    assert plugin._is_server_match("客厅Emby", "客厅Emby") is True
    assert plugin._is_server_match("Emby", "客厅Emby") is True
    assert plugin._is_server_match("Emby", "极影视") is False
    assert plugin._is_server_match("极影视", "客厅Emby") is False
    assert plugin._is_server_match("", "客厅Emby") is False


def test_short_server_name_does_not_match_by_substring() -> None:
    """过短的配置名不得命中长实例名。"""
    plugin = _plugin_with_servers()
    assert plugin._is_server_match("a", "客厅Emby") is False


def test_actual_server_name_resolves_alias_to_loaded_instance() -> None:
    """通用名/别名需要解析成真实实例名后再发起同步。"""
    plugin = _plugin_with_servers()

    assert plugin._get_actual_server_name("卧室Emby") == "卧室Emby"
    assert plugin._get_actual_server_name("Emby") == "客厅Emby"
    assert plugin._get_actual_server_name("zspace") == "极影视"
    assert plugin._get_actual_server_name("") is None


def test_find_sync_targets_skips_source_user_and_disabled_groups() -> None:
    """同步目标为同组其他用户，且不包含源用户自己与已停用组。"""
    plugin = _plugin_with_servers()
    targets = plugin._find_sync_targets("客厅Emby", "alice")

    assert ("客厅Emby", "alice") not in targets
    assert ("卧室Emby", "dave") not in targets
    assert set(targets) == {("卧室Emby", "bob"), ("极影视", "carol")}


def test_pick_best_matching_item_prefers_tmdb_identity() -> None:
    """同名多版本时优先按 ProviderIds 的 TMDB 身份锁定。"""
    plugin = _plugin()
    candidates = [
        {"Name": "流浪地球", "Type": "Movie", "ProductionYear": 2019, "ProviderIds": {"Tmdb": "111"}},
        {"Name": "流浪地球", "Type": "Movie", "ProductionYear": 2000, "ProviderIds": {"Tmdb": "222"}},
    ]

    picked = plugin._pick_best_matching_item(
        {"Type": "Movie", "Name": "任意", "ProviderIds": {"Tmdb": "222"}}, candidates
    )
    assert picked is not None and picked["ProductionYear"] == 2000


def test_pick_best_matching_item_falls_back_to_name_and_year() -> None:
    """没有 TMDB 身份时按名称 + 年份匹配电影。"""
    plugin = _plugin()
    candidates = [
        {"Name": "流浪地球", "Type": "Movie", "ProductionYear": 2019, "ProviderIds": {"Tmdb": "111"}},
        {"Name": "流浪地球", "Type": "Movie", "ProductionYear": 2000, "ProviderIds": {"Tmdb": "222"}},
    ]

    picked = plugin._pick_best_matching_item(
        {"Type": "Movie", "Name": "流浪地球", "ProductionYear": 2019}, candidates
    )
    assert picked is not None and picked["ProviderIds"]["Tmdb"] == "111"


def test_pick_best_matching_item_matches_episode_by_season_and_index() -> None:
    """剧集按 季号 + 集号 匹配，剧名带季尾缀时也要命中。"""
    plugin = _plugin()
    episodes = [
        {"Name": "E01", "Type": "Episode", "SeriesName": "某剧",
         "ParentIndexNumber": 1, "IndexNumber": 1},
        {"Name": "E02", "Type": "Episode", "SeriesName": "某剧",
         "ParentIndexNumber": 1, "IndexNumber": 2},
    ]

    picked = plugin._pick_best_matching_item(
        {"Type": "Episode", "Name": "x", "SeriesName": "某剧",
         "ParentIndexNumber": 1, "IndexNumber": 2},
        episodes,
    )
    assert picked is not None and picked["Name"] == "E02"

    suffixed = plugin._pick_best_matching_item(
        {"Type": "Episode", "Name": "x", "SeriesName": "某剧 第 1 季",
         "ParentIndexNumber": 1, "IndexNumber": 2},
        episodes,
    )
    assert suffixed is not None and suffixed["Name"] == "E02"


def test_pick_best_matching_item_returns_none_without_candidates() -> None:
    """无候选时返回 None，由调用方决定是否跳过同步。"""
    assert _plugin()._pick_best_matching_item({"Type": "Movie"}, []) is None


def test_pick_best_matching_item_rejects_episode_of_another_series() -> None:
    """同季同集但剧名不同 → 不得命中，否则进度会被写到别的剧上。"""
    plugin = _plugin()
    candidates = [
        {"Name": "第 13 集", "Type": "Episode", "SeriesName": "完全无关的剧",
         "ParentIndexNumber": 1, "IndexNumber": 13},
    ]

    picked = plugin._pick_best_matching_item(
        {"Type": "Episode", "Name": "第 13 集", "SeriesName": "杀手妈咪",
         "ParentIndexNumber": 1, "IndexNumber": 13, "ProviderIds": {}},
        candidates,
    )

    assert picked is None


def test_pick_best_matching_item_returns_none_when_no_episode_matches() -> None:
    """候选里没有源剧集时返回 None，不能退而挑第一个候选。"""
    plugin = _plugin()
    candidates = [
        {"Name": "第 5 集", "Type": "Episode", "SeriesName": "别的剧",
         "ParentIndexNumber": 2, "IndexNumber": 5},
    ]

    picked = plugin._pick_best_matching_item(
        {"Type": "Episode", "Name": "第 13 集", "SeriesName": "杀手妈咪",
         "ParentIndexNumber": 1, "IndexNumber": 13, "ProviderIds": {}},
        candidates,
    )

    assert picked is None


def test_pick_best_matching_item_second_round_uses_series_and_name() -> None:
    """候选缺季号时（极影视常见）第二轮按剧名 + 名称命中。"""
    plugin = _plugin()
    candidates = [
        {"Name": "第 1 集", "Type": "Episode", "SeriesName": "某剧", "IndexNumber": 1},
    ]

    picked = plugin._pick_best_matching_item(
        {"Type": "Episode", "Name": "第 1 集", "SeriesName": "某剧",
         "ParentIndexNumber": 1, "IndexNumber": 1},
        candidates,
    )

    assert picked is not None and picked["Name"] == "第 1 集"


def test_pick_best_matching_item_keeps_v2_movie_fallback() -> None:
    """电影沿用 V2 行为：名称 + 年份都对不上时仍取首个候选。

    这条是 V2 的既有语义（V2 只在剧集分支 return None），本次照原样保留，
    属于已知残留风险 —— 若要收紧需另外确认。
    """
    plugin = _plugin()
    candidates = [
        {"Name": "别的电影", "Type": "Movie", "ProductionYear": 2001, "ProviderIds": {}},
    ]

    picked = plugin._pick_best_matching_item(
        {"Type": "Movie", "Name": "流浪地球", "ProductionYear": 2019, "ProviderIds": {}},
        candidates,
    )

    assert picked is not None and picked["Name"] == "别的电影"


def test_media_search_terms_put_series_name_first_for_episodes() -> None:
    """剧集先搜剧名（单集名常是本地化的「第 N 集」，区分度太低），并保持去重顺序。"""
    plugin = _plugin()
    terms = plugin._get_media_search_terms(
        {"Type": "Episode", "Name": "E01", "SeriesName": "某剧 第 1 季"}
    )
    assert terms == ["某剧 第 1 季", "某剧", "E01"]


def test_media_search_terms_keep_movie_titles_only() -> None:
    """电影只取名称与原始标题。"""
    plugin = _plugin()
    assert plugin._get_media_search_terms(
        {"Type": "Movie", "Name": "流浪地球", "OriginalTitle": "The Wandering Earth"}
    ) == ["流浪地球", "The Wandering Earth"]


def test_sync_loop_protector_scopes_by_user_item_and_type() -> None:
    """刚被同步过的 用户+媒体+类型 组合在 TTL 内被拦截。"""
    protector = SyncLoopProtector(ttl_seconds=30)
    protector.add("bob", "item-1", "playback")

    assert protector.is_protected("bob", "item-1", "playback") is True
    assert protector.is_protected("bob", "item-1", "favorite") is False
    assert protector.is_protected("bob", "item-2", "playback") is False


def test_sync_loop_protector_ignores_blank_input() -> None:
    """参数不完整时不写入也不拦截，避免把空身份当成循环。"""
    protector = SyncLoopProtector(ttl_seconds=30)
    protector.add("", "item-1", "playback")

    assert protector.is_protected("", "item-1", "playback") is False


def test_sync_loop_protector_releases_after_ttl() -> None:
    """TTL 过期后同一组合重新可被处理。"""
    protector = SyncLoopProtector(ttl_seconds=-1)
    protector.add("bob", "item-1", "playback")

    assert protector.is_protected("bob", "item-1", "playback") is False


def test_duplicate_event_detection_uses_fingerprint_window() -> None:
    """同一指纹在时间窗内只处理一次，不同指纹互不影响。"""
    plugin = _plugin(_event_timestamps={})

    assert plugin._is_duplicate_event("fp-1") is False
    assert plugin._is_duplicate_event("fp-1") is True
    assert plugin._is_duplicate_event("fp-2") is False


def _event(event_name: str, item: Optional[dict] = None) -> SimpleNamespace:
    """构造只带插件读取字段的事件替身。"""
    return SimpleNamespace(event=event_name, json_object={"Item": item or {}})


def test_sync_type_from_event_maps_known_event_names() -> None:
    """事件名到同步类型的映射决定后续走播放、收藏还是标记已看分支。"""
    plugin = _plugin()

    assert plugin._get_sync_type_from_event(_event("playback.stop")) == "playback"
    assert plugin._get_sync_type_from_event(_event("playback.pause")) == "playback"
    assert plugin._get_sync_type_from_event(_event("item.markplayed")) == "mark_played"
    assert plugin._get_sync_type_from_event(_event("playback.scrobble")) == "mark_played"
    assert plugin._get_sync_type_from_event(_event("item.markunplayed")) == "mark_unplayed"


def test_sync_type_from_event_reads_favorite_flag_from_item_userdata() -> None:
    """收藏事件按 Item.UserData.IsFavorite 区分收藏与取消收藏。"""
    plugin = _plugin()

    assert plugin._get_sync_type_from_event(
        _event("user.favorite", {"UserData": {"IsFavorite": True}})
    ) == "favorite"
    assert plugin._get_sync_type_from_event(
        _event("item.rate", {"UserData": {"IsFavorite": False}})
    ) == "not_favorite"


def test_sync_type_from_event_returns_none_for_unrelated_events() -> None:
    """与同步无关的事件不产生同步类型，调用方据此跳过。"""
    assert _plugin()._get_sync_type_from_event(_event("system.update")) is None
