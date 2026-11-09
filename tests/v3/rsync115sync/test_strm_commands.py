"""
命令面契约（v0.8.0）：7 条指令、每条一个状态迁移。

Command-surface contract: seven commands, one state transition each.

## 这次收敛要解决的问题（用户原话）

> 「命令几乎没用过，太多太复杂，不清楚文件状态，不清楚指令功能，
>   导致不知道应该用哪个」

旧表面有 11 条，其中 `/rsync_search` + `/rsync_confirm` 是一条依赖内存状态的
两步流程，`/rsync_force` 与 `/rsync_sync` 是两个入口做同一类事。现在的判据是：

- 注册表只有 7 条，且 `_help_text` 覆盖全部；
- 破坏性动作（删旧重传）**必须显式写 `all` 或序号**，只发关键字只预览；
- 命令之间**没有共享的内存上下文** —— 每条都可以单独发送、顺序无关。

## 两条承重的安全约束

1. **多命中不猜**：关键字重试超过 15 条整批拒绝并提示缩小范围，
   不做「先传前 15 个」。猜一个最像的，在删旧重传这条路上就是误删好文件。
2. **预览不产生副作用**：`/rsync_retry <关键字>` 只回清单，绝不调用
   `_retransfer_keys`。删云端旧文件再重传是不可撤销动作。
"""

import importlib

import pytest

REMOVED_COMMANDS = (
    "/rsync_search",
    "/rsync_confirm",
    "/rsync_force",
    "/rsync_backfill_clear",
)

EXPECTED_COMMANDS = [
    "/rsync_status",
    "/rsync_sync",
    "/rsync_retry",
    "/rsync_ignore",
    "/rsync_backfill",
    "/rsync_strm",
    "/rsync_help",
]


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
    plugin._is_running = False
    plugin._pending_queue = {}
    plugin._backfill_queue = []
    plugin._backfill_total = 0
    plugin._last_status = {"success": True, "missing_files": [], "corrupt_files": []}
    plugin._delay_hours = 4
    plugin._log = []
    plugin._retransfer_calls = []
    plugin._sync_calls = []
    plugin._ignore_added = []
    plugin._post_reply = lambda event, msg, *a, **k: plugin._log.append(msg)
    plugin._retransfer_keys = lambda keys, **kw: (
        plugin._retransfer_calls.append(list(keys))
        or {"success": True, "message": "已开始重传"})
    plugin._start_sync_thread = lambda **kw: plugin._sync_calls.append(kw)
    return plugin, module


def _run(plugin, module, action, arg=""):
    """走真实的 handle_command 分派（不直接调辅助方法）。"""
    import app.core.event as ev_mod
    plugin._log.clear()
    plugin.handle_command(ev_mod.Event(
        event_type=module.EventType.PluginAction,
        event_data={"action": action, "arg_str": arg, "user": "t"}))
    return plugin._log[0] if plugin._log else ""


def _run_strm(plugin, module, arg):
    return _run(plugin, module, "strm", arg)


def _source_plugin(tmp_path, names):
    """带真实源目录的实例：让 `_search_target_files` 走真实匹配口径。"""
    plugin, module = _plugin()
    src = tmp_path / "src"
    src.mkdir()
    for name in names:
        (src / name).write_bytes(b"x")
    plugin._sync_pairs = [{
        "name": "电视剧", "src": str(src), "dest": "/115/TV",
        "strm_dir": "", "all_ext": False,
    }]
    plugin._media_extensions = "mkv"
    plugin._exclude_patterns = ""
    return plugin, module


# --------------------------------------------------------------------------
# 命令面：7 条，且帮助与实现不漂移
# --------------------------------------------------------------------------

