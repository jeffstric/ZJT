from contextlib import contextmanager

import pytest

from services import storyboard_asset_service as service


@contextmanager
def _fake_transaction():
    yield object()


def test_choose_asset_fallback_skips_unusable_candidates():
    result = service.choose_asset_fallback([
        {
            "id": 1,
            "ai_tool_id": 101,
            "asset_result_url": "/upload/running.mp4",
            "status": 1,
        },
        {
            "id": 2,
            "ai_tool_id": 102,
            "asset_result_url": "",
            "tool_result_url": "",
            "status": 2,
        },
        {
            "id": 3,
            "ai_tool_id": 103,
            "tool_result_url": "/upload/completed.mp4",
            "status": 2,
        },
    ])

    assert result == {"id": 3, "result_url": "/upload/completed.mp4"}


@pytest.mark.parametrize("status", [0, 1, 3, 4, 5, 6, "queued", "processing"])
def test_is_asset_task_running_covers_all_active_states(status):
    assert service.is_asset_task_running(status) is True


def test_delete_selected_video_switches_to_latest_completed_fallback(monkeypatch):
    updates = []

    def fake_query(conn, sql, params=None, fetch_one=False):
        normalized = " ".join(sql.split())
        if "FROM storyboard_scene WHERE id" in normalized:
            return {
                "id": 7,
                "selected_first_frame_id": 20,
                "selected_last_frame_id": None,
                "selected_video_id": 10,
            }
        if "WHERE a.id = %s AND a.scene_id = %s" in normalized:
            return {
                "id": 10,
                "scene_id": 7,
                "asset_type": "video",
                "ai_tool_id": None,
                "result_url": "/upload/storyboard/video/deleted.mp4",
                "media_mapping_id": None,
                "status": None,
                "tool_result_url": None,
            }
        if "WHERE a.scene_id = %s AND a.asset_type = %s" in normalized:
            return [{
                "id": 11,
                "ai_tool_id": 99,
                "asset_result_url": "",
                "tool_result_url": "/upload/storyboard/video/fallback.mp4",
                "status": 2,
            }]
        if "COUNT(*) AS reference_count" in normalized:
            return {"reference_count": 0}
        raise AssertionError(normalized)

    def fake_update(conn, sql, params=None):
        updates.append((" ".join(sql.split()), params))
        return 1

    monkeypatch.setattr(service, "transaction", _fake_transaction)
    monkeypatch.setattr(service, "execute_query_in_transaction", fake_query)
    monkeypatch.setattr(service, "execute_update_in_transaction", fake_update)

    result = service.delete_storyboard_scene_asset(7, 10, 5)

    assert result["was_selected"] is True
    assert result["selected_asset_id"] == 11
    assert result["selected_result_url"].endswith("fallback.mp4")
    assert result["should_remove_local_file"] is True
    assert any("selected_video_id = %s" in sql and params == (11, 5, 7) for sql, params in updates)
    assert any(sql.startswith("DELETE FROM storyboard_scene_asset") for sql, _ in updates)


def test_delete_last_selected_image_clears_selection(monkeypatch):
    updates = []

    def fake_query(conn, sql, params=None, fetch_one=False):
        normalized = " ".join(sql.split())
        if "FROM storyboard_scene WHERE id" in normalized:
            return {
                "id": 8,
                "selected_first_frame_id": 21,
                "selected_last_frame_id": None,
                "selected_video_id": None,
            }
        if "WHERE a.id = %s AND a.scene_id = %s" in normalized:
            return {
                "id": 21,
                "scene_id": 8,
                "asset_type": "first_frame",
                "ai_tool_id": None,
                "result_url": "/upload/storyboard/first_frame/deleted.png",
                "media_mapping_id": None,
                "status": None,
                "tool_result_url": None,
            }
        if "WHERE a.scene_id = %s AND a.asset_type = %s" in normalized:
            return []
        if "COUNT(*) AS reference_count" in normalized:
            return {"reference_count": 0}
        raise AssertionError(normalized)

    def fake_update(conn, sql, params=None):
        updates.append((" ".join(sql.split()), params))
        return 1

    monkeypatch.setattr(service, "transaction", _fake_transaction)
    monkeypatch.setattr(service, "execute_query_in_transaction", fake_query)
    monkeypatch.setattr(service, "execute_update_in_transaction", fake_update)

    result = service.delete_storyboard_scene_asset(8, 21, 5)

    assert result["selected_asset_id"] is None
    assert any("selected_first_frame_id = %s" in sql and params == (None, 5, 8) for sql, params in updates)


def test_delete_running_asset_is_rejected(monkeypatch):
    def fake_query(conn, sql, params=None, fetch_one=False):
        normalized = " ".join(sql.split())
        if "FROM storyboard_scene WHERE id" in normalized:
            return {
                "id": 9,
                "selected_first_frame_id": 31,
                "selected_last_frame_id": None,
                "selected_video_id": None,
            }
        return {
            "id": 31,
            "scene_id": 9,
            "asset_type": "first_frame",
            "ai_tool_id": 200,
            "result_url": None,
            "media_mapping_id": None,
            "status": 1,
            "tool_result_url": None,
        }

    monkeypatch.setattr(service, "transaction", _fake_transaction)
    monkeypatch.setattr(service, "execute_query_in_transaction", fake_query)

    with pytest.raises(service.StoryboardAssetDeleteError) as exc_info:
        service.delete_storyboard_scene_asset(9, 31, 5)

    assert exc_info.value.error_code == "asset_task_running"
    assert exc_info.value.status_code == 409


def test_select_asset_locks_scene_then_validates_asset(monkeypatch):
    query_order = []
    updates = []

    def fake_query(conn, sql, params=None, fetch_one=False):
        normalized = " ".join(sql.split())
        query_order.append(normalized)
        if "FROM storyboard_scene WHERE id" in normalized:
            return {"id": 12}
        if "FROM storyboard_scene_asset" in normalized:
            assert params == (44, 12, "video")
            return {"id": 44}
        raise AssertionError(normalized)

    def fake_update(conn, sql, params=None):
        updates.append((" ".join(sql.split()), params))
        return 1

    monkeypatch.setattr(service, "transaction", _fake_transaction)
    monkeypatch.setattr(service, "execute_query_in_transaction", fake_query)
    monkeypatch.setattr(service, "execute_update_in_transaction", fake_update)

    result = service.select_storyboard_scene_asset(12, 44, "video", 5)

    assert "FROM storyboard_scene WHERE id" in query_order[0]
    assert "FROM storyboard_scene_asset" in query_order[1]
    assert updates == [(
        "UPDATE storyboard_scene SET selected_video_id = %s, last_modified_user_id = %s WHERE id = %s",
        (44, 5, 12),
    )]
    assert result["asset_id"] == 44
