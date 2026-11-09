"""
状态迁移不得删行 —— v0.6.0 的回归守卫。

**为什么需要这组用例**：PQ / SW / SS 是同一张 `files` 表的三个视图，一个 key
只有一行。此前业务代码用「从旧视图 `pop` + 往新视图赋值」做迁移，而
`LedgerMapping.pop` 会 `DELETE` 整行 —— 于是正交列（`synced_at` /
`gen_requested_at` / `ingest_source` / `src_mtime`）被静默丢弃。当前进程靠内存
缓存看起来一切正常，**重载之后才暴露**：观察行消失、补生成标记退回普通宽限期。

本文件**不依赖 MoviePilot 后端**：`store.py` 只用标准库，直接用 importlib 按
文件路径加载；业务侧用 AST 取函数源码做哨兵断言。因此可以用
`pytest --noconftest` 在没有后端的机器上真跑。

哨兵断言在**缺陷版上必须失败** —— 它们检查的是具体函数体里有没有用
`move_key` / `forget_key`，而不是检查"代码里有这个词"。
"""

import ast
import importlib.util
import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_PLUGIN_DIR = os.path.join(_REPO, "plugins.v3", "rsync115sync")


def _load_store():
    """按文件路径加载 store.py（它无相对导入、无 app 依赖）。"""
    path = os.path.join(_PLUGIN_DIR, "store.py")
    spec = importlib.util.spec_from_file_location("_rsync_store_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


store = _load_store()


def _read(name):
    with open(os.path.join(_PLUGIN_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def _func_src(filename, funcname):
    """
    取某个函数的**代码**（剥掉 docstring 与注释）；找不到就失败，避免哨兵静默通过。

    ⚠️ 必须剥掉文档与注释：本仓踩过同型的坑（从构建 CSS 里抓 scoped 哈希时
    正则先命中了注释文本）。这里的 docstring 与注释**刻意解释了旧写法为什么错**，
    因此里面就写着 `SELECT * FROM files ORDER BY updated_at`、`pop` 这些词 ——
    拿原始源码做 "not in" 断言会被自己的说明文字判成违规。
    """
    src = _read(filename)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == funcname:
            body = list(node.body)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body = body[1:]                      # 去掉 docstring
            assert body, f"{funcname} 函数体为空"
            # unparse 只输出代码，注释自然消失
            return "\n".join(ast.unparse(stmt) for stmt in body)
    pytest.fail(f"{filename} 里找不到 {funcname} —— 哨兵失效，请同步更新用例")


@pytest.fixture()
def ledger(tmp_path):
    s = store.Store(tmp_path / "ledger.sqlite3")
    assert s.usable, "台账建不起来，用例前提不成立"
    return s


def _views(s):
    """按生产口径建三个视图（与 _bind_ledger_maps 同构）。"""
    pq = store.LedgerMapping(s, store.STATUS_CANDIDATE, ts_field="enqueued_at")
    sw = store.LedgerMapping(s, store.STATUS_PENDING_VERIFY, ts_field="enqueued_at")
    ss = store.LedgerMapping(s, store.STATUS_SUSPECT, ts_field="verified_at",
                             extra_from_value={"origin": "origin"})
    return pq, sw, ss


# --------------------------------------------------------------------------
# 存储层：迁移原语必须保住正交列
# --------------------------------------------------------------------------

def test_move_key_preserves_orthogonal_columns_across_reload(ledger):
    """疑似 → 观察期：synced_at / gen_requested_at / ingest_source 必须活过重载。"""
    key = "TV:S01E01.mkv"
    ledger.upsert(key, store.STATUS_SUSPECT, ingest_source="scan",
                  src_mtime=111.0, synced_at=222.0, gen_requested_at=333.0,
                  verified_at=444.0, origin="watch")
    _, sw, ss = _views(ledger)
    assert key in ss

    store.move_key(ss, key, sw, 999.0)

    # 重载：丢掉所有内存缓存，只从 SQLite 重建
    _, sw2, ss2 = _views(ledger)
    assert key in sw2, "观察行在重载后消失了 —— 正是 v0.6.0 修的 bug"
    assert key not in ss2
    row = ledger.get(key)
    assert row["status"] == store.STATUS_PENDING_VERIFY
    assert row["synced_at"] == 222.0
    assert row["gen_requested_at"] == 333.0, "补生成标记丢失 → 重载后退回普通宽限期"
    assert row["ingest_source"] == "scan", "入库来源被重置成 legacy"
    assert row["src_mtime"] == 111.0


def test_pop_then_set_is_destructive(ledger):
    """
    对照用例：旧写法（pop + 赋值）**确实**会丢列。

    它存在的意义是把"为什么不能用 pop"钉成可执行的事实 —— 如果哪天有人觉得
    pop 更直观而改回去，上面那条用例会在重载断言处失败，而这条用例解释了原因。
    """
    key = "TV:S01E02.mkv"
    ledger.upsert(key, store.STATUS_SUSPECT, ingest_source="webhook",
                  synced_at=222.0, gen_requested_at=333.0)
    _, sw, ss = _views(ledger)
    ss.pop(key, None)          # 旧写法：DELETE 整行
    sw[key] = 999.0            # 再插一行全新的
    row = ledger.get(key)
    assert row["synced_at"] is None
    assert row["gen_requested_at"] is None
    assert row["ingest_source"] == "legacy"


def test_forget_key_does_not_delete_the_row(ledger):
    """只摘缓存：行还在，且 status 不被改动。"""
    key = "TV:S01E03.mkv"
    ledger.upsert(key, store.STATUS_CANDIDATE, ingest_source="scan", synced_at=222.0)
    pq, _, ss = _views(ledger)
    # 模拟「行已被别处改成 candidate，但疑似视图还留着过期缓存」
    ss._cache[key] = {"ts": 1.0}
    assert store.forget_key(ss, key) is True
    assert key not in ss
    row = ledger.get(key)
    assert row is not None, "forget 不该删行"
    assert row["status"] == store.STATUS_CANDIDATE
    assert row["synced_at"] == 222.0
    assert key in pq


def test_retire_key_keeps_row_as_done(ledger):
    """终态留行：done 行保留 synced_at，累计成功数才不会随完成而减少。"""
    key = "TV:S01E04.mkv"
    ledger.upsert(key, store.STATUS_PENDING_VERIFY, synced_at=222.0,
                  ingest_source="scan")
    _, sw, _ = _views(ledger)
    assert store.retire_key(sw, key) is True
    assert key not in sw
    row = ledger.get(key)
    assert row is not None, "终态删行会让 synced_files 统计随完成而减少"
    assert row["status"] == store.STATUS_DONE
    assert row["synced_at"] == 222.0
    assert ledger.count_by_status()[store.STATUS_DONE] == 1


def test_upsert_does_not_clobber_ingest_source(ledger):
    """改状态时不传 ingest_source，就必须保持原值（此前每次都重置成 legacy）。"""
    key = "TV:S01E05.mkv"
    ledger.upsert(key, store.STATUS_CANDIDATE, ingest_source="webhook")
    ledger.upsert(key, store.STATUS_PENDING_VERIFY, synced_at=1.0)
    ledger.upsert(key, store.STATUS_SUSPECT, verified_at=2.0)
    assert ledger.get(key)["ingest_source"] == "webhook"
    # 显式传值仍然可以覆盖
    ledger.upsert(key, store.STATUS_SUSPECT, ingest_source="scan")
    assert ledger.get(key)["ingest_source"] == "scan"


def test_retry_count_is_no_longer_written(ledger):
    """`bump_retry` 已删除：列保留（不做 DROP COLUMN 迁移），但不再有写入者。"""
    import inspect
    assert "bump_retry" not in inspect.signature(ledger.upsert).parameters
    key = "TV:S01E06.mkv"
    ledger.upsert(key, store.STATUS_CANDIDATE)
    ledger.upsert(key, store.STATUS_SUSPECT)
    ledger.upsert(key, store.STATUS_PENDING_VERIFY)
    assert ledger.get(key)["retry_count"] == 0


# --------------------------------------------------------------------------
# 规模：终态不进默认取数，分页必须稳定
# --------------------------------------------------------------------------

def test_page_by_status_excludes_done_and_paginates_stably(ledger):
    for i in range(30):
        ledger.upsert(f"TV:done{i}.mkv", store.STATUS_DONE, synced_at=float(i))
    for i in range(7):
        ledger.upsert(f"TV:live{i}.mkv", store.STATUS_CANDIDATE, enqueued_at=float(i))

    active = ledger.page_by_status(store.ACTIVE_STATUSES)
    assert len(active) == 7, "终态 done 混进了活跃取数 —— 十万级下这就是全表扫描"
    assert all(r["status"] != store.STATUS_DONE for r in active)

    p1 = ledger.page_by_status(store.ACTIVE_STATUSES, limit=3, offset=0)
    p2 = ledger.page_by_status(store.ACTIVE_STATUSES, limit=3, offset=3)
    p3 = ledger.page_by_status(store.ACTIVE_STATUSES, limit=3, offset=6)
    assert [len(p) for p in (p1, p2, p3)] == [3, 3, 1]
    keys = [r["key"] for p in (p1, p2, p3) for r in p]
    assert len(set(keys)) == 7, "翻页出现重复或跳行（排序缺确定性 tiebreaker）"
    assert set(keys) == {r["key"] for r in active}


def test_retired_row_is_not_resurrected_into_the_queue(ledger):
    """
    终态留行后，重载**不得**把它读回冷却队列。

    这个插件在「已完成条目被复活」上翻过两次车（每 2 小时复发一轮重复通知）。
    改成留行之后多了一种复活可能：done 行还在表里，视图若按 key 而不是按
    status 取数就会把它捞回来。`_load()` 是按 status 过滤的，这条用例把它钉住。

    另注：`test_ledger_no_resurrect.py` 用 `_pending_queue.pop()` 模拟出队 ——
    那是**旧**实现路径（生产代码现在走 retire/forget）。两条路径都要不复活，
    所以这里补的是新路径，不是替换它。
    """
    key = "TV:S01E07.mkv"
    ledger.upsert(key, store.STATUS_CANDIDATE, enqueued_at=100.0)
    pq, _, _ = _views(ledger)
    assert key in pq

    store.retire_key(pq, key, synced_at=200.0)

    pq2, sw2, _ = _views(ledger)          # 等价于重载插件
    assert key not in pq2, "done 行被读回冷却队列 —— 会重新参与取件与通知"
    assert key not in sw2
    row = ledger.get(key)
    assert row["status"] == store.STATUS_DONE


def test_done_has_no_in_memory_view(ledger):
    """done 刻意不建视图：十万级终态行不该被载入内存。"""
    assert store.STATUS_DONE not in store.ACTIVE_STATUSES
    assert store.STATUS_DONE in store.ALL_STATUSES


# --------------------------------------------------------------------------
# 业务侧哨兵：具体函数必须用迁移原语，不得 pop
# --------------------------------------------------------------------------

def test_arm_watch_forgets_suspect_instead_of_pop():
    body = _func_src("strm_ops.py", "_strm_arm_watch")
    assert "forget_key(self._strm_suspects" in body, (
        "重传成功解除疑似时必须只摘缓存；pop 会删掉刚写好的观察行")
    assert "_strm_suspects.pop" not in body


def test_rearm_after_gen_request_uses_move_key():
    body = _func_src("strm_ops.py", "_rearm_after_gen_request")
    assert "move_key(" in body, "必须用 move_key 保住 gen_requested_at"
    assert "_strm_suspects.pop" not in body


def test_cd2_in_flight_suspects_move_to_watch():
    body = _func_src("cd2_ops.py", "_cd2_prune_in_flight_suspects")
    assert "move_key(" in body, (
        "正在上传的文件应移回观察期继续跟踪，而不是删行后从此不受跟踪")
    assert "_strm_suspects.pop" not in body


def test_cooling_suspects_are_not_deleted_from_the_queue():
    body = _func_src("strm_ops.py", "_prune_cooling_suspects")
    assert "forget_key(" in body, (
        "这个 key 此刻在冷却队列里，pop 会把一个还没上传的文件从队列删掉")
    assert "_strm_suspects.pop" not in body


def test_resolved_suspects_retire_to_done():
    body = _func_src("strm_ops.py", "_prune_resolved_suspects")
    assert "retire_key(" in body, "strm 已存在 = 成功终态，应留行而不是删行"


def test_items_endpoint_excludes_done_and_supports_paging():
    body = _func_src("__init__.py", "_api_get_items")
    assert "ACTIVE_STATUSES" in body, "/items 必须按活跃状态取数，不能全表扫描"
    assert "page_by_status" in body
    assert "SELECT * FROM files ORDER BY updated_at" not in body
    assert "retry_count" not in body, "恒为 0 的重试次数列不该再透给看板"