def test_command_surface_is_seven_state_transitions():
    """注册表恰好是 7 条，顺序即帮助里的分组顺序。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    registered = [c["cmd"] for c in module.CommandsMixin.get_command()]
    assert registered == EXPECTED_COMMANDS


@pytest.mark.parametrize("gone", REMOVED_COMMANDS)
def test_removed_commands_are_not_registered(gone):
    """删掉的命令不能再被市场/宿主当成可用指令列出来。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    registered = [c["cmd"] for c in module.CommandsMixin.get_command()]
    assert gone not in registered


def test_help_lists_every_registered_command():
    """
    `/rsync_help` 必须覆盖 `get_command()` 里注册的**全部**命令。

    这条断言是「文档不许落后于实现」的机器保证：帮助是用户唯一的自述入口，
    漏掉等于那个功能不存在。
    """
    plugin, module = _plugin()
    text = plugin._help_text()

    registered = [c["cmd"] for c in module.CommandsMixin.get_command()]
    missing = [c for c in registered if c not in text]
    assert not missing, (
        f"这些已注册的命令没写进 /rsync_help：{missing} —— "
        f"帮助是用户唯一的自述入口，漏掉等于没这个功能"
    )


def test_help_never_advertises_removed_commands():
    """旧命令必须从帮助里消失，否则用户照着敲会得到「没有这个功能」。"""
    plugin, _ = _plugin()
    text = plugin._help_text()
    for gone in REMOVED_COMMANDS:
        assert gone not in text, f"帮助里仍在教用户使用已删除的 {gone}"


def test_help_has_no_markdown_markers():
    """
    聊天回复走纯文本渲染：`**` 与反引号会原样显示成字面符号。

    ⚠️ 这是仓库的文案红线（docs/Plugin_Dev_Workflow.md §3.5）。需要强调时
    用【】，不用 Markdown。
    """
    plugin, _ = _plugin()
    text = plugin._help_text()
    assert "**" not in text, "帮助里出现 Markdown 加粗标记"
    assert "`" not in text, "帮助里出现 Markdown 代码标记"


def test_help_mentions_only_the_surviving_strm_subcommands():
    """strm 子命令：保留 list/check/gen/clear，删除 retry/ignore/prune。"""
    plugin, _ = _plugin()
    text = plugin._help_text()
    for sub in ("list", "check", "gen", "clear"):
        assert f"/rsync_strm {sub}" in text, f"帮助里缺 strm 子命令 {sub}"
    for gone in ("retry", "ignore", "prune"):
        assert f"/rsync_strm {gone}" not in text, (
            f"帮助里仍在教用户使用已删除的 /rsync_strm {gone}"
        )


# --------------------------------------------------------------------------
# strm：只读清单入口不受扫描守卫影响
# --------------------------------------------------------------------------

def test_list_works_without_strm_dir_configured():
    """
    ⚠️ **`list` 不得被"没有映射配置 strm 目录"的守卫挡住。**

    这道守卫是给**扫描类**操作用的（无参扫描 / 关键字查询 / check / gen）——
    它们要读 strm 目录才知道指针在不在。而 `list` 的真实前提只是"清单里有没有
    条目"：清单完全可能是**迁移进来的历史数据**，压根不需要扫描。
    """
    keys = ["电视剧:某剧/S01/E01.mkv", "电影:独一份.mkv"]
    plugin, module = _plugin({k: {"ts": 1.0, "origin": "scan"} for k in keys})
    reply = _run_strm(plugin, module, "list")

    assert "1." in reply and keys[0] in reply, f"list 没有列出清单：{reply!r}"
    assert "无法扫描" not in reply, "list 被扫描守卫挡住了"


def test_clear_works_without_strm_dir_configured():
    """
    `clear` 同样只操作已有清单。看板没有清空入口，命令是唯一途径 ——
    若被「没有 strm 目录」挡住，用户将无法清空一份坏清单。
    """
    plugin, module = _plugin()
    called = []
    plugin._api_strm_clear = lambda: (called.append(True)
                                      or {"success": True, "message": "已清空"})
    reply = _run_strm(plugin, module, "clear")

    assert called, "clear 被扫描守卫挡住了"
    assert "已清空" in reply


