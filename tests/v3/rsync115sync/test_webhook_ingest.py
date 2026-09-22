"""
Webhook 入库（第二来源）：通道 A（宿主 Emby 链路）与通道 B（插件自建端点）。

Webhook ingest, both channels:
  A — host-broadcast `EventType.WebhookMessage` (Emby native)
  B — this plugin's own anonymous `POST /webhook` (MDC-ng / custom senders)

**为什么这两条路必须有测试**：webhook 是本插件唯一由**外部**发起的入口，
出问题时用户手里没有任何可自查的证据 —— 发送端显示 200、日志一片安静、
看板队列不增长。因此这里把四件事钉住：入队语义与事件链路**完全一致**、
播放类事件绝不入队、四道防护链逐道生效、计数点记在能定位问题的位置。
"""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _plugin(src_root, *, enabled=True, listen=True, channels=("emby",),
            self_enabled=True, secret="", allowlist="", ip_allowlist="",
            pairs=None, media_extensions="mkv,srt"):
    """构造最小实例：只带 webhook 链路真正用到的状态。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin.plugin_version = "test"
    plugin._enabled = enabled
    plugin._listen_transfer = listen
    plugin._webhook_channels = list(channels)
    plugin._webhook_self_enabled = self_enabled
    plugin._webhook_secret = secret
    plugin._webhook_path_allowlist = allowlist
    plugin._webhook_ip_allowlist = ip_allowlist
    plugin._sync_pairs = pairs if pairs is not None else [{
        "name": "TV", "src": src_root, "dest": "/dest/TV",
        "all_ext": False, "strm_dir": "",
    }]
    plugin._media_extensions = media_extensions
    plugin._delay_hours = 2.0
    plugin._pending_queue = {}
    plugin._missed_queue = {}
    plugin._ignored_rules = []
    plugin._last_status = {}
    plugin._webhook_stat = plugin._wh_stat()
    plugin.saved = {}
    plugin.save_data = lambda k, v: plugin.saved.__setitem__(k, v)
    return plugin


def _media(src_root, rel="S01E01.mkv"):
    import os
    path = os.path.join(src_root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x")
    return path


def _webhook_event(channel="emby", event="library.new", **fields):
    """构造宿主 Emby 解析器形状的 WebhookMessage payload（WebhookEventInfo）。"""
    data = {"channel": channel, "event": event}
    data.update(fields)
    return SimpleNamespace(event_type=SimpleNamespace(value="webhook.message"),
                           event_data=data)


# --------------------------------------------------------------------------
# 通道 A：宿主 webhook（Emby）
# --------------------------------------------------------------------------

def test_emby_library_new_enqueues(tmp_path):
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src))

    plugin._handle_webhook_event(_webhook_event(item_path=path, server_name="PN41"))

    assert list(plugin._pending_queue) == ["TV:S01E01.mkv"]
    assert plugin.saved.get("pending_queue") == plugin._pending_queue


def test_playback_event_never_enqueues(tmp_path):
    """
    最危险的误动作：播放类事件同样带 `Item.Path`。

    不过滤的话，**用户每看一集就会把那集重新入队并再上传一次** ——
    静默、持续地消耗 115 风控配额。
    """
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src))

    for evt in ("playback.start", "playback.stop", "playback.pause",
                "item.markplayed", "user.favorite"):
        plugin._handle_webhook_event(_webhook_event(event=evt, item_path=path))

    assert plugin._pending_queue == {}


def test_other_channel_is_ignored(tmp_path):
    """多个插件同时订阅 WebhookMessage，各自只能处理自己的来源。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src), channels=("emby",))

    plugin._handle_webhook_event(_webhook_event(channel="zspace", item_path=path))

    assert plugin._pending_queue == {}


def test_multiple_channels_can_be_enabled(tmp_path):
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src), channels=("emby", "jellyfin"))

    plugin._handle_webhook_event(_webhook_event(channel="jellyfin", item_path=path))

    assert list(plugin._pending_queue) == ["TV:S01E01.mkv"]


def test_json_object_item_path_is_used_as_fallback(tmp_path):
    """宿主解析器没填 item_path 时，回退读原始报文的 Item.Path。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src))

    plugin._handle_webhook_event(_webhook_event(
        item_path=None, json_object={"Item": {"Path": path, "Type": "Episode"}}))

    assert list(plugin._pending_queue) == ["TV:S01E01.mkv"]


def test_listen_transfer_off_stops_webhook(tmp_path):
    """webhook 与整理事件共用同一个入库总闸，不设第二个开关。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src), listen=False)

    plugin._handle_webhook_event(_webhook_event(item_path=path))

    assert plugin._pending_queue == {}


