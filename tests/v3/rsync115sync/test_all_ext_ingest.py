"""
`all_ext`（同步所有文件类型）映射：入库时**目录里其他文件也必须一并上传**。

Why this file exists — 用户 2026-09-22 真机反馈：

    9KG 下配置的是所有文件都上传，在 webhook 入库后，进行上传时，
    没有把媒体文件所在目录下其他文件一并上传。

问题不在于解析或排队本身，而在于**入队粒度**：整条入库链路
（`_enqueue_ingest_paths` → 扩展名白名单 → 冷却队列 → `--files-from`）
自始至终以**文件**为单位。发送端推来一个文件路径时，只有那一个文件具备
「冷却是它、被同步的也是它」的资格，同目录的其它文件（同名不同扩展名的
字幕／音轨／封面、以及发布组塞进同目录的 .nfo/.jpg/说明文件）永远拿不到
冷却资格，也就永远不上传。

对 `all_ext` 映射而言这是自相矛盾的：配置项的字面含义就是「这个目录下的
文件全都要上传」，用户不会预期「只有被 webhook 点到名的那一个」。

两条出路，本文件的用例把它们钉死：
  1. **正路**：发送端推**目录** → `_expand_ingest_path` 已在 `all_ext` 下
     不过滤地展开（`test_directory_expansion_under_all_ext_...`）。
  2. **兜底**：发送端只推**单个文件**时，把同目录的兄弟文件一并入队
     （`test_single_file_notifies_...`）—— 发送端不保证推目录，
     而 `all_ext` 的语义要求整目录上传。

反向用例同样重要：`all_ext=False`（默认）映射**绝不能**因为本改动而扩大
上传范围，那是静默的配额浪费（`test_sibling_expansion_is_off_for_normal_pairs`）。
"""

import os

import pytest

from app.plugins.rsync115sync import Rsync115Sync


ALL_EXT_EXTENSIONS = "mkv,srt"


def _plugin(src_root, *, pairs=None, media_extensions=ALL_EXT_EXTENSIONS,
            ignore_rules=None):
    """最小实例：只带入库链路真正用到的状态。"""
    plugin = Rsync115Sync.__new__(Rsync115Sync)
    plugin.plugin_version = "test"
    plugin._enabled = True
    plugin._listen_transfer = True
    plugin._webhook_channels = ["emby"]
    plugin._webhook_self_enabled = True
    plugin._webhook_secret = ""
    plugin._webhook_path_allowlist = str(src_root)
    plugin._webhook_ip_allowlist = ""
    plugin._sync_pairs = pairs if pairs is not None else [{
        "name": "9KG", "src": src_root, "dest": "/dest/9KG",
        "all_ext": True, "strm_dir": "",
    }]
    plugin._media_extensions = media_extensions
    plugin._delay_hours = 2.0
    plugin._pending_queue = {}
    plugin._missed_queue = {}
    plugin._ignored_rules = list(ignore_rules or [])
    plugin._last_status = {}
    plugin._webhook_stat = plugin._wh_stat()
    plugin.saved = {}
    plugin.save_data = lambda k, v: plugin.saved.__setitem__(k, v)
    return plugin


def _write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def _ingest(plugin, *paths):
    """走自建端点的完整防护链（与真机 sender 的入口一致）。"""
    return plugin._ingest_from_parts(client_ip="10.0.0.9", headers=None,
                                     query={}, body={"paths": list(paths)})


# --------------------------------------------------------------------------
# 兜底通道：只推单个文件时，同目录的兄弟文件一并入队
# --------------------------------------------------------------------------

