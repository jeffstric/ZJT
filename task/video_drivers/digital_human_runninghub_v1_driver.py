"""
Digital Human RunningHub v1 版本驱动实现
"""
from typing import Dict, Any, Optional
import traceback
from .base_video_driver import BaseVideoDriver
from runninghub_request import create_digital_human, check_ltx2_task_status
from utils.sentry_util import SentryUtil, AlertLevel


class DigitalHumanRunninghubV1Driver(BaseVideoDriver):
    """
    Digital Human RunningHub v1 版本驱动
    支持数字人视频生成
    """
    
    def __init__(self):
        super().__init__(driver_name="digital_human_runninghub_v1", driver_type=13)
    
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
            "taskId": "2019324151986266113",
            "status": "RUNNING",
            "errorCode": "",
            "errorMessage": "",
            ...
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"
        
        if "taskId" not in result:
            return False, f"响应缺少 'taskId' 字段，实际字段: {list(result.keys())}"
        
        if "status" not in result:
            return False, f"响应缺少 'status' 字段，实际字段: {list(result.keys())}"
        
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
            "msg": "success",
            "data": {
                "status": "SUCCESS",  # PENDING, RUNNING, SUCCESS, FAILED
                "result": {
                    "videoUrl": "https://example.com/video.mp4"
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
        
        if "status" not in data:
            return False, f"'data' 缺少 'status' 字段，实际字段: {list(data.keys())}"
        
        task_status = data.get("status")
        if task_status == "SUCCESS":
            if "result" not in data:
                return False, "任务成功但缺少 'result' 字段"
            
            result_data = data.get("result")
            if not isinstance(result_data, dict):
                return False, f"'result' 字段类型错误，期望 dict，实际: {type(result_data)}"
            
            if "videoUrl" not in result_data:
                return False, "任务成功但 'result' 缺少 'videoUrl' 字段"
        
        return True, None
    
    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 Digital Human 视频生成任务
        
        Args:
            ai_tool: AITool 对象
                - prompt: 文本内容（讲话内容）
                - image_path: 图片路径
                - ratio: 视频比例
                - extra_config: 额外配置（JSON格式，包含 audio_url）
        
        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(f"Submitting Digital Human task: text='{ai_tool.prompt[:50]}...', ratio={ai_tool.ratio}")
            
            # 从 extra_config 中获取 audio_url
            import json
            audio_url = ""
            if ai_tool.extra_config:
                try:
                    extra_config = json.loads(ai_tool.extra_config)
                    audio_url = extra_config.get("audio_url", "")
                except json.JSONDecodeError:
                    self.logger.warning(f"Failed to parse extra_config: {ai_tool.extra_config}")
            
            # 调用外部 API
            try:
                result = create_digital_human(
                    image_url=ai_tool.image_path,
                    text=ai_tool.prompt,
                    audio_url=audio_url,
                    aspect_ratio=ai_tool.ratio or "9:16"
                )
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during Digital Human task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }
            
            self.logger.info(f"Digital Human API response: {result}")
            
            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                # 格式错误，发送报警，不重试
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Digital Human submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_digital_human",
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
            
            # 检查业务错误（通过 errorCode 或 errorMessage 判断）
            error_code = result.get("errorCode", "")
            error_message = result.get("errorMessage", "")
            if error_code or error_message:
                self.logger.warning(f"Digital Human API returned error: errorCode={error_code}, errorMessage={error_message}")
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_message or error_code}",
                    "error_type": "USER",
                    "retry": False
                }
            
            task_id = result.get("taskId")
            if not task_id:
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "Digital Human API未返回任务ID",
                    "retry": False
                }
            
            return {
                "success": True,
                "project_id": task_id
            }
            
        except Exception as e:
            # 非网络异常，发送报警，不重试
            self.logger.error(f"Unexpected exception in Digital Human submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())
            
            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Digital Human submit_task 发生未预期异常: {str(e)}",
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
        检查 Digital Human 任务状态
        
        Args:
            project_id: 任务ID
        
        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking Digital Human task status: project_id={project_id}")
            
            # 调用外部 API
            try:
                result = check_ltx2_task_status(task_id=project_id)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during Digital Human status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }
            
            self.logger.info(f"Digital Human status API response: {result}")
            
            # check_ltx2_task_status 返回格式: {"status": "SUCCESS/RUNNING/FAILED", "task_id": "...", "results": [...]}
            if not isinstance(result, dict) or "status" not in result:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="Digital Human check_ltx2_task_status 响应格式异常",
                    context={
                        "api": "check_ltx2_task_status",
                        "response": result,
                        "project_id": project_id
                    }
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "RunningHub 响应格式错误"
                }
            
            task_status = result.get("status", "")
            
            # 映射 RunningHub 状态到统一状态
            if task_status == "SUCCESS":
                # 从 results 中提取视频 URL
                results = result.get("results", [])
                result_url = None
                if results:
                    for item in results:
                        if hasattr(item, 'file_url'):
                            result_url = item.file_url
                            break
                        elif isinstance(item, dict):
                            result_url = item.get("file_url") or item.get("fileUrl")
                            if result_url:
                                break
                
                return {
                    "status": "SUCCESS",
                    "result_url": result_url
                }
            elif task_status == "FAILED":
                error_msg = result.get("error") or result.get("message") or "任务失败"
                return {
                    "status": "FAILED",
                    "error": error_msg,
                    "error_type": "USER"
                }
            else:
                # PENDING, RUNNING 或其他状态
                return {
                    "status": "RUNNING",
                    "message": "任务处理中..."
                }
                
        except Exception as e:
            # 非网络异常，发送报警
            self.logger.error(f"Unexpected exception in Digital Human check_status: {str(e)}")
            self.logger.error(traceback.format_exc())
            
            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Digital Human check_status 发生未预期异常: {str(e)}",
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
