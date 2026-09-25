"""
同步进度追踪：把 rsync 的 `--info=progress2` 输出变成看板能显示的东西。

Sync progress tracking: turn rsync's `--info=progress2` output into something the
dashboard can render.

## 为什么用 progress2 而不是 `--progress`

`--progress` 是**每文件**的进度条，只会刷屏；`--info=progress2` 是**整批累计**
进度，一条里就带着我们要的全部信息（本机 rsync 3.4.1 实测）：

    491,520  12%  400.36kB/s  0:00:08              ← 每秒一条，中间态
  3,000,000  50%  301.91kB/s  0:00:09 (xfr#1, to-chk=1/2)   ← 单文件完成
  6,000,000 100%  301.00kB/s  0:00:19 (xfr#2, to-chk=0/2)   ← 整批完成

实测结论（这些决定了下面的解析逻辑，不是推测）：

1. **进度行写在 stdout**，不是 stderr（rsync 文档说 stderr，实际是 stdout）。
2. **用 `\r` 作分隔符**，不是 `\n` —— 所以必须一边读一边按 `\r` 切。
3. **只有"完成行"带 `(xfr#N, to-chk=A/B)`**；中间态那一行**没有**括号。
   想靠 `to-chk` 过滤中间行是错的（我第一版就这么写，结果整批只看到最后一行）。
4. **`-v` 的文件名行与进度行混在同一条流里**，靠"有没有 `N%`"区分。
5. **一批传完会重复打印若干条 100%**（rsync 收尾），前端看到的会是"停在一秒前"，
   因此状态里必须带 `updated_at`，让界面能显示"最近更新 x 秒前"。

## 三个必须记住的边界

- **秒传命中时 0% 直接跳 100%**：秒传不传字节，没有中间过程。这不是 bug，
  前端文案不该把它说成异常。
- **进程死掉进度就没了**：不做跨重启续传（rsync 的 `--partial` 会让 115 秒传
  失效，本插件刻意不用），进度是**瞬时观测**，不是可恢复的状态。
- **ETA 会跳**：rsync 按瞬时速率估算，前端只把它当参考值，不承诺准确。

本模块**无状态**（纯函数 + 一个纯数据类），所以可以安全地被 Mixin 模块导入 ——
见 tests/v3/rsync115sync/test_split_contract.py 对模块级可变状态的红线。
"""

import re
from typing import Any, Dict, Optional

# 进度行：`<累计字节> <百分比>% <速率> <ETA> [(xfr#N, to-chk=A/B)]`
#
# ⚠️ 速率与 ETA 之间、ETA 与括号之间都是**多个空格**（rsync 用它对齐列），
# 所以不能用单个 `\s` 去切；用宽松的 `\s+` 并把括号段整体可选。
# 数字里的千分位逗号也要吃掉（`6,000,000`）。
_PROGRESS_RE = re.compile(
    r"^\s*(?P<bytes>[\d,]+)\s+(?P<pct>\d{1,3})%\s+"
    r"(?P<rate>\S+B/s)\s+(?P<eta>\d+:\d{2}:\d{2})"
    r"(?:\s+\(xfr#(?P<xfr>\d+),\s*to-chk=(?P<left>\d+)/(?P<total>\d+)\))?"
)

# `Name: 主库:相对路径` 这类形态里冒号是承重的，不做任何切分 —— 这里只用它
# 判断"这一行是不是进度行"，避免把文件名行误当进度。
def parse_progress_line(text: str) -> Optional[Dict[str, Any]]:
    """
    解析一条 rsync progress2 行；不是进度行则返回 None。

    Parse one progress2 line; None when the line is not progress output.

    ⚠️ **返回 None 是常态，不是错误**：同一股输出里混着 `-v` 的文件名行、
    `sending incremental file list` 这类横幅、以及收尾的 `sent ... bytes` 统计。
    调用方（读取线程）必须把 None 当作"这行不是进度"直接跳过。
    None is the common case: the same stream also carries -v filename lines and
    banner/footer text, which must be skipped rather than treated as failures.
    """
    if not text or "%" not in text:
        return None
    m = _PROGRESS_RE.match(text)
    if not m:
        return None
    try:
        return {
            "bytes": int(m.group("bytes").replace(",", "")),
            "percent": int(m.group("pct")),
            "rate": m.group("rate"),
            "eta": m.group("eta"),
            # 只有"单文件完成"那一行才带括号，中间态没有 —— 因此这两个字段
            # 在前端都可能为 None，显示时要允许缺省（见模块头实测结论 3）。
            "xfr": int(m.group("xfr")) if m.group("xfr") is not None else None,
            "files_left": int(m.group("left")) if m.group("left") is not None else None,
            "files_total": int(m.group("total")) if m.group("total") is not None else None,
        }
    except (TypeError, ValueError):
        return None


def current_file_of(text: str) -> Optional[str]:
    """
    判断一条 `-v` 输出行是不是**文件名行**（即"这个文件开始传了"）。

    Is this -v output line a filename (i.e. "this file just started transferring")?

    ⚠️ 为什么值得单独判：progress2 只给整批进度，**不告诉你在传哪一个**。
    而 `-v` 恰好会在每个文件开始传时打印它的路径名 —— 两股信息合起来才是
    "整批 50%，正在传 f2.bin"这种用户真正想看的形态。
    progress2 gives batch-level progress only; -v supplies the current filename.

    排除规则（都是实测中会真实出现的行）：
      · `sending incremental file list` / `sent 6,001,603 bytes ...` 等横幅与统计
      · 目录行（以 `/` 结尾）
      · 以空白开头（缩进的统计/警告）
      · `./` 这种 rsync 自己的占位
    """
    if not text:
        return None
    line = text.strip()
    if not line or text[:1].isspace():
        return None
    if "%" in line or line.endswith("/") or line == "./":
        return None
    # rsync 的横幅与收尾统计：都以小写英文单词开头且含空格，而真实文件路径
    # 几乎不会长成这样。宁可漏判（只是少显示一个文件名）也不误判。
    lowered = line.lower()
    for prefix in ("sending ", "sent ", "total ", "receiving ", "received ",
                   "created ", "deleting ", "skipping ", "cannot ", "skipped "):
        if lowered.startswith(prefix):
            return None
    return line
