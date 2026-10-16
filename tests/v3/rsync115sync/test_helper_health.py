"""
strm 助手健康检查：**只告警、不改行为**，且在「已加载但停用」时也要判为不健康。

Helper health probe: alert-only, and "loaded but disabled" must count as unhealthy.

**为什么要这个检查**：助手停摆后没有任何东西在生成 `.strm`，于是每个同步成功的
文件都会在宽限期后落进疑似清单。用户看到的是一批"上传异常"，真因却是助手没跑 ——
这个真因**只能在这里说**：疑似通知讲的是"宽限期内没见到 .strm"，那正是助手掉线时
的必然现象，它不会自己指向助手。

**为什么判据必须包含 `get_state()`**：停用的插件**仍然留在 `running_plugins` 表里**
（宿主 `lifecycle.py` 在 `init_plugin` 之后无条件写入 `_running[plugin_id]`，只在
`enabled` 时才 `_enable_events`）。因此只判"表里有键"会把「装了但被停用」判成正常，
而那种状态下发过去的命令落在一个事件处理器已关闭的插件上 —— 与"没装"在用户视角
完全一样。本文件的 `test_loaded_but_disabled_is_unhealthy` 钉住这一条。

**为什么探测失败要放行**：`get_state()` 缺失（旧宿主 / 桩环境）时按"可用"处理。
一个会把可用功能判死的探针比没有探针更糟 —— 与 `_helper_accepted_pan_roots`
的「读不到时不阻塞」同一取向。
"""

import importlib.util
import os
import sys
import time
import types

import pytest

# 构造**桩宿主**后加载插件包。
#
# 为什么不用 `importlib.import_module("app.plugins.rsync115sync")`（本仓多数
# 用例的写法）：那条路要求后端在磁盘上，`--noconftest` 也救不了 —— 于是本文件
# 在无后端的开发机上完全跑不起来，而本次改动的关键判据（get_state 那一层）
# 恰恰需要**变异验证**才能真正确认它在起作用。桩宿主让用例在任何机器上可跑。
# 与 test_sidecar_ingest.py 同一手法。
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
_PKG = "rsync115sync_health_test_pkg"

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


def _plugin(root, *, strm_dirs=("/media/strms/TV",), enabled=True, pairs=None):
    """最小实例：只带健康检查真正用到的状态。"""
    src = os.path.join(str(root), "src")
    os.makedirs(src, exist_ok=True)

    plugin = Rsync115Sync.__new__(Rsync115Sync)
    if pairs is None:
        pairs = [{
            "name": "电视剧", "src": src, "dest": "/115/TV",
            "strm_dir": strm_dirs[0] if strm_dirs else "", "pan_dir": "", "all_ext": False,
        }]
    plugin._sync_pairs = pairs
    plugin._strm_check_enabled = enabled
    plugin._strm_grace_minutes = 360
    plugin._notify = False
    plugin.save_data = lambda k, v: None
    return plugin


class _HelperInstance:
    """助手实例替身：可指定启用状态，也可**完全不提供** get_state（旧宿主形态）。"""

    def __init__(self, enabled):
        self._enabled = enabled

    def get_state(self):
        return self._enabled


class _NoStateInstance:
    """没有 `get_state` 的形态 —— 探测必须放行，不得判死。"""


def _stub_manager(monkeypatch, instance, *, helper_id="P115StrmHelper"):
    """把助手实例（或 None = 未加载）注入到插件管理器的运行表里。

    注入目标是**组合根**（插件包 `__init__`）上的 `_PluginManager` —— 与真机一致：
    `strm_ops._plugin_manager_cls()` 刻意优先取包根那个绑定，正是为了让宿主与测试
    都只在一个地方 patch。这里 patch 到 `strm_ops` 模块上会**不生效**（真机同理）。
    """

    class _PM:
        def __init__(self):
            self.running_plugins = {helper_id: instance} if instance is not None else {}

    monkeypatch.setattr(_mod, "_PluginManager", _PM)


