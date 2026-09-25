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
    plugin._strm_grace_minutes = 360
    plugin._strm_check_enabled = True
    plugin._strm_last_check = 0.0        # 巡检节流：0 = 从未巡检过，不会被跳过
    plugin._strm_notified = False
    plugin._ignored_rules = []
    plugin._exclude_patterns = ""
    plugin._notify = False
    plugin._strm_video_exts = lambda: {"mkv", "mp4"}
    plugin.save_data = lambda k, v: None
    return plugin


def _stub_helper(monkeypatch, module, *, running=True, helper_cfg=True):
    """
    注入助手的运行态与（可选的）「全量同步路径」配置。

    预检要读助手配置，因此这里必须能模拟「助手在跑但路径不在它列表里」这种情况 ——
    那正是用户实测踩到的坑（9KG 不在助手的 full_sync_strm_paths 里）。
    """

    class _PM:
        def __init__(self):
            self.running_plugins = {"P115StrmHelper": object()} if running else {}

    monkeypatch.setattr(module, "_PluginManager", _PM)

    class _SC:
        def get(self, key):
            if not helper_cfg:
                return {}
            return {"full_sync_strm_paths":
                    "/media/strms/Movies#/HomeTheater/Movies#1\n"
                    "/media/strms/TV#/HomeTheater/TV#1"}

    return _SC()


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
    plugin.systemconfig = _stub_helper(monkeypatch, module)

    assert plugin._strm_helper_ready()["ready"] is True


def test_helper_not_ready_when_plugin_absent(monkeypatch, tmp_path):
    """助手没装时必须给出**具体**原因，而不是让按钮静默失效。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = _plugin(str(tmp_path))
    plugin.systemconfig = _stub_helper(monkeypatch, module, running=False)

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
    plugin.systemconfig = _stub_helper(monkeypatch, module)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": ["电视剧:随便/造的/路径.mkv"]})

    assert res["success"] is False
    assert sent == [], "越权请求绝不能真的发出命令"


def test_rejects_empty_keys(monkeypatch, tmp_path):
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = _plugin(str(tmp_path))
    plugin.systemconfig = _stub_helper(monkeypatch, module)
    assert plugin._api_strm_generate({"keys": []})["success"] is False


def test_preflight_rejects_path_not_in_helper_full_sync(monkeypatch, tmp_path):
    """
    用户实测踩到的坑：网盘目录不在助手的「全量同步路径」里。

    助手会回「匹配目录失败，请检查输入路径和插件配置！」，但**这条提示只发给
    助手侧用户，本插件收不到** —— 不预检的话，用户看到的是「点了按钮，
    条目还在，然后什么都没发生」，完全无从判断。

    这里必须**在发送前拦下**，并把助手当前配置的目录列出来供对照。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    key = "9KG:未知演员/FC2-2132144/FC2-2132144-C.mp4"
    plugin = _plugin(str(tmp_path), conf={key: {"ts": time.time(), "origin": "scan"}})
    plugin._sync_pairs[0] = {"name": "9KG", "src": os.path.join(str(tmp_path), "src"),
                            "dest": "/115/9KG", "strm_dir": "/media/strms/9KG",
                            "pan_dir": "/HomeTheater/9KG", "all_ext": True}
    # 助手配置里只有 Movies / TV，没有 9KG
    plugin.systemconfig = _stub_helper(monkeypatch, module)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": [key]})

    assert res["success"] is False
    assert sent == [], "注定被拒绝的命令不得发出"
    assert "/HomeTheater/9KG" in res["message"], "要指出是哪个路径不被接受"
    assert "/HomeTheater/TV" in res["message"], "要把助手当前配置列出来供对照"
    assert key in plugin._strm_suspects, "失败时条目必须留在疑似清单"


