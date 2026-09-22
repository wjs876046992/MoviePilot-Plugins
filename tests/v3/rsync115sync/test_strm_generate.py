"""
借道 strm 助手补生成：插件层行为的单测。

Plugin-level behaviour of the "ask the helper to regenerate" path.

**为什么先补生成再删旧重传**：疑似清单的两种成因（助手漏生成 / CD2 假成功）
在本地视角完全无法区分，但处理成本差几个数量级 —— 前者重新生成指针即可，
后者要删掉云端文件再完整重传。花一次助手侧遍历换取「大概率免掉整轮重传」
是划算的；而且它顺带给出判别结果。

**为什么上限命中要整批拒绝**：助手对**每个参数**都会遍历整个云端子树。达到
上限说明疑似条目已散布到很多目录，逐目录触发的总开销可能已超过一次整库遍历，
此时应当由用户明确决策，而不是插件自动放大对 115 的访问量。

**为什么只接受疑似清单内的 key**：与 /strm_retry 同一道越权护栏 ——
否则调用方可以构造任意路径让助手去遍历云端目录。
"""

import importlib
import os
import tempfile
import time


def _plugin(root, *, conf=None):
    """构造最小实例：只带补生成路径真正用到的状态与宿主能力。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    src = os.path.join(root, "src")
    os.makedirs(src, exist_ok=True)

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{
        "name": "电视剧", "src": src, "dest": "/115/TV",
        "strm_dir": "/media/strms/TV", "pan_dir": "/HomeTheater/TV", "all_ext": False,
    }]
    plugin._strm_suspects = dict(conf or {})
    plugin._strm_watch = {}
    plugin._strm_gen_requested = {}
    plugin._strm_grace_hours = 6.0
    plugin._strm_notified = False
    plugin._ignored_rules = []
    plugin.save_data = lambda k, v: None
    return plugin


def _stub_helper(monkeypatch, module, *, running=True):
    """把助手的运行态注入被测代码（不打桩业务逻辑本身）。"""

    class _PM:
        def __init__(self):
            self.running_plugins = {"P115StrmHelper": object()} if running else {}

    monkeypatch.setattr(module, "_PluginManager", _PM)


def _sent(monkeypatch, module):
    """收集本插件发出的命令（走真实 eventmanager，宿主是桩）。"""
    from app.core.event import eventmanager
    eventmanager.sent = []
    return eventmanager.sent


# --------------------------------------------------------------------------
# 就绪检查（看板据此决定按钮可用性并解释原因）
# --------------------------------------------------------------------------

def test_helper_ready_when_configured(monkeypatch, tmp_path):
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = _plugin(str(tmp_path))
    _stub_helper(monkeypatch, module)

    assert plugin._strm_helper_ready()["ready"] is True


def test_helper_not_ready_when_plugin_absent(monkeypatch, tmp_path):
    """助手没装时必须给出**具体**原因，而不是让按钮静默失效。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = _plugin(str(tmp_path))
    _stub_helper(monkeypatch, module, running=False)

    ready = plugin._strm_helper_ready()
    assert ready["ready"] is False
    assert "P115StrmHelper" in ready["reason"]


# --------------------------------------------------------------------------
# 越权护栏
# --------------------------------------------------------------------------

def test_rejects_keys_outside_suspect_list(monkeypatch, tmp_path):
    """不在疑似清单里的 key 一律拒绝 —— 防止构造任意路径让助手去遍历云端目录。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = _plugin(str(tmp_path))
    _stub_helper(monkeypatch, module)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": ["电视剧:随便/造的/路径.mkv"]})

    assert res["success"] is False
    assert sent == [], "越权请求绝不能真的发出命令"


def test_rejects_empty_keys(monkeypatch, tmp_path):
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = _plugin(str(tmp_path))
    _stub_helper(monkeypatch, module)
    assert plugin._api_strm_generate({"keys": []})["success"] is False


def test_rejects_when_helper_not_running(monkeypatch, tmp_path):
    """助手没在运行时不发命令 —— 装了但没登录的助手会收下命令然后什么都不做。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    key = "电视剧:a.mkv"
    plugin = _plugin(str(tmp_path), conf={key: {"ts": time.time(), "origin": "scan"}})
    _stub_helper(monkeypatch, module, running=False)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": [key]})

    assert res["success"] is False
    assert sent == []
    assert key in plugin._strm_suspects


