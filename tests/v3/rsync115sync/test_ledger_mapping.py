"""
台账替身（LedgerMapping）契约测试：dict 语义必须与改造前逐项一致。

The ledger-backed mapping must behave like a plain dict for every idiom the
codebase already uses — including the four that are easy to get subtly wrong
(`pop(k, None)`, `in`, `items()` inside a loop, `sorted(items, key=x[1])`).

**为什么需要这组测试**：本批改造把约 175 处读写点指向了替身，而**一处都没改**。
这意味着替身的行为差异会以"某个分支的静默错误"形式暴露 —— 例如
`pop(k, None)` 若抛 KeyError，用户看到的是"点删除时后台报错"，
而不是任何与存储有关的提示。
"""

import pytest

from app.plugins.rsync115sync.store import (
    STATUS_CANDIDATE, STATUS_PENDING_VERIFY, STATUS_SUSPECT,
    LedgerMapping, Store,
)


def _mk(tmp_path, status=STATUS_CANDIDATE, **kw):
    ledger = Store(tmp_path / "ledger.sqlite3")
    return ledger, LedgerMapping(ledger, status, **kw)


# --------------------------------------------------------------------------
# 逐项对齐 dict 语义
# --------------------------------------------------------------------------

def test_scalar_set_and_get(tmp_path):
    """`q[key] = ts` / `q[key]` —— 冷却队列的用法（值是裸时间戳）。"""
    _, q = _mk(tmp_path)
    q["TV:a.mkv"] = 1000.0
    assert q["TV:a.mkv"] == 1000.0


def test_dict_value_roundtrip(tmp_path):
    """`s[key] = {..}` / `s[key]["ts"]` —— 疑似清单的用法（值是字典）。"""
    _, s = _mk(tmp_path, STATUS_SUSPECT, ts_field="verified_at")
    s["TV:a.mkv"] = {"ts": 5.0}
    assert isinstance(s["TV:a.mkv"], dict)
    assert s["TV:a.mkv"]["ts"] == 5.0


def test_missing_key_raises_keyerror(tmp_path):
    _, q = _mk(tmp_path)
    with pytest.raises(KeyError):
        _ = q["不存在"]


def test_pop_with_default_never_raises(tmp_path):
    """
    `pop(k, None)` 必须永不抛 —— 全仓大量使用（清理路径）。

    默认的 MutableMapping.pop 实现会走 `__getitem__`（对缺失键抛 KeyError），
    所以这里必须自己实现。第一版没写，`pop` 一调用就炸。
    """
    _, q = _mk(tmp_path)
    assert q.pop("不存在", None) is None
    q["k"] = 1.0
    assert q.pop("k", None) == 1.0


def test_pop_without_default_raises(tmp_path):
    """`pop(k)` 对缺失键应抛 KeyError（与 dict 一致）。"""
    _, q = _mk(tmp_path)
    with pytest.raises(KeyError):
        q.pop("不存在")


def test_contains_len_iter_items_keys_values(tmp_path):
    _, q = _mk(tmp_path)
    q["a"] = 1.0
    q["b"] = 2.0
    assert "a" in q and "z" not in q
    assert len(q) == 2
    assert set(iter(q)) == {"a", "b"}
    assert sorted(q.keys()) == ["a", "b"]
    assert sorted(q.values()) == [1.0, 2.0]
    assert sorted(q.items()) == [("a", 1.0), ("b", 2.0)]


def test_iteration_while_mutating_is_safe_when_snapshotted(tmp_path):
    """
    代码里到处写 `for k in list(q.keys()): q.pop(k)`。
    `list()` 快照后修改必须安全（dict 也如此）。
    """
    _, q = _mk(tmp_path)
    for i in range(3):
        q[f"k{i}"] = float(i)
    for k in list(q.keys()):
        q.pop(k, None)
    assert len(q) == 0


def test_update_and_setdefault(tmp_path):
    _, q = _mk(tmp_path)
    q.update({"a": 1.0, "b": 2.0})
    assert len(q) == 2
    assert q.setdefault("a", 9.0) == 1.0        # 已存在 → 不改
    assert q.setdefault("c", 3.0) == 3.0        # 不存在 → 写入
    assert q["c"] == 3.0


