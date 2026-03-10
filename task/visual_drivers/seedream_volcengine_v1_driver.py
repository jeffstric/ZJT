"""
Seedream 火山引擎供应商 v1 版本驱动实现
同步 API - 一次请求直接返回图片 URL
支持 Seedream 4.5 和 5.0 两个模型
"""
from typing import Dict, Any, Optional
import traceback
from .base_video_driver import BaseVideoDriver
from config.config_util import get_config, get_dynamic_config_value
from config.unified_config import TaskTypeId
from utils.sentry_util import SentryUtil, AlertLevel
from utils.image_upload_utils import upload_local_images_to_cdn_sync


class Seedream5VolcengineV1Driver(BaseVideoDriver):
    """
    Seedream 火山引擎供应商 v1 版本驱动
    同步 API - 支持文生图/图片编辑
    支持 Seedream 4.5 和 5.0 两个模型
    """

    # 模型映射：task_id -> 模型名称
    MODEL_MAPPING = {
        TaskTypeId.SEEDREAM_TEXT_TO_IMAGE: "doubao-seedream-5-0-260128",
        TaskTypeId.SEEDREAM_4_5_IMAGE: "doubao-seedream-4-5-251128",
    }

    # 支持的图片尺寸
    SUPPORTED_SIZES = ["2K", "3K", "4K"]

    # 尺寸映射表：基于 image_size 和 aspect_ratio 获取像素值
    SIZE_MAPPING = {
        "2K": {
            "1:1": "2048x2048",
            "4:3": "2304x1728",
            "3:4": "1728x2304",
            "16:9": "2848x1600",
            "9:16": "1600x2848",
            "3:2": "2496x1664",
            "2:3": "1664x2496",
            "21:9": "3136x1344",
        },
        "3K": {
            "1:1": "3072x3072",
            "4:3": "3456x2592",
            "3:4": "2592x3456",
            "16:9": "4096x2304",
            "9:16": "2304x4096",
            "2:3": "2496x3744",
            "3:2": "3744x2496",
            "21:9": "4704x2016",
        },
        "4K": {
            "1:1": "4096x4096",
            "4:3": "4704x3520",
            "3:4": "3520x4704",
            "16:9": "5504x3040",
            "9:16": "3040x5504",
            "2:3": "3328x4992",
            "3:2": "4992x3328",
            "21:9": "6240x2656",
        }
    }

    def __init__(self):
        super().__init__(driver_name="seedream5_volcengine_v1", driver_type=16)

        # 加载配置
        self._api_key = get_dynamic_config_value("volcengine", "api_key", default="")
        self._base_url = "https://ark.cn-beijing.volces.com"
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=60)
        self._model = "doubao-seedream-5-0-260128"

        # 是否为本地环境
        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        self._validate_required({
            "Volcengine API Key": self._api_key,
        })

    def _send_alert(self, alert_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        """
        发送报警信息
        """
        SentryUtil.send_alert(
            alert_type=alert_type,
            message=message,
            level=AlertLevel.ERROR,
            context=context
        )

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 submit_task API 响应格式

        期望的正确响应格式:
        {
            "model": "doubao-seedream-5-0-260128",
            "created": 1772527784,
            "data": [
                {
                    "url": "https://...",
                    "size": "1664x2496"
                }
            ],
            "usage": {...}
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "error" in result:
            error_info = result.get("error", {})
            error_code = error_info.get("code", "Unknown")
            error_message = error_info.get("message", "未知错误")
            return False, f"API 错误 [{error_code}]: {error_message}"

        if "data" not in result:
            return False, f"响应缺少 'data' 字段，实际字段: {list(result.keys())}"

        data = result.get("data")
        if not isinstance(data, list) or len(data) == 0:
            return False, f"'data' 字段为空或非数组类型"

        first_item = data[0]
        if "url" not in first_item:
            return False, f"'data[0]' 缺少 'url' 字段"

        return True, None

    def _validate_status_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 check_status API 响应格式
        同步 API 不需要轮询，此方法不会被调用
        """
        return True, None

    def _get_pixel_size(self, image_size: str, aspect_ratio: str) -> str:
        """
        根据 image_size 和 aspect_ratio 获取像素尺寸

        Args:
            image_size: 分辨率 (2K/3K)
            aspect_ratio: 宽高比 (1:1, 4:3, 3:4, 16:9, 9:16, 3:2, 2:3, 21:9)

        Returns:
            像素尺寸字符串，如 "2048x2048"
        """
        if image_size not in self.SIZE_MAPPING:
            image_size = "2K"

        size_dict = self.SIZE_MAPPING[image_size]

        if aspect_ratio in size_dict:
            return size_dict[aspect_ratio]

        # 默认返回 1:1
        return size_dict.get("1:1", "2048x2048")

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 Seedream 任务的完整请求参数
        """
        # 获取图片尺寸，默认 2K
        image_size = getattr(ai_tool, 'image_size', None) or "2K"
        if image_size not in self.SUPPORTED_SIZES:
            image_size = "2K"

        # 获取宽高比，默认 1:1
        aspect_ratio = getattr(ai_tool, 'ratio', None) or "1:1"

        # 基于 image_size 和 aspect_ratio 获取像素尺寸
        pixel_size = self._get_pixel_size(image_size, aspect_ratio)

        # 处理图片路径
        image_urls = None
        if ai_tool.image_path:
            image_urls = ai_tool.image_path.split(',') if ',' in ai_tool.image_path else [ai_tool.image_path]
            # 如果是本地环境，将本地图片上传到图床
            if self._is_local:
                self.logger.info(f"本地环境检测到图片路径，准备上传到图床: {image_urls}")
                image_urls = upload_local_images_to_cdn_sync(image_urls, self._config)
                self.logger.info(f"图片上传完成，CDN链接: {image_urls}")

        # 根据 task_id 选择模型
        task_type = getattr(ai_tool, 'type', None)
        model_name = self.MODEL_MAPPING.get(task_type, self._model)
        self.logger.info(f"使用模型: {model_name}, task_type: {task_type}")

        payload = {
            "model": model_name,
            "prompt": ai_tool.prompt,
            "size": pixel_size,
            "watermark": False
        }
        
        # Seedream 5.0 支持 output_format 参数，4.5 不支持
        if task_type == TaskTypeId.SEEDREAM_TEXT_TO_IMAGE:
            payload["output_format"] = "png"

        # 如果有图片路径，添加 image 参数（数组，支持多张图片）
        if image_urls:
            payload["image"] = image_urls

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}"
        }

        return {
            "url": f"{self._base_url}/api/v3/images/generations",
            "method": "POST",
            "json": payload,
            "headers": headers,
            "timeout": self._timeout
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询任务状态的请求参数
        同步 API 不需要轮询，返回空
        """
        return {}

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交任务到火山引擎 Seedream API
        同步 API - 直接返回图片 URL
        """
        task_id = ai_tool.id

        try:
            # 1. 构建请求参数
            request_params = self.build_create_request(ai_tool)

            # 2. 发送请求
            result = self._request(
                url=request_params["url"],
                method=request_params["method"],
                json=request_params["json"],
                headers=request_params["headers"],
                timeout=request_params.get("timeout", self._timeout)
            )

            # 3. 验证响应格式
            is_valid, error_msg = self._validate_submit_response(result)
            if not is_valid:
                # 检查是否为用户可见错误
                if "API 错误" in error_msg:
                    return {
                        "success": False,
                        "error": error_msg,
                        "error_type": "USER",
                        "retry": False
                    }

                # 系统错误，发送报警
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Seedream API 响应格式错误: {error_msg}",
                    context={"task_id": task_id, "response": result}
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": error_msg,
                    "retry": False
                }

            # 4. 提取图片 URL
            result_url = result["data"][0]["url"]

            # 5. 返回同步模式结果
            return {
                "success": True,
                "sync_mode": True,
                "result_url": result_url
            }

        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Seedream submit_task error: {error_msg}")
            self.logger.error(traceback.format_exc())

            # 网络异常，可以重试
            if "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            # 其他异常
            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Seedream submit_task 异常: {error_msg}",
                context={"task_id": task_id, "traceback": traceback.format_exc()}
            )
            return {
                "success": False,
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": error_msg,
                "retry": False
            }

    def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        检查任务状态
        同步 API 不需要轮询，此方法不会被调用
        """
        return {"status": "SUCCESS"}
