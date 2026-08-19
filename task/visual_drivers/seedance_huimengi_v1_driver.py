"""
Seedance huimengi 网关 v1 版本驱动实现
异步 API - 创建任务后轮询状态

huimengi（慧梦）是 Seedance 2.0 系列的二次封装网关，接口结构与火山原生 /
kkidc 完全不同：
- 请求体：扁平 { model, params: {...} } 结构（火山为 content[] 数组，kkidc 为
  prompt + metadata{}）
- 创建路径：POST /api/v1/tasks
- 查询路径：GET  /api/v1/tasks/{task_id}
- 提交响应：扁平 { task_id, status }
- 查询响应：扁平 { id, model, status, result: { video_url, ... }, error_message, ... }

支持模型：Seedance 2.0 Fast / 2.0 / 2.0 Mini / 2.5（与火山国内版同质，作为备选实现）
支持能力：文生视频、首帧/首尾帧图生视频、多参考图（含参考音视频）、真人审核模式

注意：huimengi 网关使用官方模型名（seedance-2.0 / seedance-2.0-fast /
seedance-2.0-mini / seedance-2.5），非火山原生 ARK 模型名（doubao-seedance-*-26xxxx），
也非 kkidc 别名（seed-2 / seed-2-fast / seed-2-mini）。

基类 SeedanceHuimengiV1Driver 包含核心逻辑，
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
from config.constant import (
    LEGACY_RESOLUTION_EXTRA_CONFIG_KEY,
    OMNI_REFERENCE_TASK_TYPE_EDIT,
    VIDEO_RESOLUTION_EXTRA_CONFIG_KEY,
)
from config.unified_config import DriverImplementation, TaskTypeId, VideoResolution
from utils.sentry_util import SentryUtil, AlertLevel
from utils.computing_power import is_video_edit_billing_task
from utils.image_upload_utils import compress_and_upload_image_sync, upload_media_to_cdn_sync
from utils.video_compressor import prepare_seedance_reference_video_sync
from model.ai_tool_pipeline_steps import PipelineStepModel, PipelineStepStatus, PipelineStepType, PipelineStage


# huimengi 网关接口文档
# 创建：POST https://api.huimengi.com/api/v1/tasks
# 查询：GET  https://api.huimengi.com/api/v1/tasks/{task_id}

# 各分辨率标准值 → huimengi params.resolution 下发值（与火山/kkidc 一致，均小写）
SEEDANCE_HUIMENGI_RESOLUTION_DRIVER_VALUES = VideoResolution.SEEDANCE_DRIVER_VALUES


def _cleanup_seedance_reference_video_temps(paths):
    """清理参考视频规范化产生的临时文件"""
    for path in paths or []:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


class SeedanceHuimengiV1Driver(BaseVideoDriver):
    """
    Seedance huimengi 网关 v1 版本驱动（基类）
    异步 API - 图生视频 / 文生视频

    子类通过不同的 driver_type 和 model_name 区分模型。

    注意：不应直接实例化基类，应使用具体的子类。
    """

    def __init__(self, driver_type: int, model_name: str, impl_name: str = DriverImplementation.SEEDANCE_2_0_HUIMENGI_V1):
        """
        初始化驱动

        Args:
            driver_type: 驱动类型（对应 TaskTypeId）
            model_name: 模型名称（如 seedance-2.0）
            impl_name: 实现方名称，需与 IMPLEMENTATION_TO_ID 映射一致
        """
        super().__init__(driver_name=impl_name, driver_type=driver_type)

        # 加载配置
        self._api_key = get_dynamic_config_value("huimengi", "api_key", default="")
        self._base_url = get_dynamic_config_value(
            "huimengi", "base_url",
            default="https://api.huimengi.com"
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
            "huimengi API Key": self._api_key,
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
        huimengi 网关内置 human_review 自动处理人脸，无需本地遮盖，始终使用原始素材。

        但当任务从 volcengine 等不支持自动处理人脸的实现方重试到 huimengi 时，
        遮盖预处理已执行（apply_results 已把 ai_tool.video_path 回填为遮盖后的网格视频）。
        此时从遗留的 face_mask pipeline step 的 target 字段恢复原始视频路径。

        匹配两种情况：
        - step.target == video_path：video_path 仍是原始路径（未被污染），返回 target（即原图）
        - step.result_url == video_path：video_path 已被 apply_results 污染为遮盖结果，返回 target 恢复原图
        """
        if not video_path:
            return video_path
        try:
            steps = PipelineStepModel.get_by_ai_tool_and_stage(ai_tool.id, PipelineStage.PARAM_PREPARE)
            for step in steps:
                if (step.step_type != PipelineStepType.FACE_MASK
                        or step.status != PipelineStepStatus.COMPLETED
                        or not step.target):
                    continue
                if step.target == video_path or step.result_url == video_path:
                    self.logger.info(f"huimengi 自动处理人脸，恢复原始视频: {video_path} -> {step.target}")
                    return step.target
        except Exception as e:
            self.logger.warning(f"查询 face_mask pipeline step 失败，使用原始路径: {e}")
        return video_path

    def _resolve_image_path_with_face_mask(self, ai_tool, image_path: str) -> str:
        """
        huimengi 网关内置 human_review 自动处理人脸，无需本地遮盖，始终使用原始素材。

        与 _resolve_video_path_with_face_mask 对称：当任务从其他实现方重试到 huimengi
        且遮盖预处理已执行时，从遗留的 image_face_mask step 的 target 字段恢复原始图片。
        """
        if not image_path:
            return image_path
        try:
            steps = PipelineStepModel.get_by_ai_tool_and_stage(ai_tool.id, PipelineStage.PARAM_PREPARE)
            for step in steps:
                if (step.step_type != PipelineStepType.IMAGE_FACE_MASK
                        or step.status != PipelineStepStatus.COMPLETED
                        or not step.target):
                    continue
                if step.target == image_path or step.result_url == image_path:
                    self.logger.info(f"huimengi 自动处理人脸，恢复原始图片: {image_path} -> {step.target}")
                    return step.target
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
        """获取 params.resolution 下发值，优先使用新 video_resolution 字段。"""
        resolution = (
            extra_config.get(VIDEO_RESOLUTION_EXTRA_CONFIG_KEY)
            or extra_config.get(LEGACY_RESOLUTION_EXTRA_CONFIG_KEY)
        )
        if not resolution:
            return None
        return SEEDANCE_HUIMENGI_RESOLUTION_DRIVER_VALUES.get(str(resolution).upper())

    # ==================== 响应校验 ====================

    def _extract_task_id(self, result: Any) -> Optional[str]:
        """
        从创建任务响应中提取 task_id

        huimengi 提交响应为扁平结构：{ task_id, status }
        兼容性回退：顶层 task_id -> 顶层 id -> data.task_id
        """
        if not isinstance(result, dict):
            return None
        # 扁平式优先：顶层 task_id
        if result.get("task_id"):
            return result.get("task_id")
        # 回退：顶层 id
        if result.get("id"):
            return result.get("id")
        # 回退：嵌套 data.task_id
        data = result.get("data")
        if isinstance(data, dict):
            return data.get("task_id") or data.get("id")
        return None

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 submit_task API 响应格式

        huimengi 正常提交响应：{ task_id: "...", status: "pending" }
        huimengi 错误响应可能形态：
        - { error: { message, code, type } }（结构化错误）
        - { error_message: "..." }（扁平错误，与查询失败响应一致）
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        # 结构化错误：{ error: { message, type, code } }
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

        # 扁平错误：{ error_message: "..." }
        if result.get("error_message"):
            from utils.content_moderation_error import format_user_facing_moderation_error

            friendly = format_user_facing_moderation_error(
                error_message=result.get("error_message"),
            )
            if friendly:
                return False, friendly
            return False, result.get("error_message")

        # 正常响应：能提取到 task_id 即视为有效
        task_id = self._extract_task_id(result)
        if not task_id:
            return False, f"响应缺少 task_id，实际字段: {list(result.keys())}"

        return True, None

    def _validate_status_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 check_status API 响应格式

        huimengi 查询响应为扁平结构：
        - 成功：{ id, model, status: "completed", result: {...}, cost, created_at, completed_at }
        - 失败：{ id, status: "failed", error_message: "...", cost: 0 }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "id" not in result and "task_id" not in result:
            return False, f"响应缺少 id/task_id，实际字段: {list(result.keys())}"

        if "status" not in result:
            return False, f"响应缺少 'status' 字段，实际字段: {list(result.keys())}"

        return True, None

    # 状态集合（huimengi 使用小写状态值：pending / processing / completed / failed，
    # 这里统一用大写存储并做大小写归一匹配）
    _SUCCESS_STATES = {"COMPLETED"}
    _FAILURE_STATES = {"FAILED"}
    _RUNNING_STATES = {"PENDING", "PROCESSING"}

    # ==================== 构建请求 ====================

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建 huimengi 创建任务请求（图生视频 / 文生视频）

        huimengi 请求体结构：{ model, params: {...} }
        所有参数（prompt / 图片 / 音视频 / 控制参数）均放在 params 内。

        模式（互斥）：
        - text_to_video: 文生视频，无图片/音视频输入，params 只放 prompt + 控制字段
        - first_last_frame: 首帧/首尾帧模式
            * 仅首帧 → params.image_url
            * 首尾帧 → params.first_frame_image + params.last_frame_image
        - multi_reference: 多模态参考模式，params 放 reference_images /
          reference_videos / reference_audios

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

        # 纯音视频参考（无任何图片输入）：强制走多参考模式，确保音频/视频正确下发
        # 适用 Seedance 2.0 系列及 2.5 的「仅音频/仅视频」输入场景（含 CLI、storyboard 等非 server 入口）
        has_media_ref = bool(reference_video_raw or reference_audio_raw)
        has_any_image = bool(first_frame or last_frame or reference_images)
        if has_media_ref and not has_any_image and not is_text_to_video:
            img_mode = ImageMode.MULTI_REFERENCE

        # 3. 构建 params 通用控制字段
        params: Dict[str, Any] = {"prompt": prompt}

        if extra_config.get('generate_audio') is not None:
            params["generate_audio"] = extra_config['generate_audio']

        # human_review：真人审核模式，从 extra_config 透传（默认 false）
        # 开启后素材将自动上传资产库审核加白，支持含真人人脸的素材
        if extra_config.get('human_review') is not None:
            params["human_review"] = bool(extra_config['human_review'])

        ratio = extra_config.get('ratio') or ai_tool.ratio
        # Seedance 2.5 带参考视频为视频编辑任务：显式 omni_reference_task_type=edit
        # 使接口提前校验参数限制（ratio 必须 adaptive、duration 必须 -1）。
        # 判定入口与计价层共用同一函数；字段放 params 内，依赖 huimengi 网关透传。
        is_25_video_edit = is_video_edit_billing_task(self.driver_type, reference_video_raw)
        if is_25_video_edit:
            params["omni_reference_task_type"] = OMNI_REFERENCE_TASK_TYPE_EDIT
            params["ratio"] = "adaptive"
            params["duration"] = -1
            self.logger.info(
                f"视频编辑模式: omni_reference_task_type={OMNI_REFERENCE_TASK_TYPE_EDIT}, "
                "ratio=adaptive duration=-1"
            )
        else:
            if ratio:
                params["ratio"] = ratio
            if ai_tool.duration:
                params["duration"] = ai_tool.duration

        resolution = self._get_resolution_for_payload(extra_config)
        if resolution:
            params["resolution"] = resolution

        # 4. 根据输入分支填充 params 的图片/音视频字段
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
                # 首尾帧模式：params 内嵌 first_frame_image / last_frame_image
                params["first_frame_image"] = processed_url
                params["last_frame_image"] = processed_last_frame
            else:
                # 仅首帧模式：用 params.image_url（huimengi API 规范）
                params["image_url"] = processed_url

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
                params["reference_images"] = processed_reference_images

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
                    params["reference_videos"] = processed_video_urls

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
                    params["reference_audios"] = processed_audio_urls

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
            params["image_url"] = processed_url

        # 5. 组装 payload（huimengi 扁平 { model, params } 结构）
        payload: Dict[str, Any] = {
            "model": self._model,
            "params": params,
        }

        self.logger.info(
            f"使用模型: {self._model}, driver_type: {self.driver_type}, 模式: {img_mode}, "
            f"params keys: {list(params.keys())}"
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}"
        }

        return {
            "url": f"{self._base_url}/api/v1/tasks",
            "method": "POST",
            "json": payload,
            "headers": headers,
            "timeout": self._timeout
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 huimengi 任务状态的请求参数
        """
        return {
            "url": f"{self._base_url}/api/v1/tasks/{project_id}",
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
        从 HTTPError 中提取响应体 JSON

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
        提交 huimengi 图生视频/文生视频任务
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
                # huimengi 的 400/429 返回结构化错误体，提取后走响应校验的 error 分支
                status_code = getattr(getattr(http_error, "response", None), "status_code", None)
                error_body = self._extract_http_error_body(http_error)
                if isinstance(error_body, dict) and ("error" in error_body or error_body.get("error_message")):
                    is_valid, error_msg = self._validate_submit_response(error_body)
                    # _validate_submit_response 对含 error/error_message 的响应必返回 (False, msg)
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
                        self.logger.warning(f"huimengi 限流(429): {error_msg}")
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
                    message=f"huimengi submit_task HTTP 错误: {str(http_error)}",
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
                self.logger.warning(f"Network error during huimengi task submission: {str(network_error)}")
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
                    message=f"huimengi API 响应格式错误: {error_msg}",
                    context={"task_id": task_id, "response": result}
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": error_msg,
                    "retry": False
                }

            # 4. 提取任务 ID
            project_id = self._extract_task_id(result)
            if not project_id:
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "huimengi API 未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": project_id
            }

        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"huimengi submit_task error: {error_msg}")
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
                message=f"huimengi submit_task 异常: {error_msg}",
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
        检查 huimengi 任务状态

        huimengi 状态值（扁平顶层 status）:
            pending（等待中）→ processing（生成中）→ completed（已完成）/ failed（失败）
        """
        try:
            self.logger.info(f"Checking huimengi task status: project_id={project_id}")

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
                    self.logger.warning(f"huimengi 状态查询限流(429)，稍后重试")
                    return {
                        "status": "RUNNING",
                        "message": "上游限流，稍后将重试"
                    }
                self._send_alert(
                    alert_type="API_HTTP_ERROR",
                    message=f"huimengi check_status HTTP 错误: {str(http_error)}",
                    context={"project_id": project_id, "status_code": status_code}
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": str(http_error)
                }
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during huimengi status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            self.logger.info(f"huimengi status API response: status={result.get('status')}")

            # 2. 验证响应格式
            is_valid, validation_error = self._validate_status_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"huimengi check_status 响应格式错误: {validation_error}",
                    context={"project_id": project_id, "response": result}
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {validation_error}"
                }

            # 3. 状态映射（huimengi 扁平顶层 status，大小写归一）
            raw_status = str(result.get("status", ""))
            status_upper = raw_status.upper()

            if status_upper in self._SUCCESS_STATES:
                # video_url 位于 result.video_url（huimengi API 规范）
                result_obj = result.get("result")
                video_url = None
                if isinstance(result_obj, dict):
                    video_url = result_obj.get("video_url")
                # 回退：顶层 video_url
                if not video_url:
                    video_url = result.get("video_url")
                if not video_url:
                    self._send_alert(
                        alert_type="INVALID_RESPONSE_FORMAT",
                        message="huimengi 任务成功但缺少 video_url",
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

            if status_upper in self._FAILURE_STATES:
                # 失败原因：优先 error_message，回退默认文案
                fail_reason = result.get("error_message") if isinstance(result.get("error_message"), str) else None
                if not fail_reason:
                    fail_reason = "任务失败"
                # 容错：过滤掉误填为 URL 的失败原因
                if fail_reason.startswith(("http://", "https://")):
                    fail_reason = "任务失败"
                return {
                    "status": "FAILED",
                    "error": fail_reason,
                    "error_type": "USER"
                }

            # pending / processing 或其他中间态
            return {
                "status": "RUNNING",
                "message": "任务处理中..."
            }

        except Exception as e:
            self.logger.error(f"Unexpected exception in huimengi check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"huimengi check_status 发生未预期异常: {str(e)}",
                context={"project_id": project_id, "traceback": traceback.format_exc()}
            )
            return {
                "status": "FAILED",
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}"
            }


