"""Transactional non-generation operations for storyboard grid batch selection."""
from typing import Any, Dict, List, Sequence

from config.constant import StoryboardAutoGenerateConstants
from model.database import (
    execute_query_in_transaction,
    execute_update_in_transaction,
    transaction,
)


class StoryboardBatchOperationError(ValueError):
    def __init__(self, error_code: str, message: str, *, payload: Dict[str, Any] | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.payload = payload or {}


def _normalize_scene_ids(scene_ids: Sequence[int]) -> List[int]:
    if isinstance(scene_ids, (str, bytes)) or not isinstance(scene_ids, Sequence):
        raise StoryboardBatchOperationError("invalid_scene_ids", "scene_ids must be an array")
    result: List[int] = []
    seen = set()
    for raw_id in scene_ids:
        try:
            scene_id = int(raw_id)
        except (TypeError, ValueError):
            raise StoryboardBatchOperationError("invalid_scene_ids", "scene_ids must contain integers")
        if scene_id <= 0:
            raise StoryboardBatchOperationError("invalid_scene_ids", "scene_ids must contain positive integers")
        if scene_id not in seen:
            seen.add(scene_id)
            result.append(scene_id)
    if not result:
        raise StoryboardBatchOperationError("empty_scene_ids", "scene_ids must not be empty")
    if len(result) > StoryboardAutoGenerateConstants.MAX_SELECTED_SCENE_COUNT:
        raise StoryboardBatchOperationError(
            "too_many_scene_ids",
            f"scene_ids exceeds {StoryboardAutoGenerateConstants.MAX_SELECTED_SCENE_COUNT}",
        )
    return sorted(result)


def batch_delete_storyboard_scenes(storyboard_id: int, scene_ids: Sequence[int]) -> Dict[str, Any]:
    """Delete an explicit scene selection atomically and settle active batch items."""
    normalized = _normalize_scene_ids(scene_ids)
    placeholders = ", ".join(["%s"] * len(normalized))

    with transaction() as conn:
        rows = execute_query_in_transaction(
            conn,
            f"""
                SELECT id FROM storyboard_scene
                WHERE storyboard_id = %s AND id IN ({placeholders})
                FOR UPDATE
            """,
            (int(storyboard_id), *normalized),
        ) or []
        found_ids = {int(row["id"]) for row in rows}
        invalid_ids = sorted(set(normalized) - found_ids)
        if invalid_ids:
            raise StoryboardBatchOperationError(
                "selection_stale",
                "some selected scenes no longer belong to this storyboard",
                payload={"invalid_scene_ids": invalid_ids},
            )

        settled_items = execute_update_in_transaction(
            conn,
            f"""
                UPDATE storyboard_image_batch_item
                SET status = %s,
                    error_code = 'scene_deleted_by_user',
                    error_message = 'scene was deleted by user during batch generation'
                WHERE storyboard_id = %s
                  AND scene_id IN ({placeholders})
                  AND status IN (%s, %s)
            """,
            (
                StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
                int(storyboard_id),
                *normalized,
                StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
                StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING,
            ),
        )
        deleted_count = execute_update_in_transaction(
            conn,
            f"DELETE FROM storyboard_scene WHERE storyboard_id = %s AND id IN ({placeholders})",
            (int(storyboard_id), *normalized),
        )

    return {
        "success": True,
        "storyboard_id": int(storyboard_id),
        "deleted_scene_ids": normalized,
        "deleted_count": int(deleted_count or 0),
        "settled_batch_item_count": int(settled_items or 0),
    }


__all__ = [
    "StoryboardBatchOperationError",
    "batch_delete_storyboard_scenes",
]
