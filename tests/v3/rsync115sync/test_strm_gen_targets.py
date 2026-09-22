"""
借道 strm 助手补生成：目标目录折算的单测。

Tests for turning suspect keys into helper-side cloud directories.

**为什么需要这个功能**：疑似清单里的条目有两种成因 ——「strm 插件漏生成」
（云端文件是好的，重新生成指针即可）与「CD2 假成功」（云端只有半成品，必须
删旧重传）。两者在本地视角**完全无法区分**，处理成本却差好几个数量级。
借助手遍历一次云端目录就能判别：生成成功 ⇒ 前者，省下整轮删除重传。

**为什么必须逐目录去重**：助手对**每个参数**都会遍历该目录的整个云端子树，
所以真实成本由「目录数」而非「文件数」决定。20 个文件散在 3 个季节目录时，
按目录只产生 3 次小规模遍历。

**为什么上限要显式回传被截断的文件**：它们仍在疑似清单里。若静默丢弃，用户
会看到「点了按钮但一部分毫无动静」，并且以为整批都处理过了 —— 于是不再关注
那些条目。这是最坏的结果，比直接拒绝执行更糟。
"""

from app.plugins.rsync115sync import strm


def _pair(name="电视剧", src="/emby/TV", strm_dir="/media/strms/TV", pan_dir="/HomeTheater/TV"):
    return {"name": name, "src": src, "dest": "/115/TV",
            "strm_dir": strm_dir, "pan_dir": pan_dir}



# --------------------------------------------------------------------------
# 显式配置的网盘目录
# --------------------------------------------------------------------------

def test_pan_dir_comes_from_pair_config():
    """网盘目录取自映射的 pan_dir 字段，而不是从任何地方推导。"""
    pairs = [_pair(pan_dir="/HomeTheater/TV")]
    assert strm.pan_dir_of("电视剧:日番/A/Season 01/E01.mkv", pairs) == "/HomeTheater/TV"


def test_pan_dir_absent_returns_none():
    """未配 pan_dir 的映射返回 None —— 调用方据此明确拒绝并提示怎么配。"""
    assert strm.pan_dir_of("电视剧:a.mkv", [_pair(pan_dir="")]) is None
    assert strm.pan_dir_of("电视剧:a.mkv", [_pair(pan_dir="   ")]) is None
    assert strm.pan_dir_of("电视剧:a.mkv", [_pair(pan_dir=None)]) is None


def test_pan_dir_unknown_pair_returns_none():
    assert strm.pan_dir_of("别的任务:a.mkv", [_pair(pan_dir="/HomeTheater/TV")]) is None


# --------------------------------------------------------------------------
# 疑似文件 → 目录参数
# --------------------------------------------------------------------------

def test_gen_targets_uses_file_parent_dir():
    """
    参数收窄到该文件**所在的目录**，而不是整个映射根 —— 这是成本的核心。

    助手收到 `/HomeTheater/TV` 会遍历整个 TV 库（上万文件）；
    收到 `/HomeTheater/TV/日番/黄泉的使者 (2026) {tmdbid=260463}/Season 01`
    只遍历那一季。
    """
    pairs = [_pair()]
    dirs, matched, unmatched, truncated = strm.gen_targets_for_suspects(
        ["电视剧:日番/黄泉的使者 (2026) {tmdbid=260463}/Season 01/E03.mkv"],
        pairs, limit=20)

    assert dirs == ["/HomeTheater/TV/日番/黄泉的使者 (2026) {tmdbid=260463}/Season 01"]
    assert matched == ["电视剧:日番/黄泉的使者 (2026) {tmdbid=260463}/Season 01/E03.mkv"]
    assert unmatched == []
    assert truncated is False


def test_gen_targets_dedups_by_directory():
    """同目录下多个疑似文件只产生**一个**目录参数（逐目录去重的实质收益）。"""
    pairs = [_pair()]
    dirs, matched, _, _ = strm.gen_targets_for_suspects(
        ["电视剧:日番/A/Season 01/E01.mkv",
         "电视剧:日番/A/Season 01/E02.mkv",
         "电视剧:日番/A/Season 01/E03.mkv"],
        pairs, limit=20)

    assert dirs == ["/HomeTheater/TV/日番/A/Season 01"]
    assert len(matched) == 3, "三个文件都应纳入本次补生成"


