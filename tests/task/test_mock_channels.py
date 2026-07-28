"""
各通道 mock 短路单元测试。

策略：各 task 模块本身可正常导入（DB 不可用时回退 YAML），且 mock 短路用的是
【函数内 deferred import】，因此直接 monkeypatch `task.mock_interceptor.is_mock_enabled`
即可让短路生效，再把该模块命名空间里的模型类换成 MagicMock 避免 DB 写入。
重点验证：mock 开启时走短路、返回正确的 mock project_id/result_url、真实 driver/factory 不被调用。
"""
import asyncio
from unittest.mock import MagicMock

import pytest

import model
from task import mock_interceptor as mi
from task import visual_task as vt
from task import audio_task as at
from task import sync_task_executor as ste
from task import grid_image_task as git
from task.async_drivers import base_async_driver as bad


@pytest.fixture
def mock_enabled(monkeypatch):
    """开启挡板：让所有通道 deferred import 拿到的 is_mock_enabled 返回 True。"""
    monkeypatch.setattr(mi, "is_mock_enabled", lambda: True)


# ──────────────── §5.1 视觉异步 submit ────────────────
class TestVisualAsyncSubmit:
    def test_short_circuit_returns_true_and_writes_mock_project_id(self, mock_enabled, monkeypatch):
        import task.pipeline_processor as pp
        import task.visual_drivers as vd

        aitools = MagicMock()
        tasks = MagicMock()
        monkeypatch.setattr(vt, "AIToolsModel", aitools)
        monkeypatch.setattr(vt, "TasksModel", tasks)
        monkeypatch.setattr(pp.PipelineProcessor, "get_pending_steps", lambda task_id, stage: [])
        monkeypatch.setattr(vd.VideoDriverFactory, "get_implementation_for_user",
                            lambda ai_tool_type, user_id: None)

        ai_tool = MagicMock()
        ai_tool.type = 5
        ai_tool.id = 1001
        ai_tool.implementation = None
        ai_tool.user_id = 1

        result = asyncio.run(vt._submit_new_task(ai_tool))

        assert result is True
        # 写入了 mock project_id 与 PROCESSING 状态
        aitools.update.assert_called_once()
        _, kwargs = aitools.update.call_args
        assert kwargs["project_id"].startswith(mi.MOCK_PROJECT_PREFIX)
        assert kwargs["status"] == vt.AI_TOOL_STATUS_PROCESSING
        tasks.update_by_task_id.assert_called_once()

    def test_param_prepare_steps_are_not_bypassed_by_mock(self, mock_enabled, monkeypatch):
        import task.pipeline_processor as pp

        aitools = MagicMock()
        tasks = MagicMock()
        monkeypatch.setattr(vt, "AIToolsModel", aitools)
        monkeypatch.setattr(vt, "TasksModel", tasks)
        monkeypatch.setattr(pp.PipelineProcessor, "get_pending_steps", lambda task_id, stage: [MagicMock()])

        ai_tool = MagicMock()
        ai_tool.type = 5
        ai_tool.id = 1002
        ai_tool.implementation = None
        ai_tool.user_id = 1

        result = asyncio.run(vt._submit_new_task(ai_tool))

        assert result is True
        aitools.update.assert_called_once_with(1002, status=vt.AI_TOOL_STATUS_WAITING_PARAM_PREPARE)
        tasks.update_by_task_id.assert_called_once_with(1002, status=vt.TASK_STATUS_WAITING_PARAM_PREPARE)

    def test_sync_mode_is_submitted_to_executor_under_mock(self, mock_enabled, monkeypatch):
        import task.pipeline_processor as pp
        import config.unified_config as uc

        aitools = MagicMock()
        tasks = MagicMock()
        executor = MagicMock()
        executor.is_running.return_value = True
        monkeypatch.setattr(vt, "AIToolsModel", aitools)
        monkeypatch.setattr(vt, "TasksModel", tasks)
        monkeypatch.setattr(pp.PipelineProcessor, "get_pending_steps", lambda task_id, stage: [])
        monkeypatch.setattr(uc, "get_implementation_name", lambda impl: "sync_impl")
        monkeypatch.setattr(uc, "get_implementation_id", lambda name: 77)
        monkeypatch.setattr(uc.UnifiedConfigRegistry, "get_implementation",
                            lambda name: MagicMock(sync_mode=True, name=name))
        monkeypatch.setattr(vt, "get_sync_task_executor", lambda: executor, raising=False)
        import task.sync_task_executor as sync_mod
        monkeypatch.setattr(sync_mod, "get_sync_task_executor", lambda: executor)

        ai_tool = MagicMock()
        ai_tool.type = 5
        ai_tool.id = 1003
        ai_tool.implementation = 77
        ai_tool.user_id = 1

        result = asyncio.run(vt._submit_new_task(ai_tool))

        assert result is True
        executor.submit.assert_called_once_with(1003, 5, "sync_impl")
        aitools.update.assert_any_call(1003, status=vt.AI_TOOL_STATUS_SYNC_QUEUED)


