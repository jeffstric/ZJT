"""GPT Image 2.6 新建模型驱动（多米 / 通用站点 site_0，sunburst / flare 各一个模型）测试。

与 2.5 同构：两个独立任务类型（55 / 56），各挂 7 个实现方（多米默认 + site_0~5），
算力与 2.5 相同（2 点），仅上游模型名升级为 2.6。
"""
import base64
import json
import logging
import os
from types import SimpleNamespace

os.environ.setdefault("comfyui_env", "prod")

from config.unified_config import (
    DriverImplementationId,
    IMPLEMENTATION_TO_ID,
    UnifiedConfigRegistry,
    TaskTypeId,
)
from task.visual_drivers.gpt_image_2_6_duomi_v1_driver import (
    GptImage26DuomiFlareV1Driver,
    GptImage26DuomiSunburstV1Driver,
)
from task.visual_drivers.gpt_image_common_v1_driver import (
    GptImage26CommonFlareSite0V1Driver,
    GptImage26CommonFlareV1Driver,
    GptImage26CommonSunburstSite0V1Driver,
    GptImage26CommonSunburstV1Driver,
)
from task.visual_drivers.gpt_image_duomi_v1_driver import GptImageDuomiV1Driver


def _make_duomi_driver(cls):
    driver = cls.__new__(cls)
    driver._base_url = "https://duomi.example.com"
    driver._token = "test-token"
    driver.logger = logging.getLogger("test_gpt_image_2_6_duomi")
    driver._timeout = 30
    driver._send_alert = lambda **kwargs: None
    return driver


def _make_common_driver(cls):
    driver = cls.__new__(cls)
    driver._base_url = "https://common.example.com"
    driver._api_key = "test-key"
    driver.logger = logging.getLogger("test_gpt_image_2_6_common")
    return driver


def test_sunburst_and_flare_are_two_independent_models():
    """sunburst / flare 为两个独立任务类型（55 / 56），各自挂图片编辑 + 文生图类目。"""
    assert GptImage26DuomiSunburstV1Driver.DEFAULT_MODEL == "gpt-image-2.6-sunburst"
    assert GptImage26DuomiFlareV1Driver.DEFAULT_MODEL == "gpt-image-2.6-flare"

    sunburst_cfg = UnifiedConfigRegistry.get_by_id(TaskTypeId.GPT_IMAGE_2_6_SUNBURST)
    flare_cfg = UnifiedConfigRegistry.get_by_id(TaskTypeId.GPT_IMAGE_2_6_FLARE)

    assert sunburst_cfg.key == 'gpt-image-2.6-sunburst-edit'
    assert sunburst_cfg.short_key == 'gpt-image-2.6-sunburst'
    assert sunburst_cfg.model_name == 'GPT Image 2.6 Sunburst'
    assert sunburst_cfg.driver_name == 'gpt_image_2_6_sunburst'
    assert flare_cfg.key == 'gpt-image-2.6-flare-edit'
    assert flare_cfg.short_key == 'gpt-image-2.6-flare'
    assert flare_cfg.model_name == 'GPT Image 2.6 Flare'
    assert flare_cfg.driver_name == 'gpt_image_2_6_flare'

    for cfg in (sunburst_cfg, flare_cfg):
        assert cfg.category == 'image_edit'
        assert 'text_to_image' in cfg.categories
        assert cfg.computing_power == 2


