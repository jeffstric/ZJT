import json
from pathlib import Path

from script_writer_core.agents.tool_executor import ToolExecutor
from script_writer_core.mcp_tool import MCP_TOOLS


def _load_agents_config() -> dict:
    config_path = Path("script_writer_core/config/agents_config.json")
    return json.loads(config_path.read_text(encoding="utf-8"))


def test_novel_episode_splitter_can_update_script():
    """剧本拆分智能体必须具备编辑剧本权限（覆盖新版本场景）。"""
    config = _load_agents_config()
    allowed_tools = config["expert_agents"]["novel-episode-splitter"]["allowed_tools"]

    assert "update_script_json" in allowed_tools
    assert "create_script_json" in allowed_tools


def test_all_configured_agent_tools_exist_in_mcp_registry():
    """所有智能体 allowed_tools 中的工具必须已注册，否则 LLM 调用会被
    expert_agent 以"工具不在允许列表中"/"未知工具"拒绝（权限配置漂移防护）。"""
    registered_names = {tool["name"] for tool in MCP_TOOLS}
    # 智能体内置能力（非 MCP 注册表工具）：ask_user 由 ExpertAgent 特判处理，
    # call_agent/load_sop 由 PmAgent 特判处理
    builtin_tool_names = {"ask_user", "call_agent", "load_sop"}

    config = _load_agents_config()
    agent_entries = dict(config["expert_agents"])
    agent_entries["pm_agent"] = config["pm_agent"]

    # 仅校验使用静态 MCP 工具的智能体；marketing/admin 类工具由企业版
    # 运行期动态注册（register_enterprise_tool），静态注册表中查不到
    static_agents = {
        name: cfg
        for name, cfg in agent_entries.items()
        if cfg.get("expert_type") == "script" or name == "pm_agent"
    }

    for agent_name, agent_config in static_agents.items():
        allowed_tools = agent_config.get("allowed_tools") or []
        unknown = [
            t
            for t in allowed_tools
            if t not in registered_names and t not in builtin_tool_names
        ]
        assert not unknown, (
            f"智能体 {agent_name} 的 allowed_tools 包含未注册工具: {unknown}"
        )


def test_configured_agent_tools_are_visible_to_llm():
    """allowed_tools 中的工具必须能出现在下发给 LLM 的工具定义里。"""
    executor = ToolExecutor(file_manager=None)

    config = _load_agents_config()
    splitter_tools = config["expert_agents"]["novel-episode-splitter"]["allowed_tools"]

    names = {
        tool["function"]["name"]
        for tool in executor.get_tool_definitions(splitter_tools)
    }
    assert "update_script_json" in names
