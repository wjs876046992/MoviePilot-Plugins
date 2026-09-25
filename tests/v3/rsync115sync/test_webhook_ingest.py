"""
Webhook 入库（第二来源）：宿主 webhook 端点的**认领 + 广播**链路。

Webhook ingest: the host-endpoint chain only.

  · 入口：宿主端点 `/api/v1/webhook/` → 宿主调用本插件的 `webhook_parser`
          （模块方法契约，见 get_module() 的声明）
  · 之后：认领结果经 `EventType.WebhookMessage` 广播回来 → `_handle_webhook_event`

本插件曾自带一个匿名端点作为第二通道（`POST /api/v1/plugin/Rsync115Sync/webhook`），
2026-09-22 **已移除** —— 宿主端点已能满足同一需求，而自建端点要顶着「向网络暴露
一个可写入接口」的风险（四条自配防护：开关 / 密钥 / 路径白名单 / IP 白名单）。
理由与取舍见 DEVELOPMENT §9.18。因此本文件原先的「通道 B」用例整组删除 ——
它们验证的四道防护已不存在，留着只会让「插件暴露了什么」出现错误答案。

**为什么这条路必须有测试**：webhook 是本插件唯一由**外部**发起的入口，
出问题时用户手里没有任何可自查的证据 —— 发送端显示 200、日志一片安静、
看板队列不增长。因此这里把三件事钉住：入队语义与事件链路**完全一致**、
播放类事件绝不入队、失败必须**可区分**（取不到路径 / 路径不在映射内）。
"""

import importlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


# 本插件的 webhook 事件 channel **恒为 WEBHOOK_TARGET**（认领时就是这么构造的）。
# 这不是可配置项，而是「这条事件由本插件认领而来」的标记。
#
# ⚠️ 历史：这里曾默认 `channel="emby"` 并配一份渠道白名单。2026-09-24 起
# 处理侧改为只认自己的认领结果（`source=rsync115sync`），宿主自己解析的
# Emby/Jellyfin 事件一概不处理 —— 它们归平台解析器与其它插件管。
# 因此用 `channel="emby"` 构造事件已**不再**代表「应被本插件处理」，
# 各用例必须用这个常量，否则断言的是别的插件该干的活。
CLAIM_CHANNEL = "rsync115sync"


