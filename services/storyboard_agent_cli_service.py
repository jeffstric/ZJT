import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config.config_util import get_config
from model.ai_tools import AIToolsModel
from model.character import CharacterModel
from model.location import LocationModel
from model.props import PropsModel
from model.script import ScriptModel
from model.storyboard import StoryboardModel
from model.storyboard_dialogue import StoryboardDialogueModel
from model.storyboard_scene import StoryboardSceneModel
from model.storyboard_scene_asset import StoryboardSceneAssetModel


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
        script = ScriptModel.get_by_id(int(script_id))
        if not script:
            raise StoryboardCliError("script_not_found", f"script not found: {script_id}")

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
            self._resolve_prompt_characters(prompt_json, world_id),
        )
        location = self._resolve_location(prompt_json)
        props = self._resolve_props(prompt_json, world_id, scene=scene)
        selected_assets = self._selected_assets(scene)

        image_prompt = self._compose_image_prompt(scene, storyboard, prompt_json, characters, location, props)
        video_prompt = _get_field(scene, "video_prompt") or image_prompt
        reference_image_items = self._collect_reference_image_items(
            storyboard, characters, location, props, selected_assets
        )
        reference_images = [item["url"] for item in reference_image_items]

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

    def split_from_script(
        self,
        storyboard_id: int,
        user_id: int,
        *,
        auth_token: str = "",
        model: str = "gemini-3-flash-preview",
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

        from api.storyboard import build_storyboard_scenes_from_parsed_script

        scenes_payload = build_storyboard_scenes_from_parsed_script(
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

    def _extract_character_names_from_prompt(self, prompt_json: Dict[str, Any]) -> List[str]:
        text = self._prompt_text(prompt_json)
        names: List[str] = []
        for pattern in (r"【【([^】]+)】】", r"\[\[([^\]]+)\]\]"):
            names.extend(match.strip() for match in re.findall(pattern, text) if match.strip())
        character_desc = prompt_json.get("character_desc")
        if character_desc:
            for part in re.split(r"[,，、/|；;。\s]+", str(character_desc)):
                part = part.strip()
                if part:
                    names.append(part)
        return _dedupe(names)

    def _resolve_prompt_characters(self, prompt_json: Dict[str, Any], world_id: Any) -> List[Dict[str, Any]]:
        if not world_id:
            return []
        characters: List[Dict[str, Any]] = []
        for name in self._extract_character_names_from_prompt(prompt_json):
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
        storyboard: Any,
        characters: Sequence[Dict[str, Any]],
        location: Optional[Dict[str, Any]],
        props: Sequence[Dict[str, Any]],
        selected_assets: Dict[str, Optional[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        seen = set()

        _append_reference_item(
            items,
            seen,
            _get_field(storyboard, "style_reference_image"),
            source_type="style",
        )
        for character in characters:
            name = character.get("name")
            for url in _extract_reference_urls(character):
                _append_reference_item(items, seen, url, source_type="character", name=name)
        if location:
            name = location.get("name")
            for url in _extract_reference_urls(location):
                _append_reference_item(items, seen, url, source_type="location", name=name)
        for prop in props:
            name = prop.get("name")
            for url in _extract_reference_urls(prop):
                _append_reference_item(items, seen, url, source_type="prop", name=name)
        for asset_type in ("first_frame", "last_frame"):
            asset = selected_assets.get(asset_type)
            if asset and asset.get("result_url"):
                label = "已有首帧" if asset_type == "first_frame" else "已有尾帧" if asset_type == "last_frame" else "已有视频封面"
                _append_reference_item(
                    items,
                    seen,
                    asset["result_url"],
                    source_type="asset",
                    name=label,
                    label=label,
                )
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
        if source_image:
            urls.append(self._resolve_source_image(context, source_image))
        urls.extend(reference_urls)
        if not urls:
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
        lines = [
            f"图{index}是{item.get('label') or '参考图'}。"
            for index, item in enumerate(reference_items, start=1)
        ]
        suffix = "\n".join(lines)
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

    def _parse_script_to_shots_sync(self, **kwargs) -> Dict[str, Any]:
        import asyncio
        from llm.script_parser import parse_script_to_shots

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(parse_script_to_shots(**kwargs))
        raise StoryboardCliError("event_loop_running", "split_from_script CLI cannot run inside an active event loop")
