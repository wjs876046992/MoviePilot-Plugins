"""
命令侧对疑似清单的处理：list / retry / ignore。

Suspect-list handling over chat: list / retry / ignore.

## 为什么补这三条

看板上有完整的处理闭环（补生成 → 删旧重传 / 忽略），但命令侧此前**只有 `gen`**
—— 用户在手机上收到「疑似异常」通知后**没有下一步可做**，只能等回到电脑前。
这是命令与看板能力之间最大的缺口。

## 两条承重的安全约束

1. **`retry` / `ignore` 必须显式指定目标**（序号或关键字），**不提供 `all`**：
   删旧重传是破坏性操作（先删云端再传）。看板上要勾选 + 确认，命令侧不该比看板
   更宽松 —— 宁可多打几个字。
2. **关键字匹配多条时拒绝并列出候选**，不猜。猜一个最像的，在 `retry` 这条
   路上就是误删好文件。
"""

import importlib
import os
import tempfile

import pytest


def _plugin(suspects=None):
    module = importlib.import_module("app.plugins.rsync115sync")
    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._strm_suspects = dict(suspects or {})
    plugin._strm_watch = {}
    plugin._strm_gen_requested = {}
    plugin._ignored_rules = []
    plugin._sync_pairs = []
    plugin._strm_check_enabled = True
    plugin._notify = False
    plugin._strm_notified = False
    plugin._log = []
    plugin._post_reply = lambda event, msg, *a, **k: plugin._log.append(msg)
    return plugin, module


def _run(plugin, module, arg):
    """走真实的 handle_command 分派（不直接调辅助方法）。"""
    import app.core.event as ev_mod
    plugin._log.clear()
    plugin.handle_command(ev_mod.Event(
        event_type=module.EventType.PluginAction,
        event_data={"action": "strm", "arg_str": arg, "user": "t"}))
    return plugin._log[0] if plugin._log else ""


KEYS = ["电视剧:某剧/S01/E01.mkv", "电视剧:某剧/S01/E02.mkv", "电影:独一份.mkv"]
CONF = {k: {"ts": 1.0, "origin": "scan"} for k in KEYS}


# --------------------------------------------------------------------------
# ⚠️ 顺序：这三条不扫描源端，不能被"没配 strm 目录"的守卫挡住
# --------------------------------------------------------------------------

def test_list_works_without_strm_dir_configured():
    """
    ⚠️ **`list` 不得被"没有映射配置 strm 目录"的守卫挡住。**

    这道守卫是给**扫描类**操作用的（全量扫描 / 关键字查询 / check / gen /
    prune / clear）—— 它们要读 strm 目录才知道指针在不在。

    而我第一版把 `list/retry/ignore` 放在了守卫**之后**，于是没配 `strm_dir`
    的实例上这三条全部被挡下，还回一句与操作无关的「无法扫描」。
    而它们的真实前提只是"清单里有没有条目"——清单完全可能是**迁移进来的
    历史数据**，压根不需要扫描。

    本用例的实例**刻意不配 `strm_dir`**：这正是当初漏掉的场景。
    """
    plugin, module = _plugin(CONF)
    reply = _run(plugin, module, "list")

    assert "1." in reply and KEYS[0] in reply, f"list 没有列出清单：{reply!r}"
    assert "无法扫描" not in reply, "list 被扫描守卫挡住了"


@pytest.mark.parametrize("arg", ["retry 99", "ignore 99"])
def test_targeted_actions_work_without_strm_dir(arg):
    """`retry` / `ignore` 同样不该被扫描守卫挡住（它们只动清单，不读 strm 目录）。"""
    plugin, module = _plugin(CONF)
    reply = _run(plugin, module, arg)
    assert "无法扫描" not in reply, f"{arg} 被扫描守卫挡住了"


# --------------------------------------------------------------------------
# 目标解析：序号 / 关键字 / 拒绝歧义
# --------------------------------------------------------------------------

def test_index_resolves_to_the_nth_entry():
    """序号按 list 的显示顺序解析（1 起），与用户看到的编号一致。"""
    plugin, _ = _plugin(CONF)
    keys, err = plugin._resolve_suspect_target("2")
    assert not err
    assert keys == [list(CONF)[1]], "序号与 list 顺序不一致"


def test_out_of_range_index_is_rejected_with_hint():
    plugin, _ = _plugin(CONF)
    keys, err = plugin._resolve_suspect_target("99")
    assert keys == []
    assert "超出范围" in err and "list" in err


