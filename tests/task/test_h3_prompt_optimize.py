"""MiniMax H3 提示词优化：变体判定、模板组装、结构校验与 extra_config 合并。"""
from types import SimpleNamespace

from config.constant import (
    H3_PROMPT_OPTIMIZE_VARIANT_FL2VA,
    H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
)
from task.pipeline_drivers.h3_prompt_optimize_util import (
    build_h3_optimize_user_message,
    load_h3_prompt_template,
    merge_h3_prompt_extra_config,
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
