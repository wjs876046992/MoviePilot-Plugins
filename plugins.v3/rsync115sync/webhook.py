"""
Webhook 入库事件：报文解析（纯逻辑，无 I/O、无状态）。

Webhook ingest: payload parsing only. Pure logic — no I/O, no mutable state.

## 为什么要这个模块

现有入库监听只挂在宿主的**整理完成事件**上，因而看不到三类入库：

  1. 用户**手动**把文件放进媒体库（不经下载器/整理流程）
  2. 外部工具（其它脚本、其它容器）搬入文件
  3. 整理事件**漏发** —— 宿主走 durable outbox，超过重试上限即永久丢弃

Webhook 作为**第二来源**覆盖这些场景。来源两处，宿主支持程度完全不同：

  · Emby  → 宿主原生支持（`app/modules/emby` 提供 webhook_parser），
            插件只订阅 `EventType.WebhookMessage` 即可，**无需自建端点**
  · MDC-ng → 宿主**不认识**（全量排查 app/modules 后确认无 mdc/mdcz 模块），
            只能由本插件自建端点接收

## 与「整理事件」的读取方式差异（照抄前一定要看）

`_handle_transfer_event` 必须**优先** `event.snapshot()`：TransferComplete 登记了
契约且在 `_SNAPSHOT_EVENTS` 内（见 app/runtime/event/contracts.py）。

WebhookMessage 恰好相反：它**登记了 payload 模型**（`WebhookEventInfo`）但
**不在 `_SNAPSHOT_EVENTS` 内**，走快照路径拿不到 payload。因此这里统一用
`getattr(event_data, ...)` 直接读对象属性，并保留 dict 兜底
（旧宿主/手工构造的事件可能给 dict）。仓库内 watchsync 用的正是这个写法。
"""

import os
import posixpath
from typing import Any, Dict, List, Optional, Tuple

# ---- 事件白名单 ----------------------------------------------------------
# Emby 的 `library.new` 是「新媒体条目入库」，`library.update` 可能是刮削更新
# 而非新增文件，但两者都值得纳入（重复入队由队列幂等兜住，代价为零）。
EMBY_INGEST_EVENTS = frozenset({
    "library.new",
    "library.update",
    "item.added",
    "item.updated",
})

# 明确**不处理**的事件族前缀。播放类事件在 Emby 里同样携带 Item.Path，
# 若不加过滤，用户每看一集都会把该文件重新入队并触发一次上传 ——
# 这是本功能最危险的误动作，必须显式挡在白名单之前。
EMBY_IGNORE_EVENT_PREFIXES = ("playback.", "session.", "user.", "item.rate", "item.mark")

# ---- 通用报文路径字段候选 ------------------------------------------------
# 按可靠性排序，逐个尝试。不同发送端（MDC 版本、自建脚本）字段名不一，
# 但**不凭猜测写死单一字段名**：候选表只覆盖语义明确的「文件绝对路径」字段，
# 真正决定用哪个的是 payload 里的实际取值（配合首端点日志）。
PATH_FIELD_CANDIDATES: Tuple[str, ...] = (
    "path", "item_path", "file_path", "filepath", "file", "source_path",
    "src_path", "full_path", "media_path", "target_path", "directory",
)

# 路径字段可能挂在嵌套对象下（Emby 风格把一切放在 Item 里）
NESTED_CONTAINERS: Tuple[str, ...] = ("item", "Item", "data", "Data", "payload", "record", "file")

# 路径列表字段候选（一次推送多个文件）
LIST_FIELD_CANDIDATES: Tuple[str, ...] = ("paths", "files", "file_list", "items", "path_list")


def _as_dict(value: Any) -> Dict[str, Any]:
    """把任意对象（pydantic 模型 / SimpleNamespace）归一成 dict，失败给空 dict。"""
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            result = dump()
            if isinstance(result, dict):
                return result
        except Exception:
            pass
    if value is None:
        return {}
    result: Dict[str, Any] = {}
    for name in dir(value):
        if name.startswith("_"):
            continue
        try:
            attr = getattr(value, name)
        except Exception:
            continue
        if callable(attr):
            continue
        result[name] = attr
    return result


def read_field(source: Any, name: str, default: Any = None) -> Any:
    """按「属性优先、dict 兜底」读字段。WebhookMessage 不走快照，故不能用契约保证。"""
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(name, default)
    value = getattr(source, name, None)
    return default if value is None else value


def _looks_like_path(value: Any) -> bool:
    """粗判是否像一个文件系统路径：必须有分隔符，避免把标题/ID 当成路径。"""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) < 3 or "/" not in text and "\\" not in text:
        return False
    return True


