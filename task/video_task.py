"""
Video generation task processing
"""
import logging
from datetime import datetime, timedelta
import uuid
from perseids_client import make_perseids_request
from config.constant import TASK_COMPUTING_POWER

from duomi_api_requset import (
    create_ai_image,
    create_image_to_video,
    get_ai_task_result,
)
from model import TasksModel, AIToolsModel
from config.constant import TASK_TYPE_GENERATE_VIDEO,AUTHENTICATION_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    
    # Parse image_urls from comma-separated string to array
    image_urls = None
    if ai_tool.image_path:
        if isinstance(ai_tool.image_path, str):
            image_urls = [url.strip() for url in ai_tool.image_path.split(',') if url.strip()]
        else:
            image_urls = ai_tool.image_path
    
    if ai_tool_type in [1, 7]:
        if ai_tool_type == 1:
            model = "gemini-2.5-pro-image-preview"
        else:
            model = "gemini-3-pro-image-preview"
        response = create_ai_image(model, ai_tool.prompt, ai_tool.ratio, image_urls)
        logger.info(response)
        project_id = response.get("data", {}).get("task_id")
    elif ai_tool_type in [2, 3]:
        result = create_image_to_video(ai_tool.prompt, ai_tool.ratio, image_urls, ai_tool.duration)
        logger.info(f"Submit task result: {result}")
        project_id = result.get("id")
    else:
        logger.error(f"Unsupported ai_tool_type: {ai_tool_type}")
        return False
    
    if not project_id:
        logger.error("Failed to create project")
        return False
    
    AIToolsModel.update(task_id, project_id=project_id, status=1)
    TasksModel.update_by_task_id(task_id, status=1)
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

    is_video = ai_tool_type in [2, 3]
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
        logger.info(f"Task {project_id} completed successfully")
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


def process_task_with_retry(task_type, process_func):
    """
    Generic task processing function with retry logic
    
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
        
        for task in tasks:
            try:
                logger.info(f"Start processing task: {task.task_id}, status: {task.status}")
                
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
                    logger.info(f"Task failed: {task.task_id}, retry count: {new_try_count}, status: -1 (处理失败), next trigger: {next_trigger}")
                    
            except Exception as e:
                logger.error(f"Error processing task {task.task_id}: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                
        logger.info(f"Processed {processed_count} tasks, {success_count} succeeded")
        return processed_count > 0, success_count > 0
            
    except Exception as e:
        logger.error(f"Task processing error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False, False


def generate_video_task(app=None):
    """Video generation task entry point"""
    process_task_with_retry(TASK_TYPE_GENERATE_VIDEO, process_generate_video)
