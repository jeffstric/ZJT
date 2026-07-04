import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config.config_util import get_config, get_current_env
from config.constant import (
    StoryboardAgentCommandConstants,
    StoryboardAgentReadConstants,
    StoryboardAutoGenerateConstants,
)
from config.unified_config import SceneVideoType
from model.ai_tools import AIToolsModel
from model.character import CharacterModel
from model.location import LocationModel
from model.props import PropsModel
from model.script import ScriptModel
from model.storyboard import StoryboardModel
from model.storyboard_dialogue import StoryboardDialogueModel
from model.storyboard_image_batch import StoryboardImageBatchItemModel, StoryboardImageBatchJobModel
from model.storyboard_scene import StoryboardSceneModel, compute_sort_between, is_precision_exhausted
from model.storyboard_scene_asset import StoryboardSceneAssetModel
from model.world import WorldModel
from services.storyboard_reference_prompt_service import (
    append_reference_legend,
    build_storyboard_reference_items,
    reference_urls,
)


VALID_IMAGE_MODES = {"auto", "text_to_image", "image_edit"}
VALID_VIDEO_MODES = {"text_to_video", "image_to_video"}
VALID_ASSET_TYPES = {"first_frame", "last_frame", "video"}
IMAGE_ASSET_TYPES = {"first_frame", "last_frame"}


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
        "asset": "已有分镜图",
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
        style: Optional[str] = None,
        style_reference_image: Optional[str] = None,
        workflow_ratio: Optional[str] = None,
        composition_preference: Optional[str] = None,
        version: int = 1,
    ) -> Dict[str, Any]:
        user_id = self._require_user_id(user_id)
        script = self._ensure_script_for_user(script_id, user_id)

        world_id = _get_field(script, "world_id")
        if not world_id:
            raise StoryboardCliError("script_missing_world", f"script has no world_id: {script_id}")

        episode_number = int(_get_field(script, "episode_number") or 1)
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
            return {
                "success": True,
                "storyboard_id": int(_get_field(existing, "id")),
                "script_id": int(script_id),
                "created": False,
                "storyboard": _to_dict(existing),
            }

        storyboard_id = StoryboardModel.create(
            user_id=int(user_id),
            world_id=int(world_id),
            episode_number=episode_number,
            workflow_id=workflow_id,
            script_id=int(script_id),
            title=title if title is not None else (_get_field(script, "title") or ""),
            style=style,
            style_reference_image=style_reference_image,
            workflow_ratio=workflow_ratio,
            composition_preference=composition_preference,
            version=version,
        )
        storyboard = StoryboardModel.get_by_id(int(storyboard_id))
        return {
            "success": True,
            "storyboard_id": int(storyboard_id),
            "script_id": int(script_id),
            "created": True,
            "storyboard": _to_dict(storyboard) if storyboard else {"id": int(storyboard_id)},
        }

    def scene_context(self, scene_id: int, user_id: Optional[int] = None) -> Dict[str, Any]:
        scene, storyboard = self._load_scene_pair(scene_id)
        prompt_json = _parse_json(_get_field(scene, "prompt_json"), {}) or {}
        video_config = _parse_json(_get_field(scene, "video_config_json"), {}) or {}
        dialogues = StoryboardDialogueModel.list_by_scene(int(scene_id)) or []

        world_id = _get_field(storyboard, "world_id")
        characters = self._merge_named_items(
            self._load_dialogue_characters(dialogues),
            self._resolve_prompt_characters(prompt_json, world_id, scene=scene),
        )
        location = self._resolve_location(prompt_json)
        props = self._resolve_props(prompt_json, world_id, scene=scene)
        selected_assets = self._selected_assets(scene)

        image_prompt = self._compose_image_prompt(scene, storyboard, prompt_json, characters, location, props)
        video_prompt = _get_field(scene, "video_prompt") or image_prompt
        reference_image_items = self._collect_reference_image_items(
            prompt_json, video_prompt, characters, location, props
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

        if mode == "auto":
            mode = "image_edit" if reference_urls else "text_to_image"

        if mode == "text_to_image":
            result = self.submitter.text_to_image(
                user_id=str(user_id),
                world_id=world_id,
                auth_token=auth_token or "",
                prompt=prompt_text,
                aspect_ratio=ratio_value,
                count=int(count or 1),
                image_size=image_size,
            )
        else:
            image_urls = self._resolve_image_edit_urls(context, source_image, reference_urls)
            prompt_text = self._append_reference_prompt_suffix(prompt_text, reference_items)
            result = self.submitter.image_edit(
                user_id=str(user_id),
                world_id=world_id,
                auth_token=auth_token or "",
                prompt=prompt_text,
                image_url=",".join(image_urls),
                aspect_ratio=ratio_value,
                count=int(count or 1),
                image_size=image_size,
            )

        return self._finalize_submission(
            scene_id=scene_id,
            user_id=user_id,
            asset_type=asset_type,
            mode=mode,
            result=result,
            reference_images=reference_urls if mode == "image_edit" else [],
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
    ) -> Dict[str, Any]:
        if mode not in VALID_VIDEO_MODES:
            raise StoryboardCliError("invalid_mode", f"invalid video mode: {mode}")

        context = self.scene_context(scene_id, user_id=user_id)
        scene = context["scene"]
        storyboard = context["storyboard"]
        world_id = str(storyboard.get("world_id") or "")
        prompt_text = prompt or context["video_prompt"] or context["image_prompt"]
        ratio_value = ratio or storyboard.get("workflow_ratio") or "16:9"
        duration_value = int(duration_seconds or scene.get("duration") or 5)

        if mode == "text_to_video":
            result = self.submitter.text_to_video(
                user_id=str(user_id),
                world_id=world_id,
                auth_token=auth_token or "",
                prompt=prompt_text,
                ratio=ratio_value,
                duration_seconds=duration_value,
                count=int(count or 1),
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
        duration: int = 5,
        prompt_json: Optional[Any] = None,
        video_prompt: Optional[str] = None,
        video_type: str = SceneVideoType.VIDEO,
        video_config_json: Optional[Any] = None,
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
            duration=int(duration or 5),
            prompt_json=prompt_payload,
            video_prompt=video_prompt,
            video_type=video_type or SceneVideoType.VIDEO,
            video_config_json=video_config_payload,
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

        storyboard = StoryboardModel.get_by_id(int(storyboard_id))
        if not storyboard:
            raise StoryboardCliError("not_found", f"storyboard not found: {storyboard_id}")

        task_type = self._resolve_image_task_type(storyboard, task_type)
        self._sync_image_model_preference(user_id, storyboard, task_type)

        batch_limit = self._normalize_batch_limit(limit)
        planned_items = self._plan_image_batch_items(
            storyboard_id=int(storyboard_id),
            asset_type=asset_type,
            sequence_mode=sequence_mode,
            limit=batch_limit,
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
            ratio=ratio or _get_field(storyboard, "workflow_ratio"),
            image_size=image_size,
            count=int(count or 1),
            limit_count=batch_limit,
            stop_on_error=1 if stop_on_error else 0,
            status=StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_PENDING,
            extra_json={"task_type": task_type},
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
                },
            )
            scene_to_item_id[item["scene_id"]] = item_id
            created_items.append({**item, "id": item_id, "dependency_item_id": dependency_item_id})

        process_result = self.process_image_batch_jobs(job_id=job_id, limit_jobs=1)
        status = self.storyboard_image_batch_status(job_id=job_id)

        return {
            "success": True,
            "storyboard_id": int(storyboard_id),
            "user_id": int(user_id),
            "asset_type": asset_type,
            "sequence_mode": sequence_mode,
            "batch_id": job_id,
            "limit": batch_limit,
            "submitted_count": process_result.get("submitted_count", 0),
            "skipped_count": status.get("skipped_count", 0),
            "failed_count": status.get("failed_count", 0),
            "status": status.get("status"),
            "items": status.get("items", created_items),
        }

    def storyboard_image_batch_status(self, job_id: int, user_id: Optional[int] = None) -> Dict[str, Any]:
        job = StoryboardImageBatchJobModel.get_by_id(int(job_id))
        if not job:
            raise StoryboardCliError("not_found", f"storyboard image batch not found: {job_id}")
        if user_id and int(job.get("user_id") or 0) != int(user_id):
            raise StoryboardCliError("forbidden", "storyboard image batch does not belong to user")
        items = StoryboardImageBatchItemModel.list_by_job(int(job_id))
        return {
            "success": True,
            "batch_id": int(job_id),
            "storyboard_id": int(job.get("storyboard_id") or 0),
            "user_id": int(job.get("user_id") or 0),
            "asset_type": job.get("asset_type"),
            "sequence_mode": job.get("sequence_mode"),
            "status": self._batch_job_status_name(job.get("status")),
            "submitted_count": int(job.get("submitted_count") or 0),
            "completed_count": int(job.get("completed_count") or 0),
            "failed_count": int(job.get("failed_count") or 0),
            "skipped_count": int(job.get("skipped_count") or 0),
            "message": job.get("message") or "",
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

    def _process_one_image_batch_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        job_id = int(job["id"])
        StoryboardImageBatchJobModel.update(job_id, status=StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_RUNNING)
        items = StoryboardImageBatchItemModel.list_by_job(job_id)
        by_id = {int(item["id"]): item for item in items}
        submitted_count = 0

        for item in items:
            if int(item.get("status") or 0) != StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING:
                continue
            asset = self._asset_info(item.get("asset_id")) if item.get("asset_id") else None
            if asset and asset.get("result_url"):
                StoryboardImageBatchItemModel.update(
                    int(item["id"]),
                    status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_COMPLETED,
                    result_url=asset.get("result_url"),
                )
                item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_COMPLETED
                item["result_url"] = asset.get("result_url")
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
            dependency = by_id.get(int(item.get("dependency_item_id") or 0))
            reference_url = None
            reference_item_id = None
            if dependency:
                dep_status = int(dependency.get("status") or 0)
                if dep_status in (
                    StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
                    StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING,
                ):
                    continue
                if dep_status == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED and int(job.get("stop_on_error") or 0):
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
                extra_json={"submission": result},
            )
            item["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING
            item["project_ids"] = project_ids
            item["asset_id"] = selected_asset_id
            item["reference_item_id"] = reference_item_id
            item["reference_url"] = reference_url
            submitted_count += 1

        self._update_image_batch_job_counts(job_id)
        return {"submitted_count": submitted_count}

    def _update_image_batch_job_counts(self, job_id: int) -> None:
        items = StoryboardImageBatchItemModel.list_by_job(int(job_id))
        pending = sum(1 for item in items if int(item.get("status") or 0) == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING)
        running = sum(1 for item in items if int(item.get("status") or 0) == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING)
        completed = sum(1 for item in items if int(item.get("status") or 0) == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_COMPLETED)
        failed = sum(1 for item in items if int(item.get("status") or 0) == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED)
        skipped = sum(1 for item in items if int(item.get("status") or 0) == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_SKIPPED)
        submitted = sum(1 for item in items if item.get("ai_tool_id") or item.get("project_ids"))
        if pending or running:
            status = StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_RUNNING
        elif failed and completed:
            status = StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_PARTIAL
        elif failed:
            status = StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_FAILED
        else:
            status = StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_COMPLETED
        StoryboardImageBatchJobModel.update(
            int(job_id),
            status=status,
            submitted_count=submitted,
            completed_count=completed,
            failed_count=failed,
            skipped_count=skipped,
        )

    def _plan_image_batch_items(
        self,
        *,
        storyboard_id: int,
        asset_type: str,
        sequence_mode: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        sequence_mode = self._normalize_sequence_mode(sequence_mode)
        scenes = StoryboardSceneModel.list_by_storyboard(int(storyboard_id)) or []
        items: List[Dict[str, Any]] = []
        previous_group_key: Optional[str] = None
        previous_item: Optional[Dict[str, Any]] = None
        previous_by_group: Dict[str, Dict[str, Any]] = {}
        missing_count = 0

        for order_index, scene in enumerate(scenes, start=1):
            scene_id = int(_get_field(scene, "id"))
            group_key = self._scene_group_key(scene, previous_group_key, storyboard_id)
            previous_group_key = group_key
            selected_asset = self._selected_asset_for_scene(scene, asset_type)
            status = "pending"
            batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING
            result_url = None
            asset_id = selected_asset.get("id") if selected_asset else None
            ai_tool_id = selected_asset.get("ai_tool_id") if selected_asset else None
            project_ids = [ai_tool_id] if ai_tool_id else []

            if selected_asset and selected_asset.get("result_url"):
                status = "already_ready"
                batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_COMPLETED
                result_url = selected_asset.get("result_url")
            elif selected_asset and selected_asset.get("status") in StoryboardAutoGenerateConstants.RUNNING_STATUSES:
                status = "already_running"
                batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING
            elif missing_count >= int(limit):
                status = "limit_reached"
                batch_status = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_SKIPPED
            else:
                missing_count += 1

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
            }
            items.append(item)
            if batch_status != StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_SKIPPED:
                previous_item = item
                previous_by_group[group_key] = item
        return items

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
    ) -> Dict[str, Any]:
        storyboard = StoryboardModel.get_by_id(int(storyboard_id))
        if not storyboard:
            raise StoryboardCliError("not_found", f"storyboard not found: {storyboard_id}")

        model = self._resolve_split_model(storyboard, model)
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

        parsed_data = self._parse_script_to_shots_sync(
            script_content=content,
            max_group_duration=max_group_duration,
            world_id=_get_field(storyboard, "world_id"),
            model=model,
            force_medium_shot=force_medium_shot,
            no_bg_music=no_bg_music,
            split_multi_dialogue=split_multi_dialogue,
            language=language,
            dialogue_language=dialogue_language or language,
            prompt_language=prompt_language or language,
            auth_token=auth_token,
            vendor_id=vendor_id,
            model_id=model_id,
        )
        if not parsed_data or not parsed_data.get("shot_groups"):
            raise StoryboardCliError("parse_empty", "script parser returned no shot groups")

        scenes_payload = self._build_storyboard_scenes_from_parsed_script(
            parsed_data,
            style=_get_field(storyboard, "style") or "",
        )
        if not scenes_payload:
            raise StoryboardCliError("scene_payload_empty", "no scene payload generated")

        generated_count = StoryboardModel.create_scenes(int(storyboard_id), int(user_id), scenes_payload)
        if script_id != _get_field(storyboard, "script_id"):
            StoryboardModel.update(int(storyboard_id), script_id=int(script_id))

        return {
            "success": True,
            "storyboard_id": int(storyboard_id),
            "script_id": int(script_id),
            "generated_count": int(generated_count),
            "status": "generated",
            "scenes": self.list_scenes(int(storyboard_id), user_id=user_id).get("scenes", []),
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

    def _resolve_split_model(self, storyboard: Any, model: Optional[str]) -> str:
        explicit = str(model or "").strip()
        if explicit:
            return explicit
        config_model = str(self._storyboard_config(storyboard).get("selectedScriptSplitLlmModel") or "").strip()
        return config_model or StoryboardAgentCommandConstants.DEFAULT_SCRIPT_SPLIT_MODEL

    def _resolve_image_task_type(self, storyboard: Any, task_type: Optional[int]) -> Optional[int]:
        if task_type not in (None, ""):
            return int(task_type)
        configured = self._storyboard_config(storyboard).get("selectedImageTaskId")
        if configured in (None, ""):
            return None
        try:
            return int(configured)
        except (TypeError, ValueError):
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
    ) -> Dict[str, Any]:
        if not isinstance(result, dict):
            raise StoryboardCliError("submit_failed", "submitter returned invalid result")
        if result.get("success") is False:
            raise StoryboardCliError("submit_failed", str(result.get("error") or "submission failed"), payload=result)

        project_ids = _project_ids(result)
        if not project_ids:
            raise StoryboardCliError("missing_project_ids", "generation submitted without project_ids", payload=result)

        bind_result = self.bind_projects(scene_id, user_id, asset_type, project_ids)
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

    def _extract_character_names_from_prompt(self, prompt_json: Dict[str, Any], scene: Any = None) -> List[str]:
        text = self._visual_prompt_text(prompt_json, scene=scene)
        names: List[str] = []
        for pattern in (r"【【([^】]+)】】", r"\[\[([^\]]+)\]\]"):
            names.extend(match.strip() for match in re.findall(pattern, text) if match.strip())
        return _dedupe(names)

    def _resolve_prompt_characters(self, prompt_json: Dict[str, Any], world_id: Any, scene: Any = None) -> List[Dict[str, Any]]:
        if not world_id:
            return []
        characters: List[Dict[str, Any]] = []
        for name in self._extract_character_names_from_prompt(prompt_json, scene=scene):
            try:
                character = CharacterModel.get_by_name(int(world_id), name)
            except Exception:
                character = None
            if character:
                characters.append(_to_dict(character))
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
        default_limit = StoryboardAutoGenerateConstants.DEFAULT_BATCH_LIMIT
        max_limit = StoryboardAutoGenerateConstants.MAX_BATCH_LIMIT
        try:
            value = int(limit) if limit not in (None, "") else default_limit
        except (TypeError, ValueError):
            value = default_limit
        return max(1, min(value, max_limit))

    def _sync_image_model_preference(self, user_id: int, storyboard: Any, task_type: Optional[int]) -> None:
        if task_type in (None, ""):
            return
        try:
            from api.script_writer import set_text_to_image_model_id

            set_text_to_image_model_id(
                str(user_id),
                str(_get_field(storyboard, "world_id") or ""),
                int(task_type),
            )
        except Exception:
            pass

    def _asset_info(self, asset_id: Any) -> Optional[Dict[str, Any]]:
        asset = StoryboardSceneAssetModel.get_by_id(int(asset_id))
        if not asset:
            return None
        info = _to_dict(asset)
        tool_id = info.get("ai_tool_id")
        if tool_id:
            tool = AIToolsModel.get_by_id(int(tool_id))
            tool_info = _to_dict(tool) if tool else None
            if tool_info:
                info["ai_tool"] = tool_info
                info["status"] = tool_info.get("status")
                info["message"] = tool_info.get("message")
                if tool_info.get("result_url"):
                    info["result_url"] = _public_upload_url(tool_info.get("result_url"))
        elif info.get("result_url"):
            info["result_url"] = _public_upload_url(info.get("result_url"))
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
        parts = [
            _get_field(storyboard, "style"),
            _get_field(storyboard, "composition_preference"),
            prompt_json.get("scene_desc"),
            prompt_json.get("perspective"),
            prompt_json.get("lighting"),
        ]
        if location:
            parts.append(location.get("name"))
            parts.append(location.get("description"))
        for character in characters:
            parts.append(character.get("name"))
            parts.append(character.get("appearance"))
        for prop in props:
            parts.append(prop.get("name"))
            parts.append(prop.get("content") or prop.get("description"))
        title = _get_field(scene, "title")
        if title:
            parts.insert(0, title)
        return "\n".join(str(part).strip() for part in parts if str(part or "").strip())

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
    ) -> List[Dict[str, Any]]:
        raw_items = build_storyboard_reference_items(
            prompt_json=prompt_json,
            video_prompt=video_prompt,
            characters=list(characters or []),
            props=list(props or []),
            location=location,
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
            items.append({
                "type": item_type,
                "source_type": source_type_map.get(item_type, "reference"),
                "name": name,
                "label": f"{item_type}：{name}" if name else item_type,
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
            "asset": "已有分镜图",
        }
        for index, item in enumerate(reference_items, start=1):
            item_type = item.get("type") or source_type_map.get(item.get("source_type") or "")
            name = item.get("name") or ""
            if item_type and name:
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
        if image_mode == "first_last_frame":
            urls = [first_url, last_url]
        elif image_mode == "first_last_with_ref":
            urls = [first_url, last_url] + context.get("reference_images", [])
        elif image_mode == "multi_reference":
            urls = context.get("reference_images", [])
        else:
            raise StoryboardCliError("invalid_image_mode", f"invalid image_mode: {image_mode}")
        urls = _dedupe(urls)
        if not urls:
            raise StoryboardCliError("source_image_missing", "image_to_video requires at least one image url")
        return ",".join(str(url) for url in urls)

    def _build_storyboard_scenes_from_parsed_script(self, parsed_data: dict, style: str = "") -> List[dict]:
        character_db_map = self._build_character_db_map(parsed_data)
        character_name_map = self._build_character_name_map(parsed_data)
        location_map = self._build_location_map(parsed_data)
        prop_map = self._build_prop_map(parsed_data)
        scenes: List[dict] = []

        for group in parsed_data.get("shot_groups") or []:
            group_name = group.get("group_name") or ""
            group_type = group.get("group_type") or ""
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

                scenes.append({
                    "title": f"分镜{scene_index}",
                    "duration": max(1, self._safe_int(shot.get("duration"), 5)),
                    "prompt": {
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
                        },
                    },
                    "video_prompt": self._compact_join([
                        shot.get("description"),
                        shot.get("scene_detail"),
                        shot.get("action"),
                        f"镜头运动：{shot.get('camera_movement')}" if shot.get("camera_movement") else None,
                        f"叙事目的：{shot.get('narrative_purpose')}" if shot.get("narrative_purpose") else None,
                    ]),
                    "video_type": SceneVideoType.VIDEO,
                    "video_config": {
                        "shot_type": shot_type,
                        "camera_angle": camera_angle,
                        "camera_movement": shot.get("camera_movement") or "",
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

    def _parse_script_to_shots_sync(self, **kwargs) -> Dict[str, Any]:
        import asyncio
        from llm.script_parser import parse_script_to_shots

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(parse_script_to_shots(**kwargs))
        raise StoryboardCliError("event_loop_running", "split_from_script CLI cannot run inside an active event loop")
