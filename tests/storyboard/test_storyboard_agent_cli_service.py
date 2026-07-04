from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class FakeSubmitter:
    def __init__(self):
        self.calls = []

    def text_to_image(self, **kwargs):
        self.calls.append(("text_to_image", kwargs))
        return {"success": True, "project_ids": [701], "model_used": "img-model"}

    def image_edit(self, **kwargs):
        self.calls.append(("image_edit", kwargs))
        return {"success": True, "project_ids": [702], "model_used": "edit-model"}

    def text_to_video(self, **kwargs):
        self.calls.append(("text_to_video", kwargs))
        return {"success": True, "project_ids": [801], "model_used": "ttv-model"}

    def image_to_video(self, **kwargs):
        self.calls.append(("image_to_video", kwargs))
        return {"success": True, "project_ids": [802], "model_used": "itv-model"}


@pytest.fixture()
def patched_storyboard_cli(monkeypatch):
    from services import storyboard_agent_cli_service as svc

    scene = SimpleNamespace(
        id=11,
        storyboard_id=22,
        sort_order=1,
        title="Opening",
        duration=6,
        prompt_json={
            "scene_desc": "A detective enters a rainy alley holding 〖〖Umbrella〗〗.",
            "perspective": "medium shot",
            "lighting": "neon rain",
            "location": {"id": 33, "name": "Rain Alley", "db_id": 33},
            "props": [{"id": 44, "name": "Umbrella", "db_id": 44}],
            "source": {"location_db_id": 33},
        },
        video_prompt="Slow dolly in as rain hits the pavement.",
        video_type="video",
        video_config_json=None,
        selected_first_frame_id=101,
        selected_last_frame_id=None,
        selected_video_id=None,
        last_modified_user_id=1,
    )
    storyboard = SimpleNamespace(
        id=22,
        world_id=99,
        user_id=7,
        title="Case",
        style="cinematic noir",
        workflow_ratio="16:9",
        composition_preference="rule of thirds",
        style_reference_image="https://cdn.test/style.png",
        script_id=123,
        config_json={
            "selectedScriptSplitLlmModel": "deepseek-v4-flash",
            "selectedImageTaskId": 1,
        },
    )
    first_asset = SimpleNamespace(
        id=101,
        scene_id=11,
        ai_tool_id=501,
        asset_type="first_frame",
        result_url=None,
    )
    ai_tool = SimpleNamespace(
        id=501,
        status=2,
        message="done",
        result_url="https://cdn.test/first.png",
        project_id="501",
        to_dict=lambda: {
            "id": 501,
            "status": 2,
            "message": "done",
            "result_url": "https://cdn.test/first.png",
            "project_id": "501",
        },
    )
    character = SimpleNamespace(
        id=55,
        name="Lin",
        appearance="black coat",
        reference_image="https://cdn.test/lin.png",
        reference_images=[{"url": "https://cdn.test/lin-ref.png"}],
        to_dict=lambda: {
            "id": 55,
            "name": "Lin",
            "appearance": "black coat",
            "reference_image": "https://cdn.test/lin.png",
            "reference_images": [{"url": "https://cdn.test/lin-ref.png"}],
        },
    )
    location = SimpleNamespace(
        id=33,
        name="Rain Alley",
        description="Wet brick alley",
        reference_image="https://cdn.test/alley.png",
        reference_images=[{"url": "https://cdn.test/alley-ref.png"}],
        to_dict=lambda: {
            "id": 33,
            "name": "Rain Alley",
            "description": "Wet brick alley",
            "reference_image": "https://cdn.test/alley.png",
            "reference_images": [{"url": "https://cdn.test/alley-ref.png"}],
        },
    )
    prop = SimpleNamespace(
        id=44,
        name="Umbrella",
        content="old black umbrella",
        reference_image="https://cdn.test/umbrella.png",
        to_dict=lambda: {
            "id": 44,
            "name": "Umbrella",
            "content": "old black umbrella",
            "reference_image": "https://cdn.test/umbrella.png",
        },
    )

    created_assets = []
    selected_assets = []
    scene_updates = []

    class FakeSceneModel:
        @staticmethod
        def get_by_id(record_id):
            return scene if int(record_id) == 11 else None

        @staticmethod
        def list_by_storyboard(storyboard_id):
            return []

        @staticmethod
        def update(record_id, **kwargs):
            scene_updates.append((record_id, kwargs))
            return 1

        @staticmethod
        def create(**kwargs):
            return 77

        @staticmethod
        def rebalance(storyboard_id):
            return 0

    class FakeStoryboardModel:
        created = []
        existing = None

        @staticmethod
        def get_by_id(record_id):
            return storyboard if int(record_id) == 22 else None

        @staticmethod
        def get_by_user_world_episode(user_id, world_id, episode_number):
            return FakeStoryboardModel.existing

        @staticmethod
        def create(**kwargs):
            FakeStoryboardModel.created.append(kwargs)
            return 321

        @staticmethod
        def update(record_id, **kwargs):
            return 1

        @staticmethod
        def create_scenes(storyboard_id, user_id, scenes):
            return len(scenes)

    class FakeScriptModel:
        @staticmethod
        def get_by_id(record_id):
            if int(record_id) != 123:
                return None
            return SimpleNamespace(
                id=123,
                world_id=99,
                user_id=7,
                title="Case Script",
                episode_number=2,
                content="INT. ALLEY - NIGHT",
                to_dict=lambda: {
                    "id": 123,
                    "world_id": 99,
                    "user_id": 7,
                    "title": "Case Script",
                    "episode_number": 2,
                    "content": "INT. ALLEY - NIGHT",
                },
            )

        @staticmethod
        def get_by_episode(world_id, episode_number):
            return None

    class FakeDialogueModel:
        @staticmethod
        def list_by_scene(scene_id):
            return [{"id": 1, "scene_id": scene_id, "character_id": 55, "text": "Keep walking."}]

    class FakeAssetModel:
        @staticmethod
        def get_by_id(record_id):
            return first_asset if int(record_id) == 101 else None

        @staticmethod
        def create(scene_id, asset_type, ai_tool_id=None, result_url=None):
            asset_id = 900 + len(created_assets)
            created_assets.append(
                {
                    "id": asset_id,
                    "scene_id": scene_id,
                    "asset_type": asset_type,
                    "ai_tool_id": ai_tool_id,
                    "result_url": result_url,
                }
            )
            return asset_id

        @staticmethod
        def set_selected(scene_id, asset_type, asset_id):
            selected_assets.append((scene_id, asset_type, asset_id))
            return 1

        @staticmethod
        def list_by_scene(scene_id, asset_type=None):
            return list(created_assets)

    class FakeAIToolsModel:
        @staticmethod
        def get_by_id(record_id):
            return ai_tool if int(record_id) == 501 else None

    class FakeWorldModel:
        @staticmethod
        def get_by_id(record_id):
            if int(record_id) != 99:
                return None
            return SimpleNamespace(
                id=99,
                user_id=7,
                title="Case World",
                to_dict=lambda: {"id": 99, "user_id": 7, "title": "Case World"},
            )

    batch_jobs = {}
    batch_items = {}

    class FakeBatchJobModel:
        @staticmethod
        def create(**kwargs):
            job_id = 800 + len(batch_jobs)
            batch_jobs[job_id] = {"id": job_id, **kwargs}
            return job_id

        @staticmethod
        def get_by_id(record_id):
            return batch_jobs.get(int(record_id))

        @staticmethod
        def list_active(limit=10):
            return list(batch_jobs.values())[:limit]

        @staticmethod
        def update(record_id, **kwargs):
            batch_jobs[int(record_id)].update(kwargs)
            return 1

    class FakeBatchItemModel:
        @staticmethod
        def create(**kwargs):
            item_id = 9000 + len(batch_items)
            batch_items[item_id] = {"id": item_id, **kwargs}
            return item_id

        @staticmethod
        def get_by_id(record_id):
            return batch_items.get(int(record_id))

        @staticmethod
        def list_by_job(job_id):
            return [
                item
                for item in sorted(batch_items.values(), key=lambda value: (value.get("order_index") or 0, value.get("id") or 0))
                if int(item.get("job_id") or 0) == int(job_id)
            ]

        @staticmethod
        def update(record_id, **kwargs):
            batch_items[int(record_id)].update(kwargs)
            return 1

    monkeypatch.setattr(svc, "StoryboardSceneModel", FakeSceneModel)
    monkeypatch.setattr(svc, "StoryboardModel", FakeStoryboardModel)
    monkeypatch.setattr(svc, "ScriptModel", FakeScriptModel)
    monkeypatch.setattr(svc, "StoryboardDialogueModel", FakeDialogueModel)
    monkeypatch.setattr(svc, "StoryboardSceneAssetModel", FakeAssetModel)
    monkeypatch.setattr(svc, "AIToolsModel", FakeAIToolsModel)
    monkeypatch.setattr(svc, "WorldModel", FakeWorldModel)
    monkeypatch.setattr(svc, "StoryboardImageBatchJobModel", FakeBatchJobModel)
    monkeypatch.setattr(svc, "StoryboardImageBatchItemModel", FakeBatchItemModel)
    monkeypatch.setattr(svc, "CharacterModel", SimpleNamespace(get_by_id=lambda record_id: character))
    monkeypatch.setattr(svc, "LocationModel", SimpleNamespace(get_by_id=lambda record_id: location))
    monkeypatch.setattr(svc, "PropsModel", SimpleNamespace(get_by_id=lambda record_id: prop))

    return SimpleNamespace(
        module=svc,
        submitter=FakeSubmitter(),
        storyboard_model=FakeStoryboardModel,
        created_assets=created_assets,
        selected_assets=selected_assets,
        scene_updates=scene_updates,
        batch_jobs=batch_jobs,
        batch_items=batch_items,
    )


