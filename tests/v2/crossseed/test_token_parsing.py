"""CrossSeed 站点 Passkey 解析规则回归测试。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

try:
    from app.plugins.crossseed import CrossSeed
except Exception:
    import importlib.util

    # 纯无宿主环境（--noconftest）下的轻量桩
    for mod in [
        "app", "app.core", "app.core.config", "app.core.event", "app.db", "app.db.site_oper",
        "app.helper", "app.helper.downloader", "app.helper.sites", "app.helper.torrent",
        "app.log", "app.plugins", "app.schemas", "app.schemas.types", "app.utils",
        "app.utils.string", "app.utils.timer",
    ]:
        sys.modules.setdefault(mod, MagicMock())

    class _PluginBase:
        pass

    sys.modules["app.plugins"]._PluginBase = _PluginBase

    _repo_root = Path(__file__).resolve().parents[3]
    _plugin_file = _repo_root / "plugins.v2" / "crossseed" / "__init__.py"
    _spec = importlib.util.spec_from_file_location("crossseed", _plugin_file)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    CrossSeed = _mod.CrossSeed


def test_parse_site_token_colon_with_spaces_in_site_name():
    """站点名包含空格时，冒号右侧正确解析为 passkey。"""
    site_name, passkey, gap = CrossSeed._parse_site_token(
        "Depth Studio:mock_passkey_abcdef0123456789"
    )
    assert site_name == "Depth Studio"
    assert passkey == "mock_passkey_abcdef0123456789"
    assert gap is None


def test_parse_site_token_chinese_colon():
    """支持全角中文冒号。"""
    site_name, passkey, gap = CrossSeed._parse_site_token(
        "Depth Studio：mock_passkey_abcdef0123456789"
    )
    assert site_name == "Depth Studio"
    assert passkey == "mock_passkey_abcdef0123456789"
    assert gap is None


def test_parse_site_token_with_query_gap():
    """支持在 passkey 后配置查询请求间隔时间。"""
    site_name, passkey, gap = CrossSeed._parse_site_token(
        "Depth Studio: mock_passkey_abcdef0123456789 30"
    )
    assert site_name == "Depth Studio"
    assert passkey == "mock_passkey_abcdef0123456789"
    assert gap == "30"


def test_parse_site_token_space_separated_known_site():
    """无冒号时，优先前缀匹配已知站点全名（即使含空格）。"""
    site_name, passkey, gap = CrossSeed._parse_site_token(
        "Depth Studio mock_passkey_abcdef0123456789",
        known_site_names=["Depth Studio", "青蛙"],
    )
    assert site_name == "Depth Studio"
    assert passkey == "mock_passkey_abcdef0123456789"
    assert gap is None


def test_parse_site_token_single_word_site_name():
    """兼容旧式单字词站点名称的无冒号与有冒号格式。"""
    s1, p1, g1 = CrossSeed._parse_site_token("青蛙:xxxxxx")
    assert (s1, p1, g1) == ("青蛙", "xxxxxx", None)

    s2, p2, g2 = CrossSeed._parse_site_token("青蛙 xxxxxx 10")
    assert (s2, p2, g2) == ("青蛙", "xxxxxx", "10")


def test_parse_site_token_empty_and_whitespace():
    """空行或纯空白返回空值。"""
    assert CrossSeed._parse_site_token("") == (None, None, None)
    assert CrossSeed._parse_site_token("   \n  ") == (None, None, None)


def test_parse_site_token_case_insensitivity():
    """解析出的站点名称保持原样，以便后续进行大小写无关匹配。"""
    s1, p1, _ = CrossSeed._parse_site_token("ptfans:token123")
    assert s1 == "ptfans"
    assert p1 == "token123"

