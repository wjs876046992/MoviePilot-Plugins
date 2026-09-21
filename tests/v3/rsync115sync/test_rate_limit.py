"""
上传限流与风控退避的单测 —— 直接决定「会不会被 115 风控封禁」。

Tests for the upload throttle / anti-abuse back-off. These are the guards that
stand between the plugin and a 115 rate-limit ban, so their boundaries matter
more than their happy path.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.plugins.rsync115sync import Rsync115Sync

# 与 Rsync115Sync.__init__ 里的默认值逐字一致（前端 Config.vue 也用同一份）。
# 关键字集合是「什么算风控」的契约，测试不应另造一份短列表 —— 否则会出现
# 「实现对、测试错」的假失败（本项目已踩过一次：漏掉「操作过快」）。
DEFAULT_RATE_LIMIT_KEYWORDS = (
    "too many requests\nrate limit\n429\ntoo frequent\n频繁\n操作过快\n请稍后"
)


def _plugin(**overrides):
    """
    构造只带限流状态的实例，绕过 __init__（它需要宿主运行时）。

    Build an instance carrying only the throttle state. `object.__new__` bypasses
    __init__ so these tests need no host runtime — the documented convention.
    """
    plugin = Rsync115Sync.__new__(Rsync115Sync)
    plugin._rate_limit_enabled = True
    plugin._upload_batch_size = 200
    plugin._upload_max_per_window = 500
    plugin._upload_window_secs = 1800
    plugin._backoff_secs = 3600
    plugin._upload_window_start = 0.0
    plugin._upload_window_count = 0
    plugin._upload_blocked_until = 0.0
    plugin._current_batch_size = 0
    # 用生产默认串，避免测试与实现对「哪些词算风控」的认知漂移
    plugin._rate_limit_keywords = DEFAULT_RATE_LIMIT_KEYWORDS
    plugin.saved = {}
    plugin._persist_rate_limit_state = lambda: plugin.saved.update(
        window_start=plugin._upload_window_start,
        window_count=plugin._upload_window_count,
        blocked_until=plugin._upload_blocked_until,
    )
    plugin.logger_messages = []
    for k, v in overrides.items():
        setattr(plugin, k, v)
    return plugin


# --------------------------------------------------------------------------
# 三层判定
# --------------------------------------------------------------------------

def test_disabled_limiter_always_allows():
    """总开关关闭时必须无条件放行，且不消耗窗口计数。"""
    plugin = _plugin(_rate_limit_enabled=False, _upload_blocked_until=9e18,
                     _upload_window_count=99999)
    assert plugin._rate_limit_allows() == (True, "")


def test_backoff_denies_and_reports_remaining_minutes():
    """退避期未过 → 拒绝，且原因里给出剩余分钟数（用户据此判断要等多久）。"""
    now = 1_000_000.0
    with patch("app.plugins.rsync115sync.time.time", return_value=now):
        plugin = _plugin(_upload_blocked_until=now + 600)
        allowed, reason = plugin._rate_limit_allows()
    assert allowed is False
    assert "退避" in reason
    assert "10 分钟" in reason


def test_backoff_expiry_allows_again():
    now = 1_000_000.0
    with patch("app.plugins.rsync115sync.time.time", return_value=now):
        plugin = _plugin(_upload_blocked_until=now - 1)
        assert plugin._rate_limit_allows()[0] is True


def test_window_rolls_over_and_resets_count():
    """窗口过期后计数归零并前移起点，否则配额永远不恢复。"""
    now = 1_000_000.0
    with patch("app.plugins.rsync115sync.time.time", return_value=now):
        plugin = _plugin(_upload_window_start=now - 2000, _upload_window_count=500)
        allowed, _ = plugin._rate_limit_allows()
        assert allowed is True
        assert plugin._upload_window_count == 0
        assert plugin._upload_window_start == now


def test_quota_exhausted_denies_within_window():
    now = 1_000_000.0
    with patch("app.plugins.rsync115sync.time.time", return_value=now):
        plugin = _plugin(_upload_window_start=now - 60, _upload_window_count=500)
        allowed, reason = plugin._rate_limit_allows()
    assert allowed is False
    assert "配额" in reason


def test_quota_boundary_exactly_at_limit_denies():
    """恰好等于上限即视为用尽（>= 而非 >）：否则会多放一批出去。"""
    now = 1_000_000.0
    with patch("app.plugins.rsync115sync.time.time", return_value=now):
        plugin = _plugin(_upload_window_start=now - 60, _upload_window_count=500,
                         _upload_max_per_window=500)
        assert plugin._rate_limit_allows()[0] is False


def test_quota_boundary_one_below_limit_allows():
    now = 1_000_000.0
    with patch("app.plugins.rsync115sync.time.time", return_value=now):
        plugin = _plugin(_upload_window_start=now - 60, _upload_window_count=499,
                         _upload_max_per_window=500)
        assert plugin._rate_limit_allows()[0] is True


def test_zero_window_start_is_treated_as_expired():
    """窗口起点为 0（首次运行/状态被清）应直接开窗，而不是判成「未过期」。"""
    now = 1_000_000.0
    with patch("app.plugins.rsync115sync.time.time", return_value=now):
        plugin = _plugin(_upload_window_start=0.0, _upload_window_count=500)
        assert plugin._rate_limit_allows()[0] is True
        assert plugin._upload_window_count == 0


def test_backoff_is_checked_before_window():
    """退避期即使窗口也过期了，仍必须拒绝 —— 判定顺序是承重的。"""
    now = 1_000_000.0
    with patch("app.plugins.rsync115sync.time.time", return_value=now):
        plugin = _plugin(_upload_blocked_until=now + 60,
                         _upload_window_start=now - 99999,
                         _upload_window_count=500)
        allowed, reason = plugin._rate_limit_allows()
    assert allowed is False
    assert "退避" in reason


# --------------------------------------------------------------------------
# 配额扣减（预扣）
# --------------------------------------------------------------------------

def test_consume_quota_adds_batch_size_and_persists():
    plugin = _plugin(_current_batch_size=30, _upload_window_count=10)
    assert plugin._consume_upload_quota() == 40
    assert plugin.saved["window_count"] == 40


def test_consume_quota_zero_batch_is_noop():
    """没有文件提交时不扣减，也不落盘 —— 否则空转轮次会白耗配额。"""
    plugin = _plugin(_current_batch_size=0, _upload_window_count=10)
    assert plugin._consume_upload_quota() == 10
    assert plugin.saved == {}


def test_consume_quota_skipped_when_limiter_disabled():
    plugin = _plugin(_rate_limit_enabled=False, _current_batch_size=50)
    assert plugin._consume_upload_quota() == 0
    assert plugin.saved == {}


def test_consume_quota_persists_before_transfer_starts():
    """
    预扣语义：调用方在启动 rsync **之前**调用它，因此这里必须已经把计数落盘，
    否则传输途中插件被重载会丢失扣减，下一批即绕过限流。
    """
    plugin = _plugin(_current_batch_size=5)
    plugin._consume_upload_quota()
    assert plugin.saved.get("window_count") == 5


# --------------------------------------------------------------------------
# 风控特征检测
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "some error: Too Many Requests",
    "error 429 from server",
    "RATE LIMIT exceeded",
    "操作过快，请稍后重试",
])
def test_detect_rate_limit_hit_positive(text):
    assert _plugin()._detect_rate_limit_hit(text) is True


@pytest.mark.parametrize("text", [
    "",
    None,
    "connection reset by peer",
    "rsync error: some files vanished (code 24)",
    "Permission denied",
])
def test_detect_rate_limit_hit_negative(text):
    """
    不能误报：误判会直接触发退避、暂停全部上传 1 小时，
    比「漏判」的后果严重得多（漏判下一批还会再撞一次）。
    """
    assert _plugin()._detect_rate_limit_hit(text) is False


def test_detect_rate_limit_hit_is_case_insensitive():
    assert _plugin()._detect_rate_limit_hit("TOO MANY REQUESTS") is True


def test_detect_rate_limit_hit_ignores_blank_keyword_lines():
    """关键词列表里的空行不能变成「永远命中」（空串是任意串的子串）。"""
    plugin = _plugin(_rate_limit_keywords="\n\n429\n\n")
    assert plugin._detect_rate_limit_hit("nothing here") is False
    assert plugin._detect_rate_limit_hit("got 429") is True


# --------------------------------------------------------------------------
# 退避触发
# --------------------------------------------------------------------------

def test_trigger_backoff_sets_deadline_and_resets_window():
    """
    退避时窗口计数一并归零：否则退避结束瞬间就会立刻撞上旧配额，
    等于白等了整个退避期。
    """
    now = 1_000_000.0
    with patch("app.plugins.rsync115sync.time.time", return_value=now):
        plugin = _plugin(_upload_window_count=480, _upload_window_start=now - 10,
                         _backoff_secs=3600)
        plugin._trigger_backoff("test")
    assert plugin._upload_blocked_until == now + 3600
    assert plugin._upload_window_count == 0
    assert plugin._upload_window_start == 0.0
    assert plugin.saved["blocked_until"] == now + 3600
