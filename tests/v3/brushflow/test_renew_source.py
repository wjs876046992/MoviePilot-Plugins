"""站点刷流 V3 插件：站点定制来源（复活区）解析与筛选单测。

覆盖按站点登记的「复活区」候选来源：
- 只有登记过的域名才启用，未登记站点回落到常规来源；
- NexusPHP 列表页解析出标题、下载链接、体积、促销系数与促销截止时间；
- 「免费剩余时间」严格匹配：无期限信息的种子一律排除；
- 任务配置能携带新增的三个字段。
"""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.plugins.brushflow import SITE_CUSTOM_SOURCES, BrushFlow, BrushTaskConfig
from app.sdk.config import settings


def _expiry_in(hours: float) -> str:
    """按宿主时区生成 N 小时后的站点时间戳

    ``_promotion_expiry_at`` 把站点时间当作宿主时区的墙上时间再附加时区，
    因此必须用宿主时区生成，否则比较会带上时区偏差。
    """
    return (datetime.now(ZoneInfo(settings.TZ)) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

FIXTURE = Path(__file__).parent / "fixtures" / "renew_list.html"


class FakeSite:
    """模拟 SiteOper().get() 返回的站点对象"""

    def __init__(self, name="彩虹岛", domain="https://chdbits.xyz/", cookie="uid=1; pass=abc"):
        self.id = 1
        self.name = name
        self.domain = domain
        self.cookie = cookie
        self.proxy = False
        self.timeout = 15
        self.public = False


def _make_task(config=None):
    """构造任务配置，可覆盖新加入的复活区字段"""
    return BrushTaskConfig(
        {
            "id": "aabbccdd00112233",
            "name": "彩虹岛复活区",
            "site_id": 1,
            "downloader": "qb",
            **(config or {}),
        }
    )


def _make_plugin(task):
    """构造不经过 __init__ 的 BrushFlow 实例"""
    plugin = object.__new__(BrushFlow)
    plugin._task_configs = {task.id: task}
    plugin._task_locks = {}
    plugin._runtime = {}
    plugin._task_context = MagicMock()
    plugin._task_context.task_id = task.id
    return plugin


def _parse(html=None):
    """按真实页面解析候选种子"""
    html = html if html is not None else FIXTURE.read_text(encoding="utf-8")
    return BrushFlow._BrushFlow__parse_nexus_list_rows(html, FakeSite())


class TestSiteRegistry:
    """站点登记表：按域名判断，未登记站点不启用定制来源"""

    def test_registered_domain_enables_custom_source(self):
        source = BrushFlow._custom_source_for_site(FakeSite(domain="https://chdbits.xyz/"))
        assert source and source["renew_path"] == "renewtorrents.php"

    def test_alternate_domain_also_registered(self):
        """同一站点的备用域名同样命中，与仓库既有 tracker 映射口径一致"""
        source = BrushFlow._custom_source_for_site(FakeSite(domain="https://ptchdbits.co/"))
        assert source is not None

    def test_unregistered_domain_has_no_custom_source(self):
        assert BrushFlow._custom_source_for_site(FakeSite(domain="https://example.com/")) is None

    def test_registry_keys_are_bare_domains(self):
        """登记表键必须是裸域名，否则 StringUtils.get_url_domain 匹配不到"""
        for domain in SITE_CUSTOM_SOURCES:
            assert "//" not in domain and not domain.endswith("/")


class TestParseNexusList:
    """解析 NexusPHP 列表页：字段取值与真实页面结构对齐"""

    def test_parses_single_row(self):
        results = _parse()
        assert len(results) == 1
        torrent = results[0]
        assert torrent.title == "Flower Of Evil S01 1080p HamiVideo WEB-DL AAC2.0 H.264-CHDWEB"
        assert torrent.enclosure == "https://chdbits.xyz/download.php?id=564651"
        assert torrent.page_url == "https://chdbits.xyz/details.php?id=564651"

    def test_size_converted_to_bytes(self):
        """页面是「63.28 / GB」，必须转成字节，否则体积判定全盘出错"""
        size = _parse()[0].size
        assert size == pytest.approx(63.28 * 1024 ** 3, rel=1e-3)

    def test_promotion_and_expiry(self):
        """促销系数取 img.pro_*，截止时间取「限时」后的 span@title"""
        torrent = _parse()[0]
        assert torrent.downloadvolumefactor == 0
        assert torrent.uploadvolumefactor == 1
        assert torrent.freedate == "2026-10-05 14:42:17"

    def test_pubdate_not_confused_with_freedate(self):
        """发布时间与促销截止时间同为 span@title，不能混淆"""
        torrent = _parse()[0]
        assert torrent.pubdate == "2026-07-19 18:55:39"

    def test_seeders_and_leechers(self):
        torrent = _parse()[0]
        assert torrent.seeders == 141
        assert torrent.leechers == 1

    def test_description_is_real_subtitle_not_tag(self):
        """描述取真正的描述句，而不是「官方」「中字」这类内联标签"""
        assert "恶之花" in (_parse()[0].description or "")
        assert _parse()[0].description not in {"官方", "中字"}

    def test_carries_site_identity_for_dedup_and_download(self):
        """site_name 决定去重键、site_cookie 决定能否取到种子，缺一即失效"""
        torrent = _parse()[0]
        assert torrent.site_name == "彩虹岛"
        assert torrent.site_cookie == "uid=1; pass=abc"

    def test_no_hit_and_run_for_this_site(self):
        """彩虹岛复活区无 H&R 标记，统一按无 H&R 处理"""
        assert _parse()[0].hit_and_run is False

    def test_empty_or_garbage_html_is_safe(self):
        assert _parse("") == []
        assert _parse("<html><body>无种子</body></html>") == []

    def test_row_without_details_anchor_is_skipped(self):
        html = '<table class="torrentname"><tr><td>无效行</td></tr></table>'
        assert _parse(html) == []


class FakeTorrent:
    """模拟 TorrentInfo：只带筛选逻辑会读取的字段

    促销与体积字段必须给真实值：免费判定先于放宽条件执行，用 MagicMock 的隐式
    真值会让「非免费种子」先返回，从而掩盖真正要测的免费剩余时间分支。
    """

    def __init__(self, freedate=None, **overrides):
        attrs = {
            "title": "测试种子",
            "description": "",
            "page_url": "",
            "site_name": "彩虹岛",
            "downloadvolumefactor": 0,
            "uploadvolumefactor": 1,
            "hit_and_run": False,
            "size": 0,
            "seeders": 1,
            "pubdate": None,
            "freedate": freedate,
        }
        attrs.update(overrides)
        self.__dict__.update(attrs)


class TestFreeRemainFilter:
    """免费剩余时间过滤：严格匹配，无期限信息一律排除"""

    def _evaluate(self, task, freedate, freeleech=""):
        """走真实的筛选方法，促销要求置空以隔离免费剩余时间这一条规则"""
        task = _make_task({"freeleech": freeleech, **task})
        plugin = _make_plugin(task)
        plugin._get_task_config = lambda task_id=None: task
        passed, reason = BrushFlow._BrushFlow__evaluate_conditions_for_brush(
            plugin, FakeTorrent(freedate=freedate, site_name="彩虹岛"), {}
        )
        return passed, reason

    def test_missing_expiry_is_rejected(self):
        passed, reason = self._evaluate({"free_remain_min": 1}, None)
        assert not passed
        assert reason == "无免费期限信息"

    def test_remain_below_min_is_rejected(self):
        passed, reason = self._evaluate({"free_remain_min": 100}, _expiry_in(1))
        assert not passed
        assert reason == "免费剩余时间不足"

    def test_remain_above_max_is_rejected(self):
        passed, reason = self._evaluate({"free_remain_max": 1}, _expiry_in(100))
        assert not passed
        assert reason == "免费剩余时间过长"

    def test_remain_within_range_passes(self):
        passed, _ = self._evaluate({"free_remain_min": 1, "free_remain_max": 100}, _expiry_in(10))
        assert passed

    def test_no_free_remain_config_skips_check(self):
        """未配置免费剩余时间时不参与筛选，无期限信息也不应被排除"""
        passed, _ = self._evaluate({}, None)
        assert passed

    def test_remain_hours_returns_none_without_freedate(self):
        assert BrushFlow._BrushFlow__free_remain_hours(None, 0) is None
        assert BrushFlow._BrushFlow__free_remain_hours("", 0) is None
        assert BrushFlow._BrushFlow__free_remain_hours("not-a-date", 0) is None


class TestTaskConfigCarriesRenewFields:
    """任务配置：新增字段可读写，且默认关闭"""

    def test_defaults(self):
        task = _make_task()
        assert task.renew_support is False
        assert task.free_remain_min is None
        assert task.free_remain_max is None

    def test_values_are_read(self):
        task = _make_task({"renew_support": True, "free_remain_min": 6, "free_remain_max": 100})
        assert task.renew_support is True
        assert task.free_remain_min == 6
        assert task.free_remain_max == 100

    def test_round_trip_through_to_dict(self):
        task = _make_task({"renew_support": True, "free_remain_min": 6})
        data = task.to_dict()
        assert data["renew_support"] is True
        assert data["free_remain_min"] == 6
