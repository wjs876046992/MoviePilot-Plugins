"""站点刷流 V3 插件：站点定制来源（复活区）解析与筛选单测。

覆盖按站点登记的「复活区」候选来源：
- 只有登记过的域名才启用，未登记站点回落到常规来源；
- NexusPHP 列表页解析出标题、下载链接、体积、促销系数与促销截止时间；
- 「免费剩余时间」严格匹配：无期限信息的种子一律排除；
- 任务配置能携带新增的三个字段。
"""
import logging
from collections import Counter
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
    """模拟 SiteOper().get() 返回的站点对象

    ⚠️ ``domain`` 必须是**裸域名**（不含协议头），``url`` 才带协议 —— 这是 SiteOper
    的真实形态。早期版本在测试里给 domain 塞了 ``https://…``，掩盖了「裸域名拼不出
    可请求 URL」这个真实缺陷，故这里固定按真实数据构造。
    """

    def __init__(
        self,
        name="彩虹岛",
        domain="chdbits.xyz",
        url="https://chdbits.xyz/",
        cookie="uid=1; pass=abc",
    ):
        self.id = 1
        self.name = name
        self.domain = domain
        self.url = url
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


def _parse(html=None, site=None):
    """按真实页面解析候选种子"""
    html = html if html is not None else FIXTURE.read_text(encoding="utf-8")
    return BrushFlow._BrushFlow__parse_nexus_list_rows(html, site or FakeSite())


class TestSiteRegistry:
    """站点登记表：按域名判断，未登记站点不启用定制来源"""

    def test_registered_domain_enables_custom_source(self):
        # 真实形态是裸域名；注册表按域名匹配必须对它生效
        source = BrushFlow._custom_source_for_site(FakeSite(domain="chdbits.xyz"))
        assert source and source["renew_path"] == "renewtorrents.php"

    def test_alternate_domain_also_registered(self):
        """同一站点的备用域名同样命中，与仓库既有 tracker 映射口径一致"""
        source = BrushFlow._custom_source_for_site(FakeSite(domain="ptchdbits.co", url="https://ptchdbits.co/"))
        assert source is not None

    def test_unregistered_domain_has_no_custom_source(self):
        assert BrushFlow._custom_source_for_site(
            FakeSite(domain="example.com", url="https://example.com/")
        ) is None

    def test_registry_keys_are_bare_domains(self):
        """登记表键必须是裸域名，否则 StringUtils.get_url_domain 匹配不到"""
        for domain in SITE_CUSTOM_SOURCES:
            assert "//" not in domain and not domain.endswith("/")


class TestSiteBaseUrl:
    """站点根地址必须带协议头，且不能把页面路径带进来

    回归用例：站点管理里填的 ``url`` 是带协议头的完整地址，``domain`` 只是裸主机名。
    早期实现直接拿 domain 拼 URL，请求打到 ``ptchdbits.co/renewtorrents.php``（无协议）
    而失败；测试桩当时把 domain 写成带协议的假数据，掩盖了这个缺陷。
    """

    def test_bare_domain_gets_https(self):
        """url 缺失时才回落到 domain；带协议头后可直接请求"""
        site = FakeSite(domain="ptchdbits.co", url="")
        assert BrushFlow._site_base_url(site) == "https://ptchdbits.co"

    def test_prefers_url_when_present(self):
        """url 是完整地址，优先使用它"""
        base = BrushFlow._site_base_url(FakeSite(domain="chdbits.xyz", url="https://ptchdbits.co/"))
        assert base == "https://ptchdbits.co"

    def test_trailing_slash_removed(self):
        assert BrushFlow._site_base_url(FakeSite(url="https://chdbits.xyz/")) == "https://chdbits.xyz"

    def test_page_path_is_dropped(self):
        """url 若带页面路径，拼 renewtorrents.php 会 404，故丢弃末段文件名"""
        base = BrushFlow._site_base_url(FakeSite(url="https://ptchdbits.co/browse.php"))
        assert base == "https://ptchdbits.co"

    def test_subdirectory_is_kept(self):
        """站点挂在子目录下时，子目录必须保留"""
        assert BrushFlow._site_base_url(FakeSite(url="https://example.com/pt/")) == "https://example.com/pt"

    def test_existing_scheme_is_kept(self):
        """domain 若已自带协议头（历史数据），不得重复拼接"""
        site = FakeSite(domain="http://chdbits.xyz", url="")
        assert BrushFlow._site_base_url(site) == "http://chdbits.xyz"

    def test_missing_address_returns_empty(self):
        site = FakeSite()
        site.domain = ""
        site.url = ""
        assert BrushFlow._site_base_url(site) == ""

    def test_fallback_to_domain_when_url_empty(self):
        """url 为空时回落到 domain，并补上协议头"""
        assert BrushFlow._site_base_url(FakeSite(domain="chdbits.xyz", url="")) == "https://chdbits.xyz"


