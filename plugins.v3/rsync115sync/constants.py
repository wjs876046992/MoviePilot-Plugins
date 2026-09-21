"""
本插件的模块级常量与默认参数。

Module-level constants and default parameters for the plugin.

为什么单独成文件（阶段 1 拆分的第一个模块）：
本模块**只有常量、没有逻辑**，因此不存在任何导入顺序或实例状态问题 ——
可以放心被任何其它模块引用，包括 `__init__.py` 之外的兄弟模块。

Why a separate file: this module holds constants only, no logic, so it has no
import-order or instance-state concerns and can be imported by any sibling
module. Pure constants are the safest possible extraction target.

注意：这些常量是**模块私有约定**，不是宿主合同的一部分。
改动它们等于改动插件默认行为，需要同步 USAGE.md。
"""

# ---- 同步扩展名 / sync extensions ----
# 与 sync_115.sh 对齐，shell 侧含字幕与更多容器格式。字幕必须纳入，
# 否则「留足外挂字幕下载时间」的冷却设计就失去意义。
# Aligned with sync_115.sh. Subtitles must be included, otherwise the very
# purpose of the cool-down period ("leave time for external subtitles") is lost.
DEFAULT_MEDIA_EXTENSIONS = (
    "mp4,mkv,ts,iso,rmvb,avi,mov,mpeg,mpg,wmv,3gp,asf,m4v,flv,m2ts,tp,f4v,srt,ssa,ass"
)

# 默认排除规则。注意 `..*` 在 rsync 语义下**只匹配以 `..` 开头的名字**，
# 挡不住 `影片.mkv..xrp4gj` 这种 `..` 出现在中间的临时文件；要挡住需改成 `*..*`。
# （实测结论见 DEVELOPMENT.md 3.10，USAGE.md 常见问题中有对照表。）
# NOTE: under rsync's glob semantics `..*` matches only names *starting* with
# `..`, so it does NOT block `movie.mkv..xrp4gj`. Use `*..*` to block those.
DEFAULT_EXCLUDE_PATTERNS = "@eaDir/\n#recycle/\n@__thumb/\n.DS_Store\n..*"

# I/O 超时对齐 shell 的 IO_TIMEOUT=600：CD2 挂载下大文件单次 I/O 超过 60 秒很常见，
# --timeout 只约束 I/O 无响应而非总时长。
# I/O timeout aligned with IO_TIMEOUT=600 in the shell script: under a CD2 mount a
# single large-file I/O can easily exceed 60s. --timeout limits I/O inactivity only.
DEFAULT_RSYNC_TIMEOUT = 600
DEFAULT_TASK_TIMEOUT = 3600

# 历史默认值：用于把「从未改过配置」的老用户平滑迁移到新默认值。
# 只有当前值恰好等于旧默认串时才替换，绝不覆盖用户自定义值。
# Legacy defaults used to migrate users who never touched their config. A value is
# replaced only when it exactly equals the old default string, so a user's
# customised setting is never overwritten.
LEGACY_DEFAULTS = {
    "media_extensions": "mp4,mkv,avi,mov,ts,m2ts,iso,wmv,flv,rmvb",
    "exclude_patterns": "@eaDir/\n#recycle/\n@__thumb/\n.DS_Store",
    "rsync_timeout": 60,
}

# rsync 退出码语义（与 sync_115.sh 的 _handle_rsync_exit 对齐）
# rsync exit-code semantics, aligned with _handle_rsync_exit in sync_115.sh:
#   0  Success / 成功
#   24 Source file vanished mid-transfer — normal fluctuation, not a failure
#      / 源文件在传输中消失，属正常波动，不计入失败
#   23 Some files not transferred — tolerable warning, not a failure
#      / 部分文件未传输，属可容忍告警，不计入失败
# 其余非 0 码均视为致命错误，必须让本轮判定为失败，避免谎报「已完成」。
# Any other non-zero code is fatal: the whole run must be marked as failed,
# otherwise the plugin would falsely report "all files uploaded".
TOLERATED_EXIT_CODES = {0, 23, 24}

# 伴生字幕扩展名：补传媒体文件时，同主名的这些文件一并纳入，
# 因为实际入库单元是「整集」（媒体 + 外挂字幕）。
# Sidecar subtitle extensions. A real ingest unit is a whole episode
# (video + external subtitles).
SIDECAR_EXTS = {"srt", "ass", "ssa", "sub", "idx", "sup", "vtt"}

# ---- 展示与日志的裁剪上限 / display and logging caps ----
# 日志里最多列出几个路径，以及单个路径的显示长度上限。目的：让日志能直接看出
# 「是哪个文件」，同时避免超长路径/大批量把日志撑爆。此前只打计数，用户无法
# 判断具体是哪个文件对不上，是排查效率低下的主因。
# Cap the number of paths and the length of each path in a single log line.
MAX_LOGGED_PATHS = 5
MAX_PATH_CHARS = 160

# /rsync_retry <关键字> 的单次匹配上限。与 search 的展示上限不同：
# retry 是「删除目标端 + 重传」，超限宁可直接拒绝也不要大范围误操作；
# search 是只读的，可以全量收集后仅截断展示。
# Match cap for keyword-retry. Deliberately different from the search display cap:
# retry deletes and re-uploads, so over-limit is rejected outright rather than
# truncated — refusing is safer than a wide destructive action.
RETRY_KEYWORD_LIMIT = 15

# ---- 巡检节流间隔（秒）/ sweep intervals in seconds ----
# strm 交叉验证巡检的最小间隔。strm 生成是分钟级过程，没必要每次同步都查。
# Minimum interval between strm cross-validation sweeps.
STRM_CHECK_INTERVAL = 1800

# 源端补齐扫描的最小间隔。事件丢失（插件重载期间）是低频问题，
# 没必要每轮同步都整树遍历一次本地媒体库。
# Minimum interval between source-root reconciliation scans.
MISSED_SCAN_INTERVAL = 1800

# 源端补齐扫描总开关。默认**关闭**，因为它的判据（文件 mtime 变新）无法区分
# 「真的新入库」与「老文件被重新 touch」：刮削写 nfo、下载器续传、套件定期刷
# 时间戳等都会让同一个老文件每轮被重复判为「新入库」，表现为「每隔几分钟冒出
# 一个其实 1 小时前就入库的文件、且立刻同步（不受冷却约束）」。
# 只有确实频繁遇到「插件重载期间丢事件」的用户才建议开启。
# Master switch for the source-root reconciliation scan. OFF by default: its signal
# (file mtime became newer) cannot distinguish a genuine new ingest from an old file
# merely being touched, which would re-enqueue the same old file every round and
# bypass the cool-down.
MISSED_SCAN_ENABLED_DEFAULT = False
