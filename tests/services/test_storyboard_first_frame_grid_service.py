from types import SimpleNamespace

import pytest

from config.constant import StoryboardAutoGenerateConstants
from script_writer_core.constant import ItemType
from services.storyboard_first_frame_grid_service import StoryboardFirstFrameGridService


def test_process_job_submits_ready_scenes_as_first_frame_grid(monkeypatch):
    from services import storyboard_first_frame_grid_service as grid_service_module

    storyboard = SimpleNamespace(
        id=22,
        world_id=99,
        workflow_ratio="9:16",
        style="电影写实",
        composition_preference="三分法构图",
    )
    scenes = [
        {
            "id": 101,
            "storyboard_id": 22,
            "sort_order": 1,
            "title": "分镜1",
            "act_name": "第一幕",
            "prompt_json": {
                "scene_desc": "【【奶酪_Cheese】】坐在驾驶室左侧。",
                "location": {"id": 33, "name": "糖浆陷阱区域"},
                "source": {"group_id": "grp_001", "shot_number": 1},
                "spatial_layout": {
                    "location_path": [{"name": "糖浆陷阱区域", "role": "current_scene"}],
                    "containers": [
                        {
                            "name": "泡泡蒸汽车",
                            "area": "驾驶室",
                            "slots": [
                                {
                                    "slot": "驾驶室左侧",
                                    "screen_position": "画面左侧",
                                    "character_db_id": 55,
                                    "name": "奶酪_Cheese",
                                }
                            ],
                        }
                    ],
                },
            },
        },
        {
            "id": 102,
            "storyboard_id": 22,
            "sort_order": 2,
            "title": "分镜2",
            "act_name": "第一幕",
            "prompt_json": {
                "scene_desc": "【【奶昔_Milkshake】】在驾驶室右侧握住方向盘。",
                "location": {"id": 33, "name": "糖浆陷阱区域"},
                "source": {"group_id": "grp_001", "shot_number": 2},
                "spatial_layout": {
                    "location_path": [{"name": "糖浆陷阱区域", "role": "current_scene"}],
                    "containers": [
                        {
                            "name": "泡泡蒸汽车",
                            "area": "驾驶室",
                            "slots": [
                                {
                                    "slot": "驾驶室右侧带方向盘位置",
                                    "screen_position": "画面右侧",
                                    "character_db_id": 56,
                                    "name": "奶昔_Milkshake",
                                }
                            ],
                        }
                    ],
                },
            },
        },
    ]
    items = [
        {
            "id": 1,
            "job_id": 88,
            "scene_id": 101,
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
            "order_index": 1,
            "extra_json": {"sort_order": 1},
        },
        {
            "id": 2,
            "job_id": 88,
            "scene_id": 102,
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
            "order_index": 2,
            "extra_json": {"sort_order": 2},
        },
    ]
    updates = {}
    submissions = []
    count_updates = []

    class FakeStoryboardModel:
        @staticmethod
        def get_by_id(record_id):
            return storyboard if int(record_id) == 22 else None

    class FakeSceneModel:
        @staticmethod
        def list_by_storyboard(storyboard_id):
            return scenes

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return items

        @staticmethod
        def update(record_id, **kwargs):
            updates[int(record_id)] = kwargs
            for item in items:
                if int(item["id"]) == int(record_id):
                    item.update(kwargs)
            return 1

    class FakeLocationModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(
                id=33,
                name="糖浆陷阱区域",
                reference_image="https://cdn.test/location.png",
                to_dict=lambda: {
                    "id": 33,
                    "name": "糖浆陷阱区域",
                    "reference_image": "https://cdn.test/location.png",
                },
            )

    class FakeCharacterModel:
        @staticmethod
        def get_by_id(record_id):
            name = "奶酪_Cheese" if int(record_id) == 55 else "奶昔_Milkshake"
            return SimpleNamespace(
                id=record_id,
                name=name,
                reference_image=f"https://cdn.test/{record_id}.png",
                to_dict=lambda: {
                    "id": record_id,
                    "name": name,
                    "reference_image": f"https://cdn.test/{record_id}.png",
                },
            )

    monkeypatch.setattr(grid_service_module, "StoryboardModel", FakeStoryboardModel)
    monkeypatch.setattr(grid_service_module, "StoryboardSceneModel", FakeSceneModel)
    monkeypatch.setattr(grid_service_module, "StoryboardImageBatchItemModel", FakeItemModel)
    monkeypatch.setattr(grid_service_module, "LocationModel", FakeLocationModel)
    monkeypatch.setattr(grid_service_module, "CharacterModel", FakeCharacterModel)

    def fake_submit(**kwargs):
        submissions.append(kwargs)
        return {
            "success": True,
            "project_ids": ["pid-grid"],
            "task_key": "grid:u:w:pid-grid",
            "grid_task_id": 77,
        }

    monkeypatch.setattr(grid_service_module, "submit_grid_image_task", fake_submit)

    service = StoryboardFirstFrameGridService(
        counts_updater=lambda job_id: count_updates.append(job_id),
        enable_llm_refine=False,
    )
    result = service.process_job(
        {
            "id": 88,
            "storyboard_id": 22,
            "user_id": 7,
            "auth_token": "token",
            "ratio": None,
        }
    )

    assert result == {"submitted_count": 1, "updated_counts": True}
    assert count_updates == [88]
    assert len(submissions) == 1
    submission = submissions[0]
    assert submission["item_type"] == ItemType.STORYBOARD_FIRST_FRAME_GRID
    assert submission["grid_size"] == 4
    assert submission["aspect_ratio"] == "9:16"
    assert submission["item_names"] == ["分镜1", "分镜2", "placeholder", "placeholder"]
    assert submission["target_entity_ids"] == [101, 102, None, None]
    assert "图片风格：" not in submission["prompts"][0]
    assert "构图倾向：" not in submission["prompts"][0]
    assert submission["global_visual_guidance"] == {
        "image_style": "电影写实",
        "composition_preference": "三分法构图",
        "application_rule": "适用于所有非空格；单格明确指定的机位、景别、主体位置与构图约束优先。",
    }
    assert "驾驶室左侧" in submission["prompts"][0]
    assert updates[1]["status"] == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING
    assert updates[1]["project_ids"] == ["pid-grid"]
    assert updates[1]["extra_json"]["grid_task_id"] == 77
    assert updates[1]["extra_json"]["reference_indices"]
    assert updates[1]["extra_json"]["grid_prompt_cell_context"]["scene_id"] == 101
    assert updates[1]["extra_json"]["grid_prompt_cell_context"]["final_prompt_text"]
    assert updates[1]["extra_json"]["grid_prompt_group_context"]["grid_task_id"] == 77
    assert updates[1]["extra_json"]["grid_prompt_group_context"]["global_visual_guidance"] == (
        submission["global_visual_guidance"]
    )
    assert len(updates[1]["extra_json"]["grid_prompt_group_context"]["cells"]) == 2


