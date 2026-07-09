import json

from config.constant import StoryboardAutoGenerateConstants
from model.storyboard_image_batch import StoryboardImageBatchItemModel


def test_find_running_by_grid_task_queries_extra_json(monkeypatch):
    captured = {}

    def fake_execute_query(sql, params, fetch_one=False, fetch_all=False):
        captured["sql"] = sql
        captured["params"] = params
        captured["fetch_one"] = fetch_one
        return {
            "id": 10,
            "job_id": 3,
            "storyboard_id": 5,
            "scene_id": 22,
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING,
            "project_ids": json.dumps(["pid"]),
            "extra_json": json.dumps({"grid_task_id": 88}),
        }

    monkeypatch.setattr("model.storyboard_image_batch.execute_query", fake_execute_query)

    row = StoryboardImageBatchItemModel.find_running_by_grid_task(88, 22)

    assert row["id"] == 10
    assert row["extra_json"]["grid_task_id"] == 88
    assert "JSON_EXTRACT(extra_json, '$.grid_task_id')" in captured["sql"]
    assert captured["params"] == (
        22,
        StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING,
        88,
    )
    assert captured["fetch_one"] is True


def test_find_by_grid_task_queries_extra_json_without_status_filter(monkeypatch):
    captured = {}

    def fake_execute_query(sql, params, fetch_one=False, fetch_all=False):
        captured["sql"] = sql
        captured["params"] = params
        captured["fetch_one"] = fetch_one
        return {
            "id": 11,
            "job_id": 3,
            "storyboard_id": 5,
            "scene_id": 22,
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
            "project_ids": json.dumps(["pid"]),
            "extra_json": json.dumps({"grid_task_id": 88}),
        }

    monkeypatch.setattr("model.storyboard_image_batch.execute_query", fake_execute_query)

    row = StoryboardImageBatchItemModel.find_by_grid_task(88, 22)

    assert row["id"] == 11
    assert row["extra_json"]["grid_task_id"] == 88
    assert "status =" not in captured["sql"]
    assert "JSON_EXTRACT(extra_json, '$.grid_task_id')" in captured["sql"]
    assert captured["params"] == (22, 88)
    assert captured["fetch_one"] is True
