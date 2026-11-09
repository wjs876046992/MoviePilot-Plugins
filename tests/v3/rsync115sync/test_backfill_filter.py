"""
定向补传：只补某一季，不惊动整个库。

Targeted backfill: restrict candidates to one season/show.

## 为什么需要这个入口

源端游标曾用 mtime 判据，保留旧时间戳的硬链接会永久漏扫（详见
`test_source_scan_mtime.py`）。修复判据只对**之后**的扫描生效 —— 历史上漏掉的
文件 mtime 依然早于游标，不会自动回来。

补救路径必须用「补传」（`_build_backfill_candidates`），因为它的口径是
「源端存在、且从未进过队列」，**完全不看 mtime**。

但 `_api_backfill_start` 会把候选**全部**真的上传。一个几千条的库为了补 14 集
而全量补传，代价远超必要。所以加了 `path_filter`：只保留相对路径包含指定
子串的候选。

## 约束

- 空 filter 必须与改动前**完全等价**（不筛选）。这是默认路径，不能有行为变化。
- 筛选必须在幂等判据（队列/忽略清单）**之前**做：被筛掉的路径不该再去查表。
"""

import re
from pathlib import Path

import pytest


def _sync_ops() -> str:
    for parent in Path(__file__).resolve().parents:
        p = parent / "plugins.v3" / "rsync115sync" / "sync_ops.py"
        if p.is_file():
            return p.read_text(encoding="utf-8")
    pytest.skip("sync_ops.py 未找到")


def test_build_candidates_accepts_filter():
    """候选构建函数必须接受 path_filter 参数，且默认值为空（不筛选）。"""
    src = _sync_ops()
    m = re.search(r"def _build_backfill_candidates\(self([^)]*)\)", src)
    assert m, "找不到 _build_backfill_candidates"
    sig = m.group(1)
    assert "path_filter" in sig, (
        "缺少 path_filter 参数 —— 定向补传无处落地，只能全量补传"
    )
    assert 'path_filter: str = ""' in sig, (
        "path_filter 必须有默认空值 —— 否则现有的『全量补传』调用点会 TypeError"
    )


def test_filter_is_applied():
    """筛选逻辑必须存在，且比对的是相对路径。"""
    src = _sync_ops()
    m = re.search(r"def _build_backfill_candidates\(self.*?(?=\n    def )", src, re.DOTALL)
    assert m, "找不到 _build_backfill_candidates 函数体"
    body = m.group(0)
    assert "needle" in body and "not in root_rel" in body, (
        "没有按相对路径做子串筛选 —— path_filter 参数会被静默忽略"
    )


def test_filter_runs_before_idempotency_checks():
    """
    筛选必须排在队列/忽略清单判据**之前**。

    顺序反了不会产生错误结果，但会让被筛掉的成千上万条路径也去查队列与
    忽略清单 —— 定向补传的收益（只扫一小部分）就被抹掉了。
    """
    src = _sync_ops()
    m = re.search(r"def _build_backfill_candidates\(self.*?(?=\n    def )", src, re.DOTALL)
    body = m.group(0)
    filter_pos = body.find("not in root_rel")
    queue_pos = body.find("self._pending_queue")
    assert filter_pos != -1 and queue_pos != -1
    assert filter_pos < queue_pos, (
        "筛选写在幂等判据之后 —— 被筛掉的路径仍然会去查队列，白白放大开销"
    )


def test_api_endpoints_forward_the_filter():
    """两个 API 都必须把 body 里的 filter 传给候选构建函数。"""
    src = _sync_ops()
    for name in ("_api_backfill_scan", "_api_backfill_start"):
        m = re.search(rf"def {name}\(self.*?(?=\n    def )", src, re.DOTALL)
        assert m, f"找不到 {name}"
        body = m.group(0)
        assert 'get("filter")' in body, f"{name} 没有从 body 读取 filter"
        assert "_build_backfill_candidates(path_filter)" in body, (
            f"{name} 没有把 path_filter 传下去 —— 定向补传在该入口失效"
        )


def test_scan_endpoint_is_post_not_get():
    """
    `/backfill_scan` 必须注册为 **POST**。

    ⚠️ 这条来自**真机实测**：它原本是 GET，而参数从 `body` 里读 ——
    FastAPI 不会把 query string 塞进 `body: Optional[Dict]`，于是 GET 下
    filter 被静默丢弃。实测返回里 `"filter": ""`，而同一请求改成 POST 后
    正确返回了筛选结果。

    这个缺陷单靠读代码发现不了（签名看着没问题，逻辑也对），
    只有对着真机打一次请求才会暴露。所以把它钉成测试。
    """
    src = _init_py()
    m = re.search(r'\{"path": "/backfill_scan"[^}]*\}', src)
    assert m, "找不到 /backfill_scan 的路由注册"
    route = m.group(0)
    assert '"POST"' in route, (
        "/backfill_scan 注册成了 GET —— 它从 body 读 filter，GET 下参数会被静默丢弃"
    )
    assert '"GET"' not in route, "/backfill_scan 不要同时注册 GET"


def _init_py() -> str:
    for parent in Path(__file__).resolve().parents:
        p = parent / "plugins.v3" / "rsync115sync" / "__init__.py"
        if p.is_file():
            return p.read_text(encoding="utf-8")
    pytest.skip("__init__.py 未找到")


def test_scan_endpoint_signature_is_fastapi_safe():
    """
    端点签名不得使用会被 FastAPI 当成响应模型的注解。

    宿主会 introspect `get_api()` 列出的方法签名，注解成非基本类型会让
    **整个路由静默注册失败**（看板对应区域直接消失）。这里用
    `filter` 之外只剩 `Optional[Dict[str, Any]]`，那是安全的基本形态；
    真正要防的是有人手滑写成 `body: SomeModel = None` 之类的具体类。
    """
    src = _sync_ops()
    m = re.search(r"def _api_backfill_scan\(self([^)]*)\)", src)
    assert m, "找不到 _api_backfill_scan 签名"
    sig = m.group(1)
    assert "Optional[Dict[str, Any]]" in sig, (
        "端点参数应保持 Optional[Dict[str, Any]]，不要换成具体模型类"
    )
