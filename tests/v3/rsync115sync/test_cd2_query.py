"""
CD2 上传队列查询的解析与匹配测试。

Tests for the CloudDrive2 upload-queue parsing and matching layer.

**为什么用真实报文而不是手工构造**：本模块的每一处细节（trailer 帧的 0x80
标志位、成功但无数据时消息体长度为 0、`destPath` 是云端路径而配置里的
`dest` 是挂载路径）都曾在探测阶段把一个"看起来正确"的实现判错。手工构造
的样本会把同样的误解写进测试里，于是测试全绿而线上全错。
真实报文取自 2026-11-08 的实际 CD2 实例（getUploadFileList / GetMountPoints），
只把 token 与文件内容本身裁掉了。

The fixtures are real captured frames: hand-built payloads would bake in the same
misreadings that the probe phase had to correct.

⚠️ 本文件**不导入 `app.*`**，可配 `--noconftest` 运行。
"""
import base64
import os
import sys

import pytest

# 插件目录通过文件位置定位，避免依赖宿主命名空间（本文件不走 app.plugins.*）
def _plugin_dir():
    for parent in __import__("pathlib").Path(__file__).resolve().parents:
        candidate = parent / "plugins.v3" / "rsync115sync"
        if (candidate / "cd2.py").is_file():
            return candidate
    pytest.skip("rsync115sync 源码目录未找到")


sys.path.insert(0, str(_plugin_dir()))
import cd2  # noqa: E402


# 真实的 GetUploadFileList 响应：一条正在上传的 3.8 GB 文件。
# 逐字节原样保存 —— 它同时覆盖了「消息帧 + trailer 帧」的拼接格式。
# A real response carrying one in-flight 3.8 GB file: message frame plus trailer
# frame, byte-for-byte as the server sent it.
REAL_UPLOAD_LIST = base64.b64decode(
    "AAAAASQIARKXAgp7LzExNW9wZW4vSG9tZVRoZWF0ZXIvVFYv5qyn576O5YmnL+WkqeidjiAoMjAx"
    "NCkge3RtZGJpZD02MDc5N30vU2Vhc29uIDAzL+WkqeidjiBTMDNFMDUuMTA4MHAuQW1hem9uLldF"
    "Qi1ETC5IMjY0LkREUCA1LjEubWt2EnsvMTE1b3Blbi9Ib21lVGhlYXRlci9UVi/mrKfnvo7liacv"
    "5aSp6J2OICgyMDE0KSB7dG1kYmlkPTYwNzk3fS9TZWFzb24gMDMv5aSp6J2OIFMwM0UwNS4xMDgw"
    "cC5BbWF6b24uV0VCLURMLkgyNjQuRERQIDUuMS5ta3YYnfrekg8ggICAwAoqDVByZXByb2Nlc3Np"
    "bmdAASCd+t6SDzABgAAAAA9ncnBjLXN0YXR1czowDQo="
)

# 真实的 GetMountPoints 响应：一条已挂载的映射。
# ⚠️ 关键点：mountPoint 是 **CD2 进程看到的宿主机路径**（/volume2/…），
# 而本插件配置里的 dest 是**容器内**路径（/CloudNAS/…）—— 两者字符串前缀
# 并不相同，正是这个差异让"直接 startswith 替换"的实现失效。
REAL_MOUNT_POINTS = base64.b64decode(
    "AAAAAD0KOwoVL3ZvbHVtZTIvQ2xvdWROQVMvMTE1EhQvMTE1b3Blbi9Ib21lVGhlYXRlci"
    "gBMIIIOGRIAVoDMTE1gAAAAA9ncnBjLXN0YXR1czowDQo="
)


def test_split_frames_separates_message_from_trailer():
    """
    消息帧与 trailer 帧必须分开 —— trailer 是文本，当 protobuf 解会得到垃圾。
    """
    messages, trailer, status = cd2.split_frames(REAL_UPLOAD_LIST)
    assert status == cd2.GRPC_OK
    assert "grpc-status:0" in trailer.replace(" ", "")
    assert len(messages) == 1
    # trailer 的文本绝不能混进消息体
    assert b"grpc-status" not in messages[0]


