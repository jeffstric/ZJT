"""
Seedance 火山引擎海外版 v1 版本驱动实现
异步 API - 创建任务后轮询状态
支持 Seedance 2.0 Fast / 2.0 两个模型（图生视频）

继承自国内版驱动，覆盖配置加载（使用 volcengine_oversea 配置节）。
支持通过 volcengine_oversea.model_aliases 配置模型别名。
"""
import json
from .base_video_driver import BaseVideoDriver
from .seedance_volcengine_v1_driver import SeedanceVolcengineV1Driver
from config.config_util import get_config, get_dynamic_config_value
from config.unified_config import DriverImplementation


class SeedanceVolcengineOverseaV1Driver(SeedanceVolcengineV1Driver):
    """
    Seedance 火山引擎海外版 v1 版本驱动（基类）
    覆盖配置加载，使用 volcengine_oversea 配置

    注意：不应直接实例化基类，应使用具体的子类。
    """

    def __init__(self, driver_type: int, model_name: str, impl_name: str = DriverImplementation.SEEDANCE_2_0_VOLCENGINE_OVERSEA_V1):
        # 跳过父类 __init__，直接调用 BaseVideoDriver 避免加载国内配置
        BaseVideoDriver.__init__(
            self,
            driver_name=impl_name,
            driver_type=driver_type
        )

        # 从海外版配置加载
        self._api_key = get_dynamic_config_value("volcengine_oversea", "api_key", default="")
        self._base_url = get_dynamic_config_value(
            "volcengine_oversea", "base_url",
            default="https://ark.ap-southeast.bytepluses.com"
        )
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        # 模型名称（支持别名配置）
        model_aliases = get_dynamic_config_value("volcengine_oversea", "model_aliases", default={})
        if isinstance(model_aliases, str):
            try:
                model_aliases = json.loads(model_aliases)
            except (json.JSONDecodeError, TypeError):
                model_aliases = {}
        self._model = model_aliases.get(model_name, model_name)

        # 是否为本地环境
        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        # 测试模式配置
        self._test_mode_enabled = get_dynamic_config_value("test_mode", "enabled", default=False)
        self._mock_video_url = get_dynamic_config_value("test_mode", "mock_videos", default={}).get("image_to_video")

        self._validate_required({
            "Volcengine Oversea API Key": self._api_key,
        })


class Seedance20FastVolcengineOverseaV1Driver(SeedanceVolcengineOverseaV1Driver):
    """Seedance 2.0 Fast 火山引擎海外版驱动"""

    def __init__(self):
        super().__init__(
            driver_type=22,
            model_name="doubao-seedance-2-0-fast-260128",
            impl_name=DriverImplementation.SEEDANCE_2_0_FAST_VOLCENGINE_OVERSEA_V1
        )


class Seedance20VolcengineOverseaV1Driver(SeedanceVolcengineOverseaV1Driver):
    """Seedance 2.0 火山引擎海外版驱动"""

    def __init__(self):
        super().__init__(
            driver_type=23,
            model_name="doubao-seedance-2-0-260128",
            impl_name=DriverImplementation.SEEDANCE_2_0_VOLCENGINE_OVERSEA_V1
        )


class Seedance20MiniVolcengineOverseaV1Driver(SeedanceVolcengineOverseaV1Driver):
    """Seedance 2.0 Mini 火山引擎海外版驱动"""

    def __init__(self):
        super().__init__(
            driver_type=31,
            model_name="doubao-seedance-2-0-mini-260615",
            impl_name=DriverImplementation.SEEDANCE_2_0_MINI_VOLCENGINE_OVERSEA_V1
        )
