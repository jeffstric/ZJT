"""
VEO3 通用聚合站点 v1 版本驱动实现
支持多个站点配置，使用基类+站点类的架构
"""
from typing import Dict, Any, Optional
import traceback
from .base_video_driver import BaseVideoDriver, ImageMode
from config.config_util import get_config, get_dynamic_config_value
from utils.sentry_util import SentryUtil, AlertLevel
from utils.image_upload_utils import upload_local_images_to_cdn_sync


class Veo3CommonV1Driver(BaseVideoDriver):
    """
    VEO3 通用聚合站点 v1 版本驱动（基类）
    支持图生视频，使用 veo3.1-fast 模型

    特点：
    - 支持多个站点配置（通过 site_id 区分）
    - 从 api_aggregator.{site_id} 加载配置
    - 支持首尾帧和多参考图模式

    注意：这是基类，不应该直接实例化，应该使用具体的站点类
    """

    def __init__(self, site_id: str):
        """
        初始化驱动（基类）

        Args:
            site_id: API 聚合站点ID（如 site_1, site_2, ... site_5）
                     对应配置 api_aggregator.site_X
        """
        self._site_id = site_id
        driver_name = f"veo3_common_{site_id}"
        super().__init__(driver_name=driver_name, driver_type=15)

        # 从 api_aggregator.{site_id} 加载配置
        self._api_key = get_dynamic_config_value("api_aggregator", site_id, "api_key", default="")
        self._base_url = get_dynamic_config_value("api_aggregator", site_id, "base_url", default="https://yunwu.ai")
        self._site_name = get_dynamic_config_value("api_aggregator", site_id, "name", default=site_id)
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        # 是否为本地环境
        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        self._validate_required({
            f"API Aggregator {site_id} API Key": self._api_key,
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

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 submit_task API 响应格式

        Args:
            result: API 响应结果

        Returns:
            tuple[bool, Optional[str]]: (是否有效, 错误信息)

        期望的响应格式（OpenAI 风格）:
        {
            "id": "chatcmpl-xxxx",
            "object": "video.completion",
            "created": 1234567890,
            "choices": [...],
            "usage": {...}
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "id" not in result:
            return False, f"响应缺少 'id' 字段，实际字段: {list(result.keys())}"

        if not isinstance(result.get("id"), str):
            return False, f"'id' 字段类型错误，期望 str，实际: {type(result.get('id'))}"

        return True, None

    def _validate_status_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 check_status API 响应格式

        Args:
            result: API 响应结果

        Returns:
            tuple[bool, Optional[str]]: (是否有效, 错误信息)

        期望的响应格式:
        {
            "id": "chatcmpl-xxxx",
            "status": "completed" / "processing" / "failed",
            "output": {
                "video": {"url": "https://..."}
            }
        }
        或 OpenAI 风格带 choices 的格式
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "id" not in result:
            return False, f"响应缺少 'id' 字段，实际字段: {list(result.keys())}"

        return True, None

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 VEO3 任务的完整请求参数

        支持三种图片模式：
        - first_last_frame: 首尾帧模式，传入1~2张图片
        - multi_reference: 多参考图模式，最多3张
        - first_last_with_ref: 首尾帧+参考图模式，优先使用首尾帧

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # 解析图片模式
        image_info = self.get_all_images_by_mode(ai_tool)
        mode = image_info['mode']
        first_frame = image_info['first_frame']
        last_frame = image_info['last_frame']
        reference_images = image_info['reference_images']

        self.logger.info(f"VEO3 yw驱动图片模式: {mode}, 首帧: {first_frame}, 尾帧: {last_frame}, 参考图: {len(reference_images)}张")

        # 根据模式构建图片列表
        image_urls = []

        if mode == ImageMode.FIRST_LAST_FRAME:
            if first_frame:
                image_urls.append(first_frame)
            if last_frame:
                image_urls.append(last_frame)
        elif mode == ImageMode.MULTI_REFERENCE:
            if reference_images:
                image_urls = reference_images[:3]
                if len(reference_images) > 3:
                    self.logger.warning(f"yw VEO3 最多支持3张参考图，已截取前3张")
        elif mode == ImageMode.FIRST_LAST_WITH_REF:
            if first_frame or last_frame:
                if first_frame:
                    image_urls.append(first_frame)
                if last_frame:
                    image_urls.append(last_frame)
                if reference_images:
                    self.logger.warning(f"yw VEO3 首尾帧+参考图模式，已使用首尾帧，忽略 {len(reference_images)} 张参考图")
            elif reference_images:
                image_urls = reference_images[:3]

        # 如果是本地环境，将本地图片上传到图床
        if self._is_local and image_urls:
            self.logger.info(f"本地环境检测到图片路径，准备上传到图床: {image_urls}")
            cdn_urls = upload_local_images_to_cdn_sync(image_urls, self._config)
            self.logger.info(f"图片上传完成，CDN链接: {cdn_urls}")
            if cdn_urls:
                image_urls = cdn_urls

        payload = {
            "model": "veo3.1-fast",
            "prompt": ai_tool.prompt,
            "aspect_ratio": ai_tool.ratio or "9:16",
            "enhance_prompt": True,
        }

        if image_urls:
            payload["images"] = image_urls

        return {
            "url": f"{self._base_url}/v1/video/create",
            "method": "POST",
            "json": payload,
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            }
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 VEO3 任务状态的完整请求参数

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        return {
            "url": f"{self._base_url}/v1/video/query",
            "method": "GET",
            "params": {"id": project_id},
            "json": None,
            "headers": {
                "Authorization": f"Bearer {self._api_key}"
            }
        }

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 VEO3 视频生成任务

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词
                - ratio: 视频比例
                - image_path: 图片路径

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(f"Submitting VEO3 yunwu task: prompt='{ai_tool.prompt[:50]}...'")

            # 构建请求参数
            request_params = self.build_create_request(ai_tool)

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during VEO3 yunwu task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(f"VEO3 yunwu API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"VEO3 yunwu submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "v1/video/create",
                        "response": result,
                        "ai_tool_id": ai_tool.id
                    }
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {validation_error}",
                    "retry": False
                }

            project_id = result.get("id")
            if not project_id:
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "VEO3 yunwu API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": project_id
            }

        except Exception as e:
            self.logger.error(f"Unexpected exception in VEO3 yunwu submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"VEO3 yunwu submit_task 发生未预期异常: {str(e)}",
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
        检查 VEO3 任务状态

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking VEO3 yunwu task status: project_id={project_id}")

            # 构建请求参数并调用统一请求方法
            request_params = self.build_check_query(project_id)

            try:
                raw_result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during VEO3 yunwu status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            self.logger.info(f"VEO3 yunwu status API response: {raw_result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_status_response(raw_result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"VEO3 yunwu check_status 响应格式错误: {validation_error}",
                    context={
                        "api": "v1/video/status",
                        "response": raw_result,
                        "project_id": project_id
                    }
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {validation_error}"
                }

            # 解析状态 - 适配 OpenAI 风格或直接状态字段
            # 尝试多种响应格式
            status_value = raw_result.get("status", "")
            result_data = raw_result

            # 格式1: 直接 status 字段 (completed / processing / failed)
            if status_value:
                if status_value in ("completed", "COMPLETED", "success", "SUCCESS"):
                    # 尝试从 output.video.url 或 choices 中提取视频URL
                    video_url = self._extract_video_url(result_data)
                    if video_url:
                        return {
                            "status": "SUCCESS",
                            "result_url": video_url
                        }
                    else:
                        return {
                            "status": "FAILED",
                            "error": "任务完成但未找到视频URL",
                            "error_type": "SYSTEM"
                        }
                elif status_value in ("failed", "FAILED", "error", "ERROR"):
                    error_msg = raw_result.get("error", raw_result.get("message", "任务失败"))
                    return {
                        "status": "FAILED",
                        "error": error_msg,
                        "error_type": "USER"
                    }
                else:
                    # processing / in_queue / in_progress 等
                    return {
                        "status": "RUNNING",
                        "message": "任务处理中..."
                    }

            # 格式2: OpenAI choices 风格
            choices = raw_result.get("choices", [])
            if choices:
                choice = choices[0]
                message = choice.get("message", {})
                content = message.get("content", "")
                finish_reason = choice.get("finish_reason", "")

                if finish_reason == "stop" and content:
                    # 可能 content 就是视频URL，或者需要解析
                    return {
                        "status": "SUCCESS",
                        "result_url": content
                    }
                elif finish_reason == "error":
                    return {
                        "status": "FAILED",
                        "error": content or "任务失败",
                        "error_type": "USER"
                    }
                else:
                    return {
                        "status": "RUNNING",
                        "message": "任务处理中..."
                    }

            # 无法识别的格式，视为处理中
            self.logger.warning(f"无法识别的 yunwu 状态响应格式: {raw_result}")
            return {
                "status": "RUNNING",
                "message": "任务处理中..."
            }

        except Exception as e:
            self.logger.error(f"Unexpected exception in VEO3 yunwu check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"VEO3 yunwu check_status 发生未预期异常: {str(e)}",
                context={
                    "exception": str(e),
                    "traceback": traceback.format_exc(),
                    "project_id": project_id
                }
            )

            return {
                "status": "FAILED",
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}"
            }

    def _extract_video_url(self, data: dict) -> Optional[str]:
        """
        从响应数据中提取视频URL
        尝试多种可能的路径

        Args:
            data: 响应数据

        Returns:
            视频URL或None
        """
        # 路径0: detail.video_url
        detail = data.get("detail", {})
        if isinstance(detail, dict):
            url = detail.get("video_url")
            if url:
                return url

        # 路径1: output.video.url
        output = data.get("output", {})
        if isinstance(output, dict):
            video = output.get("video", {})
            if isinstance(video, dict):
                url = video.get("url")
                if url:
                    return url

        # 路径2: data.video.url
        result_data = data.get("data", {})
        if isinstance(result_data, dict):
            video = result_data.get("video", {})
            if isinstance(video, dict):
                url = video.get("url")
                if url:
                    return url
            # 路径3: data.mediaUrl
            media_url = result_data.get("mediaUrl")
            if media_url:
                return media_url

        # 路径4: 直接 video.url
        video = data.get("video", {})
        if isinstance(video, dict):
            url = video.get("url")
            if url:
                return url

        # 路径5: choices[0].message.content
        choices = data.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            if content and (content.startswith("http://") or content.startswith("https://")):
                return content

        # 路径6: 根级别 video_url
        url = data.get("video_url")
        if url:
            return url

        return None


# ============ 具体站点实现类 ============

class Veo3CommonSite1V1Driver(Veo3CommonV1Driver):
    """VEO3 通用聚合 Site 1 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_1")


class Veo3CommonSite2V1Driver(Veo3CommonV1Driver):
    """VEO3 通用聚合 Site 2 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_2")


class Veo3CommonSite3V1Driver(Veo3CommonV1Driver):
    """VEO3 通用聚合 Site 3 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_3")


class Veo3CommonSite4V1Driver(Veo3CommonV1Driver):
    """VEO3 通用聚合 Site 4 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_4")


class Veo3CommonSite5V1Driver(Veo3CommonV1Driver):
    """VEO3 通用聚合 Site 5 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_5")


class Veo3CommonSite0V1Driver(Veo3CommonV1Driver):
    """VEO3 通用聚合 Site 0 v1 版本驱动

    智剧通API官方站点，对应配置 api_aggregator.site_0
    """

    def __init__(self):
        super().__init__(site_id="site_0")
