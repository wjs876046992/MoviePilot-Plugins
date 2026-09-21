"""
strm 相关路径必须遵守忽略规则。

Ignore rules must be honoured by every strm path.

**为什么单独测这一组**：用户实测反馈「已设置为忽略的文件也出现了」。
根因是 strm 的三条链路（登记观察 / 同步后巡检 / 主动扫描 / 关键字检查）
都没有读忽略规则，而**其它所有路径**（对账、补传候选、同步）都读了 ——
属于新功能漏掉了既有契约。忽略的语义是「不要再为这个文件报警」，
而 strm 疑似同样是一种报警，漏过滤会让用户收到自己明确忽略过的文件的告警。
"""

import importlib
import os
import tempfile

import pytest

from app.plugins.rsync115sync import strm


def _plugin(root, *, rules=None, pair_name="电视剧", all_ext=False):
    """构造带忽略规则的最小实例，源端与 strm 端由调用方预先建好。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{
        "name": pair_name, "src": os.path.join(root, "src"),
        "dest": "/115/TV", "strm_dir": os.path.join(root, "strm"),
        "all_ext": all_ext,
    }]
    plugin._exclude_patterns = "@eaDir/\n#recycle/"
    plugin._media_extensions = "mkv,srt,ssa,ass"
    plugin._strm_check_enabled = True
    plugin._strm_grace_hours = 6.0
    plugin._strm_last_check = 0.0
    plugin._strm_notified = False
    plugin._strm_watch = {}
    plugin._strm_suspects = {}
    plugin._ignored_rules = rules or []
    plugin._last_status = {"missing_files": [], "corrupt_files": []}
    plugin._notify = False
    plugin.saved = {}
    plugin.save_data = lambda k, v: plugin.saved.__setitem__(k, v)
    plugin.post_message = lambda **kw: None
    plugin._plugin_mtype = lambda: "plugin"
    return plugin


def _make_src(root, names):
    src = os.path.join(root, "src")
    os.makedirs(src, exist_ok=True)
    for name in names:
        with open(os.path.join(src, name), "wb") as fh:
            fh.write(b"x")


def _rule(text, match="contains"):
    return {"rule": text, "match": match}


# --------------------------------------------------------------------------
# 主动扫描
# --------------------------------------------------------------------------

def test_scan_skips_ignored_files():
    """用户实测场景：已忽略的文件不得进入疑似清单。"""
    root = tempfile.mkdtemp()
    _make_src(root, ["ignored.mkv", "wanted.mkv"])
    plugin = _plugin(root, rules=[_rule("ignored")])

    result = plugin._strm_scan()

    assert result["success"] is True
    assert len(plugin._strm_suspects) == 1
    assert "wanted.mkv" in next(iter(plugin._strm_suspects))
    assert result["data"]["skipped_ignored"] == 1


def test_scan_reports_skipped_count_in_message():
    """跳过数量要显式告知，否则用户会以为扫描漏掉了文件。"""
    root = tempfile.mkdtemp()
    _make_src(root, ["ignored.mkv"])
    plugin = _plugin(root, rules=[_rule("ignored")])
    result = plugin._strm_scan()
    assert plugin._strm_suspects == {}
    assert "忽略" in result["message"]


def test_scan_without_rules_flags_everything():
    """没有忽略规则时行为不变（证明过滤是有针对性的，不是把结果一律砍掉）。"""
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv", "b.mkv"])
    plugin = _plugin(root, rules=[])
    plugin._strm_scan()
    assert len(plugin._strm_suspects) == 2


def test_scan_exact_match_rule_only_skips_that_file():
    """exact 规则只忽略指定文件，不该连带忽略别的。"""
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv", "b.mkv"])
    plugin = _plugin(root, rules=[_rule("电视剧:a.mkv", "exact")])
    plugin._strm_scan()
    assert list(plugin._strm_suspects) == ["电视剧:b.mkv"]


# --------------------------------------------------------------------------
# 关键字检查
# --------------------------------------------------------------------------

def test_keyword_check_skips_ignored_files():
    root = tempfile.mkdtemp()
    _make_src(root, ["黄泉的使者 S01E03.mkv"])
    plugin = _plugin(root, rules=[_rule("黄泉的使者 S01E03")])

    class _Ev:
        event_data = {}

    plugin._reply_strm_keyword(_Ev(), "黄泉的使者")
    assert plugin._strm_suspects == {}


# --------------------------------------------------------------------------
# 登记观察（最上游，拦掉后后续全不涉及）
# --------------------------------------------------------------------------

def test_arm_watch_skips_ignored_files():
    """
    被忽略的文件不该进入观察清单 —— 这是最上游的拦截点。
    只在展示层过滤的话，它仍会到期转疑似并**触发通知**。
    """
    root = tempfile.mkdtemp()
    _make_src(root, ["ignored.mkv", "wanted.mkv"])
    plugin = _plugin(root, rules=[_rule("ignored")])

    armed = plugin._strm_arm_watch(["电视剧:ignored.mkv", "电视剧:wanted.mkv"])

    assert armed == 1
    assert list(plugin._strm_watch) == ["电视剧:wanted.mkv"]


def test_arm_watch_without_rules_arms_all():
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv", "b.mkv"])
    plugin = _plugin(root)
    armed = plugin._strm_arm_watch(["电视剧:a.mkv", "电视剧:b.mkv"])
    assert armed == 2


# --------------------------------------------------------------------------
# 同步后巡检（观察期内才加规则的情形）
# --------------------------------------------------------------------------

def test_check_drops_ignored_entry_instead_of_turning_it_into_suspect():
    """
    观察期内用户加了忽略规则 → 巡检必须让位，不能到期转疑似并通知。
    这是「用户会收到自己忽略过的文件告警」的最后一道防线。
    """
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv"])
    plugin = _plugin(root, rules=[_rule("a.mkv")])
    # 手工塞入一个早已过期的观察项
    plugin._strm_watch["电视剧:a.mkv"] = 1.0
    plugin._strm_last_check = 0.0

    result = plugin._strm_check()

    assert plugin._strm_suspects == {}, "忽略项不得转为疑似"
    assert "电视剧:a.mkv" not in plugin._strm_watch, "忽略项应被清理出观察清单"
    assert result["new_suspects"] == 0


# --------------------------------------------------------------------------
# 加规则时清理既有清单
# --------------------------------------------------------------------------

def test_add_rule_purges_existing_strm_lists():
    """
    加规则后要清理**已有**的 strm 条目，否则清单里的旧条目还挂着，
    看板照旧显示、还可能被「全部删旧重传」波及 —— 用户会觉得「忽略了没用」。
    """
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv", "b.mkv"])
    plugin = _plugin(root)
    plugin._strm_suspects = {
        "电视剧:a.mkv": {"ts": 1.0, "origin": strm.ORIGIN_SCAN},
        "电视剧:b.mkv": {"ts": 1.0, "origin": strm.ORIGIN_SCAN},
    }
    plugin._strm_watch = {"电视剧:a.mkv": 1.0}

    plugin._add_ignore_rule("a.mkv", match="contains")

    assert list(plugin._strm_suspects) == ["电视剧:b.mkv"]
    assert plugin._strm_watch == {}
    assert "strm_suspects" in plugin.saved
    assert "strm_watch" in plugin.saved


def test_add_rule_also_purges_missing_and_corrupt():
    """原有行为不能被破坏：missing/corrupt 仍要清理。"""
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv"])
    plugin = _plugin(root)
    plugin._last_status = {
        "missing_files": ["电视剧:a.mkv", "电视剧:b.mkv"],
        "corrupt_files": ["电视剧:a.mkv"],
    }
    plugin._add_ignore_rule("a.mkv")
    assert plugin._last_status["missing_files"] == ["电视剧:b.mkv"]
    assert plugin._last_status["corrupt_files"] == []