def test_gen_targets_root_level_file_uses_pan_root():
    """直接落在映射根下的文件（无子目录）参数就是网盘根。"""
    pairs = [_pair()]
    dirs, _, _, _ = strm.gen_targets_for_suspects(
        ["电视剧:movie.mkv"], pairs, limit=20)
    assert dirs == ["/HomeTheater/TV"]


def test_gen_targets_unmatched_when_pan_dir_missing():
    """未配 pan_dir 的映射归入无法归属，且**不能**被推导出来凑数。"""
    pairs = [_pair(name="无网盘目录", src="/emby/X", pan_dir="")]
    dirs, matched, unmatched, _ = strm.gen_targets_for_suspects(
        ["无网盘目录:a.mkv"], pairs, limit=20)

    assert dirs == []
    assert matched == []
    assert unmatched == ["无网盘目录:a.mkv"]


# --------------------------------------------------------------------------
# 上限保护
# --------------------------------------------------------------------------

def test_gen_targets_truncates_beyond_dir_limit():
    """
    目录数超过上限即停止纳入，并**把被截断的文件显式回传**。

    调用方据此告知「这一批本次跳过」；静默遗漏会让用户以为整批都处理过了。
    """
    pairs = [_pair()]
    keys = [f"电视剧:剧{i}/Season 01/E01.mkv" for i in range(5)]

    dirs, matched, unmatched, truncated = strm.gen_targets_for_suspects(
        keys, pairs, limit=3)

    assert truncated is True
    assert len(dirs) == 3
    assert len(matched) == 3, "只有前 3 个目录被纳入"
    assert len(unmatched) == 2, "被截断的必须显式回传，不能静默丢弃"


def test_gen_targets_files_in_already_seen_dir_not_dropped_by_limit():
    """
    上限只对**新目录**计数：已纳入目录下的后续文件不受影响。

    否则会出现「同一季的 E01 处理了、E02 被砍」这种反直觉结果 ——
    明明一次遍历就能同时覆盖，却因为计数口径写成「文件数」而漏掉。
    """
    pairs = [_pair()]
    keys = ["电视剧:剧A/Season 01/E01.mkv",
            "电视剧:剧B/Season 01/E01.mkv",
            "电视剧:剧A/Season 01/E02.mkv",
            "电视剧:剧A/Season 01/E03.mkv"]

    dirs, matched, unmatched, truncated = strm.gen_targets_for_suspects(
        keys, pairs, limit=2)

    assert truncated is False
    assert len(dirs) == 2
    assert len(matched) == 4, "剧A 的三个文件同属一个目录，都应纳入"
    assert unmatched == []


def test_gen_targets_limit_zero_accepts_nothing():
    """上限为 0 时一个都不发（配置可用来临时停用该能力）。"""
    pairs = [_pair()]
    dirs, matched, unmatched, truncated = strm.gen_targets_for_suspects(
        ["电视剧:剧A/Season 01/E01.mkv"], pairs, limit=0)
    assert dirs == [] and matched == [] and truncated is True


# --------------------------------------------------------------------------
# 用真实环境的配置形态做端到端折算
# --------------------------------------------------------------------------

# 实机映射（简化：只保留路径相关字段）。pan_dir 即用户在配置页显式填写的网盘目录。
REAL_PAIRS = [
    {"name": "电视剧", "src": "/media/emby/TV", "dest": "/CloudNAS/115/TV",
     "strm_dir": "/media/strms/TV", "pan_dir": "/HomeTheater/TV", "all_ext": False},
    {"name": "电影", "src": "/media/emby/Movies", "dest": "/CloudNAS/115/Movies",
     "strm_dir": "/media/strms/Movies", "pan_dir": "/HomeTheater/Movies", "all_ext": False},
    # 9KG：用户**没有**填网盘目录 → 该映射不支持补生成。
    # 这是实机真实情况（助手只认它 full_sync_strm_paths 里的路径，而 9KG 不在其中），
    # 必须如实拒绝并提示怎么配，绝不能靠推导凑出一个大概率被助手拒绝的路径。
    {"name": "9KG", "src": "/media/emby/9KG", "dest": "/CloudNAS/115/9KG",
     "strm_dir": "/media/strms/9KG", "pan_dir": "", "all_ext": True},
]


