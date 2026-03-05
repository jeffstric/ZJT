"""
Video generation task processing
"""
import logging
from datetime import datetime, timedelta
import uuid
from perseids_client import make_perseids_request
from config.constant import TASK_COMPUTING_POWER
from config.config_util import get_dynamic_config_value

from duomi_api_requset import (
    create_ai_image,
    create_image_to_video,
    create_image_to_video_veo,
    get_ai_task_result,
    create_text_to_image,
    create_kling_image_to_video,
    get_kling_task_status,
)
from runninghub_request import (
    create_ltx2_image_to_video,
    create_wan22_image_to_video,
    create_digital_human,
    check_ltx2_task_status
)
from vidu_api_requset import (
    create_vidu_image_to_video,
    create_vidu_start_end_to_video,
    get_vidu_task_status
)
from model import TasksModel, AIToolsModel, RunningHubSlotsModel
from config.constant import (
    TASK_TYPE_GENERATE_VIDEO,
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
    AI_TOOL_STATUS_COMPLETED,
    AI_TOOL_STATUS_FAILED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    RUNNINGHUB_TASK_TYPES
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _is_test_mode_enabled():
    """动态获取测试模式状态"""
    return get_dynamic_config_value("test_mode", "enabled", default=False)

def _get_max_retry_count():
    """动态获取最大重试次数"""
    return get_dynamic_config_value("task_queue", "max_retry_count", default=30)

def _get_task_expire_days():
    """动态获取任务过期天数"""
    return get_dynamic_config_value("task_queue", "task_expire_days", default=7)

def _is_expire_check_enabled():
    """动态获取是否启用过期检查"""
    return get_dynamic_config_value("task_queue", "enable_expire_check", default=True)

if _is_test_mode_enabled():
    logger.info("=" * 60)
    logger.info("TEST MODE ENABLED - Using mock API responses")
    logger.info("=" * 60)


def calculate_next_retry_delay(try_count):
    """
    Calculate next retry delay time
    
    Args:
        try_count: Number of attempts made
    
    Returns:
        Delay in seconds, maximum 360 seconds
    """
    base_delay = 3
    max_delay = 360
    delay_seconds = base_delay * (2 ** (try_count - 1))
    return min(delay_seconds, max_delay)


def _refund_computing_power(ai_tool, reason: str):
    """
    退还算力

    Args:
        ai_tool: AITool 对象
        reason: 退还原因
    """
    try:
        user_id = ai_tool.user_id
        ai_tool_type = ai_tool.type
        task_id = ai_tool.id

        if not user_id:
            logger.warning(f"Task {task_id} has no user_id, skipping refund")
            return

        computing_power_config = TASK_COMPUTING_POWER.get(ai_tool_type)

        # Handle dict-based computing power (e.g., Wan2.2, Kling, Vidu)
        if isinstance(computing_power_config, dict):
            duration = getattr(ai_tool, 'duration', 5) or 5
            computing_power = computing_power_config.get(duration)
            if not computing_power:
                computing_power = list(computing_power_config.values())[0]
        else:
            computing_power = computing_power_config

        if not computing_power:
            logger.warning(f"Task {task_id} type {ai_tool_type} has no computing power config")
            return

        transaction_id = str(uuid.uuid4())
        logger.info(f"Refunding {computing_power} computing power for user {user_id}, reason: {reason}")

        success, message, response_data = make_perseids_request(
            endpoint='get_auth_token_by_user_id',
            method='POST',
            data={"user_id": user_id}
        )

        if not success:
            logger.error(f"Failed to get auth token for user {user_id}: {message}")
            return

        auth_token = response_data['token']
        headers = {'Authorization': f'Bearer {auth_token}'}

        success, message, response_data = make_perseids_request(
            endpoint='user/calculate_computing_power',
            method='POST',
            headers=headers,
            data={
                "computing_power": computing_power,
                "behavior": "increase",
                "transaction_id": transaction_id
            }
        )

        if success:
            logger.info(f"Task {task_id} refund ({computing_power}) processed successfully")
        else:
            logger.error(f"Task {task_id} refund ({computing_power}) failed: {message}")

    except Exception as e:
        logger.error(f"Failed to process refund for task {ai_tool.id}: {e}")


def _submit_new_task(ai_tool):
    """
    使用驱动架构提交新任务 (status == AI_TOOL_STATUS_PENDING)

    这是新的实现方法，使用统一的驱动架构替代原有的 if-elif 分支逻辑。
    测试通过后将替换 _submit_new_task 方法。

    Args:
        ai_tool: AITool 对象

    Returns:
        bool: True 表示成功，False 表示失败
    """
    from task.visual_drivers import VideoDriverFactory
    
    ai_tool_type = ai_tool.type
    task_id = ai_tool.id
    
    if _is_test_mode_enabled():
        logger.info(f"[TEST MODE] [DRIVER] Submitting task {task_id} (type: {ai_tool_type})")
    
    try:
        # 1. 根据任务类型创建对应的驱动实例
        driver = VideoDriverFactory.create_driver_by_type(ai_tool_type)
        
        if not driver:
            logger.error(f"Unsupported driver type: {ai_tool_type}")
            # 更新任务状态为失败
            AIToolsModel.update(task_id, status=AI_TOOL_STATUS_FAILED, message=f"不支持的任务类型: {ai_tool_type}")
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
            # 退还算力
            _refund_computing_power(ai_tool, f"不支持的任务类型: {ai_tool_type}")
            return False
        
        logger.info(f"Using driver: {driver.driver_name} for task {task_id}")
        
        # 2. 调用驱动提交任务
        result = driver.submit_task(ai_tool)
        
        # 3. 处理提交结果
        if not result.get("success"):
            error = result.get("error", "未知错误")
            error_type = result.get("error_type", "SYSTEM")
            error_detail = result.get("error_detail", "")
            
            logger.error(f"Task {task_id} submission failed: {error}")
            if error_detail:
                logger.error(f"Error detail: {error_detail}")
            
            # 处理需要重试的情况（通常是网络异常）
            if result.get("retry"):
                logger.warning(f"Task {task_id} will retry later due to network error")
                # 返回 False，让 process_task_with_retry 增加重试计数并设置延迟
                return False
            
            # 根据错误类型处理（不需要重试的错误）
            if error_type == "USER":
                # 用户错误，直接返回给用户，标记任务失败
                AIToolsModel.update(task_id, status=AI_TOOL_STATUS_FAILED, message=error)
                TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
            else:
                # 系统错误，已通过 Sentry 报警，标记任务失败
                AIToolsModel.update(task_id, status=AI_TOOL_STATUS_FAILED, message="服务异常，请联系技术支持")
                TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
            
            # 返回 True 表示任务已处理完成（虽然失败了），不需要重试
            return True
        
        # 4. 提交成功，检查是否同步模式
        if result.get("sync_mode"):
            # 同步 API 直接返回结果，无需轮询
            result_url = result.get("result_url")
            AIToolsModel.update(task_id, result_url=result_url, status=AI_TOOL_STATUS_COMPLETED)
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_COMPLETED)
            logger.info(f"Sync task {task_id} completed with result: {result_url}")
            return True

        # 5. 异步模式，更新数据库
        project_id = result.get("project_id")

        if not project_id:
            logger.error(f"Task {task_id} submitted but no project_id returned")
            AIToolsModel.update(task_id, status=AI_TOOL_STATUS_FAILED, message="服务异常，未返回任务ID")
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
            # 返回 True 表示任务已处理完成（失败），不需要重试
            return True
        
        # 更新 AITools 和 Tasks 表状态
        AIToolsModel.update(task_id, project_id=project_id, status=AI_TOOL_STATUS_PROCESSING)
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_PROCESSING)
        
        # 如果是 RunningHub 任务，更新槽位的 project_id
        is_runninghub = ai_tool_type in RUNNINGHUB_TASK_TYPES
        if is_runninghub:
            task = TasksModel.get_by_task_id(task_id)
            if task:
                RunningHubSlotsModel.update_project_id(task.id, project_id)
                logger.info(f"Updated RunningHub slot project_id for task {task_id}")
        
        logger.info(f"Task {task_id} submitted successfully with project_id: {project_id}")
        return True
        
    except Exception as e:
        # 捕获所有未预期的异常
        logger.error(f"Unexpected exception in _submit_new_task_with_driver for task {task_id}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # 更新任务状态为失败
        AIToolsModel.update(task_id, status=AI_TOOL_STATUS_FAILED, message="服务异常，请联系技术支持")
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
        
        return False


def _check_task_status(ai_tool):
    """
    使用驱动架构检查任务状态 (status == AI_TOOL_STATUS_PROCESSING)
    
    这是新的实现方法，使用统一的驱动架构替代原有的 if-elif 分支逻辑。
    测试通过后将替换 _check_task_status 方法。
    
    Args:
        ai_tool: AITool 对象
    
    Returns:
        bool: True 表示任务已完成（成功或失败），False 表示仍在处理中
    """
    from task.visual_drivers import VideoDriverFactory
    
    project_id = ai_tool.project_id
    ai_tool_type = ai_tool.type
    task_id = ai_tool.id
    
    if not project_id:
        logger.error(f"AI tool {task_id} has no project_id while status=AI_TOOL_STATUS_PROCESSING")
        return False
    
    if _is_test_mode_enabled() and isinstance(project_id, str) and project_id.startswith("mock_task_"):
        logger.info(f"[TEST MODE] [DRIVER] Checking status for mock task {project_id}")
    
    try:
        # 1. 根据任务类型创建对应的驱动实例
        driver = VideoDriverFactory.create_driver_by_type(ai_tool_type)
        
        if not driver:
            logger.error(f"Unsupported driver type: {ai_tool_type}")
            # 更新任务状态为失败
            AIToolsModel.update(task_id, status=AI_TOOL_STATUS_FAILED, message=f"不支持的任务类型: {ai_tool_type}")
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
            return True  # 返回 True 表示任务已完成（失败）
        
        logger.info(f"Checking status for task {task_id} using driver: {driver.driver_name}")
        
        # 2. 调用驱动检查状态
        result = driver.check_status(project_id)
        
        # 3. 处理状态检查结果
        status = result.get("status")
        
        if status == "SUCCESS":
            # 任务成功完成
            result_url = result.get("result_url")        
            if not result_url:
                logger.error(f"Task {task_id} succeeded but no result URL returned")
                return _handle_task_failure(project_id, task_id, ai_tool_type, "任务成功但未返回结果URL", ai_tool.user_id)
            
            logger.info(f"Task {task_id} completed successfully, result_url: {result_url}")
            return _handle_task_success(project_id, task_id, result_url)
            
        elif status == "FAILED":
            # 任务失败
            error = result.get("error", "任务失败")
            error_type = result.get("error_type", "SYSTEM")
            
            logger.error(f"Task {task_id} failed: {error} (type: {error_type})")
            return _handle_task_failure(project_id, task_id, ai_tool_type, error, ai_tool.user_id)
            
        elif status == "RUNNING":
            # 任务仍在处理中
            message = result.get("message", "任务处理中...")
            logger.info(f"Task {task_id} still processing: {message}")
            return False  # 返回 False 表示仍在处理中
            
        else:
            # 未知状态
            logger.warning(f"Task {task_id} returned unknown status: {status}")
            return False  # 继续等待
        
    except Exception as e:
        # 捕获所有未预期的异常
        logger.error(f"Unexpected exception in _check_task_status_with_driver for task {task_id}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # 不立即标记为失败，继续重试
        return False

def _handle_task_success(project_id, task_id, media_url):
    """
    Handle successful task completion
    
    Args:
        project_id: Project ID
        task_id: Task ID
        media_url: Result media URL
    
    Returns:
        bool: True if handled successfully
    """
    try:
        AIToolsModel.update_by_project_id(
            project_id=project_id,
            result_url=media_url,
            status=AI_TOOL_STATUS_COMPLETED
        )
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_COMPLETED)
        
        # 释放 RunningHub 槽位（通过 project_id）
        RunningHubSlotsModel.release_slot_by_project_id(project_id)
        
        logger.info(f"Task {project_id} completed successfully, slot released")
        return True
    except Exception as db_error:
        logger.error(f"Failed to update records for success task {project_id}: {db_error}")
        return False


def _handle_task_failure(project_id, task_id, ai_tool_type, reason, user_id):
    """
    Handle failed task
    
    Args:
        project_id: Project ID
        task_id: Task ID
        ai_tool_type: AI tool type
        reason: Failure reason
        user_id: User ID for refund tracking
    
    Returns:
        bool: True if handled successfully
    """
    # Translate error messages
    if reason and "We currently do not support uploads of images containing photorealistic people" in reason:
        reason = "图片包含真人，无法处理"
    elif reason and "This content may violate our guardrails concerning similarity to third-party content. " in reason:
        reason = "此内容可能违反了我们关于与第三方内容相似性的规定"

    try:
        AIToolsModel.update_by_project_id(
            project_id=project_id,
            status=AI_TOOL_STATUS_FAILED,
            message=reason
        )
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
        
        # 释放 RunningHub 槽位
        is_runninghub = ai_tool_type in RUNNINGHUB_TASK_TYPES
        if is_runninghub:
            if project_id:
                RunningHubSlotsModel.release_slot_by_project_id(project_id)
            else:
                # 如果没有 project_id（提交失败），通过 task_id 释放
                task = TasksModel.get_by_task_id(task_id)
                if task:
                    RunningHubSlotsModel.release_slot_by_task_table_id(task.id)
        
    except Exception as db_error:
        logger.error(f"Failed to update records for failed task {project_id}: {db_error}")
        return False
    
    # Refund computing power (note: auth_token not available in background task)
    try:
        computing_power_config = TASK_COMPUTING_POWER.get(ai_tool_type)
        
        # Handle dict-based computing power (e.g., Wan2.2, Kling, Vidu)
        if isinstance(computing_power_config, dict):
            # Get AI tool to retrieve duration
            ai_tool = AIToolsModel.get_by_id(task_id)
            duration = ai_tool.duration if ai_tool else 5
            computing_power = computing_power_config.get(duration)
            if not computing_power:
                # Use first available value as fallback
                computing_power = list(computing_power_config.values())[0]
        else:
            computing_power = computing_power_config
        
        if computing_power:
            transaction_id = str(uuid.uuid4())
            logger.info(f"Refunding computing power for user {user_id}")
            success, message, response_data = make_perseids_request(
                endpoint='get_auth_token_by_user_id',
                method='POST',
                data={
                    "user_id": user_id
                }
            )

            if not success:
                logger.error(f"Failed to get auth token for user {user_id}: {message}")
                return False
                
            auth_token = response_data['token']
            headers = {'Authorization': f'Bearer {auth_token}'}
                        
            # 发起请求，增加算力（补回）
            success, message, response_data = make_perseids_request(
                endpoint='user/calculate_computing_power',
                method='POST',
                headers=headers,
                data={
                    "computing_power": computing_power,
                    "behavior": "increase",
                    "transaction_id": transaction_id
                }
            )
            if success:
                logger.info(f"Task {project_id} failed, computing power refund ({computing_power}) processed successfully")
            else:
                logger.error(f"Task {project_id} failed, computing power refund ({computing_power}) failed: {message}")
    except Exception as refund_error:
        logger.error(f"Failed to process refund for task {project_id}: {refund_error}")
    
    logger.info(f"Task {project_id} failed: {reason}")
    return True


def process_generate_video(task):
    """Process video generation task logic"""
    try:
        logger.info(f"Processing video generation task: {task.task_id}")
        ai_tool = AIToolsModel.get_by_id(task.task_id)
        logger.info(f"AI tool {task.task_id} is {ai_tool}")

        if not ai_tool:
            logger.error(f"Failed to get AI tool record by ID {task.task_id}")
            return False

        status = ai_tool.status

        if status == AI_TOOL_STATUS_PENDING:
            return _submit_new_task(ai_tool)
        elif status == AI_TOOL_STATUS_PROCESSING:
            return _check_task_status(ai_tool)
        else:
            logger.warning(f"Unexpected status {status} for task {task.task_id}")
            return False
        
    except Exception as e:
        logger.error(f"Failed to process video generation task: {str(e)}")
        return False


def _check_task_expiration(task):
    """
    检查任务是否已过期
    
    Args:
        task: Task对象
    
    Returns:
        bool: True表示任务已过期
    """
    if not _is_expire_check_enabled():
        return False
    
    if not task.created_at:
        return False
    
    task_age = datetime.now() - task.created_at
    if task_age.days >= _get_task_expire_days():
        logger.warning(f"Task {task.task_id} expired (created {task_age.days} days ago)")
        return True
    
    return False


def _check_max_retry_exceeded(task):
    """
    检查任务是否超过最大重试次数
    
    Args:
        task: Task对象
    
    Returns:
        bool: True表示超过最大重试次数
    """
    if task.try_count and task.try_count >= _get_max_retry_count():
        logger.warning(f"Task {task.task_id} exceeded max retry count ({task.try_count}/{_get_max_retry_count()})")
        return True
    
    return False


def process_task_with_retry(task_type, process_func):
    """
    Generic task processing function with retry logic and RunningHub concurrency control
    
    Args:
        task_type: Task type
        process_func: Specific task processing function
    
    Returns:
        Tuple of (has_task, process_result)
    """
    try:
        # Query tasks by type with status 0 (队列中) or 1 (处理中)
        tasks = TasksModel.list_by_type_and_status(task_type, status_list=[0, 1])
        
        if not tasks:
            logger.info(f"No pending {task_type} tasks with status 0 or 1")
            return False, False
        
        logger.info(f"Found {len(tasks)} tasks to process for type: {task_type}")
        
        # Loop through all tasks
        processed_count = 0
        success_count = 0
        delayed_count = 0
        expired_count = 0
        
        for task in tasks:
            try:
                logger.info(f"Start processing task: task_id={task.task_id}, table_id={task.id}, status={task.status}, try_count={task.try_count}")
                
                # 检查任务是否过期
                if _check_task_expiration(task):
                    # 标记任务为失败
                    TasksModel.update_by_task_id(task.task_id, status=TASK_STATUS_FAILED)
                    AIToolsModel.update(task.task_id, status=AI_TOOL_STATUS_FAILED, message="任务已过期")
                    
                    # 释放 RunningHub 槽位
                    ai_tool = AIToolsModel.get_by_id(task.task_id)
                    if ai_tool and ai_tool.type in RUNNINGHUB_TASK_TYPES:
                        if ai_tool.project_id:
                            RunningHubSlotsModel.release_slot_by_project_id(ai_tool.project_id)
                        else:
                            RunningHubSlotsModel.release_slot_by_task_table_id(task.id)
                    
                    expired_count += 1
                    logger.info(f"Task {task.task_id} marked as expired")
                    continue
                
                # 检查是否超过最大重试次数
                if _check_max_retry_exceeded(task):
                    # 标记任务为失败
                    TasksModel.update_by_task_id(task.task_id, status=TASK_STATUS_FAILED)
                    AIToolsModel.update(task.task_id, status=AI_TOOL_STATUS_FAILED, message=f"超过最大重试次数({_get_max_retry_count()})")
                    
                    # 获取 AI 工具详情用于退还算力和释放槽位
                    ai_tool = AIToolsModel.get_by_id(task.task_id)
                    if ai_tool:
                        # 退还算力
                        try:
                            computing_power = TASK_COMPUTING_POWER.get(ai_tool.type)
                            if computing_power:
                                transaction_id = str(uuid.uuid4())
                                success, message, response_data = make_perseids_request(
                                    endpoint='get_auth_token_by_user_id',
                                    method='POST',
                                    data={
                                        "user_id": ai_tool.user_id
                                    }
                                )
                                if success:
                                    auth_token = response_data['token']
                                    headers = {'Authorization': f'Bearer {auth_token}'}
                                    success, message, response_data = make_perseids_request(
                                        endpoint='user/calculate_computing_power',
                                        method='POST',
                                        headers=headers,
                                        data={
                                            "computing_power": computing_power,
                                            "behavior": "increase",
                                            "transaction_id": transaction_id
                                        }
                                    )
                                    if success:
                                        logger.info(f"Task {task.task_id} exceeded max retry, refunded {computing_power} computing power")
                        except Exception as e:
                            logger.error(f"Failed to refund computing power for task {task.task_id}: {e}")
                        
                        # 释放 RunningHub 槽位
                        if ai_tool.type in RUNNINGHUB_TASK_TYPES:
                            if ai_tool.project_id:
                                RunningHubSlotsModel.release_slot_by_project_id(ai_tool.project_id)
                            else:
                                RunningHubSlotsModel.release_slot_by_task_table_id(task.id)
                    
                    expired_count += 1
                    logger.info(f"Task {task.task_id} marked as failed due to max retry exceeded")
                    continue
                
                # 获取 AI 工具详情
                ai_tool = AIToolsModel.get_by_id(task.task_id)
                if not ai_tool:
                    logger.error(f"AI tool {task.task_id} not found")
                    continue
                
                is_runninghub = ai_tool.type in RUNNINGHUB_TASK_TYPES
                
                # 如果是 RunningHub 任务且状态为0（未提交）
                if is_runninghub and task.status == TASK_STATUS_QUEUED:
                    # 尝试获取槽位
                    slot_acquired = RunningHubSlotsModel.try_acquire_slot(
                        task_table_id=task.id,
                        task_id=task.task_id,
                        task_type=ai_tool.type
                    )
                    
                    if not slot_acquired:
                        # 槽位已满，延迟此任务
                        delay_seconds = 30  # 延迟30秒
                        next_trigger = datetime.now() + timedelta(seconds=delay_seconds)
                        TasksModel.update_by_task_id(
                            task.task_id,
                            next_trigger=next_trigger
                        )
                        logger.info(f"Task {task.task_id} delayed by {delay_seconds}s due to slot limit, next_trigger: {next_trigger}")
                        delayed_count += 1
                        continue  # 跳过此任务，处理下一个
                
                # Update status to 1 (处理中) if it's 0 (队列中)
                if task.status == TASK_STATUS_QUEUED:
                    TasksModel.update_by_task_id(task.task_id, status=TASK_STATUS_PROCESSING)
                    logger.info(f"Updated task {task.task_id} status to TASK_STATUS_PROCESSING (处理中)")
                
                # Call the specific processing function
                success= process_func(task)
                processed_count += 1
                
                if success:
                    logger.info(f"Task completed successfully: {task.task_id}")
                    success_count += 1
                else:
                    # Failed - increment retry count and update status to -1 (处理失败)
                    new_try_count = (task.try_count or 0) + 1
                    delay_seconds = calculate_next_retry_delay(new_try_count)
                    next_trigger = datetime.now() + timedelta(seconds=delay_seconds)
                    
                    TasksModel.update_by_task_id(
                        task.task_id,
                        try_count=new_try_count,
                        next_trigger=next_trigger
                    )
                    logger.info(f"Task failed: {task.task_id}, retry count: {new_try_count}, next trigger: {next_trigger}")
                    
            except Exception as e:
                logger.error(f"Error processing task {task.task_id}: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                
        logger.info(f"Summary: processed={processed_count}, succeeded={success_count}, delayed={delayed_count}, expired={expired_count}")
        return processed_count > 0, success_count > 0
            
    except Exception as e:
        logger.error(f"Task processing error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False, False


def generate_video_task(app=None):
    """Video generation task entry point"""
    process_task_with_retry(TASK_TYPE_GENERATE_VIDEO, process_generate_video)
