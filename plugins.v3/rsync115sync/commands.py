"""
远程命令 /rsync_*：命令表、分发入口与回复通道（阶段 2 拆分）。

Remote /rsync_* commands: command table, dispatch entry, and the reply channel.

与 strm_ops.py / sync_ops.py 同一套约束（见其模块头注释）：Mixin 只搬**代码**，
self.* 状态（_waiting_confirm_retries 等）全部留在插件实例上，本类不持有任何状态。
"""
import os
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from app.core.event import Event, EventType, eventmanager
from app.sdk.logging import logger

from .constants import (
    STRM_SCAN_LIMIT,
    MAX_LOGGED_PATHS as _MAX_LOGGED_PATHS,
    STRM_CMD_LIST_LIMIT as _STRM_CMD_LIST_LIMIT,
    RETRY_KEYWORD_LIMIT as _RETRY_KEYWORD_LIMIT,
)
from .paths import (
    excluded_dir_names as _excluded_dir_names,
    pair_name as _pair_name,
    valid_extension as _valid_extension,
)

# 宿主 MessageType：绑定由组合根（__init__.py）注入 —— 该 try/except 导入是
# 「宿主能力探测」，真相源在组合根；本模块不留拷贝（理由同 strm_ops.py 头注释）。
def _message_type_cls():
    try:
        from . import MessageType as _mt
        if _mt is not None:
            return _mt
    except Exception:  # pragma: no cover
        pass
    return MessageType  # 组合根注入的兜底（可能为 None）


