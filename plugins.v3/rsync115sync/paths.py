"""
路径与目录映射的纯函数工具。

Pure helpers for paths and directory-mapping pairs. **Stateless by design** —
nothing here may hold mutable state, because the host re-executes the source in
a per-instance namespace while imported module globals stay shared (see
docs/Plugin_Development.md 7.4). All state lives on the plugin instance.

本模块只放"给定输入就能算出输出"的函数：不读配置、不写盘、不记日志。
"""

import os
from typing import Any, Dict, List, Optional

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
