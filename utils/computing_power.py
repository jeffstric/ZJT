"""
算力计算工具函数
支持基于实现方的算力计算（从数据库读取，支持热更新）
"""
from typing import Optional, Union, Dict, Any
import logging
from config.unified_config import UnifiedConfigRegistry, UnifiedTaskConfig

logger = logging.getLogger(__name__)


def get_computing_power_for_task(
    task_type: int,
    duration: Optional[int] = None,
    user_id: Optional[int] = None,
    implementation: Optional[str] = None
) -> int:
    """
    获取任务的算力消耗（支持实现方级别的算力配置）

    Args:
        task_type: 任务类型ID
        duration: 时长（秒），用于按时长计费的任务
        user_id: 用户ID（可选），用于获取用户偏好的实现方
        implementation: 直接指定实现方（可选），优先级高于用户偏好

    Returns:
        算力消耗值，如果无法获取则返回 0
    """
    # 1. 获取任务配置
    config = UnifiedConfigRegistry.get_by_id(task_type)
    if not config:
        logger.warning(f"No config found for task type: {task_type}")
        return 0

    # 2. 确定实现方
    impl_name = implementation
    if not impl_name and user_id:
        # 尝试获取用户偏好的实现方
        try:
            from model.users import UsersModel
            user_pref = UsersModel.get_implementation_preference(user_id, config.key)
            if user_pref:
                available_impls = config.implementations if config.implementations else [config.implementation]
                if user_pref in available_impls:
                    impl_name = user_pref
        except Exception as e:
            logger.debug(f"Failed to get user preference: {e}")

    if not impl_name:
        impl_name = config.implementation

    # 3. 获取算力（优先任务配置的 computing_power 覆盖值，其次实现方配置）
    if impl_name:
        power = config.get_computing_power(duration, implementation=impl_name)
        if power:
            return power

    # 4. 回退到任务配置的算力（向后兼容，无实现方时）
    return config.get_computing_power(duration, implementation=None)


def get_computing_power_config_for_task(
    task_type: int,
    user_id: Optional[int] = None,
    implementation: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取任务的算力配置信息（包含来源信息）

    Args:
        task_type: 任务类型ID
        user_id: 用户ID（可选）
        implementation: 直接指定实现方（可选）

    Returns:
        {
            'computing_power': int | Dict[int, int],
            'source': 'database' | 'code_default',
            'implementation': str,
            'is_user_preference': bool
        }
    """
    config = UnifiedConfigRegistry.get_by_id(task_type)
    if not config:
        return {
            'computing_power': 0,
            'source': 'none',
            'implementation': None,
            'is_user_preference': False
        }

    # 确定实现方
    impl_name = implementation
    is_user_pref = False

    if not impl_name and user_id:
        try:
            from model.users import UsersModel
            user_pref = UsersModel.get_implementation_preference(user_id, config.key)
            if user_pref:
                available_impls = config.implementations if config.implementations else [config.implementation]
                if user_pref in available_impls:
                    impl_name = user_pref
                    is_user_pref = True
        except Exception:
            pass

    if not impl_name:
        impl_name = config.implementation

    # 获取算力配置
    if impl_name:
        impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
        if impl_config:
            # 检查是否有数据库配置
            try:
                from model.implementation_power import ImplementationPowerModel
                db_powers = ImplementationPowerModel.get_all_powers_for_implementation(impl_name, config.driver_name)
                if db_powers:
                    return {
                        'computing_power': db_powers if len(db_powers) > 1 or None in db_powers else list(db_powers.values())[0],
                        'source': 'database',
                        'implementation': impl_name,
                        'is_user_preference': is_user_pref
                    }
            except Exception:
                pass

            return {
                'computing_power': impl_config.default_computing_power,
                'source': 'code_default',
                'implementation': impl_name,
                'is_user_preference': is_user_pref
            }

    # 回退到任务配置
    return {
        'computing_power': config.computing_power,
        'source': 'task_config',
        'implementation': impl_name,
        'is_user_preference': False
    }


def get_implementation_for_user(
    task_type: int,
    user_id: Optional[int] = None
) -> Optional[str]:
    """
    获取任务应该使用的实现方（考虑用户偏好）

    Args:
        task_type: 任务类型ID
        user_id: 用户ID（可选）

    Returns:
        实现方名称
    """
    config = UnifiedConfigRegistry.get_by_id(task_type)
    if not config:
        return None

    impl_name = None

    # 检查用户偏好
    if user_id:
        try:
            from model.users import UsersModel
            user_pref = UsersModel.get_implementation_preference(user_id, config.key)
            if user_pref:
                available_impls = config.implementations if config.implementations else [config.implementation]
                if user_pref in available_impls:
                    impl_name = user_pref
        except Exception:
            pass

    # 使用默认实现方
    if not impl_name:
        impl_name = config.implementation

    return impl_name
