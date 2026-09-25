"""
strm 交叉验证的状态机与期望路径单测。

Tests for the strm cross-validation state machine. This is the only mechanism that
can detect a "CD2 fake success" (mount shows the file as present and correctly
sized while 115 actually holds a rename-failed partial), so its transition
boundaries are worth exhausting here rather than discovering in production.
"""

import os
import time

import pytest

from app.plugins.rsync115sync import strm


def _pair(name="TV", src="/media/TV", strm_dir="/strm/TV"):
    return {"name": name, "src": src, "dest": "/115/TV", "strm_dir": strm_dir}


# --------------------------------------------------------------------------
# expected_path —— 用户必须自己保证 strm 插件与整理后文件同名
# --------------------------------------------------------------------------

def test_expected_path_swaps_extension_only():
    assert strm.expected_path("TV:a/b.mkv", [_pair()]) == os.path.join("/strm/TV", "a/b.strm")


def test_expected_path_keeps_directory_structure():
    """目录结构必须与源端一致，否则查的是别的文件。"""
    got = strm.expected_path("TV:剧集/Season 01/剧名 S01E03.mkv", [_pair()])
    assert got == os.path.join("/strm/TV", "剧集/Season 01/剧名 S01E03.strm")


def test_expected_path_strips_extension_not_appends():
    """
    只换扩展名、不倒着拼：`a.mkv` → `a.strm`（不是 `a.mkv.strm`）。
    多段扩展名的文件按**最后一个点**切分。
    """
    assert strm.expected_path("TV:a.b.mkv", [_pair()]).endswith("a.b.strm")


@pytest.mark.parametrize("strm_dir", ["", "   ", "/"])
def test_expected_path_none_without_strm_dir_configured(strm_dir):
    """留空 = 该映射不启用验证。`/` 也会被 rstrip 成空串，同样视为未配置。"""
    assert strm.expected_path("TV:a/b.mkv", [_pair(strm_dir=strm_dir)]) is None


def test_expected_path_none_for_unmatched_pair():
    assert strm.expected_path("其它:a.mkv", [_pair()]) is None
    assert strm.expected_path("TV:a.mkv", []) is None


def test_expected_path_tolerates_trailing_slash_in_config():
    got = strm.expected_path("TV:a/b.mkv", [_pair(strm_dir="/strm/TV/")])
    assert got == os.path.join("/strm/TV", "a/b.strm")


# --------------------------------------------------------------------------
# source_root_of
# --------------------------------------------------------------------------

def test_source_root_of_resolves_owning_pair():
    assert strm.source_root_of("TV:a.mkv", [_pair(src="/media/TV/")]) == "/media/TV"


def test_source_root_of_none_when_unmatched():
    assert strm.source_root_of("其它:a.mkv", [_pair()]) is None


# --------------------------------------------------------------------------
# classify_watch —— 五态流转
# --------------------------------------------------------------------------

def test_watching_inside_grace_window():
    """宽限期内一律继续观察：strm 生成不实时，早了会误报。"""
    state, record = strm.classify_watch(
        "TV:a.mkv", synced_ts=0, now_ts=100, grace_secs=6 * 3600,
        pairs=[_pair()], strm_exists=False, src_exists=True)
    assert state == strm.WATCHING
    assert record == "TV:a.mkv"


def test_suspect_when_grace_expired_without_strm():
    state, record = strm.classify_watch(
        "TV:a.mkv", synced_ts=0, now_ts=6 * 3600, grace_secs=6 * 3600,
        pairs=[_pair()], strm_exists=False, src_exists=True)
    assert state == strm.SUSPECT
    assert record == "TV:a.mkv"


def test_grace_boundary_exactly_at_deadline_is_suspect():
    """恰好到期即判定（>= 而非 >），与拆分前行为一致。"""
    state, _ = strm.classify_watch(
        "TV:a.mkv", synced_ts=0, now_ts=21600, grace_secs=21600,
        pairs=[_pair()], strm_exists=False, src_exists=True)
    assert state == strm.SUSPECT


def test_grace_boundary_one_second_before_is_still_watching():
    state, _ = strm.classify_watch(
        "TV:a.mkv", synced_ts=0, now_ts=21599, grace_secs=21600,
        pairs=[_pair()], strm_exists=False, src_exists=True)
    assert state == strm.WATCHING


