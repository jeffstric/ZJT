"""
Audio generation task processing
"""
import asyncio
import logging
from datetime import datetime, timedelta
import uuid
import json
from typing import Optional, Dict, Any
from model import TasksModel, AIAudioModel
from model.storyboard import StoryboardModel, StoryboardSceneModel
from model.storyboard_dialogue_audio import StoryboardDialogueAudioModel
from model.storyboard_dialogue import StoryboardDialogueModel
from config.constant import (
    TASK_TYPE_GENERATE_AUDIO,
    AI_AUDIO_STATUS_PENDING,
    AI_AUDIO_STATUS_PROCESSING,
    AI_AUDIO_STATUS_COMPLETED,
    AI_AUDIO_STATUS_FAILED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED
)
from task.async_drivers.runninghub_audio_driver import RunningHubAudioConfig
from utils.index_tts_util import generate_audio, validate_emotion_vector
from utils.audio_duration_util import probe_audio_duration
import os
from config.config_util import get_dynamic_config_value

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _get_max_retry_count():
    """动态获取最大重试次数"""
    return get_dynamic_config_value("task_queue", "max_retry_count", default=30)

def _get_task_expire_days():
    """动态获取任务过期天数"""
    return get_dynamic_config_value("task_queue", "task_expire_days", default=7)

def _is_expire_check_enabled():
    """动态获取是否启用过期检查"""
    return get_dynamic_config_value("task_queue", "enable_expire_check", default=True)

# Get upload directory path
UPLOAD_DIR = "/home/appuser/comfyui_upload/tts/result_audio/"


async def recalc_scene_duration_if_all_completed(scene_id: int) -> Optional[float]:
    """
    把 storyboard_scene.duration 同步为「已完成选中配音」的时长之和（best-effort），
    并联动重算故事板总时长。

    best-effort 语义（2026-08-13 修复）：
    只要分镜下有一条已 COMPLETED 的选中配音，就把 duration 同步为这些已完成配音
    的累计时长。缺配音 / 处理中 / 失败 / 时长缺失的对白被忽略（与前端 buildScenePlan
    和导出 _build_scene_audio 只播放/拼接已有配音的口径一致）。
    这样「部分对白缺配音」的分镜 duration 不再卡在 LLM 估算值（估算值常 < 已完成
    配音时长，导致播放器提前切镜、音频/视频被掐断）。
    一条已完成配音都没有时返回 None，保留 LLM 估算值兜底。

    Returns:
        Optional[float]: 有已完成配音时返回写入的新 duration；无 dialogue / 无已完成配音 / 异常返回 None。
        所有异常仅记日志，不向上抛出（best-effort 联动，不阻塞调用方）。
    """
    if not scene_id:
        return None
    try:
        total = await asyncio.to_thread(
            StoryboardDialogueAudioModel.sum_selected_durations_if_all_completed, scene_id
        )
    except Exception as e:
        logger.warning(f"[scene-duration] scene={scene_id} 完成度查询失败: {e}")
        return None
    if total is None:
        # 无 dialogue 或无任何已完成配音 → 保留 LLM 估算值
        return None

    # DECIMAL(10,3) 保留毫秒精度；下限 0.1s 避免全零时长导致 0 秒分镜（播放器
    # resolveSceneSpan 已有 0.1s 下限保护，此处与之对齐，不再人为抬到 1.0s）。
    new_duration = max(0.1, round(float(total), 3))
    try:
        await asyncio.to_thread(StoryboardSceneModel.update, scene_id, duration=new_duration)
    except Exception as e:
        logger.warning(f"[scene-duration] scene={scene_id} 更新 duration={new_duration} 失败: {e}")
        return None

    # 联动重算故事板总时长
    try:
        scene = await asyncio.to_thread(StoryboardSceneModel.get_by_id, scene_id)
        storyboard_id = getattr(scene, 'storyboard_id', None) if scene else None
        if storyboard_id:
            await asyncio.to_thread(StoryboardModel.recalc_total_duration, storyboard_id)
    except Exception as e:
        logger.warning(f"[scene-duration] scene={scene_id} 联动重算故事板总时长失败: {e}")

    logger.info(
        f"[scene-duration] scene={scene_id} duration={new_duration}s (已完成配音累计 {total:.3f}s)"
    )
    return new_duration


