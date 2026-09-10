"""GPT Image 2.5 驱动（多米 / 通用站点，sunburst / flare 变体）测试。"""
import logging
import os
from types import SimpleNamespace

os.environ.setdefault("comfyui_env", "prod")

from config.unified_config import (
    DriverImplementation,
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


def test_duomi_sunburst_driver_uses_2_5_model_name():
    """多米 sunburst 驱动沿用 GPT Image 2 接口，仅上游模型名不同。"""
    assert issubclass(GptImage25DuomiSunburstV1Driver, GptImageDuomiV1Driver)
    assert GptImage25DuomiSunburstV1Driver.DEFAULT_MODEL == "gpt-image-2.5-sunburst"


def test_duomi_flare_driver_only_differs_in_model_name():
    """多米 flare 驱动与 sunburst 仅上游模型名不同。"""
    assert issubclass(GptImage25DuomiFlareV1Driver, GptImage25DuomiSunburstV1Driver)
    assert GptImage25DuomiFlareV1Driver.DEFAULT_MODEL == "gpt-image-2.5-flare"


def test_duomi_create_request_carries_2_5_model():
    """文生图请求体 model 字段使用 2.5 模型名，其余结构与 GPT Image 2 一致。"""
    driver = _make_duomi_driver(GptImage25DuomiSunburstV1Driver)
    ai_tool = SimpleNamespace(id=1, prompt="a cat", image_path="", ratio="16:9", image_size="2k")

    request = driver.build_create_request(ai_tool)

    assert request["url"] == "https://duomi.example.com/v1/images/generations?async=true"
    assert request["json"]["model"] == "gpt-image-2.5-sunburst"
    assert request["json"]["size"] == "2048x1152"

    flare_request = _make_duomi_driver(GptImage25DuomiFlareV1Driver).build_create_request(ai_tool)
    assert flare_request["json"]["model"] == "gpt-image-2.5-flare"


def test_common_site_driver_uses_2_5_model_names():
    """通用站点 sunburst/flare 驱动文生图与编辑请求均使用 2.5 模型名。"""
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


def test_task_config_wiring():
    """任务配置：id=46、同时挂图片编辑与文生图类目、默认实现方为多米 Sunburst。"""
    cfg = UnifiedConfigRegistry.get_by_id(TaskTypeId.GPT_IMAGE_2_5)
    assert cfg is not None
    assert cfg.key == 'gpt-image-2.5-edit'
    assert cfg.driver_name == 'gpt_image_2_5'
    assert cfg.category == 'image_edit'
    assert 'text_to_image' in cfg.categories
    assert cfg.implementation == 'duomi_gpt_image_2_5_sunburst_v1'
    assert len(cfg.implementations) == 14


def test_all_25_implementations_have_unique_ids():
    """14 个新实现方均有唯一数字 ID，静态映射与 ID 类常量一致。"""
    names = [
        'duomi_gpt_image_2_5_sunburst_v1',
        'duomi_gpt_image_2_5_flare_v1',
        'gpt_image_2_5_common_sunburst_site0_v1',
        'gpt_image_2_5_common_sunburst_site1_v1',
        'gpt_image_2_5_common_sunburst_site2_v1',
        'gpt_image_2_5_common_sunburst_site3_v1',
        'gpt_image_2_5_common_sunburst_site4_v1',
        'gpt_image_2_5_common_sunburst_site5_v1',
        'gpt_image_2_5_common_flare_site0_v1',
        'gpt_image_2_5_common_flare_site1_v1',
        'gpt_image_2_5_common_flare_site2_v1',
        'gpt_image_2_5_common_flare_site3_v1',
        'gpt_image_2_5_common_flare_site4_v1',
        'gpt_image_2_5_common_flare_site5_v1',
    ]
    ids = [IMPLEMENTATION_TO_ID[name] for name in names]
    assert len(ids) == len(set(ids))
    for name in names:
        assert IMPLEMENTATION_TO_ID[name] == getattr(DriverImplementationId, name.upper())
        assert UnifiedConfigRegistry.get_implementation(name) is not None
