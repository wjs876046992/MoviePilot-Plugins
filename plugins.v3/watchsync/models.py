"""WatchSync 插件自有表定义与数据访问。

V3 把宿主数据访问收口到 Oper、Chain 和稳定 SDK，同时允许插件为「需要索引、
筛选或大量记录」的自有数据建立插件自有表。观看记录同步明细需要分页查询、按
日期清理和聚合统计，因此这里使用插件自有表，而不是把裸 sqlite 文件写进插件
数据目录。

会话统一由 ``db_query`` / ``db_update`` 创建、提交和释放，插件不持有裸会话工厂。
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    String,
    delete,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base, db_query, db_update
from app.sdk.logging import logger

# 文本列宽上限。集中在这里，避免模型声明与列类型迁移逻辑两处漂移。
MEDIA_NAME_MAX_LENGTH = 512
ERROR_MESSAGE_MAX_LENGTH = 1024

# 必须按 64 位整型存储的列。Emby 的 PositionTicks 以 100ns 为单位（2 小时影片
# 约 7.2e10），远超 32 位整型上限 2147483647；早期版本把 position_ticks 声明为
# Integer，在 PostgreSQL 下写入会直接抛 NumericValueOutOfRange（SQLite 的
# INTEGER 按 64 位存储，所以本地开发看不出来）。
_BIGINT_COLUMNS = ("position_ticks",)

# 文本列的期望宽度，用于把历史遗留的窄列放宽。
_TEXT_COLUMNS = {
    "media_name": MEDIA_NAME_MAX_LENGTH,
    "error_message": ERROR_MESSAGE_MAX_LENGTH,
}


def clip_text(value: Optional[str], limit: int) -> Optional[str]:
    """截断超长文本，避免单个字段超出列宽导致整条记录写入失败。"""
    if value is None:
        return None
    return value if len(value) <= limit else value[:limit]


class WatchSyncRecord(Base):
    """单条观看记录同步明细。"""

    __tablename__ = "plugin_watchsync_record"
    # V3 热重载和虚拟分身会重复执行模型声明，必须复用同一份表元数据。
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 运行实例 ID：虚拟分身共用同一份源码，靠该列隔离各自数据。
    plugin_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # 该列 NOT NULL，但并非每个写入方都会显式赋值，因此在这里给一个客户端默认值；
    # 否则 INSERT 会带上 created_at=None，在 PostgreSQL / SQLite 上都直接违反非空约束。
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True, default=datetime.now
    )
    source_server: Mapped[str] = mapped_column(String(255), nullable=False)
    source_user: Mapped[str] = mapped_column(String(255), nullable=False)
    target_server: Mapped[str] = mapped_column(String(255), nullable=False)
    target_user: Mapped[str] = mapped_column(String(255), nullable=False)
    media_name: Mapped[str] = mapped_column(
        String(MEDIA_NAME_MAX_LENGTH), nullable=False, default=""
    )
    media_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    media_id: Mapped[Optional[str]] = mapped_column(String(128))
    # 播放位置，单位 100ns：必须 64 位，取值上限见文件头部说明。
    position_ticks: Mapped[Optional[int]] = mapped_column(BigInteger)
    sync_type: Mapped[str] = mapped_column(String(32), nullable=False, default="playback")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(String(ERROR_MESSAGE_MAX_LENGTH))


class WatchSyncStat(Base):
    """按天聚合的同步统计，避免每次都全表扫描明细。"""

    __tablename__ = "plugin_watchsync_stat"
    # V3 热重载和虚拟分身会重复执行模型声明，必须复用同一份表元数据。
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 运行实例 ID：虚拟分身共用同一份源码，靠该列隔离各自数据。
    plugin_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    date: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    total_syncs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_syncs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_syncs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )


class WatchSyncRecordStore:
    """插件自有表的建表与数据访问封装。"""

    def __init__(self, plugin_id: str):
        """绑定当前运行实例 ID，用于隔离虚拟分身之间的数据。"""
        self._plugin_id = plugin_id or "WatchSync"

    @property
    def plugin_id(self) -> str:
        """返回当前运行实例 ID。"""
        return self._plugin_id

    @staticmethod
    def ensure_table() -> None:
        """仅创建本插件的两张数据表，并可重复调用。

        ``create(checkfirst=True)`` 只建缺失的表、不会修改已存在的表，所以建表后
        还要补一次幂等的列类型对齐，把早期版本留下的窄列就地放宽。
        """
        from app.db import Engine

        WatchSyncRecord.__table__.create(bind=Engine, checkfirst=True)
        WatchSyncStat.__table__.create(bind=Engine, checkfirst=True)
        _align_column_types(Engine)

    @db_update
    def add_record(
        self,
        db: Optional[Session] = None,
        *,
        source_server: str,
        source_user: str,
        target_server: str,
        target_user: str,
        media_name: str,
        media_type: str,
        media_id: Optional[str],
        position_ticks: Optional[int],
        sync_type: str,
        status: str,
        error_message: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> None:
        """写入一条同步明细，由更新装饰器提交或回滚事务。"""
        assert db is not None
        db.add(
            WatchSyncRecord(
                plugin_id=self._plugin_id,
                created_at=created_at or datetime.now(),
                source_server=source_server or "",
                source_user=source_user or "",
                target_server=target_server or "",
                target_user=target_user or "",
                media_name=clip_text(media_name or "", MEDIA_NAME_MAX_LENGTH),
                media_type=media_type or "",
                media_id=media_id,
                position_ticks=position_ticks,
                sync_type=sync_type or "playback",
                status=status or "error",
                error_message=clip_text(error_message, ERROR_MESSAGE_MAX_LENGTH),
            )
        )
        db.flush()

    @db_query
    def list_records(
        self, db: Optional[Session] = None, *, limit: int = 20, offset: int = 0
    ) -> Dict[str, Any]:
        """分页读取同步明细，并在会话释放前转换为普通字典。"""
        assert db is not None
        base_filter = WatchSyncRecord.plugin_id == self._plugin_id
        total = db.execute(
            select(func.count()).select_from(WatchSyncRecord).where(base_filter)
        ).scalar_one()
        rows = (
            db.execute(
                select(WatchSyncRecord)
                .where(base_filter)
                .order_by(WatchSyncRecord.id.desc())
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )
        records = [
            {
                "id": row.id,
                "timestamp": _isoformat(row.created_at),
                "source_server": row.source_server,
                "source_user": row.source_user,
                "target_server": row.target_server,
                "target_user": row.target_user,
                "media_name": row.media_name,
                "media_type": row.media_type,
                "sync_type": row.sync_type,
                "status": row.status,
                "error_message": row.error_message,
                "created_at": _isoformat(row.created_at),
                "position_ticks": row.position_ticks,
            }
            for row in rows
        ]
        return {"total": int(total or 0), "records": records}

    @db_query
    def summary(self, db: Optional[Session] = None) -> Dict[str, Any]:
        """聚合同步统计，字段与旧版 /stats 接口保持一致。"""
        assert db is not None
        base_filter = WatchSyncRecord.plugin_id == self._plugin_id
        total_syncs = db.execute(
            select(func.count()).select_from(WatchSyncRecord).where(base_filter)
        ).scalar_one()
        success_syncs = db.execute(
            select(func.count())
            .select_from(WatchSyncRecord)
            .where(base_filter, WatchSyncRecord.status == "success")
        ).scalar_one()
        today_start = datetime.combine(datetime.now().date(), time.min)
        today_syncs = db.execute(
            select(func.count())
            .select_from(WatchSyncRecord)
            .where(base_filter, WatchSyncRecord.created_at >= today_start)
        ).scalar_one()
        recent_rows = db.execute(
            select(WatchSyncRecord.source_user, WatchSyncRecord.target_user).where(
                base_filter,
                WatchSyncRecord.created_at >= datetime.now() - timedelta(hours=24),
            )
        ).all()
        active_users = {value for row in recent_rows for value in row if value}
        sync_types = {
            value
            for (value,) in db.execute(
                select(WatchSyncRecord.sync_type).where(base_filter).distinct()
            ).all()
            if value
        }
        return {
            "total_syncs": int(total_syncs or 0),
            "today_syncs": int(today_syncs or 0),
            "success_syncs": int(success_syncs or 0),
            "failed_syncs": int(total_syncs or 0) - int(success_syncs or 0),
            "active_users": len(active_users),
            "sync_types": sorted(sync_types),
        }

    @db_update
    def purge_expired(self, db: Optional[Session] = None, *, before: datetime) -> int:
        """删除指定时间之前的同步明细，返回实际删除条数。"""
        assert db is not None
        result = db.execute(
            delete(WatchSyncRecord).where(
                WatchSyncRecord.plugin_id == self._plugin_id,
                WatchSyncRecord.created_at < before,
            )
        )
        return int(result.rowcount or 0)


def _isoformat(value: Optional[datetime]) -> str:
    """把日期时间转换为 ISO 字符串，保持旧版接口的字符串形态。"""
    return value.isoformat() if value else ""


def _align_column_types(engine: Any) -> None:
    """把历史遗留的窄列就地放宽；任何失败都只记日志，不阻断插件启动。"""
    try:
        inspector = inspect(engine)
        if WatchSyncRecord.__tablename__ not in inspector.get_table_names():
            return
        columns = {
            column["name"]: column
            for column in inspector.get_columns(WatchSyncRecord.__tablename__)
        }
    except Exception as e:
        logger.warning(f"读取自有表结构失败，跳过列类型迁移: {str(e)}")
        return

    statements = _plan_column_upgrades(engine.dialect.name, columns)
    if not statements:
        return

    try:
        with engine.begin() as connection:
            for statement in statements:
                logger.info(f"迁移自有表列类型: {statement}")
                connection.execute(text(statement))
    except Exception as e:
        logger.error(
            f"自有表列类型迁移失败，播放进度可能无法写入；请手工执行 {statements}：{str(e)}"
        )


def _plan_column_upgrades(dialect: str, columns: Dict[str, Any]) -> List[str]:
    """推导把窄列放宽所需的 DDL；返回空列表表示无需迁移。

    只处理 PostgreSQL：它的 INTEGER 是 32 位整型，VARCHAR 也强制长度上限。
    SQLite 的 INTEGER 本身按 64 位存储、文本列不限制长度，无需迁移。
    """
    if dialect != "postgresql":
        return []

    statements: List[str] = []
    for name in _BIGINT_COLUMNS:
        column = columns.get(name)
        if column is not None and not isinstance(column["type"], BigInteger):
            statements.append(_alter_column_type(name, BigInteger()))
    for name, limit in _TEXT_COLUMNS.items():
        column = columns.get(name)
        if column is None:
            continue
        current_length = getattr(column["type"], "length", None)
        if current_length is not None and current_length < limit:
            statements.append(_alter_column_type(name, String(limit)))
    return statements


def _alter_column_type(column_name: str, column_type: Any) -> str:
    """生成 PostgreSQL 的列类型变更语句。"""
    from sqlalchemy.dialects import postgresql

    table = WatchSyncRecord.__table__
    table_name = table.fullname if table.schema else table.name
    target_type = column_type.compile(dialect=postgresql.dialect())
    return f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE {target_type}"
