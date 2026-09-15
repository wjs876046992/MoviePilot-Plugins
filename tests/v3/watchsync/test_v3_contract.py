"""WatchSync V3 插件：代际合同与市场索引一致性单测。

覆盖本次 V2→V3 迁移固化的约定：

- 导入面收敛到 ``app.sdk.*`` / ``app.db`` 稳定合同，不再触碰 ``app.core`` /
  ``app.helper`` / ``app.utils`` / ``app.log``，也不再读取宿主
  ``ModuleManager._running_modules`` 私有属性；
- V3 入口主版本比历史实现高一档，并与 ``package.v3.json`` 登记一致；
- V2 实现保留在 ``plugins.v2/watchsync``，但以 ``v3: false`` 声明不再由 V3 宿主承载；
- 提交的联邦产物能暴露三个 Vue 组件，且不含 originjs 遗留的共享 Vuetify 基础样式。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from app.plugins.watchsync import WatchSync

ROOT = Path(__file__).parents[3]
PLUGIN_DIR = ROOT / "plugins.v3" / "watchsync"

# 迁移后不得再出现的宿主内部模块前缀；稳定合同只暴露 app.sdk.* / app.db。
FORBIDDEN_IMPORT_PREFIXES = (
    "app.core",
    "app.helper",
    "app.utils",
    "app.log",
    "app.application",
)

# 旧实现依赖的宿主私有入口与插件数据目录常量。
# 注意不禁止标识符 ``ModuleManager``：经 ``app.sdk.plugins`` 使用它的公开方法
# （如 get_running_module）是合规的；被禁止的是读取其 ``_running_modules`` 私有属性，
# 以及经 ``app.core.module`` 之类的旧路径导入（后者由导入前缀检查覆盖）。
FORBIDDEN_IDENTIFIERS = (
    "_running_modules",
    "__running_modules",
    "PLUGIN_DATA_PATH",
)

# 迁移后必须经由的稳定 SDK 入口。
# 不要求 ``app.sdk.network``：HTTP 层为规避宿主代理异常直接使用宿主依赖 ``httpx2``
# （后端 pyproject 已声明 ``httpx2[http2,socks]~=2.12.0``），这不属于旧路径导入。
REQUIRED_SDK_MODULES = {
    "app.sdk.config",
    "app.sdk.events",
    "app.sdk.logging",
    "app.sdk.plugins",
    "app.sdk.services",
}

EXPECTED_API_PATHS = ["/servers", "/users", "/stats", "/records", "/status", "/records/old"]

EXPECTED_RECORD_FIELDS = {
    "id",
    "timestamp",
    "source_server",
    "source_user",
    "target_server",
    "target_user",
    "media_name",
    "media_type",
    "sync_type",
    "status",
    "error_message",
    "created_at",
    "position_ticks",
}


def _plugin_modules() -> dict[str, ast.Module]:
    """解析插件目录下的全部 Python 源码，供合同扫描复用。"""
    return {
        path.name: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in sorted(PLUGIN_DIR.glob("*.py"))
    }


def _imported_modules(tree: ast.Module) -> set[str]:
    """收集源码中的 import 目标，含函数体内的延迟导入。"""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _identifiers(tree: ast.Module) -> set[str]:
    """收集标识符与属性名。

    只遍历 AST 节点，因此注释和文档字符串中提到的历史入口不会被误判。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def _bare_plugin() -> WatchSync:
    """绕过 ``__init__`` 构造插件实例，只验证不依赖运行时状态的逻辑。"""
    return object.__new__(WatchSync)


def _package(name: str) -> dict:
    """读取插件市场索引。"""
    return json.loads((ROOT / name).read_text(encoding="utf-8"))["WatchSync"]


def test_plugin_source_only_imports_stable_sdk_contracts() -> None:
    """迁移后的导入面不得再触及宿主内部模块。"""
    for filename, tree in _plugin_modules().items():
        for module in sorted(_imported_modules(tree)):
            assert not module.startswith(FORBIDDEN_IMPORT_PREFIXES), (
                f"{filename} 仍导入宿主内部模块: {module}"
            )


def test_plugin_source_does_not_read_host_private_plugin_manager() -> None:
    """旧实现直接读 ModuleManager._running_modules，V3 必须改用服务目录。"""
    for filename, tree in _plugin_modules().items():
        leaked = sorted(_identifiers(tree) & set(FORBIDDEN_IDENTIFIERS))
        assert not leaked, f"{filename} 仍引用宿主私有入口: {leaked}"


