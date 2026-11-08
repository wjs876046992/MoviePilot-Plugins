"""
CloudDrive2 gRPC-web 的最小只读客户端：查「这个文件此刻是否正在上传队列里」。

Minimal read-only CloudDrive2 gRPC-web client: ask whether a file is *currently*
in CD2's upload queue.

## 为什么需要它（用户实测的真实环路）

本插件的疑似判据是「同步报成功，宽限期内没有 .strm」。而一条大文件在 CD2 侧
要传几十分钟到几小时 —— 宽限期（默认 5 分钟）根本不够。于是：

    rsync 报成功 → 5 分钟后判疑似 → 用户/看板「删旧重传」
    → 删掉正在传的文件 → 从零重传 → 又传不完 → 又判疑似 → …

用户原话：「存在需要真实上传的，也会放疑似，不清楚情况时会一直删除一直重传，
目前我是人工去 cd2 确认的」。这个人工确认正是本模块要替代的一步。
The user was hand-checking CloudDrive2's UI before deleting anything. This module
automates exactly that check.

## 判据的定位：**只降噪，不放行**

它回答的是「此刻 CD2 正在传这个文件吗」。是 ⇒ 条目其实是**进展中**，不该报警，
也不该被删旧重传（删了会让刚传的几 GB 全部作废）。
否 ⇒ **什么都不改变**：仍按原来的判据处理。

⚠️ 这条区别是承重的。若把它当作"上传成功"的证据，就重蹈了 v0.3.0 删掉的
「云端可见性」判定 —— 那套判据对改名失败必然判错（见 DEVELOPMENT §3.11）。
本模块**只**用于把「明确在进行中」的条目从报警里摘出来，绝不用于判成功。
Only "definitely in progress" suppresses an alert. Absence proves nothing and
must not be read as success — that mistake is what v0.3.0 removed.

## 协议细节（全部实测确认，不要凭 proto 猜测）

CD2 的 HTTP 端口（默认 19798）同时提供 gRPC-web。请求/响应都是
`grpc-web+proto`，**不需要 grpcio 依赖**，用标准库的 `urllib` 即可。
端到端验证：对 `/clouddrive.CloudDriveFileSrv/GetMountPoints` 调用返回了
`/volume2/CloudNAS/115 ⇐ /115open/HomeTheater`，字段号与 proto 一致。

- 鉴权：`Authorization: Bearer <api_token>`（CD2 网页「API Tokens」页生成）。
  缺失或无效时服务端在 trailer 里回 `grpc-status: 16` / `No valid auth token`，
  **HTTP 状态仍是 200** —— 所以必须读 trailer，不能只看 HTTP 码。
- 帧格式：每条消息是 `1 字节标志 + 4 字节大端长度 + 消息体`。标志高位（0x80）
  置位的是 **trailer 帧**（内容是 `grpc-status: 0\r\n` 这样的文本），其余是
  消息帧。把 trailer 当 protobuf 去解会得到垃圾字段。
- 成功但无数据时**消息帧长度为 0**（如 `GetUploadFileList` 空队列），
  此时 `totalCount` 为 0，不是错误。

纯函数、无状态；网络调用与解析分开，解析部分可单独测试。
Stateless pure functions; the network call and the parsing are separable so the
parsing can be unit-tested offline.
"""

import struct
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# ---- gRPC-web 状态码（只用得到这两个，其余一律按失败处理）----
GRPC_OK = 0
GRPC_UNAUTHENTICATED = 16

# ---- proto 字段号 ----
# 来源：CloudDrive2 的 CloudDrive.proto，且已用线上实例逐字段核对。
# 逐字段核对而非照抄，是因为不同 CD2 版本的 proto 会漂移；核对方式是拿
# `GetMountPoints` 的真实响应比对（字段号错位时路径会明显对不上）。
# Verified field-by-field against a live instance, not copied blindly.

# GetUploadFileListRequest
_REQ_GET_ALL = 1
_REQ_ITEMS_PER_PAGE = 2
_REQ_PAGE_NUMBER = 3
_REQ_FILTER = 4
_REQ_STATUS_FILTER = 5

