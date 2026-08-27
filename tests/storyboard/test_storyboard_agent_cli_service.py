from pathlib import Path
import sys
from types import SimpleNamespace
from datetime import datetime, timedelta

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
            # 前端可能存成 dict（{model,model_id,vendor_id}），覆盖 BUG #1 真实场景。
            "selectedScriptSplitLlmModel": {
                "name": "deepseek-v4-pro",
                "model": "deepseek-v4-pro",
                "model_id": 1008,
                "vendor_id": 10,
            },
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
    recalc_calls = []

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

        @staticmethod
        def recalc_total_duration(storyboard_id):
            recalc_calls.append(int(storyboard_id))
            return 9

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
        def list_active_by_storyboard(storyboard_id, asset_type=None, limit=20):
            rows = []
            for job in batch_jobs.values():
                if int(job.get("storyboard_id") or 0) != int(storyboard_id):
                    continue
                if asset_type and job.get("asset_type") != asset_type:
                    continue
                if int(job.get("status") or 0) not in (
                    svc.StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_PENDING,
                    svc.StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_RUNNING,
                ):
                    continue
                rows.append(job)
            return rows[:limit]

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
    monkeypatch.setattr(
        svc,
        "UserPreferencesModel",
        SimpleNamespace(get=lambda *args: None, upsert=lambda *args: 1),
    )
    monkeypatch.setattr(
        svc,
        "_build_cli_generation_snapshots",
        lambda user_id, world_id, *, media_type, modes, explicit_task_id=None, profile_values=None,
        surface=svc.MediaGenerationSurface.STORYBOARD_CLI: {
            svc.MediaGenerationPreferenceService.slot_key(media_type, mode): {
                "schema_version": 1,
                "surface": surface,
                "media_type": media_type,
                "mode": mode,
                "task_id": int(explicit_task_id or (1 if media_type == "image" else 999)),
                "model_key": "fixture-model",
                "model_name": "Fixture Model",
            }
            for mode in modes
        },
    )

    return SimpleNamespace(
        module=svc,
        submitter=FakeSubmitter(),
        storyboard_model=FakeStoryboardModel,
        created_assets=created_assets,
        selected_assets=selected_assets,
        scene_updates=scene_updates,
        recalc_calls=recalc_calls,
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
    # 默认拆分模型：2026-08 gemini-3-flash-preview 下线后系统默认切 deepseek-v4-flash
    assert patched_storyboard_cli.storyboard_model.created[0]["config_json"] == {
        "selectedScriptSplitLlmModel": "deepseek-v4-flash"
    }


def test_create_storyboard_from_script_uses_explicit_model_and_saves_world_preference(
    patched_storyboard_cli, monkeypatch
):
    preference_calls = []
    monkeypatch.setattr(
        patched_storyboard_cli.module,
        "UserPreferencesModel",
        SimpleNamespace(
            get=lambda *args: None,
            upsert=lambda *args: preference_calls.append(args) or 1,
        ),
        raising=False,
    )
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    result = service.create_storyboard_from_script(
        script_id=123,
        user_id=7,
        model="deepseek-v4-pro",
        model_id=1008,
        vendor_id=10,
    )

    assert result["created"] is True
    selection = patched_storyboard_cli.storyboard_model.created[0]["config_json"][
        "selectedScriptSplitLlmModel"
    ]
    assert selection == {
        "model": "deepseek-v4-pro",
        "model_id": 1008,
        "vendor_id": 10,
    }
    assert preference_calls == [
        ("7", "99", "script_split_llm_model", selection)
    ]
    assert result["preference_saved"] is True


def test_create_storyboard_from_script_inherits_world_model_preference(
    patched_storyboard_cli, monkeypatch
):
    preference = SimpleNamespace(
        get_value=lambda: {
            "model": "deepseek-v4-flash",
            "model_id": 1009,
            "vendor_id": 10,
        }
    )
    monkeypatch.setattr(
        patched_storyboard_cli.module,
        "UserPreferencesModel",
        SimpleNamespace(get=lambda *args: preference, upsert=lambda *args: 1),
        raising=False,
    )
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    service.create_storyboard_from_script(script_id=123, user_id=7)

    assert patched_storyboard_cli.storyboard_model.created[0]["config_json"] == {
        "selectedScriptSplitLlmModel": {
            "model": "deepseek-v4-flash",
            "model_id": 1009,
            "vendor_id": 10,
        }
    }


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


def test_create_storyboard_from_script_reuse_preserves_existing_model(
    patched_storyboard_cli, monkeypatch
):
    existing = patched_storyboard_cli.module.StoryboardModel.get_by_id(22)
    patched_storyboard_cli.storyboard_model.existing = existing
    updates = []
    monkeypatch.setattr(
        patched_storyboard_cli.storyboard_model,
        "update",
        staticmethod(lambda record_id, **kwargs: updates.append((record_id, kwargs)) or 1),
    )
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    result = service.create_storyboard_from_script(script_id=123, user_id=7)

    assert result["created"] is False
    assert updates == []


def test_create_storyboard_from_script_explicit_model_overrides_reused_storyboard(
    patched_storyboard_cli, monkeypatch
):
    existing = patched_storyboard_cli.module.StoryboardModel.get_by_id(22)
    patched_storyboard_cli.storyboard_model.existing = existing
    updates = []
    preference_calls = []
    monkeypatch.setattr(
        patched_storyboard_cli.storyboard_model,
        "update",
        staticmethod(lambda record_id, **kwargs: updates.append((record_id, kwargs)) or 1),
    )
    monkeypatch.setattr(
        patched_storyboard_cli.module,
        "UserPreferencesModel",
        SimpleNamespace(
            get=lambda *args: None,
            upsert=lambda *args: preference_calls.append(args) or 1,
        ),
    )
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    result = service.create_storyboard_from_script(
        script_id=123,
        user_id=7,
        model="deepseek-v4-flash",
        model_id=1009,
        vendor_id=10,
    )

    selection = updates[0][1]["config_json"]["selectedScriptSplitLlmModel"]
    assert selection["model"] == "deepseek-v4-flash"
    assert preference_calls[0][-1] == selection
    assert result["preference_saved"] is True


def test_create_storyboard_from_script_reports_preference_save_failure(
    patched_storyboard_cli, monkeypatch
):
    monkeypatch.setattr(
        patched_storyboard_cli.module,
        "UserPreferencesModel",
        SimpleNamespace(
            get=lambda *args: None,
            upsert=lambda *args: (_ for _ in ()).throw(RuntimeError("db unavailable")),
        ),
    )
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    result = service.create_storyboard_from_script(
        script_id=123,
        user_id=7,
        model="deepseek-v4-pro",
    )

    assert result["created"] is True
    assert result["preference_saved"] is False
    assert "偏好同步失败" in result["warning"]


def test_world_context_uses_uniform_pagination_envelopes(
    patched_storyboard_cli, monkeypatch
):
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )
    page = {"total": 1, "page": 1, "page_size": 100, "data": [{"id": 1}]}
    monkeypatch.setattr(service, "list_world_scripts", lambda **kwargs: dict(page))
    monkeypatch.setattr(service, "list_world_characters", lambda *args, **kwargs: dict(page))
    monkeypatch.setattr(service, "list_world_locations", lambda *args, **kwargs: dict(page))
    monkeypatch.setattr(service, "list_world_props", lambda *args, **kwargs: dict(page))

    result = service.world_context(world_id=99, user_id=7)

    for field in ("scripts", "characters", "locations", "props"):
        assert set(result[field]) == {"total", "page", "page_size", "data"}
        assert isinstance(result[field]["data"], list)


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


