"""
strm 疑似上传异常的催办提醒与免打扰时段测试。

验证：
1. _is_hour_in_window：正常时段（如 9-21）与跨午夜时段（如 22-6）判定正确；
2. 新发现疑似异常即时报警，即使已有历史异常未处理，也不会被旧锁阻断；
3. 未解决疑似异常在间隔未到时，不重复提醒；
4. 未解决疑似异常在间隔到达但处于免打扰时段时，不发送提醒；
5. 未解决疑似异常在间隔到达且处于生效时段时，发送带操作按钮的催办提醒；
6. 催办提醒更新 _strm_last_notified_ts 并持久化；
7. 疑似清单清空后，重置提醒时间戳与闩锁，终止催办；
8. 提醒间隔设为 0 时，彻底禁用催办提醒。
"""

import importlib.util
import os
import sys
import time
import types

import pytest

# 构造无宿主环境桩
for _m in [
    "app", "app.core", "app.core.event", "app.plugins", "app.sdk",
    "app.sdk.logging", "app.schemas", "app.schemas.types",
    "app.schemas.mediaserver", "app.sdk.scheduler", "app.sdk.plugins",
    "apscheduler", "apscheduler.triggers", "apscheduler.triggers.cron",
]:
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)

sys.modules["app.plugins"]._PluginBase = object
sys.modules["app.core.event"].Event = object
sys.modules["app.core.event"].EventType = types.SimpleNamespace(
    CommandExcute=1, PluginReload=2, MessageAction=3, PluginAction=4,
    TransferComplete=5, SubtitleTransferComplete=6, AudioTransferComplete=7,
    WebhookMessage=8,
)
sys.modules["app.core.event"].eventmanager = types.SimpleNamespace(
    send_event=lambda *a, **kw: None,
    register=lambda *a, **kw: (lambda fn: fn),
)
sys.modules["app.sdk.logging"].logger = types.SimpleNamespace(
    info=lambda *a, **kw: None, debug=lambda *a, **kw: None,
    warning=lambda *a, **kw: None, error=lambda *a, **kw: None,
)
sys.modules["apscheduler.triggers.cron"].CronTrigger = object

_PLUGIN_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "plugins.v3", "rsync115sync"))
_PKG = "rsync115sync_remind_test_pkg"

_pkg = types.ModuleType(_PKG)
_pkg.__path__ = [_PLUGIN_DIR]
_pkg.__file__ = os.path.join(_PLUGIN_DIR, "__init__.py")
sys.modules[_PKG] = _pkg

_spec = importlib.util.spec_from_file_location(
    _PKG, _pkg.__file__, submodule_search_locations=[_PLUGIN_DIR])
_mod = importlib.util.module_from_spec(_spec)
_mod.__package__ = _PKG
sys.modules[_PKG] = _mod
_spec.loader.exec_module(_mod)

Rsync115Sync = _mod.Rsync115Sync
strm_ops_mod = sys.modules[f"{_PKG}.strm_ops"]
_is_hour_in_window = strm_ops_mod._is_hour_in_window


def _create_plugin(tmp_path, *, remind_hours=2, start_hour=9, end_hour=21):
    plugin = Rsync115Sync.__new__(Rsync115Sync)
    plugin.plugin_version = "0.5.3-test"
    plugin._enabled = True
    plugin._notify = True
    plugin._sync_pairs = [{
        "name": "电视剧",
        "src": str(tmp_path / "src"),
        "dest": "/dest/TV",
        "strm_dir": "/strms/TV",
        "pan_dir": "/pan/TV",
        "all_ext": False,
    }]
    plugin._strm_suspects = {}
    plugin._strm_watch = {}
    plugin._strm_gen_requested = {}
    plugin._strm_notified = False
    plugin._strm_last_notified_ts = 0.0
    plugin._strm_suspect_remind_hours = remind_hours
    plugin._strm_suspect_remind_start_hour = start_hour
    plugin._strm_suspect_remind_end_hour = end_hour
    plugin._strm_grace_minutes = 5
    plugin._strm_check_enabled = True
    plugin._strm_last_check = 0.0
    plugin._plugin_mtype = lambda: "plugin"

    plugin.saved_data = {}
    plugin.save_data = lambda k, v: plugin.saved_data.__setitem__(k, v)
    plugin.get_data = lambda k: plugin.saved_data.get(k)
    return plugin