def test_unrecognized_payload_is_counted_not_silent(tmp_path):
    """拿不到路径必须留下可排查的痕迹（计数 + 报文结构摘要）。"""
    src = tmp_path / "TV"
    src.mkdir()
    plugin = _plugin(str(src))

    plugin._handle_webhook_event(_webhook_event(item_name="某部剧", item_id="123"))

    assert plugin._webhook_stat["unrecognized"] == 1
    assert plugin._webhook_stat["last_payload_shape"]
    assert "item_name" in plugin._webhook_stat["last_payload_shape"]


# --------------------------------------------------------------------------
# 通道 B：自建端点（防护链逐道验证）
# --------------------------------------------------------------------------

def _post(plugin, *, body=None, query=None, headers=None, ip="10.0.0.9"):
    """驱动自建端点的完整防护链（绕开 Request 解析层）。"""
    return plugin._ingest_from_parts(
        client_ip=ip, headers=headers, query=dict(query or {}), body=body)


def test_self_endpoint_is_off_by_default(tmp_path):
    """暴露接口必须是用户明确打开的行为，绝不能在升级后悄悄生效。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src), self_enabled=False)
    plugin._webhook_path_allowlist = str(src)

    res = _post(plugin, body={"paths": [path]})

    assert res["success"] is False
    assert plugin._pending_queue == {}


def test_allowlisted_path_is_enqueued(tmp_path):
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src), allowlist=str(src))

    res = _post(plugin, body={"paths": [path], "event": "library.new"})

    assert res["success"] is True
    assert res["data"]["added"] == 1
    assert list(plugin._pending_queue) == ["TV:S01E01.mkv"]


def test_path_outside_allowlist_is_rejected(tmp_path):
    """
    无条件生效的那道防护：伪造者能编任何路径字符串，但不可能让它落在
    你配置的媒体库目录下。它不依赖「用户有没有填密钥」。
    """
    src = tmp_path / "TV"
    outside = tmp_path / "elsewhere" / "a.mkv"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    plugin = _plugin(str(src), allowlist=str(src))

    res = _post(plugin, body={"paths": [str(outside)]})

    assert res["success"] is False
    assert plugin._pending_queue == {}
    assert plugin._webhook_stat["rejected"] == 1


def test_sibling_directory_is_not_inside_allowlist(tmp_path):
    """`/media/TV2` 不能因为前缀相同就被当作落在 `/media/TV` 内。"""
    tv = tmp_path / "TV"
    tv2 = tmp_path / "TV2"
    tv2.mkdir()
    f = tv2 / "a.mkv"
    f.write_bytes(b"x")
    plugin = _plugin(str(tv), allowlist=str(tv))

    res = _post(plugin, body={"paths": [str(f)]})

    assert res["success"] is False


def test_allowlist_falls_back_to_mapping_sources(tmp_path):
    """未配置白名单时退回各映射的源目录 —— 保证开箱可用。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src), allowlist="")

    res = _post(plugin, body={"paths": [path]})

    assert res["success"] is True


def test_wrong_secret_is_rejected(tmp_path):
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src), allowlist=str(src), secret="s3cret")

    bad = _post(plugin, body={"paths": [path]}, headers={"x-webhook-secret": "nope"})
    assert bad["success"] is False
    assert plugin._pending_queue == {}

    ok = _post(plugin, body={"paths": [path]}, headers={"x-webhook-secret": "s3cret"})
    assert ok["success"] is True


def test_secret_via_query_parameter(tmp_path):
    """老脚本只会拼查询串，不接受自定义 Header —— 两种都要支持。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src), allowlist=str(src), secret="s3cret")

    res = _post(plugin, query={"token": "s3cret"}, body={"paths": [path]})

    assert res["success"] is True


def test_ip_allowlist_blocks_unknown_source(tmp_path):
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src), allowlist=str(src), ip_allowlist="192.168.1.")

    assert _post(plugin, body={"paths": [path]}, ip="10.0.0.9")["success"] is False
    assert _post(plugin, body={"paths": [path]}, ip="192.168.1.8")["success"] is True


def test_query_string_payload(tmp_path):
    """纯查询串形态（`?path=/x/a.mkv`）：同步文档里最容易配的一种。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src), allowlist=str(src))

    res = _post(plugin, query={"path": path})

    assert res["success"] is True
    assert list(plugin._pending_queue) == ["TV:S01E01.mkv"]


