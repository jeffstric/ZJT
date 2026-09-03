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


def resolve_scene_generation_bindings(
    scene_id: int,
    selected_map: Dict[str, Optional[int]],
) -> Dict[str, Dict[str, Any]]:
    """延迟选中的轮询期解析（生成成功前不切换选中资产）。

    提交生成时只建 storyboard_scene_asset、不 set_selected（见 bind_projects 延迟选中），
    选中指针在本函数于轮询期检测到「更新成功资产」时才切换：

    - generating：该类型最新的非终态资产（LEFT JOIN ai_tools 状态），
      供轮询方展示「生成中」占位并维持轮询不中断；
    - selected_asset_id：存在比当前选中「更新且已成功」的资产时自动切换到最新成功者
      （多次重新生成时最新成功者胜出），否则保持原值（含 None）。

    闩锁语义：仅当资产完成时间（ai_tools.update_time）不早于分镜 update_at 时才切换。
    切换本身会刷新 scene.update_at，使后续轮询自然稳定；用户在生成完成后的手动改选
    （scene.update_at 晚于完成时间）不会被覆盖。切换只认 ai_tool 生成产物，上传资产
    始终走显式选中。

    与删除/手动选中采用相同的 scene 行锁顺序。系统驱动的切换不更新
    last_modified_user_id，避免轮询副作用污染分镜修改人。
    """
    results: Dict[str, Dict[str, Any]] = {}
    with transaction() as conn:
        scene = execute_query_in_transaction(
            conn,
            """
                SELECT id, selected_first_frame_id, selected_last_frame_id, selected_video_id,
                       update_at
                FROM storyboard_scene
                WHERE id = %s
                FOR UPDATE
            """,
            (int(scene_id),),
            fetch_one=True,
        )
        if not scene:
            return {
                asset_type: {"selected_asset_id": selected_id, "switched": False, "generating": None}
                for asset_type, selected_id in selected_map.items()
            }
        scene_update_at = scene.get("update_at")

        for asset_type in selected_map:
            column = ASSET_SELECTION_COLUMNS.get(asset_type)
            if not column:
                continue
            current_selected = scene.get(column)
            rows = execute_query_in_transaction(
                conn,
                """
                    SELECT a.id, a.ai_tool_id, a.result_url AS asset_result_url,
                           t.result_url AS tool_result_url, t.status,
                           t.update_time AS tool_update_time
                    FROM storyboard_scene_asset a
                    LEFT JOIN ai_tools t ON t.id = a.ai_tool_id
                    WHERE a.scene_id = %s AND a.asset_type = %s
                    ORDER BY a.create_at DESC, a.id DESC
                """,
                (int(scene_id), asset_type),
            ) or []

            generating = next((row for row in rows if is_asset_task_running(row.get("status"))), None)

            # 行按新→旧排序；一旦走到选中或更旧的资产，不会再有「更新成功者」
            winner = None
            for row in rows:
                row_id = int(row["id"])
                if current_selected is not None and row_id <= int(current_selected):
                    break
                if not row.get("ai_tool_id"):
                    continue  # 上传资产走显式选中，不参与自动切换
                if not asset_result_url(row):
                    continue  # 未产出结果（生成中/失败）
                status = _normalized_status(row.get("status"))
                if status not in {AI_TOOL_STATUS_COMPLETED, "completed", "success"}:
                    continue
                tool_update_time = row.get("tool_update_time")
                if tool_update_time is None:
                    continue
                if scene_update_at is not None and tool_update_time < scene_update_at:
                    continue  # 完成早于分镜最后更新：用户已表达过更新意图，不覆盖
                winner = row
                break

            if winner:
                execute_update_in_transaction(
                    conn,
                    f"UPDATE storyboard_scene SET {column} = %s WHERE id = %s",
                    (int(winner["id"]), int(scene_id)),
                )
                current_selected = int(winner["id"])

            results[asset_type] = {
                "selected_asset_id": current_selected,
                "switched": bool(winner),
                "generating": generating,
            }

    return results


__all__ = [
    "StoryboardAssetDeleteError",
    "StoryboardAssetSelectError",
    "asset_result_url",
    "choose_asset_fallback",
    "delete_storyboard_scene_asset",
    "is_asset_task_running",
    "resolve_scene_generation_bindings",
    "select_storyboard_scene_asset",
]
