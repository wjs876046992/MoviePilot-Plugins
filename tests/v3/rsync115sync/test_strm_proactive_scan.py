"""
主动 strm 扫描的单测。

Tests for the proactive strm sweep.

**为什么需要这个功能**：观察模式只遍历「同步成功过」的文件，因此
「历史上传失败、插件从未认为它成功过」的文件永远进不了视野 ——
用户在 115 云端看到 `xxx.mkv..xrp4gj` 残留，插件这边毫无察觉。
主动扫描反其道而行：从**源端**出发逐个查该有的 .strm 在不在。

**为什么必须记录来源**：扫描的判据（源端有、strm 无）**无法区分**
「从未上传的存量」与「上传了但假成功」，前者是正常的、该走补传。
不标来源，用户会看到一批疑似却不知道该怎么处理。
"""

import os

import pytest

from app.plugins.rsync115sync import strm


def _pair(name="电视剧", src="/emby/TV", strm_dir="/strms/TV", all_ext=False):
    return {"name": name, "src": src, "dest": "/115/TV", "strm_dir": strm_dir, "all_ext": all_ext}


def _tree(tmp_path, structure):
    """
    按 {相对路径: 内容} 建目录树。

    Build a directory tree from {relative path: content}; a value of None means the
    entry is a directory.
    """
    for rel, content in structure.items():
        path = tmp_path / rel
        if content is None:
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def _real_list_dir(path):
    try:
        return os.listdir(path)
    except OSError:
        return None


def _scan(pairs, limit=500, exts=("mkv", "srt")):
    return strm.scan_candidates(
        pairs, _real_list_dir, limit,
        excluded_dirs=set(),
        valid_exts_for=lambda p: (None if p.get("all_ext") else set(exts)),
    )


# --------------------------------------------------------------------------
# 核心：找出缺 strm 的文件
# --------------------------------------------------------------------------

def test_finds_file_missing_strm(tmp_path):
    """用户实测场景：E03 上传失败（无 strm）、E01 正常（有 strm）→ 只报 E03。"""
    _tree(tmp_path, {
        "src/日番/黄泉的使者 (2026) {tmdbid=260463}/Season 01/E03.1080p.mkv": b"x",
        "src/日番/黄泉的使者 (2026) {tmdbid=260463}/Season 01/E01.1080p.mkv": b"x",
        "strm/日番/黄泉的使者 (2026) {tmdbid=260463}/Season 01/E01.1080p.strm": b"x",
    })
    pair = _pair(src=str(tmp_path / "src"), strm_dir=str(tmp_path / "strm"))

    candidates, truncated, checked = _scan([pair])

    assert truncated is False
    assert checked == 2
    assert len(candidates) == 1
    assert "E03.1080p.mkv" in candidates[0]
    assert candidates[0].startswith("电视剧:")


def test_returns_empty_when_all_strm_present(tmp_path):
    """全部正常时不得误报。"""
    _tree(tmp_path, {
        "src/a.mkv": b"x",
        "strm/a.strm": b"x",
    })
    pair = _pair(src=str(tmp_path / "src"), strm_dir=str(tmp_path / "strm"))
    candidates, truncated, checked = _scan([pair])
    assert candidates == []
    assert checked == 1


# --------------------------------------------------------------------------
# 过滤口径必须与同步一致
# --------------------------------------------------------------------------

def test_non_media_extension_is_not_checked(tmp_path):
    """.jpg/.nfo 永远不会被同步，不该出现在扫描结果里，也不该计入已检查数。"""
    _tree(tmp_path, {
        "src/a.mkv": b"x",
        "src/poster.jpg": b"x",
        "src/info.nfo": b"x",
        "strm/a.strm": b"x",
    })
    pair = _pair(src=str(tmp_path / "src"), strm_dir=str(tmp_path / "strm"))
    candidates, _, checked = _scan([pair])
    assert candidates == []
    assert checked == 1, "只有 a.mkv 应被检查"


