"""
Seedance 火山引擎供应商 v1 版本驱动实现
异步 API - 创建任务后轮询状态
支持 Seedance 1.5 Pro / 2.0 Fast / 2.0 三个模型（图生视频）

基类 SeedanceVolcengineV1Driver 包含核心逻辑，
子类通过 driver_type 和 model_name 区分不同模型。
"""
from typing import Dict, Any, Optional
import traceback
import json
from .base_video_driver import BaseVideoDriver
from config.config_util import get_config, get_dynamic_config_value
from utils.sentry_util import SentryUtil, AlertLevel
from utils.image_upload_utils import compress_and_upload_image_sync


class SeedanceVolcengineV1Driver(BaseVideoDriver):
    """
    Seedance 火山引擎供应商 v1 版本驱动（基类）
    异步 API - 图生视频

    子类通过不同的 driver_type 和 model_name 区分模型。

    注意：不应直接实例化基类，应使用具体的子类。
    """

    def __init__(self, driver_type: int, model_name: str):
        """
        初始化驱动

        Args:
            driver_type: 驱动类型（对应 TaskTypeId）
            model_name: 模型名称（如 doubao-seedance-1-5-pro-251215）
        """
        super().__init__(driver_name="seedance_volcengine_v1", driver_type=driver_type)

        # 加载配置
        self._api_key = get_dynamic_config_value("volcengine", "api_key", default="")
        self._base_url = "https://ark.cn-beijing.volces.com"
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        # 模型名称
        self._model = model_name

        # 是否为本地环境
        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

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
            "status": "processing"|"succeeded"|"failed",
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
        if status not in ("running", "succeeded", "failed"):
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
        构建 Seedance 图生视频创建任务请求

        content 数组格式:
        [
            { "type": "text", "text": "prompt" },
            { "type": "image_url", "image_url": { "url": "首帧图" } },
            { "type": "image_url", "image_url": { "url": "参考图1" }, "role": "reference_image" },
            { "type": "image_url", "image_url": { "url": "参考图2" }, "role": "reference_image" },
            { "type": "video_url", "video_url": { "url": "参考视频" }, "role": "reference_video" },
            { "type": "audio_url", "audio_url": { "url": "参考音频" }, "role": "reference_audio" }
        ]
        """
        # 1. 解析 extra_config
        extra_config = self._parse_extra_config(ai_tool)

        # 2. 获取图片信息（首帧 + 尾帧 + 参考图）
        all_images_info = self.get_all_images_by_mode(ai_tool)
        first_frame = all_images_info.get('first_frame')
        last_frame = all_images_info.get('last_frame')
        reference_images = all_images_info.get('reference_images', [])

        # 3. 处理首帧图片（multi_reference 模式下可选）
        processed_first_frame = None
        if first_frame:
            success, processed_url, error = compress_and_upload_image_sync(
                first_frame,
                self._config,
                max_size_mb=10.0,
                is_local=True
            )
            if success:
                processed_first_frame = processed_url
            else:
                self.logger.error(f"处理首帧图片失败: {error}")
                return {
                    "success": False,
                    "error": f"处理首帧图片失败: {error}",
                    "error_type": "USER",
                    "retry": False
                }

        # 4. 处理尾帧图片（可选）
        processed_last_frame = None
        if last_frame:
            success, processed_url, error = compress_and_upload_image_sync(
                last_frame,
                self._config,
                max_size_mb=10.0,
                is_local=True
            )
            if success:
                processed_last_frame = processed_url
            else:
                self.logger.warning(f"处理尾帧图片失败，跳过: {error}")

        # 5. 处理参考图列表
        processed_reference_images = []
        for ref_img in reference_images:
            success, new_url, error = compress_and_upload_image_sync(
                ref_img,
                self._config,
                max_size_mb=10.0,
                is_local=True
            )
            if success:
                processed_reference_images.append(new_url)
            else:
                self.logger.warning(f"处理参考图失败，跳过: {error}")
                # 参考图失败不阻断流程，继续处理

        # 6. 构建 content 数组
        content = []

        # 文本部分（放在最前面）
        prompt = ai_tool.prompt or ""
        if prompt:
            content.append({
                "type": "text",
                "text": prompt
            })

        # 首帧图（role: "first_frame"，可选）
        if processed_first_frame:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": processed_first_frame
                },
                "role": "first_frame"
            })

        # 尾帧图（role: "last_frame"，可选）
        if processed_last_frame:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": processed_last_frame
                },
                "role": "last_frame"
            })

        # 参考图列表（role: "reference_image"）
        for ref_img_url in processed_reference_images:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": ref_img_url
                },
                "role": "reference_image"
            })

        # 参考视频（role: "reference_video"）
        reference_video = extra_config.get('reference_video')
        if reference_video:
            content.append({
                "type": "video_url",
                "video_url": {
                    "url": reference_video
                },
                "role": "reference_video"
            })

        # 参考音频（role: "reference_audio"）
        reference_audio = extra_config.get('reference_audio')
        if reference_audio:
            content.append({
                "type": "audio_url",
                "audio_url": {
                    "url": reference_audio
                },
                "role": "reference_audio"
            })

        # 6. 构建 payload
        payload = {
            "model": self._model,
            "content": content
        }

        # 添加可选参数
        if extra_config.get('generate_audio') is not None:
            payload["generate_audio"] = extra_config['generate_audio']

        if extra_config.get('watermark') is not None:
            payload["watermark"] = extra_config['watermark']

        if extra_config.get('ratio'):
            payload["ratio"] = extra_config['ratio']

        if ai_tool.duration:
            payload["duration"] = ai_tool.duration

        self.logger.info(f"使用模型: {self._model}, driver_type: {self.driver_type}, content 元素数: {len(content)}")

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
        super().__init__(driver_type=21, model_name="doubao-seedance-1-5-pro-251215")


class Seedance20FastVolcengineV1Driver(SeedanceVolcengineV1Driver):
    """Seedance 2.0 Fast 图生视频驱动"""

    def __init__(self):
        super().__init__(driver_type=22, model_name="doubao-seedance-2-0-fast-260128")


class Seedance20VolcengineV1Driver(SeedanceVolcengineV1Driver):
    """Seedance 2.0 图生视频驱动"""

    def __init__(self):
        super().__init__(driver_type=23, model_name="doubao-seedance-2-0-260128")
