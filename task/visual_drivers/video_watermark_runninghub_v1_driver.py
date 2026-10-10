"""
RunningHub 视频去水印驱动

通过 RunningHub AI-App 调用「去水印去字幕」工作流。
webapp_id: 2108118160242200577

参数注入节点：
  - 视频     → nodeId 5099 fieldName=video (VHS_LoadVideo，传上传后的 fileName)
  - 提示词   → nodeId 5134 fieldName=text
  - 视频时长 → nodeId 5145 fieldName=value（秒，仅 4-10，与 MiniMax H3 720P 算力表一致）
  - 每帧秒数 → nodeId 5146 fieldName=value（帧率，默认 24）
"""
import json
from typing import Any, Dict, List, Optional
import traceback

from config.config_util import get_config, get_dynamic_config_value
from config.unified_config import MINIMAX_H3_720P_COMPUTING_POWER, TaskTypeId
from utils.file_storage import RunningHubFileStorage
from utils.runninghub_error import is_upstream_congested_error
from utils.sentry_util import AlertLevel, SentryUtil

from .base_video_driver import BaseVideoDriver
from .exceptions import ImageExpiredError


WEBAPP_ID = "2108118160242200577"
DEFAULT_DURATION = 5
DEFAULT_FPS = 24
MIN_FPS = 1
MAX_FPS = 120
MAX_PROMPT_CHARS = 2000
DEFAULT_PROMPT = (
    "去除视频画面中的短视频平台水印与字幕与相关遮挡痕迹，恢复干净、清晰、自然的原始画面；"
    "保持人物、场景、动作、镜头运动、时序和整体风格一致，不改变原视频内容，"
    "只进行水印和字幕的去除与细节修复。"
)
VIDEO_RESULT_EXTENSIONS = (".mp4", ".webm", ".mov", ".mkv")