def test_parse_upload_list_reads_real_entry():
    """真实报文里的字段必须逐项读出（含 transfered 进度）。"""
    messages, _trailer, _status = cd2.split_frames(REAL_UPLOAD_LIST)
    total = cd2.parse_upload_total(messages[0])
    items = cd2.parse_upload_list(messages[0])

    assert total == 1
    assert len(items) == 1
    item = items[0]
    assert item["status"] == cd2.STATUS_PREPROCESSING
    assert item["size"] > 3_000_000_000
    assert 0 < item["transfered"] < item["size"]
    # destPath 是**云端**路径，不是挂载路径 —— 这是匹配逻辑的前提
    assert item["dest_path"].startswith("/115open/HomeTheater/")
    assert item["dest_path"].endswith(".mkv")
    assert item["key"] == item["dest_path"]


def test_progress_text_is_human_readable():
    """进度要能直接回答「还要不要等」。"""
    messages, _trailer, _status = cd2.split_frames(REAL_UPLOAD_LIST)
    item = cd2.parse_upload_list(messages[0])[0]
    text = cd2.progress_text(item)
    assert "GB" in text
    assert "/" in text


def test_parse_mount_points_reads_real_mapping():
    """挂载映射解析：本地挂载点 → 云端目录。"""
    messages, _trailer, _status = cd2.split_frames(REAL_MOUNT_POINTS)
    mounts = cd2.parse_mount_points(messages[0])
    assert mounts == {"/volume2/CloudNAS/115": "/115open/HomeTheater"}


def test_map_local_to_cloud_aligns_segments_not_string_prefix():
    """
    ⚠️ 回归：CD2 报宿主机路径、插件配容器路径，字符串前缀对不上但实为同一挂载。

    用 `dest.startswith(mountPoint)` 的实现会在这里失败，进而让整个功能
    在生产里一次都不生效（表现为"开了但没用"）。
    """
    mounts = {"/volume2/CloudNAS/115": "/115open/HomeTheater"}
    got = cd2.map_local_to_cloud(
        "/CloudNAS/115/TV/剧名/Season 01/剧名 S01E01.mkv", mounts)
    # 云端根目录由输入推导，避免把路径字面量再写一遍（写错就是同义反复）。
    # 挂载点对齐后，**剩余分量原样接在云端根目录后面** —— TV 属于剩余分量。
    assert got == mounts["/volume2/CloudNAS/115"] + "/TV/剧名/Season 01/剧名 S01E01.mkv"


def test_map_local_to_cloud_prefers_longest_tail():
    """兄弟挂载（/115 与 /1150）不得互相吃前缀。"""
    mounts = {
        "/volume2/CloudNAS/115": "/115open/HomeTheater",
        "/volume2/CloudNAS/1150": "/WRONG",
    }
    assert cd2.map_local_to_cloud("/CloudNAS/1150/x.mkv", mounts) == "/WRONG/x.mkv"
    assert (cd2.map_local_to_cloud("/CloudNAS/115/x.mkv", mounts)
            == "/115open/HomeTheater/x.mkv")


def test_map_local_to_cloud_returns_none_when_unmatched():
    """匹配不上要明确返回 None（调用方据此退回原样比对，而不是判定失败）。"""
    mounts = {"/volume2/CloudNAS/115": "/115open/HomeTheater"}
    assert cd2.map_local_to_cloud("/totally/elsewhere/x.mkv", mounts) is None
    assert cd2.map_local_to_cloud("/x/y.mkv", {}) is None


def test_dest_paths_for_key_produces_cloud_candidate():
    """
    端到端：把本插件的 key 换算成 CD2 报文里真实出现的路径。

    这是「能匹配上」的完整证据链 —— 用线上抓到的 dest_path 做期望值，
    而不是自己再推导一遍（那是同义反复）。
    """
    messages, _trailer, _status = cd2.split_frames(REAL_UPLOAD_LIST)
    real_dest = cd2.parse_upload_list(messages[0])[0]["dest_path"]

    mounts = {"/volume2/CloudNAS/115": "/115open/HomeTheater"}
    # ⚠️ dest 必须与挂载点**同源**：映射是 /volume2/CloudNAS/115 → /115open/HomeTheater，
    # 因此本地 /CloudNAS/115 对应云端 /115open/HomeTheater，`TV` 属于剩余分量。
    # 若把 dest 写成 /CloudNAS/115/TV，就会让 TV 出现两次 —— 那是测试自身不自洽。
    pairs = [{"name": "电视剧", "src": "/media/emby/TV", "dest": "/CloudNAS/115"}]
    rel = real_dest[len(mounts["/volume2/CloudNAS/115"]) + 1:]
    key = f"电视剧:{rel}"

    candidates = cd2.dest_paths_for_key(key, pairs, mounts)
    assert cd2.normalize_path(real_dest) in {cd2.normalize_path(c) for c in candidates}


