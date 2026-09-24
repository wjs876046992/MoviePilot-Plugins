"""
远程命令 /rsync_*：命令表、分发入口与回复通道（阶段 2 拆分）。

Remote /rsync_* commands: command table, dispatch entry, and the reply channel.

与 strm_ops.py / sync_ops.py 同一套约束（见其模块头注释）：Mixin 只搬**代码**，
self.* 状态（_waiting_confirm_retries 等）全部留在插件实例上，本类不持有任何状态。
"""
import os
import time
import traceback
from typing import Any, Dict, List, Optional

from app.core.event import Event, EventType, eventmanager
from app.sdk.logging import logger

from .constants import (
    STRM_SCAN_LIMIT,
    MAX_LOGGED_PATHS as _MAX_LOGGED_PATHS,
    RETRY_KEYWORD_LIMIT as _RETRY_KEYWORD_LIMIT,
)
from .paths import (
    excluded_dir_names as _excluded_dir_names,
    pair_name as _pair_name,
    valid_exts_of as _valid_exts_of,
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
                "desc": "重试失败/缺失的115文件(自动重传)",
                "category": "工具",
                "data": {"action": "retry"}
            },
            {
                "cmd": "/rsync_sync",
                "event": EventType.PluginAction,
                "desc": "同步已达到冷却时间(如2h)的入库媒体",
                "category": "工具",
                "data": {"action": "sync"}
            },
            {
                "cmd": "/rsync_force",
                "event": EventType.PluginAction,
                "desc": "忽略冷却限制，对全部目录执行增量传输",
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
                "desc": "strm 相关操作（无参=扫描缺 strm / <文件名> 只查该文件 / check 立即检查观察期 / gen 请助手补生成 / prune 清理无效项 / clear 清空）",
                "category": "工具",
                "data": {"action": "strm"}
            },
            {
                "cmd": "/rsync_backfill_clear",
                "event": EventType.PluginAction,
                "desc": "清空存量补传队列",
                "category": "工具",
                "data": {"action": "backfill_clear"}
            }
        ]

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

    @eventmanager.register(EventType.PluginAction)
    def handle_command(self, event: Event):
        """
        处理 /rsync_* 远程指令的统一入口。

        Single entry point for all /rsync_* remote commands. The action comes from
        the command data registered in get_command().
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
                # 与同步/补传保持一致的过滤口径：扩展名 + 排除规则。
                # 早先实现两者都不应用，列表会混入 .nfo/.jpg 等永远不会被同步的
                # 文件，重传它们浪费限流配额且没有意义。
                all_ext = pair.get("all_ext", False)
                # 口径与同步/补传共用同一实现，避免「搜索能搜到但同步不认」的漂移
                valid_exts = _valid_exts_of(self._media_extensions, all_ext)
                excluded_dirs = _excluded_dir_names(self._exclude_patterns)

                for root, dirs, files in os.walk(src_dir):
                    # 就地裁剪被排除的目录（@eaDir/#recycle 等），不下钻
                    dirs[:] = [d for d in dirs if d not in excluded_dirs]
                    for f in files:
                        if keyword not in f.lower():
                            continue
                        if valid_exts is not None and os.path.splitext(f)[-1].lstrip(".").lower() not in valid_exts:
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
            if self._is_running:
                self._post_reply(event, "⚠️ 当前同步任务正在运行中。")
            else:
                self._start_sync_thread(mode="ready", channel_event=event)

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
                # 搜源端 → 删目标端（经 CD2 挂载，强制云端状态与视图对齐）→ 定向重传。
                #
                # 为什么必须先删：CD2 改名失败等场景下，CD2 挂载视图会显示目标文件
                # 「存在且大小正常」，但 115 服务端实际只有改名失败的半成品
                # （形如 影片.mkv..xrp4gj）。此时 rsync --size-only 比较源/目标大小
                # 判定「已同步」而跳过 —— 重传永远不会发生，且插件无法从视图发现这一点。
                # 先通过挂载点 rm，CD2 会真实调用 115 删除接口，把视图与云端一起纠正，
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
                deleted, undeletable = self._delete_dest_files_for_retry(result["matched"])
                if undeletable:
                    # 目标端删不掉 = 视图可能仍是脏的，此时 rsync 会因 --size-only
                    # 跳过这些文件（白占配额），必须明确告知而不是静默继续
                    names = "\n".join(f"• {k}" for k in undeletable[:_MAX_LOGGED_PATHS])
                    self._post_reply(
                        event,
                        f"⚠️ 有 {len(undeletable)} 个文件在目标端删除失败（挂载点可能未就绪），"
                        f"已跳过它们，其余 {len(deleted)} 个继续重传：\n{names}\n"
                        f"建议稍后重试；若反复失败请检查 CD2 挂载状态。"
                    )
                    if not deleted:
                        return
                summary = (
                    f"🧹 已清理目标端 {len(deleted)} 个文件并开始定向重传：\n"
                    + "\n".join(f"• {k}" for k in deleted[:_MAX_LOGGED_PATHS])
                    + (f"\n（共 {len(deleted)} 个）" if len(deleted) > _MAX_LOGGED_PATHS else "")
                )
                self._post_reply(event, summary)
                self._start_sync_thread(mode="retry", custom_files=deleted,
                                        channel_event=event)
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
            # /rsync_strm         → 全量主动扫描
            # /rsync_strm <关键字> → 只查指定文件（不遍历整库）
            # /rsync_strm clear   → 清空疑似与待观察清单
            # /rsync_strm prune   → 只清理无效条目
            #
            # 两种模式并存的原因：全量扫描是「我不知道哪些文件有问题」的答案，
            # 但当用户**已经明确知道**是哪个文件时（例如在 115 云端看到残留），
            # 遍历整库纯属浪费 —— 关键字模式直接定位那一个，秒回。
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

            arg_lower = (text_arg or "").lower()
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
                result = self._check_watch_now(list(self._strm_watch.keys()))
                self._post_reply(event, ("📺 " if result.get("success") else "⚠️ ")
                                 + result.get("message", "检查失败"))
                return
            if arg_lower in ("failed", "fail", "确认失败", "没传上"):
                # 把全部观察期条目按「用户确认没传上去」提前转入疑似清单。
                #
                # ⚠️ 远程命令**没有看板勾选那么精确**，一次就是全部在观察的条目
                # （含刚刚同步成功、本来很可能正常的那些）。因此这里必须把数量念
                # 出来，用户才知道自己刚刚越过了多少个文件的窗口 —— 静默执行会
                # 让「我没说过全部啊」变成一次无法追查的误操作。
                # 需要精确到单个文件时看板上有逐条按钮；远程命令只服务于
                # 「我已经挨个看过 115，这一批全没上去」这种整体判断。
                watch_keys = list(self._strm_watch.keys())
                if not watch_keys:
                    self._post_reply(event, "ℹ️ 当前没有处于观察期的文件。")
                    return
                result = self._api_strm_confirm_failed({"keys": watch_keys})
                self._post_reply(event, ("📺 " if result.get("success") else "⚠️ ")
                                 + f"（本次涉及全部 {len(watch_keys)} 个观察中条目）\n"
                                 + result.get("message", "操作失败"))
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
            if self._missed_queue:
                reply += (f"🕳️ 错过入库待补扫: {len(self._missed_queue)} 个"
                          f"（插件重载期间丢失事件，已由源端扫描补回，下轮同步自动带上）\n")
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