# --------------------------------------------------------------------------
# 核心判据
# --------------------------------------------------------------------------

def test_healthy_when_running_and_enabled(monkeypatch, tmp_path):
    plugin = _plugin(str(tmp_path))
    _stub_manager(monkeypatch, _HelperInstance(True))

    health = plugin._helper_health()
    assert health["needed"] is True
    assert health["ok"] is True
    assert health["reason"] == ""


def test_absent_helper_is_unhealthy(monkeypatch, tmp_path):
    """助手没装：不健康，且原因里必须点名插件，否则用户不知道去装什么。"""
    plugin = _plugin(str(tmp_path))
    _stub_manager(monkeypatch, None)

    health = plugin._helper_health()
    assert health["needed"] is True
    assert health["ok"] is False
    assert "P115StrmHelper" in health["reason"]


def test_loaded_but_disabled_is_unhealthy(monkeypatch, tmp_path):
    """
    **本次新增的核心判据**：助手已加载但处于停用状态，必须判为不健康。

    停用的插件仍留在 `running_plugins` 里（宿主只在 `enabled` 时启用事件），
    因此"表里有键"不等于"能用"。这里若判成健康，看板就不会挂任何提示，
    而用户面对的是「点了补生成没反应 + 疑似清单持续增长」却毫无线索。

    变异验证：注释掉 `_helper_running` 里的 `get_state()` 判据，本用例必须失败。
    """
    plugin = _plugin(str(tmp_path))
    _stub_manager(monkeypatch, _HelperInstance(False))

    health = plugin._helper_health()
    assert health["needed"] is True
    assert health["ok"] is False, "已加载但停用的助手被误判为健康"
    assert "停用" in health["reason"]
    # 原因必须可执行：只说"停用"不够，要说去哪儿启用
    assert "启用" in health["reason"]


def test_probe_failure_must_not_condemn(monkeypatch, tmp_path):
    """
    助手实例没有 `get_state`（旧宿主、桩环境）时**按可用处理**。

    宁可漏报一次，也不要把可用功能判死 —— 后者会让用户在不该慌的时候慌。
    """
    plugin = _plugin(str(tmp_path))
    _stub_manager(monkeypatch, _NoStateInstance())

    health = plugin._helper_health()
    assert health["ok"] is True, "探测不到状态时不应把功能判死"


def test_get_state_raising_must_not_condemn(monkeypatch, tmp_path):
    """`get_state()` 抛异常同样按可用处理（对方实例形态与预期不同）。"""

    class _Boom:
        def get_state(self):
            raise RuntimeError("boom")

    plugin = _plugin(str(tmp_path))
    _stub_manager(monkeypatch, _Boom())
    assert plugin._helper_health()["ok"] is True


# --------------------------------------------------------------------------
# needed 门槛：没在用 strm 的实例不该被打扰
# --------------------------------------------------------------------------

def test_not_needed_when_strm_disabled(monkeypatch, tmp_path):
    """strm 总开关关闭 → needed=False、ok=True，看板不挂横幅。"""
    plugin = _plugin(str(tmp_path), enabled=False)
    _stub_manager(monkeypatch, None)

    health = plugin._helper_health()
    assert health["needed"] is False
    assert health["ok"] is True
    assert health["reason"] == ""


def test_not_needed_when_no_pair_has_strm_dir(monkeypatch, tmp_path):
    """
    没有映射配 strm 目录 → 不在等 .strm，也就无所谓助手死活。

    这不只是"少一条噪音"：把这类实例也判为不健康，会让**根本没启用该功能**的
    用户每次启动都收到一条与己无关的告警，久了就没人看告警了。
    """
    plugin = _plugin(str(tmp_path), pairs=[{
        "name": "电视剧", "src": os.path.join(str(tmp_path), "src"),
        "dest": "/115/TV", "strm_dir": "", "all_ext": False,
    }])
    _stub_manager(monkeypatch, None)

    health = plugin._helper_health()
    assert health["needed"] is False
    assert health["ok"] is True


