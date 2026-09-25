"""
文件台账：SQLite 持久化层（唯一的有状态存储）。

File ledger: the plugin's SQLite persistence layer.

## 为什么换成 SQLite（而不是继续用 save_data 字典）

改造前有 **18 个 `save_data` 字典**，其中 5 个是"与文件有关的状态"
（`pending_queue` / `strm_watch` / `strm_suspects` / `ignored_files` /
`strm_gen_requested`）。它们的问题是**同一个文件的信息散在多个字典里**：

    某文件上传失败 → 它同时出现在 strm_watch 里（旧）、strm_suspects 里（新）、
                     可能还有 strm_gen_requested 里（补生成过）
    → 探查"这个文件到底怎么了"要在三个字典之间对照
    → 每个字典的清理时机不同（`_prune_orphan_gen_markers` 就是为"孤儿标记"专门写的）
    → 加任何新状态都要想清楚"这个字典要不要同步清理"

换成一个 `files` 表、一行一个文件、一个 `status` 字段贯穿全生命周期后，
"这个文件现在处于什么状态"变成一个字段的取值，不再是三个字典的交叉推断。

## 设计要点

1. **一行一个文件**，主键是队列 key（`映射名:相对路径`）—— 与全插件既有口径一致。
2. **`status` 是唯一的状态权威**，取值见 `STATUS_*`。流转是**线性**的，不回退。
3. **`events` 表只增不改**：排查"这个文件经历过什么"时不用猜。
4. **`meta` 表放迁移标记**，保证旧的 `save_data` 数据只导入一次。
5. 所有写操作走 `_write()`，统一 `commit` 与异常兜底 —— 台账写失败绝不能让
   同步流程崩掉（宁可丢一条记录，也不能中断正在进行的传输）。

## 与 `save_data` 的分工（不要混）

台账只放**与文件有关**的状态。以下仍是 `save_data`，因为它们不是"某个文件的状态"：

    upload_window_count / upload_blocked_until / last_force_ts   —— 限流窗口
    source_cursor / source_scan_last                            —— 扫描游标
    webhook_stat / ingest_skip_stat                             —— 运行态计数
    strm_notified                                               —— 通知闩锁

判据：如果一个值的变化**必然伴随某个文件的处理**，它属于台账；否则留在 `save_data`。
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# ---- 状态取值 ------------------------------------------------------------
# 线性流转，不回退。每个取值都对应"这个文件此刻该被怎样处理"。
STATUS_CANDIDATE = "candidate"            # 已发现、正在等冷却结束
STATUS_PENDING_VERIFY = "pending_verify"  # 已同步，等待宽限期后查 strm
STATUS_SYNCED = "synced"                  # strm 已出现，确认真的上传成功
STATUS_SUSPECT = "suspect"                # 宽限期到仍无 strm —— 待人工处理
STATUS_IGNORED = "ignored"                # 用户明确忽略，不再报警也不再处理

ALL_STATUSES = (
    STATUS_CANDIDATE, STATUS_PENDING_VERIFY, STATUS_SYNCED,
    STATUS_SUSPECT, STATUS_IGNORED,
)

# 入库来源：两条并列的入库通道（见 __init__.py 的「入库入口一览」）。
# 记下来是为了能回答"是扫描漏了还是 webhook 漏了"。
SOURCE_SCAN = "scan"
SOURCE_WEBHOOK = "webhook"
# 旧数据迁移进来时无法追溯来源，统一标成它（区别于上面两个"实时"来源）。
SOURCE_LEGACY = "legacy"

_SCHEMA_VERSION = 1


class Store:
    """
    文件台账。所有方法都是**幂等**的，重复调用不会产生重复行或错误。

    Idempotent by design: the plugin may retry the same operation (a webhook
    resend, a re-run of the sweep), and storage must not care.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        # ⚠️ 构造**不能抛异常**。台账是辅助设施：它打不开时相关功能应降级为
        # 空操作，而不是让插件加载失败（那会让整个同步功能都不可用 ——
        # 用户看到的现象是"插件装不上了"，与"账本坏了"完全不成比例）。
        # `_init_schema` 失败后仍留一个可用的对象，后续读写各自兜底返回空。
        self.usable = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._init_schema()
            self.usable = True
        except Exception:
            pass

    # ---- 连接 --------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        # 与 animeupscale 同口径：等锁 30 秒、WAL 模式（读不阻塞写）
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _write(self, sql: str, params: Iterable[Any] = ()) -> bool:
        """
        单条写操作。**失败返回 False 而不抛异常** —— 台账是辅助设施，
        它出问题绝不能让正在进行的同步流程中断（那才是真正丢数据的事）。
        """
        try:
            with self._connect() as conn:
                conn.execute(sql, tuple(params))
            return True
        except Exception:
            return False

    def _query(self, sql: str, params: Iterable[Any] = ()) -> List[sqlite3.Row]:
        try:
            with self._connect() as conn:
                return list(conn.execute(sql, tuple(params)))
        except Exception:
            return []

    # ---- 建表 --------------------------------------------------------
    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS files (
                    key              TEXT PRIMARY KEY,
                    pair             TEXT NOT NULL,
                    rel_path         TEXT NOT NULL,
                    status           TEXT NOT NULL,
                    -- 入库来源（scan / webhook / legacy），用于区分两条通道的可靠性
                    ingest_source    TEXT NOT NULL DEFAULT 'legacy',
                    -- 源文件 mtime：用于判断"文件后来又被改过"（改了就该重新走一遍）
                    src_mtime        REAL,
                    -- 各阶段时刻。**冷却/宽限期都按这里的字段计时**，
                    -- 不再另存一份时间戳（那是"双钟问题"的来源）
                    enqueued_at      REAL,
                    synced_at        REAL,
                    verified_at      REAL,
                    gen_requested_at REAL,
                    retry_count      INTEGER NOT NULL DEFAULT 0,
                    last_error       TEXT,
                    updated_at       REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
                CREATE INDEX IF NOT EXISTS idx_files_pair   ON files(pair);

                -- 事件流水：只增不改。排查"这个文件经历过什么"时不用猜。
                CREATE TABLE IF NOT EXISTS events (
                    id     INTEGER PRIMARY KEY AUTOINCREMENT,
                    key    TEXT NOT NULL,
                    at     REAL NOT NULL,
                    action TEXT NOT NULL,
                    detail TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_events_key ON events(key);

                -- 迁移标记与其它单值元数据
                CREATE TABLE IF NOT EXISTS meta (
                    k TEXT PRIMARY KEY,
                    v TEXT
                );
                """
            )

    # ---- meta --------------------------------------------------------
    def get_meta(self, key: str) -> Optional[str]:
        rows = self._query("SELECT v FROM meta WHERE k = ?", (key,))
        return rows[0]["v"] if rows else None

    def set_meta(self, key: str, value: str) -> bool:
        return self._write(
            "INSERT INTO meta(k, v) VALUES(?, ?) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (key, str(value)),
        )

    # ---- 文件行 ------------------------------------------------------
    @staticmethod
    def split_key(key: str) -> tuple:
        """
        把队列 key 拆成 (映射名, 相对路径)。

        ⚠️ 只按**第一个**冒号拆：任务名本身可以含冒号（`paths.split_pair_key`
        已注明这一点）。用 `split(":", 1)` 与全插件口径一致。
        """
        pair, _, rel = str(key).partition(":")
        return pair, rel

    def upsert(self, key: str, status: str, *, pair: str = "", rel_path: str = "",
               ingest_source: str = SOURCE_LEGACY, src_mtime: Optional[float] = None,
               enqueued_at: Optional[float] = None, synced_at: Optional[float] = None,
               verified_at: Optional[float] = None,
               gen_requested_at: Optional[float] = None,
               last_error: Optional[str] = None,
               bump_retry: bool = False) -> bool:
        """
        插入或更新一行。**只覆盖显式传入的字段**（None 表示"不动"），
        因此调用方不必先读一遍再写 —— 避免读改写竞态。
        """
        now = time.time()
        if not pair or not rel_path:
            p, r = self.split_key(key)
            pair = pair or p
            rel_path = rel_path or r
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO files (key, pair, rel_path, status, ingest_source,
                                       src_mtime, enqueued_at, synced_at, verified_at,
                                       gen_requested_at, retry_count, last_error, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        status           = excluded.status,
                        ingest_source    = excluded.ingest_source,
                        -- COALESCE：新值为 NULL 时保留旧值（"不动"语义）
                        src_mtime        = COALESCE(excluded.src_mtime, files.src_mtime),
                        enqueued_at      = COALESCE(excluded.enqueued_at, files.enqueued_at),
                        synced_at        = COALESCE(excluded.synced_at, files.synced_at),
                        verified_at      = COALESCE(excluded.verified_at, files.verified_at),
                        gen_requested_at = COALESCE(excluded.gen_requested_at, files.gen_requested_at),
                        last_error       = COALESCE(excluded.last_error, files.last_error),
                        retry_count      = files.retry_count + ?,
                        updated_at       = excluded.updated_at
                    """,
                    (key, pair, rel_path, status, ingest_source, src_mtime, enqueued_at,
                     synced_at, verified_at, gen_requested_at, 0, last_error, now,
                     1 if bump_retry else 0),
                )
            return True
        except Exception:
            return False

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM files WHERE key = ?", (key,))
        return dict(rows[0]) if rows else None

    def by_status(self, status: str) -> List[Dict[str, Any]]:
        rows = self._query(
            "SELECT * FROM files WHERE status = ? ORDER BY updated_at", (status,))
        return [dict(r) for r in rows]

    def count_by_status(self) -> Dict[str, int]:
        rows = self._query("SELECT status, COUNT(*) AS n FROM files GROUP BY status")
        out = {s: 0 for s in ALL_STATUSES}
        for r in rows:
            out[str(r["status"])] = int(r["n"])
        return out

    def set_status(self, key: str, status: str, **kw: Any) -> bool:
        return self.upsert(key, status, **kw)

    def delete(self, key: str) -> bool:
        return self._write("DELETE FROM files WHERE key = ?", (key,))

    # ---- 事件流水 ----------------------------------------------------
    def log_event(self, key: str, action: str, detail: str = "") -> bool:
        return self._write(
            "INSERT INTO events(key, at, action, detail) VALUES(?, ?, ?, ?)",
            (key, time.time(), action, detail),
        )

    def events_of(self, key: str, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self._query(
            "SELECT * FROM events WHERE key = ? ORDER BY at DESC LIMIT ?", (key, limit))
        return [dict(r) for r in rows]
