"""
Sora2 多米供应商 v1 版本驱动实现
"""
from typing import Dict, Any, Optional
import traceback
import os
import yaml
from .base_video_driver import BaseVideoDriver
from config_util import get_config_path
from utils.sentry_util import SentryUtil, AlertLevel


class Sora2DuomiV1Driver(BaseVideoDriver):
    """
    Sora2 多米供应商 v1 版本驱动
    支持文生视频和图生视频
    """
    
    def __init__(self):
        super().__init__(driver_name="sora2_duomi_v1", driver_type=3)
        
        # 加载配置
        config_path = get_config_path()
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)
        
        self._token = config["duomi"]["token"]
        self._base_url = "https://duomiapi.com"
        self._timeout = config["timeout"]["request_timeout"]
    
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
            "id": "task_123456789"  # 任务ID，字符串类型
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
        
        期望的正确响应格式 (get_ai_task_result 统一格式):
        {
            "code": 0,           # 0-成功, 非0-错误
            "msg": "success",    # 消息
            "data": {
                "status": 0,     # 0-处理中, 1-成功, 2-失败
                "mediaUrl": "https://example.com/video.mp4",  # status=1时必须存在
                "reason": "失败原因"  # status=2时的失败原因
            }
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"
        
        if "code" not in result:
            return False, f"响应缺少 'code' 字段，实际字段: {list(result.keys())}"
        
        if "msg" not in result:
            return False, f"响应缺少 'msg' 字段，实际字段: {list(result.keys())}"
        
        if "data" not in result:
            return False, f"响应缺少 'data' 字段，实际字段: {list(result.keys())}"
        
        data = result.get("data")
        if not isinstance(data, dict):
            return False, f"'data' 字段类型错误，期望 dict，实际: {type(data)}"
        
        if "status" not in data:
            return False, f"'data' 缺少 'status' 字段，实际字段: {list(data.keys())}"
        
        task_status = data.get("status")
        if not isinstance(task_status, int):
            return False, f"'status' 字段类型错误，期望 int，实际: {type(task_status)}"
        
        # 验证 status 值的有效性
        if task_status not in [0, 1, 2]:
            return False, f"'status' 值无效，期望 0/1/2，实际: {task_status}"
        
        # 当任务成功时，必须有 mediaUrl
        if task_status == 1:
            if "mediaUrl" not in data:
                return False, "任务成功但缺少 'mediaUrl' 字段"
            if not data.get("mediaUrl"):
                return False, "任务成功但 'mediaUrl' 为空"
        
        return True, None
    
    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 Sora2 任务的完整请求参数
        
        Args:
            ai_tool: AITool 对象
        
        Returns:
            Dict[str, Any]: 请求参数字典
        """
        payload = {
            "model": "sora-2-temporary",
            "prompt": ai_tool.prompt,
            "aspect_ratio": ai_tool.ratio or "9:16",
            "duration": ai_tool.duration or 15,
            "image_urls": [ai_tool.image_path]
        }
        
        return {
            "url": f"{self._base_url}/v1/videos/generations",
            "method": "POST",
            "json": payload,
            "headers": {
                "Content-Type": "application/json",
                "Authorization": self._token
            }
        }
    
    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 Sora2 任务状态的完整请求参数
        
        Args:
            project_id: 任务ID
        
        Returns:
            Dict[str, Any]: 请求参数字典
        """
        return {
            "url": f"{self._base_url}/v1/videos/tasks/{project_id}",
            "method": "GET",
            "json": None,
            "headers": {
                "Authorization": self._token
            }
        }
    
    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 Sora2 视频生成任务
        
        Args:
            ai_tool: AITool 对象
                - prompt: 提示词
                - ratio: 视频比例 (9:16, 16:9)
                - image_path: 图片路径（可选，图生视频时使用）
                - duration: 视频时长 (10, 15)
        
        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(f"Submitting Sora2 task: prompt='{ai_tool.prompt[:50]}...', ratio={ai_tool.ratio}, duration={ai_tool.duration}")
            
            # 构建请求参数
            request_params = self.build_create_request(ai_tool)
            
            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during Sora2 task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }
            
            self.logger.info(f"Sora2 API response: {result}")
            
            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                # 格式错误，发送报警，不重试
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Sora2 submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_image_to_video",
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
                    "error_detail": "Sora2 API未返回任务ID",
                    "retry": False
                }
            
            return {
                "success": True,
                "project_id": project_id
            }
            
        except Exception as e:
            # 非网络异常，发送报警，不重试
            self.logger.error(f"Unexpected exception in Sora2 submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())
            
            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Sora2 submit_task 发生未预期异常: {str(e)}",
                context={
                    "exception_type": type(e).__name__,
                    "traceback": traceback.format_exc(),
                    "ai_tool_id": ai_tool.id
                }
            )
            
            return {
                "success": False,
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"系统异常: {str(e)}",
                "retry": False
            }
    
    def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        检查 Sora2 任务状态
        
        Args:
            project_id: Sora2 任务ID
        
        Returns:
            Dict[str, Any]: 任务状态
        """
        try:
            # 构建请求参数并调用统一请求方法
            request_params = self.build_check_query(project_id)
            
            try:
                raw_result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，返回 RUNNING 状态，允许重试
                self.logger.warning(f"Network error during Sora2 status check: {str(network_error)}")
                return {
                    "status": "RUNNING"
                }
            
            # 规范化响应格式（从原始API响应转换为统一格式）
            state = raw_result.get("state", "")
            message = raw_result.get("message", "")
            
            if state == "succeeded":
                status = 1
                media_url = None
                videos = raw_result.get("data", {}).get("videos", [])
                if videos and len(videos) > 0:
                    media_url = videos[0].get("url")
                
                result = {
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "status": status,
                        "mediaUrl": media_url,
                        "reason": None
                    }
                }
            elif state == "error":
                result = {
                    "code": 1,
                    "msg": message or "任务失败",
                    "data": {
                        "status": 2,
                        "mediaUrl": None,
                        "reason": message
                    }
                }
            else:
                # processing 或其他状态
                result = {
                    "code": 0,
                    "msg": "processing",
                    "data": {
                        "status": 0,
                        "mediaUrl": None,
                        "reason": None
                    }
                }
            
            # 验证响应格式
            is_valid, validation_error = self._validate_status_response(result)
            if not is_valid:
                # 格式错误，发送报警，标记为失败，不重试
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Sora2 check_status 响应格式错误: {validation_error}",
                    context={
                        "api": "get_ai_task_result",
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
            
            if result.get("code") != 0:
                error_msg = result.get("msg", "Unknown error")
                self.logger.error(f"Failed to get task result: {error_msg}")
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": error_msg
                }
            
            data = result.get("data", {})
            task_status = data.get("status")  # 0-进行中 1-成功 2-失败
            media_url = data.get("mediaUrl")
            reason = data.get("reason")
            
            if task_status == 1:
                # 成功状态，验证是否有结果URL
                if not media_url:
                    self._send_alert(
                        alert_type="INVALID_RESPONSE_FORMAT",
                        message="Sora2 任务成功但缺少 mediaUrl",
                        context={
                            "project_id": project_id,
                            "response": result
                        }
                    )
                    return {
                        "status": "FAILED",
                        "error": "服务异常，请联系技术支持",
                        "error_type": "SYSTEM",
                        "error_detail": "任务成功但未返回视频URL"
                    }
                
                return {
                    "status": "SUCCESS",
                    "result_url": media_url
                }
            elif task_status == 2:
                # 翻译错误信息
                user_error = reason
                if reason and "We currently do not support uploads of images containing photorealistic people" in reason:
                    user_error = "图片包含真人，无法处理"
                elif reason and "This content may violate our guardrails concerning similarity to third-party content." in reason:
                    user_error = "此内容可能违反了我们关于与第三方内容相似性的规定"
                
                return {
                    "status": "FAILED",
                    "error": user_error or "任务失败",
                    "error_type": "USER"
                }
            else:
                # 处理中或其他状态
                return {
                    "status": "RUNNING"
                }
                
        except (ConnectionError, TimeoutError):
            # 网络异常已在内层处理，这里不应该到达
            raise
        except Exception as e:
            # 非网络异常，发送报警，标记为失败，不重试
            self.logger.error(f"Unexpected exception in Sora2 check_status: {str(e)}")
            self.logger.error(traceback.format_exc())
            
            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Sora2 check_status 发生未预期异常: {str(e)}",
                context={
                    "exception_type": type(e).__name__,
                    "traceback": traceback.format_exc(),
                    "project_id": project_id
                }
            )
            
            return {
                "status": "FAILED",
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"系统异常: {str(e)}"
            }
    
    def validate_parameters(self, ai_tool) -> tuple[bool, str]:
        """
        验证 Sora2 任务参数
        
        Args:
            ai_tool: AITool 对象
        
        Returns:
            tuple[bool, str]: (是否有效, 错误信息)
        """
        # 调用基类验证
        is_valid, error = super().validate_parameters(ai_tool)
        if not is_valid:
            return is_valid, error
        
        # Sora2 特定验证
        valid_ratios = ["9:16", "16:9"]
        if ai_tool.ratio and ai_tool.ratio not in valid_ratios:
            return False, f"Sora2 不支持的比例: {ai_tool.ratio}，有效值: {valid_ratios}"
        
        valid_durations = [10, 15]
        if ai_tool.duration and ai_tool.duration not in valid_durations:
            return False, f"Sora2 不支持的时长: {ai_tool.duration}秒，有效值: {valid_durations}"
        
        return True, None