def _plugin(src_root, *, enabled=True, listen=True,
            pairs=None, media_extensions="mkv,srt"):
    """构造最小实例：只带 webhook 链路真正用到的状态。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin.plugin_version = "test"
    plugin._enabled = enabled
    plugin._listen_transfer = listen
    plugin._sync_pairs = pairs if pairs is not None else [{
        "name": "TV", "src": src_root, "dest": "/dest/TV",
        "all_ext": False, "strm_dir": "",
    }]
    plugin._media_extensions = media_extensions
    plugin._delay_hours = 2.0
    plugin._pending_queue = {}
    plugin._source_cursor = {}
    # 源端扫描状态：`_api_get_status` 的返回键必须与这里的字段清单对齐
    plugin._source_scan_enabled = True
    plugin._source_scan_cron = '*/10 * * * *'
    plugin._source_scan_last = 0.0
    plugin._ingest_skip_stat = {}
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


def _webhook_event(channel=CLAIM_CHANNEL, event="library.new", **fields):
    """
    构造一条**本插件认领后**由宿主广播回来的 WebhookMessage。

    默认 channel 用 CLAIM_CHANNEL（= WEBHOOK_TARGET），与生产路径一致：
    `webhook_parser` 认领时构造的 `WebhookEventInfo.channel` 就是这个值。
    要模拟**别家**（宿主 Emby 解析器 / 其它插件）的事件，显式传
    `channel="emby"` 之类的值 —— 那些事件本插件应当忽略。
    """
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


def test_events_not_claimed_by_us_are_ignored(tmp_path):
    """
    不是本插件认领的事件**一律不处理**。

    宿主自己的 Emby/Jellyfin 解析器广播出来的事件（channel 是 `emby` / `jellyfin`）
    归平台与其它插件管，本插件不该碰 —— 这条是「只认 source=rsync115sync」的
    处理侧对偶判据（入口侧由 `webhook_parser` 把关）。
    """
    src = tmp_path / "TV"
    path = _media(str(src))

    for foreign in ("emby", "jellyfin", "plex", "zspace", ""):
        plugin = _plugin(str(src))
        plugin._handle_webhook_event(_webhook_event(channel=foreign, item_path=path))
        assert plugin._pending_queue == {}, (
            f"channel={foreign!r} 的事件不是本插件认领的，不该入队"
        )


def test_events_claimed_by_us_are_handled(tmp_path):
    """本插件认领的事件（channel = WEBHOOK_TARGET）正常入队 —— 与上一条配对。"""
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src))

    plugin._handle_webhook_event(_webhook_event(item_path=path))

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
# 目录型通知：发送端最自然的「通知入库」就是推一个目录
# --------------------------------------------------------------------------
#
# 这一组的由来：目录名没有扩展名，直接进扩展名白名单必然被判 skipped，而当时的
# 端点返回 `success=True, 已入队 0 个` —— 发送端和用户都以为成功了，队列却是空的。
# 对 9KG 这类场景尤其致命：另一个工程下完一部电影／一季，最自然的通知方式就是
# 把目录路径发过来；推文件反而是不自然的（它不知道目录里最终有几个文件）。
#
# 现在入口只有宿主端点一个，因此这些用例一律走 `_host_post`（真路由 + 认领 +
# 广播），而不再是曾经那个自建端点的内部函数 —— 否则「目录展开」这条判据的
# 测试就只覆盖了一条已经不存在的通路。

def _movie_dir(src_root, name="某电影 (2001)", files=("movie.mkv", "movie.zh.srt")):
    """造一个「电影目录 + 目录内文件」的真实入库形态。"""
    import os
    base = os.path.join(src_root, name)
    os.makedirs(base, exist_ok=True)
    for fn in files:
        with open(os.path.join(base, fn), "wb") as fh:
            fh.write(b"x")
    return base


def test_directory_is_expanded_not_silently_swallowed(tmp_path):
    """
    推目录必须展开成文件并入队，且**不能**报 success=True 却 0 入队。

    这是本组最重要的一条：`success=True` + 空队列是最坏的失败形态 ——
    发送端会认为投递成功而不再重试，用户看日志只看到「成功」。
    """
    src = tmp_path / "9kg"
    d = _movie_dir(str(src))
    plugin = _plugin(str(src))

    res = _host_post(plugin, {"path": d})

    assert res["success"] is True
    assert res["data"]["added"] == 2, f"目录未被展开：{res}"
    assert sorted(plugin._pending_queue) == [
        "TV:某电影 (2001)/movie.mkv", "TV:某电影 (2001)/movie.zh.srt"]


def test_directory_with_trailing_slash_expands_too(tmp_path):
    """尾斜杠是发送端最常见的写法差异，不能只支持其中一种。"""
    src = tmp_path / "9kg"
    _movie_dir(str(src))
    plugin = _plugin(str(src))

    res = _host_post(plugin, {"path": str(src / "某电影 (2001)") + "/"})

    assert res["data"]["added"] == 2


def test_directory_expansion_respects_extension_whitelist(tmp_path):
    """展开不是无差别放行：非媒体文件照样被扩展名白名单挡掉。"""
    src = tmp_path / "9kg"
    _movie_dir(str(src), files=("movie.mkv", "poster.jpg", "readme.txt"))
    plugin = _plugin(str(src), media_extensions="mkv")

    res = _host_post(plugin, {"path": str(src / "某电影 (2001)")})

    assert res["data"]["added"] == 1
    assert list(plugin._pending_queue) == ["TV:某电影 (2001)/movie.mkv"]


def test_directory_expansion_skips_excluded_dirs(tmp_path):
    """排除目录（@eaDir 等）在遍历层就剪枝，不把其中的文件捞进来。"""
    src = tmp_path / "9kg"
    base = _movie_dir(str(src))
    import os
    meta = os.path.join(base, "@eaDir")
    os.makedirs(meta)
    with open(os.path.join(meta, "thumb.mkv"), "wb") as fh:
        fh.write(b"x")
    plugin = _plugin(str(src))

    res = _host_post(plugin, {"path": base})

    assert res["data"]["added"] == 2, "排除目录内的文件不应入队"
    assert all("@eaDir" not in k for k in plugin._pending_queue)


def test_directory_expansion_is_capped_and_reported(tmp_path):
    """
    展开有上限，且**截断必须留痕**。

    无上限展开意味着「推一个 9KG 根目录」能把冷却队列一次灌进上万个条目，
    115 侧风控配额随之被打满。截断还必须是可见的 —— 静默少入队会让用户
    以为文件已经在排队，实际上永远轮不到。
    """
    src = tmp_path / "9kg"
    d = _movie_dir(str(src), files=tuple(f"e{i:03d}.mkv" for i in range(20)))
    plugin = _plugin(str(src))
    plugin.DIR_EXPAND_LIMIT = 5

    res = _host_post(plugin, {"path": d})

    assert res["data"]["added"] == 5


def test_directory_with_no_media_files_logs_instead_of_lying(tmp_path):
    """
    目录存在但里面没有可同步文件 → 不能报「已入队 0 个」就算完。

    必须与「路径根本不存在」区分开：前者是扩展名配错或目录选错，
    后者是挂载问题。这两种情况的排查方向完全不同。
    """
    src = tmp_path / "9kg"
    _movie_dir(str(src), files=("poster.jpg",))
    plugin = _plugin(str(src), media_extensions="mkv")

    res = _host_post(plugin, {"path": str(src / "某电影 (2001)")})

    assert res["data"]["added"] == 0
    assert res["data"]["expanded"] == 1
    assert plugin._webhook_stat["ingested"] == 0


def test_directory_expansion_dedups_against_already_queued(tmp_path):
    """目录展开出的文件仍走同一套幂等：重复推同一目录不刷新冷却计时。"""
    src = tmp_path / "9kg"
    d = _movie_dir(str(src))
    plugin = _plugin(str(src))

    _host_post(plugin, {"path": d})
    first = dict(plugin._pending_queue)
    res = _host_post(plugin, {"path": d})

    assert res["data"]["added"] == 0
    assert res["data"]["duplicate"] == 2
    assert plugin._pending_queue == first, "重复推目录不应刷新冷却计时"


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


def test_webhook_enqueue_sets_cooldown_basis_from_discovery(tmp_path):
    """
    由 webhook 通知的文件，冷却基准必须是**发现时刻**（而不是走什么"升级"分支）。

    ⚠️ 这条用例替换了原先两条围绕 `_missed_queue` 的用例（「升级」与「清理」）。
    那个队列已在 2026-09-25 随冷却判据统一而删除：它对"错过的事件"**无条件跳过
    冷却**，于是源端扫描刚发现一个 10 秒前刚落地的文件也会被判为"错过的"并立即
    上传 —— 而源端扫描没有"文件写完了"这个信号，正在写入的文件 mtime 恰恰最新。

    现在两个场景由冷却基准自动区分，用例只需断言：
      · webhook 通知的文件进冷却队列；
      · 队列里存的是 `min(发现时刻, mtime)`，对刚写入的文件就是发现时刻
        （即"要等满冷却时长"，不会秒传）。
    """
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _plugin(str(src))
    before = time.time()

    plugin._handle_webhook_event(_webhook_event(item_path=path))

    key = "TV:S01E01.mkv"
    assert list(plugin._pending_queue) == [key]
    basis = plugin._pending_queue[key]
    # 刚写入的文件 mtime ≈ now，min 取到 now（允许 2 秒执行抖动）
    assert before - 2 <= basis <= time.time() + 1, (
        f"冷却基准应≈发现时刻，实际 {basis}（now={before}）——"
        "偏小意味着这个文件会绕过冷却立刻上传"
    )
    assert time.time() - basis < plugin._delay_hours * 3600, "刚入库的文件不该已到期"


def test_extension_filter_applies_to_webhook(tmp_path):
    src = tmp_path / "TV"
    nfo = _media(str(src), "a.nfo")
    plugin = _plugin(str(src))

    plugin._handle_webhook_event(_webhook_event(item_path=nfo))

    assert plugin._pending_queue == {}


def test_path_in_no_mapping_is_not_enqueued(tmp_path):
    """
    入库路径与配置的源目录不一致时**不认领**（返回 None），绝不猜、绝不错误入队。

    注意断言的是「认领阶段就拒了」而不是「入队后计数为 unmatched」：路径不落在
    任何映射内意味着我们不认识这条报文，此时必须把机会让给宿主自己的解析器 ——
    抢下来再丢掉会掐断宿主对 Emby/Jellyfin/Plex 报文的处理（见本文件末组用例）。
    """
    src = tmp_path / "TV"
    src.mkdir()
    outside = tmp_path / "other" / "a.mkv"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    plugin = _parser_plugin(str(src))

    client, _ = _host_chain_route(plugin)
    res = client.post("/api/v1/webhook/?token=t&source=rsync115sync",
                      json={"data": {"source_path": str(outside)}})

    assert res.status_code == 200
    assert plugin._pending_queue == {}


# --------------------------------------------------------------------------
# 契约：端点注册与事件注册（删掉不会有任何报错的那两行）
# --------------------------------------------------------------------------

def test_no_self_built_endpoint_is_registered():
    """
    本插件**不得**注册任何匿名（免宿主鉴权）端点 —— 自建 webhook 端点已移除。

    这条用例的价值是反向的：它拦住「某天顺手再加一个匿名口」。匿名口意味着
    知道 URL 的人都能往插件里灌数据，而伪造入库会真实消耗 115 风控配额。
    宿主端点（`/api/v1/webhook/`）已能满足同一需求且鉴权由宿主负责，
    因此插件侧的正确状态是**一个匿名端点都没有**。

    用运行时读 `get_api()` 而非源码字符串匹配：注册表本身就是契约。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    apis = module.Rsync115Sync.get_api(plugin)

    assert not [a for a in apis if a.get("path") == "/webhook"], (
        "自建 webhook 端点已移除，不应再注册 /webhook"
    )
    for api in apis:
        assert not api.get("allow_anonymous"), (
            f"{api['path']} 不应匿名：本插件现在全部端点都走宿主鉴权"
        )


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


