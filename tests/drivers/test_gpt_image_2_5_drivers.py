"""GPT Image 2.5 拆分模型驱动（多米 / 通用站点 site_0，sunburst / flare 各一个模型）测试。"""
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
from task.visual_drivers.gpt_image_2_5_duomi_v1_driver import (
    GptImage25DuomiFlareV1Driver,
    GptImage25DuomiSunburstV1Driver,
)
from task.visual_drivers.gpt_image_common_v1_driver import (
    GptImage25CommonFlareSite0V1Driver,
    GptImage25CommonFlareV1Driver,
    GptImage25CommonSunburstSite0V1Driver,
    GptImage25CommonSunburstV1Driver,
)
from task.visual_drivers.gpt_image_duomi_v1_driver import GptImageDuomiV1Driver


def _make_duomi_driver(cls):
    driver = cls.__new__(cls)
    driver._base_url = "https://duomi.example.com"
    driver._token = "test-token"
    driver.logger = logging.getLogger("test_gpt_image_2_5_duomi")
    driver._timeout = 30
    driver._send_alert = lambda **kwargs: None
    return driver


def _make_common_driver(cls):
    driver = cls.__new__(cls)
    driver._base_url = "https://common.example.com"
    driver._api_key = "test-key"
    driver.logger = logging.getLogger("test_gpt_image_2_5_common")
    return driver


def test_sunburst_and_flare_are_two_independent_models():
    """sunburst / flare 拆分为两个独立任务类型（46 / 47），各自挂图片编辑 + 文生图类目。"""
    assert GptImage25DuomiSunburstV1Driver.DEFAULT_MODEL == "gpt-image-2.5-sunburst"
    assert GptImage25DuomiFlareV1Driver.DEFAULT_MODEL == "gpt-image-2.5-flare"

    sunburst_cfg = UnifiedConfigRegistry.get_by_id(TaskTypeId.GPT_IMAGE_2_5_SUNBURST)
    flare_cfg = UnifiedConfigRegistry.get_by_id(TaskTypeId.GPT_IMAGE_2_5_FLARE)

    assert sunburst_cfg.key == 'gpt-image-2.5-sunburst-edit'
    assert sunburst_cfg.short_key == 'gpt-image-2.5-sunburst'
    assert sunburst_cfg.model_name == 'GPT Image 2.5 Sunburst'
    assert sunburst_cfg.driver_name == 'gpt_image_2_5_sunburst'
    assert flare_cfg.key == 'gpt-image-2.5-flare-edit'
    assert flare_cfg.short_key == 'gpt-image-2.5-flare'
    assert flare_cfg.model_name == 'GPT Image 2.5 Flare'
    assert flare_cfg.driver_name == 'gpt_image_2_5_flare'

    for cfg in (sunburst_cfg, flare_cfg):
        assert cfg.category == 'image_edit'
        assert 'text_to_image' in cfg.categories
        assert cfg.computing_power == 2


def test_each_model_has_seven_implementations_with_duomi_default():
    """每个模型 7 个实现方：多米（默认）+ 聚合站点 site_0~site_5。"""
    sunburst_cfg = UnifiedConfigRegistry.get_by_id(TaskTypeId.GPT_IMAGE_2_5_SUNBURST)
    flare_cfg = UnifiedConfigRegistry.get_by_id(TaskTypeId.GPT_IMAGE_2_5_FLARE)

    assert sunburst_cfg.implementation == 'duomi_gpt_image_2_5_sunburst_v1'
    assert sunburst_cfg.implementations == [
        'duomi_gpt_image_2_5_sunburst_v1',
        'gpt_image_2_5_common_sunburst_site0_v1',
        'gpt_image_2_5_common_sunburst_site1_v1',
        'gpt_image_2_5_common_sunburst_site2_v1',
        'gpt_image_2_5_common_sunburst_site3_v1',
        'gpt_image_2_5_common_sunburst_site4_v1',
        'gpt_image_2_5_common_sunburst_site5_v1',
    ]
    assert flare_cfg.implementation == 'duomi_gpt_image_2_5_flare_v1'
    assert flare_cfg.implementations == [
        'duomi_gpt_image_2_5_flare_v1',
        'gpt_image_2_5_common_flare_site0_v1',
        'gpt_image_2_5_common_flare_site1_v1',
        'gpt_image_2_5_common_flare_site2_v1',
        'gpt_image_2_5_common_flare_site3_v1',
        'gpt_image_2_5_common_flare_site4_v1',
        'gpt_image_2_5_common_flare_site5_v1',
    ]