def _normalize_path(value: Any) -> Optional[str]:
    """
    归一化路径：统一分隔符、去掉首尾空白。

    Windows 形态的 `\\\\host\\share\\dir\\file.mkv` 会转成 `/host/share/dir/file.mkv`，
    但**这不保证能匹配上映射** —— 宿主抓取到的 `Item.Path` 是什么形态，取决于
    Emby/MDC 的配置。因此归一化只做「能对上就对」的努力，绝不做前缀猜测。
    """
    if not _looks_like_path(value):
        return None
    text = str(value).strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text or None


def _collect_from_mapping(data: Dict[str, Any], depth: int = 0) -> List[str]:
    """
    在一层 dict 里收集所有候选路径字段（含单值字段与列表字段）。

    深度限制为 3：够了（payload 再深也不会是「入库路径」），且能防住自引用结构。
    """
    found: List[str] = []
    if depth > 3 or not isinstance(data, dict):
        return found
    # 大小写不敏感的辅助索引。第三方发送端的字段名大小写并不统一，Emby 自己就是
    # `Item.Path`（大写 P）—— 候选表按小写写，若严格按大小写取值，
    # 「字段名对了、只是首字母大写」会被判成「未识别」，用户照报文结构摘要也看不出
    # 问题出在大小写上。仅用于候选字段查找，不改变取值语义。
    lowered = {str(k).lower(): v for k, v in data.items()}
    for name in PATH_FIELD_CANDIDATES:
        path = _normalize_path(lowered.get(name))
        if path:
            found.append(path)
    for name in LIST_FIELD_CANDIDATES:
        raw = lowered.get(name)
        if isinstance(raw, (list, tuple)):
            for entry in raw:
                if isinstance(entry, str):
                    path = _normalize_path(entry)
                    if path:
                        found.append(path)
                elif isinstance(entry, dict):
                    found.extend(_collect_from_mapping(entry, depth + 1))
    for name in NESTED_CONTAINERS:
        nested = lowered.get(name.lower())
        if isinstance(nested, dict):
            found.extend(_collect_from_mapping(nested, depth + 1))
    return found


def norm_path(value: Any) -> str:
    """比较用的路径归一：posix 化 + 去尾斜杠。仅用于比较。"""
    if not value:
        return ""
    return posixpath.normpath(str(value).replace("\\", "/").strip())


def path_in_roots(path: str, roots: List[str]) -> bool:
    """
    判断路径是否落在给定根目录之一内（逐段比较，不是朴素前缀）。

    朴素 `startswith` 会让 `/media/TV2/a.mkv` 落进 `/media/TV` ——
    归错映射会把文件上传到**另一个** 115 目录，属静默的破坏性后果
    （与 paths.pair_for_path 的判据一致，此处独立实现以免引入循环依赖）。
    """
    target = norm_path(path)
    if not target:
        return False
    for root in roots or []:
        base = norm_path(root)
        if not base or base == "/":
            continue
        if target == base or target.startswith(base + "/"):
            return True
    return False


