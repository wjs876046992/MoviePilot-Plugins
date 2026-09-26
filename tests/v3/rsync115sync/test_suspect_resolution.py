"""
疑似条目的**自动退场**：strm 后来出现了，就该移出待处理清单。

Automatic retirement of suspects whose .strm has since appeared.

## 这个缺口是怎么暴露的

用户问「疑似列表里多个同文件夹的怎么处理」时，顺着查下去发现：
**巡检只遍历观察期，从不碰疑似清单**。于是一个疑似条目一旦入列就永远不会
因为"strm 后来出现了"而消失，只能在看板上手工「忽略」或「删旧重传」。
而这三种情况都会让它变成假警报：

1. 用户通过**别的途径**补生成了 strm（助手自己的定时任务、手动触发）；
2. 用户手动点了补生成，但**只勾了同目录的一部分**文件 ——
   助手是**按目录**遍历的，没勾的那几个其实也生成了；
3. 用户在 115 侧手工处理好了。

用户原话：「在扫描缺失 strm 时，查找到有 strm 了，就可以进行移除了」——
原实现只在扫描时对观察期与疑似**去重**（不重复登记），漏掉了「已存在却
仍挂在清单里 → 移除」这一步。

## 判据只有一条：`.strm` 文件是否存在

⚠️ 绝不引入 CD2 挂载视图作判据 —— 那套「云端可见性」判定已在 v0.3.0 整条
删除，因为它在**改名失败**这个主成因上必然判错（残留与正式文件字节数相同，
挂载视图照样显示「可见、大小一致」，见 DEVELOPMENT §3.11）。
本组用例里有专门一条钉住这一点。
"""

import importlib
import os
import time

import pytest


def _plugin(root, *, watch=None, suspects=None):
    module = importlib.import_module("app.plugins.rsync115sync")
    src = os.path.join(root, "src")
    strm_dir = os.path.join(root, "strms")
    os.makedirs(src, exist_ok=True)
    os.makedirs(strm_dir, exist_ok=True)

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{
        "name": "电视剧", "src": src, "dest": "/115/TV",
        "strm_dir": strm_dir, "all_ext": False,
    }]
    plugin._strm_watch = dict(watch or {})
    plugin._strm_suspects = dict(suspects or {})
    plugin._strm_gen_requested = {}
    # ⚠️ 冷却队列：扫描要拿它比对（"还没上传的文件不可能有 strm"）。
    # 生产代码里对它是 `getattr` 兜底的 —— 本仓大量最小实例没有这个属性。
    plugin._pending_queue = {}
    plugin._strm_grace_minutes = 5
    plugin._strm_check_enabled = True
    plugin._strm_last_check = 0.0
    plugin._strm_notified = False
    plugin._ignored_rules = []
    plugin._exclude_patterns = ""
    plugin._media_extensions = "mkv"
    plugin._notify = False
    plugin.save_data = lambda k, v: None
    return plugin, src, strm_dir


def _touch_strm(strm_dir, rel):
    """按插件的推导规则造出对应的 .strm 文件。"""
    path = os.path.join(strm_dir, os.path.splitext(rel)[0] + ".strm")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x")


KEY = "电视剧:某剧/Season 01/E01.mkv"


def test_suspect_is_retired_when_strm_exists(tmp_path):
    """
    疑似条目的 .strm 出现后 ⇒ 移出待处理清单。

    这是本组的核心行为，也是用户明确要求的那个动作。
    """
    plugin, src, strm_dir = _plugin(tmp_path, suspects={KEY: {"ts": 1.0, "origin": "scan"}})
    _touch_strm(strm_dir, "某剧/Season 01/E01.mkv")

    resolved = plugin._prune_resolved_suspects()

    assert resolved == [KEY]
    assert KEY not in plugin._strm_suspects, "strm 已存在却仍挂在待处理清单里"


def test_suspect_without_strm_stays(tmp_path):
    """
    ⚠️ 反向：strm **不存在**时条目必须留在清单里。

    少了这条，一个"永远清空清单"的实现也能让上面那条通过 —— 那会把用户
    真正需要处理的文件全部静默放过。
    """
    plugin, src, strm_dir = _plugin(tmp_path, suspects={KEY: {"ts": 1.0, "origin": "scan"}})

    resolved = plugin._prune_resolved_suspects()

    assert resolved == []
    assert KEY in plugin._strm_suspects


