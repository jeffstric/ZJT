"""MiniMax H3 提示词优化：变体判定、模板组装、结构校验与 extra_config 合并。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from config.constant import (
    H3_PROMPT_OPTIMIZE_VARIANT_FL2VA,
    H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
)
from task.pipeline_drivers.h3_prompt_optimize_driver import H3PromptOptimizePipelineDriver
from task.pipeline_drivers.h3_prompt_optimize_util import (
    build_h3_optimize_user_message,
    load_h3_prompt_template,
    merge_h3_prompt_extra_config,
    parse_storyboard_dialogue_model,
    resolve_h3_prompt_variant,
    validate_h3_optimized_prompt,
)


def test_first_frame_only_is_i2va():
    tool = SimpleNamespace(image_path="/a.png", reference_images=None, extra_config=None)
    assert resolve_h3_prompt_variant(tool) == H3_PROMPT_OPTIMIZE_VARIANT_I2VA


def test_first_and_last_frame_is_fl2va():
    tool = SimpleNamespace(image_path="/a.png,/b.png", reference_images=None, extra_config=None)
    assert resolve_h3_prompt_variant(tool) == H3_PROMPT_OPTIMIZE_VARIANT_FL2VA


def test_no_image_returns_none():
    tool = SimpleNamespace(image_path="", reference_images=None, extra_config=None)
    assert resolve_h3_prompt_variant(tool) is None


def test_user_message_keeps_original_and_guide():
    original = "镜头缓推，女主转头微笑"
    message = build_h3_optimize_user_message(
        original,
        H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
        5,
        template="GUIDE_BODY",
    )
    assert "GUIDE_BODY" in message
    assert "首帧图" in message
    assert original in message
    assert "I2VA" in load_h3_prompt_template()
    assert "FL2VA" in load_h3_prompt_template()
    assert "T2VA" not in load_h3_prompt_template() or "Do not invent T2VA" in load_h3_prompt_template()


def test_fl2va_message_includes_duration():
    message = build_h3_optimize_user_message(
        "walk forward",
        H3_PROMPT_OPTIMIZE_VARIANT_FL2VA,
        8,
        template="GUIDE",
    )
    assert "8.00" in message
    assert "尾帧图" in message


def test_validate_i2va_and_fl2va():
    i2va = (
        "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
        "integrated_multimodal_description: [Shot 1] hello\n\n"
        "overall_soundscape: rain\n\n"
        "non_diegetic_music: N/A"
    )
    fl2va = (
        "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video.\n\n"
        "integrated_multimodal_description: [Shot 1] hello\n\n"
        "overall_soundscape: rain\n\n"
        "non_diegetic_music: N/A"
    )
    assert validate_h3_optimized_prompt(i2va, H3_PROMPT_OPTIMIZE_VARIANT_I2VA)
    assert not validate_h3_optimized_prompt(i2va, H3_PROMPT_OPTIMIZE_VARIANT_FL2VA)
    assert validate_h3_optimized_prompt(fl2va, H3_PROMPT_OPTIMIZE_VARIANT_FL2VA)
    assert not validate_h3_optimized_prompt("just a shot", H3_PROMPT_OPTIMIZE_VARIANT_I2VA)


def test_merge_extra_config_keeps_first_original():
    first = merge_h3_prompt_extra_config(
        {"resolution": "720P"},
        original_prompt="old",
        optimized_prompt="new",
        variant="I2VA",
        fallback=False,
    )
    second = merge_h3_prompt_extra_config(
        first,
        original_prompt="changed",
        optimized_prompt="newer",
        variant="I2VA",
        fallback=True,
    )
    import json
    data = json.loads(second)
    assert data["original_prompt"] == "old"
    assert data["h3_prompt_optimize"]["optimized_prompt"] == "newer"
    assert data["h3_prompt_optimize"]["fallback"] is True
    assert data["resolution"] == "720P"


def test_parse_storyboard_dialogue_model_object():
    cfg = json.dumps({'selectedLlmModel': {'model': 'qwen-plus', 'vendor_id': 5}})
    assert parse_storyboard_dialogue_model(cfg) == ('qwen-plus', 5)


def test_parse_storyboard_dialogue_model_string():
    cfg = json.dumps({'selectedLlmModel': 'gemini-3-flash-preview'})
    assert parse_storyboard_dialogue_model(cfg) == ('gemini-3-flash-preview', None)


def test_parse_storyboard_dialogue_model_missing():
    assert parse_storyboard_dialogue_model(None) is None
    assert parse_storyboard_dialogue_model('{}') is None


@patch('llm.llm_client_factory.is_llm_client_configured', return_value=True)
@patch('llm.llm_client_factory.get_llm_client')
@patch('config.config_util.get_dynamic_config_value')
def test_resolve_prefers_chat_model(mock_config, mock_get_client, mock_configured):
    """优先使用 step.params 的对话模型（storyboard 用户个性化选择）"""
    mock_config.return_value = 'deepseek-v4-flash'
    model, vendor_id = H3PromptOptimizePipelineDriver.resolve_h3_optimize_model(
        {'chat_model': 'qwen-plus', 'chat_vendor_id': 5}
    )
    assert model == 'qwen-plus'
    assert vendor_id == 5
    mock_get_client.assert_called_once_with('qwen-plus', vendor_id=5)


@patch('llm.llm_client_factory.is_llm_client_configured', side_effect=[False, True])
@patch('llm.llm_client_factory.get_llm_client')
@patch('config.config_util.get_dynamic_config_value')
def test_resolve_falls_back_to_pipeline_config(mock_config, mock_get_client, mock_configured):
    """对话模型未配置密钥 → 回退 pipeline 全局配置模型"""
    mock_config.return_value = 'deepseek-v4-flash'
    model, vendor_id = H3PromptOptimizePipelineDriver.resolve_h3_optimize_model(
        {'chat_model': 'qwen-plus', 'chat_vendor_id': 5}
    )
    assert model == 'deepseek-v4-flash'


@patch('llm.llm_client_factory.is_llm_client_configured', return_value=False)
@patch('llm.llm_client_factory.get_llm_client')
@patch('config.config_util.get_dynamic_config_value')
def test_resolve_returns_none_when_all_unconfigured(mock_config, mock_get_client, mock_configured):
    """所有候选模型均未配置密钥 → 返回 (None, None)，驱动将回退原文不做空跑"""
    mock_config.return_value = 'deepseek-v4-flash'
    model, vendor_id = H3PromptOptimizePipelineDriver.resolve_h3_optimize_model(
        {'chat_model': 'qwen-plus', 'chat_vendor_id': 5}
    )
    assert model is None
    assert vendor_id is None
