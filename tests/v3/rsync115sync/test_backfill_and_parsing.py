"""
补传候选口径、确认序号解析、旧默认值迁移、退出码分类、伴生字幕匹配。

Back-fill candidate criteria, confirm-index parsing, legacy-default migration,
exit-code classification, and sidecar subtitle matching — the five remaining
P1 unit-test targets from TODO.md.

它们共同的特点是**判据写在运行时、边界容易写错，而错了不会报错**：
候选多一个白耗一次 stat、序号解析错一位传错文件、迁移写坏会覆盖用户配置、
退出码分类错会把失败谎报成成功、字幕多纳一个会跨集误传。
"""

import importlib
import os

import pytest

from app.plugins.rsync115sync import constants, paths


# ==========================================================================
# _parse_confirm_indices —— /rsync_confirm 的序号解析
# ==========================================================================

def _parse(arg, total):
    module = importlib.import_module("app.plugins.rsync115sync")
    return module.Rsync115Sync._parse_confirm_indices(arg, total)


def test_confirm_all_forms_select_everything():
    for arg in ("", "all", "ALL", "全部"):
        assert _parse(arg, 3) == [0, 1, 2], arg


def test_confirm_single_and_multiple():
    assert _parse("2", 5) == [1]
    assert _parse("1,3", 5) == [0, 2]
    assert _parse("1 3", 5) == [0, 2]


def test_confirm_range_and_mixed():
    assert _parse("1-3", 5) == [0, 1, 2]
    assert _parse("1~3", 5) == [0, 1, 2]
    assert _parse("1-2 4", 5) == [0, 1, 3]


def test_confirm_full_width_comma_and_tilde():
    """中文标点与 `~` 都要认 —— 手机上很容易打出全角逗号。"""
    assert _parse("1，3", 5) == [0, 2]
    assert _parse("2~3", 5) == [1, 2]


def test_confirm_deduplicates_and_sorts():
    """重复与乱序都要归一，否则调用方按下标取值会重复重传同一个文件。"""
    assert _parse("3,1,3", 5) == [0, 2]
    assert _parse("2 1", 5) == [0, 1]


def test_confirm_out_of_range_is_dropped_not_clamped():
    """
    越界序号**丢弃**而不是夹到边界。

    夹边界会把「用户打错了」变成「静默重传了最后一个文件」—— 而这一步的后果
    是删旧重传（破坏性）。宁可少选，也不替用户猜他想要哪个。
    """
    assert _parse("0", 3) == []
    assert _parse("4", 3) == []
    assert _parse("2-9", 3) == [1, 2]      # 范围内的保留，越界的丢掉
    assert _parse("abc", 3) == []


def test_confirm_reversed_range_is_normalised():
    assert _parse("3-1", 5) == [0, 1, 2]


# ==========================================================================
# _TOLERATED_EXIT_CODES —— 退出码分类
# ==========================================================================

def test_zero_and_tolerated_warnings_are_not_fatal():
    """
    0/23/24 都算成功。

    23（部分未传输）与 24（源文件传输中消失）是 rsync 的**正常波动**，
    把它们当失败会让整轮同步被误判、并推送错误告警。
    """
    assert 0 in constants.TOLERATED_EXIT_CODES
    assert 23 in constants.TOLERATED_EXIT_CODES
    assert 24 in constants.TOLERATED_EXIT_CODES


def test_real_errors_are_fatal():
    """
    其余非 0 码必须定为致命 —— 否则会把失败谎报成「已完整上传到位」。

    1/2 是语法与协议错误，12/13 是 I/O 与权限，30/35 是超时与连接中断：
    每一个都意味着**文件没传上去**，必须让整轮判定为失败。
    """
    for code in (1, 2, 12, 13, 30, 35):
        assert code not in constants.TOLERATED_EXIT_CODES, code


# ==========================================================================
# _migrate_legacy_defaults —— 自定义值必须不动
# ==========================================================================

def _migrator(root):
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._media_extensions = ""
    plugin._exclude_patterns = ""
    plugin._rsync_timeout = 0
    plugin._migrated = {}
    plugin.update_config = lambda cfg: plugin._migrated.update(cfg)
    plugin.save_data = lambda k, v: None
    return plugin


def test_legacy_defaults_are_migrated(tmp_path):
    plugin = _migrator(str(tmp_path))
    plugin._migrate_legacy_defaults({
        "media_extensions": constants.LEGACY_DEFAULTS["media_extensions"],
        "exclude_patterns": constants.LEGACY_DEFAULTS["exclude_patterns"],
        "rsync_timeout": constants.LEGACY_DEFAULTS["rsync_timeout"],
    })
    assert plugin._media_extensions == plugin.DEFAULT_MEDIA_EXTENSIONS
    assert plugin._exclude_patterns == plugin.DEFAULT_EXCLUDE_PATTERNS
    assert plugin._rsync_timeout == plugin.DEFAULT_RSYNC_TIMEOUT


