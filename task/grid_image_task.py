"""
Grid Image Task Processing
宫格生图任务处理 - 在scheduler进程中轮询ComfyUI状态并更新数据库
"""
import os
import uuid
import logging
import asyncio
import json
import requests
import urllib.parse
import httpx
from datetime import datetime
from typing import Dict, Any
from model import GridImageTasksModel, GridImageTaskStatus, AIToolsModel
from config.constant import AI_TOOL_STATUS_WAITING_BEFORE_FINISH, MediaConstants, GridConfig, StoryboardAutoGenerateConstants
from script_writer_core.image_grid_splitter import ImageGridSplitter
from config.config_util import get_config
from utils.network_utils import is_local_file_path
from utils.project_path import get_project_root
from utils.image_grid_validator import validate_grid_image
from script_writer_core.constant import ItemType

logger = logging.getLogger(__name__)


def _build_storyboard_grid_cells(task: Any, grid_size: int) -> list:
    """Build cell bindings for legacy first-frame grid tasks without pipeline params."""
    try:
        item_names = task.get_item_names_list()
    except Exception:
        item_names = [name.strip() for name in (task.item_name or '').split(',')]
    try:
        scene_ids = task.get_target_entity_ids_list()
    except Exception:
        scene_ids = []

    scene_id_iter = iter(scene_ids)
    cells = []
    for index in range(grid_size):
        name = item_names[index] if index < len(item_names) else "placeholder"
        is_placeholder = GridConfig.is_placeholder(name)
        scene_id = None if is_placeholder else next(scene_id_iter, None)
        cells.append(
            {
                "grid_index": index,
                "scene_id": scene_id,
                "batch_item_id": None,
                "placeholder": is_placeholder or scene_id is None,
            }
        )
    return cells


def _dispatch_storyboard_first_frame_grid_split(
    task: Any,
    local_image_url: str,
    local_file_path: str,
    grid_size: int,
) -> bool:
    """Dispatch the storyboard first-frame grid split pipeline step."""
    try:
        ai_tool_id = int(task.project_id)
    except (TypeError, ValueError):
        logger.error("分镜首帧宫格缺少可用 ai_tool_id: task_key=%s project_id=%s", task.task_key, task.project_id)
        return False

    try:
        from model.ai_tool_pipeline_steps import PipelineStage, PipelineStepModel, PipelineStepType
        from task.pipeline_processor import PipelineProcessor

        AIToolsModel.update(ai_tool_id, result_url=local_image_url)

        # 组装当前宫格的完整 params（fallback 新建与预建 step 校准共用）。
        # 重试后 grid_image_path/grid_result_url/cells 可能已变化，必须用最新值覆盖。
        full_params = {
            "grid_task_id": int(task.id),
            "grid_size": grid_size,
            "grid_layout": getattr(task, "grid_layout", None) or ("2x2" if grid_size == GridConfig.SIZE_2X2 else "3x3"),
            "asset_type": "first_frame",
            "output_dir": "upload/storyboard/first_frame",
            "output_url_path": "upload/storyboard/first_frame",
            "grid_image_path": local_file_path,
            "grid_result_url": local_image_url,
            "cells": _build_storyboard_grid_cells(task, grid_size),
        }

        # 按 grid_image_tasks.id 主键查找预建 step（稳定，不受 project_id 漂移影响）。
        # 旧逻辑用 get_pending_steps(task.project_id) 查找，但宫格重试会令 project_id
        # 漂移为新 ai_tool_id，导致找不到预建 step 而 fallback 新建，原 step 沦为僵尸。
        step = PipelineStepModel.get_pending_grid_split_step_by_grid_task(int(task.id))
        if step:
            # 校准预建 step：原子更新 params（重试后最新宫格图数据）+ ai_tool_id（校正漂移，
            # 使 dispatch_step 加载到 result_url 指向最新宫格图的 ai_tool）。随后必须重新读取
            # step 对象，否则内存里的 params/ai_tool_id 仍是旧值，driver 会拆到旧宫格图。
            PipelineStepModel.update_params(step.id, full_params, ai_tool_id=ai_tool_id)
            step = PipelineStepModel.get_by_id(step.id)
        else:
            step_id = PipelineStepModel.create(
                ai_tool_id=ai_tool_id,
                stage=PipelineStage.BEFORE_FINISH,
                step_type=PipelineStepType.STORYBOARD_FIRST_FRAME_GRID_SPLIT,
                step_order=0,
                params=full_params,
                target=task.task_key,
            )
            step = PipelineStepModel.get_by_id(step_id)
        if not step:
            logger.error("分镜首帧宫格 pipeline step 创建后仍无法读取: task_key=%s", task.task_key)
            return False
        return bool(asyncio.run(PipelineProcessor.dispatch_step(step)))
    except Exception as exc:
        logger.error("分镜首帧宫格 pipeline 分发失败: task_key=%s err=%s", task.task_key, exc, exc_info=True)
        return False


