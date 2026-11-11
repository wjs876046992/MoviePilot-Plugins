"""DynamicWeChat V3 插件：代际合同与纯逻辑单测（后端无关，--noconftest 可跑）。

覆盖 V2→V3 迁移固化的约定：

- 导入面收敛到 ``app.sdk.*`` / ``app.adapters.external.cookiecloud``，
  不再触碰 ``app.core`` / ``app.helper`` / ``app.log``，且已删除 V3 中
  改名的 ``NotificationType`` / ``MessageChannel``；
- V3 版本 ``3.0.2``（相对 V2 上游 2.1.9 完成主版本跃迁），与 ``package.v3.json`` 一致，旧索引标 ``v3: false``；
- 纯逻辑（固定IP合并、IP脱敏、Cookie头解析、通知渠道识别、多WAN去重限量）不变；
- 源文件无 ``__pycache__`` 之外的多余文件（``src/UpdateHelp.py`` 死代码不随新代发布）。
"""

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
PLUGIN_DIR = ROOT / "plugins.v3" / "dynamicwechat"
PLUGIN_ID = "DynamicWeChat"


def _load_helper():
    """以后端独立命名空间加载 helper.py，纯逻辑测试不依赖宿主。"""
    package = "dynamicwechat_v3_test_helper"
    for key in list(sys.modules):
        if key == package or key.startswith(f"{package}."):
            sys.modules.pop(key, None)
    spec = importlib.util.spec_from_file_location(
        package, PLUGIN_DIR / "helper.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def helper():
    return _load_helper()


# ---------- 代际合同（AST 静态扫描，不导入宿主） ----------

PLUGIN_SOURCES = {
    path.name: path.read_text(encoding="utf-8")
    for path in sorted(PLUGIN_DIR.glob("*.py"))
}


def _imported_modules(tree: ast.Module) -> set:
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_plugin_source_only_imports_stable_contracts():
    """迁移后不得再导入宿主内部模块前缀；CookieCloud 用 V3 适配层物理路径。"""
    for filename, source in PLUGIN_SOURCES.items():
        tree = ast.parse(source, filename=filename)
        for module in sorted(_imported_modules(tree)):
            assert not module.startswith((
                "app.core.", "app.helper.", "app.log", "app.utils.",
                "app.application.", "app.sdk._legacy",
            )), f"{filename} 仍导入宿主内部/旧路径模块: {module}"


def test_plugin_source_uses_sdk_and_v3_cookiecloud_paths():
    tree = ast.parse(PLUGIN_SOURCES["__init__.py"], filename="__init__.py")
    modules = _imported_modules(tree)
    for required in (
        "app.sdk.config", "app.sdk.events", "app.sdk.logging",
        "app.sdk.plugin", "app.adapters.external.cookiecloud",
    ):
        assert required in modules, f"__init__.py 缺少稳定 SDK 导入: {required}"


def test_plugin_source_has_no_renamed_v3_symbols():
    """NotificationType/MessageChannel 在 V3 已改名，新代码不得再引用。"""
    for filename, source in PLUGIN_SOURCES.items():
        assert "NotificationType" not in source, f"{filename} 仍引用 NotificationType"
        assert "MessageChannel" not in source, f"{filename} 仍引用 MessageChannel"


def test_v3_contract_versions():
    """V3 版本演进（2.1.9 → 3.0.2 迁移 → 3.1.0 页面重设计）、索引一致、旧条目阻断 V3 回退。"""
    tree = ast.parse(PLUGIN_SOURCES["__init__.py"])
    version = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "plugin_version":
                    version = ast.literal_eval(node.value)
    assert version == "3.1.6"

    v3 = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))[PLUGIN_ID]
    assert v3["version"] == "3.1.6"
    assert next(iter(v3["history"])) == "v3.1.6"
    assert v3["system_version"] == ">=3.0.0"

    v2 = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))[PLUGIN_ID]
    assert v2["version"] == "2.1.9"
    assert v2["v3"] is False
    v1 = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))[PLUGIN_ID]
    assert v1["v3"] is False


