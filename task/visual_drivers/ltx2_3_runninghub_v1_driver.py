"""
LTX2.3 RunningHub v1 版本驱动实现
"""
from typing import Dict, Any, Optional, Tuple
import traceback
from PIL import Image
from .base_video_driver import BaseVideoDriver, ImageMode
from config.config_util import get_config, get_dynamic_config_value
from utils.sentry_util import SentryUtil, AlertLevel
from utils.file_storage import RunningHubFileStorage
from utils.image_upload_utils import resolve_url_to_local_file_sync


class Ltx2Dot3RunninghubV1Driver(BaseVideoDriver):
    """
    LTX2.3 RunningHub v1 版本驱动
    支持图生视频
    """

    def __init__(self):
        super().__init__(driver_name="ltx2.3_runninghub_v1", driver_type=10)

        # 加载配置
        self._api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        self._host = get_dynamic_config_value("runninghub", "host", default="")
        self._webapp_id = "2038246514870460418"  # LTX2.3 webapp ID
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

        Args:
            result: API 响应结果

        Returns:
            tuple[bool, Optional[str]]: (是否有效, 错误信息)

        期望的正确响应格式:
        {
            "taskId": "2019324151986266113",
            "status": "RUNNING",
            "errorCode": "",
            "errorMessage": "",
            ...
        }
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "taskId" not in result:
            return False, f"响应缺少 'taskId' 字段，实际字段: {list(result.keys())}"

        if "status" not in result:
            return False, f"响应缺少 'status' 字段，实际字段: {list(result.keys())}"

        return True, None

    def _get_image_dimensions(self, image_path: str) -> Tuple[int, int]:
        """
        获取图片的宽高尺寸

        Args:
            image_path: 图片路径（本地路径或 URL）

        Returns:
            Tuple[int, int]: (宽度, 高度)
        """
        try:
            # 解析 URL 或本地路径为本地文件路径
            local_path = resolve_url_to_local_file_sync(image_path, self._config)
            if not local_path:
                self.logger.warning(f"无法解析图片路径为本地文件: {image_path}")
                return 1280, 720

            # 读取图片尺寸
            img = Image.open(local_path)
            width, height = img.size
            img.close()
            return width, height
        except Exception as e:
            self.logger.warning(f"获取图片尺寸失败: {image_path}, error: {str(e)}")
            # 返回默认尺寸
            return 1280, 720

    def _calculate_frame_count(self, duration: int) -> int:
        """
        计算视频帧数（一定要8的倍数+1）

        Args:
            duration: 视频时长（秒）

        Returns:
            int: 符合要求的帧数
        """
        # LTX2.3 要求帧数为 8 的倍数 + 1
        # 基础帧率约 24fps，时长 5 秒约 120 帧，调整为 8 的倍数 + 1
        base_frames = duration * 24
        # 找到最接近的 8 的倍数 + 1
        frame_count = ((base_frames - 1) // 8) * 8 + 1
        # 确保至少是 9 帧（最小有效值）
        return max(frame_count, 9)

    async def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 LTX2.3 任务的完整请求参数

        支持三种图片模式：
        - first_last_frame: 首尾帧模式（使用首帧图片）
        - multi_reference: 多参考图模式（暂不支持，使用第一张参考图）
        - first_last_with_ref: 首尾帧+参考图模式（暂不支持，使用第一张参考图）

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # 解析图片模式
        image_info = self.get_all_images_by_mode(ai_tool)
        img_mode = image_info['mode']
        first_frame = image_info['first_frame']
        last_frame = image_info['last_frame']
        reference_images = image_info['reference_images']

        self.logger.info(f"LTX2.3 驱动图片模式: {img_mode}, 首帧: {first_frame}, 尾帧: {last_frame}, 参考图: {len(reference_images)}张")

        # 根据模式获取图片
        image_path = None
        if img_mode == ImageMode.FIRST_LAST_FRAME:
            image_path = first_frame
            if last_frame:
                self.logger.warning(f"LTX2.3 当前仅支持单图，已忽略尾帧")
        elif img_mode == ImageMode.MULTI_REFERENCE:
            if reference_images:
                image_path = reference_images[0]
                if len(reference_images) > 1:
                    self.logger.warning(f"LTX2.3 不支持多参考图模式，仅使用第一张参考图")
        elif img_mode == ImageMode.FIRST_LAST_WITH_REF:
            if reference_images:
                image_path = reference_images[0]
                if last_frame:
                    self.logger.warning(f"LTX2.3 不支持首尾帧+参考图模式，已忽略尾帧")

        if not image_path:
            raise ValueError("LTX2.3 任务需要至少1张图片")

        # 获取图片尺寸（在上传前获取本地路径的图片尺寸）
        img_width, img_height = self._get_image_dimensions(image_path)

        # 计算视频尺寸：最长边限制在 640，等比例缩放
        max_dimension = max(img_width, img_height)
        if max_dimension > 640:
            scale = 640 / max_dimension
            video_width = int(img_width * scale)
            video_height = int(img_height * scale)
        else:
            video_width = img_width
            video_height = img_height

        self.logger.info(f"图片尺寸: {img_width}x{img_height}, 视频尺寸: {video_width}x{video_height}")

        # 处理图片路径 - 如果是本地环境，上传到 RunningHub
        if self._is_local and image_path:
            self.logger.info(f"本地环境检测到图片路径，准备上传到 RunningHub: {image_path}")
            result = await self._storage.upload_file("", image_path)
            if result.success:
                image_path = result.key
                self.logger.info(f"图片上传完成，使用 fileName: {image_path}")
            else:
                self.logger.warning(f"图片上传失败: {result.error}")

        # 计算帧数（8的倍数+1）
        duration = ai_tool.duration or 5
        frame_count = self._calculate_frame_count(duration)

        # 构建提示词
        prompt_text = ai_tool.prompt or ""
        if last_frame and img_mode == ImageMode.FIRST_LAST_FRAME:
            # 如果有尾帧，添加到提示词中
            prompt_text = f"{prompt_text}".strip()

        # Build node info list for LTX2.3
        node_info_list = [
            {
                "nodeId": "5018",
                "fieldName": "value",
                "fieldValue": str(video_width),
                "description": "视频宽的一半"
            },
            {
                "nodeId": "5020",
                "fieldName": "value",
                "fieldValue": str(video_height),
                "description": "视频高的一半"
            },
            {
                "nodeId": "5022",
                "fieldName": "value",
                "fieldValue": str(frame_count),
                "description": "视频帧数（一定要8的倍数+1）"
            },
            {
                "nodeId": "5013",
                "fieldName": "text",
                "fieldValue": prompt_text,
                "description": "提示词"
            },
            {
                "nodeId": "2004",
                "fieldName": "image",
                "fieldValue": image_path,
                "description": "首帧图"
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
        构建查询 LTX2.3 任务状态的完整请求参数

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
        提交 LTX2.3 视频生成任务

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词
                - image_path: 图片路径
                - duration: 视频时长 (5, 8, 10)

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(f"Submitting LTX2.3 task: prompt='{ai_tool.prompt[:50] if ai_tool.prompt else ''}...', duration={ai_tool.duration}")

            # 构建请求参数
            request_params = await self.build_create_request(ai_tool)

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during LTX2.3 task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(f"LTX2.3 API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                # 格式错误，发送报警，不重试
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"LTX2.3 submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_ltx2.3_image_to_video",
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

            # 检查业务错误（通过 errorCode 或 errorMessage 判断）
            error_code = result.get("errorCode", "")
            error_message = result.get("errorMessage", "")
            if error_code or error_message:
                self.logger.warning(f"LTX2.3 API returned error: errorCode={error_code}, errorMessage={error_message}")
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
                    "error_detail": "LTX2.3 API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": task_id
            }

        except Exception as e:
            # 非网络异常，发送报警，不重试
            self.logger.error(f"Unexpected exception in LTX2.3 submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"LTX2.3 submit_task 发生未预期异常: {str(e)}",
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
        检查 LTX2.3 任务状态

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking LTX2.3 task status: project_id={project_id}")

            # 第一次调用：查询状态
            status_params = self.build_check_query(project_id)

            try:
                status_result = self._request(**status_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during LTX2.3 status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            # 验证状态响应格式: {"code": 0, "data": "SUCCESS/RUNNING/FAILED"}
            if not isinstance(status_result, dict) or "code" not in status_result:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="LTX2.3 status API 响应格式异常",
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

            # 映射 RunningHub 状态到统一状态
            if task_status == "SUCCESS":
                # 第二次调用：获取输出结果
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

                # 从 outputs 中提取视频 URL
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
            # 非网络异常，发送报警
            self.logger.error(f"Unexpected exception in LTX2.3 check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"LTX2.3 check_status 发生未预期异常: {str(e)}",
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
