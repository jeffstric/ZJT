"""
异步驱动抽象基类
所有异步驱动都需要继承此基类并实现其抽象方法。
与 BaseVideoDriver（同步驱动）对应，适用于需要异步非阻塞调用的场景。
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging
import traceback
from datetime import datetime
import httpx
from utils.logger_config import DailyFileHandler
from utils.runninghub_error import is_upstream_congested_error

logger = logging.getLogger(__name__)


def _setup_async_api_logger():
    """设置异步 API 请求日志记录器"""
    api_logger = logging.getLogger("async_api_requests")
    if not api_logger.handlers:
        file_handler = DailyFileHandler('async_api_requests', encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        api_logger.addHandler(file_handler)
        api_logger.setLevel(logging.INFO)
    return api_logger


api_logger = _setup_async_api_logger()


class BaseAsyncDriver(ABC):
    """
    异步驱动抽象基类

    所有异步驱动必须继承此类并实现以下方法：
    - submit_task: 异步提交任务到外部API
    - check_status: 异步检查任务状态
    """

    def __init__(self, driver_name: str):
        """
        初始化异步驱动

        Args:
            driver_name: 驱动名称，如 "runninghub_audio" 等
        """
        self.driver_name = driver_name
        self.logger = logging.getLogger(f"{__name__}.{driver_name}")

    @property
    def impl_id(self) -> int:
        """获取实现 ID（子类覆盖）"""
        from config.unified_config import AsyncTaskImplementationId
        return AsyncTaskImplementationId.UNKNOWN

    async def submit_with_slot_management(
        self,
        user_id: int,
        params: Dict[str, Any],
        submit_fn
    ) -> Dict[str, Any]:
        """
        统一提交入口：自动处理槽位管理、async_task 创建、异常释放

        Args:
            user_id: 用户 ID
            params: 任务参数字典
            submit_fn: 业务提交函数，返回 {'success': bool, 'project_id': str, ...}

        Returns:
            {'success': bool, 'project_id': str, 'async_task_id': int, 'slot_full': bool, ...}
        """
        from model import AsyncTasksModel, AsyncTaskStatus, RunningHubSlotsModel
        from model.runninghub_slots import RunningHubSlot
        from config.unified_config import get_async_task_config, AsyncTaskImplementationId

        config = get_async_task_config(self.impl_id)

        # 1. 创建 async_task 记录
        async_task_id = AsyncTasksModel.create(
            implementation=self.impl_id,
            user_id=user_id,
            params=params,
            max_attempts=config.max_attempts
        )

        # ===== E2E Mock 短路：跳过槽位与文件上传，直接写 mock external_task_id =====
        from task.mock_interceptor import is_mock_enabled, generate_mock_project_id
        if is_mock_enabled():
            mock_pid = generate_mock_project_id()
            AsyncTasksModel.update_external_task_id(async_task_id, mock_pid)
            logger.info(f"[MOCK] async submit short-circuit impl={self.impl_id} "
                        f"async_task_id={async_task_id} pid={mock_pid}")
            return {"success": True, "project_id": mock_pid, "async_task_id": async_task_id}
        # =========================================================================

        # 2. 如果需要槽位
        if config.need_runninghub_slot:
            # 多密钥轮换：先从密钥池领用一个密钥
            # 领用失败（池空/全满）时回退全局 key（index=0）
            from task import runninghub_key_pool
            acquired = await runninghub_key_pool.acquire_key_async()
            if acquired is not None:
                api_key_index, api_key, max_slots = acquired
                # 密钥池密钥：单密钥并发上限已由 acquire_key 检查（按 index 维度），
                # 此处跳过全局 max_concurrent_slots 检查（传大值），仅占用 slot 记录
                slot_max_slots = 999999
            else:
                # 回退全局 key（保持向后兼容：单密钥场景），用全局 max_slots 检查
                api_key_index = runninghub_key_pool.RUNNINGHUB_GLOBAL_KEY_INDEX
                api_key = None  # None 表示 driver 用其默认（全局）key
                slot_max_slots = None  # 用默认全局值
            # 注入领用到的密钥到 driver 的 client（多密钥轮换必需）
            self._apply_api_key_for_submit(api_key, api_key_index)

            slot_acquired = RunningHubSlotsModel.try_acquire_slot(
                task_id=async_task_id,
                task_type=config.slot_task_type,
                source=RunningHubSlot.SOURCE_ASYNC,
                api_key_index=api_key_index,
                max_slots=slot_max_slots
            )

            if not slot_acquired:
                # 槽位满：安排重试，由后台任务负责重试提交
                logger.info(f"槽位已满，等待重试: impl_id={self.impl_id}, async_task_id={async_task_id}")
                # 计算重试延迟（指数退避）
                delay = self._calculate_retry_delay(0)
                AsyncTasksModel.schedule_retry(async_task_id, delay)
                return {
                    'success': False,
                    'error': '槽位已满',
                    'error_type': 'SLOT_FULL',
                    'async_task_id': async_task_id,
                    'retry': True
                }

            try:
                result = await submit_fn()

                if not result.get('success'):
                    RunningHubSlotsModel.release_slot(async_task_id, source=RunningHubSlot.SOURCE_ASYNC)
                    # 反馈熔断：提交失败（非上游拥堵类）计入密钥失败
                    await runninghub_key_pool.report_failure_async(
                        api_key_index, result.get('error', '')
                    )
                    # 上游并发超限/限流（api queue limit reached / TASK_QUEUE_MAXED 等）：
                    # 安排延迟重试，不标记 FAILED（复用异步侧指数退避，与本地槽位满处理一致）
                    if result.get('retry_reason') == 'UPSTREAM_CONGESTED' or \
                            is_upstream_congested_error(result.get('error_code', '')):
                        delay = self._calculate_retry_delay(0)
                        AsyncTasksModel.schedule_retry(async_task_id, delay)
                        logger.info(f"上游拥堵，异步任务 {async_task_id} 将在 {delay}s 后重试")
                        return {**result, 'async_task_id': async_task_id}
                    AsyncTasksModel.update_status(
                        record_id=async_task_id,
                        status=AsyncTaskStatus.FAILED,
                        error_message=result.get('error', '提交失败')
                    )
                    return {**result, 'async_task_id': async_task_id}

                # 提交成功
                project_id = result.get('project_id')
                AsyncTasksModel.update_external_task_id(async_task_id, project_id)
                RunningHubSlotsModel.update_project_id(async_task_id, project_id, source=RunningHubSlot.SOURCE_ASYNC)
                await runninghub_key_pool.report_success_async(api_key_index)
                return {**result, 'async_task_id': async_task_id}

            except Exception as e:
                RunningHubSlotsModel.release_slot(async_task_id, source=RunningHubSlot.SOURCE_ASYNC)
                await runninghub_key_pool.report_failure_async(api_key_index, str(e))
                AsyncTasksModel.update_status(
                    record_id=async_task_id,
                    status=AsyncTaskStatus.FAILED,
                    error_message=str(e)
                )
                raise

        # 3. 不需要槽位：直接提交
        return await submit_fn()

    def _apply_api_key_for_submit(self, api_key: Optional[str], api_key_index: int):
        """
        提交前注入领用到的密钥到 driver 的 client（多密钥轮换）。

        子类若持有 self._client（RunningHubClient），则调用其 set_api_key。
        api_key 为 None 时表示回退全局 key，无需切换（client 默认即用全局 key）。

        Args:
            api_key: 领用到的密钥明文，None 表示回退全局 key
            api_key_index: 密钥序号（仅用于日志）
        """
        if api_key is None:
            # 回退全局 key：client 构造时已默认加载全局 key，无需操作
            return
        client = getattr(self, '_client', None)
        if client is not None and hasattr(client, 'set_api_key'):
            client.set_api_key(api_key)
            self.logger.debug(f"已注入密钥 index={api_key_index} 到 {self.driver_name} client")

    def _apply_api_key_for_task(self, task) -> str:
        """
        轮询前根据任务记录的密钥 index 切换 client 密钥。

        通过 runninghub_slots.api_key_index 反查任务提交时所用密钥，
        确保用同一密钥查询结果（错误密钥无法获取结果）。

        Args:
            task: AsyncTask 对象

        Returns:
            实际生效的 api_key_index（0=全局兜底）
        """
        from task import runninghub_key_pool
        from model.runninghub_slots import RunningHubSlot
        idx = runninghub_key_pool.get_key_index_for_slot(task.id, RunningHubSlot.SOURCE_ASYNC)
        api_key = runninghub_key_pool.get_key_by_index(idx)
        client = getattr(self, '_client', None)
        if client is not None and hasattr(client, 'set_api_key') and api_key:
            client.set_api_key(api_key)
        return idx

    @staticmethod
    def _calculate_retry_delay(retry_count: int) -> int:
        """
        计算重试延迟（指数退避）

        Args:
            retry_count: 当前重试次数

        Returns:
            延迟秒数
        """
        # retry_count=0: 30s, retry_count=1: 60s, retry_count=2: 120s, retry_count=3: 300s, 最多 5 分钟
        base_delays = [30, 60, 120, 300, 300]
        if retry_count < len(base_delays):
            return base_delays[retry_count]
        return 300  # 最多 5 分钟

    @abstractmethod
    async def submit_task(self, **kwargs) -> Dict[str, Any]:
        """
        异步提交任务到外部API

        Returns:
            Dict[str, Any]: 返回结果字典
                成功时包含:
                    - success: True
                    - project_id: 外部API返回的任务ID
                失败时包含:
                    - success: False
                    - error: 错误信息（用户可见的友好提示）
                    - error_type: 错误类型，"USER" 或 "SYSTEM"
                    - error_detail: 详细错误信息（仅 error_type="SYSTEM" 时）
                    - retry: 是否需要重试（可选，默认False）
        """
        pass

    @abstractmethod
    async def check_status(self, project_id: str) -> Dict[str, Any]:
        """
        异步查询任务状态

        Args:
            project_id: 外部API返回的任务ID

        Returns:
            Dict[str, Any]: 返回结果字典
                - status: 任务状态 ("RUNNING" | "SUCCESS" | "FAILED")
                - result_url: 结果URL（status为SUCCESS时）
                - error: 错误信息（status为FAILED时）
                - error_type: 错误类型（status为FAILED时）
        """
        pass

    async def _request(
        self,
        url: str,
        method: str = "POST",
        json: dict = None,
        headers: dict = None,
        timeout: float = 30,
        **kwargs
    ) -> dict:
        """
        统一异步 HTTP 请求方法。所有外部 API 调用都通过此方法。
        请求和响应会记录到日志。

        Args:
            url: 请求URL
            method: HTTP方法，默认POST
            json: 请求体（JSON格式）
            headers: 请求头
            timeout: 超时时间（秒）

        Returns:
            dict: API响应的JSON数据

        Raises:
            ConnectionError: 连接失败
            TimeoutError: 请求超时
        """
        request_time = datetime.now().isoformat()
        api_logger.info(f"========== 异步 API 请求开始 ==========")
        api_logger.info(f"Driver: {self.driver_name}")
        api_logger.info(f"Time: {request_time}")
        api_logger.info(f"Method: {method}")
        api_logger.info(f"URL: {url}")
        api_logger.info(f"Headers: {self._mask_sensitive_headers(headers)}")
        api_logger.info(f"Payload: {self._mask_sensitive_payload(json)}")

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method, url, json=json, headers=headers, **kwargs
                )

            response_time = datetime.now().isoformat()
            api_logger.info(f"Response Time: {response_time}")
            api_logger.info(f"Status Code: {response.status_code}")

            try:
                result = response.json()
                api_logger.info(f"Response Body: {self._truncate_base64_in_response(result)}")
            except Exception:
                result = {}
                api_logger.info(f"Response Body (raw): {response.text[:1000]}")

            api_logger.info(f"========== 异步 API 请求结束 ==========")
            response.raise_for_status()
            return result

        except httpx.TimeoutException as e:
            api_logger.error(f"Request Timeout: {str(e)}")
            api_logger.info(f"========== 异步 API 请求超时 ==========")
            raise TimeoutError(str(e)) from e
        except httpx.ConnectError as e:
            api_logger.error(f"Connection Error: {str(e)}")
            api_logger.info(f"========== 异步 API 请求连接失败 ==========")
            raise ConnectionError(str(e)) from e
        except httpx.HTTPStatusError as e:
            api_logger.error(f"HTTP Error: {e.response.status_code}")
            api_logger.info(f"========== 异步 API 请求失败 ==========")
            raise
        except Exception as e:
            api_logger.error(f"Request Error: {str(e)}")
            api_logger.error(f"Traceback: {traceback.format_exc()}")
            api_logger.info(f"========== 异步 API 请求失败 ==========")
            raise

    # ==================== 日志脱敏工具方法 ====================

    def _mask_sensitive_headers(self, headers: dict) -> dict:
        """脱敏请求头中的敏感信息"""
        if not headers:
            return {}
        masked = headers.copy()
        for key in masked:
            if key.lower() in ["authorization", "x-api-key", "api-key"]:
                value = masked[key]
                if len(value) > 20:
                    masked[key] = value[:10] + "***" + value[-4:]
                else:
                    masked[key] = "***"
        return masked

    def _mask_sensitive_payload(self, payload: dict) -> dict:
        """脱敏请求体中的敏感信息（递归处理嵌套字典）"""
        if not payload:
            return {}
        sensitive_keys = ["apikey", "api_key", "secret", "password", "token", "key"]
        masked = {}
        for key, value in payload.items():
            if key.lower() in sensitive_keys:
                str_value = str(value)
                if len(str_value) > 10:
                    masked[key] = str_value[:4] + "***" + str_value[-4:]
                else:
                    masked[key] = "***"
            elif isinstance(value, dict):
                masked[key] = self._mask_sensitive_payload(value)
            elif isinstance(value, list):
                masked[key] = [self._mask_sensitive_payload(item) if isinstance(item, dict) else item for item in value]
            else:
                masked[key] = value
        return masked

    def _truncate_base64_in_response(self, data: Any, max_length: int = 50) -> Any:
        """精简响应体中的 base64 数据和大型字段"""
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if key == "inlineData" and isinstance(value, dict):
                    result[key] = {"mimeType": value.get("mimeType", "unknown"), "data": "[base64 image data masked]"}
                elif key == "data" and isinstance(value, str) and len(value) > max_length:
                    if all(c.isalnum() or c in '+/=' for c in value[:100]):
                        result[key] = f"[base64 data {len(value)} chars masked]"
                    else:
                        result[key] = value
                elif key == "b64_json" and isinstance(value, str) and len(value) > max_length:
                    result[key] = "[b64_json masked]"
                elif key == "thoughtSignature":
                    continue
                elif isinstance(value, dict):
                    result[key] = self._truncate_base64_in_response(value, max_length)
                elif isinstance(value, list):
                    result[key] = [self._truncate_base64_in_response(item, max_length) for item in value]
                else:
                    result[key] = value
            return result
        elif isinstance(data, list):
            return [self._truncate_base64_in_response(item, max_length) for item in data]
        else:
            return data

    def __str__(self):
        return f"{self.__class__.__name__}(driver_name={self.driver_name})"

    def __repr__(self):
        return self.__str__()
