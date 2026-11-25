"""scheduler 中的用户模块任务提交与轮询入口。"""

import logging

from services.user_module_service import get_user_module_service

logger = logging.getLogger(__name__)


async def process_user_module_jobs() -> None:
    try:
        await get_user_module_service().process_pending_jobs()
    except Exception:
        logger.exception("处理用户模块任务失败")
