"""
Grid Image Task Processing
宫格生图任务处理 - 在scheduler进程中轮询ComfyUI状态并更新数据库
"""
import os
import uuid
import logging
import requests
import urllib.parse
from datetime import datetime
from typing import Dict, Any
from model import GridImageTasksModel, GridImageTaskStatus
from script_writer_core.image_grid_splitter import ImageGridSplitter
from config.config_util import get_config
from utils.network_utils import is_local_file_path
from utils.project_path import get_project_root

logger = logging.getLogger(__name__)


def _download_and_store_image(file_url: str, item_type: int, comfyui_base_url: str) -> tuple:
    """
    下载并存储图片到本地，返回本地URL和文件路径
    
    Args:
        file_url: 图片URL
        item_type: 项目类型
        comfyui_base_url: ComfyUI基础URL
    
    Returns:
        (local_image_url, local_file_path) 元组
    """
    # 确定存储目录
    if item_type == 1:  # character
        upload_dir = 'upload/character/pic'
        local_url_path = 'upload/character/pic'
    elif item_type == 2:  # location
        upload_dir = 'upload/location/pic'
        local_url_path = 'upload/location/pic'
    elif item_type == 3:  # props
        upload_dir = 'upload/props/pic'
        local_url_path = 'upload/props/pic'
    elif item_type == 4:  # character_grid (角色四宫格)
        upload_dir = 'upload/character/temp'
        local_url_path = 'upload/character/temp'
    elif item_type == 5:  # location_grid (场景四宫格)
        upload_dir = 'upload/location/temp'
        local_url_path = 'upload/location/temp'
    elif item_type == 6:  # prop_grid (道具四宫格)
        upload_dir = 'upload/props/temp'
        local_url_path = 'upload/props/temp'
    else:
        raise Exception(f'无效的item_type: {item_type}')
    
    # 创建目录
    os.makedirs(upload_dir, exist_ok=True)
    
    # 生成文件名
    parsed_url = urllib.parse.urlparse(file_url)
    filename = os.path.basename(parsed_url.path)
    if not filename or not filename.lower().endswith(('.png', '.jpg', '.jpeg')):
        filename = f"generated_{uuid.uuid4().hex[:8]}.png"
    
    local_file_path = os.path.join(upload_dir, filename)

    # 检查是否为本地文件路径（如 /upload/cache/...）
    if is_local_file_path(file_url):
        # 本地路径，直接映射到文件系统
        # 安全检查：防止路径遍历攻击
        if ".." in file_url:
            raise Exception(f"不允许的路径序列: 路径中不能包含 '..'")
        if file_url.startswith("/"):
            file_url = file_url[1:]  # 移除开头的斜杠

        # 确保文件路径在允许的目录内
        base_dir = get_project_root()
        src_path = os.path.abspath(os.path.join(base_dir, file_url))

        # 验证路径在允许的目录内
        if not src_path.startswith(base_dir):
            raise Exception(f"不允许访问的路径: {src_path}")

        if os.path.exists(src_path):
            # 文件存在，复制到目标目录
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


def _update_task_status_file(item_type: int, item_name: str, status: str, user_id: str, world_id: str):
    """
    同步任务状态到文件系统
    
    Args:
        item_type: 项目类型
        item_name: 项目名称
        status: 状态
        user_id: 用户ID
        world_id: 世界观ID
    """
    try:
        from script_writer_core.cron_task_manager import get_task_manager
        task_manager = get_task_manager()
        task_manager.update_task_status(item_type, item_name, status, user_id, world_id)
    except Exception as e:
        logger.error(f"同步任务状态到文件失败: {e}")


