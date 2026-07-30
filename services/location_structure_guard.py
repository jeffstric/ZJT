"""剧本拆分场景层级的确定性硬校验。

该模块不依赖 QC，也不执行数据库写入。

校验层次：
- L0 规划编译：bind + validate 规划 locations / space_units 对照 DB
- L1 段级：locations + 本段 space_unit/镜头引用拉起的 registry 地点新顶层
- L2/L3 合并与发布：全量父级图、可达性与环（父级冲突自动按 DB 对齐，不阻断）
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


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


def _location_key(location: Dict[str, Any]) -> str:
    return str(
        location.get("location_key")
        or location.get("entity_key")
        or ""
    ).strip()


def _new_root_error(location: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "code": "new_root_location_forbidden",
        "severity": "error",
        "message": (
            f"拆分流程不允许创建顶层场景：{_location_name(location) or _location_id(location)}；"
            "请复用已有场景，或在剧本创作页先创建顶层场景"
        ),
        "location_id": _location_id(location),
        "location_name": _location_name(location),
        "_hard_gate": True,
    }


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


def _candidate_db_match_with_kind(
    location: Dict[str, Any],
    by_id: Dict[int, Dict[str, Any]],
    by_name: Dict[str, List[Dict[str, Any]]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """返回 (DB 匹配行, 匹配方式)。匹配方式：id / exact（规范化同名）/ fuzzy（后缀模糊）。"""
    given_id = _safe_int(location.get("location_db_id"))
    if given_id is not None:
        return by_id.get(given_id), "id"
    normalized = _normalize_name(_location_name(location))
    if not normalized:
        return None, None
    exact = by_name.get(normalized) or []
    if len(exact) == 1:
        return exact[0], "exact"
    fuzzy: List[Dict[str, Any]] = []
    for db_name, matches in by_name.items():
        if db_name.endswith(normalized) or normalized.endswith(db_name):
            fuzzy.extend(matches)
    if len(fuzzy) == 1:
        return fuzzy[0], "fuzzy"
    return None, None


def _candidate_db_match(
    location: Dict[str, Any],
    by_id: Dict[int, Dict[str, Any]],
    by_name: Dict[str, List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    match, _kind = _candidate_db_match_with_kind(location, by_id, by_name)
    return match


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
    """匹配已有场景，并在 LLM 显式声明父级时检查数据库层级。

    父级不一致时返回 conflict 诊断（severity=warning），并带 match_kind
    （id/exact/fuzzy）：调用方只对 id/exact 做按库对齐；fuzzy 匹配且父级
    不同视为不同物理场景，不应绑定或对齐。
    """
    by_id, by_name = _db_indexes(db_locations)
    db_match, match_kind = _candidate_db_match_with_kind(location, by_id, by_name)
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
        # 父级不一致不再是硬门禁：仅作诊断警告返回，由调用方按 match_kind 决定
        # 按数据库层级对齐（id/exact）或拒绝绑定（fuzzy）。
        return LocationMatchResult(
            db_match,
            {
                "code": "location_parent_conflict",
                "severity": "warning",
                "message": (
                    f"场景 {_location_name(location) or _location_id(location)} 的规划父级与数据库父级不一致"
                ),
                "location_id": _location_id(location),
                "location_db_id": _safe_int(db_match.get("id")),
                "match_kind": match_kind,
                "expected_parent_db_id": actual_parent_db_id,
                "actual_parent_db_id": planned_parent_db_id,
                "parent_id": parent_key,
            },
        )
    return LocationMatchResult(db_match)


def _align_location_parent_to_db_row(
    location: Dict[str, Any],
    db_row: Dict[str, Any],
    db_id_to_internal: Dict[int, str],
) -> None:
    """已绑定 DB 的场景：parent_id 以数据库层级为准，忽略 LLM 乱写的父级。"""
    actual_parent_db_id = _safe_int(db_row.get("parent_id"))
    if actual_parent_db_id is None:
        location["parent_id"] = None
        if location.get("level") is not None:
            location["level"] = 0
        return
    parent_internal = db_id_to_internal.get(actual_parent_db_id)
    # 父场景不在当前 locations 中时清空 parent；数据库侧父子关系仍以
    # location_db_id 对应行的 parent_id 为准。
    location["parent_id"] = parent_internal if parent_internal else None


def validate_segment_new_roots(
    parsed_data: Dict[str, Any],
    db_locations: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """段级校验：新顶层场景放行（不再硬拒绝）。

    历史上本函数把"DB 无法复用的新顶层场景"作为硬门禁拒绝，导致剧本出现 DB 没有
    的场景（双世界设定、新地点、命名差异、空 world）时必然死锁——LLM 既无法复用
    又无法新建顶层，任务一律 paused（如 world 252/258 空世界、world 244 穿越前现代
    卧室、world 261 校园路上、world 246 现代客厅）。

    现放行：剧本需要的新地点允许登记为顶层，由 publish 阶段
    StoryboardLocationBootstrapService 自动落库到 world 场景库，下次复用。
    提示词层引导 LLM 优先把新场景挂到已有顶层作子场景，只有找不到合适父场景
    才作顶层新建，以控制新顶层数量。

    仍由其他函数保留的校验：location_parent_invalid（父链环 / missing /
    unreachable，见 validate_full_location_structure）。已有 DB 场景的父级冲突
    （历史 location_parent_conflict）自 2026-07-30 起降级为按数据库层级自动对齐，
    不再作为硬门禁。
    """
    return []


def validate_full_location_structure(
    parsed_data: Dict[str, Any],
    db_locations: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """合并/发布硬校验：检查完整父级图、可达性与环。

    匹配到 DB 的场景若规划父级与数据库不一致（历史 location_parent_conflict
    硬门禁），不再返回错误阻断拆分：显式 id / 规范化精确同名（exact）匹配
    就地按数据库层级回写 parent_id 并记 warning（降级信数据库，不信 LLM 结果）。
    后缀模糊匹配（fuzzy，如“阳台”撞上“酒店A阳台”）且父级不同的视为不同物理
    场景：不信任该绑定、不做对齐，按未匹配新场景走父链校验。
    与 validate_segment_location_structure_extended 就地写 location_db_id 一样，
    本函数会就地修复 parsed_data 中的 locations。
    返回的 errors 只含 location_parent_invalid（环/父级缺失/不可达根）等硬门禁。
    """
    locations = [item for item in (parsed_data.get("locations") or []) if isinstance(item, dict)]
    locations_by_key = {
        _location_id(item): item for item in locations if _location_id(item)
    }
    db_flat = flatten_db_locations(db_locations)
    matches: Dict[str, Optional[Dict[str, Any]]] = {}
    errors: List[Dict[str, Any]] = []
    conflicts: List[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]] = []

    for location in locations:
        key = _location_id(location)
        result = match_location_with_parent(location, locations_by_key, db_flat)
        if result.conflict and result.conflict.get("match_kind") == "fuzzy":
            # 模糊匹配且父级不同：视为不同场景，拒绝该 DB 绑定，
            # 按未匹配新场景参与后续父链校验，不做父级对齐。
            matches[key] = None
            continue
        matches[key] = result.db_location
        if result.conflict and result.db_location:
            conflicts.append((location, result.db_location, result.conflict))

    if conflicts:
        db_id_to_internal: Dict[int, str] = {}
        for internal_key, db_row in matches.items():
            db_id = _safe_int((db_row or {}).get("id"))
            if internal_key and db_id is not None:
                db_id_to_internal[db_id] = internal_key
        for location, db_row, conflict in conflicts:
            _align_location_parent_to_db_row(location, db_row, db_id_to_internal)
            logger.warning(
                "场景 %s 的规划父级与数据库父级不一致，已按数据库层级自动对齐: %s",
                _location_name(location) or _location_id(location),
                conflict,
            )

    # 已有 DB 场景的父级已按数据库对齐；下面检查所有新场景的父链。
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


def _registry_locations(plan: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(plan, dict):
        return []
    registry = plan.get("compiled_registry") or {}
    if isinstance(registry, dict):
        items = registry.get("locations") or []
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    entities = plan.get("entities") or {}
    if isinstance(entities, dict):
        items = entities.get("locations") or []
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _index_locations(locations: Sequence[Dict[str, Any]]) -> Tuple[
    Dict[str, Dict[str, Any]],
    Dict[str, Dict[str, Any]],
    Dict[str, Dict[str, Any]],
]:
    by_id: Dict[str, Dict[str, Any]] = {}
    by_key: Dict[str, Dict[str, Any]] = {}
    by_name: Dict[str, Dict[str, Any]] = {}
    for location in locations:
        loc_id = _location_id(location)
        if loc_id:
            by_id[loc_id] = location
        key = _location_key(location)
        if key:
            by_key[key] = location
        name = _normalize_name(_location_name(location))
        if name and name not in by_name:
            by_name[name] = location
    return by_id, by_key, by_name


def bind_planned_locations(
    planned_locations: Sequence[Dict[str, Any]],
    db_locations: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """绑定规划 locations：写 location_db_id，解析 parent_location_key → parent_id。"""
    by_id, by_name = _db_indexes(db_locations)
    bound: List[Dict[str, Any]] = []
    key_to_internal: Dict[str, str] = {}
    match_kinds: Dict[int, str] = {}  # id(location) → id/exact/fuzzy（绑定时的匹配方式）

    for raw in planned_locations or []:
        if not isinstance(raw, dict):
            continue
        location = deepcopy(raw)
        # 模型禁止编造 DB id：不在库中的显式 id 清空后走名称匹配
        given_db_id = _safe_int(location.get("location_db_id"))
        if given_db_id is not None and given_db_id not in by_id:
            location["location_db_id"] = None

        db_match, match_kind = _candidate_db_match_with_kind(location, by_id, by_name)
        if db_match:
            location["location_db_id"] = _safe_int(db_match.get("id"))
            match_kinds[id(location)] = match_kind
        else:
            location["location_db_id"] = None

        key = _location_key(location)
        internal_id = _location_id(location)
        if key and internal_id:
            key_to_internal[key] = internal_id
        bound.append(location)

    # 第二遍：parent_location_key → parent_id（内部 loc_xxx）
    for location in bound:
        parent_key = str(
            location.get("parent_location_key")
            or location.get("parent_entity_key")
            or ""
        ).strip()
        if parent_key:
            parent_internal = key_to_internal.get(parent_key)
            if parent_internal:
                location["parent_id"] = parent_internal
            elif location.get("parent_id") in (None, ""):
                # 保留无法解析的 key 到 parent_id 占位，交给 full 校验报 missing
                location["parent_id"] = parent_key
        # 已绑定 DB 且未声明规划父：parent 以 DB 为准，不在此写内部 parent
        # 未匹配 DB 且无任何父：保持 parent_id 空，由校验打新顶层
        if location.get("location_db_id") is not None and not parent_key:
            # 显式 parent_id 若存在，留给 full 校验做 conflict；不在此清空
            pass

    # 第三遍：后缀模糊匹配（fuzzy，如“阳台”撞上“酒店A阳台”）且规划父级与
    # DB 父级不同 → 视为不同物理场景，解除绑定保留为新场景，避免把镜头
    # 引用到错误资产；精确同名 / 显式 id 的父级冲突由 full 校验按 DB 对齐。
    # 注意匹配方式必须取第一遍记录的值：绑定后 location_db_id 已写入，
    # 重新匹配只会得到 "id"，无法还原 fuzzy。
    bound_by_id = {
        _location_id(location): location
        for location in bound
        if _location_id(location)
    }
    for location in bound:
        if match_kinds.get(id(location)) != "fuzzy":
            continue
        result = match_location_with_parent(location, bound_by_id, db_locations)
        if result.conflict:
            location["location_db_id"] = None

    return bound


def validate_planned_location_structure(
    planned_locations: Sequence[Dict[str, Any]],
    db_locations: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """规划 locations 硬校验（与 full 同构）。"""
    bound = bind_planned_locations(planned_locations, db_locations)
    return validate_full_location_structure({"locations": bound}, db_locations)


def validate_planned_space_units(
    spatial_world: Optional[Dict[str, Any]],
    planned_locations: Sequence[Dict[str, Any]],
    db_locations: Iterable[Dict[str, Any]] = (),
) -> List[Dict[str, Any]]:
    """规划 space_unit 必须能关联到合法 plan location。"""
    del db_locations  # 关联合法性以 locations 绑定结果为准；DB 在 locations 层已校验
    locations = [item for item in planned_locations if isinstance(item, dict)]
    by_id, by_key, by_name = _index_locations(locations)
    errors: List[Dict[str, Any]] = []
    space_units = (spatial_world or {}).get("space_units") or []
    for unit in space_units:
        if not isinstance(unit, dict):
            continue
        unit_id = str(unit.get("space_unit_id") or unit.get("id") or "")
        explicit_key = str(
            unit.get("location_key")
            or unit.get("owner_location_key")
            or unit.get("entity_key")
            or ""
        ).strip()
        owner_id = str(unit.get("owner_id") or "").strip()
        name = _location_name(unit)

        matched: Optional[Dict[str, Any]] = None
        if explicit_key and explicit_key in by_key:
            matched = by_key[explicit_key]
        elif owner_id and owner_id in by_id:
            matched = by_id[owner_id]
        elif name:
            matched = by_name.get(_normalize_name(name))

        if matched is None:
            errors.append({
                "code": "planned_space_unit_location_unbound",
                "severity": "error",
                "message": (
                    f"规划 space_unit {unit_id or name or '?'} 无法关联到 entities.locations；"
                    "请为 space_unit 使用与地点一致的名称，或填写 location_key"
                ),
                "space_unit_id": unit_id,
                "location_name": name,
                "_hard_gate": True,
            })
    return errors


def bind_and_validate_planned_locations(
    planned_locations: Sequence[Dict[str, Any]],
    db_locations: Iterable[Dict[str, Any]],
    spatial_world: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """L0：绑定规划地点并返回 (bound_locations, errors)。"""
    bound = bind_planned_locations(planned_locations, db_locations)
    errors = validate_full_location_structure({"locations": bound}, db_locations)
    if spatial_world is not None:
        errors.extend(
            validate_planned_space_units(spatial_world, bound, db_locations)
        )
    return bound, errors


def _pull_registry_location(
    loc_id: str,
    registry_by_id: Dict[str, Dict[str, Any]],
    collected: Dict[str, Dict[str, Any]],
) -> None:
    if not loc_id or loc_id in collected:
        return
    location = registry_by_id.get(loc_id)
    if not location:
        return
    collected[loc_id] = deepcopy(location)
    parent_id = str(location.get("parent_id") or "").strip()
    if parent_id:
        _pull_registry_location(parent_id, registry_by_id, collected)


def collect_segment_location_graph(
    parsed: Dict[str, Any],
    plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建本段可见地点图：locations + space_unit/镜头引用 + registry 祖先链。"""
    collected: Dict[str, Dict[str, Any]] = {}
    name_only: List[Dict[str, Any]] = []

    for location in parsed.get("locations") or []:
        if not isinstance(location, dict):
            continue
        loc_id = _location_id(location)
        if loc_id:
            collected[loc_id] = deepcopy(location)
        else:
            name_only.append(deepcopy(location))

    registry = _registry_locations(plan)
    registry_by_id, registry_by_key, registry_by_name = _index_locations(registry)

    def _ensure_ref(loc_id: str, fallback_name: str = "") -> None:
        if not loc_id:
            return
        if loc_id in collected:
            return
        if loc_id in registry_by_id:
            _pull_registry_location(loc_id, registry_by_id, collected)
            return
        # 悬挂 id：合成候选，便于打 space_unit_location_missing / 新根
        synthetic = {
            "id": loc_id,
            "name": fallback_name or loc_id,
            "location_db_id": None,
            "parent_id": None,
            "_synthetic_from_space_unit": True,
        }
        collected[loc_id] = synthetic

    for unit in (parsed.get("spatial_world") or {}).get("space_units") or []:
        if not isinstance(unit, dict):
            continue
        owner_id = str(unit.get("owner_id") or "").strip()
        unit_name = _location_name(unit)
        if owner_id:
            _ensure_ref(owner_id, unit_name)
        for raw_id in unit.get("location_ids") or []:
            ref_id = str(raw_id or "").strip()
            if ref_id:
                _ensure_ref(ref_id, unit_name)
        explicit_key = str(
            unit.get("location_key")
            or unit.get("owner_location_key")
            or ""
        ).strip()
        if explicit_key and explicit_key in registry_by_key:
            reg = registry_by_key[explicit_key]
            _pull_registry_location(_location_id(reg), registry_by_id, collected)
        elif unit_name and not owner_id:
            norm = _normalize_name(unit_name)
            if norm in registry_by_name:
                reg = registry_by_name[norm]
                _pull_registry_location(_location_id(reg), registry_by_id, collected)
            else:
                # 仅有 name、无 id：若已在 collected 中同名则跳过，否则合成
                existing_names = {
                    _normalize_name(_location_name(item)) for item in collected.values()
                }
                if norm not in existing_names:
                    name_only.append({
                        "id": "",
                        "name": unit_name,
                        "location_db_id": None,
                        "parent_id": None,
                        "_synthetic_from_space_unit": True,
                    })

    for group in parsed.get("shot_groups") or []:
        if not isinstance(group, dict):
            continue
        for shot in group.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            shot_loc = str(
                shot.get("location_id")
                or shot.get("location")
                or ""
            ).strip()
            # location_id 可能是内部 loc_xxx 或数字 db id 字符串；内部 id 才拉 registry
            if shot_loc.startswith("loc_"):
                _ensure_ref(shot_loc)

    locations = list(collected.values()) + name_only
    return {"locations": locations}


