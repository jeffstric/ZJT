"""
Vidu Q2 驱动实现
使用 viduq2 模型
"""
from typing import Dict, Any, Optional
import traceback
from .base_video_driver import BaseVideoDriver, ImageMode
from config.config_util import get_config, get_dynamic_config_value
from utils.sentry_util import SentryUtil, AlertLevel
from utils.image_upload_utils import upload_local_images_to_cdn_sync


class ViduQ2Driver(BaseVideoDriver):
    """
    Vidu Q2 驱动
    使用 viduq2 模型进行图生视频
    """

    def __init__(self):
        super().__init__(driver_name="vidu_q2", driver_type=14)

        # 加载配置
        self._api_key = get_dynamic_config_value("vidu", "token", default="")
        self._base_url = "https://api.vidu.cn"
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        # 是否为本地环境
        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()
        
        self._validate_required({
            "Vidu API Token": self._api_key,
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
            "task_id": "task_123456789",
            "state": "created",  # created, queueing, processing, success, failed
            "model": "viduq2",
            "credits": 4,
            ...
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        # 检查是否有错误
        if "error" in result:
            return True, None  # 有错误字段，格式有效但业务失败

        if "task_id" not in result:
            return False, f"响应缺少 'task_id' 字段，实际字段: {list(result.keys())}"

        if not isinstance(result.get("task_id"), str):
            return False, f"'task_id' 字段类型错误，期望 str，实际: {type(result.get('task_id'))}"

        if "state" not in result:
            return False, f"响应缺少 'state' 字段，实际字段: {list(result.keys())}"

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
            "id": "916920905987280896",
            "state": "processing",  # created, queueing, processing, success, failed
            "err_code": "",
            "creations": [],  # 处理中时为空，完成后包含结果
            "credits": 4,
            "payload": "",
            ...
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        # 检查是否有错误
        if "error" in result:
            return True, None  # 有错误字段，格式有效但业务失败

        if "id" not in result:
            return False, f"响应缺少 'id' 字段，实际字段: {list(result.keys())}"

        if "state" not in result:
            return False, f"响应缺少 'state' 字段，实际字段: {list(result.keys())}"

        if "creations" not in result:
            return False, f"响应缺少 'creations' 字段，实际字段: {list(result.keys())}"

        task_state = result.get("state")
        if task_state == "success":
            creations = result.get("creations")
            if not isinstance(creations, list):
                return False, "任务成功但 'creations' 类型错误"

            # creations 可以为空列表（表示任务完成但没有结果）
            if len(creations) > 0 and "url" not in creations[0]:
                return False, "创作对象缺少 'url' 字段"

        return True, None

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 Vidu Q2 任务的完整请求参数
        
        仅支持参考图生视频模式 (reference2video)

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # 解析图片模式，收集所有图片
        image_info = self.get_all_images_by_mode(ai_tool)
        first_frame = image_info['first_frame']
        last_frame = image_info['last_frame']
        reference_images = image_info['reference_images']
        
        # 收集所有可用图片作为参考图
        image_urls = []
        if first_frame:
            image_urls.append(first_frame)
        if last_frame:
            image_urls.append(last_frame)
        if reference_images:
            image_urls.extend(reference_images)
        
        self.logger.info(f"Vidu Q2 驱动参考图模式，图片数量: {len(image_urls)}")
        
        if not image_urls:
            raise ValueError("Vidu Q2 任务需要至少1张参考图")

        # 如果是本地环境，将本地图片上传到图床
        if self._is_local and image_urls:
            self.logger.info(f"本地环境检测到图片路径，准备上传到图床: {image_urls}")
            image_urls = upload_local_images_to_cdn_sync(image_urls, self._config)
            self.logger.info(f"图片上传完成，CDN链接: {image_urls}")

        # 构建 subjects 数组，所有图片作为一个 subject
        subject_id = "subject1"
        subjects = [
            {
                "id": subject_id,
                "images": image_urls,
                "voice_id": ""
            }
        ]
        
        # 在 prompt 前添加 subject 引用
        prompt = ai_tool.prompt or ""
        if not prompt.startswith(f"@{subject_id}"):
            prompt = f"@{subject_id} {prompt}"

        payload = {
            "model": "viduq2",
            "subjects": subjects,
            "prompt": prompt,
            "duration": ai_tool.duration or 8,
            "audio": True
        }

        return {
            "url": f"{self._base_url}/ent/v2/reference2video",
            "method": "POST",
            "json": payload,
            "headers": {
                "Authorization": f"Token {self._api_key}",
                "Content-Type": "application/json"
            }
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 Vidu Q2 任务状态的完整请求参数

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        return {
            "url": f"{self._base_url}/ent/v2/tasks/{project_id}/creations",
            "method": "GET",
            "json": None,
            "headers": {
                "Authorization": f"Token {self._api_key}",
                "Content-Type": "application/json"
            }
        }

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 Vidu Q2 视频生成任务

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词
                - reference_images: 参考图路径
                - duration: 视频时长 (5, 8)

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            # 解析图片路径进行验证（优先使用 reference_images，其次使用 image_path）
            image_urls = []
            
            # 检查 reference_images 字段
            if hasattr(ai_tool, 'reference_images') and ai_tool.reference_images:
                if isinstance(ai_tool.reference_images, str):
                    image_urls = [url.strip() for url in ai_tool.reference_images.split(',') if url.strip()]
                else:
                    image_urls = ai_tool.reference_images
            
            # 如果 reference_images 为空，尝试使用 image_path
            if not image_urls and ai_tool.image_path:
                if isinstance(ai_tool.image_path, str):
                    image_urls = [url.strip() for url in ai_tool.image_path.split(',') if url.strip()]
                else:
                    image_urls = ai_tool.image_path

            if not image_urls:
                return {
                    "success": False,
                    "error": "缺少参考图片",
                    "error_type": "USER",
                    "retry": False
                }

            self.logger.info(f"Submitting Vidu Q2 task: prompt='{ai_tool.prompt[:50]}...', duration={ai_tool.duration}, images={len(image_urls)}")

            # 构建请求参数
            try:
                request_params = self.build_create_request(ai_tool)
            except ValueError as e:
                return {
                    "success": False,
                    "error": str(e),
                    "error_type": "USER",
                    "retry": False
                }

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during Vidu Q2 task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(f"Vidu Q2 API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                # 格式错误，发送报警，不重试
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Vidu Q2 submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_vidu_q2_image_to_video",
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
            if "error" in result:
                error_msg = result.get("error", "未知错误")
                self.logger.warning(f"Vidu Q2 API returned error: {error_msg}")
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_msg}",
                    "error_type": "USER",
                    "retry": False
                }

            task_id = result.get("task_id")
            if not task_id:
                # task_id 已在 _validate_submit_response 中验证，这里理论上不会发生
                self._send_alert(
                    alert_type="MISSING_TASK_ID",
                    message="Vidu Q2 submit_task 响应缺少 task_id",
                    context={
                        "api": "create_vidu_q2_image_to_video",
                        "response": result,
                        "ai_tool_id": ai_tool.id
                    }
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "Vidu Q2 API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": task_id
            }

        except Exception as e:
            # 非网络异常，发送报警，不重试
            self.logger.error(f"Unexpected exception in Vidu Q2 submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Vidu Q2 submit_task 发生未预期异常: {str(e)}",
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
        检查 Vidu Q2 任务状态

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking Vidu Q2 task status: project_id={project_id}")

            # 构建请求参数并调用统一请求方法
            request_params = self.build_check_query(project_id)

            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during Vidu Q2 status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            
            self.logger.info(f"Vidu Q2 status API response: {result}")
            
            # 验证响应格式
            is_valid, validation_error = self._validate_status_response(result)
            if not is_valid:
                # 格式错误，发送报警
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Vidu Q2 check_status 响应格式错误: {validation_error}",
                    context={
                        "api": "get_vidu_q2_task_status",
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
            if "error" in result:
                error_msg = result.get("error", "未知错误")
                self.logger.warning(f"Vidu Q2 status API returned error: {error_msg}")
                return {
                    "status": "FAILED",
                    "error": f"查询任务状态失败: {error_msg}",
                    "error_type": "SYSTEM"
                }
            
            task_state = result.get("state", "")
            
            # 映射 Vidu 状态到统一状态
            if task_state == "success":
                creations = result.get("creations", [])
                if creations and len(creations) > 0:
                    result_url = creations[0].get("url")
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
            elif task_state == "failed":
                error_code = result.get("err_code", "任务失败")
                return {
                    "status": "FAILED",
                    "error": error_code,
                    "error_type": "USER"
                }
            elif task_state in ["created", "queueing", "processing"]:
                # 任务创建、排队或处理中
                return {
                    "status": "RUNNING",
                    "message": "任务处理中..."
                }
            else:
                # 未知状态
                self.logger.warning(f"Unknown Vidu Q2 task state: {task_state}")
                return {
                    "status": "RUNNING",
                    "message": f"任务状态: {task_state}"
                }
                
        except Exception as e:
            # 非网络异常，发送报警
            self.logger.error(f"Unexpected exception in Vidu Q2 check_status: {str(e)}")
            self.logger.error(traceback.format_exc())
            
            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Vidu Q2 check_status 发生未预期异常: {str(e)}",
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
