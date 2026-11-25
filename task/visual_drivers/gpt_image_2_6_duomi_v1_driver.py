"""
GPT Image 2.6 多米供应商 v1 版本驱动实现
基于多米 API 平台（与 GPT Image 2 / 2.5 同一接口，仅模型名称不同）：
- 提交: POST https://duomiapi.com/v1/images/generations?async=true
- 查询: GET  https://duomiapi.com/v1/tasks/{id}

sunburst / flare 为两个独立模型（任务类型 55 / 56），仅上游模型名不同：
- gpt-image-2.6-sunburst
- gpt-image-2.6-flare
"""
from config.unified_config import TaskTypeId
from .gpt_image_duomi_v1_driver import GptImageDuomiV1Driver


class GptImage26DuomiSunburstV1Driver(GptImageDuomiV1Driver):
    """
    GPT Image 2.6 Sunburst 多米供应商 v1 版本驱动
    复用 GPT Image 2 多米驱动的提交/查询/尺寸映射逻辑，仅替换上游模型名
    """

    DEFAULT_MODEL = "gpt-image-2.6-sunburst"

    def __init__(self, driver_type: int = TaskTypeId.GPT_IMAGE_2_6_SUNBURST):
        super().__init__(driver_type=driver_type)
        self.driver_name = "duomi_gpt_image_2_6_sunburst_v1"


class GptImage26DuomiFlareV1Driver(GptImage26DuomiSunburstV1Driver):
    """
    GPT Image 2.6 Flare 多米供应商 v1 版本驱动
    与 Sunburst 驱动仅上游模型名不同
    """

    DEFAULT_MODEL = "gpt-image-2.6-flare"

    def __init__(self, driver_type: int = TaskTypeId.GPT_IMAGE_2_6_FLARE):
        super().__init__(driver_type=driver_type)
        self.driver_name = "duomi_gpt_image_2_6_flare_v1"