def test_generate_image_deduplicates_multiline_visual_suffix(patched_storyboard_cli):
    storyboard = patched_storyboard_cli.storyboard_model.get_by_id(22)
    storyboard.style = "cinematic noir\r\nhigh-detail modeling"
    storyboard.composition_preference = "rule of thirds\ndynamic balance"
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    service.generate_image(
        scene_id=11,
        user_id=7,
        auth_token="token",
        mode="text_to_image",
        asset_type="first_frame",
    )

    prompt = patched_storyboard_cli.submitter.calls[0][1]["prompt"]
    assert prompt.count("图片风格：") == 1
    assert prompt.count("构图倾向：") == 1
    assert "图片风格：cinematic noir\nhigh-detail modeling" in prompt
    assert "构图倾向：rule of thirds\ndynamic balance" in prompt


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
    assert kwargs["prompt"].endswith(
        "图片风格：cinematic noir\n构图倾向：rule of thirds"
    )
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

    # The previous-frame image must also be described in the reference legend so
    # that the image model knows what each URL represents (图号与 URL 一一对应).
    prompt = kwargs["prompt"]
    assert "参考图说明" in prompt
    assert "图3是前一分镜。" in prompt
    # legend 图号数量必须与 image_url 队列长度一致
    legend_part = prompt[prompt.index("参考图说明"):]
    assert legend_part.count("图") >= len(image_urls)


def test_generate_image_skips_duplicate_source_image_in_legend(patched_storyboard_cli):
    """When source_image URL coincides with an existing reference URL, the legend
    must not add a duplicate entry (图号仍与去重后的 URL 队列一一对应)."""
    service = patched_storyboard_cli.module.StoryboardAgentCliService(
        submitter=patched_storyboard_cli.submitter
    )

    # alley.png is the scene reference for scene 11; reusing it as source_image
    # should be de-duplicated rather than described twice.
    service.generate_image(
        scene_id=11,
        user_id=7,
        auth_token="token",
        mode="image_edit",
        prompt="Keep visual continuity.",
        source_image="https://cdn.test/alley.png",
    )

    method, kwargs = patched_storyboard_cli.submitter.calls[0]
    image_urls = kwargs["image_url"].split(",")

    assert method == "image_edit"
    # URL queue has no duplicate
    assert image_urls.count("https://cdn.test/alley.png") == 1
    prompt = kwargs["prompt"]
    # legend must not contain a "前一分镜" entry for the duplicated URL
    assert "前一分镜" not in prompt


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


def test_auto_generate_missing_images_uses_cli_snapshot_not_storyboard_config(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
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
        "generate_image",
        lambda **kwargs: generated.append(kwargs)
        or {"project_ids": [701], "asset_ids": [901], "selected_asset_id": 901},
    )

    result = service.auto_generate_missing_images(storyboard_id=22, user_id=7, auth_token="token")

    # 修复后不再同步推进 batch（避免与调度器并发重复提交），交由调度器统一处理。
    # submitted_count 统一为「本次计划待生成数」：此处有 1 个 pending 场景 → submitted_count=1，
    # 与随后 status 查询同源，不再出现 0→N→M 跳变。
    # generate_image 未被同步调用，但因 plan 阶段写入 pending>0，job status 推进为 running。
    assert result["submitted_count"] == 1
    assert result["batch_id"]
    assert result["status"] == "running"
    assert not hasattr(service, "_sync_image_model_preference")
    job = patched_storyboard_cli.batch_jobs[result["batch_id"]]
    assert job["extra_json"]["generation_snapshots"]["image.text_to_image"]["surface"] == "storyboard_cli"
    assert generated == []


