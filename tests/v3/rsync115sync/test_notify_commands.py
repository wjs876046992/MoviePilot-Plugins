"""
通知里附带的处理命令必须**可复制、且不会指错对象**。

Notification commands must be copy-ready and must never resolve to the wrong file.

## 为什么要专门测这个

通知长期只写「去点看板上的『删旧重传』」，而用户是在**手机 Telegram** 上
读通知的 —— 彼时打开看板并不顺手，于是他问「我该怎么用命令让这个删旧重传」。

命令侧确实有 `/rsync_strm retry <目标>`，但目标只能填**序号**或**关键字**。
序号在这里是**不能用**的：序号是"清单当前排序"的函数，而通知往往在几小时后
才被打开，那时本轮条目可能已退场、或清单整体重排（插件重载、看板处理过别的
条目）。照过期序号执行，最好的结果是「提示没有匹配」，最坏的结果是**删掉
另一个文件再重传** —— 那是一条不可撤销的云端删除。
关键字由 key 自身推导，与时间无关，是本文件钉住的唯一正确形态。

## 判据由命令侧反向定义

`_resolve_suspect_target` 用 `kw in k.lower()`（整条 key 的子串）判命中。
因此这里生成的"唯一"关键字**必须用同一条规则**验证唯一性 ——
否则通知给出的关键字到了命令侧就变成多命中，用户敲下去只会被拒绝。
"""

import importlib.util
import os
import sys
import types

import pytest

_PLUGIN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    "plugins.v3", "rsync115sync",
)


def _strm():
    """
    以**包**形式加载 strm 模块，避开需要 MoviePilot 宿主的 `__init__.py`。

    Load `strm` as part of a synthetic package so its relative imports
    (`.paths` / `.constants`, both backend-free) resolve without the host.
    """
    name = "_rp_notify_test"
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [_PLUGIN_DIR]
        sys.modules[name] = pkg
    return importlib.import_module(f"{name}.strm")


def _pair(name="电视剧", src="/emby/TV", strm_dir="/strms/TV"):
    return {"name": name, "src": src, "dest": "/115/TV",
            "strm_dir": strm_dir, "all_ext": False}


LONG_KEY = ("电视剧:国产剧/人间烟火花小厨 (2020) {tmdbid=99230}/Season 01/"
            "人间烟火花小厨 S01E18.2160p.WEB-DL.H265.AAC.mp4")


# --------------------------------------------------------------------------
# 唯一性：通知给出的关键字必须**恰好**命中它自己
# --------------------------------------------------------------------------

def test_single_suspect_yields_the_filename_stem():
    """只有一条疑似时，给最具体的形式（去扩展名的文件名），而不是整段路径。"""
    pairs = [_pair()]
    target = _strm().brief_target_of(LONG_KEY, pairs, [LONG_KEY])
    assert target == "人间烟火花小厨 S01E18.2160p.WEB-DL.H265.AAC"
    assert target in LONG_KEY.lower() or target in LONG_KEY


def test_same_filename_in_three_dramas_falls_back_to_directory():
    """
    三部剧的第 1 集文件名完全相同 → 必须退到包含目录的那一级。

    ⚠️ 这条是**最关键**的一条：如果只按文件名判唯一性（或者干脆不判），
    通知会给出 `E01`，用户敲下去命令侧命中 3 条并拒绝 —— 或者更糟，
    某个未来版本改成"猜一个"就会删错剧。退让到 `剧甲/Season 01/E01`
    后三者的关键字互不相同。
    """
    pairs = [_pair()]
    a = "电视剧:国产剧/剧甲/Season 01/E01.mkv"
    b = "电视剧:国产剧/剧乙/Season 01/E01.mkv"
    c = "电视剧:国产剧/剧丙/Season 01/E01.mkv"
    keys = [a, b, c]
    targets = [_strm().brief_target_of(k, pairs, keys) for k in keys]
    assert len(set(targets)) == 3, f"三条疑似给不出互不相同的关键字: {targets}"
    for key, target in zip(keys, targets):
        hits = [k for k in keys if target.lower() in k.lower()]
        assert hits == [key], f"关键字 {target!r} 命中 {hits}"


