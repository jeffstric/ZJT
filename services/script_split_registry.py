"""
Script split registry - 全局 ID 注册表与空间引用完整性校验。

见 docs/script/script_parser_incremental_split_design.md §7.4 §7.5。
策略：模型直接复用任务级 ID + 后端逐路径验证，不做深层通用 ID 重写。
本模块纯函数，不依赖 DB / LLM。
"""
from typing import Dict, Any, List, Tuple, Optional, Set
import re


# ---- ID 规范化名称工具 ----

def _normalize_name(name: Optional[str]) -> str:
    """规范化实体名称，用于判断「同名实体」是否同一。
    去除角色标记【【】】、道具标记〖〖〗〗、空白和大小写。
    """
    if not name:
        return ""
    s = str(name)
    s = re.sub(r'[【】〖〗]', '', s)
    return s.strip().lower()


def _parse_id_num(prefix: str, entity_id: str) -> Optional[int]:
    """从 char_007 / loc_011 / prop_005 提取序号。"""
    if not entity_id:
        return None
    m = re.match(rf'^{re.escape(prefix)}_(\d+)$', str(entity_id))
    return int(m.group(1)) if m else None


# ---- 全局 ID 注册表 ----

class AcceptedRegistry:
    """任务级稳定资产注册表。

    随每段上下文传入模型，要求模型直接复用已有全局 ID。
    新实体只能使用当前段预留的下一组 ID（id_reservations），校验通过后才原子加入。
    见设计文档 §7.4 实体处理规则。
    """

    def __init__(self):
        self.characters: Dict[str, Dict[str, Any]] = {}   # id -> entity
        self.locations: Dict[str, Dict[str, Any]] = {}
        self.props: Dict[str, Dict[str, Any]] = {}
        self.spatial_world: Dict[str, Any] = {"space_units": []}
        # 名称反查（规范化名称 -> id），用于同实体去重
        self._name_index = {
            "character": {},
            "location": {},
            "prop": {},
        }
        # 下一段新实体的预留起始 ID
        self._cursors = {"char": 1, "loc": 1, "prop": 1}

    def to_context(self) -> Dict[str, Any]:
        """生成传给模型的 segment_context.accepted_registry 快照。"""
        return {
            "characters": list(self.characters.values()),
            "locations": list(self.locations.values()),
            "props": list(self.props.values()),
            "spatial_world": self.spatial_world,
        }

    def id_reservations(self) -> Dict[str, str]:
        """当前段可用的下一组新 ID。"""
        return {
            "character_start": f"char_{self._cursors['char']:03d}",
            "location_start": f"loc_{self._cursors['loc']:03d}",
            "prop_start": f"prop_{self._cursors['prop']:03d}",
        }

    def find_by_name(self, kind: str, name: str) -> Optional[str]:
        """按规范化名称查找已有实体 id。"""
        return self._name_index.get(kind, {}).get(_normalize_name(name))

    def find_by_db_id(self, kind: str, db_id: Any) -> Optional[str]:
        """按数据库主键查找已有实体 id。"""
        store = self._store(kind)
        db_field = f"{kind}_db_id"
        for eid, ent in store.items():
            if ent.get(db_field) is not None and str(ent.get(db_field)) == str(db_id):
                return eid
        return None

    def _store(self, kind: str) -> Dict[str, Dict[str, Any]]:
        return {"character": self.characters, "location": self.locations,
                "prop": self.props}[kind]

    def _advance_cursor(self, kind: str, entity_id: str) -> None:
        prefix_map = {"character": "char", "location": "loc", "prop": "prop"}
        prefix = prefix_map[kind]
        num = _parse_id_num(prefix, entity_id)
        if num is not None and num >= self._cursors[prefix]:
            self._cursors[prefix] = num + 1

    def commit_entity(self, kind: str, entity_id: str, entity: Dict[str, Any]) -> None:
        """段校验通过后原子加入新实体，推进游标。"""
        store = self._store(kind)
        store[entity_id] = entity
        name = entity.get("name") or entity.get("title")
        if name:
            self._name_index[kind][_normalize_name(name)] = entity_id
        self._advance_cursor(kind, entity_id)

    def commit_spatial_world(self, spatial_world: Dict[str, Any]) -> None:
        """合并段内新增的空间单元到全局 spatial_world。"""
        existing_ids = {u.get("space_unit_id") for u in self.spatial_world.get("space_units", [])}
        new_units = [u for u in (spatial_world.get("space_units") or [])
                     if u.get("space_unit_id") not in existing_ids]
        self.spatial_world.setdefault("space_units", []).extend(new_units)


