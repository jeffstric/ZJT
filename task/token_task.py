"""
Token log processing task - 处理token日志并扣除算力
对应Go的handler/token_task.go
"""
import logging

from model.computing_power import ComputingPowerModel
from model.computing_power_log import ComputingPowerLogModel
from model.token_log import TokenLogModel
from model.uncalculated_token import UncalculatedTokenModel
from model.vendor_model import VendorModelModel

logger = logging.getLogger(__name__)


def calculate_computing_power_from_tokens(
    input_token: int,
    output_token: int,
    cache_read: int,
    cache_creation: int,
    user_id: int,
    vendor_id: int,
    model_id: int
) -> tuple:
    """
    根据token计算需要扣除的算力
    
    Args:
        input_token: 输入token数
        output_token: 输出token数
        cache_read: 缓存读取数
        cache_creation: 缓存创建数
        user_id: 用户ID
        vendor_id: 供应商ID
        model_id: 模型ID
        
    Returns:
        (需要扣除的算力, 备注)
    """
    # 保存原始token值
    original_input = input_token
    original_output = output_token
    original_cache = cache_read
    
    # 获取未计算token
    uncalculated_input = 0
    uncalculated_output = 0
    uncalculated_cache_read = 0
    uncalculated_token = None
    
    try:
        uncalculated_token = UncalculatedTokenModel.get_by_user_id(user_id)
    except Exception as e:
        logger.error(f"获取用户 {user_id} 未计算token失败: {e}")
    
    if uncalculated_token:
        if uncalculated_token.uncalculated_input_token is not None:
            uncalculated_input = uncalculated_token.uncalculated_input_token
            input_token += uncalculated_token.uncalculated_input_token
        if uncalculated_token.uncalculated_output_token is not None:
            uncalculated_output = uncalculated_token.uncalculated_output_token
            output_token += uncalculated_token.uncalculated_output_token
        if uncalculated_token.uncalculated_cache_read is not None:
            uncalculated_cache_read = uncalculated_token.uncalculated_cache_read
            cache_read += uncalculated_token.uncalculated_cache_read
    
    # 计算聚合后的token值
    aggregated_input = input_token
    aggregated_output = output_token
    aggregated_cache = cache_read
    
    # 获取供应商模型配置
    vendor_model = None
    if vendor_id > 0 and model_id > 0:
        try:
            vendor_model = VendorModelModel.get_by_vendor_model(vendor_id, model_id)
        except Exception as e:
            logger.error(f"获取供应商模型配置失败(vendor:{vendor_id}, model:{model_id}): {e}")
    
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
    
    # 计算扣除算力和剩余token
    remaining_input = input_token % vendor_model.input_token_threshold
    deduct_input = input_token // vendor_model.input_token_threshold
    
    remaining_output = output_token % vendor_model.output_token_threshold
    deduct_output = output_token // vendor_model.output_token_threshold
    
    remaining_cache = cache_read % vendor_model.cache_read_threshold
    deduct_cache = cache_read // vendor_model.cache_read_threshold
    
    total_deduct = deduct_input + deduct_output + deduct_cache
    
    # 更新或创建未计算token记录
    update_needed = (uncalculated_token is not None or 
                     remaining_input != 0 or remaining_output != 0 or remaining_cache != 0)
    
    if update_needed:
        try:
            if uncalculated_token:
                UncalculatedTokenModel.update(user_id, remaining_input, remaining_output, remaining_cache)
            else:
                if remaining_input != 0 or remaining_output != 0 or remaining_cache != 0:
                    UncalculatedTokenModel.create(user_id, remaining_input, remaining_output, remaining_cache)
        except Exception as e:
            logger.error(f"更新/创建用户 {user_id} 未计算token失败: {e}")
    
    # 构建详细note
    note = (
        f"原始token(输入:{original_input}, 输出:{original_output}, 缓存读取:{original_cache}) | "
        f"未计算token(输入:{uncalculated_input}, 输出:{uncalculated_output}, 缓存读取:{uncalculated_cache_read}) | "
        f"聚合后token(输入:{aggregated_input}, 输出:{aggregated_output}, 缓存读取:{aggregated_cache}) | "
        f"剩余token(输入:{remaining_input}, 输出:{remaining_output}, 缓存读取:{remaining_cache})"
    )
    logger.info(note)
    
    return total_deduct, note


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
                model_id=token_log.model_id or 0
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