def test_whitespace_only_strm_dir_counts_as_unconfigured(monkeypatch, tmp_path):
    """`strm_dir` 只有空白字符 == 没配（与全仓 `.strip()` 口径一致）。"""
    plugin = _plugin(str(tmp_path), pairs=[{
        "name": "电视剧", "src": os.path.join(str(tmp_path), "src"),
        "dest": "/115/TV", "strm_dir": "   ", "all_ext": False,
    }])
    _stub_manager(monkeypatch, None)
    assert plugin._helper_health()["needed"] is False


# --------------------------------------------------------------------------
# 节流与「仅状态变化时留痕」
# --------------------------------------------------------------------------

def test_throttle_skips_second_probe_within_interval(monkeypatch, tmp_path):
    """30 分钟窗口内的重复调用直接返回上次结论，不重复探测。"""
    plugin = _plugin(str(tmp_path))
    plugin._helper_health_state = None
    plugin._helper_health_notified = False
    _stub_manager(monkeypatch, _HelperInstance(True))

    plugin._helper_health_check(force=True)
    first_ts = plugin._helper_health_last

    # 换成一个"不健康"的探测结果；若节流生效，本次不该去读它
    _stub_manager(monkeypatch, None)
    plugin._helper_health_check()
    assert plugin._helper_health_last == first_ts, "节流窗口内仍执行了探测"

    # force 可以穿透节流
    plugin._helper_health_check(force=True)
    assert plugin._helper_health_state["ok"] is False


def test_force_bypasses_throttle(monkeypatch, tmp_path):
    """启动首查用 force —— 它与 30 分钟窗口无关（那时窗口尚未开始）。"""
    plugin = _plugin(str(tmp_path))
    plugin._helper_health_state = None
    plugin._helper_health_last = time.time()      # 刚查过，节流会挡住非 force 调用
    _stub_manager(monkeypatch, _HelperInstance(True))

    plugin._helper_health_check(force=True)
    assert plugin._helper_health_state == {"ok": True, "reason": ""}


def test_state_change_is_tracked_across_probes(monkeypatch, tmp_path):
    """
    状态转移被正确记录：健康 → 不健康 → 健康，三次探测各留下对应状态。

    这正是"仅状态变化时留痕"依赖的基线 —— 没有它，掉线告警要么不出现，
    要么每 30 分钟重复一次。
    """
    plugin = _plugin(str(tmp_path))
    plugin._helper_health_state = None
    plugin._helper_health_notified = False

    _stub_manager(monkeypatch, _HelperInstance(True))
    plugin._helper_health_check(force=True)
    assert plugin._helper_health_state["ok"] is True

    _stub_manager(monkeypatch, None)
    plugin._helper_health_check(force=True)
    assert plugin._helper_health_state["ok"] is False

    _stub_manager(monkeypatch, _HelperInstance(True))
    plugin._helper_health_check(force=True)
    assert plugin._helper_health_state["ok"] is True


def test_disabling_strm_clears_previous_alarm(monkeypatch, tmp_path):
    """
    用户关掉 strm 总开关后，历史告警态必须被清掉，否则横幅会永远挂着 ——
    一个关不掉的状态提示比没有提示更糟（用户会以为自己没关成功）。
    """
    plugin = _plugin(str(tmp_path))
    plugin._helper_health_state = None
    plugin._helper_health_notified = False

    _stub_manager(monkeypatch, None)
    plugin._helper_health_check(force=True)
    assert plugin._helper_health_state["ok"] is False

    plugin._strm_check_enabled = False
    plugin._helper_health_check(force=True)
    assert plugin._helper_health_state["ok"] is True


# --------------------------------------------------------------------------
# 「仅告警、不改行为」——本次改动的核心承诺
# --------------------------------------------------------------------------

