"""
RunningHub 视频高清修复驱动

通过 RunningHub OpenAPI v2 AI-App 调用「视频高清放大」工作流。

参数注入节点：
  - 视频       → nodeId 46  fieldName=video（VHS 加载，传上传后的 fileName 或公网 URL）
  - 模型切换   → nodeId 108 fieldName=select（"1"）
  - 最大分辨率 → nodeId 112 fieldName=value（用户可选，白名单外回落 schema default）

用户可选参数由 VIDEO_ENHANCE_PARAMS_SCHEMA（config/unified_config.py）定义：
透传到 extra_config["params"]，驱动按 schema 逐项校验（不信任库数据，
非法值回落 default）后经 node_id/field_name 映射到节点值。

算力：按视频秒数 4-15 档计费，为 MiniMax H3 梯度的 2 倍
（表 VIDEO_ENHANCE_COMPUTING_POWER；档位由提交端点 ffprobe 探测后落库 duration）。

状态查询：v2 提交的任务用 v1 /task/openapi/status + /task/openapi/outputs 轮询
（与视频去水印一致，两端点同任务池已验证）。
失败原因透出：v1 status 失败只回 data='FAILED' 不带原因，FAILED 终态时补查
v2 /openapi/v2/query 取 failedReason，分类映射为用户可见文案
（2026-11 任务 13579/13908 实测上游审核拒绝 audit.RHAuditException 'Porn'
在用户界面只显示笼统「任务失败」，见 docs/backend/video_enhance_runninghub_v2.md）。
"""
import json
import traceback
from typing import Any, Dict, List, Optional, Tuple

from config.config_util import get_config, get_dynamic_config_value
from config.constant import (
    VIDEO_ENHANCE_MAX_DURATION_SECONDS,
    VIDEO_ENHANCE_MIN_DURATION_SECONDS,
)
from config.unified_config import (
    TaskTypeId,
    VIDEO_ENHANCE_COMPUTING_POWER,
    VIDEO_ENHANCE_PARAMS_SCHEMA,
)
from utils.content_moderation_error import FRIENDLY_PREFIX
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
# 最大分辨率缺省回落值；用户可选值由 VIDEO_ENHANCE_PARAMS_SCHEMA 定义（unified_config）
VIDEO_ENHANCE_MAX_RESOLUTION_VALUE = '1920'
# default=24G 显存 / plus=48G / ultra=84G。SeedVR2 视频超分实测 default 必爆显存
# （torch.OutOfMemoryError，2026-10-28 任务 2115435158520954881），须用 plus（48G）
VIDEO_ENHANCE_INSTANCE_TYPE = 'plus'

VIDEO_RESULT_EXTENSIONS = (".mp4", ".webm", ".mov", ".mkv")