def validate_space_unit_location_refs(
    parsed: Dict[str, Any],
    graph: Dict[str, Any],
    db_locations: Iterable[Dict[str, Any]] = (),
) -> List[Dict[str, Any]]:
    """检查 space_unit 引用是否落到地点图；悬挂合成点若也无法匹配 DB 则报 missing。"""
    del db_locations
    graph_by_id = {
        _location_id(item): item
        for item in graph.get("locations") or []
        if isinstance(item, dict) and _location_id(item)
    }
    errors: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for unit in (parsed.get("spatial_world") or {}).get("space_units") or []:
        if not isinstance(unit, dict):
            continue
        unit_id = str(unit.get("space_unit_id") or "")
        refs = []
        owner_id = str(unit.get("owner_id") or "").strip()
        if owner_id:
            refs.append(owner_id)
        for raw_id in unit.get("location_ids") or []:
            ref_id = str(raw_id or "").strip()
            if ref_id:
                refs.append(ref_id)
        for ref_id in refs:
            loc = graph_by_id.get(ref_id)
            if loc is None:
                marker = f"missing:{unit_id}:{ref_id}"
                if marker in seen:
                    continue
                seen.add(marker)
                errors.append({
                    "code": "space_unit_location_missing",
                    "severity": "error",
                    "message": (
                        f"space_unit {unit_id or '?'} 引用的地点 {ref_id} 不存在于 "
                        "locations 或规划注册表"
                    ),
                    "space_unit_id": unit_id,
                    "location_id": ref_id,
                    "_hard_gate": True,
                })
                continue
            if loc.get("_synthetic_from_space_unit") and not _location_name(loc):
                marker = f"synth:{unit_id}:{ref_id}"
                if marker in seen:
                    continue
                seen.add(marker)
                errors.append({
                    "code": "space_unit_location_missing",
                    "severity": "error",
                    "message": (
                        f"space_unit {unit_id or '?'} 引用的地点 {ref_id} 无法解析"
                    ),
                    "space_unit_id": unit_id,
                    "location_id": ref_id,
                    "_hard_gate": True,
                })
    return errors


