"""
批次结算纯函数单测 —— P0-1（出队/strm 不看出码）与 P0-2（force 预对账合并）。

Tests for batch settlement pure functions covering P0-1 (queue drain / strm arm
ignore the exit code) and P0-2 (force pre-audit merge keeps unattempted problems).

这两组函数直接决定「哪些文件离开冷却队列、哪些进 strm 观察、force 后异常清单
还剩什么」。它们被从 _execute_sync 抽出来，正是为了能在没有 rsync/CD2 的情况下
把边界钉死 —— 主方法 500+ 行且无法在单测里跑通。
"""

import inspect

from app.plugins.rsync115sync import paths


# --------------------------------------------------------------------------
# success_keys_after_audit — P0-1：对账通过即可出队，与退出码无关
# --------------------------------------------------------------------------

def test_all_audited_ok_returns_all_keys():
    """整批对账通过 → 全部应出队并 arm strm（调用方不再检查 exit_code）。"""
    got = paths.success_keys_after_audit(
        "TV", ["a.mkv", "b.srt"], missing_keys=[], corrupt_keys=[])
    assert got == ["TV:a.mkv", "TV:b.srt"]


def test_missing_and_corrupt_excluded():
    got = paths.success_keys_after_audit(
        "TV",
        ["ok.mkv", "gone.mkv", "half.mkv"],
        missing_keys=["TV:gone.mkv"],
        corrupt_keys=["TV:half.mkv"],
    )
    assert got == ["TV:ok.mkv"]


def test_exit_code_is_not_a_parameter():
    """
    回归锚点：函数签名不得出现 exit_code。

    P0-1 的根因是调用方用 `exit_code == 0` 作外层门禁，把 23/24 批次里
    对账通过的文件一并拦住。把判据收敛到本函数后，签名里再出现退出码
    说明有人又把两个维度缠回去了。
    """
    params = set(inspect.signature(paths.success_keys_after_audit).parameters)
    assert "exit_code" not in params
    assert params == {"pair_name", "rel_paths", "missing_keys", "corrupt_keys"}


def test_partial_batch_success_is_settled():
    """混合成败（exit 23 典型形态）：成功的出队，失败的留下。"""
    rels = ["good1.mkv", "bad.mkv", "good2.mkv"]
    missing = ["TV:bad.mkv"]
    succeeded = paths.success_keys_after_audit("TV", rels, missing, [])
    assert set(succeeded) == {"TV:good1.mkv", "TV:good2.mkv"}
    assert "TV:bad.mkv" not in succeeded


def test_empty_batch_returns_empty():
    assert paths.success_keys_after_audit("TV", [], [], []) == []


# --------------------------------------------------------------------------
# force_problem_rel_paths — P0-2：全量对账 key → 本映射相对路径
# --------------------------------------------------------------------------

def test_force_problems_extract_rel_paths_for_this_pair_only():
    got = paths.force_problem_rel_paths(
        "TV",
        missing_keys=["TV:a.mkv", "Movies:b.mkv"],
        corrupt_keys=["TV:c.mkv"],
    )
    assert got == ["a.mkv", "c.mkv"]


def test_force_problems_dedupes_when_key_in_both_lists():
    got = paths.force_problem_rel_paths(
        "TV",
        missing_keys=["TV:a.mkv"],
        corrupt_keys=["TV:a.mkv", "TV:b.mkv"],
    )
    assert got == ["a.mkv", "b.mkv"]


def test_force_problems_ignores_foreign_and_empty():
    got = paths.force_problem_rel_paths(
        "TV",
        missing_keys=["Other:x.mkv", "TV:", "TV"],
        corrupt_keys=[],
    )
    assert got == []


# --------------------------------------------------------------------------
# merge_force_anomalies — P0-2：预对账 + 本批复检合并
# --------------------------------------------------------------------------

def test_merge_keeps_unattempted_pre_problems():
    """批次上限截断的预异常必须原样保留（P0-2 核心）。"""
    pre_m = ["TV:batched_out.mkv", "TV:attempted.mkv"]
    attempted = ["TV:attempted.mkv"]
    post_m, post_c = [], []  # 本批已修好
    final_m, final_c = paths.merge_force_anomalies(pre_m, [], attempted, post_m, post_c)
    assert final_m == ["TV:batched_out.mkv"]
    assert final_c == []


def test_merge_uses_post_audit_for_attempted():
    """已尝试的以复检为准：修好移出，仍坏留下。"""
    pre_m = ["TV:fixed.mkv", "TV:still_missing.mkv", "TV:new_corrupt.mkv"]
    pre_c = ["TV:was_corrupt_now_fixed.mkv"]
    attempted = [
        "TV:fixed.mkv",
        "TV:still_missing.mkv",
        "TV:new_corrupt.mkv",
        "TV:was_corrupt_now_fixed.mkv",
    ]
    post_m = ["TV:still_missing.mkv"]
    post_c = ["TV:new_corrupt.mkv"]
    final_m, final_c = paths.merge_force_anomalies(
        pre_m, pre_c, attempted, post_m, post_c)
    assert set(final_m) == {"TV:still_missing.mkv"}
    assert set(final_c) == {"TV:new_corrupt.mkv"}


def test_merge_does_not_lose_unattempted_corrupt():
    pre_c = ["TV:deferred_corrupt.mkv"]
    final_m, final_c = paths.merge_force_anomalies(
        [], pre_c, attempted_keys=[], post_m=[], post_c=[])
    assert final_c == ["TV:deferred_corrupt.mkv"]
    assert final_m == []


def test_merge_reclassifies_when_post_disagrees_with_pre():
    """复检把「缺失」改判为「残缺」时，以复检为准，不能两边都留。"""
    pre_m = ["TV:x.mkv"]
    attempted = ["TV:x.mkv"]
    post_m: list = []
    post_c = ["TV:x.mkv"]
    final_m, final_c = paths.merge_force_anomalies(
        pre_m, [], attempted, post_m, post_c)
    assert final_m == []
    assert final_c == ["TV:x.mkv"]


def test_merge_all_fixed_returns_empty():
    final_m, final_c = paths.merge_force_anomalies(
        ["TV:a.mkv"], ["TV:b.mkv"],
        ["TV:a.mkv", "TV:b.mkv"],
        post_m=[], post_c=[])
    assert final_m == [] and final_c == []
