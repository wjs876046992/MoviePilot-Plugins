"""
残留识别：让「可见且大小一致」不再把改名失败的坏文件判成好的。

Residue detection: "visible and same size" must stop passing rename-failure
objects off as healthy files.

**为什么有这组测试**：用户实测反馈「疑似列表删除重传失败，文件大小是一致，
但名字不对，带 `..`，过度保护了」。根因是探测只比大小，而改名失败的残留
**大小与正式文件完全一致**（DEVELOPMENT 3.10 实测），因此「大小一致」对
改名失败这个主成因毫无鉴别力 —— 判据得换成「目录里有没有残留」。

这些用例全部来自**实测命名**（本机 rsync 3.4.1 中断传输实测：
`movie.mkv` → `.movie.mkv.WCTOKM` / `.film.mkv.c2Gfr2`）。
"""

import importlib

import pytest

from app.plugins.rsync115sync import paths, strm


# --------------------------------------------------------------------------
# paths.is_temp_residue_name —— 纯字符串判据
# --------------------------------------------------------------------------

OFFICIAL = "FC2-4730696-C-cd2.mp4"


@pytest.mark.parametrize("name", [
    ".FC2-4730696-C-cd2.mp4.WCTOKM",    # rsync 3.4.1 本机实测
    ".FC2-4730696-C-cd2.mp4.c2Gfr2",    # 同上，另一例
    "FC2-4730696-C-cd2.mp4..xrp4gj",    # 用户实际看到的形态（.. 在正式名后）
    "FC2-4730696-C-cd2.mp4.xrp4gj",     # 无前导点的形态
    ".FC2-4730696-C-cd2.mp4..xrp4gj",   # 两者叠加
])
def test_known_residue_spellings_are_detected(name):
    assert paths.is_temp_residue_name(name, OFFICIAL) is True


@pytest.mark.parametrize("name", [
    "FC2-4730696-C-cd2.mp4",             # 正式名本身不是残留
    "FC2-4730696-C-cd2.mp4.2024",        # 年份后缀（正规命名里很常见）
    "FC2-4730696-C-cd2.mp4.backup",      # 纯小写单词，看着像词不像随机串
    "FC2-4730696-C-cd2.mp4.abcdefghijk", # 过长
    "FC2-4730696-C-cd2.mp4.abc",         # 过短
    "Other.mp4..xrp4gj",                 # 别的正式名
    "FC2-4730696-C-cd2.srt..xrp4gj",     # 同名前缀、不同扩展名
    "",
])
def test_non_residue_names_are_rejected(name):
    assert paths.is_temp_residue_name(name, OFFICIAL) is False


def test_suffix_length_is_exactly_six():
    """
    后缀长度必须恰好 6。

    放宽成区间（例如 6–10）后 `影片.mkv.2024` 这类正常命名会落进判据，
    把一个好文件判成残留 ⇒ 用户对完好文件多做一次删旧重传。
    """
    assert paths.is_temp_residue_name(OFFICIAL + ".xrp4gj", OFFICIAL) is True
    assert paths.is_temp_residue_name(OFFICIAL + ".xrp4g", OFFICIAL) is False
    assert paths.is_temp_residue_name(OFFICIAL + ".xrp4gjj", OFFICIAL) is False


# --------------------------------------------------------------------------
# strm.dest_probe_outcome —— 残留判据必须**先于**大小判据
# --------------------------------------------------------------------------

def test_same_size_with_residue_is_not_ok():
    """
    核心回归：大小一致 + 有残留 ⇒ DEST_RESIDUE，绝不是 DEST_OK。

    这正是那条「白删」拦截的来源：残留的大小与正式文件一模一样（3.10 实测），
    只看大小的话它与完好文件无法区分。
    """
    got = strm.dest_probe_outcome(100, 100, dest_missing=False, residue_found=True)
    assert got == strm.DEST_RESIDUE
    assert got != strm.DEST_OK


