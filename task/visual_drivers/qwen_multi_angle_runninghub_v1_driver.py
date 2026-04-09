"""
Qwen Multi-Angle RunningHub v1 版本驱动实现
支持多角度图片编辑（水平角度、垂直角度、缩放）
"""
import json
from typing import Dict, Any, Optional, Tuple
import traceback
import requests
from PIL import Image
from io import BytesIO
from .base_video_driver import BaseVideoDriver
from config.config_util import get_config, get_dynamic_config_value
from utils.sentry_util import SentryUtil, AlertLevel
from utils.file_storage import RunningHubFileStorage


class QwenMultiAngleRunninghubV1Driver(BaseVideoDriver):
    """
    Qwen Multi-Angle RunningHub v1 版本驱动
    支持多角度图片编辑
    """

    def __init__(self):
        super().__init__(driver_name="qwen_multi_angle_runninghub_v1", driver_type=24)

        # 加载配置
        self._api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        self._host = get_dynamic_config_value("runninghub", "host", default="")
        self._webapp_id = "2040768307833348098"
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        # 是否为本地环境
        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        # 初始化 RunningHub 文件存储
        self._storage = RunningHubFileStorage(
            host=self._host,
            api_key=self._api_key,
            config=self._config,
            logger=self.logger
        )

        self._validate_required({
            "RunningHub API Key": self._api_key,
            "RunningHub Host": self._host,
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

    def _get_image_dimensions_from_url(self, image_url: str) -> Optional[Tuple[int, int]]:
        """从 URL 获取图片的实际宽高"""
        try:
            response = requests.get(image_url, timeout=10, stream=True)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))
            return img.size  # (width, height)
        except Exception as e:
            self.logger.warning(f"无法获取图片尺寸: {e}")
            return None

    def _scale_dimensions(self, width: int, height: int, max_dim: int = 1920) -> Tuple[int, int]:
        """按比例缩放尺寸，使最大边不超过 max_dim"""
        if width <= max_dim and height <= max_dim:
            return width, height
        scale = max_dim / max(width, height)
        new_width = int(width * scale)
        new_height = int(height * scale)
        # 确保是偶数（某些模型要求）
        new_width = new_width if new_width % 2 == 0 else new_width - 1
        new_height = new_height if new_height % 2 == 0 else new_height - 1
        return new_width, new_height

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 submit_task API 响应格式

        期望的正确响应格式:
        {
            "taskId": "2019324151986266113",
            "status": "RUNNING",
            "errorCode": "",
            "errorMessage": "",
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "taskId" not in result:
            return False, f"响应缺少 'taskId' 字段，实际字段: {list(result.keys())}"

        if "status" not in result:
            return False, f"响应缺少 'status' 字段，实际字段: {list(result.keys())}"

        return True, None

    async def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建多角度图片编辑任务的完整请求参数

        Args:
            ai_tool: AITool 对象
                - image_path: 输入图片路径
                - extra_config: JSON，包含 horizontal_angle, vertical_angle, zoom, width, height

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # 获取图片路径
        image_path = ai_tool.image_path
        if not image_path:
            raise ValueError("多角度图片编辑任务需要输入图片")

        # 上传图片到 RunningHub 图床
        self.logger.info(f"准备上传图片到 RunningHub 图床: {image_path}")
        result = await self._storage.upload_file("", image_path)
        if result.success:
            image_path = result.url if result.url else result.key
            self.logger.info(f"图片上传完成，使用路径: {image_path}")
        else:
            self.logger.warning(f"图片上传失败: {result.error}")

        # 解析 extra_config 参数
        extra = self._parse_extra_config(ai_tool)
        horizontal_angle = str(extra.get('horizontal_angle', 0))
        vertical_angle = str(extra.get('vertical_angle', 0))
        zoom = str(extra.get('zoom', 5.0))

        # 获取 width/height：优先从 extra_config，否则尝试从图片获取，最后使用默认值
        width = extra.get('width')
        height = extra.get('height')

        if not width or not height:
            # 尝试从图片 URL 获取实际尺寸
            img_dims = self._get_image_dimensions_from_url(image_path)
            if img_dims:
                width = width or img_dims[0]
                height = height or img_dims[1]
                self.logger.info(f"从图片获取到尺寸: {width}x{height}")

        # 使用默认值
        width = width or 1408
        height = height or 768

        # 自动缩放：最大边不超过 1920
        width, height = self._scale_dimensions(int(width), int(height), max_dim=1920)

        self.logger.info(f"多角度参数: horizontal_angle={horizontal_angle}, vertical_angle={vertical_angle}, "
                         f"zoom={zoom}, width={width}, height={height}")

        width = str(width)
        height = str(height)

        # Build node info list
        node_info_list = [
            {
                "nodeId": "10",
                "fieldName": "image",
                "fieldValue": image_path,
                "description": "image"
            },
            {
                "nodeId": "26",
                "fieldName": "height",
                "fieldValue": height,
                "description": "height"
            },
            {
                "nodeId": "26",
                "fieldName": "width",
                "fieldValue": width,
                "description": "width"
            },
            {
                "nodeId": "15",
                "fieldName": "horizontal_angle",
                "fieldValue": horizontal_angle,
                "description": "horizontal_angle 0~360"
            },
            {
                "nodeId": "15",
                "fieldName": "vertical_angle",
                "fieldValue": vertical_angle,
                "description": "vertical_angle -30~60"
            },
            {
                "nodeId": "15",
                "fieldName": "zoom",
                "fieldValue": zoom,
                "description": "zoom 0-10"
            }
        ]

        return {
            "url": f"{self._host}/openapi/v2/run/ai-app/{self._webapp_id}",
            "method": "POST",
            "json": {
                "nodeInfoList": node_info_list,
                "instanceType": "default",
                "usePersonalQueue": "false"
            },
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            }
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询任务状态的完整请求参数

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        return {
            "url": f"{self._host}/task/openapi/status",
            "method": "POST",
            "json": {
                "apiKey": self._api_key,
                "taskId": project_id
            },
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
        }

    async def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交多角度图片编辑任务

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(f"Submitting QwenMultiAngle task: ai_tool_id={ai_tool.id}")

            # 构建请求参数
            request_params = await self.build_create_request(ai_tool)

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during QwenMultiAngle task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"QwenMultiAngle submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_qwen_multi_angle",
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
            error_code = result.get("errorCode", "")
            error_message = result.get("errorMessage", "")
            if error_code or error_message:
                self.logger.warning(f"QwenMultiAngle API returned error: errorCode={error_code}, errorMessage={error_message}")
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_message or error_code}",
                    "error_type": "USER",
                    "retry": False
                }

            task_id = result.get("taskId")
            if not task_id:
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "QwenMultiAngle API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": task_id
            }

        except Exception as e:
            self.logger.error(f"Unexpected exception in QwenMultiAngle submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"QwenMultiAngle submit_task 发生未预期异常: {str(e)}",
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
        检查多角度图片编辑任务状态

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking QwenMultiAngle task status: project_id={project_id}")

            # 查询状态
            status_params = self.build_check_query(project_id)

            try:
                status_result = self._request(**status_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during QwenMultiAngle status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            # 验证状态响应格式
            if not isinstance(status_result, dict) or "code" not in status_result:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="QwenMultiAngle status API 响应格式异常",
                    context={
                        "api": "check_status",
                        "response": status_result,
                        "project_id": project_id
                    }
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "RunningHub 响应格式错误"
                }

            if status_result.get("code") != 0:
                error_msg = status_result.get("msg", "查询状态失败")
                return {
                    "status": "FAILED",
                    "error": error_msg,
                    "error_type": "USER"
                }

            task_status = status_result.get("data", "")

            # 映射状态
            if task_status == "SUCCESS":
                # 获取输出结果
                outputs_params = {
                    "url": f"{self._host}/task/openapi/outputs",
                    "method": "POST",
                    "json": {
                        "apiKey": self._api_key,
                        "taskId": project_id
                    },
                    "headers": {
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    }
                }

                try:
                    outputs_result = self._request(**outputs_params)
                except Exception as e:
                    self.logger.error(f"Failed to get outputs: {str(e)}")
                    return {
                        "status": "FAILED",
                        "error": "获取结果失败",
                        "error_type": "SYSTEM",
                        "error_detail": f"获取输出失败: {str(e)}"
                    }

                # 从 outputs 中提取文件 URL
                result_url = None
                if outputs_result.get("code") == 0:
                    outputs_data = outputs_result.get("data", [])
                    if outputs_data:
                        for item in outputs_data:
                            file_url = item.get("fileUrl")
                            if file_url:
                                result_url = file_url
                                break

                return {
                    "status": "SUCCESS",
                    "result_url": result_url
                }
            elif task_status == "FAILED":
                return {
                    "status": "FAILED",
                    "error": "任务失败",
                    "error_type": "USER"
                }
            else:
                # PENDING, RUNNING 或其他状态
                return {
                    "status": "RUNNING",
                    "message": "任务处理中..."
                }

        except Exception as e:
            self.logger.error(f"Unexpected exception in QwenMultiAngle check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"QwenMultiAngle check_status 发生未预期异常: {str(e)}",
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
