"""
目标端可见性探测：把「云端到底有没有这个文件」变成一次纯本地读取。

Destination-visibility probe: turning "does the cloud actually have this file" into
a purely local read of the CD2 mount.

**为什么需要它**：补生成之后仍无 strm 时，本地视角分不出四种成因（助手没识别 /
助手压根没执行 / 从未上传 / 改名失败只剩残留），用户只能自己猜。而目标端就在
挂载里 —— 读它的大小零 115 API，能把其中三种直接分开。

**它绝不能做的事**（这几条都是承重约束，不是注释）：

1. **不能作为「已同步」的证据**。3.11 的「CD2 假成功」正是：视图显示大小正常，
   而 115 上只有改名失败的残留（残留大小与正式文件一致，见 3.10）。
   该结论的假阳性方向是「把坏文件看成好的」—— 拿它去跳过上传会真的漏掉坏文件。
2. **不能参与清单清理判据**。同上：据此把条目从清单里摘掉，等于让一个真坏文件
   从此不再被提醒。
3. **只能用来拦下「删旧重传」**（唯一一处影响行为的地方）。那个方向上即使判错，
   代价也只是「让用户去查一下助手」——多看一眼，不会漏处理。

**挂载未就绪必须整体退化成 unknown**：`dest` 根目录读不到时，`os.path.exists`
对每个文件都返回 False —— 照此判定会给整批扣上「云端没有文件」的帽子，
而真相只是 CD2 没挂上。
"""

import importlib
import os
import time

import pytest

from app.plugins.rsync115sync import strm


def _plugin(root, *, suspects=None, dest_exists=True):
    """构造最小实例：源端与 dest 挂载点都是真实目录，便于控制可见性。"""
    module = importlib.import_module("app.plugins.rsync115sync")
    src = os.path.join(root, "src")
    dest = os.path.join(root, "dest")
    os.makedirs(src, exist_ok=True)
    if dest_exists:
        os.makedirs(dest, exist_ok=True)

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [{
        "name": "电视剧", "src": src, "dest": dest,
        "strm_dir": os.path.join(root, "strm"), "pan_dir": "/HomeTheater/TV",
        "all_ext": False,
    }]
    plugin._strm_suspects = dict(suspects or {})
    plugin._strm_watch = {}
    plugin._strm_gen_requested = {}
    plugin._ignored_rules = []
    plugin.save_data = lambda k, v: None
    return plugin


def _write(path, content=b"x" * 100):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)


KEY = "电视剧:a.mkv"


# --------------------------------------------------------------------------
# 出口一：云端不可见（真的没传上去 / 改名失败只剩残留）
# --------------------------------------------------------------------------

def test_absent_when_dest_file_missing(tmp_path):
    plugin = _plugin(str(tmp_path))
    _write(os.path.join(plugin._sync_pairs[0]["src"], "a.mkv"))

    assert plugin._dest_visibility([KEY])[KEY] == strm.DEST_ABSENT


def test_absent_when_dest_directory_missing_but_mount_ok(tmp_path):
    """挂载在、但该文件的上级目录都没有 —— 同样是「云端不可见」。"""
    plugin = _plugin(str(tmp_path))
    _write(os.path.join(plugin._sync_pairs[0]["src"], "季/集/a.mkv"))

    assert plugin._dest_visibility(["电视剧:季/集/a.mkv"])["电视剧:季/集/a.mkv"] \
        == strm.DEST_ABSENT


# --------------------------------------------------------------------------
# 出口二/三：可见但大小不符 / 可见且一致
# --------------------------------------------------------------------------

def test_mismatch_when_sizes_differ(tmp_path):
    plugin = _plugin(str(tmp_path))
    pair = plugin._sync_pairs[0]
    _write(os.path.join(pair["src"], "a.mkv"), b"x" * 100)
    _write(os.path.join(pair["dest"], "a.mkv"), b"x" * 40)

    assert plugin._dest_visibility([KEY])[KEY] == strm.DEST_SIZE_MISMATCH


def test_ok_when_sizes_match(tmp_path):
    plugin = _plugin(str(tmp_path))
    pair = plugin._sync_pairs[0]
    _write(os.path.join(pair["src"], "a.mkv"), b"x" * 100)
    _write(os.path.join(pair["dest"], "a.mkv"), b"x" * 100)

    assert plugin._dest_visibility([KEY])[KEY] == strm.DEST_OK


