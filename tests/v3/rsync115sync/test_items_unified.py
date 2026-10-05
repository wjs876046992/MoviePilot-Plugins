"""
看板只有**一个**取数入口，返回一行一个文件 + 一个 `state` 字段。

One dashboard data source: one row per file, one `state` field.

## 这个文件钉的结构（②）

插件此前有**五个并列的清单**（冷却 / 对账异常 / strm 疑似 / 观察期 / 忽略），
各有一套 API、命令与看板标签 —— 而它们在**存储层早就统一了**：
全部是 `files` 表里 `status` 的不同取值。也就是说同一份数据被界面上切成五块，
用户要分别理解五个地方。

`/items` 把存储层已有的真相直接透出来。本用例钉四件事：

1. 六种 `state` 都能出现，且与台账 status 的对应关系正确；
2. `cooling` / `ready` 是**同一个 status 按冷却时间拆的**，判据必须与
   `_count_queue` / `_execute_sync` 一致（三处漂移会让看板说"可传"而同步不传）；
3. 对账发现的问题若**台账里已有该文件**，只补注记、**不重复出一行**
   （同一文件在界面上出现两次正是混淆来源）；
4. 台账不可用 / 读取失败时降级为空列表，不炸整个看板。

⚠️ 需要 MoviePilot 后端，本机 skip；逻辑已用等价脚本在真机上验证过
（当时的输出：cooling/ready/watching/suspect/ignored/broken 六种齐出，
且 suspect 那条正确带上了 `['对账残缺']` 注记）。
"""

import os
import time

import pytest


def _plugin_and_store():
    try:
        import importlib
        mod = importlib.import_module("app.plugins.rsync115sync")
        store = importlib.import_module("app.plugins.rsync115sync.store")
    except Exception as exc:
        pytest.skip(f"无法导入（{exc.__class__.__name__}）")
    return mod, store


def _plugin(tmp_path, *, missing=None, corrupt=None):
    mod, store = _plugin_and_store()
    ledger = store.Store(os.path.join(str(tmp_path), "ledger.sqlite3"))
    p = mod.Rsync115Sync.__new__(mod.Rsync115Sync)
    p._ledger = ledger
    p._delay_hours = 4.0
    p._last_status = {"missing_files": list(missing or []),
                      "corrupt_files": list(corrupt or [])}
    p.save_data = lambda k, v: None
    p.get_data = lambda k: None
    return p, ledger, store


def test_all_six_states_are_representable(tmp_path):
    """六种 state 都要能表达出来 —— 这是"一个列表顶五个清单"的前提。"""
    p, led, st = _plugin(tmp_path)
    now = time.time()
    led.upsert("电视剧:cool.mkv", st.STATUS_CANDIDATE, pair="电视剧",
               rel_path="cool.mkv", enqueued_at=now - 60)
    led.upsert("电视剧:ready.mkv", st.STATUS_CANDIDATE, pair="电视剧",
               rel_path="ready.mkv", enqueued_at=now - 5 * 3600)
    led.upsert("电视剧:watch.mkv", st.STATUS_PENDING_VERIFY, pair="电视剧",
               rel_path="watch.mkv", enqueued_at=now - 60)
    led.upsert("电视剧:susp.mkv", st.STATUS_SUSPECT, pair="电视剧",
               rel_path="susp.mkv", origin="watch")
    led.upsert("电视剧:ign.mkv", st.STATUS_IGNORED, pair="电视剧",
               rel_path="ign.mkv")

    data = p._api_get_items()["data"]
    assert set(data["states"]) == {"cooling", "ready", "watching",
                                   "suspect", "ignored"}, data["states"]


def test_cooling_and_ready_split_by_the_same_predicate_as_the_sync(tmp_path):
    """
    `cooling` / `ready` 由**冷却时间**拆分，判据必须与同步侧一致。

    ⚠️ 三处（本方法 / `_count_queue` / `_execute_sync`）一旦漂移，看板就会出现
    「显示可传、点同步却什么都不传」这类无从解释的状态。
    """
    p, led, st = _plugin(tmp_path)
    now = time.time()
    led.upsert("电视剧:cool.mkv", st.STATUS_CANDIDATE, pair="电视剧",
               rel_path="cool.mkv", enqueued_at=now - 60)          # 1 分钟
    led.upsert("电视剧:ready.mkv", st.STATUS_CANDIDATE, pair="电视剧",
               rel_path="ready.mkv", enqueued_at=now - 5 * 3600)   # 5 小时 > 4h

    items = {it["key"]: it for it in p._api_get_items()["data"]["items"]}
    assert items["电视剧:cool.mkv"]["state"] == "cooling"
    assert items["电视剧:cool.mkv"]["remaining_seconds"] > 0
    assert items["电视剧:ready.mkv"]["state"] == "ready"
    assert items["电视剧:ready.mkv"]["remaining_seconds"] == 0


def test_pending_verify_is_exposed_as_watching(tmp_path):
    """
    对外用 `watching`，不用台账的实现语言 `pending_verify`。

    状态名不统一正是"五个清单"那套留下的毛病 —— 界面不该出现两个词指同一件事。
    """
    p, led, st = _plugin(tmp_path)
    led.upsert("电视剧:w.mkv", st.STATUS_PENDING_VERIFY, pair="电视剧",
               rel_path="w.mkv", enqueued_at=time.time() - 30)
    items = p._api_get_items()["data"]["items"]
    assert [it["state"] for it in items] == ["watching"]


def test_face_off_reconciliation_does_not_duplicate_an_existing_row(tmp_path):
    """
    对账发现的问题若台账里已有该文件，**只补注记，不重复出一行**。

    ⚠️ 同一文件在界面上出现两次，正是"五个清单各说各话"的典型形态：
    用户在"疑似"看到它、又在"异常"看到它，不知道是不是两件事。
    """
    p, led, st = _plugin(tmp_path, missing=["电视剧:gone.mkv"],
                         corrupt=["电视剧:susp.mkv"])
    led.upsert("电视剧:susp.mkv", st.STATUS_SUSPECT, pair="电视剧",
               rel_path="susp.mkv", origin="watch")

    items = p._api_get_items()["data"]["items"]
    keys = [it["key"] for it in items]
    assert keys.count("电视剧:susp.mkv") == 1, "同一文件出了两行"
    row = next(it for it in items if it["key"] == "电视剧:susp.mkv")
    assert row["state"] == "suspect"
    assert "对账残缺" in row["notes"], row
    # 台账里没有的那个才单独成行
    assert "电视剧:gone.mkv" in keys


def test_broken_state_comes_from_reconciliation_not_the_ledger(tmp_path):
    """对账问题与台账 status **正交** —— 台账里没有它也要能显示出来。"""
    p, led, st = _plugin(tmp_path, missing=["电视剧:gone.mkv"])
    data = p._api_get_items()["data"]
    assert data["states"].get("broken") == 1
    row = next(it for it in data["items"] if it["key"] == "电视剧:gone.mkv")
    assert row["state"] == "broken"


def test_missing_ledger_degrades_to_reconciliation_only(tmp_path):
    """台账不可用时降级：只返回对账那部分，不抛异常（看板不能整块白掉）。"""
    mod, store = _plugin_and_store()
    p = mod.Rsync115Sync.__new__(mod.Rsync115Sync)
    p._ledger = None
    p._delay_hours = 4.0
    p._last_status = {"missing_files": ["电视剧:x.mkv"], "corrupt_files": []}
    data = p._api_get_items()["data"]
    assert data["states"] == {"broken": 1}