def test_duomi_create_request_carries_model_name():
    """多米驱动文生图请求体使用对应模型名，其余结构与 GPT Image 2 一致。"""
    assert issubclass(GptImage25DuomiSunburstV1Driver, GptImageDuomiV1Driver)
    ai_tool = SimpleNamespace(id=1, prompt="a cat", image_path="", ratio="16:9", image_size="2k")

    request = _make_duomi_driver(GptImage25DuomiSunburstV1Driver).build_create_request(ai_tool)
    assert request["url"] == "https://duomi.example.com/v1/images/generations?async=true"
    assert request["json"]["model"] == "gpt-image-2.5-sunburst"
    assert request["json"]["size"] == "2048x1152"

    flare_request = _make_duomi_driver(GptImage25DuomiFlareV1Driver).build_create_request(ai_tool)
    assert flare_request["json"]["model"] == "gpt-image-2.5-flare"


def test_common_site_driver_uses_model_names():
    """通用站点 sunburst/flare 驱动文生图请求使用对应模型名。"""
    assert issubclass(GptImage25CommonSunburstSite0V1Driver, GptImage25CommonSunburstV1Driver)
    assert GptImage25CommonSunburstV1Driver.DEFAULT_MODEL == "gpt-image-2.5-sunburst"
    assert GptImage25CommonSunburstV1Driver.EDIT_MODEL == "gpt-image-2.5-sunburst"
    assert GptImage25CommonFlareV1Driver.DEFAULT_MODEL == "gpt-image-2.5-flare"
    assert GptImage25CommonFlareV1Driver.EDIT_MODEL == "gpt-image-2.5-flare"

    driver = _make_common_driver(GptImage25CommonSunburstSite0V1Driver)
    ai_tool = SimpleNamespace(id=1, prompt="a cat", image_path="", ratio="1:1", image_size="1k")
    request = driver.build_create_request(ai_tool)
    assert request["url"] == "https://common.example.com/v1/images/generations"
    assert request["json"]["model"] == "gpt-image-2.5-sunburst"


def test_all_25_implementations_have_unique_ids():
    """14 个新实现方均有唯一数字 ID，静态映射与 ID 类常量一致。"""
    names = {
        'duomi_gpt_image_2_5_sunburst_v1': 85,
        'duomi_gpt_image_2_5_flare_v1': 86,
        'gpt_image_2_5_common_sunburst_site0_v1': 87,
        'gpt_image_2_5_common_sunburst_site1_v1': 89,
        'gpt_image_2_5_common_sunburst_site2_v1': 90,
        'gpt_image_2_5_common_sunburst_site3_v1': 91,
        'gpt_image_2_5_common_sunburst_site4_v1': 92,
        'gpt_image_2_5_common_sunburst_site5_v1': 93,
        'gpt_image_2_5_common_flare_site0_v1': 88,
        'gpt_image_2_5_common_flare_site1_v1': 94,
        'gpt_image_2_5_common_flare_site2_v1': 95,
        'gpt_image_2_5_common_flare_site3_v1': 96,
        'gpt_image_2_5_common_flare_site4_v1': 97,
        'gpt_image_2_5_common_flare_site5_v1': 98,
    }
    for name, impl_id in names.items():
        assert IMPLEMENTATION_TO_ID[name] == impl_id
        assert IMPLEMENTATION_TO_ID[name] == getattr(DriverImplementationId, name.upper())
        assert UnifiedConfigRegistry.get_implementation(name) is not None
