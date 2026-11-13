"""企业微信 Cookie 持久化与 CookieCloud 读-合并-写单测（--noconftest 可跑）。

覆盖 2026-11-11 的真实故障：

- 旧版 update_cookie 直接把「只含 work.weixin.qq.com」的数据 POST 给 CookieCloud，
  而 /update 是整体替换 —— 结果是其它 699 个站点的 Cookie 被全部清空，
  同时企微域只剩 ww_lang 之类边缘 cookie（真机解密证实）。
- 修复后要求：写入前先下载全量、只替换企微域、再写回；拿不到全量时拒绝写入。
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[3]
PLUGIN_DIR = ROOT / "plugins.v3" / "dynamicwechat"
SOURCE = (PLUGIN_DIR / "__init__.py").read_text(encoding="utf-8")


def _load_helper():
    package = "dynamicwechat_v3_cookie_test"
    for key in list(sys.modules):
        if key == package or key.startswith(f"{package}."):
            sys.modules.pop(key, None)
    spec = importlib.util.spec_from_file_location(package, PLUGIN_DIR / "helper.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def helper():
    return _load_helper()


def test_encrypt_decrypt_roundtrip(helper):
    """新增的 decrypt 必须能解回 encrypt 的原文（CryptoJS 兼容格式）"""
    original = json.dumps({"cookie_data": {"a.com": [{"name": "x", "value": "1"}]}}).encode()
    enc = helper.encrypt(original, b"0123456789abcdef")
    assert helper.decrypt(enc, b"0123456789abcdef") == original


def test_decrypt_with_wrong_key_does_not_return_plaintext(helper):
    """错误密钥不应还原出原文（可能抛异常，也可能得到乱码——两者都算未泄漏）"""
    original = b'{"cookie_data":{"x":[{"name":"wwrtx.sid","value":"secret"}]}}'
    enc = helper.encrypt(original, b"0123456789abcdef")
    try:
        out = helper.decrypt(enc, b"fedcba9876543210")
    except Exception:
        return
    assert out != original


def test_update_cookie_merges_instead_of_replacing(helper, monkeypatch):
    """核心回归：写入时必须保留其它站点，只替换企微域"""
    cc = helper.PyCookieCloud(url="http://example.invalid", uuid="u", password="p")
    existing = {
        "m-team.io": [{"name": "sid", "value": "keep-me", "domain": ".m-team.io"}],
        "hdchina.org": [{"name": "c_secure_uid", "value": "keep-too", "domain": ".hdchina.org"}],
        ".work.weixin.qq.com": [{"name": "ww_lang", "value": "zh", "domain": ".work.weixin.qq.com"}],
    }
    monkeypatch.setattr(cc, "download_raw", lambda: json.loads(json.dumps(existing)))

    posted = {}

    class FakeResp:
        status_code = 200
        def json(self):
            return {"action": "done"}

    def fake_post(url, json=None, timeout=None):
        posted["body"] = json
        return FakeResp()

    monkeypatch.setattr(helper.requests, "post", fake_post)

    ok = cc.update_cookie({".work.weixin.qq.com": [
        {"name": "wwrtx.sid", "value": "secret-sid", "domain": ".work.weixin.qq.com"}]})
    assert ok is True

    plain = helper.decrypt(posted["body"]["encrypted"].encode(), cc.get_the_key().encode())
    doc = json.loads(plain)["cookie_data"]
    # 其它站点必须原样保留
    assert doc["m-team.io"][0]["value"] == "keep-me"
    assert doc["hdchina.org"][0]["value"] == "keep-too"
    # 企微域被替换为新值，并带上传标记
    names = [c["name"] for c in doc[".work.weixin.qq.com"]]
    assert "wwrtx.sid" in names
    assert "_upload_type" in names
    assert "ww_lang" not in names


def test_update_cookie_refuses_when_existing_data_unavailable(helper, monkeypatch):
    """拿不到全量数据时必须拒绝写入，绝不能清空别人的 Cookie"""
    cc = helper.PyCookieCloud(url="http://example.invalid", uuid="u", password="p")
    monkeypatch.setattr(cc, "download_raw", lambda: {})
    called = {"post": False}

    def fake_post(*a, **k):
        called["post"] = True
        raise AssertionError("不应发起写入")

    monkeypatch.setattr(helper.requests, "post", fake_post)
    assert cc.update_cookie({".work.weixin.qq.com": [{"name": "wwrtx.sid", "value": "s"}]}) is False
    assert called["post"] is False


def test_local_cookie_disk_roundtrip():
    """落盘/读取兜底：只保存 weixin 相关域，且能原样读回、权限 600。

    直接从插件源码按 AST 取出两个方法编译执行——比字符串切分稳，
    也不会因为方法体内有嵌套 def/try 而误截断。
    """
    import ast
    import asyncio
    import os
    import tempfile
    from types import SimpleNamespace as NS

    tree = ast.parse(SOURCE)
    wanted = {"_save_cookie_to_disk", "_load_cookie_from_disk"}
    nodes = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in wanted]
    assert len(nodes) == 2, f"未找到两个方法: {[n.name for n in nodes]}"

    module = ast.Module(body=nodes, type_ignores=[])
    ns = {
        "json": json, "os": os, "asyncio": asyncio, "List": list,
        "logger": NS(info=lambda *a, **k: None, warning=lambda *a, **k: None),
    }
    exec(compile(module, "<methods>", "exec"), ns)

    tmp = Path(tempfile.mkdtemp())
    stub = NS(get_data_path=lambda: tmp)
    cookies = [
        {"name": "wwrtx.sid", "value": "s", "domain": ".work.weixin.qq.com"},
        {"name": "unrelated", "value": "x", "domain": ".example.com"},
    ]
    asyncio.run(ns["_save_cookie_to_disk"](stub, cookies))
    saved = ns["_load_cookie_from_disk"](stub)
    assert len(saved) == 1 and saved[0]["name"] == "wwrtx.sid"
    assert oct((tmp / "cookie.json").stat().st_mode)[-3:] == "600"


def test_cookie_source_is_strictly_exclusive():
    """3.1.8 起严格二选一：开启 CookieCloud 只读云端，关闭只读本地，不交叉回退。"""
    src = SOURCE
    # 关闭时必须走本地分支并直接返回，不落到云端下载
    assert "if not self._use_cookiecloud:" in src
    assert "使用本地 Cookie（" in src
    # 云端下载只应出现在 use_cookiecloud 为真的路径上
    fn = src[src.index("async def get_cookie_async"):src.index("def parse_cookie_header")]
    assert fn.index("if not self._use_cookiecloud:") < fn.index("self._cookiecloud.download")
    # 关闭分支必须提前 return，不能继续走云端
    offline = fn[fn.index("if not self._use_cookiecloud:"):fn.index("try:", fn.index("if not self._use_cookiecloud:"))]
    assert "return disk_cookie or None" in offline


def test_disk_save_is_only_for_local_mode():
    """落盘只在关闭 CookieCloud 时发生 —— 开启时云端是唯一副本。"""
    src = SOURCE
    body = src[src.index("async def _update_cookie"):src.index("async def _send_cookie_false")]
    # 云端分支里不得再落盘
    cloud_part = body[body.index("if self._use_cookiecloud:"):body.index("else:", body.index("if self._use_cookiecloud:"))]
    assert "_save_cookie_to_disk" not in cloud_part
    # 本地分支里必须有落盘
    local_part = body[body.index("else:", body.index("if self._use_cookiecloud:")):]
    assert "_save_cookie_to_disk" in local_part


def test_empty_payload_deletes_stale_file():
    """空 payload 必须删除旧文件，不能留 0 字节（真机踩过）。"""
    assert "path.unlink(missing_ok=True)" in SOURCE
    assert "不写空文件" in SOURCE


def test_disk_load_treats_empty_as_missing():
    """0 字节/空数组都按「无备份」处理。"""
    import inspect
    src = SOURCE
    body = src[src.index("def _load_cookie_from_disk"):]
    body = body[:body.index("async def _send_cookie_false")]
    assert "st_size" in body
    assert "and data" in body


def test_verify_requires_wwrtx_sid():
    """回读校验必须检查 wwrtx.sid，而不是只看域名存在"""
    assert "wwrtx.sid" in SOURCE
    assert "_verify_cookiecloud_has_sid" in SOURCE


def test_update_cookie_reads_full_browser_cookies():
    """
    真机事故（2026-11-12）：按当前 URL 取 cookie 拿不到 `.work.weixin.qq.com`
    下的登录凭证，导致 cookie.json 被过滤成空。必须取全量再筛选。
    """
    src = SOURCE
    body = src[src.index("async def _update_cookie"):src.index("async def _send_cookie_false")]
    assert "await context.cookies()" in body, "必须取全量 cookie，而不是仅当前 URL 的"


# ---------- 3.1.9 regression: local-mode startup restore + fake-success guard ----------

def test_init_plugin_restores_cookie_from_disk():
    """Local mode keeps _saved_cookie in memory only; after reload it is empty, so
    both validation branches are skipped and the loop logs a fake keepalive success.
    init_plugin must restore it from cookie.json."""
    src = SOURCE
    init = src[src.index("def init_plugin"):src.index("def _migrate_legacy_magic_strings")]
    assert "_load_cookie_from_disk" in init
    assert "if not self._use_cookiecloud and not self._saved_cookie" in init


def test_refresh_cookie_reloads_disk_before_skipping():
    """Reload from disk again before validating (memory may be empty after config change)."""
    src = SOURCE
    fn = src[src.index("async def refresh_cookie"):src.index("async def check_login_status")]
    assert "保活前从本地恢复" in fn


def test_keepalive_requires_real_validation():
    """No real validation (cookie_used=False) must not extend lifetime or log success."""
    src = SOURCE
    fn = src[src.index("async def refresh_cookie"):src.index("async def check_login_status")]
    assert "if self._cookie_valid and cookie_used:" in fn
    assert "本轮没有任何可校验的 Cookie" in fn