def test_single_file_notifies_siblings_under_all_ext(tmp_path):
    """
    用户报告的原场景：webhook 推来电影文件，同目录的其它文件却不上传。

    `all_ext` 的字面承诺是「这个目录下的文件全都要上传」，用户不会接受
    「只有被点到名的那一个」。发送端只推一个文件（它只知道这一个），
    因此兜底必须由插件来做。
    """
    src = tmp_path / "9kg"
    movie = _write(str(src / "某电影 (2001)" / "movie.mkv"))
    _write(str(src / "某电影 (2001)" / "movie.zh.srt"))
    _write(str(src / "某电影 (2001)" / "movie.sc.ass"))
    _write(str(src / "某电影 (2001)" / "movie.nfo"))
    _write(str(src / "某电影 (2001)" / "poster.jpg"))

    plugin = _plugin(str(src))
    res = _ingest(plugin, movie)

    assert res["success"] is True
    rel = "9KG:某电影 (2001)/"
    assert sorted(plugin._pending_queue) == sorted([
        rel + "movie.mkv", rel + "movie.zh.srt", rel + "movie.sc.ass",
        rel + "movie.nfo", rel + "poster.jpg",
    ]), f"all_ext 映射：同目录其它文件未一并入队 —— {sorted(plugin._pending_queue)}"


def test_siblings_expansion_is_named_in_counts(tmp_path):
    """
    多出来的文件必须有计数，否则用户看日志会以为「只入队了 1 个」。

    看板与 /rsync_webhook 响应都用 counts，静默多入队会让用户无法解释
    「我明明只推了一个文件，怎么排队 5 个」。同名计数复用 `expanded`：
    它与目录展开是同一语义（一次通知膨胀成多个文件）。
    """
    src = tmp_path / "9kg"
    movie = _write(str(src / "9kg" / "movie.mkv"))
    _write(str(src / "9kg" / "movie.nfo"))

    plugin = _plugin(str(src))
    res = _ingest(plugin, movie)

    assert res["data"]["added"] == 2
    assert res["data"]["expanded"] == 1


def test_siblings_do_not_escape_the_mapping(tmp_path):
    """只展开**同一目录**（同一层级）的兄弟文件，绝不向上/向下递归。"""
    src = tmp_path / "9kg"
    movie = _write(str(src / "某电影" / "movie.mkv"))
    _write(str(src / "某电影" / "sibling.nfo"))
    _write(str(src / "其它电影" / "other.nfo"))          # 兄弟目录
    _write(str(src / "某电影" / "sub" / "nested.nfo"))   # 子目录
    _write(str(src / "根目录文件.nfo"))                  # 父目录

    plugin = _plugin(str(src))
    _ingest(plugin, movie)

    assert sorted(plugin._pending_queue) == [
        "9KG:某电影/movie.mkv", "9KG:某电影/sibling.nfo"]


def test_siblings_respect_ignore_rules(tmp_path):
    """忽略规则优先级最高：否则被忽略的文件会从这条新路重新进队。"""
    src = tmp_path / "9kg"
    movie = _write(str(src / "某电影" / "movie.mkv"))
    _write(str(src / "某电影" / "poster.jpg"))

    plugin = _plugin(str(src), media_extensions="mkv",
                     ignore_rules=[{"rule": "9KG:某电影/poster.jpg",
                                    "match": "exact"}])
    _ingest(plugin, movie)

    assert list(plugin._pending_queue) == ["9KG:某电影/movie.mkv"]


def test_siblings_are_not_duplicated_on_redelivery(tmp_path):
    """
    重复投递同一文件时，兄弟文件必须走同一套幂等，**不刷新冷却计时**。

    durable outbox 是 at-least-once，webhook 发送端也常带重试；若兄弟文件
    每次都被当成新入队，冷却期永远走不完。
    """
    src = tmp_path / "9kg"
    movie = _write(str(src / "某电影" / "movie.mkv"))
    _write(str(src / "某电影" / "movie.nfo"))

    plugin = _plugin(str(src))
    _ingest(plugin, movie)
    first = dict(plugin._pending_queue)
    res = _ingest(plugin, movie)

    assert res["data"]["duplicate"] == 2
    assert plugin._pending_queue == first