def validate_segment_location_structure_extended(
    parsed: Dict[str, Any],
    db_locations: Iterable[Dict[str, Any]],
    *,
    plan: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """L1 扩展：locations + space_unit/引用拉起的 registry 地点新顶层与悬挂引用。"""
    graph = collect_segment_location_graph(parsed, plan)
    # 合成点若名称能匹配 DB，不应打新根；先尝试绑定名称
    by_id, by_name = _db_indexes(db_locations)
    for location in graph.get("locations") or []:
        if not isinstance(location, dict):
            continue
        if location.get("location_db_id") not in (None, ""):
            continue
        match = _candidate_db_match(location, by_id, by_name)
        if match:
            location["location_db_id"] = _safe_int(match.get("id"))

    errors = validate_segment_new_roots(graph, db_locations)
    errors.extend(validate_space_unit_location_refs(parsed, graph, db_locations))
    return errors


__all__ = [
    "LocationMatchResult",
    "bind_and_validate_planned_locations",
    "bind_planned_locations",
    "collect_segment_location_graph",
    "flatten_db_locations",
    "match_location_with_parent",
    "validate_full_location_structure",
    "validate_planned_location_structure",
    "validate_planned_space_units",
    "validate_segment_location_structure_extended",
    "validate_segment_new_roots",
    "validate_space_unit_location_refs",
]
