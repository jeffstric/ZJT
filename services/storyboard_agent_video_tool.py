"""Scene-scoped video tool routing for the storyboard AI agent."""

from copy import deepcopy
from typing import Any, Dict, Iterable, List
import uuid

from config.constant import StoryboardDigitalHumanConstants
from config.unified_config import UnifiedConfigRegistry
from config.unified_config import SceneVideoType


DIGITAL_HUMAN_TOOL_NAME = "generate_digital_human"
STANDARD_VIDEO_TOOL_NAMES = frozenset({"generate_text_to_video", "image_to_video"})
_DIGITAL_HUMAN_SUPPORT_TOOLS = ("get_user_computing_power", "ask_user")

_DIGITAL_HUMAN_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": DIGITAL_HUMAN_TOOL_NAME,
        "description": (
            "为当前故事板对口型分镜提交 MiniMax H3 数字人视频。"
            "模型固定 MiniMax H3；提示词、时长(4–10s clamp)、首帧图、对白与 TTS 均由系统解析，"
            "禁止传入或捏造图片、音频、提示词、时长等参数。"
            "可选 resolution（480P/720P/1080P）映射为视频最长边。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "resolution": {
                    "type": "string",
                    "description": "可选分辨率：480P / 720P / 1080P，映射为最长边。",
                },
                "clip_to_audio_duration": {
                    "type": "boolean",
                    "description": "导出时是否裁剪到配音时长，默认开启。",
                },
            },
            "required": [],
        },
    },
}


def deduct_storyboard_digital_human_computing_power(
    *,
    auth_token: str,
    plan,
) -> tuple:
    """按 MiniMax H3 时长档位扣除算力（Agent / CLI 同步入口）。返回 (transaction_id, computing_power)。"""
    from services.storyboard_digital_human_service import (
        deduct_computing_power_sync,
        compute_digital_human_power,
    )

    computing_power = compute_digital_human_power(plan)
    transaction_id = str(uuid.uuid4())
    if not computing_power:
        return transaction_id, 0

    ok, message = deduct_computing_power_sync(auth_token, computing_power, transaction_id)
    if not ok:
        raise RuntimeError(message or "算力不足或扣费失败")
    return transaction_id, computing_power


def resolve_storyboard_agent_allowed_tools(
    base_allowed_tools: Iterable[str],
    *,
    generation_target: str,
    video_type: str,
) -> List[str]:
    """Restrict digital-human scenes so a model cannot choose generic video tools."""
    base = list(dict.fromkeys(base_allowed_tools or []))
    if generation_target != "video" or str(video_type or "") != SceneVideoType.DIGITAL_HUMAN:
        return base

    support_tools = [name for name in _DIGITAL_HUMAN_SUPPORT_TOOLS if name in base]
    return [DIGITAL_HUMAN_TOOL_NAME, *support_tools]


