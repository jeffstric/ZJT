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
from model import TasksModel, AIAudioModel
from config.constant import TASK_TYPE_GENERATE_AUDIO, AUTHENTICATION_ID
from utils.index_tts_util import generate_audio, validate_emotion_vector
import os
import yaml
from config_util import get_config_path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load task queue configuration
config_path = get_config_path()
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
task_queue_config = config.get("task_queue", {})
MAX_RETRY_COUNT = task_queue_config.get("max_retry_count", 30)
TASK_EXPIRE_DAYS = task_queue_config.get("task_expire_days", 7)
ENABLE_EXPIRE_CHECK = task_queue_config.get("enable_expire_check", True)

# Get upload directory path
UPLOAD_DIR = "/nas/comfyui_upload/tts/result_audio/"


async def _submit_new_task(ai_audio):
    """
    Submit a new audio generation task (status == 0)
    
    Args:
        ai_audio: AIAudio object
    
    Returns:
        bool: True if successful, False otherwise
    """
    task_id = ai_audio.id
    
    try:
        AIAudioModel.update(task_id, status=1, message="任务处理中")
        TasksModel.update_by_task_id(task_id, status=1)
        # Prepare parameters for generate_audio
        text = ai_audio.text
        
        # Get reference audio path
        spk_audio_path = ai_audio.ref_path
        if not spk_audio_path:
            logger.error(f"Task {task_id}: No reference audio path provided")
            AIAudioModel.update(task_id, status=-1, message="缺少参考音频")
            TasksModel.update_by_task_id(task_id, status=-1)
            return False
        
        
        # Get emotion control parameters
        emo_control_method = ai_audio.emo_control_method or 0
        emo_ref_path = None
        emo_weight = ai_audio.emo_weight if ai_audio.emo_weight is not None else 1.0
        emo_vec = None
        emo_text = ai_audio.emo_text
        
        # Handle emotion reference audio path
        if emo_control_method == 1 and ai_audio.emo_ref_path:
            emo_ref_path = ai_audio.emo_ref_path
        
        # Handle emotion vector
        if emo_control_method == 2 and ai_audio.emo_vec:
            try:
                # Parse emotion vector from comma-separated string
                if isinstance(ai_audio.emo_vec, str):
                    emo_vec = [float(x.strip()) for x in ai_audio.emo_vec.split(',')]
                else:
                    emo_vec = ai_audio.emo_vec
                
                # Validate emotion vector
                is_valid, error_msg = validate_emotion_vector(emo_vec)
                if not is_valid:
                    logger.error(f"Task {task_id}: Invalid emotion vector - {error_msg}")
                    AIAudioModel.update(task_id, status=-1, message=error_msg)
                    TasksModel.update_by_task_id(task_id, status=-1)
                    return False
            except Exception as e:
                logger.error(f"Task {task_id}: Failed to parse emotion vector - {str(e)}")
                AIAudioModel.update(task_id, status=-1, message=f"情感向量解析失败: {str(e)}")
                TasksModel.update_by_task_id(task_id, status=-1)
                return False
        
        # Prepare target path for generated audio
        # os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        audio_filename = f"audio_{timestamp}_{unique_id}.wav"
        result_path = os.path.join(UPLOAD_DIR, audio_filename)
        
        logger.info(f"Task {task_id}: Calling generate_audio with text='{text[:50]}...', emo_control_method={emo_control_method}, result_path={result_path}")
        
        # Call generate_audio utility
        success, audio_path_or_error = await generate_audio(
            text=text,
            spk_audio_path=spk_audio_path,
            emo_control_method=emo_control_method,
            emo_ref_path=emo_ref_path,
            emo_weight=emo_weight,
            emo_vec=emo_vec,
            emo_text=emo_text,
            result_path=result_path
        )
        
        if not success:
            logger.error(f"Task {task_id}: Audio generation failed - {audio_path_or_error}")
            AIAudioModel.update(task_id, status=-1, message=audio_path_or_error)
            TasksModel.update_by_task_id(task_id, status=-1)
            return False
        
        audio_file_path = audio_path_or_error or result_path
        
        logger.info(f"Task {task_id}: Audio saved to {audio_file_path}")
        
        # Update database with result
        AIAudioModel.update(task_id, status=2, result_url=result_path, message="音频生成成功")
        TasksModel.update_by_task_id(task_id, status=2)
        
        logger.info(f"Task {task_id}: Audio generation completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Task {task_id}: Failed to submit audio generation task - {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


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


async def process_generate_audio(task):
    """Process audio generation task logic"""
    try:
        logger.info(f"Processing audio generation task: {task.task_id}")
        ai_audio = AIAudioModel.get_by_id(task.task_id)
        logger.info(f"AI audio {task.task_id} is {ai_audio}")
        
        if not ai_audio:
            logger.error(f"Failed to get AI audio record by ID {task.task_id}")
            return False
        
        status = ai_audio.status
        
        if status == 0:
            return await _submit_new_task(ai_audio)
        else:
            logger.warning(f"Unexpected status {status} for task {task.task_id}")
            return False
        
    except Exception as e:
        logger.error(f"Failed to process video generation task: {str(e)}")
        return False


async def process_task_with_retry(task_type, process_func):
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
        tasks = TasksModel.list_by_type_and_status(task_type, status_list=[0])
        
        if not tasks:
            logger.info(f"No pending {task_type} tasks with status 0")
            return False, False
        
        logger.info(f"Found {len(tasks)} tasks to process for type: {task_type}")
        
        # Loop through all tasks
        processed_count = 0
        success_count = 0
        expired_count = 0
        
        for task in tasks:
            try:
                logger.info(f"Start processing task: {task.task_id}, status: {task.status}, try_count: {task.try_count}")
                
                # 检查任务是否过期
                if _check_task_expiration(task):
                    TasksModel.update_by_task_id(task.task_id, status=-1)
                    AIAudioModel.update(task.task_id, status=-1, message="任务已过期")
                    expired_count += 1
                    logger.info(f"Task {task.task_id} marked as expired")
                    continue
                
                # 检查是否超过最大重试次数
                if _check_max_retry_exceeded(task):
                    TasksModel.update_by_task_id(task.task_id, status=-1)
                    AIAudioModel.update(task.task_id, status=-1, message=f"超过最大重试次数({MAX_RETRY_COUNT})")
                    expired_count += 1
                    logger.info(f"Task {task.task_id} marked as failed due to max retry exceeded")
                    continue
                
                # Update status to 1 (处理中) if it's 0 (队列中)
                if task.status == 0:
                    TasksModel.update_by_task_id(task.task_id, status=1)
                    logger.info(f"Updated task {task.task_id} status to 1 (处理中)")
                
                # Call the specific processing function
                success = await process_func(task)
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
                
        logger.info(f"Summary: processed={processed_count}, succeeded={success_count}, expired={expired_count}")
        return processed_count > 0, success_count > 0
            
    except Exception as e:
        logger.error(f"Task processing error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False, False


async def generate_audio_task(app=None):
    """Audio generation task entry point"""
    await process_task_with_retry(TASK_TYPE_GENERATE_AUDIO, process_generate_audio)
