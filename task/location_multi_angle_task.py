"""
Location Multi-Angle Task Processing
场景多角度生图任务处理 - 在scheduler进程中轮询任务并生成多角度图片
"""
import os
import json
import uuid
import logging
import requests
import urllib.parse
from datetime import datetime
from typing import Dict, Any, List
from model import LocationMultiAngleTasksModel, LocationMultiAngleTask, LocationMultiAngleTaskStatus
from model.ai_tools import AIToolsModel
from config.config_util import get_config
from config.constant import AI_TOOL_STATUS_COMPLETED, AI_TOOL_STATUS_FAILED
from utils.network_utils import is_local_file_path
from utils.project_path import get_project_root

logger = logging.getLogger(__name__)


def _download_and_store_image(file_url: str, comfyui_base_url: str) -> tuple:
    """
    下载并存储图片到本地，返回本地URL和文件路径

    Args:
        file_url: 图片URL
        comfyui_base_url: ComfyUI基础URL

    Returns:
        (local_image_url, local_file_path) 元组
    """
    # 存储目录
    upload_dir = 'upload/location/pic'
    local_url_path = 'upload/location/pic'

    # 创建目录
    os.makedirs(upload_dir, exist_ok=True)

    # 生成文件名
    parsed_url = urllib.parse.urlparse(file_url)
    filename = os.path.basename(parsed_url.path)
    if not filename or not filename.lower().endswith(('.png', '.jpg', '.jpeg')):
        filename = f"multi_angle_{uuid.uuid4().hex[:8]}.png"

    local_file_path = f"{upload_dir}/{filename}"

    # 检查是否为本地文件路径
    if is_local_file_path(file_url):
        if ".." in file_url:
            raise Exception(f"不允许的路径序列: 路径中不能包含 '..'")
        if file_url.startswith("/"):
            file_url = file_url[1:]

        base_dir = get_project_root()
        src_path = os.path.abspath(os.path.join(base_dir, file_url))

        if not src_path.startswith(base_dir):
            raise Exception(f"不允许访问的路径: {src_path}")

        if os.path.exists(src_path):
            import shutil
            shutil.copy2(src_path, local_file_path)
            logger.info(f"本地文件已复制: {src_path} -> {local_file_path}")
        else:
            raise Exception(f"本地文件不存在: {src_path}")
    else:
        # 远程URL，正常下载
        img_response = requests.get(file_url, timeout=30)
        img_response.raise_for_status()

        with open(local_file_path, 'wb') as f:
            f.write(img_response.content)

    config_comfyui_base_url = get_config()["server"]["host"]
    local_image_url = f"{config_comfyui_base_url.rstrip('/')}/{local_url_path}/{filename}"

    return local_image_url, local_file_path


def _get_direction_prompt_from_angle(angle: int) -> str:
    """根据角度获取方向描述"""
    if angle >= 337.5 or angle < 22.5:
        return 'front view'
    elif angle >= 22.5 and angle < 67.5:
        return 'front-right quarter view'
    elif angle >= 67.5 and angle < 112.5:
        return 'right side view'
    elif angle >= 112.5 and angle < 157.5:
        return 'back-right quarter view'
    elif angle >= 157.5 and angle < 202.5:
        return 'back view'
    elif angle >= 202.5 and angle < 247.5:
        return 'back-left quarter view'
    elif angle >= 247.5 and angle < 292.5:
        return 'left side view'
    else:
        return 'front-left quarter view'


def _update_reference_images_to_staging(task: LocationMultiAngleTask, generated_images: List[Dict[str, Any]]) -> bool:
    """
    更新 reference_images 到暂存区

    Args:
        task: 任务对象
        generated_images: 已生成的图片列表

    Returns:
        是否更新成功
    """
    try:
        # 读取现有的 reference_images
        from script_writer_core.file_manager import FileManager
        file_manager = FileManager()
        safe_name = task.location_name  # 假设 location_name 已经是安全的
        filename = f"location_{safe_name}.json"
        file_path = file_manager.get_content_file_path(task.user_id, task.world_id, "locations", filename)

        existing_data = {}
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)

        # 合并现有的和新生成的 reference_images
        existing_refs = existing_data.get('reference_images', [])
        if isinstance(existing_refs, str):
            try:
                existing_refs = json.loads(existing_refs)
            except:
                existing_refs = []

        # 用 URL 作为唯一标识，避免重复
        existing_urls = {img.get('url') for img in existing_refs if img.get('url')}
        added_count = 0
        for new_img in generated_images:
            if new_img.get('url') not in existing_urls:
                existing_refs.append(new_img)
                existing_urls.add(new_img.get('url'))
                added_count += 1
                logger.info(f"添加新图片到暂存区: angle={new_img.get('angle')}, url={new_img.get('url')}")

        if added_count == 0:
            logger.warning(f"没有新图片需要添加到暂存区（可能已存在）")
            return True

        # 更新 reference_images
        existing_data['reference_images'] = existing_refs
        existing_data['updated_at'] = datetime.now().isoformat()

        # 保存
        logger.info(f"准备保存场景 {task.location_name} 的 JSON 文件，当前 reference_images 数量: {len(existing_refs)}")
        success = file_manager.save_json_content(task.user_id, task.world_id, "locations", filename, existing_data)

        if success:
            logger.info(f"✓ 已成功更新场景 {task.location_name} 的 reference_images 到暂存区（新增 {added_count} 张）")
        else:
            logger.error(f"✗ 保存场景 {task.location_name} 暂存区失败")

        return success

    except Exception as e:
        logger.error(f"更新暂存区失败: {e}")
        return False