def test_ambiguous_keyword_is_rejected_not_guessed():
    """
    ⚠️ **歧义必须拒绝**。猜一个最像的，在 `retry`（先删云端再传）这条路上
    就是误删好文件 —— 代价不对称，所以宁可让用户把关键字写具体。
    """
    plugin, _ = _plugin(CONF)
    keys, err = plugin._resolve_suspect_target("E0")

    assert keys == [], "歧义关键字被猜了一个目标"
    assert "匹配到 2 条" in err, f"没有说明歧义：{err!r}"
    # 必须列出候选，否则用户无从缩小范围
    assert KEYS[0] in err and KEYS[1] in err


def test_unique_keyword_resolves():
    plugin, _ = _plugin(CONF)
    keys, err = plugin._resolve_suspect_target("独一份")
    assert not err and keys == ["电影:独一份.mkv"]


def test_no_match_message_suggests_the_scan_form():
    """
    无匹配时给的提示要能把用户引向"扫描源端"那条路 —— 因为"清单里没有"
    往往意味着它还没被发现，而不是拼错了。
    """
    plugin, _ = _plugin(CONF)
    keys, err = plugin._resolve_suspect_target("不存在的东西")
    assert keys == []
    assert "没有匹配" in err


def test_subcommand_prefix_is_stripped_from_keyword():
    """
    ⚠️ `retry E0` 里的 `retry ` 前缀必须剥掉，否则关键字变成 "retry e0"、
    永远匹配不到条目，还回一句误导的「没有匹配」。

    这是我实现时真的踩到的 bug —— 第一版直接把 `text_arg` 原样传给了解析器。
    """
    plugin, _ = _plugin(CONF)
    stripped = plugin._strip_subcmd_prefix("retry E0", ("retry", "重传"))
    assert stripped == "E0", f"前缀没剥干净：{stripped!r}"

    # 中文别名同样要剥
    assert plugin._strip_subcmd_prefix("重传 独一份", ("retry", "重传")) == "独一份"
    # 原文大小写要保留（回显需要）
    assert plugin._strip_subcmd_prefix("retry MyFile", ("retry",)) == "MyFile"


# --------------------------------------------------------------------------
# ⚠️ 不提供 all
# --------------------------------------------------------------------------

@pytest.mark.parametrize("arg", ["retry", "retry all", "retry 全部", "ignore", "ignore all"])
def test_no_bulk_target_is_accepted(arg):
    """
    ⚠️ **不得支持 `all`**：删旧重传是破坏性操作（先删云端再传）。
    看板上要勾选 + 确认，命令侧不该比看板更宽松。

    `retry`（无参）也不接受 —— 无参的 `/rsync_strm` 是"扫描"，
    而 `retry` 后面不跟目标就没有可处理的对象。
    """
    plugin, module = _plugin(CONF)
    reply = _run(plugin, module, arg)

    assert "未指定目标" in reply or "没有匹配" in reply, (
        f"{arg!r} 没有被拒绝 —— 批量删旧重传会让用户一次点掉整个清单：{reply!r}"
    )
    assert len(plugin._strm_suspects) == len(CONF), "批量操作动了清单"


# --------------------------------------------------------------------------
# 帮助
# --------------------------------------------------------------------------

def test_help_lists_every_registered_command():
    """
    `/rsync_help` 必须覆盖 `get_command()` 里注册的**全部**命令。

    ⚠️ 这条断言是"文档不许落后于实现"的机器保证。本仓已经有过实例：
    `/rsync_force` 的注册说明写着「忽略冷却限制」，而 v0.2.1 起冷却照常生效
    —— 用户照着用会以为能强制上传，实际不会。
    """
    plugin, module = _plugin()
    text = plugin._help_text()

    registered = [c["cmd"] for c in module.CommandsMixin.get_command()]
    missing = [c for c in registered if c not in text]
    assert not missing, (
        f"这些已注册的命令没写进 /rsync_help：{missing} —— "
        f"帮助是用户唯一的自述入口，漏掉等于没这个功能"
    )


def test_help_mentions_every_strm_subcommand():
    """strm 的子命令也要在帮助里逐条出现（它是能力最密集的一条）。"""
    plugin, _ = _plugin()
    text = plugin._help_text()
    for sub in ("list", "check", "gen", "retry", "ignore", "prune", "clear"):
        assert f"/rsync_strm {sub}" in text, f"帮助里缺 strm 子命令 {sub}"
