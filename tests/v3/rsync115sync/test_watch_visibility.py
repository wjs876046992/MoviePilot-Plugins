"""
观察期条目的可见性契约（v0.8.0 起由 `/items` 提供，不再走 `/status`）。

**为什么**：v0.7.0 之前 `/status` 只返回观察数量（`strm_watching`），用户看到
「1 个文件处于观察期」却不知道是哪个文件、等了多久 —— 观察状态完全不可见。
后来补了 `strm_watch_detail` / `strm_watch_clocks`；v0.8.0 统一改由 `/items`
的 `state=watching` 透出（与其它状态同一条取数路径），`/status` 不再提供
逐条视图 —— 本文件把这个契约钉住，防止有人把第二套取数路径加回来。

**为什么观察期不可操作**：宽限期内的文件刚同步成功，strm 可能还在生成。
此时提供「删旧重传」只会诱导误操作：删掉刚传好的文件、白白消耗一次删除 API
与重传配额。操作只应在「疑似异常」阶段出现（看板的按钮只挂在 suspect 行）。
"""

import importlib
import os
import tempfile
import time


def _plugin(root, *, watch=None, gen_requested=None):
    module = importlib.import_module("app.plugins.rsync115sync")
    store = importlib.import_module("app.plugins.rsync115sync.store")
    src = os.path.join(root, "src")
    os.makedirs(src, exist_ok=True)
    for name in ("a.mkv", "b.mkv"):
        with open(os.path.join(src, name), "wb") as fh:
            fh.write(b"x")

    ledger = store.Store(os.path.join(root, "ledger.sqlite3"))
    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._ledger = ledger
    plugin._sync_pairs = [{
        "name": "电视剧", "src": src, "dest": "/115/TV",
        "strm_dir": os.path.join(root, "strm"), "all_ext": False,
    }]
    plugin._exclude_patterns = "@eaDir/"
    plugin._media_extensions = "mkv"
    plugin._ignored_rules = []
    plugin._strm_check_enabled = True
    plugin._strm_grace_minutes = 360
    plugin._strm_last_check = 0.0
    plugin._strm_notified = False
    plugin._strm_watch = store.LedgerMapping(
        ledger, store.STATUS_PENDING_VERIFY, ts_field="enqueued_at")
    plugin._strm_suspects = store.LedgerMapping(
        ledger, store.STATUS_SUSPECT, ts_field="verified_at",
        extra_from_value={"origin": "origin"})
    plugin._strm_gen_requested = store.LedgerFieldMap(ledger, "gen_requested_at")
    plugin._failed_files = {}
    for key, ts in (watch or {}).items():
        plugin._strm_watch[key] = ts
    for key, ts in (gen_requested or {}).items():
        plugin._strm_gen_requested[key] = ts
    plugin._notify = False
    plugin._delay_hours = 2.0
    plugin._pending_queue = {}
    plugin._backfill_queue = []
    plugin._backfill_total = 0
    plugin._source_cursor = {}
    plugin._source_scan_enabled = False
    plugin._source_scan_cron = '*/10 * * * *'
    plugin._source_scan_last = 0.0
    plugin._ingest_skip_stat = {}
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


def test_status_no_longer_exposes_per_entry_strm_views():
    """
    `/status` 只给配置与整体健康；逐条视图必须走 `/items`（v0.8.0）。

    这五份键曾经与 `/items` 并行表达同一批文件，看板与命令各读一处，
    正是"同一事实两份取数"的典型来源。
    """
    plugin = _plugin(tempfile.mkdtemp())
    data = plugin._api_get_status()["data"]
    for gone in ("strm_suspects", "strm_watch_detail", "strm_watch_clocks",
                 "strm_watching", "strm_gen_requested"):
        assert gone not in data, f"/status 不应再返回 {gone}"
    # 配置与非逐条运行态仍然要在
    for kept in ("strm_check_enabled", "strm_grace_minutes", "strm_regrace_hours"):
        assert kept in data


def test_items_exposes_watching_entries_with_timestamps():
    """观察期条目由 `/items` 透出，值是可换算的原始时间戳。"""
    root = tempfile.mkdtemp()
    ts = time.time() - 120
    plugin = _plugin(root, watch={"电视剧:a.mkv": ts})

    items = plugin._api_get_items()["data"]["items"]

    row = next(it for it in items if it["key"] == "电视剧:a.mkv")
    assert row["state"] == "watching"
    assert isinstance(row["since"], float)
    assert abs(row["since"] - ts) < 1
    assert row["clock"] == "sync"


def test_items_exposes_the_gen_clock_for_rearmed_entries():
    """
    补生成移回观察期的条目必须标 `clock=gen`。

    ⚠️ 这是**双钟问题**的唯一防线：补生成按请求时刻 + 1h 重新计时，普通观察
    按宽限期配置。前端若一律按宽限期算，会与巡检的到期判定对不上。
    """
    root = tempfile.mkdtemp()
    now = time.time()
    plugin = _plugin(root,
                     watch={"电视剧:a.mkv": now, "电视剧:b.mkv": now},
                     gen_requested={"电视剧:a.mkv": now - 60})

    items = {it["key"]: it for it in plugin._api_get_items()["data"]["items"]}

    assert items["电视剧:a.mkv"]["clock"] == "gen"
    assert items["电视剧:b.mkv"]["clock"] == "sync"