def test_prefers_shortest_unique_form():
    """同一部剧的两集：文件名已能区分，就不该拖上目录（消息要短）。"""
    pairs = [_pair()]
    e17 = "电视剧:剧甲/Season 01/剧甲 S01E17.mkv"
    e18 = "电视剧:剧甲/Season 01/剧甲 S01E18.mkv"
    keys = [e17, e18]
    target = _strm().brief_target_of(e18, pairs, keys)
    assert target == "剧甲 S01E18"
    assert "/" not in target, "文件名已唯一时不该带上目录"


def test_duplicate_keys_yield_none_rather_than_a_wrong_command():
    """
    两条**完全相同**的 key 无法区分 → 返回 None，由调用方降级提示。

    给不出唯一关键字时**绝不能退回序号**或"随便挑一个"：那是本功能存在的
    理由（序号会静默指错对象）。宁可让用户去别处自己看清单。
    """
    pairs = [_pair()]
    assert _strm().brief_target_of(LONG_KEY, pairs, [LONG_KEY, LONG_KEY]) is None


def test_unattributable_key_yields_none():
    """归属不到任何已知映射的 key 不给命令（拼不出相对路径就没有可靠关键字）。"""
    pairs = [_pair()]
    assert _strm().brief_target_of("电影:别的映射/x.mkv", pairs, ["电影:别的映射/x.mkv"]) is None


def test_keyword_uses_full_key_substring_semantics():
    """
    唯一性判据必须与 `_resolve_suspect_target` 的 `kw in k.lower()` 一致。

    用「只在文件名里搜」的判据会得出错误的"唯一"，而命令侧按整条 key 搜 ——
    两边口径不同正是这类"通知给的命令敲下去没用"的根源。
    """
    pairs = [_pair()]
    # 剧名出现在**目录**里而不是文件名里：按文件名判会漏掉这个交叉命中
    a = "电视剧:日番/同一部剧/Season 01/EP01.mkv"
    b = "电视剧:日番/另一部剧/Season 02/同一部剧 EP01.mkv"
    keys = [a, b]
    ta = _strm().brief_target_of(a, pairs, keys)
    assert ta is not None
    assert [k for k in keys if ta.lower() in k.lower()] == [a]


# --------------------------------------------------------------------------
# 命令块的排版：可复制、且不误导
# --------------------------------------------------------------------------

def test_every_shown_suspect_gets_its_own_retry_and_ignore_commands():
    """
    被列出的每条疑似都要有独立的 `retry` / `ignore` 命令。

    上限之内**逐条**给命令；超出部分见下一条用例（必须显式写出还有多少条，
    不能静默丢弃）。
    """
    pairs = [_pair()]
    keys = [f"电视剧:日番/剧{n}/Season 01/剧{n} S01E01.mkv" for n in range(5)]
    text = _strm().suspect_commands_text(keys, pairs)
    for k in keys:
        assert k in text, f"命令块漏了条目: {k}"
    assert text.count("/rsync_strm retry ") == 5
    assert text.count("/rsync_strm ignore ") == 5


def test_over_limit_items_are_announced_not_silently_dropped():
    """
    超出上限的条目必须**明确写出数量**，不能静默省略。

    这是整个模块反复出现的同一条教训：静默丢弃会让用户以为「整批都处理过了」，
    于是不再关注那些条目 —— 比直接拒绝执行更糟（见
    `gen_targets_for_suspects` 对上溢文件的同样处理）。

    ⚠️ 上限存在的理由是**消息长度**：一条命令块约 300 字符，几十条疑似
    （strm 助手整体失灵时的常见形态）会撑爆 Telegram 的单条文本上限，而宿主
    按 4096 字符拆分后，续条恰好会丢掉「② 是破坏性操作」这句警告。
    """
    pairs = [_pair()]
    keys = [f"电视剧:日番/剧{n}/Season 01/剧{n} S01E01.mkv" for n in range(8)]
    text = _strm().suspect_commands_text(keys, pairs)
    assert text.count("/rsync_strm retry ") == 5
    assert "另有 3 条未附命令" in text
    assert "/rsync_strm list" in text, "被截断时要告诉用户去哪儿看全清单"


def test_limit_is_configurable_and_zero_disables_per_item_commands():
    """上限可显式传入；传 0 时只留整批命令（gen/check），不逐条给。"""
    pairs = [_pair()]
    keys = [f"电视剧:日番/剧{n}/Season 01/剧{n} S01E01.mkv" for n in range(3)]
    text = _strm().suspect_commands_text(keys, pairs, limit=0)
    assert "/rsync_strm retry " not in text
    assert "/rsync_strm gen" in text
    assert "另有 3 条未附命令" in text


