"""
`strm.brief_target_of`：为「删旧重传」按钮生成**唯一**检索关键字。

## 为什么这个函数值得单独一组用例

通知按钮的 `callback_data` 只带指纹，但「全部删旧重传」之外的单条按钮文案
（label）来自 `brief_target_of`。它是**尽力而为**的：逐级退让（文件名 stem →
末两级 → … → 整段相对路径），第一个在 `owner_keys` 里唯一命中的就返回；
全部多命中就返回 `None`。

失败形态不是崩溃而是**指错对象**：若退让逻辑回归成"返回第一个候选不管唯一性"，
通知上那个按钮就会带着一个多义标签 —— 而按钮背后是不可撤销的云端删除。
原覆盖在 `test_notify_commands.py`（v0.8.0 随死代码一起删除），本文件把它
按**仍然在线**的 `brief_target_of` 重建。

加载方式与 `test_notify_commands.py` 相同：以合成包形式导入 `strm`
（backend-free），无需 MoviePilot 宿主。
"""

import importlib
import os
import sys
import types

_PLUGIN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    "plugins.v3", "rsync115sync",
)


def _strm():
    name = "_rp_brief_target_test"
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [_PLUGIN_DIR]
        sys.modules[name] = pkg
    return importlib.import_module(f"{name}.strm")


def _pair(name="电视剧", src="/emby/TV", strm_dir="/strms/TV"):
    return {"name": name, "src": src, "dest": "/115/TV",
            "strm_dir": strm_dir, "all_ext": False}


def test_stem_is_used_when_unique():
    """文件名 stem 唯一命中 → 返回最短的 stem。"""
    keys = ["电视剧:剧甲/Season 01/剧甲 S01E01.mkv"]
    got = _strm().brief_target_of(keys[0], [_pair()], keys)
    assert got == "剧甲 S01E01"


def test_same_stem_in_different_dramas_falls_back_to_longer_prefix():
    """
    三部剧各有一集同名 S01E01：stem 多命中，必须退让到更长的前缀。

    ⚠️ 注意「多命中」是按**剥掉映射前缀后的相对路径**在整条 key 上做子串判的
    —— 不同映射下的同名相对路径（`电视剧:x/...` 与 `电影:x/...`）在 rel 维度
    完全相同，才是真正无法区分的情形，此时必须返回 None（不许猜）。
    """
    keys = [
        "电视剧:剧甲/Season 01/S01E01.mkv",
        "电视剧:剧乙/Season 01/S01E01.mkv",
        "电视剧:剧丙/Season 01/S01E01.mkv",
    ]
    pair = _pair()
    got = _strm().brief_target_of(keys[0], [pair], keys)
    assert got is not None and "剧甲" in got, got
    # 同一相对路径出现在两个映射下 → 连整段都多命中 → None
    pair_tv = _pair("电视剧")
    pair_mv = _pair("电影", src="/emby/Movies")
    dup_keys = ["电视剧:x/Season 01/S01E01.mkv", "电影:x/Season 01/S01E01.mkv"]
    assert _strm().brief_target_of(dup_keys[0], [pair_tv, pair_mv], dup_keys) is None


def test_duplicate_keys_yield_none():
    """同一 key 出现两次 → 永远无法唯一命中 → None（不许猜）。"""
    key = "电视剧:剧甲/Season 01/剧甲 S01E01.mkv"
    assert _strm().brief_target_of(key, [_pair()], [key, key]) is None


def test_unmapped_key_yields_none():
    """key 无法解析出相对路径（不属于任何映射）→ None。"""
    assert _strm().brief_target_of(
        "不存在的映射:a.mkv", [_pair()], ["不存在的映射:a.mkv"]) is None
