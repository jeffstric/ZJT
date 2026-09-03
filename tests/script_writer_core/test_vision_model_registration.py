"""deepseek-v4-flash-vision-exp 模型接入单元测试。

覆盖：
- 常量与 DeepSeek 客户端模型映射
- ModelModel.get_by_name 的空值与查询行为
- MCP_TOOLS / ToolExecutor 注册 delete_asset_reference_image
"""
from unittest.mock import MagicMock, patch


def test_vision_model_constant_consistency():
    from config.constant import LLMModel, VL_MODEL_PREFERRED_DEFAULT
    assert LLMModel.DEEPSEEK_V4_FLASH_VISION_EXP == "deepseek-v4-flash-vision-exp"
    # VL 偏好默认值与 LLMModel 常量同值（constant 内注释以字面量避免前向引用）
    assert VL_MODEL_PREFERRED_DEFAULT == LLMModel.DEEPSEEK_V4_FLASH_VISION_EXP


def test_deepseek_client_maps_vision_model():
    from llm.openai_deepseek import DeepSeekOpenAIClient
    assert DeepSeekOpenAIClient._MODEL_NAME_MAP["deepseek-v4-flash-vision-exp"] \
        == "deepseek-v4-flash-vision-exp"


def test_model_get_by_name_returns_none_for_empty():
    from model.model import ModelModel
    assert ModelModel.get_by_name("") is None
    assert ModelModel.get_by_name(None) is None


def test_model_get_by_name_queries_enabled_exact_match():
    from model.model import ModelModel
    with patch("model.model.execute_query") as mock_query:
        row = {
            "id": 9, "model_name": "deepseek-v4-flash-vision-exp",
            "context_window": 1000000, "supports_tools": 1,
            "max_output_tokens": 384000, "supports_thinking": 1,
            "supports_vl": 1, "enabled": 1, "created_at": None, "note": "",
        }
        mock_query.return_value = row
        result = ModelModel.get_by_name("deepseek-v4-flash-vision-exp")
    assert result is not None
    assert result.id == 9
    sql, params = mock_query.call_args[0]
    assert "model_name = %s" in sql
    assert "enabled = 1" in sql
    assert params == ("deepseek-v4-flash-vision-exp",)


def test_mcp_tools_registry_contains_delete_asset_reference_image():
    from script_writer_core.mcp_tool import MCP_TOOLS
    entry = next(
        (t for t in MCP_TOOLS if t["name"] == "delete_asset_reference_image"), None
    )
    assert entry is not None
    assert set(entry["inputSchema"]["required"]) == {"asset_type", "name"}
    assert "reason" in entry["inputSchema"]["properties"]


def test_tool_executor_registers_delete_asset_reference_image():
    from script_writer_core.agents.tool_executor import ToolExecutor
    from script_writer_core.mcp_tool import delete_asset_reference_image
    executor = ToolExecutor.__new__(ToolExecutor)
    # 构造最小 tool_map（复刻 __init__ 的映射来源）
    tool_map = ToolExecutor._build_tool_map(executor) if hasattr(
        ToolExecutor, "_build_tool_map"
    ) else None
    if tool_map is None:
        # 无独立构建方法时直接验证模块导入链中的注册表
        import script_writer_core.agents.tool_executor as te
        assert te.delete_asset_reference_image is delete_asset_reference_image
    else:
        assert tool_map["delete_asset_reference_image"] is delete_asset_reference_image
