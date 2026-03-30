"""
系统状态 API 路由
"""
from fastapi import APIRouter, Header
import logging

from model.users import UsersModel
from model.user_tokens import UserTokensModel
from config.unified_config import UnifiedConfigRegistry
from config.config_util import get_config_value
from config.version import get_app_version

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
async def get_system_status():
    """
    获取系统状态
    返回系统是否已初始化（是否有用户）
    """
    try:
        total_users = UsersModel.get_total_count()
        
        return {
            "code": 0,
            "data": {
                "initialized": total_users > 0,
                "total_users": total_users
            }
        }
    except Exception as e:
        logger.error(f"Failed to get system status: {e}")
        return {
            "code": 1,
            "message": str(e)
        }


@router.get("/task-configs")
async def get_task_configs(authorization: str = Header(None)):
    """
    获取所有任务类型配置

    返回前端需要的完整配置信息，包括：
    - 任务列表（支持的比例、尺寸、时长等）
    - 分类信息
    - 供应商信息

    前端可以根据此接口动态渲染模型选择器、参数配置等组件

    支持可选的 Authorization 头。如果传入有效token，
    返回的 computing_power 将根据用户实现方偏好返回对应实现方的算力。
    """
    try:
        user_id = None
        user_prefs = {}

        # 如果传入了 Authorization 头，获取用户ID和偏好
        if authorization:
            if authorization.startswith("Bearer "):
                authorization = authorization[7:]
            user_id = UserTokensModel.get_user_id_by_token(authorization)
            if user_id:
                user_prefs = UsersModel.get_all_preferences(user_id)

        frontend_config = UnifiedConfigRegistry.get_frontend_config(user_id, user_prefs)
        return {
            "code": 0,
            "data": frontend_config
        }
    except Exception as e:
        logger.error(f"Failed to get task configs: {e}")
        return {
            "code": 1,
            "message": str(e)
        }


@router.get("/server-config")
async def get_server_config():
    """
    获取服务器公开配置

    返回前端需要的公开配置信息，如 is_local、备案号等
    """
    try:
        is_local = get_config_value('server', 'is_local', default=False)
        footer = get_config_value('server', 'footer', default={})
        version = get_app_version()

        return {
            "code": 0,
            "data": {
                "is_local": is_local,
                "version": version,
                "footer": {
                    "copyright": footer.get('copyright', ''),
                    "icp_number": footer.get('icp_number', ''),
                    "icp_url": footer.get('icp_url', 'https://beian.miit.gov.cn/'),
                    "police_number": footer.get('police_number', ''),
                    "police_url": footer.get('police_url', '')
                }
            }
        }
    except Exception as e:
        logger.error(f"Failed to get server config: {e}")
        return {
            "code": 1,
            "message": str(e)
        }