# ──────────────── §5.3 TTS 音频 submit ────────────────
class TestAudioSubmit:
    def test_short_circuit_writes_mock_result_url(self, mock_enabled, monkeypatch):
        monkeypatch.setattr(mi, "mock_audio", lambda subkey="tts": "/upload/mock/e2e_tts.mp3")
        ai_audio_model = MagicMock()
        dialogue_audio_model = MagicMock()
        tasks = MagicMock()
        monkeypatch.setattr(at, "AIAudioModel", ai_audio_model)
        monkeypatch.setattr(at, "StoryboardDialogueAudioModel", dialogue_audio_model)
        monkeypatch.setattr(at, "TasksModel", tasks)

        ai_audio = MagicMock()
        ai_audio.id = 2002

        result = asyncio.run(at._submit_new_task(ai_audio))

        assert result is True
        ai_audio_model.update.assert_called_once()
        _, kwargs = ai_audio_model.update.call_args
        assert kwargs["result_url"] == "/upload/mock/e2e_tts.mp3"
        assert kwargs["status"] == at.AI_AUDIO_STATUS_COMPLETED
        dialogue_audio_model.update_audio_url_by_ai_audio_id.assert_called_once_with(
            2002,
            "/upload/mock/e2e_tts.mp3",
        )


class TestE2EMockFixture:
    def test_mock_mode_writes_full_mock_config(self, monkeypatch):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path("auto_test/e2e").resolve()))
        import auto_test.e2e.conftest as e2e_conftest
        import config.config_util as config_util
        import model.computing_power as computing_power
        import task.sync_task_executor as sync_task_executor

        writes = []
        monkeypatch.setattr(config_util, "get_dynamic_config_value", lambda *args, **kwargs: False)
        monkeypatch.setattr(
            config_util,
            "set_dynamic_config_value",
            lambda *keys, value, value_type="string", **kwargs: writes.append((keys, value, value_type)),
        )
        monkeypatch.setattr(config_util, "invalidate_dynamic_cache", MagicMock())
        monkeypatch.setattr(computing_power.ComputingPowerModel, "create_or_update", MagicMock())
        executor = MagicMock()
        executor.is_running.return_value = False
        monkeypatch.setattr(sync_task_executor, "get_sync_task_executor", lambda: executor)

        fixture_fn = e2e_conftest.mock_mode.__wrapped__
        gen = fixture_fn("123")
        next(gen)
        try:
            next(gen)
        except StopIteration:
            pass

        keys = [w[0] for w in writes]
        assert ("test_mode", "enabled") in keys
        assert ("test_mode", "mock_images", "text_to_image") in keys
        assert ("test_mode", "mock_videos", "image_to_video") in keys
        assert ("test_mode", "mock_audio", "tts") in keys


# ──────────────── §5.2 视觉同步 SyncTaskExecutor ────────────────
class TestSyncExecutor:
    def test_short_circuit_returns_sync_result_with_mock_url(self, mock_enabled, monkeypatch):
        monkeypatch.setattr(mi, "resolve_mock_url_for_visual", lambda t: "/upload/mock/e2e_i2v.mp4")
        # 模型类在 _execute_sync_task 内 deferred import（from model import ...），故 patch 源头 model.*
        monkeypatch.setattr(model, "AIToolsModel", MagicMock())
        monkeypatch.setattr(model, "TasksModel", MagicMock())

        result = ste._execute_sync_task(task_id=3003, ai_tool_type=5)

        assert result.success is True
        assert result.result_url == "/upload/mock/e2e_i2v.mp4"
        assert result.task_id == 3003


