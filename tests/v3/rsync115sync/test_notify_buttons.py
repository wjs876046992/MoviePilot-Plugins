"""
疑似通知用**按钮**而不是代码块 —— 点一下即执行。

The suspect notification uses tap-to-run buttons, not copyable code blocks.

## 为什么改（2026-10-06，用户实测反馈「命令没办法复制」）

第一版把命令放进 ``` 围栏，指望 Telegram 对代码块提供"点按复制"。**实测不行**：
Telegram 只在部分客户端对代码块给复制按钮，而移动端长按选择很难只选中那一行
（前后都是文字）。

而宿主支持一条更直接的通路：**按钮的 `callback_data` 只要是 `/` 开头的斜杠命令，
点一下就会真的执行**。`app/modules/telegram/module.py` 里甚至专门做了
「非管理员点斜杠命令按钮则拒绝」的校验 —— 只有在真会执行时才需要这道校验。
点一下 vs 复制粘贴再发送，前者少两步。

## 布局约束（都是刻意的）

- `gen` / `check` 各占一行：它们是**整批**操作，混在按条分行的按钮里会让人
  以为只作用于那一条；
- `retry` 与 `ignore` 同行，但 `retry` 文案带 ⚠️ 与"删旧"字样 ——
  它**会先删云端旧文件**，属于破坏性操作，点之前必须让人看出来；
- 顺序上 `gen`（安全、多数够用）在 `retry` 之前。
"""

import importlib.util
import os
import sys
import types

import pytest

# 构造最小桩环境以测试 commands 模块。
# ⚠️ 先探测真实后端（同 test_helper_health.py）：桩是进程级污染，
# `Event = _DummyEvent` 会让同一进程里走真实 handle_command 的测试行为分叉。
try:
    import importlib as _il
    _real_event = _il.import_module("app.core.event")
    _HAVE_REAL_EVENT = hasattr(_real_event, "Event") and _real_event.Event is not object
except Exception:
    _HAVE_REAL_EVENT = False

class _DummyEvent:
    """通知按钮回调用的最小事件载体；有真实后端时也用它构造回调事件。"""
    def __init__(self, event_type, event_data):
        self.event_type = event_type
        self.event_data = event_data

if not _HAVE_REAL_EVENT:
    for _m in ["app", "app.core", "app.core.event", "app.sdk", "app.sdk.logging"]:
        if _m not in sys.modules:
            sys.modules[_m] = types.ModuleType(_m)

    sys.modules["app.core.event"].Event = _DummyEvent
    sys.modules["app.core.event"].EventType = types.SimpleNamespace(PluginAction=4, MessageAction=3)
    sys.modules["app.core.event"].eventmanager = types.SimpleNamespace(register=lambda *a, **kw: lambda f: f)
    sys.modules["app.sdk.logging"].logger = types.SimpleNamespace(
        info=lambda *a, **kw: None, debug=lambda *a, **kw: None,
        warning=lambda *a, **kw: None, error=lambda *a, **kw: None,
    )

_PLUGIN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    "plugins.v3", "rsync115sync",
)


def _strm():
    name = "_rp_btn_test"
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [_PLUGIN_DIR]
        sys.modules[name] = pkg
    return importlib.import_module(f"{name}.strm")


def _pair():
    return {"name": "9KG", "src": "/emby/9KG", "dest": "/115/9KG",
            "strm_dir": "/strm/9KG", "all_ext": False}


KEY = "9KG:桥本有菜/SNIS-755/SNIS-755-破解-C.mp4"


def test_every_button_uses_the_host_plugin_callback_format():
    """
    ⚠️ 核心约束：`callback_data` 必须是 `[PLUGIN]<插件ID>|<内容>`。

    ## 这条断言是被真机打回来的

    第一版写成 `/rsync_strm gen`，以为宿主会把斜杠命令的按钮当命令执行。
    **实测点下去只回一句「回调数据格式错误，请检查！」，插件侧收不到任何事件。**

    宿主（`app/chain/message.py` 的 `callback_routes`）是**白名单**：

        [PLUGIN]<ID>|<内容>   transfer:   skill:   sites:
        subscribes:   media:   update:   agent_choice

    斜杠命令**不在其中**，会落到兜底分支由宿主回那句报错。
    （我在 `telegram/module.py` 看到的「非管理员点斜杠命令按钮则拒绝」是给
    **Agent 会话确认按钮**用的，不是通用能力 —— 把局部机制当成了通用机制。）

    判据直接复刻宿主的 `parse_callback`：前缀 + 用 `|` 能切成两段 + 插件 ID 对得上。
    """
    rows = _strm().suspect_command_buttons([KEY], [_pair()])
    assert rows, "没生成任何按钮"
    for row in rows:
        for btn in row:
            cd = btn["callback_data"]
            assert cd.startswith("[PLUGIN]"), (
                f"按钮 [{btn['text']}] 的 callback_data={cd!r} 不以 [PLUGIN] 开头 —— "
                f"宿主不会转发，点了只会得到「回调数据格式错误」"
            )
            plugin_id, sep, content = cd.partition("|")
            assert sep, f"callback_data={cd!r} 缺少 `|` 分隔符"
            assert plugin_id.replace("[PLUGIN]", "", 1) == "Rsync115Sync", (
                f"插件 ID 写成了 {plugin_id!r}，宿主会转发给别的插件"
            )
            assert content, f"callback_data={cd!r} 的内容段为空"
            assert btn.get("text"), "按钮缺文案"


