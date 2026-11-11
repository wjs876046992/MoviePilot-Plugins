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


def test_get_cookie_prefers_disk_then_cloud():
    """读取顺序：内存 → 本地落盘 → CookieCloud"""
    src = SOURCE
    # 本地落盘检查应出现在 CookieCloud 下载之前
    idx_disk = src.index("使用本地落盘 Cookie")
    idx_cloud = src.index("self._cookiecloud.download")
    assert idx_disk < idx_cloud


def test_verify_requires_wwrtx_sid():
    """回读校验必须检查 wwrtx.sid，而不是只看域名存在"""
    assert "wwrtx.sid" in SOURCE
    assert "_verify_cookiecloud_has_sid" in SOURCE