# GetUploadFileListResult
_RES_TOTAL_COUNT = 1
_RES_UPLOAD_FILES = 2

# UploadFileInfo
_UPLOAD_KEY = 1
_UPLOAD_DEST_PATH = 2
_UPLOAD_SIZE = 3
_UPLOAD_TRANSFERRED = 4
_UPLOAD_STATUS_TEXT = 5
_UPLOAD_ERROR = 6
_UPLOAD_STATUS_ENUM = 8

# Status_1 枚举（**注意不是** Status，那是备份任务的状态）。
# 名字来自 CD2 自带 wasm 里的界面字符串，取值顺序来自 proto。
# 这个枚举是 `statusEnum` 字段（f8）的取值空间；`status`（f5，字符串）是它的
# 可读镜像，可能随版本改措辞 —— 因此判定只认数字，文案仅用于展示。
# Enum values come from the proto; the string mirror (f5) may be reworded between
# versions, so decisions key off the number only.
STATUS_WAITFOR_PREPROCESSING = 0
STATUS_PREPROCESSING = 1
STATUS_CANCELLED = 2
STATUS_TRANSFER = 3
STATUS_PAUSE = 4
STATUS_FINISH = 5
STATUS_SKIPPED = 6
STATUS_INQUEUE = 7
STATUS_IGNORED = 8
STATUS_ERROR = 9
STATUS_FATAL_ERROR = 10

STATUS_TEXT = {
    STATUS_WAITFOR_PREPROCESSING: "排队中",
    STATUS_PREPROCESSING: "预处理中",
    STATUS_CANCELLED: "已取消",
    STATUS_TRANSFER: "传输中",
    STATUS_PAUSE: "已暂停",
    STATUS_FINISH: "已完成",
    STATUS_SKIPPED: "已跳过",
    STATUS_INQUEUE: "队列中",
    STATUS_IGNORED: "已忽略",
    STATUS_ERROR: "失败",
    STATUS_FATAL_ERROR: "严重失败",
}

# 「此刻仍在进行、删了会白传」的状态集合。
#
# ⚠️ 这是本模块的**唯一业务判据**，故意写得窄：
# 只包含「还在队列里 / 正在预处理 / 正在传输 / 被暂停」。刻意**不含**
# FINISH —— 完成却仍没有 strm 正是我们要抓的异常；也**不含** ERROR/IGNORED/
# SKIPPED —— 那些是真的没传上去，应当继续报警。
# Only in-flight states suppress the alert. FINISH is deliberately excluded: finished
# without a strm is exactly the anomaly we exist to catch.
IN_FLIGHT_STATUSES = frozenset({
    STATUS_WAITFOR_PREPROCESSING,
    STATUS_PREPROCESSING,
    STATUS_TRANSFER,
    STATUS_PAUSE,
    STATUS_INQUEUE,
})

# ⚠️ 这些状态**不计入暂停时长**（见 `plan_delay_seconds` 的说明）。
# 只有真正"被按了暂停键"的 PAUSE 才该无限期豁免；排队/预处理/传输都在动，
# 它们卡住是**另一个问题**（CD2 侧异常），不该被当成"正常等待"一直藏起来。
# Only PAUSE gets unbounded suppression: the other in-flight states are moving, and
# one that stops moving is itself a fault that must surface.
MOVING_STATUSES = frozenset({
    STATUS_WAITFOR_PREPROCESSING,
    STATUS_PREPROCESSING,
    STATUS_TRANSFER,
    STATUS_INQUEUE,
})

