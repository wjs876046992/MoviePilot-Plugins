"""
CD2 上传队列查询的插件侧接线：把「人工去 CD2 确认」变成一步自动判断。

Plugin-side wiring for the CloudDrive2 upload-queue check, replacing the manual
"go look at the CD2 UI before deleting anything" step.

## 它解决的问题（不是优化，是一个自我维持的破坏环路）

本插件的疑似判据是「rsync 报成功，宽限期内没有 .strm」。默认宽限期 5 分钟，
而一条 8 GB 的文件在 CD2 侧要传几十分钟。于是：

    同步报成功 → 5 分钟后判疑似 → 用户点「删旧重传」
    → 删掉**正在上传**的文件 → 从零重传 → 又传不完 → 又判疑似 → …

每一轮循环都真实地浪费掉已经传完的那几个 GB。用户的原话：
「存在需要真实上传的，也会放疑似，不清楚情况时会一直删除一直重传，
目前我是人工去 cd2 确认的」。
Each lap genuinely discards the gigabytes already uploaded.

## 设计边界（为什么只做「降噪」）

查询结果**只**用于三件事，绝不用于判定上传成功：

  1. 条目明明在上传队列里 ⇒ 不转疑似、不发通知（它只是慢，不是坏）；
  2. 已在疑似清单里但此刻开始传了 ⇒ 移出清单，附进度说明；
  3. 「删旧重传」前拦截：正在传的文件拒绝删除，并告知进度与预计。

⚠️ 「查不到」**什么都不改变** —— 仍按原判据处理。这条区别是承重的：
把「不在队列里」当成「上传失败」或把「在队列里」当成「上传成功」，都会
重蹈 v0.3.0 删掉的「云端可见性」错判（见 DEVELOPMENT §3.11）。
"Not found" changes nothing. Only "definitely in flight" suppresses action —
absence proves nothing, exactly as with the removed cloud-visibility verdict.

## 失败姿态

**默认关闭**。开启后任何失败（地址错、token 过期、CD2 没开）都降级为
「按原判据处理」，并限频记一条 warning —— 绝不因为查不到就放行，
也绝不因为查不到就全部判成疑似。
Failures degrade to the original criterion, never to "allow" and never to "flag all".
"""

import time
from typing import Any, Dict, List, Optional

from app.sdk.logging import logger

from . import cd2 as _cd2   # noqa: E402
from . import store as _store_mod   # noqa: E402
from .constants import (    # noqa: E402
    CD2_API_URL_DEFAULT as _CD2_API_URL_DEFAULT,
    CD2_FAILURE_BACKOFF_SECS as _CD2_FAILURE_BACKOFF_SECS,
    CD2_QUERY_CACHE_SECS as _CD2_QUERY_CACHE_SECS,
    CD2_QUERY_ENABLED_DEFAULT as _CD2_QUERY_ENABLED_DEFAULT,
    MAX_LOGGED_PATHS as _MAX_LOGGED_PATHS,
)
from .paths import (        # noqa: E402
    brief_paths as _brief_paths,
)