def test_same_folder_siblings_are_handled_individually(tmp_path):
    """
    ⚠️ **同目录的多个疑似条目要各自判各自的 .strm**（用户问的正是这个）。

    补生成是**按目录**下发的 —— 助手收到 Season 01 就会把该目录下所有视频都
    生成一遍。所以「只勾了同目录的一部分」时，没勾的那几个也会出现在清单里
    变成假警报。逐个判 .strm 正好覆盖这种情况。
    """
    keys = {
        "电视剧:某剧/Season 01/E01.mkv": {"ts": 1.0, "origin": "scan"},
        "电视剧:某剧/Season 01/E02.mkv": {"ts": 1.0, "origin": "scan"},
        "电视剧:某剧/Season 01/E03.mkv": {"ts": 1.0, "origin": "scan"},
    }
    plugin, _src, strm_dir = _plugin(tmp_path, suspects=keys)
    # 助手遍历整个目录：E01 与 E03 有了，E02 还没有
    _touch_strm(strm_dir, "某剧/Season 01/E01.mkv")
    _touch_strm(strm_dir, "某剧/Season 01/E03.mkv")

    resolved = plugin._prune_resolved_suspects()

    assert sorted(resolved) == sorted([
        "电视剧:某剧/Season 01/E01.mkv",
        "电视剧:某剧/Season 01/E03.mkv",
    ])
    assert list(plugin._strm_suspects) == ["电视剧:某剧/Season 01/E02.mkv"], (
        "只有 E02 该留下 —— 同目录的兄弟各有各的 .strm"
    )


def test_sweep_runs_even_when_watch_list_is_empty(tmp_path):
    """
    ⚠️ **观察清单为空时，巡检也必须跑**（否则疑似条目永远得不到处理）。

    巡检原本的早退条件是 `not self._strm_watch`。而条目走完宽限期后会从
    观察期**移入**疑似清单 —— 也就是说"观察期为空、疑似非空"恰恰是最需要
    检查的时刻，早退会把这条路彻底堵死。
    """
    plugin, _src, strm_dir = _plugin(tmp_path, suspects={KEY: {"ts": 1.0, "origin": "scan"}})
    _touch_strm(strm_dir, "某剧/Season 01/E01.mkv")
    assert not plugin._strm_watch, "本用例前提：观察清单为空"

    result = plugin._strm_check()

    assert result["resolved"] == 1
    assert KEY not in plugin._strm_suspects


def test_sweep_retires_suspects_but_not_watching_entries(tmp_path):
    """
    巡检**只移出疑似清单**，不碰观察期条目（两者是不同状态，判据也不同）。

    观察期条目要走完自己的窗口才结算（`check_one`），若在这里一起清掉，
    「到期未生成 ⇒ 转疑似」这条主流程就断了。
    """
    watching = {"电视剧:某剧/Season 01/E09.mkv": 1.0}
    plugin, _src, strm_dir = _plugin(tmp_path, watch=watching,
                                     suspects={KEY: {"ts": 1.0, "origin": "scan"}})
    _touch_strm(strm_dir, "某剧/Season 01/E01.mkv")
    # 观察期那个文件的 strm 也造出来，确保它若被处理会表现为"解除观察"
    _touch_strm(strm_dir, "某剧/Season 01/E09.mkv")

    result = plugin._strm_check()

    assert result["resolved"] == 1


def test_manual_check_also_retires_suspects(tmp_path):
    """
    「立即检查全部」要一并检查疑似清单（用户原话：「类似『立即检查全部』，
    可以把疑似的也检查一遍」）。
    """
    plugin, _src, strm_dir = _plugin(tmp_path, suspects={KEY: {"ts": 1.0, "origin": "scan"}})
    _touch_strm(strm_dir, "某剧/Season 01/E01.mkv")

    res = plugin._api_strm_check({})

    assert KEY not in plugin._strm_suspects
    assert "已移出待处理清单" in res.get("message", "")


def test_deleted_strm_is_not_a_criterion(tmp_path):
    """
    ⚠️ 判据必须只看"文件在不在"，**不得**引入挂载视图（大小 / 残留名）。

    这条守的是 v0.3.0 那次删除：那套「云端可见性」判定对**改名失败**这个主成因
    必然判错（残留与正式文件字节数相同，挂载视图照样显示「可见、大小一致」），
    已经整条删掉。若这里又把它接回来，用户会再次被引到错误动作上。
    """
    plugin, _src, strm_dir = _plugin(tmp_path, suspects={KEY: {"ts": 1.0, "origin": "scan"}})
    _touch_strm(strm_dir, "某剧/Season 01/E01.mkv")

    import inspect
    src = inspect.getsource(type(plugin)._prune_resolved_suspects)
    for banned in ("getsize", "listdir", "is_temp_residue_name", "dest_probe",
                   "DEST_OK", "DEST_RESIDUE"):
        assert banned not in src, (
            f"疑似退场判据里出现了 `{banned}` —— 那属于已删除的「云端可见性」判定，"
            f"它对改名失败必然判错（见 DEVELOPMENT §3.11）"
        )


def test_resolution_resets_the_notify_latch_when_list_drains(tmp_path):
    """
    清单被清空后要重置通知闩锁 —— 否则「已全部解决」那条通知永远发不出去，
    用户会以为之前的告警被静默遗忘了。
    """
    plugin, _src, strm_dir = _plugin(tmp_path, suspects={KEY: {"ts": 1.0, "origin": "scan"}})
    plugin._strm_notified = True
    _touch_strm(strm_dir, "某剧/Season 01/E01.mkv")
    called = []
    plugin._reset_strm_notified_if_clear = lambda: called.append(True)

    plugin._prune_resolved_suspects()

    assert called, "清单清空后没有重置通知闩锁"


