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

# 插件管理器：用于确认 strm 助手插件是否真的在运行。
# 只有当它确实加载并启用时才值得去发那条命令 —— 否则命令会石沉大海，
# 而用户已经在看板上点过按钮，无从判断是「没装」还是「装了没生效」。
# Plugin manager, used to check whether the strm helper plugin is actually running.
try:
    from app.sdk.plugins import PluginManager as _PluginManager
except Exception:  # pragma: no cover - 兼容旧宿主
    _PluginManager = None


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

# ---- 已拆分到兄弟模块 / extracted to sibling modules ----
# 阶段 1（纯逻辑，无状态）：constants.py / paths.py / ignore.py / strm.py
# 阶段 2（Mixin 方法块，仍无状态）：strm_ops.py / sync_ops.py / commands.py
#   · strm_ops.py   strm 交叉验证状态机 + 助手联动 + 全部 strm Web API
#   · sync_ops.py   上传限流 / 退避 / 冷却与补传队列
#   · commands.py   /rsync_* 命令表、分发入口与回复通道
# 状态红线不变：宿主会重新执行本文件，但插件自行导入的模块全局量是共享的，
# 因此**可变状态必须留在插件实例上**——Mixin 搬的是代码不是状态（见各模块头注释），
# 组合根（本文件）负责把宿主能力绑定（_PluginManager / MessageType）注入兄弟模块。
#
# 这里用下划线别名导入，是为了让类体与既有调用点无需到处加模块前缀 ——
# 类体在求值时能读到本模块的全局名字（与 _TRANSFER_SUCCESS_EVENTS 同理）。
from . import strm as _strm  # noqa: E402
from . import strm_ops as strm_ops_mod  # noqa: E402
from .strm_ops import StrmOpsMixin  # noqa: E402
from .sync_ops import SyncOpsMixin  # noqa: E402
from . import commands as commands_mod  # noqa: E402
from .commands import CommandsMixin  # noqa: E402
# 组合根注入：宿主能力绑定以 __init__.py 为唯一真相（见 commands.py 头注释）。
commands_mod.MessageType = MessageType  # noqa: E402
# 组合根注入：宿主能力绑定以 __init__.py 为唯一真相，strm_ops 不留拷贝（见其模块头注释）。
strm_ops_mod._PluginManager = _PluginManager  # noqa: E402
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
    P115_PAN_DIR_HINT as _P115_PAN_DIR_HINT,
    P115_PAN_MAPPING_FIELD as _P115_PAN_MAPPING_FIELD,
    P115_STRM_COMMAND as _P115_STRM_COMMAND,
    P115_STRM_HELPER_PLUGIN as _P115_STRM_HELPER_PLUGIN,
    RETRY_KEYWORD_LIMIT as _RETRY_KEYWORD_LIMIT,
    SIDECAR_EXTS as _SIDECAR_EXTS,
    STRM_CHECK_INTERVAL as _STRM_CHECK_INTERVAL,
    STRM_GEN_DIR_LIMIT,
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


