from unittest.mock import MagicMock

from script_writer_core.agents.pm_agent import PMAgent


def _create_script_pm_agent():
    file_manager = MagicMock()
    file_manager.get_context_for_ai.return_value = ""
    return PMAgent(
        model="test-model",
        allowed_tools=["call_agent"],
        task_manager=MagicMock(),
        file_manager=file_manager,
        tool_executor=MagicMock(),
        agents_config={
            "pm_agent": {
                "skills": [],
                "allowed_expert_types": ["script"],
            },
            "expert_agents": {
                "story-writer": {
                    "expert_type": "script",
                    "skills": [],
                    "allowed_tools": [],
                    "model": "test-model",
                },
                "marketing-video": {
                    "expert_type": "marketing",
                    "skills": [],
                    "allowed_tools": [],
                    "model": "test-model",
                },
            },
        },
        user_id="1",
        world_id="1",
        auth_token="token",
        base_prompt="test prompt",
        skip_env_context=True,
    )


def test_script_pm_call_agent_schema_only_includes_script_experts():
    agent = _create_script_pm_agent()

    tool_defs = agent._get_tool_definitions()
    call_agent = next(tool for tool in tool_defs if tool["function"]["name"] == "call_agent")
    enum_values = call_agent["function"]["parameters"]["properties"]["AgentName"]["enum"]

    assert enum_values == ["story-writer"]


def test_admin_expert_is_hidden_from_non_admin_and_visible_to_admin():
    agent = _create_script_pm_agent()
    agent.allowed_expert_types = ["script", "admin"]
    agent.agents_config["expert_agents"]["generate-user-api-module"] = {
        "expert_type": "admin",
        "skills": ["generate-user-api-module"],
        "allowed_tools": ["user_module_generation_create"],
        "model": "test-model",
    }
    agent._admin_user_cache = False
    assert agent._get_allowed_expert_names() == ["story-writer"]
    assert agent._is_expert_allowed("generate-user-api-module") is False

    agent._admin_user_cache = True
    assert agent._get_allowed_expert_names() == [
        "generate-user-api-module",
        "story-writer",
    ]
    assert agent._is_expert_allowed("generate-user-api-module") is True
