"""
moss 文生图驱动（实现类 RunninghubAiAppMossV1Driver）。

用户可见模型名是 moss，任务常量是 TaskTypeId.MOSS_IMAGE。
本文件只是 RunningHub 实现方，不作为模型标识。
对接 RunningHub OpenAPI v2 AI App 工作流（默认 app id 2112932052181016578）：

- 提交：POST /openapi/v2/run/ai-app/{webapp_id}（Bearer 认证），返回 taskId。
- 查询：POST /openapi/v2/query（Bearer 认证），SUCCESS 时 results[].url
  即产物图片链接（24 小时有效，调度层负责转存）。

节点映射（nodeInfoList）：
- nodeId 8  aspect_ratio    画面比例（8 种枚举）
- nodeId 8  megapixels      图片倍率（百万像素，默认 2 → 1088x1920 @9:16）
- nodeId 1  text            提示词
- nodeId 13 steps           步数（固定 25）
- nodeId 18 strength_model  Lora 权重（固定 1）

仅支持文生图：模型配置主分类即 TEXT_TO_IMAGE、categories 留空，前端图片
编辑列表不会出现；驱动对带参考图的提交直接拒绝，不静默忽略。
不支持宫格生图（supports_grid_image=False）。
"""
import json
import traceback
from typing import Dict, Any, Optional

from .base_video_driver import BaseVideoDriver
from config.config_util import get_dynamic_config_value
from utils.sentry_util import SentryUtil, AlertLevel
from utils.runninghub_error import is_upstream_congested_error