def test_webhook_has_no_configurable_fields():
    """
    webhook 侧**不应再有任何配置项**（渠道白名单已随 C2 改造移除）。

    这条是**反向**断言：将来若有人重新加回一个「来源渠道」之类的配置，
    就等于把「本插件只认 source=rsync115sync」这条边界交回给用户去配 ——
    而那正是 2026-09-24 移除它的原因（默认值只有 emby，Jellyfin 用户静默失效）。
    """
    module = importlib.import_module("app.plugins.rsync115sync")
    cls = module.Rsync115Sync
    for gone in ("_normalize_channels", "_read_webhook_config", "_webhook_channels"):
        assert not hasattr(cls, gone), (
            f"{gone} 属于已移除的渠道白名单，不该再存在"
        )
    # get_config 也不该再暴露 webhook_channels（前端已无对应绑定）
    fields = cls()._api_get_config()["data"]
    assert "webhook_channels" not in fields, (
        "get_config 仍在返回 webhook_channels，而前端已无该绑定"
    )


def test_status_does_not_expose_channel_list():
    """/status 不该再返回 channels —— 看板与排查都不再依赖它。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = _plugin("/tmp/nonexistent-tv")
    # /status 会读取大量运行态字段；这里只补「本断言真正会用到的」，
    # 其余缺失由调用方（裸实例）的实际情况决定，与本断言无关。
    plugin._is_running = False
    plugin._last_status = {}
    plugin._pending_queue = {}
    plugin._backfill_queue = {}
    plugin._backfill_total = 0
    plugin._source_cursor = {}
    plugin._missed_last_scan = 0.0
    plugin._source_scan_enabled = False
    plugin._sync_pairs = []
    plugin._delay_hours = 2.0
    plugin._strm_watch = {}
    plugin._strm_suspects = {}
    plugin._strm_gen_requested = {}
    plugin._strm_grace_minutes = 360
    plugin._strm_check_enabled = False
    plugin._rate_limit_enabled = False
    plugin._upload_window_count = 0
    plugin._upload_max_per_window = 500
    plugin._upload_window_secs = 1800
    plugin._upload_blocked_until = 0.0
    plugin._last_force_ts = 0.0
    plugin._force_cooldown_days = 7
    plugin._cron = "0 */2 * * *"
    plugin._media_extensions = "mkv,srt"
    plugin._notify = False
    data = plugin._api_get_status()["data"]["webhook"]
    assert "channels" not in data, "/status 仍返回 webhook.channels"


# --------------------------------------------------------------------------
# 真实路由契约：这些断言只有把端点挂进真 FastAPI 才可能失效（也必须靠它才发现）
# --------------------------------------------------------------------------
#
# 注意：这一组测的是**宿主端点**（`/api/v1/webhook/`）而不是本插件的端点 ——
# 后者已于 2026-09-22 移除。因此下面不再有 `_real_route`（挂自建端点的那套），
# 只剩 `_host_chain_route`（复刻宿主端点 + 认领 + 广播的完整链路）。

def _host_post(plugin, payload, *, query="token=t&source=rsync115sync", raw=False):
    """
    走**宿主端点真路由 + 认领 + 广播**的完整链路，返回入队计数。

    为什么不再有「直接调处理器」的捷径：自建端点移除后，插件的入口只剩
    `webhook_parser` 一处，而它必须经宿主的模块调度器才会被调用（漏声明
    `get_module()` 就等于死代码）。测试若绕过声明表直接调实例方法，就复刻不出
    真机的失效 —— 这正是 2026-09-22 那次「测试全绿、真机全哑」的成因。
    因此本文件的所有入口用例都从这里走。

    ⚠️ 返回值里的 `data` 不是「端点响应」——插件现在没有自己的端点，宿主端点的
    响应体是宿主决定的（假宿主这里固定返回 `{"success": True}`）。计数是从
    `_enqueue_ingest_paths`（两条来源唯一共用的入队函数）捕获的，也就是**用户
    在看板上/日志里会看到的同一份数字**。以前断言的是自建端点自己拼的那个
    `{"success": …, "data": counts}`，端点没了，改从这里取。
    """
    captured: dict = {}
    original = plugin._enqueue_ingest_paths

    def spy(*args, **kwargs):
        counts = original(*args, **kwargs)
        captured.update(counts)
        return counts

    plugin._enqueue_ingest_paths = spy
    client, _ = _host_chain_route(plugin)
    kwargs = {"content": payload} if raw else {"json": payload}
    res = client.post(f"/api/v1/webhook/?{query}", **kwargs)
    if res.status_code != 200:
        return {"success": False, "status": res.status_code, "data": captured}
    return {"success": True, "data": captured}


def _claim(plugin, payload, *, source="rsync115sync"):
    """
    只驱动「认领」这一步（宿主解析入口 → provider），不广播事件。

    用于断言认领阶段的**判据与日志/样本**：报文是否被认领、失败时留下什么痕迹。
    与 `_host_post` 的分工是「只到入口」vs「一路到入队」。

    `source` 走 args（= 查询串），与真实发送端一致：收件人标识通常写在 URL 上
    （`?source=rsync115sync`），body 里只放业务字段。传 `source=None` 可模拟
    「没声明收件人」的报文（宿主每条 Emby 报文都是这个形态）。
    """
    args = {"source": source} if source else None
    return _declared_webhook_parser(plugin)(body=payload, form=None, args=args)


def _host_chain_route(plugin):
    """
    复刻**宿主** `/api/v1/webhook/` 端点的真实形态，用来验证平台那条路。

    为什么非要有它：本文件的其余用例都是直接调 `plugin.webhook_parser(...)`，
    而真实宿主在调用任何插件之前会先 `body = await request.body()` 再
    `form = await request.form()`（app/api/endpoints/webhook.py）。**那一步会失败** ——
    当发送端声明 `Content-Type: multipart/form-data` 却没有 boundary 时（很多 webhook
    配置界面的下拉框会诱导这么选），starlette 直接抛 400，请求在进入插件之前就被拒。
    插件侧一行日志都不会有，宿主日志里只有一条内容为空的 400。

    这正是用户实测踩到的那个坑，因此必须有一条用例把它钉住：**这个失败不是本插件
    能捕获的**，只能靠文档把「Content-Type 必须与 body 形态匹配」讲清楚。
    """
    pytest.importorskip("fastapi", reason="本环境无 fastapi，跳过路由层契约验证")
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    module = importlib.import_module("app.plugins.rsync115sync")
    app = FastAPI()

    # 与宿主端点逐字同序：先读原始 body，再解析 form，最后才调 provider。
    # 拿到非空结果后还要**广播事件**（宿主是 WebhookChain.message →
    # send_event(EventType.WebhookMessage, event_info)：不广播的话事件处理器
    # 永远不会被调用，表现成「认领成功但队列不涨」）。
    @app.post("/api/v1/webhook/")
    async def host_webhook(request: Request):
        body = await request.body()
        form = await request.form()
        args = request.query_params
        # ⚠️ 必须经 `_declared_webhook_parser` 取 provider，**不能**直接
        # `plugin.webhook_parser(...)`。真机的第二次「插件零日志」正是因为在
        # `get_module()` 里漏了这行声明：宿主从声明表里收集 provider，漏声明 =
        # 方法永远不会被调用。直接调实例方法会绕过声明表，于是测试全绿而真机全哑 ——
        # 这个 harness 当初就是这么写的，所以没能拦住那个 bug。
        info = _declared_webhook_parser(plugin)(body=body, form=form, args=args)
        if info:
            plugin._handle_webhook_event(SimpleNamespace(
                event_type=SimpleNamespace(value="webhook.message"),
                event_data=info))
        return {"success": True}

    return TestClient(app, raise_server_exceptions=False), module


def _declared_webhook_parser(plugin):
    """
    完全按宿主的方式取得 `webhook_parser` provider：**只从 `get_module()` 声明表里拿**。

    宿主实现（app/runtime/extensions/plugin/projection.py 的 `modules()`）：
    `declared = plugin.get_module()`，返回 `None` 就 `continue`，即该插件对
    所有模块方法都不可见。基类默认实现正是返回 `None`。

    因此这里拿不到就 `assert` 失败，而不是退回 `plugin.webhook_parser` ——
    退回就等于把「宿主根本不会调用它」这个事实从测试里抹掉。
    """
    declared = plugin.get_module()
    assert isinstance(declared, dict), (
        "get_module() 必须返回字典，宿主只接受 Mapping；返回 None 会让本插件"
        "对所有模块方法不可见（这正是真机排查三轮的那个 bug）"
    )
    provider = declared.get("webhook_parser")
    assert callable(provider), (
        "get_module() 未声明 webhook_parser —— 宿主不会调用我们的实现，"
        "认领通道整条静默失效（不报错、无日志）"
    )
    return provider


def test_host_route_rejects_multipart_without_boundary(tmp_path):
    """
    `Content-Type: multipart/form-data` + 裸 JSON body → 宿主在调用插件前就 400。

    这条用例记录的是**用户实测遇到的真实故障**，而不是假想场景：

        MP 平台能看到 webhook 请求，但看不到具体信息；
        rsync115sync 插件看不到任何日志。

    原因就是宿主端点里的 `form = await request.form()`：multipart 没有 boundary，
    starlette 直接拒绝。**插件无法捕获**（SDK 没有 middlewar 钩子，请求根本没到
    插件代码），所以本用例的价值是把这个失败模式**固定下来**：
    它必须表现为「宿主 4xx + 插件零日志」，而不是被误认为「认领判据写错了」。
    """
    src = tmp_path / "9KG"
    src.mkdir()
    plugin = _parser_plugin(str(src))
    client, _ = _host_chain_route(plugin)

    payload = json.dumps({"event": "download.finish",
                          "data": {"source_path": str(src / "某电影")}})
    res = client.post("/api/v1/webhook/?token=t&source=rsync115sync",
                      content=payload,
                      headers={"Content-Type": "Multipart/form-data"})

    assert res.status_code == 400, (
        "宿主对无 boundary 的 multipart 应当直接拒绝；若这里变成 200，"
        "说明宿主端点的解析顺序变了，文档里的排查步骤需要同步修改"
    )
    # 插件这一侧什么都没看到 —— 这正是用户「看不到任何日志」的成因
    assert plugin._webhook_stat_now().get("claimed", 0) == 0


def test_multipart_without_boundary_but_json_content_type_works(tmp_path):
    """
    同一个报文，只把 Content-Type 改对 → 整条链就通了。

    这是给用户看的那一步：**不是插件的认领判据错了，是请求头与 body 形态不匹配**。
    """
    src = tmp_path / "9KG"
    src.mkdir()
    path = _media(str(src), "movie.mkv")
    plugin = _parser_plugin(str(src))
    client, _ = _host_chain_route(plugin)

    payload = {"event": "download.finish",
               "data": {"title": "某电影", "first_actor": "某人",
                        "source_path": path, "target_path": "/9KG/某电影"}}
    res = client.post("/api/v1/webhook/?token=t&source=rsync115sync",
                      json=payload)

    assert res.status_code == 200
    assert plugin._webhook_stat_now().get("claimed", 0) == 1, (
        "改了 Content-Type 之后报文应能到达插件解析入口"
    )
    assert list(plugin._pending_queue), "报文应被认领并成功入队"


# --------------------------------------------------------------------------
# 缺尾斜杠 → 307：比 400 更隐蔽，因为「到过宿主」这件事在客户端侧被隐藏了
# --------------------------------------------------------------------------
#
# 真机现象（用户第二次实测）：
#     POST /api/v1/webhook?token=...&source=rsync115sync HTTP/1.1 307 Temporary Redirect
#     插件日志什么也看不到
#
# 成因：宿主把 webhook 端点注册在 "/"(app/api/endpoints/webhook.py 的 @router.post("/"))，
# 再由 app.include_router(prefix="/api/v1/webhook") 挂上，最终路径是 **带尾斜杠** 的
# `/api/v1/webhook/`。请求少了尾斜杠时 starlette 在**路由层**就返回 307 并指向带斜杠
# 的地址 —— 此时既没有解析请求体、更没有调用 provider，插件一行日志都不会有。
#
# 与 400 的区别（也是它更难查的原因）：400 至少留下一条状态码，而 307 在
# 多数发送端（含界面里那种「高级设置」）看起来像「已成功投递」—— 因为静默跟随后
# 结果确实是 200。真正的失败只体现在**重定向会丢掉 POST body 与部分请求头**，
# 以及插件侧彻底的静默。用户的发送端日志里那条 307 就是唯一线索。

def _host_chain_route_noredirect(plugin):
    """与 `_host_chain_route` 同形，但客户端**不自动跟随重定向**。

    ⚠️ starlette 的 `TestClient` 默认 `follow_redirects=True` —— 用它测尾斜杠问题
    会**静默掩盖**这个 bug：请求被自动跟到带斜杠的地址并返回 200，测试全绿，
    而真机上的发送端未必跟随。因此这一组必须显式关掉跟随。
    """
    pytest.importorskip("fastapi", reason="本环境无 fastapi，跳过路由层契约验证")
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    module = importlib.import_module("app.plugins.rsync115sync")
    app = FastAPI()

    @app.post("/api/v1/webhook/")
    async def host_webhook(request: Request):
        body = await request.body()
        form = await request.form()
        args = request.query_params
        # 同 `_host_chain_route`：必须走声明表，不能直接调实例方法
        info = _declared_webhook_parser(plugin)(body=body, form=form, args=args)
        if info:
            plugin._handle_webhook_event(SimpleNamespace(
                event_type=SimpleNamespace(value="webhook.message"),
                event_data=info))
        return {"success": True}

    return TestClient(app, raise_server_exceptions=False,
                      follow_redirects=False), module


def test_host_route_without_trailing_slash_307_and_plugin_is_blind(tmp_path):
    """
    **缺尾斜杠 → 307，且插件完全不知道有请求来过。**

    这是用户第二次实测的现象，也是本组用例存在的理由：第一次的 400 至少有状态码
    可查，这一次连「报文有没有到」都要靠推断。因此把两件事同时钉住：
    ① 地址少一个斜杠就是 307（不是 200、也不是 404）；
    ② 插件侧 `claimed` 保持 0 —— 与「报文没到插件」在现象上完全一致。
    """
    src = tmp_path / "9KG"
    src.mkdir()
    plugin = _parser_plugin(str(src))
    client, _ = _host_chain_route_noredirect(plugin)

    payload = json.dumps({"event": "download.finish",
                          "data": {"source_path": str(src / "某电影")}})
    res = client.post("/api/v1/webhook?token=t&source=rsync115sync",
                      content=payload,
                      headers={"Content-Type": "application/json"})

    assert res.status_code == 307, (
        "缺尾斜杠应被 starlette 重定向；若变成 200，说明宿主改了路由定义，"
        "文档里「地址必须带尾斜杠」的说明需要同步修改"
    )
    assert res.headers.get("location", "").endswith(
        "/api/v1/webhook/?token=t&source=rsync115sync"), "重定向目标应补上尾斜杠"
    assert plugin._webhook_stat_now().get("claimed", 0) == 0, (
        "重定向发生在路由层，插件不应看到任何东西 —— 这正是它难查的地方"
    )


def test_host_route_with_trailing_slash_is_the_only_working_form(tmp_path):
    """
    补上尾斜杠即可 → 200 + 正常入队。**尾斜杠不是风格问题，是必需。**

    与本组第一条配对：同一个 URL、同一个报文，只差一个 `/`，行为天差地别。
    """
    src = tmp_path / "9KG"
    src.mkdir()
    path = _media(str(src), "movie.mkv")
    plugin = _parser_plugin(str(src))
    client, _ = _host_chain_route_noredirect(plugin)

    res = client.post("/api/v1/webhook/?token=t&source=rsync115sync",
                      json={"event": "download.finish",
                            "data": {"source_path": path}})

    assert res.status_code == 200
    assert plugin._webhook_stat_now().get("claimed", 0) == 1
    assert list(plugin._pending_queue), "带尾斜杠时整条链应当通畅"


def test_source_path_nested_under_data_is_recognized(tmp_path):
    """
    用户实际发送的字段形态：`data.source_path`（嵌在 `data` 下）。

    `data` 在 NESTED_CONTAINERS 内、`source_path` 在 PATH_FIELD_CANDIDATES 内，
    因此这个形态**本来就应该能被识别** —— 本用例把它钉住，避免以后有人以为
    嵌套字段不被支持而去写特例。真正踩到的坑是 Content-Type，不是字段名。
    """
    src = tmp_path / "9KG"
    src.mkdir()
    d = tmp_path / "9KG" / "某电影 (2024)"
    d.mkdir()
    path = _media(str(d), "movie.mkv")
    plugin = _parser_plugin(str(src))

    info = plugin.webhook_parser(
        body=json.dumps({"event": "download.finish",
                         "data": {"title": "某电影", "first_actor": "某人",
                                  "source_path": path,
                                  "target_path": "/9KG/某电影 (2024)"}}).encode(),
        form={}, args={"token": "t", "source": "rsync115sync"})

    assert info is not None, "data.source_path 形态应可认领"
    assert info.item_path == path


def test_unclaimable_addressed_payload_still_leaves_a_trace(tmp_path):
    """
    **声明发往本插件、但最终没认领** 的报文必须留下线索。

    这正是「插件看不到任何日志」那次最难的地方：认领失败与报文没到，现象完全一样。
    现在：入口计数 `claimed` 一定增加，并且样本里能直接看到发送端到底传了什么。

    宿主自己的 Emby 报文不受影响（没声明收件人的那条路仍只记 debug，不刷屏）。
    """
    src = tmp_path / "9KG"
    src.mkdir()
    plugin = _parser_plugin(str(src))
    outside = tmp_path / "elsewhere" / "x.mkv"
    outside.parent.mkdir()
    outside.write_bytes(b"x")

    # 声明发给我们，但路径不在任何映射内 → 认领失败
    info = plugin.webhook_parser(
        body=json.dumps({"paths": [str(outside)]}).encode(),
        form={}, args={"source": "rsync115sync"})

    assert info is None, "路径不在映射内时不应认领（避免短路宿主解析器）"
    stat = plugin._webhook_stat_now()
    assert stat["claimed"] == 1, "声明发往本插件的报文必须计入 claimed"
    # ⚠️ 这里原先断言「必须留下报文样本」。样本随看板的样本区一并移除（它的
    # 唯一消费者就是那块区域），改由 claimed + last_claimed_shape 承担自查：
    # 两者配合足以区分「请求没到」与「到了但路径不在映射内」。
    assert stat["last_claimed_shape"], (
        "认领失败也必须留下字段结构摘要，否则用户无从自查是哪个字段没对上"
    )


def test_addressed_claim_failure_is_logged_at_info(tmp_path, caplog):
    """
    认领失败必须打 **info** 级日志（不能只是 debug）。

    这条是用户要求「增加点日志来定位问题」的直接落点：debug 级在默认日志级别下
    根本看不到，而这个分支只会在**用户显式声明了 source=rsync115sync** 时走到 ——
    它天然是低频且高价值的，不存在刷屏风险。日志里必须带上路径与当前映射，
    否则用户只知道自己「配了但没生效」，仍然不知道该改哪一项。
    """
    import logging

    src = tmp_path / "9KG"
    src.mkdir()
    plugin = _parser_plugin(str(src))
    outside = tmp_path / "elsewhere" / "x.mkv"
    outside.parent.mkdir()
    outside.write_bytes(b"x")

    with caplog.at_level(logging.INFO, logger="stubhost"):
        plugin.webhook_parser(
            body=json.dumps({"paths": [str(outside)]}).encode(),
            form={}, args={"source": "rsync115sync"})

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "不属于任何映射" in text, f"认领失败必须留下 info 日志，实际日志：{text!r}"
    assert str(outside) in text, "日志要写出是哪个路径没匹配上"
    assert str(src) in text, "日志要写出当前配置的映射源目录，用户才知道该往哪改"


def test_host_route_accepts_documented_payload_shapes(tmp_path):
    """
    发送端能用的几种载体都要在**真路由**下走通：JSON body、查询串、纯文本 JSON。

    为什么值得单独测：这三种形态在宿主端点里走的是不同分支 —— JSON 进 body、
    查询串进 args、text/plain 的 JSON 要先 decode 再 parse。宿主把三者作为三个
    不同参数交给 provider（`body=…, form=…, args=…`），漏读任何一个，对应形态的
    发送端就会表现为「请求到了、插件说取不到路径」。这里走 TestClient 发真请求，
    不用手写 dict —— 手写 dict 会绕过 starlette 的解码层，测不出真实形态。
    """
    src = tmp_path / "TV"
    src.mkdir()
    plugin = _parser_plugin(str(src))
    client, _ = _host_chain_route(plugin)
    url = "/api/v1/webhook/?token=t&source=rsync115sync"

    p1 = _media(str(src), "json.mkv")
    r1 = client.post(url, json={"event": "download.finish",
                                "data": {"source_path": p1}})
    assert r1.status_code == 200 and plugin._webhook_stat_now()["claimed"] == 1

    p2 = _media(str(src), "query.mkv")
    r2 = client.post(f"{url}&path={p2}")
    assert r2.status_code == 200 and plugin._webhook_stat_now()["claimed"] == 2

    p3 = _media(str(src), "text.mkv")
    r3 = client.post(url, content='{"data": {"source_path": "%s"}}' % p3,
                     headers={"Content-Type": "text/plain"})
    assert r3.status_code == 200 and plugin._webhook_stat_now()["claimed"] == 3

    assert sorted(plugin._pending_queue) == [
        "TV:json.mkv", "TV:query.mkv", "TV:text.mkv"]


def test_host_route_enqueues_every_path_in_the_list(tmp_path):
    """
    一次推多个文件时**全部**入队，不是只取第一个。

    两层都可能是丢文件的地方：宿主端点把原始 body 交给我们（bytes → JSON），
    认领侧把命中的路径写进 `json_object.paths`，接收侧再把 `item_path` 与
    `json_object` 合并去重（`item_path` 按宿主契约只能放单个值，早先写成
    「有值就直接返回」时，第二条起全部静默丢失）。走真路由才覆盖到第一层。
    """
    src = tmp_path / "TV"
    src.mkdir()
    plugin = _parser_plugin(str(src))
    client, _ = _host_chain_route(plugin)
    paths = [_media(str(src), f"e0{i}.mkv") for i in (1, 2, 3)]

    res = client.post("/api/v1/webhook/?token=t&source=rsync115sync",
                      json={"event": "download.finish",
                            "data": {"paths": paths}})

    assert res.status_code == 200
    assert sorted(plugin._pending_queue) == ["TV:e01.mkv", "TV:e02.mkv", "TV:e03.mkv"]




def _page_source():
    """
    读看板组件的**源码**（不是构建产物）。

    这些看板断言是纯文本检查（模板里有没有某个字段绑定），读源码即可；读 dist
    产物会把断言绑到文件名哈希上，构建一变就全红。

    ⚠️ 用「向上逐级找」而不是固定的 `parents[N]`：本文件早先的版本写了硬编码
    层数，一旦测试目录或本文件位置调整（例如按插件拆子目录），断言就会读到错的
    路径 —— 表现为「找不到文件」或更糟的「读到了别的文件却仍然通过」。
    `test_dashboard_stat_row_border.py` 用的是同一套找法。
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "plugins.v3" / "rsync115sync" / "src" / "components" / "Page.vue"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    pytest.skip("未找到 rsync115sync 的 Page.vue 源码")