def test_process_job_groups_by_parsed_group_before_act_name(monkeypatch):
    from services import storyboard_first_frame_grid_service as grid_service_module

    scenes = []
    items = []
    for idx in range(1, 7):
        scene_id = 700 + idx
        group_id = "grp_001" if idx <= 3 else "grp_002"
        scenes.append(
            {
                "id": scene_id,
                "storyboard_id": 70,
                "sort_order": idx,
                "title": f"分镜{idx}",
                "act_name": "场景1：同一个大场景",
                "prompt_json": {
                    "scene_desc": f"分镜{idx}",
                    "location": {"id": 88, "name": "厨房"},
                    "source": {"group_id": group_id, "group_name": f"{group_id} - 片段"},
                },
            }
        )
        items.append(
            {
                "id": idx,
                "job_id": 170,
                "scene_id": scene_id,
                "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
                "group_key": f"group:{group_id}",
                "order_index": idx,
                "extra_json": {},
            }
        )

    submissions = []

    class FakeStoryboardModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(id=70, world_id=99, workflow_ratio="16:9")

    class FakeSceneModel:
        @staticmethod
        def list_by_storyboard(storyboard_id):
            return scenes

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return items

        @staticmethod
        def update(record_id, **kwargs):
            for item in items:
                if int(item["id"]) == int(record_id):
                    item.update(kwargs)
            return 1

    class FakeLocationModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(
                id=88,
                name="厨房",
                reference_image="https://cdn.test/kitchen.png",
                to_dict=lambda: {
                    "id": 88,
                    "name": "厨房",
                    "reference_image": "https://cdn.test/kitchen.png",
                },
            )

    monkeypatch.setattr(grid_service_module, "StoryboardModel", FakeStoryboardModel)
    monkeypatch.setattr(grid_service_module, "StoryboardSceneModel", FakeSceneModel)
    monkeypatch.setattr(grid_service_module, "StoryboardImageBatchItemModel", FakeItemModel)
    monkeypatch.setattr(grid_service_module, "LocationModel", FakeLocationModel)
    monkeypatch.setattr(
        grid_service_module,
        "submit_grid_image_task",
        lambda **kwargs: submissions.append(kwargs) or {
            "success": True,
            "project_ids": ["pid-grid"],
            "task_key": "grid:test",
            "grid_task_id": 1700,
        },
    )

    result = StoryboardFirstFrameGridService(enable_llm_refine=False).process_job(
        {"id": 170, "storyboard_id": 70, "user_id": 7, "auth_token": "token"}
    )

    assert result["submitted_count"] == 1
    assert len(submissions) == 1
    assert submissions[0]["grid_size"] == 4
    assert submissions[0]["target_entity_ids"] == [701, 702, 703, None]
    assert submissions[0]["item_names"] == ["分镜1", "分镜2", "分镜3", "placeholder"]
    assert items[3]["status"] == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING
    assert items[3]["extra_json"]["waiting"] == "previous_group_first_frame"
    assert items[3]["extra_json"]["previous_scene_id"] == 703


def test_process_job_treats_location_reference_images_as_ready(monkeypatch):
    from services import storyboard_first_frame_grid_service as grid_service_module

    scene = {
        "id": 201,
        "storyboard_id": 23,
        "sort_order": 1,
        "title": "分镜1",
        "act_name": "第一幕",
        "prompt_json": {
            "scene_desc": "糖浆陷阱区域的首帧。",
            "location": {"id": 44, "name": "糖浆陷阱区域"},
            "source": {"group_id": "grp_001"},
        },
    }
    item = {
        "id": 11,
        "job_id": 89,
        "scene_id": 201,
        "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
        "order_index": 1,
        "extra_json": {},
    }
    submissions = []

    class FakeStoryboardModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(id=23, world_id=99, workflow_ratio="16:9")

    class FakeSceneModel:
        @staticmethod
        def list_by_storyboard(storyboard_id):
            return [scene]

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return [item]

        @staticmethod
        def update(record_id, **kwargs):
            item.update(kwargs)
            return 1

    class FakeLocationModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(
                id=44,
                name="糖浆陷阱区域",
                reference_image=None,
                reference_images='[{"url": "https://cdn.test/location-ref.png"}]',
                to_dict=lambda: {
                    "id": 44,
                    "name": "糖浆陷阱区域",
                    "reference_image": None,
                    "reference_images": [{"url": "https://cdn.test/location-ref.png"}],
                },
            )

    monkeypatch.setattr(grid_service_module, "StoryboardModel", FakeStoryboardModel)
    monkeypatch.setattr(grid_service_module, "StoryboardSceneModel", FakeSceneModel)
    monkeypatch.setattr(grid_service_module, "StoryboardImageBatchItemModel", FakeItemModel)
    monkeypatch.setattr(grid_service_module, "LocationModel", FakeLocationModel)
    monkeypatch.setattr(
        grid_service_module,
        "submit_grid_image_task",
        lambda **kwargs: submissions.append(kwargs) or {
            "success": True,
            "project_ids": ["123"],
            "task_key": "grid:test",
            "grid_task_id": 78,
        },
    )

    result = StoryboardFirstFrameGridService(enable_llm_refine=False).process_job(
        {"id": 89, "storyboard_id": 23, "user_id": 7, "auth_token": "token"}
    )

    assert result["submitted_count"] == 1
    assert submissions[0]["reference_images"][0]["url"] == "https://cdn.test/location-ref.png"


