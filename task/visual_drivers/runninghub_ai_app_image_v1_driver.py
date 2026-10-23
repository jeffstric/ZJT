"""
RunningHub AI App 图片 v1 版本驱动实现

对接 RunningHub ai-app 工作流（默认 app id 2113539132868874242），
同一工作流同时支持两种模式：
- 图片编辑：nodeId 17-22 传入 1-6 张图（不足补 "None"，工作流节点 16
  easy makeImageList 的 skip_empty=true 会自动忽略 None），并开启
  「原图无偏移」（nodeId 25）与「使用图片尺寸」（nodeId 29）跟随图 1。
- 文生图：图片槽全填 "None"，关闭节点 25/29（文档要求文生图必须关闭，
  否则画面偏移或报错），通过节点 28 显式指定 aspect_ratio + megapixels。
"""
import json
from typing import Dict, Any, List, Optional
import traceback

from .base_video_driver import BaseVideoDriver
from config.config_util import get_config, get_dynamic_config_value
from utils.sentry_util import SentryUtil, AlertLevel
from utils.file_storage import RunningHubFileStorage
from utils.runninghub_error import is_upstream_congested_error
from .exceptions import ImageExpiredError


class RunninghubAiAppImageV1Driver(BaseVideoDriver):
    """RunningHub AI App 图片驱动（图片编辑 + 文生图）"""

    # 工作流固定 app id；可通过动态配置 runninghub.ai_app_image_webapp_id 覆盖
    DEFAULT_WEBAPP_ID = "2113539132868874242"

    # ai_tool.ratio（"1:1" 等标准比例）→ 工作流节点 28 的 aspect_ratio 枚举值
    ASPECT_RATIO_MAPPING = {
        '1:1': '1:1 (Square)',
        '2:3': '2:3 (Portrait Photo)',
        '3:2': '3:2 (Photo)',
        '3:4': '3:4 (Portrait Standard)',
        '4:3': '4:3 (Standard)',
        '9:16': '9:16 (Portrait Widescreen)',
        '16:9': '16:9 (Widescreen)',
        '21:9': '21:9 (Ultrawide)',
    }

    # 工作流图片槽位（nodeId 17-22），最多 6 张参考图
    IMAGE_NODE_IDS = ['17', '18', '19', '20', '21', '22']

    def __init__(self):
        super().__init__(driver_name="runninghub_ai_app_image_v1", driver_type=52)

        # 加载配置
        self._api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        self._host = get_dynamic_config_value("runninghub", "host", default="")
        self._webapp_id = get_dynamic_config_value(
            "runninghub", "ai_app_image_webapp_id", default=self.DEFAULT_WEBAPP_ID
        )
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

    def _map_aspect_ratio(self, ratio: str) -> str:
        """标准比例 → 工作流 aspect_ratio 枚举值，未知比例回落 1:1"""
        key = (ratio or '1:1').strip()
        mapped = self.ASPECT_RATIO_MAPPING.get(key)
        if not mapped:
            self.logger.warning(f"未知的图片比例 '{ratio}'，使用默认比例 1:1")
            mapped = self.ASPECT_RATIO_MAPPING['1:1']
        return mapped

    @staticmethod
    def _map_megapixels(image_size: str) -> str:
        """分辨率档位（1K/2K/4K）→ 工作流节点 28 的 megapixels（百万像素值）"""
        size = (image_size or '').strip().upper()
        if size.endswith('K'):
            size = size[:-1]
        try:
            mp = int(size)
        except (TypeError, ValueError):
            return '2'
        # 限制在 1-4 百万像素范围内
        return str(min(max(mp, 1), 4))

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 submit_task API 响应格式

        期望的正确响应格式:
        {
            "taskId": "2113539...",
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
        构建创建 AI App 图片任务的完整请求参数

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词（编辑模式为修改指令，文生图为完整画面描述）
                - image_path: 参考图 URL（逗号分隔，可为空 = 文生图模式）
                - ratio: 图片比例（文生图模式生效，编辑模式跟随图 1 尺寸）
                - image_size: 分辨率档位 1K/2K/4K（文生图模式生效）

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # 参考图列表（可选，最多 6 张）
        image_urls: List[str] = []
        if ai_tool.image_path:
            image_urls = [u.strip() for u in str(ai_tool.image_path).split(',') if u.strip()]
        image_urls = image_urls[:len(self.IMAGE_NODE_IDS)]

        # 上传图片到 RunningHub 图床（fieldValue 需要 RunningHub 图床路径）
        image_field_values: List[str] = []
        if image_urls:
            self.logger.info(f"准备上传 {len(image_urls)} 张图片到 RunningHub 图床")
            uploaded = []
            for url in image_urls:
                result = await self._storage.upload_file("", url)
                if result.success:
                    uploaded.append(result.url if result.url else result.key)
                else:
                    # 上传失败直接报错，不再静默用原始过期 URL 导致下游 401 假象
                    raise RuntimeError(f"图片上传到 RunningHub 失败: {result.error}")
            image_field_values = uploaded

        has_image = bool(image_field_values)

        node_info_list = []

        # 图片槽位：nodeId 17-22，无图填 "None"（工作流 skip_empty 自动忽略）
        for idx, node_id in enumerate(self.IMAGE_NODE_IDS):
            node_info_list.append({
                "nodeId": node_id,
                "fieldName": "image",
                "fieldValue": image_field_values[idx] if idx < len(image_field_values) else "None",
                "description": f"图{idx + 1}（文生图时不填）"
            })

        # 提示词
        node_info_list.append({
            "nodeId": "23",
            "fieldName": "value",
            "fieldValue": ai_tool.prompt or "",
            "description": "提示词"
        })

        # 使用反推（本地大模型润色提示词）：固定关闭
        node_info_list.append({
            "nodeId": "24",
            "fieldName": "value",
            "fieldValue": "false",
            "description": "使用反推"
        })

        # 原图无偏移：编辑模式开启；文生图必须关闭（否则画面偏移或报错）
        node_info_list.append({
            "nodeId": "25",
            "fieldName": "value",
            "fieldValue": "true" if has_image else "false",
            "description": "原图无偏移（文生图需关闭）"
        })

        if has_image:
            # 使用图片尺寸：编辑模式跟随图 1 尺寸，忽略节点 28
            node_info_list.append({
                "nodeId": "29",
                "fieldName": "value",
                "fieldValue": "true",
                "description": "使用图片尺寸"
            })
        else:
            # 使用图片尺寸关闭，显式指定比例 + 百万像素
            node_info_list.append({
                "nodeId": "29",
                "fieldName": "value",
                "fieldValue": "false",
                "description": "使用图片尺寸（文生图需关闭）"
            })
            node_info_list.append({
                "nodeId": "28",
                "fieldName": "aspect_ratio",
                "fieldValue": self._map_aspect_ratio(getattr(ai_tool, 'ratio', None)),
                "description": "图片比例"
            })
            node_info_list.append({
                "nodeId": "28",
                "fieldName": "megapixels",
                "fieldValue": self._map_megapixels(getattr(ai_tool, 'image_size', None)),
                "description": "自定义尺寸 多少 100万像素"
            })

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
        提交 AI App 图片任务（图片编辑 / 文生图）

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            mode = "image_edit" if ai_tool.image_path else "text_to_image"
            self.logger.info(f"Submitting RunningHubAiAppImage task: ai_tool_id={ai_tool.id}, mode={mode}")

            # 构建请求参数
            request_params = await self.build_create_request(ai_tool)

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during RunningHubAiAppImage task submission: {str(network_error)}")
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
                    message=f"RunningHubAiAppImage submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "run_ai_app_image",
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
                # 上游并发超限/限流(api queue limit reached / TASK_QUEUE_MAXED 等)：自动延迟重试，不直接判失败
                if is_upstream_congested_error(error_code):
                    self.logger.warning(
                        f"RunningHubAiAppImage upstream congested, will auto-retry: "
                        f"errorCode={error_code}, errorMessage={error_message}"
                    )
                    return self._build_upstream_congested_result()
                self.logger.warning(
                    f"RunningHubAiAppImage API returned error: errorCode={error_code}, errorMessage={error_message}"
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
                    "error_detail": "RunningHubAiAppImage API未返回任务ID",
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
            self.logger.error(f"Unexpected exception in RunningHubAiAppImage submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"RunningHubAiAppImage submit_task 发生未预期异常: {str(e)}",
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
        检查 AI App 图片任务状态

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking RunningHubAiAppImage task status: project_id={project_id}")

            # 查询状态
            status_params = self.build_check_query(project_id)

            try:
                status_result = self._request(**status_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during RunningHubAiAppImage status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            # 验证状态响应格式
            if not isinstance(status_result, dict) or "code" not in status_result:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="RunningHubAiAppImage status API 响应格式异常",
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
            self.logger.error(f"Unexpected exception in RunningHubAiAppImage check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"RunningHubAiAppImage check_status 发生未预期异常: {str(e)}",
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
