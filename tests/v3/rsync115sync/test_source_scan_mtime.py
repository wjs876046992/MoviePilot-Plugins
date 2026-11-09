"""
源端扫描的入选判据：保留旧 mtime 的硬链接也必须被扫到。

The source-cursor scan must not miss files whose mtime was preserved by a
hardlink / `cp -p` / `rsync -t` copy.

## 缺陷表现（用户实测，2026-11-08 / 11-09）

`/media/emby/TV/欧美剧/天蝎 (2014)/Season 04` 里有 20 个 mkv，strm 只生成了 6 个。
用户在系统里**找不到任何痕迹** —— 台账里 0 条、没有告警、没有日志。

## 根因（用 ctime 与日志双向证实）

20 个 mkv 的真实落地时刻（ctime，硬链接建立时刷新）与保留的时间戳（mtime）不同：

    mtime 09:25–09:36  ← 被保留的源端时间戳
    ctime 09:26–09:58  ← 真正进入媒体库目录的时刻

其中 14 集的 ctime 是 **09:45–09:58**，而 mtime 仍是 09:32–09:36。
扫描在 09:30:02 与 09:42:37 各跑一轮，**游标在 09:42:37 推进到了扫描时刻**。
此后这 14 个文件的 mtime 永远早于游标，每轮都被判"不新"，永久跳过。

日志原文（`logs/plugins/rsync115sync.log`）：

    09:30:02 源端扫描 监听到 3 个新入库文件（游标=09:20:00，候选=23）→ E15/E05/E02
    09:42:37 源端扫描 监听到 3 个新入库文件（游标=09:30:00，候选=7） → E12/E17/E20

抓到的正是 ctime 落在 09:26–09:38 的 6 个；漏掉的是 ctime 09:45–09:58 的 14 个。

## 为什么这是常态而不是边缘情况

qBittorrent 做种硬链接、`cp -p`、`rsync -a/-t`、Trash/Link 类整理工具
**都会保留 mtime**。NAS 上的媒体整理流程几乎必然经过其中一种。

## 修复

判据从 `os.path.getmtime` 改为 `_ingest_stamp`（`max(mtime, ctime)`）。
ctime 无法被拷贝保留 —— 建立硬链接、复制、改名都会刷新它。
`SOURCE_CURSOR_OVERLAP_SECS` 的重叠窗口保留（它负责"同一秒批量落盘"，
与这里负责的"时间戳被保留但落地更晚"是两件不同的事）。
"""

import os
import re
import time
from pathlib import Path

import pytest


def _init_py() -> str:
    for parent in Path(__file__).resolve().parents:
        p = parent / "plugins.v3" / "rsync115sync" / "__init__.py"
        if p.is_file():
            return p.read_text(encoding="utf-8")
    pytest.skip("__init__.py 未找到")


def _ingest_stamp():
    """
    从插件源码里取出 `_ingest_stamp` 的**实现**并返回可调用的函数。

    ⚠️ 不能 `from app.plugins.rsync115sync import _ingest_stamp` ——
    本机没有 MoviePilot 后端，导入会连带拉起 `app.*`。这里只抽那一个函数
    的源码（它只依赖标准库 `os`），用 exec 在独立命名空间里求值。
    这样测的是**插件里的真实现**，不是一份抄过来的副本。
    """
    src = _init_py()
    # ⚠️ 边界必须是「行首的非缩进 def / 行首注释」，不能只写 `(?=^def |\Z)`：
    # `\Z` 会先匹配，导致捕获到文件剩余部分（连相对导入一起 exec，报
    # ImportError）。第一次写就踩了这个。
    m = re.search(r"^def _ingest_stamp\(.*?(?=^def |^# |\Z)",
                  src, re.DOTALL | re.MULTILINE)
    assert m, "插件源码里找不到 _ingest_stamp —— 判据修复可能被回退了"
    code = m.group(0)
    assert "def _ingest_stamp" in code and "import" not in code, (
        "抓取到的不止 _ingest_stamp 一个函数 —— 边界写错了"
    )
    ns = {"os": os, "__name__": "ingest_stamp"}
    exec(compile(code, "<ingest_stamp>", "exec"), ns)
    return ns["_ingest_stamp"]


# --------------------------------------------------------------------------
# 判据函数本身
# --------------------------------------------------------------------------