def test_process_job_fails_pending_items_when_scene_was_deleted(monkeypatch):
    from services import storyboard_first_frame_grid_service as grid_service_module

    items = [
        {
            "id": 31,
            "job_id": 90,
            "scene_id": 301,
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
            "order_index": 1,
            "extra_json": {"title": "deleted scene"},
        },
    ]
    updates = {}
    count_updates = []

    class FakeStoryboardModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(id=24, world_id=99, workflow_ratio="16:9")

    class FakeSceneModel:
        @staticmethod
        def list_by_storyboard(storyboard_id):
            return []

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return items

        @staticmethod
        def update(record_id, **kwargs):
            updates[int(record_id)] = kwargs
            for item in items:
                if int(item["id"]) == int(record_id):
                    item.update(kwargs)
            return 1

    monkeypatch.setattr(grid_service_module, "StoryboardModel", FakeStoryboardModel)
    monkeypatch.setattr(grid_service_module, "StoryboardSceneModel", FakeSceneModel)
    monkeypatch.setattr(grid_service_module, "StoryboardImageBatchItemModel", FakeItemModel)

    service = StoryboardFirstFrameGridService(
        counts_updater=lambda job_id: count_updates.append(job_id),
        enable_llm_refine=False,
    )
    result = service.process_job(
        {
            "id": 90,
            "storyboard_id": 24,
            "user_id": 7,
            "auth_token": "token",
            "ratio": None,
        }
    )

    assert result == {"submitted_count": 0, "updated_counts": True}
    assert count_updates == [90]
    assert updates[31]["status"] == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
    assert updates[31]["error_code"] == "scene_deleted"
    assert updates[31]["extra_json"]["failure_source"] == "scene_deleted"
    assert updates[31]["extra_json"]["deleted_scene_id"] == 301


def test_process_job_uses_prompt_prop_when_prop_id_is_logical(monkeypatch):
    from services import storyboard_first_frame_grid_service as grid_service_module

    scene = {
        "id": 202,
        "storyboard_id": 24,
        "sort_order": 1,
        "title": "分镜1",
        "act_name": "第一幕",
        "prompt_json": {
            "scene_desc": "泡泡蒸汽车内的首帧。",
            "location": {"id": 45, "name": "迷雾森林"},
            "props": [
                {
                    "id": "prop_001",
                    "name": "泡泡蒸汽车",
                    "reference_image": "https://cdn.test/prop.png",
                }
            ],
            "source": {"group_id": "grp_001"},
        },
    }
    item = {
        "id": 12,
        "job_id": 90,
        "scene_id": 202,
        "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
        "order_index": 1,
        "extra_json": {},
    }
    submissions = []

    class FakeStoryboardModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(id=24, world_id=99, workflow_ratio="16:9")

    class FakeSceneModel:
        @staticmethod
        def list_by_storyboard(storyboard_id):
            return [scene]

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return [item]

        @staticmethod
        def update(record_id, **kwargs):
            item.update(kwargs)
            return 1

    class FakeLocationModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(
                id=45,
                name="迷雾森林",
                reference_image="https://cdn.test/location.png",
                to_dict=lambda: {
                    "id": 45,
                    "name": "迷雾森林",
                    "reference_image": "https://cdn.test/location.png",
                },
            )

    class FakePropsModel:
        @staticmethod
        def get_by_id(record_id):
            raise AssertionError("logical prop ids should not be queried as DB ids")

    monkeypatch.setattr(grid_service_module, "StoryboardModel", FakeStoryboardModel)
    monkeypatch.setattr(grid_service_module, "StoryboardSceneModel", FakeSceneModel)
    monkeypatch.setattr(grid_service_module, "StoryboardImageBatchItemModel", FakeItemModel)
    monkeypatch.setattr(grid_service_module, "LocationModel", FakeLocationModel)
    monkeypatch.setattr(grid_service_module, "PropsModel", FakePropsModel)
    monkeypatch.setattr(
        grid_service_module,
        "submit_grid_image_task",
        lambda **kwargs: submissions.append(kwargs) or {
            "success": True,
            "project_ids": ["123"],
            "task_key": "grid:test",
            "grid_task_id": 79,
        },
    )

    result = StoryboardFirstFrameGridService(enable_llm_refine=False).process_job(
        {"id": 90, "storyboard_id": 24, "user_id": 7, "auth_token": "token"}
    )

    assert result["submitted_count"] == 1
    assert any(ref["url"] == "https://cdn.test/prop.png" for ref in submissions[0]["reference_images"])


def test_process_job_references_previous_group_last_scene_frame(monkeypatch):
    from services import storyboard_first_frame_grid_service as grid_service_module

    scenes = [
        {
            "id": 301,
            "storyboard_id": 31,
            "sort_order": 1,
            "title": "A last",
            "act_name": "Act A",
            "first_frame_url": "https://cdn.test/a-last-cell.png",
            "prompt_json": {
                "scene_desc": "Act A ending.",
                "location": {"id": 51, "name": "A room"},
                "source": {"group_id": "grp_a"},
            },
        },
        {
            "id": 302,
            "storyboard_id": 31,
            "sort_order": 2,
            "title": "B first",
            "act_name": "Act B",
            "prompt_json": {
                "scene_desc": "Act B opening.",
                "location": {"id": 52, "name": "B room"},
                "source": {"group_id": "grp_b"},
            },
        },
    ]
    items = [
        {
            "id": 31,
            "job_id": 91,
            "scene_id": 301,
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_COMPLETED,
            "order_index": 1,
            "result_url": "https://cdn.test/a-last-cell.png",
            "extra_json": {},
        },
        {
            "id": 32,
            "job_id": 91,
            "scene_id": 302,
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
            "order_index": 2,
            "extra_json": {},
        },
    ]
    submissions = []

    class FakeStoryboardModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(id=31, world_id=99, workflow_ratio="16:9")

    class FakeSceneModel:
        @staticmethod
        def list_by_storyboard(storyboard_id):
            return scenes

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return items

        @staticmethod
        def update(record_id, **kwargs):
            for item in items:
                if int(item["id"]) == int(record_id):
                    item.update(kwargs)
            return 1

    class FakeLocationModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(
                id=record_id,
                name=f"location-{record_id}",
                reference_image=f"https://cdn.test/location-{record_id}.png",
                to_dict=lambda: {
                    "id": record_id,
                    "name": f"location-{record_id}",
                    "reference_image": f"https://cdn.test/location-{record_id}.png",
                },
            )

    monkeypatch.setattr(grid_service_module, "StoryboardModel", FakeStoryboardModel)
    monkeypatch.setattr(grid_service_module, "StoryboardSceneModel", FakeSceneModel)
    monkeypatch.setattr(grid_service_module, "StoryboardImageBatchItemModel", FakeItemModel)
    monkeypatch.setattr(grid_service_module, "LocationModel", FakeLocationModel)
    monkeypatch.setattr(
        grid_service_module,
        "submit_grid_image_task",
        lambda **kwargs: submissions.append(kwargs) or {
            "success": True,
            "project_ids": ["pid-b"],
            "task_key": "grid:test",
            "grid_task_id": 80,
        },
    )

    result = StoryboardFirstFrameGridService(enable_llm_refine=False).process_job(
        {"id": 91, "storyboard_id": 31, "user_id": 7, "auth_token": "token"}
    )

    assert result["submitted_count"] == 1
    assert any(ref["url"] == "https://cdn.test/a-last-cell.png" for ref in submissions[0]["reference_images"])
    assert "previous storyboard frame" in submissions[0]["prompts"][0]
    assert "https://cdn.test/a-grid.png" not in str(submissions[0])


