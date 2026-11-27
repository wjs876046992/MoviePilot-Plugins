"""115 网盘 STRM 助手：依赖清单契约单测。

背景（NAS 上真实踩过）：``p115client==0.0.9.6.5.1`` 在 ``tool/upload.py``
里 ``from concurrenttools import threadpool_map, taskgroup_map``，而它的
元数据只声明 ``python-concurrenttools>=0.1.8``（无上界）。python-concurrenttools
0.1.9 已把这两个名字改名为 ``thread_conmap`` / ``async_conmap``，于是安装时
解析到 0.1.9 会让 p115client 导入即失败，插件以 ``load_failed`` 结束。

上游已把这个坑从根上解决：``p115client>=0.0.9.7.2`` 改用 ``thread_conmap`` /
``async_conmap``，元数据自带 ``Requires-Dist: python-concurrenttools (>=0.1.9)``，
故清单不再需要（也不再声明）``python-concurrenttools``。

这些用例锁住随之而来的清单约束：
1. ``p115client`` 精确锁定，且落在支持新 concurrenttools API 的版本线上；
2. 清单不再显式声明 ``python-concurrenttools``（避免与 p115client 自带的约束打架）；
3. 未发布到 PyPI 的三个 Rust 扩展必须有本地 wheel 来源声明；
4. 本地 wheel 目录真实存在且包含清单引用的文件。
"""
import tomllib
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugins.v3" / "p115strmhelper"
MANIFEST = PLUGIN_DIR / "pyproject.toml"
RUST_PACKAGES = ("full_strm_sync", "share_strm_scan", "txt_tree_storage")


@pytest.fixture(scope="module")
def manifest() -> dict:
    """读取插件 pyproject.toml，失败即测试失败（清单必须存在且可解析）。"""
    with MANIFEST.open("rb") as file_obj:
        return tomllib.load(file_obj)


def _dependency(manifest: dict, name: str) -> str | None:
    """按包名取依赖声明字符串，比较时忽略大小写与下划线/连字符差异。"""
    normalized = name.lower().replace("_", "-")
    for raw in manifest["project"]["dependencies"]:
        if raw.lower().replace("_", "-").startswith(normalized):
            return raw
    return None


def test_p115client_is_pinned_exactly(manifest):
    """p115client 必须精确锁定，且不得退回不支持新 concurrenttools API 的版本线。"""
    dependency = _dependency(manifest, "p115client")
    assert dependency is not None, "清单缺少 p115client 依赖"
    assert dependency.startswith("p115client=="), f"p115client 必须精确锁定，实际：{dependency}"
    version = dependency.split("==", 1)[1]
    assert tuple(int(part) for part in version.split(".")) >= (0, 0, 9, 7, 2), (
        f"p115client 需 >=0.0.9.7.2 才适配 concurrenttools 0.1.9 的 "
        f"thread_conmap / async_conmap，实际：{version}"
    )


def test_concurrenttools_is_not_pinned_manually(manifest):
    """p115client 的元数据已声明 python-concurrenttools>=0.1.9，清单不应再重复锁定。"""
    assert _dependency(manifest, "python-concurrenttools") is None, (
        "清单不应再声明 python-concurrenttools：p115client 自带 Requires-Dist 约束，"
        "重复声明会与上游版本线脱节"
    )


@pytest.mark.parametrize("package", RUST_PACKAGES)
def test_rust_package_declares_local_wheel_sources(manifest, package):
    """三个 Rust 扩展不在 PyPI 上，必须声明本地 wheel 来源。"""
    sources = manifest["tool"]["uv"]["sources"].get(package)
    assert sources, f"{package} 缺少 tool.uv.sources 本地来源声明"
    assert all(entry["path"].startswith("wheels/") for entry in sources)


@pytest.mark.parametrize("package", RUST_PACKAGES)
def test_rust_wheel_sources_exist_on_disk(manifest, package):
    """清单引用的每个 wheel 都必须在插件目录内真实存在。"""
    for entry in manifest["tool"]["uv"]["sources"][package]:
        wheel = PLUGIN_DIR / entry["path"]
        assert wheel.is_file(), f"缺少 wheel 文件：{wheel}"
