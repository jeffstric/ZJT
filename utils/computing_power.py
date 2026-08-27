"""
算力计算工具函数
支持基于实现方的算力计算（从数据库读取，支持热更新）

【函数族选择指南】
  get_computing_power_for_task(task_type,...)       → 返回 int，实际扣费用的算力值
  get_computing_power_config_for_task(task_type,...) → 返回 dict，包含配置详情（source/implementation/is_user_preference）
"""
from typing import Optional, Union, Dict, Any, List
import logging
import json
import math
from config.unified_config import UnifiedConfigRegistry, UnifiedTaskConfig, get_implementation_name
from config.constant import (
    IMAGE_MODE_EXTRA_CONFIG_KEY,
    VIDEO_RESOLUTION_EXTRA_CONFIG_KEY,
    TASK_COMPUTING_POWER,
    VIDEO_EDIT_BILLING_TASK_TYPES,
    DIFF_REFUND_TXN_PREFIX,
    DIFF_CHARGE_TXN_PREFIX,
)

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


# ==================== 视频编辑任务计费时长（Seedance 2.5 omni_reference_task_type=edit）====================
# 视频编辑任务的输出时长由参考视频决定（驱动下发 duration=-1、ratio=adaptive、
# omni_reference_task_type=edit），计费时长须按参考视频总时长吸附档位。
# ⚠️ 判定唯一入口 is_video_edit_billing_task：驱动层（下发 edit）与计价层（计费时长）
# 共用，调用方不得自写条件；新增任务类型改 config/constant.VIDEO_EDIT_BILLING_TASK_TYPES。

# 计费时长来源标识：写入 extra_config.billing_duration_source 供审计追溯
BILLING_DURATION_SOURCE_REFERENCE_VIDEO = "reference_video"
BILLING_DURATION_SOURCE_USER_INPUT = "user_input"


def is_video_edit_billing_task(task_type, video_path) -> bool:
    """
    判断任务是否为「按参考视频总时长计费」的视频编辑任务（唯一判定入口）。

    驱动层据此下发 omni_reference_task_type=edit / ratio=adaptive / duration=-1，
    计价层据此把计费时长从用户输入切换为参考视频总时长，两处判定必须同源，
    否则会出现「API 按 edit 下发、算力按用户时长扣」的错位。

    Args:
        task_type: 任务类型 ID（TaskTypeId）
        video_path: 参考视频路径/URL（逗号分隔多个），与 ai_tools.video_path 同格式
    """
    if not video_path or not str(video_path).strip():
        return False
    return task_type in VIDEO_EDIT_BILLING_TASK_TYPES


def resolve_video_edit_billing_duration(
    task_type,
    video_path,
    user_duration: Optional[int],
) -> tuple[int, str]:
    """
    解析视频编辑任务的计费时长（计价唯一入口）。

    命中视频编辑任务时探测参考视频总时长，向上取整到整数秒并 clamp 到任务
    supported_durations 区间（档位表按整数秒建键，get_computing_power 匹配不到
    档位会错取首档，必须吸附；不足 1 秒的零头按 1 秒计，保证平台不亏）；
    未命中或探测失败时回退用户输入时长。

    同步函数（外部 URL 下载 + ffprobe 子进程），异步上下文须 asyncio.to_thread 包装。
    扣费与 ai_tools.duration 落库必须使用同一返回值，保证退费兜底重算同源。

    Args:
        task_type: 任务类型 ID（TaskTypeId）
        video_path: 参考视频路径/URL（逗号分隔多个）
        user_duration: 用户输入时长（秒），回退值

    Returns:
        (计费时长秒数, 来源标识)；来源 ∈ {BILLING_DURATION_SOURCE_REFERENCE_VIDEO,
        BILLING_DURATION_SOURCE_USER_INPUT}
    """
    fallback = int(user_duration) if user_duration else 5
    if not is_video_edit_billing_task(task_type, video_path):
        return fallback, BILLING_DURATION_SOURCE_USER_INPUT

    from utils.video_compressor import get_reference_videos_total_duration_sync

    total = get_reference_videos_total_duration_sync(video_path)
    if total is None:
        logger.warning(
            f"task_type={task_type} 参考视频时长探测失败，计费回退用户输入时长 {fallback}s"
        )
        return fallback, BILLING_DURATION_SOURCE_USER_INPUT

    # 向上取整（不足 1 秒的零头按 1 秒计）；减 1µs 容器时钟容差，避免恰好整数秒的
    # 视频因浮点噪声被多计 1 秒（如 10.000000 → 仍计 10）
    billing = math.ceil(total - 1e-6)
    config = UnifiedConfigRegistry.get_by_id(task_type)
    if config and config.supported_durations:
        durations = sorted(config.supported_durations)
        billing = min(max(billing, durations[0]), durations[-1])

    logger.info(
        f"视频编辑计费时长: 参考视频总时长 {total:.1f}s → 计费 {billing}s（向上取整） "
        f"(用户输入 {fallback}s, task_type={task_type})"
    )
    return billing, BILLING_DURATION_SOURCE_REFERENCE_VIDEO