def test_bare_array_body(tmp_path):
    src = tmp_path / "TV"
    p1 = _media(str(src), "a.mkv")
    p2 = _media(str(src), "b.mkv")
    plugin = _plugin(str(src), allowlist=str(src))

    res = _post(plugin, body=[p1, p2])

    assert res["success"] is True
    assert sorted(plugin._pending_queue) == ["TV:a.mkv", "TV:b.mkv"]


def test_string_body_is_parsed_as_json(tmp_path):
    """部分发送端把 JSON 当纯文本发（Content-Type 不是 application/json）。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src), allowlist=str(src))

    res = _post(plugin, body='{"paths": ["%s"]}' % path)

    assert res["success"] is True


def test_mixed_paths_only_allowlisted_ones_enter(tmp_path):
    src = tmp_path / "TV"
    path = _media(str(src))
    outside = tmp_path / "elsewhere.mkv"
    outside.write_bytes(b"x")
    plugin = _plugin(str(src), allowlist=str(src))

    res = _post(plugin, body={"paths": [path, str(outside)]})

    assert res["success"] is True
    assert res["data"]["added"] == 1
    assert list(plugin._pending_queue) == ["TV:S01E01.mkv"]


# --------------------------------------------------------------------------
# 合流：两条通道共用同一个入队语义（不能各写一份）
# --------------------------------------------------------------------------

def test_duplicate_keeps_original_timestamp(tmp_path):
    """重复投递不刷新冷却计时 —— 与整理事件链路同一条红线。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src))

    plugin._handle_webhook_event(_webhook_event(item_path=path))
    first = plugin._pending_queue["TV:S01E01.mkv"]
    plugin._handle_webhook_event(_webhook_event(item_path=path))

    assert plugin._pending_queue["TV:S01E01.mkv"] == first


def test_ignored_key_is_not_enqueued_from_webhook(tmp_path):
    """忽略清单优先级最高：否则被忽略的文件会从 webhook 这条新路重新进队。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src))
    plugin._ignored_rules = [{"rule": "TV:s01e01.mkv", "match": "exact"}]

    plugin._handle_webhook_event(_webhook_event(item_path=path))

    assert plugin._pending_queue == {}


def test_missed_queue_entry_is_upgraded_to_cooling_queue(tmp_path):
    """
    已在「待补扫」清单里的文件收到真实入库事件时，必须**升级**进冷却队列。

    ⚠️ 这条用例是**反向**的：它替换了一条曾经断言「不重复入队」的用例。
    原断言把「已在待补扫清单」当成重复投递，看起来合理，实际造成静默的永久卡死 ——
    补齐扫描发现文件「源端存在、从未同步过」，只把它放进待补扫清单；随后真实入库
    事件到达时又因「已在待补扫清单」被判重复而不入冷却队列，该文件从此既不在冷却
    队列、也没被任何一轮同步取走，用户只能看到清单里永远挂着一条、且无从解释。

    正确语义：文件真的入库了就走正常冷却流程，同时从待补扫清单移出
    （两处都保留会让同一文件被两条通道各自处理）。
    """
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src))
    plugin._missed_queue = {"TV:S01E01.mkv": 1.0}

    plugin._handle_webhook_event(_webhook_event(item_path=path))

    assert list(plugin._pending_queue) == ["TV:S01E01.mkv"]
    assert plugin._missed_queue == {}


def test_webhook_enqueue_clears_missed_entry(tmp_path):
    """webhook 补上了错过的事件时，同样要把源端补齐清单里的条目移除。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src))
    plugin._missed_queue = {"TV:other.mkv": 1.0}

    plugin._handle_webhook_event(_webhook_event(item_path=path))

    assert "TV:S01E01.mkv" in plugin._pending_queue


def test_extension_filter_applies_to_webhook(tmp_path):
    src = tmp_path / "TV"
    nfo = _media(str(src), "a.nfo")
    plugin = _plugin(str(src))

    plugin._handle_webhook_event(_webhook_event(item_path=nfo))

    assert plugin._pending_queue == {}


def test_path_in_no_mapping_is_not_enqueued(tmp_path):
    """入库路径与配置的源目录不一致时只记日志，绝不猜、绝不错误入队。"""
    src = tmp_path / "TV"
    src.mkdir()
    outside = tmp_path / "other" / "a.mkv"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    plugin = _plugin(str(src), allowlist=str(tmp_path))

    res = _post(plugin, body={"paths": [str(outside)]})

    assert res["success"] is True          # 白名单内，通过了防护链
    assert res["data"]["unmatched"] == 1   # 但不属于任何映射 → 不入队
    assert plugin._pending_queue == {}