class TestRenewUrlConstruction:
    """复活区请求地址与种子链接必须都是可直接请求的绝对地址"""

    def test_renew_url_is_absolute(self):
        site = FakeSite(domain="ptchdbits.co", url="https://ptchdbits.co/")
        base = BrushFlow._site_base_url(site)
        assert f"{base}/renewtorrents.php" == "https://ptchdbits.co/renewtorrents.php"

    def test_parsed_links_carry_scheme(self):
        """回归：裸域名曾解析出无协议的 enclosure，下载器无法取种"""
        results = _parse(site=FakeSite(domain="ptchdbits.co", url="https://ptchdbits.co/"))
        assert results
        assert results[0].enclosure == "https://ptchdbits.co/download.php?id=564651"
        assert results[0].page_url == "https://ptchdbits.co/details.php?id=564651"


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

    def test_hit_and_run_marker_is_parsed(self):
        """H&R 标记写在 div.circle-text 里，必须解析出来

        此前硬编码 hit_and_run=False，导致任务的「排除 H&R」对复活区完全失效。
        """
        html = (
            '<table class="torrentname"><tr>'
            '<td class="embedded"><a title="H5 Movie 2024" href="details.php?id=9">x</a>'
            '<font class="subtitle"><div class="circle">'
            '<div class="circle-text">h5</div></div></font></td>'
            '<td></td><td></td><td><span title="2026-07-19 18:55:39"></span></td>'
            '<td>1.00 / GB</td><td><a>1</a></td><td><a>1</a></td>'
            '</tr></table>'
        )
        assert _parse(html)[0].hit_and_run is True

    def test_plain_row_has_no_hit_and_run(self):
        """无 circle-text 标记的行不应被误判为 H&R"""
        assert _parse()[0].hit_and_run is False

    def test_quantity_marker_is_not_hit_and_run(self):
        """n/N 前缀是纯达量考核，不算 H&R"""
        html = (
            '<table class="torrentname"><tr>'
            '<td class="embedded"><a title="N Movie 2024" href="details.php?id=10">x</a>'
            '<font class="subtitle"><div class="circle">'
            '<div class="circle-text">n5</div></div></font></td>'
            '<td></td><td></td><td><span title="2026-07-19 18:55:39"></span></td>'
            '<td>1.00 / GB</td><td><a>1</a></td><td><a>1</a></td>'
            '</tr></table>'
        )
        assert _parse(html)[0].hit_and_run is False

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

    def test_page_freedate_is_convertible_for_logging(self):
        """排除日志会打印原始时间戳与换算结果，故页面时间必须可被换算

        若此处返回 None，日志就只能显示 freedate 而看不出「还差多少小时」，
        排查「免费剩余时间不足」时会失去最关键的依据。
        """
        torrent = _parse()[0]
        assert torrent.freedate == "2026-10-05 14:42:17"
        assert BrushFlow._BrushFlow__free_remain_hours(torrent.freedate, 0) is not None


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


class _Seed:
    """最小候选种子：计数测试只依赖 title，其余字段给默认值"""

    def __init__(self, title: str, size: float = 0.0, pubdate: str = "2026-01-01 00:00:00"):
        self.title = title
        self.size = size
        self.pubdate = pubdate
        self.description = ""
        self.freedate = None


