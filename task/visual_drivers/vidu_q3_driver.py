"""
Vidu Q3 官方驱动实现（api.vidu.cn）
模型: viduq3-turbo / viduq3-pro（reference2video 端点的 pro 档模型名为 viduq3）
支持文生视频（t2v）、图生视频（首尾帧 i2v）、参考生视频（r2v），异步任务模式
认证头：Authorization: Token {api_key}（注意是 Token 不是 Bearer）
"""
from typing import Dict, Any, List, Optional
import json
import traceback
from .base_video_driver import BaseVideoDriver
from config.config_util import get_config, get_dynamic_config_value
from config.constant import LEGACY_RESOLUTION_EXTRA_CONFIG_KEY, VIDEO_RESOLUTION_EXTRA_CONFIG_KEY
from config.unified_config import VideoResolution
from utils.sentry_util import SentryUtil, AlertLevel
from utils.image_upload_utils import upload_local_images_to_cdn_sync

# 文生视频支持的比例
SUPPORTED_RATIOS_T2V = ('16:9', '9:16', '3:4', '4:3', '1:1')
# 参考生视频支持的比例
SUPPORTED_RATIOS_R2V = ('16:9', '9:16', '1:1')
# 参考生视频参考图上限
MAX_R2V_IMAGES = 7


