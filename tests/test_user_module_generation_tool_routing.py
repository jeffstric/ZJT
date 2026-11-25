from unittest.mock import MagicMock

from tools import user_module_agent_tools
from script_writer_core.agents.expert_agent import ExpertAgent
from script_writer_core.agents.tool_executor import (
    ToolExecutor,
    register_enterprise_tool,
    unregister_enterprise_tool,
)
from script_writer_core.agents.tool_executor import _enterprise_tool_metadata


def test_tool_executor_injects_trusted_generation_model_context():
    executor = ToolExecutor(file_manager=None)
    create_tool = MagicMock(return_value={"generation_id": "generation-1"})
    # 动态注册（商业版注入路径）：受信模型路由由注册元数据声明
    register_enterprise_tool(
        "user_module_generation_create", create_tool, inject_trusted_model=True
    )
    try:
        result = executor.execute_tool(
            tool_name="user_module_generation_create",
            tool_args={
                "module_id": "vendor.demo",
                "requirement": "实现一个异步视频生成接口",
                "model": "forged-model",
                "model_id": 999,
                "vendor_id": 999,
            },
            user_id="7",
            world_id="module-development",
            auth_token="token",
            model="trusted-model",
            model_id=12,
            vendor_id=3,
        )

        assert result == {"generation_id": "generation-1"}
        create_tool.assert_called_once_with(
            "7",
            "module-development",
            "token",
            model="trusted-model",
            model_id=12,
            vendor_id=3,
            module_id="vendor.demo",
            requirement="实现一个异步视频生成接口",
        )
    finally:
        unregister_enterprise_tool("user_module_generation_create")
    assert "user_module_generation_create" not in _enterprise_tool_metadata


def test_expert_agent_forwards_trusted_model_id():
    executor = MagicMock()
    executor.execute_tool.return_value = {"generation_id": "generation-1"}
    agent = object.__new__(ExpertAgent)
    agent.allowed_tools = ["user_module_generation_create", "user_module_project_search"]
    agent.tool_executor = executor
    agent.user_id = "7"
    agent.world_id = "module-development"
    agent.auth_token = "token"
    agent.model = "trusted-model"
    agent.model_id = 12
    agent.vendor_id = 3
    agent.agent_id = "expert_generate-user-api-module"

    agent._execute_tool(
        "user_module_generation_create",
        {"module_id": "vendor.demo", "requirement": "实现一个异步视频生成接口"},
    )
    create_kwargs = executor.execute_tool.call_args.kwargs
    assert create_kwargs["model_id"] == 12

    executor.reset_mock()
    agent._execute_tool("user_module_project_search", {"query": "Driver"})
    search_kwargs = executor.execute_tool.call_args.kwargs
    # 受信模型路由统一透传给 execute_tool；是否消费由工具注册元数据
    # （inject_trusted_model）决定，未声明的工具不会在调用参数里收到这些字段。
    assert search_kwargs["model_id"] == 12


def test_generation_create_tool_persists_injected_review_target(monkeypatch):
    captured = {}

    class FakeGenerationService:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return {"generation_id": "generation-1"}

    monkeypatch.setattr(
        user_module_agent_tools, "_require_user_module_admin", lambda *_args: None
    )
    monkeypatch.setattr(
        user_module_agent_tools,
        "_user_module_generation_service",
        FakeGenerationService,
    )

    result = user_module_agent_tools.user_module_generation_create(
        user_id="7",
        world_id="module-development",
        auth_token="token",
        module_id="vendor.demo",
        requirement="实现一个异步视频生成接口",
        model="trusted-model",
        model_id=12,
        vendor_id=3,
    )

    assert result == {"generation_id": "generation-1"}
    assert captured == {
        "module_id": "vendor.demo",
        "requirement": "实现一个异步视频生成接口",
        "created_by": "7",
        "review_model": "trusted-model",
        "review_model_id": 12,
        "review_vendor_id": 3,
    }