def test_same_size_without_residue_is_ok():
    """没有残留时维持原判 —— 新判据只收窄「有证据说明坏了」的那一支。"""
    assert strm.dest_probe_outcome(100, 100, False, residue_found=False) == strm.DEST_OK


def test_absent_takes_precedence_over_residue():
    """
    不可见仍是 DEST_ABSENT。

    挂载视图只认正式名，改名失败时它可能连残留都看不到；此时「不可见」本身
    就是对症的判据（删旧重传是空操作），不该因残留维度改判。
    """
    assert strm.dest_probe_outcome(None, 100, True, residue_found=True) == strm.DEST_ABSENT


def test_unreadable_size_still_unknown():
    assert strm.dest_probe_outcome(None, 100, False, residue_found=True) == strm.DEST_UNKNOWN


def test_residue_check_precedes_size_check():
    """
    分支顺序是承重的：残留判定必须先于大小判定。

    残留存在时大小**必然**一致（它就是从正式文件改名失败来的），
    若先判大小就会返回 DEST_OK —— 把确凿的坏文件判成好的，
    也就是用户遇到的那次过度保护。
    """
    import inspect
    src = inspect.getsource(strm.dest_probe_outcome)
    assert src.index("residue_found") < src.index("dest_size == src_size")


# --------------------------------------------------------------------------
# 端到端：探测函数真的会去看目录
# --------------------------------------------------------------------------

def _plugin(root):
    module = importlib.import_module("app.plugins.rsync115sync")
    src = os.path.join(root, "src")
    dest = os.path.join(root, "dest")
    os.makedirs(src, exist_ok=True)
    os.makedirs(dest, exist_ok=True)
    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{
        "name": "9KG", "src": src, "dest": os.path.join(root, "dest"),
        "strm_dir": os.path.join(root, "strm"), "pan_dir": "/HomeTheater/TV",
        "all_ext": False,
    }]
    plugin._exclude_patterns = "@eaDir/"
    plugin._media_extensions = "mp4"
    plugin._ignored_rules = []
    return plugin, src, dest


import os  # noqa: E402  (放在此处以免与上面的常量区混在一起)


def test_probe_sees_residue_next_to_official_file(tmp_path):
    plugin, src, dest = _plugin(str(tmp_path))
    name = "FC2-4730696-C-cd2.mp4"
    for d in (src, dest):
        with open(os.path.join(d, name), "wb") as fh:
            fh.write(b"x" * 100)
    with open(os.path.join(dest, f".{name}.WCTOKM"), "wb") as fh:
        fh.write(b"x" * 100)  # 残留大小与正式文件一致

    verdict = plugin._dest_visibility(["9KG:" + name])["9KG:" + name]
    assert verdict == strm.DEST_RESIDUE


def test_probe_returns_ok_when_clean(tmp_path):
    plugin, src, dest = _plugin(str(tmp_path))
    name = "clean.mp4"
    for d in (src, dest):
        with open(os.path.join(d, name), "wb") as fh:
            fh.write(b"x" * 100)
    assert plugin._dest_visibility(["9KG:" + name])["9KG:" + name] == strm.DEST_OK


def test_unreadable_dir_is_treated_as_residue(tmp_path):
    """
    目录读不到时**保守判成有残留**。

    返回 False 会把它判成 DEST_OK，而 DEST_OK 在改名失败这一主成因下
    恰好是**错的那一边**；两种错误方向里宁可偏向「先别删、去查一下」。
    """
    plugin, src, dest = _plugin(str(tmp_path))
    name = "x.mp4"
    for d in (src, dest):
        with open(os.path.join(d, name), "wb") as fh:
            fh.write(b"x" * 100)
    # 缓存里把该目录标成「读不到」（listdir 抛 OSError 时的落盘形态）
    assert plugin._has_dest_residue(os.path.join(dest, name), {dest: None}) is True