def test_siblings_expansion_is_capped(tmp_path):
    """异常目录（几千个文件）不能把冷却队列一次灌满：上限必须存在且留痕。"""
    src = tmp_path / "9kg"
    movie = _write(str(src / "某电影" / "movie.mkv"))
    for i in range(40):
        _write(str(src / "某电影" / f"junk{i:03d}.jpg"))

    plugin = _plugin(str(src))
    plugin.SIBLING_EXPAND_LIMIT = 10
    _ingest(plugin, movie)

    assert len(plugin._pending_queue) == 10


# --------------------------------------------------------------------------
# 反向用例：默认（all_ext=False）映射绝不放宽
# --------------------------------------------------------------------------

def test_sibling_expansion_is_off_for_normal_pairs(tmp_path):
    """
    未勾选 `all_ext` 的映射**只能**入队被点到名的文件。

    这条是防「顺手把兜底扩大到所有映射」的哨兵：那会让每次入库都多上传
    本该被扩展名白名单挡掉的文件，静默消耗 115 风控配额 —— 与用户的配置
    意图直接冲突。
    """
    src = tmp_path / "TV"
    movie = _write(str(src / "某剧" / "S01E01.mkv"))
    _write(str(src / "某剧" / "S01E01.srt"))     # 字幕仍在白名单内
    _write(str(src / "某剧" / "S01E01.nfo"))     # 不在白名单内
    _write(str(src / "某剧" / "poster.jpg"))     # 不在白名单内

    plugin = _plugin(str(src), pairs=[{
        "name": "TV", "src": str(src), "dest": "/dest/TV",
        "all_ext": False, "strm_dir": "",
    }])
    _ingest(plugin, movie)

    assert list(plugin._pending_queue) == ["TV:某剧/S01E01.mkv"], \
        "默认映射不该把同目录其它文件一起入队"


def test_sidecar_subtitles_still_not_auto_added_for_normal_pairs(tmp_path):
    """
    默认映射下**连同名字幕也不自动入队** —— 现状如此，改动不得顺手变更。

    这里钉住的是「本次修复的范围」：只针对 all_ext。默认映射的伴生字幕
    由补传前置扫描（`_find_sidecar_files`）那条路负责，两条路混起来会让
    「为什么这个字幕被传了、那个没有」无法解释。
    """
    src = tmp_path / "TV"
    movie = _write(str(src / "某剧" / "S01E01.mkv"))
    _write(str(src / "某剧" / "S01E01.zh.srt"))

    plugin = _plugin(str(src), pairs=[{
        "name": "TV", "src": str(src), "dest": "/dest/TV",
        "all_ext": False, "strm_dir": "",
    }])
    _ingest(plugin, movie)

    assert list(plugin._pending_queue) == ["TV:某剧/S01E01.mkv"]


# --------------------------------------------------------------------------
# 正路：推目录（本已支持，此处作为「两种发送姿势都覆盖」的对照）
# --------------------------------------------------------------------------

def test_directory_expansion_under_all_ext_includes_non_media(tmp_path):
    """推目录 + all_ext：目录里的**所有**文件都要入队，包括 jpg/nfo 等。"""
    src = tmp_path / "9kg"
    base = str(src / "某电影 (2001)")
    _write(os.path.join(base, "movie.mkv"))
    _write(os.path.join(base, "movie.zh.srt"))
    _write(os.path.join(base, "poster.jpg"))
    _write(os.path.join(base, "movie.nfo"))
    _write(os.path.join(base, "说明.txt"))

    plugin = _plugin(str(src))
    res = _ingest(plugin, base)

    assert res["data"]["added"] == 5, f"all_ext 下目录展开不得过滤任何扩展名：{res}"
    assert res["data"]["expanded"] == 1


def test_directory_expansion_under_all_ext_skips_excluded_dirs(tmp_path):
    """`all_ext` 不等于「连群晖元数据目录也传」：排除目录仍在遍历层剪枝。"""
    src = tmp_path / "9kg"
    base = str(src / "某电影")
    _write(os.path.join(base, "movie.mkv"))
    _write(os.path.join(base, "@eaDir", "thumb.jpg"))

    plugin = _plugin(str(src))
    _ingest(plugin, base)

    assert list(plugin._pending_queue) == ["9KG:某电影/movie.mkv"]
