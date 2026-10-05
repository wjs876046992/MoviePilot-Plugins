"""
注册为端点的插件方法，其**签名**必须能过 Pydantic 的响应模型构造。

Endpoint-visible signatures must survive the host's Pydantic response-model build.

## 这个文件钉的缺陷（2026-09-28，实测）

宿主用插件方法的**签名**去构造 FastAPI 响应的 Pydantic 模型。给一个端点方法
加了 `channel_event: Optional[Event]` 之后：

    Error adding plugin route /api/v1/plugin/Rsync115Sync/strm_retry:
    Invalid args for response field! ... app.runtime.events.Event | None

**整条路由注册失败** —— 看板上的「删旧重传」直接消失。而日志里只有宿主
`routes.py` 的一行 ERROR，极易被当成无关噪音（实测刷了 10 条才发现）。

教训：**给端点方法加参数，注解必须是宿主/Pydantic 认识的类型**（`Any`、基本类型、
`Dict[str, Any]`…）。宿主自己的 `Event` 不在其中。

⚠️ 本用例是**静态**检查（扫签名），不需要 MoviePilot 后端 —— 这类问题恰恰
应该在改代码时就拦住，而不是等真机上路由消失。
"""

import ast
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
    # 有后端时走上面；没有时按本仓库布局推导（本用例不依赖后端，应当总能跑）
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "plugins.v3" / "rsync115sync"
        if cand.is_dir():
            return cand
    pytest.skip("未找到插件源码目录")


# 在签名里出现即会让 FastAPI 构造响应模型失败的类型名
_FORBIDDEN = ("Event", "EventType", "ChainEventType")


def _registered_endpoints(src: str) -> set:
    """从端点注册表里取出方法名。"""
    out = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
        if "path" not in keys or "endpoint" not in keys:
            continue
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == "endpoint":
                name = getattr(v, "attr", None)
                if name:
                    out.add(name)
    return out


def test_no_endpoint_signature_uses_a_host_event_type():
    """
    端点方法的参数注解里不得出现宿主事件类型。

    `Event` 等类型不是合法的 Pydantic 字段类型，会让**整条路由注册失败**，
    而现象是"看板上某个按钮不见了" —— 与注解毫无直观联系。
    """
    pkg = _plugin_dir()
    endpoints = _registered_endpoints((pkg / "__init__.py").read_text(encoding="utf-8"))
    assert endpoints, "没扫到任何端点，注册表结构可能变了"

    bad = []
    for f in pkg.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.FunctionDef) or node.name not in endpoints:
                continue
            for arg in list(node.args.args) + list(node.args.kwonlyargs):
                if arg.annotation is None:
                    continue
                text = ast.unparse(arg.annotation)
                if any(t in text for t in _FORBIDDEN):
                    bad.append(f"{f.name}:{node.lineno} {node.name}({arg.arg}: {text})")

    assert not bad, (
        "端点方法的参数注解里出现了宿主事件类型 —— 宿主会用它构造 Pydantic "
        "响应模型并失败，导致**整条路由注册不上**（看板上对应的按钮/区域消失），"
        "而日志里只有 routes.py 一行 ERROR。请改用 Any 或基本类型：\n  "
        + "\n  ".join(bad)
    )


def test_probe_detects_the_real_regression():
    """
    变异测试：确认上面的探针真的能抓到这类注解。

    只验证判据本身对"已知会出问题的写法"报红 —— 否则探针可能在空转。
    """
    sample = ast.parse(
        "def _api_x(self, body, channel_event: Optional[Event] = None): ..."
    )
    arg = sample.body[0].args.args[2]
    assert any(t in ast.unparse(arg.annotation) for t in _FORBIDDEN), (
        "探针认不出 Optional[Event] —— 它对真实缺陷也不会有反应"
    )
