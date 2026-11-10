"""
远程命令 /rsync_*：命令表、分发入口与回复通道（阶段 2 拆分）。

Remote /rsync_* commands: command table, dispatch entry, and the reply channel.

与 strm_ops.py / sync_ops.py 同一套约束（见其模块头注释）：Mixin 只搬**代码**，
self.* 状态全部留在插件实例上，本类不持有任何状态。

## 命令面按「用户想做什么」收敛为 7 条（v0.8.0）

用户原话：「命令几乎没用过，太多太复杂，不清楚文件状态，不清楚指令功能，
导致不知道应该用哪个」。旧表有 11 条，其中 `/rsync_search` + `/rsync_confirm`
是一条依赖内存状态的两步流程，`/rsync_force` 与 `/rsync_sync` 是两个入口做
同一类事。现在每一条命令对应**一个状态迁移**：

    status / sync / retry / ignore / backfill / strm / help

破坏性动作（删旧重传）仍然要求显式目标：`/rsync_retry <关键字>` 只预览，
只有 `<关键字> all` 或 `<关键字> <序号>` 才执行。命令侧**不再保存搜索上下文**
（旧 `_waiting_confirm_retries`），所以每条命令都可以单独发送、顺序无关。
"""
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from app.core.event import Event, EventType, eventmanager
from app.sdk.logging import logger

