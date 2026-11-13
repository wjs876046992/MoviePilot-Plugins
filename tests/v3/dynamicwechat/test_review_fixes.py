"""3.3.0 代码审查修复的回归测试（--noconftest 可跑）。

覆盖全量审查发现的 10 个问题中最容易复发的几类：
- 三态 None 被当成失效、通知假成功、pinned 未校验
- 跨模式切换不生效、二维码时间戳缺失、验证码残留
- 原子写与损坏文件备份
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[3]
PLUGIN_DIR = ROOT / "plugins.v3" / "dynamicwechat"
SOURCE = (PLUGIN_DIR / "__init__.py").read_text(encoding="utf-8")
HELPER_SRC = (PLUGIN_DIR / "helper.py").read_text(encoding="utf-8")


def _load_helper():
    package = "dw_review_helper"
    for key in list(sys.modules):
        if key == package or key.startswith(f"{package}."):
            sys.modules.pop(key, None)
    spec = importlib.util.spec_from_file_location(package, PLUGIN_DIR / "helper.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    return module


def _method(name):
    import ast
    tree = ast.parse(SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"{name} not found")


# ---------- 三态 None 不得视为失效 ----------

def test_none_result_does_not_clear_cookie():
    """check_login_status 返回 None（无结论）时不得清空 Cookie 或发失效通知。"""
    body = _method("refresh_cookie")
    # 无结论分支里不能再出现「清 Cookie」的赋值
    idx = body.index("本次 Cookie 校验无结论")
    window = body[max(0, idx - 600):idx]
    assert "_saved_cookie = None" not in window, "None 分支仍在清空 _saved_cookie"
    assert "self._cookie_valid = False" not in window, "None 分支仍在标记 Cookie 失效"
    assert "Cookie 状态保持不变" in body


def test_cloud_check_handles_none_separately():
    body = _method("refresh_cookie")
    assert "cloud_result is None" in body


# ---------- 通知不得谎报成功 ----------

def test_mp_notify_not_counted_as_success():
    """post_message 返回 None 且不上报失败，不能计入 success_count。"""
    for name in ("_send_cookie_false", "_push_qr_code_async", "_test_notify_async"):
        body = _method(name)
        assert "mp_attempted" in body, f"{name} 未区分「已提交」与「已送达」"
        # MP 分支里不得再出现 success_count += 1
        mp_region = body[body.index("if self._use_mp_notify") if "if self._use_mp_notify" in body
                         else body.index("if has_mp"):]
        mp_region = mp_region[:400]
        assert "success_count += 1" not in mp_region, f"{name} 的 MP 通知仍计为成功"


# ---------- pinned_ips 必须校验 IPv4 ----------

def test_pinned_ips_are_validated():
    body = _method("_merge_pinned_ips")
    assert "_is_ipv4" in body
    assert "已忽略" in body


# ---------- 跨模式切换 ----------

def test_switch_mode_resets_memory_cookie():
    """切换 CookieCloud 开关后必须清掉旧模式的内存副本。"""
    init = SOURCE[SOURCE.index("def init_plugin"):SOURCE.index("def _migrate_legacy_magic_strings")]
    reset_at = init.index("self._saved_cookie = None")
    restore_at = init.index("if not self._use_cookiecloud:")
    assert reset_at < restore_at


# ---------- 二维码时间戳 ----------

def test_push_qr_sets_expiry_timestamp():
    body = _method("_push_qr_code_async")
    assert "_future_timestamp" in body, "推送二维码必须设置有效期，否则详情页不渲染图片"


# ---------- 验证码清理 ----------

def test_verification_code_cleared_on_all_captcha_outcomes():
    # 锚点取赋值行（docstring 里也列出了这些原因名，不能直接按字符串找）
    body = _method("check_login_status")
    for marker in ("self._last_check_result = 'captcha_no_code'",
                   "self._last_check_result = 'captcha_btn_error'",
                   "self._last_check_result = 'captcha_failed'"):
        assert marker in body, f"未找到 {marker}"
        window = body[body.index(marker):body.index(marker) + 200]
        assert "_verification_code = ''" in window, f"{marker} 之后未清理验证码"


def test_local_scanning_resets_stale_code():
    body = _method("local_scanning")
    assert "self._verification_code = ''" in body


# ---------- 并发 ----------

def test_local_scanning_takes_qr_lock():
    body = _method("local_scanning")
    assert "_qr_lock.acquire" in body
    assert "_qr_lock.release" in body


# ---------- 原子写与损坏备份 ----------

def test_atomic_write_replaces_not_truncates(tmp_path):
    helper = _load_helper()
    target = tmp_path / "settings.json"
    target.write_text('{"old": 1}', encoding="utf-8")
    helper.atomic_write_json(target, {"new": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"new": 2}
    assert not list(tmp_path.glob(".tmp-*"))


def test_corrupt_settings_is_backed_up(tmp_path):
    helper = _load_helper()
    target = tmp_path / "settings.json"
    target.write_text("{not valid json", encoding="utf-8")
    mgr = helper.JsonFieldManager(str(target))
    assert mgr._load() == {}
    assert (tmp_path / "settings.json.corrupt").exists(), "损坏文件必须留备份"


# ---------- CookieCloud 本地判定 ----------

def test_is_local_uses_dir_not_url(monkeypatch):
    helper = _load_helper()
    # 自建服务在 localhost 但没给本地目录 → 必须走网络分支
    cc = helper.PyCookieCloud(url="http://localhost:8088/cookiecloud", uuid="u", password="p")
    assert cc._is_local() is False
    cc2 = helper.PyCookieCloud(url="http://localhost:3000/cookiecloud", uuid="u",
                               password="p", local_dir="/config/cookies")
    assert cc2._is_local() is True