def extract_paths(event_data: Any) -> Tuple[List[str], str]:
    """
    从 WebhookMessage 的 payload 中提取候选入库路径。

    :return: (路径列表, 来源说明) —— 说明用于日志，便于按实际报文调整字段表

    读取顺序（**只用实测值，不做前缀猜测**）：

      1. `item_path` —— 宿主 Emby 解析器保证填好的字段（`WebhookEventInfo.item_path`）
      2. `json_object` 里的 Item.Path —— 原始 Emby 报文（`json_object` 是宿主解析器
         塞进去的**原始 dict**，字段名以 Emby 为准）
      2b. `json_object.paths` —— 本插件**自己认领**时写进去的多路径清单
          （`webhook_parser` 的返回值，见 __init__.py）
      3. 顶层候选字段 + 一层嵌套容器 —— 覆盖非 Emby 发送端（自建脚本 / MDC-ng）

    ⚠️ 1 与 2 必须**合并**而不是「1 有值就直接返回」。理由是自相矛盾会丢文件：
    `webhook_parser` 认领时把命中的**全部**路径写进 `json_object["paths"]`，
    而 `item_path` 按契约只能放**第一个** —— 一个目录型 webhook 推送 3 个文件时，
    「1 有值就返回」会让后 2 个静默消失，而日志里那次认领看上去完全成功。
    Emby 的真实报文两者都指向同一个文件，去重后行为不变。

    第 3 步是**尽力而为**：拿不到就是拿不到，绝不从 item_name 之类字段推测路径 ——
    本项目在「凭推测写机制」上吃过多次亏（见 DEVELOPMENT.md 3.8.1/3.12）。
    """
    data = _as_dict(event_data)
    if not data:
        return [], "空报文"

    found: List[str] = []
    labels: List[str] = []

    def _add(path: Optional[str]) -> None:
        if path and path not in found:
            found.append(path)

    # 1) 宿主解析器给的规范字段
    _add(_normalize_path(read_field(event_data, "item_path")) or _normalize_path(
        data.get("item_path")))
    if found:
        labels.append("item_path")

    # 2) 原始报文（Emby 形态：json_object.Item.Path）+ 认领时写入的多路径清单
    raw = data.get("json_object")
    if isinstance(raw, (str, bytes)):
        try:
            import json
            raw = json.loads(raw)
        except Exception:
            raw = None
    if isinstance(raw, dict):
        before = len(found)
        listed = raw.get("paths")
        if isinstance(listed, (list, tuple)):
            for entry in listed:
                _add(_normalize_path(entry))
        if len(found) > before:
            labels.append("json_object.paths")
        before = len(found)
        for holder in (raw.get("Item"), raw.get("item"), raw):
            if isinstance(holder, dict):
                _add(_normalize_path(holder.get("Path") or holder.get("path")))
        if len(found) > before:
            labels.append("json_object.Item.Path")

    if found:
        return found, "，".join(labels)

    # 3) 其它发送端的候选字段
    candidates = _collect_from_mapping(data)
    deduped: List[str] = []
    for path in candidates:
        if path not in deduped:
            deduped.append(path)
    if deduped:
        return deduped, "候选字段"

    # 连一个像路径的字段都没有：调用方会打一条「字段清单」debug 日志用于对齐报文
    return [], "未识别"


# ---- 报文样本（字段名 + 值，供「发送端未知」时对齐字段） ----
#
# ⚠️ 与 describe_payload 的分工：那个只留**结构**（键名与类型，不记值），
# 用于日志；这个保留**值**，因为它要回答的问题不同 ——
# 「对方到底把路径放在哪个字段里、值长什么样」。只留结构永远答不出来。
#
# 隐私取舍：值只截断保留，单字段上限 SAMPLE_VALUE_MAX 字符；且看板显示的是
# **最近若干条**而不是全量历史。入库路径本身对用户不是秘密（是他自己的媒体库），
# 但报文里可能混有 token / 播放进度之类的无关字段，故逐字段截断而非原样落盘。

SAMPLE_VALUE_MAX = 200


def _sanitize_sample(value: Any, depth: int = 0) -> Any:
    """把报文值裁成可安全落盘/展示的形状：限深、限长、去掉密钥类字段。"""
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in list(value.items())[:60]:
            key_text = str(key)
            # 密钥类字段一律脱敏：看板是明文展示的，不该把 token 抄在上面
            if _looks_secret(key_text):
                out[key_text] = "***"
                continue
            out[key_text] = _sanitize_sample(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_sanitize_sample(item, depth + 1) for item in list(value)[:20]]
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8", "replace")
        except Exception:
            return "<bytes>"
    if isinstance(value, str):
        if len(value) > SAMPLE_VALUE_MAX:
            return value[:SAMPLE_VALUE_MAX] + f"…(+{len(value) - SAMPLE_VALUE_MAX})"
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:SAMPLE_VALUE_MAX]


_SECRET_HINTS = ("token", "secret", "password", "passwd", "apikey", "api_key",
                 "authorization", "credential", "sign", "signature")


def _looks_secret(key_name: str) -> bool:
    lowered = str(key_name).lower()
    return any(hint in lowered for hint in _SECRET_HINTS)


def sample_payload(event_data: Any) -> Dict[str, Any]:
    """
    生成一份「可展示的报文样本」：字段名 + **值**（截断、脱敏、限深）。

    为什么需要它：发送端往往是另一个工程，它到底会传什么字段在开发期是未知的
    （用户原话：「我不知道发送端会传递什么样的参数」）。`describe_payload` 给出
    结构、却答不出「值长什么样」，而候选字段表能不能命中，取决于**值**是否符合
    路径形态。把最近若干条报文原样留下来，改候选表就不必靠猜。
    """
    data = _as_dict(event_data)
    if not data:
        return {}
    try:
        return _sanitize_sample(data)
    except Exception:
        return {"<样本生成失败>": True}