def _grid_validation_max_retries(task: Any) -> int:
    max_retries = _safe_int(getattr(task, "max_retries", 0), default=0)
    if task.item_type == ItemType.STORYBOARD_FIRST_FRAME_GRID:
        return GridConfig.STORYBOARD_FIRST_FRAME_VALIDATION_MAX_RETRIES
    return max_retries


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mark_storyboard_grid_batch_items_failed(task: Any, error_message: str) -> None:
    if task.item_type != ItemType.STORYBOARD_FIRST_FRAME_GRID:
        return
    try:
        from model.storyboard_image_batch import StoryboardImageBatchItemModel

        for scene_id in task.get_target_entity_ids_list():
            try:
                batch_item = StoryboardImageBatchItemModel.find_running_by_grid_task(
                    int(task.id),
                    int(scene_id),
                )
                if not batch_item:
                    continue
                extra = batch_item.get("extra_json") if isinstance(batch_item.get("extra_json"), dict) else {}
                StoryboardImageBatchItemModel.update(
                    int(batch_item["id"]),
                    status=StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
                    error_code=StoryboardAutoGenerateConstants.ERROR_GRID_FIRST_FRAME_FAILED,
                    error_message=error_message[:512],
                    extra_json={
                        **extra,
                        "grid_validation_failed": True,
                        "grid_validation_error": error_message[:512],
                    },
                )
            except Exception as item_err:
                logger.error(
                    "标记分镜首帧宫格 batch item 失败时出错: grid_task_id=%s scene_id=%s err=%s",
                    getattr(task, "id", None),
                    scene_id,
                    item_err,
                    exc_info=True,
                )
    except Exception as exc:
        logger.error("分镜首帧宫格 batch item 失败回写整体异常: %s", exc, exc_info=True)

    # 同步终止绑定的 pipeline step，避免其永久卡在 PENDING 被全局调度器反复 skip 刷日志。
    # 该函数已被超时/ComfyUI FAILED/异常/几何校验失败 四条失败路径调用，在此集中回写即可全覆盖。
    _fail_pending_grid_split_step_for_task(task, error_message)


def _fail_pending_grid_split_step_for_task(task: Any, error_message: str) -> None:
    """将 task 绑定的仍 PENDING 的 storyboard grid split pipeline step 标记为 FAILED。"""
    if task.item_type != ItemType.STORYBOARD_FIRST_FRAME_GRID:
        return
    # 按 grid_image_tasks.id 主键回写（稳定，不受 project_id 漂移影响）。
    # 旧逻辑用 task.project_id 查找，但宫格重试会令 project_id 漂移为新 ai_tool_id，
    # 导致找不到预建 step 而回写失效，step 沦为僵尸。
    grid_task_id = getattr(task, "id", None)
    try:
        grid_task_id = int(grid_task_id)
    except (TypeError, ValueError):
        logger.error(
            "回写分镜首帧宫格 pipeline step 失败：缺少可用 grid_task_id, task_key=%s id=%s",
            getattr(task, "task_key", None), grid_task_id,
        )
        return
    try:
        from model.ai_tool_pipeline_steps import PipelineStepModel

        PipelineStepModel.fail_pending_grid_split_step_by_grid_task(grid_task_id, error_message)
    except Exception as exc:
        logger.error(
            "回写分镜首帧宫格 pipeline step 失败: grid_task_id=%s err=%s",
            grid_task_id, exc, exc_info=True,
        )


