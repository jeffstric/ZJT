"""
Script Writer API 集成模块
将 script_writer 的 Flask API 集成到 FastAPI 中
"""

import os
import json
import logging
import uuid
import asyncio
import threading
from typing import Optional, Dict, Any, List
from datetime import datetime
from fastapi import APIRouter, Request, Query as QueryParam, Header, UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from perseids_server.utils.permission import require_permission
from config.config_util import get_dynamic_config_value, get_config
from model.vendor_model import VendorModelModel

# ==================== 加载 API 配置 ====================
def _load_api_config():
    """从统一配置加载 API 配置到环境变量"""
    # 设置 Google Gemini API
    google_api_key = get_dynamic_config_value('llm', 'google', 'api_key', default=None)
    google_base_url = get_dynamic_config_value('llm', 'google', 'gemini_base_url', default=None)
    
    if google_api_key:
        os.environ.setdefault('GOOGLE_API_KEY', google_api_key)
        os.environ.setdefault('GEMINI_API_KEY', google_api_key)
    if google_base_url:
        os.environ.setdefault('GOOGLE_GEMINI_BASE_URL', google_base_url)
    
    logging.info("API config loaded from unified config")

# 启动时加载配置
_load_api_config()

# 导入数据模型
from model.world import WorldModel
from model.script import ScriptModel
from model.character import CharacterModel
from model.location import LocationModel
from model.props import PropsModel

# 导入服务
from perseids_server.client import async_make_perseids_request

# 导入智能体系统
from script_writer_core.agents import TaskManager, TaskStatus, ToolExecutor
from script_writer_core.chat_session import ChatSession
from script_writer_core.file_manager import FileManager
logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(prefix="/api", tags=["script_writer"])

# 会话存储（数据库 + 可选内存缓存）
# 使用数据库存储支持多 worker 进程间会话共享
from script_writer_core.session_storage import SessionStorage
session_storage = SessionStorage(use_cache=True, cache_ttl=300)

# 生图模型配置存储（按 user_id + world_id 存储 task_id）
# key: f"{user_id}_{world_id}", value: task_id (int)
text_to_image_model_config: Dict[str, int] = {}
TEXT_TO_IMAGE_MODEL_LOCK = threading.RLock()

# 默认生图模型 task_id (nano-banana-Pro)
DEFAULT_TEXT_TO_IMAGE_TASK_ID = 7


def _get_text_to_image_models_from_config():
    """从统一配置获取文生图模型列表"""
    from config.unified_config import UnifiedConfigRegistry, TaskCategory
    configs = UnifiedConfigRegistry.get_by_category(TaskCategory.TEXT_TO_IMAGE)
    return {c.id: {"name": c.name, "computing_power": c.get_computing_power(), "supports_grid_image": c.supports_grid_image}
            for c in configs if c.enabled}


def get_text_to_image_model_id(user_id: str, world_id: str) -> int:
    """获取用户在指定世界的生图模型 task_id"""
    key = f"{user_id}_{world_id}"
    with TEXT_TO_IMAGE_MODEL_LOCK:
        result = text_to_image_model_config.get(key, DEFAULT_TEXT_TO_IMAGE_TASK_ID)
        logger.info(f"[生图模型配置] 读取: key={key}, task_id={result}, 配置存在={key in text_to_image_model_config}")
        return result


def set_text_to_image_model_id(user_id: str, world_id: str, task_id: int):
    """设置用户在指定世界的生图模型 task_id"""
    key = f"{user_id}_{world_id}"
    with TEXT_TO_IMAGE_MODEL_LOCK:
        text_to_image_model_config[key] = task_id
        logger.info(f"[生图模型配置] 已保存: key={key}, task_id={task_id}")


# 全局组件
task_manager = TaskManager()
# 指定项目根目录作为 base_dir，确保文件保存到正确位置
from utils.project_path import get_project_root
project_root = get_project_root()
file_manager = FileManager(base_dir=project_root)
tool_executor = ToolExecutor(file_manager=file_manager)

# 设置 mcp_tool 的全局 file_manager
from script_writer_core.mcp_tool import set_file_manager
from script_writer_core.mcp_tool import _sanitize_filename
set_file_manager(file_manager)

# 设置 mcp_tool 的生图模型获取函数
from script_writer_core.mcp_tool import set_text_to_image_model_getter
set_text_to_image_model_getter(get_text_to_image_model_id)

# 加载智能体配置
import json
agents_config_path = os.path.join(os.path.dirname(__file__), '..', 'script_writer_core', 'config', 'agents_config.json')
try:
    with open(agents_config_path, 'r', encoding='utf-8') as f:
        agents_config = json.load(f)
    logger.info(f"Agents config loaded from {agents_config_path}")
except Exception as e:
    logger.warning(f"Failed to load agents_config.json: {e}, using defaults")
    agents_config = {
        "pm_agent": {
            "model": "gemini/gemini-2.0-flash-exp",
            "allowed_tools": ["skill", "request_human_verification"],
            "skills": ["script-orchestrator"],
            "max_consecutive_failures": 3,
            "max_total_failures": 7
        },
        "expert_agents": {}
    }

# ==================== 辅助函数 ====================

async def verify_auth_token(user_id: str, auth_token: str) -> tuple[bool, Optional[dict]]:
    """
    验证用户的 auth_token
    
    Args:
        user_id: 用户ID
        auth_token: 用户的认证令牌
        
    Returns:
        tuple: (success: bool, error_response: dict or None)
    """
    if not auth_token:
        return True, None
    
    try:
        # 调用认证服务器验证 token
        success, message, auth_data = await async_make_perseids_request(
            endpoint='get_auth_token_by_user_id',
            data={
                'user_id': int(user_id),
                'authentication_id': os.environ.get('SYSTEM_AUTH_ID', '')
            },
            method='POST'
        )
        
        if not success:
            logger.warning(f"Token验证失败 - user_id: {user_id}, 错误: {message}")
            return False, {
                'success': False,
                'error': 'Token验证失败',
                'message': message
            }
        
        logger.info(f"Token验证成功 - user_id: {user_id}")
        return True, None
        
    except Exception as e:
        logger.error(f"Token验证异常 - user_id: {user_id}, 错误: {str(e)}")
        return False, {
            'success': False,
            'error': 'Token验证异常',
            'message': f'验证服务异常: {str(e)}'
        }

async def check_computing_power(auth_token: str) -> tuple[bool, int, Optional[str]]:
    """
    检查用户算力
    
    Args:
        auth_token: 认证令牌
        
    Returns:
        tuple: (success: bool, computing_power: int, error_message: str or None)
    """
    if not auth_token:
        return True, 999999, None  # 无token时跳过检查
    
    try:
        headers = {'Authorization': f'Bearer {auth_token}'}
        success, message, response_data = await async_make_perseids_request(
            endpoint='user/check_computing_power',
            method='GET',
            headers=headers
        )
        
        if not success:
            # 检测 token 过期
            if '无效或已过期' in message or 'token' in message.lower() or '认证' in message:
                return False, 0, f'TOKEN_EXPIRED: {message}'
            return False, 0, f'算力检查失败: {message}'
        
        computing_power = response_data.get('computing_power', 0) if isinstance(response_data, dict) else 0
        return True, computing_power, None
        
    except Exception as e:
        logger.error(f"算力检查异常: {str(e)}")
        return False, 0, f'算力检查异常: {str(e)}'

async def validate_model(model: str, auth_token: str) -> tuple[bool, List[str], Optional[str]]:
    """
    验证模型是否有效
    
    Args:
        model: 模型名称
        auth_token: 认证令牌
        
    Returns:
        tuple: (is_valid: bool, valid_models: list, error_message: str or None)
    """
    if not auth_token:
        return True, [], None  # 无token时跳过验证
    
    try:
        headers = {'Authorization': f'Bearer {auth_token}'}
        success, message, response_data = await async_make_perseids_request(
            endpoint='user/models',
            method='GET',
            headers=headers
        )
        
        if not success:
            logger.warning(f"获取模型列表失败: {message}")
            return False, [], f'无法验证模型有效性: {message}'
        
        # 获取有效的模型列表
        valid_models = []
        remote_models = response_data.get('models', []) if isinstance(response_data, dict) else []
        for model_info in remote_models:
            valid_models.append(model_info.get('model_name'))
        
        # 验证用户选择的模型是否在有效列表中
        if model not in valid_models:
            logger.warning(f"用户尝试设置无效模型: {model}, 有效模型列表: {valid_models}")
            return False, valid_models, f'模型 "{model}" 不存在或不可用'
        
        return True, valid_models, None
        
    except Exception as e:
        logger.error(f"模型验证异常: {str(e)}")
        return False, [], f'模型验证异常: {str(e)}'

# ==================== 数据库同步函数 ====================

