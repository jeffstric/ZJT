"""
RunningHub 视频高清修复驱动

通过 RunningHub OpenAPI v2 AI-App 调用「视频高清放大」工作流。

参数注入节点：
  - 视频       → nodeId 46  fieldName=video（VHS 加载，传上传后的 fileName 或公网 URL）
  - 模型切换   → nodeId 108 fieldName=select（"1"）
  - 最大分辨率 → nodeId 112 fieldName=value（1920，不建议超过）

算力：按视频秒数 4-15 档计费，为 MiniMax H3 梯度的 2 倍
（表 VIDEO_ENHANCE_COMPUTING_POWER；档位由提交端点 ffprobe 探测后落库 duration）。

状态查询：v2 提交的任务用 v1 /task/openapi/status + /task/openapi/outputs 轮询
（与视频去水印一致，两端点同任务池已验证）。
"""
from typing import Any, Dict, List, Optional
import traceback

from config.config_util import get_config, get_dynamic_config_value
from config.constant import (
    VIDEO_ENHANCE_MAX_DURATION_SECONDS,
    VIDEO_ENHANCE_MIN_DURATION_SECONDS,
)
from config.unified_config import TaskTypeId, VIDEO_ENHANCE_COMPUTING_POWER
from utils.file_storage import RunningHubFileStorage
from utils.runninghub_error import is_upstream_congested_error
from utils.sentry_util import AlertLevel, SentryUtil

from .base_video_driver import BaseVideoDriver

# ==================== RunningHub AI App「视频高清放大」参数（仅本驱动使用） ====================
# app id 与节点参数映射；时长上下限/探测超时在 config/constant.py（端点与驱动共用）
VIDEO_ENHANCE_APP_ID = '2064116518987845634'
VIDEO_ENHANCE_VIDEO_NODE_ID = '46'
VIDEO_ENHANCE_MODEL_SWITCH_NODE_ID = '108'
VIDEO_ENHANCE_MODEL_SWITCH_VALUE = '1'
VIDEO_ENHANCE_MAX_RESOLUTION_NODE_ID = '112'
VIDEO_ENHANCE_MAX_RESOLUTION_VALUE = '1920'
# default=24G 显存 / plus=48G / ultra=84G。SeedVR2 视频超分实测 default 必爆显存
# （torch.OutOfMemoryError，2026-10-28 任务 2115435158520954881），须用 plus（48G）
VIDEO_ENHANCE_INSTANCE_TYPE = 'plus'

VIDEO_RESULT_EXTENSIONS = (".mp4", ".webm", ".mov", ".mkv")


