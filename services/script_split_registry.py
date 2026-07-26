"""
Script split registry - 全局 ID 注册表与空间引用完整性校验。

见 docs/script/script_parser_incremental_split_design.md §7.4 §7.5。
策略：模型直接复用任务级 ID + 后端逐路径验证，不做深层通用 ID 重写。
本模块纯函数，不依赖 DB / LLM。
"""
from typing import Dict, Any, List, Tuple, Optional, Set
from copy import deepcopy
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


# ---- 临时 ID / 全局 ID 改写 ----

_KIND_SPECS = [
    ("character", "characters", "char", "character_db_id"),
    ("location", "locations", "loc", "location_db_id"),
    ("prop", "props", "prop", "props_db_id"),
]


def _is_tmp_entity_id(prefix: str, entity_id: Any) -> bool:
    """新实体临时 id：char_tmp_xxx / loc_tmp_xxx / prop_tmp_xxx（tmp 后至少一段后缀）。"""
    if not entity_id:
        return False
    return bool(re.match(rf"^{re.escape(prefix)}_tmp_.+$", str(entity_id), flags=re.I))


def _apply_id_map_inplace(obj: Any, id_map: Dict[str, str]) -> None:
    """将树中所有等于旧 id 的字符串值替换为新 id（精确匹配）。

    要求 ``id_map`` 已是「无链」映射（任一 value 不再是另一 key），
    否则会因单趟替换产生连锁覆盖。调用方应先用
    ``_resolve_id_map_chains`` 解析链。
    """
    if not id_map:
        return
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            if isinstance(value, str) and value in id_map:
                obj[key] = id_map[value]
            else:
                _apply_id_map_inplace(value, id_map)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            if isinstance(value, str) and value in id_map:
                obj[index] = id_map[value]
            else:
                _apply_id_map_inplace(value, id_map)


def _resolve_id_map_chains(id_map: Dict[str, str]) -> Dict[str, str]:
    """解析 id_map 中的替换链，返回无链映射。

    例 ``{a:b, b:c}`` → ``{a:c, b:c}``。这样 ``_apply_id_map_inplace``
    单趟精确替换即可正确，不产生连锁覆盖。要求映射无环（实体归并场景
    天然无环：旧 ID 总指向新 ID，新 ID 不会再作为 key 出现）。
    """
    resolved: Dict[str, str] = {}
    for old, target in id_map.items():
        seen = {old}
        cur = target
        # 顺链解析到终点（终点不在 key 集合中）
        while cur in id_map and cur not in seen:
            seen.add(cur)
            cur = id_map[cur]
        resolved[old] = cur
    return resolved