@pytest.mark.parametrize("custom", [
    "mp4,mkv",                              # 用户自己精简过
    "mp4,mkv,avi,mov,ts,m2ts,iso,wmv,flv,rmvb,srt",   # 在旧默认上加了字幕
    "MKV,MP4",                              # 大小写不同（字符串比较不算相等）
])
def test_customised_extensions_are_never_overwritten(tmp_path, custom):
    """
    **本组最重要的一条**：用户只要改过一个字符，就完全不动。

    迁移写坏的后果是静默覆盖用户的配置 —— 他不会立刻发现，而是某天发现
    「有些文件不再同步了」。因此判据是**恰好等于**旧默认串，不是「差不多」。
    """
    plugin = _migrator(str(tmp_path))
    plugin._migrate_legacy_defaults({"media_extensions": custom})
    assert plugin._media_extensions == "", "自定义扩展名被迁移覆盖了"


def test_customised_exclude_and_timeout_are_untouched(tmp_path):
    plugin = _migrator(str(tmp_path))
    plugin._migrate_legacy_defaults({
        "exclude_patterns": "@eaDir/\n#recycle/\n@__thumb/\n.DS_Store\n..*",
        "rsync_timeout": 900,
    })
    assert plugin._exclude_patterns == ""
    assert plugin._rsync_timeout == 0


def test_migration_is_idempotent(tmp_path):
    """迁移后取值已等于新默认，重复调用不再匹配旧串，无副作用。"""
    plugin = _migrator(str(tmp_path))
    cfg = {"media_extensions": constants.LEGACY_DEFAULTS["media_extensions"]}
    plugin._migrate_legacy_defaults(cfg)
    first = plugin._media_extensions
    plugin._migrate_legacy_defaults(cfg)
    assert plugin._media_extensions == first


# ==========================================================================
# _find_sidecar_files —— 伴生字幕匹配
# ==========================================================================

def _plugin(root, *, media_ext="mkv", sidecar_exts=None):
    module = importlib.import_module("app.plugins.rsync115sync")
    src = os.path.join(root, "src")
    os.makedirs(src, exist_ok=True)
    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{"name": "电视剧", "src": src,
                           "dest": os.path.join(root, "dest"),
                           "strm_dir": os.path.join(root, "strm"),
                           "pan_dir": "/TV", "all_ext": False}]
    plugin._exclude_patterns = "@eaDir/"
    plugin._media_extensions = media_ext
    plugin._ignored_rules = []
    plugin._SIDECAR_EXTS = sidecar_exts or {"srt", "ass", "ssa"}
    plugin.save_data = lambda k, v: None
    return plugin, src


def _touch(path, content=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)


def test_sidecar_matches_same_stem_subtitles(tmp_path):
    plugin, src = _plugin(str(tmp_path))
    _touch(os.path.join(src, "剧名 S01E01.mkv"))
    _touch(os.path.join(src, "剧名 S01E01.zh.srt"))
    _touch(os.path.join(src, "剧名 S01E01.ass"))

    got = plugin._find_sidecar_files(src, "剧名 S01E01.mkv")
    assert sorted(got) == ["剧名 S01E01.ass", "剧名 S01E01.zh.srt"]


def test_sidecar_does_not_grab_other_episodes(tmp_path):
    """
    **本组最重要的一条**：不得跨集误纳。

    只认「主名 + `.` + 附加标记 + 字幕扩展名」—— 若放宽成「以主名前缀开头」，
    `剧名 S01E010.srt`（S01E01 的后缀）甚至同季所有集数都会被卷进来，
    而补传会真的把它们上传，属于静默放大。
    """
    plugin, src = _plugin(str(tmp_path))
    _touch(os.path.join(src, "剧名 S01E01.mkv"))
    _touch(os.path.join(src, "剧名 S01E01.zh.srt"))
    # 下面两个都不是 S01E01 的字幕，绝不能被纳入
    _touch(os.path.join(src, "剧名 S01E010.srt"))
    _touch(os.path.join(src, "剧名 S01E02.srt"))

    got = plugin._find_sidecar_files(src, "剧名 S01E01.mkv")
    assert got == ["剧名 S01E01.zh.srt"]


def test_sidecar_never_includes_the_media_file_itself(tmp_path):
    """
    `.mkv` 不是字幕扩展名，媒体文件自己不该被当成「伴生字幕」。

    若 SIDECAR_EXTS 与媒体扩展名交集非空，媒体文件会被重复加入候选，
    表现为「补传数量比实际文件数多」。
    """
    plugin, src = _plugin(str(tmp_path))
    _touch(os.path.join(src, "剧名 S01E01.mkv"))
    got = plugin._find_sidecar_files(src, "剧名 S01E01.mkv")
    assert got == []


def test_sidecar_ignores_directories_named_like_subtitles(tmp_path):
    """
    以字幕扩展名结尾的**目录**不能被当成字幕文件。

    真实场景：某些工具会生成 `xxx.srt/` 这种目录。若只按名字判断，它会进入
    候选并交给 rsync，rsync 随后以「不是普通文件」失败，整批退出码被拖成非 0。
    """
    plugin, src = _plugin(str(tmp_path))
    _touch(os.path.join(src, "剧名 S01E01.mkv"))
    os.makedirs(os.path.join(src, "剧名 S01E01.zh.srt"))     # 目录，不是文件

    got = plugin._find_sidecar_files(src, "剧名 S01E01.mkv")
    assert got == []