async def _finalize_scene_duration_if_completed(ai_audio_id: int, audio_url: str) -> None:
    """
    配音生成成功后的分镜时长联动：
    1. 用 ffprobe 探测本条音频时长，回写到 storyboard_dialogue_audio.duration。
    2. 反查该音频所属 scene_id，调用 recalc_scene_duration_if_all_completed 重算分镜时长。

    纯后端联动，任何步骤失败都只记日志，不影响音频本身的成功结果。
    """
    if not audio_url:
        return

    # Step 1: 探测时长并回写
    try:
        duration = await probe_audio_duration(audio_url)
    except Exception as e:
        logger.warning(f"[scene-duration] ai_audio={ai_audio_id} 探测时长异常: {e}")
        return
    if duration is None or duration <= 0:
        logger.warning(f"[scene-duration] ai_audio={ai_audio_id} 未能获取有效时长, url={audio_url}")
        return
    try:
        await asyncio.to_thread(
            StoryboardDialogueAudioModel.update_duration_by_ai_audio_id, ai_audio_id, duration
        )
    except Exception as e:
        logger.warning(f"[scene-duration] ai_audio={ai_audio_id} 回写 duration 失败: {e}")
        return

    # Step 2: 反查 scene_id
    try:
        dialogue_audio = await asyncio.to_thread(
            StoryboardDialogueAudioModel.get_by_ai_audio_id, ai_audio_id
        )
    except Exception as e:
        logger.warning(f"[scene-duration] ai_audio={ai_audio_id} 反查 dialogue_audio 失败: {e}")
        return
    if not dialogue_audio:
        return
    dialogue_id = getattr(dialogue_audio, 'dialogue_id', None)
    if not dialogue_id:
        return
    try:
        dialogue = await asyncio.to_thread(StoryboardDialogueModel.get_by_id, dialogue_id)
    except Exception as e:
        logger.warning(f"[scene-duration] dialogue={dialogue_id} 查询失败: {e}")
        return
    if not dialogue:
        return
    scene_id = getattr(dialogue, 'scene_id', None)
    if not scene_id:
        return

    # Step 3: 判定是否全部完成，若是则重算分镜时长并联动故事板总时长
    await recalc_scene_duration_if_all_completed(scene_id)




