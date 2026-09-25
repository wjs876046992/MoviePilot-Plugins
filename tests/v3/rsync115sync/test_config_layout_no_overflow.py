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
    # 且说明块确实用的是统一的 v-alert 形态
    body = _template(src)
    alerts = re.findall(r'<v-alert[^>]*type="([a-z]+)"[^>]*variant="([a-z]+)"', body)
    assert alerts, "未找到任何 v-alert 说明块"
    info_tonal = [a for a in alerts if a == ("info", "tonal")]
    assert len(info_tonal) >= 3, (
        f"说明块应统一为 type=info variant=tonal，实际只有 {len(info_tonal)} 个"
    )