# ──────────────── §5.6 四宫格 _resubmit_image_request ────────────────
class TestGridResubmit:
    def test_returns_mock_project_id(self, mock_enabled):
        task = MagicMock()
        pid = git._resubmit_image_request(task)
        assert isinstance(pid, str)
        assert pid.startswith(mi.MOCK_PROJECT_PREFIX)

    def test_reference_image_grid_resubmits_with_image_edit(self, monkeypatch):
        import task.mock_interceptor as mock_interceptor
        import script_writer_core.mcp_tool as mcp

        monkeypatch.setattr(mock_interceptor, "is_mock_enabled", lambda: False)
        monkeypatch.setattr(mcp, "_to_public_http_url", lambda raw_url, base_url: f"http://public/{raw_url.rsplit('/', 1)[-1]}")
        captured = {}

        def fake_post(url, data, timeout, verify, **kwargs):
            captured["url"] = url
            captured["data"] = data
            response = MagicMock()
            response.raise_for_status.return_value = None
            response.json.return_value = {"project_ids": ["new_i2i_project"]}
            return response

        monkeypatch.setattr(git.httpx, "post", fake_post)

        task = MagicMock()
        task.task_key = "grid"
        task.prompt = (
            '{"global_visual_guidance":{"image_style":"皮克斯3D动画"},'
            '"shots":[{"prompt_text":"镜头内容"}]}'
        )
        task.task_config_id = "7"
        task.comfyui_base_url = "http://inner"
        task.user_id = "u"
        task.auth_token = "t"
        task.aspect_ratio = "9:16"
        task.image_size = None
        task.reference_images = '[{"url": "/upload/ref/a.png", "role_description": "ref"}]'

        pid = git._resubmit_image_request(task)

        assert pid == "new_i2i_project"
        assert captured["url"] == "http://inner/api/image-edit"
        assert captured["data"]["ratio"] == "9:16"
        assert captured["data"]["prompt"] == task.prompt
        assert captured["data"]["ref_image_urls"] == "http://public/a.png"
        assert "aspect_ratio" not in captured["data"]


# ──────────────── §5.4 RunningHub 异步 submit（BaseAsyncDriver）────────────────
class _TestAsyncDriver(bad.BaseAsyncDriver):
    """BaseAsyncDriver 的最小可实例化子类（实现抽象方法）。"""

    def __init__(self):
        super().__init__("test_async")

    @property
    def impl_id(self):
        return 99

    async def submit_task(self, **kwargs):
        return {"success": True, "project_id": "should_not_be_reached"}

    async def check_status(self, project_id):
        return {"status": "SUCCESS", "result_url": "x"}


class TestBaseAsyncDriverSubmit:
    def test_short_circuit_skips_slot_and_submit_fn(self, mock_enabled, monkeypatch):
        async_tasks = MagicMock()
        async_tasks.create.return_value = 5555  # async_task_id
        # submit_with_slot_management 内 deferred import（from model import ...），故 patch 源头 model.*
        monkeypatch.setattr(model, "AsyncTasksModel", async_tasks)
        monkeypatch.setattr(model, "RunningHubSlotsModel", MagicMock())
        # get_async_task_config 同样在方法内 deferred import（from config.unified_config import）
        import config.unified_config as uc
        monkeypatch.setattr(uc, "get_async_task_config", lambda impl_id: MagicMock())

        driver = _TestAsyncDriver()
        submit_fn = MagicMock()

        result = asyncio.run(
            driver.submit_with_slot_management(user_id=1, params={"k": "v"}, submit_fn=submit_fn)
        )

        # 真实提交函数绝不能被调用（否则会真实上传/调 RunningHub）
        submit_fn.assert_not_called()
        assert result["success"] is True
        assert result["project_id"].startswith(mi.MOCK_PROJECT_PREFIX)
        assert result["async_task_id"] == 5555
        # external_task_id 已写成 mock（positional: async_task_id, mock_pid）
        async_tasks.update_external_task_id.assert_called_once()
        assert async_tasks.update_external_task_id.call_args.args[1].startswith(mi.MOCK_PROJECT_PREFIX)


