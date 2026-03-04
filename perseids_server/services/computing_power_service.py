"""
ComputingPowerService 算力服务 - 对应Go的handler/computing_power.go
"""
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import logging

from model.computing_power import ComputingPowerModel, ComputingPower
from model.computing_power_log import ComputingPowerLogModel, ComputingPowerLog

logger = logging.getLogger(__name__)


class ComputingPowerService:
    """算力服务 - 查询、增减算力等"""
    
    @staticmethod
    def check_computing_power(user_id: int) -> Dict[str, Any]:
        """
        查询用户算力
        
        Args:
            user_id: 用户ID
            
        Returns:
            算力信息
        """
        power = ComputingPowerModel.get_by_user_id(user_id)
        
        if not power:
            # 用户算力数据不存在时，自动创建初始记录（算力为0）
            try:
                ComputingPowerModel.create_or_update(user_id, 0, None)
                power = ComputingPowerModel.get_by_user_id(user_id)
            except Exception as e:
                logger.error(f"自动创建用户算力记录失败: {e}")
        
        if not power:
            # 创建失败时返回默认值
            return {
                "success": True,
                "message": "查询成功",
                "data": {
                    "exists": False,
                    "computing_power": 0,
                    "expiration_time": None,
                    "user_id": user_id,
                }
            }
        
        return {
            "success": True,
            "message": "查询成功",
            "data": {
                "exists": True,
                "computing_power": power.computing_power,
                "expiration_time": power.expiration_time.isoformat() if power.expiration_time else None,
                "user_id": user_id,
            }
        }
    
    @staticmethod
    def calculate_computing_power(
        user_id: int,
        computing_power: int,
        behavior: str,
        transaction_id: str,
        message: Optional[str] = None,
        note: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        计算（增减）算力
        
        Args:
            user_id: 用户ID
            computing_power: 算力值（必须为正数）
            behavior: 'increase' 或 'deduct'
            transaction_id: 交易ID（用于幂等性）
            message: 消息
            note: 备注
            
        Returns:
            操作结果
        """
        # 验证参数
        if computing_power <= 0:
            return {"success": False, "message": "算力值必须大于0"}
        
        if behavior not in ("increase", "deduct"):
            return {"success": False, "message": "无效的操作类型"}
        
        # 检查幂等性
        if transaction_id and ComputingPowerLogModel.check_transaction_exists(transaction_id):
            return {"success": False, "message": "该交易已处理"}
        
        # 查询当前算力
        current_power = ComputingPowerModel.get_by_user_id(user_id)
        
        if not current_power:
            if behavior == "increase":
                # 创建新记录
                ComputingPowerModel.create(user_id, computing_power, None)
                
                # 记录日志
                ComputingPowerLogModel.create(
                    user_id=user_id,
                    behavior="increase",
                    computing_power=computing_power,
                    from_value=0,
                    to_value=computing_power,
                    message=message,
                    note=note,
                    transaction_id=transaction_id
                )
                
                return {
                    "success": True,
                    "message": "算力增加成功",
                    "data": {
                        "previous_computing_power": 0,
                        "current_computing_power": computing_power,
                        "behavior": behavior,
                        "amount": computing_power,
                    }
                }
            else:
                return {"success": False, "message": "用户算力数据不存在，无法扣除"}
        
        # 计算新算力值
        previous_power = current_power.computing_power
        
        if behavior == "increase":
            new_power = previous_power + computing_power
        else:  # deduct
            new_power = previous_power - computing_power
            if new_power < 0:
                return {
                    "success": False,
                    "message": "算力不足，无法扣除",
                    "data": {
                        "current_computing_power": previous_power,
                        "required_computing_power": computing_power,
                    }
                }
        
        # 更新算力
        ComputingPowerModel.update(user_id, new_power)
        
        # 记录日志
        ComputingPowerLogModel.create(
            user_id=user_id,
            behavior=behavior,
            computing_power=computing_power,
            from_value=previous_power,
            to_value=new_power,
            message=message,
            note=note,
            transaction_id=transaction_id
        )
        
        action_msg = "算力增加成功" if behavior == "increase" else "算力扣除成功"
        logger.info(f"{action_msg} - 用户ID: {user_id}, {previous_power} -> {new_power}")
        
        return {
            "success": True,
            "message": action_msg,
            "data": {
                "previous_computing_power": previous_power,
                "current_computing_power": new_power,
                "behavior": behavior,
                "amount": computing_power,
            }
        }
    
    @staticmethod
    def get_computing_power_logs(
        user_id: Optional[int] = None,
        behavior: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        获取算力日志
        
        Args:
            user_id: 用户ID（可选）
            behavior: 行为类型（可选）
            limit: 每页数量
            offset: 偏移量
            
        Returns:
            日志列表和总数
        """
        logs = ComputingPowerLogModel.get_all(user_id, behavior, limit, offset)
        total = ComputingPowerLogModel.get_count(user_id, behavior)
        
        return {
            "success": True,
            "message": "查询成功",
            "data": {
                "logs": [log.to_dict() for log in logs],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        }
    
    @staticmethod
    def get_invitation_reward_stats(user_id: int) -> Dict[str, Any]:
        """
        获取用户邀请奖励统计
        
        Args:
            user_id: 用户ID
            
        Returns:
            邀请奖励统计
        """
        stats = ComputingPowerLogModel.get_invitation_reward_stats(user_id)
        
        return {
            "success": True,
            "message": "查询成功",
            "data": stats
        }
    
    @staticmethod
    def ensure_user_has_power(user_id: int, initial_power: int = 50) -> ComputingPower:
        """
        确保用户有算力记录，没有则创建
        
        Args:
            user_id: 用户ID
            initial_power: 初始算力值
            
        Returns:
            算力记录
        """
        power = ComputingPowerModel.get_by_user_id(user_id)
        if not power:
            ComputingPowerModel.create(user_id, initial_power, None)
            power = ComputingPowerModel.get_by_user_id(user_id)
        return power