async def _submit_new_task(ai_audio):
    """
    Submit a new audio generation task (status == AI_AUDIO_STATUS_PENDING)
    
    Args:
        ai_audio: AIAudio object
    
    Returns:
        bool: True if successful, False otherwise
    """
    task_id = ai_audio.id

    # ===== E2E Mock 短路（必须在 generate_audio 之前，直接写 mock result_url）=====
    # 注意：不能放在 utils/index_tts_util.generate_audio 内部——_submit_new_task 会用
    # 本地 audio_filename 拼接 result_url 覆盖返回值，导致写库 URL 指向不存在文件。
    from task.mock_interceptor import is_mock_enabled, mock_audio
    if is_mock_enabled():
        url = mock_audio("tts")
        if url:
            AIAudioModel.update(task_id, status=AI_AUDIO_STATUS_COMPLETED,
                                result_url=url, message="[MOCK] 音频生成成功")
            StoryboardDialogueAudioModel.update_audio_url_by_ai_audio_id(task_id, url)
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_COMPLETED)
            logger.info(f"[MOCK] audio tts short-circuit task={task_id} url={url}")
            # Mock 场景同样联动分镜时长（保证 E2E 测试覆盖）
            try:
                await _finalize_scene_duration_if_completed(task_id, url)
            except Exception as e:
                logger.warning(f"[MOCK] task={task_id}: 分镜时长联动失败: {e}")
            return True
    # =====================================================================

    try:
        AIAudioModel.update(task_id, status=AI_AUDIO_STATUS_PROCESSING, message="任务处理中")
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_PROCESSING)
        # Prepare parameters for generate_audio
        text = ai_audio.text
        
        # Get reference audio path
        spk_audio_path = ai_audio.ref_path
        if not spk_audio_path:
            logger.error(f"Task {task_id}: No reference audio path provided")
            AIAudioModel.update(task_id, status=AI_AUDIO_STATUS_FAILED, message="缺少参考音频")
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
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
                    AIAudioModel.update(task_id, status=AI_AUDIO_STATUS_FAILED, message=error_msg)
                    TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
                    return False
            except Exception as e:
                logger.error(f"Task {task_id}: Failed to parse emotion vector - {str(e)}")
                AIAudioModel.update(task_id, status=AI_AUDIO_STATUS_FAILED, message=f"情感向量解析失败: {str(e)}")
                TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
                return False
        
        # Prepare target path for generated audio
        # os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        audio_filename = f"audio_{timestamp}_{unique_id}.wav"
        result_path = os.path.join(UPLOAD_DIR, audio_filename)
        
        logger.info(
            f"Task {task_id}: Calling generate_audio with text='{text[:50]}...', "
            f"emo_control_method={emo_control_method}, emo_vec={emo_vec!r}, "
            f"emo_weight={emo_weight}, result_path={result_path}"
        )
        logger.info(
            "[dialogue-emotion][audio-task] task_id=%s emo_control_method=%s emo_vec=%r "
            "emo_text=%r text_preview=%r",
            task_id,
            emo_control_method,
            emo_vec if emo_vec is not None else ai_audio.emo_vec,
            emo_text,
            (text[:40] + "...") if len(text) > 40 else text,
        )
        
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
            AIAudioModel.update(task_id, status=AI_AUDIO_STATUS_FAILED, message=audio_path_or_error)
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
            return False
        
        audio_file_path = audio_path_or_error or result_path

        logger.info(f"Task {task_id}: Audio saved to {audio_file_path}")
        upload_url = get_dynamic_config_value("tts", "upload_url")
        result_url = f"{upload_url}{audio_filename}"
        # Update database with result
        AIAudioModel.update(task_id, status=AI_AUDIO_STATUS_COMPLETED, result_url=result_url, message="音频生成成功")
        StoryboardDialogueAudioModel.update_audio_url_by_ai_audio_id(task_id, result_url)
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_COMPLETED)

        # 联动分镜时长：探测本条音频时长，若该分镜所有配音已完成则重算分镜时长
        try:
            await _finalize_scene_duration_if_completed(task_id, result_url)
        except Exception as e:
            logger.warning(f"Task {task_id}: 分镜时长联动失败, 不影响音频结果: {e}")

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
        
        if status == AI_AUDIO_STATUS_PENDING:
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
                    TasksModel.update_by_task_id(task.task_id, status=TASK_STATUS_FAILED)
                    AIAudioModel.update(task.task_id, status=AI_AUDIO_STATUS_FAILED, message="任务已过期")
                    expired_count += 1
                    logger.info(f"Task {task.task_id} marked as expired")
                    continue
                
                # 检查是否超过最大重试次数
                if _check_max_retry_exceeded(task):
                    TasksModel.update_by_task_id(task.task_id, status=TASK_STATUS_FAILED)
                    AIAudioModel.update(task.task_id, status=AI_AUDIO_STATUS_FAILED, message=f"超过最大重试次数({_get_max_retry_count()})")
                    expired_count += 1
                    logger.info(f"Task {task.task_id} marked as failed due to max retry exceeded")
                    continue
                
                # Update status to 1 (处理中) if it's 0 (队列中)
                if task.status == TASK_STATUS_QUEUED:
                    TasksModel.update_by_task_id(task.task_id, status=TASK_STATUS_PROCESSING)
                    logger.info(f"Updated task {task.task_id} status to TASK_STATUS_PROCESSING (处理中)")
                
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
                new_try_count = (task.try_count or 0) + 1
                delay_seconds = calculate_next_retry_delay(new_try_count)
                next_trigger = datetime.now() + timedelta(seconds=delay_seconds)
                TasksModel.update_by_task_id(
                    task.task_id,
                    try_count=new_try_count,
                    next_trigger=next_trigger,
                )
                logger.info(
                    f"Task exception backoff: {task.task_id}, retry count: {new_try_count}, next trigger: {next_trigger}"
                )
                
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





