"""
路径与目录映射的纯函数工具。

Pure helpers for paths and directory-mapping pairs. **Stateless by design** —
nothing here may hold mutable state, because the host re-executes the source in
a per-instance namespace while imported module globals stay shared (see
docs/Plugin_Development.md 7.4). All state lives on the plugin instance.

本模块只放"给定输入就能算出输出"的函数：不读配置、不写盘、不记日志。
"""

import os
from typing import Any, Dict, List, Optional, Tuple

from .constants import MAX_LOGGED_PATHS, MAX_PATH_CHARS


def brief_paths(paths: List[str]) -> str:
    """
    把路径列表压缩成适合写进单行日志的短串。

    Compact a path list into a single-line log fragment: cap the number of
    entries and truncate each path, so logs stay readable and bounded.
    """
    shown = []
    for path in paths[:MAX_LOGGED_PATHS]:
        text = str(path)
        if len(text) > MAX_PATH_CHARS:
            text = "…" + text[-MAX_PATH_CHARS:]
        shown.append(text)
    suffix = f" 等共 {len(paths)} 个" if len(paths) > MAX_LOGGED_PATHS else ""
    return "; ".join(shown) + suffix


def pair_name(pair: Dict[str, Any]) -> str:
    """
    取映射对的展示名：优先用户填的备注名，回退到源目录路径。

    Display name of a mapping pair: the user-supplied label, falling back to the
    source root. **Use this instead of open-coding the fallback** — the expression
    用户名 or src 曾在本文件外重复出现 9 次，只要有一处写成 `src`（未 rstrip("/")）
    或漏掉 `.strip()`，同一个文件就会在不同代码路径下归属到不同的 key 前缀，
    表现为「事件入了队但同步时找不到它」这类极难定位的问题。
    This exact fallback used to be open-coded in 9 places; a single variant that
    forgot to strip trailing slashes would make the same file resolve to two
    different key prefixes depending on the code path.
    """
    name = (pair.get("name") or "").strip()
    if name:
        return name
    return (pair.get("src") or "").strip().rstrip("/")


def src_root(pair: Dict[str, Any]) -> str:
    """映射的源端根目录（已 rstrip("/")），统一定义避免各处以不同形式出现。"""
    return (pair.get("src") or "").strip().rstrip("/")


def dest_root(pair: Dict[str, Any]) -> str:
    """映射的目标端（CD2 挂载）根目录（已 rstrip("/")）。"""
    return (pair.get("dest") or "").strip().rstrip("/")


def split_pair_key(key: str, pairs: List[Dict[str, Any]]) -> Optional[tuple]:
    """
    把队列 key（形如 `任务名:相对路径`）还原成 (pair, 相对路径)。

    Resolve a queue key of the form `pair_name:relative/path` back to
    (pair, relative path). Returns None when the key belongs to no known pair.

    为什么按前缀匹配而不是 split(":")：任务名里可能含冒号，相对路径里
    也可能含冒号（罕见但合法），只有「已知映射名 + 冒号」的前缀匹配才可靠。
    早先 `_delete_dest_files_for_retry` 等处各自实现了一遍这段逻辑，
    任意一处顺序写反就会把文件判给错误的映射 —— 而那是**删除操作**的输入。
    Prefix matching against known pair names is the only reliable form: both the
    label and the relative path may legitimately contain a colon. This logic was
    previously open-coded at several destructive call sites.
    """
    for pair in pairs:
        pn = pair_name(pair)
        if pn and key.startswith(f"{pn}:"):
            return pair, key.split(f"{pn}:", 1)[1]
    return None


