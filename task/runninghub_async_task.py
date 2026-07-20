"""
RunningHub 异步任务处理
在 scheduler 进程中定时轮询 RunningHub 任务状态并更新数据库

使用通用 async_tasks 表，通过 implementation 字段区分不同的任务类型：
- RUNNINGHUB_AUDIO: 音频生成
- RUNNINGHUB_FACE_MASK: 人脸遮盖视频生成
- RUNNINGHUB_IMAGE_FACE_MASK: 人脸遮盖图片生成
"""
import asyncio
import logging
from datetime import datetime
from typing import Any

from model import AsyncTasksModel, AsyncTaskStatus, RunningHubSlotsModel
from model.runninghub_slots import RunningHubSlot
from config.unified_config import AsyncTaskImplementationId
from task.async_drivers.runninghub_audio_driver import RunningHubAudioDriver
from task.async_drivers.runninghub_face_mask_driver import RunningHubFaceMaskDriver
from task.async_drivers.runninghub_image_face_mask_driver import RunningHubImageFaceMaskDriver

logger = logging.getLogger(__name__)

DRIVER_MAP = {
    AsyncTaskImplementationId.RUNNINGHUB_AUDIO: RunningHubAudioDriver,
    AsyncTaskImplementationId.RUNNINGHUB_FACE_MASK: RunningHubFaceMaskDriver,
    AsyncTaskImplementationId.RUNNINGHUB_IMAGE_FACE_MASK: RunningHubImageFaceMaskDriver,
}


def _setup_cdn_mapping(task: Any, local_path: str, original_url: str, character_id: int):
    """
    创建或替换 CDN mapping 记录，触发异步上传
    复用 ensure_entity_image_mapping，传入 label="voice"

    Args:
        task: AsyncTask 对象
        local_path: 本地相对路径（如 "upload/character/voice/rh_voice_xxx.wav"）
        original_url: 原始远程 URL
        character_id: 角色 ID
    """
    from utils.media_mapping_util import ensure_entity_image_mapping
    from model.media_file_mapping import MediaFileEntity

    ensure_entity_image_mapping(
        user_id=task.user_id,
        image_url=f"/{local_path}",
        entity_type=MediaFileEntity.CHARACTER,
        entity_id=character_id,
        label="voice"
    )


def _handle_audio_task_success(task: Any, result_url: str):
    """
    处理音频任务成功的情况：
    1. 下载音频到本地 upload/character/voice/
    2. 如果开启图床，创建 CDN mapping 并触发上传
    3. 更新角色的 default_voice 为本地路径

    Args:
        task: AsyncTask 对象
        result_url: RunningHub 远程音频 URL
    """
    from datetime import datetime

    params = task.get_params_dict()
    character_id = params.get('character_id')
    character_name = params.get('character_name')

    # Step 1: 下载音频到本地
    voice_url = result_url  # 默认使用远程 URL（下载失败时回退）
    local_path = None

    try:
        from utils.audio_utils import download_and_save_character_voice
        local_path = download_and_save_character_voice(
            remote_url=result_url,
            filename_prefix="rh_voice"
        )
        if local_path:
            voice_url = f"/{local_path}"
            logger.info(f"Audio saved locally, voice_url: {voice_url}")
        else:
            logger.warning(f"Failed to download audio, using remote URL: {result_url}")
    except Exception as e:
        logger.error(f"Download audio failed: {e}", exc_info=True)

    # Step 2: 如果开启 CDN 且有 character_id，创建 mapping 并触发上传
    if local_path and character_id:
        try:
            from config.config_util import get_config
            enable_cdn = get_config().get("server", {}).get("auto_upload_to_cdn", False)
            if enable_cdn:
                _setup_cdn_mapping(task, local_path, result_url, character_id)
        except Exception as e:
            logger.error(f"CDN mapping setup failed: {e}", exc_info=True)

    # Step 3: 更新角色的 default_voice
    # 优先通过 character_id 更新数据库
    if character_id:
        try:
            from model.character import CharacterModel
            CharacterModel.update(character_id, default_voice=voice_url)
            logger.info(f"Updated character {character_id} default_voice: {voice_url}")
            return
        except Exception as e:
            logger.error(f"Failed to update character default_voice by id: {e}")

    # 通过 character_name 更新角色 JSON 文件
    if character_name and task.user_id:
        try:
            from script_writer_core.file_manager import FileManager
            file_manager = FileManager()
            uid = str(task.user_id)
            world_id = params.get('world_id', uid)
            character_data = file_manager.get_character_json(character_name, uid, world_id)
            if character_data:
                character_data['default_voice'] = voice_url
                character_data['updated_at'] = datetime.now().isoformat()
                from script_writer_core.mcp_tool import _sanitize_filename
                filename = f"character_{_sanitize_filename(character_name)}.json"
                file_manager.save_json_content(uid, world_id, "characters", filename, character_data)
                logger.info(f"Updated character '{character_name}' default_voice via FileManager: {voice_url}")
            else:
                logger.warning(f"Character '{character_name}' not found in FileManager")
        except Exception as e:
            logger.error(f"Failed to update character default_voice by name: {e}")
    else:
        logger.warning(f"No character_id or character_name in task params, skipping update")

    return local_path


