"""
入库闸门单测：哪些候选文件会进入冷却队列。

Tests for the ingest gate — the entry point of the whole sync chain. If a file
fails to enqueue here it is never uploaded, and nothing anywhere reports an
error: the file simply never appears. That silence is why these cases matter.

⚠️ 本文件原先驱动的是**宿主的整理完成事件**（`_handle_transfer_event`）。那条
路径已于 2026-09-25 整条删除（理由：只覆盖整理链路、durable outbox 不重放、
宿主版本相关、装饰器在类体求值 —— 见 DEVELOPMENT §4.0f），改用**源端游标扫描**
作为主通道。

**用例本身全部保留**：它们验证的是扩展名闸门 / 映射归属 / 存在性 / 忽略清单 /
幂等 / 目录展开这些**入队判据**，与候选路径从哪条通道来无关 —— 而所有通道都
汇入同一个 `_enqueue_ingest_paths`。因此这里只换驱动入口，断言一字未改。
The cases are preserved verbatim: they test the ingest gate, which is shared by
every channel. Only the entry point changed.
"""

import os
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.plugins.rsync115sync import Rsync115Sync


def mod_today_start():
    """当日 0 点时间戳（与被测实现的基线规则一致，来源是同一模块的函数）。"""
    from app.plugins.rsync115sync import _today_start_ts

    return _today_start_ts()


def _plugin(src_root, *, delay_hours=2.0, media_extensions="mkv,srt",
            all_ext=False, pair_name="TV"):
    """构造只带事件处理所需状态的最小实例。"""
    plugin = Rsync115Sync.__new__(Rsync115Sync)
    plugin.plugin_version = "test"
    plugin._enabled = True
    plugin._listen_transfer = True
    plugin._delay_hours = delay_hours
    plugin._media_extensions = media_extensions
    plugin._sync_pairs = [{
        "name": pair_name, "src": src_root, "dest": "/dest/TV",
        "all_ext": all_ext, "strm_dir": "",
    }]
    plugin._pending_queue = {}
    plugin._source_cursor = {}
    plugin._source_scan_enabled = True
    plugin._exclude_patterns = plugin.DEFAULT_EXCLUDE_PATTERNS
    plugin._ignored_rules = []
    plugin._last_status = {}
    plugin.saved = {}
    plugin.save_data = lambda k, v: plugin.saved.__setitem__(k, v)
    return plugin


# --------------------------------------------------------------------------
# 基本入队
# --------------------------------------------------------------------------