def rel_path_of_key(key: str, pairs: List[Dict[str, Any]]) -> Optional[str]:
    """
    把队列 key 还原成**相对路径**；无法归属到任何已知映射时返回 None。

    Resolve a queue key back to its relative path, or None when unattributable.

    为什么必须存在这个函数，而不是各处写 `key.split(":", 1)[1]`：
    `split(":", 1)` 在**第一个**冒号处切开，而任务名本身可以含冒号
    （`split_pair_key` 的 docstring 已注明）。任务名形如 `TV:主库` 时，
    key `TV:主库:S01E01.mkv` 被切开得到 `主库:S01E01.mkv` —— 相对路径凭空
    多出一段，用于拼文件系统路径时永远不存在，表现为「文件明明在、却判为
    源端已消失」（strm 条目被判 `source_gone` 清理、可见性探测报 unknown）。

    正解与前缀匹配同源：只有「已知映射名 + 冒号」的前缀匹配才可靠，
    因此这里复用 `pair_name` 逐对比较，与 `split_pair_key` 保持同一判据。

    ⚠️ 多个映射名互为前缀时必须取**最长**匹配：映射 `TV` 与 `TV:主库` 并存时，
    key `TV:主库:S01E01.mkv` 同时满足两者的前缀条件。若按遍历顺序取第一个，
    得到的是 `主库:S01E01.mkv` —— 与 `split(":", 1)` 的错误结果一模一样。
    最长匹配是唯一自洽的解释：越具体的映射名越能解释这个 key。

    Longest-prefix wins: with pairs `TV` and `TV:主库`, the more specific name
    is the only self-consistent interpretation of the key.

    Prefix matching against known pair names is the only reliable form, because
    both the label and the relative path may legitimately contain a colon.
    """
    best_name = ""
    for pair in pairs or []:
        pn = pair_name(pair)
        if pn and key.startswith(f"{pn}:") and len(pn) > len(best_name):
            best_name = pn
    return key[len(best_name) + 1:] if best_name else None


def abs_under(root: str, rel_path: str) -> str:
    """把相对路径拼到根目录下，并同步去掉相对路径的前导斜杠（防 os.path 逃逸）。"""
    return os.path.join(root, (rel_path or "").lstrip("/"))


def excluded_dir_names(exclude_patterns: str) -> set:
    """
    从排除规则文本里抽出「目录名」集合，供 os.walk 就地剪枝。

    Extract the directory-name set from the exclude patterns so os.walk can prune
    in place instead of descending into metadata dirs (@eaDir etc.).

    只认以 `/` 结尾且不以 `.` 开头的规则行，与 rsync 的目录排除语义对齐；
    `.DS_Store` 这类文件规则不属于目录，必须排除在外。
    Only lines ending in `/` and not starting with `.` are directories; file rules
    such as `.DS_Store` must not be pruned as directories.
    """
    return {
        line.strip().rstrip("/")
        for line in (exclude_patterns or "").splitlines()
        if line.strip().endswith("/") and not line.strip().startswith(".")
    }


def is_junk_file_name(name: str) -> bool:
    """
    系统垃圾文件名：macOS 的 `.DS_Store` 与 AppleDouble 资源分叉 `._*`。

    macOS junk: `.DS_Store` and AppleDouble resource forks (`._*`).

    这两种文件在四处的处理口径必须一致（补传前置扫描、双向对账、目录展开、
    all_ext 同目录展开）。原先是在三处各写一遍 `startswith("._") or == ".DS_Store"`，
    任何一处漏写就会表现为「明明排除过的垃圾文件被同步上去了」——
    而它在 115 侧是**真实占用配额**的上传。
    The same predicate used to be open-coded at three sites; one omission means junk
    files get uploaded and actually consume 115 quota.
    """
    text = str(name or "")
    return text.startswith("._") or text == ".DS_Store"


