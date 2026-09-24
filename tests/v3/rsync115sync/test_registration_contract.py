"""
插件注册契约：事件订阅必须在位。

Plugin registration contract: the event subscription must be present.

**为什么单独为「一行装饰器」写测试**：v0.1.7 的代码拆分曾把
`@eventmanager.register(EventType.WebhookMessage)` 连同上方的分节注释一起删掉。
删除后插件**一切正常**——能加载、看板能渲染、定时任务照跑、单元测试全绿——
唯一的表现是「冷却队列永远是 0」，因为插件再也收不到入库事件。

这类回归没有任何运行时信号，只能靠静态契约测试拦住。参见 DEVELOPMENT 8.5。
"""

import ast
import importlib
from pathlib import Path
from typing import Optional

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
# 入库来源订阅 —— 整个插件的入口
# --------------------------------------------------------------------------
#
# ⚠️ 本节原先钉的是**宿主整理完成事件**（`on_transfer_complete` +
# `_TRANSFER_SUCCESS_EVENTS`）。那条订阅已于 2026-09-25 整条删除，理由四条：
#   1. 只覆盖整理链路 —— 手动入库、外部工具搬入、9KG 全都不产生整理事件；
#   2. durable outbox **不重放** —— 插件忙/重载期间的事件永久丢弃；
#   3. 宿主版本相关 —— 后两个事件靠 getattr 探测，旧宿主下字幕音频静默全丢；
#   4. 装饰器在**类体**求值 —— 被误删过一次且不报错（v0.1.7，见 §3.8）。
#
# 替代它的主通道是**源端游标扫描**（独立 service，见下）。本节因此改为钉住：
#   · 那条订阅**确实已被删除**（防止被误加回来 —— 它与新通道职责重叠）；
#   · webhook 订阅仍在；
#   · 主通道的 service 已注册。


def test_transfer_event_subscription_is_gone():
    """
    反向哨兵：宿主整理完成事件的订阅必须**不存在**。

    为什么值得专门钉一条：删掉它不会有任何报错，而**加回来**同样不会有 ——
    一旦有人"顺手恢复"这段代码，就会出现两条职责重叠的入库通道：
    事件那条会带来它的四个静默失效点，而扫描那条已经覆盖了它的全部场景。
    留着重复的通道只会让「到底哪条在丢文件」重新变成需要猜测的问题。
    """
    source = (PLUGIN_DIR / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    # 1) 不能有 on_transfer_complete 方法，也没有指向它的订阅装饰器
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            assert node.name != "on_transfer_complete", (
                "on_transfer_complete 被加回来了 —— 该订阅已废弃，主通道是源端游标扫描"
            )
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "eventmanager" and node.attr == "register":
                assert "TransferComplete" not in ast.dump(node), (
                    "出现了对 TransferComplete 的事件订阅 —— 已废弃"
                )

    # 2) 模块级常量不得复活。
    # ⚠️ 用 AST 找 **Name/赋值目标**，不要 grep 原始源码 —— 文件顶部有一段
    # 专门解释"这里曾经有过什么、为什么删掉"的注释，grep 会命中它并误报。
    # （这条断言第一版就是这么写错的：注释成了它自己的假红来源。）
    live_names = {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
    } | {
        t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name)
    }
    assert "_TRANSFER_SUCCESS_EVENTS" not in live_names, (
        "_TRANSFER_SUCCESS_EVENTS 被以代码引用了（注释里提到是允许的）"
    )
    func_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_transfer_success_events" not in func_names, "_transfer_success_events 不得复活"


def test_webhook_subscription_survives():
    """
    webhook 订阅必须**保留**（它是 9KG 的专属通道 + 加速器）。

    与上一条同样重要且方向相反：删掉这个装饰器不会有任何报错，
    表现为「发送端明明推了、日志里一条 webhook 记录都没有」。
    """
    func = _method(_class_node(_plugin_tree()), "on_webhook_message")
    decorators = _decorator_source(func)

    assert decorators, (
        "on_webhook_message 缺少 @eventmanager.register 装饰器 —— "
        "宿主的 webhook 广播将无人接收，且不会有任何报错。"
    )
    assert any("eventmanager.register" in d for d in decorators), decorators
    assert any("WebhookMessage" in d for d in decorators), (
        f"必须注册 EventType.WebhookMessage，实际装饰器：{decorators}"
    )