class _CountingPlugin:
    """把真实的 __brush_site_torrents 跑在受控桩上，用于校验计数口径"""

    def __init__(self, torrents, *, conditions=None, downloads=None, subscription_hits=None,
                 task=None, source_available=True):
        self.torrents = torrents
        self.conditions = conditions or {}
        self.downloads = downloads or {}
        self.subscription_hits = set(subscription_hits or ())
        self.source_available = source_available
        self._task = task or _make_task()
        self.plugin = object.__new__(BrushFlow)
        self.plugin.eventmanager = MagicMock()
        self.plugin.service_info = MagicMock(name="qb")
        # 逐个注入私有方法桩：这些方法各自有独立单测，此处只关心计数与汇总
        self.plugin._BrushFlow__fetch_custom_source_torrents = self._fetch
        self.plugin._BrushFlow__filter_torrents_contains_subscribe = self._filter_subscribe
        self.plugin._BrushFlow__calculate_seeding_torrents_size = lambda _tasks: 0.0
        self.plugin._BrushFlow__evaluate_pre_conditions_for_brush = lambda include_network_conditions=True: (True, None)
        self.plugin._BrushFlow__evaluate_size_condition_for_brush = lambda seeding, size, global_torrents_size=0: (True, None)
        self.plugin._BrushFlow__evaluate_conditions_for_brush = (
            lambda torrent, _tasks: self.conditions.get(torrent.title, (True, None))
        )
        self.plugin._BrushFlow__download = lambda torrent: self.downloads.get(torrent.title)
        self.plugin._BrushFlow__send_add_message = lambda _torrent: None
        self.plugin._torrent_to_task_record = lambda torrent, _site, _task: {"title": torrent.title}
        self.plugin._custom_source_for_site = lambda _site: {"renew_path": "renewtorrents.php"}
        self.plugin._get_task_config = lambda _task_id=None: self._task

    def _fetch(self, _site, _task, _source):
        return list(self.torrents) if self.source_available else []

    def _filter_subscribe(self, torrents, _titles):
        return [item for item in torrents if item.title not in self.subscription_hits]

    def run(self):
        report = {"reason_counts": Counter(), "added_count": 0, "added_titles": []}
        BrushFlow._BrushFlow__brush_site_torrents(
            self.plugin, FakeSite(), {}, {}, set(), report, 0.0
        )
        return report


class TestRoundSummaryCounting:
    """轮末汇总的计数口径

    回归背景：订阅排除的种子从未进入候选，但早期实现把它也写进 reason_counts，
    导致汇总出现「跳过 100 个 > 候选 95 个」这类自相矛盾的数字。
    """

    def test_subscription_exclusion_is_not_counted_as_skipped(self, caplog):
        torrents = [_Seed(f"T{i}") for i in range(10)]
        plugin = _CountingPlugin(
            torrents,
            subscription_hits={"T0", "T1", "T2"},
            conditions={f"T{i}": (False, "重复种子") for i in range(3, 10)},
        )
        with caplog.at_level(logging.INFO):
            report = plugin.run()

        assert report["subscription_excluded"] == 3
        assert report["candidate_count"] == 7
        # 订阅排除不得混进跳过原因
        assert "命中订阅内容" not in report["reason_counts"]
        skipped = sum(report["reason_counts"].values())
        assert skipped == 7
        assert skipped <= report["candidate_count"]

    def test_summary_reports_subscription_separately(self, caplog):
        torrents = [_Seed(f"T{i}") for i in range(5)]
        plugin = _CountingPlugin(
            torrents,
            subscription_hits={"T0"},
            conditions={f"T{i}": (False, "重复种子") for i in range(1, 5)},
        )
        with caplog.at_level(logging.INFO):
            plugin.run()
        summary = [record.getMessage() for record in caplog.records if "本轮结束" in record.getMessage()]
        assert summary, "应输出轮末汇总"
        assert "候选 4 个" in summary[0]
        assert "订阅已排除 1 个" in summary[0]
        assert "跳过 4 个" in summary[0]

    def test_skips_are_not_logged_individually(self, caplog):
        """逐条跳过明细已移除，只保留一条汇总，避免刷屏"""
        torrents = [_Seed(f"T{i}") for i in range(30)]
        plugin = _CountingPlugin(
            torrents, conditions={f"T{i}": (False, "重复种子") for i in range(30)}
        )
        with caplog.at_level(logging.INFO):
            plugin.run()
        messages = [record.getMessage() for record in caplog.records]
        assert not [item for item in messages if "跳过（" in item]
        assert not [item for item in messages if "促销时间详情" in item]
        assert len([item for item in messages if "本轮结束" in item]) == 1

    def test_counts_are_self_consistent_without_subscription(self, caplog):
        """无订阅时「新增 + 跳过」应等于候选数"""
        torrents = [_Seed(f"T{i}") for i in range(12)]
        plugin = _CountingPlugin(
            torrents,
            conditions={f"T{i}": (False, "重复种子") for i in range(2, 12)},
            downloads={"T0": "hash-0"},
        )
        plugin._task = _make_task({"except_subscribe": False})
        with caplog.at_level(logging.INFO):
            report = plugin.run()
        skipped = sum(report["reason_counts"].values())
        assert report["added_count"] + skipped == report["candidate_count"]

    def test_empty_source_warns_and_returns(self, caplog):
        plugin = _CountingPlugin([], source_available=False)
        with caplog.at_level(logging.INFO):
            report = plugin.run()
        messages = [record.getMessage() for record in caplog.records]
        assert report["result"] == "no_candidates"
        assert any("未取得任何候选种子" in item for item in messages)
        assert not [item for item in messages if "本轮结束" in item]


