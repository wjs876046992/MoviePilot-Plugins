"""
面板高度链：根 div 的 `h-100` 与内容区的收缩许可是承重的。

The height chain matters: without it the whole Content area collapses.

## 缺陷表现（用户实测）

「点击按钮操作后，面板 Content 区域消失了，Title 还在」。

## 根因

`v-card` 用了 Vuetify 的 `h-100`（**定义为 `height: 100% !important`**，
见 `node_modules/vuetify/lib/styles/main.css`）。而 `height: 100%` 需要一个
**有确定高度的父元素**才能解析 —— 根 div 没有高度时它退化成 `auto`，
于是 `.body-surface` 的 `flex-grow-1` + `overflow-y-auto` 拿不到确定高度：
内容一收缩，整块 Content 塌成 0 高，再被卡片的 `overflow-hidden` 裁掉。

**Title 为什么还在**：`v-card-item` 是 grid 布局、有固有高度，不依赖这条链。

## 同类页面的正确写法

`watchsync` / `courseorganizer` 的根 div 都是 `class="plugin-page h-100"` ——
本插件漏了那个 `h-100`。
"""

import os
import re


def _src() -> str:
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    path = os.path.join(root, "plugins.v3", "rsync115sync",
                        "src", "components", "Page.vue")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_root_div_has_h_100():
    """
    根 div 必须带 `h-100` —— 它是 `v-card` 的 `height:100%` 唯一的高度来源。

    少了它，`height:100%` 解析成 `auto`，内容区随内容塌陷并被裁掉。
    """
    src = _src()
    assert 'class="plugin-page h-100"' in src, (
        "根 div 少了 h-100 —— v-card 的 height:100% 会解析成 auto，"
        "内容区可能塌成 0 高后被 overflow-hidden 裁掉"
    )


def test_card_keeps_height_and_overflow_pair():
    """
    `h-100` + `overflow-hidden` 必须成对出现（它们是一条链上的两端）。

    单独看任何一个都正常，只有组合起来在高度链断裂时才会出问题 ——
    所以断言的是这一对。
    """
    src = _src()
    m = re.search(r"<v-card[^>]*class=\"([^\"]*)\"", src)
    assert m, "找不到根 v-card"
    cls = m.group(1)
    assert "h-100" in cls, "根 v-card 少了 h-100（内容区的 flex-grow 需要它）"
    assert "overflow-hidden" in cls, "根 v-card 少了 overflow-hidden（圆角裁剪需要它）"
    assert "d-flex" in cls and "flex-column" in cls, "根 v-card 必须仍是纵向 flex 容器"


def test_body_has_min_height_zero():
    """
    内容区必须有 `min-height: 0`。

    ⚠️ 弹性子项默认 `min-height: auto`，会拒绝收缩到内容高度以下 ——
    高度链正常时无害，异常时它会让内容区既撑不开也缩不回（滚动行为怪异）。
    这是 flex + overflow 组合的标准做法，不是可有可无。
    """
    src = _src()
    m = re.search(r"\.body-surface\s*\{([^}]*)\}", src)
    assert m, "找不到 .body-surface 规则"
    assert "min-height: 0" in m.group(1), (
        ".body-surface 缺 min-height:0 —— 弹性子项默认 min-height:auto，"
        "会拒绝收缩，导致滚动区行为异常"
    )


def test_card_has_a_minimum_height_fallback():
    """
    卡片要有最小高度保底 —— 第二道防线。

    即使宿主容器高度异常、或百分比链因别的改动断掉，卡片也不会塌成 0
    （那正是"Content 消失"的形态）。
    """
    src = _src()
    m = re.search(r"\.page-main-card\s*\{([^}]*)\}", src)
    assert m, "找不到 .page-main-card 规则"
    assert "min-height" in m.group(1), (
        ".page-main-card 没有 min-height 保底 —— 高度链一旦断了，"
        "整块 Content 会被 overflow-hidden 裁掉"
    )
