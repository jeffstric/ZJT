"""
任务管理器
使用APScheduler处理后台任务，包括状态轮询、文件下载和数据更新
"""

import os
import time
import requests
import urllib.parse
import uuid
import threading
import json
import logging
from datetime import datetime
from typing import Dict, Any, List
from apscheduler.schedulers.background import BackgroundScheduler
from script_writer_core.image_grid_splitter import ImageGridSplitter
from config.config_util import get_config
from config.constant import FilePathConstants
from utils.network_utils import is_local_file_path

logger = logging.getLogger(__name__)

class TaskManager:
    """任务管理器，使用APScheduler处理后台任务"""
    
    @staticmethod
    def generate_task_key(item_type: int, item_name: str, user_id: str = None) -> str:
        """
        统一生成任务键的方法，供全局使用
        
        Args:
            item_type: 项目类型 (1=character, 2=location, 3=props)
            item_name: 项目名称
            user_id: 用户ID（可选，保留供未来使用）
        
        Returns:
            str: 任务键
        """
        if user_id:
            return f"{user_id}_{item_type}_{item_name}"
        else:
            return f"{item_type}_{item_name}"
    
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        self.active_tasks = {}  # 存储活跃任务信息
        self.global_lock = threading.RLock()  # 全局读写锁，用于管理locks字典
        self.task_locks = {}  # 为每个任务键维护独立的锁
    
    def _get_task_lock(self, task_key: str) -> threading.Lock:
        """获取指定任务的锁，如果不存在则创建"""
        with self.global_lock:
            if task_key not in self.task_locks:
                self.task_locks[task_key] = threading.Lock()
            return self.task_locks[task_key]
    
    def _cleanup_task_lock(self, task_key: str):
        """清理任务锁（当任务完成时）"""
        with self.global_lock:
            if task_key in self.task_locks:
                del self.task_locks[task_key]
    
    def _generate_task_key(self, item_type: int, item_name: str, user_id: str = None) -> str:
        """生成任务键，使用统一的静态方法"""
        return self.generate_task_key(item_type, item_name, user_id)
    
    def _generate_global_task_key(self, item_type: int, item_name: str) -> str:
        """生成全局任务键（不包含user_id）"""
        return f"{item_type}_{item_name}"
    
    def _get_task_status_file_path(self, user_id: str, world_id: str) -> str:
        """获取任务状态文件的路径"""
        task_status_dir = os.path.join(FilePathConstants._SCRIPT_WRITER_USER_DATA_SUBDIR, str(user_id), str(world_id), "task_status")
        os.makedirs(task_status_dir, exist_ok=True)
        return os.path.join(task_status_dir, "task_status.json")
    
    def _read_task_status_file(self, user_id: str, world_id: str) -> Dict[str, List[Dict]]:
        """读取任务状态文件"""
        file_path = self._get_task_status_file_path(user_id, world_id)
        
        if not os.path.exists(file_path):
            return {}
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    
    def _write_task_status_file(self, data: Dict[str, List[Dict]], user_id: str, world_id: str):
        """写入任务状态文件"""
        file_path = self._get_task_status_file_path(user_id, world_id)
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"写入任务状态文件失败: {str(e)}")
    
    def update_task_status(self, item_type: int, item_name: str, status: str, user_id: str, world_id: str):
        """更新任务状态"""
        try:
            # 读取现有数据
            data = self._read_task_status_file(user_id, world_id)
            
            # 确保item_type键存在
            item_type_key = str(item_type)
            if item_type_key not in data:
                data[item_type_key] = {}
            
            # 更新或添加记录（使用item_name作为key）
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data[item_type_key][item_name] = {
                'item_name': item_name,
                'status': status,
                'update_time': current_time
            }
            
            # 写入文件
            self._write_task_status_file(data, user_id, world_id)
            
        except Exception as e:
            print(f"更新任务状态失败: {str(e)}")
    
    def _update_task_status_file(self, item_type: int, item_name: str, status: str, user_id: str, world_id: str = None):
        """同步任务状态到文件系统"""
        try:
            # 如果没有提供world_id，尝试从上下文获取
            if not world_id:
                try:
                    import importlib
                    mcp_tool = importlib.import_module('script_writer_core.mcp_tool')
                    context = mcp_tool.get_context()
                    world_id = context.get('world_id')
                except:
                    print(f"无法获取world_id，跳过状态同步")
                    return
            
            if world_id:
                self.update_task_status(item_type, item_name, status, user_id, world_id)
        except Exception as e:
            print(f"同步任务状态失败: {str(e)}")
    
    def is_item_generating(self, item_type: int, item_name: str, user_id: str) -> bool:
        """检查指定item是否正在生成图片（全局唯一性约束）"""
        task_key = self._generate_task_key(item_type, item_name)
        with self.global_lock:
            return task_key in self.active_tasks
    
    def get_active_tasks(self, user_id: str = None) -> Dict[str, Any]:
        """获取活跃任务列表"""
        with self.global_lock:
            if user_id:
                return {k: v for k, v in self.active_tasks.items() if v.get('user_id') == user_id}
            return self.active_tasks.copy()
    
    def create_image_task(self, project_id: str, item_type: int, item_name: str, 
                         comfyui_base_url: str, auth_token: str, user_id: str, world_id: str) -> str:
        """创建图片生成后台任务（全局唯一性约束）"""
        task_key = self._generate_task_key(item_type, item_name)
        
        # 获取该任务的专用锁
        task_lock = self._get_task_lock(task_key)
        
        with task_lock:
            # 检查是否已有相同任务（使用全局锁进行快速检查）
            with self.global_lock:
                if task_key in self.active_tasks:
                    raise ValueError(f"该项目正在生成图片中，请等待完成后再试")
            
            # 创建任务记录
            with self.global_lock:
                self.active_tasks[task_key] = {
                    'project_id': project_id,
                    'item_type': item_type,
                    'item_name': item_name,
                    'user_id': user_id,
                    'world_id': world_id,
                    'status': 'scheduled',
                    'attempts': 0,
                    'max_attempts': 60,
                    'created_at': datetime.now().isoformat(),
                    'last_check': None
                }
            
            # 同步任务状态到文件
            self._update_task_status_file(item_type, item_name, 'scheduled', user_id, world_id)
        
        # 创建APScheduler任务
        job_id = f"image_task_{project_id}"
        try:
            self.scheduler.add_job(
                func=self._process_image_task,
                trigger='interval',
                seconds=10,  # 每10秒检查一次
                max_instances=1,
                args=[project_id, item_type, item_name, comfyui_base_url, auth_token, user_id, world_id],
                id=job_id,
                replace_existing=True
            )
        except Exception as e:
            # 如果调度任务创建失败，清理已创建的任务记录
            with self.global_lock:
                if task_key in self.active_tasks:
                    del self.active_tasks[task_key]
            raise e
        
        return job_id
    
    def _process_image_task(self, project_id: str, item_type: int, item_name: str, 
                           comfyui_base_url: str, auth_token: str, user_id: str, world_id: str):
        """处理图片生成任务的后台逻辑"""
        task_key = self._generate_task_key(item_type, item_name)
        
        try:
            # 获取该任务的专用锁
            task_lock = self._get_task_lock(task_key)
            
            with task_lock:
                # 检查任务是否还存在
                with self.global_lock:
                    if task_key not in self.active_tasks:
                        # 任务已被删除，停止处理
                        self._remove_job(f"image_task_{project_id}")
                        return
                    
                    task_info = self.active_tasks[task_key]
                    task_info['attempts'] += 1
                    task_info['last_check'] = datetime.now().isoformat()
                    
                    # 检查是否超过最大尝试次数
                    if task_info['attempts'] > task_info['max_attempts']:
                        logger = logging.getLogger(__name__)
                        
                        # 记录超时失败信息
                        timeout_details = {
                            'task_key': task_key,
                            'item_type': item_type,
                            'item_name': item_name,
                            'user_id': user_id,
                            'project_id': project_id,
                            'attempts': task_info['attempts'],
                            'max_attempts': task_info['max_attempts'],
                            'timestamp': datetime.now().isoformat(),
                            'failure_source': 'Timeout_MaxAttempts'
                        }
                        
                        logger.error(f"图片生成任务超时失败 - 超过最大尝试次数: {task_info['attempts']}/{task_info['max_attempts']}", 
                                    extra={'task_details': timeout_details})
                        
                        task_info['status'] = 'timeout'
                        task_info['failed_at'] = datetime.now().isoformat()
                        
                        # 同步超时状态到文件
                        self._update_task_status_file(item_type, item_name, 'timeout', user_id, world_id)
                        
                        # 记录任务状态更新到日志
                        logger.info(f"任务状态已更新为超时: {task_key}", extra={'status_update': timeout_details})
                        
                        self._cleanup_task(task_key, project_id)
                        return
                    
                    # 更新运行状态（仅在第一次尝试时）
                    if task_info['attempts'] == 1:
                        task_info['status'] = 'running'
                        self._update_task_status_file(item_type, item_name, 'running', user_id, world_id)
            
            # 检查图片生成状态（在锁外进行网络请求）
            try:
                status_url = f"{comfyui_base_url.rstrip('/')}/api/get-status/{project_id}"
                response = requests.get(f"{status_url}?auth_token={auth_token}", timeout=10)
                response.raise_for_status()
                
                status_data = response.json()
                if 'tasks' not in status_data or not status_data['tasks']:
                    return  # 继续等待
                
                task = status_data['tasks'][0]
                task_status = task.get('status', '')
                
                if task_status == 'SUCCESS':
                    # 图片生成成功，开始下载和更新
                    self._handle_success(task, project_id, item_type, item_name, 
                                       comfyui_base_url, auth_token, user_id, world_id, task_key)
                elif task_status == 'FAILED':
                    # 图片生成失败
                    logger = logging.getLogger(__name__)
                    
                    # 记录详细的失败信息
                    failure_reason = task.get('reason', '生成失败')
                    error_details = {
                        'task_key': task_key,
                        'item_type': item_type,
                        'item_name': item_name,
                        'user_id': user_id,
                        'project_id': project_id,
                        'failure_reason': failure_reason,
                        'task_status': task_status,
                        'timestamp': datetime.now().isoformat(),
                        'failure_source': 'ComfyUI_API_Response'
                    }
                    
                    logger.error(f"图片生成任务失败 - ComfyUI返回失败状态: {failure_reason}", 
                                extra={'task_details': error_details})
                    
                    with self.global_lock:
                        if task_key in self.active_tasks:
                            self.active_tasks[task_key]['status'] = 'failed'
                            self.active_tasks[task_key]['error'] = failure_reason
                            self.active_tasks[task_key]['failed_at'] = datetime.now().isoformat()
                    
                    # 同步失败状态到文件
                    self._update_task_status_file(item_type, item_name, 'failed', user_id, world_id)
                    
                    # 记录任务状态更新到日志
                    logger.info(f"任务状态已更新为失败: {task_key}", extra={'status_update': error_details})
                    
                    self._cleanup_task(task_key, project_id)
                
                # 其他状态继续等待
                
            except requests.RequestException as e:
                # 网络请求异常，更新状态但不清理任务（继续重试）
                with self.global_lock:
                    if task_key in self.active_tasks:
                        self.active_tasks[task_key]['last_error'] = str(e)
            
        except Exception as e:
            # 处理异常 - 重新获取锁（因为可能在锁外发生异常）
            logger = logging.getLogger(__name__)
            
            # 记录详细的失败信息到日志
            error_details = {
                'task_key': task_key,
                'item_type': item_type,
                'item_name': item_name,
                'user_id': user_id,
                'project_id': project_id,
                'error_type': type(e).__name__,
                'error_message': str(e),
                'timestamp': datetime.now().isoformat()
            }
            
            logger.error(f"图片生成任务失败 - {error_details['error_type']}: {error_details['error_message']}", 
                        extra={'task_details': error_details})
            
            try:
                task_lock = self._get_task_lock(task_key)
                with task_lock:
                    with self.global_lock:
                        if task_key in self.active_tasks:
                            self.active_tasks[task_key]['status'] = 'error'
                            self.active_tasks[task_key]['error'] = str(e)
                            # 记录失败时间
                            self.active_tasks[task_key]['failed_at'] = datetime.now().isoformat()
                
                # 同步错误状态到文件
                self._update_task_status_file(item_type, item_name, 'failed', user_id, world_id)
                
                # 记录任务状态更新到日志
                logger.info(f"任务状态已更新为失败: {task_key}", extra={'status_update': error_details})
                
            except Exception as cleanup_error:
                # 记录清理过程中的异常
                logger.error(f"任务清理过程中发生异常: {str(cleanup_error)}", 
                           extra={'cleanup_error': str(cleanup_error), 'original_error': error_details})
            
            self._cleanup_task(task_key, project_id)
    
    def _download_and_store_image(self, file_url: str, item_type: int, comfyui_base_url: str) -> tuple[str, str]:
        """下载并存储图片到本地，返回本地URL和文件路径"""
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
            if file_url.startswith("/"):
                file_url = file_url[1:]  # 移除开头的斜杠
            src_path = os.path.join(os.path.dirname(__file__), "..", file_url)
            src_path = os.path.abspath(src_path)

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
    
    def _handle_success(self, task: Dict, project_id: str, item_type: int, item_name: str,
                       comfyui_base_url: str, auth_token: str, user_id: str, world_id: str, task_key: str):
        """处理图片生成成功的情况"""
        try:
            results = task.get('results', [])
            if not results:
                raise Exception('图片生成完成但未返回结果')
            
            file_url = results[0].get('file_url', '')
            if not file_url:
                raise Exception('图片生成完成但未返回文件URL')
                      
            # 默认关闭图片下载功能
            enable_image_download = get_config().get("image", {}).get("enable_download", False)
            
            if enable_image_download:
                # 启用图片下载和本地存储
                local_image_url, local_file_path = self._download_and_store_image(
                    file_url, item_type, comfyui_base_url
                )
            else:
                # 直接使用任务返回的图片地址
                local_image_url = file_url
                local_file_path = None
            
            # 检查是否为4宫格类型，需要进行图片拆分
            is_grid_type = item_type in [4, 5, 6]  # 4=character_grid, 5=location_grid, 6=prop_grid
            split_image_urls = []
            
            # 调试日志
            print(f"[DEBUG] item_type={item_type}, is_grid_type={is_grid_type}, enable_image_download={enable_image_download}, local_file_path={local_file_path}")
            
            if is_grid_type and enable_image_download and local_file_path:
                # 4宫格图片需要拆分
                try:
                    # 解析item_name（格式："name1,name2,name3,name4"）
                    item_names = [name.strip() for name in item_name.split(',')]
                    
                    if len(item_names) == 4:
                        # 创建拆分器
                        splitter = ImageGridSplitter()
                        
                        # 根据item_type确定输出目录（存储到pic目录，而不是temp目录）
                        if item_type == 4:  # character_grid
                            output_dir = 'upload/character/pic'
                        elif item_type == 5:  # location_grid
                            output_dir = 'upload/location/pic'
                        elif item_type == 6:  # prop_grid
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
                            # 获取相对路径
                            rel_path = os.path.relpath(split_path, start=os.path.dirname(__file__))
                            split_url = f"{config_comfyui_base_url.rstrip('/')}/{rel_path}"
                            split_image_urls.append(split_url)
                        
                        print(f"[SUCCESS] 4宫格图片拆分成功: {len(split_paths)} 张图片")
                        print(f"[DEBUG] split_image_urls: {split_image_urls}")
                    else:
                        print(f"警告: 4宫格item_name格式不正确，期望4个名称，实际: {len(item_names)}")
                except Exception as e:
                    print(f"4宫格图片拆分失败: {str(e)}")
                    # 拆分失败不影响主流程，继续执行
            
            # 更新对应的item（避免循环导入）
            update_success = False
            try:
                # 延迟导入避免循环导入问题
                import importlib
                mcp_tool = importlib.import_module('script_writer_core.mcp_tool')
                
                if item_type == 1:  # character
                    result = mcp_tool.update_character_json(user_id, world_id, auth_token, item_name, reference_image=local_image_url)
                    update_success = result.get('success', False)
                elif item_type == 2:  # location
                    result = mcp_tool.update_location_json(user_id, world_id, auth_token, item_name, reference_image=local_image_url)
                    update_success = result.get('success', False)
                elif item_type == 3:  # props
                    result = mcp_tool.update_prop_json(user_id, world_id, auth_token, item_name, reference_image=local_image_url)
                    update_success = result.get('success', False)
                elif item_type == 4:  # character_grid (4宫格角色)
                    # 更新4个角色的参考图
                    item_names = [name.strip() for name in item_name.split(',')]
                    print(f"[DEBUG] 准备更新4宫格角色: item_names={item_names}, split_image_urls数量={len(split_image_urls)}")
                    if len(item_names) == 4 and len(split_image_urls) == 4:
                        for idx, (name, img_url) in enumerate(zip(item_names, split_image_urls)):
                            result = mcp_tool.update_character_json(user_id, world_id, auth_token, name, reference_image=img_url)
                            if result.get('success', False):
                                print(f"已更新角色 {name} 的参考图 (位置: {'左上' if idx==0 else '右上' if idx==1 else '左下' if idx==2 else '右下'})")
                        update_success = True
                elif item_type == 5:  # location_grid (4宫格场景)
                    # 更新4个场景的参考图
                    item_names = [name.strip() for name in item_name.split(',')]
                    print(f"[DEBUG] 准备更新4宫格场景: item_names={item_names}, split_image_urls数量={len(split_image_urls)}")
                    if len(item_names) == 4 and len(split_image_urls) == 4:
                        for idx, (name, img_url) in enumerate(zip(item_names, split_image_urls)):
                            result = mcp_tool.update_location_json(user_id, world_id, auth_token, name, reference_image=img_url)
                            if result.get('success', False):
                                print(f"已更新场景 {name} 的参考图 (位置: {'左上' if idx==0 else '右上' if idx==1 else '左下' if idx==2 else '右下'})")
                        update_success = True
                elif item_type == 6:  # prop_grid (4宫格道具)
                    # 更新4个道具的参考图
                    item_names = [name.strip() for name in item_name.split(',')]
                    print(f"[DEBUG] 准备更新4宫格道具: item_names={item_names}, split_image_urls数量={len(split_image_urls)}")
                    if len(item_names) == 4 and len(split_image_urls) == 4:
                        for idx, (name, img_url) in enumerate(zip(item_names, split_image_urls)):
                            result = mcp_tool.update_prop_json(user_id, world_id, auth_token, name, reference_image=img_url)
                            if result.get('success', False):
                                print(f"已更新道具 {name} 的参考图 (位置: {'左上' if idx==0 else '右上' if idx==1 else '左下' if idx==2 else '右下'})")
                        update_success = True
            except Exception as e:
                # 更新失败但不影响图片下载成功
                update_success = False
                print(f"更新item失败: {str(e)}")
            
            # 更新任务状态
            task_lock = self._get_task_lock(task_key)
            with task_lock:
                with self.global_lock:
                    if task_key in self.active_tasks:
                        self.active_tasks[task_key].update({
                            'status': 'completed',
                            'local_image_url': local_image_url,
                            'local_file_path': local_file_path,
                            'update_success': update_success,
                            'completed_at': datetime.now().isoformat()
                        })
            
            # 同步完成状态到文件
            self._update_task_status_file(item_type, item_name, 'completed', user_id, world_id)
            
            # 清理任务
            self._cleanup_task(task_key, project_id)
            
        except Exception as e:
            logger = logging.getLogger(__name__)
            
            # 记录下载失败信息
            download_error_details = {
                'task_key': task_key,
                'item_type': item_type,
                'item_name': item_name,
                'user_id': user_id,
                'project_id': project_id,
                'error_type': type(e).__name__,
                'error_message': str(e),
                'timestamp': datetime.now().isoformat(),
                'failure_source': 'Download_Process'
            }
            
            logger.error(f"图片下载失败 - {download_error_details['error_type']}: {download_error_details['error_message']}", 
                        extra={'task_details': download_error_details})
            
            task_lock = self._get_task_lock(task_key)
            with task_lock:
                with self.global_lock:
                    if task_key in self.active_tasks:
                        self.active_tasks[task_key]['status'] = 'download_failed'
                        self.active_tasks[task_key]['error'] = str(e)
                        self.active_tasks[task_key]['failed_at'] = datetime.now().isoformat()
            
            # 同步下载失败状态到文件
            self._update_task_status_file(item_type, item_name, 'failed', user_id, world_id)
            
            # 记录任务状态更新到日志
            logger.info(f"任务状态已更新为下载失败: {task_key}", extra={'status_update': download_error_details})
            
            self._cleanup_task(task_key, project_id)
    
    def _cleanup_task(self, task_key: str, project_id: str):
        """清理任务"""
        # 移除调度任务
        self._remove_job(f"image_task_{project_id}")
        
        # 延迟删除任务记录（保留5分钟供查询）
        def delayed_cleanup():
            time.sleep(300)  # 5分钟后删除
            with self.global_lock:
                if task_key in self.active_tasks:
                    del self.active_tasks[task_key]
            # 清理任务锁
            self._cleanup_task_lock(task_key)
        
        cleanup_thread = threading.Thread(target=delayed_cleanup, daemon=True)
        cleanup_thread.start()
    
    def _remove_job(self, job_id: str):
        """安全移除调度任务"""
        try:
            self.scheduler.remove_job(job_id)
        except:
            pass  # 任务可能已经不存在
    
    def cancel_task(self, item_type: int, item_name: str, user_id: str) -> bool:
        """取消指定的图片生成任务（全局唯一性约束）"""
        task_key = self._generate_task_key(item_type, item_name)
        
        # 获取该任务的专用锁
        task_lock = self._get_task_lock(task_key)
        
        with task_lock:
            with self.global_lock:
                if task_key not in self.active_tasks:
                    return False
                
                task_info = self.active_tasks[task_key]
                project_id = task_info['project_id']
                
                # 更新状态为已取消
                task_info['status'] = 'cancelled'
                task_info['cancelled_at'] = datetime.now().isoformat()
        
        # 同步取消状态到文件
        # 从任务信息中获取world_id
        world_id = task_info.get('world_id')
        if world_id:
            self._update_task_status_file(item_type, item_name, 'cancelled', user_id, world_id)
        
        # 移除调度任务
        self._remove_job(f"image_task_{project_id}")
        return True
    
    def shutdown(self):
        """关闭任务管理器，清理所有资源"""
        try:
            self.scheduler.shutdown(wait=False)
        except:
            pass
        
        with self.global_lock:
            self.active_tasks.clear()
            self.task_locks.clear()


# 全局任务管理器实例
_task_manager = None


def get_task_manager():
    """获取任务管理器实例（单例模式）"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
