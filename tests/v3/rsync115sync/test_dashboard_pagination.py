"""
看板四个标签页的分页契约。

Pagination contract for the dashboard's four tabs.

## 四个标签各自的逻辑（这份表也是本组用例要守住的东西）

| 标签 | 数据源 | 它回答的问题 |
|---|---|---|
| **入库延迟冷却队列** | `_pending_queue`（台账 `candidate`） | 已发现、还在等冷却到期的文件 |
| **对账异常清单** | `missing_files` + `corrupt_files` | rsync 对账后发现**云端缺失或大小不符**的文件 |
| **strm 疑似异常**（内部两个列表） | ① `strm_watch`（观察中，只读）② `strm_suspects`（待处理，可操作） | ① 刚同步成功、在等 .strm 生成 ② 宽限期到了仍无 .strm |
| **已忽略** | `ignored_files` 规则 | 用户明确要求不再报警的文件 |

**为什么四个都要分页**：前三者都随媒体库增长而变长。实机数据：队列 102 条、
观察中 91 条、对账缺失 102 条 —— 每一条都是一个卡片 `div`，一次全渲染既卡顿
又没法浏览（用户实测反馈过「一个 tab 到底在讲什么」的困惑，列表长度本身就是
原因之一）。

## 易错点（本组用例的重点）

- **strm 标签里有两个独立列表**，共用一个页码会让「翻疑似清单」把观察中列表
  一起翻走；
- **数据变少时要就地纠偏页码**（同步成功后条目会被移出），否则用户停在空白页
  且无法自行返回；
- **分页条只在超过一页时出现**，不占常驻空间。
"""

import os
import re

import pytest


def _source() -> str:
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    path = os.path.join(root, "plugins.v3", "rsync115sync",
                        "src", "components", "Page.vue")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _tab_body(src: str, name: str) -> str:
    """取出某个 tab 区域的模板文本（从它的 v-if 到下一个 tab 的 v-if）。"""
    marks = [(m.group(1), m.start()) for m in
             re.finditer(r"currentTab === '(\w+)'", src)]
    for i, (tab, pos) in enumerate(marks):
        if tab != name:
            continue
        end = marks[i + 1][1] if i + 1 < len(marks) else len(src)
        return src[pos:end]
    raise AssertionError(f"没找到 tab {name}")


# --------------------------------------------------------------------------
# 四个标签都要有分页
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tab,expected_pager", [
    ("queue", "queuePaged"),
    ("failed", "failedPaged"),
    ("ignored", "ignoredPaged"),
])
def test_each_tab_slices_its_list(tab, expected_pager):
    """三个单列表标签：v-for 必须走自己的分页切片，而不是原始集合。"""
    body = _tab_body(_source(), tab)
    assert f"{expected_pager}.slice" in body, (
        f"{tab} 标签没有分页 —— 列表变长时会一次渲染全部条目"
    )


def test_strm_tab_paginates_both_of_its_lists():
    """
    strm 标签里有**两个**列表，且各自分页。

    ⚠️ 这是最容易漏的一个：`strm_watch`（观察中）此前完全没有分页，
    实机一次同步就登记 90+ 个文件，而它只会增长到宽限期到期为止。
    """
    body = _tab_body(_source(), "strm")
    assert "watchingPaged.slice" in body, "观察中列表没有分页"
    assert "strmPaged.slice" in body, "疑似清单没有分页"


def test_watching_list_has_its_own_page_state():
    """
    观察中列表必须有**自己的页码 ref**，不能与疑似清单共用一个。

    共用页码的表现：翻疑似清单时观察中列表一起被翻走（两个列表同屏），
    而用户完全看不出发生了什么。
    """
    src = _source()
    assert "const pageWatching = ref(1)" in src
    # ⚠️ 必须断言**它绑的是 pageWatching**，而不是只断言"这个 computed 存在"。
    # 第一版这里写的是 `"const watchingPaged = computed(" in src`，而它对本节的
    # 目标缺陷（把两个列表绑到同一个页码 ref）**永远为真** ——
    # 变异测试当场证明：改成 `paginate(strmWatchingEntries.value, pageStrm)`
    # 之后全部用例仍然通过。断言必须落在"绑给谁"上。
    assert ("const watchingPaged = computed(() => "
            "paginate(strmWatchingEntries.value, pageWatching))") in src, (
        "观察中列表没有绑定自己的页码 ref —— 翻疑似清单时会把它一起翻走"
    )
    body = _tab_body(src, "strm")
    assert "watchingPaged.pages > 1" in body
    assert "paged.pages > 1" in body
    assert "watchingPaged.slice" in body and "strmPaged.slice" in body


