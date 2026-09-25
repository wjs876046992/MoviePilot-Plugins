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

# 宿主 webhook 事件的 payload 模型。实现 `webhook_parser` 时必须返回它的实例 ——
# 宿主在 WebhookChain 里直接把它交给 eventmanager，返回别的类型（或 None）都会
# 让整条链静默结束。桩环境下退化成一个「能带任意属性」的最小替身。
try:
    from app.schemas.mediaserver import WebhookEventInfo as _HostWebhookEventInfo
except Exception:  # pragma: no cover - 桩环境
    _HostWebhookEventInfo = None

    # ⚠️ 替身类必须定义在这个 except 块**内部**（而不是模块顶层）：
    # 注册契约测试用 AST 取「源文件里第一个 ClassDef」当作插件主类，
    # 顶层再放一个类会让它取错对象，表现为一批「缺少基类契约方法」的误报。
    class _FallbackWebhookEventInfo:  # type: ignore[no-redef]
        """桩环境替身：只保证能挂属性，供单测验证认领逻辑。"""

        def __init__(self, **kwargs: Any) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)


def _webhook_event_info_class():
    """返回宿主可用的 WebhookEventInfo 类型（桩环境用替身）。"""
    return _HostWebhookEventInfo or _FallbackWebhookEventInfo


# ---- 已删除：MoviePilot 整理完成事件订阅（2026-09-25） ----
# 这里曾有 `_transfer_success_events()` 与模块级 `_TRANSFER_SUCCESS_EVENTS`，
# 用于订阅宿主按文件类型分派的三个「整理成功」事件。**整条已移除**，理由四条：
#
#   1. 只覆盖整理链路 —— 手动放进媒体库、外部工具搬入（本插件的 9KG 场景）、
#      MoviePilot 之外的下载完成，都不产生整理事件；
#   2. durable outbox **不重放** —— 插件忙/重载/重启期间的事件进有限重试，
#      超过上限即永久丢弃，且事后无从补发；
#   3. 宿主版本相关 —— 后两个事件靠 `getattr` 探测，旧宿主只有 TransferComplete，
#      字幕与音频**静默全丢**；
#   4. 装饰器在**类体**求值 —— v0.1.7 拆分时被误删过一次（DEVELOPMENT §3.8），
#      删掉不报错，只是永远收不到事件，属最难自查的一类回归。
#
# 替代它的主通道是**源端游标扫描**（`_scan_source_cursor`）：判据基于文件自身
# mtime 与上次成功同步的游标，与上述四点全部无关 —— 它看得见手动入库与 9KG、
# 游标落盘后重载可续、不依赖宿主版本、也不靠装饰器注册。
# webhook 保留为「9KG 专属通道 + 加速器」，不再承担完整性。
#
# The host transfer-event subscription was removed entirely (see above). The
# primary ingest channel is now a source-root cursor scan driven by file mtime;
# the webhook channel is kept as an accelerator only. Records kept in
# DEVELOPMENT §3.8 / §4.0f.
def _today_start_ts(now_ts: Optional[float] = None) -> float:
    """
    今天 0 点的本地时间戳 —— 源端扫描的**首次基线**。

    Local midnight of today, used as the first-scan baseline.

    为什么首次基线取当日 0 点、而不是「当前时刻」也不是「只记不入队」：
      · 取当前时刻 → 今天已入库的文件 mtime 比它旧，**成为永久漏**；
      · 「只记不入队」引导阶段 → 同一个问题，还要多维护一份"基线已建立"状态。
      · 取当日 0 点 → 今天入库的全部覆盖（扫描本来也只在今天的时间尺度上
        有意义），且与 sync_115.sh 的 `--since` 缺省行为一致。
    代价是首次启用可能会把今天已入库的存量一并捞进队列 —— 这是**期望行为**
    （它们确实还没上传），且队列有冷却与批次上限兜住，不会瞬时打满配额。
    """
    import datetime as _dt
    now = _dt.datetime.fromtimestamp(now_ts if now_ts is not None else time.time())
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.timestamp()


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
# 类体在求值时能读到本模块的全局名字。
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
    LEGACY_DEFAULTS_ALL as _LEGACY_DEFAULTS_ALL,
    MAX_LOGGED_PATHS as _MAX_LOGGED_PATHS,
    MAX_PATH_CHARS as _MAX_PATH_CHARS,
    SOURCE_CURSOR_OVERLAP_SECS as _SOURCE_CURSOR_OVERLAP_SECS,
    SOURCE_SCAN_CRON_DEFAULT as _SOURCE_SCAN_CRON_DEFAULT,
    SOURCE_SCAN_ENABLED_DEFAULT as _SOURCE_SCAN_ENABLED_DEFAULT,
    SOURCE_SCAN_INTERVAL_LEGACY_DEFAULT as _SOURCE_SCAN_INTERVAL_LEGACY_DEFAULT,
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
    ext_of as _ext_of,
    force_problem_rel_paths as _force_problem_rel_paths,
    is_junk_file_name as _is_junk_file_name,
    merge_force_anomalies as _merge_force_anomalies,
    pair_for_path as _pair_for_path,
    pair_name as _pair_name,
    success_keys_after_audit as _success_keys_after_audit,
    valid_extension as _wh_valid_extension,
    valid_exts_of as _valid_exts_of,
)
# Webhook 报文解析（纯逻辑，无状态）。认领判据也在这里（判定「这条报文是不是发给
# 本插件的」），但它不再是某个自建端点的内部函数 —— 自建端点已于 2026-09-22 移除，
# 现在唯一的载体是宿主的平台 webhook 链路，见 DEVELOPMENT §9.18。
from . import webhook as _wh  # noqa: E402
from . import store as _store_mod  # noqa: E402
from .store import Store as _Store  # noqa: E402


