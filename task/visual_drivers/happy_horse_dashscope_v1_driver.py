"""
Happy Horse 阿里云百炼驱动实现
模型: happyhorse-1.0-i2v
支持图生视频（基于首帧），异步任务模式
"""
from typing import Dict, Any, Optional, List
import os
import traceback
import json
from pathlib import Path
from .base_video_driver import BaseVideoDriver, ImageMode
from config.config_util import get_config, get_dynamic_config_value
from config.constant import LEGACY_RESOLUTION_EXTRA_CONFIG_KEY, VIDEO_RESOLUTION_EXTRA_CONFIG_KEY
from api.media import _get_media_duration_seconds
from utils.sentry_util import SentryUtil, AlertLevel
from utils.image_upload_utils import upload_local_images_to_cdn_sync


class HappyHorseDashscopeV1Driver(BaseVideoDriver):
    """
    Happy Horse 图生视频驱动（阿里云百炼 DashScope）
    支持单张首帧图片 + 可选的驱动音频和驱动视频
    """

    MODEL = "happyhorse-1.0-i2v"

    def __init__(self, driver_name: str = "happy_horse_dashscope_v1", driver_type: int = 28):
        super().__init__(driver_name=driver_name, driver_type=driver_type)

        # 加载配置（复用 LLM 配置的阿里云 Qwen API Key）
        self._api_key = get_dynamic_config_value("llm", "qwen", "api_key", default="")
        self._base_url = "https://dashscope.aliyuncs.com/api/v1"
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        # 是否为本地环境
        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        self._validate_required({
            "DashScope API Key": self._api_key,
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
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "error" in result:
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

        if "error" in result:
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
        支持: resolution (720P/1080P), watermark (true/false), seed (int), prompt_extend (bool)
        """
        params = {
            "resolution": "720P",  # 默认值
            "watermark": False,      # 默认添加水印
            "prompt_extend": True,  # 默认开启 prompt 扩展
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
                if resolution in ("720P", "1080P"):
                    params["resolution"] = resolution
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

    def _get_audio_duration(self, audio_path: str) -> Optional[float]:
        """
        获取音频文件时长（秒），复用 api/media.py 的 ffprobe 逻辑
        """
        if not audio_path or not os.path.exists(audio_path):
            return None

        try:
            return _get_media_duration_seconds(audio_path)
        except Exception:
            return None

    def _validate_audio(self, audio_path: str, video_duration: int) -> tuple[bool, Optional[str]]:
        """
        校验音频文件是否符合 Happy Horse API 要求

        返回: (是否通过, 错误信息)
        """
        if not audio_path:
            return True, None

        # 1. 格式校验
        ext = Path(audio_path).suffix.lower()
        if ext not in (".wav", ".mp3"):
            return False, f"音频格式不支持: {ext}，仅支持 wav、mp3"

        # 2. 文件大小校验（≤15MB）
        try:
            if os.path.exists(audio_path):
                size_mb = os.path.getsize(audio_path) / (1024 * 1024)
                if size_mb > 15:
                    return False, f"音频文件过大: {size_mb:.1f}MB，限制 15MB"
        except OSError:
            pass

        # 3. 时长校验（2-30秒）
        duration = self._get_audio_duration(audio_path)
        if duration is not None:
            if duration < 2:
                return False, f"音频时长过短: {duration:.1f}秒，要求 2-30 秒"
            if duration > 30:
                return False, f"音频时长过长: {duration:.1f}秒，要求 2-30 秒"

            # 4. 截断提示（API 会自动截断，但提醒用户）
            if duration > video_duration:
                self.logger.info(
                    f"音频时长({duration:.1f}s)超过视频时长({video_duration}s)，"
                    f"API 将自动截取前 {video_duration} 秒"
                )
            elif duration < video_duration:
                self.logger.info(
                    f"音频时长({duration:.1f}s)短于视频时长({video_duration}s)，"
                    f"超出部分为无声视频"
                )

        return True, None

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
        构建创建 Happy Horse 任务的完整请求参数
        根据 driver_type 自动分发到 i2v / r2v / t2v 模式
        """
        if self.driver_type == 29:
            return self._build_r2v_request(ai_tool)
        if self.driver_type == 30:
            return self._build_t2v_request(ai_tool)
        return self._build_i2v_request(ai_tool)

    def _build_i2v_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建 i2v（图生视频）请求

        支持：
        - 首帧图片（有且仅有1张，必须）
        - 驱动音频（可选，type=driving_audio）
        - 驱动视频（可选，type=driving_video）
        ratio 由 API 从首帧自动推断
        """
        # 获取首帧图片（仅取第一张）
        first_frame, _ = self.get_first_last_frames(ai_tool)

        if not first_frame:
            return {
                "success": False,
                "error": "缺少首帧图片",
                "error_type": "USER",
                "retry": False
            }

        # 处理首帧图片上传
        image_urls = self._upload_media_to_cdn([first_frame], "图片")
        first_frame_url = image_urls[0]

        # 构建 media 列表
        media_list = [
            {
                "type": "first_frame",
                "url": first_frame_url
            }
        ]

        # 解析 extra_config 中的可选参数
        extra_params = self._parse_extra_params(ai_tool)

        # 确定视频时长（音频校验需要）
        duration = ai_tool.duration or 5
        if not (3 <= duration <= 15):
            duration = 5

        # 处理驱动音频
        audio_path = self.get_audio_path(ai_tool)
        if audio_path:
            # 校验音频文件
            is_valid, error_msg = self._validate_audio(audio_path, duration)
            if not is_valid:
                return {
                    "success": False,
                    "error": error_msg,
                    "error_type": "USER",
                    "retry": False
                }
            audio_urls = self._upload_media_to_cdn([audio_path], "音频")
            if audio_urls and audio_urls[0]:
                media_list.append({
                    "type": "driving_audio",
                    "url": audio_urls[0]
                })
                self.logger.info(f"已添加驱动音频: {audio_urls[0]}")

        # 处理驱动视频
        video_path = self.get_video_path(ai_tool)
        if video_path:
            video_urls = self._upload_media_to_cdn([video_path], "视频")
            if video_urls and video_urls[0]:
                media_list.append({
                    "type": "driving_video",
                    "url": video_urls[0]
                })
                self.logger.info(f"已添加驱动视频: {video_urls[0]}")

        payload = {
            "model": self.MODEL,
            "input": {
                "prompt": ai_tool.prompt or "",
                "media": media_list
            },
            "parameters": {
                "resolution": extra_params["resolution"],
                "duration": duration,
                "watermark": extra_params["watermark"],
                "prompt_extend": extra_params["prompt_extend"]
            }
        }

        # 可选参数：seed
        if "seed" in extra_params:
            payload["parameters"]["seed"] = extra_params["seed"]

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

    def _build_r2v_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建 r2v（参考生视频）请求

        支持：
        - 多张参考图像（1-9张，必须）
        - 文本提示词中通过 [Image 1]、[Image 2] 指代参考图像
        - 支持 ratio 参数
        """
        # 获取参考图像
        image_urls = self._get_r2v_image_urls(ai_tool)
        if not image_urls:
            return {
                "success": False,
                "error": "缺少参考图片",
                "error_type": "USER",
                "retry": False
            }

        if len(image_urls) > 9:
            self.logger.warning(f"参考图数量超过9张，已截取前9张")
            image_urls = image_urls[:9]

        # 上传所有参考图
        uploaded_urls = self._upload_media_to_cdn(image_urls, "参考图")

        # 构建 media 列表
        media_list = []
        for url in uploaded_urls:
            if url:
                media_list.append({
                    "type": "reference_image",
                    "url": url
                })

        if not media_list:
            return {
                "success": False,
                "error": "参考图片上传失败",
                "error_type": "SYSTEM",
                "retry": True
            }

        self.logger.info(f"已添加 {len(media_list)} 张参考图")

        # 解析 extra_config 中的可选参数
        extra_params = self._parse_extra_params(ai_tool)

        # 构建请求体
        duration = ai_tool.duration or 5
        if not (3 <= duration <= 15):
            duration = 5

        ratio = ai_tool.ratio or '16:9'
        if ratio not in ('16:9', '9:16', '3:4', '4:3', '1:1'):
            ratio = '16:9'

        payload = {
            "model": self.MODEL,
            "input": {
                "prompt": ai_tool.prompt or "",
                "media": media_list
            },
            "parameters": {
                "resolution": extra_params["resolution"],
                "ratio": ratio,
                "duration": duration,
                "watermark": extra_params["watermark"]
            }
        }

        # 可选参数：seed
        if "seed" in extra_params:
            payload["parameters"]["seed"] = extra_params["seed"]

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

    def _build_t2v_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建 t2v（文生视频）请求

        仅需要文本提示词，不需要任何图片/音频/视频
        """
        # 解析 extra_config 中的可选参数
        extra_params = self._parse_extra_params(ai_tool)

        # 构建请求体
        duration = ai_tool.duration or 5
        if not (3 <= duration <= 15):
            duration = 5

        ratio = ai_tool.ratio or '16:9'
        if ratio not in ('16:9', '9:16', '1:1', '4:3', '3:4'):
            ratio = '16:9'

        payload = {
            "model": self.MODEL,
            "input": {
                "prompt": ai_tool.prompt or ""
            },
            "parameters": {
                "resolution": extra_params["resolution"],
                "ratio": ratio,
                "duration": duration,
                "watermark": extra_params["watermark"]
            }
        }

        # 可选参数：seed
        if "seed" in extra_params:
            payload["parameters"]["seed"] = extra_params["seed"]

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

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 Happy Horse 任务状态的完整请求参数
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
        提交 Happy Horse 视频生成任务
        """
        try:
            if self.driver_type == 30:
                # t2v 模式：只需要 prompt
                if not ai_tool.prompt or not ai_tool.prompt.strip():
                    return {
                        "success": False,
                        "error": "提示词不能为空",
                        "error_type": "USER",
                        "retry": False
                    }
                self.logger.info(
                    f"Submitting Happy Horse t2v task: prompt='{(ai_tool.prompt or '')[:50]}...', "
                    f"duration={ai_tool.duration}"
                )
            elif self.driver_type == 29:
                # r2v 模式：验证参考图片
                image_urls = self._get_r2v_image_urls(ai_tool)
                if not image_urls:
                    return {
                        "success": False,
                        "error": "缺少参考图片",
                        "error_type": "USER",
                        "retry": False
                    }
                self.logger.info(
                    f"Submitting Happy Horse r2v task: prompt='{(ai_tool.prompt or '')[:50]}...', "
                    f"duration={ai_tool.duration}, ref_images={len(image_urls)}"
                )
            else:
                # i2v 模式：验证首帧图片
                first_frame, _ = self.get_first_last_frames(ai_tool)
                if not first_frame:
                    return {
                        "success": False,
                        "error": "缺少首帧图片",
                        "error_type": "USER",
                        "retry": False
                    }

                audio_path = self.get_audio_path(ai_tool)
                video_path = self.get_video_path(ai_tool)
                self.logger.info(
                    f"Submitting Happy Horse i2v task: prompt='{(ai_tool.prompt or '')[:50]}...', "
                    f"duration={ai_tool.duration}, first_frame={first_frame}, "
                    f"audio={audio_path is not None}, video={video_path is not None}"
                )

            # 构建请求参数
            request_params = self.build_create_request(ai_tool)
            if "success" in request_params and not request_params["success"]:
                return request_params

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during Happy Horse task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(f"Happy Horse API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Happy Horse submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_happy_horse_video",
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
                error_code = result.get("error", {})
                error_msg = "未知错误"
                if isinstance(error_code, dict):
                    error_msg = error_code.get("message", str(error_code))
                else:
                    error_msg = str(error_code)
                self.logger.warning(f"Happy Horse API returned error: {error_msg}")
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
                    message="Happy Horse submit_task 响应缺少 task_id",
                    context={
                        "api": "create_happy_horse_video",
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
            self.logger.error(f"Unexpected exception in Happy Horse submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Happy Horse submit_task 发生未预期异常: {str(e)}",
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
        检查 Happy Horse 任务状态
        """
        try:
            self.logger.info(f"Checking Happy Horse task status: project_id={project_id}")

            # 构建请求参数并调用统一请求方法
            request_params = self.build_check_query(project_id)

            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during Happy Horse status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            self.logger.info(f"Happy Horse status API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_status_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Happy Horse check_status 响应格式错误: {validation_error}",
                    context={
                        "api": "get_happy_horse_task_status",
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
                error_code = result.get("error", {})
                error_msg = "未知错误"
                if isinstance(error_code, dict):
                    error_msg = error_code.get("message", str(error_code))
                else:
                    error_msg = str(error_code)
                self.logger.warning(f"Happy Horse status API returned error: {error_msg}")
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
                self.logger.warning(f"Unknown Happy Horse task status: {task_status}")
                return {
                    "status": "RUNNING",
                    "message": f"任务状态: {task_status}"
                }

        except Exception as e:
            self.logger.error(f"Unexpected exception in Happy Horse check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Happy Horse check_status 发生未预期异常: {str(e)}",
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


class HappyHorseDashscopeR2VV1Driver(HappyHorseDashscopeV1Driver):
    """
    Happy Horse 参考生视频驱动（r2v）
    支持多张参考图像 + 文本提示词生成视频
    """
    MODEL = "happyhorse-1.0-r2v"

    def __init__(self):
        super().__init__(driver_name="happy_horse_dashscope_r2v_v1", driver_type=29)


class HappyHorseDashscopeT2VV1Driver(HappyHorseDashscopeV1Driver):
    """
    Happy Horse 文生视频驱动（t2v）
    仅需要文本提示词生成视频
    """
    MODEL = "happyhorse-1.0-t2v"

    def __init__(self):
        super().__init__(driver_name="happy_horse_dashscope_t2v_v1", driver_type=30)