class ViduQ3TurboV1Driver(BaseVideoDriver):
    """
    Vidu Q3 图生视频驱动（turbo）
    1 张图片走 img2video，2 张图片走 start-end2video
    """

    # 各端点模型名（pro 子类覆盖；注意 reference2video 的 pro 档模型名为 viduq3）
    MODEL_IMG2V = 'viduq3-turbo'
    MODEL_SE2V = 'viduq3-turbo'
    MODEL_T2V = 'viduq3-turbo'
    MODEL_R2V = 'viduq3-turbo'

    def __init__(self, driver_name: str = "vidu_q3_i2v_turbo_v1", driver_type: int = 43):
        super().__init__(driver_name=driver_name, driver_type=driver_type)

        # 加载配置（复用 vidu.token）
        self._api_key = get_dynamic_config_value("vidu", "token", default="")
        self._base_url = "https://api.vidu.cn"
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        self._config = get_config()

        self._validate_required({
            "Vidu Token": self._api_key,
        })

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

        期望的正确响应格式:
        {
            "task_id": "task_123456789",
            "state": "created",  # created, queueing, processing, success, failed
            ...
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        # 检查是否有错误
        if "error" in result:
            return True, None  # 有错误字段，格式有效但业务失败

        if "task_id" not in result:
            return False, f"响应缺少 'task_id' 字段，实际字段: {list(result.keys())}"

        if not isinstance(result.get("task_id"), str):
            return False, f"'task_id' 字段类型错误，期望 str，实际: {type(result.get('task_id'))}"

        if "state" not in result:
            return False, f"响应缺少 'state' 字段，实际字段: {list(result.keys())}"

        return True, None

    def _validate_status_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 check_status API 响应格式

        期望的正确响应格式:
        {
            "id": "916920905987280896",
            "state": "processing",  # created, queueing, processing, success, failed
            "err_code": "",
            "creations": [],  # 处理中时为空，完成后包含结果
            ...
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        # 检查是否有错误
        if "error" in result:
            return True, None  # 有错误字段，格式有效但业务失败

        if "id" not in result:
            return False, f"响应缺少 'id' 字段，实际字段: {list(result.keys())}"

        if "state" not in result:
            return False, f"响应缺少 'state' 字段，实际字段: {list(result.keys())}"

        if "creations" not in result:
            return False, f"响应缺少 'creations' 字段，实际字段: {list(result.keys())}"

        task_state = result.get("state")
        if task_state == "success":
            creations = result.get("creations")
            if not isinstance(creations, list):
                return False, "任务成功但 'creations' 类型错误"

            # creations 可以为空列表（表示任务完成但没有结果）
            if len(creations) > 0 and "url" not in creations[0]:
                return False, "创作对象缺少 'url' 字段"

        return True, None

    def _parse_extra_params(self, ai_tool) -> Dict[str, Any]:
        """
        从 extra_config 解析可选参数
        支持: video_resolution/resolution (540P/720P/1080P), audio (bool),
        audio_type (str), seed (int), watermark (bool), off_peak (bool)
        """
        params = {
            "resolution": VideoResolution.P720,  # 默认值
            "audio": True,         # q3 默认生成有声视频
            "audio_type": "all",   # audio=true 时默认全部音频
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
                if resolution in VideoResolution.VIDU_Q3_DRIVER_VALUES:
                    params["resolution"] = resolution
                if "audio" in config:
                    params["audio"] = bool(config["audio"])
                if "audio_type" in config and config["audio_type"]:
                    params["audio_type"] = str(config["audio_type"])
                if "watermark" in config:
                    params["watermark"] = bool(config["watermark"])
                if "off_peak" in config:
                    params["off_peak"] = bool(config["off_peak"])
                if "seed" in config:
                    seed = config["seed"]
                    if isinstance(seed, int) and 0 <= seed <= 2147483647:
                        params["seed"] = seed
        except (json.JSONDecodeError, TypeError, ValueError):
            self.logger.warning(f"无法解析 extra_config: {ai_tool.extra_config}")

        return params

    def _resolve_duration(self, ai_tool, min_duration: int = 1) -> int:
        """解析时长参数，默认 5 秒，钳制到 min_duration-16 秒"""
        duration = ai_tool.duration or 5
        if not (min_duration <= duration <= 16):
            duration = 5
        return duration

    def _resolve_ratio(self, ai_tool, supported: tuple) -> str:
        """解析比例参数，无效值回退为 16:9"""
        ratio = ai_tool.ratio or '16:9'
        if ratio not in supported:
            ratio = '16:9'
        return ratio

    def _resolve_resolution_value(self, extra_params: Dict[str, Any]) -> str:
        """把标准分辨率（大写）转换为 Vidu 下发值（小写）"""
        return VideoResolution.VIDU_Q3_DRIVER_VALUES.get(
            extra_params.get("resolution"), '720p'
        )

    def _apply_common_params(self, payload: Dict[str, Any], extra_params: Dict[str, Any]):
        """应用公共参数：resolution / audio / audio_type / seed / watermark / off_peak

        注意：q3 系列不生效的参数（movement_amplitude / style / bgm / voice_id）禁止下发
        """
        payload["resolution"] = self._resolve_resolution_value(extra_params)
        payload["audio"] = extra_params["audio"]
        if extra_params["audio"]:
            payload["audio_type"] = extra_params["audio_type"]
        for key in ("seed", "watermark", "off_peak"):
            if key in extra_params:
                payload[key] = extra_params[key]

    def _upload_images_to_cdn(self, image_urls: List[str]) -> List[str]:
        """将图片上传到CDN图床，确保外部API可访问"""
        if not image_urls:
            return image_urls

        self.logger.info(f"准备上传图片到CDN图床: {image_urls}")
        result = upload_local_images_to_cdn_sync(image_urls, self._config)
        self.logger.info(f"图片上传完成，CDN链接: {result}")
        return result if result else image_urls

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 Vidu Q3 任务的完整请求参数
        根据 driver_type 自动分发到 i2v / r2v / t2v 模式
        """
        if self.driver_type == 44:
            return self._build_r2v_request(ai_tool)
        if self.driver_type == 42:
            return self._build_t2v_request(ai_tool)
        return self._build_i2v_request(ai_tool)

    def _build_i2v_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建 i2v（图生视频）请求

        - 1 张图片：img2video（images=[首帧]）
        - 2 张图片：start-end2video（images=[首帧, 尾帧]）
        两个端点均无 aspect_ratio 参数，不下发
        """
        first_frame, last_frame = self.get_first_last_frames(ai_tool)

        if not first_frame:
            return {
                "success": False,
                "error": "缺少首帧图片",
                "error_type": "USER",
                "retry": False
            }

        frames = [first_frame] + ([last_frame] if last_frame else [])
        uploaded_urls = self._upload_images_to_cdn(frames)

        extra_params = self._parse_extra_params(ai_tool)

        if last_frame and len(uploaded_urls) > 1 and uploaded_urls[1]:
            # 首尾帧：第 1 张首帧，第 2 张尾帧
            url = f"{self._base_url}/ent/v2/start-end2video"
            payload = {
                "model": self.MODEL_SE2V,
                "images": [uploaded_urls[0], uploaded_urls[1]],
                "prompt": ai_tool.prompt or "",
                "duration": self._resolve_duration(ai_tool),
            }
        else:
            url = f"{self._base_url}/ent/v2/img2video"
            payload = {
                "model": self.MODEL_IMG2V,
                "images": [uploaded_urls[0]],
                "prompt": ai_tool.prompt or "",
                "duration": self._resolve_duration(ai_tool),
            }

        self._apply_common_params(payload, extra_params)
        return self._build_request_result(url, payload)

    def _build_t2v_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建 t2v（文生视频）请求，仅需要文本提示词
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

        payload = {
            "model": self.MODEL_T2V,
            "prompt": prompt,
            "duration": self._resolve_duration(ai_tool),
            "aspect_ratio": self._resolve_ratio(ai_tool, SUPPORTED_RATIOS_T2V),
        }
        self._apply_common_params(payload, extra_params)
        return self._build_request_result(f"{self._base_url}/ent/v2/text2video", payload)

    def _get_r2v_image_urls(self, ai_tool) -> List[str]:
        """
        获取 r2v 模式的参考图像 URL 列表
        合并 image_path（逗号分隔）和 reference_images（JSON 数组）两种存储方式，去重保序
        """
        image_urls = []

        if ai_tool.image_path:
            if isinstance(ai_tool.image_path, str):
                image_urls.extend(url.strip() for url in ai_tool.image_path.split(',') if url.strip())
            else:
                image_urls.extend(ai_tool.image_path)

        if ai_tool.reference_images:
            try:
                refs = json.loads(ai_tool.reference_images) if isinstance(ai_tool.reference_images, str) else ai_tool.reference_images
                if isinstance(refs, list):
                    image_urls.extend(str(url).strip() for url in refs if str(url).strip())
            except (json.JSONDecodeError, TypeError):
                self.logger.warning(f"无法解析 reference_images: {ai_tool.reference_images}")

        # 去重保序
        return list(dict.fromkeys(image_urls))

    def _build_r2v_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建 r2v（参考生视频）请求

        - images: 1-7 张参考图（必填）
        - prompt: 必填
        """
        image_urls = self._get_r2v_image_urls(ai_tool)
        if not image_urls:
            return {
                "success": False,
                "error": "缺少参考图片",
                "error_type": "USER",
                "retry": False
            }
        if len(image_urls) > MAX_R2V_IMAGES:
            self.logger.warning(f"参考图数量超过{MAX_R2V_IMAGES}张，已截取前{MAX_R2V_IMAGES}张")
            image_urls = image_urls[:MAX_R2V_IMAGES]

        prompt = (ai_tool.prompt or "").strip()
        if not prompt:
            return {
                "success": False,
                "error": "提示词不能为空",
                "error_type": "USER",
                "retry": False
            }

        uploaded_urls = self._upload_images_to_cdn(image_urls)

        extra_params = self._parse_extra_params(ai_tool)

        payload = {
            "model": self.MODEL_R2V,
            "images": uploaded_urls,
            "prompt": prompt,
            "duration": self._resolve_duration(ai_tool, min_duration=3),
            "aspect_ratio": self._resolve_ratio(ai_tool, SUPPORTED_RATIOS_R2V),
        }
        self._apply_common_params(payload, extra_params)
        return self._build_request_result(f"{self._base_url}/ent/v2/reference2video", payload)

    def _build_request_result(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """包装请求参数（URL / method / headers）"""
        return {
            "url": url,
            "method": "POST",
            "json": payload,
            "headers": {
                "Authorization": f"Token {self._api_key}",
                "Content-Type": "application/json"
            }
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 Vidu Q3 任务状态的完整请求参数

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        return {
            "url": f"{self._base_url}/ent/v2/tasks/{project_id}/creations",
            "method": "GET",
            "json": None,
            "headers": {
                "Authorization": f"Token {self._api_key}",
                "Content-Type": "application/json"
            }
        }

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 Vidu Q3 视频生成任务

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词
                - image_path: 图片路径（逗号分隔）
                - reference_images: 参考图（JSON 数组，r2v 模式）
                - duration: 视频时长（1-16，r2v 为 3-16）

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(
                f"Submitting Vidu Q3 task: driver={self.driver_name}, "
                f"prompt='{(ai_tool.prompt or '')[:50]}...', duration={ai_tool.duration}"
            )

            # 构建请求参数（参数校验在 build 内完成，失败返回 USER 错误）
            request_params = self.build_create_request(ai_tool)
            if "success" in request_params and not request_params["success"]:
                return request_params

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during Vidu Q3 task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(f"Vidu Q3 API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                # 格式错误，发送报警，不重试
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Vidu Q3 submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_vidu_q3_video",
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
            if "error" in result:
                error_msg = result.get("error", "未知错误")
                self.logger.warning(f"Vidu Q3 API returned error: {error_msg}")
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_msg}",
                    "error_type": "USER",
                    "retry": False
                }

            task_id = result.get("task_id")
            if not task_id:
                # task_id 已在 _validate_submit_response 中验证，这里理论上不会发生
                self._send_alert(
                    alert_type="MISSING_TASK_ID",
                    message="Vidu Q3 submit_task 响应缺少 task_id",
                    context={
                        "api": "create_vidu_q3_video",
                        "response": result,
                        "ai_tool_id": ai_tool.id
                    }
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "Vidu Q3 API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": task_id
            }

        except Exception as e:
            # 非网络异常，发送报警，不重试
            self.logger.error(f"Unexpected exception in Vidu Q3 submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Vidu Q3 submit_task 发生未预期异常: {str(e)}",
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
        检查 Vidu Q3 任务状态

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking Vidu Q3 task status: project_id={project_id}")

            # 构建请求参数并调用统一请求方法
            request_params = self.build_check_query(project_id)

            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during Vidu Q3 status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            self.logger.info(f"Vidu Q3 status API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_status_response(result)
            if not is_valid:
                # 格式错误，发送报警
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Vidu Q3 check_status 响应格式错误: {validation_error}",
                    context={
                        "api": "get_vidu_q3_task_status",
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
            if "error" in result:
                error_msg = result.get("error", "未知错误")
                self.logger.warning(f"Vidu Q3 status API returned error: {error_msg}")
                return {
                    "status": "FAILED",
                    "error": f"查询任务状态失败: {error_msg}",
                    "error_type": "SYSTEM"
                }

            task_state = result.get("state", "")

            # 映射 Vidu 状态到统一状态
            if task_state == "success":
                creations = result.get("creations", [])
                if creations and len(creations) > 0:
                    result_url = creations[0].get("url")
                    return {
                        "status": "SUCCESS",
                        "result_url": result_url
                    }
                else:
                    return {
                        "status": "FAILED",
                        "error": "任务成功但未返回视频URL",
                        "error_type": "SYSTEM"
                    }
            elif task_state == "failed":
                error_code = result.get("err_code", "任务失败")
                return {
                    "status": "FAILED",
                    "error": error_code,
                    "error_type": "USER"
                }
            elif task_state in ["created", "queueing", "processing"]:
                # 任务创建、排队或处理中
                return {
                    "status": "RUNNING",
                    "message": "任务处理中..."
                }
            else:
                # 未知状态
                self.logger.warning(f"Unknown Vidu Q3 task state: {task_state}")
                return {
                    "status": "RUNNING",
                    "message": f"任务状态: {task_state}"
                }

        except Exception as e:
            # 非网络异常，发送报警
            self.logger.error(f"Unexpected exception in Vidu Q3 check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Vidu Q3 check_status 发生未预期异常: {str(e)}",
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


class ViduQ3TurboR2VV1Driver(ViduQ3TurboV1Driver):
    """
    Vidu Q3 参考生视频驱动（turbo）
    支持 1-7 张参考图 + 文本提示词生成视频
    """

    def __init__(self):
        super().__init__(driver_name="vidu_q3_r2v_turbo_v1", driver_type=44)


class ViduQ3TurboT2VV1Driver(ViduQ3TurboV1Driver):
    """
    Vidu Q3 文生视频驱动（turbo）
    仅需要文本提示词生成视频
    """

    def __init__(self):
        super().__init__(driver_name="vidu_q3_t2v_turbo_v1", driver_type=42)


class ViduQ3ProV1Driver(ViduQ3TurboV1Driver):
    """
    Vidu Q3 图生视频驱动（pro）
    注意：reference2video 端点的 pro 档模型名为 viduq3，其余端点为 viduq3-pro
    """
    MODEL_IMG2V = 'viduq3-pro'
    MODEL_SE2V = 'viduq3-pro'
    MODEL_T2V = 'viduq3-pro'
    MODEL_R2V = 'viduq3'

    def __init__(self):
        super().__init__(driver_name="vidu_q3_i2v_pro_v1", driver_type=43)


class ViduQ3ProR2VV1Driver(ViduQ3TurboR2VV1Driver):
    """
    Vidu Q3 参考生视频驱动（pro，reference2video 模型名为 viduq3）
    """
    MODEL_IMG2V = 'viduq3-pro'
    MODEL_SE2V = 'viduq3-pro'
    MODEL_T2V = 'viduq3-pro'
    MODEL_R2V = 'viduq3'

    def __init__(self):
        ViduQ3TurboV1Driver.__init__(self, driver_name="vidu_q3_r2v_pro_v1", driver_type=44)


class ViduQ3ProT2VV1Driver(ViduQ3TurboT2VV1Driver):
    """
    Vidu Q3 文生视频驱动（pro）
    """
    MODEL_IMG2V = 'viduq3-pro'
    MODEL_SE2V = 'viduq3-pro'
    MODEL_T2V = 'viduq3-pro'
    MODEL_R2V = 'viduq3'

    def __init__(self):
        ViduQ3TurboV1Driver.__init__(self, driver_name="vidu_q3_t2v_pro_v1", driver_type=42)
