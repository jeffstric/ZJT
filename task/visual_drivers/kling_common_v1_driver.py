"""
Kling 通用聚合站点 v1 版本驱动实现
支持多个站点配置，使用基类+站点类的架构
"""
from typing import Dict, Any, Optional
import traceback
from .base_video_driver import BaseVideoDriver, ImageMode
from config.config_util import get_config, get_dynamic_config_value
from utils.sentry_util import SentryUtil, AlertLevel
from utils.image_upload_utils import upload_local_images_to_cdn_sync


class KlingCommonV1Driver(BaseVideoDriver):
    """
    Kling 通用聚合站点 v1 版本驱动（基类）
    支持图生视频，使用 kling-v2-5-turbo 模型

    特点：
    - 支持多个站点配置（通过 site_id 区分）
    - 从 api_aggregator.{site_id} 加载配置
    - 接口与 kling_duomi_v1_driver 保持一致

    注意：这是基类，不应该直接实例化，应该使用具体的站点类
    """

    def __init__(self, site_id: str):
        """
        初始化驱动（基类）

        Args:
            site_id: API 聚合站点ID（如 site_0, site_1, ... site_5）
                     对应配置 api_aggregator.site_X
        """
        self._site_id = site_id
        driver_name = f"kling_common_{site_id}"
        super().__init__(driver_name=driver_name, driver_type=12)

        # 从 api_aggregator.{site_id} 加载配置
        self._api_key = get_dynamic_config_value("api_aggregator", site_id, "api_key", default="")
        self._base_url = get_dynamic_config_value("api_aggregator", site_id, "base_url", default="https://yunwu.ai")
        self._site_name = get_dynamic_config_value("api_aggregator", site_id, "name", default=site_id)
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        # 是否为本地环境
        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        self._validate_required({
            f"API Aggregator {site_id} API Key": self._api_key,
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
            "code": 0,
            "message": "success",
            "data": {
                "task_id": "task_123456789"
            }
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "code" not in result:
            return False, f"响应缺少 'code' 字段，实际字段: {list(result.keys())}"

        if result.get("code") != 0:
            return True, None  # code != 0 表示业务错误，格式仍然有效

        if "data" not in result:
            return False, f"响应缺少 'data' 字段，实际字段: {list(result.keys())}"

        data = result.get("data")
        if not isinstance(data, dict):
            return False, f"'data' 字段类型错误，期望 dict，实际: {type(data)}"

        if "task_id" not in data:
            return False, f"'data' 缺少 'task_id' 字段，实际字段: {list(data.keys())}"

        if not isinstance(data.get("task_id"), str):
            return False, f"'task_id' 字段类型错误，期望 str，实际: {type(data.get('task_id'))}"

        return True, None

    def _validate_status_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 check_status API 响应格式

        期望的正确响应格式:
        {
            "code": 0,
            "message": "success",
            "data": {
                "task_id": "task_123456789",
                "task_status": "succeed",
                "task_result": {
                    "videos": [{"id": "...", "url": "...", "duration": "5"}]
                }
            }
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "code" not in result:
            return False, f"响应缺少 'code' 字段，实际字段: {list(result.keys())}"

        if result.get("code") != 0:
            return True, None  # code != 0 表示业务错误，格式仍然有效

        if "data" not in result:
            return False, f"响应缺少 'data' 字段，实际字段: {list(result.keys())}"

        data = result.get("data")
        if not isinstance(data, dict):
            return False, f"'data' 字段类型错误，期望 dict，实际: {type(data)}"

        if "task_status" not in data:
            return False, f"'data' 缺少 'task_status' 字段，实际字段: {list(data.keys())}"

        task_status = data.get("task_status")
        if task_status == "succeed":
            if "task_result" not in data:
                return False, "任务成功但缺少 'task_result' 字段"

            task_result = data.get("task_result")
            if not isinstance(task_result, dict):
                return False, f"'task_result' 字段类型错误，期望 dict，实际: {type(task_result)}"

            if "videos" not in task_result:
                return False, "任务成功但 'task_result' 缺少 'videos' 字段"

            videos = task_result.get("videos")
            if not isinstance(videos, list) or len(videos) == 0:
                return False, "任务成功但 'videos' 为空或类型错误"

            if "url" not in videos[0]:
                return False, "视频对象缺少 'url' 字段"

        return True, None

    def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 Kling 任务的完整请求参数

        支持三种图片模式：
        - first_last_frame: 首尾帧模式（使用首帧图片）
        - multi_reference: 多参考图模式（使用第一张参考图）
        - first_last_with_ref: 首尾帧+参考图模式（仅使用首帧）
        """
        # 解析图片模式
        image_info = self.get_all_images_by_mode(ai_tool)
        img_mode = image_info['mode']
        first_frame = image_info['first_frame']
        last_frame = image_info['last_frame']
        reference_images = image_info['reference_images']

        self.logger.info(f"Kling 聚合站点({self._site_id}) 图片模式: {img_mode}, 首帧: {first_frame}, 参考图: {len(reference_images)}张")

        # 根据模式获取图片
        image_path = None
        if img_mode == ImageMode.FIRST_LAST_FRAME:
            # 首尾帧模式：使用首帧，支持尾帧
            image_path = first_frame
        elif img_mode == ImageMode.MULTI_REFERENCE:
            if reference_images:
                image_path = reference_images[0]
                if len(reference_images) > 1:
                    self.logger.warning(f"Kling 不支持多参考图模式，仅使用第一张参考图")
        elif img_mode == ImageMode.FIRST_LAST_WITH_REF:
            # 首尾帧+参考图模式：使用首帧和尾帧，忽略参考图
            image_path = first_frame

        if not image_path:
            raise ValueError("Kling 任务需要至少1张图片")

        # 处理图片路径 - 如果是本地环境，上传到图床
        if self._is_local:
            images_to_upload = [image_path]
            if last_frame:
                images_to_upload.append(last_frame)
            self.logger.info(f"本地环境检测到图片路径，准备上传到图床: {images_to_upload}")
            cdn_urls = upload_local_images_to_cdn_sync(images_to_upload, self._config)
            self.logger.info(f"图片上传完成，CDN链接: {cdn_urls}")
            if cdn_urls and cdn_urls[0]:
                image_path = cdn_urls[0]
                if last_frame and len(cdn_urls) > 1 and cdn_urls[1]:
                    last_frame = cdn_urls[1]

        # 根据是否存在尾帧，动态选择模式
        mode = "pro" if last_frame else "std"

        payload = {
            "model_name": "kling-v2-5-turbo",
            "image": image_path,
            "prompt": ai_tool.prompt,
            "mode": mode,
            "duration": ai_tool.duration or 5,
            "cfg_scale": 0.5
        }

        # 如果有尾帧，添加 image_tail 参数
        if last_frame:
            payload["image_tail"] = last_frame

        return {
            "url": f"{self._base_url}/kling/v1/videos/image2video",
            "method": "POST",
            "json": payload,
            "headers": {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json"
            }
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询 Kling 任务状态的完整请求参数
        """
        return {
            "url": f"{self._base_url}/kling/v1/videos/image2video/{project_id}",
            "method": "GET",
            "json": None,
            "headers": {
                "Authorization": f"Bearer {self._api_key}"
            }
        }

    def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 Kling 视频生成任务
        """
        try:
            self.logger.info(f"Submitting Kling {self._site_id} task: prompt='{ai_tool.prompt[:50]}...', duration={ai_tool.duration}")

            # 构建请求参数
            request_params = self.build_create_request(ai_tool)

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during Kling {self._site_id} task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(f"Kling {self._site_id} API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Kling {self._site_id} submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_kling_image2video",
                        "response": result,
                        "ai_tool_id": ai_tool.id,
                        "site_id": self._site_id
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
            if result.get("code") != 0:
                error_msg = result.get("message", "未知错误")
                self.logger.warning(f"Kling {self._site_id} API returned error: code={result.get('code')}, message={error_msg}")
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_msg}",
                    "error_type": "USER",
                    "retry": False
                }

            task_id = result.get("data", {}).get("task_id")
            if not task_id:
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "Kling API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": task_id
            }

        except Exception as e:
            self.logger.error(f"Unexpected exception in Kling {self._site_id} submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Kling {self._site_id} submit_task 发生未预期异常: {str(e)}",
                context={
                    "exception": str(e),
                    "traceback": traceback.format_exc(),
                    "ai_tool_id": ai_tool.id,
                    "site_id": self._site_id
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
        检查 Kling 任务状态
        """
        try:
            self.logger.info(f"Checking Kling {self._site_id} task status: project_id={project_id}")

            # 构建请求参数并调用统一请求方法
            request_params = self.build_check_query(project_id)

            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during Kling {self._site_id} status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            self.logger.info(f"Kling {self._site_id} status API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_status_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"Kling {self._site_id} check_status 响应格式错误: {validation_error}",
                    context={
                        "api": "get_kling_task_status",
                        "response": result,
                        "project_id": project_id,
                        "site_id": self._site_id
                    }
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {validation_error}"
                }

            # 检查业务错误
            if result.get("code") != 0:
                error_msg = result.get("message", "未知错误")
                self.logger.warning(f"Kling {self._site_id} status API returned error: code={result.get('code')}, message={error_msg}")
                return {
                    "status": "FAILED",
                    "error": f"查询任务状态失败: {error_msg}",
                    "error_type": "SYSTEM"
                }

            data = result.get("data", {})
            task_status = data.get("task_status", "")

            # 映射 Kling 状态到统一状态
            if task_status == "succeed":
                videos = data.get("task_result", {}).get("videos", [])
                if videos and len(videos) > 0:
                    result_url = videos[0].get("url")
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
            elif task_status == "failed":
                reason = data.get("fail_reason", "任务失败")
                return {
                    "status": "FAILED",
                    "error": reason,
                    "error_type": "USER"
                }
            else:
                # processing 或其他状态
                return {
                    "status": "RUNNING",
                    "message": "任务处理中..."
                }

        except Exception as e:
            self.logger.error(f"Unexpected exception in Kling {self._site_id} check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"Kling {self._site_id} check_status 发生未预期异常: {str(e)}",
                context={
                    "exception": str(e),
                    "traceback": traceback.format_exc(),
                    "project_id": project_id,
                    "site_id": self._site_id
                }
            )

            return {
                "status": "FAILED",
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}"
            }


# ============ 具体站点实现类 ============

class KlingCommonSite0V1Driver(KlingCommonV1Driver):
    """Kling 通用聚合 Site 0 v1 版本驱动

    智剧通API官方站点，对应配置 api_aggregator.site_0
    """

    def __init__(self):
        super().__init__(site_id="site_0")


class KlingCommonSite1V1Driver(KlingCommonV1Driver):
    """Kling 通用聚合 Site 1 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_1")


class KlingCommonSite2V1Driver(KlingCommonV1Driver):
    """Kling 通用聚合 Site 2 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_2")


class KlingCommonSite3V1Driver(KlingCommonV1Driver):
    """Kling 通用聚合 Site 3 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_3")


class KlingCommonSite4V1Driver(KlingCommonV1Driver):
    """Kling 通用聚合 Site 4 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_4")


class KlingCommonSite5V1Driver(KlingCommonV1Driver):
    """Kling 通用聚合 Site 5 v1 版本驱动"""

    def __init__(self):
        super().__init__(site_id="site_5")
