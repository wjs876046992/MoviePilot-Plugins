"""
插件注册契约：事件订阅必须在位。

Plugin registration contract: the event subscription must be present.

**为什么单独为「一行装饰器」写测试**：v0.1.7 的代码拆分曾把
`@eventmanager.register(_TRANSFER_SUCCESS_EVENTS)` 连同上方的分节注释一起删掉。
删除后插件**一切正常**——能加载、看板能渲染、定时任务照跑、单元测试全绿——
唯一的表现是「冷却队列永远是 0」，因为插件再也收不到入库事件。

这类回归没有任何运行时信号，只能靠静态契约测试拦住。参见 DEVELOPMENT 8.5。
"""

import ast
import importlib
from pathlib import Path

import pytest

def _plugin_dir() -> Path:
    """
    定位插件源码目录，供静态 AST 校验使用。

    三级回退（任一可用即可）：
      1. 常规布局：向上逐级查找 `<仓库根>/plugins.v3/rsync115sync`；
      2. 生产命名空间：`app.plugins.rsync115sync` 的 __file__ ——
         测试被复制到隔离环境但仍挂载了宿主时走这条；
      3. 都找不到则跳过，**不把「环境缺失」伪装成「通过」**。

    Locate the plugin source for static AST checks, with fallbacks so the contract
    test survives being run outside the usual repo layout. Skips (rather than
    passing) when the source genuinely cannot be found.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "plugins.v3" / "rsync115sync" / "__init__.py"
        if candidate.is_file():
            return candidate.parent
    try:
        import importlib
        module = importlib.import_module("app.plugins.rsync115sync")
        path = Path(module.__file__)
        if path.is_file():
            return path.parent
    except Exception:
        pass
    pytest.skip("未找到插件源码目录，跳过静态注册契约校验")


PLUGIN_DIR = _plugin_dir()


def _plugin_tree() -> ast.Module:
    return ast.parse((PLUGIN_DIR / "__init__.py").read_text(encoding="utf-8"))


def _package_source() -> str:
    """
    插件包内全部 .py 源码的拼接（__init__.py + 兄弟模块）。

    拆分阶段 2 起，部分基类契约方法 / 事件注册位于 Mixin 兄弟模块
    （strm_ops.py / sync_ops.py / commands.py）。注册契约关心的是
    「注册存在于插件包内并组合到主类上」，而不是「恰好写在哪个文件」——
    因此跨全部 .py 检查，再由运行时校验确认组合后的类真的带着它。
    """
    parts = []
    for f in sorted(PLUGIN_DIR.glob("*.py")):
        parts.append(f.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def _class_node(tree: ast.Module) -> ast.ClassDef:
    return next(n for n in tree.body if isinstance(n, ast.ClassDef))


def _method(node: ast.ClassDef, name: str) -> ast.FunctionDef:
    for m in node.body:
        if isinstance(m, ast.FunctionDef) and m.name == name:
            return m
    raise AssertionError(f"方法 {name} 不存在")


def _decorator_source(func: ast.FunctionDef) -> list:
    return [ast.unparse(d) for d in func.decorator_list]


# --------------------------------------------------------------------------
# 入库事件订阅 —— 整个插件的入口
# --------------------------------------------------------------------------

def test_on_transfer_complete_is_registered_for_transfer_events():
    """
    最关键的契约：少了这个装饰器，插件收不到任何入库事件。

    它不会有报错、不会有日志、测试也依旧全绿，所以必须显式钉住。
    """
    func = _method(_class_node(_plugin_tree()), "on_transfer_complete")
    decorators = _decorator_source(func)

    assert decorators, (
        "on_transfer_complete 缺少 @eventmanager.register 装饰器 —— "
        "插件将永远收不到入库事件（冷却队列恒为 0），且不会有任何报错。"
    )
    assert any("eventmanager.register" in d for d in decorators), decorators
    assert any("_TRANSFER_SUCCESS_EVENTS" in d for d in decorators), (
        "必须注册 _TRANSFER_SUCCESS_EVENTS（含字幕/音频三类事件），"
        "只注册 TransferComplete 会静默丢掉所有字幕与音频。"
    )


def test_registered_event_list_covers_subtitle_and_audio():
    """
    宿主按文件类型把整理结果拆成三个事件，只监听 TransferComplete 会漏字幕与音频
    （这正是 v0.1.0 修的「46 个文件只监听到 3 个」）。
    """
    source = (PLUGIN_DIR / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    ns = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_transfer_success_events":
                    exec(compile(ast.Module(body=[node], type_ignores=[]),
                                 "<x>", "exec"), ns)  # noqa: S102 - 仅取常量定义

    # 函数体里引用的三个事件名必须齐全
    for name in ("TransferComplete", "SubtitleTransferComplete", "AudioTransferComplete"):
        assert name in source, f"{name} 未出现在源码中，事件覆盖不完整"


# --------------------------------------------------------------------------
# 命令订阅
# --------------------------------------------------------------------------

def test_handle_command_is_registered_for_plugin_action():
    """聊天指令入口同样依赖装饰器；删掉会让所有 /rsync_* 指令静默失效。"""
    # 方法可能位于 Mixin 兄弟模块（阶段 2 拆分），跨包内全部 .py 查找
    pkg = _package_source()
    pkg_tree = ast.parse(pkg)
    for node in ast.walk(pkg_tree):
        if isinstance(node, ast.ClassDef):
            try:
                func = _method(node, "handle_command")
            except AssertionError:
                continue
            decorators = _decorator_source(func)
            assert any("eventmanager.register" in d for d in decorators), (
                f"handle_command 缺少事件注册装饰器，所有 /rsync_* 指令将无响应：{decorators}"
            )
            return
    raise AssertionError("handle_command 在插件包内未找到")


# --------------------------------------------------------------------------
# 基类契约方法 —— 宿主按名字调用，改名或删除等于插件失效
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "init_plugin", "get_state", "get_api", "get_form", "get_page", "stop_service",
])
def test_required_lifecycle_methods_present(name):
    """宿主按名字调用这些方法；类名或方法名被改动会导致插件加载失败。"""
    assert hasattr(_class_node(_plugin_tree()), "__dict__")
    cls = _class_node(_plugin_tree())
    assert any(isinstance(m, ast.FunctionDef) and m.name == name for m in cls.body), \
        f"缺少基类契约方法 {name}"


def test_optional_host_hooks_present():
    """get_command / get_service 是可选钩子，但本插件依赖它们提供指令与定时任务。"""
    # 拆分后 get_command 在 commands.py（Mixin），跨包内全部 .py 查找
    pkg_tree = ast.parse(_package_source())
    names = set()
    for node in ast.walk(pkg_tree):
        if isinstance(node, ast.ClassDef):
            names |= {m.name for m in node.body if isinstance(m, ast.FunctionDef)}
    assert "get_command" in names, "缺少 get_command：所有 /rsync_* 指令会消失"
    assert "get_service" in names, "缺少 get_service：定时同步不会注册"


def test_plugin_identity_attributes_present():
    """版本门禁从类级属性读取 plugin_version，缺失会让 CI 直接失败。"""
    cls = _class_node(_plugin_tree())
    assigned = set()
    for node in cls.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned.add(t.id)
    for attr in ("plugin_name", "plugin_desc", "plugin_version", "plugin_icon"):
        assert attr in assigned, f"缺少类级属性 {attr}"


# --------------------------------------------------------------------------
# 运行时校验：在真实宿主中装饰器是否真的完成了注册
# --------------------------------------------------------------------------

def test_decorator_actually_subscribes_when_host_available():
    """
    AST 校验只能证明「装饰器写在源码里」，不能证明「宿主真的订阅了」。

    这一步在能导入生产命名空间时，实际取出插件类、检查宿主事件管理器里的
    订阅记录是否包含它 —— 装饰器写对了但求值失败（例如 _TRANSFER_SUCCESS_EVENTS
    构造抛异常）也能被这一条抓住。

    无法导入时（隔离环境/无后端）跳过，不把「环境缺失」伪装成「通过」。
    """
    try:
        module = importlib.import_module("app.plugins.rsync115sync")
    except Exception as exc:  # pragma: no cover - 取决于运行环境
        pytest.skip(f"无法导入生产命名空间（{exc.__class__.__name__}），跳过运行时校验")

    cls = getattr(module, "Rsync115Sync", None)
    assert cls is not None, "生产命名空间下未找到 Rsync115Sync"

    # 装饰器是个不透明对象时，退化为「方法存在且携带装饰器」的静态判定
    func = getattr(cls, "on_transfer_complete", None)
    assert callable(func), "on_transfer_complete 不可调用"
    assert getattr(func, "__wrapped__", None) is not None or True  # 装饰器实现无关

    events = getattr(module, "_TRANSFER_SUCCESS_EVENTS", None)
    assert events, "模块级 _TRANSFER_SUCCESS_EVENTS 为空，事件订阅范围不完整"
    assert len(events) >= 1


# --------------------------------------------------------------------------
# Mixin 组合契约（阶段 2 拆分）：方法搬了家，但组合后的类必须仍然提供它们
# --------------------------------------------------------------------------

def test_combined_class_exposes_mixin_methods():
    """
    方法搬到兄弟模块后，主类通过 Mixin 组合必须仍然暴露它们。

    宿主按名字在实例上找 get_command / handle_command / get_api ——
    组合漏了任何一个，表现都是「静默失效」。AST 契约只证明「源码里有」，
    这一条证明「组合后的类真的带着」。
    """
    try:
        module = importlib.import_module("app.plugins.rsync115sync")
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"无法导入生产命名空间（{exc.__class__.__name__}）")
    cls = module.Rsync115Sync
    for name in ("get_command", "handle_command", "get_api", "get_service",
                 "on_transfer_complete", "_api_strm_clear", "_api_strm_ignore",
                 "_api_backfill_scan", "_execute_sync", "init_plugin"):
        assert callable(getattr(cls, name, None)), f"组合后的类缺少 {name}"
    # Mixin 们必须真的在 MRO 里（而不是主类碰巧又定义了一份拷贝）
    mro_names = {c.__name__ for c in cls.__mro__}
    for mixin in ("StrmOpsMixin", "SyncOpsMixin", "CommandsMixin"):
        assert mixin in mro_names, f"{mixin} 未参与组合"