async def _analyze_character_voice_capability(
    character_data: Dict[str, Any],
    model: Optional[str] = None,
    vendor_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    使用 LLM 智能分析角色发声能力和音色特征

    Args:
        character_data: 角色数据字典
        model: LLM 模型名称（可选，未提供时使用默认模型）
        vendor_id: 供应商 ID（可选）

    Returns:
        dict: {
            "can_speak_human_language": bool,
            "voice_type": str,
            "voice_description": str,
            "sample_text": str
        }
    """
    if not character_data:
        return {
            "can_speak_human_language": True,
            "voice_type": "human",
            "voice_description": "平静、自然、清晰的声音",
            "sample_text": "大家好，我是角色。"
        }

    # 如果没有提供 model，使用默认模型
    if not model:
        model = "qwen3.5-plus"

    field_mapping = {
        'name': '角色名',
        'age': '年龄',
        'identity': '身份',
        'appearance': '外貌',
        'personality': '性格',
        'behavior': '行为习惯',
        'other_info': '补充设定',
    }
    character_lines = []
    for key, label in field_mapping.items():
        value = character_data.get(key)
        if value and str(value).strip():
            character_lines.append(f"{label}：{str(value).strip()}")

    if not character_lines:
        return {
            "can_speak_human_language": True,
            "voice_type": "human",
            "voice_description": "平静、自然、清晰的声音",
            "sample_text": f"大家好，我是{character_data.get('name', '角色')}。"
        }

    system_prompt = (
        "你是一位专业的声音设计师。请分析以下角色信息，判断该角色能否说人话，以及应该使用什么样的声音。\n\n"
        "请严格按照以下JSON格式输出，不要输出任何其他内容：\n"
        "{\n"
        '  "can_speak_human_language": true/false,\n'
        '  "voice_type": "human" | "dog" | "cat" | "bird" | "other_animal" | "machine" | "nature",\n'
        '  "voice_description": "音色描述（用于TTS提示词）",\n'
        '  "sample_text": "示例文本（人话或动物叫声）"\n'
        "}\n\n"
        "判断规则：\n"
        "1. 如果角色明确说明\"会说话\"、\"能说人话\"→ can_speak_human_language=true\n"
        "2. 如果角色是普通动物且无特殊说明→ can_speak_human_language=false\n"
        "3. 如果角色是\"修炼成精\"、\"童话故事中的xxx\"→ can_speak_human_language=true\n\n"
        "重要要求：\n"
        "4. voice_description 必须聚焦声音特征：音色、音调、语速、年龄感、性别特征\n"
        "   - 人类角色必须包含性别（男性/女性）和年龄感（如\"30岁左右\"、\"年轻\"等）\n"
        "   - 示例：\"30岁左右的成熟男性，声音沉稳有力\"、\"25岁左右的年轻女性，声音清脆悦耳\"\n\n"
        "5. sample_text 生成规则：\n"
        "   - 能说人话（人类/会说话的动物）→ 必须包含年龄和性别信息的自我介绍（20-40字）\n"
        "     * 格式参考：\"大家好，我是{角色名}，今年{年龄}岁，是一位{性别}，是{身份}。很高兴在这个故事里与你相遇。\"\n"
        "     * 如果角色信息中没有明确年龄，根据身份和外貌推断（如少年约15-18岁，青年约20-30岁）\n"
        "     * 如果角色信息中没有明确性别，根据身份和外貌推断\n"
        "   - 不能说人话（普通动物）→ 生成对应的声音（狗=汪汪汪，猫=喵喵喵，15-20字）"
    )

    user_prompt = "请根据以下角色信息，生成音色分析：\n\n" + "\n".join(character_lines) + "\n\n请直接输出JSON："

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        from llm.llm_client_factory import get_llm_client
        import asyncio

        llm_client = get_llm_client(model, vendor_id=vendor_id)
        response = await asyncio.to_thread(
            llm_client.call_api,
            model=model,
            messages=messages,
            temperature=0.3,
            max_tokens=1500,
        )

        result_text = response.choices[0].message.content.strip() if response and response.choices else ""

        if result_text:
            try:
                result_json = json.loads(result_text)
                logger.info(f"LLM 生成角色音色分析成功: {result_json}")
                return result_json
            except json.JSONDecodeError:
                logger.warning(f"LLM 返回的不是有效JSON: {result_text}")
        else:
            logger.warning("LLM 返回空内容")

    except Exception as e:
        logger.warning(f"LLM 生成音色分析失败: {e}")

    return {
        "can_speak_human_language": True,
        "voice_type": "human",
        "voice_description": "平静、自然、清晰的声音",
        "sample_text": f"大家好，我是{character_data.get('name', '角色')}。"
    }


async def build_character_audio_text(
    character_data: Dict[str, Any],
    custom_text: Optional[str],
    model: Optional[str] = None,
    vendor_id: Optional[int] = None
) -> str:
    """
    构建角色音频文本（使用 LLM 智能判断角色发声类型）

    Args:
        character_data: 角色数据字典
        custom_text: 自定义文本（可选）
        model: LLM 模型名称（可选）
        vendor_id: 供应商 ID（可选）

    Returns:
        str: 音频文本
    """
    if custom_text and custom_text.strip():
        return custom_text.strip()

    voice_analysis = await _analyze_character_voice_capability(character_data, model, vendor_id)
    return voice_analysis.get('sample_text', f"大家好，我是{character_data.get('name', '角色')}。")


async def build_character_audio_style_prompt(
    character_data: Dict[str, Any],
    custom_prompt: Optional[str],
    model: Optional[str] = None,
    vendor_id: Optional[int] = None
) -> str:
    """
    构建角色音色风格提示词（使用 LLM 智能判断角色发声类型）
    如果用户提供了自定义提示词，直接返回；
    否则调用 LLM 根据角色信息自动生成专业的音色描述。

    Args:
        character_data: 角色数据字典
        custom_prompt: 自定义提示词（可选）
        model: LLM 模型名称（可选）
        vendor_id: 供应商 ID（可选）

    Returns:
        str: 音色风格提示词
    """
    if custom_prompt and custom_prompt.strip():
        return custom_prompt.strip()

    if not character_data:
        return RunningHubAudioConfig.AUDIO_STYLE_DEFAULT_PROMPT

    voice_analysis = await _analyze_character_voice_capability(character_data, model, vendor_id)
    return voice_analysis.get('voice_description', RunningHubAudioConfig.AUDIO_STYLE_DEFAULT_PROMPT)
