"""
Gemini 多米供应商 v1 版本驱动实现（标准版）
"""
from typing import Dict, Any, Optional
import traceback
from .base_video_driver import BaseVideoDriver
from duomi_api_requset import create_ai_image, get_ai_task_result
from utils.sentry_util import SentryUtil, AlertLevel


class GeminiDuomiV1Driver(BaseVideoDriver):
    """
    Gemini 多米供应商 v1 版本驱动（标准版）
    支持图片编辑
    """
    
    def __init__(self):
        super().__init__(driver_name="gemini_duomi_v1", driver_type=1)
    
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
            "code": 200,
            "msg": "success",
            "data": {
                "task_id": "task_123456789",
                "state": "processing",
                "message": "..."
            }
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"
        
        if "code" not in result:
            return False, f"响应缺少 'code' 字段，实际字段: {list(result.keys())}"
        
        if result.get("code") != 200:
            return True, None  # code != 200 表示业务错误，格式仍然有效
        
        if "data" not in result:
            return False, f"响应缺少 'data' 字段，实际字段: {list(result.keys())}"
        
        data = result.get("data")
        if not isinstance(data, dict):
            return False, f"'data' 字段类型错误，期望 dict，实际: {type(data)}"
        
        if "task_id" not in data:
            return False, f"'data' 缺少 'task_id' 字段，实际字段: {list(data.keys())}"
        
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
                "mediaUrl": "https://example.com/image.png",  # status=1时必须存在
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
    
    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 Gemini 图片编辑任务
        
        Args:
            ai_tool: AITool 对象
                - prompt: 提示词
                - ratio: 图片比例
                - image_path: 输入图片路径
                - image_size: 图片尺寸 (1K, 2K, 4K)
        
        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(f"Submitting Gemini task: prompt='{ai_tool.prompt[:50]}...', ratio={ai_tool.ratio}, size={ai_tool.image_size}")
            
            # 准备图片URL列表
            image_urls = [ai_tool.image_path] if ai_tool.image_path else None
            
            # 调用外部 API
            try:
                result = create_ai_image(
                    model="gemini-2.5-pro-image-preview",
                    prompt=ai_tool.prompt,
                    ratio=ai_tool.ratio,
                    image_urls=image_urls,
                    image_size=ai_tool.image_size or "1K"
                )
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during Gemini task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }
            
            self.logger.info(f"Gemini API response: {result}")
            
            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                # 格式错误，发送报警，不重试
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Gemini submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_ai_image",
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
            if result.get("code") != 200:
                error_msg = result.get("msg", "未知错误")
                self.logger.warning(f"Gemini API returned error: code={result.get('code')}, msg={error_msg}")
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
                    "error_detail": "Gemini API未返回任务ID",
                    "retry": False
                }
            
            return {
                "success": True,
                "project_id": task_id
            }
            
        except Exception as e:
            # 非网络异常，发送报警，不重试
            self.logger.error(f"Unexpected exception in Gemini submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())
            
            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Gemini submit_task 发生未预期异常: {str(e)}",
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
        
        Args:
            project_id: 任务ID
        
        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking Gemini task status: project_id={project_id}")
            
            # 调用外部 API
            try:
                result = get_ai_task_result(project_id=project_id, is_video=False)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during Gemini status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }
            
            self.logger.info(f"Gemini status API response: {result}")
            
            # 验证响应格式
            is_valid, validation_error = self._validate_status_response(result)
            if not is_valid:
                # 格式错误，发送报警
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Gemini check_status 响应格式错误: {validation_error}",
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
            
            # 检查业务错误
            if result.get("code") != 0:
                error_msg = result.get("msg", "未知错误")
                self.logger.warning(f"Gemini status API returned error: code={result.get('code')}, msg={error_msg}")
                return {
                    "status": "FAILED",
                    "error": f"查询任务状态失败: {error_msg}",
                    "error_type": "SYSTEM"
                }
            
            data = result.get("data", {})
            task_status = data.get("status")
            
            # 映射状态到统一状态
            if task_status == 1:
                # 成功
                result_url = data.get("mediaUrl")
                return {
                    "status": "SUCCESS",
                    "result_url": result_url
                }
            elif task_status == 2:
                # 失败
                reason = data.get("reason", "任务失败")
                return {
                    "status": "FAILED",
                    "error": reason,
                    "error_type": "USER"
                }
            else:
                # 处理中
                return {
                    "status": "RUNNING",
                    "message": "任务处理中..."
                }
                
        except Exception as e:
            # 非网络异常，发送报警
            self.logger.error(f"Unexpected exception in Gemini check_status: {str(e)}")
            self.logger.error(traceback.format_exc())
            
            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Gemini check_status 发生未预期异常: {str(e)}",
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