def is_temp_residue_name(name: str, official_name: str) -> bool:
    """
    `name` 是否是 `official_name` 的**传输残留**（改名未完成留下的临时文件）。

    Whether `name` is an aborted-transfer residue of `official_name`.

    rsync 把数据写进 `<目录>/.<正式名>.<6位随机>`，**全部传完后才改名**为正式名
    （本机 rsync 3.4.1 实测：`movie.mkv` → `.movie.mkv.WCTOKM`）。CD2 改名失败时
    这个残留就永久留在云端。判据因此是：「以正式名 + `.` 开头，其余是一个短的
    随机后缀」。

    ⚠️ 为什么必须做这个判据：`--size-only` 只比大小，而残留的大小与正式文件
    **完全一致**（3.10 实测），所以「大小一致」根本区分不出「传完了」与
    「传完了但改名失败」。目录里有没有残留才是能区分的那条证据。
    The size comparison cannot separate "transferred" from "transferred but the final
    rename failed", because the residue is byte-identical in size.

    容忍四种写法（前两种实测，后两种用户报告）：`.影片.mkv.WCTOKM`（rsync 3.4.1
    本机实测的原生形态）、`.影片.mkv.c2Gfr2`、`影片.mkv..xrp4gj`
    （**用户实际看到的形态**，`..` 在正式名之后）、`影片.mkv.xrp4gj`。
    做法是：先剥掉两侧的点再比后缀，而不是逐形态硬编 —— 形态清单永远补不全，
    而「剥点 + 定长随机后缀」对所有已知形态都成立。
    Tolerant of the known spellings by stripping dots instead of enumerating forms.

    **后缀要求恰好 6 位纯字母数字**（rsync 的临时名后缀长度就是 6，用户自己给出的
    正则也是 `[a-z0-9]{6}`），且**不允许是纯小写单词**：
      · `2024` → 长度不符，排除（这类年份后缀在正规命名里很常见）；
      · `backup` → 纯小写单词，排除；
      · `WCTOKM` / `c2Gfr2` / `xrp4gj` → 通过（实测的三种真实形态）。
    最后那条「纯小写单词」规则是权衡出来的：`.backup` 这类名字与随机后缀在形状上
    无法彻底区分，而两种错误方向的代价并不对称 —— 误判成残留最多是让用户对一份
    完好文件多做一次重传（源端还在，重传不会丢数据），漏判则会把坏文件继续挡在
    门外（正是用户反馈的过度保护）。
    Known limitation: a 6-letter lowercase suffix such as `.backup` cannot be told
    apart by shape alone, and the two error directions are not symmetric — a false
    residue costs one redundant re-upload, a missed one keeps the file blocked.
    """
    text = str(name or "")
    official = str(official_name or "")
    if not text or not official:
        return False
    body = text.lstrip(".")
    if not body.startswith(official + "."):
        return False
    tail = body[len(official) + 1:].lstrip(".")
    # ⚠️ 长度必须恰好 6（rsync 临时名后缀的固定长度），不能放宽成区间：
    # 放宽后 `影片.mkv.2024` 这类正常命名会落进判据。
    if len(tail) != 6 or not tail.isascii() or not tail.isalnum():
        return False
    # 纯小写字母（如 backup）看着像词而不像随机串，排除
    return not tail.islower() or any(c.isdigit() for c in tail)


def valid_exts_of(media_extensions: str, all_ext: bool) -> Optional[set]:
    """
    映射的扩展名白名单；`all_ext=True`（同步所有类型）时返回 None 表示不过滤。

    Extension whitelist for a pair; None means "no filtering" when the pair is set
    to sync every file type. Returning None rather than an empty set is deliberate:
    an empty set would silently filter out *every* file.
    """
    if all_ext:
        return None
    return {x.strip().lower() for x in (media_extensions or "").split(",") if x.strip()}


def ext_of(file_path: str) -> str:
    """
    取小写扩展名（不含点）；无扩展名返回空串。

    Single exit point for extension extraction. It used to be open-coded at four
    sites; one omission of `.lower()` means the same file is accepted on one path
    and dropped on another.
    """
    return os.path.splitext(str(file_path))[-1].lstrip(".").lower()


def valid_extension(pair: Dict[str, Any], file_path: str, media_extensions: str) -> bool:
    """
    入库闸门的**唯一实现**：该文件是否应被纳入同步。

    The single implementation of the ingest extension gate.

    ⚠️ 不要再在别处写第二份。本插件历史上同时存在三份扩展名判断
    （入库闸门 / 补传候选 / 搜索重传），三份的 all_ext 分支与大小写处理各不相同，
    结果同一个 `.sup` 在补传路上会被带上、在入库闸门上会被丢弃 —— 同一个文件
    两条路两个结果，而丢弃只记 debug，界面上零痕迹。
    Callers must not re-implement this check.
    """
    valid = valid_exts_of(media_extensions, bool((pair or {}).get("all_ext", False)))
    if valid is None:
        return True
    return ext_of(file_path) in valid