def test_unmapped_pair_is_left_alone(tmp_path):
    """
    映射没配 `strm_dir` 时无从判断，条目**保持原样**。

    那种条目该由 `_prune_invalid_strm_suspects` 按「映射取消验证」清理，
    两处判据不要混（混了会让"没配 strm_dir"变成"strm 不存在"而误清）。
    """
    plugin, _src, _strm_dir = _plugin(tmp_path, suspects={KEY: {"ts": 1.0, "origin": "scan"}})
    plugin._sync_pairs[0]["strm_dir"] = ""

    resolved = plugin._prune_resolved_suspects()

    assert resolved == []
    assert KEY in plugin._strm_suspects

# --------------------------------------------------------------------------
# ⚠️ 冷却期文件不是异常：扫描必须先与冷却队列比对
# --------------------------------------------------------------------------

def test_cooling_file_is_not_reported_as_missing_strm(tmp_path):
    """
    **还在冷却队列里的文件不得被扫成疑似。**

    它按定义**尚未上传**，所以此刻必然没有 `.strm` —— 把它报成疑似是纯粹的
    误报，而用户看到的是"我明明还没到上传时间，怎么就说我文件有问题"。

    用户实测反馈：「还在冷却期未上传，手动扫描 strm，未检查到就放到疑似列表里，
    按理应该先和冷却期的比对」。原实现只比对了忽略规则、观察期、疑似清单三处，
    **唯独漏了冷却队列**，于是每次全量扫描都会把整批正在冷却的文件报成缺 strm。
    """
    plugin, src, strm_dir = _plugin(tmp_path)
    os.makedirs(os.path.join(src, "某剧", "S01"), exist_ok=True)
    with open(os.path.join(src, "某剧", "S01", "E01.mkv"), "wb") as fh:
        fh.write(b"x")
    plugin._pending_queue["电视剧:某剧/S01/E01.mkv"] = time.time()

    plugin._strm_scan()

    assert "电视剧:某剧/S01/E01.mkv" not in plugin._strm_suspects, (
        "冷却期文件被扫成了疑似 —— 它还没上传，不可能有 strm"
    )


def test_scan_reports_how_many_were_skipped_as_cooling(tmp_path):
    """
    跳过数量必须**如实回报** —— 否则用户会以为扫出来的这批漏掉了。

    与 `skipped_watching` / `skipped_ignored` 同一个理由：静默跳过会让用户
    对清单的可信度产生怀疑（"为什么只报了这几个"）。
    """
    plugin, src, _strm_dir = _plugin(tmp_path)
    # 候选来自**真实存在的源端文件**（扫描是走目录的），所以先造出来
    os.makedirs(os.path.join(src, "某剧", "S01"), exist_ok=True)
    with open(os.path.join(src, "某剧", "S01", "E01.mkv"), "wb") as fh:
        fh.write(b"x")
    plugin._pending_queue["电视剧:某剧/S01/E01.mkv"] = time.time()

    res = plugin._strm_scan()

    assert res["data"]["skipped_cooling"] == 1, (
        f"冷却期文件没有被计入跳过：{res['data']}"
    )
    assert "冷却" in res["message"]


def test_keyword_check_also_skips_cooling_files(tmp_path):
    """
    关键字查询（`/rsync_strm <文件名>`）必须与全量扫描**同口径**。

    两处漏一个就会出现"全量扫描不报、按文件名查却报"这种自相矛盾 ——
    而用户恰恰会在收到疑似通知后，用文件名去查那一个。
    """
    plugin, src, _strm_dir = _plugin(tmp_path)
    with open(os.path.join(src, "某剧 S01E01.mkv"), "wb") as fh:
        fh.write(b"x")
    key = "电视剧:某剧 S01E01.mkv"
    plugin._pending_queue[key] = time.time()

    plugin._reply_strm_keyword(None, "某剧")

    assert key not in plugin._strm_suspects, (
        "关键字查询把冷却期文件报成了疑似 —— 与全量扫描口径不一致"
    )


def test_cooling_check_gate_comes_before_suspect_creation():
    """
    结构断言：冷却判据必须在 `_strm_suspects[key] = ...` **之前**。

    顺序写反就等于没写（先入清单再判断），而这类"看起来加了、实际无效"的
    改动不会有任何报错 —— 只能靠结构断言守。
    """
    import ast
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    path = os.path.join(root, "plugins.v3", "rsync115sync", "strm_ops.py")
    tree = ast.parse(open(path, encoding="utf-8").read(), path)

    # 两个入口（全量扫描 / 关键字查询）都要有，且都在创建疑似之前
    for fn_name in ("_strm_scan", "_reply_strm_keyword"):
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == fn_name), None)
        assert fn is not None, f"{fn_name} 不见了"
        src = ast.unparse(fn)
        assert "_pending_queue" in src, f"{fn_name} 里没有冷却队列比对"
        assert src.index("_pending_queue") < src.index("_strm_suspects[key]"), (
            f"{fn_name}: 冷却判据必须排在「写入疑似清单」之前，否则等于没写"
        )

