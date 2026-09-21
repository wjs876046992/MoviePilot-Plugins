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


# --------------------------------------------------------------------------
# 清洗历史脏条目（用户实测：上次扫描出的非视频文件还在清单里）
# --------------------------------------------------------------------------

def test_prune_removes_non_video_entries():
    """
    用户实测场景：v0.1.7 的扫描把 jpg/nfo 写进了疑似清单，修复过滤后
    **旧条目仍在**（写入时过滤拦不住已落盘的数据）。载入清洗必须移除它们。
    """
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv"])
    plugin = _plugin(root)
    plugin._strm_suspects = {
        "电视剧:a.mkv": {"ts": 1.0, "origin": strm.ORIGIN_SCAN},        # 视频，保留
        "电视剧:poster.jpg": {"ts": 1.0, "origin": strm.ORIGIN_SCAN},   # 图片，清
        "电视剧:tvshow.nfo": {"ts": 1.0, "origin": strm.ORIGIN_SCAN},   # 元数据，清
        "电视剧:a.zh.srt": {"ts": 1.0, "origin": strm.ORIGIN_SCAN},     # 字幕，清
    }

    removed = plugin._prune_invalid_strm_suspects()

    assert removed == 3
    assert list(plugin._strm_suspects) == ["电视剧:a.mkv"]


def test_prune_removes_ignored_entries():
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv", "b.mkv"])
    plugin = _plugin(root, rules=[_rule("a.mkv")])
    plugin._strm_suspects = {
        "电视剧:a.mkv": {"ts": 1.0, "origin": strm.ORIGIN_SCAN},
        "电视剧:b.mkv": {"ts": 1.0, "origin": strm.ORIGIN_SCAN},
    }
    assert plugin._prune_invalid_strm_suspects() == 1
    assert list(plugin._strm_suspects) == ["电视剧:b.mkv"]


def test_prune_removes_entries_whose_source_is_gone():
    """源端已删除的条目无从重传，留着只会让重传失败。"""
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv"])
    plugin = _plugin(root)
    plugin._strm_suspects = {
        "电视剧:a.mkv": {"ts": 1.0, "origin": strm.ORIGIN_SCAN},
        "电视剧:deleted.mkv": {"ts": 1.0, "origin": strm.ORIGIN_SCAN},
    }
    assert plugin._prune_invalid_strm_suspects() == 1
    assert list(plugin._strm_suspects) == ["电视剧:a.mkv"]


def test_prune_removes_entries_without_strm_dir():
    """映射取消 strm 目录后，验证前提消失，条目应清理。"""
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv"])
    plugin = _plugin(root)
    plugin._sync_pairs[0]["strm_dir"] = ""
    plugin._strm_suspects = {"电视剧:a.mkv": {"ts": 1.0, "origin": strm.ORIGIN_SCAN}}
    assert plugin._prune_invalid_strm_suspects() == 1
    assert plugin._strm_suspects == {}


def test_prune_keeps_legitimate_suspects():
    """真正有问题的条目必须保留 —— 清洗不能变成变相清空。"""
    root = tempfile.mkdtemp()
    _make_src(root, ["bad.mkv"])
    plugin = _plugin(root)
    plugin._strm_suspects = {"电视剧:bad.mkv": {"ts": 1.0, "origin": strm.ORIGIN_WATCH}}
    assert plugin._prune_invalid_strm_suspects() == 0
    assert list(plugin._strm_suspects) == ["电视剧:bad.mkv"]


def test_prune_is_idempotent():
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv"])
    plugin = _plugin(root)
    plugin._strm_suspects = {"电视剧:poster.jpg": {"ts": 1.0, "origin": strm.ORIGIN_SCAN}}
    assert plugin._prune_invalid_strm_suspects() == 1
    assert plugin._prune_invalid_strm_suspects() == 0


# --------------------------------------------------------------------------
# 手动清空
# --------------------------------------------------------------------------

def test_clear_empties_both_lists():
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv"])
    plugin = _plugin(root)
    plugin._strm_suspects = {"电视剧:a.mkv": {"ts": 1.0, "origin": strm.ORIGIN_SCAN}}
    plugin._strm_watch = {"电视剧:b.mkv": 1.0}

    result = plugin._api_strm_clear()

    assert result["success"] is True
    assert plugin._strm_suspects == {}
    assert plugin._strm_watch == {}
    assert "strm_suspects" in plugin.saved and "strm_watch" in plugin.saved


def test_prune_api_reports_counts():
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv"])
    plugin = _plugin(root)
    plugin._strm_suspects = {
        "电视剧:a.mkv": {"ts": 1.0, "origin": strm.ORIGIN_SCAN},
        "电视剧:poster.jpg": {"ts": 1.0, "origin": strm.ORIGIN_SCAN},
    }
    result = plugin._api_strm_prune()
    assert result["data"]["removed"] == 1
    assert result["data"]["remaining"] == 1


