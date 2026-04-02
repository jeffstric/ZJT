"""
Seedance 火山引擎供应商 v1 版本驱动实现
异步 API - 创建任务后轮询状态
支持 Seedance 1.5 Pro / 2.0 Fast / 2.0 三个模型（图生视频）

基类 SeedanceVolcengineV1Driver 包含核心逻辑，
子类通过 driver_type 和 model_name 区分不同模型。
"""
from typing import Dict, Any, Optional
import traceback
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

        content 数组格式: [text, image_url]
        """
        # 处理图片（必须传图片）
        if not ai_tool.image_path:
            raise ValueError("Seedance 图生视频需要至少1张图片")

        image_urls = [url.strip() for url in ai_tool.image_path.split(',') if url.strip()]

        if not image_urls:
            raise ValueError("Seedance 图生视频需要至少1张图片")

        # 压缩并上传图片
        processed_urls = []
        for img_url in image_urls:
            success, new_url, error = compress_and_upload_image_sync(
                img_url,
                self._config,
                max_size_mb=10.0,
                is_local=True
            )
            if success:
                processed_urls.append(new_url)
            else:
                self.logger.error(f"处理图片失败: {error}")
                return {
                    "success": False,
                    "error": f"处理图片失败: {error}",
                    "error_type": "USER",
                    "retry": False
                }

        # 构建提示词（内嵌 duration 等参数）
        prompt = ai_tool.prompt or ""
        duration = getattr(ai_tool, 'duration', None) or 5
        prompt_with_params = f"{prompt} --duration {duration}"

        # 构建 content 数组
        content = []

        # 文本部分
        if prompt_with_params:
            content.append({
                "type": "text",
                "text": prompt_with_params
            })

        # 图片部分（取第一张作为参考图）
        content.append({
            "type": "image_url",
            "image_url": {
                "url": processed_urls[0]
            }
        })

        self.logger.info(f"使用模型: {self._model}, driver_type: {self.driver_type}")

        payload = {
            "model": self._model,
            "content": content
        }

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