def test_real_world_user_scenario():
    """
    用户实机场景：E03 缺 strm（实测案例），验证折算出的网盘目录参数。

    期望参数精确到**季目录**，而不是整个 TV 库 —— 若退化成映射根，
    助手会遍历上万文件，成本与「整库全量」同级，这个功能就失去意义了。
    """
    key = "电视剧:日番/黄泉的使者 (2026) {tmdbid=260463}/Season 01/黄泉的使者 S01E03.1080p.mkv"

    dirs, matched, unmatched, truncated = strm.gen_targets_for_suspects(
        [key], REAL_PAIRS, limit=20)

    assert dirs == ["/HomeTheater/TV/日番/黄泉的使者 (2026) {tmdbid=260463}/Season 01"]
    assert matched == [key]
    assert unmatched == []
    assert truncated is False


def test_real_world_pair_without_pan_dir_is_reported():
    """未填网盘目录的映射（实机 9KG）必须如实拒绝，不能被其它映射或推导带过。"""
    dirs, matched, unmatched, _ = strm.gen_targets_for_suspects(
        ["9KG:某内容/x.mkv"], REAL_PAIRS, limit=20)

    assert dirs == []
    assert matched == []
    assert unmatched == ["9KG:某内容/x.mkv"]


def test_real_world_mixed_pairs():
    """多映射混合：配了的纳入、没配的如实归入 unmatched，互不干扰。"""
    keys = [
        "电视剧:日番/A/Season 01/E01.mkv",
        "电影:某电影 (2024)/某电影.mkv",
        "9KG:某内容/x.mkv",
    ]

    dirs, matched, unmatched, _ = strm.gen_targets_for_suspects(
        keys, REAL_PAIRS, limit=20)

    assert "/HomeTheater/TV/日番/A/Season 01" in dirs
    assert "/HomeTheater/Movies/某电影 (2024)" in dirs
    assert len(matched) == 2
    assert unmatched == ["9KG:某内容/x.mkv"], "未配网盘目录的映射必须如实报告"


# --------------------------------------------------------------------------
# 命令通道的失真：连续空格
# --------------------------------------------------------------------------

def test_double_space_dir_is_refused_not_sent_broken():
    """
    目录名含**连续空格**时，该文件不纳入参数列表。

    原因：宿主把命令串按空白切分后再用单个空格拼回（command.py 的
    `cmd.split()[0]` / `" ".join(cmd.split()[1:])`），`/TV/剧  名` 到助手那边
    就变成了 `/TV/剧 名`，路径匹配失败。而失败提示只发给助手侧用户，本插件
    收不到 —— 表现为「点了按钮什么都没发生」。与其发一条注定失败的假命令，
    不如在这里就明确列为未处理。

    单个空格、括号、中日文、`{}` 都是无损的（用户实机的目录名全属这一类）。
    """
    pairs = [_pair(pan_dir="/HomeTheater/TV")]
    key = "电视剧:日番/剧  名/Season 01/E01.mkv"

    dirs, matched, unmatched, _ = strm.gen_targets_for_suspects([key], pairs, limit=20)

    assert dirs == [], "含连续空格的路径不得发出（宿主会把空格折叠掉）"
    assert matched == []
    assert unmatched == [key]


def test_single_space_and_brackets_are_lossless():
    """实机目录名的真实形态：单个空格、括号、中日文、{} —— 必须原样通过。"""
    pairs = [_pair(pan_dir="/HomeTheater/TV")]
    key = "电视剧:日番/黄泉的使者 (2026) {tmdbid=260463}/Season 01/E03.mkv"

    dirs, _, unmatched, _ = strm.gen_targets_for_suspects([key], pairs, limit=20)

    assert dirs == ["/HomeTheater/TV/日番/黄泉的使者 (2026) {tmdbid=260463}/Season 01"]
    assert unmatched == []
