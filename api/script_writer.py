"""
Script Writer API 集成模块
将 script_writer 的 Flask API 集成到 FastAPI 中
"""

import os
import re
import json
import time
import logging
import uuid
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime
from fastapi import APIRouter, Request, Query as QueryParam, Header, UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from perseids_server.utils.permission import require_permission
from config.config_util import get_dynamic_config_value, get_config
from config.unified_config import TaskCategory, UnifiedConfigRegistry
from config.constant import (
    Action,
    StoryType,
    MediaGenerationMode,
    MediaGenerationSurface,
    MediaGenerationType,
    DEFAULT_TEXT_TO_IMAGE_TASK_ID,
    PERSEIDS_ERR_INVALID_AUTH_TOKEN,
    PERSEIDS_ERR_NO_VALID_TOKEN,
    ERROR_CODE_TOKEN_EXPIRED,
    ERROR_CODE_AUTH_SERVICE_UNAVAILABLE,
)
from utils.resource_access import get_user_id_from_header, ensure_world_access
from task.audio_task import build_character_audio_text, build_character_audio_style_prompt
from llm.llm_client_factory import get_llm_client

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
from services.media_generation_preference_service import (
    MediaGenerationPreferenceError,
    MediaGenerationPreferenceService,
)

# 导入智能体系统
from script_writer_core.agents import TaskManager, TaskStatus, ToolExecutor
from script_writer_core.chat_session import ChatSession
from script_writer_core.file_manager import FileManager
from script_writer_core.skill_loader import SkillLoader
from utils.file_storage import get_file_storage
from utils.conversation_history import append_message_if_not_duplicate
from utils.sse import format_sse_event, parse_last_event_id
from config.constant import MediaConstants
from utils.video_compressor import get_video_info, is_reference_video_pixel_count_valid
logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(prefix="/api", tags=["script_writer"])

# 会话存储（数据库 + 可选内存缓存）
# 使用数据库存储支持多 worker 进程间会话共享
from script_writer_core.session_storage import SessionStorage
session_storage = SessionStorage(use_cache=True, cache_ttl=300)

# 用户偏好存储：数据库是唯一数据源，不使用永久进程内缓存。
from model.user_preferences import (
    UserPreferencesModel,
    PREF_TYPE_TEXT_TO_IMAGE_MODEL,
    PREF_TYPE_IMAGE_PREFERENCES,
    PREF_TYPE_VIDEO_PREFERENCES,
    PREF_TYPE_TEXT_TO_VIDEO_MODEL,
    PREF_TYPE_IMAGE_TO_VIDEO_MODEL,
    PREF_TYPE_DEFAULT_LLM_MODEL,
)
# 生图模型设置范围：session=本对话草稿；world_default=世界默认（新会话种子）
IMAGE_MODEL_SCOPE_SESSION = "session"
IMAGE_MODEL_SCOPE_WORLD_DEFAULT = "world_default"


def _get_text_to_image_models_from_config():
    """从统一配置获取文生图模型列表"""
    from config.unified_config import UnifiedConfigRegistry, TaskCategory
    configs = UnifiedConfigRegistry.get_by_category(TaskCategory.TEXT_TO_IMAGE)
    return {
        c.id: {
            "name": c.name,
            "computing_power": c.get_computing_power(),
            "supports_grid_image": c.supports_grid_image,
            "short_key": getattr(c, "short_key", None) or c.key,
            "key": c.key,
        }
        for c in configs if c.enabled
    }


def get_text_to_image_model_id(user_id: str, world_id: str) -> int:
    """读取兼容偏好；数据库是唯一数据源，不使用进程内永久缓存。"""
    pref = UserPreferencesModel.get(user_id, world_id, PREF_TYPE_TEXT_TO_IMAGE_MODEL)
    if pref and pref.config_value is not None:
        result = pref.get_value()
        if isinstance(result, int):
            return result
    return DEFAULT_TEXT_TO_IMAGE_TASK_ID


def set_text_to_image_model_id(user_id: str, world_id: str, task_id: int):
    """设置用户在指定世界的生图模型 task_id（legacy 偏好）"""
    UserPreferencesModel.upsert(user_id, world_id, PREF_TYPE_TEXT_TO_IMAGE_MODEL, task_id)


def _sync_image_model_to_media_pref_world_default(user_id: str, world_id: str, task_id: int) -> None:
    """将生图模型写入 marketing_ui image 槽位（世界默认）。不兼容的模式跳过。"""
    for mode in (MediaGenerationMode.TEXT_TO_IMAGE, MediaGenerationMode.IMAGE_EDIT):
        try:
            existing = MediaGenerationPreferenceService.get_profile(
                user_id,
                world_id,
                MediaGenerationSurface.MARKETING_UI,
                MediaGenerationType.IMAGE,
                mode,
                initialize=False,
            ) or {}
            profile = {
                key: value
                for key, value in existing.items()
                if key in MediaGenerationPreferenceService.PROFILE_FIELDS and value is not None
            }
            profile['task_id'] = int(task_id)
            MediaGenerationPreferenceService.save_profile(
                user_id,
                world_id,
                MediaGenerationSurface.MARKETING_UI,
                MediaGenerationType.IMAGE,
                mode,
                profile,
            )
        except (MediaGenerationPreferenceError, ValueError, TypeError) as mode_err:
            logger.warning(
                '写入世界默认生图 media_pref 跳过: user_id=%s world_id=%s mode=%s task_id=%s err=%s',
                user_id, world_id, mode, task_id, mode_err,
            )


def get_default_llm_model(user_id: str, world_id: str) -> Optional[Dict[str, Any]]:
    """读取世界级默认对话模型。
    
    如果数据库没有配置，使用回退逻辑选择默认模型（与前端 pickPreferredCreationDefaultLlmKey 逻辑一致）：
    1. 首选供应商 + 首选模型
    2. 首选供应商 + 任意模型
    3. 列表第一项
    """
    pref = UserPreferencesModel.get(str(user_id), str(world_id), PREF_TYPE_DEFAULT_LLM_MODEL)
    if not pref or pref.config_value is None:
        # 数据库没有配置，使用回退逻辑
        return _get_fallback_default_llm_model()
    value = pref.get_value()
    if isinstance(value, dict) and value.get('model'):
        return value
    return None


def _get_fallback_default_llm_model() -> Optional[Dict[str, Any]]:
    """回退逻辑：当数据库没有配置时，选择默认模型。

    优先走场景目录的性价比档（llm.chat / deepseek-v4-flash），
    再回退 DEFAULT_LLM_MODEL_*，最后列表第一项。
    """
    try:
        from llm.llm_client_factory import get_available_models as _get_available_models
        from config.constant import DEFAULT_LLM_MODEL_PREFERRED_VENDORS, DEFAULT_LLM_MODEL_PREFERRED_MODEL
        from config.model_catalog import ModelScene, resolve_track_item
        import asyncio
        
        # 获取可用模型列表
        result = asyncio.run(_get_available_models())
        models = result.get('models', []) if isinstance(result, dict) else []
        
        if not models:
            return None

        hit, _track = resolve_track_item(ModelScene.LLM_CHAT, models, kind="llm")
        if hit:
            return {
                'model': hit.get('name'),
                'model_id': hit.get('id') if hit.get('id') is not None else hit.get('model_id'),
                'vendor_id': hit.get('vendor_id'),
                'name': hit.get('name'),
            }
        
        # 辅助函数
        def vendor_of(m):
            return (m.get('vendor_name') or '').lower()
        
        def model_of(m):
            return (m.get('name') or m.get('model') or '').lower()
        
        # 1. 首选供应商 + 首选模型
        for preferred_vendor in DEFAULT_LLM_MODEL_PREFERRED_VENDORS:
            found = next((m for m in models if vendor_of(m) == preferred_vendor and DEFAULT_LLM_MODEL_PREFERRED_MODEL in model_of(m)), None)
            if found:
                return {'model': found['name'], 'model_id': found.get('id'), 'vendor_id': found.get('vendor_id'), 'name': found['name']}
        
        # 2. 首选供应商 + 任意模型
        for preferred_vendor in DEFAULT_LLM_MODEL_PREFERRED_VENDORS:
            found = next((m for m in models if vendor_of(m) == preferred_vendor), None)
            if found:
                return {'model': found['name'], 'model_id': found.get('id'), 'vendor_id': found.get('vendor_id'), 'name': found['name']}
        
        # 3. 列表第一项
        first = models[0]
        return {'model': first['name'], 'model_id': first.get('id'), 'vendor_id': first.get('vendor_id'), 'name': first['name']}
        
    except Exception as e:
        logger.warning(f"回退选择默认 LLM 模型失败：{e}")
        return None


def set_default_llm_model(user_id: str, world_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """写入世界级默认对话模型。"""
    normalized = {
        'model': str(payload.get('model') or ''),
        'model_id': int(payload['model_id']) if payload.get('model_id') not in (None, '') else None,
        'vendor_id': int(payload['vendor_id']) if payload.get('vendor_id') not in (None, '') else None,
        'name': payload.get('name') or payload.get('model') or '',
    }
    if not normalized['model']:
        raise ValueError('model 不能为空')
    UserPreferencesModel.upsert(
        str(user_id), str(world_id), PREF_TYPE_DEFAULT_LLM_MODEL, normalized
    )
    return normalized


def get_image_preferences(user_id: str, world_id: str) -> Dict[str, str]:
    """获取用户在指定世界的图片偏好（比例、分辨率）"""
    pref = UserPreferencesModel.get(user_id, world_id, PREF_TYPE_IMAGE_PREFERENCES)
    if pref and pref.config_value is not None:
        result = pref.get_value()
        if isinstance(result, dict):
            return result
    return {}


def set_image_preferences(user_id: str, world_id: str, prefs: Dict[str, str]):
    """设置用户在指定世界的图片偏好"""
    UserPreferencesModel.upsert(user_id, world_id, PREF_TYPE_IMAGE_PREFERENCES, prefs)


def get_video_preferences(user_id: str, world_id: str) -> Dict[str, str]:
    """获取用户在指定世界的视频偏好（比例、时长）"""
    pref = UserPreferencesModel.get(user_id, world_id, PREF_TYPE_VIDEO_PREFERENCES)
    if pref and pref.config_value is not None:
        result = pref.get_value()
        if isinstance(result, dict):
            return result
    return {}


def set_video_preferences(user_id: str, world_id: str, prefs: Dict[str, str]):
    """设置用户在指定世界的视频偏好"""
    UserPreferencesModel.upsert(user_id, world_id, PREF_TYPE_VIDEO_PREFERENCES, prefs)


def get_text_to_video_model_id(user_id: str, world_id: str) -> Optional[int]:
    """获取用户在指定世界的文生视频模型 task_id"""
    pref = UserPreferencesModel.get(user_id, world_id, PREF_TYPE_TEXT_TO_VIDEO_MODEL)
    if pref and pref.config_value is not None:
        result = pref.get_value()
        if isinstance(result, int):
            return result
    return None


def set_text_to_video_model_id(user_id: str, world_id: str, task_id: int):
    """设置用户在指定世界的文生视频模型 task_id"""
    UserPreferencesModel.upsert(user_id, world_id, PREF_TYPE_TEXT_TO_VIDEO_MODEL, task_id)


def get_image_to_video_model_id(user_id: str, world_id: str) -> Optional[int]:
    """获取用户在指定世界的图生视频模型 task_id"""
    pref = UserPreferencesModel.get(user_id, world_id, PREF_TYPE_IMAGE_TO_VIDEO_MODEL)
    if pref and pref.config_value is not None:
        result = pref.get_value()
        if isinstance(result, int):
            return result
    return None


def set_image_to_video_model_id(user_id: str, world_id: str, task_id: int):
    """设置用户在指定世界的图生视频模型 task_id"""
    UserPreferencesModel.upsert(user_id, world_id, PREF_TYPE_IMAGE_TO_VIDEO_MODEL, task_id)


def _session_expire_hours(session_type: int) -> int:
    """按会话类型返回过期时长（小时）"""
    from config.constant import SessionHistoryConstants
    return (SessionHistoryConstants.SESSION_EXPIRE_HOURS_MARKETING
            if session_type == 2 else SessionHistoryConstants.SESSION_EXPIRE_HOURS_SCRIPT)


def _extend_session_expiry(session_id: str, session_type: int):
    """用户产生新消息活动时顺延会话过期时间（同步函数，需用 asyncio.to_thread 调用）"""
    from datetime import timedelta
    from model.chat_sessions import ChatSessionsModel
    expires_at = datetime.now() + timedelta(hours=_session_expire_hours(session_type))
    ChatSessionsModel.update_metadata(session_id=session_id, expires_at=expires_at)


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
from script_writer_core.mcp_tool import set_text_to_image_model_getter, set_image_preferences_getter, set_video_preferences_getter, set_text_to_video_model_getter, set_image_to_video_model_getter
set_text_to_image_model_getter(get_text_to_image_model_id)
set_image_preferences_getter(get_image_preferences)
set_video_preferences_getter(get_video_preferences)
set_text_to_video_model_getter(get_text_to_video_model_id)
set_image_to_video_model_getter(get_image_to_video_model_id)

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
            "allowed_tools": ["skill", "ask_user"],
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
            # 依据源头 error_code 精确分类（不做 message 文案匹配）：
            # NO_VALID_TOKEN = 该用户确证无有效 token（被顶号/登出/重置密码），按 token 失效处理；
            # 其余失败（服务故障/DB 异常等）一律视为认证服务不可用，不得误报 token 失效。
            if isinstance(auth_data, dict) and auth_data.get('error_code') == PERSEIDS_ERR_NO_VALID_TOKEN:
                logger.warning(f"Token确证失效 - user_id: {user_id}, 错误: {message}")
                return False, {
                    'success': False,
                    'error': '登录已过期，请重新登录',
                    'error_code': ERROR_CODE_TOKEN_EXPIRED,
                    'token_expired': True
                }
            logger.warning(f"Token验证服务故障 - user_id: {user_id}, 错误: {message}")
            return False, {
                'success': False,
                'error': '认证服务暂时不可用，请稍后重试',
                'error_code': ERROR_CODE_AUTH_SERVICE_UNAVAILABLE,
                'message': message
            }
        
        logger.info(f"Token验证成功 - user_id: {user_id}")
        return True, None
        
    except Exception as e:
        logger.error(f"Token验证异常 - user_id: {user_id}, 错误: {str(e)}")
        return False, {
            'success': False,
            'error': '认证服务暂时不可用，请稍后重试',
            'error_code': ERROR_CODE_AUTH_SERVICE_UNAVAILABLE,
            'message': f'验证服务异常: {str(e)}'
        }

def _auth_error_status_code(error_response: dict) -> int:
    """按 error_code 分流：认证服务自身故障 → 502；token 确证失效 → 401。"""
    if isinstance(error_response, dict) and error_response.get('error_code') == ERROR_CODE_AUTH_SERVICE_UNAVAILABLE:
        return 502
    return 401

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
            # 依据源头 error_code 判定 token 确证失效（不做 message 文案匹配，
            # 避免算力不足/限额等含 "token"/"认证" 字样的错误被误判为登录失效）
            if isinstance(response_data, dict) and response_data.get('error_code') == PERSEIDS_ERR_INVALID_AUTH_TOKEN:
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

        # 添加阿里云 Qwen 模型（如果配置了 API Key）
        try:
            from config.config_util import get_dynamic_config_value
            from model.model import ModelModel
            from model.vendor_model import VendorModelModel
            from model.vendor import VendorDAO
            qwen_api_key = get_dynamic_config_value('llm', 'qwen', 'api_key', default='')
            if qwen_api_key:
                all_vendor_models = VendorModelModel.get_all()
                # 动态查询 aliyun vendor_id，避免硬编码
                aliyun_vendor = next((v for v in VendorDAO.get_all() if v.vendor_name == 'aliyun'), None)
                aliyun_vendor_id = aliyun_vendor.id if aliyun_vendor else 2
                qwen_model_ids = list(set([vm.model_id for vm in all_vendor_models if vm.vendor_id == aliyun_vendor_id]))
                for mid in qwen_model_ids:
                    local_model = ModelModel.get_by_id(mid)
                    if local_model and local_model.supports_tools:
                        valid_models.append(local_model.model_name)
        except Exception as e:
            logger.warning(f"获取阿里云 Qwen 模型列表失败: {e}")

        # 添加 Ollama 本地模型（如果启用）
        try:
            from config.config_util import get_dynamic_config_value
            from model.model import ModelModel
            from model.vendor_model import VendorModelModel
            from model.vendor import VendorDAO
            ollama_enabled = get_dynamic_config_value('llm', 'ollama', 'enabled', default=False)
            if ollama_enabled:
                ollama_vendor_models = VendorModelModel.get_all()
                # 动态查询 ollama vendor_id，避免硬编码
                ollama_vendor = next((v for v in VendorDAO.get_all() if v.vendor_name == 'ollama'), None)
                ollama_vendor_id = ollama_vendor.id if ollama_vendor else 3
                ollama_model_ids = [vm.model_id for vm in ollama_vendor_models if vm.vendor_id == ollama_vendor_id]
                for mid in ollama_model_ids:
                    local_model = ModelModel.get_by_id(mid)
                    if local_model and local_model.supports_tools:
                        # Ollama 模型使用 ollama: 前缀
                        valid_models.append(f"ollama:{local_model.model_name}")
        except Exception as e:
            logger.warning(f"获取 Ollama 模型列表失败: {e}")

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
        from config.constant import Edition

        # 空间隔离标志：仅独立空间模式（企业版且未开启 shared_space）才按 user_id 过滤记录。
        # 社区版/共享空间下 world 是多人共享的，记录的 user_id 可能是任意协作者，
        # 此处过滤会导致「删除暂存」时把别人创建的角色/场景/道具/剧本静默跳过、无法同步。
        # 该约定与各 Model.list_by_user() 中 is_space_isolated() 的判断保持一致。
        filter_by_user = Edition.is_space_isolated()

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
                'story_type': getattr(world, 'story_type', 'dialogue'),
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
            if filter_by_user and char.get('user_id') != int(user_id):
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
                    default_voice=char.get('default_voice'),
                    _temp_filename=temp_filename,
                    _skip_image_validation=True
                )

                if temp_result.get('success'):
                    temp_file = base_path / "characters" / temp_filename
                    if temp_file.exists():
                        try:
                            new_content = temp_file.read_text(encoding='utf-8')
                            existing_content = char_file.read_text(encoding='utf-8')

                            if not compare_json_content(new_content, existing_content, file_name):
                                if force_overwrite:
                                    overwrite_result = create_character_json(
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
                                        default_voice=char.get('default_voice'),
                                        _skip_image_validation=True
                                    )
                                    if not overwrite_result.get('success'):
                                        logger.warning(f"同步覆盖角色失败 {char.get('name')}: {overwrite_result.get('error')}")
                                    result['diff_files'].append(file_name)
                                    result['overwritten_files'].append(file_name)
                                else:
                                    result['diff_files'].append(file_name)
                                    result['skipped_files'].append(file_name)
                        finally:
                            if temp_file.exists():
                                temp_file.unlink()
                else:
                    logger.warning(f"同步生成角色临时文件失败 {char.get('name')}: {temp_result.get('error')}")
            else:
                create_result = create_character_json(
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
                    default_voice=char.get('default_voice'),
                    _skip_image_validation=True
                )
                if not create_result.get('success'):
                    logger.warning(f"同步角色失败 {char.get('name')}: {create_result.get('error')}")
        
        # 2. 同步剧本
        scripts_result = ScriptModel.list_by_world(int(world_id), page=1, page_size=1000)
        scripts = scripts_result.get('data', []) if isinstance(scripts_result, dict) else []
        for script in scripts:
            if (filter_by_user and script.get('user_id') != int(user_id)) or not script.get('content'):
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
        
        # 3. 同步场景（保留 DB 层级：parent_id + parent_name）
        locations_result = LocationModel.list_by_world(int(world_id), page=1, page_size=1000)
        locations = locations_result.get('data', []) if isinstance(locations_result, dict) else []
        # id → name，用于把 DB parent_id 还原为文件层 parent_name
        id_to_name = {}
        for loc in locations:
            if loc.get('id') is not None and loc.get('name'):
                id_to_name[int(loc['id'])] = loc['name']

        def _location_parent_fields(loc: dict) -> dict:
            pid = loc.get('parent_id')
            parent_name = None
            parent_id_val = None
            if pid is not None and pid != '':
                try:
                    parent_id_val = int(pid)
                    parent_name = id_to_name.get(parent_id_val)
                except (TypeError, ValueError):
                    parent_id_val = None
                    parent_name = None
            return {
                'parent_id': parent_id_val,
                'parent_name': parent_name,
            }

        for loc in locations:
            if filter_by_user and loc.get('user_id') != int(user_id):
                continue

            parent_fields = _location_parent_fields(loc)
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
                    parent_id=parent_fields['parent_id'],
                    parent_name=parent_fields['parent_name'],
                    _temp_filename=temp_filename,
                    _skip_image_validation=True,
                    **({'reference_images': loc.get('reference_images')} if loc.get('reference_images') is not None else {}),
                )

                if temp_result.get('success'):
                    temp_file = base_path / "locations" / temp_filename
                    if temp_file.exists():
                        try:
                            new_content = temp_file.read_text(encoding='utf-8')
                            existing_content = loc_file.read_text(encoding='utf-8')

                            if not compare_json_content(new_content, existing_content, file_name):
                                if force_overwrite:
                                    overwrite_result = create_location_json(
                                        user_id=user_id,
                                        world_id=world_id,
                                        auth_token=auth_token,
                                        name=loc.get('name'),
                                        description=loc.get('description'),
                                        reference_image=loc.get('reference_image'),
                                        parent_id=parent_fields['parent_id'],
                                        parent_name=parent_fields['parent_name'],
                                        _skip_image_validation=True,
                                        **({'reference_images': loc.get('reference_images')} if loc.get('reference_images') is not None else {}),
                                    )
                                    if not overwrite_result.get('success'):
                                        logger.warning(f"同步覆盖场景失败 {loc.get('name')}: {overwrite_result.get('error')}")
                                    result['diff_files'].append(file_name)
                                    result['overwritten_files'].append(file_name)
                                else:
                                    result['diff_files'].append(file_name)
                                    result['skipped_files'].append(file_name)
                        finally:
                            if temp_file.exists():
                                temp_file.unlink()
                else:
                    logger.warning(f"同步生成场景临时文件失败 {loc.get('name')}: {temp_result.get('error')}")
            else:
                create_result = create_location_json(
                    user_id=user_id,
                    world_id=world_id,
                    auth_token=auth_token,
                    name=loc.get('name'),
                    description=loc.get('description'),
                    reference_image=loc.get('reference_image'),
                    parent_id=parent_fields['parent_id'],
                    parent_name=parent_fields['parent_name'],
                    _skip_image_validation=True,
                    **({'reference_images': loc.get('reference_images')} if loc.get('reference_images') is not None else {}),
                )
                if not create_result.get('success'):
                    logger.warning(f"同步场景失败 {loc.get('name')}: {create_result.get('error')}")
        
        # 4. 同步道具
        props_result = PropsModel.list_by_world(int(world_id), page=1, page_size=1000)
        props = props_result.get('data', []) if isinstance(props_result, dict) else []
        for prop in props:
            if filter_by_user and prop.get('user_id') != int(user_id):
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
                    _temp_filename=temp_filename,
                    _skip_image_validation=True
                )

                if temp_result.get('success'):
                    temp_file = base_path / "props" / temp_filename
                    if temp_file.exists():
                        try:
                            new_content = temp_file.read_text(encoding='utf-8')
                            existing_content = prop_file.read_text(encoding='utf-8')

                            if not compare_json_content(new_content, existing_content, file_name):
                                if force_overwrite:
                                    overwrite_result = create_prop_json(
                                        user_id=user_id,
                                        world_id=world_id,
                                        auth_token=auth_token,
                                        name=prop.get('name'),
                                        prop_type=prop.get('type'),
                                        description=prop.get('content'),
                                        reference_image=prop.get('reference_image'),
                                        _skip_image_validation=True
                                    )
                                    if not overwrite_result.get('success'):
                                        logger.warning(f"同步覆盖道具失败 {prop.get('name')}: {overwrite_result.get('error')}")
                                    result['diff_files'].append(file_name)
                                    result['overwritten_files'].append(file_name)
                                else:
                                    result['diff_files'].append(file_name)
                                    result['skipped_files'].append(file_name)
                        finally:
                            if temp_file.exists():
                                temp_file.unlink()
                else:
                    logger.warning(f"同步生成道具临时文件失败 {prop.get('name')}: {temp_result.get('error')}")
            else:
                create_result = create_prop_json(
                    user_id=user_id,
                    world_id=world_id,
                    auth_token=auth_token,
                    name=prop.get('name'),
                    prop_type=prop.get('type'),
                    description=prop.get('content'),
                    reference_image=prop.get('reference_image'),
                    _skip_image_validation=True
                )
                if not create_result.get('success'):
                    logger.warning(f"同步道具失败 {prop.get('name')}: {create_result.get('error')}")
        
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
    session_type: int = 1