# ──────────────── §5.6 四宫格 poll（process_grid_image_tasks）────────────────
class TestGridPoll:
    def test_mock_project_completes_without_http(self, mock_enabled, monkeypatch):
        import task.grid_image_task as git
        monkeypatch.setattr(mi, "_img", lambda k: f"/upload/mock/{k}.png")

        task = MagicMock()
        task.task_key = "k"
        task.project_id = "mock_task_grid1"   # mock id → 触发短路
        task.item_type = 0
        task.try_count = 0                     # 真实 int，避免 MagicMock 比较报错
        task.max_attempts = 60
        task.auth_token = "t"
        task.comfyui_base_url = "http://h"

        grid_model = MagicMock()
        grid_model.get_pending_tasks.return_value = [task]
        # GridImageTasksModel 在 grid_image_task 顶层 import，patch 模块属性而非 model.*
        monkeypatch.setattr(git, "GridImageTasksModel", grid_model)

        handler = MagicMock()
        monkeypatch.setattr(git, "_handle_task_success", handler)

        git.process_grid_image_tasks()

        # mock 分支命中：用 mock file_url 复用 _handle_task_success，未走 requests.get
        handler.assert_called_once()
        _, comfyui_data = handler.call_args.args
        assert comfyui_data["status"] == "SUCCESS"
        assert comfyui_data["results"][0]["file_url"].startswith("/upload/mock/")

    def test_first_frame_grid_mock_uses_grid_image_fixture(self, mock_enabled, monkeypatch):
        import task.grid_image_task as git
        from script_writer_core.constant import ItemType

        monkeypatch.setattr(mi, "_img", lambda k: f"/upload/mock/{k}.png")

        task = MagicMock()
        task.task_key = "first-frame-grid"
        task.project_id = "mock_task_grid_ff"
        task.item_type = ItemType.STORYBOARD_FIRST_FRAME_GRID
        task.try_count = 0
        task.max_attempts = 60
        task.auth_token = "t"
        task.comfyui_base_url = "http://h"

        grid_model = MagicMock()
        grid_model.get_pending_tasks.return_value = [task]
        monkeypatch.setattr(git, "GridImageTasksModel", grid_model)

        handler = MagicMock()
        monkeypatch.setattr(git, "_handle_task_success", handler)

        git.process_grid_image_tasks()

        handler.assert_called_once()
        _, comfyui_data = handler.call_args.args
        assert comfyui_data["results"][0]["file_url"] == "/upload/mock/grid_image.png"

    def test_grid_success_forces_download_even_for_non_mock_url(self, monkeypatch):
        import importlib
        import task.grid_image_task as git

        fake_mcp = MagicMock()
        fake_mcp.update_character_json.return_value = {"success": True}
        monkeypatch.setattr(importlib, "import_module", lambda name: fake_mcp)
        monkeypatch.setattr(git, "get_config", lambda: {
            "image": {"enable_download": False},
            "server": {"host": "http://h"},
        })
        downloader = MagicMock(return_value=("http://h/upload/character/temp/grid.png", "grid.png"))
        monkeypatch.setattr(git, "_download_and_store_image", downloader)
        splitter = MagicMock()
        splitter.split_grid.return_value = ["a.png", "b.png", "c.png", "d.png"]
        monkeypatch.setattr(git, "ImageGridSplitter", MagicMock(return_value=splitter))
        monkeypatch.setattr(git, "validate_grid_image", lambda path, grid_size: MagicMock(is_valid=True, reason="ok", confidence=1.0))
        grid_model = MagicMock()
        monkeypatch.setattr(git, "GridImageTasksModel", grid_model)
        monkeypatch.setattr(git, "_update_task_status_file", MagicMock())

        task = MagicMock()
        task.task_key = "grid"
        task.item_type = 4
        task.item_name = "a,b,c,d"
        task.grid_size = 4
        task.comfyui_base_url = "http://h"
        task.user_id = "u"
        task.world_id = "w"
        task.auth_token = "t"
        task.get_item_names_list = lambda: ["a", "b", "c", "d"]
        task.get_target_entity_ids_list = lambda: []

        git._handle_task_success(task, mi.comfyui_status_success("http://remote.test/grid.png"))

        downloader.assert_called_once_with("http://remote.test/grid.png", 4, "http://h")
        assert fake_mcp.update_character_json.call_count == 4
        grid_model.update_status.assert_called_once()

    def test_first_frame_grid_writeback_creates_assets_and_updates_batch_items(self, monkeypatch):
        import task.grid_image_task as git
        from script_writer_core.constant import ItemType

        monkeypatch.setattr(git, "get_config", lambda: {
            "image": {"enable_download": False},
            "server": {"host": "http://h"},
        })
        monkeypatch.setattr(
            git,
            "_download_and_store_image",
            lambda url, item_type, base: ("http://h/upload/storyboard/temp/grid.png", "grid.png"),
        )
        splitter = MagicMock()
        splitter.split_grid.return_value = [
            "upload/storyboard/first_frame/a.png",
            "upload/storyboard/first_frame/b.png",
            "upload/storyboard/first_frame/c.png",
            "upload/storyboard/first_frame/d.png",
        ]
        monkeypatch.setattr(git, "ImageGridSplitter", MagicMock(return_value=splitter))
        monkeypatch.setattr(git, "validate_grid_image", lambda path, grid_size: MagicMock(is_valid=True, reason="ok", confidence=1.0))
        grid_model = MagicMock()
        monkeypatch.setattr(git, "GridImageTasksModel", grid_model)
        monkeypatch.setattr(git, "_update_task_status_file", MagicMock())

        dispatch_calls = []
        monkeypatch.setattr(
            git,
            "_dispatch_storyboard_first_frame_grid_split",
            lambda task, local_image_url, local_file_path, grid_size: dispatch_calls.append(
                (task.id, local_image_url, local_file_path, grid_size)
            ) or True,
        )

        task = MagicMock()
        task.id = 77
        task.task_key = "first-frame-grid"
        task.item_type = ItemType.STORYBOARD_FIRST_FRAME_GRID
        task.item_name = "scene#101,102,#,#"
        task.grid_size = 4
        task.comfyui_base_url = "http://h"
        task.user_id = "u"
        task.world_id = "w"
        task.auth_token = "t"
        task.project_id = "501"
        task.get_item_names_list = lambda: ["分镜1", "分镜2", "placeholder", "placeholder"]
        task.get_target_entity_ids_list = lambda: [101, 102]

        git._handle_task_success(task, mi.comfyui_status_success("/upload/mock/grid_image.png"))

        assert dispatch_calls == [(77, "http://h/upload/storyboard/temp/grid.png", "grid.png", 4)]
        splitter.split_grid.assert_not_called()
        grid_model.update_status.assert_called_once()

    def test_first_frame_grid_validation_failure_resubmits_before_writeback(self, monkeypatch):
        import task.grid_image_task as git
        from script_writer_core.constant import ItemType

        monkeypatch.setattr(git, "get_config", lambda: {
            "image": {"enable_download": False},
            "server": {"host": "http://h"},
        })
        monkeypatch.setattr(
            git,
            "_download_and_store_image",
            lambda url, item_type, base: ("http://h/upload/storyboard/temp/bad.png", "bad.png"),
        )
        monkeypatch.setattr(
            git,
            "validate_grid_image",
            lambda path, grid_size: MagicMock(is_valid=False, reason="not a uniform grid", confidence=0.1),
        )
        monkeypatch.setattr(git, "_resubmit_image_request", lambda task: "new_project")
        grid_model = MagicMock()
        monkeypatch.setattr(git, "GridImageTasksModel", grid_model)
        monkeypatch.setattr(git, "_update_task_status_file", MagicMock())
        dispatcher = MagicMock()
        monkeypatch.setattr(git, "_dispatch_storyboard_first_frame_grid_split", dispatcher)
        monkeypatch.setattr(git, "ImageGridSplitter", MagicMock())

        task = MagicMock()
        task.id = 77
        task.task_key = "first-frame-grid"
        task.item_type = ItemType.STORYBOARD_FIRST_FRAME_GRID
        task.item_name = "scene#101,102,#,#"
        task.grid_size = 4
        task.max_retries = 2
        task.retry_count = 0
        task.prompt = "{}"
        task.task_config_id = "7"
        task.comfyui_base_url = "http://h"
        task.user_id = "u"
        task.world_id = "w"
        task.auth_token = "t"
        task.project_id = "501"
        task.get_target_entity_ids_list = lambda: [101, 102]

        git._handle_task_success(task, mi.comfyui_status_success("/upload/mock/bad_grid.png"))

        grid_model.reset_for_retry.assert_called_once_with("first-frame-grid", "new_project")
        grid_model.update_status.assert_not_called()
        dispatcher.assert_not_called()

    def test_first_frame_grid_validation_failure_fails_batch_after_two_retries(self, monkeypatch):
        import task.grid_image_task as git
        from script_writer_core.constant import ItemType

        monkeypatch.setattr(git, "get_config", lambda: {
            "image": {"enable_download": False},
            "server": {"host": "http://h"},
        })
        monkeypatch.setattr(
            git,
            "_download_and_store_image",
            lambda url, item_type, base: ("http://h/upload/storyboard/temp/bad.png", "bad.png"),
        )
        monkeypatch.setattr(
            git,
            "validate_grid_image",
            lambda path, grid_size: MagicMock(is_valid=False, reason="not a uniform grid", confidence=0.1),
        )
        grid_model = MagicMock()
        monkeypatch.setattr(git, "GridImageTasksModel", grid_model)
        monkeypatch.setattr(git, "_update_task_status_file", MagicMock())

        found_items = {
            101: {"id": 1001, "extra_json": {"grid_task_id": 77}},
            102: {"id": 1002, "extra_json": {"grid_task_id": 77}},
        }
        updated_items = []
        monkeypatch.setattr(
            "model.storyboard_image_batch.StoryboardImageBatchItemModel.find_running_by_grid_task",
            lambda grid_task_id, scene_id: found_items.get(scene_id),
        )
        monkeypatch.setattr(
            "model.storyboard_image_batch.StoryboardImageBatchItemModel.update",
            lambda item_id, **kwargs: updated_items.append((item_id, kwargs)) or 1,
        )

        task = MagicMock()
        task.id = 77
        task.task_key = "first-frame-grid"
        task.item_type = ItemType.STORYBOARD_FIRST_FRAME_GRID
        task.item_name = "scene#101,102,#,#"
        task.grid_size = 4
        task.max_retries = 2
        task.retry_count = 2
        task.prompt = "{}"
        task.task_config_id = "7"
        task.comfyui_base_url = "http://h"
        task.user_id = "u"
        task.world_id = "w"
        task.auth_token = "t"
        task.project_id = "501"
        task.get_target_entity_ids_list = lambda: [101, 102]

        git._handle_task_success(task, mi.comfyui_status_success("/upload/mock/bad_grid.png"))

        grid_model.reset_for_retry.assert_not_called()
        grid_model.update_status.assert_called_once()
        assert grid_model.update_status.call_args.kwargs["status"] == git.GridImageTaskStatus.FAILED
        assert [item_id for item_id, _ in updated_items] == [1001, 1002]
        assert all(kwargs["status"] == git.StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED for _, kwargs in updated_items)

    def test_grid_mock_splits_even_when_image_download_disabled(self, monkeypatch):
        import importlib
        fake_mcp = MagicMock()
        fake_mcp.update_character_json.return_value = {"success": True}
        monkeypatch.setattr(importlib, "import_module", lambda name: fake_mcp)
        monkeypatch.setattr(git, "get_config", lambda: {
            "image": {"enable_download": False},
            "server": {"host": "http://h"},
        })
        monkeypatch.setattr(git, "_download_and_store_image",
                            lambda url, item_type, base: ("http://h/upload/character/temp/grid.png", "grid.png"))
        splitter = MagicMock()
        splitter.split_grid.return_value = ["a.png", "b.png", "c.png", "d.png"]
        monkeypatch.setattr(git, "ImageGridSplitter", MagicMock(return_value=splitter))
        monkeypatch.setattr(git, "validate_grid_image", lambda path, grid_size: MagicMock(is_valid=True, reason="ok", confidence=1.0))
        grid_model = MagicMock()
        monkeypatch.setattr(git, "GridImageTasksModel", grid_model)
        monkeypatch.setattr(git, "_update_task_status_file", MagicMock())

        task = MagicMock()
        task.task_key = "grid"
        task.item_type = 4
        task.item_name = "a,b,c,d"
        task.grid_size = 4  # 九宫格支持后，grid_size 由 task 携带
        task.comfyui_base_url = "http://h"
        task.user_id = "u"
        task.world_id = "w"
        task.auth_token = "t"
        # get_item_names_list / get_target_entity_ids_list 在 MagicMock 上返回 MagicMock，
        # 覆盖为真实列表，使切图与回写逻辑按预期工作
        task.get_item_names_list = lambda: ["a", "b", "c", "d"]
        task.get_target_entity_ids_list = lambda: []

        git._handle_task_success(task, mi.comfyui_status_success("/upload/mock/e2e_grid_2x2.png"))

        assert fake_mcp.update_character_json.call_count == 4
        grid_model.update_status.assert_called_once()


