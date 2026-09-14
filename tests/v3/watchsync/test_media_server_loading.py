"""WatchSync V3 插件：媒体服务器实例发现单测。

迁移要点：旧实现直接读取宿主 ``ModuleManager._running_modules`` 私有属性，
V3 改为通过稳定 SDK 的 ``MediaServerHelper`` 服务目录获取实例；宿主不同版本的
``get_services`` 签名不一致，过滤式调用不受支持时必须降级为全量读取再按实例类型筛选，
且 Jellyfin/Plex 等其他类型不得被误纳。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.plugins.watchsync import WatchSync


class _EmbyInstance:
    """占位 Emby 实例。"""


class _ZSpaceInstance:
    """占位极影视实例。"""

    _is_watchsync_zspace = True


class _JellyfinInstance:
    """占位 Jellyfin 实例：不属于本插件支持的媒体服务器类型。"""


# 类型判定依赖类名与模块名，显式固定模块名以免受测试文件名影响。
_EmbyInstance.__module__ = "app.adapters.external.emby"
_ZSpaceInstance.__module__ = "app.adapters.external.zspace"
_JellyfinInstance.__module__ = "app.adapters.external.jellyfin"


class _FakeHelper:
    """模拟 MediaServerHelper：可切换是否支持 type_filter 关键字。"""

    def __init__(self, catalog: dict, supports_filter: bool = True):
        self._catalog = catalog
        self._supports_filter = supports_filter

    def get_services(self, type_filter=None):
        """按调用方式返回服务目录；不支持过滤时抛出真实宿主会抛出的 TypeError。"""
        if type_filter is None:
            return {
                name: SimpleNamespace(instance=instance)
                for items in self._catalog.values()
                for name, instance in items
            }
        if not self._supports_filter:
            raise TypeError("get_services() got an unexpected keyword argument 'type_filter'")
        return {
            name: SimpleNamespace(instance=instance)
            for name, instance in self._catalog.get(type_filter, [])
        }


def _bare_plugin() -> WatchSync:
    """绕过 ``__init__`` 构造插件实例，并屏蔽本机极影视自动发现。"""
    plugin = object.__new__(WatchSync)
    plugin._load_local_zspace_instance = lambda: None
    return plugin


def _load(helper: _FakeHelper) -> WatchSync:
    """在替身服务目录下执行实例加载。"""
    plugin = _bare_plugin()
    with patch("app.plugins.watchsync.MediaServerHelper", return_value=helper):
        plugin._load_media_server_instances()
    return plugin


def test_classify_media_server_recognises_supported_types() -> None:
    """类型兜底判定必须只认 Emby 与极影视。"""
    assert WatchSync._classify_media_server(_EmbyInstance()) == "emby"
    assert WatchSync._classify_media_server(_ZSpaceInstance()) == "zspace"


def test_classify_media_server_rejects_other_and_empty_instances() -> None:
    """Jellyfin 等其他类型与空实例都归为 unknown，避免被误同步。"""
    assert WatchSync._classify_media_server(_JellyfinInstance()) == "unknown"
    assert WatchSync._classify_media_server(None) == "unknown"


def test_load_media_server_instances_registers_types_and_zspace_alias() -> None:
    """极影视实例同时登记为 Emby 兼容层与 zspace 类型。"""
    plugin = _load(
        _FakeHelper(
            {
                "emby": [("客厅Emby", _EmbyInstance())],
                "zspace": [("极影视", _ZSpaceInstance())],
            }
        )
    )

    assert set(plugin._emby_instances) == {"客厅Emby", "极影视"}
    assert set(plugin._zspace_instances) == {"极影视"}
    assert plugin._server_types == {"客厅Emby": "emby", "极影视": "zspace"}


def test_load_falls_back_to_full_catalog_when_type_filter_is_unsupported() -> None:
    """宿主 get_services 不接受 type_filter 时降级为全量读取并按类型筛选。"""
    plugin = _load(
        _FakeHelper(
            {
                "emby": [("客厅Emby", _EmbyInstance()), ("Jellyfin", _JellyfinInstance())],
                "zspace": [("极影视", _ZSpaceInstance())],
            },
            supports_filter=False,
        )
    )

    assert set(plugin._emby_instances) == {"客厅Emby", "极影视"}
    assert "Jellyfin" not in plugin._emby_instances
    assert plugin._server_types == {"客厅Emby": "emby", "极影视": "zspace"}


def test_load_keeps_local_zspace_discovery_when_catalog_is_empty() -> None:
    """服务目录为空时仍保留本机极影视自动发现结果。"""
    local_instance = _ZSpaceInstance()
    plugin = object.__new__(WatchSync)
    plugin._load_local_zspace_instance = lambda: ("本机极影视", local_instance)

    with patch("app.plugins.watchsync.MediaServerHelper", return_value=_FakeHelper({})):
        plugin._load_media_server_instances()

    assert plugin._emby_instances == {"本机极影视": local_instance}
    assert plugin._zspace_instances == {"本机极影视": local_instance}
    assert plugin._server_types == {"本机极影视": "zspace"}


def test_load_keeps_catalog_instance_when_local_zspace_has_same_name() -> None:
    """同名实例以服务目录登记为准，自动发现不覆盖已有实例。"""
    catalog_instance = _ZSpaceInstance()
    plugin = object.__new__(WatchSync)
    plugin._load_local_zspace_instance = lambda: ("极影视", _ZSpaceInstance())

    with patch(
        "app.plugins.watchsync.MediaServerHelper",
        return_value=_FakeHelper({"zspace": [("极影视", catalog_instance)]}),
    ):
        plugin._load_media_server_instances()

    assert plugin._emby_instances["极影视"] is catalog_instance


def test_fetch_media_server_instances_skips_entries_without_instance() -> None:
    """没有实例对象的服务条目必须跳过，避免后续调空对象。"""
    helper = _FakeHelper({})
    helper.get_services = lambda type_filter=None: {
        "客厅Emby": SimpleNamespace(instance=_EmbyInstance()),
        "空条目": SimpleNamespace(instance=None),
    }

    assert set(WatchSync._fetch_media_server_instances(helper, "emby")) == {"客厅Emby"}


def test_fetch_media_server_instances_returns_empty_on_service_error() -> None:
    """服务目录读取失败时返回空映射，不向上抛异常。"""

    class _BrokenHelper:
        def get_services(self, type_filter=None):
            raise RuntimeError("service catalog unavailable")

    assert WatchSync._fetch_media_server_instances(_BrokenHelper(), "emby") == {}


def test_load_survives_unavailable_service_catalog() -> None:
    """服务目录构造失败时只记录日志，插件仍可初始化。"""
    plugin = _bare_plugin()
    with patch(
        "app.plugins.watchsync.MediaServerHelper",
        side_effect=RuntimeError("catalog unavailable"),
    ):
        plugin._load_media_server_instances()

    assert plugin._emby_instances == {}
    assert plugin._zspace_instances == {}
    assert plugin._server_types == {}
