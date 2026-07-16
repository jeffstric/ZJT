"""剧本拆分场景层级的确定性硬校验。

该模块不依赖 QC，也不执行数据库写入。段级只判断新顶层场景；完整校验在
合并和发布前使用全量 locations 与最新数据库场景树检查父级、冲突和环。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class LocationMatchResult:
    db_location: Optional[Dict[str, Any]]
    conflict: Optional[Dict[str, Any]] = None


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _normalize_name(value: Any) -> str:
    return "".join(str(value or "").strip().lower().split())


def _location_id(location: Dict[str, Any]) -> str:
    return str(location.get("id") or location.get("location_id") or "")


def _location_name(location: Dict[str, Any]) -> str:
    return str(location.get("name") or location.get("location_name") or "")


def flatten_db_locations(locations: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flattened: List[Dict[str, Any]] = []

    def visit(items: Iterable[Dict[str, Any]], inherited_parent: Optional[int] = None) -> None:
        for raw in items or []:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            if item.get("parent_id") in (None, "") and inherited_parent is not None:
                item["parent_id"] = inherited_parent
            children = item.pop("children", None) or []
            flattened.append(item)
            visit(children, _safe_int(item.get("id")))

    visit(locations or [])
    return flattened


def _db_indexes(db_locations: Iterable[Dict[str, Any]]) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    by_id: Dict[int, Dict[str, Any]] = {}
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for location in flatten_db_locations(db_locations):
        db_id = _safe_int(location.get("id"))
        if db_id is not None:
            by_id[db_id] = location
        normalized = _normalize_name(location.get("name"))
        if normalized:
            by_name.setdefault(normalized, []).append(location)
    return by_id, by_name


def _unique_name_match(name: Any, by_name: Dict[str, List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    normalized = _normalize_name(name)
    if not normalized:
        return None
    exact = by_name.get(normalized) or []
    if len(exact) == 1:
        return exact[0]
    fuzzy: List[Dict[str, Any]] = []
    for db_name, matches in by_name.items():
        if db_name.endswith(normalized) or normalized.endswith(db_name):
            fuzzy.extend(matches)
    return fuzzy[0] if len(fuzzy) == 1 else None


def _candidate_db_match(
    location: Dict[str, Any],
    by_id: Dict[int, Dict[str, Any]],
    by_name: Dict[str, List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    given_id = _safe_int(location.get("location_db_id"))
    if given_id is not None:
        return by_id.get(given_id)
    return _unique_name_match(_location_name(location), by_name)


def _resolve_planned_parent_db_id(
    location: Dict[str, Any],
    locations_by_key: Dict[str, Dict[str, Any]],
    by_id: Dict[int, Dict[str, Any]],
    by_name: Dict[str, List[Dict[str, Any]]],
) -> Optional[int]:
    parent_key = str(location.get("parent_id") or "")
    if not parent_key:
        return None
    parent = locations_by_key.get(parent_key)
    if not parent:
        return None
    parent_match = _candidate_db_match(parent, by_id, by_name)
    return _safe_int(parent_match.get("id")) if parent_match else None


def match_location_with_parent(
    location: Dict[str, Any],
    locations_by_key: Dict[str, Dict[str, Any]],
    db_locations: Iterable[Dict[str, Any]],
) -> LocationMatchResult:
    """匹配已有场景，并在 LLM 显式声明父级时检查数据库层级。"""
    by_id, by_name = _db_indexes(db_locations)
    db_match = _candidate_db_match(location, by_id, by_name)
    if not db_match:
        return LocationMatchResult(None)

    parent_key = str(location.get("parent_id") or "")
    if not parent_key:
        # 对已有 DB 场景，null 表示未声明层级；数据库层级为权威值。
        return LocationMatchResult(db_match)

    planned_parent_db_id = _resolve_planned_parent_db_id(
        location, locations_by_key, by_id, by_name,
    )
    actual_parent_db_id = _safe_int(db_match.get("parent_id"))
    if planned_parent_db_id != actual_parent_db_id:
        return LocationMatchResult(
            db_match,
            {
                "code": "location_parent_conflict",
                "severity": "error",
                "message": (
                    f"场景 {_location_name(location) or _location_id(location)} 的规划父级与数据库父级不一致"
                ),
                "location_id": _location_id(location),
                "location_db_id": _safe_int(db_match.get("id")),
                "expected_parent_db_id": actual_parent_db_id,
                "actual_parent_db_id": planned_parent_db_id,
                "parent_id": parent_key,
                "_hard_gate": True,
            },
        )
    return LocationMatchResult(db_match)


def validate_segment_new_roots(
    parsed_data: Dict[str, Any],
    db_locations: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """段级硬校验：仅拒绝本段无法复用 DB 的新顶层场景。"""
    by_id, by_name = _db_indexes(db_locations)
    errors: List[Dict[str, Any]] = []
    for location in parsed_data.get("locations") or []:
        if not isinstance(location, dict) or location.get("parent_id") not in (None, ""):
            continue
        if _candidate_db_match(location, by_id, by_name):
            continue
        errors.append({
            "code": "new_root_location_forbidden",
            "severity": "error",
            "message": (
                f"拆分流程不允许创建顶层场景：{_location_name(location) or _location_id(location)}；"
                "请复用已有场景，或在剧本创作页先创建顶层场景"
            ),
            "location_id": _location_id(location),
            "location_name": _location_name(location),
            "_hard_gate": True,
        })
    return errors


def validate_full_location_structure(
    parsed_data: Dict[str, Any],
    db_locations: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """合并/发布硬校验：检查完整父级图、显式 DB 冲突、可达性与环。"""
    locations = [item for item in (parsed_data.get("locations") or []) if isinstance(item, dict)]
    locations_by_key = {
        _location_id(item): item for item in locations if _location_id(item)
    }
    db_flat = flatten_db_locations(db_locations)
    by_id, by_name = _db_indexes(db_flat)
    matches: Dict[str, Optional[Dict[str, Any]]] = {}
    errors: List[Dict[str, Any]] = []

    for location in locations:
        key = _location_id(location)
        result = match_location_with_parent(location, locations_by_key, db_flat)
        matches[key] = result.db_location
        if result.conflict:
            errors.append(result.conflict)

    # 已有 DB 场景的显式父级冲突已完成；下面检查所有新场景的父链。
    reported: set[str] = set()
    reported_cycles: set[frozenset[str]] = set()
    for location in locations:
        key = _location_id(location)
        if matches.get(key):
            continue
        parent_key = str(location.get("parent_id") or "")
        if not parent_key:
            if key not in reported:
                reported.add(key)
                errors.extend(validate_segment_new_roots({"locations": [location]}, db_flat))
            continue

        chain: List[str] = []
        current_key = key
        while True:
            if current_key in chain:
                cycle = chain[chain.index(current_key):] + [current_key]
                cycle_nodes = frozenset(cycle)
                if cycle_nodes not in reported_cycles:
                    reported_cycles.add(cycle_nodes)
                    errors.append({
                        "code": "location_parent_invalid",
                        "severity": "error",
                        "reason": "cycle",
                        "message": f"场景父级形成环：{' -> '.join(cycle)}",
                        "location_id": key,
                        "involved_location_ids": cycle,
                        "_hard_gate": True,
                    })
                break
            chain.append(current_key)
            current = locations_by_key.get(current_key)
            if not current:
                marker = f"missing:{key}:{current_key}"
                if marker not in reported:
                    reported.add(marker)
                    errors.append({
                        "code": "location_parent_invalid",
                        "severity": "error",
                        "reason": "missing_parent",
                        "message": f"场景 {key} 的父级 {current_key} 不存在",
                        "location_id": key,
                        "parent_id": current_key,
                        "_hard_gate": True,
                    })
                break
            if matches.get(current_key):
                break
            next_parent = str(current.get("parent_id") or "")
            if not next_parent:
                marker = f"unreachable:{key}:{current_key}"
                if marker not in reported:
                    reported.add(marker)
                    errors.append({
                        "code": "location_parent_invalid",
                        "severity": "error",
                        "reason": "unreachable_root",
                        "message": f"场景 {key} 的父级链无法到达已有数据库场景",
                        "location_id": key,
                        "parent_id": current_key,
                        "_hard_gate": True,
                    })
                break
            current_key = next_parent

    return errors


__all__ = [
    "LocationMatchResult",
    "flatten_db_locations",
    "match_location_with_parent",
    "validate_full_location_structure",
    "validate_segment_new_roots",
]
