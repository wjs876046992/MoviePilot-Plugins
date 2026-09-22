"""
上传限流 / 退避 / 冷却与补传队列：状态机辅助方法（阶段 2 拆分）。

Upload rate-limiting / backoff / cool-down and the backfill queue (stage-2 split).

与 strm_ops.py 同一套约束（见其模块头注释）：Mixin 只搬**代码**，方法读写的
self.* 状态（限流计数、退避窗口、_backfill_queue、_pending_queue ...）全部留在
插件实例上，本类不持有任何状态。
"""
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.sdk.logging import logger

from .paths import pair_name as _pair_name


class SyncOpsMixin:
    """限流 / 退避 / 补传队列方法；本类不持有任何状态。"""

    def _count_queue(self, now_ts: float, threshold: float) -> Tuple[int, int, int]:
        """
        统计冷却队列：返回 (就绪数, 冷却中数, 已失效数)。

        Count the cool-down queue as (ready, cooling, stale).

        为什么需要第三个数字：入库文件在冷却途中被删除后，队列条目要等冷却到期、
        下一轮同步才会被清理。若只按时间戳统计，这些「文件已不存在」的条目会被
        算进冷却中甚至就绪数，看板就会出现「冷却要 2 小时、却有一批 1 小时前的
        条目迟迟不就绪」这类误导信息。
        宿主没有「媒体库文件被删除」事件（只有下载器/订阅/站点的删除事件），
        因此无法在删除时即时移除，只能在**展示时**用存在性过滤，不改动持久化队列
        （避免为了显示而增加热路径开销）。真正清理由同步轮次负责。
        Stale entries are those whose file is already gone. The host emits no
        "library file deleted" event, so removal cannot be event-driven; we filter
        them at display time only and let the sync run do the actual pruning.
        """
        ready_count = 0
        cooling_count = 0
        stale_count = 0
        for key, ts in self._pending_queue.items():
            if not self._queue_key_exists(key):
                stale_count += 1
                continue
            if now_ts - ts >= threshold:
                ready_count += 1
            else:
                cooling_count += 1
        return ready_count, cooling_count, stale_count

    def _queue_key_exists(self, key: str) -> bool:
        """
        判断队列条目对应的源端文件是否仍然存在。

        Whether the source file behind a queue key still exists.

        key 形如 "任务名:相对路径"，需用映射的 src 还原绝对路径。任务名与 src
        都可能被用户改名，因此无法纯靠解析 key 得出路径；这里按前缀匹配所有映射，
        逐个还原。解析不出时不视为失效（宁可当作存在，避免误报）。
        """
        direct = os.path.isabs(key) and key != ""
        if direct:
            return os.path.exists(key)
        for pair in self._sync_pairs:
            pair_name = _pair_name(pair)
            src_root = (pair.get("src") or "").strip().rstrip("/")
            if not src_root or not pair_name:
                continue
            if key.startswith(f"{pair_name}:"):
                rel_p = key.split(f"{pair_name}:", 1)[1]
                return os.path.exists(os.path.join(src_root, rel_p))
        return True  # 无法归属任何映射，不判定为失效

    # ================= 上传限流与风控退避 =================

    def _load_rate_limit_state(self):
        """
        从插件数据目录恢复限流窗口与退避状态。

        Restore window counter and back-off deadline from the plugin data
        directory. Must run before any upload decision is made.
        """
        self._upload_window_start = float(self.get_data("upload_window_start") or 0.0)
        self._upload_window_count = int(self.get_data("upload_window_count") or 0)
        self._upload_blocked_until = float(self.get_data("upload_blocked_until") or 0.0)

    def _persist_rate_limit_state(self):
        """
        持久化限流状态。

        Persist throttling state. Written before the first count is charged so
        that a restart cannot open a race window that bypasses the limiter.
        """
        self.save_data("upload_window_start", self._upload_window_start)
        self.save_data("upload_window_count", self._upload_window_count)
        self.save_data("upload_blocked_until", self._upload_blocked_until)

    def _rate_limit_allows(self) -> Tuple[bool, str]:
        """
        上传闸门：判断当前是否可以发起本批上传。

        Upload gate: decide whether this batch may start uploading now.

        返回 (是否放行, 原因说明)，原因用于回显给用户。
        Returns (allowed, human_readable_reason); the reason is surfaced to the user.

        三层判定 / three sequential checks:
          1) 退避期未过 → 拒绝 / still inside back-off → deny
          2) 窗口已过期 → 计数归零并前移窗口 / window expired → reset and roll forward
          3) 窗口内计数达上限 → 拒绝 / quota exhausted → deny
        """
        if not self._rate_limit_enabled:
            return True, ""

        now_ts = time.time()

        # 1) 风控退避期 / back-off window
        if now_ts < self._upload_blocked_until:
            remain = int(self._upload_blocked_until - now_ts)
            return False, f"风控退避中，还需等待 {max(1, remain // 60)} 分钟"

        # 2) 窗口滚动 / roll the counting window when it has elapsed
        if self._upload_window_start <= 0 or (now_ts - self._upload_window_start) >= self._upload_window_secs:
            self._upload_window_start = now_ts
            self._upload_window_count = 0

        # 3) 窗口配额 / per-window quota
        if self._upload_window_count >= self._upload_max_per_window:
            elapsed = int(now_ts - self._upload_window_start)
            remain = max(1, self._upload_window_secs - elapsed)
            return False, (f"本窗口配额已用尽（{self._upload_window_count}/{self._upload_max_per_window}），"
                           f"约 {max(1, remain // 60)} 分钟后继续")

        return True, ""

    def _consume_upload_quota(self, batch_info: str = "") -> int:
        """
        扣减配额：把本批实际上传的文件数并入窗口计数并落盘。

        Charge the quota: add this batch's file count to the window counter and
        persist it immediately.

        调用时机是在 rsync 启动**之前**预留：若在传输过程中插件被重载，
        已提交的文件数不会因内存状态丢失而让下一批绕过限流。
        Called BEFORE rsync starts (pre-charged). If the plugin is reloaded while
        a transfer is in flight, the already-committed count is not lost with the
        in-memory state, so the next batch cannot bypass the limiter.

        返回扣减后的窗口计数 / returns the updated window count.
        """
        if not self._rate_limit_enabled:
            return self._upload_window_count
        count = self._current_batch_size
        if count <= 0:
            return self._upload_window_count
        self._upload_window_count += count
        self._persist_rate_limit_state()
        logger.info(f"[Rsync115Sync] 🚦 上传配额扣减 {count} 个{batch_info}，"
                    f"本窗口累计 {self._upload_window_count}/{self._upload_max_per_window}")
        return self._upload_window_count

    def _detect_rate_limit_hit(self, stderr: str) -> bool:
        """
        从 rsync 错误输出中识别 115 / CD2 的风控特征串。

        Detect 115 / CD2 rate-limiting signatures in rsync stderr. Matching is
        case-insensitive and substring-based, so `429`, `too many requests`,
        `rate limit` and similar messages all trigger a back-off.
        """
        if not stderr:
            return False
        lowered = stderr.lower()
        for kw in self._rate_limit_keywords.splitlines():
            kw = kw.strip().lower()
            if kw and kw in lowered:
                return True
        return False

    def _trigger_backoff(self, reason: str):
        """
        命中风控：进入退避期，后续批次在退避结束前一律不放行。

        Enter back-off after a rate-limit hit. No batch is permitted until the
        back-off deadline passes, giving 115's side time to settle.
        """
        self._upload_blocked_until = time.time() + self._backoff_secs
        # 退避期间窗口计数一并归零，避免退避结束后立刻撞上配额上限
        self._upload_window_start = 0.0
        self._upload_window_count = 0
        self._persist_rate_limit_state()
        logger.warning(f"[Rsync115Sync] 🚫 触发风控退避：{reason}，"
                       f"暂停上传 {self._backoff_secs // 60} 分钟")

    def _build_backfill_candidates(self) -> List[str]:
        """
        扫描源端，构建“存量补传”候选清单。

        Scan the source side and build the back-fill candidate list.

        全程只读源目录，不访问 115 挂载点，因此零 API 开销。
        Read-only over local directories; the 115 mount is never touched, so this
        costs ZERO API calls regardless of library size.

        候选口径：源端存在、且不在冷却队列、也不在异常清单中的文件
        （即本插件从未处理过的存量文件）。
        Criteria: exists locally AND absent from the cool-down queue, the anomaly
        lists and the ignore list — i.e. files this plugin has never handled.

        注意：无法在不访问 115 的前提下判断目标端是否已存在，
        therefore the list may include files that were synced before but never
        queued. Those are skipped by rsync's --size-only at transfer time, at the
        cost of one stat request per candidate.
        注意：候选规模即用户点击补传的最小 API 代价，故 UI 先预览再确认。
        """
        candidates: List[str] = []
        seen = set()
        # 目录列举缓存：整个扫描过程共用，避免同一季目录被反复 listdir
        dir_cache: Dict[str, Optional[List[str]]] = {}
        valid_exts = [x.strip().lower() for x in self._media_extensions.split(",") if x.strip()]
        # 只按扩展名过滤候选，范围由每个映射对的 all_ext 决定
        for pair in self._sync_pairs:
            src_dir = (pair.get("src") or "").strip().rstrip("/")
            pair_name = _pair_name(pair)
            if not src_dir or not os.path.isdir(src_dir):
                continue
            all_ext = pair.get("all_ext", False)
            for root, dirs, files in os.walk(src_dir):
                # 就地裁剪排除目录，避免无谓 descend
                dirs[:] = [d for d in dirs if f"{d}/" not in self._exclude_patterns]
                for f in files:
                    if f.startswith("._") or f == ".DS_Store":
                        continue
                    ext = os.path.splitext(f)[-1].lstrip(".").lower()
                    if not all_ext and ext not in valid_exts:
                        continue
                    root_rel = os.path.relpath(os.path.join(root, f), src_dir)
                    key = f"{pair_name}:{root_rel}"
                    if key in seen:
                        continue
                    # 已在冷却队列或异常清单中的文件不属于“存量补传”
                    if key in self._pending_queue:
                        continue
                    if key in (self._last_status.get("missing_files") or []):
                        continue
                    if key in (self._last_status.get("corrupt_files") or []):
                        continue
                    if self._is_ignored(key):
                        continue
                    seen.add(key)
                    candidates.append(key)
                    # 媒体文件带上同主名的伴生字幕一起补传
                    # Attach same-stem sidecar subtitles to the media file
                    for sc in self._find_sidecar_files(src_dir, root_rel, dir_cache):
                        sc_key = f"{pair_name}:{sc}"
                        if sc_key not in seen and not self._is_ignored(sc_key):
                            seen.add(sc_key)
                            candidates.append(sc_key)
        return candidates

    def _api_backfill_scan(self):
        """
        预览补传候选数量与样例，供用户在触发前评估规模。

        Preview candidate count and a sample so the user can judge the cost
        before committing. Because every candidate costs at least one target-side
        stat, this preview is what keeps a single click from firing thousands of
        requests unnoticed.

        并发保护：扫描会遍历全部映射的源目录，大库下耗时可达数十秒。
        若同一时刻已有扫描在跑，直接拒绝而不是排队 —— 重复扫描结果完全一致，
        让它们叠加只会白白占用磁盘 IO。
        Concurrency guard: a large library scan can take tens of seconds.
        A second concurrent scan is rejected outright (results would be identical).
        """
        if self._is_running:
            return {"success": False,
                    "message": "已有同步任务正在运行，扫描结果可能不完整，请稍后再试"}
        if not self._backfill_scan_lock.acquire(blocking=False):
            return {"success": False,
                    "message": "已有一次补传扫描正在进行，请等待其完成（结果相同，无需重复触发）"}
        try:
            candidates = self._build_backfill_candidates()
        finally:
            # 必须在 finally 中释放：扫描抛异常若不释放，之后所有扫描与补传
            # 都会被这个锁永久挡住（重启插件才能恢复）
            self._backfill_scan_lock.release()
        sample = candidates[:20]
        return {
            "success": True,
            "data": {
                "count": len(candidates),
                "sample": sample,
                "batch_size": self._upload_batch_size,
                "windows_needed": (
                    (len(candidates) + self._upload_max_per_window - 1) // self._upload_max_per_window
                    if self._upload_max_per_window > 0 else 0
                ),
            }
        }

    def _api_backfill_start(self, body: Dict[str, Any]):
        """
        启动存量补传。

        Start the back-fill run.

        只扫描源端（零 API），把候选写入独立的补传队列，
        随后由核心同步逻辑按批次上限与窗口配额逐步消费。
        Scan the source only (zero API), store candidates in a dedicated queue,
        then let the core sync loop drain it under the batch cap and window quota.

        队列独立于 pending_queue：补传项不参与入库冷却计时，避免污染
        “冷却中 / 已就绪”统计。
        The queue is separate from pending_queue: back-fill entries do NOT take
        part in cool-down timing, so the cooling/ready counters stay accurate.
        """
        if self._is_running:
            return {"success": False, "message": "已有任务正在运行，请稍后再试"}
        # 扫描互斥：本接口内部同样会全库扫描。若此刻已有扫描在跑
        # （例如用户先点了预览还没结束就点了确认），两个扫描会同时遍历磁盘；
        # 更糟的是确认框展示的候选数与最终写入队列的候选数将来自两次不同扫描，
        # 与用户确认的内容不一致。
        # Also guards the case where a preview scan is still running while the user
        # confirms: the confirmed count would otherwise come from a different scan.
        if not self._backfill_scan_lock.acquire(blocking=False):
            return {"success": False,
                    "message": "有一次扫描正在进行（可能是刚才的预览），请等它结束后重试"}
        try:
            candidates = self._build_backfill_candidates()
        finally:
            self._backfill_scan_lock.release()
        if not candidates:
            return {"success": True, "message": "没有需要补传的存量文件"}

        # 整体替换：每次触发都以当前源端实际状态为准
        self._backfill_queue = candidates
        self._backfill_total = len(candidates)
        self.save_data("backfill_queue", self._backfill_queue)
        self.save_data("backfill_total", self._backfill_total)

        logger.info(f"[Rsync115Sync] 📦 已建立存量补传队列：{len(candidates)} 个文件"
                    f"（其中含伴生字幕），按每批 {self._upload_batch_size} 个、"
                    f"每窗口 {self._upload_max_per_window} 个推进")
        self._start_sync_thread(mode="backfill", custom_files=list(candidates))
        return {
            "success": True,
            "message": f"已启动存量补传：{len(candidates)} 个文件，"
                       f"受批次与限流约束将分多轮完成",
        }

    def _api_backfill_clear(self):
        """
        清空补传队列与进度。

        Clear the back-fill queue and its progress counters. Already-synced files
        are unaffected; only the pending work list is discarded.
        """
        self._backfill_queue = []
        self._backfill_total = 0
        self.save_data("backfill_queue", [])
        self.save_data("backfill_total", 0)
        return {"success": True, "message": "已清空存量补传队列"}

    # ================= 核心同步执行逻辑 (严格对齐 sync_115.sh) =================

    def _force_cooldown_allows(self) -> Tuple[bool, str]:
        """
        force 全量校验的冷却判定。

        该模式会遍历 115 挂载点全目录，是本插件最重的 API 操作，
        因此按天限频。只有成功执行才推进时间戳——失败不占用冷却额度，
        便于排障（重复尝试仍受窗口配额约束，不会无限冲击 115）。
        """
        days = max(0, int(self._force_cooldown_days))
        if days <= 0 or self._last_force_ts <= 0:
            return True, ""
        elapsed = time.time() - self._last_force_ts
        remain = days * 86400 - elapsed
        if remain <= 0:
            return True, ""
        hours = int(remain // 3600)
        next_ts = datetime.fromtimestamp(self._last_force_ts + days * 86400)
        return False, (f"全量校验冷却中（每 {days} 天一次），"
                       f"约 {hours} 小时后可用，最早 {next_ts.strftime('%Y-%m-%d %H:%M')}")

    def _mark_force_done(self):
        """
        记录一次成功的全量校验，开始计算冷却。

        Record a successful full verification and start the cool-down clock.
        Called only on success, so a failed run does not consume the allowance.
        """
        self._last_force_ts = time.time()
        self.save_data("last_force_ts", self._last_force_ts)

    def _resume_backfill_if_pending(self) -> bool:
        """
        定时巡检时自动续跑未完成的补传队列。

        补传受“单批上限”与“窗口配额”约束，一次通常跑不完全部候选；
        未完成的队列在此自动续跑，配额用尽则本轮跳过、等下一窗口继续，
        无需用户重复点击。

        返回是否已占用本轮（同一次 cron 只跑一种模式，避免线程争抢同一把锁）。
        """
        if not self._backfill_queue:
            return False
        allowed, reason = self._rate_limit_allows()
        if not allowed:
            logger.info(f"[Rsync115Sync] 📦 补传队列剩余 {len(self._backfill_queue)} 个，"
                        f"本轮暂缓（{reason}）")
            return False
        logger.info(f"[Rsync115Sync] 📦 续跑存量补传队列，剩余 {len(self._backfill_queue)} 个")
        self._start_sync_thread(mode="backfill", custom_files=list(self._backfill_queue))
        return True