# --------------------------------------------------------------------------
# 出口四：探测无效（挂载未就绪）—— 这条最容易误判
# --------------------------------------------------------------------------

def test_mount_not_ready_yields_unknown_not_absent(tmp_path):
    """
    ⚠️ 承重断言：CD2 未挂载时，**不得**把整批判成「云端没有文件」。

    `os.path.exists` 在挂载点消失时对每个文件都返回 False。若直接采信，
    用户会看到「云端不可见 → 删旧重传可修」的建议，并据此删掉一批好文件 ——
    而真正的问题是挂载没就绪。
    """
    plugin = _plugin(str(tmp_path), dest_exists=False)
    _write(os.path.join(plugin._sync_pairs[0]["src"], "a.mkv"))

    verdict = plugin._dest_visibility([KEY])[KEY]

    assert verdict == strm.DEST_UNKNOWN
    assert verdict != strm.DEST_ABSENT


def test_unknown_when_pair_has_no_dest_root(tmp_path):
    """映射没填 dest：无从探测，退化成 unknown 而不是猜一个路径出来。"""
    plugin = _plugin(str(tmp_path))
    _write(os.path.join(plugin._sync_pairs[0]["src"], "a.mkv"))
    plugin._sync_pairs[0]["dest"] = ""

    assert plugin._dest_visibility([KEY])[KEY] == strm.DEST_UNKNOWN


def test_probe_is_read_only(tmp_path):
    """探测只读：不得创建、删除或改动任何文件（它跑在清单维护路径上）。"""
    plugin = _plugin(str(tmp_path))
    pair = plugin._sync_pairs[0]
    _write(os.path.join(pair["src"], "a.mkv"), b"x" * 100)
    _write(os.path.join(pair["dest"], "a.mkv"), b"x" * 100)
    before = sorted(os.listdir(pair["dest"]))

    plugin._dest_visibility([KEY])

    assert sorted(os.listdir(pair["dest"])) == before


# --------------------------------------------------------------------------
# 唯一一处影响行为的地方：删旧重传前的拦截
# --------------------------------------------------------------------------

def test_retry_is_blocked_when_cloud_copy_looks_intact(tmp_path):
    """
    云端可见且大小一致 → 拦下删旧重传，并明确说明理由。

    删掉是纯浪费：rsync `--size-only` 会因为大小一致而跳过，文件根本传不上去，
    用户白白损失一次云端删除 + 一次限流配额，最后问题原样还在。
    """
    plugin = _plugin(str(tmp_path), suspects={KEY: {"ts": time.time(), "origin": "scan"}})
    pair = plugin._sync_pairs[0]
    _write(os.path.join(pair["src"], "a.mkv"), b"x" * 100)
    _write(os.path.join(pair["dest"], "a.mkv"), b"x" * 100)
    plugin._is_running = False
    plugin._delete_dest_files_for_retry = lambda keys: pytest.fail(
        "被拦下时不得执行任何删除")

    res = plugin._api_strm_retry({"keys": [KEY]})

    assert res["success"] is False
    assert "云端" in res["message"]
    assert "strm" in res["message"], "应把用户导向生成侧排查，而不是只丢一个失败"


def test_retry_proceeds_when_cloud_copy_is_absent(tmp_path):
    """
    ⚠️ 反过来必须放行：云端不可见时删旧重传正是对症的。

    这条守的是「探测不能把功能整体闸死」—— 若把 unknown/absent 也一并拦下，
    用户对着一批真的没传上去的文件将完全无计可施，而那正是本功能要解决的问题。
    （云端没有文件时删除是空操作，见 `_delete_dest_files_for_retry`。）
    """
    plugin = _plugin(str(tmp_path), suspects={KEY: {"ts": time.time(), "origin": "scan"}})
    pair = plugin._sync_pairs[0]
    _write(os.path.join(pair["src"], "a.mkv"), b"x" * 100)
    # dest 端刻意留空 → 云端不可见
    called = {}
    plugin._delete_dest_files_for_retry = lambda keys: (called.setdefault("keys", keys), ([], []))[1]
    plugin._start_sync_thread = lambda **kw: called.setdefault("started", kw)
    plugin._is_running = False

    res = plugin._api_strm_retry({"keys": [KEY]})

    assert res["success"] is True
    assert called.get("keys") == [KEY], "云端不可见时必须照常走删除重传通道"


