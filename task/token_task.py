"""
Token log processing task - 处理token日志并扣除算力
对应Go的handler/token_task.go
"""
import logging

from model.computing_power import ComputingPowerModel
from model.computing_power_log import ComputingPowerLogModel
from model.token_log import TokenLogModel
from model.uncalculated_power import UncalculatedPowerModel
from model.vendor_model import VendorModelModel

logger = logging.getLogger(__name__)


def calculate_computing_power_from_tokens(
    input_token: int,
    output_token: int,
    cache_read: int,
    cache_creation: int,
    user_id: int,
    vendor_id: int,
    model_id: int,
    raw_input_token: int = 0
) -> tuple:
    """
    根据token计算需要扣除的算力

    使用 1/100 算力为最小刻度，累积到 uncalculated_power 表。
    累积满 100（即 1 算力）时扣减。

    Args:
        input_token: 输入token数
        output_token: 输出token数
        cache_read: 缓存读取数
        cache_creation: 缓存创建数（暂未使用）
        user_id: 用户ID
        vendor_id: 供应商ID
        model_id: 模型ID
        raw_input_token: 原始输入token数，用于分段计费选择

    Returns:
        (需要扣除的算力, 备注)
    """
    # 获取供应商模型配置（支持分段计费）
    vendor_model = None
    if vendor_id > 0 and model_id > 0:
        try:
            # 使用 raw_input_token 选择合适的计费档位
            vendor_model = VendorModelModel.get_by_vendor_model_for_billing(
                vendor_id, model_id, raw_input_token
            )
        except Exception as e:
            logger.error(f"获取供应商模型配置失败(vendor:{vendor_id}, model:{model_id}, raw_input:{raw_input_token}): {e}")

    if not vendor_model:
        logger.warning(f"用户 {user_id} 缺少供应商模型配置，无法计算算力")
        return 0, ""

    # 验证阈值配置
    if not vendor_model.input_token_threshold or vendor_model.input_token_threshold <= 0:
        logger.warning(f"供应商模型缺少有效输入token阈值(vendor:{vendor_id}, model:{model_id})")
        return 0, ""
    if not vendor_model.output_token_threshold or vendor_model.output_token_threshold <= 0:
        logger.warning(f"供应商模型缺少有效输出token阈值(vendor:{vendor_id}, model:{model_id})")
        return 0, ""
    if not vendor_model.cache_read_threshold or vendor_model.cache_read_threshold <= 0:
        logger.warning(f"供应商模型缺少有效缓存读取阈值(vendor:{vendor_id}, model:{model_id})")
        return 0, ""

    # 计算本次 token_log 的算力成本（浮点）
    cost_power = (
        input_token / vendor_model.input_token_threshold
        + output_token / vendor_model.output_token_threshold
        + cache_read / vendor_model.cache_read_threshold
    )
    cost_hundredths = round(cost_power * 100)

    # 获取已有的未扣减算力
    existing_power = 0
    uncalculated = None
    try:
        uncalculated = UncalculatedPowerModel.get_by_user_id(user_id)
        if uncalculated:
            existing_power = uncalculated.accumulated_power
    except Exception as e:
        logger.error(f"获取用户 {user_id} 未扣减算力失败: {e}")

    # 聚合
    total = existing_power + cost_hundredths

    # 计算扣减
    deduct_count = total // 100
    remainder = total % 100

    # 存储剩余到 uncalculated_power
    try:
        if remainder > 0 or uncalculated:
            UncalculatedPowerModel.upsert(user_id, remainder)
    except Exception as e:
        logger.error(f"更新用户 {user_id} 未扣减算力失败: {e}")

    # 构建详细note
    note = (
        f"token(输入:{input_token}, 输出:{output_token}, 缓存读取:{cache_read}) | "
        f"阈值(输入:{vendor_model.input_token_threshold}, 输出:{vendor_model.output_token_threshold}, "
        f"缓存读取:{vendor_model.cache_read_threshold}) | "
        f"本次算力成本:{cost_power:.4f}({cost_hundredths}百分位) | "
        f"已有累积:{existing_power}百分位 → 总计:{total}百分位 | "
        f"扣减:{deduct_count}算力, 剩余:{remainder}百分位"
    )
    logger.info(note)

    return deduct_count, note


def process_token_logs():
    """
    处理未处理的token日志
    对应Go的ProcessTokenLogs函数
    
    Returns:
        处理结果字典
    """
    logs = TokenLogModel.get_unprocessed(limit=100)
    
    if not logs:
        return {"success": True, "message": "没有未处理的日志", "processed": 0}
    
    logger.info(f"开始处理 {len(logs)} 条未处理的token日志")
    
    processed_count = 0
    error_count = 0
    
    for token_log in logs:
        try:
            # 计算需要扣除的算力
            computing_power_to_deduct, note_detail = calculate_computing_power_from_tokens(
                input_token=token_log.input_token or 0,
                output_token=token_log.output_token or 0,
                cache_read=token_log.cache_read or 0,
                cache_creation=token_log.cache_creation or 0,
                user_id=token_log.user_id,
                vendor_id=token_log.vendor_id or 0,
                model_id=token_log.model_id or 0,
                raw_input_token=token_log.raw_input_token or 0
            )

            # 如果扣减为0，只标记为已处理，不生成算力日志
            if computing_power_to_deduct == 0:
                TokenLogModel.update_status(token_log.id, 1)
                processed_count += 1
                logger.info(f"token日志 ID:{token_log.id} 扣减算力为0，已标记为已处理")
                continue

            # 获取用户当前算力
            user_power = ComputingPowerModel.get_by_user_id(token_log.user_id)
            if not user_power:
                logger.warning(f"获取用户 {token_log.user_id} 算力失败，跳过该日志")
                continue
            
            # 扣除算力
            new_power = user_power.computing_power - computing_power_to_deduct
            
            ComputingPowerModel.update(token_log.user_id, new_power)
            
            # 创建算力日志
            transaction_id = f"token_log_{token_log.id}"
            ComputingPowerLogModel.create(
                user_id=token_log.user_id,
                behavior="deduct",
                computing_power=computing_power_to_deduct,
                from_value=user_power.computing_power,
                to_value=new_power,
                message="Token消耗扣除算力",
                note=note_detail,
                transaction_id=transaction_id
            )
            
            # 更新token日志状态为已处理
            TokenLogModel.update_status(token_log.id, 1)
            
            processed_count += 1
            logger.info(f"成功处理token日志 ID:{token_log.id}, 用户:{token_log.user_id}, 扣除算力:{computing_power_to_deduct}")
            
        except Exception as e:
            logger.error(f"处理token日志失败 - ID:{token_log.id}, 错误:{e}")
            error_count += 1
    
    return {
        "success": True,
        "message": f"处理完成，成功:{processed_count}，失败:{error_count}",
        "processed": processed_count,
        "errors": error_count,
    }


def process_token_task(app=None):
    """Token日志处理任务入口点"""
    try:
        process_token_logs()
    except Exception as e:
        logger.error(f"Token处理任务出错: {e}")
        import traceback
        logger.error(traceback.format_exc())
