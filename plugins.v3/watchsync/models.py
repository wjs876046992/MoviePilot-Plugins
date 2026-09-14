"""WatchSync 插件自有表定义与数据访问。

V3 把宿主数据访问收口到 Oper、Chain 和稳定 SDK，同时允许插件为「需要索引、
筛选或大量记录」的自有数据建立插件自有表。观看记录同步明细需要分页查询、按
日期清理和聚合统计，因此这里使用插件自有表，而不是把裸 sqlite 文件写进插件
数据目录。

会话统一由 ``db_query`` / ``db_update`` 创建、提交和释放，插件不持有裸会话工厂。
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, Integer, String, delete, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base, db_query, db_update


class WatchSyncRecord(Base):
    """单条观看记录同步明细。"""

    __tablename__ = "plugin_watchsync_record"
    # V3 热重载和虚拟分身会重复执行模型声明，必须复用同一份表元数据。
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 运行实例 ID：虚拟分身共用同一份源码，靠该列隔离各自数据。
    plugin_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    source_server: Mapped[str] = mapped_column(String(255), nullable=False)
    source_user: Mapped[str] = mapped_column(String(255), nullable=False)
    target_server: Mapped[str] = mapped_column(String(255), nullable=False)
    target_user: Mapped[str] = mapped_column(String(255), nullable=False)
    media_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    media_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    media_id: Mapped[Optional[str]] = mapped_column(String(128))
    position_ticks: Mapped[Optional[int]] = mapped_column(Integer)
    sync_type: Mapped[str] = mapped_column(String(32), nullable=False, default="playback")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(String(1024))


class WatchSyncRecordStore:
    """WatchSyncRecord 的建表与读写封装。"""

    def __init__(self, plugin_id: str):
        """绑定当前运行实例 ID，用于隔离虚拟分身之间的数据。"""
        self._plugin_id = plugin_id or "WatchSync"

    @property
    def plugin_id(self) -> str:
        """返回当前运行实例 ID。"""
        return self._plugin_id

    @staticmethod
    def ensure_table() -> None:
        """仅创建本插件的数据表，不触发宿主全部元数据建表。"""
        from app.db import Engine

        WatchSyncRecord.__table__.create(bind=Engine, checkfirst=True)

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
                media_name=media_name or "",
                media_type=media_type or "",
                media_id=media_id,
                position_ticks=position_ticks,
                sync_type=sync_type or "playback",
                status=status or "error",
                error_message=error_message,
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
