"""
strm 交叉验证的纯逻辑（路径推导与三态流转判定）。

Pure logic for strm cross-validation: expected-path derivation and the
three-state transition decision. **No I/O, no persistence** — the plugin instance
supplies the directory listings and stores the resulting state.

为什么需要这个功能见 DEVELOPMENT.md 3.11 / 4.5：CD2 改名失败后挂载视图会把
目标文件显示成「存在且大小正常」，对账与 `--size-only` 都被蒙蔽；strm 插件
生成的 .strm 依据与 CD2 无关，是独立见证人，且读取它只是本地文件操作。

Why: after a CD2 rename failure the mount view reports the file as present and
correctly sized, blinding both the audit and `--size-only`. The .strm produced by
a strm plugin is an independent witness and is read purely locally.
"""

import os
import posixpath
from typing import Any, Dict, List, Optional, Tuple

# 观察期状态。前三个构成用户可见的三态生命周期，后两个是**清理出口**：
# 它们同样移出待观察清单，但原因不同，必须分开返回 —— 早先把两者与
# SETTLED 合并成一个状态，会让巡检日志里的「正常」计数把「源端已删」
# 也算进去，排查时看不到真正的清理规模。
# States. The first three are the user-visible lifecycle; the last two are cleanup
# exits that must stay distinguishable or the sweep log over-reports "normal".
WATCHING = "watching"          # 待观察：同步成功已登记，宽限期内不报警
SUSPECT = "suspect"            # 疑似异常：宽限期到期仍未生成 strm
SETTLED = "settled"            # 已解除：strm 已生成（正常出口）
NO_STRM_DIR = "no_strm_dir"    # 清理：该映射被改成没有 strm_dir，观察已无意义
SOURCE_GONE = "source_gone"    # 清理：源端文件已消失，无从验证也无从重传
# 清理：**非视频文件**（字幕/图片/元数据）不可能有 .strm。与上面两个清理出口
# 分开命名，是因为成因完全不同 —— 前两者是「验证前提消失」，这条是「判据本身
# 就不适用于该文件」。合并计数会让排查时看不到「清单里混了非视频」这一独立问题。
# Cleanup: the file kind can never have a .strm at all. Kept distinct from the other
# two cleanup exits because the cause differs — this one means the criterion itself
# never applied to the file.
NOT_WATCHABLE = "not_watchable"

# 宽限期下限（小时）。防止 0 值把「上传中/刮削中」直接判成异常。
# Lower bound on the grace window, so a 0 value cannot turn "still uploading"
# into a false alarm.
MIN_GRACE_HOURS = 0.5
DEFAULT_GRACE_HOURS = 6.0

# 补生成（请 strm 助手重生成指针文件）后的重新计时窗口（小时）。
#
# 为什么**不沿用**宽限期的配置值：两者度量的是完全不同的东西。
# 宽限期量的是「rsync 已报成功 → strm 出现」的刮削/入库传播延迟；
# 而补生成的等待对象是助手的一次**云端目录遍历**，跟这个配置毫无因果。
# 用户把宽限期调大（比如 24h）的理由是「我的刮削很慢」，不该连带让补生成
# 之后的结果在半天内不可判定 —— 那才是真的把功能调坏了。
# 反过来取一个小的固定值，代价只是「稍早一点给出结果」，而且结果会即时
# 覆盖读取：已生成就直接解除，无需等窗口结束（见 watch_state_of）。
# A separate, fixed window: the configured grace measures scrape/ingest lag, not
# the helper's directory walk, so reusing it would make a "slow scraping" setting
# silently cripple the regenerate feature.
REGRACE_HOURS = 1.0


def expected_path(key: str, pairs: List[Dict[str, Any]]) -> Optional[str]:
    """
    由队列 key 推导「应当生成」的 .strm 绝对路径；该映射未配 strm_dir 时返回 None。

    Derive the expected .strm path for a queue key; None when the owning pair has no
    strm_dir configured. 规则：与整理后的文件同名、目录结构一致，仅扩展名换成 .strm
    （`A/B/剧名 S01E03.mkv` → `strm根/A/B/剧名 S01E03.strm`）。
    """
    from .paths import pair_name as _pair_name
    for pair in pairs:
        pn = _pair_name(pair)
        if not pn or not key.startswith(f"{pn}:"):
            continue
        strm_dir = (pair.get("strm_dir") or "").strip().rstrip("/")
        if not strm_dir:
            return None
        rel_p = key.split(f"{pn}:", 1)[1]
        stem, _ = os.path.splitext(rel_p)
        return os.path.join(strm_dir, stem + ".strm")
    return None