def test_auto_generate_images_regenerates_selected_ready_frames(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    monkeypatch.setattr(
        module.StoryboardSceneModel,
        "list_by_storyboard",
        lambda storyboard_id: [
            {
                "id": 11,
                "storyboard_id": storyboard_id,
                "title": "Opening",
                "sort_order": 1,
                "selected_first_frame_id": 101,
            }
        ],
    )
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    result = service.auto_generate_missing_images(
        storyboard_id=22,
        user_id=7,
        auth_token="token",
        scene_ids=[11],
        existing_policy="regenerate",
    )

    assert result["submitted_count"] == 1
    assert result["regenerated_count"] == 1
    assert result["reused_count"] == 0
    assert result["existing_policy"] == "regenerate"
    assert result["items"][0]["status"] == "pending"
    assert result["items"][0]["plan_status"] == "regenerate_pending"
    assert result["items"][0]["asset_id"] is None
    assert result["items"][0]["base_asset_id"] == 101


def test_auto_generate_images_requires_selection_for_regenerate(patched_storyboard_cli):
    module = patched_storyboard_cli.module
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    with pytest.raises(module.StoryboardCliError) as exc:
        service.auto_generate_missing_images(
            storyboard_id=22,
            user_id=7,
            auth_token="token",
            existing_policy="regenerate",
        )

    assert exc.value.error_code == "scene_ids_required"
    assert patched_storyboard_cli.batch_jobs == {}


def test_plan_image_batch_regenerate_keeps_running_and_requeues_ready(
    patched_storyboard_cli, monkeypatch
):
    module = patched_storyboard_cli.module
    scenes = [
        {"id": 1, "storyboard_id": 22, "sort_order": 1, "selected_first_frame_id": 101},
        {"id": 2, "storyboard_id": 22, "sort_order": 2, "selected_first_frame_id": None},
        {"id": 3, "storyboard_id": 22, "sort_order": 3, "selected_first_frame_id": 103},
    ]
    monkeypatch.setattr(module.StoryboardSceneModel, "list_by_storyboard", lambda _id: scenes)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    def selected_asset(scene, _asset_type):
        if scene["id"] == 1:
            return {"id": 101, "ai_tool_id": 501, "status": 2, "result_url": "https://cdn.test/old.png"}
        if scene["id"] == 3:
            return {"id": 103, "ai_tool_id": 503, "status": 1, "result_url": None}
        return None

    monkeypatch.setattr(service, "_selected_asset_for_scene", selected_asset)
    items = service._plan_image_batch_items(
        storyboard_id=22,
        asset_type="first_frame",
        sequence_mode="speed",
        limit=0,
        scene_ids=[1, 2, 3],
        existing_policy="regenerate",
    )

    assert [item["status"] for item in items] == ["regenerate_pending", "pending", "already_running"]
    assert items[0]["base_asset_id"] == 101
    assert items[0]["asset_id"] is None
    assert items[1]["base_asset_id"] is None
    assert items[2]["asset_id"] == 103


def test_completed_regeneration_only_selects_new_asset_when_base_is_still_selected(
    patched_storyboard_cli, monkeypatch
):
    module = patched_storyboard_cli.module
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)
    scene = {"id": 11, "selected_first_frame_id": 101}
    monkeypatch.setattr(module.StoryboardSceneModel, "get_by_id", lambda _id: scene)
    item = {
        "id": 9001,
        "scene_id": 11,
        "asset_type": "first_frame",
        "asset_id": 102,
        "extra_json": {
            "plan_status": "regenerate_pending",
            "base_asset_id": 101,
        },
    }

    service._select_completed_regeneration_asset(item)
    assert patched_storyboard_cli.selected_assets[-1] == (11, "first_frame", 102)

    selected_count = len(patched_storyboard_cli.selected_assets)
    scene["selected_first_frame_id"] = 103
    item["asset_id"] = 104
    service._select_completed_regeneration_asset(item)
    assert len(patched_storyboard_cli.selected_assets) == selected_count


def test_bind_projects_can_create_candidate_without_selecting_it(patched_storyboard_cli):
    module = patched_storyboard_cli.module
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    result = service.bind_projects(
        scene_id=11,
        user_id=7,
        asset_type="first_frame",
        project_ids=[701],
        select_result=False,
    )

    assert result["selected_asset_id"] == result["asset_ids"][0]
    assert patched_storyboard_cli.selected_assets == []


