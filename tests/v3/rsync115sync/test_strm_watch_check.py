"""
观察期条目的「立即检查」：手动触发 strm 是否已生成。

Manual "check now" for watching entries.

**为什么需要它**：观察期长达数小时，而用户往往**已经知道** strm 出来了
（刚跑完生成任务、或在文件管理器里看到了）。此前唯一的反馈渠道是等下一轮巡检
（最长 30 分钟），而且是「全量」的 —— 用户想确认这一个，却要等整轮。

**为什么不违反「观察期不放操作按钮」**：当初拒绝的是**破坏性**操作
（删旧重传会诱导用户删掉刚传好的文件、白耗一次删除与重传配额）。
手动检查是纯本地只读，零副作用，与那条结论不冲突。

**为什么必须与巡检共用实现**：两处各写一遍判定，「手动说已生成、巡检仍判观察中」
这类分歧会随着后续改动逐渐出现，且极难排查（两边看着都对）。因此断言锁住
「巡检调用 check_one」这一事实。
"""

import importlib
import inspect
import os
import time


def _plugin(root, *, watch=None, suspects=None):
    """最小实例：只带观察期检查路径用到的状态。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    src = os.path.join(root, "src")
    os.makedirs(src, exist_ok=True)
    with open(os.path.join(src, "a.mkv"), "wb") as fh:
        fh.write(b"x")

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    # dest 用真实临时目录：云端可见性探测要读它，写死 abs 路径会在测试里
    # 撞上真实文件系统（既不可控，也可能没权限）。
    dest = os.path.join(root, "dest")
    os.makedirs(dest, exist_ok=True)
    plugin._sync_pairs = [{
        "name": "电视剧", "src": src, "dest": dest,
        "strm_dir": os.path.join(root, "strm"), "pan_dir": "/HomeTheater/TV",
        "all_ext": False,
    }]
    plugin._exclude_patterns = "@eaDir/"
    plugin._media_extensions = "mkv"
    plugin._ignored_rules = []
    plugin._strm_check_enabled = True
    plugin._strm_grace_minutes = 360
    plugin._strm_last_check = 0.0
    plugin._strm_notified = False
    plugin._strm_gen_requested = {}
    plugin._strm_watch = dict(watch or {})
    plugin._strm_suspects = dict(suspects or {})
    plugin._notify = False
    plugin._is_running = False
    plugin.save_data = lambda k, v: None
    plugin.get_data = lambda k: None
    plugin.post_message = lambda **kw: None
    return plugin


def _make_strm(plugin, rel="a.mkv"):
    """.strm 端生成对应文件（模拟 strm 插件跑完了）。"""
    strm_path = plugin._strm_expected_path(f"电视剧:{rel}")
    os.makedirs(os.path.dirname(strm_path), exist_ok=True)
    with open(strm_path, "wb") as fh:
        fh.write(b"http://x")


KEY = "电视剧:a.mkv"


# --------------------------------------------------------------------------
# 三种结局
# --------------------------------------------------------------------------

def test_check_settles_when_strm_now_exists(tmp_path):
    """strm 已生成 → 立即解除观察（用户最常用的场景：刚跑完生成任务）。"""
    plugin = _plugin(str(tmp_path), watch={KEY: time.time()})
    _make_strm(plugin)

    res = plugin._api_strm_check({"keys": [KEY]})

    assert res["success"] is True
    assert KEY not in plugin._strm_watch, "已生成就不该继续挂在观察期"
    assert res["data"]["settled"] == [KEY]
    assert "已生成" in res["message"]


def test_check_keeps_watching_when_still_absent_within_grace(tmp_path):
    """宽限期内仍未生成 → 继续等待，**不得**转成疑似（否则手点一下就误报）。"""
    plugin = _plugin(str(tmp_path), watch={KEY: time.time()})

    res = plugin._api_strm_check({"keys": [KEY]})

    assert KEY in plugin._strm_watch, "宽限期内必须留在观察期"
    assert KEY not in plugin._strm_suspects, "宽限期内不得转疑似"
    assert res["data"]["still_watching"] == [KEY]
    assert "仍未生成" in res["message"]


def test_check_moves_to_suspects_when_grace_expired(tmp_path):
    """宽限期已过且仍无 strm → 转入疑似清单（与巡检同一处置）。"""
    plugin = _plugin(str(tmp_path), watch={KEY: time.time() - 7 * 3600})

    res = plugin._api_strm_check({"keys": [KEY]})

    assert KEY not in plugin._strm_watch
    assert KEY in plugin._strm_suspects, "到期未生成应转疑似"
    assert res["data"]["suspects"] == [KEY]


def test_check_removes_entry_when_source_gone(tmp_path):
    """源端文件已消失 → 移出观察（无从验证也无从重传）。"""
    plugin = _plugin(str(tmp_path), watch={KEY: time.time()})
    os.remove(os.path.join(str(tmp_path), "src", "a.mkv"))

    res = plugin._api_strm_check({"keys": [KEY]})

    assert KEY not in plugin._strm_watch
    assert res["data"]["removed"] == [KEY]


# --------------------------------------------------------------------------
# 输入校验
# --------------------------------------------------------------------------

def test_check_rejects_keys_not_in_watch_list(tmp_path):
    """只接受观察期内的 key —— 与其它入口同口径，不越权触碰任意路径。"""
    plugin = _plugin(str(tmp_path), watch={})
    res = plugin._api_strm_check({"keys": ["电视剧:随便/造的.mkv"]})
    assert res["success"] is False


def test_check_with_no_keys_is_rejected(tmp_path):
    plugin = _plugin(str(tmp_path), watch={KEY: time.time()})
    assert plugin._api_strm_check({"keys": []})["success"] is False


def test_check_only_touches_requested_keys(tmp_path):
    """勾了一条就只查那一条，不能顺手把别的条目也判了。"""
    other = "电视剧:other.mkv"
    plugin = _plugin(str(tmp_path), watch={KEY: time.time(), other: time.time()})

    res = plugin._api_strm_check({"keys": [KEY]})

    assert res["data"]["still_watching"] == [KEY]
    assert other in plugin._strm_watch, "未请求的条目必须原样保留"
    assert other not in plugin._strm_suspects


# --------------------------------------------------------------------------
# 与巡检共用实现（防止两套判定漂移）
# --------------------------------------------------------------------------

def test_sweep_delegates_to_shared_check_one():
    """
    巡检必须调用 check_one，而不是自己再算一遍。

    这是本条功能里最容易悄悄腐化的地方：复制一份判定逻辑当时能跑通，
    之后任何一侧改动都会造成「手动检查说已生成、巡检仍判观察中」，
    而两边单独看都正确，排查成本极高。用源码断言把「共用」这件事钉住。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    src = inspect.getsource(module.Rsync115Sync._strm_check)
    assert "check_one(" in src, "巡检必须复用 check_one"
    # 只检查**调用**，不检查提及：docstring 里说明判定委托给 strm.py 时会
    # 提到 classify_watch，那是文档而非实现，不该触发失败。
    calls = [ln.strip() for ln in src.splitlines()
             if "classify_watch(" in ln and not ln.strip().startswith("#")]
    assert not calls, (
        f"巡检不应自己调用 classify_watch（那是 check_one 的职责，"
        f"重复调用意味着判定逻辑被复制了一份）: {calls}"
    )


