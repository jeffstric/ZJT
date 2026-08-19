"""
MiniMax H3 RunningHub v1 版本驱动实现

支持首尾帧图生视频，通过 RunningHub AI-App 接口调用「支持音频的 H3 图生视频」工作流。
webapp_id: 2086436470516174849

参数注入节点 nodeId：
  - 提示词      → nodeId 143 fieldName=text         (CR Text)
  - 首帧图片    → nodeId 114 fieldName=image        (LoadImage)
  - 尾帧图片    → nodeId 145 fieldName=image        (LoadImage，始终传，空则留空)
  - 分辨率      → nodeId 115 fieldName=megapixels   (ResolutionSelector，0.4/0.9)
  - 比例        → nodeId 115 fieldName=aspect_ratio (ResolutionSelector，带括号完整文本)
  - 时长(秒)    → nodeId 136 fieldName=value        (INTConstant)
"""
import json
from typing import Dict, Any, Optional, Tuple
import traceback
from .base_video_driver import BaseVideoDriver, ImageMode
from config.config_util import get_config, get_dynamic_config_value
from config.unified_config import TaskTypeId, VideoResolution
from config.constant import VIDEO_RESOLUTION_EXTRA_CONFIG_KEY, LEGACY_RESOLUTION_EXTRA_CONFIG_KEY
from utils.sentry_util import SentryUtil, AlertLevel
from utils.file_storage import RunningHubFileStorage
from utils.runninghub_error import is_upstream_congested_error
from .exceptions import ImageExpiredError


# 比例 → ResolutionSelector(nodeId=115) aspect_ratio COMBO 完整文本
RATIO_TO_ASPECT_RATIO_VALUE = {
    '1:1': '1:1 (Square)',
    '16:9': '16:9 (Widescreen)',
    '9:16': '9:16 (Portrait Widescreen)',
    '4:3': '4:3 (Standard)',
    '3:4': '3:4 (Portrait Standard)',
}

# 默认分辨率（megapixels），对应 720P
DEFAULT_MEGAPIXELS = VideoResolution.MINIMAX_H3_DRIVER_VALUES[VideoResolution.P720]

# aspect_ratio 节点的 fieldData（COMBO 元数据，按加速版工作流定义原样传入）
ASPECT_RATIO_FIELD_DATA = (
    '["COMBO", {"default": "1:1 (Square)", "options": '
    '["1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", '
    '"3:4 (Portrait Standard)", "4:3 (Standard)", '
    '"9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)"], '
    '"tooltip": "The aspect ratio for the output dimensions.", "multiselect": false}]'
)