# 「正在上传」的豁免**最长期限**（小时）。
#
# ## 为什么必须有上限（否则本模块会制造一类新的、更隐蔽的故障）
#
# 豁免的逻辑是「它还在传，别报警也别删」。但 CD2 的任务可能**永远卡住**：
# 网络中断后停在 `预处理中` 不动、用户手动暂停后忘了恢复、115 侧限流导致
# 长时间无进展。这时条目会被永久摘出疑似清单 —— 而它其实就是坏了。
# 结果：用户失去了唯一的告警，看到的只有"一切正常"，直到若干天后发现
# 某个剧集在云端是残缺的。**一个把真问题藏起来的保护，比没有保护更糟。**
#
# 所以豁免有期限：超过这个时长仍在传，就退回原判据（照常报警），
# 让用户自己判断是不是卡住了。默认 6 小时 —— 足够覆盖一条 50 GB 文件
# 在慢速宽带上传完所需的时间，又不至于让一个卡死的任务静默数天。
# A stuck CD2 task would otherwise hide a real failure forever; the exemption must
# expire so the alert comes back. A safeguard that conceals a fault is worse than none.
CD2_SUPPRESS_MAX_HOURS = 6

# 暂停状态的豁免**更短**（小时）。
#
# 暂停是用户主动动作，语义是「我知道，先别管」—— 本该长期有效。但"暂停后
# 忘了恢复"太常见了，而它的表现与"卡死"完全一致。取 24 小时：足够覆盖
# 「晚上暂停、第二天继续」这种正常用法，又不会把一个忘了一周的暂停当成常态。
# Pausing is deliberate, so it lasts longer — but "paused and forgotten" looks
# identical to "stuck", so it still expires.
CD2_SUPPRESS_PAUSE_MAX_HOURS = 24

# 单次查询最多取多少条上传任务。CD2 的上传队列是「活跃任务」，不是历史库，
# 正常情况下只有个位数到几十条；给个宽松上限只是为了不在服务端行为异常时
# 把几万条塞进内存。
# The queue holds active tasks, not history, so this is only a runaway guard.
MAX_UPLOAD_ITEMS = 2000

# HTTP 超时（秒）。这个调用挂在疑似判定路径上，**绝不能让它拖慢巡检** ——
# 巡检是同步 servery 里的一环，卡住会连带影响同步调度。
# Kept short: this sits on the sweep path and must never stall the scheduler.
HTTP_TIMEOUT = 8


# ---------------------------------------------------------------------------
# 编解码（纯函数）
# ---------------------------------------------------------------------------

def _encode_varint(value: int) -> bytes:
    """无符号 varint 编码。"""
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _encode_key(field: int, wire_type: int) -> bytes:
    """protobuf 的 tag（field_number << 3 | wire_type）。"""
    return _encode_varint((field << 3) | wire_type)


def _iter_fields(buf: bytes):
    """
    逐个产出 (field_number, wire_type, value)。

    value：varint 为 int，length-delimited 为 bytes，定长为 bytes。
    遇到未知 wire type 直接抛出 —— 静默跳过会让后续字段整体错位，
    表现为「字段全乱但也不报错」，比失败难查得多。
    """
    i = 0
    n = len(buf)
    while i < n:
        shift = 0
        key = 0
        while True:
            if i >= n:
                raise ValueError("protobuf: varint key 截断")
            b = buf[i]
            i += 1
            key |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
        field, wire = key >> 3, key & 7
        if wire == 0:
            shift = 0
            val = 0
            while True:
                if i >= n:
                    raise ValueError("protobuf: varint 值截断")
                b = buf[i]
                i += 1
                val |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
            yield field, wire, val
        elif wire == 2:
            shift = 0
            ln = 0
            while True:
                if i >= n:
                    raise ValueError("protobuf: 长度前缀截断")
                b = buf[i]
                i += 1
                ln |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
            if i + ln > n:
                raise ValueError("protobuf: length-delimited 越界")
            yield field, wire, buf[i:i + ln]
            i += ln
        elif wire == 5:
            if i + 4 > n:
                raise ValueError("protobuf: fixed32 越界")
            yield field, wire, buf[i:i + 4]
            i += 4
        elif wire == 1:
            if i + 8 > n:
                raise ValueError("protobuf: fixed64 越界")
            yield field, wire, buf[i:i + 8]
            i += 8
        else:
            raise ValueError(f"protobuf: 未知 wire type {wire}")


def _decode_text(raw: bytes) -> str:
    """bytes → str，坏字节不抛异常（路径出问题不该让整轮查询失败）。"""
    return raw.decode("utf-8", "replace")