# ==================== 失败退费（扣返一致性保障） ====================
# 背景：Grok 多供应商切换事故（2026-08-19）——任务按 A 供应商扣费后，重试切换
# 到 B 供应商时 ai_tools.implementation 被改写，最终退费按 B 的价格重算，
# 出现「扣16分退80分」。退费金额必须以实际扣减流水为准，而非重算。

REFUND_TXN_PREFIX = 'refund-'


def collect_refund_txn_ids_for_deduct_logs(logs: Optional[List[Dict[str, Any]]]) -> List[str]:
    """从扣减日志收集待查询的失败退回流水号 refund-{原扣费流水号}。"""
    collected = []
    seen = set()
    for log in logs or []:
        if log.get('behavior') != 'deduct':
            continue
        tid = log.get('transaction_id')
        if not tid:
            continue
        tid = str(tid)
        if (
            tid.startswith(REFUND_TXN_PREFIX)
            or tid.startswith(DIFF_REFUND_TXN_PREFIX)
            or tid.startswith(DIFF_CHARGE_TXN_PREFIX)
        ):
            continue
        refund_tid = f"{REFUND_TXN_PREFIX}{tid}"
        if refund_tid in seen:
            continue
        seen.add(refund_tid)
        collected.append(refund_tid)
    return collected