# ──────────────── §5.7 多角度 _apply_mock_angle 状态机 ────────────────
class TestMultiAngleApplyMock:
    @staticmethod
    def _task(n_angles, current_index=0):
        task = MagicMock()
        task.get_angles_list.return_value = [
            {"angle": a * 90, "angleKey": f"k{a}", "label": f"{a * 90}°"}
            for a in range(n_angles)
        ]
        task.current_angle_index = current_index
        task.get_generated_images_list.return_value = []
        return task

    def _patch(self, monkeypatch, task):
        import task.location_multi_angle_task as lmt
        monkeypatch.setattr(mi, "_img", lambda k: f"/upload/mock/{k}.png")
        loc_model = MagicMock()
        loc_model.get_by_task_key.return_value = task
        monkeypatch.setattr(lmt, "LocationMultiAngleTasksModel", loc_model)
        monkeypatch.setattr(lmt, "_download_and_store_image",
                            lambda url, base: (f"http://h/{url.split('/')[-1]}", f"loc/{url}"))
        monkeypatch.setattr(lmt, "_update_reference_images_to_staging", MagicMock())
        return lmt, loc_model

    def test_middle_angle_advances_index_not_completed(self, mock_enabled, monkeypatch):
        lmt, loc_model = self._patch(monkeypatch, self._task(3, current_index=0))
        lmt._apply_mock_angle("key", "http://h")
        loc_model.update_status.assert_called_once()
        args = loc_model.update_status.call_args.args
        kw = loc_model.update_status.call_args.kwargs
        # update_status(task_key, status, ...) —— status 是位置参数
        assert args[1] == lmt.LocationMultiAngleTaskStatus.PROCESSING
        assert kw["current_angle_index"] == 1
        assert len(kw["generated_images"]) == 1

    def test_last_angle_marks_completed(self, mock_enabled, monkeypatch):
        lmt, loc_model = self._patch(monkeypatch, self._task(2, current_index=1))
        lmt._apply_mock_angle("key", "http://h")
        loc_model.update_status.assert_called_once()
        args = loc_model.update_status.call_args.args
        kw = loc_model.update_status.call_args.kwargs
        assert args[1] == lmt.LocationMultiAngleTaskStatus.COMPLETED
        assert len(kw["generated_images"]) == 1

    def test_process_mock_does_not_require_multi_angle_config(self, mock_enabled, monkeypatch):
        import task.location_multi_angle_task as lmt
        task = self._task(1, current_index=0)
        task.status = lmt.LocationMultiAngleTaskStatus.QUEUED
        task.ai_tool_task_id = 0
        task.location_name = "loc"
        loc_model = MagicMock()
        loc_model.get_by_task_key.return_value = task
        monkeypatch.setattr(lmt, "LocationMultiAngleTasksModel", loc_model)
        monkeypatch.setattr(lmt, "get_config", lambda: {"server": {"host": "http://h"}})
        monkeypatch.setattr(lmt, "_apply_mock_angle", MagicMock())
        import config.unified_config as uc
        monkeypatch.setattr(uc.UnifiedConfigRegistry, "get_by_key", lambda key: None)

        result = lmt.process_location_multi_angle_task("key")

        assert result["success"] is True
        lmt._apply_mock_angle.assert_called_once_with("key", "http://h")


