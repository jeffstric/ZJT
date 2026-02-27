import logging
from typing import Dict, Any, List
from script_writer_core.file_manager import FileManager
from script_writer_core.mcp_tool import (
    MCP_TOOLS,
    read_world,
    update_world,
    read_script_json,
    list_script_jsons,
    read_character_json,
    list_character_jsons,
    read_location_json,
    list_location_jsons,
    read_prop_json,
    list_prop_jsons,
    get_script_problem,
    set_script_problem,
    create_character_json,
    create_script_json,
    create_location_json,
    create_prop_json,
    update_character_json,
    update_script_json,
    update_location_json,
    update_prop_json,
    get_long_user_input,
    generate_text_to_image,
    generate_4grid_character_images,
    generate_4grid_location_images,
    generate_4grid_prop_images,
    get_task_status
)

logger = logging.getLogger(__name__)


class ToolExecutor:
    """工具执行器 - 统一管理所有工具的执行"""
    
    def __init__(self, file_manager: FileManager):
        self.file_manager = file_manager
        
        self.tool_map = {
            # MCP 工具函数（直接调用）
            "read_world": read_world,
            "update_world": update_world,
            "read_script_json": read_script_json,
            "list_script_jsons": list_script_jsons,
            "read_character_json": read_character_json,
            "list_character_jsons": list_character_jsons,
            "read_location_json": read_location_json,
            "list_location_jsons": list_location_jsons,
            "read_prop_json": read_prop_json,
            "list_prop_jsons": list_prop_jsons,
            "get_script_problem": get_script_problem,
            "set_script_problem": set_script_problem,
            "create_character_json": create_character_json,
            "create_script_json": create_script_json,
            "create_location_json": create_location_json,
            "create_prop_json": create_prop_json,
            "update_character_json": update_character_json,
            "update_script_json": update_script_json,
            "update_location_json": update_location_json,
            "update_prop_json": update_prop_json,
            "get_long_user_input": get_long_user_input,
            "generate_text_to_image": generate_text_to_image,
            "generate_4grid_character_images": generate_4grid_character_images,
            "generate_4grid_location_images": generate_4grid_location_images,
            "generate_4grid_prop_images": generate_4grid_prop_images,
            "get_task_status": get_task_status,
        }
    
    def execute_tool(
        self, 
        tool_name: str, 
        tool_args: Dict[str, Any],
        user_id: str,
        world_id: str,
        auth_token: str
    ) -> Dict[str, Any]:
        """执行工具"""
        # 调试日志：记录接收到的工具名称和参数
        logger.info(f"Requesting execution for tool: '{tool_name}' (repr: {repr(tool_name)})")

        # 检查工具是否存在
        if tool_name not in self.tool_map:
            return {"error": f"未知工具: {tool_name}"}
        
        try:
            # MCP 工具现在需要 user_id, world_id, auth_token 作为前三个参数
            mcp_tool_names = [
                "read_world", "update_world", "read_script_json", "list_script_jsons",
                "read_character_json", "list_character_jsons", "read_location_json",
                "list_location_jsons", "read_prop_json", "list_prop_jsons",
                "get_script_problem", "set_script_problem", "create_character_json",
                "create_script_json", "create_location_json", "create_prop_json",
                "update_character_json", "update_script_json", "update_location_json",
                "update_prop_json", "get_long_user_input", "generate_text_to_image",
                "generate_4grid_character_images", "generate_4grid_location_images",
                "generate_4grid_prop_images", "get_task_status"
            ]
            
            if tool_name in mcp_tool_names:
                # MCP 工具：将 user_id, world_id, auth_token 作为前三个参数传递
                result = self.tool_map[tool_name](user_id, world_id, auth_token, **tool_args)
            else:
                # 兼容旧逻辑，但理论上现在应该都走上面
                tool_args["user_id"] = user_id
                tool_args["world_id"] = world_id
                result = self.tool_map[tool_name](**tool_args)
            
            return result
        except Exception as e:
            logger.error(f"Tool {tool_name} execution failed: {e}", exc_info=True)
            return {"error": str(e)}
    
    def get_tool_definitions(self, allowed_tools: List[str]) -> List[Dict[str, Any]]:
        """获取工具定义"""
        all_tools = self._get_all_tool_definitions()
        return [tool for tool in all_tools if tool["function"]["name"] in allowed_tools]
    
    def _convert_mcp_tools_to_gemini_format(self) -> List[Dict[str, Any]]:
        """将 MCP 工具定义转换为 Gemini API 格式"""
        gemini_tools = []
        for mcp_tool in MCP_TOOLS:
            gemini_tool = {
                "type": "function",
                "function": {
                    "name": mcp_tool["name"],
                    "description": mcp_tool["description"],
                    "parameters": mcp_tool["inputSchema"]
                }
            }
            gemini_tools.append(gemini_tool)
        return gemini_tools

    def _get_all_tool_definitions(self) -> List[Dict[str, Any]]:
        """获取所有工具定义（从 MCP_TOOLS 转换）"""
        # 直接返回 MCP 工具定义
        return self._convert_mcp_tools_to_gemini_format()
