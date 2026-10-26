# -*- coding: utf-8 -*-
"""
Seedance TopenRouter 供应商 v1 版本驱动实现
异步 API - 创建任务后轮询状态
支持 Seedance 2.0 Fast / 2.0 / 2.0 Mini / 2.5 四个模型

TopenRouter（topenrouter.chinadatapay.com）的视频接口与火山方舟协议同构：
- 请求体一致（model + content[] 带 role + ratio/duration/resolution/seed/watermark）
- 响应体一致（创建返回 {"id"}；查询返回 status/content.video_url/usage）
- 鉴权一致（Bearer）
差异仅为任务路径（/v1/video/tasks）、模型名简化（doubao-seedance-2.0 系列）、
状态枚举扩展（cancelled/expired，映射为失败）。

继承自火山引擎国内版驱动，覆盖配置加载（topenrouter 配置节）、任务路径与
真人素材处理（SeedanceHumanAssetMixin 按 topenrouter.human_asset_mode 分派，
默认 asset_library：素材经 utils/seedance_asset_client.py 上传真人库加白后
以 asset:// 引用；素材地址/Token 读 topenrouter.asset_base_url / asset_api_key）。
"""
import json
from typing import Dict

from .base_video_driver import BaseVideoDriver
from .seedance_volcengine_v1_driver import SeedanceVolcengineV1Driver
from config.config_util import get_config, get_dynamic_config_value
from config.constant import (
    SEEDANCE_2_5_AUDIO_MAX_TOTAL_DURATION,
    TOPENROUTER_API_BASE_URL,
    TOPENROUTER_SEEDANCE_MODEL_ALIASES,
)
from config.unified_config import DriverImplementation


class SeedanceTopenrouterV1Driver(SeedanceVolcengineV1Driver):
    """
    Seedance TopenRouter v1 版本驱动（基类）

    协议与火山方舟同构，仅覆盖任务路径与模型名；真人素材按
    topenrouter.human_asset_mode 分派（见 SeedanceHumanAssetMixin），
    默认 asset_library 模式经真人库加白后以 asset:// 引用。

    注意：不应直接实例化基类，应使用具体的子类。
    """

    # TopenRouter 任务接口路径（与火山方舟不同的唯二路径差异之一）
    _create_task_path = "/v1/video/tasks"
    _query_task_path = "/v1/video/tasks"
    # TopenRouter 状态枚举比火山多 cancelled / expired，均映射为失败
    _valid_task_statuses = ("queued", "running", "succeeded", "failed", "cancelled", "expired")

    # 真人素材三模式挂 topenrouter 配置组（human_asset_mode / asset_base_url / asset_api_key）
    _human_asset_config_group = "topenrouter"

    # TopenRouter 文档未列出的模型名按惯例推测，可经 topenrouter.model_aliases 热修正
    DEFAULT_MODEL_ALIASES = dict(TOPENROUTER_SEEDANCE_MODEL_ALIASES)

    def __init__(self, driver_type: int, model_name: str, impl_name: str):
        # 跳过父类 __init__，直接调用 BaseVideoDriver 避免加载火山国内配置
        BaseVideoDriver.__init__(
            self,
            driver_name=impl_name,
            driver_type=driver_type
        )

        # 从 TopenRouter 配置节加载
        self._api_key = get_dynamic_config_value("topenrouter", "api_key", default="")
        self._base_url = get_dynamic_config_value(
            "topenrouter", "base_url", default=""
        ).rstrip("/") or TOPENROUTER_API_BASE_URL
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        # 模型名称：默认别名映射 + 配置覆盖（配置优先）
        model_aliases = dict(self.DEFAULT_MODEL_ALIASES)
        configured_aliases = get_dynamic_config_value("topenrouter", "model_aliases", default={})
        if isinstance(configured_aliases, str):
            try:
                configured_aliases = json.loads(configured_aliases)
            except (json.JSONDecodeError, TypeError):
                configured_aliases = {}
        if isinstance(configured_aliases, dict):
            model_aliases.update(configured_aliases)
        self._model = model_aliases.get(model_name, model_name)

        # 是否为本地环境
        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        # 测试模式配置
        self._test_mode_enabled = get_dynamic_config_value("test_mode", "enabled", default=False)
        self._mock_video_url = get_dynamic_config_value("test_mode", "mock_videos", default={}).get("image_to_video")

        self._validate_required({
            "TopenRouter API Key": self._api_key,
        })

    # ---------- 状态映射（cancelled/expired → failed） ----------

    def _map_task_status(self, status: str) -> str:
        if status in ("cancelled", "expired"):
            return "failed"
        return status


# ============ 具体模型实现类 ============

class Seedance20FastTopenrouterV1Driver(SeedanceTopenrouterV1Driver):
    """Seedance 2.0 Fast TopenRouter 驱动"""

    def __init__(self):
        super().__init__(
            driver_type=22,
            model_name="doubao-seedance-2-0-fast-260128",
            impl_name=DriverImplementation.SEEDANCE_2_0_FAST_TOPENROUTER_V1,
        )


class Seedance20TopenrouterV1Driver(SeedanceTopenrouterV1Driver):
    """Seedance 2.0 TopenRouter 驱动"""

    def __init__(self):
        super().__init__(
            driver_type=23,
            model_name="doubao-seedance-2-0-260128",
            impl_name=DriverImplementation.SEEDANCE_2_0_TOPENROUTER_V1,
        )


class Seedance20MiniTopenrouterV1Driver(SeedanceTopenrouterV1Driver):
    """Seedance 2.0 Mini TopenRouter 驱动"""

    def __init__(self):
        super().__init__(
            driver_type=31,
            model_name="doubao-seedance-2-0-mini-260615",
            impl_name=DriverImplementation.SEEDANCE_2_0_MINI_TOPENROUTER_V1,
        )


class Seedance25TopenrouterV1Driver(SeedanceTopenrouterV1Driver):
    """
    Seedance 2.5 全模态 TopenRouter 驱动

    接口与 2.0 系列完全兼容，参考音频限制与火山 2.5 一致：
    总时长 ≤30s 且 ≤10 段（见基类 R2V_AUDIO_MAX_* 注释）。
    """

    R2V_AUDIO_MAX_TOTAL_SECONDS = SEEDANCE_2_5_AUDIO_MAX_TOTAL_DURATION
    R2V_AUDIO_MAX_COUNT = 10

    def __init__(self):
        super().__init__(
            driver_type=36,
            model_name="doubao-seedance-2-5-260628",
            impl_name=DriverImplementation.SEEDANCE_2_5_TOPENROUTER_V1,
        )