def attach_refund_to_deduct_logs(
    logs: Optional[List[Dict[str, Any]]],
    refund_map: Optional[Dict[str, Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """给扣减日志挂上对应失败退回流水（refund_map key 为完整 refund- 流水号）。"""
    logs = logs or []
    if not refund_map:
        return logs
    for log in logs:
        if log.get('behavior') != 'deduct':
            continue
        tid = log.get('transaction_id')
        if not tid:
            continue
        tid = str(tid)
        if tid.startswith(REFUND_TXN_PREFIX):
            continue
        refund = refund_map.get(f"{REFUND_TXN_PREFIX}{tid}")
        if not refund:
            continue
        log['refund'] = {
            'transaction_id': refund.get('transaction_id'),
            'computing_power': refund.get('computing_power'),
        }
    return logs


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


# ==================== 供应商切换差价结算（"贵扣便宜用"修复） ====================
# 背景：任务按供应商A价格扣费（如 site1 10秒=55分），失败切换到供应商B后成功
# （如慧梦 10秒=14分），旧机制不退差价导致用户多付。方案：任务成功时按实际
# 完成供应商的价格双向结算——多扣退差、少扣补收（补收 best-effort 不追债）。

def settle_task_success_diff(ai_tool, task_type: Optional[int] = None) -> Optional[int]:
    """任务成功后按实际完成供应商双向结算差价

    ⚠️ 结算前提（任一不满足则静默跳过，不抛异常、不阻断成功状态更新）：
      1. 动态开关 billing.settle_diff_enabled 开启（默认开，可随时关闭）
      2. 任务发生过供应商切换（implementation_attempts 存在 attempt>=2）
      3. 实扣金额可查（ai_tools.transaction_id 对应扣费流水，与创建扣费同源）

    幂等：diff-refund-{原扣费流水号} / diff-charge-{原扣费流水号}，任一已存在即跳过。
    补收 best-effort：余额不足或 perseids 扣费失败仅记日志（本次让利），不重试不追债。

    ⚠️ 调用时 ai_tools.implementation 必须已是最终完成供应商（切换驱动在提交前
    已改写；无切换任务该字段即首供应商，会被前提2过滤）。

    Args:
        ai_tool: AITool 完整记录（含 transaction_id / implementation / duration / extra_config）
        task_type: 任务类型ID（缺省时取 ai_tool.type）

    Returns:
        结算金额：正数=退差（用户多收），负数=补收（用户多付）；未结算返回 None
    """
    ai_tool_type = task_type if task_type is not None else getattr(ai_tool, 'type', None)
    user_id = getattr(ai_tool, 'user_id', None)
    task_id = getattr(ai_tool, 'id', None)
    transaction_id = getattr(ai_tool, 'transaction_id', None)
    if ai_tool_type is None or not user_id or not transaction_id:
        return None

    try:
        # 0. 灰度开关（默认开）
        from config.config_util import get_dynamic_config_value
        if not get_dynamic_config_value('billing', 'settle_diff_enabled', default=True):
            return None

        # 1. 仅结算发生过供应商切换的任务（无切换：扣费价=完成供应商价，无差价）
        from model.implementation_attempts import ImplementationAttemptModel
        if ImplementationAttemptModel.get_retry_implementation_count(task_id) < 1:
            return None

        from model.computing_power_log import ComputingPowerLogModel

        # 2. 幂等：任一方向已结算过即跳过
        refund_txn = f"{DIFF_REFUND_TXN_PREFIX}{transaction_id}"
        charge_txn = f"{DIFF_CHARGE_TXN_PREFIX}{transaction_id}"
        if ComputingPowerLogModel.check_transaction_exists(refund_txn) \
                or ComputingPowerLogModel.check_transaction_exists(charge_txn):
            return None

        # 3. 实扣金额（创建扣费流水原额）
        deducted = ComputingPowerLogModel.get_deducted_power_by_transaction(user_id, transaction_id)
        if not deducted:
            logger.warning(f"[SettleDiff] task {task_id} no deduct log for {transaction_id}, skip")
            return None

        # 4. 实际完成供应商价格（最终 implementation + duration + context 修饰符）
        actual = _recalculate_task_power(ai_tool, ai_tool_type, user_id)
        if not actual:
            logger.warning(f"[SettleDiff] task {task_id} cannot resolve actual price, skip")
            return None

        diff = deducted - actual
        if diff == 0:
            return None

        # 5. 发起结算（与退费相同的两步 perseids 调用）
        from perseids_server.client import make_perseids_request
        success, message, response_data = make_perseids_request(
            endpoint='get_auth_token_by_user_id', method='POST', data={"user_id": user_id}
        )
        if not success:
            logger.error(f"[SettleDiff] task {task_id} get auth token failed: {message}")
            return None
        headers = {'Authorization': f"Bearer {response_data['token']}"}

        if diff > 0:
            txn, behavior, amount = refund_txn, 'increase', diff
        else:
            txn, behavior, amount = charge_txn, 'deduct', -diff

        success, message, _ = make_perseids_request(
            endpoint='user/calculate_computing_power', method='POST', headers=headers,
            data={"computing_power": amount, "behavior": behavior, "transaction_id": txn}
        )
        if success:
            logger.info(
                f"[SettleDiff] task {task_id} settled: deducted={deducted}, "
                f"actual={actual}, {'refund' if diff > 0 else 'charge'} {amount}"
            )
            return diff
        # 补收失败（如余额不足）best-effort：仅告警，本次让利；退差失败则待审计脚本补偿
        logger.error(f"[SettleDiff] task {task_id} settle {behavior} {amount} failed: {message}")
        return None
    except Exception as e:
        logger.error(f"[SettleDiff] task {task_id} settle failed: {e}")
        return None


def settle_success_diff_for_task(task_id) -> Optional[int]:
    """按任务ID取完整记录并结算差价（成功终态挂钩统一入口）

    五个成功终态写入点（task/visual_task.py 同步API与异步完成、
    task/download_queue_task.py 下载worker×2、task/sync_task_executor.py
    同步执行器）在置 AI_TOOL_STATUS_COMPLETED 后调用本函数。
    内部重新查询 ai_tools 以获取切换后的最终 implementation；
    幂等且吞异常，可安全重复调用。新增成功终态点时必须同样挂钩。
    """
    try:
        from model.ai_tools import AIToolsModel
        ai_tool = AIToolsModel.get_by_id(task_id)
        if not ai_tool:
            logger.warning(f"[SettleDiff] task {task_id} not found, skip settle")
            return None
        return settle_task_success_diff(ai_tool)
    except Exception as e:
        logger.error(f"[SettleDiff] load task {task_id} failed: {e}")
        return None


def sort_resolution_options(options: List[str]) -> List[str]:
    """分辨率档位按 1K/2K/3K… 再 480P/720P… 排列，避免 1K 落到列表底部。"""

    def rank(value: str):
        text = str(value or "").strip()
        compact = text.replace(" ", "")
        if len(compact) >= 2 and compact[:-1].isdigit() and compact[-1] in "Kk":
            return (0, int(compact[:-1]), text.lower())
        if len(compact) >= 2 and compact[:-1].isdigit() and compact[-1] in "Pp":
            return (1, int(compact[:-1]), text.lower())
        return (2, 0, text.lower())

    return sorted((str(item) for item in options if str(item or "").strip()), key=rank)


def resolution_options_for_driver_key(driver_key: str, impl_config: Any = None) -> List[str]:
    """该 DriverKey 下可配置的分辨率档位（任务修饰符 + supported_sizes + 实现方视频档位）。"""
    options: List[str] = []
    seen = set()

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if not text or text == "_default" or text in seen:
            return
        seen.add(text)
        options.append(text)

    if not driver_key:
        return options
    for task in UnifiedConfigRegistry.get_all():
        if getattr(task, "driver_name", None) != driver_key:
            continue
        for modifier in getattr(task, "power_modifiers", None) or []:
            if getattr(modifier, "attribute", None) != "resolution":
                continue
            for key in getattr(modifier, "values", None) or {}:
                add(key)
        for size in getattr(task, "supported_sizes", None) or []:
            add(size)
    if impl_config is not None:
        for item in getattr(impl_config, "supported_video_resolutions", None) or []:
            if isinstance(item, dict):
                add(item.get("value"))
            else:
                add(item)
    return sort_resolution_options(options)


def default_resolution_multipliers(driver_key: str, options: Optional[List[str]] = None) -> Dict[str, float]:
    """任务代码中的分辨率默认倍率；未声明的档位为 1.0。"""
    option_list = list(options or resolution_options_for_driver_key(driver_key))
    defaults = {item: 1.0 for item in option_list}
    if not driver_key:
        return defaults
    for task in UnifiedConfigRegistry.get_all():
        if getattr(task, "driver_name", None) != driver_key:
            continue
        for modifier in getattr(task, "power_modifiers", None) or []:
            if getattr(modifier, "attribute", None) != "resolution":
                continue
            for key, value in (getattr(modifier, "values", None) or {}).items():
                try:
                    defaults[str(key)] = float(value)
                except (TypeError, ValueError):
                    continue
    return defaults


def effective_resolution_multipliers(
    driver_key: str,
    implementation_name: str,
    impl_config: Any = None,
) -> Dict[str, Any]:
    """管理页用的档位、默认倍率、当前有效倍率。"""
    options = resolution_options_for_driver_key(driver_key, impl_config)
    defaults = default_resolution_multipliers(driver_key, options)
    current = dict(defaults)
    try:
        from model.implementation_power import ImplementationPowerModel

        db_modifiers = ImplementationPowerModel.get_modifiers(implementation_name, driver_key) or {}
    except Exception:
        db_modifiers = {}
    spec = db_modifiers.get("resolution") if isinstance(db_modifiers, dict) else None
    if isinstance(spec, dict):
        for key, value in spec.items():
            if key == "_default":
                continue
            try:
                current[str(key)] = float(value)
                if str(key) not in options:
                    options.append(str(key))
                    defaults.setdefault(str(key), 1.0)
            except (TypeError, ValueError):
                continue
    options = sort_resolution_options(options)
    return {
        "resolution_options": options,
        "resolution_multipliers": {key: current.get(key, 1.0) for key in options},
        "default_resolution_multipliers": {key: defaults.get(key, 1.0) for key in options},
    }
