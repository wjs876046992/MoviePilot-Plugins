"""
取消忽略必须**同时**清台账 —— 否则「已忽略」永远清不掉。

Un-ignoring must clear the ledger row too, or the ignored list can never drain.

## 缺陷（2026-09-28，核对新看板时发现）

忽略有**两份存储**，而移除只清了一份：

    _ignored_rules（save_data）   用户写的**规则**，支持 contains 模糊匹配
    台账 status='ignored' 的行    具体**文件**的忽略状态

添加时两处都写（`_add_ignore_rule` 里 `upsert(..., STATUS_IGNORED)`），
移除时却只删前者 —— 台账里的行**永远不会被删掉**。

这个残留此前**看不见**（旧看板「已忽略」读的是 `_ignored_rules`，台账只做计数），
所以潜伏了很久。`/items` 把台账行直接透给看板之后，它立刻变成用户可见的错误：
**取消忽略后，那个文件仍留在「已忽略」清单里**。

## 判据必须与 `ignore.remove_rule` 对齐

`ignore.remove_rule` 的口径是：

    int  → 按序号，**从 0 起**
    str  → 按**规则文本**（大小写不敏感），**不看数字**

我第一版写成「1 起的数字字符串也当序号」，两处都错；真机一测就暴露了。
因此本文件里有一条专门钉这个口径。

⚠️ 需要 MoviePilot 后端，本机 skip；等价逻辑已在真机上验证通过
（真机输出：contains 清 2 行、exact 清 1 行、int 序号按 0 起、字符串数字按文本）。
"""

import os

import pytest


def _fixture(tmp_path):
    try:
        import importlib
        mod = importlib.import_module("app.plugins.rsync115sync")
        store = importlib.import_module("app.plugins.rsync115sync.store")
    except Exception as exc:
        pytest.skip(f"无法导入（{exc.__class__.__name__}）")
    ledger = store.Store(os.path.join(str(tmp_path), "ledger.sqlite3"))
    p = mod.Rsync115Sync.__new__(mod.Rsync115Sync)
    p._ledger = ledger
    p._ignored_rules = []
    p._last_status = {"missing_files": [], "corrupt_files": []}
    p.save_data = lambda k, v: None
    p.get_data = lambda k: None
    return p, ledger, store


def test_removing_a_contains_rule_clears_the_rows_it_covers(tmp_path):
    """contains 规则（如「繁花」）要清掉它覆盖的**全部**行，且不误伤别的。"""
    p, led, st = _fixture(tmp_path)
    for k in ("电视剧:繁花/S01E01.mkv", "电视剧:繁花/S01E02.mkv", "电影:别的/x.mkv"):
        led.upsert(k, st.STATUS_IGNORED)
    p._ignored_rules = [{"rule": "繁花", "match": "contains"},
                        {"rule": "电影:别的/x.mkv", "match": "exact"}]

    assert p._remove_ignore_rule("繁花") is True
    left = [r["key"] for r in led.by_status(st.STATUS_IGNORED)]
    assert left == ["电影:别的/x.mkv"], left


def test_removing_an_exact_rule_only_clears_the_identical_key(tmp_path):
    """exact 规则只删 key 完全相同的行 —— 包含关系不算命中。"""
    p, led, st = _fixture(tmp_path)
    led.upsert("电视剧:繁花/S01E01.mkv", st.STATUS_IGNORED)
    p._ignored_rules = [{"rule": "电视剧:繁花/S01E01.mkv", "match": "exact"}]

    assert p._remove_ignore_rule("电视剧:繁花/S01E01.mkv") is True
    assert not led.by_status(st.STATUS_IGNORED)


def test_int_index_is_zero_based_like_ignore_remove_rule(tmp_path):
    """
    int 序号按 **0 起** —— 与 `ignore.remove_rule` 逐字一致。

    ⚠️ 起点写错会出现「规则删了 A、台账删了 B」：两边都不报错，状态悄悄错位。
    """
    p, led, st = _fixture(tmp_path)
    led.upsert("电视剧:a/1.mkv", st.STATUS_IGNORED)
    p._ignored_rules = [{"rule": "a", "match": "contains"}]

    assert p._remove_ignore_rule(0) is True
    assert not led.by_status(st.STATUS_IGNORED), "0 起口径下，索引 0 = 第一条"


def test_string_digit_is_rule_text_not_an_index(tmp_path):
    """
    字符串 `"1"` 是**规则文本**，不是序号 —— 与 `ignore.remove_rule` 同口径。

    ⚠️ 命令侧传进来的是 `text_arg`（字符串），因此实际生效的永远是这一支；
    序号那一支只在看板/内部调用 int 时才用。把字符串数字当序号会让
    「/rsync_ignore remove 1」删掉第 1 条规则的去向与预期不符。
    """
    p, led, st = _fixture(tmp_path)
    p._ignored_rules = [{"rule": "繁花", "match": "contains"}]
    assert p._ignore_rule_at("1") is None, "字符串 '1' 不该被当成序号"


def test_ignore_rule_at_matches_remove_rule_exactly(tmp_path):
    """
    两者对同一参数的判定必须一致 —— 取到的就是即将被删掉的那条。

    这是本组用例的核心不变量：`_ignore_rule_at` 是"看一眼"，`remove_rule` 是"删"，
    看错对象就会删错台账行。
    """
    p, led, st = _fixture(tmp_path)
    from app.plugins.rsync115sync import ignore as ig
    rules = [{"rule": "甲", "match": "contains"},
             {"rule": "乙", "match": "contains"}]
    p._ignored_rules = [dict(r) for r in rules]

    peeked = p._ignore_rule_at("乙")
    ig.remove_rule(p._ignored_rules, "乙")
    assert peeked is not None and peeked["rule"] == "乙"
    assert [r["rule"] for r in p._ignored_rules] == ["甲"], "删掉的不是取到的那条"

    # int 分支同样对齐
    p._ignored_rules = [dict(r) for r in rules]
    peeked = p._ignore_rule_at(0)
    ig.remove_rule(p._ignored_rules, 0)
    assert peeked is not None and peeked["rule"] == "甲"
    assert [r["rule"] for r in p._ignored_rules] == ["乙"]