def source_root_of(key: str, pairs: List[Dict[str, Any]]) -> Optional[str]:
    """队列 key 所属映射的源端根目录；无法归属时返回 None。"""
    from .paths import pair_name as _pair_name
    for pair in pairs:
        pn = _pair_name(pair)
        if pn and key.startswith(f"{pn}:"):
            return (pair.get("src") or "").strip().rstrip("/") or None
    return None


def classify_watch(key: str, synced_ts: float, now_ts: float, grace_secs: float,
                   pairs: List[Dict[str, Any]], strm_exists: bool,
                   src_exists: bool) -> Tuple[str, Optional[str]]:
    """
    对单个「待观察」条目做一次状态判定。

    Decide the next state of one watching entry.

    调用方负责提供两个**已经探测好**的布尔值（strm 是否已生成、源端是否还在），
    本函数因而保持纯函数：不碰文件系统、可被单测穷举。这是刻意的设计 ——
    三态流转的边界（恰好到期、源端消失、映射被改）最容易写错，必须可测。
    The caller probes the filesystem and passes booleans in, keeping this pure and
    unit-testable: the transition boundaries are exactly where bugs hide.

    返回 (状态, 应当记录到的 key 或 None)。除 WATCHING/SUSPECT 外第二个值均为
    None，因为清理与解除都不需要保留记录。

    判定顺序**是承重的**，与拆分前保持一致：映射失效 → 源端消失 → strm 已生成
    → 是否到期。举例：源端文件已删、而 strm 恰好还在，应当按「源端消失」处理
    （验证已无意义），而不是记成一次正常解除。顺序写反不会有功能故障，
    但会让巡检计数长期失真。
    The check order is load-bearing and matches the pre-split behaviour.
    """
    expected = expected_path(key, pairs)
    if expected is None:
        return NO_STRM_DIR, None
    if not src_exists:
        return SOURCE_GONE, None
    if strm_exists:
        return SETTLED, None
    if now_ts - synced_ts >= grace_secs:
        return SUSPECT, key
    return WATCHING, key


def regrace_secs(gen_requested_ts: Any, now_ts: float) -> float:
    """
    补生成之后的重新计时窗口：请求时刻 → 请求 + REGRACE_HOURS 之间的剩余秒数。

    Seconds left in the post-request regrace window; <= 0 once it has elapsed.

    ⚠️ **以请求时刻为基准，不是「此刻 + 窗口」**。若按后者，每看一次都顺延一次，
    条目就永远不会到期 —— 用户看到的是一条无限停留在「观察中」的记录。
    看板每 30 秒刷新一次状态，这个错误会立刻显形为「怎么等都不出结果」，
    而且越看越久。
    Anchored to the request timestamp, never to "now": re-anchoring on every read
    would push the deadline forward forever and the entry could never resolve.

    已生成（SETTLED）的情形根本不会走到这里，所以窗口到期只是**下界**——
    助手快的时候结果会在下一轮巡检就出来。
    """
    try:
        base = float(gen_requested_ts)
    except (TypeError, ValueError):
        base = now_ts
    return base + REGRACE_HOURS * 3600 - now_ts