class TaskCreateRequest(BaseModel):
    message: str
    auth_token: str = ""
    model: Optional[str] = None
    model_id: Optional[int] = None
    vendor_id: int = 1
    enable_thinking: bool = False
    thinking_effort: str = "medium"
    image_urls: Optional[List[str]] = None
    video_urls: Optional[List[str]] = None
    audio_urls: Optional[List[str]] = None
    thumbnail_urls: Optional[List[str]] = None
    image_preferences: Optional[Dict[str, Any]] = None
    video_preferences: Optional[Dict[str, Any]] = None
    language: Optional[str] = None


def build_agent_user_message_with_media(
    user_message: str,
    image_urls: Optional[List[str]] = None,
    video_urls: Optional[List[str]] = None,
    audio_urls: Optional[List[str]] = None,
    thumbnail_urls: Optional[List[str]] = None,
) -> str:
    """构建 PM/前端历史共用的用户消息文本，保留上传接口返回的媒体 URL。

    上传接口已经根据配置决定返回本地 URL 还是 CDN URL；这里不重新判断 CDN，
    只负责把 URL 写入可恢复展示的媒体标签。
    """
    combined_parts = []
    if image_urls:
        for i, image_url in enumerate(image_urls):
            thumb = ""
            if thumbnail_urls and i < len(thumbnail_urls) and thumbnail_urls[i]:
                thumb = f" thumb: {thumbnail_urls[i]}"
            combined_parts.append(f"[图片{i + 1}]（URL: {image_url}{thumb}）")
    if video_urls:
        for i, video_url in enumerate(video_urls):
            combined_parts.append(f"[视频{i + 1}]（URL: {video_url}）")
    if audio_urls:
        for i, audio_url in enumerate(audio_urls):
            combined_parts.append(f"[音频{i + 1}]（URL: {audio_url}）")

    if combined_parts:
        return "\n".join(combined_parts) + "\n\n" + (user_message or "")
    return user_message or ""


def sync_agent_image_preferences(user_id: str, world_id: str, prefs: Dict[str, Any]) -> List[str]:
    """Persist image preferences sent with an Agent task and return text summary parts."""
    if not prefs:
        return []

    # 可持久化的偏好字段：key -> 中文标签
    STORABLE_PREFS = [
        ('ratio', '图片比例'),
        ('resolution', '分辨率'),
    ]

    pref_parts: List[str] = []
    # 只在有需要持久化的字段时才读取/写入
    needs_persist = any(prefs.get(k) not in (None, '') for k, _ in STORABLE_PREFS)
    stored_prefs = dict(get_image_preferences(user_id, world_id) or {}) if needs_persist else {}
    original_prefs = dict(stored_prefs) if needs_persist else None

    for key, label in STORABLE_PREFS:
        value = prefs.get(key)
        if value is not None and value != '':
            stored_prefs[key] = str(value)
            pref_parts.append(f"{label}: {value}")

    model_name = prefs.get('model_name')
    if model_name:
        pref_parts.append(f"生图模型: {model_name}")

    if needs_persist and stored_prefs != original_prefs:
        set_image_preferences(user_id, world_id, stored_prefs)
        logger.info(f'[Agent任务] 已同步图片偏好: user_id={user_id}, world_id={world_id}, prefs={stored_prefs}')

    return pref_parts


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

class CharacterReferenceAudioRequest(BaseModel):
    world_id: int
    character_id: Optional[int] = None
    character_name: Optional[str] = None
    character_data: Optional[Dict[str, Any]] = None
    style_prompt: Optional[str] = None
    text: Optional[str] = None
    # LLM 模型信息（从前端 model-selector 获取）
    model: Optional[str] = None
    model_id: Optional[int] = None
    vendor_id: Optional[int] = None

class ScriptSaveRequest(BaseModel):
    content: Dict[str, Any]

class LocationSaveRequest(BaseModel):
    content: Dict[str, Any]

class PropSaveRequest(BaseModel):
    content: Dict[str, Any]

class WorldCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""

class SessionTitleUpdateRequest(BaseModel):
    title: str

class WorldUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class VerificationSubmitRequest(BaseModel):
    approved: bool
    user_input: Optional[str] = None
    image_urls: Optional[List[str]] = None
    video_urls: Optional[List[str]] = None
    audio_urls: Optional[List[str]] = None
    thumbnail_urls: Optional[List[str]] = None

class SessionHistoryUpdateRequest(BaseModel):
    messages: List[Dict[str, Any]]

class SessionMessageAppendRequest(BaseModel):
    role: str
    content: str

# ==================== 会话管理 API ====================

@router.post('/session/create')
@require_permission("script_session:create")
async def create_session(request: Request, session_request: SessionCreateRequest):
    """创建新会话"""
    try:
        # 验证 auth_token
        is_valid, error_response = await verify_auth_token(session_request.user_id, session_request.auth_token)
        if not is_valid:
            return JSONResponse(error_response, status_code=_auth_error_status_code(error_response))
        
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
            model_id=session_request.model_id,
            session_type=session_request.session_type
        )

        # 存储会话到数据库
        from config.constant import SessionHistoryConstants
        expire_hours = SessionHistoryConstants.SESSION_EXPIRE_HOURS_MARKETING if session_request.session_type == 2 else SessionHistoryConstants.SESSION_EXPIRE_HOURS_SCRIPT
        if not session_storage.save_session(session, expires_hours=expire_hours):
            logger.error(f'会话保存到数据库失败 - session_id: {session_id}')
            return JSONResponse({
                'success': False,
                'error': '会话保存失败'
            }, status_code=500)

        # 将 system prompt 和 tool_definitions 写入 chat_messages（仅创建时执行一次）
        try:
            from script_writer_core.conversation_recorder import ConversationRecorder
            recorder = ConversationRecorder()

            # 写入 system prompt
            await asyncio.to_thread(
                recorder.append_message,
                session_id=session_id,
                role="system",
                content=session.pm_agent.system_prompt,
                message_type="system_prompt",
                visibility="llm",
                context_state="active",
                source="system",
                agent_scope="pm",
            )

            # 写入工具定义
            tool_defs = session.pm_agent._get_tool_definitions()
            if tool_defs:
                await asyncio.to_thread(
                    recorder.append_message,
                    session_id=session_id,
                    role="system",
                    content={"tools": tool_defs},
                    provider_payload={"tools": tool_defs},
                    message_type="tool_definitions",
                    visibility="internal",
                    context_state="active",
                    source="system",
                    agent_scope="pm",
                )

            logger.info(f'System prompt and tool_definitions written to chat_messages for session {session_id}')
        except Exception as e:
            logger.error(f'写入 chat_messages 失败（非致命）: {e}')

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
        # 优先从 chat_messages 读取（新路径）
        try:
            from model.chat_messages import ChatMessagesModel
            messages = await asyncio.to_thread(
                ChatMessagesModel.list_for_session, session_id,
                visibility=['ui', 'both'],
                exclude_context_state=['deleted'],
                exclude_message_types=['context_summary'],  # 排除 context_summary，不混入聊天流
            )

            if messages:
                history = [msg.to_frontend_dict() for msg in messages]
                verification_history = [
                    item for item in history
                    if item.get('role') == 'verification'
                    and isinstance(item.get('content'), dict)
                    and item.get('content', {}).get('verification_id')
                ]
                if verification_history:
                    from model.agent_verifications import AgentVerificationsModel
                    for item in verification_history:
                        verification = await asyncio.to_thread(
                            AgentVerificationsModel.get_by_verification_id,
                            item['content']['verification_id'],
                        )
                        if verification:
                            item['verification_status'] = verification.status
                            item['content']['status'] = verification.status
                # 从 chat_sessions 获取时间戳
                from model.chat_sessions import ChatSessionsModel
                entity = await asyncio.to_thread(ChatSessionsModel.get_by_session_id, session_id)
                return JSONResponse({
                    'success': True,
                    'history': history,
                    'created_at': entity.created_at.isoformat() if entity and entity.created_at else None,
                    'updated_at': entity.updated_at.isoformat() if entity and entity.updated_at else None
                })
        except Exception as e:
            logger.warning(f'从 chat_messages 读取历史失败: {e}')

        # 新路径：chat_messages 无数据时返回空历史（不再回退旧 conversation_history）
        # 获取 session 时间戳用于响应
        from model.chat_sessions import ChatSessionsModel
        entity = await asyncio.to_thread(ChatSessionsModel.get_by_session_id, session_id)
        if not entity:
            return JSONResponse({
                'success': False,
                'error': '会话不存在'
            }, status_code=404)

        return JSONResponse({
            'success': True,
            'history': [],
            'created_at': entity.created_at.isoformat() if entity.created_at else None,
            'updated_at': entity.updated_at.isoformat() if entity.updated_at else None
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
        # 从数据库加载会话（仅用于检查是否存在）
        from model.chat_sessions import ChatSessionsModel
        entity = await asyncio.to_thread(ChatSessionsModel.get_by_session_id, session_id)

        if not entity:
            return JSONResponse({
                'success': False,
                'error': '会话不存在'
            }, status_code=404)

        # 清空旧 conversation_history（兼容过渡期）
        await asyncio.to_thread(ChatSessionsModel.clear_history, session_id)

        # 软删除 chat_messages 中所有消息
        from model.chat_messages import ChatMessagesModel
        all_msgs = await asyncio.to_thread(
            ChatMessagesModel.list_for_session, session_id,
            exclude_context_state=['deleted'],
        )
        deletable_ids = [
            m.id for m in all_msgs
            if m.message_type not in ('system_prompt', 'tool_definitions')
        ]
        if deletable_ids:
            await asyncio.to_thread(
                ChatMessagesModel.update_context_state,
                deletable_ids,
                'deleted',
            )

        session_storage.invalidate_cache(session_id)

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

@router.post('/session/{session_id}/compress')
@require_permission("script_session:compress_history")
async def compress_session_history(request: Request, session_id: str):
    """压缩会话历史（基于 chat_messages DB 压缩）"""
    try:
        from model.chat_sessions import ChatSessionsModel
        from model.chat_messages import ChatMessagesModel
        from model.agent_tasks import AgentTasksModel

        # 检查会话是否存在
        session_entity = await asyncio.to_thread(ChatSessionsModel.get_by_session_id, session_id)
        if not session_entity:
            return JSONResponse({
                'success': False,
                'error': '会话不存在'
            }, status_code=404)

        # 获取最近的任务信息（用于模型配置）
        task_entity = await asyncio.to_thread(AgentTasksModel.get_latest_by_session, session_id)
        if not task_entity:
            return JSONResponse({
                'success': False,
                'error': '没有可用的任务信息，无法确定模型配置'
            }, status_code=400)

        # 加载 session 并设置 _session_id，确保 PM Agent 走 DB 压缩路径
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
                'error': '会话加载失败'
            }, status_code=404)

        # 从 task_entity 构建 AgentTask
        from script_writer_core.agents.task_manager import AgentTask
        task = AgentTask(
            task_id=task_entity.task_id,
            session_id=session_id,
            user_message=task_entity.user_message or '',
            user_id=session_entity.user_id,
            world_id=session_entity.world_id,
            auth_token=task_entity.auth_token or session_entity.auth_token or '',
            vendor_id=task_entity.vendor_id,
            model_id=task_entity.model_id or session_entity.model_id,
            enable_thinking=str(getattr(task_entity, 'enable_thinking', False)).lower() == 'true',
            thinking_effort=getattr(task_entity, 'thinking_effort', 'medium'),
            image_urls=getattr(task_entity, 'image_urls', None),
            video_urls=getattr(task_entity, 'video_urls', None),
            audio_urls=getattr(task_entity, 'audio_urls', None),
            language=getattr(task_entity, 'language', 'zh-CN'),
        )

        # 确保 PM Agent 设置了 _session_id（DB 压缩前置条件）
        if not session.pm_agent._session_id:
            session.pm_agent._session_id = session_id
        session.pm_agent._task_id = task.task_id
        session.pm_agent._vendor_id = task.vendor_id
        if not session.pm_agent._conversation_recorder:
            from script_writer_core.conversation_recorder import ConversationRecorder
            session.pm_agent._conversation_recorder = ConversationRecorder()

        # 执行压缩（使用 run_in_executor 避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, session.compress_history, task)

        if result.get('success'):
            return JSONResponse({
                'success': True,
                'message': f"对话历史已压缩：{result.get('before_count')} → {result.get('after_count')} 条消息",
                'before_count': result.get('before_count'),
                'after_count': result.get('after_count'),
                'reduced': result.get('reduced'),
                'summary': result.get('summary', '')
            })
        else:
            return JSONResponse({
                'success': False,
                'error': result.get('error', '压缩失败')
            }, status_code=400)
    except Exception as e:
        logger.error(f'压缩会话历史失败: {str(e)}')
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

