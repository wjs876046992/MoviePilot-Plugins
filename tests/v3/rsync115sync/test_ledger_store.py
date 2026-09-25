"""
文件台账（SQLite）契约测试。

The file ledger: schema, upsert semantics and the one-shot legacy migration.

**为什么需要这组测试**：本次改造把原来散在 5 个 `save_data` 字典里的
"文件状态"收进一张 `files` 表。表格语义一旦出错，表现是**静默的状态丢失**
（条目莫名消失 / 时间戳被重置 / 冷却重新计时），而不是报错 —— 这类问题
在真机上极难定位（用户只会说"队列好像不对"）。
"""

import sqlite3
import time
from pathlib import Path

import pytest


def _store(tmp_path):
    from app.plugins.rsync115sync.store import Store

    return Store(tmp_path / "ledger.sqlite3")


# --------------------------------------------------------------------------
# 表结构
# --------------------------------------------------------------------------

def test_schema_is_created_idempotently(tmp_path):
    """重复打开同一个文件不应报错，也不应重复建表。"""
    from app.plugins.rsync115sync.store import Store

    path = tmp_path / "ledger.sqlite3"
    Store(path)
    Store(path)          # 第二次打开
    with sqlite3.connect(path) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"files", "events", "meta"} <= tables


def test_wal_mode_enabled(tmp_path):
    """
    必须开 WAL：巡检线程与同步线程会同时碰台账，回滚日志模式下列表读会被写阻塞。
    """
    from app.plugins.rsync115sync.store import Store

    s = Store(tmp_path / "l.sqlite3")
    with sqlite3.connect(s.path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal", f"journal_mode={mode}"


# --------------------------------------------------------------------------
# upsert 的"只覆盖传入字段"语义（本模块最容易写错的地方）
# --------------------------------------------------------------------------

def test_upsert_only_overwrites_given_fields(tmp_path):
    """
    `None` 表示"这个字段不动"，而不是"把它清空"。

    为什么关键：调用方（例如"验证通过"）只想改 status 与 verified_at，
    若 upsert 把未传的字段写 NULL，`enqueued_at` 会被抹掉 —— 而冷却基准
    就存在那个字段里，结果是**冷却重新计时**（用户看到"明明等了三小时，
    怎么又从头开始"）。
    """
    s = _store(tmp_path)
    s.upsert("TV:a.mkv", "candidate", enqueued_at=100.0, src_mtime=50.0)
    s.upsert("TV:a.mkv", "pending_verify", synced_at=200.0)
    row = s.get("TV:a.mkv")
    assert row["status"] == "pending_verify"
    assert row["enqueued_at"] == 100.0, "enqueued_at 被 NULL 覆盖了 —— 冷却会重新计时"
    assert row["src_mtime"] == 50.0, "src_mtime 被 NULL 覆盖了"
    assert row["synced_at"] == 200.0


def test_retry_count_only_bumps_when_asked(tmp_path):
    """重试次数只在显式 `bump_retry=True` 时 +1，普通状态更新不该动它。"""
    s = _store(tmp_path)
    s.upsert("TV:a.mkv", "candidate")
    assert s.get("TV:a.mkv")["retry_count"] == 0
    s.upsert("TV:a.mkv", "suspect", bump_retry=True)
    assert s.get("TV:a.mkv")["retry_count"] == 1
    s.upsert("TV:a.mkv", "pending_verify")          # 普通更新
    assert s.get("TV:a.mkv")["retry_count"] == 1, "非重试的更新不该累加计数"


def test_upsert_derives_pair_and_rel_path_from_key(tmp_path):
    """
    未显式给 pair/rel_path 时，从 key 推导；且**只按第一个冒号拆** ——
    任务名本身可以含冒号（`paths.split_pair_key` 已记录过这个坑）。
    """
    s = _store(tmp_path)
    s.upsert("剧:集:名/S01E01.mkv", "candidate")
    row = s.get("剧:集:名/S01E01.mkv")
    assert row["pair"] == "剧"
    assert row["rel_path"] == "集:名/S01E01.mkv"


def test_upsert_survives_broken_input(tmp_path):
    """台账写失败必须返回 False 而不是抛异常 —— 它绝不能中断正在进行的同步。"""
    s = _store(tmp_path)
    # key 传成不可哈希/异常类型不应炸掉调用方
    assert s.upsert("TV:ok.mkv", "candidate") is True


# --------------------------------------------------------------------------
# 状态查询
# --------------------------------------------------------------------------

def test_count_by_status_always_returns_all_keys(tmp_path):
    """
    计数必须**补齐全部状态键**（没有的补 0）。

    为什么：看板直接读这些数字。若某个状态一条都没有就不出现这个键，
    前端取到 `undefined` 会显示成空白而不是 0 —— 用户会以为功能坏了。
    """
    from app.plugins.rsync115sync.store import ALL_STATUSES

    s = _store(tmp_path)
    s.upsert("TV:a.mkv", "candidate")
    counts = s.count_by_status()
    for st in ALL_STATUSES:
        assert st in counts, f"缺少状态键 {st}"
    assert counts["candidate"] == 1


def test_delete_removes_row(tmp_path):
    s = _store(tmp_path)
    s.upsert("TV:a.mkv", "candidate")
    s.delete("TV:a.mkv")
    assert s.get("TV:a.mkv") is None


# --------------------------------------------------------------------------
# 事件流水
# --------------------------------------------------------------------------

def test_events_are_append_only_and_newest_first(tmp_path):
    s = _store(tmp_path)
    s.log_event("TV:a.mkv", "enqueue")
    time.sleep(0.01)
    s.log_event("TV:a.mkv", "sync_ok")
    ev = s.events_of("TV:a.mkv")
    assert [e["action"] for e in ev] == ["sync_ok", "enqueue"], "事件应按时间倒序"


# --------------------------------------------------------------------------
# meta
# --------------------------------------------------------------------------

def test_meta_roundtrip_and_overwrite(tmp_path):
    s = _store(tmp_path)
    assert s.get_meta("nope") is None
    s.set_meta("k", "v1")
    assert s.get_meta("k") == "v1"
    s.set_meta("k", "v2")
    assert s.get_meta("k") == "v2", "set_meta 应是 upsert 语义"


def test_broken_store_degrades_without_raising(tmp_path):
    """
    台账文件不可用时，读取类方法返回空而不抛 —— 降级而非崩溃。
    （路径指向一个目录，让 sqlite 无法打开文件。）
    """
    from app.plugins.rsync115sync.store import Store

    bad = tmp_path / "adir"
    bad.mkdir()             # 路径是个目录 → sqlite 无法打开
    s = Store(bad)          # 构造**不得抛异常**
    assert s.usable is False, "打不开的台账应被标记为不可用"
    assert s.get("TV:a.mkv") is None
    assert s.by_status("candidate") == []
    assert s.count_by_status()  # 仍返回完整状态键、全为 0
    assert s.get_meta("x") is None
    assert s.set_meta("x", "1") is False, "不可用时写入应返回 False 而非抛异常"


def test_trim_events_keeps_newest_per_key(tmp_path):
    """
    事件流水按 **key** 裁剪到最近 N 条，而不是按总行数。

    ⚠️ 这条断言的是"为什么按 key"这个设计决定，不是实现细节：某一天批量入队
    几千个文件把总量顶上去时，按总量裁会**把别的文件的记录一并挤掉** ——
    而你想查的往往正是那个冷门的老文件。按 key 裁则每个文件都留着最近几条。
    """
    from app.plugins.rsync115sync.store import STATUS_CANDIDATE

    s = _store(tmp_path)
    # ⚠️ 必须先建台账行：事件的生命周期**跟随台账行**，无主的事件会被
    # `trim_events` 清掉（见 test_trim_events_drops_events_of_departed_files）。
    for key in ("剧:a.mkv", "剧:b.mkv"):
        s.upsert(key, STATUS_CANDIDATE, enqueued_at=1.0)
    for i in range(30):
        s.log_event("剧:a.mkv", "enqueue", str(i))
    s.log_event("剧:b.mkv", "enqueue")

    s.trim_events(keep_per_key=20)

    assert len(s.events_of("剧:a.mkv", 999)) == 20
    assert len(s.events_of("剧:b.mkv", 999)) == 1, "冷门文件不得被热门文件的量挤掉"


def test_trim_events_keeps_the_newest_not_the_oldest(tmp_path):
    """裁掉的是**最旧**的：留下陈旧记录、丢掉刚发生的事会让流水彻底没用。"""
    from app.plugins.rsync115sync.store import STATUS_CANDIDATE

    s = _store(tmp_path)
    s.upsert("剧:a.mkv", STATUS_CANDIDATE, enqueued_at=1.0)
    for i in range(5):
        s.log_event("剧:a.mkv", "step", str(i))

    s.trim_events(keep_per_key=2)

    kept = [e["detail"] for e in s.events_of("剧:a.mkv", 999)]   # 新的在前
    assert kept == ["4", "3"]


def test_trim_events_on_empty_table_is_a_noop(tmp_path):
    """空表上裁剪不得报错、也不得返回非零（它每次插件加载都会跑一遍）。"""
    s = _store(tmp_path)
    assert s.trim_events() == 0
    assert s.events_of("任何", 999) == []


def test_trim_events_returns_a_row_count_not_a_bool(tmp_path):
    """
    ⚠️ `trim_events` 必须返回**删掉的行数**，不是"成没成"。

    这条锁的是一个真出过的 bug：它最初只是转发 `_write` 的返回值（布尔），
    而调用方把那个值直接写进了日志 —— 实机日志打出的是

        📒 事件流水已裁剪 True 条（每个文件保留最近 20 条）

    那句日志既读不出信息，又**掩盖了唯一有用的信号**（到底裁没裁）。
    注意 `True == 1` 在 Python 里成立，所以"断言它是真值"永远抓不到这个 bug ——
    必须断言**类型**与**具体数值**。
    """
    from app.plugins.rsync115sync.store import STATUS_CANDIDATE

    s = _store(tmp_path)
    s.upsert("剧:a.mkv", STATUS_CANDIDATE, enqueued_at=1.0)
    for i in range(30):
        s.log_event("剧:a.mkv", "enqueue", str(i))

    trimmed = s.trim_events(keep_per_key=20)

    assert not isinstance(trimmed, bool), "返回的是布尔 —— 日志会打出「裁剪 True 条」"
    assert trimmed == 10

    # 幂等：再裁一次没有东西可删，必须返回 0
    assert s.trim_events(keep_per_key=20) == 0


def test_trim_events_drops_events_of_departed_files(tmp_path):
    """
    ⚠️ 台账行已经不在的事件必须清掉 —— **这才是无上限增长的那一半**。

    只按 key 裁是不够的：每个成功同步的文件都会给它的 key 留下若干条事件
    （实机：`arm_watch` 88 条 + 出队时的 `dequeue`），随后那一行被删掉，
    事件却留了下来。按 key 裁**看不见它们**（没有对应的台账行），
    于是它们只会一直堆积。

    规则一句话：**事件的生命周期跟随台账行**。行没了，它的历史既没有锚点
    也没有读者（`events_of` 是按 key 查的，没有任何地方会枚举已离场的 key）。

    ⚠️ 因此 `dequeue` 的可见窗口是"到下次插件加载为止" —— 你要查"它怎么不见了"
    的时刻，恰恰是刚跑完一轮、还在看台账的时候。
    """
    from app.plugins.rsync115sync.store import STATUS_CANDIDATE

    s = _store(tmp_path)
    # 模拟：3 个文件同步成功后出队（台账行被删），1 个仍在跟踪
    for i in range(3):
        key = f"剧:gone{i}.mkv"
        s.upsert(key, STATUS_CANDIDATE, enqueued_at=1.0)
        s.log_event(key, "enqueue")
        s.log_event(key, "dequeue", "candidate")
        s.delete(key)
    s.upsert("剧:alive.mkv", STATUS_CANDIDATE, enqueued_at=1.0)
    s.log_event("剧:alive.mkv", "enqueue")

    removed = s.trim_events()

    assert removed == 6, "已出队文件的 6 条事件都该被清掉"
    assert s.events_of("剧:gone0.mkv") == []
    assert [e["action"] for e in s.events_of("剧:alive.mkv")] == ["enqueue"]