def test_preflight_degrades_when_helper_config_unreadable(monkeypatch, tmp_path):
    """
    读不到助手配置时**不阻塞**（退回旧行为），而不是把功能判死。

    理由：预检读的是对方配置的字段名，属实现细节。对方改个字段名就让本功能
    完全不可用，比「照发、可能失败」更糟 —— 后者至少还有成功的机会。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    key = "电视剧:日番/A/Season 01/E01.mkv"
    plugin = _plugin(str(tmp_path), conf={key: {"ts": time.time(), "origin": "scan"}})
    plugin.systemconfig = _stub_helper(monkeypatch, module, helper_cfg=False)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": [key]})

    assert res["success"] is True, "读不到助手配置时不应阻塞"
    assert len(sent) == 1


def test_rejects_when_helper_not_running(monkeypatch, tmp_path):
    """助手没在运行时不发命令 —— 装了但没登录的助手会收下命令然后什么都不做。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    key = "电视剧:a.mkv"
    plugin = _plugin(str(tmp_path), conf={key: {"ts": time.time(), "origin": "scan"}})
    plugin.systemconfig = _stub_helper(monkeypatch, module, running=False)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": [key]})

    assert res["success"] is False
    assert sent == []
    assert key in plugin._strm_suspects


# --------------------------------------------------------------------------
# 正常路径：命令发出 + 条目移回观察期（命令**发出之后**才移）
# --------------------------------------------------------------------------

def test_requests_helper_and_moves_entry_back_to_watch(monkeypatch, tmp_path):
    """
    核心行为：向助手发出目录参数，条目从疑似清单**移回观察期**并按请求时刻计时。

    移回观察期是有意的：用户要的正是「等一会儿再点一下检查」，而观察期本身就
    带着巡检 + 手动检查两套现成的判定机制。留在疑似清单里只能靠手动刷新去猜。

    ⚠️ 但移回的**时机**是命令确实发出之后，不是收到请求时 —— 早先的实现顺序
    写反，助手拒收（路径不在它的全量列表里）时条目照样消失，用户看到
    「点了一下，东西不见了」，宽限期到它又带着「补生成无效」回来。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    key = "电视剧:日番/黄泉的使者/Season 01/E03.mkv"
    plugin = _plugin(str(tmp_path), conf={key: {"ts": time.time(), "origin": "scan"}})
    plugin.systemconfig = _stub_helper(monkeypatch, module)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": [key]})

    assert res["success"] is True
    assert len(sent) == 1
    etype, data = sent[0]
    assert data["cmd"] == "/p115_strm /HomeTheater/TV/日番/黄泉的使者/Season 01"
    assert key in plugin._strm_gen_requested, "应留下「已请求生成」标记"
    assert key in plugin._strm_watch, "命令确实发出后，条目应移回观察期（便于手动检查）"
    assert key not in plugin._strm_suspects, "移回观察期后不应再留在疑似清单"


def test_rearm_clock_is_the_request_time_not_the_sync_time(monkeypatch, tmp_path):
    """
    重新计时以**请求时刻**为基准，不是沿用疑似条目里那个旧时间戳。

    若沿用旧时间戳（往往是几小时甚至几天前的首次疑似时间），重新计时窗口一
    开始就已经过期 —— 下一轮巡检会立刻把它打回疑似，用户看到的是「点了按钮，
    条目在疑似和观察之间闪一下又回来了」。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    key = "电视剧:a.mkv"
    old_ts = time.time() - 86400 * 3  # 三天前首次疑似
    plugin = _plugin(str(tmp_path), conf={key: {"ts": old_ts, "origin": "scan"}})
    plugin.systemconfig = _stub_helper(monkeypatch, module)
    _sent(monkeypatch, module)

    before = time.time()
    plugin._api_strm_generate({"keys": [key]})

    assert plugin._strm_watch[key] >= before, "观察计时必须从请求时刻重新开始"


