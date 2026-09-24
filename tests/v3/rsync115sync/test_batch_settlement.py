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
    final_m, final_c = paths.merge_force_anomalies([], pre_c, [], [], [])
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
    # ⚠️ 位置传参：本函数的参数是「预对账 → 尝试 → 复检」三段，调用方一律按
    # 位置传（见 __init__.py 的 force 分支）。此处曾用 post_m=/post_c= 关键字
    # 调用，而形参名实际是 post_missing/post_corrupt，于是这两条用例一直抛
    # TypeError 却无人发现 —— 关键字名与形参名解耦不了，改为位置传参后
    # 形参改名不会再让它静默失效。
    final_m, final_c = paths.merge_force_anomalies(
        ["TV:a.mkv"], ["TV:b.mkv"],
        ["TV:a.mkv", "TV:b.mkv"],
        [], [])
    assert final_m == [] and final_c == []

# --------------------------------------------------------------------------
# 补齐清单出账时机 — 必须在「批次上限截断之后」且「rsync 真正执行之后」
# --------------------------------------------------------------------------

def _execute_sync_source() -> str:
    """取 _execute_sync 的源码（只做结构断言，不执行）。"""
    import importlib
    from pathlib import Path
    module = importlib.import_module("app.plugins.rsync115sync")
    src = Path(module.__file__).read_text(encoding="utf-8")
    import ast
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
               and n.name == "Rsync115Sync")
    fn = next(n for n in cls.body
              if isinstance(n, ast.FunctionDef) and n.name == "_execute_sync")
    return ast.get_source_segment(src, fn) or ""


def test_ready_mode_selects_by_cooldown_basis():
    """
    ready 模式必须按 `now - 基准 >= 冷却时长` 选文件，且基准语义与 `_count_queue` 相同。

    ⚠️ 这两条用例替换了原先的「补齐清单出账时机」用例组。那个清单（`_missed_queue`）
    已随冷却判据统一而删除 —— 它的出账时机之所以曾经需要两条源码顺序断言，
    正是因为"另一个队列 + 另一套出账逻辑"本身容易错位。现在只有 `_pending_queue`
    一个队列、一处出账（由对账结果驱动，见下面的第二条断言），这类错位不复存在。

    保留的是**判据本身**：它必须与看板的 `_count_queue` 逐字一致，否则会出现
    「看板说有 N 个就绪、点同步却什么也不传」这种无从解释的状态。
    """
    src = _execute_sync_source()
    if not src:
        import pytest
        pytest.skip("无法取得 _execute_sync 源码")

    assert "now_ts - basis_ts < threshold" in src, (
        "ready 模式的冷却判据变了 —— 必须与 _count_queue 保持逐字一致"
    )
    # 出账仍必须晚于 rsync 真正执行：Popen 失败/超时的条目若提前出队，
    # 会既没传、又没进异常清单，静默丢失（这是 v0.2.1 修过的那一类）。
    popen_idx = src.index("subprocess.Popen")
    settle_idx = src.index("succeeded_keys = set(")
    assert settle_idx > popen_idx, (
        "冷却队列出账早于 rsync 执行：Popen 失败/超时的条目会既没传、又没进异常清单"
    )


def test_no_second_queue_for_missed_events():
    """
    反向哨兵：不得再出现「第二个队列 + 跳过冷却」的实现。

    那个模式（`_missed_queue`）的全部问题在于**判据与冷却队列不同**：
    它用"无条件跳过冷却"来表达"这些文件等得够久了"，副作用是源端扫描刚发现
    一个 10 秒前刚落地的文件也立刻上传。正确表达是冷却基准取
    `min(发现时刻, mtime)`（见 `_cooldown_basis`）—— 同一件事，一个判据。
    """
    src = _execute_sync_source()
    if not src:
        import pytest
        pytest.skip("无法取得 _execute_sync 源码")
    # ⚠️ 必须**先剥掉注释与字符串**再检查：本文件与插件源码里都有大量说明
    # 文本在解释"为什么删掉那个队列"，直接 grep 原始源码会命中那些解释，
    # 把一条正确的注释判成"代码复活了"（我自己踩过一次，断言当场变假红）。
    # 剥注释而不是删掉解释，是因为那条解释本身是此刻最该留下的信息。
    import io
    import tokenize

    code_only = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        code_only.append(tok.string)
    emitted = " ".join(code_only)
    assert "_missed_queue" not in emitted, (
        "_execute_sync 中又出现了 _missed_queue（代码，非注释）—— 该队列已废弃，"
        "错过的事件由冷却基准取 mtime 表达"
    )
