"""
MiniMax H3 数字人 RunningHub v1 版本驱动实现

支持图片 + 音频 + 提示词生成数字人视频。
webapp_id: 2087200340012785665

参数注入节点 nodeId：
  - 提示词        → nodeId 214 fieldName=value  (文本描述动作)
  - 音频          → nodeId 215 fieldName=audio
  - 图片          → nodeId 209 fieldName=image
  - 视频时长(秒)  → nodeId 212 fieldName=value
  - 最长边长度    → nodeId 213 fieldName=value
  - 开始说话秒数  → nodeId 229 fieldName=value
"""
import json
from typing import Dict, Any, Optional
import traceback
from .base_video_driver import BaseVideoDriver
from config.config_util import get_config, get_dynamic_config_value
from config.unified_config import TaskTypeId
from utils.sentry_util import SentryUtil, AlertLevel
from utils.file_storage import RunningHubFileStorage
from utils.runninghub_error import is_upstream_congested_error
from .exceptions import ImageExpiredError


# 支持的最长边选项
SUPPORTED_MAX_EDGES = {720, 1280, 1920}
DEFAULT_MAX_EDGE = 1280
DEFAULT_DURATION = 10
DEFAULT_START_SECOND = 0
SUPPORTED_DURATIONS = {4, 5, 6, 7, 8, 9, 10}