def _handle_face_mask_task_success(task: Any, result_url: str):
    """
    处理人脸遮盖视频任务成功的情况：
    1. 从 task.params 获取原视频路径
    2. 下载 RunningHub 返回的遮罩视频到本地缓存
    3. 将遮罩视频与原视频融合生成最终的人脸遮盖视频
    4. 返回融合后的视频路径（供 pipeline_processor 写入 step.result_url）

    Args:
        task: AsyncTask 对象
        result_url: RunningHub 远程遮罩视频 URL

    Returns:
        融合后的本地相对路径（无前导 /），失败返回 None
    """
    try:
        import os
        from utils.media_cache import download_and_cache
        from utils.face_mask_util import overlay_face_mask
        from utils.project_path import get_project_root, resolve_upload_url_to_local_path
        from datetime import datetime

        params = task.get_params_dict()
        original_video = params.get('video_path')  # 原视频路径

        if not original_video:
            logger.error("缺少 video_path 参数，无法融合视频")
            return None

        project_root = get_project_root()

        # Step 1: 下载遮罩视频和原视频到本地缓存
        loop = asyncio.new_event_loop()
        try:
            # 1a. 下载遮罩视频
            mask_video_local = loop.run_until_complete(
                download_and_cache(result_url, task.id, "video")
            )
            if not mask_video_local:
                logger.error("下载遮罩视频失败")
                return None
            mask_video_abs = os.path.join(project_root, mask_video_local.lstrip('/'))

            # 1b. 获取原视频本地路径
            if original_video.startswith('http://') or original_video.startswith('https://'):
                # 优先尝试本机 URL 映射（域名与 server.host 匹配时直接用本地文件，无需下载）
                from utils.image_upload_utils import try_map_url_to_local_file
                from config.config_util import get_config
                local_mapped = try_map_url_to_local_file(original_video, get_config(), project_root)
                if local_mapped and os.path.exists(local_mapped):
                    original_abs = local_mapped
                    logger.info(f"原视频映射到本地文件: {original_video} -> {original_abs}")
                else:
                    # CDN/远程 URL：路径映射不可靠（CDN 路径结构与本地不同），下载到缓存
                    original_local = loop.run_until_complete(
                        download_and_cache(original_video, task.id, "video")
                    )
                    if not original_local:
                        logger.error(f"原视频下载失败: {original_video}")
                        return None
                    original_abs = os.path.join(project_root, original_local.lstrip('/'))
            else:
                original_abs = resolve_upload_url_to_local_path(original_video)
        finally:
            loop.close()

        if not os.path.exists(original_abs):
            logger.error(f"原视频不存在: {original_abs}")
            return None

        # Step 2: 生成输出路径
        output_dir = os.path.join(project_root, "upload", "cache", datetime.now().strftime("%Y-%m-%d"))
        os.makedirs(output_dir, exist_ok=True)
        output_filename = f"face_mask_{task.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp4"
        output_video = os.path.join(output_dir, output_filename)

        # Step 3: 融合视频（原视频 + 遮罩 -> 最终视频）
        success, final_video, error = overlay_face_mask(
            original_video=original_abs,
            mask_video=mask_video_abs,
            output_video=output_video,
            mask_color=(0, 0, 0),  # 黑色遮罩
            mask_alpha=1.0,
            threshold=128
        )

        if not success or not final_video:
            logger.error(f"融合视频失败: {error}")
            return None

        # Step 4: 返回融合后的视频相对路径（如 upload/cache/2026-05-27/face_mask_xxx.mp4）
        rel_path = os.path.relpath(final_video, project_root).replace("\\", "/")
        logger.info(f"人脸遮盖视频融合成功: /{rel_path}")
        return rel_path

    except Exception as e:
        logger.error(f"处理人脸遮盖视频失败: {e}", exc_info=True)
        return None


