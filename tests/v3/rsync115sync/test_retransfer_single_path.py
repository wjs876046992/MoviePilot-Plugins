"""
「删旧重传」只能有**一份实现** —— 两个入口必须行为一致。

Delete-then-retransfer must have exactly one implementation, shared by every entry.

## 这个文件钉的缺陷（2026-09-28）

同一动作此前有**两份独立实现**：`/rsync_retry <文件名>` 一份、
`_api_strm_retry` 一份。它们悄悄分叉了：

| | `/rsync_retry <文件名>` | `_api_strm_retry` |
|---|---|---|
| 前置预检 | ❌ 无 | ✅ 有 |
| 删除失败时 | 跳过失败的，传其余 | **整批中止** |
| 完成后反馈 | ✅ 回结果 | ❌ 静默 |

**没有预检的那份是危险的那份**：预检（rsync 是否装上、映射是否可用、执行锁、
限流退避、挂载目录就绪）存在的全部意义，就是避免「文件已从目标端删掉、
却因为闸门命中而没重传」。少了它，那条路径会把文件删了然后什么都不做。

两份实现必然分叉 —— 它们唯一的共同点是「都调了 `_delete_dest_files_for_retry`」。
因此修法不是给两边各补一份，而是**收敛成一个实现**，两个入口都转调它。
"""

import ast
import os
from pathlib import Path

import pytest


def _plugin_dir() -> Path:
    try:
        import importlib
        module = importlib.import_module("app.plugins.rsync115sync")
        p = Path(module.__file__)
        if p.is_file():
            return p.parent
    except Exception:
        pass
    pytest.skip("未找到插件源码目录")


def _src(name: str) -> str:
    return (_plugin_dir() / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 结构：实现只能有一处
# --------------------------------------------------------------------------

def test_retransfer_implementation_exists_once():
    """删除动作的实现只能有一处 —— `_retransfer_keys`。"""
    hits = []
    for f in _plugin_dir().glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_retransfer_keys":
                hits.append((f.name, node.lineno))
    assert len(hits) == 1, f"`_retransfer_keys` 应当只有一处定义，实际：{hits}"


def test_both_entry_points_delegate_to_the_shared_implementation():
    """
    两个入口都必须**转调**同一个实现，不得自己 `_delete_dest_files_for_retry`。

    ⚠️ 这条是核心：只要有一个入口自己删，它就会重新长出第二套行为
    （预检、失败处置、反馈都可能不同），而分叉正是本缺陷。
    """
    for fname, funcs in (
        ("commands.py", ["_dispatch_command"]),
        ("strm_ops.py", ["_api_strm_retry"]),
    ):
        src = _src(fname)
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in funcs:
                body = ast.get_source_segment(src, node)
                assert "_retransfer_keys" in body, (
                    f"{fname}.{node.name} 没有转调 `_retransfer_keys` —— "
                    f"删旧重传会重新出现第二份实现"
                )
                assert "_delete_dest_files_for_retry" not in body, (
                    f"{fname}.{node.name} 自己调了 `_delete_dest_files_for_retry` —— "
                    f"它绕过了共享实现（预检/失败处置会再次分叉）"
                )
                found = True
        assert found, f"{fname} 里找不到 {funcs}"


def test_shared_implementation_runs_the_preflight_before_deleting():
    """
    共享实现里，预检必须**排在删除之前** —— 顺序是承重的。

    反过来的话，闸门命中时文件已经删掉了。

    ⚠️ 判据必须落在**真实的调用节点**上，不能对源码做字符串查找：
    本函数的 docstring 里也提到了这两个函数名（解释它们各自做什么），
    按文本 `index()` 会命中注释里的那一处，得出错误结论
    —— 这正是「测试用文本匹配代替结构检查」的典型失效。
    """
    src = _src("strm_ops.py")
    tree = ast.parse(src)
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_retransfer_keys":
            func = node
    assert func is not None, "找不到 _retransfer_keys"

    calls = {}
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = getattr(target, "attr", None) or getattr(target, "id", None)
        if name in ("_retry_preflight", "_delete_dest_files_for_retry"):
            calls[name] = node.lineno

    assert "_retry_preflight" in calls, "共享实现里没有调用 _retry_preflight"
    assert "_delete_dest_files_for_retry" in calls, "共享实现里没有调用删除"
    assert calls["_retry_preflight"] < calls["_delete_dest_files_for_retry"], (
        f"删除（第 {calls['_delete_dest_files_for_retry']} 行）排在预检"
        f"（第 {calls['_retry_preflight']} 行）之前 —— 闸门命中时文件已被删掉"
    )


def test_chat_entry_points_pass_the_feedback_channel():
    """
    聊天入口必须把 event 透传下去，否则重传过程与结果都收不到。

    `_post_reply` 在 event 为空时直接 return，所以不传 = 全程静默：
    用户只看到发起时那一句，之后毫无音讯（实测过的「似乎没有重传」）。
    """
    cmd_src = _src("commands.py")
    tree = ast.parse(cmd_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_dispatch_command", "_strm_suspect_action"
        ):
            seg = ast.get_source_segment(cmd_src, node)
            if "_retransfer_keys" in seg or "_api_strm_retry" in seg:
                assert "channel_event=event" in seg, (
                    f"{node.name} 发起重传时没有传 channel_event —— "
                    f"用户不会收到任何进度或结果"
                )
