"""
上传失败自动重试预算（v0.8.1）的行为契约。

`failed` 清单的每个条目现在携带 `count`（已自动重试失败的次数）与
`exhausted_at`（达上限时刻，NULL=未达）。本文件测的是**方法级**不变量；
「retry 轮失败才 +1」这条结算内的计数规则，结构由
`test_state_transition.py::test_retry_count_only_bumps_on_retry_rounds` 钉住，
端到端在真机验证。

⚠️ 需要 MoviePilot 后端，本机无后端时整组 skip。
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
    p._failed_files = store.LedgerMapping(
        ledger, store.STATUS_FAILED, ts_field="verified_at",
        extra_from_value={"reason": "fail_reason", "count": "retry_count",
                          "exhausted_at": "exhausted_at"})
    p._pending_queue = {}
    p._strm_watch = {}
    p._strm_suspects = {}
    p._auto_retry_enabled = True
    p._auto_retry_limit = 3
    p._notify = False
    p.save_data = lambda k, v: None
    p.get_data = lambda k: None
    return p, ledger, store


def test_new_failure_starts_at_zero_count(tmp_path):
    """首次失败：count=0、未达上限。"""
    p, led, st = _fixture(tmp_path)
    p._mark_failed("电视剧:a.mkv", st.FAIL_MISSING)
    v = p._failed_files["电视剧:a.mkv"]
    assert v["count"] == 0
    assert "exhausted_at" not in v


def test_mark_failed_preserves_count_and_exhausted(tmp_path):
    """重写失败（force/后续轮）不丢已有预算 —— 内存缓存被整体替换的坑。"""
    p, led, st = _fixture(tmp_path)
    p._mark_failed("电视剧:a.mkv", st.FAIL_MISSING)
    p._mark_failed("电视剧:a.mkv", st.FAIL_CORRUPT, count=2)
    p._mark_exhausted("电视剧:a.mkv")
    # 不带 count 再写一次（模拟 force 对账重写）→ 必须保留 count/exhausted
    p._mark_failed("电视剧:a.mkv", st.FAIL_CORRUPT)
    v = p._failed_files["电视剧:a.mkv"]
    assert v["count"] == 2
    assert v["exhausted_at"] is not None


def test_reset_retry_budget_clears_both(tmp_path):
    """手动重试清零：count=0、exhausted_at 置 NULL（DB 层面也清零）。"""
    p, led, st = _fixture(tmp_path)
    p._mark_failed("电视剧:a.mkv", st.FAIL_MISSING, count=3)
    p._mark_exhausted("电视剧:a.mkv")

    assert p._reset_retry_budget("电视剧:a.mkv") is True

    v = p._failed_files["电视剧:a.mkv"]
    assert v["count"] == 0
    assert "exhausted_at" not in v
    row = led.get("电视剧:a.mkv")
    assert row["retry_count"] == 0
    assert row["exhausted_at"] is None


def test_retryable_failed_keys_excludes_exhausted(tmp_path):
    """自动重试候选只含未达上限的；达上限后移出候选。"""
    p, led, st = _fixture(tmp_path)
    p._mark_failed("电视剧:a.mkv", st.FAIL_MISSING)
    p._mark_failed("电视剧:b.mkv", st.FAIL_CORRUPT)
    p._mark_exhausted("电视剧:b.mkv")
    assert set(p._retryable_failed_keys()) == {"电视剧:a.mkv"}


def test_reset_budget_on_key_not_in_failed_is_noop(tmp_path):
    """对不在失败清单里的 key 清零 → 无事发生，不报错。"""
    p, led, st = _fixture(tmp_path)
    assert p._reset_retry_budget("电视剧:不存在.mkv") is False
