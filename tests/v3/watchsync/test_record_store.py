"""WatchSync V3 插件：观看记录自有表单测。

V3 把历史同步明细从插件数据目录里的裸 sqlite 文件迁移到插件自有表：

- 表名带 ``plugin_`` 前缀，避免与宿主或其他插件的表冲突；
- 按运行实例 ID 过滤，兼容虚拟分身共享同一份源码的场景；
- 建表只在 ``init_plugin`` 中按需执行，且必须可重复调用。

用例通过唯一实例 ID 隔离各自写入的行，因此可以安全共用宿主测试库。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from app.plugins.watchsync.models import WatchSyncRecord, WatchSyncRecordStore

# `list_records()` 返回给前端的明细字段，迁移前由裸 sqlite 查询拼装。
EXPECTED_RECORD_FIELDS = {
    "id",
    "timestamp",
    "source_server",
    "source_user",
    "target_server",
    "target_user",
    "media_name",
    "media_type",
    "sync_type",
    "status",
    "error_message",
    "created_at",
    "position_ticks",
}


def _unique_store() -> WatchSyncRecordStore:
    """用唯一实例 ID 构造访问器，避免与其他用例共享同一份行。"""
    WatchSyncRecordStore.ensure_table()
    return WatchSyncRecordStore(f"WatchSync-test-{uuid4().hex}")


def _add(
    store: WatchSyncRecordStore,
    *,
    status: str = "success",
    sync_type: str = "playback",
    source_user: str = "alice",
    target_user: str = "bob",
    media_name: str = "流浪地球",
    position_ticks: Optional[int] = 120,
    error_message: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> None:
    """写入一条同步明细，默认字段与旧接口形态保持一致。"""
    store.add_record(
        source_server="客厅Emby",
        source_user=source_user,
        target_server="卧室Emby",
        target_user=target_user,
        media_name=media_name,
        media_type="Movie",
        media_id="tmdb-111",
        position_ticks=position_ticks,
        sync_type=sync_type,
        status=status,
        error_message=error_message,
        created_at=created_at,
    )


def test_record_table_uses_plugin_prefixed_name_and_extend_existing() -> None:
    """表名带插件前缀，且复用元数据以兼容热重载与虚拟分身。"""
    assert WatchSyncRecord.__tablename__ == "plugin_watchsync_record"
    assert WatchSyncRecord.__table__.name == "plugin_watchsync_record"
    assert WatchSyncRecord.__table_args__ == {"extend_existing": True}


def test_record_table_indexes_instance_and_time_columns() -> None:
    """实例隔离列与按时间清理/统计的列都需要索引。"""
    table = WatchSyncRecord.__table__

    assert table.c.plugin_id.index is True
    assert table.c.plugin_id.nullable is False
    assert table.c.created_at.index is True
    assert table.c.created_at.nullable is False
    assert table.c.status.nullable is False


def test_ensure_table_is_a_staticmethod() -> None:
    """建表入口不依赖实例状态，避免模块导入期就建立数据库连接。"""
    assert isinstance(WatchSyncRecordStore.__dict__["ensure_table"], staticmethod)


def test_ensure_table_is_idempotent() -> None:
    """重复初始化不得报错（宿主热重载会再次执行）。"""
    WatchSyncRecordStore.ensure_table()
    WatchSyncRecordStore.ensure_table()


def test_record_store_falls_back_when_instance_id_is_blank() -> None:
    """实例 ID 缺省时回落到插件名，避免写入无法归属的数据。"""
    assert WatchSyncRecordStore("").plugin_id == "WatchSync"
    assert WatchSyncRecordStore("WatchSync_Clone").plugin_id == "WatchSync_Clone"


def test_records_round_trip_and_stay_isolated_per_instance() -> None:
    """明细可写可读，且按运行实例 ID 隔离。"""
    store = _unique_store()
    other = _unique_store()

    _add(store, media_name="流浪地球")
    _add(other, media_name="沙丘")

    page = store.list_records(limit=10, offset=0)
    assert page["total"] == 1

    record = page["records"][0]
    assert set(record) == EXPECTED_RECORD_FIELDS
    assert record["media_name"] == "流浪地球"
    assert record["status"] == "success"
    assert record["position_ticks"] == 120
    assert record["timestamp"] == record["created_at"]
    assert record["created_at"] != ""

    assert other.list_records(limit=10, offset=0)["total"] == 1


def test_list_records_pages_newest_first() -> None:
    """明细按 id 倒序分页，前端拿到的第一页是最新记录。"""
    store = _unique_store()
    _add(store, media_name="第一条")
    _add(store, media_name="第二条")
    _add(store, media_name="第三条")

    first_page = store.list_records(limit=2, offset=0)
    assert first_page["total"] == 3
    assert [row["media_name"] for row in first_page["records"]] == ["第三条", "第二条"]

    second_page = store.list_records(limit=2, offset=2)
    assert second_page["total"] == 3
    assert [row["media_name"] for row in second_page["records"]] == ["第一条"]


def test_summary_aggregates_status_today_and_sync_types() -> None:
    """统计字段与旧版 /stats 接口保持一致。"""
    store = _unique_store()
    _add(store, status="success", sync_type="playback",
         source_user="alice", target_user="bob")
    _add(store, status="error", sync_type="favorite",
         source_user="carol", target_user="dave", error_message="收藏同步失败")
    _add(store, status="success", sync_type="mark_played",
         source_user="eve", target_user="frank",
         created_at=datetime.now() - timedelta(days=40))

    summary = store.summary()
    assert summary["total_syncs"] == 3
    assert summary["success_syncs"] == 2
    assert summary["failed_syncs"] == 1
    assert summary["today_syncs"] == 2
    assert summary["sync_types"] == ["favorite", "mark_played", "playback"]
    # 近 24 小时活跃用户只统计 alice/bob/carol/dave，40 天前的记录不计入。
    assert summary["active_users"] == 4


def test_summary_is_empty_for_instance_without_records() -> None:
    """没有明细的实例统计全为零，避免前端出现空值。"""
    summary = _unique_store().summary()

    assert summary["total_syncs"] == 0
    assert summary["success_syncs"] == 0
    assert summary["failed_syncs"] == 0
    assert summary["today_syncs"] == 0
    assert summary["active_users"] == 0
    assert summary["sync_types"] == []


def test_purge_expired_only_removes_own_expired_rows() -> None:
    """清理只删除本实例中早于截止时间的明细。"""
    store = _unique_store()
    other = _unique_store()
    _add(store, media_name="过期记录", created_at=datetime.now() - timedelta(days=40))
    _add(store, media_name="近期记录")
    _add(other, media_name="他人过期记录", created_at=datetime.now() - timedelta(days=40))

    deleted = store.purge_expired(before=datetime.now() - timedelta(days=30))

    assert deleted == 1
    assert [row["media_name"] for row in store.list_records(limit=10, offset=0)["records"]] == [
        "近期记录"
    ]
    assert other.list_records(limit=10, offset=0)["total"] == 1


def test_record_fields_survive_optional_values() -> None:
    """可选字段缺省时写入空串或 None，读取端不需要额外兜底。"""
    store = _unique_store()
    _add(store, position_ticks=None, error_message=None)

    record: dict[str, Any] = store.list_records(limit=1, offset=0)["records"][0]
    assert record["position_ticks"] is None
    assert record["error_message"] is None
