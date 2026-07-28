"""
Seedance kkidc 网关 v1 版本驱动实现
异步 API - 创建任务后轮询状态

kkidc 是火山 Seedance 的二次封装网关，接口结构与火山原生完全不同：
- 请求体：扁平 prompt + metadata{} 结构（火山为 content[] 数组）
- 创建路径：POST /v1/video/generations
- 查询路径：GET  /v1/video/generations/{task_id}
- 三段式响应：{code, message, data:{...}}

支持模型：Seedance 2.0 Fast / 2.0 / 2.0 Mini（与火山国内版同质，作为备选实现）
支持能力：文生视频、首帧/首尾帧图生视频、多参考图（含参考音视频）

注意：kkidc 网关使用自有的模型别名（seed-2 / seed-2-fast / seed-2-mini），
非火山原生模型名（doubao-seedance-*-26xxxx）。1.5 Pro 不对接。

基类 SeedanceKkidcV1Driver 包含核心逻辑，
子类通过 driver_type 和 model_name 区分不同模型。
"""
from typing import Dict, Any, Optional
import os
import traceback
import json
import uuid

import requests

# 防御：确保 requests 是真实模块（而非被测试 sys.modules 污染成的 MagicMock）。
# 本驱动用 requests.exceptions.HTTPError 捕获 4xx/5xx，若 requests 被 mock，
# except 会失效。模块加载时若发现 requests 异常，强制重载真实模块。
if not hasattr(requests, 'exceptions') or not hasattr(requests.exceptions, 'HTTPError'):
    import importlib
    import sys as _sys
    _sys.modules.pop('requests', None)
    _sys.modules.pop('requests.exceptions', None)
    requests = importlib.import_module('requests')

from .base_video_driver import BaseVideoDriver, ImageMode
from config.config_util import get_config, get_dynamic_config_value
from config.constant import LEGACY_RESOLUTION_EXTRA_CONFIG_KEY, VIDEO_RESOLUTION_EXTRA_CONFIG_KEY
from config.unified_config import DriverImplementation, VideoResolution
from utils.sentry_util import SentryUtil, AlertLevel
from utils.image_upload_utils import compress_and_upload_image_sync, upload_media_to_cdn_sync
from utils.video_compressor import prepare_seedance_reference_video_sync
from model.ai_tool_pipeline_steps import PipelineStepModel, PipelineStepStatus, PipelineStepType, PipelineStage


# kkidc 网关接口文档（内部）
# 创建：POST https://ai-api.kkidc.com/v1/video/generations
# 查询：GET  https://ai-api.kkidc.com/v1/video/generations/{task_id}

# 各分辨率标准值 → kkidc metadata.resolution 下发值（与火山一致，均小写）
SEEDANCE_KKIDC_RESOLUTION_DRIVER_VALUES = VideoResolution.SEEDANCE_DRIVER_VALUES


def _cleanup_seedance_reference_video_temps(paths):
    """清理参考视频规范化产生的临时文件"""
    for path in paths or []:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


