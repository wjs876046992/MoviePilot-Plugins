"""
「确认失败」越窗通道与确认后放行的删旧重传守卫。

The "confirmed failed" out-of-window channel and the guard override it unlocks.

**为什么有这组测试**：这条路径上有两个反方向的错误，且都很难在真机上发现 ——
  1. **锁死用户**：窗口本意是「还可能有救的时间」，若把它当成「你必须等多久」，
     已经去 115 亲眼看过的人（只剩 `xxx.mkv..随机6位` 残留）就只能干等 6 小时，
     而窗口内看板连处理按钮都不给；
  2. **静默放过坏文件**：另一个方向是干脆取消那道守卫 —— 那么 CD2 视图过期
     导致的假阳性会变成「谁都能删掉一个看起来完好的文件」。
因此这里钉的是**两者之间的那条线**：
  · 只有 observation 清单里的 key 能被越窗（数据护栏不动）；
  · 只有 `origin == confirmed` 的条目能被放行，且必须带 `force` 二确认；
  · 未确认过的条目行为与改动前完全一致。
"""

import importlib
import os
import time

import pytest

KEY = "电视剧:a.mkv"
OTHER = "电视剧:other.mkv"
ORIGIN_CONFIRMED = "confirmed"


def _plugin(root, *, watch=None, suspects=None, dest_size=100):
    """最小实例：源/目标端都有真实文件，够走完可见性探测。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    src = os.path.join(root, "src")
    dest = os.path.join(root, "dest")
    os.makedirs(src, exist_ok=True)
    os.makedirs(dest, exist_ok=True)
    for name in ("a.mkv", "other.mkv"):
        with open(os.path.join(src, name), "wb") as fh:
            fh.write(b"x" * dest_size)
        with open(os.path.join(dest, name), "wb") as fh:
            fh.write(b"x" * dest_size)

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{
        "name": "电视剧", "src": src, "dest": dest,
        "strm_dir": os.path.join(root, "strm"), "pan_dir": "/HomeTheater/TV",
        "all_ext": False,
    }]
    plugin._exclude_patterns = "@eaDir/"
    plugin._media_extensions = "mkv"
    plugin._ignored_rules = []
    plugin._strm_check_enabled = True
    plugin._strm_grace_hours = 6.0
    plugin._strm_last_check = 0.0
    plugin._strm_notified = False
    plugin._strm_gen_requested = {}
    plugin._strm_watch = dict(watch or {})
    plugin._strm_suspects = dict(suspects or {})
    plugin._notify = False
    plugin._is_running = False
    plugin._deleted = []
    plugin._started = []
    # 预检默认放行：这些用例关心的是删除之后的行为，配额/锁由各自的用例单独设置
    plugin._rate_limit_enabled = False
    plugin._upload_max_per_window = 100
    plugin._upload_window_start = time.time()
    plugin._upload_window_count = 0
    plugin._upload_window_secs = 1800
    plugin._upload_blocked_until = 0
    plugin._is_running = False
    import threading as _threading
    plugin._lock = _threading.Lock()
    plugin._start_sync_thread = lambda **kw: plugin._started.append(kw)
    plugin._delete_dest_files_for_retry = (
        lambda keys: (plugin._deleted.extend(keys), (list(keys), []))[1])
    plugin.post_message = lambda **kw: None
    saved = {}
    plugin.save_data = lambda k, v: saved.__setitem__(k, v)
    plugin.get_data = lambda k: None
    plugin._saved = saved
    return plugin


# --------------------------------------------------------------------------
# _promote_watch_to_suspects —— 越窗入清单（唯一的权限边界是观察清单）
# --------------------------------------------------------------------------

def test_promote_moves_watch_entry_and_stamps_origin(tmp_path):
    plugin = _plugin(str(tmp_path), watch={KEY: time.time()})
    res = plugin._promote_watch_to_suspects([KEY], ORIGIN_CONFIRMED, "确认")
    assert res["moved"] == [KEY]
    assert KEY not in plugin._strm_watch
    assert plugin._strm_suspects[KEY]["origin"] == ORIGIN_CONFIRMED
    # 落盘必须包含两个清单：只写一个会让重启后条目「复活」或凭空消失
    assert "strm_watch" in plugin._saved and "strm_suspects" in plugin._saved


def test_promote_rejects_keys_outside_watch_list(tmp_path):
    """
    数据护栏：不在观察清单里的 key 一律不动。

    这是本通道**唯一**的权限边界 —— 疑似清单里的条目通向「删除云端文件」，
    若允许凭字符串构造，等于开了一个任意路径删除入口。
    """
    plugin = _plugin(str(tmp_path), watch={})
    res = plugin._promote_watch_to_suspects(["/etc/passwd", OTHER], ORIGIN_CONFIRMED, "确认")
    assert res["moved"] == []
    assert plugin._strm_suspects == {}


def test_promote_invalidates_gen_marker(tmp_path):
    """
    转疑似后补生成标记必须失效。

    留着它，看板会把一条**用户确认的事实**渲染成「补生成后仍无」这种生成侧
    推断 —— 两个完全不同的结论共用一个显示位置。
    """
    plugin = _plugin(str(tmp_path), watch={KEY: time.time()})
    plugin._strm_gen_requested = {KEY: time.time()}
    plugin._promote_watch_to_suspects([KEY], ORIGIN_CONFIRMED, "确认")
    assert KEY not in plugin._strm_gen_requested
    assert plugin._saved["strm_gen_requested"] == {}


def test_promote_is_idempotent_and_keeps_first_ts(tmp_path):
    """重复确认不刷新时间戳：否则每点一次「首次疑似时间」就往后跳。"""
    plugin = _plugin(str(tmp_path), watch={KEY: time.time()})
    plugin._promote_watch_to_suspects([KEY], ORIGIN_CONFIRMED, "确认")
    first_ts = plugin._strm_suspects[KEY]["ts"]
    # 第二次：条目已在疑似清单、不在观察清单，由手动检查重新登记回观察期再确认
    plugin._strm_watch[KEY] = time.time()
    plugin._strm_suspects[KEY]["ts"] = first_ts - 60
    res = plugin._promote_watch_to_suspects([KEY], ORIGIN_CONFIRMED, "确认")
    assert res["moved"] == [] and res["restored"] == [KEY]
    assert plugin._strm_suspects[KEY]["ts"] == pytest.approx(first_ts - 60)


# --------------------------------------------------------------------------
# _api_strm_confirm_failed —— 看板/命令入口
# --------------------------------------------------------------------------

def test_confirm_failed_accepts_suspect_list_entries(tmp_path):
    """
    **已在疑似清单**的条目也要被接受。

    这条修的是一个我自己造出来的死路：提示里写「条目已在疑似清单 → 直接点
    删旧重传」，但普通疑似条目（origin=watch）在守卫那里**没有**任何「用户
    确认过」的记录，force 也放不了行；而想补一次确认时，本接口又拒收
    非观察期条目。用户被夹在中间，两边都是死路。
    """
    plugin = _plugin(str(tmp_path), watch={},
                     suspects={KEY: {"ts": time.time(), "origin": "watch"}})
    ts_before = plugin._strm_suspects[KEY]["ts"]
    res = plugin._api_strm_confirm_failed({"keys": [KEY]})
    assert res["success"] is True
    assert plugin._strm_suspects[KEY]["origin"] == ORIGIN_CONFIRMED
    # 时间戳不得刷新：首次疑似时间要保留，否则看不出它挂了多久
    assert plugin._strm_suspects[KEY]["ts"] == ts_before
    assert res["data"]["marked"] == [KEY]


def test_confirm_failed_then_retry_force_succeeds(tmp_path):
    """
    完整闭环：疑似清单 → 确认失败 → 删旧重传（一次提醒）→ force → 真的删。

    这条把用户实际遇到的那条路整段走一遍。此前它在「确认失败」那一步就被
    拒收，后面两步永远到不了。
    """
    plugin = _plugin(str(tmp_path),
                     suspects={KEY: {"ts": time.time(), "origin": "watch"}})
    plugin._lock = __import__("threading").Lock()
    assert plugin._api_strm_confirm_failed({"keys": [KEY]})["success"] is True

    first = plugin._api_strm_retry({"keys": [KEY]})
    assert first["success"] is False and first["needs_force"] is True
    assert plugin._deleted == []

    second = plugin._api_strm_retry({"keys": [KEY], "force": True})
    assert second["success"] is True
    assert plugin._deleted == [KEY]


def test_plain_suspect_without_confirmation_stays_blocked(tmp_path):
    """
    未确认过的普通疑似条目**仍然**被拦，且不给 force 通道。

    这是另一边：确认要由用户主动补上，不能因为「清单里本来就有一条」就默认放行。
    """
    plugin = _plugin(str(tmp_path),
                     suspects={KEY: {"ts": time.time(), "origin": "watch"}})
    plugin._lock = __import__("threading").Lock()
    res = plugin._api_strm_retry({"keys": [KEY]})
    assert res["success"] is False
    assert "needs_force" not in res
    assert plugin._deleted == []
    res2 = plugin._api_strm_retry({"keys": [KEY], "force": True})
    assert res2["success"] is False
    assert plugin._deleted == []


def test_confirm_failed_promotes_and_reports(tmp_path):
    plugin = _plugin(str(tmp_path), watch={KEY: time.time()})
    res = plugin._api_strm_confirm_failed({"keys": [KEY]})
    assert res["success"] is True
    assert res["data"]["moved"] == [KEY]
    assert plugin._strm_suspects[KEY]["origin"] == ORIGIN_CONFIRMED


def test_confirm_failed_without_keys_reports_instead_of_silence(tmp_path):
    plugin = _plugin(str(tmp_path), watch={KEY: time.time()})
    assert plugin._api_strm_confirm_failed({})["success"] is False
    assert plugin._api_strm_confirm_failed({"keys": [OTHER]})["success"] is False


# --------------------------------------------------------------------------
# _api_strm_retry —— 已被用户确认的条目才能推翻可见性守卫
# --------------------------------------------------------------------------

def test_plain_suspect_is_still_blocked_by_visibility_guard(tmp_path):
    """回归锚点：未确认过的条目行为与改动前一致（仍被拦住）。"""
    plugin = _plugin(str(tmp_path),
                     suspects={KEY: {"ts": time.time(), "origin": "watch"}})
    res = plugin._api_strm_retry({"keys": [KEY]})
    assert res["success"] is False
    assert "needs_force" not in res
    assert plugin._deleted == []


def test_confirmed_suspect_first_click_asks_once_then_executes(tmp_path):
    """
    已确认的条目：一次提醒（带上真实探测结论）→ 二确认 → 才真的删。

    第一次返回 `needs_force` 而不是直接执行，是因为**那次探测的结果本身**
    就是给用户的信息：插件看到的是「可见且大小一致」，而用户看到的是云端没有
    正式文件 —— 这个分歧值得在动手前摊开。
    """
    plugin = _plugin(str(tmp_path),
                     suspects={KEY: {"ts": time.time(), "origin": ORIGIN_CONFIRMED}})
    first = plugin._api_strm_retry({"keys": [KEY]})
    assert first["success"] is False and first["needs_force"] is True
    assert "可见且大小" in first["message"]
    assert plugin._deleted == [] and plugin._started == []

    second = plugin._api_strm_retry({"keys": [KEY], "force": True})
    assert second["success"] is True
    assert plugin._deleted == [KEY]
    assert plugin._started and plugin._started[0]["custom_files"] == [KEY]


def test_force_does_not_bypass_mixed_batch(tmp_path):
    """
    同批里混着未确认的条目时，force 也**整批拒绝**。

    半执行的破坏性操作让用户无法判断「刚才那次点击到底做了什么」—— 而重试成本
    只是取消勾选再点一次。宁可让他多点一次，也不制造事后对不了账的结果。
    """
    plugin = _plugin(str(tmp_path), suspects={
        KEY: {"ts": time.time(), "origin": ORIGIN_CONFIRMED},
        OTHER: {"ts": time.time(), "origin": "watch"},
    })
    res = plugin._api_strm_retry({"keys": [KEY, OTHER], "force": True})
    assert res["success"] is False
    assert OTHER in res["message"]
    assert plugin._deleted == [], "整批拒绝时不得有任何文件被删除"


def test_unconfirmed_entries_are_not_affected_by_confirmed_ones(tmp_path):
    """确认过的条目在场时，未确认条目的拦截文案仍然指向原来的处置建议。"""
    plugin = _plugin(str(tmp_path), suspects={
        KEY: {"ts": time.time(), "origin": ORIGIN_CONFIRMED},
        OTHER: {"ts": time.time(), "origin": "watch"},
    })
    res = plugin._api_strm_retry({"keys": [KEY, OTHER]})
    assert res["success"] is False
    assert "needs_force" not in res
    assert "STRM 助手" in res["message"]


def test_missing_dest_file_needs_no_force(tmp_path):
    """
    云端确实没有文件时不走二确认（探测为 absent ⇒ 本来就不该拦）。

    这条是「守卫只拦『可见且大小一致』」的回归锚点：把 absent 也拦下来，
    用户同样会被锁死，而且是更荒谬的一种 —— 云端没文件时删除是空操作。
    """
    plugin = _plugin(str(tmp_path),
                     suspects={KEY: {"ts": time.time(), "origin": ORIGIN_CONFIRMED}})
    os.remove(os.path.join(str(tmp_path), "dest", "a.mkv"))
    res = plugin._api_strm_retry({"keys": [KEY]})
    assert res["success"] is True
    assert plugin._deleted == [KEY]


# --------------------------------------------------------------------------
# 文案契约：面向用户的回复必须是**纯文本**
# --------------------------------------------------------------------------

def _reply_strings(path):
    """取某模块里「会出现在用户面前」的字符串常量（排除 logger 与文档字符串）。

    为什么需要这个区分：本插件的同一句文案有两个消费方 —— 远程命令发到聊天渠道
    （Markdown 渲染），看板塞进纯文本区块（**不渲染**）。因此写 `**加粗**` 的结果
    是看板上出现一堆星号（用户实测反馈）。日志里写 Markdown 无所谓，所以只排除
    `logger.*` 与 docstring，其余一律当作面向用户的文案。
    """
    import ast
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)

    logged = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "attr", getattr(fn, "id", ""))
            if name in ("debug", "info", "warning", "error", "critical", "exception"):
                for arg in ast.walk(node):
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        logged.add(arg.value)

    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in docstrings or node.value in logged:
                continue
            out.append(node.value)
    return out


def test_user_facing_strings_are_plain_text():
    """
    面向用户的文案不得出现 Markdown 标记。

    看板的提示区块是纯文本（`{{ }}` 插值，不做渲染），写 `**x**` 只会显示成
    `**x**`。远程命令那边走聊天渠道，Markdown 是渲染的 —— 两者共用同一批字符串，
    所以唯一的做法是**全部按纯文本写**。
    """
    import pathlib
    plugin_dir = pathlib.Path(__file__).resolve().parents[3] / "plugins.v3" / "rsync115sync"
    offenders = []
    for name in ("strm_ops.py", "commands.py", "sync_ops.py", "__init__.py"):
        for text in _reply_strings(plugin_dir / name):
            if "**" in text:
                offenders.append((name, text.strip().splitlines()[0][:70]))
    assert not offenders, f"面向用户的文案里出现了 Markdown 标记：{offenders}"


def test_blocked_message_uses_real_newlines(tmp_path):
    """
    多段说明必须用显式 `\\n` 分隔，不能靠 Python 的隐式字符串拼接。

    隐式拼接会把几段黏成一行，而浏览器对纯文本里的单个 `\\n` 只当空格 ——
    结果是整段说明挤成一坨（用户实测看到的形态）。这条钉住「至少有两处
    \\n\\n 分段」，因为这条文案本身就是「结论 + 三条排查项 + 两条处置路径」的结构。
    """
    plugin = _plugin(str(tmp_path), suspects={KEY: {"ts": time.time(), "origin": "watch"}})
    msg = plugin._api_strm_retry({"keys": [KEY]})["message"]
    assert msg.count("\n\n") >= 2, "删除拦截文案的分段丢失，会在看板上挤成一整行"
    # 第一段与文件清单之间必须换行，否则文件名会接在冒号后面
    assert "：\n• " in msg or "：\n" in msg


def test_confirm_failed_message_is_readable(tmp_path):
    plugin = _plugin(str(tmp_path), watch={KEY: time.time()})
    msg = plugin._api_strm_confirm_failed({"keys": [KEY]})["message"]
    assert "**" not in msg
    assert "\n" in msg


# --------------------------------------------------------------------------
# 删旧重传的前置预检 —— 「删了却没传」必须变成「根本没删」
# --------------------------------------------------------------------------

def test_preflight_blocks_delete_when_quota_exhausted(tmp_path):
    """
    配额用尽时**不得删除**云端文件。

    原先的顺序是「先删 → 再 `_start_sync_thread` → `_execute_sync` 里才判配额」，
    而配额闸门一命中就整轮 `return`：文件已经删掉、却永远不会重传。
    更糟的是看板这条路径不传 `channel_event`，`_post_reply` 直接 return，
    连一句提示都发不出来 —— 用户看到的只有「已删除并开始定向重传」。
    """
    plugin = _plugin(str(tmp_path),
                     suspects={KEY: {"ts": time.time(), "origin": ORIGIN_CONFIRMED}})
    plugin._rate_limit_enabled = True
    plugin._upload_max_per_window = 0
    plugin._upload_window_start = time.time()
    plugin._upload_window_count = 0
    plugin._upload_blocked_until = 0
    plugin._lock = __import__("threading").Lock()

    res = plugin._api_strm_retry({"keys": [KEY], "force": True})
    assert res["success"] is False
    assert plugin._deleted == [], "配额不足时仍删除了文件 —— 这正是「删了却没传」的成因"
    assert plugin._started == []
    assert "配额" in res["message"]


def test_preflight_blocks_delete_during_backoff(tmp_path):
    plugin = _plugin(str(tmp_path),
                     suspects={KEY: {"ts": time.time(), "origin": ORIGIN_CONFIRMED}})
    plugin._rate_limit_enabled = True
    plugin._upload_max_per_window = 100
    plugin._upload_window_start = time.time()
    plugin._upload_window_count = 0
    plugin._upload_blocked_until = time.time() + 3600  # 风控退避中
    plugin._lock = __import__("threading").Lock()

    res = plugin._api_strm_retry({"keys": [KEY], "force": True})
    assert res["success"] is False
    assert plugin._deleted == [], "退避期内仍删除了文件"
    assert "退避" in res["message"]


def test_preflight_blocks_delete_when_lock_held(tmp_path):
    """执行锁被占用时同样不得删 —— `_execute_sync` 拿不到锁会整轮 return。"""
    plugin = _plugin(str(tmp_path),
                     suspects={KEY: {"ts": time.time(), "origin": ORIGIN_CONFIRMED}})
    plugin._rate_limit_enabled = False
    plugin._lock = __import__("threading").Lock()
    plugin._lock.acquire()
    try:
        res = plugin._api_strm_retry({"keys": [KEY], "force": True})
        assert res["success"] is False
        assert plugin._deleted == []
    finally:
        plugin._lock.release()


def test_preflight_passes_when_everything_ready(tmp_path):
    """条件都满足时必须照常删除并重传（预检不能变成新的过度保护）。"""
    plugin = _plugin(str(tmp_path),
                     suspects={KEY: {"ts": time.time(), "origin": ORIGIN_CONFIRMED}})
    plugin._rate_limit_enabled = True
    plugin._upload_max_per_window = 100
    plugin._upload_window_start = time.time()
    plugin._upload_window_count = 0
    plugin._upload_blocked_until = 0
    plugin._lock = __import__("threading").Lock()

    res = plugin._api_strm_retry({"keys": [KEY], "force": True})
    assert res["success"] is True, res.get("message")
    assert plugin._deleted == [KEY]


def test_preflight_fails_open_on_incomplete_instance(tmp_path):
    """
    预检**绝不能自己变成新的故障点**。

    它引用的状态（限流计数、窗口配置……）都由 `init_plugin` 建立，而它会在
    任何初始化不完整的路径上被走到。这不是理论问题：把它写成直接取属性后，
    `test_strm_dest_probe` 的两条既有用例当场抛 AttributeError ——
    一个「防止删了没传」的保护反而让重传整个不可用。

    这条钉住取向：异常时**放行**（等于回到改动前的行为），而不是阻塞。
    """
    plugin = _plugin(str(tmp_path),
                     suspects={KEY: {"ts": time.time(), "origin": ORIGIN_CONFIRMED}})
    # 抹掉预检要用到的全部限流状态，构造「初始化不完整」的实例
    for attr in ("_rate_limit_enabled", "_upload_window_secs", "_upload_max_per_window",
                 "_upload_window_start", "_upload_window_count", "_upload_blocked_until"):
        if hasattr(plugin, attr):
            delattr(plugin, attr)
    assert plugin._retry_preflight([]) == ""