# --------------------------------------------------------------------------
# 正常路径：命令发出 + 条目回到观察期
# --------------------------------------------------------------------------

def test_requests_helper_and_moves_entries_back_to_watch(monkeypatch, tmp_path):
    """
    核心行为：向助手发出目录参数，并把条目从疑似移回「待观察」重新计时。

    重新计时是为了复用既有巡检状态机（strm 出现 ⇒ 自动解除；宽限期到仍无 ⇒
    回到疑似且判定更硬），不需要为异步的助手再加一条轮询路径。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    key = "电视剧:日番/黄泉的使者/Season 01/E03.mkv"
    plugin = _plugin(str(tmp_path), conf={key: {"ts": time.time(), "origin": "scan"}})
    _stub_helper(monkeypatch, module)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": [key]})

    assert res["success"] is True
    assert len(sent) == 1
    etype, data = sent[0]
    assert data["cmd"] == "/p115_strm /HomeTheater/TV/日番/黄泉的使者/Season 01"
    assert key not in plugin._strm_suspects, "应移出疑似清单"
    assert key in plugin._strm_watch, "应回到观察期"
    assert key in plugin._strm_gen_requested, "应留下「已请求生成」标记"


def test_same_directory_files_share_one_command(monkeypatch, tmp_path):
    """同目录的多个文件只发一条命令 —— 助手会遍历整个目录，发多条纯属重复开销。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    keys = [f"电视剧:剧A/Season 01/E0{i}.mkv" for i in range(1, 4)]
    plugin = _plugin(str(tmp_path), conf={k: {"ts": time.time(), "origin": "scan"} for k in keys})
    _stub_helper(monkeypatch, module)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": keys})

    assert res["success"] is True
    assert len(sent) == 1, "三个同目录文件应合并为一条命令"
    assert res["data"]["requested"] == 3
    assert len(plugin._strm_watch) == 3


# --------------------------------------------------------------------------
# 上限保护：整批拒绝
# --------------------------------------------------------------------------

def test_over_directory_limit_rejects_whole_batch(monkeypatch, tmp_path):
    """
    目录数超限时**整批拒绝**（不发任何命令），而不是处理前 N 个。

    静默截断会让用户以为整批都处理过了，于是不再关注剩下的条目 —— 这比直接
    拒绝更糟。而且达到这个量级时逐目录触发已不划算，该由用户明确决策。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    from app.plugins.rsync115sync.constants import STRM_GEN_DIR_LIMIT

    keys = [f"电视剧:剧{i}/Season 01/E01.mkv" for i in range(STRM_GEN_DIR_LIMIT + 5)]
    plugin = _plugin(str(tmp_path), conf={k: {"ts": time.time(), "origin": "scan"} for k in keys})
    _stub_helper(monkeypatch, module)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": keys})

    assert res["success"] is False
    assert sent == [], "整批拒绝时不得发出任何命令"
    assert "上限" in res["message"]
    # 清单**不动**：条目仍留在疑似里，用户缩小范围后可以重新发起
    assert len(plugin._strm_suspects) == len(keys)
    assert plugin._strm_watch == {}


def test_limit_not_hit_still_processes(monkeypatch, tmp_path):
    """未达上限时正常执行（防止把「≥上限」误写成「>0」这类边界错误）。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    from app.plugins.rsync115sync.constants import STRM_GEN_DIR_LIMIT

    keys = [f"电视剧:剧{i}/Season 01/E01.mkv" for i in range(STRM_GEN_DIR_LIMIT)]
    plugin = _plugin(str(tmp_path), conf={k: {"ts": time.time(), "origin": "scan"} for k in keys})
    _stub_helper(monkeypatch, module)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": keys})

    assert res["success"] is True
    assert len(sent) == STRM_GEN_DIR_LIMIT


# --------------------------------------------------------------------------
# 无法反查网盘路径
# --------------------------------------------------------------------------

