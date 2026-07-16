from unittest.mock import patch

from enterprise.services.storyboard_quality_sequence.location_references import (
    QualityLocationReferenceCoordinator,
)


def _scene(scene_id, location_id):
    return {
        "id": scene_id,
        "prompt_json": {
            "source": {"location_db_id": location_id},
        },
    }


def _planned(scene_id):
    return {"scene_id": scene_id, "status": "pending", "batch_status": 0}


def test_quality_preflight_blocks_when_required_root_has_no_reference_image():
    coordinator = QualityLocationReferenceCoordinator()
    locations = [{
        "id": 10,
        "name": "城南酒店",
        "parent_id": None,
        "reference_image": None,
        "children": [],
    }]

    with patch.object(coordinator, "_load_locations", return_value=locations), \
         patch.object(coordinator, "_latest_grid_task", return_value=None), \
         patch.object(coordinator, "_submit_ready_layer") as submit:
        result = coordinator.preflight(
            storyboard_id=5,
            world_id=6,
            user_id=1,
            auth_token="token",
            scenes=[_scene(101, 10)],
            planned_items=[_planned(101)],
        )

    assert result["status"] == "blocked"
    assert result["error_code"] == "quality_parent_reference_missing"
    assert result["blockers"][0]["parent_location_id"] == 10
    assert result["blockers"][0]["affected_scene_ids"] == [101]
    submit.assert_not_called()


def test_quality_preflight_submits_ready_child_layer_and_returns_waiting():
    coordinator = QualityLocationReferenceCoordinator()
    locations = [{
        "id": 10,
        "name": "城南酒店",
        "parent_id": None,
        "reference_image": "parent.png",
        "children": [{
            "id": 11,
            "name": "酒店走廊",
            "parent_id": 10,
            "reference_image": None,
            "children": [],
        }],
    }]

    with patch.object(coordinator, "_load_locations", return_value=locations), \
         patch.object(coordinator, "_latest_grid_task", return_value=None), \
         patch.object(
             coordinator,
             "_submit_ready_layer",
             return_value={"submitted_batches": 1, "submitted_subscene_count": 1},
         ) as submit:
        result = coordinator.preflight(
            storyboard_id=5,
            world_id=6,
            user_id=1,
            auth_token="token",
            scenes=[_scene(102, 11)],
            planned_items=[_planned(102)],
        )

    assert result["status"] == "waiting"
    assert result["error_code"] == "waiting_location_references"
    assert result["retry_after_ms"] > 0
    submit.assert_called_once()