def test_clear_only_affects_own_status(tmp_path):
    """
    `clear()` 只清本状态的行 —— 台账是共享表，清错会把别的状态一起删掉。
    """
    ledger, cand = _mk(tmp_path, STATUS_CANDIDATE)
    watch = LedgerMapping(ledger, STATUS_PENDING_VERIFY, ts_field="enqueued_at")
    cand["c1"] = 1.0
    watch["w1"] = 1.0
    cand.clear()
    assert len(cand) == 0
    assert list(watch.keys()) == ["w1"], "clear 误删了其它状态的条目"
    assert len(ledger.by_status(STATUS_PENDING_VERIFY)) == 1


# --------------------------------------------------------------------------
# 持久化与跨实例
# --------------------------------------------------------------------------

def test_writes_reach_sqlite_immediately(tmp_path):
    """写穿：赋值后台账里就该有（不是等退出时才落盘）。"""
    ledger, q = _mk(tmp_path)
    q["TV:a.mkv"] = 123.0
    rows = ledger.by_status(STATUS_CANDIDATE)
    assert len(rows) == 1 and rows[0]["key"] == "TV:a.mkv"


def test_new_instance_reloads_from_ledger(tmp_path):
    """重启（新实例）后从台账恢复 —— 这是本批改造的目的。"""
    ledger, q = _mk(tmp_path)
    q["TV:a.mkv"] = 777.0
    q2 = LedgerMapping(ledger, STATUS_CANDIDATE, ts_field="enqueued_at")
    assert q2["TV:a.mkv"] == 777.0


def test_delete_removes_from_both_cache_and_ledger(tmp_path):
    ledger, q = _mk(tmp_path)
    q["TV:a.mkv"] = 1.0
    del q["TV:a.mkv"]
    assert "TV:a.mkv" not in q
    assert ledger.get("TV:a.mkv") is None


def test_extra_fields_roundtrip_for_suspects(tmp_path):
    """疑似条目的 `origin` / `dest` 必须能带过一轮存取。"""
    ledger, s = _mk(tmp_path, STATUS_SUSPECT, ts_field="verified_at",
                    extra_from_value={"origin": "origin", "dest": "dest"})
    s["TV:a.mkv"] = {"ts": 1.0, "origin": "watch", "dest": "residue"}
    s2 = LedgerMapping(ledger, STATUS_SUSPECT, ts_field="verified_at",
                       extra_from_value={"origin": "origin", "dest": "dest"})
    assert s2["TV:a.mkv"]["origin"] == "watch"
    assert s2["TV:a.mkv"]["dest"] == "residue"


def test_unknown_fields_in_value_are_ignored(tmp_path):
    """
    台账是强 schema：调用方塞进来的未知键**忽略**而不是报错。
    旧代码向疑似条目写过 `force` / `clock` 之类，不能因此崩。
    """
    _, s = _mk(tmp_path, STATUS_SUSPECT, ts_field="verified_at",
               extra_from_value={"origin": "origin"})
    s["TV:a.mkv"] = {"ts": 1.0, "origin": "scan", "某个未来的键": "x"}
    assert s["TV:a.mkv"]["origin"] == "scan"


def test_missing_enqueued_at_gets_current_time(tmp_path):
    """
    `q[k] = ts` 之外的写路径（例如 dict 值里没有时间戳）必须补齐当前时刻 ——
    否则该行没有计时基准，"到期没到期"永远算不出来。
    """
    ledger, q = _mk(tmp_path)
    q["TV:a.mkv"] = {}          # 空字典，没有时间字段
    row = ledger.get("TV:a.mkv")
    assert row["enqueued_at"] is not None


# --------------------------------------------------------------------------
# 降级：台账不可用时不得崩
# --------------------------------------------------------------------------

def test_mapping_degrades_without_ledger(tmp_path):
    """
    台账打不开时，替身仍要有 dict 行为（内存态）—— 不然整个插件都用不了。
    """
    bad = tmp_path / "dir"
    bad.mkdir()
    ledger = Store(bad)
    assert ledger.usable is False
    q = LedgerMapping(ledger, STATUS_CANDIDATE, ts_field="enqueued_at")
    q["a"] = 1.0                # 不得抛
    assert q["a"] == 1.0
    assert q.pop("a", None) == 1.0