def test_unmapped_keys_are_reported_not_silently_dropped(monkeypatch, tmp_path):
    """未配网盘目录的映射必须**明确告知**，且不能移出疑似清单。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    key = "电视剧:a.mkv"
    plugin = _plugin(str(tmp_path), conf={key: {"ts": time.time(), "origin": "scan"}})
    plugin._sync_pairs[0]["pan_dir"] = ""
    _stub_helper(monkeypatch, module)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": [key]})

    assert res["success"] is False
    assert sent == []
    assert key in plugin._strm_suspects, "无法处理时条目必须留在清单里"


def test_missing_pan_dir_never_falls_back_to_derivation(monkeypatch, tmp_path):
    """
    未配网盘目录时**绝不**用本地 strm_dir 凑一个路径出来。

    凑出来的路径大概率不在助手允许的列表里，发过去会被静默拒绝（助手只回一条
    「路径匹配错误」的用户消息，本插件看不到）。宁可明确拒绝，也不要制造
    「看起来做了、实际什么都没发生」的假象。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    key = "电视剧:日番/A/Season 01/E01.mkv"
    plugin = _plugin(str(tmp_path), conf={key: {"ts": time.time(), "origin": "scan"}})
    plugin._sync_pairs[0]["pan_dir"] = ""
    plugin._sync_pairs[0]["strm_dir"] = "/media/strms/TV"
    _stub_helper(monkeypatch, module)
    sent = _sent(monkeypatch, module)

    plugin._api_strm_generate({"keys": [key]})

    assert sent == [], "不得用本地路径推导出网盘路径"


# --------------------------------------------------------------------------
# 标记的持久化与清理
# --------------------------------------------------------------------------

def test_gen_requested_cleared_when_suspect_is_cleared(monkeypatch, tmp_path):
    """
    「清空清单」必须同时清掉补生成标记。

    否则下次扫描出的同一条目会被误标成「补生成过仍失败」—— 而实际上根本没请求过。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    key = "电视剧:a.mkv"
    plugin = _plugin(str(tmp_path), conf={key: {"ts": time.time(), "origin": "scan"}})
    plugin._strm_gen_requested = {key: time.time()}
    plugin._reset_strm_notified_if_clear = lambda: None

    plugin._api_strm_clear()

    assert plugin._strm_gen_requested == {}


def test_gen_marker_survives_when_entry_returns_as_suspect(monkeypatch, tmp_path):
    """
    补生成后仍无 strm → 条目回到疑似清单时，标记必须**保留**。

    用户需要据此看出「这已经是补生成之后的结果」（判定比首次疑似硬得多），
    而不是又来了一条普通疑似。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    import app.plugins.rsync115sync.strm as strm_mod

    key = "电视剧:a.mkv"
    plugin = _plugin(str(tmp_path), conf={key: {"ts": time.time(), "origin": "scan"}})
    plugin._strm_watch = {key: 0.0}
    plugin._strm_last_check = 0.0
    plugin._strm_check_enabled = True
    plugin._strm_expected_path = lambda k: "/nonexistent/never.strm"
    plugin._is_ignored = lambda k: False
    plugin._notify_strm_suspects = lambda *a, **kw: None
    plugin._reset_strm_notified_if_clear = lambda: None
    plugin._strm_gen_requested = {key: time.time()}
    # 让巡检认为已过宽限期，且源端仍在 → 应判为疑似
    monkeypatch.setattr(strm_mod, "source_root_of", lambda k, p: "")

    plugin._strm_check()

    assert key in plugin._strm_suspects
    assert key in plugin._strm_gen_requested, "补生成标记必须保留，供看板区分判定强度"


def test_gen_marker_removed_when_watch_settles(monkeypatch, tmp_path):
    """strm 最终生成（正常解除）时，补生成标记随之清理，避免无限增长。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    import app.plugins.rsync115sync.strm as strm_mod

    key = "电视剧:a.mkv"
    plugin = _plugin(str(tmp_path))
    plugin._strm_watch = {key: time.time()}
    plugin._strm_last_check = 0.0
    plugin._strm_check_enabled = True
    # strm 已存在 → SETTLED
    plugin._strm_expected_path = lambda k: __file__
    plugin._is_ignored = lambda k: False
    plugin._notify_strm_suspects = lambda *a, **kw: None
    plugin._strm_gen_requested = {key: time.time()}
    monkeypatch.setattr(strm_mod, "source_root_of", lambda k, p: "")

    plugin._strm_check()

    assert key not in plugin._strm_watch, "strm 已生成 → 应解除观察"
    assert key not in plugin._strm_gen_requested, "解除后标记应清理"