def rewrite_segment_entity_ids(
    seg_result: Dict[str, Any],
    registry: AcceptedRegistry,
) -> Dict[str, Any]:
    """按 name / *_db_id 匹配 registry，把临时 id 与错误编号改写为全局 id。

    规则：
    1. name 或 db_id 命中 registry → 强制复用已有全局 id。
    2. 否则视为新实体：接受合法且未占用的 {prefix}_NNN（≥预留起始）；
       临时 id（prefix_tmp_xxx）、非法格式、低于预留、或撞已占用号 → 后端按序发号。
    3. 本段内同名新实体共享同一新全局 id。
    4. 改写 characters/locations/props 及整棵 JSON 中的精确 id 引用。

    不修改 registry 游标；commit 仍在段通过后进行。
    """
    if not isinstance(seg_result, dict):
        return seg_result

    reservations = registry.id_reservations()
    local_cursors = {
        "char": _parse_id_num("char", reservations["character_start"]) or 1,
        "loc": _parse_id_num("loc", reservations["location_start"]) or 1,
        "prop": _parse_id_num("prop", reservations["prop_start"]) or 1,
    }
    id_map: Dict[str, str] = {}
    # 本段已确定的最终 id（防止两个新实体抢同一合法号）
    taken_final_ids: Set[str] = set()
    for kind in ("character", "location", "prop"):
        taken_final_ids.update(registry._store(kind).keys())
    # 本段新实体：规范化名 → 最终 id
    pending_name_to_id: Dict[Tuple[str, str], str] = {}

    def _alloc(prefix: str) -> str:
        while True:
            num = local_cursors[prefix]
            local_cursors[prefix] = num + 1
            candidate = f"{prefix}_{num:03d}"
            if candidate not in taken_final_ids:
                taken_final_ids.add(candidate)
                return candidate

    for kind, top_key, prefix, db_field in _KIND_SPECS:
        entities = seg_result.get(top_key) or []
        if not isinstance(entities, list):
            continue
        for ent in entities:
            if not isinstance(ent, dict):
                continue
            old_id = str(ent.get("id") or "").strip()
            if not old_id:
                # 无 id：有 name 则发号并写回
                name_norm = _normalize_name(ent.get("name"))
                existing = (
                    registry.find_by_name(kind, ent.get("name"))
                    or registry.find_by_db_id(kind, ent.get(db_field))
                )
                if existing:
                    ent["id"] = existing
                    continue
                if name_norm and (kind, name_norm) in pending_name_to_id:
                    ent["id"] = pending_name_to_id[(kind, name_norm)]
                    continue
                new_id = _alloc(prefix)
                ent["id"] = new_id
                if name_norm:
                    pending_name_to_id[(kind, name_norm)] = new_id
                continue

            if old_id in id_map:
                ent["id"] = id_map[old_id]
                continue

            existing = (
                registry.find_by_name(kind, ent.get("name"))
                or registry.find_by_db_id(kind, ent.get(db_field))
            )
            name_norm = _normalize_name(ent.get("name"))

            if existing is not None:
                final_id = existing
            elif name_norm and (kind, name_norm) in pending_name_to_id:
                final_id = pending_name_to_id[(kind, name_norm)]
            else:
                num = _parse_id_num(prefix, old_id)
                res_key = {
                    "char": "character_start",
                    "loc": "location_start",
                    "prop": "prop_start",
                }[prefix]
                start = _parse_id_num(prefix, reservations[res_key]) or 1
                occupied_by_registry = old_id in registry._store(kind)
                keep_as_new = (
                    num is not None
                    and num >= start
                    and not _is_tmp_entity_id(prefix, old_id)
                    and not occupied_by_registry
                    and old_id not in taken_final_ids
                )
                if keep_as_new:
                    final_id = old_id
                    taken_final_ids.add(final_id)
                    if num + 1 > local_cursors[prefix]:
                        local_cursors[prefix] = num + 1
                else:
                    final_id = _alloc(prefix)
                if name_norm:
                    pending_name_to_id[(kind, name_norm)] = final_id

            if old_id != final_id:
                id_map[old_id] = final_id
            ent["id"] = final_id

    if id_map:
        _apply_id_map_inplace(seg_result, id_map)
        # 实体 id 再对齐一次（防止 map 应用顺序问题）
        for _kind, top_key, _prefix, _db in _KIND_SPECS:
            for ent in seg_result.get(top_key) or []:
                if not isinstance(ent, dict):
                    continue
                eid = str(ent.get("id") or "")
                if eid in id_map:
                    ent["id"] = id_map[eid]

    return seg_result


# ---- 合并阶段：按 name 登记先来后到重新发号 ----