class MinimaxH3RunninghubV1Driver(BaseVideoDriver):
    """
    MiniMax H3 RunningHub v1 版本驱动
    支持首尾帧图生视频
    """

    def __init__(self):
        super().__init__(driver_name="minimax_h3_runninghub_v1", driver_type=TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO)

        # 加载配置
        self._api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        self._host = get_dynamic_config_value("runninghub", "host", default="")
        # ⚠️ TODO: 此处需替换为「MiniMax H3 FL2VA开源版-图生视频-含尾帧.json」上传到 RunningHub 后的新 webapp_id
        # 当前值 2086058220979834882 是旧加速开源版工作流（音频有 BUG），上线前必须更新。
        self._webapp_id = "2086436470516174849"  # MiniMax H3 图生视频（支持音频）webapp ID
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
        """
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "taskId" not in result:
            return False, f"响应缺少 'taskId' 字段，实际字段: {list(result.keys())}"

        if "status" not in result:
            return False, f"响应缺少 'status' 字段，实际字段: {list(result.keys())}"

        return True, None

    def _ratio_to_aspect_ratio_value(self, ratio: str) -> str:
        """
        将视频比例映射为 RunningHub 工作流 aspect_ratio 节点的完整文本值

        Args:
            ratio: 视频比例，如 "9:16", "16:9"

        Returns:
            str: aspect_ratio 完整文本，如 "9:16 (Portrait Widescreen)"
        """
        return RATIO_TO_ASPECT_RATIO_VALUE.get(ratio, '9:16 (Portrait Widescreen)')  # 默认 9:16

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

    def _get_megapixels(self, extra_config: Dict[str, Any]) -> str:
        """
        从 extra_config 读取分辨率并映射为 ResolutionSelector 的 megapixels 值

        Args:
            extra_config: 解析后的额外配置字典

        Returns:
            str: megapixels 值（"0.4" / "0.9"），取不到时默认 720P（"0.9"）
        """
        resolution = (
            extra_config.get(VIDEO_RESOLUTION_EXTRA_CONFIG_KEY)
            or extra_config.get(LEGACY_RESOLUTION_EXTRA_CONFIG_KEY)
        )
        if not resolution:
            return DEFAULT_MEGAPIXELS
        return VideoResolution.MINIMAX_H3_DRIVER_VALUES.get(
            str(resolution).upper(), DEFAULT_MEGAPIXELS
        )

    async def _upload_image_to_runninghub(self, image_path: str, description: str) -> str:
        """
        上传图片到 RunningHub 图床并返回可用的 fieldValue

        Args:
            image_path: 图片路径（本地路径或 URL）
            description: 图片描述（用于日志）

        Returns:
            str: 上传后的图片标识（download_url 或 fileName）

        Raises:
            RuntimeError: 上传失败时抛出
        """
        self.logger.info(f"准备上传{description}到 RunningHub 图床: {image_path}")
        result = await self._storage.upload_file("", image_path)
        if result.success:
            uploaded_path = result.url if result.url else result.key
            self.logger.info(f"{description}上传完成，使用标识: {uploaded_path}")
            return uploaded_path
        else:
            raise RuntimeError(f"{description}上传到 RunningHub 失败: {result.error}")

    async def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 MiniMax H3 任务的完整请求参数

        支持首尾帧模式（节点映射）：
        - 提示词 → nodeId 143 (text，CR Text)
        - 首帧图片（必需）→ nodeId 114 (image，LoadImage)
        - 尾帧图片（可选）→ nodeId 145 (image，LoadImage，始终传，空则留空)
        - 分辨率 → nodeId 115 (megapixels)
        - 比例 → nodeId 115 (aspect_ratio，带括号完整文本)
        - 时长（秒）→ nodeId 136 (value，INTConstant)

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

        self.logger.info(
            f"MiniMax H3 驱动图片模式: {img_mode}, 首帧: {first_frame}, 尾帧: {last_frame}, 参考图: {len(reference_images)}张"
        )

        # 获取首帧图片
        first_image_path = None
        last_image_path = None

        if img_mode == ImageMode.FIRST_LAST_FRAME:
            first_image_path = first_frame
            last_image_path = last_frame  # 可能为 None
        elif img_mode == ImageMode.MULTI_REFERENCE:
            if reference_images:
                first_image_path = reference_images[0]
                if len(reference_images) >= 2:
                    last_image_path = reference_images[1]
                if len(reference_images) > 2:
                    self.logger.warning(f"MiniMax H3 最多支持首尾帧2张图，已忽略多余的参考图")
        elif img_mode == ImageMode.FIRST_LAST_WITH_REF:
            first_image_path = first_frame
            last_image_path = last_frame
            if reference_images:
                self.logger.warning(f"MiniMax H3 不支持首尾帧+参考图模式，已忽略参考图")

        if not first_image_path:
            raise ValueError("MiniMax H3 任务需要至少1张首帧图片")

        # 上传首帧图片到 RunningHub 图床
        first_frame_uploaded = await self._upload_image_to_runninghub(first_image_path, "首帧图片")

        # 上传尾帧图片（如果有）
        last_frame_uploaded = None
        if last_image_path:
            last_frame_uploaded = await self._upload_image_to_runninghub(last_image_path, "尾帧图片")

        # 获取时长
        duration = ai_tool.duration or 5

        # 获取比例并映射为 aspect_ratio 完整文本（带括号）
        ratio = ai_tool.ratio or '9:16'
        aspect_ratio_value = self._ratio_to_aspect_ratio_value(ratio)

        # 从 extra_config 解析分辨率并映射为 megapixels
        extra_config = self._parse_extra_config(ai_tool)
        megapixels_value = self._get_megapixels(extra_config)

        # 构建提示词：优先使用 pipeline 优化结果，原文已备份在 extra_config.original_prompt
        prompt_meta = extra_config.get("h3_prompt_optimize") if isinstance(extra_config, dict) else None
        if isinstance(prompt_meta, dict) and prompt_meta.get("optimized_prompt"):
            prompt_text = str(prompt_meta.get("optimized_prompt") or "")
        else:
            prompt_text = ai_tool.prompt or ""
        original_prompt = ""
        if isinstance(extra_config, dict):
            original_prompt = extra_config.get("original_prompt") or (
                prompt_meta.get("original_prompt") if isinstance(prompt_meta, dict) else ""
            ) or ""

        # 构建 nodeInfoList
        # - nodeId 143 text           提示词（CR Text）
        # - nodeId 114 image          首帧 LoadImage
        # - nodeId 145 image          尾帧 LoadImage（始终传，无尾帧时 fieldValue 留空，
        #                              否则 RunningHub 会用节点默认值作为尾帧）
        # - nodeId 115 megapixels     分辨率（0.4/0.9）
        # - nodeId 115 aspect_ratio   比例（带括号完整文本，带 fieldData）
        # - nodeId 136 value          时长（秒，INTConstant）
        node_info_list = [
            {
                "nodeId": "143",
                "fieldName": "text",
                "fieldValue": prompt_text,
                "description": "text"
            },
            {
                "nodeId": "114",
                "fieldName": "image",
                "fieldValue": first_frame_uploaded,
                "description": "image"
            },
            {
                "nodeId": "145",
                "fieldName": "image",
                "fieldValue": last_frame_uploaded or "",
                "description": "image"
            },
            {
                "nodeId": "115",
                "fieldName": "megapixels",
                "fieldValue": megapixels_value,
                "description": "megapixels"
            },
            {
                "nodeId": "115",
                "fieldName": "aspect_ratio",
                "fieldData": ASPECT_RATIO_FIELD_DATA,
                "fieldValue": aspect_ratio_value,
                "description": "aspect_ratio"
            },
            {
                "nodeId": "136",
                "fieldName": "value",
                "fieldValue": str(duration),
                "description": "value"
            }
        ]

        self.logger.info(
            f"MiniMax H3 请求参数: duration={duration}s, ratio={ratio}(aspect_ratio={aspect_ratio_value}), "
            f"megapixels={megapixels_value}, has_last_frame={last_frame_uploaded is not None}, "
            f"prompt_len={len(prompt_text)}, original_len={len(original_prompt or '')}, "
            f"variant={(prompt_meta or {}).get('variant') if isinstance(prompt_meta, dict) else None}, "
            f"fallback={(prompt_meta or {}).get('fallback') if isinstance(prompt_meta, dict) else None}"
        )

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
        构建查询 MiniMax H3 任务状态的完整请求参数

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
        提交 MiniMax H3 视频生成任务

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词
                - image_path: 图片路径（首帧，逗号分隔时可含尾帧）
                - duration: 视频时长（秒）
                - ratio: 视频比例

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(
                f"Submitting MiniMax H3 task: prompt='{ai_tool.prompt[:50] if ai_tool.prompt else ''}...', "
                f"duration={ai_tool.duration}"
            )

            # 构建请求参数
            request_params = await self.build_create_request(ai_tool)

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during MiniMax H3 task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True
                }

            self.logger.info(f"MiniMax H3 API response: {result}")

            # 验证响应格式
            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                # 格式错误，发送报警，不重试
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"MiniMax H3 submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_minimax_h3_image_to_video",
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
                # 上游并发超限/限流：自动延迟重试
                if is_upstream_congested_error(error_code):
                    self.logger.warning(
                        f"MiniMax H3 upstream congested, will auto-retry: "
                        f"errorCode={error_code}, errorMessage={error_message}"
                    )
                    return self._build_upstream_congested_result()
                self.logger.warning(
                    f"MiniMax H3 API returned error: errorCode={error_code}, errorMessage={error_message}"
                )
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
                    "error_detail": "MiniMax H3 API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": task_id
            }

        except ImageExpiredError as e:
            # 第三方图床签名过期，无法恢复：友好提示用户重新上传
            self.logger.warning(f"输入图片已过期: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "error_type": "USER",
                "retry": False
            }

        except Exception as e:
            # 非网络异常，发送报警，不重试
            self.logger.error(f"Unexpected exception in MiniMax H3 submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"MiniMax H3 submit_task 发生未预期异常: {str(e)}",
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
        检查 MiniMax H3 任务状态

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking MiniMax H3 task status: project_id={project_id}")

            # 第一次调用：查询状态
            status_params = self.build_check_query(project_id)

            try:
                status_result = self._request(**status_params)
            except (ConnectionError, TimeoutError) as network_error:
                # 网络异常，允许重试
                self.logger.warning(f"Network error during MiniMax H3 status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            # 验证状态响应格式
            if not isinstance(status_result, dict) or "code" not in status_result:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="MiniMax H3 status API 响应格式异常",
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
            self.logger.error(f"Unexpected exception in MiniMax H3 check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"MiniMax H3 check_status 发生未预期异常: {str(e)}",
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