def test_settled_when_strm_appeared():
    state, record = strm.classify_watch(
        "TV:a.mkv", synced_ts=0, now_ts=99999, grace_secs=21600,
        pairs=[_pair()], strm_exists=True, src_exists=True)
    assert state == strm.SETTLED
    assert record is None


def test_strm_appearing_before_deadline_settles_immediately():
    """strm 一生成就立刻解除，不必等宽限期走完。"""
    state, _ = strm.classify_watch(
        "TV:a.mkv", synced_ts=0, now_ts=60, grace_secs=21600,
        pairs=[_pair()], strm_exists=True, src_exists=True)
    assert state == strm.SETTLED


def test_source_gone_cleans_up_even_past_deadline():
    """
    源端消失 → 清理，**不转疑似**：文件都没了，既无从验证也无从重传。
    若误判为疑似，用户会在看板上看到永远处理不掉的条目。
    """
    state, record = strm.classify_watch(
        "TV:a.mkv", synced_ts=0, now_ts=99999, grace_secs=21600,
        pairs=[_pair()], strm_exists=False, src_exists=False)
    assert state == strm.SOURCE_GONE
    assert record is None


def test_source_gone_wins_over_strm_exists():
    """
    源端已消失、而 strm 恰好还在 → 按「源端消失」清理，而不是记成正常解除。
    判定顺序是承重的，写反会让巡检的 ok 计数长期失真。
    """
    state, _ = strm.classify_watch(
        "TV:a.mkv", synced_ts=0, now_ts=99999, grace_secs=21600,
        pairs=[_pair()], strm_exists=True, src_exists=False)
    assert state == strm.SOURCE_GONE


def test_no_strm_dir_wins_over_everything():
    """映射被改成没有 strm_dir 后，观察项立即失效，与其它条件无关。"""
    for strm_exists in (True, False):
        for src_exists in (True, False):
            state, _ = strm.classify_watch(
                "TV:a.mkv", synced_ts=0, now_ts=99999, grace_secs=21600,
                pairs=[_pair(strm_dir="")],
                strm_exists=strm_exists, src_exists=src_exists)
            assert state == strm.NO_STRM_DIR


def test_unmatched_key_is_cleaned_up():
    """key 不再属于任何映射（映射被删/改名）→ 清理，否则永远挂在观察期。"""
    state, _ = strm.classify_watch(
        "已删除的映射:a.mkv", synced_ts=0, now_ts=99999, grace_secs=21600,
        pairs=[_pair()], strm_exists=False, src_exists=True)
    assert state == strm.NO_STRM_DIR


# --------------------------------------------------------------------------
# grace_secs_of —— 单位是**分钟**（2026-09-25 从小时改过来），下限防误报
# --------------------------------------------------------------------------

def test_grace_secs_of_normal_value():
    """5 分钟 → 300 秒。"""
    assert strm.grace_secs_of(5) == 300.0
    assert strm.grace_secs_of(60) == 3600.0


def test_grace_secs_of_enforces_minimum():
    """0 或负数会把「还在上传中」直接判成异常，必须被抬到下限。"""
    assert strm.grace_secs_of(0) == strm.MIN_GRACE_MINUTES * 60
    assert strm.grace_secs_of(-5) == strm.MIN_GRACE_MINUTES * 60
    assert strm.grace_secs_of(0.1) == strm.MIN_GRACE_MINUTES * 60


@pytest.mark.parametrize("bad", [None, "", "abc", [], {}])
def test_grace_secs_of_invalid_input_falls_back_to_default(bad):
    """配置里出现脏值（v-model.number 曾写回过 NaN 这类）时回退默认，不抛异常。"""
    assert strm.grace_secs_of(bad) == strm.DEFAULT_GRACE_MINUTES * 60


def test_grace_secs_of_accepts_numeric_string():
    """前端 v-model 可能传来字符串，必须能解析。"""
    assert strm.grace_secs_of("45") == 2700.0