@router.put('/session/{session_id}/history')
@require_permission("script_session:update")
async def update_session_history(request: Request, session_id: str, history_request: SessionHistoryUpdateRequest):
    """更新会话历史消息（整体替换模式，用于前端手动编辑历史）"""
    try:
        from model.chat_sessions import ChatSessionsModel
        from model.chat_messages import ChatMessagesModel

        session_entity = await asyncio.to_thread(ChatSessionsModel.get_by_session_id, session_id)
        if not session_entity:
            return JSONResponse({
                'success': False,
                'error': '会话不存在'
            }, status_code=404)

        # 过滤 system 消息
        filtered_messages = [msg for msg in history_request.messages if msg.get('role') != 'system']

        # 只软删 UI 可编辑的普通消息，保留基础设施消息（system_prompt、tool_definitions、context_summary）
        existing = await asyncio.to_thread(
            ChatMessagesModel.list_for_session, session_id,
            agent_scope='pm',
            exclude_context_state=['deleted'],
        )
        ui_editable_ids = [
            m.id for m in existing
            if m.message_type in ('normal', 'tool_call', 'tool_result',
                                  'verification_request', 'verification_answer')
        ]
        if ui_editable_ids:
            await asyncio.to_thread(
                ChatMessagesModel.update_context_state,
                ui_editable_ids,
                'deleted',
            )

        # 逐条写入新历史
        from script_writer_core.conversation_recorder import ConversationRecorder
        recorder = ConversationRecorder()
        for msg in filtered_messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            await asyncio.to_thread(
                recorder.append_message,
                session_id=session_id,
                role=role,
                content={"text": content} if isinstance(content, str) else content,
                message_type="normal",
                visibility="both",
                agent_scope="pm",
                source="frontend",
            )

        session_storage.invalidate_cache(session_id)

        return JSONResponse({
            'success': True,
            'message': '会话历史已更新'
        })
    except Exception as e:
        logger.error(f'更新会话历史失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.post('/session/{session_id}/message')
@require_permission("script_session:update")
async def append_session_message(request: Request, session_id: str, message_request: SessionMessageAppendRequest):
    """追加消息到会话历史（写入 chat_messages 表）"""
    try:
        from model.chat_sessions import ChatSessionsModel
        from script_writer_core.conversation_recorder import ConversationRecorder

        session_entity = await asyncio.to_thread(ChatSessionsModel.get_by_session_id, session_id)
        if not session_entity:
            return JSONResponse({
                'success': False,
                'error': '会话不存在'
            }, status_code=404)

        role = message_request.role
        content = message_request.content

        # 写入 chat_messages（幂等，重复消息自动跳过）
        recorder = ConversationRecorder()

        # 判断消息类型
        message_type = "normal"
        if role == "assistant" and content and content.startswith('__PENDING_TASK__'):
            message_type = "normal"  # pending task 标记也作为普通 assistant 消息

        # 显式 idempotency_key：避免同一分钟内相同内容被吞掉
        import uuid as _uuid
        idem_key = f"frontend:{session_id}:{role}:{_uuid.uuid4().hex[:16]}"

        await asyncio.to_thread(
            recorder.append_message,
            session_id=session_id,
            role=role,
            content={"text": content} if isinstance(content, str) else content,
            message_type=message_type,
            visibility="both",
            agent_scope="pm",
            source="frontend",
            idempotency_key=idem_key,
        )

        # 清除缓存，确保下次加载时从数据库读取最新数据
        session_storage.invalidate_cache(session_id)

        # 追加消息即视为会话活动，顺延过期时间
        try:
            await asyncio.to_thread(
                _extend_session_expiry, session_id, getattr(session_entity, 'session_type', 1) or 1
            )
        except Exception as e:
            logger.error(f'顺延会话过期时间失败（非致命）: {e}')

        return JSONResponse({
            'success': True,
            'message': '消息已追加'
        })
    except Exception as e:
        logger.error(f'追加消息失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.post('/session/{session_id}/clean-pending-tasks')
@require_permission("script_session:update")
async def clean_pending_tasks(request: Request, session_id: str):
    """清理对话历史中的 __PENDING_TASK__ 标记（精确清理，支持并发任务）

    请求体（可选）:
    - task_type: str, 如 'image_task_submitted' / 'video_task_submitted'
    - project_ids: list[int], 如 [757]
    不传参数时清理全部 pending 标记（向后兼容）。
    """
    try:
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass  # 无 body 时兼容旧调用

        task_type = body.get('task_type')
        project_ids = body.get('project_ids')

        from model.chat_messages import ChatMessagesModel

        all_msgs = await asyncio.to_thread(
            ChatMessagesModel.list_for_session, session_id,
            agent_scope='pm',
            exclude_context_state=['deleted'],
        )

        pending_msg_ids = []
        for m in all_msgs:
            text = ''
            if isinstance(m.content, str):
                text = m.content
            elif isinstance(m.content, dict):
                text = m.content.get('text', '')

            if not text.startswith('__PENDING_TASK__'):
                continue

            # 精确匹配：只清理指定 task_type 和 project_ids 的 pending 消息
            if task_type and project_ids:
                match = re.match(r'^__PENDING_TASK__:([^:]+):(.+)$', text)
                if match:
                    msg_event_type = match.group(1)
                    try:
                        msg_project_ids = json.loads(match.group(2))
                    except (json.JSONDecodeError, TypeError):
                        msg_project_ids = []
                    if msg_event_type == task_type and set(map(str, msg_project_ids)) == set(map(str, project_ids)):
                        pending_msg_ids.append(m.id)
            else:
                # 兼容旧调用：不传参数时清理全部
                pending_msg_ids.append(m.id)

        if pending_msg_ids:
            await asyncio.to_thread(
                ChatMessagesModel.update_context_state,
                pending_msg_ids,
                'deleted',
            )
            session_storage.invalidate_cache(session_id)

        return JSONResponse({
            'success': True,
            'removed': len(pending_msg_ids)
        })
    except Exception as e:
        logger.error(f'清理 pending task 标记失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

@router.put('/session/{session_id}/message/{message_id}')
@require_permission("script_session:update")
async def update_message_content(request: Request, session_id: str, message_id: str):
    """更新指定消息的内容（用于 pending_task → 结果替换）"""
    try:
        body = await request.json()
        new_content = body.get('content')
        new_message_type = body.get('message_type')

        if not new_content:
            return JSONResponse({'success': False, 'error': 'content is required'}, status_code=400)

        from model.chat_messages import ChatMessagesModel
        affected = await asyncio.to_thread(
            ChatMessagesModel.update_content,
            message_id,
            new_content,
            new_message_type,
            session_id
        )
        if affected == 0:
            return JSONResponse({'success': False, 'error': 'message not found or session mismatch'}, status_code=404)
        session_storage.invalidate_cache(session_id)
        return JSONResponse({'success': True})
    except Exception as e:
        logger.error(f'更新消息内容失败: {str(e)}')
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

@router.post('/session/{session_id}/replace-pending-task')
@require_permission("script_session:update")
async def replace_pending_task(request: Request, session_id: str):
    """按 task_type + project_ids 查找并替换 pending_task 消息为结果内容

    请求体:
    - task_type: str, 如 'image_task_submitted' / 'video_task_submitted'
    - project_ids: list[int], 如 [757]
    - content: str, 替换后的结果内容

    返回:
    - replaced: int, 实际替换的行数（0 表示未找到匹配的 pending 行）
    """
    try:
        body = await request.json()
        task_type = body.get('task_type')
        project_ids = body.get('project_ids')
        new_content = body.get('content')

        if not task_type or not project_ids or not new_content:
            return JSONResponse({
                'success': False,
                'error': 'task_type, project_ids and content are required'
            }, status_code=400)

        from model.chat_messages import ChatMessagesModel
        affected = await asyncio.to_thread(
            ChatMessagesModel.replace_pending_task,
            session_id,
            task_type,
            project_ids,
            new_content
        )

        if affected > 0:
            session_storage.invalidate_cache(session_id)

        return JSONResponse({
            'success': True,
            'replaced': affected
        })
    except Exception as e:
        logger.error(f'替换 pending task 失败: {str(e)}')
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

@router.get('/session/{session_id}/latest-task')
@require_permission("agent_task:view")
async def get_latest_task_for_session(request: Request, session_id: str):
    """获取会话的最新任务信息（用于前端恢复活跃任务流）"""
    try:
        from model.agent_tasks import AgentTasksModel

        task = await asyncio.to_thread(AgentTasksModel.get_latest_by_session, session_id)
        if not task:
            return JSONResponse({
                'success': False,
                'error': '没有任务'
            }, status_code=404)

        return JSONResponse({
            'success': True,
            'task': task.to_dict()
        })
    except Exception as e:
        logger.error(f'获取最新任务失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)

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
        from config.constant import SessionHistoryConstants
        session_entity = ChatSessionsModel.get_by_session_id(session_id)
        expire_hours = SessionHistoryConstants.SESSION_EXPIRE_HOURS_MARKETING
        if session_entity and session_entity.session_type == 2:
            expire_hours = SessionHistoryConstants.SESSION_EXPIRE_HOURS_MARKETING
        else:
            expire_hours = SessionHistoryConstants.SESSION_EXPIRE_HOURS_SCRIPT
        expires_at = datetime.now() + timedelta(hours=expire_hours)
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


def _marketing_media_preferences_sync(user_id: str, world_id: str):
    profiles = {}
    for media_type, modes in (
        (MediaGenerationType.IMAGE, MediaGenerationMode.IMAGE_MODES),
        (MediaGenerationType.VIDEO, MediaGenerationMode.VIDEO_MODES),
    ):
        for mode in modes:
            profile = MediaGenerationPreferenceService.get_profile(
                user_id,
                world_id,
                MediaGenerationSurface.MARKETING_UI,
                media_type,
                mode,
            )
            profiles[MediaGenerationPreferenceService.slot_key(media_type, mode)] = profile
    return profiles


def _resolve_explicit_image_task_id(image_preferences: Dict[str, Any], image_mode: str):
    """从 image_preferences 解析显式生图 task_id（请求级，优先于世界默认偏好）。"""
    explicit_image_task_id = image_preferences.get('task_id')
    if explicit_image_task_id not in (None, ''):
        try:
            return int(explicit_image_task_id)
        except (TypeError, ValueError):
            return None
    model_name = image_preferences.get('model_name')
    if not model_name:
        return None
    required_category = (
        TaskCategory.IMAGE_EDIT
        if image_mode == MediaGenerationMode.IMAGE_EDIT
        else TaskCategory.TEXT_TO_IMAGE
    )
    matched = next(
        (
            config for config in UnifiedConfigRegistry.get_all()
            if (config.name == model_name or config.key == model_name)
            and required_category in {config.category, *(config.categories or [])}
        ),
        None,
    )
    return matched.id if matched else None


def _apply_image_task_id_to_execution_profiles(
    user_id: str,
    world_id: str,
    profiles: Dict[str, Any],
    request_slots: set,
    image_preferences: Dict[str, Any],
    explicit_image_task_id: int,
    *,
    persist_world_default: bool = True,
) -> None:
    """将显式生图模型写入本任务的 image 槽位快照来源。

    - 同时尝试 text_to_image / image_edit（模型不兼容则跳过该槽）
    - 默认仍写入 marketing_ui media_pref 作为「下次任务默认」；任务真相源是随后的 generation_snapshots
    """
    base_image_profile = dict(image_preferences)
    base_image_profile['task_id'] = int(explicit_image_task_id)
    for mode in (MediaGenerationMode.TEXT_TO_IMAGE, MediaGenerationMode.IMAGE_EDIT):
        image_slot = MediaGenerationPreferenceService.slot_key(MediaGenerationType.IMAGE, mode)
        existing = profiles.get(image_slot) or {}
        mode_profile = {
            key: value
            for key, value in {**existing, **base_image_profile}.items()
            if key in MediaGenerationPreferenceService.PROFILE_FIELDS or key == 'task_id'
        }
        mode_profile['task_id'] = int(explicit_image_task_id)
        try:
            if persist_world_default:
                saved = MediaGenerationPreferenceService.save_profile(
                    user_id,
                    world_id,
                    MediaGenerationSurface.MARKETING_UI,
                    MediaGenerationType.IMAGE,
                    mode,
                    mode_profile,
                )
            else:
                # 仅本任务内存覆盖：校验模型兼容性但不落库
                config = MediaGenerationPreferenceService.validate_model(
                    mode_profile.get('task_id'),
                    MediaGenerationType.IMAGE,
                    mode,
                    image_mode=mode_profile.get('image_mode'),
                )
                saved = dict(mode_profile)
                saved.update(
                    {
                        'schema_version': 1,
                        'task_id': int(config.id),
                        'model_key': config.key,
                        'model_name': config.name,
                    }
                )
            profiles[image_slot] = saved
            request_slots.add(image_slot)
        except (MediaGenerationPreferenceError, ValueError, TypeError) as mode_err:
            logger.warning(
                '任务创建时写入 image 槽位跳过: user_id=%s world_id=%s mode=%s task_id=%s err=%s',
                user_id, world_id, mode, explicit_image_task_id, mode_err,
            )


def _apply_video_task_id_to_execution_profiles(
    user_id: str,
    world_id: str,
    profiles: Dict[str, Any],
    request_slots: set,
    video_preferences: Dict[str, Any],
    explicit_video_task_id: int,
    *,
    persist_world_default: bool = True,
) -> None:
    """将界面选中的视频模型写入所有兼容的 video 槽位快照。

    避免只写入 text_to_video / image_to_video，参考生视频槽仍停留在
    MiniMax H3 参考生视频默认值，导致界面显示 Seedance 2.5、实际却跑 H3。
    """
    from config.unified_config import resolve_video_clone_task_config

    base_video_profile = dict(video_preferences)
    for mode in MediaGenerationMode.VIDEO_MODES:
        mode_task_id = int(explicit_video_task_id)
        if mode == MediaGenerationMode.REFERENCE_TO_VIDEO:
            resolved = resolve_video_clone_task_config(mode_task_id)
            if resolved is not None:
                mode_task_id = int(resolved.id)
        video_slot = MediaGenerationPreferenceService.slot_key(MediaGenerationType.VIDEO, mode)
        existing = profiles.get(video_slot) or {}
        mode_profile = {
            key: value
            for key, value in {**existing, **base_video_profile}.items()
            if key in MediaGenerationPreferenceService.PROFILE_FIELDS or key == 'task_id'
        }
        mode_profile['task_id'] = mode_task_id
        try:
            if persist_world_default:
                saved = MediaGenerationPreferenceService.save_profile(
                    user_id,
                    world_id,
                    MediaGenerationSurface.MARKETING_UI,
                    MediaGenerationType.VIDEO,
                    mode,
                    mode_profile,
                )
            else:
                config = MediaGenerationPreferenceService.validate_model(
                    mode_profile.get('task_id'),
                    MediaGenerationType.VIDEO,
                    mode,
                    image_mode=mode_profile.get('image_mode'),
                    has_reference_audio_video=(mode == MediaGenerationMode.REFERENCE_TO_VIDEO),
                )
                saved = dict(mode_profile)
                saved.update(
                    {
                        'schema_version': 1,
                        'task_id': int(config.id),
                        'model_key': config.key,
                        'model_name': config.name,
                    }
                )
            profiles[video_slot] = saved
            request_slots.add(video_slot)
        except (MediaGenerationPreferenceError, ValueError, TypeError) as mode_err:
            logger.warning(
                '任务创建时写入 video 槽位跳过: user_id=%s world_id=%s mode=%s task_id=%s err=%s',
                user_id, world_id, mode, mode_task_id, mode_err,
            )


def _build_marketing_task_execution_context_sync(
    user_id: str,
    world_id: str,
    task_request,
) -> Dict[str, Any]:
    profiles = _marketing_media_preferences_sync(user_id, world_id)
    request_slots = set()

    image_preferences = dict(task_request.image_preferences or {})
    image_mode = MediaGenerationPreferenceService.determine_mode(
        MediaGenerationType.IMAGE,
        image_urls=task_request.image_urls,
    )
    explicit_image_task_id = _resolve_explicit_image_task_id(image_preferences, image_mode)
    if explicit_image_task_id is not None:
        _apply_image_task_id_to_execution_profiles(
            user_id,
            world_id,
            profiles,
            request_slots,
            image_preferences,
            explicit_image_task_id,
            persist_world_default=True,
        )

    video_preferences = dict(task_request.video_preferences or {})
    explicit_video_task_id = video_preferences.get('task_id')
    if explicit_video_task_id in (None, '') and video_preferences.get('model_name'):
        wanted = str(video_preferences.get('model_name') or '').strip()
        if wanted:
            matched = next(
                (
                    config for config in UnifiedConfigRegistry.get_all()
                    if wanted in {
                        config.name,
                        config.key,
                        getattr(config, 'short_key', None),
                    }
                    and TaskCategory.IMAGE_TO_VIDEO in {config.category, *(config.categories or [])}
                ),
                None,
            )
            if matched:
                explicit_video_task_id = matched.id
    if explicit_video_task_id not in (None, ''):
        _apply_video_task_id_to_execution_profiles(
            user_id,
            world_id,
            profiles,
            request_slots,
            video_preferences,
            int(explicit_video_task_id),
            persist_world_default=True,
        )

    snapshots = {}
    for slot, profile in profiles.items():
        media_type, mode = slot.split('.', 1)
        snapshots[slot] = MediaGenerationPreferenceService.build_snapshot(
            profile,
            MediaGenerationSurface.MARKETING_UI,
            media_type,
            mode,
            model_source='request' if slot in request_slots else 'preference',
            has_reference_audio_video=(
                mode == MediaGenerationMode.REFERENCE_TO_VIDEO
                and bool(task_request.video_urls or task_request.audio_urls)
            ),
        )
    return {
        'schema_version': 1,
        'surface': MediaGenerationSurface.MARKETING_UI,
        'generation_snapshots': snapshots,
    }


@router.get('/marketing/media-preferences')
@require_permission("world:view")
async def get_marketing_media_preferences(
    request: Request,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...),
    header_user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    resolved_user_id = get_user_id_from_header(header_user_id)
    if str(resolved_user_id) != str(user_id):
        return JSONResponse(status_code=403, content={'success': False, 'error': 'user_id 与登录用户不一致'})
    await asyncio.to_thread(ensure_world_access, int(world_id), resolved_user_id, Action.VIEW)
    try:
        profiles = await asyncio.to_thread(
            _marketing_media_preferences_sync, str(resolved_user_id), str(world_id)
        )
        return JSONResponse({'success': True, 'profiles': profiles})
    except MediaGenerationPreferenceError as exc:
        return JSONResponse(status_code=400, content={'success': False, 'error': exc.to_dict()})


@router.put('/marketing/media-preferences')
@require_permission("world:update")
async def update_marketing_media_preference(
    request: Request,
    header_user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    data = await request.json()
    resolved_user_id = get_user_id_from_header(header_user_id)
    user_id = str(data.get('user_id') or '')
    world_id = str(data.get('world_id') or '')
    if not user_id or not world_id:
        return JSONResponse(
            status_code=400,
            content={'success': False, 'error': 'user_id 和 world_id 不能为空'},
        )
    if str(resolved_user_id) != user_id:
        return JSONResponse(status_code=403, content={'success': False, 'error': 'user_id 与登录用户不一致'})
    await asyncio.to_thread(ensure_world_access, int(world_id), resolved_user_id, Action.EDIT)
    try:
        profile = await asyncio.to_thread(
            MediaGenerationPreferenceService.save_profile,
            str(resolved_user_id),
            world_id,
            MediaGenerationSurface.MARKETING_UI,
            data.get('media_type'),
            data.get('mode'),
            data.get('profile'),
        )
        return JSONResponse({'success': True, 'profile': profile})
    except (MediaGenerationPreferenceError, ValueError) as exc:
        error = exc.to_dict() if isinstance(exc, MediaGenerationPreferenceError) else str(exc)
        return JSONResponse(status_code=400, content={'success': False, 'error': error})

@router.get('/text-to-image-models')
async def get_text_to_image_models(scene: Optional[str] = None):
    """获取可用的生图模型列表（从统一配置读取）"""
    try:
        from config.model_catalog import (
            ModelScene,
            annotate_task_models,
            build_tracks_payload,
        )
        models_config = _get_text_to_image_models_from_config()
        models = [
            {
                "task_id": task_id,
                "name": info["name"],
                "computing_power": info["computing_power"],
                "supports_grid_image": info.get("supports_grid_image", False),
                "short_key": info.get("short_key") or "",
                "key": info.get("key") or "",
            }
            for task_id, info in models_config.items()
        ]
        catalog_scene = scene or ModelScene.IMAGE_TEXT_TO_IMAGE
        models = annotate_task_models(models, catalog_scene)
        catalog = build_tracks_payload(catalog_scene, models, kind="task")
        default_task_id = DEFAULT_TEXT_TO_IMAGE_TASK_ID
        value_route = (catalog.get("tracks") or {}).get("value", {}).get("default_route") or {}
        if value_route.get("task_id") is not None:
            default_task_id = value_route["task_id"]
        return JSONResponse({
            "success": True,
            "models": models,
            "default_task_id": default_task_id,
            "catalog": catalog,
        })
    except Exception as e:
        logger.error(f'获取生图模型列表失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


@router.post('/text-to-image-model')
async def set_text_to_image_model(request: Request):
    """设置生图模型。

    scope:
      - session（默认）：本对话草稿 chat_sessions.text_to_image_model_id
      - world_default：世界默认（legacy + media_pref），供新会话种子；不改当前会话草稿
    """
    try:
        data = await request.json()
        user_id = str(data.get('user_id', ''))
        world_id = str(data.get('world_id', ''))
        session_id = data.get('session_id')
        scope = str(data.get('scope') or IMAGE_MODEL_SCOPE_SESSION).strip().lower()
        if scope not in (IMAGE_MODEL_SCOPE_SESSION, IMAGE_MODEL_SCOPE_WORLD_DEFAULT):
            return JSONResponse({
                'success': False,
                'error': f'无效的 scope: {scope}，有效值为 session / world_default',
            }, status_code=400)
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

        if scope == IMAGE_MODEL_SCOPE_WORLD_DEFAULT:
            await asyncio.to_thread(set_text_to_image_model_id, user_id, world_id, task_id)
            await asyncio.to_thread(
                _sync_image_model_to_media_pref_world_default, user_id, world_id, task_id
            )
        else:
            # 本对话：只更新会话草稿；兼容无 session_id 的旧调用则回退写 legacy
            if session_id:
                try:
                    from model.chat_sessions import ChatSessionsModel
                    await asyncio.to_thread(
                        ChatSessionsModel.update_model,
                        session_id=session_id,
                        model=None,
                        model_id=None,
                        text_to_image_model_id=task_id,
                    )
                    logger.info(
                        f'已更新会话生图草稿 - session_id: {session_id}, task_id: {task_id}'
                    )
                except Exception as db_error:
                    logger.error(f'更新会话生图草稿失败: {db_error}')
                    return JSONResponse({
                        'success': False,
                        'error': f'更新会话生图模型失败: {db_error}',
                    }, status_code=500)
            else:
                await asyncio.to_thread(set_text_to_image_model_id, user_id, world_id, task_id)

        # 同步保存比例和分辨率偏好（世界级输出偏好，与 scope 无关）
        ratio = data.get('ratio')
        resolution = data.get('resolution')
        if ratio or resolution:
            prefs = await asyncio.to_thread(get_image_preferences, user_id, world_id)
            if ratio:
                prefs['ratio'] = ratio
            if resolution:
                prefs['resolution'] = resolution
            await asyncio.to_thread(set_image_preferences, user_id, world_id, prefs)

        model_info = models_config[task_id]
        logger.info(
            f'生图模型设置成功 - scope={scope}, user_id={user_id}, world_id={world_id}, '
            f'task_id={task_id}, model={model_info["name"]}'
        )

        return JSONResponse({
            'success': True,
            'message': '生图模型设置成功',
            'task_id': task_id,
            'model_name': model_info["name"],
            'scope': scope,
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
    world_id: str = QueryParam(...),
    session_id: Optional[str] = QueryParam(None)
):
    """获取当前生效的生图模型配置。

    读取优先级：会话草稿（session_id 对应的 chat_sessions.text_to_image_model_id）
    > 世界默认 legacy 偏好（text_to_image_model / media_pref 回填源）。
    显式传入 session_id 可让前端回显与用户在本对话内的切换保持一致，避免刷新后被世界默认覆盖。
    """
    try:
        # 优先读取会话草稿：用户在本对话内切换的生图模型
        session_task_id = None
        if session_id:
            def _load_session_draft():
                from model.chat_sessions import ChatSessionsModel
                session = ChatSessionsModel.get_by_session_id(session_id)
                return getattr(session, 'text_to_image_model_id', None) if session else None

            session_task_id = await asyncio.to_thread(_load_session_draft)

        # 会话草稿有效则采用，否则回退世界默认
        if session_task_id is not None:
            task_id = session_task_id
        else:
            task_id = await asyncio.to_thread(get_text_to_image_model_id, user_id, world_id)

        models_config = _get_text_to_image_models_from_config()
        model_info = models_config.get(task_id, models_config.get(DEFAULT_TEXT_TO_IMAGE_TASK_ID, {}))

        return JSONResponse({
            'success': True,
            'task_id': task_id,
            'model_name': model_info.get("name", "unknown"),
            'computing_power': model_info.get("computing_power", 0),
            'scope': 'session' if session_task_id is not None else 'world_default',
        })
    except Exception as e:
        logger.error(f'获取生图模型配置失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


@router.get('/world-defaults/llm')
async def get_world_default_llm(
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...),
):
    """获取世界级默认对话模型。"""
    try:
        pref = await asyncio.to_thread(get_default_llm_model, user_id, world_id)
        return JSONResponse({
            'success': True,
            'default': pref,
        })
    except Exception as e:
        logger.error(f'获取默认对话模型失败: {str(e)}')
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@router.put('/world-defaults/llm')
async def put_world_default_llm(request: Request):
    """设置世界级默认对话模型（新会话种子；不改当前会话）。"""
    try:
        data = await request.json()
        user_id = str(data.get('user_id') or '')
        world_id = str(data.get('world_id') or '')
        if not user_id or not world_id:
            return JSONResponse(
                {'success': False, 'error': 'user_id 和 world_id 不能为空'},
                status_code=400,
            )
        model = data.get('model')
        if not model:
            return JSONResponse({'success': False, 'error': 'model 不能为空'}, status_code=400)
        try:
            saved = await asyncio.to_thread(
                set_default_llm_model,
                user_id,
                world_id,
                {
                    'model': model,
                    'model_id': data.get('model_id'),
                    'vendor_id': data.get('vendor_id'),
                    'name': data.get('name') or model,
                },
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse({'success': False, 'error': str(exc)}, status_code=400)
        logger.info(
            f'默认对话模型已设置 user_id={user_id} world_id={world_id} model={saved.get("model")}'
        )
        return JSONResponse({'success': True, 'default': saved})
    except Exception as e:
        logger.error(f'设置默认对话模型失败: {str(e)}')
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@router.get('/video-model')
async def get_video_models(
    category: str = QueryParam("text_to_video"),
    user_id: Optional[str] = QueryParam(None),
    world_id: Optional[str] = QueryParam(None)
):
    """获取可用的视频模型列表"""
    try:
        from config.unified_config import UnifiedConfigRegistry, TaskCategory

        valid_categories = [TaskCategory.TEXT_TO_VIDEO, TaskCategory.IMAGE_TO_VIDEO]
        if category not in valid_categories:
            return JSONResponse({
                'success': False,
                'error': f'无效的 category: {category}，有效值为: {valid_categories}'
            }, status_code=400)

        configs = UnifiedConfigRegistry.get_by_category(category)
        models = []
        for c in configs:
            if c.enabled and not c.hidden:
                models.append({
                    'task_id': c.id,
                    'key': c.key,
                    'name': c.name,
                    'supported_durations': c.supported_durations or [],
                    'default_duration': c.default_duration,
                    'supported_ratios': c.supported_ratios or [],
                    'computing_power': c.get_computing_power() if c.computing_power else 0
                })

        # 获取当前用户的偏好
        current_task_id = None
        if user_id and world_id:
            if category == TaskCategory.TEXT_TO_VIDEO:
                current_task_id = get_text_to_video_model_id(user_id, world_id)
            else:
                current_task_id = get_image_to_video_model_id(user_id, world_id)

        return JSONResponse({
            'success': True,
            'category': category,
            'models': models,
            'current_task_id': current_task_id
        })
    except Exception as e:
        logger.error(f'获取视频模型列表失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


@router.post('/video-model')
async def set_video_model(request: Request):
    """设置视频模型偏好"""
    from config.unified_config import UnifiedConfigRegistry, TaskCategory
    try:
        data = await request.json()
        user_id = str(data.get('user_id', ''))
        world_id = str(data.get('world_id', ''))
        task_id = data.get('task_id')
        category = data.get('category', TaskCategory.TEXT_TO_VIDEO)

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

        # 验证 task_id 是否属于指定类别
        config = UnifiedConfigRegistry.get_by_id(task_id)
        if not config:
            return JSONResponse({
                'success': False,
                'error': f'无效的 task_id: {task_id}'
            }, status_code=400)

        # 验证类别匹配
        valid_categories = [TaskCategory.TEXT_TO_VIDEO, TaskCategory.IMAGE_TO_VIDEO]
        if category not in valid_categories:
            return JSONResponse({
                'success': False,
                'error': f'无效的 category: {category}'
            }, status_code=400)

        # 检查模型的类别是否包含请求的类别
        model_categories = [config.category]
        if config.categories:
            model_categories.extend(config.categories)
        if category not in model_categories:
            return JSONResponse({
                'success': False,
                'error': f'模型 {config.name} 不属于类别 {category}'
            }, status_code=400)

        # 保存偏好：检查模型实际支持的所有 category，对每个匹配的都设置
        if TaskCategory.TEXT_TO_VIDEO in model_categories:
            set_text_to_video_model_id(user_id, world_id, task_id)
        if TaskCategory.IMAGE_TO_VIDEO in model_categories:
            set_image_to_video_model_id(user_id, world_id, task_id)

        # 同步更新 video_preferences 缓存（含 model_name、ratio、duration 等）
        video_prefs = data.get('video_preferences')
        if video_prefs and isinstance(video_prefs, dict):
            existing_prefs = get_video_preferences(user_id, world_id)
            existing_prefs.update(video_prefs)
            existing_prefs['task_id'] = task_id
            existing_prefs['model_name'] = config.name
            set_video_preferences(user_id, world_id, existing_prefs)

        return JSONResponse({
            'success': True,
            'task_id': task_id,
            'model_name': config.name,
            'category': category
        })
    except Exception as e:
        logger.error(f'设置视频模型偏好失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


@router.get('/sessions')
async def list_sessions(
    user_id: Optional[str] = QueryParam(None),
    world_id: Optional[str] = QueryParam(None),
    session_type: Optional[int] = QueryParam(None)
):
    """列出所有会话"""
    try:
        from model.chat_sessions import ChatSessionsModel

        if user_id:
            # 从数据库查询用户的会话
            entities = ChatSessionsModel.list_by_user(user_id, world_id, active_only=True, limit=100, session_type=session_type)
            def _extract_title(entity):
                """获取会话标题：优先用数据库 title，否则从对话历史提取"""
                if entity.title:
                    return entity.title
                for msg in entity.conversation_history:
                    if isinstance(msg, dict) and msg.get('role') == 'user':
                        content = msg.get('content', '')
                        if isinstance(content, str) and content.strip():
                            # 去除 HTML 标签和图片引用，取纯文本
                            clean = re.sub(r'<[^>]+>', '', content).strip()
                            clean = re.sub(r'\[图片\d+\]', '', clean).strip()
                            clean = re.sub(r'\s+', ' ', clean).strip()
                            if clean:
                                return clean[:20] + ('...' if len(clean) > 20 else '')
                return '新对话'

            session_list = [
                {
                    'session_id': e.session_id,
                    'user_id': e.user_id,
                    'world_id': e.world_id,
                    'title': _extract_title(e),
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
                    # 从对话历史提取标题
                    title = '新对话'
                    for msg in session.get_history():
                        if isinstance(msg, dict) and msg.get('role') == 'user':
                            content = msg.get('content', '')
                            if isinstance(content, str) and content.strip():
                                clean = re.sub(r'<[^>]+>', '', content).strip()
                                # 去除 URL 和图片标签，只保留用户文字
                                clean = re.sub(r'https?://\S+', '', clean).strip()
                                clean = re.sub(r'\[图片\d+][（(]URL:[\s\S]*?[）)]\n?', '', clean).strip()
                                clean = re.sub(r'\s+', ' ', clean).strip()
                                if clean:
                                    title = clean[:20] + ('...' if len(clean) > 20 else '')
                                    break
                    session_list.append({
                        'session_id': sid,
                        'user_id': session.user_id,
                        'world_id': session.world_id,
                        'title': title,
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


@router.delete('/session/{session_id}')
@require_permission("script_session:delete")
async def delete_session(request: Request, session_id: str):
    """删除会话（软删除）"""
    try:
        from model.chat_sessions import ChatSessionsModel
        affected = ChatSessionsModel.soft_delete(session_id)
        if affected > 0:
            return JSONResponse({'success': True})
        return JSONResponse({'success': False, 'error': '会话不存在'}, status_code=404)
    except Exception as e:
        logger.error(f'删除会话失败: {str(e)}')
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@router.put('/session/{session_id}/title')
@require_permission("script_session:update")
async def update_session_title(request: Request, session_id: str, body: SessionTitleUpdateRequest):
    """更新会话标题"""
    try:
        if not body.title.strip():
            return JSONResponse({'success': False, 'error': '标题不能为空'}, status_code=400)
        from model.chat_sessions import ChatSessionsModel
        affected = ChatSessionsModel.update_title(session_id, body.title.strip())
        if affected > 0:
            return JSONResponse({'success': True})
        return JSONResponse({'success': False, 'error': '会话不存在'}, status_code=404)
    except Exception as e:
        logger.error(f'更新会话标题失败: {str(e)}')
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

@router.get('/vendors')
async def get_vendors():
    """获取所有供应商列表（含图标），供前端动态加载"""
    try:
        from model.vendor import VendorDAO
        from config.constant import VENDOR_ICONS
        vendors = VendorDAO.get_all()
        result = []
        for v in vendors:
            result.append({
                'id': v.id,
                'vendor_name': v.vendor_name,
                'note': v.note,
                'icon': VENDOR_ICONS.get(v.vendor_name, '📦')
            })
        return JSONResponse({'success': True, 'vendors': result})
    except Exception as e:
        logger.error(f'获取供应商列表失败: {str(e)}')
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@router.get('/models')
async def get_available_models(scene: Optional[str] = None):
    """获取可用的 AI 模型列表，根据 vendor 表分组。

    scene 可选，传入后附加性价比/效果双档 catalog，并为每条模型标注 track。
    """
    try:
        from llm.llm_client_factory import get_available_models as _get_available_models
        from config.model_catalog import (
            ModelScene,
            annotate_llm_models,
            build_tracks_payload,
        )
        result = await _get_available_models()
        models = result.get('models') or []
        catalog_scene = scene or ModelScene.LLM_CHAT
        models = annotate_llm_models(models, catalog_scene)
        catalog = build_tracks_payload(catalog_scene, models, kind="llm")
        return JSONResponse({
            'success': True,
            'models': models,
            'catalog': catalog,
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
                        if 'story_type' in world_data:
                            update_data['story_type'] = world_data['story_type']
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
                    # 直接使用 list_characters 返回的 json_data，避免用中文名查找拼音文件名导致找不到
                    char_data = char.get('json_data')
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
                        default_voice = char_data.get('default_voice')

                        # 使用 create_or_update 避免并发竞态导致的重复创建
                        char_id = CharacterModel.create_or_update(
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
                            reference_images=reference_images,
                            default_voice=default_voice
                        )
                        # 确保 CDN mapping（图片 + 音频）
                        try:
                            from utils.media_mapping_util import ensure_entity_image_mapping
                            from model.media_file_mapping import MediaFileEntity
                            if reference_image:
                                ensure_entity_image_mapping(
                                    user_id=user_id,
                                    image_url=reference_image,
                                    entity_type=MediaFileEntity.CHARACTER,
                                    entity_id=char_id,
                                    label="image"
                                )
                            if default_voice:
                                ensure_entity_image_mapping(
                                    user_id=user_id,
                                    image_url=default_voice,
                                    entity_type=MediaFileEntity.CHARACTER,
                                    entity_id=char_id,
                                    label="voice"
                                )
                        except Exception as e:
                            logger.warning(f"CDN mapping for character {name} failed: {e}")
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
                    script_data = file_manager.get_script(script['file_name'], str(user_id), str(world_id))
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
            
            # 4. 提交场景（两阶段：先建行再按名称挂 parent_id，避免名称被 int 静默丢弃）
            def resolve_location_parent_name(loc_data: dict) -> Optional[str]:
                """文件层父引用：优先 parent_name，其次非纯数字 parent_id 当名称。"""
                if not isinstance(loc_data, dict):
                    return None
                pn = loc_data.get('parent_name')
                if pn is not None and str(pn).strip():
                    return str(pn).strip()
                raw = loc_data.get('parent_id')
                if raw is None or raw == '':
                    return None
                s = str(raw).strip()
                if not s:
                    return None
                # 纯数字视为 DB id，Phase B 单独处理
                if s.isdigit():
                    return None
                return s

            locations = file_manager.list_locations(str(user_id), str(world_id))
            name_to_db_id: Dict[str, int] = {}
            pending_parent_by_name: Dict[str, Optional[str]] = {}
            pending_parent_id_raw: Dict[str, Any] = {}

            # Phase A：upsert 全部场景；已存在不覆盖 parent_id，新建 parent=None
            for loc in locations:
                try:
                    loc_data = loc.get('json_data')
                    if not loc_data or not isinstance(loc_data, dict):
                        results['locations']['skipped'] += 1
                        continue
                    name = loc_data.get('name', loc['name'])
                    description = loc_data.get('description')
                    reference_image = loc_data.get('reference_image')
                    reference_images = loc_data.get('reference_images')
                    pending_parent_by_name[name] = resolve_location_parent_name(loc_data)
                    pending_parent_id_raw[name] = loc_data.get('parent_id')

                    existing = LocationModel.get_by_name(world_id, name)
                    if existing:
                        LocationModel.update(
                            existing.id,
                            description=description,
                            reference_image=reference_image,
                            reference_images=reference_images,
                        )
                        loc_id = existing.id
                    else:
                        loc_id = LocationModel.create(
                            world_id=world_id,
                            name=name,
                            user_id=user_id,
                            parent_id=None,
                            reference_image=reference_image,
                            reference_images=reference_images,
                            description=description,
                        )
                    name_to_db_id[name] = int(loc_id)
                    try:
                        if reference_image:
                            from utils.media_mapping_util import ensure_entity_image_mapping
                            from model.media_file_mapping import MediaFileEntity
                            ensure_entity_image_mapping(
                                user_id=user_id,
                                image_url=reference_image,
                                entity_type=MediaFileEntity.LOCATION,
                                entity_id=loc_id,
                                label="image"
                            )
                    except Exception as e:
                        logger.warning(f"CDN mapping for location {name} failed: {e}")
                    results['locations']['success'] += 1
                    results['total'] += 1
                except Exception as e:
                    results['locations']['failed'] += 1
                    results['locations']['errors'].append(f"{loc.get('name', '?')}: {str(e)}")

            # Phase B：按 parent_name / 数字 parent_id 挂接父级（父必须是顶级）
            for child_name, parent_name in pending_parent_by_name.items():
                child_id = name_to_db_id.get(child_name)
                if not child_id:
                    continue
                parent_db_id = None
                raw_parent = pending_parent_id_raw.get(child_name)
                if parent_name:
                    parent_db_id = name_to_db_id.get(parent_name)
                    if not parent_db_id:
                        parent_row = LocationModel.get_by_name(world_id, parent_name)
                        if parent_row:
                            parent_db_id = int(parent_row.id)
                elif raw_parent is not None and str(raw_parent).strip().isdigit():
                    try:
                        cand = int(raw_parent)
                        parent_obj = LocationModel.get_by_id(cand)
                        if parent_obj and int(parent_obj.world_id) == world_id:
                            parent_db_id = cand
                    except (TypeError, ValueError):
                        parent_db_id = None

                if not parent_name and not parent_db_id:
                    # 明确顶层：清空父级
                    try:
                        LocationModel.update(child_id, parent_id=None)
                    except Exception as e:
                        logger.warning(f"Clear parent for location {child_name} failed: {e}")
                    continue

                if not parent_db_id:
                    results['locations']['errors'].append(
                        f"{child_name}: 找不到父场景「{parent_name or raw_parent}」，未写入 parent_id"
                    )
                    continue
                if parent_db_id == child_id:
                    results['locations']['errors'].append(f"{child_name}: 不能将自己设为父场景")
                    continue
                parent_obj = LocationModel.get_by_id(parent_db_id)
                if not parent_obj:
                    results['locations']['errors'].append(f"{child_name}: 父场景 id={parent_db_id} 不存在")
                    continue
                if parent_obj.parent_id is not None:
                    results['locations']['errors'].append(
                        f"{child_name}: 父场景「{parent_obj.name}」不是顶级场景，已跳过挂接"
                    )
                    continue
                try:
                    LocationModel.update(child_id, parent_id=parent_db_id)
                except Exception as e:
                    results['locations']['errors'].append(f"{child_name}: 挂接父级失败 {e}")
            
            # 5. 提交道具
            props = file_manager.list_props(str(user_id), str(world_id))
            for prop in props:
                try:
                    # 直接使用 list_props 返回的 json_data，避免用中文名查找拼音文件名导致找不到
                    prop_data = prop.get('json_data')
                    if prop_data and isinstance(prop_data, dict):
                        name = prop_data.get('name', prop['name'])
                        description = prop_data.get('description')
                        reference_image = prop_data.get('reference_image')
                        
                        # 使用 create_or_update 避免并发竞态导致的重复创建
                        prop_id = PropsModel.create_or_update(
                            world_id=world_id,
                            name=name,
                            user_id=user_id,
                            content=description,
                            reference_image=reference_image
                        )
                        # 确保 CDN mapping
                        try:
                            if reference_image:
                                from utils.media_mapping_util import ensure_entity_image_mapping
                                from model.media_file_mapping import MediaFileEntity
                                ensure_entity_image_mapping(
                                    user_id=user_id,
                                    image_url=reference_image,
                                    entity_type=MediaFileEntity.PROPS,
                                    entity_id=prop_id,
                                    label="image"
                                )
                        except Exception as e:
                            logger.warning(f"CDN mapping for prop {name} failed: {e}")
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

@router.post('/script-writer/characters/reference-audio')
@require_permission("character:edit")
async def generate_character_reference_audio(
    request: Request,
    audio_request: CharacterReferenceAudioRequest,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id")
):
    """
    提交角色参考音频生成任务（异步非阻塞）

    提交后立即返回任务 ID，前端通过 GET /script-writer/characters/reference-audio-status/{task_id} 轮询结果
    """
    try:
        if not user_id:
            body = await request.json()
            user_id = body.get('user_id')
        if not user_id:
            return JSONResponse({'success': False, 'error': '缺少用户ID'}, status_code=400)
        character = None
        if audio_request.character_id:
            character = await asyncio.to_thread(CharacterModel.get_by_id, audio_request.character_id)
        elif audio_request.character_name:
            character = await asyncio.to_thread(CharacterModel.get_by_name, audio_request.world_id, audio_request.character_name)
        if character and (character.world_id != audio_request.world_id or character.user_id != int(user_id)):
            return JSONResponse({'success': False, 'error': '无权限访问该角色'}, status_code=403)
        character_data = character.to_dict() if character else (audio_request.character_data or {})
        if not character_data:
            return JSONResponse({'success': False, 'error': '缺少角色数据'}, status_code=400)
        if audio_request.character_name and not character_data.get('name'):
            character_data['name'] = audio_request.character_name

        # 构建参数
        style_prompt = await build_character_audio_style_prompt(
            character_data, audio_request.style_prompt,
            model=audio_request.model, vendor_id=audio_request.vendor_id
        )
        text = await build_character_audio_text(
            character_data, audio_request.text,
            model=audio_request.model, vendor_id=audio_request.vendor_id
        )

        # 写入异步任务表，由 scheduler 后台统一处理提交
        from model import AsyncTasksModel
        from config.unified_config import AsyncTaskImplementationId

        task_id = AsyncTasksModel.create_and_schedule(
            implementation=AsyncTaskImplementationId.RUNNINGHUB_AUDIO,
            user_id=int(user_id),
            params={'style_prompt': style_prompt, 'text': text}
        )

        return JSONResponse({
            'success': True,
            'task_id': task_id,
            'message': '音频生成任务已提交，请通过 task_id 查询状态'
        })
    except Exception as e:
        logger.error(f'生成角色参考音频失败: {str(e)}', exc_info=True)
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@router.get('/script-writer/characters/reference-audio-status/{task_id}')
@require_permission("character:view")
async def get_reference_audio_status(request: Request, task_id: int):
    """查询角色参考音频生成任务状态"""
    try:
        from model import AsyncTasksModel, AsyncTaskStatus
        task = AsyncTasksModel.get_by_id(task_id)
        if not task:
            return JSONResponse({'success': False, 'error': '任务不存在'}, status_code=404)

        if task.status == AsyncTaskStatus.COMPLETED:
            return JSONResponse({
                'success': True,
                'status': 'SUCCESS',
                'task_id': task_id,
                'result_url': task.result_url,
                'character_id': task.get_params_dict().get('character_id')
            })
        elif task.status == AsyncTaskStatus.FAILED:
            return JSONResponse({
                'success': True,
                'status': 'FAILED',
                'task_id': task_id,
                'error': task.error_message or '音频生成失败'
            })
        elif task.status == AsyncTaskStatus.TIMEOUT:
            return JSONResponse({
                'success': True,
                'status': 'TIMEOUT',
                'task_id': task_id,
                'error': '任务超时'
            })
        else:
            return JSONResponse({
                'success': True,
                'status': 'RUNNING',
                'task_id': task_id
            })
    except Exception as e:
        logger.error(f'查询音频任务状态失败: {str(e)}')
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)

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
        json_data = json.loads(content)
        json_data['story_type'] = StoryType.normalize(json_data.get('story_type'))
        content = json.dumps(json_data, ensure_ascii=False, indent=2)
        
        if raw_json:
            # 返回JSON数据用于编辑
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
            world_data['story_type'] = StoryType.normalize(world_data.get('story_type'))
            content = json.dumps(world_data, ensure_ascii=False, indent=2)
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

# ==================== 画风识别 API ====================

@router.get('/style-models')
@require_permission("world:view_files")
async def list_style_models(request: Request):
    """获取可用于画风识别的 vl 模型列表。

    复用 ``llm_client_factory.get_available_models``：它已过滤掉未配置密钥的 vendor，
    且仅返回 enabled + supports_tools 的模型；此处再按 ``supports_vl==True`` 过滤，
    天然满足「必须填了密钥的实施方」要求（与上方 LLM 模型选择器同源过滤）。

    排序：优先 ``volcengine / doubao-seed-2-0-lite``，再其余 volcengine，再其他供应商。
    """
    try:
        from llm.llm_client_factory import get_available_models as _get_available_models
        from config.constant import (
            IMAGE_STYLE_LLM_TIMEOUT,
            IMAGE_STYLE_PREFERRED_MODEL,
            IMAGE_STYLE_PREFERRED_VENDOR,
        )

        result = await _get_available_models()
        pref_vendor = (IMAGE_STYLE_PREFERRED_VENDOR or 'volcengine').lower()
        pref_model = (IMAGE_STYLE_PREFERRED_MODEL or 'doubao-seed-2-0-lite').lower()

        vl_models = []
        for m in result.get('models', []):
            if not m.get('supports_vl'):
                continue
            name = m.get('name') or ''
            vendor_name = m.get('vendor_name') or ''
            is_preferred = (
                vendor_name.lower() == pref_vendor
                and pref_model in name.lower()
            )
            vl_models.append({
                'model_id': m.get('model_id'),
                'vendor_id': m.get('vendor_id'),
                'name': name,
                'vendor_name': vendor_name,
                'recommended': is_preferred,
                'input_token_threshold': m.get('input_token_threshold'),
            })

        def _sort_key(item: dict):
            vendor = (item.get('vendor_name') or '').lower()
            name = (item.get('name') or '').lower()
            is_pref = 0 if item.get('recommended') else 1
            is_volc = 0 if vendor == pref_vendor else 1
            return (is_pref, is_volc, vendor, name)

        vl_models.sort(key=_sort_key)

        from config.model_catalog import (
            ModelScene,
            annotate_llm_models,
            build_tracks_payload,
        )
        vl_models = annotate_llm_models(vl_models, ModelScene.LLM_STYLE_RECOGNIZE)
        catalog = build_tracks_payload(ModelScene.LLM_STYLE_RECOGNIZE, vl_models, kind="llm")

        return JSONResponse({
            'success': True,
            'models': vl_models,
            'llm_timeout': IMAGE_STYLE_LLM_TIMEOUT,
            'preferred_vendor': IMAGE_STYLE_PREFERRED_VENDOR,
            'preferred_model': IMAGE_STYLE_PREFERRED_MODEL,
            'catalog': catalog,
        })
    except Exception as e:
        logger.error(f'获取画风识别模型列表失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


class RecognizeStyleRequest(BaseModel):
    user_id: str
    world_id: str
    auth_token: str = ""
    image_url: str            # /api/upload-image 返回的 url
    model: str                # 如 doubao-seed-2-0-pro
    model_id: Optional[int] = None
    vendor_id: Optional[int] = None


# 提取 LLM 返回中的 JSON 对象（容错：```json 代码块 / 首个 {...}）
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_FIRST_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_style_json(content: str) -> Optional[dict]:
    """从 LLM 文本回复中容错提取 visual_style JSON。

    模型若仍回了 composition_preference，一律丢弃，识别链路只修画风。
    """
    if not content:
        return None
    candidates = []
    m = _JSON_BLOCK_RE.search(content)
    if m:
        candidates.append(m.group(1))
    m = _FIRST_OBJ_RE.search(content)
    if m:
        candidates.append(m.group(0))
    candidates.append(content.strip())

    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict) and 'visual_style' in obj:
                visual_style = str(obj.get('visual_style', '')).strip()
                if visual_style:
                    return {'visual_style': visual_style}
        except Exception:
            continue
    return None


@router.post('/recognize-style')
@require_permission("world:view_files")
async def recognize_style(request: Request, body: RecognizeStyleRequest):
    """调用 vl 模型识别图片画风，仅返回画面风格（供前端确认后再写入）。"""
    from config.constant import IMAGE_STYLE_LLM_TIMEOUT, IMAGE_STYLE_COMPRESS_TIMEOUT
    from utils.image_compressor import compress_local_image_to_base64

    if not body.image_url:
        return JSONResponse({'success': False, 'error': '缺少图片 url'}, status_code=400)
    if not body.model:
        return JSONResponse({'success': False, 'error': '未选择识别模型'}, status_code=400)

    try:
        # 1) 解析 image_url → 本地路径（仅允许本服务 upload 目录下的文件）
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        upload_root = os.path.join(app_dir, 'upload').replace('\\', '/')
        image_url = body.image_url.strip()
        # 取 URL path 部分，定位 upload/... 相对片段
        rel = image_url
        if '://' in rel:
            from urllib.parse import urlparse
            rel = urlparse(rel).path
        rel = rel.lstrip('/').replace('\\', '/')
        if '/upload/' in rel:
            rel = rel[rel.index('/upload/') + len('/upload/'):]
        elif rel.startswith('upload/'):
            rel = rel[len('upload/'):]
        local_path = os.path.normpath(os.path.join(upload_root, rel))
        # 防目录穿越：最终路径必须在 upload_root 下
        if not local_path.replace('\\', '/').startswith(upload_root):
            return JSONResponse({'success': False, 'error': '非法的图片路径'}, status_code=400)
        if not os.path.isfile(local_path):
            return JSONResponse({'success': False, 'error': f'图片文件不存在: {rel}'}, status_code=404)

        # 2) 压缩转 base64（同步 CPU 操作 → to_thread 包装 + wait_for 超时保护）
        try:
            ok, data_url, err = await asyncio.wait_for(
                asyncio.to_thread(
                    compress_local_image_to_base64,
                    local_path, 2.0, 2_073_600
                ),
                timeout=IMAGE_STYLE_COMPRESS_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return JSONResponse({'success': False, 'error': '图片压缩超时，请重试'}, status_code=504)
        if not ok or not data_url:
            return JSONResponse({'success': False, 'error': f'图片处理失败: {err}'}, status_code=400)

        # 3) 构造多模态消息，调用 vl 模型（同步 call_api → to_thread + wait_for）
        # visual_style 规范与 asset-readiness-checker 画风审核条款一致，
        # 字段语义对齐 plot-analyzer：只回答「是什么风格」，不产出构图/色彩。
        system_prompt = (
            "你是一位资深的动画/影视美术指导，负责为项目设定可直接用于生图/生视频的画风。"
            "visual_style 会作为 suffix 拼接到生图/生视频模型的 prompt 后面，"
            "只保留对模型有用的风格关键词。"
            "请只返回一个 JSON 对象，不要包含任何其它文字、解释或 Markdown。"
            "\n\n"
            "字段规则（极其重要）：\n"
            "1) 只输出 visual_style（画面风格），不要输出 composition_preference、"
            "color_language 或其它字段。\n"
            "2) visual_style 只回答「是什么风格？」——先判定画风大类，再写具体风格关键词。\n"
            "   画风大类二选一：\n"
            "   - 写实风格类：真实照片感、电影级写实、纪实摄影；关键词含写实/真实/照片/摄影/电影感。\n"
            "   - 动漫/漫画风格类：日系动漫、美式漫画、卡通；关键词含动漫/二次元/漫画/卡通。\n"
            "   两种大类有本质区别，不可混淆：写实绝不能含「动漫/漫画/二次元」；"
            "动漫绝不能含「写实/照片/摄影」。\n"
            "3) 必须精简：建议 8~20 字，最多不超过 50 字，只写风格关键词。"
            "正确示例：「现代都市写实风格」「电影级写实风格」「日系新海诚动漫风格」"
            "「美漫:漫威风」「迪士尼风格」「皮克斯风」。\n"
            "4) 禁止混入：色调/饱和度/光泽、镜头角度/构图/景别、剧情内容、角色身份、场景叙事、"
            "「生活化」「带货」「居家」等内容描述。\n"
            "5) 禁止误导生图的词：多宫格、分镜图、多格、grid、collage、montage、拼图、拼贴、"
            "四格、九格、四宫格、九宫格、分镜、故事板、对比图、时间线、序列帧、"
            "「生成多张」「每张」「各一张」。\n"
            "6) 禁止笼统：不要写「好看的」「合适的」等无法指导生图的词。\n"
            "7) 不要输出 color_language；色彩信息不要塞进 visual_style。"
        )
        user_text = (
            "请分析这张参考图的画风，仅返回如下 JSON（中文，精简）：\n"
            '{"visual_style":"画风大类+具体风格关键词，如：现代都市写实风格 / 日系新海诚动漫风格"}\n'
            "记住：只写 visual_style，不要写构图倾向、色彩、镜头、剧情内容。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ]

        client = get_llm_client(body.model, vendor_id=body.vendor_id)
        # 仅 OpenAI 兼容系列（含 doubao）的 call_api 支持 request_timeout；
        # Gemini 等原生 client 不支持该参数，传了会 TypeError。先探测再条件传入。
        import inspect as _inspect
        call_kwargs = dict(
            model=body.model,
            messages=messages,
            temperature=0.4,
            max_tokens=400,
            auth_token=body.auth_token or None,
            vendor_id=body.vendor_id,
            model_id=body.model_id,
        )
        if 'request_timeout' in _inspect.signature(client.call_api).parameters:
            call_kwargs['request_timeout'] = IMAGE_STYLE_LLM_TIMEOUT
        try:
            # 外层 wait_for 对所有 client 兜底超时，满足超时红线（R4/R5/R6）
            response = await asyncio.wait_for(
                asyncio.to_thread(client.call_api, **call_kwargs),
                timeout=IMAGE_STYLE_LLM_TIMEOUT + 10,
            )
        except asyncio.TimeoutError:
            return JSONResponse({'success': False, 'error': '模型识别超时，请重试或更换模型'}, status_code=504)

        content = response.choices[0].message.content if response and response.choices else ''
        parsed = _extract_style_json(content)
        if not parsed or not parsed.get('visual_style'):
            return JSONResponse({
                'success': False,
                'error': '无法从模型回复中解析画风结果，请重试或更换模型',
                'raw': content,
            }, status_code=422)

        return JSONResponse({
            'success': True,
            'visual_style': parsed['visual_style'],
            'model': body.model,
            'vendor_id': body.vendor_id,
        })
    except Exception as e:
        logger.error(f'画风识别失败: {str(e)}', exc_info=True)
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


class ApplyWorldStyleRequest(BaseModel):
    user_id: str
    world_id: str
    auth_token: str = ""
    visual_style: str
    composition_preference: Optional[str] = ""  # 兼容旧请求体，忽略不写盘
    image_url: str
    model: str
    vendor_id: Optional[int] = None


@router.post('/world-style')
@require_permission("world:save_files")
async def apply_world_style(request: Request, body: ApplyWorldStyleRequest):
    """将（用户确认后的）画风识别结果写入 world.json，并在 style_history 追加一条记录。

    仅更新 visual_style，不覆盖已有 composition_preference。
    """
    try:
        visual_style = (body.visual_style or '').strip()
        if not visual_style:
            return JSONResponse({'success': False, 'error': '画面风格不能为空'}, status_code=400)

        world_data = file_manager.get_world_json(str(body.user_id), str(body.world_id)) or {}
        world_data['visual_style'] = visual_style

        history = world_data.setdefault('style_history', [])
        history.append({
            'time': datetime.now().isoformat(timespec='seconds'),
            'model': body.model,
            'vendor_id': body.vendor_id,
            'image_url': body.image_url,
            'visual_style': visual_style,
            'composition_preference': '',
        })

        ok = file_manager.save_world(world_data, str(body.user_id), str(body.world_id))
        if not ok:
            return JSONResponse({'success': False, 'error': '世界文件保存失败'}, status_code=500)

        return JSONResponse({
            'success': True,
            'message': '世界画风已更新（画面风格），本次识别已记录到 style_history',
        })
    except Exception as e:
        logger.error(f'应用画风到 world.json 失败: {str(e)}', exc_info=True)
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


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
            return JSONResponse(error_response, status_code=_auth_error_status_code(error_response))
        
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

        # 根据 model_id 查询真实的 vendor_id（而不是使用 task_request 中的默认值 1）
        vendor_id = task_request.vendor_id
        if vendor_id == 1:  # 如果是默认值，尝试从数据库获取真实值
            try:
                real_vendor_id = VendorModelModel.get_vendor_id_by_model_id(model_id)
                if real_vendor_id:
                    vendor_id = real_vendor_id
            except Exception as e:
                logger.warning(f"Failed to get vendor_id for model {model_id}: {e}")
        
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

        # 对话级生图模型：请求显式 task_id > 会话草稿 chat_sessions.text_to_image_model_id
        # > 世界默认 media_pref/legacy。保证 script_writer 改模型后「下一条消息」写入新 task 快照。
        image_prefs = dict(task_request.image_preferences or {})
        if image_prefs.get('task_id') in (None, ''):
            session_image_model_id = getattr(session, 'text_to_image_model_id', None)
            if session_image_model_id in (None, ''):
                try:
                    from model.chat_sessions import ChatSessionsModel
                    session_entity = await asyncio.to_thread(
                        ChatSessionsModel.get_by_session_id, session_id
                    )
                    if session_entity is not None:
                        session_image_model_id = getattr(
                            session_entity, 'text_to_image_model_id', None
                        )
                except Exception as session_err:
                    logger.warning(
                        f'读取会话生图模型草稿失败 session_id={session_id}: {session_err}'
                    )
            if session_image_model_id not in (None, ''):
                try:
                    image_prefs['task_id'] = int(session_image_model_id)
                    task_request.image_preferences = image_prefs
                    logger.info(
                        f'[Agent任务] 使用会话草稿生图模型: session_id={session_id}, '
                        f'task_id={image_prefs["task_id"]}'
                    )
                except (TypeError, ValueError):
                    pass

        try:
            execution_context_json = await asyncio.to_thread(
                _build_marketing_task_execution_context_sync,
                str(user_id),
                str(world_id),
                task_request,
            )
        except MediaGenerationPreferenceError as exc:
            return JSONResponse(
                {'success': False, 'error': exc.to_dict()},
                status_code=400,
            )
        
        # 如果有图片偏好，追加到用户消息中供 PM 和专家参考
        user_message = task_request.message
        if task_request.image_preferences:
            prefs = task_request.image_preferences

            # 同步生图模型配置（优先 task_id，其次 model_name）到 legacy 偏好
            synced_tid = None
            explicit_tid = prefs.get('task_id')
            if explicit_tid not in (None, ''):
                try:
                    synced_tid = int(explicit_tid)
                except (TypeError, ValueError):
                    synced_tid = None
            if synced_tid is None:
                model_name = prefs.get('model_name')
                if model_name:
                    models_config = _get_text_to_image_models_from_config()
                    for tid, info in models_config.items():
                        if info.get('name') == model_name:
                            synced_tid = tid
                            break
            if synced_tid is not None:
                await asyncio.to_thread(
                    set_text_to_image_model_id, user_id, world_id, synced_tid
                )
                logger.info(
                    f'[Agent任务] 已同步生图模型: user_id={user_id}, world_id={world_id}, '
                    f'model={prefs.get("model_name")}, task_id={synced_tid}'
                )

            pref_parts = await asyncio.to_thread(
                sync_agent_image_preferences, user_id, world_id, prefs
            )
            if pref_parts:
                user_message += f"\n\n[用户图片偏好] {', '.join(pref_parts)}"

        # 如果有视频偏好，保存到内存并追加到用户消息中；旧客户端未传时回退到历史偏好。
        effective_video_preferences = task_request.video_preferences or await asyncio.to_thread(
            get_video_preferences, user_id, world_id
        )
        if effective_video_preferences:
            v_prefs = dict(effective_video_preferences)

            # 如果前端传递了 task_id（视频模型选择），同步到模型偏好
            v_task_id = v_prefs.get('task_id')
            v_config = None
            if v_task_id:
                try:
                    v_task_id = int(v_task_id)
                    from config.unified_config import UnifiedConfigRegistry, TaskCategory
                    v_config = UnifiedConfigRegistry.get_by_id(v_task_id)
                    if v_config and v_config.enabled:
                        v_model_categories = [v_config.category]
                        if v_config.categories:
                            v_model_categories.extend(v_config.categories)
                        if TaskCategory.IMAGE_TO_VIDEO in v_model_categories:
                            await asyncio.to_thread(
                                set_image_to_video_model_id, user_id, world_id, v_task_id
                            )
                        if TaskCategory.TEXT_TO_VIDEO in v_model_categories:
                            await asyncio.to_thread(
                                set_text_to_video_model_id, user_id, world_id, v_task_id
                            )
                except (TypeError, ValueError):
                    pass

            # 保存到内存供 MCP 视频工具函数读取
            await asyncio.to_thread(set_video_preferences, user_id, world_id, v_prefs)
            v_pref_parts = []
            if v_prefs.get('ratio'):
                v_pref_parts.append(f"视频比例: {v_prefs['ratio']}")
            if v_prefs.get('duration'):
                if str(v_prefs.get('duration')).lower() == 'auto':
                    v_pref_parts.append("视频时长: auto（模型自动/优先最长）")
                else:
                    v_pref_parts.append(f"视频时长: {v_prefs['duration']}秒")
            if v_prefs.get('image_mode'):
                v_pref_parts.append(f"图片模式: {v_prefs['image_mode']}")
            if v_prefs.get('resolution'):
                v_pref_parts.append(f"视频分辨率: {v_prefs['resolution']}")
            # 添加视频模型名称（优先从前端传入，其次从 task_id 解析）
            v_model_display = v_prefs.get('model_name')
            if not v_model_display and v_config:
                v_model_display = v_config.name
            if v_model_display:
                v_pref_parts.append(f"视频模型: {v_model_display}")
            if v_config:
                from config.unified_config import VIDEO_CLONE_DRIVER_KEYS
                if v_config.key in VIDEO_CLONE_DRIVER_KEYS:
                    v_pref_parts.append("视频克隆: 当前模型支持")
                else:
                    v_pref_parts.append("视频克隆: 当前模型不支持")
            # 人脸处理开关（让智能体感知：仅当开启时才在视频克隆提示词追加「黑框还原真人人脸」）
            if v_prefs.get('enable_face_mask'):
                v_pref_parts.append("人脸处理: 已开启")
            if v_pref_parts:
                user_message += f"\n\n[用户视频偏好] {', '.join(v_pref_parts)}"

        # 创建任务（返回 task_id 字符串）
        task_language = task_request.language or 'zh-CN'
        logger.info(f'创建任务: language={task_language} (from request: {task_request.language})')
        task_id = await asyncio.to_thread(
            task_manager.create_task,
            session_id=session_id,
            user_message=user_message,
            user_id=user_id,
            world_id=world_id,
            auth_token=auth_token,
            vendor_id=vendor_id,
            model_id=model_id,
            enable_thinking=task_request.enable_thinking,
            thinking_effort=task_request.thinking_effort,
            image_urls=task_request.image_urls,
            video_urls=task_request.video_urls,
            audio_urls=task_request.audio_urls,
            thumbnail_urls=task_request.thumbnail_urls,
            language=task_language,
            execution_context_json=execution_context_json,
        )
        
        # 获取任务对象
        task = await asyncio.to_thread(task_manager.get_task, task_id)

        logger.info(f'任务已创建: {task_id}, user_id: {user_id}, model_id: {model_id}')

        # 将用户消息写入 chat_messages（使用 task 创建后的最终 user_message）。
        # 这里必须保留图片/视频/音频 URL 标签，否则历史接口从 chat_messages 恢复时
        # marketing_agent.html 无法还原媒体预览。URL 已由上传接口按 is_local/CDN 配置生成。
        try:
            from script_writer_core.conversation_recorder import ConversationRecorder
            recorder = ConversationRecorder()
            persisted_user_message = build_agent_user_message_with_media(
                user_message=user_message,
                image_urls=task_request.image_urls,
                video_urls=task_request.video_urls,
                audio_urls=task_request.audio_urls,
                thumbnail_urls=task_request.thumbnail_urls,
            )
            await asyncio.to_thread(
                recorder.append_message,
                session_id=session_id,
                role="user",
                content={"text": persisted_user_message},
                provider_payload={"role": "user", "content": persisted_user_message},
                message_type="normal",
                task_id=task_id,
                idempotency_key=f"task:{task_id}:user:initial",
                visibility="both",
                source="frontend",
                agent_scope="pm",
            )
            logger.info(f'User message written to chat_messages for task {task_id}')
        except Exception as e:
            logger.error(f'写入用户消息到 chat_messages 失败（非致命）: {e}')

        # 用户发消息即视为会话活动，顺延过期时间（覆盖任务失败不顺延的缺口）
        try:
            await asyncio.to_thread(
                _extend_session_expiry, session_id, getattr(session, 'session_type', 1)
            )
        except Exception as e:
            logger.error(f'顺延会话过期时间失败（非致命）: {e}')

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
                from config.constant import SessionHistoryConstants
                expire_hours = SessionHistoryConstants.SESSION_EXPIRE_HOURS_MARKETING if getattr(session, 'session_type', 1) == 2 else SessionHistoryConstants.SESSION_EXPIRE_HOURS_SCRIPT
                session_storage.save_session(session, expires_hours=expire_hours)
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
            last_message_id = parse_last_event_id(
                request.headers.get("last-event-id") or request.query_params.get("last_id")
            )  # 用于追踪已读取的消息

            # 立即发送连接确认消息
            yield format_sse_event({'type': 'connected', 'task_id': task_id})

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

                    yield format_sse_event(msg, event_id=msg.get('id'))

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
                        yield format_sse_event({'type': 'heartbeat', 'timestamp': datetime.now().isoformat()})
                        heartbeat_counter = 0

                    # 检查任务状态（从数据库）
                    try:
                        db_task = await asyncio.to_thread(AgentTasksModel.get_by_task_id, task_id)
                        if db_task and db_task.status in ['completed', 'failed', 'cancelled']:
                            logger.info(f"[SSE-STREAM] Task status changed to {db_task.status}, ending stream")
                            yield format_sse_event({'type': 'done', 'status': db_task.status})
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
        # 检查算力是否充足
        auth_token = request.headers.get('Authorization', '').replace('Bearer ', '')
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
                    'error_code': 'INSUFFICIENT_POWER',
                    'message': '您的算力不足，请充值后再试'
                }, status_code=400)

        result = {
            "action": "confirm" if verify_request.approved else "cancel",
            "user_input": verify_request.user_input,
            "image_urls": verify_request.image_urls,
            "video_urls": verify_request.video_urls,
            "audio_urls": verify_request.audio_urls,
            "thumbnail_urls": verify_request.thumbnail_urls,
        }
        success = task_manager.submit_verification(
            verification_id=verification_id,
            result=result
        )

        if not success:
            # 查询实际状态，返回更有意义的错误信息
            db_verification = task_manager.get_verification(verification_id)
            if db_verification and db_verification.status == 'cancelled':
                return JSONResponse({
                    'success': False,
                    'error': '验证已超时',
                    'status': 'cancelled'
                }, status_code=410)
            else:
                return JSONResponse({
                    'success': False,
                    'error': '验证请求不存在或已处理',
                    'status': db_verification.status if db_verification else 'not_found'
                }, status_code=404)

        # 将 verification 回答中的媒体合并到当前任务，确保等待中的 PM/专家能看到真实 URL
        db_verification = task_manager.get_verification(verification_id)

        # 提交验证回答即视为会话活动，顺延过期时间
        try:
            if db_verification:
                from model.agent_tasks import AgentTasksModel
                from model.chat_sessions import ChatSessionsModel
                _task_entity = await asyncio.to_thread(
                    AgentTasksModel.get_by_task_id, db_verification.task_id
                )
                if _task_entity and _task_entity.session_id:
                    _session_entity = await asyncio.to_thread(
                        ChatSessionsModel.get_by_session_id, _task_entity.session_id
                    )
                    if _session_entity:
                        await asyncio.to_thread(
                            _extend_session_expiry,
                            _task_entity.session_id,
                            getattr(_session_entity, 'session_type', 1) or 1
                        )
        except Exception as e:
            logger.error(f'顺延会话过期时间失败（非致命）: {e}')

        if db_verification and (verify_request.image_urls or verify_request.video_urls or verify_request.audio_urls):
            try:
                from model.agent_tasks import AgentTasksModel
                task_entity = await asyncio.to_thread(
                    AgentTasksModel.get_by_task_id, db_verification.task_id
                )
                if task_entity:
                    def _merge_urls(existing, incoming):
                        merged = list(existing or [])
                        for url in incoming or []:
                            if isinstance(url, str) and url and url not in merged:
                                merged.append(url)
                        return merged or None

                    merged_image_urls = _merge_urls(task_entity.image_urls, verify_request.image_urls)
                    merged_video_urls = _merge_urls(task_entity.video_urls, verify_request.video_urls)
                    merged_audio_urls = _merge_urls(task_entity.audio_urls, verify_request.audio_urls)
                    await asyncio.to_thread(
                        AgentTasksModel.update_media_urls,
                        db_verification.task_id,
                        merged_image_urls,
                        merged_video_urls,
                        merged_audio_urls,
                    )
                    task_manager.merge_task_media(
                        db_verification.task_id,
                        image_urls=verify_request.image_urls,
                        video_urls=verify_request.video_urls,
                        audio_urls=verify_request.audio_urls,
                        thumbnail_urls=verify_request.thumbnail_urls,
                    )
            except Exception as e:
                logger.error(f"Failed to merge verification media into task: {e}")

        # 将 verification_answer 写入 chat_messages
        if verify_request.user_input:
            try:
                from script_writer_core.conversation_recorder import ConversationRecorder
                recorder = ConversationRecorder()
                # 从 verification 获取 session_id（通过 task_id 关联 agent_tasks 表）
                session_id_for_msg = None
                if db_verification:
                    from model.agent_tasks import AgentTasksModel
                    task_entity = await asyncio.to_thread(
                        AgentTasksModel.get_by_task_id, db_verification.task_id
                    )
                    if task_entity:
                        session_id_for_msg = task_entity.session_id
                if session_id_for_msg:
                    persisted_verification_answer = build_agent_user_message_with_media(
                        user_message=verify_request.user_input,
                        image_urls=verify_request.image_urls,
                        video_urls=verify_request.video_urls,
                        audio_urls=verify_request.audio_urls,
                        thumbnail_urls=verify_request.thumbnail_urls,
                    )
                    await asyncio.to_thread(
                        recorder.append_message,
                        session_id=session_id_for_msg,
                        role="user",
                        content={"text": persisted_verification_answer},
                        message_type="verification_answer",
                        verification_id=verification_id,
                        idempotency_key=f"verification:{verification_id}:answer:{recorder._content_hash({'text': persisted_verification_answer})}",
                        visibility="both",
                        source="verification",
                        agent_scope="pm",
                    )
            except Exception as e:
                logger.error(f"Failed to persist verification_answer: {e}")

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


def _validate_entity_content(content: str, label: str = "内容"):
    """
    校验实体文件内容：若内容看起来是 JSON（以 { 或 [ 开头）但解析失败，返回错误。
    非 JSON 内容（纯文本/markdown 等）放行，交由下层 FileManager 原样写入。
    与 FileManager._safe_write_entity_json 的策略保持一致。
    """
    if not content or not content.strip():
        return False, f'{label}不能为空'
    stripped = content.strip()
    if stripped[:1] in ('{', '['):
        try:
            json.loads(stripped)
        except (json.JSONDecodeError, ValueError) as e:
            return False, f'{label}JSON格式错误: {e}'
    return True, None


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

        ok, err = _validate_entity_content(content, '角色卡内容')
        if not ok:
            return JSONResponse({'success': False, 'error': err}, status_code=400)
        
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

        ok, err = _validate_entity_content(content, '剧本内容')
        if not ok:
            return JSONResponse({'success': False, 'error': err}, status_code=400)
        
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

        ok, err = _validate_entity_content(content, '场景内容')
        if not ok:
            return JSONResponse({'success': False, 'error': err}, status_code=400)
        
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

        ok, err = _validate_entity_content(content, '道具内容')
        if not ok:
            return JSONResponse({'success': False, 'error': err}, status_code=400)
        
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
                ],
                'character_count': int,
                'character_image_count': int,
                'location_count': int,
                'location_image_count': int
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

        # 2. 检查角色参考图（只需至少一个角色有图即可）
        characters_result = CharacterModel.list_by_world(world_id, page=1, page_size=1000)
        characters = characters_result.get('data', [])
        result['character_count'] = len(characters)
        result['character_image_count'] = sum(
            1 for c in characters
            if c.get('reference_image') or c.get('reference_images')
        )
        if result['character_image_count'] == 0 and characters:
            result['missing_assets'].append({
                'type': 'characters',
                'items': [c['name'] for c in characters]
            })

        # 3. 检查场景参考图（只需至少一个场景有图即可）
        locations_result = LocationModel.list_by_world(world_id, page=1, page_size=1000)
        locations = locations_result.get('data', [])
        result['location_count'] = len(locations)
        result['location_image_count'] = sum(
            1 for loc in locations
            if loc.get('reference_image') or loc.get('reference_images')
        )
        if result['location_image_count'] == 0 and locations:
            result['missing_assets'].append({
                'type': 'locations',
                'items': [loc['name'] for loc in locations]
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
                'type': 'props',
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
        item_type: 项目类型 (1=character, 2=location, 3=props, 4=style 画风识别参考图)
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
        elif item_type == 4:  # style 画风识别参考图
            upload_dir = 'upload/style/pic'
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


@router.post('/upload-agent-image')
@require_permission("script_writer:upload_image")
async def upload_agent_image(
    request: Request,
    file: UploadFile = File(...),
    session_id: str = Form(...)
):
    """
    上传 Agent 对话模式的图片（支持多图）

    图片保存到 upload/marketing/pic/{session_id}/ 目录，
    以 session_id 为子目录，方便定时清理脚本比照 chat_sessions 表删除孤立图片。

    Args:
        file: 图片文件
        session_id: 会话ID（用于组织存储路径）

    Returns:
        图片访问 URL
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

        content = await file.read()
        if len(content) > max_size_bytes:
            return JSONResponse({
                'success': False,
                'error': f'图片大小不能超过 {max_size_mb}MB'
            }, status_code=400)

        # 存储路径: upload/marketing/pic/{session_id}/
        upload_dir = os.path.join('upload', 'marketing', 'pic', session_id)
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_upload_dir = os.path.join(app_dir, upload_dir)

        os.makedirs(full_upload_dir, exist_ok=True)

        # 生成唯一文件名
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        unique_id = uuid.uuid4().hex[:8]
        filename = f"{timestamp}_{unique_id}{file_extension}"
        file_path = os.path.join(full_upload_dir, filename)

        with open(file_path, 'wb') as f:
            f.write(content)

        # 获取服务器地址，构建访问 URL
        server_host = get_config()["server"]["host"]
        url = f"{server_host.rstrip('/')}/{upload_dir.replace(os.sep, '/')}/{filename}"

        # 生成缩略图
        thumbnail_url = None
        try:
            thumb_dir = os.path.join(full_upload_dir, 'thumb')
            os.makedirs(thumb_dir, exist_ok=True)
            thumb_filename = f"thumb_{filename.rsplit('.', 1)[0]}.jpg"
            thumb_path = os.path.join(thumb_dir, thumb_filename)

            from PIL import Image
            with Image.open(file_path) as img:
                img.thumbnail((200, 200), Image.LANCZOS)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(thumb_path, "JPEG", quality=75)

            thumbnail_url = f"{server_host.rstrip('/')}/{upload_dir.replace(os.sep, '/')}/thumb/{thumb_filename}"
            logger.info(f'Agent 图片缩略图生成成功: {thumbnail_url}')
        except Exception as thumb_err:
            logger.warning(f'生成缩略图失败，使用原图: {thumb_err}')

        logger.info(f'Agent 图片上传成功: {url}')

        return JSONResponse({
            'success': True,
            'url': url,
            'thumbnail_url': thumbnail_url or url
        })

    except Exception as e:
        logger.error(f'Agent 图片上传失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': f'上传失败: {str(e)}'
        }, status_code=500)


@router.post('/upload-agent-video')
@require_permission("script_writer:upload_image")
async def upload_agent_video(
    request: Request,
    file: UploadFile = File(...),
    session_id: str = Form(...)
):
    """
    上传 Agent 对话模式的视频文件

    视频保存到 upload/marketing/video/{session_id}/ 目录，
    前端已压缩为 480p，此处仅做存储。

    Args:
        file: 视频文件
        session_id: 会话ID（用于组织存储路径）

    Returns:
        视频访问 URL
    """
    try:
        allowed_extensions = {'.mp4', '.mov', '.webm', '.avi', '.mkv'}
        file_extension = os.path.splitext(file.filename or '')[1].lower()

        if file_extension not in allowed_extensions:
            return JSONResponse({
                'success': False,
                'error': f'不支持的文件类型。允许的类型: {", ".join(allowed_extensions)}'
            }, status_code=400)

        max_size_mb = get_dynamic_config_value('upload', 'max_video_size_mb', default=50)
        max_size_bytes = max_size_mb * 1024 * 1024

        content = await file.read()
        if len(content) > max_size_bytes:
            return JSONResponse({
                'success': False,
                'error': f'视频大小不能超过 {max_size_mb}MB'
            }, status_code=400)

        upload_dir = os.path.join('upload', 'marketing', 'video', session_id)
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_upload_dir = os.path.join(app_dir, upload_dir)

        os.makedirs(full_upload_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        unique_id = uuid.uuid4().hex[:8]
        filename = f"{timestamp}_{unique_id}{file_extension}"
        file_path = os.path.join(full_upload_dir, filename)

        with open(file_path, 'wb') as f:
            f.write(content)

        # ffprobe 验证分辨率和时长
        video_info = await get_video_info(file_path)
        if video_info:
            max_duration = get_dynamic_config_value('upload', 'max_video_duration_seconds', default=15)

            if video_info['duration'] > max_duration + 1:
                os.remove(file_path)
                return JSONResponse({
                    'success': False,
                    'error': f'视频时长 {video_info["duration"]:.1f}s 超过限制 {max_duration}s'
                }, status_code=400)

            if not is_reference_video_pixel_count_valid(video_info):
                os.remove(file_path)
                width = video_info.get('width', 0)
                height = video_info.get('height', 0)
                pixel_count = width * height
                return JSONResponse({
                    'success': False,
                    'error': (
                        f'视频分辨率 {width}x{height} 总像素 {pixel_count} '
                        f'低于最低要求 {MediaConstants.VIDEO_REFERENCE_MIN_PIXEL_COUNT}'
                    )
                }, status_code=400)

            # 帧率校验：doubao-seedance r2v 要求参考视频帧率 ≤60fps，高刷屏浏览器
            # 压缩可能产出 120fps 等超频视频，此处拦截避免下游 InvalidParameter。
            fps = video_info.get('fps', 0) or 0
            max_fps = MediaConstants.VIDEO_REFERENCE_MAX_FPS
            if fps > max_fps:
                os.remove(file_path)
                return JSONResponse({
                    'success': False,
                    'error': (
                        f'视频帧率 {fps:.1f}fps 超过限制 {max_fps}fps'
                        '（建议使用 30fps 以内的视频）'
                    )
                }, status_code=400)

        # 根据 is_local 配置决定返回本地 URL 还是 CDN URL
        is_local = get_dynamic_config_value('server', 'is_local', default=False)

        if is_local:
            # 本地开发：返回本地服务器 URL
            server_host = get_config()["server"]["host"]
            url = f"{server_host.rstrip('/')}/{upload_dir.replace(os.sep, '/')}/{filename}"
        else:
            # 生产环境：上传到七牛云 CDN，返回 CDN URL
            # CDN key 包含 session_id，便于按会话清理
            try:
                storage = get_file_storage(get_config())
                storage_key = f"marketing/{session_id}/video/{filename}"
                upload_result = await storage.upload_file(storage_key, file_path)
                if upload_result.success:
                    # 签名 URL 有效期 30 天，与会话生命周期一致
                    cdn_url_expires = 30 * 24 * 3600  # 30天
                    url = storage.get_download_url(upload_result.key, expires=cdn_url_expires)
                else:
                    # CDN 上传失败，降级返回本地 URL
                    logger.warning(f'视频 CDN 上传失败({upload_result.error})，降级返回本地 URL')
                    server_host = get_config()["server"]["host"]
                    url = f"{server_host.rstrip('/')}/{upload_dir.replace(os.sep, '/')}/{filename}"
            except Exception as cdn_err:
                logger.error(f'视频 CDN 上传异常: {cdn_err}')
                server_host = get_config()["server"]["host"]
                url = f"{server_host.rstrip('/')}/{upload_dir.replace(os.sep, '/')}/{filename}"

        logger.info(f'Agent 视频上传成功: {url}')

        return JSONResponse({
            'success': True,
            'url': url
        })

    except Exception as e:
        logger.error(f'Agent 视频上传失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': f'上传失败: {str(e)}'
        }, status_code=500)


@router.post('/upload-agent-audio')
@require_permission("script_writer:upload_image")
async def upload_agent_audio(
    request: Request,
    file: UploadFile = File(...),
    session_id: str = Form(...)
):
    """
    上传 Agent 对话模式的音频文件

    音频保存到 upload/marketing/audio/{session_id}/ 目录，
    以 session_id 为子目录，方便定时清理脚本比照 chat_sessions 表删除孤立文件。

    Args:
        file: 音频文件
        session_id: 会话ID（用于组织存储路径）

    Returns:
        音频访问 URL
    """
    try:
        allowed_extensions = {'.mp3', '.wav', '.aac', '.ogg', '.m4a', '.flac'}
        file_extension = os.path.splitext(file.filename or '')[1].lower()

        if file_extension not in allowed_extensions:
            return JSONResponse({
                'success': False,
                'error': f'不支持的文件类型。允许的类型: {", ".join(allowed_extensions)}'
            }, status_code=400)

        max_size_mb = get_dynamic_config_value('upload', 'max_audio_size_mb', default=20)
        max_size_bytes = max_size_mb * 1024 * 1024

        content = await file.read()
        if len(content) > max_size_bytes:
            return JSONResponse({
                'success': False,
                'error': f'音频大小不能超过 {max_size_mb}MB'
            }, status_code=400)

        upload_dir = os.path.join('upload', 'marketing', 'audio', session_id)
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_upload_dir = os.path.join(app_dir, upload_dir)

        os.makedirs(full_upload_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        unique_id = uuid.uuid4().hex[:8]
        filename = f"{timestamp}_{unique_id}{file_extension}"
        file_path = os.path.join(full_upload_dir, filename)

        with open(file_path, 'wb') as f:
            f.write(content)

        server_host = get_config()["server"]["host"]
        url = f"{server_host.rstrip('/')}/{upload_dir.replace(os.sep, '/')}/{filename}"

        logger.info(f'Agent 音频上传成功: {url}')

        return JSONResponse({
            'success': True,
            'url': url
        })

    except Exception as e:
        logger.error(f'Agent 音频上传失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': f'上传失败: {str(e)}'
        }, status_code=500)


@router.post('/upload-character-audio')
@require_permission("script_writer:upload_image")
async def upload_character_audio(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Form(...),
    world_id: str = Form(...),
    auth_token: str = Form(...)
):
    """
    上传角色参考音频文件

    音频保存到 upload/character/voice/ 目录，
    超过 20 秒自动裁剪。

    Args:
        file: 音频文件
        user_id: 用户ID
        world_id: 世界ID
        auth_token: 认证令牌

    Returns:
        音频访问 URL
    """
    import subprocess
    from config.config_util import get_config_value, resolve_bin_path
    from config.constant import CHARACTER_VOICE_MAX_DURATION, CHARACTER_VOICE_TRIM_TIMEOUT
    from utils.project_path import get_project_root

    try:
        allowed_extensions = {'.mp3', '.wav', '.aac', '.ogg', '.m4a', '.flac', '.wma'}
        file_extension = os.path.splitext(file.filename or '')[1].lower()

        if file_extension not in allowed_extensions:
            return JSONResponse({
                'success': False,
                'error': f'不支持的文件类型。允许的类型: {", ".join(sorted(allowed_extensions))}'
            }, status_code=400)

        max_size_mb = get_dynamic_config_value('upload', 'max_audio_size_mb', default=20)
        max_size_bytes = max_size_mb * 1024 * 1024

        content = await file.read()
        if len(content) > max_size_bytes:
            return JSONResponse({
                'success': False,
                'error': f'音频大小不能超过 {max_size_mb}MB'
            }, status_code=400)

        upload_dir = os.path.join('upload', 'character', 'voice')
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_upload_dir = os.path.join(app_dir, upload_dir)

        os.makedirs(full_upload_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = uuid.uuid4().hex[:8]
        filename = f"character_voice_{timestamp}_{unique_id}{file_extension}"
        file_path = os.path.join(full_upload_dir, filename)

        with open(file_path, 'wb') as f:
            f.write(content)

        # 自动裁剪音频（超过 20 秒）
        await asyncio.to_thread(_trim_character_audio, file_path, CHARACTER_VOICE_MAX_DURATION, CHARACTER_VOICE_TRIM_TIMEOUT)

        server_host = get_config()["server"]["host"]
        url = f"{server_host.rstrip('/')}/{upload_dir.replace(os.sep, '/')}/{filename}"

        logger.info(f'角色参考音频上传成功: {url}')

        return JSONResponse({
            'success': True,
            'url': url
        })

    except Exception as e:
        logger.error(f'角色参考音频上传失败: {str(e)}')
        return JSONResponse({
            'success': False,
            'error': f'上传失败: {str(e)}'
        }, status_code=500)


def _trim_character_audio(audio_path: str, max_duration: float, timeout: int) -> None:
    """
    检查音频时长，超过 max_duration 则用 ffmpeg 裁剪。
    同步函数，调用方应通过 asyncio.to_thread 包装。
    """
    import subprocess
    from config.config_util import get_config_value, resolve_bin_path
    from utils.project_path import get_project_root

    try:
        app_dir = get_project_root()
        ffmpeg_path = resolve_bin_path(get_config_value("bin", "ffmpeg", default="ffmpeg"), app_dir)
        ffprobe_path = resolve_bin_path(get_config_value("bin", "ffprobe", default="ffprobe"), app_dir)

        duration_cmd = [
            ffprobe_path, '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            audio_path
        ]
        duration_result = subprocess.run(
            duration_cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=timeout
        )
        if duration_result.returncode != 0:
            logger.warning(f"Failed to get audio duration: {duration_result.stderr}")
            return

        duration = float(duration_result.stdout.strip())
        logger.info(f"Character voice audio duration: {duration:.2f}s")

        if duration <= max_duration:
            return

        logger.info(f"Trimming character voice audio from {duration:.2f}s to {max_duration:.2f}s")
        base_name = os.path.splitext(audio_path)[0]
        ext = os.path.splitext(audio_path)[1]
        trimmed_path = f"{base_name}_trimmed{ext}"

        trim_cmd = [
            ffmpeg_path, '-i', audio_path,
            '-t', str(max_duration),
            '-acodec', 'copy',
            '-y',
            trimmed_path
        ]
        trim_result = subprocess.run(
            trim_cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=timeout
        )
        if trim_result.returncode != 0:
            logger.error(f"ffmpeg trim error: {trim_result.stderr}")
            return

        os.remove(audio_path)
        os.rename(trimmed_path, audio_path)
        logger.info(f"Character voice audio trimmed successfully: {audio_path}")

    except subprocess.TimeoutExpired:
        logger.warning(f"Audio trim/probe timeout({timeout}s): {audio_path}")
    except Exception as e:
        logger.warning(f"Audio trim failed (non-fatal): {audio_path} - {e}")


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
            
            # 验证文件所属用户（路径前缀已校验 user_id/world_id，此处额外校验文件内容中的 user_id）
            file_user_id = str(file_data.get('user_id', ''))
            request_user_id = str(user_id)
            
            if file_user_id and file_user_id != request_user_id:
                logger.warning(f'用户 {request_user_id} 尝试删除用户 {file_user_id} 的文件: {file_path}')
                return JSONResponse({
                    'success': False,
                    'error': '无权限删除此文件：文件不属于当前用户'
                }, status_code=403)
            # file_user_id 为空时，信任路径前缀校验（兼容旧文件未写入 user_id 的情况）
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


# ==================== 技能管理 API ====================

class SkillUpdateRequest(BaseModel):
    prompt_content: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    auth_token: Optional[str] = None


@router.get('/skills')
@require_permission("skill:view")
async def list_skills(
    request: Request,
    user_id: int = QueryParam(..., description="用户ID"),
    auth_token: str = QueryParam("", description="认证token")
):
    """获取所有 skill 列表（含用户是否自定义标记）"""
    try:
        # 加载所有 skill 元数据（从文件系统）
        loader = SkillLoader()
        all_metadata = loader.get_all_skills_metadata()

        # 获取用户已自定义的 skill 名称
        from model.skill_definitions import SkillDefinitionsModel
        custom_names = SkillDefinitionsModel.get_custom_skill_names(user_id)

        skills = []
        for skill_name, metadata in sorted(all_metadata.items()):
            # 获取文件大小
            skill_file = loader.skills_dir / skill_name / 'SKILL.md'
            file_size = skill_file.stat().st_size if skill_file.exists() else 0

            skills.append({
                'skill_name': skill_name,
                'display_name': metadata.get('name') or skill_name,
                'description': metadata.get('description', ''),
                'file_size': file_size,
                'has_custom': skill_name in custom_names,
            })

        return {"success": True, "skills": skills}
    except Exception as e:
        logger.error(f"获取技能列表失败: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get('/skills/{skill_name}')
@require_permission("skill:view")
async def get_skill_detail(
    request: Request,
    skill_name: str,
    user_id: int = QueryParam(..., description="用户ID"),
    auth_token: str = QueryParam("", description="认证token")
):
    """获取单个 skill 详情（优先返回用户自定义，回退文件系统）"""
    try:
        loader = SkillLoader(user_id=user_id)
        skill_data = loader.get_skill_full_content(skill_name)
        if not skill_data:
            return JSONResponse({"success": False, "error": f"技能不存在: {skill_name}"}, status_code=404)

        # 检查是否为用户自定义
        from model.skill_definitions import SkillDefinitionsModel
        user_skill = SkillDefinitionsModel.get_user_skill(user_id, skill_name)

        return {
            "success": True,
            "skill": {
                "skill_name": skill_name,
                "display_name": skill_data.get('name') or skill_name,
                "description": skill_data.get('description', ''),
                "prompt_content": skill_data.get('prompt', ''),
                "has_custom": user_skill is not None,
            }
        }
    except Exception as e:
        logger.error(f"获取技能详情失败: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.put('/skills/{skill_name}')
@require_permission("skill:edit")
async def update_skill(
    request: Request,
    skill_name: str,
    update_req: SkillUpdateRequest,
    user_id: int = QueryParam(..., description="用户ID"),
):
    """保存用户自定义 skill prompt"""
    try:
        # 验证 skill 是否存在（文件系统中）
        loader = SkillLoader()
        if skill_name not in loader.list_skills():
            return JSONResponse({"success": False, "error": f"技能不存在: {skill_name}"}, status_code=404)

        from model.skill_definitions import SkillDefinitionsModel

        # 获取元数据作为默认值
        metadata = loader.get_skill_metadata(skill_name) or {}
        display_name = update_req.display_name or metadata.get('name') or skill_name
        description = update_req.description or metadata.get('description', '')

        # 保存到数据库
        SkillDefinitionsModel.upsert_user_skill(
            user_id=user_id,
            skill_name=skill_name,
            prompt_content=update_req.prompt_content,
            display_name=display_name,
            description=description,
        )

        # 清除内存缓存（如果有全局单例）
        try:
            from script_writer_core.mcp_tool import get_skill_loader
            get_skill_loader().invalidate_cache(skill_name)
        except Exception:
            pass

        return {"success": True, "message": "技能已保存"}
    except Exception as e:
        logger.error(f"保存技能失败: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.delete('/skills/{skill_name}')
@require_permission("skill:edit")
async def delete_skill(
    request: Request,
    skill_name: str,
    user_id: int = QueryParam(..., description="用户ID"),
    auth_token: str = QueryParam("", description="认证token")
):
    """删除用户自定义 skill，回退到默认"""
    try:
        from model.skill_definitions import SkillDefinitionsModel
        deleted = SkillDefinitionsModel.delete_user_skill(user_id, skill_name)

        if deleted:
            # 清除内存缓存
            try:
                from script_writer_core.mcp_tool import get_skill_loader
                get_skill_loader().invalidate_cache(skill_name)
            except Exception:
                pass
            return {"success": True, "message": "已恢复默认配置"}
        else:
            return {"success": True, "message": "当前已是默认配置"}
    except Exception as e:
        logger.error(f"删除技能自定义失败: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ==================== 世界导出/导入 ====================

@router.get('/export-world')
@require_permission("script:list")
async def export_world(
    request: Request,
    user_id: str = QueryParam(...),
    world_id: str = QueryParam(...)
):
    """导出世界完整数据（含图片）为 zip 包，上传到图床后返回下载链接"""
    zip_path = None
    try:
        zip_path = await asyncio.to_thread(file_manager.export_world, user_id, world_id)
        filename = os.path.basename(zip_path)
        storage = get_file_storage(get_config())
        storage_key = storage.generate_key_with_datetime(filename)
        upload_result = await storage.upload_file(storage_key, zip_path, content_type='application/zip')
        if not upload_result.success:
            return JSONResponse({'success': False, 'error': upload_result.error or '上传导出文件失败'}, status_code=500)
        download_url = storage.get_download_url(upload_result.key, attname=filename)
        return JSONResponse({
            'success': True,
            'download_url': download_url,
            'filename': filename
        })
    except FileNotFoundError as e:
        return JSONResponse({'success': False, 'error': str(e)}, status_code=404)
    except Exception as e:
        logger.error(f'导出世界失败: {str(e)}', exc_info=True)
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)
    finally:
        if zip_path and os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                logger.warning(f'清理导出临时文件失败: {zip_path}', exc_info=True)


@router.post('/import-world')
@require_permission("script:create")
async def import_world(
    request: Request,
    user_id: str = Form(...),
    world_id: str = Form(...),
    file: UploadFile = File(...)
):
    """从 zip 包导入世界数据（小文件兜底链路，已修复事件循环阻塞）"""
    tmp_path = None
    try:
        import tempfile as _tempfile
        suffix = '.zip'
        # 流式分块写临时文件，避免一次性 await file.read() 把整个 zip 读进内存
        with _tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MB / chunk
                if not chunk:
                    break
                tmp.write(chunk)

        try:
            # 解包是 CPU+磁盘密集型同步函数，必须丢线程池，否则阻塞事件循环
            result = await asyncio.to_thread(file_manager.import_world, user_id, world_id, tmp_path)
            return JSONResponse({
                'success': True,
                'message': f'导入完成: 剧本{result["scripts"]}个, 角色{result["characters"]}个, '
                           f'场景{result["locations"]}个, 道具{result["props"]}个, 图片{result["images"]}张',
                'result': result
            })
        finally:
            try:
                await asyncio.to_thread(os.unlink, tmp_path)
            except Exception:
                pass

    except Exception as e:
        logger.error(f'导入世界失败: {str(e)}')
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


# ==================== 大世界文件：前端直传七牛 + 后端限速下载导入 ====================
#
# 设计目标：上传非常大的世界 zip 时不再卡死整个服务。
#   1) 浏览器 ──> POST /api/world-upload-token        颁发绑定 key 的短期上传 token
#   2) 浏览器 ──> 七牛上传域名（前端直传，带进度）     后端完全不接触大文件
#   3) 浏览器 ──> POST /api/import-world-from-cloud   提交 key，立即返回 job_id
#   4) 后端    ：asyncio.create_task 后台限速下载 zip → to_thread 解包
#   5) 浏览器 ──> GET  /api/world-import-status       轮询 job 进度
#
# job 状态仅存内存（进程重启会丢失，前端会把 404 当作"任务丢失，请重试"）。

# 内存任务表：{ job_id: {status, progress, stage, message, result, error, started_at, updated_at} }
_world_import_jobs: Dict[str, Dict[str, Any]] = {}
_world_import_jobs_lock = asyncio.Lock()
_world_import_cleanup_started = False


async def _ensure_world_import_cleanup_task():
    """惰性启动 job 清理协程（首次有任务时起，周期淘汰 TTL 过期 job）"""
    global _world_import_cleanup_started
    if _world_import_cleanup_started:
        return
    async with _world_import_jobs_lock:
        if not _world_import_cleanup_started:
            asyncio.create_task(_world_import_jobs_cleanup_loop())
            _world_import_cleanup_started = True


async def _world_import_jobs_cleanup_loop():
    """周期清理超过 WORLD_IMPORT_JOB_TTL 的 job，防止内存无限增长"""
    from config.constant import WORLD_IMPORT_JOB_TTL, WORLD_IMPORT_JOB_CLEANUP_INTERVAL
    while True:
        try:
            await asyncio.sleep(WORLD_IMPORT_JOB_CLEANUP_INTERVAL)
            now = time.time()
            expired = []
            async with _world_import_jobs_lock:
                for jid, job in list(_world_import_jobs.items()):
                    if now - job.get('updated_at', job.get('started_at', now)) > WORLD_IMPORT_JOB_TTL:
                        expired.append(jid)
                for jid in expired:
                    _world_import_jobs.pop(jid, None)
            if expired:
                logger.info(f'[world_import] 清理过期 job: {len(expired)} 个')
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception('[world_import] cleanup loop error')


async def _set_world_import_job(job_id: str, **fields):
    """更新 job 字段（线程安全）"""
    async with _world_import_jobs_lock:
        job = _world_import_jobs.get(job_id)
        if job is None:
            return
        job.update(fields)
        job['updated_at'] = time.time()


async def _count_active_world_import_jobs() -> int:
    """统计处于 pending/downloading/unpacking 状态的 job 数"""
    async with _world_import_jobs_lock:
        return sum(
            1 for j in _world_import_jobs.values()
            if j.get('status') in ('pending', 'downloading', 'unpacking')
        )


async def _download_world_zip_with_rate_limit(
    download_url: str,
    job_id: str,
    total_size_hint: Optional[int] = None
) -> str:
    """
    流式下载世界 zip 到临时文件，并按 WORLD_IMPORT_DOWNLOAD_RATE_BPS 限速。

    - httpx.AsyncClient 流式下载，逐 chunk 写盘，避免内存峰值。
    - 每个 chunk 后 await asyncio.sleep() 控速，避免打满出口带宽。
    - 整体用 asyncio.wait_for(timeout) 保护，遵守超时红线。
    - try/finally 清理临时文件。
    """
    import tempfile as _tempfile
    from config.constant import (
        WORLD_IMPORT_DOWNLOAD_RATE_BPS,
        WORLD_IMPORT_DOWNLOAD_CHUNK_BYTES,
        WORLD_IMPORT_DOWNLOAD_TIMEOUT,
        WORLD_IMPORT_PROGRESS_STEP,
        UploadPathConstants,
    )
    import httpx

    # 确保 temp 目录存在
    tmp_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), UploadPathConstants.TEMP_DIR)
    os.makedirs(tmp_root, exist_ok=True)

    tmp_path: Optional[str] = None

    async def _do_download():
        nonlocal tmp_path
        with _tempfile.NamedTemporaryFile(delete=False, suffix='.zip', dir=tmp_root) as tmp:
            tmp_path = tmp.name
            received = 0
            last_reported_step = 0
            rate_bps = WORLD_IMPORT_DOWNLOAD_RATE_BPS
            chunk_bytes = WORLD_IMPORT_DOWNLOAD_CHUNK_BYTES
            async with httpx.AsyncClient(timeout=httpx.Timeout(WORLD_IMPORT_DOWNLOAD_TIMEOUT, connect=30.0)) as client:
                async with client.stream('GET', download_url) as response:
                    response.raise_for_status()
                    if total_size_hint is None:
                        # 尝试从 Content-Length 推断
                        cl = response.headers.get('content-length')
                        if cl:
                            try:
                                total_size_hint_inner = int(cl)
                            except ValueError:
                                total_size_hint_inner = 0
                        else:
                            total_size_hint_inner = 0
                    else:
                        total_size_hint_inner = total_size_hint

                    async for chunk in response.aiter_bytes(chunk_size=chunk_bytes):
                        tmp.write(chunk)
                        received += len(chunk)
                        # 限速：按本 chunk 字节数计算应睡眠时间，平滑出口速率
                        if rate_bps and rate_bps > 0:
                            await asyncio.sleep(len(chunk) / rate_bps)
                        # 进度上报（按 5% 粒度，避免高频写字典）
                        if total_size_hint_inner > 0:
                            pct = int(received * 100 / total_size_hint_inner)
                            if pct >= last_reported_step + WORLD_IMPORT_PROGRESS_STEP:
                                last_reported_step = pct
                                await _set_world_import_job(
                                    job_id,
                                    status='downloading',
                                    stage='downloading',
                                    progress=min(pct, 99),
                                    received_bytes=received,
                                    total_bytes=total_size_hint_inner,
                                )
            # 下载完成
            await _set_world_import_job(
                job_id,
                stage='downloading',
                progress=99,
                received_bytes=received,
            )
            return tmp_path

    try:
        # 超时红线：所有流式操作必须受 wait_for 保护
        return await asyncio.wait_for(_do_download(), timeout=WORLD_IMPORT_DOWNLOAD_TIMEOUT)
    except Exception:
        # 失败时清理半成品临时文件
        if tmp_path:
            try:
                await asyncio.to_thread(os.unlink, tmp_path)
            except Exception:
                pass
        raise


async def _run_world_import_job(job_id: str, download_url: str, user_id: str, world_id: str):
    """后台协程：限速下载 zip → 线程池解包 → 更新 job 状态"""
    tmp_path: Optional[str] = None
    try:
        await _set_world_import_job(job_id, status='downloading', stage='downloading', progress=0)
        tmp_path = await _download_world_zip_with_rate_limit(download_url, job_id)

        await _set_world_import_job(job_id, status='unpacking', stage='unpacking', progress=99)
        # 解包是同步 CPU/磁盘密集型，丢线程池避免阻塞事件循环
        result = await asyncio.to_thread(file_manager.import_world, user_id, world_id, tmp_path)

        await _set_world_import_job(
            job_id,
            status='done',
            stage='done',
            progress=100,
            result=result,
            message=f'导入完成: 剧本{result["scripts"]}个, 角色{result["characters"]}个, '
                    f'场景{result["locations"]}个, 道具{result["props"]}个, 图片{result["images"]}张',
        )
    except asyncio.TimeoutError:
        logger.error(f'[world_import] job {job_id} 下载超时')
        await _set_world_import_job(job_id, status='failed', stage='failed', error='下载超时')
    except Exception as e:
        logger.error(f'[world_import] job {job_id} 失败: {e}', exc_info=True)
        await _set_world_import_job(job_id, status='failed', stage='failed', error=str(e))
    finally:
        if tmp_path:
            try:
                await asyncio.to_thread(os.unlink, tmp_path)
            except Exception:
                pass


@router.post('/world-upload-token')
@require_permission("script:create")
async def world_upload_token(
    request: Request,
    world_id: str = Form(...),
    filename: str = Form(...),
    size: Optional[int] = Form(None),
):
    """
    颁发前端直传七牛的上传 token。

    前端拿到 {upload_url, token, key} 后，用 XHR 直接 POST 到七牛上传域名，
    不再经后端转发大文件，彻底释放后端带宽与事件循环。
    """
    from config.constant import (
        QINIU_UPLOAD_REGION_URL,
        QINIU_DIRECT_UPLOAD_TOKEN_EXPIRES,
        WORLD_IMPORT_KEY_PREFIX,
    )
    try:
        storage = get_file_storage(get_config())
        if not hasattr(storage, 'get_upload_token'):
            return JSONResponse(
                {'success': False, 'error': '当前存储后端不支持前端直传'},
                status_code=500,
            )

        # 生成绑定 key：world_import/<datetime>/<unique>.zip
        base_key = storage.generate_key_with_datetime(filename)
        key = f"{WORLD_IMPORT_KEY_PREFIX}/{base_key}"
        token = storage.get_upload_token(
            key=key,
            expires=QINIU_DIRECT_UPLOAD_TOKEN_EXPIRES,
            policy={'fileType': 0},  # 0=标准存储
        )
        return JSONResponse({
            'success': True,
            'upload_url': QINIU_UPLOAD_REGION_URL,
            'token': token,
            'key': key,
            'expires': QINIU_DIRECT_UPLOAD_TOKEN_EXPIRES,
        })
    except Exception as e:
        logger.error(f'颁发世界上传 token 失败: {e}', exc_info=True)
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@router.post('/import-world-from-cloud')
@require_permission("script:create")
async def import_world_from_cloud(
    request: Request,
    user_id: str = Form(...),
    world_id: str = Form(...),
    key: str = Form(...),
):
    """
    基于七牛云 key 触发大世界导入（异步后台任务）。

    立即返回 job_id，前端轮询 /api/world-import-status 获取进度。
    """
    from config.constant import WORLD_IMPORT_JOB_MAX_CONCURRENT
    try:
        # 并发上限保护
        active = await _count_active_world_import_jobs()
        if active >= WORLD_IMPORT_JOB_MAX_CONCURRENT:
            return JSONResponse(
                {'success': False, 'error': f'当前已有 {active} 个导入任务在进行，请稍后再试'},
                status_code=429,
            )

        storage = get_file_storage(get_config())
        # 生成临时私有下载 URL（短期过期，不泄露）
        download_url = storage.get_download_url(key)

        job_id = str(uuid.uuid4())
        now = time.time()
        async with _world_import_jobs_lock:
            _world_import_jobs[job_id] = {
                'status': 'pending',
                'stage': 'pending',
                'progress': 0,
                'message': '任务已创建',
                'result': None,
                'error': None,
                'started_at': now,
                'updated_at': now,
                'user_id': user_id,
                'world_id': world_id,
            }

        await _ensure_world_import_cleanup_task()
        # 后台执行，不阻塞响应
        asyncio.create_task(_run_world_import_job(job_id, download_url, user_id, world_id))

        return JSONResponse({'success': True, 'job_id': job_id})
    except Exception as e:
        logger.error(f'创建云端世界导入任务失败: {e}', exc_info=True)
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


@router.get('/world-import-status')
@require_permission("script:create")
async def world_import_status(
    request: Request,
    job_id: str = QueryParam(...),
):
    """查询世界导入任务进度（前端轮询）"""
    async with _world_import_jobs_lock:
        job = _world_import_jobs.get(job_id)
        if not job:
            return JSONResponse(
                {'success': False, 'error': '任务不存在或已过期（可能进程已重启），请重试'},
                status_code=404,
            )
        # 返回快照，不暴露内部字段
        return JSONResponse({
            'success': True,
            'job_id': job_id,
            'status': job.get('status'),
            'stage': job.get('stage'),
            'progress': job.get('progress', 0),
            'message': job.get('message'),
            'result': job.get('result'),
            'error': job.get('error'),
        })
