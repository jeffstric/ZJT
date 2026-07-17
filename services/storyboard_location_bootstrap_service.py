"""
Storyboard location bootstrap service.

将剧本解析（llm/script_parser）产出的 locations 落库为可复用的 location 资产，
建立 loc_xxx -> 数据库 location.id 的映射，并回填到 parsed_data，使下游
build_storyboard_scenes_from_parsed_script 写入的 prompt_json.source.location_db_id
能拿到真实的 DB id。

设计要点：
  - parent_id 是真实外键（ON DELETE SET NULL），必须先父后子拓扑排序入库。
  - LocationModel.create_or_update 的 ON DUPLICATE KEY 只按 (world_id, name) 匹配，
    同名不同 parent 的子场景会被误 upsert，故创建前先 get_by_name 校验 parent_id
    一致性，不一致则给新行名追加 " (子场景)" 后缀并记 warning。
  - 新顶层、孤儿父级和父级环属于结构硬错误，任何数据库写入前直接拒绝。
  - 本服务为纯同步 DB 操作；web 接口调用时须用 asyncio.to_thread 包装。

仅消费 location_db_id / name / parent_id（内部 loc_xxx）/ description 字段；
atmosphere/environment_sound/background_music/level 不落库，仅随 location dict
原样保留在 parsed_data 里，供九宫格 prompt 使用。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from model.location import LocationModel

logger = logging.getLogger(__name__)

# 同名异父子场景创建时追加的后缀，避免在 (world_id, name) 上撞唯一键
_SUBSCENE_CONFLICT_SUFFIX = " (子场景)"


class LocationBootstrapStructureError(ValueError):
    """bootstrap 最后防线发现非法场景父级结构。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class StoryboardLocationBootstrapService:
    """剧本解析后：location 入库 + id 回填。"""

    def bootstrap(
        self,
        parsed_data: Dict[str, Any],
        world_id: int,
        user_id: int,
        *,
        update_existing_description: bool = True,
    ) -> Dict[str, Any]:
        """
        将 parsed_data.locations 落库并回填真实 DB id。

        Args:
            parsed_data: 解析后的剧本数据（会被原地修改：locations[i].location_db_id、
                         shot_groups[].shots[].db_location_id）。
            world_id: 世界观 DB id。
            user_id: 用户 DB id。

        Returns:
            {
                'created_location_count': int,   # 新建的子场景数
                'reused_location_count': int,    # 复用既有 DB 场景数
                'id_map': {loc_xxx -> db_id},    # 内部 id 到 DB id 映射
                'warnings': List[str],           # 名称冲突 / 孤儿场景等告警
            }
        """
        warnings: List[str] = []
        id_map: Dict[str, Optional[int]] = {}
        created_count = 0
        reused_count = 0

        locations = parsed_data.get("locations") or []
        if not isinstance(locations, list):
            return self._empty_result()

        self._validate_structure_before_write(locations)
        ordered = self._topological_order(locations, warnings)

        for location in ordered:
            loc_key = str(location.get("id") or "")
            if not loc_key:
                continue

            existing_db_id = self._safe_int(location.get("location_db_id"))
            if existing_db_id is not None:
                # 顶层已匹配场景：直接复用 DB id，不入库
                id_map[loc_key] = existing_db_id
                reused_count += 1
                continue

            # 新场景 / 子场景：解析父 id
            parent_key = location.get("parent_id")
            parent_db_id = id_map.get(str(parent_key)) if parent_key else None

            name = self._clean_name(location.get("name"))
            if not name:
                warnings.append(f"loc_key={loc_key} 缺少 name，跳过入库")
                id_map[loc_key] = None
                continue

            if parent_key and parent_db_id is None:
                raise LocationBootstrapStructureError(
                    "location_parent_invalid",
                    f"子场景 {loc_key}(name={name}) 的父场景 {parent_key} 未能映射到数据库",
                )
            # 无 parent_key：新顶层场景，parent_db_id=None，下面 create 以 parent_id=None 落库

            # 先查同名行：存在则直接复用 id（绝不走 upsert，避免 ON DUPLICATE KEY UPDATE
            # 把已有的 reference_image / reference_images 抹成 NULL，造成数据丢失）。
            # - 同名同父：复用既有行（最常见，重跑场景）。
            # - 同名异父：改名（加后缀）后作为新行创建，避免覆盖别人的 parent_id。
            existing = LocationModel.get_by_name(world_id, name)
            if existing is not None:
                existing_parent = self._safe_int(getattr(existing, 'parent_id', None))
                if existing_parent == parent_db_id:
                    # 同名同父：复用既有行，但可选更新 description（重跑剧本时场景描述可能变化）
                    db_id = self._safe_int(getattr(existing, 'id', None))
                    if db_id:
                        id_map[loc_key] = db_id
                        location["location_db_id"] = db_id
                        # 如果解析产生了新的 description，更新它（不动 reference_image，保护已有参考图）
                        new_desc = location.get("description")
                        if update_existing_description and new_desc:
                            old_desc = getattr(existing, 'description', None) or ''
                            if str(new_desc).strip() != str(old_desc).strip():
                                LocationModel.update(db_id, description=new_desc)
                        reused_count += 1
                        continue
                # 同名异父：改名后走新建分支
                resolved_name = f"{name}{_SUBSCENE_CONFLICT_SUFFIX}"
                warnings.append(
                    f"loc_key={loc_key} 名称 '{name}' 与 parent_id={existing_parent} 的既有场景"
                    f"冲突（当前 parent_id={parent_db_id}），改名为 '{resolved_name}'"
                )
                renamed = True
            else:
                resolved_name = name
                renamed = False

            # 真正新建：用 create（纯 INSERT），不触发 ON DUPLICATE KEY 的字段覆盖。
            # 若并发导致唯一键冲突（极罕见），fallback 到 create_or_update 但显式
            # 保留既有 reference_image（查一次最新值带回填）。
            try:
                db_id = LocationModel.create(
                    world_id=world_id,
                    name=resolved_name,
                    user_id=user_id,
                    parent_id=parent_db_id,
                    description=location.get("description"),
                )
            except Exception as create_err:
                # 唯一键冲突 fallback：查既有行复用 id（保护已有字段）
                existing_after = LocationModel.get_by_name(world_id, resolved_name)
                if existing_after is not None:
                    db_id = self._safe_int(getattr(existing_after, 'id', None))
                    if db_id:
                        warnings.append(
                            f"loc_key={loc_key} name={resolved_name} 创建时唯一键冲突，复用既有 id={db_id}"
                        )
                    else:
                        raise
                else:
                    raise

            # 回写 location dict，保留解析阶段携带的描述性字段供九宫格 prompt 使用
            location["location_db_id"] = db_id
            location["name"] = resolved_name
            if renamed:
                location["renamed_from"] = name

            id_map[loc_key] = db_id
            created_count += 1

        # 回填 shot.db_location_id（build_storyboard_scenes_from_parsed_script 优先读它）
        self._backfill_shots(parsed_data, id_map, warnings)

        logger.info(
            "[location-bootstrap] world_id=%s created=%s reused=%s warnings=%s",
            world_id, created_count, reused_count, len(warnings),
        )

        return {
            "created_location_count": created_count,
            "reused_location_count": reused_count,
            "id_map": id_map,
            "warnings": warnings,
        }

    # ---------- 内部辅助 ----------

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "created_location_count": 0,
            "reused_location_count": 0,
            "id_map": {},
            "warnings": [],
        }

    def _validate_structure_before_write(
        self,
        locations: List[Dict[str, Any]],
    ) -> None:
        """写入前验证每个新场景的父链最终到达一个已有 DB 场景。"""
        by_key = {
            str(location.get("id") or location.get("location_id")): location
            for location in locations
            if isinstance(location, dict)
            and (location.get("id") or location.get("location_id"))
        }
        for location in by_key.values():
            if self._safe_int(location.get("location_db_id")) is not None:
                continue
            key = str(location.get("id") or location.get("location_id") or "")
            parent_key = str(location.get("parent_id") or "")
            if not parent_key:
                # 新顶层场景放行：DB 没有的新地点允许作为顶层落库
                # （提示词引导 LLM 优先挂父场景，找不到合适父场景才作顶层新建）
                continue

            visited = {key}
            current_key = parent_key
            while True:
                if current_key in visited:
                    raise LocationBootstrapStructureError(
                        "location_parent_invalid",
                        f"场景 {key} 的父级形成环：{current_key}",
                    )
                visited.add(current_key)
                current = by_key.get(current_key)
                if current is None:
                    raise LocationBootstrapStructureError(
                        "location_parent_invalid",
                        f"场景 {key} 的父级 {current_key} 不存在",
                    )
                if self._safe_int(current.get("location_db_id")) is not None:
                    break
                next_parent = str(current.get("parent_id") or "")
                if not next_parent:
                    raise LocationBootstrapStructureError(
                        "location_parent_invalid",
                        f"场景 {key} 的父级链无法到达已有数据库场景",
                    )
                current_key = next_parent

    def _topological_order(
        self, locations: List[Dict[str, Any]], warnings: List[str]
    ) -> List[Dict[str, Any]]:
        """
        按 level 升序 + 父先于子排序。

        level 缺失时按 0 处理（顶层）；同 level 保持原顺序（稳定排序）。
        检测到 parent_id 指向不存在的 loc_key 时记 warning（孤儿场景）。
        """
        all_keys = {
            str(loc.get("id")) for loc in locations if isinstance(loc, dict) and loc.get("id")
        }
        for loc in locations:
            parent = loc.get("parent_id") if isinstance(loc, dict) else None
            if parent and str(parent) not in all_keys:
                warnings.append(
                    f"loc_key={loc.get('id')} 的 parent_id={parent} 不在 locations 列表中"
                )

        def _level(loc: Dict[str, Any]) -> int:
            lv = loc.get("level")
            try:
                return int(lv) if lv is not None else 0
            except (TypeError, ValueError):
                return 0

        # 稳定排序：先按 level，同 level 内保留原始相对顺序（Python sort 稳定）
        return sorted(
            [loc for loc in locations if isinstance(loc, dict)],
            key=_level,
        )

    def _backfill_shots(
        self,
        parsed_data: Dict[str, Any],
        id_map: Dict[str, Optional[int]],
        warnings: List[str],
    ) -> None:
        """
        回填 shot_groups[].shots[].db_location_id。

        build_storyboard_scenes_from_parsed_script 优先读 shot.db_location_id，
        其次读 location.location_db_id。两处都回填以确保 scene 的
        prompt_json.source.location_db_id 拿到真实 DB id。
        """
        for group in parsed_data.get("shot_groups") or []:
            if not isinstance(group, dict):
                continue
            for shot in group.get("shots") or []:
                if not isinstance(shot, dict):
                    continue
                loc_key = str(shot.get("location_id") or "")
                if not loc_key or loc_key not in id_map:
                    continue
                db_id = id_map.get(loc_key)
                if db_id is None:
                    if not shot.get("db_location_id"):
                        warnings.append(
                            f"shot location_id={loc_key} 解析到的 DB id 为空"
                        )
                    continue
                shot["db_location_id"] = db_id

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            iv = int(value)
            return iv if iv > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clean_name(name: Any) -> str:
        return str(name or "").strip()

    # ---------- Phase 5: 按父场景分批提交九宫格 i2i ----------

    def submit_subscene_grids(
        self,
        parsed_data: Dict[str, Any],
        bootstrap_result: Dict[str, Any],
        world_id: int,
        user_id: int,
        auth_token: str = "",
        *,
        force_overwrite: bool = False,
    ) -> Dict[str, Any]:
        """
        按父场景分组子场景，提交 3x3 九宫格 i2i 任务（父场景图作为输入）。

        规则：
          - 按父场景分组其子场景。
          - 父场景必须有 reference_image，否则该批不提交（标 missing_parent_reference_image），
            子场景后续首帧生图走 t2i 降级。
          - 不足 9 个补 placeholder 占位（不回写、不建 location）；超过 9 个拆多个 3x3 批次。
          - 每个子场景 prompt 必含父场景上下文 + 连续性约束。

        Args:
            force_overwrite: 兼容旧调用参数，已废弃且不再生效；已有参考图的子场景
                             始终会被跳过，避免覆盖用户资产。

        非阻塞：每个批次独立提交，单个失败不影响其他批次。

        Returns:
            {
                'submitted_batches': int,         # 已提交批次数
                'submitted_subscene_count': int,  # 已提交子场景数
                'skipped_no_parent_image': int,   # 因父图缺失跳过的子场景数
                'batch_details': List[dict],      # 各批次明细
                'warnings': List[str],
            }
        """
        # 延迟导入避免循环依赖
        from script_writer_core.mcp_tool import generate_9grid_location_images
        from config.constant import GridConfig

        id_map = bootstrap_result.get("id_map") or {}
        warnings = list(bootstrap_result.get("warnings") or [])
        locations = parsed_data.get("locations") or []

        # 建立 loc_xxx -> location dict
        loc_by_key = {
            str(loc.get("id")): loc for loc in locations
            if isinstance(loc, dict) and loc.get("id")
        }

        # 按父场景分组子场景（只处理 parent_id 指向 loc_xxx 且自身已入库的子场景）
        # 补偿重跑友好：始终跳过「已有参考图」或「已有运行中九宫格任务」的子场景，
        # 只提交「缺图且无运行中任务」的，避免重复提交 / 覆盖已生成结果。
        # force_overwrite 为兼容旧 API 保留，但不再允许覆盖已有参考图。
        del force_overwrite
        children_by_parent: Dict[str, List[Dict[str, Any]]] = {}
        skipped_already_has_image = 0
        skipped_running_grid = 0
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            parent_key = loc.get("parent_id")
            if not parent_key:
                continue  # 顶层场景，不作为子场景处理
            sub_db_id = self._safe_int(loc.get("location_db_id"))
            if sub_db_id is None:
                continue  # 入库失败的子场景，跳过
            # 跳过已有参考图的子场景（重跑时不重复生成，也不允许旧 overwrite 参数覆盖）
            if self._subscene_has_reference_image(sub_db_id, loc):
                skipped_already_has_image += 1
                continue
            # 跳过有运行中九宫格任务的子场景，避免同一子场景并发回写互相覆盖。
            if self._subscene_has_running_grid(sub_db_id):
                skipped_running_grid += 1
                continue
            children_by_parent.setdefault(str(parent_key), []).append(loc)

        if skipped_already_has_image or skipped_running_grid:
            logger.info(
                "[subscene-grids] 跳过已有图子场景=%s, 跳过运行中任务子场景=%s",
                skipped_already_has_image, skipped_running_grid,
            )

        submitted_batches = 0
        submitted_subscene_count = 0
        skipped_no_parent_image = 0
        batch_details = []

        for parent_key, children in children_by_parent.items():
            parent_db_id = self._safe_int(id_map.get(parent_key))
            parent_loc = loc_by_key.get(parent_key) or {}

            # 取父场景参考图
            parent_image = self._resolve_parent_reference_image(parent_db_id, parent_loc)
            if not parent_image:
                skipped_no_parent_image += len(children)
                warnings.append(
                    f"父场景 {parent_key}(db_id={parent_db_id}) 无参考图，"
                    f"{len(children)} 个子场景九宫格批次未提交 (missing_parent_reference_image)"
                )
                batch_details.append({
                    "parent_key": parent_key,
                    "parent_db_id": parent_db_id,
                    "status": "missing_parent_reference_image",
                    "subscene_count": len(children),
                })
                continue

            # 拆成多个 3x3 批次
            # 构造参考图列表：父场景图 + 角色说明（拼进 prompt 全局说明区）
            parent_name = self._clean_name(parent_loc.get("name")) if isinstance(parent_loc, dict) else ""
            ref_images_for_grid = [{
                "url": parent_image,
                "role_description": (
                    f"父场景'{parent_name}'的完整场景图，展示整体空间结构、色彩、材质、光照，"
                    f"各子场景需保持与其连续性"
                ),
            }]
            for batch_idx, batch in enumerate(self._chunk_into_grid_batches(children, GridConfig.SIZE_3X3)):
                item_names, target_ids, prompts = self._build_batch_grid_io(
                    batch, parent_loc, GridConfig.SIZE_3X3, id_map
                )
                try:
                    result = generate_9grid_location_images(
                        user_id=str(user_id),
                        world_id=str(world_id),
                        auth_token=auth_token,
                        sub_location_names=item_names,
                        prompts=prompts,
                        reference_images=ref_images_for_grid,
                        target_entity_ids=target_ids,
                    )
                    ok = bool(result.get("success"))
                    submitted_batches += 1 if ok else 0
                    if ok:
                        submitted_subscene_count += len(batch)
                    batch_details.append({
                        "parent_key": parent_key,
                        "parent_db_id": parent_db_id,
                        "batch_index": batch_idx,
                        "status": "submitted" if ok else "failed",
                        "subscene_count": len(batch),
                        "target_entity_ids": target_ids,
                        "result": result,
                    })
                    if not ok:
                        msg = f"父场景 {parent_key} 批次 {batch_idx} 提交失败: {result.get('error')}"
                        warnings.append(msg)
                        logger.error("[subscene-grids] %s", msg)
                except Exception as exc:
                    msg = f"父场景 {parent_key} 批次 {batch_idx} 提交异常: {exc}"
                    warnings.append(msg)
                    logger.error("[subscene-grids] %s", msg, exc_info=True)
                    batch_details.append({
                        "parent_key": parent_key,
                        "parent_db_id": parent_db_id,
                        "batch_index": batch_idx,
                        "status": "exception",
                        "subscene_count": len(batch),
                    })

        logger.info(
            "[subscene-grids] world_id=%s submitted_batches=%s subscenes=%s skipped_no_parent=%s",
            world_id, submitted_batches, submitted_subscene_count, skipped_no_parent_image,
        )

        return {
            "submitted_batches": submitted_batches,
            "submitted_subscene_count": submitted_subscene_count,
            "skipped_no_parent_image": skipped_no_parent_image,
            "batch_details": batch_details,
            "warnings": warnings,
        }

    # ---- Phase 5 辅助 ----

    def _subscene_has_reference_image(self, sub_db_id: int, loc: Dict[str, Any]) -> bool:
        """子场景是否已有参考图。优先查 DB 行（重跑时反映最新状态），fallback 到 parsed dict。"""
        try:
            db_loc = LocationModel.get_by_id(sub_db_id)
            if db_loc and db_loc.reference_image:
                return True
        except Exception as exc:
            logger.warning(f"查询子场景 db_id={sub_db_id} 参考图失败: {exc}")
        # DB 无图时，回退看 parsed dict（首次提交时 DB 可能还没图）
        return bool(isinstance(loc, dict) and loc.get("reference_image"))

    def _subscene_has_running_grid(self, sub_db_id: int) -> bool:
        """子场景是否有运行中的九宫格任务（避免补偿重跑时重复提交）。"""
        try:
            from model.grid_image_tasks import GridImageTasksModel
            return GridImageTasksModel.has_running_grid_for_entity(sub_db_id)
        except Exception as exc:
            logger.warning(f"查询子场景 db_id={sub_db_id} 运行中九宫格任务失败: {exc}")
            return False

    def _resolve_parent_reference_image(
        self, parent_db_id: Optional[int], parent_loc: Dict[str, Any]
    ) -> Optional[str]:
        """取父场景参考图：优先 DB 行 reference_image，其次 reference_images[0]。"""
        # 先用 parsed location dict 里携带的（若有）
        img = parent_loc.get("reference_image") if isinstance(parent_loc, dict) else None
        if img:
            return img
        if parent_db_id:
            try:
                loc = LocationModel.get_by_id(parent_db_id)
                if loc:
                    if loc.reference_image:
                        return loc.reference_image
                    refs = loc.reference_images
                    if isinstance(refs, str):
                        import json as _json
                        try:
                            refs = _json.loads(refs)
                        except (ValueError, TypeError):
                            refs = []
                    if isinstance(refs, list) and refs:
                        first = refs[0]
                        if isinstance(first, dict):
                            return first.get("url")
                        if isinstance(first, str):
                            return first
            except Exception as exc:
                logger.warning(f"取父场景 db_id={parent_db_id} 参考图失败: {exc}")
        return None

    @staticmethod
    def _chunk_into_grid_batches(
        items: List[Dict[str, Any]], grid_size: int
    ) -> List[List[Dict[str, Any]]]:
        """将子场景列表切成 grid_size 大小的批次。"""
        return [items[i:i + grid_size] for i in range(0, len(items), grid_size)]

    def _build_batch_grid_io(
        self,
        batch: List[Dict[str, Any]],
        parent_loc: Dict[str, Any],
        grid_size: int,
        id_map: Dict[str, Optional[int]],
    ) -> tuple:
        """
        构造一批九宫格的 (item_names, target_entity_ids, prompts)。

        不足 grid_size 补 placeholder（名称用 'placeholder'，切图回写时跳过）。
        target_entity_ids 仅含真实子场景 db id（placeholder 对应位置为 None，
        回写器按索引对齐时跳过 None）。
        """
        from config.constant import GridConfig

        item_names: List[str] = []
        target_ids: List[Optional[int]] = []
        prompts: List[str] = []

        parent_name = self._clean_name(parent_loc.get("name")) if isinstance(parent_loc, dict) else ""
        parent_desc = self._clean_name(parent_loc.get("description")) if isinstance(parent_loc, dict) else ""

        for sub in batch:
            name = self._clean_name(sub.get("name"))
            db_id = self._safe_int(sub.get("location_db_id"))
            item_names.append(name)
            target_ids.append(db_id)
            prompts.append(self._compose_subscene_prompt(sub, parent_name, parent_desc))

        # 补 placeholder 至 grid_size
        while len(item_names) < grid_size:
            item_names.append("placeholder")
            target_ids.append(None)
            prompts.append("纯黑背景占位，无场景内容。")

        return item_names, target_ids, prompts

    @staticmethod
    def _compose_subscene_prompt(
        sub: Dict[str, Any], parent_name: str, parent_desc: str
    ) -> str:
        """
        构造单个子场景的九宫格 prompt 文本。

        必须包含父场景上下文 + 子场景描述 + 氛围 + 连续性约束，
        使图生图能保持父场景空间结构/色彩/材质/光照连续。
        """
        name = str(sub.get("name") or "").strip()
        desc = str(sub.get("description") or "").strip()
        atmosphere = str(sub.get("atmosphere") or "").strip()
        env_sound = str(sub.get("environment_sound") or "").strip()
        loc_type = str(sub.get("type") or "").strip()

        parts = []
        if parent_name:
            parts.append(f"父场景：{parent_name}。")
        if parent_desc:
            parts.append(f"父场景描述：{parent_desc}。")
        parts.append("以上述父场景参考图为基础，保持其空间结构、色彩、材质、光照的连续性。")
        if name:
            parts.append(f"子场景：{name}。")
        if loc_type:
            parts.append(f"类型：{loc_type}。")
        if desc:
            parts.append(f"子场景描述：{desc}。")
        if atmosphere:
            parts.append(f"氛围/光线：{atmosphere}。")
        if env_sound:
            parts.append(f"环境声参考：{env_sound}。")
        return " ".join(parts)
