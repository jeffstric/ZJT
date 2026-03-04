"""
Kling 多米供应商 v1 版本驱动实现
"""
from typing import Dict, Any, Optional
import traceback
from .base_video_driver import BaseVideoDriver
from config.config_util import get_config, get_dynamic_config_value
from utils.sentry_util import SentryUtil, AlertLevel
from utils.image_upload_utils import upload_local_images_to_cdn_sync


class KlingDuomiV1Driver(BaseVideoDriver):
    """
    Kling 多米供应商 v1 版本驱动
    支持图生视频
    """

    def __init__(self):
        super().__init__(driver_name="kling_duomi_v1", driver_type=12)

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
            "code": 0,
            "message": "success",
            "data": {
                "task_id": "task_123456789"
            }
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "code" not in result:
            return False, f"响应缺少 'code' 字段，实际字段: {list(result.keys())}"

        if result.get("code") != 0:
            return True, None  # code != 0 表示业务错误，格式仍然有效

        if "data" not in result:
            return False, f"响应缺少 'data' 字段，实际字段: {list(result.keys())}"

        data = result.get("data")
        if not isinstance(data, dict):
            return False, f"'data' 字段类型错误，期望 dict，实际: {type(data)}"

        if "task_id" not in data:
            return False, f"'data' 缺少 'task_id' 字段，实际字段: {list(data.keys())}"

        if not isinstance(data.get("task_id"), str):
            return False, f"'task_id' 字段类型错误，期望 str，实际: {type(data.get('task_id'))}"

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
            "code": 0,
            "message": "success",
            "data": {
                "task_id": "task_123456789",
                "task_status": "succeed",  # processing, succeed, failed
                "task_result": {
                    "videos": [
                        {
                            "id": "video_id",
                            "url": "https://example.com/video.mp4",
                            "duration": "5"
                        }
                    ]
                }
            }
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "code" not in result:
            return False, f"响应缺少 'code' 字段，实际字段: {list(result.keys())}"

        if result.get("code") != 0:
            return True, None  # code != 0 表示业务错误，格式仍然有效

        if "data" not in result:
            return False, f"响应缺少 'data' 字段，实际字段: {list(result.keys())}"

        data = result.get("data")
        if not isinstance(data, dict):
            return False, f"'data' 字段类型错误，期望 dict，实际: {type(data)}"

        if "task_status" not in data:
            return False, f"'data' 缺少 'task_status' 字段，实际字段: {list(data.keys())}"

        task_status = data.get("task_status")
        if task_status == "succeed":
            if "task_result" not in data:
                return False, "任务成功但缺少 'task_result' 字段"

            task_result = data.get("task_result")
            if not isinstance(task_result, dict):
                return False, f"'task_result' 字段类型错误，期望 dict，实际: {type(task_result)}"

            if "videos" not in task_result:
                return False, "任务成功但 'task_result' 缺少 'videos' 字段"

            videos = task_result.get("videos")
            if not isinstance(videos, list) or len(videos) == 0:
                return False, "任务成功但 'videos' 为空或类型错误"

            if "url" not in videos[0]:
                return False, "视频对象缺少 'url' 字段"

        return True, None

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 Kling 任务的完整请求参数

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # 根据时长确定模式
        mode = "std" if ai_tool.duration == 5 else "pro"

        # 处理图片路径 - 如果是本地环境，上传到图床
        image_path = ai_tool.image_path
        if self._is_local and image_path:
            self.logger.info(f"本地环境检测到图片路径，准备上传到图床: {image_path}")
            cdn_urls = upload_local_images_to_cdn_sync([image_path], self._config)
            self.logger.info(f"图片上传完成，CDN链接: {cdn_urls}")
            if cdn_urls and cdn_urls[0]:
                image_path = cdn_urls[0]

        payload = {
            "model_name": "kling-v2-5-turbo",
            "image": image_path,
            "prompt": ai_tool.prompt,
            "mode": mode,
            "duration": ai_tool.duration or 5,
            "cfg_scale": 0.5
        }

        return {
            "url": f"{self._base_url}/api/video/kling/v1/videos/image2video",
            "method": "POST",
            "json": payload,
            "headers": {
                "Authorization": self._token,
                "Content-Type": "application/json"
            }
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 Kling 任务状态的完整请求参数

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        return {
            "url": f"{self._base_url}/api/video/kling/v1/videos/image2video/{project_id}",
            "method": "GET",
            "json": None,
            "headers": {
                "Authorization": self._token
            }
        }

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 Kling 视频生成任务

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词
                - image_path: 图片路径
                - duration: 视频时长 (5, 10)

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(f"Submitting Kling task: prompt='{ai_tool.prompt[:50]}...', duration={ai_tool.duration}")

            # 构建请求参数
            request_params = self.build_create_request(ai_tool)

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during Kling task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(f"Kling API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                # 格式错误，发送报警，不重试
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Kling submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_kling_image_to_video",
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

            # 检查业务错误
            if result.get("code") != 0:
                error_msg = result.get("message", "未知错误")
                self.logger.warning(f"Kling API returned error: code={result.get('code')}, message={error_msg}")
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_msg}",
                    "error_type": "USER",
                    "retry": False
                }

            task_id = result.get("data", {}).get("task_id")
            if not task_id:
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "Kling API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": task_id
            }

        except Exception as e:
            # 非网络异常，发送报警，不重试
            self.logger.error(f"Unexpected exception in Kling submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Kling submit_task 发生未预期异常: {str(e)}",
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
        检查 Kling 任务状态

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking Kling task status: project_id={project_id}")

            # 构建请求参数并调用统一请求方法
            request_params = self.build_check_query(project_id)

            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during Kling status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            
            self.logger.info(f"Kling status API response: {result}")
            
            # 验证响应格式
            is_valid, validation_error = self._validate_status_response(result)
            if not is_valid:
                # 格式错误，发送报警
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Kling check_status 响应格式错误: {validation_error}",
                    context={
                        "api": "get_kling_task_status",
                        "response": result,
                        "project_id": project_id
                    }
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {validation_error}"
                }
            
            # 检查业务错误
            if result.get("code") != 0:
                error_msg = result.get("message", "未知错误")
                self.logger.warning(f"Kling status API returned error: code={result.get('code')}, message={error_msg}")
                return {
                    "status": "FAILED",
                    "error": f"查询任务状态失败: {error_msg}",
                    "error_type": "SYSTEM"
                }
            
            data = result.get("data", {})
            task_status = data.get("task_status", "")
            
            # 映射 Kling 状态到统一状态
            if task_status == "succeed":
                videos = data.get("task_result", {}).get("videos", [])
                if videos and len(videos) > 0:
                    result_url = videos[0].get("url")
                    return {
                        "status": "SUCCESS",
                        "result_url": result_url
                    }
                else:
                    return {
                        "status": "FAILED",
                        "error": "任务成功但未返回视频URL",
                        "error_type": "SYSTEM"
                    }
            elif task_status == "failed":
                reason = data.get("fail_reason", "任务失败")
                return {
                    "status": "FAILED",
                    "error": reason,
                    "error_type": "USER"
                }
            else:
                # processing 或其他状态
                return {
                    "status": "RUNNING",
                    "message": "任务处理中..."
                }
                
        except Exception as e:
            # 非网络异常，发送报警
            self.logger.error(f"Unexpected exception in Kling check_status: {str(e)}")
            self.logger.error(traceback.format_exc())
            
            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Kling check_status 发生未预期异常: {str(e)}",
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