# ============ 具体模型实现类 ============

class Seedance20FastHuimengiV1Driver(SeedanceHuimengiV1Driver):
    """Seedance 2.0 Fast 图生视频驱动（huimengi 网关）

    使用 huimengi 官方模型名 seedance-2.0-fast。
    """

    def __init__(self):
        super().__init__(
            driver_type=22,
            model_name="seedance-2.0-fast",
            impl_name=DriverImplementation.SEEDANCE_2_0_FAST_HUIMENGI_V1
        )


class Seedance20HuimengiV1Driver(SeedanceHuimengiV1Driver):
    """Seedance 2.0 图生视频驱动（huimengi 网关）

    使用 huimengi 官方模型名 seedance-2.0。
    """

    def __init__(self):
        super().__init__(
            driver_type=23,
            model_name="seedance-2.0",
            impl_name=DriverImplementation.SEEDANCE_2_0_HUIMENGI_V1
        )


class Seedance20MiniHuimengiV1Driver(SeedanceHuimengiV1Driver):
    """Seedance 2.0 Mini 图生视频驱动（huimengi 网关）

    使用 huimengi 官方模型名 seedance-2.0-mini。
    """

    def __init__(self):
        super().__init__(
            driver_type=31,
            model_name="seedance-2.0-mini",
            impl_name=DriverImplementation.SEEDANCE_2_0_MINI_HUIMENGI_V1
        )


class Seedance25HuimengiV1Driver(SeedanceHuimengiV1Driver):
    """Seedance 2.5 全模态视频驱动（huimengi 网关）

    接口与 2.0 系列完全兼容（扁平 {model, params}、状态轮询一致），
    仅 model_name 为 seedance-2.5。2.5 额外支持：
    - 纯音频输入（无图无视频，仅参考音频）
    - 最多 30 张参考图 / 10 个参考视频 / 10 段参考音频
    - 视频时长 [4, 30]s
    支持分辨率 480P / 720P / 1080P（不支持 4K）。
    """

    def __init__(self):
        super().__init__(
            driver_type=TaskTypeId.SEEDANCE_2_5_IMAGE_TO_VIDEO,
            model_name="seedance-2.5",
            impl_name=DriverImplementation.SEEDANCE_2_5_HUIMENGI_V1
        )