def test_gen_and_check_are_whole_batch_and_stand_alone():
    """
    `gen` / `check` 是**整批**操作，各占一行且不与其他按钮混排。

    混排会让人以为它只作用于那一行的条目 —— 实测过的误解来源。
    """
    rows = _strm().suspect_command_buttons([KEY], [_pair()])
    flat = {b["callback_data"]: (i, len(r)) for i, r in enumerate(rows) for b in r}
    for cmd in ("[PLUGIN]Rsync115Sync|gen", "[PLUGIN]Rsync115Sync|check"):
        assert cmd in flat, f"缺少按钮 {cmd}"
        _, width = flat[cmd]
        assert width == 1, f"{cmd} 所在行有 {width} 个按钮，应当独占一行"


def test_destructive_button_says_so_and_comes_after_gen():
    """
    破坏性按钮必须①文案自明 ②排在安全的那个之后。

    `retry` 会先删云端旧文件；文案不带提示、或排在 `gen` 之前，
    都会显著提高误点概率。
    """
    rows = _strm().suspect_command_buttons([KEY], [_pair()])
    order = [b["callback_data"] for r in rows for b in r]
    retry_idx = next(i for i, c in enumerate(order) if c.endswith("|retry " + KEY.split("/")[-1].rsplit(".", 1)[0]) or "|retry " in c)
    gen_idx = next(i for i, c in enumerate(order) if c.endswith("|gen"))
    assert gen_idx < retry_idx, "「删旧重传」排在了「先试补生成」之前"

    retry_btn = next(b for r in rows for b in r if "|retry " in b["callback_data"])
    assert ("删旧" in retry_btn["text"]) or ("⚠" in retry_btn["text"]), (
        f"破坏性按钮文案不自明：{retry_btn['text']!r} —— 点之前必须让人看出来"
    )


def test_ambiguous_keyword_yields_no_button_for_that_entry():
    """
    给不出唯一关键字时**不给按钮** —— 与文本块的策略一致。

    按钮比文本更危险：点一下就执行，没有"再检查一遍命令"的机会。
    因此宁可少一个按钮，也不要给一个会命中多条的。
    """
    dup = "9KG:x/E01.mkv"
    rows = _strm().suspect_command_buttons([dup, dup], [_pair()])
    cmds = [b["callback_data"] for r in rows for b in r]
    assert not any("|retry " in c for c in cmds), (
        "条目无法唯一确定时仍生成了重传按钮"
    )
    # 整批操作仍要在（它们不依赖具体条目）
    assert "[PLUGIN]Rsync115Sync|gen" in cmds


def test_button_count_is_bounded():
    """条目多时按钮数量有上限 —— Telegram 对按钮总数有限制。"""
    keys = [f"9KG:剧{n}/E{n:02d}.mkv" for n in range(20)]
    rows = _strm().suspect_command_buttons(keys, [_pair()], limit=5)
    retry_rows = [r for r in rows if any("|retry " in c["callback_data"] for c in r)]
    assert len(retry_rows) == 5, f"limit=5 时应只有 5 行条目按钮，实际 {len(retry_rows)}"


def test_single_suspect_has_no_retry_all_button():
    """
    单条异常时**不出现**「全部删旧重传」按钮（单条已有单独重传按钮，避免冗余）。
    """
    rows = _strm().suspect_command_buttons([KEY], [_pair()])
    cmds = [b["callback_data"] for r in rows for b in r]
    assert not any("|retry_all" in c for c in cmds), "单条异常时不应出现全部删旧重传按钮"

    rows_with_total_1 = _strm().suspect_command_buttons([KEY], [_pair()], total_count=1)
    cmds_1 = [b["callback_data"] for r in rows_with_total_1 for b in r]
    assert not any("|retry_all" in c for c in cmds_1), "total_count=1 时不应出现全部删旧重传按钮"


