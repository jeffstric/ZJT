"""
MiniMax H3 图生视频 晨羽智云（chenyu.cn）工作流驱动

晨羽开放 API v2 将工作流包装为两步异步 HTTP API：
  1. 提交任务：POST {base_url}/api/open/v2/workflow/run/submit
     → 立即返回 data.run_order_id（run_status=queued）
  2. 轮询结果：GET {base_url}/api/open/v2/workflow/run/info?run_order_id={run_order_id}
     → data.run_status ∈ queued/running/succeeded/failed...
     → succeeded 后 data.outputs.n92_images[0] 为成片地址

认证：Authorization: Bearer {chenyu.api_key}（chenyu.cn 控制台「API 服务」页创建）。

媒体：开放 API 文档明说媒体字段可直接传公网 HTTPS URL —— 首帧经七牛 CDN 转公网，
无需走 /api/open/v2/assets 临时资源上传（大文件/复用/不便暴露公网时才需要，48h 有效）。

工作流 inputs（Minimax-H3图生视频 wf_fe451b10caa4bf0a7c99，仅首帧）：
- n105_104_prompt（String，必填）：提示词
- n114_image（MediaURI，必填）：首帧图片公网 URL（工作流无尾帧槽）
- n105_111_value（Number，必填）：秒数（任务层 4-10 档）
- n119_megapixels（Number，必填）：百万像素（480P→0.6 / 720P→1.0，上游档位 0.6=480p、1=768p；2026-11-09 修正——初版误设 0.5，事故 ai_tools 13444）
  工作流无比例参数，成片比例跟随首帧图

幂等：idempotency_key = zjt_h3_chenyu_{ai_tool.id}，调度层重试提交同一任务
不会在上游重复计费（重放响应 data.idempotent_replay=True）。

计费：提交时预冻结 quote（实测约 0.98 元/单，仅为上限），完成后按 GPU 实算
分钟数结算并释放差额（实测 4s@0.5MP 实扣 0.156 元，quote_amount 不可作为
成本口径）。run_status 实测流转：queued → running → pending_review → succeeded。
"""
import json
import traceback
from typing import Any, Dict, Optional, Tuple

import requests

from config.config_util import get_config, get_dynamic_config_value
from config.constant import (
    LEGACY_RESOLUTION_EXTRA_CONFIG_KEY,
    VIDEO_RESOLUTION_EXTRA_CONFIG_KEY,
)
from config.unified_config import DriverImplementation, TaskTypeId, VideoResolution
from utils.image_upload_utils import compress_and_upload_image_sync
from utils.sentry_util import AlertLevel, SentryUtil

from .base_video_driver import BaseVideoDriver

# ===== 工作流标识（晨羽控制台工作流 API 页；工作流更新走 revision，常量集中此处） =====
CHENYU_WORKFLOW_ID = "wf_fe451b10caa4bf0a7c99"
CHENYU_WORKFLOW_REVISION = "wfr_9088e3367308ac1939d0"

CHENYU_API_BASE_DEFAULT = "https://www.chenyu.cn"

# 分辨率标准值 → 工作流百万像素档（n119_megapixels）
# 480P→0.6 / 720P→1.0（上游档位 0.6=480p、1=768p；2026-11-09 修正——初版误设 0.5，
# 事故 ai_tools 13444：480P 任务实发 0.5）
RESOLUTION_TO_MEGAPIXELS = {
    VideoResolution.P480: 0.6,
    VideoResolution.P720: 1.0,
}
DEFAULT_MEGAPIXELS = 1.0

# 成片输出槽（succeeded 后 outputs.n92_images[0] 为视频地址）
OUTPUT_VIDEO_KEY = "n92_images"

# 查询状态归一（run_status 小写；失败态枚举保守覆盖，未知态不判死继续轮询，
# 任务过期检查负责终态兜底——口径同 AutoDL 驱动）
_SUCCESS_STATES = {"succeeded", "success", "completed"}
_FAILURE_STATES = {"failed", "error", "cancelled", "canceled", "timeout"}
# pending_review 为内容审核阶段（2026-11-08 E2E 实测出现），仍在执行流中
_RUNNING_STATES = {"queued", "running", "pending", "submitted", "pending_review"}


