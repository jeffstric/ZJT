"""
算力计算工具函数
支持基于实现方的算力计算（从数据库读取，支持热更新）

【函数族选择指南】
  get_computing_power_for_task(task_type,...)       → 返回 int，实际扣费用的算力值
  get_computing_power_config_for_task(task_type,...) → 返回 dict，包含配置详情（source/implementation/is_user_preference）
"""
from typing import Optional, Union, Dict, Any
import logging
import json
from config.unified_config import UnifiedConfigRegistry, UnifiedTaskConfig, get_implementation_name
from config.constant import IMAGE_MODE_EXTRA_CONFIG_KEY, VIDEO_RESOLUTION_EXTRA_CONFIG_KEY, TASK_COMPUTING_POWER

logger = logging.getLogger(__name__)


def build_context_from_task_record(task_record) -> Dict[str, Any]:
    """
    从 ai_tools 任务记录构建算力计算所需的 context

    Args:
        task_record: ai_tools 表中的记录对象（有 extra_config、image_size、image_path 等字段）

    Returns:
        context 字典，格式如 {'image_mode': 'first_last_with_tail', 'resolution': '2K'}
    """
    context = {}

    try:
        # 1. image_mode / video_resolution：从 extra_config JSON 解析
        if task_record and hasattr(task_record, 'extra_config') and task_record.extra_config:
            try:
                extra = task_record.extra_config if isinstance(task_record.extra_config, dict) else json.loads(task_record.extra_config)
                if IMAGE_MODE_EXTRA_CONFIG_KEY in extra:
                    # 判断是否有尾帧：first_last_frame 模式下 image_path 有2张图
                    image_mode = extra[IMAGE_MODE_EXTRA_CONFIG_KEY]
                    if image_mode == 'first_last_frame' and hasattr(task_record, 'image_path') and task_record.image_path:
                        # 仅检查是否有逗号（有尾帧），避免不必要的 split
                        if ',' in task_record.image_path:
                            context['image_mode'] = 'first_last_with_tail'
                        else:
                            context['image_mode'] = image_mode
                    else:
                        context['image_mode'] = image_mode
                if VIDEO_RESOLUTION_EXTRA_CONFIG_KEY in extra:
                    context['resolution'] = extra[VIDEO_RESOLUTION_EXTRA_CONFIG_KEY]
            except (json.JSONDecodeError, TypeError):
                pass

        # 2. 图片任务 resolution：从 image_size 字段回退
        if 'resolution' not in context and task_record and hasattr(task_record, 'image_size') and task_record.image_size:
            context['resolution'] = task_record.image_size

    except Exception as e:
        logger.error(f"Failed to build context from task record: {e}")

    return context