def test_multiple_suspects_have_retry_all_button():
    """
    多条异常时必须出现「⚠️ 全部删旧重传」按钮：
    1. 独占一行；
    2. 文案自明（含"全部删旧重传"与"⚠️"）；
    3. 顺序排在 gen 与 check 之后；
    4. callback_data 满足 Telegram 格式与 64 字节约束。
    """
    keys = ["9KG:剧/E01.mkv", "9KG:剧/E02.mkv"]
    rows = _strm().suspect_command_buttons(keys, [_pair()])
    flat = {b["callback_data"]: (i, len(r), b["text"]) for i, r in enumerate(rows) for b in r}

    retry_all_cd = "[PLUGIN]Rsync115Sync|retry_all"
    assert retry_all_cd in flat, f"多条异常时缺少按钮 {retry_all_cd}"
    row_idx, width, text = flat[retry_all_cd]
    assert width == 1, f"全部删旧重传应当独占一行，实际宽度 {width}"
    assert "全部删旧重传" in text, f"文案缺少「全部删旧重传」: {text!r}"
    assert "⚠" in text, f"破坏性按钮文案应带警示符: {text!r}"

    # 顺序排在 gen 和 check 之后
    gen_row = flat["[PLUGIN]Rsync115Sync|gen"][0]
    check_row = flat["[PLUGIN]Rsync115Sync|check"][0]
    assert gen_row < row_idx, "全部删旧重传排在了补生成之前"
    assert check_row < row_idx, "全部删旧重传排在了检查结果之前"

    # 字节长度约束
    assert len(retry_all_cd.encode("utf-8")) <= 64


def test_total_count_triggers_retry_all_even_if_new_suspects_is_single():
    """
    本次新增虽然只有 1 条，但系统清单总数 > 1 时，仍应当提供「全部删旧重传」。
    """
    rows = _strm().suspect_command_buttons([KEY], [_pair()], total_count=3)
    cmds = [b["callback_data"] for r in rows for b in r]
    assert "[PLUGIN]Rsync115Sync|retry_all" in cmds, (
        "total_count=3 时应生成全部删旧重传按钮"
    )


def test_handle_button_action_retry_all():
    """
    点击「全部删旧重传」按钮时的回调处理：
    1. 清单为空时，友好提示无需处理；
    2. 清单非空时，调用 _api_strm_retry 批量传入全部 key 并回执。
    """
    name = "_rp_btn_test"
    cmds_mod = importlib.import_module(f"{name}.commands")
    cmds_mod.Event = _DummyEvent
    CommandsMixin = cmds_mod.CommandsMixin

    class FakePlugin(CommandsMixin):
        def __init__(self):
            self._strm_suspects = {}
            self.replies = []
            self.retried_keys = []

        def _post_reply(self, event, msg):
            self.replies.append(msg)

        def _api_strm_retry(self, body, channel_event=None):
            self.retried_keys = body.get("keys", [])
            return {"success": True, "message": f"已清理 {len(self.retried_keys)} 个旧文件"}

    plugin = FakePlugin()
    # 1. 空清单
    event = _DummyEvent(3, {"plugin_id": "FakePlugin", "text": "retry_all"})
    plugin._handle_button_action(event)
    assert len(plugin.replies) == 1
    assert "没有待处理" in plugin.replies[0]

    # 2. 有多个疑似条目
    plugin._strm_suspects = {"9KG:a.mkv": {}, "9KG:b.mkv": {}}
    plugin.replies.clear()
    plugin._handle_button_action(event)
    assert plugin.retried_keys == ["9KG:a.mkv", "9KG:b.mkv"]
    assert len(plugin.replies) == 1
    assert "已清理 2 个旧文件" in plugin.replies[0]
    assert "已提交全部 2 个疑似异常文件" in plugin.replies[0]

# --------------------------------------------------------------------------
# sanitize_buttons：发送前的 64 字节预检（通知与 /rsync_strm list 共用）
# --------------------------------------------------------------------------

def test_sanitize_passes_normal_buttons_through():
    """正常按钮原样通过，oversized 为空。"""
    mod = _strm()
    rows = mod.suspect_command_buttons([KEY], [_pair()], total_count=2)
    out, oversized = mod.sanitize_buttons(rows)
    assert out == rows
    assert oversized == []


def test_sanitize_drops_the_whole_batch_when_one_button_oversizes():
    """
    任何一个按钮超限 → **整批**变 None。

    Telegram 的 64 字节上限作用在整条消息上：有一个超限，整条发送直接失败
    （BUTTON_DATA_INVALID），其余按钮并不会照常发出。所以"只剔掉超限那个"
    救不了这条消息 —— 唯一安全的动作是整批去掉按钮只发正文。
    """
    mod = _strm()
    good = [{"text": "ok", "callback_data": "[PLUGIN]Rsync115Sync|gen"}]
    bad = [{"text": "bad", "callback_data": "[PLUGIN]Rsync115Sync|x " + "长" * 30}]
    out, oversized = mod.sanitize_buttons([good, bad])
    assert out is None, "超限时必须整批丢弃（返回 None），不能只剔一个"
    assert oversized == [bad[0]]
    # 边界：恰好 64 字节是合法的（上限含 64）
    exactly = [{"text": "e", "callback_data": "[PLUGIN]Rsync115Sync|" + "a" * (64 - len("[PLUGIN]Rsync115Sync|"))}]
    out2, oversized2 = mod.sanitize_buttons([exactly])
    assert out2 == [exactly] and oversized2 == [], "恰好 64 字节应当通过"
