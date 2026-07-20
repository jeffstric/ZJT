"""
Async Task 提交重试处理
在 scheduler 进程中定时处理待提交的异步任务

流程：
1. 获取可重试的任务（status=QUEUED, next_retry_at <= NOW, retry_count < max_retries）
2. 对于每个任务：
   a. 根据 implementation 获取对应的 driver
   b. 占用槽位
   c. 调用 driver.submit_task() 提交到外部 API
   d. 更新 async_task 的 external_task_id
   e. 如果提交失败，释放槽位并安排下次重试
"""
import logging
import asyncio
from typing import Dict, Any

from model import AsyncTasksModel, AsyncTaskStatus, RunningHubSlotsModel
from model.runninghub_slots import RunningHubSlot
from config.unified_config import (
    AsyncTaskImplementationId,
    get_async_task_config
)

logger = logging.getLogger(__name__)

# ⚠️ 命名陷阱：此 DRIVER_MAP 存储字符串路径（延迟导入），而 runninghub_async_task.py 的
# DRIVER_MAP 存储类引用（直接导入）。两处都叫 DRIVER_MAP 但值类型不同。
# 此设计避免同步调度器进程中导入不必要的异步模块。
DRIVER_MAP = {
    AsyncTaskImplementationId.RUNNINGHUB_AUDIO: 'task.async_drivers.runninghub_audio_driver.RunningHubAudioDriver',
    AsyncTaskImplementationId.RUNNINGHUB_FACE_MASK: 'task.async_drivers.runninghub_face_mask_driver.RunningHubFaceMaskDriver',
    AsyncTaskImplementationId.RUNNINGHUB_IMAGE_FACE_MASK: 'task.async_drivers.runninghub_image_face_mask_driver.RunningHubImageFaceMaskDriver',
}


