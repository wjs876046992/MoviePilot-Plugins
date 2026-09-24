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
