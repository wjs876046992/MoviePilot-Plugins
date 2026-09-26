"""
strm 交叉验证：核心状态机、助手联动与全部 strm Web API（阶段 2 拆分）。

Strm cross-validation: core state machine, helper delegation, and every strm
web API (stage-2 split).

为什么用 Mixin 而不是独立对象：这块逻辑读写大量插件实例状态
（_strm_watch / _strm_suspects / _strm_gen_requested / _ignored_rules ...），
DEVELOPMENT.md 8.1 的宿主约束是「**可变状态**必须留在插件实例上」——
Mixin 搬的是**代码**不是状态，方法里的 self.* 在组合后的实例上解析，
与宿主文档 §7.3 的 DatabaseMixin 模式同构。若改成持有状态的独立对象，
就会制造「谁才是真相来源」的第二个答案。

合并方式：主类声明 `class Rsync115Sync(StrmOpsMixin, _PluginBase)`，
MRO 保证同名覆盖不会发生（本 Mixin 不与主类/基类重名）。
静态审计与实例化冒烟见 tests/v3/rsync115sync/test_split_contract.py。
"""
import os
import re
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.event import Event, EventType, eventmanager
from app.sdk.logging import logger

# 宿主插件管理器：绑定由组合根（__init__.py）注入（见其导入区说明），
# 本模块不留自己的拷贝 —— 否则同一能力出现两份真相，测试注入点也会漂移。
def _plugin_manager_cls():
    # 解析顺序刻意是「包根优先」：宿主与测试都 patch app.plugins.rsync115sync
    # 模块上的绑定（组合根），组合根注入的拷贝只兜底防循环导入期的空窗。
    try:
        from . import _PluginManager as _pm
        if _pm is not None:
            return _pm
    except Exception:  # pragma: no cover
        pass
    if _PluginManager is not None:
        return _PluginManager
    return None

from . import store as _store_mod   # noqa: E402
from . import strm as _strm  # noqa: E402

from .constants import (  # noqa: E402
    STRM_CHECK_INTERVAL as _STRM_CHECK_INTERVAL,
    STRM_SCAN_LIMIT as STRM_SCAN_LIMIT,
    STRM_VIDEO_EXTENSIONS as STRM_VIDEO_EXTENSIONS,
    # 「不值得进入 strm 交叉验证」的原因码，常量的唯一归属地见其定义处说明
    SKIP_NON_VIDEO as SKIP_NON_VIDEO,
    SKIP_NO_STRM_DIR as SKIP_NO_STRM_DIR,
    STRM_GEN_DIR_LIMIT as STRM_GEN_DIR_LIMIT,
    P115_STRM_HELPER_PLUGIN as _P115_STRM_HELPER_PLUGIN,
    P115_STRM_COMMAND as _P115_STRM_COMMAND,
    P115_PAN_DIR_HINT as _P115_PAN_DIR_HINT,
    P115_PAN_MAPPING_FIELD as _P115_PAN_MAPPING_FIELD,
    RETRY_KEYWORD_LIMIT as _RETRY_KEYWORD_LIMIT,
    MAX_LOGGED_PATHS as _MAX_LOGGED_PATHS,
)
from .paths import (  # noqa: E402
    brief_paths as _brief_paths,
    excluded_dir_names as _excluded_dir_names,
    pair_name as _pair_name,
    rel_path_of_key as _rel_path_of_key,
    valid_exts_of as _valid_exts_of,
)

# ================= strm 交叉验证（由 __init__.py 原位搬入） =================


