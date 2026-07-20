"""Shared command registry for storyboard agent CLI and HTTP APIs."""
from typing import Any, Dict, List, Optional, Sequence

from config.config_util import get_current_env
from config.constant import StoryboardAgentCommandConstants
from services.storyboard_agent_cli_service import (
    StoryboardAgentCliService,
    StoryboardCliError,
)


def _to_int(value: Any, name: str, default: Optional[int] = None) -> Optional[int]:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise StoryboardCliError("invalid_parameter", f"{name} must be an integer")


def _to_float(value: Any, name: str, default: Optional[float] = None) -> Optional[float]:
    """将参数转为 float，用于 duration 等 DECIMAL 字段（不再截断小数）。"""
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise StoryboardCliError("invalid_parameter", f"{name} must be a number")


def _to_required_int(value: Any, name: str) -> int:
    if value in (None, ""):
        raise StoryboardCliError("missing_parameter", f"{name} is required")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise StoryboardCliError("invalid_parameter", f"{name} must be an integer")


def _to_required_str(value: Any, name: str, hint: str = "") -> str:
    """要求非非空字符串。用于 split-from-script 的 model 等强制参数，
    避免回退到服务端默认模型（CLI 路径必须显式指定）。"""
    if value in (None, ""):
        msg = f"{name} is required"
        if hint:
            msg = f"{msg} ({hint})"
        raise StoryboardCliError("missing_parameter", msg)
    return str(value).strip()


def _to_int_in_range(
    value: Any, name: str, default: int, min_value: int, max_value: int,
) -> int:
    """将参数转为 int 并强制范围校验。用于 max_group_duration 等需要约束范围的参数。"""
    if value in (None, ""):
        return default
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise StoryboardCliError("invalid_parameter", f"{name} must be an integer")
    if result < min_value or result > max_value:
        raise StoryboardCliError(
            "invalid_parameter",
            f"{name} must be between {min_value} and {max_value} (got {result})",
        )
    return result


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _project_ids(value: Any) -> List[int]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        values: Sequence[Any] = [item.strip() for item in value.split(",")]
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        values = [value]
    out: List[int] = []
    for item in values:
        if item in (None, ""):
            continue
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            raise StoryboardCliError("invalid_parameter", "project_ids must be integers")
    return out