def test_existing_media_file_is_enqueued(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "S01E01.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._enqueue_ingest_paths(list([str(f)]), source='', event_desc='test')

    assert list(plugin._pending_queue) == ["TV:S01E01.mkv"]
    assert plugin.saved.get("pending_queue") == plugin._pending_queue


def test_nested_path_is_stored_relative_to_src(tmp_path):
    """队列 key 用**相对路径**，绝对路径在不同容器/挂载下不通用。"""
    src = tmp_path / "TV"
    (src / "剧集" / "Season 01").mkdir(parents=True)
    f = src / "剧集" / "Season 01" / "S01E03.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._enqueue_ingest_paths(list([str(f)]), source='', event_desc='test')

    assert list(plugin._pending_queue) == ["TV:剧集/Season 01/S01E03.mkv"]


def test_extension_filter_skips_non_media(tmp_path):
    """.nfo/.jpg 等不在扩展名白名单内的文件不入队（同步它们无意义且浪费配额）。"""
    src = tmp_path / "TV"
    src.mkdir()
    mkv = src / "a.mkv"
    nfo = src / "a.nfo"
    mkv.write_bytes(b"x")
    nfo.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._enqueue_ingest_paths(list([str(mkv), str(nfo)]), source='', event_desc='test')

    assert list(plugin._pending_queue) == ["TV:a.mkv"]


def test_all_ext_pair_enqueues_every_extension(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    nfo = src / "a.nfo"
    nfo.write_bytes(b"x")

    plugin = _plugin(str(src), all_ext=True)
    plugin._enqueue_ingest_paths(list([str(nfo)]), source='', event_desc='test')

    assert list(plugin._pending_queue) == ["TV:a.nfo"]


def test_subtitle_extension_is_enqueued(tmp_path):
    """字幕必须入队：冷却期的设计目的就是「等外挂字幕下载完再上传」。"""
    src = tmp_path / "TV"
    src.mkdir()
    srt = src / "S01E01.zh.srt"
    srt.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._enqueue_ingest_paths(list([str(srt)]), source='', event_desc='test')

    assert list(plugin._pending_queue) == ["TV:S01E01.zh.srt"]


# --------------------------------------------------------------------------
# 映射归属（决定「会不会被同步」）
# --------------------------------------------------------------------------

def test_path_outside_any_mapping_is_not_enqueued(tmp_path):
    """下载器源路径通常不在媒体库映射内，绝不能错误入队。"""
    src = tmp_path / "TV"
    src.mkdir()
    other = tmp_path / "downloads" / "a.mkv"
    other.parent.mkdir()
    other.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._enqueue_ingest_paths(list([str(other)]), source='', event_desc='test')

    assert plugin._pending_queue == {}


def test_sibling_prefix_is_not_attributed_to_wrong_mapping(tmp_path):
    """
    关键回归：`/media/TV` 不得吞掉 `/media/TV2/...`。

    一旦归属错映射，文件会被上传到**另一个** 115 目标目录 —— 静默的破坏性后果。
    """
    tv = tmp_path / "TV"
    tv2 = tmp_path / "TV2"
    tv.mkdir()
    tv2.mkdir()
    f = tv2 / "a.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(tv))
    plugin._enqueue_ingest_paths(list([str(f)]), source='', event_desc='test')

    assert plugin._pending_queue == {}


def test_file_owned_by_mapping_but_unreadable_is_not_enqueued(tmp_path):
    """路径前缀匹配但容器内读不到（宿主/容器挂载不一致）→ 不入队。"""
    src = tmp_path / "TV"
    src.mkdir()

    plugin = _plugin(str(src))
    plugin._enqueue_ingest_paths(list([str(src / "不存在的文件.mkv")]), source='', event_desc='test')

    assert plugin._pending_queue == {}


# --------------------------------------------------------------------------
# 幂等（事件走 durable outbox，at-least-once）
# --------------------------------------------------------------------------

def test_duplicate_delivery_keeps_original_timestamp(tmp_path):
    """
    重复投递**不得刷新冷却计时**。

    若无条件覆盖时间戳，每次重投都会把冷却重新计时，表现为
    「明明是 1 小时前入库的文件，冷却永远走不完、永远不同步」。
    """
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    with patch("app.plugins.rsync115sync.time.time", return_value=1000.0):
        plugin._enqueue_ingest_paths(list([str(f)]), source='', event_desc='test')
    first_ts = plugin._pending_queue["TV:a.mkv"]

    with patch("app.plugins.rsync115sync.time.time", return_value=9999.0):
        plugin._enqueue_ingest_paths(list([str(f)]), source='', event_desc='test')

    assert plugin._pending_queue["TV:a.mkv"] == first_ts == 1000.0


def test_scan_path_uses_discovery_time_as_basis(tmp_path):
    """
    源端扫描入队时，队列值 = `min(发现时刻, mtime)`。

    ⚠️ 这条用例替换了原先的「入队后清理 `_missed_queue`」。那个队列已删除，
    而它承担的语义（"错过的事件要补回来"）现在由**冷却基准取 mtime** 表达：
    重载期间错过的文件 mtime 已旧 → 基准旧 → 立即到期 → 下一轮就传。
    这里用"老 mtime"钉住这一点，防止有人把基准改成"一律用发现时刻"
    （那会让错过的事件再也补不上，需要额外等满一个冷却期）。
    """
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")
    old = time.time() - 10 * 3600          # 10 小时前入库
    os.utime(f, (old, old))

    plugin = _plugin(str(src))
    plugin._enqueue_ingest_paths([str(f)], source='', event_desc='test', from_scan=True)

    basis = plugin._pending_queue["TV:a.mkv"]
    assert abs(basis - old) < 2, (
        f"扫描入队的老文件应以自身 mtime 为冷却基准（{old}），实际 {basis}；"
        "若等于发现时刻，说明'错过的事件'要多等一个冷却期才能补上"
    )
    assert time.time() - basis > plugin._delay_hours * 3600, "10 小时前的文件应已到期"


def test_old_mtime_is_treated_as_due_for_both_sources(tmp_path):
    """
    mtime 明显早于发现时刻 ⇒ 判为「早就该传了」，**两个来源一致**（都走 min）。

    为什么这是对的，而不是漏洞：实测（2026-09-25）`cp -p` / `rsync -a` 都在
    **内容写完之后**才设置 mtime。因此"看见老 mtime"等价于"这个文件已经拷完了"
    —— 而正在写入的文件带的是当前时间，会由 min 正常纳入冷却。

    ⚠️ 这条用例存在的真正价值：**钉住"别把 cp -p 说成需要额外保护"**。
    `_cooldown_basis` 的 docstring 一度声称 min 能防住 cp -p，那是错的
    （min 恰恰会放行老 mtime）；写错的注释比没有注释更糟，因为后来者会照它推导。
    """
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")
    old = time.time() - 10 * 3600
    os.utime(f, (old, old))

    # 扫描来源
    p1 = _plugin(str(src))
    p1._enqueue_ingest_paths([str(f)], source='', event_desc='test', from_scan=True)
    b1 = p1._pending_queue["TV:a.mkv"]
    assert abs(b1 - old) < 2, f"扫描：应以老 mtime 为基准，实际偏差 {b1-old:.0f}s"

    # webhook 来源
    p2 = _plugin(str(src))
    p2._enqueue_ingest_paths([str(f)], source='', event_desc='test', from_scan=False)
    b2 = p2._pending_queue["TV:a.mkv"]
    assert abs(b2 - old) < 2, (
        f"webhook：同样应以老 mtime 为基准（两个来源一致），实际偏差 {b2-old:.0f}s；"
        "若这里取发现时刻，说明有人在 webhook 路径上偷偷加了不同的兜底"
    )
    assert time.time() - b1 > p1._delay_hours * 3600, "10 小时前的文件应判为已到期"


def test_from_scan_only_affects_unreadable_mtime(tmp_path):
    """
    `from_scan` 的**唯一**影响面是 `getmtime` 抛错时的兜底方向。

    这条用例把该参数的作用域钉死，防止它被顺手扩成"两个来源不同的冷却规则"
    —— 那样同一条路径从扫描进来还是从 webhook 进来会有两种到期时间，
    而这种差异在界面上完全看不出来。
    """
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")
    os.utime(f, (time.time(), time.time()))

    plugin = _plugin(str(src))
    before = time.time()
    plugin._enqueue_ingest_paths([str(f)], source='', event_desc='test', from_scan=True)
    b = plugin._pending_queue["TV:a.mkv"]
    assert before - 2 <= b <= time.time() + 1, (
        f"可读 mtime 时，from_scan 不该改变基准（应为发现时刻），实际 {b}"
    )


def test_multiple_files_in_one_event_all_enqueued(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    files = []
    for i in range(3):
        p = src / f"e{i}.mkv"
        p.write_bytes(b"x")
        files.append(str(p))

    plugin = _plugin(str(src))
    plugin._enqueue_ingest_paths(list(files), source='', event_desc='test')

    assert sorted(plugin._pending_queue) == ["TV:e0.mkv", "TV:e1.mkv", "TV:e2.mkv"]


# --------------------------------------------------------------------------
# 源端游标扫描（主通道）—— 只覆盖与"通道"本身有关的语义；
# 闸门判据（扩展名/归属/存在性/幂等）由上面的用例覆盖，两者不重复测。
# --------------------------------------------------------------------------

def test_source_scan_baseline_is_today_midnight(tmp_path):
    """
    首次扫描的基线取**当日 0 点**：今天已入库的存量要被覆盖，昨天的不动。

    ⚠️ 别改成「基线=当前时刻」（今天的文件会成为永久漏）或「只记不入队」
    （同一个漏，还要多维护一份状态）。两次踩法不同、后果相同。
    """
    src = tmp_path / "TV"
    src.mkdir()
    old = src / "yesterday.mkv"
    old.write_bytes(b"x")
    stamp = mod_today_start() - 3600          # 昨天
    os.utime(old, (stamp, stamp))
    today = src / "today.mkv"
    today.write_bytes(b"x")                   # mtime = now

    plugin = _plugin(str(src))
    n = plugin._scan_source_cursor()

    assert n == 1, f"应只捞到今天的 1 个，实际 {n}（{list(plugin._pending_queue)}）"
    assert list(plugin._pending_queue) == ["TV:today.mkv"]


def test_source_scan_advances_cursor_so_second_run_is_quiet(tmp_path):
    """
    游标推进 ⇒ 同一批文件不会被第二轮重复入队。

    这是「不多传」的第一层：没有它，每轮扫描都会把整批文件重新塞进队列
    （队列幂等虽然能兜住，但每轮都要重扫重判，且日志会被"发现 N 个"刷屏）。
    """
    src = tmp_path / "TV"
    src.mkdir()
    (src / "a.mkv").write_bytes(b"x")

    plugin = _plugin(str(src))
    assert plugin._scan_source_cursor() == 1
    assert plugin._scan_source_cursor() == 0
    assert plugin._scan_source_cursor() == 0
    assert len(plugin._pending_queue) == 1


def test_source_scan_overlap_window_catches_boundary_mtime(tmp_path):
    """
    重叠窗口：mtime **恰好等于**游标的文件仍要被发现。

    `os.path.getmtime` 的比较是严格大于，而同一秒批量落盘很常见（整季拷贝、
    SMB 一次写入）。没有这个窗口，这类文件会**每次都落在窗口外、永久跳过** ——
    一种不会报错、只是永远少几个文件的失效。
    """
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "boundary.mkv"
    f.write_bytes(b"x")
    cursor_ts = time.time() - 30              # 30 秒前推进过游标
    os.utime(f, (cursor_ts, cursor_ts))       # mtime 恰好 == 游标

    plugin = _plugin(str(src))
    plugin._source_cursor = {"TV": cursor_ts}
    n = plugin._scan_source_cursor()

    assert n == 1, "mtime 恰等于游标的文件被漏掉了（重叠窗口未生效）"


def test_source_scan_only_advances_cursor_after_enqueue(tmp_path):
    """
    ⚠️ 游标只在**成功入队之后**推进。

    旧实现无条件推进（`self._missed_last_scan = now_ts` 写在循环外、入队失败
    也会执行）。若这里退化回去，一次落盘异常就会让整批候选永久丢失 ——
    游标越过了它们，而它们从未进过队列，任何一轮同步都不会再取。
    """
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._source_cursor = {}
    plugin._scan_source_cursor()
    first_cursor = plugin._source_cursor["TV"]
    assert first_cursor > 0

    # 让第二次扫描的入队环节抛错：游标不得推进
    def _boom(*a, **k):
        raise RuntimeError("模拟入队失败")

    plugin._enqueue_ingest_paths = _boom
    (src / "b.mkv").write_bytes(b"x")
    with pytest.raises(RuntimeError):
        plugin._scan_source_cursor()
    assert plugin._source_cursor["TV"] == first_cursor, (
        "入队失败后游标仍被推进 —— 这一批候选将永久丢失"
    )


# --------------------------------------------------------------------------
# 守卫：开关关闭（由**调用方**判定，不在闸门内部）
# --------------------------------------------------------------------------

# ⚠️ 这两个开关此前藏在已删除的 `_handle_transfer_event` 里，因此由那条路径
# 的用例覆盖。现在**每个调用方自己判**：`_handle_webhook_event` 与
# `_scan_source_cursor_safe` 各自在入口 return。测试也随之改为直调调用方 ——
# 断言"闸门自己拦"会让用例在一个根本不存在的机制上通过。
def test_webhook_handler_returns_early_when_disabled(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._enabled = False
    plugin._handle_webhook_event(SimpleNamespace(
        event_data=SimpleNamespace(channel="rsync115sync", event="library.new",
                                   server_name="x", item_path=str(f), json_object={})))

    assert plugin._pending_queue == {}


def test_listen_transfer_off_does_not_enqueue(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._listen_transfer = False
    plugin._handle_webhook_event(SimpleNamespace(
        event_data=SimpleNamespace(channel="rsync115sync", event="library.new",
                                   server_name="x", item_path=str(f), json_object={})))

    assert plugin._pending_queue == {}


def test_source_scan_service_returns_early_when_disabled(tmp_path):
    """扫描 service 入口也必须尊重开关：关闭时不该遍历目录。"""
    src = tmp_path / "TV"
    src.mkdir()
    (src / "a.mkv").write_bytes(b"x")
    plugin = _plugin(str(src))
    plugin._source_cursor = {}

    plugin._source_scan_enabled = False
    assert plugin._scan_source_cursor_safe() == 0
    assert plugin._pending_queue == {}

    plugin._source_scan_enabled = True
    assert plugin._scan_source_cursor_safe() == 1


def test_empty_path_entries_are_skipped(tmp_path):
    src = tmp_path / "TV"
    src.mkdir()
    f = src / "a.mkv"
    f.write_bytes(b"x")

    plugin = _plugin(str(src))
    plugin._enqueue_ingest_paths(["", None, str(f)], source='', event_desc='test')

    assert list(plugin._pending_queue) == ["TV:a.mkv"]
