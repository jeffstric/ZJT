"""_llm_model_context model_id 宽容归一（复合串不再 ValueError）回归测试。"""
import json
from unittest.mock import patch, MagicMock

from services.storyboard_first_frame_grid_service import StoryboardFirstFrameGridService


def _svc():
    return StoryboardFirstFrameGridService.__new__(StoryboardFirstFrameGridService)


def test_normal_dict_preference():
    sb = {"config_json": json.dumps({
        "selectedScriptSplitLlmModel": {"model": "deepseek-v4-flash", "model_id": 5, "vendor_id": 2}})}
    model, model_id, vendor_id = _svc()._llm_model_context(sb)
    assert (model, model_id, vendor_id) == ("deepseek-v4-flash", 5, 2)


def test_legacy_composite_model_id_no_longer_raises():
    """历史存储把 "vendor:模型名" 复合串当 model_id：裸 int() 会 ValueError 500。"""
    sb = {"config_json": json.dumps({
        "selectedScriptSplitLlmModel": {"model": "x", "model_id": "vllm:qwen3.8:27b", "vendor_id": 9}})}
    with patch("model.vendor.VendorDAO.get_by_name", lambda n: MagicMock(id=9, vendor_name=n)), \
         patch("model.model.ModelModel.get_by_name", lambda n: MagicMock(id=1011, model_name=n)), \
         patch("model.vendor_model.VendorModelModel.get_by_vendor_model", lambda v, m: object()):
        model, model_id, vendor_id = _svc()._llm_model_context(sb)
    assert model_id == 1011
    assert vendor_id == 9


def test_unresolvable_model_id_falls_back_to_none():
    sb = {"config_json": json.dumps({
        "selectedScriptSplitLlmModel": {"model": "m", "model_id": "garbage", "vendor_id": 3}})}
    model, model_id, vendor_id = _svc()._llm_model_context(sb)
    assert (model, model_id, vendor_id) == ("m", None, 3)


def test_string_preference_uses_defaults():
    sb = {"config_json": json.dumps({"selectedScriptSplitLlmModel": "deepseek-v4-flash"})}

    class _Constants:
        DEFAULT_SCRIPT_SPLIT_MODEL = "deepseek-v4-flash"

    import services.storyboard_first_frame_grid_service as mod
    original = mod.StoryboardAgentCommandConstants
    mod.StoryboardAgentCommandConstants = _Constants
    try:
        model, model_id, vendor_id = _svc()._llm_model_context(sb)
    finally:
        mod.StoryboardAgentCommandConstants = original
    assert model == "deepseek-v4-flash"
    assert model_id is None and vendor_id is None
