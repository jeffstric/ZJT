import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from PIL import Image

_saved_database = sys.modules.get("model.database")
sys.modules["model.database"] = MagicMock()
for _mod in [
    "model.ai_tool_pipeline_steps",
    "model.storyboard_scene_asset",
    "model.storyboard_image_batch",
    "task.pipeline_drivers.storyboard_grid_split_driver",
]:
    if _mod in sys.modules:
        importlib.reload(sys.modules[_mod])

from model.ai_tool_pipeline_steps import PipelineStep, PipelineStepType
from task.pipeline_drivers.storyboard_grid_split_driver import StoryboardGridSplitPipelineDriver

if _saved_database is not None:
    sys.modules["model.database"] = _saved_database
else:
    sys.modules.pop("model.database", None)


def _make_grid(path: Path) -> None:
    img = Image.new("RGB", (200, 200), "white")
    colors = ["red", "green", "blue", "yellow"]
    boxes = [(0, 0, 100, 100), (100, 0, 200, 100), (0, 100, 100, 200), (100, 100, 200, 200)]
    for color, box in zip(colors, boxes):
        Image.new("RGB", (100, 100), color).save(path.with_name(f"cell_{color}.png"))
        patch = Image.open(path.with_name(f"cell_{color}.png"))
        img.paste(patch, box)
        patch.close()
    for x in range(99, 102):
        for y in range(200):
            img.putpixel((x, y), (0, 0, 0))
    for y in range(99, 102):
        for x in range(200):
            img.putpixel((x, y), (0, 0, 0))
    img.save(path)
    img.close()


def test_storyboard_grid_split_driver_writes_only_real_cells(monkeypatch, tmp_path):
    grid_path = tmp_path / "grid.png"
    output_dir = tmp_path / "out"
    _make_grid(grid_path)

    created_assets = []
    selected_assets = []
    updated_items = []

    def fake_create(scene_id, asset_type, ai_tool_id=None, result_url=None):
        asset_id = 9000 + len(created_assets)
        created_assets.append(
            {
                "asset_id": asset_id,
                "scene_id": scene_id,
                "asset_type": asset_type,
                "ai_tool_id": ai_tool_id,
                "result_url": result_url,
            }
        )
        return asset_id

    monkeypatch.setattr(
        "task.pipeline_drivers.storyboard_grid_split_driver.resolve_upload_url_to_local_path",
        lambda value: str(grid_path),
    )
    monkeypatch.setattr(
        "task.pipeline_drivers.storyboard_grid_split_driver.get_config",
        lambda: {"server": {"host": "http://server.test"}},
    )
    monkeypatch.setattr(
        "task.pipeline_drivers.storyboard_grid_split_driver.StoryboardSceneAssetModel.create",
        fake_create,
    )
    monkeypatch.setattr(
        "task.pipeline_drivers.storyboard_grid_split_driver.StoryboardSceneAssetModel.set_selected",
        lambda scene_id, asset_type, asset_id: selected_assets.append((scene_id, asset_type, asset_id)) or 1,
    )
    monkeypatch.setattr(
        "task.pipeline_drivers.storyboard_grid_split_driver.StoryboardImageBatchItemModel.update",
        lambda item_id, **kwargs: updated_items.append((item_id, kwargs)) or 1,
    )

    step = PipelineStep(
        id=12,
        ai_tool_id=77,
        step_type=PipelineStepType.STORYBOARD_FIRST_FRAME_GRID_SPLIT,
        params={
            "grid_size": 4,
            "output_dir": str(output_dir),
            "output_url_path": "upload/storyboard/first_frame",
            "cells": [
                {"grid_index": 0, "scene_id": 101, "batch_item_id": 201},
                {"grid_index": 1, "scene_id": 102, "batch_item_id": 202},
                {"grid_index": 2, "scene_id": 103, "batch_item_id": 203},
                {"grid_index": 3, "placeholder": True},
            ],
        },
    )
    ai_tool = SimpleNamespace(id=77, result_url="/upload/storyboard/temp/grid.png")

    result = asyncio.run(StoryboardGridSplitPipelineDriver().execute(step, ai_tool))

    assert result["success"] is True
    assert [asset["scene_id"] for asset in created_assets] == [101, 102, 103]
    assert all(asset["asset_type"] == "first_frame" for asset in created_assets)
    assert all(asset["ai_tool_id"] == 77 for asset in created_assets)
    assert len(selected_assets) == 3
    assert [item_id for item_id, _ in updated_items] == [201, 202, 203]
    assert result["result_data"]["skipped_cells"] == [3]
    assert len(result["result_data"]["created_assets"]) == 3


def test_storyboard_grid_split_driver_updates_failed_batch_item_on_late_recovery(monkeypatch, tmp_path):
    grid_path = tmp_path / "grid.png"
    output_dir = tmp_path / "out"
    _make_grid(grid_path)

    updated_items = []

    monkeypatch.setattr(
        "task.pipeline_drivers.storyboard_grid_split_driver.resolve_upload_url_to_local_path",
        lambda value: str(grid_path),
    )
    monkeypatch.setattr(
        "task.pipeline_drivers.storyboard_grid_split_driver.get_config",
        lambda: {"server": {"host": "http://server.test"}},
    )
    monkeypatch.setattr(
        "task.pipeline_drivers.storyboard_grid_split_driver.StoryboardSceneAssetModel.create",
        lambda scene_id, asset_type, ai_tool_id=None, result_url=None: 9000 + int(scene_id),
    )
    monkeypatch.setattr(
        "task.pipeline_drivers.storyboard_grid_split_driver.StoryboardSceneAssetModel.set_selected",
        lambda scene_id, asset_type, asset_id: 1,
    )
    monkeypatch.setattr(
        "task.pipeline_drivers.storyboard_grid_split_driver.StoryboardImageBatchItemModel.find_running_by_grid_task",
        lambda grid_task_id, scene_id: None,
    )
    monkeypatch.setattr(
        "task.pipeline_drivers.storyboard_grid_split_driver.StoryboardImageBatchItemModel.find_by_grid_task",
        lambda grid_task_id, scene_id: {"id": 354, "extra_json": {"grid_task_id": grid_task_id}},
    )
    monkeypatch.setattr(
        "task.pipeline_drivers.storyboard_grid_split_driver.StoryboardImageBatchItemModel.update",
        lambda item_id, **kwargs: updated_items.append((item_id, kwargs)) or 1,
    )

    step = PipelineStep(
        id=129,
        ai_tool_id=1123,
        step_type=PipelineStepType.STORYBOARD_FIRST_FRAME_GRID_SPLIT,
        params={
            "grid_task_id": 492,
            "grid_size": 4,
            "output_dir": str(output_dir),
            "output_url_path": "upload/storyboard/first_frame",
            "cells": [
                {"grid_index": 0, "scene_id": 522},
                {"grid_index": 1, "placeholder": True},
                {"grid_index": 2, "placeholder": True},
                {"grid_index": 3, "placeholder": True},
            ],
        },
    )
    ai_tool = SimpleNamespace(id=1123, result_url="/upload/storyboard/temp/grid.png")

    result = asyncio.run(StoryboardGridSplitPipelineDriver().execute(step, ai_tool))

    assert result["success"] is True
    assert updated_items
    item_id, kwargs = updated_items[0]
    assert item_id == 354
    assert kwargs["status"] == 2
    assert kwargs["ai_tool_id"] == 1123
    assert kwargs["asset_id"] == 9522