# ==================== FAILED 终态失败原因透出（v2 /openapi/v2/query 兜底） ====================
# v2 查询端点（与 api/clients/runninghub_client.py query_v2_task 同源，Bearer 认证）
VIDEO_ENHANCE_V2_QUERY_PATH = '/openapi/v2/query'
# 审核拒绝（failedReason.exception_type = audit.RHAuditException，实测样本
# exception_message='Porn'，节点 VHS_VideoCombine）的用户文案。以 FRIENDLY_PREFIX
# 开头，保证 ai_tools.message → /api/get-status 的 is_content_violation 识别为
# 内容违规（营销链路据此引导），且 visual_task._normalize_failure_reason 原样放行
VIDEO_ENHANCE_AUDIT_FAILED_MESSAGE = (
    f"{FRIENDLY_PREFIX}：视频内容未通过平台安全审核，请更换视频后重试"
)
# 显存溢出（torch.OutOfMemoryError）：plus 实例 48G 仍可能被超长视频打爆
VIDEO_ENHANCE_OOM_FAILED_MESSAGE = "视频处理失败：上游 GPU 显存不足，请稍后重试"
# 上游 errorMessage 中无信息量的通用话术（工作流失败笼统描述），不透传给用户
VIDEO_ENHANCE_GENERIC_WORKFLOW_ERROR = "工作流运行失败"
# 用户可见失败摘要最大长度（防上游异常文本过长污染 ai_tools.message）
VIDEO_ENHANCE_FAILED_REASON_MAX_LEN = 200


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

    def _parse_extra_config(self, ai_tool) -> Dict[str, Any]:
        """解析 ai_tools.extra_config（兼容 JSON 字符串与字典；解析失败按空处理）。"""
        raw = getattr(ai_tool, "extra_config", None)
        if not raw:
            return {}
        try:
            config = raw if isinstance(raw, dict) else json.loads(raw)
            return config if isinstance(config, dict) else {}
        except (json.JSONDecodeError, TypeError):
            self.logger.warning(f"无法解析 extra_config: {raw}")
            return {}

    def _resolve_schema_params(self, ai_tool) -> Dict[str, str]:
        """按 VIDEO_ENHANCE_PARAMS_SCHEMA 逐项解析用户参数（列表驱动，不信任库数据）。

        缺省回落 schema default；值不在 options 白名单内的非法值告警后回落 default。
        """
        raw_params = self._parse_extra_config(ai_tool).get("params") or {}
        if not isinstance(raw_params, dict):
            self.logger.warning(f"extra_config.params 不是对象，忽略: {raw_params}")
            raw_params = {}
        resolved: Dict[str, str] = {}
        for item in VIDEO_ENHANCE_PARAMS_SCHEMA:
            key = item.get("key")
            default = item.get("default")
            value = raw_params.get(key, default)
            allowed = {
                opt.get("value") for opt in item.get("options", []) if isinstance(opt, dict)
            }
            if value not in allowed:
                if value != default:
                    self.logger.warning(
                        f"视频高清修复参数 {key}={value} 不在白名单 {sorted(allowed)}，"
                        f"回落 default={default}"
                    )
                value = default
            resolved[key] = value
        return resolved

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
        schema_params = self._resolve_schema_params(ai_tool)
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
                "fieldValue": schema_params.get(
                    "max_resolution", VIDEO_ENHANCE_MAX_RESOLUTION_VALUE
                ),
                "description": "最大分辨率",
            },
        ]
        self.logger.info(
            f"视频高清修复请求参数: duration={duration}s 档, "
            f"max_resolution={schema_params.get('max_resolution')}"
        )
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

    def _build_v2_query_request(self, project_id: str) -> Dict[str, Any]:
        # v2 端点认证走 Authorization Bearer 头（v1 status 是 apiKey 放 body，两者不同；
        # 缺 Bearer 头上游返回 code=1602 HEADER_API_KEY_NOT_FOUND）
        return {
            "url": f"{self._host}{VIDEO_ENHANCE_V2_QUERY_PATH}",
            "method": "POST",
            "json": {"taskId": project_id},
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        }

    def _query_v2_failure_detail(self, project_id: str) -> Optional[Dict[str, Any]]:
        """FAILED 终态补查 v2 /openapi/v2/query 拿 failedReason。

        查询失败只记告警返回 None，不影响上层「任务失败」兜底文案
        （终态已定，二次查询属于增强信息，不允许把它变成新故障点）。
        """
        try:
            result = self._request(**self._build_v2_query_request(project_id))
        except Exception as exc:
            self.logger.warning(f"Video enhance v2 query failed for task {project_id}: {exc}")
            return None
        return result if isinstance(result, dict) else None

    def _resolve_failed_error(self, project_id: str) -> Tuple[str, str, Optional[str]]:
        """构造 FAILED 终态的用户可见错误，返回 (error, error_type, error_detail)。

        分类映射：
        - 审核拒绝（exception_type 含 audit，如 audit.RHAuditException）→
          FRIENDLY_PREFIX 审核文案（USER）
        - 显存溢出（OutOfMemoryError）→ 显存不足提示（SYSTEM）
        - 其余 → 透传上游异常摘要（USER）；v2 查询失败或无有效细节 → 回落
          「任务失败」（维持旧行为，error_detail 为 None）
        """
        query_result = self._query_v2_failure_detail(project_id)
        if not query_result:
            return "任务失败", "USER", None

        error_message = str(query_result.get("errorMessage") or "").strip()
        raw_failed_reason = query_result.get("failedReason")
        failed_reason = raw_failed_reason if isinstance(raw_failed_reason, dict) else {}
        exception_type = str(failed_reason.get("exception_type") or "").strip()
        exception_message = str(failed_reason.get("exception_message") or "").strip()
        node_name = str(failed_reason.get("node_name") or "").strip()

        # 完整原始细节只进调度进程日志（app log），不进用户可见 message
        try:
            reason_blob = json.dumps(failed_reason, ensure_ascii=False) if failed_reason else error_message
        except (TypeError, ValueError):
            reason_blob = str(failed_reason or error_message)
        self.logger.warning(
            f"Video enhance task {project_id} upstream FAILED: "
            f"errorCode={query_result.get('errorCode')}, errorMessage={error_message}, "
            f"failedReason={reason_blob}"
        )
        error_detail = f"errorCode={query_result.get('errorCode')}, failedReason={reason_blob}"

        lowered_type = exception_type.lower()
        lowered_message = exception_message.lower()
        if "audit" in lowered_type or "audit" in lowered_message:
            return VIDEO_ENHANCE_AUDIT_FAILED_MESSAGE, "USER", error_detail
        if "outofmemory" in lowered_type or "outofmemory" in lowered_message:
            return VIDEO_ENHANCE_OOM_FAILED_MESSAGE, "SYSTEM", error_detail

        # 兜底透传：优先异常摘要（node: message），errorMessage 的
        # 「工作流运行失败」无信息量不透传
        summary = exception_message
        if not summary and error_message and error_message != VIDEO_ENHANCE_GENERIC_WORKFLOW_ERROR:
            summary = error_message
        if not summary:
            return "任务失败", "USER", error_detail
        if node_name:
            summary = f"{node_name}: {summary}"
        summary = summary[:VIDEO_ENHANCE_FAILED_REASON_MAX_LEN]
        return f"视频处理失败：{summary}", "USER", error_detail

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
                # v1 status 不带失败原因：补查 v2 /query 分类透出（审核拒绝/显存溢出等）
                error, error_type, error_detail = self._resolve_failed_error(project_id)
                return {
                    "status": "FAILED",
                    "error": error,
                    "error_type": error_type,
                    "error_detail": error_detail,
                }

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
