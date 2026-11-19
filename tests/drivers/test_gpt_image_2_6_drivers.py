"""GPT Image 2.6 新建模型驱动（多米 / 通用站点 site_0，sunburst / flare 各一个模型）测试。

与 2.5 同构：两个独立任务类型（55 / 56），各挂 7 个实现方（多米默认 + site_0~5），
算力与 2.5 相同（2 点），仅上游模型名升级为 2.6。
"""
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