def watch_state_of(key: str, watch: Dict[str, Any],
                   gen_requested: Dict[str, Any], now_ts: float) -> Tuple[str, float]:
    """
    判定某个观察期条目的**计时基准**，返回 (基准种类, 基准时间戳)。

    Decide which clock an observation entry is running on: ("sync"|"gen", ts).

    ⚠️ 这不是可有可无的细节，而是两处显示分歧的来源。补生成把条目从疑似清单
    移回观察期后，它的登记时刻来自 `gen_requested`（请求那一刻），**不是**
    `watch` 里的同步成功时刻。若显示端仍拿同步时刻去算剩余时间，用户会看到
    「入口 A 说还要等 5 小时、入口 B 说已到期」—— 两边算的都不是同一个钟。
    The display side and the sweep must resolve the clock the same way, or the same
    entry shows two different remaining times depending on where it is looked at.

    `gen_requested` 无记录时返回同步时刻；两个字典都缺（正常巡检不会出现，
    因为循环就是遍历 watch 的键）时退回 now_ts，保证宽限期内不会误判。

    ⚠️ 坏时间戳（null、字符串、被手工改坏的 JSON）一律**退回 now_ts**，绝不抛
    异常：这两个字典直接来自持久化文件，而调用点散布在巡检、手动检查、看板
    状态三处 —— 任何一处抛异常，代价分别是「整轮巡检中断」「按钮点了报错」
    「整个看板打不开」，而原因只是一个条目的时间戳格式不对。
    取值失败时按「刚登记」处理（而非 0 → 立即到期），与 classify_watch 的兜底
    同一取向：宁可多留一轮，也不要把坏数据变成一次「上传异常」误报。
    """
    if key in gen_requested:
        return "gen", _ts_or(gen_requested[key], now_ts)
    if key in watch:
        return "sync", _ts_or(watch[key], now_ts)
    return "sync", now_ts


# 「目标端探测」的结论。四个取值都要能被调用方区分开，理由见 dest_probe_outcome。
DEST_OK = "ok"                    # 可见、大小一致、**且目录里没有残留** → 文件是好的
DEST_SIZE_MISMATCH = "mismatch"   # 可见但大小不符 → 传到一半
DEST_ABSENT = "absent"            # 不可见 → 云端没有正式文件
DEST_UNKNOWN = "unknown"          # 探测无效（挂载未就绪 / 源端没了 / 读不到大小）
# 可见、大小一致，**但同目录里存在该文件的残留**（形如 `影片.mkv..xrp4gj`）。
#
# 为什么必须与 DEST_OK 分开：`--size-only` 的判据只有大小，而改名失败的残留
# 大小与正式文件**完全一致**（3.10 实测），所以「大小一致」对改名失败这个
# **主成因**毫无鉴别力 —— 它一直是假阳性。而 CD2 改名失败时正式名根本不存在，
# 挂载视图里那个「正式名」其实是视图过期；`os.listdir` 则是直读目录内容，
# 能同时看到残留与改名失败的痕迹。有残留 ⇒ 「文件已完整落地」这个结论不成立。
# Same size but a residue exists: since --size-only compares size alone and a
# rename-failure residue is byte-identical in size, "same size" never discriminated
# this case. A residue means the final rename did not complete.
DEST_RESIDUE = "residue"


