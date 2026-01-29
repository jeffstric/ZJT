"""
Video generation task processing
"""
import logging
from datetime import datetime, timedelta
import uuid
from perseids_client import make_perseids_request
from config.constant import TASK_COMPUTING_POWER
import yaml
import os
from config_util import get_config_path

from duomi_api_requset import (
    create_ai_image,
    create_image_to_video,
    get_ai_task_result,
    create_text_to_image,
    create_kling_image_to_video,
    get_kling_task_status,
)
from runninghub_request import (
    create_ltx2_image_to_video,
    create_wan22_image_to_video,
    check_ltx2_task_status,
    TaskStatus
)
from model import TasksModel, AIToolsModel, RunningHubSlotsModel
from config.constant import TASK_TYPE_GENERATE_VIDEO,AUTHENTICATION_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load test mode configuration
config_path = get_config_path()
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
test_mode_config = config.get("test_mode", {})
TEST_MODE_ENABLED = test_mode_config.get("enabled", False)

# Load task queue configuration
task_queue_config = config.get("task_queue", {})
MAX_RETRY_COUNT = task_queue_config.get("max_retry_count", 30)
TASK_EXPIRE_DAYS = task_queue_config.get("task_expire_days", 7)
ENABLE_EXPIRE_CHECK = task_queue_config.get("enable_expire_check", True)

if TEST_MODE_ENABLED:
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


def _submit_new_task(ai_tool):
    """
    Submit a new task to external API (status == 0)
    
    Args:
        ai_tool: AITool object
    
    Returns:
        bool: True if successful, False otherwise
    """
    ai_tool_type = ai_tool.type
    task_id = ai_tool.id
    
    if TEST_MODE_ENABLED:
        logger.info(f"[TEST MODE] Submitting task {task_id} (type: {ai_tool_type})")
    
    # Parse image_urls from comma-separated string to array
    image_urls = None
    if ai_tool.image_path:
        if isinstance(ai_tool.image_path, str):
            image_urls = [url.strip() for url in ai_tool.image_path.split(',') if url.strip()]
        else:
            image_urls = ai_tool.image_path
    
    if ai_tool_type in [1, 7]:
        # Check if this is image-edit (has image_urls) or text-to-image (no image_urls)
        if image_urls:
            # Image editing task
            if ai_tool_type == 1:
                model = "gemini-2.5-pro-image-preview"
            else:
                model = "gemini-3-pro-image-preview"
            response = create_ai_image(model, ai_tool.prompt, ai_tool.ratio, image_urls,ai_tool.image_size)
            logger.info(response)
            project_id = response.get("data", {}).get("task_id")
        else:
            # Text-to-image task
            if ai_tool_type == 1:
                model = "gemini-2.5-pro-image-preview"  # 标准版
            else:
                model = "gemini-3-pro-image-preview"  # 加强版
            
            # Get image_size from database if available (only for gemini-3-pro-image-preview)
            image_size = None
            if ai_tool_type == 7:  # Only for gemini-3-pro-image-preview
                image_size = ai_tool.image_size or "1K"  # Use stored value or default
            
            response = create_text_to_image(
                model=model,
                prompt=ai_tool.prompt,
                aspect_ratio=ai_tool.ratio or "9:16",
                image_size=image_size
            )
            logger.info(f"Text-to-image response: {response}")
            
            if response.get("code") != 200:
                error_msg = response.get("msg", "API调用失败")
                logger.error(f"Text-to-image API error: {error_msg}")
                return False
            
            project_id = response.get("data", {}).get("task_id")
    elif ai_tool_type == 10:
        # LTX2.0 图生视频 (type=10)
        result = create_ltx2_image_to_video(
            image_url=ai_tool.image_path,
            prompt=ai_tool.prompt or "",
            duration=ai_tool.duration
        )
        logger.info(f"Submit LTX2.0 task result: {result}")
        
        # v2 API 响应格式：直接返回 taskId, status, errorCode, errorMessage
        # 成功时 taskId 存在，失败时 errorCode 或 errorMessage 有值
        if not result.get("taskId"):
            error_msg = result.get("errorMessage") or result.get("msg", "LTX2.0 API调用失败")
            
            # 特殊处理：RunningHub 队列已满错误
            if error_msg == "TASK_QUEUE_MAXED" or result.get("errorCode") == "TASK_QUEUE_MAXED":
                logger.warning(f"RunningHub queue maxed for task {task_id}, will retry later")
                # 延迟60秒后重试，不增加重试计数
                next_trigger = datetime.now() + timedelta(seconds=60)
                TasksModel.update_by_task_id(task_id, next_trigger=next_trigger)
                return True  # 返回True避免增加重试计数
            
            logger.error(f"LTX2.0 API error: {error_msg}")
            return False
        
        project_id = result.get("taskId")
    elif ai_tool_type == 11:
        # Wan2.2 图生视频 (type=11)
        result = create_wan22_image_to_video(
            image_url=ai_tool.image_path,
            prompt=ai_tool.prompt,
            duration=ai_tool.duration,
            ratio=ai_tool.ratio,
            quality="hd"  # 默认使用高清版
        )
        logger.info(f"Submit Wan2.2 task result: {result}")
        
        # v2 API 响应格式：直接返回 taskId, status, errorCode, errorMessage
        # 成功时 taskId 存在，失败时 errorCode 或 errorMessage 有值
        if not result.get("taskId"):
            error_msg = result.get("errorMessage") or result.get("msg", "Wan2.2 API调用失败")
            
            # 特殊处理：RunningHub 队列已满错误
            if error_msg == "TASK_QUEUE_MAXED" or result.get("errorCode") == "TASK_QUEUE_MAXED":
                logger.warning(f"RunningHub queue maxed for task {task_id}, will retry later")
                # 延迟60秒后重试，不增加重试计数
                next_trigger = datetime.now() + timedelta(seconds=60)
                TasksModel.update_by_task_id(task_id, next_trigger=next_trigger)
                return True  # 返回True避免增加重试计数
            
            logger.error(f"Wan2.2 API error: {error_msg}")
            return False
        
        project_id = result.get("taskId")
    elif ai_tool_type == 12:
        # 可灵图生视频 (type=12)
        kling_mode = "std"
        result = create_kling_image_to_video(
            image_url=ai_tool.image_path,
            prompt=ai_tool.prompt,
            duration=ai_tool.duration,
            mode=kling_mode
        )
        logger.info(f"Submit Kling task result: {result}")
        
        if result.get("code") != 0:
            error_msg = result.get("message", "可灵 API调用失败")
            logger.error(f"Kling API error: {error_msg}")
            return False
        
        project_id = result.get("data", {}).get("task_id")
    elif ai_tool_type in [2, 3]:
        # Sora2 视频生成 (type=2: 文生视频, type=3: 图生视频)
        result = create_image_to_video(ai_tool.prompt, ai_tool.ratio, ai_tool.image_path, ai_tool.duration)
        logger.info(f"Submit Sora2 task result: {result}")
        project_id = result.get("id")
    else:
        logger.error(f"Unsupported ai_tool_type: {ai_tool_type}")
        return False
    
    if not project_id:
        logger.error("Failed to create project")
        return False
    
    AIToolsModel.update(task_id, project_id=project_id, status=1)
    TasksModel.update_by_task_id(task_id, status=1)
    
    # 如果是 RunningHub 任务，更新槽位的 project_id
    is_runninghub = ai_tool_type in [10, 11]
    if is_runninghub:
        task = TasksModel.get_by_task_id(task_id)
        if task:
            RunningHubSlotsModel.update_project_id(task.id, project_id)
    
    logger.info(f"Task {task_id} submitted successfully with project_id: {project_id}")
    return True