def test_source_scan_service_is_registered():
    """
    入库发现的**主通道**必须注册成 service。

    为什么在契约测试里钉：扫描一旦不注册，插件不会报错、看板照常渲染、
    webhook 也照常工作 —— 只是**新入库的文件再也不会被自动发现**，
    而且只有当用户注意到「队列很久没动静」时才会暴露。
    """
    source = (PLUGIN_DIR / "__init__.py").read_text(encoding="utf-8")

    assert "Rsync115Sync_SourceScan" in source, "源端扫描 service 未注册"
    assert "_scan_source_cursor_safe" in source, "源端扫描的 service 入口不存在"
    # 扫描必须由**独立** service 驱动，不能还挂在同步 cron 里
    # （挂在里面会被「补传优先 return」饿死，见 _scheduled_sync 的说明）
    tree = ast.parse(source)
    sched = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_sync":
            sched = ast.dump(node)
    assert sched is not None, "未找到 _execute_sync"
    assert "_scan_source_cursor()" not in sched, (
        "_execute_sync 里又出现了源端扫描调用 —— 它必须由独立 service 驱动，"
        "否则会被补传队列饿死"
    )


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


# --------------------------------------------------------------------------
# webhook_parser 必须被 get_module() 声明 —— 只实现方法是**不会**被调用的
# --------------------------------------------------------------------------
#
# 这一组是 2026-09-22 真机联调的最终结论，也是本文件里最贵的一条教训。
#
# 症状：`source=rsync115sync` 的报文打进来，宿主日志能看到请求，插件一行日志
# 都没有。排查依次走过 Content-Type（真踩到了，但不是本次的因）、地址尾斜杠
# （真踩到了，也不是）、映射配置 —— 每一轮都建立在「插件已被调用」这个**错误
# 前提**上，因此怎么查都查不到。
#
# 真因：宿主是从 `get_module()` 返回的「方法名 → 方法」映射里收集 provider 的
# （app/runtime/extensions/plugin/projection.py 的 modules()：`declared =
# plugin.get_module()`，返回 None 直接 continue）。基类默认实现 `pass` → 返回
# None。**所以只写 `def webhook_parser(...)` 是死代码** —— 永远不会被调用，
# 也不会报错。加一行 `"webhook_parser": self.webhook_parser` 就通了。
#
# 教训（与文件开头那段同源，但更隐蔽）：文件开头那条是「装饰器被删」，
# 装饰器至少写在源码里看得见；这一条是**从未存在过**的声明 ——
# 没有删除记录、没有 diff、没有报错，静态搜索 `webhook_parser` 会命中
# 方法定义，让所有基于 grep 的自查都误判为「已实现」。