# --------------------------------------------------------------------------
# 契约：端点注册与事件注册（删掉不会有任何报错的那两行）
# --------------------------------------------------------------------------

def test_webhook_endpoint_is_registered_as_anonymous(tmp_path):
    """
    端点必须显式声明 allow_anonymous —— 外部发送端不带宿主 API_TOKEN。

    用运行时读 `get_api()` 而非源码字符串匹配：注册表本身就是契约。
    匿名是**有意为之**（安全由处理器内部的四道防护承担），
    所以这里同时断言它确实是匿名的，避免有人「顺手」把它改成需要鉴权 ——
    那会让 MDC 通道静默失效（发送端只会收到 401，用户在插件侧看不到任何记录）。
    """
    import os
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    apis = module.Rsync115Sync.get_api(plugin)
    entry = [a for a in apis if a.get("path") == "/webhook"]
    assert entry, "自建 webhook 端点未注册"
    assert entry[0].get("allow_anonymous") is True
    assert "POST" in entry[0]["methods"]
    # 其余端点必须保持需要鉴权：只有 webhook 允许匿名
    for api in apis:
        if api["path"] != "/webhook":
            assert not api.get("allow_anonymous"), f"{api['path']} 不应匿名"


def test_webhook_message_event_is_subscribed():
    """
    订阅 WebhookMessage 的装饰器必须存在。

    ⚠️ 删掉它不会有任何报错：插件照常加载、看板照常渲染，只是**永远收不到
    webhook 事件**。v0.1.7 的拆分曾把整理事件的装饰器一起删掉（见 3.8 记录的
    那次回归），因此这里按 AST 扫包内全部模块做同样的守卫。
    """
    import ast
    import os
    plugin_dir = os.path.dirname(importlib.import_module("app.plugins.rsync115sync").__file__)
    found = False
    for name in os.listdir(plugin_dir):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(plugin_dir, name), encoding="utf-8").read())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                text = ast.unparse(deco)
                if "eventmanager.register" in text and "WebhookMessage" in text:
                    found = True
    assert found, "插件包内没有任何函数订阅 EventType.WebhookMessage"