# --------------------------------------------------------------------------
# 1. 时段窗口判定
# --------------------------------------------------------------------------

def test_is_hour_in_window():
    # 正常白天时段 9-21 点
    assert _is_hour_in_window(9, 9, 21) is True
    assert _is_hour_in_window(15, 9, 21) is True
    assert _is_hour_in_window(21, 9, 21) is True
    assert _is_hour_in_window(8, 9, 21) is False
    assert _is_hour_in_window(22, 9, 21) is False
    assert _is_hour_in_window(0, 9, 21) is False

    # 跨午夜时段 22 点到次日 6 点
    assert _is_hour_in_window(22, 22, 6) is True
    assert _is_hour_in_window(23, 22, 6) is True
    assert _is_hour_in_window(0, 22, 6) is True
    assert _is_hour_in_window(6, 22, 6) is True
    assert _is_hour_in_window(7, 22, 6) is False
    assert _is_hour_in_window(12, 22, 6) is False


# --------------------------------------------------------------------------
# 2. 新发现异常即时报警与双轨提醒
# --------------------------------------------------------------------------

def test_new_suspects_alert_immediately(tmp_path):
    """新发现的异常立即推送通知，并刷新提醒时间戳。"""
    plugin = _create_plugin(tmp_path)
    sent = []
    plugin.post_message = lambda **kw: sent.append(kw)

    plugin._strm_suspects = {"电视剧:ep1.mkv": {"ts": 1000.0, "origin": "watch"}}
    plugin._notify_strm_suspects(["电视剧:ep1.mkv"])

    assert len(sent) == 1
    assert "发现疑似上传异常" in sent[0]["title"]
    assert "未处理提醒" not in sent[0]["title"]
    assert plugin._strm_notified is True
    assert plugin._strm_last_notified_ts > 0
    assert plugin.saved_data["strm_last_notified_ts"] == plugin._strm_last_notified_ts


def test_new_suspect_alerts_even_if_already_notified(tmp_path):
    """已有旧异常未处理（_strm_notified=True）时，新异常依然必须即时报警，不得被阻断。"""
    plugin = _create_plugin(tmp_path)
    sent = []
    plugin.post_message = lambda **kw: sent.append(kw)

    # 模拟之前已发过通知
    plugin._strm_suspects = {"电视剧:ep1.mkv": {"ts": 1000.0, "origin": "watch"}}
    plugin._strm_notified = True
    plugin._strm_last_notified_ts = 1000.0

    # 新异常 ep2 进入
    plugin._strm_suspects["电视剧:ep2.mkv"] = {"ts": 2000.0, "origin": "watch"}
    plugin._notify_strm_suspects(["电视剧:ep2.mkv"])

    assert len(sent) == 1, "新发现的异常被旧闩锁误阻断"
    assert "ep2.mkv" in sent[0]["text"]
    assert plugin._strm_last_notified_ts > 1000.0


# --------------------------------------------------------------------------
# 3. 催办提醒条件判定
# --------------------------------------------------------------------------

def test_remind_skipped_when_interval_not_reached(tmp_path, monkeypatch):
    """提醒间隔未到（如过去 1 小时 < 2 小时），不发送催办提醒。"""
    plugin = _create_plugin(tmp_path, remind_hours=2)
    sent = []
    plugin.post_message = lambda **kw: sent.append(kw)

    now_ts = 10000.0
    plugin._strm_suspects = {"电视剧:ep1.mkv": {"ts": now_ts - 3600, "origin": "watch"}}
    plugin._strm_last_notified_ts = now_ts - 3600  # 1小时前发过

    # 模拟处于 14 点（时段内）
    monkeypatch.setattr(time, "localtime", lambda ts: types.SimpleNamespace(tm_hour=14))

    plugin._check_suspect_remind(now_ts)
    assert len(sent) == 0, "间隔未到却提前发送了催办提醒"