def dest_probe_outcome(dest_size: Optional[int], src_size: Optional[int],
                       dest_missing: bool, residue_found: bool = False) -> str:
    """
    把一个文件的「目标端可见性探测」折算成结论。

    Turn one file's destination-visibility probe into a verdict.

    **为什么需要它**：补生成之后仍无 strm 时，本地视角分不出四种成因，用户只能
    自己猜「到底云端有没有这个文件」。而目标端是 CD2 挂载点 —— 读它的大小是
    **纯本地调用、零 115 API**，这一步探测能把其中三种直接分开：

    | 探测结果 | 云端情况 | 该不该删旧重传 |
    |---|---|---|
    | 不可见 | 没有正式文件（从未传成功 / 改名失败只剩残留） | ✅ 正确（且删除是空操作） |
    | 大小不符 | 传到一半 | ✅ 正确 |
    | 大小一致 | 文件是好的（rsync 会跳过） | ⚠️ **纯属白删**，且 rsync 照样跳过 |

    **⚠️ 它只能用来「排除删旧重传」，绝不能当作「已同步」的证据。**
    3.11 记录的「CD2 假成功」正是：挂载视图显示大小正常，而 115 上只有改名
    失败的残留（残留大小与正式文件完全一致，见 3.10 —— 用大小根本分不出来）。
    也就是说本函数最右边那一列的「大小一致」有一个已知的假阳性方向：
    它会把「改名失败 + 视图过期」误判成「文件完好」。
    这个方向的错误**只导致「建议你先别删」**，代价是多查一次助手，可接受；
    反过来若拿它去触发删除或跳过上传，就会真的漏掉坏文件 —— 因此调用方
    只允许用它做「不要动手」的建议，不允许用它做「已经好了」的结论。
    Only safe for the "don't delete" direction: the fake-success case makes
    "same size" optimistic, and optimistically skipping work is harmless only
    when the work skipped is a deletion.

    参数用 `None` 表达「读不到」，而不是布尔值：`os.path.getsize` 在挂载点抖动时
    会抛 OSError，把它压成 False 会与「确实不存在」混为一谈。
    "Unreadable" is expressed as None rather than collapsed into a boolean, because
    a flaky mount and a genuinely absent file must not look the same.

    ⚠️ **`same_size` 不等于「文件没事」** —— 这正是本函数存在的理由。
    `--size-only` 只看大小，而改名失败的残留大小与正式文件完全一致，
    「大小一致」对改名失败这个主成因毫无鉴别力。因此真正的判据是
    `residue_found`：**同目录里有该文件的残留 ⇒ 最后一次改名没有完成**，
    此时无论大小是否一致都不能得出「云端是好的」。
    Same size proves less than it looks: a rename-failure residue is byte-identical
    in size, so the discriminating input is whether a residue exists at all.

    ⚠️ 分支顺序**是承重的**（与 3.10 排查时的第一版不同：那时只有大小一个维度，
    8 种组合枚举过重排等价；加了残留维度后不再等价，别再按那条结论推理）。
    残留判定必须先于大小判定：残留存在时大小必然「一致」（它就是从正式文件改名
    失败来的），若先判大小就会返回 DEST_OK 把坏文件判成好的。
    Branch order is load-bearing now: the residue check must precede the size check.
    """
    if dest_missing:
        # ⚠️ 残留不算「正式文件存在」：残留的命名不是正式名。
        # 但**挂载视图可能连残留都看不到**（它只认正式名），所以这里不因残留
        # 改判 —— 不可见就是不可见，删旧重传本来就是对症处置。
        return DEST_ABSENT
    if dest_size is None or src_size is None:
        return DEST_UNKNOWN
    if residue_found:
        return DEST_RESIDUE
    return DEST_OK if dest_size == src_size else DEST_SIZE_MISMATCH


def dest_path_of(key: str, pairs: List[Dict[str, Any]]) -> Optional[str]:
    """
    队列 key → 目标端（CD2 挂载内）对应文件的绝对路径；无法归属时返回 None。

    Map a queue key to its absolute destination path on the CD2 mount.

    与 `_delete_dest_files_for_retry` 的构造口径一致（同样按映射名前缀归属、
    同样 `dest` 根 + 相对路径），但不做任何删除动作 —— 这里只是读。
    """
    from .paths import pair_name as _pair_name
    for pair in pairs:
        pn = _pair_name(pair)
        if pn and key.startswith(f"{pn}:"):
            dest_root = (pair.get("dest") or "").strip().rstrip("/")
            if not dest_root:
                return None
            rel = key.split(f"{pn}:", 1)[1].lstrip("/")
            if not rel:
                return None
            return posixpath.join(dest_root, rel)
    return None


def dest_root_of(key: str, pairs: List[Dict[str, Any]]) -> Optional[str]:
    """队列 key 所属映射的目标端根目录；无法归属时返回 None。

    The mapping's destination root — used as the mount-readiness probe: if even the
    root is unreadable the whole verdict set must degrade to DEST_UNKNOWN.
    """
    from .paths import pair_name as _pair_name
    for pair in pairs:
        pn = _pair_name(pair)
        if pn and key.startswith(f"{pn}:"):
            return (pair.get("dest") or "").strip().rstrip("/") or None
    return None


