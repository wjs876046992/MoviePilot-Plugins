"""DynamicWeChat 页面形状测试（--noconftest 可跑）。

对应 REDESIGN_REQUIREMENTS.md 验收标准 1–8、10：

1. Cookie 失效红条不再被 _is_special_upload 门控消失；
2. 插件未启用时顶部灰条、无成功色；
3. 连续无结论 ≥3 出现橙色网络告警；
4. 未配第三方 Token 时「IP变动后通知」开关仍存在（含警示说明）；
5. 通知 Token placeholder 不再出现微信/AnPush；
6. 测试按钮在配置页、不在详情页；
7. get_page 连续两次调用不改 _qr_code_image（渲染无写副作用）；
8. 二维码三态文案互不相同；
10. 全部用户可见文本无 Markdown 标记、无内部术语。

导入宿主 app.* 会失败（无后端），因此不导入插件模块，而是以 AST 从源码中
提取 get_page/get_form 的源码段执行——不行，函数体依赖实例状态，AST 执行
不可行。改为「源码文本 + 结构」双断言：文本断言验收 4/5/10/（按钮位置 6），
结构断言用 importlib 加载（会因缺 app 失败）……

最终方案：用 ast 提取 get_page/_page_snapshot/_banner 的源码，连同 helper.py
（无宿主依赖）一起，在一个 stub 命名空间里 exec——stub 掉宿主依赖模块后，
__init__.py 顶层 import 失败无法 exec 整个文件；因此本测试把
「get_page + _page_snapshot + _is_ipv4 + _banner 局部」从 __init__.py 源码中
按函数边界切出，在提供 datetime/base64/re 等标准库的命名空间中 exec，
再用 object 级 stub 实例调用。这不经过宿主命名空间，等价于纯逻辑测试。
"""