def _handle_image_face_mask_task_success(task: Any, result_url: str):
    """
    处理图片人脸遮盖任务成功的情况：
    1. 下载 RunningHub 返回的图片到本地缓存
    2. 返回本地相对路径（供 pipeline_processor 写入 step.result_url）

    Args:
        task: AsyncTask 对象
        result_url: RunningHub 远程图片 URL

    Returns:
        本地相对路径（无前导 /），失败返回 None
    """
    try:
        from utils.media_cache import download_and_cache

        loop = asyncio.new_event_loop()
        try:
            local_url = loop.run_until_complete(
                download_and_cache(result_url, task.id, "image")
            )
        finally:
            loop.close()

        if not local_url:
            logger.error(f"下载图片人脸遮盖结果失败: {result_url}")
            return None

        rel_path = local_url.lstrip("/")
        logger.info(f"图片人脸遮盖结果缓存成功: /{rel_path}")
        return rel_path

    except Exception as e:
        logger.error(f"处理图片人脸遮盖结果失败: {e}", exc_info=True)
        return None


SUCCESS_HANDLER_MAP = {
    AsyncTaskImplementationId.RUNNINGHUB_AUDIO: _handle_audio_task_success,
    AsyncTaskImplementationId.RUNNINGHUB_FACE_MASK: _handle_face_mask_task_success,
    AsyncTaskImplementationId.RUNNINGHUB_IMAGE_FACE_MASK: _handle_image_face_mask_task_success,
}

# ⚠️ 后处理必须成功的实现方列表：audio 不在此列表（下载失败可回退到远程 URL），
# 但 face_mask 和 image_face_mask 必须成功（需要本地融合视频）。
# 如果 success_handler 返回 None，任务标记为 FAILED 而非回退。
POST_PROCESSING_REQUIRED = {
    AsyncTaskImplementationId.RUNNINGHUB_FACE_MASK: True,
    AsyncTaskImplementationId.RUNNINGHUB_IMAGE_FACE_MASK: True,
}


