"""WatchSync V3 插件：媒体服务器实例发现单测。

发现策略分三层，本文件覆盖全部三层：

1. 稳定 SDK 的服务目录 ``MediaServerHelper().get_services()``（V3 文档推荐的入口）；
   宿主不同版本的 ``get_services`` 签名不一致，过滤式调用不受支持时必须降级为
   全量读取再按实例类型筛选，且 Jellyfin/Plex 等其他类型不得被误纳。
2. 服务目录不可用或未命中时，退回宿主的运行模块；必须走公开的
   ``ModuleManager().get_running_module()``，不得读取 ``_running_modules`` 私有属性。
3. 都没有时做本机极影视自动发现，且一个实例都发现不了时必须留日志而不是静默。
"""

from __future__ import annotations

import importlib
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


class _FakeCatalogHelper:
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


class _FakeHostModule:
    """模拟宿主运行模块（EmbyModule / ZSpaceModule）。"""

    def __init__(self, instances: dict):
        self._instances = instances

    def get_instances(self) -> dict:
        """返回该模块管理的媒体服务器实例映射。"""
        return self._instances


class _HostModuleWithoutInstances:
    """模拟没有 get_instances 的运行模块。"""


def _bare_plugin() -> WatchSync:
    """绕过 ``__init__`` 构造插件实例，并屏蔽本机极影视自动发现。"""
    plugin = object.__new__(WatchSync)
    plugin._load_local_zspace_instance = lambda: None
    return plugin


def _patch_module_manager(monkeypatch, modules: dict) -> None:
    """把 ``app.sdk.plugins.ModuleManager`` 换成按 ID 返回替身模块的版本。

    插件在函数内部做 ``from app.sdk.plugins import ModuleManager``，因此替换模块属性
    即可同时作用于本地桩与真实后端。
    """
    sdk_plugins = importlib.import_module("app.sdk.plugins")

    class _FakeModuleManager:
        def get_running_module(self, module_id):
            return modules.get(module_id)

    monkeypatch.setattr(sdk_plugins, "ModuleManager", _FakeModuleManager)


def _load(helper: _FakeCatalogHelper | None) -> WatchSync:
    """在替身服务目录下执行实例加载；helper 为 None 时模拟服务目录不可用。"""
    plugin = _bare_plugin()
    if helper is None:
        with patch("app.plugins.watchsync.MediaServerHelper", side_effect=RuntimeError("no catalog")):
            plugin._load_emby_instances()
    else:
        with patch("app.plugins.watchsync.MediaServerHelper", return_value=helper):
            plugin._load_emby_instances()
    return plugin


def test_classify_media_server_recognises_supported_types() -> None:
    """类型兜底判定必须只认 Emby 与极影视。"""
    assert WatchSync._classify_media_server(_EmbyInstance()) == "emby"
    assert WatchSync._classify_media_server(_ZSpaceInstance()) == "zspace"


def test_classify_media_server_rejects_other_and_empty_instances() -> None:
    """Jellyfin 等其他类型与空实例都归为 unknown，避免被误同步。"""
    assert WatchSync._classify_media_server(_JellyfinInstance()) == "unknown"
    assert WatchSync._classify_media_server(None) == "unknown"


def test_load_emby_instances_registers_types_and_zspace_alias(monkeypatch) -> None:
    """服务目录可用时，极影视实例同时登记为 Emby 兼容层与 zspace 类型。"""
    _patch_module_manager(monkeypatch, {})
    plugin = _load(
        _FakeCatalogHelper(
            {
                "emby": [("客厅Emby", _EmbyInstance())],
                "zspace": [("极影视", _ZSpaceInstance())],
            }
        )
    )

    assert set(plugin._emby_instances) == {"客厅Emby", "极影视"}
    assert set(plugin._zspace_instances) == {"极影视"}
    assert plugin._server_types == {"客厅Emby": "emby", "极影视": "zspace"}