def test_all_ext_pair_checks_everything(tmp_path):
    _tree(tmp_path, {
        "src/poster.jpg": b"x",
    })
    pair = _pair(src=str(tmp_path / "src"), strm_dir=str(tmp_path / "strm"), all_ext=True)
    candidates, _, checked = _scan([pair])
    assert checked == 1
    assert len(candidates) == 1


def test_excluded_dirs_are_pruned(tmp_path):
    """@eaDir 等元数据目录不参与扫描（与同步/搜索/补传同一口径）。"""
    _tree(tmp_path, {
        "src/@eaDir/junk.mkv": b"x",
        "src/keep.mkv": b"x",
        "strm/keep.strm": b"x",
    })
    pair = _pair(src=str(tmp_path / "src"), strm_dir=str(tmp_path / "strm"))
    candidates = strm.scan_candidates(
        [pair], _real_list_dir, 500,
        excluded_dirs={"@eaDir"},
        valid_exts_for=lambda p: {"mkv"},
    )[0]
    assert candidates == []


# --------------------------------------------------------------------------
# 映射筛选
# --------------------------------------------------------------------------

def test_pairs_without_strm_dir_are_skipped(tmp_path):
    """没配 strm_dir 的映射不参与扫描（否则会把整库都当成缺 strm）。"""
    _tree(tmp_path, {"src/a.mkv": b"x"})
    pair = _pair(src=str(tmp_path / "src"), strm_dir="")
    candidates, _, checked = _scan([pair])
    assert candidates == []
    assert checked == 0


def test_multiple_pairs_are_scanned_independently(tmp_path):
    """多个映射各自用自己的 strm 根，key 前缀也要正确区分。"""
    _tree(tmp_path, {
        "tv/a.mkv": b"x",
        "movies/b.mkv": b"x",
        "strmtv/a.strm": b"x",
    })
    pairs = [
        _pair(name="TV", src=str(tmp_path / "tv"), strm_dir=str(tmp_path / "strmtv")),
        _pair(name="MV", src=str(tmp_path / "movies"), strm_dir=str(tmp_path / "strmmv")),
    ]
    candidates, _, checked = _scan(pairs)
    assert checked == 2
    assert candidates == ["MV:b.mkv"]


# --------------------------------------------------------------------------
# 上限与截断
# --------------------------------------------------------------------------

def test_limit_truncates_and_reports(tmp_path):
    """
    达到上限必须停止并上报 truncated —— 否则 strm 插件大面积不工作时
    会一次涌出成千上万条，看板与通知都会被淹没。
    """
    structure = {f"src/f{i}.mkv": b"x" for i in range(20)}
    _tree(tmp_path, structure)
    pair = _pair(src=str(tmp_path / "src"), strm_dir=str(tmp_path / "strm"))

    candidates, truncated, checked = _scan([pair], limit=5)

    assert truncated is True
    assert len(candidates) == 5, "必须恰好停在上限，不能超收"
    assert checked <= 5, "达到上限后不应继续检查其它文件"


def test_limit_not_hit_reports_not_truncated(tmp_path):
    _tree(tmp_path, {"src/a.mkv": b"x"})
    pair = _pair(src=str(tmp_path / "src"), strm_dir=str(tmp_path / "strm"))
    candidates, truncated, _ = _scan([pair], limit=5)
    assert truncated is False
    assert len(candidates) == 1


# --------------------------------------------------------------------------
# 来源标记
# --------------------------------------------------------------------------

def test_origin_constants_are_distinct():
    """scan 与 watch 必须可区分，否则用户不知道疑似从哪来、该怎么处理。"""
    assert strm.ORIGIN_WATCH != strm.ORIGIN_SCAN


# --------------------------------------------------------------------------
# 期望路径（主动扫描依赖它，且已被真实路径验证）
# --------------------------------------------------------------------------