class RunninghubAiAppMossV1Driver(BaseVideoDriver):
    """moss 文生图驱动（仅文生图，RunningHub OpenAPI v2 AI App）"""

    # 工作流固定 app id；可通过动态配置 runninghub.ai_app_moss_webapp_id 覆盖
    DEFAULT_WEBAPP_ID = "2112932052181016578"

    # ai_tool.ratio（"1:1" 等标准比例）→ 工作流节点 8 的 aspect_ratio 枚举值
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

    # 工作流固定参数：采样步数与 Lora 权重
    DEFAULT_STEPS = '25'
    DEFAULT_STRENGTH_MODEL = '1'

    def __init__(self):
        super().__init__(driver_name="runninghub_ai_app_moss_v1", driver_type=53)

        # 加载配置
        self._api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        self._host = get_dynamic_config_value("runninghub", "host", default="")
        self._webapp_id = get_dynamic_config_value(
            "runninghub", "ai_app_moss_webapp_id", default=self.DEFAULT_WEBAPP_ID
        )
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

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

    def _map_aspect_ratio(self, ratio: str) -> str:
        """标准比例 → 工作流 aspect_ratio 枚举值，未知比例回落 9:16（上游默认）"""
        key = (ratio or '9:16').strip()
        mapped = self.ASPECT_RATIO_MAPPING.get(key)
        if not mapped:
            self.logger.warning(f"未知的图片比例 '{ratio}'，使用默认比例 9:16")
            mapped = self.ASPECT_RATIO_MAPPING['9:16']
        return mapped

    @staticmethod
    def _map_megapixels(image_size: str) -> str:
        """分辨率档位（1K/2K/4K）→ 工作流节点 8 的 megapixels（百万像素值）"""
        size = (image_size or '').strip().upper()
        if size.endswith('K'):
            size = size[:-1]
        try:
            mp = int(size)
        except (TypeError, ValueError):
            return '2'
        # 限制在 1-4 百万像素范围内
        return str(min(max(mp, 1), 4))

    def _auth_headers(self) -> Dict[str, str]:
        """v2 接口统一 Bearer 认证头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}"
        }

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        """
        验证 submit_task API 响应格式

        期望的正确响应格式:
        {
            "taskId": "2112932...",
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
        构建创建 moss 文生图任务的完整请求参数

        Args:
            ai_tool: AITool 对象
                - prompt: 提示词（完整画面描述）
                - image_path: 本驱动不支持参考图，非空直接拒绝
                - ratio: 图片比例（写入节点 8）
                - image_size: 分辨率档位 1K/2K/4K（写入节点 8 megapixels）

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        # 仅支持文生图：带参考图的提交直接拒绝，不静默忽略（避免用户误以为参考图生效）
        if ai_tool.image_path:
            raise ValueError("moss 模型仅支持文生图，不支持参考图")

        node_info_list = [
            {
                "nodeId": "8",
                "fieldName": "aspect_ratio",
                "fieldValue": self._map_aspect_ratio(getattr(ai_tool, 'ratio', None)),
                "description": "画面比例"
            },
            {
                "nodeId": "8",
                "fieldName": "megapixels",
                "fieldValue": self._map_megapixels(getattr(ai_tool, 'image_size', None)),
                "description": "图片倍率（百万像素）"
            },
            {
                "nodeId": "1",
                "fieldName": "text",
                "fieldValue": ai_tool.prompt or "",
                "description": "提示词"
            },
            {
                "nodeId": "13",
                "fieldName": "steps",
                "fieldValue": self.DEFAULT_STEPS,
                "description": "步数"
            },
            {
                "nodeId": "18",
                "fieldName": "strength_model",
                "fieldValue": self.DEFAULT_STRENGTH_MODEL,
                "description": "Lora权重"
            },
        ]

        return {
            "url": f"{self._host}/openapi/v2/run/ai-app/{self._webapp_id}",
            "method": "POST",
            "json": {
                "nodeInfoList": node_info_list,
                "instanceType": "default",
                "usePersonalQueue": "false"
            },
            "headers": self._auth_headers()
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        """
        构建查询任务状态的完整请求参数（OpenAPI v2 /query）

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 请求参数字典
        """
        return {
            "url": f"{self._host}/openapi/v2/query",
            "method": "POST",
            "json": {
                "taskId": project_id
            },
            "headers": self._auth_headers()
        }

    async def submit_task(self, ai_tool) -> Dict[str, Any]:
        """
        提交 moss 文生图任务

        Args:
            ai_tool: AITool 对象

        Returns:
            Dict[str, Any]: 提交结果
        """
        try:
            self.logger.info(f"Submitting RunninghubAiAppMoss task: ai_tool_id={ai_tool.id}")

            # 构建请求参数（带参考图时抛 ValueError）
            try:
                request_params = await self.build_create_request(ai_tool)
            except ValueError as param_error:
                return {
                    "success": False,
                    "error": str(param_error),
                    "error_type": "USER",
                    "retry": False
                }

            # 调用统一请求方法
            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during RunninghubAiAppMoss task submission: {str(network_error)}")
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
                    message=f"RunninghubAiAppMoss submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "run_ai_app_moss",
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
                        f"RunninghubAiAppMoss upstream congested, will auto-retry: "
                        f"errorCode={error_code}, errorMessage={error_message}"
                    )
                    return self._build_upstream_congested_result()
                self.logger.warning(
                    f"RunninghubAiAppMoss API returned error: errorCode={error_code}, errorMessage={error_message}"
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
                    "error_detail": "RunninghubAiAppMoss API未返回任务ID",
                    "retry": False
                }

            return {
                "success": True,
                "project_id": task_id
            }

        except Exception as e:
            self.logger.error(f"Unexpected exception in RunninghubAiAppMoss submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"RunninghubAiAppMoss submit_task 发生未预期异常: {str(e)}",
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

    @staticmethod
    def _extract_result_url(results: Any) -> Optional[str]:
        """从 v2 query 的 results 列表提取产物图片 URL（优先 png，取第一个带 url 的）"""
        if not isinstance(results, list):
            return None
        first_url = None
        for item in results:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not url:
                continue
            if item.get("outputType") == 'png':
                return url
            if first_url is None:
                first_url = url
        return first_url

    def _extract_failed_reason(self, query_result: Dict[str, Any]) -> str:
        """汇总 v2 query 失败响应里的用户可见错误信息"""
        error_message = (query_result.get("errorMessage") or "").strip()
        if error_message:
            return error_message
        failed_reason = query_result.get("failedReason")
        if isinstance(failed_reason, dict) and failed_reason:
            try:
                return json.dumps(failed_reason, ensure_ascii=False)
            except (TypeError, ValueError):
                return str(failed_reason)
        if failed_reason:
            return str(failed_reason)
        return "任务失败"

    def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        检查 moss 文生图任务状态（OpenAPI v2 /query）

        Args:
            project_id: 任务ID

        Returns:
            Dict[str, Any]: 状态检查结果
        """
        try:
            self.logger.info(f"Checking RunninghubAiAppMoss task status: project_id={project_id}")

            # 查询状态
            query_params = self.build_check_query(project_id)

            try:
                query_result = self._request(**query_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during RunninghubAiAppMoss status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试"
                }

            # 验证查询响应格式
            if not isinstance(query_result, dict) or "status" not in query_result:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="RunninghubAiAppMoss query API 响应格式异常",
                    context={
                        "api": "check_status",
                        "response": query_result,
                        "project_id": project_id
                    }
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "RunningHub 响应格式错误"
                }

            task_status = query_result.get("status", "")

            # 映射状态
            if task_status == "SUCCESS":
                # 产物 url 24 小时有效，调度层负责转存；无 url 时保持
                # SUCCESS + None 走「任务成功但未返回结果URL」终态语义
                return {
                    "status": "SUCCESS",
                    "result_url": self._extract_result_url(query_result.get("results"))
                }
            elif task_status == "FAILED":
                return {
                    "status": "FAILED",
                    "error": self._extract_failed_reason(query_result),
                    "error_type": "USER"
                }
            else:
                # QUEUED, RUNNING 或其他状态
                return {
                    "status": "RUNNING",
                    "message": "任务处理中..."
                }

        except Exception as e:
            self.logger.error(f"Unexpected exception in RunninghubAiAppMoss check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"RunninghubAiAppMoss check_status 发生未预期异常: {str(e)}",
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