def process_runninghub_async_tasks(app=None):
    """
    处理 RunningHub 异步任务（在 scheduler 进程中定时执行）

    ⚠️ 此函数由 APScheduler 同步调度器调用，但内部创建 asyncio 事件循环来运行异步的
    driver.check_status()。每个 implementation 轮询创建一个新循环，结束后自动清理。

    流程：
    1. 遍历所有已注册的 RunningHub 实现（音频、人脸遮盖视频等）
    2. 对每个实现，获取 QUEUED/PROCESSING 状态的任务
    3. 调用对应 driver 的 check_status() 查询远程状态
    4. 根据结果更新数据库
    """
    import asyncio

    for impl_id, driver_class in DRIVER_MAP.items():
        try:
            pending_tasks = AsyncTasksModel.get_pending_tasks(
                implementation=impl_id,
                limit=50
            )

            if not pending_tasks:
                continue

            logger.info(f"开始处理 {len(pending_tasks)} 个 RunningHub 异步任务 (implementation={impl_id})")

            driver = driver_class()
            success_handler = SUCCESS_HANDLER_MAP.get(impl_id)

            loop = asyncio.new_event_loop()
            try:
                for task in pending_tasks:
                    try:
                        # 跳过尚未提交到外部 API 的任务（由调度器的提交流程负责）
                        if not task.external_task_id:
                            continue

                        # ===== E2E Mock 短路：跳过 success_handler（其内部 download 不识别本地路径，见方案 §5.8）=====
                        from task.mock_interceptor import is_mock_id, mock_audio, mock_video
                        if is_mock_id(task.external_task_id):
                            params = task.get_params_dict()
                            if impl_id == AsyncTaskImplementationId.RUNNINGHUB_AUDIO:
                                async_result_url = mock_audio("character_audio") or "/upload/mock/e2e_char.mp3"
                                # 替代 _handle_audio_task_success 的副作用：直接写角色 default_voice
                                character_id = params.get('character_id')
                                if character_id:
                                    try:
                                        from model.character import CharacterModel
                                        CharacterModel.update(character_id, default_voice=async_result_url)
                                    except Exception as e:
                                        logger.warning(f"[MOCK] set default_voice failed: {e}")
                            else:  # RUNNINGHUB_FACE_MASK：直接写 completed，跳过 overlay（见 §5.8）
                                async_result_url = mock_video("face_mask") or "/upload/mock/e2e_face_mask.mp4"
                            AsyncTasksModel.update_status(
                                record_id=task.id,
                                status=AsyncTaskStatus.COMPLETED,
                                result_url=async_result_url
                            )
                            RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_ASYNC)
                            logger.info(f"[MOCK] async poll short-circuit task={task.id} url={async_result_url}")
                            continue
                        # =====================================================================

                        AsyncTasksModel.increment_try_count(task.id)
                        task.try_count += 1

                        if task.try_count > task.max_attempts:
                            logger.error(f"RunningHub 异步任务超时: {task.id}, 尝试次数: {task.try_count}/{task.max_attempts}")
                            AsyncTasksModel.update_status(
                                record_id=task.id,
                                status=AsyncTaskStatus.TIMEOUT,
                                error_message=f"超过最大尝试次数 {task.max_attempts}"
                            )
                            RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_ASYNC)
                            continue

                        if task.try_count == 1:
                            AsyncTasksModel.update_status(
                                record_id=task.id,
                                status=AsyncTaskStatus.PROCESSING
                            )

                        # 多密钥轮换：轮询前根据任务记录的密钥 index 切换 driver client 密钥
                        # （错误密钥无法获取结果）
                        if hasattr(driver, '_apply_api_key_for_task'):
                            driver._apply_api_key_for_task(task)

                        status_result = loop.run_until_complete(driver.check_status(task.external_task_id))

                        if status_result.get('status') == 'SUCCESS':
                            result_url = status_result.get('result_url')

                            local_path = None
                            if success_handler:
                                local_path = success_handler(task, result_url)

                            # 后处理必须成功但返回 None → 标记 FAILED
                            if POST_PROCESSING_REQUIRED.get(impl_id) and local_path is None:
                                error_msg = f"任务后处理失败 (implementation={impl_id}), task_id={task.id}"
                                logger.error(error_msg)
                                AsyncTasksModel.update_status(
                                    record_id=task.id,
                                    status=AsyncTaskStatus.FAILED,
                                    error_message=error_msg
                                )
                                RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_ASYNC)
                            else:
                                async_result_url = f"/{local_path}" if local_path else result_url
                                AsyncTasksModel.update_status(
                                    record_id=task.id,
                                    status=AsyncTaskStatus.COMPLETED,
                                    result_url=async_result_url
                                )
                                RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_ASYNC)
                                logger.info(f"RunningHub 异步任务完成: {task.id}, result: {async_result_url}")

                        elif status_result.get('status') == 'FAILED':
                            error_message = status_result.get('error', '任务失败')
                            AsyncTasksModel.update_status(
                                record_id=task.id,
                                status=AsyncTaskStatus.FAILED,
                                error_message=error_message
                            )
                            RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_ASYNC)
                            logger.error(f"RunningHub 异步任务失败: {task.id}, error: {error_message}")

                    except Exception as e:
                        logger.error(f"处理 RunningHub 异步任务异常: {task.id}, error: {str(e)}")
            finally:
                loop.close()

        except Exception as e:
            logger.error(f"处理 RunningHub 异步任务失败 (implementation={impl_id}): {e}")
