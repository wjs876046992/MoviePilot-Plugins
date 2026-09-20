import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.core.event import Event, EventType, eventmanager
from app.plugins import _PluginBase
from app.sdk.logging import logger
from apscheduler.triggers.cron import CronTrigger

try:
    from app.schemas.types import MessageType
except Exception:  # pragma: no cover - 兼容不同版本宿主
    MessageType = None


class Rsync115Sync(_PluginBase):
    plugin_name = "115网盘同步助手"
    plugin_desc = "需依赖 CloudDrive2 (CD2) 将 115 网盘挂载到本地宿主机并映射至 MoviePilot 容器。专为 CD2 挂载 115 打造：支持入库 N 小时冷却后同步、双向对账审计、关键字查找入库重试与手机端交互指令。"
    plugin_icon = "mdi-cloud-sync"
    plugin_version = "0.0.8"
    plugin_author = "HermanWu"

    # rsync 退出码语义（与 sync_115.sh 的 _handle_rsync_exit 对齐）：
    #   0  成功
    #   24 源文件在传输中消失——属正常波动，不计入失败
    #   23 部分文件未传输——属可容忍告警，不计入失败
    # 其余非 0 码均视为致命错误，必须让本轮判定为失败，避免谎报“已完成”。
    _TOLERATED_EXIT_CODES = {0, 23, 24}

    # 伴生字幕扩展名：补传媒体文件时，同主名的这些文件一并纳入，
    # 因为实际入库单元是“整集”（媒体 + 外挂字幕）
    _SIDECAR_EXTS = {"srt", "ass", "ssa", "sub", "idx", "sup", "vtt"}

    def __init__(self):
        super().__init__()
        self._enabled: bool = False
        self._listen_transfer: bool = True
        self._notify: bool = True
        self._delay_hours: float = 2.0
        self._cron: str = "0 */2 * * *"

        # 多目录映射对列表: [{"name": "电视剧", "src": "/path/TV", "dest": "/mnt/115/TV", "all_ext": False}]
        self._sync_pairs: List[Dict[str, Any]] = []

        # 严格继承 sync_115.sh 的参数设置 (绝不用 --inplace, --temp-dir, --partial)
        self._media_extensions: str = "mp4,mkv,avi,mov,ts,m2ts,iso,wmv,flv,rmvb"
        self._exclude_patterns: str = "@eaDir/\n#recycle/\n@__thumb/\n.DS_Store\n..*"
        self._rsync_timeout: int = 60
        self._task_timeout: int = 3600

        # ---- 上传限流与风控退避（防小文件高频上传触发 115 风控）----
        # 全局生效：ready / retry / force / 补传 共用同一套窗口计数。
        # 单位时间是硬闸门，与“单次取多少文件”的分批参数正交，两者都需要。
        self._rate_limit_enabled: bool = True
        self._upload_batch_size: int = 200          # 单次 rsync 最多处理的文件数（分批）
        self._upload_max_per_window: int = 500      # 单窗口最多上传文件数
        self._upload_window_secs: int = 1800        # 计数窗口长度（秒）
        self._backoff_secs: int = 3600              # 命中风控特征后的退避时长（秒）
        self._rate_limit_keywords: str = (
            "too many requests\nrate limit\n429\ntoo frequent\n频繁\n操作过快\n请稍后"
        )

        # 限流运行时状态（持久化：窗口计数与退避必须跨重载、跨重启保留）
        self._upload_window_start: float = 0.0
        self._upload_window_count: int = 0
        self._upload_blocked_until: float = 0.0
        # 当前批次实际提交给 rsync 的文件数，用于成功后扣减配额
        self._current_batch_size: int = 0

        # 锁与运行时状态
        self._lock = threading.Lock()
        self._is_running: bool = False
        self._current_process: Optional[subprocess.Popen] = None

        # 冷却队列: { "任务名:相对路径": 入库时间戳 float }
        self._pending_queue: Dict[str, float] = {}

        # 待确认的交互重试列表（关键字查找结果）：[{"key": "...", "path": "..."}]
        self._waiting_confirm_retries: List[str] = []

        # 存量补传队列（独立于 pending_queue，不参与冷却计时）
        # 条目格式与其它清单一致："任务名:相对路径"
        self._backfill_queue: List[str] = []
        # 补传进度快照，用于看板/指令回显
        self._backfill_total: int = 0

        # 忽略规则清单（结构化方案 B）
        # [ { "rule": str, "match": "exact"|"contains", "created_at": str, "created_by": str, "source": "chat"|"web" } ]
        self._ignored_rules: List[Dict[str, Any]] = []

        self._last_status: Dict[str, Any] = {
            "state": "idle",
            "start_time": None,
            "end_time": None,
            "success": True,
            "error": "",
            "missing_files": [],      # 完全缺失列表
            "corrupt_files": [],      # 大小异常列表
        }

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled", False)
            self._listen_transfer = config.get("listen_transfer", True)
            self._notify = config.get("notify", True)
            self._delay_hours = float(config.get("delay_hours", 2.0))
            self._cron = config.get("cron", "0 */2 * * *")
            self._sync_pairs = config.get("sync_pairs") or []
            self._media_extensions = config.get("media_extensions") or "mp4,mkv,avi,mov,ts,m2ts,iso,wmv,flv,rmvb"
            self._exclude_patterns = config.get("exclude_patterns") or "@eaDir/\n#recycle/\n@__thumb/\n.DS_Store\n..*"
            self._rsync_timeout = int(config.get("rsync_timeout") or 60)
            self._task_timeout = int(config.get("task_timeout") or 3600)
            # 上传限流配置：允许用户按自己的风控容忍度调整
            self._rate_limit_enabled = bool(config.get("rate_limit_enabled", True))
            self._upload_batch_size = max(0, int(config.get("upload_batch_size") or 200))
            self._upload_max_per_window = max(0, int(config.get("upload_max_per_window") or 500))
            self._upload_window_secs = max(1, int(config.get("upload_window_secs") or 1800))
            self._backoff_secs = max(1, int(config.get("backoff_secs") or 3600))
            if config.get("rate_limit_keywords"):
                self._rate_limit_keywords = config.get("rate_limit_keywords")

        # 恢复限流窗口与退避状态（必须早于任何上传判定）
        self._load_rate_limit_state()

        # 恢复持久化数据
        saved_queue = self.get_data("pending_queue") or {}
        if isinstance(saved_queue, dict):
            self._pending_queue = saved_queue
        self._last_status["missing_files"] = self.get_data("missing_files") or []
        self._last_status["corrupt_files"] = self.get_data("corrupt_files") or []
        saved_ignored = self.get_data("ignored_files") or []
        if isinstance(saved_ignored, list):
            self._ignored_rules = saved_ignored
        # 恢复未完成的补传队列，保证跨重载/重启继续推进
        saved_backfill = self.get_data("backfill_queue") or []
        if isinstance(saved_backfill, list):
            self._backfill_queue = saved_backfill
        self._backfill_total = int(self.get_data("backfill_total") or 0)
        if self._backfill_queue:
            logger.info(f"[Rsync115Sync] 📦 已恢复存量补传队列：剩余 {len(self._backfill_queue)} 个"
                        f"（原始 {self._backfill_total} 个），将由定时巡检继续推进")

    def get_state(self) -> bool:
        return self._enabled

    def _is_ignored(self, key: str) -> bool:
        """检查某个文件 key 是否命中了忽略规则（大小写不敏感）"""
        if not key or not self._ignored_rules:
            return False
        k_lower = key.lower()
        for r in self._ignored_rules:
            rule_str = (r.get("rule") or "").lower().strip()
            if not rule_str:
                continue
            match_mode = r.get("match", "contains")
            if match_mode == "exact":
                if k_lower == rule_str:
                    return True
            else:
                if rule_str in k_lower:
                    return True
        return False

    def _add_ignore_rule(self, rule: str, match: str = "contains", created_by: str = "", source: str = "chat") -> bool:
        """添加一条忽略规则，并同步剔除已存在于缺失/残缺清单里的项"""
        rule = rule.strip()
        if not rule:
            return False
        # 去重
        for item in self._ignored_rules:
            if item.get("rule", "").lower() == rule.lower() and item.get("match") == match:
                return False
        entry = {
            "rule": rule,
            "match": match,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "created_by": created_by,
            "source": source,
        }
        self._ignored_rules.append(entry)
        self.save_data("ignored_files", self._ignored_rules)

        # 立即联动剔除已有的 missing/corrupt
        self._last_status["missing_files"] = [k for k in self._last_status.get("missing_files", []) if not self._is_ignored(k)]
        self._last_status["corrupt_files"] = [k for k in self._last_status.get("corrupt_files", []) if not self._is_ignored(k)]
        self.save_data("missing_files", self._last_status["missing_files"])
        self.save_data("corrupt_files", self._last_status["corrupt_files"])
        return True

    def _remove_ignore_rule(self, index_or_rule: Any) -> bool:
        """移除指定忽略规则"""
        removed = False
        if isinstance(index_or_rule, int) and 0 <= index_or_rule < len(self._ignored_rules):
            self._ignored_rules.pop(index_or_rule)
            removed = True
        elif isinstance(index_or_rule, str):
            target = index_or_rule.strip().lower()
            orig_len = len(self._ignored_rules)
            self._ignored_rules = [r for r in self._ignored_rules if (r.get("rule") or "").lower() != target]
            removed = len(self._ignored_rules) < orig_len
        if removed:
            self.save_data("ignored_files", self._ignored_rules)
        return removed

    # ================= 监听 MoviePilot 媒体转移完成事件 =================

    @eventmanager.register(EventType.TransferComplete)
    def on_transfer_complete(self, event: Event):
        if not self._enabled or not self._listen_transfer:
            return

        event_data = event.event_data or {}
        transfer_info = event_data.get("transferinfo")
        if not transfer_info:
            return

        file_list = getattr(transfer_info, "file_list_new", []) or []
        now_ts = time.time()
        added_count = 0

        for file_path in file_list:
            if not file_path or not os.path.exists(file_path):
                continue

            for pair in self._sync_pairs:
                src_root = (pair.get("src") or "").strip().rstrip("/")
                pair_name = pair.get("name") or src_root
                if src_root and file_path.startswith(src_root):
                    if not pair.get("all_ext", False):
                        ext = os.path.splitext(file_path)[-1].lstrip(".").lower()
                        valid_exts = [x.strip().lower() for x in self._media_extensions.split(",") if x.strip()]
                        if ext not in valid_exts:
                            continue

                    rel_path = os.path.relpath(file_path, src_root)
                    queue_key = f"{pair_name}:{rel_path}"
                    self._pending_queue[queue_key] = now_ts
                    added_count += 1
                    break

        if added_count > 0:
            self.save_data("pending_queue", self._pending_queue)
            logger.info(f"[Rsync115Sync] 监听到 {added_count} 个新入库媒体，已加入 {self._delay_hours}h 延迟冷却队列")

    # ================= 远程命令定义 =================

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/rsync_search",
                "event": EventType.PluginAction,
                "desc": "查入库文件并生成重试指令 (例: /rsync_search 繁花)",
                "category": "工具",
                "data": {"action": "search"}
            },
            {
                "cmd": "/rsync_confirm",
                "event": EventType.PluginAction,
                "desc": "确认执行查找到的待重试文件",
                "category": "工具",
                "data": {"action": "confirm"}
            },
            {
                "cmd": "/rsync_retry",
                "event": EventType.PluginAction,
                "desc": "重试失败/缺失的115文件(自动重传)",
                "category": "工具",
                "data": {"action": "retry"}
            },
            {
                "cmd": "/rsync_sync",
                "event": EventType.PluginAction,
                "desc": "同步已达到冷却时间(如2h)的入库媒体",
                "category": "工具",
                "data": {"action": "sync"}
            },
            {
                "cmd": "/rsync_force",
                "event": EventType.PluginAction,
                "desc": "忽略冷却限制，对全部目录执行增量传输",
                "category": "工具",
                "data": {"action": "force"}
            },
            {
                "cmd": "/rsync_status",
                "event": EventType.PluginAction,
                "desc": "查看当前115同步进度与冷却/待重试队列",
                "category": "工具",
                "data": {"action": "status"}
            },
            {
                "cmd": "/rsync_ignore",
                "event": EventType.PluginAction,
                "desc": "忽略指定文件不再报警 (例: /rsync_ignore 剧名 或 /rsync_ignore list/clear)",
                "category": "工具",
                "data": {"action": "ignore"}
            },
            {
                "cmd": "/rsync_backfill",
                "event": EventType.PluginAction,
                "desc": "补传存量媒体（含同名字幕），受限流分批推进",
                "category": "工具",
                "data": {"action": "backfill"}
            },
            {
                "cmd": "/rsync_backfill_clear",
                "event": EventType.PluginAction,
                "desc": "清空存量补传队列",
                "category": "工具",
                "data": {"action": "backfill_clear"}
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        services = []
        if self._enabled and self._cron:
            try:
                services.append({
                    "id": "Rsync115Sync_Cron",
                    "name": "定时检查并同步115冷却就绪媒体",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self._scheduled_sync,
                    "kwargs": {}
                })
            except Exception as e:
                logger.error(f"[Rsync115Sync] 定时规则解析失败: {e}")
        return services

    # ================= 渲染模式与基类抽象方法实现 =================

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        return "vue", "dist/assets"

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [], {}

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self):
        if self._current_process:
            try:
                self._current_process.kill()
            except Exception:
                pass
        self._is_running = False

    # ================= Web API 接口 (支撑独立前端页面) =================

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/status", "endpoint": self._api_get_status, "methods": ["GET"], "auth": "bear"},
            {"path": "/queue", "endpoint": self._api_get_queue, "methods": ["GET"], "auth": "bear"},
            {"path": "/config", "endpoint": self._api_get_config, "methods": ["GET"], "auth": "bear"},
            {"path": "/config", "endpoint": self._api_save_config, "methods": ["POST"], "auth": "bear"},
            {"path": "/sync", "endpoint": self._api_trigger_sync, "methods": ["POST"], "auth": "bear"},
            {"path": "/retry", "endpoint": self._api_trigger_retry, "methods": ["POST"], "auth": "bear"},
            {"path": "/sync_item", "endpoint": self._api_sync_item, "methods": ["POST"], "auth": "bear"},
            {"path": "/ignored", "endpoint": self._api_get_ignored, "methods": ["GET"], "auth": "bear"},
            {"path": "/ignore", "endpoint": self._api_add_ignore, "methods": ["POST"], "auth": "bear"},
            {"path": "/unignore", "endpoint": self._api_remove_ignore, "methods": ["POST"], "auth": "bear"},
            {"path": "/backfill_scan", "endpoint": self._api_backfill_scan, "methods": ["GET"], "auth": "bear"},
            {"path": "/backfill_start", "endpoint": self._api_backfill_start, "methods": ["POST"], "auth": "bear"},
            {"path": "/backfill_clear", "endpoint": self._api_backfill_clear, "methods": ["POST"], "auth": "bear"},
        ]

    def _api_get_ignored(self):
        return {"success": True, "data": self._ignored_rules}

    def _api_add_ignore(self, body: Dict[str, Any]):
        rule = (body or {}).get("rule", "").strip()
        match = (body or {}).get("match", "contains")
        if not rule:
            return {"success": False, "message": "规则不能为空"}
        ok = self._add_ignore_rule(rule=rule, match=match, created_by="Web", source="web")
        return {"success": ok, "message": "已加入忽略清单" if ok else "规则已存在或添加失败"}

    def _api_remove_ignore(self, body: Dict[str, Any]):
        idx = (body or {}).get("index")
        rule = (body or {}).get("rule")
        target = idx if isinstance(idx, int) else rule
        if target is None:
            return {"success": False, "message": "缺少指定索引或规则"}
        ok = self._remove_ignore_rule(target)
        return {"success": ok, "message": "已从忽略清单移除" if ok else "未找到匹配规则"}

    def _api_get_config(self):
        return {
            "success": True,
            "data": {
                "enabled": self._enabled,
                "listen_transfer": self._listen_transfer,
                "notify": self._notify,
                "delay_hours": self._delay_hours,
                "cron": self._cron,
                "sync_pairs": self._sync_pairs,
                "media_extensions": self._media_extensions,
                "exclude_patterns": self._exclude_patterns,
                "rsync_timeout": self._rsync_timeout,
                "task_timeout": self._task_timeout,
                "rate_limit_enabled": self._rate_limit_enabled,
                "upload_batch_size": self._upload_batch_size,
                "upload_max_per_window": self._upload_max_per_window,
                "upload_window_secs": self._upload_window_secs,
                "backoff_secs": self._backoff_secs,
                "rate_limit_keywords": self._rate_limit_keywords,
            }
        }

    def _api_save_config(self, config: Dict[str, Any]):
        if not config:
            return {"success": False, "message": "配置数据为空"}
        self._enabled = config.get("enabled", False)
        self._listen_transfer = config.get("listen_transfer", True)
        self._notify = config.get("notify", True)
        self._delay_hours = float(config.get("delay_hours", 2.0))
        self._cron = config.get("cron", "0 */2 * * *")
        self._sync_pairs = config.get("sync_pairs") or []
        self._media_extensions = config.get("media_extensions") or "mp4,mkv,avi,mov,ts,m2ts,iso,wmv,flv,rmvb"
        self._exclude_patterns = config.get("exclude_patterns") or "@eaDir/\n#recycle/\n@__thumb/\n.DS_Store\n..*"
        self._rsync_timeout = int(config.get("rsync_timeout") or 60)
        self._task_timeout = int(config.get("task_timeout") or 3600)
        # 上传限流配置：允许用户按自己的风控容忍度调整
        self._rate_limit_enabled = bool(config.get("rate_limit_enabled", True))
        self._upload_batch_size = max(0, int(config.get("upload_batch_size") or 200))
        self._upload_max_per_window = max(0, int(config.get("upload_max_per_window") or 500))
        self._upload_window_secs = max(1, int(config.get("upload_window_secs") or 1800))
        self._backoff_secs = max(1, int(config.get("backoff_secs") or 3600))
        if config.get("rate_limit_keywords"):
            self._rate_limit_keywords = config.get("rate_limit_keywords")
        self.update_config(config)
        return {"success": True, "message": "配置保存成功"}

    def _api_get_status(self):
        now_ts = time.time()
        threshold = self._delay_hours * 3600
        ready_count = sum(1 for ts in self._pending_queue.values() if now_ts - ts >= threshold)
        cooling_count = len(self._pending_queue) - ready_count
        return {
            "success": True,
            "data": {
                "is_running": self._is_running,
                "ready_count": ready_count,
                "cooling_count": cooling_count,
                "delay_hours": self._delay_hours,
                "last_status": self._last_status,
                "sync_pairs_count": len(self._sync_pairs),
                # 补传进度与限流状态，供看板展示
                "backfill_remaining": len(self._backfill_queue),
                "backfill_total": self._backfill_total,
                "rate_limit_enabled": self._rate_limit_enabled,
                "upload_window_count": self._upload_window_count,
                "upload_max_per_window": self._upload_max_per_window,
                "upload_blocked_until": self._upload_blocked_until,
            }
        }

    def _api_get_queue(self):
        now_ts = time.time()
        threshold = self._delay_hours * 3600
        items = []
        for key, ts in sorted(self._pending_queue.items(), key=lambda x: x[1]):
            elapsed = now_ts - ts
            remaining = max(0, threshold - elapsed)
            items.append({
                "key": key,
                "enter_time": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
                "is_ready": elapsed >= threshold,
                "remaining_seconds": int(remaining)
            })
        return {"success": True, "data": items}

    def _api_trigger_sync(self):
        if self._is_running:
            return {"success": False, "message": "已有任务正在运行"}
        self._start_sync_thread(mode="ready")
        return {"success": True, "message": "已触发同步任务"}

    def _api_trigger_retry(self):
        if self._is_running:
            return {"success": False, "message": "已有任务正在运行"}
        self._start_sync_thread(mode="retry")
        return {"success": True, "message": "已触发重试任务"}

    def _api_sync_item(self, body: Dict[str, Any]):
        """
        手动触发单条记录的同步/重试。

        请求体: { "key": "任务名:相对路径" }
        无论该文件是「冷却缓冲中」还是「已就绪」，都会立即定向上传；
        若它仍在冷却队列中，会被移出队列，避免稍后被定时任务重复同步一次。
        """
        body = body or {}
        keys = body.get("keys") if isinstance(body.get("keys"), list) else None
        if not keys:
            single = (body.get("key") or "").strip()
            if not single:
                return {"success": False, "message": "缺少 key 参数"}
            keys = [single]
        keys = [str(k).strip() for k in keys if str(k).strip()]
        if not keys:
            return {"success": False, "message": "缺少 key 参数"}

        if self._is_running:
            return {"success": False, "message": "已有任务正在运行，请稍后再试"}

        # 移出冷却队列（本次已经手动提前上传，无需再排队）
        popped = 0
        for k in keys:
            if k in self._pending_queue:
                self._pending_queue.pop(k, None)
                popped += 1
        if popped:
            self.save_data("pending_queue", self._pending_queue)

        logger.info(f"[Rsync115Sync] 用户从看板手动触发同步: {', '.join(keys)}（其中 {popped} 条来自冷却队列）")
        self._start_sync_thread(mode="retry", custom_files=keys)
        return {"success": True, "message": f"已触发同步：{len(keys)} 个文件"}

    # ================= 上传限流与风控退避 =================

    def _load_rate_limit_state(self):
        """从插件数据目录恢复限流窗口与退避状态。"""
        self._upload_window_start = float(self.get_data("upload_window_start") or 0.0)
        self._upload_window_count = int(self.get_data("upload_window_count") or 0)
        self._upload_blocked_until = float(self.get_data("upload_blocked_until") or 0.0)

    def _persist_rate_limit_state(self):
        """持久化限流状态。必须在首次计数前落盘，以关闭重启竞态窗口。"""
        self.save_data("upload_window_start", self._upload_window_start)
        self.save_data("upload_window_count", self._upload_window_count)
        self.save_data("upload_blocked_until", self._upload_blocked_until)

    def _rate_limit_allows(self) -> Tuple[bool, str]:
        """
        上传闸门：判断当前是否可以发起本批上传。

        返回 (是否放行, 原因说明)。三层判定：
          1) 退避期未过 → 拒绝；
          2) 窗口已过期 → 计数归零并前移窗口；
          3) 窗口内计数达上限 → 拒绝。
        """
        if not self._rate_limit_enabled:
            return True, ""

        now_ts = time.time()

        # 1) 风控退避期
        if now_ts < self._upload_blocked_until:
            remain = int(self._upload_blocked_until - now_ts)
            return False, f"风控退避中，还需等待 {max(1, remain // 60)} 分钟"

        # 2) 窗口滚动
        if self._upload_window_start <= 0 or (now_ts - self._upload_window_start) >= self._upload_window_secs:
            self._upload_window_start = now_ts
            self._upload_window_count = 0

        # 3) 窗口配额
        if self._upload_window_count >= self._upload_max_per_window:
            elapsed = int(now_ts - self._upload_window_start)
            remain = max(1, self._upload_window_secs - elapsed)
            return False, (f"本窗口配额已用尽（{self._upload_window_count}/{self._upload_max_per_window}），"
                           f"约 {max(1, remain // 60)} 分钟后继续")

        return True, ""

    def _consume_upload_quota(self, batch_info: str = "") -> int:
        """
        扣减配额：把本批实际上传的文件数并入窗口计数并落盘。

        必须在 rsync 成功后立即调用，保证窗口计数不因进程重启而丢失，
        否则重启会绕过限流直接放行下一批。
        返回扣减后的窗口计数。
        """
        if not self._rate_limit_enabled:
            return self._upload_window_count
        count = self._current_batch_size
        if count <= 0:
            return self._upload_window_count
        self._upload_window_count += count
        self._persist_rate_limit_state()
        logger.info(f"[Rsync115Sync] 🚦 上传配额扣减 {count} 个{batch_info}，"
                    f"本窗口累计 {self._upload_window_count}/{self._upload_max_per_window}")
        return self._upload_window_count

    def _detect_rate_limit_hit(self, stderr: str) -> bool:
        """从 rsync 错误输出中识别 115 / CD2 的风控特征串。"""
        if not stderr:
            return False
        lowered = stderr.lower()
        for kw in self._rate_limit_keywords.splitlines():
            kw = kw.strip().lower()
            if kw and kw in lowered:
                return True
        return False

    def _trigger_backoff(self, reason: str):
        """命中风控：进入退避期，后续批次在退避结束前一律不放行。"""
        self._upload_blocked_until = time.time() + self._backoff_secs
        # 退避期间窗口计数一并归零，避免退避结束后立刻撞上配额上限
        self._upload_window_start = 0.0
        self._upload_window_count = 0
        self._persist_rate_limit_state()
        logger.warning(f"[Rsync115Sync] 🚫 触发风控退避：{reason}，"
                       f"暂停上传 {self._backoff_secs // 60} 分钟")

    # ================= 存量媒体补传（零 API 本地扫描） =================

    def _find_sidecar_files(self, src_dir: str, rel_media: str) -> List[str]:
        """
        查找与某个媒体文件同主名的伴生字幕文件（本地扫描，不访问 115）。

        例：`剧名/剧名 S01E01.mkv` → `剧名/剧名 S01E01.zh.srt`、`…S01E01.ass`
        真实场景中入库的往往是整集（媒体 + 外挂字幕），若只同步媒体，
        字幕会被遗漏且永不触发同步。
        """
        src_f = os.path.join(src_dir, rel_media)
        parent_rel = os.path.dirname(rel_media)
        parent_abs = os.path.dirname(src_f)
        stem = os.path.splitext(os.path.basename(rel_media))[0]
        if not os.path.isdir(parent_abs):
            return []

        sidecars: List[str] = []
        prefix = f"{stem}."
        try:
            for name in os.listdir(parent_abs):
                if name == os.path.basename(rel_media):
                    continue
                # 仅认“主名 + 附加标记 + 字幕扩展名”，避免误纳同剧其它剧集
                if not name.startswith(prefix):
                    continue
                if os.path.splitext(name)[-1].lstrip(".").lower() not in self._SIDECAR_EXTS:
                    continue
                if not os.path.isfile(os.path.join(parent_abs, name)):
                    continue
                sidecars.append(f"{parent_rel}/{name}" if parent_rel else name)
        except OSError as e:
            logger.debug(f"[Rsync115Sync] 扫描伴生字幕失败 {rel_media}: {e}")
        return sidecars

    def _build_backfill_candidates(self) -> List[str]:
        """
        扫描源端，构建“存量补传”候选清单。

        全程只读源目录，不访问 115 挂载点，因此零 API 开销。
        候选口径：源端存在、且不在冷却队列、也不在异常清单中的文件
        （即本插件从未处理过的存量文件）。

        注意：无法在不访问 115 的前提下判断目标端是否已存在，
        因此候选可能包含已同步过但从未入过队的文件；这些文件会被
        rsync 的 --size-only 在传输阶段跳过（代价是每个文件一次 stat）。
        """
        candidates: List[str] = []
        seen = set()
        valid_exts = [x.strip().lower() for x in self._media_extensions.split(",") if x.strip()]
        # 只按扩展名过滤候选，范围由每个映射对的 all_ext 决定
        for pair in self._sync_pairs:
            src_dir = (pair.get("src") or "").strip().rstrip("/")
            pair_name = pair.get("name") or src_dir
            if not src_dir or not os.path.isdir(src_dir):
                continue
            all_ext = pair.get("all_ext", False)
            for root, dirs, files in os.walk(src_dir):
                # 就地裁剪排除目录，避免无谓 descend
                dirs[:] = [d for d in dirs if f"{d}/" not in self._exclude_patterns]
                for f in files:
                    if f.startswith("._") or f == ".DS_Store":
                        continue
                    ext = os.path.splitext(f)[-1].lstrip(".").lower()
                    if not all_ext and ext not in valid_exts:
                        continue
                    root_rel = os.path.relpath(os.path.join(root, f), src_dir)
                    key = f"{pair_name}:{root_rel}"
                    if key in seen:
                        continue
                    # 已在冷却队列或异常清单中的文件不属于“存量补传”
                    if key in self._pending_queue:
                        continue
                    if key in (self._last_status.get("missing_files") or []):
                        continue
                    if key in (self._last_status.get("corrupt_files") or []):
                        continue
                    if self._is_ignored(key):
                        continue
                    seen.add(key)
                    candidates.append(key)
                    # 媒体文件带上同主名的伴生字幕一起补传
                    for sc in self._find_sidecar_files(src_dir, root_rel):
                        sc_key = f"{pair_name}:{sc}"
                        if sc_key not in seen and not self._is_ignored(sc_key):
                            seen.add(sc_key)
                            candidates.append(sc_key)
        return candidates

    def _api_backfill_scan(self):
        """预览补传候选数量与样例，供用户在触发前评估规模。"""
        candidates = self._build_backfill_candidates()
        sample = candidates[:20]
        return {
            "success": True,
            "data": {
                "count": len(candidates),
                "sample": sample,
                "batch_size": self._upload_batch_size,
                "windows_needed": (
                    (len(candidates) + self._upload_max_per_window - 1) // self._upload_max_per_window
                    if self._upload_max_per_window > 0 else 0
                ),
            }
        }

    def _api_backfill_start(self, body: Dict[str, Any]):
        """
        启动存量补传。

        只扫描源端（零 API），把候选写入独立的补传队列，
        随后由核心同步逻辑按批次上限与窗口配额逐步消费。
        """
        if self._is_running:
            return {"success": False, "message": "已有任务正在运行，请稍后再试"}

        candidates = self._build_backfill_candidates()
        if not candidates:
            return {"success": True, "message": "没有需要补传的存量文件"}

        # 整体替换：每次触发都以当前源端实际状态为准
        self._backfill_queue = candidates
        self._backfill_total = len(candidates)
        self.save_data("backfill_queue", self._backfill_queue)
        self.save_data("backfill_total", self._backfill_total)

        logger.info(f"[Rsync115Sync] 📦 已建立存量补传队列：{len(candidates)} 个文件"
                    f"（其中含伴生字幕），按每批 {self._upload_batch_size} 个、"
                    f"每窗口 {self._upload_max_per_window} 个推进")
        self._start_sync_thread(mode="backfill", custom_files=list(candidates))
        return {
            "success": True,
            "message": f"已启动存量补传：{len(candidates)} 个文件，"
                       f"受批次与限流约束将分多轮完成",
        }

    def _api_backfill_clear(self):
        """清空补传队列与进度。"""
        self._backfill_queue = []
        self._backfill_total = 0
        self.save_data("backfill_queue", [])
        self.save_data("backfill_total", 0)
        return {"success": True, "message": "已清空存量补传队列"}

    # ================= 核心同步执行逻辑 (严格对齐 sync_115.sh) =================

    def _resume_backfill_if_pending(self) -> bool:
        """
        定时巡检时自动续跑未完成的补传队列。

        补传受“单批上限”与“窗口配额”约束，一次通常跑不完全部候选；
        未完成的队列在此自动续跑，配额用尽则本轮跳过、等下一窗口继续，
        无需用户重复点击。

        返回是否已占用本轮（同一次 cron 只跑一种模式，避免线程争抢同一把锁）。
        """
        if not self._backfill_queue:
            return False
        allowed, reason = self._rate_limit_allows()
        if not allowed:
            logger.info(f"[Rsync115Sync] 📦 补传队列剩余 {len(self._backfill_queue)} 个，"
                        f"本轮暂缓（{reason}）")
            return False
        logger.info(f"[Rsync115Sync] 📦 续跑存量补传队列，剩余 {len(self._backfill_queue)} 个")
        self._start_sync_thread(mode="backfill", custom_files=list(self._backfill_queue))
        return True

    def _scheduled_sync(self):
        logger.info("[Rsync115Sync] 触发定时检查同步就绪媒体...")
        # 补传队列存在时优先续跑：队列有限且自终止，排空后自动恢复常规巡检。
        # 两种模式共用同一把执行锁与同一份窗口配额，故同一轮只启动其中一个。
        if self._resume_backfill_if_pending():
            return
        self._start_sync_thread(mode="ready")

    def _start_sync_thread(self, mode: str = "ready", custom_files: Optional[List[str]] = None, channel_event: Optional[Event] = None):
        threading.Thread(target=self._execute_sync, args=(mode, custom_files, channel_event), daemon=True).start()

    def _execute_sync(self, mode: str = "ready", custom_files: Optional[List[str]] = None, channel_event: Optional[Event] = None):
        if not shutil.which("rsync"):
            self._post_reply(channel_event, "❌ 系统未安装 rsync 命令，请在终端执行: apt update && apt install -y rsync")
            return

        if not self._sync_pairs:
            self._post_reply(channel_event, "❌ 未配置任何同步目录对，请先前往插件配置页面添加目录映射！")
            return

        if not self._lock.acquire(blocking=False):
            self._post_reply(channel_event, "⚠️ 当前已有正在执行的同步任务，请勿重复发起。")
            return

        try:
            self._is_running = True
            start_time = datetime.now()
            self._last_status["state"] = "running"
            self._last_status["start_time"] = start_time.strftime("%Y-%m-%d %H:%M:%S")
            self._last_status["end_time"] = None
            self._last_status["error"] = ""

            total_pairs = len(self._sync_pairs)
            logger.info("=" * 60)
            logger.info(f"[Rsync115Sync] ▶ 开始执行同步任务 (模式: {mode}，共 {total_pairs} 个映射)")
            logger.info(f"[Rsync115Sync] 触发来源: {'聊天指令' if channel_event else ('看板/API 手动' if custom_files else '定时巡检')}")
            logger.info(f"[Rsync115Sync] 冷却队列: {len(self._pending_queue)} 条 | "
                        f"历史异常: 缺失 {len(self._last_status.get('missing_files', []) or [])} / "
                        f"残缺 {len(self._last_status.get('corrupt_files', []) or [])} | "
                        f"忽略规则: {len(self._ignored_rules)} 条")
            if custom_files:
                logger.info(f"[Rsync115Sync] 本次指定文件 {len(custom_files)} 个: {custom_files}")
            logger.info("=" * 60)

            # ---- 上传闸门：退避期或配额用尽时整轮直接跳过，绝不触碰 115 ----
            allowed, reason = self._rate_limit_allows()
            if not allowed:
                logger.warning(f"[Rsync115Sync] ⏸ 本轮跳过（{reason}）")
                self._last_status["state"] = "throttled"
                self._post_reply(channel_event, f"⏸ 已暂停本轮同步：{reason}")
                return

            self._post_reply(channel_event, f"🚀 开始执行115同步任务 (模式: {mode}，共 {total_pairs} 个映射)...")

            has_error = False
            # 记录致命退出码，便于在通知里给出可定位的失败原因
            fatal_exit_codes = []
            # 本轮补传已处理的文件（用于推进补传队列进度）
            self._backfill_done_keys: set = set()
            total_missing = []
            total_corrupt = []
            synced_count = 0
            # 本轮实际核对过的文件 key 集合（增量模式下用于与历史结果合并，避免误清空）
            audited_keys = set()
            # 本轮开始前的异常集合快照，用于判断是否发生变化、抑制重复告警
            prev_anomaly_set = set(self._last_status.get("missing_files", []) or []) | \
                set(self._last_status.get("corrupt_files", []) or [])

            for idx, pair in enumerate(self._sync_pairs):
                src = (pair.get("src") or "").strip().rstrip("/")
                dest = (pair.get("dest") or "").strip().rstrip("/")
                pair_name = pair.get("name") or src
                all_ext = pair.get("all_ext", False)

                if not os.path.exists(src) or not os.path.exists(dest):
                    logger.warning(f"[Rsync115Sync] [{pair_name}] 目录无效或 CD2 挂载未就绪，跳过本组映射: {src} -> {dest}")
                    continue

                # 严格按照 sync_115.sh 黄金参数构建：绝不加 --inplace / --partial / --temp-dir
                cmd = [
                    "rsync",
                    "-rav",
                    "--iconv=UTF-8,UTF-8",
                    "--protect-args",
                    "--no-implied-dirs",
                    "--size-only",
                    "--no-perms",
                    "--no-owner",
                    "--no-group",
                    "--omit-dir-times",
                    f"--timeout={self._rsync_timeout}",
                ]

                # 仅当对端是 rsync 守护进程(rsync://)时才能使用 --contimeout，
                # 本地路径/CD2 挂载场景下携带该参数会直接报语法错误退出码 1。
                if "::" in dest or dest.startswith("rsync://"):
                    cmd.append("--contimeout=30")

                # 排除目录参数
                for ex in self._exclude_patterns.splitlines():
                    ex_clean = ex.strip()
                    if ex_clean:
                        cmd.append(f"--exclude={ex_clean}")

                temp_list_file = None
                pair_files = []
                now_ts = time.time()
                threshold = self._delay_hours * 3600

                if mode == "ready":
                    for key, ts in list(self._pending_queue.items()):
                        if key.startswith(f"{pair_name}:") and (now_ts - ts >= threshold):
                            rel_p = key.split(f"{pair_name}:", 1)[1]
                            if os.path.exists(os.path.join(src, rel_p)):
                                pair_files.append(rel_p)
                            else:
                                self._pending_queue.pop(key, None)

                elif mode in ("retry", "backfill"):
                    # 重试/补传模式：若指定了 custom_files 优先按其处理，
                    # 否则 retry 回退到历史异常清单（backfill 不自动回退，
                    # 其候选由 _api_backfill_start 显式传入）
                    if custom_files:
                        raw_target_keys = custom_files
                    elif mode == "backfill":
                        raw_target_keys = []
                    else:
                        raw_target_keys = list(set(
                            (self._last_status.get("missing_files") or [])
                            + (self._last_status.get("corrupt_files") or [])
                        ))
                    origin = ("（来自用户指定）" if custom_files
                              else ("（补传模式，无候选）" if mode == "backfill" else "（来自历史异常清单）"))
                    logger.info(f"[Rsync115Sync] [{pair_name}] 候选 {len(raw_target_keys)} 个{origin}")

                    ignored_cnt = 0
                    target_keys = []
                    for k in raw_target_keys:
                        if self._is_ignored(k):
                            ignored_cnt += 1
                            logger.info(f"[Rsync115Sync] [{pair_name}] ⏭ 命中忽略规则，跳过: {k}")
                        else:
                            target_keys.append(k)
                    if ignored_cnt:
                        logger.info(f"[Rsync115Sync] [{pair_name}] 共 {ignored_cnt} 个候选因忽略规则被过滤")

                    for key in target_keys:
                        # 兼容处理前缀匹配：
                        # 格式 A: "任务备注名:相对路径"
                        # 格式 B: "相对路径"（当无任务名前缀时）
                        rel_p = None
                        if key.startswith(f"{pair_name}:"):
                            rel_p = key.split(f"{pair_name}:", 1)[1]
                        elif not any(key.startswith(f"{(p.get('name') or p.get('src') or '').strip().rstrip('/')}:") for p in self._sync_pairs):
                            # key 没有任何已知映射前缀，检查文件是否落在当前 src 下
                            if os.path.exists(os.path.join(src, key)):
                                rel_p = key
                            else:
                                logger.debug(f"[Rsync115Sync] [{pair_name}] 前缀不匹配且源端不存在，跳过: {key}")
                        else:
                            # 属于其它映射任务，交由那一组处理
                            logger.debug(f"[Rsync115Sync] [{pair_name}] 该 key 归属其它映射，跳过: {key}")

                        if rel_p is None:
                            continue

                        rel_p = rel_p.lstrip("/")
                        # 确保源端文件确实存在才加入传输列表
                        if not os.path.exists(os.path.join(src, rel_p)):
                            logger.warning(f"[Rsync115Sync] [{pair_name}] ⚠ 源文件已不存在，跳过重试: {rel_p}")
                            continue

                        pair_files.append(rel_p)
                        # 重传前若目标端有大小不一致的残缺文件，先清理确保全新上传秒传
                        dest_f = os.path.join(dest, rel_p)
                        src_f = os.path.join(src, rel_p)
                        if os.path.exists(dest_f) and os.path.exists(src_f):
                            try:
                                if os.path.getsize(dest_f) != os.path.getsize(src_f):
                                    logger.info(f"[Rsync115Sync] [{pair_name}] 🧹 清理目标端残缺文件以便重新秒传: {rel_p}")
                                    os.remove(dest_f)
                            except Exception as e:
                                logger.warning(f"[Rsync115Sync] [{pair_name}] 清理残缺文件失败 {rel_p}: {e}")
                        else:
                            logger.info(f"[Rsync115Sync] [{pair_name}] 🆕 目标端不存在，执行首次上传: {rel_p}")

                # 生成 --files-from 清单文件
                # 关键：ready/retry/backfill 一律走 --files-from，只让 rsync 处理
                # 指定文件，绝不整目录遍历 115 挂载点（那是风控的主要来源）
                if mode in ["ready", "retry", "backfill"]:
                    if not pair_files:
                        # 本次没有需要处理的文件，跳过该目录（不做全盘对账，避免历史存量文件误报）
                        logger.info(f"[Rsync115Sync] [{pair_name}] 本组无待传输文件，跳过（不做全量对账，避免历史存量误报）")
                        continue

                    # ---- 批次上限：单次 rsync 处理量有界，避免命令行过长与瞬时峰值 ----
                    # 裁剪掉的文件留在原队列/清单中，由下一轮 cron 或下次触发继续处理
                    deferred = 0
                    if len(pair_files) > self._upload_batch_size > 0:
                        deferred = len(pair_files) - self._upload_batch_size
                        pair_files = pair_files[:self._upload_batch_size]
                        logger.info(f"[Rsync115Sync] [{pair_name}] ✂ 本批受批次上限限制，"
                                    f"本次处理 {len(pair_files)} 个，剩余 {deferred} 个留待下轮")

                    logger.info(f"[Rsync115Sync] [{pair_name}] 待传输 {len(pair_files)} 个文件:")
                    for _p in pair_files:
                        logger.info(f"[Rsync115Sync] [{pair_name}]   - {_p}")
                    temp_list_file = f"/tmp/rsync_files_{int(time.time())}_{idx}.txt"
                    with open(temp_list_file, "w", encoding="utf-8") as f:
                        for item in pair_files:
                            f.write(f"{item}\n")
                    cmd.append(f"--files-from={temp_list_file}")

                cmd.extend([f"{src}/", dest])

                rsync_start = time.time()
                # 先预留本批配额并落盘：万一进程在传输中被重载，
                # 已上传的文件数不会因为内存状态丢失而绕过限流
                self._current_batch_size = len(pair_files)
                if self._current_batch_size:
                    self._consume_upload_quota(f"（{pair_name} 预留）")

                logger.info(f"[Rsync115Sync] [{pair_name}] ▶ 启动 rsync (模式 {mode}，{len(pair_files)} 个文件)")
                logger.debug(f"[Rsync115Sync] [{pair_name}] 完整命令: {' '.join(shlex.quote(c) for c in cmd)}")

                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
                self._current_process = process

                try:
                    stdout, stderr = process.communicate(timeout=self._task_timeout)
                    exit_code = process.returncode
                except subprocess.TimeoutExpired:
                    logger.error(f"[Rsync115Sync] [{pair_name}] ❌ 传输超时（超过 {self._task_timeout} 秒）强制 Kill！")
                    process.kill()
                    stdout, stderr = process.communicate()
                    exit_code = -9
                    has_error = True

                rsync_cost = int(time.time() - rsync_start)
                # 记录 rsync 关键输出，便于排查传输失败原因
                if exit_code == 0:
                    up_files = [ln for ln in (stdout or "").splitlines() if ln and not ln.endswith("/") and ln != "./"]
                    logger.info(f"[Rsync115Sync] [{pair_name}] ✅ rsync 完成，退出码 0，耗时 {rsync_cost} 秒，"
                                f"输出 {len(up_files)} 行变更记录")
                    for ln in up_files[:20]:
                        logger.info(f"[Rsync115Sync] [{pair_name}]   ⇪ {ln}")
                    if len(up_files) > 20:
                        logger.info(f"[Rsync115Sync] [{pair_name}]   ... 其余 {len(up_files) - 20} 条已省略")
                elif exit_code in self._TOLERATED_EXIT_CODES:
                    # 23=部分未传输、24=源文件消失，属可容忍告警：记录但不判定整轮失败
                    logger.warning(f"[Rsync115Sync] [{pair_name}] ⚠ rsync 退出码 {exit_code}"
                                   f"（{'源文件传输中消失' if exit_code == 24 else '部分文件未传输'}），"
                                   f"耗时 {rsync_cost} 秒，按可容忍处理")
                    warn_tail = (stderr or "").strip().splitlines()[-5:]
                    for ln in warn_tail:
                        logger.warning(f"[Rsync115Sync] [{pair_name}]   ⚠ {ln}")
                else:
                    # 致命退出码：必须置位 has_error，否则增量对账恰好无缺失时
                    # 会被误判为成功并推送“全部完整上传到位”的错误通知
                    has_error = True
                    fatal_exit_codes.append(f"{pair_name}={exit_code}")
                    logger.error(f"[Rsync115Sync] [{pair_name}] ❌ rsync 失败，退出码 {exit_code}，"
                                 f"耗时 {rsync_cost} 秒（判定为致命错误）")
                    warn_tail = (stderr or "").strip().splitlines()[-5:]
                    for ln in warn_tail:
                        logger.error(f"[Rsync115Sync] [{pair_name}]   ✗ {ln}")

                if temp_list_file and os.path.exists(temp_list_file):
                    try:
                        os.remove(temp_list_file)
                    except Exception:
                        pass

                # ---- 风控特征检测：stderr 命中限流关键词立刻进入退避并终止本轮 ----
                if self._rate_limit_enabled and self._detect_rate_limit_hit(stderr):
                    self._trigger_backoff(f"[{pair_name}] rsync 输出命中限流特征")
                    self._post_reply(channel_event, "🚫 检测到 115/CD2 限流特征，已暂停上传并进入退避期。")
                    break

                # ---- 配额中途耗尽：已完成本组，但不再继续下一组映射 ----
                if (self._rate_limit_enabled
                        and self._upload_window_count >= self._upload_max_per_window):
                    logger.warning(f"[Rsync115Sync] 🚦 本窗口配额已用尽"
                                   f"（{self._upload_window_count}/{self._upload_max_per_window}），"
                                   f"剩余映射留待下一轮")
                    break

                # 双向对账审计：ready/retry 仅核对本次同步的文件；force 才做全量扫描
                if mode == "force":
                    m_list, c_list = self._audit_files_integrity(src, dest, pair_name, all_ext, rel_paths=None)
                else:
                    if not pair_files:
                        continue
                    synced_count += len(pair_files)
                    audited_keys.update(f"{pair_name}:{p}" for p in pair_files)
                    m_list, c_list = self._audit_files_integrity(src, dest, pair_name, all_ext, rel_paths=pair_files)
                total_missing.extend(m_list)
                total_corrupt.extend(c_list)

                logger.info(f"[Rsync115Sync] [{pair_name}] 🔍 对账结果: 本次核对 {len(pair_files)} 个，"
                            f"缺失 {len(m_list)} 个，残缺 {len(c_list)} 个")
                for k in m_list:
                    logger.warning(f"[Rsync115Sync] [{pair_name}]   ✗ 缺失未同步: {k}")
                for k in c_list:
                    logger.warning(f"[Rsync115Sync] [{pair_name}]   ✗ 大小残缺: {k}")

                # 同步成功则将已完成的文件移除出冷却队列
                if exit_code == 0 and mode == "ready":
                    for rel_p in pair_files:
                        k = f"{pair_name}:{rel_p}"
                        if k not in m_list and k not in c_list:
                            self._pending_queue.pop(k, None)
                            logger.info(f"[Rsync115Sync] [{pair_name}] 🧊 已移出冷却队列: {rel_p}")

                # 补传模式：无论本批成功与否都从补传队列移除
                # （失败的会进入 missing/corrupt 清单，由 /rsync_retry 接手，
                #   若留在补传队列会与异常清单重复处理）
                if mode == "backfill":
                    for rel_p in pair_files:
                        k = f"{pair_name}:{rel_p}"
                        if k in self._backfill_done_keys:
                            continue
                        self._backfill_done_keys.add(k)

            self.save_data("pending_queue", self._pending_queue)

            # 推进补传队列：移除本轮已处理的文件并落盘
            if mode == "backfill" and self._backfill_done_keys:
                before = len(self._backfill_queue)
                self._backfill_queue = [
                    k for k in self._backfill_queue if k not in self._backfill_done_keys
                ]
                self.save_data("backfill_queue", self._backfill_queue)
                logger.info(f"[Rsync115Sync] 📦 补传队列推进：{before} → {len(self._backfill_queue)}"
                            f"（本轮处理 {len(self._backfill_done_keys)} 个）")

            # 结果合并：
            # - force 全量模式：以本轮全盘扫描结果为准，直接替换。
            # - ready/retry 增量模式：本轮"已核对且恢复正常"的文件移出清单；
            #   本轮未涉及的历史异常项予以保留，避免因为增量对账而误清空。
            if mode == "force":
                final_missing = list(dict.fromkeys(total_missing))
                final_corrupt = list(dict.fromkeys(total_corrupt))
            else:
                prev_missing = self._last_status.get("missing_files", []) or []
                prev_corrupt = self._last_status.get("corrupt_files", []) or []
                # 保留：未被本轮核对过的历史项
                kept_missing = [k for k in prev_missing if k not in audited_keys]
                kept_corrupt = [k for k in prev_corrupt if k not in audited_keys]
                final_missing = list(dict.fromkeys(kept_missing + total_missing))
                final_corrupt = list(dict.fromkeys(kept_corrupt + total_corrupt))

            # 忽略清单内的条目一律不进入异常列表
            final_missing = [k for k in final_missing if not self._is_ignored(k)]
            final_corrupt = [k for k in final_corrupt if not self._is_ignored(k)]

            self._last_status["missing_files"] = final_missing
            self._last_status["corrupt_files"] = final_corrupt
            self.save_data("missing_files", final_missing)
            self.save_data("corrupt_files", final_corrupt)
            total_missing, total_corrupt = final_missing, final_corrupt

            logger.info(f"[Rsync115Sync] 📋 异常清单已更新: 缺失 {len(final_missing)} 个 / 残缺 {len(final_corrupt)} 个 "
                        f"(本轮核对 {len(audited_keys)} 个，模式 {mode})")

            end_time = datetime.now()
            duration = int((end_time - start_time).total_seconds())
            self._last_status["end_time"] = end_time.strftime("%Y-%m-%d %H:%M:%S")

            is_success = (not has_error and not total_missing and not total_corrupt)
            self._last_status["success"] = is_success

            # 判断异常集合是否发生变化（用于抑制重复告警）
            anomaly_now = set(total_missing) | set(total_corrupt)
            anomaly_changed = (anomaly_now != prev_anomaly_set)

            if is_success:
                self._last_status["state"] = "completed"
                if mode == "force":
                    msg = f"🎉 115网盘全量同步与对账完成！\n耗时: {duration} 秒\n未发现任何缺失或残缺文件。"
                    should_notify = True
                elif synced_count == 0:
                    # 定时巡检空转：没有任何文件需要处理，无需打扰用户
                    msg = f"✅ 本轮无需同步（暂无冷却就绪或待重试文件）\n耗时: {duration} 秒\n冷却队列与异常清单均为空。"
                    should_notify = False
                else:
                    msg = f"🎉 115网盘同步与对账完成！\n耗时: {duration} 秒\n本次处理 {synced_count} 个文件，全部完整上传到位。"
                    should_notify = True
            else:
                self._last_status["state"] = "failed"
                # rsync 致命退出码优先说明：此时退出码才是根因，
                # 缺失/残缺计数可能只是它的次生结果
                code_hint = ""
                if fatal_exit_codes:
                    code_hint = f"❌ rsync 失败: {', '.join(fatal_exit_codes)}\n"
                if synced_count > 0:
                    # 有实际传输动作，但仍有未完成项 → 必须报告
                    msg = (
                        f"⚠️ 115同步存在未完成项！\n"
                        f"耗时: {duration} 秒\n"
                        f"{code_hint}"
                        f"📤 本次传输: {synced_count} 个\n"
                        f"🔍 缺失未同步: {len(total_missing)} 个\n"
                        f"🔍 大小残缺: {len(total_corrupt)} 个\n"
                        f"💡 手机端发送 /rsync_retry 即可定向重试异常文件！\n"
                        f"💡 如为不想同步的存量文件，可发送 /rsync_ignore 剧名 忽略。"
                    )
                    should_notify = True
                elif anomaly_changed or fatal_exit_codes:
                    # 异常项有变化，或 rsync 以致命退出码失败 → 报告
                    # （后者即使异常清单无变化也必须上报，否则失败被静默吞掉）
                    msg = (
                        f"⚠️ 115同步异常清单有更新！\n"
                        f"耗时: {duration} 秒\n"
                        f"{code_hint}"
                        f"🔍 缺失未同步: {len(total_missing)} 个\n"
                        f"🔍 大小残缺: {len(total_corrupt)} 个\n"
                        f"💡 手机端发送 /rsync_retry 即可定向重试异常文件！\n"
                        f"💡 如为不想同步的存量文件，可发送 /rsync_ignore 剧名 忽略。"
                    )
                    should_notify = True
                else:
                    # 定时巡检：异常清单与上次完全一致，且本轮无任何传输动作 → 静默，不打扰用户
                    msg = (
                        f"ℹ️ 115定时巡检完成，异常清单无变化\n"
                        f"耗时: {duration} 秒\n"
                        f"🔍 仍待处理: 缺失 {len(total_missing)} 个 / 残缺 {len(total_corrupt)} 个"
                    )
                    should_notify = False

            logger.info(f"[Rsync115Sync] ⏹ 任务结束 (模式 {mode}，耗时 {duration} 秒，传输 {synced_count} 个，"
                        f"状态 {'成功' if is_success else '存在异常'}，通知 {'发送' if (channel_event or (self._notify and should_notify)) else '静默'})")

            # 用户主动发起的命令：无论结果都必须回复给发起人
            if channel_event:
                self._post_reply(channel_event, msg)
            elif self._notify and should_notify:
                # 定时任务没有发起人，必须带上 mtype 才能交由宿主按「通知场景开关」
                # 路由受众。不带 mtype 时 check_message 会跳过范围校验，消息将
                # 广播给所有渠道的所有用户；带 mtype 后默认按「插件」场景 = 仅管理员。
                mtype = self._plugin_mtype()
                if mtype is None:
                    # 无法确定消息类型时宁可不发，也不重演“广播给全部用户”的问题
                    logger.warning(f"[Rsync115Sync] 宿主 MessageType 不可用，已跳过本次通知以免广播："
                                   f"{msg.replace(chr(10), ' | ')}")
                else:
                    self.post_message(mtype=mtype, title="115网盘同步报告", text=msg)
            else:
                logger.info(f"[Rsync115Sync] {msg.replace(chr(10), ' | ')}")

        except Exception as e:
            logger.error(f"[Rsync115Sync] ❌ 同步过程发生异常: {e}\n{traceback.format_exc()}")
            self._post_reply(channel_event, f"❌ 同步过程发生严重异常: {str(e)}")
        finally:
            self._is_running = False
            self._current_process = None
            self._lock.release()

    def _audit_files_integrity(self, source_dir: str, target_dir: str, pair_name: str,
                               all_ext: bool, rel_paths: Optional[List[str]] = None) -> Tuple[List[str], List[str]]:
        """
        对账审计（增量模式）。

        rel_paths 不为 None 时：仅核对本次实际参与同步的文件（冷却就绪 / 定向重试），
        不再全盘 os.walk 整个媒体库，避免历史存量文件被反复误报为缺失。
        rel_paths 为 None 时：执行全量扫描（仅供 force 强制全量模式使用）。
        """
        missing, corrupt = [], []
        if not os.path.exists(source_dir) or not os.path.exists(target_dir):
            return missing, corrupt

        valid_exts = [x.strip().lower() for x in self._media_extensions.split(",") if x.strip()]

        if rel_paths is not None:
            # ---- 增量对账：只检查指定文件 ----
            for rel_f in rel_paths:
                rel_f = (rel_f or "").lstrip("/")
                if not rel_f:
                    continue
                src_f = os.path.join(source_dir, rel_f)
                dest_f = os.path.join(target_dir, rel_f)
                key = f"{pair_name}:{rel_f}"

                if self._is_ignored(key) or not os.path.exists(src_f):
                    continue

                if not os.path.exists(dest_f):
                    missing.append(key)
                    continue

                try:
                    if os.path.getsize(src_f) != os.path.getsize(dest_f):
                        corrupt.append(key)
                except Exception:
                    corrupt.append(key)

            return missing, corrupt

        # ---- 全量对账：force 模式专用 ----
        now_ts = time.time()
        cooling_seconds = self._delay_hours * 3600

        for root, _, files in os.walk(source_dir):
            for f in files:
                if f.startswith("._") or f == ".DS_Store":
                    continue
                if not all_ext:
                    ext = os.path.splitext(f)[-1].lstrip(".").lower()
                    if ext not in valid_exts:
                        continue

                src_f = os.path.join(root, f)
                rel_f = os.path.relpath(src_f, source_dir)
                dest_f = os.path.join(target_dir, rel_f)
                key = f"{pair_name}:{rel_f}"

                # 忽略清单中的文件不参与对账
                if self._is_ignored(key):
                    continue

                # 冷却期内的文件属于正常等待调度，不计入缺失/待重试
                if key in self._pending_queue:
                    enter_ts = self._pending_queue[key]
                    if (now_ts - enter_ts) < cooling_seconds:
                        continue

                if not os.path.exists(dest_f):
                    missing.append(key)
                    continue

                try:
                    if os.path.getsize(src_f) != os.path.getsize(dest_f):
                        corrupt.append(key)
                except Exception:
                    corrupt.append(key)

        return missing, corrupt

    @staticmethod
    def _parse_confirm_indices(arg_str: str, total_count: int) -> List[int]:
        """
        解析用户输入的确认重试序号
        支持格式：
          - "" 或 "all" 或 "全部": 全选 [0..total_count-1]
          - "1": 选单个
          - "1,2" 或 "1 2": 选多个
          - "1-2 4" 或 "1~3": 范围 + 单个混合
        """
        if not arg_str or arg_str.lower() in ["all", "全部"]:
            return list(range(total_count))

        selected = set()
        normalized = arg_str.replace(",", " ").replace("，", " ")
        parts = normalized.split()

        for p in parts:
            if "-" in p or "~" in p:
                sep = "-" if "-" in p else "~"
                subparts = p.split(sep)
                if len(subparts) == 2 and subparts[0].isdigit() and subparts[1].isdigit():
                    start, end = int(subparts[0]), int(subparts[1])
                    for idx in range(min(start, end), max(start, end) + 1):
                        if 1 <= idx <= total_count:
                            selected.add(idx - 1)
            elif p.isdigit():
                idx = int(p)
                if 1 <= idx <= total_count:
                    selected.add(idx - 1)

        return sorted(list(selected))

    # ================= 交互命令分发 (带关键字查找与确认重试) =================

    @eventmanager.register(EventType.PluginAction)
    def handle_command(self, event: Event):
        data = event.event_data or {}
        action = data.get("action")
        # 兼容 MoviePilot 的 arg_str 以及各类渠道传入的参数
        text_arg = (
            data.get("arg_str")
            or data.get("args")
            or data.get("arg")
            or data.get("text")
            or ""
        ).strip()

        if action == "search":
            # 根据关键字从本地源目录或历史记录查找匹配的文件
            if not text_arg:
                self._post_reply(event, "⚠️ 请提供搜索关键字，例如：/rsync_search 繁花")
                return

            keyword = text_arg.lower()
            matched = []

            for pair in self._sync_pairs:
                src_dir = (pair.get("src") or "").strip().rstrip("/")
                pair_name = pair.get("name") or src_dir
                if not os.path.exists(src_dir):
                    continue

                for root, _, files in os.walk(src_dir):
                    for f in files:
                        if keyword in f.lower():
                            rel_f = os.path.relpath(os.path.join(root, f), src_dir)
                            matched.append(f"{pair_name}:{rel_f}")
                            if len(matched) >= 15:
                                break
                    if len(matched) >= 15:
                        break

            if not matched:
                self._post_reply(event, f"🔍 未找到包含关键字「{text_arg}」的本地入库媒体文件。")
                return

            self._waiting_confirm_retries = matched
            list_text = "\n".join([f"{i+1}. {item}" for i, item in enumerate(matched)])
            reply = (
                f"🔍 找到以下 {len(matched)} 个匹配媒体：\n"
                f"--------------------------------\n"
                f"{list_text}\n"
                f"--------------------------------\n"
                f"👉 请发送确认指令触发重传：\n"
                f"• 全部重传: /rsync_confirm (或 /rsync_confirm all)\n"
                f"• 选单序号: /rsync_confirm 1\n"
                f"• 多个序号: /rsync_confirm 1,2 或 /rsync_confirm 1 2\n"
                f"• 范围序号: /rsync_confirm 1-2 4"
            )
            self._post_reply(event, reply)

        elif action == "confirm":
            if not self._waiting_confirm_retries:
                self._post_reply(event, "⚠️ 当前没有等待确认的重试文件，请先发送 /rsync_search <关键字> 查找文件。")
                return

            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中，请稍后再试。")
                return

            # 解析用户输入的序号参数（支持 1 / 1,2 / 1-2 4 / all / 全部 等）
            total_candidates = self._waiting_confirm_retries
            total_count = len(total_candidates)
            selected_indices = self._parse_confirm_indices(text_arg, total_count)

            if not selected_indices:
                self._post_reply(
                    event,
                    f"⚠️ 输入的序号无效！有效范围为 1~{total_count}。\n"
                    f"示例：/rsync_confirm 1 或 /rsync_confirm 1,2 或 /rsync_confirm 1-2 4 或 /rsync_confirm all"
                )
                return

            to_retry = [total_candidates[i] for i in selected_indices]
            self._waiting_confirm_retries = []

            chosen_names = "\n".join([f"• {item}" for item in to_retry])
            self._post_reply(
                event,
                f"✅ 已确认重试 ({len(to_retry)}/{total_count} 个媒体)：\n"
                f"{chosen_names}\n"
                f"--------------------------------\n"
                f"🚀 正在启动定向上传..."
            )
            self._start_sync_thread(mode="retry", custom_files=to_retry, channel_event=event)

        elif action == "sync":
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中。")
            else:
                self._start_sync_thread(mode="ready", channel_event=event)

        elif action == "force":
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中。")
            else:
                self._start_sync_thread(mode="force", channel_event=event)

        elif action == "retry":
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中。")
            else:
                self._start_sync_thread(mode="retry", channel_event=event)

        elif action == "backfill":
            # 只扫源端（零 API），再按批次与限流配额分多轮推进
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中，请稍后再试。")
                return
            self._post_reply(event, "🔍 正在扫描本地入库文件（不访问 115）...")
            candidates = self._build_backfill_candidates()
            if not candidates:
                self._post_reply(event, "✅ 没有需要补传的存量文件。")
                return
            self._backfill_queue = candidates
            self._backfill_total = len(candidates)
            self.save_data("backfill_queue", self._backfill_queue)
            self.save_data("backfill_total", self._backfill_total)
            self._post_reply(
                event,
                f"📦 已建立补传队列：{len(candidates)} 个文件（含同名字幕）\n"
                f"受批次上限 {self._upload_batch_size} 个与限流配额 "
                f"{self._upload_max_per_window} 个/{self._upload_window_secs // 60} 分钟约束，\n"
                f"将分多轮自动推进，可发送 /rsync_status 查看进度。"
            )
            self._start_sync_thread(mode="backfill", custom_files=list(candidates),
                                    channel_event=event)

        elif action == "backfill_clear":
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中，请稍后再试。")
                return
            self._backfill_queue = []
            self._backfill_total = 0
            self.save_data("backfill_queue", [])
            self.save_data("backfill_total", 0)
            self._post_reply(event, "✅ 已清空存量补传队列。")

        elif action == "status":
            st = self._last_status
            state = "正在同步 ⏳" if self._is_running else ("同步完成 ✅" if st.get("success") else "有文件缺失/异常 ⚠️")
            now_ts = time.time()
            threshold = self._delay_hours * 3600
            ready_count = sum(1 for ts in self._pending_queue.values() if now_ts - ts >= threshold)
            cooling_count = len(self._pending_queue) - ready_count

            reply = (
                f"📊 115网盘同步状态报告\n"
                f"当前状态: {state}\n"
                f"冷却就绪可同步: {ready_count} 个\n"
                f"冷却缓冲中: {cooling_count} 个 (设定: {self._delay_hours}h)\n"
                f"彻底缺失文件: {len(st.get('missing_files', []))} 个\n"
                f"残缺不全文件: {len(st.get('corrupt_files', []))} 个\n"
            )
            if len(st.get('missing_files', [])) + len(st.get('corrupt_files', [])) > 0:
                reply += "💡 发送 /rsync_retry 即可立即定向补传异常文件！\n"
            reply += "💡 支持发送 /rsync_search <剧名/电影名> 查找并确认重传指定媒体。"
            if self._ignored_rules:
                reply += f"\n🚫 已忽略规则: {len(self._ignored_rules)} 条 (/rsync_ignore list 查看)"
            self._post_reply(event, reply)

        elif action == "ignore":
            operator = str(data.get("user") or "")
            arg_lower = text_arg.lower()

            # 查看忽略清单
            if arg_lower in ("list", "ls", "列表", ""):
                if not self._ignored_rules:
                    self._post_reply(event, "📋 当前没有任何忽略规则。\n发送 /rsync_ignore <剧名> 即可忽略指定媒体的报警。")
                    return
                lines = [
                    f"{i+1}. [{r.get('match', 'contains')}] {r.get('rule')}  (加入于 {r.get('created_at', '-')})"
                    for i, r in enumerate(self._ignored_rules)
                ]
                reply = (
                    f"📋 当前共 {len(self._ignored_rules)} 条忽略规则：\n"
                    f"--------------------------------\n"
                    + "\n".join(lines) +
                    f"\n--------------------------------\n"
                    f"• 移除指定规则: /rsync_ignore remove 1\n"
                    f"• 清空全部规则: /rsync_ignore clear"
                )
                self._post_reply(event, reply)
                return

            # 清空忽略清单
            if arg_lower in ("clear", "清空", "reset"):
                count = len(self._ignored_rules)
                self._ignored_rules = []
                self.save_data("ignored_files", self._ignored_rules)
                self._post_reply(event, f"✅ 已清空全部 {count} 条忽略规则，相关文件将重新纳入对账。")
                return

            # 移除指定规则
            if arg_lower.startswith("remove") or arg_lower.startswith("del"):
                parts = text_arg.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    idx = int(parts[1]) - 1
                    if 0 <= idx < len(self._ignored_rules):
                        removed = self._ignored_rules.pop(idx)
                        self.save_data("ignored_files", self._ignored_rules)
                        self._post_reply(event, f"✅ 已移除忽略规则：{removed.get('rule')}")
                    else:
                        self._post_reply(event, f"⚠️ 序号超出范围，当前共 {len(self._ignored_rules)} 条规则。")
                else:
                    self._post_reply(event, "⚠️ 用法：/rsync_ignore remove 1")
                return

            # 若输入为纯数字：必须配合搜索结果才按序号精确忽略
            if text_arg.isdigit():
                if not self._waiting_confirm_retries:
                    self._post_reply(
                        event,
                        "⚠️ 纯数字需要在搜索结果上下文中使用。\n"
                        "请先发送 /rsync_search <剧名> 获取列表，再发送 /rsync_ignore 序号。\n"
                        "若想按关键字忽略，请使用剧名而非数字（避免误伤含数字的其它文件）。"
                    )
                    return
                idx = int(text_arg) - 1
                if 0 <= idx < len(self._waiting_confirm_retries):
                    target_key = self._waiting_confirm_retries[idx]
                    ok = self._add_ignore_rule(target_key, match="exact", created_by=operator, source="chat")
                    self._post_reply(
                        event,
                        f"✅ 已忽略：{target_key}" if ok else "⚠️ 该规则已存在。"
                    )
                    return
                self._post_reply(event, f"⚠️ 序号超出范围（1~{len(self._waiting_confirm_retries)}）。")
                return

            # 安全护栏：过短的包含规则极易误伤，要求至少 2 个字符
            if len(text_arg) < 2:
                self._post_reply(event, "⚠️ 忽略关键字过短，请至少输入 2 个字符，以免误伤其它文件。")
                return

            # 关键字忽略（子串包含）
            ok = self._add_ignore_rule(text_arg, match="contains", created_by=operator, source="chat")
            # 若已有搜索结果，提示可精确忽略
            hint = ""
            if self._waiting_confirm_retries:
                hint = f"\n💡 也可用序号精确忽略: /rsync_ignore 1 (对应上一条搜索结果)"
            if ok:
                self._post_reply(
                    event,
                    f"✅ 已加入忽略清单（包含匹配）：\n• {text_arg}\n"
                    f"后续该范围文件不再计入缺失、不再触发重试提醒。{hint}"
                )
            else:
                self._post_reply(event, f"⚠️ 规则「{text_arg}」已存在，无需重复添加。")

    @staticmethod
    def _plugin_mtype():
        """
        返回插件通知使用的消息类型。

        使用「插件」场景：宿主据此读取系统「通知场景开关」里配置的受众范围，
        默认 admin，即只发给各渠道管理员，而不再广播给全部用户。
        """
        if MessageType is None:
            return None
        for attr in ("Plugin", "Other"):
            mtype = getattr(MessageType, attr, None)
            if mtype is not None:
                return mtype
        return None

    def _post_reply(self, event: Optional[Event], text: str):
        """
        回复用户主动发起的命令。

        必须使用 userid 参数指定接收者：post_message 的形参名为 userid，
        若误传 user，该字段会被 Message 模型丢弃，导致 userid 为空，
        消息降级为“广播给所有渠道”，每个用户都会收到本条回复。
        """
        if not event:
            return
        try:
            data = event.event_data or {}
            self.post_message(
                channel=data.get("channel"),
                userid=data.get("user"),
                title="115网盘同步助手",
                text=text,
            )
        except Exception as e:
            logger.warning(f"[Rsync115Sync] 命令回复发送失败: {e}")