class MinimaxH3ChenyuV1Driver(BaseVideoDriver):
    """
    MiniMax H3 图生视频（晨羽智云工作流，仅首帧）

    挂载任务类型 34（与 RunningHub/AutoDL 实现方可切换），输入契约：
    - 首帧必填（image_path 首图）
    - 无尾帧槽：带尾帧任务经 validate_input_compatibility 判不兼容
      （重试候选选择换下一个实现，不静默丢尾帧约束）
    - 无音频槽（audio_path 输入忽略）
    """

    def __init__(self):
        super().__init__(
            driver_name=DriverImplementation.MINIMAX_H3_CHENYU_V1,
            driver_type=TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO,
        )

        # 加载配置（chenyu.api_key / chenyu.base_url 支持后台热更新）
        self._api_key = get_dynamic_config_value("chenyu", "api_key", default="")
        self._base_url = (
            get_dynamic_config_value("chenyu", "base_url", default=CHENYU_API_BASE_DEFAULT)
            or CHENYU_API_BASE_DEFAULT
        ).rstrip("/")
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)
        self._config = get_config()

        self._validate_required({
            "晨羽智云 API Key": self._api_key,
        })

        self._test_mode_enabled = get_dynamic_config_value("test_mode", "enabled", default=False)
        self._mock_video_url = get_dynamic_config_value(
            "test_mode", "mock_videos", default={}
        ).get("image_to_video")

    # ==================== 报警 / 辅助方法 ====================

    def _send_alert(self, alert_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        SentryUtil.send_alert(
            alert_type=alert_type,
            message=message,
            level=AlertLevel.ERROR,
            context=context
        )

    def _auth_headers(self) -> Dict[str, str]:
        """晨羽认证头：Authorization: Bearer {token}"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    def _extract_http_error_body(self, http_error) -> Optional[dict]:
        """从 HTTPError 中提取响应体 JSON（_request raise_for_status 丢弃响应体，这里重解析）"""
        try:
            response = getattr(http_error, "response", None)
            if response is None:
                return None
            return response.json()
        except (ValueError, AttributeError):
            return None

    def _parse_extra_config(self, ai_tool) -> Dict[str, Any]:
        """解析 extra_config JSON（非法输入回退空 dict，不中断提交）"""
        if not ai_tool.extra_config:
            return {}
        try:
            config = (
                ai_tool.extra_config
                if isinstance(ai_tool.extra_config, dict)
                else json.loads(ai_tool.extra_config)
            )
            return config if isinstance(config, dict) else {}
        except (ValueError, TypeError):
            self.logger.warning(f"无法解析 extra_config: {ai_tool.extra_config}")
            return {}

    def _get_megapixels(self, extra_config: Dict[str, Any]) -> float:
        """平台分辨率标准值 → 工作流百万像素档，未知值回落 1.0"""
        resolution = (
            extra_config.get(VIDEO_RESOLUTION_EXTRA_CONFIG_KEY)
            or extra_config.get(LEGACY_RESOLUTION_EXTRA_CONFIG_KEY)
        )
        megapixels = RESOLUTION_TO_MEGAPIXELS.get(resolution)
        if megapixels:
            return megapixels
        if resolution:
            self.logger.warning(f"晨羽驱动收到未知分辨率 {resolution}，回落 {DEFAULT_MEGAPIXELS}MP")
        return DEFAULT_MEGAPIXELS

    def _resolve_prompt(self, ai_tool, extra_config: Dict[str, Any]) -> str:
        """
        解析提示词（口径与 AutoDL/RunningHub H3 驱动一致）：
        优先使用 pipeline 优化结果（extra_config.h3_prompt_optimize.optimized_prompt），
        回退 ai_tool.prompt 原文
        """
        prompt_meta = extra_config.get("h3_prompt_optimize") if isinstance(extra_config, dict) else None
        if isinstance(prompt_meta, dict) and prompt_meta.get("optimized_prompt"):
            return str(prompt_meta.get("optimized_prompt") or "")
        return ai_tool.prompt or ""

    def _to_public_image_url(self, image_path: str, description: str) -> Tuple[Optional[str], Optional[str]]:
        """
        首帧转公网 URL（本地/局域网压缩后上传七牛 CDN，外网 URL 原样返回）

        Returns:
            (cdn_url, None) 或 (None, error_message)
        """
        success, url, error = compress_and_upload_image_sync(
            image_path, self._config, max_size_mb=10.0, is_local=True
        )
        if not success:
            return None, f"{description}处理失败: {error}"
        return url, None

    # ==================== 输入契约 ====================

    def validate_input_compatibility(self, ai_tool) -> Tuple[bool, Optional[str]]:
        """
        工作流仅支持首帧（n114_image，无尾帧槽）：带尾帧任务切到本实现会
        静默丢失尾帧约束，提前判不兼容换下一个候选（AutoDL/RunningHub 支持尾帧）。
        无首帧属参数错误，所有实现同样失败，不在此拦，留给驱动报准确错误。
        """
        image_info = self.get_all_images_by_mode(ai_tool)
        if image_info.get('first_frame') and image_info.get('last_frame'):
            return False, "晨羽 H3 图生视频工作流仅支持首帧，当前任务带尾帧"
        return True, None

    # ==================== 提交 ====================

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建提交请求参数（首帧转公网 URL + 工作流 inputs）

        Returns:
            成功：{"url", "method", "json", "headers"}
            失败：{"success": False, "error", "error_type", "retry"}
        """
        extra_config = self._parse_extra_config(ai_tool)

        # 首帧必填；尾帧存在仅告警（正常路径走不到——带尾帧任务在
        # validate_input_compatibility 已判不兼容；管理员手动切默认实现可能触发）
        image_info = self.get_all_images_by_mode(ai_tool)
        first_frame = image_info.get('first_frame')
        if not first_frame:
            return {
                "success": False,
                "error": "图生视频模式需要至少1张首帧图片",
                "error_type": "USER",
                "retry": False
            }
        if image_info.get('last_frame'):
            self.logger.warning(
                f"晨羽 H3 工作流不支持尾帧，已忽略尾帧输入（成片将不含尾帧约束）"
            )

        first_url, first_error = self._to_public_image_url(first_frame, "首帧图片")
        if first_error:
            return {
                "success": False,
                "error": first_error,
                "error_type": "USER",
                "retry": False
            }

        prompt_text = self._resolve_prompt(ai_tool, extra_config)
        if getattr(ai_tool, "audio_path", None):
            self.logger.info("晨羽 H3 工作流不支持参考音频，已忽略音频输入")

        payload = {
            "workflow_id": CHENYU_WORKFLOW_ID,
            "revision_id": CHENYU_WORKFLOW_REVISION,
            # 幂等键按任务生成：调度层重试提交同一任务不重复计费
            "idempotency_key": f"zjt_h3_chenyu_{ai_tool.id}",
            "accept_external_cost_risk": False,
            "inputs": {
                "n105_104_prompt": prompt_text,
                "n114_image": first_url,
                "n105_111_value": int(ai_tool.duration or 5),
                "n119_megapixels": self._get_megapixels(extra_config),
            },
        }

        return {
            "url": f"{self._base_url}/api/open/v2/workflow/run/submit",
            "method": "POST",
            "json": payload,
            "headers": self._auth_headers(),
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """构建状态查询请求参数"""
        return {
            "url": f"{self._base_url}/api/open/v2/workflow/run/info",
            "method": "GET",
            "params": {"run_order_id": project_id},
            "headers": self._auth_headers(),
        }

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交图生视频任务到晨羽开放 API

        Returns:
            成功：{"success": True, "project_id": run_order_id}
            失败：{"success": False, "error": ..., "error_type": ..., "retry": ...}
        """
        task_id = ai_tool.id

        try:
            # 1. 构建请求参数（素材缺失/上传失败时 build_create_request 返回错误）
            request_params = self.build_create_request(ai_tool)
            if "success" in request_params and not request_params["success"]:
                return request_params

            # 测试模式：返回 mock 数据，避免实际 API 调用和费用
            if self._test_mode_enabled:
                mock_project_id = f"test-chenyu-{task_id}"
                self.logger.info(f"[TEST MODE] 返回模拟 run_order_id: {mock_project_id}")
                return {
                    "success": True,
                    "project_id": mock_project_id
                }

            # 2. 发送请求
            try:
                result = self._request(
                    url=request_params["url"],
                    method=request_params["method"],
                    json=request_params["json"],
                    headers=request_params["headers"],
                    timeout=self._timeout,
                )
            except requests.exceptions.HTTPError as http_error:
                status_code = getattr(getattr(http_error, "response", None), "status_code", None)
                error_body = self._extract_http_error_body(http_error)
                msg = str(error_body.get("msg")) if isinstance(error_body, dict) and error_body.get("msg") else ""
                if status_code == 429:
                    # 限流：友好提示 + 允许重试
                    self.logger.warning(f"晨羽提交限流(429): {msg}")
                    return {
                        "success": False,
                        "error": "上游限流，请稍后重试",
                        "error_type": "USER",
                        "retry": True
                    }
                if msg:
                    # 参数/鉴权等业务错误：用户错误，不重试
                    return {
                        "success": False,
                        "error": f"任务提交失败: {msg}",
                        "error_type": "USER",
                        "retry": False
                    }
                self._send_alert(
                    alert_type="API_HTTP_ERROR",
                    message=f"晨羽 submit_task HTTP 错误: {str(http_error)}",
                    context={"task_id": task_id, "status_code": status_code}
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": str(http_error),
                    "retry": False
                }
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during chenyu task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(
                f"晨羽 H3 工作流提交响应: code={result.get('code') if isinstance(result, dict) else result}"
            )

            # 3. 业务错误（code != 0；晨羽业务错误走 HTTP 200 + code!=0）
            if not isinstance(result, dict):
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"晨羽提交响应格式错误: 非字典类型 {type(result)}",
                    context={"task_id": task_id}
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: 非字典类型 {type(result)}",
                    "retry": False
                }
            if result.get("code") != 0:
                error_msg = str(result.get("msg") or result.get("code") or "任务提交失败")
                self.logger.warning(f"晨羽 H3 工作流提交失败: {error_msg}")
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_msg}",
                    "error_type": "USER",
                    "retry": False
                }

            data = result.get("data")
            run_order_id = data.get("run_order_id") if isinstance(data, dict) else None
            if not run_order_id:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"晨羽提交响应缺少 run_order_id: {result}",
                    context={"task_id": task_id}
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应缺少 run_order_id: {result}",
                    "retry": False
                }

            # 幂等重放留痕（调度重试时上游不重复计费）
            if isinstance(data, dict) and data.get("idempotent_replay"):
                self.logger.info(f"晨羽提交命中幂等重放（未重复计费）: task_id={task_id}")

            return {
                "success": True,
                "project_id": run_order_id,
            }

        except Exception as e:
            self.logger.error(f"Unexpected error in chenyu submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())
            self._send_alert(
                alert_type="SUBMIT_UNEXPECTED_ERROR",
                message=f"晨羽 submit_task 未预期异常: {str(e)}",
                context={"task_id": task_id}
            )
            return {
                "success": False,
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": str(e),
                "retry": False
            }

    # ==================== 查询状态 ====================

    def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        检查晨羽任务状态

        run_status（data.run_status，小写归一）:
            queued / running / pending / submitted → 轮询等待
            succeeded → 成功，outputs.n92_images[0] 为成片地址
            failed / error / cancelled → 失败（error_message 带原因）
            未知状态不判死继续轮询（任务过期检查负责终态兜底）

        Returns:
            {"status": "RUNNING"} /
            {"status": "SUCCESS", "result_url": ...} /
            {"status": "FAILED", "message": ...}
        """
        try:
            # 测试模式：返回 mock 数据
            if self._test_mode_enabled and self._mock_video_url:
                self.logger.info(f"[TEST MODE] 返回模拟视频结果: {self._mock_video_url}")
                return {
                    "status": "SUCCESS",
                    "result_url": self._mock_video_url
                }

            try:
                request_params = self.build_check_query(project_id)
                result = self._request(
                    url=request_params["url"],
                    method=request_params["method"],
                    params=request_params.get("params"),
                    headers=request_params["headers"],
                    timeout=self._timeout,
                )
            except requests.exceptions.HTTPError as http_error:
                status_code = getattr(getattr(http_error, "response", None), "status_code", None)
                if status_code in (429, 404):
                    # 限流/刚提交传播延迟：按处理中等待（任务过期检查负责终态兜底）
                    self.logger.warning(
                        f"晨羽状态查询 {status_code}（可能限流/传播中）: run_order_id={project_id}"
                    )
                    return {
                        "status": "RUNNING",
                        "message": "任务查询暂不可用，稍后将重试"
                    }
                error_body = self._extract_http_error_body(http_error)
                msg = str(error_body.get("msg")) if isinstance(error_body, dict) and error_body.get("msg") else str(http_error)
                return {
                    "status": "FAILED",
                    "message": f"任务查询失败: {msg}"
                }
            except (ConnectionError, TimeoutError) as network_error:
                # 网络抖动不判死，等待下次轮询
                self.logger.warning(f"Network error during chenyu status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络异常，稍后将重试"
                }

            if not isinstance(result, dict):
                self._send_alert(
                    alert_type="INVALID_STATUS_RESPONSE",
                    message=f"晨羽状态查询响应格式错误: 非字典类型 {type(result)}",
                    context={"run_order_id": project_id}
                )
                return {
                    "status": "FAILED",
                    "message": "服务异常，请联系技术支持"
                }

            # 业务错误（code != 0）：订单不存在可能是刚提交的传播延迟，按处理中等待
            if result.get("code") != 0:
                error_msg = str(result.get("msg") or result.get("code") or "查询失败")
                if "不存在" in error_msg:
                    self.logger.warning(
                        f"晨羽状态查询订单不存在（可能仍在传播）: run_order_id={project_id}"
                    )
                    return {
                        "status": "RUNNING",
                        "message": "任务查询暂不可用，稍后将重试"
                    }
                return {
                    "status": "FAILED",
                    "message": f"任务查询失败: {error_msg}"
                }

            data = result.get("data")
            if not isinstance(data, dict):
                self._send_alert(
                    alert_type="INVALID_STATUS_RESPONSE",
                    message=f"晨羽状态查询响应缺少 data: {result}",
                    context={"run_order_id": project_id}
                )
                return {
                    "status": "FAILED",
                    "message": "服务异常，请联系技术支持"
                }

            run_status = str(data.get("run_status") or "").lower()

            if run_status in _SUCCESS_STATES:
                outputs = data.get("outputs")
                video_urls = (
                    outputs.get(OUTPUT_VIDEO_KEY)
                    if isinstance(outputs, dict) else None
                )
                result_url = video_urls[0] if isinstance(video_urls, list) and video_urls else None
                if not result_url:
                    self._send_alert(
                        alert_type="INVALID_STATUS_RESPONSE",
                        message=f"晨羽任务成功但缺少成片输出: {data}",
                        context={"run_order_id": project_id}
                    )
                    return {
                        "status": "FAILED",
                        "message": "服务异常，请联系技术支持"
                    }
                return {
                    "status": "SUCCESS",
                    "result_url": result_url
                }

            if run_status in _FAILURE_STATES:
                error_msg = str(data.get("error_message") or data.get("error_code") or "任务失败")
                return {
                    "status": "FAILED",
                    "message": f"任务失败: {error_msg}"
                }

            if run_status in _RUNNING_STATES:
                return {
                    "status": "RUNNING"
                }

            # 未知状态：不判死继续轮询（口径同 AutoDL 驱动，过期检查兜底）
            self.logger.warning(
                f"晨羽未知 run_status={run_status}，继续轮询: run_order_id={project_id}"
            )
            return {
                "status": "RUNNING",
                "message": f"未知状态 {run_status}，继续等待"
            }

        except Exception as e:
            self.logger.error(f"Unexpected error in chenyu check_status: {str(e)}")
            self.logger.error(traceback.format_exc())
            self._send_alert(
                alert_type="STATUS_CHECK_UNEXPECTED_ERROR",
                message=f"晨羽 check_status 未预期异常: {str(e)}",
                context={"run_order_id": project_id}
            )
            return {
                "status": "FAILED",
                "message": "服务异常，请联系技术支持"
            }