def test_process_job_waits_for_previous_group_last_scene_frame(monkeypatch):
    from services import storyboard_first_frame_grid_service as grid_service_module

    scenes = [
        {
            "id": 401,
            "storyboard_id": 32,
            "sort_order": 1,
            "title": "A last",
            "act_name": "Act A",
            "prompt_json": {
                "scene_desc": "Act A ending.",
                "location": {"id": 61, "name": "A room"},
                "source": {"group_id": "grp_a"},
            },
        },
        {
            "id": 402,
            "storyboard_id": 32,
            "sort_order": 2,
            "title": "B first",
            "act_name": "Act B",
            "prompt_json": {
                "scene_desc": "Act B opening.",
                "location": {"id": 62, "name": "B room"},
                "source": {"group_id": "grp_b"},
            },
        },
    ]
    items = [
        {
            "id": 41,
            "job_id": 92,
            "scene_id": 401,
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING,
            "order_index": 1,
            "extra_json": {"grid_source_url": "https://cdn.test/a-grid.png"},
        },
        {
            "id": 42,
            "job_id": 92,
            "scene_id": 402,
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
            "order_index": 2,
            "extra_json": {},
        },
    ]
    submissions = []

    class FakeStoryboardModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(id=32, world_id=99, workflow_ratio="16:9")

    class FakeSceneModel:
        @staticmethod
        def list_by_storyboard(storyboard_id):
            return scenes

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return items

        @staticmethod
        def update(record_id, **kwargs):
            for item in items:
                if int(item["id"]) == int(record_id):
                    item.update(kwargs)
            return 1

    class FakeLocationModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(
                id=record_id,
                name=f"location-{record_id}",
                reference_image=f"https://cdn.test/location-{record_id}.png",
                to_dict=lambda: {
                    "id": record_id,
                    "name": f"location-{record_id}",
                    "reference_image": f"https://cdn.test/location-{record_id}.png",
                },
            )

    monkeypatch.setattr(grid_service_module, "StoryboardModel", FakeStoryboardModel)
    monkeypatch.setattr(grid_service_module, "StoryboardSceneModel", FakeSceneModel)
    monkeypatch.setattr(grid_service_module, "StoryboardImageBatchItemModel", FakeItemModel)
    monkeypatch.setattr(grid_service_module, "LocationModel", FakeLocationModel)
    monkeypatch.setattr(
        grid_service_module,
        "submit_grid_image_task",
        lambda **kwargs: submissions.append(kwargs) or {"success": True},
    )

    result = StoryboardFirstFrameGridService(enable_llm_refine=False).process_job(
        {"id": 92, "storyboard_id": 32, "user_id": 7, "auth_token": "token"}
    )

    assert result["submitted_count"] == 0
    assert submissions == []
    assert items[1]["status"] == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING
    assert items[1]["extra_json"]["waiting"] == "previous_group_first_frame"
    assert items[1]["extra_json"]["previous_scene_id"] == 401


def test_process_job_keeps_waiting_when_previous_group_is_still_active_after_max_ticks(monkeypatch):
    from services import storyboard_first_frame_grid_service as grid_service_module

    scenes = [
        {
            "id": 401,
            "storyboard_id": 32,
            "sort_order": 1,
            "title": "A last",
            "act_name": "Act A",
            "prompt_json": {"location": {"id": 61}, "source": {"group_id": "grp_a"}},
        },
        {
            "id": 402,
            "storyboard_id": 32,
            "sort_order": 2,
            "title": "B first",
            "act_name": "Act B",
            "prompt_json": {"location": {"id": 62}, "source": {"group_id": "grp_b"}},
        },
    ]
    max_ticks = StoryboardAutoGenerateConstants.QUALITY_PREVIOUS_REFERENCE_WAIT_MAX_TICKS
    items = [
        {
            "id": 41,
            "job_id": 92,
            "scene_id": 401,
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING,
            "order_index": 1,
            "extra_json": {},
        },
        {
            "id": 42,
            "job_id": 92,
            "scene_id": 402,
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
            "order_index": 2,
            "extra_json": {"previous_group_reference_wait_count": max_ticks},
        },
    ]
    count_updates = []

    class FakeStoryboardModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(id=32, world_id=99, workflow_ratio="16:9")

    class FakeSceneModel:
        @staticmethod
        def list_by_storyboard(storyboard_id):
            return scenes

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return items

        @staticmethod
        def update(record_id, **kwargs):
            for item in items:
                if int(item["id"]) == int(record_id):
                    item.update(kwargs)
            return 1

    monkeypatch.setattr(grid_service_module, "StoryboardModel", FakeStoryboardModel)
    monkeypatch.setattr(grid_service_module, "StoryboardSceneModel", FakeSceneModel)
    monkeypatch.setattr(grid_service_module, "StoryboardImageBatchItemModel", FakeItemModel)
    monkeypatch.setattr(
        grid_service_module,
        "submit_grid_image_task",
        lambda **kwargs: pytest.fail("active previous group should keep waiting before grid submission"),
    )

    result = StoryboardFirstFrameGridService(
        counts_updater=lambda job_id: count_updates.append(job_id),
        enable_llm_refine=False,
    ).process_job({"id": 92, "storyboard_id": 32, "user_id": 7, "auth_token": "token"})

    assert result["submitted_count"] == 0
    assert result["updated_counts"] is True
    assert count_updates == [92]
    assert items[1]["status"] == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING
    assert items[1].get("error_code") is None
    assert items[1]["extra_json"]["previous_group_reference_wait_count"] == max_ticks + 1
    assert items[1]["extra_json"]["waiting"] == "previous_group_first_frame"


