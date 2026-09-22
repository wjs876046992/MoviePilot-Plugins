"""
看板首行三个数据卡片的 border-top 必须完整可见。

The top border of the three stat cards on the dashboard's first row must be
visible in the real host, not just in isolation.

**为什么有这条测试**：v0.0.12 修过一次「首行圆角被裁」，当时的结论是
「宿主把 .v-card-text 的 padding-block-start 强制归零，圆角落入
overflow-hidden 裁剪范围」。但真实宿主（headless Chromium + 宿主真实样式表）
复测发现那只解释了**圆角**问题 —— border-top 整条不可见的真正成因是另一个：
宿主把滚动容器顶部内边距归零后，`.v-row` 自带的 `margin: -12px` 把整行顶边
推出滚动框之外（实测卡片顶边相对容器顶边为 -8px），且 scrollHeight ==
clientHeight、页面无法滚动，用户连滚动补救都做不到。
若只按旧结论打补丁，下次布局微调时同样的可见性损失会再静默复发。
因此这里用**源码断言**钉住三件事：
  1. 首行 v-row 必须带专用类（不再依赖通用 margin 工具类）；
  2. 该类必须显式归零负上边距（margin-top: 0 !important）；
  3. 补回的下方间距必须与 Vuetify 原生 mb-3 等值（12px），
     否则修一条边、丢一段留白。
"""
import re
from pathlib import Path

import pytest


def _plugin_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "plugins.v3" / "rsync115sync" / "src"
        if (candidate / "components" / "Page.vue").is_file():
            return candidate
    pytest.skip("rsync115sync 源码目录未找到")


def _page_vue() -> str:
    path = _plugin_dir() / "components" / "Page.vue"
    return path.read_text(encoding="utf-8")


def test_stat_row_uses_dedicated_class():
    """首行数据卡片行必须挂专用类，布局意图不再隐身于通用工具类。"""
    vue = _page_vue()
    assert re.search(r'<v-row class="[^"]*\bstrm-stat-row\b', vue), (
        "首行 v-row 缺少 strm-stat-row 类 —— border-top 被裁的修复依赖这个钩子"
    )


def test_stat_row_negates_negative_top_margin():
    """.strm-stat-row 必须显式归零负上边距，把首行拉回滚动框内。"""
    vue = _page_vue()
    m = re.search(
        r"\.strm-stat-row\s*\{([^}]*)\}", vue, re.S
    )
    assert m, "Page.vue 缺少 .strm-stat-row 规则"
    body = m.group(1)
    assert re.search(r"margin-top:\s*0\s*!important", body), (
        "必须显式 margin-top: 0 !important —— Vuetify .v-row 默认 -12px，"
        "普通声明无法可靠覆盖"
    )
    assert re.search(r"margin-bottom:\s*12px\s*!important", body), (
        "归零负上边距会同时清掉 mb-3 的下方间距，必须以 12px 补回，"
        "否则首行与提示条贴在一起"
    )


def test_stat_row_comment_records_real_host_evidence():
    """规则上方必须留有真实宿主实测依据，防止后人凭理论回退。"""
    vue = _page_vue()
    m = re.search(r"/\*(.*?)\*/\s*\.strm-stat-row\s*\{", vue, re.S)
    assert m, "缺少 .strm-stat-row 前置注释"
    comment = m.group(1)
    assert "-8px" in comment, "必须记录实测偏移量，作为回退判断的证据"
    assert "scrollHeight" in comment, "必须记录「页面无法滚动」的实测事实"
