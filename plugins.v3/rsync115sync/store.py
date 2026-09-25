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
            self._upgrade_schema()
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
                    -- 疑似来源（watch / scan / confirmed）。改造前放在
                    -- `_strm_suspects[key]["origin"]`：这条疑点是同步后观察判出来的、
                    -- 还是主动扫描扫出来的 —— 可信度不同，看板要显示。
                    origin           TEXT,
                    -- 云端可见性结论。**纯展示**：它有已知假阳性（CD2 改名失败时
                    -- 坏文件也显示大小一致），因此绝不参与任何清理判据。
                    dest             TEXT,
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

    def _upgrade_schema(self) -> None:
        """
        给**已存在**的台账补新增列。

        第 1 批已经部署过，用户机器上可能已有 `ledger.sqlite3`；
        `CREATE TABLE IF NOT EXISTS` 不会给已有表加列，因此必须显式补。
        `ALTER TABLE ADD COLUMN` 重复执行会报错，所以先查 `PRAGMA table_info`。

        Idempotent ADD COLUMN for ledgers created by an earlier build.
        """
        want = {"files": [("origin", "TEXT"), ("dest", "TEXT")]}
        try:
            with self._connect() as conn:
                for table, cols in want.items():
                    have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                    for name, decl in cols:
                        if name not in have:
                            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        except Exception:
            pass

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
               origin: Optional[str] = None,
               dest: Optional[str] = None,
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
                                       gen_requested_at, retry_count, last_error,
                                       origin, dest, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        origin           = COALESCE(excluded.origin, files.origin),
                        dest             = COALESCE(excluded.dest, files.dest),
                        retry_count      = files.retry_count + ?,
                        updated_at       = excluded.updated_at
                    """,
                    (key, pair, rel_path, status, ingest_source, src_mtime, enqueued_at,
                     synced_at, verified_at, gen_requested_at, 0, last_error,
                     origin, dest, now,
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


# ==========================================================================
# 台账支持的「字典替身」：以 SQLite 为真相源、对外仍是 dict 接口
# ==========================================================================

from collections.abc import MutableMapping  # noqa: E402


class LedgerMapping(MutableMapping):
    """
    把台账里的某一类状态暴露成 dict 接口 —— 现有读写点**一行都不用改**。

    Expose one status class of the ledger as a plain dict-like object, so the
    ~175 existing read/write sites (`q[key] = ts` / `key in q` / `q.pop(k)` /
    `q.items()`) keep working untouched.

    ## 为什么用这个办法而不是"逐个改读写点"

    改造前 `pending_queue` / `strm_watch` / `strm_suspects` / `ignored` 四类状态
    合计约 175 处读写。逐个改写有两个问题：

      1. **量大且分散** —— 任何一处漏改都是静默的行为差异（例如某个分支仍在读
         旧字典，表现为"看板上有时对有时不对"）；
      2. **不可回滚** —— 一旦改了一半，代码处于两套状态并存且不一致的中间态。

    用替身类之后，切换点只有**构造处一行**：`self._pending_queue = LedgerMapping(...)`。
    行为差异被限制在一个类里，可单独测试、可单独回退。

    ## 内存缓存 + 写穿（write-through）

    读全部走内存缓存（性能：`.items()` 在循环里被频繁调用，每次都查 SQLite
    会明显变慢）；写同时改缓存与 SQLite。

    **真相源是 SQLite**：缓存只在进程内有效，重启后从台账重建。因此若 SQLite
    写失败，内存里会短暂领先于台账 —— 这是刻意的取舍（宁可丢一条记录的持久化，
    也不能因为台账故障中断同步），失败会记 warning。

    ## 只暴露与文件有关的字段

    值统一是 `Dict[str, Any]`（台账整行）。但旧代码里有两种用法：
      · `_pending_queue[key] = ts`      —— 写**裸时间戳**
      · `_strm_suspects[key] = {...}`   —— 写**字典**
    因此 `__setitem__` 需要兼容两种：给标量时按"时间戳"存进该状态对应的
    时间字段，给字典时按字段名存。见 `_to_row`。
    """

    def __init__(self, ledger: "Store", status: str, *,
                 ts_field: str = "enqueued_at",
                 extra_from_value: Optional[Dict[str, str]] = None):
        """
        :param ledger: 台账
        :param status: 本替身对应的 status 取值（candidate / pending_verify / ...）
        :param ts_field: `self[k] = <标量>` 时，那个标量写进哪个时间字段
        :param extra_from_value: `self[k] = {..}` 时，字典的哪些键映射到台账字段
            （未列出的键会被忽略 —— 台账是强 schema，不能让调用方塞任意字段）
        """
        self._ledger = ledger
        self._status = status
        self._ts_field = ts_field
        self._extra = dict(extra_from_value or {})
        self._cache: Dict[str, Any] = {}
        self._load()

    # ---- 载入 --------------------------------------------------------
    def _load(self) -> None:
        """从台账重建内存缓存。台账不可用时留空缓存（降级为空集合）。"""
        self._cache = {}
        if self._ledger is None or not getattr(self._ledger, "usable", False):
            return
        for row in self._ledger.by_status(self._status):
            self._cache[str(row["key"])] = self._row_to_value(row)

    def reload(self) -> None:
        """外部改过台账后重新载入（跨实例共享同一台账时用）。"""
        self._load()

    def _row_to_value(self, row: Any) -> Any:
        """
        台账行 → 旧代码期望的值形态。

        ⚠️ 还原成**与改造前一致**的形状是这一步的关键：旧代码会写
        `self._strm_suspects[k]["dest"]`、`entry.get("ts")` 等，形状不对就是
        KeyError/TypeError。宁可在这里多写几行转换，也不要让调用方感知到存储变了。
        """
        row = dict(row)
        ts = row.get(self._ts_field)
        # 只有"时间戳型"的队列还原成裸标量（`_pending_queue[key] = ts` 的语义）；
        # 其余还原成字典（`_strm_suspects[key] = {...}` 的语义）。
        if self._ts_field == "enqueued_at" and not self._extra:
            return ts if ts is not None else 0.0
        out: Dict[str, Any] = {}
        if ts is not None:
            out["ts"] = ts
        for field, key_name in self._extra_inverse().items():
            if row.get(field) is not None:
                out[key_name] = row[field]
        return out

    def _extra_inverse(self) -> Dict[str, str]:
        """`{台账字段: 值里的键名}`（构造参数是反过来的，这里翻一次）。"""
        return {v: k for k, v in self._extra.items()}

    def _to_row(self, value: Any) -> Dict[str, Any]:
        """旧代码给的值 → 台账字段。兼容裸标量与字典两种。"""
        if isinstance(value, (int, float)):
            return {self._ts_field: float(value)}
        if isinstance(value, dict):
            row: Dict[str, Any] = {}
            if "ts" in value:
                row[self._ts_field] = value["ts"]
            for key_name, field in self._extra.items():
                if key_name in value:
                    row[field] = value[key_name]
            return row
        return {}

    # ---- MutableMapping 接口 ----------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self._cache[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._cache[key] = value
        if self._ledger is None:
            return
        fields = self._to_row(value)
        # `self[k] = ts` 的语义是"新入队"：缺 enqueued_at 时补当前时刻，
        # 否则该行没有计时基准，后续"到期没到期"就算不出来。
        if self._ts_field == "enqueued_at" and self._ts_field not in fields:
            fields[self._ts_field] = time.time()
        if not self._ledger.upsert(key, self._status, **fields):
            # 不抛：台账故障不该中断同步（见 Store._write 的说明）
            pass

    def __delitem__(self, key: str) -> None:
        self._cache.pop(key, None)
        if self._ledger is not None:
            self._ledger.delete(key)

    def __iter__(self):
        return iter(self._cache)

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, key: object) -> bool:
        return key in self._cache

    def clear(self) -> None:
        """清空该状态的全部条目（只删本状态的行，不动其它状态）。"""
        for key in list(self._cache):
            if self._ledger is not None:
                self._ledger.delete(key)
        self._cache.clear()

    def pop(self, key, *args):
        """
        ⚠️ 必须自己实现 `pop` 而不是依赖 MutableMapping 的默认实现：
        默认实现是 `try: v=self[key] except KeyError: ...`，那会走 `__getitem__`，
        对**不存在的 key 抛 KeyError**，而本插件到处在用 `q.pop(k, None)`
        ——语义上应当与 dict 完全一致。直接代理到缓存即可。
        """
        if key in self._cache:
            value = self._cache.pop(key)
            if self._ledger is not None:
                self._ledger.delete(key)
            return value
        if args:
            return args[0]
        raise KeyError(key)

    def update(self, other=(), **kwargs) -> None:      # type: ignore[override]
        """批量写入（`_pending_queue.update({...})` 之类）。"""
        items = dict(other, **kwargs) if other else dict(**kwargs)
        for k, v in items.items():
            self[k] = v

    def setdefault(self, key, default=None):
        if key in self._cache:
            return self._cache[key]
        self[key] = default
        return default

    def keys(self):
        return self._cache.keys()

    def values(self):
        return self._cache.values()

    def items(self):
        return self._cache.items()

    def get(self, key, default=None):
        return self._cache.get(key, default)

    def __repr__(self) -> str:
        return f"<LedgerMapping {self._status} n={len(self._cache)}>"