def _check_task_status(ai_tool):
    """
    Check task status from external API (status == 1)
    
    Args:
        ai_tool: AITool object
    
    Returns:
        bool: True if task completed (success or failed), False if still processing
    """
    project_id = ai_tool.project_id
    ai_tool_type = ai_tool.type
    task_id = ai_tool.id
    
    if not project_id:
        logger.error(f"AI tool {task_id} has no project_id while status=1")
        return False

    # Check if this is LTX2.0 or Wan2.2 model (type=10 or 11, both use RunningHub)
    is_runninghub = ai_tool_type in [10, 11]
    # Check if this is Kling model (type=12, uses Duomi API)
    is_kling = ai_tool_type == 12
    is_video = ai_tool_type in [2, 3, 10, 11, 12]
    
    if TEST_MODE_ENABLED and isinstance(project_id, str) and project_id.startswith("mock_task_"):
        logger.info(f"[TEST MODE] Checking status for mock task {project_id}")
    
    if is_runninghub:
        # LTX2.0 or Wan2.2 model - use RunningHub status check
        try:
            result = check_ltx2_task_status(project_id)
            status = result.get("status")
            
            if status == "SUCCESS":
                # Get video URL from results
                results = result.get("results", [])
                if results and len(results) > 0:
                    media_url = results[0].file_url
                    return _handle_task_success(project_id, task_id, media_url)
                else:
                    logger.error(f"LTX2.0 task {project_id} succeeded but no results")
                    return _handle_task_failure(project_id, task_id, ai_tool_type, "No results returned", ai_tool.user_id)
            elif status == "FAILED":
                return _handle_task_failure(project_id, task_id, ai_tool_type, "Task failed", ai_tool.user_id)
            else:
                # Still processing (QUEUED or RUNNING)
                logger.info(f"LTX2.0 task {project_id} still processing (status={status})")
                return True
        except Exception as e:
            logger.error(f"Error checking LTX2.0 task status: {e}")
            return False
    elif is_kling:
        # Kling model - use Kling status check
        try:
            result = get_kling_task_status(project_id)
            
            if result.get("code") != 0:
                error_msg = result.get("message", "Unknown error")
                logger.error(f"Failed to get Kling task status: {error_msg}")
                return False
            
            data = result.get("data", {})
            task_status = data.get("task_status")
            
            if task_status == "succeed":
                # Get video URL from results
                task_result = data.get("task_result", {})
                videos = task_result.get("videos", [])
                if videos and len(videos) > 0:
                    media_url = videos[0].get("url")
                    return _handle_task_success(project_id, task_id, media_url)
                else:
                    logger.error(f"Kling task {project_id} succeeded but no videos")
                    return _handle_task_failure(project_id, task_id, ai_tool_type, "No videos returned", ai_tool.user_id)
            elif task_status == "failed":
                return _handle_task_failure(project_id, task_id, ai_tool_type, "Task failed", ai_tool.user_id)
            else:
                # Still processing
                logger.info(f"Kling task {project_id} still processing (status={task_status})")
                return True
        except Exception as e:
            logger.error(f"Error checking Kling task status: {e}")
            return False
    else:
        # Sora2 or other models - use original logic
        result = get_ai_task_result(project_id, is_video)
        
        if not isinstance(result, dict):
            logger.error(f"Unexpected task result format for project {project_id}: {result}")
            return False

        if result.get("code") != 0:
            error_msg = result.get("msg", "Unknown error")
            logger.error(f"Failed to get task result: {error_msg}")
            return False

        data = result.get("data", {})
        task_status = data.get("status")  # 0-进行中 1-成功 2-失败
        media_url = data.get("mediaUrl")
        reason = data.get("reason")

        if task_status == 1:
            return _handle_task_success(project_id, task_id, media_url)
        elif task_status == 2:
            return _handle_task_failure(project_id, task_id, ai_tool_type, reason,ai_tool.user_id)
        else:
            logger.info(f"Task {project_id} still processing (status={task_status})")
            return True


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
            status=2
        )
        TasksModel.update_by_task_id(task_id, status=2)
        
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
            status=-1,
            message=reason
        )
        TasksModel.update_by_task_id(task_id, status=-1)
        
        # 释放 RunningHub 槽位
        is_runninghub = ai_tool_type in [10, 11]
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
        computing_power = TASK_COMPUTING_POWER.get(ai_tool_type)
        
        if computing_power:
            transaction_id = str(uuid.uuid4())
            logger.info(f"Refunding {user_id} , {AUTHENTICATION_ID}")
            success, message, response_data = make_perseids_request(
                endpoint='get_auth_token_by_user_id',
                method='POST',
                data={
                    "user_id": user_id,
                    "authentication_id": AUTHENTICATION_ID
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
        
        if status == 0:
            return _submit_new_task(ai_tool)
        elif status == 1:
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
    if not ENABLE_EXPIRE_CHECK:
        return False
    
    if not task.created_at:
        return False
    
    task_age = datetime.now() - task.created_at
    if task_age.days >= TASK_EXPIRE_DAYS:
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
    if task.try_count and task.try_count >= MAX_RETRY_COUNT:
        logger.warning(f"Task {task.task_id} exceeded max retry count ({task.try_count}/{MAX_RETRY_COUNT})")
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
                    TasksModel.update_by_task_id(task.task_id, status=-1)
                    AIToolsModel.update(task.task_id, status=-1, message="任务已过期")
                    
                    # 释放 RunningHub 槽位
                    ai_tool = AIToolsModel.get_by_id(task.task_id)
                    if ai_tool and ai_tool.type in [10, 11]:
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
                    TasksModel.update_by_task_id(task.task_id, status=-1)
                    AIToolsModel.update(task.task_id, status=-1, message=f"超过最大重试次数({MAX_RETRY_COUNT})")
                    
                    # 释放 RunningHub 槽位
                    ai_tool = AIToolsModel.get_by_id(task.task_id)
                    if ai_tool and ai_tool.type in [10, 11]:
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
                
                is_runninghub = ai_tool.type in [10, 11]
                
                # 如果是 RunningHub 任务且状态为0（未提交）
                if is_runninghub and task.status == 0:
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
                if task.status == 0:
                    TasksModel.update_by_task_id(task.task_id, status=1)
                    logger.info(f"Updated task {task.task_id} status to 1 (处理中)")
                
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