def sync_database_to_files(user_id: str, world_id: str, auth_token: str, force_overwrite: bool) -> dict:
    """
    从数据库同步数据到文件系统（JSON格式）
    
    Args:
        user_id: 用户ID
        world_id: 世界ID
        auth_token: 认证令牌
        force_overwrite: 是否强制覆盖（必填）
            - True: 强制覆盖，返回被覆盖的文件列表
            - False: 不覆盖有差异的文件，返回差异文件列表
    
    Returns:
        dict: {
            'success': bool,
            'diff_files': list,  # 存在差异的文件名列表
            'overwritten_files': list,  # 被覆盖的文件名列表（仅force_overwrite=True时）
            'skipped_files': list,  # 跳过的文件名列表（仅force_overwrite=False时）
            'local_only_files': list  # 本地存在但数据库不存在的文件列表
        }
    """
    result = {
        'success': True,
        'diff_files': [],
        'overwritten_files': [],
        'skipped_files': [],
        'local_only_files': []
    }
    
    if not user_id or not world_id:
        raise ValueError(f"user_id 和 world_id 不能为空: user_id={user_id}, world_id={world_id}")
    
    def compare_json_content(new_content: str, existing_content: str, file_name: str = "") -> bool:
        """比较两个JSON内容是否一致（忽略格式差异和时间戳字段）"""
        try:
            new_data = json.loads(new_content) if isinstance(new_content, str) else new_content
            existing_data = json.loads(existing_content) if isinstance(existing_content, str) else existing_content
            
            ignore_fields = {
                'created_at', 'update_time', 'create_time', 'updated_at',
                'user_id', 'world_id', 'type'
            }
            
            new_data_filtered = {k: v for k, v in new_data.items() if k not in ignore_fields}
            existing_data_filtered = {k: v for k, v in existing_data.items() if k not in ignore_fields}
            
            return new_data_filtered == existing_data_filtered
        except Exception as e:
            logger.error(f"比较JSON内容失败 ({file_name}): {e}")
            return new_content == existing_content
    
    try:
        from model.world import WorldModel
        from model.character import CharacterModel
        from model.location import LocationModel
        from model.script import ScriptModel
        from model.props import PropsModel
        from script_writer_core.mcp_tool import create_character_json, create_location_json, create_prop_json
        from pathlib import Path

        base_path = file_manager._get_user_world_path(user_id, world_id)

        if force_overwrite:
            deleted_files = []
            directories_to_clean = ['worlds', 'characters', 'scripts', 'locations', 'props']
            
            for dir_name in directories_to_clean:
                dir_path = base_path / dir_name
                if dir_path.exists() and dir_path.is_dir():
                    for file_path in dir_path.glob('*.json'):
                        if not file_path.name.startswith('temp_'):
                            try:
                                file_path.unlink()
                                deleted_files.append(f"{dir_name}/{file_path.name}")
                            except Exception as e:
                                logger.error(f"删除文件失败 {file_path}: {e}")
            
            if deleted_files:
                logger.info(f"强制覆盖模式：已删除 {len(deleted_files)} 个现有文件")

        # 0. 同步世界信息
        world = WorldModel.get_by_id(int(world_id))
        if world:
            world_data = {
                'id': world.id,
                'name': world.name,
                'story_outline': world.story_outline,
                'visual_style': world.visual_style,
                'era_environment': world.era_environment,
                'color_language': world.color_language,
                'composition_preference': world.composition_preference,
                'user_id': world.user_id
            }
            new_world_json = json.dumps(world_data, ensure_ascii=False, indent=2)
            world_file = base_path / "worlds" / f"world_{world_id}.json"
            file_name = f"world_{world_id}.json"
            
            if world_file.exists():
                existing_content = world_file.read_text(encoding='utf-8')
                if not compare_json_content(new_world_json, existing_content, file_name):
                    if force_overwrite:
                        file_manager.save_world(world_data, user_id, world_id)
                        result['diff_files'].append(file_name)
                        result['overwritten_files'].append(file_name)
                    else:
                        result['diff_files'].append(file_name)
                        result['skipped_files'].append(file_name)
            else:
                file_manager.save_world(world_data, user_id, world_id)

        # 1. 同步角色卡
        characters_result = CharacterModel.list_by_world(int(world_id), page=1, page_size=1000)
        characters = characters_result.get('data', []) if isinstance(characters_result, dict) else []
        for char in characters:
            if char.get('user_id') != int(user_id):
                continue
                
            try:
                existing_char_data = file_manager.get_character(char.get('name'), user_id, world_id)
                preserve_empty_other_info = (
                    existing_char_data and 
                    isinstance(existing_char_data, dict) and 
                    existing_char_data.get('other_info') == ""
                )
            except:
                existing_char_data = None
                preserve_empty_other_info = False
            
            sync_other_info = "" if preserve_empty_other_info else char.get('other_info')
            
            char_file = base_path / "characters" / f"character_{char.get('name')}.json"
            file_name = f"character_{char.get('name')}.json"
            
            if char_file.exists():
                temp_filename = f"temp_character_{char.get('name')}.json"
                temp_result = create_character_json(
                    user_id=user_id,
                    world_id=world_id,
                    auth_token=auth_token,
                    name=char.get('name'),
                    age=char.get('age'),
                    identity=char.get('identity'),
                    appearance=char.get('appearance'),
                    personality=char.get('personality'),
                    behavior=char.get('behavior'),
                    other_info=sync_other_info,
                    reference_image=char.get('reference_image'),
                    _temp_filename=temp_filename
                )
                
                if temp_result.get('success'):
                    temp_file = base_path / "characters" / temp_filename
                    if temp_file.exists():
                        try:
                            new_content = temp_file.read_text(encoding='utf-8')
                            existing_content = char_file.read_text(encoding='utf-8')
                            
                            if not compare_json_content(new_content, existing_content, file_name):
                                if force_overwrite:
                                    create_character_json(
                                        user_id=user_id,
                                        world_id=world_id,
                                        auth_token=auth_token,
                                        name=char.get('name'),
                                        age=char.get('age'),
                                        identity=char.get('identity'),
                                        appearance=char.get('appearance'),
                                        personality=char.get('personality'),
                                        behavior=char.get('behavior'),
                                        other_info=sync_other_info,
                                        reference_image=char.get('reference_image')
                                    )
                                    result['diff_files'].append(file_name)
                                    result['overwritten_files'].append(file_name)
                                else:
                                    result['diff_files'].append(file_name)
                                    result['skipped_files'].append(file_name)
                        finally:
                            if temp_file.exists():
                                temp_file.unlink()
            else:
                create_character_json(
                    user_id=user_id,
                    world_id=world_id,
                    auth_token=auth_token,
                    name=char.get('name'),
                    age=char.get('age'),
                    identity=char.get('identity'),
                    appearance=char.get('appearance'),
                    personality=char.get('personality'),
                    behavior=char.get('behavior'),
                    other_info=sync_other_info,
                    reference_image=char.get('reference_image')
                )
        
        # 2. 同步剧本
        scripts_result = ScriptModel.list_by_world(int(world_id), page=1, page_size=1000)
        scripts = scripts_result.get('data', []) if isinstance(scripts_result, dict) else []
        for script in scripts:
            if script.get('user_id') != int(user_id) or not script.get('content'):
                continue
                
            script_data = {
                'title': script.get('title'),
                'episode_number': script.get('episode_number'),
                'content': script.get('content'),
                'create_time': script.get('create_time'),
                'update_time': script.get('update_time')
            }
            new_script_json = json.dumps(script_data, ensure_ascii=False, indent=2)
            script_file = base_path / "scripts" / f"script_{script.get('title')}.json"
            file_name = f"script_{script.get('title')}.json"
            
            if script_file.exists():
                existing_content = script_file.read_text(encoding='utf-8')
                if not compare_json_content(new_script_json, existing_content, file_name):
                    if force_overwrite:
                        file_manager.save_script(script.get('title'), new_script_json, user_id, world_id)
                        result['diff_files'].append(file_name)
                        result['overwritten_files'].append(file_name)
                    else:
                        result['diff_files'].append(file_name)
                        result['skipped_files'].append(file_name)
            else:
                file_manager.save_script(script.get('title'), new_script_json, user_id, world_id)
        
        # 3. 同步场景
        locations_result = LocationModel.list_by_world(int(world_id), page=1, page_size=1000)
        locations = locations_result.get('data', []) if isinstance(locations_result, dict) else []
        for loc in locations:
            if loc.get('user_id') != int(user_id):
                continue
                
            loc_file = base_path / "locations" / f"location_{loc.get('name')}.json"
            file_name = f"location_{loc.get('name')}.json"
            
            if loc_file.exists():
                temp_filename = f"temp_location_{loc.get('name')}.json"
                temp_result = create_location_json(
                    user_id=user_id,
                    world_id=world_id,
                    auth_token=auth_token,
                    name=loc.get('name'),
                    description=loc.get('description'),
                    reference_image=loc.get('reference_image'),
                    _temp_filename=temp_filename
                )
                
                if temp_result.get('success'):
                    temp_file = base_path / "locations" / temp_filename
                    if temp_file.exists():
                        try:
                            new_content = temp_file.read_text(encoding='utf-8')
                            existing_content = loc_file.read_text(encoding='utf-8')
                            
                            if not compare_json_content(new_content, existing_content, file_name):
                                if force_overwrite:
                                    create_location_json(
                                        user_id=user_id,
                                        world_id=world_id,
                                        auth_token=auth_token,
                                        name=loc.get('name'),
                                        description=loc.get('description'),
                                        reference_image=loc.get('reference_image')
                                    )
                                    result['diff_files'].append(file_name)
                                    result['overwritten_files'].append(file_name)
                                else:
                                    result['diff_files'].append(file_name)
                                    result['skipped_files'].append(file_name)
                        finally:
                            if temp_file.exists():
                                temp_file.unlink()
            else:
                create_location_json(
                    user_id=user_id,
                    world_id=world_id,
                    auth_token=auth_token,
                    name=loc.get('name'),
                    description=loc.get('description'),
                    reference_image=loc.get('reference_image')
                )
        
        # 4. 同步道具
        props_result = PropsModel.list_by_world(int(world_id), page=1, page_size=1000)
        props = props_result.get('data', []) if isinstance(props_result, dict) else []
        for prop in props:
            if prop.get('user_id') != int(user_id):
                continue
                
            prop_file = base_path / "props" / f"prop_{prop.get('name')}.json"
            file_name = f"prop_{prop.get('name')}.json"
            
            if prop_file.exists():
                temp_filename = f"temp_prop_{prop.get('name')}.json"
                temp_result = create_prop_json(
                    user_id=user_id,
                    world_id=world_id,
                    auth_token=auth_token,
                    name=prop.get('name'),
                    prop_type=prop.get('type'),
                    description=prop.get('content'),
                    reference_image=prop.get('reference_image'),
                    _temp_filename=temp_filename
                )
                
                if temp_result.get('success'):
                    temp_file = base_path / "props" / temp_filename
                    if temp_file.exists():
                        try:
                            new_content = temp_file.read_text(encoding='utf-8')
                            existing_content = prop_file.read_text(encoding='utf-8')
                            
                            if not compare_json_content(new_content, existing_content, file_name):
                                if force_overwrite:
                                    create_prop_json(
                                        user_id=user_id,
                                        world_id=world_id,
                                        auth_token=auth_token,
                                        name=prop.get('name'),
                                        prop_type=prop.get('type'),
                                        description=prop.get('content'),
                                        reference_image=prop.get('reference_image')
                                    )
                                    result['diff_files'].append(file_name)
                                    result['overwritten_files'].append(file_name)
                                else:
                                    result['diff_files'].append(file_name)
                                    result['skipped_files'].append(file_name)
                        finally:
                            if temp_file.exists():
                                temp_file.unlink()
            else:
                create_prop_json(
                    user_id=user_id,
                    world_id=world_id,
                    auth_token=auth_token,
                    name=prop.get('name'),
                    prop_type=prop.get('type'),
                    description=prop.get('content'),
                    reference_image=prop.get('reference_image')
                )
        
        logger.info(f"数据库同步完成: user_id={user_id}, world_id={world_id}, force_overwrite={force_overwrite}")
        if result['diff_files']:
            if force_overwrite:
                logger.info(f"  已覆盖的差异文件: {result['overwritten_files']}")
            else:
                logger.info(f"  跳过的差异文件: {result['skipped_files']}")
        if result['local_only_files']:
            logger.info(f"  本地存在但数据库不存在的文件: {result['local_only_files']}")
            
    except Exception as e:
        logger.error(f"数据库同步失败: {e}")
        result['success'] = False
    
    return result

