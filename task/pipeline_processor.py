"""
Pipeline 编排器
负责创建、分发、检查流水线步骤，是 pipeline 系统的核心协调模块。

职责：
1. 创建 param_prepare / before_finish 步骤（委托 PipelineDriverFactory）
2. 分发步骤给对应驱动执行
3. 轮询处理中的步骤，推进状态
4. 将步骤结果应用回 ai_tool
"""
import logging
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
import pymysql

from model import (
    PipelineStepModel, PipelineStep, PipelineStepStatus, PipelineStage,
    AIToolsModel, AITool, AsyncTasksModel, AsyncTaskStatus
)
from task.pipeline_drivers import PipelineDriverFactory

logger = logging.getLogger(__name__)


class PipelineProcessor:
    """Pipeline 编排器"""

    # ==================== 步骤创建（委托给 PipelineDriverFactory） ====================

    @staticmethod
    def create_param_prepare_steps(
        ai_tool_id: int,
        ai_tool_type: int
    ) -> List[int]:
        """
        根据任务类型自动创建 param_prepare 步骤

        委托给 PipelineDriverFactory.create_param_prepare_steps()

        Args:
            ai_tool_id: ai_tools.id
            ai_tool_type: ai_tools.type

        Returns:
            创建的步骤 ID 列表
        """
        return PipelineDriverFactory.create_param_prepare_steps(ai_tool_id, ai_tool_type)

    @staticmethod
    def is_seedance_face_mask_type(ai_tool_type: int) -> bool:
        """是否属于走 param_prepare 人脸遮盖的 Seedance 模型（委托 PipelineDriverFactory）。

        供 server.py 闸门查询，模型清单单一来源在 config/unified_config.py。
        """
        return PipelineDriverFactory.is_seedance_face_mask_type(ai_tool_type)

    @staticmethod
    def create_before_finish_steps(
        ai_tool_id: int,
        ai_tool_type: int,
        failed_implementation: int,
        failure_reason: str
    ) -> List[int]:
        """
        创建 before_finish 重试步骤

        委托给 PipelineDriverFactory.create_before_finish_steps()

        Args:
            ai_tool_id: ai_tools.id
            ai_tool_type: ai_tools.type
            failed_implementation: 失败时的实现方 ID
            failure_reason: 失败原因

        Returns:
            创建的步骤 ID 列表
        """
        return PipelineDriverFactory.create_before_finish_steps(
            ai_tool_id, ai_tool_type, failed_implementation, failure_reason
        )

    # ==================== 步骤查询 ====================

    @staticmethod
    def get_pending_steps(ai_tool_id: int, stage: str) -> List[PipelineStep]:
        """获取待处理步骤"""
        return PipelineStepModel.get_pending_steps(ai_tool_id, stage)

    @staticmethod
    def get_all_steps(ai_tool_id: int, stage: str) -> List[PipelineStep]:
        """获取某阶段所有步骤"""
        return PipelineStepModel.get_by_ai_tool_and_stage(ai_tool_id, stage)

    @staticmethod
    def has_steps(ai_tool_id: int, stage: str) -> bool:
        """检查是否存在步骤"""
        return PipelineStepModel.has_steps(ai_tool_id, stage)

    # ==================== 步骤分发 ====================

    @staticmethod
    async def dispatch_step(step: PipelineStep) -> bool:
        """
        分发步骤给对应驱动执行

        关键变更：槽位满时自动安排重试

        Args:
            step: PipelineStep 对象

        Returns:
            True 表示分发成功（步骤进入 PROCESSING），False 表示失败
        """
        driver = PipelineDriverFactory.create_driver(step.step_type)
        if not driver:
            logger.error(f"No driver for step type: {step.step_type}, step_id={step.id}")
            PipelineStepModel.update_status(
                step.id,
                PipelineStepStatus.FAILED,
                error_message=f'未知的步骤类型: {step.step_type}'
            )
            return False

        # 更新步骤状态为 PROCESSING
        PipelineStepModel.update_status(step.id, PipelineStepStatus.PROCESSING)

        # 获取关联的 ai_tool
        ai_tool = AIToolsModel.get_by_id(step.ai_tool_id)
        if not ai_tool:
            logger.error(f"ai_tool {step.ai_tool_id} not found for step {step.id}")
            PipelineStepModel.update_status(
                step.id,
                PipelineStepStatus.FAILED,
                error_message='关联的 ai_tool 不存在'
            )
            return False

        # 执行步骤
        try:
            result = await driver.execute(step, ai_tool)

            if result.get('success'):
                async_task_id = result.get('async_task_id')
                if async_task_id:
                    # 步骤创建了 async_task，关联并等待
                    PipelineStepModel.update_async_task_id(step.id, async_task_id)
                    logger.info(f"Step {step.id} dispatched, async_task_id={async_task_id}")
                else:
                    # 步骤直接完成（如 implementation_retry）
                    result_data = result.get('result_data')
                    PipelineStepModel.update_status_with_retry(
                        step.id,
                        PipelineStepStatus.COMPLETED,
                        result_data=result_data
                    )
                    logger.info(f"Step {step.id} completed directly")
                return True
            else:
                # 处理失败
                error = result.get('error', '未知错误')
                error_type = result.get('error_type', '')

                # 槽位满：安排重试
                if error_type == 'SLOT_FULL':
                    delay = PipelineProcessor._calculate_retry_delay(step.retry_count)
                    PipelineStepModel.schedule_retry(step.id, delay)
                    PipelineStepModel.update_status(step.id, PipelineStepStatus.PENDING)
                    logger.info(f"槽位满，步骤 {step.id} 安排 {delay}s 后重试")
                    return True

                # 其他失败：标记步骤失败
                logger.error(f"Step {step.id} execute failed: {error}")
                PipelineStepModel.update_status(
                    step.id,
                    PipelineStepStatus.FAILED,
                    error_message=error
                )
                return False

        except pymysql.MySQLError as e:
            logger.error(f"Step {step.id} DB error during execute: {e}", exc_info=True)
            PipelineStepModel.update_status(
                step.id,
                PipelineStepStatus.FAILED,
                error_message=f'数据库异常: {str(e)}'
            )
            return False
        except Exception as e:
            logger.error(f"Step {step.id} execute exception: {e}", exc_info=True)
            PipelineStepModel.update_status(
                step.id,
                PipelineStepStatus.FAILED,
                error_message=f'执行异常: {str(e)}'
            )
            return False

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

    # ==================== 结果应用 ====================

    @staticmethod
    def apply_results(ai_tool: AITool, stage: str):
        """
        将步骤结果应用回 ai_tool

        Args:
            ai_tool: AITool 对象
            stage: 阶段名称
        """
        steps = PipelineStepModel.get_by_ai_tool_and_stage(ai_tool.id, stage)

        if stage == PipelineStage.PARAM_PREPARE:
            # 预处理阶段：将步骤结果写回 ai_tool 的对应字段
            updates = {}
            image_path_items = None
            reference_image_items = None

            for step in steps:
                if step.status == PipelineStepStatus.COMPLETED and step.step_type == 'face_mask':
                    masked_video_url = step.result_url
                    if masked_video_url:
                        # 更新 ai_tool 的 video_path 为遮盖后的视频
                        updates['video_path'] = masked_video_url
                        logger.info(
                            f"Applied face_mask result to ai_tool {ai_tool.id}: "
                            f"video_path -> {masked_video_url}"
                        )
                elif step.status == PipelineStepStatus.COMPLETED and step.step_type == 'image_face_mask':
                    masked_image_url = step.result_url
                    if not masked_image_url:
                        continue

                    params = step.get_params_dict()
                    field = params.get('field')
                    index = params.get('index')
                    if not isinstance(index, int):
                        logger.warning(f"image_face_mask step {step.id} missing integer index, skipped")
                        continue

                    if field == 'image_path':
                        if image_path_items is None:
                            image_path_items = [
                                item.strip()
                                for item in (getattr(ai_tool, 'image_path', '') or '').split(',')
                                if item.strip()
                            ]
                        if 0 <= index < len(image_path_items):
                            image_path_items[index] = masked_image_url
                            updates['image_path'] = ','.join(image_path_items)
                            logger.info(
                                f"Applied image_face_mask result to ai_tool {ai_tool.id}: "
                                f"image_path[{index}] -> {masked_image_url}"
                            )
                    elif field == 'reference_images':
                        if reference_image_items is None:
                            raw_reference_images = getattr(ai_tool, 'reference_images', None)
                            try:
                                parsed = json.loads(raw_reference_images) if isinstance(raw_reference_images, str) else raw_reference_images
                            except json.JSONDecodeError:
                                parsed = []
                            reference_image_items = parsed if isinstance(parsed, list) else []
                        if 0 <= index < len(reference_image_items):
                            reference_image_items[index] = masked_image_url
                            updates['reference_images'] = json.dumps(reference_image_items, ensure_ascii=False)
                            logger.info(
                                f"Applied image_face_mask result to ai_tool {ai_tool.id}: "
                                f"reference_images[{index}] -> {masked_image_url}"
                            )

            if updates:
                AIToolsModel.update(ai_tool.id, **updates)

    # ==================== 调度器入口 ====================

    @staticmethod
    async def process_all_pending_steps():
        """
        处理所有待处理的 pipeline 步骤（调度器入口）

        流程：
        1. 获取所有 PENDING 状态的步骤，分发给驱动执行
        2. 获取所有 PROCESSING 状态的步骤，轮询 async_task 状态
        3. 处理重试步骤（next_retry_at <= NOW）
        4. 检查是否有 ai_tool 的所有步骤都完成了，推进 ai_tool 状态
        """
        # 1. 处理 PENDING 状态的步骤（分发任务）
        waiting_steps = PipelineStepModel.get_all_waiting_steps(limit=50)
        if waiting_steps:
            logger.info(f"Dispatching {len(waiting_steps)} waiting pipeline steps")
            dispatched_before_finish = set()  # (ai_tool_id, stage) 去重
            for step in waiting_steps:
                try:
                    key = (step.ai_tool_id, step.stage)
                    # before_finish 阶段：同一 ai_tool 只分发一个步骤，避免并发覆盖
                    if step.stage == PipelineStage.BEFORE_FINISH:
                        if key in dispatched_before_finish:
                            continue
                        dispatched_before_finish.add(key)

                    success = await PipelineProcessor.dispatch_step(step)

                    # 如果 before_finish 步骤已同步完成，将同组其余步骤标记为 skipped
                    if success and step.stage == PipelineStage.BEFORE_FINISH:
                        remaining = PipelineStepModel.get_pending_steps(step.ai_tool_id, step.stage)
                        for r in remaining:
                            PipelineStepModel.update_status(
                                r.id, PipelineStepStatus.COMPLETED,
                                result_data={'skipped': True, 'reason': 'earlier_retry_succeeded'}
                            )
                        logger.info(f"Skipped {len(remaining)} remaining before_finish steps for ai_tool {step.ai_tool_id}")
                except Exception as e:
                    logger.error(f"Error dispatching step {step.id}: {e}", exc_info=True)

        # 2. 处理 PROCESSING 状态的步骤
        processing_steps = PipelineStepModel.get_processing_steps(limit=50)

        if processing_steps:
            logger.info(f"Processing {len(processing_steps)} pipeline steps")

            # 记录已处理的 ai_tool_id，避免重复检查
            checked_ai_tools = set()

            for step in processing_steps:
                try:
                    await PipelineProcessor._process_single_step(step)

                    # 检查该步骤所属的 ai_tool 是否所有步骤都完成
                    if step.ai_tool_id not in checked_ai_tools:
                        checked_ai_tools.add(step.ai_tool_id)
                        await PipelineProcessor._check_ai_tool_stage_completion(
                            step.ai_tool_id, step.stage
                        )

                except Exception as e:
                    logger.error(f"Error processing step {step.id}: {e}", exc_info=True)

        # 处理重试步骤
        retry_steps = PipelineProcessor.get_ready_to_retry_steps(limit=50)
        if retry_steps:
            logger.info(f"Processing {len(retry_steps)} retry pipeline steps")
            for step in retry_steps:
                try:
                    await PipelineProcessor.dispatch_step(step)
                except Exception as e:
                    logger.error(f"Error retrying step {step.id}: {e}", exc_info=True)

    @staticmethod
    def get_ready_to_retry_steps(limit: int = 50) -> List[PipelineStep]:
        """获取可重试的步骤"""
        return PipelineStepModel.get_ready_to_retry_steps(limit)

    @staticmethod
    async def _process_single_step(step: PipelineStep):
        """处理单个步骤"""
        if not step.async_task_id:
            # 没有关联 async_task，可能是 implementation_retry 等直接执行的步骤
            # 这种情况应该在 dispatch_step 时就已经 COMPLETED 了
            # 如果还是 PROCESSING，可能是异常情况
            logger.warning(
                f"Step {step.id} is PROCESSING but has no async_task_id, "
                f"step_type={step.step_type}"
            )
            return

        # 查询 async_task 状态
        async_task = AsyncTasksModel.get_by_id(step.async_task_id)
        if not async_task:
            logger.error(f"async_task {step.async_task_id} not found for step {step.id}")
            PipelineStepModel.update_status(
                step.id,
                PipelineStepStatus.FAILED,
                error_message=f'async_task {step.async_task_id} 不存在'
            )
            return

        if async_task.status == AsyncTaskStatus.COMPLETED:
            # async_task 完成，标记步骤完成
            result_data = {}
            if async_task.result_url:
                result_data['result_url'] = async_task.result_url
            if async_task.result_data:
                result_data.update(async_task.get_result_data_dict())

            PipelineStepModel.update_status(
                step.id,
                PipelineStepStatus.COMPLETED,
                result_data=result_data,
                result_url=async_task.result_url
            )
            logger.info(f"Step {step.id} completed (async_task {step.async_task_id})")

        elif async_task.status in (AsyncTaskStatus.FAILED, AsyncTaskStatus.TIMEOUT):
            # async_task 失败，标记步骤失败
            error = async_task.error_message or 'async_task 失败'
            PipelineStepModel.update_status(
                step.id,
                PipelineStepStatus.FAILED,
                error_message=error
            )
            logger.warning(f"Step {step.id} failed (async_task {step.async_task_id}): {error}")

        # 其他状态（QUEUED, PROCESSING）继续等待

    @staticmethod
    async def _check_ai_tool_stage_completion(ai_tool_id: int, stage: str):
        """
        检查 ai_tool 某阶段是否所有步骤都完成，据此推进 ai_tool 状态

        - param_prepare 全部完成 → ai_tool status 改回 PENDING(0)
        - param_prepare 有失败且无待处理 → ai_tool status 改为 FAILED(-1)

        Args:
            ai_tool_id: ai_tools.id
            stage: 阶段名称
        """
        steps = PipelineStepModel.get_by_ai_tool_and_stage(ai_tool_id, stage)
        if not steps:
            return

        pending = [s for s in steps if s.status in (PipelineStepStatus.PENDING, PipelineStepStatus.PROCESSING)]
        failed = [s for s in steps if s.status in (PipelineStepStatus.FAILED, PipelineStepStatus.TIMEOUT)]
        completed = [s for s in steps if s.status == PipelineStepStatus.COMPLETED]

        total = len(steps)
        logger.info(
            f"Pipeline stage {stage} for ai_tool {ai_tool_id}: "
            f"total={total}, completed={len(completed)}, pending={len(pending)}, failed={len(failed)}"
        )

        # 如果还有 PENDING/PROCESSING 步骤，分发下一个
        if pending:
            if not any(s.status == PipelineStepStatus.PROCESSING for s in pending):
                next_pending = next(
                    (s for s in steps if s.status == PipelineStepStatus.PENDING),
                    None
                )
                if next_pending:
                    logger.info(f"Dispatching next pending step {next_pending.id} for ai_tool {ai_tool_id}")
                    await PipelineProcessor.dispatch_step(next_pending)
            return

        # 所有步骤已结束（没有 PENDING/PROCESSING 了）
        if stage == PipelineStage.PARAM_PREPARE:
            from model import AIToolsModel
            from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_FAILED

            if len(completed) == total:
                # 全部完成：推进到 PENDING，等待 visual_task 正常处理
                AIToolsModel.update(ai_tool_id, status=AI_TOOL_STATUS_PENDING)
                logger.info(f"ai_tool {ai_tool_id} param_prepare all completed, status -> PENDING")
            elif failed:
                # 有失败：标记 ai_tool 失败
                AIToolsModel.update(ai_tool_id, status=AI_TOOL_STATUS_FAILED, completed_time=datetime.now())
                logger.warning(f"ai_tool {ai_tool_id} param_prepare has {len(failed)} failed steps, status -> FAILED")

        elif stage == PipelineStage.BEFORE_FINISH:
            from model import AIToolsModel, TasksModel
            from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_FAILED, TASK_STATUS_QUEUED, TASK_STATUS_FAILED

            if len(completed) == total:
                # 全部完成：确保 tasks.status 同步（安全兜底）
                ai_tool = AIToolsModel.get_by_id(ai_tool_id)
                if ai_tool and ai_tool.status == AI_TOOL_STATUS_PENDING:
                    TasksModel.update_by_task_id(ai_tool_id, status=TASK_STATUS_QUEUED)
                    logger.info(f"ai_tool {ai_tool_id} before_finish all completed, tasks -> QUEUED")
            elif failed:
                # 所有重试耗尽 → 最终失败
                AIToolsModel.update(ai_tool_id, status=AI_TOOL_STATUS_FAILED, completed_time=datetime.now())
                TasksModel.update_by_task_id(ai_tool_id, status=TASK_STATUS_FAILED)
                logger.warning(f"ai_tool {ai_tool_id} before_finish all failed, status -> FAILED")