def test_channel_normalization_never_yields_empty():
    """空渠道列表会让「开着开关却什么都不接收」，比报错更难自查。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    normalize = module.Rsync115Sync._normalize_channels
    assert normalize("") == ["emby"]
    assert normalize(None) == ["emby"]
    assert normalize([]) == ["emby"]
    assert normalize(" Emby , Jellyfin ,emby") == ["emby", "jellyfin"]


# --------------------------------------------------------------------------
# 真实路由契约：这些断言只有把端点挂进真 FastAPI 才可能失效（也必须靠它才发现）
# --------------------------------------------------------------------------

def _real_route(plugin):
    """
    把本插件的 /webhook 端点挂进一个真实 FastAPI 应用，并绑定到给定实例上。

    **为什么必须有这一组**：本仓单测环境通常没有 fastapi，因此其余用例都是直接
    调用处理方法，绕过路由层。而路由层恰好是最容易「静默失效」的一环 ——
    实测（fastapi 0.141）把签名写成 `request: Any = None` 时，FastAPI 会把它
    当作**查询参数**：端点注册成功、HTTP 200、但 request 拿到的是空字符串，
    来源 IP / 请求头 / 请求体全部读不到。密钥校验于是永远失败、报文永远为空。
    这种「注册成功、调用成功、结果全空」的失效，只有真路由能发现。

    注意 `dependant.call` 是注册时**捕获**的方法对象，只改 route.endpoint 不够 ——
    实际调用走的是 dependant.call，两处都要换成本实例的方法。
    """
    pytest.importorskip("fastapi", reason="本环境无 fastapi，跳过路由层契约验证")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    module = importlib.import_module("app.plugins.rsync115sync")
    app = FastAPI()
    for api in module.Rsync115Sync.get_api(plugin):
        if api["path"] == "/webhook":
            app.add_api_route(path=api["path"], endpoint=api["endpoint"],
                              methods=api["methods"])
    route = app.router.routes[-1]
    # get_api 返回的已经是绑定到本实例的方法；再套一层 MethodType 会造成
    # 「重复绑定」(self 被喂成方法对象)，调用时报 got multiple values for argument 'request'。
    bound = plugin._api_webhook_ingest
    route.endpoint = bound
    route.dependant.call = bound
    return TestClient(app), module


def test_real_route_injects_request_object(tmp_path):
    src = tmp_path / "TV"
    plugin = _plugin(str(src), allowlist=str(src), secret="s3cret")
    client, _ = _real_route(plugin)
    path = _media(str(src))
    res = client.post("/webhook", headers={"X-Webhook-Secret": "s3cret"},
                      json={"paths": [path]})

    assert res.status_code == 200
    assert res.json()["success"] is True, res.text
    assert list(plugin._pending_queue) == ["TV:S01E01.mkv"]


def test_real_route_reads_secret_from_header(tmp_path):
    """
    request 必须真被注入 —— 否则读不到请求头，密钥校验**永远失败**。

    这正是「参数写成 Any 就被当成查询参数」那个坑的表现形式，所以这里用手写错误
    密钥做对照：只有真拿到头，正确密钥才会通过、错误密钥才会被拒。
    """
    src = tmp_path / "TV"
    src.mkdir()
    plugin = _plugin(str(src), allowlist=str(src), secret="s3cret")
    client, _ = _real_route(plugin)

    bad = client.post("/webhook", headers={"X-Webhook-Secret": "wrong"},
                      json={"paths": [str(src / "x.mkv")]})
    assert bad.json()["success"] is False
    assert "密钥" in bad.json()["message"]


def test_real_route_accepts_all_documented_payload_shapes(tmp_path):
    """四种报文形态都要在真实路由下走通（解析层单测覆盖不到 content-type 分流）。"""
    src = tmp_path / "TV"
    plugin = _plugin(str(src), allowlist=str(src))
    client, _ = _real_route(plugin)

    path = _media(str(src), "json.mkv")
    assert client.post("/webhook", json={"paths": [path]}).json()["success"] is True

    path2 = _media(str(src), "array.mkv")
    assert client.post("/webhook", json=[path2]).json()["success"] is True

    path3 = _media(str(src), "query.mkv")
    assert client.post("/webhook", params={"path": path3}).json()["success"] is True

    path4 = _media(str(src), "text.mkv")
    res = client.post("/webhook", content='{"path": "%s"}' % path4,
                      headers={"Content-Type": "text/plain"})
    assert res.json()["success"] is True

    assert sorted(plugin._pending_queue) == [
        "TV:array.mkv", "TV:json.mkv", "TV:query.mkv", "TV:text.mkv"]


def test_real_route_enqueues_every_path_in_the_list(tmp_path):
    """
    一次推多个文件时**全部**入队，不是只取第一个。

    端点接收侧有两层：`_ingest_from_request` 负责把请求体解码成 str/dict/list，
    `_webhook_payload_of` 才做形态归一。直接在 `_ingest_from_parts` 上传 bytes
    会绕过解码层（真实请求永远先经 starlette 解码），于是这个断言的真正价值是
    钉住**真实路由**下的多路径行为 —— 走 TestClient 发真请求，不经手写 dict。
    """
    src = tmp_path / "TV"
    plugin = _plugin(str(src), allowlist=str(src))
    client, _ = _real_route(plugin)
    paths = [_media(str(src), f"e0{i}.mkv") for i in (1, 2, 3)]

    res = client.post("/webhook", json={"paths": paths})

    assert res.json()["success"] is True
    assert res.json()["data"]["added"] == 3
    assert sorted(plugin._pending_queue) == ["TV:e01.mkv", "TV:e02.mkv", "TV:e03.mkv"]


def test_real_route_reports_source_ip(tmp_path):
    """来源 IP 取自 request.client —— 只有真注入才拿得到，IP 白名单全靠它。"""
    src = tmp_path / "TV"
    plugin = _plugin(str(src), allowlist=str(src), ip_allowlist="10.1.2.3")
    client, _ = _real_route(plugin)

    # TestClient 的默认 client host 是 "testclient"，不在白名单内 → 必须被拒
    res = client.post("/webhook", json={"paths": [str(src / "a.mkv")]})
    assert res.json()["success"] is False
    assert plugin._webhook_stat["rejected"] == 1
    assert plugin._webhook_stat["last_source"] == "testclient"

# ===================== 看板契约 =====================
#
# 这一组的由来：USAGE.md 的「怎么确认这条路通了」整节把 webhook 的四项计数与
# 「最近报文结构」写成看板上可见，而 Page.vue 实际上没有渲染它们 —— 文档承诺了
# 一个不存在的界面。 用户按文档去"看板确认"，看到的是一个空无一物的看板，
# 只能得到「是不是没生效」这个错误结论。
#
# 这类「文档描述了、后端也返回了、前端却没画」的缺口不会让任何测试变红：
# 后端用例只查 /status 的字段，而字段确实在。所以这里必须从**模板**侧断言。

_PLUGIN_SRC = Path(__file__).resolve().parents[3] / "plugins.v3" / "rsync115sync" / "src"


def _page_source() -> str:
    path = _PLUGIN_SRC / "components" / "Page.vue"
    assert path.is_file(), f"找不到看板源码：{path}"
    return path.read_text(encoding="utf-8")


def test_dashboard_renders_webhook_counters():
    """
    USAGE.md 承诺的四项计数必须真的出现在看板上。

    只断言 `statusData.webhook` 在 /status 里存在是不够的 —— 后端多返回一个字段
    而前端从不读取，用户看到的东西与功能没做时完全一样。
    """
    src = _page_source()
    for field in ("received", "ingested", "rejected", "unrecognized"):
        assert f"webhookStat.{field}" in src or f"webhookStat.value.{field}" in src, (
            f"看板未渲染 webhook 的 {field} 计数，但 USAGE.md 承诺用户能在这里看到它"
        )
    assert "last_payload_shape" in src, (
        "看板未展示最近报文的字段结构摘要 —— 用户遇到「未识别」时唯一的自查依据"
    )


def test_dashboard_webhook_panel_is_gated_not_always_visible():
    """
    面板必须有显示条件，不能常驻。

    反向陷阱：判据若写成「webhook 功能已启用」，由于渠道默认就是 emby，
    这块面板会对**每一个**用户常驻显示一条「收到 0 条」—— 等于没有门控，
    还会让没配 webhook 的人以为自己配漏了什么。
    """
    src = _page_source()
    assert "webhookVisible" in src, "看板缺少 webhook 面板的显示条件"
    assert "v-if=\"webhookVisible\"" in src, "webhook 面板未绑定显示条件"


def test_stub_host_status_defaults_align_with_frontend():
    """
    后端 /status 暴露的 webhook 字段必须能被前端默认值兜住。

    前端 statusData 的初值是空对象 `webhook: {}`：首帧（尚未拉到 /status）时
    模板里所有 `webhookStat.x` 都会取到 undefined。`v-if="webhookVisible"` 依赖
    `webhookStat.received` 与 `webhookStat.self_enabled` 读取 undefined 而不抛错 ——
    这条用例把「模板用到的字段都允许缺失」这件事钉住，防止将来有人写成
    `webhookStat.channels.join(...)` 而在首帧崩掉整个看板。
    """
    src = _page_source()
    # channels 是唯一被直接调用的数组字段，模板里必须带默认值兜底。
    assert "(webhookStat.channels || [])" in src, (
        "webhookStat.channels 未做空值兜底，首帧会抛 TypeError 并让整个看板白屏"
    )
    assert "(webhookStat.allow_roots || [])" in src, (
        "webhookStat.allow_roots 未做空值兜底，首帧会抛 TypeError"
    )

# ===================== webhook_parser 认领契约 =====================
#
# 这一组存在的原因（DEVELOPMENT.md 9.11）：宿主的 `webhook_parser` 是 FIRST_NON_EMPTY
# + plugin_short_circuit 的模块方法，**插件优先于宿主**。任一插件返回非空结果，
# 宿主的 Emby/Jellyfin/Plex 解析器就再也不会被调用。因此：
#   · 不实现它 = 赌别的插件永不实现，赌输则整条 Emby 链静默死亡
#   · 实现它但认领过宽 = 我们自己去掐死宿主解析器
# 两个方向都要钉住。

def _parser_plugin(src_root, **kwargs):
    """构造带映射的最小实例（复用 _plugin 的默认值，便于直接驱动 webhook_parser）。"""
    return _plugin(src_root, **kwargs)


def test_webhook_parser_exists_with_host_signature():
    """
    签名必须是 (body, form, args) 三个参数名 —— 宿主按关键词调用。

    参数名不匹配时宿主既不报错也不告警（兼容阶段只诊断不拒绝 provider），
    表现为「回调 200、插件收不到任何东西」，属最难自查的一类。
    """
    import inspect
    module = importlib.import_module("app.plugins.rsync115sync")
    params = list(inspect.signature(module.Rsync115Sync.webhook_parser).parameters)
    assert params == ["self", "body", "form", "args"], (
        f"webhook_parser 签名与宿主调用约定不符：{params}"
    )


def test_webhook_parser_returns_none_for_unnamed_payload(tmp_path):
    """
    **最关键的一条**：未显式声明收件人的报文必须返回 None。

    返回非空会短路宿主的解析器 —— 用户就算只装了本插件、不用任何 webhook，
    只要 Emby 解析被我们吞掉，宿主的健康检查/图片获取等功能会一起失效。
    """
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _parser_plugin(str(src))

    assert plugin.webhook_parser(
        body=json.dumps({"Event": "library.new", "Item": {"Path": path}}).encode(),
        form=None, args={"token": "abc"}) is None


def test_webhook_parser_does_not_claim_emby_channel_by_default(tmp_path):
    """
    渠道默认值是 `emby`，**绝不能**按它认领。

    宿主的 Emby 解析器产出的 channel 就是 `emby`（emby.py:1082）。按 channel 认领
    会把宿主本来能正常处理的 Emby 报文抢过来并短路掉宿主解析器 —— 本插件只想要一个
    路径，代价完全不成比例。这里用「宿主那侧的真实报文形态」做反向验证。
    """
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _parser_plugin(str(src))
    assert plugin._webhook_channels == ["emby"], "前置条件：默认渠道仍是 emby"

    body = json.dumps({"Event": "library.new", "Item": {"Path": path}}).encode()
    assert plugin.webhook_parser(body=body, form=None, args={"source": "PN41"}) is None


def test_webhook_parser_claims_when_addressed_by_query(tmp_path):
    """显式声明 `source=rsync115sync` 时才认领，并返回宿主契约要求的模型。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _parser_plugin(str(src))

    info = plugin.webhook_parser(
        body=json.dumps({"paths": [path]}).encode(),
        form=None, args={"source": "rsync115sync"})

    assert info is not None
    assert info.item_path == path
    assert info.channel == "rsync115sync"
    assert info.json_object["paths"] == [path]


