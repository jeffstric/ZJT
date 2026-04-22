"""
GPT Image 2 多米供应商 v1 版本驱动实现
支持文生图任务，基于多米 API 平台
"""
from typing import Dict, Any, Optional
import traceback
from .base_video_driver import BaseVideoDriver
from config.config_util import get_config, get_dynamic_config_value
from utils.sentry_util import SentryUtil, AlertLevel
from utils.image_upload_utils import upload_local_images_to_cdn_sync


class GptImageDuomiV1Driver(BaseVideoDriver):
    """
    GPT Image 2 多米供应商 v1 版本驱动
    支持文生图任务
    """

    # 比例映射：前端比例 -> API 支持的比例
    # API 仅支持 1:1, 3:2, 2:3，需要将 16:9 映射为 3:2，9:16 映射为 2:3
    RATIO_MAPPING = {
        '1:1': '1:1',
        '2:3': '2:3',
        '3:2': '3:2',
        '16:9': '3:2',  # 兼容映射
        '9:16': '2:3',  # 兼容映射
    }

    # 默认模型
    DEFAULT_MODEL = "gpt-image-2"

    def __init__(self, driver_type: int = 25):
        super().__init__(driver_name="gpt_image_duomi_v1", driver_type=driver_type)

        # 加载配置
        self._token = get_dynamic_config_value("duomi", "token", default="")
        self._base_url = "https://duomiapi.com"
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        # 是否为本地环境
        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        self._validate_required({
            "Duomi API Token": self._token,
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

        期望的正确响应格式:
        {
            "id": "task_123456789",
            "state": "pending",
            ...
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "id" not in result:
            return False, f"响应缺少 'id' 字段，实际字段: {list(result.keys())}"

        return True, None

    def _validate_status_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 check_status API 响应格式

        Args:
            result: API 响应结果

        Returns:
            tuple[bool, Optional[str]]: (是否有效, 错误信息)

        期望的正确响应格式:
        {
            "id": "task_123",
            "state": "succeeded",
            "data": {
                "images": [{"url": "...", "file_name": "..."}]
            },
            ...
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "id" not in result:
            return False, f"响应缺少 'id' 字段，实际字段: {list(result.keys())}"

        if "state" not in result:
            return False, f"响应缺少 'state' 字段，实际字段: {list(result.keys())}"

        return True, None

    def _map_ratio(self, ratio: str) -> str:
        """
        将前端比例映射为 API 支持的比例

        Args:
            ratio: 前端传入的比例，如 "1:1", "16:9", "9:16"

        Returns:
            API 支持的比例
        """
        mapped = self.RATIO_MAPPING.get(ratio)
        if mapped:
            return mapped
        # 默认返回 1:1
        self.logger.warning(f"未知的比例 '{ratio}'，使用默认比例 1:1")
        return "1:1"

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 GPT Image 2 任务的完整请求参数

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # 准备图片URL列表 - 支持参考图（可选）
        image_urls = None
        if ai_tool.image_path:
            image_urls = ai_tool.image_path.split(',') if ',' in ai_tool.image_path else [ai_tool.image_path]

        # 如果是本地环境，将本地图片上传到图床
        if self._is_local and image_urls:
            self.logger.info(f"本地环境检测到图片路径，准备上传到图床: {image_urls}")
            image_urls = upload_local_images_to_cdn_sync(image_urls, self._config)
            self.logger.info(f"图片上传完成，CDN链接: {image_urls}")

        # 映射比例
        api_ratio = self._map_ratio(ai_tool.ratio or "1:1")

        payload = {
            "model": self.DEFAULT_MODEL,
            "prompt": ai_tool.prompt,
            "size": api_ratio,
        }

        # 添加参考图（如果有）
        if image_urls:
            payload["image"] = image_urls

        return {
            "url": f"{self._base_url}/v1/images/generations?async=true",
            "method": "POST",
            "json": payload,
            "headers": {
                "Content-Type": "application/json",
                "Authorization": self._token
            }
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 GPT Image 2 任务状态的完整请求参数

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        return {
            "url": f"{self._base_url}/v1/tasks/{project_id}",
            "method": "GET",
            "json": None,
            "headers": {
                "Authorization": self._token
            }
        }

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 GPT Image 2 图片生成任务

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词
                - ratio: 图片比例（支持 1:1, 2:3, 3:2, 16:9, 9:16）
                - image_path: 输入图片路径（可选，作为参考图）

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(f"Submitting GPT Image 2 task: prompt='{ai_tool.prompt[:50]}...', ratio={ai_tool.ratio}")

            # 构建请求参数
            request_params = self.build_create_request(ai_tool)

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during GPT Image 2 task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(f"GPT Image 2 API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                # 格式错误，发送报警，不重试
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"GPT Image 2 submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_image",
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

            task_id = result.get("id")
            if not task_id:
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "GPT Image 2 API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": task_id
            }

        except Exception as e:
            # 非网络异常，发送报警，不重试
            self.logger.error(f"Unexpected exception in GPT Image 2 submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"GPT Image 2 submit_task 发生未预期异常: {str(e)}",
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
        检查 GPT Image 2 任务状态

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking GPT Image 2 task status: project_id={project_id}")

            # 构建请求参数并调用统一请求方法
            request_params = self.build_check_query(project_id)

            try:
                raw_result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during GPT Image 2 status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            self.logger.info(f"GPT Image 2 status API response: {raw_result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_status_response(raw_result)
            if not is_valid:
                # 格式错误，发送报警
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"GPT Image 2 check_status 响应格式错误: {validation_error}",
                    context={
                        "api": "get_task_status",
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

            # 解析状态
            state = raw_result.get("state", "")

            if state == "succeeded":
                # 成功，获取图片URL
                data = raw_result.get("data", {})
                images = data.get("images", [])
                if images and len(images) > 0:
                    media_url = images[0].get("url")
                    return {
                        "status": "SUCCESS",
                        "result_url": media_url
                    }
                else:
                    return {
                        "status": "FAILED",
                        "error": "任务成功但未返回图片URL",
                        "error_type": "SYSTEM"
                    }
            elif state == "error":
                # 失败
                return {
                    "status": "FAILED",
                    "error": "图片生成失败",
                    "error_type": "USER"
                }
            elif state in ["pending", "running"]:
                # 处理中
                return {
                    "status": "RUNNING",
                    "message": "任务处理中..."
                }
            else:
                # 未知状态
                self.logger.warning(f"Unknown state: {state}")
                return {
                    "status": "RUNNING",
                    "message": "任务处理中..."
                }

        except Exception as e:
            # 非网络异常，发送报警
            self.logger.error(f"Unexpected exception in GPT Image 2 check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"GPT Image 2 check_status 发生未预期异常: {str(e)}",
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