def test_dashboard_renders_webhook_counters():
    """
    看板必须把三个计数都画出来：收到 / 入队 / 平台解析入口到达。

    后端算了字段、文档也写了、前端没画 —— 这类缺口在本项目反复出现过
    （「后端有字段、前端没画」与「后端没字段、前端画了」都算）。
    """
    src = _page_source()
    for field in ("webhookStat.received", "webhookStat.ingested", "webhookStat.claimed"):
        assert field in src, f"看板未渲染 {field}"
    assert "Webhook 入库" in src, "看板缺少 webhook 区域标题"


def test_dashboard_webhook_panel_is_gated_not_always_visible():
    """
    面板只在**曾经收到过请求**时出现，不能常驻。

    否则绝大多数用户会一直看到一块永远是 0 的面板，反而怀疑自己配错了什么。
    """
    src = _page_source()
    assert "webhookVisible" in src, "webhook 面板缺少可见性门控"
    assert "v-if=\"webhookVisible\"" in src, "门控没有挂到面板上"


def test_dashboard_no_longer_renders_payload_samples():
    """
    看板**不再**显示「最近报文」样本（按要求移除）。

    样本连同其后端采集一并删除：它唯一的消费者就是这块区域，留着采集等于
    让插件持续抓取并落盘完整报文体（截断脱敏后仍是用户数据）而无人读取。
    排查改靠 `last_payload_shape`（字段结构）+ 三个计数。

    ⚠️ 这条用例是**反向**的（断言某物不再存在）。它同样重要：样本区一旦被
    重新加回模板，就等于把那份无人读取的采集也带回来 —— 需要同时恢复后端。
    """
    src = _page_source()
    for gone in ("webhookStat.samples", "prettySample", "webhook-sample",
                 "最近报文（新 → 旧）"):
        assert gone not in src, f"{gone} 属于已移除的报文样本区，不该再出现在看板里"