def test_auto_generate_missing_images_reuses_active_identical_batch(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
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

    first = service.auto_generate_missing_images(
        storyboard_id=22,
        user_id=7,
        auth_token="token",
        sequence_mode="balanced",
    )
    second = service.auto_generate_missing_images(
        storyboard_id=22,
        user_id=7,
        auth_token="token",
        sequence_mode="balanced",
    )

    assert second["batch_id"] == first["batch_id"]
    assert second["idempotent_reuse"] is True
    assert len(patched_storyboard_cli.batch_jobs) == 1
    assert len(patched_storyboard_cli.batch_items) == 1


def test_auto_generate_missing_images_rejects_conflicting_active_batch(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
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

    service.auto_generate_missing_images(
        storyboard_id=22,
        user_id=7,
        auth_token="token",
        sequence_mode="balanced",
    )

    with pytest.raises(module.StoryboardCliError) as exc:
        service.auto_generate_missing_images(
            storyboard_id=22,
            user_id=7,
            auth_token="token",
            sequence_mode="speed",
        )

    assert exc.value.error_code == "active_batch_exists"
    assert exc.value.payload["active_batch_id"] == 800
    assert len(patched_storyboard_cli.batch_jobs) == 1


def test_quality_location_preflight_blocks_before_batch_creation(
    patched_storyboard_cli, monkeypatch
):
    module = patched_storyboard_cli.module
    scenes = [{
        "id": 11,
        "storyboard_id": 22,
        "title": "Opening",
        "sort_order": 1,
        "selected_first_frame_id": None,
        "prompt_json": {"source": {"location_db_id": 33}},
    }]
    monkeypatch.setattr(module.StoryboardSceneModel, "list_by_storyboard", lambda _id: scenes)
    monkeypatch.setattr(module.Edition, "is_community", classmethod(lambda cls: False))

    class BlockedCoordinator:
        def preflight(self, **_kwargs):
            return {
                "status": "blocked",
                "error_code": "quality_parent_reference_missing",
                "message": "父场景缺少参考图",
                "blockers": [{
                    "parent_location_id": 33,
                    "affected_scene_ids": [11],
                }],
            }

    monkeypatch.setattr(
        module,
        "get_storyboard_quality_location_reference_coordinator",
        lambda: BlockedCoordinator(),
    )
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    with pytest.raises(module.StoryboardCliError) as exc_info:
        service.auto_generate_missing_images(
            storyboard_id=22,
            user_id=7,
            auth_token="token",
            sequence_mode="quality",
        )

    assert exc_info.value.error_code == "quality_parent_reference_missing"
    assert exc_info.value.payload["blockers"][0]["affected_scene_ids"] == [11]
    assert patched_storyboard_cli.batch_jobs == {}
    assert patched_storyboard_cli.batch_items == {}


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


def test_process_image_batch_fails_running_item_when_grid_task_failed(patched_storyboard_cli, monkeypatch):
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
            "count": 1,
            "stop_on_error": 1,
            "status": 1,
        }
    }
    items = {
        180: {
            "id": 180,
            "job_id": 88,
            "scene_id": 360,
            "status": 1,
            "order_index": 1,
            "extra_json": {"grid_task_id": 454},
        },
        181: {
            "id": 181,
            "job_id": 88,
            "scene_id": 361,
            "status": 0,
            "dependency_item_id": 180,
            "order_index": 2,
            "extra_json": {},
        },
    }
    updates = []

    class FakeJobModel:
        @staticmethod
        def update(job_id, **kwargs):
            jobs[job_id].update(kwargs)
            return 1

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return [items[180], items[181]]

        @staticmethod
        def update(record_id, **kwargs):
            updates.append((record_id, kwargs))
            items[record_id].update(kwargs)
            return 1

    class FakeGridModel:
        @staticmethod
        def get_by_id(record_id):
            assert record_id == 454
            return SimpleNamespace(status=-1, error_message="grid validation failed")

    monkeypatch.setattr(module, "StoryboardImageBatchJobModel", FakeJobModel)
    monkeypatch.setattr(module, "StoryboardImageBatchItemModel", FakeItemModel)
    monkeypatch.setattr(module, "GridImageTasksModel", FakeGridModel)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    result = service._process_one_image_batch_job(jobs[88])

    assert result["submitted_count"] == 0
    assert items[180]["status"] == module.StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
    assert items[180]["error_code"] == module.StoryboardAutoGenerateConstants.ERROR_GRID_FIRST_FRAME_FAILED
    assert items[181]["status"] == module.StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
    assert any(call[0] == 180 for call in updates)


def test_process_image_batch_fails_stale_running_item(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    old_update_at = datetime.now() - timedelta(seconds=module.StoryboardAutoGenerateConstants.BATCH_RUNNING_ITEM_TIMEOUT_SECONDS + 5)
    jobs = {
        88: {
            "id": 88,
            "storyboard_id": 22,
            "user_id": 7,
            "auth_token": "token",
            "asset_type": "first_frame",
            "sequence_mode": "balanced",
            "mode": "auto",
            "count": 1,
            "stop_on_error": 0,
            "status": 1,
        }
    }
    items = {
        180: {
            "id": 180,
            "job_id": 88,
            "scene_id": 360,
            "status": 1,
            "order_index": 1,
            "update_at": old_update_at.isoformat(),
            "extra_json": {},
        }
    }

    class FakeJobModel:
        @staticmethod
        def update(job_id, **kwargs):
            jobs[job_id].update(kwargs)
            return 1

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return [items[180]]

        @staticmethod
        def update(record_id, **kwargs):
            items[record_id].update(kwargs)
            return 1

    monkeypatch.setattr(module, "StoryboardImageBatchJobModel", FakeJobModel)
    monkeypatch.setattr(module, "StoryboardImageBatchItemModel", FakeItemModel)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    result = service._process_one_image_batch_job(jobs[88])

    assert result["submitted_count"] == 0
    assert items[180]["status"] == module.StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED
    assert items[180]["error_code"] == module.StoryboardAutoGenerateConstants.ERROR_BATCH_ITEM_RUNNING_TIMEOUT
    assert jobs[88]["status"] == module.StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_FAILED


def test_quality_first_frame_batch_uses_grid_service(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    calls = []

    class FakeGridService:
        def __init__(self, counts_updater=None):
            self.counts_updater = counts_updater

        def process_job(self, job):
            calls.append(job)
            self.counts_updater(int(job["id"]))
            return {"submitted_count": 2, "updated_counts": True}

    monkeypatch.setattr(module, "StoryboardFirstFrameGridService", FakeGridService)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)
    job = {
        "id": 88,
        "storyboard_id": 22,
        "user_id": 7,
        "auth_token": "t",
        "asset_type": "first_frame",
        "sequence_mode": "quality",
    }
    patched_storyboard_cli.batch_jobs[88] = dict(job)

    result = service._process_one_image_batch_job(job)

    assert result["submitted_count"] == 2
    assert calls == [job]


def test_image_batch_logs_error_when_model_mismatch(patched_storyboard_cli, monkeypatch, caplog):
    """对账防线：非 quality 批任务提交模型与创建时快照不一致时必须打 error。

    线上事故：用户选择 GPT Image 2（task_id=26），实际提交 nano-banana-Pro
    （task_id=7）。此类不一致必须立即在日志/Sentry 暴露。
    """
    import logging

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
            "count": 1,
            "stop_on_error": 1,
            "status": 1,
            "extra_json": {
                "task_type": 26,
                "generation_snapshots": {
                    "image.text_to_image": {"task_id": 26, "model_key": "gpt-image-2-edit"},
                    "image.image_edit": {"task_id": 26, "model_key": "gpt-image-2-edit"},
                },
            },
        }
    }
    items = {
        2: {
            "id": 2,
            "job_id": 88,
            "scene_id": 101,
            "status": 0,
            "order_index": 1,
            "group_key": "group:A",
        },
    }

    class FakeJobModel:
        @staticmethod
        def update(job_id, **kwargs):
            jobs[job_id].update(kwargs)
            return 1

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return [items[2]]

        @staticmethod
        def update(record_id, **kwargs):
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
            "submission": {"model_task_id": 7, "model_used": "nano-banana-Pro"},
        },
    )

    with caplog.at_level(logging.ERROR):
        result = service._process_one_image_batch_job(jobs[88])

    assert result["submitted_count"] == 1
    mismatch_errors = [
        rec for rec in caplog.records
        if "批任务提交模型与快照不一致" in rec.getMessage()
    ]
    assert mismatch_errors, "模型不一致必须打 error 日志"
    message = mismatch_errors[0].getMessage()
    assert "expected_task_id=26" in message
    assert "actual_task_id=7" in message