class VideoEnhanceRunninghubV1Driver(BaseVideoDriver):
    """RunningHub 视频高清修复。按时长计费，算力为 MiniMax H3 梯度的 2 倍。"""

    def __init__(self):
        super().__init__(
            driver_name="video_enhance_runninghub_v1",
            driver_type=TaskTypeId.VIDEO_ENHANCE,
        )
        self._api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        self._host = get_dynamic_config_value("runninghub", "host", default="")
        self._webapp_id = VIDEO_ENHANCE_APP_ID
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)
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

    def _resolve_duration(self, raw) -> int:
        if raw is None or raw == "":
            raise ValueError(
                f"视频高清修复缺少时长档位（{VIDEO_ENHANCE_MIN_DURATION_SECONDS}-"
                f"{VIDEO_ENHANCE_MAX_DURATION_SECONDS} 秒），请重新提交"
            )
        try:
            duration = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"视频时长档位必须是整数秒，当前值: {raw}") from exc
        if duration not in VIDEO_ENHANCE_COMPUTING_POWER:
            allowed = sorted(VIDEO_ENHANCE_COMPUTING_POWER)
            raise ValueError(f"视频时长仅支持 {allowed} 秒")
        return duration

    def _resolve_video_path(self, raw) -> str:
        if isinstance(raw, list):
            parts = [str(item).strip() for item in raw if str(item).strip()]
        elif raw:
            parts = [item.strip() for item in str(raw).split(",") if item.strip()]
        else:
            parts = []
        if not parts:
            raise ValueError("视频高清修复需要提供视频")
        if len(parts) > 1:
            self.logger.warning("视频高清修复收到多个视频，仅使用第一个")
        return parts[0]

    async def _upload_video(self, video_path: str) -> str:
        self.logger.info(f"准备上传视频到 RunningHub: {video_path}")
        result = await self._storage.upload_file("", video_path)
        if not result.success:
            raise RuntimeError(f"视频上传到 RunningHub 失败: {result.error}")
        uploaded = result.key if result.key else result.url
        if not uploaded:
            raise RuntimeError("视频上传到 RunningHub 失败: 未返回文件标识")
        self.logger.info(f"视频上传完成，使用 fileName: {uploaded}")
        return uploaded

    def _validate_submit_response(self, result: Any) -> tuple:
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"
        if result.get("errorCode") or result.get("errorMessage"):
            return True, None
        if "taskId" not in result:
            return False, f"响应缺少 'taskId' 字段，实际字段: {list(result.keys())}"
        return True, None

    def _normalize_submit_result(self, result: Any) -> Any:
        """兼容 v2 顶层 taskId，以及包在 data 里的 taskId。"""
        if not isinstance(result, dict):
            return result
        data = result.get("data")
        if isinstance(data, dict) and data.get("taskId") and not result.get("taskId"):
            normalized = dict(data)
            for key in ("errorCode", "errorMessage"):
                if result.get(key) and not normalized.get(key):
                    normalized[key] = result.get(key)
            return normalized
        code = result.get("code")
        if code not in (None, 0) and not result.get("taskId") and not result.get("errorCode"):
            normalized = dict(result)
            normalized["errorCode"] = str(code)
            normalized["errorMessage"] = result.get("msg") or result.get("message") or "任务提交失败"
            return normalized
        return result

    async def build_create_request(self, ai_tool) -> Dict[str, Any]:
        video_path = self._resolve_video_path(getattr(ai_tool, "video_path", None))
        duration = self._resolve_duration(getattr(ai_tool, "duration", None))
        uploaded_video = await self._upload_video(video_path)

        node_info_list = [
            {
                "nodeId": VIDEO_ENHANCE_VIDEO_NODE_ID,
                "fieldName": "video",
                "fieldValue": uploaded_video,
                "description": "上传视频",
            },
            {
                "nodeId": VIDEO_ENHANCE_MODEL_SWITCH_NODE_ID,
                "fieldName": "select",
                "fieldValue": VIDEO_ENHANCE_MODEL_SWITCH_VALUE,
                "description": "模型切换",
            },
            {
                "nodeId": VIDEO_ENHANCE_MAX_RESOLUTION_NODE_ID,
                "fieldName": "value",
                "fieldValue": VIDEO_ENHANCE_MAX_RESOLUTION_VALUE,
                "description": "最大分辨率",
            },
        ]
        self.logger.info(f"视频高清修复请求参数: duration={duration}s 档")
        return {
            "url": f"{self._host}/openapi/v2/run/ai-app/{self._webapp_id}",
            "method": "POST",
            "json": {
                "nodeInfoList": node_info_list,
                "instanceType": VIDEO_ENHANCE_INSTANCE_TYPE,
                "usePersonalQueue": "false",
            },
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        }

    def _user_failure(self, error: str, retry: bool = False) -> Dict[str, Any]:
        return {
            "success": False,
            "error": error,
            "error_type": "USER",
            "retry": retry,
        }

    def _system_failure(self, error_detail: str, ai_tool_id, alert_type: str, response=None) -> Dict[str, Any]:
        self._send_alert(
            alert_type=alert_type,
            message=f"视频高清修复 submit_task: {error_detail}",
            context={
                "api": "video_enhance",
                "response": response,
                "ai_tool_id": ai_tool_id,
                "error_detail": error_detail,
            },
        )
        return {
            "success": False,
            "error": "服务异常，请联系技术支持",
            "error_type": "SYSTEM",
            "error_detail": error_detail,
            "retry": False,
        }

    async def submit_task(self, ai_tool) -> Dict[str, Any]:
        ai_tool_id = getattr(ai_tool, "id", None)
        try:
            self.logger.info(
                f"Submitting video enhance task: duration={getattr(ai_tool, 'duration', None)}"
            )
            request_params = await self.build_create_request(ai_tool)
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during video enhance submit: {network_error}")
                return self._user_failure("网络连接异常，请稍后重试", retry=True)

            result = self._normalize_submit_result(result)
            self.logger.info(f"Video enhance API response: {result}")
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                return self._system_failure(
                    f"API响应格式错误: {validation_error}",
                    ai_tool_id,
                    "INVALID_RESPONSE_FORMAT",
                    result,
                )

            error_code = result.get("errorCode", "")
            error_message = result.get("errorMessage", "")
            if error_code or error_message:
                if is_upstream_congested_error(error_code):
                    self.logger.warning(
                        f"Video enhance upstream congested: errorCode={error_code}, errorMessage={error_message}"
                    )
                    return self._build_upstream_congested_result()
                return self._user_failure(f"任务提交失败: {error_message or error_code}")

            task_id = result.get("taskId")
            if not task_id:
                return self._system_failure(
                    "RunningHub 未返回任务ID",
                    ai_tool_id,
                    "INVALID_RESPONSE_FORMAT",
                    result,
                )
            return {"success": True, "project_id": task_id}

        except ValueError as exc:
            # 参数校验类失败（时长档位越界、缺视频）：用户输入问题，重试无意义
            self.logger.warning(f"Video enhance submit rejected: {exc}")
            return self._user_failure(str(exc))
        except RuntimeError as exc:
            # 上传输入视频到 RunningHub 的瞬态失败（5xx/网络抖动）：可重试
            self.logger.warning(f"Video enhance upload transient failure, will retry: {exc}")
            return self._user_failure(f"视频上传失败，将自动重试: {exc}", retry=True)
        except Exception as exc:
            self.logger.error(f"Unexpected exception in video enhance submit_task: {exc}")
            self.logger.error(traceback.format_exc())
            return self._system_failure(
                f"未预期异常: {exc}",
                ai_tool_id,
                "UNEXPECTED_EXCEPTION",
            )

    def _extract_task_status(self, status_result: Dict[str, Any]) -> str:
        data = status_result.get("data", "")
        if isinstance(data, dict):
            return str(data.get("status") or data.get("taskStatus") or "")
        return str(data or "")

    def _pick_result_url(self, outputs_data: Any) -> Optional[str]:
        if not isinstance(outputs_data, list):
            return None
        candidates: List[str] = []
        for item in outputs_data:
            if not isinstance(item, dict):
                continue
            url = item.get("fileUrl") or item.get("url")
            if url:
                candidates.append(str(url))
        for url in candidates:
            path = url.split("?", 1)[0].lower()
            if path.endswith(VIDEO_RESULT_EXTENSIONS):
                return url
        return candidates[0] if candidates else None

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        return {
            "url": f"{self._host}/task/openapi/status",
            "method": "POST",
            "json": {"apiKey": self._api_key, "taskId": project_id},
            "headers": {"Content-Type": "application/json", "Accept": "application/json"},
        }

    def check_status(self, project_id: str) -> Dict[str, Any]:
        try:
            self.logger.info(f"Checking video enhance task status: project_id={project_id}")
            try:
                status_result = self._request(**self.build_check_query(project_id))
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during video enhance status check: {network_error}")
                return {"status": "RUNNING", "message": "网络连接异常，稍后将重试"}

            if not isinstance(status_result, dict) or "code" not in status_result:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="视频高清修复 status API 响应格式异常",
                    context={"api": "check_status", "response": status_result, "project_id": project_id},
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "RunningHub 响应格式错误",
                }

            if status_result.get("code") != 0:
                return {
                    "status": "FAILED",
                    "error": status_result.get("msg") or "查询状态失败",
                    "error_type": "USER",
                }

            task_status = self._extract_task_status(status_result)
            if task_status == "SUCCESS":
                outputs_params = {
                    "url": f"{self._host}/task/openapi/outputs",
                    "method": "POST",
                    "json": {"apiKey": self._api_key, "taskId": project_id},
                    "headers": {"Content-Type": "application/json", "Accept": "application/json"},
                }
                try:
                    outputs_result = self._request(**outputs_params)
                except Exception as exc:
                    # 上游任务已 SUCCESS：outputs 网络抖动/超时不应把已完成任务
                    # 判成终态失败。preserve_retry_count 让调度层单独安排结果获取
                    # 重试，不消耗生成阶段的 max_retry_count；任务过期仍作最终兜底。
                    self.logger.warning(
                        f"Outputs fetch transient failure for task {project_id}: {exc}"
                    )
                    return {
                        "status": "RUNNING",
                        "message": "任务已完成，获取结果中...",
                        "preserve_retry_count": True,
                    }

                if not isinstance(outputs_result, dict):
                    self._send_alert(
                        alert_type="INVALID_RESPONSE_FORMAT",
                        message="视频高清修复 outputs API 响应格式异常",
                        context={"api": "outputs", "response": outputs_result, "project_id": project_id},
                    )
                    return {
                        "status": "FAILED",
                        "error": "获取结果失败",
                        "error_type": "SYSTEM",
                        "error_detail": "outputs 响应格式错误",
                    }

                error_code = outputs_result.get("code")
                if error_code != 0:
                    try:
                        numeric_code = int(error_code)
                    except (TypeError, ValueError):
                        numeric_code = None
                    transient = (
                        is_upstream_congested_error(error_code)
                        or numeric_code == 429
                        or (numeric_code is not None and 500 <= numeric_code < 600)
                    )
                    self.logger.warning(
                        f"Outputs API returned code={error_code} "
                        f"for task {project_id}: {outputs_result.get('msg', '')}"
                    )
                    if transient:
                        return {
                            "status": "RUNNING",
                            "message": "任务已完成，获取结果中...",
                            "preserve_retry_count": True,
                        }
                    return {
                        "status": "FAILED",
                        "error": "获取结果失败",
                        "error_type": "SYSTEM",
                        "error_detail": (
                            f"获取输出失败: code={error_code}, "
                            f"msg={outputs_result.get('msg', '')}"
                        ),
                    }

                result_url = self._pick_result_url(outputs_result.get("data"))
                if not result_url:
                    self._send_alert(
                        alert_type="INVALID_RESPONSE_FORMAT",
                        message="视频高清修复成功但没有视频结果",
                        context={"api": "outputs", "response": outputs_result, "project_id": project_id},
                    )
                    return {
                        "status": "FAILED",
                        "error": "任务成功但未返回视频结果",
                        "error_type": "SYSTEM",
                        "error_detail": "outputs 中没有可用视频地址",
                    }
                return {"status": "SUCCESS", "result_url": result_url}

            if task_status == "FAILED":
                return {"status": "FAILED", "error": "任务失败", "error_type": "USER"}

            return {"status": "RUNNING", "message": "任务处理中..."}

        except Exception as exc:
            self.logger.error(f"Unexpected exception in video enhance check_status: {exc}")
            self.logger.error(traceback.format_exc())
            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"视频高清修复 check_status 发生未预期异常: {exc}",
                context={"exception": str(exc), "traceback": traceback.format_exc(), "project_id": project_id},
            )
            return {
                "status": "FAILED",
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {exc}",
            }
