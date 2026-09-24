"""验证插件版本校验在本地 push、PR 和 Release 三个入口保持一致。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / ".github/scripts/check_plugin_versions.py"
CSS_CHECKER = REPO_ROOT / ".github/scripts/check_federation_css.py"
PRE_PUSH = REPO_ROOT / ".githooks/pre-push"
PR_WORKFLOW = REPO_ROOT / ".github/workflows/plugin-gate.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github/workflows/release.yml"
TEST_RUNNER = REPO_ROOT / "tests/run.py"


def _write_fixture(repo: Path, package_version: str, source_version: str) -> None:
    """构造最小 v2 插件仓，隔离验证 checker 与 Hook 的退出码。"""
    plugin_dir = repo / "plugins.v2/example"
    plugin_dir.mkdir(parents=True)
    (repo / "package.json").write_text("{}\n", encoding="utf-8")
    (repo / "package.v2.json").write_text(
        json.dumps(
            {
                "Example": {
                    "version": package_version,
                    "release": True,
                }
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(
        "class Example:\n"
        f'    plugin_version = "{source_version}"\n',
        encoding="utf-8",
    )
    checker_target = repo / ".github/scripts/check_plugin_versions.py"
    checker_target.parent.mkdir(parents=True)
    shutil.copy2(CHECKER, checker_target)
    shutil.copy2(CSS_CHECKER, repo / ".github/scripts/check_federation_css.py")


def _run_checker(repo: Path, *package_files: Path | str) -> subprocess.CompletedProcess[str]:
    """从指定目录运行 checker，便于覆盖 cwd 与 package 路径组合。"""
    args = ["python3", str(CHECKER)]
    args.extend(str(package_file) for package_file in package_files)
    return subprocess.run(
        args,
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


def test_checker_rejects_mismatched_versions(tmp_path: Path) -> None:
    """package 与源码版本不一致时必须返回失败，防止错误资产进入发布流程。"""
    _write_fixture(tmp_path, package_version="2.0.0", source_version="1.0.0")

    result = _run_checker(tmp_path, "package.json", "package.v2.json")

    assert result.returncode == 1
    assert "版本不一致" in result.stdout


def test_checker_resolves_plugin_dir_relative_to_package_file(tmp_path: Path) -> None:
    """从其他 cwd 调用时，插件目录应相对 package 文件定位。"""
    repo = tmp_path / "repo"
    _write_fixture(repo, package_version="2.0.0", source_version="2.0.0")

    result = _run_checker(tmp_path, repo / "package.json", repo / "package.v2.json")

    assert result.returncode == 0, result.stdout + result.stderr


def test_checker_reports_missing_release_plugin_dir(tmp_path: Path) -> None:
    """release=true 的插件缺少源码目录时应失败，避免发布项被静默跳过。"""
    repo = tmp_path / "repo"
    (repo / ".github/scripts").mkdir(parents=True)
    shutil.copy2(CHECKER, repo / ".github/scripts/check_plugin_versions.py")
    (repo / "package.json").write_text("{}\n", encoding="utf-8")
    (repo / "package.v2.json").write_text(
        json.dumps({"MissingPlugin": {"version": "1.0.0", "release": True}}),
        encoding="utf-8",
    )

    result = _run_checker(repo, "package.json", "package.v2.json")

    assert result.returncode == 1
    assert "缺少插件目录" in result.stdout
    assert "plugins.v2/missingplugin" in result.stdout


def test_checker_reads_class_level_plugin_version_only(tmp_path: Path) -> None:
    """只接受类级 plugin_version，避免函数内局部变量被误识别为插件版本。"""
    repo = tmp_path / "repo"
    _write_fixture(repo, package_version="1.2.3", source_version="0.0.0")
    init_file = repo / "plugins.v2/example/__init__.py"
    init_file.write_text(
        "def helper():\n"
        "    plugin_version = '1.2.3'\n"
        "    return plugin_version\n",
        encoding="utf-8",
    )

    result = _run_checker(repo, "package.json", "package.v2.json")

    assert result.returncode == 1
    assert "未在" in result.stdout
    assert "类级 plugin_version" in result.stdout


def test_checker_accepts_annotated_class_level_plugin_version(tmp_path: Path) -> None:
    """类级注解赋值的 plugin_version 也是有效插件版本声明。"""
    repo = tmp_path / "repo"
    _write_fixture(repo, package_version="1.2.3", source_version="0.0.0")
    init_file = repo / "plugins.v2/example/__init__.py"
    init_file.write_text(
        "class Example:\n"
        "    plugin_version: str = '1.2.3'\n",
        encoding="utf-8",
    )

    result = _run_checker(repo, "package.json", "package.v2.json")

    assert result.returncode == 0, result.stdout + result.stderr


def test_checker_validates_all_v3_entries_in_v3_directory(tmp_path: Path) -> None:
    """V3 独立实现即使不走 Release 资产也必须校验索引与源码版本。"""
    repo = tmp_path / "repo"
    plugin_dir = repo / "plugins.v3/example"
    plugin_dir.mkdir(parents=True)
    (repo / "package.v3.json").write_text(
        json.dumps({"Example": {"version": "3.0.1", "release": False}}),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(
        "class Example:\n    plugin_version = '3.0.0'\n",
        encoding="utf-8",
    )

    result = _run_checker(repo, "package.v3.json")

    assert result.returncode == 1
    assert "plugins.v3/example" in result.stdout
    assert "版本不一致" in result.stdout


def test_checker_rejects_v3_patch_bump_and_unsorted_history(tmp_path: Path) -> None:
    """V3 副本停留旧代主版本或历史倒序时必须被发布门禁拒绝（V3 大版本内补丁发布允许）。"""
    repo = tmp_path / "repo"
    plugin_dir = repo / "plugins.v3/example"
    plugin_dir.mkdir(parents=True)
    (repo / "package.json").write_text("{}\n", encoding="utf-8")
    (repo / "package.v2.json").write_text(
        json.dumps({"Example": {"version": "2.6.1", "v3": False}}),
        encoding="utf-8",
    )
    (repo / "package.v3.json").write_text(
        json.dumps(
            {
                "Example": {
                    "version": "2.6.2",
                    "history": {"v2.6.2": "错误补丁版本", "v2.7.0": "错误排序"},
                }
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(
        "class Example:\n    plugin_version = '2.6.2'\n",
        encoding="utf-8",
    )

    result = _run_checker(repo, "package.v3.json")

    assert result.returncode == 1
    assert "history 未按语义版本降序排列" in result.stdout
    assert "V3 版本应与旧代 2.6.1 保持大版本跃迁" in result.stdout


def test_pre_push_propagates_version_gate_failure(tmp_path: Path) -> None:
    """pre-push 必须传播 checker 非零状态，确保 git push 在上传前被拒绝。"""
    _write_fixture(tmp_path, package_version="2.0.0", source_version="1.0.0")
    hook_target = tmp_path / ".githooks/pre-push"
    hook_target.parent.mkdir(parents=True)
    shutil.copy2(PRE_PUSH, hook_target)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["sh", ".githooks/pre-push"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "插件版本门禁失败" in result.stdout


def test_pre_push_accepts_matching_versions(tmp_path: Path) -> None:
    """版本一致时 pre-push 应允许上传，避免正常插件发布被误拦截。"""
    _write_fixture(tmp_path, package_version="2.0.0", source_version="2.0.0")
    hook_target = tmp_path / ".githooks/pre-push"
    hook_target.parent.mkdir(parents=True)
    shutil.copy2(PRE_PUSH, hook_target)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["sh", ".githooks/pre-push"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "插件版本门禁通过" in result.stdout


def test_pr_workflow_runs_gate_for_every_main_pull_request() -> None:
    """Required Check 不得使用 paths 过滤，否则部分 PR 会一直缺少强制状态。"""
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "branches:" in workflow
    assert "- main" in workflow
    assert "paths:" not in workflow
    assert "name: Plugin release gate" in workflow
    assert (
        "python .github/scripts/check_plugin_versions.py "
        "package.json package.v2.json package.v3.json"
    ) in workflow


def test_current_repository_passes_version_gate() -> None:
    """启用 Ruleset 前真实 main 基线必须通过，否则所有 PR 都无法合并。"""
    result = subprocess.run(
        ["python3", str(CHECKER), "package.json", "package.v2.json", "package.v3.json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout


def test_full_test_runner_includes_ci_gate_tests() -> None:
    """V3 全量入口必须执行 CI、专用实现和仍兼容 V3 的 V2 实现。"""
    runner = TEST_RUNNER.read_text(encoding="utf-8")

    assert 'for generation in ("ci", "v3", "v2"):' in runner
    assert "compatible_v2_test_targets" in runner


def test_pr_workflow_uses_uv_backend_environment() -> None:
    """PR 门禁复用主程序锁定的 uv 测试环境。"""
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")

    assert "uv sync --locked" in workflow
    assert "../MoviePilot/.venv/bin/python tests/run.py" in workflow


def test_release_workflow_packages_missing_target_tag_from_v2_first() -> None:
    """缺少目标版本时必须打包，且同版本重复条目优先采用 V2 目录。"""
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert 'git diff --quiet "$tag" -- "$plugin_dir"' in workflow
    assert 'git tag --list "${plugin_id}_v*"' not in workflow
    assert workflow.index('process_package "package.v2.json"') < workflow.index(
        'process_package "package.json"'
    )
    assert workflow.index('process_package "package.json"') < workflow.index(
        'process_package "package.v3.json"'
    )


# --------------------------------------------------------------------------
# 门禁盲区：插件自带 package.json 与 Config.vue 版本 chip
# --------------------------------------------------------------------------
#
# 原先只比 package ↔ plugin_version，而 Vue 模式下这两个字段也会随版本推进，
# 漏改时门禁照旧「通过」（v0.2.2 踩过）。下面钉住三件事：
#   1) 漂移能被发现；
#   2) 无关插件的历史漂移**只警告、不阻断** —— 首次启用时仓库里已有 5 个插件
#      带着历史漂移，直接判失败会让任何人的 push 都过不去，而一个「一上来就
#      堵死所有人」的检查，下场一定是被绕过或放宽，那它就再也挡不住真正的漂移；
#   3) 被点名严格检查的插件（CHECK_STRICT_PLUGINS，pre-push 钩子按改动范围注入）
#      一旦漂移必须失败。


def _add_manifest(repo: Path, version: str) -> None:
    (repo / "plugins.v2/example/package.json").write_text(
        json.dumps({"name": "example", "version": version}) + "\n", encoding="utf-8"
    )


def _add_vue_chip(repo: Path, version: str) -> None:
    target = repo / "plugins.v2/example/src/components/Config.vue"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"<v-chip>v{version}</v-chip>\n", encoding="utf-8")


def _run_checker_strict(repo: Path, strict: str, *package_files: Path | str):
    """以 CHECK_STRICT_PLUGINS 指定的插件做严格判定。"""
    args = ["python3", str(CHECKER)]
    args.extend(str(f) for f in package_files)
    env = dict(os.environ, CHECK_STRICT_PLUGINS=strict)
    return subprocess.run(args, cwd=repo, text=True, capture_output=True,
                          check=False, env=env)


def test_manifest_drift_is_noticed_but_does_not_block(tmp_path: Path) -> None:
    """无关插件的清单漂移只提醒 —— 不能一上来就堵死所有人的 push。"""
    _write_fixture(tmp_path, package_version="2.0.0", source_version="2.0.0")
    _add_manifest(tmp_path, "1.0.0")

    result = _run_checker(tmp_path, "package.json", "package.v2.json")

    assert result.returncode == 0, result.stdout
    assert "package.json 版本漂移" in result.stdout
    assert "不阻断" in result.stdout


def test_manifest_drift_blocks_when_plugin_is_strict(tmp_path: Path) -> None:
    """正在改的插件漂移时必须失败，否则新引入的漂移照样溜过去。"""
    _write_fixture(tmp_path, package_version="2.0.0", source_version="2.0.0")
    _add_manifest(tmp_path, "1.0.0")

    result = _run_checker_strict(tmp_path, "example", "package.json", "package.v2.json")

    assert result.returncode == 1
    assert "package.json 版本漂移" in result.stdout


def test_ui_chip_drift_is_detected(tmp_path: Path) -> None:
    """
    配置页的版本 chip 漂移必须被发现。

    它是最容易被漏掉的一处：改了 plugin_version 与 package.json，界面却仍显示
    旧版本号 —— 用户据此判断「我装的到底是不是新版」，会直接误导排查。
    """
    _write_fixture(tmp_path, package_version="2.0.0", source_version="2.0.0")
    _add_vue_chip(tmp_path, "1.0.0")

    result = _run_checker_strict(tmp_path, "example", "package.json", "package.v2.json")

    assert result.returncode == 1
    assert "版本 chip 漂移" in result.stdout


def test_ui_chip_matching_is_accepted(tmp_path: Path) -> None:
    """chip 与版本一致时不得误报。"""
    _write_fixture(tmp_path, package_version="2.0.0", source_version="2.0.0")
    _add_vue_chip(tmp_path, "2.0.0")

    result = _run_checker_strict(tmp_path, "example", "package.json", "package.v2.json")

    assert result.returncode == 0, result.stdout


def test_plugins_without_manifest_or_chip_are_skipped(tmp_path: Path) -> None:
    """
    没有自带 package.json / 没有版本 chip 的插件一律跳过。

    这是刻意为之：本仓 V3 目录下多数插件没有自带清单，若把这些判成漂移，
    门禁会立刻失败一大片，随即被放宽 —— 那就再也挡不住真正的漂移。
    """
    _write_fixture(tmp_path, package_version="2.0.0", source_version="2.0.0")

    result = _run_checker_strict(tmp_path, "example", "package.json", "package.v2.json")

    assert result.returncode == 0, result.stdout
    assert "漂移" not in result.stdout
