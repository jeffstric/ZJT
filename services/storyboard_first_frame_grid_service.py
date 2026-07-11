"""Quality-mode storyboard first-frame grid orchestration."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from config.constant import (
    GridConfig,
    StoryboardAgentCommandConstants,
    StoryboardAutoGenerateConstants,
    StoryboardTimeouts,
)
from model.character import CharacterModel
from model.location import LocationModel
from model.props import PropsModel
from model.storyboard import StoryboardModel
from model.storyboard_image_batch import StoryboardImageBatchItemModel
from model.storyboard_scene import StoryboardSceneModel
from script_writer_core.constant import ItemType
from script_writer_core.mcp_tool import submit_grid_image_task
from services.storyboard_spatial import build_spatial_prompt_context

logger = logging.getLogger(__name__)
_LLM_REFINE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="first-frame-grid-llm")


def _to_dict(value: Any) -> Dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return {
            key: val
            for key, val in vars(value).items()
            if not key.startswith("_")
        }
    return {}


def _as_prompt_json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _reference_url(asset: Dict[str, Any]) -> str:
    if not asset:
        return ""
    for key in ("selected_reference_image", "reference_image", "image_url", "avatar", "pic", "url"):
        if asset.get(key):
            return str(asset[key])
    refs = asset.get("reference_images")
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except Exception:
            refs = []
    if isinstance(refs, list):
        for item in refs:
            if isinstance(item, str) and item:
                return item
            if isinstance(item, dict):
                for key in ("url", "file_url", "image_url", "reference_image"):
                    if item.get(key):
                        return str(item[key])
    return ""


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _safe_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _slot_visibility(slot: Dict[str, Any]) -> str:
    return str(slot.get("visibility") or "visible").strip().lower()


def _is_visible_spatial_item(item: Dict[str, Any]) -> bool:
    return _slot_visibility(item) in {"", "visible", "partial"}


class StoryboardFirstFrameGridService:
    """Submit ready quality-mode first-frame batch items as 2x2/3x3 grid tasks."""

    def __init__(
        self,
        counts_updater: Optional[Callable[[int], None]] = None,
        *,
        enable_llm_refine: bool = True,
    ) -> None:
        self._counts_updater = counts_updater
        self._enable_llm_refine = enable_llm_refine

    def process_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        job_id = int(job["id"])
        storyboard_id = int(job["storyboard_id"])
        storyboard = StoryboardModel.get_by_id(storyboard_id)
        storyboard_data = _to_dict(storyboard)
        scenes = StoryboardSceneModel.list_by_storyboard(storyboard_id) or []
        items = StoryboardImageBatchItemModel.list_by_job(job_id)
        scenes_by_id = {int(scene.get("id") or 0): scene for scene in scenes if scene.get("id")}
        items_by_scene_id = {
            int(item.get("scene_id") or 0): item
            for item in items
            if item.get("scene_id") is not None
        }
        self._fail_orphan_pending_items(job_id, items, scenes_by_id)
        previous_references = self._build_previous_group_references(scenes, items_by_scene_id)

        pending_items = [
            item for item in items
            if int(item.get("status") or 0) == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING
            and int(item.get("scene_id") or 0) in scenes_by_id
        ]
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for item in pending_items:
            scene = scenes_by_id[int(item["scene_id"])]
            key = self._grid_group_key(scene, item)
            grouped.setdefault(key, []).append(item)

        submitted_count = 0
        max_batches = int(StoryboardAutoGenerateConstants.QUALITY_GRID_BATCHES_PER_TICK)
        for group_items in grouped.values():
            if submitted_count >= max_batches:
                break
            group_key = self._grid_group_key(scenes_by_id[int(group_items[0]["scene_id"])], group_items[0])
            previous_reference = previous_references.get(group_key)
            if previous_reference and not previous_reference.get("url"):
                if self._handle_missing_previous_reference(job, group_items, previous_reference):
                    continue
            ready_items = self._ready_items(group_items, scenes_by_id)
            for chunk in self._chunk_ready_items(ready_items):
                if submitted_count >= max_batches:
                    break
                if self._submit_chunk(job, storyboard_data, scenes_by_id, chunk, previous_reference=previous_reference):
                    submitted_count += 1

        if self._counts_updater:
            self._counts_updater(job_id)
            updated_counts = True
        else:
            updated_counts = False
        return {"submitted_count": submitted_count, "updated_counts": updated_counts}

    def _fail_orphan_pending_items(
        self,
        job_id: int,
        items: Sequence[Dict[str, Any]],
        scenes_by_id: Dict[int, Dict[str, Any]],
    ) -> None:
        """Settle pending items whose scenes were removed by a later script split."""
        for item in items:
            if int(item.get("status") or 0) != StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING:
                continue
            scene_id = int(item.get("scene_id") or 0)
            if scene_id in scenes_by_id:
                continue
            extra = item.get("extra_json") if isinstance(item.get("extra_json"), dict) else {}
            StoryboardImageBatchItemModel.update(
                int(item["id"]),
                status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
                error_code="scene_deleted",
                error_message="scene was removed before the storyboard first-frame grid could run",
                extra_json={
                    **extra,
                    "failure_source": "scene_deleted",
                    "deleted_scene_id": scene_id,
                },
            )
            item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
            logger.warning(
                "[quality-grid] job=%s item=%s scene=%s no longer exists; mark failed",
                job_id,
                item.get("id"),
                scene_id,
            )

    def _grid_group_key(self, scene: Dict[str, Any], item: Dict[str, Any]) -> str:
        prompt = _as_prompt_json(scene.get("prompt_json"))
        source = prompt.get("source") if isinstance(prompt.get("source"), dict) else {}
        return _first_non_empty(
            item.get("group_key"),
            source.get("group_id"),
            source.get("group_name"),
            scene.get("act_name"),
            f"storyboard:{scene.get('storyboard_id')}",
        )

    def _scene_order_key(self, scene: Dict[str, Any]) -> Tuple[float, int]:
        try:
            order = float(scene.get("sort_order"))
        except (TypeError, ValueError):
            order = float("inf")
        return order, int(scene.get("id") or 0)

    def _build_previous_group_references(
        self,
        scenes: Sequence[Dict[str, Any]],
        items_by_scene_id: Dict[int, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        references: Dict[str, Dict[str, Any]] = {}
        previous_scene: Optional[Dict[str, Any]] = None
        previous_group_key: Optional[str] = None

        for scene in sorted(scenes, key=self._scene_order_key):
            scene_id = int(scene.get("id") or 0)
            item = items_by_scene_id.get(scene_id, {})
            group_key = self._grid_group_key(scene, item)
            if previous_scene and previous_group_key and group_key != previous_group_key and group_key not in references:
                previous_scene_id = int(previous_scene.get("id") or 0)
                previous_item = items_by_scene_id.get(previous_scene_id, {})
                references[group_key] = self._previous_scene_reference(previous_scene, previous_item)
            previous_scene = scene
            previous_group_key = group_key
        return references

    def _previous_scene_reference(self, scene: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
        url = _first_non_empty(
            item.get("result_url"),
            scene.get("first_frame_url"),
        )
        extra = item.get("extra_json") if isinstance(item.get("extra_json"), dict) else {}
        return {
            "source_type": "previous_frame",
            "name": str(scene.get("title") or f"scene_{scene.get('id')}"),
            "url": url,
            "role_description": f"previous storyboard frame: {scene.get('title') or scene.get('id')}",
            "scene_id": int(scene.get("id") or 0),
            "item_id": item.get("id"),
            "item_status": item.get("status"),
            "grid_prompt_group_context": extra.get("grid_prompt_group_context"),
        }

    def _handle_missing_previous_reference(
        self,
        job: Dict[str, Any],
        group_items: Sequence[Dict[str, Any]],
        previous_reference: Dict[str, Any],
    ) -> bool:
        previous_status = previous_reference.get("item_status")
        previous_is_active = previous_status in (
            StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
            StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING,
        )
        should_fail = (
            int(job.get("stop_on_error") or 0)
            and previous_status == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
        )
        max_wait_ticks = int(StoryboardAutoGenerateConstants.QUALITY_PREVIOUS_REFERENCE_WAIT_MAX_TICKS)
        for item in group_items:
            extra = item.get("extra_json") if isinstance(item.get("extra_json"), dict) else {}
            wait_count = int(extra.get("previous_group_reference_wait_count") or 0) + 1
            wait_extra = {
                **extra,
                "waiting": "previous_group_first_frame",
                "previous_scene_id": previous_reference.get("scene_id"),
                "previous_item_id": previous_reference.get("item_id"),
                "previous_group_reference_wait_count": wait_count,
                "previous_group_reference_wait_max_ticks": max_wait_ticks,
            }
            if should_fail:
                StoryboardImageBatchItemModel.update(
                    int(item["id"]),
                    status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
                    error_code="dependency_failed",
                    error_message="previous group last frame generation failed",
                    extra_json={**wait_extra, "failure_source": "previous_group_failed"},
                )
                item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
            elif not previous_is_active and wait_count > max_wait_ticks:
                StoryboardImageBatchItemModel.update(
                    int(item["id"]),
                    status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
                    error_code=StoryboardAutoGenerateConstants.ERROR_PREVIOUS_GROUP_REFERENCE_TIMEOUT,
                    error_message=(
                        "previous group last frame was not ready after "
                        f"{max_wait_ticks} scheduler ticks"
                    ),
                    extra_json={**wait_extra, "failure_source": "previous_group_reference_timeout"},
                )
                item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
            else:
                StoryboardImageBatchItemModel.update(
                    int(item["id"]),
                    extra_json=wait_extra,
                )
        return True

    def _ready_items(
        self,
        items: Sequence[Dict[str, Any]],
        scenes_by_id: Dict[int, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        ready: List[Dict[str, Any]] = []
        for item in sorted(items, key=lambda it: (it.get("order_index") or 0, it.get("id") or 0)):
            scene = scenes_by_id[int(item["scene_id"])]
            location = self._resolve_location(_as_prompt_json(scene.get("prompt_json")))
            if not _reference_url(location):
                extra = item.get("extra_json") if isinstance(item.get("extra_json"), dict) else {}
                StoryboardImageBatchItemModel.update(
                    int(item["id"]),
                    extra_json={
                        **extra,
                        "waiting": "location_grid_reference",
                        "location_db_id": location.get("id") or location.get("db_id") or location.get("location_db_id"),
                    },
                )
                continue
            ready.append(item)
        return ready

    def _chunk_ready_items(self, ready_items: Sequence[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        if not ready_items:
            return []
        if len(ready_items) <= GridConfig.SIZE_2X2:
            return [list(ready_items)]
        chunks: List[List[Dict[str, Any]]] = []
        for start in range(0, len(ready_items), GridConfig.SIZE_3X3):
            chunks.append(list(ready_items[start:start + GridConfig.SIZE_3X3]))
        return chunks

    def _submit_chunk(
        self,
        job: Dict[str, Any],
        storyboard: Dict[str, Any],
        scenes_by_id: Dict[int, Dict[str, Any]],
        chunk: Sequence[Dict[str, Any]],
        *,
        previous_reference: Optional[Dict[str, Any]] = None,
    ) -> bool:
        grid_size = GridConfig.SIZE_2X2 if len(chunk) <= GridConfig.SIZE_2X2 else GridConfig.SIZE_3X3
        real_scenes = [scenes_by_id[int(item["scene_id"])] for item in chunk]
        manifest, per_scene_indices = self._build_reference_manifest(real_scenes, previous_reference=previous_reference)
        item_names = [str(scene.get("title") or f"scene_{scene.get('id')}") for scene in real_scenes]
        prompts = [
            self._build_cell_prompt(scene, per_scene_indices.get(int(scene["id"]), []), manifest)
            for scene in real_scenes
        ]
        prompts = self._refine_prompts_with_llm(
            storyboard=storyboard,
            scenes=real_scenes,
            prompts=prompts,
            manifest=manifest,
            per_scene_indices=per_scene_indices,
            auth_token=str(job.get("auth_token") or ""),
            previous_grid_prompt_context=(previous_reference or {}).get("grid_prompt_group_context"),
        )
        group_key = self._grid_group_key(scenes_by_id[int(chunk[0]["scene_id"])], chunk[0])
        prompt_group_context = self._build_prompt_group_context(
            result_grid_task_id=None,
            group_key=group_key,
            scenes=real_scenes,
            prompts=prompts,
            per_scene_indices=per_scene_indices,
        )
        target_entity_ids: List[Optional[int]] = [int(scene["id"]) for scene in real_scenes]
        grid_cells: List[Dict[str, Any]] = [
            {
                "grid_index": index,
                "scene_id": int(item["scene_id"]),
                "batch_item_id": int(item["id"]),
                "placeholder": False,
            }
            for index, item in enumerate(chunk)
        ]
        while len(item_names) < grid_size:
            item_names.append("placeholder")
            prompts.append("")
            target_entity_ids.append(None)
            grid_cells.append(
                {
                    "grid_index": len(grid_cells),
                    "scene_id": None,
                    "batch_item_id": None,
                    "placeholder": True,
                }
            )

        ratio = _first_non_empty(job.get("ratio"), storyboard.get("workflow_ratio"), "16:9")
        result = submit_grid_image_task(
            user_id=str(job.get("user_id") or ""),
            world_id=str(storyboard.get("world_id") or ""),
            auth_token=str(job.get("auth_token") or ""),
            item_names=item_names,
            prompts=prompts,
            item_type=ItemType.STORYBOARD_FIRST_FRAME_GRID,
            grid_size=grid_size,
            mode="image_edit",
            reference_images=[
                {"url": ref["url"], "role_description": ref["role_description"]}
                for ref in manifest
            ],
            target_entity_ids=target_entity_ids,
            aspect_ratio=ratio,
            image_size=GridConfig.GRID_SIZE_IMAGE_SIZE_MAP.get(grid_size),
            grid_cells=grid_cells,
        )
        if not result.get("success"):
            for item in chunk:
                StoryboardImageBatchItemModel.update(
                    int(item["id"]),
                    status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
                    error_code=StoryboardAutoGenerateConstants.ERROR_GRID_FIRST_FRAME_FAILED,
                    error_message=str(result.get("error") or "grid first-frame submission failed")[:512],
                )
            return False

        grid_task_id = result.get("grid_task_id")
        prompt_group_context["grid_task_id"] = grid_task_id
        project_ids = result.get("project_ids") or []
        for index, item in enumerate(chunk):
            scene_id = int(item["scene_id"])
            extra = item.get("extra_json") if isinstance(item.get("extra_json"), dict) else {}
            next_extra = {
                key: value
                for key, value in extra.items()
                if key not in {
                    "waiting",
                    "previous_scene_id",
                    "previous_item_id",
                    "previous_group_reference_wait_count",
                    "previous_group_reference_wait_max_ticks",
                }
            }
            StoryboardImageBatchItemModel.update(
                int(item["id"]),
                status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING,
                ai_tool_id=project_ids[0] if project_ids else None,
                project_ids=project_ids,
                extra_json={
                    **next_extra,
                    "grid_task_id": grid_task_id,
                    "project_id": project_ids[0] if project_ids else None,
                    "grid_index": index,
                    "grid_size": grid_size,
                    "grid_group_key": self._grid_group_key(scenes_by_id[scene_id], item),
                    "reference_indices": per_scene_indices.get(scene_id, []),
                    "grid_task_key": result.get("task_key"),
                    "previous_group_scene_id": (previous_reference or {}).get("scene_id"),
                    "previous_group_reference_url": (previous_reference or {}).get("url"),
                    "grid_prompt_cell_context": prompt_group_context["cells"][index],
                    "grid_prompt_group_context": prompt_group_context,
                },
            )
        return True

    def _resolve_location(self, prompt_json: Dict[str, Any]) -> Dict[str, Any]:
        location_data = prompt_json.get("location") if isinstance(prompt_json.get("location"), dict) else {}
        location_id = (
            location_data.get("db_id")
            or location_data.get("id")
            or location_data.get("location_db_id")
        )
        source = prompt_json.get("source") if isinstance(prompt_json.get("source"), dict) else {}
        location_id = location_id or source.get("location_db_id")
        if location_id:
            location = LocationModel.get_by_id(int(location_id))
            if location:
                data = _to_dict(location)
                data.setdefault("id", int(location_id))
                return data
        return dict(location_data)

    def _build_reference_manifest(
        self,
        scenes: Sequence[Dict[str, Any]],
        *,
        previous_reference: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[int, List[int]]]:
        manifest: List[Dict[str, Any]] = []
        index_by_key: Dict[Tuple[str, str, str], int] = {}
        per_scene_indices: Dict[int, List[int]] = {}

        for scene in scenes:
            scene_id = int(scene["id"])
            prompt = _as_prompt_json(scene.get("prompt_json"))
            refs = self._scene_reference_items(prompt)
            indices = []
            for ref in refs:
                key = (ref["source_type"], ref["name"], ref["url"])
                if key not in index_by_key:
                    index_by_key[key] = len(manifest) + 1
                    manifest.append({**ref, "index": index_by_key[key]})
                indices.append(index_by_key[key])
            per_scene_indices[scene_id] = indices
        if previous_reference and previous_reference.get("url"):
            ref = {
                "source_type": "previous_frame",
                "name": str(previous_reference.get("name") or "previous frame"),
                "url": str(previous_reference["url"]),
                "role_description": str(previous_reference.get("role_description") or "previous storyboard frame"),
            }
            key = (ref["source_type"], ref["name"], ref["url"])
            if key not in index_by_key:
                index_by_key[key] = len(manifest) + 1
                manifest.append({**ref, "index": index_by_key[key]})
            previous_index = index_by_key[key]
            for scene_id in per_scene_indices:
                if previous_index not in per_scene_indices[scene_id]:
                    per_scene_indices[scene_id].append(previous_index)
        return manifest, per_scene_indices

    def _scene_reference_items(self, prompt_json: Dict[str, Any]) -> List[Dict[str, str]]:
        refs: List[Dict[str, str]] = []
        spatial = prompt_json.get("spatial_layout") if isinstance(prompt_json.get("spatial_layout"), dict) else {}

        for character_id, fallback_name in self._character_refs_from_spatial(spatial):
            character = _to_dict(CharacterModel.get_by_id(int(character_id))) if character_id else {}
            url = _reference_url(character)
            if url:
                refs.append({
                    "source_type": "character",
                    "name": character.get("name") or fallback_name,
                    "url": url,
                    "role_description": f"角色：{character.get('name') or fallback_name}",
                })

        for prop in prompt_json.get("props") or []:
            if not isinstance(prop, dict):
                continue
            prop_id = prop.get("db_id") or prop.get("props_db_id") or prop.get("id")
            prop_db_id = _safe_int(prop_id)
            prop_data = _to_dict(PropsModel.get_by_id(prop_db_id)) if prop_db_id is not None else prop
            url = _reference_url(prop_data)
            name = prop_data.get("name") or prop.get("name") or ""
            if url:
                refs.append({
                    "source_type": "prop",
                    "name": name,
                    "url": url,
                    "role_description": f"道具：{name}",
                })

        location = self._resolve_location(prompt_json)
        location_url = _reference_url(location)
        if location_url:
            refs.append({
                "source_type": "location",
                "name": location.get("name") or "",
                "url": location_url,
                "role_description": f"场景：{location.get('name') or ''}",
            })

        deduped: List[Dict[str, str]] = []
        seen = set()
        for ref in refs:
            key = (ref.get("source_type"), ref.get("name"), ref.get("url"))
            if ref.get("url") and key not in seen:
                seen.add(key)
                deduped.append(ref)
        return deduped

    def _character_refs_from_spatial(self, spatial_layout: Dict[str, Any]) -> Iterable[Tuple[Optional[int], str]]:
        for container in spatial_layout.get("containers") or []:
            if not isinstance(container, dict):
                continue
            for slot in container.get("slots") or []:
                if not isinstance(slot, dict):
                    continue
                if slot.get("occupant_type") in (None, "character") and _is_visible_spatial_item(slot):
                    yield slot.get("character_db_id") or slot.get("db_id"), str(slot.get("name") or "")
        for position in spatial_layout.get("loose_positions") or []:
            if not isinstance(position, dict):
                continue
            if position.get("occupant_type") == "character" and _is_visible_spatial_item(position):
                yield position.get("character_db_id") or position.get("db_id"), str(position.get("name") or "")

    def _spatial_entities(
        self,
        spatial_layout: Dict[str, Any],
        spatial_world: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        context = build_spatial_prompt_context(spatial_layout, spatial_world)
        return context["visible_entities"], context["hidden_entities"]

    def _build_cell_prompt(
        self,
        scene: Dict[str, Any],
        reference_indices: Sequence[int],
        manifest: Sequence[Dict[str, Any]],
    ) -> str:
        prompt = _as_prompt_json(scene.get("prompt_json"))
        spatial = prompt.get("spatial_layout") if isinstance(prompt.get("spatial_layout"), dict) else {}
        spatial_world = prompt.get("spatial_world") if isinstance(prompt.get("spatial_world"), dict) else None
        visible_entities, hidden_entities = self._spatial_entities(spatial, spatial_world)
        base_text = self._clean_hidden_entities_from_prompt(
            str(prompt.get("scene_desc") or scene.get("title") or "").strip(),
            hidden_entities,
        )
        camera_anchor_text = self._camera_anchor_prompt(spatial)
        visible_text = self._visible_spatial_prompt(visible_entities, hidden_entities)
        reference_text = "、".join(
            f"图{idx}" for idx in reference_indices
        )
        reference_details = "；".join(
            f"图{ref['index']}是{ref['role_description']}"
            for ref in manifest
            if ref.get("index") in set(reference_indices)
        )
        parts = [
            base_text,
            camera_anchor_text,
            visible_text,
            f"本格只使用这些参考图编号：{reference_text}。" if reference_text else "",
            reference_details,
        ]
        return "\n".join(part for part in parts if part)

    def _camera_anchor_prompt(self, spatial_layout: Dict[str, Any]) -> str:
        anchor = spatial_layout.get("camera_anchor") if isinstance(spatial_layout.get("camera_anchor"), dict) else {}
        if not anchor:
            return ""

        parts = []
        for key in ("description", "camera_position", "shooting_direction", "screen_composition"):
            value = str(anchor.get(key) or "").strip()
            if value and value not in parts:
                parts.append(value)

        relative = anchor.get("relative_to_character")
        if isinstance(relative, dict):
            rel_parts = [
                str(relative.get("name") or "").strip(),
                str(relative.get("position") or "").strip(),
                str(relative.get("distance") or "").strip(),
            ]
            rel_text = "，".join(part for part in rel_parts if part)
            if rel_text:
                parts.append(f"相机相对角色位置：{rel_text}")

        if not parts:
            return ""
        return "机位必须保持与分镜一致：" + "；".join(parts) + "。"

    def _visible_spatial_prompt(
        self,
        visible_entities: Sequence[Dict[str, Any]],
        hidden_entities: Sequence[Dict[str, Any]],
    ) -> str:
        lines: List[str] = []
        for entity in visible_entities:
            parts = []
            if entity.get("screen_position"):
                parts.append(str(entity["screen_position"]))
            if entity.get("slot"):
                parts.append(str(entity["slot"]))
            parts.append(str(entity.get("name") or ""))
            if entity.get("pose"):
                parts.append(str(entity["pose"]))
            line = "，".join(part for part in parts if part)
            if line:
                lines.append(line + "。")

        hidden_slots = []
        for entity in hidden_entities:
            slot = _first_non_empty(entity.get("slot"), entity.get("screen_position"))
            if slot and slot not in hidden_slots:
                hidden_slots.append(slot)
        for slot in hidden_slots:
            lines.append(f"构图中{slot}不入画。")

        return "\n".join(lines)

    def _clean_hidden_entities_from_prompt(
        self,
        prompt_text: str,
        hidden_entities: Sequence[Dict[str, Any]],
    ) -> str:
        text = str(prompt_text or "")
        for entity in hidden_entities:
            name = str(entity.get("name") or "").strip()
            if name:
                text = text.replace(name, "")
        return text.replace("，，", "，").replace("，。", "。").strip()

    def _build_prompt_cell_context(
        self,
        scene: Dict[str, Any],
        grid_index: int,
        final_prompt_text: str,
        reference_indices: Sequence[int],
    ) -> Dict[str, Any]:
        prompt = _as_prompt_json(scene.get("prompt_json"))
        spatial = prompt.get("spatial_layout") if isinstance(prompt.get("spatial_layout"), dict) else {}
        spatial_world = prompt.get("spatial_world") if isinstance(prompt.get("spatial_world"), dict) else None
        visible_entities, hidden_entities = self._spatial_entities(spatial, spatial_world)
        return {
            "scene_id": int(scene.get("id") or 0),
            "grid_index": int(grid_index),
            "final_prompt_text": str(final_prompt_text or ""),
            "visible_entities": [entity.get("name") for entity in visible_entities if entity.get("name")],
            "hidden_continuity_entities": [entity.get("name") for entity in hidden_entities if entity.get("name")],
            "spatial_summary": self._spatial_summary(visible_entities, hidden_entities),
            "reference_indices": list(reference_indices),
        }

    def _build_prompt_group_context(
        self,
        *,
        result_grid_task_id: Any,
        group_key: str,
        scenes: Sequence[Dict[str, Any]],
        prompts: Sequence[str],
        per_scene_indices: Dict[int, List[int]],
    ) -> Dict[str, Any]:
        cells = [
            self._build_prompt_cell_context(
                scene,
                index,
                prompts[index] if index < len(prompts) else "",
                per_scene_indices.get(int(scene["id"]), []),
            )
            for index, scene in enumerate(scenes)
        ]
        return {
            "grid_task_id": result_grid_task_id,
            "group_key": group_key,
            "cells": cells,
        }

    def _spatial_summary(
        self,
        visible_entities: Sequence[Dict[str, Any]],
        hidden_entities: Sequence[Dict[str, Any]],
    ) -> str:
        parts: List[str] = []
        for entity in visible_entities:
            name = entity.get("name")
            slot = _first_non_empty(entity.get("slot"), entity.get("screen_position"))
            if name and slot:
                parts.append(f"{name}在{slot}")
            elif name:
                parts.append(str(name))
        for entity in hidden_entities:
            slot = _first_non_empty(entity.get("slot"), entity.get("screen_position"))
            if slot:
                parts.append(f"{slot}不入画")
        return "；".join(parts)

    def _refine_prompts_with_llm(
        self,
        *,
        storyboard: Dict[str, Any],
        scenes: Sequence[Dict[str, Any]],
        prompts: List[str],
        manifest: Sequence[Dict[str, Any]],
        per_scene_indices: Dict[int, List[int]],
        auth_token: str,
        previous_grid_prompt_context: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        if not self._enable_llm_refine:
            return prompts
        try:
            future = _LLM_REFINE_EXECUTOR.submit(
                self._call_llm_refiner,
                storyboard,
                scenes,
                prompts,
                manifest,
                per_scene_indices,
                auth_token,
                previous_grid_prompt_context,
            )
            return future.result(timeout=StoryboardTimeouts.FIRST_FRAME_GRID_LLM_PROMPT_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning("首帧宫格 LLM prompt 改写超时，使用确定性 prompt")
            return prompts
        except Exception as exc:
            logger.warning("首帧宫格 LLM prompt 改写失败，使用确定性 prompt: %s", exc)
            return prompts

    def _call_llm_refiner(
        self,
        storyboard: Dict[str, Any],
        scenes: Sequence[Dict[str, Any]],
        prompts: List[str],
        manifest: Sequence[Dict[str, Any]],
        per_scene_indices: Dict[int, List[int]],
        auth_token: str,
        previous_grid_prompt_context: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        from llm.llm_client_factory import get_llm_client

        model, model_id, vendor_id = self._llm_model_context(storyboard)
        cells = []
        for index, scene in enumerate(scenes):
            scene_id = int(scene["id"])
            prompt = _as_prompt_json(scene.get("prompt_json"))
            spatial_layout = prompt.get("spatial_layout") if isinstance(prompt.get("spatial_layout"), dict) else {}
            spatial_world = prompt.get("spatial_world") if isinstance(prompt.get("spatial_world"), dict) else None
            visible_entities, hidden_entities = self._spatial_entities(spatial_layout, spatial_world)
            cells.append({
                "scene_id": scene_id,
                "grid_index": index,
                "prompt_text": prompts[index],
                "reference_indices": per_scene_indices.get(scene_id, []),
                "spatial_world": spatial_world or {},
                "spatial_layout": spatial_layout,
                "visible_entities": visible_entities,
                "hidden_continuity_entities": hidden_entities,
            })
        system_prompt = (
            "你是分镜首帧宫格提示词编辑器。只输出 JSON，不要 Markdown。"
            "输入中的 reference_indices 是服务层权威编号，不得改动；"
            "spatial_layout、visible_entities、hidden_continuity_entities 只用于理解空间连续性；"
            "最终 prompt_text 只描述画面中应当可见的内容，不能输出 visibility、framing_role、spatial_layout、容器/区域、空间布局硬约束等字段化文本；"
            "hidden_continuity_entities 代表仍在空间里但本格不可见或被遮挡的对象，不要把它们写成可见主体；必要时只用自然语言写构图不入画。"
            "slot_integrity_rule: preserve every physical seat/slot from spatial_layout exactly. Do not change front passenger/side-by-side/front-row seats into rear seats. Rear-seat wording is allowed only if spatial_layout already says rear seat or changed_positions declares a real seat move."
            "camera_anchor_integrity_rule: preserve camera_anchor camera_position, shooting_direction, and screen_composition; do not invent a different viewpoint while refining prompt_text."
            "previous_grid_prompt_context 仅作前一幕风格、环境、角色状态参考；当前 spatial_layout 始终优先，不要照抄上一幕 prompt。"
        )
        user_payload = {
            "reference_manifest": list(manifest),
            "previous_grid_prompt_context": previous_grid_prompt_context or {},
            "shots": cells,
            "output_schema": {
                "shots": [
                    {
                        "scene_id": "int",
                        "grid_index": "int",
                        "prompt_text": "string",
                        "reference_indices": ["int"],
                    }
                ]
            },
        }
        client = get_llm_client(model, vendor_id=vendor_id)
        response = client.call_api(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            temperature=0.2,
            max_tokens=4096,
            auth_token=auth_token,
            vendor_id=vendor_id,
            model_id=model_id,
            enable_thinking=False,
            agent_scope="storyboard_first_frame_grid",
        )
        content = response.choices[0].message.content if getattr(response, "choices", None) else ""
        parsed = self._parse_llm_json(content)
        returned = parsed.get("shots") if isinstance(parsed, dict) else None
        if not isinstance(returned, list):
            raise ValueError("LLM output missing shots array")
        prompt_by_key = {}
        expected_keys = {(int(scene["id"]), idx) for idx, scene in enumerate(scenes)}
        for item in returned:
            if not isinstance(item, dict):
                continue
            raw_scene_id = item.get("scene_id")
            raw_grid_index = item.get("grid_index")
            key = (
                int(raw_scene_id) if raw_scene_id is not None else 0,
                int(raw_grid_index) if raw_grid_index is not None else -1,
            )
            if key not in expected_keys:
                continue
            text = str(item.get("prompt_text") or "").strip()
            if text:
                prompt_by_key[key] = text
        if set(prompt_by_key.keys()) != expected_keys:
            raise ValueError("LLM output shots do not match input scenes")
        cleaned_prompts: List[str] = []
        for idx, scene in enumerate(scenes):
            prompt = _as_prompt_json(scene.get("prompt_json"))
            spatial = prompt.get("spatial_layout") if isinstance(prompt.get("spatial_layout"), dict) else {}
            spatial_world = prompt.get("spatial_world") if isinstance(prompt.get("spatial_world"), dict) else None
            _, hidden_entities = self._spatial_entities(spatial, spatial_world)
            cleaned_prompts.append(
                self._clean_hidden_entities_from_prompt(
                    prompt_by_key[(int(scene["id"]), idx)],
                    hidden_entities,
                )
            )
        return cleaned_prompts

    def _llm_model_context(self, storyboard: Dict[str, Any]) -> Tuple[str, Optional[int], Optional[int]]:
        config = storyboard.get("config_json") or {}
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except Exception:
                config = {}
        selected = config.get("selectedScriptSplitLlmModel") if isinstance(config, dict) else None
        if isinstance(selected, dict):
            model = str(selected.get("model") or selected.get("name") or "").strip()
            model_id = selected.get("model_id") or selected.get("id")
            vendor_id = selected.get("vendor_id") or selected.get("vendorId")
        else:
            model = str(selected or "").strip()
            model_id = None
            vendor_id = None
        return (
            model or StoryboardAgentCommandConstants.DEFAULT_SCRIPT_SPLIT_MODEL,
            int(model_id) if model_id else None,
            int(vendor_id) if vendor_id else None,
        )

    def _parse_llm_json(self, content: str) -> Dict[str, Any]:
        text = str(content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end >= start:
            text = text[start:end + 1]
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("LLM output is not a JSON object")
        return parsed
