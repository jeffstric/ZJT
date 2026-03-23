"""
Gemini Image Preview 通用供应商 v1 版本驱动实现
使用 Gemini 原生 API 格式（generateContent）
支持多个 Gemini 模型进行图片生成/编辑

适配的模型：
- gemini-2.5-flash-image:generateContent
- gemini-3-pro-image-preview:generateContent
- gemini-3.1-flash-image-preview:generateContent

该驱动适用于兼容 Gemini 原生 API 格式的中转站
"""
from typing import Dict, Any, Optional
import traceback
import base64
import requests
from .base_video_driver import BaseVideoDriver
from config.config_util import get_config, get_dynamic_config_value
from config.unified_config import TaskTypeId
from utils.sentry_util import SentryUtil, AlertLevel


class GeminiImagePreviewCommonV1Driver(BaseVideoDriver):
    """
    Gemini Image Preview 通用供应商 v1 版本驱动（基类）
    使用 Gemini 原生 API 格式进行图片生成/编辑

    特点：
    - 同步接口，直接返回结果，无需轮询
    - 支持 base64 编码的图片输入
    - 支持宽高比和清晰度控制
    - 支持多模型切换（根据 task_id 自动选择模型）
    - 支持多个 Gemini 任务类型
    
    注意：这是基类，不应该直接实例化，应该使用具体的站点类
    """

    # 支持的 DriverKey 列表
    SUPPORTED_DRIVER_KEYS = [
        'gemini_image_edit',
        'gemini_image_edit_pro', 
        'gemini_3_1_flash_image_edit'
    ]

    # 模型映射：task_id -> 模型名称
    MODEL_MAPPING = {
        TaskTypeId.GEMINI_2_5_FLASH_IMAGE: "gemini-2.5-flash-image",
        TaskTypeId.GEMINI_3_PRO_IMAGE: "gemini-3-pro-image-preview",
        TaskTypeId.GEMINI_3_1_FLASH_IMAGE: "gemini-3.1-flash-image-preview",
    }

    # 默认模型
    DEFAULT_MODEL = "gemini-2.5-flash-image"

    # 默认配置
    DEFAULT_ASPECT_RATIO = "9:16"
    DEFAULT_IMAGE_SIZE = "1K"

    def __init__(self, site_id: str):
        """
        初始化驱动（基类）

        Args:
            site_id: API 聚合站点ID（如 site_1, site_2, ... site_5）
                     对应配置 api_aggregator.site_X
        """
        self._site_id = site_id
        driver_name = f"gemini_common_{site_id}"
        super().__init__(driver_name=driver_name, driver_type=7)

        # 从 api_aggregator.{site_id} 加载配置
        self._api_key = get_dynamic_config_value("api_aggregator", site_id, "api_key", default="")
        self._base_url = get_dynamic_config_value("api_aggregator", site_id, "base_url", default="")
        self._site_name = get_dynamic_config_value("api_aggregator", site_id, "name", default=site_id)
        self._timeout = get_dynamic_config_value("timeout", "sync_request_timeout", default=300)

        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        self._validate_required({
            f"API Aggregator {site_id} API Key": self._api_key,
            f"API Aggregator {site_id} Base URL": self._base_url,
        })

    def _send_alert(self, alert_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        """
        发送报警信息

        Args:
            alert_type: 报警类型，如 "INVALID_RESPONSE_FORMAT", "UNEXPECTED_EXCEPTION"
            message: 报警消息
            context: 上下文信息（可选）
        """
        SentryUtil.send_alert(
            alert_type=alert_type,
            message=message,
            level=AlertLevel.ERROR,
            context=context
        )

    def _download_image_as_base64(self, image_url: str) -> tuple[str, str]:
        """
        下载图片并转换为 base64 编码

        Args:
            image_url: 图片 URL

        Returns:
            tuple[str, str]: (base64_data, mime_type)
        """
        try:
            response = requests.get(image_url, timeout=30)
            response.raise_for_status()

            # 根据内容类型确定 mime_type
            content_type = response.headers.get('Content-Type', 'image/jpeg')
            if 'png' in content_type.lower():
                mime_type = 'image/png'
            elif 'gif' in content_type.lower():
                mime_type = 'image/gif'
            elif 'webp' in content_type.lower():
                mime_type = 'image/webp'
            else:
                mime_type = 'image/jpeg'

            # 转换为 base64
            base64_data = base64.b64encode(response.content).decode('utf-8')
            return base64_data, mime_type

        except Exception as e:
            self.logger.error(f"Failed to download image: {image_url}, error: {str(e)}")
            raise

    def _get_model_name(self, ai_tool) -> str:
        """
        根据 task_id 获取模型名称

        Args:
            ai_tool: AITool 对象

        Returns:
            str: 模型名称
        """
        task_type = getattr(ai_tool, 'type', None)
        model_name = self.MODEL_MAPPING.get(task_type, self.DEFAULT_MODEL)
        self.logger.info(f"使用模型: {model_name}, task_type: {task_type}")
        return model_name

    def _build_contents(self, ai_tool) -> list:
        """
        构建 Gemini API 的 contents 部分

        Args:
            ai_tool: AITool 对象

        Returns:
            list: contents 数组
        """
        parts = []

        # 添加文本提示词
        if ai_tool.prompt:
            parts.append({"text": ai_tool.prompt})

        # 添加图片（如果存在）
        if ai_tool.image_path:
            # 支持逗号分隔的多个图片 URL
            image_urls = [url.strip() for url in ai_tool.image_path.split(',') if url.strip()]

            for image_url in image_urls:
                try:
                    base64_data, mime_type = self._download_image_as_base64(image_url)
                    parts.append({
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": base64_data
                        }
                    })
                except Exception as e:
                    self.logger.warning(f"Failed to process image {image_url}: {str(e)}")
                    # 继续处理其他图片，不中断

        return [{"role": "user", "parts": parts}]

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 Gemini 任务的完整请求参数

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # 获取模型名称
        model_name = self._get_model_name(ai_tool)

        # 构建 contents
        contents = self._build_contents(ai_tool)

        # 构建请求体
        payload = {
            "contents": contents,
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": {
                    "aspectRatio": ai_tool.ratio or self.DEFAULT_ASPECT_RATIO,
                    "imageSize": ai_tool.image_size or self.DEFAULT_IMAGE_SIZE
                }
            }
        }

        # 构建完整 URL（包含 key 参数）
        url = f"{self._base_url}/v1beta/models/{model_name}:generateContent?key={self._api_key}"

        return {
            "url": url,
            "method": "POST",
            "json": payload,
            "headers": {
                "Content-Type": "application/json"
            }
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询任务状态的完整请求参数

        注意：Gemini Image Preview 是同步接口，此方法仅用于接口兼容

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # 同步接口不需要轮询，返回空请求
        return {
            "url": "",
            "method": "GET",
            "json": None,
            "headers": {}
        }

    def _extract_image_from_response(self, response: dict) -> Optional[str]:
        """
        从 Gemini API 响应中提取图片 URL 或 base64 数据

        Args:
            response: API 响应

        Returns:
            Optional[str]: 图片 URL 或 data URL
        """
        try:
            candidates = response.get("candidates", [])
            if not candidates:
                return None

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])

            for part in parts:
                # 检查是否有 inlineData（base64 图片）
                if "inlineData" in part:
                    inline_data = part["inlineData"]
                    mime_type = inline_data.get("mimeType", "image/png")
                    data = inline_data.get("data", "")
                    if data:
                        # 返回 data URL 格式
                        return f"data:{mime_type};base64,{data}"

                # 兼容旧格式 inline_data（下划线格式）
                if "inline_data" in part:
                    inline_data = part["inline_data"]
                    mime_type = inline_data.get("mime_type", "image/png")
                    data = inline_data.get("data", "")
                    if data:
                        # 返回 data URL 格式
                        return f"data:{mime_type};base64,{data}"

                # 检查是否有直接的图片 URL
                if "image_url" in part:
                    return part["image_url"]

            return None

        except Exception as e:
            self.logger.error(f"Failed to extract image from response: {str(e)}")
            return None

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 Gemini 图片生成任务

        注意：这是同步接口，会直接返回结果

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词
                - ratio: 图片比例（如 9:16, 16:9, 1:1）
                - image_path: 输入图片路径（可选，用于图片编辑）
                - image_size: 图片尺寸（1K, 2K, 4K）
                - type: 任务类型（用于选择模型）

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(f"Submitting Gemini Image Preview task: prompt='{ai_tool.prompt[:50] if ai_tool.prompt else ''}...', ratio={ai_tool.ratio}, size={ai_tool.image_size}")

            # 构建请求参数
            request_params = self.build_create_request(ai_tool)

            # 调用 API（同步接口，使用较长的超时时间）
            try:
                result = self._request(timeout=self._timeout, **request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during Gemini task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(f"Gemini Image Preview API response keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")

            # 检查是否有错误
            if "error" in result:
                error_info = result.get("error", {})
                error_msg = error_info.get("message", "未知错误")
                self.logger.warning(f"Gemini Image Preview API returned error: {error_msg}")
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_msg}",
                    "error_type": "USER",
                    "retry": False
                }

            # 提取图片
            image_data = self._extract_image_from_response(result)
            if not image_data:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="Gemini Image Preview API 未返回图片数据",
                    context={
                        "api": "generateContent",
                        "response_keys": list(result.keys()) if isinstance(result, dict) else str(type(result)),
                        "ai_tool_id": ai_tool.id
                    }
                )
                return {
                    "success": False,
                    "error": "服务异常，图片生成失败",
                    "error_type": "SYSTEM",
                    "error_detail": "API 未返回图片数据",
                    "retry": False
                }

            # 同步接口：直接返回成功结果
            # 使用特殊的 project_id 标识这是一个同步完成的任务
            return {
                "success": True,
                "project_id": f"sync_{ai_tool.id}",
                "sync_result": True,
                "result_url": image_data
            }

        except Exception as e:
            self.logger.error(f"Unexpected exception in Gemini Image Preview submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Gemini Image Preview submit_task 发生未预期异常: {str(e)}",
                context={
                    "exception": str(e),
                    "traceback": traceback.format_exc(),
                    "ai_tool_id": ai_tool.id
                }
            )

            return {
                "success": False,
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}",
                "retry": False
            }

    def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        检查 Gemini 任务状态

        注意：Gemini Image Preview 是同步接口，此方法仅用于接口兼容
        如果 submit_task 返回了 sync_result，业务层应直接使用返回的结果

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        # 同步接口：如果进入此方法，说明是兼容模式调用
        # 直接返回成功状态（实际结果在 submit_task 中已返回）
        return {
            "status": "SUCCESS",
            "message": "同步接口已完成"
        }

    def validate_parameters(self, ai_tool) -> tuple[bool, Optional[str]]:
        """
        验证任务参数是否有效

        Args:
            ai_tool: AITool 对象

        Returns:
            tuple[bool, Optional[str]]: (是否有效, 错误信息)
        """
        # 基础验证：必须有提示词（文生图）或图片（图生图/编辑）
        if not ai_tool.prompt and not ai_tool.image_path:
            return False, "缺少提示词或图片"

        # 验证图片尺寸
        valid_sizes = ['1K', '2K', '4K']
        if ai_tool.image_size and ai_tool.image_size not in valid_sizes:
            return False, f"不支持的图片尺寸: {ai_tool.image_size}，支持: {', '.join(valid_sizes)}"

        # 验证宽高比
        valid_ratios = ['9:16', '16:9', '1:1', '3:4', '4:3', '21:9', '1:4', '4:1', '1:8', '8:1']
        if ai_tool.ratio and ai_tool.ratio not in valid_ratios:
            return False, f"不支持的宽高比: {ai_tool.ratio}，支持: {', '.join(valid_ratios)}"

        return True, None


# ============ 具体站点实现类 ============

class GeminiImagePreviewSite1V1Driver(GeminiImagePreviewCommonV1Driver):
    """Gemini Image Preview Site 1 v1 版本驱动"""
    
    def __init__(self):
        super().__init__(site_id="site_1")


class GeminiImagePreviewSite2V1Driver(GeminiImagePreviewCommonV1Driver):
    """Gemini Image Preview Site 2 v1 版本驱动"""
    
    def __init__(self):
        super().__init__(site_id="site_2")


class GeminiImagePreviewSite3V1Driver(GeminiImagePreviewCommonV1Driver):
    """Gemini Image Preview Site 3 v1 版本驱动"""
    
    def __init__(self):
        super().__init__(site_id="site_3")


class GeminiImagePreviewSite4V1Driver(GeminiImagePreviewCommonV1Driver):
    """Gemini Image Preview Site 4 v1 版本驱动"""
    
    def __init__(self):
        super().__init__(site_id="site_4")


class GeminiImagePreviewSite5V1Driver(GeminiImagePreviewCommonV1Driver):
    """Gemini Image Preview Site 5 v1 版本驱动"""
    
    def __init__(self):
        super().__init__(site_id="site_5")
