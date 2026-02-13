"""
LTX2 RunningHub v1 版本驱动实现
"""
from typing import Dict, Any, Optional
import traceback
import os
import yaml
from .base_video_driver import BaseVideoDriver
from config_util import get_config_path
from utils.sentry_util import SentryUtil, AlertLevel


class Ltx2RunninghubV1Driver(BaseVideoDriver):
    """
    LTX2 RunningHub v1 版本驱动
    支持图生视频
    """

    def __init__(self):
        super().__init__(driver_name="ltx2_runninghub_v1", driver_type=10)

        # 加载配置
        config_path = get_config_path()
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)

        self._api_key = config["runninghub"]["api_key"]
        self._host = config["runninghub"]["host"]
        self._webapp_id = "2011014079896358914"  # LTX2.0 webapp ID
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

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 LTX2 任务的完整请求参数

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # Build node info list for LTX2.0 v2
        node_info_list = [
            {
                "nodeId": "67",
                "fieldName": "image",
                "fieldValue": ai_tool.image_path,
                "description": "图像image"
            },
            {
                "nodeId": "123",
                "fieldName": "text",
                "fieldValue": "",
                "description": "魔搭社区的key"
            },
            {
                "nodeId": "66",
                "fieldName": "value",
                "fieldValue": "1280",
                "description": "最长边"
            },
            {
                "nodeId": "52",
                "fieldName": "value",
                "fieldValue": str(ai_tool.duration or 5),
                "description": "时长"
            },
            {
                "nodeId": "108",
                "fieldName": "select",
                "fieldValue": "1",
                "description": "镜头运动选择"
            },
            {
                "nodeId": "109",
                "fieldName": "select",
                "fieldValue": "3",
                "description": "手动选择运镜"
            },
            {
                "nodeId": "160",
                "fieldName": "select",
                "fieldValue": "2",
                "description": "提示词设置"
            },
            {
                "nodeId": "96",
                "fieldName": "text",
                "fieldValue": ai_tool.prompt or "",
                "description": "提示词【自动可不填】"
            }
        ]

        return {
            "url": f"{self._host}/openapi/v2/run/ai-app/{self._webapp_id}",
            "method": "POST",
            "json": {
                "nodeInfoList": node_info_list,
                "instanceType": "plus",
                "usePersonalQueue": "false"
            },
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            }
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 LTX2 任务状态的完整请求参数

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        return {
            "url": f"{self._host}/task/openapi/status",
            "method": "POST",
            "json": {
                "apiKey": self._api_key,
                "taskId": project_id
            },
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
        }

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 LTX2 视频生成任务

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词
                - image_path: 图片路径
                - duration: 视频时长 (5, 8, 10)

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(f"Submitting LTX2 task: prompt='{ai_tool.prompt[:50]}...', duration={ai_tool.duration}")

            # 构建请求参数
            request_params = self.build_create_request(ai_tool)

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during LTX2 task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(f"LTX2 API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                # 格式错误，发送报警，不重试
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"LTX2 submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_ltx2_image_to_video",
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
                self.logger.warning(f"LTX2 API returned error: errorCode={error_code}, errorMessage={error_message}")
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
                    "error_detail": "LTX2 API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": task_id
            }

        except Exception as e:
            # 非网络异常，发送报警，不重试
            self.logger.error(f"Unexpected exception in LTX2 submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"LTX2 submit_task 发生未预期异常: {str(e)}",
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
        检查 LTX2 任务状态

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking LTX2 task status: project_id={project_id}")

            # 第一次调用：查询状态
            status_params = self.build_check_query(project_id)

            try:
                status_result = self._request(**status_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during LTX2 status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            # 验证状态响应格式: {"code": 0, "data": "SUCCESS/RUNNING/FAILED"}
            if not isinstance(status_result, dict) or "code" not in status_result:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="LTX2 status API 响应格式异常",
                    context={
                        "api": "check_status",
                        "response": status_result,
                        "project_id": project_id
                    }
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "RunningHub 响应格式错误"
                }

            if status_result.get("code") != 0:
                error_msg = status_result.get("msg", "查询状态失败")
                return {
                    "status": "FAILED",
                    "error": error_msg,
                    "error_type": "USER"
                }

            task_status = status_result.get("data", "")

            # 映射 RunningHub 状态到统一状态
            if task_status == "SUCCESS":
                # 第二次调用：获取输出结果
                outputs_params = {
                    "url": f"{self._host}/task/openapi/outputs",
                    "method": "POST",
                    "json": {
                        "apiKey": self._api_key,
                        "taskId": project_id
                    },
                    "headers": {
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    }
                }

                try:
                    outputs_result = self._request(**outputs_params)
                except Exception as e:
                    self.logger.error(f"Failed to get outputs: {str(e)}")
                    return {
                        "status": "FAILED",
                        "error": "获取结果失败",
                        "error_type": "SYSTEM",
                        "error_detail": f"获取输出失败: {str(e)}"
                    }

                # 从 outputs 中提取视频 URL
                result_url = None
                if outputs_result.get("code") == 0:
                    outputs_data = outputs_result.get("data", [])
                    if outputs_data:
                        for item in outputs_data:
                            file_url = item.get("fileUrl")
                            if file_url:
                                result_url = file_url
                                break

                return {
                    "status": "SUCCESS",
                    "result_url": result_url
                }
            elif task_status == "FAILED":
                return {
                    "status": "FAILED",
                    "error": "任务失败",
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
            self.logger.error(f"Unexpected exception in LTX2 check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"LTX2 check_status 发生未预期异常: {str(e)}",
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
