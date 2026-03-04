"""
系统状态 API 路由
"""
from fastapi import APIRouter
import logging

from model.users import UsersModel

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