def test_load_falls_back_to_full_catalog_when_type_filter_is_unsupported(monkeypatch) -> None:
    """宿主 get_services 不接受 type_filter 时降级为全量读取并按类型筛选。"""
    _patch_module_manager(monkeypatch, {})
    plugin = _load(
        _FakeCatalogHelper(
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


def test_load_falls_back_to_running_modules_when_catalog_is_empty(monkeypatch) -> None:
    """服务目录为空时退回运行模块，且只用公开入口拿模块。"""
    _patch_module_manager(
        monkeypatch,
        {
            "EmbyModule": _FakeHostModule({"客厅Emby": _EmbyInstance()}),
            "ZSpaceModule": _FakeHostModule({"极影视": _ZSpaceInstance()}),
        },
    )
    plugin = _load(_FakeCatalogHelper({}))

    assert set(plugin._emby_instances) == {"客厅Emby", "极影视"}
    assert set(plugin._zspace_instances) == {"极影视"}
    assert plugin._server_types == {"客厅Emby": "emby", "极影视": "zspace"}


def test_load_falls_back_to_running_modules_when_catalog_is_unavailable(monkeypatch) -> None:
    """服务目录构造失败时同样退回运行模块，插件不因此加载失败。"""
    _patch_module_manager(
        monkeypatch, {"EmbyModule": _FakeHostModule({"客厅Emby": _EmbyInstance()})}
    )
    plugin = _load(None)

    assert set(plugin._emby_instances) == {"客厅Emby"}
    assert plugin._server_types == {"客厅Emby": "emby"}


def test_load_keeps_local_zspace_discovery_when_nothing_else_is_available(monkeypatch) -> None:
    """服务目录与运行模块都拿不到时才走本机极影视自动发现。"""
    _patch_module_manager(monkeypatch, {})
    local_instance = _ZSpaceInstance()
    plugin = object.__new__(WatchSync)
    plugin._load_local_zspace_instance = lambda: ("本机极影视", local_instance)

    with patch("app.plugins.watchsync.MediaServerHelper", return_value=_FakeCatalogHelper({})):
        plugin._load_emby_instances()

    assert plugin._emby_instances == {"本机极影视": local_instance}
    assert plugin._zspace_instances == {"本机极影视": local_instance}
    assert plugin._server_types == {"本机极影视": "zspace"}


def test_load_keeps_catalog_instance_when_local_zspace_has_same_name(monkeypatch) -> None:
    """同名实例以服务目录登记为准，自动发现不覆盖已有实例。"""
    _patch_module_manager(monkeypatch, {})
    catalog_instance = _ZSpaceInstance()
    plugin = object.__new__(WatchSync)
    plugin._load_local_zspace_instance = lambda: ("极影视", _ZSpaceInstance())

    with patch(
        "app.plugins.watchsync.MediaServerHelper",
        return_value=_FakeCatalogHelper({"zspace": [("极影视", catalog_instance)]}),
    ):
        plugin._load_emby_instances()

    assert plugin._emby_instances["极影视"] is catalog_instance


def test_load_survives_without_any_discovery_source(monkeypatch) -> None:
    """三层都拿不到实例时只是没有服务器，不能抛异常。"""
    _patch_module_manager(monkeypatch, {})
    plugin = _load(_FakeCatalogHelper({}))

    assert plugin._emby_instances == {}
    assert plugin._zspace_instances == {}
    assert plugin._server_types == {}


def test_load_logs_warning_when_no_server_is_discovered(monkeypatch, caplog) -> None:
    """一个实例都发现不了时必须留日志，避免"插件已加载但不工作"难以排查。"""
    _patch_module_manager(monkeypatch, {})

    with caplog.at_level("WARNING", logger="stub-watchsync"):
        _load(_FakeCatalogHelper({}))

    assert any("未加载到任何 Emby" in record.message for record in caplog.records)


def test_fetch_catalog_instances_skips_entries_without_instance() -> None:
    """没有实例对象的服务条目必须跳过，避免后续调空对象。"""
    helper = SimpleNamespace(
        get_services=lambda type_filter=None: {
            "客厅Emby": SimpleNamespace(instance=_EmbyInstance()),
            "空条目": SimpleNamespace(instance=None),
        }
    )

    with patch("app.plugins.watchsync.MediaServerHelper", return_value=helper):
        assert set(WatchSync._fetch_catalog_instances("emby")) == {"客厅Emby"}


def test_fetch_catalog_instances_returns_empty_on_service_error() -> None:
    """服务目录读取失败时返回空映射，不向上抛异常。"""

    def _boom(type_filter=None):
        raise RuntimeError("service catalog unavailable")

    helper = SimpleNamespace(get_services=_boom)
    with patch("app.plugins.watchsync.MediaServerHelper", return_value=helper):
        assert WatchSync._fetch_catalog_instances("emby") == {}


def test_fetch_catalog_instances_returns_empty_when_helper_cannot_be_built() -> None:
    """服务目录对象构造失败时返回空映射，交给下一层兜底。"""
    with patch("app.plugins.watchsync.MediaServerHelper", side_effect=RuntimeError("no catalog")):
        assert WatchSync._fetch_catalog_instances("emby") == {}


def test_fetch_catalog_instances_returns_empty_without_sdk_helper() -> None:
    """宿主未提供媒体服务器服务目录时不报错，交给下一层兜底。"""
    with patch("app.plugins.watchsync.MediaServerHelper", None):
        assert WatchSync._fetch_catalog_instances("emby") == {}


def test_fetch_module_instances_tolerates_module_without_get_instances(monkeypatch) -> None:
    """拿到的运行模块没有 get_instances 时返回空映射。"""
    _patch_module_manager(monkeypatch, {"EmbyModule": _HostModuleWithoutInstances()})

    assert WatchSync._fetch_module_instances("EmbyModule") == {}


def test_fetch_module_instances_returns_empty_for_unknown_module(monkeypatch) -> None:
    """模块未运行时（未配置媒体服务器）返回空映射。"""
    _patch_module_manager(monkeypatch, {})

    assert WatchSync._fetch_module_instances("EmbyModule") == {}