def test_remind_skipped_outside_time_window(tmp_path, monkeypatch):
    """虽已超过 2 小时，但处于免打扰时段（如 22 点），不发送催办提醒。"""
    plugin = _create_plugin(tmp_path, remind_hours=2, start_hour=9, end_hour=21)
    sent = []
    plugin.post_message = lambda **kw: sent.append(kw)

    now_ts = 10000.0
    plugin._strm_suspects = {"电视剧:ep1.mkv": {"ts": now_ts - 7200, "origin": "watch"}}
    plugin._strm_last_notified_ts = now_ts - 7200  # 2小时前发过

    # 模拟当前处于 22 点（免打扰）
    monkeypatch.setattr(time, "localtime", lambda ts: types.SimpleNamespace(tm_hour=22))

    plugin._check_suspect_remind(now_ts)
    assert len(sent) == 0, "免打扰时段内误发送了催办提醒"


def test_remind_sent_when_interval_and_window_met(tmp_path, monkeypatch):
    """间隔已到（2 小时）且处于 9-21 点生效时段内，成功触发催办提醒。"""
    plugin = _create_plugin(tmp_path, remind_hours=2, start_hour=9, end_hour=21)
    sent = []
    plugin.post_message = lambda **kw: sent.append(kw)

    now_ts = 10000.0
    plugin._strm_suspects = {
        "电视剧:ep1.mkv": {"ts": now_ts - 7200, "origin": "watch"},
        "电视剧:ep2.mkv": {"ts": now_ts - 7200, "origin": "watch"},
    }
    plugin._strm_last_notified_ts = now_ts - 7200  # 2小时前发过

    # 模拟当前处于 15 点
    monkeypatch.setattr(time, "localtime", lambda ts: types.SimpleNamespace(tm_hour=15))

    plugin._check_suspect_remind(now_ts)

    assert len(sent) == 1, "未在满足条件时触发催办提醒"
    msg = sent[0]
    assert "发现疑似上传异常（未处理提醒）" in msg["title"]
    assert "待处理提醒" in msg["text"]
    assert "ep1.mkv" in msg["text"]
    assert "ep2.mkv" in msg["text"]
    assert msg["buttons"] is not None, "催办提醒中未携带交互按钮"
    # 验证时间戳已刷新
    assert plugin._strm_last_notified_ts == now_ts
    assert plugin.saved_data["strm_last_notified_ts"] == now_ts


def test_remind_disabled_when_interval_is_zero(tmp_path, monkeypatch):
    """提醒间隔设为 0 时，彻底禁用催办提醒。"""
    plugin = _create_plugin(tmp_path, remind_hours=0)
    sent = []
    plugin.post_message = lambda **kw: sent.append(kw)

    now_ts = 10000.0
    plugin._strm_suspects = {"电视剧:ep1.mkv": {"ts": 0, "origin": "watch"}}
    plugin._strm_last_notified_ts = 0

    monkeypatch.setattr(time, "localtime", lambda ts: types.SimpleNamespace(tm_hour=14))
    plugin._check_suspect_remind(now_ts)
    assert len(sent) == 0


def test_suspects_cleared_resets_remind_timestamp_and_stops_remind(tmp_path):
    """疑似清单清空后，重置提醒时间戳与通知闩锁，发送已解决通知并停止催办。"""
    plugin = _create_plugin(tmp_path)
    sent = []
    plugin.post_message = lambda **kw: sent.append(kw)

    plugin._strm_notified = True
    plugin._strm_last_notified_ts = 5000.0
    plugin._strm_suspects = {}  # 已经清空

    plugin._reset_strm_notified_if_clear()

    assert plugin._strm_notified is False
    assert plugin._strm_last_notified_ts == 0.0
    assert plugin.saved_data["strm_notified"] is False
    assert plugin.saved_data["strm_last_notified_ts"] == 0.0
    assert len(sent) == 1
    assert "已全部解决" in sent[0]["title"]