class StoryboardAgentCommandService:
    def __init__(self, service: Optional[StoryboardAgentCliService] = None):
        self.service = service or StoryboardAgentCliService()

    def _with_environment(self, result: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(result or {})
        payload["environment"] = get_current_env()
        return payload

    def schema(self) -> Dict[str, Any]:
        return {
            "success": True,
            "environment": get_current_env(),
            "commands": [
                {
                    "name": "list-worlds",
                    "permission": "world:view",
                    "params": ["page", "page_size", "keyword", "include_full_story_outline"],
                },
                {
                    "name": "list-world-scripts",
                    "permission": "script:view",
                    "params": ["world_id", "page", "page_size", "include_content", "include_full_story_outline"],
                },
                {
                    "name": "get-script",
                    "permission": "script:view",
                    "params": ["script_id"],
                },
                {
                    "name": "list-world-characters",
                    "permission": "character:view",
                    "params": ["world_id", "page", "page_size", "keyword", "include_full_story_outline"],
                },
                {
                    "name": "list-world-locations",
                    "permission": "location:view",
                    "params": ["world_id", "page", "page_size", "keyword", "include_full_story_outline"],
                },
                {
                    "name": "list-world-props",
                    "permission": "props:view",
                    "params": ["world_id", "page", "page_size", "keyword", "include_full_story_outline"],
                },
                {
                    "name": "world-context",
                    "permission": "world:view",
                    "params": ["world_id", "page_size", "include_script_content", "include_full_story_outline"],
                    "response": {
                        "scripts": "Page<object>",
                        "characters": "Page<object>",
                        "locations": "Page<object>",
                        "props": "Page<object>",
                        "page_shape": ["total", "page", "page_size", "data"],
                    },
                },
                {
                    "name": "create-storyboard-from-script",
                    "permission": "storyboard:create",
                    "params": [
                        "script_id", "title", "workflow_id",
                        "model", "model_id", "vendor_id",
                    ],
                    # style / style_reference_image / workflow_ratio / composition_preference
                    # 已移除：画风与构图由世界表继承，禁止命令行差异化覆盖。
                },
                {
                    "name": "split-from-script",
                    "permission": "storyboard:update",
                    "params": [
                        "storyboard_id",
                        "model",
                        "model_id",
                        "vendor_id",
                        "max_group_duration",
                        "language",
                        "force_overwrite_subscene_grids",
                    ],
                },
                {
                    "name": "scene-context",
                    "permission": "storyboard:view",
                    "params": ["scene_id"],
                },
                {
                    "name": "list-scenes",
                    "permission": "storyboard:view",
                    "params": ["storyboard_id"],
                },
                {
                    "name": "insert-scene",
                    "permission": "storyboard:update",
                    "params": [
                        "storyboard_id",
                        "after_scene_id",
                        "before_scene_id",
                        "title",
                        "duration",
                        "prompt_json",
                        "video_prompt",
                        "video_type",
                        "video_config_json",
                        "difficulty",
                        "act_name",
                    ],
                },
                {
                    "name": "generate-image",
                    "permission": "storyboard:generate",
                    "params": ["scene_id", "mode", "asset_type", "prompt", "source_image", "ratio", "image_size", "count"],
                },
                {
                    "name": "auto-generate-missing-images",
                    "permission": "storyboard:generate",
                    "params": [
                        "storyboard_id",
                        "asset_type",
                        "mode",
                        "ratio",
                        "image_size",
                        "count",
                        "limit",
                        "task_type",
                        "sequence_mode",
                    ],
                },
                {
                    "name": "auto-generate-missing-videos",
                    "permission": "storyboard:generate",
                    "params": [
                        "storyboard_id",
                        "limit",
                        "task_type",
                        "ratio",
                        "sequence_mode",
                    ],
                },
                {
                    "name": "generate-video",
                    "permission": "storyboard:generate",
                    "params": ["scene_id", "mode", "image_mode", "prompt", "ratio", "duration_seconds", "count"],
                },
                {
                    "name": "task-status",
                    "permission": "storyboard:view",
                    "params": ["scene_id", "asset_type"],
                },
                {
                    "name": "storyboard-task-status",
                    "permission": "storyboard:view",
                    "params": ["storyboard_id", "asset_type"],
                    "response": {
                        "scenes": "array",
                        "result_url_path": "scenes[].selected_assets.first_frame.result_url",
                    },
                },
                {
                    "name": "storyboard-image-batch-status",
                    "permission": "storyboard:view",
                    "params": ["batch_id"],
                },
                {
                    "name": "bind-projects",
                    "permission": "storyboard:update",
                    "params": ["scene_id", "asset_type", "project_ids"],
                },
                {
                    "name": "update-scene",
                    "permission": "storyboard:update",
                    "params": [
                        "scene_id",
                        "duration",
                        "title",
                        "prompt_json",
                        "video_prompt",
                        "video_type",
                        "video_config_json",
                        "difficulty",
                        "act_name",
                    ],
                },
                {
                    "name": "export-check",
                    "permission": "storyboard:export",
                    "params": ["storyboard_id"],
                    "response": {
                        "total_scenes": "int",
                        "ready_scenes": "int",
                        "missing_scenes": "int",
                        "details": "array",
                    },
                },
                {
                    "name": "export-full-video",
                    "permission": "storyboard:export",
                    "params": ["storyboard_id", "include_subtitles"],
                    "response": {
                        "download_url": "string",
                        "filename": "string",
                    },
                },
                {
                    "name": "export-package",
                    "permission": "storyboard:export",
                    "params": ["storyboard_id"],
                    "response": {
                        "download_url": "string",
                        "filename": "string",
                    },
                },
            ],
        }

    def execute(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return self._with_environment(self._execute_raw(command, params))

    def _execute_raw(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(params or {})

        if command == "list-worlds":
            return self.service.list_worlds(
                user_id=_to_int(data.get("user_id"), "user_id"),
                page=_to_int(data.get("page"), "page", 1) or 1,
                page_size=_to_int(data.get("page_size"), "page_size", 20) or 20,
                keyword=data.get("keyword"),
                include_full_story_outline=_to_bool(data.get("include_full_story_outline")),
            )

        if command == "list-world-scripts":
            return self.service.list_world_scripts(
                world_id=_to_required_int(data.get("world_id"), "world_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
                page=_to_int(data.get("page"), "page", 1) or 1,
                page_size=_to_int(data.get("page_size"), "page_size", 20) or 20,
                include_content=_to_bool(data.get("include_content")),
                include_full_story_outline=_to_bool(data.get("include_full_story_outline")),
            )

        if command == "get-script":
            return self.service.get_script(
                script_id=_to_required_int(data.get("script_id"), "script_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
            )

        if command == "list-world-characters":
            return self.service.list_world_characters(
                world_id=_to_required_int(data.get("world_id"), "world_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
                page=_to_int(data.get("page"), "page", 1) or 1,
                page_size=_to_int(data.get("page_size"), "page_size", 20) or 20,
                keyword=data.get("keyword"),
                include_full_story_outline=_to_bool(data.get("include_full_story_outline")),
            )

        if command == "list-world-locations":
            return self.service.list_world_locations(
                world_id=_to_required_int(data.get("world_id"), "world_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
                page=_to_int(data.get("page"), "page", 1) or 1,
                page_size=_to_int(data.get("page_size"), "page_size", 20) or 20,
                keyword=data.get("keyword"),
                include_full_story_outline=_to_bool(data.get("include_full_story_outline")),
            )

        if command == "list-world-props":
            return self.service.list_world_props(
                world_id=_to_required_int(data.get("world_id"), "world_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
                page=_to_int(data.get("page"), "page", 1) or 1,
                page_size=_to_int(data.get("page_size"), "page_size", 20) or 20,
                keyword=data.get("keyword"),
                include_full_story_outline=_to_bool(data.get("include_full_story_outline")),
            )

        if command == "world-context":
            return self.service.world_context(
                world_id=_to_required_int(data.get("world_id"), "world_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
                page_size=_to_int(data.get("page_size"), "page_size", 100) or 100,
                include_script_content=_to_bool(data.get("include_script_content")),
                include_full_story_outline=_to_bool(data.get("include_full_story_outline")),
            )

        if command == "scene-context":
            return self.service.scene_context(
                scene_id=_to_required_int(data.get("scene_id"), "scene_id"),
                user_id=_to_int(data.get("user_id"), "user_id"),
            )

        if command == "list-scenes":
            return self.service.list_scenes(
                storyboard_id=_to_required_int(data.get("storyboard_id"), "storyboard_id"),
                user_id=_to_int(data.get("user_id"), "user_id"),
            )

        if command == "insert-scene":
            return self.service.insert_scene(
                storyboard_id=_to_required_int(data.get("storyboard_id"), "storyboard_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
                after_scene_id=_to_int(data.get("after_scene_id") or data.get("after_id"), "after_scene_id"),
                before_scene_id=_to_int(data.get("before_scene_id") or data.get("before_id"), "before_scene_id"),
                prev_id=_to_int(data.get("prev_id"), "prev_id"),
                next_id=_to_int(data.get("next_id"), "next_id"),
                title=data.get("title") or "",
                duration=_to_float(data.get("duration"), "duration", 5.0) or 5.0,
                prompt_json=data.get("prompt_json"),
                video_prompt=data.get("video_prompt"),
                video_type=data.get("video_type") or "video",
                video_config_json=data.get("video_config_json"),
                difficulty=data.get("difficulty"),
                act_name=data.get("act_name"),
            )

        if command == "create-storyboard-from-script":
            # ⚠️ style / style_reference_image / composition_preference / workflow_ratio
            # 已从命令层移除：这四项属于世界/故事板级的画风一致性资产，必须由世界表
            # 继承（StoryboardModel.create 内部 world.visual_style / composition_preference
            # 自动回退），禁止 CLI/Agent 按方案差异化覆盖，否则同世界多集画风不一致。
            # 调用方即使传入也会被忽略。
            return self.service.create_storyboard_from_script(
                script_id=_to_required_int(data.get("script_id"), "script_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
                title=data.get("title"),
                workflow_id=_to_int(data.get("workflow_id"), "workflow_id"),
                version=_to_int(data.get("version"), "version", 1) or 1,
                model=data.get("model"),
                model_id=_to_int(data.get("model_id"), "model_id"),
                vendor_id=_to_int(data.get("vendor_id"), "vendor_id"),
            )

        if command == "split-from-script":
            _legacy_force_overwrite_subscene_grids = _to_bool(data.get("force_overwrite_subscene_grids"))
            del _legacy_force_overwrite_subscene_grids
            # CLI 路径强制显式指定 LLM 模型，禁止回退到默认 gemini。
            # 调用方可先用 list_llm_models 查询可用模型及费用。
            return self.service.split_from_script(
                storyboard_id=_to_required_int(data.get("storyboard_id"), "storyboard_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
                auth_token=data.get("auth_token") or "",
                model=_to_required_str(
                    data.get("model"), "model",
                    hint="use --model; call list_llm_models to get available models",
                ),
                model_id=_to_int(data.get("model_id"), "model_id"),
                vendor_id=_to_int(data.get("vendor_id"), "vendor_id"),
                max_group_duration=_to_int_in_range(
                    data.get("max_group_duration"),
                    "max_group_duration",
                    StoryboardAgentCommandConstants.MAX_GROUP_DURATION_DEFAULT,
                    StoryboardAgentCommandConstants.MAX_GROUP_DURATION_MIN,
                    StoryboardAgentCommandConstants.MAX_GROUP_DURATION_MAX,
                ),
                force_medium_shot=_to_bool(data.get("force_medium_shot")),
                no_bg_music=_to_bool(data.get("no_bg_music")),
                split_multi_dialogue=_to_bool(data.get("split_multi_dialogue")),
                language=data.get("language") or "",
                dialogue_language=data.get("dialogue_language") or "",
                prompt_language=data.get("prompt_language") or "",
                # 旧字段继续接受，但已废弃：split 内部永远不会覆盖已有子场景参考图。
                force_overwrite_subscene_grids=False,
            )

        if command == "generate-image":
            return self.service.generate_image(
                scene_id=_to_required_int(data.get("scene_id"), "scene_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
                auth_token=data.get("auth_token") or "",
                mode=data.get("mode") or "auto",
                asset_type=data.get("asset_type") or "first_frame",
                prompt=data.get("prompt"),
                source_image=data.get("source_image"),
                ratio=data.get("ratio"),
                image_size=data.get("image_size"),
                count=_to_int(data.get("count"), "count", 1) or 1,
            )

        if command == "auto-generate-missing-images":
            return self.service.auto_generate_missing_images(
                storyboard_id=_to_required_int(data.get("storyboard_id"), "storyboard_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
                auth_token=data.get("auth_token") or "",
                asset_type=data.get("asset_type") or "first_frame",
                mode=data.get("mode") or "auto",
                prompt=data.get("prompt"),
                source_image=data.get("source_image"),
                ratio=data.get("ratio"),
                image_size=data.get("image_size"),
                count=_to_int(data.get("count"), "count", 1) or 1,
                limit=_to_int(data.get("limit"), "limit"),
                stop_on_error=not _to_bool(data.get("continue_on_error")),
                task_type=_to_int(data.get("task_type") or data.get("image_task_id"), "task_type"),
                sequence_mode=data.get("sequence_mode") or data.get("batch_mode"),
            )

        if command == "auto-generate-missing-videos":
            # CLI 批量视频强制要求显式 task_type：CLI 路径不走 ai-chat，不会把齿轮选择
            # 同步到用户偏好，必须由调用方显式传入，避免回退到错误模型。
            return self.service.auto_generate_missing_videos(
                storyboard_id=_to_required_int(data.get("storyboard_id"), "storyboard_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
                auth_token=data.get("auth_token") or "",
                limit=_to_int(data.get("limit"), "limit"),
                stop_on_error=not _to_bool(
                    True if data.get("continue_on_error") is None else data.get("continue_on_error")
                ),
                task_type=_to_required_int(
                    data.get("task_type") or data.get("video_task_id"), "task_type"
                ),
                ratio=data.get("ratio"),
                sequence_mode=data.get("sequence_mode") or data.get("batch_mode") or "speed",
            )

        if command == "generate-video":
            # CLI 单条视频强制要求显式 task_type（同上理由）。
            return self.service.generate_video(
                scene_id=_to_required_int(data.get("scene_id"), "scene_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
                auth_token=data.get("auth_token") or "",
                mode=data.get("mode") or "image_to_video",
                prompt=data.get("prompt"),
                ratio=data.get("ratio"),
                duration_seconds=_to_int(data.get("duration_seconds") or data.get("duration"), "duration_seconds"),
                count=_to_int(data.get("count"), "count", 1) or 1,
                image_mode=data.get("image_mode") or "first_last_frame",
                image_urls=data.get("image_urls"),
                video_urls=data.get("video_urls"),
                audio_urls=data.get("audio_urls"),
                task_type=_to_required_int(data.get("task_type"), "task_type"),
            )

        if command == "task-status":
            return self.service.task_status(
                scene_id=_to_required_int(data.get("scene_id"), "scene_id"),
                asset_type=data.get("asset_type"),
            )

        if command == "storyboard-task-status":
            return self.service.storyboard_task_status(
                storyboard_id=_to_required_int(data.get("storyboard_id"), "storyboard_id"),
                user_id=_to_int(data.get("user_id"), "user_id"),
                asset_type=data.get("asset_type") or "first_frame",
            )

        if command == "storyboard-image-batch-status":
            return self.service.storyboard_image_batch_status(
                job_id=_to_required_int(data.get("batch_id") or data.get("job_id"), "batch_id"),
                user_id=_to_int(data.get("user_id"), "user_id"),
            )

        if command == "bind-projects":
            result = self.service.bind_projects(
                scene_id=_to_required_int(data.get("scene_id"), "scene_id"),
                user_id=_to_int(data.get("user_id"), "user_id"),
                asset_type=data.get("asset_type"),
                project_ids=_project_ids(data.get("project_ids")),
            )
            return {"success": True, "scene_id": _to_required_int(data.get("scene_id"), "scene_id"), **result}

        if command == "update-scene":
            return self.service.update_scene(
                scene_id=_to_required_int(data.get("scene_id"), "scene_id"),
                user_id=_to_int(data.get("user_id"), "user_id"),
                duration=_to_float(data.get("duration"), "duration"),
                title=data.get("title"),
                prompt_json=data.get("prompt_json"),
                video_prompt=data.get("video_prompt"),
                video_type=data.get("video_type"),
                video_config_json=data.get("video_config_json"),
                audio_embedded=data.get("audio_embedded"),
                difficulty=data.get("difficulty"),
                act_name=data.get("act_name"),
            )

        if command == "export-check":
            return self.service.export_check(
                storyboard_id=_to_required_int(data.get("storyboard_id"), "storyboard_id"),
                user_id=_to_int(data.get("user_id"), "user_id"),
            )

        if command == "export-full-video":
            _include_sub = data.get("include_subtitles")
            include_subtitles = True if _include_sub is None else _to_bool(_include_sub)
            return self.service.export_full_video(
                storyboard_id=_to_required_int(data.get("storyboard_id"), "storyboard_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
                include_subtitles=include_subtitles,
            )

        if command == "export-package":
            return self.service.export_package(
                storyboard_id=_to_required_int(data.get("storyboard_id"), "storyboard_id"),
                user_id=_to_required_int(data.get("user_id"), "user_id"),
            )

        raise StoryboardCliError("unknown_command", f"unknown command: {command}")
