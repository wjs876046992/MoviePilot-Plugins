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

# 宿主公开的窄调度门面。用于保存配置后**主动重建本插件的定时任务** ——
# 配置走本插件自己的 API 时，宿主不会替我们刷新调度（详见 _refresh_scheduled_job）。
# 缺失时降级为 None，不影响插件加载：旧宿主上没有它只是需要手动重载。
# Narrow scheduler facade from the host SDK; None on older hosts.
try:
    from app.sdk.scheduler import update_plugin_job as _update_plugin_job
except Exception:  # pragma: no cover - 兼容旧宿主
    _update_plugin_job = None


def _transfer_success_events() -> List[Any]:
    """
    返回「整理成功」需要监听的全部事件类型。

    All event types that signal a successful transfer/ingest.

    宿主按**文件类型**把整理结果拆成三个事件（app/chain/transfer/settlement.py
    的 _durable_transfer_event）：
        主要媒体文件 → TransferComplete
        字幕文件     → SubtitleTransferComplete
        音频文件     → AudioTransferComplete

    只监听 TransferComplete 会**静默丢掉所有字幕与音频**，表现为「入库很多、
    却只监听到很少」。这里按存在性动态收集，兼容尚未提供后两者的旧宿主。

    The host splits transfer results into three event types by file kind.
    Listening to TransferComplete alone silently drops every subtitle and audio
    file. Types are collected defensively so older hosts still work.
    """
    types: List[Any] = [EventType.TransferComplete]
    for name in ("SubtitleTransferComplete", "AudioTransferComplete"):
        extra = getattr(EventType, name, None)
        if extra is not None and extra not in types:
            types.append(extra)
    return types


# 模块级常量：装饰器在类体执行时求值，故必须在类定义前构造好
_TRANSFER_SUCCESS_EVENTS = _transfer_success_events()

# ---- 已拆分到兄弟模块的纯逻辑（阶段 1 拆分）/ extracted in stage-1 split ----
# 展示与日志上限、重试上限、巡检节流等**纯常量** → constants.py
# 路径与目录映射纯函数                        → paths.py
# 忽略规则匹配                                → ignore.py
# strm 交叉验证的路径推导与三态判定           → strm.py
# 四个模块都不含可变状态：宿主会在实例命名空间中重新执行本文件，但**插件自行
# 导入的模块全局量是共享的**，因此状态必须留在插件实例上（见 DEVELOPMENT.md 8.1）。
#
# 这里用下划线别名导入，是为了让类体与既有调用点无需到处加模块前缀 ——
# 类体在求值时能读到本模块的全局名字（与 _TRANSFER_SUCCESS_EVENTS 同理）。
from . import strm as _strm  # noqa: E402
from .constants import (  # noqa: E402
    DEFAULT_EXCLUDE_PATTERNS,
    DEFAULT_MEDIA_EXTENSIONS,
    DEFAULT_RSYNC_TIMEOUT,
    DEFAULT_TASK_TIMEOUT,
    LEGACY_DEFAULTS as _LEGACY_DEFAULTS,
    MAX_LOGGED_PATHS as _MAX_LOGGED_PATHS,
    MAX_PATH_CHARS as _MAX_PATH_CHARS,
    MISSED_SCAN_ENABLED_DEFAULT as _MISSED_SCAN_ENABLED_DEFAULT,
    MISSED_SCAN_INTERVAL as _MISSED_SCAN_INTERVAL,
    RETRY_KEYWORD_LIMIT as _RETRY_KEYWORD_LIMIT,
    SIDECAR_EXTS as _SIDECAR_EXTS,
    STRM_CHECK_INTERVAL as _STRM_CHECK_INTERVAL,
    STRM_SCAN_LIMIT,
    STRM_VIDEO_EXTENSIONS,
    TOLERATED_EXIT_CODES as _TOLERATED_EXIT_CODES,
)
from .ignore import (  # noqa: E402
    add_rule as _ignore_add_rule,
    filter_ignored as _ignore_filter,
    is_ignored as _ignore_is_ignored,
    remove_rule as _ignore_remove_rule,
)
from .paths import (  # noqa: E402
    brief_paths as _brief_paths,
    excluded_dir_names as _excluded_dir_names,
    pair_for_path as _pair_for_path,
    pair_name as _pair_name,
    valid_exts_of as _valid_exts_of,
)