def _get_driver_class(impl_id: int):
    """根据 implementation ID 获取 driver 类"""
    driver_path = DRIVER_MAP.get(impl_id)
    if not driver_path:
        return None
    module_path, class_name = driver_path.rsplit('.', 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _calculate_retry_delay(retry_count: int) -> int:
    """
    计算重试延迟（指数退避）

    Args:
        retry_count: 当前重试次数

    Returns:
        延迟秒数
    """
    base_delays = [30, 60, 120, 300, 300]
    if retry_count < len(base_delays):
        return base_delays[retry_count]
    return 300  # 最多 5 分钟


async def _submit_task_with_retry(task: AsyncTasksModel) -> Dict[str, Any]:
    """
    提交单个任务（带重试逻辑）

    Args:
        task: AsyncTask 对象

    Returns:
        {'success': bool, 'error': str, ...}
    """
    driver_class = _get_driver_class(task.implementation)
    if not driver_class:
        logger.error(f"No driver for implementation: {task.implementation}")
        return {
            'success': False,
            'error': f'未知的实现类型: {task.implementation}'
        }

    config = get_async_task_config(task.implementation)
    driver = driver_class()

    # ===== E2E Mock 防御：mock external_task_id 跳过真实 submit =====
    # 正常 mock async task 的 next_retry_at=NULL，不会被 get_ready_to_retry_tasks 取到，
    # 故不会进入本流程；此守卫仅为防御性兜底（见方案 §5.4）。
    from task.mock_interceptor import is_mock_id
    if is_mock_id(task.external_task_id):
        logger.info(f"[MOCK] async submission skip (mock id) task={task.id}")
        return {'success': True, 'project_id': task.external_task_id, 'mock': True}
    # =============================================================

    # 需要槽位
    if config.need_runninghub_slot:
        # 多密钥轮换：先从密钥池领用密钥
        from task import runninghub_key_pool
        acquired = await runninghub_key_pool.acquire_key_async()
        if acquired is not None:
            api_key_index, api_key, _ = acquired
            slot_max_slots = 999999  # 单密钥上限已由 acquire_key 检查，跳过全局检查
        else:
            api_key_index = runninghub_key_pool.RUNNINGHUB_GLOBAL_KEY_INDEX
            api_key = None
            slot_max_slots = None  # 用默认全局值
        # 注入密钥到 driver（异步驱动通过基类 _apply_api_key_for_submit）
        if hasattr(driver, '_apply_api_key_for_submit'):
            driver._apply_api_key_for_submit(api_key, api_key_index)

        slot_acquired = RunningHubSlotsModel.try_acquire_slot(
            task_id=task.id,
            task_type=config.slot_task_type,
            source=RunningHubSlot.SOURCE_ASYNC,
            api_key_index=api_key_index,
            max_slots=slot_max_slots
        )

        if not slot_acquired:
            # 槽位满，安排下次重试
            delay = _calculate_retry_delay(task.retry_count)
            AsyncTasksModel.schedule_retry(task.id, delay)
            logger.info(f"槽位已满，任务 {task.id} 安排 {delay}s 后重试")
            return {
                'success': False,
                'error': '槽位已满',
                'error_type': 'SLOT_FULL',
                'retry': True
            }

        try:
            # 调用 driver 的 submit_task 提交任务（只传 submit_task 接受的参数）
            import inspect
            params = task.get_params_dict()
            sig = inspect.signature(driver.submit_task)
            valid_params = {k: v for k, v in params.items() if k in sig.parameters}
            result = await driver.submit_task(**valid_params)

            if not result.get('success'):
                RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_ASYNC)
                await runninghub_key_pool.report_failure_async(
                    api_key_index, result.get('error', '')
                )
                AsyncTasksModel.update_status(
                    record_id=task.id,
                    status=AsyncTaskStatus.FAILED,
                    error_message=result.get('error', '提交失败')
                )
                return result

            # 提交成功：原子记录 external_task_id、切换为 PROCESSING 并退出重试队列
            project_id = result.get('project_id')
            AsyncTasksModel.mark_submitted(task.id, project_id)
            RunningHubSlotsModel.update_project_id(task.id, project_id, source=RunningHubSlot.SOURCE_ASYNC)
            await runninghub_key_pool.report_success_async(api_key_index)
            logger.info(f"任务 {task.id} 提交成功，project_id={project_id}")
            return result

        except Exception as e:
            RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_ASYNC)
            await runninghub_key_pool.report_failure_async(api_key_index, str(e))
            logger.error(f"任务 {task.id} 提交异常: {e}", exc_info=True)
            AsyncTasksModel.update_status(
                record_id=task.id,
                status=AsyncTaskStatus.FAILED,
                error_message=str(e)
            )
            raise
    else:
        # 不需要槽位，直接提交
        params = task.get_params_dict()
        result = await driver.submit_task(**params)

        if not result.get('success'):
            AsyncTasksModel.update_status(
                record_id=task.id,
                status=AsyncTaskStatus.FAILED,
                error_message=result.get('error', '提交失败')
            )
            return result

        project_id = result.get('project_id')
        AsyncTasksModel.mark_submitted(task.id, project_id)
        return result


def process_pending_async_task_submissions():
    """
    处理待提交的异步任务（调度器入口）

    扫描所有需要重试的 async_task（status=QUEUED, next_retry_at <= NOW, retry_count < max_retries），
    逐个提交到外部 API。
    """
    try:
        retry_tasks = AsyncTasksModel.get_ready_to_retry_tasks(limit=50)

        if not retry_tasks:
            return

        logger.info(f"开始处理 {len(retry_tasks)} 个待提交的异步任务")

        loop = asyncio.new_event_loop()
        try:
            for task in retry_tasks:
                # 检查是否超过最大重试次数
                if task.retry_count >= task.max_retries:
                    RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_ASYNC)
                    logger.warning(f"任务 {task.id} 超过最大重试次数 {task.max_retries}，标记为失败")
                    AsyncTasksModel.update_status(
                        record_id=task.id,
                        status=AsyncTaskStatus.FAILED,
                        error_message=f'超过最大重试次数 {task.max_retries}'
                    )
                    continue

                try:
                    loop.run_until_complete(_submit_task_with_retry(task))
                except Exception as e:
                    logger.error(f"处理待提交任务异常: {task.id}, error: {str(e)}")
        finally:
            loop.close()

    except Exception as e:
        logger.error(f"处理待提交异步任务失败: {e}", exc_info=True)