def describe_payload(event_data: Any, limit: int = 40) -> str:
    """
    把报文的**结构与字段名**（不是值）摘要成一行，供端点日志排障。

    只列键名与类型，不打印值：入库路径可能含隐私信息，且逐字段打值在批量推送时
    会把日志刷爆。拿到字段名就足以判断「该把哪个字段加进候选表」。
    """
    def shape(obj: Any, depth: int = 0) -> str:
        if isinstance(obj, dict):
            if depth >= 2:
                return "{...}"
            inner = ", ".join(f"{k}:{shape(v, depth + 1)}" for k, v in list(obj.items())[:limit])
            return "{" + inner + "}"
        if isinstance(obj, (list, tuple)):
            return f"[{len(obj)}]" if obj else "[]"
        return type(obj).__name__

    try:
        return shape(_as_dict(event_data))
    except Exception:
        return "<无法摘要>"


def match_mapping(file_path: str, pairs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    把入库路径归属到某个目录映射（**复用本模块的逐段比较**，不改写原路径）。

    注意与 `paths.pair_for_path` 的分工：那里做的是同一件事，但它对每条路径
    取「最长匹配」并做相对路径计算。此处只回答「属于哪个映射」，因此独立实现、
    保持纯函数，避免 webhook 链路反向依赖同步链路的实现细节。

    Windows/UNC 形态的路径在这里基本匹配不上（映射配的是容器内的 POSIX 路径）——
    这是**预期行为**：匹配不上就不入队，绝不猜。
    """
    target = norm_path(file_path)
    if not target:
        return None
    best: Optional[Dict[str, Any]] = None
    best_len = -1
    for pair in pairs or []:
        src_root = norm_path((pair or {}).get("src") or "")
        if not src_root:
            continue
        if target == src_root or target.startswith(src_root + "/"):
            if len(src_root) > best_len:
                best, best_len = pair, len(src_root)
    return best


def valid_extension(pair: Dict[str, Any], file_path: str, media_extensions: str) -> bool:
    """扩展名过滤：与事件链路同一口径（映射勾了 all_ext 则不过滤）。"""
    if (pair or {}).get("all_ext", False):
        return True
    ext = posixpath.splitext(str(file_path))[-1].lstrip(".").lower()
    valid = {x.strip().lower() for x in (media_extensions or "").split(",") if x.strip()}
    return ext in valid


def rel_under(src_root: str, file_path: str) -> str:
    """取源端相对路径（用于与事件链路共用同一个队列 key 口径）。"""
    base = norm_path(src_root)
    target = norm_path(file_path)
    if not base or not target or not target.startswith(base + "/"):
        return ""
    return target[len(base) + 1:]


def is_ingest_event(event_name: str) -> bool:
    """
    判断是否属于「入库类」webhook 事件。

    空事件名一律拒绝：宁可漏（用户能从日志看到并补上白名单），
    也不要把播放/标记类事件当成入库，导致用户看一集就触发一次上传。
    """
    name = (event_name or "").strip().lower()
    if not name:
        return False
    for prefix in EMBY_IGNORE_EVENT_PREFIXES:
        if name.startswith(prefix):
            return False
    return name in EMBY_INGEST_EVENTS


def channel_of(event_data: Any) -> str:
    """取事件来源渠道（emby / mdcz / 自建 sender 自报名）。"""
    return str(read_field(event_data, "channel", "") or "").strip().lower()


def secret_ok(expected: str, provided: Any) -> bool:
    """
    常量时间比较 webhook 密钥。

    用 `secrets.compare_digest` 而非 `==`：字符串比较会短路，逐字符的耗时差
    可被用于逐位猜解密钥。空 expected 视为「未配置」——**调用方必须据此拒绝请求**，
    本函数不做这个判断，避免把「未配置」和「密钥错误」两种语义混在一起。
    """
    import secrets
    if not expected:
        return False
    return secrets.compare_digest(str(expected), str(provided or ""))


def header_lookup(headers: Any, name: str) -> Optional[str]:
    """
    从 FastAPI 的 headers 里取一个头（大小写不敏感）—— 不使用 Header(...) 参数
    注入，因为那是 fastapi 专有依赖，桩环境里没有；用 Request 更稳。
    """
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except Exception:
        return None
    if value is not None:
        return value
    try:
        for key, val in headers.items():
            if str(key).lower() == name.lower():
                return val
    except Exception:
        return None
    return None


def is_file(path: str) -> bool:
    """os.path.isfile 的薄封装，便于测试替换。"""
    try:
        return os.path.isfile(path)
    except Exception:
        return False