def test_each_model_has_seven_implementations_with_duomi_default():
    """每个模型 7 个实现方：多米（默认）+ 聚合站点 site_0~site_5。"""
    sunburst_cfg = UnifiedConfigRegistry.get_by_id(TaskTypeId.GPT_IMAGE_2_6_SUNBURST)
    flare_cfg = UnifiedConfigRegistry.get_by_id(TaskTypeId.GPT_IMAGE_2_6_FLARE)

    assert sunburst_cfg.implementation == 'duomi_gpt_image_2_6_sunburst_v1'
    assert sunburst_cfg.implementations == [
        'duomi_gpt_image_2_6_sunburst_v1',
        'gpt_image_2_6_common_sunburst_site0_v1',
        'gpt_image_2_6_common_sunburst_site1_v1',
        'gpt_image_2_6_common_sunburst_site2_v1',
        'gpt_image_2_6_common_sunburst_site3_v1',
        'gpt_image_2_6_common_sunburst_site4_v1',
        'gpt_image_2_6_common_sunburst_site5_v1',
    ]
    assert flare_cfg.implementation == 'duomi_gpt_image_2_6_flare_v1'
    assert flare_cfg.implementations == [
        'duomi_gpt_image_2_6_flare_v1',
        'gpt_image_2_6_common_flare_site0_v1',
        'gpt_image_2_6_common_flare_site1_v1',
        'gpt_image_2_6_common_flare_site2_v1',
        'gpt_image_2_6_common_flare_site3_v1',
        'gpt_image_2_6_common_flare_site4_v1',
        'gpt_image_2_6_common_flare_site5_v1',
    ]


def test_duomi_create_request_carries_model_name():
    """多米驱动文生图请求体使用对应模型名，其余结构与 GPT Image 2 / 2.5 一致。"""
    assert issubclass(GptImage26DuomiSunburstV1Driver, GptImageDuomiV1Driver)
    ai_tool = SimpleNamespace(id=1, prompt="a cat", image_path="", ratio="16:9", image_size="2k")

    request = _make_duomi_driver(GptImage26DuomiSunburstV1Driver).build_create_request(ai_tool)
    assert request["url"] == "https://duomi.example.com/v1/images/generations?async=true"
    assert request["json"]["model"] == "gpt-image-2.6-sunburst"
    assert request["json"]["size"] == "2048x1152"

    flare_request = _make_duomi_driver(GptImage26DuomiFlareV1Driver).build_create_request(ai_tool)
    assert flare_request["json"]["model"] == "gpt-image-2.6-flare"


def test_common_site_driver_uses_model_names():
    """通用站点 sunburst/flare 驱动文生图请求使用对应模型名。"""
    assert issubclass(GptImage26CommonSunburstSite0V1Driver, GptImage26CommonSunburstV1Driver)
    assert GptImage26CommonSunburstV1Driver.DEFAULT_MODEL == "gpt-image-2.6-sunburst"
    assert GptImage26CommonSunburstV1Driver.EDIT_MODEL == "gpt-image-2.6-sunburst"
    assert GptImage26CommonFlareV1Driver.DEFAULT_MODEL == "gpt-image-2.6-flare"
    assert GptImage26CommonFlareV1Driver.EDIT_MODEL == "gpt-image-2.6-flare"

    driver = _make_common_driver(GptImage26CommonSunburstSite0V1Driver)
    ai_tool = SimpleNamespace(id=1, prompt="a cat", image_path="", ratio="1:1", image_size="1k")
    request = driver.build_create_request(ai_tool)
    assert request["url"] == "https://common.example.com/v1/images/generations"
    assert request["json"]["model"] == "gpt-image-2.6-sunburst"


def test_all_26_implementations_have_unique_ids():
    """14 个新实现方均有唯一数字 ID（112~125），静态映射与 ID 类常量一致。"""
    names = {
        'duomi_gpt_image_2_6_sunburst_v1': 112,
        'duomi_gpt_image_2_6_flare_v1': 113,
        'gpt_image_2_6_common_sunburst_site0_v1': 114,
        'gpt_image_2_6_common_sunburst_site1_v1': 115,
        'gpt_image_2_6_common_sunburst_site2_v1': 116,
        'gpt_image_2_6_common_sunburst_site3_v1': 117,
        'gpt_image_2_6_common_sunburst_site4_v1': 118,
        'gpt_image_2_6_common_sunburst_site5_v1': 119,
        'gpt_image_2_6_common_flare_site0_v1': 120,
        'gpt_image_2_6_common_flare_site1_v1': 121,
        'gpt_image_2_6_common_flare_site2_v1': 122,
        'gpt_image_2_6_common_flare_site3_v1': 123,
        'gpt_image_2_6_common_flare_site4_v1': 124,
        'gpt_image_2_6_common_flare_site5_v1': 125,
    }
    for name, impl_id in names.items():
        assert IMPLEMENTATION_TO_ID[name] == impl_id
        assert IMPLEMENTATION_TO_ID[name] == getattr(DriverImplementationId, name.upper())
        assert UnifiedConfigRegistry.get_implementation(name) is not None


