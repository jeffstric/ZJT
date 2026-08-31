"""
Wan3.0 阿里云百炼驱动实现
模型: wan3.0-video（标准版）/ wan3.0-video-prime（高速版）
支持图生视频（首尾帧）、参考生视频（参考图/视频/音频）、文生视频，异步任务模式
"""
from typing import Dict, Any, Optional, List
import traceback
import json
from .base_video_driver import BaseVideoDriver
from config.config_util import get_config, get_dynamic_config_value
from config.constant import LEGACY_RESOLUTION_EXTRA_CONFIG_KEY, VIDEO_RESOLUTION_EXTRA_CONFIG_KEY
from config.unified_config import VideoResolution
from api.media import _get_media_duration_seconds
from utils.sentry_util import SentryUtil, AlertLevel
from utils.image_upload_utils import upload_local_images_to_cdn_sync

# 支持的比例（adaptive 由 API 自动推断）
SUPPORTED_RATIOS = ('adaptive', '16:9', '4:3', '1:1', '3:4', '9:16')
# 无视频输入时 duration 取值范围（秒）
MIN_DURATION = 2
MAX_DURATION = 30
# 参考视频/音频数量与总时长上限
MAX_REF_MEDIA_COUNT = 5
MAX_REF_MEDIA_TOTAL_SECONDS = 15