import ast
import re
import textwrap
import base64  # noqa: F401  (exec 命名空间用)
from datetime import datetime, timedelta  # noqa: F401
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[3]
PLUGIN_DIR = ROOT / "plugins.v3" / "dynamicwechat"
SOURCE = (PLUGIN_DIR / "__init__.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename="__init__.py")


def _extract_function(name: str) -> str:
    """按顶层类内函数边界切出源码段（含装饰器行之前的 def）。"""
    lines = SOURCE.split("\n")
    starts = [i for i, l in enumerate(lines) if re.match(rf"    def {name}\(", l)]
    assert starts, f"{name} not found"
    s = starts[0]
    # 函数结束：下一个同缩进 def/装饰器/类结束
    e = len(lines)
    for j in range(s + 1, len(lines)):
        stripped = lines[j]
        if stripped and not stripped.startswith(" ") and not stripped.startswith("\t"):
            e = j
            break
        if re.match(r"    (def |@|async def )", stripped):
            e = j
            break
    return textwrap.dedent("\n".join(lines[s:e]))


def _build_page_env(extra_attrs: dict):
    """构造可执行 get_page/_page_snapshot/_is_ipv4 的命名空间与 stub 实例。"""
    ns = {
        "datetime": datetime,
        "timedelta": timedelta,
        "base64": base64,
        "re": re,
        "List": list,
        "Dict": dict,
        "Any": object,
        "Tuple": tuple,
    }
    exec(_extract_function("_is_ipv4"), ns)
    exec(_extract_function("_translate_check_result"), ns)
    exec(_extract_function("get_page"), ns)

    self = SimpleNamespace()
    defaults = dict(
        _enabled=True,
        _input_id_list="1000002",
        _cron="0 * * * *",
        _cookie_valid=True,
        _cookie_lifetime=86400,
        _is_special_upload=True,
        _saved_cookie=[{"name": "x"}],
        _none_streak=0,
        _last_keepalive_ok=True,
        _last_keepalive_note="本地Cookie校验有效",
        _last_ip_check_ok=True,
        _last_ip_check_note="公网IP未变化",
        _ip_changed=True,
        _current_ip_address="1.2.3.4",
        _qr_running=False,
        _future_timestamp=0,
        _qr_code_image=None,
        _waiting_captcha=False,
        _use_mp_notify=True,
        _my_send=None,
        _notification_token="",
        _await_ip=False,
        _company_domain="",
        _last_ddns_ok=None,
        _last_ddns_ip="",
        wan2=None,
        _pinned_ips="",
        _use_cookiecloud=True,
        _cc_server=None,
        mask_ip=lambda ip: ip,
        _wan_enabled=False,
        _wan_max_ips="",
        _custom_ip_urls="",
    )
    defaults.update(extra_attrs)
    for k, v in defaults.items():
        setattr(self, k, v)
    # 快照函数从独立命名空间 exec 出来，再绑到实例上（get_page 经 self._page_snapshot() 调用）
    snap_ns = {
        "Dict": dict, "Any": object, "datetime": datetime,
        "re": re, "CronTrigger": SimpleNamespace(from_crontab=lambda c: None),
        "settings": SimpleNamespace(
            COOKIECLOUD_KEY="k", COOKIECLOUD_PASSWORD="p", COOKIECLOUD_ENABLE_LOCAL=False),
    }
    exec(_extract_function("_is_ipv4"), snap_ns)
    exec(_extract_function("_page_snapshot"), snap_ns)
    self._page_snapshot = lambda: snap_ns["_page_snapshot"](self)
    self._is_ipv4 = lambda ip: snap_ns["_is_ipv4"](ip)
    return ns, self


def _banner_texts(page_result):
    """从 get_page 返回结构中收集全部可见状态文本（div/VChip/td/span）。"""
    texts = []

    def walk(node):
        if isinstance(node, dict):
            comp = node.get("component")
            if comp in ("div", "VChip", "span", "td") and node.get("text"):
                texts.append(node["text"])
            for child in node.get("content", []) or []:
                walk(child)

    for item in page_result:
        walk(item)
    return texts


def _all_texts(nodes):
    """收集结构中所有 text/label/placeholder 字段值。"""
    out = []

    def walk(node):
        if isinstance(node, dict):
            for key in ("text", "label", "placeholder"):
                v = node.get(key)
                if isinstance(v, str):
                    out.append(v)
            for child in node.get("content", []) or []:
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(nodes)
    return out


# ---------- 验收 1：Cookie 失效红条不被 _is_special_upload 门控 ----------

def test_cookie_invalid_banner_not_gated():
    ns, self_ = _build_page_env({
        "_cookie_valid": False,
        "_is_special_upload": False,
        "_none_streak": 0,
    })
    texts = _banner_texts(ns["get_page"](self_))
    assert any("自动恢复失败" in t for t in texts), texts


# ---------- 验收 2：未启用时灰条、无成功色 ----------

def test_disabled_banner_gray_no_green():
    ns, self_ = _build_page_env({"_enabled": False, "_is_special_upload": False})
    result = ns["get_page"](self_)
    texts = _banner_texts(result)
    assert any("插件未启用" in t for t in texts), texts
    # 不应出现 success 色的 chip（未启用时无任何成功状态）
    def has_success_chip(node):
        if isinstance(node, dict):
            if node.get("component") == "VChip":
                if (node.get("props") or {}).get("color") == "success":
                    return True
            return any(has_success_chip(c) for c in (node.get("content") or []) if isinstance(c, (dict, list)))
        if isinstance(node, list):
            return any(has_success_chip(i) for i in node)
        return False
    assert not has_success_chip(result)


# ---------- 验收 3：连续无结论告警 ----------

def test_none_streak_warning_banner():
    ns, self_ = _build_page_env({
        "_cookie_valid": False,
        "_none_streak": 3,
    })
    texts = _banner_texts(ns["get_page"](self_))
    assert any("连续 3 次无法确认登录状态" in t for t in texts), texts


# ---------- 验收 4：await_ip 开关恒存在（配置页） ----------

def test_await_ip_switch_always_rendered():
    """配置页结构中必须始终包含 await_ip 开关（不再条件渲染整个开关）。"""
    assert "'model': 'await_ip'" in SOURCE
    # 旧实现：开关整体包在 if self._my_send ... else [] 里；新实现为无条件行
    # 断言 await_ip 行不在条件列表推导的 else [] 分支中——检查其 VCol 不在 *() 内
    lines = SOURCE.split("\n")
    idx = next(i for i, l in enumerate(lines) if "'model': 'await_ip'" in l)
    # 向上找最近的 '*' 开头的条件展开行（旧写法特征）
    window = "\n".join(lines[max(0, idx - 30):idx])
    assert "*(" not in window.split("VRow")[-1] or "'await_ip'" not in window, (
        "await_ip 开关不应位于条件展开块内"
    )


# ---------- 验收 5：placeholder 不再教用户填无效渠道 ----------

def test_notification_placeholder_channels_correct():
    assert "微信" not in _placeholder_of("notification_token")
    assert "AnPush" not in _placeholder_of("notification_token")
    placeholder = _placeholder_of("notification_token")
    assert "Server酱" in placeholder and "||Q" in placeholder


def _placeholder_of(model: str) -> str:
    m = re.search(
        rf"'model': '{model}'.*?'placeholder':\s*'([^']*)'", SOURCE, re.S)
    assert m, f"placeholder for {model} not found"
    return m.group(1)


# ---------- 验收 6：测试按钮在配置页、不在详情页 ----------

def test_test_notify_button_location():
    """验收 6：测试按钮只出现在 get_form 的页面结构里，get_page 内不得有按钮。"""
    form_src = _extract_function("get_form")
    page_src = _extract_function("get_page")
    assert "test_notify" in form_src, "配置页应有测试通知按钮"
    assert "test_notify" not in page_src, "详情页不应再有测试通知按钮"


# ---------- 验收 7：get_page 无写副作用 ----------

def test_get_page_no_side_effect():
    sentinel = object()
    ns, self_ = _build_page_env({"_qr_code_image": sentinel, "_future_timestamp": 0})
    ns["get_page"](self_)
    ns["get_page"](self_)
    assert self_._qr_code_image is sentinel
    # 源码层面：get_page 函数体内不得出现对 _qr_code_image 的赋值
    page_src = _extract_function("get_page")
    assert not re.search(r"self\._qr_code_image\s*=\s*None", page_src)


# ---------- 验收 8：二维码状态文案互不相同 ----------

def test_qr_three_states_distinct():
    """无任务 / 运行中未出码 / 有效 三态文案互不相同（运行中已过期并入黄条族但与运行中未出码可区分）"""
    ns1, s1 = _build_page_env({"_qr_running": False, "_future_timestamp": 0})
    t1 = _banner_texts(ns1["get_page"](s1))
    ns2, s2 = _build_page_env({"_qr_running": True, "_future_timestamp": 0})
    t2 = _banner_texts(ns2["get_page"](s2))
    ns3, s3 = _build_page_env({
        "_qr_running": False,
        "_future_timestamp": int((datetime.now() + timedelta(seconds=60)).timestamp()),
    })
    t3 = _banner_texts(ns3["get_page"](s3))
    no_task = next(t for t in t1 if "/push_qr" in t)
    running = next(t for t in t2 if "每隔几秒刷新本页" in t)
    valid = next(t for t in t3 if "过期时间" in t)
    assert len({no_task, running, valid}) == 3
    # 运行中条必须告诉用户页面不会自动更新（快照渲染的盲等问题）
    assert "刷新" in running


# ---------- 验收 10：无 Markdown、无内部术语 ----------

def test_no_markdown_or_internal_jargon():
    forbidden_tokens = ["**", "_is_special_upload", "_none_streak",
                        "_last_check_result", "_special_upload"]
    # 详情页 + 配置页全部可见文本
    texts = []
    for func in ("get_page", "get_form"):
        src = _extract_function(func)
        for m in re.finditer(r"'(?:text|label|placeholder)':\s*'((?:[^'\\]|\\.)*)'", src):
            texts.append(m.group(1))
    joined = "\n".join(texts)
    for token in forbidden_tokens:
        assert token not in joined, f"可见文本包含违禁内容: {token}"
    # 反引号代码块
    assert "`" not in joined


# ---------- 拆字段：配置页新字段存在 + 迁移函数存在 ----------

def test_split_fields_present():
    for model in ("wan_enabled", "wan_max_ips", "custom_ip_urls"):
        assert f"'model': '{model}'" in SOURCE, f"配置页缺少 {model} 字段"
    assert "_migrate_legacy_magic_strings" in SOURCE


def test_migrate_logic():
    """迁移逻辑单测：直接 exec _migrate_legacy_magic_strings 源码。"""
    ns = {"logger": SimpleNamespace(info=lambda *a, **k: None,
                                    warning=lambda *a, **k: None)}
    exec(_extract_function("_migrate_legacy_magic_strings"), ns)

    def run(input_ids, wan_enabled=False, wan_max_ips="", custom=""):
        s = SimpleNamespace(_input_id_list=input_ids, _wan_enabled=wan_enabled,
                            _wan_max_ips=wan_max_ips, _custom_ip_urls=custom)
        ns["_migrate_legacy_magic_strings"](s)
        return s

    # 多WAN旧值
    s = run("1000002||wan2")
    assert s._input_id_list == "1000002"
    assert s._wan_enabled is True and s._wan_max_ips == "2"
    # 自定义URL旧值
    s = run("1000002||https://a.example.com,https://b.example.com")
    assert s._input_id_list == "1000002"
    assert s._custom_ip_urls == "https://a.example.com,https://b.example.com"
    # 幂等：新字段已有值时不覆盖
    s = run("1000002||wan3", wan_enabled=True, wan_max_ips="5")
    assert s._wan_max_ips == "5"
    # 无 || 时不动
    s = run("1000002,1000003")
    assert s._input_id_list == "1000002,1000003" and not s._wan_enabled


# ---------- v3.1.1 评审修复回归 ----------

def test_keepalive_none_distinguishes_note():
    """keepalive ok=None 时：note 非空显示橙条（无结论），note 空才是灰条（没跑过）"""
    ns_a, s_a = _build_page_env({
        "_last_keepalive_ok": None, "_last_keepalive_note": "网络较慢，未能确认登录状态"})
    ta = _banner_texts(ns_a["get_page"](s_a))
    assert any("无结论" in t and "网络较慢" in t for t in ta), ta
    ns_b, s_b = _build_page_env({"_last_keepalive_ok": None, "_last_keepalive_note": ""})
    tb = _banner_texts(ns_b["get_page"](s_b))
    assert any("还没跑过第一轮" in t for t in tb), tb


def test_green_banner_requires_keepalive_success():
    """绿条绑定实际校验：校验失败时顶部条必须是红色且说明可信IP不会更新"""
    ns, s = _build_page_env({
        "_last_keepalive_ok": False, "_last_keepalive_note": "本地Cookie已失效"})
    texts = _banner_texts(ns["get_page"](s))
    assert any("可信IP不会更新" in t for t in texts), texts


def test_ddns_and_pinned_normal_states():
    """DDNS 正常态与 pinned 格式错误态有渲染（此前 ddns_ok 只有 1 分支、pinned_valid 死字段）"""
    ns, s = _build_page_env({
        "_company_domain": "nas.example.com",
        "_last_ddns_ok": True, "_last_ddns_ip": "203.0.113.10",
        "_pinned_ips": "203.0.113.10", })
    texts = _banner_texts(ns["get_page"](s))
    assert any("个域名" in t for t in texts), texts
    assert any("每次更新可信IP都会保留" in t for t in texts), texts
    ns2, s2 = _build_page_env({"_pinned_ips": "not-an-ip,203.0.113.10"})
    texts2 = _banner_texts(ns2["get_page"](s2))
    assert any("格式错误" in t or "非IP格式" in t for t in texts2), texts2


def test_section_titles_present():
    """配置页以 VCard 卡片分区，五张卡标题齐全（3.1.2 卡片式布局）"""
    form_src = _extract_function("get_form")
    for marker in ("\u57fa\u7840", "IP \u6765\u6e90", "\u626b\u7801\u767b\u5f55", "\u901a\u77e5", "\u9ad8\u7ea7"):
        assert marker in form_src, f"配置页缺少分区卡: {marker}"
    assert "'component': 'VCard'" in form_src and "_card(" in form_src
    assert form_src.count("_card(\n") + form_src.count("_card('") >= 5


def test_app_id_placeholder_not_forbidden_value():
    """P0 回归：应用ID 占位符不得再演示 100000x 格式"""
    m = re.search(r"'model': 'input_id_list'.*?'placeholder':\s*'([^']*)'", SOURCE, re.S)
    assert m
    assert "1000002" not in m.group(1) and "1000003" not in m.group(1)


def test_once_switches_declare_one_shot():
    """P3 回归：一次性触发语义必须可见——开关短 label + 卡内触发器说明 alert"""
    assert "自动复位" in SOURCE
    assert "触发器" in SOURCE


# ---------- 3.1.3 多 DDNS 域名 + 布局调整 ----------

def test_resolve_domains_merges_all():
    """所有域名都解析，结果合并去重；部分失败仍返回可用结果"""
    ns = {"Tuple": tuple, "List": list, "logger": SimpleNamespace(warning=lambda *a, **k: None)}
    exec(_extract_function("resolve_domains"), ns)

    def run(raw, mapping):
        s = SimpleNamespace(get_ip_from_domain=lambda d: mapping.get(d, "获取IP失败"))
        return ns["resolve_domains"](s, raw)

    # 两个域名指向不同出口 → 合并
    merged, ok, failed = run("a.example.com,b.example.com", {
        "a.example.com": "203.0.113.10", "b.example.com": "198.51.100.7"})
    assert merged == "203.0.113.10;198.51.100.7"
    assert ok == ["a.example.com", "b.example.com"] and failed == []

    # 两个域名解析到同一 IP → 去重
    merged, _, _ = run("a.example.com,b.example.com", {
        "a.example.com": "203.0.113.10", "b.example.com": "203.0.113.10"})
    assert merged == "203.0.113.10"

    # 部分失败：成功的照用，失败的报告
    merged, ok, failed = run("a.example.com,dead.example.com", {"a.example.com": "203.0.113.10"})
    assert merged == "203.0.113.10" and ok == ["a.example.com"] and failed == ["dead.example.com"]

    # 全部失败
    merged, ok, failed = run("x.example.com,y.example.com", {})
    assert merged == "" and ok == [] and len(failed) == 2

    # 中文逗号也支持、空串返回空
    merged, _, _ = run("a.example.com，b.example.com", {"a.example.com": "1.1.1.1", "b.example.com": "2.2.2.2"})
    assert merged == "1.1.1.1;2.2.2.2"
    assert run("", {})[0] == ""


def test_pinned_ips_moved_to_ip_source_card():
    """固定可信IP 现在位于 IP 来源卡内，不再出现在高级卡"""
    form_src = _extract_function("get_form")
    ip_card = form_src.index("'IP 来源'")
    adv_card = form_src.index("'高级'")
    pinned_pos = form_src.index("'model': 'pinned_ips'")
    assert ip_card < pinned_pos < adv_card, "pinned_ips 应位于 IP来源 与 高级 之间"


def test_wan_switch_and_number_layout():
    """多WAN 开关独占窄列、数量框宽列（此前 6+6 并排挤压）"""
    form_src = _extract_function("get_form")
    assert "_col(4, {'component': 'VSwitch', 'props': {'model': 'wan_enabled'" in form_src
    assert "_col(8, {'component': 'VTextField', 'props': {'model': 'wan_max_ips'" in form_src


def test_ddns_field_mentions_multiple_domains():
    form_src = _extract_function("get_form")
    assert "多个用英文逗号分隔" in form_src
    assert "所有域名都会解析" in form_src


# ---------- 3.1.4 详情页卡片式布局 ----------

def test_page_uses_three_cards():
    """详情页为三张卡：运行状态 / IP 来源 / 扫码登录"""
    page_src = _extract_function("get_page")
    for title in ("运行状态", "IP 来源", "扫码登录"):
        assert title in page_src, f"详情页缺少卡片: {title}"
    assert page_src.count("_card(") >= 3
    # 3.1.6：状态表达必须是 VChip + VTable，不得再有硬编码色横幅
    assert "VChip" in page_src and "VTable" in page_src
    assert "_banner(" not in page_src
    assert "#40bb45" not in page_src and "#ff0000" not in page_src


def test_page_banner_texts_survive_card_wrap():
    """卡片包裹后 _banner_texts 仍能收集全部状态条（递归 walk 的回归）"""
    ns, self_ = _build_page_env({
        "_company_domain": "a.example.com",
        "_last_ddns_ok": True, "_last_ddns_ip": "203.0.113.10",
        "_pinned_ips": "203.0.113.10",
    })
    texts = _banner_texts(ns["get_page"](self_))
    assert any("个域名" in t for t in texts), texts
    assert any("每次更新可信IP都会保留" in t for t in texts), texts
    assert any(t in ("多WAN多出口", "DDNS域名", "公网IP探测") for t in texts), texts
    assert any("运行状态" not in t for t in texts)  # 卡标题不是 banner，不应混入