def _common_tool(extra_config: dict, image_path: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        prompt="a cat",
        image_path=image_path,
        ratio="1:1",
        image_size="1k",
        extra_config=json.dumps(extra_config),
    )


def test_common_26_output_format_supports_gif_and_svg():
    """2.6 通用站点 output_format 扩展支持 gif/svg（文生图 JSON + 图片编辑表单均透传）；
    大小写不敏感，jpg 归一为 jpeg，非法值忽略。"""
    driver = _make_common_driver(GptImage26CommonSunburstSite0V1Driver)

    for fmt, expected in [("gif", "gif"), ("SVG", "svg"), ("png", "png"), ("JPG", "jpeg")]:
        request = driver.build_create_request(_common_tool({"output_format": fmt}))
        assert request["json"]["output_format"] == expected

    # 非法值忽略，不写入 payload
    request = driver.build_create_request(_common_tool({"output_format": "tiff"}))
    assert "output_format" not in request["json"]

    # 图片编辑（multipart 表单字段）同样透传
    edit_tool = _common_tool({"output_format": "svg"}, image_path="/a/b.png")
    form_data = driver._build_edit_form_data(edit_tool, "1024x1024")
    assert form_data["output_format"] == "svg"


def test_common_26_quality_supports_xhigh_and_max():
    """2.6 质量档在 2.5 基础上扩展 xhigh/max（openlux 接口文档），文生图与编辑均透传。"""
    driver = _make_common_driver(GptImage26CommonFlareSite0V1Driver)

    request = driver.build_create_request(_common_tool({"quality": "xhigh"}))
    assert request["json"]["quality"] == "xhigh"

    edit_tool = _common_tool({"quality": "max"}, image_path="/a/b.png")
    form_data = driver._build_edit_form_data(edit_tool, "1024x1024")
    assert form_data["quality"] == "max"


def test_common_26_b64_response_mime_sniffing():
    """b64_json 响应不携带格式信息，驱动按字节魔数识别 gif/svg 等真实格式并生成正确 data URL。"""
    driver = _make_common_driver(GptImage26CommonSunburstSite0V1Driver)

    samples = [
        (b"GIF89a" + b"\x00" * 30, "image/gif"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/svg+xml"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 30, "image/png"),
        (b"\xff\xd8\xff\xe0" + b"\x00" * 30, "image/jpeg"),
    ]
    for raw, mime in samples:
        b64 = base64.b64encode(raw).decode()
        expected_url = f"data:{mime};base64,{b64}"
        # images/generations 列表形态
        assert driver._extract_image_from_response({"data": [{"b64_json": b64}]}) == expected_url
        # yunwu edits 字典形态
        assert driver._extract_image_from_response({"data": {"b64_json": b64}}) == expected_url


def test_base_common_driver_rejects_gif_and_svg():
    """gif/svg 仅 2.6 系列启用：GPT Image 2 / 2.5 通用基类收到 gif/svg 时忽略（保持上游兼容）。"""
    from task.visual_drivers.gpt_image_common_v1_driver import GptImage25CommonSunburstSite0V1Driver

    driver = _make_common_driver(GptImage25CommonSunburstSite0V1Driver)
    request = driver.build_create_request(_common_tool({"output_format": "gif"}))
    assert "output_format" not in request["json"]