def test_ingest_stamp_uses_ctime_when_mtime_is_older(tmp_path):
    """
    mtime 被保留成旧值、ctime 是新建时刻时，必须返回 ctime。

    这正是 v0.5.10 漏扫 14 集的场景：硬链接保留了源端 mtime。
    """
    stamp = _ingest_stamp()
    f = tmp_path / "ep.mkv"
    f.write_bytes(b"x")

    old = time.time() - 3600          # 一小时前（被保留的 mtime）
    new = time.time() - 60            # 一分钟前（硬链接建立时刻）
    os.utime(f, (old, old))
    # 注意：ctime 无法直接设置，只能由内核在元数据变更时刷新。
    # 这里用 os.utime 把 mtime 改到"旧"，而此刻的 ctime 是"现在"，
    # 正好复现"旧 mtime + 新 ctime"的形态。
    ctime_now = f.stat().st_ctime
    assert stamp(str(f)) >= ctime_now - 1, (
        "旧 mtime 时没有采用 ctime —— 这正是硬链接保留时间戳导致永久漏扫的成因"
    )
    assert stamp(str(f)) > old + 60, "返回值退化成旧 mtime 了"


def test_ingest_stamp_takes_later_of_the_two(tmp_path):
    """取两者较大值：正常拷贝时 mtime 更新，应返回 mtime。"""
    stamp = _ingest_stamp()
    f = tmp_path / "ep.mkv"
    f.write_bytes(b"x")
    future = time.time() + 3600       # 模拟 mtime 比 ctime 新的情形
    os.utime(f, (future, future))
    assert stamp(str(f)) == pytest.approx(future, abs=1), (
        "没有取 mtime 与 ctime 的较大值 —— 正常拷贝（mtime=完成时刻）会漏"
    )


def test_ingest_stamp_raises_on_missing_file(tmp_path):
    """
    文件不存在时抛 OSError，交给调用方兜底。

    调用点用 `except OSError: continue`（当作读不到、跳过），
    不能在这里吞掉异常 —— 否则调用方无法区分"写完了"与"读不到"。
    """
    stamp = _ingest_stamp()
    with pytest.raises(OSError):
        stamp(str(tmp_path / "not-there.mkv"))


# --------------------------------------------------------------------------
# 接入点：扫描循环必须用这个判据
# --------------------------------------------------------------------------

def test_scan_loop_uses_ingest_stamp():
    """
    源端扫描的候选筛选必须调用 `_ingest_stamp`，不能退回 `os.path.getmtime`。

    这是**接入点**断言：函数本身正确但没被调用，等于没修。
    """
    src = _init_py()
    # 取 _scan_source_cursor 的函数体
    m = re.search(r"def _scan_source_cursor\(self\).*?(?=\n    def )", src, re.DOTALL)
    assert m, "找不到 _scan_source_cursor"
    body = m.group(0)

    assert "_ingest_stamp(" in body, (
        "源端扫描没有使用 _ingest_stamp —— 保留旧 mtime 的硬链接会永久漏扫"
    )
    assert "os.path.getmtime" not in body, (
        "源端扫描仍在用 os.path.getmtime 筛候选 —— 这就是 v0.5.10 漏掉整季 14 集的成因"
    )


def test_cursor_overlap_window_is_kept():
    """
    重叠窗口必须保留。

    它负责的是"多个文件在同一秒批量落盘、时间戳恰好等于游标"，
    与 `_ingest_stamp` 负责的"时间戳被保留但落地更晚"是**两件不同的事**。
    修了后者就删掉前者，会在同一秒批量落盘时重新引入永久漏扫。
    """
    src = _init_py()
    assert "SOURCE_CURSOR_OVERLAP_SECS" in src, (
        "游标重叠窗口被删了 —— 它负责同秒批量落盘的场景，与 ctime 判据互补"
    )
    m = re.search(r"since\s*=\s*cursor\s*-\s*self\._SOURCE_CURSOR_OVERLAP_SECS", src)
    assert m, "`since` 没有减去重叠窗口 —— 同秒落盘的文件会被严格比较永久跳过"


def test_cooldown_basis_still_uses_mtime():
    """
    冷却基准必须**继续**用 mtime，不得改成 ctime。

    两者回答不同问题：
      · 扫描判据问「何时出现」→ ctime 兜底（硬链接会刷新 ctime）
      · 冷却基准问「何时写完」→ 只能看 mtime

    用 ctime 算冷却会让已完整的文件因为"09:56 才建硬链接"而白等几小时，
    而且与"等文件写完"这个原始职责无关。这条断言防止"顺手统一成 ctime"。
    """
    src = _init_py()
    m = re.search(r"def _cooldown_basis\(self.*?(?=\n    def )", src, re.DOTALL)
    assert m, "找不到 _cooldown_basis"
    body = m.group(0)
    assert "getmtime" in body, (
        "_cooldown_basis 里没有 mtime —— 冷却基准被改成 ctime 了？"
        "ctime 反映元数据变更时刻，用它算冷却会让完整文件白等几小时"
    )
    assert "_ingest_stamp(" not in body, (
        "_cooldown_basis 不要改用 _ingest_stamp —— 那是扫描判据，不是冷却判据"
    )
