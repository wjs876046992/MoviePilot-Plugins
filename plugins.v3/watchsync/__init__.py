import json
import traceback
import hashlib
import time
import random
import threading
import re
from datetime import datetime, timedelta, timezone
from typing import Any, List, Dict, Tuple, Optional
from functools import wraps
from collections import defaultdict
import os
from urllib.parse import quote
import httpx2

import warnings
from sqlalchemy import String, Integer, DateTime, select, func, delete, desc
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.db import Base, db_query, db_update, Engine
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.plugins import _PluginBase
from app.schemas import WebhookEventInfo
from app.schemas.types import EventType
from app.sdk.config import settings
from apscheduler.triggers.interval import IntervalTrigger


# 忽略插件重载时因为重复注册同名模型（Declarative Base 类型覆盖）产生的 SAWarning
with warnings.catch_warnings():
    warnings.simplefilter("ignore", category=sa_exc.SAWarning)

    # 强制清理内存中的旧表结构定义，防止 extend_existing=True 把已被删除的 timestamp “幽灵”字段重新带回来
    if "plugin_watchsync_record" in Base.metadata.tables:
        Base.metadata.remove(Base.metadata.tables["plugin_watchsync_record"])
    if "plugin_watchsync_stat" in Base.metadata.tables:
        Base.metadata.remove(Base.metadata.tables["plugin_watchsync_stat"])

    class WatchSyncRecord(Base):
        __tablename__ = "plugin_watchsync_record"
        __table_args__ = {"extend_existing": True}

        id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
        plugin_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
        source_server: Mapped[str] = mapped_column(String(100), nullable=False)
        source_user: Mapped[str] = mapped_column(String(100), nullable=False)
        target_server: Mapped[str] = mapped_column(String(100), nullable=False)
        target_user: Mapped[str] = mapped_column(String(100), nullable=False)
        media_name: Mapped[str] = mapped_column(String(255), nullable=False)
        media_type: Mapped[str] = mapped_column(String(50), nullable=False)
        media_id: Mapped[str] = mapped_column(String(100), nullable=True)
        position_ticks: Mapped[int] = mapped_column(Integer, nullable=True)
        sync_type: Mapped[str] = mapped_column(String(50), default='playback')
        status: Mapped[str] = mapped_column(String(50), nullable=False)
        error_message: Mapped[str] = mapped_column(String(500), nullable=True)
        created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


    class WatchSyncStat(Base):
        __tablename__ = "plugin_watchsync_stat"
        __table_args__ = {"extend_existing": True}

        id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
        plugin_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
        date: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
        total_syncs: Mapped[int] = mapped_column(Integer, default=0)
        success_syncs: Mapped[int] = mapped_column(Integer, default=0)
        failed_syncs: Mapped[int] = mapped_column(Integer, default=0)
        updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class SyncLoopProtector:
    """防循环同步装置"""
    def __init__(self, ttl_seconds: int = 15):
        self._cache: Dict[Tuple[str, str, str], datetime] = {}
        self._ttl = timedelta(seconds=ttl_seconds)
        self._lock = threading.Lock()

    def add(self, user_name: str, item_id: str, sync_type: str):
        if not all([user_name, item_id, sync_type]):
            return
        with self._lock:
            cache_key = (user_name, item_id, sync_type)
            self._cache[cache_key] = datetime.now()
            self._cleanup_nolock()

    def is_protected(self, user_name: str, item_id: str, sync_type: str) -> bool:
        if not all([user_name, item_id, sync_type]):
            return False
        with self._lock:
            cache_key = (user_name, item_id, sync_type)
            if cache_key in self._cache:
                event_time = self._cache[cache_key]
                if datetime.now() - event_time < self._ttl:
                    return True
        return False

    def _cleanup_nolock(self):
        now = datetime.now()
        expired_keys = [
            key for key, timestamp in self._cache.items() if now - timestamp > self._ttl]
        for key in expired_keys:
            try:
                del self._cache[key]
            except KeyError:
                pass