def test_check_one_does_not_touch_persistence():
    """
    check_one 只做探测与判定，不写盘、不发通知。

    调用方各自负责持久化（巡检批量提交，手动检查即时提交）。若 check_one 内
    自己 save_data，巡检就会退化成「每个条目写一次盘」，批量场景下反复 IO。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    src = inspect.getsource(module.Rsync115Sync.check_one)
    assert "save_data" not in src
    assert "post_message" not in src


# --------------------------------------------------------------------------
# 窗口内检查：顺手探一次云端可见性（回答「等下去会怎样」）
# --------------------------------------------------------------------------

def test_check_within_window_probes_cloud_visibility(tmp_path):
    """
    窗口内检查虽不改状态，但必须**顺手探一次云端可见性**。

    用户点「检查 strm」时真正的疑问往往不是「还要等多久」，而是「等下去会怎样」。
    探一次就能回答：云端有文件 ⇒ 问题在生成侧，窗口过了也别急着删；
    云端看不到 ⇒ 窗口过了直接删旧重传即可。
    """
    plugin = _plugin(str(tmp_path), watch={KEY: time.time()})
    # dest 端刻意留空 → 云端不可见
    res = plugin._api_strm_check({"keys": [KEY]})

    assert res["success"] is True
    assert KEY in plugin._strm_watch, "窗口内不应解除观察"
    assert "云端" in res["message"], "应给出云端可见性的结论"
    assert "删旧重传" in res["message"], "并说明该结论对后续操作意味着什么"


def test_check_within_window_says_do_not_delete_when_cloud_copy_intact(tmp_path):
    """
    云端可见且大小一致时，窗口内的回答必须是「别急着删」。

    这是探测唯一被允许的用法方向：它的假阳性是「把坏文件看成好的」，
    因此只能用来劝用户**先别动手**，不能反过来说「文件是好的、可以放心」。
    """
    plugin = _plugin(str(tmp_path), watch={KEY: time.time()})
    pair = plugin._sync_pairs[0]
    with open(os.path.join(pair["src"], "a.mkv"), "wb") as fh:
        fh.write(b"x" * 100)
    dest_file = os.path.join(pair["dest"], "a.mkv")
    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
    with open(dest_file, "wb") as fh:
        fh.write(b"x" * 100)

    res = plugin._api_strm_check({"keys": [KEY]})

    assert KEY in plugin._strm_watch
    assert "大小" in res["message"] and "别急" in res["message"]


def test_check_notifies_when_entry_becomes_suspect(tmp_path):
    """
    ⚠️ 手动检查转疑似时**必须发通知**，与自动巡检同口径。

    不补这一步的话，用户主动检查反而比什么都不做更安静：条目已进疑似清单，
    而 `_reset_strm_notified_if_clear()` 会因「清单刚由空转非空」把闩锁重置，
    等下一轮巡检再判时已经没有条目可判了 —— 等于「谁先发现」决定了要不要通知。
    """
    notified = []
    plugin = _plugin(str(tmp_path), watch={KEY: 0.0})   # 早已过了窗口
    plugin._strm_last_check = 0.0
    plugin._strm_check_enabled = True
    plugin._strm_expected_path = lambda k: "/nonexistent/never.strm"
    plugin._is_ignored = lambda k: False
    plugin._reset_strm_notified_if_clear = lambda: None
    plugin._notify_strm_suspects = lambda keys: notified.append(list(keys))
    import app.plugins.rsync115sync.strm as strm_mod
    import pytest as _pytest
    _pytest.MonkeyPatch().setattr(strm_mod, "source_root_of", lambda k, p: "")

    res = plugin._api_strm_check({"keys": [KEY]})

    assert KEY in plugin._strm_suspects
    assert notified and KEY in notified[0], "手动检查转疑似也必须走通知"
