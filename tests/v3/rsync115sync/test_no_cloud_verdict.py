"""
**结构哨兵**：整条「云端可见性」判定不得复活。

Structural sentinel: the cloud-visibility verdict must not come back.

## 为什么用"禁止出现"而不是"断言行为"

那条判定的失败方式**不是算错**，而是"算得再准也没用"：CD2 挂载视图对
「云端其实是改名失败的残留」这个主成因必然显示成「可见、大小一致」
（残留与正式文件字节数相同），于是它给出的结论有一边注定是错的，
而错的那一边会把用户引向错误动作 —— 删不掉那个坏文件。

判据收敛成一条：**.strm 存在与否**。也就是说，这个功能不是"被关掉了"，
而是"被证明不成立" —— 因此防止它复活靠的是**结构**（名字不许出现），
而不是行为（行为测试可以在功能被一行行加回来时全部保持绿色）。

⚠️ 断言的是**标识符**而不是自由文本：源码里的中文注释解释"为什么删掉它"
是允许的（而且必要），只要没有任何一行代码真的用它。
"""

import ast
import os
import re

import pytest

_PKG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    "plugins.v3", "rsync115sync",
)

# 被删除判据的**标识符**（函数名 / 常量名 / 端点片段）。
# 这里逐条列出而不是用宽泛正则：宽泛模式会误伤解释性注释，而注释里
# 出现「云端可见性」正是我们要保留的东西。
_FORBIDDEN = (
    "dest_probe_outcome",
    "dest_path_of",
    "dest_root_of",
    "_dest_visibility",
    "_has_dest_residue",
    "_annotate_dest",
    "_remove_dest_residues",
    "is_temp_residue_name",
    "_promote_watch_to_suspects",
    "strm_confirm_failed",
    "strm_probe",
    "DEST_OK",
    "DEST_RESIDUE",
    "DEST_ABSENT",
    "DEST_UNKNOWN",
    "DEST_SIZE_MISMATCH",
    "ORIGIN_CONFIRMED",
)


def _python_sources():
    for name in sorted(os.listdir(_PKG)):
        if name.endswith(".py"):
            yield os.path.join(_PKG, name)


def _identifiers(path):
    """
    取出一个 .py 里**语法上真的被用到的标识符**（Name / Attribute / 关键字）。

    用 AST 而不是 grep：注释与字符串里出现这些词是**刻意保留**的
    （"为什么删掉 X" 的说明），grep 会把它们当成复活。
    """
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.add(alias.asname or alias.name.split(".")[0])
    return out


@pytest.mark.parametrize("name", _FORBIDDEN)
def test_removed_verdict_identifier_never_reappears(name):
    for path in _python_sources():
        assert name not in _identifiers(path), (
            f"{os.path.basename(path)} 里又出现了 `{name}` —— "
            f"「云端可见性」这套判定已被证明在改名失败这个主成因上必然判错"
            f"（见 strm_ops._api_strm_retry 的说明），不要把它加回来。"
        )


def test_endpoints_are_not_registered(tmp_path=None):
    """两个已删端点不得重新注册 —— 它们是那条判据的入口。"""
    src = open(os.path.join(_PKG, "__init__.py"), encoding="utf-8").read()
    # 只匹配真正作为 path 出现的字符串（"/strm_probe"），
    # 注释里的 `/strm_probe` 保留无妨 —— 所以要求前后是引号而不是反引号。
    for path in ("/strm_probe", "/strm_confirm_failed"):
        assert f'"path": "{path}"' not in src
        assert f"'{path}'" not in src


def _find_function(path, name):
    """取出某个顶层类里的指定方法节点（拿得到 AST 就不会被注释骗到）。"""
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_retry_endpoint_has_no_force_channel():
    """
    删旧重传不得再有 `force` 越权通道。

    它原本的唯一用途是推翻那道"云端看起来是好的"的拦截；拦截没了，
    通道也就无从谈起。留着它等于留着一个没有任何守卫可越的后门。

    ⚠️ 走 AST 而不是 grep 源码文本：那个方法里**留着**一段解释
    「这里曾经有一道守卫、它为什么错」的注释，里面就写着 `needs_force`。
    文本匹配会把这段必要的说明当成复活 —— 这正是我前几轮反复踩到的
    假红形态（"grep 到了自己写的解释"）。
    """
    node = _find_function(os.path.join(_PKG, "strm_ops.py"), "_api_strm_retry")
    assert node is not None, "_api_strm_retry 不见了"

    used = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
    used |= {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    used |= {k.arg for k in ast.walk(node) if isinstance(k, ast.keyword) and k.arg}
    used |= {c.value for c in ast.walk(node)
             if isinstance(c, ast.Constant) and isinstance(c.value, str)}

    assert "needs_force" not in used, "不得再返回 needs_force"
    assert "force" not in used, "不得再读 body['force']"


# --------------------------------------------------------------------------
# 死状态 / 死字段：定义了但没有任何写入者的东西，与死探测一样有害
# --------------------------------------------------------------------------

def test_no_status_value_without_a_writer():
    """
    `ALL_STATUSES` 里每个取值都必须**真的会被写入**。

    这里曾有一个 `synced`（"strm 已出现，确认真的上传成功"），三批改造期间
    一直躺在常量表里，而它**从来没有写入者** —— 那一步的实现是删行，不是改状态。
    一个定义了却永不出现的取值比没有更糟：它让看板的计数表多一个永远为 0 的
    格子，而读者会据此以为"从来没有文件成功过"。

    判据：每个状态名都要在**别处**被当成值用（写进 `upsert` / 传入
    `LedgerMapping`），只在 `store.py` 自己的常量表里出现不算。
    """
    from app.plugins.rsync115sync.store import ALL_STATUSES

    pkg = os.path.dirname(_PKG)
    users = ""
    for root, _dirs, files in os.walk(pkg):
        if os.sep + "dist" in root or "node_modules" in root:
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            if path == os.path.join(_PKG, "store.py"):
                continue              # 定义处不算使用者
            users += open(path, encoding="utf-8").read()

    for status in ALL_STATUSES:
        assert f'"{status}"' in users or f"STATUS_{status.upper()}" in users, (
            f"状态 `{status}` 在常量表里定义了，但全仓没有任何写入者 —— "
            f"它会让计数表上多一个永远为 0 的格子。删掉它，或者补上真正会写它的路径。"
        )


def test_ledger_overview_counts_what_the_user_asked_to_distinguish():
    """
    `/status` 的台账概览必须能回答「哪些是已成功的」。

    用户需求原话：「所有映射目录里的视频，同时也可以一份台账…便于区分已成功的」。
    判据是 `synced_at IS NOT NULL` —— 它与状态**正交**（一个文件可以既同步成功过、
    又处于待处理，那正是"传过、但这一轮没传成"），因此不能拿某个状态去代替。
    """
    src = open(os.path.join(_PKG, "__init__.py"), encoding="utf-8").read()
    assert "synced_at IS NOT NULL" in src, "台账概览丢了「已成功」的判据"
    assert '"ledger": self._ledger_overview()' in src, "台账概览未接入 /status"