class StrmOpsMixin:
    """strm 交叉验证全部方法；本类不持有任何状态（见模块 docstring）。"""

    # ================= strm 交叉验证 =================

    # strm 交叉验证的**纯逻辑**（期望路径推导、三态流转判定）已迁至 strm.py，
    # 便于单测穷举边界（恰好到期 / 源端消失 / 映射被改）。本类保留的职责是
    # I/O 与持久化：探测文件系统、读写 _strm_watch / _strm_suspects。

    @staticmethod
    def _strm_video_exts() -> set:
        """
        strm 检查专用的扩展名集合（**仅视频**）。

        Video-only extension set for strm checks.

        为什么不能复用同步用的 media_extensions：那个白名单**包含字幕**
        （srt/ssa/ass），因为同步的入库单元是「整集 = 视频 + 外挂字幕」。
        但 strm 插件只为**视频**生成 .strm 指针文件，字幕永远不会有 ——
        拿同步白名单去查 strm，每个 `xxx.zh.srt` 都会变成「疑似上传异常」。
        这是主动扫描上线时的真实缺陷（用户发现 jpg/nfo 也会被判）。

        也不看映射的 all_ext：勾了「同步所有类型」意味着 jpg/nfo 也会被同步，
        但它们同样不会生成 strm，参与检查只会制造误报。
        """
        return {e.strip().lower() for e in STRM_VIDEO_EXTENSIONS.split(",") if e.strip()}

    @staticmethod
    def _migrate_strm_suspects(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        把疑似清单迁移到带来源的新格式。

        Migrate the suspect list to the origin-carrying shape.

        v0.1.7 及更早存的是 `{key: 时间戳}`；v0.1.8 起改为
        `{key: {ts, origin}}`。旧条目一律按 `watch` 处理 —— 那个版本只存在
        观察这一条来源，语义上就是正确的归属。
        Tolerates non-dict input, non-numeric values, and already-migrated entries.

        ⚠️ `origin` 字段名保留不改：它既在 `save_data` 的旧 JSON 里，也是
        台账 `files.origin` 这一列的名字。改名要同时动迁移代码与已有数据库，
        收益只是好看一点 —— 不做。（历史上有过第三个取值 `confirmed`，
        随「云端可见性」整套删除；读到它的旧条目会退化成 `watch`，与它
        真实的来路一致：那批条目本来就是同步成功后才进清单的。）
        """
        if not isinstance(raw, dict):
            return {}
        migrated: Dict[str, Dict[str, Any]] = {}
        for key, value in raw.items():
            if isinstance(value, dict) and "ts" in value:
                migrated[str(key)] = {
                    "ts": float(value.get("ts") or 0.0),
                    "origin": ("scan" if str(value.get("origin")) == _strm.ORIGIN_SCAN
                               else _strm.ORIGIN_WATCH),
                }
                continue
            try:
                ts = float(value)
            except (TypeError, ValueError):
                ts = 0.0
            migrated[str(key)] = {"ts": ts, "origin": _strm.ORIGIN_WATCH}
        return migrated

    def _prune_invalid_strm_suspects(self) -> int:
        """
        清洗疑似清单里**无效**的条目，返回清理数量。

        Prune suspects that can no longer be valid; returns how many were removed.

        哪些属于无效（每条都对应一个真实产生过脏数据的缺陷）：
          1. **非视频文件** —— v0.1.7 的主动扫描把 jpg/nfo/海报也扫了进来，
             而 strm 插件只为视频生成指针文件，这些条目永远不会恢复正常，
             会永久留在清单里。用户实测反馈过。
          2. **已命中忽略规则的文件** —— 忽略即「不再报警」，不应占着清单，
             还会被「全部删旧重传」波及。
          3. **源端文件已不存在** —— 无从重传，留着重传只会失败。
          4. **所属映射已取消 strm_dir 或已删除** —— 验证前提消失，
             与 _strm_check 的 NO_STRM_DIR 出口同一判据。

        为什么在**载入时**清洗而不只在写入时过滤：写入时过滤只能拦住新数据，
        升级前已经落盘的脏条目会一直留着，用户看到一堆永远处理不掉的条目，
        只能靠手工改插件数据文件。载入时清洗让升级本身就把历史问题一起解决。
        Pruning at load time (not only at write time) is what lets an upgrade clean
        up entries written by earlier, buggy versions.
        """
        removed = 0
        for key in list(self._strm_suspects.keys()):
            reason = None

            # 前缀匹配还原相对路径（任务名可含冒号）；归属不明时退回原 key，
            # 只用于取扩展名，判错的最坏后果是「没被判为非视频」而非删错文件。
            rel = _rel_path_of_key(key, self._sync_pairs) or key
            # 前两条判据与登记闸门**共用** `_strm_watchable`：字幕/图片既不该进
            # 观察期，也不该留在疑似清单里，两处写两份判据迟早在扩展名上漂移。
            watchable, _skip_code, skip_text = self._strm_watchable(key)
            if not watchable:
                reason = skip_text
            elif self._is_ignored(key):
                reason = "已命中忽略规则"
            else:
                src_root = _strm.source_root_of(key, self._sync_pairs)
                if src_root and not os.path.exists(os.path.join(src_root, rel)):
                    reason = "源端文件已不存在"

            if reason:
                self._strm_suspects.pop(key, None)
                # 补生成标记一并失效：条目都已判为无效，那个「请求过生成」的记录
                # 描述的场景不复存在。用户实测数据里 `strm_suspects` 为空、
                # 而 `strm_gen_requested` 还留着一条被忽略的文件，正是漏了这一步。
                self._strm_gen_requested.pop(key, None)
                removed += 1
                logger.info(f"[Rsync115Sync] 🧹 清理无效 strm 疑似条目（{reason}）: {key}")

        if removed:
            self.save_data("strm_suspects", self._strm_suspects)
            self.save_data("strm_gen_requested", self._strm_gen_requested)
            logger.warning(f"[Rsync115Sync] 🧹 已清理 {removed} 个无效 strm 疑似条目"
                           f"（非视频 / 已忽略 / 源端已删 / 映射已取消验证），剩余 "
                           f"{len(self._strm_suspects)} 个")
            # 清单可能因此清空，重置通知闩锁（与其它收尾路径一致）
            self._reset_strm_notified_if_clear()
        return removed

    def _prune_orphan_gen_markers(self) -> int:
        """
        清洗**孤儿补生成标记**：两个清单里都已不存在、却还留着请求记录的 key。

        Prune regenerate markers whose key is in neither the watch nor the suspect
        list — state that nothing else will ever clean up.

        **为什么单列一步**：`_strm_gen_requested` 的语义是「这个文件被请过补生成」，
        它只在两个清单中的条目上才有意义。但它自己没有任何出口 —— 条目从清单里
        消失（被忽略、被清理、重传成功解除观察）时，若调用方忘了连带失效，
        这条记录就永久留在数据文件里，既不显示、也不参与判定，只在下次该文件
        进入观察时冒出来把看板误导成「补生成后仍无」。
        用户实测数据里见过这种残留（`strm_suspects` 为空、标记还在）。
        A marker is meaningful only for an entry in one of the two lists; orphans
        linger invisibly and later mislabel a fresh observation.

        ⚠️ 切到台账之后，**同一行上的标记会随行一起消失** —— 条目被
        `_prune_invalid_strm_suspects` / `_prune_invalid_strm_watch` 摘掉时，
        `LedgerMapping.__delitem__` 删的是整行，`gen_requested_at` 那一列自然
        不在了。本函数因此只剩**跨 status 的那一类**孤儿要管：标记挂在
        `synced` / `ignored` / `candidate` 这些行上，而它们不属于任何一个清单。
        Row deletion now takes the marker with it, so only markers on rows whose
        status is outside both lists can still be orphaned.
        """
        orphans = [k for k in list(self._strm_gen_requested.keys())
                   if k not in self._strm_watch and k not in self._strm_suspects]
        for key in orphans:
            self._strm_gen_requested.pop(key, None)
        if orphans:
            self.save_data("strm_gen_requested", self._strm_gen_requested)
            logger.warning(f"[Rsync115Sync] 🧹 已清理 {len(orphans)} 个孤儿补生成标记"
                           f"（条目已不在任何清单中）: {_brief_paths(orphans)}")
        return len(orphans)

    def _prune_invalid_strm_watch(self) -> int:
        """
        清洗**观察清单**里不可能有 strm 的条目（非视频），返回清理数量。

        Prune watching entries that can never produce a .strm; returns how many were
        removed.

        为什么与疑似清单分开清洗：观察清单在旧版本里同样会混入字幕/图片
        （`_strm_arm_watch` 原先只挡「映射没配 strm_dir」，不挡文件类型）。
        这批条目升级后不会再被巡检处理掉 —— 巡检会清理它们，但要等到用户
        下一次同步触发巡检；而载入时清掉可以让看板立刻不再显示
        「N 个文件处于观察期」这种由字幕凑出来的假象。
        判据与登记闸门共用 `_strm_watchable`，因此清洗口径与入口闸门一致。

        Legacy watches can hold subtitles/images too: the arm gate used to filter only
        by "pair has no strm_dir", not by file kind.
        """
        removed = 0
        for key in list(self._strm_watch.keys()):
            watchable, _skip_code, skip_text = self._strm_watchable(key)
            if watchable:
                continue
            self._strm_watch.pop(key, None)
            # 补生成标记随之失效：它描述的是一次针对该文件的生成请求，
            # 而该文件本就不该被观察（与巡检清理出口同一处置）。
            self._strm_gen_requested.pop(key, None)
            removed += 1
            logger.info(f"[Rsync115Sync] 🧹 清理无效 strm 观察条目（{skip_text}）: {key}")
        if removed:
            self.save_data("strm_watch", self._strm_watch)
            self.save_data("strm_gen_requested", self._strm_gen_requested)
            logger.warning(f"[Rsync115Sync] 🧹 已清理 {removed} 个无效 strm 观察条目"
                           f"（非视频文件不会生成 strm），剩余 {len(self._strm_watch)} 个")
        return removed

    def _strm_expected_path(self, key: str) -> Optional[str]:
        """由队列 key 推导「应当生成」的 .strm 绝对路径；无 strm_dir 的映射返回 None。"""
        return _strm.expected_path(key, self._sync_pairs)

    def _strm_watchable(self, key: str) -> Tuple[bool, str, str]:
        """
        该 key 是否**值得**进入 strm 交叉验证。返回 (可否参与, 跳过原因码, 原因说明)。

        Whether this key can ever be represented by a .strm. Returns
        (watchable, skip_code, skip_text).

        ⚠️ 原因**分成「码」与「人话」两段**：码用于判定分支（例如「这批里有多少个
        是非视频」），人话只用于日志。若让调用方去匹配中文文案来判断分支，文案一改
        分支就静默失效 —— 这正是一类难查的回归。
        The code drives branching while the text is log-only, so rewording a message
        can never silently change behaviour.

        为什么需要它：strm 助手只为**视频**生成指针文件，字幕/图片/元数据
        （srt/ass/jpg/nfo…）永远不会有 .strm —— 而这正是「strm 疑似上传异常」
        标签页的判据。把它们纳入监控等于给每个字幕判一个**永远无法满足**的条件：
        用户看到一批永远不会消失的「疑似上传异常」，而它们本来就该没有 strm。

        为什么这条闸门必须放在**登记/进入清单**处，而不是展示层：疑似清单是
        「可执行操作」的数据源 —— 「删旧重传」会去删 115 端的对应文件，「忽略」
        又需要用户为一条本就正常的记录做手工豁免。只在展示层过滤，这些操作
        仍会作用在字幕上（用户实测反馈正是「清单里混着非视频文件」）。

        ⚠️ 与 `_prune_invalid_strm_suspects` 的关系：那是**载入时清洗历史脏数据**
        的兜底（老版本落盘的非视频条目），本方法是把闸门前移到写入路径，让新条目
        从一开始就不产生。两者判据都是「视频扩展名」，因此共用 `_strm_video_exts`
        与 `_rel_path_of_key`，不各写一份 —— 两份判据迟早会漂移。

        Returns
        -------
        Tuple[bool, str]
            (是否可参与 strm 交叉验证, 不可参与的原因；可参与时原因为空串)
        """
        # 取出相对路径只看扩展名。归属不明时退回原 key：判错的最坏后果是
        # 「没被判为非视频」而非误删记录（与 _prune_invalid_strm_suspects 同取向）。
        rel = _rel_path_of_key(key, self._sync_pairs) or key
        ext = os.path.splitext(rel)[-1].lstrip(".").lower()
        if ext not in self._strm_video_exts():
            return False, SKIP_NON_VIDEO, f"非视频文件（.{ext} 不会生成 strm）"
        # 所属映射未配 strm_dir —— 本来的判据是「推导不出期望路径」，保持原判
        # （与 _strm_expected_path 一致），否则会把「映射没配」误报成「非视频」。
        if self._strm_expected_path(key) is None:
            return False, SKIP_NO_STRM_DIR, "所属映射未配置 strm 目录"
        return True, "", ""

    def _mark_synced(self, key: str, now_ts: float) -> None:
        """
        记下「这个文件被 rsync 报告同步成功」的时刻（台账 `synced_at` 列）。

        Record the moment rsync reported this file as synced.

        为什么单独一层、而不是直接调 `self._ledger.upsert(...)`：
        它要在**台账不可用时静默降级**，而 `self._ledger` 可能是 None。
        收在一处，就不必在每个调用点重复这个判空（漏一处就是 AttributeError
        打断正在进行的传输）。
        One place for the null check: the ledger may be unavailable, and a missing
        guard at any call site would raise inside the sync path.

        ⚠️ 用 `getattr` 而不是直接取属性：本插件有大量 `__new__` 构造的最小实例
        （单测与若干内部路径），它们**没有** `init_plugin` 建立的那些属性 ——
        直接取会抛 AttributeError。这是本仓反复踩到的一类问题（见
        `_api_get_status` 里同类说明）。
        `getattr` rather than direct attribute access: many minimal instances are
        built via `__new__` and never run `init_plugin`.
        """
        ledger = getattr(self, "_ledger", None)
        if ledger is None:
            return
        try:
            ledger.upsert(key, _store_mod.STATUS_PENDING_VERIFY, synced_at=now_ts)
        except Exception as e:
            # 台账是辅助设施，写失败绝不能让同步流程中断
            logger.debug(f"[Rsync115Sync] 记录同步成功时刻失败（已忽略）: {key}: {e}")

    def _strm_arm_watch(self, keys: List[str]) -> int:
        """
        同步成功后把文件登记进「待观察」清单（宽限期从现在起算）。

        Arm a strm watch for successfully synced files. A key already in the suspect
        list is removed on success — the re-transfer cleared it.

        ⚠️ 同时**清除补生成标记**：此刻这个文件刚被完整重传过，之前的「已请求
        助手补生成」记录已经过期 —— 留着它会让看板把一条全新的观察标成「生成
        过仍失败」，而这轮观察跟那次补生成毫无关系（比 `_strm_check` 里有意
        保留标记的情形更彻底的失效：重传已经改变了事实基础）。
        The regenerate marker is invalidated here: a fresh transfer means any earlier
        "already asked the helper" note no longer describes this file's situation.
        """
        armed = 0
        skipped_non_video = 0
        now_ts = time.time()
        for k in keys:
            watchable, skip_code, skip_text = self._strm_watchable(k)
            if not watchable:
                # 非视频文件（字幕/图片/元数据）永远不会有 .strm，登记观察只会
                # 在宽限期后产出一条**永远无法解除**的疑似异常。计数而非静默
                # 丢弃：入库一批带字幕的剧集时，「同步 10 个、只观察 3 个」需要
                # 一个可解释的数字，否则排查时只能靠猜。
                # Non-video files can never get a .strm; arming them would only
                # produce a suspect that can never be resolved.
                if skip_code == SKIP_NON_VIDEO:
                    skipped_non_video += 1
                continue
            # 已加入忽略清单的文件不登记观察。
            #
            # 为什么要在**最上游**拦：「忽略」的语义是「这个文件不要再报警」，
            # 而 strm 疑似同样是一种报警。若只在展示层过滤，被忽略的文件仍会在
            # 观察期到期时写进疑似清单、还会触发通知 —— 用户会收到自己明确
            # 忽略过的文件的告警。在登记处拦掉，后续观察/疑似/通知全都不涉及它。
            # Skip ignored files at the earliest point: ignoring means "stop alerting
            # about this file", and a strm suspect is an alert. Filtering only at the
            # display layer would still write them into the suspect list and notify.
            if self._is_ignored(k):
                continue
            # ⚠️ 记一次「同步成功」的时刻。**这是 `synced_at` 的唯一写入点**，
            # 也是台账能回答"哪些文件真的传上去过"的依据（用户需求 C1：
            # 「所有映射目录里的视频 + 一份台账，便于区分已成功的」）。
            #
            # 此刻的措辞是"rsync 报成功"，不是"已验证可用" —— 后者要等 .strm
            # 出现（下面登记观察的那一步）。所以这一列可能与后来转成待处理并存：
            # 那正是"传过、但这一轮没传成"的形态，是有用的事实而非矛盾。
            # Reason: this is "rsync reported success", not "verified usable" — the
            # latter waits for the .strm. Both can be true at once, and that is
            # exactly the "synced before, failed this round" case.
            self._mark_synced(k, now_ts)
            self._strm_watch[k] = now_ts
            # 重传成功即解除疑点
            if k in self._strm_suspects:
                self._strm_suspects.pop(k, None)
                self.save_data("strm_suspects", self._strm_suspects)
            if k in self._strm_gen_requested:
                self._strm_gen_requested.pop(k, None)
                self.save_data("strm_gen_requested", self._strm_gen_requested)
            armed += 1
        if armed:
            self.save_data("strm_watch", self._strm_watch)
            # 疑点被解除后，若清单已清空则重置通知标志，让下次新发现能再次提醒
            self._reset_strm_notified_if_clear()
        if skipped_non_video:
            # 只在真的跳过了才记；这是用户核对「入库数与观察数对不上」的唯一线索
            logger.debug(f"[Rsync115Sync] 📺 已跳过 {skipped_non_video} 个非视频文件"
                         f"（字幕/图片等永远不会生成 strm，不纳入交叉验证）")
        return armed

    def _strm_check(self) -> Dict[str, Any]:
        """
        strm 交叉验证巡检：走 I/O 与持久化，三态判定交给 strm.classify_watch。

        Strm cross-validation sweep. This method only probes the filesystem and
        persists results; the state machine itself lives in strm.py.

        出口：strm 已生成（正常解除）/ 到期未生成（转疑似）/ 未到期（继续观察）/
        映射取消 strm_dir 或源端消失（清理）。后两者不合并计数，见 strm.py 的
        状态定义说明。

        纯本地文件系统操作，零 115 API；由定时巡检调用，内部再按固定间隔节流。
        """
        now_ts = time.time()
        # 巡检节流：strm 生成是分钟级的事，没必要每次同步都查一遍
        if now_ts - self._strm_last_check < _STRM_CHECK_INTERVAL:
            return {"checked": 0, "ok": 0, "new_suspects": 0}
        self._strm_last_check = now_ts

        # ⚠️ 早退条件**必须同时看两个清单**：巡检现在还要处理「疑似条目的 strm
        # 后来出现了」这件事（见 `_prune_resolved_suspects`）。若仍只判
        # `not self._strm_watch`，那么观察清单为空、疑似清单非空时整轮直接返回 ——
        # 而那恰恰是最需要它跑的时刻（条目已全部转入疑似，就等着被确认）。
        # The early-return must consider both lists: suspects can be non-empty while
        # the watch list is empty, which is exactly when resolution matters.
        if not self._strm_check_enabled or not (self._strm_watch or self._strm_suspects):
            # 明确留痕：否则用户无法区分「strm 功能没工作」与「工作了但两个清单都是空的」，
            # 只能看到一个静默返回，排查时完全没有依据（用户实测反馈过这一点）。
            logger.debug(f"[Rsync115Sync] strm 巡检跳过："
                         f"{'功能已关闭' if not self._strm_check_enabled else f'观察与疑似清单均为空'}")
            return {"checked": 0, "ok": 0, "new_suspects": 0, "resolved": 0}

        # 先处理疑似清单：这一步与下面的观察期循环彼此独立（一个 key 不可能同时
        # 在两个清单里），但放在前面有个好处 —— 它清空的条目不会在本轮被后面的
        # 逻辑重新登记成疑似。
        #
        # 两个判据都要跑：`_prune_cooling_suspects` 处理"还没上传"的误报，
        # `_prune_resolved_suspects` 处理"其实已经成功"的。顺序上先清冷却期的 ——
        # 它是**已经确定的误报**，而另一个要读文件系统。
        cooling_pruned = self._prune_cooling_suspects()
        resolved = self._prune_resolved_suspects()

        grace_secs = _strm.grace_secs_of(self._strm_grace_minutes)
        settled_ok: List[str] = []
        new_suspects: List[str] = []
        # 其中「补生成后仍无」的那部分：与普通到期分开计数，日志与通知里
        # 才能体现判定强度的差别（生成动作做过而仍没有，基本可确认云端缺文件）。
        gen_suspects: List[str] = []
        dropped: List[str] = []

        for key in list(self._strm_watch.keys()):
            # 忽略清单是最高优先级：用户在观察期内加了忽略规则时，这里必须让位，
            # 否则条目仍会到期转疑似并触发通知 —— 用户会收到自己忽略过的文件的告警。
            # `_add_ignore_rule` 已经会主动清理两个清单，这里是兜底（例如规则由
            # 其它实例/更早版本写入，或清理逻辑未覆盖到的时序）。
            # Ignore rules win: a rule added during the grace window must not let the
            # entry turn into a suspect (and notify) anyway.
            if self._is_ignored(key):
                dropped.append(key)
                continue
            # 非视频条目直接清理（兜底）：登记闸门已在 `_strm_arm_watch` 拦掉新的，
            # 但**旧版本落盘**的观察清单（含 srt/jpg）仍会被载入。它与"疑似清单载入
            # 即清洗"是同一个理由 —— 写入路径的过滤拦不住升级前已存在的数据。
            # 这类条目永远等不到 .strm，留着只会走完宽限期后变成一条无法解除的疑似。
            watchable, _skip_code, skip_text = self._strm_watchable(key)
            if not watchable:
                logger.info(f"[Rsync115Sync] 🧹 清理无效 strm 观察条目（{skip_text}）: {key}")
                dropped.append(key)
                continue
            # 判定委托给 check_one：它与看板「立即检查」是**同一份实现**，
            # 否则「手动说已生成、巡检仍判观察中」这类分歧迟早出现。
            state, record = self.check_one(key, now_ts, grace_secs)
            if state == _strm.SUSPECT:
                new_suspects.append(record)
                if key in self._strm_gen_requested:
                    gen_suspects.append(record)
            elif state == _strm.WATCHING:
                continue
            elif state == _strm.SETTLED:
                settled_ok.append(key)
            else:
                # NO_STRM_DIR 与 SOURCE_GONE 都是清理出口，与「正常解除」分开计数
                dropped.append(key)

        for k in settled_ok + dropped:
            self._strm_watch.pop(k, None)
            # 条目已离场（strm 已生成 / 映射失效 / 源端消失），补生成标记随之失效。
            # 不清理的话这个字典只增不减，长期运行会把每次请求过的 key 全留着 ——
            # 而看板正是靠它标记「已请求生成」，陈旧标记会让新条目被误标。
            self._strm_gen_requested.pop(k, None)
        for k in new_suspects:
            self._strm_watch.pop(k, None)
            self._strm_suspects[k] = {"ts": now_ts, "origin": _strm.ORIGIN_WATCH}
            # ⚠️ 有意**保留** _strm_gen_requested：这些条目正是「已经请助手生成过、
            # 宽限期到仍无 strm」的那批，标记必须留着，用户才知道这已经是补生成
            # 之后的结果（判定比首次疑似硬得多），而不是又一轮普通疑似。
        if settled_ok or dropped or new_suspects:
            self.save_data("strm_watch", self._strm_watch)
            self.save_data("strm_suspects", self._strm_suspects)
            self.save_data("strm_gen_requested", self._strm_gen_requested)
            if new_suspects:
                # 日志里把「补生成后仍无」单独标出来：排查时这一条的信息量远大于
                # 普通到期，混在一起的计数会让人误以为两者同样可疑。
                gen_note = (f"，其中 {len(gen_suspects)} 个是补生成后仍无"
                            if gen_suspects else "")
                logger.warning(f"[Rsync115Sync] 📺 strm 交叉验证发现 {len(new_suspects)} 个疑似上传异常"
                               f"（宽限期 {self._strm_grace_minutes} 分钟内未见 strm 生成{gen_note}）: "
                               f"{_brief_paths(new_suspects)}")
                self._notify_strm_suspects(new_suspects)
            elif settled_ok:
                logger.debug(f"[Rsync115Sync] strm 交叉验证：{len(settled_ok)} 个文件 strm 已生成，正常")

        return {"checked": len(settled_ok) + len(new_suspects) + len(dropped),
                "ok": len(settled_ok), "new_suspects": len(new_suspects),
                "resolved": len(resolved),
                "cooling_pruned": len(cooling_pruned)}

    def _prune_cooling_suspects(self) -> List[str]:
        """
        移除「此刻仍在冷却队列」的疑似条目，返回被移除的 key。

        Drop suspect entries whose file is *currently* still in the cool-down queue.

        ## 为什么它们是误报（用户实测反馈）

        用户原话：「还在冷却期未上传，手动扫描 strm，未检查到就放到疑似列表里，
        按理应该先和冷却期的比对」，并进一步指出 ——
        **「冷却结束会自动同步，按理应该移除了」**。

        冷却队列里的文件**尚未上传**，所以必然没有 `.strm`。把它挂在疑似清单里
        的后果不是"多一条记录"，而是**它会把人引向错误的处置**：
        疑似清单上唯一的修复动作是「删旧重传」，而这个文件根本不是"上传失败"，
        是"**还没轮到上传**"。手动删了反而打断正常的冷却流程。

        ## 与 `_prune_resolved_suspects` 的分工

        | 方法 | 判据 | 覆盖的场景 |
        |---|---|---|
        | `_prune_resolved_suspects` | `.strm` 已存在 | 上传其实成功了（助手补生成 / 用户手动处理过） |
        | `_prune_cooling_suspects`（本方法） | 仍在冷却队列 | 上传**还没开始**，被扫描误报进来 |

        两个判据互斥（一个要求"已上传成功"，一个要求"尚未上传"），合并反而会让
        "它到底为什么被移出"变得说不清 —— 而这一条在排查时需要能一眼分辨。

        ⚠️ **判据是「此刻仍在队列」，不是「曾经在过」**：文件冷却结束、同步跑完后
        会出队；若那次同步失败，它才会作为**真疑似**留下来。所以不能用历史痕迹判断，
        只能看当前状态。
        The criterion is *currently* queued: after cooling elapses the file is synced
        and dequeued, and a genuine failure is then correctly a suspect again.

        ⚠️ 观察期**不在**本方法的判据里（用户明确要求）：观察期条目已同步成功、
        只是还没等到 `.strm`，那是另一件事，由 `check_one` 的窗口机制处理。
        """
        pending = getattr(self, "_pending_queue", None) or {}
        if not pending:
            return []
        cooling = [k for k in list(self._strm_suspects.keys()) if k in pending]
        for key in cooling:
            self._strm_suspects.pop(key, None)
            # 补生成标记一并失效：条目已离场，留着只会让下一次同名条目被误标成
            # 「补生成后仍无」—— 而那次补生成针对的是"还没上传的文件"，
            # 结论毫无意义。与其它出口同口径。
            self._strm_gen_requested.pop(key, None)
        if cooling:
            self.save_data("strm_suspects", self._strm_suspects)
            logger.info(f"[Rsync115Sync] 🧊 {len(cooling)} 个疑似条目其实**还在冷却队列**"
                        f"（尚未上传，按定义不可能有 strm），已移出待处理清单: "
                        f"{_brief_paths(cooling)}")
            # 清单可能因此清空 —— 与其它出口同口径重置通知闩锁，
            # 否则「已全部解决」那条通知永远发不出去。
            self._reset_strm_notified_if_clear()
        return cooling

    def _prune_resolved_suspects(self) -> List[str]:
        """
        移除「.strm 已经存在」的疑似条目，返回被移除的 key。

        Drop suspect entries whose .strm now exists; returns the removed keys.

        ## 为什么需要它（这是一个真实存在的缺口）

        巡检只遍历**观察期**，从不碰疑似清单。于是一个疑似条目一旦入列，
        就**永远不会因为「strm 后来出现了」而自动消失**，只能在看板上手工
        「忽略」或「删旧重传」。而这三种情况都会让它变成假警报：

          1. 用户通过**别的途径**补生成了 strm（助手自己的定时任务、手动触发）；
          2. 用户手动点了补生成，但**只勾了同目录的一部分**文件 ——
             助手按目录遍历，没勾的那几个其实也生成了；
          3. 用户在 115 侧手工处理好了。

        用户明确提出过这一点：「在扫描缺失 strm 时，查找到有 strm 了，就可以
        进行移除了」。原实现只在**扫描**时对观察期与疑似去重（不重复登记），
        漏掉了「已存在却仍挂在清单里 → 移除」这一步。

        ## 判据**只有一条**：`.strm` 文件是否存在

        ⚠️ 绝不引入 CD2 挂载视图（大小 / 残留名）作判据 —— 那套「云端可见性」
        判定已在 v0.3.0 整条删除，原因是它对**改名失败**这个主成因必然判错
        （残留与正式文件字节数相同，挂载视图照样显示「可见、大小一致」，见
        DEVELOPMENT §3.11）。判据只能是 strm，因为助手**只在视频正确上传后才
        生成它**，这是唯一与「云端真的可用」同构的信号。
        Only ".strm exists" — never the mount view: that verdict was removed in
        v0.3.0 because it is wrong exactly for the rename-failure case.

        纯本地检查（一次 `os.path.exists`），零 115 API，因此不需要执行锁。
        """
        resolved: List[str] = []
        for key in list(self._strm_suspects.keys()):
            # 映射没配 strm_dir 时 `_strm_expected_path` 返回 None —— 无从判断，
            # 保持原样（这种条目的清理归 `_prune_invalid_strm_suspects` 按
            # 「映射取消验证」处理，两处的判据不要混）。
            expected = self._strm_expected_path(key)
            if not expected:
                continue
            try:
                exists = os.path.exists(expected)
            except OSError:
                # 读不到不代表没有：与 `check_one` 同一取向 —— 保守地留在清单里，
                # 宁可多挂一轮也不要因为一次挂载抖动把它静默摘掉。
                continue
            if exists:
                self._strm_suspects.pop(key, None)
                # 补生成标记随之失效（条目已离场，留着它只会让下一个同名条目被误标）
                self._strm_gen_requested.pop(key, None)
                resolved.append(key)

        if resolved:
            self.save_data("strm_suspects", self._strm_suspects)
            logger.info(f"[Rsync115Sync] ✅ {len(resolved)} 个疑似条目的 strm 已存在，"
                        f"已移出待处理清单: {_brief_paths(resolved)}")
            # 清单可能因此清空 —— 与其它出口同口径重置通知闩锁
            # （否则「已全部解决」这条通知永远不会发，用户会以为问题被静默遗忘）。
            self._reset_strm_notified_if_clear()
        return resolved

    def _notify_strm_suspects(self, new_suspects: List[str]) -> None:
        """
        发现新的 strm 疑似异常时推送通知（仅新发现时发，不重复打扰）。

        Notify on newly discovered strm suspects only — the whole-list state is
        already visible on the dashboard, so repeating it every sweep would train
        the user to ignore the channel.
        """
        if not self._notify or self._strm_notified or not new_suspects:
            return
        mtype = self._plugin_mtype()
        if mtype is None:
            logger.warning("[Rsync115Sync] 宿主 MessageType 不可用，已跳过 strm 疑似异常通知以免广播")
            return
        total = len(self._strm_suspects)
        listed = "\n".join(f"• {k}" for k in new_suspects[:_MAX_LOGGED_PATHS])
        more = f"\n（另有 {len(new_suspects) - _MAX_LOGGED_PATHS} 个未列出）" \
            if len(new_suspects) > _MAX_LOGGED_PATHS else ""
        try:
            self.post_message(
                mtype=mtype,
                title="115同步：发现疑似上传异常",
                text=(
                    f"⚠️ 本次新发现 {len(new_suspects)} 个疑似上传异常（清单共 {total} 个）：\n"
                    f"{listed}{more}\n\n"
                    f"判定依据：同步已报告成功，但 {self._strm_grace_minutes} 分钟内未在 strm 目录生成对应文件。\n"
                    f"💡 请先确认 strm 插件本身是否正常（媒体是否识别、功能是否开启），\n"
                    f"   再前往看板「strm 疑似异常」标签处理：\n"
                    f"   ① 先点「先尝试生成 strm」——若只是漏生成，这一步就能解决，无需重传；\n"
                    f"   ② 补生成后仍无，再对该条目使用「删旧重传」。"
                ),
            )
            self._strm_notified = True
            self.save_data("strm_notified", True)
            logger.info(f"[Rsync115Sync] 📤 已推送 strm 疑似异常通知（{len(new_suspects)} 个新发现，"
                        f"清单共 {total} 个）")
        except Exception as e:
            logger.error(f"[Rsync115Sync] strm 疑似异常通知发送失败: {e}")

    def _reset_strm_notified_if_clear(self) -> None:
        """
        疑似清单清空后重置通知标志，使下次新发现能再次提醒，并推送「已全部解决」。

        Reset the notification latch once the suspect list drains, so a future batch
        alerts again; also send a short all-clear so the user knows the earlier
        warning was resolved rather than merely forgotten.
        """
        if self._strm_notified and not self._strm_suspects:
            self._strm_notified = False
            self.save_data("strm_notified", False)
            if self._notify:
                mtype = self._plugin_mtype()
                if mtype is not None:
                    try:
                        self.post_message(
                            mtype=mtype,
                            title="115同步：strm 疑似异常已全部解决",
                            text="✅ 之前报告的 strm 疑似上传异常文件已全部恢复"
                                 "（strm 已生成或已完成重传），无需再处理。",
                        )
                    except Exception as e:
                        logger.error(f"[Rsync115Sync] strm 恢复通知发送失败: {e}")

    # ---- 主动 strm 扫描（补上「从未被观察过」的盲区）----
    #
    # 为什么需要它：观察模式（_strm_check）只遍历自己登记过的文件，而登记只发生在
    # **同步成功之后**。于是「历史上传失败、插件从未认为它成功过」的文件永远进不了
    # 视野 —— 用户在 115 云端看到 `xxx.mkv..xrp4gj` 残留、挂载视图却显示正常，
    # 插件这边毫无察觉（用户实测场景）。主动扫描反其道而行：从**源端**出发，
    # 逐个查该有的 .strm 在不在，因此不依赖「插件自认为成功过」这个前提。
    #
    # 纯本地文件比对（源端 + strm 端都是本地路径），零 115 API。
    # Purely local comparison of two local trees; never touches the 115 mount.

    def _strm_scan(self, limit: int = STRM_SCAN_LIMIT) -> Dict[str, Any]:
        """
        主动扫描：找出源端存在但缺对应 .strm 的文件。

        Proactive sweep for files whose own .strm never appeared.

        ⚠️ 判据固有歧义（务必向用户说明）：它**无法区分**
          a) 从未上传过的存量文件（正常，应走补传而非重传）
          b) 上传了但 CD2 假成功（要抓的异常）
        两者表现完全一致。因此结果一律标为 `scan` 来源的**疑似**，
        且 UI/通知必须提示用户先判断是哪种情况。
        """
        if not self._strm_check_enabled:
            return {"success": False, "message": "strm 交叉验证已关闭"}

        configured = [p for p in self._sync_pairs
                      if (p.get("strm_dir") or "").strip()]
        if not configured:
            return {"success": False,
                    "message": "没有任何映射配置了 strm 目录，无法执行扫描。"
                               "请在配置页为目标映射填写 strm 目录。"}

        def _list_dir(path: str):
            try:
                return os.listdir(path)
            except OSError:
                return None

        excluded = _excluded_dir_names(self._exclude_patterns)

        def _valid_exts(pair):
            # ⚠️ 必须用**视频专用**扩展名，不能用同步用的 media_extensions：
            # 后者含 srt/ssa/ass，而 strm 插件只为视频生成 .strm，字幕永远没有 ——
            # 用同步白名单会让每个字幕都被判成疑似异常（必然误报）。
            # 同理**忽略 all_ext**：勾了「同步所有类型」也不该去查 jpg/nfo 的 strm。
            #
            # 注意必须写 self. —— 这是个闭包，内部的裸名字会按**模块全局**解析，
            # 而 _strm_video_exts 是类方法，不会因此找到（报 NameError）。
            # `getattr` 在真实实例上有效，裸实例（__new__ 造）也一样，
            # 但闭包名字解析与实例无关，这是两种完全不同的查找路径。
            return self._strm_video_exts()

        candidates, truncated, checked = _strm.scan_candidates(
            self._sync_pairs, _list_dir, limit,
            excluded_dirs=excluded, valid_exts_for=_valid_exts)

        now_ts = time.time()
        added = 0
        skipped_ignored = 0
        skipped_watching = 0
        skipped_cooling = 0
        for key in candidates:
            # 已被用户加入忽略清单的文件不产生疑似条目 —— 「忽略」的语义就是
            # 「不要再为这个文件报警」，而疑似清单是一种报警。用户在 /rsync_ignore
            # 里明确忽略过的文件再次出现，是用户实测反馈的问题。
            # Ignored files never become suspects: ignoring means "stop alerting".
            if self._is_ignored(key):
                skipped_ignored += 1
                continue
            # ⚠️ 已在观察期的条目**不降级**为疑似（scan → suspect 会把「刚同步
            # 成功、还在等生成」错判成「有问题」）。
            #
            # 这条闸门是补生成功能带来的：请求补生成后条目会被移回观察期，而它
            # 此刻的 .strm 按定义还不存在，任何一次主动扫描都会立刻把它打回疑似
            # —— 用户点完按钮看到的仍是同一批疑似条目，功能表现为完全没作用。
            # 观察期自带到期机制，让扫过的条目自己走完窗口即可。
            # Never demote a watching entry to a suspect: right after a regenerate
            # request its .strm does not exist yet by definition, so a sweep would
            # instantly undo the re-arm and make the feature look inert.
            if key in self._strm_watch:
                skipped_watching += 1
                continue
            # ⚠️ **还在冷却队列里的文件不是异常**：它按定义**尚未上传**，
            # 所以此刻必然没有 .strm —— 把它扫成疑似是纯粹的误报。
            #
            # 用户实测反馈：「还在冷却期未上传，手动扫描 strm，未检查到就放到
            # 疑似列表里，按理应该先和冷却期的比对」。原实现只比对了忽略规则、
            # 观察期、疑似清单三处，**唯独漏了冷却队列**，于是每次全量扫描都会
            # 把整批正在冷却的文件报成"缺 strm"。
            #
            # 这与观察期那条闸门是同一个道理（都是"暂时没有 .strm 属正常"），
            # 但冷却队列更基础：它连上传都还没开始。
            # A file still cooling down has not been uploaded at all, so it cannot
            # have a .strm yet. Reporting it as a suspect is a pure false positive.
            # ⚠️ `getattr` 兜底：本方法会被 service 直接调用，而 `__new__`
            # 构造的最小实例（单测 / 内部路径）没有 `_pending_queue` ——
            # 缺属性不该让**整条扫描**崩掉（同一处理见 `_expand_ingest_path`）。
            if key in (getattr(self, "_pending_queue", None) or {}):
                skipped_cooling += 1
                continue
            # 已在疑似清单里的不重复计数，但**不刷新时间戳**
            # （刷新会让「首次疑似时间」失去意义，用户无从判断它挂了多久）
            if key in self._strm_suspects:
                continue
            self._strm_suspects[key] = {"ts": now_ts, "origin": _strm.ORIGIN_SCAN}
            added += 1

        if added:
            self.save_data("strm_suspects", self._strm_suspects)
        logger.info(f"[Rsync115Sync] 📺 主动 strm 扫描（已检查 {checked} 个文件）："
                    f"发现 {len(candidates)} 个缺 strm，新增 {added} 个疑似"
                    f"{f'，因忽略规则跳过 {skipped_ignored} 个' if skipped_ignored else ''}"
                    f"{f'，{skipped_watching} 个仍在观察期未降级' if skipped_watching else ''}"
                    f"{f'，{skipped_cooling} 个仍在冷却队列未上传' if skipped_cooling else ''}")

        if added:
            self._notify_strm_suspects(candidates[:added])

        # 顺带清掉两类**确定的误报**。放在扫描里是因为用户点这个按钮的意图
        # 正是「全面看一遍现在到底还有哪些问题」—— 只报新增而不清理失效的，
        # 清单会越看越不可信（挂着的问题其实早解决了 / 压根还没轮到）。
        #
        # ① 仍在冷却队列的（尚未上传 ⇒ 不可能有 strm）—— 用户实测反馈的这一类；
        # ② `.strm` 已经出现的（上传其实成功了）。
        cooling_pruned = self._prune_cooling_suspects()
        resolved = self._prune_resolved_suspects()

        msg = (f"已检查 {checked} 个文件，发现 {len(candidates)} 个缺 strm 的文件"
               f"（新增 {added} 个）。")
        if cooling_pruned:
            msg += (f"\n🧊 另有 {len(cooling_pruned)} 个疑似条目其实**还在冷却队列**"
                    f"（尚未上传，按定义不可能有 strm），已移出待处理清单。")
        if resolved:
            msg += (f"\n✅ 另有 {len(resolved)} 个疑似条目的 strm 已存在"
                    f"（可能是助手自己生成的、或你已处理过），已移出待处理清单。")
        if skipped_cooling:
            # 必须说出来：否则用户会以为扫出来的这批漏掉了。它们不是漏掉，
            # 而是**还没轮到上传** —— 冷却期结束、同步跑过之后才会有 .strm。
            msg += (f"\n🧊 另有 {skipped_cooling} 个文件仍在**冷却队列**（尚未上传），"
                    f"未计入疑似 —— 它们此刻必然没有 strm，属正常等待。")
        if skipped_watching:
            # 必须说出来：否则用户会以为扫出来的这批漏掉了。它们不是漏掉，
            # 而是**故意**交给观察期自己判定（可能是刚请求补生成、也可能是
            # 刚同步成功还没生成）。
            msg += (f"\n⏳ 另有 {skipped_watching} 个文件已处于观察期（刚同步成功或"
                    f"已请求补生成），未重复计入疑似 —— 它们由观察窗口自行判定。")
        if skipped_ignored:
            msg += f"\n🚫 其中 {skipped_ignored} 个已命中忽略规则，未计入疑似。"
        if truncated:
            msg += (f"\n⚠️ 已达到单次上限 {limit} 个，结果被截断 ——"
                    f"若这个数字很大，更可能是 strm 插件本身没在工作，"
                    f"请先确认它的开关与媒体识别是否正常。")
        msg += "\n💡 注意：缺 strm 也可能是「从未上传过的存量文件」，"
        msg += "这类应使用补传而不是删旧重传。"
        # ⚠️ `candidates` 必须一并回传：看板要靠它显示「缺哪几个」。
        # 只回计数的话，用户看到「缺 2 个、新增 0 个」却查不到是哪两个
        # —— 而这个功能的全部意义就是告诉他哪个文件该处理。
        return {"success": True, "message": msg,
                "data": {"checked": checked, "found": len(candidates),
                         "added": added, "truncated": truncated,
                         "candidates": candidates,
                         "skipped_ignored": skipped_ignored,
                         "skipped_watching": skipped_watching,
                         "skipped_cooling": skipped_cooling,
                         "resolved_suspects": resolved,
                         "cooling_pruned_suspects": cooling_pruned}}

    def _reply_strm_keyword(self, event: Optional[Event], keyword: str) -> None:
        """
        `/rsync_strm <关键字>`：只检查源端命中关键字的文件，不做整库遍历。

        Check only the source files matching a keyword — no library-wide walk.

        为什么需要这一条：用户往往**已经知道是哪个文件出了问题**（例如在 115
        云端看到了 `xxx.mkv..xrp4gj` 残留），此时遍历整库既慢又无意义。
        复用了与 `/rsync_retry <关键字>` 相同的源端匹配口径（扩展名过滤 +
        排除目录裁剪 + 超限即拒），保证「搜到的」与「能重传的」是同一批文件。

        纯本地操作，零 115 API；命中即写入疑似清单（来源标记为 scan）。
        """
        result = self._search_target_files(keyword)
        if not result["matched"]:
            self._post_reply(event,
                             f"🔍 未在源目录中找到包含「{keyword}」的文件。")
            return
        if result["truncated"]:
            self._post_reply(
                event,
                f"⚠️ 关键字「{keyword}」匹配到超过 {_RETRY_KEYWORD_LIMIT} 个文件，"
                f"请用更精确的文件名缩小范围。本次未做任何检查。"
            )
            return

        missing, present, no_strm_dir, non_video = [], [], [], []
        for key in result["matched"]:
            # _search_target_files 用的是**同步口径**（含字幕），而 strm 只对视频
            # 生成指针文件，因此这里必须再按视频扩展名筛一次，否则字幕会误报。
            ext = os.path.splitext(
                _rel_path_of_key(key, self._sync_pairs) or key)[-1].lstrip(".").lower()
            if ext not in self._strm_video_exts():
                non_video.append(key)
                continue
            expected = self._strm_expected_path(key)
            if expected is None:
                no_strm_dir.append(key)
                continue
            if os.path.exists(expected):
                present.append(key)
            else:
                missing.append(key)

        now_ts = time.time()
        added = 0
        skipped_ignored = 0
        skipped_watching = 0
        skipped_cooling = 0
        for key in missing:
            # 与主动扫描同口径：被忽略的文件不产生疑似条目（忽略即「不再报警」）
            if self._is_ignored(key):
                skipped_ignored += 1
                continue
            # 与主动扫描同口径：观察期内的条目不得降级为疑似。
            # 否则用户刚请助手补生成（条目被移回观察期、strm 按定义还不存在），
            # 用它自己的文件名查一下就会把它打回疑似 —— 等于把刚做的操作撤销掉。
            if key in self._strm_watch:
                skipped_watching += 1
                continue
            # 与主动扫描同口径：**还在冷却队列里的文件不是异常**（尚未上传，
            # 按定义不可能有 .strm）。这条判据必须在"新增疑似"之前 ——
            # 与全量扫描是同一个误报源，两处口径必须一致。
            if key in (getattr(self, "_pending_queue", None) or {}):
                skipped_cooling += 1
                continue
            if key in self._strm_suspects:
                continue
            self._strm_suspects[key] = {"ts": now_ts, "origin": _strm.ORIGIN_SCAN}
            added += 1
        if added:
            self.save_data("strm_suspects", self._strm_suspects)
            logger.warning(f"[Rsync115Sync] 📺 关键字 strm 检查「{keyword}」："
                           f"命中 {len(result['matched'])} 个，缺 strm {len(missing)} 个，"
                           f"新增疑似 {added} 个: {_brief_paths(missing)}")

        lines = [f"📺 strm 检查「{keyword}」",
                 f"--------------------------------",
                 f"命中文件: {len(result['matched'])} 个",
                 f"✅ 已有 strm: {len(present)} 个",
                 f"❌ 缺 strm  : {len(missing)} 个（新增疑似 {added} 个）"]
        if skipped_cooling:
            lines.append(f"🧊 仍在冷却队列（尚未上传）: {skipped_cooling} 个 —— 未计入疑似")
        if no_strm_dir:
            lines.append(f"⏭️ 所在映射未配 strm 目录，未检查: {len(no_strm_dir)} 个")
        if non_video:
            # 字幕等非视频文件不会有 .strm，本就不该参与检查；明确告知而非静默丢弃
            lines.append(f"⏭️ 非视频文件（字幕等，不会生成 strm），已跳过: {len(non_video)} 个")
        if skipped_watching:
            lines.append(f"⏳ 已在观察期（刚同步成功或已请求补生成），未重复计入疑似: {skipped_watching} 个")
        if skipped_ignored:
            lines.append(f"🚫 命中忽略规则，未计入疑似: {skipped_ignored} 个")
        if missing:
            lines.append("--------------------------------")
            lines.append("缺 strm 的文件：")
            for k in missing[:_MAX_LOGGED_PATHS]:
                lines.append(f"• {k}")
            if len(missing) > _MAX_LOGGED_PATHS:
                lines.append(f"…（共 {len(missing)} 个）")
            lines.append("")
            lines.append("💡 可能是「从未上传」或「上传了但 CD2 假成功」。")
            lines.append("   已在看板「strm 疑似异常」标签内，可勾选批量处理：")
            lines.append("   ① 先点「先尝试生成 strm」，漏生成的话这一步就够了；")
            lines.append("   ② 仍无 strm 再「删旧重传」。")
        self._post_reply(event, "\n".join(lines))

    def _check_watch_now(self, keys: List[str]) -> Dict[str, Any]:
        """
        看板入口：立刻检查指定观察期条目的 strm 是否已生成（**不走巡检节流**）。

        Dashboard entry point: check the given watching entries right now, bypassing
        the sweep's throttle.

        为什么需要它：观察期长达数小时，而用户往往**知道** strm 已经出来了
        （刚跑完助手、或在文件管理器里看到了）。此时唯一的反馈渠道是等下一轮
        巡检（最多 30 分钟），而且巡检还是「全量」的 —— 用户想确认这一个，
        却要等整轮。这里给它一条即时通道。

        ⚠️ 与巡检共用同一套判定，不另写一份：`check_one()` 抽出的正是巡检循环体，
        两处若各写一遍，「手动检查说已生成、自动巡检却仍判观察中」这类分歧迟早出现。
        Shares the exact per-entry judgement with the sweep — a second implementation
        would eventually disagree with it.

        纯本地文件检查，零 115 API，因此**不加执行锁**（不占配额、不与同步冲突）。
        """
        now_ts = time.time()
        grace_secs = _strm.grace_secs_of(self._strm_grace_minutes)
        targets = [k for k in (keys or []) if k in self._strm_watch]
        if not targets:
            return {"success": False, "message": "所选文件已不在观察期（可能已被处理或解除）"}

        changed = False
        entered: List[str] = []          # 本次因到期而转入疑似的 key
        results: List[Dict[str, Any]] = []
        for key in targets:
            # 非视频条目：与巡检同一出口（清理而非转疑似）。走到这里说明它是
            # 旧版本落盘的脏数据 —— 登记闸门已保证新条目不会是非视频文件。
            # 手动检查也不该把它推到疑似清单里，否则用户点一下就多一条永远不消失的记录。
            watchable, _skip_code, skip_text = self._strm_watchable(key)
            if not watchable:
                logger.info(f"[Rsync115Sync] 🧹 清理无效 strm 观察条目（{skip_text}）: {key}")
                self._strm_watch.pop(key, None)
                self._strm_gen_requested.pop(key, None)
                changed = True
                results.append({"key": key, "state": _strm.NOT_WATCHABLE, "clock": ""})
                continue
            # clock 随结果一并回传：调用方要靠它区分「普通观察到期」与
            # 「补生成后仍无」（后者判定硬得多），而这两种状态名都叫 suspect。
            clock = _strm.watch_state_of(
                key, self._strm_watch, self._strm_gen_requested, now_ts)[0]
            state, record = self.check_one(key, now_ts, grace_secs)
            if state == _strm.SETTLED:
                self._strm_watch.pop(key, None)
                self._strm_gen_requested.pop(key, None)
                changed = True
                results.append({"key": key, "state": state, "clock": clock})
            elif state in (_strm.NO_STRM_DIR, _strm.SOURCE_GONE):
                self._strm_watch.pop(key, None)
                self._strm_gen_requested.pop(key, None)
                changed = True
                results.append({"key": key, "state": state, "clock": clock})
            elif state == _strm.SUSPECT:
                # 到期未生成：与巡检同一处置（转疑似 + 通知）
                self._strm_watch.pop(key, None)
                self._strm_suspects[key] = {"ts": now_ts, "origin": _strm.ORIGIN_WATCH}
                entered.append(key)
                changed = True
                results.append({"key": key, "state": state, "clock": clock})
            else:
                results.append({"key": key, "state": state, "clock": clock})
        if changed:
            self.save_data("strm_watch", self._strm_watch)
            self.save_data("strm_suspects", self._strm_suspects)
            self.save_data("strm_gen_requested", self._strm_gen_requested)

        settled = [r["key"] for r in results if r["state"] == _strm.SETTLED]
        suspects = [r["key"] for r in results if r["state"] == _strm.SUSPECT]
        gone = [r["key"] for r in results if r["state"] == _strm.SOURCE_GONE]
        no_dir = [r["key"] for r in results if r["state"] == _strm.NO_STRM_DIR]
        non_video = [r["key"] for r in results if r["state"] == _strm.NOT_WATCHABLE]
        still = [r["key"] for r in results if r["state"] == _strm.WATCHING]

        if settled:
            msg = f"✅ 已生成 strm：{len(settled)} 个，已解除观察"
            if still:
                msg += f"；另有 {len(still)} 个仍未生成，继续等待"
        elif suspects:
            # 两种情况必须分开说：补生成之后仍没有，才是「生成动作做过而仍然
            # 没有」的硬判据；而普通观察到期只说明刮削/生成侧可能有别的毛病。
            # 混成一句话会让用户以为前者已经有了结论，而实际上这次可能压根
            # 没请求过生成。
            gen_base = [r["key"] for r in results
                        if r["state"] == _strm.SUSPECT and r.get("clock") == "gen"]
            if gen_base:
                msg = (f"⚠️ 补生成后仍未见 strm：{len(gen_base)} 个已转入疑似清单 —— "
                       f"生成动作已经做过而指针文件仍不出现，云端确实缺该文件的可能性很高，"
                       f"此时「删旧重传」的正当性比首次疑似充分得多")
            else:
                msg = (f"⚠️ 宽限期已过且仍无 strm：{len(suspects)} 个已转入疑似异常清单"
                       f"（此时才需要判断是否删旧重传）")
        elif gone:
            msg = f"🗑️ 源端文件已不存在：{len(gone)} 个已移出观察（无从验证也无从重传）"
        elif no_dir:
            msg = f"🗑️ 所属映射已取消 strm 目录：{len(no_dir)} 个已移出观察"
        elif non_video:
            # 旧版本落盘的非视频条目：明确告知并说明「本就不该监控」，
            # 否则用户会以为是自己操作不当把条目弄丢了。
            msg = (f"🗑️ 非视频文件（字幕/图片等不会生成 strm）：{len(non_video)} 个已移出观察。"
                   f"这类文件本就不参与 strm 交叉验证 —— 它们没有指针文件是正常的。")
        else:
            # 仍在窗口内：strm 没出来是正常的。用户真正想知道的是「等下去会怎样」，
            # 而唯一能承重的判据只有 strm 本身 —— 所以这里只回答等待规则。
            #
            # ⚠️ 这里曾经会**顺手探一次 CD2 挂载的「云端可见性」**，并据此分三路
            # 给建议（可见/不可见/有残留）。已按需求整条砍掉：挂载视图对
            # 「CD2 看起来正常、云端其实是改名失败的残留」这个主成因根本不可信，
            # 它给出的结论注定有一边是错的，而错的那一边会把用户引向错误动作。
            # 判据收敛成一条：**strm 存在与否**。挂载视图不参与任何判断。
            msg = (f"⏳ 仍未生成 strm（{len(still)} 个），窗口还没到。"
                   f"strm 生成不实时，若刚跑完生成任务请稍等再试。")

        if entered:
            # 手动检查与自动巡检**走同一个通知口径**。
            # 不补这一句的话，用户主动检查反而比什么都不做更安静：条目已经进了
            # 疑似清单，等下一轮巡检时 `_strm_notified` 会被这一次的
            # `_reset_strm_notified_if_clear()` 重置（清单刚由空转非空），
            # 巡检再判时已经没有条目可判了 —— 结果是「谁先发现」决定了要不要通知。
            # The manual path must notify on the same terms as the sweep, or checking
            # first would swallow the alert the sweep would have sent.
            self._notify_strm_suspects(entered)

        if settled or suspects or gone or no_dir:
            self._reset_strm_notified_if_clear()
            logger.info(f"[Rsync115Sync] 📺 手动检查观察期条目：{len(targets)} 个 → "
                        f"已生成 {len(settled)} / 转疑似 {len(suspects)} / "
                        f"清理 {len(gone) + len(no_dir)} / 仍等待 {len(still)}")
        return {"success": True, "message": msg,
                "data": {"settled": settled, "suspects": suspects,
                         "still_watching": still,
                         "removed": gone + no_dir, "results": results}}

    def check_one(self, key: str, now_ts: float, grace_secs: float) -> Tuple[str, Optional[str]]:
        """
        对单个观察期条目做一次探测与判定（**巡检与手动检查的唯一共用实现**）。

        Probe and classify one watching entry — the single shared implementation used
        by both the periodic sweep and the dashboard's manual check.

        调用方负责持久化与通知；本方法只做「探测文件系统 → 交给纯函数判定」。
        抽出来的原因：两处若各写一份，「手动说已生成、巡检仍判观察中」这类
        分歧会随着后续改动逐渐出现，而它极难排查（两边看着都对）。

        ⚠️ 计时基准**不是**固定的同步时刻：被请过补生成的条目改用请求时刻重新
        计时（见 `_rearm_after_gen_request`）。基准由 `strm.watch_state_of` 统一
        解析，看板显示走的是**同一个函数** —— 否则会出现「看板说还剩 5 小时、
        巡检已判到期转疑似」的双钟问题。
        The clock depends on whether the entry was re-armed by a regenerate request;
        both the sweep and the dashboard resolve it through the same helper.
        """
        strm_exists = os.path.exists(self._strm_expected_path(key) or "")
        src_root = _strm.source_root_of(key, self._sync_pairs)
        # 相对路径用前缀匹配还原（`_rel_path_of_key`），否则任务名含冒号时
        # 会把仍在源端的文件判成 source_gone 而清理掉观察记录。
        src_exists = (not src_root) or os.path.exists(
            os.path.join(src_root, _rel_path_of_key(key, self._sync_pairs) or ""))
        base_kind, base_ts = _strm.watch_state_of(
            key, self._strm_watch, self._strm_gen_requested, now_ts)
        # 判定窗口：补生成后换用较短的固定窗口，理由见 strm.REGRACE_HOURS
        window = grace_secs if base_kind == "sync" else _strm.REGRACE_HOURS * 3600
        return _strm.classify_watch(
            key, base_ts, now_ts, window, self._sync_pairs,
            strm_exists=strm_exists, src_exists=src_exists)

    def _rearm_after_gen_request(self, keys: List[str], now_ts: float) -> None:
        """
        补生成请求发出后，把条目从疑似清单移回观察期，并以**请求时刻**重新计时。

        Move the requested entries back to the watch list after the regenerate
        command has actually been sent.

        ⚠️ 与「请求即移动」的旧实现的区别，只在**移动位置**：旧代码在发命令前
        无条件移动，即便助手随后拒收（路径不在它的全量列表里）也已经移走，
        用户看到条目凭空消失。现在由调用方在命令**确实发出之后**才调用本方法，
        且只对真正上了车的 key 调用（见 `_api_strm_generate` 的发送循环）。
        The difference from the old design is *where* the move happens: after the
        command is actually sent, not before — a rejected command must not make the
        entry disappear.

        为什么请求过的条目值得回到观察期：用户要的正是「等一会儿再点一下检查」。
        留在疑似清单里只能靠手动刷新去猜结果，而观察期本身就带着巡检 + 手动检查
        两套现成的判定机制；而且即使一次都不点，宽限期内无人处理，watcher 到期
        仍会把它送回来（此时带着已验证过判别结果的身份），等于**零人工兜底**。
        Re-arming reuses the existing sweep/dashboard checks and guarantees the entry
        comes back on its own if nobody looks at it.
        """
        moved = 0
        for key in keys:
            self._strm_suspects.pop(key, None)
            self._strm_watch[key] = now_ts
            moved += 1
        if moved:
            self.save_data("strm_watch", self._strm_watch)
            self.save_data("strm_suspects", self._strm_suspects)
            logger.info(f"[Rsync115Sync] 📺 {moved} 个条目已从疑似清单移回观察期，"
                        f"按 {_strm.REGRACE_HOURS}h 窗口重新计时（可用「检查 strm」即时查看结果）")

    # ---- 借道 strm 助手补生成 / delegating generation to the helper plugin ----

    def _helper_running(self) -> Tuple[bool, str]:
        """
        助手插件是否在运行。返回 (是否运行, 不运行时的原因)。

        Why check the running state at all: the helper keys its behaviour off its own
        login/session. A plugin that is installed but failed to log in will accept the
        command and do nothing, which from our side looks identical to success.
        """
        if _plugin_manager_cls() is None:
            return False, "宿主未提供插件管理器，无法确认 strm 助手是否在运行"
        try:
            running = _plugin_manager_cls()().running_plugins or {}
        except Exception as e:
            return False, f"读取插件运行态失败：{e}"
        if not running.get(_P115_STRM_HELPER_PLUGIN):
            return False, (f"未检测到运行中的「{_P115_STRM_HELPER_PLUGIN}」插件。"
                           f"请先安装并启用它（本功能借它生成 strm）")
        return True, ""

    def _strm_helper_ready(self) -> Dict[str, Any]:
        """
        看板用：补生成功能是否可用（助手在运行 + 至少一个映射配了网盘目录）。

        Cheap readiness probe so the dashboard can disable the button **and say why**;
        a button that silently does nothing on click is worse than a disabled one.
        """
        ok, reason = self._helper_running()
        if not ok:
            return {"ready": False, "reason": reason}
        configured = [p for p in self._sync_pairs if (p.get("pan_dir") or "").strip()]
        if not configured:
            return {"ready": False, "reason": _P115_PAN_DIR_HINT}
        return {"ready": True, "reason": ""}

    def _helper_accepted_pan_roots(self) -> Tuple[List[str], Optional[str]]:
        """
        读助手「全量同步路径」里的网盘目录，用于**发送前预检**。

        Read the helper's accepted cloud roots, used only to pre-validate.

        ⚠️ 用途边界：这里**只做校验**，绝不参与「网盘目录从哪来」的推导 ——
        参数仍然全部来自本插件用户在映射里显式填的 `pan_dir`（见 strm.pan_dir_of）。
        校验之所以必须做：助手对不在该列表里的路径**直接拒绝**，而它的拒绝提示
        只发给自己那边的用户，本插件拿不到，表现为用户视角的「点了没反应」。
        This is validation only — never a source for the parameter itself.

        **读不到时返回 (空, None) 表示「不阻塞」**：不能因为对方改了字段名就把
        整个功能判死。宁可退化成「照发」（旧行为），也不要让用户完全用不了。
        Returns an empty list with no error when unreadable, so a helper-side rename
        degrades to the old send-anyway behaviour instead of breaking the feature.
        """
        if _plugin_manager_cls() is None:
            return [], None
        try:
            cfg = self.systemconfig.get(f"plugin.{_P115_STRM_HELPER_PLUGIN}") or {}
        except Exception as e:
            logger.warning(f"[Rsync115Sync] 读取助手配置失败，跳过发送前预检: {e}")
            return [], None
        if not isinstance(cfg, dict):
            return [], None
        raw = cfg.get(_P115_PAN_MAPPING_FIELD)
        if not raw:
            return [], None
        return [pan for _, pan in _strm.parse_pan_mappings(raw)], None

    def _send_helper_command(self, pan_path: str) -> bool:
        """
        通过宿主命令总线把 `/p115_strm <网盘路径>` 交给助手插件执行。

        Dispatch `/p115_strm <cloud path>` through the host command bus.

        ⚠️ **不直接调用助手的内部方法**：`/p115_strm` 是它对外注册的命令，
        由宿主解析后转发（`CommandChain.command_event` → `PluginAction`），
        属于稳定契约；直接 import 它的 `service.servicer` 会随对方升级而失效，
        而且是**静默失效** —— 本插件这边看起来一切正常。仓库里的 watchsync /
        agentresourceofficer 都走事件总线，此处保持一致。
        Dispatch through the event bus (the helper's registered command) rather than
        calling its internals: the latter breaks silently on their upgrades.
        """
        try:
            eventmanager.send_event(
                EventType.CommandExcute,
                {"cmd": f"{_P115_STRM_COMMAND} {pan_path}", "source": None, "user": None},
            )
            logger.info(f"[Rsync115Sync] 📺 已请求 strm 助手生成: {pan_path}")
            return True
        except Exception as e:
            logger.error(f"[Rsync115Sync] 请求 strm 助手生成失败（{pan_path}）: {e}")
            return False

    def _api_strm_clear(self) -> Dict[str, Any]:
        """
        清空 strm 疑似清单（含待观察清单）。

        Clear the strm suspect list (and the pending watch list).

        为什么提供「全清」而不是只清无效项：清洗只能识别**结构性**无效
        （非视频/已忽略/源端已删），而用户可能因为 strm 插件本身配置错误
        而积累了一批误报 —— 那些条目在结构上完全合法，只能整体清空重来。
        清空后下次同步/扫描会重新建立清单。
        Structural pruning cannot detect "the whole strm plugin was misconfigured",
        so a full reset must remain available.
        """
        suspects = len(self._strm_suspects)
        watching = len(self._strm_watch)
        # ⚠️ 必须用 `.clear()`，**不能**写 `self._strm_suspects = {}`。
        #
        # 后者会把台账替身**整个换回普通 dict** —— 而那个 dict 不在台账体系里：
        # 之后所有写入只进内存、重建实例即丢失，且台账里那些行永远留在
        # 待处理/观察状态。表现是"点了清空、刷新又回来了"，极难定位。
        # 清空语义是"这个队列空了"，不是"换一个空容器"。
        # `.clear()` on a LedgerMapping deletes that status's rows and keeps the
        # object; rebinding the attribute would silently detach the ledger
        # (writes stop reaching it and the stale rows survive every reload).
        self._strm_suspects.clear()
        self._strm_watch.clear()
        # 补生成标记也一并清掉：它与清单是同一份状态的两种视图，清单都没了
        # 却留着「已请求生成」的标记，会让下一次扫描出的同一条目被误标成
        # 「补生成过仍失败」—— 而实际上根本没请求过。
        self._strm_gen_requested.clear()
        # ⚠️ 这两行调用**保留**，不要因为"台账已经接管了"就删掉：
        # 台账**不可用**时（`_open_store` 失败 → 属性是普通 dict），
        # `save_data` 就是唯一的持久化手段，删了会让降级路径丢数据。
        # 台账可用时它们是冗余的，由 `save_data` 覆盖点静默跳过 ——
        # 判断依据是"值是不是台账替身"，而不是"台账可不可用"，
        # 因此两种情形各走各的路，不需要在调用点做分支。
        # Kept on purpose: in the degraded path (no ledger) save_data *is* the
        # persistence. The override skips them exactly when the value is a mapping.
        self.save_data("strm_suspects", self._strm_suspects)
        self.save_data("strm_watch", self._strm_watch)
        self.save_data("strm_gen_requested", self._strm_gen_requested)
        self._reset_strm_notified_if_clear()
        logger.info(f"[Rsync115Sync] 🧹 已清空 strm 清单：疑似 {suspects} 个 / 待观察 {watching} 个")
        return {"success": True,
                "message": f"已清空 strm 疑似清单（{suspects} 个）与待观察清单（{watching} 个）。"
                           f"下次同步或扫描会重新建立。"}

    def _api_strm_prune(self) -> Dict[str, Any]:
        """只清理无效条目（非视频 / 已忽略 / 源端已删 / 映射取消验证）。"""
        removed = self._prune_invalid_strm_suspects()
        if removed:
            msg = f"已清理 {removed} 个无效条目，剩余 {len(self._strm_suspects)} 个。"
        else:
            msg = f"没有发现无效条目（当前 {len(self._strm_suspects)} 个）。"
        return {"success": True, "message": msg,
                "data": {"removed": removed, "remaining": len(self._strm_suspects)}}

    def _api_strm_ignore(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """
        看板入口：把疑似清单条目加入忽略规则（**精确匹配**）并移出清单。

        Dashboard entry point: add suspect entries to the ignore list (exact match)
        and drop them from the suspect list.

        为什么走 _add_ignore_rule 而不是只把条目从清单里删掉：只删清单的话，
        下一轮同步/巡检会把同一个文件再报一遍 —— 用户的操作等于没做。
        忽略规则才是持久判定，_add_ignore_rule 内部已含「联动清理两个清单 +
        落盘 + 重置通知闩锁」，本接口不复制那份逻辑。

        为什么用精确匹配：key 是「映射名:源端相对路径」，contains 会把同目录
        同名文件（如 S01E01/S01E01.strm 之外的同前缀集）误杀；用户此刻面对的
        是**一个具体条目**，意图就是只忽略它。想扩大范围仍可在「已忽略」清单
        里手动改成 contains 规则。

        护栏与 /strm_retry 同口径：只接受疑似清单内的 key。这既是权限边界
        （不允许构造任意路径写忽略规则），也是 UX 边界 —— 该入口的语义是
        「处理清单里这条误报」，不是通用忽略编辑器。
        """
        keys = body.get("keys") or []
        if not keys:
            return {"success": False, "message": "未指定要忽略的文件"}
        allowed = [k for k in keys if k in self._strm_suspects]
        not_allowed = [k for k in keys if k not in self._strm_suspects]
        if not_allowed:
            logger.warning(f"[Rsync115Sync] strm 忽略请求含非疑似清单条目，已忽略: {not_allowed[:3]}")
        if not allowed:
            return {"success": False, "message": "所选文件不在疑似异常清单中"}

        added, already = [], []
        for key in allowed:
            if self._add_ignore_rule(rule=key, match="exact", created_by="Web", source="strm_dashboard"):
                added.append(key)
            else:
                already.append(key)
        if added:
            msg = (f"已忽略 {len(added)} 个文件（精确匹配），并已从疑似清单移除。\n"
                   f"如需恢复对账，请到「已忽略」清单删除对应规则。")
        else:
            msg = "所选文件均已在忽略清单中，未做改动。"
        return {"success": True, "message": msg,
                "data": {"ignored": added, "already_ignored": already}}

    def _api_strm_check(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """
        看板入口：立即检查观察期条目的 strm 是否已生成。

        Dashboard entry point: check the given watching entries right now.

        ⚠️ 这**不是**纯 `_check_watch_now`：本插件此前只提供"检查观察期"这一条
        通道（见 strm_ops 模块头的说法），而 **v0.3.1 起对账/主动扫描都会检查
        疑似清单**，如果这个端点只转调观察期那一侧，就会出现内部不一致 ——
        最典型的是「只有观察期正确更新，疑似清单纹丝不动」（用户实测反馈过）。
        This shares the suspect check too, otherwise the endpoint would only ever
        keep the watch side correct while the suspect list stayed stale.
        """
        res = self._check_watch_now((body or {}).get("keys") or [])
        if self._strm_suspects:
            self._prune_cooling_suspects()
            resolved = self._prune_resolved_suspects()
            if resolved:
                res["message"] = (res.get("message", "")
                                  + f"\n✅ 另有 {len(resolved)} 个疑似条目的 strm 已生成，"
                                    f"已移出待处理清单。")
                res.setdefault("data", {})["resolved_suspects"] = resolved
        return res

    def _api_strm_scan(self) -> Dict[str, Any]:
        """
        看板入口：主动扫描缺 strm 的文件（纯本地，零 115 API）。

        **不加 `_is_running` 闸门**：扫描只读本地目录、不启动 rsync、不占窗口配额，
        与同步任务互不干扰（`_scan_missed_ingest` 同理）。加闸门反而会让用户在
        同步进行中无法排查问题。
        No execution gate: this reads local directories only and shares no state with
        a running rsync, so blocking it during a sync would only hurt diagnostics.
        """
        return self._strm_scan()

    def _api_strm_generate(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """
        先尝试请 strm 助手补生成指针文件，而不是直接删旧重传。

        Ask the helper plugin to (re)generate the .strm files before resorting to the
        destructive delete-and-retransfer path.

        为什么值得多这一步：疑似清单的两种成因（助手漏生成 / CD2 假成功）在本地
        视角**完全无法区分**，但处理成本差好几个数量级 —— 前者重新生成一次指针
        文件即可，后者要删掉云端文件再完整重传一遍。花一次助手侧的目录遍历换取
        「大概率免掉整轮重传」，是明显划算的交易。而且它同时给出了判别结果：
        生成成功 ⇒ 漏生成；仍然没有 ⇒ 云端确实缺文件，此时删旧重传的正当性反而
        更充分了。
        One helper-side sweep buys a good chance of avoiding a full delete-and-retransfer,
        and it doubles as the discriminator between the two indistinguishable causes.

        ⚠️ 参数由**本插件用户显式配置**的「网盘目录」推导，不读助手配置：
        助手只认它自己 `full_sync_strm_paths` 里的路径，且那两棵树不必同构 ——
        从本地路径反推云端路径在原理上就不成立（详见 strm.pan_dir_of 的说明）。
        The cloud path comes from our own explicit config, never from reverse-mapping
        the helper's config: the helper only accepts paths in its own full-sync list,
        and the local/cloud trees are not required to correspond.

        只接受已在疑似清单中的 key（与 /strm_retry 同一道越权护栏）。
        """
        keys = (body or {}).get("keys") or []
        if not keys:
            return {"success": False, "message": "未指定要补生成的文件"}
        allowed = [k for k in keys if k in self._strm_suspects]
        not_allowed = [k for k in keys if k not in self._strm_suspects]
        if not_allowed:
            logger.warning(f"[Rsync115Sync] strm 补生成请求含非疑似清单条目，已忽略: "
                           f"{not_allowed[:3]}")
        if not allowed:
            return {"success": False, "message": "所选文件不在疑似异常清单中"}

        ok, reason = self._helper_running()
        if not ok:
            return {"success": False, "message": reason}

        dirs, matched, unmatched, truncated = _strm.gen_targets_for_suspects(
            allowed, self._sync_pairs, STRM_GEN_DIR_LIMIT)

        if not dirs:
            return {"success": False,
                    "message": "所选文件所属的映射都没有配置「网盘目录」，无法定位云端路径：\n"
                               + "\n".join(f"• {k}" for k in unmatched[:_MAX_LOGGED_PATHS])
                               + f"\n{_P115_PAN_DIR_HINT}"}

        # ⚠️ **发送前预检**：助手只接受它 full_sync_strm_paths 里的网盘路径，
        # 不在列表里的会被它拒绝（用户实测：`匹配目录失败，请检查输入路径和插件配置！`）。
        # 若不预检，命令发出去必然失败，而**失败提示只发给助手侧用户**，本插件
        # 完全看不到 —— 用户看到的是「点了按钮，疑似条目消失了，然后什么都没发生」。
        # 提前拦下并把助手的配置状态摆出来，是本插件唯一能给出有用信息的位置。
        # Pre-flight: the helper rejects any path outside its own full-sync list, and
        # its rejection notice never reaches us. Catching it here is the only point
        # where we can tell the user anything actionable.
        accepted, accepted_err = self._helper_accepted_pan_roots()
        if accepted_err:
            return {"success": False, "message": accepted_err}
        # ⚠️ `accepted` 为空 = **未知**，不是「什么都不接受」。
        # 早先写成无条件过滤时踩了这个坑：读不到助手配置（对方改了字段名、
        # 或本插件读配置失败）会让**每一个**目录都被判为「不在列表里」，
        # 于是功能整体失效 —— 恰好是预检想避免的、却更严重的一种失败。
        # 空列表必须跳过预检，退回「照发」的旧行为。
        # An empty list means "unknown", not "nothing allowed": filtering against it
        # would reject every path and disable the whole feature.
        rejected = ([d for d in dirs if not _strm.is_under_any(d, accepted)]
                    if accepted else [])
        if rejected:
            listed = "\n".join(f"• {d}" for d in rejected[:_MAX_LOGGED_PATHS])
            return {"success": False,
                    "message": f"这些网盘目录不在 P115StrmHelper 的「全量同步路径」里，"
                               f"发过去会被它拒绝（未发出任何命令）：\n{listed}\n\n"
                               f"该助手只接受它自己「全量同步路径」中的路径。\n"
                               f"它当前配置的网盘目录：\n"
                               + "\n".join(f"• {p}" for p in accepted[:_MAX_LOGGED_PATHS])
                               + f"\n\n请在助手配置页为这些网盘目录补上对应映射行，"
                                 f"或在本插件里把该映射的「网盘目录」改成上面已有的路径。"}

        # ⚠️ 上限命中时**整批拒绝**，而不是「处理前 N 个、剩下的留给用户猜」。
        # 达到上限说明疑似条目已散布到很多目录，此时逐目录触发的总开销可能已超过
        # 一次整库遍历 —— 该由用户明确决策，插件不该自动放大对 115 的访问量。
        # Refuse the whole batch when the directory cap is hit: at that point the
        # per-directory cost has likely outgrown a single full sweep, and silently
        # truncating would leave the user believing the whole list was handled.
        if truncated:
            return {"success": False,
                    "message": f"本次涉及 {len(dirs)}+ 个不同目录，超过单次上限 "
                               f"{STRM_GEN_DIR_LIMIT} 个，已整批拒绝（未发出任何命令）。\n"
                               f"达到这个量级时逐个目录触发已不划算，请先缩小范围：\n"
                               f"• 用「清理无效项」移除已不可能恢复的条目\n"
                               f"• 或在看板上勾选一部分（同一目录的会更划算）分批处理\n"
                               f"• 若确实是一批文件上传失败，直接用「删旧重传」更合适"}

        sent_dirs = [target for target in dirs if self._send_helper_command(target)]
        if not sent_dirs:
            return {"success": False,
                    "message": "补生成命令发送失败（宿主事件总线不可用），请查看日志"}
        # 逐条反查「哪些 key 的目录确实上了车」。用 sent_dirs 而不是 dirs：
        # 发送是逐目录调用的，某一目录失败时若仍按全量收尾，它下面的文件会被
        # 移进观察期 —— 而那条命令根本没发出去，用户会在窗口内等一个永远不会
        # 到来的结果。这里与发送循环共用 strm.gen_target_of_key 的推导，
        # 保证「发出去的是什么」与「认为覆盖了什么」不可能分叉。
        sent_set = set(sent_dirs)
        matched = [k for k in allowed if _strm.gen_target_of_key(k, self._sync_pairs) in sent_set]

        # 只有**确实发过命令**的条目才允许离场。
        #
        # 这里的历史坑值得留一笔：最早的做法是「请求即移入观察期」，而移动发生在
        # 发命令之前，于是助手拒收（路径不在它的全量列表里）时条目照样消失，
        # 用户看到「点了一下，东西不见了」，宽限期到它又带着「补生成无效」回来
        # （助手那边其实打印的是「匹配目录失败」）。那个设计错在**把「命令已发出」
        # 当成了「生成已执行」**，并顺着这个错误结论把好文件推去删旧重传。
        #
        # 现在两道闸门：发送前预检拦掉必然被拒的路径；发送后按「实际发出命令的
        # 目录」反查命中哪些 key，只有它们才移回观察期。没上车的条目原样留在
        # 疑似清单，用户仍能看到并操作。
        # Only entries whose directory actually got a command may leave the suspect
        # list; anything the helper would have rejected is still sitting there.
        now_ts = time.time()
        for key in matched:
            self._strm_gen_requested[key] = now_ts
        self.save_data("strm_gen_requested", self._strm_gen_requested)
        self._rearm_after_gen_request(matched, now_ts)

        logger.info(f"[Rsync115Sync] 📺 已请 strm 助手补生成：{len(sent_dirs)} 个目录 / "
                    f"{len(matched)} 个文件（已移回观察期，等待结果）")
        msg = (f"已向 strm 助手发出 {len(sent_dirs)} 条补生成命令，覆盖 {len(matched)} 个文件，"
               f"它们已移回「观察中」。\n"
               f"• strm 助手会按目录遍历云端并重新生成指针文件\n"
               f"• strm 一出现就自动判为正常；若 {_strm.REGRACE_HOURS:g} 小时后仍未出现，"
               f"会回到疑似清单（此时才是「生成过仍没有」，判定更硬）\n"
               f"• 不必干等：在观察期点「检查 strm」即可立即比对结果\n"
               f"• 若助手报「匹配目录失败」，说明该网盘路径不在它的「全量同步路径」里，"
               f"请在助手配置页补上（详见配置页说明）\n"
               f"助手是异步长任务，生成需要时间。\n\n"
               # ⚠️ 这里曾有一整段「云端可见性」的说法（「看板会给出探测结论帮你
               # 区分「可见且大小一致」…」）。那套判定已在 v0.3.0 整条删除 ——
               # 它对**改名失败**这个主成因必然判错（残留与正式文件字节数相同，
               # 挂载视图照样显示「可见、大小一致」），留着这段文案等于承诺一个
               # 不存在的功能，而且它给的"先别删"建议正是被证明会把人引向错误
               # 动作的那一条。现在只说**唯一成立的判据**。
               f"若窗口到了仍没有 strm，说明这次上传没有真正完成，"
               f"直接「删旧重传」即可：\n"
               f"• .strm 是助手在视频**正确上传后**才生成的，它不出现就是判据本身\n"
               f"• 云端没有文件时删除是空操作，不会白删\n"
               f"• 传过一半 / 只剩改名失败残留的情况，删旧重传也都是对症的")
        if unmatched:
            msg += (f"\n\n⚠️ 另有 {len(unmatched)} 个文件本次未处理"
                    f"（所属映射未配置「网盘目录」），它们仍留在疑似清单中。")
        return {"success": True, "message": msg,
                "data": {"dirs": sent_dirs, "requested": len(matched),
                         "unmatched": unmatched[: _MAX_LOGGED_PATHS],
                         "unmatched_count": len(unmatched)}}

    def _api_strm_retry(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """
        确认后对疑似异常执行「删旧重传」（复用 v0.1.4 的删旧通道）。

        Confirmed re-transfer for strm suspects, reusing the delete-then-sync path.
        不做无确认的自动重传：strm 插件自身漏生成也会表现为"该有而没有"，
        误报源无法排除，删除是破坏性操作，必须用户确认。

        判据只有一条：**待处理清单里没有对应 strm**。挂载视图不参与判断 ——
        它对 CD2 改名失败这个主成因给出的结论恰好是错的（详见下方说明）。
        The only criterion is the missing strm; the mount view is never consulted.
        """
        if self._is_running:
            return {"success": False, "message": "已有任务正在运行，请稍后再试"}
        keys = body.get("keys") or []
        if not keys:
            return {"success": False, "message": "未指定要重传的文件"}
        # 只允许对疑似清单里的 key 操作，防止越权构造任意路径
        allowed = [k for k in keys if k in self._strm_suspects]
        not_allowed = [k for k in keys if k not in self._strm_suspects]
        if not_allowed:
            logger.warning(f"[Rsync115Sync] strm 重传请求含非疑似清单条目，已忽略: {not_allowed[:3]}")
        if not allowed:
            return {"success": False, "message": "所选文件不在疑似异常清单中"}

        # 这里曾经有一道「云端可见性复探」的守卫：删之前重探 CD2 挂载，判成
        # 「可见且大小一致」就整批拦下并要用户二次确认（`needs_force`），
        # 另有一条 `origin == confirmed` 的越权通道专门用来推翻它。
        #
        # 已整条删除，理由是那道守卫**在最该放行的主成因上必然拦人**：
        # CD2 改名失败时挂载视图照样显示「可见、大小一致」（残留与正式文件
        # 字节数相同），于是插件告诉用户「文件很可能是好的、别删」，
        # 而真相恰恰相反。判据只能来自 strm —— 它不存在，就该走删旧重传。
        # The old re-probe guard blocked exactly the case it was meant to allow:
        # a rename-failure residue is byte-identical in size, so the mount reports
        # "visible and same size" for a file that is not usable at all.
        # ---- 删旧**之前**先确认这轮传得动 ----
        #
        # 顺序是承重的：先删后传的实现里，任何一条前置闸门（执行锁、风控退避、
        # 窗口配额、目录未就绪）都会让**文件已经被删掉、却没有重传**。
        # 用户看到的却是「已删除 N 个文件并开始定向重传」——因为看板这条路径
        # 不传 channel_event，`_post_reply` 直接 return，`_execute_sync` 里所有
        # 拦截都是静默的（用户实测「似乎没有重传」的成因之一）。
        # 先做只读预检，把「删了却传不了」变成「根本不会删」。
        # Pre-flight: every gate inside _execute_sync would otherwise fire *after*
        # the delete, leaving the file gone with no retry and no visible error.
        blocked_reason = self._retry_preflight([])
        if blocked_reason:
            logger.warning(f"[Rsync115Sync] ⛔ 删旧重传未执行（{blocked_reason}），未删除任何文件")
            return {"success": False,
                    "message": f"本次删旧重传未执行，未删除任何文件。\n\n原因：{blocked_reason}\n\n"
                               f"（先把这道闸门挡在前面，是为了避免「文件已删、却没传上去」"
                               f"—— 等条件满足后重新点即可。）"}

        deleted, undeletable = self._delete_dest_files_for_retry(allowed)
        if undeletable:
            return {"success": False,
                    "message": f"{len(undeletable)} 个文件目标端删除失败（挂载点可能未就绪），请稍后重试"}
        # 重传期间仍留在疑似清单（失败会被同步流程记入异常清单）；
        # 成功后由 _strm_arm_watch 解除
        self._start_sync_thread(mode="retry", custom_files=deleted)
        return {"success": True,
                "message": f"已删除 {len(deleted)} 个文件并开始定向重传，完成后自动复核 strm"}

    def _search_target_files(self, keyword: str) -> Dict[str, Any]:
        """
        按关键字在**源端**查找文件（供 /rsync_retry <文件名> 与忽略序号复用）。

        Search the *source* roots by keyword, reused by keyword-retry and
        index-based ignore.

        与 /rsync_search 的差异：
        - 带上限并上报是否截断（retry 用「超限即拒」策略，search 用「截断展示」策略）；
        - 关键字命中后不直接采用 —— 删除目标端是破坏性操作，必须由调用方再做
          一次「相对路径精确对齐」校验（见 _delete_dest_files_for_retry）。
        口径与同步/补传一致：按映射扩展名过滤、就地裁剪排除目录、零 115 API。
        """
        keyword = keyword.strip().lower()
        matched: List[str] = []
        truncated = False
        for pair in self._sync_pairs:
            src_dir = (pair.get("src") or "").strip().rstrip("/")
            pair_name = _pair_name(pair)
            if not os.path.exists(src_dir):
                continue
            all_ext = pair.get("all_ext", False)
            valid_exts = _valid_exts_of(self._media_extensions, all_ext)
            excluded_dirs = _excluded_dir_names(self._exclude_patterns)
            for root, dirs, files in os.walk(src_dir):
                dirs[:] = [d for d in dirs if d not in excluded_dirs]
                for f in files:
                    if keyword not in f.lower():
                        continue
                    if valid_exts is not None and \
                            os.path.splitext(f)[-1].lstrip(".").lower() not in valid_exts:
                        continue
                    rel_f = os.path.relpath(os.path.join(root, f), src_dir)
                    matched.append(f"{pair_name}:{rel_f}")
                    if len(matched) > _RETRY_KEYWORD_LIMIT:
                        # 超过上限立即停：retry 是删了重传，宁可不执行也不宜大范围误伤
                        truncated = True
                        break
                if truncated:
                    break
            if truncated:
                break
        return {"matched": matched, "truncated": truncated,
                "total": len(matched) + (1 if truncated else 0) if truncated else len(matched)}

    def _retry_preflight(self, keys: List[str]) -> str:
        """
        删旧重传的前置预检：能传才让删。返回阻塞原因（空串=可执行）。

        Read-only pre-flight for delete-then-retransfer. Returns "" when the run
        would actually happen, otherwise a human-readable reason.

        **为什么必须放在删除之前**：先删后传的每一步前置闸门都住在
        `_execute_sync` 里 —— 执行锁、风控退避、窗口配额、映射目录未就绪。
        它们在删除**之后**才判，一旦命中就是「文件已经从云端删掉、却没有重传」，
        而看板这条路径不传 `channel_event`，`_post_reply` 直接 return，
        所以连一句提示都发不出来（用户实测「似乎没有重传」即此）。
        把闸门搬到前面，最坏结果是「没删也没传」，用户重试即可 ——
        与「删了没传」相比，这是能接受的失败形态。
        The gates live inside _execute_sync, i.e. *after* the delete. Moving the same
        checks in front turns "deleted but never uploaded" (unrecoverable, silent)
        into "nothing happened, try again" (safe).

        ⚠️ 与 `_execute_sync` 的判据**不能漂移**：这里只做只读判断，真正的执行
        仍由那边的闸门决定。这里放行、那边拦下，仍是「删了没传」；因此两处引用
        的是同一批状态（`_rate_limit_allows` 就是那边用的那个函数）。
        Reuses `_rate_limit_allows` — the very function the run itself calls — so the
        two cannot disagree.
        """
        if not shutil.which("rsync"):
            return "系统未安装 rsync 命令（请在容器内执行 apt install -y rsync）"
        if not self._sync_pairs:
            return "未配置任何同步目录对"
        # 执行锁：`_execute_sync` 拿不到锁就整轮 return，而删除已经发生。
        # ⚠️ `getattr` 兜底而不是直接取属性：`_lock` 由 `init_plugin` 建立，
        # 而本方法也被裸实例（测试、以及任何在初始化前调用到的路径）走到 ——
        # 一个缺失的属性会抛异常，把「预检」变成「删除前的新故障点」。
        lock = getattr(self, "_lock", None)
        if lock is not None:
            if not lock.acquire(blocking=False):
                return "当前已有同步任务正在运行，请等它结束后再试"
            lock.release()
        # ⚠️ 预检是**尽力而为**的附加保护，绝不能自己变成一个新的故障点：
        # 它引用的状态（限流计数、窗口配置……）都由 `init_plugin` 建立，
        # 而本方法在任何初始化不完整的路径上也可能被走到。任何异常都按
        # 「放行」处理并记日志 —— 预检的职责是**把已知的阻塞提前说出来**，
        # 不是发明新的阻塞。真要说「最坏情况」，放行等于回到改动前的行为，
        # 而不放行会让重传永久不可用。
        # Best-effort only: any failure here means "proceed", never "block".
        try:
            allowed, reason = self._rate_limit_allows()
            if not allowed:
                return reason
            # 映射目录未就绪：`_execute_sync` 会 `continue` 掉这一组，同样什么都不传
            ready = [p for p in self._sync_pairs
                     if os.path.exists((p.get("src") or "").strip().rstrip("/"))
                     and os.path.exists((p.get("dest") or "").strip().rstrip("/"))]
            if not ready:
                return ("所有映射的源目录或目标端（CD2 挂载）都不可用 —— "
                        "请检查挂载是否正常，此时重传不会发生")
        except Exception as e:
            logger.warning(f"[Rsync115Sync] 删旧重传预检异常（按放行处理）: {e}")
        return ""

    def _delete_dest_files_for_retry(self, keys: List[str]) -> Tuple[List[str], List[str]]:
        """
        重传前删除目标端文件（经 CD2 挂载），返回 (已删除, 删除失败) 两组 key。

        Delete destination files via the CD2 mount before re-transfer.

        护栏（破坏性操作的三道闸）：
        1. **相对路径精确对齐**：key 形如 "任务名:相对路径"。只有当源端文件存在、
           且其相对路径映射到目标端的绝对路径后，才删**那一个**路径。
           关键字只用于搜源端，绝不参与目标端路径的构造 —— 不会出现"按关键字
           删掉一批相近文件"的情况。
        2. **删除前后都记录大小**：删前若目标端文件不存在则无需删除（直接可传）；
           若存在，记录大小并核对删除后确实消失。
        3. **删除后复查**：rm 失败或复查仍存在（CD2 缓存未失效）时归入
           "删除失败"，调用方必须跳过这些文件 —— 带着脏视图去 rsync 会被
           --size-only 跳过，白白消耗限流配额。

        绝不触碰 `..` 中缀的云端残留：本函数只按「源端相对路径 → 目标端同路径」
        精确删除正式文件，残留不在任何源端清单里，天然不会被选中。
        """
        deleted: List[str] = []
        undeletable: List[str] = []
        for key in keys:
            # 解析 "任务名:相对路径"，并找到该任务的目标根目录
            pair = None
            pair_name = None
            rel_p = None
            for p in self._sync_pairs:
                pn = _pair_name(p)
                if key.startswith(f"{pn}:"):
                    pair = p
                    pair_name = pn
                    rel_p = key.split(f"{pn}:", 1)[1]
                    break
            if pair is None or not rel_p:
                # 无前缀 key（理论上 retry custom_files 不会出现）保守跳过
                logger.warning(f"[Rsync115Sync] 重传前清理：key 无法归属映射，跳过删除: {key}")
                undeletable.append(key)
                continue

            dest_root = (pair.get("dest") or "").strip().rstrip("/")
            src_root = (pair.get("src") or "").strip().rstrip("/")
            src_file = os.path.join(src_root, rel_p)
            dest_file = os.path.join(dest_root, rel_p)

            # 护栏：源端必须真实存在才允许继续（防路径解析异常导致误删别处文件）
            if not os.path.isfile(src_file):
                logger.warning(f"[Rsync115Sync] 重传前清理：源端不存在，跳过删除: {src_file}")
                undeletable.append(key)
                continue

            dest_size = None
            try:
                if os.path.exists(dest_file):
                    dest_size = os.path.getsize(dest_file)
            except OSError as e:
                logger.warning(f"[Rsync115Sync] [{pair_name}] 目标端大小读取失败（继续尝试删除）: "
                               f"{dest_file}: {e}")

            if dest_size is None:
                # 目标端本就没有正式文件：无需删除，可直接重传。
                #
                # ⚠️ 这里曾经顺带调用 `_remove_dest_residues()` 去清同目录里
                # `.<正式名>.<随机后缀>` 的残留。那条通道随「云端可见性」整套
                # 一起删除了：它是为**展示**（避免清单上永远挂着「有残留」
                # 注记）而存在，并非重传本身需要的动作 —— 删旧重传的判据是
                # 「strm 不存在」，与残留无关，重传照样会发生。
                logger.info(f"[Rsync115Sync] [{pair_name}] 目标端无正式文件，无需清理，直接重传: {rel_p}")
                deleted.append(key)
                continue

            try:
                os.remove(dest_file)
            except OSError as e:
                logger.error(f"[Rsync115Sync] [{pair_name}] ❌ 目标端删除失败，该文件本轮跳过: "
                             f"{dest_file}: {e}")
                undeletable.append(key)
                continue

            # 删除后复查：CD2 可能因缓存/瞬时错误「假删」，仍存在则视为失败
            still_there = False
            try:
                still_there = os.path.exists(dest_file)
            except OSError:
                still_there = False
            if still_there:
                logger.error(f"[Rsync115Sync] [{pair_name}] ❌ 目标端删除后仍存在（CD2 视图未失效），"
                             f"该文件本轮跳过: {dest_file}")
                undeletable.append(key)
                continue

            # （清理同目录残留的动作随「云端可见性」整套删除，见上）
            logger.info(f"[Rsync115Sync] [{pair_name}] 🧹 已删除目标端待重传文件: {rel_p} "
                        f"（删前大小 {dest_size} 字节）")
            deleted.append(key)
        return deleted, undeletable