def test_health_check_does_not_change_any_behaviour(monkeypatch, tmp_path):
    """
    助手掉线时，健康检查**不得**改动任何功能状态。

    这条是本改动的核心承诺（用户明确选择"仅告警"）。助手没跑 ≠ 没人在生成 .strm：
    本插件的 `strm_dir` 允许接任意 strm 生成插件，因此自动停用会在用户毫不知情的
    情况下关掉整条交叉验证链路。若哪天有人把它改成"不健康就 return / 清空清单"，
    本用例会失败。
    """
    plugin = _plugin(str(tmp_path))
    plugin._strm_watch = {"电视剧:a.mkv": time.time()}
    plugin._strm_suspects = {"电视剧:b.mkv": {"ts": time.time(), "origin": "watch"}}
    plugin._strm_check_enabled = True
    plugin._helper_health_state = None
    plugin._helper_health_notified = False
    _stub_manager(monkeypatch, None)

    before_watch = dict(plugin._strm_watch)
    before_suspects = dict(plugin._strm_suspects)

    plugin._helper_health_check(force=True)

    assert plugin._strm_watch == before_watch, "健康检查改动了观察清单"
    assert plugin._strm_suspects == before_suspects, "健康检查改动了疑似清单"
    assert plugin._strm_check_enabled is True, "健康检查关掉了 strm 总开关"


def test_existing_helper_callers_unaffected_when_healthy(monkeypatch, tmp_path):
    """
    回归护栏：助手健康时，既有的两个调用方行为不变。

    `_helper_running` 加了第二层判据，若写错方向（把正常的判成异常），
    补生成按钮会集体失效 —— 那比本次要修的问题严重得多。
    """
    plugin = _plugin(str(tmp_path), pairs=[{
        "name": "电视剧", "src": os.path.join(str(tmp_path), "src"),
        "dest": "/115/TV", "strm_dir": "/media/strms/TV",
        "pan_dir": "/HomeTheater/TV", "all_ext": False,
    }])
    _stub_manager(monkeypatch, _HelperInstance(True))

    assert plugin._helper_running() == (True, "")
    # pan_dir 已配 → 补生成就绪（走的是同一条 _helper_running）
    assert plugin._strm_helper_ready()["ready"] is True


def test_helper_running_reports_reason_for_absent_helper(monkeypatch, tmp_path):
    """既有行为保持：助手不在时给出含插件名的具体原因（看板横幅依赖它）。"""
    plugin = _plugin(str(tmp_path))
    _stub_manager(monkeypatch, None)

    ok, reason = plugin._helper_running()
    assert ok is False
    assert "P115StrmHelper" in reason


# --------------------------------------------------------------------------
# 启动排程：延迟首查（不能同步查 —— 宿主加载顺序无保证）
# --------------------------------------------------------------------------

def test_startup_check_is_scheduled_with_delay_and_force(monkeypatch, tmp_path):
    """
    启动检查必须**延迟**排程并带 force。

    延迟的理由是宿主按插件逐个 `init_plugin`、**返回之后**才写入运行表 ——
    同步查会读到「助手尚未加载」的假状态并推一条错误告警。
    force 的理由是首查与 30 分钟窗口无关（那时窗口还没开始）。
    """
    calls = []
    monkeypatch.setattr(
        _mod, "_add_plugin_once_job",
        lambda *a, **kw: (calls.append((a, kw)), True)[1])

    plugin = _plugin(str(tmp_path))
    plugin._schedule_startup_helper_check()

    assert len(calls) == 1, "启动检查没有被排程"
    args, kwargs = calls[0]
    assert args[0] == Rsync115Sync.__name__
    assert args[1] == "helper_health_startup"
    assert callable(args[2])
    assert kwargs["delay_seconds"] > 0, "延迟为 0 等于同步检查，会读到假状态"
    assert kwargs["func_kwargs"] == {"force": True}