def test_retry_proceeds_when_mount_not_ready(tmp_path):
    """
    探测无效时放行（fail-open），而不是一律拦下。

    这是本功能唯一能接受的方向：`unknown` 拦人的话，CD2 一抖动用户就完全无法
    处理疑似清单 —— 而那批条目很可能真的该删旧重传。
    """
    plugin = _plugin(str(tmp_path), suspects={KEY: {"ts": time.time(), "origin": "scan"}},
                     dest_exists=False)
    _write(os.path.join(plugin._sync_pairs[0]["src"], "a.mkv"), b"x" * 100)
    called = {}
    plugin._delete_dest_files_for_retry = lambda keys: (called.setdefault("keys", keys), ([], []))[1]
    plugin._start_sync_thread = lambda **kw: None
    plugin._is_running = False

    res = plugin._api_strm_retry({"keys": [KEY]})

    assert res["success"] is True
    assert called.get("keys") == [KEY]


def test_retry_reprobes_instead_of_trusting_stored_verdict(tmp_path):
    """
    ⚠️ 重传前**重新探测**，不复用清单里那份陈旧结论。

    清单里的结论来自入清单那一刻（可能是一小时前），用户是看到建议之后才点的
    按钮 —— 中间完全可能又跑过一次同步，文件已经传好了。拿旧结论决定要不要删，
    等于用一个过期的事实做破坏性判断。
    """
    plugin = _plugin(str(tmp_path), suspects={KEY: {"ts": time.time(), "origin": "scan"}})
    pair = plugin._sync_pairs[0]
    _write(os.path.join(pair["src"], "a.mkv"), b"x" * 100)
    # 清单里存的是「云端不可见」（入清单时的探测结果）
    plugin._strm_suspects[KEY]["dest"] = strm.DEST_ABSENT
    # 但现在 dest 端其实已经有大小一致的文件了（期间同步成功过）
    _write(os.path.join(pair["dest"], "a.mkv"), b"x" * 100)
    plugin._delete_dest_files_for_retry = lambda keys: pytest.fail(
        "陈旧结论不得被采信：应重新探测并拦下")
    plugin._is_running = False

    res = plugin._api_strm_retry({"keys": [KEY]})

    assert res["success"] is False


# --------------------------------------------------------------------------
# 清单注解：给新条目附上结论，但不参与清理
# --------------------------------------------------------------------------

def test_annotate_writes_verdict_into_entry(tmp_path):
    plugin = _plugin(str(tmp_path), suspects={KEY: {"ts": time.time(), "origin": "scan"}})
    _write(os.path.join(plugin._sync_pairs[0]["src"], "a.mkv"), b"x" * 100)

    plugin._annotate_dest([KEY])

    assert plugin._strm_suspects[KEY]["dest"] == strm.DEST_ABSENT


def test_annotate_never_removes_entries(tmp_path):
    """
    ⚠️ 承重断言：探测结论**只写不删**。

    假阳性方向是「把坏文件看成好的」—— 若据此把条目从清单里摘掉，
    一个真正的坏文件会从此不再被提醒，后果与用户主动「忽略」它一样严重，
    而且用户并不知道自己忽略了它。
    """
    plugin = _plugin(str(tmp_path), suspects={KEY: {"ts": time.time(), "origin": "scan"}})
    pair = plugin._sync_pairs[0]
    _write(os.path.join(pair["src"], "a.mkv"), b"x" * 100)
    _write(os.path.join(pair["dest"], "a.mkv"), b"x" * 100)  # 看着完好

    plugin._annotate_dest([KEY])

    assert KEY in plugin._strm_suspects, "看着完好也不得从清单里摘掉"
    assert plugin._strm_suspects[KEY]["dest"] == strm.DEST_OK


def test_annotate_failure_does_not_break_list_maintenance(tmp_path):
    """探测抛异常时必须吞掉：它只是附加信息，不能让清单维护本身失败。"""
    plugin = _plugin(str(tmp_path), suspects={KEY: {"ts": time.time(), "origin": "scan"}})
    plugin._dest_visibility = lambda keys: (_ for _ in ()).throw(RuntimeError("挂载炸了"))

    plugin._annotate_dest([KEY])  # 不得抛出

    assert KEY in plugin._strm_suspects