def test_stub_host_status_defaults_align_with_frontend():
    """
    后端 /status 暴露的 webhook 字段必须能被前端默认值兜住。

    前端 statusData 的初值是空对象 `webhook: {}`：首帧（尚未拉到 /status）时
    模板里所有 `webhookStat.x` 都会取到 undefined。`v-if="webhookVisible"` 依赖
    `webhookStat.received` 与 `webhookStat.claimed` 读取 undefined 而不抛错 ——
    这条用例把「模板用到的字段都允许缺失」这件事钉住，防止将来有人直接调用
    某个数组字段的方法而在首帧崩掉整个看板。
    """
    src = _page_source()
    # 自建端点移除后，看板不该再渲染它的任何字段（allow_roots / secret_set /
    # self_enabled）：这些键已不再由 /status 返回，模板里留着只会恒取 undefined。
    for gone in ("webhookStat.self_enabled", "webhookStat.secret_set",
                 "webhookStat.allow_roots"):
        assert gone not in src, (
            f"{gone} 是自建端点的字段，已随端点移除 —— 看板不该再引用它"
        )
    # `channels` 曾用于看板展示，展示与后端字段均已随渠道白名单移除；
    # 这里改成**反向**断言：它一旦回到看板，就说明白名单（或其残留）也回来了。
    assert "webhookStat.channels" not in src, (
        "webhookStat.channels 属于已移除的渠道白名单，看板不该再引用它"
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


def test_startup_reports_claim_hook_registration(tmp_path, caplog):
    """
    启动时必须**正面确认**认领钩子已注册，而不是等真机上去核对一条不存在的日志。

    由来：2026-09-22 排查了三轮才发现真因是 `get_module()` 没声明 `webhook_parser`
    —— 那是「一条本该出现的日志从不出现」的失效形态，没有任何堆栈或错误可看。
    这条用例把「启动时自证」固定下来：`init_plugin` 之后日志里必须有一行
    明确说明钩子已注册；反过来若声明丢了，必须出现 `error` 级的告警。

    顺带它也覆盖「NAS 上跑的不是最新版」这种部署问题：版本号与这行日志是否出现，
    两者一对就能判断。
    """
    import logging

    # 插件用的是宿主注入的 logger（生产环境名叫 moviepilot，桩环境叫 stubhost），
    # 因此按**实例上的 logger 对象名**取，别把环境细节写死在用例里。
    importlib.import_module("app.plugins.rsync115sync")
    plugin = _plugin(str(tmp_path / "TV"))
    logger_name = __import__(
        "app.plugins.rsync115sync", fromlist=["logger"]).logger.name

    with caplog.at_level(logging.INFO, logger=logger_name):
        plugin.init_plugin({"enabled": True, "listen_transfer": True,
                            "sync_pairs": []})

    text = caplog.text
    assert "认领钩子已注册" in text, (
        "启动日志必须正面确认 webhook_parser 已向宿主声明 —— 缺了这条确认，"
        "真机上的静默失效就只能靠人肉核对「哪条日志没出现」"
    )
    assert "认领钩子**未注册**" not in text

    # 反向：声明被拿掉时必须报 error 级（而不是继续静默）
    broken = _plugin(str(tmp_path / "TV"))
    broken.get_module = lambda: {}          # 模拟漏声明
    with caplog.at_level(logging.ERROR, logger=logger_name):
        caplog.clear()
        broken.init_plugin({"enabled": True, "listen_transfer": True,
                            "sync_pairs": []})
        assert "认领钩子**未注册**" in caplog.text, (
            "声明缺失时必须报 error —— 这正是真机上「什么也看不到」的那种失效"
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


def test_webhook_parser_does_not_claim_host_emby_payloads(tmp_path):
    """
    宿主 Emby 解析器形态的报文（`source=<实例名>`）**绝不能**被本插件认领。

    宿主的 Emby 解析器产出的 channel 就是 `emby`（emby.py:1082）。按 source 认领
    会把宿主本来能正常处理的 Emby 报文抢过来并短路掉宿主解析器 —— 本插件只想要一个
    路径，代价完全不成比例。这里用「宿主那侧的真实报文形态」做反向验证：
    `source` 填的是 Emby 实例名，不是本插件的标识。
    """
    src = tmp_path / "TV"
    path = _media(str(src))
    plugin = _parser_plugin(str(src))

    body = json.dumps({"Event": "library.new", "Item": {"Path": path}}).encode()
    for foreign_source in ("PN41", "emby", "jellyfin", ""):
        assert plugin.webhook_parser(
            body=body, form=None, args={"source": foreign_source}) is None, (
            f"source={foreign_source!r} 不是本插件的标识，不该认领"
        )


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