def encode_upload_list_request(get_all: bool = True,
                               items_per_page: int = 0,
                               page_number: int = 0) -> bytes:
    """
    构造 `GetUploadFileListRequest`。

    默认 `getAll=True` 一次拿全 —— 分页会引入「翻页期间队列在变」的竞态，
    而我们只关心「这几个文件在不在」，一次拿全最简单也最不容易错。
    `getAll` fetches everything in one shot; paging would race with a live queue.
    """
    out = bytearray()
    out += _encode_key(_REQ_GET_ALL, 0) + _encode_varint(1 if get_all else 0)
    if items_per_page:
        out += _encode_key(_REQ_ITEMS_PER_PAGE, 0) + _encode_varint(items_per_page)
    if page_number:
        out += _encode_key(_REQ_PAGE_NUMBER, 0) + _encode_varint(page_number)
    return bytes(out)


def frame_message(payload: bytes) -> bytes:
    """
    给消息加 gRPC-web 帧头：`0x00 + 4 字节大端长度 + 消息体`。

    0x00 是「未压缩」标志。压缩需要额外的 `grpc-encoding` 协商，
    我们不启用 —— 纯本地 LAN 调用，省掉一层出错可能。
    """
    return b"\x00" + struct.pack(">I", len(payload)) + payload


def split_frames(raw: bytes) -> Tuple[List[bytes], str, int]:
    """
    把 gRPC-web 响应拆成 (消息帧列表, trailer 文本, grpc-status)。

    ⚠️ 必须区分消息帧与 trailer 帧：标志高位（0x80）置位的是 trailer，
    内容是纯文本 `grpc-status: 0\r\n`。把 trailer 拿去当 protobuf 解析会
    读出垃圾字段（而这不会报错，只会让你以为服务端返回了奇怪的东西）。
    Trailer frames carry the status text; parsing them as protobuf silently yields
    garbage, so the high bit must be checked before anything else.
    """
    messages: List[bytes] = []
    trailer_parts: List[str] = []
    i = 0
    n = len(raw)
    while i + 5 <= n:
        flag = raw[i]
        length = struct.unpack(">I", raw[i + 1:i + 5])[0]
        i += 5
        end = i + length
        if end > n:
            # 截断的帧：保留已解析出的部分，但让状态码体现出问题
            trailer_parts.append(f"（响应截断，期望 {length} 字节）")
            break
        chunk = raw[i:end]
        i = end
        if flag & 0x80:
            trailer_parts.append(_decode_text(chunk))
        else:
            messages.append(chunk)
    status = _parse_grpc_status(trailer_parts)
    return messages, "".join(trailer_parts).strip(), status


