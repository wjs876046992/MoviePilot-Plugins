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
#
# ⚠️ **字幕是整集，不是只有 srt/ass/ssa**：Sup 图形字幕（`.sup`）与
# VobSub（`.sub`/`.idx`）在蓝光原盘转制里很常见，只认前三个等于「外挂字幕
# 只同步了一部分，另一部分静默丢弃」。四者必须同时默认在列。
# ⚠️ **音频**：宿主的整理完成事件按文件类型分派，音频走
# `AudioTransferComplete`。旧的 18 项默认**一个音频扩展名都没有**，于是
# 「音频入库」在闸门第一行就被 `skipped` 吃掉，且只记 debug —— 这正是
# 2026-09-25 之前「入库监听漏得多」的一半原因（另一半是事件本身会丢）。
# 音频只影响「要不要传到 115」；真正的音乐库同步是另一个插件的事。
#
# ⚠️ 本串在**三处**各有一份，改动必须同步（见 DEVELOPMENT §4.0f 的清单）：
#   1. 这里（后端默认值）
#   2. `LEGACY_DEFAULTS` 的历次旧默认串（迁移用）
#   3. `src/components/Config.vue` 的 `defaultConfig`
# 漏掉第 3 处会让「新装用户看到的表单值」与「后端实际默认值」不一致。
# Keep this string in sync with LEGACY_DEFAULTS and Config.vue's defaultConfig.
DEFAULT_MEDIA_EXTENSIONS = (
    # 视频容器 / video containers
    "mp4,mkv,ts,iso,rmvb,avi,mov,mpeg,mpg,wmv,3gp,asf,m4v,flv,m2ts,tp,f4v"
    # 外挂字幕 / external subtitles
    ",srt,ssa,ass,sup,sub,idx,vtt"
    # 音频 / audio
    ",mp3,flac,m4a,aac,opus,wav,mka,ape,wma"
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
#
# ⚠️ **一个字段可能有多代旧默认值**（本项目已改过两轮扩展名与两轮排除规则）。
# 迁移逻辑必须逐代比对，只比对最近一代会让更老的用户永远停在最初的窄白名单上
# —— 表现为「按文档升级了，音频/字幕却还是不入队」，而配置页上那一栏
# 看起来是"用户自己填的"，无从判断该不该动。
# A field can have SEVERAL generations of legacy defaults. Compare against every
# generation, not just the latest one.
LEGACY_DEFAULTS = {
    # 第 1 代（v0.0.x）：无字幕
    "media_extensions": "mp4,mkv,avi,mov,ts,m2ts,iso,wmv,flv,rmvb",
    "exclude_patterns": "@eaDir/\n#recycle/\n@__thumb/\n.DS_Store",
    "rsync_timeout": 60,
}

# 第 2 代扩展名默认值（v0.0.10 起）：加了字幕与更多容器，但仍**无音频**、
# 且字幕只有 srt/ssa/ass。凡当前值等于它，一律迁到最新默认值。
# Generation-2 media extensions (subtitles added, audio still missing).
LEGACY_MEDIA_EXTENSIONS_V2 = (
    "mp4,mkv,ts,iso,rmvb,avi,mov,mpeg,mpg,wmv,3gp,asf,m4v,flv,m2ts,tp,f4v,srt,ssa,ass"
)

# 映射到一个字段的全部「旧默认串」——迁移逻辑只应迭代它，不要手写 if 链，
# 否则下次再加一代默认值时必然漏掉某条分支。
LEGACY_DEFAULTS_ALL = {
    "media_extensions": (
        LEGACY_DEFAULTS["media_extensions"],
        LEGACY_MEDIA_EXTENSIONS_V2,
    ),
    "exclude_patterns": (LEGACY_DEFAULTS["exclude_patterns"],),
    "rsync_timeout": (str(LEGACY_DEFAULTS["rsync_timeout"]),),
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

# ---- 源端游标扫描 / source-root cursor scan ----
# 入库发现的**主通道**。取代了 2026-09-25 删除的宿主整理事件订阅，
# 判据与 sync_115.sh 的 `find -newer <last_sync>` 同构：
#   游标（上次成功扫描时刻）→ 挑出 mtime 晚于 (游标 − 重叠窗口) 的文件 → 入队
#
# 为什么它能同时做到「不漏」与「不多传」：
#   · 不依赖任何外部通知 —— 手动入库、外部搬入、9KG、插件重载期间发生的一切，
#     只要文件在源目录里就会被下次扫描看见；
#   · 老文件被 touch 不会造成重复上传 —— 冷却基准取 min(发现时刻, mtime)，
#     且游标随扫描推进，同一批文件不会反复"变新"（这是旧实现被默认关闭的原因）。
SOURCE_SCAN_ENABLED_DEFAULT = True

# 扫描节奏。**独立于同步 cron**（原先挂在 `_execute_sync(ready)` 内部，
# 而 `_scheduled_sync` 是"补传优先 and return" —— 补传一忙扫描整轮不跑）。
#
# 2026-09-25：从"固定间隔（秒）"改为**cron 表达式**，与「定时检查」用同一套写法。
# 理由：固定间隔表达不了"只在夜里扫"这类需求，而大库的整树遍历有成本；
# cron 表达力更强且用户已经熟悉本插件另一处 cron 字段。
# 每轮只是本地 os.walk，零 115 API，所以默认给一个较密的 `*/10`。
SOURCE_SCAN_CRON_DEFAULT = "*/10 * * * *"

# 兼容：旧配置里存的是秒（int）。发现 `source_scan_interval` 存在时按它换算成
# 等价的 cron，避免"升级后扫描节奏突然变成默认值"。换算只在**无法整除**时
# 退化为最接近的 `*/N`（cron 不支持秒，故下限是 1 分钟）。
SOURCE_SCAN_INTERVAL_LEGACY_DEFAULT = 600

# 游标重叠窗口（秒）。`os.path.getmtime` 的比较是严格大于，而同一秒批量落盘
# 很常见（整季拷贝、SMB 一次写入）。mtime 恰好等于游标的文件会被严格比较
# **永久跳过**，故把下界往后退一个窗口。代价不对称：窗口内的重复扫到由队列
# 幂等吸收（代价为零），而漏掉是永久损失。
SOURCE_CURSOR_OVERLAP_SECS = 120

# ---- 主动 strm 扫描 / proactive strm sweep ----
# 单次主动扫描最多收集多少个「源端存在但缺 strm」的文件。
#
# 为什么需要上限：主动扫描的判据是「源端有、strm 端没有」，它**无法区分**两种来源 ——
# 「从未上传过」（该走补传）与「上传了但 CD2 假成功」（该走删旧重传）。若 strm 插件
# 本身大面积不工作（开关关闭、媒体未识别），一次扫描会涌出成千上万条，看板与
# 通知都会被淹没。因此限量收集并在界面明确告知被截断的数量，让用户先判断
# 「是 strm 插件没工作」还是「真有一批坏文件」。
# Cap on a proactive sweep. The criterion (source present, strm absent) cannot
# distinguish "never uploaded" from "uploaded but fake-succeeded", so a broken strm
# plugin would flood the list; the cap plus an explicit truncation notice keeps that
# diagnosable.
STRM_SCAN_LIMIT = 500

# ---- strm 检查专用的视频扩展名 / video-only extensions for strm checks ----
# ⚠️ **不要与 DEFAULT_MEDIA_EXTENSIONS 混用**，两者回答的是不同问题：
#   DEFAULT_MEDIA_EXTENSIONS —— 「要同步哪些文件」（含字幕，因为入库单元是整集）
#   STRM_VIDEO_EXTENSIONS    —— 「哪些文件会生成 .strm」（仅视频容器）
#
# strm 插件只为**视频**生成指针文件，字幕永远不会有 .strm。若把同步用的白名单
# 直接拿来做 strm 检查，每个 `xxx.zh.srt` 都会被判成「疑似上传异常」——
# 必然误报，且数量通常多于视频本身。这是 v0.1.7 主动扫描的真实缺陷。
# Subtitles never get a .strm; reusing the sync whitelist makes every subtitle a
# false suspect. Kept as a separate, explicit list rather than "sync list minus
# subtitles", because a user may add non-video extensions to the sync list.
STRM_VIDEO_EXTENSIONS = (
    "mp4,mkv,ts,iso,rmvb,avi,mov,mpeg,mpg,wmv,3gp,asf,m4v,flv,m2ts,tp,f4v"
)

# 「不值得进入 strm 交叉验证」的两种原因**码**。
#
# 为什么用码而不是直接拿中文文案去分支：文案是给人看的，随时可能改；
# 一旦调用方靠 `"非视频" in reason` 这类匹配来分支，改一次措辞就会让分支静默失效
# （那正是「跳过计数突然全为零」这类难查回归的来源）。码负责判定，文案只管日志。
# Skip reasons as codes, kept apart from the human-readable text so that rewording a
# message can never silently change a branch.
#
# ⚠️ 放在 constants.py 而不是 strm_ops.py：`test_split_contract.test_mixins_are_stateless`
# 禁止 Mixin 模块出现**任何**模块级赋值（宿主按实例重建命名空间时，模块级可变状态
# 会被分身共用），常量按拆分约定一律归本模块，再由协作方显式导入。
# These live here, not in the mixin module: the split contract forbids module-level
# assignments there, and constants belong in this module by the stage-1 split rule.
SKIP_NON_VIDEO = "non_video"          # 字幕/图片/元数据：永远不会有 .strm
SKIP_NO_STRM_DIR = "no_strm_dir"      # 所属映射未配置 strm 目录：验证前提不存在

# ---- 借道 strm 助手补生成 / delegating strm generation to the helper plugin ----
# 「疑似上传异常」有两种成因，处理成本差三个数量级：
#   a) strm 插件自身漏生成 —— 云端文件其实是好的，重新生成一次指针文件即可
#   b) CD2 改名失败假成功 —— 云端只有 `..xxx` 半成品，必须删旧重传
# 两者在插件本地视角**完全无法区分**，但可以花一次「让 strm 助手遍历云端目录」的
# 代价来判别：生成成功 ⇒ 是 a，省下整轮删除重传；仍没有 ⇒ 是 b。
# The two causes of a "suspect" are indistinguishable locally, but a single
# helper-side sweep discriminates them: success ⇒ (a), still absent ⇒ (b).
#
# 助手插件名与其命令（宿主命令表里的注册名，见其 get_command）。
# 命令走 EventType.CommandExcute 由**宿主**解析后转发，本插件不直接调用其内部方法：
# 内部方法签名属于实现细节，跨插件耦合会在对方升级时静默失效。
# We dispatch through the host command bus rather than calling the helper's
# internals, so an upgrade on their side cannot silently break us.
P115_STRM_HELPER_PLUGIN = "P115StrmHelper"
P115_STRM_COMMAND = "/p115_strm"

# ⚠️ 助手**只认** full_sync_strm_paths 这一个字段做参数匹配，别再去找别的。
# 实证：p115strmhelper/__init__.py 的 p115_strm 只把该字段传给
# PathUtils.get_p115_strm_path；monitor_life_paths / increment_sync_strm_paths
# 里的目录传过去一律匹配失败（助手回「路径匹配错误」），不会报错到本插件这边，
# 表现是「命令发出去了但什么都没发生」。
# 早先本模块按「多来源更保险」写了三级回退 —— 方向恰好相反：多出来的两个来源
# 只会让本插件以为可用、实际必然失败。这是凭推测写机制的又一例（见 TODO 3.8.1）。
# Only this field is used by the helper to validate the argument. The other two
# fields look like useful fallbacks but always fail; keeping them would make the
# button appear to work while nothing happens.
P115_PAN_MAPPING_FIELD = "full_sync_strm_paths"

# 单次补生成最多涉及多少个**不同目录**。
#
# 为什么按目录数而不是文件数限：助手收到的每个参数都会让它遍历该目录的整个云端
# 子树（不是只处理那一个文件），所以真实成本 ≈ 遍历到的文件总数，而目录数正是它的
# 主因。逐目录去重后，20 个散落在 15 个季节目录的疑似只产生 15 次小规模遍历，
# 远小于遍历整个媒体库。超过上限说明疑似条目已呈全局散布，此时继续逐目录触发
# 开销反而超过一次整库遍历 —— 应当由用户明确决策，而不是插件自动放大访问量。
# Capped by *directory* count, not file count: each argument makes the helper walk
# that entire cloud subtree, so the directory count drives the real cost.
STRM_GEN_DIR_LIMIT = 20

# 补生成期间该条目的去向：从疑似清单移回「待观察」并重新计时。
# strm 助手是异步长任务，插件侧拿不到完成回调；重新计时可以复用已有的巡检状态机
# （strm 出现 ⇒ 自动解除；窗口到仍无 ⇒ 回到疑似清单，且此时判定更硬 ——
# 生成动作已经做过而仍然没有，基本可以确定是云端真缺文件），用户也能顺手用
# 「检查 strm」按钮即时查看结果，而不必手动刷新去猜。
# Re-arming the existing watch reuses the whole state machine instead of adding a
# second, parallel polling path.
#
# ⚠️ 移动的时机是「命令**确实发出**之后」，不是「收到请求时」。顺序写反会让助手
# 拒收的条目也从清单里消失（用户实测过），详见 _api_strm_generate 里的说明。
# The move happens only after the command is actually sent: doing it on request made
# entries vanish even when the helper rejected the path outright.
#
# ⚠️ 重新计时的窗口用的是 strm.REGRACE_HOURS，**不是**宽限期配置值 —— 两者
# 度量的是不同的延迟（刮削入库 vs 助手遍历云端目录），见 strm.py 的说明。
#
# ⚠️ 「已补生成过」**不记为新的 origin**：它与来源是正交的两个维度，
# 见 strm.py 顶部的说明。状态由插件实例上的 _strm_gen_requested 单独承载。

# 本插件侧显式配置的「网盘目录」映射对（每行 `本插件映射名#网盘目录`）。
# sync_pairs 里对应映射的 `pan_dir` 字段填了值就优先用它。
#
# 为什么必须支持显式配置（而不是全靠反查助手配置）：
#   1. 助手那边可能压根没为这个目录做全量映射（用户实机：9KG 只在
#      monitor_life_paths 里，而助手只认 full_sync_strm_paths），自动反查
#      永远够不着 —— 此时本插件用户会看到「补生成」对 9KG 完全不可用；
#   2. 反查依赖的是对方配置的**字段名与格式**，属实现细节，对方改名即静默失效；
#   3. 网盘目录与本地 strm 目录**不必同构**（助手侧 `本地#网盘` 是两棵独立的树），
#      从本地路径推导网盘路径在原理上就是不牢靠的。
# Explicit per-pair cloud dir: the helper's config cannot be relied upon as the
# only source, both because it may simply not cover the directory and because
# deriving a cloud path from a local one assumes the two trees are isomorphic.
P115_PAN_DIR_HINT = (
    "请在上方目录映射中为该映射填写「网盘目录」"
    "（助手 /p115_strm 只接受它 full_sync_strm_paths 里存在的网盘路径）"
)