# ==================== 请求模型定义 ====================

class SessionCreateRequest(BaseModel):
    user_id: str
    world_id: str
    auth_token: str = ""
    model: Optional[str] = None
    model_id: Optional[int] = None

class TaskCreateRequest(BaseModel):
    message: str
    auth_token: str = ""
    model: Optional[str] = None
    model_id: Optional[int] = None
    vendor_id: int = 1

class ModelChangeRequest(BaseModel):
    model: str
    model_id: Optional[int] = None
    auth_token: str = ""

class SyncFilesRequest(BaseModel):
    user_id: str
    world_id: str

class SubmitDatabaseRequest(BaseModel):
    user_id: str
    world_id: str

class CharacterSaveRequest(BaseModel):
    content: Dict[str, Any]

class ScriptSaveRequest(BaseModel):
    content: Dict[str, Any]

class LocationSaveRequest(BaseModel):
    content: Dict[str, Any]

class PropSaveRequest(BaseModel):
    content: Dict[str, Any]

class WorldCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""

class WorldUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class VerificationSubmitRequest(BaseModel):
    approved: bool
    user_input: Optional[str] = None

# ==================== 会话管理 API ====================

@router.post('/session/create')
@require_permission("script_session:create")
async def create_session(request: Request, session_request: SessionCreateRequest):
    """创建新会话"""
    try:
        # 验证 auth_token
        is_valid, error_response = await verify_auth_token(session_request.user_id, session_request.auth_token)
        if not is_valid:
            return JSONResponse(error_response, status_code=401)
        
        # 从数据库同步数据到文件系统（不强制覆盖，有差异时跳过）
        sync_result = sync_database_to_files(session_request.user_id, session_request.world_id, session_request.auth_token, force_overwrite=False)
        if sync_result['skipped_files']:
            logger.info(f"create_session: 以下文件存在差异，已跳过: {sync_result['skipped_files']}")
        
        # 生成会话ID
        session_id = str(uuid.uuid4())
        
        # 创建 ChatSession（包含 PMAgent）
        session = ChatSession(
            session_id=session_id,
            task_manager=task_manager,
            file_manager=file_manager,
            tool_executor=tool_executor,
            agents_config=agents_config,
            system_prompt=None,  # 使用 PMAgent 的默认构建逻辑
            user_id=session_request.user_id,
            world_id=session_request.world_id,
            auth_token=session_request.auth_token,
            model=session_request.model,
            model_id=session_request.model_id
        )

        # 存储会话到数据库
        if not session_storage.save_session(session, expires_hours=24):
            logger.error(f'会话保存到数据库失败 - session_id: {session_id}')
            return JSONResponse({
                'success': False,
                'error': '会话保存失败'
            }, status_code=500)

        logger.info(f'会话创建成功 - session_id: {session_id}, user_id: {session_request.user_id}, world_id: {session_request.world_id}')
        
        return JSONResponse({
            'success': True,
            'message': '会话创建成功（多智能体模式）',
            'session_id': session_id,
            'user_id': session_request.user_id,
            'world_id': session_request.world_id,
            'skipped_files': sync_result.get('skipped_files', []),
            'local_only_files': sync_result.get('local_only_files', [])
        })
    except Exception as e:
        logger.error(f'创建会话失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.get('/session/{session_id}/history')
@require_permission("script_session:view")
async def get_session_history(request: Request, session_id: str):
    """获取会话历史"""
    try:
        # 从数据库加载会话
        session = session_storage.load_session(
            session_id=session_id,
            task_manager=task_manager,
            file_manager=file_manager,
            tool_executor=tool_executor,
            agents_config=agents_config
        )

        if not session:
            return JSONResponse({
                'success': False,
                'error': '会话不存在'
            }, status_code=404)

        return JSONResponse({
            'success': True,
            'history': session.get_history(),
            'created_at': session.created_at.isoformat() if session.created_at else None,
            'updated_at': session.updated_at.isoformat() if session.updated_at else None
        })
    except Exception as e:
        logger.error(f'获取会话历史失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.post('/session/{session_id}/clear')
@require_permission("script_session:clear_history")
async def clear_session_history(request: Request, session_id: str):
    """清空会话历史"""
    try:
        # 从数据库加载会话
        session = session_storage.load_session(
            session_id=session_id,
            task_manager=task_manager,
            file_manager=file_manager,
            tool_executor=tool_executor,
            agents_config=agents_config
        )

        if not session:
            return JSONResponse({
                'success': False,
                'error': '会话不存在'
            }, status_code=404)

        # 清空历史
        session.clear_history()

        # 持久化到数据库
        from model.chat_sessions import ChatSessionsModel
        ChatSessionsModel.clear_history(session_id)

        return JSONResponse({
            'success': True,
            'message': '会话历史已清空'
        })
    except Exception as e:
        logger.error(f'清空会话历史失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.post('/session/clear-directory')
async def clear_user_directory(request: SyncFilesRequest):
    """清空用户世界目录"""
    # TODO: 实现清空目录逻辑
    return JSONResponse({
        'success': True,
        'message': '目录已清空'
    })

@router.post('/session/{session_id}/model')
@require_permission("script_session:change_model")
async def set_session_model(request: Request, session_id: str, model_request: ModelChangeRequest):
    """切换会话模型"""
    try:
        # 从数据库加载会话
        session = session_storage.load_session(
            session_id=session_id,
            task_manager=task_manager,
            file_manager=file_manager,
            tool_executor=tool_executor,
            agents_config=agents_config
        )

        if not session:
            return JSONResponse({
                'success': False,
                'error': '会话不存在'
            }, status_code=404)

        # 验证模型是否有效
        if model_request.auth_token:
            is_valid, valid_models, error_msg = await validate_model(model_request.model, model_request.auth_token)
            if not is_valid:
                return JSONResponse({
                    'success': False,
                    'error': error_msg,
                    'valid_models': valid_models
                }, status_code=400)

        # 更新模型 - 使用 ChatSession 的 set_model 方法
        model_id = None
        if model_request.model_id is not None:
            try:
                model_id = int(model_request.model_id)
            except (TypeError, ValueError):
                return JSONResponse({
                    'success': False,
                    'error': 'model_id 必须为数字'
                }, status_code=400)

        session.set_model(model_request.model, model_id)

        # 持久化到数据库 - 同时更新过期时间以延长 session 有效期
        from datetime import datetime, timedelta
        from model.chat_sessions import ChatSessionsModel
        expires_at = datetime.now() + timedelta(hours=24)
        ChatSessionsModel.update_model(
            session_id=session_id,
            model=model_request.model,
            model_id=model_id,
            expires_at=expires_at
        )

        logger.info(f'模型切换成功 - session_id: {session_id}, model: {model_request.model}')

        return JSONResponse({
            'success': True,
            'message': '模型切换成功',
            'model': model_request.model
        })
    except Exception as e:
        logger.error(f'切换模型失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


# ==================== 生图模型配置 API ====================

@router.get('/text-to-image-models')
async def get_text_to_image_models():
    """获取可用的生图模型列表（从统一配置读取）"""
    try:
        models_config = _get_text_to_image_models_from_config()
        models = [
            {
                "task_id": task_id,
                "name": info["name"],
                "computing_power": info["computing_power"],
                "supports_grid_image": info.get("supports_grid_image", False)
            }
            for task_id, info in models_config.items()
        ]
        return JSONResponse({
            "success": True,
            "models": models,
            "default_task_id": DEFAULT_TEXT_TO_IMAGE_TASK_ID
        })
    except Exception as e:
        logger.error(f'获取生图模型列表失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


@router.post('/text-to-image-model')
async def set_text_to_image_model(request: Request):
    """设置当前会话的生图模型"""
    try:
        data = await request.json()
        user_id = str(data.get('user_id', ''))
        world_id = str(data.get('world_id', ''))
        session_id = data.get('session_id')
        # 支持 model_id 和 task_id 两种参数名
        task_id = data.get('task_id') or data.get('model_id')

        # 如果没有提供 user_id 和 world_id，尝试从 session 中获取
        if (not user_id or not world_id) and session_id:
            session = session_storage.load_session(
                session_id=session_id,
                task_manager=task_manager,
                file_manager=file_manager,
                tool_executor=tool_executor,
                agents_config=agents_config
            )
            if session and hasattr(session, 'user_id') and hasattr(session, 'world_id'):
                user_id = str(session.user_id)
                world_id = str(session.world_id)
                logger.info(f'从 session 获取 user_id 和 world_id - session_id: {session_id}, user_id: {user_id}, world_id: {world_id}')

        if not user_id or not world_id:
            return JSONResponse({
                'success': False,
                'error': 'user_id 和 world_id 不能为空'
            }, status_code=400)

        if task_id is None:
            return JSONResponse({
                'success': False,
                'error': 'task_id 不能为空'
            }, status_code=400)

        try:
            task_id = int(task_id)
        except (TypeError, ValueError):
            return JSONResponse({
                'success': False,
                'error': 'task_id 必须为数字'
            }, status_code=400)

        # 从配置获取有效模型列表
        models_config = _get_text_to_image_models_from_config()
        if task_id not in models_config:
            return JSONResponse({
                'success': False,
                'error': f'无效的 task_id: {task_id}，有效值为: {list(models_config.keys())}'
            }, status_code=400)

        set_text_to_image_model_id(user_id, world_id, task_id)

        # 如果提供了 session_id，同时更新数据库中的 chat_sessions 表
        if session_id:
            try:
                from model.chat_sessions import ChatSessionsModel
                ChatSessionsModel.update_model(
                    session_id=session_id,
                    model=None,  # 不更新 LLM 模型
                    model_id=None,  # 不更新 LLM 模型 ID
                    text_to_image_model_id=task_id  # 只更新生图模型 ID
                )
                logger.info(f'已更新数据库中的生图模型 - session_id: {session_id}, task_id: {task_id}')
            except Exception as db_error:
                logger.error(f'更新数据库生图模型失败: {db_error}')
                # 数据库更新失败不影响内存配置更新，继续执行

        model_info = models_config[task_id]
        logger.info(f'生图模型设置成功 - user_id: {user_id}, world_id: {world_id}, task_id: {task_id}, model: {model_info["name"]}')

        return JSONResponse({
            'success': True,
            'message': '生图模型设置成功',
            'task_id': task_id,
            'model_name': model_info["name"]
        })
    except Exception as e:
        logger.error(f'设置生图模型失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


@router.get('/text-to-image-model')
async def get_current_text_to_image_model(
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...)
):
    """获取当前会话的生图模型配置"""
    try:
        task_id = get_text_to_image_model_id(user_id, world_id)
        models_config = _get_text_to_image_models_from_config()
        model_info = models_config.get(task_id, models_config.get(DEFAULT_TEXT_TO_IMAGE_TASK_ID, {}))

        return JSONResponse({
            'success': True,
            'task_id': task_id,
            'model_name': model_info.get("name", "unknown"),
            'computing_power': model_info.get("computing_power", 0)
        })
    except Exception as e:
        logger.error(f'获取生图模型配置失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


@router.get('/sessions')
async def list_sessions(
    user_id: Optional[str] = QueryParam(None),
    world_id: Optional[str] = QueryParam(None)
):
    """列出所有会话"""
    try:
        from model.chat_sessions import ChatSessionsModel

        if user_id:
            # 从数据库查询用户的会话
            entities = ChatSessionsModel.list_by_user(user_id, world_id, active_only=True, limit=100)
            session_list = [
                {
                    'session_id': e.session_id,
                    'user_id': e.user_id,
                    'world_id': e.world_id,
                    'created_at': e.created_at.isoformat() if e.created_at else None,
                    'updated_at': e.updated_at.isoformat() if e.updated_at else None,
                    'model': e.model,
                    'message_count': len(e.conversation_history)
                }
                for e in entities
            ]
        else:
            # 列出缓存中的会话（用于调试）
            session_list = []
            cached_ids = session_storage.get_cached_sessions()
            for sid in cached_ids:
                session = session_storage.load_session(
                    session_id=sid,
                    task_manager=task_manager,
                    file_manager=file_manager,
                    tool_executor=tool_executor,
                    agents_config=agents_config
                )
                if session:
                    session_list.append({
                        'session_id': sid,
                        'user_id': session.user_id,
                        'world_id': session.world_id,
                        'created_at': session.created_at.isoformat() if session.created_at else None,
                        'updated_at': session.updated_at.isoformat() if session.updated_at else None,
                        'message_count': len(session.get_history())
                    })

        return JSONResponse({
            'success': True,
            'sessions': session_list
        })
    except Exception as e:
        logger.error(f'获取会话列表失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

# ==================== 模型和算力 API ====================

@router.get('/models')
async def get_available_models(
    auth_token: Optional[str] = QueryParam(None),
    authorization: Optional[str] = Header(None)
):
    """获取可用的 AI 模型列表"""
    try:
        # 从query参数或header获取token
        token = auth_token or (authorization.replace('Bearer ', '') if authorization else None)
        
        if not token:
            return JSONResponse({
                'success': False,
                'error': '缺少 auth_token 参数'
            }, status_code=400)
        
        # 调用perseids服务获取模型列表
        headers = {'Authorization': f'Bearer {token}'}
        success, message, response_data = await async_make_perseids_request(
            endpoint='user/models',
            method='GET',
            headers=headers
        )
        
        models = []
        if not success:
            logger.info(f"获取模型列表失败: {message}")
            # 检测 token 过期
            if '无效或已过期' in message or 'token' in message.lower() or '认证' in message:
                return JSONResponse({
                    'success': False,
                    'error': message,
                    'error_code': 'TOKEN_EXPIRED',
                    'token_expired': True
                }, status_code=401)
        else:
            logger.info(f"模型列表响应: {response_data}")
            remote_models = response_data.get('models', []) if isinstance(response_data, dict) else []
            for idx, model_info in enumerate(remote_models):
                model_id = model_info.get('id')
                input_token_threshold = None
                context_window = None
                try:
                    if model_id:
                        vendor_model = VendorModelModel.get_by_vendor_model_for_billing(
                            vendor_id=1,
                            model_id=int(model_id),
                            raw_input_token=0
                        )
                        if vendor_model and vendor_model.input_token_threshold:
                            input_token_threshold = vendor_model.input_token_threshold
                except Exception as vm_err:
                    logger.warning(f"获取模型 {model_id} 的 vendor_model 失败: {vm_err}")
                # 从本地 model 表获取上下文窗口配置
                try:
                    from model.model import ModelModel
                    local_model = ModelModel.get_by_id(int(model_id)) if model_id is not None else None
                    if local_model:
                        context_window = local_model.context_window
                except Exception:
                    pass
                models.append({
                    'id': str(model_id),
                    'name': model_info.get('model_name'),
                    'description': model_info.get('note') or '',
                    'category': 'perseids',
                    'recommended': model_id == 1,
                    'input_token_threshold': input_token_threshold,
                    'context_window': context_window
                })

        if not models:
            models = []
        
        return JSONResponse({
            'success': True,
            'models': models
        })
    except Exception as e:
        logger.error(f'获取模型列表失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

# ==================== 文件同步 API ====================

@router.post('/sync-files')
async def sync_files(request: SyncFilesRequest):
    """同步数据库到文件系统"""
    try:
        user_id = request.user_id
        world_id = request.world_id
        auth_token = getattr(request, 'auth_token', '')
        
        # 调用同步函数（强制覆盖）
        sync_result = sync_database_to_files(user_id, world_id, auth_token, force_overwrite=True)
        
        response_data = {
            'success': True,
            'message': '数据库内容已同步到文件系统'
        }
        
        # 如果有差异文件被覆盖，添加提示信息
        if sync_result['overwritten_files']:
            response_data['overwritten_files'] = sync_result['overwritten_files']
            response_data['message'] = f"数据库内容已同步到文件系统，以下文件存在差异并已被覆盖: {', '.join(sync_result['overwritten_files'])}"
        
        return JSONResponse(response_data)
    except Exception as e:
        logger.error(f'同步文件失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e),
            'message': f'同步失败: {str(e)}'
        }, status_code=500)

@router.post('/submit-to-database')
async def submit_to_database(request: SubmitDatabaseRequest):
    """批量将所有文件提交到数据库"""
    try:
        user_id = int(request.user_id)
        world_id = int(request.world_id)
        
        from model.world import WorldModel
        from model.character import CharacterModel
        from model.location import LocationModel
        from model.script import ScriptModel
        from model.props import PropsModel
        
        results = {
            'worlds': {'success': 0, 'failed': 0, 'skipped': 0, 'errors': []},
            'characters': {'success': 0, 'failed': 0, 'skipped': 0, 'errors': []},
            'scripts': {'success': 0, 'failed': 0, 'skipped': 0, 'errors': []},
            'locations': {'success': 0, 'failed': 0, 'skipped': 0, 'errors': []},
            'props': {'success': 0, 'failed': 0, 'skipped': 0, 'errors': []},
            'total': 0
        }
        
        try:
            # 1. 提交世界文件
            try:
                world_data = file_manager.get_world_json(str(user_id), str(world_id))
                if world_data:
                    existing_world = WorldModel.get_by_id(world_id)
                    if existing_world and existing_world.user_id == user_id:
                        update_data = {}
                        if 'name' in world_data:
                            update_data['name'] = world_data['name']
                        if 'description' in world_data:
                            update_data['description'] = world_data['description']
                        if 'story_outline' in world_data:
                            update_data['story_outline'] = world_data['story_outline']
                        if 'visual_style' in world_data:
                            update_data['visual_style'] = world_data['visual_style']
                        if 'era_environment' in world_data:
                            update_data['era_environment'] = world_data['era_environment']
                        if 'color_language' in world_data:
                            update_data['color_language'] = world_data['color_language']
                        if 'composition_preference' in world_data:
                            update_data['composition_preference'] = world_data['composition_preference']
                        
                        if update_data:
                            WorldModel.update(world_id, **update_data)
                            results['worlds']['success'] += 1
                            results['total'] += 1
                        else:
                            results['worlds']['skipped'] += 1
                    else:
                        results['worlds']['failed'] += 1
                        results['worlds']['errors'].append('世界不存在或无权限访问')
                else:
                    results['worlds']['skipped'] += 1
            except Exception as e:
                logger.error(f"世界文件处理异常: {e}")
                results['worlds']['failed'] += 1
                results['worlds']['errors'].append(f"世界文件: {str(e)}")

            # 2. 提交角色卡
            characters = file_manager.list_characters(str(user_id), str(world_id))
            for char in characters:
                try:
                    char_data = file_manager.get_character_json(char['name'], str(user_id), str(world_id))
                    if char_data and isinstance(char_data, dict):
                        name = char_data.get('name', char['name'])
                        age = char_data.get('age')
                        identity = char_data.get('identity')
                        appearance = char_data.get('appearance')
                        personality = char_data.get('personality')
                        behavior = char_data.get('behavior')
                        other_info = char_data.get('other_info')
                        reference_image = char_data.get('reference_image')
                        reference_images = char_data.get('reference_images')

                        # 使用 create_or_update 避免并发竞态导致的重复创建
                        CharacterModel.create_or_update(
                            world_id=world_id,
                            name=name,
                            user_id=user_id,
                            age=age,
                            identity=identity,
                            appearance=appearance,
                            personality=personality,
                            behavior=behavior,
                            other_info=other_info,
                            reference_image=reference_image,
                            reference_images=reference_images
                        )
                        results['characters']['success'] += 1
                        results['total'] += 1
                    else:
                        results['characters']['skipped'] += 1
                except Exception as e:
                    logger.error(f"角色处理异常 {char.get('name', 'UNKNOWN')}: {e}")
                    results['characters']['failed'] += 1
                    results['characters']['errors'].append(f"{char.get('name', 'UNKNOWN')}: {str(e)}")
            
            # 3. 提交剧本
            scripts = file_manager.list_scripts(str(user_id), str(world_id))
            for script in scripts:
                try:
                    script_data = file_manager.get_script(script['name'], str(user_id), str(world_id))
                    if script_data and isinstance(script_data, dict):
                        title = script_data.get('title', script['name'])
                        episode_number = script_data.get('episode_number')
                        content = script_data.get('content', '')
                        
                        if not content:
                            results['scripts']['skipped'] += 1
                            continue
                        
                        existing_script = None
                        if episode_number:
                            existing_script = ScriptModel.get_by_episode(world_id, episode_number)
                        
                        if existing_script:
                            ScriptModel.update(
                                existing_script.id,
                                content=content,
                                episode_number=episode_number,
                                title=title
                            )
                            results['scripts']['success'] += 1
                            results['total'] += 1
                        else:
                            ScriptModel.create(
                                world_id=world_id,
                                user_id=user_id,
                                title=title,
                                episode_number=episode_number,
                                content=content
                            )
                            results['scripts']['success'] += 1
                            results['total'] += 1
                    else:
                        results['scripts']['skipped'] += 1
                except Exception as e:
                    results['scripts']['failed'] += 1
                    results['scripts']['errors'].append(f"{script['name']}: {str(e)}")
            
            # 4. 提交场景
            locations = file_manager.list_locations(str(user_id), str(world_id))
            for loc in locations:
                try:
                    loc_data = file_manager.get_location_json(loc['name'], str(user_id), str(world_id))
                    if loc_data and isinstance(loc_data, dict):
                        name = loc_data.get('name', loc['name'])
                        parent_id_raw = loc_data.get('parent_id')
                        description = loc_data.get('description')
                        reference_image = loc_data.get('reference_image')
                        reference_images = loc_data.get('reference_images')

                        # 处理 parent_id：必须是整数或 None
                        parent_id = None
                        if parent_id_raw is not None:
                            try:
                                parent_id = int(parent_id_raw) if parent_id_raw else None
                            except (ValueError, TypeError):
                                parent_id = None

                        # 使用 create_or_update 避免并发竞态导致的重复创建
                        LocationModel.create_or_update(
                            world_id=world_id,
                            name=name,
                            user_id=user_id,
                            parent_id=parent_id,
                            reference_image=reference_image,
                            reference_images=reference_images,
                            description=description
                        )
                        results['locations']['success'] += 1
                        results['total'] += 1
                    else:
                        results['locations']['skipped'] += 1
                except Exception as e:
                    results['locations']['failed'] += 1
                    results['locations']['errors'].append(f"{loc['name']}: {str(e)}")
            
            # 5. 提交道具
            props = file_manager.list_props(str(user_id), str(world_id))
            for prop in props:
                try:
                    prop_data = file_manager.get_prop_json(prop['name'], str(user_id), str(world_id))
                    if prop_data and isinstance(prop_data, dict):
                        name = prop_data.get('name', prop['name'])
                        description = prop_data.get('description')
                        reference_image = prop_data.get('reference_image')
                        
                        # 使用 create_or_update 避免并发竞态导致的重复创建
                        PropsModel.create_or_update(
                            world_id=world_id,
                            name=name,
                            user_id=user_id,
                            content=description,
                            reference_image=reference_image
                        )
                        results['props']['success'] += 1
                        results['total'] += 1
                    else:
                        results['props']['skipped'] += 1
                except Exception as e:
                    results['props']['failed'] += 1
                    results['props']['errors'].append(f"{prop['name']}: {str(e)}")
            
            # 构建详细消息
            details = []
            skipped_details = []
            
            if results['characters']['success'] > 0:
                details.append(f"角色卡 {results['characters']['success']} 个")
            if results['scripts']['success'] > 0:
                details.append(f"剧本 {results['scripts']['success']} 个")
            if results['locations']['success'] > 0:
                details.append(f"场景 {results['locations']['success']} 个")
            if results['props']['success'] > 0:
                details.append(f"道具 {results['props']['success']} 个")
            
            total_skipped = (results['characters']['skipped'] + results['scripts']['skipped'] + 
                           results['locations']['skipped'] + results['props']['skipped'])
            
            if results['characters']['skipped'] > 0:
                skipped_details.append(f"角色卡 {results['characters']['skipped']} 个")
            if results['scripts']['skipped'] > 0:
                skipped_details.append(f"剧本 {results['scripts']['skipped']} 个")
            if results['locations']['skipped'] > 0:
                skipped_details.append(f"场景 {results['locations']['skipped']} 个")
            if results['props']['skipped'] > 0:
                skipped_details.append(f"道具 {results['props']['skipped']} 个")
            
            message_parts = []
            if details:
                message_parts.append(f"成功提交 {', '.join(details)}")
            if skipped_details:
                message_parts.append(f"跳过未改动 {', '.join(skipped_details)}")
            
            final_message = '；'.join(message_parts) if message_parts else "没有需要提交的内容"
            
            return JSONResponse({
                'success': True,
                'total': results['total'],
                'skipped': total_skipped,
                'details': results,
                'message': final_message
            })
            
        except Exception as e:
            raise e
            
    except Exception as e:
        logger.error(f'提交数据库失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e),
            'message': f'提交到数据库失败: {str(e)}'
        }, status_code=500)

# ==================== 剧本管理 API ====================
# 注意: 角色管理接口 /characters 已在 server.py 中实现，此处不再重复
# 注意: 剧本管理接口 /scripts 已在 server.py 中实现，此处不再重复
# 注意: 场景管理接口 /locations 已在 server.py 中实现，此处不再重复
# 注意: 道具管理接口 /props 已在 server.py 中实现，此处不再重复
# 注意: 世界管理接口 /worlds 已在 server.py 中实现，此处不再重复

@router.get('/world-files')
@require_permission("world:view_files")
async def get_world_files(
    request: Request,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...),
    auth_token: Optional[str] = QueryParam(None)
):
    """获取世界文件列表"""
    try:
        world_dir = file_manager._get_user_world_path(user_id, world_id)
        world_file_path = os.path.join(world_dir, 'worlds', f'world_{world_id}.json')
        
        worlds = []
        if os.path.exists(world_file_path):
            worlds.append({
                'name': f'world_{world_id}.json',
                'path': world_file_path,
                'exists': True
            })
        
        return JSONResponse({
            'success': True,
            'worlds': worlds
        })
    except Exception as e:
        logger.error(f'获取世界文件列表失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.get('/world-files/{filename}')
@require_permission("world:view_files")
async def get_world_file(
    request: Request,
    filename: str,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...),
    auth_token: Optional[str] = QueryParam(None),
    raw_json: bool = QueryParam(False)
):
    """获取世界文件内容"""
    try:
        world_dir = file_manager._get_user_world_path(user_id, world_id)
        world_file_path = os.path.join(world_dir, 'worlds', f'world_{world_id}.json')
        
        if not os.path.exists(world_file_path):
            # 如果文件不存在，从数据库获取世界信息并创建文件
            world = WorldModel.get_by_id(int(world_id))
            if world and world.user_id == int(user_id):
                # 创建世界文件目录
                os.makedirs(os.path.dirname(world_file_path), exist_ok=True)
                
                # 创建世界文件
                world_data = world.to_dict() if hasattr(world, 'to_dict') else {
                    'id': world.id,
                    'name': world.name,
                    'description': world.description,
                    'user_id': world.user_id
                }
                with open(world_file_path, 'w', encoding='utf-8') as f:
                    json.dump(world_data, f, ensure_ascii=False, indent=2)
            else:
                return JSONResponse({
                    'success': False,
                    'error': '世界不存在或无权限访问'
                }, status_code=404)
        
        # 读取文件内容
        with open(world_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if raw_json:
            # 返回JSON数据用于编辑
            json_data = json.loads(content)
            return JSONResponse({
                'success': True,
                'world': {
                    'content': content,
                    'json_data': json_data
                }
            })
        else:
            # 返回原始内容用于查看
            return JSONResponse({
                'success': True,
                'content': content
            })
    except Exception as e:
        logger.error(f'获取世界文件失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.post('/world-files/{filename}')
@require_permission("world:save_files")
async def save_world_file(
    request: Request,
    filename: str,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...),
    auth_token: Optional[str] = QueryParam(None)
):
    """保存世界文件"""
    try:
        data = await request.json()
        content = data.get('content')
        
        if not content:
            return JSONResponse({
                'success': False,
                'error': '缺少必需参数: content'
            }, status_code=400)
        
        world_dir = file_manager._get_user_world_path(user_id, world_id)
        world_file_path = os.path.join(world_dir, 'worlds', f'world_{world_id}.json')
        
        # 验证JSON格式
        try:
            world_data = json.loads(content)
        except json.JSONDecodeError as e:
            return JSONResponse({
                'success': False,
                'error': f'JSON格式错误: {str(e)}'
            }, status_code=400)
        
        # 创建目录
        os.makedirs(os.path.dirname(world_file_path), exist_ok=True)
        
        # 保存文件
        with open(world_file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return JSONResponse({
            'success': True,
            'message': '世界文件保存成功'
        })
    except Exception as e:
        logger.error(f'保存世界文件失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

# ==================== 智能体任务 API ====================

@router.post('/session/{session_id}/task')
@require_permission("agent_task:create")
async def create_agent_task(request: Request, session_id: str, task_request: TaskCreateRequest):
    """创建智能体任务"""
    try:
        # 从数据库加载会话
        session = session_storage.load_session(
            session_id=session_id,
            task_manager=task_manager,
            file_manager=file_manager,
            tool_executor=tool_executor,
            agents_config=agents_config
        )

        if not session:
            return JSONResponse({
                'success': False,
                'error': '会话不存在'
            }, status_code=404)

        user_id = session.user_id
        world_id = session.world_id
        auth_token = task_request.auth_token or session.auth_token

        # 验证 auth_token
        is_valid, error_response = await verify_auth_token(user_id, auth_token)
        if not is_valid:
            return JSONResponse(error_response, status_code=401)
        
        # 检查 model_id - 优先使用请求中的 model_id（前端最新选择），其次使用会话中的
        model_id = task_request.model_id if task_request.model_id is not None else (session.model_id if hasattr(session, 'model_id') else None)
        if not model_id:
            return JSONResponse({
                'success': False,
                'error': '缺少 model_id 参数'
            }, status_code=400)
        
        try:
            model_id = int(model_id)
        except (TypeError, ValueError):
            return JSONResponse({
                'success': False,
                'error': 'model_id 必须为数字'
            }, status_code=400)
        
        # 强制同步模型到 pm_agent：确保切换模型后实际使用正确的 LLM client
        # 前端传来的 model 是最新的用户选择，优先使用
        request_model = task_request.model
        if request_model and hasattr(session, 'pm_agent') and session.pm_agent:
            if session.pm_agent.model != request_model:
                logger.info(f'模型同步: pm_agent.model 从 "{session.pm_agent.model}" 切换为 "{request_model}"')
                session.pm_agent.model = request_model
                session.model = request_model
                session.model_id = model_id
        
        # 检查算力是否充足
        if auth_token:
            success, computing_power, error_msg = await check_computing_power(auth_token)
            if not success:
                # 检测 token 过期
                if error_msg and 'TOKEN_EXPIRED' in error_msg:
                    return JSONResponse({
                        'success': False,
                        'error': error_msg.replace('TOKEN_EXPIRED: ', ''),
                        'error_code': 'TOKEN_EXPIRED',
                        'token_expired': True
                    }, status_code=401)
                return JSONResponse({
                    'success': False,
                    'error': '算力检查失败',
                    'message': error_msg
                }, status_code=400)
            
            if computing_power < 1:
                return JSONResponse({
                    'success': False,
                    'error': '算力不足',
                    'message': '您的算力不足，请充值'
                }, status_code=400)
        
        # 验证消息不能为空
        if not task_request.message:
            return JSONResponse({
                'success': False,
                'error': '消息不能为空'
            }, status_code=400)
        
        # 创建任务（返回 task_id 字符串）
        task_id = task_manager.create_task(
            session_id=session_id,
            user_message=task_request.message,
            user_id=user_id,
            world_id=world_id,
            auth_token=auth_token,
            vendor_id=task_request.vendor_id,
            model_id=model_id
        )
        
        # 获取任务对象
        task = task_manager.get_task(task_id)
        
        logger.info(f'任务已创建: {task_id}, user_id: {user_id}, model_id: {model_id}')
        
        # 准备会话数据
        session_data = {
            'user_id': session.user_id,
            'world_id': session.world_id,
            'session_id': session_id
        }
        
        # 定义任务完成回调函数
        def on_task_complete(result):
            """任务完成后的回调函数"""
            try:
                logger.info(f"[Task] Task completed callback triggered for session {session_id}")
                # 任务完成后保存会话状态到数据库
                session_storage.save_session(session, expires_hours=24)
                logger.info(f"[Task] Session {session_id} saved after task completion")
            except Exception as e:
                logger.error(f"[Task] Failed to save session after task completion: {e}")

        # 启动任务（使用 PMAgent，后台线程执行）
        logger.info(f"[Task] Starting task execution for session {session_id}")
        task_manager.start_task(task, session.pm_agent, session_data, on_complete=on_task_complete)
        
        return JSONResponse({
            'success': True,
            'task_id': task_id,
            'session_id': session_id
        })
        
    except Exception as e:
        logger.error(f'创建任务失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.get('/task/{task_id}/stream')
@require_permission("agent_task:stream")
async def stream_task_messages(request: Request, task_id: str):
    """SSE流式获取任务消息（统一使用数据库轮询，支持跨进程）"""
    from model.agent_task_messages import AgentTaskMessagesModel
    from model.agent_tasks import AgentTasksModel

    # 检查任务是否存在（从数据库，支持跨 worker）
    if not task_manager.task_exists(task_id):
        return JSONResponse({
            'success': False,
            'error': '任务不存在'
        }, status_code=404)

    async def event_generator():
        try:
            logger.info(f"[SSE-STREAM] Starting SSE stream for task {task_id}")
            heartbeat_counter = 0
            message_count = 0
            last_message_id = 0  # 用于追踪已读取的消息

            # 立即发送连接确认消息
            yield f"data: {json.dumps({'type': 'connected', 'task_id': task_id}, ensure_ascii=False)}\n\n"

            while True:
                messages_to_send = []

                # 统一从数据库轮询消息（避免 worker 切换导致消息丢失）
                try:
                    db_messages = await asyncio.to_thread(
                        AgentTaskMessagesModel.get_messages_after,
                        task_id, last_message_id, 50
                    )
                    for db_msg in db_messages:
                        messages_to_send.append(db_msg.to_dict())
                        last_message_id = max(last_message_id, db_msg.id)
                except Exception as e:
                    logger.error(f"[SSE-STREAM] Failed to poll messages from database: {e}")

                # 发送消息
                for msg in messages_to_send:
                    message_count += 1
                    msg_type = msg.get('type', 'unknown')
                    logger.info(f"[SSE-STREAM] Got message #{message_count}, type: {msg_type}")
                    if msg.get('content'):
                        logger.info(f"[SSE-STREAM] Message content preview: {str(msg.get('content'))[:100]}...")

                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"

                    # 如果是完成或错误消息，结束流
                    if msg_type in ['done', 'error']:
                        logger.info(f"[SSE-STREAM] Stream ending, type: {msg_type}")
                        return

                    heartbeat_counter = 0

                # 没有消息时的处理
                if not messages_to_send:
                    heartbeat_counter += 1

                    # 每9秒发送心跳
                    if heartbeat_counter >= 3:
                        yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now().isoformat()}, ensure_ascii=False)}\n\n"
                        heartbeat_counter = 0

                    # 检查任务状态（从数据库）
                    try:
                        db_task = await asyncio.to_thread(AgentTasksModel.get_by_task_id, task_id)
                        if db_task and db_task.status in ['completed', 'failed', 'cancelled']:
                            logger.info(f"[SSE-STREAM] Task status changed to {db_task.status}, ending stream")
                            yield f"data: {json.dumps({'type': 'done', 'status': db_task.status}, ensure_ascii=False)}\n\n"
                            return
                    except Exception as e:
                        logger.error(f"[SSE-STREAM] Failed to check task status: {e}")

                # 短暂等待后继续轮询（避免频繁查询数据库）
                await asyncio.sleep(0.3)

            logger.info(f"[SSE-STREAM] Stream completed, sent {message_count} messages")

        except Exception as e:
            logger.error(f"[SSE-STREAM] Stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

@router.get('/task/{task_id}/status')
@require_permission("agent_task:view")
async def get_task_status(request: Request, task_id: str):
    """获取任务状态"""
    try:
        task = task_manager.get_task(task_id)
        
        if not task:
            return JSONResponse({
                'success': False,
                'error': '任务不存在'
            }, status_code=404)
        
        return JSONResponse({
            'success': True,
            'task': task.to_dict()
        })
        
    except Exception as e:
        logger.error(f'获取任务状态失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.post('/verification/{verification_id}')
@require_permission("agent_task:verify")
async def submit_verification(request: Request, verification_id: str, verify_request: VerificationSubmitRequest):
    """提交人工验证结果"""
    try:
        success = task_manager.submit_verification(
            verification_id=verification_id,
            approved=verify_request.approved,
            user_input=verify_request.user_input
        )
        
        if not success:
            return JSONResponse({
                'success': False,
                'error': '验证请求不存在'
            }, status_code=404)
        
        return JSONResponse({
            'success': True,
            'message': '验证提交成功'
        })
        
    except Exception as e:
        logger.error(f'提交验证失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

# ==================== 文件操作 API ====================

class FileContentRequest(BaseModel):
    user_id: str
    world_id: str
    content: str

# 角色卡管理接口

@router.get('/characters-files')
@require_permission("character:list")
async def list_characters(
    request: Request,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...)
):
    """列出所有角色卡"""
    try:
        characters = file_manager.list_characters(user_id, world_id)
        
        return JSONResponse({
            'success': True,
            'characters': characters,
            'total': len(characters)
        })
    except Exception as e:
        logger.error(f'列出角色卡失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.get('/characters-files/{character_name}')
@require_permission("character:view")
async def get_character(
    request: Request,
    character_name: str,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...),
    raw_json: bool = QueryParam(False)
):
    """获取指定角色卡"""
    try:
        if raw_json:
            json_data = file_manager.get_character_json(character_name, user_id, world_id)
            if json_data is None:
                return JSONResponse({
                    'success': False,
                    'error': f'角色卡不存在: {character_name}'
                }, status_code=404)
            
            return JSONResponse({
                'success': True,
                'character': {
                    'name': character_name,
                    'content': json.dumps(json_data, ensure_ascii=False, indent=2),
                    'json_data': json_data
                }
            })
        else:
            content = file_manager.get_character(character_name, user_id, world_id)
            
            if content is None:
                return JSONResponse({
                    'success': False,
                    'error': f'角色卡不存在: {character_name}'
                }, status_code=404)
            
            return JSONResponse({
                'success': True,
                'character': {
                    'name': character_name,
                    'content': content
                }
            })
    except Exception as e:
        logger.error(f'获取角色卡失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.post('/characters-files/{character_name}')
@require_permission("character:create")
async def save_character(request: Request, character_name: str, file_request: FileContentRequest):
    """保存角色卡"""
    try:
        content = file_request.content.strip()
        
        if not content:
            return JSONResponse({
                'success': False,
                'error': '角色卡内容不能为空'
            }, status_code=400)
        
        success = file_manager.save_character(character_name, content, file_request.user_id, file_request.world_id)
        
        return JSONResponse({
            'success': success,
            'message': f'角色卡已保存: {character_name}' if success else '保存失败'
        })
    except Exception as e:
        logger.error(f'保存角色卡失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

# 剧本管理接口

@router.get('/scripts-files')
@require_permission("script:list")
async def list_scripts(
    request: Request,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...)
):
    """列出所有剧本"""
    try:
        scripts = file_manager.list_scripts(user_id, world_id)
        scripts.sort(key=lambda x: (x['episode_number'] is None, x['episode_number'] if x['episode_number'] is not None else 0, x['name']))
        
        return JSONResponse({
            'success': True,
            'scripts': scripts,
            'total': len(scripts)
        })
    except Exception as e:
        logger.error(f'列出剧本失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.get('/scripts-files/{script_name}')
@require_permission("script:view")
async def get_script(
    request: Request,
    script_name: str,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...),
    raw_json: bool = QueryParam(False)
):
    """获取指定剧本"""
    try:
        script_data = file_manager.get_script(script_name, user_id, world_id)
        
        if script_data is None:
            return JSONResponse({
                'success': False,
                'error': f'剧本不存在: {script_name}'
            }, status_code=404)
        
        if raw_json:
            return JSONResponse({
                'success': True,
                'script': {
                    'name': script_data.get('title', script_name),
                    'content': json.dumps(script_data, ensure_ascii=False, indent=2),
                    'json_data': script_data
                }
            })
        else:
            return JSONResponse({
                'success': True,
                'script': {
                    'name': script_data.get('title', script_name),
                    'content': script_data.get('content', ''),
                    'episode_number': script_data.get('episode_number'),
                    'title': script_data.get('title', script_name),
                    'created_at': script_data.get('create_time', ''),
                    'updated_at': script_data.get('update_time', '')
                }
            })
    except Exception as e:
        logger.error(f'获取剧本失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.post('/scripts-files/{script_name}')
@require_permission("script:create")
async def save_script(request: Request, script_name: str, file_request: FileContentRequest):
    """保存剧本"""
    try:
        content = file_request.content.strip()
        
        if not content:
            return JSONResponse({
                'success': False,
                'error': '剧本内容不能为空'
            }, status_code=400)
        
        success = file_manager.save_script(script_name, content, file_request.user_id, file_request.world_id)
        
        return JSONResponse({
            'success': success,
            'message': f'剧本已保存: {script_name}' if success else '保存失败'
        })
    except Exception as e:
        logger.error(f'保存剧本失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

# 场景管理接口

@router.get('/locations-files')
@require_permission("location:list")
async def list_locations(
    request: Request,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...)
):
    """列出所有场景"""
    try:
        locations = file_manager.list_locations(user_id, world_id)
        
        return JSONResponse({
            'success': True,
            'locations': locations,
            'count': len(locations)
        })
    except Exception as e:
        logger.error(f'列出场景失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.get('/locations-files/{location_name}')
@require_permission("location:view")
async def get_location(
    request: Request,
    location_name: str,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...),
    raw_json: bool = QueryParam(False)
):
    """获取场景内容"""
    try:
        if raw_json:
            json_data = file_manager.get_location_json(location_name, user_id, world_id)
            if json_data is None:
                return JSONResponse({
                    'success': False,
                    'error': f'场景不存在: {location_name}'
                }, status_code=404)
            
            return JSONResponse({
                'success': True,
                'location': {
                    'name': location_name,
                    'content': json.dumps(json_data, ensure_ascii=False, indent=2),
                    'json_data': json_data
                }
            })
        else:
            content = file_manager.get_location(location_name, user_id, world_id)
            
            if content is None:
                return JSONResponse({
                    'success': False,
                    'error': f'场景不存在: {location_name}'
                }, status_code=404)
            
            return JSONResponse({
                'success': True,
                'name': location_name,
                'content': content
            })
    except Exception as e:
        logger.error(f'获取场景失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.post('/locations-files/{location_name}')
@require_permission("location:create")
async def save_location(request: Request, location_name: str, file_request: FileContentRequest):
    """保存场景"""
    try:
        content = file_request.content
        
        if not content:
            return JSONResponse({
                'success': False,
                'error': '场景内容不能为空'
            }, status_code=400)
        
        success = file_manager.save_location(location_name, content, file_request.user_id, file_request.world_id)
        
        if not success:
            return JSONResponse({
                'success': False,
                'error': f'保存场景失败: {location_name}'
            }, status_code=500)
        
        return JSONResponse({
            'success': True,
            'message': f'场景已保存: {location_name}'
        })
    except Exception as e:
        logger.error(f'保存场景失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.patch('/locations-files/{location_name}/reference-images')
@require_permission("location:update")
async def update_location_reference_images(
    request: Request,
    location_name: str
):
    """
    更新场景的多角度参考图（reference_images 字段）
    仅更新 reference_images，不影响其他字段
    """
    try:
        body = await request.json()
        user_id = body.get('user_id')
        world_id = body.get('world_id')
        reference_images = body.get('reference_images')

        if not user_id or not world_id:
            return JSONResponse({
                'success': False,
                'error': 'user_id 和 world_id 是必填字段'
            }, status_code=400)

        if reference_images is None:
            return JSONResponse({
                'success': False,
                'error': 'reference_images 不能为空'
            }, status_code=400)

        # 生成安全的文件名
        safe_name = _sanitize_filename(location_name)
        filename = f"location_{safe_name}.json"
        file_path = file_manager.get_content_file_path(user_id, world_id, "locations", filename)

        # 检查文件是否存在
        if not os.path.exists(file_path):
            return JSONResponse({
                'success': False,
                'error': f'场景 "{location_name}" 不存在'
            }, status_code=404)

        # 读取现有数据
        with open(file_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)

        # 更新 reference_images 字段
        existing_data['reference_images'] = reference_images
        existing_data['updated_at'] = datetime.now().isoformat()

        # 保存更新后的数据
        success = file_manager.save_json_content(user_id, world_id, "locations", filename, existing_data)

        if not success:
            return JSONResponse({
                'success': False,
                'error': '保存场景参考图失败'
            }, status_code=500)

        # 同时更新数据库记录
        try:
            loc_record = LocationModel.get_by_name(int(world_id), location_name)
            if loc_record:
                LocationModel.update(
                    record_id=loc_record.id,
                    reference_images=reference_images
                )
        except Exception as db_err:
            logger.warning(f'更新数据库参考图失败（不影响文件保存）: {db_err}')

        return JSONResponse({
            'success': True,
            'message': f'场景 "{location_name}" 的参考图已更新',
            'reference_images': reference_images
        })

    except Exception as e:
        logger.error(f'更新场景参考图失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


# ==================== 场景多角度生图任务接口 ====================

class LocationMultiAngleTaskRequest(BaseModel):
    user_id: str
    world_id: str
    location_name: str
    main_image: str
    description: Optional[str] = None
    angles: List[Dict[str, Any]]  # [{angle: 90, label: '右侧 (90°)', angleKey: 'right'}, ...]
    model: Optional[str] = None
    auth_token: Optional[str] = None


@router.post('/location-multi-angle-tasks')
@require_permission("location:create")
async def create_location_multi_angle_task(
    request: Request,
    task_request: LocationMultiAngleTaskRequest
):
    """
    创建场景多角度生图任务
    任务会在后台队列中处理，用户可以稍后查询任务状态
    """
    try:
        import uuid
        from model import LocationMultiAngleTasksModel

        # 检查是否存在正在执行中的任务
        running_task = LocationMultiAngleTasksModel.has_running_task(
            user_id=task_request.user_id,
            world_id=task_request.world_id,
            location_name=task_request.location_name
        )

        if running_task:
            return JSONResponse({
                'success': False,
                'error': '该场景存在正在执行中的多角度生成任务，请等待当前任务完成后再操作',
                'task_key': running_task.task_key,
                'task_status': running_task.status
            }, status_code=400)

        # 生成唯一任务键
        task_key = f"loc_multi_{uuid.uuid4().hex[:12]}"

        # 创建任务记录
        task_id = LocationMultiAngleTasksModel.create(
            task_key=task_key,
            location_name=task_request.location_name,
            user_id=task_request.user_id,
            world_id=task_request.world_id,
            main_image=task_request.main_image,
            description=task_request.description,
            angles=task_request.angles,
            model=task_request.model,
            auth_token=task_request.auth_token
        )

        logger.info(f"创建场景多角度生图任务: {task_key}, location={task_request.location_name}, angles={len(task_request.angles)}")

        return JSONResponse({
            'success': True,
            'task_key': task_key,
            'task_id': task_id,
            'message': f'已创建多角度生图任务，{len(task_request.angles)} 个角度等待生成'
        })

    except Exception as e:
        logger.error(f'创建场景多角度生图任务失败: {str(e)}')
        import traceback
        logger.error(traceback.format_exc())
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


@router.get('/location-multi-angle-tasks/{task_key}')
@require_permission("location:view")
async def get_location_multi_angle_task(
    request: Request,
    task_key: str,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...)
):
    """
    获取场景多角度生图任务状态
    """
    try:
        from model import LocationMultiAngleTasksModel, LocationMultiAngleTaskStatus

        task = LocationMultiAngleTasksModel.get_by_task_key(task_key)

        if not task:
            return JSONResponse({
                'success': False,
                'error': '任务不存在'
            }, status_code=404)

        # 验证权限
        if task.user_id != user_id or task.world_id != world_id:
            return JSONResponse({
                'success': False,
                'error': '无权访问该任务'
            }, status_code=403)

        return JSONResponse({
            'success': True,
            'task': task.to_dict()
        })

    except Exception as e:
        logger.error(f'获取任务状态失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


@router.get('/location-multi-angle-tasks')
@require_permission("location:list")
async def list_location_multi_angle_tasks(
    request: Request,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...),
    limit: int = QueryParam(50)
):
    """
    获取用户的场景多角度生图任务列表
    """
    try:
        from model import LocationMultiAngleTasksModel

        tasks = LocationMultiAngleTasksModel.get_user_tasks(user_id, world_id, limit)

        return JSONResponse({
            'success': True,
            'tasks': [task.to_dict() for task in tasks],
            'count': len(tasks)
        })

    except Exception as e:
        logger.error(f'获取任务列表失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


# 道具管理接口

@router.get('/props-files')
@require_permission("prop:list")
async def list_props(
    request: Request,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...)
):
    """列出所有道具"""
    try:
        props = file_manager.list_props(user_id, world_id)
        
        return JSONResponse({
            'success': True,
            'props': props,
            'count': len(props)
        })
    except Exception as e:
        logger.error(f'列出道具失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.get('/props-files/{prop_name}')
@require_permission("prop:view")
async def get_prop(
    request: Request,
    prop_name: str,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...),
    raw_json: bool = QueryParam(False)
):
    """获取道具内容"""
    try:
        if raw_json:
            json_data = file_manager.get_prop_json(prop_name, user_id, world_id)
            if json_data is None:
                return JSONResponse({
                    'success': False,
                    'error': f'道具不存在: {prop_name}'
                }, status_code=404)
            
            return JSONResponse({
                'success': True,
                'prop': {
                    'name': prop_name,
                    'content': json.dumps(json_data, ensure_ascii=False, indent=2),
                    'json_data': json_data
                }
            })
        else:
            content = file_manager.get_prop(prop_name, user_id, world_id)
            
            if content is None:
                return JSONResponse({
                    'success': False,
                    'error': f'道具不存在: {prop_name}'
                }, status_code=404)
            
            return JSONResponse({
                'success': True,
                'name': prop_name,
                'content': content
            })
    except Exception as e:
        logger.error(f'获取道具失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.post('/props-files/{prop_name}')
@require_permission("prop:create")
async def save_prop(request: Request, prop_name: str, file_request: FileContentRequest):
    """保存道具"""
    try:
        content = file_request.content
        
        if not content:
            return JSONResponse({
                'success': False,
                'error': '道具内容不能为空'
            }, status_code=400)
        
        success = file_manager.save_prop(prop_name, content, file_request.user_id, file_request.world_id)
        
        if not success:
            return JSONResponse({
                'success': False,
                'error': f'保存道具失败: {prop_name}'
            }, status_code=500)
        
        return JSONResponse({
            'success': True,
            'message': f'道具已保存: {prop_name}'
        })
    except Exception as e:
        logger.error(f'保存道具失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


# ==================== 资产完成状态检查 API ====================

class CheckAssetsRequest(BaseModel):
    """检查资产完成状态请求"""
    world_id: int


@router.post('/check-assets-complete')
@require_permission("world:view")
async def check_assets_complete(request: Request, check_request: CheckAssetsRequest):
    """
    检查世界资产完成状态
    
    根据世界ID检查：
    1. 是否存在剧本
    2. 角色、场景、道具是否有参考图缺失
    
    Returns:
        {
            'code': 0,
            'data': {
                'has_script': bool,
                'missing_assets': [
                    {'type': '角色', 'items': ['角色名1', '角色名2']},
                    {'type': '场景', 'items': ['场景名1']},
                    {'type': '道具', 'items': ['道具名1']}
                ]
            }
        }
    """
    world_id = check_request.world_id
    
    try:
        result = {
            'has_script': False,
            'missing_assets': []
        }
        
        # 1. 检查是否存在剧本
        scripts_result = ScriptModel.list_by_world(world_id, page=1, page_size=1)
        result['has_script'] = scripts_result.get('total', 0) > 0
        
        # 2. 检查角色参考图
        characters_result = CharacterModel.list_by_world(world_id, page=1, page_size=1000)
        characters = characters_result.get('data', [])
        missing_characters = [
            c['name'] for c in characters 
            if not c.get('reference_image')
        ]
        if missing_characters:
            result['missing_assets'].append({
                'type': '角色',
                'items': missing_characters
            })
        
        # 3. 检查场景参考图
        locations_result = LocationModel.list_by_world(world_id, page=1, page_size=1000)
        locations = locations_result.get('data', [])
        missing_locations = [
            loc['name'] for loc in locations 
            if not loc.get('reference_image')
        ]
        if missing_locations:
            result['missing_assets'].append({
                'type': '场景',
                'items': missing_locations
            })
        
        # 4. 检查道具参考图
        props_result = PropsModel.list_by_world(world_id, page=1, page_size=1000)
        props = props_result.get('data', [])
        missing_props = [
            p['name'] for p in props 
            if not p.get('reference_image')
        ]
        if missing_props:
            result['missing_assets'].append({
                'type': '道具',
                'items': missing_props
            })
        
        return JSONResponse({
            'code': 0,
            'data': result
        })
        
    except Exception as e:
        logger.error(f'检查资产完成状态失败: {str(e)}')
        return JSONResponse({
            'code': -1,
            'message': f'检查失败: {str(e)}'
        }, status_code=500)


# ==================== 图片上传 API ====================

@router.post('/upload-image')
@require_permission("script_writer:upload_image")
async def upload_reference_image(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Form(...),
    world_id: str = Form(...),
    item_type: int = Form(...),
    auth_token: str = Form(...)
):
    """
    上传角色、场景、道具的参考图片
    
    Args:
        file: 图片文件
        user_id: 用户ID
        world_id: 世界ID
        item_type: 项目类型 (1=character, 2=location, 3=props)
        auth_token: 认证令牌
    
    Returns:
        图片访问URL
    """
    try:
        # 验证文件类型
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
        file_extension = os.path.splitext(file.filename or '')[1].lower()
        
        if file_extension not in allowed_extensions:
            return JSONResponse({
                'success': False,
                'error': f'不支持的文件类型。允许的类型: {", ".join(allowed_extensions)}'
            }, status_code=400)
        
        # 验证文件大小
        max_size_mb = get_dynamic_config_value('upload', 'max_image_size_mb', default=10)
        max_size_bytes = max_size_mb * 1024 * 1024
        
        # 读取文件内容
        content = await file.read()
        if len(content) > max_size_bytes:
            return JSONResponse({
                'success': False,
                'error': f'图片大小不能超过 {max_size_mb}MB'
            }, status_code=400)
        
        # 根据 item_type 确定存储路径
        if item_type == 1:  # character
            upload_dir = 'upload/character/pic'
        elif item_type == 2:  # location
            upload_dir = 'upload/location/pic'
        elif item_type == 3:  # props
            upload_dir = 'upload/props/pic'
        else:
            return JSONResponse({
                'success': False,
                'error': f'无效的 item_type: {item_type}'
            }, status_code=400)
        
        # 获取应用根目录
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_upload_dir = os.path.join(app_dir, upload_dir)
        
        # 创建目录
        os.makedirs(full_upload_dir, exist_ok=True)
        
        # 生成唯一文件名
        unique_id = uuid.uuid4().hex[:16]
        filename = f"{unique_id}{file_extension}"
        file_path = os.path.join(full_upload_dir, filename)
        
        # 保存文件
        with open(file_path, 'wb') as f:
            f.write(content)

        # 获取服务器地址
        server_host = get_config()["server"]["host"]

        # 返回URL
        url = f"{server_host.rstrip('/')}/{upload_dir}/{filename}"

        logger.info(f'图片上传成功: {url}')

        return JSONResponse({
            'success': True,
            'url': url
        })
        
    except Exception as e:
        logger.error(f'图片上传失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': f'上传失败: {str(e)}'
        }, status_code=500)


@router.delete('/staging-file')
@require_permission("script_writer:delete_staging_file")
async def delete_staging_file(
    request: Request,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...),
    relative_path: str = QueryParam(...),
    auth_token: str = QueryParam(...)
):
    """
    删除暂存区的角色、场景、道具、剧本文件
    
    Args:
        user_id: 用户ID
        world_id: 世界ID
        relative_path: 文件相对路径（从 script_writer 目录开始，如：2/130/props/prop_xxx.json）
        auth_token: 认证令牌
    
    Returns:
        删除结果
    """
    try:
        # 验证相对路径格式，防止路径遍历攻击
        if '..' in relative_path or relative_path.startswith('/'):
            logger.warning(f'检测到可疑路径: {relative_path}')
            return JSONResponse({
                'success': False,
                'error': '无效的文件路径'
            }, status_code=400)
        
        # 验证路径必须属于当前用户和世界
        expected_prefix = f"{user_id}/{world_id}/"
        if not relative_path.startswith(expected_prefix):
            logger.warning(f'路径不匹配用户世界: {relative_path}, 期望前缀: {expected_prefix}')
            return JSONResponse({
                'success': False,
                'error': '无效的文件路径：路径不属于当前用户和世界'
            }, status_code=403)
        
        # 验证文件类型（从路径中提取）
        path_parts = relative_path.split('/')
        if len(path_parts) < 4:
            return JSONResponse({
                'success': False,
                'error': '无效的文件路径格式'
            }, status_code=400)
        
        file_type = path_parts[2]  # user_id/world_id/file_type/filename
        allowed_types = ['characters', 'locations', 'props', 'scripts']
        if file_type not in allowed_types:
            return JSONResponse({
                'success': False,
                'error': f'不支持的文件类型。允许的类型: {", ".join(allowed_types)}'
            }, status_code=400)
        
        # 构建完整文件路径
        from config.constant import FilePathConstants
        file_manager = FileManager()
        base_dir = file_manager.base_dir / FilePathConstants._SCRIPT_WRITER_USER_DATA_SUBDIR
        file_path = base_dir / relative_path
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return JSONResponse({
                'success': False,
                'error': '文件不存在'
            }, status_code=404)
        
        # 读取文件内容，验证所属用户
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                file_data = json.load(f)
            
            # 验证文件所属用户
            file_user_id = str(file_data.get('user_id', ''))
            request_user_id = str(user_id)
            
            if file_user_id != request_user_id:
                logger.warning(f'用户 {request_user_id} 尝试删除用户 {file_user_id} 的文件: {file_path}')
                return JSONResponse({
                    'success': False,
                    'error': '无权限删除此文件：文件不属于当前用户'
                }, status_code=403)
        except json.JSONDecodeError:
            logger.error(f'文件格式错误，无法验证所属用户: {file_path}')
            return JSONResponse({
                'success': False,
                'error': '文件格式错误'
            }, status_code=400)
        except KeyError:
            logger.warning(f'文件缺少 user_id 字段: {file_path}')
            # 如果文件中没有 user_id 字段，为安全起见拒绝删除
            return JSONResponse({
                'success': False,
                'error': '文件缺少所属用户信息，无法验证权限'
            }, status_code=400)
        
        # 删除文件
        os.remove(file_path)
        
        logger.info(f'暂存区文件删除成功: {file_path}')
        
        return JSONResponse({
            'success': True,
            'message': '文件删除成功'
        })
        
    except Exception as e:
        logger.error(f'暂存区文件删除失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': f'删除失败: {str(e)}'
        }, status_code=500)


# ==================== 配置检查 API ====================
@router.get("/config/check")
async def check_configs(
    keys: str = QueryParam(..., description="配置键列表，逗号分隔，如 'llm.qwen.api_key,runninghub.api_key'"),
    authorization: Optional[str] = Header(None)
):
    """
    检查配置是否已配置（value 非空）

    用于前端判断某些功能是否可用（如 qwen 模型需要配置 api_key 才能选择）
    """
    # 验证token
    token = authorization.replace('Bearer ', '') if authorization else None
    if not token:
        return JSONResponse({"success": False, "error": "未授权"}, status_code=401)

    key_list = [k.strip() for k in keys.split(',')]
    results = {}

    for key in key_list:
        parts = key.split('.')
        if len(parts) >= 2:
            section = parts[0]
            sub_keys = parts[1:]
            value = get_dynamic_config_value(section, *sub_keys, default="")
            results[key] = bool(value and value.strip())
        else:
            results[key] = False

    return {"success": True, "results": results}
