"""分镜候选资产的事务型删除与选中项回退。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from config.constant import (
    AI_TOOL_STATUS_COMPLETED,
    AI_TOOL_STATUS_DOWNLOADING,
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
    AI_TOOL_STATUS_SYNC_QUEUED,
    AI_TOOL_STATUS_WAITING_BEFORE_FINISH,
    AI_TOOL_STATUS_WAITING_PARAM_PREPARE,
)
from model.database import (
    execute_query_in_transaction,
    execute_update_in_transaction,
    transaction,
)


ASSET_SELECTION_COLUMNS = {
    "first_frame": "selected_first_frame_id",
    "last_frame": "selected_last_frame_id",
    "video": "selected_video_id",
}

RUNNING_AI_TOOL_STATUSES = {
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
    AI_TOOL_STATUS_SYNC_QUEUED,
    AI_TOOL_STATUS_WAITING_PARAM_PREPARE,
    AI_TOOL_STATUS_WAITING_BEFORE_FINISH,
    AI_TOOL_STATUS_DOWNLOADING,
}


class StoryboardAssetDeleteError(ValueError):
    def __init__(self, error_code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


class StoryboardAssetSelectError(ValueError):
    def __init__(self, error_code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


def _normalized_status(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip().lower()
        if text.lstrip("-").isdigit():
            return int(text)
        return text
    return value


def is_asset_task_running(status: Any) -> bool:
    value = _normalized_status(status)
    return value in RUNNING_AI_TOOL_STATUSES or value in {
        "pending",
        "queued",
        "running",
        "processing",
        "downloading",
    }


def asset_result_url(row: Optional[Dict[str, Any]]) -> str:
    if not row:
        return ""
    return str(row.get("asset_result_url") or row.get("tool_result_url") or "").strip()


def choose_asset_fallback(candidates: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """选择最新的可用完成资产，跳过运行中、失败或无结果的候选。"""
    for candidate in candidates:
        result_url = asset_result_url(candidate)
        if not result_url:
            continue
        ai_tool_id = candidate.get("ai_tool_id")
        status = _normalized_status(candidate.get("status"))
        if ai_tool_id and status not in {
            AI_TOOL_STATUS_COMPLETED,
            "completed",
            "success",
        }:
            continue
        return {
            "id": int(candidate["id"]),
            "result_url": result_url,
        }
    return None


def delete_storyboard_scene_asset(
    scene_id: int,
    asset_id: int,
    user_id: int,
) -> Dict[str, Any]:
    """原子删除候选；若删除选中项，则在同一事务内切换到可用回退项。"""
    with transaction() as conn:
        scene = execute_query_in_transaction(
            conn,
            """
                SELECT id, selected_first_frame_id, selected_last_frame_id, selected_video_id
                FROM storyboard_scene
                WHERE id = %s
                FOR UPDATE
            """,
            (int(scene_id),),
            fetch_one=True,
        )
        if not scene:
            raise StoryboardAssetDeleteError("scene_not_found", "分镜不存在", 404)

        asset = execute_query_in_transaction(
            conn,
            """
                SELECT a.id, a.scene_id, a.asset_type, a.ai_tool_id, a.result_url,
                       a.media_mapping_id, t.status, t.result_url AS tool_result_url
                FROM storyboard_scene_asset a
                LEFT JOIN ai_tools t ON t.id = a.ai_tool_id
                WHERE a.id = %s AND a.scene_id = %s
                FOR UPDATE
            """,
            (int(asset_id), int(scene_id)),
            fetch_one=True,
        )
        if not asset:
            raise StoryboardAssetDeleteError(
                "asset_not_found",
                "候选资产不存在或不属于该分镜",
                404,
            )

        asset_type = str(asset.get("asset_type") or "")
        selection_column = ASSET_SELECTION_COLUMNS.get(asset_type)
        if not selection_column:
            raise StoryboardAssetDeleteError("invalid_asset_type", "不支持删除该类型的候选资产")
        if asset.get("ai_tool_id") and is_asset_task_running(asset.get("status")):
            raise StoryboardAssetDeleteError(
                "asset_task_running",
                "候选仍在生成中，请完成后再删除",
                409,
            )

        was_selected = str(scene.get(selection_column) or "") == str(asset_id)
        fallback = None
        if was_selected:
            candidates = execute_query_in_transaction(
                conn,
                """
                    SELECT a.id, a.ai_tool_id, a.result_url AS asset_result_url,
                           t.result_url AS tool_result_url, t.status
                    FROM storyboard_scene_asset a
                    LEFT JOIN ai_tools t ON t.id = a.ai_tool_id
                    WHERE a.scene_id = %s AND a.asset_type = %s AND a.id <> %s
                    ORDER BY a.create_at DESC, a.id DESC
                """,
                (int(scene_id), asset_type, int(asset_id)),
            ) or []
            fallback = choose_asset_fallback(candidates)

        selected_asset_id = fallback["id"] if fallback else scene.get(selection_column)
        selected_result_url = fallback["result_url"] if fallback else ""
        if was_selected and not fallback:
            selected_asset_id = None

        if was_selected:
            execute_update_in_transaction(
                conn,
                f"UPDATE storyboard_scene SET {selection_column} = %s, "
                "last_modified_user_id = %s WHERE id = %s",
                (selected_asset_id, int(user_id), int(scene_id)),
            )
        else:
            execute_update_in_transaction(
                conn,
                "UPDATE storyboard_scene SET last_modified_user_id = %s WHERE id = %s",
                (int(user_id), int(scene_id)),
            )

        other_references = execute_query_in_transaction(
            conn,
            """
                SELECT COUNT(*) AS reference_count
                FROM storyboard_scene_asset
                WHERE id <> %s AND result_url = %s
            """,
            (int(asset_id), asset.get("result_url")),
            fetch_one=True,
        ) or {}
        deleted_count = execute_update_in_transaction(
            conn,
            "DELETE FROM storyboard_scene_asset WHERE id = %s AND scene_id = %s",
            (int(asset_id), int(scene_id)),
        )
        if int(deleted_count or 0) != 1:
            raise StoryboardAssetDeleteError("asset_delete_conflict", "候选资产已被其他操作删除", 409)

    return {
        "success": True,
        "scene_id": int(scene_id),
        "deleted_asset_id": int(asset_id),
        "asset_type": asset_type,
        "was_selected": was_selected,
        "selected_asset_id": selected_asset_id,
        "selected_result_url": selected_result_url,
        "result_url": asset.get("result_url") or "",
        "should_remove_local_file": bool(
            not asset.get("ai_tool_id")
            and not asset.get("media_mapping_id")
            and asset.get("result_url")
            and int(other_references.get("reference_count") or 0) == 0
        ),
    }


def select_storyboard_scene_asset(
    scene_id: int,
    asset_id: int,
    asset_type: str,
    user_id: int,
) -> Dict[str, Any]:
    """与删除采用相同锁顺序，避免并发选择把已删除 asset 写回选中指针。"""
    selection_column = ASSET_SELECTION_COLUMNS.get(str(asset_type or ""))
    if not selection_column:
        raise StoryboardAssetSelectError(
            "invalid_asset_type",
            "asset_type 必须为 first_frame/last_frame/video",
        )

    with transaction() as conn:
        scene = execute_query_in_transaction(
            conn,
            "SELECT id FROM storyboard_scene WHERE id = %s FOR UPDATE",
            (int(scene_id),),
            fetch_one=True,
        )
        if not scene:
            raise StoryboardAssetSelectError("scene_not_found", "分镜不存在", 404)
        asset = execute_query_in_transaction(
            conn,
            """
                SELECT id FROM storyboard_scene_asset
                WHERE id = %s AND scene_id = %s AND asset_type = %s
                FOR UPDATE
            """,
            (int(asset_id), int(scene_id), str(asset_type)),
            fetch_one=True,
        )
        if not asset:
            raise StoryboardAssetSelectError(
                "asset_not_found",
                "资产不存在、类型不匹配或不属于该分镜",
                400,
            )
        execute_update_in_transaction(
            conn,
            f"UPDATE storyboard_scene SET {selection_column} = %s, "
            "last_modified_user_id = %s WHERE id = %s",
            (int(asset_id), int(user_id), int(scene_id)),
        )

    return {
        "success": True,
        "scene_id": int(scene_id),
        "asset_type": str(asset_type),
        "asset_id": int(asset_id),
    }


__all__ = [
    "StoryboardAssetDeleteError",
    "StoryboardAssetSelectError",
    "asset_result_url",
    "choose_asset_fallback",
    "delete_storyboard_scene_asset",
    "is_asset_task_running",
    "select_storyboard_scene_asset",
]