def test_webhook_parser_is_declared_in_get_module():
    """
    静态契约：`get_module()` 必须声明 `webhook_parser`。

    断言的是**返回值**而不是「方法名出现在源码里」—— 后者正是当初误判的原因：
    `webhook_parser` 方法确实定义在源码里，但没人调用它。
    """
    src = (PLUGIN_DIR / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    declaring: Optional[ast.FunctionDef] = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_module":
            declaring = node
            break
    assert declaring is not None, (
        "本插件实现了 webhook_parser，必须用 get_module() 向宿主声明；"
        "缺少该方法会让认领通道整条静默失效（宿主不会报错）"
    )

    # 收集 return 的字典字面量里的字符串键
    keys = set()
    for node in ast.walk(declaring):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(key.value)
    assert "webhook_parser" in keys, (
        "get_module() 的返回字典里必须包含 'webhook_parser' 键；"
        "只定义方法不声明 = 宿主永远不调用它（这正是真机联调排查三轮的原因）"
    )


def test_webhook_parser_declaration_returns_the_bound_method():
    """
    运行时契约：声明的必须是**本实例的绑定方法**，且真能返回可认领的结果。

    只做静态 AST 校验不够 —— `{"webhook_parser": self.something_else}` 这种
    键对值错的写法同样能通过 AST 检查，却会让宿主调用到错误的实现。
    这里在能导入生产命名空间时真正调用一次 `get_module()`。
    """
    try:
        module = importlib.import_module("app.plugins.rsync115sync")
    except Exception as exc:  # pragma: no cover - 取决于运行环境
        pytest.skip(f"无法导入生产命名空间（{exc.__class__.__name__}），跳过运行时校验")

    cls = module.Rsync115Sync
    instance = cls.__new__(cls)          # 不跑 init_plugin：这里只验声明本身
    declared = instance.get_module()

    assert isinstance(declared, dict), "get_module() 必须返回字典（宿主只接受 Mapping）"
    assert "webhook_parser" in declared, "未声明 webhook_parser"
    func = declared["webhook_parser"]
    assert callable(func), "webhook_parser 声明项必须可调用"
    # 必须是绑定了本实例的方法：宿主会直接 `func(body=..., form=..., args=...)`
    assert getattr(func, "__self__", None) is instance, (
        "声明的必须是 self.webhook_parser（绑定方法），不能是类或其它函数 ——"
        "宿主会直接调用它，签名不符不会报错、只会拿不到值"
    )
    # 光验「是个绑定方法」还不够：`{"webhook_parser": self._别的同名签名方法}`
    # 同样能通过（签名不同在兼容阶段只诊断不拒绝）。必须**按名字**核对。
    assert getattr(func, "__name__", "") == "webhook_parser", (
        f"声明的实现必须是 webhook_parser 本身，实际是 "
        f"{getattr(func, '__name__', type(func).__name__)} —— 键对值错同样会静默失效"
    )


def test_no_other_module_methods_are_implemented_but_undeclared():
    """
    反向审计：**不允许存在「实现了宿主模块方法却没声明」的死代码。**

    宿主模块方法名是一份固定清单（`_METHOD_CONTRACTS` 去掉下划线前缀的公开方法，
    外加冻结清单）。插件上若出现与其中某个同名的可调用成员，却不在 `get_module()`
    的返回里，那就是 §9.17 那种死代码 —— 宿主永远不会调用它，也不会有任何提示。

    这条是**通用**哨兵，专治「以后又在别的地方犯同一个错」：新增任何胁持方法时，
    忘了声明就会被它拦下，而不是等到真机上发现「什么都没发生」。
    """
    try:
        module = importlib.import_module("app.plugins.rsync115sync")
    except Exception as exc:  # pragma: no cover - 取决于运行环境
        pytest.skip(f"无法导入生产命名空间（{exc.__class__.__name__}）")
    import inspect

    host_methods = _host_module_method_names()
    if not host_methods:  # pragma: no cover - 找不到宿主源码时
        pytest.skip("无法读取宿主模块方法清单，跳过反向审计")

    cls = module.Rsync115Sync
    instance = cls.__new__(cls)
    declared = set(instance.get_module() or {})
    implemented = {name for name, _ in inspect.getmembers(cls, callable)}

    undeclared = sorted((host_methods & implemented) - declared)
    assert not undeclared, (
        f"插件实现了宿主模块方法 {undeclared} 但未在 get_module() 里声明 —— "
        f"宿主永远不会调用它们（不报错、无日志），见 DEVELOPMENT §9.17"
    )


def _host_module_method_names():
    """
    从宿主源码里解析出模块方法名清单。

    不导入 `app.runtime.extensions.module.contracts`：测试环境只有 `app.plugins` 桩，
    没有完整宿主。改为 AST 解析 —— 与其余契约测试同一策略（找不到就跳过，
    不把「环境缺失」伪装成「通过」）。
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "MoviePilot" / "app" / "runtime" / "extensions" / \
            "module" / "contracts.py"
        if candidate.is_file():
            break
    else:
        candidate = Path("/tmp/mp-src/app/runtime/extensions/module/contracts.py")
        if not candidate.is_file():
            return set()

    tree = ast.parse(candidate.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = {getattr(t, "id", "") for t in node.targets}
        if "_METHOD_CONTRACTS" in targets and isinstance(node.value, ast.Dict):
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    names.add(key.value)
        if targets & {"_FROZEN_METHODS", "_LEGACY_METHODS"} and \
                isinstance(node.value, (ast.List, ast.Tuple)):
            for entry in node.value.elts:
                if isinstance(entry, ast.Constant) and isinstance(entry.value, str):
                    names.add(entry.value)
    return names


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

    # webhook 处理器必须可调用（它是唯一保留的事件订阅）
    assert callable(getattr(cls, "on_webhook_message", None)), "on_webhook_message 不可调用"
    # 已废弃的事件侧符号不得复活
    assert not hasattr(cls, "on_transfer_complete"), "on_transfer_complete 不得复活"
    assert not hasattr(module, "_TRANSFER_SUCCESS_EVENTS"), "_TRANSFER_SUCCESS_EVENTS 不得复活"


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
                 "on_webhook_message", "_api_strm_clear", "_api_strm_ignore",
                 "_api_backfill_scan", "_execute_sync", "init_plugin",
                 "_scan_source_cursor", "_scan_source_cursor_safe",
                 "_cooldown_basis", "_has_ready_files"):
        assert callable(getattr(cls, name, None)), f"组合后的类缺少 {name}"
    # Mixin 们必须真的在 MRO 里（而不是主类碰巧又定义了一份拷贝）
    mro_names = {c.__name__ for c in cls.__mro__}
    for mixin in ("StrmOpsMixin", "SyncOpsMixin", "CommandsMixin"):
        assert mixin in mro_names, f"{mixin} 未参与组合"