def test_process_job_fails_previous_group_wait_after_terminal_missing_result(monkeypatch):
    from services import storyboard_first_frame_grid_service as grid_service_module

    scenes = [
        {
            "id": 501,
            "storyboard_id": 33,
            "sort_order": 1,
            "title": "A last",
            "act_name": "Act A",
            "prompt_json": {"location": {"id": 71}, "source": {"group_id": "grp_a"}},
        },
        {
            "id": 502,
            "storyboard_id": 33,
            "sort_order": 2,
            "title": "B first",
            "act_name": "Act B",
            "prompt_json": {"location": {"id": 72}, "source": {"group_id": "grp_b"}},
        },
    ]
    max_ticks = StoryboardAutoGenerateConstants.QUALITY_PREVIOUS_REFERENCE_WAIT_MAX_TICKS
    items = [
        {
            "id": 51,
            "job_id": 93,
            "scene_id": 501,
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_COMPLETED,
            "order_index": 1,
            "extra_json": {},
        },
        {
            "id": 52,
            "job_id": 93,
            "scene_id": 502,
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
            "order_index": 2,
            "extra_json": {"previous_group_reference_wait_count": max_ticks},
        },
    ]

    class FakeStoryboardModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(id=33, world_id=99, workflow_ratio="16:9")

    class FakeSceneModel:
        @staticmethod
        def list_by_storyboard(storyboard_id):
            return scenes

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return items

        @staticmethod
        def update(record_id, **kwargs):
            for item in items:
                if int(item["id"]) == int(record_id):
                    item.update(kwargs)
            return 1

    monkeypatch.setattr(grid_service_module, "StoryboardModel", FakeStoryboardModel)
    monkeypatch.setattr(grid_service_module, "StoryboardSceneModel", FakeSceneModel)
    monkeypatch.setattr(grid_service_module, "StoryboardImageBatchItemModel", FakeItemModel)
    monkeypatch.setattr(
        grid_service_module,
        "submit_grid_image_task",
        lambda **kwargs: pytest.fail("terminal missing previous result should fail before grid submission"),
    )

    result = StoryboardFirstFrameGridService(enable_llm_refine=False).process_job(
        {"id": 93, "storyboard_id": 33, "user_id": 7, "auth_token": "token"}
    )

    assert result["submitted_count"] == 0
    assert items[1]["status"] == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
    assert items[1]["error_code"] == StoryboardAutoGenerateConstants.ERROR_PREVIOUS_GROUP_REFERENCE_TIMEOUT
    assert items[1]["extra_json"]["previous_group_reference_wait_count"] == max_ticks + 1
    assert items[1]["extra_json"]["failure_source"] == "previous_group_reference_timeout"


def test_process_job_strict_act_does_not_skip_blocked_middle_group(monkeypatch):
    from services import storyboard_first_frame_grid_service as grid_service_module

    scenes = [
        {
            "id": 601 + index,
            "storyboard_id": 40,
            "sort_order": index + 1,
            "title": f"分镜{index + 1}",
            "act_name": f"第{index + 1}幕",
            "prompt_json": {
                "scene_desc": f"第{index + 1}幕画面",
                "location": {"id": 81 + index, "name": f"场景{index + 1}"},
                "source": {"group_id": f"grp_00{index + 1}"},
            },
        }
        for index in range(3)
    ]
    items = [
        {
            "id": 61 + index,
            "job_id": 94,
            "scene_id": 601 + index,
            "group_key": f"group:grp_00{index + 1}",
            "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
            "order_index": index + 1,
            "extra_json": {},
        }
        for index in range(3)
    ]
    items[0]["status"] = StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING
    items[0]["ai_tool_id"] = 900
    items[2]["extra_json"] = {
        "previous_group_reference_wait_count": (
            StoryboardAutoGenerateConstants.QUALITY_PREVIOUS_REFERENCE_WAIT_MAX_TICKS
        )
    }
    submissions = []

    class FakeStoryboardModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(id=40, world_id=99, workflow_ratio="16:9")

    class FakeSceneModel:
        @staticmethod
        def list_by_storyboard(storyboard_id):
            return scenes

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return items

        @staticmethod
        def update(record_id, **kwargs):
            for item in items:
                if int(item["id"]) == int(record_id):
                    item.update(kwargs)
            return 1

    class FakeLocationModel:
        @staticmethod
        def get_by_id(record_id):
            return SimpleNamespace(
                id=record_id,
                name=f"场景{record_id}",
                reference_image=f"https://cdn.test/location-{record_id}.png",
                to_dict=lambda: {
                    "id": record_id,
                    "name": f"场景{record_id}",
                    "reference_image": f"https://cdn.test/location-{record_id}.png",
                },
            )

    monkeypatch.setattr(grid_service_module, "StoryboardModel", FakeStoryboardModel)
    monkeypatch.setattr(grid_service_module, "StoryboardSceneModel", FakeSceneModel)
    monkeypatch.setattr(grid_service_module, "StoryboardImageBatchItemModel", FakeItemModel)
    monkeypatch.setattr(grid_service_module, "LocationModel", FakeLocationModel)
    monkeypatch.setattr(
        grid_service_module,
        "submit_grid_image_task",
        lambda **kwargs: submissions.append(kwargs) or {
            "success": True,
            "project_ids": ["pid"],
            "task_key": "grid:test",
            "grid_task_id": 901 + len(submissions),
        },
    )

    result = StoryboardFirstFrameGridService(enable_llm_refine=False).process_job(
        {"id": 94, "storyboard_id": 40, "user_id": 7, "auth_token": "token"}
    )

    assert result["submitted_count"] == 0
    assert submissions == []
    assert items[0]["status"] == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING
    assert items[1]["status"] == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING
    assert items[2]["status"] == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING


def test_process_job_quality_missing_location_reference_fails_instead_of_degrading(monkeypatch):
    from model import grid_image_tasks as grid_task_module
    from services import storyboard_first_frame_grid_service as grid_service_module

    scene = {
        "id": 701,
        "storyboard_id": 41,
        "sort_order": 1,
        "title": "分镜1",
        "act_name": "第一幕",
        "prompt_json": {
            "scene_desc": "新场景中的人物",
            "location": {"id": 91, "name": "新场景"},
            "source": {"group_id": "grp_001"},
        },
    }
    item = {
        "id": 71,
        "job_id": 95,
        "scene_id": 701,
        "group_key": "group:grp_001",
        "status": StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_PENDING,
        "order_index": 1,
        "extra_json": {
            "location_grid_wait_count": StoryboardAutoGenerateConstants.QUALITY_WAIT_MAX_TICKS,
        },
    }
    submissions = []

    monkeypatch.setattr(
        grid_service_module.StoryboardModel,
        "get_by_id",
        lambda record_id: SimpleNamespace(id=41, world_id=99, workflow_ratio="16:9"),
    )
    monkeypatch.setattr(
        grid_service_module.StoryboardSceneModel,
        "list_by_storyboard",
        lambda storyboard_id: [scene],
    )
    monkeypatch.setattr(
        grid_service_module.StoryboardImageBatchItemModel,
        "list_by_job",
        lambda job_id: [item],
    )

    def fake_update(record_id, **kwargs):
        item.update(kwargs)
        return 1

    monkeypatch.setattr(
        grid_service_module.StoryboardImageBatchItemModel,
        "update",
        fake_update,
    )
    monkeypatch.setattr(
        grid_service_module.LocationModel,
        "get_by_id",
        lambda record_id: SimpleNamespace(
            id=91,
            name="新场景",
            reference_image=None,
            reference_images=None,
            to_dict=lambda: {
                "id": 91,
                "name": "新场景",
                "reference_image": None,
                "reference_images": None,
            },
        ),
    )
    monkeypatch.setattr(
        grid_task_module.GridImageTasksModel,
        "has_running_grid_for_entity",
        lambda entity_id, item_type=5: False,
    )
    monkeypatch.setattr(
        grid_service_module,
        "submit_grid_image_task",
        lambda **kwargs: submissions.append(kwargs) or {"success": True},
    )

    result = StoryboardFirstFrameGridService(enable_llm_refine=False).process_job(
        {"id": 95, "storyboard_id": 41, "user_id": 7, "auth_token": "token"}
    )

    assert result["submitted_count"] == 0
    assert submissions == []
    assert item["status"] == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
    assert item["error_code"] == "location_reference_generation_failed"
    assert item["extra_json"]["failure_source"] == "location_reference_generation_failed"
    assert "degraded_location_grid_reference" not in item["extra_json"]