def test_same_directory_files_share_one_command(monkeypatch, tmp_path):
    """同目录的多个文件只发一条命令 —— 助手会遍历整个目录，发多条纯属重复开销。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    keys = [f"电视剧:剧A/Season 01/E0{i}.mkv" for i in range(1, 4)]
    plugin = _plugin(str(tmp_path), conf={k: {"ts": time.time(), "origin": "scan"} for k in keys})
    plugin.systemconfig = _stub_helper(monkeypatch, module)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": keys})

    assert res["success"] is True
    assert len(sent) == 1, "三个同目录文件应合并为一条命令"
    assert res["data"]["requested"] == 3
    assert all(k in plugin._strm_watch for k in keys), "条目都应移回观察期"
    assert plugin._strm_suspects == {}


def test_entry_stays_when_command_send_fails(monkeypatch, tmp_path):
    """
    命令**发送失败**时条目不得离开疑似清单。

    这是「移动时机」的直接后果：发送循环返回失败，却仍按原计划移动条目，
    用户会在观察窗口里等一个永远不会到来的结果，而且清单上看不到它了。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    key = "电视剧:a.mkv"
    plugin = _plugin(str(tmp_path), conf={key: {"ts": time.time(), "origin": "scan"}})
    plugin.systemconfig = _stub_helper(monkeypatch, module)
    plugin._send_helper_command = lambda d: False

    res = plugin._api_strm_generate({"keys": [key]})

    assert res["success"] is False
    assert key in plugin._strm_suspects, "没发出去的命令不得让条目离场"
    assert plugin._strm_watch == {}, "不得进入观察期"
    assert plugin._strm_gen_requested == {}, "也不该留下「已请求」标记"


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
    plugin.systemconfig = _stub_helper(monkeypatch, module)
    sent = _sent(monkeypatch, module)

    res = plugin._api_strm_generate({"keys": keys})

    assert res["success"] is False
    assert sent == [], "整批拒绝时不得发出任何命令"
    assert "上限" in res["message"]
    # 清单**不动**：条目仍留在疑似里，用户缩小范围后可以重新发起
    assert len(plugin._strm_suspects) == len(keys)
    assert plugin._strm_watch == {}
    assert plugin._strm_gen_requested == {}


def test_limit_not_hit_still_processes(monkeypatch, tmp_path):
    """未达上限时正常执行（防止把「≥上限」误写成「>0」这类边界错误）。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    from app.plugins.rsync115sync.constants import STRM_GEN_DIR_LIMIT

    keys = [f"电视剧:剧{i}/Season 01/E01.mkv" for i in range(STRM_GEN_DIR_LIMIT)]
    plugin = _plugin(str(tmp_path), conf={k: {"ts": time.time(), "origin": "scan"} for k in keys})
    plugin.systemconfig = _stub_helper(monkeypatch, module)
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
    plugin.systemconfig = _stub_helper(monkeypatch, module)
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
    plugin.systemconfig = _stub_helper(monkeypatch, module)
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
    而不是又来了一条普通疑似 —— 后者会被当成又一次刮削延迟，用户不会去
    助手侧查「到底有没有生成」。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    import app.plugins.rsync115sync.strm as strm_mod

    key = "电视剧:a.mkv"
    plugin = _plugin(str(tmp_path), conf={key: {"ts": time.time(), "origin": "scan"}})
    plugin._strm_watch = {key: 0.0}
    plugin._strm_expected_path = lambda k: "/nonexistent/never.strm"
    plugin._is_ignored = lambda k: False
    plugin._notify_strm_suspects = lambda *a, **kw: None
    plugin._reset_strm_notified_if_clear = lambda: None
    # 补生成窗口（1h）早已走完 → 应判为疑似
    plugin._strm_gen_requested = {key: time.time() - 7200}
    monkeypatch.setattr(strm_mod, "source_root_of", lambda k, p: "")

    plugin._strm_check()

    assert key in plugin._strm_suspects
    assert key in plugin._strm_gen_requested, "补生成标记必须保留，供看板区分判定强度"


def test_gen_clock_uses_fixed_window_not_configured_grace(monkeypatch, tmp_path):
    """
    补生成后的等待窗口用固定值，**不跟随宽限期配置**。

    两者度量的是不同的延迟：宽限期是「rsync 报成功 → strm 出现」的刮削/入库
    传播延迟；补生成等的是助手的一次云端目录遍历。用户把宽限期调到 24h
    （理由是刮削慢）不该连带让补生成的结果在半天内无法判定 —— 那会让
    「已生成」的即时反馈也一起消失。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    import app.plugins.rsync115sync.strm as strm_mod
    from app.plugins.rsync115sync import strm as pure

    key = "电视剧:a.mkv"
    plugin = _plugin(str(tmp_path))
    plugin._strm_grace_minutes = 1440                       # 宽限期故意调得很大
    grace_secs = pure.grace_secs_of(plugin._strm_grace_minutes)
    plugin._strm_watch = {key: time.time() - 7200}         # 两小时前请求的补生成
    plugin._strm_gen_requested = {key: time.time() - 7200}
    plugin._strm_expected_path = lambda k: "/nonexistent/never.strm"
    monkeypatch.setattr(strm_mod, "source_root_of", lambda k, p: "")

    state, _ = plugin.check_one(key, time.time(), grace_secs)

    assert state == pure.SUSPECT, (
        f"{pure.REGRACE_HOURS:g}h 窗口应已到期（宽限期 1440 分钟不参与补生成的判定）")


