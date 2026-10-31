"""失效实现方偏好批量清理服务。

供应商被管理端禁用（implementation_power_config.enabled=0）或其必需配置被
清空后，指向该实现方的用户偏好/固定标记（users.implementation_preferences）
若残留，会导致固定模式任务持续失败（FIXED_IMPLEMENTATION_UNAVAILABLE），且
设置界面按可用列表渲染、看不到该供应商，用户无法自行取消固定。

本模块由管理端「实现方启停」「配置更新」入口主动触发全量用户清理；
用户侧打开设置页另有单用户自愈兜底（GET implementation-preferences）。
只暴露同步入口；异步 Web 路由必须在线程中调用。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Dict, Set

from config.unified_config import UnifiedConfigRegistry
from model.database import execute_query, execute_update

logger = logging.getLogger(__name__)


def find_affected_implementations(updated_config_keys: Iterable[str]) -> list:
    """根据被更新的配置键，找出依赖它们的实现方名列表。

    实现方通过 required_config_keys（如 ['topenrouter.api_key']）声明必需配置；
    更新键与必需键有交集的实现方，其可用性可能因本次更新发生变化（典型：api_key
    被清空导致未配置）。

    Returns:
        实现方名字列表（去重），无命中时为空列表。
    """
    keys = {k for k in updated_config_keys if k}
    if not keys:
        return []
    try:
        implementations = UnifiedConfigRegistry.get_all_implementations()
    except Exception as e:
        logger.error(f"Failed to load implementations for cleanup: {e}")
        return []

    affected = []
    for name, impl in implementations.items():
        required = getattr(impl, "required_config_keys", None) or []
        if keys.intersection(required):
            affected.append(name)
    return affected


def cleanup_preferences_for_implementations(implementation_names: Iterable[str]) -> Dict[str, int]:
    """清除所有用户中指向 implementation_names 的偏好与固定标记。

    实现方名以 JSON 字符串值形态出现在 users.implementation_preferences 中，
    先 LIKE 预筛避免全表拉取，再逐行解析精确判定（preferences 值命中才清，
    同时删除该 task 的 locks 标记）；JSON 无变化的行不写回。

    Returns:
        {"scanned": 预筛行数, "cleared_users": 发生清理并写回的用户数}
    """
    names = {n for n in implementation_names if n}
    if not names:
        return {"scanned": 0, "cleared_users": 0}

    like_clause = " OR ".join(
        "implementation_preferences LIKE %s" for _ in names
    )
    like_params = [f'%"{name}"%' for name in names]
    sql = (
        f"SELECT id, implementation_preferences FROM users "
        f"WHERE implementation_preferences IS NOT NULL AND ({like_clause})"
    )
    rows = execute_query(sql, tuple(like_params)) or []

    cleared_users = 0
    for row in rows:
        try:
            preferences = json.loads(row.get("implementation_preferences") or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(preferences, dict):
            continue
        groups = preferences.get("groups")
        if not isinstance(groups, dict):
            continue

        changed = False
        for group in groups.values():
            if not isinstance(group, dict):
                continue
            prefs = group.get("preferences")
            locks = group.get("locks")
            if not isinstance(prefs, dict):
                continue
            stale_keys = [k for k, v in prefs.items() if v in names]
            for task_key in stale_keys:
                del prefs[task_key]
                changed = True
                if isinstance(locks, dict):
                    locks.pop(task_key, None)

        if not changed:
            continue
        update_sql = "UPDATE users SET implementation_preferences = %s, updated_at = NOW() WHERE id = %s"
        affected = execute_update(
            update_sql,
            (json.dumps(preferences, ensure_ascii=False), row["id"]),
        )
        if affected:
            cleared_users += 1
            logger.info(
                f"Cleared stale implementation preferences for user {row['id']}: "
                f"implementations={sorted(names)}"
            )
    return {"scanned": len(rows), "cleared_users": cleared_users}
