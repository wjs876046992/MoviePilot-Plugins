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

# 宽限期下限（小时）。防止 0 值把「上传中/刮削中」直接判成异常。
# Lower bound on the grace window, so a 0 value cannot turn "still uploading"
# into a false alarm.
MIN_GRACE_HOURS = 0.5
DEFAULT_GRACE_HOURS = 6.0


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


def grace_secs_of(grace_hours: Any) -> float:
    """宽限期（小时）→ 秒，并施加下限，防止 0/负数把上传中的文件判成异常。"""
    try:
        hours = float(grace_hours)
    except (TypeError, ValueError):
        hours = DEFAULT_GRACE_HOURS
    return max(MIN_GRACE_HOURS, hours) * 3600