class CommandsMixin:
    """命令表 / 分发 / 回复；本类不持有任何状态。"""

    # ================= 远程命令定义 =================

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/rsync_search",
                "event": EventType.PluginAction,
                "desc": "查入库文件并生成重试指令 (例: /rsync_search 繁花)",
                "category": "工具",
                "data": {"action": "search"}
            },
            {
                "cmd": "/rsync_confirm",
                "event": EventType.PluginAction,
                "desc": "确认执行查找到的待重试文件",
                "category": "工具",
                "data": {"action": "confirm"}
            },
            {
                "cmd": "/rsync_retry",
                "event": EventType.PluginAction,
                "desc": "重试失败/缺失的 115 文件；带文件名则定向单文件重传（先删挂载点旧文件、经 CD2 转发 115 删除，例: /rsync_retry 繁花）",
                "category": "工具",
                "data": {"action": "retry"}
            },
            {
                "cmd": "/rsync_sync",
                "event": EventType.PluginAction,
                "desc": "同步已达冷却时间的入库媒体；带文件名则不等冷却、立即定向同步该文件（例: /rsync_sync 繁花 S01E03）",
                "category": "工具",
                "data": {"action": "sync"}
            },
            {
                "cmd": "/rsync_force",
                "event": EventType.PluginAction,
                "desc": "全量只读对账：逐文件比对源端与 CD2 挂载点的大小，仅对不一致的文件重传（不绕过冷却、共享限流配额、7 天冷却）",
                "category": "工具",
                "data": {"action": "force"}
            },
            {
                "cmd": "/rsync_status",
                "event": EventType.PluginAction,
                "desc": "查看当前115同步进度与冷却/待重试队列",
                "category": "工具",
                "data": {"action": "status"}
            },
            {
                "cmd": "/rsync_ignore",
                "event": EventType.PluginAction,
                "desc": "忽略指定文件不再报警 (例: /rsync_ignore 剧名 或 /rsync_ignore list/clear)",
                "category": "工具",
                "data": {"action": "ignore"}
            },
            {
                "cmd": "/rsync_backfill",
                "event": EventType.PluginAction,
                "desc": "补传存量媒体（含同名字幕），受限流分批推进",
                "category": "工具",
                "data": {"action": "backfill"}
            },
            {
                "cmd": "/rsync_strm",
                "event": EventType.PluginAction,
                "desc": "strm 相关操作（无参=扫描缺 strm / <文件名> 只查该文件 / list 列疑似清单 / check 立即检查观察期 / gen 请助手补生成 / retry <序号> 删旧重传 / ignore <序号> 忽略 / prune 清理无效项 / clear 清空）",
                "category": "工具",
                "data": {"action": "strm"}
            },
            {
                "cmd": "/rsync_backfill_clear",
                "event": EventType.PluginAction,
                "desc": "清空存量补传队列",
                "category": "工具",
                "data": {"action": "backfill_clear"}
            },
            {
                "cmd": "/rsync_help",
                "event": EventType.PluginAction,
                # 说明保持短：聊天渠道的指令列表不换行，写长了会被截断
                "desc": "列出全部指令与用法（忘了怎么用就发这条）",
                "category": "工具",
                "data": {"action": "help"}
            }
        ]

    # ---- 指令帮助 / command reference ------------------------------------

    def _help_text(self) -> str:
        """
        全部指令与用法（`/rsync_help`）。

        The command reference. 内容按**用户要做的事**分组，而不是按代码里的
        action 顺序 —— 手机上要能一眼找到"我现在想干什么"。

        ⚠️ 维护要求：**新增/修改命令时必须同步改这里**。它列的是用户唯一的
        自述入口，写错等于教用户用不存在的功能（本仓已有过「说明停留在旧版本」
        的实例：`/rsync_force` 的注册说明写着"忽略冷却限制"，而 v0.2.1 起冷却
        照常生效 —— 用户照着用会以为能强制上传，实际不会）。
        Keep in sync with get_command(); a stale reference teaches users to call
        things that do not exist.
        """
        return (
            f"📖 115 网盘同步助手 · 指令一览\n"
            f"===============================\n"
            f"【查看状态】\n"
            f"/rsync_status —— 同步状态报告：冷却队列、异常清单、扫描健康度\n"
            f"/rsync_help —— 这条帮助\n"
            f"\n"
            f"【触发同步】\n"
            f"/rsync_sync —— 同步已达冷却时间的入库媒体（冷却时长见配置页）\n"
            f"/rsync_sync <文件名> —— ⚡ 不等冷却，立即上传该文件（会自动移出冷却队列）\n"
            f"/rsync_force —— 全量只读对账：逐文件比对源端与 CD2 挂载点的大小，\n"
            f"                仅对不一致的文件重传（⚠️ 它比的是挂载视图，不是云端）\n"
            f"                （不绕过冷却、共享限流配额、7 天冷却）\n"
            f"/rsync_backfill —— 补传存量媒体（源端有、本插件从未处理过的）\n"
            f"/rsync_backfill_clear —— 清空补传队列\n"
            f"\n"
            f"【处理异常】\n"
            f"/rsync_retry —— 重试缺失/残缺文件\n"
            f"/rsync_retry <文件名> —— 定向单文件重传（先删挂载点旧文件 → CD2 转发 115 删除 → 重传）\n"
            f"/rsync_search <关键字> —— 在源端查文件，生成候选清单\n"
            f"/rsync_confirm <序号|all> —— 确认执行上一步查找到的文件\n"
            f"\n"
            f"【strm 交叉验证】\n"
            f"/rsync_strm —— 全量扫描缺 strm 的文件\n"
            f"/rsync_strm <文件名> —— 只查这一个（不遍历整库，秒回）\n"
            f"/rsync_strm list —— 列出疑似清单（带序号）\n"
            f"/rsync_strm check —— 立即检查观察期（不等下一轮巡检）\n"
            f"/rsync_strm gen —— 请助手补生成 strm（多数问题的第一步）\n"
            f"/rsync_strm retry <序号|关键字> —— 删旧重传（⚠️ 先删挂载点旧文件再传，破坏性）\n"
            f"/rsync_strm ignore <序号|关键字> —— 误报，不再提醒\n"
            f"/rsync_strm prune —— 清理无效项（非视频/已忽略/源端已删）\n"
            f"/rsync_strm clear —— 清空两个清单\n"
            f"\n"
            f"【忽略清单】\n"
            f"/rsync_ignore <剧名> —— 不再为它报警\n"
            f"/rsync_ignore list —— 查看全部规则\n"
            f"/rsync_ignore remove <序号> —— 移除某条\n"
            f"/rsync_ignore clear —— 清空全部\n"
            f"\n"
            f"===============================\n"
            f"💡 看板「配置 → 插件页面」有同样的全部功能，且能看到文件清单。\n"
            f"💡 疑似清单的处理顺序：先 /rsync_strm gen，仍无 strm 再 retry。"
        )

    # ---- 疑似清单的命令侧处理 / suspect handling over chat ---------------

    def _strm_suspect_list_text(self) -> str:
        """
        用**带序号的列表**回报疑似清单（`retry` / `ignore` 的指定依据）。

        Render the suspect list with stable indices.

        ⚠️ 序号必须基于**确定顺序**：`Store.by_status` 按 `updated_at` 排序，
        因此同一个时刻生成的列表在同一条消息里可复现。序号还会**截断显示**
        （清单可能有上百条），但截断只影响显示 —— 超出的条目仍可用关键字指定。
        Indices come from a deterministic ordering; truncation is display-only.
        """
        keys = list(self._strm_suspects.keys())
        if not keys:
            return "✅ 当前没有 strm 疑似异常。\n💡 /rsync_strm 可全量扫描一次。"

        shown = keys[:_STRM_CMD_LIST_LIMIT]
        lines = [f"{i+1}. {k}" for i, k in enumerate(shown)]
        reply = (f"📺 strm 疑似异常（共 {len(keys)} 个）：\n"
                 f"--------------------------------\n"
                 + "\n".join(lines))
        if len(keys) > len(shown):
            reply += (f"\n… 其余 {len(keys) - len(shown)} 个未列出"
                      f"（可用关键字直接指定，不必看全清单）")
        reply += (
            f"\n--------------------------------\n"
            f"• 先试补生成（多数情况够用）: /rsync_strm gen\n"
            f"• 确认是上传失败 → 删旧重传: /rsync_strm retry <序号>\n"
            f"• 误报，不想再提醒 → 忽略: /rsync_strm ignore <序号>\n"
            f"※ retry 会**先删挂载点上的旧文件**（经 CD2 转发 115 删除）再重传，请先确认。"
        )
        return reply

    @staticmethod
    def _strip_subcmd_prefix(text: str, prefixes: Tuple[str, ...]) -> str:
        """
        从参数里剥掉子命令前缀，只留目标（序号或关键字）。

        Strip the subcommand prefix, leaving only the target.

        ⚠️ 用**原文**剥而不是小写副本：文件名的大小写要原样保留（回显时可读），
        而匹配本身在 `_resolve_suspect_target` 里已做大小写不敏感处理。
        中文前缀（重传/忽略）同样需要剥 —— 用户两种写法都会用。
        Strip from the original text so the filename keeps its case.
        """
        raw = (text or "").strip()
        low = raw.lower()
        for pref in prefixes:
            if low.startswith(pref.lower()):
                return raw[len(pref):].strip()
        return raw

    def _example_cmd_target(self, shown: List[Dict[str, Any]],
                            all_cooling: List[Dict[str, Any]]) -> str:
        """
        为示例命令挑一个**真的能用**的片段。

        Pick a fragment for the example command that actually resolves.

        ## 为什么不能张嘴就取第一条的文件名

        实测撞到过：冷却队列里同时有 `S01/E01.mkv` 与 `S02/E01.mkv` 时，
        示例给出 `E01.mkv` —— 用户照着敲，`_resolve_pending_target` 命中 2 条
        并拒绝。**一个照抄就会被拒的示例比没有示例更糟**：它让人以为功能坏了。

        因此按唯一性挑：优先找文件名在本队列里唯一的条目，给出它的文件名；
        全都重名则退到"末两级目录"（`S01/E01.mkv`），那通常已经能区分。
        实在挑不出来就**不给示例**，只留一行说明 —— 与 `strm.brief_target_of`
        同一条原则：宁可让人自己看清单，也不要给一个会指错/被拒的目标。
        """
        by_name: Dict[str, int] = {}
        for item in all_cooling:
            name = self._brief_cmd_hint(item["key"]).lower()
            by_name[name] = by_name.get(name, 0) + 1
        for item in shown:
            hint = self._brief_cmd_hint(item["key"])
            if by_name.get(hint.lower(), 0) == 1:
                return hint
        # 文件名全重名 → 用末两级（目录/文件名），它通常带上季或剧名
        for item in shown:
            parts = [p for p in item["key"].split("/") if p]
            if len(parts) >= 2:
                return "/".join(parts[-2:])
        return "（请照上面某一行自行截取片段，确保只命中一条）"

    @staticmethod
    def _brief_cmd_hint(key: str) -> str:
        """
        从队列 key 里取一段**够短又能搜到**的片段，供示例命令使用。

        Short-but-findable fragment of a queue key, for the example command.

        ⚠️ 与 `strm.brief_target_of` 的取向不同：那个是**有通知余量**的场景，
        会为「唯一性」逐级退让（长一点也认）。这里是往一条本就拥挤的状态报告里
        插示例，短是硬指标，因此只取**文件名部分**（去掉映射前缀与目录）。
        代价是用户真抄下去时可能多命中几条 —— 那时 `_resolve_pending_target`
        会列出候选让他写得更具体，而不是猜一个（不猜是刻意的，见其 docstring）。
        """
        body = key.rsplit("/", 1)[-1] if "/" in key else key
        # 剥掉映射前缀（"电视剧:国产剧/…" → 若整条没有目录，前缀就还在开头）
        if ":" in body:
            body = body.split(":", 1)[1]
        return body or key

    def _resolve_pending_target(self, text: str) -> Tuple[str, str]:
        """
        把用户的指定（关键字）解析成**冷却队列**里的一个 key；返回 `(key, 错误)`。

        Resolve a keyword to a single key in the cool-down queue.

        ## 为什么只是关键字，不给序号

        「疑似清单」有 `list` 子命令给出稳定序号，用户 `retry 2` 之前能先看一眼。
        冷却队列**没有**这样一个入口，因此给序号等于让用户盲猜 —— 而这条路的
        后果是**立刻把那个文件传上去**（绕过冷却）。猜错的对象会被提前上传，
        虽不如删错文件严重，但同样不可预期。

        关键字由用户看着手机上的通知/文件名直接写，唯一性在这里当场校验：
        多命中就拒绝并列出候选，与 `_resolve_suspect_target` 同一条原则
        （**不猜**）。冷却队列通常也就几个到几十个条目，这个代价可以接受。
        """
        text = (text or "").strip()
        if not text:
            return "", "未指定目标。例如：/rsync_sync 繁花 S01E03"
        keys = list((getattr(self, "_pending_queue", None) or {}).keys())
        if not keys:
            return "", ("冷却队列是空的 —— 没有可提前上传的文件。\n"
                        "用 /rsync_status 查看当前状态。")
        kw = text.lower()
        matched = [k for k in keys if kw in k.lower()]
        if not matched:
            # 命中的可能不是冷却队列里的：明确区分「没有这个文件」与
            # 「有这个文件但没在冷却」—— 后者其实是好消息（已在传或已传完），
            # 而一句笼统的"没找到"会让用户以为文件名写错了。
            healed = self._search_target_files(text)["matched"]
            if healed:
                return "", (f"「{text}」不在冷却队列里（源端存在 {len(healed)} 个匹配）。\n"
                            f"它可能已经在传、传过了，或压根没入库。\n"
                            f"• 想确认状态 → /rsync_status\n"
                            f"• 属实缺文件 → /rsync_retry {text}")
            return "", f"冷却队列里没有匹配「{text}」的条目。\n用 /rsync_status 查看当前队列。"
        if len(matched) > 1:
            shown = "\n".join(f"• {k}" for k in matched[:_STRM_CMD_LIST_LIMIT])
            return "", (f"「{text}」匹配到 {len(matched)} 条，请写得更具体：\n{shown}\n"
                        f"（冷却队列没有稳定序号，因此只能按关键字指定）")
        return matched[0], ""

    def _resolve_suspect_target(self, text: str) -> Tuple[List[str], str]:
        """
        把用户的指定（序号 / 关键字）解析成疑似清单里的 key 列表。

        Resolve a user-specified target (index or keyword) to suspect keys.

        返回 `(keys, 错误说明)`；成功时错误说明为空串。

        ⚠️ 关键字匹配**多个时不猜**：返回候选清单让用户把范围缩小。
        猜一个最像的，在 `retry`（先删挂载点文件再传）这条路上就是误删好文件。
        Never guess among multiple keyword matches on a destructive path.
        """
        text = (text or "").strip()
        if not text:
            return [], "未指定目标。请用序号或关键字，例如：/rsync_strm retry 2"

        keys = list(self._strm_suspects.keys())
        if not keys:
            return [], "当前没有 strm 疑似异常。"

        # ① 纯数字 = 序号（1 起，按清单显示顺序）
        if text.isdigit():
            idx = int(text)
            if not 1 <= idx <= len(keys):
                return [], (f"序号 {idx} 超出范围（当前 1~{len(keys)}）。"
                            f"\n用 /rsync_strm list 查看清单。")
            return [keys[idx - 1]], ""

        # ② 别名形式 "retry 2" / "ignore 2" —— 从各子命令分支里透传时可能带前缀
        parts = text.split()
        if len(parts) == 2 and parts[1].isdigit():
            return self._resolve_suspect_target(parts[1])

        # ③ 关键字：**只搜疑似清单**（不遍历源端）——
        #    这个入口的语义是"处理清单里这一条"，不是通用查找器。
        kw = text.lower()
        matched = [k for k in keys if kw in k.lower()]
        if not matched:
            return [], (f"疑似清单里没有匹配「{text}」的条目。"
                        f"\n用 /rsync_strm list 查看全部，或 /rsync_strm {text} 扫描源端。")
        if len(matched) > 1:
            shown = "\n".join(f"• {k}" for k in matched[:_STRM_CMD_LIST_LIMIT])
            return [], (f"「{text}」匹配到 {len(matched)} 条，请把关键字写得更具体：\n{shown}")
        return matched, ""

    def _strm_suspect_action(self, event, arg: str, action: str) -> str:
        """
        对疑似清单里的**一个**目标执行 retry 或 ignore，返回给用户的话。

        Run retry/ignore on one resolved target and return the reply text.

        复用看板的 `_api_strm_retry` / `_api_strm_ignore` —— 那两条路径里各有
        越权护栏（只接受疑似清单内的 key）与副作用（补生成标记失效、通知闩锁
        重置），**在命令侧重写一遍必然漂移**。这里只做"序号/关键字 → key"的
        解析，把结果原样交给同一个实现。
        """
        keys, err = self._resolve_suspect_target(arg)
        if err:
            return err
        key = keys[0]

        if action == "retry":
            # ⚠️ 不做二次确认：手机端确认弹窗体验差，而**破坏性操作的门槛
            # 已经用"必须显式指定目标 + 不提供 all"表达了**。回执里明确写出
            # 删了什么、正在重传什么，让误操作可追溯。
            # 透传 event：重传过程与结果要回到用户手上（不传=静默，见其实现注释）
            res = self._api_strm_retry({"keys": [key]}, channel_event=event)
            head = "🔁 " if res.get("success") else "⚠️ "
            return f"{head}{res.get('message', '操作失败')}\n\n目标：{key}"
        res = self._api_strm_ignore({"keys": [key]})
        head = "🚫 " if res.get("success") else "⚠️ "
        return f"{head}{res.get('message', '操作失败')}\n\n目标：{key}"

    @staticmethod
    def _parse_confirm_indices(arg_str: str, total_count: int) -> List[int]:
        """
        解析用户输入的确认重试序号
        支持格式：
          - "" 或 "all" 或 "全部": 全选 [0..total_count-1]
          - "1": 选单个
          - "1,2" 或 "1 2": 选多个
          - "1-2 4" 或 "1~3": 范围 + 单个混合
        """
        if not arg_str or arg_str.lower() in ["all", "全部"]:
            return list(range(total_count))

        selected = set()
        normalized = arg_str.replace(",", " ").replace("，", " ")
        parts = normalized.split()

        for p in parts:
            if "-" in p or "~" in p:
                sep = "-" if "-" in p else "~"
                subparts = p.split(sep)
                if len(subparts) == 2 and subparts[0].isdigit() and subparts[1].isdigit():
                    start, end = int(subparts[0]), int(subparts[1])
                    for idx in range(min(start, end), max(start, end) + 1):
                        if 1 <= idx <= total_count:
                            selected.add(idx - 1)
            elif p.isdigit():
                idx = int(p)
                if 1 <= idx <= total_count:
                    selected.add(idx - 1)

        return sorted(list(selected))

    # ================= 交互命令分发 (带关键字查找与确认重试) =================

    def _dispatch_command(self, event: Event):
        """
        处理 /rsync_* 远程指令的**实现**。

        Implementation of the /rsync_* command dispatcher. The action comes from
        the command data registered in `get_command()`.

        ⚠️ **不要把 `@eventmanager.register(EventType.PluginAction)` 加回本方法，
        也不要把它改名回 `handle_command`。** 事件处理器必须定义在插件的
        **组合根类**（`__init__.py` 的 `Rsync115Sync`）里 —— 宿主按
        `owner_class.__name__` 查插件实例，而本类叫 `CommandsMixin`，
        查不到任何插件，解析失败后宿主**静默跳过**该处理器：
        没有异常、没有日志、命令一去不回（详见 `__init__.py` 里那段长注释）。
        The registered handler is the thin wrapper on `Rsync115Sync`; this method is
        only its implementation.
        """
        data = event.event_data or {}
        action = data.get("action")
        # 兼容 MoviePilot 的 arg_str 以及各类渠道传入的参数
        text_arg = (
            data.get("arg_str")
            or data.get("args")
            or data.get("arg")
            or data.get("text")
            or ""
        ).strip()

        if action == "help":
            self._post_reply(event, self._help_text())
            return
        if action == "search":
            # 根据关键字从本地源目录查找匹配的文件，供确认后定向重传
            if not text_arg:
                self._post_reply(event, "⚠️ 请提供搜索关键字，例如：/rsync_search 繁花")
                return

            keyword = text_arg.lower()
            matched = []
            # 展示上限：手机消息太长会被渠道截断或淹没，列表只展示前 N 条。
            # ⚠️ 但候选必须**全量收集**、只截断展示 —— 早先实现把收集也截断在 15，
            # 导致超过 15 个匹配时用户永远选不到第 16 个（all 也只重传前 15 个），
            # 用户实测「24 个文件只找到 15 个」即此缺陷。
            _SEARCH_DISPLAY_LIMIT = 15

            for pair in self._sync_pairs:
                src_dir = (pair.get("src") or "").strip().rstrip("/")
                pair_name = _pair_name(pair)
                if not os.path.exists(src_dir):
                    continue
                # 过滤口径：扩展名 + 排除规则，两者都走与入库闸门**同一份实现**。
                # 早先这两者都不应用，列表会混入 .nfo/.jpg 等永远不会被同步的文件，
                # 重传它们浪费限流配额且没有意义；后来又各自维护一份实现，
                # 漂移成「搜索能搜到但同步不认」。
                excluded_dirs = _excluded_dir_names(self._exclude_patterns)

                for root, dirs, files in os.walk(src_dir):
                    # 就地裁剪被排除的目录（@eaDir/#recycle 等），不下钻
                    dirs[:] = [d for d in dirs if d not in excluded_dirs]
                    for f in files:
                        if keyword not in f.lower():
                            continue
                        if not _valid_extension(pair, f, self._media_extensions):
                            continue
                        rel_f = os.path.relpath(os.path.join(root, f), src_dir)
                        matched.append(f"{pair_name}:{rel_f}")

            if not matched:
                self._post_reply(event, f"🔍 未找到包含关键字「{text_arg}」的本地入库媒体文件。")
                return

            # 候选全量保留（confirm 可重传全部），仅展示层截断
            self._waiting_confirm_retries = matched
            display = matched[:_SEARCH_DISPLAY_LIMIT]
            list_text = "\n".join([f"{i+1}. {item}" for i, item in enumerate(display)])
            truncated_hint = (
                f"（另有 {len(matched) - _SEARCH_DISPLAY_LIMIT} 个未列出，"
                f"确认 all 时会一并重传）\n" if len(matched) > _SEARCH_DISPLAY_LIMIT else ""
            )
            reply = (
                f"🔍 找到 {len(matched)} 个匹配媒体"
                f"{'，展示前 %d 个' % _SEARCH_DISPLAY_LIMIT if len(matched) > _SEARCH_DISPLAY_LIMIT else ''}：\n"
                f"--------------------------------\n"
                f"{list_text}\n"
                f"{truncated_hint}"
                f"--------------------------------\n"
                f"👉 请发送确认指令触发重传：\n"
                f"• 全部重传: /rsync_confirm (或 /rsync_confirm all)\n"
                f"• 选单序号: /rsync_confirm 1\n"
                f"• 多个序号: /rsync_confirm 1,2 或 /rsync_confirm 1 2\n"
                f"• 范围序号: /rsync_confirm 1-2 4\n"
                f"⚠️ 注意：确认只对已收集的候选生效，当前候选共 {len(matched)} 个"
            )
            self._post_reply(event, reply)

        elif action == "confirm":
            if not self._waiting_confirm_retries:
                self._post_reply(event, "⚠️ 当前没有等待确认的重试文件，请先发送 /rsync_search <关键字> 查找文件。")
                return

            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中，请稍后再试。")
                return

            # 解析用户输入的序号参数（支持 1 / 1,2 / 1-2 4 / all / 全部 等）
            total_candidates = self._waiting_confirm_retries
            total_count = len(total_candidates)
            selected_indices = self._parse_confirm_indices(text_arg, total_count)

            if not selected_indices:
                self._post_reply(
                    event,
                    f"⚠️ 输入的序号无效！有效范围为 1~{total_count}。\n"
                    f"示例：/rsync_confirm 1 或 /rsync_confirm 1,2 或 /rsync_confirm 1-2 4 或 /rsync_confirm all"
                )
                return

            to_retry = [total_candidates[i] for i in selected_indices]
            self._waiting_confirm_retries = []

            chosen_names = "\n".join([f"• {item}" for item in to_retry])
            self._post_reply(
                event,
                f"✅ 已确认重试 ({len(to_retry)}/{total_count} 个媒体)：\n"
                f"{chosen_names}\n"
                f"--------------------------------\n"
                f"🚀 正在启动定向上传..."
            )
            self._start_sync_thread(mode="retry", custom_files=to_retry, channel_event=event)

        elif action == "sync":
            # 带文件名 = 不等冷却、立即定向同步（看板「立即同步」按钮的命令版）。
            #
            # 为什么需要这条路：冷却期的现职是「等文件写完 / 等外挂字幕到齐」，
            # 但用户常常**知道**那个文件已经安顿好了（刚跑完刮削、字幕已下齐），
            # 此时干等 4 小时毫无道理。看板一直有这个按钮（`_api_sync_item`），
            # 而命令侧此前没有 —— 用户在手机上收到通知却只能干等。
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中。")
                return
            if not text_arg:
                self._start_sync_thread(mode="ready", channel_event=event)
                return

            target, err = self._resolve_pending_target(text_arg)
            if err:
                self._post_reply(event, err)
                return
            res = self._api_sync_item({"keys": [target]})
            head = "🚀 " if res.get("success") else "⚠️ "
            self._post_reply(event, f"{head}{res.get('message', '操作失败')}\n\n目标：{target}")

        elif action == "force":
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中。")
                return
            allowed, reason = self._force_cooldown_allows()
            if not allowed:
                self._post_reply(
                    event,
                    f"⛔ 已跳过全量校验：{reason}\n"
                    f"该操作会对源/目标做只读全量对账（逐文件 stat，开销大）；"
                    f"上传仅针对问题文件并共享限流配额（v0.2.1+）。\n"
                    f"如需补传存量媒体，请改用 /rsync_backfill（只扫源端、按配额分批）。"
                )
                return
            self._start_sync_thread(mode="force", channel_event=event)

        elif action == "retry":
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中。")
            elif text_arg:
                # 带关键字 = 「目标明确」的单文件补偿：
                # 搜源端 → 删**目标端（CD2 挂载点）上的文件** → 定向重传。
                #
                # 为什么必须先删：CD2 改名失败等场景下，CD2 挂载视图会显示目标文件
                # 「存在且大小正常」，但 115 服务端实际只有改名失败的半成品
                # （形如 影片.mkv..xrp4gj）。此时 rsync --size-only 比较源/目标大小
                # 判定「已同步」而跳过 —— 重传永远不会发生，且插件无法从视图发现这一点。
                # 本插件**没有直连 115 的能力**：它只能操作 CD2 挂载点，由 CD2 决定
                # 是否把这次 rm 转发成 115 的删除。正常情况下会转发，于是云端与视图
                # 一起纠正；若 CD2 不转发，删除只在本地视图生效（云端残留仍在）——
                # 这一点无法由插件验证，所以**不能**把「删了挂载点」等同于「删了云端」。
                # 之后 rsync 发现目标端确无此文件，必然完整重传并重新走改名流程。
                # （同 sync_115 仓库 retry_file.sh 的既有做法，此处插件化并加护栏。）
                # Keyword mode = targeted single-file compensation. The destination
                # file must be deleted via the CD2 mount first: the mount view may
                # report the file as present while the 115 cloud only holds a
                # rename-failed partial, which would make --size-only skip the
                # re-transfer entirely.
                result = self._search_target_files(text_arg)
                if not result["matched"]:
                    self._post_reply(event,
                                     f"🔍 未在源目录中找到包含「{text_arg}」的文件，未做任何改动。")
                    return
                if result["truncated"]:
                    self._post_reply(
                        event,
                        f"⚠️ 关键字「{text_arg}」匹配到 {result['total']} 个文件，超过单次上限 "
                        f"{_RETRY_KEYWORD_LIMIT} 个。\n请用更精确的文件名缩小范围，本次未做任何改动。"
                    )
                    return
                # ⚠️ 删旧重传的**唯一实现**在 `_retransfer_keys`。
                # 这里曾经自己实现了一遍（预检、删除、失败处置全在这里），
                # 结果与 `_api_strm_retry` 那份悄悄分叉：这条路径**没有前置预检**，
                # 于是会出现「文件已从目标端删掉，却因为限流退避/挂载未就绪而没有
                # 重传」—— 而预检存在的全部意义就是挡掉这个形态。
                # 收敛到一处后，两个入口的行为由同一份代码保证一致。
                res = self._retransfer_keys(result["matched"], channel_event=event,
                                            origin="关键字定向重传")
                head = "🧹 " if res.get("success") else "⚠️ "
                self._post_reply(event, f"{head}{res.get('message', '操作失败')}")
            else:
                # 不带关键字：维持既有语义 —— 重传历史异常清单
                self._start_sync_thread(mode="retry", channel_event=event)

        elif action == "backfill":
            # 只扫源端（零 API），再按批次与限流配额分多轮推进
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中，请稍后再试。")
                return
            self._post_reply(event, "🔍 正在扫描本地入库文件（不访问 115）...")
            candidates = self._build_backfill_candidates()
            if not candidates:
                self._post_reply(event, "✅ 没有需要补传的存量文件。")
                return
            self._backfill_queue = candidates
            self._backfill_total = len(candidates)
            self.save_data("backfill_queue", self._backfill_queue)
            self.save_data("backfill_total", self._backfill_total)
            self._post_reply(
                event,
                f"📦 已建立补传队列：{len(candidates)} 个文件（含同名字幕）\n"
                f"受批次上限 {self._upload_batch_size} 个与限流配额 "
                f"{self._upload_max_per_window} 个/{self._upload_window_secs // 60} 分钟约束，\n"
                f"将分多轮自动推进，可发送 /rsync_status 查看进度。"
            )
            self._start_sync_thread(mode="backfill", custom_files=list(candidates),
                                    channel_event=event)

        elif action == "strm":
            # 先算好小写参数，并处理**不扫描源端**的三条（list/retry/ignore）。
            # ⚠️ 它们必须排在下面那道「必须配置了 strm 目录才能扫描」的守卫**之前**：
            # 那三条的语义是“处理已有清单里的条目”，不扫描、也不需要 strm_dir。
            # 曾经写反过 —— 没配 strm_dir 的实例上它们全被挡下。
            # `retry`/`ignore` 还**必须显式指定目标**（序号或关键字），
            # 不提供 all：删旧重传是破坏性操作，命令侧不该比看板更宽松。
            arg_lower = (text_arg or "").lower()
            # ⚠️ 这三条必须排在**下面那道守卫之前** —— 它们是"处理已有清单"，
            # 不扫描源端、也不需要 strm 目录配置。
            #
            # 这个顺序曾经写反：`list/retry/ignore` 放在了「没有映射配置 strm 目录
            # → 无法扫描」的守卫之后，于是**没配 strm_dir 的实例上这三条全部被
            # 挡下**，提示还是"无法扫描"这种与操作无关的话。而它们的实际前提只是
            # "清单里有没有条目" —— 清单可能是迁移进来的历史数据，压根不需要扫描。
            if arg_lower in ("list", "ls", "列表", "清单"):
                self._post_reply(event, self._strm_suspect_list_text())
                return
            if arg_lower.startswith(("retry", "重传")) or arg_lower in ("删旧重传",):
                # ⚠️ 要把子命令前缀从参数里**剥掉**再交给解析器。
                # 之前直接传 `text_arg`（原样含 "retry E0"），于是关键字变成
                # "retry e0"、永远匹配不到条目，还回一句误导的"没有匹配"。
                self._post_reply(event, self._strm_suspect_action(
                    event, self._strip_subcmd_prefix(text_arg, ("retry", "重传")), "retry"))
                return
            if arg_lower.startswith(("ignore", "忽略")) and text_arg.strip():
                self._post_reply(event, self._strm_suspect_action(
                    event, self._strip_subcmd_prefix(text_arg, ("ignore", "忽略")), "ignore"))
                return

            # /rsync_strm         → 全量主动扫描
            # /rsync_strm <关键字> → 只查指定文件（不遍历整库）
            # /rsync_strm clear   → 清空疑似与待观察清单
            # /rsync_strm prune   → 只清理无效条目
            #
            # 两种模式并存的原因：全量扫描是「我不知道哪些文件有问题」的答案，
            # 但当用户**已经明确知道**是哪个文件时（例如在 115 云端看到残留），
            # 遍历整库纯属浪费 —— 关键字模式直接定位那一个，秒回。

            # ⚠️ 这道守卫只针对**下面这些会扫描源端的操作**（无参全量扫描 /
            # 关键字查询 / check / gen / prune / clear）。
            # `list` / `retry` / `ignore` 已在上面提前返回，不受它约束。
            if not self._strm_check_enabled:
                self._post_reply(event, "⚠️ strm 交叉验证已在配置页关闭，无法扫描。")
                return
            configured = [p for p in self._sync_pairs if (p.get("strm_dir") or "").strip()]
            if not configured:
                self._post_reply(
                    event,
                    "⚠️ 没有任何映射配置了 strm 目录，无法扫描。\n"
                    "请到配置页为需要验证的映射填写「strm 目录」（strm 插件的输出根目录）。"
                )
                return


            if arg_lower in ("clear", "清空", "reset"):
                result = self._api_strm_clear()
                self._post_reply(event, "🧹 " + result["message"])
                return
            if arg_lower in ("prune", "清理"):
                result = self._api_strm_prune()
                self._post_reply(event, "🧹 " + result["message"])
                return
            if arg_lower in ("check", "检查"):
                # 立即检查观察期条目的 strm 是否已生成（不等下一轮巡检）
                #
                # ⚠️ 这里用 `_api_strm_check` 而**不是**直接调 `_check_watch_now`：
                # 后者只负责"清"（把不自洽的疑似条目移出），措辞在端点那一层。
                # 早先直接调 `_check_watch_now`，于是命令侧**只**做观察期判定、
                # 疑似清单一个条目都不动 —— 而通知正文已把 `check` 写成补生成后的
                # 标准动作，用户照抄敲下去却看不到任何变化。
                # 同一个动作从看板与从命令做出来必须一致。
                result = self._api_strm_check({"keys": list(self._strm_watch.keys())})
                self._post_reply(event, ("📺 " if result.get("success") else "⚠️ ")
                                 + result.get("message", "检查失败"))
                return
            if arg_lower in ("gen", "generate", "生成", "补生成"):
                # 与看板按钮同一入口：先请 strm 助手补生成，成功了就不必删旧重传。
                # 远程命令不传 keys 时处理**全部**疑似条目（看板上则可以只勾一部分），
                # 但仍受同一个目录上限保护 —— 超限整批拒绝，不自动放大访问量。
                result = self._api_strm_generate({"keys": list(self._strm_suspects.keys())})
                self._post_reply(event, ("📺 " if result.get("success") else "⚠️ ")
                                 + result.get("message", "操作失败"))
                return
            if text_arg:
                self._reply_strm_keyword(event, text_arg)
                return

            self._post_reply(event, "🔍 正在扫描源端并逐个比对 strm（纯本地，不访问 115）...")
            try:
                result = self._strm_scan()
            except Exception as e:
                logger.error(f"[Rsync115Sync] 主动 strm 扫描异常: {e}\n{traceback.format_exc()}")
                self._post_reply(event, f"❌ 扫描过程出错：{e}")
                return
            if not result.get("success"):
                self._post_reply(event, f"⚠️ {result.get('message')}")
                return
            data = result.get("data") or {}
            reply = (
                f"📺 strm 扫描完成\n"
                f"--------------------------------\n"
                f"已检查源端文件: {data.get('checked', 0)} 个\n"
                f"缺对应 strm: {data.get('found', 0)} 个\n"
                f"新增疑似异常: {data.get('added', 0)} 个\n"
            )
            # ⚠️ 「缺 N 个」与「新增 M 个」对不上时**必须解释差额**，否则用户
            # 只会看到「检测到两个，却没有出现在列表里」这种自相矛盾的结论 ——
            # 实测反馈就是这么来的（那两个是被忽略规则跳过的）。
            # 三个去向各是一句话，缺任何一句都会重新变成「数字对不上」。
            skipped_ignored = data.get("skipped_ignored", 0)
            skipped_watching = data.get("skipped_watching", 0)
            if skipped_ignored:
                reply += (f"🚫 其中 {skipped_ignored} 个已命中「忽略」规则，按你的要求"
                          f"不再报警，因此不进疑似清单（/rsync_ignore list 查看规则）。\n")
            if skipped_watching:
                reply += (f"⏳ 其中 {skipped_watching} 个正在观察期（刚同步成功或已请求"
                          f"补生成），交给观察窗口自行判定，不重复计入疑似。\n")
            unexplained = data.get("found", 0) - data.get("added", 0) \
                - skipped_ignored - skipped_watching
            if unexplained > 0:
                # 已挂在疑似清单里的条目不算「新增」——它们本来就在，扫描只是
                # 又看见了它们一次。这条兜底能挡住将来新增跳过分支时的静默漏报。
                reply += (f"ℹ️ 另有 {unexplained} 个已在疑似清单中（本次未重复计入新增）。\n")
            if data.get("truncated"):
                reply += (f"⚠️ 已达到单次上限 {STRM_SCAN_LIMIT} 个，结果被截断。\n"
                          f"   数量这么大通常说明 strm 插件本身没在工作，"
                          f"请先确认它的开关与媒体识别是否正常。\n")
            reply += (
                f"--------------------------------\n"
                f"💡 缺 strm 有两种可能，处理方式不同：\n"
                f"• 从未上传过的存量文件 → 用 /rsync_backfill 补传\n"
                f"• 上传了但 CD2 假成功（云端可能有 ..xxx 残留）→ 先试 /rsync_strm gen 补生成，\n"
                f"  仍无 strm 再用看板「删旧重传」\n"
                f"💡 疑似清单已在看板「strm 疑似异常」标签内，可勾选批量处理。"
            )
            self._post_reply(event, reply)

        elif action == "backfill_clear":
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中，请稍后再试。")
                return
            self._backfill_queue = []
            self._backfill_total = 0
            self.save_data("backfill_queue", [])
            self.save_data("backfill_total", 0)
            self._post_reply(event, "✅ 已清空存量补传队列。")

        elif action == "status":
            st = self._last_status
            state = "正在同步 ⏳" if self._is_running else ("同步完成 ✅" if st.get("success") else "有文件缺失/异常 ⚠️")
            now_ts = time.time()
            threshold = self._delay_hours * 3600
            ready_count, cooling_count, stale_count = self._count_queue(now_ts, threshold)

            reply = (
                f"📊 115网盘同步状态报告\n"
                f"当前状态: {state}\n"
                f"冷却就绪可同步: {ready_count} 个\n"
                f"冷却缓冲中: {cooling_count} 个 (设定: {self._delay_hours}h)\n"
                f"彻底缺失文件: {len(st.get('missing_files', []))} 个\n"
                f"残缺不全文件: {len(st.get('corrupt_files', []))} 个\n"
            )
            if stale_count:
                reply += (f"🗑️ 源端已删除待清理: {stale_count} 个"
                          f"（文件已不在本地，将在下轮同步时移出队列，不计入上方计数）\n")
            # 冷却明细：光给一个计数，用户没法"提前上传"那个他刚弄好的文件 ——
            # 而这正是 `⚡ 立即同步` 要解决的场景。列表带关键字（不是序号：
            # 冷却队列没有稳定序号，见 `_resolve_pending_target`），
            # 用户从通知/文件名里直接抄一段就能用。
            cooling_items = self._pending_queue_entries(now_ts, threshold)
            if cooling_items:
                shown = cooling_items[:_STRM_CMD_LIST_LIMIT]
                reply += "--------------------------------\n🧊 冷却中（可不等冷却、立即上传）：\n"
                for item in shown:
                    reply += f"• {item['key']}（还需 {item['remaining_min']} 分钟）\n"
                if len(cooling_items) > len(shown):
                    reply += f"… 其余 {len(cooling_items) - len(shown)} 个未列出\n"
                reply += (f"⚡ 提前上传：/rsync_sync <上面某一行的片段>\n"
                          f"   例：/rsync_sync {self._example_cmd_target(shown, cooling_items)}\n"
                          f"   （冷却的现职是等文件写完 / 等外挂字幕到齐；确认它已安顿好再用。）\n")
            # 源端扫描（主通道）健康度：游标落后 = 新文件不会被发现。
            # 这与「队列里有多少」是两件事，必须分别报告 —— 队列空可能是
            # 「没有新文件」，也可能是「扫描根本没在跑」，用户没法从计数区分。
            if self._source_scan_enabled:
                if self._source_scan_last:
                    ago_mins = int((now_ts - self._source_scan_last) / 60)
                    reply += (f"🔍 源端扫描: {len(self._source_cursor)} 个映射，"
                              f"最近推进 {ago_mins} 分钟前（cron {self._source_scan_cron}）\n")
                else:
                    reply += "🔍 源端扫描: 已启用，尚未完成首轮\n"
            else:
                reply += "🔍 源端扫描: ⚠️ 已关闭 —— 入库只能靠 Webhook 通知发现\n"
            # ⚠️ 这里曾有一行「因扩展名被跳过（累计）」的统计 —— 用户要求移除
            # 看板提示时，连同 `_ingest_skip_stat` 属性与它的写入逻辑一起删了，
            # **但漏了这个读取点**，于是 `/rsync_status` 直接抛 AttributeError：
            #
            #     'Rsync115Sync' object has no attribute '_ingest_skip_stat'
            #
            # 这是「删数据源时漏查消费方」的典型形态：属性、写入、看板三处都改了，
            # 而读取处散在另一个文件里。**删任何状态前先 grep 全仓**。
            # （日志里那条 info 仍在：每个扩展名首次被挡下时会打一条，
            #   要排查"某类文件全被丢弃"看日志即可。）
            if len(st.get('missing_files', [])) + len(st.get('corrupt_files', [])) > 0:
                reply += "💡 发送 /rsync_retry 即可立即定向补传异常文件！\n"
            reply += "💡 支持发送 /rsync_search <剧名/电影名> 查找并确认重传指定媒体。"
            if self._ignored_rules:
                reply += f"\n🚫 已忽略规则: {len(self._ignored_rules)} 条 (/rsync_ignore list 查看)"
            self._post_reply(event, reply)

        elif action == "ignore":
            operator = str(data.get("user") or "")
            arg_lower = text_arg.lower()

            # 查看忽略清单
            if arg_lower in ("list", "ls", "列表", ""):
                if not self._ignored_rules:
                    self._post_reply(event, "📋 当前没有任何忽略规则。\n发送 /rsync_ignore <剧名> 即可忽略指定媒体的报警。")
                    return
                lines = [
                    f"{i+1}. [{r.get('match', 'contains')}] {r.get('rule')}  (加入于 {r.get('created_at', '-')})"
                    for i, r in enumerate(self._ignored_rules)
                ]
                reply = (
                    f"📋 当前共 {len(self._ignored_rules)} 条忽略规则：\n"
                    f"--------------------------------\n"
                    + "\n".join(lines) +
                    f"\n--------------------------------\n"
                    f"• 移除指定规则: /rsync_ignore remove 1\n"
                    f"• 清空全部规则: /rsync_ignore clear"
                )
                self._post_reply(event, reply)
                return

            # 清空忽略清单
            if arg_lower in ("clear", "清空", "reset"):
                count = len(self._ignored_rules)
                self._ignored_rules = []
                self.save_data("ignored_files", self._ignored_rules)
                self._post_reply(event, f"✅ 已清空全部 {count} 条忽略规则，相关文件将重新纳入对账。")
                return

            # 移除指定规则
            if arg_lower.startswith("remove") or arg_lower.startswith("del"):
                parts = text_arg.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    idx = int(parts[1]) - 1
                    if 0 <= idx < len(self._ignored_rules):
                        removed = self._ignored_rules.pop(idx)
                        self.save_data("ignored_files", self._ignored_rules)
                        self._post_reply(event, f"✅ 已移除忽略规则：{removed.get('rule')}")
                    else:
                        self._post_reply(event, f"⚠️ 序号超出范围，当前共 {len(self._ignored_rules)} 条规则。")
                else:
                    self._post_reply(event, "⚠️ 用法：/rsync_ignore remove 1")
                return

            # 若输入为纯数字：必须配合搜索结果才按序号精确忽略
            if text_arg.isdigit():
                if not self._waiting_confirm_retries:
                    self._post_reply(
                        event,
                        "⚠️ 纯数字需要在搜索结果上下文中使用。\n"
                        "请先发送 /rsync_search <剧名> 获取列表，再发送 /rsync_ignore 序号。\n"
                        "若想按关键字忽略，请使用剧名而非数字（避免误伤含数字的其它文件）。"
                    )
                    return
                idx = int(text_arg) - 1
                if 0 <= idx < len(self._waiting_confirm_retries):
                    target_key = self._waiting_confirm_retries[idx]
                    ok = self._add_ignore_rule(target_key, match="exact", created_by=operator, source="chat")
                    self._post_reply(
                        event,
                        f"✅ 已忽略：{target_key}" if ok else "⚠️ 该规则已存在。"
                    )
                    return
                self._post_reply(event, f"⚠️ 序号超出范围（1~{len(self._waiting_confirm_retries)}）。")
                return

            # 安全护栏：过短的包含规则极易误伤，要求至少 2 个字符
            if len(text_arg) < 2:
                self._post_reply(event, "⚠️ 忽略关键字过短，请至少输入 2 个字符，以免误伤其它文件。")
                return

            # 关键字忽略（子串包含）
            ok = self._add_ignore_rule(text_arg, match="contains", created_by=operator, source="chat")
            # 若已有搜索结果，提示可精确忽略
            hint = ""
            if self._waiting_confirm_retries:
                hint = f"\n💡 也可用序号精确忽略: /rsync_ignore 1 (对应上一条搜索结果)"
            if ok:
                self._post_reply(
                    event,
                    f"✅ 已加入忽略清单（包含匹配）：\n• {text_arg}\n"
                    f"后续该范围文件不再计入缺失、不再触发重试提醒。{hint}"
                )
            else:
                self._post_reply(event, f"⚠️ 规则「{text_arg}」已存在，无需重复添加。")

    @staticmethod
    def _plugin_mtype():
        """
        返回插件通知使用的消息类型。

        使用「插件」场景：宿主据此读取系统「通知场景开关」里配置的受众范围，
        默认 admin，即只发给各渠道管理员，而不再广播给全部用户。
        """
        if _message_type_cls() is None:
            return None
        for attr in ("Plugin", "Other"):
            mtype = getattr(_message_type_cls(), attr, None)
            if mtype is not None:
                return mtype
        return None

    def _post_reply(self, event: Optional[Event], text: str):
        """
        回复用户主动发起的命令。

        必须使用 userid 参数指定接收者：post_message 的形参名为 userid，
        若误传 user，该字段会被 Message 模型丢弃，导致 userid 为空，
        消息降级为“广播给所有渠道”，每个用户都会收到本条回复。
        """
        if not event:
            return
        try:
            data = event.event_data or {}
            self.post_message(
                channel=data.get("channel"),
                userid=data.get("user"),
                title="115网盘同步助手",
                text=text,
            )
        except Exception as e:
            logger.warning(f"[Rsync115Sync] 命令回复发送失败: {e}")