class DigitalHumanMinimaxH3RunninghubV1Driver(BaseVideoDriver):
    """
    MiniMax H3 数字人 RunningHub v1 版本驱动
    支持图片 + 音频 + 提示词生成数字人视频
    """

    def __init__(self):
        super().__init__(
            driver_name="digital_human_minimax_h3_runninghub_v1",
            driver_type=TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3,
        )

        self._api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        self._host = get_dynamic_config_value("runninghub", "host", default="")
        self._webapp_id = "2087200340012785665"  # MiniMax H3 数字人 webapp ID
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        self._storage = RunningHubFileStorage(
            host=self._host,
            api_key=self._api_key,
            config=self._config,
            logger=self.logger,
        )

        self._validate_required({
            "RunningHub API Key": self._api_key,
            "RunningHub Host": self._host,
        })

    def _send_alert(self, alert_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        SentryUtil.send_alert(
            alert_type=alert_type,
            message=message,
            level=AlertLevel.ERROR,
            context=context,
        )

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "taskId" not in result:
            return False, f"响应缺少 'taskId' 字段，实际字段: {list(result.keys())}"

        if "status" not in result:
            return False, f"响应缺少 'status' 字段，实际字段: {list(result.keys())}"

        return True, None

    def _parse_extra_config(self, ai_tool) -> Dict[str, Any]:
        if not ai_tool.extra_config:
            return {}
        try:
            config = (
                ai_tool.extra_config
                if isinstance(ai_tool.extra_config, dict)
                else json.loads(ai_tool.extra_config)
            )
            return config if isinstance(config, dict) else {}
        except (json.JSONDecodeError, TypeError):
            self.logger.warning(f"无法解析 extra_config: {ai_tool.extra_config}")
            return {}

    def _resolve_duration(self, ai_tool) -> int:
        duration = ai_tool.duration or DEFAULT_DURATION
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            duration = DEFAULT_DURATION
        if duration not in SUPPORTED_DURATIONS:
            self.logger.warning(f"不支持的时长 {duration}，回退到默认 {DEFAULT_DURATION}")
            return DEFAULT_DURATION
        return duration

    def _resolve_max_edge(self, extra_config: Dict[str, Any]) -> int:
        raw = extra_config.get("max_edge", DEFAULT_MAX_EDGE)
        try:
            max_edge = int(raw)
        except (TypeError, ValueError):
            max_edge = DEFAULT_MAX_EDGE
        if max_edge not in SUPPORTED_MAX_EDGES:
            self.logger.warning(f"不支持的最长边 {max_edge}，回退到默认 {DEFAULT_MAX_EDGE}")
            return DEFAULT_MAX_EDGE
        return max_edge

    def _resolve_start_second(self, extra_config: Dict[str, Any]) -> int:
        raw = extra_config.get("start_second", DEFAULT_START_SECOND)
        try:
            start_second = int(raw)
        except (TypeError, ValueError):
            start_second = DEFAULT_START_SECOND
        if start_second < 0:
            start_second = DEFAULT_START_SECOND
        return start_second

    async def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 MiniMax H3 数字人任务的完整请求参数

        节点映射：
        - 提示词 → nodeId 214 (value)
        - 音频   → nodeId 215 (audio)
        - 图片   → nodeId 209 (image)
        - 时长   → nodeId 212 (value)
        - 最长边 → nodeId 213 (value)
        - 开始说话秒数 → nodeId 229 (value)
        """
        extra_config = self._parse_extra_config(ai_tool)
        duration = self._resolve_duration(ai_tool)
        max_edge = self._resolve_max_edge(extra_config)
        start_second = self._resolve_start_second(extra_config)

        audio_url = ai_tool.audio_path or ai_tool.message or ""
        if audio_url:
            self.logger.info(f"准备上传音频到 RunningHub: {audio_url}")
            result = await self._storage.upload_file("", audio_url)
            if result.success:
                audio_url = result.key if result.key else result.url
                self.logger.info(f"音频上传完成，使用 fileName: {audio_url}")
            else:
                raise RuntimeError(f"音频上传到 RunningHub 失败: {result.error}")

        image_path = ai_tool.image_path
        if image_path:
            if "," in image_path:
                image_path = image_path.split(",")[0].strip()
            self.logger.info(f"准备上传图片到 RunningHub 图床: {image_path}")
            result = await self._storage.upload_file("", image_path)
            if result.success:
                image_path = result.url if result.url else result.key
                self.logger.info(f"图片上传完成，使用 URL: {image_path}")
            else:
                raise RuntimeError(f"图片上传到 RunningHub 失败: {result.error}")

        node_info_list = [
            {
                "nodeId": "214",
                "fieldName": "value",
                "fieldValue": ai_tool.prompt or "",
                "description": "value",
            },
            {
                "nodeId": "215",
                "fieldName": "audio",
                "fieldValue": audio_url,
                "description": "audio",
            },
            {
                "nodeId": "209",
                "fieldName": "image",
                "fieldValue": image_path,
                "description": "image",
            },
            {
                "nodeId": "212",
                "fieldName": "value",
                "fieldValue": str(duration),
                "description": "value",
            },
            {
                "nodeId": "213",
                "fieldName": "value",
                "fieldValue": str(max_edge),
                "description": "value",
            },
            {
                "nodeId": "229",
                "fieldName": "value",
                "fieldValue": str(start_second),
                "description": "value",
            },
        ]

        return {
            "url": f"{self._host}/openapi/v2/run/ai-app/{self._webapp_id}",
            "method": "POST",
            "json": {
                "nodeInfoList": node_info_list,
                "instanceType": "default",
                "usePersonalQueue": "false",
            },
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        return {
            "url": f"{self._host}/task/openapi/status",
            "method": "POST",
            "json": {
                "apiKey": self._api_key,
                "taskId": project_id,
            },
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        }

    async def submit_task(self, ai_tool) -> Dict[str, Any]:
        try:
            prompt_preview = (ai_tool.prompt or "")[:50]
            self.logger.info(
                f"Submitting MiniMax H3 digital human task: text='{prompt_preview}...', "
                f"duration={ai_tool.duration}"
            )

            request_params = await self.build_create_request(ai_tool)

            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True,
                }

            self.logger.info(f"API response: {result}")

            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_digital_human_minimax_h3",
                        "response": result,
                        "ai_tool_id": ai_tool.id,
                    },
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {validation_error}",
                    "retry": False,
                }

            error_code = result.get("errorCode", "")
            error_message = result.get("errorMessage", "")
            if error_code or error_message:
                if is_upstream_congested_error(error_code):
                    self.logger.warning(
                        f"Digital Human(MiniMax H3) upstream congested, will auto-retry: "
                        f"errorCode={error_code}, errorMessage={error_message}"
                    )
                    return self._build_upstream_congested_result()
                self.logger.warning(
                    f"API returned error: errorCode={error_code}, errorMessage={error_message}"
                )
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_message or error_code}",
                    "error_type": "USER",
                    "retry": False,
                }

            task_id = result.get("taskId")
            if not task_id:
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "API未返回任务ID",
                    "retry": False,
                }

            return {
                "success": True,
                "project_id": task_id,
            }

        except ImageExpiredError as e:
            self.logger.warning(f"输入图片已过期: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "error_type": "USER",
                "retry": False,
            }

        except Exception as e:
            self.logger.error(f"Unexpected exception in submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"submit_task 发生未预期异常: {str(e)}",
                context={
                    "exception": str(e),
                    "traceback": traceback.format_exc(),
                    "ai_tool_id": getattr(ai_tool, "id", None),
                },
            )

            return {
                "success": False,
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}",
                "retry": False,
            }

    def check_status(self, project_id: str) -> Dict[str, Any]:
        try:
            self.logger.info(f"Checking task status: project_id={project_id}")

            status_params = self.build_check_query(project_id)

            try:
                status_result = self._request(**status_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试",
                }

            if not isinstance(status_result, dict) or "code" not in status_result:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="status API 响应格式异常",
                    context={
                        "api": "check_status",
                        "response": status_result,
                        "project_id": project_id,
                    },
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "RunningHub 响应格式错误",
                }

            if status_result.get("code") != 0:
                error_msg = status_result.get("msg", "查询状态失败")
                return {
                    "status": "FAILED",
                    "error": error_msg,
                    "error_type": "USER",
                }

            task_status = status_result.get("data", "")

            if task_status == "SUCCESS":
                outputs_params = {
                    "url": f"{self._host}/task/openapi/outputs",
                    "method": "POST",
                    "json": {
                        "apiKey": self._api_key,
                        "taskId": project_id,
                    },
                    "headers": {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                }

                try:
                    outputs_result = self._request(**outputs_params)
                except Exception as e:
                    self.logger.error(f"Failed to get outputs: {str(e)}")
                    return {
                        "status": "FAILED",
                        "error": "获取结果失败",
                        "error_type": "SYSTEM",
                        "error_detail": f"获取输出失败: {str(e)}",
                    }

                result_url = None
                if outputs_result.get("code") == 0:
                    outputs_data = outputs_result.get("data", [])
                    self.logger.info(f"Outputs data: {outputs_data}")
                    if outputs_data:
                        for item in outputs_data:
                            file_type = item.get("fileType")
                            file_url = item.get("fileUrl")
                            if file_type == "mp4" and file_url:
                                result_url = file_url
                                break

                return {
                    "status": "SUCCESS",
                    "result_url": result_url,
                }
            elif task_status == "FAILED":
                return {
                    "status": "FAILED",
                    "error": "任务失败",
                    "error_type": "USER",
                }
            else:
                return {
                    "status": "RUNNING",
                    "message": "任务处理中...",
                }

        except Exception as e:
            self.logger.error(f"Unexpected exception in check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"check_status 发生未预期异常: {str(e)}",
                context={
                    "exception": str(e),
                    "traceback": traceback.format_exc(),
                    "project_id": project_id,
                },
            )

            return {
                "status": "FAILED",
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}",
            }
