import json
import hashlib
import logging
import math
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config.config_util import get_config, get_current_env
from config.constant import (
    Edition,
    StoryboardAgentCommandConstants,
    StoryboardAgentReadConstants,
    StoryboardAutoGenerateConstants,
    StoryboardFeatureFlags,
    SceneDifficulty,
    MediaGenerationMode,
    MediaGenerationSurface,
    MediaGenerationType,
)
from config.unified_config import SceneVideoType, UnifiedConfigRegistry
from model.ai_tools import AIToolsModel
from model.character import CharacterModel
from model.location import LocationModel
from model.props import PropsModel
from model.script import ScriptModel
from model.storyboard import StoryboardModel
from model.user_preferences import UserPreferencesModel
from model.storyboard_dialogue import StoryboardDialogueModel
from model.storyboard_image_batch import StoryboardImageBatchItemModel, StoryboardImageBatchJobModel
from model.storyboard_scene import StoryboardSceneModel, compute_sort_between, is_precision_exhausted
from model.storyboard_scene_asset import StoryboardSceneAssetModel
from model.world import WorldModel
from model.grid_image_tasks import GridImageTasksModel, GridImageTaskStatus
from services.storyboard_reference_prompt_service import (
    append_reference_legend,
    append_storyboard_visual_suffix,
    build_storyboard_reference_items,
    extract_storyboard_reference_names,
    reference_urls,
)
from services.storyboard_first_frame_grid_service import StoryboardFirstFrameGridService
from services.storyboard_quality_sequence import (
    get_storyboard_quality_location_reference_coordinator,
)
from services.media_generation_preference_service import (
    MediaGenerationPreferenceError,
    MediaGenerationPreferenceService,
)


VALID_IMAGE_MODES = {"auto", "text_to_image", "image_edit"}
VALID_VIDEO_MODES = {"text_to_video", "image_to_video"}
# 图生视频的图片输入模式：first_last_frame（首尾帧）/ multi_reference（全能参考）。
# 对齐 marketing_agent 与驱动层 ImageMode，驱动支持的第三种 first_last_with_ref 仅手动对话用，批量不开放。
VALID_VIDEO_IMAGE_MODES = {"first_last_frame", "multi_reference", "first_last_with_ref"}
VALID_ASSET_TYPES = {"first_frame", "last_frame", "video"}
IMAGE_ASSET_TYPES = {"first_frame", "last_frame"}

logger = logging.getLogger(__name__)
_IMAGE_BATCH_CREATE_LOCK = threading.Lock()


def _build_cli_generation_snapshots(
    user_id: int,
    world_id: int,
    *,
    media_type: str,
    modes: Sequence[str],
    explicit_task_id: Optional[int] = None,
    profile_values: Optional[Dict[str, Any]] = None,
    surface: str = MediaGenerationSurface.STORYBOARD_CLI,
) -> Dict[str, Dict[str, Any]]:
    snapshots: Dict[str, Dict[str, Any]] = {}
    for mode in modes:
        try:
            if explicit_task_id not in (None, ''):
                config = MediaGenerationPreferenceService.validate_model(
                    explicit_task_id,
                    media_type,
                    mode,
                    image_mode=(profile_values or {}).get('image_mode'),
                )
                profile = dict(profile_values or {})
                profile.update({
                    'schema_version': 1,
                    'task_id': int(config.id),
                    'model_key': config.key,
                    'model_name': config.name,
                })
                source = 'request'
            else:
                profile = MediaGenerationPreferenceService.get_profile(
                    user_id,
                    world_id,
                    surface,
                    media_type,
                    mode,
                )
                source = 'preference'
            snapshot = MediaGenerationPreferenceService.build_snapshot(
                profile,
                surface,
                media_type,
                mode,
                model_source=source,
            )
            snapshots[MediaGenerationPreferenceService.slot_key(media_type, mode)] = snapshot
        except MediaGenerationPreferenceError:
            if len(modes) == 1:
                raise
    if not snapshots:
        raise StoryboardCliError('MODEL_REQUIRED', '没有可用于本批次的媒体模型快照')
    return snapshots


def _batch_status_name(code: Any) -> str:
    """批量 item/job 状态码 → 可读名称，仅用于诊断日志。"""
    mapping = {
        0: "pending",
        1: "running",
        2: "completed",
        -1: "failed",
        3: "skipped",
    }
    try:
        return mapping.get(int(code), str(code))
    except (TypeError, ValueError):
        return str(code)


def _url_preview(url: Any) -> str:
    """日志里的 URL 只保留是否非空 + 尾段，避免刷屏。"""
    if not url:
        return "None"
    text = str(url)
    return text if len(text) <= 48 else f"{text[:32]}...({len(text)}chars)"


class StoryboardCliError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.payload = payload or {}

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "success": False,
            "error_code": self.error_code,
            "error": self.message,
            "environment": get_current_env(),
        }
        data.update(self.payload)
        return data


def _to_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    result: Dict[str, Any] = {}
    for key, val in vars(value).items():
        if key.startswith("_"):
            continue
        if hasattr(val, "isoformat"):
            result[key] = val.isoformat()
        else:
            result[key] = val
    return result


