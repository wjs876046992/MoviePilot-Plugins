"""
传输进度：把 rsync 的 progress2 输出变成看板能显示的东西。

Transfer progress: rsync's progress2 output, made visible on the dashboard.

## 为什么需要它

在此之前一次 **28 分钟**的传输在看板上全程是黑屏 —— 唯一能看到的是
「正在同步 ⏳」这五个字。用户完全无法判断"在传"还是"卡住了"。

## 本组用例的样本全部来自**真实抓取**（rsync 3.4.1，容器内的同一版本），
## 不是照文档编的。三条与文档不符、但决定了实现形态的实测结论：

1. **进度行写在 stdout**（文档说 stderr）；
2. **帧之间用 `\\r` 分隔**，整块帧只在该文件**传完时**才补一个 `\\n`
   —— 所以 `readline()` 会等到整个文件传完才返回，逐字符读是必需的；
3. **只有"单文件完成"那一行带 `(xfr#N, to-chk=A/B)`**，中间态没有。
   想靠 `to-chk` 过滤中间行会把这些帧全部丢掉（第一版就这么错的）。
"""

import importlib

import pytest

from app.plugins.rsync115sync import progress


# ---- 真实样本（cat -A / od 抓取，非文档抄写）----
_REAL_FRAMES = [
    ("         32,768   0%    0.00kB/s    0:00:00  ",
     {"bytes": 32768, "percent": 0, "rate": "0.00kB/s", "eta": "0:00:00",
      "xfr": None, "files_left": None, "files_total": None}),
    ("        557,056  13%  500.49kB/s    0:00:06  ",
     {"bytes": 557056, "percent": 13, "rate": "500.49kB/s", "eta": "0:00:06",
      "xfr": None, "files_left": None, "files_total": None}),
    ("      2,000,000  50%  500.42kB/s    0:00:03 (xfr#1, to-chk=1/2)",
     {"bytes": 2000000, "percent": 50, "rate": "500.42kB/s", "eta": "0:00:03",
      "xfr": 1, "files_left": 1, "files_total": 2}),
    ("      4,000,000 100%  504.46kB/s    0:00:07 (xfr#2, to-chk=0/2)",
     {"bytes": 4000000, "percent": 100, "rate": "504.46kB/s", "eta": "0:00:07",
      "xfr": 2, "files_left": 0, "files_total": 2}),
]

# 与进度帧混在同一股输出里、必须被跳过的真实文本
_NON_PROGRESS = [
    "sending incremental file list",
    "sent 4,001,123 bytes  received 54 bytes  470,726.71 bytes/sec",
    "total size is 4,000,000  speedup is 1.00",
    "",
]


@pytest.mark.parametrize("line,expect", _REAL_FRAMES)
def test_parses_real_progress_frames(line, expect):
    """真实抓取的进度帧必须被逐字段还原。"""
    got = progress.parse_progress_line(line)
    assert got is not None, f"这一帧没被识别: {line!r}"
    for k, v in expect.items():
        assert got[k] == v, f"{k}: 期望 {v!r}，得到 {got[k]!r}"


@pytest.mark.parametrize("line", _NON_PROGRESS)
def test_non_progress_lines_are_none(line):
    """
    非进度行必须返回 None，而不是抛异常 —— 同一股流里混着横幅、文件名与统计。

    ⚠️ 这不是"顺带测一下"：如果这里改成抛异常，读取线程会在遇到
    `sending incremental file list` 这一行时直接崩掉，**整股输出全丢**，
    而表现是"进度条不动了、日志里也没有变更记录"。
    """
    assert progress.parse_progress_line(line) is None


def test_midfile_frame_without_parenthesis_is_still_parsed():
    """
    ⚠️ 承重：**中间态那一帧没有 `(xfr#N, to-chk=A/B)`**，必须照样被识别。

    第一版实现里我用"含 to-chk"来筛进度行，于是整批只认到最后一帧 ——
    进度条在整个传输过程中一动不动，只在结束时跳到 100%。
    这条用例就是为了钉住这个错误：中间态必须给出 bytes/percent/rate/eta，
    而 xfr/files_left/files_total 允许为 None。
    """
    got = progress.parse_progress_line(
        "      1,605,632  40%  500.16kB/s    0:00:04  ")
    assert got is not None
    assert got["percent"] == 40
    assert got["bytes"] == 1605632
    assert got["xfr"] is None and got["files_left"] is None


def test_current_file_detects_filename_lines():
    """`-v` 的文件名行是"正在传哪一个"的**唯一**来源（progress2 只给整批进度）。"""
    assert progress.current_file_of("电视剧/国漫/某剧/Season 01/E01.mkv") \
        == "电视剧/国漫/某剧/Season 01/E01.mkv"
    for noise in _NON_PROGRESS + ["subdir/", "./"]:
        assert progress.current_file_of(noise) is None, f"误判为文件名: {noise!r}"


def test_filename_hint_never_shadows_a_progress_frame():
    """
    文件名判据必须让位给进度帧 —— 两者在同一股流里，判错会让"当前文件"
    被刷成一行进度文本。

    （进度帧以空白开头，而 `current_file_of` 明确拒绝缩进行，所以顺序上
    即使先判文件名也不会误判；这条用例把这个不变量钉住。）
    """
    for line, _ in _REAL_FRAMES:
        assert progress.current_file_of(line) is None


# --------------------------------------------------------------------------
# 插件层的接线：进度能写进去、能读出来、结束会被清掉
# --------------------------------------------------------------------------