@pytest.mark.parametrize("arg", ["retry foo", "ignore foo", "prune"])
def test_removed_strm_subcommands_are_treated_as_keyword_queries(arg):
    """
    删除的子命令不得再进任何动作分支。

    它们现在只会落到「按关键字查询」这一条无副作用路径上 —— 这是最安全的
    降级：不会删文件、不会改清单，最多提示没有匹配。若某个分支被误加回来，
    本用例会先失败。
    """
    plugin, module = _plugin()
    plugin._sync_pairs = [{
        "name": "电视剧", "src": "/tmp", "dest": "/115/TV",
        "strm_dir": "/strm/TV", "all_ext": False,
    }]
    plugin._reply_strm_keyword = lambda event, text: plugin._log.append(f"keyword:{text}")

    reply = _run_strm(plugin, module, arg)
    assert reply == f"keyword:{arg}", f"{arg!r} 没有落到关键字查询路径：{reply!r}"


# --------------------------------------------------------------------------
# 疑似清单目标解析（通知按钮的底层；不再接受纯数字序号）
# --------------------------------------------------------------------------

def _suspect_plugin():
    keys = ["电视剧:某剧/S01/E01.mkv", "电视剧:某剧/S01/E02.mkv", "电影:独一份.mkv"]
    return _plugin({k: {"ts": 1.0, "origin": "scan"} for k in keys})


def test_ambiguous_keyword_is_rejected_not_guessed():
    """
    ⚠️ **歧义必须拒绝**。猜一个最像的，在删旧重传这条路上就是误删好文件。
    """
    plugin, _ = _suspect_plugin()
    keys, err = plugin._resolve_suspect_target("E0")

    assert keys == [], "歧义关键字被猜了一个目标"
    assert "匹配到 2 条" in err, f"没有说明歧义：{err!r}"
    assert "E01.mkv" in err and "E02.mkv" in err


def test_unique_keyword_resolves():
    plugin, _ = _suspect_plugin()
    keys, err = plugin._resolve_suspect_target("独一份")
    assert not err and keys == ["电影:独一份.mkv"]


def test_pure_digit_is_no_longer_an_index():
    """
    v0.8.0 起没有 `/rsync_strm retry <序号>` 了，所以纯数字也不该再被当作序号。

    清单里没有任何 key 含 "5"：旧实现会解析成第 5 条（越界或猜一条），
    新实现只把它当关键字，结果必须是「没有匹配」。
    """
    plugin, _ = _suspect_plugin()
    keys, err = plugin._resolve_suspect_target("5")
    assert keys == []
    assert "没有匹配" in err


def test_no_match_message_points_at_the_list_route():
    """无匹配时把用户引向仍然存在的入口（list / 看板），不提已删除的命令。"""
    plugin, _ = _suspect_plugin()
    keys, err = plugin._resolve_suspect_target("不存在的东西")
    assert keys == []
    assert "没有匹配" in err
    assert "/rsync_strm list" in err
    assert "/rsync_strm retry" not in err


# --------------------------------------------------------------------------
# /rsync_retry：无状态两步（预览 → 显式执行）
# --------------------------------------------------------------------------

def test_keyword_retry_previews_without_acting(tmp_path):
    """
    ⚠️ 带关键字只预览：必须给出序号、完整 key 和下一步命令，
    但**绝不能**已经调用 `_retransfer_keys`。
    """
    plugin, module = _source_plugin(tmp_path, ["繁花 S01E01.mkv", "繁花 S01E02.mkv"])
    reply = _run(plugin, module, "retry", "繁花")

    assert plugin._retransfer_calls == [], "预览阶段就执行了删旧重传"
    assert "1. 电视剧:繁花 S01E01.mkv" in reply
    assert "2. 电视剧:繁花 S01E02.mkv" in reply
    assert "/rsync_retry 繁花 all" in reply
    assert "/rsync_retry 繁花 <序号>" in reply
    assert "只有写 all 或序号才会执行" in reply


