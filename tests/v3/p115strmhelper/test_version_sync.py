"""115 网盘 STRM 助手：版本字段一致性单测。

该插件同时维护五处版本号：类属性 ``plugin_version``、``version.py`` 的
``VERSION``、前端 ``package.json`` 的 ``version``、市场索引 ``package.v3.json``
的 ``version`` 与最新 ``history`` 键。

上游写法是 ``plugin_version = VERSION``（Name 节点），但本仓库版本门禁用 AST
只识别字符串字面量，会判为「未声明类级 plugin_version」。因此这里把
``plugin_version`` 改成字面量，并用本用例锁住它与 ``version.py`` 的同步关系——
两处一旦漂移即失败。
"""
import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "plugins.v3" / "p115strmhelper"


def _class_version() -> str | None:
    """从类级赋值中取出 plugin_version 字面量，复现版本门禁的读取方式。"""
    tree = ast.parse((PLUGIN_DIR / "__init__.py").read_text(encoding="utf-8"))
    for class_node in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        for node in class_node.body:
            if (
                isinstance(node, ast.Assign)
                and any(
                    getattr(target, "id", None) == "plugin_version"
                    for target in node.targets
                )
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                return node.value.value
    return None


def test_plugin_version_is_a_string_literal():
    """门禁只认字面量；写成 VERSION 变量会让版本校验直接失败。"""
    assert _class_version() is not None


def test_version_py_matches_plugin_version():
    """version.py 的 VERSION 供 UA 等复用，必须与类属性同步。"""
    text = (PLUGIN_DIR / "version.py").read_text(encoding="utf-8")
    match = re.search(r'VERSION\s*=\s*"([^"]+)"', text)
    assert match is not None
    assert match.group(1) == _class_version()


def test_frontend_manifest_matches_plugin_version():
    """前端 package.json 的 version 需对齐，否则 pre-push 严格模式会失败。"""
    manifest = json.loads((PLUGIN_DIR / "package.json").read_text(encoding="utf-8"))
    assert manifest["version"] == _class_version()


def test_index_entry_matches_plugin_version():
    """市场索引 version 与最新 history 键都要与类属性一致。"""
    index = json.loads((REPO_ROOT / "package.v3.json").read_text(encoding="utf-8"))
    entry = index["P115StrmHelper"]
    assert entry["version"] == _class_version()
    assert next(iter(entry["history"])) == f"v{_class_version()}"