def test_commands_are_fenced_for_tap_to_copy():
    """
    每条命令都必须包在 ``` 围栏里。

    这是"可点击复制"在 Telegram 上真能拿到的形态：围栏内的文本宿主**不会**
    转义，客户端提供点按复制。裸行会被 `standardize()` 转义成 `/rsync\\_strm gen`
    （肉眼看不出来，但长按复制有带走反斜杠的风险）。
    """
    pairs = [_pair()]
    text = _strm().suspect_commands_text(["电视剧:剧甲 S01E01.mkv"], pairs)
    for cmd in ["/rsync_strm gen", "/rsync_strm check"]:
        assert f"```\n{cmd}\n```" in text, f"{cmd} 没有被围栏包住"
    # retry/ignore 的目标是算出来的，逐个断言它确实被围栏包着
    for line_no, line in enumerate(text.splitlines()):
        if line.startswith("/rsync_strm retry") or line.startswith("/rsync_strm ignore"):
            prev = text.splitlines()[line_no - 1]
            nxt = text.splitlines()[line_no + 1]
            assert prev == "```" and nxt == "```", f"{line!r} 没被围栏包住"


def test_gen_is_offered_once_not_per_item():
    """
    `/rsync_strm gen` 是**整批**操作（不带目标），只在开头出现一次。

    逐条重复会让人以为它只作用于那一条 —— 于是用户会对每个文件都敲一遍，
    每次都触发助手的云端目录遍历（有成本，且 `_strm_gen_requested` 是防重试的）。
    """
    pairs = [_pair()]
    keys = [f"电视剧:日番/剧{n}/Season 01/剧{n} S01E01.mkv" for n in range(5)]
    text = _strm().suspect_commands_text(keys, pairs)
    assert text.count("/rsync_strm gen") == 1
    assert text.count("/rsync_strm check") == 1


def test_command_block_stays_well_under_telegram_limit():
    """
    满额（5 条）命令块要显著短于宿主拆分阈值（4096），给正文留出余量。

    宿主 `_split_plain_text` 按 4096 字符拆，拆开后的续条会脱离上下文 ——
    尤其会丢掉末尾那句「② 是破坏性操作」的警告。留一半余量是保守取值。
    """
    pairs = [_pair()]
    keys = [f"电视剧:国产剧/很长的剧名{n} (2020) {{tmdbid=1000{n}}}/Season 01/"
            f"很长的剧名{n} S01E{n:02d}.2160p.WEB-DL.H265.AAC.mp4" for n in range(5)]
    text = _strm().suspect_commands_text(keys, pairs)
    assert len(text) < 2048, f"命令块 {len(text)} 字符，太长了"


def test_ambiguous_items_get_a_warning_instead_of_a_command():
    """
    给不出唯一关键字时，明确写「无法自动生成命令」，**不留**任何可执行行。

    留一行's 看起来能用'的命令（比如退回序号）才是真正的危险 —— 那条命令会
    在用户毫不知情的情况下作用于别的文件。
    """
    pairs = [_pair()]
    dup = "电视剧:剧甲/Season 01/E01.mkv"
    text = _strm().suspect_commands_text([dup, dup], pairs)
    assert "无法自动生成唯一命令" in text
    assert "/rsync_strm retry " not in text
    assert "/rsync_strm ignore " not in text


def test_command_targets_are_substrings_of_their_own_key():
    """
    每个命令里的关键字都能在自己的 key 里找到，且**只**命中自己的 key。

    这条把"通知给的关键字"与"命令侧怎么判命中"钉在一起：命令侧用
    `kw in k.lower()`，所以这里也必须用同一口径验证，否则会出现
    「通知给了命令、敲下去说没有匹配」或更糟的「匹配到别的条目」。
    """
    pairs = [_pair()]
    keys = [
        "电视剧:国产剧/剧甲 (2020)/Season 01/剧甲 S01E01.2160p.WEB-DL.mp4",
        "电视剧:国产剧/剧乙 (2021)/Season 01/剧乙 S01E01.2160p.WEB-DL.mp4",
    ]
    text = _strm().suspect_commands_text(keys, pairs)
    targets = [ln.split("retry ", 1)[1] for ln in text.splitlines()
               if ln.startswith("/rsync_strm retry ")]
    assert len(targets) == len(keys)
    for key, target in zip(keys, targets):
        assert target.lower() in key.lower()
        assert [k for k in keys if target.lower() in k.lower()] == [key]