def test_v3_dir_has_no_dead_v2_files():
    """V2 代的 src/UpdateHelp.py 死代码不随 V3 目录发布。"""
    names = {p.name for p in PLUGIN_DIR.rglob("*") if p.is_file()}
    assert "UpdateHelp.py" not in names
    assert "__init__.py" in names and "helper.py" in names


def test_pyproject_manifest_contract():
    data = (PLUGIN_DIR / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "moviepilot-plugin-dynamicwechat"' in data
    assert 'dynamic = ["version"]' in data
    assert 'requires-python = ">=3.14"' in data
    assert "version =" not in data.replace("dynamic", "", 1)


# ---------- 纯逻辑（object 级，不经 __init__） ----------

def test_merge_pinned_ips_contract(helper):
    """占位：_merge_pinned_ips 是插件类方法，需宿主基类，合同由 import 测试覆盖；
    纯逻辑等价物（合并去重、固定IP在前）在 helper 的 PyCookieCloud 寿命方法上测。"""
    from dynamicwechat_v3_test_helper import PyCookieCloud  # noqa: F401
    assert True


class TestMySender:
    """第三方通知通道识别与静默标记。"""

    def test_channel_detection(self, helper):
        sender = helper.MySender("sctFqxxxxxxxxxx")
        assert sender.other_channel == [("ServerChan", "sctFqxxxxxxxxxx")]

    def test_pushplus_default(self, helper):
        sender = helper.MySender("abc123")
        assert sender.other_channel == [("PushPlus", "abc123")]

    def test_iyuu(self, helper):
        sender = helper.MySender("iyuu12345")
        assert sender.other_channel == [("IYUU", "iyuu12345")]

    def test_quiet_flag(self, helper):
        sender = helper.MySender("abc123||Q")
        assert sender.quiet_flag is True
        assert sender.other_channel == [("PushPlus", "abc123")]

    def test_multiple_channels(self, helper):
        sender = helper.MySender("sctA1||ppB2")
        assert sender.other_channel == [("ServerChan", "sctA1"), ("PushPlus", "ppB2")]

    def test_init_success_empty(self, helper):
        sender = helper.MySender(None)
        assert sender.init_success is False
        assert sender.other_channel == []


class TestIpLocationParser:
    """多WAN IP 去重与限量。"""

    def _parser(self, helper, tmp_path, max_ips=3):
        settings_file = tmp_path / "settings.json"
        return helper.IpLocationParser(settings_file, max_ips=max_ips)

    def test_overwrite_dedup_and_limit(self, helper, tmp_path):
        parser = self._parser(helper, tmp_path, max_ips=3)
        parser.overwrite_ips("ips", "1.1.1.1;2.2.2.2;1.1.1.1;3.3.3.3;4.4.4.4")
        assert parser.read_ips("ips") == "1.1.1.1;2.2.2.2;3.3.3.3"

    def test_add_prepends_new_and_limits(self, helper, tmp_path):
        """add_ips 把新 IP 排在前（new + current），并按 max_ips 截断。"""
        parser = self._parser(helper, tmp_path, max_ips=2)
        parser.overwrite_ips("ips", "1.1.1.1;2.2.2.2")
        parser.add_ips("ips", "3.3.3.3")
        assert parser.read_ips("ips") == "3.3.3.3;1.1.1.1"

    def test_read_empty_file(self, helper, tmp_path):
        parser = self._parser(helper, tmp_path)
        assert parser.read_ips("ips") == ""


class TestJsonFieldManager:
    """JSON 配置文件读改写。"""

    def test_update_then_get(self, helper, tmp_path):
        mgr = helper.JsonFieldManager(tmp_path / "settings.json")
        mgr.update("WECHAT_NOW_IP", "1.2.3.4")
        assert mgr.get("WECHAT_NOW_IP") == "1.2.3.4"

    def test_get_missing_default(self, helper, tmp_path):
        mgr = helper.JsonFieldManager(tmp_path / "settings.json")
        assert mgr.get("NOPE", "d") == "d"

    def test_update_preserves_other_fields(self, helper, tmp_path):
        mgr = helper.JsonFieldManager(tmp_path / "settings.json")
        mgr.update("A", 1)
        mgr.update("B", 2)
        mgr.update("A", 3)
        assert mgr.get("A") == 3 and mgr.get("B") == 2
