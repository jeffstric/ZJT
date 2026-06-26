"""
Seedance 火山引擎供应商 v1 版本驱动实现
异步 API - 创建任务后轮询状态
支持 Seedance 1.5 Pro / 2.0 Fast / 2.0 / 2.0 Mini 四个模型
支持图生视频（首尾帧 / 多参考图）与文生视频（纯文本）

基类 SeedanceVolcengineV1Driver 包含核心逻辑，
子类通过 driver_type 和 model_name 区分不同模型。
"""
from typing import Dict, Any, Optional
import os
import traceback
import json
import uuid
from .base_video_driver import BaseVideoDriver, ImageMode
from config.config_util import get_config, get_dynamic_config_value
from config.unified_config import DriverImplementation
from utils.sentry_util import SentryUtil, AlertLevel
from utils.image_upload_utils import compress_and_upload_image_sync, upload_media_to_cdn_sync
from model.ai_tool_pipeline_steps import PipelineStepModel, PipelineStepStatus, PipelineStepType, PipelineStage


# 接口文档 https://www.volcengine.com/docs/82379/1520757?lang=zh

class SeedanceVolcengineV1Driver(BaseVideoDriver):
    """
    Seedance 火山引擎供应商 v1 版本驱动（基类）
    异步 API - 图生视频 / 文生视频

    子类通过不同的 driver_type 和 model_name 区分模型。

    注意：不应直接实例化基类，应使用具体的子类。
    """

    def __init__(self, driver_type: int, model_name: str, impl_name: str = DriverImplementation.SEEDANCE_2_0_VOLCENGINE_V1):
        """
        初始化驱动

        Args:
            driver_type: 驱动类型（对应 TaskTypeId）
            model_name: 模型名称（如 doubao-seedance-1-5-pro-251215）
            impl_name: 实现方名称，需与 IMPLEMENTATION_TO_ID 映射一致
        """
        super().__init__(driver_name=impl_name, driver_type=driver_type)

        # 加载配置
        self._api_key = get_dynamic_config_value("volcengine", "api_key", default="")
        self._base_url = "https://ark.cn-beijing.volces.com"
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
            "Volcengine API Key": self._api_key,
        })

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
        使用其 result_url（人脸遮盖后的视频）替代原始路径，避免 seedance 2.0 审核不通过。
        """
        try:
            steps = PipelineStepModel.get_by_ai_tool_and_stage(ai_tool.id, PipelineStage.PARAM_PREPARE)
            for step in steps:
                if (step.step_type == PipelineStepType.FACE_MASK
                        and step.status == PipelineStepStatus.COMPLETED
                        and step.target == video_path
                        and step.result_url):
                    result_url = step.result_url
                    # result_url 是本地路径（如 /upload/cache/...），去掉前导 / 变成相对路径
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

        与 _resolve_video_path_with_face_mask 对称：若 ai_tool_pipeline_steps 中存在
        target 匹配的已完成 image_face_mask 步骤，使用其 result_url（人脸遮盖后的图片）
        替代原始路径，避免 seedance 2.0 审核不通过。

        主动查询 step 而非依赖 apply_results 对 ai_tool 字段的回写，规避并发调度下
        回写未及时生效导致提交原始（带人脸）图片的问题。无论回写是否生效均鲁棒：
        - 回写未生效：step.target(原始URL) == 当前图片路径(原始URL)，命中遮盖结果
        - 回写已生效：当前图片路径已是遮盖路径，target 不匹配，原样返回（仍是遮盖图）
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

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 submit_task API 响应格式

        期望格式:
        { "id": "cgt-2026xxxx-xxxx" }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "error" in result:
            error_info = result.get("error", {})
            error_code = error_info.get("code", "Unknown")
            error_message = error_info.get("message", "未知错误")
            return False, f"API 错误 [{error_code}]: {error_message}"

        if "id" not in result:
            return False, f"响应缺少 'id' 字段，实际字段: {list(result.keys())}"

        return True, None

    def _validate_status_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 check_status API 响应格式

        期望格式:
        {
            "id": "cgt-xxx",
            "status": "queued"|"running"|"succeeded"|"failed",
            "content": { "video_url": "https://..." },  # succeeded 时
            ...
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "id" not in result:
            return False, f"响应缺少 'id' 字段，实际字段: {list(result.keys())}"

        if "status" not in result:
            return False, f"响应缺少 'status' 字段，实际字段: {list(result.keys())}"

        status = result.get("status")
        if status not in ("queued", "running", "succeeded", "failed"):
            return False, f"'status' 值无效: {status}"

        if status == "succeeded":
            content = result.get("content")
            if not content or not isinstance(content, dict):
                return False, "任务成功但缺少 'content' 字段"
            if "video_url" not in content:
                return False, "任务成功但缺少 'content.video_url' 字段"

        return True, None

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建 Seedance 创建任务请求（图生视频 / 文生视频）

        模式（互斥）：
        - text_to_video: 文生视频，无任何图片/音视频输入，content 只放 text
        - first_last_frame: 首帧/首尾帧模式，content 中放 first_frame/last_frame
        - multi_reference: 多模态参考模式，content 中放 reference_image + reference_video + reference_audio
        - first_last_with_ref: 首尾帧+参考图模式（暂不支持，降级为首尾帧）

        文生视频判定：无首/尾帧、无参考图、无参考视频/音频，且 extra_config 未声明 image_mode
        （文生视频接口不写 extra_config，图生视频接口必写 {'image_mode': ...}）。
        """
        # 1. 解析 extra_config 和图片模式
        extra_config = self._parse_extra_config(ai_tool)
        all_images_info = self.get_all_images_by_mode(ai_tool)
        img_mode = all_images_info['mode']
        first_frame = all_images_info.get('first_frame')
        last_frame = all_images_info.get('last_frame')
        reference_images = all_images_info.get('reference_images', [])

        prompt = ai_tool.prompt or ""
        content = []

        # 2. 根据输入分支构建 content
        # 文生视频判定：无任何图片/音视频输入，且 extra_config 未声明 image_mode
        # （文生视频接口 /api/ai-app-run 不写 extra_config；图生视频接口必写 {'image_mode': ...}）
        reference_video_raw = self.get_video_path(ai_tool) or extra_config.get('reference_video')
        reference_audio_raw = self.get_audio_path(ai_tool) or extra_config.get('reference_audio')
        is_text_to_video = (
            not first_frame and not last_frame and not reference_images
            and not reference_video_raw and not reference_audio_raw
            and 'image_mode' not in extra_config
        )

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
            content.append({"type": "text", "text": prompt})

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

            # 文本
            if prompt:
                content.append({"type": "text", "text": prompt})

            # 有尾帧时：首帧带 role: "first_frame"，尾帧带 role: "last_frame"
            # 无尾帧时：首帧不带 role 字段（API 文档规范）
            if processed_last_frame:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": processed_url},
                    "role": "first_frame"
                })
                content.append({
                    "type": "image_url",
                    "image_url": {"url": processed_last_frame},
                    "role": "last_frame"
                })
            else:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": processed_url}
                })

        elif img_mode == ImageMode.MULTI_REFERENCE:
            # ---- 多模态参考模式 ----
            self.logger.info(f"多参考图模式: reference_images={len(reference_images)}张")

            # 处理参考图列表（图片可选，多参考模式下视频/音频也可独立使用）
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

            # 文本
            if prompt:
                content.append({"type": "text", "text": prompt})

            # 参考图（如有）
            for ref_img_url in processed_reference_images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": ref_img_url},
                    "role": "reference_image"
                })

            # 参考视频（仅多参考图模式下添加，需上传到 CDN）
            reference_video_raw = self.get_video_path(ai_tool) or extra_config.get('reference_video')
            if reference_video_raw:
                video_paths = [v.strip() for v in reference_video_raw.split(",") if v.strip()]
                for video_path in video_paths:
                    # 查找 face_mask 遮盖结果，如有则使用遮盖后的视频
                    actual_path = self._resolve_video_path_with_face_mask(ai_tool, video_path)
                    success, cdn_url, error = upload_media_to_cdn_sync(actual_path, self._config)
                    if success and cdn_url:
                        content.append({
                            "type": "video_url",
                            "video_url": {"url": cdn_url},
                            "role": "reference_video"
                        })
                    else:
                        self.logger.warning(f"参考视频上传 CDN 失败，跳过: {error}")

            # 参考音频（仅多参考图模式下添加，需上传到 CDN）
            reference_audio_raw = self.get_audio_path(ai_tool) or extra_config.get('reference_audio')
            if reference_audio_raw:
                audio_paths = [a.strip() for a in reference_audio_raw.split(",") if a.strip()]
                for audio_path in audio_paths:
                    success, cdn_url, error = upload_media_to_cdn_sync(audio_path, self._config)
                    if success and cdn_url:
                        content.append({
                            "type": "audio_url",
                            "audio_url": {"url": cdn_url},
                            "role": "reference_audio"
                        })
                    else:
                        self.logger.warning(f"参考音频上传 CDN 失败，跳过: {error}")

        else:
            # ---- 未知模式，降级为首尾帧 ----
            self.logger.warning(f"未知的 image_mode: {img_mode}，降级为首尾帧模式")
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
            if prompt:
                content.append({"type": "text", "text": prompt})
            content.append({
                "type": "image_url",
                "image_url": {"url": processed_url}
            })

        # 3. 构建 payload（所有模式通用）
        payload = {
            "model": self._model,
            "content": content
        }

        if extra_config.get('generate_audio') is not None:
            payload["generate_audio"] = extra_config['generate_audio']

        if extra_config.get('watermark') is not None:
            payload["watermark"] = extra_config['watermark']

        ratio = extra_config.get('ratio') or ai_tool.ratio
        if ratio:
            payload["ratio"] = ratio

        if ai_tool.duration:
            payload["duration"] = ai_tool.duration

        self.logger.info(f"使用模型: {self._model}, driver_type: {self.driver_type}, 模式: {img_mode}, content 元素数: {len(content)}")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}"
        }

        return {
            "url": f"{self._base_url}/api/v3/contents/generations/tasks",
            "method": "POST",
            "json": payload,
            "headers": headers,
            "timeout": self._timeout
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 Seedance 任务状态的请求参数
        """
        return {
            "url": f"{self._base_url}/api/v3/contents/generations/tasks/{project_id}",
            "method": "GET",
            "json": None,
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            }
        }

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 Seedance 图生视频任务
        异步 API - 返回 task_id 用于后续轮询
        """
        task_id = ai_tool.id

        try:
            # 1. 构建请求参数
            request_params = self.build_create_request(ai_tool)

            # build_create_request 可能返回错误（如图片处理失败）
            if "success" in request_params and not request_params["success"]:
                return request_params

            # 测试模式：返回mock数据，避免实际API调用和费用
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
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during Seedance task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            # 3. 验证响应格式
            is_valid, error_msg = self._validate_submit_response(result)
            if not is_valid:
                if "API 错误" in error_msg:
                    return {
                        "success": False,
                        "error": error_msg,
                        "error_type": "USER",
                        "retry": False
                    }

                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Seedance API 响应格式错误: {error_msg}",
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
            project_id = result.get("id")
            if not project_id:
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "Seedance API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": project_id
            }

        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Seedance submit_task error: {error_msg}")
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
                message=f"Seedance submit_task 异常: {error_msg}",
                context={"task_id": task_id, "traceback": traceback.format_exc()}
            )
            return {
                "success": False,
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": error_msg,
                "retry": False
            }

    def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        检查 Seedance 任务状态
        status 映射: processing -> RUNNING, succeeded -> SUCCESS, failed -> FAILED
        """
        try:
            self.logger.info(f"Checking Seedance task status: project_id={project_id}")

            # 测试模式：返回mock数据，避免实际API调用
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
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during Seedance status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            self.logger.info(f"Seedance status API response: status={result.get('status')}")

            # 2. 验证响应格式
            is_valid, validation_error = self._validate_status_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Seedance check_status 响应格式错误: {validation_error}",
                    context={"project_id": project_id, "response": result}
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {validation_error}"
                }

            # 3. 映射状态
            status = result.get("status")

            if status == "succeeded":
                video_url = result.get("content", {}).get("video_url")
                return {
                    "status": "SUCCESS",
                    "result_url": video_url
                }
            elif status == "failed":
                error_msg = result.get("error", {})
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", "任务失败")
                elif not isinstance(error_msg, str):
                    error_msg = "任务失败"
                return {
                    "status": "FAILED",
                    "error": error_msg,
                    "error_type": "USER"
                }
            else:
                # running 或其他中间状态
                return {
                    "status": "RUNNING",
                    "message": "任务处理中..."
                }

        except Exception as e:
            self.logger.error(f"Unexpected exception in Seedance check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Seedance check_status 发生未预期异常: {str(e)}",
                context={"project_id": project_id, "traceback": traceback.format_exc()}
            )
            return {
                "status": "FAILED",
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}"
            }


# ============ 具体模型实现类 ============

class Seedance15ProVolcengineV1Driver(SeedanceVolcengineV1Driver):
    """Seedance 1.5 Pro 图生视频驱动"""

    def __init__(self):
        super().__init__(driver_type=21, model_name="doubao-seedance-1-5-pro-251215", impl_name=DriverImplementation.SEEDANCE_1_5_PRO_VOLCENGINE_V1)


class Seedance20FastVolcengineV1Driver(SeedanceVolcengineV1Driver):
    """Seedance 2.0 Fast 图生视频驱动"""

    def __init__(self):
        super().__init__(driver_type=22, model_name="doubao-seedance-2-0-fast-260128", impl_name=DriverImplementation.SEEDANCE_2_0_FAST_VOLCENGINE_V1)


class Seedance20VolcengineV1Driver(SeedanceVolcengineV1Driver):
    """Seedance 2.0 图生视频驱动"""

    def __init__(self):
        super().__init__(driver_type=23, model_name="doubao-seedance-2-0-260128", impl_name=DriverImplementation.SEEDANCE_2_0_VOLCENGINE_V1)


class Seedance20MiniVolcengineV1Driver(SeedanceVolcengineV1Driver):
    """Seedance 2.0 Mini 图生视频驱动"""

    def __init__(self):
        super().__init__(driver_type=31, model_name="doubao-seedance-2-0-mini-260615", impl_name=DriverImplementation.SEEDANCE_2_0_MINI_VOLCENGINE_V1)