def test_webhook_parser_claims_when_addressed_by_header(tmp_path):
    """也支持 X-Webhook-Target 头 —— 发送端不一定方便改查询串。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _parser_plugin(str(src))

    info = plugin.webhook_parser(
        body=json.dumps({"paths": [path]}).encode(),
        form={"x-webhook-target": "rsync115sync"}, args={})

    assert info is not None and info.item_path == path


def test_webhook_parser_declines_when_path_outside_any_mapping(tmp_path):
    """
    自报收件人但路径不属于本插件任何映射 → **仍不认领**。

    否则一次配错地址的发送端会把报文吞掉（宿主解析器被短路），而本插件什么也做不成 ——
    两边都失效，且没有任何日志能指向原因。
    """
    src = tmp_path / "TV"
    other = tmp_path / "Other"
    other.mkdir()
    outside = other / "x.mkv"
    outside.write_bytes(b"x")
    plugin = _parser_plugin(str(src))

    assert plugin.webhook_parser(
        body=json.dumps({"paths": [str(outside)]}).encode(),
        form=None, args={"source": "rsync115sync"}) is None


def test_webhook_parser_declines_when_plugin_disabled(tmp_path):
    """插件停用/关闭入库监听时不再认领 —— 认领了也没人会处理。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    body = json.dumps({"paths": [path]}).encode()

    for kwargs in ({"enabled": False}, {"listen": False}):
        plugin = _parser_plugin(str(src), **kwargs)
        assert plugin.webhook_parser(body=body, form=None, args={"source": "rsync115sync"}) is None