def _parse_json(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return default


def _dedupe(values: Sequence[Any]) -> List[Any]:
    seen = set()
    out: List[Any] = []
    for value in values:
        if value in (None, ""):
            continue
        marker = str(value)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(value)
    return out


def _get_field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_reference_urls(item: Any) -> List[str]:
    data = _to_dict(item)
    urls: List[str] = []
    single = data.get("reference_image")
    if single:
        urls.append(single)

    refs = _parse_json(data.get("reference_images"), [])
    if isinstance(refs, list):
        for ref in refs:
            if isinstance(ref, str):
                urls.append(ref)
            elif isinstance(ref, dict):
                urls.append(ref.get("url") or ref.get("image_url") or ref.get("path"))
    return _dedupe(urls)


def _public_upload_url(url: Any) -> str:
    if not url:
        return ""
    text = str(url).strip().replace("\\", "/")
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text

    relative = text.lstrip("/")
    if not relative.startswith("upload/"):
        return text

    try:
        host = (get_config().get("server", {}) or {}).get("host", "")
    except Exception:
        host = ""
    if not host:
        return f"/{relative}"
    return f"{host.rstrip('/')}/{relative}"


def _reference_label(source_type: str, name: Optional[str]) -> str:
    label_map = {
        "style": "全局画风参考图",
        "character": "角色",
        "location": "场景",
        "prop": "道具",
        "asset": "前一分镜",
    }
    prefix = label_map.get(source_type, "参考图")
    return f"{prefix}：{name}" if name else prefix


def _append_reference_item(
    items: List[Dict[str, Any]],
    seen: set,
    url: Any,
    *,
    source_type: str,
    name: Optional[str] = None,
    label: Optional[str] = None,
) -> None:
    if not url:
        return
    url_text = _public_upload_url(url)
    if not url_text or url_text in seen:
        return
    seen.add(url_text)
    items.append({
        "url": url_text,
        "source_type": source_type,
        "name": name or "",
        "label": label or _reference_label(source_type, name),
    })


def _project_ids(result: Dict[str, Any]) -> List[int]:
    values = result.get("project_ids")
    if values is None and result.get("project_id") is not None:
        values = [result.get("project_id")]
    if not isinstance(values, list):
        return []
    out = []
    for item in values:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _asset_selected_field(asset_type: str) -> str:
    if asset_type == "first_frame":
        return "selected_first_frame_id"
    if asset_type == "last_frame":
        return "selected_last_frame_id"
    if asset_type == "video":
        return "selected_video_id"
    raise StoryboardCliError("invalid_asset_type", f"invalid asset_type: {asset_type}")


class AiToolSubmissionService:
    """Thin adapter over the same tool functions used by the agent/home flows."""

    def text_to_image(self, **kwargs) -> Dict[str, Any]:
        from script_writer_core.mcp_tool import generate_text_to_image

        return generate_text_to_image(**kwargs)

    def image_edit(self, **kwargs) -> Dict[str, Any]:
        from script_writer_core.mcp_tool import edit_image

        return edit_image(**kwargs)

    def text_to_video(self, **kwargs) -> Dict[str, Any]:
        from enterprise.tools.video_tools import generate_text_to_video

        return generate_text_to_video(**kwargs)

    def image_to_video(self, **kwargs) -> Dict[str, Any]:
        from enterprise.tools.video_tools import image_to_video

        return image_to_video(**kwargs)


class StoryboardAgentCliService:
    def __init__(self, submitter: Optional[AiToolSubmissionService] = None):
        self.submitter = submitter or AiToolSubmissionService()

    def get_media_preferences(
        self,
        user_id: int,
        world_id: int,
        *,
        media_type: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        user_id = self._require_user_id(user_id)
        self._ensure_world_for_user(world_id, user_id)
        slots = []
        for current_type, modes in (
            (MediaGenerationType.IMAGE, MediaGenerationMode.IMAGE_MODES),
            (MediaGenerationType.VIDEO, MediaGenerationMode.VIDEO_MODES),
        ):
            for current_mode in modes:
                if media_type and current_type != media_type:
                    continue
                if mode and current_mode != mode:
                    continue
                slots.append((current_type, current_mode))
        if not slots:
            raise StoryboardCliError('invalid_parameter', 'media_type/mode 组合无效')
        profiles = {}
        for current_type, current_mode in slots:
            profile = MediaGenerationPreferenceService.get_profile(
                user_id,
                world_id,
                MediaGenerationSurface.STORYBOARD_CLI,
                current_type,
                current_mode,
            )
            profiles[MediaGenerationPreferenceService.slot_key(current_type, current_mode)] = profile
        return {'success': True, 'profiles': profiles}

    def set_media_preference(
        self,
        user_id: int,
        world_id: int,
        *,
        media_type: str,
        mode: str,
        task_id: int,
    ) -> Dict[str, Any]:
        user_id = self._require_user_id(user_id)
        self._ensure_world_for_user(world_id, user_id)
        try:
            profile = MediaGenerationPreferenceService.save_profile(
                user_id,
                world_id,
                MediaGenerationSurface.STORYBOARD_CLI,
                media_type,
                mode,
                {'task_id': task_id},
            )
        except (MediaGenerationPreferenceError, ValueError) as exc:
            code = getattr(exc, 'code', 'invalid_parameter')
            raise StoryboardCliError(code, str(exc))
        return {
            'success': True,
            'slot': MediaGenerationPreferenceService.slot_key(media_type, mode),
            'profile': profile,
        }

    def list_worlds(
        self,
        user_id: int,
        *,
        page: int = 1,
        page_size: int = StoryboardAgentReadConstants.DEFAULT_PAGE_SIZE,
        keyword: Optional[str] = None,
        include_full_story_outline: bool = False,
    ) -> Dict[str, Any]:
        user_id = self._require_user_id(user_id)
        result = WorldModel.list_by_user(
            user_id=user_id,
            page=self._normalize_page(page),
            page_size=self._normalize_page_size(page_size),
            order_by="update_time",
            order_direction="DESC",
            keyword=keyword,
        )
        result = self._filter_page_by_user(result, user_id)
        result["data"] = [
            self._world_payload(item, include_full_story_outline=include_full_story_outline)
            for item in result.get("data", [])
        ]
        return {"success": True, **result}

    def list_world_scripts(
        self,
        world_id: int,
        user_id: int,
        *,
        page: int = 1,
        page_size: int = StoryboardAgentReadConstants.DEFAULT_PAGE_SIZE,
        include_content: bool = False,
        include_full_story_outline: bool = False,
    ) -> Dict[str, Any]:
        user_id = self._require_user_id(user_id)
        world = self._ensure_world_for_user(world_id, user_id)
        result = ScriptModel.list_by_user(
            user_id=user_id,
            page=self._normalize_page(page),
            page_size=self._normalize_page_size(page_size),
            order_by="episode_number",
            order_direction="ASC",
            world_id=int(world_id),
        )
        data = result.get("data") or []
        original_count = len(data)
        result["data"] = [
            self._script_payload(item, include_content=include_content)
            for item in data
            if self._record_belongs_to_user(item, user_id)
        ]
        if len(result["data"]) != original_count:
            result["total"] = len(result["data"])
        return {
            "success": True,
            "world": self._world_payload(world, include_full_story_outline=include_full_story_outline),
            **result,
        }

    def get_script(self, script_id: int, user_id: int) -> Dict[str, Any]:
        user_id = self._require_user_id(user_id)
        script = self._ensure_script_for_user(script_id, user_id)
        return {"success": True, "script": self._script_payload(_to_dict(script), include_content=True)}

    def list_world_characters(
        self,
        world_id: int,
        user_id: int,
        *,
        page: int = 1,
        page_size: int = StoryboardAgentReadConstants.DEFAULT_PAGE_SIZE,
        keyword: Optional[str] = None,
        include_full_story_outline: bool = False,
    ) -> Dict[str, Any]:
        user_id = self._require_user_id(user_id)
        world = self._ensure_world_for_user(world_id, user_id)
        result = CharacterModel.list_by_world(
            int(world_id),
            page=self._normalize_page(page),
            page_size=self._normalize_page_size(page_size),
            order_by="name",
            order_direction="ASC",
            keyword=keyword,
        )
        return {
            "success": True,
            "world": self._world_payload(world, include_full_story_outline=include_full_story_outline),
            **self._filter_page_by_user(result, user_id),
        }

    def list_world_locations(
        self,
        world_id: int,
        user_id: int,
        *,
        page: int = 1,
        page_size: int = StoryboardAgentReadConstants.DEFAULT_PAGE_SIZE,
        keyword: Optional[str] = None,
        include_full_story_outline: bool = False,
    ) -> Dict[str, Any]:
        user_id = self._require_user_id(user_id)
        world = self._ensure_world_for_user(world_id, user_id)
        result = LocationModel.list_by_world(
            int(world_id),
            page=self._normalize_page(page),
            page_size=self._normalize_page_size(page_size),
            order_by="name",
            order_direction="ASC",
            keyword=keyword,
        )
        return {
            "success": True,
            "world": self._world_payload(world, include_full_story_outline=include_full_story_outline),
            **self._filter_page_by_user(result, user_id),
        }

    def list_world_props(
        self,
        world_id: int,
        user_id: int,
        *,
        page: int = 1,
        page_size: int = StoryboardAgentReadConstants.DEFAULT_PAGE_SIZE,
        keyword: Optional[str] = None,
        include_full_story_outline: bool = False,
    ) -> Dict[str, Any]:
        user_id = self._require_user_id(user_id)
        world = self._ensure_world_for_user(world_id, user_id)
        result = PropsModel.list_by_world(
            int(world_id),
            page=self._normalize_page(page),
            page_size=self._normalize_page_size(page_size),
            keyword=keyword,
            order_by="name",
            order_direction="ASC",
        )
        return {
            "success": True,
            "world": self._world_payload(world, include_full_story_outline=include_full_story_outline),
            **self._filter_page_by_user(result, user_id),
        }

    def world_context(
        self,
        world_id: int,
        user_id: int,
        *,
        page_size: int = StoryboardAgentReadConstants.DEFAULT_WORLD_CONTEXT_PAGE_SIZE,
        include_script_content: bool = False,
        include_full_story_outline: bool = False,
    ) -> Dict[str, Any]:
        user_id = self._require_user_id(user_id)
        world = self._ensure_world_for_user(world_id, user_id)
        page_size = self._normalize_page_size(page_size)
        scripts = self.list_world_scripts(
            world_id=int(world_id),
            user_id=user_id,
            page=1,
            page_size=page_size,
            include_content=include_script_content,
            include_full_story_outline=include_full_story_outline,
        )
        characters = self.list_world_characters(
            int(world_id),
            user_id,
            page=1,
            page_size=page_size,
            include_full_story_outline=include_full_story_outline,
        )
        locations = self.list_world_locations(
            int(world_id),
            user_id,
            page=1,
            page_size=page_size,
            include_full_story_outline=include_full_story_outline,
        )
        props = self.list_world_props(
            int(world_id),
            user_id,
            page=1,
            page_size=page_size,
            include_full_story_outline=include_full_story_outline,
        )
        return {
            "success": True,
            "world": self._world_payload(world, include_full_story_outline=include_full_story_outline),
            "scripts": self._page_summary(scripts),
            "characters": self._page_summary(characters),
            "locations": self._page_summary(locations),
            "props": self._page_summary(props),
        }

    def create_storyboard_from_script(
        self,
        script_id: int,
        user_id: int,
        *,
        title: Optional[str] = None,
        workflow_id: Optional[int] = None,
        version: int = 1,
        model: Optional[Any] = None,
        model_id: Optional[int] = None,
        vendor_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        user_id = self._require_user_id(user_id)
        script = self._ensure_script_for_user(script_id, user_id)

        world_id = _get_field(script, "world_id")
        if not world_id:
            raise StoryboardCliError("script_missing_world", f"script has no world_id: {script_id}")

        episode_number = int(_get_field(script, "episode_number") or 1)
        explicit_model = any(value not in (None, "") for value in (model, model_id, vendor_id))
        preference_warning = None
        preference_saved = None
        existing = StoryboardModel.get_by_user_world_episode(int(user_id), int(world_id), episode_number)
        if existing:
            existing_script_id = _get_field(existing, "script_id")
            if existing_script_id and int(existing_script_id) != int(script_id):
                raise StoryboardCliError(
                    "storyboard_exists_with_other_script",
                    "storyboard already exists for this user/world/episode with another script",
                    payload={
                        "storyboard_id": _get_field(existing, "id"),
                        "existing_script_id": existing_script_id,
                        "script_id": int(script_id),
                    },
                )
            if not existing_script_id:
                StoryboardModel.update(int(_get_field(existing, "id")), script_id=int(script_id))
                existing = StoryboardModel.get_by_id(int(_get_field(existing, "id"))) or existing
            existing_config = self._storyboard_config(existing)
            existing_selection = self._normalize_script_split_model_selection(
                existing_config.get("selectedScriptSplitLlmModel")
            )
            selection = None
            if explicit_model:
                selection = self._normalize_script_split_model_selection(
                    model, model_id=model_id, vendor_id=vendor_id
                )
            elif existing_selection:
                selection = existing_selection
            else:
                selection, preference_warning = self._world_script_split_model_preference(
                    int(user_id), int(world_id)
                )

            if explicit_model or not existing_selection:
                existing_config["selectedScriptSplitLlmModel"] = selection
                StoryboardModel.update(
                    int(_get_field(existing, "id")), config_json=existing_config
                )
            if explicit_model:
                preference_saved, preference_warning = self._save_world_script_split_model_preference(
                    int(user_id), int(world_id), selection
                )

            result = {
                "success": True,
                "storyboard_id": int(_get_field(existing, "id")),
                "script_id": int(script_id),
                "created": False,
                "storyboard": _to_dict(existing),
            }
            if preference_saved is not None:
                result["preference_saved"] = preference_saved
            if preference_warning:
                result["warning"] = preference_warning
            return result

        selection, preference_warning = self._world_script_split_model_preference(
            int(user_id), int(world_id)
        )
        if explicit_model:
            selection = self._normalize_script_split_model_selection(
                model, model_id=model_id, vendor_id=vendor_id
            )

        # 画幅：从同世界已有集继承（优先第 1 集），再兜底 16:9。
        # ⚠️ style / style_reference_image / composition_preference / workflow_ratio
        # 均不从命令入参获取——前两者由 StoryboardModel.create 内部从世界表
        # 继承（world.visual_style / world.composition_preference），保证同世界画风一致。
        ratio_resolver = getattr(StoryboardModel, 'resolve_inherited_workflow_ratio', None)
        inherited = (
            ratio_resolver(int(user_id), int(world_id))
            if callable(ratio_resolver)
            else None
        ) or {}
        effective_ratio = (str(inherited.get("workflow_ratio") or "").strip() or None) or "16:9"

        storyboard_id = StoryboardModel.create(
            user_id=int(user_id),
            world_id=int(world_id),
            episode_number=episode_number,
            workflow_id=workflow_id,
            script_id=int(script_id),
            title=title if title is not None else (_get_field(script, "title") or ""),
            workflow_ratio=effective_ratio,
            version=version,
            config_json={"selectedScriptSplitLlmModel": selection},
        )
        if explicit_model:
            preference_saved, preference_warning = self._save_world_script_split_model_preference(
                int(user_id), int(world_id), selection
            )
        storyboard = StoryboardModel.get_by_id(int(storyboard_id))
        result = {
            "success": True,
            "storyboard_id": int(storyboard_id),
            "script_id": int(script_id),
            "created": True,
            "storyboard": _to_dict(storyboard) if storyboard else {"id": int(storyboard_id)},
        }
        if preference_saved is not None:
            result["preference_saved"] = preference_saved
        if preference_warning:
            result["warning"] = preference_warning
        return result

    def scene_context(self, scene_id: int, user_id: Optional[int] = None) -> Dict[str, Any]:
        scene, storyboard = self._load_scene_pair(scene_id)
        prompt_json = _parse_json(_get_field(scene, "prompt_json"), {}) or {}
        video_config = _parse_json(_get_field(scene, "video_config_json"), {}) or {}
        dialogues = StoryboardDialogueModel.list_by_scene(int(scene_id)) or []

        world_id = _get_field(storyboard, "world_id")
        video_prompt_raw = _get_field(scene, "video_prompt") or ""
        # 角色参考以提示词【【名】】为真源：每个标记独立查世界库（含用户后加的新引用）。
        # 对白角色仍合并进 characters 供上下文展示，但不单独扩展参考图。
        characters = self._merge_named_items(
            self._load_dialogue_characters(dialogues),
            self._resolve_prompt_characters(
                prompt_json, world_id, scene=scene, video_prompt=video_prompt_raw
            ),
        )
        location = self._resolve_location(prompt_json)
        props = self._resolve_props(prompt_json, world_id, scene=scene)
        selected_assets = self._selected_assets(scene)

        image_prompt = self._compose_image_prompt(scene, storyboard, prompt_json, characters, location, props)
        video_prompt = video_prompt_raw or image_prompt
        reference_image_items = self._collect_reference_image_items(
            prompt_json,
            video_prompt,
            characters,
            location,
            props,
            world_id=world_id,
        )
        reference_images = reference_urls(reference_image_items)

        return {
            "success": True,
            "scene": _to_dict(scene),
            "storyboard": _to_dict(storyboard),
            "dialogues": dialogues,
            "characters": characters,
            "location": location,
            "props": props,
            "prompt_json": prompt_json,
            "video_config_json": video_config,
            "image_prompt": image_prompt,
            "video_prompt": video_prompt,
            "selected_assets": selected_assets,
            "reference_images": reference_images,
            "reference_image_items": reference_image_items,
            "user_id": user_id,
        }

    def generate_image(
        self,
        scene_id: int,
        user_id: int,
        *,
        auth_token: str = "",
        mode: str = "auto",
        asset_type: str = "first_frame",
        prompt: Optional[str] = None,
        source_image: Optional[str] = None,
        ratio: Optional[str] = None,
        image_size: Optional[str] = None,
        count: int = 1,
        sequence_mode: Optional[str] = None,
        force_bypass: bool = False,
        select_result: bool = True,
        task_type: Optional[int] = None,
        generation_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
        preference_surface: str = MediaGenerationSurface.STORYBOARD_CLI,
    ) -> Dict[str, Any]:
        if mode not in VALID_IMAGE_MODES:
            raise StoryboardCliError("invalid_mode", f"invalid image mode: {mode}")
        if asset_type not in IMAGE_ASSET_TYPES:
            raise StoryboardCliError("invalid_asset_type", "image asset_type must be first_frame or last_frame")

        context = self.scene_context(scene_id, user_id=user_id)
        storyboard = context["storyboard"]
        world_id = str(storyboard.get("world_id") or "")
        prompt_text = prompt or context["image_prompt"]
        ratio_value = ratio or storyboard.get("workflow_ratio") or "16:9"
        reference_items = context.get("reference_image_items") or []
        reference_urls = [item["url"] for item in reference_items if item.get("url")]

        # 外部 location grid readiness check（Phase 6）：
        # 若当前 scene 引用的子场景 location.reference_image 缺失，按 sequence_mode 决定是否阻止：
        #   - quality（效果模式）：严格阻止，等待九宫格完成（缺图+无运行中任务也阻止，强制保证质量）
        #   - balanced/speed（均衡/速度模式）：仅在九宫格任务运行中时等待；缺图+无任务则放行走 t2i 兜底
        self._check_location_grid_readiness(context, sequence_mode=sequence_mode, force_bypass=force_bypass)

        if mode == "auto":
            mode = "image_edit" if reference_urls else "text_to_image"

        if not generation_snapshots:
            generation_snapshots = _build_cli_generation_snapshots(
                int(user_id),
                int(world_id),
                media_type=MediaGenerationType.IMAGE,
                modes=[mode],
                explicit_task_id=task_type,
                profile_values={'ratio': ratio_value},
                surface=preference_surface,
            )
        generation_snapshot = None
        if generation_snapshots:
            slot_key = MediaGenerationPreferenceService.slot_key(
                MediaGenerationType.IMAGE, mode
            )
            generation_snapshot = generation_snapshots.get(slot_key)
            if not generation_snapshot:
                raise StoryboardCliError(
                    'MODEL_MODE_UNSUPPORTED',
                    f'批次快照未锁定图片模式 {mode}',
                )

        from script_writer_core.mcp_tool import scoped_image_generation_snapshot
        with scoped_image_generation_snapshot(generation_snapshot):
            if mode == "text_to_image":
                prompt_text = append_storyboard_visual_suffix(
                    prompt_text,
                    style=storyboard.get("style"),
                    composition_preference=storyboard.get("composition_preference"),
                )
                result = self.submitter.text_to_image(
                    user_id=str(user_id),
                    world_id=world_id,
                    auth_token=auth_token or "",
                    prompt=prompt_text,
                    aspect_ratio=ratio_value,
                    count=int(count or 1),
                    image_size=image_size,
                    task_type=(generation_snapshot or {}).get('task_id'),
                )
            else:
                image_urls = self._resolve_image_edit_urls(context, source_image, reference_urls)
                prompt_text = self._append_reference_prompt_suffix(
                    prompt_text,
                    self._with_source_image_legend(reference_items, context, source_image),
                )
                prompt_text = append_storyboard_visual_suffix(
                    prompt_text,
                    style=storyboard.get("style"),
                    composition_preference=storyboard.get("composition_preference"),
                )
                result = self.submitter.image_edit(
                    user_id=str(user_id),
                    world_id=world_id,
                    auth_token=auth_token or "",
                    prompt=prompt_text,
                    image_url=",".join(image_urls),
                    aspect_ratio=ratio_value,
                    count=int(count or 1),
                    image_size=image_size,
                    task_type=(generation_snapshot or {}).get('task_id'),
                )

        return self._finalize_submission(
            scene_id=scene_id,
            user_id=user_id,
            asset_type=asset_type,
            mode=mode,
            result=result,
            reference_images=reference_urls if mode == "image_edit" else [],
            select_result=select_result,
        )

    def generate_video(
        self,
        scene_id: int,
        user_id: int,
        *,
        auth_token: str = "",
        mode: str = "image_to_video",
        prompt: Optional[str] = None,
        ratio: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        count: int = 1,
        image_mode: str = "first_last_frame",
        image_urls: Optional[str] = None,
        video_urls: Optional[str] = None,
        audio_urls: Optional[str] = None,
        task_type: Optional[int] = None,
        generation_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
        preference_surface: str = MediaGenerationSurface.STORYBOARD_CLI,
    ) -> Dict[str, Any]:
        if mode not in VALID_VIDEO_MODES:
            raise StoryboardCliError("invalid_mode", f"invalid video mode: {mode}")

        context = self.scene_context(scene_id, user_id=user_id)
        scene = context["scene"]
        storyboard = context["storyboard"]
        video_type = str(scene.get("video_type") or SceneVideoType.VIDEO)

        # 对口型：双模型路由（Wan2.2 / LTX2.3），统一编排 + 按实际模型扣费。
        # 忽略调用方传入的 prompt / duration / ratio（以服务端规划为准）。
        if video_type == SceneVideoType.DIGITAL_HUMAN:
            from services.storyboard_digital_human_service import (
                StoryboardDigitalHumanError,
                deduct_computing_power_sync,
                compute_digital_human_power,
                orchestrate_digital_human_generation,
                submit_digital_human_plan,
            )
            # CLI 必须携带可用 auth_token；缺少计费身份时拒绝提交，不再免费建单。
            normalized_token = str(auth_token or "").strip()
            if not normalized_token:
                raise StoryboardCliError(
                    "missing_auth_token",
                    "数字人生成需要 auth_token 以扣除算力，缺少计费身份时拒绝提交",
                )
            try:
                plan, _segments, _scene, _sb = orchestrate_digital_human_generation(int(scene_id))
            except StoryboardDigitalHumanError as exc:
                raise StoryboardCliError(exc.code, exc.message, payload=exc.payload) from exc

            computing_power = compute_digital_human_power(plan)
            transaction_id = str(uuid.uuid4())
            ok, msg = deduct_computing_power_sync(normalized_token, computing_power, transaction_id)
            if not ok:
                raise StoryboardCliError("deduct_failed", msg or "算力不足或扣费失败")

            try:
                dh_result = submit_digital_human_plan(
                    plan,
                    scene_id=int(scene_id),
                    user_id=int(user_id),
                    transaction_id=transaction_id,
                    computing_power=computing_power,
                )
            except StoryboardDigitalHumanError as exc:
                raise StoryboardCliError(exc.code, exc.message, payload=exc.payload) from exc
            return {
                "success": True,
                "scene_id": int(scene_id),
                "video_type": SceneVideoType.DIGITAL_HUMAN,
                "project_ids": [dh_result["ai_tool_id"]] if dh_result.get("ai_tool_id") else [],
                "asset_ids": [dh_result["asset_id"]] if dh_result.get("asset_id") else [],
                "selected_asset_id": dh_result.get("asset_id"),
                "task_type": dh_result.get("task_type"),
                "model_used": dh_result.get("model_used"),
                "routing_reason": dh_result.get("routing_reason"),
                "speech_duration": dh_result.get("speech_duration"),
                "status": dh_result.get("status") or "submitted",
                **{k: v for k, v in dh_result.items() if k not in ("success",)},
            }

        world_id = str(storyboard.get("world_id") or "")
        prompt_text = prompt or context["video_prompt"] or context["image_prompt"]
        ratio_value = ratio or storyboard.get("workflow_ratio") or "16:9"
        # scene.duration 现为 DECIMAL(10,3) 浮点（音频求和同步）。视频后端要求整数秒，
        # 用 ceil 向上取整，确保视频时长不短于音频（避免丢帧/音画不同步）；下限 1 秒。
        duration_value = max(1, math.ceil(float(duration_seconds or scene.get("duration") or 5)))

        actual_media_mode = MediaGenerationPreferenceService.determine_mode(
            MediaGenerationType.VIDEO,
            image_urls=(image_urls or self._resolve_video_image_urls(context, image_mode)) if mode != 'text_to_video' else None,
            video_urls=video_urls,
            audio_urls=audio_urls,
            image_mode=image_mode if mode != 'text_to_video' else None,
        )
        if not generation_snapshots:
            generation_snapshots = _build_cli_generation_snapshots(
                int(user_id),
                int(world_id),
                media_type=MediaGenerationType.VIDEO,
                modes=[actual_media_mode],
                explicit_task_id=task_type,
                profile_values={
                    'ratio': ratio_value,
                    'duration_seconds': duration_value,
                    'image_mode': image_mode if mode != 'text_to_video' else None,
                },
                surface=preference_surface,
            )
        generation_snapshot = None
        if generation_snapshots:
            generation_snapshot = generation_snapshots.get(
                MediaGenerationPreferenceService.slot_key(
                    MediaGenerationType.VIDEO, actual_media_mode
                )
            )
            if not generation_snapshot:
                raise StoryboardCliError(
                    'MODEL_MODE_UNSUPPORTED',
                    f'批次快照未锁定视频模式 {actual_media_mode}',
                )
            task_type = int(generation_snapshot['task_id'])

        from script_writer_core.mcp_tool import scoped_video_preferences
        with scoped_video_preferences(generation_snapshot):
            if mode == "text_to_video":
                result = self.submitter.text_to_video(
                    user_id=str(user_id),
                    world_id=world_id,
                    auth_token=auth_token or "",
                    prompt=prompt_text,
                    ratio=ratio_value,
                    duration_seconds=duration_value,
                    count=int(count or 1),
                    task_type=task_type,
                )
            else:
                resolved_image_urls = image_urls or self._resolve_video_image_urls(context, image_mode)
                result = self.submitter.image_to_video(
                    user_id=str(user_id),
                    world_id=world_id,
                    auth_token=auth_token or "",
                    prompt=prompt_text,
                    image_urls=resolved_image_urls,
                    ratio=ratio_value,
                    duration_seconds=duration_value,
                    count=int(count or 1),
                    image_mode=image_mode,
                    video_urls=video_urls,
                    audio_urls=audio_urls,
                    task_type=task_type,
                )

        return self._finalize_submission(
            scene_id=scene_id,
            user_id=user_id,
            asset_type="video",
            mode=mode,
            result=result,
        )

    def bind_projects(
        self,
        scene_id: int,
        user_id: Optional[int],
        asset_type: str,
        project_ids: Sequence[int],
        select_result: bool = True,
    ) -> Dict[str, Any]:
        if asset_type not in VALID_ASSET_TYPES:
            raise StoryboardCliError("invalid_asset_type", f"invalid asset_type: {asset_type}")
        if not project_ids:
            raise StoryboardCliError("missing_project_ids", "project_ids is empty")

        asset_ids: List[int] = []
        for project_id in project_ids:
            asset_id = StoryboardSceneAssetModel.create(
                scene_id=int(scene_id),
                asset_type=asset_type,
                ai_tool_id=int(project_id),
            )
            asset_ids.append(int(asset_id))

        selected_asset_id = asset_ids[0]
        if select_result:
            StoryboardSceneAssetModel.set_selected(int(scene_id), asset_type, selected_asset_id)
        if user_id is not None:
            StoryboardSceneModel.update(int(scene_id), last_modified_user_id=int(user_id))

        return {
            "asset_ids": asset_ids,
            "selected_asset_id": selected_asset_id,
            "asset_type": asset_type,
        }

    def task_status(
        self,
        scene_id: int,
        *,
        asset_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        context = self.scene_context(scene_id)
        selected = context["selected_assets"]
        if asset_type:
            if asset_type not in VALID_ASSET_TYPES:
                raise StoryboardCliError("invalid_asset_type", f"invalid asset_type: {asset_type}")
            selected = {asset_type: selected.get(asset_type)}
        return {"success": True, "scene_id": int(scene_id), "selected_assets": selected}

    def list_scenes(
        self,
        storyboard_id: int,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        storyboard = self._ensure_storyboard_for_user(storyboard_id, user_id)
        scenes = StoryboardSceneModel.list_by_storyboard(int(storyboard_id)) or []
        summaries = [self._scene_summary(scene, index=index) for index, scene in enumerate(scenes, start=1)]
        return {
            "success": True,
            "storyboard_id": int(storyboard_id),
            "user_id": user_id,
            "storyboard": _to_dict(storyboard),
            "scene_count": len(summaries),
            "scenes": summaries,
        }

    def insert_scene(
        self,
        storyboard_id: int,
        user_id: int,
        *,
        after_scene_id: Optional[int] = None,
        before_scene_id: Optional[int] = None,
        prev_id: Optional[int] = None,
        next_id: Optional[int] = None,
        title: str = "",
        duration: float = 5,
        prompt_json: Optional[Any] = None,
        video_prompt: Optional[str] = None,
        video_type: str = SceneVideoType.VIDEO,
        video_config_json: Optional[Any] = None,
        audio_embedded: Optional[bool] = None,
        difficulty: str = SceneDifficulty.MEDIUM,
        act_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        user_id = self._require_user_id(user_id)
        self._ensure_storyboard_for_user(storyboard_id, user_id)

        prev_scene_id = int(prev_id or after_scene_id or 0) or None
        next_scene_id = int(next_id or before_scene_id or 0) or None
        ordered_scenes = StoryboardSceneModel.list_by_storyboard(int(storyboard_id)) or []

        prev_scene_id, next_scene_id = self._resolve_insert_neighbors(
            storyboard_id=int(storyboard_id),
            scenes=ordered_scenes,
            prev_scene_id=prev_scene_id,
            next_scene_id=next_scene_id,
        )
        sort_order = self._compute_scene_insert_sort(int(storyboard_id), prev_scene_id, next_scene_id)
        prompt_payload = self._json_dict_param(prompt_json, "prompt_json")
        video_config_payload = self._json_dict_param(video_config_json, "video_config_json")

        scene_id = StoryboardSceneModel.create(
            storyboard_id=int(storyboard_id),
            sort_order=sort_order,
            title=title or "",
            duration=float(duration or 5),
            prompt_json=prompt_payload,
            video_prompt=video_prompt,
            video_type=video_type or SceneVideoType.VIDEO,
            video_config_json=video_config_payload,
            audio_embedded=audio_embedded,
            difficulty=difficulty,
            act_name=act_name,
            last_modified_user_id=int(user_id),
        )
        scene = StoryboardSceneModel.get_by_id(int(scene_id))
        return {
            "success": True,
            "storyboard_id": int(storyboard_id),
            "scene_id": int(scene_id),
            "insert": {
                "prev_id": prev_scene_id,
                "next_id": next_scene_id,
                "sort_order": sort_order,
            },
            "scene": _to_dict(scene) if scene else {"id": int(scene_id)},
        }

    def update_scene(
        self,
        scene_id: int,
        user_id: int,
        *,
        duration: Optional[float] = None,
        title: Optional[str] = None,
        prompt_json: Optional[Any] = None,
        video_prompt: Optional[str] = None,
        video_type: Optional[str] = None,
        video_config_json: Optional[Any] = None,
        audio_embedded: Optional[bool] = None,
        difficulty: Optional[str] = None,
        act_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update editable fields of an existing scene.

        All keyword args default to None and are skipped when None, so callers can
        patch a single field (e.g. duration) without touching the others. Only
        duration / title / prompt_json / video_prompt / video_type /
        video_config_json / audio_embedded / difficulty / act_name are mutable here;
        selected asset pointers stay under bind-projects / asset select endpoints.
        When duration changes, the storyboard's total_duration is recomputed to stay
        consistent.
        """
        user_id = self._require_user_id(user_id)
        scene, storyboard = self._load_scene_pair(scene_id)
        storyboard_id = int(_get_field(storyboard, "id"))
        self._ensure_storyboard_for_user(storyboard_id, user_id)

        update_fields: Dict[str, Any] = {}
        if duration is not None:
            update_fields["duration"] = max(1.0, float(duration))
        if title is not None:
            update_fields["title"] = str(title or "")
        if prompt_json is not None:
            update_fields["prompt_json"] = self._json_dict_param(prompt_json, "prompt_json")
        if video_prompt is not None:
            update_fields["video_prompt"] = str(video_prompt or "")
        if video_type is not None:
            update_fields["video_type"] = video_type or SceneVideoType.VIDEO
        if video_config_json is not None:
            update_fields["video_config_json"] = self._json_dict_param(video_config_json, "video_config_json")
        if audio_embedded is not None:
            update_fields["audio_embedded"] = bool(audio_embedded)
        if difficulty is not None:
            update_fields["difficulty"] = SceneDifficulty.normalize(difficulty)
        if act_name is not None:
            update_fields["act_name"] = str(act_name).strip() or None

        if not update_fields:
            raise StoryboardCliError("missing_parameter", "no updatable fields provided")

        update_fields["last_modified_user_id"] = int(user_id)
        affected = StoryboardSceneModel.update(int(scene_id), **update_fields)

        total_duration = _get_field(storyboard, "total_duration")
        if "duration" in update_fields:
            total_duration = StoryboardModel.recalc_total_duration(storyboard_id)

        updated_scene = StoryboardSceneModel.get_by_id(int(scene_id))
        return {
            "success": True,
            "scene_id": int(scene_id),
            "storyboard_id": storyboard_id,
            "affected": affected,
            "scene": _to_dict(updated_scene) if updated_scene else {"id": int(scene_id)},
            "total_duration": total_duration,
        }

    def storyboard_task_status(
        self,
        storyboard_id: int,
        user_id: Optional[int] = None,
        *,
        asset_type: Optional[str] = StoryboardAutoGenerateConstants.DEFAULT_ASSET_TYPE,
    ) -> Dict[str, Any]:
        if asset_type and asset_type not in VALID_ASSET_TYPES:
            raise StoryboardCliError("invalid_asset_type", f"invalid asset_type: {asset_type}")

        storyboard = StoryboardModel.get_by_id(int(storyboard_id))
        if not storyboard:
            raise StoryboardCliError("not_found", f"storyboard not found: {storyboard_id}")

        scenes = StoryboardSceneModel.list_by_storyboard(int(storyboard_id)) or []
        items: List[Dict[str, Any]] = []
        for scene in scenes:
            selected_assets = self._selected_assets(scene)
            item = {
                "scene_id": int(_get_field(scene, "id")),
                "title": _get_field(scene, "title") or "",
                "sort_order": _get_field(scene, "sort_order"),
                "selected_assets": selected_assets,
            }
            if asset_type:
                item[asset_type] = selected_assets.get(asset_type)
            items.append(item)

        return {
            "success": True,
            "storyboard_id": int(storyboard_id),
            "user_id": user_id,
            "asset_type": asset_type,
            "scene_count": len(items),
            "scenes": items,
        }

    def auto_generate_missing_images(
        self,
        storyboard_id: int,
        user_id: int,
        *,
        auth_token: str = "",
        asset_type: str = StoryboardAutoGenerateConstants.DEFAULT_ASSET_TYPE,
        mode: str = "auto",
        prompt: Optional[str] = None,
        source_image: Optional[str] = None,
        ratio: Optional[str] = None,
        image_size: Optional[str] = None,
        count: int = 1,
        limit: Optional[int] = None,
        stop_on_error: bool = True,
        task_type: Optional[int] = None,
        sequence_mode: Optional[str] = None,
        scene_ids: Optional[Sequence[int]] = None,
        existing_policy: str = StoryboardAutoGenerateConstants.IMAGE_EXISTING_POLICY_SKIP,
    ) -> Dict[str, Any]:
        if not int(user_id or 0):
            raise StoryboardCliError("missing_user_id", "user_id is required")
        if not str(auth_token or "").strip():
            raise StoryboardCliError("missing_auth_token", "auth_token is required")
        if mode not in VALID_IMAGE_MODES:
            raise StoryboardCliError("invalid_mode", f"invalid image mode: {mode}")
        if asset_type not in IMAGE_ASSET_TYPES:
            raise StoryboardCliError("invalid_asset_type", "image asset_type must be first_frame or last_frame")
        sequence_mode = self._normalize_sequence_mode(sequence_mode)
        if (
            sequence_mode == StoryboardAutoGenerateConstants.SEQUENCE_MODE_QUALITY
            and Edition.is_community()
        ):
            raise StoryboardCliError(
                "enterprise_only",
                "效果模式仅商业版支持，请购买商业版后使用",
            )

        storyboard = StoryboardModel.get_by_id(int(storyboard_id))
        if not storyboard:
            raise StoryboardCliError("not_found", f"storyboard not found: {storyboard_id}")
        requested_scene_ids = self._normalize_requested_scene_ids(
            int(storyboard_id), scene_ids
        )
        existing_policy = str(existing_policy or "").strip().lower()
        if existing_policy not in StoryboardAutoGenerateConstants.VALID_IMAGE_EXISTING_POLICIES:
            raise StoryboardCliError(
                "invalid_existing_policy",
                f"invalid image existing_policy: {existing_policy}",
            )
        if (
            existing_policy == StoryboardAutoGenerateConstants.IMAGE_EXISTING_POLICY_REGENERATE
            and requested_scene_ids is None
        ):
            raise StoryboardCliError(
                "scene_ids_required",
                "scene_ids is required when existing_policy is regenerate",
            )

        task_type = self._resolve_image_task_type(storyboard, task_type)

        batch_limit = self._normalize_batch_limit(limit)
        effective_ratio = ratio or _get_field(storyboard, "workflow_ratio")
        requested_snapshot_modes = {
            'text_to_image': [MediaGenerationMode.TEXT_TO_IMAGE],
            'image_edit': [MediaGenerationMode.IMAGE_EDIT],
            'auto': [MediaGenerationMode.TEXT_TO_IMAGE, MediaGenerationMode.IMAGE_EDIT],
        }[mode]
        generation_snapshots = _build_cli_generation_snapshots(
            int(user_id),
            int(_get_field(storyboard, 'world_id')),
            media_type=MediaGenerationType.IMAGE,
            modes=requested_snapshot_modes,
            explicit_task_id=task_type,
            profile_values={'ratio': effective_ratio, 'resolution': image_size},
        )
        idempotency_payload = self._image_batch_idempotency_payload(
            storyboard_id=int(storyboard_id),
            user_id=int(user_id),
            asset_type=asset_type,
            sequence_mode=sequence_mode,
            mode=mode,
            task_type=task_type,
            ratio=effective_ratio,
            image_size=image_size,
            count=int(count or 1),
            limit=batch_limit,
            prompt=prompt,
            source_image=source_image,
            stop_on_error=bool(stop_on_error),
            scene_ids=requested_scene_ids,
            existing_policy=existing_policy,
        )
        idempotency_key = self._image_batch_idempotency_key(idempotency_payload)
        with _IMAGE_BATCH_CREATE_LOCK:
            existing_status = self._active_image_batch_status_for_request(
                storyboard_id=int(storyboard_id),
                asset_type=asset_type,
                idempotency_key=idempotency_key,
            )
            if existing_status:
                return existing_status

        planned_items = self._plan_image_batch_items(
            storyboard_id=int(storyboard_id),
            asset_type=asset_type,
            sequence_mode=sequence_mode,
            limit=batch_limit,
            scene_ids=requested_scene_ids,
            existing_policy=existing_policy,
        )
        is_quality_first_frame = (
            sequence_mode == StoryboardAutoGenerateConstants.SEQUENCE_MODE_QUALITY
            and asset_type == "first_frame"
        )
        if is_quality_first_frame:
            self._require_quality_location_references(
                storyboard_id=int(storyboard_id),
                world_id=int(_get_field(storyboard, "world_id")),
                user_id=int(user_id),
                auth_token=auth_token,
                scenes=StoryboardSceneModel.list_by_storyboard(int(storyboard_id)) or [],
                planned_items=planned_items,
                allow_submit=True,
            )

        with _IMAGE_BATCH_CREATE_LOCK:
            existing_status = self._active_image_batch_status_for_request(
                storyboard_id=int(storyboard_id),
                asset_type=asset_type,
                idempotency_key=idempotency_key,
            )
            if existing_status:
                return existing_status
            planned_items = self._plan_image_batch_items(
                storyboard_id=int(storyboard_id),
                asset_type=asset_type,
                sequence_mode=sequence_mode,
                limit=batch_limit,
                scene_ids=requested_scene_ids,
                existing_policy=existing_policy,
            )
            if is_quality_first_frame:
                # 真正建 batch 前在锁内只读复检；禁止在全局锁内提交外部宫格任务。
                self._require_quality_location_references(
                    storyboard_id=int(storyboard_id),
                    world_id=int(_get_field(storyboard, "world_id")),
                    user_id=int(user_id),
                    auth_token=auth_token,
                    scenes=StoryboardSceneModel.list_by_storyboard(int(storyboard_id)) or [],
                    planned_items=planned_items,
                    allow_submit=False,
                )
            job_id = StoryboardImageBatchJobModel.create(
                storyboard_id=int(storyboard_id),
                user_id=int(user_id),
                auth_token=auth_token,
                asset_type=asset_type,
                sequence_mode=sequence_mode,
                mode=mode,
                prompt=prompt,
                source_image=source_image,
                ratio=effective_ratio,
                image_size=image_size,
                count=int(count or 1),
                limit_count=batch_limit,
                stop_on_error=1 if stop_on_error else 0,
                status=StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_PENDING,
                extra_json={
                    "task_type": task_type,
                    "generation_snapshots": generation_snapshots,
                    "idempotency_key": idempotency_key,
                    "idempotency_payload": idempotency_payload,
                    "requested_scene_ids": requested_scene_ids,
                    "existing_policy": existing_policy,
                },
            )
        scene_to_item_id: Dict[int, int] = {}
        created_items: List[Dict[str, Any]] = []
        for item in planned_items:
            dependency_item_id = scene_to_item_id.get(item.get("dependency_scene_id"))
            item_id = StoryboardImageBatchItemModel.create(
                job_id=job_id,
                storyboard_id=int(storyboard_id),
                scene_id=item["scene_id"],
                asset_type=asset_type,
                group_key=item.get("group_key"),
                order_index=item.get("order_index") or 0,
                dependency_item_id=dependency_item_id,
                status=item.get("batch_status"),
                ai_tool_id=item.get("ai_tool_id"),
                asset_id=item.get("asset_id"),
                project_ids=item.get("project_ids") or [],
                result_url=item.get("result_url"),
                extra_json={
                    "title": item.get("title") or "",
                    "sort_order": item.get("sort_order"),
                    "plan_status": item.get("status"),
                    "dependency_scene_id": item.get("dependency_scene_id"),
                    "existing_policy": existing_policy,
                    "base_asset_id": item.get("base_asset_id"),
                    "generation_snapshots": generation_snapshots,
                },
            )
            scene_to_item_id[item["scene_id"]] = item_id
            created_items.append({**item, "id": item_id, "dependency_item_id": dependency_item_id})
            logger.info(
                "[batch-create] job=%s item=%s scene=%s status=%s dep_scene=%s dep_item=%s resolved=%s",
                job_id, item_id, item["scene_id"], item.get("status"),
                item.get("dependency_scene_id"), dependency_item_id,
                bool(dependency_item_id) if item.get("dependency_scene_id") else "N/A",
            )

        # 不在此处同步推进 batch：交由调度器 process_storyboard_image_batch_tasks
        # 统一处理，避免「同步流 + 调度器流」并发重复提交同一 pending item
        # （曾导致同一分镜生成两条提示词完全相同的 ai_tools 记录）。
        # 前端通过 pollImageBatchStatus(batch_id) 持续轮询进度即可。
        #
        # 但 submitted_count 必须在此时一次性写入「计划待生成数」，与状态查询同源，
        # 否则提交响应恒为 0、轮询返回中间值、完成返回终值，会出现 0→N→M 的跳变。
        self._persist_image_batch_planned_counts(job_id)
        status = self.storyboard_image_batch_status(job_id=job_id)

        return {
            "success": True,
            "storyboard_id": int(storyboard_id),
            "user_id": int(user_id),
            "asset_type": asset_type,
            "sequence_mode": sequence_mode,
            "existing_policy": existing_policy,
            "batch_id": job_id,
            "limit": batch_limit,
            "submitted_count": status.get("submitted_count", 0),
            "skipped_count": status.get("skipped_count", 0),
            "failed_count": status.get("failed_count", 0),
            "regenerated_count": status.get("regenerated_count", 0),
            "reused_count": status.get("reused_count", 0),
            "status": status.get("status"),
            "items": status.get("items", created_items),
        }

    def _require_quality_location_references(
        self,
        *,
        storyboard_id: int,
        world_id: int,
        user_id: int,
        auth_token: str,
        scenes: Sequence[Any],
        planned_items: Sequence[Dict[str, Any]],
        allow_submit: bool,
    ) -> None:
        result = get_storyboard_quality_location_reference_coordinator().preflight(
            storyboard_id=storyboard_id,
            world_id=world_id,
            user_id=user_id,
            auth_token=auth_token,
            scenes=scenes,
            planned_items=planned_items,
            allow_submit=allow_submit,
        )
        if result.get("status") == "ready":
            return
        error_code = str(
            result.get("error_code")
            or StoryboardAutoGenerateConstants.ERROR_WAITING_LOCATION_REFERENCES
        )
        raise StoryboardCliError(
            error_code,
            str(result.get("message") or "场景参考图尚未就绪"),
            payload={
                key: value
                for key, value in result.items()
                if key not in {"error_code", "message"}
            },
        )

    def auto_generate_missing_videos(
        self,
        storyboard_id: int,
        user_id: int,
        *,
        auth_token: str = "",
        limit: Optional[int] = None,
        stop_on_error: bool = False,
        task_type: Optional[int] = None,
        ratio: Optional[str] = None,
        sequence_mode: Optional[str] = None,
        image_mode: Optional[str] = None,
        scene_ids: Optional[Sequence[int]] = None,
        enable_face_mask: bool = False,
    ) -> Dict[str, Any]:
        """批量提交缺失分镜视频：复用 image batch 编排表，asset_type=video。

        仅处理「已有可用首帧、尚无完成视频」的分镜；无首帧的记为 skipped。
        sequence_mode 默认 speed（无串行依赖，可并行排队）。
        image_mode 默认 first_last_frame；支持 multi_reference（全能参考），后端自动用
        [选中首帧] + [角色/场景/道具参考图] + [全局画风参考图] 作为参考图集。
        enable_face_mask：Seedance 2.0 系列「是否处理人脸」，写入 generation snapshot。
        """
        if not int(user_id or 0):
            raise StoryboardCliError("missing_user_id", "user_id is required")
        if not str(auth_token or "").strip():
            raise StoryboardCliError("missing_auth_token", "auth_token is required")

        storyboard = StoryboardModel.get_by_id(int(storyboard_id))
        if not storyboard:
            raise StoryboardCliError("not_found", f"storyboard not found: {storyboard_id}")
        requested_scene_ids = self._normalize_requested_scene_ids(
            int(storyboard_id), scene_ids
        )

        asset_type = "video"
        sequence_mode = self._normalize_sequence_mode(
            sequence_mode or StoryboardAutoGenerateConstants.SEQUENCE_MODE_SPEED
        )
        image_mode = self._normalize_video_image_mode(image_mode)
        batch_limit = self._normalize_batch_limit(limit)
        effective_ratio = ratio or _get_field(storyboard, "workflow_ratio")
        # CLI 只使用显式 task_type 或 storyboard_cli 独立偏好，不读取项目/UI 配置。
        resolved_task_type = task_type
        media_mode = (
            MediaGenerationMode.REFERENCE_TO_VIDEO
            if image_mode in ('multi_reference', 'first_last_with_ref')
            else MediaGenerationMode.IMAGE_TO_VIDEO
        )
        generation_snapshots = _build_cli_generation_snapshots(
            int(user_id),
            int(_get_field(storyboard, 'world_id')),
            media_type=MediaGenerationType.VIDEO,
            modes=[media_mode],
            explicit_task_id=resolved_task_type,
            profile_values={
                'ratio': effective_ratio,
                'image_mode': image_mode,
                'enable_face_mask': bool(enable_face_mask),
            },
        )
        locked_snapshot = generation_snapshots[
            MediaGenerationPreferenceService.slot_key(MediaGenerationType.VIDEO, media_mode)
        ]
        resolved_task_type = int(locked_snapshot['task_id'])

        idempotency_payload = {
            "storyboard_id": int(storyboard_id),
            "user_id": int(user_id),
            "asset_type": asset_type,
            "sequence_mode": sequence_mode,
            "task_type": int(resolved_task_type) if resolved_task_type is not None else None,
            "ratio": str(effective_ratio or ""),
            "limit": batch_limit,
            "stop_on_error": bool(stop_on_error),
            "image_mode": image_mode,
            "enable_face_mask": bool(locked_snapshot.get('enable_face_mask', False)),
            "kind": "auto-video",
            "scene_ids": requested_scene_ids,
        }
        idempotency_key = self._image_batch_idempotency_key(idempotency_payload)
        with _IMAGE_BATCH_CREATE_LOCK:
            existing_status = self._active_image_batch_status_for_request(
                storyboard_id=int(storyboard_id),
                asset_type=asset_type,
                idempotency_key=idempotency_key,
            )
            if existing_status:
                return existing_status

            planned_items = self._plan_video_batch_items(
                storyboard_id=int(storyboard_id),
                limit=batch_limit,
                scene_ids=requested_scene_ids,
            )
            job_id = StoryboardImageBatchJobModel.create(
                storyboard_id=int(storyboard_id),
                user_id=int(user_id),
                auth_token=auth_token,
                asset_type=asset_type,
                sequence_mode=sequence_mode,
                mode="image_to_video",
                prompt=None,
                source_image=None,
                ratio=effective_ratio,
                image_size=None,
                count=1,
                limit_count=batch_limit,
                stop_on_error=1 if stop_on_error else 0,
                status=StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_PENDING,
                extra_json={
                    "task_type": resolved_task_type,
                    "generation_snapshots": generation_snapshots,
                    "image_mode": image_mode,
                    "idempotency_key": idempotency_key,
                    "idempotency_payload": idempotency_payload,
                    "kind": "auto-video",
                    "requested_scene_ids": requested_scene_ids,
                },
            )

        created_items: List[Dict[str, Any]] = []
        for item in planned_items:
            item_id = StoryboardImageBatchItemModel.create(
                job_id=job_id,
                storyboard_id=int(storyboard_id),
                scene_id=item["scene_id"],
                asset_type=asset_type,
                group_key=item.get("group_key"),
                order_index=item.get("order_index") or 0,
                dependency_item_id=None,
                status=item.get("batch_status"),
                ai_tool_id=item.get("ai_tool_id"),
                asset_id=item.get("asset_id"),
                project_ids=item.get("project_ids") or [],
                result_url=item.get("result_url"),
                extra_json={
                    "title": item.get("title") or "",
                    "sort_order": item.get("sort_order"),
                    "plan_status": item.get("status"),
                    "skip_reason": item.get("skip_reason") or "",
                    "generation_snapshots": generation_snapshots,
                },
            )
            created_items.append({**item, "id": item_id})

        # 同图片路径：submitted_count 一次性写入「计划待生成数」，与状态查询同源。
        self._persist_image_batch_planned_counts(job_id)
        status = self.storyboard_image_batch_status(job_id=job_id)
        return {
            "success": True,
            "storyboard_id": int(storyboard_id),
            "user_id": int(user_id),
            "asset_type": asset_type,
            "sequence_mode": sequence_mode,
            "batch_id": job_id,
            "limit": batch_limit,
            "submitted_count": status.get("submitted_count", 0),
            "skipped_count": status.get("skipped_count", 0),
            "failed_count": status.get("failed_count", 0),
            "status": status.get("status"),
            "items": status.get("items", created_items),
        }

    def _plan_video_batch_items(
        self,
        *,
        storyboard_id: int,
        limit: int,
        scene_ids: Optional[Sequence[int]] = None,
    ) -> List[Dict[str, Any]]:
        """规划缺失视频的分镜。

        - video：已有首帧且无完成视频 → pending
        - digital_human：已有成片配音 + 形象/首帧且无完成视频 → pending；缺配音 skip
        """
        from config.constant import StoryboardDigitalHumanConstants
        from services.storyboard_digital_human_service import plan_digital_human_ready

        scenes = StoryboardSceneModel.list_by_storyboard(int(storyboard_id)) or []
        requested = set(scene_ids) if scene_ids is not None else None
        items: List[Dict[str, Any]] = []
        missing_count = 0
        previous_group_key: Optional[str] = None

        for order_index, scene in enumerate(scenes, start=1):
            scene_id = int(_get_field(scene, "id"))
            group_key = self._scene_group_key(scene, previous_group_key, storyboard_id)
            previous_group_key = group_key
            if requested is not None and scene_id not in requested:
                continue
            selected_video = self._selected_asset_for_scene(scene, "video")
            first_frame = self._selected_asset_for_scene(scene, "first_frame")
            has_first = bool(first_frame and first_frame.get("result_url"))
            video_type = str(_get_field(scene, "video_type") or SceneVideoType.VIDEO)
            is_digital_human = video_type == SceneVideoType.DIGITAL_HUMAN
            status = "pending"
            batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING
            result_url = None
            asset_id = selected_video.get("id") if selected_video else None
            ai_tool_id = selected_video.get("ai_tool_id") if selected_video else None
            project_ids = [ai_tool_id] if ai_tool_id else []
            skip_reason = ""

            if selected_video and selected_video.get("result_url"):
                status = "already_ready"
                batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_COMPLETED
                result_url = selected_video.get("result_url")
            elif selected_video and selected_video.get("status") in StoryboardAutoGenerateConstants.RUNNING_STATUSES:
                status = "already_running"
                batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING
            elif not has_first:
                status = "missing_first_frame"
                batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_SKIPPED
                skip_reason = "missing_first_frame"
            elif is_digital_human:
                dh_status, dh_skip = plan_digital_human_ready(scene_id)
                if dh_status != "ready":
                    status = dh_status or "missing_audio"
                    batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_SKIPPED
                    skip_reason = dh_skip or StoryboardDigitalHumanConstants.SKIP_REASON_MISSING_AUDIO
                elif int(limit) > 0 and missing_count >= int(limit):
                    status = "limit_reached"
                    batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_SKIPPED
                    skip_reason = "limit_reached"
                else:
                    missing_count += 1
            elif int(limit) > 0 and missing_count >= int(limit):
                status = "limit_reached"
                batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_SKIPPED
                skip_reason = "limit_reached"
            else:
                missing_count += 1

            items.append({
                "scene_id": scene_id,
                "title": _get_field(scene, "title") or "",
                "sort_order": _get_field(scene, "sort_order"),
                "asset_type": "video",
                "video_type": video_type,
                "group_key": group_key,
                "order_index": order_index,
                "dependency_scene_id": None,
                "status": status,
                "batch_status": batch_status,
                "asset": selected_video,
                "asset_id": asset_id,
                "ai_tool_id": ai_tool_id,
                "project_ids": project_ids,
                "result_url": result_url,
                "skip_reason": skip_reason,
            })
        return items

    def _image_batch_idempotency_payload(
        self,
        *,
        storyboard_id: int,
        user_id: int,
        asset_type: str,
        sequence_mode: str,
        mode: str,
        task_type: Optional[int],
        ratio: Optional[str],
        image_size: Optional[str],
        count: int,
        limit: int,
        prompt: Optional[str],
        source_image: Optional[str],
        stop_on_error: bool,
        scene_ids: Optional[Sequence[int]] = None,
        existing_policy: str = StoryboardAutoGenerateConstants.IMAGE_EXISTING_POLICY_SKIP,
    ) -> Dict[str, Any]:
        return {
            "storyboard_id": int(storyboard_id),
            "user_id": int(user_id),
            "asset_type": asset_type,
            "sequence_mode": sequence_mode,
            "mode": mode,
            "task_type": int(task_type) if task_type is not None else None,
            "ratio": str(ratio or ""),
            "image_size": str(image_size or ""),
            "count": int(count or 1),
            "limit": int(limit),
            "prompt": str(prompt or ""),
            "source_image": str(source_image or ""),
            "stop_on_error": bool(stop_on_error),
            "scene_ids": list(scene_ids) if scene_ids is not None else None,
            "existing_policy": existing_policy,
        }

    def _image_batch_idempotency_key(self, payload: Dict[str, Any]) -> str:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return f"storyboard:auto-image:{digest}"

    def _active_image_batch_status_for_request(
        self,
        *,
        storyboard_id: int,
        asset_type: str,
        idempotency_key: str,
    ) -> Optional[Dict[str, Any]]:
        active_jobs = StoryboardImageBatchJobModel.list_active_by_storyboard(
            int(storyboard_id),
            asset_type=asset_type,
            limit=20,
        )
        if not active_jobs:
            return None

        for job in active_jobs:
            extra = job.get("extra_json") if isinstance(job.get("extra_json"), dict) else {}
            if extra.get("idempotency_key") == idempotency_key:
                status = self.storyboard_image_batch_status(job_id=int(job.get("id")))
                status["idempotent_reuse"] = True
                return status

        active = active_jobs[0]
        raise StoryboardCliError(
            "active_batch_exists",
            "当前故事板已有自动生成任务正在进行，请等待完成后再发起新的生成。",
            payload={
                "active_batch_id": active.get("id"),
                "active_storyboard_id": active.get("storyboard_id"),
                "active_asset_type": active.get("asset_type"),
                "active_sequence_mode": active.get("sequence_mode"),
                "active_status": self._batch_job_status_name(active.get("status")),
            },
        )

    def storyboard_image_batch_status(self, job_id: int, user_id: Optional[int] = None) -> Dict[str, Any]:
        job = StoryboardImageBatchJobModel.get_by_id(int(job_id))
        if not job:
            raise StoryboardCliError("not_found", f"storyboard image batch not found: {job_id}")
        if user_id and int(job.get("user_id") or 0) != int(user_id):
            raise StoryboardCliError("forbidden", "storyboard image batch does not belong to user")
        items = StoryboardImageBatchItemModel.list_by_job(int(job_id))
        counts = self._summarize_batch_items(items)
        total = counts["total"]
        completed = counts["completed"]
        progress = round(completed / total, 4) if total else 0
        return {
            "success": True,
            "batch_id": int(job_id),
            "storyboard_id": int(job.get("storyboard_id") or 0),
            "user_id": int(job.get("user_id") or 0),
            "asset_type": job.get("asset_type"),
            "sequence_mode": job.get("sequence_mode"),
            "existing_policy": (
                job.get("extra_json", {}).get("existing_policy")
                if isinstance(job.get("extra_json"), dict)
                else StoryboardAutoGenerateConstants.IMAGE_EXISTING_POLICY_SKIP
            ) or StoryboardAutoGenerateConstants.IMAGE_EXISTING_POLICY_SKIP,
            "status": self._batch_job_status_name(job.get("status")),
            "submitted_count": int(job.get("submitted_count") or 0),
            "completed_count": int(job.get("completed_count") or 0),
            "failed_count": int(job.get("failed_count") or 0),
            "skipped_count": int(job.get("skipped_count") or 0),
            "message": job.get("message") or "",
            # 聚合字段：实时遍历 items 统计，供调用方直接读取进度。
            # submitted_count 仍保留为「计划待生成数」，progress/pending/running/completed/
            # failed/skipped/total 反映当前 tick 的实际状态。
            "progress": progress,
            "total": total,
            "pending": counts["pending"],
            "running": counts["running"],
            "completed": counts["completed"],
            "failed": counts["failed"],
            "skipped": counts["skipped"],
            "regenerated_count": sum(
                1
                for item in items
                if isinstance(item.get("extra_json"), dict)
                and item["extra_json"].get("plan_status") == "regenerate_pending"
            ),
            "reused_count": sum(
                1
                for item in items
                if isinstance(item.get("extra_json"), dict)
                and item["extra_json"].get("plan_status") == "already_ready"
            ),
            "items": [self._batch_item_summary(item) for item in items],
        }

    def process_image_batch_jobs(
        self,
        *,
        job_id: Optional[int] = None,
        limit_jobs: Optional[int] = None,
    ) -> Dict[str, Any]:
        if job_id:
            job = StoryboardImageBatchJobModel.get_by_id(int(job_id))
            jobs = [job] if job else []
        else:
            jobs = StoryboardImageBatchJobModel.list_active(
                int(limit_jobs or StoryboardAutoGenerateConstants.BATCH_SCHEDULER_JOB_LIMIT)
            )

        submitted_count = 0
        processed_count = 0
        for job in jobs:
            if not job:
                continue
            result = self._process_one_image_batch_job(job)
            submitted_count += int(result.get("submitted_count") or 0)
            processed_count += 1
        return {
            "success": True,
            "processed_count": processed_count,
            "submitted_count": submitted_count,
        }

    def _parse_batch_item_time(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed

    def _fail_image_batch_item(
        self,
        item: Dict[str, Any],
        *,
        error_code: str,
        error_message: str,
        extra_json: Optional[Dict[str, Any]] = None,
    ) -> None:
        update_kwargs: Dict[str, Any] = {
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
            "error_code": error_code,
            "error_message": str(error_message or "generation failed")[:512],
        }
        if extra_json is not None:
            current_extra = item.get("extra_json") if isinstance(item.get("extra_json"), dict) else {}
            update_kwargs["extra_json"] = {**current_extra, **extra_json}
        StoryboardImageBatchItemModel.update(int(item["id"]), **update_kwargs)
        item.update(update_kwargs)

    def _select_completed_regeneration_asset(self, item: Dict[str, Any]) -> None:
        extra = item.get("extra_json") if isinstance(item.get("extra_json"), dict) else {}
        if extra.get("plan_status") != "regenerate_pending":
            return
        base_asset_id = extra.get("base_asset_id")
        generated_asset_id = item.get("asset_id")
        if base_asset_id in (None, "") or generated_asset_id in (None, ""):
            return
        scene = StoryboardSceneModel.get_by_id(int(item["scene_id"]))
        if not scene:
            return
        asset_type = item.get("asset_type") or StoryboardAutoGenerateConstants.DEFAULT_ASSET_TYPE
        current_asset_id = _get_field(scene, _asset_selected_field(asset_type))
        # 任务期间用户若切换到其它候选，完成回写不得覆盖用户选择。
        if str(current_asset_id) != str(base_asset_id):
            return
        StoryboardSceneAssetModel.set_selected(
            int(item["scene_id"]),
            asset_type,
            int(generated_asset_id),
        )

    def _complete_image_batch_item(self, item: Dict[str, Any], *, result_url: str) -> None:
        self._select_completed_regeneration_asset(item)
        StoryboardImageBatchItemModel.update(
            int(item["id"]),
            status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_COMPLETED,
            result_url=result_url,
        )
        item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_COMPLETED
        item["result_url"] = result_url

    def _reconcile_running_image_batch_items(self, job_id: int, items: List[Dict[str, Any]]) -> None:
        timeout_seconds = int(StoryboardAutoGenerateConstants.BATCH_RUNNING_ITEM_TIMEOUT_SECONDS)
        now = datetime.now()
        grid_failed_statuses = {
            GridImageTaskStatus.FAILED,
            GridImageTaskStatus.TIMEOUT,
            GridImageTaskStatus.CANCELLED,
            GridImageTaskStatus.DOWNLOAD_FAILED,
        }
        for item in items:
            if int(item.get("status") or 0) != StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING:
                continue

            asset = self._asset_info(item.get("asset_id")) if item.get("asset_id") else None
            if asset and asset.get("result_url"):
                self._complete_image_batch_item(item, result_url=asset.get("result_url"))
                continue
            if asset and int(asset.get("status") or 0) == -1:
                self._fail_image_batch_item(
                    item,
                    error_code="generation_failed",
                    error_message=asset.get("message") or "generation failed",
                )
                continue

            extra = item.get("extra_json") if isinstance(item.get("extra_json"), dict) else {}
            grid_task_id = extra.get("grid_task_id")
            if grid_task_id:
                try:
                    grid_task = GridImageTasksModel.get_by_id(int(grid_task_id))
                except Exception as exc:
                    logger.warning(
                        "[batch-reconcile] job=%s item=#%s scene=%s grid_task_id=%s query failed: %s",
                        job_id, item.get("id"), item.get("scene_id"), grid_task_id, exc,
                    )
                    grid_task = None
                if grid_task:
                    grid_status = int(_get_field(grid_task, "status", 0) or 0)
                    if grid_status in grid_failed_statuses:
                        self._fail_image_batch_item(
                            item,
                            error_code=StoryboardAutoGenerateConstants.ERROR_GRID_FIRST_FRAME_FAILED,
                            error_message=_get_field(grid_task, "error_message", None) or "grid image task failed",
                            extra_json={
                                "grid_task_status": grid_status,
                                "failure_source": "grid_task",
                            },
                        )
                        continue
                    if grid_status == GridImageTaskStatus.COMPLETED and int(_get_field(grid_task, "update_success", 0) or 0) != 1:
                        self._fail_image_batch_item(
                            item,
                            error_code=StoryboardAutoGenerateConstants.ERROR_GRID_FIRST_FRAME_FAILED,
                            error_message=_get_field(grid_task, "error_message", None) or "grid split/writeback failed",
                            extra_json={
                                "grid_task_status": grid_status,
                                "failure_source": "grid_task_writeback",
                            },
                        )
                        continue

            last_update = self._parse_batch_item_time(item.get("update_at") or item.get("updated_at") or item.get("create_at"))
            if last_update and (now - last_update).total_seconds() > timeout_seconds:
                self._fail_image_batch_item(
                    item,
                    error_code=StoryboardAutoGenerateConstants.ERROR_BATCH_ITEM_RUNNING_TIMEOUT,
                    error_message=f"batch item stayed running for more than {timeout_seconds} seconds",
                    extra_json={"failure_source": "batch_running_timeout"},
                )

    def _process_one_image_batch_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        job_id = int(job["id"])
        job_extra = job.get("extra_json") if isinstance(job.get("extra_json"), dict) else {}
        generation_snapshots = job_extra.get('generation_snapshots') or {}
        StoryboardImageBatchJobModel.update(job_id, status=StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_RUNNING)
        items = StoryboardImageBatchItemModel.list_by_job(job_id)
        self._reconcile_running_image_batch_items(job_id, items)
        asset_type = (job.get("asset_type") or StoryboardAutoGenerateConstants.DEFAULT_ASSET_TYPE)
        if asset_type == "video":
            return self._process_one_video_batch_job(job, items)
        if (
            StoryboardFeatureFlags.QUALITY_GRID_FIRST_FRAME_ENABLED
            and asset_type == "first_frame"
            and self._normalize_sequence_mode(job.get("sequence_mode")) == StoryboardAutoGenerateConstants.SEQUENCE_MODE_QUALITY
        ):
            return StoryboardFirstFrameGridService(
                counts_updater=self._update_image_batch_job_counts
            ).process_job(job)

        by_id = {int(item["id"]): item for item in items}
        submitted_count = 0

        # 诊断日志：本轮各 item 状态快照
        def _snapshot_part(it):
            dep = it.get("dependency_item_id")
            dep_str = f",dep=#{dep}" if dep else ""
            return f"#{it['id']}(s{it['scene_id']},{_batch_status_name(it.get('status'))}{dep_str})"
        snapshot = " ".join(_snapshot_part(it) for it in items)
        logger.info("[batch-tick] job=%s round items: %s", job_id, snapshot or "(empty)")

        for item in items:
            if int(item.get("status") or 0) != StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING:
                continue
            asset = self._asset_info(item.get("asset_id")) if item.get("asset_id") else None
            if asset and asset.get("result_url"):
                self._complete_image_batch_item(item, result_url=asset.get("result_url"))
            elif asset and asset.get("status") == -1:
                StoryboardImageBatchItemModel.update(
                    int(item["id"]),
                    status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
                    error_code="generation_failed",
                    error_message=asset.get("message") or "generation failed",
                )
                item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED

        for item in items:
            if int(item.get("status") or 0) != StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING:
                continue
            item_extra = item.get("extra_json") if isinstance(item.get("extra_json"), dict) else {}
            is_regeneration = item_extra.get("plan_status") == "regenerate_pending"
            dependency = by_id.get(int(item.get("dependency_item_id") or 0))
            reference_url = None
            reference_item_id = None
            if dependency:
                dep_status = int(dependency.get("status") or 0)
                if dep_status in (
                    StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
                    StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING,
                ):
                    logger.info(
                        "[batch-dep] item=#%s scene=%s dep=#%s dep_status=%s → skip (等待依赖完成)",
                        item["id"], item["scene_id"], dependency.get("id"), _batch_status_name(dep_status),
                    )
                    continue
                if dep_status == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED and int(job.get("stop_on_error") or 0):
                    logger.info(
                        "[batch-dep] item=#%s scene=%s dep=#%s dep_status=failed → mark dependency_failed",
                        item["id"], item["scene_id"], dependency.get("id"),
                    )
                    StoryboardImageBatchItemModel.update(
                        int(item["id"]),
                        status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
                        error_code="dependency_failed",
                        error_message="previous frame generation failed",
                    )
                    item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
                    continue
                reference_url = dependency.get("result_url")
                reference_item_id = dependency.get("id") if reference_url else None
                # 关键诊断：依赖已完成，但 result_url 是否真的有值
                if reference_url:
                    logger.info(
                        "[batch-dep] item=#%s scene=%s dep=#%s dep_status=%s dep_result_url=%s → reference_url=%s (将作为前一分镜)",
                        item["id"], item["scene_id"], dependency.get("id"), _batch_status_name(dep_status),
                        _url_preview(dependency.get("result_url")), _url_preview(reference_url),
                    )
                else:
                    logger.warning(
                        "[batch-dep] item=#%s scene=%s dep=#%s dep_status=%s dep_result_url=None → reference_url=None (依赖完成但无结果URL！)",
                        item["id"], item["scene_id"], dependency.get("id"), _batch_status_name(dep_status),
                    )
            elif item.get("dependency_item_id"):
                logger.info(
                    "[batch-dep] item=#%s scene=%s dependency_item_id=%s 未在 by_id 中找到 → reference_url=None",
                    item["id"], item["scene_id"], item.get("dependency_item_id"),
                )

            try:
                submit_mode = "image_edit" if reference_url else (job.get("mode") or "auto")
                source_image = reference_url or job.get("source_image")
                result = self.generate_image(
                    scene_id=int(item["scene_id"]),
                    user_id=int(job["user_id"]),
                    auth_token=job.get("auth_token") or "",
                    mode=submit_mode,
                    asset_type=job.get("asset_type") or StoryboardAutoGenerateConstants.DEFAULT_ASSET_TYPE,
                    prompt=job.get("prompt"),
                    source_image=source_image,
                    ratio=job.get("ratio"),
                    image_size=job.get("image_size"),
                    count=int(job.get("count") or 1),
                    sequence_mode=job.get("sequence_mode"),
                    select_result=not is_regeneration,
                    generation_snapshots=generation_snapshots,
                )
            except StoryboardCliError as exc:
                # 外部 location grid readiness check：保持 PENDING，不改状态，仅写诊断 extra_json，
                # 等待九宫格回写后下一 tick 自动重试。详见 _check_location_grid_readiness。
                from config.constant import LocationReferenceStatus
                if exc.error_code == LocationReferenceStatus.WAITING_GRID:
                    is_quality_wait = bool(exc.payload.get("quality_mode"))
                    # 正常情况下 quality 首帧 batch 在创建前已完成全批预检，不会进入这里。
                    # 若创建后发生并发资产变更，严格失败，绝不降级成无参考图 t2i。
                    if is_quality_wait:
                        prev_extra = item.get("extra_json") if isinstance(item.get("extra_json"), dict) else {}
                        StoryboardImageBatchItemModel.update(
                            int(item["id"]),
                            status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
                            error_code=StoryboardAutoGenerateConstants.ERROR_QUALITY_PARENT_REFERENCE_MISSING,
                            error_message="效果模式场景参考图前置条件在批次创建后失效",
                            extra_json={
                                **prev_extra,
                                "location_db_id": exc.payload.get("location_db_id"),
                            },
                        )
                        item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
                        if int(job.get("stop_on_error") or 0):
                            break
                        continue
                    else:
                        # balanced/speed：缺参考图 + 有运行中九宫格任务（可能已卡死）。
                        # 累加等待计数；超过 BALANCED_LOCATION_REFERENCE_WAIT_MAX_TICKS 后
                        # 放弃等待，降级走 t2i 文生图（force_bypass 跳过 readiness 检查）。
                        prev_extra = item.get("extra_json") if isinstance(item.get("extra_json"), dict) else {}
                        prev_count = int(prev_extra.get("location_grid_wait_count") or 0)
                        wait_count = prev_count + 1
                        max_wait = int(StoryboardAutoGenerateConstants.BALANCED_LOCATION_REFERENCE_WAIT_MAX_TICKS)
                        wait_extra = {
                            **prev_extra,
                            "waiting": "location_grid_reference",
                            "location_db_id": exc.payload.get("location_db_id"),
                            "location_grid_wait_count": wait_count,
                            "location_grid_wait_max_ticks": max_wait,
                        }
                        if wait_count <= max_wait:
                            StoryboardImageBatchItemModel.update(int(item["id"]), extra_json=wait_extra)
                            logger.info(
                                "[batch-loc] item=#%s scene=%s → 保持 PENDING (等待 location 九宫格，%d/%d)",
                                item["id"], item["scene_id"], wait_count, max_wait,
                            )
                            continue
                        # 超时降级：放弃等待参考图，走 t2i 文生图
                        logger.warning(
                            "[batch-loc] item=#%s scene=%s → 降级 t2i (等待 %d/%d 超时，放弃 location 参考图)",
                            item["id"], item["scene_id"], wait_count, max_wait,
                        )
                        degraded_result = self.generate_image(
                            scene_id=int(item["scene_id"]),
                            user_id=int(job["user_id"]),
                            auth_token=job.get("auth_token") or "",
                            mode="text_to_image",
                            asset_type=job.get("asset_type") or StoryboardAutoGenerateConstants.DEFAULT_ASSET_TYPE,
                            prompt=job.get("prompt"),
                            ratio=job.get("ratio"),
                            image_size=job.get("image_size"),
                            count=int(job.get("count") or 1),
                            sequence_mode=job.get("sequence_mode"),
                            force_bypass=True,
                            select_result=not is_regeneration,
                        )
                        degraded_project_ids = degraded_result.get("project_ids") or []
                        degraded_asset_ids = degraded_result.get("asset_ids") or []
                        degraded_selected = degraded_result.get("selected_asset_id") or (degraded_asset_ids[0] if degraded_asset_ids else None)
                        degraded_extra = {
                            **wait_extra,
                            "waiting": "",
                            "degraded_from_location_reference": True,
                        }
                        StoryboardImageBatchItemModel.update(
                            int(item["id"]),
                            status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING,
                            ai_tool_id=degraded_project_ids[0] if degraded_project_ids else None,
                            asset_id=degraded_selected,
                            project_ids=degraded_project_ids,
                            reference_item_id=reference_item_id,
                            reference_url=None,
                            extra_json=degraded_extra,
                        )
                        item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING
                        item["project_ids"] = degraded_project_ids
                        item["asset_id"] = degraded_selected
                        item["reference_item_id"] = reference_item_id
                        item["reference_url"] = None
                        submitted_count += 1
                        continue
                self._fail_image_batch_item(
                    item,
                    error_code=exc.error_code,
                    error_message=exc.message,
                    extra_json={"payload": exc.payload},
                )
                if int(job.get("stop_on_error") or 0):
                    break
                continue

            project_ids = result.get("project_ids") or []
            asset_ids = result.get("asset_ids") or []
            selected_asset_id = result.get("selected_asset_id") or (asset_ids[0] if asset_ids else None)
            StoryboardImageBatchItemModel.update(
                int(item["id"]),
                status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING,
                ai_tool_id=project_ids[0] if project_ids else None,
                asset_id=selected_asset_id,
                project_ids=project_ids,
                reference_item_id=reference_item_id,
                reference_url=reference_url,
                extra_json={**item_extra, "submission": result},
            )
            item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING
            item["project_ids"] = project_ids
            item["asset_id"] = selected_asset_id
            item["reference_item_id"] = reference_item_id
            item["reference_url"] = reference_url
            item["extra_json"] = {**item_extra, "submission": result}
            submitted_count += 1
            if reference_url:
                logger.info(
                    "[batch-submit] item=#%s scene=%s mode=%s source_image=%s → asset=%s (已用前一分镜作参考)",
                    item["id"], item["scene_id"], submit_mode, _url_preview(source_image), selected_asset_id,
                )
            else:
                logger.warning(
                    "[batch-submit] item=#%s scene=%s mode=%s source_image=None → asset=%s (⚠️未使用前一分镜)",
                    item["id"], item["scene_id"], submit_mode, selected_asset_id,
                )

        self._update_image_batch_job_counts(job_id)
        return {"submitted_count": submitted_count}


    def _process_one_video_batch_job(self, job: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """推进视频批量任务。generate_video 内部按 scene.video_type 分流图生视频 / LTX 对口型。"""
        job_id = int(job["id"])
        submitted_count = 0

        # 从 job.extra_json 读取图生视频图片输入模式（兼容旧批次默认 first_last_frame）。
        job_extra = job.get("extra_json") if isinstance(job.get("extra_json"), dict) else {}
        generation_snapshots = job_extra.get('generation_snapshots') or {}
        batch_image_mode = self._normalize_video_image_mode(job_extra.get("image_mode"))
        # 严格校验：所选 task_type 不支持 image_mode 时失败，禁止降级输入模式。
        task_type_raw = job_extra.get("task_type")
        if batch_image_mode != "first_last_frame" and task_type_raw is not None:
            try:
                cfg = UnifiedConfigRegistry.get_by_id(int(task_type_raw))
                supported = [str(m) for m in (getattr(cfg, "supported_image_modes", None) or [])]
                compatible = batch_image_mode in supported
                if batch_image_mode == "first_last_with_ref":
                    compatible = all(
                        required in supported
                        for required in ("first_last_frame", "multi_reference")
                    )
                if not compatible:
                    raise StoryboardCliError(
                        "MODEL_INPUT_UNSUPPORTED",
                        f"task_type={task_type_raw} 不支持 image_mode={batch_image_mode}",
                    )
            except StoryboardCliError:
                raise
            except Exception as exc:
                raise StoryboardCliError(
                    "MODEL_INPUT_UNSUPPORTED",
                    f"无法校验 task_type={task_type_raw}: {exc}",
                )

        for item in items:
            if int(item.get("status") or 0) != StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING:
                continue
            asset = self._asset_info(item.get("asset_id")) if item.get("asset_id") else None
            if asset and asset.get("result_url"):
                self._complete_image_batch_item(item, result_url=asset.get("result_url"))
            elif asset and int(asset.get("status") or 0) == -1:
                self._fail_image_batch_item(
                    item,
                    error_code="generation_failed",
                    error_message=asset.get("message") or "video generation failed",
                )

        for item in items:
            if int(item.get("status") or 0) != StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING:
                continue
            scene_id = int(item["scene_id"])
            try:
                result = self.generate_video(
                    scene_id=scene_id,
                    user_id=int(job["user_id"]),
                    auth_token=job.get("auth_token") or "",
                    mode="image_to_video",
                    prompt=job.get("prompt"),
                    ratio=job.get("ratio"),
                    image_mode=batch_image_mode,
                    task_type=task_type_raw,
                    generation_snapshots=generation_snapshots,
                )
            except StoryboardCliError as exc:
                StoryboardImageBatchItemModel.update(
                    int(item["id"]),
                    status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
                    error_code=exc.error_code,
                    error_message=exc.message,
                    extra_json={"payload": exc.payload},
                )
                item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
                if int(job.get("stop_on_error") or 0):
                    break
                continue
            except Exception as exc:
                StoryboardImageBatchItemModel.update(
                    int(item["id"]),
                    status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
                    error_code="submit_error",
                    error_message=str(exc)[:512],
                )
                item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
                if int(job.get("stop_on_error") or 0):
                    break
                continue

            project_ids = result.get("project_ids") or []
            if not project_ids and result.get("ai_tool_id"):
                project_ids = [result["ai_tool_id"]]
            asset_ids = result.get("asset_ids") or []
            if not asset_ids and result.get("asset_id"):
                asset_ids = [result["asset_id"]]
            selected_asset_id = (
                result.get("selected_asset_id")
                or result.get("asset_id")
                or (asset_ids[0] if asset_ids else None)
            )
            StoryboardImageBatchItemModel.update(
                int(item["id"]),
                status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING,
                ai_tool_id=project_ids[0] if project_ids else None,
                asset_id=selected_asset_id,
                project_ids=project_ids,
                extra_json={
                    **(item.get('extra_json') if isinstance(item.get('extra_json'), dict) else {}),
                    "submission": result,
                    "video_type": result.get("video_type") or item.get("video_type"),
                },
            )
            item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING
            item["project_ids"] = project_ids
            item["asset_id"] = selected_asset_id
            submitted_count += 1
            logger.info(
                "[video-batch-submit] job=%s item=#%s scene=%s asset=%s",
                job_id, item["id"], item["scene_id"], selected_asset_id,
            )

        self._update_image_batch_job_counts(job_id)
        return {"submitted_count": submitted_count}

    def _summarize_batch_items(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        """按 item.status（数字码）统计各状态计数。

        与 `_update_image_batch_job_counts` / status 接口共用同一口径，
        避免状态码判据在三处漂移。
        """
        pending = sum(1 for item in items if int(item.get("status") or 0) == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING)
        running = sum(1 for item in items if int(item.get("status") or 0) == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING)
        completed = sum(1 for item in items if int(item.get("status") or 0) == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_COMPLETED)
        failed = sum(1 for item in items if int(item.get("status") or 0) == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED)
        skipped = sum(1 for item in items if int(item.get("status") or 0) == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_SKIPPED)
        return {
            "total": len(items),
            "pending": pending,
            "running": running,
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
        }

    def _persist_image_batch_planned_counts(self, job_id: int) -> None:
        """在 batch item 全部落库后调用一次，写入本次计划的 submitted_count（计划待生成数）。

        submitted_count 语义统一为「本轮计划提交的总数」= pending(待生成) + running(已有任务在跑)，
        该值一旦在 plan 阶段写入就不再随调度 tick 变化；实际进度由 status 接口的
        pending/running/completed 等聚合字段反映。这避免提交响应返回 0、轮询返回中间值、
        完成返回终值这种 0→N→M 跳变。
        """
        items = StoryboardImageBatchItemModel.list_by_job(int(job_id))
        counts = self._summarize_batch_items(items)
        planned_submitted = counts["pending"] + counts["running"]
        if counts["pending"] or counts["running"]:
            status = StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_RUNNING
        elif counts["failed"] and counts["completed"]:
            status = StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_PARTIAL
        elif counts["failed"]:
            status = StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_FAILED
        else:
            status = StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_COMPLETED
        StoryboardImageBatchJobModel.update(
            int(job_id),
            status=status,
            submitted_count=planned_submitted,
            completed_count=counts["completed"],
            failed_count=counts["failed"],
            skipped_count=counts["skipped"],
        )

    def _update_image_batch_job_counts(self, job_id: int) -> None:
        items = StoryboardImageBatchItemModel.list_by_job(int(job_id))
        counts = self._summarize_batch_items(items)
        if counts["pending"] or counts["running"]:
            status = StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_RUNNING
        elif counts["failed"] and counts["completed"]:
            status = StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_PARTIAL
        elif counts["failed"]:
            status = StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_FAILED
        else:
            status = StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_COMPLETED
        # 注意：submitted_count 不在此处更新。它表示「本轮计划待生成数」，
        # 只在 plan 阶段（_persist_image_batch_planned_counts）一次性写入；
        # 调度 tick 只推进 status/completed_count/failed_count/skipped_count。
        StoryboardImageBatchJobModel.update(
            int(job_id),
            status=status,
            completed_count=counts["completed"],
            failed_count=counts["failed"],
            skipped_count=counts["skipped"],
        )

    def _plan_image_batch_items(
        self,
        *,
        storyboard_id: int,
        asset_type: str,
        sequence_mode: str,
        limit: int,
        scene_ids: Optional[Sequence[int]] = None,
        existing_policy: str = StoryboardAutoGenerateConstants.IMAGE_EXISTING_POLICY_SKIP,
    ) -> List[Dict[str, Any]]:
        sequence_mode = self._normalize_sequence_mode(sequence_mode)
        scenes = StoryboardSceneModel.list_by_storyboard(int(storyboard_id)) or []
        requested = set(scene_ids) if scene_ids is not None else None
        items: List[Dict[str, Any]] = []
        previous_group_key: Optional[str] = None
        previous_item: Optional[Dict[str, Any]] = None
        previous_by_group: Dict[str, Dict[str, Any]] = {}
        missing_count = 0

        for order_index, scene in enumerate(scenes, start=1):
            scene_id = int(_get_field(scene, "id"))
            group_key = self._scene_group_key(scene, previous_group_key, storyboard_id)
            previous_group_key = group_key
            if requested is not None and scene_id not in requested:
                continue
            selected_asset = self._selected_asset_for_scene(scene, asset_type)
            status = "pending"
            batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING
            result_url = None
            asset_id = selected_asset.get("id") if selected_asset else None
            ai_tool_id = selected_asset.get("ai_tool_id") if selected_asset else None
            project_ids = [ai_tool_id] if ai_tool_id else []
            base_asset_id = asset_id

            should_regenerate = bool(
                selected_asset
                and selected_asset.get("result_url")
                and existing_policy == StoryboardAutoGenerateConstants.IMAGE_EXISTING_POLICY_REGENERATE
            )
            if selected_asset and selected_asset.get("result_url") and not should_regenerate:
                status = "already_ready"
                batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_COMPLETED
                result_url = selected_asset.get("result_url")
            elif (
                not should_regenerate
                and selected_asset
                and selected_asset.get("status") in StoryboardAutoGenerateConstants.RUNNING_STATUSES
            ):
                status = "already_running"
                batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING
            elif int(limit) > 0 and missing_count >= int(limit):
                status = "limit_reached"
                batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_SKIPPED
            else:
                missing_count += 1
                if should_regenerate:
                    status = "regenerate_pending"
                    asset_id = None
                    ai_tool_id = None
                    project_ids = []

            dependency_scene_id = None
            if sequence_mode == StoryboardAutoGenerateConstants.SEQUENCE_MODE_BALANCED:
                dependency_scene_id = (previous_by_group.get(group_key) or {}).get("scene_id")
            elif sequence_mode == StoryboardAutoGenerateConstants.SEQUENCE_MODE_QUALITY:
                dependency_scene_id = (previous_item or {}).get("scene_id")

            item = {
                "scene_id": scene_id,
                "title": _get_field(scene, "title") or "",
                "sort_order": _get_field(scene, "sort_order"),
                "asset_type": asset_type,
                "group_key": group_key,
                "order_index": order_index,
                "dependency_scene_id": dependency_scene_id,
                "status": status,
                "batch_status": batch_status,
                "asset": selected_asset,
                "asset_id": asset_id,
                "ai_tool_id": ai_tool_id,
                "project_ids": project_ids,
                "result_url": result_url,
                "base_asset_id": base_asset_id,
            }
            items.append(item)
            if batch_status != StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_SKIPPED:
                previous_item = item
                previous_by_group[group_key] = item

        # 诊断日志：输出规划出的依赖图，确认同组串联链是否正确建立
        plan_lines = []
        for idx, it in enumerate(items, start=1):
            plan_lines.append(
                f"  item#{idx} scene={it['scene_id']} group={it.get('group_key')} "
                f"status={it.get('status')} dep_scene={it.get('dependency_scene_id')} "
                f"result_url={'yes' if it.get('result_url') else 'None'}"
            )
        logger.info(
            "[batch-plan] storyboard=%s mode=%s items=%d:\n%s",
            storyboard_id, sequence_mode, len(items), "\n".join(plan_lines) or "  (empty)",
        )
        return items

    def _normalize_requested_scene_ids(
        self,
        storyboard_id: int,
        scene_ids: Optional[Sequence[int]],
    ) -> Optional[List[int]]:
        """Validate an optional selected-scene scope without changing legacy all-scene calls."""
        if scene_ids is None:
            return None
        if isinstance(scene_ids, (str, bytes)) or not isinstance(scene_ids, Sequence):
            raise StoryboardCliError("invalid_scene_ids", "scene_ids must be an array")

        normalized: List[int] = []
        seen = set()
        for raw_id in scene_ids:
            try:
                scene_id = int(raw_id)
            except (TypeError, ValueError):
                raise StoryboardCliError("invalid_scene_ids", "scene_ids must contain integers")
            if scene_id <= 0:
                raise StoryboardCliError("invalid_scene_ids", "scene_ids must contain positive integers")
            if scene_id not in seen:
                seen.add(scene_id)
                normalized.append(scene_id)

        if not normalized:
            raise StoryboardCliError("empty_scene_ids", "scene_ids must not be empty")
        if len(normalized) > StoryboardAutoGenerateConstants.MAX_SELECTED_SCENE_COUNT:
            raise StoryboardCliError(
                "too_many_scene_ids",
                f"scene_ids exceeds {StoryboardAutoGenerateConstants.MAX_SELECTED_SCENE_COUNT}",
            )

        storyboard_scene_ids = {
            int(_get_field(scene, "id"))
            for scene in (StoryboardSceneModel.list_by_storyboard(int(storyboard_id)) or [])
        }
        invalid_ids = sorted(set(normalized) - storyboard_scene_ids)
        if invalid_ids:
            raise StoryboardCliError(
                "selection_stale",
                "some selected scenes do not belong to this storyboard",
                payload={"invalid_scene_ids": invalid_ids},
            )
        return sorted(normalized)

    def _scene_group_key(self, scene: Any, previous_group_key: Optional[str], storyboard_id: int) -> str:
        prompt_json = _parse_json(_get_field(scene, "prompt_json"), {}) or {}
        source = prompt_json.get("source") if isinstance(prompt_json, dict) else {}
        if isinstance(source, dict):
            for key in ("group_id", "group_name", "group_type"):
                value = source.get(key)
                if str(value or "").strip():
                    return f"group:{value}"
        return previous_group_key or f"manual:{storyboard_id}:0"

    def _normalize_sequence_mode(self, sequence_mode: Optional[str]) -> str:
        value = str(sequence_mode or StoryboardAutoGenerateConstants.DEFAULT_SEQUENCE_MODE).strip().lower()
        if value not in StoryboardAutoGenerateConstants.VALID_SEQUENCE_MODES:
            raise StoryboardCliError("invalid_sequence_mode", f"invalid sequence_mode: {sequence_mode}")
        return value

    def _normalize_video_image_mode(self, image_mode: Optional[str]) -> str:
        """规范化图生视频图片输入模式，默认 first_last_frame。"""
        value = str(image_mode or "first_last_frame").strip().lower()
        if value not in VALID_VIDEO_IMAGE_MODES:
            return "first_last_frame"
        return value

    def _batch_job_status_name(self, status: Any) -> str:
        value = int(status or 0)
        return {
            StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_PENDING: "pending",
            StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_RUNNING: "running",
            StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_COMPLETED: "completed",
            StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_FAILED: "failed",
            StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_PARTIAL: "partial",
        }.get(value, "unknown")

    def _batch_item_status_name(self, status: Any) -> str:
        value = int(status or 0)
        return {
            StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING: "pending",
            StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING: "running",
            StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_COMPLETED: "completed",
            StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED: "failed",
            StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_SKIPPED: "skipped",
        }.get(value, "unknown")

    def _batch_item_summary(self, item: Dict[str, Any]) -> Dict[str, Any]:
        extra = item.get("extra_json") or {}
        if not isinstance(extra, dict):
            extra = {}
        return {
            "id": item.get("id"),
            "scene_id": item.get("scene_id"),
            "title": extra.get("title") or "",
            "sort_order": extra.get("sort_order"),
            "asset_type": item.get("asset_type"),
            "group_key": item.get("group_key"),
            "order_index": item.get("order_index"),
            "dependency_item_id": item.get("dependency_item_id"),
            "dependency_scene_id": extra.get("dependency_scene_id"),
            "status": self._batch_item_status_name(item.get("status")),
            "plan_status": extra.get("plan_status"),
            "existing_policy": extra.get("existing_policy") or StoryboardAutoGenerateConstants.IMAGE_EXISTING_POLICY_SKIP,
            "base_asset_id": extra.get("base_asset_id"),
            "waiting": extra.get("waiting") or "",
            "project_ids": item.get("project_ids") or [],
            "asset_id": item.get("asset_id"),
            "reference_item_id": item.get("reference_item_id"),
            "reference_url": item.get("reference_url"),
            "result_url": item.get("result_url"),
            "error_code": item.get("error_code"),
            "error_message": item.get("error_message"),
        }

    def split_from_script(
        self,
        storyboard_id: int,
        user_id: int,
        *,
        auth_token: str = "",
        model: Optional[str] = None,
        model_id: Optional[int] = None,
        vendor_id: Optional[int] = None,
        max_group_duration: int = 15,
        force_medium_shot: bool = False,
        no_bg_music: bool = False,
        split_multi_dialogue: bool = False,
        language: str = "",
        dialogue_language: str = "",
        prompt_language: str = "",
        sequence_mode: str = "speed",
        force_overwrite_subscene_grids: bool = False,
    ) -> Dict[str, Any]:
        """从剧本拆分生成分镜场景。

        已改为异步路径：创建持久化拆分任务后立即返回 task_id，实际拆分（LLM 解析、
        资产化、create_scenes、子场景九宫格）由 task/script_split_task.py worker 推进，
        与 generate-from-script 路由收敛到同一 worker（step_publish 处理 storyboard source）。
        这样避免同步阻塞约 7 分钟拖垮 asyncio 默认 ThreadPoolExecutor。
        调用方用 GET /api/script-split/tasks/{task_id} 轮询进度。
        """
        # 兼容旧 CLI/API 参数名，但不再允许覆盖已有子场景参考图。
        del force_overwrite_subscene_grids
        sequence_mode = self._normalize_sequence_mode(sequence_mode)
        if sequence_mode == StoryboardAutoGenerateConstants.SEQUENCE_MODE_QUALITY and Edition.is_community():
            raise StoryboardCliError("enterprise_only", "效果模式仅商业版支持")
        storyboard = StoryboardModel.get_by_id(int(storyboard_id))
        if not storyboard:
            raise StoryboardCliError("not_found", f"storyboard not found: {storyboard_id}")

        # 解析 model 三元组：config 里可能是 dict（{model,model_id,vendor_id}）也可能是 str。
        # 旧实现直接 str(dict) 会把 dict repr 当模型名拼进 URL 触发 404。
        resolved_model, resolved_model_id, resolved_vendor_id = self._resolve_split_model_context(
            storyboard, model, model_id, vendor_id
        )

        existing_scenes = StoryboardSceneModel.list_by_storyboard(int(storyboard_id))
        if existing_scenes:
            raise StoryboardCliError("scenes_exist", "storyboard already has scenes")

        script_id = _get_field(storyboard, "script_id")
        if not script_id:
            script = ScriptModel.get_by_episode(_get_field(storyboard, "world_id"), _get_field(storyboard, "episode_number") or 1)
            script_id = _get_field(script, "id") if script else None
        if not script_id:
            raise StoryboardCliError("script_not_found", "no script available for storyboard")

        script = ScriptModel.get_by_id(int(script_id))
        content = _get_field(script, "content") if script else None
        if not str(content or "").strip():
            raise StoryboardCliError("script_empty", "script content is empty")

        # 若 DB 里 script_id 缺失，补写（快速校验，不阻塞）
        if script_id != _get_field(storyboard, "script_id"):
            StoryboardModel.update(int(storyboard_id), script_id=int(script_id))

        # 构造 request_config，对齐 generate-from-script 路由的字段集。
        # worker 的 _normalize_request_config 会兜底 model 为 dict 的情况，但这里已解包成三元组。
        from config.constant import ScriptSplitConstants
        request_config = {
            "max_group_duration": int(max_group_duration),
            "world_id": _get_field(storyboard, "world_id"),
            "model": resolved_model,
            "temperature": 0.5,
            "force_medium_shot": bool(force_medium_shot),
            "no_bg_music": bool(no_bg_music),
            "split_multi_dialogue": bool(split_multi_dialogue),
            "language": language or "",
            "dialogue_language": dialogue_language or language or "",
            "prompt_language": prompt_language or language or "",
            "vendor_id": resolved_vendor_id,
            "model_id": int(resolved_model_id) if resolved_model_id else 1,
            "enable_thinking": False,
            "thinking_effort": "medium",
            # 故事板发布专用配置：worker step_publish 据此走 storyboard source 发布
            "source": "storyboard",
            "storyboard_id": int(storyboard_id),
            "enable_qc": False,
            "qc_max_rounds": 1,
            "sequence_mode": sequence_mode,
        }

        # service 已在路由层 asyncio.to_thread 的子线程中执行，无活动事件循环，
        # asyncio.run 安全（与 _parse_script_to_shots_sync 的既有模式一致）。
        import asyncio as _asyncio
        from api.script_split import create_split_task
        task_id, is_new = _asyncio.run(
            create_split_task(
                user_id=int(user_id),
                source_type=ScriptSplitConstants.SOURCE_TYPE_STORYBOARD,
                source_id=int(storyboard_id),
                source_node_key=None,
                script_content=str(content),
                request_config=request_config,
                auth_token=auth_token or None,
            )
        )

        return {
            "success": True,
            "storyboard_id": int(storyboard_id),
            "script_id": int(script_id),
            "message": "分镜拆分任务已创建" if is_new else "已有进行中的拆分任务",
            "status": "queued",
            "task_id": task_id,
            "status_url": f"/api/script-split/tasks/{task_id}",
        }

    def _require_user_id(self, user_id: Any) -> int:
        try:
            value = int(user_id)
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            raise StoryboardCliError("missing_user_id", "user_id is required")
        return value

    def _normalize_page(self, page: Any) -> int:
        try:
            value = int(page)
        except (TypeError, ValueError):
            value = 1
        return max(1, value)

    def _normalize_page_size(self, page_size: Any) -> int:
        try:
            value = int(page_size)
        except (TypeError, ValueError):
            value = StoryboardAgentReadConstants.DEFAULT_PAGE_SIZE
        value = max(1, value)
        return min(value, StoryboardAgentReadConstants.MAX_PAGE_SIZE)

    def _record_belongs_to_user(self, record: Any, user_id: int) -> bool:
        record_user_id = _get_field(record, "user_id")
        if record_user_id in (None, ""):
            return True
        try:
            return int(record_user_id) == int(user_id)
        except (TypeError, ValueError):
            return False

    def _ensure_world_for_user(self, world_id: int, user_id: int) -> Any:
        try:
            world_id_value = int(world_id)
        except (TypeError, ValueError):
            raise StoryboardCliError("invalid_parameter", "world_id must be an integer")
        world = WorldModel.get_by_id(world_id_value)
        if not world:
            raise StoryboardCliError("not_found", f"world not found: {world_id}")
        if not self._record_belongs_to_user(world, user_id):
            raise StoryboardCliError("forbidden", "world does not belong to current user")
        return world

    def _ensure_storyboard_for_user(self, storyboard_id: int, user_id: Optional[int]) -> Any:
        try:
            storyboard_id_value = int(storyboard_id)
        except (TypeError, ValueError):
            raise StoryboardCliError("invalid_parameter", "storyboard_id must be an integer")
        storyboard = StoryboardModel.get_by_id(storyboard_id_value)
        if not storyboard:
            raise StoryboardCliError("not_found", f"storyboard not found: {storyboard_id}")
        if user_id is not None and not self._record_belongs_to_user(storyboard, int(user_id)):
            raise StoryboardCliError("forbidden", "storyboard does not belong to current user")
        return storyboard

    def _ensure_script_for_user(self, script_id: int, user_id: int) -> Any:
        try:
            script_id_value = int(script_id)
        except (TypeError, ValueError):
            raise StoryboardCliError("invalid_parameter", "script_id must be an integer")
        script = ScriptModel.get_by_id(script_id_value)
        if not script:
            raise StoryboardCliError("script_not_found", f"script not found: {script_id}")
        if not self._record_belongs_to_user(script, user_id):
            raise StoryboardCliError("forbidden", "script does not belong to current user")
        world_id = _get_field(script, "world_id")
        if not world_id:
            raise StoryboardCliError("script_missing_world", f"script has no world_id: {script_id}")
        self._ensure_world_for_user(world_id, user_id)
        return script

    def _storyboard_config(self, storyboard: Any) -> Dict[str, Any]:
        return _parse_json(_get_field(storyboard, "config_json"), {}) or {}

    def _normalize_script_split_model_selection(
        self,
        model: Optional[Any],
        *,
        model_id: Optional[int] = None,
        vendor_id: Optional[int] = None,
    ) -> Any:
        """规范化 selectedScriptSplitLlmModel 的字符串/对象两种存储形式。"""
        if isinstance(model, dict):
            model_name = str(model.get("model") or model.get("name") or "").strip()
            if model_id in (None, ""):
                model_id = model.get("model_id") or model.get("id")
            if vendor_id in (None, ""):
                vendor_id = model.get("vendor_id") or model.get("vendorId")
        else:
            model_name = str(model or "").strip()

        if not model_name:
            model_name = StoryboardAgentCommandConstants.DEFAULT_SCRIPT_SPLIT_MODEL
        if model_id in (None, "") and vendor_id in (None, ""):
            return model_name
        return {
            "model": model_name,
            "model_id": int(model_id) if model_id not in (None, "") else None,
            "vendor_id": int(vendor_id) if vendor_id not in (None, "") else None,
        }

    def _world_script_split_model_preference(
        self, user_id: int, world_id: int
    ) -> Tuple[Any, Optional[str]]:
        try:
            preference = UserPreferencesModel.get(
                str(user_id),
                str(world_id),
                StoryboardAgentCommandConstants.SCRIPT_SPLIT_MODEL_PREFERENCE_TYPE,
            )
            if preference:
                return self._normalize_script_split_model_selection(preference.get_value()), None
        except Exception as exc:
            logger.warning(
                "读取世界 %s 的剧本拆分模型偏好失败: %s", world_id, exc
            )
            return (
                StoryboardAgentCommandConstants.DEFAULT_SCRIPT_SPLIT_MODEL,
                "读取世界级拆分模型偏好失败，已使用服务端默认模型",
            )
        return StoryboardAgentCommandConstants.DEFAULT_SCRIPT_SPLIT_MODEL, None

    def _save_world_script_split_model_preference(
        self, user_id: int, world_id: int, selection: Any
    ) -> Tuple[bool, Optional[str]]:
        try:
            UserPreferencesModel.upsert(
                str(user_id),
                str(world_id),
                StoryboardAgentCommandConstants.SCRIPT_SPLIT_MODEL_PREFERENCE_TYPE,
                selection,
            )
            return True, None
        except Exception as exc:
            logger.error(
                "保存世界 %s 的剧本拆分模型偏好失败: %s", world_id, exc
            )
            return False, "故事板已保存，但世界级拆分模型偏好同步失败"

    def _resolve_split_model_context(
        self,
        storyboard: Any,
        model: Optional[Any] = None,
        model_id: Optional[int] = None,
        vendor_id: Optional[int] = None,
    ) -> tuple:
        """解析剧本拆分 LLM 模型三元组 (model, model_id, vendor_id)。

        selectedScriptSplitLlmModel 在前端可能存成 dict
        ({name/model/model_id/vendor_id}) 而非字符串。直接 str(dict) 会把整个
        dict 的 repr 当模型名，一路传到 gemini_client._build_url 拼进
        models/{model}:generateContent 触发 404。这里统一解包，逻辑与
        storyboard_first_frame_grid_service._llm_model_context 完全对齐。

        优先级：显式入参 > config_json > 默认模型。
        """
        # 显式入参优先
        explicit_model = ""
        if isinstance(model, dict):
            explicit_model = str(model.get("model") or model.get("name") or "").strip()
            if model_id in (None, ""):
                model_id = model.get("model_id") or model.get("id")
            if vendor_id in (None, ""):
                vendor_id = model.get("vendor_id") or model.get("vendorId")
        elif model not in (None, ""):
            explicit_model = str(model).strip()

        if explicit_model:
            resolved_model = explicit_model
        else:
            selected = self._storyboard_config(storyboard).get("selectedScriptSplitLlmModel")
            if isinstance(selected, dict):
                resolved_model = str(selected.get("model") or selected.get("name") or "").strip()
                if model_id in (None, ""):
                    model_id = selected.get("model_id") or selected.get("id")
                if vendor_id in (None, ""):
                    vendor_id = selected.get("vendor_id") or selected.get("vendorId")
            else:
                resolved_model = str(selected or "").strip()

        if not resolved_model:
            resolved_model = StoryboardAgentCommandConstants.DEFAULT_SCRIPT_SPLIT_MODEL
        return (
            resolved_model,
            int(model_id) if model_id not in (None, "") else None,
            int(vendor_id) if vendor_id not in (None, "") else None,
        )

    def _resolve_image_task_type(self, storyboard: Any, task_type: Optional[int]) -> Optional[int]:
        if task_type not in (None, ""):
            return int(task_type)
        # CLI 与 Storyboard Web 偏好严格隔离；未显式指定时由 CLI 五槽位偏好解析。
        return None

    def _filter_page_by_user(self, result: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        out = dict(result or {})
        data = out.get("data") or []
        filtered = [item for item in data if self._record_belongs_to_user(item, user_id)]
        out["data"] = filtered
        if len(filtered) != len(data):
            out["total"] = len(filtered)
        return out

    def _script_payload(self, script: Any, *, include_content: bool) -> Dict[str, Any]:
        payload = _to_dict(script)
        content = payload.get("content") or ""
        payload["content_length"] = len(str(content))
        if not include_content:
            payload.pop("content", None)
        return payload

    def _world_payload(self, world: Any, *, include_full_story_outline: bool = False) -> Dict[str, Any]:
        payload = _to_dict(world)
        story_outline = str(payload.get("story_outline") or "")
        preview, truncated = self._story_outline_preview(story_outline)
        payload["story_outline_preview"] = preview
        payload["story_outline_truncated"] = truncated
        if not include_full_story_outline:
            payload["story_outline"] = preview
        return payload

    def _story_outline_preview(self, story_outline: str) -> Tuple[str, bool]:
        text = story_outline or ""
        keep = StoryboardAgentReadConstants.STORY_OUTLINE_PREVIEW_CHARS
        if len(text) <= keep * 2:
            return text, False
        return f"{text[:keep]}...{text[-keep:]}", True

    def _scene_summary(self, scene: Any, *, index: int) -> Dict[str, Any]:
        scene_id = int(_get_field(scene, "id"))
        prompt_json = _parse_json(_get_field(scene, "prompt_json"), {}) or {}
        scene_desc = prompt_json.get("scene_desc") if isinstance(prompt_json, dict) else None
        return {
            "scene_id": scene_id,
            "index": index,
            "title": _get_field(scene, "title") or "",
            "summary": scene_desc or _get_field(scene, "video_prompt") or "",
            "duration": _get_field(scene, "duration"),
            "sort_order": _get_field(scene, "sort_order"),
            "asset_status": {
                "first_frame": self._scene_asset_summary(scene, "first_frame"),
                "last_frame": self._scene_asset_summary(scene, "last_frame"),
                "video": self._scene_asset_summary(scene, "video"),
            },
        }

    def _scene_asset_summary(self, scene: Any, asset_type: str) -> Dict[str, Any]:
        url_field = {
            "first_frame": "first_frame_url",
            "last_frame": "last_frame_url",
            "video": "video_url",
        }[asset_type]
        asset_id = _get_field(scene, _asset_selected_field(asset_type))
        return {
            "selected_asset_id": int(asset_id) if asset_id not in (None, "") else None,
            "result_url": _public_upload_url(_get_field(scene, url_field)),
        }

    def _resolve_insert_neighbors(
        self,
        *,
        storyboard_id: int,
        scenes: Sequence[Any],
        prev_scene_id: Optional[int],
        next_scene_id: Optional[int],
    ) -> Tuple[Optional[int], Optional[int]]:
        ordered_ids = [int(_get_field(scene, "id")) for scene in scenes if _get_field(scene, "id") not in (None, "")]
        id_set = set(ordered_ids)

        if prev_scene_id is not None and prev_scene_id not in id_set:
            self._ensure_scene_belongs_to_storyboard(prev_scene_id, storyboard_id)
        if next_scene_id is not None and next_scene_id not in id_set:
            self._ensure_scene_belongs_to_storyboard(next_scene_id, storyboard_id)

        if prev_scene_id is None and next_scene_id is None:
            if ordered_ids:
                return ordered_ids[-1], None
            return None, None

        if prev_scene_id is not None and next_scene_id is None and prev_scene_id in ordered_ids:
            index = ordered_ids.index(prev_scene_id)
            return prev_scene_id, ordered_ids[index + 1] if index + 1 < len(ordered_ids) else None

        if next_scene_id is not None and prev_scene_id is None and next_scene_id in ordered_ids:
            index = ordered_ids.index(next_scene_id)
            return ordered_ids[index - 1] if index > 0 else None, next_scene_id

        return prev_scene_id, next_scene_id

    def _ensure_scene_belongs_to_storyboard(self, scene_id: int, storyboard_id: int) -> Any:
        scene = StoryboardSceneModel.get_by_id(int(scene_id))
        if not scene:
            raise StoryboardCliError("not_found", f"scene not found: {scene_id}")
        if int(_get_field(scene, "storyboard_id") or 0) != int(storyboard_id):
            raise StoryboardCliError(
                "scene_storyboard_mismatch",
                f"scene {scene_id} does not belong to storyboard {storyboard_id}",
            )
        return scene

    def _compute_scene_insert_sort(
        self,
        storyboard_id: int,
        prev_scene_id: Optional[int],
        next_scene_id: Optional[int],
    ) -> float:
        prev_sort = self._scene_sort_value(prev_scene_id)
        next_sort = self._scene_sort_value(next_scene_id)
        mid = compute_sort_between(prev_sort, next_sort)
        if is_precision_exhausted(mid, prev_sort, next_sort):
            StoryboardSceneModel.rebalance(int(storyboard_id))
            prev_sort = self._scene_sort_value(prev_scene_id)
            next_sort = self._scene_sort_value(next_scene_id)
            mid = compute_sort_between(prev_sort, next_sort)
        return float(mid)

    def _scene_sort_value(self, scene_id: Optional[int]) -> Optional[float]:
        if scene_id is None:
            return None
        scene = StoryboardSceneModel.get_by_id(int(scene_id))
        if not scene:
            raise StoryboardCliError("not_found", f"scene not found: {scene_id}")
        sort_order = _get_field(scene, "sort_order")
        return float(sort_order) if sort_order is not None else None

    def _json_dict_param(self, value: Any, name: str) -> Optional[Dict[str, Any]]:
        if value in (None, ""):
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                raise StoryboardCliError("invalid_parameter", f"{name} must be a JSON object")
            if isinstance(parsed, dict):
                return parsed
        raise StoryboardCliError("invalid_parameter", f"{name} must be a JSON object")

    def _page_summary(self, page: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "total": page.get("total", 0),
            "page": page.get("page", 1),
            "page_size": page.get("page_size", 0),
            "data": page.get("data") or [],
        }

    def _finalize_submission(
        self,
        *,
        scene_id: int,
        user_id: int,
        asset_type: str,
        mode: str,
        result: Dict[str, Any],
        reference_images: Optional[Sequence[str]] = None,
        select_result: bool = True,
    ) -> Dict[str, Any]:
        if not isinstance(result, dict):
            raise StoryboardCliError("submit_failed", "submitter returned invalid result")
        if result.get("success") is False:
            raise StoryboardCliError("submit_failed", str(result.get("error") or "submission failed"), payload=result)

        project_ids = _project_ids(result)
        if not project_ids:
            raise StoryboardCliError("missing_project_ids", "generation submitted without project_ids", payload=result)

        bind_result = self.bind_projects(
            scene_id,
            user_id,
            asset_type,
            project_ids,
            select_result=select_result,
        )
        return {
            "success": True,
            "scene_id": int(scene_id),
            "mode": mode,
            "project_ids": project_ids,
            "status": result.get("status") or "submitted",
            "model_used": result.get("model_used"),
            "reference_images": list(reference_images or []),
            **bind_result,
            "submission": result,
        }

    def _load_scene_pair(self, scene_id: int) -> Tuple[Any, Any]:
        scene = StoryboardSceneModel.get_by_id(int(scene_id))
        if not scene:
            raise StoryboardCliError("not_found", f"scene not found: {scene_id}")
        storyboard = StoryboardModel.get_by_id(_get_field(scene, "storyboard_id"))
        if not storyboard:
            raise StoryboardCliError("not_found", f"storyboard not found for scene: {scene_id}")
        return scene, storyboard

    def _load_dialogue_characters(self, dialogues: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ids = _dedupe([d.get("character_id") for d in dialogues if isinstance(d, dict)])
        characters: List[Dict[str, Any]] = []
        for character_id in ids:
            character = CharacterModel.get_by_id(int(character_id))
            if character:
                characters.append(_to_dict(character))
        return characters

    def _merge_named_items(
        self,
        *groups: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen = set()
        for group in groups:
            for item in group or []:
                marker = item.get("id") or item.get("name")
                if marker in (None, ""):
                    marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
                marker = str(marker)
                if marker in seen:
                    continue
                seen.add(marker)
                merged.append(item)
        return merged

    def _prompt_text(self, prompt_json: Dict[str, Any]) -> str:
        parts: List[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for sub_value in value.values():
                    visit(sub_value)
            elif isinstance(value, list):
                for sub_value in value:
                    visit(sub_value)
            elif value is not None:
                parts.append(str(value))

        visit(prompt_json)
        return "\n".join(parts)

    def _visual_prompt_text(self, prompt_json: Dict[str, Any], scene: Any = None) -> str:
        parts: List[str] = []
        excluded_keys = {
            "props",
            "props_present",
            "characters",
            "characters_present",
            "character_desc",
            "location",
            "source",
        }

        def visit(value: Any, key: str = "") -> None:
            if key in excluded_keys:
                return
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    visit(sub_value, str(sub_key))
            elif isinstance(value, list):
                for sub_value in value:
                    visit(sub_value)
            elif value is not None:
                parts.append(str(value))

        visit(prompt_json)
        video_prompt = _get_field(scene, "video_prompt") if scene is not None else None
        if video_prompt:
            parts.append(str(video_prompt))
        return "\n".join(parts)

    def _extract_character_names_from_prompt(
        self,
        prompt_json: Dict[str, Any],
        scene: Any = None,
        video_prompt: str = "",
    ) -> List[str]:
        """Extract character tags for reference matching.

        Align with build_storyboard_reference_items / video_workflow shot frame:
        only `【【角色名】】` in image/video prompt fields count. Also keep legacy
        `[[name]]` markers from the same visual text for backward compatibility.
        """
        prompt_video = video_prompt or (_get_field(scene, "video_prompt") if scene is not None else "") or ""
        names = list(extract_storyboard_reference_names(prompt_json, prompt_video).get("characters") or [])
        # Legacy ASCII markers in the same prompt fields used by reference matching.
        text_parts = [
            (prompt_json or {}).get("scene_desc") or "",
            (prompt_json or {}).get("opening_frame_description") or "",
            (prompt_json or {}).get("image_prompt") or "",
            prompt_video or (prompt_json or {}).get("video_prompt") or "",
        ]
        text = "\n".join(str(part) for part in text_parts if part)
        for match in re.findall(r"\[\[([^\]]+)\]\]", text):
            name = match.strip()
            if name:
                names.append(name)
        return _dedupe(names)

    def _resolve_prompt_characters(
        self,
        prompt_json: Dict[str, Any],
        world_id: Any,
        scene: Any = None,
        video_prompt: str = "",
    ) -> List[Dict[str, Any]]:
        """Resolve each prompt-tagged character name from the world library.

        Does not depend on script-split presence lists: a user-added
        `【【新角色】】` is looked up the same way as original tags (mirrors
        video_workflow collectShotFrameRefImages per-tag lookup).
        """
        if not world_id:
            return []
        characters: List[Dict[str, Any]] = []
        for name in self._extract_character_names_from_prompt(
            prompt_json, scene=scene, video_prompt=video_prompt
        ):
            try:
                character = CharacterModel.get_by_name(int(world_id), name)
            except Exception as exc:
                logger.warning(
                    "[storyboard-ref] character lookup failed name=%r world_id=%s err=%s",
                    name,
                    world_id,
                    exc,
                )
                character = None
            if character:
                characters.append(_to_dict(character))
            else:
                logger.warning(
                    "[storyboard-ref] tagged character not found in world library: "
                    "name=%r world_id=%s",
                    name,
                    world_id,
                )
        return characters

    def _extract_prop_names_from_prompt_text(self, prompt_text: str) -> List[str]:
        names: List[str] = []
        for match in re.findall(r"〖〖([^〗]+)〗〗", prompt_text or ""):
            name = match.strip()
            if name:
                names.append(name)
        return _dedupe(names)

    def _resolve_location(self, prompt_json: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        location_data = prompt_json.get("location")
        location_id = None
        if isinstance(location_data, dict):
            location_id = location_data.get("db_id") or location_data.get("id") or location_data.get("location_db_id")
        source = prompt_json.get("source") if isinstance(prompt_json.get("source"), dict) else {}
        location_id = location_id or source.get("location_db_id")
        if location_id:
            location = LocationModel.get_by_id(int(location_id))
            if location:
                return _to_dict(location)
        return location_data if isinstance(location_data, dict) else None

    def _check_location_grid_readiness(self, context: Dict[str, Any], *, sequence_mode: Optional[str] = None, force_bypass: bool = False) -> None:
        """
        外部 location grid readiness check（Phase 6）。

        若当前 scene 引用的 location 缺少 reference_image，按 sequence_mode 决定是否阻止生图：
          - quality（效果模式，严格）：缺图就阻止（无论是否有运行中九宫格任务），强制等待九宫格完成。
            保证首帧质量，不降级走 t2i。批量调度器对 quality 阻止有重试上限保护（QUALITY_WAIT_MAX_TICKS）。
          - balanced/speed（均衡/速度模式，宽松）：仅在九宫格任务运行中时阻止等待；
            缺图+无运行中任务则放行，走 t2i 兜底（保证生图不卡住）。
            运行中任务但等待超过 BALANCED_LOCATION_REFERENCE_WAIT_MAX_TICKS 时，
            调用方传 force_bypass=True 跳过检查降级走 t2i（防止九宫格卡死导致永久等待）。

        判定矩阵：
          | reference_image | 运行中任务 | quality 模式     | balanced/speed 模式 |
          |-----------------|------------|------------------|---------------------|
          | 有              | (任意)     | READY 放行       | READY 放行          |
          | 缺              | 有         | WAITING_GRID 阻止| WAITING_GRID 阻止（≤BALANCED超时后force_bypass降级）|
          | 缺              | 无         | WAITING_GRID 阻止| 放行(t2i 兜底)      |

        quality 模式下"缺图+无任务"抛 WAITING_GRID 时 payload 带 quality_mode=True，
        供调度器做重试上限降级（避免九宫格彻底失败时死锁）。
        """
        from config.constant import LocationReferenceStatus, StoryboardAutoGenerateConstants
        from model.grid_image_tasks import GridImageTasksModel

        # 降级路径：balanced/speed 等待已超时，强制跳过检查走 t2i
        if force_bypass:
            return

        location = context.get("location")
        if not isinstance(location, dict):
            return
        # 已有参考图，无需等待
        if location.get("reference_image"):
            return
        # 解析 location DB id
        loc_db_id = location.get("id") or location.get("db_id") or location.get("location_db_id")
        try:
            loc_db_id_int = int(loc_db_id) if loc_db_id else None
        except (TypeError, ValueError):
            loc_db_id_int = None

        is_quality_mode = (sequence_mode or "").strip().lower() == StoryboardAutoGenerateConstants.SEQUENCE_MODE_QUALITY
        has_running = bool(loc_db_id_int) and GridImageTasksModel.has_running_grid_for_entity(loc_db_id_int)

        if has_running:
            # 缺图 + 有运行中任务 → 所有模式都阻止等待
            logger.info(
                "[location-readiness] location db_id=%s reference_image 缺失，"
                "九宫格任务运行中 → waiting_location_grid_reference", loc_db_id_int,
            )
            raise StoryboardCliError(
                LocationReferenceStatus.WAITING_GRID,
                f"location db_id={loc_db_id_int} 参考图生成中，等待九宫格完成",
                payload={"location_db_id": loc_db_id_int},
            )

        # 缺图 + 无运行中任务
        if is_quality_mode:
            # 效果模式：严格阻止，强制等待九宫格提交/完成（避免 t2i 降级导致质量下降）
            # payload 带 quality_mode=True，调度器据此做重试上限降级
            logger.info(
                "[location-readiness] location db_id=%s reference_image 缺失且无运行中任务，"
                "quality 模式 → 严格阻止生图（等待九宫格提交）", loc_db_id_int,
            )
            raise StoryboardCliError(
                LocationReferenceStatus.WAITING_GRID,
                f"location db_id={loc_db_id_int} 缺少参考图，效果模式要求等待九宫格生成",
                payload={"location_db_id": loc_db_id_int, "quality_mode": True},
            )
        # 均衡/速度模式：放行，走 t2i 兜底（保证生图不卡住），保持原静默降级行为

    def _resolve_props(
        self,
        prompt_json: Dict[str, Any],
        world_id: Any = None,
        scene: Any = None,
    ) -> List[Dict[str, Any]]:
        props_items = prompt_json.get("props")
        if not isinstance(props_items, list):
            props_items = []
        prompt_text = self._visual_prompt_text(prompt_json, scene=scene)
        marked_names = set(self._extract_prop_names_from_prompt_text(prompt_text))
        out: List[Dict[str, Any]] = []

        if world_id:
            for name in marked_names:
                try:
                    prop = PropsModel.get_by_name(int(world_id), name)
                except Exception:
                    prop = None
                if prop:
                    out.append(_to_dict(prop))

        for item in props_items:
            if not isinstance(item, dict):
                continue
            item_name = str(item.get("name") or "").strip()
            if item_name and item_name not in marked_names and item_name not in prompt_text:
                continue
            prop_id = item.get("db_id") or item.get("props_db_id") or item.get("id")
            prop = None
            if prop_id:
                try:
                    prop = PropsModel.get_by_id(int(prop_id))
                except Exception:
                    prop = None
            if not prop and world_id and item_name:
                try:
                    prop = PropsModel.get_by_name(int(world_id), item_name)
                except Exception:
                    prop = None
            out.append(_to_dict(prop) if prop else item)

        if world_id:
            try:
                world_props = PropsModel.list_by_world(int(world_id), page=1, page_size=1000).get("data", [])
            except Exception:
                world_props = []
            for prop in world_props:
                name = prop.get("name")
                if name and name in prompt_text:
                    out.append(prop)
        return self._merge_named_items(out)

    def _selected_assets(self, scene: Any) -> Dict[str, Optional[Dict[str, Any]]]:
        selected: Dict[str, Optional[Dict[str, Any]]] = {}
        for asset_type in ("first_frame", "last_frame", "video"):
            asset_id = _get_field(scene, _asset_selected_field(asset_type))
            selected[asset_type] = self._asset_info(asset_id) if asset_id else None
        return selected

    def _selected_asset_for_scene(self, scene: Any, asset_type: str) -> Optional[Dict[str, Any]]:
        asset_id = _get_field(scene, _asset_selected_field(asset_type))
        return self._asset_info(asset_id) if asset_id else None

    def _normalize_batch_limit(self, limit: Optional[int]) -> int:
        """归一化 batch limit。

        - limit 缺省/空 → UNLIMITED_BATCH_LIMIT (0)，表示规划全部缺失场景、不截断；
        - 显式传 0 → 同样视为无限制（与缺省一致，便于调用方显式表达）；
        - 显式传正整数 → clamp 到 [1, MAX_BATCH_LIMIT]。
        """
        unlimited = StoryboardAutoGenerateConstants.UNLIMITED_BATCH_LIMIT
        max_limit = StoryboardAutoGenerateConstants.MAX_BATCH_LIMIT
        if limit in (None, ""):
            return unlimited
        try:
            value = int(limit)
        except (TypeError, ValueError):
            return unlimited
        if value <= 0:
            return unlimited
        return max(1, min(value, max_limit))

    def _asset_info(self, asset_id: Any) -> Optional[Dict[str, Any]]:
        """读取 scene_asset；result_url 优先用 asset 自身，tool 仅作兜底。

        宫格拆分后多个 first_frame asset 共享同一 ai_tool：
        - asset.result_url = 单格 first_frame/...
        - ai_tools.result_url = 整张宫格 temp/...
        若无条件用 tool 覆盖，批量图生视频会误用宫格图作输入（故事板 #15 复现）。
        对齐 api/storyboard.py::_asset_task_info。
        """
        asset = StoryboardSceneAssetModel.get_by_id(int(asset_id))
        if not asset:
            return None
        info = _to_dict(asset)
        asset_result = (info.get("result_url") or "").strip()
        tool_id = info.get("ai_tool_id")
        if tool_id:
            tool = AIToolsModel.get_by_id(int(tool_id))
            tool_info = _to_dict(tool) if tool else None
            if tool_info:
                info["ai_tool"] = tool_info
                info["status"] = tool_info.get("status")
                info["message"] = tool_info.get("message")
                tool_result = (tool_info.get("result_url") or "").strip()
                # 仅当 asset 尚无 result_url 时用 tool 兜底；已有单格结果绝不覆盖
                if asset_result:
                    info["result_url"] = _public_upload_url(asset_result)
                elif tool_result:
                    info["result_url"] = _public_upload_url(tool_result)
                else:
                    info["result_url"] = None
        elif asset_result:
            info["result_url"] = _public_upload_url(asset_result)
        return info

    def _compose_image_prompt(
        self,
        scene: Any,
        storyboard: Any,
        prompt_json: Dict[str, Any],
        characters: Sequence[Dict[str, Any]],
        location: Optional[Dict[str, Any]],
        props: Sequence[Dict[str, Any]],
    ) -> str:
        # 提示词只保留「画面本身需要呈现」的文本信息：
        #   画风(style) + 构图(composition_preference) + 画面描述(scene_desc)
        #   + 镜头景别(perspective) + 光照(lighting)
        # 不再拼接 location/character/prop 的名字与设定描述：
        # 这些实体的视觉特征已通过「参考图 + 参考图说明（图N是角色/道具/场景：...）」
        # 由生图模型识别。把设定档案（尤其道具的「规格/功能/背景/剧情作用/象征意义」、
        # 场景的「类型/规模/剧情作用」、角色外貌）塞进文本会浪费 token 且干扰画面，
        # 也与「角色外貌交给角色库/参考图」的解析规则保持一致。
        del characters, location, props  # 保留签名以兼容调用方，仅不再用于拼接
        parts = [
            prompt_json.get("scene_desc"),
            prompt_json.get("perspective"),
            prompt_json.get("lighting"),
        ]
        title = _get_field(scene, "title")
        if title:
            parts.insert(0, title)
        prompt_text = "\n".join(str(part).strip() for part in parts if str(part or "").strip())
        return append_storyboard_visual_suffix(
            prompt_text,
            style=_get_field(storyboard, "style"),
            composition_preference=_get_field(storyboard, "composition_preference"),
        )

    def _collect_reference_images(
        self,
        storyboard: Any,
        characters: Sequence[Dict[str, Any]],
        location: Optional[Dict[str, Any]],
        props: Sequence[Dict[str, Any]],
        selected_assets: Dict[str, Optional[Dict[str, Any]]],
    ) -> List[str]:
        urls: List[str] = []
        urls.append(_get_field(storyboard, "style_reference_image"))
        for item in characters:
            urls.extend(_extract_reference_urls(item))
        if location:
            urls.extend(_extract_reference_urls(location))
        for prop in props:
            urls.extend(_extract_reference_urls(prop))
        for asset in selected_assets.values():
            if asset and asset.get("result_url"):
                urls.append(asset["result_url"])
        return _dedupe([_public_upload_url(url) for url in urls])

    def _collect_reference_image_items(
        self,
        prompt_json: Dict[str, Any],
        video_prompt: str,
        characters: Sequence[Dict[str, Any]],
        location: Optional[Dict[str, Any]],
        props: Sequence[Dict[str, Any]],
        world_id: Any = None,
    ) -> List[Dict[str, Any]]:
        """Build reference items from prompt tags; each tagged role is resolved independently.

        Mirrors video_workflow shot-frame collection: user-added `【【角色】】` that were
        not in the original split still resolve via world library lookup.
        """
        character_list = list(characters or [])
        tagged_names = extract_storyboard_reference_names(prompt_json, video_prompt).get("characters") or []
        by_name = {
            str(item.get("name") or "").strip(): item
            for item in character_list
            if str(item.get("name") or "").strip()
        }
        if world_id not in (None, ""):
            for name in tagged_names:
                if name in by_name:
                    continue
                try:
                    character = CharacterModel.get_by_name(int(world_id), name)
                except Exception as exc:
                    logger.warning(
                        "[storyboard-ref] character lookup failed name=%r world_id=%s err=%s",
                        name,
                        world_id,
                        exc,
                    )
                    character = None
                if character:
                    data = _to_dict(character)
                    character_list.append(data)
                    by_name[name] = data
                else:
                    logger.warning(
                        "[storyboard-ref] tagged character not found in world library: "
                        "name=%r world_id=%s",
                        name,
                        world_id,
                    )

        raw_items = build_storyboard_reference_items(
            prompt_json=prompt_json,
            video_prompt=video_prompt,
            characters=character_list,
            props=list(props or []),
            location=location,
        )
        role_names_with_url = {
            str(item.get("name") or "").strip()
            for item in raw_items
            if item.get("type") == "角色" and item.get("url")
        }
        for name in tagged_names:
            if name not in role_names_with_url:
                logger.warning(
                    "[storyboard-ref] tagged character has no usable reference image: name=%r",
                    name,
                )

        items: List[Dict[str, Any]] = []
        seen = set()
        source_type_map = {
            "角色": "character",
            "道具": "prop",
            "场景": "location",
        }
        for item in raw_items:
            url = _public_upload_url(item.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            item_type = item.get("type") or "参考图"
            name = item.get("name") or ""
            variant_label = item.get("variant_label") or ""
            display_label = f"{item_type}：{name}" if name else item_type
            if variant_label:
                display_label = f"{display_label}，{variant_label}"
            items.append({
                "type": item_type,
                "source_type": source_type_map.get(item_type, "reference"),
                "name": name,
                "variant_label": variant_label,
                "label": display_label,
                "url": url,
            })
        return items

    def _resolve_source_image(self, context: Dict[str, Any], source_image: Optional[str]) -> str:
        if source_image and source_image not in {"selected_first_frame", "selected_last_frame"}:
            return source_image
        selected_key = "last_frame" if source_image == "selected_last_frame" else "first_frame"
        asset = context["selected_assets"].get(selected_key)
        if asset and asset.get("result_url"):
            return asset["result_url"]
        raise StoryboardCliError("source_image_missing", f"{selected_key} image is not ready")

    def _resolve_image_edit_urls(
        self,
        context: Dict[str, Any],
        source_image: Optional[str],
        reference_urls: Sequence[str],
    ) -> List[str]:
        urls: List[str] = []
        urls.extend(reference_urls)
        if source_image:
            urls.append(self._resolve_source_image(context, source_image))
        resolved = _dedupe([_public_upload_url(url) for url in urls])
        if not resolved:
            raise StoryboardCliError("source_image_missing", "image_edit requires at least one reference image")
        return [str(url) for url in resolved]

    def _with_source_image_legend(
        self,
        reference_items: Sequence[Dict[str, Any]],
        context: Dict[str, Any],
        source_image: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Append the previous-frame (source_image) as an asset legend item.

        Keeps the reference legend aligned with the image-edit URL queue: when
        the previous storyboard frame is appended after role/prop/location
        references, the legend gets a matching "图N是前一分镜。" entry so the
        image model knows what each URL represents.
        """
        if not source_image:
            return list(reference_items)
        try:
            resolved_source = self._resolve_source_image(context, source_image)
        except StoryboardCliError:
            return list(reference_items)
        public_source = _public_upload_url(resolved_source)
        if not public_source:
            return list(reference_items)
        existing_urls = {item.get("url") for item in reference_items}
        if public_source in existing_urls:
            return list(reference_items)
        legend_items = list(reference_items)
        legend_items.append({
            "type": "前一分镜",
            "source_type": "asset",
            "name": "",
            "label": "前一分镜",
            "url": public_source,
        })
        return legend_items

    def _append_reference_prompt_suffix(
        self,
        prompt: str,
        reference_items: Sequence[Dict[str, Any]],
    ) -> str:
        if not reference_items:
            return prompt
        normalized = []
        fallback_lines = []
        source_type_map = {
            "character": "角色",
            "prop": "道具",
            "location": "场景",
            "style": "全局画风参考图",
            "asset": "前一分镜",
        }
        for index, item in enumerate(reference_items, start=1):
            item_type = item.get("type") or source_type_map.get(item.get("source_type") or "")
            name = item.get("name") or ""
            if item_type:
                # item_type alone is enough (e.g. asset legend with empty name),
                # which build_reference_legend renders as "图N是{type}。".
                normalized.append({"type": item_type, "name": name, "url": item.get("url") or ""})
            else:
                fallback_lines.append(f"图{index}是{item.get('label') or '参考图'}。")
        if normalized and not fallback_lines:
            return append_reference_legend(prompt, normalized)
        suffix = "\n".join(fallback_lines)
        return f"{prompt}\n\n参考图说明：\n{suffix}"

    def _resolve_video_image_urls(self, context: Dict[str, Any], image_mode: str) -> str:
        selected = context["selected_assets"]
        first_url = (selected.get("first_frame") or {}).get("result_url")
        last_url = (selected.get("last_frame") or {}).get("result_url")
        # 拒绝宫格整图作为图生视频输入（应使用选中分镜单格 first_frame）
        if first_url and self._is_storyboard_grid_composite_url(first_url):
            raise StoryboardCliError(
                "invalid_first_frame_for_video",
                "选中首帧指向宫格整图，请确认分镜已拆分并选中单格 first_frame 资产",
                payload={"first_frame_url": first_url},
            )
        if image_mode == "first_last_frame":
            urls = [first_url, last_url]
        elif image_mode == "first_last_with_ref":
            urls = [first_url, last_url] + context.get("reference_images", [])
        elif image_mode == "multi_reference":
            # 全能参考：首帧优先作为主参考，叠加角色/场景/道具参考图与全局画风参考图。
            urls = []
            if first_url:
                urls.append(first_url)
            urls.extend(context.get("reference_images", []))
            storyboard = context.get("storyboard")
            style_ref = _get_field(storyboard, "style_reference_image") if storyboard else None
            if style_ref:
                urls.append(_public_upload_url(style_ref))
        else:
            raise StoryboardCliError("invalid_image_mode", f"invalid image_mode: {image_mode}")
        urls = _dedupe(urls)
        if not urls:
            raise StoryboardCliError("source_image_missing", "image_to_video requires at least one image url")
        return ",".join(str(url) for url in urls)

    @staticmethod
    def _is_storyboard_grid_composite_url(url: Any) -> bool:
        value = str(url or "").lower()
        if not value:
            return False
        if "/storyboard/temp/" in value:
            return True
        if "/grid/" in value or "grid_result" in value or "grid-image" in value:
            return True
        return False

    def _build_storyboard_scenes_from_parsed_script(self, parsed_data: dict, style: str = "") -> List[dict]:
        character_db_map = self._build_character_db_map(parsed_data)
        character_name_map = self._build_character_name_map(parsed_data)
        location_map = self._build_location_map(parsed_data)
        prop_map = self._build_prop_map(parsed_data)
        spatial_world = parsed_data.get("spatial_world") if isinstance(parsed_data.get("spatial_world"), dict) else None
        scenes: List[dict] = []

        for group in parsed_data.get("shot_groups") or []:
            group_name = group.get("group_name") or ""
            group_type = group.get("group_type") or ""
            # act_name：优先用 group.act_title（LLM 显式输出的幕名），其次从 group_name 剥掉 " - 片段N" 后缀
            raw_act = group.get("act_title") or group.get("act")
            if raw_act:
                act_name = str(raw_act).strip() or None
            elif group_name:
                _cleaned = re.sub(r"\s*-\s*片段\d+$", "", str(group_name)).strip()
                act_name = _cleaned or None
            else:
                act_name = None
            for shot in group.get("shots") or []:
                scene_index = len(scenes) + 1
                location = location_map.get(str(shot.get("location_id"))) or {}
                location_name = shot.get("location_name") or location.get("name") or ""
                location_db_id = shot.get("db_location_id", location.get("location_db_id"))
                camera_angle = shot.get("camera_angle") or ""
                shot_type = shot.get("shot_type") or ""

                shot_props = []
                for prop_id in shot.get("props_present") or []:
                    prop = prop_map.get(str(prop_id)) or {}
                    shot_props.append({
                        "id": prop.get("id") or prop_id,
                        "name": prop.get("name") or "",
                        "db_id": prop.get("db_id") or prop.get("props_db_id"),
                    })

                character_names = []
                for raw_character_id in shot.get("characters_present") or []:
                    name = character_name_map.get(str(raw_character_id))
                    if name:
                        character_names.append(name)

                dialogues = []
                for dialogue in shot.get("dialogue") or []:
                    text = str(dialogue.get("text") or "").strip()
                    if not text:
                        continue
                    dialogues.append({
                        "character_id": self._dialogue_character_id(dialogue, character_db_map),
                        "text": text,
                        "speed": 1.0,
                        "volume": 100,
                    })

                from services.storyboard_scene_type import resolve_scene_video_type
                resolved_video_type, presentation_meta = resolve_scene_video_type(shot, dialogues)

                prompt_payload = {
                    "perspective": self._compact_join([camera_angle, shot_type], " / "),
                    "style": style or parsed_data.get("style") or "",
                    "scene_desc": self._compact_join([
                        shot.get("opening_frame_description"),
                        shot.get("scene_detail"),
                    ]),
                    "character_desc": "、".join(dict.fromkeys(character_names)),
                    "location": {
                        "id": location_db_id,
                        "name": location_name,
                    },
                    "props": shot_props,
                    "source": {
                        "group_id": group.get("group_id"),
                        "group_name": group_name,
                        "group_type": group_type,
                        "shot_id": shot.get("shot_id"),
                        "shot_number": shot.get("shot_number"),
                        "location_id": shot.get("location_id"),
                        "location_name": location_name,
                        "location_db_id": location_db_id,
                        "narrative_purpose": shot.get("narrative_purpose"),
                        "difficulty_reason": shot.get("difficulty_reason"),
                    },
                }
                if spatial_world:
                    prompt_payload["spatial_world"] = spatial_world
                if isinstance(shot.get("spatial_layout"), dict):
                    prompt_payload["spatial_layout"] = shot.get("spatial_layout")

                scenes.append({
                    "title": f"分镜{scene_index}",
                    "duration": max(1.0, self._safe_float(shot.get("duration"), 5.0)),
                    "difficulty": SceneDifficulty.normalize(shot.get("difficulty")),
                    "act_name": act_name,
                    "prompt": prompt_payload,
                    "video_prompt": self._compact_join([
                        shot.get("description"),
                        shot.get("scene_detail"),
                        shot.get("action"),
                        f"镜头运动：{shot.get('camera_movement')}" if shot.get("camera_movement") else None,
                        f"叙事目的：{shot.get('narrative_purpose')}" if shot.get("narrative_purpose") else None,
                    ]),
                    "video_type": resolved_video_type,
                    # 声音同出：数字人分镜 LTX2.3 产物已内嵌口型音轨，导出时保留原音轨、跳过 TTS 混音
                    "audio_embedded": resolved_video_type == SceneVideoType.DIGITAL_HUMAN,
                    "video_config": {
                        "shot_type": shot_type,
                        "camera_angle": camera_angle,
                        "camera_movement": shot.get("camera_movement") or "",
                        **presentation_meta,
                    },
                    "dialogues": dialogues,
                })

        return scenes

    def _compact_join(self, parts: Sequence[Optional[str]], sep: str = "\n") -> str:
        return sep.join(str(part).strip() for part in parts if str(part or "").strip())

    def _safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _build_character_db_map(self, parsed_data: dict) -> Dict[str, Optional[int]]:
        return {
            str(character.get("id")): character.get("character_db_id")
            for character in (parsed_data.get("characters") or [])
            if character.get("id")
        }

    def _build_character_name_map(self, parsed_data: dict) -> Dict[str, str]:
        return {
            str(character.get("id")): character.get("name") or ""
            for character in (parsed_data.get("characters") or [])
            if character.get("id")
        }

    def _build_location_map(self, parsed_data: dict) -> Dict[str, dict]:
        return {
            str(location.get("id")): location
            for location in (parsed_data.get("locations") or [])
            if location.get("id")
        }

    def _build_prop_map(self, parsed_data: dict) -> Dict[str, dict]:
        return {
            str(prop.get("id")): prop
            for prop in (parsed_data.get("props") or [])
            if prop.get("id")
        }

    def _dialogue_character_id(
        self,
        dialogue: dict,
        character_db_map: Dict[str, Optional[int]],
    ) -> Optional[int]:
        raw_character_id = dialogue.get("character_id")
        if raw_character_id is None:
            return None
        db_character_id = character_db_map.get(str(raw_character_id))
        if db_character_id is None:
            return None
        return self._safe_int(db_character_id, None)

    def export_check(
        self,
        storyboard_id: int,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """导出前核查：检查所有分镜素材完整性，返回缺失清单。"""
        from services.storyboard_export_service import collect_export_plan

        self._ensure_storyboard_for_user(storyboard_id, user_id)

        plan = collect_export_plan(int(storyboard_id))
        details: List[Dict[str, Any]] = []
        ready_count = 0
        missing_count = 0

        for sc in plan.scenes:
            has_visual = sc.visual_type != "none"
            has_audio = len(sc.audios) > 0
            is_ready = has_visual and not sc.missing
            if is_ready:
                ready_count += 1
            else:
                missing_count += 1
            details.append({
                "index": sc.index,
                "scene_id": sc.scene_id,
                "title": sc.title,
                "visual_type": sc.visual_type,
                "audios": len(sc.audios),
                "missing": list(sc.missing),
                "ready": is_ready,
            })

        return {
            "success": True,
            "storyboard_id": int(storyboard_id),
            "title": plan.title,
            "episode_number": plan.episode_number,
            "total_scenes": len(plan.scenes),
            "ready_scenes": ready_count,
            "missing_scenes": missing_count,
            "details": details,
        }

    def export_full_video(
        self,
        storyboard_id: int,
        user_id: int,
        *,
        include_subtitles: bool = True,
    ) -> Dict[str, Any]:
        """导出整集视频：合成 MP4 + 上传 CDN，返回 download_url。"""
        import asyncio
        import os as _os
        from services.storyboard_export_service import (
            collect_export_plan,
            materialize_package_files,
            build_merged_video,
            upload_local_file_to_cdn,
            make_work_dir,
            cleanup_dir,
        )

        self._ensure_storyboard_for_user(storyboard_id, user_id)

        work = None
        try:
            work = make_work_dir(int(storyboard_id))
            plan = collect_export_plan(int(storyboard_id))
            if not plan.scenes:
                raise StoryboardCliError("no_scenes", "故事板没有分镜，无法导出")
            materialize_package_files(plan, _os.path.join(work, "package"))
            local_path = build_merged_video(
                plan, work, burn_subtitles=include_subtitles
            )
            download_url, filename = asyncio.run(
                upload_local_file_to_cdn(local_path, content_type="video/mp4")
            )
            return {
                "success": True,
                "download_url": download_url,
                "filename": filename,
            }
        finally:
            if work:
                cleanup_dir(work)

    def export_package(
        self,
        storyboard_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
        """导出素材压缩包：打包 zip + 上传 CDN，返回 download_url。"""
        import asyncio
        from services.storyboard_export_service import (
            collect_export_plan,
            build_package_zip,
            upload_local_file_to_cdn,
            make_work_dir,
            cleanup_dir,
        )

        self._ensure_storyboard_for_user(storyboard_id, user_id)

        work = None
        try:
            work = make_work_dir(int(storyboard_id))
            plan = collect_export_plan(int(storyboard_id))
            if not plan.scenes:
                raise StoryboardCliError("no_scenes", "故事板没有分镜，无法导出")
            zip_path = build_package_zip(plan, work)
            download_url, filename = asyncio.run(
                upload_local_file_to_cdn(zip_path, content_type="application/zip")
            )
            return {
                "success": True,
                "download_url": download_url,
                "filename": filename,
            }
        finally:
            if work:
                cleanup_dir(work)

    def _parse_script_to_shots_sync(self, **kwargs) -> Dict[str, Any]:
        import asyncio
        from llm.script_parser import parse_script_to_shots

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(parse_script_to_shots(**kwargs))
        raise StoryboardCliError("event_loop_running", "split_from_script CLI cannot run inside an active event loop")
