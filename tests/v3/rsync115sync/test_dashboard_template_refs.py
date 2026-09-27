"""
看板模板引用的标识符必须都在 `<script setup>` 里定义。

Every identifier a template *calls* must exist in `<script setup>`.

## 为什么需要这个文件（真实缺陷，2026-09-27 定位）

用户反馈：「看板页面，操作任何按钮后，下面内容直接隐藏，得关掉重新打开才显示」。

真正的根因**不是** CSS 高度链，而是**模板调用了一个不存在的函数**：

    fde36bb「砍掉云端可见性」删掉了 `function plainText() {...}`，
    但模板里的两处调用留了下来：
        {{ plainText(actionMsg) }}      （操作反馈条）
        {{ plainText(strmScanMsg) }}    （strm 扫描提示）

Vue 把模板里的 `plainText(...)` 编译成 `_ctx.plainText(...)`（因为模板编译器
无法静态判定它是 script 里的绑定），于是这成了**运行时的未定义引用**。

### 症状为什么是「Title 还在、Content 整块消失」

`actionMsg` 只在**点过按钮之后**才有值，而它的渲染位于卡片主体内部。
点击按钮 → `actionMsg` 从空串变成非空 → 触发该子树的重新渲染 →
渲染函数抛 `TypeError: _ctx.plainText is not a function` → Vue 中断这棵子树的
更新。顶端 `v-card-item`（Title，属于另一棵子树）不受影响，于是表现为
「Title 在、Content 没了」；重新打开对话框时 `actionMsg` 是空串，
`v-if="actionMsg"` 为假、那行根本不会渲染，因此又完全正常。

这精确解释了症状的三个特征：
  1. 只在**操作之后**出现（`actionMsg` 被赋值）
  2. Title 不受影响（不同子树）
  3. 关掉重开就好（初值空串，走不到那个分支）

### 为什么构建期没拦住

模板编译产物里的 `_ctx.plainText(...)` 是一个**合法的运行时属性访问** ——
`vite build` 不会、也无法报错。Vite 只是普通构建工具，不做模板↔script 的
标识符一致性检查（那需要 vue-tsc 之类的类型层校验）。
所以这类缺陷**只能靠测试或真机**发现。

### 同一提交里还有第二处同类缺陷

`c288a33` 给文件列表加分页时，`v-for="(file, idx) in ..."` 被改成了
`v-for="entry in failedPaged.slice"`，但内层 4 处 `file` 没跟着改 ——
`itemLoading === file`、`syncSingle(file)`、`ignoreFile(file, 'exact')` 全部
引用了不存在的 `file`。「对账异常清单」标签里的**重试 / 忽略按钮完全失效**
（点击即抛错）。同一类的两个缺陷都在本文件被钉死。

## 判据

模板里出现的每个「调用目标」都必须能在 `<script setup>` 中找到定义
（`function` / `const` / `let` / `var`，或 props 声明）。
`v-for` 的迭代别名是模板局部绑定，不属于 script 定义，需单独收集后排除。
"""

import os
import re

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))

# 模板里合法的非 script 标识符：
#   内建全局；`v-for` 的别名；Vue 模板语法关键字。
_BUILTINS = frozenset({
    "Number", "String", "Boolean", "Array", "Object", "JSON",
    "parseInt", "parseFloat", "Date", "Math", "isNaN", "RegExp", "Error",
    "window", "console", "Set", "Map", "Promise",
})

# `v-for="x in y"` 里的 `in`、箭头函数里的 `in`、纯文本「strm (」等
# 会混进正则结果，这些不是函数调用。
_NOT_A_CALL = frozenset({"in", "of", "strm"})


def _components_dir() -> str:
    return os.path.join(_ROOT, "plugins.v3", "rsync115sync", "src", "components")


def _read_component(name: str) -> str:
    with open(os.path.join(_components_dir(), name), encoding="utf-8") as fh:
        return fh.read()


def _split(src: str):
    """把 SFC 切成模板段与脚本段。"""
    tpl_start = src.index("<template>") + len("<template>")
    tpl_end = src.rindex("</template>")
    script_start = src.index("<script setup>")
    script_end = src.index("</script>", script_start)
    return src[tpl_start:tpl_end], src[script_start:script_end]


