"""
核心同步链路的纯逻辑单测：哪些文件会被同步、归属哪组映射、口径是否一致。

Pure-logic tests for the core sync path: which files sync, which mapping owns
them, and whether the filtering criteria agree across code paths.

**为什么这几个函数值得优先测**：它们决定了「文件到底会不会被同步」。
一旦出错，表现是「入库了但永远不上传」或「传到了错误的目标目录」——
前者静默、后者破坏性，而且都不会有任何报错。
"""

import os

import pytest

from app.plugins.rsync115sync import paths


def _pair(name="TV", src="/media/TV", dest="/115/TV", strm_dir="", all_ext=False):
    return {"name": name, "src": src, "dest": dest, "strm_dir": strm_dir, "all_ext": all_ext}


# --------------------------------------------------------------------------
# pair_for_path —— 决定文件归属哪组映射
# --------------------------------------------------------------------------

def test_pair_for_path_matches_file_directly_under_root():
    pair = _pair()
    assert paths.pair_for_path("/media/TV/a.mkv", [pair]) is pair


def test_pair_for_path_matches_path_equal_to_root():
    """路径恰好等于源根目录本身（目录级事件）也应归属该映射。"""
    pair = _pair()
    assert paths.pair_for_path("/media/TV", [pair]) is pair


def test_pair_for_path_rejects_sibling_prefix():
    """
    关键回归：`/media/TV` 不能吞掉 `/media/TV2/...`。

    写成裸 startswith 时两者都命中，文件会被挂到 TV 映射上，并按 TV 的 src
    计算相对路径 —— 结果上传到 TV 的 115 目录，即**送错目标**。
    """
    pair = _pair()
    assert paths.pair_for_path("/media/TV2/a.mkv", [pair]) is None
    assert paths.pair_for_path("/media/TVX/a.mkv", [pair]) is None


def test_pair_for_path_ignores_trailing_slash_in_config():
    """用户在配置页填了尾斜杠时，归属判定不应受影响。"""
    assert paths.pair_for_path("/media/TV/a.mkv", [_pair(src="/media/TV/")]) is not None
    assert paths.pair_for_path("/media/TV/a.mkv", [_pair(src="  /media/TV/  ")]) is not None


def test_pair_for_path_skips_empty_src():
    """未填源目录的映射不能匹配任何路径（否则会把全库都算作它的）。"""
    empty = _pair(name="空", src="")
    real = _pair(name="真", src="/media/TV")
    assert paths.pair_for_path("/media/TV/a.mkv", [empty, real]) is real


def test_pair_for_path_returns_first_match_on_overlap():
    """前缀重叠时取第一个，与配置顺序一致（行为已文档化，不应悄悄改变）。"""
    outer = _pair(name="outer", src="/media")
    inner = _pair(name="inner", src="/media/TV")
    assert paths.pair_for_path("/media/TV/a.mkv", [outer, inner]) is outer
    assert paths.pair_for_path("/media/TV/a.mkv", [inner, outer]) is inner


def test_pair_for_path_empty_path_is_unmatched():
    assert paths.pair_for_path("", [_pair()]) is None


# --------------------------------------------------------------------------
# pair_name —— 队列 key 的前缀来源
# --------------------------------------------------------------------------

def test_pair_name_prefers_label_then_falls_back_to_src():
    assert paths.pair_name(_pair(name="剧集")) == "剧集"
    assert paths.pair_name(_pair(name="", src="/media/TV/")) == "/media/TV"


def test_pair_name_is_stable_across_repeated_calls():
    """
    幂等且与调用次数无关：pair_name 曾以 9 处硬编码的形式散落各处，
    写法不一致会导致同一文件在不同代码路径下得到不同的 key 前缀，
    表现为「事件入队了、同步时找不到」。
    """
    pair = _pair(name=" 剧集 ", src="/media/TV/")
    assert paths.pair_name(pair) == paths.pair_name(pair) == "剧集"


# --------------------------------------------------------------------------
# split_pair_key —— 反向解析（重试/删除等破坏性操作的输入）
# --------------------------------------------------------------------------

def test_split_pair_key_roundtrips_with_pair_name():
    pair = _pair(name="剧集", src="/media/TV")
    key = f"{paths.pair_name(pair)}:Season 01/a.mkv"
    assert paths.split_pair_key(key, [pair]) == (pair, "Season 01/a.mkv")


def test_split_pair_key_tolerates_colon_inside_path():
    """相对路径里含冒号时必须整体保留，不能被截断。"""
    pair = _pair(name="剧集")
    assert paths.split_pair_key("剧集:a:b/c.mkv", [pair]) == (pair, "a:b/c.mkv")


def test_split_pair_key_unknown_prefix_is_none():
    """不属于任何映射的 key 必须返回 None —— 删除类操作据此拒绝执行。"""
    assert paths.split_pair_key("其它:a.mkv", [_pair(name="剧集")]) is None


def test_split_pair_key_no_pairs():
    assert paths.split_pair_key("剧集:a.mkv", []) is None


# --------------------------------------------------------------------------
# 过滤口径一致性 —— 扩展名与排除目录
# --------------------------------------------------------------------------