def retry_on_failure(max_retries=3, base_delay=1, max_delay=60, backoff_factor=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    if result:
                        return result
                    elif attempt == max_retries:
                        return False
                except Exception as e:
                    last_exception = e
                    if attempt == max_retries:
                        raise e
                delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                jitter = random.uniform(0, delay * 0.1)
                time.sleep(delay + jitter)
            return False
        return wrapper
    return decorator


class LocalZSpaceInstance:
    _is_watchsync_zspace = True

    def __init__(self, name: str, host: str, token: str, user_id: str, username: str):
        self.name = name or "极影视"
        self._host = self._standardize_host(host)
        self._apikey = token
        self.user = user_id
        self._username = username or user_id

    @staticmethod
    def _standardize_host(host: str) -> str:
        host = (host or "").strip()
        if not host.endswith("/"):
            host += "/"
        return host

    def get_user(self, user_name: Optional[str] = None) -> Optional[str]:
        if not user_name or user_name in (self._username, self.user, self.name):
            return self.user
        return None


class WatchSync(_PluginBase):
    plugin_name = "Emby观看记录同步"
    plugin_desc = "在不同用户之间同步观看记录（自用插件，不保证兼容性）"
    plugin_icon = "https://raw.githubusercontent.com/DzAvril/MoviePilot-Plugins/main/icons/emby_watch_sync.png"
    plugin_version = "3.0.1"
    plugin_author = "DzAvril"
    author_url = "https://github.com/DzAvril"
    plugin_config_prefix = "watchsync_"
    plugin_order = 20
    auth_level = 2

    def __init__(self):
        super().__init__()
        self._enabled = False
        self._sync_groups = []
        self._sync_movies = True
        self._sync_tv = True
        self._sync_favorite = True
        self._sync_played = True
        self._min_watch_time = 300
        self._emby_instances = {}
        self._zspace_instances = {}
        self._server_types = {}
        self._zspace_poll_enabled = True
        self._zspace_poll_interval = 30
        self._zspace_poll_limit = 20
        self._zspace_poll_bootstrap_recent_minutes = 120
        self._zspace_poll_state = {}
        self._zspace_poll_lock = threading.RLock()
        
        self._event_timestamps = {}
        self._sync_metrics = {
            'total_events': 0,
            'successful_syncs': 0,
            'failed_syncs': 0,
            'duplicate_events': 0,
            'api_errors': defaultdict(int),
            'last_sync_time': None
        }
        self._sync_lock = threading.RLock()
        self._active_syncs = {}
        self._max_concurrent_syncs = 3
        self._loop_protector = SyncLoopProtector(ttl_seconds=30)

    @staticmethod
    def ensure_table() -> None:
        WatchSyncRecord.__table__.create(bind=Engine, checkfirst=True)
        WatchSyncStat.__table__.create(bind=Engine, checkfirst=True)

    def init_plugin(self, config: dict = None):
        self.ensure_table()
        
        if config:
            self._enabled = config.get("enabled", False)
            self._sync_groups = config.get("sync_groups", [])
            self._sync_movies = config.get("sync_movies", True)
            self._sync_tv = config.get("sync_tv", True)
            self._sync_favorite = config.get("sync_favorite", True)
            self._sync_played = config.get("sync_played", True)
            self._min_watch_time = config.get("min_watch_time", 300)
            self._zspace_poll_enabled = config.get("zspace_poll_enabled", True)
            self._zspace_poll_interval = self._coerce_int(
                config.get("zspace_poll_interval", 30), 30, 10)
            self._zspace_poll_limit = self._coerce_int(
                config.get("zspace_poll_limit", 20), 20, 1)
            self._zspace_poll_bootstrap_recent_minutes = self._coerce_int(
                config.get("zspace_poll_bootstrap_recent_minutes", 120), 120, 0)
            
        self._load_emby_instances()

    def get_service(self) -> list[dict]:
        if not self.get_state() or not self._zspace_poll_enabled:
            return []
        if not self._has_zspace_poll_source_users():
            return []
            
        return [
            {
                "id": f"{self.__class__.__name__}.ZSpaceProgressPoll",
                "name": "极影视观看进度轮询",
                "trigger": IntervalTrigger(seconds=self._zspace_poll_interval),
                "func": self.poll_zspace_watch_progress,
                "kwargs": {},
            }
        ]

    def _emby_request(self, instance, method: str, url: str, **kwargs):
        """完全独立的 HTTP 通讯代理，不再依赖易碎的后端内部兼容层实现"""
        host = getattr(instance, "_host", getattr(instance, "host", "")) or ""
        apikey = getattr(instance, "_apikey", getattr(instance, "api_key", getattr(instance, "token", ""))) or ""
        
        if host and not host.endswith("/"):
            host += "/"
            
        actual_url = url.replace("[HOST]", host).replace("[APIKEY]", apikey)
        if hasattr(instance, "user"):
            actual_url = actual_url.replace("[USER]", getattr(instance, "user", None) or "")
            
        headers = kwargs.get("headers", {})
        if self._is_zspace_instance(instance):
            headers["X-Emby-Token"] = apikey
            headers["X-Emby-Authorization"] = f"MediaBrowser Token={apikey}"
        
        json_data = kwargs.get("json")
        data_data = kwargs.get("data")
        
        try:
            if method == "get":
                return httpx2.get(actual_url, headers=headers, timeout=15)
            elif method == "post":
                if json_data is not None:
                    return httpx2.post(actual_url, headers=headers, json=json_data, timeout=15)
                elif data_data is not None:
                    return httpx2.post(actual_url, headers=headers, content=data_data, timeout=15)
                else:
                    return httpx2.post(actual_url, headers=headers, timeout=15)
            elif method == "delete":
                return httpx2.delete(actual_url, headers=headers, timeout=15)
        except Exception as e:
            logger.error(f"WatchSync HTTP请求出错 ({method} {actual_url[:100]}...)：{e}")
            
        # 安全的回退调用原生方法
        if not isinstance(instance, LocalZSpaceInstance) and hasattr(instance, f"{method}_data"):
            try:
                return getattr(instance, f"{method}_data")(actual_url, **kwargs)
            except Exception:
                pass
        return None

    @staticmethod
    def _coerce_int(value, default: int, min_value: int) -> int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = default
        return max(value, min_value)

    def _generate_event_fingerprint(self, event_data: WebhookEventInfo) -> str:
        json_obj = event_data.json_object
        user_id = json_obj.get("User", {}).get("Id", "")
        item_id = json_obj.get("Item", {}).get("Id", "")
        session_id = json_obj.get("Session", {}).get("Id", "")
        position_ticks = (json_obj.get("Session", {}).get("PositionTicks", 0) or
                          json_obj.get("PlaybackInfo", {}).get("PositionTicks", 0))
        position_rounded = (position_ticks // 100000000) * 100000000
        fingerprint_data = (f"{event_data.channel}_{event_data.event}_"
                            f"{user_id}_{item_id}_{session_id}_{position_rounded}")
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()

    def _is_duplicate_event(self, event_fingerprint: str, time_window_seconds: int = 30) -> bool:
        current_time = datetime.now()
        cutoff_time = current_time - timedelta(seconds=time_window_seconds * 2)
        
        expired_events = [fp for fp, timestamp in self._event_timestamps.items() if timestamp < cutoff_time]
        for fp in expired_events:
            del self._event_timestamps[fp]

        if event_fingerprint in self._event_timestamps:
            last_time = self._event_timestamps[event_fingerprint]
            if current_time - last_time < timedelta(seconds=time_window_seconds):
                return True
                
        self._event_timestamps[event_fingerprint] = current_time
        return False

    def _is_event_a_sync_loop(self, event_data: WebhookEventInfo) -> bool:
        try:
            json_obj = event_data.json_object
            user_name = json_obj.get("User", {}).get("Name")
            item_id = json_obj.get("Item", {}).get("Id")
            sync_type = self._get_sync_type_from_event(event_data)

            if not all([user_name, item_id, sync_type]):
                return False

            return self._loop_protector.is_protected(user_name, item_id, sync_type)
        except Exception:
            return False

    def _get_sync_type_from_event(self, event_data: WebhookEventInfo) -> Optional[str]:
        json_obj = event_data.json_object
        event_type = event_data.event
        
        if event_type in ["playback.pause", "playback.stop"]:
            return "playback"
        elif event_type in ["user.favorite", "item.favorite", "item.rate"]:
            is_fav = json_obj.get("Item", {}).get("UserData", {}).get("IsFavorite", False)
            return "favorite" if is_fav else "not_favorite"
        elif event_type in ["item.markplayed", "playback.scrobble"]:
            return "mark_played"
        elif event_type == "item.markunplayed":
            return "mark_unplayed"
        return None

    def _update_sync_metrics(self, event_type: str, success: bool = True, error_type: str = None):
        if event_type == 'event_received':
            self._sync_metrics['total_events'] += 1
        elif event_type == 'sync_completed':
            if success:
                self._sync_metrics['successful_syncs'] += 1
                self._sync_metrics['last_sync_time'] = datetime.now()
            else:
                self._sync_metrics['failed_syncs'] += 1
        elif event_type == 'duplicate_event':
            self._sync_metrics['duplicate_events'] += 1
        elif event_type == 'api_error' and error_type:
            self._sync_metrics['api_errors'][error_type] += 1

    def get_state(self) -> bool:
        return self._enabled

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        return [{"key": "watchsync", "name": "观看记录同步"}]

    def get_dashboard(self, key: str = "", **kwargs):
        return (
            {"cols": 12, "md": 6},
            {
                "refresh": 30,
                "border": True,
                "title": "观看记录同步",
                "subtitle": "在不同用户之间同步观看记录和收藏状态",
                "render_mode": "vue",
            },
            None,
        )
        
    @staticmethod
    def _get_running_modules() -> dict:
        try:
            from app.sdk.plugins import module_manager
            if hasattr(module_manager, '_running_modules'):
                return module_manager._running_modules
        except Exception:
            pass
        try:
            from app.sdk.plugins import ModuleManager
            return getattr(ModuleManager(), '_running_modules', {})
        except Exception:
            pass
        try:
            from app.core.module import ModuleManager
            return getattr(ModuleManager(), '_running_modules', {})
        except Exception:
            pass
        return {}

    def _load_emby_instances(self):
        self._emby_instances = {}
        self._zspace_instances = {}
        self._server_types = {}

        running_modules = self._get_running_modules()

        emby_module = running_modules.get("EmbyModule")
        if emby_module and hasattr(emby_module, 'get_instances'):
            for name, instance in emby_module.get_instances().items():
                self._emby_instances[name] = instance
                self._server_types[name] = "emby"

        zspace_module = running_modules.get("ZSpaceModule")
        if zspace_module and hasattr(zspace_module, 'get_instances'):
            for name, instance in zspace_module.get_instances().items():
                self._emby_instances[name] = instance
                self._zspace_instances[name] = instance
                self._server_types[name] = "zspace"

        local_zspace = self._load_local_zspace_instance()
        if local_zspace:
            name, instance = local_zspace
            if name not in self._emby_instances:
                self._emby_instances[name] = instance
                self._zspace_instances[name] = instance
                self._server_types[name] = "zspace"

    def _load_local_zspace_instance(self) -> Optional[Tuple[str, LocalZSpaceInstance]]:
        import sqlite3
        db_path = os.environ.get("WATCHSYNC_ZSPACE_DB", "/zvideo/zvideo.db")
        if not os.path.exists(db_path):
            return None

        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                media = conn.execute("SELECT media_uid, media_uname, user_name FROM zvideo_media LIMIT 1").fetchone()
                if not media:
                    return None
                token_row = conn.execute(
                    "SELECT token FROM zvideo_media_token WHERE media_uid=? ORDER BY updated DESC LIMIT 1",
                    (media["media_uid"],)
                ).fetchone()
                if not token_row or not token_row["token"]:
                    return None
        except Exception:
            return None

        hosts = [
            os.environ.get("WATCHSYNC_ZSPACE_HOST"),
            os.environ.get("ZSPACE_EMBY_HOST"),
            "http://127.0.0.1:8021/",
            "http://172.17.0.1:8021/",
        ]
        
        user_id = media["media_uid"]
        username = media["media_uname"] or media["user_name"] or user_id
        token = token_row["token"]

        for host in [h for h in hosts if h]:
            instance = LocalZSpaceInstance("极影视", host, token, user_id, username)
            try:
                response = self._emby_request(instance, "get", "[HOST]emby/System/Info")
                if response and response.status_code == 200:
                    server_info = response.json() or {}
                    return server_info.get("ServerName") or "极影视", instance
            except:
                pass
        return None

    def poll_zspace_watch_progress(self):
        if not self._enabled or not self._zspace_poll_enabled:
            return
        if not self._zspace_poll_lock.acquire(blocking=False):
            return
        try:
            for server_name, zspace_instance in list(self._zspace_instances.items()):
                self._poll_zspace_instance(server_name, zspace_instance)
        finally:
            self._zspace_poll_lock.release()

    def _poll_zspace_instance(self, server_name: str, zspace_instance):
        source_users = self._get_zspace_poll_source_users(server_name)
        for source_user in source_users:
            user_id = zspace_instance.get_user(source_user) if hasattr(zspace_instance, "get_user") else None
            if not user_id:
                continue

            items = self._fetch_zspace_resume_items(zspace_instance, user_id)
            for item in items:
                position_ticks = self._get_resume_position_ticks(item)
                if not self._should_sync_zspace_resume_item(server_name, source_user, item, position_ticks):
                    continue
                if self._loop_protector.is_protected(source_user, item.get("Id"), "playback"):
                    continue
                self._sync_to_group_users(server_name, source_user, item, position_ticks)

    def _get_zspace_poll_source_users(self, server_name: str) -> List[str]:
        users = []
        for group in self._sync_groups:
            if not group.get("enabled", True):
                continue
            for user in group.get("users", []):
                username = user.get("username")
                actual_server = self._get_actual_server_name(user.get("server"))
                if username and actual_server == server_name and self._get_server_type(actual_server) == "zspace" and username not in users:
                    users.append(username)
        return users

    def _has_zspace_poll_source_users(self) -> bool:
        return any(self._get_zspace_poll_source_users(s) for s in self._zspace_instances.keys())

    def _fetch_zspace_resume_items(self, zspace_instance, user_id: str) -> List[dict]:
        url = (
            f"[HOST]emby/Users/{user_id}/Items/Resume?api_key=[APIKEY]"
            f"&Recursive=true&MediaTypes=Video&Limit={self._zspace_poll_limit}"
            f"&Fields=ProviderIds,Path,SeriesName,ParentIndexNumber,IndexNumber,"
            f"RunTimeTicks,UserData,DateCreated,ProductionYear"
        )
        response = self._emby_request(zspace_instance, "get", url)
        if not response or response.status_code != 200:
            return []
        
        payload = response.json()
        if isinstance(payload, dict):
            return payload.get("Items", [])
        if isinstance(payload, list):
            return payload
        return []

    def _should_sync_zspace_resume_item(self, server_name: str, source_user: str, item: dict, position_ticks: int) -> bool:
        item_id = item.get("Id")
        if not item_id or not position_ticks or position_ticks < self._min_watch_time * 10000000:
            return False

        user_data = item.get("UserData") or {}
        last_played = self._parse_zspace_datetime(user_data.get("LastPlayedDate") or item.get("LastPlayedDate"))
        signature = self._zspace_resume_signature(item, position_ticks)
        state_key = f"{server_name}:{source_user}:{item_id}"
        previous_signature = self._zspace_poll_state.get(state_key)
        
        if previous_signature == signature:
            return False

        self._zspace_poll_state[state_key] = signature
        if previous_signature is None and not self._is_recent_zspace_resume(last_played):
            return False
            
        return True

    @staticmethod
    def _get_resume_position_ticks(item: dict) -> int:
        value = (item.get("UserData") or {}).get("PlaybackPositionTicks") or item.get("PlaybackPositionTicks") or 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _zspace_resume_signature(item: dict, position_ticks: int) -> str:
        user_data = item.get("UserData") or {}
        last_played = user_data.get("LastPlayedDate") or item.get("LastPlayedDate") or ""
        return f"{position_ticks}:{last_played}:{user_data.get('Played')}"

    @staticmethod
    def _parse_zspace_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value: return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    def _is_recent_zspace_resume(self, last_played: Optional[datetime]) -> bool:
        if self._zspace_poll_bootstrap_recent_minutes <= 0:
            return True
        if not last_played:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self._zspace_poll_bootstrap_recent_minutes)
        return last_played >= cutoff

    @eventmanager.register(EventType.WebhookMessage)
    def handle_webhook_message(self, event: Event):
        self._update_sync_metrics('event_received')
        if not self._enabled or not event or not event.event_data:
            return

        if self._is_event_a_sync_loop(event.event_data):
            self._update_sync_metrics('duplicate_events')
            return

        event_fingerprint = self._generate_event_fingerprint(event.event_data)
        if self._is_duplicate_event(event_fingerprint):
            self._update_sync_metrics('duplicate_event')
            return

        try:
            event_data = event.event_data
            if getattr(event_data, 'channel', '') not in ["emby", "zspace"]:
                return

            supported_events = [
                "playback.pause", "playback.stop",
                "playback.scrobble",
                "user.favorite", "item.favorite",
                "item.rate", "library.new", "library.update",
                "item.markplayed", "item.markunplayed"
            ]

            if getattr(event_data, 'event', '') not in supported_events:
                return

            webhook_data = {
                "channel": event_data.channel,
                "event": event_data.event,
                "server_name": event_data.server_name,
                "json_object": event_data.json_object
            }

            evt = getattr(event_data, "event", "")
            if evt in ["playback.pause", "playback.stop"]:
                self._handle_playback_event(webhook_data)
            elif evt in ["user.favorite", "item.favorite", "item.rate", "library.new", "library.update"]:
                self._handle_favorite_event(webhook_data)
            elif evt in ["playback.scrobble", "item.markplayed", "item.markunplayed"]:
                self._handle_played_status_event(webhook_data)

        except Exception as e:
            logger.error(f"处理Webhook消息失败: {e}")

    def _handle_favorite_event(self, webhook_data):
        if not self._sync_favorite: return
        json_object = webhook_data.get("json_object", {})
        if not json_object: return

        server_name = webhook_data.get("server_name") or json_object.get("Server", {}).get("Name") or self._default_server_for_channel(webhook_data.get("channel"))
        user_name = json_object.get("User", {}).get("Name")
        item_info = json_object.get("Item", {})

        is_favorite = json_object.get("IsFavorite", False)
        if not is_favorite:
            is_favorite = item_info.get("UserData", {}).get("IsFavorite", False)
        if webhook_data.get("event") == "item.rate":
            is_favorite = item_info.get("UserData", {}).get("IsFavorite", False)
        elif webhook_data.get("event") in ["user.favorite", "item.favorite"]:
            is_favorite = True

        if not all([server_name, user_name, item_info]): return
        item_type = item_info.get("Type")
        if (item_type == "Movie" and not self._sync_movies) or (item_type in ["Episode", "Series"] and not self._sync_tv):
            return

        target_users = self._find_sync_targets(server_name, user_name)
        self._sync_favorite_to_targets(server_name, user_name, item_info, is_favorite, target_users)

    def _handle_played_status_event(self, webhook_data):
        if not self._sync_played: return
        json_object = webhook_data.get("json_object", {})
        if not json_object: return

        server_name = webhook_data.get("server_name") or json_object.get("Server", {}).get("Name") or self._default_server_for_channel(webhook_data.get("channel"))
        user_name = json_object.get("User", {}).get("Name")
        item_info = json_object.get("Item", {})
        is_played = webhook_data.get("event") in ["playback.scrobble", "item.markplayed"]

        if not all([server_name, user_name, item_info]): return
        item_type = item_info.get("Type")
        if (item_type == "Movie" and not self._sync_movies) or (item_type in ["Episode", "Series"] and not self._sync_tv):
            return

        target_users = self._find_sync_targets(server_name, user_name)
        self._sync_played_status_to_targets(server_name, user_name, item_info, is_played, target_users)

    def _sync_played_status_to_targets(self, source_server, source_user, item_info, is_played, target_users):
        for target_server, target_user in target_users:
            try:
                emby_instance = self._emby_instances.get(target_server)
                if not emby_instance: continue
                target_item = self._find_matching_item(emby_instance, target_user, item_info)
                target_item_id = target_item.get("Id") if isinstance(target_item, dict) else target_item
                if not target_item_id: continue

                success = self._set_item_played_status(emby_instance, target_user, target_item_id, is_played)
                sync_type = "mark_played" if is_played else "mark_unplayed"
                if success:
                    self._loop_protector.add(target_user, target_item_id, sync_type)

                self._record_sync_result(
                    source_server=source_server,
                    source_user=source_user,
                    target_server=target_server,
                    target_user=target_user,
                    item_info=item_info,
                    position_ticks=0,
                    status="success" if success else "error",
                    error_message=None if success else "播放状态同步失败",
                    sync_type=sync_type
                )
            except Exception as e:
                self._record_sync_result(
                    source_server=source_server,
                    source_user=source_user,
                    target_server=target_server,
                    target_user=target_user,
                    item_info=item_info,
                    position_ticks=0,
                    status="error",
                    error_message=str(e),
                    sync_type="mark_played" if is_played else "mark_unplayed"
                )

    def _set_item_played_status(self, emby_instance, user_name, item_id, is_played):
        try:
            user_id = self._get_user_id(emby_instance, user_name)
            if not user_id: return False

            url = f"[HOST]emby/Users/{user_id}/PlayedItems/{item_id}?api_key=[APIKEY]"
            response = self._emby_request(emby_instance, "post" if is_played else "delete", url)
            return response and response.status_code in [200, 204]
        except Exception:
            return False

    def _find_sync_targets(self, source_server: str, source_user: str) -> List[Tuple[str, str]]:
        target_users = []
        for group in self._sync_groups:
            if not group.get("enabled", True): continue
            
            if not any(self._is_server_match(u.get("server"), source_server) and u.get("username") == source_user for u in group.get("users", [])):
                continue

            for target_user in group.get("users", []):
                t_server, t_user = target_user.get("server"), target_user.get("username")
                if self._is_server_match(t_server, source_server) and t_user == source_user:
                    continue
                actual_target_server = self._get_actual_server_name(t_server)
                if actual_target_server:
                    target_users.append((actual_target_server, t_user))
        return target_users

    def _sync_favorite_to_targets(self, source_server, source_user, item_info, is_favorite, target_users):
        for target_server, target_user in target_users:
            try:
                emby_instance = self._emby_instances.get(target_server)
                if not emby_instance: continue

                target_item = self._find_matching_item(emby_instance, target_user, item_info)
                target_item_id = target_item.get("Id") if isinstance(target_item, dict) else target_item
                if not target_item_id: continue

                success = self._set_item_favorite(emby_instance, target_user, target_item_id, is_favorite)
                sync_type = "favorite" if is_favorite else "not_favorite"
                
                if success:
                    self._loop_protector.add(target_user, target_item_id, sync_type)

                self._record_sync_result(
                    source_server=source_server,
                    source_user=source_user,
                    target_server=target_server,
                    target_user=target_user,
                    item_info=item_info,
                    position_ticks=0,
                    status="success" if success else "error",
                    error_message=None if success else "收藏同步失败",
                    sync_type=sync_type
                )
            except Exception as e:
                self._record_sync_result(
                    source_server=source_server,
                    source_user=source_user,
                    target_server=target_server,
                    target_user=target_user,
                    item_info=item_info,
                    position_ticks=0,
                    status="error",
                    error_message=str(e),
                    sync_type="favorite" if is_favorite else "not_favorite"
                )

    def _set_item_favorite(self, emby_instance, user_name, item_id, is_favorite):
        try:
            user_id = self._get_user_id(emby_instance, user_name)
            if not user_id: return False

            url = f"[HOST]emby/Users/{user_id}/FavoriteItems/{item_id}?api_key=[APIKEY]"
            response = self._emby_request(emby_instance, "post" if is_favorite else "delete", url, data="")

            return response and response.status_code in [200, 204]
        except Exception:
            return False

    def _get_user_id(self, emby_instance, user_name):
        if self._is_zspace_instance(emby_instance) and hasattr(emby_instance, "get_user"):
            return emby_instance.get_user(user_name)
        response = self._emby_request(emby_instance, "get", "[HOST]emby/Users?api_key=[APIKEY]")
        if response and response.status_code == 200:
            for user in response.json():
                if user.get("Name") == user_name: return user.get("Id")
        return None

    def _cleanup_expired_syncs(self):
        current_time = datetime.now()
        with self._sync_lock:
            expired_keys = [k for k, start in self._active_syncs.items() if current_time - start > timedelta(minutes=10)]
            for key in expired_keys: del self._active_syncs[key]

    def get_sync_status(self) -> dict:
        with self._sync_lock:
            return {
                "metrics": dict(self._sync_metrics),
                "active_syncs": len(self._active_syncs),
                "max_concurrent": self._max_concurrent_syncs,
                "event_cache_size": len(self._event_timestamps),
                "emby_servers": len(self._emby_instances),
                "zspace_servers": len(self._zspace_instances),
                "sync_groups": len([g for g in self._sync_groups if g.get("enabled", True)]),
                "zspace_poll_enabled": self._zspace_poll_enabled,
                "zspace_poll_interval": self._zspace_poll_interval,
                "zspace_poll_source_users": {
                    sn: self._get_zspace_poll_source_users(sn) for sn in self._zspace_instances.keys()
                }
            }

    def _handle_playback_event(self, webhook_data):
        json_object = webhook_data.get("json_object", {})
        if not json_object: return

        server_name = webhook_data.get("server_name") or json_object.get("Server", {}).get("Name") or self._default_server_for_channel(webhook_data.get("channel"))
        user_name = json_object.get("User", {}).get("Name")
        item_info = json_object.get("Item", {})
        session_info = json_object.get("Session", {})
        playback_info = json_object.get("PlaybackInfo", {})

        if not session_info.get("PositionTicks") and playback_info.get("PositionTicks"):
            session_info["PositionTicks"] = playback_info.get("PositionTicks")
            
        if not all([server_name, user_name, item_info]): return

        item_type = item_info.get("Type")
        if (item_type == "Movie" and not self._sync_movies) or (item_type in ["Episode", "Series"] and not self._sync_tv):
            return

        play_duration_ticks = session_info.get("PlayDurationTicks", 0) or playback_info.get("PlayDurationTicks", 0)
        position_ticks = session_info.get("PositionTicks", 0) or playback_info.get("PositionTicks", 0)

        if not play_duration_ticks and item_info.get("RunTimeTicks") and position_ticks:
            play_duration_ticks = position_ticks

        if (play_duration_ticks / 10000000) < self._min_watch_time: return

        self._sync_to_group_users(server_name, user_name, item_info, position_ticks)

        item_runtime = item_info.get("RunTimeTicks", 0)
        if item_runtime and position_ticks and position_ticks >= item_runtime * 0.9:
            self._sync_played_status_to_targets(server_name, user_name, item_info, True, self._find_sync_targets(server_name, user_name))

    def _sync_to_group_users(self, source_server: str, source_user: str, item_info: dict, position_ticks: int):
        for target_server, target_username in self._find_sync_targets(source_server, source_user):
            if self._sync_watch_progress_with_retry(source_server, source_user, target_server, target_username, item_info, position_ticks):
                self._update_sync_metrics('sync_completed', True)
            else:
                self._update_sync_metrics('sync_completed', False)

    def _is_server_match(self, config_server: str, actual_server: str) -> bool:
        if not config_server or not actual_server: return False
        if config_server == actual_server: return True
        
        config_lower, actual_lower = config_server.lower(), actual_server.lower()
        actual_type = self._get_server_type(actual_server)

        if config_lower == "emby": return actual_type == "emby" or (self._has_server_type("emby") and not self._looks_like_zspace_server_name(actual_server))
        if config_lower in ["zspace", "zvideo", "jiyingshi", "极影视"]: return actual_type == "zspace" or self._looks_like_zspace_server_name(actual_server)

        if len(config_server) >= 3 and config_lower in actual_lower and len(config_server) / len(actual_server) > 0.3: return True
        if len(actual_server) >= 3 and actual_lower in config_lower and len(actual_server) / len(config_server) > 0.3: return True
        
        return False

    def _get_server_type(self, server_name: str) -> str:
        if not server_name: return "unknown"
        if server_name in self._server_types: return self._server_types[server_name]
        if server_name in self._zspace_instances: return "zspace"
        if self._is_zspace_instance(self._emby_instances.get(server_name)): return "zspace"
        return "emby" if self._emby_instances.get(server_name) else "unknown"

    def _has_server_type(self, server_type: str) -> bool:
        return any(self._get_server_type(sn) == server_type for sn in self._emby_instances.keys())

    def _looks_like_zspace_server_name(self, server_name: str) -> bool:
        if not server_name: return False
        return server_name in self._zspace_instances or any(alias in server_name.lower() for alias in ["zspace", "zvideo", "jiyingshi", "qizhi", "极影视", "极空间"])

    def _default_server_for_channel(self, channel: str) -> Optional[str]:
        expected = "zspace" if channel == "zspace" else "emby"
        return next((sn for sn in self._emby_instances.keys() if self._get_server_type(sn) == expected), next(iter(self._emby_instances.keys()), None))

    def _is_zspace_instance(self, instance) -> bool:
        if not instance: return False
        return getattr(instance, "_is_watchsync_zspace", False) or "zspace" in instance.__class__.__name__.lower()

    def _get_actual_server_name(self, config_server: str) -> Optional[str]:
        if not config_server: return None
        if config_server in self._emby_instances: return config_server
        
        c = config_server.lower()
        if c == "emby": return next((sn for sn in self._emby_instances.keys() if self._get_server_type(sn) == "emby"), None)
        if c in ["zspace", "zvideo", "jiyingshi", "极影视"]: return next(iter(self._zspace_instances.keys()), None)
        return next((sn for sn in self._emby_instances.keys() if c in sn.lower() or sn.lower() in c), None)

    @retry_on_failure(max_retries=3, base_delay=2, max_delay=30)
    def _sync_watch_progress_with_retry(self, source_server: str, source_user: str, target_server: str, target_user: str, item_info: dict, position_ticks: int) -> bool:
        sync_key = f"{target_server}:{target_user}:{item_info.get('Id', '')}"
        with self._sync_lock:
            if sync_key in self._active_syncs or len(self._active_syncs) >= self._max_concurrent_syncs: return False
            self._active_syncs[sync_key] = datetime.now()
        try:
            return self._sync_watch_progress(source_server, source_user, target_server, target_user, item_info, position_ticks)
        finally:
            with self._sync_lock: self._active_syncs.pop(sync_key, None)

    def _sync_watch_progress(self, source_server: str, source_user: str, target_server: str, target_user: str, item_info: dict, position_ticks: int) -> bool:
        target_emby = self._emby_instances.get(target_server)
        if not target_emby or not self._health_check_emby_connection(target_server, target_emby): return False
        target_item = self._find_matching_item(target_emby, target_user, item_info)
        
        target_item_id = None
        if isinstance(target_item, dict):
            target_item_id = target_item.get("Id") or target_item.get("id") or target_item.get("item_id")
        elif target_item:
            target_item_id = getattr(target_item, 'Id', getattr(target_item, 'id', getattr(target_item, 'item_id', None)))

        if not target_item_id: return False

        success = self._update_user_progress(target_emby, target_user, target_item_id, position_ticks)
        if success:
            self._loop_protector.add(target_user, target_item_id, "playback")

        self._record_sync_result(source_server=source_server, source_user=source_user, target_server=target_server, target_user=target_user, item_info=item_info, position_ticks=position_ticks, status="success" if success else "error", sync_type="playback")
        return success

    def _find_matching_item(self, emby_instance, target_user, source_item: dict) -> Optional[dict]:
        if self._is_zspace_instance(emby_instance):
            return self._find_matching_zspace_item(emby_instance, target_user, source_item)

        tmdb_id = source_item.get("ProviderIds", {}).get("Tmdb")
        if tmdb_id:
            results = emby_instance.get_movies(title="", tmdb_id=int(tmdb_id)) if source_item.get("Type") == "Movie" else self._search_tv_by_tmdb(emby_instance, tmdb_id)
            if results: return results[0].__dict__ if hasattr(results[0], '__dict__') else results[0]

        try:
            user_id = emby_instance.get_user(target_user)
            if not user_id: return None
            include_types = "Movie" if source_item.get("Type") == "Movie" else "Series,Episode"
            
            for term in self._get_media_search_terms(source_item):
                search_url = f"[HOST]emby/Users/{user_id}/Items?api_key=[APIKEY]&Recursive=true&IncludeItemTypes={include_types}&SearchTerm={quote(str(term))}&Limit=50&Fields=ProviderIds,SeriesName,ParentIndexNumber,IndexNumber,Path,UserData,ProductionYear,RunTimeTicks"
                if source_item.get("ProductionYear") and source_item.get("Type") == "Movie":
                    search_url += f"&Years={source_item.get('ProductionYear')}"
                    
                response = self._emby_request(emby_instance, "get", search_url)
                if response and response.status_code == 200:
                    best = self._pick_best_matching_item(source_item, response.json().get("Items", []))
                    if best: return best
        except Exception:
            pass
        return None

    def _get_media_search_terms(self, source_item: dict) -> List[str]:
        terms = []
        candidates = [source_item.get("Name"), source_item.get("OriginalTitle")] if source_item.get("Type") == "Movie" else [source_item.get("Name"), source_item.get("SeriesName"), self._normalize_series_name(source_item.get("SeriesName")), source_item.get("OriginalTitle")]
        for term in candidates:
            if term and term not in terms: terms.append(term)
        return terms

    def _find_matching_zspace_item(self, zspace_instance, target_user, source_item: dict) -> Optional[dict]:
        user_id = zspace_instance.get_user(target_user)
        if not user_id: return None
        if source_item.get("Id", "").startswith("video_"):
            resp = self._emby_request(zspace_instance, "get", f"[HOST]emby/Users/{user_id}/Items/{source_item.get('Id')}?api_key=[APIKEY]")
            if resp and resp.status_code == 200: return resp.json()

        for term in [source_item.get("SeriesName"), source_item.get("Name"), source_item.get("OriginalTitle")]:
            if not term: continue
            url = f"[HOST]emby/Users/{user_id}/Items?api_key=[APIKEY]&Recursive=true&IncludeItemTypes={'Movie' if source_item.get('Type') == 'Movie' else 'Episode'}&SearchTerm={quote(str(term))}&Limit=30&Fields=ProviderIds,OriginalTitle,ProductionYear,Path,UserData,SeriesName,ParentIndexNumber,IndexNumber,RunTimeTicks"
            resp = self._emby_request(zspace_instance, "get", url)
            if resp and resp.status_code == 200:
                best = self._pick_best_matching_item(source_item, self._expand_zspace_episode_candidates(zspace_instance, user_id, source_item, resp.json().get("Items", [])))
                if best: return best
        return None

    def _expand_zspace_episode_candidates(self, zspace_instance, user_id: str, source_item: dict, candidates: List[dict]) -> List[dict]:
        if source_item.get("Type") != "Episode" or not candidates: return candidates
        expanded = [c for c in candidates if c.get("Type") == "Episode"]
        for c in candidates:
            if c.get("Type") == "Series" and c.get("Id"):
                resp = self._emby_request(zspace_instance, "get", f"[HOST]emby/Shows/{c.get('Id')}/Episodes?api_key=[APIKEY]&UserId={user_id}&Fields=ProviderIds,OriginalTitle,ProductionYear,Path,UserData,SeriesName,ParentIndexNumber,IndexNumber,RunTimeTicks")
                if resp and resp.status_code == 200: expanded.extend(resp.json().get("Items", []))
        return expanded or candidates

    def _pick_best_matching_item(self, source_item: dict, candidates: List[dict]) -> Optional[dict]:
        if not candidates: return None
        st, sn, sy, ss, se = source_item.get("Type"), (source_item.get("Name") or "").strip().lower(), source_item.get("ProductionYear"), source_item.get("ParentIndexNumber"), source_item.get("IndexNumber")
        s_ser = self._normalize_series_name(source_item.get("SeriesName")).lower()

        for c in candidates:
            if source_item.get("ProviderIds", {}).get("Tmdb") and c.get("ProviderIds", {}).get("Tmdb") == source_item.get("ProviderIds", {}).get("Tmdb"): return c

        if st == "Movie":
            for c in candidates:
                if (c.get("Name") or "").strip().lower() == sn and (not sy or not c.get("ProductionYear") or str(c.get("ProductionYear")) == str(sy)): return c
        elif st in ["Episode", "Series"]:
            for c in candidates:
                if st == "Episode" and c.get("Type") != "Episode": continue
                if st == "Episode" and ss and str(ss) != str(c.get("ParentIndexNumber")): continue
                if st == "Episode" and se and str(se) != str(c.get("IndexNumber")): continue
                return c
        return candidates[0]

    @staticmethod
    def _normalize_series_name(name: Optional[str]) -> str:
        if not name: return ""
        v = str(name).strip()
        for p in [r"\s*第\s*\d+\s*季\s*$", r"\s*[Ss]eason\s*\d+\s*$", r"\s*[Ss]\d+\s*$"]:
            v = re.sub(p, "", v).strip()
        return v

    def _search_tv_by_tmdb(self, emby_instance, tmdb_id: str):
        resp = self._emby_request(emby_instance, "get", "[HOST]emby/Items?api_key=[APIKEY]&Recursive=true&IncludeItemTypes=Series,Episode&Fields=ProviderIds")
        if resp and resp.status_code == 200:
            return [i for i in resp.json().get("Items", []) if i.get("ProviderIds", {}).get("Tmdb") == tmdb_id]
        return None

    def _update_user_progress(self, emby_instance, user_name: str, item_id: str, position_ticks: int) -> bool:
        user_id = emby_instance.get_user(user_name)
        if not user_id: return False
        if self._is_zspace_instance(emby_instance): return self._update_zspace_progress(emby_instance, user_id, item_id, position_ticks)
        return self._update_progress_via_userdata(emby_instance, user_id, item_id, position_ticks)

    def _update_zspace_progress(self, zspace_instance, user_id: str, item_id: str, position_ticks: int) -> bool:
        resp = self._emby_request(zspace_instance, "post", "[HOST]emby/Sessions/Playing/Progress", json={
            "ItemId": item_id, "UserId": user_id, "PositionTicks": position_ticks, "IsPaused": True, "IsMuted": False,
            "PlayMethod": "DirectPlay", "PlaySessionId": "watchsync", "MediaSourceId": item_id, "CanSeek": True, "EventName": "timeupdate"
        })
        return resp and resp.status_code in [200, 204]

    def _update_progress_via_userdata(self, emby_instance, user_id: str, item_id: str, position_ticks: int) -> bool:
        ud = self._get_current_userdata(emby_instance, user_id, item_id)
        data = {"PlaybackPositionTicks": position_ticks, "LastPlayedDate": datetime.now().isoformat() + "Z"}
        for k in ["PlayCount", "IsFavorite", "Rating", "Played"]:
            if ud.get(k) is not None: data[k] = ud[k]
        resp = self._emby_request(emby_instance, "post", f"[HOST]emby/Users/{user_id}/Items/{item_id}/UserData?api_key=[APIKEY]", json=data)
        return resp and resp.status_code in [200, 204]

    def _get_current_userdata(self, emby_instance, user_id: str, item_id: str) -> dict:
        resp = self._emby_request(emby_instance, "get", f"[HOST]emby/Users/{user_id}/Items/{item_id}?api_key=[APIKEY]")
        return resp.json().get("UserData", {}) if resp and resp.status_code == 200 else {}

    def _health_check_emby_connection(self, server_name: str, emby_instance) -> bool:
        resp = self._emby_request(emby_instance, "get", "[HOST]emby/System/Info?api_key=[APIKEY]")
        return resp and resp.status_code == 200

    @db_update
    def _record_sync_result(self, db: Optional[Session] = None, *, source_server: str, source_user: str, target_server: str, target_user: str, item_info: dict, position_ticks: int, status: str, error_message: str = None, sync_type: str = "playback"):
        assert db is not None
        plugin_id = self.__class__.__name__
        record = WatchSyncRecord(
            plugin_id=plugin_id,
            source_server=source_server,
            source_user=source_user,
            target_server=target_server,
            target_user=target_user,
            media_name=item_info.get('Name', ''),
            media_type=item_info.get('Type', ''),
            media_id=item_info.get('Id', ''),
            position_ticks=position_ticks,
            sync_type=sync_type,
            status=status,
            error_message=error_message
        )
        db.add(record)
        
        today = datetime.now().strftime('%Y-%m-%d')
        stat = db.execute(select(WatchSyncStat).where(WatchSyncStat.plugin_id == plugin_id, WatchSyncStat.date == today)).scalar_one_or_none()
        if not stat:
            stat = WatchSyncStat(
                plugin_id=plugin_id, 
                date=today, 
                total_syncs=0, 
                success_syncs=0, 
                failed_syncs=0
            )
            db.add(stat)
            
        stat.total_syncs += 1
        if status == 'success': stat.success_syncs += 1
        else: stat.failed_syncs += 1


    # ====== API Endpoints (FastAPI路由入口，分离DB参数以确保兼容性) ======

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/servers", "endpoint": self._get_servers, "methods": ["GET"], "auth": "bear"},
            {"path": "/users", "endpoint": self._get_users_endpoint, "methods": ["GET"], "auth": "bear"},
            {"path": "/stats", "endpoint": self._get_stats_endpoint, "methods": ["GET"], "auth": "bear"},
            {"path": "/records", "endpoint": self._get_records_endpoint, "methods": ["GET"], "auth": "bear"},
            {"path": "/status", "endpoint": self._get_status_endpoint, "methods": ["GET"], "auth": "bear"},
            {"path": "/records/old", "endpoint": self._clear_old_records_endpoint, "methods": ["DELETE"], "auth": "bear"}
        ]

    def _get_servers(self) -> Dict[str, Any]:
        return {
            "success": True, 
            "data": [{"name": k, "type": self._get_server_type(k), "host": getattr(v, '_host', ''), "status": "online"} for k, v in self._emby_instances.items()]
        }

    def _get_users_endpoint(self) -> Dict[str, Any]:
        return {
            "success": True, 
            "data": {k: self._get_server_users(v) for k, v in self._emby_instances.items()}
        }

    def _get_server_users(self, emby_instance) -> List[Dict[str, str]]:
        if not emby_instance: return []
        if self._is_zspace_instance(emby_instance):
            u_id = emby_instance.get_user(None) if hasattr(emby_instance, "get_user") else getattr(emby_instance, "user", None)
            u_name = getattr(emby_instance, "_username", None) or u_id
            return [{"id": u_id, "name": u_name}] if u_id and u_name else []
        resp = self._emby_request(emby_instance, "get", "[HOST]emby/Users?api_key=[APIKEY]")
        return [{"id": u["Id"], "name": u["Name"]} for u in resp.json()] if resp and resp.status_code == 200 else []


    def _get_stats_endpoint(self) -> Dict[str, Any]:
        return self._get_stats_db()

    @db_query
    def _get_stats_db(self, db: Optional[Session] = None) -> Dict[str, Any]:
        assert db is not None
        plugin_id = self.__class__.__name__
        
        stmt = select(
            WatchSyncRecord.status,
            WatchSyncRecord.created_at,
            WatchSyncRecord.source_user,
            WatchSyncRecord.target_user,
            WatchSyncRecord.sync_type
        ).where(WatchSyncRecord.plugin_id == plugin_id)
        records = db.execute(stmt).mappings().all()
        
        t_syncs = len(records)
        s_syncs = sum(1 for r in records if r['status'] == 'success')
        today = datetime.now().date()
        recent = datetime.now() - timedelta(hours=24)
        
        stats = {
            "总同步次数": t_syncs,
            "今日同步次数": sum(1 for r in records if r['created_at'] and r['created_at'].date() == today),
            "成功次数": s_syncs,
            "失败次数": t_syncs - s_syncs,
            "成功率": f"{(s_syncs/t_syncs*100):.1f}" if t_syncs > 0 else "0",
            "活跃用户数": len(set([r['source_user'] for r in records if r['created_at'] and r['created_at'] >= recent] + [r['target_user'] for r in records if r['created_at'] and r['created_at'] >= recent])),
            "同步类型": list(set(r['sync_type'] or 'playback' for r in records)),
            "同步组数": sum(1 for g in self._sync_groups if g.get("enabled", True)),
            "组内用户数": sum(len(g.get("users", [])) for g in self._sync_groups if g.get("enabled", True))
        }
        return {"success": True, "data": stats}

    def _get_records_endpoint(self, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
        return self._get_records_db(limit=limit, offset=offset)

    @db_query
    def _get_records_db(self, db: Optional[Session] = None, *, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
        assert db is not None
        plugin_id = self.__class__.__name__
        limit, offset = min(max(limit, 10), 100), max(offset, 0)
        total = db.execute(select(func.count()).select_from(WatchSyncRecord).where(WatchSyncRecord.plugin_id == plugin_id)).scalar()
        
        stmt = select(
            WatchSyncRecord.id, WatchSyncRecord.plugin_id, WatchSyncRecord.source_server,
            WatchSyncRecord.source_user, WatchSyncRecord.target_server, WatchSyncRecord.target_user,
            WatchSyncRecord.media_name, WatchSyncRecord.media_type, WatchSyncRecord.media_id,
            WatchSyncRecord.position_ticks, WatchSyncRecord.sync_type, WatchSyncRecord.status,
            WatchSyncRecord.error_message, WatchSyncRecord.created_at
        ).where(WatchSyncRecord.plugin_id == plugin_id).order_by(desc(WatchSyncRecord.created_at)).limit(limit).offset(offset)
        
        recs = db.execute(stmt).mappings().all()
        
        data = []
        for r in recs:
            item = dict(r)
            if item.get("created_at"):
                item["created_at"] = item["created_at"].isoformat()
                item["timestamp"] = item["created_at"]
            data.append(item)
            
        return {
            "success": True, 
            "data": data,
            "pagination": {"total": total, "offset": offset, "limit": limit, "has_more": (offset + len(recs)) < total, "current_count": len(recs)}
        }

    def _get_status_endpoint(self):
        self._cleanup_expired_syncs()
        sts = self.get_sync_status()
        sts.update({"plugin_enabled": self._enabled, "sync_movies": self._sync_movies, "sync_tv": self._sync_tv, "min_watch_time": self._min_watch_time, "last_update": datetime.now().isoformat()})
        return {"success": True, "data": sts}

    def _clear_old_records_endpoint(self, days: int = 30) -> Dict[str, Any]:
        return self._clear_old_records_db(days=days)

    @db_update
    def _clear_old_records_db(self, db: Optional[Session] = None, *, days: int = 30) -> Dict[str, Any]:
        assert db is not None
        plugin_id = self.__class__.__name__
        cutoff = datetime.now() - timedelta(days=max(min(days, 365), 1))
        res = db.execute(delete(WatchSyncRecord).where(WatchSyncRecord.plugin_id == plugin_id, WatchSyncRecord.created_at < cutoff))
        return {"success": True, "message": f"成功清理了 {res.rowcount} 条旧记录"}

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        return "vue", "dist/assets"

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [], {}

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self):
        pass