def test_image_batch_no_error_log_when_model_matches(patched_storyboard_cli, monkeypatch, caplog):
    """模型一致时对账静默通过，不产生误报。"""
    import logging

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
            "count": 1,
            "stop_on_error": 1,
            "status": 1,
            "extra_json": {
                "task_type": 26,
                "generation_snapshots": {
                    "image.text_to_image": {"task_id": 26, "model_key": "gpt-image-2-edit"},
                },
            },
        }
    }
    items = {
        2: {"id": 2, "job_id": 88, "scene_id": 101, "status": 0, "order_index": 1},
    }

    class FakeJobModel:
        @staticmethod
        def update(job_id, **kwargs):
            return 1

    class FakeItemModel:
        @staticmethod
        def list_by_job(job_id):
            return [items[2]]

        @staticmethod
        def update(record_id, **kwargs):
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
            "submission": {"model_task_id": 26, "model_used": "GPT Image 2 图片编辑"},
        },
    )

    with caplog.at_level(logging.ERROR):
        result = service._process_one_image_batch_job(jobs[88])

    assert result["submitted_count"] == 1
    assert not [
        rec for rec in caplog.records
        if "批任务提交模型与快照不一致" in rec.getMessage()
    ]


def test_split_from_script_creates_async_task_and_returns_task_id(patched_storyboard_cli, monkeypatch):
    """BUG #2：split-from-script 改为异步路径，返回 task_id + status_url，不再同步阻塞跑 LLM。"""
    module = patched_storyboard_cli.module
    monkeypatch.setattr(module.StoryboardSceneModel, "list_by_storyboard", lambda storyboard_id: [])

    captured_configs = []

    async def fake_create_split_task(**kwargs):
        captured_configs.append(kwargs.get("request_config") or {})
        return ("task-abc-123", True)

    import api.script_split as script_split_module
    monkeypatch.setattr(script_split_module, "create_split_task", fake_create_split_task)

    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    result = service.split_from_script(
        storyboard_id=22,
        user_id=7,
        auth_token="token",
        sequence_mode="balanced",
        force_overwrite_subscene_grids=True,
    )

    # 异步路径：返回 task_id + status_url + queued，不再返回 generated_count/scenes
    assert result["success"] is True
    assert result["status"] == "queued"
    assert result["task_id"] == "task-abc-123"
    assert result["status_url"] == "/api/script-split/tasks/task-abc-123"
    # BUG #1：config 里是 dict，应被解包成 model 字符串 + model_id + vendor_id 传入 request_config
    cfg = captured_configs[0]
    assert cfg["model"] == "deepseek-v4-pro"
    assert cfg["model_id"] == 1008
    assert cfg["vendor_id"] == 10
    assert cfg["storyboard_id"] == 22
    assert cfg["source"] == "storyboard"
    assert cfg["sequence_mode"] == "balanced"


def test_resolve_split_model_context_unpacks_dict(patched_storyboard_cli, monkeypatch):
    """BUG #1：_resolve_split_model_context 正确解包 dict，避免 str(dict) 拼进 URL。"""
    module = patched_storyboard_cli.module
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)
    storyboard = patched_storyboard_cli.module.StoryboardModel.get_by_id(22)

    # fixture 里 selectedScriptSplitLlmModel 是 dict
    model, model_id, vendor_id = service._resolve_split_model_context(storyboard, None, None, None)
    assert model == "deepseek-v4-pro"
    assert model_id == 1008
    assert vendor_id == 10

    # 显式入参优先
    model, model_id, vendor_id = service._resolve_split_model_context(storyboard, "gpt-4o", 200, 30)
    assert model == "gpt-4o"
    assert model_id == 200
    assert vendor_id == 30

    # 显式入参为 dict 也应解包
    model, model_id, vendor_id = service._resolve_split_model_context(
        storyboard, {"model": "claude-x", "model_id": 300, "vendor_id": 40}, None, None
    )
    assert model == "claude-x"
    assert model_id == 300
    assert vendor_id == 40


