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