def test_startup_check_missing_facade_is_silent(monkeypatch, tmp_path):
    """旧宿主没有这个门面时**静默跳过** —— 启动检查是增强，不能让它影响插件加载。"""
    monkeypatch.setattr(_mod, "_add_plugin_once_job", None)
    plugin = _plugin(str(tmp_path))
    plugin._schedule_startup_helper_check()   # 不抛异常即通过


def test_startup_check_scheduler_not_ready_is_silent(monkeypatch, tmp_path):
    """调度器未就绪（返回 False）时不重试、不报错，定期复查会补上。"""
    monkeypatch.setattr(_mod, "_add_plugin_once_job", lambda *a, **kw: False)
    plugin = _plugin(str(tmp_path))
    plugin._schedule_startup_helper_check()


def test_startup_check_raising_is_silent(monkeypatch, tmp_path):
    """排程抛异常也必须被吞掉 —— 它发生在 init_plugin 末尾，绝不能让插件加载失败。"""
    def _boom(*a, **kw):
        raise RuntimeError("scheduler exploded")

    monkeypatch.setattr(_mod, "_add_plugin_once_job", _boom)
    plugin = _plugin(str(tmp_path))
    plugin._schedule_startup_helper_check()


# --------------------------------------------------------------------------
# 掉线通知：一次、且不重复打扰
# --------------------------------------------------------------------------

def test_down_notification_sent_once_per_transition(monkeypatch, tmp_path):
    """
    掉线只推**一条**通知：(a) 每次状态转移一条，(b) 同一状态重复探测不再推。

    `post_message` 不返回投递结果，因此闩锁必须在发送之后置位（与 `_strm_notified`
    同一手法）—— 这里断言的是"不会变成每 30 分钟一封信"。
    """
    sent = []
    plugin = _plugin(str(tmp_path))
    plugin._notify = True
    plugin._helper_health_state = None
    plugin._helper_health_notified = False
    plugin._plugin_mtype = lambda: "plugin"
    plugin.post_message = lambda **kw: sent.append(kw)

    _stub_manager(monkeypatch, None)

    plugin._helper_health_check(force=True)
    assert len(sent) == 1, "首次掉线没有通知"
    assert "strm" in sent[0]["title"]

    # 重复探测（仍不健康）→ 不再推
    plugin._helper_health_check(force=True)
    plugin._helper_health_check(force=True)
    assert len(sent) == 1, "掉线通知重复推送（用户会被静默训练成忽略它）"

    # 恢复 → 再掉线 → 允许再推一条
    _stub_manager(monkeypatch, _HelperInstance(True))
    plugin._helper_health_check(force=True)
    _stub_manager(monkeypatch, None)
    plugin._helper_health_check(force=True)
    assert len(sent) == 2, "恢复后再次掉线应当重新提醒"


def test_no_notification_when_notify_disabled(monkeypatch, tmp_path):
    """通知开关关闭时不推送（与疑似通知共用同一个开关）。"""
    sent = []
    plugin = _plugin(str(tmp_path))
    plugin._notify = False
    plugin._helper_health_state = None
    plugin._helper_health_notified = False
    plugin._plugin_mtype = lambda: "plugin"
    plugin.post_message = lambda **kw: sent.append(kw)

    _stub_manager(monkeypatch, None)
    plugin._helper_health_check(force=True)
    assert sent == []


def test_notification_send_failure_does_not_raise(monkeypatch, tmp_path):
    """发送失败必须被吞掉并**不置位闩锁** —— 否则一次失败会变成永久静默。"""
    plugin = _plugin(str(tmp_path))
    plugin._notify = True
    plugin._helper_health_state = None
    plugin._helper_health_notified = False
    plugin._plugin_mtype = lambda: "plugin"

    def _boom(**kw):
        raise RuntimeError("telegram down")

    plugin.post_message = _boom
    _stub_manager(monkeypatch, None)
    plugin._helper_health_check(force=True)     # 不抛异常即通过
    assert plugin._helper_health_notified is False, "发送失败却置位了闩锁（永久静默）"
