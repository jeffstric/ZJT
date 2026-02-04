"""
Sora2 视频生成驱动实现
"""
from typing import Dict, Any, Optional
import traceback
from .base_video_driver import BaseVideoDriver
from duomi_api_requset import create_image_to_video, get_ai_task_result
from utils.sentry_util import SentryUtil, AlertLevel


class Sora2VideoDriver(BaseVideoDriver):
    """
    Sora2 视频生成驱动
    支持文生视频和图生视频
    """
    
    def __init__(self):
        super().__init__(driver_name="sora2", driver_type=3)
    
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
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"
        
        if "code" not in result:
            return False, f"响应缺少 'code' 字段，实际字段: {list(result.keys())}"
        
        if result.get("code") == 0:
            if "data" not in result:
                return False, "响应缺少 'data' 字段"
            
            data = result.get("data")
            if not isinstance(data, dict):
                return False, f"'data' 字段类型错误，期望 dict，实际: {type(data)}"
            
            if "status" not in data:
                return False, f"'data' 缺少 'status' 字段，实际字段: {list(data.keys())}"
            
            task_status = data.get("status")
            if task_status == 1:
                if "mediaUrl" not in data:
                    return False, "任务成功但缺少 'mediaUrl' 字段"
        
        return True, None
    
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
            
            # 调用外部 API
            try:
                result = create_image_to_video(
                    prompt=ai_tool.prompt,
                    ratio=ai_tool.ratio,
                    img_url=ai_tool.image_path,
                    duration=ai_tool.duration
                )
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
            
        except (ConnectionError, TimeoutError):
            # 网络异常已在内层处理，这里不应该到达
            raise
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
            # 调用外部 API
            try:
                result = get_ai_task_result(project_id, is_video=True)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，返回 RUNNING 状态，允许重试
                self.logger.warning(f"Network error during Sora2 status check: {str(network_error)}")
                return {
                    "status": "RUNNING"
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
