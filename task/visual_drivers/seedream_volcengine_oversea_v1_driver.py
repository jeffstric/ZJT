"""
Seedream 火山引擎海外版 v1 版本驱动实现
同步 API - 一次请求直接返回图片 URL
2026-11-20 起统一使用 Seedream 5.0 Pro（5.0/4.5 同代快照已下线）

继承自国内版驱动，覆盖配置加载（使用 volcengine_oversea 配置节）。
"""
from .base_video_driver import BaseVideoDriver
from .seedream_volcengine_v1_driver import Seedream5VolcengineV1Driver
from config.config_util import get_config, get_dynamic_config_value
from config.unified_config import TaskTypeId


class Seedream5VolcengineOverseaV1Driver(Seedream5VolcengineV1Driver):
    """
    Seedream 火山引擎海外版 v1 版本驱动
    同步 API - 支持文生图/图片编辑
    使用 volcengine_oversea 配置（独立的 api_key + base_url）
    """

    # 海外版模型映射：task_id -> 模型名称（不带 doubao- 前缀）
    # 2026-11-20 与国内版同步：5-0-260128 / 4-5-251128 为同代退役快照；
    # Task 16/18 已停用（hidden），此处保留兼容映射指向在售
    # seedream-5-0-pro-260628（历史重试/显式 task_id 调用兜底）
    MODEL_MAPPING = {
        TaskTypeId.SEEDREAM_TEXT_TO_IMAGE: "seedream-5-0-pro-260628",
        TaskTypeId.SEEDREAM_4_5_IMAGE: "seedream-5-0-pro-260628",
        TaskTypeId.SEEDREAM_5_0_PRO: "seedream-5-0-pro-260628",
    }

    def __init__(self):
        # 跳过父类 __init__，直接调用 BaseVideoDriver 避免加载国内配置
        BaseVideoDriver.__init__(
            self,
            driver_name="seedream5_volcengine_oversea_v1",
            driver_type=TaskTypeId.SEEDREAM_TEXT_TO_IMAGE
        )

        # 从海外版配置加载
        self._api_key = get_dynamic_config_value("volcengine_oversea", "api_key", default="")
        self._base_url = get_dynamic_config_value(
            "volcengine_oversea", "base_url",
            default="https://ark.ap-southeast.bytepluses.com"
        )
        # 同步请求接口需要更长的超时时间，不复用异步接口的 request_timeout
        # sync_request_timeout 为纯秒语义（可能 ×2 放大），跳过 coerce 的
        # ≥1000 毫秒启发式，防大秒值被误除 1000（#8）
        self._skip_timeout_coerce = True
        self._timeout = get_dynamic_config_value("timeout", "sync_request_timeout", default=300)
        self._model = "seedream-5-0-pro-260628"

        # 是否为本地环境
        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        self._validate_required({
            "Volcengine Oversea API Key": self._api_key,
        })