def test_plugin_source_routes_through_v3_sdk_entrypoints() -> None:
    """配置、事件、日志、网络与媒体服务器发现都必须走稳定 SDK。"""
    modules = _imported_modules(_plugin_modules()["__init__.py"])
    assert REQUIRED_SDK_MODULES <= modules


def test_self_owned_record_store_uses_shared_db_contract() -> None:
    """插件自有表必须使用宿主共享的 app.db 声明式基类与事务装饰器。"""
    modules = _imported_modules(_plugin_modules()["models.py"])
    assert "app.db" in modules


def test_entry_version_follows_generation_rule_and_market_index() -> None:
    """V3 入口主版本比历史实现高一档，且与 package.v3.json 登记保持一致。"""
    legacy_version = _package("package.v2.json")["version"]
    entry = _package("package.v3.json")

    assert int(entry["version"].split(".")[0]) == int(legacy_version.split(".")[0]) + 1
    assert WatchSync.plugin_version == entry["version"]
    assert f"v{WatchSync.plugin_version}" in entry["history"]
    assert entry["system_version"] == ">=3.0.0"


def test_v2_implementation_is_kept_for_legacy_hosts() -> None:
    """同时保留两代实现：V2 目录仍在，但声明 v3: false 不参与 V3 承载。"""
    assert (ROOT / "plugins.v2" / "watchsync" / "__init__.py").is_file()
    legacy = _package("package.v2.json")
    assert legacy["v3"] is False
    assert legacy["release"] is True


def test_render_mode_points_at_committed_federation_assets() -> None:
    """Vue 渲染模式固定为 dist/assets，宿主据此加载 remoteEntry。"""
    assert WatchSync.get_render_mode() == ("vue", "dist/assets")


def test_dashboard_meta_and_api_surface_are_preserved() -> None:
    """迁移不得改动前端依赖的仪表盘与 API 契约。"""
    plugin = _bare_plugin()
    assert plugin.get_dashboard_meta() == [{"key": "watchsync", "name": "观看记录同步"}]
    api = plugin.get_api()
    assert [item["path"] for item in api] == EXPECTED_API_PATHS
    assert all(item["auth"] == "bear" for item in api)


def test_record_endpoints_return_failure_envelope_instead_of_raising(monkeypatch) -> None:
    """自有表读取异常时返回失败信封，不把异常抛给宿主接口层。"""
    plugin = _bare_plugin()

    def _boom(*args, **kwargs):
        raise RuntimeError("plugin_watchsync_record 表不可用")

    for name in ("_get_records_db", "_get_stats_db", "_clear_old_records_db"):
        monkeypatch.setattr(plugin, name, _boom)

    responses = (
        plugin._get_records_endpoint(),
        plugin._get_stats_endpoint(),
        plugin._clear_old_records_endpoint(30),
    )
    for response in responses:
        assert response["success"] is False
        assert "不可用" in response["message"]


def test_committed_federation_bundle_exposes_vue_components() -> None:
    """提交的 dist 必须能被宿主作为联邦远端加载并暴露三个组件。"""
    remote_entry = PLUGIN_DIR / "dist" / "assets" / "remoteEntry.js"
    assert remote_entry.is_file()

    source = remote_entry.read_text(encoding="utf-8")
    for expose in ('"./Page"', '"./Config"', '"./Dashboard"'):
        assert expose in source


def test_committed_bundle_does_not_publish_shared_vuetify_baseline_styles() -> None:
    """originjs 会为 shared 项遗留未引用的基础样式，提交前必须清理。"""
    leaked = sorted(PLUGIN_DIR.glob("**/__federation_shared_vuetify/styles-*.css"))
    assert leaked == [], f"提交了联邦共享基础样式: {leaked}"


def test_federation_config_declares_vuetify_as_host_shared_singleton() -> None:
    """宿主全局提供 Vuetify，插件侧共享声明不得重复生成基础样式。"""
    config = (PLUGIN_DIR / "vite.config.js").read_text(encoding="utf-8")
    assert "singleton: true" in config
    # 注释中会说明为什么不能声明 'vuetify/styles'，因此先去掉行注释再断言。
    code = "\n".join(line.split("//", 1)[0] for line in config.splitlines())
    assert "'vuetify/styles'" not in code
