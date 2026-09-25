"""
删旧重传的删除护栏 —— 本插件**唯一**的破坏性操作。

Guardrails of the delete-then-retransfer path: the plugin's only destructive action.

**为什么优先级最高**：TODO 里这条被标了「破坏性操作，优先级应提前」。它是唯一
会删用户云端文件的代码路径，而它的三道闸全是**运行时**判据（相对路径精确对齐、
源端必须存在、删除后复查），静态看代码看不出对错，只能靠用例钉住。

用例围绕「绝不该删」的方向写：错误的删除无法撤销，而少删一次只是重传慢一轮。
"""

import importlib
import os
import time

KEY = "电视剧:a.mkv"
OTHER_PAIR = "电影:movie.mkv"


def _plugin(root):
    module = importlib.import_module("app.plugins.rsync115sync")
    src_tv = os.path.join(root, "src_tv")
    src_mv = os.path.join(root, "src_mv")
    dest_tv = os.path.join(root, "dest_tv")
    dest_mv = os.path.join(root, "dest_mv")
    for d in (src_tv, src_mv, dest_tv, dest_mv):
        os.makedirs(d, exist_ok=True)

    plugin = module.Rsync115Sync.__new__(module.Rsync115Sync)
    plugin._sync_pairs = [
        {"name": "电视剧", "src": src_tv, "dest": dest_tv,
         "strm_dir": os.path.join(root, "strm1"), "pan_dir": "/TV", "all_ext": False},
        {"name": "电影", "src": src_mv, "dest": dest_mv,
         "strm_dir": os.path.join(root, "strm2"), "pan_dir": "/Movies", "all_ext": False},
    ]
    plugin._exclude_patterns = "@eaDir/"
    plugin._media_extensions = "mkv"
    plugin._ignored_rules = []
    plugin.save_data = lambda k, v: None
    plugin.get_data = lambda k: None
    return plugin


def _write(path, content=b"x" * 100):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)


# --------------------------------------------------------------------------
# 闸门一：源端必须存在（否则路径解析出错就会删到别处）
# --------------------------------------------------------------------------

def test_source_missing_blocks_deletion(tmp_path):
    """
    源端文件不存在时**不得删除**目标端。

    这是防止「路径解析异常导致误删」的最后一道闸：目标端即使真有同名文件，
    只要源端没有对应物，就没有「重传」这回事，删除只会造成净损失。
    """
    plugin = _plugin(str(tmp_path))
    dest_file = os.path.join(plugin._sync_pairs[0]["dest"], "a.mkv")
    _write(dest_file)                       # 目标端有
    # 源端**故意不建**

    deleted, undeletable = plugin._delete_dest_files_for_retry([KEY])
    assert deleted == []
    assert undeletable == [KEY]
    assert os.path.exists(dest_file), "源端不存在却仍然删掉了目标端文件"


def test_unmapped_key_is_skipped_not_deleted(tmp_path):
    """key 无法归属任何映射时保守跳过 —— 没有映射就构造不出可信的目标路径。"""
    plugin = _plugin(str(tmp_path))
    deleted, undeletable = plugin._delete_dest_files_for_retry(["不存在的映射:a.mkv"])
    assert deleted == []
    assert undeletable == ["不存在的映射:a.mkv"]


# --------------------------------------------------------------------------
# 闸门二：相对路径精确对齐（只删那一个绝对路径）
# --------------------------------------------------------------------------

def test_deletes_only_the_exact_path(tmp_path):
    plugin = _plugin(str(tmp_path))
    src_a = os.path.join(plugin._sync_pairs[0]["src"], "a.mkv")
    dest_a = os.path.join(plugin._sync_pairs[0]["dest"], "a.mkv")
    sibling = os.path.join(plugin._sync_pairs[0]["dest"], "b.mkv")   # 同目录近邻
    _write(src_a)
    _write(dest_a)
    _write(sibling)

    deleted, undeletable = plugin._delete_dest_files_for_retry([KEY])
    assert deleted == [KEY] and undeletable == []
    assert not os.path.exists(dest_a)
    assert os.path.exists(sibling), "删除波及了同目录的另一个文件"