def _handle_grid_validation_failure(task: Any, validation: Any) -> bool:
    reason = getattr(validation, "reason", "invalid grid image")
    confidence = getattr(validation, "confidence", 0.0)
    error_message = f"宫格图片几何校验失败: {reason}; confidence={confidence:.2f}"
    retry_count = getattr(task, "retry_count", 0) or 0
    max_retries = _grid_validation_max_retries(task)

    if retry_count < max_retries and getattr(task, "prompt", None) and getattr(task, "task_config_id", None):
        logger.info(
            "宫格校验失败，准备重试: task_key=%s retry=%s/%s reason=%s",
            task.task_key,
            retry_count + 1,
            max_retries,
            reason,
        )
        new_project_id = _resubmit_image_request(task)
        if new_project_id:
            GridImageTasksModel.reset_for_retry(task.task_key, new_project_id)
            _update_task_status_file(task.item_type, task.item_name, "retrying", task.user_id, task.world_id)
            return True
        error_message = f"{error_message}; 重试提交失败"

    GridImageTasksModel.update_status(
        task_key=task.task_key,
        status=GridImageTaskStatus.FAILED,
        error_message=error_message,
    )
    _mark_storyboard_grid_batch_items_failed(task, error_message)
    _update_task_status_file(task.item_type, task.item_name, "failed", task.user_id, task.world_id)
    return True


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
    # ⚠️ item_type 魔数映射（与 script_writer_core/constant.py ItemType 对应）：
    #   0=营销通用, 1=角色, 2=场景, 3=道具, 4=角色四宫格, 5=场景四宫格, 6=道具四宫格,
    #   7=角色变体图, 8=分镜首帧宫格
    #   四宫格类型(4/5/6)存入 temp 目录（后续会被拆分），单图类型存入 pic 目录
    if item_type == 0:  # 通用生图（营销等场景）
        upload_dir = 'upload/marketing/pic'
        local_url_path = 'upload/marketing/pic'
    elif item_type == 1:  # character
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
    elif item_type == 7:  # character_variant (角色变体图)
        upload_dir = 'upload/character/pic'
        local_url_path = 'upload/character/pic'
    elif item_type == ItemType.STORYBOARD_FIRST_FRAME_GRID:
        upload_dir = 'upload/storyboard/temp'
        local_url_path = 'upload/storyboard/temp'
    else:
        raise Exception(f'无效的item_type: {item_type}')
    
    # 创建目录
    os.makedirs(upload_dir, exist_ok=True)
    
    # 生成文件名
    parsed_url = urllib.parse.urlparse(file_url)
    filename = os.path.basename(parsed_url.path)
    if not filename or not filename.lower().endswith(MediaConstants.ALLOWED_IMAGE_EXTENSIONS):
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


def _resubmit_image_request(task) -> str:
    """
    重新提交图片生成请求到 ComfyUI，返回新的 project_id
    
    Args:
        task: GridImageTask对象（必须包含 prompt, task_config_id, comfyui_base_url, auth_token, user_id）
    
    Returns:
        新的 project_id，失败返回 None
    """
    # ===== E2E Mock 短路 =====
    from task.mock_interceptor import is_mock_enabled, generate_mock_project_id
    if is_mock_enabled():
        return generate_mock_project_id()
    # =========================

    if not task.prompt or not task.task_config_id:
        logger.warning(f"任务 {task.task_key} 缺少 prompt 或 task_config_id，无法重试")
        return None
    
    try:
        reference_images = _parse_reference_images(getattr(task, "reference_images", None))
        if reference_images:
            from script_writer_core.mcp_tool import _to_public_http_url

            public_ref_urls = []
            for ref in reference_images:
                raw_url = ref.get("url") if isinstance(ref, dict) else ref
                public_url = _to_public_http_url(raw_url, task.comfyui_base_url) if raw_url else None
                if public_url:
                    public_ref_urls.append(public_url)
            if not public_ref_urls:
                logger.warning("任务 %s 缺少可用 reference_images，无法按 image-edit 重试", task.task_key)
                return None
            api_url = f"{task.comfyui_base_url.rstrip('/')}/api/image-edit"
            request_data = {
                'prompt': task.prompt,
                'task_id': task.task_config_id,
                'ratio': task.aspect_ratio or "16:9",
                'count': 1,
                'user_id': task.user_id,
                'auth_token': task.auth_token,
                'ref_image_urls': ','.join(public_ref_urls),
            }
            if task.image_size:
                request_data['image_size'] = task.image_size
        else:
            api_url = f"{task.comfyui_base_url.rstrip('/')}/api/text-to-image"
            request_data = {
                'prompt': task.prompt,
                'task_id': task.task_config_id,
                'user_id': task.user_id,
                'auth_token': task.auth_token,
                'count': 1
            }
            if task.aspect_ratio:
                request_data['aspect_ratio'] = task.aspect_ratio
            if task.image_size:
                request_data['image_size'] = task.image_size
        
        response = httpx.post(api_url, data=request_data, timeout=30, verify=False, trust_env=False)
        response.raise_for_status()
        
        result_data = response.json()
        project_ids = result_data.get('project_ids', [])
        
        if project_ids:
            logger.info(f"任务 {task.task_key} 重试提交成功，新 project_id: {project_ids[0]}")
            return project_ids[0]
        else:
            logger.warning(f"任务 {task.task_key} 重试提交成功但未返回 project_id")
            return None
            
    except Exception as e:
        logger.error(f"任务 {task.task_key} 重试提交失败: {e}")
        return None


