"""
跨插件依赖边界：只有「先尝试生成 strm」依赖 P115StrmHelper。

Cross-plugin dependency boundary: exactly one feature needs the helper.

**为什么要测这个**：UI 上标注了「观察/扫描/重传不依赖插件」「仅补生成依赖」，
但这些标注是**声明**，代码一改就可能变成谎话 —— 用户会照着错的标注去判断
「我不装助手会少什么」。把边界写成断言，标注就有了强制力。

依赖一旦扩散（例如有人在删旧重传里顺手读一下助手配置），这个测试会失败，
提醒作者：要么撤掉改动，要么同步改 UI 与文档里的声明。
"""

import importlib
import inspect


def _plugin_class():
    module = importlib.import_module("app.plugins.rsync115sync")
    return module.Rsync115Sync


def _helper_refs_in(method_name):
    """统计某个方法体内引用助手的次数（源码级检查，不做运行）。"""
    src = inspect.getsource(getattr(_plugin_class(), method_name))
    markers = ("P115StrmHelper", "_P115_STRM", "_helper_running",
               "_helper_accepted_pan_roots", "_send_helper_command")
    return sum(src.count(m) for m in markers)


# --------------------------------------------------------------------------
# 自包含的能力：一个都不能碰助手
# --------------------------------------------------------------------------

def test_strm_cross_validation_does_not_touch_helper():
    """
    整条交叉验证链路必须自包含 —— 这是 UI 上「不依赖插件」那条 chip 的依据。

    它只读本地文件系统。若哪天有人为了「更准」而在这里查助手状态，
    不装助手的用户就会整套功能失效，而 UI 还在说「不依赖」。
    """
    for name in ("_strm_check", "_strm_arm_watch", "_strm_expected_path"):
        assert _helper_refs_in(name) == 0, f"{name} 不应依赖助手"


def test_proactive_scan_and_prune_do_not_touch_helper():
    """主动扫描、清理、关键字检查都必须是纯本地的。"""
    for name in ("_strm_scan", "_reply_strm_keyword", "_prune_invalid_strm_suspects"):
        assert _helper_refs_in(name) == 0, f"{name} 不应依赖助手"


def test_delete_and_retransfer_does_not_touch_helper():
    """
    **删旧重传**绝不能依赖助手。

    它是破坏性操作的最后退路：助手没装、助手坏了、助手路径没配 —— 这些情况下
    用户仍然必须能够删旧重传。把两者绑在一起，等于「助手一坏，坏文件也修不了」。
    """
    for name in ("_api_strm_retry", "_delete_dest_files_for_retry"):
        assert _helper_refs_in(name) == 0, f"{name} 不应依赖助手"


def test_core_sync_path_does_not_touch_helper():
    """同步主链路（媒体 → 115）与助手毫无关系，这是插件的立身之本。"""
    for name in ("_execute_sync", "_build_backfill_candidates", "_start_sync_thread"):
        assert _helper_refs_in(name) == 0, f"{name} 不应依赖助手"


# --------------------------------------------------------------------------
# 唯一依赖点
# --------------------------------------------------------------------------

def test_only_the_generate_endpoint_depends_on_helper():
    """
    反向断言：依赖**只**出现在补生成这一个入口上。

    这条是上一条的对照 —— 只测「不该依赖的没依赖」，无法发现「依赖悄悄扩散」。
    """
    cls = _plugin_class()
    source = inspect.getsource(cls)
    # 找出所有出现助手引用的方法名
    offenders = set()
    for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith("__"):
            continue
        if _helper_refs_in(name) > 0:
            offenders.add(name)
    allowed = {
        "_helper_running",            # 运行态探测（供就绪检查与补生成共用）
        "_helper_accepted_pan_roots",  # 发送前预检
        "_send_helper_command",       # 实际下发命令
        "_api_strm_generate",         # 补生成入口
        "_strm_helper_ready",         # 派生的就绪检查（调用 _helper_running）
        # 补生成成功后的收尾：它自己不调用助手，只是把条目移回观察期。
        # 出现在这里的原因是「补生成这件事」被有意收成一个方法，而不是说
        # 这里产生了新的依赖 —— 若要在这里读助手配置，就应该重新审视整个边界。
        "_rearm_after_gen_request",
        # get_api 只在路由表的注释里点名了助手（说明该端点是唯一依赖点），
        # 不构成运行时依赖；注释本身就是 UI 标注的契约来源。
        "get_api",
    }
    assert offenders <= allowed, (
        f"助手依赖扩散到了预期之外的方法：{sorted(offenders - allowed)}；"
        f"若这是有意的，请同步更新 UI 标注（Page.vue/Config.vue）与本文件的 allowed 集合"
    )


def test_api_endpoint_count_matches_documented_surface():
    """端点清单里只有 /strm_generate 需要外部插件（注释即契约，这里锁住它）。"""
    src = inspect.getsource(_plugin_class().get_api)
    assert "/strm_generate" in src
    # get_api 内只有一处提到助手依赖
    assert src.count("P115StrmHelper") == 1