def _plugin():
    module = importlib.import_module("app.plugins.rsync115sync")
    return module.Rsync115Sync.__new__(module.Rsync115Sync)


def test_snapshot_is_none_before_any_run():
    """没跑同步时 /status 的 progress 必须是 None（前端据此整块隐藏）。"""
    assert _plugin()._progress_snapshot() is None


def test_reset_then_update_then_snapshot():
    """重置 → 更新 → 快照，字段与派生值都要对。"""
    p = _plugin()
    p._progress_reset("ready", 3)
    p._progress_update(percent=42, rate="1.2MB/s", file="a/b/c.mkv",
                       pair_name="电视剧", pair_index=2)

    snap = p._progress_snapshot()
    assert snap["percent"] == 42
    assert snap["file"] == "a/b/c.mkv"
    assert snap["pair_name"] == "电视剧"
    assert snap["pair_index"] == 2
    assert snap["pair_total"] == 3
    assert snap["mode"] == "ready"
    # 派生字段由快照算，不存进状态（避免两份时间互相漂移）
    assert isinstance(snap["elapsed_seconds"], int)
    assert isinstance(snap["stale_seconds"], int)


def test_snapshot_is_a_copy_not_the_live_state():
    """
    快照必须是副本 —— 否则 /status 的调用方拿到的是活字典，
    而读取线程正在并发改它（JSON 序列化时抛 "dictionary changed size"）。
    """
    p = _plugin()
    p._progress_reset("ready", 1)
    snap = p._progress_snapshot()
    snap["percent"] = 999

    assert p._progress_snapshot()["percent"] == 0


def test_clear_removes_the_snapshot():
    """任务结束后进度必须消失 —— 留着过期百分比比没有更糟。"""
    p = _plugin()
    p._progress_reset("ready", 1)
    p._progress_snapshot_clear()

    assert p._progress_snapshot() is None


def test_consume_segment_separates_progress_from_change_log():
    """
    `_consume_rsync_segment` 处理一个片段：进度帧返回 None（不进变更日志），
    其余原样返回。

    ⚠️ 这是"几百条进度碎片不能混进变更记录"的唯一保证 —— 加了 progress2 之后，
    若不区分，`up_files` 会把每秒一条的进度帧全数当成"变更记录"打印出来。
    """
    p = _plugin()
    p._progress_reset("ready", 1)

    assert p._consume_rsync_segment("      4,000,000 100%  504.46kB/s    0:00:07 (xfr#2, to-chk=0/2)") is None
    assert p._consume_rsync_segment("sending incremental file list") == "sending incremental file list"
    assert p._consume_rsync_segment("电视剧/E01.mkv") == "电视剧/E01.mkv"

    # 进度确实写进去了（不是被丢弃）
    assert p._progress_snapshot()["percent"] == 100
    # 文件名行也顺手更新了"当前文件"
    assert p._progress_snapshot()["file"] == "电视剧/E01.mkv"


def test_progress_state_is_available_without_init_plugin():
    """
    `__new__` 实例必须也能用进度相关方法。

    ⚠️ 本仓为"`__new__` 实例缺属性"已经栽过五次（`_rate_limit_enabled` /
    `_upload_window_secs` / `_ledger` / `_progress_lock` / …）。这次用惰性自愈
    的 `_progress_state()` 一次性解决，这条用例钉住它。
    """
    p = _plugin()
    assert "_progress_lock" not in p.__dict__        # 确实没有 init 过
    p._progress_update(percent=1)                    # 不得抛
    assert p._progress_snapshot() is None            # 未 reset 时当成"没在跑"
    p._progress_reset("ready", 1)
    assert p._progress_snapshot()["percent"] == 0


# --------------------------------------------------------------------------
# 前端：进度区与轮询节奏
# --------------------------------------------------------------------------

def _page_source():
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    path = os.path.join(root, "plugins.v3", "rsync115sync",
                        "src", "components", "Page.vue")
    return open(path, encoding="utf-8").read()


def test_dashboard_polls_faster_while_running():
    """
    运行中 5 秒、空闲 30 秒，且能在一轮之内自动切换。

    ⚠️ 空闲也用 5 秒只是白耗宿主资源（空闲时没有任何"正在变"的东西）；
    而运行中还用 30 秒则进度条毫无意义。
    """
    src = _page_source()
    assert "POLL_RUNNING_MS = 5000" in src
    assert "POLL_IDLE_MS = 30000" in src
    assert "function reschedule()" in src
    # fetchStatus 收尾必须调 reschedule，否则开始/结束同步后节奏不会切换
    assert src.count("reschedule()") >= 2


def test_progress_card_is_hidden_when_idle():
    """
    进度区由 `v-if="progress"` 整块控制 —— 空闲时必须整块消失，而不是显示 0%。

    后端空闲返回 None，因此前端一个真值判断就够，不必逐字段判空
    （字段是否齐全由 `_progress_snapshot` 保证）。
    """
    src = _page_source()
    assert 'v-if="progress"' in src
    assert "const progress = computed(() => statusData.value.progress || null)" in src


def test_dashboard_warns_when_rsync_goes_silent():
    """
    必须显示「已 N 秒没有收到 rsync 输出」。

    ⚠️ 这不是装饰：rsync 在扫描/收尾阶段会**长时间不出声**（实测一批传完会
    重复打印若干条 100%），只看百分比会以为卡死了。这一行把"在慢慢传"与
    "真卡住了"分开 —— 它也是后端停滞看门狗的证据来源。
    """
    src = _page_source()
    assert "没有收到 rsync 输出" in src
    assert "stale_seconds" in src
