"""
观察期条目的可见性契约。

Watch-phase entries must be visible on the dashboard with an explicit
「观察中」 tag and **no action buttons**.

**为什么**：此前 /status 只返回观察数量（strm_watching），用户看到「1 个文件处于
观察期」却不知道是哪个文件、等了多久 —— 观察状态完全不可见。现在返回明细并
在看板展示为只读条目。

**为什么不可操作**：宽限期内的文件刚同步成功，strm 可能还在生成（上传/刮削中）。
此时提供「删旧重传」按钮只会诱导用户误操作：删掉刚传好的文件、白白消耗一次
115 删除 API 与重传配额。操作只应在「疑似异常」阶段出现。
"""

import importlib
import os
import tempfile
import time


def _plugin(root, *, watch=None, suspects=None):
    module = importlib.import_module("app.plugins.rsync115sync")
    src = os.path.join(root, "src")
    os.makedirs(src, exist_ok=True)
    for name in ("a.mkv", "b.mkv"):
        with open(os.path.join(src, name), "wb") as fh:
            fh.write(b"x")

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{
        "name": "电视剧", "src": src, "dest": "/115/TV",
        "strm_dir": os.path.join(root, "strm"), "all_ext": False,
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
    plugin._delay_hours = 2.0
    plugin._pending_queue = {}
    plugin._backfill_queue = []
    plugin._backfill_total = 0
    plugin._missed_queue = {}
    plugin._missed_last_scan = 0
    plugin._missed_scan_enabled = False
    plugin._last_status = {"missing_files": [], "corrupt_files": []}
    plugin._is_running = False
    plugin._rate_limit_enabled = True
    plugin._upload_window_count = 0
    plugin._upload_max_per_window = 500
    plugin._upload_blocked_until = 0.0
    plugin._last_force_ts = 0.0
    plugin._force_cooldown_days = 7
    plugin.get_data = lambda k: None
    plugin.save_data = lambda k, v: None
    return plugin


def test_status_returns_watch_detail():
    """/status 必须返回观察清单的明细，而不只是数量。"""
    root = tempfile.mkdtemp()
    plugin = _plugin(root, watch={"电视剧:a.mkv": time.time() - 60})

    data = plugin._api_get_status()["data"]

    assert "strm_watch_detail" in data
    assert "电视剧:a.mkv" in data["strm_watch_detail"]
    assert data["strm_watching"] == 1


def test_status_watch_detail_excludes_suspects():
    """观察明细与疑似清单必须是两个互斥的集合 —— 一个 key 只能在一处。"""
    root = tempfile.mkdtemp()
    plugin = _plugin(root,
                     watch={"电视剧:a.mkv": time.time()},
                     suspects={"电视剧:b.mkv": {"ts": time.time(), "origin": "scan"}})

    data = plugin._api_get_status()["data"]

    assert list(data["strm_watch_detail"]) == ["电视剧:a.mkv"]
    assert list(data["strm_suspects"]) == ["电视剧:b.mkv"]


def test_expired_watch_moves_to_suspects_and_leaves_watch_detail():
    """
    状态流转的可见性：宽限期到期 → 从观察明细消失、出现在疑似清单。
    用户看到的条目应从「观察中」变为「疑似异常」，而不是两个地方都有。
    """
    root = tempfile.mkdtemp()
    now = time.time()
    plugin = _plugin(root, watch={"电视剧:a.mkv": now - 7 * 3600})  # 7h 前同步，已超 6h 宽限
    plugin._strm_last_check = 0

    plugin._strm_check()

    assert "电视剧:a.mkv" not in plugin._strm_watch
    assert "电视剧:a.mkv" in plugin._strm_suspects

    data = plugin._api_get_status()["data"]
    assert "电视剧:a.mkv" not in data["strm_watch_detail"]
    assert "电视剧:a.mkv" in data["strm_suspects"]


def test_watch_detail_is_raw_timestamps_for_frontend_math():
    """明细值是同步成功的时间戳（原始数字），剩余时间由前端换算 —— 保持后端无展示逻辑。"""
    root = tempfile.mkdtemp()
    ts = time.time() - 120
    plugin = _plugin(root, watch={"电视剧:a.mkv": ts})

    detail = plugin._api_get_status()["data"]["strm_watch_detail"]

    assert isinstance(detail["电视剧:a.mkv"], float)
    assert abs(detail["电视剧:a.mkv"] - ts) < 1
