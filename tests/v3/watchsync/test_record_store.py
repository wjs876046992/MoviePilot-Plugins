"""WatchSync V3 插件：观看记录自有表单测。

V3 把历史同步明细从插件数据目录里的裸 sqlite 文件迁移到插件自有表：

- 表名带 ``plugin_`` 前缀，避免与宿主或其他插件的表冲突；
- 按运行实例 ID 过滤，兼容虚拟分身共享同一份源码的场景；
- 建表只在 ``init_plugin`` 中按需执行，且必须可重复调用。

用例通过唯一实例 ID 隔离各自写入的行，因此可以安全共用宿主测试库。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.dialects import postgresql

from app.plugins.watchsync import WatchSync, models
from app.plugins.watchsync.models import (
    ERROR_MESSAGE_MAX_LENGTH,
    MEDIA_NAME_MAX_LENGTH,
    WatchSyncRecord,
    WatchSyncRecordStore,
    _plan_column_upgrades,
    clip_text,
)

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


# ---- position_ticks 溢出回归 ---------------------------------------------------------
# 线上报错：PostgreSQL 下 NumericValueOutOfRange（整数越界）。
# 原因：ticks 以 100ns 为单位，43.4 秒的位置就是 4.3e10，远超 32 位整型上限；
# 而 SQLite 的 INTEGER 按 64 位存储，所以本地怎么跑都不会暴露。
REPORTED_POSITION_TICKS = 43430000000
INT32_MAX = 2147483647


def test_position_ticks_column_is_64_bit() -> None:
    """播放位置必须按 64 位整型建列，否则 PostgreSQL 写入直接失败。"""
    column_type = WatchSyncRecord.__table__.c.position_ticks.type

    assert isinstance(column_type, BigInteger)
    # 线上报错的那个取值确实超出 32 位，用例本身也说明了为什么本地测不出来。
    assert REPORTED_POSITION_TICKS > INT32_MAX


def test_large_position_ticks_round_trip() -> None:
    """线上报错的取值必须能写入并原样读回。"""
    store = _unique_store()
    _add(store, position_ticks=REPORTED_POSITION_TICKS)

    record = store.list_records(limit=1, offset=0)["records"][0]
    assert record["position_ticks"] == REPORTED_POSITION_TICKS


def test_plugin_write_path_accepts_large_ticks_and_clips_text() -> None:
    """插件真实写入路径：既存得下大 ticks，也不会被超长文本拖垮整条记录。"""
    plugin = object.__new__(WatchSync)
    plugin._record_sync_result(
        source_server="BearFamily Emby",
        source_user="strm",
        target_server="BearFamily Emby",
        target_user="wjs",
        item_info={"Name": "第 12 集" * 500, "Type": "Episode", "Id": "95493"},
        position_ticks=REPORTED_POSITION_TICKS,
        status="error",
        error_message="E" * (ERROR_MESSAGE_MAX_LENGTH * 3),
    )

    record = WatchSyncRecordStore(WatchSync.__name__).list_records(
        limit=1, offset=0
    )["records"][0]
    assert record["position_ticks"] == REPORTED_POSITION_TICKS
    assert len(record["media_name"]) == MEDIA_NAME_MAX_LENGTH
    assert len(record["error_message"]) == ERROR_MESSAGE_MAX_LENGTH


def test_clip_text_keeps_short_values_and_truncates_long_ones() -> None:
    """截断只作用于超长文本，None 保持 None。"""
    assert clip_text("短文本", 8) == "短文本"
    assert clip_text(None, 8) is None
    assert clip_text("abcdefghij", 4) == "abcd"


def test_record_write_clips_text_to_declared_width() -> None:
    """超长媒体名与错误信息写入前截断，避免超出列宽。"""
    store = _unique_store()
    _add(
        store,
        media_name="长" * (MEDIA_NAME_MAX_LENGTH + 100),
        error_message="E" * (ERROR_MESSAGE_MAX_LENGTH + 100),
    )

    record = store.list_records(limit=1, offset=0)["records"][0]
    assert len(record["media_name"]) == MEDIA_NAME_MAX_LENGTH
    assert len(record["error_message"]) == ERROR_MESSAGE_MAX_LENGTH


def test_record_write_failure_never_breaks_the_sync_path() -> None:
    """明细落库失败只记日志。

    走到记录这一步时进度已经同步到目标服务器了，若把 DB 异常继续抛回 webhook 层，
    一次数据库抖动就会升级成「处理Webhook消息失败」。
    """
    plugin = object.__new__(WatchSync)
    attempts: list[dict[str, Any]] = []

    def _boom(**kwargs: Any) -> None:
        attempts.append(kwargs)
        raise RuntimeError("NumericValueOutOfRange")

    plugin._record_sync_result = _boom  # type: ignore[method-assign]

    plugin._record_sync_result_safely(
        source_server="BearFamily Emby",
        source_user="strm",
        target_server="BearFamily Emby",
        target_user="wjs",
        item_info={"Name": "第 12 集"},
        position_ticks=REPORTED_POSITION_TICKS,
        status="error",
    )

    # 确实调用了写入，只是异常被兜住。
    assert len(attempts) == 1


def test_sync_path_only_records_through_the_safe_wrapper() -> None:
    """同步路径不得直接调用会抛异常的写入函数。"""
    source = (
        Path(__file__).parents[3] / "plugins.v3" / "watchsync" / "__init__.py"
    ).read_text(encoding="utf-8")

    assert "def _record_sync_result(" in source
    assert "def _record_sync_result_safely(" in source
    # 唯一一次直接调用在安全包装内部；其余调用点必须走 *_safely，否则用例失败。
    assert source.count("self._record_sync_result(") == 1
    assert "self._record_sync_result(**kwargs)" in source


# ---- 历史窄列迁移 -------------------------------------------------------------------
# create(checkfirst=True) 只建缺失的表、不会修改已存在的表，所以先前版本建出来的
# 32 位列必须靠一次幂等的 ALTER 补齐，否则老库依旧写不进去。
LEGACY_UPGRADE_STATEMENTS = [
    "ALTER TABLE plugin_watchsync_record ALTER COLUMN position_ticks TYPE BIGINT",
    "ALTER TABLE plugin_watchsync_record ALTER COLUMN media_name TYPE VARCHAR(512)",
    "ALTER TABLE plugin_watchsync_record ALTER COLUMN error_message TYPE VARCHAR(1024)",
]


class _FakeInspector:
    """只实现迁移逻辑用到的那两个方法。"""

    def __init__(self, columns: Optional[dict[str, Any]]):
        self._columns = columns

    def get_table_names(self) -> list[str]:
        if self._columns is None:
            return []
        return [WatchSyncRecord.__tablename__]

    def get_columns(self, table_name: str) -> list[dict[str, Any]]:
        return list((self._columns or {}).values())


class _FakeConnection:
    """记录被执行的 DDL。"""

    def __init__(self, executed: list[str]):
        self._executed = executed

    def execute(self, statement: Any) -> None:
        self._executed.append(str(statement))

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


class _FakeEngine:
    """只提供迁移所需的 dialect / begin()，不需要真实数据库。"""

    def __init__(self, dialect: str = "postgresql"):
        self.dialect = SimpleNamespace(name=dialect)
        self.executed: list[str] = []
        self.begin_calls = 0

    def begin(self) -> _FakeConnection:
        self.begin_calls += 1
        return _FakeConnection(self.executed)


def _legacy_columns() -> dict[str, Any]:
    """模拟线上那张表：32 位 ticks + 偏窄的文本列。"""
    return {
        "position_ticks": {"name": "position_ticks", "type": postgresql.INTEGER()},
        "media_name": {"name": "media_name", "type": String(255)},
        "error_message": {"name": "error_message", "type": String(500)},
        "created_at": {"name": "created_at", "type": DateTime()},
    }


def test_plan_upgrades_legacy_ticks_and_narrow_text_columns() -> None:
    """历史窄列应被放宽到模型声明的类型与宽度。"""
    statements = _plan_column_upgrades("postgresql", _legacy_columns())

    assert statements == LEGACY_UPGRADE_STATEMENTS


def test_plan_is_noop_on_sqlite() -> None:
    """SQLite 的 INTEGER 本身 64 位、文本也不限长，无需迁移。"""
    assert _plan_column_upgrades("sqlite", _legacy_columns()) == []


def test_plan_skips_columns_that_are_already_wide() -> None:
    """生产库已是目标类型时不得重复下发 DDL（迁移必须可重复运行）。"""
    columns = {
        "position_ticks": {"name": "position_ticks", "type": BigInteger()},
        "media_name": {"name": "media_name", "type": String(MEDIA_NAME_MAX_LENGTH)},
        "error_message": {
            "name": "error_message",
            "type": String(ERROR_MESSAGE_MAX_LENGTH),
        },
    }

    assert _plan_column_upgrades("postgresql", columns) == []


def test_align_column_types_executes_ddl_for_legacy_table(monkeypatch) -> None:
    """对历史窄表执行迁移，DDL 在同一个事务里下发。"""
    engine = _FakeEngine()
    monkeypatch.setattr(models, "inspect", lambda _engine: _FakeInspector(_legacy_columns()))

    models._align_column_types(engine)

    assert engine.begin_calls == 1
    assert engine.executed == LEGACY_UPGRADE_STATEMENTS


def test_align_column_types_is_noop_when_table_missing(monkeypatch) -> None:
    """表还不存在时只由 create() 建表，不额外下发 DDL。"""
    engine = _FakeEngine()
    monkeypatch.setattr(models, "inspect", lambda _engine: _FakeInspector(None))

    models._align_column_types(engine)

    assert engine.begin_calls == 0
    assert engine.executed == []


def test_align_column_types_never_breaks_plugin_startup(monkeypatch) -> None:
    """结构读取失败只记日志；抛出异常会让插件完全无法初始化。"""
    engine = _FakeEngine()

    def _explode(_engine: Any) -> Any:
        raise RuntimeError("inspection unavailable")

    monkeypatch.setattr(models, "inspect", _explode)

    models._align_column_types(engine)

    assert engine.begin_calls == 0


def test_align_column_types_swallows_ddl_failure(monkeypatch) -> None:
    """DDL 失败（如权限不足）也不得中断启动，交由日志提示人工处理。"""
    engine = _FakeEngine()
    monkeypatch.setattr(models, "inspect", lambda _engine: _FakeInspector(_legacy_columns()))
    monkeypatch.setattr(
        engine,
        "begin",
        lambda: (_ for _ in ()).throw(RuntimeError("permission denied")),
    )

    models._align_column_types(engine)