# --------------------------------------------------------------------------
# 覆盖「真正会跑的路径」：载入自动清洗 + 指令清空（变异测试发现的缺口）
# --------------------------------------------------------------------------

def test_prune_runs_automatically_on_plugin_load():
    """
    载入时必须**自动**清洗，而不是只提供一个手动入口。

    **这条用例是被变异测试逼出来的**：最初只测 `_prune_invalid_strm_suspects`
    本身，因此把 init_plugin 里那行调用删掉时测试**依然全绿** —— 用户升级后
    旧脏条目照样留着，正是本次要解决的问题。必须走完整载入路径才拦得住。
    """
    import importlib
    import tempfile

    module = importlib.import_module("app.plugins.rsync115sync")
    root = tempfile.mkdtemp()
    src = os.path.join(root, "src")
    os.makedirs(src)
    for name in ("bad.mkv", "poster.jpg"):
        with open(os.path.join(src, name), "wb") as fh:
            fh.write(b"x")

    stored = {
        # 模拟升级前落盘的脏数据：jpg 被判成疑似
        "strm_suspects": {
            "电视剧:bad.mkv": {"ts": 1.0, "origin": "scan"},
            "电视剧:poster.jpg": {"ts": 1.0, "origin": "scan"},
        },
    }
    saved = {}

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{
        "name": "电视剧", "src": src, "dest": "/115/TV",
        "strm_dir": os.path.join(root, "strm"), "all_ext": False,
    }]
    plugin._exclude_patterns = "@eaDir/"
    plugin._media_extensions = "mkv,srt"
    plugin._ignored_rules = []
    plugin._notify = False
    plugin._strm_notified = False
    plugin._strm_watch = {}
    plugin._strm_suspects = {}
    plugin._strm_grace_hours = 6.0
    plugin._strm_check_enabled = True
    plugin._strm_last_check = 0.0
    plugin._enabled = True
    plugin._listen_transfer = True
    plugin._delay_hours = 2.0
    plugin._cron = "0 */2 * * *"
    plugin._media_extensions = "mkv,srt"
    plugin._rsync_timeout = 600
    plugin._task_timeout = 3600
    plugin._rate_limit_enabled = True
    plugin._upload_batch_size = 200
    plugin._upload_max_per_window = 500
    plugin._upload_window_secs = 1800
    plugin._backoff_secs = 3600
    plugin._rate_limit_keywords = "429"
    plugin._force_cooldown_days = 7
    plugin._pending_queue = {}
    plugin._backfill_queue = []
    plugin._missed_queue = {}
    plugin._last_status = {}
    plugin.get_data = lambda k: stored.get(k)
    plugin.save_data = lambda k, v: (saved.__setitem__(k, v), stored.__setitem__(k, v))[0]
    plugin.update_config = lambda c: True

    plugin.init_plugin({"enabled": True, "sync_pairs": plugin._sync_pairs})

    assert "电视剧:poster.jpg" not in plugin._strm_suspects, (
        "载入时未自动清洗历史脏条目 —— init_plugin 里的 _prune_invalid_strm_suspects 调用可能被移除"
    )
    assert "电视剧:bad.mkv" in plugin._strm_suspects


def test_strm_command_clear_and_prune_modes():
    """/rsync_strm clear 与 prune 必须真的生效（而非落到搜索分支）。"""
    import importlib

    module = importlib.import_module("app.plugins.rsync115sync")
    root = tempfile.mkdtemp()
    src = os.path.join(root, "src")
    os.makedirs(src)
    with open(os.path.join(src, "a.mkv"), "wb") as fh:
        fh.write(b"x")

    plugin = _plugin(root)
    plugin._strm_suspects = {"电视剧:a.mkv": {"ts": 1.0, "origin": "scan"}}
    plugin._strm_watch = {"电视剧:a.mkv": 1.0}
    replies = []
    plugin._post_reply = lambda ev, text: replies.append(text)

    class _Ev:
        event_data = {"action": "strm", "arg_str": "clear"}

    plugin.handle_command(_Ev())

    assert plugin._strm_suspects == {} and plugin._strm_watch == {}
    assert any("清空" in r for r in replies)


def test_strm_command_prune_mode():
    import importlib

    module = importlib.import_module("app.plugins.rsync115sync")
    root = tempfile.mkdtemp()
    _make_src(root, ["a.mkv"])
    plugin = _plugin(root)
    plugin._strm_suspects = {
        "电视剧:a.mkv": {"ts": 1.0, "origin": "scan"},
        "电视剧:poster.jpg": {"ts": 1.0, "origin": "scan"},
    }
    replies = []
    plugin._post_reply = lambda ev, text: replies.append(text)

    class _Ev:
        event_data = {"action": "strm", "arg_str": "prune"}

    plugin.handle_command(_Ev())

    assert list(plugin._strm_suspects) == ["电视剧:a.mkv"]
    assert any("清理" in r for r in replies)