def process_location_multi_angle_task(task_key: str) -> Dict[str, Any]:
    """
    处理单个场景多角度生图任务（非阻塞模式）

    每次调用只处理一个角度：
    1. 如果有正在等待的 ai_tool_task_id，检查是否完成
    2. 如果完成，处理结果并提交下一个角度
    3. 如果没有正在等待的任务，提交当前角度

    Args:
        task_key: 任务唯一键

    Returns:
        处理结果
    """
    try:
        # 获取任务
        task = LocationMultiAngleTasksModel.get_by_task_key(task_key)
        if not task:
            return {'success': False, 'error': f'任务 {task_key} 不存在'}

        # 获取角度列表
        angles = task.get_angles_list()
        if not angles:
            LocationMultiAngleTasksModel.update_status(
                task_key, LocationMultiAngleTaskStatus.FAILED,
                error_message='没有需要生成的角度'
            )
            return {'success': False, 'error': '没有需要生成的角度'}

        current_index = task.current_angle_index
        generated_images = task.get_generated_images_list()

        # 检查是否已完成所有角度
        if current_index >= len(angles):
            if task.status != LocationMultiAngleTaskStatus.COMPLETED:
                LocationMultiAngleTasksModel.update_status(
                    task_key,
                    LocationMultiAngleTaskStatus.COMPLETED,
                    generated_images=generated_images
                )
            logger.info(f"任务 {task_key} 已完成所有角度")
            return {'success': True, 'completed': True, 'generated_images': generated_images}

        # 标记为处理中
        if task.status == LocationMultiAngleTaskStatus.QUEUED:
            LocationMultiAngleTasksModel.update_status(
                task_key, LocationMultiAngleTaskStatus.PROCESSING
            )

        config = get_config()
        comfyui_base_url = config["server"]["host"]

        # 检查是否有正在等待的 AI 任务
        if task.ai_tool_task_id:
            logger.info(f"检查正在等待的 AI 任务: {task.ai_tool_task_id}")
            ai_tool = AIToolsModel.get_by_id(task.ai_tool_task_id)

            if ai_tool:
                if ai_tool.status == AI_TOOL_STATUS_COMPLETED:
                    # AI 任务完成，处理结果
                    image_url = ai_tool.result_url
                    logger.info(f"角度 {current_index} 生成完成，result_url={image_url}")

                    # 获取当前角度信息
                    angle_info = angles[current_index]
                    angle_key = angle_info.get('angleKey', 'unknown')
                    label = angle_info.get('label', f"{angle_info.get('angle', 0)}°")

                    # 下载并存储图片
                    try:
                        local_image_url, local_file_path = _download_and_store_image(image_url, comfyui_base_url)
                    except Exception as download_err:
                        logger.warning(f"下载图片失败，使用原始URL: {download_err}")
                        local_image_url = image_url
                        local_file_path = None

                    # 添加到已生成列表
                    new_image = {
                        'angle': angle_key,
                        'label': label,
                        'url': local_image_url,
                        'local_file_path': local_file_path
                    }
                    generated_images.append(new_image)
                    logger.info(f"成功生成 {label}: {local_image_url}")

                    # 更新暂存区
                    _update_reference_images_to_staging(task, [new_image])

                    # 更新进度，清除 ai_tool_task_id
                    current_index += 1
                    LocationMultiAngleTasksModel.update_status(
                        task_key,
                        LocationMultiAngleTaskStatus.PROCESSING,
                        current_angle_index=current_index,
                        generated_images=generated_images,
                        ai_tool_task_id=0  # 清除
                    )

                    # 检查是否全部完成
                    if current_index >= len(angles):
                        LocationMultiAngleTasksModel.update_status(
                            task_key,
                            LocationMultiAngleTaskStatus.COMPLETED,
                            generated_images=generated_images
                        )
                        logger.info(f"场景 {task.location_name} 多角度生图任务全部完成，共 {len(generated_images)} 张图片")
                        return {'success': True, 'completed': True, 'generated_images': generated_images}

                    # 继续提交下一个角度（不用 return，继续执行下面的代码）
                    task = LocationMultiAngleTasksModel.get_by_task_key(task_key)  # 重新获取更新后的任务

                elif ai_tool.status == AI_TOOL_STATUS_FAILED:
                    # AI 任务失败，跳过这个角度
                    logger.error(f"角度 {current_index} 生成失败: {ai_tool.message}")
                    current_index += 1
                    LocationMultiAngleTasksModel.update_status(
                        task_key,
                        LocationMultiAngleTaskStatus.PROCESSING,
                        current_angle_index=current_index,
                        ai_tool_task_id=0  # 清除
                    )

                    if current_index >= len(angles):
                        LocationMultiAngleTasksModel.update_status(
                            task_key,
                            LocationMultiAngleTaskStatus.COMPLETED,
                            generated_images=generated_images,
                            error_message=f'部分角度生成失败，共完成 {len(generated_images)}/{len(angles)} 个'
                        )
                        return {'success': True, 'completed': True, 'generated_images': generated_images}

                    task = LocationMultiAngleTasksModel.get_by_task_key(task_key)
                else:
                    # 仍在处理中，等待下次调度
                    logger.info(f"角度 {current_index} 仍在生成中，等待下次调度")
                    return {'success': True, 'waiting': True, 'ai_tool_task_id': task.ai_tool_task_id}
            else:
                # ai_tool 不存在，清除并重新提交
                logger.warning(f"AI 任务 {task.ai_tool_task_id} 不存在，重新提交")
                LocationMultiAngleTasksModel.update_status(
                    task_key,
                    LocationMultiAngleTaskStatus.PROCESSING,
                    ai_tool_task_id=0
                )
                task = LocationMultiAngleTasksModel.get_by_task_key(task_key)

        # 如果没有正在等待的任务，提交当前角度
        current_index = task.current_angle_index
        if current_index >= len(angles):
            return {'success': True, 'completed': True, 'generated_images': generated_images}

        angle_info = angles[current_index]
        angle = angle_info.get('angle', 0)
        label = angle_info.get('label', f'{angle}°')
        angle_key = angle_info.get('angleKey', 'unknown')

        logger.info(f"提交场景 {task.location_name} 的 {label} (angle={angle})")

        # 获取 qwen-multi-angle 任务的 task_id
        from config.unified_config import UnifiedConfigRegistry
        multi_angle_config = UnifiedConfigRegistry.get_by_key('qwen-multi-angle')
        if not multi_angle_config:
            logger.error("无法获取 qwen-multi-angle 任务配置")
            LocationMultiAngleTasksModel.update_status(
                task_key, LocationMultiAngleTaskStatus.FAILED,
                error_message='无法获取多角度生成任务配置'
            )
            return {'success': False, 'error': '无法获取多角度生成任务配置'}

        task_id = multi_angle_config.id

        # 构建提示词
        direction_prompt = _get_direction_prompt_from_angle(angle)
        prompt = f"<sks> {direction_prompt} eye-level shot medium shot"

        # 调用 /api/image-edit 接口
        extra_config = {
            'horizontal_angle': angle,
            'vertical_angle': 0,
            'zoom': 5.0
        }

        try:
            form_data = {
                'task_id': task_id,
                'ref_image_urls': task.main_image,
                'prompt': prompt,
                'extra_config': json.dumps(extra_config),
                'model': task.model or '',
                'user_id': task.user_id,
                'auth_token': task.auth_token or ''
            }

            response = requests.post(
                f"{comfyui_base_url}/api/image-edit",
                data=form_data,
                timeout=120
            )

            result = response.json()

            if result.get('status') == 'submitted' and result.get('project_ids'):
                project_id = result['project_ids'][0] if result['project_ids'] else None

                if project_id:
                    logger.info(f"已提交 {label} 生成任务，project_id={project_id}")
                    # 记录 ai_tool_task_id，等待下次调度检查
                    LocationMultiAngleTasksModel.update_status(
                        task_key,
                        LocationMultiAngleTaskStatus.PROCESSING,
                        ai_tool_task_id=project_id
                    )
                    return {'success': True, 'submitted': True, 'project_id': project_id}
                else:
                    logger.error(f"生成 {label} 失败: 未返回 project_id")
                    return {'success': False, 'error': '未返回 project_id'}
            else:
                error_msg = result.get('error', '未知错误')
                logger.error(f"生成 {label} 失败: {error_msg}")
                return {'success': False, 'error': error_msg}

        except Exception as e:
            logger.error(f"提交角度 {angle} 时发生异常: {e}")
            return {'success': False, 'error': str(e)}

    except Exception as e:
        logger.error(f"处理任务 {task_key} 时发生异常: {e}")
        import traceback
        logger.error(traceback.format_exc())

        try:
            LocationMultiAngleTasksModel.update_status(
                task_key,
                LocationMultiAngleTaskStatus.FAILED,
                error_message=str(e)
            )
        except:
            pass

        return {'success': False, 'error': str(e)}


def process_pending_location_multi_angle_tasks():
    """
    处理所有待处理的场景多角度生图任务 - 供调度器调用
    """
    try:
        pending_tasks = LocationMultiAngleTasksModel.get_pending_tasks(limit=5)

        if not pending_tasks:
            return

        logger.info(f"发现 {len(pending_tasks)} 个待处理的场景多角度生图任务")

        for task in pending_tasks:
            logger.info(f"开始处理任务: {task.task_key}")
            result = process_location_multi_angle_task(task.task_key)
            logger.info(f"任务 {task.task_key} 处理结果: {result}")

    except Exception as e:
        logger.error(f"处理待处理任务时发生异常: {e}")
        import traceback
        logger.error(traceback.format_exc())