class VideoWatermarkRunninghubV1Driver(BaseVideoDriver):
    """RunningHub 视频去水印。按时长计费，算力与 MiniMax H3 720P 共用同一张表。"""

    def __init__(self):
        super().__init__(
            driver_name="video_watermark_runninghub_v1",
            driver_type=TaskTypeId.VIDEO_WATERMARK_REMOVE,
        )
        self._api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        self._host = get_dynamic_config_value("runninghub", "host", default="")
        self._webapp_id = WEBAPP_ID
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

    def _parse_extra_config(self, ai_tool) -> Dict[str, Any]:
        raw = getattr(ai_tool, "extra_config", None)
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            self.logger.warning(f"无法解析 extra_config: {raw}")
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _resolve_duration(self, raw) -> int:
        if raw is None or raw == "":
            return DEFAULT_DURATION
        try:
            duration = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"视频时长必须是整数秒，当前值: {raw}") from exc
        if duration not in MINIMAX_H3_720P_COMPUTING_POWER:
            allowed = sorted(MINIMAX_H3_720P_COMPUTING_POWER)
            raise ValueError(f"视频时长仅支持 {allowed} 秒")
        return duration

    def _resolve_fps(self, extra_config: Dict[str, Any]) -> int:
        raw = extra_config.get("fps") if isinstance(extra_config, dict) else None
        if raw is None or raw == "":
            return DEFAULT_FPS
        try:
            fps = int(raw)
        except (TypeError, ValueError):
            self.logger.warning(f"帧率无法解析，改用 {DEFAULT_FPS}: {raw}")
            return DEFAULT_FPS
        if fps < MIN_FPS or fps > MAX_FPS:
            self.logger.warning(f"帧率 {fps} 超出 {MIN_FPS}-{MAX_FPS}，改用 {DEFAULT_FPS}")
            return DEFAULT_FPS
        return fps

    def _resolve_prompt(self, prompt) -> str:
        text = str(prompt or "").strip()
        if not text:
            return DEFAULT_PROMPT
        if len(text) > MAX_PROMPT_CHARS:
            raise ValueError(f"提示词不能超过 {MAX_PROMPT_CHARS} 个字符")
        return text

    def _resolve_video_path(self, raw) -> str:
        if isinstance(raw, list):
            parts = [str(item).strip() for item in raw if str(item).strip()]
        elif raw:
            parts = [item.strip() for item in str(raw).split(",") if item.strip()]
        else:
            parts = []
        if not parts:
            raise ValueError("视频去水印需要提供视频")
        if len(parts) > 1:
            self.logger.warning("视频去水印收到多个视频，仅使用第一个")
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
        if "status" not in result:
            return False, f"响应缺少 'status' 字段，实际字段: {list(result.keys())}"
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
        extra_config = self._parse_extra_config(ai_tool)
        fps = self._resolve_fps(extra_config)
        prompt_text = self._resolve_prompt(getattr(ai_tool, "prompt", None))
        uploaded_video = await self._upload_video(video_path)

        node_info_list = [
            {
                "nodeId": "5099",
                "fieldName": "video",
                "fieldValue": uploaded_video,
                "description": "视频",
            },
            {
                "nodeId": "5134",
                "fieldName": "text",
                "fieldValue": prompt_text,
                "description": "提示词",
            },
            {
                "nodeId": "5145",
                "fieldName": "value",
                "fieldValue": str(duration),
                "description": "视频时长",
            },
            {
                "nodeId": "5146",
                "fieldName": "value",
                "fieldValue": str(fps),
                "description": "每帧秒数",
            },
        ]
        self.logger.info(
            f"视频去水印请求参数: duration={duration}s, fps={fps}, prompt_len={len(prompt_text)}"
        )
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
            message=f"视频去水印 submit_task: {error_detail}",
            context={
                "api": "video_watermark_remove",
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
                f"Submitting video watermark task: duration={getattr(ai_tool, 'duration', None)}"
            )
            request_params = await self.build_create_request(ai_tool)
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during video watermark submit: {network_error}")
                return self._user_failure("网络连接异常，请稍后重试", retry=True)

            result = self._normalize_submit_result(result)
            self.logger.info(f"Video watermark API response: {result}")
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
                        f"Video watermark upstream congested: errorCode={error_code}, errorMessage={error_message}"
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

        except ImageExpiredError as exc:
            self.logger.warning(f"输入视频已过期: {exc}")
            return self._user_failure(str(exc))
        except ValueError as exc:
            # 参数校验类失败（时长/帧率/提示词越界、缺视频）：用户输入问题，重试无意义
            self.logger.warning(f"Video watermark submit rejected: {exc}")
            return self._user_failure(str(exc))
        except RuntimeError as exc:
            # 上传输入视频到 RunningHub 的瞬态失败（5xx/网络抖动）：可重试。
            # 修复前归入 USER 不可重试，瞬态抖动直接消耗用户一次任务走退费
            self.logger.warning(f"Video watermark upload transient failure, will retry: {exc}")
            return self._user_failure(f"视频上传失败，将自动重试: {exc}", retry=True)
        except Exception as exc:
            self.logger.error(f"Unexpected exception in video watermark submit_task: {exc}")
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
            self.logger.info(f"Checking video watermark task status: project_id={project_id}")
            try:
                status_result = self._request(**self.build_check_query(project_id))
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during video watermark status check: {network_error}")
                return {"status": "RUNNING", "message": "网络连接异常，稍后将重试"}

            if not isinstance(status_result, dict) or "code" not in status_result:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="视频去水印 status API 响应格式异常",
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
                    self.logger.error(f"Failed to get watermark outputs: {exc}")
                    return {
                        "status": "FAILED",
                        "error": "获取结果失败",
                        "error_type": "SYSTEM",
                        "error_detail": f"获取输出失败: {exc}",
                    }
                result_url = None
                if isinstance(outputs_result, dict) and outputs_result.get("code") == 0:
                    result_url = self._pick_result_url(outputs_result.get("data"))
                if not result_url:
                    self._send_alert(
                        alert_type="INVALID_RESPONSE_FORMAT",
                        message="视频去水印成功但没有视频结果",
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
            self.logger.error(f"Unexpected exception in video watermark check_status: {exc}")
            self.logger.error(traceback.format_exc())
            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"视频去水印 check_status 发生未预期异常: {exc}",
                context={"exception": str(exc), "traceback": traceback.format_exc(), "project_id": project_id},
            )
            return {
                "status": "FAILED",
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {exc}",
            }