def _ts_or(value: Any, fallback: float) -> float:
    """把可能是 null / 字符串 / 任意对象的持久化时间戳解析成 float，失败即兜底。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def grace_secs_of(grace_hours: Any) -> float:
    """宽限期（小时）→ 秒，并施加下限，防止 0/负数把上传中的文件判成异常。"""
    try:
        hours = float(grace_hours)
    except (TypeError, ValueError):
        hours = DEFAULT_GRACE_HOURS
    return max(MIN_GRACE_HOURS, hours) * 3600


# 疑似来源标记。主动扫描与同步后观察的判据不同、可信度也不同，必须在数据里
# 分开记录，否则用户看到一堆疑似却不知道「为什么突然多出来这些」。
# Suspect origins. A proactive scan and a post-sync watch have different criteria
# and different confidence, so the origin must be recorded with the entry.
ORIGIN_WATCH = "watch"      # 同步成功后观察到期仍未生成（可信度高：该文件确实传过）
ORIGIN_SCAN = "scan"        # 主动扫描发现源端有、strm 端没有（**可能是从未上传过**）
# 第三种 origin：**用户在看板上确认了该文件没传上去**（例如在 115 里亲眼看到
# 只有改名失败的残留），因此越过重新计时的窗口直接入清单。
#
# 为什么必须单独记一个 origin，而不是复用 watch/scan：它是唯一一条「结论来自
# 人而不是探测器」的入口，而下游的删旧重传守卫要凭这个区别决定放不放行 ——
# CD2 挂载视图「可见且大小一致」的已知假阳性，只有当事人的确认能推翻。
# 混用 origin 会让守卫再也分不出「机器觉得没问题」与「人已经确认有问题」，
# 那道人命关天的拦截就只能二选一：要么永不放行（用户被卡死），要么一律放行
# （坏文件被静默放过）。
#
# 之所以敢让它越权，是因为它**不绕过任何数据护栏**：key 仍必须在观察清单里
# （用户只能对插件已经盯着的文件下这个结论，不能凭空构造路径），删除仍走
# 相对路径精确对齐（_delete_dest_files_for_retry 的三道闸），重传正常入队。
ORIGIN_CONFIRMED = "confirmed"
# 注：「已补生成过」这一状态**没有**做成第三种 origin。
# 它是与来源正交的一个维度（watch 与 scan 都可能被补生成过），硬塞进 origin
# 会让两个维度互相覆盖。改用实例上的 _strm_gen_requested 字典单独记录，
# 看板据此显示「补生成无效」。origin 仍保持二元语义。
# "Already asked the helper" is deliberately NOT a third origin: it is orthogonal to
# provenance, so it lives in its own dict on the instance.


def _path_parts(path: Optional[str]) -> Tuple[str, ...]:
    """把绝对路径拆成非空分量元组，供逐分量比较（绕开字符串前缀的陷阱）。"""
    return tuple(p for p in str(path or "").strip().rstrip("/").split("/") if p)


def is_under_any(path: str, roots: List[str]) -> bool:
    """
    判断某个路径是否落在给定的任一根目录之下（**逐路径分量**比较）。

    Whether `path` lies under any of `roots`, compared on path boundaries.

    ⚠️ 不能用字符串 `startswith`：`/HomeTheater/TV2` 会被 `/HomeTheater/TV`
    误判为「在其之下」，从而放行一条助手其实会拒绝的路径 —— 与本模块其它
    路径判定同一条教训（见 paths.pair_for_path）。
    Plain startswith would let "/HomeTheater/TV" swallow "/HomeTheater/TV2".
    """
    target = _path_parts(path)
    if not target:
        return False
    for root in roots:
        root_parts = _path_parts(root)
        if root_parts and target[: len(root_parts)] == root_parts:
            return True
    return False


def parse_pan_mappings(raw: Any) -> List[Tuple[str, str]]:
    """
    解析助手配置里的映射串（换行分隔的 `本地目录#网盘目录[#标记]`）。

    Parse the helper's newline-separated `local#cloud[#flag]` mapping string.

    ⚠️ **仅用于发送前预检**，绝不用于推导参数 —— 参数只能来自用户在本插件里
    显式配置的 pan_dir（理由见 pan_dir_of）。行尾的 `#0`/`#1` 标记只是助手
    对「是否参与全量」的取舍，不影响该路径是否被接受，故此处丢弃。
    Used for pre-flight validation only, never to derive the parameter. The trailing
    `#0`/`#1` flag governs the helper's own full-sweep policy, not path acceptance.
    """
    mappings: List[Tuple[str, str]] = []
    for line in str(raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("#", 2)
        if len(parts) < 2:
            continue
        local_root, pan_root = parts[0].strip(), parts[1].strip()
        if local_root and pan_root:
            mappings.append((local_root, pan_root))
    return mappings


def pan_dir_of(key: str, pairs: List[Dict[str, Any]]) -> Optional[str]:
    """
    取队列 key 所属映射配置的**网盘目录**（用户在本插件里显式填的），未配置返回 None。

    The cloud directory the user configured for this mapping, or None.

    为什么必须由用户显式配置，而不是从助手的配置反查：
      1. **助手侧未必有这个目录的映射** —— 实证：用户实机 9KG 只出现在助手的
         `monitor_life_paths` 里，而 `/p115_strm` 只认 `full_sync_strm_paths`，
         自动反查出来的路径发过去必然匹配失败（见 constants.P115_PAN_MAPPING_FIELD）。
      2. 反查依赖对方配置的字段名与格式，属**实现细节**，对方改名即静默失效。
      3. 两棵树**不必同构**：本地 strm 目录与 115 网盘目录是独立的两个根，
         「本地路径减去前缀 = 网盘路径」在原理上就不成立，只是碰巧在规整的
         配置里看起来对。
    The mapping is explicit because none of the automatic derivations are sound: the
    helper may not cover the directory at all, the field names are their internals,
    and the two trees are not required to be isomorphic.
    """
    from .paths import pair_name as _pair_name
    for pair in pairs:
        pn = _pair_name(pair)
        if pn and key.startswith(f"{pn}:"):
            return (pair.get("pan_dir") or "").strip().rstrip("/") or None
    return None


def gen_target_of_key(key: str, pairs: List[Dict[str, Any]]) -> Optional[str]:
    """
    单个疑似文件对应的助手参数（**目录**），无法归属时返回 None。

    The helper argument (a directory) for one suspect key, or None if unattributable.

    与 `gen_targets_for_suspects` 共用同一份推导：调用方在命令发出后要用它反查
    「哪些 key 命中了成功发出的目录」，两处若各写一遍，一旦推导规则改动
    （例如空格折叠的判据）就会出现「命令发了 A 目录、却被认为覆盖了 B 目录的文件」。
    Shared with the batch builder so the post-send reverse lookup can never disagree
    with what was actually derived and sent.
    """
    # 用前缀匹配还原相对路径（任务名可含冒号，split(":", 1) 会切错）；
    # 无法归属时退回原 key —— 下方 pan_dir_of 同样会返回 None，最终结果一致。
    from .paths import rel_path_of_key as _rel_path_of_key
    rel = _rel_path_of_key(key, pairs) or key
    pan_root = pan_dir_of(key, pairs)
    if not pan_root:
        return None
    # 相对路径里的目录部分（去掉文件名）拼到网盘根下 —— 只把参数收窄到
    # 该文件所在的季/集目录，不上升为整个映射根。
    rel_dir = posixpath.dirname(rel)
    target = posixpath.join(pan_root, rel_dir) if rel_dir else pan_root
    # ⚠️ 命令通道对「连续空格」不是无损的：宿主把命令串按空白切分后再用单个
    # 空格拼回 args（command.py: `cmd.split()[0]` / `" ".join(...)`），因此
    # `/TV/剧  名` 到达助手时会变成 `/TV/剧 名`，路径匹配失败。而失败消息只
    # 发给助手侧的用户、本插件收不到 —— 表现为「点了按钮什么都没发生」。
    # 这类路径宁可明确列为未处理，也不要发一条注定失败的假命令。
    # The host splits the command line on whitespace and rejoins with single
    # spaces, so runs of spaces inside a directory name are collapsed and the
    # path silently stops matching on the helper side.
    if target != " ".join(target.split()):
        return None
    return target


def gen_targets_for_suspects(keys: List[str], pairs: List[Dict[str, Any]],
                             limit: int) -> Tuple[List[str], List[str], List[str], bool]:
    """
    把疑似文件的 key 折算成「请助手生成 strm」的网盘**目录**参数列表。

    Turn suspect keys into the list of cloud directories to hand to the helper.

    返回 (目录参数, 已归属目录的 key, 无法归属的 key, 是否因上限被截断)。

    ⚠️ **必须传目录，不能传文件**。实证（用户实机 2026-08-17 的助手日志）：
    传文件路径时助手会打印「网盘媒体目录 ID 获取成功: .../杀手妈咪 S01E05.mkv」，
    然后生成 **0 个** STRM 文件 —— 它拿到的 ID 指向文件本身，其下没有可遍历的
    内容。而传目录时（2026-08-13 日志）正常生成 6 个。传文件不会报错，只是
    静默什么也不做，是最难排查的一类失败。
    Pass directories, never files: a file path yields a "directory ID" that contains
    nothing to iterate, and the helper silently generates zero files.

    ⚠️ 命中上限时**不能只丢掉多余的文件**：它们仍在疑似清单里，用户会看到
    「点了按钮但一部分毫无动静」。必须把「哪些已纳入、哪些被截断」分开回传，
    让调用方给出明确提示（或干脆在此前就拒绝执行）—— 静默遗漏是最坏的结果，
    因为用户会以为整批都处理过了，从而不再关注那些条目。
    When the cap is hit the dropped keys are returned explicitly rather than
    silently discarded, so the caller can tell the user which batch was skipped.

    逐目录去重的理由见 constants.STRM_GEN_DIR_LIMIT：助手对每个参数都会遍历
    整个云端子树，所以按**目录**去重才是真正的成本控制（20 个文件散在 3 个
    季节目录 ⇒ 3 次小遍历，而不是 20 次，更不是整库一次）。
    De-duplicating by directory (not by file) is what keeps the helper's cloud
    traversal bounded.
    """
    ordered_dirs: List[str] = []
    seen_dirs = set()
    matched_keys: List[str] = []
    unmatched: List[str] = []
    truncated = False

    for key in keys:
        target = gen_target_of_key(key, pairs)
        if target is None:
            unmatched.append(key)
            continue
        if target not in seen_dirs:
            if len(ordered_dirs) >= limit:
                # 目录数超限：本文件与后续文件都不再纳入，并置截断标志。
                truncated = True
                unmatched.append(key)
                continue
            seen_dirs.add(target)
            ordered_dirs.append(target)
        matched_keys.append(key)

    return ordered_dirs, matched_keys, unmatched, truncated


def scan_candidates(pairs: List[Dict[str, Any]], list_dir, limit: int,
                    excluded_dirs=None, valid_exts_for=None) -> Tuple[List[str], bool, int]:
    """
    主动扫描：找出「源端存在、但对应 .strm 不存在」的文件。

    Proactive sweep: find files whose own .strm has not appeared.

    ⚠️ **判据的固有歧义**：本函数只能看到「源端有、strm 无」，**无法区分**
      a) 该文件从未上传过（应当走补传，不是异常）
      b) 上传了但 CD2 假成功（这才是要抓的）
    两者的表现完全一样。因此调用方必须把结果标为「疑似」而非「确诊」，
    并在界面与通知里说明这一点 —— 否则用户会把整库未同步的存量当成坏文件。
    The criterion cannot distinguish "never uploaded" from "fake success"; the
    caller must present results as suspects, not conclusions.

    参数列表由调用方注入（list_dir / valid_exts_for），本函数保持纯逻辑：
    不直接读配置、不持有状态，便于单测穷举。

    :param list_dir: 可调用对象，接收目录路径返回文件名列表（失败返回 None）
    :param excluded_dirs: 需要剪枝的目录名集合（@eaDir 等）
    :param valid_exts_for: 接收 pair 返回扩展名白名单或 None 的可调用对象
    :return: (候选 key 列表, 是否被截断, 已检查的文件总数)
    """
    import os as _os

    excluded_dirs = excluded_dirs or set()
    candidates: List[str] = []
    truncated = False
    checked = 0

    for pair in pairs:
        src_root = (pair.get("src") or "").strip().rstrip("/")
        strm_dir = (pair.get("strm_dir") or "").strip().rstrip("/")
        if not src_root or not strm_dir:
            continue  # 未配 strm_dir 的映射不参与（与观察模式一致）
        pn = (pair.get("name") or src_root).strip()
        exts = valid_exts_for(pair) if valid_exts_for else None

        for root, dirnames, filenames in _os.walk(src_root):
            dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
            for fn in filenames:
                if exts is not None:
                    if _os.path.splitext(fn)[-1].lstrip(".").lower() not in exts:
                        continue
                checked += 1
                rel_f = _os.path.relpath(_os.path.join(root, fn), src_root)
                stem, _ = _os.path.splitext(rel_f)
                if _os.path.exists(_os.path.join(strm_dir, stem + ".strm")):
                    continue  # strm 存在 → 正常
                candidates.append(f"{pn}:{rel_f}")
                if len(candidates) >= limit:
                    # 达到上限即停：继续扫毫无收益（结果不会保留），只浪费磁盘 IO
                    truncated = True
                    break
            if truncated:
                break
        if truncated:
            break

    return candidates, truncated, checked