def test_scene_context_collects_scene_prompts_and_reference_assets(patched_storyboard_cli):
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    context = service.scene_context(scene_id=11)

    assert context["scene"]["id"] == 11
    assert context["storyboard"]["world_id"] == 99
    assert context["image_prompt"]
    assert context["video_prompt"] == "Slow dolly in as rain hits the pavement."
    assert context["characters"][0]["id"] == 55
    assert context["location"]["id"] == 33
    assert context["props"][0]["id"] == 44
    assert context["selected_assets"]["first_frame"]["result_url"] == "https://cdn.test/first.png"
    assert "https://cdn.test/umbrella.png" in context["reference_images"]
    assert "https://cdn.test/alley.png" in context["reference_images"]
    assert "https://cdn.test/first.png" not in context["reference_images"]
    assert "https://cdn.test/style.png" not in context["reference_images"]
    assert context["reference_image_items"][0]["label"] == "道具：Umbrella"


def test_create_storyboard_from_script_creates_blank_storyboard(patched_storyboard_cli):
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    result = service.create_storyboard_from_script(script_id=123, user_id=7)

    assert result["success"] is True
    assert result["storyboard_id"] == 321
    assert result["script_id"] == 123
    assert result["created"] is True
    assert patched_storyboard_cli.storyboard_model.created[0]["world_id"] == 99
    assert patched_storyboard_cli.storyboard_model.created[0]["episode_number"] == 2
    assert patched_storyboard_cli.storyboard_model.created[0]["script_id"] == 123
    assert patched_storyboard_cli.storyboard_model.created[0]["title"] == "Case Script"