class SeedanceKkidcV1Driver(BaseVideoDriver):
    """
    Seedance kkidc 网关 v1 版本驱动（基类）
    异步 API - 图生视频 / 文生视频

    子类通过不同的 driver_type 和 model_name 区分模型。

    注意：不应直接实例化基类，应使用具体的子类。
    """

    def __init__(self, driver_type: int, model_name: str, impl_name: str = DriverImplementation.SEEDANCE_2_0_KKIDC_V1):
        """
        初始化驱动

        Args:
            driver_type: 驱动类型（对应 TaskTypeId）
            model_name: 模型名称（如 doubao-seedance-1-5-pro-251215）
            impl_name: 实现方名称，需与 IMPLEMENTATION_TO_ID 映射一致
        """
        super().__init__(driver_name=impl_name, driver_type=driver_type)

        # 加载配置
        self._api_key = get_dynamic_config_value("kkidc", "api_key", default="")
        self._base_url = get_dynamic_config_value(
            "kkidc", "base_url",
            default="https://ai-api.kkidc.com/v1"
        )
        # 去除尾部斜杠，避免路径拼接出现双斜杠
        self._base_url = self._base_url.rstrip("/")
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        # 模型名称
        self._model = model_name

        # 是否为本地环境
        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        # 测试模式配置
        self._test_mode_enabled = get_dynamic_config_value("test_mode", "enabled", default=False)
        self._mock_video_url = get_dynamic_config_value("test_mode", "mock_videos", default={}).get("image_to_video")

        self._validate_required({
            "kkidc API Key": self._api_key,
        })

    # ==================== 报警 / 辅助方法 ====================

    def _send_alert(self, alert_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        """发送报警信息"""
        SentryUtil.send_alert(
            alert_type=alert_type,
            message=message,
            level=AlertLevel.ERROR,
            context=context
        )

    def _resolve_video_path_with_face_mask(self, ai_tool, video_path: str) -> str:
        """
        查找 face_mask pipeline step 的遮盖结果替换原始视频路径

        如果 ai_tool_pipeline_steps 中存在 target 匹配的已完成 face_mask 步骤，
        使用其 result_url（人脸遮盖后的视频）替代原始路径，避免审核不通过。
        """
        try:
            steps = PipelineStepModel.get_by_ai_tool_and_stage(ai_tool.id, PipelineStage.PARAM_PREPARE)
            for step in steps:
                if (step.step_type == PipelineStepType.FACE_MASK
                        and step.status == PipelineStepStatus.COMPLETED
                        and step.target == video_path
                        and step.result_url):
                    result_url = step.result_url
                    if result_url.startswith("/"):
                        result_url = result_url.lstrip('/')
                    if not os.path.exists(result_url):
                        self.logger.warning(f"face_mask 结果文件不存在: {result_url}，使用原始路径")
                        return video_path
                    self.logger.info(f"使用 face_mask 结果替换视频: {video_path} -> {result_url}")
                    return result_url
        except Exception as e:
            self.logger.warning(f"查询 face_mask pipeline step 失败，使用原始路径: {e}")
        return video_path

    def _resolve_image_path_with_face_mask(self, ai_tool, image_path: str) -> str:
        """
        查找 image_face_mask pipeline step 的遮盖结果替换原始图片路径

        与 _resolve_video_path_with_face_mask 对称：若存在 target 匹配的已完成
        image_face_mask 步骤，使用其 result_url 替代原始路径，避免审核不通过。
        """
        if not image_path:
            return image_path
        try:
            steps = PipelineStepModel.get_by_ai_tool_and_stage(ai_tool.id, PipelineStage.PARAM_PREPARE)
            for step in steps:
                if (step.step_type == PipelineStepType.IMAGE_FACE_MASK
                        and step.status == PipelineStepStatus.COMPLETED
                        and step.target == image_path
                        and step.result_url):
                    self.logger.info(f"使用 image_face_mask 结果替换图片: {image_path} -> {step.result_url}")
                    return step.result_url
        except Exception as e:
            self.logger.warning(f"查询 image_face_mask pipeline step 失败，使用原始路径: {e}")
        return image_path

    def _parse_extra_config(self, ai_tool) -> Dict[str, Any]:
        """解析 extra_config JSON"""
        if not ai_tool.extra_config:
            return {}
        try:
            config = ai_tool.extra_config if isinstance(ai_tool.extra_config, dict) else json.loads(ai_tool.extra_config)
            return config if isinstance(config, dict) else {}
        except (json.JSONDecodeError, TypeError):
            self.logger.warning(f"无法解析 extra_config: {ai_tool.extra_config}")
            return {}

    def _get_resolution_for_payload(self, extra_config: Dict[str, Any]) -> Optional[str]:
        """获取 metadata.resolution 下发值，优先使用新 video_resolution 字段。"""
        resolution = (
            extra_config.get(VIDEO_RESOLUTION_EXTRA_CONFIG_KEY)
            or extra_config.get(LEGACY_RESOLUTION_EXTRA_CONFIG_KEY)
        )
        if not resolution:
            return None
        return SEEDANCE_KKIDC_RESOLUTION_DRIVER_VALUES.get(str(resolution).upper())

    # ==================== 响应校验 ====================

    @staticmethod
    def _extract_task_id(result: Any) -> Optional[str]:
        """
        从创建任务响应中提取 task_id，兼容两种结构：
        - 三段式：{ code, message, data: { task_id } }
        - 扁平式：{ id, task_id, object, model, status, ... }（顶层即 task_id）
        """
        if not isinstance(result, dict):
            return None
        # 三段式优先
        data = result.get("data")
        if isinstance(data, dict) and data.get("task_id"):
            return data.get("task_id")
        # 扁平式回退（顶层 task_id 或 id）
        return result.get("task_id") or result.get("id")

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 submit_task API 响应格式

        兼容两种结构：
        - 三段式：{ code, message, data: { task_id } }
        - 扁平式：{ id, task_id, object, model, status, progress, created_at }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        # 错误响应：{ error: { message, type, code } }
        if "error" in result:
            error_info = result.get("error", {})
            if not isinstance(error_info, dict):
                error_info = {"message": str(error_info)}
            from utils.content_moderation_error import format_user_facing_moderation_error

            friendly = format_user_facing_moderation_error(
                error_code=error_info.get("code"),
                error_message=error_info.get("message"),
                error_type=error_info.get("type"),
            )
            if friendly:
                return False, friendly
            error_code = error_info.get("code", "Unknown")
            error_message = error_info.get("message", "未知错误")
            return False, f"API 错误 [{error_code}]: {error_message}"

        # 正常响应：能提取到 task_id 即视为有效
        task_id = self._extract_task_id(result)
        if not task_id:
            return False, f"响应缺少 task_id（顶层与 data.task_id 均无），实际字段: {list(result.keys())}"

        return True, None

    def _validate_status_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 check_status API 响应格式

        兼容两种结构：
        - 三段式：{ data: { task_id, status, data: { status, content: { video_url } } } }
        - 扁平式：{ id, task_id, status, video_url, ... }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        # 兼容三段式 { data: {...} } 与扁平式 { status, video_url, ... }
        data = result.get("data") if isinstance(result.get("data"), dict) else result

        if "task_id" not in data and "id" not in data:
            return False, f"响应缺少 task_id/id，实际字段: {list(data.keys())}"

        if "status" not in data:
            return False, f"响应缺少 'status' 字段，实际字段: {list(data.keys())}"

        return True, None

    @staticmethod
    def _extract_status_data(result: Any) -> Dict[str, Any]:
        """
        从查询响应中提取状态数据块，兼容两种结构：
        - 三段式：{ data: { status, data: { status, content: { video_url } } } }
        - 扁平式：{ status, video_url, ... }（顶层即状态数据）

        返回包含归一化状态、video_url、fail_reason 的扁平 dict。
        status 取外层（三段式大写枚举或扁平式小写值），inner_status 取内层小写（三段式独有）。
        """
        if not isinstance(result, dict):
            return {}
        outer = result.get("data") if isinstance(result.get("data"), dict) else result
        # 内层 data（三段式独有，承载 video_url / 上游小写 status）
        inner = outer.get("data") if isinstance(outer.get("data"), dict) else {}

        # 外层 status 原样保留（可能大写 SUCCESS 也可能小写 succeeded）
        raw_status = str(outer.get("status", ""))
        return {
            "status": raw_status,
            "status_upper": raw_status.upper(),
            "inner_status": str(inner.get("status", "")).lower() if inner else "",
            "fail_reason": outer.get("fail_reason") if isinstance(outer.get("fail_reason"), str) else None,
            "video_url": (inner.get("content", {}) or {}).get("video_url") if isinstance(inner, dict) else None,
        }

    # 成功态集合（大小写均含，覆盖三段式大写枚举与扁平式/上游小写值）
    _SUCCESS_STATES = {"SUCCESS", "SUCCEEDED"}
    _FAILURE_STATES = {"FAILURE", "FAILED", "EXPIRED"}
    _RUNNING_STATES = {"QUEUED", "RUNNING", "IN_PROGRESS", "NOT_START", "SUBMITTED", "PENDING", "UNKNOWN", ""}

    # ==================== 构建请求 ====================

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建 kkidc 创建任务请求（图生视频 / 文生视频）

        模式（互斥）：
        - text_to_video: 文生视频，无图片/音视频输入，payload 只放 prompt + metadata
        - first_last_frame: 首帧/首尾帧模式，metadata 放 first_frame_image / last_frame_image
        - multi_reference: 多模态参考模式，metadata 放 reference_images / reference_videos / reference_audios

        文生视频判定：无首/尾帧、无参考图、无参考视频/音频，且 extra_config 未声明 image_mode。
        """
        # 1. 解析 extra_config 和图片模式
        extra_config = self._parse_extra_config(ai_tool)
        all_images_info = self.get_all_images_by_mode(ai_tool)
        img_mode = all_images_info['mode']
        first_frame = all_images_info.get('first_frame')
        last_frame = all_images_info.get('last_frame')
        reference_images = all_images_info.get('reference_images', [])

        prompt = ai_tool.prompt or ""

        # 2. 文生视频判定：无任何图片/音视频输入，且 extra_config 未声明 image_mode
        reference_video_raw = self.get_video_path(ai_tool) or extra_config.get('reference_video')
        reference_audio_raw = self.get_audio_path(ai_tool) or extra_config.get('reference_audio')
        is_text_to_video = (
            not first_frame and not last_frame and not reference_images
            and not reference_video_raw and not reference_audio_raw
            and 'image_mode' not in extra_config
        )

        # 3. 构建 metadata（所有模式通用字段）
        metadata: Dict[str, Any] = {}

        if extra_config.get('generate_audio') is not None:
            metadata["generate_audio"] = extra_config['generate_audio']

        ratio = extra_config.get('ratio') or ai_tool.ratio
        if ratio:
            metadata["ratio"] = ratio

        if ai_tool.duration:
            metadata["duration"] = ai_tool.duration

        if extra_config.get('watermark') is not None:
            metadata["watermark"] = extra_config['watermark']

        resolution = self._get_resolution_for_payload(extra_config)
        if resolution:
            metadata["resolution"] = resolution

        # 4. 根据输入分支构建 payload 顶层
        # 文生视频分支顶层只有 prompt；图生视频分支有 image / metadata 内嵌图片字段
        top_image: Optional[str] = None  # 首帧图生视频专用顶层 image 字段

        if is_text_to_video:
            # ---- 文生视频模式（纯文本，无图片/音视频输入）----
            self.logger.info("文生视频模式: 无任何图片/音视频输入")
            if not prompt.strip():
                return {
                    "success": False,
                    "error": "文生视频模式需要输入提示词",
                    "error_type": "USER",
                    "retry": False
                }

        elif img_mode == ImageMode.FIRST_LAST_FRAME or img_mode == ImageMode.FIRST_LAST_WITH_REF:
            # ---- 首帧/首尾帧模式 ----
            self.logger.info(f"首尾帧模式: first_frame={first_frame}, last_frame={last_frame}")

            if not first_frame:
                return {
                    "success": False,
                    "error": "首尾帧模式需要至少1张首帧图片",
                    "error_type": "USER",
                    "retry": False
                }

            # 处理首帧图片
            first_frame = self._resolve_image_path_with_face_mask(ai_tool, first_frame)
            success, processed_url, error = compress_and_upload_image_sync(
                first_frame, self._config, max_size_mb=10.0, is_local=True
            )
            if not success:
                self.logger.error(f"处理首帧图片失败: {error}")
                return {
                    "success": False,
                    "error": f"处理首帧图片失败: {error}",
                    "error_type": "USER",
                    "retry": False
                }

            # 处理尾帧图片（可选）
            processed_last_frame = None
            if last_frame:
                last_frame = self._resolve_image_path_with_face_mask(ai_tool, last_frame)
                success_lf, url_lf, error_lf = compress_and_upload_image_sync(
                    last_frame, self._config, max_size_mb=10.0, is_local=True
                )
                if success_lf:
                    processed_last_frame = url_lf
                else:
                    self.logger.warning(f"处理尾帧图片失败，跳过: {error_lf}")

            if processed_last_frame:
                # 首尾帧模式：metadata 内嵌 first_frame_image / last_frame_image
                metadata["first_frame_image"] = processed_url
                metadata["last_frame_image"] = processed_last_frame
            else:
                # 仅首帧模式：用顶层 image 字段（API 文档规范）
                top_image = processed_url

        elif img_mode == ImageMode.MULTI_REFERENCE:
            # ---- 多模态参考模式 ----
            self.logger.info(f"多参考图模式: reference_images={len(reference_images)}张")

            # 处理参考图列表
            processed_reference_images = []
            for ref_img in reference_images:
                resolved_ref = self._resolve_image_path_with_face_mask(ai_tool, ref_img)
                success, new_url, error = compress_and_upload_image_sync(
                    resolved_ref, self._config, max_size_mb=10.0, is_local=True
                )
                if success:
                    processed_reference_images.append(new_url)
                else:
                    self.logger.warning(f"处理参考图失败，跳过: {error}")

            if processed_reference_images:
                metadata["reference_images"] = processed_reference_images

            # 参考视频（需上传到 CDN）
            reference_video_raw = self.get_video_path(ai_tool) or extra_config.get('reference_video')
            if reference_video_raw:
                video_paths = [v.strip() for v in reference_video_raw.split(",") if v.strip()]
                processed_video_urls = []
                for video_path in video_paths:
                    actual_path = self._resolve_video_path_with_face_mask(ai_tool, video_path)
                    prep_success, prepared_path, prep_error, cleanup_paths = prepare_seedance_reference_video_sync(
                        actual_path, self._config
                    )
                    try:
                        if not prep_success or not prepared_path:
                            self.logger.warning(f"参考视频规范化失败，跳过: {prep_error}")
                            continue

                        success, cdn_url, error = upload_media_to_cdn_sync(prepared_path, self._config)
                        if success and cdn_url:
                            processed_video_urls.append(cdn_url)
                        else:
                            self.logger.warning(f"参考视频上传 CDN 失败，跳过: {error}")
                    finally:
                        _cleanup_seedance_reference_video_temps(cleanup_paths)
                if processed_video_urls:
                    metadata["reference_videos"] = processed_video_urls

            # 参考音频（需上传到 CDN）
            reference_audio_raw = self.get_audio_path(ai_tool) or extra_config.get('reference_audio')
            if reference_audio_raw:
                audio_paths = [a.strip() for a in reference_audio_raw.split(",") if a.strip()]
                processed_audio_urls = []
                for audio_path in audio_paths:
                    success, cdn_url, error = upload_media_to_cdn_sync(audio_path, self._config)
                    if success and cdn_url:
                        processed_audio_urls.append(cdn_url)
                    else:
                        self.logger.warning(f"参考音频上传 CDN 失败，跳过: {error}")
                if processed_audio_urls:
                    metadata["reference_audios"] = processed_audio_urls

        else:
            # ---- 未知模式，降级为首帧 ----
            self.logger.warning(f"未知的 image_mode: {img_mode}，降级为首帧模式")
            if not first_frame:
                return {
                    "success": False,
                    "error": "未找到可用的图片",
                    "error_type": "USER",
                    "retry": False
                }
            first_frame = self._resolve_image_path_with_face_mask(ai_tool, first_frame)
            success, processed_url, error = compress_and_upload_image_sync(
                first_frame, self._config, max_size_mb=10.0, is_local=True
            )
            if not success:
                return {
                    "success": False,
                    "error": f"处理图片失败: {error}",
                    "error_type": "USER",
                    "retry": False
                }
            top_image = processed_url

        # 5. 组装 payload
        payload: Dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
        }
        if top_image is not None:
            payload["image"] = top_image

        payload["metadata"] = metadata

        self.logger.info(
            f"使用模型: {self._model}, driver_type: {self.driver_type}, 模式: {img_mode}, "
            f"top_image: {'有' if top_image else '无'}, metadata keys: {list(metadata.keys())}"
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}"
        }

        return {
            "url": f"{self._base_url}/video/generations",
            "method": "POST",
            "json": payload,
            "headers": headers,
            "timeout": self._timeout
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 kkidc 任务状态的请求参数
        """
        return {
            "url": f"{self._base_url}/video/generations/{project_id}",
            "method": "GET",
            "json": None,
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            }
        }

    # ==================== 提交任务 ====================

    def _extract_http_error_body(self, http_error) -> Optional[dict]:
        """
        从 HTTPError 中提取响应体 JSON（kkidc 的 400/429 返回 {error:{message,type,code}}）

        基类 _request 在 raise_for_status() 时会丢弃响应体，这里重新解析。
        """
        try:
            response = getattr(http_error, "response", None)
            if response is None:
                return None
            return response.json()
        except (ValueError, AttributeError):
            return None

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 kkidc 图生视频/文生视频任务
        异步 API - 返回 task_id 用于后续轮询
        """
        task_id = ai_tool.id

        try:
            # 1. 构建请求参数
            request_params = self.build_create_request(ai_tool)

            # build_create_request 可能返回错误（如图片处理失败）
            if "success" in request_params and not request_params["success"]:
                return request_params

            # 测试模式：返回 mock 数据，避免实际 API 调用和费用
            if self._test_mode_enabled:
                mock_project_id = f"test-{uuid.uuid4().hex[:8]}"
                self.logger.info(f"[TEST MODE] 返回模拟task_id: {mock_project_id}")
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
                    timeout=request_params.get("timeout", self._timeout)
                )
            except requests.exceptions.HTTPError as http_error:
                # kkidc 的 400/429 返回结构化错误体，提取后走响应校验的 error 分支
                status_code = getattr(getattr(http_error, "response", None), "status_code", None)
                error_body = self._extract_http_error_body(http_error)
                if isinstance(error_body, dict) and "error" in error_body:
                    is_valid, error_msg = self._validate_submit_response(error_body)
                    # _validate_submit_response 对含 error 的响应必返回 (False, msg)
                    from utils.content_moderation_error import is_content_moderation_user_message

                    if is_content_moderation_user_message(error_msg):
                        return {
                            "success": False,
                            "error": error_msg,
                            "error_type": "USER",
                            "retry": False
                        }

                    if status_code == 429:
                        # 限流：友好提示 + 允许重试，不发 Sentry
                        self.logger.warning(f"kkidc 限流(429): {error_msg}")
                        return {
                            "success": False,
                            "error": "上游限流，请稍后重试",
                            "error_type": "USER",
                            "retry": True
                        }

                    # 400 等请求错误：用户错误，不重试
                    return {
                        "success": False,
                        "error": error_msg,
                        "error_type": "USER",
                        "retry": False
                    }
                # 无法解析错误体，按系统错误处理
                self._send_alert(
                    alert_type="API_HTTP_ERROR",
                    message=f"kkidc submit_task HTTP 错误: {str(http_error)}",
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
                self.logger.warning(f"Network error during kkidc task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            # 3. 验证响应格式
            is_valid, error_msg = self._validate_submit_response(result)
            if not is_valid:
                from utils.content_moderation_error import is_content_moderation_user_message

                if is_content_moderation_user_message(error_msg):
                    return {
                        "success": False,
                        "error": error_msg,
                        "error_type": "USER",
                        "retry": False
                    }

                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"kkidc API 响应格式错误: {error_msg}",
                    context={"task_id": task_id, "response": result}
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": error_msg,
                    "retry": False
                }

            # 4. 提取任务 ID（兼容三段式 data.task_id 与扁平式顶层 task_id）
            project_id = self._extract_task_id(result)
            if not project_id:
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "kkidc API 未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": project_id
            }

        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"kkidc submit_task error: {error_msg}")
            self.logger.error(traceback.format_exc())

            if "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"kkidc submit_task 异常: {error_msg}",
                context={"task_id": task_id, "traceback": traceback.format_exc()}
            )
            return {
                "success": False,
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": error_msg,
                "retry": False
            }

    # ==================== 查询状态 ====================

    def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        检查 kkidc 任务状态

        kkidc 状态（外层大写，优先）:
            NOT_START / SUBMITTED / QUEUED / IN_PROGRESS / SUCCESS / FAILURE / UNKNOWN
        上游 data.data.status（小写，回退）:
            queued / running / succeeded / failed / expired
        """
        try:
            self.logger.info(f"Checking kkidc task status: project_id={project_id}")

            # 测试模式：返回 mock 数据
            if self._test_mode_enabled and self._mock_video_url:
                self.logger.info(f"[TEST MODE] 返回模拟视频结果: {self._mock_video_url}")
                return {
                    "status": "SUCCESS",
                    "result_url": self._mock_video_url
                }

            # 1. 构建请求并发送
            request_params = self.build_check_query(project_id)

            try:
                result = self._request(**request_params)
            except requests.exceptions.HTTPError as http_error:
                status_code = getattr(getattr(http_error, "response", None), "status_code", None)
                if status_code == 429:
                    # 限流：保持 RUNNING，等待下次轮询
                    self.logger.warning(f"kkidc 状态查询限流(429)，稍后重试")
                    return {
                        "status": "RUNNING",
                        "message": "上游限流，稍后将重试"
                    }
                self._send_alert(
                    alert_type="API_HTTP_ERROR",
                    message=f"kkidc check_status HTTP 错误: {str(http_error)}",
                    context={"project_id": project_id, "status_code": status_code}
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": str(http_error)
                }
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during kkidc status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            self.logger.info(f"kkidc status API response: code={result.get('code')}")

            # 2. 验证响应格式
            is_valid, validation_error = self._validate_status_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"kkidc check_status 响应格式错误: {validation_error}",
                    context={"project_id": project_id, "response": result}
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {validation_error}"
                }

            # 3. 状态映射（外层状态 + 内层状态合并判断，大小写归一）
            sd = self._extract_status_data(result)
            # 外层与内层状态的并集（均转大写用于匹配）
            status_set = {sd["status_upper"], sd["inner_status"].upper()}

            if status_set & self._SUCCESS_STATES:
                # video_url: 优先内层 content.video_url，回退顶层 video_url
                video_url = sd["video_url"]
                if not video_url:
                    outer = result.get("data") if isinstance(result.get("data"), dict) else result
                    video_url = outer.get("video_url")
                if not video_url:
                    self._send_alert(
                        alert_type="INVALID_RESPONSE_FORMAT",
                        message="kkidc 任务成功但缺少 video_url",
                        context={"project_id": project_id, "response": result}
                    )
                    return {
                        "status": "FAILED",
                        "error": "任务成功但未返回视频地址",
                        "error_type": "SYSTEM"
                    }
                return {
                    "status": "SUCCESS",
                    "result_url": video_url
                }

            if status_set & self._FAILURE_STATES:
                # 失败原因：优先 fail_reason，回退 inner data
                fail_reason = sd["fail_reason"]
                if not fail_reason:
                    fail_reason = "任务失败"
                # 容错：文档示例中 fail_reason 曾误填为 video URL，过滤掉明显的 URL
                if fail_reason.startswith(("http://", "https://")):
                    fail_reason = "任务失败"
                return {
                    "status": "FAILED",
                    "error": fail_reason,
                    "error_type": "USER"
                }

            # NOT_START / SUBMITTED / QUEUED / IN_PROGRESS / UNKNOWN 或中间态
            return {
                "status": "RUNNING",
                "message": "任务处理中..."
            }

        except Exception as e:
            self.logger.error(f"Unexpected exception in kkidc check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"kkidc check_status 发生未预期异常: {str(e)}",
                context={"project_id": project_id, "traceback": traceback.format_exc()}
            )
            return {
                "status": "FAILED",
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}"
            }


