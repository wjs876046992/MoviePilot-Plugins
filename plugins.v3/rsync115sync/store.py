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
from collections.abc import MutableMapping
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

        ⚠️ 返回值是**布尔**，不是行数 —— 绝大多数调用方（`upsert` / `delete` /
        `set_field`）只关心"成没成"。需要行数的（如 `trim_events`）自己走
        `conn.total_changes`，见 `_write_count`。这个区别曾经害过一次：
        `trim_events` 直接转发了本函数的返回值，于是日志打出
        「事件流水已裁剪 **True** 条」—— 那句日志既无法读出信息，
        又掩盖了"到底裁没裁"这个唯一有用的信号。
        Boolean, not a row count: a caller that needs the count (see
        `_write_count`) must not forward this return value into a message.
        """
        try:
            with self._connect() as conn:
                conn.execute(sql, tuple(params))
            return True
        except Exception:
            return False

    def _write_count(self, sql: str, params: Iterable[Any] = ()) -> int:
        """
        像 `_write` 一样写，但返回**受影响行数**（失败返回 0）。

        Same as `_write` but returns how many rows changed (0 on failure).
        """
        try:
            with self._connect() as conn:
                before = conn.total_changes
                conn.execute(sql, tuple(params))
                return conn.total_changes - before
        except Exception:
            return 0

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
                    -- 疑似来源（watch / scan）。改造前放在
                    -- `_strm_suspects[key]["origin"]`：这条疑点是同步后观察判出来的、
                    -- 还是主动扫描扫出来的 —— 可信度不同，看板要显示。
                    origin           TEXT,
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
        # ⚠️ 只补**当前版本真正会写**的列。历史上有过一列 `dest`（云端可见性
        # 结论），它随那整套判定一起删了 —— 已经建过表的机器上那一列会留着，
        # 空着不碍事；这里不再补，免得新库上凭空多出一列没人写的字段。
        # Only columns the current build actually writes are added here.
        want = {"files": [("origin", "TEXT")]}
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
                                       origin, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        retry_count      = files.retry_count + ?,
                        updated_at       = excluded.updated_at
                    """,
                    (key, pair, rel_path, status, ingest_source, src_mtime, enqueued_at,
                     synced_at, verified_at, gen_requested_at, 0, last_error,
                     origin, now,
                     1 if bump_retry else 0),
                )
            return True
        except Exception:
            return False

    def set_field(self, key: str, field: str, value: Any) -> bool:
        """
        只改一行的某一个字段，**不动 status、不动其它字段**。

        Update a single column without touching the row's status or siblings.

        ⚠️ 存在的理由：`upsert` 的写语义是"插一行或整行更新"，而有些字段与
        status 是**正交**的 —— 补生成标记（`gen_requested_at`）就属于这一类：
        它描述"这个文件被请过补生成"，与"这个文件现在处于 candidate 还是
        pending_verify"毫无关系。用 `upsert` 去写它就必须连 status 一起写，
        而调用方（一个字典替身）压根不知道当前 status 是什么。
        Carrying status along would force the caller to know something it has no
        business knowing; this writes exactly one column.
        """
        return self._write(f"UPDATE files SET {field} = ? WHERE key = ?", (value, key))

    def clear_field(self, key: str, field: str) -> bool:
        """
        把一行的某个字段置为 **NULL**（与 `set_field(key, field, None)` 不同：
        后者在 `upsert` 的语义里是"不修改"，会静默地什么都不做）。

        ⚠️ 这个区别是有代价的教训：`upsert` 用 `COALESCE(excluded.x, files.x)`
        表达"没传的字段就别动"，于是**没有任何办法**通过它写入 NULL。
        清空一个正交字段（撤销"已补生成"标记）必须走这条路。
        NULL cannot be expressed through upsert's COALESCE semantics.
        """
        return self._write(f"UPDATE files SET {field} = NULL WHERE key = ?", (key,))

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

    def trim_events(self, keep_per_key: int = 20) -> int:
        """
        把每个 key 的事件流水裁到最近 `keep_per_key` 条，返回删掉的行数。

        Keep only the newest `keep_per_key` events per key.

        ⚠️ **为什么必须裁**：流水是只增不改的，而一个文件的"一生"里事件并不少
        —— 实机一轮就有 97 条（88 条登记观察 + 9 条入队）。长期运行下这张表会
        无限增长，且它**没有任何读取者**（`events_of` 目前只有测试在用），
        等于纯占磁盘。
        Bounded by design: the table is append-only and has no reader yet, so
        unbounded growth would be pure disk cost.

        按 key 而不是按总行数裁：某一天批量入队几千个文件把总量顶上去时，
        按总量裁会**把别的文件的记录一并挤掉** —— 而你想查的往往正是那个冷门的
        老文件。按 key 裁则每个文件都保留着最近的那几条。
        Per-key rather than global: a bulk day would otherwise evict other files'
        history, and the file you want to inspect is usually the rare old one.

        失败返回 0、只记日志不抛：清理是维护动作，不该中断插件加载。
        """
        # ① 无主事件：台账行已经不在（同步成功后出队是最常见的路径）。
        # ⚠️ 只按 key 裁是**不够**的 —— 每个成功同步的文件都会给它的 key 留下
        # 若干条事件，随后那一行被删掉，事件却留了下来：日积月累是无上限的。
        # 规则一句话：**事件的生命周期跟随台账行**。行没了，它的历史就没有
        # 锚点也没有读者（`events_of` 是按 key 查的，而没有任何地方会去枚举
        # 已离场的 key）。
        # Orphans are the unbounded part: per-key trimming cannot see rows whose
        # ledger entry is gone, and every successful sync leaves one behind.
        removed = self._write_count(
            "DELETE FROM events WHERE key NOT IN (SELECT key FROM files)")
        # ② 每个仍在跟踪的文件保留最近 N 条
        removed += self._write_count(
            "DELETE FROM events WHERE id NOT IN ("
            "  SELECT id FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY key ORDER BY at DESC, id DESC) AS rn"
            "    FROM events) WHERE rn <= ?)",
            (int(keep_per_key),),
        )
        return removed

    def events_of(self, key: str, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self._query(
            "SELECT * FROM events WHERE key = ? ORDER BY at DESC LIMIT ?", (key, limit))
        return [dict(r) for r in rows]


# ==========================================================================
# 台账支持的「字典替身」：以 SQLite 为真相源、对外仍是 dict 接口
# ==========================================================================

class LedgerFieldMap(MutableMapping):
    """
    把一个**台账字段**暴露成 dict 接口 —— 与 `LedgerMapping` 同一手法，
    只是它对应的不是某个 status，而是某一列。

    Expose a single ledger *column* as a dict-like view.

    ## 它为什么必须存在

    台账里有两类状态：

      · **与 status 一一对应**的（冷却队列 = candidate、观察期 = pending_verify、
        待处理 = suspect）—— 用 `LedgerMapping` 一个替身顶一个队列；
      · **与 status 正交**的（`gen_requested_at`：这个文件被请过补生成）——
        一个文件既可能在 candidate 也可能在 pending_verify，同时又是"补生成过"的。

    第二类如果硬塞进某个 status 替身，就必须先知道"它现在是什么 status"，
    而调用方（`_strm_gen_requested.pop(key)` 这种）只知道 key。做成独立的一列视图，
    调用点依旧一行不用改。

    ⚠️ 它**不做插入**：`self[k] = ts` 只更新已存在的行。若 key 不在台账里，
    写会被静默跳过 —— 这是对的，因为"给一个台账里没有的文件打补生成标记"
    在语义上没有意义（那个文件已经不受跟踪了），凭空 INSERT 会造出一行
    没有 status 的幽灵记录。
    Zero status: this view never inserts, so a write for a key the ledger no longer
    tracks is a no-op instead of a ghost row.
    """

    def __init__(self, ledger: "Store", field: str):
        self._ledger = ledger
        self._field = field
        self._cache: Dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        self._cache = {}
        if self._ledger is None or not getattr(self._ledger, "usable", False):
            return
        for row in self._ledger._query(
                f"SELECT key, {self._field} AS v FROM files WHERE {self._field} IS NOT NULL"):
            try:
                self._cache[str(row["key"])] = float(row["v"])
            except (TypeError, ValueError):
                continue

    def reload(self) -> None:
        self._load()

    # ---- MutableMapping ------------------------------------------------
    def __getitem__(self, key: str) -> float:
        return self._cache[key]

    def __setitem__(self, key: str, value: Any) -> None:
        try:
            ts = float(value)
        except (TypeError, ValueError):
            return
        self._cache[key] = ts
        if self._ledger is not None:
            self._ledger.set_field(key, self._field, ts)

    def __delitem__(self, key: str) -> None:
        self._cache.pop(key, None)
        if self._ledger is not None:
            self._ledger.clear_field(key, self._field)

    def pop(self, key, *args):
        """与 `LedgerMapping.pop` 同一理由：`q.pop(k, None)` 必须不抛异常。"""
        if key in self._cache:
            value = self._cache.pop(key)
            if self._ledger is not None:
                self._ledger.clear_field(key, self._field)
            return value
        if args:
            return args[0]
        raise KeyError(key)

    def setdefault(self, key, default=None):
        if key in self._cache:
            return self._cache[key]
        self[key] = default
        return default

    def clear(self) -> None:
        for key in list(self._cache):
            if self._ledger is not None:
                self._ledger.clear_field(key, self._field)
        self._cache.clear()

    def update(self, other=(), **kwargs) -> None:      # type: ignore[override]
        items = dict(other, **kwargs) if other else dict(**kwargs)
        for k, v in items.items():
            self[k] = v

    def keys(self):
        return self._cache.keys()

    def values(self):
        return self._cache.values()

    def items(self):
        return self._cache.items()

    def get(self, key, default=None):
        return self._cache.get(key, default)

    def __iter__(self):
        return iter(self._cache)

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, key: object) -> bool:
        return key in self._cache

    def __repr__(self) -> str:
        return f"<LedgerFieldMap {self._field} n={len(self._cache)}>"





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
                 extra_from_value: Optional[Dict[str, str]] = None,
                 events: Optional[Dict[str, str]] = None):
        """
        :param ledger: 台账
        :param status: 本替身对应的 status 取值（candidate / pending_verify / ...）
        :param ts_field: `self[k] = <标量>` 时，那个标量写进哪个时间字段
        :param extra_from_value: `self[k] = {..}` 时，字典的哪些键映射到台账字段
            （未列出的键会被忽略 —— 台账是强 schema，不能让调用方塞任意字段）
        :param events: `{值里的键名: 事件 action}` —— 写入时附带记一条事件流水。
            见下方「为什么事件记在这一层」。
        """
        self._ledger = ledger
        self._status = status
        self._ts_field = ts_field
        self._extra = dict(extra_from_value or {})
        self._events = dict(events or {})
        self._cache: Dict[str, Any] = {}
        self._load()

    def _note(self, key: str, value: Any) -> None:
        """
        按 `events` 映射记一条事件流水。

        ⚠️ **为什么事件记在这一层，而不是在几十个业务调用点各加一行**：
        `events` 表建了却没有人写，就是一张**空表** —— 它占着"这个文件经历过什么
        可以查"的承诺，而查出来永远是空。而逐个业务点去加 `log_event`，等于把
        "什么算一个状态变更"的判断复制到几十处，迟早漂移成一半写一半不写
        （比完全没写更糟：那时你会相信它）。
        记在这里的好处是**它不可能漂移** —— 所有状态变更都必须经过本类的
        `__setitem__`，而本类是那些状态的唯一入口。

        Why here and not at each business call site: the events table was created but
        never written, and scattering log_event across dozens of call sites would let
        "what counts as a transition" drift into half-covered, which is worse than none.
        Every mutation must pass through this class, so this cannot drift.
        """
        if not self._events or self._ledger is None:
            return
        action = self._events.get(self._event_key_of(value))
        if action:
            self._ledger.log_event(key, action)

    def _event_key_of(self, value: Any) -> str:
        """把写入的值换算成 `events` 映射的键（标量一律算作"入队"）。"""
        if isinstance(value, dict):
            for name in self._events:
                if name in value:
                    return name
            return ""
        # 裸标量：`_ts_field` 就是它的语义（`_pending_queue[k] = ts` → 入队）
        return self._ts_field if self._ts_field in self._events else ""

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
        `entry.get("origin")`、`entry.get("ts")` 等，形状不对就是
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
        self._note(key, value)
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
        existed = key in self._cache
        self._cache.pop(key, None)
        if existed and self._events and self._ledger is not None:
            # 离场也记一条，并把**从哪个队列走的**写进 detail。
            #
            # ⚠️ 它答不出"为什么走"（同步成功 / 被忽略 / 源端已删走的是同一个
            # 出口）—— 那是调用方的语义，不是替身能知道的。它给出的是"什么时候
            # 走的、从哪个队列"，配上前后两条日志里的原因就能串起来。
            #
            # ⚠️ **可见窗口是"到下次插件加载为止"**：`trim_events` 会删掉台账行
            # 已经不存在的事件（那正是大多数离场事件的下场）。这不是缺陷 ——
            # 你要查"它怎么不见了"的时刻，恰恰是刚跑完一轮、还在看台账的时候；
            # 而保留它到永远等于给每个同步成功的文件永久记账。
            # The reason lives in the caller; the timestamp is recorded here so the
            # timeline has no hole, and the surrounding log lines supply the why.
            # Lifetime: this survives until the next plugin load (see trim_events).
            self._ledger.log_event(key, "dequeue", self._status)
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
            if self._events and self._ledger is not None:
                self._ledger.log_event(key, "dequeue", self._status)
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