def test_create_storyboard_from_script_reuses_existing_storyboard(patched_storyboard_cli):
    existing = SimpleNamespace(
        id=654,
        world_id=99,
        user_id=7,
        episode_number=2,
        script_id=123,
        title="Existing",
        to_dict=lambda: {
            "id": 654,
            "world_id": 99,
            "user_id": 7,
            "episode_number": 2,
            "script_id": 123,
            "title": "Existing",
        },
    )
    patched_storyboard_cli.storyboard_model.existing = existing
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    result = service.create_storyboard_from_script(script_id=123, user_id=7)

    assert result["storyboard_id"] == 654
    assert result["created"] is False
    assert patched_storyboard_cli.storyboard_model.created == []


def test_generate_image_text_to_image_binds_first_frame_asset(patched_storyboard_cli):
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    result = service.generate_image(
        scene_id=11,
        user_id=7,
        auth_token="token",
        mode="text_to_image",
        asset_type="first_frame",
    )

    assert result["success"] is True
    assert result["project_ids"] == [701]
    assert patched_storyboard_cli.submitter.calls[0][0] == "text_to_image"
    assert patched_storyboard_cli.created_assets[0]["ai_tool_id"] == 701
    assert patched_storyboard_cli.selected_assets[0] == (11, "first_frame", 900)