def test_keyword_retry_all_executes_every_match(tmp_path):
    plugin, module = _source_plugin(tmp_path, ["繁花 S01E01.mkv", "繁花 S01E02.mkv"])
    _run(plugin, module, "retry", "繁花 all")

    assert plugin._retransfer_calls == [[
        "电视剧:繁花 S01E01.mkv",
        "电视剧:繁花 S01E02.mkv",
    ]]


def test_keyword_retry_index_executes_only_that_one(tmp_path):
    plugin, module = _source_plugin(tmp_path, ["繁花 S01E01.mkv", "繁花 S01E02.mkv"])
    _run(plugin, module, "retry", "繁花 2")

    assert plugin._retransfer_calls == [["电视剧:繁花 S01E02.mkv"]]


def test_keyword_retry_out_of_range_index_does_nothing(tmp_path):
    plugin, module = _source_plugin(tmp_path, ["繁花 S01E01.mkv"])
    reply = _run(plugin, module, "retry", "繁花 9")

    assert plugin._retransfer_calls == []
    assert "超出范围" in reply


def test_keyword_retry_over_limit_rejects_the_whole_batch(tmp_path):
    """
    ⚠️ 多命中不猜：超过 15 个**整批拒绝**，不做「先传前 15 个」。

    部分执行会让用户以为整批都处理了，而剩下的永远没人管。
    """
    names = [f"繁花 S01E{n:02d}.mkv" for n in range(1, 17)]
    plugin, module = _source_plugin(tmp_path, names)
    reply = _run(plugin, module, "retry", "繁花")

    assert plugin._retransfer_calls == [], "超限时仍然执行了一部分"
    assert "超过单次上限" in reply
    assert "缩小范围" in reply


def test_bare_all_needs_a_keyword(tmp_path):
    """裸 `all` 不猜目标：告诉用户把它跟在关键字后面。"""
    plugin, module = _source_plugin(tmp_path, ["繁花 S01E01.mkv"])
    reply = _run(plugin, module, "retry", "all")

    assert plugin._retransfer_calls == []
    assert "配合关键字" in reply


def test_keyword_retry_without_match_does_nothing(tmp_path):
    plugin, module = _source_plugin(tmp_path, ["繁花 S01E01.mkv"])
    reply = _run(plugin, module, "retry", "不存在")

    assert plugin._retransfer_calls == []
    assert "未在源目录中找到" in reply


# --------------------------------------------------------------------------
# /rsync_sync --all：保留原 /rsync_force 的冷却闸
# --------------------------------------------------------------------------

def test_sync_all_keeps_the_force_cooldown_gate():
    """
    `--all` 继承了 `/rsync_force` 的全部约束，冷却闸是其中最重要的一条。

    旧命令的注册说明曾写着「忽略冷却限制」而实际不忽略 —— 用户照着用会以为
    能强制上传。这里同时钉住「闸被调用」与「未放行时不启动」。
    """
    plugin, module = _plugin()
    gate_calls = []

    def _blocked():
        gate_calls.append(True)
        return False, "全量校验冷却中（每 7 天一次），约 100 小时后可用"

    plugin._force_cooldown_allows = _blocked
    reply = _run(plugin, module, "sync", "--all")

    assert gate_calls, "sync --all 没有走冷却闸"
    assert plugin._sync_calls == [], "冷却未到期却启动了全量对账"
    assert "冷却" in reply
    assert "--all" in reply or "全量" in reply


def test_sync_all_starts_the_full_reconciliation_when_allowed():
    plugin, module = _plugin()
    plugin._force_cooldown_allows = lambda: (True, "")

    _run(plugin, module, "sync", "--all")

    assert plugin._sync_calls, "冷却已到期却没有启动"
    assert plugin._sync_calls[-1].get("mode") == "force", (
        "sync --all 必须走 force 的全量只读对账语义"
    )