class StoryboardAgentVideoToolExecutor:
    """Inject scene-scoped video settings and route digital-human submission."""

    def __init__(self, delegate, *, scene_id: int, video_preferences=None):
        self._delegate = delegate
        self._scene_id = int(scene_id)
        self._video_preferences = dict(video_preferences or {})
        self._already_bound_project_ids = set()

    def get_tool_definitions(self, allowed_tools: List[str]) -> List[Dict[str, Any]]:
        delegated_names = [name for name in allowed_tools if name != DIGITAL_HUMAN_TOOL_NAME]
        definitions = list(self._delegate.get_tool_definitions(delegated_names))
        if DIGITAL_HUMAN_TOOL_NAME in allowed_tools:
            definitions.append(deepcopy(_DIGITAL_HUMAN_TOOL_DEFINITION))
        return definitions

    def execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        user_id: str,
        world_id: str,
        auth_token: str,
        language: str = "zh-CN",
        model: str = None,
        vendor_id: int = None,
    ) -> Dict[str, Any]:
        if tool_name in STANDARD_VIDEO_TOOL_NAMES:
            from script_writer_core.mcp_tool import scoped_video_preferences

            args = dict(tool_args or {})
            preferences = self._video_preferences
            if preferences.get("ratio"):
                args["ratio"] = preferences["ratio"]
            if preferences.get("duration") is not None:
                args["duration_seconds"] = int(preferences["duration"])
            if tool_name == "image_to_video" and preferences.get("image_mode"):
                args["image_mode"] = preferences["image_mode"]

            # 与 marketing_agent 一致：任务快照里的 task_id 强制覆盖 Agent/LLM
            # 传入的 task_type，避免 list_video_models 自选或中途改模型后落到旧偏好。
            forced_task_type = preferences.get("task_id")
            if forced_task_type is not None and str(forced_task_type).strip() != "":
                try:
                    args["task_type"] = int(forced_task_type)
                except (TypeError, ValueError):
                    pass

            with scoped_video_preferences(preferences):
                return self._delegate.execute_tool(
                    tool_name,
                    args,
                    user_id,
                    world_id,
                    auth_token,
                    language=language,
                    model=model,
                    vendor_id=vendor_id,
                )

        if tool_name != DIGITAL_HUMAN_TOOL_NAME:
            return self._delegate.execute_tool(
                tool_name,
                tool_args,
                user_id,
                world_id,
                auth_token,
                language=language,
                model=model,
                vendor_id=vendor_id,
            )

        from services.storyboard_digital_human_service import (
            StoryboardDigitalHumanError,
            orchestrate_digital_human_generation,
            submit_digital_human_plan,
        )

        args = dict(tool_args or {})
        preferences = self._video_preferences
        # 分辨率：工具参数优先，否则取齿轮/会话注入的视频偏好
        resolution = args.get("resolution") or preferences.get("resolution")
        # 统一编排：解析 → MiniMax 计划 → 准备音频。忽略模型传入的 prompt/duration/ratio。
        try:
            plan, _segments, _scene, _sb = orchestrate_digital_human_generation(
                self._scene_id,
                resolution=resolution,
            )
        except StoryboardDigitalHumanError as exc:
            message_by_code = {
                StoryboardDigitalHumanConstants.ERROR_MISSING_IMAGE: "当前对口型分镜缺少已生成完成的选中首帧，请先生成并选中首帧",
                StoryboardDigitalHumanConstants.ERROR_AUDIO_REQUIRED: "当前对口型分镜尚无已完成配音，请先生成配音",
                StoryboardDigitalHumanConstants.ERROR_AUDIO_PENDING: "当前对口型分镜的配音仍在生成，请等待配音完成",
                StoryboardDigitalHumanConstants.ERROR_MULTI_SPEAKER: "当前对口型分镜包含多个说话角色，请拆成单人分镜",
                StoryboardDigitalHumanConstants.ERROR_UNSUPPORTED_RATIO: exc.message,
            }
            raise RuntimeError(message_by_code.get(exc.code, exc.message))

        transaction_id, computing_power = deduct_storyboard_digital_human_computing_power(
            auth_token=auth_token,
            plan=plan,
        )
        result = submit_digital_human_plan(
            plan,
            scene_id=self._scene_id,
            user_id=int(user_id),
            transaction_id=transaction_id,
            computing_power=computing_power,
            clip_to_audio_duration=bool(args.get("clip_to_audio_duration", True)),
            resolution=resolution,
        )
        project_id = result.get("ai_tool_id")
        if project_id is None:
            return {"error": "数字人视频任务提交成功，但未返回 ai_tool_id"}

        self._already_bound_project_ids.add(str(project_id))
        return {
            **result,
            "project_ids": [project_id],
            "already_bound": True,
        }

    def are_projects_already_bound(self, project_ids: Iterable[Any]) -> bool:
        normalized = [str(project_id) for project_id in (project_ids or [])]
        return bool(normalized) and all(
            project_id in self._already_bound_project_ids for project_id in normalized
        )