# ──────────────── §5.4 RunningHub 异步 poll（process_runninghub_async_tasks）────────────────
class TestRunninghubPoll:
    def test_mock_task_completes_without_real_check_status(self, mock_enabled, monkeypatch):
        import task.runninghub_async_task as rat
        import model.character as model_character
        from config.unified_config import AsyncTaskImplementationId

        monkeypatch.setattr(mi, "mock_audio", lambda k="tts": "/upload/mock/e2e_char.mp3")

        task = MagicMock()
        task.external_task_id = "mock_task_audio1"   # mock id → 触发短路
        task.id = 7
        task.get_params_dict.return_value = {"character_id": 42}

        async_model = MagicMock()
        async_model.get_pending_tasks.return_value = [task]
        # AsyncTasksModel/RunningHubSlotsModel 在 runninghub_async_task 顶层 import，patch 模块属性
        monkeypatch.setattr(rat, "AsyncTasksModel", async_model)
        monkeypatch.setattr(rat, "RunningHubSlotsModel", MagicMock())
        monkeypatch.setattr(model_character, "CharacterModel", MagicMock())

        # 用 MagicMock driver 类替换 DRIVER_MAP，确保 check_status 是 mock 且可断言"未被调用"
        driver_inst = MagicMock()
        monkeypatch.setattr(rat, "DRIVER_MAP",
                            {AsyncTaskImplementationId.RUNNINGHUB_AUDIO: MagicMock(return_value=driver_inst)})
        monkeypatch.setattr(rat, "SUCCESS_HANDLER_MAP",
                            {AsyncTaskImplementationId.RUNNINGHUB_AUDIO: MagicMock()})
        monkeypatch.setattr(rat, "POST_PROCESSING_REQUIRED", {})

        rat.process_runninghub_async_tasks()

        # 真实轮询 driver.check_status 绝不能被调用
        driver_inst.check_status.assert_not_called()
        # mock 任务直接置 COMPLETED，且跳过 success_handler（不触发 increment_try_count）
        async_model.update_status.assert_called_once()
        assert async_model.update_status.call_args.kwargs["status"] == rat.AsyncTaskStatus.COMPLETED
        assert async_model.update_status.call_args.kwargs["result_url"] == "/upload/mock/e2e_char.mp3"
        async_model.increment_try_count.assert_not_called()