def test_valid_exts_of_returns_none_when_all_ext():
    """all_ext 时必须返回 None 而不是空集合：空集合会静默过滤掉**全部**文件。"""
    assert paths.valid_exts_of("mkv,srt", all_ext=True) is None
    assert paths.valid_exts_of("mkv,srt", all_ext=False) == {"mkv", "srt"}


def test_valid_exts_of_normalises_case_and_spaces():
    assert paths.valid_exts_of(" MKV , SrT ,, ", all_ext=False) == {"mkv", "srt"}


def test_valid_exts_of_empty_string_yields_empty_set():
    """空配置 + 非 all_ext = 什么都不传。这是「配置没填」应有的表现，不能变成「全都传」。"""
    assert paths.valid_exts_of("", all_ext=False) == set()


def test_excluded_dir_names_only_takes_directory_rules():
    """
    只认以 `/` 结尾的规则行。`.DS_Store` 这类**文件**规则不能被当成目录名，
    否则 os.walk 会把同名目录整棵剪掉。
    """
    patterns = "@eaDir/\n#recycle/\n@__thumb/\n.DS_Store\n..*"
    assert paths.excluded_dir_names(patterns) == {"@eaDir", "#recycle", "@__thumb"}


def test_excluded_dir_names_ignores_dot_prefixed_and_blank_lines():
    patterns = "\n  \n.hidden/\n.recycle/\nnormal/\n"
    assert paths.excluded_dir_names(patterns) == {"normal"}


def test_excluded_dir_names_empty_input():
    assert paths.excluded_dir_names("") == set()
    assert paths.excluded_dir_names(None) == set()


# --------------------------------------------------------------------------
# brief_paths —— 只影响日志，但截断错误会让排查失去依据
# --------------------------------------------------------------------------

def test_brief_paths_caps_count_and_reports_total():
    text = paths.brief_paths([f"/p/{i}" for i in range(9)])
    assert text.count("/p/") == 5
    assert "等共 9 个" in text


def test_brief_paths_truncates_long_paths_keeping_tail():
    """截断保留**尾部**：文件名在尾部，保留头部会让日志看不出是哪个文件。"""
    long_path = "/very/long/prefix/" + "x" * 300 + "/target.mkv"
    text = paths.brief_paths([long_path])
    assert "target.mkv" in text
    assert len(text) < len(long_path)


def test_brief_paths_empty_list():
    assert paths.brief_paths([]) == ""

# --------------------------------------------------------------------------
# rel_path_of_key — 队列 key 还原相对路径必须用前缀匹配
# --------------------------------------------------------------------------

def test_rel_path_of_key_plain_name():
    assert paths.rel_path_of_key("TV:S01E01.mkv", [_pair(name="TV")]) == "S01E01.mkv"


def test_rel_path_of_key_label_containing_colon():
    """
    任务名含冒号时 `split(":", 1)` 会切错 —— 这是本函数存在的唯一理由。

    key `TV:主库:S01E01.mkv` 在**第一个**冒号处切开得到 `主库:S01E01.mkv`，
    相对路径凭空多出一段；用它拼文件系统路径时该文件永远不存在，表现为
    「文件明明在、却判为源端已消失」（strm 条目被 source_gone 清理、
    目标端可见性探测报 unknown）。前缀匹配才可靠（同 split_pair_key 判据）。
    """
    pairs = [_pair(name="TV:主库")]
    key = "TV:主库:S01E01.mkv"
    assert paths.rel_path_of_key(key, pairs) == "S01E01.mkv"
    # 对照：旧实现在同一输入上是错的，锁住这条差异
    assert key.split(":", 1)[1] == "主库:S01E01.mkv"


def test_rel_path_of_key_relative_path_containing_colon():
    """相对路径本身含冒号（罕见但合法）也必须完整保留。"""
    pairs = [_pair(name="TV")]
    assert paths.rel_path_of_key("TV:S01E:alt.mkv", pairs) == "S01E:alt.mkv"


def test_rel_path_of_key_unknown_mapping_returns_none():
    assert paths.rel_path_of_key("Other:x.mkv", [_pair(name="TV")]) is None


def test_rel_path_of_key_empty_pairs_returns_none():
    assert paths.rel_path_of_key("TV:x.mkv", []) is None
    assert paths.rel_path_of_key("TV:x.mkv", None) is None


def test_rel_path_of_key_prefers_longest_matching_prefix():
    """
    两个映射名互为前缀时（TV 与 TV:主库），key 必须归属到**真正匹配的那个**。

    逐对比较按 `startswith(f"{pn}:")`，`TV:主库:S01E01.mkv` 同时满足
    `TV:` 前缀 —— 但只有 `TV:主库:` 是完整的一段，因此取到的相对路径
    才是对的。这条同时钉住「不能退化成按第一个冒号切」。
    """
    pairs = [_pair(name="TV"), _pair(name="TV:主库")]
    assert paths.rel_path_of_key("TV:主库:S01E01.mkv", pairs) == "S01E01.mkv"


def test_rel_path_of_key_trailing_slash_in_src_label():
    """未填备注名时回退到源目录；带尾斜杠的 src 也必须能匹配上。"""
    pairs = [{"name": "", "src": "/media/TV/", "dest": "/115/TV"}]
    assert paths.rel_path_of_key("/media/TV:S01E01.mkv", pairs) == "S01E01.mkv"
