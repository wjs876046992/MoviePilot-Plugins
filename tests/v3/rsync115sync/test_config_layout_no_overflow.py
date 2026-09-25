"""
配置页布局：任何长说明都不得把控件挤出可视区。

Configuration page layout: no long description may push a control out of view.

**为什么需要这组测试**：同一个问题被用户提了**三次**，前两次我都靠"猜 + 改说明
长度"处理，没有去查真正的机制：

  1. 「源端补齐扫描」的四行说明挤压开关；
  2. 「源端扫描 Cron」的说明挤掉输入框；
  3. 再报一次 —— 而我上一轮已经加过 `flex-wrap` + `flex-basis`，**仍然看不见**。

第三次才查到真因：**Webhook 示例 URL 是整页最长的一串不可断字符（约 80 字符）**，
它把所在行撑出卡片宽度，而卡片 `overflow-hidden` —— 右侧那一列（含 cron 输入框）
被整条裁掉，且没有滚动条可救。`flex-wrap` 救不了它，因为**内容根本没打算换行**。

所以这里用三条不变量把"靠换行与断词自洽"钉死，而不是继续针对某个具体文案打补丁。
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


def _read_component(name: str) -> str:
    """按文件名读组件源码（两个组件共用一套布局/配色不变量）。"""
    for parent in Path(__file__).resolve().parents:
        p = parent / "plugins.v3" / "rsync115sync" / "src" / "components" / name
        if p.is_file():
            return p.read_text(encoding="utf-8")
    pytest.skip(f"{name} 未找到")


def _template(src: str) -> str:
    """取模板部分，并去掉注释与标签，只留用户能看到的文本与属性。"""
    body = src[src.find("<template>"):src.rfind("</template>")]
    body = re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                  body, flags=re.DOTALL)
    return body


def test_setting_row_has_no_horizontal_overflow():
    """
    设置行必须 `overflow: hidden`。

    这条看着像"把溢出藏起来"，实际作用正相反：它让**溢出成为不可能**——
    设置行的职责是排布，任何内容太宽都必须靠换行解决。没有它时，一个超长串
    会把右侧控件推出卡片，而卡片 `overflow-hidden` 会把它裁掉 ——
    用户看到的是"输入框不见了"，且没有任何滚动条可救。
    """
    css = _config_vue()
    m = re.search(r"\.setting-row\s*\{(.*?)\}", css, re.DOTALL)
    assert m, "未找到 .setting-row 基础规则"
    assert "overflow: hidden" in m.group(1), (
        "设置行必须 overflow: hidden —— 否则一行里的超长内容会把右侧控件推出可视区"
    )


def test_setting_row_text_column_breaks_long_tokens():
    """
    设置行的文字列必须允许在**任意字符**处断行。

    `word-break: break-word` / `overflow-wrap: anywhere` 的作用对象正是
    cron 表达式、URL、路径这类**不含空格的超长串** —— 浏览器默认把它们当成
    "一个词"，放不下就直接溢出，而不是折行。中文本来就可在任意处断，
    所以这条对中文文案没有任何副作用。
    """
    css = _config_vue()
    m = re.search(r"\.setting-row\s*>\s*div:first-child\s*\{(.*?)\}", css, re.DOTALL)
    assert m, "未找到 .setting-row > div:first-child 规则"
    body = m.group(1)
    assert "word-break" in body or "overflow-wrap" in body, (
        "文字列必须允许超长串断行，否则 cron/URL/路径会把控件挤出去"
    )
    assert "flex: 1 1 20rem" in body, (
        "文字列需要 flex-basis：没有基准宽度时它可以收缩到 0，容器再窄也不会换行"
    )
    assert "min-width: 15rem" in body, (
        "文字列需要 min-width 下限 —— 允许塌成 0 等同于『永不换行』"
    )


def test_long_unbreakable_tokens_are_wrapped():
    """
    模板里超过 40 字符的不可断串必须带断行类。

    这条是**面向未来**的：新增一段 URL / 命令 / 长路径时，它会提醒你加
    `class="wrap-anywhere"`。缺了它，同一个"控件被挤没"的问题会以新面孔
    再出现一次 —— 而前两次我都是**等用户报了才知道**。
    """
    body = _template(_config_vue())
    # ⚠️ 必须**先摘掉已带断行类的元素**再扫描。
    # 第一版直接 `re.sub(r"<[^>]*>", " ", body)` 把标签全剥掉，于是那个已经
    # 用 class="wrap-anywhere" 正确包裹的 URL 仍然被报成违规 ——
    # 一条"正确地修好了"的代码被自己的哨兵判红。哨兵假红会让人开始无视哨兵
    # （本项目已记录过两次同类：grep 命中注释、绑死引号样式）。
    body = re.sub(r'<[a-z-]+[^>]*class="[^"]*wrap-anywhere[^"]*"[^>]*>.*?</[a-z-]+>',
                  " ", body, flags=re.DOTALL)
    # 只看标签之间的**文本**（长 CSS 类名之类不算）
    text_only = re.sub(r"<[^>]*>", " ", body)
    offenders = [
        tok for tok in re.findall(r"[^\s]{40,}", text_only)
        # 纯中文长句不算（中文可在任意处断行）
        if re.search(r"[A-Za-z0-9/:_?&=.]{20,}", tok)
    ]
    assert not offenders, (
        f"这些不可断的长串会把布局撑宽、把控件挤出可视区：{offenders[:3]}；"
        f"请用 <code class=\"wrap-anywhere\"> 包住，或改成分多行显示"
    )


def test_input_rows_do_not_rely_on_flex_width_math():
    """
    含输入框的设置行必须走**纵向排布**（`setting-row-stacked`）。

    **为什么这条是必要的**（同一处被用户提了三次的收尾）：

      1. 说明太长把开关挤成一条缝 → 压短说明；
      2. cron 说明把输入框挤掉 → 加 `flex-wrap` + 文字列基准宽度；
      3. **还是被挤压，强刷无效** → 加 `overflow:hidden` + 断词；
      4. 仍然被挤压。

    前三轮改的都是"flex 的宽度分配"（内容多宽、何时换行、能否溢出），
    全都依赖 flexbox 的收缩/换行计算在真实宿主样式下按预期工作 —— 而那个前提
    已被证明不可靠。与其继续调参数，不如让含输入框的行**根本不参与这套计算**：

        标签在上、输入框在下 → "被旁边文字挤压"在结构上不可能发生，
        与文字多长、窗口多宽都无关。

    ⚠️ 本用例的**写法**也值得留意：第一版用正则按"下一个 setting-row 之前"
    切分块，结果把某开关行**之后**的整片参数区算进了那一行，误报一条假红
    （已见三次同类：grep 命中注释、绑死引号、剥标签剥掉包裹）。现在改为
    **按标签文本定位，再回看它所在 div 的 class** —— 不依赖任何跨块的边界推断。
    """
    src = _config_vue()
    body = _template(src)

    # 这两个是已知含输入框、且历史上出过问题的行
    for label in ("源端扫描 Cron 规则", "观察宽限期（分钟）"):
        idx = body.find(label)
        assert idx > 0, f"未找到标签「{label}」"
        # 回看最近的 setting-row 类声明
        head = body[:idx]
        m = None
        for m2 in re.finditer(r'<div class="(setting-row[^"]*)"', head):
            m = m2
        assert m, f"标签「{label}」之前没有 setting-row"
        cls = m.group(1)
        assert "setting-row-stacked" in cls, (
            f"「{label}」所在行仍是横排（{cls}）—— 横排挤压输入框已栽过三次，"
            f'请改为 class="setting-row setting-row-stacked"'
        )
        # 且该行确实含输入框（否则这条断言没有意义）
        seg = body[m.end():body.find("<!--", m.end()) if body.find("<!--", m.end()) > 0 else m.end() + 4000]
        assert "v-text-field" in seg, f"「{label}」行内未找到 v-text-field，用例前提不成立"


def test_description_blocks_share_one_style():
    """
    页面里的说明块必须用**同一种样式**（`v-alert type="info" variant="tonal"`）。

    **为什么专门钉一条**：Webhook 接入说明曾用自制的 `.sub-note`（灰底 + 左侧
    竖线）来表达"它从属于上面的开关"。层级确实表达出来了，但代价是它在一片
    蓝色说明块里显得**像是另一种东西** —— 用户直接指出「样式和其它描述模块
    不一样，其他是蓝色的」。

    结论：**层级应该由位置表达（紧跟在所属开关之后），而不是靠换一套配色**。
    页面里出现第二种"说明块样式"时，读者得先分辨"这两种蓝/灰是不是在说不同的事"，
    而它其实不承载任何额外语义。

    这条断言的做法是：找出所有形如「标题 + 正文说明」的块，检查它们的容器类
    是否一致 —— 出现新的自制样式类就失败。
    """
    src = _config_vue()
    # ⚠️ 必须**先剥掉注释**再查。
    # 第一版直接在全文里找 ".sub-note"，命中的是**解释"为什么不再用 .sub-note"的注释**
    # —— 一条正确地描述了历史的注释被判成"样式复活了"。这与本项目已记过三次的
    # 同类错误一模一样（grep 命中注释 / 绑死引号 / 剥标签剥掉包裹）。
    code = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
    code = re.sub(r"<!--.*?-->", " ", code, flags=re.DOTALL)
    # 已知的说明块容器：v-alert（统一）+ 历史上的自制类（禁止复活）
    forbidden = ["sub-note", "note-block", "desc-block"]
    for token in forbidden:
        assert token not in code, (
            f"出现了非统一的说明块样式 {token!r} —— 页面里只该有 v-alert type=\"info\" "
            f"（用户已反馈过：自制的灰底/竖线样式与其它说明块不一致）"
        )
    # 说明块的**统一形态由组件保证**：所有长说明都走 CollapsibleNote，
    # 而它内部固定用 `<v-alert type="info" variant="tonal">`。
    # ⚠️ 这里不能再数"页面里有几个 info alert" —— 长说明已全部收进组件，
    # 页面模板里那个计数自然变成 0，第一版就是这么误报的。
    note = _read_component("CollapsibleNote.vue")
    assert re.search(r'<v-alert[^>]*type="info"[^>]*variant="tonal"', note), (
        "CollapsibleNote 必须内部固定用 type=info variant=tonal —— "
        "用户此前专门要求过所有说明块外观一致（都是蓝色）"
    )
    # 折叠组件必须被配置页真正使用（否则本文件其它断言都是空转）
    assert "<CollapsibleNote" in _template(src), "配置页未使用 CollapsibleNote"


def test_theme_variables_have_no_literal_fallback():
    """
    主题变量不得带**三值字面量兜底**（`var(--v-theme-x, 1, 2, 3)`）。

    ## 为什么这是错的（已实测确认，不是风格问题）

    Vuetify 把主题色写成**裸三元组**并**自带 rgb() 消费**：

        /* Vuetify 生成：theme.mjs 的 genCssVariables */
        .v-theme--dark { --v-theme-surface: 18,18,18; }
        /* Vuetify 消费 */
        .bg-surface { background-color: rgb(var(--v-theme-surface)) !important; }

    因此我们自己写 CSS 时，**绝不能**再套一层并把三元组当兜底：

        ❌  rgb(var(--v-theme-surface, 255, 255, 255))
            变量有值 → rgb(255, 255, 255) ？？ 变量本身是 "255,255,255"，
            于是变成 rgb(255, 255, 255) —— 参数个数对不上，**整条声明被丢弃**
        ✅  rgb(var(--v-theme-surface))

    声明被丢弃的直接后果：卡片没有背景，而文字色由宿主提供 —— 深色模式下
    宿主给的是浅色文字，落在页面底色上就是「文字看不见」。用户实测反馈：
    **深色模式下手机端与 PC 端文字都看不见**。

    ⚠️ 注意这条与"兜底值本身是不是浅色"无关 —— 只要写了三值兜底，**无论深浅
    都会让整条声明失效**。所以我修的不是"把白色换成深色"，而是去掉那个兜底。
    （第一版我曾以为"深色下兜底太浅"才是病因，那个诊断方向是错的。*)

    反面同样要拦：`var(--v-theme-x)` 是允许的（变量缺失时声明自然失效，
    回退到宿主样式，这是正确行为）。
    """
    for name in ("Config.vue", "Page.vue"):
        src = _read_component(name)
        code = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
        code = re.sub(r"<!--.*?-->", " ", code, flags=re.DOTALL)
        bad = re.findall(r"var\(--v-theme-[a-z-]+,\s*[0-9]+\s*,\s*[0-9]+\s*,\s*[0-9]+\s*\)", code)
        assert not bad, (
            f"{name} 里的主题变量带了三值字面量兜底：{bad[:3]}；"
            f"Vuetify 的 --v-theme-* 是裸三元组（如 '18,18,18'）且自带 rgb() 消费，"
            f"再套一层 rgb() 会构造出参数个数非法的值，**整条声明被浏览器丢弃** → "
            f"深色模式下卡片没有背景、而文字色来自宿主（浅色）→ 文字看不见。"
            f"正确写法：rgb(var(--v-theme-surface))，不要兜底。"
        )


def test_column_direction_resets_flex_basis():
    """
    媒体查询把设置行改成纵向排布时，**必须重置子项的 flex 基准**。

    ## 为什么（用户实测反馈：手机端「启用同步助手」占了很大的高度）

    `flex-basis` 度量的是**主轴方向**上的尺寸。桌面端给文字列设的是：

        .setting-row > div:first-child { flex: 1 1 20rem; }   /* 20rem = 320px */

    这里的 `20rem` 是**宽度**基准 —— 用来决定"一行放不下时要不要整体换行"。

    但一旦媒体查询把主轴改成纵向：

        .setting-row { flex-direction: column; }

    同一个 `flex-basis` 就**转而控制高度** —— 于是手机端每个"开关 + 说明"行
    凭空多出约 320px，表现为「启用同步助手」这类行奇高、一屏放不下两项。

    ⚠️ 这与"设置行被挤压"是同一类错误的另一面：**改主轴方向时必须同时检查
    依赖主轴方向的属性**（flex-basis / width / height / margin-inline 等）。
    我加 `flex: 1 1 20rem` 时只想着桌面端的横向排布，没意识到已有的移动端
    媒体查询会把主轴翻过来。

    这条断言的做法：在移动端媒体查询块内，若 `.setting-row` 被设为
    `flex-direction: column`，则必须存在对 `.setting-row > div:first-child`
    的 flex 重置（`flex: 0 0 auto` 或显式 `flex-basis: auto`）。
    """
    src = _read_component("Config.vue")
    css = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)

    # 取移动端媒体查询块（本文件只有一个 max-width 断点）
    mq = re.search(r"@media[^{]*max-width:\s*599\.98px[^{]*\{(.*)", css, re.DOTALL)
    assert mq, "未找到移动端媒体查询块"
    block = mq.group(1)

    if "flex-direction: column" not in block:
        return  # 没有翻主轴，本条不适用

    # 块内必须重置文字列的 flex 基准
    assert re.search(r"\.setting-row\s*>\s*div:first-child\s*\{[^}]*flex:\s*0\s+0\s+auto", block) \
        or re.search(r"\.setting-row\s*>\s*div:first-child\s*\{[^}]*flex-basis:\s*auto", block), (
        "移动端把 .setting-row 改成了 flex-direction: column，但没有重置 "
        "`.setting-row > div:first-child` 的 flex 基准 —— 桌面端那个 "
        "`flex: 1 1 20rem` 会转而控制**高度**，让每个开关行凭空多出约 320px"
        "（用户实测：手机端「启用同步助手」占了很大的高度）"
    )


def test_long_notes_are_collapsible_by_default():
    """
    配置页的长说明必须**默认折叠**，点击展开。

    **为什么**（用户反馈）：手机屏幕窄，配置页的描述都展开着时占十几行，
    一屏放不下一个设置项 —— 用户得不停滚动才能找到真正要改的开关。
    桌面端宽屏时这个问题不明显，所以只有手机用户会先报出来。

    ## 实现约束（这条断言同时钉住三件事）

    1. **用 `v-show` 而不是 `v-if`**：`v-if` 会把内容从 DOM 里移除，
       折叠状态下 Ctrl+F 找不到任何关键词 —— 而"想确认某条说明怎么写"
       恰恰是用户会去搜索的场景（也正是他会想展开那条说明的时候）。
       `v-show` 保留 DOM、只切 `display`，搜索能得到反馈。
    2. **默认关闭**：`ref(false)`。
    3. **不得用 `v-expansion-panels`**：那会引入一套新的视觉语言（面板边框、
       联动语义），而这些说明各自依附于**它上面那个**设置项，不是一组并列面板；
       且用户此前专门要求过所有说明块"样式一致、都是蓝色"。
    """
    src = _read_component("CollapsibleNote.vue")
    assert "v-show" in src, "折叠应使用 v-show（保留 DOM，Ctrl+F 仍能搜到关键词）"
    # ⚠️ 不能简单断言"模板里没有 v-if" —— 组件用 v-if 控制「（点击展开）」
    # 那个小提示的显隐，那是合理的。要检查的是**承载折叠内容的容器**。
    # （第一版就是这么写错的，一条正确的实现被自己的哨兵判红。）
    tmpl = src.split("<template>")[1].split("</template>")[0]
    slot_line = next((ln for ln in tmpl.splitlines() if "<slot" in ln or "slot />" in ln), "")
    assert slot_line, "未找到承载内容的 <slot>"
    assert "v-show" in slot_line, f"折叠内容的容器必须用 v-show，实际：{slot_line.strip()}"
    assert "v-if" not in slot_line, f"折叠内容不得用 v-if，实际：{slot_line.strip()}"
    assert re.search(r"const open = ref\(false\)", src), "必须默认折叠（ref(false)）"

    # 配置页：长说明都应改用该组件，模板里不应再有裸露的 info alert
    cfg = _read_component("Config.vue")
    body = cfg[cfg.find("<template>"):cfg.rfind("</template>")]
    assert "CollapsibleNote" in cfg, "配置页未使用可折叠说明组件"
    assert "<v-expansion-panels" not in body, (
        "不得改用 v-expansion-panels —— 这些说明各自依附于它上面的设置项，"
        "不是一组并列面板；且会破坏所有说明块外观一致的前提"
    )
    leftovers = re.findall(r'<v-alert[^>]*type="info"[^>]*>', body)
    assert not leftovers, (
        f"还有 {len(leftovers)} 个长说明未折叠 —— 手机端会占满屏幕，"
        f"请改用 <CollapsibleNote title=\"…\">"
    )