# --------------------------------------------------------------------------
# /rsync_backfill clear：合并原 /rsync_backfill_clear
# --------------------------------------------------------------------------

def test_backfill_clear_subcommand_empties_the_queue():
    plugin, module = _plugin()
    plugin._backfill_queue = ["电视剧:a.mkv"]
    plugin._backfill_total = 1
    saves = []
    plugin.save_data = lambda key, value: saves.append((key, value))

    reply = _run(plugin, module, "backfill", "clear")

    assert plugin._backfill_queue == []
    assert plugin._backfill_total == 0
    assert ("backfill_queue", []) in saves
    assert ("backfill_total", 0) in saves
    assert plugin._sync_calls == [], "清空队列不该启动同步线程"
    assert "已清空" in reply


def test_backfill_without_args_still_builds_the_queue():
    """无参行为与 v0.7.0 一致：扫描源端并建立补传队列。"""
    plugin, module = _plugin()
    plugin._build_backfill_candidates = lambda: ["电视剧:a.mkv"]
    plugin._upload_batch_size = 10
    plugin._upload_max_per_window = 20
    plugin._upload_window_secs = 3600
    plugin.save_data = lambda key, value: None

    _run(plugin, module, "backfill")

    assert plugin._backfill_queue == ["电视剧:a.mkv"]
    assert plugin._backfill_total == 1
    assert plugin._sync_calls[-1].get("mode") == "backfill"


# --------------------------------------------------------------------------
# /rsync_ignore：纯数字不再依赖内存里的搜索上下文
# --------------------------------------------------------------------------

def test_ignore_pure_number_is_rejected_not_a_rule():
    """
    旧实现把 `/rsync_ignore 1` 解释为「上一次搜索结果里的第 1 个」。

    v0.8.0 没有搜索上下文了。review 发现「落进 2 字符护栏」仍然危险：
    用户想的是「第 23 条」，实际会忽略所有含 "23" 的文件（S01E23、剧名 1923
    全中）。纯数字一律拒绝并指路完整 key —— 误报是好的，静默误伤不是。
    """
    plugin, module = _plugin()
    # 旧属性已在 v0.8.0 删除；即使有人加回来，也不得被使用
    plugin._add_ignore_rule = lambda rule, **kw: plugin._ignore_added.append(rule) or True

    for digit_input in ("1", "23", "1923"):
        reply = _run(plugin, module, "ignore", digit_input)
        assert plugin._ignore_added == [], f"纯数字 {digit_input} 仍被当成规则"
        assert "纯数字" in reply
    # 非纯数字但只有 1 个字符的串仍走原有 2 字符护栏
    # （"1a" 有 2 个字符，本来就该被接受 —— 护栏拦的是过短的模糊输入）
    plugin._ignore_added.clear()      # _run 只清 _log，不重置收集器
    reply = _run(plugin, module, "ignore", "1")
    assert plugin._ignore_added == []
    assert "纯数字" in reply


def test_ignore_full_key_is_added_as_a_rule():
    """要精确忽略单个文件，直接发完整 key（不再需要先搜索）。"""
    plugin, module = _plugin()
    key = "电视剧:某剧/S01/E01.mkv"
    plugin._add_ignore_rule = lambda rule, **kw: plugin._ignore_added.append(rule) or True

    _run(plugin, module, "ignore", key)

    assert plugin._ignore_added == [key]


def test_ignore_list_and_clear_still_work():
    plugin, module = _plugin()
    plugin._ignored_rules = [{"rule": "繁花", "match": "contains", "created_at": "-"}]
    plugin.save_data = lambda key, value: None

    listed = _run(plugin, module, "ignore", "list")
    assert "1." in listed and "繁花" in listed

    cleared = _run(plugin, module, "ignore", "clear")
    assert plugin._ignored_rules == []
    assert "已清空" in cleared
