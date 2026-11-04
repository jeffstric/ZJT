"""
ComputingPowerService 算力服务 - 对应Go的handler/computing_power.go
"""
from typing import Optional, Dict, Any
import logging

import pymysql

from model.computing_power import ComputingPowerModel, ComputingPower
from model.computing_power_log import ComputingPowerLogModel
from model.database import (
    transaction,
    execute_query_in_transaction,
    execute_insert_in_transaction,
    execute_update_in_transaction,
)

ALREADY_PROCESSED_MESSAGE = "该交易已处理"
_POWER_LOG_INSERT_SQL = """
    INSERT INTO computing_power_log
    (user_id, behavior, computing_power, `from`, `to`, message, note, transaction_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

logger = logging.getLogger(__name__)


def _duplicate_key_text(exc: BaseException) -> str:
    args = getattr(exc, "args", ()) or ()
    if len(args) > 1:
        return str(args[1]).lower()
    return str(exc).lower()


def _is_duplicate_transaction(exc: BaseException) -> bool:
    """唯一索引冲突且落在 transaction_id 上，视为这笔流水已经入过账。"""
    if not isinstance(exc, pymysql.err.IntegrityError):
        return False
    if not exc.args or exc.args[0] != 1062:
        return False
    text = _duplicate_key_text(exc)
    return "transaction_id" in text


def _is_duplicate_user_power_row(exc: BaseException) -> bool:
    """并发首笔加款同时插入 computing_power 行时，输掉的一方重试一次。"""
    if not isinstance(exc, pymysql.err.IntegrityError):
        return False
    if not exc.args or exc.args[0] != 1062:
        return False
    text = _duplicate_key_text(exc)
    return "transaction_id" not in text and "user_id" in text


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

        if transaction_id is not None:
            transaction_id = str(transaction_id).strip() or None

        # 余额更新和流水插入放在同一事务里。唯一索引冲突会回滚余额，
        # 避免「余额已加上、流水插入失败」造成双倍入账。
        # 「该交易已处理」仍返回 success=False，微信支付/签到等调用方按文案识别幂等重放。
        last_user_row_race = None
        for _attempt in range(2):
            try:
                return ComputingPowerService._apply_power_change(
                    user_id, computing_power, behavior, transaction_id, message, note,
                )
            except pymysql.err.IntegrityError as exc:
                if _is_duplicate_transaction(exc):
                    return {"success": False, "message": ALREADY_PROCESSED_MESSAGE}
                if _is_duplicate_user_power_row(exc) and _attempt == 0:
                    last_user_row_race = exc
                    continue
                raise
        logger.error(f"算力行并发插入重试仍失败 user_id={user_id}: {last_user_row_race}")
        return {"success": False, "message": "算力更新失败，请重试"}

    @staticmethod
    def _apply_power_change(
        user_id: int,
        computing_power: int,
        behavior: str,
        transaction_id: Optional[str],
        message: Optional[str],
        note: Optional[str],
    ) -> Dict[str, Any]:
        with transaction() as conn:
            current = execute_query_in_transaction(
                conn,
                "SELECT computing_power FROM computing_power WHERE user_id = %s FOR UPDATE",
                (user_id,),
                fetch_one=True,
            )
            if transaction_id:
                existing = execute_query_in_transaction(
                    conn,
                    "SELECT id FROM computing_power_log WHERE transaction_id = %s LIMIT 1",
                    (transaction_id,),
                    fetch_one=True,
                )
                if existing:
                    return {"success": False, "message": ALREADY_PROCESSED_MESSAGE}

            if not current:
                if behavior != "increase":
                    return {"success": False, "message": "用户算力数据不存在，无法扣除"}
                execute_insert_in_transaction(
                    conn,
                    """
                    INSERT INTO computing_power (user_id, computing_power, expiration_time)
                    VALUES (%s, %s, NULL)
                    """,
                    (user_id, computing_power),
                )
                execute_insert_in_transaction(
                    conn,
                    _POWER_LOG_INSERT_SQL,
                    (user_id, "increase", computing_power, 0, computing_power, message, note, transaction_id),
                )
                return {
                    "success": True,
                    "message": "算力增加成功",
                    "data": {
                        "previous_computing_power": 0,
                        "current_computing_power": computing_power,
                        "behavior": behavior,
                        "amount": computing_power,
                    },
                }

            previous_power = int(current["computing_power"] or 0)
            if behavior == "increase":
                new_power = previous_power + computing_power
            else:
                new_power = previous_power - computing_power
                if new_power < 0:
                    return {
                        "success": False,
                        "message": "算力不足，无法扣除",
                        "data": {
                            "current_computing_power": previous_power,
                            "required_computing_power": computing_power,
                        },
                    }

            execute_update_in_transaction(
                conn,
                "UPDATE computing_power SET computing_power = %s, updated_at = NOW() WHERE user_id = %s",
                (new_power, user_id),
            )
            execute_insert_in_transaction(
                conn,
                _POWER_LOG_INSERT_SQL,
                (user_id, behavior, computing_power, previous_power, new_power, message, note, transaction_id),
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
            },
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
