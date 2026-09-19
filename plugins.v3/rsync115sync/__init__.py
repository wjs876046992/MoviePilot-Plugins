import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.core.event import Event, EventType, eventmanager
from app.plugins import _PluginBase
from app.sdk.logging import logger
from app.sdk.services import CronTrigger


class Rsync115Sync(_PluginBase):
    plugin_name = "115网盘同步助手"
    plugin_desc = "需依赖 CloudDrive2 (CD2) 将 115 网盘挂载到本地宿主机并映射至 MoviePilot 容器。专为 CD2 挂载 115 打造：支持入库 N 小时冷却后同步、杜绝 ..* 幽灵临时文件、双向对账审计与命令定向重试。"
    plugin_icon = "mdi-cloud-sync"
    plugin_version = "0.0.1"
    plugin_author = "HermanWu"

    def __init__(self):
        super().__init__()
        self._enabled: bool = False
        self._listen_transfer: bool = True
        self._notify: bool = True
        self._delay_hours: float = 2.0
        self._cron: str = "0 */2 * * *"
        self._auto_clean_ghosts: bool = True

        # 多目录映射对列表: [{"name": "电视剧", "src": "/path/TV", "dest": "/mnt/115/TV", "all_ext": False}]
        self._sync_pairs: List[Dict[str, Any]] = []

        # 严格继承 sync_115.sh 的参数设置
        self._media_extensions: str = "mp4,mkv,avi,mov,ts,m2ts,iso,wmv,flv,rmvb"
        self._exclude_patterns: str = "@eaDir/\n#recycle/\n@__thumb/\n.DS_Store"
        self._rsync_timeout: int = 60
        self._task_timeout: int = 3600

        # 锁与运行时状态
        self._lock = threading.Lock()
        self._is_running: bool = False
        self._current_process: Optional[subprocess.Popen] = None

        # 冷却队列: { "任务名:相对路径": 入库时间戳 float }
        self._pending_queue: Dict[str, float] = {}

        self._last_status: Dict[str, Any] = {
            "state": "idle",
            "start_time": None,
            "end_time": None,
            "success": True,
            "error": "",
            "missing_files": [],      # 完全缺失列表
            "corrupt_files": [],      # 大小异常列表
            "cleaned_ghosts": []      # 已清理的 ..* 幽灵文件
        }

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled", False)
            self._listen_transfer = config.get("listen_transfer", True)
            self._notify = config.get("notify", True)
            self._delay_hours = float(config.get("delay_hours", 2.0))
            self._cron = config.get("cron", "0 */2 * * *")
            self._auto_clean_ghosts = config.get("auto_clean_ghosts", True)
            self._sync_pairs = config.get("sync_pairs") or []
            self._media_extensions = config.get("media_extensions") or "mp4,mkv,avi,mov,ts,m2ts,iso,wmv,flv,rmvb"
            self._exclude_patterns = config.get("exclude_patterns") or "@eaDir/\n#recycle/\n@__thumb/\n.DS_Store"
            self._rsync_timeout = int(config.get("rsync_timeout") or 60)
            self._task_timeout = int(config.get("task_timeout") or 3600)

        # 恢复持久化数据
        saved_queue = self.get_data("pending_queue") or {}
        if isinstance(saved_queue, dict):
            self._pending_queue = saved_queue
        self._last_status["missing_files"] = self.get_data("missing_files") or []
        self._last_status["corrupt_files"] = self.get_data("corrupt_files") or []

    def get_state(self) -> bool:
        return self._enabled

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

            # 匹配属于哪一个配置好的 sync_pair
            for pair in self._sync_pairs:
                src_root = (pair.get("src") or "").strip().rstrip("/")
                pair_name = pair.get("name") or src_root
                if src_root and file_path.startswith(src_root):
                    # 判断扩展名是否满足（非 all_ext 模式下只接收媒体扩展名）
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
                "cmd": "/rsync_retry",
                "event": EventType.PluginAction,
                "desc": "重试失败/缺失的115文件(自动清空残缺)",
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
                "cmd": "/rsync_clean",
                "event": EventType.PluginAction,
                "desc": "扫描并清理网盘中残留的 ..* 临时幽灵文件",
                "category": "工具",
                "data": {"action": "clean"}
            },
            {
                "cmd": "/rsync_status",
                "event": EventType.PluginAction,
                "desc": "查看当前115同步进度与冷却/待重试队列",
                "category": "工具",
                "data": {"action": "status"}
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

    # ================= Web API 接口 (支撑独立前端页面) =================

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/status", "endpoint": self._api_get_status, "methods": ["GET"], "auth": "bear"},
            {"path": "/queue", "endpoint": self._api_get_queue, "methods": ["GET"], "auth": "bear"},
            {"path": "/sync", "endpoint": self._api_trigger_sync, "methods": ["POST"], "auth": "bear"},
            {"path": "/retry", "endpoint": self._api_trigger_retry, "methods": ["POST"], "auth": "bear"},
            {"path": "/clean", "endpoint": self._api_clean_ghosts, "methods": ["POST"], "auth": "bear"}
        ]

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
                "sync_pairs_count": len(self._sync_pairs)
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

    def _api_clean_ghosts(self):
        total_cleaned = []
        for pair in self._sync_pairs:
            dest = (pair.get("dest") or "").strip()
            if dest and os.path.exists(dest):
                total_cleaned.extend(self._scan_and_clean_ghost_files(dest))
        return {"success": True, "cleaned_count": len(total_cleaned), "files": total_cleaned}

    # ================= 核心同步执行逻辑 (严格对齐 sync_115.sh) =================

    def _scheduled_sync(self):
        logger.info("[Rsync115Sync] 触发定时检查同步就绪媒体...")
        self._start_sync_thread(mode="ready")

    def _start_sync_thread(self, mode: str = "ready", channel_event: Optional[Event] = None):
        threading.Thread(target=self._execute_sync, args=(mode, channel_event), daemon=True).start()

    def _execute_sync(self, mode: str = "ready", channel_event: Optional[Event] = None):
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

            all_cleaned_ghosts = []
            if self._auto_clean_ghosts:
                for pair in self._sync_pairs:
                    dest_p = (pair.get("dest") or "").strip()
                    if dest_p and os.path.exists(dest_p):
                        all_cleaned_ghosts.extend(self._scan_and_clean_ghost_files(dest_p))
            self._last_status["cleaned_ghosts"] = all_cleaned_ghosts

            total_pairs = len(self._sync_pairs)
            logger.info(f"[Rsync115Sync] 开始执行同步任务 (模式: {mode}，涉及 {total_pairs} 个目录映射)...")
            self._post_reply(channel_event, f"🚀 开始执行115同步任务 (模式: {mode}，共 {total_pairs} 个映射)...")

            # 遍历每个同步目录执行
            has_error = False
            total_missing = []
            total_corrupt = []

            for idx, pair in enumerate(self._sync_pairs):
                src = (pair.get("src") or "").strip().rstrip("/")
                dest = (pair.get("dest") or "").strip().rstrip("/")
                pair_name = pair.get("name") or src
                all_ext = pair.get("all_ext", False)

                if not os.path.exists(src) or not os.path.exists(dest):
                    logger.warning(f"[Rsync115Sync] 目录无效或挂载未就绪，跳过: {src} -> {dest}")
                    continue

                # 严格按照 sync_115.sh build_rsync_base_args 构建参数
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
                    "--contimeout=30"
                ]

                # 排除目录参数
                for ex in self._exclude_patterns.splitlines():
                    ex_clean = ex.strip()
                    if ex_clean:
                        cmd.append(f"--exclude={ex_clean}")

                # 文件列表筛选
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

                elif mode == "retry":
                    # 重试模式：筛选属于当前目录对的异常文件
                    for key in list(set(self._last_status.get("missing_files", []) + self._last_status.get("corrupt_files", []))):
                        if key.startswith(f"{pair_name}:"):
                            rel_p = key.split(f"{pair_name}:", 1)[1]
                            pair_files.append(rel_p)
                            # 重试前若目标端有大小不一致的坏文件，先清理
                            dest_f = os.path.join(dest, rel_p)
                            src_f = os.path.join(src, rel_p)
                            if os.path.exists(dest_f) and os.path.exists(src_f):
                                if os.path.getsize(dest_f) != os.path.getsize(src_f):
                                    try:
                                        os.remove(dest_f)
                                    except Exception:
                                        pass

                # 生成 --files-from
                if mode in ["ready", "retry"]:
                    if not pair_files:
                        continue
                    temp_list_file = f"/tmp/rsync_files_{int(time.time())}_{idx}.txt"
                    with open(temp_list_file, "w", encoding="utf-8") as f:
                        for item in pair_files:
                            f.write(f"{item}\n")
                    cmd.append(f"--files-from={temp_list_file}")

                cmd.extend([f"{src}/", dest])

                logger.info(f"[Rsync115Sync] [{pair_name}] 执行: {' '.join(cmd[:12])}...")
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
                self._current_process = process

                try:
                    stdout, stderr = process.communicate(timeout=self._task_timeout)
                    exit_code = process.returncode
                except subprocess.TimeoutExpired:
                    logger.error(f"[Rsync115Sync] [{pair_name}] 传输超时强制Kill！")
                    process.kill()
                    stdout, stderr = process.communicate()
                    exit_code = -9
                    has_error = True

                if temp_list_file and os.path.exists(temp_list_file):
                    try:
                        os.remove(temp_list_file)
                    except Exception:
                        pass

                # 双向对账审计
                m_list, c_list = self._audit_files_integrity(src, dest, pair_name, all_ext)
                total_missing.extend(m_list)
                total_corrupt.extend(c_list)

                # 同步成功则将已完成的文件移除出冷却队列
                if exit_code == 0 and mode == "ready":
                    for rel_p in pair_files:
                        k = f"{pair_name}:{rel_p}"
                        if k not in m_list and k not in c_list:
                            self._pending_queue.pop(k, None)

            self.save_data("pending_queue", self._pending_queue)
            self._last_status["missing_files"] = total_missing
            self._last_status["corrupt_files"] = total_corrupt
            self.save_data("missing_files", total_missing)
            self.save_data("corrupt_files", total_corrupt)

            end_time = datetime.now()
            duration = int((end_time - start_time).total_seconds())
            self._last_status["end_time"] = end_time.strftime("%Y-%m-%d %H:%M:%S")

            is_success = (not has_error and not total_missing and not total_corrupt)
            self._last_status["success"] = is_success

            if is_success:
                self._last_status["state"] = "completed"
                msg = f"🎉 115网盘同步与对账完成！\n耗时: {duration} 秒\n所有文件均完整上传到位。"
                if all_cleaned_ghosts:
                    msg += f"\n🧹 顺手清理了 {len(all_cleaned_ghosts)} 个 ..* 幽灵临时文件。"
            else:
                self._last_status["state"] = "failed"
                msg = (
                    f"⚠️ 115同步存在未完成项！\n"
                    f"耗时: {duration} 秒\n"
                    f"🔍 缺失未同步: {len(total_missing)} 个\n"
                    f"🔍 大小残缺: {len(total_corrupt)} 个\n"
                    f"💡 手机端发送 /rsync_retry 即可定向重试异常文件！"
                )

            self._post_reply(channel_event, msg)
            if self._notify and not channel_event:
                self.post_message(title="115网盘同步报告", text=msg)

        except Exception as e:
            logger.error(f"[Rsync115Sync] 同步过程发生异常: {e}")
            self._post_reply(channel_event, f"❌ 同步过程发生严重异常: {str(e)}")
        finally:
            self._is_running = False
            self._current_process = None
            self._lock.release()

    def _scan_and_clean_ghost_files(self, target_dir: str) -> List[str]:
        cleaned = []
        if not os.path.exists(target_dir):
            return cleaned
        for root, _, files in os.walk(target_dir):
            for f in files:
                if f.startswith("..") or (f.startswith(".") and any(ext in f for ext in [".mkv.", ".mp4.", ".iso."])):
                    ghost_p = os.path.join(root, f)
                    try:
                        os.remove(ghost_p)
                        cleaned.append(os.path.relpath(ghost_p, target_dir))
                    except Exception:
                        pass
        return cleaned

    def _audit_files_integrity(self, source_dir: str, target_dir: str, pair_name: str, all_ext: bool) -> Tuple[List[str], List[str]]:
        missing, corrupt = [], []
        if not os.path.exists(source_dir) or not os.path.exists(target_dir):
            return missing, corrupt

        valid_exts = [x.strip().lower() for x in self._media_extensions.split(",") if x.strip()]

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

                if not os.path.exists(dest_f):
                    missing.append(key)
                    continue

                try:
                    if os.path.getsize(src_f) != os.path.getsize(dest_f):
                        corrupt.append(key)
                except Exception:
                    corrupt.append(key)

        return missing, corrupt

    @_PluginBase.event_handler(EventType.PluginAction)
    def handle_command(self, event: Event):
        data = event.event_data or {}
        action = data.get("action")

        if action == "sync":
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

        elif action == "clean":
            cleaned = []
            for pair in self._sync_pairs:
                d = (pair.get("dest") or "").strip()
                if d and os.path.exists(d):
                    cleaned.extend(self._scan_and_clean_ghost_files(d))
            if cleaned:
                self._post_reply(event, f"🧹 已清理 {len(cleaned)} 个残留的 ..* 幽灵临时文件！")
            else:
                self._post_reply(event, "✨ 网盘目录未发现任何 ..* 临时文件。")

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
                reply += "💡 发送 /rsync_retry 即可立即定向补传异常文件！"
            self._post_reply(event, reply)

    def _post_reply(self, event: Optional[Event], text: str):
        if not event:
            return
        try:
            self.post_message(
                channel=event.event_data.get("channel"),
                user=event.event_data.get("user"),
                title="115网盘同步助手",
                text=text
            )
        except Exception:
            pass