def get_computing_power_for_task(
    task_type: int,
    duration: Optional[int] = None,
    user_id: Optional[int] = None,
    implementation: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
) -> int:
    """
    获取任务的算力消耗（支持实现方级别的算力配置和修饰符）

    Args:
        task_type: 任务类型ID
        duration: 时长（秒），用于按时长计费的任务
        user_id: 用户ID（可选），用于获取用户偏好的实现方
        implementation: 直接指定实现方（可选），优先级高于用户偏好
        context: 额外上下文参数，用于修饰符计算（如 {'image_mode': 'first_last_with_tail'}）

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
        power = config.get_computing_power(duration, implementation=impl_name, context=context)
        if power:
            return power

    # 4. 回退到任务配置的算力（向后兼容，无实现方时）
    return config.get_computing_power(duration, implementation=None, context=context)


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


# ==================== 失败退费（扣返一致性保障） ====================
# 背景：Grok 多供应商切换事故（2026-08-19）——任务按 A 供应商扣费后，重试切换
# 到 B 供应商时 ai_tools.implementation 被改写，最终退费按 B 的价格重算，
# 出现「扣16分退80分」。退费金额必须以实际扣减流水为准，而非重算。

REFUND_TXN_PREFIX = 'refund-'


def build_refund_transaction_id(ai_tool) -> Optional[str]:
    """构造幂等退费流水号：refund-{原扣费流水号}

    任务创建时扣费流水号与 ai_tools.transaction_id 1:1 绑定，
    以此派生退费流水号可天然防止同一任务重复退费。

    Returns:
        幂等流水号；任务无扣费流水号时返回 None（调用方回退随机 uuid）
    """
    transaction_id = getattr(ai_tool, 'transaction_id', None)
    if not transaction_id:
        return None
    return f"{REFUND_TXN_PREFIX}{transaction_id}"


def is_already_refunded(ai_tool) -> bool:
    """检查任务是否已退过费（幂等防重复退费）

    依赖 perseids 服务将退费流水写入同一 computing_power_log 表；
    check-then-post 存在极小竞态窗口，仅作防御性加固。
    """
    refund_txn = build_refund_transaction_id(ai_tool)
    if not refund_txn:
        return False
    try:
        from model.computing_power_log import ComputingPowerLogModel
        return ComputingPowerLogModel.check_transaction_exists(refund_txn)
    except Exception as e:
        logger.warning(f"Failed to check refund idempotency for {refund_txn}: {e}")
        return False


def _recalculate_task_power(ai_tool, ai_tool_type: int, user_id: int) -> Optional[int]:
    """按当前配置重算任务算力（退费回退路径，考虑实现方修饰符、分辨率等上下文）"""
    context = build_context_from_task_record(ai_tool)
    # 优先使用任务记录中的实现方，回退到用户当前偏好
    impl_id = getattr(ai_tool, 'implementation', None)
    impl_name = get_implementation_name(impl_id) if impl_id else None
    implementation = impl_name if impl_name and impl_name != 'unknown' else get_implementation_for_user(ai_tool_type, user_id)

    return get_computing_power_for_task(
        task_type=ai_tool_type,
        duration=getattr(ai_tool, 'duration', None) or 5,
        user_id=user_id,
        implementation=implementation,
        context=context
    )


def _static_task_power(ai_tool, ai_tool_type: int) -> Optional[int]:
    """静态 TASK_COMPUTING_POWER 兜底（不含修饰符，可能金额不准，仅最后回退）"""
    computing_power_config = TASK_COMPUTING_POWER.get(ai_tool_type)
    if isinstance(computing_power_config, dict):
        duration = getattr(ai_tool, 'duration', None) or 5
        computing_power = computing_power_config.get(duration)
        if not computing_power:
            computing_power = list(computing_power_config.values())[0]
        return computing_power
    return computing_power_config


def resolve_refund_amount(ai_tool, task_type: Optional[int] = None) -> Optional[int]:
    """解析失败任务的退费金额（扣返一致性保障）

    ⚠️ 回退顺序（修改时必须保持）：
      1. 按 ai_tools.transaction_id 关联 computing_power_log 扣费流水，
         取实际扣减金额原额退还——精确，免疫供应商切换、价格热更新
      2. get_computing_power_for_task 按当前配置重算——流水缺失时的兼容
         回退（供应商切换场景下可能金额不准，仅兜底）
      3. TASK_COMPUTING_POWER 静态配置——最旧数据兜底

    Args:
        ai_tool: AITool 对象（含 transaction_id / implementation / duration / extra_config）
        task_type: 任务类型ID（缺省时取 ai_tool.type）

    Returns:
        退费金额；无法解析返回 None
    """
    ai_tool_type = task_type if task_type is not None else getattr(ai_tool, 'type', None)
    user_id = getattr(ai_tool, 'user_id', None)
    if ai_tool_type is None or not user_id:
        return None

    # 1. 实际扣减流水（原额退还）
    transaction_id = getattr(ai_tool, 'transaction_id', None)
    if transaction_id:
        try:
            from model.computing_power_log import ComputingPowerLogModel
            deducted = ComputingPowerLogModel.get_deducted_power_by_transaction(user_id, transaction_id)
            if deducted:
                return deducted
            logger.warning(
                f"No deduct log found for transaction {transaction_id} "
                f"(user {user_id}), falling back to recalculation"
            )
        except Exception as e:
            logger.warning(f"Failed to lookup deducted power by transaction {transaction_id}: {e}")

    # 2. 按当前配置重算（考虑修饰符）
    try:
        computing_power = _recalculate_task_power(ai_tool, ai_tool_type, user_id)
        if computing_power:
            return computing_power
    except Exception as e:
        logger.warning(f"Modifier-aware refund recalculation failed, falling back: {e}")

    # 3. 静态配置兜底
    return _static_task_power(ai_tool, ai_tool_type)