def success_keys_after_audit(
        pair_name: str,
        rel_paths: List[str],
        missing_keys: List[str],
        corrupt_keys: List[str],
) -> List[str]:
    """
    从本批相对路径里选出「对账通过」的队列 key。

    Queue keys from this batch that passed audit (neither missing nor corrupt).

    用于冷却出队与 strm 观察登记。**判据只有对账结果，不含 rsync 退出码** ——
    退出码 23/24 是整批级告警（部分未传 / 源文件中途消失），与「这一份文件
    目标端是否已就绪」不是同一维度。曾用 `exit_code == 0` 作外层门禁，导致
    批内混合成败时已传成功的文件永不出队、也永不进入 strm 观察（P0-1）。

    Audit outcome is the only criterion — deliberately independent of the rsync
    exit code, which describes the whole batch rather than each file.
    """
    bad = set(missing_keys) | set(corrupt_keys)
    return [
        f"{pair_name}:{rel_p}"
        for rel_p in rel_paths
        if f"{pair_name}:{rel_p}" not in bad
    ]


def force_problem_rel_paths(
        pair_name: str,
        missing_keys: List[str],
        corrupt_keys: List[str],
) -> List[str]:
    """
    从 force 全量对账结果里取出**本映射**的相对路径清单（缺失 ∪ 残缺）。

    Relative paths for this pair from a force full-audit key list (missing ∪ corrupt).

    force 先全盘对账、再只对问题文件走 ``--files-from`` + 配额预扣（P0-2）：
    上传路径与 ready/retry 共用同一套批次上限与窗口配额，不再整树盲传。
    """
    prefix = f"{pair_name}:"
    rels: List[str] = []
    seen = set()
    for key in list(missing_keys) + list(corrupt_keys):
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        rel_p = key[len(prefix):]
        if rel_p and rel_p not in seen:
            seen.add(rel_p)
            rels.append(rel_p)
    return rels


def merge_force_anomalies(
        pre_missing: List[str],
        pre_corrupt: List[str],
        attempted_keys: List[str],
        post_missing: List[str],
        post_corrupt: List[str],
) -> Tuple[List[str], List[str]]:
    """
    合并 force「预对账 → 定向传输 → 复检」三段结果为最终异常清单。

    Merge force pre-audit, attempted transfer, and post-audit into final anomaly lists.

    - 本批未尝试的预异常（批次上限 / 配额截断）原样保留；
    - 本批已尝试的以复检为准：修好则移出，仍坏则留下。
    未尝试却因预对账已知的问题绝不能在合并时丢失（P0-2）。
    """
    attempted = set(attempted_keys)
    final_missing = [k for k in pre_missing if k not in attempted]
    final_corrupt = [k for k in pre_corrupt if k not in attempted]
    final_missing.extend(k for k in post_missing if k not in final_missing)
    final_corrupt.extend(k for k in post_corrupt if k not in final_corrupt)
    # 同一 key 不应同时出现在缺失与残缺：复检若改判类型，以复检为准
    final_missing = [k for k in final_missing if k not in set(post_corrupt)]
    final_corrupt = [k for k in final_corrupt if k not in set(post_missing)]
    return final_missing, final_corrupt


def pair_for_path(file_path: str, pairs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    判断某个绝对路径归属哪一组映射；不属于任何映射时返回 None。

    Decide which mapping pair owns an absolute path; None when it belongs to none.

    ⚠️ **必须按路径分隔符判定归属，不能用裸 startswith**：
    `/media/TV` 会匹配上 `/media/TV2/x.mkv`，把文件挂到错误的映射上，
    随后按错误的 src 计算相对路径并入队 —— 结果是文件被送到**另一个**
    目标目录。这条判定决定了「哪些文件才会被同步」，是本插件最核心的判据之一。
    Match on a path boundary — plain startswith would let "/media/TV" swallow
    "/media/TV2/...", attributing files to the wrong mapping and uploading them to
    the wrong destination.

    多个映射前缀重叠时取**第一个匹配**（与配置顺序一致），调用方不应依赖更
    复杂的优先级规则。
    """
    if not file_path:
        return None
    for pair in pairs:
        root = (pair.get("src") or "").strip().rstrip("/")
        if not root:
            continue
        if file_path == root or file_path.startswith(root + os.sep):
            return pair
    return None
