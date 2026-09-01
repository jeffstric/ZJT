from script_writer_core.agents.tool_executor import (
    ToolExecutor,
    register_enterprise_tool,
    unregister_enterprise_tool,
)


def test_existing_executor_observes_enterprise_tool_replace_and_unregister():
    tool_name = "test_dynamic_enterprise_tool"

    def first_tool(user_id, world_id, auth_token):
        return {"implementation": "first"}

    def second_tool(user_id, world_id, auth_token):
        return {"implementation": "second"}

    register_enterprise_tool(tool_name, first_tool)
    executor = ToolExecutor(file_manager=None)
    try:
        assert executor.execute_tool(tool_name, {}, "7", "world", "token") == {
            "implementation": "first"
        }

        register_enterprise_tool(tool_name, second_tool)
        assert executor.execute_tool(tool_name, {}, "7", "world", "token") == {
            "implementation": "second"
        }

        unregister_enterprise_tool(tool_name)
        assert executor.execute_tool(tool_name, {}, "7", "world", "token") == {
            "error": f"未知工具: {tool_name}"
        }
    finally:
        unregister_enterprise_tool(tool_name)
