"""
旧 `save_data` 快照不得复活已同步的条目（一个自我延续的死循环）。

The legacy save_data snapshot must not resurrect settled entries.

## 这个循环是怎么被发现、以及它造成了什么

用户反馈「隔一段时间就收到『本次处理 102 个文件，全部完整上传到位』」。
查事件流水发现：

    enqueue 事件按小时分布： 02:00 → 102 条、03:00 → 102 条
    通知累计出现 69 次

**每两小时把 102 个早已同步完成的文件整批重新入队一次。** 完整链条：

1. 台账接管后，`save_data("pending_queue", self._pending_queue)` 的值是
   **台账替身**，被插件的 `save_data` 覆盖点静默跳过（那是对的 —— 否则真实
   宿主会因 JSON 无法序列化而抛异常）；
2. 于是 `save_data` 里那份快照**永远停在首次迁移时的样子**，再也不更新；
3. 而 `_seed_ledger_from_saved` 每次 `init_plugin` 都拿它"按缺失键回填" ——
   同步成功后已从台账删掉的条目，在**下一次重载时被原样复活**；
4. 复活 ⇒ 重新冷却 4h ⇒ 再跑一轮 ⇒ 全部命中秒传跳过 ⇒ 对账通过 ⇒ 出队
   ⇒ 下一次重载又复活 …… 无限循环，且每轮都推一条「成功」通知。

## 为什么单测当时没抓到

桩宿主的 `save_data` 无条件 `stored[k] = v`，**让那份陈旧快照永远存在**；
真实宿主则不会（值被覆盖点跳过）。**桩的宽容度就是测试的盲区** —— 本仓
已为此栽过多次（JSON 序列化那次是同一类）。
"""

import importlib
import os
import tempfile