def test_llm_refiner_replaces_prompts_by_scene_id_and_grid_index(monkeypatch):
    from llm import llm_client_factory

    class FakeMessage:
        content = (
            '{"shots": ['
            '{"scene_id": 101, "grid_index": 0, "prompt_text": "改写后的镜头1", "reference_indices": [1]},'
            '{"scene_id": 102, "grid_index": 1, "prompt_text": "改写后的镜头2", "reference_indices": [2]}'
            ']}'
        )

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeClient:
        def call_api(self, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(llm_client_factory, "get_llm_client", lambda model, vendor_id=None: FakeClient())
    service = StoryboardFirstFrameGridService(enable_llm_refine=True)

    result = service._refine_prompts_with_llm(
        storyboard={"config_json": {"selectedScriptSplitLlmModel": "fake-model"}},
        scenes=[{"id": 101, "prompt_json": {}}, {"id": 102, "prompt_json": {}}],
        prompts=["原始1", "原始2"],
        manifest=[{"index": 1, "role_description": "场景：A"}, {"index": 2, "role_description": "场景：B"}],
        per_scene_indices={101: [1], 102: [2]},
        auth_token="token",
    )

    assert result == ["改写后的镜头1", "改写后的镜头2"]


def test_llm_refiner_receives_hidden_continuity_but_returns_clean_prompt(monkeypatch):
    from llm import llm_client_factory

    calls = []

    class FakeMessage:
        content = (
            '{"shots": ['
            '{"scene_id": 102, "grid_index": 0, "prompt_text": "近景，聚焦驾驶座上的奶昔_Milkshake，奶酪_Cheese仍在副驾驶座不入画。", "reference_indices": [1]}'
            ']}'
        )

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeClient:
        def call_api(self, **kwargs):
            calls.append(kwargs)
            return FakeResponse()

    monkeypatch.setattr(llm_client_factory, "get_llm_client", lambda model, vendor_id=None: FakeClient())
    service = StoryboardFirstFrameGridService(enable_llm_refine=True)

    scene = {
        "id": 102,
        "prompt_json": {
            "spatial_layout": {
                "containers": [
                    {
                        "name": "泡泡蒸汽车",
                        "area": "驾驶舱",
                        "slots": [
                            {
                                "slot": "驾驶座",
                                "screen_position": "画面中央偏左",
                                "occupant_type": "character",
                                "character_id": "char_001",
                                "name": "奶昔_Milkshake",
                                "visibility": "visible",
                                "framing_role": "primary_subject",
                            },
                            {
                                "slot": "副驾驶座",
                                "screen_position": "画面外（右侧）",
                                "occupant_type": "character",
                                "character_id": "char_002",
                                "name": "奶酪_Cheese",
                                "visibility": "offscreen",
                                "framing_role": "offscreen_continuity",
                            },
                        ],
                    }
                ],
                "continuity": {
                    "notes": "奶酪仍在副驾驶座但处于画面外"
                },
            }
        },
    }

    result = service._refine_prompts_with_llm(
        storyboard={"config_json": {"selectedScriptSplitLlmModel": "fake-model"}},
        scenes=[scene],
        prompts=["原始提示\n副驾驶座是奶酪_Cheese，画面外（右侧）。"],
        manifest=[{"index": 1, "role_description": "角色：奶昔"}, {"index": 2, "role_description": "角色：奶酪"}],
        per_scene_indices={102: [1]},
        auth_token="token",
        rewriter_instruction="ENTERPRISE_VISUAL_CONSTRAINT;",
        global_visual_guidance={
            "image_style": "电影写实",
            "composition_preference": "三分法构图",
        },
    )

    assert "近景，聚焦驾驶座上的奶昔_Milkshake" in result[0]
    assert "副驾驶座不入画" in result[0]
    assert "奶酪_Cheese" not in result[0]
    assert "offscreen_continuity" not in result[0]
    assert "空间布局硬约束" not in result[0]

    payload = calls[0]["messages"][1]["content"]
    assert "hidden_continuity_entities" in payload
    assert "奶酪_Cheese" in payload
    assert "offscreen_continuity" in payload
    assert "global_visual_guidance" in payload
    assert "电影写实" in payload
    system_prompt = calls[0]["messages"][0]["content"]
    assert "slot_integrity_rule" in system_prompt
    assert "camera_anchor_integrity_rule" in system_prompt
    assert "ENTERPRISE_VISUAL_CONSTRAINT;" in system_prompt


def test_clean_cell_prompt_excludes_offscreen_character_and_reference_index():
    service = StoryboardFirstFrameGridService(enable_llm_refine=False)
    scene = {
        "id": 102,
        "title": "分镜2",
        "prompt_json": {
            "scene_desc": "近景，聚焦驾驶座上的奶昔_Milkshake，对奶酪_Cheese说话。",
            "spatial_layout": {
                "containers": [
                    {
                        "name": "泡泡蒸汽车",
                        "area": "驾驶舱",
                        "slots": [
                            {
                                "slot": "驾驶座",
                                "screen_position": "画面中央",
                                "occupant_type": "character",
                                "name": "奶昔_Milkshake",
                                "visibility": "visible",
                                "framing_role": "primary_subject",
                                "pose": "双手紧握拉杆",
                            },
                            {
                                "slot": "副驾驶座",
                                "screen_position": "画面外（右侧）",
                                "occupant_type": "character",
                                "name": "奶酪_Cheese",
                                "visibility": "offscreen",
                                "framing_role": "offscreen_continuity",
                                "pose": "仍在副驾驶座",
                            },
                        ],
                    }
                ],
                "continuity": {"notes": "奶酪仍在副驾驶座但位于画外"},
            },
        },
    }

    prompt = service._build_cell_prompt(
        scene,
        reference_indices=[1],
        manifest=[
            {"index": 1, "role_description": "角色：奶昔_Milkshake"},
            {"index": 2, "role_description": "角色：奶酪_Cheese"},
        ],
    )

    assert "奶昔_Milkshake" in prompt
    assert "双手紧握拉杆" in prompt
    assert "副驾驶座不入画" in prompt
    assert "奶酪_Cheese" not in prompt
    assert "offscreen_continuity" not in prompt
    assert "容器/区域" not in prompt
    assert "图1" in prompt
    assert "图2" not in prompt


def test_cell_prompt_includes_camera_anchor_for_slot_consistency():
    service = StoryboardFirstFrameGridService(enable_llm_refine=False)
    scene = {
        "id": 110,
        "title": "vehicle interior",
        "prompt_json": {
            "scene_desc": "front-row side-by-side vehicle shot",
            "spatial_layout": {
                "camera_anchor": {
                    "description": "outside left window looking into the cabin",
                    "camera_position": "outside left window",
                    "shooting_direction": "through the left window toward the dashboard",
                    "relative_to_character": {
                        "name": "Cheese",
                        "position": "left front 30 degrees",
                        "distance": "medium shot distance",
                    },
                    "screen_composition": "Cheese stays in the front passenger seat, Milkshake stays in the driver seat",
                },
                "containers": [
                    {
                        "name": "bubble steam car",
                        "area": "front cabin",
                        "slots": [
                            {
                                "slot": "front passenger seat",
                                "screen_position": "left side of frame",
                                "occupant_type": "character",
                                "name": "Cheese",
                                "visibility": "visible",
                                "framing_role": "primary_subject",
                            }
                        ],
                    }
                ],
            },
        },
    }

    prompt = service._build_cell_prompt(scene, reference_indices=[], manifest=[])

    assert "outside left window looking into the cabin" in prompt
    assert "through the left window toward the dashboard" in prompt
    assert "front passenger seat" in prompt
    assert "driver seat" in prompt


def test_cell_prompt_prefers_derived_projection_over_raw_screen_position(monkeypatch):
    monkeypatch.setattr("config.constant.Edition.is_enterprise", lambda: True)
    service = StoryboardFirstFrameGridService(enable_llm_refine=False)
    scene = {
        "id": 111,
        "title": "vehicle interior",
        "prompt_json": {
            "scene_desc": "驾驶室镜头",
            "spatial_world": {
                "space_units": [
                    {
                        "space_unit_id": "space_prop_001_cabin",
                        "anchors": [
                            {
                                "anchor_id": "front_driver_seat",
                                "label": "驾驶座",
                                "position_3d": {"x": 0.55, "y": 0.45, "z": 0.25},
                            }
                        ],
                    }
                ]
            },
            "spatial_layout": {
                "space_unit_refs": ["space_prop_001_cabin"],
                "camera_pose": {
                    "space_unit_id": "space_prop_001_cabin",
                    "eye": {"x": 0.0, "y": -0.8, "z": 0.6},
                    "target": {"x": 0.0, "y": 0.45, "z": 0.25},
                    "up": {"x": 0, "y": 0, "z": 1},
                },
                "containers": [
                    {
                        "name": "泡泡蒸汽车",
                        "area": "驾驶室",
                        "slots": [
                            {
                                "slot": "驾驶座",
                                "space_unit_id": "space_prop_001_cabin",
                                "anchor_id": "front_driver_seat",
                                "screen_position": "画面左侧（错误）",
                                "occupant_type": "character",
                                "name": "奶昔_Milkshake",
                                "visibility": "visible",
                                "framing_role": "primary_subject",
                            }
                        ],
                    }
                ],
            },
        },
    }

    prompt = service._build_cell_prompt(scene, reference_indices=[], manifest=[])

    assert "画面右侧" in prompt
    assert "画面左侧（错误）" not in prompt


def test_character_references_from_spatial_skip_offscreen_characters():
    service = StoryboardFirstFrameGridService(enable_llm_refine=False)

    refs = list(service._character_refs_from_spatial({
        "containers": [
            {
                "slots": [
                    {
                        "occupant_type": "character",
                        "character_db_id": 1,
                        "name": "奶昔_Milkshake",
                        "visibility": "visible",
                    },
                    {
                        "occupant_type": "character",
                        "character_db_id": 2,
                        "name": "奶酪_Cheese",
                        "visibility": "offscreen",
                    },
                ]
            }
        ]
    }))

    assert refs == [(1, "奶昔_Milkshake")]


def test_character_references_from_loose_positions_infer_missing_occupant_type():
    service = StoryboardFirstFrameGridService(enable_llm_refine=False)

    refs = list(service._character_refs_from_spatial({
        "loose_positions": [
            {
                "character_id": "char_001",
                "character_db_id": 868,
                "name": "陈逸飞",
                "visibility": "visible",
                "framing_role": "primary_subject",
            },
            {
                "character_id": "char_002",
                "character_db_id": 867,
                "name": "林星辰",
                "visibility": "partial",
                "framing_role": "secondary_continuity",
            },
            {
                "occupant_type": "prop",
                "db_id": 6868,
                "name": "银色指环",
                "visibility": "visible",
            },
        ]
    }))

    assert refs == [(868, "陈逸飞"), (867, "林星辰")]


def test_scene_reference_items_fall_back_to_tagged_character_and_prop_names(monkeypatch):
    from services import storyboard_first_frame_grid_service as grid_service_module

    class FakeCharacterModel:
        @staticmethod
        def get_by_name(world_id, name):
            assert world_id == 9
            if name != "陈逸飞":
                return None
            return SimpleNamespace(
                id=868,
                name=name,
                reference_image="https://cdn.test/chen.png",
            )

    class FakePropsModel:
        @staticmethod
        def get_by_name(world_id, name):
            assert world_id == 9
            if name != "笔记本大别墅计划":
                return None
            return SimpleNamespace(
                id=6867,
                name=name,
                reference_image="https://cdn.test/notebook.png",
            )

    monkeypatch.setattr(grid_service_module, "CharacterModel", FakeCharacterModel)
    monkeypatch.setattr(grid_service_module, "PropsModel", FakePropsModel)

    refs = StoryboardFirstFrameGridService(enable_llm_refine=False)._scene_reference_items(
        {
            "scene_desc": "【【陈逸飞】】翻开〖〖笔记本大别墅计划〗〗。",
            "spatial_layout": {},
            "props": [],
        },
        world_id=9,
    )

    assert refs == [
        {
            "source_type": "character",
            "name": "陈逸飞",
            "url": "https://cdn.test/chen.png",
            "role_description": "角色：陈逸飞",
        },
        {
            "source_type": "prop",
            "name": "笔记本大别墅计划",
            "url": "https://cdn.test/notebook.png",
            "role_description": "道具：笔记本大别墅计划",
        },
    ]


def test_scene_reference_items_do_not_restore_tagged_offscreen_character(monkeypatch):
    from services import storyboard_first_frame_grid_service as grid_service_module

    class FakeCharacterModel:
        @staticmethod
        def get_by_name(world_id, name):
            raise AssertionError("offscreen characters must not be restored from prompt tags")

    monkeypatch.setattr(grid_service_module, "CharacterModel", FakeCharacterModel)

    refs = StoryboardFirstFrameGridService(enable_llm_refine=False)._scene_reference_items(
        {
            "scene_desc": "镜头外的【【林星辰】】仍留在原位。",
            "spatial_layout": {
                "loose_positions": [
                    {
                        "character_id": "char_002",
                        "character_db_id": 867,
                        "name": "林星辰",
                        "visibility": "offscreen",
                        "framing_role": "offscreen_continuity",
                    }
                ]
            },
        },
        world_id=9,
    )

    assert not any(ref["source_type"] == "character" for ref in refs)


def test_llm_refiner_receives_previous_grid_prompt_context(monkeypatch):
    from llm import llm_client_factory

    calls = []

    class FakeMessage:
        content = (
            '{"shots": ['
            '{"scene_id": 201, "grid_index": 0, "prompt_text": "延续上一幕雾气风格的近景。", "reference_indices": [1]}'
            ']}'
        )

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeClient:
        def call_api(self, **kwargs):
            calls.append(kwargs)
            return FakeResponse()

    monkeypatch.setattr(llm_client_factory, "get_llm_client", lambda model, vendor_id=None: FakeClient())
    service = StoryboardFirstFrameGridService(enable_llm_refine=True)

    previous_context = {
        "group_key": "grp_001",
        "cells": [
            {
                "scene_id": 101,
                "final_prompt_text": "上一幕最后一格，泡泡蒸汽车驶入浓雾。",
                "visible_entities": ["奶昔_Milkshake", "泡泡蒸汽车"],
                "spatial_summary": "奶昔在驾驶座，奶酪在副驾驶座但不入画",
            }
        ],
    }

    result = service._refine_prompts_with_llm(
        storyboard={"config_json": {"selectedScriptSplitLlmModel": "fake-model"}},
        scenes=[{"id": 201, "prompt_json": {}}],
        prompts=["当前幕第一格"],
        manifest=[{"index": 1, "role_description": "场景：糖浆区域"}],
        per_scene_indices={201: [1]},
        auth_token="token",
        previous_grid_prompt_context=previous_context,
    )

    assert result == ["延续上一幕雾气风格的近景。"]
    payload = calls[0]["messages"][1]["content"]
    assert "previous_grid_prompt_context" in payload
    assert "上一幕最后一格，泡泡蒸汽车驶入浓雾" in payload