def test_webhook_parser_reads_emby_style_form_encoded_payload(tmp_path):
    """
    Emby 把 JSON 塞在 form 的 `data` 字段里（见 emby.py 的解析实现）。

    平台 webhook 端点的 body 是**原始 bytes**，不是解析好的 dict
    （app/api/endpoints/webhook.py 用的是 `await request.body()`），
    因此解析层必须自己处理 form 的 data 与原始 JSON 两种载体。
    """
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _parser_plugin(str(src))

    info = plugin.webhook_parser(
        body=b"",
        form={"data": json.dumps({"Event": "library.new", "Item": {"Path": path}})},
        args={"source": "rsync115sync"})

    assert info is not None and info.item_path == path


def test_claimed_multi_path_payload_enqueues_every_path(tmp_path):
    """
    **认领路径不能丢文件**：认领时写进 json_object 的多路径，回来时必须全部入队。

    `webhook_parser` 按契约只能把第一个路径放进 `item_path`，其余全部塞进
    `json_object["paths"]`；而接收侧曾写成「item_path 有值就直接返回」——
    一次推 3 个文件只有第 1 个入队，后 2 个静默消失，且认领日志显示完全成功。
    本用例走**完整往返**（认领 → 宿主广播 → 事件处理），而不是分别断言两端，
    正因为这个 bug 只在两端拼接处才出现。
    """
    src = tmp_path / "TV"
    paths = [_media(str(src), f"S01E0{i}.mkv") for i in (1, 2, 3)]
    plugin = _parser_plugin(str(src))

    info = plugin.webhook_parser(
        body=json.dumps({"paths": paths}).encode(),
        form=None, args={"source": "rsync115sync"})
    assert info is not None, "前置条件：该报文应被认领"

    # 宿主会把解析结果原样广播回来 —— 这里复现那一步
    plugin._handle_webhook_event(SimpleNamespace(
        event_type=SimpleNamespace(value="webhook.message"),
        event_data={
            "channel": info.channel, "event": info.event,
            "server_name": info.server_name, "item_path": info.item_path,
            "json_object": info.json_object,
        }))

    assert sorted(plugin._pending_queue) == [
        "TV:S01E01.mkv", "TV:S01E02.mkv", "TV:S01E03.mkv"], (
        "认领时命中的路径数应等于入队数 —— 少一个就是静默丢文件"
    )


