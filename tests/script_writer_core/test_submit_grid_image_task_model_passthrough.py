"""submit_grid_image_task 生图模型显式透传防回归测试。

线上事故背景：storyboard 拆分界面选择 GPT Image 2（task_id=26），quality 模式
首帧宫格链路未透传模型，静默回退默认 nano-banana-Pro（task_id=7）生图。
本组测试锁定三层防线：
1. 显式 task_type 必须原样用于请求、任务记录与返回值；
2. 显式 task_type 不兼容 image_edit 时明确报错（禁止静默换模型）；
3. 未显式指定时回退偏好/默认解析，必须打 warning 让隐式解析点现形。
"""
import logging
from types import SimpleNamespace

import pytest

import model as model_package
import model.ai_tool_pipeline_steps as pipeline_steps_module
import task.mock_interceptor as mock_interceptor_module
from script_writer_core import mcp_tool
from script_writer_core.constant import ItemType

# 34 = MiniMax H3（视频模型），不属于 IMAGE_EDIT 类别，用于校验拒绝路径
_NON_IMAGE_EDIT_TASK_ID = 34
_GPT_IMAGE_2_TASK_ID = 26
_DEFAULT_TEXT_TO_IMAGE_TASK_ID = 7


@pytest.fixture()
def grid_submit_env(monkeypatch):
    """为 submit_grid_image_task(i2i) 提供最小外部依赖 stub（http/DB/model 全部隔离）。"""
    monkeypatch.setattr(
        mcp_tool, "get_config", lambda: {"server": {"host": "http://grid.test"}}
    )

    http_calls = []

    class FakeResponse:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"project_ids": ["pid-1"]}

    def fake_post(url, data=None, **kwargs):
        http_calls.append((url, dict(data or {})))
        return FakeResponse()

    monkeypatch.setattr(mcp_tool.httpx, "post", fake_post)

    grid_created = []

    class FakeGridImageTasksModel:
        @staticmethod
        def get_by_task_key(task_key):
            return None

        @staticmethod
        def create(**kwargs):
            grid_created.append(kwargs)
            return 901

    class FakePipelineStepModel:
        @staticmethod
        def create(**kwargs):
            return 902

    monkeypatch.setattr(model_package, "GridImageTasksModel", FakeGridImageTasksModel)
    monkeypatch.setattr(pipeline_steps_module, "PipelineStepModel", FakePipelineStepModel)
    monkeypatch.setattr(mock_interceptor_module, "is_mock_enabled", lambda: False)

    # 隔离全局注册的偏好 getter，避免真实读取数据库偏好
    monkeypatch.setattr(mcp_tool, "_get_text_to_image_model_id_func", None)

    return SimpleNamespace(http_calls=http_calls, grid_created=grid_created)


def _base_kwargs():
    return dict(
        user_id="7",
        world_id="99",
        auth_token="token",
        item_names=["分镜1", "分镜2", "placeholder", "placeholder"],
        prompts=["p1", "p2", "", ""],
        item_type=ItemType.STORYBOARD_FIRST_FRAME_GRID,
        grid_size=4,
        mode="image_edit",
        reference_images=[{"url": "https://cdn.test/ref.png", "role_description": "场景：A"}],
        target_entity_ids=[301, 302, None, None],
    )


def test_explicit_task_type_used_in_request_and_record(grid_submit_env):
    result = mcp_tool.submit_grid_image_task(**_base_kwargs(), task_type=_GPT_IMAGE_2_TASK_ID)

    assert result["success"] is True
    assert grid_submit_env.http_calls, "应发起宫格 i2i 请求"
    _url, request_data = grid_submit_env.http_calls[0]
    assert request_data["task_id"] == _GPT_IMAGE_2_TASK_ID
    assert result["model_task_id"] == _GPT_IMAGE_2_TASK_ID
    assert grid_submit_env.grid_created[0]["task_config_id"] == str(_GPT_IMAGE_2_TASK_ID)


def test_explicit_task_type_rejects_non_image_edit_model(grid_submit_env):
    result = mcp_tool.submit_grid_image_task(**_base_kwargs(), task_type=_NON_IMAGE_EDIT_TASK_ID)

    assert result["success"] is False
    assert "不支持图片编辑" in result["error"]
    assert str(_NON_IMAGE_EDIT_TASK_ID) in result["error"]
    assert grid_submit_env.http_calls == [], "模型校验失败不应发起请求"
    assert grid_submit_env.grid_created == [], "模型校验失败不应创建任务记录"


def test_missing_task_type_falls_back_with_warning(grid_submit_env, caplog):
    with caplog.at_level(logging.WARNING):
        result = mcp_tool.submit_grid_image_task(**_base_kwargs())

    assert result["success"] is True
    assert result["model_task_id"] == _DEFAULT_TEXT_TO_IMAGE_TASK_ID
    warnings = [
        rec for rec in caplog.records
        if "未显式指定生图模型" in rec.getMessage()
    ]
    assert warnings, "隐式回退偏好/默认模型必须打 warning 现形"