def test_scan_does_not_demote_watching_entries(monkeypatch, tmp_path):
    """
    主动扫描**不得**把观察期条目降级成疑似。

    这条是补生成功能带来的必要闸门：请求补生成后条目被移回观察期，而它此刻的
    .strm 按定义还不存在 —— 任何一次扫描都会立刻把它打回疑似，用户点完按钮
    看到的仍是同一批条目，功能表现为完全没作用。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    import app.plugins.rsync115sync.strm as strm_mod

    key = "电视剧:a.mkv"
    plugin = _plugin(str(tmp_path))
    plugin._strm_watch = {key: time.time()}
    plugin._notify_strm_suspects = lambda *a, **kw: None
    # 扫描认为源端有这个文件、而 strm 不存在 → 本会产生疑似
    monkeypatch.setattr(strm_mod, "scan_candidates",
                        lambda *a, **kw: ([key], False, 1))

    plugin._strm_scan()

    assert key not in plugin._strm_suspects, "观察期条目不得被扫描降级为疑似"
    assert key in plugin._strm_watch, "仍应留在观察期"


def test_gen_marker_removed_when_watch_settles(monkeypatch, tmp_path):
    """strm 最终生成（正常解除）时，补生成标记随之清理，避免无限增长。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    import app.plugins.rsync115sync.strm as strm_mod

    key = "电视剧:a.mkv"
    plugin = _plugin(str(tmp_path))
    plugin._strm_watch = {key: time.time()}
    # strm 已存在 → SETTLED
    plugin._strm_expected_path = lambda k: __file__
    plugin._is_ignored = lambda k: False
    plugin._notify_strm_suspects = lambda *a, **kw: None
    plugin._strm_gen_requested = {key: time.time()}
    monkeypatch.setattr(strm_mod, "source_root_of", lambda k, p: "")

    plugin._strm_check()

    assert key not in plugin._strm_watch, "strm 已生成 → 应解除观察"
    assert key not in plugin._strm_gen_requested, "解除后标记应清理"


def test_only_files_whose_directory_was_actually_sent_are_rearmed(monkeypatch, tmp_path):
    """
    逐目录发送时**部分失败**：只有真正发出去的目录下的文件才移回观察期。

    若按「本次涉及的全部目录」收尾，发送失败那条命令下的文件也会被移进观察期
    —— 而命令从未发出，用户在窗口里等的是一个永远不会到来的结果，同时它在
    疑似清单上也不见了。这是「把请求当成执行」的另一种形态。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    ok_key = "电视剧:剧A/Season 01/E01.mkv"
    bad_key = "电视剧:剧B/Season 01/E01.mkv"
    plugin = _plugin(str(tmp_path), conf={
        ok_key: {"ts": time.time(), "origin": "scan"},
        bad_key: {"ts": time.time(), "origin": "scan"},
    })
    plugin.systemconfig = _stub_helper(monkeypatch, module)
    sent = _sent(monkeypatch, module)
    # 只让「剧A」那条命令成功
    plugin._send_helper_command = lambda d: "剧A" in d

    res = plugin._api_strm_generate({"keys": [ok_key, bad_key]})

    assert res["success"] is True
    assert len(sent) == 0, "本用例已替换发送函数，事件总线不应再被调用"
    assert ok_key in plugin._strm_watch, "命令成功发出的目录，其文件应移回观察期"
    assert bad_key in plugin._strm_suspects, "命令未发出的目录，其文件必须留在疑似清单"
    assert bad_key not in plugin._strm_watch


def test_retransfer_success_clears_stale_gen_marker(monkeypatch, tmp_path):
    """
    删旧重传成功后必须清掉补生成标记。

    重传改变了事实基础：这个文件已经被完整重新上传过，之前那次「已请求补生成」
    的记录不再描述它的处境。留着标记会让看板把一轮**全新的**观察标成
    「补生成后仍无」，用户会去查一次跟当前问题无关的助手日志。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    key = "电视剧:a.mkv"
    plugin = _plugin(str(tmp_path))
    plugin._strm_gen_requested = {key: time.time() - 7200}
    plugin._reset_strm_notified_if_clear = lambda: None

    plugin._strm_arm_watch([key])

    assert key in plugin._strm_watch
    assert key not in plugin._strm_gen_requested, "重传成功后补生成标记应失效"