def test_dest_paths_for_key_without_mount_map_still_returns_local_path():
    """没有挂载映射时仍返回本地拼接结果（用户可能直接把 dest 填成云端路径）。"""
    pairs = [{"name": "TV", "src": "/src/TV", "dest": "/CloudNAS/115/TV"}]
    assert cd2.dest_paths_for_key("TV:a/b.mkv", pairs, None) == [
        "/CloudNAS/115/TV/a/b.mkv"]


def test_find_in_flight_matches_exactly_not_by_prefix():
    """
    ⚠️ 回归：只能精确匹配，不能前缀匹配。

    前缀匹配会让「同目录里另一个正在传的文件」把整季的疑似全部压掉 ——
    那等于用一个假证据洗白一批真问题。
    """
    uploads = [
        {"dest_path": "/cloud/TV/S01/E01.mkv", "status": cd2.STATUS_TRANSFER},
        {"dest_path": "/cloud/TV/S01/E02.mkv", "status": cd2.STATUS_TRANSFER},
    ]
    hits = cd2.find_in_flight(["/cloud/TV/S01/E01.mkv"], uploads)
    assert len(hits) == 1
    assert hits[0]["dest_path"] == "/cloud/TV/S01/E01.mkv"

    # 目录前缀绝不能命中
    assert cd2.find_in_flight(["/cloud/TV/S01"], uploads) == []
    # 兄弟文件也不命中
    assert cd2.find_in_flight(["/cloud/TV/S01/E03.mkv"], uploads) == []


def test_find_in_flight_ignores_terminal_states():
    """
    ⚠️ 承重判据：只有"进行中"的状态才算在传。

    FINISH 必须**不**被当成在传 —— 传完了却仍然没有 strm 正是要抓的异常。
    ERROR / SKIPPED / IGNORED 同理：它们是真的没传上去，应当继续报警。
    若把 FINISH 也算进来，这个功能会把唯一真正的故障从清单里抹掉。
    """
    path = "/cloud/a.mkv"
    for status in (cd2.STATUS_FINISH, cd2.STATUS_ERROR, cd2.STATUS_SKIPPED,
                   cd2.STATUS_IGNORED, cd2.STATUS_CANCELLED):
        uploads = [{"dest_path": path, "status": status}]
        assert cd2.find_in_flight([path], uploads) == [], (
            f"状态 {status} 不应被当成正在上传")

    for status in (cd2.STATUS_PREPROCESSING, cd2.STATUS_TRANSFER,
                   cd2.STATUS_INQUEUE, cd2.STATUS_PAUSE,
                   cd2.STATUS_WAITFOR_PREPROCESSING):
        uploads = [{"dest_path": path, "status": status}]
        assert len(cd2.find_in_flight([path], uploads)) == 1, (
            f"状态 {status} 应被认定为正在上传")


def test_split_frames_defaults_to_ok_when_trailer_missing():
    """
    trailer 被反向代理吃掉时按成功处理。

    理由：把正常响应判成失败会让每个条目都退回"查不到"，这个保护等于白开；
    而真正的失败（鉴权）一定带 trailer，不会漏判。
    """
    messages, _trailer, status = cd2.split_frames(b"\x00\x00\x00\x00\x05hello")
    assert status == cd2.GRPC_OK
    assert messages == [b"hello"]


def test_split_frames_reports_unauthenticated():
    """鉴权失败的 trailer 必须被识别成 16，而不是当成空结果。"""
    trailer = b"grpc-status:16\r\ngrpc-message:No%20valid%20auth%20token\r\n"
    raw = (b"\x80" + len(trailer).to_bytes(4, "big") + trailer)
    _messages, _text, status = cd2.split_frames(raw)
    assert status == cd2.GRPC_UNAUTHENTICATED


def test_empty_message_body_is_zero_tasks_not_an_error():
    """
    ⚠️ 成功但队列为空时，消息帧长度为 0 —— 这是 0 条任务，不是失败。

    混淆这两者会让"CD2 里确实没有上传任务"被当成"查不到"，
    从而使这个保护永远不生效。
    """
    raw = b"\x00\x00\x00\x00\x00" + b"\x80\x00\x00\x00\x0fgrpc-status:0\r\n"
    messages, _trailer, status = cd2.split_frames(raw)
    assert status == cd2.GRPC_OK
    assert messages == [b""]
    assert cd2.parse_upload_total(messages[0]) == 0
    assert cd2.parse_upload_list(messages[0]) == []


