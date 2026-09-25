"""
strm 疑似条目的「忽略」操作：以精确匹配加入忽略规则并移出疑似清单。

Ignore action for strm suspect entries: add an exact-match ignore rule and drop
the entry from the suspect list.

**为什么有这条测试**：忽略操作有两条错误实现方向，都会让用户的操作变成
「看起来点了、实际没用」——
  1. 只把条目从疑似清单删掉：下一轮同步/巡检会把同一个文件再报一遍，
     清单永远清不干净；
  2. 直接操作清单 + 自己写盘：与 `_add_ignore_rule` 的联动清理
     （missing/corrupt 联动、通知闩锁重置）形成两份真相。
因此这里钉住三件事：走 `_add_ignore_rule`（持久判定）、
匹配方式必须是 exact（contains 会误杀同目录同名集数）、
护栏与 /strm_retry 同口径（只接受疑似清单内的 key）。
"""

import importlib
import os

KEY = "电视剧:a.mkv"
OTHER = "电视剧:other.mkv"


def _plugin(root, *, suspects=None):
    """最小实例：只带忽略路径用到的状态。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    src = os.path.join(root, "src")
    os.makedirs(src, exist_ok=True)
    with open(os.path.join(src, "a.mkv"), "wb") as fh:
        fh.write(b"x")

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{
        "name": "电视剧", "src": src, "dest": os.path.join(root, "dest"),
        "strm_dir": os.path.join(root, "strm"), "pan_dir": "/HomeTheater/TV",
        "all_ext": False,
    }]
    plugin._exclude_patterns = "@eaDir/"
    plugin._media_extensions = "mkv"
    plugin._ignored_rules = []
    plugin._strm_check_enabled = True
    plugin._strm_grace_minutes = 360
    plugin._strm_last_check = 0.0
    plugin._strm_notified = True
    plugin._strm_gen_requested = {}
    plugin._strm_watch = {}
    plugin._strm_suspects = dict(suspects or {})
    # _last_status 里放一条同映射的缺失文件，验证 _add_ignore_rule 的联动清理
    plugin._last_status = {"missing_files": [KEY], "corrupt_files": []}
    plugin._notify = False
    plugin._is_running = False
    saved = {}
    plugin.save_data = lambda k, v: saved.__setitem__(k, v)
    plugin.get_data = lambda k: None
    plugin.post_message = lambda **kw: None
    plugin._saved = saved
    return plugin


# --------------------------------------------------------------------------
# 正常路径
# --------------------------------------------------------------------------

def test_ignore_adds_exact_rule_and_purges_suspect(tmp_path):
    """忽略 = 精确匹配规则入库 + 条目移出疑似清单 + 落盘。"""
    plugin = _plugin(str(tmp_path), suspects={KEY: {"dest": "ok"}})

    res = plugin._api_strm_ignore({"keys": [KEY]})

    assert res["success"] is True
    assert KEY not in plugin._strm_suspects, "忽略后必须立即移出疑似清单"
    assert len(plugin._ignored_rules) == 1
    rule = plugin._ignored_rules[0]
    assert rule["rule"] == KEY
    assert rule["match"] == "exact", "看板忽略必须用精确匹配，contains 会误杀同名集数"
    assert plugin._saved.get("ignored_files"), "忽略规则必须落盘"
    assert plugin._saved.get("strm_suspects") == {}


def test_ignore_does_not_touch_unrelated_entries(tmp_path):
    """忽略一条只影响一条，清单里的其它条目原样保留。"""
    plugin = _plugin(str(tmp_path), suspects={KEY: {"dest": "ok"}, OTHER: {"dest": "ok"}})

    res = plugin._api_strm_ignore({"keys": [KEY]})

    assert res["success"] is True
    assert OTHER in plugin._strm_suspects, "未请求的条目必须原样保留"


def test_ignore_purges_missing_files_list_too(tmp_path):
    """忽略走 _add_ignore_rule 的完整联动：missing 清单里的同 key 也被剔除。"""
    plugin = _plugin(str(tmp_path), suspects={KEY: {"dest": "ok"}})
    assert KEY in plugin._last_status["missing_files"]

    plugin._api_strm_ignore({"keys": [KEY]})

    assert KEY not in plugin._last_status["missing_files"], (
        "忽略必须联动清理缺失清单，否则同文件仍显示在对账异常里"
    )


def test_ignore_resets_notify_latch_when_list_drains(tmp_path):
    """疑似清单被清空时通知闩锁必须重置 —— 否则下一次新发现不再提醒。"""
    plugin = _plugin(str(tmp_path), suspects={KEY: {"dest": "ok"}})
    assert plugin._strm_notified is True

    plugin._api_strm_ignore({"keys": [KEY]})

    assert plugin._strm_notified is False, "清单清空后必须重置通知闩锁"


# --------------------------------------------------------------------------
# 护栏（与 /strm_retry 同口径）
# --------------------------------------------------------------------------

def test_ignore_rejects_keys_not_in_suspect_list(tmp_path):
    """只接受疑似清单内的 key —— 不允许构造任意路径写忽略规则。"""
    plugin = _plugin(str(tmp_path), suspects={})
    res = plugin._api_strm_ignore({"keys": ["电视剧:随便/造的.mkv"]})
    assert res["success"] is False
    assert plugin._ignored_rules == []


def test_ignore_with_no_keys_is_rejected(tmp_path):
    plugin = _plugin(str(tmp_path), suspects={KEY: {"dest": "ok"}})
    assert plugin._api_strm_ignore({"keys": []})["success"] is False


def test_ignore_only_touches_requested_keys(tmp_path):
    """混合请求时：清单内的被处理，清单外的被拒（且不落任何规则）。"""
    plugin = _plugin(str(tmp_path), suspects={KEY: {"dest": "ok"}})

    res = plugin._api_strm_ignore({"keys": [KEY, "电视剧:越权.mkv"]})

    assert res["success"] is True
    assert KEY not in plugin._strm_suspects
    assert len(plugin._ignored_rules) == 1, "越权 key 不得产生忽略规则"


def test_ignore_duplicate_request_is_idempotent(tmp_path):
    """重复忽略同一文件：规则已存在 → 提示未做改动，不产生重复规则。"""
    plugin = _plugin(str(tmp_path), suspects={KEY: {"dest": "ok"}})
    plugin._api_strm_ignore({"keys": [KEY]})
    plugin._strm_suspects[KEY] = {"dest": "ok"}  # 模拟清单又报回来

    res = plugin._api_strm_ignore({"keys": [KEY]})

    assert res["success"] is True
    assert len(plugin._ignored_rules) == 1, "不得产生重复规则"
    assert res["data"]["already_ignored"] == [KEY]


# --------------------------------------------------------------------------
# 契约：端点注册
# --------------------------------------------------------------------------

def test_strm_ignore_endpoint_registered():
    """看板前端会 post /strm_ignore，端点漏注册会让按钮静默失效。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    import inspect
    # 端点表在实例方法 get_api 里构造，检查源码中包含注册项即可
    src = inspect.getsource(module.Rsync115Sync)
    assert '"/strm_ignore"' in src
