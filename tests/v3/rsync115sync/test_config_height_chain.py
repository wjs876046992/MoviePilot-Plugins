"""
配置页高度链：标题栏与底部操作栏必须固定，不随表单内容滚走。

The config page's height chain: the title bar (which carries the 「高级设置」switch)
and the save bar must stay put while the form body scrolls.

## 缺陷表现（用户实测）

「配置页面，顶部 title 包含高级设置的按钮部分固定」—— 滚动表单时，
标题栏连同里面的「高级设置」开关一起被滚出视口；底部「保存配置」同样。
用户要展开高级区，得先把页面滚回顶部。

## 根因

宿主的配置弹窗是 `<VDialog scrollable>` → `<VCard>` → `<VCardText class="pa-0">`
（见 MoviePilot-Frontend `src/components/dialog/PluginConfigDialog.vue`）。
`VDialog scrollable` 给它的 `.v-card-text` 加了 `overflow-y: auto`，
**那一层才是默认的滚动容器**。

本组件根 div 此前只是 `class="plugin-config"`，没有确定高度 ⇒ 内部 `v-card` 的
`h-100`（`height: 100% !important`）解析成 `auto` ⇒ `.config-body` 的
`flex-grow-1 overflow-y-auto` 拿不到确定高度、永不滚动。滚动于是"上浮"到
宿主那一层，把卡片内部所有的 flex:none 兄弟（标题栏、操作栏）一起滚走。

**为什么不能改用 `position: sticky`**：卡片的 `overflow-hidden`（圆角裁剪所需）
会成为 sticky 的最近滚动容器，而它自身不滚动，sticky 完全失效。必须让卡片
自己成为滚动容器，标题栏与操作栏作为滚动区之外的 flex 兄弟天然固定。

## 与看板的关系

`Page.vue` 的根 div 早就是 `class="plugin-page h-100"`（见
`test_dashboard_height_chain.py`），所以看板没有这个缺陷。配置页漏了同一个
`h-100` —— 这组测试把两侧对齐，防止再次漂移。
"""

import re
from pathlib import Path

import pytest


def _config_vue() -> str:
    for parent in Path(__file__).resolve().parents:
        p = parent / "plugins.v3" / "rsync115sync" / "src" / "components" / "Config.vue"
        if p.is_file():
            return p.read_text(encoding="utf-8")
    pytest.skip("Config.vue 未找到")


def _template(src: str) -> str:
    return src[src.find("<template>"):src.rfind("</template>")]


def _strip_comments(src: str) -> str:
    """
    去掉 HTML 与 CSS 注释后再扫描。

    ⚠️ 必须做这一步：本文件的说明文字本身就会提到 `position: sticky`
    （解释为什么**不能**用它），不剥注释会把"反面教材"当成违规命中 ——
    这条断言第一次写就踩了这个坑。
    """
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.DOTALL)
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
    return src


def test_root_div_has_h_100():
    """
    根 div 必须带 `h-100` —— 它是内部 `v-card` 的 `height:100%` 唯一高度来源。

    少了它，`h-100` 解析成 auto，`.config-body` 的溢出滚动永不生效，
    滚动上浮到宿主容器，标题栏与操作栏随之被滚走。
    """
    src = _config_vue()
    assert re.search(r'<div class="plugin-config h-100"', src), (
        "根 div 少了 h-100 —— v-card 的 height:100% 会解析成 auto，"
        "滚动会上浮到宿主容器，标题栏与底部保存按钮会跟着滚走"
    )


def test_root_box_sizing_is_border_box():
    """
    根 div 必须 `box-sizing: border-box`。

    100% 高度 + 18px 上下留白：不加 border-box 时留白叠在 100% **之外**，
    卡片比可用高度多出 36px，底部操作栏被推出容器并被 overflow-hidden 裁掉。
    """
    src = _config_vue()
    m = re.search(r"\.plugin-config\s*\{(.*?)\}", src, re.DOTALL)
    assert m, "找不到 .plugin-config 规则"
    assert "box-sizing: border-box" in m.group(1), (
        ".plugin-config 缺 box-sizing:border-box —— 100% 高度之外再叠 18px "
        "上下留白，底部操作栏会被裁掉"
    )


def test_body_has_min_height_zero():
    """
    `.config-body` 必须有 `min-height: 0`。

    弹性子项默认 `min-height: auto`，会拒绝收缩到内容高度以下 ——
    内容一多就**撑高整张卡片**而不是自己滚动，标题栏与操作栏被挤出可见区。
    """
    src = _config_vue()
    m = re.search(r"\.config-body\s*\{(.*?)\}", src, re.DOTALL)
    assert m, "找不到 .config-body 规则"
    assert "min-height: 0" in m.group(1), (
        ".config-body 缺 min-height:0 —— 内容变多时会撑高卡片而不是自身滚动，"
        "标题栏与底部操作栏会被挤出可见区"
    )


