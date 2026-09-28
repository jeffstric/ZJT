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
真人素材 asset:// 引用（复用 supports_auto_face + enable_face_mask 闸门注入的
human_review 标志，素材经 utils/seedance_asset_client.py 上传平台素材库加白）。
"""
import json
from typing import Any, Dict

from .base_video_driver import BaseVideoDriver
from .seedance_volcengine_v1_driver import SeedanceVolcengineV1Driver
from config.config_util import get_config, get_dynamic_config_value
from config.constant import (
    SEEDANCE_2_5_AUDIO_MAX_TOTAL_DURATION,
    SEEDANCE_ASSET_URL_SCHEME,
    TOPENROUTER_ASSET_BASE_URL,
    TOPENROUTER_SEEDANCE_MODEL_ALIASES,
)
from config.unified_config import DriverImplementation
from utils.seedance_asset_client import SeedanceAssetClient, SeedanceAssetError

# content 条目 type → 素材库 AssetType（真人素材上传素材库时的类型映射）
_ASSET_TYPE_BY_CONTENT_TYPE = {
    "image_url": "Image",
    "video_url": "Video",
    "audio_url": "Audio",
}


class SeedanceTopenrouterV1Driver(SeedanceVolcengineV1Driver):
    """
    Seedance TopenRouter v1 版本驱动（基类）

    协议与火山方舟同构，仅覆盖任务路径与模型名；真人素材经平台素材库
    （Action 接口）上传加白后以 asset:// 引用，规避真人风控。

    注意：不应直接实例化基类，应使用具体的子类。
    """

    # TopenRouter 任务接口路径（与火山方舟不同的唯二路径差异之一）
    _create_task_path = "/v1/video/tasks"
    _query_task_path = "/v1/video/tasks"
    # TopenRouter 状态枚举比火山多 cancelled / expired，均映射为失败
    _valid_task_statuses = ("queued", "running", "succeeded", "failed", "cancelled", "expired")

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
        ).rstrip("/") or TOPENROUTER_ASSET_BASE_URL
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

        # 素材库客户端（真人素材加白；token 读 asset_api_key 缺省回落 api_key）
        self._asset_client = SeedanceAssetClient(api_key=self._api_key, base_url=self._base_url)

    # ---------- 状态映射（cancelled/expired → failed） ----------

    def _map_task_status(self, status: str) -> str:
        if status in ("cancelled", "expired"):
            return "failed"
        return status

    # ---------- 真人素材 asset:// 引用 ----------

    def _should_use_asset_library(self, extra_config: Dict[str, Any]) -> bool:
        """
        是否将媒体素材上传平台素材库并以 asset:// 引用（真人素材加白）。

        判定与 huimengi human_review 一致：
        - extra_config 显式声明 human_review 时以其为准（server 端 supports_auto_face
          闸门在用户勾选人脸处理时注入 true）
        - 未声明但 enable_face_mask=true 时补注 true（跨实现方失败重试切换到本
          实现方后 extra_config 字段缺失的兜底场景）
        """
        if extra_config.get('human_review') is not None:
            return bool(extra_config['human_review'])
        return bool(extra_config.get('enable_face_mask'))

    def _convert_content_to_asset_refs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        将 content 中的图片/视频/音频公网 URL 上传平台素材库并替换为 asset:// 引用。

        素材需等待 Active 才可用于视频生成；上传/等待失败直接抛错由调用方转为
        SYSTEM 错误（不静默降级直传 URL：真人素材直传会触发上游敏感风控）。
        """
        content = payload.get("content")
        if not isinstance(content, list):
            return payload
        for item in content:
            item_type = item.get("type")
            asset_type = _ASSET_TYPE_BY_CONTENT_TYPE.get(item_type)
            media = item.get(item_type)
            url = media.get("url") if isinstance(media, dict) else None
            if not asset_type or not url or url.startswith(SEEDANCE_ASSET_URL_SCHEME):
                continue
            asset = self._asset_client.create_asset(url=url, asset_type=asset_type)
            asset_id = asset.get("Id")
            if not asset_id:
                raise SeedanceAssetError(f"素材接口未返回 Id: {url}")
            self._asset_client.wait_asset_active(asset_id)
            media["url"] = f"{SEEDANCE_ASSET_URL_SCHEME}{asset_id}"
            self.logger.info(
                f"[{self.driver_name}] 真人素材已上传素材库: {url} -> {media['url']}"
            )
        return payload

    # ---------- 请求构造（插入素材库转换） ----------

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """构建创建任务请求；真人审核模式下先把媒体素材换 asset:// 引用"""
        request_params = super().build_create_request(ai_tool)

        # super() 返回业务错误（如图片处理失败）时直接透传
        if not isinstance(request_params, dict) or request_params.get("success") is False:
            return request_params

        if self._should_use_asset_library(self._parse_extra_config(ai_tool)):
            try:
                request_params["json"] = self._convert_content_to_asset_refs(
                    request_params["json"]
                )
            except SeedanceAssetError as e:
                # 素材上传/等待失败：系统级错误，可重试；不降级直传（真人风控）
                self.logger.error(f"[{self.driver_name}] 真人素材上传素材库失败: {e.message}")
                self._send_alert(
                    alert_type="ASSET_UPLOAD_FAILED",
                    message=f"TopenRouter 素材库上传失败: {e.message}",
                    context={"task_id": ai_tool.id, "code": e.code, "http_status": e.http_status}
                )
                return {
                    "success": False,
                    "error": "真人素材上传失败，请稍后重试",
                    "error_type": "SYSTEM",
                    "error_detail": e.message,
                    "retry": True
                }
        return request_params


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
