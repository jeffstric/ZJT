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
from fastapi import APIRouter, Request, Query as QueryParam, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from perseids_server.utils.permission import require_permission
from config.config_util import get_dynamic_config_value

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

# 导入服务
from perseids_server.client import async_make_perseids_request

# 导入智能体系统
from script_writer_core.agents import TaskManager, TaskStatus, ToolExecutor
from script_writer_core.chat_session import ChatSession
from script_writer_core.file_manager import FileManager
logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(prefix="/api", tags=["script_writer"])

# 会话存储（内存中）
# 注意：这是临时方案，生产环境应使用数据库或Redis
sessions_storage: Dict[str, ChatSession] = {}
sessions_lock = threading.RLock()  # 使用可重入锁保护 sessions_storage 字典的并发访问

# 全局组件
task_manager = TaskManager()
# 指定项目根目录作为 base_dir，确保文件保存到正确位置
from utils.project_path import get_project_root
project_root = get_project_root()
file_manager = FileManager(base_dir=project_root)
tool_executor = ToolExecutor(file_manager=file_manager)

# 设置 mcp_tool 的全局 file_manager
from script_writer_core.mcp_tool import set_file_manager
set_file_manager(file_manager)

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
        
        # 存储会话
        with sessions_lock:
            sessions_storage[session_id] = session
        
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
        with sessions_lock:
            if session_id not in sessions_storage:
                return JSONResponse({
                    'success': False,
                    'error': '会话不存在'
                }, status_code=404)
            
            session = sessions_storage[session_id]
        return JSONResponse({
            'success': True,
            'history': session.get('history', []),
            'created_at': session.get('created_at'),
            'updated_at': session.get('updated_at')
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
        with sessions_lock:
            if session_id not in sessions_storage:
                return JSONResponse({
                    'success': False,
                    'error': '会话不存在'
                }, status_code=404)
            
            sessions_storage[session_id]['history'] = []
            sessions_storage[session_id]['updated_at'] = datetime.now().isoformat()
        
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
        with sessions_lock:
            if session_id not in sessions_storage:
                return JSONResponse({
                    'success': False,
                    'error': '会话不存在'
                }, status_code=404)
            
            session = sessions_storage[session_id]
        
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

@router.get('/sessions')
async def list_sessions():
    """列出所有会话"""
    try:
        with sessions_lock:
            session_list = [
                {
                    'session_id': sid,
                    'user_id': data.get('user_id'),
                    'world_id': data.get('world_id'),
                    'created_at': data.get('created_at'),
                    'message_count': len(data.get('history', []))
                }
                for sid, data in sessions_storage.items()
            ]
        
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
                models.append({
                    'id': str(model_info.get('id')),
                    'name': model_info.get('model_name'),
                    'description': model_info.get('note') or '',
                    'category': 'perseids',
                    'recommended': model_info.get('id') == 1
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
                            reference_image=reference_image
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
        # 检查会话是否存在
        with sessions_lock:
            if session_id not in sessions_storage:
                return JSONResponse({
                    'success': False,
                    'error': '会话不存在'
                }, status_code=404)
            
            session = sessions_storage[session_id]
            user_id = session.user_id
            world_id = session.world_id
            auth_token = task_request.auth_token or session.auth_token
        
        # 验证 auth_token
        is_valid, error_response = await verify_auth_token(user_id, auth_token)
        if not is_valid:
            return JSONResponse(error_response, status_code=401)
        
        # 检查 model_id - 优先使用会话中保存的 model_id，如果没有则使用请求中的 model_id
        model_id = session.model_id if hasattr(session, 'model_id') and session.model_id is not None else task_request.model_id
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
        
        # 启动任务（使用 PMAgent，后台线程执行）
        def run_task_sync():
            """同步执行任务（在线程中运行）"""
            task_manager.start_task(task, session.pm_agent, session_data)
        
        # 在后台线程中启动任务
        import threading
        task_thread = threading.Thread(target=run_task_sync, daemon=True)
        task_thread.start()
        
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
    """SSE流式获取任务消息"""
    # 检查任务是否存在
    task = task_manager.get_task(task_id)
    if not task:
        return JSONResponse({
            'success': False,
            'error': '任务不存在'
        }, status_code=404)
    
    async def event_generator():
        try:
            logger.info(f"[SSE-STREAM] Starting SSE stream for task {task_id}")
            heartbeat_counter = 0
            message_count = 0
            
            while True:
                try:
                    # 从任务的消息队列获取消息（超时5秒）
                    logger.debug(f"[SSE-STREAM] Waiting for message from queue (timeout=5s)...")
                    msg = await asyncio.to_thread(task.message_queue.get, timeout=5)
                    message_count += 1
                    logger.info(f"[SSE-STREAM] Got message #{message_count}, type: {msg.get('type')}, role: {msg.get('role', 'N/A')}")
                    if msg.get('content'):
                        logger.info(f"[SSE-STREAM] Message content preview: {str(msg.get('content'))[:100]}...")
                    
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                    logger.info(f"[SSE-STREAM] Message #{message_count} sent to client")
                    
                    # 如果是完成或错误消息，结束流
                    if msg.get('type') in ['done', 'error']:
                        logger.info(f"[SSE-STREAM] Stream ending, type: {msg.get('type')}")
                        break
                    
                    heartbeat_counter = 0
                    
                except:
                    # 超时，发送心跳
                    heartbeat_counter += 1
                    if heartbeat_counter >= 6:
                        logger.debug(f"[SSE-STREAM] Sending heartbeat")
                        yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now().isoformat()}, ensure_ascii=False)}\n\n"
                        heartbeat_counter = 0
                    
                    # 检查任务状态
                    if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                        logger.info(f"[SSE-STREAM] Task status changed to {task.status.value}, ending stream")
                        yield f"data: {json.dumps({'type': 'done', 'status': task.status.value}, ensure_ascii=False)}\n\n"
                        break
            
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