def test_sidecar_respects_nested_relative_path(tmp_path):
    plugin, src = _plugin(str(tmp_path))
    rel = "Season 01/剧名 S01E01.mkv"
    _touch(os.path.join(src, rel))
    _touch(os.path.join(src, "Season 01/剧名 S01E01.srt"))

    got = plugin._find_sidecar_files(src, rel)
    assert got == ["Season 01/剧名 S01E01.srt"]


def test_sidecar_returns_empty_for_unreadable_dir(tmp_path):
    """
    目录读不到时返回空列表而不是抛异常。

    调用它的是补传扫描，一个不可读的目录不该让整个扫描崩掉 —— 少纳几个字幕
    是可接受的降级，扫描失败不是。
    """
    plugin, src = _plugin(str(tmp_path))
    got = plugin._find_sidecar_files(src, "不存在的目录/a.mkv")
    assert got == []


# ==========================================================================
# _build_backfill_candidates —— 候选口径
# ==========================================================================

def _bf_plugin(root, *, pending=None, anomalies=None, ignored=None, all_ext=False):
    module = importlib.import_module("app.plugins.rsync115sync")
    src = os.path.join(root, "src")
    os.makedirs(src, exist_ok=True)
    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{"name": "电视剧", "src": src,
                           "dest": os.path.join(root, "dest"),
                           "strm_dir": os.path.join(root, "strm"),
                           "pan_dir": "/TV", "all_ext": all_ext}]
    plugin._exclude_patterns = "@eaDir/"
    plugin._media_extensions = "mkv"
    plugin._ignored_rules = list(ignored or [])
    plugin._pending_queue = dict(pending or {})
    plugin._last_status = {"missing_files": list(anomalies or []),
                           "corrupt_files": []}
    plugin._SIDECAR_EXTS = {"srt"}
    plugin.save_data = lambda k, v: None
    return plugin, src


def test_backfill_excludes_queued_anomalous_and_ignored(tmp_path):
    """
    候选是「插件**从未处理过**的存量文件」，三个排除口径缺一不可：

      · 冷却队列里 → 正常流程会处理，补传重复
      · 异常清单里 → 走 /rsync_retry，补传路径不同（补传不删旧）
      · 忽略清单里 → 用户明确说过别再传
    """
    plugin, src = _bf_plugin(
        str(tmp_path),
        pending={"电视剧:cooling.mkv": 1.0},
        anomalies=["电视剧:missing.mkv"],
        ignored=[{"rule": "电视剧:ignored.mkv", "match": "exact"}],
    )
    for name in ("cooling.mkv", "missing.mkv", "ignored.mkv", "fresh.mkv"):
        _touch(os.path.join(src, name))

    got = plugin._build_backfill_candidates()
    assert got == ["电视剧:fresh.mkv"]


def test_backfill_skips_junk_and_wrong_extension(tmp_path):
    plugin, src = _bf_plugin(str(tmp_path))
    _touch(os.path.join(src, "ok.mkv"))
    _touch(os.path.join(src, ".DS_Store"))
    _touch(os.path.join(src, "._ok.mkv"))       # AppleDouble 资源分叉
    _touch(os.path.join(src, "readme.txt"))

    got = plugin._build_backfill_candidates()
    assert got == ["电视剧:ok.mkv"]


def test_backfill_all_ext_includes_everything(tmp_path):
    """勾了「同步所有类型」时不按扩展名过滤，否则该选项形同虚设。"""
    plugin, src = _bf_plugin(str(tmp_path), all_ext=True)
    _touch(os.path.join(src, "ok.mkv"))
    _touch(os.path.join(src, "note.txt"))
    got = plugin._build_backfill_candidates()
    assert "电视剧:note.txt" in got


def test_backfill_prunes_excluded_dirs(tmp_path):
    """@eaDir/ 等排除目录必须**就地剪枝**（不下钻），否则白扫整棵子树。"""
    plugin, src = _bf_plugin(str(tmp_path))
    _touch(os.path.join(src, "ok.mkv"))
    _touch(os.path.join(src, "@eaDir", "hidden.mkv"))

    got = plugin._build_backfill_candidates()
    assert got == ["电视剧:ok.mkv"]


def test_backfill_attaches_sidecars(tmp_path):
    plugin, src = _bf_plugin(str(tmp_path))
    _touch(os.path.join(src, "ep.mkv"))
    _touch(os.path.join(src, "ep.srt"))

    got = plugin._build_backfill_candidates()
    assert set(got) == {"电视剧:ep.mkv", "电视剧:ep.srt"}


def test_backfill_deduplicates(tmp_path):
    """同一个文件只出现一次，否则会被重复上传。"""
    plugin, src = _bf_plugin(str(tmp_path))
    _touch(os.path.join(src, "ep.mkv"))
    got = plugin._build_backfill_candidates()
    assert len(got) == len(set(got))
