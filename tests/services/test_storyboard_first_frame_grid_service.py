from types import SimpleNamespace

from config.constant import StoryboardAutoGenerateConstants
from script_writer_core.constant import ItemType
from services.storyboard_first_frame_grid_service import StoryboardFirstFrameGridService


def test_process_job_submits_ready_scenes_as_first_frame_grid(monkeypatch):
    from services import storyboard_first_frame_grid_service as grid_service_module

    storyboard = SimpleNamespace(id=22, world_id=99, workflow_ratio="9:16")
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
    assert "驾驶室左侧" in submission["prompts"][0]
    assert updates[1]["status"] == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING
    assert updates[1]["project_ids"] == ["pid-grid"]
    assert updates[1]["extra_json"]["grid_task_id"] == 77
    assert updates[1]["extra_json"]["reference_indices"]
    assert updates[1]["extra_json"]["grid_prompt_cell_context"]["scene_id"] == 101
    assert updates[1]["extra_json"]["grid_prompt_cell_context"]["final_prompt_text"]
    assert updates[1]["extra_json"]["grid_prompt_group_context"]["grid_task_id"] == 77
    assert len(updates[1]["extra_json"]["grid_prompt_group_context"]["cells"]) == 2


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
    assert item["status"] == StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING


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
    system_prompt = calls[0]["messages"][0]["content"]
    assert "slot_integrity_rule" in system_prompt
    assert "camera_anchor_integrity_rule" in system_prompt


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