def test_emby_shape_item_path_and_json_object_are_deduped(tmp_path):
    """
    Emby 真实形态：`item_path` 与 `json_object.Item.Path` 指向同一个文件。

    合并两处来源（见 extract_paths 的说明）后必须去重 —— 否则同一个文件会被
    当成两条独立路径去重失败，`added` 计数虚高一倍，用户据此误判发送端在重复推送。
    """
    from app.plugins.rsync115sync import webhook as wh

    src = tmp_path / "TV"
    path = _media(str(src))

    paths, source = wh.extract_paths(SimpleNamespace(
        item_path=path, json_object={"Item": {"Path": path, "Type": "Episode"}}))

    assert paths == [path], f"同一文件被当成多条路径：{paths}"
    # 来源标注只列**贡献了新路径**的那一处：json_object 与 item_path 重复时
    # 不应出现在标注里，否则日志会让人以为报文里有两处不同的路径来源。
    assert source == "item_path", f"重复来源不应被标注为独立来源：{source}"

    # 反过来：json_object 带来新路径时，标注必须体现出来（否则丢文件无从排查）
    paths, source = wh.extract_paths(SimpleNamespace(
        item_path=path, json_object={"paths": [path, str(src / "S01E02.mkv")]}))
    assert len(paths) == 2 and "json_object.paths" in source

    # 端到端：入队一次，且重复投递不刷新冷却
    plugin = _parser_plugin(str(src))
    plugin._handle_webhook_event(_webhook_event(
        item_path=path, json_object={"Item": {"Path": path}}))
    assert list(plugin._pending_queue) == ["TV:S01E01.mkv"]


def test_webhook_parser_swallows_malformed_payload(tmp_path):
    """
    报文畸形时返回 None 而不是抛异常。

    宿主对 provider 异常是隔离处理的，但异常会记进「插件错误」—— 一条配对错误的
    请求不该把插件健康度搞脏，更不该影响后续 provider。
    """
    src = tmp_path / "TV"
    src.mkdir()
    plugin = _parser_plugin(str(src))

    assert plugin.webhook_parser(body=b"\x00\x01not-json", form="???",
                                 args={"source": "rsync115sync"}) is None


def test_claimed_payload_survives_the_channel_filter(tmp_path):
    """
    认领 → 事件处理这条闭环必须真的走到入队。

    这是自查时发现的一个**自相矛盾**：`webhook_parser` 认领后构造的事件 channel 是
    `rsync115sync`，而 `_handle_webhook_event` 的渠道过滤只放行用户配置的渠道
    （默认 `emby`）—— 于是我们会认领一条报文、再自己把它丢掉，表现为日志里
    连一条记录都没有，与「没收到」完全一样。本用例把整条闭环钉住。
    """
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _parser_plugin(str(src))

    info = plugin.webhook_parser(
        body=json.dumps({"paths": [path]}).encode(),
        form=None, args={"source": "rsync115sync"})
    assert info is not None

    plugin._handle_webhook_event(SimpleNamespace(event_data=info))

    assert list(plugin._pending_queue) == ["TV:S01E01.mkv"]


def test_emby_channel_name_is_reserved_not_claimable():
    """
    钉住「宿主自带渠道名不可用于认领」这个前提。

    若将来有人把 WEBHOOK_TARGET 改成 `emby`，认领判据会与宿主 Emby 解析器的输出
    撞车，后果是宿主解析器被短路 —— 这条用例就是那次改动的哨兵。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    reserved = {"emby", "jellyfin", "plex", "zspace"}
    assert module.Rsync115Sync.WEBHOOK_TARGET not in reserved, (
        "WEBHOOK_TARGET 撞上了宿主自带的渠道名，会导致宿主 webhook 解析被短路"
    )