class Cd2OpsMixin:
    """
    CD2 上传队列查询。无状态：全部运行时数据挂在插件实例上。

    ⚠️ 本 Mixin 必须保持**零模块级赋值**（拆分红线，见 test_split_contract）：
    宿主按实例重建命名空间时，模块级可变状态会被不同分身共用。
    """

    def _cd2_enabled(self) -> bool:
        """CD2 查询是否已启用且配置完整。"""
        return bool(getattr(self, "_cd2_query_enabled", False)) and bool(
            (getattr(self, "_cd2_api_url", "") or "").strip())

    def _cd2_settings(self) -> Dict[str, str]:
        """取当前 CD2 连接参数（地址与 token 一律 strip）。"""
        return {
            "url": (getattr(self, "_cd2_api_url", "") or "").strip().rstrip("/"),
            "token": (getattr(self, "_cd2_api_token", "") or "").strip(),
        }

    def _cd2_in_backoff(self) -> bool:
        """是否处于连接失败后的静默期。"""
        until = float(getattr(self, "_cd2_backoff_until", 0.0) or 0.0)
        return time.time() < until

    def _cd2_note_failure(self, reason: str) -> None:
        """
        记一次失败并进入静默期。

        为什么要静默期：CD2 没开或 token 过期时，一次巡检可能问几十条，
        每条都打一次 HTTP + 记一条 warning —— 既拖慢判定路径又刷屏日志，
        而信息量与一条完全相同。
        A back-off keeps a misconfigured address from becoming one warning per entry.
        """
        self._cd2_backoff_until = time.time() + _CD2_FAILURE_BACKOFF_SECS
        self._cd2_last_error = reason
        logger.warning(
            f"[Rsync115Sync] ⚠️ CD2 上传队列查询失败，{_CD2_FAILURE_BACKOFF_SECS // 60} 分钟内"
            f"不再尝试（本次按原判据处理，不影响同步）: {reason}")

    def _cd2_uploads(self, force: bool = False) -> Optional[List[Dict[str, Any]]]:
        """
        取 CD2 当前上传任务列表；不可用时返回 None（调用方须按「查不到」处理）。

        返回值语义**严格三态**，调用方不能把 None 与 [] 混为一谈：
          · None —— 查不了（未启用/失败/静默期）。**不改变任何判定**；
          · []   —— 查到了，队列就是空的。可以据此确认「没在传」；
          · [...] —— 查到了任务列表（含已完成/失败，由调用方按状态筛）。

        ⚠️ `None` 与 `[]` 的区别是本模块的全部价值所在。合成一个值会让
        「CD2 没开」被当成「队列为空」，进而让本该降噪的条目照旧报警 ——
        功能看起来在工作，实际一次都没生效。
        None means "unknown" and must never collapse into [] ("nothing queued").
        """
        if not self._cd2_enabled():
            return None
        now = time.time()
        cache = getattr(self, "_cd2_cache", None)
        if not force and isinstance(cache, dict):
            if now - float(cache.get("ts") or 0.0) < _CD2_QUERY_CACHE_SECS:
                return cache.get("uploads")
        if self._cd2_in_backoff():
            return None

        settings = self._cd2_settings()
        try:
            uploads = _cd2.fetch_upload_queue(settings["url"], settings["token"])
        except _cd2.CloudDrive2Error as exc:
            self._cd2_note_failure(str(exc))
            self._cd2_cache = {"ts": now, "uploads": None}
            return None
        except Exception as exc:      # 兜底：任何解析异常都不该打断巡检
            self._cd2_note_failure(f"{type(exc).__name__}: {exc}")
            self._cd2_cache = {"ts": now, "uploads": None}
            return None

        # 成功后清掉静默期与错误记录，看板据此显示"已恢复"
        self._cd2_backoff_until = 0.0
        self._cd2_last_error = ""
        self._cd2_cache = {"ts": now, "uploads": uploads}
        return uploads

    def _cd2_mount_map(self, force: bool = False) -> Optional[Dict[str, str]]:
        """
        取 CD2 挂载映射 {本地挂载点: 云端目录}；不可用时返回 None。

        与上传列表同一套缓存/静默期：两者一次查询成本相近，
        且都用同一次「CD2 到底通不通」的判断。
        Cached separately from the upload list because mount points change rarely.
        """
        if not self._cd2_enabled():
            return None
        now = time.time()
        cache = getattr(self, "_cd2_mount_cache", None)
        if not force and isinstance(cache, dict):
            if now - float(cache.get("ts") or 0.0) < _CD2_QUERY_CACHE_SECS * 10:
                return cache.get("mounts")
        if self._cd2_in_backoff():
            return None

        settings = self._cd2_settings()
        try:
            mounts = _cd2.fetch_mount_map(settings["url"], settings["token"])
        except _cd2.CloudDrive2Error as exc:
            self._cd2_note_failure(str(exc))
            self._cd2_mount_cache = {"ts": now, "mounts": None}
            return None
        except Exception as exc:
            self._cd2_note_failure(f"{type(exc).__name__}: {exc}")
            self._cd2_mount_cache = {"ts": now, "mounts": None}
            return None

        self._cd2_mount_cache = {"ts": now, "mounts": mounts}
        return mounts

    def _cd2_ages(self, keys: List[str]) -> Dict[str, float]:
        """
        估算每个 key **已经等了多久**（秒），供豁免期限判定使用。

        取两个来源里更早的那个：
          · 观察期登记时刻（`_strm_watch[key]`）—— 从同步成功算起；
          · 疑似时刻（`_strm_suspects[key]["ts"]`）—— 从首次疑似算起。
        一个条目可能两者都有记录（先观察、后转疑似、又被移回），取更早的
        才是"它到底挂了多久"的正确下界。

        ⚠️ 为什么必须估这个值：CD2 不报上传开始时间，所以"卡住"只能由
        **本地已等待时长**推断。传 0 会让卡死任务被无限期豁免（真问题被藏起来），
        传常数会让正常上传被误报 —— 两个方向都不可接受。
        CD2 does not report upload start times, so staleness must come from local
        waiting time; both extremes (0 or a constant) are wrong.
        """
        now = time.time()
        ages: Dict[str, float] = {}
        watch = getattr(self, "_strm_watch", {}) or {}
        suspects = getattr(self, "_strm_suspects", {}) or {}
        for key in keys:
            stamps = []
            if key in watch:
                try:
                    stamps.append(float(watch[key]))
                except (TypeError, ValueError):
                    pass
            entry = suspects.get(key) if hasattr(suspects, "get") else None
            if isinstance(entry, dict) and entry.get("ts") is not None:
                try:
                    stamps.append(float(entry["ts"]))
                except (TypeError, ValueError):
                    pass
            if stamps:
                ages[key] = max(0.0, now - min(stamps))
            else:
                # 两个清单都没有（例如命令侧直接点名一个不在清单里的 key）：
                # 当作"刚发现"，即**放行豁免** —— 宁可压一轮也不要把正在传的删掉。
                ages[key] = 0.0
        return ages

    def _cd2_in_flight_for(self, keys: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量查询哪些 key 此刻**正在上传**，返回 {key: 上传任务详情}。

        查不了时返回**空字典** —— 调用方据此「什么都不改变」。这与
        `_cd2_uploads` 的三态不同：这里只关心"确认为在传的有哪些"，
        「不知道」和「没在传」在这条路径上的处理完全一致（都保持原判）。
        Both "unknown" and "none in flight" leave the verdict untouched, so they
        collapse safely here (unlike at the caller of _cd2_uploads).

        ⚠️ 结果**再按豁免期限过滤一次**：一条卡在 CD2 里不动的任务必须在
        `CD2_SUPPRESS_MAX_HOURS` 之后失去豁免，否则它会把真故障永久藏起来。
        见 `cd2.should_suppress` 的说明。
        """
        if not keys or not self._cd2_enabled():
            return {}
        uploads = self._cd2_uploads()
        if not uploads:
            return {}
        mounts = self._cd2_mount_map()
        ages = self._cd2_ages(keys)
        hits: Dict[str, Dict[str, Any]] = {}
        expired: List[str] = []
        for key in keys:
            candidates = _cd2.dest_paths_for_key(key, getattr(self, "_sync_pairs", []), mounts)
            matched = _cd2.find_in_flight(candidates, uploads)
            if not matched:
                continue
            if _cd2.should_suppress(matched[0], ages.get(key, 0.0)):
                hits[key] = matched[0]
            else:
                expired.append(key)
        if expired:
            logger.warning(
                f"[Rsync115Sync] ⏳ {len(expired)} 个条目在 CD2 上传队列里停留超过 "
                f"{_cd2.CD2_SUPPRESS_MAX_HOURS:g} 小时仍未完成，"
                f"【不再按「上传中」豁免】（很可能任务已卡死，请到 CD2 网页确认）: "
                f"{_brief_paths(expired)}")
        return hits

    # ---- 三个使用点 ----

    def _cd2_suppress_new_suspects(self, keys: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        从「即将转为疑似」的列表里剔除仍在上传的，返回 {被剔除的 key: 详情}。

        用于 `_strm_check`：条目到期但 CD2 显示还在传 ⇒ 让它继续留在观察期，
        而不是转疑似。**只影响报警，不伪造成功** —— 它仍在观察期，下一轮继续判。
        Kept in the watch list rather than flagged; it is not marked as success.
        """
        in_flight = self._cd2_in_flight_for(keys)
        if in_flight:
            logger.info(
                f"[Rsync115Sync] ⏳ {len(in_flight)} 个条目宽限期已到，但 CD2 显示仍在上传中，"
                f"本轮不转疑似: "
                f"{'; '.join(f'{k}（{_cd2.progress_text(v)}）' for k, v in list(in_flight.items())[:_MAX_LOGGED_PATHS])}")
        return in_flight

    def _cd2_hold_failed_settlement(self, keys: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        从「即将判为对账失败」的列表里剔除仍在上传的，返回 {被剔除的 key: 详情}。

        v0.8.2（TODO 10.5）：CD2 的「在传/排队」核对此前**只用于 strm 疑似**，
        对账失败那条路完全不查 —— 大文件还在上传、目标端暂时不存在或大小不符
        （CD2 边写边改挂载视图）时会被立即判 missing/corrupt 并报警。现在三处
        判失败前统一走同一个判据（`_cd2_in_flight_for`：排队/预处理/传输/暂停/
        队列中，刻意不含 FINISH 与 ERROR，卡死超限失去豁免）。

        被剔除的条目**不写失败清单**（与挂载不可用的保守结算同一取向），
        下一轮继续判；已在失败清单里的由 `_cd2_recover_failed_in_flight` 回退。
        Suppressed entries skip the failed list this round, like the conservative
        mount-unavailable settlement; entries already failed get reverted by
        `_cd2_recover_failed_in_flight`.
        """
        in_flight = self._cd2_in_flight_for(keys)
        if in_flight:
            logger.info(
                f"[Rsync115Sync] ⏳ {len(in_flight)} 个条目对账不一致，但 CD2 显示仍在上传中，"
                f"本轮不判失败（大文件传输中挂载视图暂时不一致属正常）: "
                f"{'; '.join(f'{k}（{_cd2.progress_text(v)}）' for k, v in list(in_flight.items())[:_MAX_LOGGED_PATHS])}")
        return in_flight

    def _cd2_recover_failed_in_flight(self) -> List[str]:
        """
        巡检入口：把「已判失败、但 CD2 显示正在上传」的条目移回等待态。

        为什么需要回退而不是只挡新增（TODO 10.5）：rsync 刚写完时 CD2 可能
        **还没扫到挂载点**，上一轮的单次检查会漏 —— 文件已在 failed 里，
        之后 CD2 才显示在传。此时失败判定是过早的，应当撤回。

        「移回等待态」= 从 failed 视图摘掉（缓存），行改回 candidate 并保留
        原冷却基准的**已完成量**：冷却基准取 `min(发现时刻, mtime)`，此处取
        "现在" 会让冷却重新走全程；取旧 enqueued_at 又可能立即再次取件。
        折中：基准 = now − 一个批次周期（`_delay_hours` 的 1/4，至少 15 分钟），
        让它在下一两轮内被重新取件重传，而不是立即、也不是等 4 小时。

        Returns: 被回退的 key 列表（供调用方记日志/计数）。
        """
        failed = getattr(self, "_failed_files", None)
        if not failed:
            return []
        keys = list(failed.keys())
        if not keys:
            return []
        in_flight = self._cd2_in_flight_for(keys)
        if not in_flight:
            return []
        now_ts = time.time()
        basis = now_ts - max(900.0, float(getattr(self, "_delay_hours", 4.0)) * 900.0)
        reverted: List[str] = []
        for key in list(in_flight.keys()):
            entry = failed.get(key)
            # 只回退「未达上限」的：达上限是用户已知的人工处理项，
            # 自动回退会让告警与实际状态脱节。
            if isinstance(entry, dict) and entry.get("exhausted_at"):
                continue
            # ⚠️ 回退前**必须清预算列**（review F3）：`move_key` 只写
            # `enqueued_at`（其余列走 upsert 的 COALESCE），台账里的
            # `fail_reason` / `retry_count` / `exhausted_at` 会原样留着。
            # 下一次失败时 `_mark_failed` 不传 exhausted_at → COALESCE 保留旧值
            # → 文件"从未达上限却显示已停止自动重试、且永不自动重试"。
            # 与结算恢复路径（`_execute_sync` 的 recovered 段）同一处置。
            ledger = getattr(self, "_ledger", None)
            if ledger is not None:
                try:
                    ledger.clear_fail_reason(key)
                    ledger.clear_field(key, "exhausted_at")
                    ledger.set_field(key, "retry_count", 0)
                except Exception:
                    pass
            _store_mod.move_key(failed, key, self._pending_queue, basis)
            reverted.append(key)
        if reverted:
            self.save_data("failed_files", failed)
            self.save_data("pending_queue", self._pending_queue)
            self._sync_failed_projection()
            logger.info(
                f"[Rsync115Sync] ↩️ {len(reverted)} 个失败条目其实【正在 CD2 上传】"
                f"（上一轮判失败过早），已移回冷却队列稍后自动重传: "
                f"{_brief_paths(reverted)}")
        return reverted

    def _cd2_prune_in_flight_suspects(self) -> List[str]:
        """
        把已进入疑似清单、但此刻正在上传的条目移出，返回被移除的 key。

        为什么属于「清理出口」而不是「解除」：它既不是上传成功，也不是误报 ——
        是**进展中**。移出的理由是「不该让它出现在待处理清单里」，因为清单上
        唯一的处置动作（删旧重传）对正在传的文件是纯破坏性的。
        Not resolution and not a false positive: the entry is progressing, and the
        only action offered by the list would destroy it.

        与 `_prune_cooling_suspects` 的分工：
          · 冷却队列 —— 照片级**尚未开始**（本插件自己的队列表）；
          · 本方法   —— CD2 **已经开始传**（CD2 的实时队列）。
        两者都表现为「暂时没有 .strm 属正常」，但所需的信息源完全不同。
        """
        suspects = list(getattr(self, "_strm_suspects", {}) or {})
        if not suspects:
            return []
        in_flight = self._cd2_in_flight_for(suspects)
        if not in_flight:
            return []
        now_ts = time.time()
        for key in in_flight:
            # ⚠️ 移回**观察期**，不是删行。正在上传的文件仍然需要被跟踪，下一轮
            # 继续判；pop 会 DELETE 整行，让它从此不受任何跟踪 —— 而它恰恰是最
            # 需要盯着的那一批（大文件、传得慢）。移出疑似清单的理由只是「清单上
            # 唯一的处置动作（删旧重传）对正在传的文件是破坏性的」，观察期没有
            # 那个动作，所以移过去既消掉了破坏性入口，又保住了跟踪。
            _store_mod.move_key(self._strm_suspects, key, self._strm_watch, now_ts)
            # 补生成标记一并失效：与其它出口同口径，重新按普通宽限期计时。
            self._strm_gen_requested.pop(key, None)
        self.save_data("strm_suspects", self._strm_suspects)
        self.save_data("strm_watch", self._strm_watch)
        logger.info(
            f"[Rsync115Sync] 📤 {len(in_flight)} 个疑似条目其实【正在 CD2 上传】"
            f"（宽限期不够长而已，不是异常），已移出待处理清单: "
            f"{'; '.join(f'{k}（{_cd2.progress_text(v)}）' for k, v in list(in_flight.items())[:_MAX_LOGGED_PATHS])}")
        self._reset_strm_notified_if_clear()
        return list(in_flight)

    def _cd2_failed_for(self, keys: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        查这些 key 在 CD2 里是否处于**失败/暂停**状态，返回 {key: 上传任务}。

        这不是判定，是**解释**：疑似清单里的条目成因有两种，差别很大——
          · 文件还在 CD2 传（大文件慢）→ 已有逻辑会把它移出清单；
          · 文件在 CD2 已经**失败**（ERROR / FATAL_ERROR，传输 0 字节）
            → 清单保留是对的，但用户看到「疑似上传异常」会以为要等，
              实际需要去 CD2 处理或删旧重传。
        本方法只把第二种情况查出来，供通知与看板附加一行说明。

        ⚠️ 刻意**不**把这些状态并入 `IN_FLIGHT_STATUSES`：失败不是"在传"，
        豁免它会让真故障永久藏起来（见 `should_suppress` 的说明）。

        查不到时返回空字典 —— 调用方据此不显示任何额外信息，行为与改造前一致。
        """
        if not keys or not self._cd2_enabled():
            return {}
        uploads = self._cd2_uploads()
        if not uploads:
            return {}
        mounts = self._cd2_mount_map()
        hits: Dict[str, Dict[str, Any]] = {}
        for key in keys:
            candidates = _cd2.dest_paths_for_key(key, getattr(self, "_sync_pairs", []), mounts)
            if not candidates:
                continue
            wanted = {_cd2.normalize_path(p) for p in candidates if p}
            if not wanted:
                continue
            for item in uploads:
                if item.get("status") not in _cd2.CD2_FAILED_STATUSES:
                    continue
                if any(_cd2.normalize_path(p) in wanted
                       for p in (item.get("dest_path"), item.get("key"))):
                    hits[key] = item
                    break
        return hits

    def _cd2_block_retransfer(self, keys: List[str]) -> Optional[str]:
        """
        「删旧重传」前的最后一道闸：拒绝删除正在上传的文件。

        返回 None 表示放行；返回字符串表示应中止并把它作为提示回给用户。

        ⚠️ 为什么必须挡在**删除**这一层，而不只是"不报警"：
        用户可能早就把条目加进了清单，或者从命令侧 `/rsync_strm retry` 直接
        点名重传 —— 那些路径都不经过"新发现"的判定。挡在删除前是唯一能
        覆盖全部入口的位置。
        Blocking at the delete step is the only place that covers every entry path —
        the user may retry an entry that was queued long ago.
        """
        if not keys or not self._cd2_enabled():
            return None
        in_flight = self._cd2_in_flight_for(keys)
        if not in_flight:
            return None
        detail = "\n".join(
            f"• {k}\n  ↳ {_cd2.progress_text(v)}"
            for k, v in list(in_flight.items())[:_MAX_LOGGED_PATHS])
        more = (f"\n（另有 {len(in_flight) - _MAX_LOGGED_PATHS} 个未列出）"
                if len(in_flight) > _MAX_LOGGED_PATHS else "")
        logger.warning(
            f"[Rsync115Sync] 🛑 拒绝删旧重传：{len(in_flight)} 个文件此刻正在 CD2 上传，"
            f"删除会让已传部分作废: {_brief_paths(list(in_flight))}")
        return (f"这 {len(in_flight)} 个文件此刻【正在 CD2 上传】，"
                f"删掉会让已经传完的部分作废：\n{detail}{more}\n\n"
                f"请等它们传完再判断（上传完成后 strm 通常会自行生成）。"
                f"如果确认是卡死的任务，请先在 CD2 网页里取消对应上传。")