def test_pager_bars_only_appear_when_needed():
    """
    分页条只在超过一页时出现 —— 不分页时多一条「第 1/1 页」只是噪声。
    """
    src = _source()
    for pager in ("paged", "watchingPaged"):
        assert f'v-if="{pager}.pages > 1"' in src, f"{pager} 的分页条缺少条件"


def test_page_refs_are_per_tab():
    """
    四个标签（strm 里两个列表共五个）各自持有页码，切标签不会互相影响。

    ⚠️ 若它们共用一个 ref，用户在队列翻到第 3 页再切到「已忽略」，
    会看到「第 3 页 / 共 1 页」这种自相矛盾的状态。
    """
    src = _source()
    for name in ("pageQueue", "pageFailed", "pageStrm", "pageIgnored", "pageWatching"):
        assert f"const {name} = ref(1)" in src, f"缺少独立页码 {name}"


def test_paginate_clamps_page_when_list_shrinks():
    """
    ⚠️ 页码必须**就地纠偏**：条目被移出后总页数会变小，若仍停在第 5 页，
    模板渲染出的是空列表，而分页条又显示「第 5 / 共 2 页」——
    用户既看不到内容也点不动（下一页已禁用），只能刷新页面。

    `paginate` 定义在 .vue 里无法直接 import，因此这里既断言源码里的关键
    纠偏语句存在，也用一段**逐句等价**的实现验证行为。
    """
    src = _source()
    # ⚠️ 断言必须**锚定整条纠偏语句**，不能被别处的相似子串满足。
    # 第一版写的是 `"pageRef.value = page" in src` —— 而翻页按钮里的
    # `paged.pageRef.value = paged.page - 1` **刚好包含这个子串**，
    # 于是删掉纠偏语句后用例照样通过（变异测试发现的）。
    # 这类"断言被无关代码满足"的假绿在本仓已反复出现，锚定整句是唯一可靠的写法。
    assert "if (page !== pageRef.value) pageRef.value = page" in src, \
        "页码纠偏语句不见了 —— 条目变少后用户会停在空白页且无法自行返回"

    def paginate(total, page_val, size=15):
        pages = max(1, -(-total // size))
        return min(max(1, page_val), pages)

    assert paginate(0, 1) == 1
    assert paginate(10, 5) == 1        # 只有 1 页 → 回到第 1 页
    assert paginate(45, 5) == 3        # 3 页 → 夹到最后一页
    assert paginate(45, 2) == 2        # 未越界则不动

# --------------------------------------------------------------------------
# ⚠️ 分页最常见的静默错误：把「页内下标」当「全表下标」用
# --------------------------------------------------------------------------

def test_paginated_lists_never_use_the_loop_index_for_actions():
    """
    分页列表里**不得**用 v-for 的下标去执行"全表操作"。

    ## 这里修掉的是一个真 bug（早于本次改造就存在）

    「已忽略」列表原本是：

        <div v-for="(rule, idx) in ignoredPaged.slice" ...>
          <v-btn @click="removeIgnore(idx)">

    而 `ignore.remove_rule` 按**全表绝对下标** pop。`idx` 是**页内下标**：
    第 1 页碰巧正确（页内 0..14 == 全表 0..14），**从第 2 页起会删错规则** ——
    点第 2 页第 1 条会删掉全表第 1 条；而且删完列表变短，下标进一步漂移，
    用户看到的是"点了恢复，结果另一条消失了"。

    已改为传**规则文本**（唯一，且后端本来就支持）。

    ## 为什么这条断言值得存在

    这类错误**不会报错、也不会崩**，只是悄悄操作了另一条数据 ——
    而它在第 1 页上表现完全正常，所以手工点几下根本发现不了。
    唯一可靠的防线是结构断言：分页列表的 v-for 不许取下标。
    """
    import os
    import re
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    src = open(os.path.join(root, "plugins.v3", "rsync115sync",
                            "src", "components", "Page.vue"),
               encoding="utf-8").read()

    # 取出所有「在分页切片上迭代」的 v-for（两种形态都要抓到）：
    #   · `v-for="item in queuePaged.slice"`      → 合规（没取下标）
    #   · `v-for="(rule, idx) in ignoredPaged.slice"` → 违规（取了页内下标）
    # ⚠️ 只抓括号形态是不够的 —— 修复之后全部都是无括号形态，那样这条断言
    # 会"因为一个都匹配不到"而变成空跑（第一版就是这么写的，`assert paged_loops`
    # 当场报 `[]`）。必须两种都抓，再按"有没有括号"分流。
    paged_loops = re.findall(r'v-for="([^"]*?)\s+in\s+(\w+Paged\.slice)"', src)
    offenders = [f"`{vars_} in {src_}`" for vars_, src_ in paged_loops
                 if vars_.strip().startswith("(")]
    assert paged_loops, (
        f"没有找到任何分页列表 —— 正则失效了（找到 {len(paged_loops)} 个），"
        f"这条断言会变成空跑，先修正则"
    )
    assert len(paged_loops) >= 5, (
        f"只找到 {len(paged_loops)} 个分页列表，预期至少 5 个"
        f"（队列 / 对账 / 观察中 / 待处理 / 已忽略）—— 正则或列表漏了"
    )
    assert not offenders, (
        f"分页列表取了循环下标，它会被当成全表下标用：{offenders}。"
        f"改用条目的唯一标识（key / 规则文本）传参。"
    )


def test_unignore_sends_the_rule_text_not_an_index():
    """恢复忽略必须传规则文本（后端按全表下标 pop，页内下标会删错）。"""
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    src = open(os.path.join(root, "plugins.v3", "rsync115sync",
                            "src", "components", "Page.vue"),
               encoding="utf-8").read()
    assert "removeIgnore(rule.rule)" in src, "恢复忽略没有传规则文本"
    assert "removeIgnore(idx)" not in src, "恢复忽略仍在传页内下标"
    assert "{ rule }" in src, "请求体没有带 rule"


# --------------------------------------------------------------------------
# 「扩展名被跳过」提示已按用户要求移除
# --------------------------------------------------------------------------

def test_extension_skip_alert_is_removed():
    """
    看板不再显示「有文件因扩展名不在同步白名单被跳过」。

    ⚠️ 移除的是**看板提示与它的累计统计**，不是入库闸门本身 ——
    闸门照旧拦截，且每个扩展名第一次出现时仍会打一条 info 日志
    （看板提示被用户要求移除，日志留作排查依据）。
    """
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    vue = open(os.path.join(root, "plugins.v3", "rsync115sync",
                            "src", "components", "Page.vue"),
               encoding="utf-8").read()
    py = open(os.path.join(root, "plugins.v3", "rsync115sync", "__init__.py"),
              encoding="utf-8").read()

    for text, where in ((vue, "Page.vue"), (py, "__init__.py")):
        assert "ingest_skip_stat" not in text, f"{where} 仍残留统计持久化"
        assert "ingest_skipped_by_ext" not in text, f"{where} 仍残留 /status 字段"
    assert "扩展名不在同步白名单" not in vue, "看板提示没删干净"
    assert "_note_ingest_skips" not in py, "统计收集函数没删干净"


def test_ingest_gate_still_logs_the_first_drop():
    """
    闸门本身与它的日志必须保留 —— 移除的只是看板提示。

    「某一类文件 100% 被丢弃」曾在看板与日志上都没有痕迹（音频全丢就是
    这样潜伏了多个版本）。用户要求移除看板提示后，**日志是唯一的线索**，
    所以这条 assert 守的是"别把日志也一起删了"。
    """
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    py = open(os.path.join(root, "plugins.v3", "rsync115sync", "__init__.py"),
              encoding="utf-8").read()
    assert "扩展名未纳入同步白名单，跳过" in py, "闸门的 info 日志被一起删了"