def _handle_task_success(task: Any, comfyui_task_data: Dict):
    """
    处理任务成功的情况
    
    Args:
        task: GridImageTask对象
        comfyui_task_data: ComfyUI返回的任务数据
    """
    try:
        results = comfyui_task_data.get('results', [])
        if not results:
            raise Exception('图片生成完成但未返回结果')
        
        file_url = results[0].get('file_url', '')
        if not file_url:
            raise Exception('图片生成完成但未返回文件URL')
        
        # 默认关闭图片下载功能
        enable_image_download = get_config().get("image", {}).get("enable_download", False)
        
        if enable_image_download:
            # 启用图片下载和本地存储
            local_image_url, local_file_path = _download_and_store_image(
                file_url, task.item_type, task.comfyui_base_url
            )
        else:
            # 直接使用任务返回的图片地址
            local_image_url = file_url
            local_file_path = None
        
        # 检查是否为4宫格类型，需要进行图片拆分
        is_grid_type = task.item_type in [4, 5, 6]  # 4=character_grid, 5=location_grid, 6=prop_grid
        split_image_urls = []
        
        if is_grid_type and enable_image_download and local_file_path:
            # 4宫格图片需要拆分
            try:
                # 解析item_name（格式："name1,name2,name3,name4"）
                item_names = [name.strip() for name in task.item_name.split(',')]
                
                if len(item_names) == 4:
                    # 创建拆分器
                    splitter = ImageGridSplitter()
                    
                    # 根据item_type确定输出目录（存储到pic目录，而不是temp目录）
                    if task.item_type == 4:  # character_grid
                        output_dir = 'upload/character/pic'
                    elif task.item_type == 5:  # location_grid
                        output_dir = 'upload/location/pic'
                    elif task.item_type == 6:  # prop_grid
                        output_dir = 'upload/props/pic'
                    else:
                        output_dir = os.path.dirname(local_file_path)
                    
                    # 确保输出目录存在
                    os.makedirs(output_dir, exist_ok=True)
                    
                    # 生成唯一的文件名（使用UUID避免重复）
                    unique_names = [str(uuid.uuid4()) for _ in range(4)]
                    
                    # 拆分图片
                    split_paths = splitter.split_2x2_grid(
                        grid_image_path=local_file_path,
                        output_dir=output_dir,
                        output_names=unique_names,
                        output_format="png"
                    )
                    
                    # 构建拆分后图片的URL
                    config_comfyui_base_url = get_config()["server"]["host"]
                    
                    for split_path in split_paths:
                        # 获取文件名，使用预定义的 output_dir 构建 URL
                        filename = os.path.basename(split_path)
                        split_url = f"{config_comfyui_base_url.rstrip('/')}/{output_dir}/{filename}"
                        split_image_urls.append(split_url)
                    
                    logger.info(f"4宫格图片拆分成功: {len(split_paths)} 张图片")
                else:
                    logger.warning(f"4宫格item_name格式不正确，期望4个名称，实际: {len(item_names)}")
            except Exception as e:
                logger.error(f"4宫格图片拆分失败: {str(e)}")
        
        # 更新对应的item
        update_success = False
        try:
            import importlib
            mcp_tool = importlib.import_module('script_writer_core.mcp_tool')
            
            if task.item_type == 1:  # character
                result = mcp_tool.update_character_json(task.user_id, task.world_id, task.auth_token, 
                                                       task.item_name, reference_image=local_image_url)
                update_success = result.get('success', False)
            elif task.item_type == 2:  # location
                result = mcp_tool.update_location_json(task.user_id, task.world_id, task.auth_token, 
                                                      task.item_name, reference_image=local_image_url)
                update_success = result.get('success', False)
            elif task.item_type == 3:  # props
                result = mcp_tool.update_prop_json(task.user_id, task.world_id, task.auth_token, 
                                                   task.item_name, reference_image=local_image_url)
                update_success = result.get('success', False)
            elif task.item_type == 4:  # character_grid (4宫格角色)
                item_names = [name.strip() for name in task.item_name.split(',')]
                if len(item_names) == 4 and len(split_image_urls) == 4:
                    for idx, (name, img_url) in enumerate(zip(item_names, split_image_urls)):
                        result = mcp_tool.update_character_json(task.user_id, task.world_id, task.auth_token, 
                                                               name, reference_image=img_url)
                        if result.get('success', False):
                            logger.info(f"已更新角色 {name} 的参考图")
                    update_success = True
            elif task.item_type == 5:  # location_grid (4宫格场景)
                item_names = [name.strip() for name in task.item_name.split(',')]
                if len(item_names) == 4 and len(split_image_urls) == 4:
                    for idx, (name, img_url) in enumerate(zip(item_names, split_image_urls)):
                        result = mcp_tool.update_location_json(task.user_id, task.world_id, task.auth_token, 
                                                              name, reference_image=img_url)
                        if result.get('success', False):
                            logger.info(f"已更新场景 {name} 的参考图")
                    update_success = True
            elif task.item_type == 6:  # prop_grid (4宫格道具)
                item_names = [name.strip() for name in task.item_name.split(',')]
                if len(item_names) == 4 and len(split_image_urls) == 4:
                    for idx, (name, img_url) in enumerate(zip(item_names, split_image_urls)):
                        result = mcp_tool.update_prop_json(task.user_id, task.world_id, task.auth_token, 
                                                          name, reference_image=img_url)
                        if result.get('success', False):
                            logger.info(f"已更新道具 {name} 的参考图")
                    update_success = True
        except Exception as e:
            logger.error(f"更新item失败: {str(e)}")
            update_success = False
        
        # 更新数据库任务状态
        GridImageTasksModel.update_status(
            task_key=task.task_key,
            status=GridImageTaskStatus.COMPLETED,
            result_url=local_image_url,
            local_file_path=local_file_path,
            update_success=1 if update_success else 0
        )
        
        # 同步完成状态到文件
        _update_task_status_file(task.item_type, task.item_name, 'completed', task.user_id, task.world_id)
        
        logger.info(f"宫格生图任务完成: {task.task_key}")
        
    except Exception as e:
        logger.error(f"处理任务成功逻辑失败: {str(e)}")
        # 更新为下载失败状态
        GridImageTasksModel.update_status(
            task_key=task.task_key,
            status=GridImageTaskStatus.DOWNLOAD_FAILED,
            error_message=str(e)
        )
        _update_task_status_file(task.item_type, task.item_name, 'failed', task.user_id, task.world_id)