# ============ 具体模型实现类 ============

class Seedance20FastKkidcV1Driver(SeedanceKkidcV1Driver):
    """Seedance 2.0 Fast 图生视频驱动（kkidc 网关）

    注意：kkidc 网关使用自有的模型别名 seed-2-fast，
    非火山原生模型名 doubao-seedance-2-0-fast-260128。
    """

    def __init__(self):
        super().__init__(
            driver_type=22,
            model_name="seed-2-fast",
            impl_name=DriverImplementation.SEEDANCE_2_0_FAST_KKIDC_V1
        )


class Seedance20KkidcV1Driver(SeedanceKkidcV1Driver):
    """Seedance 2.0 图生视频驱动（kkidc 网关）

    注意：kkidc 网关使用自有的模型别名 seed-2，
    非火山原生模型名 doubao-seedance-2-0-260128。
    """

    def __init__(self):
        super().__init__(
            driver_type=23,
            model_name="seed-2",
            impl_name=DriverImplementation.SEEDANCE_2_0_KKIDC_V1
        )


class Seedance20MiniKkidcV1Driver(SeedanceKkidcV1Driver):
    """Seedance 2.0 Mini 图生视频驱动（kkidc 网关）

    注意：kkidc 网关使用自有的模型别名 seed-2-mini，
    非火山原生模型名 doubao-seedance-2-0-mini-260615。
    """

    def __init__(self):
        super().__init__(
            driver_type=31,
            model_name="seed-2-mini",
            impl_name=DriverImplementation.SEEDANCE_2_0_MINI_KKIDC_V1
        )
