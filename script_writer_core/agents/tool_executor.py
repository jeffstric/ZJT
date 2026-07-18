import logging
from typing import Dict, Any, List, Callable, Optional
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
    generate_character_variant_image,
    get_task_status,
    check_image_status,
    edit_image,
    get_text_to_image_model_info,
    get_user_computing_power,
    list_video_models,
    list_llm_models,
    fetch_image_as_base64,
    generate_reference_audio,
    generate_character_reference_audio,
    check_reference_audio_status,
    generate_digital_human,
)

logger = logging.getLogger(__name__)

# 企业版动态注册的工具函数（在 enterprise 模块加载时注入）
_enterprise_tool_functions: Dict[str, Callable] = {}


def register_enterprise_tool(name: str, func: Callable):
    """注册企业版工具函数（由 enterprise 模块调用）"""
    _enterprise_tool_functions[name] = func
    logger.info(f"已注册企业版工具: {name}")


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
            "generate_character_variant_image": generate_character_variant_image,
            "get_task_status": get_task_status,
            "check_image_status": check_image_status,
            "edit_image": edit_image,
            "get_text_to_image_model_info": get_text_to_image_model_info,
            "get_user_computing_power": get_user_computing_power,
            "list_video_models": list_video_models,
            "list_llm_models": list_llm_models,
            "fetch_image_as_base64": fetch_image_as_base64,
            "generate_reference_audio": generate_reference_audio,
            "generate_character_reference_audio": generate_character_reference_audio,
            "check_reference_audio_status": check_reference_audio_status,
            "generate_digital_human": generate_digital_human,
        }

        # 注入企业版工具函数
        self.tool_map.update(_enterprise_tool_functions)
    
    def execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        user_id: str,
        world_id: str,
        auth_token: str,
        language: str = "zh-CN",
        model: Optional[str] = None,
        vendor_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """执行工具"""
        # 调试日志：记录接收到的工具名称和参数
        logger.info(f"Requesting execution for tool: '{tool_name}' (repr: {repr(tool_name)})")

        # 检查工具是否存在（优先本地 tool_map，再查企业版动态注册表）
        tool_func = self.tool_map.get(tool_name) or _enterprise_tool_functions.get(tool_name)
        if not tool_func:
            return {"error": f"未知工具: {tool_name}"}

        try:
            # ⚠️ 双重注册维护：mcp_tool_names 列表必须与 tool_map 保持同步
            # mcp_tool_names 中的工具会自动注入 user_id/world_id/auth_token 前三个参数
            # 新增 MCP 工具时，必须同时更新 tool_map 和 mcp_tool_names 两处
            mcp_tool_names = [
                "read_world", "update_world", "read_script_json", "list_script_jsons",
                "read_character_json", "list_character_jsons", "read_location_json",
                "list_location_jsons", "read_prop_json", "list_prop_jsons",
                "get_script_problem", "set_script_problem", "create_character_json",
                "create_script_json", "create_location_json", "create_prop_json",
                "update_character_json", "update_script_json", "update_location_json",
                "update_prop_json", "get_long_user_input", "generate_text_to_image",
                "generate_4grid_character_images", "generate_4grid_location_images",
                "generate_4grid_prop_images", "generate_character_variant_image",
                "get_task_status", "check_image_status",
                "edit_image", "get_text_to_image_model_info", "get_user_computing_power",
                "list_video_models", "list_llm_models",
                "generate_text_to_video", "image_to_video",
                "fetch_image_as_base64",
                "generate_reference_audio",
                "generate_character_reference_audio", "check_reference_audio_status",
                "generate_digital_human"
            ]

            # 需要传递 language 参数的创建工具（update 函数不调用 validate_name_for_filename，不需要此参数）
            language_aware_tools = [
                "create_character_json", "create_script_json",
                "create_location_json", "create_prop_json"
            ]

            # 需要传递 model/vendor_id 参数的工具（内部调用 LLM 时需要使用用户选择的模型）
            model_aware_tools = [
                "generate_character_reference_audio"
            ]

            if tool_name in mcp_tool_names:
                # MCP 工具：将 user_id, world_id, auth_token 作为前三个参数传递
                extra_kwargs = {}
                if tool_name in language_aware_tools:
                    extra_kwargs['language'] = language
                if tool_name in model_aware_tools:
                    extra_kwargs['model'] = model
                    extra_kwargs['vendor_id'] = vendor_id
                result = tool_func(user_id, world_id, auth_token, **extra_kwargs, **tool_args)
            else:
                # 兼容旧逻辑，但理论上现在应该都走上面
                tool_args["user_id"] = user_id
                tool_args["world_id"] = world_id
                result = tool_func(**tool_args)

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