def test_resolve_split_model_context_handles_str_config(patched_storyboard_cli, monkeypatch):
    """BUG #1 向后兼容：config 为字符串时只取 model，model_id/vendor_id 为 None。"""
    module = patched_storyboard_cli.module
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)
    storyboard = patched_storyboard_cli.module.StoryboardModel.get_by_id(22)
    # 覆盖 config 为字符串
    storyboard.config_json = {"selectedScriptSplitLlmModel": "gemini-3-flash-preview"}

    model, model_id, vendor_id = service._resolve_split_model_context(storyboard, None, None, None)
    assert model == "gemini-3-flash-preview"
    assert model_id is None
    assert vendor_id is None


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


def _patch_update_scene_models(monkeypatch, module, fixture, *, scene_duration=6,
                                scene_title="Opening", storyboard_total=11,
                                storyboard_user_id=7):
    """Wire isolated fakes for update_scene tests and expose captured calls.

    Reuses the fixture's recalc_calls list (reset per test) so the global
    FakeStoryboardModel.recalc_total_duration records into a clean buffer.
    """
    scene = SimpleNamespace(
        id=11,
        storyboard_id=22,
        title=scene_title,
        duration=scene_duration,
        prompt_json={"scene_desc": "A detective enters a rainy alley."},
        video_prompt="Slow dolly in.",
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
        user_id=storyboard_user_id,
        title="Case",
        total_duration=storyboard_total,
    )
    scene_updates = []
    recalc_calls = fixture.recalc_calls
    recalc_calls.clear()

    def fake_scene_get(record_id):
        return scene if int(record_id) == 11 else None

    def fake_scene_update(record_id, **kwargs):
        scene_updates.append((record_id, kwargs))
        # Reflect changes onto the in-memory scene so get_by_id returns updated state.
        for key, value in kwargs.items():
            setattr(scene, key, value)
        return 1

    def fake_storyboard_get(record_id):
        return storyboard if int(record_id) == 22 else None

    def fake_recalc(storyboard_id):
        recalc_calls.append(int(storyboard_id))
        return 9

    monkeypatch.setattr(module.StoryboardSceneModel, "get_by_id", fake_scene_get)
    monkeypatch.setattr(module.StoryboardSceneModel, "update", fake_scene_update)
    monkeypatch.setattr(module.StoryboardModel, "get_by_id", fake_storyboard_get)
    monkeypatch.setattr(module.StoryboardModel, "recalc_total_duration", fake_recalc)

    return SimpleNamespace(
        scene=scene,
        storyboard=storyboard,
        scene_updates=scene_updates,
        recalc_calls=recalc_calls,
    )