def test_grace_default_is_five_minutes():
    """
    默认宽限期 = 5 分钟。钉住它是为了防止"改单位时顺手改错量级" ——
    5 秒或 5 小时都能跑，但前者会大面积误报、后者会让功能形同虚设。
    """
    assert strm.DEFAULT_GRACE_MINUTES == 5
    assert strm.grace_secs_of(strm.DEFAULT_GRACE_MINUTES) == 300.0


def test_grace_secs_of_is_minutes_not_hours():
    """
    ⚠️ 单位回归哨兵：6 这个值必须被解释成 **6 分钟**（360 秒），不是 6 小时。

    这条用例存在的意义就是"单位改回去时它会红"。旧版 `grace_secs_of(6) == 21600`
    测试的正是小时语义，这次改单位时它整条被替换（而不是改个数字）——
    因为**单位本身**才是被测试的对象。
    """
    assert strm.grace_secs_of(6) == 360.0, (
        "宽限期的单位是分钟；若这里又变回 21600，说明有人把单位改回了小时，"
        "而配置页与文档都写着分钟"
    )


# watch_state_of —— 计时基准（双钟问题的唯一防线）
# --------------------------------------------------------------------------

def test_watch_state_prefers_gen_clock_when_requested():
    """
    有补生成记录时，基准取**请求时刻**，不是 watch 里的同步时刻。

    两个时间戳差得很远（同步是几小时前、请求是刚刚），取错哪一个都会让
    重新计时窗口算出一个完全不同的到期时间。
    """
    now = time.time()
    watch = {"TV:a.mkv": now - 7200}
    gen = {"TV:a.mkv": now - 60}

    kind, ts = strm.watch_state_of("TV:a.mkv", watch, gen, now)

    assert kind == "gen"
    assert ts == gen["TV:a.mkv"]


def test_watch_state_falls_back_to_sync_clock():
    """没有补生成记录时用同步时刻 —— 普通观察期的原有语义不得被改变。"""
    now = time.time()
    watch = {"TV:a.mkv": now - 100}

    kind, ts = strm.watch_state_of("TV:a.mkv", watch, {}, now)

    assert kind == "sync"
    assert ts == watch["TV:a.mkv"]


def test_watch_state_unknown_key_defaults_to_now():
    """
    两个字典都没有这个 key 时退回 now（= 仍在宽限期内）。

    与 classify_watch 里那个同类的兜底同一取向：宁可让一个不该存在的条目多留
    一轮，也不要把「不知道」当成「已到期」而误报上传异常。
    """
    now = time.time()

    kind, ts = strm.watch_state_of("TV:x.mkv", {}, {}, now)

    assert kind == "sync"
    assert ts == now


@pytest.mark.parametrize("bad", [None, "abc", object()])
def test_watch_state_tolerates_corrupt_timestamps(bad):
    """数据文件里出现非数字时间戳时不得抛异常 —— 巡检会因此整轮中断。"""
    now = time.time()
    kind, ts = strm.watch_state_of("TV:a.mkv", {"TV:a.mkv": bad}, {}, now)
    assert kind == "sync"
    assert ts == now


# --------------------------------------------------------------------------
# regrace_secs —— 以请求时刻为锚，绝不随读取顺延
# --------------------------------------------------------------------------

def test_regrace_counts_down_from_request_time():
    now = time.time()
    assert strm.regrace_secs(now - 600, now) == pytest.approx(strm.REGRACE_HOURS * 3600 - 600)


def test_regrace_is_anchored_not_rebased_on_read():
    """
    ⚠️ 承重断言：剩余时间**只**由请求时刻决定，与「现在几点」无关 ——
    换句话说，同一请求连读两次，剩余量必须严格递减（而不是每次刷新都重置）。

    写反的后果不是误差，而是功能失效：看板每 30 秒读一次状态，若每次读取都把
    窗口顺延一次，条目永远到不了期，用户看到的是「怎么等都不出结果」，
    而且越看越久。
    """
    req = time.time() - 1800
    first = strm.regrace_secs(req, req + 1800)
    second = strm.regrace_secs(req, req + 2400)

    assert second < first, "再次读取必须得到更短的剩余时间，而不是重置窗口"


def test_regrace_goes_non_positive_after_window():
    now = time.time()
    assert strm.regrace_secs(now - strm.REGRACE_HOURS * 3600 - 10, now) <= 0