def _template_call_names(template: str) -> set:
    """
    模板里被「调用」的标识符（形如 `foo(`）。

    负向断言 `(?<![\\w$.])` 排除属性访问（`a.b(`）与方法名 —— 只有裸标识符
    才会编译成 `_ctx.foo(...)`，也就是只有它们才会因未定义而在运行时抛错。
    """
    return set(re.findall(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(", template))


def _script_bindings(script: str) -> set:
    """
    `<script setup>` 里的顶层绑定名。

    只认**行首**（允许缩进）的声明：函数/变量的内部语句不会被误当成顶层绑定，
    否则嵌套作用域里的临时变量会让本测试失效（那是本测试最怕的假阴性）。
    """
    names = set()
    for a, b, c in re.findall(
            r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"
            r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
            r"|^\s*(?:const|let|var)\s*\{([^}]*)\}",
            script, re.M):
        if a or b:
            names.add(a or b)
        elif c:
            for part in c.split(","):
                part = part.strip()
                if part:
                    names.add(part.split(":")[-1].strip())
    # defineProps 的字段名也属于模板可直接引用的绑定
    for block in re.findall(r"defineProps\(\{([^}]*)\}", script, re.S):
        names.update(re.findall(r"^\s*([A-Za-z_$][\w$]*)\s*:", block, re.M))
    return names


def _template_local_aliases(template: str) -> set:
    """`v-for` 引入的模板局部绑定 + `v-slot` 解构名。"""
    aliases = set()
    for m in re.finditer(r'v-for="\(?([^)"]*?)\)?\s+(?:in|of)\s', template):
        for part in m.group(1).split(","):
            name = part.strip()
            if name:
                aliases.add(name)
    return aliases


def _undefined_template_calls(component: str) -> set:
    template, script = _split(_read_component(component))
    calls = _template_call_names(template)
    known = _script_bindings(script) | _template_local_aliases(template) | _BUILTINS
    return {c for c in calls if c not in known and c not in _NOT_A_CALL}


# ---------------------------------------------------------------------------
# 主闸门
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("component", ["Page.vue", "Config.vue", "CollapsibleNote.vue"])
def test_no_undefined_template_calls(component):
    """
    模板里不得调用 `<script setup>` 中不存在的标识符。

    这就是 2026-09-27「Content 区整块消失」的成因：`plainText` 被删、调用留下，
    点击按钮把 `actionMsg` 从空串变成非空 → 渲染该行 → 抛 TypeError →
    Vue 中断子树更新 → Title 在、Content 没了。构建期完全静默。
    """
    missing = _undefined_template_calls(component)
    assert not missing, (
        f"{component} 模板调用了未定义的标识符 {sorted(missing)} —— "
        "模板编译器会把它编译成 `_ctx.<name>(...)` 的运行时属性访问，"
        "构建**不会**报错，只在渲染该分支时抛 TypeError 并中断整棵子树 "
        "（表现为 Content 区整块消失）。请补回函数定义或删掉调用点。"
    )


# ---------------------------------------------------------------------------
# 反向用例：确认探针真的能发现缺陷（否则主闸门是空转的）
# ---------------------------------------------------------------------------

def test_probe_detects_a_deleted_helper():
    """变异测试：删掉 `plainText` 的定义后，探针必须报出它。"""
    src = _read_component("Page.vue")
    assert "function plainText" in src, "前提失效：Page.vue 里已没有 plainText 定义"

    mutated = re.sub(r"function plainText\(text\)\s*\{.*?\n\}", "", src, count=1, flags=re.S)
    template, script = _split(mutated)
    known = _script_bindings(script) | _template_local_aliases(template) | _BUILTINS
    assert "plainText" in _template_call_names(template)
    assert "plainText" not in known, "变异未生效 —— 探针会误判为通过"


def test_probe_would_have_caught_the_file_alias_bug():
    """
    探针必须能发现 `v-for` 改别名后残留的裸标识符。

    ⚠️ `file` 是**变量引用**而不是调用（`syncSingle(file)` 里 file 是实参），
    所以上面的调用探针抓不到它。这里为它单独钉一条：`v-for` 把
    `(file, idx)` 改成 `entry` 之后，片段内不得再出现裸 `file`。
    """
    template, _ = _split(_read_component("Page.vue"))
    failed_tab = template[template.index("currentTab === 'failed'"):]
    failed_tab = failed_tab[:failed_tab.index("currentTab === 'strm'")]
    bare = re.findall(r"(?<![\w.$])file(?![\w$])", failed_tab)
    assert not bare, (
        "「对账异常清单」标签里仍引用了裸 `file` —— 该标签的 v-for 别名是 "
        "`entry`，`file` 未定义（重试/忽略按钮点击即抛错）"
    )


def test_failed_tab_buttons_use_entry_alias():
    """正向断言：对账异常清单的重试/忽略必须绑定 `entry.file`。"""
    template, _ = _split(_read_component("Page.vue"))
    failed_tab = template[template.index("currentTab === 'failed'"):]
    failed_tab = failed_tab[:failed_tab.index("currentTab === 'strm'")]
    assert "syncSingle(entry.file)" in failed_tab
    assert "ignoreFile(entry.file, 'exact')" in failed_tab