def test_enum_request_roundtrip():
    """请求编码必须能被自己的解码器读回（getAll=1）。"""
    payload = cd2.encode_upload_list_request(get_all=True)
    fields = {f: v for f, _w, v in cd2._iter_fields(payload)}
    assert fields[cd2._REQ_GET_ALL] == 1


def test_frame_message_prefixes_length():
    """帧头格式：0x00 + 4 字节大端长度。"""
    framed = cd2.frame_message(b"abc")
    assert framed == b"\x00\x00\x00\x00\x03abc"


def test_normalize_path_handles_slashes_and_trailing():
    """路径归一化（匹配前统一形式）。"""
    assert cd2.normalize_path("/a//b/") == "/a/b"
    assert cd2.normalize_path("/a\\b\\") == "/a/b"
    assert cd2.normalize_path("") == ""
    assert cd2.normalize_path(None) == ""
    assert cd2.normalize_path("/") == "/"


def test_auth_failure_in_http_headers_is_not_an_empty_queue():
    """
    ⚠️ 回归（实测踩到的真 bug）：鉴权失败时 grpc-status 在 **HTTP 响应头**里，
    响应体为空；而成功时它在 trailer 帧里。

    只读 trailer 的实现会把「token 无效」读成「队列为空」—— 于是保护看起来
    在工作、实际一次都没生效，而且日志里连一条失败都没有。
    这里用假的 urlopen 复现这两种响应的**位置差异**，锁住修复。
    """
    import io
    import urllib.error

    class FakeResponse:
        def __init__(self, headers, body):
            self.status = 200
            self.headers = headers
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    real_urlopen = cd2.urllib.request.urlopen

    try:
        # 失败：状态在响应头，响应体为空
        cd2.urllib.request.urlopen = lambda *a, **k: FakeResponse(
            {"grpc-status": "16", "grpc-message": "Invalid%20auth%20token"}, b"")
        with pytest.raises(cd2.CloudDrive2Error) as err:
            cd2.fetch_upload_queue("http://x:19798", "bad-token")
        assert "Token" in str(err.value)

        # 成功：状态在 trailer 帧里（用真实抓包报文）
        cd2.urllib.request.urlopen = lambda *a, **k: FakeResponse({}, REAL_UPLOAD_LIST)
        items = cd2.fetch_upload_queue("http://x:19798", "good-token")
        assert len(items) == 1
    finally:
        cd2.urllib.request.urlopen = real_urlopen


def test_stuck_task_loses_its_suppression_after_the_deadline():
    """
    ⚠️ 承重：卡死的 CD2 任务必须**失去**豁免，否则真故障被永久藏起来。

    没有这道边界时，一个永远停在「预处理中」的任务会让对应文件再也不出现在
    疑似清单里 —— 用户看到"一切正常"，而云端文件其实是残缺的。
    这个模块的目标是减少误报，不是把真问题藏起来。
    """
    stuck = {"dest_path": "/c/a.mkv", "status": cd2.STATUS_PREPROCESSING}

    # 刚到期转疑似：允许压住（它确实可能刚开始传）
    assert cd2.should_suppress(stuck, age_secs=60) is True
    # 卡了一整天：不再压住
    assert cd2.should_suppress(stuck, age_secs=25 * 3600) is False


def test_pause_gets_a_longer_but_still_finite_exemption():
    """暂停是主动动作，可以豁免更久 —— 但同样必须有上限。"""
    paused = {"dest_path": "/c/a.mkv", "status": cd2.STATUS_PAUSE}
    assert cd2.should_suppress(paused, 5 * 3600) is True       # 6h 仍在豁免内
    assert cd2.should_suppress(paused, 7 * 3600) is True       # 超过 6h 但没超过 24h
    assert cd2.should_suppress(paused, 25 * 3600) is False     # 忘了一整天


def test_terminal_states_are_never_suppressing_regardless_of_age():
    """终态一律不豁免（无论多新）—— 完成/失败的文件必须照常报警。"""
    for status in (cd2.STATUS_FINISH, cd2.STATUS_ERROR, cd2.STATUS_SKIPPED,
                   cd2.STATUS_IGNORED, cd2.STATUS_CANCELLED):
        item = {"dest_path": "/c/a.mkv", "status": status}
        assert cd2.should_suppress(item, age_secs=1) is False, (
            f"状态 {status} 不应压制告警")
        assert cd2.suppression_seconds(item) == 0.0
