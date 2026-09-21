"""
忽略规则的匹配与增删（纯逻辑，不含持久化）。

Ignore-rule matching and list mutation. Pure logic only — **no I/O**.
持久化由调用方（插件实例）负责，本模块不接触配置或磁盘。

为什么不做成类：忽略规则的全部状态就是一个 `List[Dict]`，它属于插件实例并
经由 `save_data("ignored_files", ...)` 落盘。在这里再包一层持有列表的对象，
只会制造「谁才是真相来源」的第二个答案。因此本模块保持为纯函数，
调用方传列表进来、拿结果出去。
Deliberately stateless: all ignore-rule state lives on the plugin instance. Wrapping
it in an object here would create a second source of truth.
"""

from datetime import datetime
from typing import Any, Dict, List

MATCH_EXACT = "exact"
MATCH_CONTAINS = "contains"


def is_ignored(key: str, rules: List[Dict[str, Any]]) -> bool:
    """
    检查某个文件 key 是否命中了忽略规则（大小写不敏感）。

    Whether a file key matches any ignore rule (case-insensitive).
    规则为空或 key 为空时一律返回 False（「不忽略」是安全默认值：
    误报多一点可接受，误忽略会让文件永远不再被同步）。
    """
    if not key or not rules:
        return False
    k_lower = key.lower()
    for r in rules:
        rule_str = (r.get("rule") or "").lower().strip()
        if not rule_str:
            continue
        if r.get("match", MATCH_CONTAINS) == MATCH_EXACT:
            if k_lower == rule_str:
                return True
        else:
            if rule_str in k_lower:
                return True
    return False


def add_rule(rules: List[Dict[str, Any]], rule: str, match: str = MATCH_CONTAINS,
             created_by: str = "", source: str = "chat") -> bool:
    """
    就地追加一条忽略规则；已存在（规则文本 + 匹配方式都相同）时返回 False。

    Append an ignore rule in place. Returns False when it already exists.

    去重同时比较「文本」与「匹配方式」：`剧名` 的 exact 与 contains 是两条
    不同规则，前者只忽略那一个文件，后者忽略整部剧的所有文件。
    Dedupe compares both text and match mode — they mean different things.
    """
    rule = (rule or "").strip()
    if not rule:
        return False
    for item in rules:
        if (item.get("rule") or "").lower() == rule.lower() and \
                item.get("match", MATCH_CONTAINS) == match:
            return False
    rules.append({
        "rule": rule,
        "match": match,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "created_by": created_by,
        "source": source,
    })
    return True


def remove_rule(rules: List[Dict[str, Any]], index_or_rule: Any) -> bool:
    """
    按序号（int，从 0 起）或规则文本（str，大小写不敏感）移除；未命中返回 False。

    Remove by index (int, zero-based) or by rule text (str, case-insensitive).
    """
    removed = False
    if isinstance(index_or_rule, int) and 0 <= index_or_rule < len(rules):
        rules.pop(index_or_rule)
        removed = True
    elif isinstance(index_or_rule, str):
        target = index_or_rule.strip().lower()
        before = len(rules)
        rules[:] = [r for r in rules if (r.get("rule") or "").lower() != target]
        removed = len(rules) < before
    return removed


def filter_ignored(keys: List[str], rules: List[Dict[str, Any]]) -> List[str]:
    """批量剔除命中忽略规则的 key（异常清单落盘前的统一收口）。"""
    return [k for k in keys if not is_ignored(k, rules)]