class Rsync115Sync(_PluginBase):
    plugin_name = "115网盘同步助手"
    plugin_desc = "需依赖 CloudDrive2 (CD2) 将 115 网盘挂载到本地宿主机并映射至 MoviePilot 容器。专为 CD2 挂载 115 打造：支持入库 N 小时冷却后同步、双向对账审计、关键字查找入库重试与手机端交互指令。"
    plugin_icon = "mdi-cloud-sync"
    plugin_version = "0.1.7"
    plugin_author = "HermanWu"

    # rsync 退出码语义见 constants.TOLERATED_EXIT_CODES（含逐码说明）
    _TOLERATED_EXIT_CODES = _TOLERATED_EXIT_CODES

    # 伴生字幕扩展名见 constants.SIDECAR_EXTS（含设计动机说明）
    _SIDECAR_EXTS = _SIDECAR_EXTS

    # ---- 默认参数（与 sync_115.sh 对齐）/ Defaults, aligned with sync_115.sh ----
    # 以下默认值来自 constants.py（模块顶部已导入）。保留为类属性是为了兼容
    # 既有的 self.DEFAULT_* 调用点，并让类自描述其默认行为。
    # Defaults imported from constants.py; kept as class attributes so existing
    # `self.DEFAULT_*` call sites keep working and the class stays self-describing.
    DEFAULT_MEDIA_EXTENSIONS = DEFAULT_MEDIA_EXTENSIONS
    DEFAULT_EXCLUDE_PATTERNS = DEFAULT_EXCLUDE_PATTERNS
    DEFAULT_RSYNC_TIMEOUT = DEFAULT_RSYNC_TIMEOUT
    DEFAULT_TASK_TIMEOUT = DEFAULT_TASK_TIMEOUT

    # 历史默认值与补齐扫描开关：迁移逻辑（_migrate_legacy_defaults）与 __init__
    # 都通过 self.* 访问它们。**别名必须保留** —— 直接删掉类属性会让
    # `self._MISSED_SCAN_ENABLED_DEFAULT` 抛 AttributeError（拆分时实测踩到）。
    # These aliases are load-bearing: __init__ and _migrate_legacy_defaults read them
    # through `self.*`, so removing the class attributes breaks instantiation.
    _LEGACY_DEFAULTS = _LEGACY_DEFAULTS
    _MISSED_SCAN_INTERVAL = _MISSED_SCAN_INTERVAL
    _MISSED_SCAN_ENABLED_DEFAULT = _MISSED_SCAN_ENABLED_DEFAULT

    def __init__(self):
        super().__init__()
        self._enabled: bool = False
        self._listen_transfer: bool = True
        self._missed_scan_enabled: bool = self._MISSED_SCAN_ENABLED_DEFAULT
        self._notify: bool = True
        self._delay_hours: float = 2.0
        self._cron: str = "0 */2 * * *"

        # 多目录映射对列表:
        # [{"name": "电视剧", "src": "/path/TV", "dest": "/mnt/115/TV", "all_ext": False,
        #   "strm_dir": "/path/strm/TV" 或 ""}]
        # Directory mapping pairs. Each entry maps one local source root to one
        # CD2-mounted 115 destination root; `all_ext` disables extension filtering.
        # `strm_dir`（可选，与 src 不同根、由用户配置）启用 strm 交叉验证：
        # 同步成功后观察对应 strm 是否在宽限期内生成，未生成即疑似上传异常。
        # Optional per-pair strm root (different root, user-configured). When set,
        # a successful sync arms a watch: if the matching .strm never appears within
        # the grace window, the file is flagged as a suspected upload failure.
        self._sync_pairs: List[Dict[str, Any]] = []

        # ---- strm 交叉验证（利用 strm 插件生成的本地 .strm 作为独立见证）----
        # ---- Strm cross-validation ----
        #
        # 为什么需要它：CD2 改名失败后，挂载视图显示"文件存在且正常"，插件的
        # 对账与 --size-only 都会被蒙蔽（见 DEVELOPMENT.md 3.11）。而 strm 插件
        # 生成 .strm 的依据与 CD2 视图无关 —— 它是第三方视角的独立见证人，
        # 且读取它只是本地文件系统操作，零 115 API。
        #
        # 三态生命周期（_strm_watch：待观察 → _strm_suspects：疑似异常）：
        #   待观察：同步成功后登记，宽限期内不报警（strm 生成不实时，
        #           可能还在上传/刮削中）；
        #   疑似异常：宽限期到期仍未生成 → 入清单、看板展示、可推送通知，
        #           用户提供处理按钮（删旧重传），**不做无确认的自动重传**
        #           —— strm 插件自身漏生成（媒体不识别/开关关闭）也会表现
        #           为"该有而没有"，与真异常不可区分，误报源无法排除；
        #   解除：重传成功或 strm 已生成 → 移出清单。
        self._strm_watch: Dict[str, float] = {}        # key → 同步成功时间戳
        # key → {"ts": 首次疑似时间戳, "origin": "watch"|"scan"}
        #
        # 为什么值从「时间戳」变成「字典」：疑似有两个来源，可信度不同，
        # 必须分开记录，否则用户看到一批疑似却不知道「为什么突然多出来这些」——
        #   watch：同步成功过、宽限期到期仍无 strm（**可信度高**，该文件确实传过）
        #   scan ：主动扫描发现源端有、strm 端没有（**可能是从未上传过**，属正常存量）
        # 旧格式（纯 float）在 _load 时自动迁移，见 init_plugin。
        # Value shape changed from float to dict to record the suspect's origin.
        self._strm_suspects: Dict[str, Dict[str, Any]] = {}
        self._strm_grace_hours: float = 6.0            # 宽限期（小时），可配置
        self._strm_check_enabled: bool = True          # 总开关（有 strm_dir 的映射才实际生效）
        self._strm_last_check: float = 0.0             # 上次巡检时间（节流）
        self._strm_notified: bool = False              # 疑似清单是否已推送过通知（防重复打扰）

        # 严格继承 sync_115.sh 的参数设置 (绝不用 --inplace, --temp-dir, --partial)
        # Parameters strictly inherited from sync_115.sh.
        # --inplace / --temp-dir / --partial are deliberately NEVER used, because
        # 115's instant-upload (秒传) requires a complete file to hash.
        self._media_extensions: str = self.DEFAULT_MEDIA_EXTENSIONS
        self._exclude_patterns: str = self.DEFAULT_EXCLUDE_PATTERNS
        self._rsync_timeout: int = self.DEFAULT_RSYNC_TIMEOUT
        self._task_timeout: int = self.DEFAULT_TASK_TIMEOUT

        # ---- 上传限流与风控退避（防小文件高频上传触发 115 风控）----
        # Upload throttling and anti-abuse back-off, protecting against 115's
        # rate limiting triggered by bursts of small files.
        # 全局生效：ready / retry / force / 补传 共用同一套窗口计数。
        # Applies globally: ready / retry / force / back-fill all share one
        # window counter and one back-off state.
        # 单位时间是硬闸门，与“单次取多少文件”的分批参数正交，两者都需要。
        # The time-based quota is a hard gate and is orthogonal to the per-run
        # batch size — both are required, they solve different problems.
        self._rate_limit_enabled: bool = True
        self._upload_batch_size: int = 200          # 单批上限 / max files per rsync run
        self._upload_max_per_window: int = 500      # 单窗口配额 / max files per window
        self._upload_window_secs: int = 1800        # 窗口长度(秒) / window length in seconds
        self._backoff_secs: int = 3600              # 退避时长(秒) / back-off duration
        # 命中任一关键词即判定为风控 / any keyword hit is treated as rate limiting
        self._rate_limit_keywords: str = (
            "too many requests\nrate limit\n429\ntoo frequent\n频繁\n操作过快\n请稍后"
        )

        # 限流运行时状态（持久化：窗口计数与退避必须跨重载、跨重启保留）
        # Persisted throttling state. The window counter and back-off deadline
        # must survive reloads and host restarts, otherwise a restart would
        # silently reset the quota and let the next batch bypass the limiter.
        self._upload_window_start: float = 0.0
        self._upload_window_count: int = 0
        self._upload_blocked_until: float = 0.0
        # 当前批次实际提交给 rsync 的文件数，用于成功后扣减配额
        # Files actually handed to rsync in the current batch, used to charge
        # the quota before the transfer starts.
        self._current_batch_size: int = 0

        # 全量校验（force）冷却：该模式会遍历 115 挂载点全目录，
        # 请求量按媒体库文件数计，必须限频而非随意手动触发。
        # Cool-down for the full-verification (force) mode. It walks the entire
        # 115 mount, costing one request per file in the library, so it must be
        # rate-limited rather than freely triggered by hand.
        self._force_cooldown_days: int = 7
        self._last_force_ts: float = 0.0

        # 锁与运行时状态
        self._lock = threading.Lock()
        self._is_running: bool = False
        self._current_process: Optional[subprocess.Popen] = None
        # 补传扫描互斥锁：防止用户连点按钮触发多次并发的全库目录遍历
        # 与上面的 _lock 分开：扫描是只读的，不应阻塞（也不应被）同步任务占用，
        # 但必须与其他扫描互斥
        self._backfill_scan_lock = threading.Lock()

        # 冷却队列: { "任务名:相对路径": 入库时间戳 float }
        self._pending_queue: Dict[str, float] = {}

        # 待确认的交互重试列表（关键字查找结果）：[{"key": "...", "path": "..."}]
        self._waiting_confirm_retries: List[str] = []

        # 冷却队列等待期错过的入库事件：{"任务名:相对路径": 首次错过时间戳}
        #
        # 为什么需要它：事件走 durable outbox（at-least-once），投递时若插件不可用
        # 会进入有限重试，**超过重试上限即永久丢失**。事件一旦错过就不会重放，
        # 只能在每轮同步开头扫一次源端目录、拿文件 mtime 与本队列比对来补齐。
        #
        # （早期注释称「宿主只在整理批次收尾时广播」，该说法已撤回，见 3.8.1：
        #  事件是**按文件即时发布**的，与按批次合并的用户通知是两条独立路径。）
        #
        # 注意这些条目**不参与冷却计时**：冷却的目的是「等外挂字幕下载完
        # 再上传」，而这些文件已经比原计划多等了很久，再等一轮毫无意义。
        # Missed events cannot be replayed, so each sync run may scan the source
        # roots and compare file mtimes against this queue.
        # (The earlier "batch-finalisation broadcast" rationale was retracted.)
        # These entries intentionally do NOT take part in cool-down timing.
        self._missed_queue: Dict[str, float] = {}
        # 上次源端补齐扫描的成果，供看板与指令回显（0 表示尚未扫描过）
        self._missed_last_scan: int = 0

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
        """
        初始化插件：读取配置并恢复持久化状态。

        Initialise the plugin. Must be safely re-callable — the host invokes it on
        every reload, restart and virtual-instance creation. Restores the
        cool-down queue, anomaly lists, back-fill queue and throttle state
        so no progress is lost across reloads.
        """
        if config:
            self._enabled = config.get("enabled", False)
            self._listen_transfer = config.get("listen_transfer", True)
            self._missed_scan_enabled = bool(
                config.get("missed_scan_enabled", self._MISSED_SCAN_ENABLED_DEFAULT)
            )
            self._notify = config.get("notify", True)
            self._delay_hours = float(config.get("delay_hours", 2.0))
            self._cron = config.get("cron", "0 */2 * * *")
            self._sync_pairs = config.get("sync_pairs") or []
            self._media_extensions = config.get("media_extensions") or self.DEFAULT_MEDIA_EXTENSIONS
            self._exclude_patterns = config.get("exclude_patterns") or self.DEFAULT_EXCLUDE_PATTERNS
            self._rsync_timeout = int(config.get("rsync_timeout") or self.DEFAULT_RSYNC_TIMEOUT)
            self._task_timeout = int(config.get("task_timeout") or self.DEFAULT_TASK_TIMEOUT)
            # 上传限流配置：允许用户按自己的风控容忍度调整
            self._rate_limit_enabled = bool(config.get("rate_limit_enabled", True))
            self._upload_batch_size = max(0, int(config.get("upload_batch_size") or 200))
            self._upload_max_per_window = max(0, int(config.get("upload_max_per_window") or 500))
            self._upload_window_secs = max(1, int(config.get("upload_window_secs") or 1800))
            self._backoff_secs = max(1, int(config.get("backoff_secs") or 3600))
            if config.get("rate_limit_keywords"):
                self._rate_limit_keywords = config.get("rate_limit_keywords")
            self._force_cooldown_days = max(0, int(config.get("force_cooldown_days") or 7))
            # strm 交叉验证配置（总开关与宽限期；每映射的 strm_dir 在 sync_pairs 内）
            self._strm_check_enabled = bool(config.get("strm_check_enabled", True))
            self._strm_grace_hours = max(0.5, float(config.get("strm_grace_hours") or 6.0))
            # 老配置迁移：把「从未调整过」的旧默认值平滑升到新默认值
            self._migrate_legacy_defaults(config)

        # 恢复限流窗口与退避状态（必须早于任何上传判定）
        self._load_rate_limit_state()
        self._last_force_ts = float(self.get_data("last_force_ts") or 0.0)

        # 恢复持久化数据
        saved_queue = self.get_data("pending_queue") or {}
        if isinstance(saved_queue, dict):
            self._pending_queue = saved_queue
        self._last_status["missing_files"] = self.get_data("missing_files") or []
        self._last_status["corrupt_files"] = self.get_data("corrupt_files") or []
        saved_ignored = self.get_data("ignored_files") or []
        if isinstance(saved_ignored, list):
            self._ignored_rules = saved_ignored
        # 恢复「冷却期错过的入库事件」待补扫队列
        saved_missed = self.get_data("missed_queue") or {}
        if isinstance(saved_missed, dict):
            self._missed_queue = saved_missed
        self._missed_last_scan = int(self.get_data("missed_last_scan") or 0)
        if self._missed_queue:
            logger.info(f"[Rsync115Sync] 🕳️ 已恢复错过的入库待补扫清单：{len(self._missed_queue)} 个"
                        f"（将在每轮同步开头扫描源端目录补齐）")

        # 恢复未完成的补传队列，保证跨重载/重启继续推进
        saved_backfill = self.get_data("backfill_queue") or []
        if isinstance(saved_backfill, list):
            self._backfill_queue = saved_backfill
        self._backfill_total = int(self.get_data("backfill_total") or 0)
        if self._backfill_queue:
            logger.info(f"[Rsync115Sync] 📦 已恢复存量补传队列：剩余 {len(self._backfill_queue)} 个"
                        f"（原始 {self._backfill_total} 个），将由定时巡检继续推进")

        # 恢复 strm 交叉验证状态（待观察清单必须跨重载延续，否则宽限期重新计时）
        saved_watch = self.get_data("strm_watch") or {}
        if isinstance(saved_watch, dict):
            self._strm_watch = saved_watch
        saved_suspects = self.get_data("strm_suspects") or {}
        if isinstance(saved_suspects, dict):
            self._strm_suspects = self._migrate_strm_suspects(saved_suspects)
            # 载入即清洗历史脏数据（非视频 / 已忽略 / 源端已删 / 映射取消验证）。
            # 放在这里而不是只在写入时过滤：写入过滤拦不住升级前已落盘的坏条目，
            # 用户会看到一堆永远处理不掉的东西，只能手工改数据文件。
            self._prune_invalid_strm_suspects()
        self._strm_notified = bool(self.get_data("strm_notified") or False)
        if self._strm_watch or self._strm_suspects:
            logger.info(f"[Rsync115Sync] 📺 已恢复 strm 交叉验证状态："
                        f"待观察 {len(self._strm_watch)} / 疑似异常 {len(self._strm_suspects)}")

        # 启动摘要：此前 init_plugin 一条日志都没有，导致用户无法从日志判断
        # 到底装的是哪个版本、事件是否已注册、映射是否读到 —— 排查「入库数量对不上」
        # 时只能靠猜。这里把关键状态一次性打出来，版本号放在最前面便于核对。
        # Startup summary. Without it there was no way to tell from the logs which
        # version was actually loaded, which made version mix-ups undiagnosable.
        try:
            event_names = ",".join(
                str(getattr(e, "value", e)) for e in _TRANSFER_SUCCESS_EVENTS
            )
            pair_summary = ", ".join(
                f"{(p.get('name') or p.get('src') or '?')}=>{(p.get('dest') or '?')}"
                for p in self._sync_pairs
            ) or "（无）"
            logger.info(
                f"[Rsync115Sync] v{self.plugin_version} 初始化完成 | "
                f"启用={self._enabled} 监听入库={self._listen_transfer} | "
                f"冷却={self._delay_hours}h 定时={self._cron} | "
                f"监听事件={event_names} | "
                f"映射 {len(self._sync_pairs)} 组: {pair_summary} | "
                f"队列: 冷却 {len(self._pending_queue)} / 补传 {len(self._backfill_queue)}"
                f" / 待补扫 {len(self._missed_queue)} | "
                f"限流={'开' if self._rate_limit_enabled else '关'}"
                f"({self._upload_batch_size}/批, {self._upload_max_per_window}/窗口)"
            )
        except Exception as log_err:  # 摘要日志失败绝不能影响插件加载
            logger.warning(f"[Rsync115Sync] 初始化摘要日志输出失败（已忽略）: {log_err}")

    def get_state(self) -> bool:
        return self._enabled

    # ---- 忽略规则：匹配逻辑在 ignore.py，本类只负责持久化 ----
    # 状态（_ignored_rules 列表）留在实例上，模块不持有副本，避免出现两个真相来源。

    def _is_ignored(self, key: str) -> bool:
        """检查某个文件 key 是否命中了忽略规则（大小写不敏感）。"""
        return _ignore_is_ignored(key, self._ignored_rules)

    def _add_ignore_rule(self, rule: str, match: str = "contains", created_by: str = "", source: str = "chat") -> bool:
        """添加一条忽略规则，并同步剔除已存在于缺失/残缺清单里的项。"""
        if not _ignore_add_rule(self._ignored_rules, rule, match, created_by, source):
            return False
        self.save_data("ignored_files", self._ignored_rules)

        # 立即联动剔除已有的 missing/corrupt：否则被忽略的文件仍会显示在异常
        # 清单里直到下一轮同步，用户会以为「忽略了没用」。
        self._last_status["missing_files"] = _ignore_filter(
            self._last_status.get("missing_files", []), self._ignored_rules)
        self._last_status["corrupt_files"] = _ignore_filter(
            self._last_status.get("corrupt_files", []), self._ignored_rules)
        self.save_data("missing_files", self._last_status["missing_files"])
        self.save_data("corrupt_files", self._last_status["corrupt_files"])

        # strm 疑似清单与待观察清单同样要清理 —— 否则用户忽略之后，
        # 清单里那些条目还挂着（看板照旧显示、还可被「全部删旧重传」波及），
        # 同样会让人觉得「忽略了没用」。此处是用户实测反馈的补漏。
        # Purge strm lists too, else ignored entries linger on the dashboard.
        for key in list(self._strm_suspects.keys()):
            if _ignore_is_ignored(key, self._ignored_rules):
                self._strm_suspects.pop(key, None)
        for key in list(self._strm_watch.keys()):
            if _ignore_is_ignored(key, self._ignored_rules):
                self._strm_watch.pop(key, None)
        self.save_data("strm_suspects", self._strm_suspects)
        self.save_data("strm_watch", self._strm_watch)
        # 清单可能因此清空，重置通知闩锁（与 _strm_arm_watch 同一收尾逻辑）
        self._reset_strm_notified_if_clear()
        return True

    def _remove_ignore_rule(self, index_or_rule: Any) -> bool:
        """移除指定忽略规则（按序号或规则文本）。"""
        if not _ignore_remove_rule(self._ignored_rules, index_or_rule):
            return False
        self.save_data("ignored_files", self._ignored_rules)
        return True

    # ================= 监听 MoviePilot 媒体转移完成事件 =================
    #
    # ⚠️ 这行装饰器是**整个插件的入口**，删掉它不会有任何报错 —— 插件照常加载、
    # 看板照常渲染、定时同步照常跑，只是**永远收不到入库事件**，表现为「冷却队列
    # 永远是 0」。v0.1.7 的拆分（ed2ba1d）曾把它连同上方的分节注释一起删掉，
    # 前端与后端均无任何提示，属于最难自查的一类回归。改动本文件时务必保留。
    #
    # This decorator is the plugin's only ingest entry point. Removing it raises no
    # error anywhere: the plugin loads, the dashboard renders, cron runs — it simply
    # never receives ingest events, so the cool-down queue stays empty forever.
    @eventmanager.register(_TRANSFER_SUCCESS_EVENTS)
    def on_transfer_complete(self, event: Event):
        """
        事件入口：仅做异常兜底，业务逻辑见 _handle_transfer_event。

        Event entry point. Only guards against exceptions — the actual work lives
        in _handle_transfer_event.

        为什么要拆这两层：宿主把事件处理器丢到线程池执行，**未捕获的异常会被
        记为「插件错误」**（官方事件说明明确指出「异常要自己捕获」）。
        入库排队涉及文件系统探测与状态落盘，任何意外都不该污染宿主错误统计，
        更不该因为一个文件出问题就中断整批事件处理。
        兜底后仅记日志：单个事件失败不影响其余事件，也不影响插件运行。
        """
        try:
            self._handle_transfer_event(event)
        except Exception as err:
            # 记完整堆栈便于定位；不 re-raise，避免被宿主记为插件错误
            logger.error(f"[Rsync115Sync] v{self.plugin_version} 处理整理事件时异常"
                         f"（已兜底，不影响其它事件）: {err}")
            logger.debug(f"[Rsync115Sync] 事件处理异常堆栈:\n{traceback.format_exc()}")

    def _handle_transfer_event(self, event: Event):
        """
        监听媒体转移/字幕/音频整理完成事件，把新入库文件放入冷却队列。

        Handle the media-transfer-complete event: enqueue newly ingested files
        into the cool-down queue. The delay gives external subtitles time to
        download before the initial upload happens.

        ⚠️ 必须同时监听字幕与音频事件（2026-09 修复的一起「46 个只监听到 3 个」）：
        宿主按**文件类型**把整理完成结果拆成三个事件（见 app/chain/transfer/
        settlement.py 的 _durable_transfer_event）：
            主要媒体文件 → TransferComplete
            字幕文件     → SubtitleTransferComplete
            音频文件     → AudioTransferComplete
        此前只注册了 TransferComplete，于是**字幕与音频文件完全不会入队**。

        The host splits transfer results into three event types by file kind
        (see _durable_transfer_event). Registering only TransferComplete silently
        drops every subtitle and audio file.
        """
        if not self._enabled or not self._listen_transfer:
            return

        # 按平台推荐方式读取 payload：优先用 event.snapshot() 拿到**类型化快照**，
        # 失败时回退到原始 dict。
        #
        # 为什么用 snapshot()：宿主对 TransferComplete 登记了契约
        # （app/runtime/event/contracts.py 的 _PAYLOAD_MODELS →
        # TransferResultContractData，且 TransferComplete 在 _SNAPSHOT_EVENTS 内），
        # 快照会按契约把 payload 解析成 Pydantic 模型，字段名与类型由宿主保证；
        # 而原始 event_data 是「保持插件旧对象字段不变」的兼容形状，
        # 字段一旦调整就只会静默读到空值 —— 这正是本项目前几轮反复踩的坑。
        #
        # 但**必须保留回退**：旧宿主可能没有 snapshot()，或事件未登记契约
        # （此时 snapshot.payload 为 None），直接改用快照会让原本能工作的
        # 事件全部读不到数据。故两者并存，并在日志中标注实际来源。
        #
        # Prefer the platform-recommended typed snapshot, but keep the raw dict as a
        # fallback: an unregistered contract or older host yields payload=None, and
        # dropping the raw path would break otherwise-working events.
        transfer_info = None
        file_item = None
        payload_source = "raw"
        snapshot = None
        snapshot_fn = getattr(event, "snapshot", None)
        if callable(snapshot_fn):
            try:
                snapshot = snapshot_fn()
            except Exception as snap_err:
                # 快照解析失败绝不能影响事件处理，直接走回退
                logger.debug(f"[Rsync115Sync] event.snapshot() 调用失败，回退原始 dict: {snap_err}")
                snapshot = None
        if snapshot is not None:
            typed = getattr(snapshot, "payload", None)
            if typed is not None:
                transfer_info = getattr(typed, "transferinfo", None)
                file_item = getattr(typed, "fileitem", None)
                if transfer_info is not None:
                    payload_source = "snapshot"
                    # 契约存在但校验有错时不阻断处理，只留痕便于排查字段变更
                    if getattr(snapshot, "errors", None):
                        logger.debug(f"[Rsync115Sync] 事件快照存在校验告警（不影响处理）: "
                                     f"{getattr(snapshot, 'errors', ())}")

        # 回退：原始 dict（兼容未登记契约的旧宿主）
        event_data = event.event_data or {}
        if transfer_info is None:
            transfer_info = event_data.get("transferinfo")
        if file_item is None:
            file_item = event_data.get("fileitem")

        if not transfer_info:
            logger.info(f"[Rsync115Sync] v{self.plugin_version} 收到整理完成事件但缺少 transferinfo，已忽略"
                        f"（事件={getattr(event.event_type, 'value', event.event_type)}"
                        f"，读取方式={payload_source}）")
            return

        # 路径来源按可靠性降级：file_list_new（实际落库路径，最可靠）
        #                     → file_list（整理前的全部文件）
        #                     → payload 里的 fileitem.path（源文件，兜底）
        #
        # 为什么要回退：`file_list_new` 的模型默认值是空 list，宿主**28 个
        # TransferInfo 构造点里有 25 个不显式赋值**（多为失败分支/中间态，
        # 见 DEVELOPMENT.md 3.8.2）。因此该字段为空是**真实存在的情况**。
        # （注意：这是「可能为空」，**不是**「按文件类型刻意置空」——后者查无依据。）
        #
        # 语义差别要留意：fileitem.path 是**下载器源路径**，而 file_list_new 是
        # **整理后的库内路径**。源路径通常不在媒体库映射内，故可能匹配不到映射；
        # 匹配不到只记日志，绝不错误入队。
        #
        # Path source, most to least reliable. file_list_new can legitimately be
        # empty (25 of 28 constructor sites rely on the default), so fall back.
        # Note fileitem.path is the downloader source path, not the library path.
        file_list = list(getattr(transfer_info, "file_list_new", []) or [])
        path_source = "file_list_new"
        if not file_list:
            file_list = list(getattr(transfer_info, "file_list", []) or [])
            if file_list:
                path_source = "file_list"
        if not file_list:
            # file_item 已在上方按 snapshot → 原始 dict 的顺序解析好
            fallback_path = getattr(file_item, "path", None) if file_item else None
            if fallback_path:
                file_list = [fallback_path]
                path_source = "fileitem.path"
        fallback_used = path_source != "file_list_new"

        now_ts = time.time()
        added_count = 0
        skipped_count = 0
        unmatched_count = 0
        duplicate_count = 0
        # 按原因分类收集，便于日志给出可行动结论。
        # ⚠️ 关键：**先判映射归属，再判文件是否存在**。
        # 原实现先判存在、不存在就 continue，导致「不在任何映射内」这个计数
        # 永远为 0 —— 不是真的匹配上了，而是根本没走到映射判断。
        # 这会掩盖病因：分不清「宿主给的库路径与你配置的源目录不一致」
        # （改配置即可）与「路径对但容器里读不到」（挂载/映射问题）。
        # Classify by cause, and evaluate mapping membership BEFORE existence,
        # so the two diagnoses stay distinguishable in the log.
        added_paths: List[str] = []
        missing_paths: List[str] = []      # 归属某映射，但文件在容器内不存在
        unmatched_paths: List[str] = []    # 不属于任何映射（含配置为空的场景）

        for file_path in file_list:
            if not file_path:
                skipped_count += 1
                continue

            # 第一步：判定映射归属。这一步必须独立于文件是否存在 ——
            # 否则无法区分「路径不属于任何映射」与「路径属于映射但读不到」。
            own_pair = _pair_for_path(file_path, self._sync_pairs)

            if own_pair is None:
                unmatched_count += 1
                unmatched_paths.append(file_path)
                continue

            src_root = (own_pair.get("src") or "").strip().rstrip("/")
            pair_name = _pair_name(own_pair)

            # 扩展名过滤（映射配了 all_ext 则不过滤）
            if not own_pair.get("all_ext", False):
                ext = os.path.splitext(file_path)[-1].lstrip(".").lower()
                valid_exts = [x.strip().lower() for x in self._media_extensions.split(",") if x.strip()]
                if ext not in valid_exts:
                    skipped_count += 1
                    continue

            # 第二步：归属已确定，此时才检查文件在容器内是否可见。
            # 明确归入「缺失」而不是笼统的「跳过」—— 这条最能定位挂载/路径映射问题。
            if not os.path.exists(file_path):
                missing_paths.append(file_path)
                continue

            rel_path = os.path.relpath(file_path, src_root)
            queue_key = f"{pair_name}:{rel_path}"
            # 幂等：已在队列中的条目**保留原入库时间**，不刷新时间戳。
            # 宿主的整理事件走 durable outbox（at-least-once），同一事件可能
            # 被重复投递；若无条件覆盖时间戳，每次重投都会把冷却重新计时，
            # 表现为「明明是 1 小时前入库的文件，冷却永远走不完」。
            # Idempotent: keep the original timestamp instead of refreshing it.
            if queue_key in self._pending_queue:
                duplicate_count += 1
                continue
            self._pending_queue[queue_key] = now_ts
            # 该文件已经补上，从「错过待补扫」清单里移除，避免下轮重复判定
            self._missed_queue.pop(queue_key, None)
            added_count += 1
            added_paths.append(rel_path)

        event_value = getattr(event.event_type, "value", event.event_type)
        if added_count > 0:
            self.save_data("pending_queue", self._pending_queue)
            if self._missed_queue:
                self.save_data("missed_queue", self._missed_queue)
            logger.info(f"[Rsync115Sync] v{self.plugin_version} 监听到 {added_count} 个新入库文件"
                        f"（事件={event_value}，读取方式={payload_source}"
                        f"{f'，路径来源={path_source}（回退）' if fallback_used else ''}"
                        f"{f'，重复投递已跳过 {duplicate_count} 个' if duplicate_count else ''}）"
                        f"，已加入 {self._delay_hours}h 延迟冷却队列: "
                        f"{_brief_paths(added_paths)}")
        elif duplicate_count:
            # 重复投递不是问题（幂等已处理），但值得留痕，否则会误判成「没监听」
            logger.info(f"[Rsync115Sync] v{self.plugin_version} 事件中的 {duplicate_count} 个文件"
                        f"已在冷却队列中，未刷新其冷却计时"
                        f"（事件={event_value}，队列共 {len(self._pending_queue)} 条，读取方式={payload_source}）")
        elif missing_paths and not unmatched_paths:
            # 归属映射明确、但容器内读不到该文件。
            # ⚠️ 这是**最值得警惕**的一类：若路径前缀与你的映射一致却读不到，
            # 说明宿主机路径与容器内挂载不一致（或文件已被移动/删除）。
            # 保持 INFO 并给出完整路径，这是定位挂载问题的关键证据。
            # Owned by a mapping but unreadable inside the container — the most
            # important case: the prefix matches, so this points at a host/container
            # path-mapping mismatch (or the file having moved).
            logger.info(f"[Rsync115Sync] v{self.plugin_version} 入库事件路径在本容器内不可见"
                        f"（事件={event_value}，共 {len(missing_paths)} 个；"
                        f"路径前缀与映射一致但读不到，请检查宿主机目录是否已映射进容器）: "
                        f"{_brief_paths(missing_paths)}")
        elif unmatched_paths:
            # 路径不属于任何映射 —— 配置问题，给出现有映射便于对照
            mapping_desc = ", ".join(
                (p.get("src") or "?") for p in self._sync_pairs
            ) or "（尚未配置任何映射）"
            logger.info(f"[Rsync115Sync] v{self.plugin_version} 入库事件路径不在任何映射内"
                        f"（事件={event_value}，共 {len(unmatched_paths)} 个，读取方式={payload_source}）: "
                        f"{_brief_paths(unmatched_paths)}"
                        f"；当前映射的源目录: {mapping_desc}")
        else:
            # 其余情况（路径为空、扩展名被过滤等）无需用户行动，降为 debug
            logger.debug(f"[Rsync115Sync] v{self.plugin_version} 整理完成事件未入队"
                         f"（事件={event_value}，共 {len(file_list)} 个路径："
                         f"空路径/扩展名被过滤 {skipped_count}"
                         f"{f'，路径来源={path_source}（回退）' if fallback_used else ''}）")

    def _scan_missed_ingest(self) -> int:
        """
        扫描各映射的源端目录，补齐「冷却等待期间错过的入库事件」。

        Reconcile the queue with the source roots: pick up ingest events that were
        missed while the plugin was unavailable.

        为什么不能在事件里补：事件走 durable outbox，投递时插件若不可用会进入有限
        重试，超过上限即永久丢失；事件错过不会重放。因此只能反过来查：
        每轮同步开头扫一次源端目录，用文件 mtime 与「上次扫描时间」比对，
        把新出现的文件补进队列。（早期此处称「宿主只在批次收尾广播」，已撤回，见 3.8.1。）

        成本：每轮同步**每映射一次** os.walk —— 全部是本地目录遍历，
        不触碰 115 挂载点，因此不产生 115 API 请求、不触发风控。
        这与补传前置扫描（_api_backfill_scan）的成本性质相同。

        Cost: one os.walk per mapping per sync run, purely over local source
        directories. It never touches the 115 mount, so it costs no 115 API
        requests and cannot trigger rate limiting.

        :return: 本次新补入的文件数 / number of files newly enqueued
        """
        now_ts = time.time()
        # 首轮没有基准时间：只建立基准，避免把存量媒体整库灌进队列
        if not self._missed_last_scan:
            self._missed_last_scan = now_ts
            self.save_data("missed_last_scan", self._missed_last_scan)
            logger.info("[Rsync115Sync] 首次源端补齐扫描：仅建立时间基准，本次不入队")
            return 0

        # 扫描间隔下限：媒体库很大时，每轮同步都整树遍历代价过高
        # （冷启动、频繁手动同步、补传连跑等场景）。事件丢失是低频问题，
        # 隔一段时间扫一次已足够，且漏掉的事件在下次扫描仍会被 mtime 捞出来。
        # Throttle: a full tree walk on every run is too costly for large
        # libraries. Missed events are low-frequency and stay discoverable by
        # mtime, so an interval floor loses nothing but wasted I/O.
        if now_ts - self._missed_last_scan < self._MISSED_SCAN_INTERVAL:
            return 0

        since = self._missed_last_scan
        added = 0
        for pair in self._sync_pairs:
            src_root = (pair.get("src") or "").strip().rstrip("/")
            pair_name = _pair_name(pair)
            if not src_root or not os.path.isdir(src_root):
                continue
            valid_exts = _valid_exts_of(self._media_extensions, pair.get("all_ext", False))
            # 与同步/搜索/补传共用同一份排除目录口径。此处原先是硬编码的
            # ("@eaDir", "#recycle", "@__thumb")，用户在配置页修改排除规则后，
            # 补齐扫描仍会照旧下钻那些目录 —— 表现为「明明排除了，却还是被捞进来」。
            # 复用 paths.excluded_dir_names() 后三处口径不可能再漂移。
            # Shares the exclusion set with sync/search/backfill. Previously hardcoded,
            # so a user's edited exclude rules were ignored by this scan.
            excluded_dirs = _excluded_dir_names(self._exclude_patterns)

            for dirpath, dirnames, filenames in os.walk(src_root):
                # 跳过被排除的目录，避免遍历群晖元数据目录
                dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
                for fn in filenames:
                    if valid_exts is not None:
                        ext = os.path.splitext(fn)[-1].lstrip(".").lower()
                        if ext not in valid_exts:
                            continue
                    full = os.path.join(dirpath, fn)
                    try:
                        mtime = os.path.getmtime(full)
                    except OSError:
                        continue
                    if mtime <= since:
                        continue
                    rel_path = os.path.relpath(full, src_root)
                    queue_key = f"{pair_name}:{rel_path}"
                    # 已在冷却队列或已在待补扫清单中的都不重复计入，
                    # 否则每轮扫描都会重复“发现 N 个遗漏”并刷警告
                    if queue_key in self._pending_queue or queue_key in self._missed_queue:
                        continue
                    # 补入的条目按「首次错过时间」计时，但同步筛选时走 missed 通道
                    # 不参与冷却，见 _collect_ready 的说明
                    self._missed_queue[queue_key] = now_ts
                    added += 1

        self._missed_last_scan = now_ts
        self.save_data("missed_last_scan", self._missed_last_scan)
        if added:
            self.save_data("missed_queue", self._missed_queue)
            logger.warning(f"[Rsync115Sync] 🕳️ 源端补齐扫描发现 {added} 个可能错过事件的入库文件，"
                           f"已加入待同步清单（不参与冷却，下轮直接同步）")
        else:
            logger.info("[Rsync115Sync] 源端补齐扫描完成：无遗漏")
        return added

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
                "cmd": "/rsync_strm",
                "event": EventType.PluginAction,
                "desc": "扫描缺 strm 的媒体文件（<文件名> 只查指定文件 / clear 清空清单 / prune 清理无效项）",
                "category": "工具",
                "data": {"action": "strm"}
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
        """
        注册定时巡检服务（cron 可配置）。

        Register the periodic inspection service. Each tick resumes an unfinished
        back-fill queue first, otherwise runs a normal ready-sync.
        """
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
        """
        声明使用 Vue 联邦组件渲染，产物目录为 dist/assets。

        Declare Vue module-federation rendering; the built bundle lives in
        dist/assets and is served by the host.
        """
        return "vue", "dist/assets"

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [], {}

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self):
        """
        停止插件：终止在跑的 rsync 进程并复位运行标志。

        Stop the plugin: kill any running rsync process and clear the running
        flag, so a reload does not leave an orphan transfer behind.
        """
        if self._current_process:
            try:
                self._current_process.kill()
            except Exception:
                pass
        self._is_running = False

    # ================= Web API 接口 (支撑独立前端页面) =================

    def get_api(self) -> List[Dict[str, Any]]:
        """
        注册插件 HTTP API（供看板与配置页调用）。

        Register the plugin HTTP API consumed by the dashboard and config page.
        Paths are relative; the host mounts them under /plugin/Rsync115Sync/.
        """
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
            # 注意：没有 /strm_suspects 端点。strm 疑似清单由 /status 的
            # strm_suspects 字段一并返回，看板只依赖 /status 一处取数；
            # 早先注册过一个返回同样数据的 GET /strm_suspects，全仓库零调用，
            # 已移除避免两条取数路径返回同一份状态而产生分歧。
            {"path": "/strm_scan", "endpoint": self._api_strm_scan, "methods": ["POST"], "auth": "bear"},
            {"path": "/strm_prune", "endpoint": self._api_strm_prune, "methods": ["POST"], "auth": "bear"},
            {"path": "/strm_clear", "endpoint": self._api_strm_clear, "methods": ["POST"], "auth": "bear"},
            {"path": "/strm_retry", "endpoint": self._api_strm_retry, "methods": ["POST"], "auth": "bear"},
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
                "missed_scan_enabled": self._missed_scan_enabled,
                "strm_check_enabled": self._strm_check_enabled,
                "strm_grace_hours": self._strm_grace_hours,
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
                "force_cooldown_days": self._force_cooldown_days,
            }
        }

    def _api_save_config(self, config: Dict[str, Any]):
        if not config:
            return {"success": False, "message": "配置数据为空"}
        self._enabled = config.get("enabled", False)
        self._listen_transfer = config.get("listen_transfer", True)
        self._missed_scan_enabled = bool(
            config.get("missed_scan_enabled", self._MISSED_SCAN_ENABLED_DEFAULT)
        )
        self._notify = config.get("notify", True)
        self._delay_hours = float(config.get("delay_hours", 2.0))
        self._cron = config.get("cron", "0 */2 * * *")
        self._sync_pairs = config.get("sync_pairs") or []
        self._media_extensions = config.get("media_extensions") or self.DEFAULT_MEDIA_EXTENSIONS
        self._exclude_patterns = config.get("exclude_patterns") or self.DEFAULT_EXCLUDE_PATTERNS
        self._rsync_timeout = int(config.get("rsync_timeout") or self.DEFAULT_RSYNC_TIMEOUT)
        self._task_timeout = int(config.get("task_timeout") or self.DEFAULT_TASK_TIMEOUT)
        # 上传限流配置：允许用户按自己的风控容忍度调整
        self._rate_limit_enabled = bool(config.get("rate_limit_enabled", True))
        self._upload_batch_size = max(0, int(config.get("upload_batch_size") or 200))
        self._upload_max_per_window = max(0, int(config.get("upload_max_per_window") or 500))
        self._upload_window_secs = max(1, int(config.get("upload_window_secs") or 1800))
        self._backoff_secs = max(1, int(config.get("backoff_secs") or 3600))
        if config.get("rate_limit_keywords"):
            self._rate_limit_keywords = config.get("rate_limit_keywords")
        self._force_cooldown_days = max(0, int(config.get("force_cooldown_days") or 7))
        # strm 交叉验证配置（与 init_plugin 保持一致）
        self._strm_check_enabled = bool(config.get("strm_check_enabled", True))
        self._strm_grace_hours = max(0.5, float(config.get("strm_grace_hours") or 6.0))
        self.update_config(config)
        refreshed = self._refresh_scheduled_job()
        return {
            "success": True,
            "message": "配置保存成功" + ("" if refreshed else "（定时任务重建失败，请手动重载插件）"),
        }

    def _refresh_scheduled_job(self) -> bool:
        """
        保存配置后重建本插件的定时任务。

        Rebuild this plugin's scheduler jobs after the config is saved.

        ⚠️ **为什么必须显式做这件事**：宿主有两条保存路径，只有一条会重建调度 ——

          PUT  /plugin/{id}                      → PluginConfigCommand.update()
                                                   → save → initialize
                                                   → refresh_registrations()  ← 重建在这里
          POST /plugin/Rsync115Sync/config       → 本插件的 _api_save_config
                                                   → update_config()          ← 只写库

        配置页用的是**本插件自己的端点**，因此此前改了 cron 只是写进数据库，
        APScheduler 里跑的仍是旧表达式 —— 表现为「cron 改成每 5 分钟，却再也
        看不到任何执行日志」。改「启用/监听入库」这类开关同理不会刷新事件订阅。

        用宿主公开的 SDK 门面（app.sdk.scheduler）而不是内部模块，符合插件边界要求。
        On failure we only warn: the config itself is already saved, so a scheduler
        refresh problem must not make the user think the save failed.
        """
        if _update_plugin_job is None:
            logger.warning("[Rsync115Sync] 宿主未提供 app.sdk.scheduler.update_plugin_job，"
                           "无法主动重建定时任务（配置已保存，如需立即生效请手动重载插件）")
            return False
        try:
            # 插件 ID 用类名：宿主注册表以类名为键，且分身场景下运行类名即实例 ID
            _update_plugin_job(self.__class__.__name__)
            logger.info(f"[Rsync115Sync] 🔁 已按新配置重建定时任务（cron={self._cron}）")
            return True
        except Exception as err:
            logger.warning(f"[Rsync115Sync] 定时任务重建失败（配置已保存，可手动重载插件）: {err}")
            return False

    def _count_queue(self, now_ts: float, threshold: float) -> Tuple[int, int, int]:
        """
        统计冷却队列：返回 (就绪数, 冷却中数, 已失效数)。

        Count the cool-down queue as (ready, cooling, stale).

        为什么需要第三个数字：入库文件在冷却途中被删除后，队列条目要等冷却到期、
        下一轮同步才会被清理。若只按时间戳统计，这些「文件已不存在」的条目会被
        算进冷却中甚至就绪数，看板就会出现「冷却要 2 小时、却有一批 1 小时前的
        条目迟迟不就绪」这类误导信息。
        宿主没有「媒体库文件被删除」事件（只有下载器/订阅/站点的删除事件），
        因此无法在删除时即时移除，只能在**展示时**用存在性过滤，不改动持久化队列
        （避免为了显示而增加热路径开销）。真正清理由同步轮次负责。
        Stale entries are those whose file is already gone. The host emits no
        "library file deleted" event, so removal cannot be event-driven; we filter
        them at display time only and let the sync run do the actual pruning.
        """
        ready_count = 0
        cooling_count = 0
        stale_count = 0
        for key, ts in self._pending_queue.items():
            if not self._queue_key_exists(key):
                stale_count += 1
                continue
            if now_ts - ts >= threshold:
                ready_count += 1
            else:
                cooling_count += 1
        return ready_count, cooling_count, stale_count

    def _queue_key_exists(self, key: str) -> bool:
        """
        判断队列条目对应的源端文件是否仍然存在。

        Whether the source file behind a queue key still exists.

        key 形如 "任务名:相对路径"，需用映射的 src 还原绝对路径。任务名与 src
        都可能被用户改名，因此无法纯靠解析 key 得出路径；这里按前缀匹配所有映射，
        逐个还原。解析不出时不视为失效（宁可当作存在，避免误报）。
        """
        direct = os.path.isabs(key) and key != ""
        if direct:
            return os.path.exists(key)
        for pair in self._sync_pairs:
            pair_name = _pair_name(pair)
            src_root = (pair.get("src") or "").strip().rstrip("/")
            if not src_root or not pair_name:
                continue
            if key.startswith(f"{pair_name}:"):
                rel_p = key.split(f"{pair_name}:", 1)[1]
                return os.path.exists(os.path.join(src_root, rel_p))
        return True  # 无法归属任何映射，不判定为失效

    def _api_get_status(self):
        now_ts = time.time()
        threshold = self._delay_hours * 3600
        ready_count, cooling_count, stale_count = self._count_queue(now_ts, threshold)
        return {
            "success": True,
            "data": {
                "is_running": self._is_running,
                "ready_count": ready_count,
                "cooling_count": cooling_count,
                # 源端文件已不存在、等待同步轮清理的条目数（不计入上面两个数字）
                "stale_count": stale_count,
                "delay_hours": self._delay_hours,
                "last_status": self._last_status,
                "sync_pairs_count": len(self._sync_pairs),
                # 补传进度与限流状态，供看板展示
                "backfill_remaining": len(self._backfill_queue),
                "backfill_total": self._backfill_total,
                # 错过入库事件的待补扫清单：数字大于 0 说明有事件在插件不可用期间丢失，
                # 已由源端扫描补回、将在下轮同步（不参与冷却）
                "missed_count": len(self._missed_queue),
                "missed_last_scan": self._missed_last_scan,
                "missed_scan_enabled": self._missed_scan_enabled,
                # strm 交叉验证状态（看板展示与重传操作的数据源）
                "strm_suspects": self._strm_suspects,
                "strm_watching": len(self._strm_watch),
                "strm_grace_hours": self._strm_grace_hours,
                "strm_check_enabled": self._strm_check_enabled,
                "rate_limit_enabled": self._rate_limit_enabled,
                "upload_window_count": self._upload_window_count,
                "upload_max_per_window": self._upload_max_per_window,
                "upload_blocked_until": self._upload_blocked_until,
                "last_force_ts": self._last_force_ts,
                "force_cooldown_days": self._force_cooldown_days,
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
        """
        从插件数据目录恢复限流窗口与退避状态。

        Restore window counter and back-off deadline from the plugin data
        directory. Must run before any upload decision is made.
        """
        self._upload_window_start = float(self.get_data("upload_window_start") or 0.0)
        self._upload_window_count = int(self.get_data("upload_window_count") or 0)
        self._upload_blocked_until = float(self.get_data("upload_blocked_until") or 0.0)

    def _persist_rate_limit_state(self):
        """
        持久化限流状态。

        Persist throttling state. Written before the first count is charged so
        that a restart cannot open a race window that bypasses the limiter.
        """
        self.save_data("upload_window_start", self._upload_window_start)
        self.save_data("upload_window_count", self._upload_window_count)
        self.save_data("upload_blocked_until", self._upload_blocked_until)

    def _rate_limit_allows(self) -> Tuple[bool, str]:
        """
        上传闸门：判断当前是否可以发起本批上传。

        Upload gate: decide whether this batch may start uploading now.

        返回 (是否放行, 原因说明)，原因用于回显给用户。
        Returns (allowed, human_readable_reason); the reason is surfaced to the user.

        三层判定 / three sequential checks:
          1) 退避期未过 → 拒绝 / still inside back-off → deny
          2) 窗口已过期 → 计数归零并前移窗口 / window expired → reset and roll forward
          3) 窗口内计数达上限 → 拒绝 / quota exhausted → deny
        """
        if not self._rate_limit_enabled:
            return True, ""

        now_ts = time.time()

        # 1) 风控退避期 / back-off window
        if now_ts < self._upload_blocked_until:
            remain = int(self._upload_blocked_until - now_ts)
            return False, f"风控退避中，还需等待 {max(1, remain // 60)} 分钟"

        # 2) 窗口滚动 / roll the counting window when it has elapsed
        if self._upload_window_start <= 0 or (now_ts - self._upload_window_start) >= self._upload_window_secs:
            self._upload_window_start = now_ts
            self._upload_window_count = 0

        # 3) 窗口配额 / per-window quota
        if self._upload_window_count >= self._upload_max_per_window:
            elapsed = int(now_ts - self._upload_window_start)
            remain = max(1, self._upload_window_secs - elapsed)
            return False, (f"本窗口配额已用尽（{self._upload_window_count}/{self._upload_max_per_window}），"
                           f"约 {max(1, remain // 60)} 分钟后继续")

        return True, ""

    def _consume_upload_quota(self, batch_info: str = "") -> int:
        """
        扣减配额：把本批实际上传的文件数并入窗口计数并落盘。

        Charge the quota: add this batch's file count to the window counter and
        persist it immediately.

        调用时机是在 rsync 启动**之前**预留：若在传输过程中插件被重载，
        已提交的文件数不会因内存状态丢失而让下一批绕过限流。
        Called BEFORE rsync starts (pre-charged). If the plugin is reloaded while
        a transfer is in flight, the already-committed count is not lost with the
        in-memory state, so the next batch cannot bypass the limiter.

        返回扣减后的窗口计数 / returns the updated window count.
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
        """
        从 rsync 错误输出中识别 115 / CD2 的风控特征串。

        Detect 115 / CD2 rate-limiting signatures in rsync stderr. Matching is
        case-insensitive and substring-based, so `429`, `too many requests`,
        `rate limit` and similar messages all trigger a back-off.
        """
        if not stderr:
            return False
        lowered = stderr.lower()
        for kw in self._rate_limit_keywords.splitlines():
            kw = kw.strip().lower()
            if kw and kw in lowered:
                return True
        return False

    def _trigger_backoff(self, reason: str):
        """
        命中风控：进入退避期，后续批次在退避结束前一律不放行。

        Enter back-off after a rate-limit hit. No batch is permitted until the
        back-off deadline passes, giving 115's side time to settle.
        """
        self._upload_blocked_until = time.time() + self._backoff_secs
        # 退避期间窗口计数一并归零，避免退避结束后立刻撞上配额上限
        self._upload_window_start = 0.0
        self._upload_window_count = 0
        self._persist_rate_limit_state()
        logger.warning(f"[Rsync115Sync] 🚫 触发风控退避：{reason}，"
                       f"暂停上传 {self._backoff_secs // 60} 分钟")

    def _migrate_legacy_defaults(self, config: Dict[str, Any]):
        """
        把老用户的「旧默认值」平滑迁移到新默认值。

        Migrate legacy defaults to the new ones for existing users.

        只在当前值**恰好等于旧默认串**时才替换——用户只要手工改过任何一个字符，
        就完全不动，绝不覆盖自定义配置。
        A value is replaced ONLY when it exactly equals the old default string.
        If the user changed even one character, nothing is touched — a customised
        setting is never overwritten.

        迁移后必须 update_config 固化，否则存在竞态：用户先打开配置页拿到旧值，
        后端重载完成迁移，用户再保存时又把旧值覆盖回去。
        The result must be persisted via update_config, otherwise a race exists:
        the user opens the form and holds the old values, a reload completes the
        migration, then the user saves and writes the old values back.

        幂等 / idempotent: 迁移后取值已等于新默认，不再匹配旧串，重复调用无副作用。
        """
        try:
            changed = {}
            # 扩展名：旧默认（无字幕）→ 新默认（含字幕）
            cur_ext = (config.get("media_extensions") or "").strip()
            if cur_ext and cur_ext == self._LEGACY_DEFAULTS["media_extensions"]:
                self._media_extensions = self.DEFAULT_MEDIA_EXTENSIONS
                changed["media_extensions"] = self.DEFAULT_MEDIA_EXTENSIONS
            # 排除规则：旧默认（无 ..*）→ 新默认
            cur_ex = (config.get("exclude_patterns") or "").strip()
            if cur_ex and cur_ex == self._LEGACY_DEFAULTS["exclude_patterns"]:
                self._exclude_patterns = self.DEFAULT_EXCLUDE_PATTERNS
                changed["exclude_patterns"] = self.DEFAULT_EXCLUDE_PATTERNS
            # I/O 超时：60 → 600（前端为 v-model.number，兼容 int/str 两种形态）
            cur_to = str(config.get("rsync_timeout") or "").strip()
            if cur_to and cur_to == str(self._LEGACY_DEFAULTS["rsync_timeout"]):
                self._rsync_timeout = self.DEFAULT_RSYNC_TIMEOUT
                changed["rsync_timeout"] = self.DEFAULT_RSYNC_TIMEOUT

            if changed:
                merged = dict(config)
                merged.update(changed)
                self.update_config(merged)
                logger.info(f"[Rsync115Sync] 🔧 已迁移旧默认配置: {', '.join(changed)}")
        except Exception as e:
            # 迁移失败不应影响插件启动，保留原配置即可
            logger.warning(f"[Rsync115Sync] 旧配置迁移失败（保持原值）: {e}")

    # ================= 存量媒体补传（零 API 本地扫描） =================

    @staticmethod
    def _list_dir_cached(cache: Dict[str, Optional[List[str]]], abs_dir: str) -> Optional[List[str]]:
        """
        带缓存的目录列举：同一次补传扫描内，每个目录只真正 listdir 一次。

        Cached directory listing: each directory is listed at most once per scan.

        为什么需要：`_find_sidecar_files` 会对**每个媒体文件**调用一次，
        若同一季目录下有 24 集，就会对同一个目录重复 listdir 24 次。
        一个 50 季的库会产生上万次重复系统调用（纯本地 IO，不碰 115，
        但足以让扫描明显变慢）。缓存后每个目录只列一次。
        Without this, a season directory with 24 episodes gets listed 24 times;
        a 50-season library wastes thousands of redundant syscalls.
        """
        if abs_dir in cache:
            return cache[abs_dir]
        try:
            entries = os.listdir(abs_dir)
        except OSError:
            entries = None          # 目录不存在或无权限：缓存失败结果，避免反复重试
        cache[abs_dir] = entries
        return entries

    def _find_sidecar_files(self, src_dir: str, rel_media: str,
                            cache: Optional[Dict[str, Optional[List[str]]]] = None) -> List[str]:
        """
        查找与某个媒体文件同主名的伴生字幕文件（本地扫描，不访问 115）。

        Find sidecar subtitle files sharing the stem of a media file.
        Pure local scan — never touches the 115 mount.

        例 / example: `剧名/剧名 S01E01.mkv` → `剧名/剧名 S01E01.zh.srt`、`…S01E01.ass`

        真实场景中入库的往往是整集（媒体 + 外挂字幕），若只同步媒体，
        字幕会被遗漏且永不触发同步。
        A real ingest unit is a whole episode (video + external subtitles). If
        only the media file is queued, the subtitles are missed and never get a
        chance to sync.

        :param cache: 可选的目录列举缓存，批量扫描时由调用方传入以消除重复 listdir
        """
        src_f = os.path.join(src_dir, rel_media)
        parent_rel = os.path.dirname(rel_media)
        parent_abs = os.path.dirname(src_f)
        stem = os.path.splitext(os.path.basename(rel_media))[0]

        names = self._list_dir_cached(cache, parent_abs) if cache is not None \
            else self._list_dir_cached({}, parent_abs)
        if names is None:
            return []

        sidecars: List[str] = []
        prefix = f"{stem}."
        base_name = os.path.basename(rel_media)
        for name in names:
            if name == base_name:
                continue
            # 仅认“主名 + 附加标记 + 字幕扩展名”，避免误纳同剧其它剧集
            if not name.startswith(prefix):
                continue
            if os.path.splitext(name)[-1].lstrip(".").lower() not in self._SIDECAR_EXTS:
                continue
            # 保留 isfile 校验：listdir 返回的可能是子目录，若其名字恰好以字幕
            # 扩展名结尾（如名为 "S01E01.srt" 的目录）会被误当字幕加入候选，
            # rsync 随后会因「文件不存在」报错。
            # 该 stat 只在「名字已匹配主名 + 扩展名」时才执行，是极小的子集，
            # 与缓存带来的收益相比可以忽略。
            if not os.path.isfile(os.path.join(parent_abs, name)):
                continue
            sidecars.append(f"{parent_rel}/{name}" if parent_rel else name)
        return sidecars

    def _build_backfill_candidates(self) -> List[str]:
        """
        扫描源端，构建“存量补传”候选清单。

        Scan the source side and build the back-fill candidate list.

        全程只读源目录，不访问 115 挂载点，因此零 API 开销。
        Read-only over local directories; the 115 mount is never touched, so this
        costs ZERO API calls regardless of library size.

        候选口径：源端存在、且不在冷却队列、也不在异常清单中的文件
        （即本插件从未处理过的存量文件）。
        Criteria: exists locally AND absent from the cool-down queue, the anomaly
        lists and the ignore list — i.e. files this plugin has never handled.

        注意：无法在不访问 115 的前提下判断目标端是否已存在，
        therefore the list may include files that were synced before but never
        queued. Those are skipped by rsync's --size-only at transfer time, at the
        cost of one stat request per candidate.
        注意：候选规模即用户点击补传的最小 API 代价，故 UI 先预览再确认。
        """
        candidates: List[str] = []
        seen = set()
        # 目录列举缓存：整个扫描过程共用，避免同一季目录被反复 listdir
        dir_cache: Dict[str, Optional[List[str]]] = {}
        valid_exts = [x.strip().lower() for x in self._media_extensions.split(",") if x.strip()]
        # 只按扩展名过滤候选，范围由每个映射对的 all_ext 决定
        for pair in self._sync_pairs:
            src_dir = (pair.get("src") or "").strip().rstrip("/")
            pair_name = _pair_name(pair)
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
                    # Attach same-stem sidecar subtitles to the media file
                    for sc in self._find_sidecar_files(src_dir, root_rel, dir_cache):
                        sc_key = f"{pair_name}:{sc}"
                        if sc_key not in seen and not self._is_ignored(sc_key):
                            seen.add(sc_key)
                            candidates.append(sc_key)
        return candidates

    def _api_backfill_scan(self):
        """
        预览补传候选数量与样例，供用户在触发前评估规模。

        Preview candidate count and a sample so the user can judge the cost
        before committing. Because every candidate costs at least one target-side
        stat, this preview is what keeps a single click from firing thousands of
        requests unnoticed.

        并发保护：扫描会遍历全部映射的源目录，大库下耗时可达数十秒。
        若同一时刻已有扫描在跑，直接拒绝而不是排队 —— 重复扫描结果完全一致，
        让它们叠加只会白白占用磁盘 IO。
        Concurrency guard: a large library scan can take tens of seconds.
        A second concurrent scan is rejected outright (results would be identical).
        """
        if self._is_running:
            return {"success": False,
                    "message": "已有同步任务正在运行，扫描结果可能不完整，请稍后再试"}
        if not self._backfill_scan_lock.acquire(blocking=False):
            return {"success": False,
                    "message": "已有一次补传扫描正在进行，请等待其完成（结果相同，无需重复触发）"}
        try:
            candidates = self._build_backfill_candidates()
        finally:
            # 必须在 finally 中释放：扫描抛异常若不释放，之后所有扫描与补传
            # 都会被这个锁永久挡住（重启插件才能恢复）
            self._backfill_scan_lock.release()
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

        Start the back-fill run.

        只扫描源端（零 API），把候选写入独立的补传队列，
        随后由核心同步逻辑按批次上限与窗口配额逐步消费。
        Scan the source only (zero API), store candidates in a dedicated queue,
        then let the core sync loop drain it under the batch cap and window quota.

        队列独立于 pending_queue：补传项不参与入库冷却计时，避免污染
        “冷却中 / 已就绪”统计。
        The queue is separate from pending_queue: back-fill entries do NOT take
        part in cool-down timing, so the cooling/ready counters stay accurate.
        """
        if self._is_running:
            return {"success": False, "message": "已有任务正在运行，请稍后再试"}
        # 扫描互斥：本接口内部同样会全库扫描。若此刻已有扫描在跑
        # （例如用户先点了预览还没结束就点了确认），两个扫描会同时遍历磁盘；
        # 更糟的是确认框展示的候选数与最终写入队列的候选数将来自两次不同扫描，
        # 与用户确认的内容不一致。
        # Also guards the case where a preview scan is still running while the user
        # confirms: the confirmed count would otherwise come from a different scan.
        if not self._backfill_scan_lock.acquire(blocking=False):
            return {"success": False,
                    "message": "有一次扫描正在进行（可能是刚才的预览），请等它结束后重试"}
        try:
            candidates = self._build_backfill_candidates()
        finally:
            self._backfill_scan_lock.release()
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
        """
        清空补传队列与进度。

        Clear the back-fill queue and its progress counters. Already-synced files
        are unaffected; only the pending work list is discarded.
        """
        self._backfill_queue = []
        self._backfill_total = 0
        self.save_data("backfill_queue", [])
        self.save_data("backfill_total", 0)
        return {"success": True, "message": "已清空存量补传队列"}

    # ================= 核心同步执行逻辑 (严格对齐 sync_115.sh) =================

    def _force_cooldown_allows(self) -> Tuple[bool, str]:
        """
        force 全量校验的冷却判定。

        该模式会遍历 115 挂载点全目录，是本插件最重的 API 操作，
        因此按天限频。只有成功执行才推进时间戳——失败不占用冷却额度，
        便于排障（重复尝试仍受窗口配额约束，不会无限冲击 115）。
        """
        days = max(0, int(self._force_cooldown_days))
        if days <= 0 or self._last_force_ts <= 0:
            return True, ""
        elapsed = time.time() - self._last_force_ts
        remain = days * 86400 - elapsed
        if remain <= 0:
            return True, ""
        hours = int(remain // 3600)
        next_ts = datetime.fromtimestamp(self._last_force_ts + days * 86400)
        return False, (f"全量校验冷却中（每 {days} 天一次），"
                       f"约 {hours} 小时后可用，最早 {next_ts.strftime('%Y-%m-%d %H:%M')}")

    def _mark_force_done(self):
        """
        记录一次成功的全量校验，开始计算冷却。

        Record a successful full verification and start the cool-down clock.
        Called only on success, so a failed run does not consume the allowance.
        """
        self._last_force_ts = time.time()
        self.save_data("last_force_ts", self._last_force_ts)

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
        """
        定时巡检入口：优先续跑未完成的补传队列，否则执行常规就绪同步。

        Cron entry point. Only one mode runs per tick because both share the same
        execution lock and window quota — launching both would make them contend
        for the lock and the second one would silently do nothing.
        """
        logger.info("[Rsync115Sync] 触发定时检查同步就绪媒体...")
        # strm 交叉验证巡检：纯本地文件系统操作（零 115 API），
        # 在任何同步启动前顺带执行；内部自带节流（30 分钟）与异常兜底
        try:
            self._strm_check()
        except Exception as e:
            logger.warning(f"[Rsync115Sync] strm 交叉验证巡检异常（已忽略，不影响本轮同步）: {e}")
        # 补传队列存在时优先续跑：队列有限且自终止，排空后自动恢复常规巡检。
        # 两种模式共用同一把执行锁与同一份窗口配额，故同一轮只启动其中一个。
        if self._resume_backfill_if_pending():
            return
        self._start_sync_thread(mode="ready")

    def _start_sync_thread(self, mode: str = "ready", custom_files: Optional[List[str]] = None, channel_event: Optional[Event] = None):
        """
        在后台线程启动一次同步，避免阻塞宿主事件循环。

        Run one sync in a background daemon thread so the host event loop is not
        blocked. Execution is serialised by self._lock inside _execute_sync.
        """
        threading.Thread(target=self._execute_sync, args=(mode, custom_files, channel_event), daemon=True).start()

    def _execute_sync(self, mode: str = "ready", custom_files: Optional[List[str]] = None, channel_event: Optional[Event] = None):
        """
        同步主流程：本插件唯一真正与 115 交互的地方。

        Core sync routine — the single place that actually talks to the 115 mount.

        三种模式 / three modes:
          ready    — 处理冷却到期的入库文件，走 --files-from 定向传输
                     sync files whose cool-down has elapsed (targeted via --files-from)
          retry    — 处理异常清单或用户指定文件，同样走 --files-from
                     retry the anomaly list or user-specified files, also --files-from
          backfill — 处理存量补传队列，同样走 --files-from
                     drain the back-fill queue, also --files-from
          force    — 全量校验，遍历 115 全目录（最重，受 7 天冷却限制）
                     full verification, walks the whole 115 tree (heaviest; gated
                     by a 7-day cool-down)

        防风控设计（贯穿全流程）/ anti-abuse design applied throughout:
          1) 入口闸门：退避期或配额用尽时整轮直接返回，一次 API 都不发；
             entry gate — return early on back-off or exhausted quota, zero API calls
          2) 批次上限：单次 rsync 提交量有界，超出部分留待下轮；
             per-run batch cap, remainder deferred to the next run
          3) 配额预扣：启动 rsync 前先扣减并落盘，防止重载绕过；
             quota pre-charged and persisted before rsync starts
          4) stderr 风控检测：命中关键词立即退避并终止本轮；
             stderr rate-limit detection aborts the run immediately
          5) 配额中途耗尽：停止处理后续映射对。
             stop before the next mapping pair once the quota is gone
        """
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
            # Upload gate. On back-off or exhausted quota, skip the entire run
            # without touching the 115 mount at all — not even one stat.
            # 返回而非 break：本轮不产生任何 API 调用，等下一次 cron 再来。
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

            # 源端补齐扫描：只走本地目录遍历（不触碰 115 挂载点，零 API 开销），
            # 用于兜住「插件重载期间错过的入库事件」。仅 ready 模式需要——
            # retry/backfill 处理的是更早的存量，与新鲜入库无关。
            # Source-root reconciliation for missed ingest events. Local-only walk,
            # no 115 mount access. Only needed in ready mode.
            if mode == "ready" and self._missed_scan_enabled:
                try:
                    self._scan_missed_ingest()
                except Exception as scan_err:
                    # 补齐失败不能影响正常同步
                    logger.warning(f"[Rsync115Sync] 源端补齐扫描异常（已忽略，不影响本轮同步）: {scan_err}")

            for idx, pair in enumerate(self._sync_pairs):
                src = (pair.get("src") or "").strip().rstrip("/")
                dest = (pair.get("dest") or "").strip().rstrip("/")
                pair_name = _pair_name(pair)
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

                # 全量模式（force）没有 --files-from 清单，必须靠 include/exclude
                # 过滤才能限定传输范围。rsync 规则按顺序首条匹配生效，因此
                # --include 必须全部排在 --exclude 之前，且 --exclude="*" 放最后兜底。
                # The force mode has no --files-from list, so include/exclude rules
                # are the only thing bounding the transfer. rsync applies the FIRST
                # matching rule, so every --include must precede --exclude and the
                # catch-all --exclude="*" must come last. Ordering is load-bearing:
                # swapping them would silently disable the whole filter.
                if mode not in ("ready", "retry", "backfill"):
                    cmd.append("--include=*/")
                    if not all_ext:
                        for _ext in [x.strip().lower() for x in self._media_extensions.split(",") if x.strip()]:
                            cmd.append(f"--include=*.{_ext}")

                # 排除目录参数
                for ex in self._exclude_patterns.splitlines():
                    ex_clean = ex.strip()
                    if ex_clean:
                        cmd.append(f"--exclude={ex_clean}")

                # 全量模式兜底：过滤掉未显式 include 的一切，避免无差别整树传输
                if mode not in ("ready", "retry", "backfill"):
                    cmd.append("--exclude=*")

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

                    # 补齐清单：这些文件是在插件不可用期间错过的入库事件
                    # （事件错过不重放，已通过源端扫描补回）。
                    # 它们已经等得够久了，**不再走冷却判定**，直接纳入本轮同步。
                    # Missed-ingest entries: recovered by scanning the source
                    # roots. They have already waited long enough, so they skip
                    # the cool-down check and sync in this run.
                    missed_here = [k for k in list(self._missed_queue.keys())
                                   if k.startswith(f"{pair_name}:")]
                    missed_taken = 0
                    for key in missed_here:
                        rel_p = key.split(f"{pair_name}:", 1)[1]
                        if os.path.exists(os.path.join(src, rel_p)):
                            if rel_p not in pair_files:
                                pair_files.append(rel_p)
                            # 仅在**确实纳入本轮**时才移出清单：
                            # 若本轮批次上限/配额已满、该文件不会真正被处理，
                            # 提前移除会让它彻底丢失（既不在冷却队列，也不在补齐清单）
                            if rel_p in pair_files:
                                self._missed_queue.pop(key, None)
                                missed_taken += 1
                        else:
                            # 文件已不在源端（被删除/移动），清掉避免长期堆积
                            self._missed_queue.pop(key, None)
                    if missed_taken:
                        # 立即落盘，避免记录只在内存里、重载即丢
                        self.save_data("missed_queue", self._missed_queue)
                        logger.info(f"[Rsync115Sync] [{pair_name}] 🕳️ 本轮纳入 {missed_taken} 个"
                                    f"错过的入库文件（含字幕等，不参与冷却）")

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
                    # Per-run batch cap: bound how much a single rsync handles, to
                    # avoid an over-long command line and a burst of target-side
                    # stat requests. Trimmed files stay in the source queue/list and
                    # are picked up by the next cron tick or the next manual trigger.
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
                # Pre-charge the quota and persist it BEFORE launching rsync. If the
                # plugin is reloaded mid-transfer, the committed count survives, so
                # a restart cannot silently hand out a fresh allowance.
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
                # Rate-limit detection: a keyword hit in stderr triggers back-off
                # and aborts the whole run immediately, instead of hammering 115
                # with the remaining pairs.
                if self._rate_limit_enabled and self._detect_rate_limit_hit(stderr):
                    self._trigger_backoff(f"[{pair_name}] rsync 输出命中限流特征")
                    self._post_reply(channel_event, "🚫 检测到 115/CD2 限流特征，已暂停上传并进入退避期。")
                    break

                # ---- 配额中途耗尽：已完成本组，但不再继续下一组映射 ----
                # Quota exhausted mid-run: this pair is done, stop before touching
                # the next pair. Fixes the previous behaviour where a single run
                # could scan every mapping pair back-to-back with no ceiling.
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
                    succeeded_keys = []
                    for rel_p in pair_files:
                        k = f"{pair_name}:{rel_p}"
                        if k not in m_list and k not in c_list:
                            self._pending_queue.pop(k, None)
                            succeeded_keys.append(k)
                            logger.info(f"[Rsync115Sync] [{pair_name}] 🧊 已移出冷却队列: {rel_p}")
                    # strm 交叉验证：登记待观察（有 strm_dir 的映射才实际生效）
                    if succeeded_keys:
                        armed = self._strm_arm_watch(succeeded_keys)
                        if armed:
                            logger.info(f"[Rsync115Sync] [{pair_name}] 📺 已登记 {armed} 个文件进入 "
                                        f"strm 观察期（{self._strm_grace_hours}h 内未生成 strm 将标记疑似异常）")

                # 重试模式成功：同样登记 strm 观察（重传后自动复核 strm 是否生成，
                # 生成即自动解除疑点，无需用户再确认）
                if exit_code == 0 and mode == "retry":
                    succeeded_retry = [f"{pair_name}:{rel_p}" for rel_p in pair_files
                                       if f"{pair_name}:{rel_p}" not in m_list
                                       and f"{pair_name}:{rel_p}" not in c_list]
                    if succeeded_retry:
                        self._strm_arm_watch(succeeded_retry)

                # 补传模式：无论本批成功与否都从补传队列移除
                # （失败的会进入 missing/corrupt 清单，由 /rsync_retry 接手，
                #   若留在补传队列会与异常清单重复处理）
                # Back-fill: drain entries once attempted, regardless of outcome.
                if mode == "backfill":
                    for rel_p in pair_files:
                        k = f"{pair_name}:{rel_p}"
                        if k in self._backfill_done_keys:
                            continue
                        self._backfill_done_keys.add(k)

            self.save_data("pending_queue", self._pending_queue)

            # 推进补传队列：移除本轮已处理的文件并落盘，保证跨重载可续跑
            # Advance the back-fill queue: drop processed keys and persist, so the
            # run resumes exactly where it stopped after a reload or host restart.
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

            # 全量校验冷却只在成功时开始计时：失败不占用额度，便于立即排障重试
            if mode == "force" and not has_error:
                self._mark_force_done()

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

    # ================= strm 交叉验证 =================

    # strm 交叉验证的**纯逻辑**（期望路径推导、三态流转判定）已迁至 strm.py，
    # 便于单测穷举边界（恰好到期 / 源端消失 / 映射被改）。本类保留的职责是
    # I/O 与持久化：探测文件系统、读写 _strm_watch / _strm_suspects。

    @staticmethod
    def _strm_video_exts() -> set:
        """
        strm 检查专用的扩展名集合（**仅视频**）。

        Video-only extension set for strm checks.

        为什么不能复用同步用的 media_extensions：那个白名单**包含字幕**
        （srt/ssa/ass），因为同步的入库单元是「整集 = 视频 + 外挂字幕」。
        但 strm 插件只为**视频**生成 .strm 指针文件，字幕永远不会有 ——
        拿同步白名单去查 strm，每个 `xxx.zh.srt` 都会变成「疑似上传异常」。
        这是主动扫描上线时的真实缺陷（用户发现 jpg/nfo 也会被判）。

        也不看映射的 all_ext：勾了「同步所有类型」意味着 jpg/nfo 也会被同步，
        但它们同样不会生成 strm，参与检查只会制造误报。
        """
        return {e.strip().lower() for e in STRM_VIDEO_EXTENSIONS.split(",") if e.strip()}

    @staticmethod
    def _migrate_strm_suspects(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        把疑似清单迁移到带来源的新格式。

        Migrate the suspect list to the origin-carrying shape.

        v0.1.7 及更早存的是 `{key: 时间戳}`；v0.1.8 起改为
        `{key: {"ts": 时间戳, "origin": "watch"|"scan"}}`。旧条目一律按
        `watch` 处理 —— 那个版本只存在观察这一条来源，语义上就是正确的归属。
        迁移必须容忍三种脏数据：非 dict、值不是数字、值已经是新格式。
        Legacy entries are all attributed to `watch` (the only origin that existed
        then). Tolerates non-dict input and already-migrated entries.
        """
        if not isinstance(raw, dict):
            return {}
        migrated: Dict[str, Dict[str, Any]] = {}
        for key, value in raw.items():
            if isinstance(value, dict) and "ts" in value:
                migrated[str(key)] = {
                    "ts": float(value.get("ts") or 0.0),
                    "origin": str(value.get("origin") or _strm.ORIGIN_WATCH),
                }
                continue
            try:
                ts = float(value)
            except (TypeError, ValueError):
                ts = 0.0
            migrated[str(key)] = {"ts": ts, "origin": _strm.ORIGIN_WATCH}
        return migrated

    def _prune_invalid_strm_suspects(self) -> int:
        """
        清洗疑似清单里**无效**的条目，返回清理数量。

        Prune suspects that can no longer be valid; returns how many were removed.

        哪些属于无效（每条都对应一个真实产生过脏数据的缺陷）：
          1. **非视频文件** —— v0.1.7 的主动扫描把 jpg/nfo/海报也扫了进来，
             而 strm 插件只为视频生成指针文件，这些条目永远不会恢复正常，
             会永久留在清单里。用户实测反馈过。
          2. **已命中忽略规则的文件** —— 忽略即「不再报警」，不应占着清单，
             还会被「全部删旧重传」波及。
          3. **源端文件已不存在** —— 无从重传，留着重传只会失败。
          4. **所属映射已取消 strm_dir 或已删除** —— 验证前提消失，
             与 _strm_check 的 NO_STRM_DIR 出口同一判据。

        为什么在**载入时**清洗而不只在写入时过滤：写入时过滤只能拦住新数据，
        升级前已经落盘的脏条目会一直留着，用户看到一堆永远处理不掉的条目，
        只能靠手工改插件数据文件。载入时清洗让升级本身就把历史问题一起解决。
        Pruning at load time (not only at write time) is what lets an upgrade clean
        up entries written by earlier, buggy versions.
        """
        removed = 0
        video_exts = self._strm_video_exts()
        for key in list(self._strm_suspects.keys()):
            reason = None

            rel = key.split(":", 1)[1] if ":" in key else key
            ext = os.path.splitext(rel)[-1].lstrip(".").lower()
            if ext not in video_exts:
                reason = f"非视频文件（.{ext} 不会生成 strm）"
            elif self._is_ignored(key):
                reason = "已命中忽略规则"
            elif self._strm_expected_path(key) is None:
                reason = "所属映射未配置 strm 目录"
            else:
                src_root = _strm.source_root_of(key, self._sync_pairs)
                if src_root and not os.path.exists(os.path.join(src_root, rel)):
                    reason = "源端文件已不存在"

            if reason:
                self._strm_suspects.pop(key, None)
                removed += 1
                logger.info(f"[Rsync115Sync] 🧹 清理无效 strm 疑似条目（{reason}）: {key}")

        if removed:
            self.save_data("strm_suspects", self._strm_suspects)
            logger.warning(f"[Rsync115Sync] 🧹 已清理 {removed} 个无效 strm 疑似条目"
                           f"（非视频 / 已忽略 / 源端已删 / 映射已取消验证），剩余 "
                           f"{len(self._strm_suspects)} 个")
            # 清单可能因此清空，重置通知闩锁（与其它收尾路径一致）
            self._reset_strm_notified_if_clear()
        return removed

    def _strm_expected_path(self, key: str) -> Optional[str]:
        """由队列 key 推导「应当生成」的 .strm 绝对路径；无 strm_dir 的映射返回 None。"""
        return _strm.expected_path(key, self._sync_pairs)

    def _strm_arm_watch(self, keys: List[str]) -> int:
        """
        同步成功后把文件登记进「待观察」清单（宽限期从现在起算）。

        Arm a strm watch for successfully synced files. A key already in the suspect
        list is removed on success — the re-transfer cleared it.
        """
        armed = 0
        now_ts = time.time()
        for k in keys:
            if self._strm_expected_path(k) is None:
                continue  # 该映射未配 strm_dir，不参与交叉验证
            # 已加入忽略清单的文件不登记观察。
            #
            # 为什么要在**最上游**拦：「忽略」的语义是「这个文件不要再报警」，
            # 而 strm 疑似同样是一种报警。若只在展示层过滤，被忽略的文件仍会在
            # 观察期到期时写进疑似清单、还会触发通知 —— 用户会收到自己明确
            # 忽略过的文件的告警。在登记处拦掉，后续观察/疑似/通知全都不涉及它。
            # Skip ignored files at the earliest point: ignoring means "stop alerting
            # about this file", and a strm suspect is an alert. Filtering only at the
            # display layer would still write them into the suspect list and notify.
            if self._is_ignored(k):
                continue
            self._strm_watch[k] = now_ts
            # 重传成功即解除疑点
            if k in self._strm_suspects:
                self._strm_suspects.pop(k, None)
                self.save_data("strm_suspects", self._strm_suspects)
            armed += 1
        if armed:
            self.save_data("strm_watch", self._strm_watch)
            # 疑点被解除后，若清单已清空则重置通知标志，让下次新发现能再次提醒
            self._reset_strm_notified_if_clear()
        return armed

    def _strm_check(self) -> Dict[str, Any]:
        """
        strm 交叉验证巡检：走 I/O 与持久化，三态判定交给 strm.classify_watch。

        Strm cross-validation sweep. This method only probes the filesystem and
        persists results; the state machine itself lives in strm.py.

        出口：strm 已生成（正常解除）/ 到期未生成（转疑似）/ 未到期（继续观察）/
        映射取消 strm_dir 或源端消失（清理）。后两者不合并计数，见 strm.py 的
        状态定义说明。

        纯本地文件系统操作，零 115 API；由定时巡检调用，内部再按固定间隔节流。
        """
        now_ts = time.time()
        # 巡检节流：strm 生成是分钟级的事，没必要每次同步都查一遍
        if now_ts - self._strm_last_check < _STRM_CHECK_INTERVAL:
            return {"checked": 0, "ok": 0, "new_suspects": 0}
        self._strm_last_check = now_ts

        if not self._strm_check_enabled or not self._strm_watch:
            # 明确留痕：否则用户无法区分「strm 功能没工作」与「工作了但没有待观察项」，
            # 只能看到一个静默返回，排查时完全没有依据（用户实测反馈过这一点）。
            logger.debug(f"[Rsync115Sync] strm 巡检跳过："
                         f"{'功能已关闭' if not self._strm_check_enabled else f'观察清单为空（疑似 {len(self._strm_suspects)} 个）'}")
            return {"checked": 0, "ok": 0, "new_suspects": 0}

        grace_secs = _strm.grace_secs_of(self._strm_grace_hours)
        settled_ok: List[str] = []
        new_suspects: List[str] = []
        dropped: List[str] = []

        for key, synced_ts in list(self._strm_watch.items()):
            # 忽略清单是最高优先级：用户在观察期内加了忽略规则时，这里必须让位，
            # 否则条目仍会到期转疑似并触发通知 —— 用户会收到自己忽略过的文件的告警。
            # `_add_ignore_rule` 已经会主动清理两个清单，这里是兜底（例如规则由
            # 其它实例/更早版本写入，或清理逻辑未覆盖到的时序）。
            # Ignore rules win: a rule added during the grace window must not let the
            # entry turn into a suspect (and notify) anyway.
            if self._is_ignored(key):
                dropped.append(key)
                continue
            # 两个探测值先算好再交给纯函数判定：三态边界因而可以在单测里穷举，
            # 不需要真实文件系统。
            strm_exists = os.path.exists(self._strm_expected_path(key) or "")
            src_root = _strm.source_root_of(key, self._sync_pairs)
            src_exists = (not src_root) or os.path.exists(
                os.path.join(src_root, key.split(":", 1)[1]))
            state, record = _strm.classify_watch(
                key, synced_ts, now_ts, grace_secs, self._sync_pairs,
                strm_exists=strm_exists, src_exists=src_exists)
            if state == _strm.SUSPECT:
                new_suspects.append(record)
            elif state == _strm.WATCHING:
                continue
            elif state == _strm.SETTLED:
                settled_ok.append(key)
            else:
                # NO_STRM_DIR 与 SOURCE_GONE 都是清理出口，与「正常解除」分开计数
                dropped.append(key)

        for k in settled_ok + dropped:
            self._strm_watch.pop(k, None)
        for k in new_suspects:
            self._strm_watch.pop(k, None)
            self._strm_suspects[k] = {"ts": now_ts, "origin": _strm.ORIGIN_WATCH}

        if settled_ok or dropped or new_suspects:
            self.save_data("strm_watch", self._strm_watch)
            self.save_data("strm_suspects", self._strm_suspects)
            if new_suspects:
                logger.warning(f"[Rsync115Sync] 📺 strm 交叉验证发现 {len(new_suspects)} 个疑似上传异常"
                               f"（宽限期 {self._strm_grace_hours}h 内未见 strm 生成）: "
                               f"{_brief_paths(new_suspects)}")
                self._notify_strm_suspects(new_suspects)
            elif settled_ok:
                logger.debug(f"[Rsync115Sync] strm 交叉验证：{len(settled_ok)} 个文件 strm 已生成，正常")

        return {"checked": len(settled_ok) + len(new_suspects) + len(dropped),
                "ok": len(settled_ok), "new_suspects": len(new_suspects)}

    def _notify_strm_suspects(self, new_suspects: List[str]) -> None:
        """
        发现新的 strm 疑似异常时推送通知（仅新发现时发，不重复打扰）。

        Notify on newly discovered strm suspects only — the whole-list state is
        already visible on the dashboard, so repeating it every sweep would train
        the user to ignore the channel.
        """
        if not self._notify or self._strm_notified or not new_suspects:
            return
        mtype = self._plugin_mtype()
        if mtype is None:
            logger.warning("[Rsync115Sync] 宿主 MessageType 不可用，已跳过 strm 疑似异常通知以免广播")
            return
        total = len(self._strm_suspects)
        listed = "\n".join(f"• {k}" for k in new_suspects[:_MAX_LOGGED_PATHS])
        more = f"\n（另有 {len(new_suspects) - _MAX_LOGGED_PATHS} 个未列出）" \
            if len(new_suspects) > _MAX_LOGGED_PATHS else ""
        try:
            self.post_message(
                mtype=mtype,
                title="115同步：发现疑似上传异常",
                text=(
                    f"⚠️ 本次新发现 {len(new_suspects)} 个疑似上传异常（清单共 {total} 个）：\n"
                    f"{listed}{more}\n\n"
                    f"判定依据：同步已报告成功，但 {self._strm_grace_hours}h 内未在 strm 目录生成对应文件。\n"
                    f"💡 请先确认 strm 插件本身是否正常（媒体是否识别、功能是否开启），\n"
                    f"   再前往看板「对账异常清单」标签使用「删旧重传」处理。"
                ),
            )
            self._strm_notified = True
            self.save_data("strm_notified", True)
            logger.info(f"[Rsync115Sync] 📤 已推送 strm 疑似异常通知（{len(new_suspects)} 个新发现，"
                        f"清单共 {total} 个）")
        except Exception as e:
            logger.error(f"[Rsync115Sync] strm 疑似异常通知发送失败: {e}")

    def _reset_strm_notified_if_clear(self) -> None:
        """
        疑似清单清空后重置通知标志，使下次新发现能再次提醒，并推送「已全部解决」。

        Reset the notification latch once the suspect list drains, so a future batch
        alerts again; also send a short all-clear so the user knows the earlier
        warning was resolved rather than merely forgotten.
        """
        if self._strm_notified and not self._strm_suspects:
            self._strm_notified = False
            self.save_data("strm_notified", False)
            if self._notify:
                mtype = self._plugin_mtype()
                if mtype is not None:
                    try:
                        self.post_message(
                            mtype=mtype,
                            title="115同步：strm 疑似异常已全部解决",
                            text="✅ 之前报告的 strm 疑似上传异常文件已全部恢复"
                                 "（strm 已生成或已完成重传），无需再处理。",
                        )
                    except Exception as e:
                        logger.error(f"[Rsync115Sync] strm 恢复通知发送失败: {e}")

    # ---- 主动 strm 扫描（补上「从未被观察过」的盲区）----
    #
    # 为什么需要它：观察模式（_strm_check）只遍历自己登记过的文件，而登记只发生在
    # **同步成功之后**。于是「历史上传失败、插件从未认为它成功过」的文件永远进不了
    # 视野 —— 用户在 115 云端看到 `xxx.mkv..xrp4gj` 残留、挂载视图却显示正常，
    # 插件这边毫无察觉（用户实测场景）。主动扫描反其道而行：从**源端**出发，
    # 逐个查该有的 .strm 在不在，因此不依赖「插件自认为成功过」这个前提。
    #
    # 纯本地文件比对（源端 + strm 端都是本地路径），零 115 API。
    # Purely local comparison of two local trees; never touches the 115 mount.

    def _strm_scan(self, limit: int = STRM_SCAN_LIMIT) -> Dict[str, Any]:
        """
        主动扫描：找出源端存在但缺对应 .strm 的文件。

        Proactive sweep for files whose own .strm never appeared.

        ⚠️ 判据固有歧义（务必向用户说明）：它**无法区分**
          a) 从未上传过的存量文件（正常，应走补传而非重传）
          b) 上传了但 CD2 假成功（要抓的异常）
        两者表现完全一致。因此结果一律标为 `scan` 来源的**疑似**，
        且 UI/通知必须提示用户先判断是哪种情况。
        """
        if not self._strm_check_enabled:
            return {"success": False, "message": "strm 交叉验证已关闭"}

        configured = [p for p in self._sync_pairs
                      if (p.get("strm_dir") or "").strip()]
        if not configured:
            return {"success": False,
                    "message": "没有任何映射配置了 strm 目录，无法执行扫描。"
                               "请在配置页为目标映射填写 strm 目录。"}

        def _list_dir(path: str):
            try:
                return os.listdir(path)
            except OSError:
                return None

        excluded = _excluded_dir_names(self._exclude_patterns)

        def _valid_exts(pair):
            # ⚠️ 必须用**视频专用**扩展名，不能用同步用的 media_extensions：
            # 后者含 srt/ssa/ass，而 strm 插件只为视频生成 .strm，字幕永远没有 ——
            # 用同步白名单会让每个字幕都被判成疑似异常（必然误报）。
            # 同理**忽略 all_ext**：勾了「同步所有类型」也不该去查 jpg/nfo 的 strm。
            #
            # 注意必须写 self. —— 这是个闭包，内部的裸名字会按**模块全局**解析，
            # 而 _strm_video_exts 是类方法，不会因此找到（报 NameError）。
            # `getattr` 在真实实例上有效，裸实例（__new__ 造）也一样，
            # 但闭包名字解析与实例无关，这是两种完全不同的查找路径。
            return self._strm_video_exts()

        candidates, truncated, checked = _strm.scan_candidates(
            self._sync_pairs, _list_dir, limit,
            excluded_dirs=excluded, valid_exts_for=_valid_exts)

        now_ts = time.time()
        added = 0
        skipped_ignored = 0
        for key in candidates:
            # 已被用户加入忽略清单的文件不产生疑似条目 —— 「忽略」的语义就是
            # 「不要再为这个文件报警」，而疑似清单是一种报警。用户在 /rsync_ignore
            # 里明确忽略过的文件再次出现，是用户实测反馈的问题。
            # Ignored files never become suspects: ignoring means "stop alerting".
            if self._is_ignored(key):
                skipped_ignored += 1
                continue
            # 已在疑似清单里的不重复计数，但**不刷新时间戳**
            # （刷新会让「首次疑似时间」失去意义，用户无从判断它挂了多久）
            if key in self._strm_suspects:
                continue
            self._strm_suspects[key] = {"ts": now_ts, "origin": _strm.ORIGIN_SCAN}
            added += 1

        if added:
            self.save_data("strm_suspects", self._strm_suspects)
        logger.info(f"[Rsync115Sync] 📺 主动 strm 扫描（已检查 {checked} 个文件）："
                    f"发现 {len(candidates)} 个缺 strm，新增 {added} 个疑似"
                    f"{f'，因忽略规则跳过 {skipped_ignored} 个' if skipped_ignored else ''}")

        if added:
            self._notify_strm_suspects(candidates[:added])

        msg = (f"已检查 {checked} 个文件，发现 {len(candidates)} 个缺 strm 的文件"
               f"（新增 {added} 个）。")
        if skipped_ignored:
            msg += f"\n🚫 其中 {skipped_ignored} 个已命中忽略规则，未计入疑似。"
        if truncated:
            msg += (f"\n⚠️ 已达到单次上限 {limit} 个，**结果被截断** ——"
                    f"若这个数字很大，更可能是 strm 插件本身没在工作，"
                    f"请先确认它的开关与媒体识别是否正常。")
        msg += "\n💡 注意：缺 strm 也可能是「从未上传过的存量文件」，"
        msg += "这类应使用补传而不是删旧重传。"
        return {"success": True, "message": msg,
                "data": {"checked": checked, "found": len(candidates),
                         "added": added, "truncated": truncated,
                         "skipped_ignored": skipped_ignored}}

    def _reply_strm_keyword(self, event: Optional[Event], keyword: str) -> None:
        """
        `/rsync_strm <关键字>`：只检查源端命中关键字的文件，不做整库遍历。

        Check only the source files matching a keyword — no library-wide walk.

        为什么需要这一条：用户往往**已经知道是哪个文件出了问题**（例如在 115
        云端看到了 `xxx.mkv..xrp4gj` 残留），此时遍历整库既慢又无意义。
        复用了与 `/rsync_retry <关键字>` 相同的源端匹配口径（扩展名过滤 +
        排除目录裁剪 + 超限即拒），保证「搜到的」与「能重传的」是同一批文件。

        纯本地操作，零 115 API；命中即写入疑似清单（来源标记为 scan）。
        """
        result = self._search_target_files(keyword)
        if not result["matched"]:
            self._post_reply(event,
                             f"🔍 未在源目录中找到包含「{keyword}」的文件。")
            return
        if result["truncated"]:
            self._post_reply(
                event,
                f"⚠️ 关键字「{keyword}」匹配到超过 {_RETRY_KEYWORD_LIMIT} 个文件，"
                f"请用更精确的文件名缩小范围。本次未做任何检查。"
            )
            return

        missing, present, no_strm_dir, non_video = [], [], [], []
        for key in result["matched"]:
            # _search_target_files 用的是**同步口径**（含字幕），而 strm 只对视频
            # 生成指针文件，因此这里必须再按视频扩展名筛一次，否则字幕会误报。
            ext = os.path.splitext(key.split(":", 1)[-1])[-1].lstrip(".").lower()
            if ext not in self._strm_video_exts():
                non_video.append(key)
                continue
            expected = self._strm_expected_path(key)
            if expected is None:
                no_strm_dir.append(key)
                continue
            if os.path.exists(expected):
                present.append(key)
            else:
                missing.append(key)

        now_ts = time.time()
        added = 0
        skipped_ignored = 0
        for key in missing:
            # 与主动扫描同口径：被忽略的文件不产生疑似条目（忽略即「不再报警」）
            if self._is_ignored(key):
                skipped_ignored += 1
                continue
            if key in self._strm_suspects:
                continue
            self._strm_suspects[key] = {"ts": now_ts, "origin": _strm.ORIGIN_SCAN}
            added += 1
        if added:
            self.save_data("strm_suspects", self._strm_suspects)
            logger.warning(f"[Rsync115Sync] 📺 关键字 strm 检查「{keyword}」："
                           f"命中 {len(result['matched'])} 个，缺 strm {len(missing)} 个，"
                           f"新增疑似 {added} 个: {_brief_paths(missing)}")

        lines = [f"📺 strm 检查「{keyword}」",
                 f"--------------------------------",
                 f"命中文件: {len(result['matched'])} 个",
                 f"✅ 已有 strm: {len(present)} 个",
                 f"❌ 缺 strm  : {len(missing)} 个（新增疑似 {added} 个）"]
        if no_strm_dir:
            lines.append(f"⏭️ 所在映射未配 strm 目录，未检查: {len(no_strm_dir)} 个")
        if non_video:
            # 字幕等非视频文件不会有 .strm，本就不该参与检查；明确告知而非静默丢弃
            lines.append(f"⏭️ 非视频文件（字幕等，不会生成 strm），已跳过: {len(non_video)} 个")
        if skipped_ignored:
            lines.append(f"🚫 命中忽略规则，未计入疑似: {len(skipped_ignored) if False else skipped_ignored} 个")
        if missing:
            lines.append("--------------------------------")
            lines.append("缺 strm 的文件：")
            for k in missing[:_MAX_LOGGED_PATHS]:
                lines.append(f"• {k}")
            if len(missing) > _MAX_LOGGED_PATHS:
                lines.append(f"…（共 {len(missing)} 个）")
            lines.append("")
            lines.append("💡 可能是「从未上传」或「上传了但 CD2 假成功」。")
            lines.append("   已在看板「对账异常清单」的 strm 疑似区，可勾选批量「删旧重传」。")
        self._post_reply(event, "\n".join(lines))

    def _api_strm_clear(self) -> Dict[str, Any]:
        """
        清空 strm 疑似清单（含待观察清单）。

        Clear the strm suspect list (and the pending watch list).

        为什么提供「全清」而不是只清无效项：清洗只能识别**结构性**无效
        （非视频/已忽略/源端已删），而用户可能因为 strm 插件本身配置错误
        而积累了一批误报 —— 那些条目在结构上完全合法，只能整体清空重来。
        清空后下次同步/扫描会重新建立清单。
        Structural pruning cannot detect "the whole strm plugin was misconfigured",
        so a full reset must remain available.
        """
        suspects = len(self._strm_suspects)
        watching = len(self._strm_watch)
        self._strm_suspects = {}
        self._strm_watch = {}
        self.save_data("strm_suspects", self._strm_suspects)
        self.save_data("strm_watch", self._strm_watch)
        self._reset_strm_notified_if_clear()
        logger.info(f"[Rsync115Sync] 🧹 已清空 strm 清单：疑似 {suspects} 个 / 待观察 {watching} 个")
        return {"success": True,
                "message": f"已清空 strm 疑似清单（{suspects} 个）与待观察清单（{watching} 个）。"
                           f"下次同步或扫描会重新建立。"}

    def _api_strm_prune(self) -> Dict[str, Any]:
        """只清理无效条目（非视频 / 已忽略 / 源端已删 / 映射取消验证）。"""
        removed = self._prune_invalid_strm_suspects()
        if removed:
            msg = f"已清理 {removed} 个无效条目，剩余 {len(self._strm_suspects)} 个。"
        else:
            msg = f"没有发现无效条目（当前 {len(self._strm_suspects)} 个）。"
        return {"success": True, "message": msg,
                "data": {"removed": removed, "remaining": len(self._strm_suspects)}}

    def _api_strm_scan(self) -> Dict[str, Any]:
        """
        看板入口：主动扫描缺 strm 的文件（纯本地，零 115 API）。

        **不加 `_is_running` 闸门**：扫描只读本地目录、不启动 rsync、不占窗口配额，
        与同步任务互不干扰（`_scan_missed_ingest` 同理）。加闸门反而会让用户在
        同步进行中无法排查问题。
        No execution gate: this reads local directories only and shares no state with
        a running rsync, so blocking it during a sync would only hurt diagnostics.
        """
        return self._strm_scan()

    def _api_strm_retry(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """
        确认后对疑似异常执行「删旧重传」（复用 v0.1.4 的删旧通道）。

        Confirmed re-transfer for strm suspects, reusing the delete-then-sync path.
        不做无确认的自动重传：strm 插件自身漏生成也会表现为"该有而没有"，
        误报源无法排除，删除是破坏性操作，必须用户确认。
        """
        if self._is_running:
            return {"success": False, "message": "已有任务正在运行，请稍后再试"}
        keys = body.get("keys") or []
        if not keys:
            return {"success": False, "message": "未指定要重传的文件"}
        # 只允许对疑似清单里的 key 操作，防止越权构造任意路径
        allowed = [k for k in keys if k in self._strm_suspects]
        not_allowed = [k for k in keys if k not in self._strm_suspects]
        if not_allowed:
            logger.warning(f"[Rsync115Sync] strm 重传请求含非疑似清单条目，已忽略: {not_allowed[:3]}")
        if not allowed:
            return {"success": False, "message": "所选文件不在疑似异常清单中"}

        deleted, undeletable = self._delete_dest_files_for_retry(allowed)
        if undeletable:
            return {"success": False,
                    "message": f"{len(undeletable)} 个文件目标端删除失败（挂载点可能未就绪），请稍后重试"}
        # 重传期间仍留在疑似清单（失败会被同步流程记入异常清单）；
        # 成功后由 _strm_arm_watch 解除
        self._start_sync_thread(mode="retry", custom_files=deleted)
        return {"success": True,
                "message": f"已删除 {len(deleted)} 个文件并开始定向重传，完成后自动复核 strm"}

    def _search_target_files(self, keyword: str) -> Dict[str, Any]:
        """
        按关键字在**源端**查找文件（供 /rsync_retry <文件名> 与忽略序号复用）。

        Search the *source* roots by keyword, reused by keyword-retry and
        index-based ignore.

        与 /rsync_search 的差异：
        - 带上限并上报是否截断（retry 用「超限即拒」策略，search 用「截断展示」策略）；
        - 关键字命中后不直接采用 —— 删除目标端是破坏性操作，必须由调用方再做
          一次「相对路径精确对齐」校验（见 _delete_dest_files_for_retry）。
        口径与同步/补传一致：按映射扩展名过滤、就地裁剪排除目录、零 115 API。
        """
        keyword = keyword.strip().lower()
        matched: List[str] = []
        truncated = False
        for pair in self._sync_pairs:
            src_dir = (pair.get("src") or "").strip().rstrip("/")
            pair_name = _pair_name(pair)
            if not os.path.exists(src_dir):
                continue
            all_ext = pair.get("all_ext", False)
            valid_exts = _valid_exts_of(self._media_extensions, all_ext)
            excluded_dirs = _excluded_dir_names(self._exclude_patterns)
            for root, dirs, files in os.walk(src_dir):
                dirs[:] = [d for d in dirs if d not in excluded_dirs]
                for f in files:
                    if keyword not in f.lower():
                        continue
                    if valid_exts is not None and \
                            os.path.splitext(f)[-1].lstrip(".").lower() not in valid_exts:
                        continue
                    rel_f = os.path.relpath(os.path.join(root, f), src_dir)
                    matched.append(f"{pair_name}:{rel_f}")
                    if len(matched) > _RETRY_KEYWORD_LIMIT:
                        # 超过上限立即停：retry 是删了重传，宁可不执行也不宜大范围误伤
                        truncated = True
                        break
                if truncated:
                    break
            if truncated:
                break
        return {"matched": matched, "truncated": truncated,
                "total": len(matched) + (1 if truncated else 0) if truncated else len(matched)}

    def _delete_dest_files_for_retry(self, keys: List[str]) -> Tuple[List[str], List[str]]:
        """
        重传前删除目标端文件（经 CD2 挂载），返回 (已删除, 删除失败) 两组 key。

        Delete destination files via the CD2 mount before re-transfer.

        护栏（破坏性操作的三道闸）：
        1. **相对路径精确对齐**：key 形如 "任务名:相对路径"。只有当源端文件存在、
           且其相对路径映射到目标端的绝对路径后，才删**那一个**路径。
           关键字只用于搜源端，绝不参与目标端路径的构造 —— 不会出现"按关键字
           删掉一批相近文件"的情况。
        2. **删除前后都记录大小**：删前若目标端文件不存在则无需删除（直接可传）；
           若存在，记录大小并核对删除后确实消失。
        3. **删除后复查**：rm 失败或复查仍存在（CD2 缓存未失效）时归入
           "删除失败"，调用方必须跳过这些文件 —— 带着脏视图去 rsync 会被
           --size-only 跳过，白白消耗限流配额。

        绝不触碰 `..` 中缀的云端残留：本函数只按「源端相对路径 → 目标端同路径」
        精确删除正式文件，残留不在任何源端清单里，天然不会被选中。
        """
        deleted: List[str] = []
        undeletable: List[str] = []
        for key in keys:
            # 解析 "任务名:相对路径"，并找到该任务的目标根目录
            pair = None
            pair_name = None
            rel_p = None
            for p in self._sync_pairs:
                pn = _pair_name(p)
                if key.startswith(f"{pn}:"):
                    pair = p
                    pair_name = pn
                    rel_p = key.split(f"{pn}:", 1)[1]
                    break
            if pair is None or not rel_p:
                # 无前缀 key（理论上 retry custom_files 不会出现）保守跳过
                logger.warning(f"[Rsync115Sync] 重传前清理：key 无法归属映射，跳过删除: {key}")
                undeletable.append(key)
                continue

            dest_root = (pair.get("dest") or "").strip().rstrip("/")
            src_root = (pair.get("src") or "").strip().rstrip("/")
            src_file = os.path.join(src_root, rel_p)
            dest_file = os.path.join(dest_root, rel_p)

            # 护栏：源端必须真实存在才允许继续（防路径解析异常导致误删别处文件）
            if not os.path.isfile(src_file):
                logger.warning(f"[Rsync115Sync] 重传前清理：源端不存在，跳过删除: {src_file}")
                undeletable.append(key)
                continue

            dest_size = None
            try:
                if os.path.exists(dest_file):
                    dest_size = os.path.getsize(dest_file)
            except OSError as e:
                logger.warning(f"[Rsync115Sync] [{pair_name}] 目标端大小读取失败（继续尝试删除）: "
                               f"{dest_file}: {e}")

            if dest_size is None:
                # 目标端本就不存在（或读取失败且确认不存在）：无需删除，可直接重传
                logger.info(f"[Rsync115Sync] [{pair_name}] 目标端无此文件，无需清理，直接重传: {rel_p}")
                deleted.append(key)
                continue

            try:
                os.remove(dest_file)
            except OSError as e:
                logger.error(f"[Rsync115Sync] [{pair_name}] ❌ 目标端删除失败，该文件本轮跳过: "
                             f"{dest_file}: {e}")
                undeletable.append(key)
                continue

            # 删除后复查：CD2 可能因缓存/瞬时错误「假删」，仍存在则视为失败
            still_there = False
            try:
                still_there = os.path.exists(dest_file)
            except OSError:
                still_there = False
            if still_there:
                logger.error(f"[Rsync115Sync] [{pair_name}] ❌ 目标端删除后仍存在（CD2 视图未失效），"
                             f"该文件本轮跳过: {dest_file}")
                undeletable.append(key)
                continue

            logger.info(f"[Rsync115Sync] [{pair_name}] 🧹 已删除目标端待重传文件: {rel_p} "
                        f"（删前大小 {dest_size} 字节）")
            deleted.append(key)
        return deleted, undeletable

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
        """
        处理 /rsync_* 远程指令的统一入口。

        Single entry point for all /rsync_* remote commands. The action comes from
        the command data registered in get_command().
        """
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
            # 根据关键字从本地源目录查找匹配的文件，供确认后定向重传
            if not text_arg:
                self._post_reply(event, "⚠️ 请提供搜索关键字，例如：/rsync_search 繁花")
                return

            keyword = text_arg.lower()
            matched = []
            # 展示上限：手机消息太长会被渠道截断或淹没，列表只展示前 N 条。
            # ⚠️ 但候选必须**全量收集**、只截断展示 —— 早先实现把收集也截断在 15，
            # 导致超过 15 个匹配时用户永远选不到第 16 个（all 也只重传前 15 个），
            # 用户实测「24 个文件只找到 15 个」即此缺陷。
            _SEARCH_DISPLAY_LIMIT = 15

            for pair in self._sync_pairs:
                src_dir = (pair.get("src") or "").strip().rstrip("/")
                pair_name = _pair_name(pair)
                if not os.path.exists(src_dir):
                    continue
                # 与同步/补传保持一致的过滤口径：扩展名 + 排除规则。
                # 早先实现两者都不应用，列表会混入 .nfo/.jpg 等永远不会被同步的
                # 文件，重传它们浪费限流配额且没有意义。
                all_ext = pair.get("all_ext", False)
                # 口径与同步/补传共用同一实现，避免「搜索能搜到但同步不认」的漂移
                valid_exts = _valid_exts_of(self._media_extensions, all_ext)
                excluded_dirs = _excluded_dir_names(self._exclude_patterns)

                for root, dirs, files in os.walk(src_dir):
                    # 就地裁剪被排除的目录（@eaDir/#recycle 等），不下钻
                    dirs[:] = [d for d in dirs if d not in excluded_dirs]
                    for f in files:
                        if keyword not in f.lower():
                            continue
                        if valid_exts is not None and os.path.splitext(f)[-1].lstrip(".").lower() not in valid_exts:
                            continue
                        rel_f = os.path.relpath(os.path.join(root, f), src_dir)
                        matched.append(f"{pair_name}:{rel_f}")

            if not matched:
                self._post_reply(event, f"🔍 未找到包含关键字「{text_arg}」的本地入库媒体文件。")
                return

            # 候选全量保留（confirm 可重传全部），仅展示层截断
            self._waiting_confirm_retries = matched
            display = matched[:_SEARCH_DISPLAY_LIMIT]
            list_text = "\n".join([f"{i+1}. {item}" for i, item in enumerate(display)])
            truncated_hint = (
                f"（另有 {len(matched) - _SEARCH_DISPLAY_LIMIT} 个未列出，"
                f"确认 all 时会一并重传）\n" if len(matched) > _SEARCH_DISPLAY_LIMIT else ""
            )
            reply = (
                f"🔍 找到 {len(matched)} 个匹配媒体"
                f"{'，展示前 %d 个' % _SEARCH_DISPLAY_LIMIT if len(matched) > _SEARCH_DISPLAY_LIMIT else ''}：\n"
                f"--------------------------------\n"
                f"{list_text}\n"
                f"{truncated_hint}"
                f"--------------------------------\n"
                f"👉 请发送确认指令触发重传：\n"
                f"• 全部重传: /rsync_confirm (或 /rsync_confirm all)\n"
                f"• 选单序号: /rsync_confirm 1\n"
                f"• 多个序号: /rsync_confirm 1,2 或 /rsync_confirm 1 2\n"
                f"• 范围序号: /rsync_confirm 1-2 4\n"
                f"⚠️ 注意：确认只对已收集的候选生效，当前候选共 {len(matched)} 个"
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
                return
            allowed, reason = self._force_cooldown_allows()
            if not allowed:
                self._post_reply(
                    event,
                    f"⛔ 已跳过全量校验：{reason}\n"
                    f"该操作会遍历 115 全目录（请求量按媒体库文件数计，可能上万次），"
                    f"频繁执行极易触发风控。\n"
                    f"如需补传存量媒体，请改用 /rsync_backfill（只扫源端、按配额分批）。"
                )
                return
            self._start_sync_thread(mode="force", channel_event=event)

        elif action == "retry":
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中。")
            elif text_arg:
                # 带关键字 = 「目标明确」的单文件补偿：
                # 搜源端 → 删目标端（经 CD2 挂载，强制云端状态与视图对齐）→ 定向重传。
                #
                # 为什么必须先删：CD2 改名失败等场景下，CD2 挂载视图会显示目标文件
                # 「存在且大小正常」，但 115 服务端实际只有改名失败的半成品
                # （形如 影片.mkv..xrp4gj）。此时 rsync --size-only 比较源/目标大小
                # 判定「已同步」而跳过 —— 重传永远不会发生，且插件无法从视图发现这一点。
                # 先通过挂载点 rm，CD2 会真实调用 115 删除接口，把视图与云端一起纠正，
                # 之后 rsync 发现目标端确无此文件，必然完整重传并重新走改名流程。
                # （同 sync_115 仓库 retry_file.sh 的既有做法，此处插件化并加护栏。）
                # Keyword mode = targeted single-file compensation. The destination
                # file must be deleted via the CD2 mount first: the mount view may
                # report the file as present while the 115 cloud only holds a
                # rename-failed partial, which would make --size-only skip the
                # re-transfer entirely.
                result = self._search_target_files(text_arg)
                if not result["matched"]:
                    self._post_reply(event,
                                     f"🔍 未在源目录中找到包含「{text_arg}」的文件，未做任何改动。")
                    return
                if result["truncated"]:
                    self._post_reply(
                        event,
                        f"⚠️ 关键字「{text_arg}」匹配到 {result['total']} 个文件，超过单次上限 "
                        f"{_RETRY_KEYWORD_LIMIT} 个。\n请用更精确的文件名缩小范围，本次未做任何改动。"
                    )
                    return
                deleted, undeletable = self._delete_dest_files_for_retry(result["matched"])
                if undeletable:
                    # 目标端删不掉 = 视图可能仍是脏的，此时 rsync 会因 --size-only
                    # 跳过这些文件（白占配额），必须明确告知而不是静默继续
                    names = "\n".join(f"• {k}" for k in undeletable[:_MAX_LOGGED_PATHS])
                    self._post_reply(
                        event,
                        f"⚠️ 有 {len(undeletable)} 个文件在目标端删除失败（挂载点可能未就绪），"
                        f"已跳过它们，其余 {len(deleted)} 个继续重传：\n{names}\n"
                        f"建议稍后重试；若反复失败请检查 CD2 挂载状态。"
                    )
                    if not deleted:
                        return
                summary = (
                    f"🧹 已清理目标端 {len(deleted)} 个文件并开始定向重传：\n"
                    + "\n".join(f"• {k}" for k in deleted[:_MAX_LOGGED_PATHS])
                    + (f"\n（共 {len(deleted)} 个）" if len(deleted) > _MAX_LOGGED_PATHS else "")
                )
                self._post_reply(event, summary)
                self._start_sync_thread(mode="retry", custom_files=deleted,
                                        channel_event=event)
            else:
                # 不带关键字：维持既有语义 —— 重传历史异常清单
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

        elif action == "strm":
            # /rsync_strm         → 全量主动扫描
            # /rsync_strm <关键字> → 只查指定文件（不遍历整库）
            # /rsync_strm clear   → 清空疑似与待观察清单
            # /rsync_strm prune   → 只清理无效条目
            #
            # 两种模式并存的原因：全量扫描是「我不知道哪些文件有问题」的答案，
            # 但当用户**已经明确知道**是哪个文件时（例如在 115 云端看到残留），
            # 遍历整库纯属浪费 —— 关键字模式直接定位那一个，秒回。
            if not self._strm_check_enabled:
                self._post_reply(event, "⚠️ strm 交叉验证已在配置页关闭，无法扫描。")
                return
            configured = [p for p in self._sync_pairs if (p.get("strm_dir") or "").strip()]
            if not configured:
                self._post_reply(
                    event,
                    "⚠️ 没有任何映射配置了 strm 目录，无法扫描。\n"
                    "请到配置页为需要验证的映射填写「strm 目录」（strm 插件的输出根目录）。"
                )
                return

            arg_lower = (text_arg or "").lower()
            if arg_lower in ("clear", "清空", "reset"):
                result = self._api_strm_clear()
                self._post_reply(event, "🧹 " + result["message"])
                return
            if arg_lower in ("prune", "清理"):
                result = self._api_strm_prune()
                self._post_reply(event, "🧹 " + result["message"])
                return
            if text_arg:
                self._reply_strm_keyword(event, text_arg)
                return

            self._post_reply(event, "🔍 正在扫描源端并逐个比对 strm（纯本地，不访问 115）...")
            try:
                result = self._strm_scan()
            except Exception as e:
                logger.error(f"[Rsync115Sync] 主动 strm 扫描异常: {e}\n{traceback.format_exc()}")
                self._post_reply(event, f"❌ 扫描过程出错：{e}")
                return
            if not result.get("success"):
                self._post_reply(event, f"⚠️ {result.get('message')}")
                return
            data = result.get("data") or {}
            reply = (
                f"📺 strm 扫描完成\n"
                f"--------------------------------\n"
                f"已检查源端文件: {data.get('checked', 0)} 个\n"
                f"缺对应 strm: {data.get('found', 0)} 个\n"
                f"新增疑似异常: {data.get('added', 0)} 个\n"
            )
            if data.get("truncated"):
                reply += (f"⚠️ 已达到单次上限 {STRM_SCAN_LIMIT} 个，结果被截断。\n"
                          f"   数量这么大通常说明 strm 插件本身没在工作，"
                          f"请先确认它的开关与媒体识别是否正常。\n")
            reply += (
                f"--------------------------------\n"
                f"💡 缺 strm 有**两种**可能，处理方式不同：\n"
                f"• 从未上传过的存量文件 → 用 /rsync_backfill 补传\n"
                f"• 上传了但 CD2 假成功（云端可能有 ..xxx 残留）→ 用看板「删旧重传」\n"
                f"💡 疑似清单已在看板「对账异常清单」标签内，可勾选批量处理。"
            )
            self._post_reply(event, reply)

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
            ready_count, cooling_count, stale_count = self._count_queue(now_ts, threshold)

            reply = (
                f"📊 115网盘同步状态报告\n"
                f"当前状态: {state}\n"
                f"冷却就绪可同步: {ready_count} 个\n"
                f"冷却缓冲中: {cooling_count} 个 (设定: {self._delay_hours}h)\n"
                f"彻底缺失文件: {len(st.get('missing_files', []))} 个\n"
                f"残缺不全文件: {len(st.get('corrupt_files', []))} 个\n"
            )
            if stale_count:
                reply += (f"🗑️ 源端已删除待清理: {stale_count} 个"
                          f"（文件已不在本地，将在下轮同步时移出队列，不计入上方计数）\n")
            if self._missed_queue:
                reply += (f"🕳️ 错过入库待补扫: {len(self._missed_queue)} 个"
                          f"（插件重载期间丢失事件，已由源端扫描补回，下轮同步自动带上）\n")
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
