"""
忽略只有**一份**真相源：`_ignored_rules`（规则）。v0.7.0 收敛。

## 旧缺陷（2026-09-28 发现，v0.7.0 从根上删除）

忽略曾有**两份存储**，而新增只写一份：

    _ignored_rules（save_data）   用户写的**规则**，支持 contains 模糊匹配
    台账 status='ignored' 的行    具体**文件**的忽略状态（只由一次性迁移写入）

于是 `/items` 的「已忽略」与「已忽略」页的规则列表长期不一致：取消忽略只删
规则，台账行永远留着；新增忽略只写规则，台账行永远不出现。v0.7.0 的做法不是
"把两份写同步"（那仍然有两份），而是**删掉台账那一份**：遗留行一次性转成
exact 规则并删除，之后忽略只认规则。

⚠️ 需要 MoviePilot 后端；本机没有时整组 skip。
"""

import os

import pytest


def _fixture(tmp_path):
    try:
        import importlib
        mod = importlib.import_module("app.plugins.rsync115sync")
        store = importlib.import_module("app.plugins.rsync115sync.store")
    except Exception as exc:
        pytest.skip(f"无法导入（{exc.__class__.__name__}）")
    ledger = store.Store(os.path.join(str(tmp_path), "ledger.sqlite3"))
    p = mod.Rsync115Sync.__new__(mod.Rsync115Sync)
    p._ledger = ledger
    p._ignored_rules = []
    p._failed_files = {}
    p._strm_suspects = {}
    p._strm_watch = {}
    p._strm_gen_requested = {}
    p._last_status = {"missing_files": [], "corrupt_files": []}
    p._strm_notified = False
    p.save_data = lambda k, v: None
    p.get_data = lambda k: None
    return p, ledger, store


def test_ignored_is_no_longer_a_ledger_status():
    """状态词表里不该再有 ignored —— 它是规则，不是文件状态。"""
    try:
        import importlib
        store = importlib.import_module("app.plugins.rsync115sync.store")
    except Exception as exc:
        pytest.skip(f"无法导入（{exc.__class__.__name__}）")
    assert not hasattr(store, "STATUS_IGNORED")
    assert "ignored" not in store.ALL_STATUSES
    assert "ignored" not in store.ACTIVE_STATUSES


def test_legacy_ignored_rows_become_exact_rules_once(tmp_path):
    """遗留的 ignored 行 → exact 规则，且行被删除；重复调用幂等。"""
    p, led, st = _fixture(tmp_path)
    for k in ("电视剧:繁花/S01E01.mkv", "电影:别的/x.mkv"):
        led.upsert(k, "ignored")          # 旧版本写下的行（状态词表已不含它）

    p._migrate_ignored_rows_to_rules()

    got = {(r["rule"], r["match"]) for r in p._ignored_rules}
    assert got == {("电视剧:繁花/S01E01.mkv", "exact"), ("电影:别的/x.mkv", "exact")}
    assert not led.by_status("ignored"), "迁移后台账里不该再有 ignored 行"
    assert led.get_meta("ignored_rows_to_rules") == "1"

    # 幂等：第二次调用不再产生任何变化
    before = [dict(r) for r in p._ignored_rules]
    p._migrate_ignored_rows_to_rules()
    assert p._ignored_rules == before


def test_remove_ignore_rule_only_touches_the_rules_list(tmp_path):
    """取消忽略只删规则；台账里没有需要同步删除的行（它本来就不该有）。"""
    p, led, st = _fixture(tmp_path)
    p._ignored_rules = [{"rule": "繁花", "match": "contains"},
                        {"rule": "电影:别的/x.mkv", "match": "exact"}]

    assert p._remove_ignore_rule("繁花") is True
    assert [r["rule"] for r in p._ignored_rules] == ["电影:别的/x.mkv"]
    assert not led.by_status("ignored")


def test_ignore_add_removes_the_failed_row_so_it_cannot_resurrect(tmp_path):
    """
    忽略一个已判失败的文件：它必须从台账里**真正移除**。

    ⚠️ 只摘缓存是不够的：`/items` 直接按 status 取数，行仍是 failed 的话
    看板立刻又显示成 broken；重载后 `LedgerMapping._load()` 还会把它重新载入，
    于是它继续阻塞调度 —— 正是用户报过的「忽略了没用」。
    """
    p, led, st = _fixture(tmp_path)
    p._failed_files = st.LedgerMapping(led, st.STATUS_FAILED,
                                       ts_field="verified_at",
                                       extra_from_value={"reason": "fail_reason"})
    key = "电视剧:繁花/S01E01.mkv"
    p._failed_files[key] = {"ts": 1.0, "reason": "missing"}
    assert led.get(key)["status"] == st.STATUS_FAILED

    p._add_ignore_rule("繁花", match="contains")

    assert key not in p._failed_files
    assert led.get(key) is None, "忽略必须删行，否则重载后会复活"

    # 重载后也不该再出现
    reloaded = st.LedgerMapping(led, st.STATUS_FAILED,
                                ts_field="verified_at",
                                extra_from_value={"reason": "fail_reason"})
    assert key not in reloaded


def test_preserved_contains_rules_survive_the_row_migration(tmp_path):
    """迁移遗留行时**不能**覆盖用户已有的关键字规则（v0.7.0 review 发现）。"""
    p, led, st = _fixture(tmp_path)
    p._ignored_rules = [{"rule": "繁花", "match": "contains"}]
    led.upsert("电视剧:繁花/S01E01.mkv", "ignored")

    p._migrate_ignored_rows_to_rules()

    rules = [(r["rule"], r["match"]) for r in p._ignored_rules]
    assert ("繁花", "contains") in rules, "用户原有的包含规则被覆盖了"
    assert ("电视剧:繁花/S01E01.mkv", "exact") in rules
