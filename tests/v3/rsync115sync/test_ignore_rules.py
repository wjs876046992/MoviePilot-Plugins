"""
忽略规则匹配与增删的单测。

Tests for ignore-rule matching and mutation. A wrong rule silently stops files from
ever being synced (the file never appears in the anomaly list again), so the
fail-safe direction matters: ambiguous input must mean "not ignored".
"""

import pytest

from app.plugins.rsync115sync import ignore


def _rule(text, match="contains"):
    return {"rule": text, "match": match}


# --------------------------------------------------------------------------
# is_ignored
# --------------------------------------------------------------------------

def test_empty_key_or_rules_is_never_ignored():
    """空 key / 空规则一律「不忽略」—— 这是安全方向：忽略错了文件就再也不上传。"""
    assert ignore.is_ignored("", [_rule("剧名")]) is False
    assert ignore.is_ignored("任务:剧名.mkv", []) is False
    assert ignore.is_ignored("任务:剧名.mkv", None) is False


def test_contains_matches_substring_case_insensitively():
    rules = [_rule("AbC", "contains")]
    assert ignore.is_ignored("任务:xabcx.mkv", rules) is True
    assert ignore.is_ignored("任务:XABCX.MKV", rules) is True
    assert ignore.is_ignored("任务:xyz.mkv", rules) is False


def test_exact_matches_only_whole_key():
    """exact 用于「只忽略这一个文件」，不能变成子串匹配。"""
    rules = [_rule("任务:剧名 S01E01.mkv", "exact")]
    assert ignore.is_ignored("任务:剧名 S01E01.mkv", rules) is True
    assert ignore.is_ignored("任务:剧名 S01E01.mkv.extra", rules) is False
    assert ignore.is_ignored("任务:别的 S01E01.mkv", rules) is False


def test_exact_is_case_insensitive():
    rules = [_rule("任务:AbC.mkv", "exact")]
    assert ignore.is_ignored("任务:abc.MKV", rules) is True


def test_blank_rule_text_never_matches():
    """空规则文本是任意串的子串；若当成 contains 会忽略**全部**文件。"""
    assert ignore.is_ignored("任务:a.mkv", [_rule("", "contains")]) is False
    assert ignore.is_ignored("任务:a.mkv", [_rule("   ", "contains")]) is False


def test_missing_match_field_defaults_to_contains():
    """早期版本存的规则没有 match 字段，必须仍能按 contains 生效。"""
    assert ignore.is_ignored("任务:剧名.mkv", [{"rule": "剧名"}]) is True


def test_unknown_match_mode_behaves_as_contains():
    """未知匹配模式按 contains 处理（而不是静默失效）。"""
    assert ignore.is_ignored("任务:剧名.mkv", [_rule("剧名", "weird-mode")]) is True


def test_any_matching_rule_is_enough():
    rules = [_rule("甲"), _rule("乙")]
    assert ignore.is_ignored("任务:乙.mkv", rules) is True
    assert ignore.is_ignored("任务:丙.mkv", rules) is False


# --------------------------------------------------------------------------
# add_rule
# --------------------------------------------------------------------------

def test_add_rule_appends_and_returns_true():
    rules = []
    assert ignore.add_rule(rules, "剧名") is True
    assert len(rules) == 1
    assert rules[0]["rule"] == "剧名"
    assert rules[0]["match"] == "contains"
    assert rules[0]["created_at"]  # 有时间戳便于用户排查来源


def test_add_rule_rejects_duplicate_same_mode():
    rules = []
    ignore.add_rule(rules, "剧名")
    assert ignore.add_rule(rules, "剧名") is False
    assert len(rules) == 1


def test_add_rule_dedupes_case_insensitively():
    rules = []
    ignore.add_rule(rules, "AbC")
    assert ignore.add_rule(rules, "abc") is False


def test_add_rule_allows_same_text_with_different_mode():
    """
    `剧名` 的 exact 与 contains 是**两条不同规则**：前者只忽略那一个文件，
    后者忽略整部剧。去重时若只看文本会把用户后加的那条吞掉。
    """
    rules = []
    assert ignore.add_rule(rules, "剧名", match="contains") is True
    assert ignore.add_rule(rules, "剧名", match="exact") is True
    assert len(rules) == 2


def test_add_rule_strips_and_rejects_blank():
    rules = []
    assert ignore.add_rule(rules, "   ") is False
    assert ignore.add_rule(rules, "") is False
    assert ignore.add_rule(rules, None) is False
    assert rules == []
    assert ignore.add_rule(rules, "  剧名  ") is True
    assert rules[0]["rule"] == "剧名"


def test_add_rule_records_origin_metadata():
    """来源信息用于区分「谁在哪加的」，排查误忽略时是唯一线索。"""
    rules = []
    ignore.add_rule(rules, "剧名", created_by="user1", source="web")
    assert rules[0]["created_by"] == "user1"
    assert rules[0]["source"] == "web"


# --------------------------------------------------------------------------
# remove_rule
# --------------------------------------------------------------------------

def test_remove_rule_by_index():
    rules = [_rule("甲"), _rule("乙")]
    assert ignore.remove_rule(rules, 0) is True
    assert [r["rule"] for r in rules] == ["乙"]


def test_remove_rule_by_text_is_case_insensitive():
    rules = [_rule("AbC")]
    assert ignore.remove_rule(rules, "abc") is True
    assert rules == []


def test_remove_rule_removes_all_matching_text():
    rules = [_rule("甲", "contains"), _rule("甲", "exact")]
    assert ignore.remove_rule(rules, "甲") is True
    assert rules == []


@pytest.mark.parametrize("bad_index", [-1, 5, 100])
def test_remove_rule_out_of_range_index(bad_index):
    """越界序号必须返回 False 而不是抛异常 —— 输入来自聊天指令，不可信。"""
    rules = [_rule("甲")]
    assert ignore.remove_rule(rules, bad_index) is False
    assert len(rules) == 1


def test_remove_rule_nonexistent_text():
    rules = [_rule("甲")]
    assert ignore.remove_rule(rules, "不存在") is False
    assert len(rules) == 1


def test_remove_rule_mutates_in_place():
    """
    必须是**就地修改**：调用方持有的是同一个列表对象，并在此后 save_data 落盘。
    若实现改成重新赋值一个新列表，调用方手里的还是旧对象，改动会静默丢失。
    """
    rules = [_rule("甲")]
    same_object = rules
    ignore.remove_rule(rules, 0)
    assert same_object == []


# --------------------------------------------------------------------------
# filter_ignored
# --------------------------------------------------------------------------

def test_filter_ignored_drops_matching_keys():
    rules = [_rule("剧名")]
    keys = ["任务:剧名 S01E01.mkv", "任务:别的.mkv"]
    assert ignore.filter_ignored(keys, rules) == ["任务:别的.mkv"]


def test_filter_ignored_with_no_rules_returns_all():
    keys = ["a", "b"]
    assert ignore.filter_ignored(keys, []) == keys
