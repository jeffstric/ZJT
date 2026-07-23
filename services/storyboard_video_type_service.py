"""Transactional storyboard scene video-type switching rules."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional

from config.constant import (
    AI_TOOL_STATUS_COMPLETED,
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
)
from config.unified_config import SceneVideoType
from model.database import transaction


class StoryboardVideoTypeValidationError(ValueError):
    """The requested scene video type is not valid for the scene."""


class StoryboardVideoTypeConflict(RuntimeError):
    """The scene type changed after the client rendered it."""


class StoryboardVideoTypeNotFound(LookupError):
    """The scene disappeared before the transaction acquired its lock."""


def validate_video_type_switch(
    *,
    current_type: str,
    target_type: str,
    expected_type: str,
    speaker_count: int,
) -> None:
    allowed = {SceneVideoType.VIDEO, SceneVideoType.DIGITAL_HUMAN}
    if target_type not in allowed:
        raise StoryboardVideoTypeValidationError(
            "video_type 必须是 video 或 digital_human"
        )
    if expected_type != current_type:
        raise StoryboardVideoTypeConflict("分镜生成方式已被其他操作修改")
    if target_type == SceneVideoType.DIGITAL_HUMAN and speaker_count > 1:
        raise StoryboardVideoTypeValidationError("对口型模式仅支持单个说话角色")


def _is_running(status: Any) -> bool:
    return status in {
        AI_TOOL_STATUS_PENDING,
        AI_TOOL_STATUS_PROCESSING,
        str(AI_TOOL_STATUS_PENDING),
        str(AI_TOOL_STATUS_PROCESSING),
        "pending",
        "queued",
        "running",
        "processing",
    }


def _is_completed(asset: Dict[str, Any]) -> bool:
    status = asset.get("status")
    return bool(asset.get("result_url")) and status in {
        None,
        AI_TOOL_STATUS_COMPLETED,
        str(AI_TOOL_STATUS_COMPLETED),
        "completed",
        "success",
    }


def decide_selected_video_after_switch(
    target_type: str,
    selected_asset: Optional[Dict[str, Any]],
    candidates: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Choose the selected video without deleting or cancelling old assets."""
    if not selected_asset:
        return {
            "selected_video_id": None,
            "video_url": None,
            "old_task_detached": False,
        }

    selected_type = str(selected_asset.get("video_type") or "")
    is_old_running_task = (
        _is_running(selected_asset.get("status"))
        and bool(selected_type)
        and selected_type != target_type
    )
    if not is_old_running_task:
        return {
            "selected_video_id": selected_asset.get("id"),
            "video_url": selected_asset.get("result_url"),
            "old_task_detached": False,
        }

    fallback = next((item for item in candidates if _is_completed(item)), None)
    return {
        "selected_video_id": fallback.get("id") if fallback else None,
        "video_url": fallback.get("result_url") if fallback else None,
        "old_task_detached": True,
    }


def _parse_extra_video_type(extra_config: Any) -> str:
    if isinstance(extra_config, dict):
        payload = extra_config
    else:
        try:
            payload = json.loads(extra_config or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
    return str(payload.get("video_type") or "")


def _asset_from_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        "id": row.get("id"),
        "status": row.get("status"),
        "video_type": _parse_extra_video_type(row.get("extra_config")),
        "result_url": row.get("asset_result_url") or row.get("tool_result_url"),
    }


def switch_storyboard_scene_video_type(
    scene_id: int,
    target_type: str,
    expected_type: str,
    user_id: int,
) -> Dict[str, Any]:
    """Atomically switch the scene mode and detach a selected old running task."""
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, video_type, selected_video_id "
            "FROM storyboard_scene WHERE id = %s FOR UPDATE",
            (scene_id,),
        )
        scene = cursor.fetchone()
        if not scene:
            raise StoryboardVideoTypeNotFound("分镜不存在")

        cursor.execute(
            "SELECT COUNT(DISTINCT character_id) AS speaker_count "
            "FROM storyboard_dialogue "
            "WHERE scene_id = %s AND character_id IS NOT NULL",
            (scene_id,),
        )
        speaker_row = cursor.fetchone() or {}
        validate_video_type_switch(
            current_type=str(scene.get("video_type") or SceneVideoType.VIDEO),
            target_type=str(target_type or ""),
            expected_type=str(expected_type or ""),
            speaker_count=int(speaker_row.get("speaker_count") or 0),
        )

        selected_asset = None
        selected_video_id = scene.get("selected_video_id")
        if selected_video_id:
            cursor.execute(
                "SELECT a.id, a.result_url AS asset_result_url, "
                "t.result_url AS tool_result_url, t.status, t.extra_config "
                "FROM storyboard_scene_asset a "
                "LEFT JOIN ai_tools t ON t.id = a.ai_tool_id "
                "WHERE a.id = %s AND a.scene_id = %s AND a.asset_type = 'video'",
                (selected_video_id, scene_id),
            )
            selected_asset = _asset_from_row(cursor.fetchone())

        cursor.execute(
            "SELECT a.id, a.result_url AS asset_result_url, "
            "t.result_url AS tool_result_url, t.status, t.extra_config "
            "FROM storyboard_scene_asset a "
            "LEFT JOIN ai_tools t ON t.id = a.ai_tool_id "
            "WHERE a.scene_id = %s AND a.asset_type = 'video' "
            "AND a.id <> COALESCE(%s, 0) "
            "ORDER BY a.create_at DESC, a.id DESC",
            (scene_id, selected_video_id),
        )
        candidates = [_asset_from_row(row) for row in (cursor.fetchall() or [])]
        selection = decide_selected_video_after_switch(
            target_type,
            selected_asset,
            [item for item in candidates if item],
        )

        cursor.execute(
            "UPDATE storyboard_scene "
            "SET video_type = %s, selected_video_id = %s, last_modified_user_id = %s "
            "WHERE id = %s",
            (target_type, selection["selected_video_id"], user_id, scene_id),
        )

    return {
        "scene_id": scene_id,
        "video_type": target_type,
        **selection,
    }


__all__ = [
    "StoryboardVideoTypeConflict",
    "StoryboardVideoTypeNotFound",
    "StoryboardVideoTypeValidationError",
    "decide_selected_video_after_switch",
    "switch_storyboard_scene_video_type",
    "validate_video_type_switch",
]