def _parse_reference_images(value: Any) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            return []
    return []


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
        
        is_grid_type = ItemType.is_grid(task.item_type)

        # grid 类型必须落盘后拆图；非 grid 仍受 image.enable_download 控制。
        enable_image_download = get_config().get("image", {}).get("enable_download", False)

        if enable_image_download or is_grid_type:
            # 启用图片下载和本地存储
            local_image_url, local_file_path = _download_and_store_image(
                file_url, task.item_type, task.comfyui_base_url
            )
        else:
            # 直接使用任务返回的图片地址
            local_image_url = file_url
            local_file_path = None
        
        # 检查是否为宫格类型，需要进行图片拆分
        split_image_urls = []
        # 宫格规格：优先用 task.grid_size（新列），旧记录/MagicMock 默认 4
        from config.constant import GridConfig
        try:
            _raw_grid_size = task.grid_size
            grid_size = int(_raw_grid_size) if isinstance(_raw_grid_size, int) else GridConfig.SIZE_2X2
        except (AttributeError, TypeError, ValueError):
            grid_size = GridConfig.SIZE_2X2

        if is_grid_type and local_file_path:
            validation = validate_grid_image(local_file_path, grid_size)
            if not validation.is_valid:
                _handle_grid_validation_failure(task, validation)
                return

        if is_grid_type and local_file_path and task.item_type != ItemType.STORYBOARD_FIRST_FRAME_GRID:
            # 宫格图片需要拆分
            try:
                # 解析名称：优先用结构化 item_names_json，fallback 到 item_name 逗号 split
                try:
                    item_names = task.get_item_names_list()
                except Exception:
                    item_names = [name.strip() for name in (task.item_name or '').split(',')]
                # 健壮性：item_names 为空或数量不在 VALID_SIZES 时，仍用 grid_size 兜底
                if not item_names:
                    item_names = [name.strip() for name in (task.item_name or '').split(',')]

                if len(item_names) == grid_size:
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
                    unique_names = [str(uuid.uuid4()) for _ in range(grid_size)]

                    # 拆分图片（通用 N×N 切分）
                    split_paths = splitter.split_grid(
                        grid_image_path=local_file_path,
                        output_dir=output_dir,
                        grid_size=grid_size,
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

                    logger.info(f"宫格(grid_size={grid_size})图片拆分成功: {len(split_paths)} 张图片")
                else:
                    logger.warning(f"宫格 item_name 数量({len(item_names)})与 grid_size({grid_size})不符，跳过拆分")
            except Exception as e:
                logger.error(f"宫格图片拆分失败: {str(e)}")
        
        # 更新对应的item
        update_success = False
        try:
            if task.item_type == 0:  # 通用生图（营销等场景），不绑定任何item
                # 只需记录图片URL到数据库，无需更新JSON文件
                update_success = True
                logger.info(f"通用生图任务完成，图片URL: {local_image_url}")
            else:
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
                elif task.item_type == 4:  # character_grid (宫格角色)
                    item_names = task.get_item_names_list()
                    if len(item_names) == grid_size and len(split_image_urls) == grid_size:
                        for idx, (name, img_url) in enumerate(zip(item_names, split_image_urls)):
                            if GridConfig.is_placeholder(name):
                                logger.info(f"跳过占位符格子 #{idx + 1}")
                                continue
                            result = mcp_tool.update_character_json(task.user_id, task.world_id, task.auth_token,
                                                                   name, reference_image=img_url)
                            if result.get('success', False):
                                logger.info(f"已更新角色 {name} 的参考图")
                        update_success = True
                elif task.item_type == 5:  # location_grid (宫格场景)
                    # 名称统一从 item_names_json 读取（item_name 列已改为展示短 key）
                    item_names = task.get_item_names_list()
                    # target_entity_ids_json 在 create 时已过滤 placeholder 的 None，是纯 id 列表
                    try:
                        target_db_ids = task.get_target_entity_ids_list()
                    except Exception:
                        target_db_ids = []
                    if len(item_names) == grid_size and len(split_image_urls) == grid_size:
                        from model.location import LocationModel
                        # 按"非 placeholder 名称"与"有效 target id"顺序对齐回写
                        valid_id_iter = iter(target_db_ids)
                        for idx, (name, img_url) in enumerate(zip(item_names, split_image_urls)):
                            if GridConfig.is_placeholder(name):
                                logger.info(f"跳过占位符格子 #{idx + 1}")
                                continue
                            # 取下一个有效 DB id（与当前非 placeholder 名称对齐）
                            loc_db_id = next(valid_id_iter, None)
                            if loc_db_id:
                                try:
                                    LocationModel.update(int(loc_db_id), reference_image=img_url)
                                    logger.info(f"已按 DB id={loc_db_id} 更新场景 reference_image")
                                except Exception as loc_err:
                                    logger.warning(f"按 DB id 更新场景失败(非阻塞，回退按名): {loc_err}")
                            # 同时按名更新 JSON 文件，保持与角色/道具一致的资产管线
                            result = mcp_tool.update_location_json(task.user_id, task.world_id, task.auth_token,
                                                                  name, reference_image=img_url)
                            if result.get('success', False):
                                logger.info(f"已更新场景 {name} 的参考图")
                        update_success = True
                elif task.item_type == 6:  # prop_grid (宫格道具)
                    item_names = task.get_item_names_list()
                    if len(item_names) == grid_size and len(split_image_urls) == grid_size:
                        for idx, (name, img_url) in enumerate(zip(item_names, split_image_urls)):
                            if GridConfig.is_placeholder(name):
                                logger.info(f"跳过占位符格子 #{idx + 1}")
                                continue
                            result = mcp_tool.update_prop_json(task.user_id, task.world_id, task.auth_token,
                                                              name, reference_image=img_url)
                            if result.get('success', False):
                                logger.info(f"已更新道具 {name} 的参考图")
                        update_success = True
                elif task.item_type == ItemType.STORYBOARD_FIRST_FRAME_GRID:
                    update_success = _dispatch_storyboard_first_frame_grid_split(
                        task,
                        local_image_url,
                        local_file_path,
                        grid_size,
                    )
                elif task.item_type == 7:  # character_variant (角色变体图)
                    # item_name 格式为 "角色名|变体标签"
                    parts = (task.item_name or '').split('|', 1)
                    char_name = parts[0].strip()
                    variant_label = parts[1].strip() if len(parts) > 1 else '变体'
                    # 读取角色当前数据（resolve 支持中文名/sanitize/扫描 name 字段）
                    file_manager = mcp_tool.get_file_manager()
                    resolved_path = file_manager.resolve_character_file_path(
                        char_name, task.user_id, task.world_id
                    )
                    char_data = file_manager.get_character_json(char_name, task.user_id, task.world_id)
                    if char_data:
                        existing_variants = char_data.get('reference_images', []) or []
                        if not isinstance(existing_variants, list):
                            existing_variants = []
                        new_variant = {'id': str(uuid.uuid4()), 'label': variant_label, 'url': local_image_url}
                        # 移除同标签的旧条目（如果有）
                        existing_variants = [
                            v for v in existing_variants
                            if not (isinstance(v, dict) and v.get('label') == variant_label)
                        ]
                        existing_variants.append(new_variant)
                        # 更新角色的 reference_images
                        result = mcp_tool.update_character_json(
                            task.user_id, task.world_id, task.auth_token,
                            char_name, reference_images=existing_variants
                        )
                        update_success = result.get('success', False)
                        if update_success:
                            logger.info(
                                f"已追加角色 {char_name} 的变体图 [{variant_label}]: {local_image_url} "
                                f"(file={resolved_path})"
                            )
                            # 同步更新数据库中的 reference_images，确保前端通过 API 能获取到变体图
                            try:
                                from model.character import CharacterModel
                                db_char = CharacterModel.get_by_name(int(task.world_id), char_name)
                                if db_char:
                                    CharacterModel.update(db_char.id, reference_images=existing_variants)
                                    logger.info(f"已同步角色 {char_name} 的变体图到数据库 (id={db_char.id})")
                                else:
                                    logger.warning(
                                        f"数据库中未找到角色 {char_name} (world_id={task.world_id})，跳过同步"
                                    )
                            except Exception as db_err:
                                logger.warning(f"同步角色 {char_name} 变体图到数据库失败(非阻塞): {db_err}")
                        else:
                            logger.error(
                                f"角色变体图写回失败: char={char_name}, label={variant_label}, "
                                f"file={resolved_path}, error={result.get('error')}"
                            )
                    else:
                        logger.error(
                            f"角色 {char_name} 不存在，无法更新变体图 "
                            f"(user_id={task.user_id}, world_id={task.world_id}, "
                            f"item_name={task.item_name}, resolved={resolved_path})"
                        )
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
        # 同步终止绑定的 pipeline step（DOWNLOAD_FAILED 也是失败终态，否则 step 会永久卡 PENDING）
        _fail_pending_grid_split_step_for_task(task, f"宫格生图下载/处理失败: {e}")


def _recover_late_completed_terminal_tasks(limit: int = 20) -> int:
    """Recover grid tasks that timed out before the bound ai_tools result arrived."""
    try:
        late_tasks = GridImageTasksModel.get_late_completed_terminal_tasks(limit=limit)
    except AttributeError:
        return 0
    if not late_tasks:
        return 0

    recovered_count = 0
    logger.info("发现 %s 个宫格晚到成功任务，准备恢复拆分/回写", len(late_tasks))
    for task in late_tasks:
        file_url = getattr(task, "ai_tool_result_url", None)
        if not file_url:
            continue
        try:
            _handle_task_success(task, {"status": "SUCCESS", "results": [{"file_url": file_url}]})
            recovered_count += 1
        except Exception as exc:
            logger.error(
                "恢复宫格晚到成功任务失败: task_key=%s project_id=%s err=%s",
                getattr(task, "task_key", None),
                getattr(task, "project_id", None),
                exc,
                exc_info=True,
            )
    return recovered_count


def _cleanup_orphan_grid_split_steps() -> int:
    """
    清理孤立的 storyboard grid split pipeline step。

    孤儿定义：step 仍 PENDING，但绑定的 grid_image_tasks 已进入终态：
    - 失败终态（FAILED / TIMEOUT / DOWNLOAD_FAILED / CANCELLED）：失败回写漏命中；
    - 成功终态（COMPLETED）：宫格重试导致 project_id 漂移，预建 step 未被 dispatch、
      被 fallback 新建的兄弟 step 替代，沦为僵尸。

    全局调度器（task.pipeline_processor）每 13s 会反复 skip 它们刷日志，
    在此每轮轻量清理，使其尽快终止、退出扫描范围。

    Returns:
        被标记为 FAILED 的 step 数量
    """
    try:
        from config.constant import GridConfig, GridImageTaskStatus
        from model.ai_tool_pipeline_steps import PipelineStepModel
    except Exception as exc:
        logger.error("加载孤儿 grid split step 清理依赖失败: %s", exc, exc_info=True)
        return 0

    terminal_statuses = (
        GridImageTaskStatus.FAILED,
        GridImageTaskStatus.TIMEOUT,
        GridImageTaskStatus.DOWNLOAD_FAILED,
        GridImageTaskStatus.CANCELLED,
        GridImageTaskStatus.COMPLETED,
    )
    try:
        orphans = PipelineStepModel.get_orphan_grid_split_steps(
            limit=GridConfig.GRID_SPLIT_ORPHAN_CLEANUP_LIMIT,
            grid_terminal_statuses=terminal_statuses,
        )
    except Exception as exc:
        logger.error("查询孤儿 grid split step 失败: %s", exc, exc_info=True)
        return 0
    if not orphans:
        return 0

    step_ids = [s.id for s in orphans]
    logger.info("发现 %s 个孤儿 storyboard grid split step，标记为 FAILED: ids=%s", len(step_ids), step_ids)
    try:
        affected = PipelineStepModel.fail_steps_by_ids(
            step_ids,
            error_message="宫格生图任务已进入终态，绑定 step 未被正常 dispatch/fail，由孤儿清理标记为 FAILED",
        )
        return affected
    except Exception as exc:
        logger.error("标记孤儿 grid split step 失败: ids=%s err=%s", step_ids, exc, exc_info=True)
        return 0


def process_grid_image_tasks(app=None):
    """
    处理宫格生图任务（在scheduler进程中定时执行）
    
    Args:
        app: FastAPI应用实例（保持与其他任务处理函数签名一致）
    """
    try:
        _recover_late_completed_terminal_tasks()
        _cleanup_orphan_grid_split_steps()

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
                    timeout_msg = f"超过最大尝试次数 {task.max_attempts}"
                    logger.error(f"任务超时: {task.task_key}, 尝试次数: {task.try_count}/{task.max_attempts}")
                    GridImageTasksModel.update_status(
                        task_key=task.task_key,
                        status=GridImageTaskStatus.TIMEOUT,
                        error_message=timeout_msg
                    )
                    _update_task_status_file(task.item_type, task.item_name, 'timeout',
                                           task.user_id, task.world_id)
                    _mark_storyboard_grid_batch_items_failed(task, f"宫格生图超时: {timeout_msg}")
                    continue
                
                # 更新为处理中状态（仅在第一次尝试时）
                if task.try_count == 1:
                    GridImageTasksModel.update_status(
                        task_key=task.task_key,
                        status=GridImageTaskStatus.PROCESSING
                    )
                    _update_task_status_file(task.item_type, task.item_name, 'running', 
                                           task.user_id, task.world_id)
                
                # ===== E2E Mock 短路 =====
                from task.mock_interceptor import is_mock_enabled, is_mock_id, comfyui_status_success, _img
                if is_mock_enabled() and is_mock_id(task.project_id):
                    file_url = (_img("grid_image") if ItemType.is_grid(task.item_type)
                                else _img("comfyui_text_to_image")) or "/upload/mock/e2e_grid_2x2.png"
                    _handle_task_success(task, comfyui_status_success(file_url))
                    continue
                # =========================

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

                    # ⚠️ 竞态防护：grid_image_task(每10秒) 和 visual_task(每5秒) 同时轮询同一任务
                    # 当 visual_task 触发 before_finish 重试时，ai_tools.status 会变为 WAITING_BEFORE_FINISH
                    # 此时 grid_image_task 必须跳过，否则会覆盖状态导致重试失败
                    try:
                        ai_tool_record = AIToolsModel.get_by_id(int(task.project_id))
                        if ai_tool_record and ai_tool_record.status == AI_TOOL_STATUS_WAITING_BEFORE_FINISH:
                            logger.info(f"任务 {task.task_key} 已被 pipeline 重试接管，跳过")
                            continue
                    except Exception:
                        pass
                    
                    # 检查是否可以自动重试
                    max_retries = getattr(task, 'max_retries', 0) or 0
                    retry_count = getattr(task, 'retry_count', 0) or 0
                    
                    if retry_count < max_retries and task.prompt and task.task_config_id:
                        # 尝试重新提交请求
                        logger.info(f"任务 {task.task_key} 准备自动重试 ({retry_count + 1}/{max_retries})")
                        new_project_id = _resubmit_image_request(task)
                        
                        if new_project_id:
                            # 重置任务状态，等待下一轮轮询
                            GridImageTasksModel.reset_for_retry(task.task_key, new_project_id)
                            _update_task_status_file(task.item_type, task.item_name, 'retrying',
                                                   task.user_id, task.world_id)
                            logger.info(f"任务 {task.task_key} 已重置为重试状态，新 project_id: {new_project_id}")
                            continue  # 继续处理下一个任务
                        else:
                            logger.error(f"任务 {task.task_key} 重试提交失败，标记为终态失败")
                    
                    # 无法重试或重试失败，标记为终态失败
                    GridImageTasksModel.update_status(
                        task_key=task.task_key,
                        status=GridImageTaskStatus.FAILED,
                        error_message=failure_reason
                    )
                    _update_task_status_file(task.item_type, task.item_name, 'failed',
                                           task.user_id, task.world_id)
                    _mark_storyboard_grid_batch_items_failed(task, f"宫格生图失败: {failure_reason}")
                
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
                _mark_storyboard_grid_batch_items_failed(task, f"宫格生图异常: {e}")
        
        # 清理旧任务（7天前的已完成/失败任务）
        try:
            GridImageTasksModel.cleanup_old_tasks(days=7)
        except Exception as e:
            logger.error(f"清理旧任务失败: {e}")
            
    except Exception as e:
        logger.error(f"处理宫格生图任务失败: {e}")
