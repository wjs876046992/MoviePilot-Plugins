"""站点刷流 V3 插件：H&R 判定来源标记单测。

背景：插件把种子标记为 H&R 有两个来源 —— 站点索引器解析出的 `hit_and_run`，
以及任务里手动勾选的「全站 H&R」。原先记录里只存一个布尔值，从界面上分不清
一颗种子是「站点声明带考核」还是「被全站开关连坐」，排查时无从下手。

`hr_source` 字段记录判定出处，本用例锁住三种取值：
`site`（站点标记）/ `task_site_hr`（全站开关）/ `""`（均不成立）。
"""
from types import SimpleNamespace

from app.plugins.brushflow import BrushFlow, BrushTaskConfig


def _task(**overrides):
    """构造任务配置，默认绑定站点与下载器"""
    return BrushTaskConfig(
        {
            "id": "aabbccdd00112233",
            "name": "聆音刷流",
            "site_id": 1,
            "downloader": "qb",
            **overrides,
        }
    )


def _torrent(**overrides):
    """构造站点候选种子的最小替身，字段与 TorrentInfo 对齐"""
    base = dict(
        title="示例种子", size=1024, pubdate=None, description=None, page_url=None,
        date_elapsed=None, freedate=None, uploadvolumefactor=None,
        downloadvolumefactor=None, hit_and_run=False, volume_factor=None,
        freedate_diff=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


_SITE = SimpleNamespace(id=1, name="聆音")


class TestHrSource:
    """_torrent_to_task_record：H&R 来源标记"""

    def test_site_marker_marks_source_site(self):
        """站点声明 H&R 时来源为 site"""
        record = BrushFlow._torrent_to_task_record(_torrent(hit_and_run=True), _SITE, _task())
        assert record["hit_and_run"] is True
        assert record["hr_source"] == "site"

    def test_site_hr_switch_marks_source_task(self):
        """任务勾选「全站 H&R」而站点未标记时，来源为 task_site_hr"""
        task = _task(site_hr_active=True)
        record = BrushFlow._torrent_to_task_record(_torrent(hit_and_run=False), _SITE, task)
        assert record["hit_and_run"] is True
        assert record["hr_source"] == "task_site_hr"

    def test_site_marker_wins_over_switch(self):
        """两者同时成立时以站点标记为准，便于区分真实考核"""
        task = _task(site_hr_active=True)
        record = BrushFlow._torrent_to_task_record(_torrent(hit_and_run=True), _SITE, task)
        assert record["hit_and_run"] is True
        assert record["hr_source"] == "site"

    def test_plain_torrent_has_no_source(self):
        """普通种子既非 H&R 也无来源标记"""
        record = BrushFlow._torrent_to_task_record(_torrent(hit_and_run=False), _SITE, _task())
        assert record["hit_and_run"] is False
        assert record["hr_source"] == ""