def test_update_scene_duration_recomputes_total_duration(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    fakes = _patch_update_scene_models(monkeypatch, module, patched_storyboard_cli)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    result = service.update_scene(scene_id=11, user_id=7, duration=8)

    assert result["success"] is True
    assert result["scene_id"] == 11
    assert result["storyboard_id"] == 22
    record_id, fields = fakes.scene_updates[0]
    assert record_id == 11
    assert fields["duration"] == 8
    assert fields["last_modified_user_id"] == 7
    # duration changed -> total_duration must be recomputed
    assert fakes.recalc_calls == [22]
    assert result["total_duration"] == 9


def test_update_scene_non_duration_fields_skip_total_recalc(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    fakes = _patch_update_scene_models(monkeypatch, module, patched_storyboard_cli, storyboard_total=11)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    result = service.update_scene(
        scene_id=11,
        user_id=7,
        title="New title",
        prompt_json={"scene_desc": "Updated description."},
        video_prompt="Updated video prompt.",
    )

    fields = fakes.scene_updates[0][1]
    assert fields["title"] == "New title"
    assert fields["prompt_json"] == {"scene_desc": "Updated description."}
    assert fields["video_prompt"] == "Updated video prompt."
    assert "duration" not in fields
    # Non-duration patch must not trigger recalc; total_duration echoes the storyboard value.
    assert fakes.recalc_calls == []
    assert result["total_duration"] == 11


def test_update_scene_without_any_field_raises(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    _patch_update_scene_models(monkeypatch, module, patched_storyboard_cli)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    with pytest.raises(module.StoryboardCliError) as exc:
        service.update_scene(scene_id=11, user_id=7)

    assert exc.value.error_code == "missing_parameter"


def test_update_scene_missing_scene_raises_not_found(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    _patch_update_scene_models(monkeypatch, module, patched_storyboard_cli)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    with pytest.raises(module.StoryboardCliError) as exc:
        service.update_scene(scene_id=999, user_id=7, duration=8)

    assert exc.value.error_code == "not_found"


def test_update_scene_forbidden_for_other_user(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    _patch_update_scene_models(monkeypatch, module, patched_storyboard_cli, storyboard_user_id=7)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    with pytest.raises(module.StoryboardCliError) as exc:
        service.update_scene(scene_id=11, user_id=999, duration=8)

    assert exc.value.error_code == "forbidden"


def test_update_scene_clamps_duration_to_minimum_one(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    fakes = _patch_update_scene_models(monkeypatch, module, patched_storyboard_cli)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    service.update_scene(scene_id=11, user_id=7, duration=0)

    assert fakes.scene_updates[0][1]["duration"] == 1

    service.update_scene(scene_id=11, user_id=7, duration=-3)
    assert fakes.scene_updates[1][1]["duration"] == 1


def test_update_scene_via_command_service_route(patched_storyboard_cli, monkeypatch):
    """The command dispatcher must route update-scene and preserve decimal duration."""
    from services.storyboard_agent_command_service import StoryboardAgentCommandService
    module = patched_storyboard_cli.module
    fakes = _patch_update_scene_models(monkeypatch, module, patched_storyboard_cli)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)
    command_service = StoryboardAgentCommandService(service=service)

    result = command_service.execute("update-scene", {"scene_id": 11, "user_id": 7, "duration": "10.75"})

    assert result["success"] is True
    assert fakes.scene_updates[0][1]["duration"] == 10.75
    assert result["environment"]  # _with_environment adds it


def test_cli_parsed_scene_payload_preserves_decimal_duration(patched_storyboard_cli):
    module = patched_storyboard_cli.module
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)
    parsed_data = {
        "characters": [],
        "locations": [],
        "props": [],
        "spatial_world": {
            "space_units": [
                {
                    "space_unit_id": "space_loc_rain_alley",
                    "name": "雨夜街口空间",
                    "anchors": [{"anchor_id": "street_left", "position_3d": {"x": -0.5, "y": 0, "z": 0}}],
                }
            ]
        },
        "shot_groups": [
            {
                "group_name": "第一幕 - 片段1",
                "act_title": "第一幕",
                "shots": [
                    {
                        "shot_id": "s001",
                        "duration": 4.75,
                        "difficulty": "难",
                        "difficulty_reason": "长动作",
                        "opening_frame_description": "雨夜街口",
                        "spatial_layout": {
                            "schema_version": 1,
                            "location_path": [{"name": "雨夜街口", "role": "current_scene"}],
                            "containers": [],
                        },
                    }
                ],
            }
        ],
    }

    scenes = service._build_storyboard_scenes_from_parsed_script(parsed_data, style="noir")

    assert scenes[0]["duration"] == 4.75
    assert scenes[0]["difficulty"] == "难"
    assert scenes[0]["act_name"] == "第一幕"
    assert scenes[0]["prompt"]["spatial_world"]["space_units"][0]["space_unit_id"] == "space_loc_rain_alley"
    assert scenes[0]["prompt"]["spatial_layout"]["location_path"][0]["name"] == "雨夜街口"
    assert scenes[0]["prompt"]["source"]["difficulty_reason"] == "长动作"


def test_auto_generate_missing_images_rejects_quality_mode_in_community(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    monkeypatch.setattr("config.constant.Edition.is_community", lambda: True)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    with pytest.raises(module.StoryboardCliError) as exc:
        service.auto_generate_missing_images(
            storyboard_id=1,
            user_id=7,
            auth_token="token",
            asset_type="first_frame",
            sequence_mode="quality",
        )

    assert exc.value.error_code == "enterprise_only"
    assert "效果模式仅商业版支持" in exc.value.message


def _scenes_missing(storyboard_id, count):
    """构造 count 个全部缺首帧的分镜。"""
    return [
        {
            "id": 100 + i,
            "storyboard_id": storyboard_id,
            "title": f"Scene {i}",
            "sort_order": i,
            "selected_first_frame_id": None,
        }
        for i in range(1, count + 1)
    ]


def test_auto_generate_missing_images_no_limit_plans_all_scenes(patched_storyboard_cli, monkeypatch):
    """BUG #4：不传 limit 时应规划全部缺失场景，无 limit_reached 截断。"""
    module = patched_storyboard_cli.module
    monkeypatch.setattr(
        module.StoryboardSceneModel,
        "list_by_storyboard",
        lambda storyboard_id: _scenes_missing(storyboard_id, 25),
    )
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    result = service.auto_generate_missing_images(
        storyboard_id=22, user_id=7, auth_token="token", sequence_mode="speed"
    )

    # 25 个全部缺图，不传 limit → 全部规划为 pending，submitted_count=计划数=25
    assert result["limit"] == module.StoryboardAutoGenerateConstants.UNLIMITED_BATCH_LIMIT
    assert result["submitted_count"] == 25
    items = result["items"]
    assert len(items) == 25
    assert all(item["plan_status"] == "pending" for item in items)
    assert all(item["status"] == "pending" for item in items)
    assert not any(item.get("plan_status") == "limit_reached" for item in items)


def test_auto_generate_missing_images_explicit_limit_truncates(patched_storyboard_cli, monkeypatch):
    """BUG #4：显式传 limit=5 时只规划前 5 个，其余标 limit_reached/skipped。"""
    module = patched_storyboard_cli.module
    monkeypatch.setattr(
        module.StoryboardSceneModel,
        "list_by_storyboard",
        lambda storyboard_id: _scenes_missing(storyboard_id, 25),
    )
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    result = service.auto_generate_missing_images(
        storyboard_id=22, user_id=7, auth_token="token", sequence_mode="speed", limit=5
    )

    assert result["limit"] == 5
    assert result["submitted_count"] == 5
    items = result["items"]
    assert len(items) == 25
    pending = [item for item in items if item["plan_status"] == "pending"]
    limited = [item for item in items if item["plan_status"] == "limit_reached"]
    assert len(pending) == 5
    assert len(limited) == 20
    assert all(item["status"] == "pending" for item in pending)
    assert all(item["status"] == "skipped" for item in limited)


def test_batch_status_returns_aggregated_fields(patched_storyboard_cli, monkeypatch):
    """BUG #3：status 接口聚合字段 progress/total/pending/... 必须非 null 且正确。"""
    module = patched_storyboard_cli.module
    monkeypatch.setattr(
        module.StoryboardSceneModel,
        "list_by_storyboard",
        lambda storyboard_id: _scenes_missing(storyboard_id, 10),
    )
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    create = service.auto_generate_missing_images(
        storyboard_id=22, user_id=7, auth_token="token", sequence_mode="speed", limit=5
    )
    batch_id = create["batch_id"]

    # 提交响应与随后第一次 status 查询的 submitted_count 必须一致（BUG #5）
    assert create["submitted_count"] == 5

    status = service.storyboard_image_batch_status(job_id=batch_id, user_id=7)
    assert status["submitted_count"] == 5  # 与提交响应同源，不跳变

    # 聚合字段全部非 None 且与 items 实际统计一致（BUG #3）
    assert status["total"] == 10
    assert status["pending"] == 5
    assert status["running"] == 0
    assert status["completed"] == 0
    assert status["failed"] == 0
    assert status["skipped"] == 5
    assert status["progress"] == 0.0
    # 旧字段保留做向后兼容
    assert status["completed_count"] == status["completed"]
    assert status["failed_count"] == status["failed"]
    assert status["skipped_count"] == status["skipped"]


def test_batch_status_aggregation_matches_items_after_progress(patched_storyboard_cli, monkeypatch):
    """BUG #3：模拟 2 个完成、1 个失败后，聚合字段随 items 实时变化且正确。"""
    module = patched_storyboard_cli.module
    monkeypatch.setattr(
        module.StoryboardSceneModel,
        "list_by_storyboard",
        lambda storyboard_id: _scenes_missing(storyboard_id, 10),
    )
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    create = service.auto_generate_missing_images(
        storyboard_id=22, user_id=7, auth_token="token", sequence_mode="speed", limit=5
    )
    batch_id = create["batch_id"]

    # 手动推进 item 状态：取前 5 个 pending item，2 个完成、1 个失败、1 个 running、1 个仍 pending
    items = module.StoryboardImageBatchItemModel.list_by_job(batch_id)
    pending_items = [it for it in items if it["status"] == 0][:5]
    module.StoryboardImageBatchItemModel.update(pending_items[0]["id"], status=2)  # completed
    module.StoryboardImageBatchItemModel.update(pending_items[1]["id"], status=2)  # completed
    module.StoryboardImageBatchItemModel.update(pending_items[2]["id"], status=-1)  # failed
    module.StoryboardImageBatchItemModel.update(pending_items[3]["id"], status=1)  # running
    # pending_items[4] 保持 pending

    status = service.storyboard_image_batch_status(job_id=batch_id, user_id=7)
    assert status["total"] == 10
    assert status["pending"] == 1
    assert status["running"] == 1
    assert status["completed"] == 2
    assert status["failed"] == 1
    assert status["skipped"] == 5
    assert status["progress"] == round(2 / 10, 4)
    # submitted_count 仍是计划数，不随进度变化（BUG #5）
    assert status["submitted_count"] == 5


def test_plan_image_batch_only_contains_requested_scenes(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    scenes = [
        {"id": 1, "storyboard_id": 22, "sort_order": 1, "title": "A", "prompt_json": {"source": {"group_id": "act-1"}}},
        {"id": 2, "storyboard_id": 22, "sort_order": 2, "title": "B", "prompt_json": {"source": {"group_id": "act-1"}}},
        {"id": 3, "storyboard_id": 22, "sort_order": 3, "title": "C", "prompt_json": {"source": {"group_id": "act-2"}}},
    ]
    monkeypatch.setattr(module.StoryboardSceneModel, "list_by_storyboard", lambda _id: scenes)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)
    monkeypatch.setattr(service, "_selected_asset_for_scene", lambda _scene, _type: None)

    items = service._plan_image_batch_items(
        storyboard_id=22,
        asset_type="first_frame",
        sequence_mode="quality",
        limit=0,
        scene_ids=[2, 3],
    )

    assert [item["scene_id"] for item in items] == [2, 3]
    assert [item["group_key"] for item in items] == ["group:act-1", "group:act-2"]


def test_requested_scene_ids_rejects_empty_and_foreign_selection(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    monkeypatch.setattr(
        module.StoryboardSceneModel,
        "list_by_storyboard",
        lambda _id: [{"id": 1}, {"id": 2}],
    )
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    with pytest.raises(module.StoryboardCliError) as empty_error:
        service._normalize_requested_scene_ids(22, [])
    assert empty_error.value.error_code == "empty_scene_ids"

    with pytest.raises(module.StoryboardCliError) as stale_error:
        service._normalize_requested_scene_ids(22, [1, 99])
    assert stale_error.value.error_code == "selection_stale"


def test_plan_video_batch_filters_selection_and_requires_first_frame(patched_storyboard_cli, monkeypatch):
    module = patched_storyboard_cli.module
    scenes = [
        {"id": 1, "storyboard_id": 22, "sort_order": 1, "title": "A", "video_type": "video", "prompt_json": {}},
        {"id": 2, "storyboard_id": 22, "sort_order": 2, "title": "B", "video_type": "video", "prompt_json": {}},
        {"id": 3, "storyboard_id": 22, "sort_order": 3, "title": "C", "video_type": "video", "prompt_json": {}},
    ]
    monkeypatch.setattr(module.StoryboardSceneModel, "list_by_storyboard", lambda _id: scenes)
    service = module.StoryboardAgentCliService(submitter=patched_storyboard_cli.submitter)

    def selected_asset(scene, asset_type):
        if asset_type == "first_frame" and scene["id"] == 1:
            return {"id": 101, "result_url": "https://cdn.test/a.png", "status": 2}
        return None

    monkeypatch.setattr(service, "_selected_asset_for_scene", selected_asset)
    items = service._plan_video_batch_items(storyboard_id=22, limit=0, scene_ids=[1, 2])

    assert [item["scene_id"] for item in items] == [1, 2]
    assert items[0]["status"] == "pending"
    assert items[1]["status"] == "missing_first_frame"
    assert items[1]["skip_reason"] == "missing_first_frame"