class TestDownloaderScopedLimits:
    """按下载器维度的限额：体积统计与删除分组必须严格隔离

    回归背景：多台下载器位于不同机器、磁盘容量各异。早期只有一个跨下载器的
    总量阈值，先满的一台会牵连其余台，删除时也可能从还有空间的机器上删种。
    """

    GB = 1024 ** 3

    def _plugin(self, limits=None, global_disksize=None, global_range=None):
        plugin = object.__new__(BrushFlow)
        plugin._downloader_limits = limits or {}
        plugin._global_disksize = global_disksize
        plugin._global_delete_size_range = global_range
        return plugin

    def test_downloader_limit_takes_priority_over_global(self):
        plugin = self._plugin(
            limits={"qb-a": {"disksize": 50, "proxy_delete": True, "delete_size_range": "40-50"}},
            global_disksize=999,
        )
        site_task = _make_task({"downloader": "qb-a"})
        limit, scope, _label = plugin._seeding_scope(site_task)
        assert limit == 50
        assert scope == "downloader"

    def test_unconfigured_downloader_falls_back_to_global(self):
        plugin = self._plugin(limits={}, global_disksize=999)
        limit, scope, _label = plugin._seeding_scope(_make_task({"downloader": "qb-b"}))
        assert limit == 999
        assert scope == "global"

    def test_no_limit_configured_means_unlimited(self):
        plugin = self._plugin(limits={})
        limit, scope, _label = plugin._seeding_scope(_make_task({"downloader": "qb-c"}))
        assert limit is None
        assert scope == "none"

    def test_seeding_size_counts_only_own_downloader(self):
        """qb-a 的体积不得包含 qb-b 的种子"""
        plugin = object.__new__(BrushFlow)
        plugin._task_configs = {
            "t1": _make_task({"downloader": "qb-a"}),
            "t3": _make_task({"downloader": "qb-b"}),
        }
        plugin._BrushFlow__calculate_seeding_torrents_size = staticmethod(
            lambda rows: sum(row.get("size", 0) for row in rows.values())
        )
        sizes = {"t1": {"a": {"size": 10 * self.GB}}, "t3": {"c": {"size": 99 * self.GB}}}
        plugin._get_task_data = lambda task_id, _name: sizes[task_id]
        assert plugin._calculate_downloader_seeding_size("qb-a") == 10 * self.GB
        assert plugin._calculate_downloader_seeding_size("qb-b") == 99 * self.GB

    def test_size_range_rejects_inverted_bounds(self):
        """区间写反必须拒绝：早期任务级缺这条校验，会退化成「一直删」"""
        assert BrushFlow._parse_size_range_limits("40-50") == (40 * self.GB, 50 * self.GB)
        assert BrushFlow._parse_size_range_limits("50-40") is None
        assert BrushFlow._parse_size_range_limits("50") == (50 * self.GB, 50 * self.GB)

    def test_candidates_grouped_by_downloader(self):
        """配了阈值的下载器独立成组，其余合并进全局组"""
        plugin = self._plugin(
            limits={"qb-a": {"disksize": 50, "proxy_delete": True, "delete_size_range": "40-50"}},
            global_range="80-100",
        )
        candidates = [
            {"downloader_name": "qb-a", "torrent_hash": "a1", "size": 10 * self.GB},
            {"downloader_name": "qb-a", "torrent_hash": "a2", "size": 20 * self.GB},
            {"downloader_name": "qb-b", "torrent_hash": "b1", "size": 30 * self.GB},
            {"downloader_name": "qb-c", "torrent_hash": "c1", "size": 40 * self.GB},
        ]
        groups = plugin._group_candidates_by_scope(candidates, 100 * self.GB)
        assert set(groups) == {"qb-a", "__global__"}
        assert groups["qb-a"]["total_size"] == 30 * self.GB
        assert groups["qb-a"]["max_size"] == 50 * self.GB
        assert groups["__global__"]["total_size"] == 70 * self.GB
        assert groups["__global__"]["max_size"] == 100 * self.GB

    def test_normalize_limits_drops_empty_and_invalid_entries(self):
        """空条目与非法区间被丢弃，不应连带整份设置加载失败"""
        normalized = BrushFlow._normalize_downloader_limits(
            {
                "qb-a": {"disksize": 50, "proxy_delete": True, "delete_size_range": "40-50"},
                "qb-empty": {"disksize": None, "proxy_delete": False, "delete_size_range": None},
                "qb-bad": {"disksize": 10, "proxy_delete": True, "delete_size_range": "50-40"},
                "": {"disksize": 5},
            }
        )
        assert "qb-a" in normalized
        assert "qb-empty" not in normalized
        assert "qb-bad" not in normalized, "区间写反应被丢弃"
        assert "" not in normalized