def _fresh_plugin(root, stored):
    """构造一个会走 `init_plugin` 的最小实例（数据目录独立，避免用例间污染）。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    src = os.path.join(root, "src")
    os.makedirs(src, exist_ok=True)
    with open(os.path.join(src, "a.mkv"), "wb") as fh:
        fh.write(b"x")

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{
        "name": "电视剧", "src": src, "dest": "/115/TV",
        "strm_dir": os.path.join(root, "strm"), "all_ext": False,
    }]
    for k, v in dict(
        _exclude_patterns="", _media_extensions="mkv", _ignored_rules=[],
        _notify=False, _strm_notified=False, _strm_gen_requested={},
        _strm_watch={}, _strm_suspects={}, _strm_grace_minutes=5,
        _strm_check_enabled=True, _strm_last_check=0.0, _enabled=True,
        _listen_transfer=True, _delay_hours=4.0, _cron="*/10 * * * *",
        _rsync_timeout=600, _task_timeout=3600, _rate_limit_enabled=True,
        _upload_batch_size=200, _upload_max_per_window=500,
        _upload_window_secs=1800, _backoff_secs=3600, _rate_limit_keywords="429",
        _force_cooldown_days=7, _pending_queue={}, _backfill_queue=[],
        _source_cursor={}, _last_status={},
    ).items():
        setattr(plugin, k, v)

    saved = {}
    plugin.get_data_path = lambda: __import__("pathlib").Path(root)
    plugin.get_data = lambda k: stored.get(k)
    plugin.del_data = lambda k: (stored.pop(k, None), True)[1]

    def _save(k, v):
        saved[k] = v
        # 与真实宿主一致：值是台账替身时，插件的覆盖点会跳过它，
        # 因此它**不会**被写回 `stored`（这正是死循环的关键前提）。
        if not isinstance(v, (module.store.LedgerMapping,
                              module.store.LedgerFieldMap)):
            stored[k] = v
        return True

    plugin.save_data = _save
    plugin.update_config = lambda c: True
    return plugin, saved


def test_settled_entry_is_not_resurrected_on_reload(tmp_path):
    """
    ⚠️ **核心回归**：条目同步成功、已从台账出队后，重载**不得**把它复活。

    复现原缺陷的最小路径：
      1. 首启带着一份旧 `pending_queue` 快照 → 迁移进台账（这一步是**对的**）；
      2. 条目同步成功 → 从台账删除；
      3. 插件重载（宿主会定期做这件事）→ **旧快照不得再被回填**。
    """
    stored = {"pending_queue": {"电视剧:a.mkv": 1.0}}

    # ① 首启：旧快照被迁进台账（这条路径必须保留，否则升级会丢数据）
    p1, _ = _fresh_plugin(tmp_path, stored)
    p1.init_plugin({"enabled": True, "sync_pairs": p1._sync_pairs})
    assert "电视剧:a.mkv" in p1._pending_queue, (
        "首启没有把旧 save_data 迁进台账 —— 升级用户的队列会丢失"
    )

    # ② 同步成功：条目出队（模拟 P0-1 的出队路径）
    p1._pending_queue.pop("电视剧:a.mkv", None)
    assert "电视剧:a.mkv" not in p1._pending_queue

    # ③ 重载：不得复活
    p2, _ = _fresh_plugin(tmp_path, stored)
    p2.init_plugin({"enabled": True, "sync_pairs": p2._sync_pairs})
    assert "电视剧:a.mkv" not in p2._pending_queue, (
        "已同步完成的条目在重载后被复活了 —— 这就是那个每 2 小时复发一次的"
        "死循环（旧 save_data 快照被反复回填）。"
        "_seed_ledger_from_saved 必须只在一次性迁移时生效。"
    )


def test_first_boot_still_migrates_legacy_queue(tmp_path):
    """
    ⚠️ **反向保护**：首启迁移**必须**照常工作。

    修死循环时很容易把 seeding 整个关掉 —— 那样升级用户的三份队列数据
    （`pending_queue` / `strm_watch` / `strm_gen_requested`）会直接消失。
    这条用例钉住"该迁的还得迁"。

    ⚠️ 注意判据的顺序陷阱：`legacy_migrated` 标记是**迁移函数自己**写上的，
    而 seeding 发生在迁移之后。若 seeding 那时才去读标记，首启会被判成
    "已迁移过"而完全跳过 —— 我第一版就写错了这个顺序。
    """
    stored = {
        "pending_queue": {"电视剧:a.mkv": 1.0},
        "strm_watch": {"电视剧:b.mkv": 2.0},
        # ⚠️ 补生成标记必须挂在一个**已存在于某个清单**的文件上 ——
        # 它是 `LedgerFieldMap`（按列的视图），刻意不做插入（标记得有行可挂）。
        # `{"电视剧:c.mkv"}` 这种"只在 gen_requested 里出现"的**孤儿标记**
        # 在语义上就是无效的（`_prune_orphan_gen_markers` 会删掉它），
        # 拿它当用例不真实。这里让它与 watch 里的条目重合。
        "strm_gen_requested": {"电视剧:b.mkv": 3.0},
    }
    p, _ = _fresh_plugin(tmp_path, stored)
    p.init_plugin({"enabled": True, "sync_pairs": p._sync_pairs})

    assert "电视剧:a.mkv" in p._pending_queue
    assert "电视剧:b.mkv" in p._strm_watch
    assert "电视剧:b.mkv" in p._strm_gen_requested, (
        "「已补生成过」标记在升级时丢了 —— 看板不会再标「补生成后仍无」，"
        "用户可能对同一批文件反复补生成（每次让助手遍历一遍云端目录）"
    )


def test_stale_snapshot_is_deleted_after_migration(tmp_path):
    """
    迁移完成后要把那几个 `save_data` 键**清掉** —— 留着就是一份永不刷新的
    陈旧快照，迟早有人再拿它回填一次。
    """
    stored = {"pending_queue": {"电视剧:a.mkv": 1.0}}
    p, _ = _fresh_plugin(tmp_path, stored)
    p.init_plugin({"enabled": True, "sync_pairs": p._sync_pairs})

    for key in ("pending_queue", "strm_watch", "strm_suspects", "strm_gen_requested"):
        assert key not in stored, (
            f"迁移后 {key} 仍留在 save_data 里 —— 它已经不再更新，"
            f"留着只会被误当成权威数据回填"
        )


def test_seed_guard_blocks_resurrection_even_with_snapshot_present(tmp_path):
    """
    ⚠️ **单独覆盖那道守卫**：即使旧快照仍在，已迁移过的实例也不得回填。

    为什么需要这条单独的用例：修复死循环用了**两道**措施 ——
      ① 迁移后**删掉**陈旧快照；
      ② `_seed_ledger_from_saved` 只在一次性迁移时生效（`_allow_legacy_seed`）。
    ① 会掩盖 ②：快照被删掉之后，守卫在不在都看不出差别 ——
    变异测试当场证明了这一点（去掉守卫，其它用例照样全绿）。

    但守卫不是多余的：删除可能失败（`del_data` 抛异常时被吞掉）、
    快照可能从备份恢复、也可能被更早的版本重新写入。那时**只有守卫**能挡住
    那个每 2 小时把 102 个已同步文件整批复活的死循环。

    本用例手工把台账标成"已迁移"，再**故意留着**快照，验证回填不会发生。
    """
    stored = {"pending_queue": {"电视剧:a.mkv": 1.0}}

    p, _ = _fresh_plugin(tmp_path, stored)
    # 先建出台账并写上迁移标记（模拟"这个库早就迁移过了"）
    p.init_plugin({"enabled": True, "sync_pairs": p._sync_pairs})
    p._ledger.set_meta("legacy_migrated", "1")

    # ⚠️ 必须**真的把条目从台账里删掉**（模拟同步成功后出队）。
    # 漏了这一步，用例测到的就只是"台账里本来就有那一行"这种正常加载 ——
    # 我第一版正是这么写的，于是它对着一个无关的原因失败。
    p._pending_queue.pop("电视剧:a.mkv", None)
    assert p._ledger.get("电视剧:a.mkv") is None, "台账里该条目应已被删除"

    # 故意把快照塞回去（模拟删除失败 / 从备份恢复 / 旧版本重新写入）
    stored["pending_queue"] = {"电视剧:a.mkv": 1.0}

    p2, _ = _fresh_plugin(tmp_path, stored)
    p2.init_plugin({"enabled": True, "sync_pairs": p2._sync_pairs})

    assert "电视剧:a.mkv" not in p2._pending_queue, (
        "已迁移过的台账仍被旧快照回填 —— 这正是那个每 2 小时发作一次的死循环。"
        "`_seed_ledger_from_saved` 必须只认一次性迁移开关 `_allow_legacy_seed`。"
    )

# --------------------------------------------------------------------------
# 存储边界：台账在插件自己的 SQLite 文件，配置与小状态在宿主 DB
# --------------------------------------------------------------------------

def test_ledger_lives_in_the_plugin_data_dir():
    """
    台账必须是 `<插件数据目录>/ledger.sqlite3` —— **不**进宿主数据库。

    这不是风格问题：台账是一行一个文件的全生命周期状态，写频高、量随库增长；
    塞进宿主的 JSON 列既会撞上「不可序列化」（已被 ea6107f 那次事故证明），
    也会把插件自己的状态混进平台配置里。用户问「台账在 sqlite、配置在 MP 数据库吧」
    时确认的正是这条边界。
    """
    import importlib
    module = importlib.import_module("app.plugins.rsync115sync")
    import inspect
    src = inspect.getsource(module.Rsync115Sync._open_store)
    assert "ledger.sqlite3" in src, "台账文件名变了"
    assert "get_data_path()" in src, (
        "台账没有落在插件数据目录 —— 它不该写进宿主数据库"
    )


def test_user_config_is_not_written_by_the_ledger():
    """
    配置（开关 / cron / sync_pairs）走 `update_config`，**不**进台账。

    判据来自 store.py 顶部那张表：「与文件有关」的进台账，其余留在宿主侧。
    若哪天有人把配置也塞进 `files` 表，这张表就不再是"一行一个文件"了。
    """
    import importlib
    module = importlib.import_module("app.plugins.rsync115sync")
    import inspect
    src = inspect.getsource(module.Rsync115Sync._api_save_config)
    assert "update_config" in src, "保存配置没有走宿主接口"


def test_cursor_stays_in_save_data_not_the_ledger():
    """
    `source_cursor` 必须留在 `save_data`（宿主侧），不进台账。

    ⚠️ 它**不是**某个文件的状态，而是"我看到哪里了"的记账 —— 台账的 key 是
    `映射名:相对路径`，装不下"某个映射的扫描位置"。混进去会造出一批虚构路径。

    这条也顺带守住"游标不做成可编辑字段"那个决定的前提：它一旦进了台账，
    就很容易被当成普通行去改，而实测往回拨游标会让已同步文件重新入队。
    """
    import importlib
    module = importlib.import_module("app.plugins.rsync115sync")
    import inspect
    # 载入路径：游标从 get_data 恢复
    src = inspect.getsource(module.Rsync115Sync.init_plugin)
    assert 'get_data("source_cursor")' in src, (
        "游标不再从 save_data 恢复 —— 若已迁进台账，需同步更新存储边界文档"
    )
    # 台账 schema 里不得出现游标字段
    from app.plugins.rsync115sync import store as store_mod
    schema_src = inspect.getsource(store_mod.Store._init_schema)
    assert "cursor" not in schema_src.lower(), "台账 schema 里出现了游标字段"