def test_nested_relative_path_is_preserved(tmp_path):
    """子目录相对路径必须原样保留，不能被 basename 化。"""
    plugin = _plugin(str(tmp_path))
    rel = "Season 01/a.mkv"
    _write(os.path.join(plugin._sync_pairs[0]["src"], rel))
    dest_nested = os.path.join(plugin._sync_pairs[0]["dest"], rel)
    _write(dest_nested)

    deleted, _ = plugin._delete_dest_files_for_retry(["电视剧:" + rel])
    assert deleted == ["电视剧:" + rel]
    assert not os.path.exists(dest_nested)


def test_other_pair_files_are_untouched(tmp_path):
    """一批里混有其它映射的 key 时，各归各的 dest 根，不会串台。"""
    plugin = _plugin(str(tmp_path))
    _write(os.path.join(plugin._sync_pairs[0]["src"], "a.mkv"))
    _write(os.path.join(plugin._sync_pairs[0]["dest"], "a.mkv"))
    _write(os.path.join(plugin._sync_pairs[1]["src"], "movie.mkv"))
    dest_mv = os.path.join(plugin._sync_pairs[1]["dest"], "movie.mkv")
    _write(dest_mv)

    deleted, undeletable = plugin._delete_dest_files_for_retry([KEY])
    assert deleted == [KEY]
    assert os.path.exists(dest_mv), "删 A 映射时波及了 B 映射的同名文件"


def test_mapping_name_with_colon_is_resolved_by_prefix(tmp_path):
    """
    映射名本身含冒号时，key 必须按**完整映射名前缀**切分。

    这正是 `split(":", 1)` 那类 bug 的形态：多切一段 → 相对路径错 → 拼出的
    路径不存在（表现为「删不掉」）或指向别处（表现为误删）。
    """
    plugin = _plugin(str(tmp_path))
    plugin._sync_pairs[0]["name"] = "剧:集"          # 名字里带冒号
    _write(os.path.join(plugin._sync_pairs[0]["src"], "a.mkv"))
    dest_file = os.path.join(plugin._sync_pairs[0]["dest"], "a.mkv")
    _write(dest_file)

    deleted, _ = plugin._delete_dest_files_for_retry(["剧:集:a.mkv"])
    assert deleted == ["剧:集:a.mkv"]
    assert not os.path.exists(dest_file)


# --------------------------------------------------------------------------
# 闸门三：目标端不存在时是「no-op 成功」，不是失败
# --------------------------------------------------------------------------

def test_absent_destination_is_successful_noop(tmp_path):
    """
    目标端本就没有文件 ⇒ 直接可传，不该报删除失败。

    它必须是**成功**：调用方只在 undeletable 非空时中止，若把这种情况算作失败，
    用户就会连「云端本来就没有」的文件都重传不了 —— 而那恰恰是最该重传的一类。
    """
    plugin = _plugin(str(tmp_path))
    _write(os.path.join(plugin._sync_pairs[0]["src"], "a.mkv"))
    # 目标端故意不建

    deleted, undeletable = plugin._delete_dest_files_for_retry([KEY])
    assert deleted == [KEY]
    assert undeletable == []


def test_delete_failure_is_reported_and_not_counted_as_deleted(tmp_path):
    """
    删除抛 OSError 时归入 undeletable，**不能**算作已删除。

    带脏视图去 rsync 会被 --size-only 跳过：既没传成，又白耗一次限流配额。
    调用方据此跳过这些文件，所以计数必须准确。
    """
    plugin = _plugin(str(tmp_path))
    _write(os.path.join(plugin._sync_pairs[0]["src"], "a.mkv"))
    _write(os.path.join(plugin._sync_pairs[0]["dest"], "a.mkv"))

    def boom(path):
        raise OSError("模拟挂载点只读")

    real_remove = os.remove
    os.remove = boom
    try:
        deleted, undeletable = plugin._delete_dest_files_for_retry([KEY])
    finally:
        os.remove = real_remove
    assert deleted == []
    assert undeletable == [KEY]