# ──────────────── §5.5 ComfyUI 工具直调（generate_text_to_image）────────────────
class TestMcpToolTextToImage:
    def test_mock_branch_skips_http_and_returns_mock_project_id(self, mock_enabled, monkeypatch):
        import script_writer_core.mcp_tool as mt
        import config.unified_config as uc
        import utils.computing_power as cp

        # 短路前的最小依赖 patch
        monkeypatch.setattr(mt, "_get_text_to_image_task_id", lambda u, w: 1)
        monkeypatch.setattr(mt, "_get_model_name_by_task_id", lambda tid: "mock_model")
        monkeypatch.setattr(mt, "get_config", lambda: {"server": {"host": "http://h"}, "image": {}})
        monkeypatch.setattr(mt, "_get_image_preferences", lambda u, w: {})
        monkeypatch.setattr(uc.UnifiedConfigRegistry, "get_by_id", lambda tid: None)
        monkeypatch.setattr(cp, "get_computing_power_for_task", lambda tid, context=None: 0)
        # httpx 必须不被调用
        monkeypatch.setattr(mt, "httpx", MagicMock())
        # 通用生图（item_type=None）会建 grid_image_tasks 后台记录
        monkeypatch.setattr(model, "GridImageTasksModel", MagicMock())

        result = mt.generate_text_to_image(
            user_id="u", world_id="w", auth_token="t", prompt="a cat", item_type=None
        )

        assert result["success"] is True
        assert result["project_ids"][0].startswith(mi.MOCK_PROJECT_PREFIX)
        mt.httpx.post.assert_not_called()   # 关键：未真实 POST ComfyUI