def test_header_and_actions_are_outside_the_scroll_body():
    """
    标题栏、提示条、操作栏都必须是 `.config-body` 的**兄弟**，不在其内部。

    这是"固定"的结构前提：它们由 `flex: none`（Vuetify 给 .v-card-item /
    .v-card-actions 的定义）保持固有高度，只有 `.config-body` 滚动。
    若哪天有人把标题栏挪进 `v-card-text` 里，样式怎么调都固定不住。
    """
    body = _template(_config_vue())
    open_idx = body.find('<v-card-text class="config-body')
    assert open_idx != -1, "找不到 config-body 的 v-card-text"

    # 从 config-body 开始配对标签，找到它自己的闭合位置
    depth = 0
    close_idx = -1
    for m in re.finditer(r"<(/?)v-card-text\b", body[open_idx:]):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            close_idx = open_idx + m.start()
            break
    assert close_idx != -1, "config-body 的 v-card-text 没有闭合"

    inner = body[open_idx:close_idx]
    assert "v-card-item" not in inner, (
        "标题栏（v-card-item）被放进了滚动区内部 —— 它会随内容滚走"
    )
    assert "config-actions" not in inner, (
        "底部操作栏被放进了滚动区内部 —— 它会随内容滚走"
    )

    # 反过来也要成立：它们确实存在于 config-body 之外
    outside = body[:open_idx] + body[close_idx:]
    assert "header-surface" in outside, "标题栏不在滚动区之外"
    assert "config-actions" in outside, "底部操作栏不在滚动区之外"


def test_fixed_bars_use_sticky_with_overflow_released():
    """
    标题栏与底栏必须用 `position: sticky` 固定，且卡片的 `overflow-hidden` 必须被放开。

    ⚠️ 这条断言的前一版写反了：它断言"不得用 sticky，必须靠 flex 高度链"。
    那是基于一个**未经实测的推断** —— 以为`h-100` 在桌面端能解析出高度。
    用真实 Vuetify 样式表 + 构建产物在 Chromium 里量过之后发现两端都断在
    宿主 `.v-card-text`（它的高度由 flex 决定，后代 `height:100%` 全解析成
    auto），于是 `h-100` 那条链在**两个断点上都无效**，滚动实际发生在宿主
    那一层。sticky 是唯一能相对祖先滚动容器定位的机制。

    sticky 的前提是到滚动容器之间没有 `overflow != visible` 的祖先，
    而卡片上恰好继承了 `overflow-hidden` —— 所以这两条必须同时成立，
    少任何一条都会静默退化成"不固定"。因此断言的是一个**组合**。
    """
    raw = _config_vue()
    src = _strip_comments(raw)

    # 1) 标题栏与底栏都用 sticky
    # ⚠️ 用 finditer 而不是 search：同一个类名在样式区可能出现多条规则
    # （.header-surface 就有一条背景规则 + 一条 sticky 规则），
    # 只取第一条会误判成"缺 sticky"。
    for cls, edge in ((".header-surface", "top: 0"), (".config-actions", "bottom: 0")):
        blocks = [m.group(1) for m in
                  re.finditer(rf"{re.escape(cls)}\s*\{{(.*?)\}}", src, re.DOTALL)]
        assert blocks, f"找不到 {cls} 规则"
        merged = "\n".join(blocks)
        assert "position: sticky" in merged, f"{cls} 缺 position:sticky —— 它会随内容滚走"
        assert edge in merged, f"{cls} 的 sticky 锚点应为 {edge}"

    # 2) 卡片的 overflow-hidden 被放开，且用的是自己这一层
    blocks = [m.group(1) for m in
              re.finditer(r"\.config-main-card\s*\{(.*?)\}", src, re.DOTALL)]
    assert blocks, "找不到 .config-main-card 规则"
    assert "overflow: visible" in "\n".join(blocks), (
        ".config-main-card 必须放开 overflow —— 卡片继承了 overflow-hidden，"
        "它会成为 sticky 的最近裁剪祖先，让 sticky 静默失效"
    )

    # 3) 固定规则不得被收进移动端媒体查询里（桌面端同样需要）
    media_start = raw.find("@media (max-width: 599.98px)")
    assert media_start != -1
    media = raw[media_start:]
    # 取媒体查询块内第一个 .header-surface（如果它只在 media 里出现，说明桌面端漏了）
    before_media = raw[:media_start]
    assert "position: sticky" in before_media, (
        "sticky 规则被放进了移动端媒体查询 —— 桌面端同样需要它"
        "（实测两端都断在宿主 .v-card-text）"
    )


def test_does_not_touch_host_overflow():
    """
    只允许放开**本组件自己**的 overflow，不得用 `:deep()` 去改宿主的 `.v-card`。

    **实测依据**（1280×900，逐项放开对比）：

      | 放开哪一层             | 标题栏 | 保存条 |
      | 都不放开               | ✗     | ✓     |
      | 只放开本卡片           | ✓     | ✓     |
      | 只放开宿主 .v-card     | ✓     | ✗     |
      | 只放开宿主 .v-card-text| ✓     | ✗     |

    放开宿主那两层会改变滚动容器，反而让底栏失效。而且 `:deep(.v-card)`
    编译成 `[data-v-x] .v-card`（后代选择器），本来就够不到作为**祖先**的宿主卡片 ——
    写了也是死代码，只会误导下一个维护者。
    """
    src = _strip_comments(_config_vue())
    bad = re.findall(r":deep\(\s*\.v-card\s*\)|:deep\(\s*\.v-card-text\s*\)", src)
    assert not bad, (
        f"不得用 :deep() 改宿主的 overflow（{bad}）—— 实测放开宿主那两层会让底栏"
        f"失效；且后代选择器够不到祖先，是死代码"
    )