# ---- 单段实体校验 ----

def validate_segment_entities(
    seg_result: Dict[str, Any],
    registry: AcceptedRegistry,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """校验单段的角色/场景/道具实体是否符合全局 ID 策略。

    见设计文档 §7.4 实体处理规则 1-4：
    1. 同 db_id 或规范化名称相同 → 必须复用已有全局 ID。
    2. 新实体 → 必须使用预留 ID 起始（char_NNN/loc_NNN/prop_NNN）。
    3. 给同实体分配新 ID、复用已占用 ID、引用未登记 ID → 拒绝。
    """
    errors: List[Dict[str, Any]] = []
    reservations = registry.id_reservations()
    res_start = {
        "character": _parse_id_num("char", reservations["character_start"]),
        "location": _parse_id_num("loc", reservations["location_start"]),
        "prop": _parse_id_num("prop", reservations["prop_start"]),
    }

    kind_specs = [
        ("character", "characters", "char", "character_db_id"),
        ("location", "locations", "loc", "location_db_id"),
        ("prop", "props", "prop", "props_db_id"),
    ]

    for kind, top_key, prefix, db_field in kind_specs:
        entities = seg_result.get(top_key) or []
        if not isinstance(entities, list):
            errors.append({"code": f"{kind}_not_list", "message": f"{top_key} 不是数组"})
            continue
        for ent in entities:
            if not isinstance(ent, dict):
                continue
            eid = ent.get("id")
            if not eid:
                errors.append({"code": f"{kind}_missing_id", "kind": kind,
                               "message": f"{kind} 缺少 id"})
                continue

            # 判断该实体是否应复用已有全局 ID
            existing_by_name = registry.find_by_name(kind, ent.get("name"))
            existing_by_db = registry.find_by_db_id(kind, ent.get(db_field))
            existing_id = existing_by_name or existing_by_db

            if existing_id is not None:
                # 应复用，但模型给了别的 id → 拒绝
                if eid != existing_id:
                    errors.append({
                        "code": f"{kind}_id_should_reuse",
                        "kind": kind,
                        "given_id": eid,
                        "expected_id": existing_id,
                        "message": f"{kind} '{ent.get('name')}' 应复用已有全局 ID {existing_id}，"
                                   f"但模型给了 {eid}",
                    })
            else:
                # 新实体：id 序号必须 >= 预留起始
                num = _parse_id_num(prefix, eid)
                start = res_start[kind]
                if num is None:
                    errors.append({
                        "code": f"{kind}_id_format_invalid",
                        "kind": kind,
                        "given_id": eid,
                        "message": f"新 {kind} id 格式应为 {prefix}_NNN，得到 {eid}",
                    })
                elif num < start:
                    errors.append({
                        "code": f"{kind}_id_not_reserved",
                        "kind": kind,
                        "given_id": eid,
                        "expected_start": f"{prefix}_{start:03d}",
                        "message": f"新 {kind} id {eid} 低于预留起始 {prefix}_{start:03d}，"
                                   f"可能复用了已占用编号",
                    })

    return (len(errors) == 0), errors


# ---- 空间引用完整性校验 ----

def _collect_registry_ids(registry: AcceptedRegistry) -> Dict[str, Set[str]]:
    """收集注册表中所有合法的全局 ID 集合。"""
    return {
        "character": set(registry.characters.keys()),
        "location": set(registry.locations.keys()),
        "prop": set(registry.props.keys()),
        "space_unit": {u.get("space_unit_id") for u in registry.spatial_world.get("space_units", [])},
        "anchor": _collect_anchors(registry.spatial_world),
        "frame": _collect_frames(registry.spatial_world),
    }


def _collect_anchors(spatial_world: Dict[str, Any]) -> Set[str]:
    """收集所有 space_unit 内的 anchor_id，按 space_unit 范围返回扁平集合。"""
    anchors: Set[str] = set()
    for u in spatial_world.get("space_units", []) or []:
        for a in u.get("anchors", []) or []:
            aid = a.get("anchor_id")
            if aid:
                anchors.add((u.get("space_unit_id"), aid))
    return anchors  # type: ignore[return-value]


def _collect_frames(spatial_world: Dict[str, Any]) -> Set[str]:
    return {u.get("coordinate_frame", {}).get("frame_id")
            for u in spatial_world.get("space_units", []) or []
            if u.get("coordinate_frame", {}).get("frame_id")}


def validate_segment_spatial_references(
    seg_result: Dict[str, Any],
    registry: AcceptedRegistry,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """逐路径验证单段 spatial_layout 引用的全局 ID 完整性。

    见设计文档 §7.5 第 5 点。所有引用必须存在于注册表或本段新增空间中。
    任一引用不存在、重复定义改变语义 → 拒绝，不静默深层改写。
    """
    errors: List[Dict[str, Any]] = []
    reg_ids = _collect_registry_ids(registry)

    # 本段 spatial_world 的新增空间单元也视为合法引用目标
    seg_space_units: Dict[str, Dict[str, Any]] = {}
    seg_anchors: Set[Tuple[str, str]] = set()
    seg_frames: Set[str] = set()
    for u in seg_result.get("spatial_world", {}).get("space_units", []) or []:
        suid = u.get("space_unit_id")
        if suid:
            seg_space_units[suid] = u
        for a in u.get("anchors", []) or []:
            aid = a.get("anchor_id")
            if aid and suid:
                seg_anchors.add((suid, aid))
        cf = u.get("coordinate_frame", {}) or {}
        if cf.get("frame_id"):
            seg_frames.add(cf["frame_id"])

    all_space_units = reg_ids["space_unit"] | set(seg_space_units.keys())
    all_anchors = reg_ids["anchor"] | seg_anchors  # type: ignore[operator]
    all_frames = reg_ids["frame"] | seg_frames
    def _current_entity_ids(key: str) -> Set[str]:
        return {
            str(entity["id"])
            for entity in (seg_result.get(key) or [])
            if isinstance(entity, dict) and entity.get("id")
        }

    # 当前候选段的实体尚未 commit 到 accepted_registry，但本段空间布局
    # 必须能够引用它们。这里只构造只读联合视图，不提前污染正式 registry；
    # 实体 ID 自身是否合法仍由 validate_segment_entities 独立判定。
    all_chars = reg_ids["character"] | _current_entity_ids("characters")
    all_locs = reg_ids["location"] | _current_entity_ids("locations")
    all_props = reg_ids["prop"] | _current_entity_ids("props")

    def _err(code, path, value, entity_id=None, extra=None):
        e = {"code": code, "path": path, "value": value}
        if entity_id:
            e["entity_id"] = entity_id
        if extra:
            e.update(extra)
        e["message"] = f"空间引用不存在: {path}={value}"
        errors.append(e)

    for group in seg_result.get("shot_groups", []) or []:
        for shot in group.get("shots", []) or []:
            sl = shot.get("spatial_layout")
            if not isinstance(sl, dict):
                continue
            shot_id = shot.get("shot_id", "?")
            prefix = f"shot[{shot_id}].spatial_layout"

            # space_unit_refs[]
            for ref in sl.get("space_unit_refs", []) or []:
                if ref not in all_space_units:
                    _err("ref_space_unit_unknown", f"{prefix}.space_unit_refs", ref)

            # camera_pose.space_unit_id
            cp = sl.get("camera_pose") or {}
            if cp.get("space_unit_id") and cp["space_unit_id"] not in all_space_units:
                _err("ref_space_unit_unknown", f"{prefix}.camera_pose.space_unit_id",
                     cp["space_unit_id"])

            # camera_anchor.relative_to_character.character_id
            ca = sl.get("camera_anchor") or {}
            rtc = ca.get("relative_to_character") or {}
            if rtc.get("character_id") and rtc["character_id"] not in all_chars:
                _err("ref_character_unknown",
                     f"{prefix}.camera_anchor.relative_to_character.character_id",
                     rtc["character_id"])

            # location_path[].location_id
            for lp in sl.get("location_path", []) or []:
                if lp.get("location_id") and lp["location_id"] not in all_locs:
                    _err("ref_location_unknown", f"{prefix}.location_path.location_id",
                         lp["location_id"])

            # containers[].prop_id/container_id 及 slots 引用
            for c in sl.get("containers", []) or []:
                if c.get("prop_id") and c["prop_id"] not in all_props:
                    _err("ref_prop_unknown", f"{prefix}.containers.prop_id", c["prop_id"])
                for s in c.get("slots", []) or []:
                    if s.get("space_unit_id") and s["space_unit_id"] not in all_space_units:
                        _err("ref_space_unit_unknown",
                             f"{prefix}.containers.slots.space_unit_id", s["space_unit_id"])
                    if s.get("anchor_id"):
                        if (s.get("space_unit_id"), s["anchor_id"]) not in all_anchors:
                            _err("ref_anchor_unknown",
                                 f"{prefix}.containers.slots.anchor_id", s["anchor_id"])
                    if s.get("character_id") and s["character_id"] not in all_chars:
                        _err("ref_character_unknown",
                             f"{prefix}.containers.slots.character_id", s["character_id"])

            # loose_positions[]
            for lp in sl.get("loose_positions", []) or []:
                if lp.get("space_unit_id") and lp["space_unit_id"] not in all_space_units:
                    _err("ref_space_unit_unknown",
                         f"{prefix}.loose_positions.space_unit_id", lp["space_unit_id"])
                if lp.get("anchor_id"):
                    if (lp.get("space_unit_id"), lp["anchor_id"]) not in all_anchors:
                        _err("ref_anchor_unknown",
                             f"{prefix}.loose_positions.anchor_id", lp["anchor_id"])
                if lp.get("character_id") and lp["character_id"] not in all_chars:
                    _err("ref_character_unknown",
                         f"{prefix}.loose_positions.character_id", lp["character_id"])

            # continuity.changed_positions[]
            cont = sl.get("continuity") or {}
            for ch in cont.get("changed_positions", []) or []:
                if ch.get("character_id") and ch["character_id"] not in all_chars:
                    _err("ref_character_unknown",
                         f"{prefix}.continuity.changed_positions.character_id",
                         ch["character_id"])
                if ch.get("from_container_id") and ch["from_container_id"] not in all_props:
                    _err("ref_prop_unknown",
                         f"{prefix}.continuity.changed_positions.from_container_id",
                         ch["from_container_id"])
                if ch.get("to_container_id") and ch["to_container_id"] not in all_props:
                    _err("ref_prop_unknown",
                         f"{prefix}.continuity.changed_positions.to_container_id",
                         ch["to_container_id"])

    return (len(errors) == 0), errors


# ---- 合并（全局阶段）----

def renumber_global(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """最终阶段统一重排 group_id / shot_id / shot_number。

    见设计文档 §9 第 4 点。角色/场景/道具/空间 ID 已在各段接受时稳定，不在此重写。
    """
    result = dict(parsed)
    groups = result.get("shot_groups") or []
    shot_counter = 0
    group_counter = 0
    total_duration = 0.0
    for g in groups:
        group_counter += 1
        g["group_id"] = f"grp_{group_counter:03d}"
        for s in g.get("shots", []) or []:
            shot_counter += 1
            s["shot_id"] = f"s{shot_counter:03d}"
            s["shot_number"] = shot_counter
            dur = s.get("duration")
            if isinstance(dur, (int, float)):
                total_duration += dur
    result["total_duration"] = int(total_duration) or result.get("total_duration", 0)
    result["metadata"] = result.get("metadata") or {}
    result["metadata"]["total_shots"] = shot_counter
    return result


__all__ = [
    "AcceptedRegistry",
    "validate_segment_entities",
    "validate_segment_spatial_references",
    "renumber_global",
]