def renumber_entities_by_name(
    parsed: Dict[str, Any],
    truth: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """合并阶段统一重发号：所有实体按规范化 name 登记，先来后到分配全局 ID。

    解决并发段各自为规划表外新实体分配了不一致 ID（甚至复用同一 ID 指向不同
    实体）导致的死锁（见 quality_merge_invalid）。发号原则：

    1. 命中真源（``truth``：quality 用 compiled_registry；speed 传空）的实体，
       强制使用真源 ID——真源是规划阶段的全局身份真源，段的 ID 不算数。
    2. 真源外的实体，段级 ID 一律丢弃，按规范化 name 登记先来后到从真源占用
       号段的下一个开始顺序发号（``{prefix}_NNN``）；同 name 复用已发号。
    3. 收集 id_map（段旧ID → 全局新ID），用 ``_apply_id_map_inplace`` 对整棵
       parsed 树精确重写（shot.props_present / characters_present /
       focus_character_ids / location_id / dialogue.character_id /
       spatial_layout 全部引用 / spatial_world.owner_id 等）。

    Args:
        parsed: 合并后的整棵数据树（会被原地修改并返回）。
        truth: 真源实体集合，形如 ``{"characters":[...], "locations":[...],
            "props":[...]}``。每个实体需含 ``id`` 与可选 ``name``/``*_db_id``。
            传 None / 空时所有实体都视为新实体从 001 起发号。

    Returns:
        重发号后的 ``parsed``（同一对象，原地修改）。
    """
    if not isinstance(parsed, dict):
        return parsed
    truth = truth or {}

    id_map: Dict[str, str] = {}
    # 已占用的最终 ID（真源 ID + 已发号的新 ID），防止抢号
    taken_final_ids: Set[str] = set()
    # 规范化 name → 最终 ID（同实体去重）
    name_to_id: Dict[Tuple[str, str], str] = {}
    # db_id(str) → 最终 ID（DB 主键也是身份真源，与 name 互补）
    db_id_to_id: Dict[Tuple[str, str], str] = {}
    # 各类发号游标：起点 = 真源已用最大号 + 1（无真源则 1）
    cursors = {"char": 1, "loc": 1, "prop": 1}

    # ---- 1. 登记真源实体，占用号段、建立反查索引 ----
    for kind, top_key, prefix, db_field in _KIND_SPECS:
        truth_items = truth.get(top_key) or []
        max_num = 0
        for ent in truth_items:
            if not isinstance(ent, dict):
                continue
            truth_id = str(ent.get("id") or "").strip()
            if not truth_id:
                continue
            taken_final_ids.add(truth_id)
            name_norm = _normalize_name(ent.get("name"))
            if name_norm:
                name_to_id[(kind, name_norm)] = truth_id
            db_val = ent.get(db_field)
            if db_val is not None and str(db_val) != "":
                db_id_to_id[(kind, str(db_val))] = truth_id
            num = _parse_id_num(prefix, truth_id)
            if num is not None and num > max_num:
                max_num = num
        # 真源占用号段之后开始发新号
        cursors[prefix] = max(cursors[prefix], max_num + 1)

    # ---- 1b. 真源实体作为基底注入：并发段只返回实体子集时，补回缺失的真源实体。
    #    命中真源的段实体保留其补充字段（描述/外观等），身份（id/name）以真源为准。
    for kind, top_key, prefix, db_field in _KIND_SPECS:
        existing_list = parsed.get(top_key)
        if not isinstance(existing_list, list):
            existing_list = []
            parsed[top_key] = existing_list
        # 真源身份索引：规范化 name / db_id → 真源 id
        truth_name_to_id: Dict[str, str] = {}
        truth_dbid_to_id: Dict[str, str] = {}
        for te in (truth.get(top_key) or []):
            if not isinstance(te, dict):
                continue
            tid = str(te.get("id") or "").strip()
            if not tid:
                continue
            nn = _normalize_name(te.get("name"))
            if nn:
                truth_name_to_id[nn] = tid
            dv = te.get(db_field)
            if dv is not None and str(dv) != "":
                truth_dbid_to_id[str(dv)] = tid
        # 段实体是否确属某真源实体：要求身份匹配（name 或 db_id）。
        # 仅 id 号落在真源号段但 name 不符（如段擅自复用了真源号给别的实体）
        # 不算真源段版本，避免误吞该段实体。
        existing_by_truth_id: Dict[str, Dict[str, Any]] = {}
        for ent in existing_list:
            if not isinstance(ent, dict):
                continue
            nn = _normalize_name(ent.get("name"))
            dv = ent.get(db_field)
            dk = str(dv) if (dv is not None and str(dv) != "") else ""
            matched_id = None
            if nn and nn in truth_name_to_id:
                matched_id = truth_name_to_id[nn]
            elif dk and dk in truth_dbid_to_id:
                matched_id = truth_dbid_to_id[dk]
            if matched_id:
                existing_by_truth_id[matched_id] = ent
        truth_items = truth.get(top_key) or []
        for truth_ent in truth_items:
            if not isinstance(truth_ent, dict):
                continue
            truth_id = str(truth_ent.get("id") or "").strip()
            if not truth_id:
                continue
            existing = existing_by_truth_id.get(truth_id)
            if existing is None:
                # parsed 缺失该真源实体 → 深拷贝补回
                existing_list.append(deepcopy(truth_ent))
            else:
                # 已存在：保留段补充字段，身份字段以真源为准（name/id/db_id）。
                # 段实体原 id 若与真源 id 不同，记录到 id_map 供后续整树重写，
                # 否则 shot 等引用处的旧 id 无法被更新。
                old_existing_id = str(existing.get("id") or "").strip()
                for k, v in truth_ent.items():
                    if k in ("id", "name", "entity_key", db_field):
                        existing[k] = v
                if old_existing_id and old_existing_id != truth_id:
                    id_map[old_existing_id] = truth_id

    # 预扫描：收集所有实体的 old_id。发号时必须避开它们——新发号若与某 old_id
    # 相同，会使该字符串既是 id_map 的 key（old_id 需被替换）又是 value
    # （新实体用它作目标），产生歧义导致误归并。避开 old_id 后新号与旧号空间
    # 不相交，id_map 无歧义（链解析 ``_resolve_id_map_chains`` 作额外保险）。
    reserved_old_ids: Set[str] = set()
    for _kind, top_key, _prefix, _db in _KIND_SPECS:
        for ent in parsed.get(top_key) or []:
            if isinstance(ent, dict):
                oid = str(ent.get("id") or "").strip()
                if oid:
                    reserved_old_ids.add(oid)

    def _alloc(prefix: str) -> str:
        """从游标顺序发号，跳过已占用号与所有 old_id。"""
        while True:
            num = cursors[prefix]
            cursors[prefix] = num + 1
            candidate = f"{prefix}_{num:03d}"
            if candidate not in taken_final_ids and candidate not in reserved_old_ids:
                taken_final_ids.add(candidate)
                return candidate

    # ---- 2. 遍历 parsed 实体，逐个确定最终 ID ----
    for kind, top_key, prefix, db_field in _KIND_SPECS:
        entities = parsed.get(top_key) or []
        if not isinstance(entities, list):
            continue
        for ent in entities:
            if not isinstance(ent, dict):
                continue
            old_id = str(ent.get("id") or "").strip()
            name_norm = _normalize_name(ent.get("name"))
            db_val = ent.get(db_field)
            db_key = str(db_val) if (db_val is not None and str(db_val) != "") else ""

            # 命中真源 name → 用真源 ID（真源优先于段 ID）
            final_id = (
                (name_to_id.get((kind, name_norm)) if name_norm else None)
                or (db_id_to_id.get((kind, db_key)) if db_key else None)
            )
            if final_id is None:
                # 真源外新实体：按 name 登记先来后到发号
                if name_norm and (kind, name_norm) in name_to_id:
                    final_id = name_to_id[(kind, name_norm)]
                else:
                    final_id = _alloc(prefix)
                    if name_norm:
                        name_to_id[(kind, name_norm)] = final_id
                    if db_key:
                        db_id_to_id[(kind, db_key)] = final_id

            if old_id and old_id != final_id:
                id_map[old_id] = final_id
            ent["id"] = final_id

    # ---- 3. 对整棵 parsed 树精确重写所有旧 ID 引用 ----
    if id_map:
        # 先解析替换链（新发号可能与某 old_id 撞号形成 a→b→c），确保单趟替换正确。
        id_map = _resolve_id_map_chains(id_map)
        # 实体自身的 id 已在阶段 2 直接赋值为 final_id，无需再走 map；
        # 此处重写整棵树中其余引用（shot.props_present 等）。
        # 注意：对实体数组节点需用解析后的 final 值，避免被二次映射。
        _apply_id_map_inplace(parsed, id_map)
        # 实体 id 再对齐一次（防止 map 应用顺序问题）
        for _kind, top_key, _prefix, _db in _KIND_SPECS:
            for ent in parsed.get(top_key) or []:
                if not isinstance(ent, dict):
                    continue
                eid = str(ent.get("id") or "")
                if eid in id_map:
                    ent["id"] = id_map[eid]

    # ---- 4. 按最终 ID 去重实体条目 ----
    # 重发号后多个段条目可能落到同一最终 ID（如同 name 同 db_id 的实体），
    # 需合并为单条：保留首条，后续条目的非空补充字段（描述/外观等）并入。
    for _kind, top_key, _prefix, _db in _KIND_SPECS:
        entities = parsed.get(top_key)
        if not isinstance(entities, list):
            continue
        merged_by_id: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for ent in entities:
            if not isinstance(ent, dict):
                continue
            eid = str(ent.get("id") or "").strip()
            if not eid:
                continue
            if eid not in merged_by_id:
                merged_by_id[eid] = dict(ent)
                order.append(eid)
            else:
                base = merged_by_id[eid]
                for k, v in ent.items():
                    # 身份字段（id/name/entity_key/db_id）以首条为准，其余补充字段并入
                    if k in ("id", "name", "entity_key", _db):
                        continue
                    if k not in base or base[k] in (None, "", [], {}):
                        base[k] = v
        parsed[top_key] = [merged_by_id[eid] for eid in order]

    return parsed


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

    调用方应先执行 rewrite_segment_entity_ids，以吸收 tmp id 与常见编号错误。
    """
    errors: List[Dict[str, Any]] = []
    reservations = registry.id_reservations()
    res_start = {
        "character": _parse_id_num("char", reservations["character_start"]),
        "location": _parse_id_num("loc", reservations["location_start"]),
        "prop": _parse_id_num("prop", reservations["prop_start"]),
    }

    for kind, top_key, prefix, db_field in _KIND_SPECS:
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
                        "message": f"新 {kind} id 格式应为 {prefix}_NNN 或 {prefix}_tmp_xxx，得到 {eid}",
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
    "rewrite_segment_entity_ids",
    "renumber_entities_by_name",
    "validate_segment_entities",
    "validate_segment_spatial_references",
    "renumber_global",
]