def test_generate_image_auto_uses_scene_references_for_image_edit(patched_storyboard_cli):
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    result = service.generate_image(
        scene_id=11,
        user_id=7,
        auth_token="token",
        mode="auto",
        prompt="Make it snow.",
    )

    method, kwargs = patched_storyboard_cli.submitter.calls[0]
    assert result["project_ids"] == [702]
    assert method == "image_edit"
    assert "https://cdn.test/umbrella.png" in kwargs["image_url"]
    assert "https://cdn.test/alley.png" in kwargs["image_url"]
    assert "https://cdn.test/first.png" not in kwargs["image_url"]
    assert "参考图说明" in kwargs["prompt"]
    assert "图1是道具：Umbrella" in kwargs["prompt"]


def test_generate_image_appends_source_image_after_described_references(patched_storyboard_cli):
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    service.generate_image(
        scene_id=11,
        user_id=7,
        auth_token="token",
        mode="image_edit",
        prompt="Keep visual continuity.",
        source_image="https://cdn.test/previous-frame.png",
    )

    method, kwargs = patched_storyboard_cli.submitter.calls[0]
    image_urls = kwargs["image_url"].split(",")

    assert method == "image_edit"
    assert image_urls[-1] == "https://cdn.test/previous-frame.png"
    assert "https://cdn.test/umbrella.png" in image_urls[:-1]
    assert "https://cdn.test/alley.png" in image_urls[:-1]


def test_generate_image_auto_falls_back_to_text_without_references(patched_storyboard_cli, monkeypatch):
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )
    monkeypatch.setattr(service, "_collect_reference_image_items", lambda *args: [])

    result = service.generate_image(
        scene_id=11,
        user_id=7,
        auth_token="token",
        mode="auto",
    )

    method, kwargs = patched_storyboard_cli.submitter.calls[0]
    assert result["project_ids"] == [701]
    assert method == "text_to_image"
    assert kwargs["prompt"]


def test_generate_image_auto_converts_upload_paths_to_public_urls(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module

    monkeypatch.setattr(
        module,
        "get_config",
        lambda: {"server": {"host": "http://localhost:9003"}},
        raising=False,
    )

    service = module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )
    monkeypatch.setattr(
        service,
        "_collect_reference_image_items",
        lambda *args: [
            {
                "url": "upload/location/pic/room.png",
                "source_type": "location",
                "name": "Room",
                "label": "场景：Room",
            },
            {
                "url": "/upload/cache/frame.png",
                "source_type": "asset",
                "name": "已有首帧",
                "label": "已有首帧",
            },
        ],
    )

    service.generate_image(
        scene_id=11,
        user_id=7,
        auth_token="token",
        mode="auto",
    )

    method, kwargs = patched_storyboard_cli.submitter.calls[0]
    assert method == "image_edit"
    assert kwargs["image_url"] == (
        "http://localhost:9003/upload/location/pic/room.png,"
        "http://localhost:9003/upload/cache/frame.png"
    )