class Rsync115Sync(StrmOpsMixin, SyncOpsMixin, CommandsMixin, _PluginBase):
    plugin_name = "115网盘同步助手"
    plugin_desc = "需依赖 CloudDrive2 (CD2) 将 115 网盘挂载到本地宿主机并映射至 MoviePilot 容器。专为 CD2 挂载 115 打造：支持入库 N 小时冷却后同步、双向对账审计、关键字查找入库重试与手机端交互指令。"
    plugin_icon = "mdi-cloud-sync"
    plugin_version = "0.1.10"
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
        #   "strm_dir": "/path/strm/TV" 或 "", "pan_dir": "/HomeTheater/TV" 或 ""}]
        # Directory mapping pairs. Each entry maps one local source root to one
        # CD2-mounted 115 destination root; `all_ext` disables extension filtering.
        # `strm_dir`（可选，与 src 不同根、由用户配置）启用 strm 交叉验证：
        # 同步成功后观察对应 strm 是否在宽限期内生成，未生成即疑似上传异常。
        # Optional per-pair strm root (different root, user-configured). When set,
        # a successful sync arms a watch: if the matching .strm never appears within
        # the grace window, the file is flagged as a suspected upload failure.
        #
        # `pan_dir`（可选）是该映射在 **115 网盘**里的目录，供「先尝试生成 strm」
        # 把参数传给 strm 助手使用。必须由用户显式填写：
        #   - 助手只接受它 full_sync_strm_paths 里存在的网盘路径；
        #   - 本地 strm 目录与网盘目录**不必同构**，无法从前者推导出后者；
        #   - 反查助手配置属跨插件耦合，对方改字段即静默失效。
        # `pan_dir` is the mapping's directory **on the 115 cloud**, used when asking
        # the strm helper to regenerate pointers. It must be explicit: the helper only
        # accepts its own full-sync paths, and the local and cloud trees need not
        # correspond, so no derivation from local paths can be sound.
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
        # 已请 strm 助手补生成过的 key → 时间戳。
        # 记录它的目的是**防止无限重试**：用户可能反复点「尝试生成」，而助手每次
        # 都会真的去遍历云端目录（有成本）。已请求过的条目在看板标出，让用户先看
        # 结果再决定是否再试，而不是无痕地重复发起。
        # Keys already handed to the helper, so repeated clicks do not silently
        # re-trigger cloud traversals.
        self._strm_gen_requested: Dict[str, float] = {}

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
        saved_gen = self.get_data("strm_gen_requested") or {}
        if isinstance(saved_gen, dict):
            self._strm_gen_requested = saved_gen
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
            {"path": "/strm_check", "endpoint": self._api_strm_check, "methods": ["POST"], "auth": "bear"},
            {"path": "/strm_probe", "endpoint": self._api_strm_probe, "methods": ["POST"], "auth": "bear"},
            {"path": "/strm_scan", "endpoint": self._api_strm_scan, "methods": ["POST"], "auth": "bear"},
            {"path": "/strm_prune", "endpoint": self._api_strm_prune, "methods": ["POST"], "auth": "bear"},
            {"path": "/strm_ignore", "endpoint": self._api_strm_ignore, "methods": ["POST"], "auth": "bear"},
            {"path": "/strm_clear", "endpoint": self._api_strm_clear, "methods": ["POST"], "auth": "bear"},
            {"path": "/strm_retry", "endpoint": self._api_strm_retry, "methods": ["POST"], "auth": "bear"},
            # ⚠️ 本插件**唯一**依赖外部插件的端点：它把命令交给 P115StrmHelper 执行。
            # 其余全部端点（含 strm 观察/扫描/清理/删旧重传）都是自包含的 ——
            # 在 UI 与文档里必须区分清楚，否则用户会以为不装助手就用不了 strm 功能。
            # The only endpoint that depends on another plugin; everything else,
            # including the whole strm cross-validation feature, is self-contained.
            {"path": "/strm_generate", "endpoint": self._api_strm_generate, "methods": ["POST"], "auth": "bear"},
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
                # 观察期明细：key → 同步成功时间戳。
                # 之前只返回数量（strm_watching），用户看到「1 个文件处于观察期」
                # 却不知道是哪个文件、等了多久 —— 明细让观察状态可见、可预期
                # （对照宽限期就能算出还剩多久出结果）。
                "strm_watch_detail": {k: ts for k, ts in self._strm_watch.items()},
                # 每个观察条目的计时基准：key → "sync" | "gen"。
                # 看板必须用它决定「还剩多久」以及该跟哪个窗口比 —— 补生成重新
                # 计时过的条目若仍按同步时刻算，用户会看到「入口说还有 5 小时、
                # 另一个入口说已到期」。判定与显示走同一个 strm.watch_state_of。
                "strm_watch_clocks": {
                    k: _strm.watch_state_of(k, self._strm_watch,
                                            self._strm_gen_requested, time.time())[0]
                    for k in self._strm_watch},
                "strm_regrace_hours": _strm.REGRACE_HOURS,
                "strm_watching": len(self._strm_watch),
                "strm_grace_hours": self._strm_grace_hours,
                "strm_check_enabled": self._strm_check_enabled,
                # 已请 strm 助手补生成过的 key → 时间戳，看板据此标出
                # 「已请求生成，等待结果」，避免用户重复点击（每次都会让助手
                # 真的去遍历云端目录，是有成本的操作）。
                "strm_gen_requested": dict(self._strm_gen_requested),
                "strm_gen_dir_limit": STRM_GEN_DIR_LIMIT,
                "strm_helper_ok": self._strm_helper_ready(),
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

