class Rsync115Sync(StrmOpsMixin, SyncOpsMixin, CommandsMixin, _PluginBase):
    plugin_name = "115网盘同步助手"
    plugin_desc = "需依赖 CloudDrive2 (CD2) 将 115 网盘挂载到本地宿主机并映射至 MoviePilot 容器。专为 CD2 挂载 115 打造：支持入库 N 小时冷却后同步、双向对账审计、关键字查找入库重试与手机端交互指令。"
    plugin_icon = "mdi-cloud-sync"
    plugin_version = "0.2.7"
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

    # 历史默认值与源端扫描参数：迁移逻辑（_migrate_legacy_defaults）与 __init__
    # 都通过 self.* 访问它们。**别名必须保留** —— 直接删掉类属性会让
    # `self._SOURCE_SCAN_ENABLED_DEFAULT` 抛 AttributeError（拆分时实测踩到）。
    # These aliases are load-bearing: __init__ and _migrate_legacy_defaults read them
    # through `self.*`, so removing the class attributes breaks instantiation.
    _LEGACY_DEFAULTS = _LEGACY_DEFAULTS
    _LEGACY_DEFAULTS_ALL = _LEGACY_DEFAULTS_ALL
    # 迁移目标值与「字段 → 实例属性名」的映射。写成表而不是 if 链：
    # 每加一代旧默认值，只需往 constants 的表里加一项，这里不必改。
    _LEGACY_MIGRATION_TARGETS = {
        "media_extensions": DEFAULT_MEDIA_EXTENSIONS,
        "exclude_patterns": DEFAULT_EXCLUDE_PATTERNS,
        "rsync_timeout": DEFAULT_RSYNC_TIMEOUT,
    }
    _LEGACY_MIGRATION_ATTRS = {
        "media_extensions": "_media_extensions",
        "exclude_patterns": "_exclude_patterns",
        "rsync_timeout": "_rsync_timeout",
    }
    # 源端游标扫描的节奏与重叠窗口（见 constants.SOURCE_SCAN_*）。
    _SOURCE_SCAN_CRON_DEFAULT = _SOURCE_SCAN_CRON_DEFAULT
    _SOURCE_SCAN_ENABLED_DEFAULT = _SOURCE_SCAN_ENABLED_DEFAULT
    _SOURCE_SCAN_INTERVAL_LEGACY_DEFAULT = _SOURCE_SCAN_INTERVAL_LEGACY_DEFAULT
    _SOURCE_CURSOR_OVERLAP_SECS = _SOURCE_CURSOR_OVERLAP_SECS

    def __init__(self):
        super().__init__()
        self._enabled: bool = False
        self._listen_transfer: bool = True
        # 源端游标扫描（入库发现的**主通道**，取代已删除的整理事件订阅）
        self._source_scan_enabled: bool = self._SOURCE_SCAN_ENABLED_DEFAULT
        self._source_scan_cron: str = self._SOURCE_SCAN_CRON_DEFAULT
        self._notify: bool = True
        # ---- Webhook 入库（第二来源，见 webhook.py 头注释）----
        # 注：这里曾有 `_webhook_channels`（来源渠道过滤，默认 emby），已于
        # 2026-09-24 移除。本插件的 webhook 入口**只认显式发给自己的报文**
        # （`source=rsync115sync` / `X-Webhook-Target` 头），处理侧同样只接受
        # 自己认领的结果 —— 别的媒体服务器推来的事件由**平台自己的解析器**
        # 处理，我们既不监听也不处理，因此不再需要一份渠道白名单。
        # 详见 DEVELOPMENT §4.0a ③-b。
        # webhook 运行态：累计收入计数 + 最近一次报文的字段结构摘要。
        # 必须持久化（save_data）而不是只放内存：用户排查时习惯「推一条 → 重载插件
        # → 去看板确认」，只在内存里的话重载即清零，永远看不到刚推的那一条。
        # 计数只增不清，用作「这条路是否真的在工作」的证据。
        # 初始化走 _wh_stat()，保证「模板只有一处真相」，不在类体里再放一份可变默认值。
        self._webhook_stat: Dict[str, Any] = self._wh_stat()

        # 入库闸门挡下的扩展名累计分布（扩展名 → 次数），供看板回答
        # 「哪一类文件正在被静默丢弃」。**累计不清零**，与 webhook_stat 同理：
        # 它是一条「这条路是不是在丢东西」的证据，清掉就等于让问题再次隐形。
        # 说明：这里曾是整个插件里最危险的一处盲区 —— 闸门丢弃只记 debug，
        # 看板四个计数里没有它，于是「音频 100% 被丢」潜伏了多个版本。
        self._ingest_skip_stat: Dict[str, int] = {}

        # 4h：源端扫描没有"文件写完了"信号，冷却期因此多了一层职责 —— 等文件写完
        # （正在写入的文件 mtime 恰恰最新）。2h 对慢写的大文件不够，见 USAGE。
        # 文件台账（SQLite）。
        #
        # ⚠️ 属性名**不要**用 `self._store`：那是宿主插件基类内部极可能占用的
        # 名字（本仓的测试桩就用它存 `save_data` 的数据），撞名会让 `save_data`
        # 直接 `TypeError: 'NoneType' object does not support item assignment` ——
        # 而报错点在**宿主基类**里，从堆栈看不出和台账有关。
        # 实测踩到过：改完台账后 `test_instantiation_smoke` 挂在
        # `_add_ignore_rule → save_data` 上，查了几步才发现是取名撞了。
        # 用 `_ledger` 这种本插件专属的名字，从根上避免。
        #
        # **惰性打开**：`__new__` 构造的实例（单测/部分宿主
        # 路径）没有 `get_data_path`，此时不能抛异常 —— 台账缺失时相关功能降级
        # 为空操作，而不是让整个插件加载失败。
        # Lazy: instances built via `__new__` have no data path; a missing ledger
        # must degrade to no-ops, never break plugin loading.
        self._ledger: Optional[_Store] = None

        self._delay_hours: float = 4.0
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
        self._strm_grace_minutes: int = 5              # 宽限期（分钟），可配置
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
        # ⚠️ 这里曾有 `_missed_queue` + `_missed_last_scan`（「错过入库待补扫清单」），
        # 已于 2026-09-25 删除，它被 `_source_cursor` 取代。删除理由是**语义重复
        # 且危险**：那个队列的注释写着「不参与冷却计时」——它的原意是"这些文件
        # 已经比原计划多等了很久，再等一轮毫无意义"，但实现成了**无条件跳过冷却**，
        # 于是源端扫描刚发现一个 10 秒前刚落地的文件，也会被判为"错过的"并立即上传。
        # 现在两个场景由冷却基准 `min(发现时刻, mtime)` 自动区分，不需要第二个队列。
        # The missed-event queue was removed: "skip cool-down unconditionally" made a
        # freshly-dropped file upload immediately. `_source_cursor` replaces it.

        # 源端扫描游标：映射名 → 「上次成功扫描的时刻」。
        # 与 sync_115.sh 的 data/last_sync_<job> 同构，是「不漏」的判据所在。
        # 落盘文件而非 save_data 语义上的小状态：条目数 = 映射数（通常个位数）。
        self._source_cursor: Dict[str, float] = {}
        # 上次源端扫描的时刻，供看板与指令回显（0 表示尚未扫描过）
        self._source_scan_last: float = 0.0

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
            self._source_scan_enabled = bool(
                config.get("source_scan_enabled", self._SOURCE_SCAN_ENABLED_DEFAULT)
            )
            self._source_scan_cron = self._read_source_scan_cron(config)
            self._notify = config.get("notify", True)
            self._delay_hours = float(config.get("delay_hours", 4.0))
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
            self._strm_grace_minutes = self._read_grace_minutes(config)
            self._warn_on_legacy_grace_unit(config)
            # 老配置迁移：把「从未调整过」的旧默认值平滑升到新默认值
            self._migrate_legacy_defaults(config)

        # 恢复限流窗口与退避状态（必须早于任何上传判定）
        self._load_rate_limit_state()
        self._last_force_ts = float(self.get_data("last_force_ts") or 0.0)

        # 打开文件台账（SQLite）并做一次性迁移。
        # ⚠️ 必须排在下面的字典恢复**之前**：迁移要用那些字典的内容。
        self._open_store()

        # 恢复持久化数据
        #
        # ⚠️ 三个字典（pending_queue / strm_watch / strm_suspects）在台账可用时
        # **不再从 save_data 恢复** —— 否则这一步会把 `_bind_ledger_maps()` 装好的
        # 替身又覆盖回普通 dict，真相源悄悄变回旧字典（而台账看起来"能用"）。
        # 实测踩到过：绑完替身紧接着被这里覆盖，两个存储并存且不一致。
        # ⚠️ 台账可用时**不是"跳过恢复"**，而是把旧数据喂进台账 —— 见
        # `_seed_ledger_from_saved` 的说明。跳过会让"升级后第一次启动"丢数据。
        saved_queue = self.get_data("pending_queue") or {}
        if isinstance(saved_queue, dict):
            self._seed_ledger_from_saved(self._pending_queue, saved_queue, "enqueued_at")
        self._last_status["missing_files"] = self.get_data("missing_files") or []
        self._last_status["corrupt_files"] = self.get_data("corrupt_files") or []
        saved_ignored = self.get_data("ignored_files") or []
        if isinstance(saved_ignored, list):
            self._ignored_rules = saved_ignored
        # 恢复源端扫描游标（主通道的「看到了哪里」，必须跨重载续上）
        saved_cursor = self.get_data("source_cursor") or {}
        if isinstance(saved_cursor, dict):
            self._source_cursor = {str(k): float(v) for k, v in saved_cursor.items()}
        self._source_scan_last = float(self.get_data("source_scan_last") or 0.0)
        if self._source_cursor:
            newest = max(self._source_cursor.values())
            logger.info(f"[Rsync115Sync] 🔍 已恢复源端扫描游标：{len(self._source_cursor)} 个映射，"
                        f"最近一次推进于 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(newest))}")

        # 恢复 webhook 运行态（累计计数与最近一次报文摘要）。
        # 逐字段合并而不是整体替换：运行态字典跨版本会增加字段，整体替换会把
        # 新版本新增的计数键抹掉，看板取字段时拿到 KeyError。
        # 入库闸门挡下的扩展名分布（累计）。与 webhook_stat 同样必须持久化：
        # 它的全部价值就是「长期累计」，重载即清零等于没有。
        saved_skip_stat = self.get_data("ingest_skip_stat") or {}
        if isinstance(saved_skip_stat, dict):
            self._ingest_skip_stat = {str(k): int(v) for k, v in saved_skip_stat.items()}
        saved_wh_stat = self.get_data("webhook_stat") or {}
        if isinstance(saved_wh_stat, dict):
            self._webhook_stat_now().update(saved_wh_stat)

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
            self._seed_ledger_from_saved(self._strm_watch, saved_watch, "enqueued_at")
        saved_suspects = self.get_data("strm_suspects") or {}
        if isinstance(saved_suspects, dict):
            self._seed_ledger_from_saved(
                self._strm_suspects, self._migrate_strm_suspects(saved_suspects),
                "verified_at")
            # 载入即清洗历史脏数据（非视频 / 已忽略 / 源端已删 / 映射取消验证）。
            # 放在这里而不是只在写入时过滤：写入过滤拦不住升级前已落盘的坏条目，
            # 用户会看到一堆永远处理不掉的东西，只能手工改数据文件。
            self._prune_invalid_strm_suspects()
        saved_gen = self.get_data("strm_gen_requested") or {}
        if isinstance(saved_gen, dict):
            self._strm_gen_requested = saved_gen
        # 观察清单同样要载入即清洗（非视频文件永远不会生成 strm）。
        # ⚠️ 必须放在 `_strm_gen_requested` 恢复**之后**：清洗会连带失效该文件的
        # 补生成标记，早于此处调用就只能清掉一个空的标记字典，旧标记会留下来，
        # 看板据此把新条目误标成「补生成后仍无」。
        self._prune_invalid_strm_watch()
        # 孤儿补生成标记：两个清单里都没有的 key 却还留着「请求过生成」的记录。
        # ⚠️ 必须排在**两个清单的清洗之后** —— 先跑的话，那些本轮才被判为无效、
        # 正准备摘掉的条目，其标记此刻还「有主」，会被漏掉。
        self._prune_orphan_gen_markers()
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
            pair_summary = ", ".join(
                f"{(p.get('name') or p.get('src') or '?')}=>{(p.get('dest') or '?')}"
                for p in self._sync_pairs
            ) or "（无）"
            logger.info(
                f"[Rsync115Sync] v{self.plugin_version} 初始化完成 | "
                f"启用={self._enabled} 监听入库={self._listen_transfer} | "
                f"冷却={self._delay_hours}h 定时={self._cron} | "
                f"源端扫描={'cron ' + self._source_scan_cron if self._source_scan_enabled else '关'} | "
                f"映射 {len(self._sync_pairs)} 组: {pair_summary} | "
                f"队列: 冷却 {len(self._pending_queue)} / 补传 {len(self._backfill_queue)} | "
                f"限流={'开' if self._rate_limit_enabled else '关'}"
                f"({self._upload_batch_size}/批, {self._upload_max_per_window}/窗口)"
            )
            # 单独一行报告「认领钩子是否真的声明出去了」。
            # 为什么要专门报这个：2026-09-22 真机排查了三轮（Content-Type 400、
            # 尾斜杠 307、映射配置）才定位到真因 —— 插件实现了 webhook_parser
            # 却没在 get_module() 里声明，于是**宿主的模块调度器根本看不到本插件**
            # （宿主会打「请求插件 X 执行：webhook_parser」而那条日志从不出现，
            # 但没人会平白无故去核对一条**不存在**的日志）。这类失效不报错、
            # 无堆栈、grep 方法名还命中，只能靠一条明确的正面日志来自证。
            # 同时它还能立刻暴露「NAS 上的插件不是最新版」这种部署问题 ——
            # 启动摘要里的版本号与这行是否出现，两者一对就能判断。
            try:
                declared = self.get_module() or {}
            except Exception:
                declared = {}
            if "webhook_parser" in declared:
                logger.info("[Rsync115Sync] 认领钩子已注册（webhook_parser 已向宿主声明）："
                            "source=rsync115sync 的平台 webhook 报文会被本插件接管。"
                            "若此后再看不到任何 webhook 日志，请按 USAGE 的「到达=0 排查清单」逐项检查")
            else:
                logger.error("[Rsync115Sync] 认领钩子**未注册** —— get_module() 没有声明 "
                             "webhook_parser，宿主的模块调度器看不到本插件，"
                             "source=rsync115sync 的报文将完全无响应且无任何日志。"
                             "这通常意味着你跑的不是最新版插件（见 DEVELOPMENT §9.17）")
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

        # ⚠️ 补生成标记必须一起清：它是**第三个**要跟着忽略走的字典。
        # 用户实测数据里出现过「strm_suspects 为空、但 strm_gen_requested 里
        # 还留着一条已被忽略的文件」—— 只因当初先请求了补生成、后加的忽略规则。
        # 那条残留没有任何东西会去清理它（它既不显示、也不参与判定），
        # 会一直躺在数据文件里；而一旦该文件再次进入观察，看板就会凭它显示
        # 「补生成后仍无」，把一个已被用户明确忽略的文件报成一次生成失败。
        # 三个字典一起清才是完整语义 —— 漏掉任何一个都会留下一份幽灵状态。
        # Invalidate the regenerate markers too: it is the third dict that must follow
        # an ignore, and a leftover marker makes a brand-new observation render as
        # "asked the helper and it still failed".
        for key in list(self._strm_gen_requested.keys()):
            if _ignore_is_ignored(key, self._ignored_rules):
                self._strm_gen_requested.pop(key, None)
        self.save_data("strm_gen_requested", self._strm_gen_requested)
        # 清单可能因此清空，重置通知闩锁（与 _strm_arm_watch 同一收尾逻辑）
        self._reset_strm_notified_if_clear()
        return True

    def _remove_ignore_rule(self, index_or_rule: Any) -> bool:
        """移除指定忽略规则（按序号或规则文本）。"""
        if not _ignore_remove_rule(self._ignored_rules, index_or_rule):
            return False
        self.save_data("ignored_files", self._ignored_rules)
        return True

    # ================= 入库入口一览（改动前必读） =================
    #
    # 本插件现有**两条**入库来源，两者的分工必须保持清晰：
    #
    #   ① 源端游标扫描（主通道，`_scan_source_cursor`）—— **完整性的唯一承担者**。
    #      按文件 mtime 与持久化游标比对，覆盖整理入库、手动入库、外部搬入、
    #      以及插件不可用期间发生的一切。它不依赖宿主事件，因此没有「事件丢失」
    #      这个失效模式。定时 service 驱动，默认 30 分钟一轮。
    #
    #   ② Webhook（`on_webhook_message`，本文件下方）—— 「9KG 专属通道 + 加速器」。
    #      它让文件**早一点**进队列，但**不承担完整性**：即使它整条失效，
    #      主通道仍会在下一轮扫描时把同一个文件捞回来（去重由队列幂等保证）。
    #
    # ⚠️ 历史上这里还有第三条：订阅宿主的整理完成事件
    # （`TransferComplete` / `SubtitleTransferComplete` / `AudioTransferComplete`）。
    # **已于 2026-09-25 整条删除**，理由见本文件顶部「已删除」注释块与
    # DEVELOPMENT §4.0f。删除它没有替代损失：上述四种事件覆盖不到的场景，
    # 主通道本来就覆盖；而主通道覆盖不了的场景（事件永久丢失），它也覆盖不了。
    #
    # ⚠️ 下方 `on_webhook_message` 的装饰器**删掉不会有任何报错**：
    # 表现为「发送端明明推了，手动放进媒体库的文件却要靠扫描才补上」，
    # 日志里连一条 webhook 记录都没有。改动本文件时务必保留。
    #
    # 与整理事件的关键差异（照抄代码前必读）：
    #   · TransferComplete **在** _SNAPSHOT_EVENTS 内 → 走 event.snapshot() 拿类型化快照
    #   · WebhookMessage **不在** _SNAPSHOT_EVENTS 内（只登记了 payload 模型）→
    #     快照拿不到 payload，必须直接读 event_data 的属性（repo 内 watchsync 同写法）
    # 这条差异是实测源码结论（app/runtime/event/contracts.py），不是推测。
    @eventmanager.register(EventType.WebhookMessage)
    def on_webhook_message(self, event: Event):
        """
        事件入口：仅做异常兜底，业务逻辑见 _handle_webhook_event。

        Entry point for host-delivered webhooks (Emby today; any module that ships a
        webhook_parser tomorrow). Guarded so a malformed payload can never be
        recorded as a host-level plugin error.
        """
        try:
            self._handle_webhook_event(event)
        except Exception as err:
            logger.error(f"[Rsync115Sync] v{self.plugin_version} 处理 webhook 事件时异常"
                         f"（已兜底，不影响其它事件）: {err}")
            logger.debug(f"[Rsync115Sync] webhook 事件异常堆栈:\n{traceback.format_exc()}")

    def _enqueue_ingest_paths(self, raw_paths: List[str], source: str,
                              event_desc: str, from_scan: bool = False) -> Dict[str, int]:
        """
        把一组**候选入库路径**校验后放入冷却队列 —— 全部入库来源的合流点。

        Validate candidate ingest paths and put the survivors into the cool-down
        queue. Every ingest source (source-root cursor scan, webhook) goes through
        this single funnel, so they can never drift apart.

        为什么必须合流：各来源的**归一化与安全判据完全不同**（路径来源可信度、
        是否可能收到伪造数据），但**入队语义必须只有一个** —— 重复投递保留原时间戳、
        扩展名与映射归属先于存在性判断。若各写一份，「扫描入队的文件」与
        「webhook 入队的文件」迟早出现行为差异。

        ⚠️ 判据顺序：**先判映射归属，再判文件是否存在**。反过来的话，
        「不在任何映射内」这个计数永远为 0，日志就分不清「路径与你配置的源目录
        不一致」（改配置）与「路径对但容器里读不到」（挂载问题）。

        :param source: 日志里的来源标签（如 `Webhook`、`源端扫描`）。
        :param from_scan: 本批候选是否来自**源端扫描**。只影响「取不到 mtime 时」
            的兜底方向（详见 `_cooldown_basis`），默认 False（webhook 路径）。
        :return: 各原因计数（added/duplicate/skipped/unmatched/missing/expanded）；
            `skipped_ext` 单独记录**被扩展名白名单挡下**的扩展名分布，
            用于看板定位「哪个类型正在被静默丢弃」。
        """
        # 来源标签可能在左侧（"Webhook 监听到 N 个"）或完全没有（整理事件）。
        # 统一在这里拼一次，避免每个分支都要判断有没有来源。
        who = f"{source} " if source else ""
        counts = {"added": 0, "duplicate": 0, "skipped": 0, "unmatched": 0,
                  "missing": 0, "expanded": 0}
        added_paths: List[str] = []
        unmatched_paths: List[str] = []
        missing_paths: List[str] = []
        # 被扩展名闸门挡下的扩展名 → 次数。**必须按扩展名分桶**，不能只给一个
        # 总数：一个总数回答不了「丢的是什么」，而排查时唯一有用的信息就是扩展名。
        # 2026-09-25 那次「音频全丢」正是这样潜伏了多个版本 —— 判定只记 debug，
        # 看板上零痕迹，直到逐行读代码才发现。
        skipped_ext: Dict[str, int] = {}
        now_ts = time.time()

        for file_path in raw_paths or []:
            if not file_path:
                counts["skipped"] += 1
                continue

            own_pair = _pair_for_path(file_path, self._sync_pairs)
            if own_pair is None:
                counts["unmatched"] += 1
                unmatched_paths.append(file_path)
                continue

            src_root = (own_pair.get("src") or "").strip().rstrip("/")
            pair_name = _pair_name(own_pair)

            if not os.path.exists(file_path):
                counts["missing"] += 1
                missing_paths.append(file_path)
                continue

            # 目录展开（webhook 专属前置步骤，见 _expand_ingest_path）。
            # ⚠️ 必须在扩展名过滤**之前**：目录名没有扩展名，直接进白名单会被判
            # skipped —— 而发送端最自然的「通知入库」就是推一个目录（下完一部电影
            # 或一季的文件夹）。那曾表现为 success=True、0 入队、队列为空，
            # 发送端与用户都以为成功了。展开成文件后走下面同一套判据，不额外放行
            # 任何东西（非媒体文件照样被扩展名过滤掉）。
            expanded = self._expand_ingest_path(file_path)
            if expanded is None:
                # 普通文件：先看是否为 all_ext 映射的「同目录兜底」。
                # `is None` 表示不属于 all_ext，退回单文件判据 —— 与下面目录
                # 分支同一条理由：空列表/None 都是合法结果，不能靠真值判断。
                siblings = self._collect_sibling_files(file_path, own_pair)
                if siblings is None:
                    sub = self._enqueue_one_path(
                        file_path, own_pair, src_root, pair_name, now_ts, counts,
                        skipped_ext, from_scan)
                    if sub:
                        added_paths.append(sub)
                    continue
                counts["expanded"] += 1
                for mate in siblings:
                    sub = self._enqueue_one_path(
                        mate, own_pair, src_root, pair_name, now_ts, counts,
                        skipped_ext, from_scan)
                    if sub:
                        added_paths.append(sub)
                continue

            # 目录：把展开出的文件按同一套判据逐个入队。
            # ⚠️ 判据是 `is None`，**不是**真值判断 —— 空列表是「目录存在但无可用
            # 文件」这一合法结果，用 `if expanded:` 会让它掉进下面的单文件分支，
            # 于是目录被当成文件去做扩展名校验，最终表现为「目录被静默吞掉」
            # 这个函数本来要修的那个 bug（自己踩过一次，故留此注释）。
            counts["expanded"] += 1
            for child in expanded:
                sub = self._enqueue_one_path(
                    child, own_pair, src_root, pair_name, now_ts, counts,
                    skipped_ext, from_scan)
                if sub:
                    added_paths.append(sub)

        counts["skipped_by_ext"] = skipped_ext
        self._note_ingest_skips(skipped_ext)

        # 看板/日志用：本批是否有目录被展开（不改变入队总数，故单独计数）
        if counts["added"] > 0:
            self.save_data("pending_queue", self._pending_queue)
            dup_note = f"，其中 {counts['duplicate']} 个已在队列中" if counts["duplicate"] else ""
            exp_note = (f"，含 {counts['expanded']} 个目录已展开为 {counts['added']} 个文件"
                        if counts["expanded"] else "")
            logger.info(f"[Rsync115Sync] v{self.plugin_version} {who}监听到 "
                        f"{counts['added']} 个新入库文件（{event_desc}{dup_note}{exp_note}）"
                        f"，已加入 {self._delay_hours}h 延迟冷却队列: "
                        f"{_brief_paths(added_paths)}")
        elif counts["duplicate"]:
            # 重复投递不是问题（幂等已处理），但值得留痕，否则会误判成「没监听」
            logger.info(f"[Rsync115Sync] v{self.plugin_version} {who}"
                        f"{counts['duplicate']} 个文件已在冷却队列中，未刷新其冷却计时"
                        f"（{event_desc}，队列共 {len(self._pending_queue)} 条）")
        elif counts["expanded"]:
            # 展开过目录却一个文件都没进来：目录存在但没有可同步的媒体文件，
            # 或全在忽略清单里。**必须留 info** —— 否则「推了个目录、什么也没发生」
            # 与「推了个不存在的路径」在日志上没有区别。
            logger.info(f"[Rsync115Sync] v{self.plugin_version} {who}目录已展开但无文件入队"
                        f"（{event_desc}，目录 {counts['expanded']} 个；"
                        f"可能目录内无媒体文件、扩展名未包含，或全在忽略清单中）")
        elif missing_paths and not unmatched_paths:
            # 归属映射明确、但容器内读不到 —— 最值得警惕的一类（挂载不一致）
            logger.info(f"[Rsync115Sync] v{self.plugin_version} {who}路径在本容器内不可见"
                        f"（{event_desc}，共 {len(missing_paths)} 个；"
                        f"路径前缀与映射一致但读不到，请检查宿主机目录是否已映射进容器）: "
                        f"{_brief_paths(missing_paths)}")
        elif unmatched_paths:
            mapping_desc = ", ".join((p.get("src") or "?") for p in self._sync_pairs) or "（尚未配置任何映射）"
            logger.info(f"[Rsync115Sync] v{self.plugin_version} {who}路径不在任何映射内"
                        f"（{event_desc}，共 {len(unmatched_paths)} 个）: "
                        f"{_brief_paths(unmatched_paths)}；当前映射的源目录: {mapping_desc}")
        else:
            logger.debug(f"[Rsync115Sync] v{self.plugin_version} {who}未入队"
                         f"（{event_desc}，空路径/扩展名被过滤 {counts['skipped']} 个）")
        return counts

    # ---- 目录展开：webhook 发送端最自然的「通知入库」是推一个目录 ----

    # 目录展开的上限。一个 Webhook 报文能带进来的文件数必须有界：发送端若是
    # 「推整个 9KG 根目录」，无上限展开会让一次请求把冷却队列灌进上万个条目
    # （115 侧随之而来的是风控配额被瞬间打满）。超出部分**不静默截断** ——
    # 计数进 truncated，日志里明说少了多少，用户才知道该改成推子目录。
    DIR_EXPAND_LIMIT = 500

    # `all_ext` 映射下单目录同级文件的展开上限（见 _collect_sibling_files）。
    # 与 DIR_EXPAND_LIMIT 同量级但更小：这条路兜的是「一部电影一个目录」，
    # 正常几到几十个文件；几百个说明用户把整库塞进了同一个目录，
    # 那种情况下应该推目录而不是推文件。
    SIBLING_EXPAND_LIMIT = 300

    def _expand_ingest_path(self, file_path: str) -> Optional[List[str]]:
        """
        把候选路径按「目录 / 普通文件」分流。

        :return: `None`  = 这是**普通文件**，调用方按单文件判据处理；
                 `[...]` = 这是**目录**，元素是展开出的文件（空列表表示目录里没有
                 可同步的文件）。

        ⚠️ 返回值用 `is None` 区分，**不要**用真值判断调用：空列表是「目录存在但
        无可用文件」这一合法结果，把它当成「普通文件」会让调用方拿目录去做扩展名
        校验，最终回到「目录被静默吞掉」这个函数本来要修的问题上。

        为什么要按扩展名白名单**就地剪枝**而不是展开后再过滤：
        `os.walk` 一个 9KG 根目录会遍历其中每个目录项，而绝大多数是无关文件。
        用同一份扩展名表剪枝后，遍历量与真正要同步的文件数同阶，
        且语义与后面的过滤完全一致（不会出现「展开时放行、入队时又被拒」的分歧）。

        **目录必须展开**：目录名没有扩展名，直接进扩展名白名单必然被判 skipped ——
        而发送端最自然的「通知入库」就是推一个目录。那曾表现为
        `success=True`、入队 0 个、队列为空，发送端和用户都以为成功了。
        """
        try:
            if not os.path.isdir(file_path):
                return None
        except Exception:
            return None

        # 目录本身不需要扩展名校验；展开出的文件逐个交给调用方走同一套判据。
        # 复用 paths.valid_exts_of —— 与同步/搜索/补齐扫描**同一份口径**，
        # all_ext 映射返回 None 表示不过滤。自己再解析一次字段迟早会漂移。
        pair = _pair_for_path(file_path, self._sync_pairs) or {}
        wanted = _valid_exts_of(self._media_extensions, pair.get("all_ext", False))
        # 同样复用排除目录口径（@eaDir / #recycle 等），避免走进用户明确排除的目录 ——
        # 那既是性能问题，也会把排除目录里的文件错误入队。
        # getattr 兜底：本方法在 webhook 链路上被调用，而 `__new__` 构造的实例
        # （单测）或跨版本的旧数据文件可能没有该属性 —— 缺属性时不该让整条入库链路崩掉。
        excluded_dirs = _excluded_dir_names(
            getattr(self, "_exclude_patterns", self.DEFAULT_EXCLUDE_PATTERNS))

        found: List[str] = []
        truncated = False
        try:
            for root, dirnames, filenames in os.walk(file_path):
                dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
                for name in sorted(filenames):
                    if wanted is not None:
                        ext = os.path.splitext(name)[-1].lstrip(".").lower()
                        if ext not in wanted:
                            continue
                    found.append(os.path.join(root, name))
                    if len(found) >= self.DIR_EXPAND_LIMIT:
                        truncated = True
                        break
                if truncated:
                    break
        except Exception as err:
            logger.debug(f"[Rsync115Sync] 展开目录失败（按空目录处理）: {file_path} — {err}")
            return []

        if truncated:
            logger.warning(f"[Rsync115Sync] 目录 {file_path} 内可同步文件超过 "
                           f"{self.DIR_EXPAND_LIMIT} 个上限，本次只处理前 "
                           f"{self.DIR_EXPAND_LIMIT} 个；建议改为推送具体子目录，"
                           f"否则一轮同步会同时上传过多文件。")
        # 排序保证同一目录多次推送的入队顺序稳定（便于对照日志与队列）
        return sorted(found)

    def _collect_sibling_files(self, file_path: str, pair: Dict[str, Any]) -> Optional[List[str]]:
        """
        `all_ext` 映射的兜底：把**同一目录**下的其它文件一并纳入本次入队。

        Sibling expansion for `all_ext` pairs: when a single file is announced,
        every other file in the **same directory** is enqueued with it.

        为什么必须有这一步（2026-09-22 真机反馈）：
        「9KG 下配置的是所有文件都上传，在 webhook 入库后，进行上传时，
        没有把媒体文件所在目录下其他文件一并上传」。原因是整条链路
        （扩展名白名单 → 冷却队列 → `--files-from`）**以文件为粒度**，
        发送端推来一个文件路径时，同目录的其它文件永远拿不到冷却资格 ——
        于是永远不上传。而 `all_ext` 配置项的字面含义正是「这个目录下的
        文件全都要上传」，用户不会预期「只有被点到名的那一个」。

        为什么只在 `all_ext` 下生效：默认映射的上传范围是**扩展名白名单**，
        顺手扩大范围等于绕过用户「只同步视频+字幕」的配置意图，每次入库都
        静默多传文件、多耗 115 风控配额。

        为什么只取一层（不递归子目录）：本方法兜的是「一部电影被放在一个
        目录里」这个真实入库形态。递归会把 `Season 01/` 之类的层级一次性拉进来，
        而那是「推目录」这条路的语义（见 `_expand_ingest_path`）—— 两条路的
        边界必须清晰，否则一次通知能膨胀成整季甚至整库。
        `sibling_files` 里每一项都是**绝对路径**，且**不保证**在映射内或存在：
        children 仍逐个走 `_enqueue_one_path` 的同一套判据（扩展名 / 忽略清单 /
        幂等 / 待补扫升级），本方法不额外放行任何东西。

        :return: `None` = 不属于 `all_ext` 映射（或不是普通文件），调用方只处理
                 被点到名的那个文件；`[...]` = 该目录下参与本轮判定的文件
                 （**含** `file_path` 自身，便于调用方原样遍历）。
        """
        if not (pair or {}).get("all_ext", False):
            return None
        try:
            if not os.path.isfile(file_path):
                return None
        except OSError:
            return None

        parent = os.path.dirname(file_path)
        try:
            names = sorted(os.listdir(parent))
        except OSError as err:
            # 列不了目录（权限/竞态）不该让整条入库链路崩掉：退化成单文件入队，
            # 被点到名的那个文件仍然会入队。
            logger.debug(f"[Rsync115Sync] all_ext 同目录展开失败（按单文件处理）: "
                         f"{parent} — {err}")
            return None

        # 排除目录口径与遍历层一致（补传前置扫描用同一份 patterns），
        # 否则同一个目录在两条路上结果不同，用户无法解释。
        excluded_dirs = _excluded_dir_names(
            getattr(self, "_exclude_patterns", self.DEFAULT_EXCLUDE_PATTERNS))
        # 上限**含被点到名的文件本身**：先给它留一个位置，再枚举同级文件。
        # 若反过来（先枚举到满、最后硬塞进去），总量会变成 LIMIT+1 ——
        # 上限就成了「大约」，而这类上限一旦是「大约」就等于没有。
        room = max(0, self.SIBLING_EXPAND_LIMIT - 1)
        siblings: List[str] = []
        truncated = 0
        for name in names:
            full = os.path.join(parent, name)
            if full == file_path:
                continue
            try:
                if not os.path.isfile(full):
                    continue
            except OSError:
                continue
            if _is_junk_file_name(name):
                # 垃圾文件在白名单层也会被 `..*` 排除规则挡掉（rsync 的 --exclude
                # 在本插件是**无条件**追加的），此处提前剪掉既省一次判定，
                # 也让计数不虚高。
                continue
            if name in excluded_dirs:
                continue
            if len(siblings) >= room:
                truncated += 1
                continue
            siblings.append(full)

        if truncated:
            # 截断必须留痕：静默少入队会让用户以为文件已在排队，实际永远轮不到
            logger.warning(f"[Rsync115Sync] all_ext 目录 {parent} 内文件超过 "
                           f"{self.SIBLING_EXPAND_LIMIT} 个上限，"
                           f"{truncated} 个未纳入本批；建议把该类目录拆分为子目录，"
                           f"或改用「推送目录」方式通知（两种方式语义相同）")
        # 被点到名的文件**一定**在结果里：它是发送端唯一的明确意图，
        # 无论它叫 `._x` 还是恰好排在上限之外，都不能被兜底逻辑挤掉。
        siblings.insert(0, file_path)
        return siblings

    def _enqueue_one_path(self, file_path: str, own_pair: Dict[str, Any], src_root: str,
                          pair_name: str, now_ts: float, counts: Dict[str, int],
                          skipped_ext: Optional[Dict[str, int]] = None,
                          from_scan: bool = False) -> str:
        """
        对**单个文件**做完整入队判定，返回入队的相对路径（未入队返回空串）。

        从 `_enqueue_ingest_paths` 的循环体里抽出来，使「直接推文件」与
        「推目录、展开成文件」走**完全同一套**判据（扩展名 / 忽略清单 / 幂等）。
        分开写迟早出现两条路径的行为漂移。

        :param skipped_ext: 被扩展名闸门挡下时的分桶累加器（扩展名 → 次数）。
            传 None 表示调用方不需要这个维度（单测直调常见）。
        :param from_scan: 候选是否来自源端扫描。它只影响「取不到 mtime 时」的兜底
            方向（见 `_cooldown_basis`），默认 False = 信任发现时刻（webhook 路径）。
        """
        if not _wh_valid_extension(own_pair, file_path, self._media_extensions):
            counts["skipped"] += 1
            if skipped_ext is not None:
                # 按扩展名分桶 + 留一条 **info** 级日志。
                # 这里原先只 `counts["skipped"] += 1`，而汇总日志把 skipped
                # 写在 debug 级 —— 于是「某一类文件全都被丢弃」在日志与看板上
                # 都不留任何痕迹（2026-09-25 之前音频就是这样全丢的）。
                # 只对**未知扩展名**打 info 且每条扩展名只打一次（由桶判定），
                # 避免大批量入库时刷屏。
                raw_ext = _ext_of(file_path)
                bucket = raw_ext or "(无扩展名)"
                first_time = skipped_ext.get(bucket, 0) == 0
                skipped_ext[bucket] = skipped_ext.get(bucket, 0) + 1
                if first_time:
                    shown = f".{raw_ext}" if raw_ext else "无扩展名"
                    logger.info(f"[Rsync115Sync] ⏭ 扩展名未纳入同步白名单，跳过（{shown}）："
                                f"{file_path}；如需同步请在配置页「同步的扩展名」中加入该扩展名")
            return ""

        rel_path = os.path.relpath(file_path, src_root)
        queue_key = f"{pair_name}:{rel_path}"
        if self._is_ignored(queue_key):
            # 忽略清单优先级最高：否则被忽略的文件会从 webhook 这条新路
            # 重新进队，表现为「明明忽略了却还在同步」。
            counts["skipped"] += 1
            return ""
        # 幂等：已在队列中的条目保留原冷却基准，不刷新计时。
        # durable outbox 是 at-least-once，webhook 发送端也常带重试，源端扫描更是
        # 每轮都会重新看到同一批文件；无条件覆盖会让「1 小时前入库的文件」永远
        # 走不完冷却 —— 表现为「队列一直有东西、却永远没有就绪的」。
        # Idempotent: an entry already queued keeps its original cool-down basis.
        if queue_key in self._pending_queue:
            counts["duplicate"] += 1
            return ""

        self._pending_queue[queue_key] = self._cooldown_basis(file_path, now_ts, from_scan)
        counts["added"] += 1
        return rel_path

    def _cooldown_basis(self, file_path: str, discovered_ts: float,
                        from_scan: bool) -> float:
        """
        计算一个队列条目的**冷却基准时刻** —— 本插件冷却判据的唯一入口。

        Compute the cool-down basis timestamp for a queue entry. This is the single
        entry point of the cool-down predicate.

        规则 / rule:

            基准 = min(发现时刻, mtime)        到期 = 基准 + delay_hours

        它同时解决**两件方向相反**的事，这是取 min 而不是二选一的原因：

        | 场景 | mtime 相对发现时刻 | 基准取谁 | 效果 |
        |---|---|---|---|
        | 插件重载期间错过的文件 | 更旧 | **mtime** | 立即到期 → 下一轮就补传 |
        | 刚落地 / 正在写入的文件 | 更新或相等 | **发现时刻** | 等满冷却 → 不传半截文件 |
        | 未来时间戳（工具写错） | 更新 | **发现时刻** | 夹紧，不会"立刻到期" |

        第二行覆盖了源端扫描最危险的那个场景：**扫描没有"文件写完了"这个信号**
        （事件方案有，宿主只在整理完成后才广播），它唯一看得见的是 mtime，而
        正在写入的文件 mtime 恰好是最新的。用 min + 足够长的冷却期，等价于
        「等这个文件写完」，同时保留「等外挂字幕到齐」这个原始职责。

        ## 关于 `cp -p` / `rsync -a` 保留旧时间戳（**实测结论，别照抄想当然的说法**）

        本方法**不**为这类文件提供保护，而且**不需要** —— 实测（2026-09-25，
        `cp -p` 一个 200MB 文件，50ms 采样目标端 mtime）：

            写入阶段   mtime ≈ 当前时间      ← 此时 min 取"发现时刻" → 照常冷却
            写完那一刻 mtime = 源端老时间戳  ← 此时 min 取"老 mtime" → 立即上传

        `cp -p` / `rsync -a` 都在**内容写完之后**才设置 mtime，所以「看见老 mtime」
        本身就意味着「这个文件已经拷完了」；而正在写的那些文件带的是当前时间，
        由 min 正常纳入冷却。这正是上面第二行。
        （`rsync` 更进一步：目标端是"临时名写完后 rename"，文件以最终 mtime
        原子出现，连"看到半截"的窗口都没有。）

        仍未覆盖的：某工具**原地写入**且从第一刻起就带着源端老时间戳（既不 rename、
        也不先写 now）。这类写入在实测里没有出现，真要根除需要"到期时比对 mtime
        是否仍等于发现时的快照"，代价是队列值与持久化结构都要改 —— 见 TODO。

        Measured: cp -p sets mtime only after the copy finishes, so an old mtime
        means the file is complete. The in-progress case carries "now" and is
        handled by min. Do not claim this function guards against cp -p.

        :param from_scan: 候选是否由**源端扫描**发现。它只影响下面这一个分支 ——
            `getmtime` 抛错（NFS/CD2 抖动、权限）时的兜底方向：

              · **源端扫描**（from_scan=True）：候选是"mtime 落在窗口内"筛出来的，
                正常不会 stat 失败。真失败说明这个文件此刻读不到元数据 —— 当作
                "很久以前"立即就绪，让它在下一轮被重试，而不是白等一个冷却期。
              · **Webhook**（from_scan=False）：发送端主动点名了它，与 mtime 无关。
                取"发现时刻"按普通冷却排队 —— 这是保守方向（晚传不丢数据）。
        """
        try:
            mtime = os.path.getmtime(file_path)
        except OSError:
            return (discovered_ts - 10 ** 7) if from_scan else discovered_ts
        return min(discovered_ts, mtime)

    def _handle_webhook_event(self, event: Event):
        """
        处理宿主广播的 WebhookMessage：只认「入库类」事件 + 已启用的来源渠道。

        Handle a host-broadcast WebhookMessage. Only ingest-type events from an
        enabled channel are accepted; everything else returns immediately.

        两个必查项，缺一个都会产生静默的错误行为：

        1. **按 channel 过滤** —— 多个插件会同时订阅 WebhookMessage（仓库内
           watchsync / mediaservermsg 都订阅了），各插件必须只处理自己的来源。
           不滤的话，本插件会去处理别的媒体服务器推送的播放事件。
        2. **按事件名过滤（白名单）** —— 播放类事件同样携带 Item.Path。
           不过滤的后果是：**用户每看一集，那集就被重新入队并再上传一次**。
        """
        if not self._enabled:
            return
        # 开关语义：webhook 与整理事件都是「入库来源」，共用同一个 listen_transfer
        # 总闸。分成两个开关会让用户遇到「关了一个、另一个还在悄悄入队」。
        if not self._listen_transfer:
            return

        event_data = getattr(event, "event_data", None)
        if not event_data:
            return

        channel = _wh.channel_of(event_data)
        # 只处理**我们自己认领的**报文：认领时构造的 `WebhookEventInfo.channel`
        # 恒为 `WEBHOOK_TARGET`，所以这条判据等价于「本事件由本插件的
        # webhook_parser 认领而来」。
        #
        # 为什么不再按「来源渠道白名单」过滤（原先默认放行 `emby`）：
        # 本插件的入口只认显式发给自己的报文（`source=rsync115sync`），
        # 别的媒体服务器推来的入库事件由**平台自己的解析器**处理 ——
        # 用户的价值也不需要我们来兜（平台原生支持 `source=<实例名>`）。
        # 两边都不该管对方的事，一份渠道白名单只会带来两个副作用：
        #   · 默认只有 `emby`，用 Jellyfin 的用户的 B 路悄悄失效；
        #   · 别人推来的播放类事件要走到这里才被事件名白名单挡住，
        #     白白多一层误判面。
        # 改成「只认自己的认领结果」后，语义与入口判据完全一致，配置项也随之删除。
        # Only our own claims are handled: `channel` is set to WEBHOOK_TARGET when we
        # claim. Other senders belong to the platform's own parsers, so the old
        # channel allow-list was both redundant and a footgun (default `emby` only).
        if channel != self.WEBHOOK_TARGET:
            # 明确留痕（debug 级）：排查「事件到了没有」时，
            # 第一件要确认的就是 channel 到底是什么。
            logger.debug(f"[Rsync115Sync] webhook 事件不是本插件认领的，忽略"
                         f"（channel={channel or '空'}，只处理={self.WEBHOOK_TARGET}）")
            return

        event_name = str(_wh.read_field(event_data, "event", "") or "")
        server_name = str(_wh.read_field(event_data, "server_name", "") or "")
        shape = _wh.describe_payload(event_data)
        # 计数点放在**渠道过滤之后**：别的媒体服务器推的播放事件也会走到这里，
        # 把它们计进 received 会让看板上的数字虚高，用户以为 webhook 配得很成功。
        if not _wh.is_ingest_event(event_name):
            self._note_webhook(channel=channel, event=event_name, source=server_name,
                               shape=shape)
            logger.debug(f"[Rsync115Sync] webhook 非入库类事件，忽略（event={event_name or '空'}）")
            return

        raw_paths, path_source = _wh.extract_paths(event_data)
        if not raw_paths:
            # 拿不到路径 = 报文结构还没对齐。只记 debug，不刷 info：
            # 播放类噪声已经挡在前面了，这里能剩下的通常只是刮削更新之类。
            # 留结构摘要（`last_payload_shape`）：这是「字段名对不对得上」的最小线索，
            # 而完整报文的值形态属于开发期对齐字段用的信息，不进运行态。
            self._note_webhook(channel=channel, event=event_name, source=server_name,
                               shape=shape, unrecognized=True, action="未识别")
            logger.debug(f"[Rsync115Sync] webhook 未取到入库路径"
                         f"（event={event_name}，channel={channel}，报文结构={shape}）")
            return

        counts = self._enqueue_ingest_paths(
            raw_paths, source="Webhook(宿主)",
            event_desc=f"event={event_name}，channel={channel}，"
                       f"server={server_name or '未知'}，路径来源={path_source}")
        self._note_webhook(channel=channel, event=event_name, source=server_name,
                           shape=shape, ingested=counts.get("added", 0),
                           action="入队" if counts.get("added", 0) else "未入队")

    def _scan_source_cursor(self) -> int:
        """
        源端游标扫描：入库发现的**主通道**，也是完整性的唯一承担者。

        Source-root cursor scan — the primary ingest channel.

        判据与 `sync_to_115.sh` 同构：

            游标文件里记着每个映射「上次成功同步的时刻」
            → `os.walk` 源端，挑出 mtime 晚于（游标 - 重叠窗口）的文件
            → 交给 `_enqueue_ingest_paths` 走**与 webhook 完全相同**的入队判据
            → 只有真的入队成功才推进游标

        为什么它能做到「不漏」：它不依赖任何外部通知。整理入库、手动放进媒体库、
        外部工具搬入、MoviePilot 之外的下载完成，乃至插件重载/重启期间发生的一切，
        只要文件在映射的源目录里，mtime 就会被下次扫描看见。
        它取代了宿主的整理完成事件订阅 —— 后者有四个静默失效点（见文件头注释），
        且 durable outbox 不重放。

        为什么它能做到「不多传」：
          1. 已入队的 key 不重复入队（`_pending_queue` 幂等）；
          2. 已就绪的文件由 rsync `--size-only` 判为无需传输，是空操作；
          3. 老文件被 touch（刮削写 nfo、下载器续传、套件刷时间戳）只会让它
             重新落入重叠窗口，但冷却基准取 `min(发现时刻, mtime)`，不会因此变新;
          4. 游标只在**成功入队之后**推进 —— 失败的那一批下轮还会被看见。

        ⚠️ 与旧 `_scan_missed_ingest` 的三处关键差异（**不要退回旧写法**）：

        | | 旧实现 | 本实现 |
        |---|---|---|
        | 判据 | 「mtime 晚于**上次扫描时间**」 | 「mtime 晚于**游标 - 重叠窗口**」 |
        | 入队去向 | `_missed_queue`（**无条件跳过冷却**） | `_pending_queue`（正常冷却） |
        | 游标推进 | **无条件**推进（入队失败也推） | 仅在成功入队后推进 |
        | 由谁驱动 | 挂在同步 cron 内部（会被补传饿死） | 独立 service，cron `*/30` |

        旧实现那三条的合成效果是：「扫描刚发现一个 10 秒前刚落地的文件 →
        判为『错过的』→ 不吃冷却 → 本轮上传」。而源端扫描**没有"文件写完了"
        这个信号**，正在写入的文件 mtime 恰恰是最新的 —— 那个组合会稳定地
        制造「传到一半源文件还在变」的中断，也就是 DEVELOPMENT §3.10 记录的
        云端残留。新实现把冷却入口还给扫描发现的文件，正是为了堵住它。

        成本：每轮**每映射一次** `os.walk`，纯本地目录遍历，不触碰 115 挂载点，
        因此零 115 API 请求、不触发风控。与补传前置扫描（`_api_backfill_scan`）
        的成本性质相同，只是节奏独立（默认 cron `*/30`）。

        :return: 本次新入队的文件数 / number of files newly enqueued
        """
        now_ts = time.time()
        total_added = 0
        for pair in self._sync_pairs:
            src_root = (pair.get("src") or "").strip().rstrip("/")
            pair_name = _pair_name(pair)
            if not src_root or not os.path.isdir(src_root):
                continue

            # 游标缺失 = 该映射第一次扫描：用「当日 0 点」作基线。
            # 与 shell 的 `--since` 缺省一致，好处是**今天已入库的存量天然被覆盖**
            # —— 不需要单独的「只记不入队」引导阶段（那会让今天入库的文件成为
            # 永久漏：既不在游标的历史里，也永远不会再"变新"）。
            # ⚠️ 不要改成"建立基线时只记不入队"：那正是上面说的永久漏。
            cursor = float(self._source_cursor.get(pair_name) or 0.0)
            if cursor <= 0.0:
                cursor = _today_start_ts()
                self._source_cursor[pair_name] = cursor
                logger.info(f"[Rsync115Sync] [{pair_name}] 首次源端扫描：基线取当日 0 点"
                            f"（{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(cursor))}）")

            # 重叠窗口：`os.path.getmtime` 的比较是严格大于，而多个文件在同一秒
            # 落盘很常见（整季批量拷贝、SMB 一次写入）。若某文件的 mtime 恰好
            # 等于游标，严格比较会让它**每次都落在窗口外、永久跳过**。
            # 往后退一个窗口后，最坏情况只是重复扫到已入队的文件 —— 那由队列
            # 幂等吸收，代价为零；而漏掉是永久损失。代价不对称，故取重叠。
            since = cursor - self._SOURCE_CURSOR_OVERLAP_SECS
            # getattr 兜底：本方法会被 service 直接调用，而 `__new__` 构造的实例
            # （单测）或跨版本的旧数据文件可能没有该属性 —— 缺属性时不该让
            # **整条发现通道**崩掉（那正是最难自查的一类失效）。与
            # `_expand_ingest_path` 同款处理。
            excluded_dirs = _excluded_dir_names(
                getattr(self, "_exclude_patterns", self.DEFAULT_EXCLUDE_PATTERNS))

            candidates: List[str] = []
            for dirpath, dirnames, filenames in os.walk(src_root):
                dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    try:
                        if os.path.getmtime(full) <= since:
                            continue
                    except OSError:
                        continue
                    candidates.append(full)

            if not candidates:
                # 没有任何候选也要推进游标：否则一个安静期很长的映射会让游标
                # 永远停在原地，下次一旦有新文件，窗口会往回退到很久以前，
                # 把期间所有 mtime 落在窗口内的文件一次性全捞进来。
                self._source_cursor[pair_name] = now_ts
                continue

            # 与 webhook 走**同一个入口**：扩展名闸门、忽略清单、幂等、
            # 目录展开、all_ext 同目录兜底全部共用，判据不可能漂移。
            counts = self._enqueue_ingest_paths(
                candidates, source="源端扫描", from_scan=True,
                event_desc=f"映射={pair_name}，游标={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(cursor))}"
                           f"，候选={len(candidates)}")
            added = int(counts.get("added", 0))
            total_added += added

            # ⚠️ 只在**成功入队之后**推进游标。若这里无条件推进（旧实现的写法），
            # 一次落盘失败或异常就会让整批候选永久丢失 —— 游标越过了它们，
            # 而它们从未进过队列，任何一轮同步都不会再取。
            # ⚠️ 推进到 now_ts 而不是"最大 mtime"：now_ts 是保守值，只会重复扫，
            # 不会跳过任何在扫描期间落地的文件。
            self._source_cursor[pair_name] = now_ts

        self._source_scan_last = now_ts
        self.save_data("source_cursor", self._source_cursor)
        self.save_data("source_scan_last", self._source_scan_last)
        if total_added:
            logger.info(f"[Rsync115Sync] 🔍 源端扫描：{total_added} 个新文件已入冷却队列"
                        f"（{self._delay_hours}h 后上传；映射 {len(self._sync_pairs)} 组）")
        else:
            logger.debug(f"[Rsync115Sync] 源端扫描完成：无新文件（映射 {len(self._sync_pairs)} 组）")
        return total_added


    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册**两个**定时服务：入库发现（扫描）与冷却就绪同步。

        Registers two services: ingest discovery (scan) and cool-down sync.

        ⚠️ 为什么必须是两个、不能合成一个：这两者的**节奏由不同因素决定**，
        合并会互相绑架。

          · **发现层的节奏**只该由「媒体多久出现一次」决定 —— 默认 30 分钟一轮，
            与上传无关。它很便宜（纯本地 os.walk，零 115 API），但**不是零成本**：
            大库下每轮要整树遍历一次，所以没必要扫得比"入库发生"更勤。
          · **传输层的节奏**由冷却时长与 cron 决定，还要与补传队列争批次与配额。

        合并到传输 cron 里的后果是实测过的：`_scheduled_sync` 第一件事是
        `if self._resume_backfill_if_pending(): return` —— 补传队列非空时整轮
        **只跑补传**，扫描一次都不跑。于是一个几千条的补传队列会给发现层断粮，
        而看板上完全看不出「扫描被跳过了」。
        Discovery must not be starved by the transfer layer's batch quota.
        """
        services = []

        # ① 入库发现（主通道）：固定间隔，不由用户 cron 控制
        if self._enabled and self._source_scan_enabled:
            try:
                services.append({
                    "id": "Rsync115Sync_SourceScan",
                    "name": "源端扫描入库（主通道）",
                    "trigger": CronTrigger.from_crontab(self._source_scan_cron),
                    "func": self._scan_source_cursor_safe,
                    "kwargs": {}
                })
            except Exception as e:
                logger.error(f"[Rsync115Sync] 源端扫描服务注册失败: {e}")

        # ② 冷却就绪同步 + 补传续跑（用户可配 cron）
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

    def _scan_source_cursor_safe(self) -> int:
        """
        源端扫描的 service 入口：异常兜底 + 运行态落盘。

        为什么要有这一层：扫描是**定时 service**，宿主把它丢到调度线程里跑；
        未捕获的异常会被记成「插件错误」，而这只是发现层的一次失败 ——
        下一轮（默认 30 分钟后）会重新扫到同一批文件（游标没推进），自愈。
        所以这里最该做的是**记日志并让本轮安静结束**，而不是抛出。
        """
        if not self._enabled or not self._source_scan_enabled:
            return 0
        try:
            return self._scan_source_cursor()
        except Exception as err:
            logger.error(f"[Rsync115Sync] 源端扫描异常（已兜底，下一轮会重扫同一批）: {err}")
            logger.debug(f"[Rsync115Sync] 源端扫描异常堆栈:\n{traceback.format_exc()}")
            return 0

    # ================= 胁持宿主模块方法（webhook_parser） =================

    def get_module(self) -> Dict[str, Any]:
        """
        声明本插件接管的宿主模块方法。

        ⚠️ **实现 `webhook_parser` 方法本身不会让宿主调用它** —— 宿主是从
        `get_module()` 返回的「方法名 → 方法」映射里收集 provider 的
        （`app/runtime/extensions/plugin/projection.py:92` 的 `modules()`：
        `declared = plugin.get_module()`，`None` 直接 `continue`）。
        基类默认实现返回 `None`，因此**漏写这个声明 = 认领通道整条静默失效**：
        宿主不会报错、`webhook_parser` 一行日志都不会有、`source=rsync115sync`
        的报文只会交给宿主自己的 Emby/Jellyfin/Plex 解析器（它们不认识这个
        source，于是返回 None），最终现象就是「平台收到请求、插件毫无反应」。

        这正是 2026-09-22 真机联调排查了 Content-Type 与尾斜杠两轮之后
        才发现的**真正原因** —— 前三轮所有排查都建立在「插件已被调用」这个
        错误前提上。教训：跨系统静默失效时，要先验证**链路是否真的接通**，
        再排查链路上的每一步；`tests/v3/rsync115sync/test_registration_contract.py`
        的 `test_webhook_parser_is_declared_in_get_module` 就是为此加的哨兵。

        Returns
        -------
        Dict[str, Any]
            模块方法名 → 绑定方法。当前只声明 `webhook_parser`。
        """
        return {
            "webhook_parser": self.webhook_parser,
        }

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

    # ================= 认领宿主 webhook 解析（必须实现，理由见下） =================
    #
    # ⚠️ 这不是可选优化，是**必须**实现的。宿主的 `webhook_parser` 是「模块方法」，
    # 其契约（app/runtime/extensions/module/contracts.py:1089）为：
    #     aggregation = FIRST_NON_EMPTY   # 取第一个非空结果
    #     plugin_short_circuit = True     # 非空即短路
    #     public_to_plugins = True        # 插件可实现
    # 而调度顺序是**插件优先、宿主殿后**（dispatcher.py:169）。两者相加的语义是：
    #
    #     任何启用的插件只要实现了 webhook_parser 并返回非空结果，
    #     宿主的 Emby / Jellyfin / Plex 解析器就**再也不会被调用**。
    #
    # （已用宿主自己的调度代码复现：插件返回非空 → 第二个 provider 的 call_mode
    #  变为 STOP、不被调用；见 DEVELOPMENT.md 9.11。）
    #
    # 所以不实现它等于赌「别的插件永远不实现这个钩子」。赌输的后果是：宿主的
    # WebhookEventInfo 根本不会被构造 → WebhookMessage 不广播 → 本插件一行日志都没有，
    # 现象与「Emby 回调没配好」完全一致，用户没有任何可自查的线索。
    #
    # ## ⚠️ 认领判据只认「显式收件人」，绝不按 channel 认领
    #
    # 曾经想按配置里的 `webhook_channels`（默认 emby）来认领 —— 那是个严重错误：
    # 宿主的 Emby 解析器产出的 `channel` **就是** `emby`
    # （`emby.py:1082` `WebhookEventInfo(event=..., channel="emby")`）。按它认领会把
    # 宿主本来能正常处理的 Emby 报文抢过来、短路掉宿主解析器，于是健康检查、图片
    # 获取等宿主功能一起失效 —— 而本插件只想要一个路径，代价完全不成比例。
    #
    # 现在的判据是**发送端必须显式声明收件人为本插件**，且只认一个明确的标识：
    #     `source=rsync115sync`（查询串）或 `x-webhook-target: rsync115sync`（请求头）
    # 宿主自己的解析器按 source 去查**新媒体服务器实例**，`rsync115sync` 不是实例名，
    # 因此它们只会返回 None 并继续往下走，不存在「抢错」的可能。
    #
    # 三条全部满足才认领，缺一条都返回 None：
    #   1. 显式收件人标识命中
    #   2. 插件本身已启用且监听入库事件
    #   3. 报文里确实含**本插件映射下的**路径（只凭自报标识就认领会吞掉别人报文）
    #
    # ## ⚠️ 签名与请求体形态
    #
    # 签名必须与宿主调用方式一致（`base.py:514` 以 body/form/args 三个关键词调用）。
    # 参数名不匹配时宿主**不会报错也不会告警**（兼容阶段只诊断不拒绝 provider），
    # 表现为「回调 200、插件收不到」，属最难查的一类。
    #
    # `/api/v1/webhook/` 的 body 是 **`await request.body()` 的原始 bytes**
    # （`app/api/endpoints/webhook.py`），不是解析好的 dict；`form` 拿到的是
    # `await request.form()`。因此这里把三种载体都试一遍：form → body → args。
    # （Emby 走 form、Jellyfin/TrimeMedia 走 body、Plex 走 form —— 各家不一。）
    #
    # ## ⚠️⚠️ 本函数之外还有一种「连这里都到不了」的失败（实测踩坑）
    #
    # 宿主端点在调用 provider 之前就先 `form = await request.form()`。若发送端用
    # `Content-Type: multipart/form-data` 却发**裸 JSON body**（没有 boundary ——
    # 很多 webhook 配置界面的「Content-Type 下拉框」会诱导用户这么选），starlette
    # 会直接抛 `400 Missing boundary in multipart`，请求在**进入本函数之前**就被拒。
    # 此时本插件一行日志都不会有，而宿主日志里只有一条 400、内容为空 ——
    # 用户看到的现象正是「MP 平台能看到请求，但看不到具体信息，插件也没日志」。
    # 这是**发送端配置问题**，插件无法在此函数里兜住（那个 400 发生在 provider 调度
    # 之前，SDK 也没有路由中间件钩子；曾写过一版路由级探测代码，因永远不可达而删除，
    # 详见 DEVELOPMENT §9.16）。能做的只有**可观测**：让这个失败在现象上与「到了但
    # 认领失败」区分开 —— 靠看板的「平台解析入口到达」计数（本函数之外的
    # `_note_webhook_claim_attempt`）始终为 0，即可判定请求没到插件，接着去查
    # Content-Type。
    WEBHOOK_TARGET = "rsync115sync"

    def webhook_parser(self, body: Any, form: Any, args: Any) -> Any:
        """
        认领**显式发给本插件**的 webhook 报文，其余一律 `None`（= 我不认领）。

        Claim webhook payloads explicitly addressed to this plugin. Returns None
        for everything else, so the host's own Emby/Jellyfin/Plex parsers keep
        working — returning a non-empty result here would short-circuit them.

        认领成功时返回宿主契约要求的 `WebhookEventInfo`（不是本插件自造的类型）：
        宿主会把它直接交给 eventmanager，类型不符或返回 `None` 都会让整条链静默结束。
        """
        try:
            if not getattr(self, "_enabled", False) or not getattr(self, "_listen_transfer", True):
                return None
            query = self._query_of(args)
            if not self._claims_for_us(form, body, query):
                # 没写着发给本插件 → 正常情况（宿主每条 Emby 报文都会走到这里）。
                # 只记 debug：这是**高频**路径，打 info 会刷屏。
                logger.debug("[Rsync115Sync] webhook 报文未声明发往本插件，不认领")
                return None
            # 从这里往下：报文**明确写着是给我们的**。到了这一步就不允许再「静默」了 ——
            # 用户已经按文档在发送端填了 source=rsync115sync，若最终什么都没发生，
            # 他手里必须有可自查的线索（这正是「看不到任何日志」那次的教训）。
            self._note_webhook_claim_attempt(body, form, query)
            raw_paths = self._paths_from_webhook_request(body, form, query)
            if not raw_paths:
                logger.info(f"[Rsync115Sync] webhook 报文声明发往本插件，但**取不到任何路径** ——"
                            f"请照下一条日志的报文样本核对字段名（发送端字段需出现在"
                            f" webhook.PATH_FIELD_CANDIDATES 或嵌套容器表内）。"
                            f"报文结构={_wh.describe_payload(self._webhook_body_of(body, form, query))}")
                return None
            # 判据 3：必须真能归属到本插件的某个映射。不满足说明这条报文不是给我们的
            # （或路径形态对不上），此时**认领了反而更糟** —— 既吞掉报文，又什么都做不成。
            own = [_pair_for_path(p, self._sync_pairs or []) for p in raw_paths]
            if not any(own):
                mapping_desc = ", ".join((p.get("src") or "?") for p in (self._sync_pairs or [])) \
                    or "（尚未配置任何映射）"
                logger.info(f"[Rsync115Sync] webhook 报文声明发往本插件，但取到的路径"
                            f"**不属于任何映射**，不认领（避免短路宿主解析器）: "
                            f"{_brief_paths(raw_paths)}；当前映射的源目录: {mapping_desc}")
                return None
            return _webhook_event_info_class()(
                event="library.new",
                channel=self.WEBHOOK_TARGET,
                server_name=self.WEBHOOK_TARGET,
                item_path=raw_paths[0],
                json_object={"paths": raw_paths},
            )
        except Exception as err:  # 认领判定异常绝不能影响宿主其它 provider
            logger.debug(f"[Rsync115Sync] webhook_parser 认领判定异常（已忽略）: {err}")
            return None

    def _webhook_body_of(self, body: Any, form: Any, query: Any) -> Any:
        """
        把三种载体合成一份「可摘要/可采样」的报文，供日志与看板展示。

        与 `_paths_from_webhook_request` 的区别：那个按优先级**取路径**，找到就返回；
        这个只为**展示**而合并全部载体 —— 发送端把 JSON 塞在 form 的 `data` 字段里时，
        只用 body 做摘要会得到空报文，用户照着看不出任何东西。
        """
        merged: Dict[str, Any] = {}
        if isinstance(query, dict):
            merged.update(query)
        for source in (form, body):
            if not source:
                continue
            if isinstance(source, (bytes, bytearray)):
                try:
                    source = bytes(source).decode("utf-8", "replace")
                except Exception:
                    continue
            if isinstance(source, str):
                text = source.strip()
                if not text:
                    continue
                try:
                    import json
                    parsed = json.loads(text)
                except Exception:
                    parsed = None
                if isinstance(parsed, dict):
                    merged.update(parsed)
                elif parsed is not None:
                    merged["_body"] = parsed
                else:
                    merged["_body"] = text
                continue
            try:
                merged.update(dict(source))
            except Exception:
                continue
        return merged

    def _note_webhook_claim_attempt(self, body: Any, form: Any, query: Any) -> None:
        """
        记下「一个声明发给本插件的报文到了」。

        与 `_handle_webhook_event` 里的计数分工：那里统计的是**宿主广播回来的事件**
        （只覆盖成功认领的那条路），这里统计的是**宿主解析入口收到的东西**。
        只有后者能区分「报文没到插件」与「到了但认领失败」—— 那次排查里两者
        观察到的现象完全一样（都没有日志），而修法完全不同。
        """
        stat = self._webhook_stat_now()
        stat["claimed"] = int(stat.get("claimed", 0)) + 1
        payload = self._webhook_body_of(body, form, query)
        stat["last_claimed_ts"] = time.time()
        stat["last_claimed_shape"] = _wh.describe_payload(payload)
        try:
            self.save_data("webhook_stat", stat)
        except Exception:
            pass
        # 记一条「平台解析入口到达」（不带报文值）。它是「请求到底有没有到插件」
        # 的唯一凭据 —— 与「收到事件」之差就是「到了却没认领」，那次排查缺的正是它。
        try:
            self._note_webhook(source="宿主解析入口", shape=stat["last_claimed_shape"],
                               action="已到达·待认领")
        except Exception:
            pass
        logger.debug(f"[Rsync115Sync] webhook 报文声明发往本插件，开始认领判定："
                     f"{stat['last_claimed_shape']}")

    # 收件人标识可出现的载体：查询串、请求头（form 与 body 里也一并找，兼容
    # 把标识写进 JSON 的发送端）。
    _WEBHOOK_TARGET_KEYS = ("source", "target", "channel", "x-webhook-target")

    @classmethod
    def _claims_for_us(cls, *sources: Any) -> bool:
        """判断任一载体里是否显式声明了「发给本插件」。"""
        for source in sources:
            for key, value in cls._iter_flat_items(source):
                if key in cls._WEBHOOK_TARGET_KEYS and str(value).strip().lower() == cls.WEBHOOK_TARGET:
                    return True
        return False

    @staticmethod
    def _iter_flat_items(source: Any):
        """把 dict / QueryParams / 原始 bytes / 字符串归一成 (key, value) 迭代。"""
        if not source:
            return
        if isinstance(source, (bytes, bytearray)):
            try:
                source = source.decode("utf-8", "ignore")
            except Exception:
                return
        if isinstance(source, str):
            text = source.strip()
            if not text:
                return
            if text.startswith("{"):
                try:
                    import json
                    source = json.loads(text)
                except Exception:
                    return
            else:
                try:
                    from urllib.parse import parse_qsl
                    yield from ((k.lower(), v) for k, v in parse_qsl(text))
                except Exception:
                    return
                return
        if isinstance(source, dict):
            yield from ((str(k).lower(), v) for k, v in source.items())
            return
        # QueryParams / Multidict / form 等：都支持 items()
        items = getattr(source, "items", None)
        if callable(items):
            try:
                yield from ((str(k).lower(), v) for k, v in items())
            except Exception:
                return

    @classmethod
    def _paths_from_webhook_request(cls, body: Any, form: Any, args: Any) -> List[str]:
        """按 form → body → args 的顺序取出候选入库路径（各家发送端载体不一）。"""
        import json

        for source in (form, body):
            candidate: Any = None
            if isinstance(source, (bytes, bytearray)):
                try:
                    source = bytes(source).decode("utf-8", "ignore")
                except Exception:
                    continue
            if isinstance(source, str):
                text = source.strip()
                if not text:
                    continue
                try:
                    candidate = json.loads(text)
                except Exception:
                    from urllib.parse import parse_qsl
                    candidate = dict(parse_qsl(text)) or None
            elif source:
                candidate = dict(source) if not isinstance(source, dict) else source
            if isinstance(candidate, dict) and candidate.get("data"):
                # Emby 把 JSON 塞在 form 的 `data` 字段里（见 emby.py 的解析实现）
                inner = candidate.get("data")
                if isinstance(inner, str):
                    try:
                        candidate = json.loads(inner)
                    except Exception:
                        pass
                elif isinstance(inner, dict):
                    candidate = inner
            if candidate:
                paths, _ = _wh.extract_paths(candidate)
                if paths:
                    return paths
        if args:
            paths, _ = _wh.extract_paths(dict(args))
            if paths:
                return paths
        return []

    @staticmethod
    def _query_of(args: Any) -> Dict[str, Any]:
        """把宿主传来的 args（QueryParams 或 dict）归一成 dict。"""
        if not args:
            return {}
        try:
            return {str(k): v for k, v in dict(args).items()}
        except Exception:
            return {}

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
            # 「立即运行一次」：先扫一次源端（不等扫描 cron），再跑一次就绪同步
            # （不等同步 cron）。**不绕过冷却** —— 见 _api_run_now 的说明。
            {"path": "/run_now", "endpoint": self._api_run_now, "methods": ["POST"], "auth": "bear"},
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
            # 用户确认「确实没传上去」→ 越过观察窗口直接转疑似（纯本地，零 115 API）。
            {"path": "/strm_confirm_failed", "endpoint": self._api_strm_confirm_failed,
             "methods": ["POST"], "auth": "bear"},
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

    # ================= Webhook 入库运行态 =================
    #
    # 现在只有一条通道：宿主的 `webhook_parser` 契约（认领确认发给本插件的报文）。
    # 自建匿名端点已于 2026-09-22 移除，原因见 DEVELOPMENT §9.18。

    def _note_ingest_skips(self, skipped_ext: Dict[str, int]) -> None:
        """
        把「被扩展名闸门挡下」的分布累加进运行态，供看板展示。

        Accumulate extensions blocked by the ingest gate so the dashboard can
        answer "which file types are being silently dropped".

        为什么值得专门做：闸门丢弃此前只写 debug 日志，而看板的四个计数里没有它
        —— 「某一类文件 100% 被丢弃」在界面上**完全没有痕迹**。这不是假设：
        音频曾因此全丢（用户的默认白名单里一个音频扩展名都没有），直到逐行
        读代码才发现。一条只增不清的分布就足以让这种情况在第一次发生时暴露。

        Why it matters: this exact blind spot let "100% of audio files dropped"
        survive multiple releases. A monotonically growing histogram is enough to
        make that visible the first time it happens.
        """
        if not skipped_ext:
            return
        stat = getattr(self, "_ingest_skip_stat", None)
        if not isinstance(stat, dict):
            stat = {}
            self._ingest_skip_stat = stat
        for ext, n in skipped_ext.items():
            stat[ext] = int(stat.get(ext, 0)) + int(n)
        try:
            self.save_data("ingest_skip_stat", stat)
        except Exception:
            # 统计落盘失败绝不能影响入库本身
            pass

    @staticmethod
    def _wh_stat() -> Dict[str, Any]:
        """
        新建一份 webhook 运行态模板。

        计数键清单只在这里出现一次：`init_plugin` 用它初始化、`_note_webhook` 用它
        兜底（`__new__` 构造的测试实例、或跨版本的旧数据文件都可能缺字段）。
        两处各写一份的话，新增一个计数键必然漏掉其中一处，表现为看板取键 KeyError。
        """
        return {
            "received": 0,          # 收到的 webhook 事件数（含被过滤的非入库类）
            "ingested": 0,          # 真正入队的文件数
            "rejected": 0,          # 被防护链或白名单拒绝的请求数
            "unrecognized": 0,      # 收到了但没解析出路径的次数
            "last_ts": 0.0,
            "last_channel": "",
            "last_event": "",
            "last_source": "",
            "last_payload_shape": "",
            # 注：曾有一份「最近报文样本（含值）」的环形缓冲。它随看板样本区一并
            # 移除 —— 样本的唯一消费者就是那块看板区域，留着只会让插件持续
            # 抓取并落盘完整报文体（截断脱敏后仍是用户数据），而没有任何人读它。
            # 排查仍靠 last_payload_shape（字段结构）与四个计数。
            # 平台 webhook 端点**正在返回非 200**：多为发送端 Content-Type 与
            # body 形态不匹配（如 multipart 却没有 boundary），请求在进入
            # webhook_parser 之前就被拒。详见 _log_webhook_route_failure。
            "route_failed": False,
            "route_status": 0,
            "route_warned_ts": 0.0,
            "route_last_ts": 0.0,
            # 宿主解析入口收到的「声明发往本插件」的报文数（认领成功与否都计）。
            # 与 received 的分工：received 记的是宿主**广播回来**的事件，
            # 只覆盖认领成功那条路；claimed 记的是入口到达量 ——
            # 只有它能区分「报文没到插件」与「到了但认领失败」。
            "claimed": 0,
            "last_claimed_ts": 0.0,
            "last_claimed_shape": "",
        }

    def _webhook_stat_now(self) -> Dict[str, Any]:
        """
        取运行态（缺失时按模板补全）—— 每个读写点都必须走它。

        为什么不能直接 `self._webhook_stat`：本插件的单测与部分宿主路径用
        `__new__` 构造实例（不跑 `__init__`），此时该属性不存在。为看板/统计这类
        旁路功能抛 AttributeError，会把「入库本身完全正常」的情况表现成异常，
        是本项目已记录过的一类缺陷（DEVELOPMENT.md 8.5：只有实例化才能暴露）。
        """
        stat = getattr(self, "_webhook_stat", None)
        if not isinstance(stat, dict):
            stat = self._wh_stat()
            self._webhook_stat = stat
        else:
            for key, default in self._wh_stat().items():
                stat.setdefault(key, default)
        return stat

    def _note_webhook(self, *, channel: str = "", event: str = "", source: str = "",
                      shape: str = "", ingested: int = 0, rejected: bool = False,
                      unrecognized: bool = False,
                      action: str = "") -> None:
        """
        记录一次 webhook 到达/入队/被拒，供看板与日志回答「这条路到底通不通」。

        为什么值得专门做一份运行态：webhook 是全插件唯一**由外部发起**的入口，
        出问题时用户手里没有任何可自查的证据 —— 发送端显示 200、插件日志一片
        安静、看板队列不增长。把「收到几条 / 入队几条 / 拒了几条 / 最后一次报文的
        字段结构」记下来，才能把问题定位到具体是哪一环。
        """
        stat = self._webhook_stat_now()
        stat["received"] = int(stat.get("received", 0)) + 1
        stat["ingested"] = int(stat.get("ingested", 0)) + max(0, int(ingested))
        if rejected:
            stat["rejected"] = int(stat.get("rejected", 0)) + 1
        if unrecognized:
            stat["unrecognized"] = int(stat.get("unrecognized", 0)) + 1
        stat["last_ts"] = time.time()
        if channel:
            stat["last_channel"] = channel
        if event:
            stat["last_event"] = event
        if source:
            stat["last_source"] = source
        if shape:
            stat["last_payload_shape"] = shape
        # 注：这里曾有「最近报文样本」的采集（含值、截断脱敏）。随看板样本区
        # 一并移除 —— 它的唯一消费者就是那块区域。保留采集等于让插件持续抓取
        # 并落盘完整报文体（再脱敏也仍是用户数据）而无人读取。
        try:
            self.save_data("webhook_stat", stat)
        except Exception:
            pass  # 运行态落盘失败绝不能影响入库本身

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
                "source_scan_enabled": self._source_scan_enabled,
                "source_scan_cron": self._source_scan_cron,
                # webhook（第二入库来源）：入口只认 `source=rsync115sync`，
                # 无可配置项。曾有的渠道白名单已随其移除（DEVELOPMENT §4.0a）。
                "strm_check_enabled": self._strm_check_enabled,
                "strm_grace_minutes": self._strm_grace_minutes,
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
        self._source_scan_enabled = bool(
            config.get("source_scan_enabled", self._SOURCE_SCAN_ENABLED_DEFAULT)
        )
        self._source_scan_cron = self._read_source_scan_cron(config)
        self._notify = config.get("notify", True)
        self._delay_hours = float(config.get("delay_hours", 4.0))
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
        self._strm_grace_minutes = self._read_grace_minutes(config)
        self._warn_on_legacy_grace_unit(config)
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



    # ================= 文件台账（SQLite） =================

    def _open_store(self) -> None:
        """
        打开台账并（首次）执行一次性迁移。任何异常都不阻断插件加载。

        Open the ledger and run the one-shot migration. Never blocks plugin load:
        a broken ledger is a degraded feature, not a failed startup.
        """
        try:
            data_path = self.get_data_path()
        except Exception as e:
            logger.warning(f"[Rsync115Sync] 无法获取插件数据目录，文件台账不可用（相关功能降级）: {e}")
            return
        try:
            self._ledger = _Store(data_path / "ledger.sqlite3")
        except Exception as e:
            logger.error(f"[Rsync115Sync] 文件台账打开失败（相关功能降级）: {e}")
            self._ledger = None
            return
        try:
            self._migrate_legacy_state_once()
        except Exception as e:
            logger.warning(f"[Rsync115Sync] 旧数据迁移失败（不影响运行，下次启动会重试）: {e}")
        self._bind_ledger_maps()

    def _bind_ledger_maps(self) -> None:
        """
        把四类「与文件有关的状态」换成台账替身（dict 接口不变，真相源变为 SQLite）。

        Replace the four file-related state dicts with ledger-backed mappings. The
        dict interface is preserved, so the ~175 existing read/write sites are
        untouched — the only switch point is here.

        ## 为什么这样切换（而不是逐个改读写点）

        四类状态合计约 175 处读写，散在 6 个文件里。逐个改写有两个问题：
          1. 任何一处漏改都是**静默的行为差异**（例如某个分支仍在读旧字典，
             表现为"看板上有时对有时不对"）；
          2. 改到一半时两套状态并存且不一致，不可回滚。
        替身类把差异限制在一个类里，可单独测试、可单独回退。

        ## 四类状态与各自的时间戳字段

        | 状态 | 旧字典 | 时间戳字段 | 值的形态 |
        |---|---|---|---|
        | candidate | `_pending_queue` | `enqueued_at` | 裸 float（入队时刻）|
        | pending_verify | `_strm_watch` | `enqueued_at` | 裸 float（同步成功时刻）|
        | suspect | `_strm_suspects` | `verified_at`（= 首次疑似时刻）| dict `{ts, origin, dest}` |
        | ignored | `_ignored_rules` | —— | **不替换**，见下 |

        ⚠️ 忽略清单**不换成替身**：它存的是**规则**（支持 `contains` 关键字匹配），
        不是"某个文件的状态" —— 台账的 key 是具体文件路径，装不下"某剧名"这种
        模式规则。它继续走 `save_data`，台账里那份只是迁移时留的快照。
        """
        if self._ledger is None:
            # 台账不可用：保持原有字典（功能不受影响，只是没有持久化台账）。
            # 这是刻意的降级 —— 台账故障不该让插件失去跟踪能力。
            return
        self._pending_queue = self._adopt_into_ledger(
            getattr(self, "_pending_queue", None),
            _store_mod.LedgerMapping(self._ledger, _store_mod.STATUS_CANDIDATE,
                                     ts_field="enqueued_at"))
        self._strm_watch = self._adopt_into_ledger(
            getattr(self, "_strm_watch", None),
            _store_mod.LedgerMapping(self._ledger, _store_mod.STATUS_PENDING_VERIFY,
                                     ts_field="enqueued_at"))
        self._strm_suspects = self._adopt_into_ledger(
            getattr(self, "_strm_suspects", None),
            _store_mod.LedgerMapping(self._ledger, _store_mod.STATUS_SUSPECT,
                                     ts_field="verified_at",
                                     extra_from_value={"origin": "origin",
                                                       "dest": "dest",
                                                       "gen_requested_at": "gen"}))

    def _seed_ledger_from_saved(self, mapping, saved: Dict[str, Any],
                                ts_field: str) -> None:
        """
        把 `save_data` 里的旧数据**喂进**台账替身（只在台账尚无该键时）。

        Seed the ledger-backed mapping from legacy `save_data` content.

        ## 为什么不是"台账可用就跳过恢复"

        我第一版写的是 `if isinstance(saved, dict) and self._ledger is None:` ——
        意图是"台账已就位，别再让旧字典覆盖替身"。但那把两种不同情况混成了一件事：

          · 台账里**已经有**这个 key → 以台账为准，忽略旧值 ✅（原意图正确）
          · 台账里**还没有**这个 key → 旧值是唯一来源，跳过它就**丢数据** ❌

        第二种正是"升级后第一次启动"的场景（台账刚建、还是空的），
        以及 `__new__` 构造后直接走 `init_plugin` 的单测路径。
        实测：`test_strm_ignore_filter` 的两条载入路径用例因此整条清单变空。

        正确做法是**逐键判断**：台账有的以台账为准，台账没有的用旧值补上。
        """
        if not isinstance(saved, dict) or not saved:
            return
        existing_keys = set(mapping.keys())
        seeded = 0
        for key, value in saved.items():
            if key in existing_keys:
                continue          # 台账已有 → 以台账为准（它更新）
            mapping[key] = value
            seeded += 1
        if seeded:
            logger.debug(f"[Rsync115Sync] 已从旧 save_data 补入台账 {seeded} 条"
                         f"（这些键在台账中尚不存在）")

    @staticmethod
    def _adopt_into_ledger(existing, mapping):
        """
        把**内存里已有的**字典内容并入台账替身，再返回替身。

        Fold any pre-existing in-memory dict into the ledger-backed mapping.

        ## 为什么需要这一步（实测踩到的数据丢失）

        `init_plugin` 之前若已有值（`__new__` 构造的测试实例、或将来某处在
        构造阶段就填了队列），绑定替身时那些值会被**整体丢弃** —— 替身从台账
        载入，而台账里还没有它们。表现是"条目莫名消失"，且完全不报错。
        实测：`test_strm_ignore_filter` 的两条载入路径用例就是这么变红的。

        生产路径上目前不会触发（那些字典只在 `init_plugin` 里被赋值），
        但**不能依赖这个巧合** —— 一处静默的数据丢弃，代价远大于这里几行判断。
        """
        if isinstance(existing, dict) and existing:
            for k, v in existing.items():
                mapping[k] = v
        return mapping

    def _migrate_legacy_state_once(self) -> None:
        """
        把旧版 `save_data` 字典里**无法重建**的那部分导入台账，只做一次。

        Migrate the parts of the legacy `save_data` state that CANNOT be rebuilt.

        ## 为什么只迁这两个（而不是全部 18 个字典）

        逐类核对过「丢了能不能靠扫描重建」：

        | 旧字典 | 丢了会怎样 | 处理 |
        |---|---|---|
        | `ignored_files` | **用户手工建的规则，不可重建** —— 丢了那些特意忽略的文件会重新变成告警，得一条条再加 | **必须迁** |
        | `strm_suspects` | 可重建，但会丢失「该文件曾同步成功过」（origin=watch）这一信息 | **建议迁** |
        | `pending_queue` | 扫描按 mtime 重新发现（代价：冷却重新计时）| 丢弃 |
        | `strm_watch` | 扫描重新登记（代价：宽限期重新计时）| 丢弃 |
        | `strm_gen_requested` | 丢失「已补生成过」标记（代价：可能重复点补生成）| 丢弃 |
        | `backfill_queue` | 重扫即可 | 丢弃 |

        迁移标记写进 `meta` 表，因此**重载/重启都不会重复导入**。

        ## 为什么旧的 save_data 键**不删**

        迁移后仍保留旧键，作为「迁移结果对不对」的对照。等新台账稳定运行一段时间
        后再清理 —— 现在就删的话，万一迁移有偏差，用户的数据就真没了。
        """
        if self._ledger is None:
            return
        if self._ledger.get_meta("legacy_migrated") == "1":
            return

        migrated = {"ignored": 0, "suspects": 0}

        # ① 忽略规则：**不可重建**，必须迁
        #
        # ⚠️ 只迁「形如 映射名:相对路径」的规则。忽略规则也支持纯关键字
        # （contains 模式，例如 `/rsync_ignore 某剧名`），那种规则没有对应的
        # 单个文件 —— 它不是"某个文件的状态"，仍由 `_ignored_rules` 承担。
        # 把关键字硬塞进台账会在 files 表里造出一批虚构路径。
        rules = self.get_data("ignored_files") or []
        if isinstance(rules, list):
            for rule in rules:
                text = rule if isinstance(rule, str) else (
                    (rule or {}).get("rule") or (rule or {}).get("pattern") or "")
                text = str(text).strip()
                if not text or ":" not in text:
                    continue
                if self._ledger.upsert(text, _store_mod.STATUS_IGNORED,
                                      ingest_source=_store_mod.SOURCE_LEGACY):
                    migrated["ignored"] += 1

        # ② strm 疑似清单：可重建，但迁移能保住原始时间戳
        suspects = self.get_data("strm_suspects") or {}
        if isinstance(suspects, dict):
            for key, entry in suspects.items():
                ts = None
                if isinstance(entry, dict):
                    try:
                        ts = float(entry.get("ts") or 0) or None
                    except (TypeError, ValueError):
                        ts = None
                if self._ledger.upsert(str(key), _store_mod.STATUS_SUSPECT,
                                      ingest_source=_store_mod.SOURCE_LEGACY,
                                      enqueued_at=ts, verified_at=ts):
                    migrated["suspects"] += 1

        self._ledger.set_meta("legacy_migrated", "1")
        logger.info(f"[Rsync115Sync] 📒 文件台账已建立，旧数据迁移完成："
                    f"忽略条目 {migrated['ignored']} / 疑似 {migrated['suspects']}"
                    f"（旧 save_data 键保留未删，便于对照）")

    def _api_get_status(self):
        now_ts = time.time()
        threshold = self._delay_hours * 3600
        ready_count, cooling_count, stale_count = self._count_queue(now_ts, threshold)
        webhook_stat = dict(self._webhook_stat_now())
        # 看板要能直接回答「webhook 这条路到底通不通」。只给累计计数还不够：
        # 用户配好发送端后最常见的问题是「到底有没有请求打进来」，
        # 而 0 次既可能是没配、也可能是配错地址 —— 报文的最后结构摘要
        # 正是用来区分这两者的（没请求 = 没配好；有请求但未识别 = 字段名要加）。
        # 注：这里曾补一个 `channels` 字段（当前生效的渠道白名单），白名单已移除。
        return {
            "success": True,
            "data": {
                "is_running": self._is_running,
                # webhook 运行态：计数 + 最近报文的**字段结构**（不记值）。
                "webhook": webhook_stat,
                # 入库闸门挡下的扩展名分布（累计，扩展名 → 次数）。
                # 看板据此显示「哪些类型正在被丢弃」—— 这是此前完全缺失的一维：
                # 丢弃只写 debug，界面上零痕迹（音频曾因此全丢而不自知）。
                # getattr 兜底：本方法会被 `__new__` 构造的实例（单测/部分宿主路径）
                # 调用，此时 `__init__` 没跑过、该属性不存在。为看板统计抛
                # AttributeError 会把「同步本身完全正常」表现成异常（本项目已记录过
                # 这一类缺陷，见 _webhook_stat_now 的同一处理）。
                "ingest_skipped_by_ext": dict(getattr(self, "_ingest_skip_stat", None) or {}),
                # 源端游标扫描（主入库通道）的可见状态
                "source_scan_enabled": self._source_scan_enabled,
                "source_scan_cron": self._source_scan_cron,
                "source_cursor": dict(self._source_cursor),
                "source_scan_last": self._source_scan_last,
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
                # ⚠️ 这里曾有 source_scan_enabled / source_scan_interval 的**第二份**
                # （直接读属性，无 getattr 兜底）。字典里重复的键不会报错、后者胜出，
                # 于是上面那份带兜底的写法被悄悄架空 —— `__new__` 构造的实例调本方法
                # 仍会 AttributeError。重复键是这类"看起来已经修了"的典型来源，
                # 加字段时务必先 grep 确认该键不存在。
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
                "strm_grace_minutes": self._strm_grace_minutes,
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
                # 窗口长度：看板用它把"还剩几个窗口"换算成分钟数
                # （`预计需要约 N 个窗口（N × M 分钟）`）。此前看板读的是
                # `statusData.upload_window_secs || 1800` —— 而 /status 从来不返回
                # 这个键，于是那行文案**永远按 1800 秒算**，即使用户把窗口改成了
                # 其它值。默认值恰好正确，所以这个缺口一直没被发现。
                #
                # ⚠️ 必须带 getattr 兜底：本方法会被 `__new__` 构造的实例调用
                # （单测与部分宿主路径），此时 `__init__` 没跑过。
                # 我加这个键时漏了兜底，当场让 5 条既有用例报 AttributeError ——
                # 同一个坑本文件里已经记过两次（见上方两条同款注释），这是第三次。
                # 新增任何 /status 字段时，先问自己：`__new__` 实例上它有值吗？
                "upload_window_secs": int(
                    getattr(self, "_upload_window_secs", 1800)),
                "upload_blocked_until": self._upload_blocked_until,
                "last_force_ts": self._last_force_ts,
                "force_cooldown_days": self._force_cooldown_days,
            }
        }

    def _api_get_queue(self):
        now_ts = time.time()
        threshold = self._delay_hours * 3600
        items = []
        for key, basis_ts in sorted(self._pending_queue.items(), key=lambda x: x[1]):
            # ⚠️ 队列里存的是**冷却基准**（min(发现时刻, mtime)），不是入队时刻。
            # 对一个"入库时间早于发现时间"的文件（插件重载期间错过的），
            # 基准会明显早于它真正进队列的时刻 —— 因此下面这个时间字段命名为
            # 「冷却基准」而不是「入队时间」，否则用户会看到「入队时间 3 小时前」
            # 却不知道那个时间是文件自己的 mtime（这正是它已就绪的原因）。
            elapsed = now_ts - basis_ts
            remaining = max(0, threshold - elapsed)
            items.append({
                "key": key,
                "basis_time": datetime.fromtimestamp(basis_ts).strftime("%Y-%m-%d %H:%M:%S"),
                "enter_time": datetime.fromtimestamp(basis_ts).strftime("%Y-%m-%d %H:%M:%S"),
                "is_ready": elapsed >= threshold,
                "remaining_seconds": int(remaining)
            })
        return {"success": True, "data": items}

    def _api_trigger_sync(self):
        if self._is_running:
            return {"success": False, "message": "已有任务正在运行"}
        self._start_sync_thread(mode="ready")
        return {"success": True, "message": "已触发同步任务"}

    def _api_run_now(self):
        """
        「立即运行一次」：**不等两个 cron**，立刻扫一次源端并跑一次就绪同步。

        Run once right now, skipping both schedules: the source scan is executed
        immediately and a ready-sync is started without waiting for the cron tick.

        ## 它绕过什么、不绕过什么（这是本端点最需要说清的一件事）

        | | 是否绕过 |
        |---|---|
        | 源端扫描的 cron 节奏 | ✅ 绕过 —— 立刻扫一次 |
        | 同步的 cron 节奏 | ✅ 绕过 —— 立刻跑一轮 ready |
        | **文件冷却时长**（`delay_hours`） | ❌ **不绕过** |
        | 限流窗口 / 退避 / 批次上限 | ❌ 不绕过 |
        | 忽略清单 / 扩展名闸门 | ❌ 不绕过 |

        **为什么冷却不在此列**：冷却期的现职是"等文件写完"（源端扫描没有"写完了"
        这个信号，而正在写入的文件 mtime 恰恰最新），绕过它等于把半截文件传给
        115 —— 那正是 §3.10 记录的云端残留的成因。想立刻传某个**已经冷却到位**
        的文件，用列表里的单条「立即同步」（`/sync_item`），那个是定向上传。

        所以本按钮的真实语义是「**别等下一班，现在就查一次**」：
        它把"发现"提前，再把"已经到期的"传上去。若队列里的文件都还在冷却中，
        返回消息会**明说**有多少个在冷却、还要等多久 —— 否则用户会以为按钮没生效。

        :return: 含本次扫描结果与排队情况的响应
        """
        if self._is_running:
            return {"success": False, "message": "已有任务正在运行，请稍后再试"}

        # ① 立刻扫一次源端（本地 IO、零 115 API，与 _api_backfill_scan 同性质）
        scanned = 0
        scan_err = ""
        if self._source_scan_enabled:
            try:
                scanned = self._scan_source_cursor()
            except Exception as err:
                # 扫描失败不该拦住同步：同步处理的是**已经**在队列里的文件
                scan_err = str(err)
                logger.warning(f"[Rsync115Sync] 「立即运行一次」的源端扫描失败（已忽略，继续同步）: {err}")
        else:
            scan_err = "源端扫描已关闭，本次只同步已入队的文件"

        # ② 统计排队情况，让返回消息能直接回答"为什么一个也没传"
        now_ts = time.time()
        threshold = self._delay_hours * 3600
        ready_count, cooling_count, stale_count = self._count_queue(now_ts, threshold)
        # ⚠️ 只在**仍在冷却**的条目里取最小值。
        # 第一版写成对 `_pending_queue.values()` 全体取 `min`，于是已经就绪的条目
        # 会贡献一个负的剩余量，把结果压成 0 —— 消息里就出现了
        # 「1 个仍在冷却中（最快还需约 0 分钟）」这种自相矛盾的话
        # （实测：那个文件实际还有 4 小时）。已就绪的条目本来也不该参与这个数。
        remaining = [threshold - (now_ts - basis) for basis in self._pending_queue.values()]
        pending_remainders = [r for r in remaining if r > 0]
        cooling_min = max(0, int(min(pending_remainders, default=0) / 60))

        # ③ 立刻跑一轮 ready（不等同步 cron）
        self._start_sync_thread(mode="ready")

        parts = [f"已立即执行：源端扫描新增 {scanned} 个文件入队"]
        if scan_err:
            parts.append(f"（{scan_err}）")
        if cooling_count:
            parts.append(f"当前 {cooling_count} 个仍在冷却中"
                         f"（最快还需约 {cooling_min} 分钟），它们不在本轮传输范围")
        if ready_count:
            parts.append(f"{ready_count} 个已就绪，正在传输")
        elif not cooling_count:
            parts.append("队列中没有待传输文件")
        if stale_count:
            parts.append(f"{stale_count} 个条目的源文件已不存在，将在本轮清理")
        parts.append("限流与批次上限照常生效，可在看板「冷却队列」标签查看进度")
        return {"success": True,
                "message": "；".join(parts),
                "data": {"scanned": scanned, "ready": ready_count,
                         "cooling": cooling_count, "stale": stale_count}}

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







    # ================= Webhook 入库配置 =================
    # 现已**没有任何 webhook 配置项**，这一节只剩说明：
    #   · 自建匿名端点及其四条防护（开关/密钥/路径白名单/IP 白名单）
    #     随端点在 2026-09-22 一并移除 —— 见 DEVELOPMENT §9.18。
    #   · 来源渠道白名单（默认 `emby`）在 2026-09-24 移除 —— 见 §4.0a ③-b：
    #     本插件只认 `source=rsync115sync`，其它来源归平台自己的解析器，
    #     因此不存在「需要用户声明接收哪些渠道」这件事。
    # 保留本注释是为了让「配置页/接口里为什么没有 webhook 项」有据可查。

    @staticmethod
    def _read_grace_minutes(config: Dict[str, Any]) -> int:
        """
        读取观察宽限期（分钟）。**缺失**回默认，**填了 0** 则夹到下限 1。

        Read the grace window in minutes: missing → default; an explicit 0 → the
        lower bound, not the default.

        ⚠️ 这里刻意**不用** `config.get(k) or default` —— 那个写法把 `0` 和
        "没填" 当成同一件事，于是"我想尽快判定所以填 0"的用户会**静默拿到 5 分钟**，
        而不是他想要的"最短"。差别看似很小（都是等一会儿才判定），但方向是反的：
        用户表达的是"越小越好"，代码给了一个比它大 5 倍的值，而且屏幕上那个框
        显示的就是他填的 0。
        `delay_hours` 同理（那里的 hint 明说"设为 0 可关闭等待"），它用的是
        `config.get(k, default)` 而不是 `or`，语义一致。
        """
        raw = config.get("strm_grace_minutes")
        if raw is None or raw == "":
            return _strm.DEFAULT_GRACE_MINUTES
        try:
            return max(_strm.MIN_GRACE_MINUTES, int(float(raw)))
        except (TypeError, ValueError):
            return _strm.DEFAULT_GRACE_MINUTES

    def _read_source_scan_cron(self, config: Dict[str, Any]) -> str:
        """
        读取源端扫描的 cron 表达式，并兼容旧的「间隔秒数」配置。

        Read the source-scan cron, migrating the old "interval in seconds" key.

        兼容规则（**必须存在**，否则老用户升级后节奏会静默变化）：

          · 有 `source_scan_cron` → 用它；
          · 否则有 `source_scan_interval`（秒）→ 换算成等价的 `*/N * * * *`。
            cron 的最小粒度是分钟，因此向上取整到分钟（600 秒 → `*/10`）；
            小于 60 秒的值按 1 分钟处理，并在日志里说明 —— 静默夹紧会让用户
            以为自己配的 30 秒生效了。
          · 都没有 → 默认 `*/30 * * * *`。

        ⚠️ 表达式本身**不在这里校验**：非法 cron 由 `CronTrigger.from_crontab`
        在注册 service 时抛错，而那条路已有 try/except 与日志（与「定时检查」
        同一个处理方式）。在这里再校验一次会形成两处判据，迟早不一致。
        """
        cron = str(config.get("source_scan_cron") or "").strip()
        if cron:
            return cron

        legacy = config.get("source_scan_interval")
        if legacy is not None:
            try:
                secs = int(float(legacy))
            except (TypeError, ValueError):
                secs = 0
            if secs > 0:
                minutes = max(1, round(secs / 60))
                if secs < 60:
                    logger.info(f"[Rsync115Sync] 源端扫描间隔 {secs} 秒小于 cron 的最小粒度"
                                f"（1 分钟），已按 1 分钟处理")
                logger.info(f"[Rsync115Sync] 源端扫描间隔已从「{secs} 秒」换算为 cron "
                            f"表达式「*/{minutes} * * * *」（该配置项已改为 cron，见配置页）")
                return f"*/{minutes} * * * *"

        return self._SOURCE_SCAN_CRON_DEFAULT

    @staticmethod
    def _warn_on_legacy_grace_unit(config: Dict[str, Any]) -> None:
        """
        旧的 `strm_grace_hours`（小时）已换成 `strm_grace_minutes`（分钟）。

        The grace window unit changed from hours to minutes; the key was renamed.

        ⚠️ **必须显式提示，不能静默换算。** 旧键里存的 `6.0` 表示 6 小时；
        若按同名语义继续读并换个单位解释，它会变成 **6 分钟** —— 而 6 分钟正是
        最坏的一种表现：strm 还没生成就大面积判成"疑似上传异常"，
        于是用户收到一堆假的坏消息，然后开始无视这个功能。
        （换个方向把 `6.0` 当小时再换算成 360 分钟同样错，只是错得不那么吵。）

        正确做法就是**不猜**：值回落到新默认（5 分钟），并明确告诉用户旧值已失效、
        需要自己去配置页重设一次。配置页那栏的 hint 里也写着单位是分钟。

        Static 是为了能在 `__new__` 构造的实例上跑（单测路径）；它只读 config、只写日志。
        """
        if not config or config.get("strm_grace_minutes") is not None:
            return
        legacy = config.get("strm_grace_hours")
        if legacy is None:
            return
        logger.info(f"[Rsync115Sync] ⚠️ 配置项「strm_grace_hours」已废弃：观察宽限期的单位从"
                    f"**小时**改为**分钟**，键名随之改为 strm_grace_minutes。"
                    f"你原来的值（{legacy} 小时）不会被自动换算 —— 静默换个单位去解释同一个数"
                    f"会让 6 小时变成 6 分钟，从而大面积误报。"
                    f"当前已回落到新默认 {5} 分钟，请到配置页「strm 交叉验证」里按分钟重设。")

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
            # ⚠️ 判据写成「当前值 ∈ 该字段的**全部**旧默认串」。这里原先是
            # 逐字段比对**单个**旧默认串，于是第二代旧默认值（含字幕但不含音频
            # 的那串）既不等于第一代、也不等于新默认，永远不被迁移 ——
            # 用户看到的现象是「按文档升级了，音频还是不传」，而配置页那栏
            # 显示着一串看起来很正常的扩展名，无从判断它是"用户自己填的"。
            # Compare against EVERY generation of legacy defaults for that field.
            for field, legacy_values in self._LEGACY_DEFAULTS_ALL.items():
                cur = str(config.get(field) or "").strip()
                if not cur or cur not in legacy_values:
                    continue
                new_value = self._LEGACY_MIGRATION_TARGETS[field]
                setattr(self, self._LEGACY_MIGRATION_ATTRS[field], new_value)
                changed[field] = new_value

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
        定时巡检入口：常规就绪同步优先，补传队列用**剩余**配额续跑。

        Cron entry point. Ready-sync first; the back-fill queue drains with what is
        left of the window quota.

        ⚠️ 这里的顺序在 2026-09-25 被**反转过**，原因是旧顺序会让主任务饿死：

            旧：if self._resume_backfill_if_pending(): return   # 补传非空 → 直接返回
                self._start_sync_thread(mode="ready")

        补传队列是"存量"（可能是几千条），而每个 cron tick 都会启动一批补传就
        return。批次上限 200、窗口配额 500/30min 的情况下，一个几千条的队列会
        连续占用十几轮 cron，期间**所有冷却到期的追加文件一动不动** —— 而界面上
        没有任何地方说明「现在是补传在跑，ready 在排队」。

        为什么不能改成"两个都启动"：两种模式共用同一把执行锁与同一份窗口配额，
        同时启动只会让后者拿不到锁而静默什么都不做（原注释已经指出这点）。
        正确做法是**顺序互换**：ready 先跑（它是新鲜入库，时效敏感），
        补传后跑（它是存量，晚一轮无所谓）——`_execute_sync` 内部还有配额判定，
        配额被 ready 用掉时补传会自然地留到下一轮。

        Order matters: ready is freshness-sensitive, back-fill is stock inventory.
        """
        logger.info("[Rsync115Sync] 触发定时检查同步就绪媒体...")
        # strm 交叉验证巡检：纯本地文件系统操作（零 115 API），
        # 在任何同步启动前顺带执行；内部自带节流（30 分钟）与异常兜底
        try:
            self._strm_check()
        except Exception as e:
            logger.warning(f"[Rsync115Sync] strm 交叉验证巡检异常（已忽略，不影响本轮同步）: {e}")

        # ready 优先：新鲜入库的时效性远高于存量补传。
        # 若 ready 本轮确实有活干，补传推迟到下一个 tick（`_resume_backfill_if_pending`
        # 每轮都会再试，且队列有限、自终止，不会因此永远排不上）。
        if self._has_ready_files():
            self._start_sync_thread(mode="ready")
            return
        if self._resume_backfill_if_pending():
            return
        # 两者都没活干：仍然跑一次 ready，让它完成队列清理（源端已消失的条目出队）
        # 并如实回报「本轮无需同步」。
        self._start_sync_thread(mode="ready")

    def _has_ready_files(self) -> bool:
        """
        队列里是否存在**已经冷却到期**的条目。

        Whether any queued entry has passed its cool-down. Uses the same basis as
        `_execute_sync` (min(discovered, mtime) + delay) so the scheduling decision
        can never disagree with what the run would actually pick up.
        """
        now_ts = time.time()
        threshold = self._delay_hours * 3600
        for basis_ts in (self._pending_queue or {}).values():
            try:
                if now_ts - float(basis_ts) >= threshold:
                    return True
            except (TypeError, ValueError):
                continue
        return False

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
          force    — 先全量只读对账，再只对问题文件走 --files-from + 配额预扣
                     （P0-2：不再整树盲传；全量遍历仍受 7 天冷却约束）
                     full read-only audit first, then transfer only problem files
                     via --files-from with quota pre-charge (no more blind full-tree
                     rsync; the full walk stays gated by the 7-day cool-down)

        防风控设计（贯穿全流程）/ anti-abuse design applied throughout:
          1) 入口闸门：退避期或配额用尽时整轮直接返回，一次 API 都不发；
             entry gate — return early on back-off or exhausted quota, zero API calls
          2) 批次上限：单次 rsync 提交量有界，超出部分留待下轮（force 同样适用）；
             per-run batch cap, remainder deferred (force included)
          3) 配额预扣：启动 rsync 前先扣减并落盘，防止重载绕过（force 同样适用）；
             quota pre-charged and persisted before rsync starts (force included)
          4) stderr 风控检测：命中关键词立即退避并终止本轮；
             stderr rate-limit detection aborts the whole run immediately
          5) 配额中途耗尽：非 force 停止后续映射；force 只关传输、继续只读对账。
             ready/retry/backfill stop further pairs; force keeps auditing only.
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
            # ⚠️ 这里**不再**调用源端扫描。扫描已从同步 cron 里移出去，
            # 改由独立 service 驱动（见 get_service）。原因：原先挂在
            # `_execute_sync(mode="ready")` 内部，而 `_scheduled_sync` 是
            # 「补传队列非空就 return」—— 补传一忙，扫描整轮不跑，
            # 主通道被次要通道饿死。发现层的节奏不该由传输层决定。

            # force 在配额耗尽后仍应完成**剩余映射的只读全量对账**（不传输）：
            # 对账是 force 的语义核心，且不再产生上传；若直接 break，剩余映射要等
            # 下一个 7 天冷却才能被核对。传输侧由 force_transfer_allowed 关掉。
            force_transfer_allowed = True

            for idx, pair in enumerate(self._sync_pairs):
                src = (pair.get("src") or "").strip().rstrip("/")
                dest = (pair.get("dest") or "").strip().rstrip("/")
                pair_name = _pair_name(pair)
                all_ext = pair.get("all_ext", False)

                if not os.path.exists(src) or not os.path.exists(dest):
                    logger.warning(f"[Rsync115Sync] [{pair_name}] 目录无效或 CD2 挂载未就绪，跳过本组映射: {src} -> {dest}")
                    continue

                # 配额已尽且非 force：维持原「停止后续映射」语义
                if (mode != "force"
                        and self._rate_limit_enabled
                        and self._upload_window_count >= self._upload_max_per_window):
                    logger.warning(f"[Rsync115Sync] 🚦 本窗口配额已用尽"
                                   f"（{self._upload_window_count}/{self._upload_max_per_window}），"
                                   f"剩余映射留待下一轮")
                    break

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

                # 排除目录参数（所有模式共用）
                for ex in self._exclude_patterns.splitlines():
                    ex_clean = ex.strip()
                    if ex_clean:
                        cmd.append(f"--exclude={ex_clean}")

                temp_list_file = None
                pair_files = []
                # force 预对账结果：批次上限未覆盖的问题必须原样保留在最终清单
                force_pre_missing: List[str] = []
                force_pre_corrupt: List[str] = []
                now_ts = time.time()
                threshold = self._delay_hours * 3600

                if mode == "force":
                    # ---- P0-2：先全盘对账（只读遍历），再只传问题文件 ----
                    # 旧路径对整棵源树做无 --files-from 的 rsync，pair_files 恒为空，
                    # 配额预扣与批次上限全部旁路。现改为：
                    #   全量对账 → 问题相对路径 → 与 ready/retry 共用 files-from + 预扣。
                    # 全量遍历仍受命令入口的 7 天冷却约束；传输受窗口配额约束。
                    force_pre_missing, force_pre_corrupt = self._audit_files_integrity(
                        src, dest, pair_name, all_ext, rel_paths=None)
                    pair_files = _force_problem_rel_paths(
                        pair_name, force_pre_missing, force_pre_corrupt)
                    if not pair_files:
                        logger.info(f"[Rsync115Sync] [{pair_name}] 🔍 force 全量对账通过，"
                                    f"无需传输（缺失 0 / 残缺 0）")
                        continue
                    if not force_transfer_allowed or (
                            self._rate_limit_enabled
                            and self._upload_window_count >= self._upload_max_per_window):
                        # 只读对账已完成；本映射的问题原样进最终清单，不发起上传
                        total_missing.extend(force_pre_missing)
                        total_corrupt.extend(force_pre_corrupt)
                        logger.warning(f"[Rsync115Sync] [{pair_name}] 🚦 配额已尽，force 仅完成对账："
                                       f"{len(pair_files)} 个问题文件留待 /rsync_retry 或下轮 force")
                        continue
                    logger.info(f"[Rsync115Sync] [{pair_name}] 🔍 force 预对账发现 "
                                f"{len(pair_files)} 个问题文件，转入定向传输（受批次上限与配额约束）")

                elif mode == "ready":
                    # 冷却判据的**唯一出口**：条目在队列里存的是「冷却基准时刻」
                    # （min(发现时刻, mtime)，见 _cooldown_basis），到期 = 基准 + 冷却时长。
                    # ⚠️ 两个队列已合并：这里曾另有一条 `_missed_queue` 通道，
                    # 它对"插件重载期间错过的文件"**无条件跳过冷却**。删除它的原因见
                    # _cooldown_basis 的 docstring —— 同一件事现在由基准取 mtime 表达，
                    # 而且顺带避免了「扫到刚落地的文件也立刻传」。
                    for key, basis_ts in list(self._pending_queue.items()):
                        if not key.startswith(f"{pair_name}:"):
                            continue
                        if now_ts - basis_ts < threshold:
                            continue
                        rel_p = key.split(f"{pair_name}:", 1)[1]
                        if os.path.exists(os.path.join(src, rel_p)):
                            pair_files.append(rel_p)
                        else:
                            # 源端已不存在（被删除/移动）：出队，避免长期挂账
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

                # ---- 所有模式（含 force）统一：files-from + 批次上限 + 配额预扣 ----
                if not pair_files:
                    # 本次没有需要处理的文件，跳过该目录（不做全盘对账，避免历史存量文件误报）
                    logger.info(f"[Rsync115Sync] [{pair_name}] 本组无待传输文件，跳过（不做全量对账，避免历史存量误报）")
                    continue

                # ---- 批次上限：单次 rsync 处理量有界，避免命令行过长与瞬时峰值 ----
                # force 截断的问题文件不会进 pending_queue：由预对账清单 +
                # merge_force_anomalies 留在异常清单，供 /rsync_retry 继续。
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
                    # 23=部分未传输、24=源文件消失，属可容忍告警：记录但不判定整轮失败。
                    # 只影响「整轮是否算失败」，**不**阻止本批对账通过的文件出队与
                    # 登记 strm（P0-1，见 paths.success_keys_after_audit）。
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

                # 注：这里原有一段「补齐清单出账」（把本批确实交给 rsync 的条目从
                # `_missed_queue` 移出）。该队列已随冷却判据统一而删除 —— 现在冷却
                # 到期的条目统一存在 `_pending_queue` 里，其出队由下方的对账结果驱动
                # （见「P0-1：出队与 strm 登记只看对账，不看退出码」一段），
                # 时机与粒度都与本段原本的意图一致，且只维护一处状态。
                # The missed-event queue was removed; cool-down entries now live in
                # `_pending_queue` and are settled by the audit result below.

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
                    if mode == "force":
                        force_transfer_allowed = False
                        logger.warning(f"[Rsync115Sync] 🚦 本窗口配额已用尽"
                                       f"（{self._upload_window_count}/{self._upload_max_per_window}），"
                                       f"force 后续映射只做对账、不再上传")
                    else:
                        logger.warning(f"[Rsync115Sync] 🚦 本窗口配额已用尽"
                                       f"（{self._upload_window_count}/{self._upload_max_per_window}），"
                                       f"剩余映射留待下一轮")
                        break

                # 双向对账：ready/retry/backfill 核对本批；force 核对本批传输结果，
                # 再与预对账未尝试部分合并（不重跑整树，避免二次全量遍历）。
                #
                # ⚠️ audit 在 src/dest 任一不存在时返回**空清单**（不是「全部通过」）。
                # 若不拦截，会把本批全部当成成功：错误出队、arm strm，并因
                # audited_keys 清掉历史异常 —— 挂载掉线时的静默数据丢失。
                attempted_keys = [f"{pair_name}:{p}" for p in pair_files]
                audit_valid = os.path.exists(src) and os.path.exists(dest)
                if not audit_valid:
                    logger.warning(
                        f"[Rsync115Sync] [{pair_name}] ⚠ 源/目标目录不可用，跳过对账结算"
                        f"（不出队、不 arm strm、不改历史异常）: {src} -> {dest}")
                    if mode == "force":
                        total_missing.extend(force_pre_missing)
                        total_corrupt.extend(force_pre_corrupt)
                    elif mode in ("ready", "retry", "backfill"):
                        # 保守：本批记为仍缺失，留待下轮/重试；不更新 audited_keys
                        total_missing.extend(attempted_keys)
                    if mode == "backfill":
                        for rel_p in pair_files:
                            k = f"{pair_name}:{rel_p}"
                            if k not in self._backfill_done_keys:
                                self._backfill_done_keys.add(k)
                    continue

                m_list, c_list = self._audit_files_integrity(
                    src, dest, pair_name, all_ext, rel_paths=pair_files)
                if mode == "force":
                    final_m, final_c = _merge_force_anomalies(
                        force_pre_missing, force_pre_corrupt,
                        attempted_keys, m_list, c_list)
                    total_missing.extend(final_m)
                    total_corrupt.extend(final_c)
                    succeeded = _success_keys_after_audit(pair_name, pair_files, m_list, c_list)
                    synced_count += len(succeeded)
                else:
                    synced_count += len(pair_files)
                    audited_keys.update(attempted_keys)
                    total_missing.extend(m_list)
                    total_corrupt.extend(c_list)

                logger.info(f"[Rsync115Sync] [{pair_name}] 🔍 对账结果: 本次核对 {len(pair_files)} 个，"
                            f"缺失 {len(m_list)} 个，残缺 {len(c_list)} 个")
                for k in m_list:
                    logger.warning(f"[Rsync115Sync] [{pair_name}]   ✗ 缺失未同步: {k}")
                for k in c_list:
                    logger.warning(f"[Rsync115Sync] [{pair_name}]   ✗ 大小残缺: {k}")

                # ---- P0-1：出队与 strm 登记只看对账，不看退出码 ----
                # exit 23/24 是整批告警；批内已就绪文件若被 `exit_code == 0`
                # 拦住，会永不出队、也永不进入 strm 观察。
                if mode == "ready":
                    succeeded_keys = set(_success_keys_after_audit(
                        pair_name, pair_files, m_list, c_list))
                    # 用 pair_files 正向拼 key，不用 split(":",1) 反解析 ——
                    # 任务名本身可能含冒号（paths.split_pair_key 已注明）。
                    for rel_p in pair_files:
                        k = f"{pair_name}:{rel_p}"
                        if k not in succeeded_keys:
                            continue
                        self._pending_queue.pop(k, None)
                        logger.info(f"[Rsync115Sync] [{pair_name}] 🧊 已移出冷却队列: {rel_p}")
                    # strm 交叉验证：登记待观察（有 strm_dir 的映射才实际生效）
                    if succeeded_keys:
                        armed = self._strm_arm_watch(sorted(succeeded_keys))
                        if armed:
                            logger.info(f"[Rsync115Sync] [{pair_name}] 📺 已登记 {armed} 个文件进入 "
                                        f"strm 观察期（{self._strm_grace_minutes} 分钟内未生成 strm 将标记疑似异常）")

                # 重试模式成功：同样登记 strm 观察（重传后自动复核 strm 是否生成，
                # 生成即自动解除疑点，无需用户再确认）
                if mode == "retry":
                    succeeded_retry = _success_keys_after_audit(
                        pair_name, pair_files, m_list, c_list)
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

        # 全量对账的扩展名判据与入库闸门同一实现（all_ext 分支由它内部处理）。
        # 这里原先自己解析了一份 valid_exts 并只判 `not all_ext`，
        # 与入库闸门是两份独立实现 —— 两份一旦分叉，对账就会去核对一批
        # 根本不会被同步的文件，把异常清单刷出永远消不掉的条目。
        audit_pair = {"all_ext": all_ext}

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
        cooling_seconds = self._delay_hours * 3600   # 条目存的是冷却基准，见 _cooldown_basis

        for root, _, files in os.walk(source_dir):
            for f in files:
                if _is_junk_file_name(f):
                    continue
                if not _wh_valid_extension(audit_pair, f, self._media_extensions):
                    continue

                src_f = os.path.join(root, f)
                rel_f = os.path.relpath(src_f, source_dir)
                dest_f = os.path.join(target_dir, rel_f)
                key = f"{pair_name}:{rel_f}"

                # 忽略清单中的文件不参与对账
                if self._is_ignored(key):
                    continue

                # 冷却期内的文件属于正常等待调度，不计入缺失/待重试。
                # 队列值 = 冷却基准（min(发现时刻, mtime)），判据与 _execute_sync 一致。
                if key in self._pending_queue:
                    basis_ts = self._pending_queue[key]
                    if (now_ts - basis_ts) < cooling_seconds:
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

































