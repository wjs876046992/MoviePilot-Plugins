"""
扫描结果的**数字对账**：缺 N 个、新增 M 个，差额去哪儿了必须说清楚。

Reconciliation of the sweep's numbers: when "found N" and "added M" disagree, the
difference must be explained by name.

**为什么有这组测试**：用户实测反馈「已检查 3011 个文件，缺 strm 2 个，新增疑似 0 个」
并追问「检测到两个，却没有出现在疑似列表里」。那两个是被**忽略规则**跳过的
（用户的 ignored_files 里正有那两条），扫描器算出了这个数、也在 `message` 里
写了这句话 —— 但**看板**走的是 `data`，而 `data` 里根本没带上这两个计数字段，
于是看板上只剩两句对不上的数字。
The scanner computed the reason and even phrased it, but the dashboard reads `data`,
which never carried those counters.
"""

import importlib
import os
import time


def _plugin(root, *, ignored=None, watch=None, suspects=None):
    module = importlib.import_module("app.plugins.rsync115sync")
    src = os.path.join(root, "src")
    strm_dir = os.path.join(root, "strm")
    os.makedirs(src, exist_ok=True)
    os.makedirs(strm_dir, exist_ok=True)
    with open(os.path.join(src, "a.mkv"), "wb") as fh:
        fh.write(b"x")

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{
        "name": "电影", "src": src, "dest": os.path.join(root, "dest"),
        "strm_dir": strm_dir, "pan_dir": "/HomeTheater/Movies", "all_ext": False,
    }]
    plugin._exclude_patterns = "@eaDir/"
    plugin._media_extensions = "mkv"
    plugin._ignored_rules = list(ignored or [])
    plugin._strm_check_enabled = True
    plugin._strm_grace_hours = 6.0
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


KEY = "电影:a.mkv"


def test_scan_data_exposes_skip_reasons(tmp_path):
    """
    跳过原因必须出现在 `data` 里，不能只在 `message` 里。

    看板只读 `data`（`message` 是给聊天渠道的另一种排版）。字段少一个，
    看板就会显示成「缺 2 个、新增 0 个」而不解释为什么。
    """
    ign = [{"rule": KEY, "match": "exact", "source": "web"}]
    plugin = _plugin(str(tmp_path), ignored=ign)
    data = plugin._strm_scan()["data"]
    assert data["found"] == 1
    assert data["added"] == 0
    assert data["skipped_ignored"] == 1
    assert data.get("skipped_watching") == 0
    # 差额必须能被这些字段解释干净 —— 这是那条「数字对不上」反馈的判据
    assert data["found"] - data["added"] == data["skipped_ignored"] + data["skipped_watching"]


def test_scan_data_exposes_candidate_paths(tmp_path):
    """
    `candidates` 必须回传：用户要的是「缺哪几个」，只给计数等于让他自己去翻。

    与上一条同源：`_strm_scan` 早就在 `message` 里列出了文件清单，
    而看板读的 `data` 里没有它。
    """
    plugin = _plugin(str(tmp_path))
    data = plugin._strm_scan()["data"]
    assert data["candidates"] == [KEY]


def test_scan_data_reports_watching_skips(tmp_path):
    """观察期跳过的数量同样要能被解释。"""
    plugin = _plugin(str(tmp_path), watch={KEY: time.time()})
    data = plugin._strm_scan()["data"]
    assert data["found"] == 1
    assert data["added"] == 0
    assert data["skipped_watching"] == 1
    assert data["found"] - data["added"] == data["skipped_ignored"] + data["skipped_watching"]


# --------------------------------------------------------------------------
# 忽略规则必须连带失效补生成标记
# --------------------------------------------------------------------------

def test_ignore_clears_stale_gen_marker(tmp_path):
    """
    用户实测数据里 `strm_suspects` 为空、`strm_gen_requested` 却还留着一条
    已被忽略的文件 —— 因为当初先请求了补生成、后加的忽略规则，而忽略只清
    两个清单、漏了第三个字典。
    """
    plugin = _plugin(str(tmp_path))
    plugin._strm_gen_requested = {KEY: time.time()}
    plugin._last_status = {"missing_files": [], "corrupt_files": []}
    assert plugin._add_ignore_rule(rule=KEY, match="exact") is True
    assert KEY not in plugin._strm_gen_requested, "忽略后补生成标记成了幽灵状态"


def test_load_prunes_orphan_gen_markers(tmp_path):
    """
    载入时必须兜底清一次孤儿标记。

    调用方漏清是本条的历史成因，但**不能只靠调用方自觉**：任何一条新的
    「从清单里移除条目」路径都可能再次漏掉它，而残留是静默的。
    """
    plugin = _plugin(str(tmp_path))
    plugin._strm_watch = {}
    plugin._strm_suspects = {}
    plugin._strm_gen_requested = {KEY: time.time()}
    assert plugin._prune_orphan_gen_markers() == 1
    assert plugin._strm_gen_requested == {}


def test_orphan_prune_keeps_markers_for_live_entries(tmp_path):
    """仍挂在清单上的条目标记**不能**被误清 —— 它是看板显示「补生成后仍无」的依据。"""
    plugin = _plugin(str(tmp_path))
    plugin._strm_watch = {KEY: time.time()}
    plugin._strm_gen_requested = {KEY: time.time()}
    assert plugin._prune_orphan_gen_markers() == 0
    assert KEY in plugin._strm_gen_requested