class Wan3DashscopeV1Driver(BaseVideoDriver):
    """
    Wan3.0 图生视频驱动（阿里云百炼 DashScope，业务空间版异步 API）
    支持首帧图片 + 可选尾帧图片
    """

    MODEL = "wan3.0-video"

    def __init__(self, driver_name: str = "wan3_video_dashscope_v1", driver_type: int = 40):
        super().__init__(driver_name=driver_name, driver_type=driver_type)

        # 加载配置（复用 LLM 配置的阿里云 Qwen API Key）
        self._api_key = get_dynamic_config_value("llm", "qwen", "api_key", default="")
        self._workspace_id = get_dynamic_config_value("wan3", "workspace_id", default="")
        self._region = get_dynamic_config_value("wan3", "endpoint_region", default="cn-beijing")
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        self._config = get_config()
        self._base_url = f"https://{self._workspace_id}.{self._region}.maas.aliyuncs.com/api/v1"

        self._validate_required({
            "DashScope API Key": self._api_key,
            "百炼业务空间ID": self._workspace_id,
        })

    def _send_alert(self, alert_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        """
        发送报警信息
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

        期望响应:
        {
            "output": {
                "task_status": "PENDING",
                "task_id": "0385dc79-5ff8-4d82-bcb6-xxxxxx"
            },
            "request_id": "..."
        }
        失败响应: {"code": "...", "message": "...", "request_id": "..."}
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "code" in result:
            return True, None  # 有错误字段，格式有效但业务失败

        output = result.get("output")
        if not isinstance(output, dict):
            return False, f"响应缺少 'output' 字段或类型错误，实际: {result.keys()}"

        if "task_id" not in output:
            return False, f"output 缺少 'task_id' 字段"

        return True, None

    def _validate_status_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 check_status API 响应格式

        期望响应:
        {
            "output": {
                "task_id": "...",
                "task_status": "SUCCEEDED",
                "video_url": "https://..."
            },
            "request_id": "..."
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "code" in result:
            return True, None

        output = result.get("output")
        if not isinstance(output, dict):
            return False, f"响应缺少 'output' 字段或类型错误"

        if "task_status" not in output:
            return False, f"output 缺少 'task_status' 字段"

        return True, None

    def _parse_extra_params(self, ai_tool) -> Dict[str, Any]:
        """
        从 extra_config 解析可选参数
        支持: resolution (480P/720P/1080P), audio (bool), watermark (true/false),
        seed (int), prompt_extend (bool)
        """
        params = {
            "resolution": VideoResolution.P1080,  # 默认值
            "audio": True,         # 默认生成有声视频
            "watermark": False,    # 默认不添加水印
            "prompt_extend": True,  # 默认开启 prompt 智能改写
        }

        if not ai_tool.extra_config:
            return params

        try:
            config = json.loads(ai_tool.extra_config) if isinstance(ai_tool.extra_config, str) else ai_tool.extra_config
            if isinstance(config, dict):
                resolution = (
                    config.get(VIDEO_RESOLUTION_EXTRA_CONFIG_KEY)
                    or config.get(LEGACY_RESOLUTION_EXTRA_CONFIG_KEY)
                )
                if resolution in VideoResolution.WAN3_DRIVER_VALUES:
                    params["resolution"] = resolution
                if "audio" in config:
                    params["audio"] = bool(config["audio"])
                if "watermark" in config:
                    params["watermark"] = bool(config["watermark"])
                if "seed" in config:
                    seed = config["seed"]
                    if isinstance(seed, int) and 0 <= seed <= 2147483647:
                        params["seed"] = seed
                if "prompt_extend" in config:
                    params["prompt_extend"] = bool(config["prompt_extend"])
        except (json.JSONDecodeError, TypeError, ValueError):
            self.logger.warning(f"无法解析 extra_config: {ai_tool.extra_config}")

        return params

    def _resolve_ratio(self, ai_tool) -> str:
        """解析比例参数，无效值回退为 adaptive（由 API 自动推断）"""
        ratio = ai_tool.ratio or 'adaptive'
        if ratio not in SUPPORTED_RATIOS:
            ratio = 'adaptive'
        return ratio

    def _resolve_duration(self, ai_tool) -> int:
        """解析时长参数，钳制到 2-30 秒"""
        duration = ai_tool.duration or 5
        if not (MIN_DURATION <= duration <= MAX_DURATION):
            duration = 5
        return duration

    def _build_parameters(self, ai_tool, extra_params: Dict[str, Any], duration: int) -> Dict[str, Any]:
        """组装 parameters 字段（resolution/ratio/duration/audio/watermark/prompt_extend/seed）"""
        parameters = {
            "resolution": extra_params["resolution"],
            "ratio": self._resolve_ratio(ai_tool),
            "duration": duration,
            "audio": extra_params["audio"],
            "watermark": extra_params["watermark"],
            "prompt_extend": extra_params["prompt_extend"],
        }
        if "seed" in extra_params:
            parameters["seed"] = extra_params["seed"]
        return parameters

    def _build_request_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """包装请求参数（URL / method / headers / timeout）"""
        return {
            "url": f"{self._base_url}/services/aigc/video-generation/video-synthesis",
            "method": "POST",
            "json": payload,
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "X-DashScope-Async": "enable"
            },
            "timeout": self._timeout
        }

    def _upload_media_to_cdn(self, media_urls: List[str], media_type: str = "媒体") -> List[str]:
        """
        将媒体文件上传到CDN图床，确保外部API可访问

        Args:
            media_urls: 媒体文件路径或URL列表
            media_type: 媒体类型描述（用于日志）

        Returns:
            List[str]: 上传后的CDN链接列表
        """
        if not media_urls:
            return media_urls

        self.logger.info(f"准备上传{media_type}到CDN图床: {media_urls}")
        result = upload_local_images_to_cdn_sync(media_urls, self._config)
        self.logger.info(f"{media_type}上传完成，CDN链接: {result}")
        return result

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 Wan3.0 任务的完整请求参数
        根据 driver_type 自动分发到 i2v / r2v / t2v 模式
        """
        if self.driver_type == 41:
            return self._build_r2v_request(ai_tool)
        if self.driver_type == 39:
            return self._build_t2v_request(ai_tool)
        return self._build_i2v_request(ai_tool)

    def _build_i2v_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建 i2v（图生视频）请求

        支持：
        - 首帧图片（最多1张，与 prompt 必填其一，本项目必选）
        - 尾帧图片（可选，最多1张）
        """
        first_frame, last_frame = self.get_first_last_frames(ai_tool)

        if not first_frame:
            return {
                "success": False,
                "error": "缺少首帧图片",
                "error_type": "USER",
                "retry": False
            }

        # 处理首尾帧图片上传
        frames = [first_frame] + ([last_frame] if last_frame else [])
        uploaded_urls = self._upload_media_to_cdn(frames, "图片")

        media_list = [{"type": "first_frame", "url": uploaded_urls[0]}]
        if last_frame and len(uploaded_urls) > 1 and uploaded_urls[1]:
            media_list.append({"type": "last_frame", "url": uploaded_urls[1]})

        extra_params = self._parse_extra_params(ai_tool)
        duration = self._resolve_duration(ai_tool)

        payload = {
            "model": self.MODEL,
            "input": {
                "prompt": ai_tool.prompt or "",
                "media": media_list
            },
            "parameters": self._build_parameters(ai_tool, extra_params, duration)
        }

        return self._build_request_result(payload)

    def _get_r2v_image_urls(self, ai_tool) -> List[str]:
        """
        获取 r2v 模式的参考图像 URL 列表
        兼容 image_path（逗号分隔）和 reference_images（JSON 数组）两种存储方式
        """
        image_urls = []

        # 优先从 image_path 读取（逗号分隔）
        if ai_tool.image_path:
            image_urls = [url.strip() for url in ai_tool.image_path.split(',') if url.strip()]

        # 如果 image_path 为空，尝试从 reference_images 读取（JSON 数组）
        if not image_urls and ai_tool.reference_images:
            try:
                refs = json.loads(ai_tool.reference_images) if isinstance(ai_tool.reference_images, str) else ai_tool.reference_images
                if isinstance(refs, list):
                    image_urls = [str(url).strip() for url in refs if str(url).strip()]
            except (json.JSONDecodeError, TypeError):
                self.logger.warning(f"无法解析 reference_images: {ai_tool.reference_images}")

        return image_urls

    def _split_paths(self, raw: Optional[str]) -> List[str]:
        """拆分逗号分隔的媒体路径"""
        if not raw:
            return []
        return [p.strip() for p in raw.split(',') if p.strip()]

    def _sum_video_durations(self, video_paths: List[str]) -> float:
        """累加参考视频总时长（秒），无法获取时长的段跳过"""
        total = 0.0
        for path in video_paths:
            try:
                seconds = _get_media_duration_seconds(path)
            except Exception:
                seconds = None
            if seconds:
                total += seconds
        return total

    def _build_r2v_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建 r2v（参考生视频）请求

        支持：
        - 参考图像（最多10张）
        - 参考视频（最多5段，总时长≤15秒；输入总时长+输出时长≤30秒）
        - 参考音频（最多5段，总时长≤15秒）
        prompt 与 media 必填其一
        """
        duration = self._resolve_duration(ai_tool)

        # 参考图像
        image_urls = self._get_r2v_image_urls(ai_tool)
        if len(image_urls) > 10:
            self.logger.warning("参考图数量超过10张，已截取前10张")
            image_urls = image_urls[:10]

        # 参考视频（逗号分隔多段）
        video_paths = self._split_paths(self.get_video_path(ai_tool))
        if len(video_paths) > MAX_REF_MEDIA_COUNT:
            self.logger.warning(f"参考视频超过{MAX_REF_MEDIA_COUNT}段，已截取前{MAX_REF_MEDIA_COUNT}段")
            video_paths = video_paths[:MAX_REF_MEDIA_COUNT]

        # 校验：输入视频总时长 + 输出时长 ≤ 30 秒
        if video_paths:
            total_input = self._sum_video_durations(video_paths)
            if total_input > 0 and total_input + duration > MAX_DURATION:
                return {
                    "success": False,
                    "error": f"参考视频总时长({total_input:.1f}秒)+输出时长({duration}秒)超过30秒限制，请缩短参考视频或输出时长",
                    "error_type": "USER",
                    "retry": False
                }

        # 参考音频（逗号分隔多段）
        audio_paths = self._split_paths(self.get_audio_path(ai_tool))
        if len(audio_paths) > MAX_REF_MEDIA_COUNT:
            self.logger.warning(f"参考音频超过{MAX_REF_MEDIA_COUNT}段，已截取前{MAX_REF_MEDIA_COUNT}段")
            audio_paths = audio_paths[:MAX_REF_MEDIA_COUNT]

        prompt = (ai_tool.prompt or "").strip()
        if not image_urls and not video_paths and not audio_paths and not prompt:
            return {
                "success": False,
                "error": "缺少参考素材或提示词",
                "error_type": "USER",
                "retry": False
            }

        # 上传并组装 media 列表（参考图 → 参考视频 → 参考音频）
        media_list = []
        if image_urls:
            uploaded_images = self._upload_media_to_cdn(image_urls, "参考图")
            for url in uploaded_images:
                if url:
                    media_list.append({"type": "reference_image", "url": url})
        if video_paths:
            uploaded_videos = self._upload_media_to_cdn(video_paths, "参考视频")
            for url in uploaded_videos:
                if url:
                    media_list.append({"type": "reference_video", "url": url})
        if audio_paths:
            uploaded_audios = self._upload_media_to_cdn(audio_paths, "参考音频")
            for url in uploaded_audios:
                if url:
                    media_list.append({"type": "reference_audio", "url": url})

        self.logger.info(
            f"r2v 素材: 参考图={len(image_urls)}, 参考视频={len(video_paths)}, 参考音频={len(audio_paths)}"
        )

        extra_params = self._parse_extra_params(ai_tool)

        payload = {
            "model": self.MODEL,
            "input": {
                "prompt": ai_tool.prompt or "",
                "media": media_list
            },
            "parameters": self._build_parameters(ai_tool, extra_params, duration)
        }

        return self._build_request_result(payload)

    def _build_t2v_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建 t2v（文生视频）请求

        仅需要文本提示词，不需要任何图片/音频/视频
        """
        prompt = (ai_tool.prompt or "").strip()
        if not prompt:
            return {
                "success": False,
                "error": "提示词不能为空",
                "error_type": "USER",
                "retry": False
            }

        extra_params = self._parse_extra_params(ai_tool)
        duration = self._resolve_duration(ai_tool)

        payload = {
            "model": self.MODEL,
            "input": {
                "prompt": ai_tool.prompt or ""
            },
            "parameters": self._build_parameters(ai_tool, extra_params, duration)
        }

        return self._build_request_result(payload)

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 Wan3.0 任务状态的完整请求参数
        """
        return {
            "url": f"{self._base_url}/tasks/{project_id}",
            "method": "GET",
            "headers": {
                "Authorization": f"Bearer {self._api_key}"
            },
            "timeout": self._timeout
        }

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 Wan3.0 视频生成任务
        """
        try:
            if self.driver_type == 39:
                # t2v 模式：只需要 prompt
                if not ai_tool.prompt or not ai_tool.prompt.strip():
                    return {
                        "success": False,
                        "error": "提示词不能为空",
                        "error_type": "USER",
                        "retry": False
                    }
                self.logger.info(
                    f"Submitting Wan3.0 t2v task: prompt='{(ai_tool.prompt or '')[:50]}...', "
                    f"duration={ai_tool.duration}"
                )
            elif self.driver_type == 41:
                # r2v 模式：参考素材与提示词至少其一
                image_urls = self._get_r2v_image_urls(ai_tool)
                has_media = bool(image_urls or self.get_video_path(ai_tool) or self.get_audio_path(ai_tool))
                has_prompt = bool(ai_tool.prompt and ai_tool.prompt.strip())
                if not has_media and not has_prompt:
                    return {
                        "success": False,
                        "error": "缺少参考素材或提示词",
                        "error_type": "USER",
                        "retry": False
                    }
                self.logger.info(
                    f"Submitting Wan3.0 r2v task: prompt='{(ai_tool.prompt or '')[:50]}...', "
                    f"duration={ai_tool.duration}, ref_images={len(image_urls)}"
                )
            else:
                # i2v 模式：验证首帧图片
                first_frame, last_frame = self.get_first_last_frames(ai_tool)
                if not first_frame:
                    return {
                        "success": False,
                        "error": "缺少首帧图片",
                        "error_type": "USER",
                        "retry": False
                    }
                self.logger.info(
                    f"Submitting Wan3.0 i2v task: prompt='{(ai_tool.prompt or '')[:50]}...', "
                    f"duration={ai_tool.duration}, first_frame={first_frame}, "
                    f"last_frame={last_frame is not None}"
                )

            # 构建请求参数
            request_params = self.build_create_request(ai_tool)
            if "success" in request_params and not request_params["success"]:
                return request_params

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during Wan3.0 task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(f"Wan3.0 API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Wan3.0 submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_wan3_video",
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

            # 检查业务错误
            if "code" in result:
                error_msg = result.get("message") or str(result.get("code"))
                self.logger.warning(f"Wan3.0 API returned error: {error_msg}")
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_msg}",
                    "error_type": "USER",
                    "retry": False
                }

            # 提取任务ID
            output = result.get("output", {})
            task_id = output.get("task_id")
            if not task_id:
                self._send_alert(
                    alert_type="MISSING_TASK_ID",
                    message="Wan3.0 submit_task 响应缺少 task_id",
                    context={
                        "api": "create_wan3_video",
                        "response": result,
                        "ai_tool_id": ai_tool.id
                    }
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": task_id
            }

        except Exception as e:
            self.logger.error(f"Unexpected exception in Wan3.0 submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Wan3.0 submit_task 发生未预期异常: {str(e)}",
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
        检查 Wan3.0 任务状态
        """
        try:
            self.logger.info(f"Checking Wan3.0 task status: project_id={project_id}")

            # 构建请求参数并调用统一请求方法
            request_params = self.build_check_query(project_id)

            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during Wan3.0 status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            self.logger.info(f"Wan3.0 status API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_status_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Wan3.0 check_status 响应格式错误: {validation_error}",
                    context={
                        "api": "get_wan3_task_status",
                        "response": result,
                        "project_id": project_id
                    }
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {validation_error}"
                }

            # 检查业务错误
            if "code" in result:
                error_msg = result.get("message") or str(result.get("code"))
                self.logger.warning(f"Wan3.0 status API returned error: {error_msg}")
                return {
                    "status": "FAILED",
                    "error": f"查询任务状态失败: {error_msg}",
                    "error_type": "USER"
                }

            # 提取状态
            output = result.get("output", {})
            task_status = output.get("task_status", "UNKNOWN")

            # 映射状态到统一状态
            if task_status == "SUCCEEDED":
                video_url = output.get("video_url")
                if video_url:
                    return {
                        "status": "SUCCESS",
                        "result_url": video_url
                    }
                else:
                    return {
                        "status": "FAILED",
                        "error": "任务成功但未返回视频URL",
                        "error_type": "SYSTEM"
                    }
            elif task_status == "FAILED":
                error_code = output.get("code", "任务执行失败")
                error_message = output.get("message", error_code)
                return {
                    "status": "FAILED",
                    "error": error_message,
                    "error_type": "USER"
                }
            elif task_status == "CANCELED":
                return {
                    "status": "FAILED",
                    "error": "任务已取消",
                    "error_type": "USER"
                }
            elif task_status == "UNKNOWN":
                return {
                    "status": "FAILED",
                    "error": "任务不存在或已过期",
                    "error_type": "USER"
                }
            elif task_status in ("PENDING", "RUNNING"):
                return {
                    "status": "RUNNING",
                    "message": f"任务{task_status == 'PENDING' and '排队中' or '处理中'}..."
                }
            else:
                self.logger.warning(f"Unknown Wan3.0 task status: {task_status}")
                return {
                    "status": "RUNNING",
                    "message": f"任务状态: {task_status}"
                }

        except Exception as e:
            self.logger.error(f"Unexpected exception in Wan3.0 check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Wan3.0 check_status 发生未预期异常: {str(e)}",
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


class Wan3DashscopeR2VV1Driver(Wan3DashscopeV1Driver):
    """
    Wan3.0 参考生视频驱动（r2v）
    支持参考图像/参考视频/参考音频 + 文本提示词生成视频
    """

    def __init__(self):
        super().__init__(driver_name="wan3_video_dashscope_r2v_v1", driver_type=41)


class Wan3DashscopeT2VV1Driver(Wan3DashscopeV1Driver):
    """
    Wan3.0 文生视频驱动（t2v）
    仅需要文本提示词生成视频
    """

    def __init__(self):
        super().__init__(driver_name="wan3_video_dashscope_t2v_v1", driver_type=39)


class Wan3VideoPrimeDashscopeV1Driver(Wan3DashscopeV1Driver):
    """
    Wan3.0 图生视频驱动（高速版 wan3.0-video-prime）
    """
    MODEL = "wan3.0-video-prime"

    def __init__(self):
        super().__init__(driver_name="wan3_video_prime_dashscope_v1", driver_type=40)


class Wan3VideoPrimeDashscopeR2VV1Driver(Wan3DashscopeR2VV1Driver):
    """
    Wan3.0 参考生视频驱动（高速版 wan3.0-video-prime）
    """
    MODEL = "wan3.0-video-prime"

    def __init__(self):
        Wan3DashscopeV1Driver.__init__(self, driver_name="wan3_video_prime_dashscope_r2v_v1", driver_type=41)


class Wan3VideoPrimeDashscopeT2VV1Driver(Wan3DashscopeT2VV1Driver):
    """
    Wan3.0 文生视频驱动（高速版 wan3.0-video-prime）
    """
    MODEL = "wan3.0-video-prime"

    def __init__(self):
        Wan3DashscopeV1Driver.__init__(self, driver_name="wan3_video_prime_dashscope_t2v_v1", driver_type=39)