def test_expected_path_for_real_world_case():
    """
    真实路径回归：源端 `.../emby/TV/<rel>` → strm 端 `.../strms/TV/<rel>.strm`。
    仅换扩展名、目录结构照搬。
    """
    pair = _pair(src="/volume3/HomeTheater/emby/TV",
                 strm_dir="/volume3/HomeTheater/strms/TV")
    key = ("电视剧:日番/黄泉的使者 (2026) {tmdbid=260463}/Season 01/"
           "黄泉的使者 S01E03.1080p.friDay.WEB-DL.H264.AAC 2.0.mkv")
    got = strm.expected_path(key, [pair])
    assert got == (
        "/volume3/HomeTheater/strms/TV/日番/黄泉的使者 (2026) {tmdbid=260463}/Season 01/"
        "黄泉的使者 S01E03.1080p.friDay.WEB-DL.H264.AAC 2.0.strm"
    )


def test_expected_path_handles_multi_dot_filename():
    """文件名里含多个点时必须只切最后一个扩展名（真实文件正是这种形态）。"""
    # 注意 key 前缀必须与映射名一致，否则 expected_path 会（正确地）返回 None
    got = strm.expected_path("电视剧:A/x.1080p.WEB-DL.H264.AAC 2.0.mkv", [_pair()])
    assert got.endswith("x.1080p.WEB-DL.H264.AAC 2.0.strm")


# --------------------------------------------------------------------------
# 来源标记必须真的写进清单（变异测试发现的缺口）
# --------------------------------------------------------------------------

def test_scan_records_origin_as_scan():
    """
    扫描写入的条目，来源必须是 scan 而不是 watch。

    **这条用例是被变异测试逼出来的**：最初只断言了「两个来源常量不相等」，
    把扫描处硬写成 ORIGIN_WATCH 时测试依然全绿 —— 常量不同不代表代码用对了。
    来源错了用户就分不清「从未上传的存量」与「真的上传失败」，
    而两者的处理方式完全相反（补传 vs 删旧重传）。
    """
    plugin = _bare_plugin()
    assert plugin._strm_scan()["success"] is True
    assert len(plugin._strm_suspects) == 1
    entry = next(iter(plugin._strm_suspects.values()))
    assert entry["origin"] == strm.ORIGIN_SCAN, (
        f"主动扫描的来源应记为 scan，实际是 {entry['origin']}"
    )


def _bare_plugin():
    """构造只带扫描所需状态的最小实例（不碰真实文件系统之外的宿主能力）。"""
    import importlib
    module = importlib.import_module("app.plugins.rsync115sync")
    import tempfile

    root = tempfile.mkdtemp()
    src = os.path.join(root, "src")
    os.makedirs(src)
    with open(os.path.join(src, "a.mkv"), "wb") as fh:
        fh.write(b"x")
    # strm 端刻意留空 → a.mkv 应被判为缺 strm

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{
        "name": "电视剧", "src": src, "dest": "/115/TV",
        "strm_dir": os.path.join(root, "strm"), "all_ext": False,
    }]
    plugin._exclude_patterns = "@eaDir/\n#recycle/"
    plugin._media_extensions = "mkv"
    plugin._strm_check_enabled = True
    plugin._strm_suspects = {}
    plugin._notify = False
    plugin._strm_notified = False
    plugin.save_data = lambda k, v: None
    plugin.post_message = lambda **kw: None
    return plugin


def test_scan_is_idempotent_and_does_not_refresh_timestamp():
    """重复扫描不得刷新「首次疑似时间」—— 刷新会让「挂了多久」失去意义。"""
    plugin = _bare_plugin()
    plugin._strm_scan()
    first = dict(plugin._strm_suspects)
    result = plugin._strm_scan()
    assert plugin._strm_suspects == first
    assert result["data"]["added"] == 0
    assert result["data"]["found"] == len(first)


def test_scan_refuses_when_no_pair_has_strm_dir():
    """没有任何映射配置 strm 目录时必须明确拒绝，而不是把整库当缺 strm 报出来。"""
    plugin = _bare_plugin()
    plugin._sync_pairs[0]["strm_dir"] = ""
    result = plugin._strm_scan()
    assert result["success"] is False
    assert "strm 目录" in result["message"]


def test_scan_refuses_when_disabled():
    plugin = _bare_plugin()
    plugin._strm_check_enabled = False
    result = plugin._strm_scan()
    assert result["success"] is False