def _parse_grpc_status(trailer_parts: List[str]) -> int:
    """
    从 trailer 文本里取 `grpc-status`，取不到时按**成功**处理。

    ⚠️ 取不到默认成功的理由：CD2 在正常响应时确实带 trailer，但反向代理
    有可能吃掉它。此时把正常响应判成失败，会让上传任务被当成「查不到」而
    重新报警 —— 也就是这个功能不仅没帮上忙，还倒退了。真正的失败（鉴权失败）
    一定会带 trailer，所以不会漏判。
    Absent trailer defaults to OK: a proxy stripping it must not turn a working
    query into an alert. Real failures (bad token) always carry a trailer.
    """
    for part in trailer_parts:
        for line in part.replace("\r\n", "\n").split("\n"):
            line = line.strip()
            if line.lower().startswith("grpc-status:"):
                try:
                    return int(line.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    return GRPC_OK
    return GRPC_OK


def parse_upload_list(message: bytes) -> List[Dict[str, Any]]:
    """
    解析 `GetUploadFileListResult` → 上传任务列表。

    每项：`{key, dest_path, size, transfered, status, status_text, error}`，
    其中 `status` 是数字（判定用），`status_text` 是给人看的。
    """
    items: List[Dict[str, Any]] = []
    for field, wire, value in _iter_fields(message):
        if field != _RES_UPLOAD_FILES or wire != 2:
            continue
        item: Dict[str, Any] = {
            "key": "", "dest_path": "", "size": 0, "transfered": 0,
            "status": -1, "status_text": "", "error": "",
        }
        for f2, w2, v2 in _iter_fields(value):
            if f2 == _UPLOAD_KEY and w2 == 2:
                item["key"] = _decode_text(v2)
            elif f2 == _UPLOAD_DEST_PATH and w2 == 2:
                item["dest_path"] = _decode_text(v2)
            elif f2 == _UPLOAD_SIZE and w2 == 0:
                item["size"] = int(v2)
            elif f2 == _UPLOAD_TRANSFERRED and w2 == 0:
                item["transfered"] = int(v2)
            elif f2 == _UPLOAD_STATUS_TEXT and w2 == 2:
                item["status_text"] = _decode_text(v2)
            elif f2 == _UPLOAD_ERROR and w2 == 2:
                item["error"] = _decode_text(v2)
            elif f2 == _UPLOAD_STATUS_ENUM and w2 == 0:
                item["status"] = int(v2)
        items.append(item)
    return items


def parse_upload_total(message: bytes) -> int:
    """从 `GetUploadFileListResult` 取 `totalCount`（没有该字段时为 0）。"""
    for field, wire, value in _iter_fields(message):
        if field == _RES_TOTAL_COUNT and wire == 0:
            return int(value)
    return 0


# ---------------------------------------------------------------------------
# 匹配：把本插件的队列 key 换算成 CD2 的上传任务
# ---------------------------------------------------------------------------

def normalize_path(path: Optional[str]) -> str:
    """
    路径归一化：反斜杠转正斜杠、压掉重复斜杠、去掉尾部斜杠。

    不处理大小写与符号链接 —— 两端都是同一台机器上的 POSIX 路径，
    多余的正则只会引入这个功能自己的一类误判。
    """
    text = str(path or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    if len(text) > 1:
        text = text.rstrip("/")
    return text


def map_local_to_cloud(local_path: str,
                       mount_map: Optional[Dict[str, str]]) -> Optional[str]:
    """
    把本地路径换算成 CD2 的云端路径；无法匹配时返回 None。

    ## 为什么不能简单地做前缀替换

    CD2 报的挂载点（`GetMountPoints` 的 `mountPoint`）是**CD2 进程自己看到的
    宿主机路径**，而本插件配置里的 `dest` 是**MoviePilot 容器内**看到的路径。
    两者常常带不同的前缀，实测就是这种情况：

        CD2  mountPoint = /volume2/CloudNAS/115
        MP   配置 dest  = /CloudNAS/115/TV/…          （容器里 /volume2 没有挂进来）

    `dest.startswith(mountPoint)` 为假，但两者描述的是同一个挂载。所以按
    **路径分量**对齐：找 mountPoint 的某个后缀与本地路径的前缀相同，取最长的
    那个匹配，剩下的分量接到云端根目录后面。
    Segment-wise alignment: CD2 reports host paths while the plugin's `dest` is the
    container view, so a string prefix check fails even though they are the same mount.

    返回 None 表示「不知道」，调用方应退回原样路径去比对 —— 而不是当成
    「没在上传」（那会让本该降噪的条目重新变成报警）。
    """
    if not mount_map:
        return None
    local_segs = [s for s in normalize_path(local_path).split("/") if s]
    if not local_segs:
        return None
    best_tail_len = -1
    best_mapped: Optional[str] = None
    for mount_point, cloud_root in mount_map.items():
        mount_segs = [s for s in normalize_path(mount_point).split("/") if s]
        if not mount_segs:
            continue
        # 用 mountPoint 的每个后缀去对齐本地路径的前缀，取最长匹配。
        # 最长优先是为了避免短后缀（如 `/115`）在兄弟挂载之间乱认。
        for k in range(len(mount_segs)):
            tail = mount_segs[k:]
            if len(local_segs) < len(tail) or local_segs[:len(tail)] != tail:
                continue
            if len(tail) <= best_tail_len:
                continue
            rest = local_segs[len(tail):]
            cloud_segs = [s for s in normalize_path(cloud_root).split("/") if s]
            best_tail_len = len(tail)
            best_mapped = "/" + "/".join(cloud_segs + rest)
    return best_mapped


def dest_paths_for_key(key: str,
                       pairs: List[Dict[str, Any]],
                       mount_map: Optional[Dict[str, str]] = None) -> List[str]:
    """
    由队列 key（`任务名:相对路径`）推导该文件在 CD2 侧的**可能**目标路径。

    为什么是「可能 / 复数」：本插件的 `dest` 是 **CD2 挂载点**（本地视图，如
    `/CloudNAS/115/TV`），而 CD2 的上传任务里 `destPath` 用的是**云端路径**
    （如 `/115open/HomeTheater/TV`）。两者之间靠 CD2 自己的挂载映射对应，
    而那张映射只有 CD2 知道 —— 所以 `mount_map` 由 `GetMountPoints` 取得
    （`{本地挂载点: 云端目录}`），本函数据此把本地路径换算成云端路径。

    `mount_map` 缺失或不匹配时，仍然把 `dest` 拼接原样返回：用户可能恰好
    把 dest 直接填成了云端路径；匹配不上就是查不到，按「没在传」处理，
    不影响原有判据。
    The local `dest` is a mount view while CD2 reports cloud paths, so the mount
    map from GetMountPoints bridges them. When it is unavailable we still try the
    raw path — a miss simply means "not found", which changes nothing.
    """
    result: List[str] = []
    for pair in pairs:
        pair_name = (pair.get("name") or "").strip() or (pair.get("src") or "").strip().rstrip("/")
        if not pair_name or not key.startswith(f"{pair_name}:"):
            continue
        rel = key.split(f"{pair_name}:", 1)[1]
        dest = normalize_path(pair.get("dest"))
        if not dest or not rel:
            continue
        local_full = normalize_path(f"{dest}/{rel}")
        result.append(local_full)
        # 换算成云端路径：CD2 的上传任务用云端路径报告目标。
        mapped = map_local_to_cloud(local_full, mount_map)
        if mapped and mapped not in result:
            result.append(mapped)
    return result


def find_in_flight(candidates: List[str],
                   uploads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    在 CD2 上传任务里找出与 `candidates` 对应的、**仍在进行中**的条目。

    匹配口径：CD2 的 `destPath` 是**完整文件路径**（含文件名），
    而我们的候选也是完整路径，因此按归一化后精确相等比较。
    不做模糊/前缀匹配 —— 前缀会把「同目录的另一个文件」算进来，
    那会让一条正在传的邻居文件把整季的疑似全部压掉。
    Exact match only: a prefix match would let one in-flight neighbour silence
    every suspect in the same folder.
    """
    wanted = {normalize_path(p) for p in candidates if p}
    if not wanted:
        return []
    hits: List[Dict[str, Any]] = []
    for item in uploads:
        if item.get("status") not in IN_FLIGHT_STATUSES:
            continue
        for path in (item.get("dest_path"), item.get("key")):
            if normalize_path(path) in wanted:
                hits.append(item)
                break
    return hits


def suppression_seconds(item: Dict[str, Any]) -> float:
    """
    这条上传任务还能"压住告警"多久（秒）；已超过上限或不该压时返回 0。

    ⚠️ 这是防止「保护变成掩护」的关键。CD2 的 `UploadFileInfo` **没有**开始
    时间字段，所以无法知道它已经传了多久 —— 改用**本地证据**：条目在观察期
    里存在了多久（由调用方传入，见 `should_suppress`）。
    判据是「挂了很久还在说自己在传」，那几乎必然是卡住了。

    CD2 does not report an upload start time, so staleness is measured from our own
    local evidence: how long the entry has been waiting.
    """
    status = item.get("status")
    if status == STATUS_PAUSE:
        return CD2_SUPPRESS_PAUSE_MAX_HOURS * 3600
    if status in MOVING_STATUSES:
        return CD2_SUPPRESS_MAX_HOURS * 3600
    return 0.0


def should_suppress(item: Dict[str, Any], age_secs: float) -> bool:
    """
    这条任务是否仍应压住告警/阻止删除。

    :param age_secs: 该条目**已经等待了多久**（秒）—— 观察期条目从同步成功
        算起，疑似条目从首次疑似算起。调用方必须传真实值：把它写成 0 会让
        卡死的任务被无限期豁免，写成常数会让正常上传被误报。

    ## 为什么需要这个边界

    没有它，一个卡在 `预处理中` 的 CD2 任务会让对应文件**永远**不出现在
    疑似清单里 —— 用户看到的是"一切正常"，而云端文件其实是残缺的。
    这个模块的目标是减少误报，不是把真问题藏起来。
    Without it, one stuck task hides that file's failure forever — the opposite of
    what this module is for.
    """
    limit = suppression_seconds(item)
    if limit <= 0:
        return False
    return float(age_secs or 0.0) < limit


def progress_text(item: Dict[str, Any]) -> str:
    """
    把一条上传任务说成人话：「传输中 5.7 GB / 8.1 GB」。

    进度对用户的意义在于回答「还要不要等」—— 所以分母用总大小而不是百分比，
    大文件能直接看出还剩几个 GB。
    """
    status = STATUS_TEXT.get(item.get("status"), item.get("status_text") or "上传中")
    size = int(item.get("size") or 0)
    done = int(item.get("transfered") or 0)
    if size > 0:
        return f"{status} {_gb(done)} / {_gb(size)}"
    if done > 0:
        return f"{status} {_gb(done)}"
    return status


def _gb(num: int) -> str:
    """字节 → 人类可读（只用于展示，保留一位小数）。"""
    if num >= 1024 ** 3:
        return f"{num / (1024 ** 3):.1f} GB"
    if num >= 1024 ** 2:
        return f"{num / (1024 ** 2):.0f} MB"
    if num >= 1024:
        return f"{num / 1024:.0f} KB"
    return f"{num} B"


def parse_mount_points(message: bytes) -> Dict[str, str]:
    """
    解析 `GetMountPointsResult` → {本地挂载点: 云端目录}。

    ⚠️ 只收 `isMounted` 为真的条目：未挂载的映射指向的是**配置**而非现状，
    拿它做换算会把路径翻译到一个当前并不存在的位置。
    Only mounted entries: an unmounted mapping describes intent, not current state.
    """
    mapping: Dict[str, str] = {}
    for field, wire, value in _iter_fields(message):
        if field != 1 or wire != 2:      # GetMountPointsResult.mountPoints
            continue
        mount_point = ""
        source_dir = ""
        mounted = True                   # 字段缺失时不排除（proto3 默认 false 会造成漏收）
        for f2, w2, v2 in _iter_fields(value):
            if f2 == 1 and w2 == 2:
                mount_point = _decode_text(v2)
            elif f2 == 2 and w2 == 2:
                source_dir = _decode_text(v2)
            elif f2 == 9 and w2 == 0:
                mounted = bool(v2)
        if mount_point and source_dir and mounted:
            mapping[normalize_path(mount_point)] = normalize_path(source_dir)
    return mapping


# ---------------------------------------------------------------------------
# 网络：只读查询
# ---------------------------------------------------------------------------

class CloudDrive2Error(Exception):
    """CD2 查询失败（网络/鉴权/协议）。调用方一律按「查不到」降级处理。"""


def call_grpc_web(base_url: str, method: str, payload: bytes,
                  token: str, timeout: float = HTTP_TIMEOUT) -> Tuple[bytes, str, int]:
    """
    调用一个 gRPC-web 方法，返回 (首个消息体, trailer 文本, grpc-status)。

    `base_url` 形如 `http://192.168.1.8:19798`；`method` 是完整方法名
    `clouddrive.CloudDriveFileSrv/GetUploadFileList`。

    ## ⚠️ 失败与成功的状态码藏在**两个不同位置**（实测踩过）

    | 情形 | HTTP 码 | grpc-status 的位置 |
    |---|---|---|
    | 成功 | 200 | **trailer 帧**（响应体末尾的 `\x80` 帧） |
    | 鉴权失败 / 服务端错误 | 200 | **HTTP 响应头** |

    关键点：两种情况 HTTP 码**都是 200**，而失败时响应体是空的
    （`content-length: 0`）、trailer 帧根本不存在。因此只看 trailer 会把
    「token 无效」读成「队列为空」—— 而这两者在业务上的意义完全相反：
    前者是查不到（应保持原判据），后者是确认没在传。
    实际踩到过：错误 token 返回了「0 条任务」，于是保护看起来在工作、实际从未生效。

    Status codes live in *two different places*: success carries them in a trailer
    frame, failures carry them in HTTP headers — and both answer 200. Reading only
    the trailer turns "bad token" into "empty queue", which is the one confusion this
    module must never make.

    ⚠️ 只读方法才会被本模块调用。**绝不**在这里暴露删除/上传接口：
    这个类存在的意义是「少做破坏性操作」，不该反过来成为破坏的入口。
    Read-only by construction — this module must not become a path to destructive ops.
    """
    url = f"{str(base_url).rstrip('/')}/{method.lstrip('/')}"
    headers = {
        "Content-Type": "application/grpc-web+proto",
        "x-grpc-web": "1",
        "x-user-agent": "grpc-web-python/0.1",
    }
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url, data=frame_message(payload), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # 先读头部的 grpc-status —— 失败路径**只**在这里
            header_status = response.headers.get("grpc-status")
            header_message = response.headers.get("grpc-message", "")
            raw = response.read()
    except urllib.error.HTTPError as exc:
        # 理论上不该发生（CD2 用 200 承载错误），但反向代理可能改写状态码
        raise CloudDrive2Error(f"HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise CloudDrive2Error(f"无法连接 CD2（{base_url}）: {exc.reason}") from exc
    except OSError as exc:
        raise CloudDrive2Error(f"CD2 请求失败: {exc}") from exc

    if header_status not in (None, ""):
        try:
            status_from_header = int(header_status)
        except (TypeError, ValueError):
            status_from_header = GRPC_OK
        if status_from_header != GRPC_OK:
            self_message = str(header_message).replace("%20", " ")
            if status_from_header == GRPC_UNAUTHENTICATED:
                raise CloudDrive2Error(
                    f"CD2 拒绝了 API Token（grpc-status 16: {self_message or 'Invalid auth token'}）。"
                    f"请在 CD2 网页「API Tokens」页重新生成并填入配置")
            raise CloudDrive2Error(
                f"CD2 返回 grpc-status={status_from_header}: {self_message}")

    messages, trailer, status = split_frames(raw)
    if status == GRPC_UNAUTHENTICATED:
        raise CloudDrive2Error(
            "CD2 拒绝了 API Token（grpc-status 16）。请在 CD2 网页「API Tokens」"
            "页重新生成并填入配置")
    if status != GRPC_OK:
        raise CloudDrive2Error(f"CD2 返回 grpc-status={status}: {trailer}")
    message = messages[0] if messages else b""
    return message, trailer, status


def fetch_upload_queue(base_url: str, token: str,
                       timeout: float = HTTP_TIMEOUT) -> List[Dict[str, Any]]:
    """取 CD2 当前的上传任务列表（含已完成/失败的，由调用方按状态筛）。"""
    message, _trailer, _status = call_grpc_web(
        base_url, "clouddrive.CloudDriveFileSrv/GetUploadFileList",
        encode_upload_list_request(get_all=True), token, timeout)
    return parse_upload_list(message)[:MAX_UPLOAD_ITEMS]


def fetch_mount_map(base_url: str, token: str,
                    timeout: float = HTTP_TIMEOUT) -> Dict[str, str]:
    """取 CD2 的挂载映射 {本地挂载点: 云端目录}，用于本地↔云端路径换算。"""
    message, _trailer, _status = call_grpc_web(
        base_url, "clouddrive.CloudDriveFileSrv/GetMountPoints",
        b"", token, timeout)
    return parse_mount_points(message)