def process_grid_image_tasks(app=None):
    """
    处理宫格生图任务（在scheduler进程中定时执行）
    
    Args:
        app: FastAPI应用实例（保持与其他任务处理函数签名一致）
    """
    try:
        # 获取待处理的任务
        pending_tasks = GridImageTasksModel.get_pending_tasks(limit=50)
        
        if not pending_tasks:
            return
        
        logger.info(f"开始处理 {len(pending_tasks)} 个宫格生图任务")
        
        for task in pending_tasks:
            try:
                # 增加尝试次数
                GridImageTasksModel.increment_try_count(task.task_key)
                task.try_count += 1
                
                # 检查是否超过最大尝试次数
                if task.try_count > task.max_attempts:
                    logger.error(f"任务超时: {task.task_key}, 尝试次数: {task.try_count}/{task.max_attempts}")
                    GridImageTasksModel.update_status(
                        task_key=task.task_key,
                        status=GridImageTaskStatus.TIMEOUT,
                        error_message=f"超过最大尝试次数 {task.max_attempts}"
                    )
                    _update_task_status_file(task.item_type, task.item_name, 'timeout', 
                                           task.user_id, task.world_id)
                    continue
                
                # 更新为处理中状态（仅在第一次尝试时）
                if task.try_count == 1:
                    GridImageTasksModel.update_status(
                        task_key=task.task_key,
                        status=GridImageTaskStatus.PROCESSING
                    )
                    _update_task_status_file(task.item_type, task.item_name, 'running', 
                                           task.user_id, task.world_id)
                
                # 检查ComfyUI任务状态
                status_url = f"{task.comfyui_base_url.rstrip('/')}/api/get-status/{task.project_id}"
                response = requests.get(f"{status_url}?auth_token={task.auth_token}", timeout=10)
                response.raise_for_status()
                
                status_data = response.json()
                if 'tasks' not in status_data or not status_data['tasks']:
                    continue  # 继续等待
                
                comfyui_task = status_data['tasks'][0]
                task_status = comfyui_task.get('status', '')
                
                if task_status == 'SUCCESS':
                    # 图片生成成功
                    _handle_task_success(task, comfyui_task)
                elif task_status == 'FAILED':
                    # 图片生成失败
                    failure_reason = comfyui_task.get('reason', '生成失败')
                    logger.error(f"ComfyUI任务失败: {task.task_key}, 原因: {failure_reason}")
                    GridImageTasksModel.update_status(
                        task_key=task.task_key,
                        status=GridImageTaskStatus.FAILED,
                        error_message=failure_reason
                    )
                    _update_task_status_file(task.item_type, task.item_name, 'failed', 
                                           task.user_id, task.world_id)
                
            except requests.RequestException as e:
                # 网络请求异常，记录但不更新状态（继续重试）
                logger.warning(f"轮询ComfyUI失败: {task.task_key}, 错误: {str(e)}")
            except Exception as e:
                # 其他异常，标记为失败
                logger.error(f"处理任务异常: {task.task_key}, 错误: {str(e)}")
                GridImageTasksModel.update_status(
                    task_key=task.task_key,
                    status=GridImageTaskStatus.FAILED,
                    error_message=str(e)
                )
                _update_task_status_file(task.item_type, task.item_name, 'failed', 
                                       task.user_id, task.world_id)
        
        # 清理旧任务（7天前的已完成/失败任务）
        try:
            GridImageTasksModel.cleanup_old_tasks(days=7)
        except Exception as e:
            logger.error(f"清理旧任务失败: {e}")
            
    except Exception as e:
        logger.error(f"处理宫格生图任务失败: {e}")