def test_scene_context_collects_prompt_matched_character_and_prop_references(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    scene = SimpleNamespace(
        id=11,
        storyboard_id=22,
        title="Prompt match",
        duration=5,
        prompt_json={
            "scene_desc": "【【Lin】】 picks up 〖〖Umbrella〗〗.",
            "character_desc": "Lin",
            "props": [{"name": "Umbrella"}],
            "location": {"name": "Rain Alley", "db_id": 33},
        },
        video_prompt="",
        video_config_json=None,
        selected_first_frame_id=None,
        selected_last_frame_id=None,
        selected_video_id=None,
    )
    storyboard = SimpleNamespace(
        id=22,
        world_id=99,
        style="cinematic noir",
        workflow_ratio="16:9",
        composition_preference="rule of thirds",
        style_reference_image=None,
    )
    matched_character = SimpleNamespace(
        id=77,
        name="Lin",
        reference_image="https://cdn.test/lin-prompt.png",
        reference_images=None,
        to_dict=lambda: {
            "id": 77,
            "name": "Lin",
            "reference_image": "https://cdn.test/lin-prompt.png",
        },
    )
    matched_prop = SimpleNamespace(
        id=88,
        name="Umbrella",
        reference_image="https://cdn.test/umbrella-prompt.png",
        content="old umbrella",
        to_dict=lambda: {
            "id": 88,
            "name": "Umbrella",
            "content": "old umbrella",
            "reference_image": "https://cdn.test/umbrella-prompt.png",
        },
    )

    monkeypatch.setattr(module.StoryboardSceneModel, "get_by_id", lambda record_id: scene)
    monkeypatch.setattr(module.StoryboardModel, "get_by_id", lambda record_id: storyboard)
    monkeypatch.setattr(module.StoryboardDialogueModel, "list_by_scene", lambda scene_id: [])
    monkeypatch.setattr(
        module,
        "CharacterModel",
        SimpleNamespace(
            get_by_id=lambda record_id: None,
            get_by_name=lambda world_id, name: matched_character if name == "Lin" else None,
        ),
    )
    monkeypatch.setattr(
        module,
        "PropsModel",
        SimpleNamespace(
            get_by_id=lambda record_id: None,
            get_by_name=lambda world_id, name: matched_prop if name == "Umbrella" else None,
        ),
    )

    service = module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    context = service.scene_context(scene_id=11)

    assert "https://cdn.test/lin-prompt.png" in context["reference_images"]
    assert "https://cdn.test/umbrella-prompt.png" in context["reference_images"]


def test_scene_context_does_not_use_character_desc_for_reference_images(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    scene = SimpleNamespace(
        id=11,
        storyboard_id=22,
        title="Prompt character scope",
        duration=5,
        prompt_json={
            "scene_desc": "【【Lin】】 walks through the alley.",
            "character_desc": "Lin、Bob",
            "location": {"name": "Rain Alley", "db_id": 33},
        },
        video_prompt="",
        video_config_json=None,
        selected_first_frame_id=None,
        selected_last_frame_id=None,
        selected_video_id=None,
    )
    storyboard = SimpleNamespace(
        id=22,
        world_id=99,
        style="cinematic noir",
        workflow_ratio="16:9",
        composition_preference="rule of thirds",
        style_reference_image=None,
    )
    lin = SimpleNamespace(
        id=77,
        name="Lin",
        reference_image="https://cdn.test/lin-prompt.png",
        to_dict=lambda: {"id": 77, "name": "Lin", "reference_image": "https://cdn.test/lin-prompt.png"},
    )
    bob = SimpleNamespace(
        id=78,
        name="Bob",
        reference_image="https://cdn.test/bob-desc-only.png",
        to_dict=lambda: {"id": 78, "name": "Bob", "reference_image": "https://cdn.test/bob-desc-only.png"},
    )
    location = SimpleNamespace(
        id=33,
        name="Rain Alley",
        reference_image="https://cdn.test/alley.png",
        to_dict=lambda: {"id": 33, "name": "Rain Alley", "reference_image": "https://cdn.test/alley.png"},
    )

    monkeypatch.setattr(module.StoryboardSceneModel, "get_by_id", lambda record_id: scene)
    monkeypatch.setattr(module.StoryboardModel, "get_by_id", lambda record_id: storyboard)
    monkeypatch.setattr(module.StoryboardDialogueModel, "list_by_scene", lambda scene_id: [])
    monkeypatch.setattr(
        module,
        "CharacterModel",
        SimpleNamespace(
            get_by_id=lambda record_id: None,
            get_by_name=lambda world_id, name: lin if name == "Lin" else bob if name == "Bob" else None,
        ),
    )
    monkeypatch.setattr(module, "LocationModel", SimpleNamespace(get_by_id=lambda record_id: location))
    monkeypatch.setattr(module, "PropsModel", SimpleNamespace(get_by_id=lambda record_id: None))

    service = module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    context = service.scene_context(scene_id=11)

    assert "https://cdn.test/lin-prompt.png" in context["reference_images"]
    assert "https://cdn.test/bob-desc-only.png" not in context["reference_images"]


def test_scene_context_does_not_use_stale_prompt_json_props_when_prompt_changed(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    scene = SimpleNamespace(
        id=11,
        storyboard_id=22,
        title="Prompt changed",
        duration=5,
        prompt_json={
            "scene_desc": "【【Lin】】 walks through the alley with empty hands.",
            "props": [{"name": "Umbrella"}],
            "location": {"name": "Rain Alley", "db_id": 33},
        },
        video_prompt="No objects are visible in the shot.",
        video_config_json=None,
        selected_first_frame_id=None,
        selected_last_frame_id=None,
        selected_video_id=None,
    )
    storyboard = SimpleNamespace(
        id=22,
        world_id=99,
        style="cinematic noir",
        workflow_ratio="16:9",
        composition_preference="rule of thirds",
        style_reference_image=None,
    )
    stale_prop = SimpleNamespace(
        id=88,
        name="Umbrella",
        reference_image="https://cdn.test/umbrella-stale.png",
        content="old umbrella",
        to_dict=lambda: {
            "id": 88,
            "name": "Umbrella",
            "content": "old umbrella",
            "reference_image": "https://cdn.test/umbrella-stale.png",
        },
    )

    monkeypatch.setattr(module.StoryboardSceneModel, "get_by_id", lambda record_id: scene)
    monkeypatch.setattr(module.StoryboardModel, "get_by_id", lambda record_id: storyboard)
    monkeypatch.setattr(module.StoryboardDialogueModel, "list_by_scene", lambda scene_id: [])
    monkeypatch.setattr(
        module,
        "CharacterModel",
        SimpleNamespace(
            get_by_id=lambda record_id: None,
            get_by_name=lambda world_id, name: None,
        ),
    )
    monkeypatch.setattr(
        module,
        "PropsModel",
        SimpleNamespace(
            get_by_id=lambda record_id: None,
            get_by_name=lambda world_id, name: stale_prop if name == "Umbrella" else None,
            list_by_world=lambda world_id, page=1, page_size=1000: {"data": [stale_prop.to_dict()]},
        ),
    )

    service = module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    context = service.scene_context(scene_id=11)

    assert "https://cdn.test/umbrella-stale.png" not in context["reference_images"]
    assert context["props"] == []


def test_generate_video_supports_text_and_image_modes(patched_storyboard_cli):
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    text_result = service.generate_video(
        scene_id=11,
        user_id=7,
        auth_token="token",
        mode="text_to_video",
    )
    image_result = service.generate_video(
        scene_id=11,
        user_id=7,
        auth_token="token",
        mode="image_to_video",
        image_mode="first_last_frame",
    )

    assert text_result["project_ids"] == [801]
    assert image_result["project_ids"] == [802]
    assert patched_storyboard_cli.submitter.calls[0][0] == "text_to_video"
    assert patched_storyboard_cli.submitter.calls[1][0] == "image_to_video"
    assert patched_storyboard_cli.submitter.calls[1][1]["image_urls"] == "https://cdn.test/first.png"
    assert patched_storyboard_cli.created_assets[-1]["asset_type"] == "video"


def test_auto_generate_missing_images_defaults_task_type_from_storyboard_config(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    captured_task_types = []
    generated = []

    monkeypatch.setattr(
        module.StoryboardSceneModel,
        "list_by_storyboard",
        lambda storyboard_id: [
            {
                "id": 11,
                "storyboard_id": storyboard_id,
                "title": "Opening",
                "sort_order": 1,
                "selected_first_frame_id": None,
            }
        ],
    )
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)
    monkeypatch.setattr(
        service,
        "_sync_image_model_preference",
        lambda user_id, storyboard, task_type: captured_task_types.append(task_type),
    )
    monkeypatch.setattr(
        service,
        "generate_image",
        lambda **kwargs: generated.append(kwargs)
        or {"project_ids": [701], "asset_ids": [901], "selected_asset_id": 901},
    )

    result = service.auto_generate_missing_images(storyboard_id=22, user_id=7, auth_token="token")

    assert result["submitted_count"] == 1
    assert captured_task_types == [1]
    assert generated[0]["scene_id"] == 11


def test_plan_image_batch_dependencies_by_sequence_mode(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    scenes = [
        {"id": 101, "storyboard_id": 22, "sort_order": 1, "title": "A1", "prompt_json": {"source": {"group_id": "A"}}},
        {"id": 102, "storyboard_id": 22, "sort_order": 2, "title": "A2", "prompt_json": {"source": {"group_id": "A"}}},
        {"id": 103, "storyboard_id": 22, "sort_order": 3, "title": "A3", "prompt_json": {}},
        {"id": 201, "storyboard_id": 22, "sort_order": 4, "title": "B1", "prompt_json": {"source": {"group_id": "B"}}},
        {"id": 202, "storyboard_id": 22, "sort_order": 5, "title": "B2", "prompt_json": {"source": {"group_id": "B"}}},
        {"id": 301, "storyboard_id": 22, "sort_order": 6, "title": "C1", "prompt_json": {"source": {"group_id": "C"}}},
    ]
    monkeypatch.setattr(module.StoryboardSceneModel, "list_by_storyboard", lambda storyboard_id: scenes)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    balanced = service._plan_image_batch_items(storyboard_id=22, asset_type="first_frame", sequence_mode="balanced", limit=20)
    quality = service._plan_image_batch_items(storyboard_id=22, asset_type="first_frame", sequence_mode="quality", limit=20)
    speed = service._plan_image_batch_items(storyboard_id=22, asset_type="first_frame", sequence_mode="speed", limit=20)

    assert [item["scene_id"] for item in balanced if not item.get("dependency_scene_id")] == [101, 201, 301]
    assert {item["scene_id"]: item.get("dependency_scene_id") for item in balanced} == {
        101: None,
        102: 101,
        103: 102,
        201: None,
        202: 201,
        301: None,
    }
    assert {item["scene_id"]: item.get("group_key") for item in balanced}[103] == "group:A"
    assert {item["scene_id"]: item.get("dependency_scene_id") for item in quality} == {
        101: None,
        102: 101,
        103: 102,
        201: 103,
        202: 201,
        301: 202,
    }
    assert all(item.get("dependency_scene_id") is None for item in speed)


def test_process_image_batch_submits_dependent_with_previous_frame_reference(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module

    jobs = {
        88: {
            "id": 88,
            "storyboard_id": 22,
            "user_id": 7,
            "auth_token": "token",
            "asset_type": "first_frame",
            "sequence_mode": "balanced",
            "mode": "auto",
            "prompt": None,
            "source_image": None,
            "ratio": "16:9",
            "image_size": "1K",
            "count": 1,
            "stop_on_error": 1,
            "status": 1,
        }
    }
    items = {
        1: {
            "id": 1,
            "job_id": 88,
            "scene_id": 101,
            "status": 2,
            "result_url": "https://cdn.test/a1.png",
            "order_index": 1,
            "group_key": "group:A",
        },
        2: {
            "id": 2,
            "job_id": 88,
            "scene_id": 102,
            "status": 0,
            "dependency_item_id": 1,
            "order_index": 2,
            "group_key": "group:A",
        },
    }
    updates = []

    class FakeJobModel:
        @staticmethod
        def list_active(limit=10):
            return [jobs[88]]

        @staticmethod
        def update(job_id, **kwargs):
            jobs[job_id].update(kwargs)
            return 1

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return [items[1], items[2]]

        @staticmethod
        def get_by_id(record_id):
            return items.get(record_id)

        @staticmethod
        def update(record_id, **kwargs):
            updates.append((record_id, kwargs))
            items[record_id].update(kwargs)
            return 1

    monkeypatch.setattr(module, "StoryboardImageBatchJobModel", FakeJobModel)
    monkeypatch.setattr(module, "StoryboardImageBatchItemModel", FakeItemModel)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)
    monkeypatch.setattr(
        service,
        "generate_image",
        lambda **kwargs: {
            "project_ids": [702],
            "asset_ids": [902],
            "selected_asset_id": 902,
            "request": kwargs,
        },
    )

    result = service.process_image_batch_jobs()

    assert result["submitted_count"] == 1
    running_update = updates[0][1]
    assert running_update["status"] == 1
    assert running_update["reference_item_id"] == 1
    assert running_update["reference_url"] == "https://cdn.test/a1.png"
    assert running_update["project_ids"] == [702]
    assert items[2]["status"] == 1


def test_split_from_script_defaults_model_from_storyboard_config_and_returns_scenes(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    captured_parse_kwargs = []
    created_payloads = []
    returned_scenes = [
        {"scene_id": 31, "title": "Scene A", "duration": 5, "sort_order": 0, "selected_first_frame_id": None},
        {"scene_id": 32, "title": "Scene B", "duration": 6, "sort_order": 1, "selected_first_frame_id": None},
    ]

    monkeypatch.setattr(module.StoryboardSceneModel, "list_by_storyboard", lambda storyboard_id: [])
    monkeypatch.setattr(
        module.StoryboardModel,
        "create_scenes",
        lambda storyboard_id, user_id, scenes: created_payloads.append(scenes) or len(scenes),
    )
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)
    monkeypatch.setattr(
        service,
        "_parse_script_to_shots_sync",
        lambda **kwargs: captured_parse_kwargs.append(kwargs) or {"shot_groups": [{"title": "Scene A"}]},
    )
    monkeypatch.setattr(
        service,
        "_build_storyboard_scenes_from_parsed_script",
        lambda parsed_data, style="": [
            {"title": "Scene A", "duration": 5, "prompt": {"scene_desc": "A"}},
            {"title": "Scene B", "duration": 6, "prompt": {"scene_desc": "B"}},
        ],
    )
    monkeypatch.setattr(service, "list_scenes", lambda storyboard_id, user_id=None: {"success": True, "scenes": returned_scenes})

    result = service.split_from_script(storyboard_id=22, user_id=7, auth_token="token")

    assert captured_parse_kwargs[0]["model"] == "deepseek-v4-flash"
    assert len(created_payloads[0]) == 2
    assert result["generated_count"] == 2
    assert [scene["scene_id"] for scene in result["scenes"]] == [31, 32]


def test_list_scenes_returns_scene_summaries(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    monkeypatch.setattr(
        module.StoryboardSceneModel,
        "list_by_storyboard",
        lambda storyboard_id: [
            {
                "id": 31,
                "storyboard_id": storyboard_id,
                "title": "Scene A",
                "duration": 5,
                "sort_order": 0,
                "selected_first_frame_id": 101,
                "first_frame_url": "https://cdn.test/first.png",
                "selected_last_frame_id": None,
                "selected_video_id": None,
            }
        ],
    )
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    result = service.list_scenes(storyboard_id=22, user_id=7)

    assert result["success"] is True
    assert result["scene_count"] == 1
    assert result["scenes"][0]["scene_id"] == 31
    assert result["scenes"][0]["asset_status"]["first_frame"]["selected_asset_id"] == 101
    assert result["scenes"][0]["asset_status"]["first_frame"]["result_url"] == "https://cdn.test/first.png"


def test_insert_scene_after_existing_scene_creates_between_neighbors(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    scenes = [
        {"id": 31, "storyboard_id": 22, "title": "Scene A", "duration": 5, "sort_order": 10.0},
        {"id": 32, "storyboard_id": 22, "title": "Scene B", "duration": 5, "sort_order": 20.0},
    ]
    created = []

    def fake_get_by_id(record_id):
        if int(record_id) == 77:
            return SimpleNamespace(
                id=77,
                storyboard_id=22,
                title="Inserted",
                duration=4,
                sort_order=15.0,
                prompt_json={"scene_desc": "Inserted beat"},
                video_prompt="Inserted video",
                video_type="video",
                video_config_json=None,
                selected_first_frame_id=None,
                selected_last_frame_id=None,
                selected_video_id=None,
            )
        for scene in scenes:
            if int(scene["id"]) == int(record_id):
                return SimpleNamespace(**scene)
        return None

    monkeypatch.setattr(module.StoryboardSceneModel, "list_by_storyboard", lambda storyboard_id: scenes)
    monkeypatch.setattr(module.StoryboardSceneModel, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(module.StoryboardSceneModel, "rebalance", lambda storyboard_id: 0)
    monkeypatch.setattr(
        module.StoryboardSceneModel,
        "create",
        lambda **kwargs: created.append(kwargs) or 77,
    )
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    result = service.insert_scene(
        storyboard_id=22,
        user_id=7,
        after_scene_id=31,
        title="Inserted",
        duration=4,
        prompt_json={"scene_desc": "Inserted beat"},
        video_prompt="Inserted video",
    )

    assert result["success"] is True
    assert result["scene_id"] == 77
    assert created[0]["storyboard_id"] == 22
    assert created[0]["sort_order"] == 15.0
    assert created[0]["title"] == "Inserted"
    assert created[0]["prompt_json"] == {"scene_desc": "Inserted beat"}
    assert created[0]["last_modified_user_id"] == 7