from .constants import (
    STRM_SCAN_LIMIT,
    STRM_CMD_LIST_LIMIT as _STRM_CMD_LIST_LIMIT,
    RETRY_KEYWORD_LIMIT as _RETRY_KEYWORD_LIMIT,
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
        """
        命令表：7 条，每条对应一个状态迁移。

        The command surface: one command per state transition.

        ⚠️ 表与 `_help_text` 必须同步（`test_help_lists_every_registered_command`）。
        删除命令时连同它的 `action` 分支一起删 —— 只从表里摘掉、分发里留着，
        用户仍可用旧消息里的按钮/别名触发一条"已经没有入口"的路径。
        """
        return [
            {
                "cmd": "/rsync_status",
                "event": EventType.PluginAction,
                "desc": "查看当前115同步进度与冷却/待重试队列",
                "category": "工具",
                "data": {"action": "status"}
            },
            {
                "cmd": "/rsync_sync",
                "event": EventType.PluginAction,
                "desc": "同步已达冷却时间的媒体；带文件名则立即定向同步；--all 全量只读对账（重操作，7 天冷却）",
                "category": "工具",
                "data": {"action": "sync"}
            },
            {
                "cmd": "/rsync_retry",
                "event": EventType.PluginAction,
                "desc": "重试失败/缺失的 115 文件；带关键字只预览匹配清单，加 all 或序号才执行删旧重传（破坏性）",
                "category": "工具",
                "data": {"action": "retry"}
            },
            {
                "cmd": "/rsync_ignore",
                "event": EventType.PluginAction,
                "desc": "忽略指定文件不再报警（例: /rsync_ignore 剧名；list / remove <序号> / clear）",
                "category": "工具",
                "data": {"action": "ignore"}
            },
            {
                "cmd": "/rsync_backfill",
                "event": EventType.PluginAction,
                "desc": "补传存量媒体（含同名字幕），受限流分批推进；带 clear 清空补传队列",
                "category": "工具",
                "data": {"action": "backfill"}
            },
            {
                "cmd": "/rsync_strm",
                "event": EventType.PluginAction,
                "desc": "strm 相关操作（无参=扫描缺 strm / <文件名> 只查该文件 / list 列疑似清单 / check 立即检查观察期 / gen 请助手补生成 / clear 清空）",
                "category": "工具",
                "data": {"action": "strm"}
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

        The command reference, grouped by **what the user wants to do** rather
        than by the order of `action` branches — on a phone the question is
        "which one do I need now", not "what does the code call this".

        ⚠️ 维护要求：**新增/修改命令时必须同步改这里**。它列的是用户唯一的
        自述入口，写错等于教用户用不存在的功能（本仓已有过「说明停留在旧版本」
        的实例：`/rsync_force` 的注册说明写着"忽略冷却限制"，而 v0.2.1 起冷却
        照常生效 —— 用户照着用会以为能强制上传，实际不会）。`/rsync_force`
        已在 v0.8.0 并入 `/rsync_sync --all`，本文件不得再出现旧名字。

        Keep in sync with get_command(); a stale reference teaches users to call
        things that do not exist.
        """
        # ⚠️ 每条命令**一行**：`test_help_lists_every_registered_command` 要求
        # 覆盖 get_command() 的全部命令。`**` 一律不用：宿主 standardize() 会把
        # 纯文本里的 Markdown 标记转义，Telegram 上显示成字面星号。
        # 需要强调时用【】。
        return (
            f"📖 115 网盘同步助手 · 指令一览（按你想做的事）\n"
            f"【先看情况】\n"
            f"/rsync_status —— 状态报告：冷却队列、异常清单、扫描健康度\n"
            f"/rsync_help —— 这条帮助\n"
            f"\n"
            f"【让文件传上去】\n"
            f"/rsync_sync —— 同步已达冷却时间的媒体（冷却时长见配置页）\n"
            f"/rsync_sync <文件名> —— 不等冷却，立即上传这一个\n"
            f"/rsync_sync --all —— 全量只读对账，只重传不一致的文件（重操作，7 天冷却）\n"
            f"/rsync_backfill —— 补传存量媒体（源端有、从未处理过的）\n"
            f"/rsync_backfill clear —— 清空补传队列\n"
            f"\n"
            f"【文件没传上去】\n"
            f"/rsync_retry —— 重试失败清单里的文件\n"
            f"/rsync_retry <关键字> —— 只查看匹配清单，不执行任何改动\n"
            f"/rsync_retry <关键字> all —— 重传全部匹配（最多 15 个）\n"
            f"/rsync_retry <关键字> <序号> —— 只重传清单里的那一个\n"
            f"⚠️ 【只有写 all 或序号才会执行】重传会先删云端旧文件再上传。\n"
            f"\n"
            f"【strm 有问题】\n"
            f"/rsync_strm —— 全量扫描缺 strm 的文件\n"
            f"/rsync_strm <文件名> —— 只查这一个（不遍历整库，秒回）\n"
            f"/rsync_strm list —— 列出疑似清单\n"
            f"/rsync_strm check —— 立即检查观察期（不等下一轮巡检）\n"
            f"/rsync_strm gen —— 请助手补生成 strm（多数问题的第一步）\n"
            f"/rsync_strm clear —— 清空疑似与待观察清单\n"
            f"\n"
            f"【老是误报】\n"
            f"/rsync_ignore <剧名> —— 不再为它报警（至少 2 个字符）\n"
            f"/rsync_ignore list —— 查看全部规则\n"
            f"/rsync_ignore remove <序号> —— 移除清单里的某条规则\n"
            f"/rsync_ignore clear —— 清空全部\n"
            f"\n"
            f"💡 看板「配置 → 插件页面」有同样的功能，且能看到文件清单。\n"
            f"💡 疑似清单的处理顺序：先 gen，仍无 strm 再到看板删旧重传或忽略。"
        )

    # ---- 疑似清单的命令侧处理 / suspect handling over chat ---------------

    def _strm_suspect_list_text(self) -> str:
        """
        用**带序号的列表**回报疑似清单（`/rsync_strm list`）。

        Render the suspect list with stable indices.

        ⚠️ 序号必须基于**确定顺序**：`Store.by_status` 按 `updated_at` 排序，
        因此同一个时刻生成的列表在同一条消息里可复现。序号还会**截断显示**
        （清单可能有上百条），但截断只影响显示 —— 完整清单在看板
        「strm 疑似异常」标签内。
        Indices come from a deterministic ordering; truncation is display-only.

        ⚠️ v0.8.0 起删除了 `/rsync_strm retry` / `ignore` 两个子命令：删除性
        动作只在看板与通知按钮里提供（看板要勾选确认，按钮走同一套 API）。
        清单本身仍是只读入口，因此这里只给「去哪里处理」，不教用户敲已删除的命令。
        """
        keys = list(self._strm_suspects.keys())
        if not keys:
            return "✅ 当前没有 strm 疑似异常。\n💡 /rsync_strm 可全量扫描一次。"

        # 上限从 `_STRM_CMD_LIST_LIMIT` 收到 10：带序号的清单在手机上一条占
        # 两三行，30 条就接近宿主 4096 字符的拆分边界，拆开后的续条会丢掉
        # 尾部的操作提示。少列几条、让用户用关键字指定，比列表被截半好。
        shown = keys[:min(_STRM_CMD_LIST_LIMIT, 10)]
        lines = [f"{i+1}. {k}" for i, k in enumerate(shown)]
        reply = f"📺 strm 疑似异常（共 {len(keys)} 个）：\n" + "\n".join(lines)
        if len(keys) > len(shown):
            reply += (f"\n… 其余 {len(keys) - len(shown)} 个未列出"
                      f"（完整清单见看板「strm 疑似异常」标签）")
        # 保留 gen（安全、多数够用）与看板处理入口。破坏性动作的警告仍然保留：
        # 看板上的「删旧重传」会真的删云端文件，用户不能被清单文案引到没有
        # 二次确认的路径上。
        reply += (
            f"\n\n/rsync_strm gen —— 先试补生成（多数够用）\n"
            f"💡 删旧重传 / 忽略请到看板「strm 疑似异常」内勾选，或点通知里的按钮。\n"
            f"⚠️ 删旧重传会先删云端旧文件再重传，请先确认。"
        )
        return reply

    @staticmethod
    def _parse_retry_target(text: str) -> Tuple[str, Optional[Any]]:
        """
        把 `/rsync_retry` 的参数拆成 `(关键字, 选择)`。

        Split `/rsync_retry` arguments into `(keyword, selection)`.

        `selection` 的三种取值：
          - `None`：只预览，不执行（**默认**，安全侧）；
          - `"all"` / `"全部"`：重传全部匹配；
          - `int`：按预览清单的 1 起序号只传那一个。

        ⚠️ 只有**末尾独立的一段**才会被当作选择项：关键字本身可能以数字结尾
        （人名、集数），所以 `/rsync_retry E01` 是「搜 E01」，而
        `/rsync_retry E01 2` 才是「搜 E01 并只传第 2 个」。
        Only a standalone trailing token is a selection; the keyword may itself
        end in digits.
        """
        raw = (text or "").strip()
        parts = raw.rsplit(None, 1)
        if len(parts) == 2:
            keyword, tail = parts[0].strip(), parts[1].strip()
            if keyword:
                if tail.lower() in ("all", "全部"):
                    return keyword, "all"
                if tail.isdigit():
                    return keyword, int(tail)
        return raw, None

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

        「疑似清单」有 `/rsync_strm list` 给出稳定序号，但那条路径的动作已经
        收敛到看板/通知按钮上。冷却队列**没有**这样一个入口，因此给序号等于让
        用户盲猜 —— 而这条路的后果是**立刻把那个文件传上去**（绕过冷却）。
        猜错的对象会被提前上传，虽不如删错文件严重，但同样不可预期。

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
        把用户的指定（关键字或完整 key）解析成疑似清单里的 key 列表。

        Resolve a keyword (or full key) to suspect keys.

        返回 `(keys, 错误说明)`；成功时错误说明为空串。

        ⚠️ v0.8.0 起**不再接受纯数字序号**：命令侧没有「retry <序号>」入口了
        （看板/通知按钮直接携带指纹或完整 key）。保留数字解析只会让一个已经
        没有入口的参数形式看起来仍然可用，反而在清单重排后指向另一个文件。

        ⚠️ 关键字匹配**多个时不猜**：返回候选清单让用户把范围缩小。
        猜一个最像的，在删旧重传这条路上就是误删好文件。
        Never guess among multiple keyword matches on a destructive path.
        """
        text = (text or "").strip()
        if not text:
            return [], "未指定目标。"

        keys = list(self._strm_suspects.keys())
        if not keys:
            return [], "当前没有 strm 疑似异常。"

        # 关键字：**只搜疑似清单**（不遍历源端）——
        # 这个入口的语义是"处理清单里这一条"，不是通用查找器。
        kw = text.lower()
        matched = [k for k in keys if kw in k.lower()]
        if not matched:
            return [], (f"疑似清单里没有匹配「{text}」的条目。"
                        f"\n用 /rsync_strm list 查看全部，或在看板「strm 疑似异常」内处理。")
        if len(matched) > 1:
            shown = "\n".join(f"• {k}" for k in matched[:_STRM_CMD_LIST_LIMIT])
            return [], (f"「{text}」匹配到 {len(matched)} 条，请把关键字写得更具体：\n{shown}")
        return matched, ""

    def _strm_suspect_action(self, event, arg: str, action: str) -> str:
        """
        对疑似清单里的**一个**目标执行 retry 或 ignore，返回给用户的话。

        Run retry/ignore on one resolved target and return the reply text.

        这是**通知按钮**的实现（`retry` / `ignore` 两个回调）。v0.8.0 起聊天侧
        不再提供 `/rsync_strm retry|ignore`，但按钮仍走这里 ——
        `handle_button_action` 用指纹反查完整 key，再交给同一套实现。

        复用看板的 `_api_strm_retry` / `_api_strm_ignore` —— 那两条路径里各有
        越权护栏（只接受疑似清单内的 key）与副作用（补生成标记失效、通知闩锁
        重置），**在命令侧重写一遍必然漂移**。这里只做"目标 → key"的解析，
        把结果原样交给同一个实现。
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

    # ================= 交互命令分发 (状态迁移 → 单一入口) =================

    def _handle_button_action(self, event: Event) -> None:
        """
        处理通知里按钮的点击（**实现**，注册见 `__init__.py`）。

        Handle an inline-keyboard click from a notification.

        ## 事件形状

        宿主把 `[PLUGIN]Rsync115Sync|<内容>` 解析成 `(plugin_id, content)` 后广播：

            {"plugin_id": "Rsync115Sync", "text": "<内容>", "userid": ..., ...}

        ## ⚠️ 两道守卫都是必须的

        1. **插件 ID 守卫**：`MessageAction` 是定向事件，但形状上仍是广播 ——
           不判 `plugin_id` 就会把别的插件的按钮回调也解析一遍（可能误动本插件
           的数据）。库内 `p115strmhelper` 同样做法。
        2. **内容必须以已知动作开头**：解析不出动作就**静默返回**，不回消息
           —— 否则用户点到别处（或旧消息里的按钮）会收到莫名其妙的回复。

        ⚠️ 与命令路径同一条复用原则：这里只做"动作+目标 → 已有入口"的映射，
        真正的实现全部转调既有方法，不在本函数里重写一遍。
        """
        data = getattr(event, "event_data", None) or {}
        own = self.__class__.__name__.lower() if hasattr(self, "__class__") else ""
        plugin_id = str(data.get("plugin_id") or "").strip()
        target_id = str(data.get("__mp_target_plugin_id") or "").strip()
        if plugin_id and plugin_id.lower() != own:
            return
        if target_id and target_id.lower() != own:
            return

        raw = str(data.get("text") or "").strip()
        if not raw:
            return
        action, _, target = raw.partition(" ")
        action = action.strip().lower()
        target = target.strip()

        # 按钮回调没有 `channel_event` 那套上下文，但回复需要渠道与用户：
        # 把 MessageAction 的字段转成 `_post_reply` 认识的形状（它读 channel/user）。
        reply_ctx = Event(
            EventType.PluginAction,
            {"channel": data.get("channel"), "source": data.get("source"),
             "user": data.get("userid") or data.get("user")},
        )

        if action == "gen":
            # 整批补生成：与 /rsync_strm gen 同一条入口
            res = self._api_strm_generate({"keys": list(self._strm_suspects.keys())})
            self._post_reply(reply_ctx, ("📺 " if res.get("success") else "⚠️ ")
                             + res.get("message", "操作失败"))
            return
        if action == "check":
            res = self._api_strm_check({"keys": list(self._strm_watch.keys())})
            self._post_reply(reply_ctx, ("📺 " if res.get("success") else "⚠️ ")
                             + res.get("message", "检查失败"))
            return
        if action == "retry_all":
            # 全部删旧重传：对当前所有疑似异常条目执行删旧重传
            keys = list(self._strm_suspects.keys())
            if not keys:
                self._post_reply(reply_ctx, "⚠️ 当前没有待处理的 strm 疑似异常。")
                return
            res = self._api_strm_retry({"keys": keys}, channel_event=reply_ctx)
            if res.get("success"):
                self._post_reply(
                    reply_ctx,
                    f"🔁 {res.get('message', '已启动删旧重传')}\n\n"
                    f"已提交全部 {len(keys)} 个疑似异常文件进行删旧重传。"
                )
            else:
                self._post_reply(
                    reply_ctx,
                    f"⚠️ {res.get('message', '操作失败')}"
                )
            return
        if action in ("retry", "ignore") and target:
            # ⚠️ 按钮携带的是**指纹**不是关键字（Telegram 对 callback_data 有
            # 64 字节上限，中文关键字必然超限 → 整条消息发不出去）。
            # 这里把指纹反查回完整 key，再交给与命令侧**同一个**实现
            # （含越权护栏），不在按钮路径重写一遍。
            from .strm import fingerprint as _fp
            keys = [k for k in self._strm_suspects if _fp(k) == target]
            if len(keys) != 1:
                # 清单已变（条目被处理掉、或指纹撞车）→ **明确拒绝，绝不猜**。
                # 这是删除性操作，猜错就是删错文件。
                self._post_reply(reply_ctx,
                                 f"⚠️ 该条目已不在疑似异常清单中（可能已被处理）。\n"
                                 f"用 /rsync_strm list 查看当前清单。")
                return
            self._post_reply(reply_ctx, self._strm_suspect_action(
                reply_ctx, keys[0], "retry" if action == "retry" else "ignore"))
            return
        logger.debug(f"[Rsync115Sync] 未识别的按钮回调，已忽略: {raw!r}")

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

        if action == "sync":
            # 三种状态迁移，同一个入口：
            #   无参        → 同步已达冷却时间的文件
            #   <文件名>    → 不等冷却、立即定向同步该文件（看板「立即同步」的命令版）
            #   --all       → 全量只读对账（原 /rsync_force）
            #
            # 为什么带文件名这条路需要存在：冷却期的现职是「等文件写完 / 等外挂字幕
            # 到齐」，但用户常常**知道**那个文件已经安顿好了（刚跑完刮削、字幕已下齐），
            # 此时干等 4 小时毫无道理。
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中。")
                return
            if not text_arg:
                self._start_sync_thread(mode="ready", channel_event=event)
                return

            if text_arg.lower() == "--all":
                # ⚠️ 原 `/rsync_force` 的全部约束原样保留：7 天冷却闸、全量只读
                # 对账语义、共享限流配额。`_mark_force_done` 由执行成功后的
                # `_execute_sync` 调用，这里只负责判闸。
                allowed, reason = self._force_cooldown_allows()
                if not allowed:
                    self._post_reply(
                        event,
                        f"⛔ 已跳过全量对账：{reason}\n"
                        f"--all 会对源/目标做只读全量对账（逐文件 stat，开销大），"
                        f"并共享限流配额；这是一项重操作，默认 7 天冷却。\n"
                        f"如需补传存量媒体，请改用 /rsync_backfill（只扫源端、按配额分批）。"
                    )
                    return
                self._start_sync_thread(mode="force", channel_event=event)
                return

            target, err = self._resolve_pending_target(text_arg)
            if err:
                self._post_reply(event, err)
                return
            res = self._api_sync_item({"keys": [target]})
            head = "🚀 " if res.get("success") else "⚠️ "
            self._post_reply(event, f"{head}{res.get('message', '操作失败')}\n\n目标：{target}")

        elif action == "retry":
            # 无参 → 重试失败清单（既有语义）。
            # 带关键字 → **无状态两步**：先只回匹配清单，用户再显式选择执行。
            # 这是 v0.8.0 替换 `/rsync_search` + `/rsync_confirm` 的形态：
            # 旧流程把搜索结果存在内存里，命令顺序一旦错开（重载、换设备、
            # 中间插了别的查询）就会对错对象执行；现在每次都用同一条查询重新
            # 算清单，序号只在这一条消息的上下文中有效。
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中。")
                return
            if not text_arg:
                self._start_sync_thread(mode="retry", channel_event=event)
                return

            if text_arg.lower() in ("all", "全部"):
                self._post_reply(
                    event,
                    "⚠️ all 需要配合关键字，例如：/rsync_retry 繁花 all\n"
                    "如果只想重试失败清单，直接发送 /rsync_retry（不带参数）。"
                )
                return

            keyword, selection = self._parse_retry_target(text_arg)
            result = self._search_target_files(keyword)
            if not result["matched"]:
                self._post_reply(event,
                                 f"🔍 未在源目录中找到包含「{keyword}」的文件，未做任何改动。")
                return
            if result.get("truncated") or len(result["matched"]) > _RETRY_KEYWORD_LIMIT:
                # ⚠️ 多命中不猜：超限**整批拒绝**，不做「先传前 15 个」——
                # 那会让用户以为整批都处理了，而剩下的永远没人管。
                self._post_reply(
                    event,
                    f"⚠️ 关键字「{keyword}」匹配到 {result['total']} 个文件，超过单次上限 "
                    f"{_RETRY_KEYWORD_LIMIT} 个。\n请用更精确的文件名缩小范围，本次未做任何改动。"
                )
                return

            # ⚠️ 先排序再编号：序号要能在下一次调用（重新查询）时指向同一个文件。
            # `os.walk` 的目录序不保证跨调用稳定，直接按原顺序编号会让用户
            # 「照着上一条消息的 2 号」删掉另一个文件。
            matched = sorted(result["matched"])

            if selection is None:
                lines = "\n".join(f"{i+1}. {key}" for i, key in enumerate(matched))
                self._post_reply(
                    event,
                    f"🔍 关键字「{keyword}」匹配到 {len(matched)} 个文件：\n"
                    f"{lines}\n\n"
                    f"下一步（照抄后改参数）：\n"
                    f"/rsync_retry {keyword} all —— 全部重传\n"
                    f"/rsync_retry {keyword} <序号> —— 只传清单里的那一个\n"
                    f"⚠️ 【只有写 all 或序号才会执行】重传会先删云端旧文件再上传。"
                )
                return

            if selection == "all":
                targets = matched
                origin = "关键字全部重传"
            else:
                if not 1 <= selection <= len(matched):
                    self._post_reply(
                        event,
                        f"⚠️ 序号 {selection} 超出范围（当前 1~{len(matched)}）。\n"
                        f"请重新发送 /rsync_retry {keyword} 查看最新清单。"
                    )
                    return
                targets = [matched[selection - 1]]
                origin = "关键字定向重传"

            # ⚠️ 删旧重传的**唯一实现**在 `_retransfer_keys`
            # （预检、删除、失败处置全在那里）。命令侧只负责选目标，
            # 不直接调用底层的删除函数 —— 两份实现必然分叉。
            res = self._retransfer_keys(targets, channel_event=event, origin=origin)
            head = "🧹 " if res.get("success") else "⚠️ "
            self._post_reply(event, f"{head}{res.get('message', '操作失败')}")

        elif action == "backfill":
            # `clear` 子命令合并了原 `/rsync_backfill_clear`；其余参数一律按
            # 「建立补传队列」处理（无参行为与 v0.7.0 一致）。
            arg_lower = (text_arg or "").strip().lower()
            if arg_lower in ("clear", "清空", "reset"):
                if self._is_running:
                    self._post_reply(event, "⚠️ 当前同步任务正在运行中，请稍后再试。")
                    return
                self._backfill_queue = []
                self._backfill_total = 0
                self.save_data("backfill_queue", [])
                self.save_data("backfill_total", 0)
                self._post_reply(event, "✅ 已清空存量补传队列。")
                return

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
            # v0.8.0 的子命令面：
            #   无参          → 全量主动扫描
            #   <关键字>      → 只查指定文件（不遍历整库）
            #   list          → 列出疑似清单
            #   check         → 立即检查观察期
            #   gen           → 请助手补生成
            #   clear         → 清空两个清单
            #
            # `retry` / `ignore` / `prune` 已删除：看板「strm 疑似异常」标签
            # 有对应按钮（删旧重传 / 忽略 / 清理），通知里也有按钮。命令侧再留
            # 一套会形成第二条需要维护的入口，而它们的破坏性动作必须靠
            # 「显式目标」兜底 —— 用户反而更难判断该用哪个。
            arg_lower = (text_arg or "").lower()

            # ⚠️ `list` 与 `clear` 只操作已有清单，不扫描源端、也不需要 strm 目录。
            # 它们必须排在下面那道「必须配置了 strm 目录才能扫描」的守卫**之前**。
            # 这个顺序曾经写反：没配 strm_dir 的实例上 list 被挡下，提示还是
            # "无法扫描"这种与操作无关的话。清单可能是迁移进来的历史数据，
            # 压根不需要扫描；清空同理（看板没有清空入口，命令是唯一途径）。
            if arg_lower in ("list", "ls", "列表", "清单"):
                self._post_reply(event, self._strm_suspect_list_text())
                return
            if arg_lower in ("clear", "清空", "reset"):
                result = self._api_strm_clear()
                self._post_reply(event, "🧹 " + result["message"])
                return

            # 两种扫描模式并存的原因：全量扫描是「我不知道哪些文件有问题」的
            # 答案；但当用户**已经明确知道**是哪个文件时（例如在 115 云端看到
            # 残留），遍历整库纯属浪费 —— 关键字模式直接定位那一个，秒回。

            # ⚠️ 这道守卫只针对**下面这些会读 strm 目录的操作**（无参全量扫描 /
            # 关键字查询 / check / gen）。`list` / `clear` 已在上面提前返回。
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
                # 与疑似清单同一理由：明细只列 10 条，避免逼近宿主 4096 拆分边界。
                shown = cooling_items[:min(_STRM_CMD_LIST_LIMIT, 10)]
                reply += "\n🧊 冷却中（可不等冷却、立即上传）：\n"
                for item in shown:
                    reply += f"• {item['key']}（还需 {item['remaining_min']} 分钟）\n"
                if len(cooling_items) > len(shown):
                    reply += f"… 其余 {len(cooling_items) - len(shown)} 个未列出\n"
                reply += (f"⚡ 提前上传：/rsync_sync <上面某一行的片段>\n"
                          f"   例：/rsync_sync {self._example_cmd_target(shown, cooling_items)}\n")
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
            # 补传进度 + 限流窗口（v0.8.5，TODO 10）：此前 /rsync_status 只有
            # 冷却队列与异常清单，用户在聊天侧看不到「补传还剩多少、限流还差
            # 几个窗口」—— 只能开看板。信息本身早已在实例状态里，补展示即可。
            if getattr(self, "_backfill_queue", None):
                total = int(getattr(self, "_backfill_total", 0) or 0)
                remaining = len(self._backfill_queue)
                done_n = max(0, total - remaining)
                # ⚠️ 全部 getattr 兜底：__new__ 构造的实例（单测）没有这些属性，
                # 直接取会 AttributeError —— 本仓已三次踩此坑（见 __init__.py
                # _api_get_status 里同款注释），新增读取点默认按「可能缺属性」写。
                rate_on = bool(getattr(self, "_rate_limit_enabled", True))
                per_window = int(getattr(self, "_upload_max_per_window", 0) or 0)
                if rate_on and per_window:
                    wins = -(-remaining // per_window)
                    win_note = f"，按当前配额还需约 {wins} 个窗口（每窗口 {per_window} 个）"
                else:
                    win_note = ""
                reply += (f"📦 存量补传: 已完成 {done_n} / {total}，"
                          f"剩余 {remaining} 个{win_note}\n")
            if getattr(self, "_rate_limit_enabled", True):
                used = int(getattr(self, "_upload_window_count", 0) or 0)
                cap = int(getattr(self, "_upload_max_per_window", 0) or 0)
                blocked = float(getattr(self, "_upload_blocked_until", 0.0) or 0.0)
                if blocked > now_ts:
                    mins = int((blocked - now_ts) / 60) + 1
                    reply += (f"🚦 限流: 🚫 风控退避中，约 {mins} 分钟后恢复"
                              f"（历史累计 {int(getattr(self, '_backoff_count', 0) or 0)} 次）\n")
                elif used:
                    secs = int(getattr(self, "_upload_window_secs", 1800) or 1800)
                    start = float(getattr(self, "_upload_window_start", 0.0) or 0.0)
                    left = max(1, int((secs - (now_ts - start)) / 60) + 1) if start else 0
                    reset_note = f"，约 {left} 分钟后重置" if left else ""
                    reply += (f"🚦 限流: 本窗口已用 {used} / {cap} 个{reset_note}\n")
                else:
                    reply += f"🚦 限流: 已启用（每窗口 {cap} 个），本窗口尚未使用\n"
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
            reply += "💡 支持发送 /rsync_retry <剧名/电影名> 查看匹配文件，再加 all 或序号重传。"
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
                # v0.7.0 起忽略只有一份真相源（`_ignored_rules` 规则）——
                # 台账里不再有 status='ignored' 的行，清空规则即完成全部清理。
                self._ignored_rules = []
                self.save_data("ignored_files", self._ignored_rules)
                self._post_reply(event, f"✅ 已清空全部 {count} 条忽略规则，"
                                        f"相关文件将重新纳入对账。")
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

            # ⚠️ v0.8.0 起**没有**「纯数字序号」这种写法：旧的
            # `/rsync_ignore 1` 依赖 `_waiting_confirm_retries`（上一次搜索的
            # 内存上下文），命令顺序一错就会忽略错文件。现在纯数字按普通关键字
            # 处理，并落进下面那条「至少 2 个字符」的护栏 —— `1` 会被拒绝，
            # `1923`（剧名）仍然可用。要精确忽略某一个文件，请直接发完整 key，
            # 例如：/rsync_ignore 电视剧:某剧/Season 01/E01.mkv

            # 安全护栏 1：纯数字按普通关键字极易误伤（用户想的是「第 23 条」，
            # 实际会忽略掉所有含 "23" 的文件 —— S01E23、剧名 1923 全中）。
            # 旧版本依赖搜索结果上下文解释序号，v0.8.0 没有那个上下文了；
            # 模糊的纯数字输入一律拒绝，精确忽略请发完整 key。
            if text_arg.isdigit():
                self._post_reply(
                    event,
                    "⚠️ 纯数字无法作为忽略规则（会误伤所有含该数字的文件）。\n"
                    "要精确忽略某个文件，请发送它的完整路径（可在看板条目上看到），\n"
                    "例如：/rsync_ignore 电视剧:某剧/Season 01/E01.mkv"
                )
                return

            # 安全护栏 2：过短的包含规则极易误伤，要求至少 2 个字符
            if len(text_arg) < 2:
                self._post_reply(event, "⚠️ 忽略关键字过短，请至少输入 2 个字符，以免误伤其它文件。")
                return

            # 关键字忽略（子串包含）
            ok = self._add_ignore_rule(text_arg, match="contains", created_by=operator, source="chat")
            if ok:
                self._post_reply(
                    event,
                    f"✅ 已加入忽略清单（包含匹配）：\n• {text_arg}\n"
                    f"后续该范围文件不再计入缺失、不再触发重试提醒。"
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

