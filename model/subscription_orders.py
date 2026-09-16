"""
SubscriptionOrders Model - 月度订阅订单表（每个扣款周期一条订单）
首期为「支付中签约」订单；续期为委托代扣扣款订单
"""
from typing import List, Optional, Dict, Any
from .database import execute_query, execute_update, execute_insert
import logging

from config.constant import SubscriptionOrderStatus

logger = logging.getLogger(__name__)


class SubscriptionOrder:
    """订阅订单实体"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.order_id = kwargs.get('order_id')
        self.contract_code = kwargs.get('contract_code')
        self.user_id = kwargs.get('user_id')
        self.subscription_plan_id = kwargs.get('subscription_plan_id')
        self.period_index = kwargs.get('period_index', 1)
        self.amount = kwargs.get('amount')
        self.computing_power = kwargs.get('computing_power')
        self.period_start = kwargs.get('period_start')
        self.period_end = kwargs.get('period_end')
        self.status = kwargs.get('status', SubscriptionOrderStatus.PENDING_PAY)
        self.transaction_id = kwargs.get('transaction_id')
        self.upgrade_from_contract_code = kwargs.get('upgrade_from_contract_code')
        self.err_code = kwargs.get('err_code')
        self.err_msg = kwargs.get('err_msg')
        self.prenotify_sent_at = kwargs.get('prenotify_sent_at')
        self.next_retry_at = kwargs.get('next_retry_at')
        self.retry_count = kwargs.get('retry_count', 0)
        self.paid_at = kwargs.get('paid_at')
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'order_id': self.order_id,
            'contract_code': self.contract_code,
            'user_id': self.user_id,
            'subscription_plan_id': self.subscription_plan_id,
            'period_index': self.period_index,
            'amount': float(self.amount) if self.amount is not None else None,
            'computing_power': self.computing_power,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'status': self.status,
            'transaction_id': self.transaction_id,
            'upgrade_from_contract_code': self.upgrade_from_contract_code,
            'err_code': self.err_code,
            'err_msg': self.err_msg,
            'retry_count': self.retry_count,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'create_at': self.create_at.isoformat() if self.create_at else None,
        }


class SubscriptionOrdersModel:
    """订阅订单数据库操作"""

    @staticmethod
    def create(
        order_id: str,
        contract_code: str,
        user_id: int,
        subscription_plan_id: int,
        period_index: int,
        amount: float,
        computing_power: int,
        period_start,
        period_end,
        status: int = SubscriptionOrderStatus.PENDING_PAY,
        upgrade_from_contract_code: Optional[str] = None,
    ) -> int:
        """创建订阅订单（一个扣款周期一条；upgrade_from_contract_code 非空表示套餐升级单）"""
        sql = """
            INSERT INTO subscription_orders
            (order_id, contract_code, user_id, subscription_plan_id, period_index,
             amount, computing_power, period_start, period_end, status,
             upgrade_from_contract_code, retry_count, create_at, update_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, NOW(), NOW())
        """
        try:
            record_id = execute_insert(sql, (
                order_id, contract_code, user_id, subscription_plan_id, period_index,
                amount, computing_power, period_start, period_end, status,
                upgrade_from_contract_code,
            ))
            logger.info(f"Created subscription order {order_id}, period={period_index}, record_id={record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create subscription order {order_id}: {e}")
            raise

    @staticmethod
    def get_by_order_id(order_id: str) -> Optional[SubscriptionOrder]:
        sql = "SELECT * FROM subscription_orders WHERE order_id = %s"
        try:
            result = execute_query(sql, (order_id,), fetch_one=True)
            return SubscriptionOrder(**result) if result else None
        except Exception as e:
            logger.error(f"Failed to get subscription order {order_id}: {e}")
            raise

    @staticmethod
    def get_latest_by_contract(contract_code: str) -> Optional[SubscriptionOrder]:
        """取签约下最近一条订单（按周期序号倒序）"""
        sql = "SELECT * FROM subscription_orders WHERE contract_code = %s ORDER BY period_index DESC LIMIT 1"
        try:
            result = execute_query(sql, (contract_code,), fetch_one=True)
            return SubscriptionOrder(**result) if result else None
        except Exception as e:
            logger.error(f"Failed to get latest order for contract {contract_code}: {e}")
            raise

    @staticmethod
    def get_by_user(user_id: int, limit: int = 20, offset: int = 0) -> List[SubscriptionOrder]:
        sql = """
            SELECT * FROM subscription_orders
            WHERE user_id = %s
            ORDER BY id DESC
            LIMIT %s OFFSET %s
        """
        try:
            results = execute_query(sql, (user_id, limit, offset), fetch_all=True)
            return [SubscriptionOrder(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get subscription orders for user {user_id}: {e}")
            raise

    @staticmethod
    def mark_paid(order_id: str, transaction_id: str) -> int:
        """标记已支付（幂等由调用方保证：status=1 时不再调用）"""
        sql = """
            UPDATE subscription_orders
            SET status = %s, transaction_id = %s, paid_at = NOW(), update_at = NOW()
            WHERE order_id = %s
        """
        try:
            return execute_update(sql, (
                SubscriptionOrderStatus.PAID, transaction_id, order_id,
            ))
        except Exception as e:
            logger.error(f"Failed to mark order paid {order_id}: {e}")
            raise

    @staticmethod
    def mark_confirming(order_id: str) -> int:
        """direct 模式受理成功：等待 24 小时自动扣费结果"""
        sql = """
            UPDATE subscription_orders
            SET status = %s, next_retry_at = DATE_ADD(NOW(), INTERVAL 26 HOUR), update_at = NOW()
            WHERE order_id = %s
        """
        try:
            return execute_update(sql, (SubscriptionOrderStatus.CONFIRMING, order_id))
        except Exception as e:
            logger.error(f"Failed to mark order confirming {order_id}: {e}")
            raise

    @staticmethod
    def mark_failed(order_id: str, err_code: str, err_msg: str, next_retry_at, retry_increment: int = 1) -> int:
        """扣款/支付失败：记录原因并安排下次重试"""
        sql = """
            UPDATE subscription_orders
            SET status = %s, err_code = %s, err_msg = %s, next_retry_at = %s,
                retry_count = retry_count + %s, update_at = NOW()
            WHERE order_id = %s
        """
        try:
            return execute_update(sql, (
                SubscriptionOrderStatus.FAILED, err_code, err_msg, next_retry_at,
                retry_increment, order_id,
            ))
        except Exception as e:
            logger.error(f"Failed to mark order failed {order_id}: {e}")
            raise

    @staticmethod
    def close(order_id: str, err_code: Optional[str] = None, err_msg: Optional[str] = None) -> int:
        """关闭订单（重试窗口耗尽/手动取消）"""
        sql = """
            UPDATE subscription_orders
            SET status = %s,
                err_code = COALESCE(%s, err_code),
                err_msg = COALESCE(%s, err_msg),
                next_retry_at = NULL, update_at = NOW()
            WHERE order_id = %s
        """
        try:
            return execute_update(sql, (
                SubscriptionOrderStatus.CLOSED, err_code, err_msg, order_id,
            ))
        except Exception as e:
            logger.error(f"Failed to close order {order_id}: {e}")
            raise

    @staticmethod
    def mark_prenotify_sent(order_id: str) -> int:
        """记录预扣费通知已下发（等待期起点）"""
        sql = """
            UPDATE subscription_orders
            SET prenotify_sent_at = NOW(), update_at = NOW()
            WHERE order_id = %s AND prenotify_sent_at IS NULL
        """
        try:
            return execute_update(sql, (order_id,))
        except Exception as e:
            logger.error(f"Failed to mark prenotify sent {order_id}: {e}")
            raise

    @staticmethod
    def get_retry_due_orders(now=None) -> List[SubscriptionOrder]:
        """取到期应重试的订单：失败/待扣款且 next_retry_at 已到；不含 CONFIRMING（等回调）"""
        sql = """
            SELECT * FROM subscription_orders
            WHERE status IN (%s, %s)
              AND (next_retry_at IS NULL OR next_retry_at <= NOW())
              AND period_start IS NOT NULL
              AND period_start <= DATE_ADD(NOW(), INTERVAL 1 DAY)
            ORDER BY period_start ASC
            LIMIT 100
        """
        try:
            results = execute_query(sql, (
                SubscriptionOrderStatus.PENDING_PAY, SubscriptionOrderStatus.FAILED,
            ), fetch_all=True)
            return [SubscriptionOrder(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get retry due orders: {e}")
            raise

    @staticmethod
    def set_grant_flag(order_id: str, flag: Optional[str]) -> int:
        """
        标记/清除算力发放状态（复用 err_code 字段）：
          GRANT_PENDING - 已收款，发放进行中（崩溃恢复用）
          GRANT_FAILED  - 发放失败，待补偿
          NULL          - 发放完成
        仅作用于已支付订单，避免影响扣款重试链路
        """
        sql = """
            UPDATE subscription_orders
            SET err_code = %s, update_at = NOW()
            WHERE order_id = %s AND status = %s
        """
        try:
            return execute_update(sql, (flag, order_id, SubscriptionOrderStatus.PAID))
        except Exception as e:
            logger.error(f"Failed to set grant flag {flag} for {order_id}: {e}")
            raise

    @staticmethod
    def get_grant_pending_orders(limit: int = 50) -> List[SubscriptionOrder]:
        """取已支付但算力未发放完成（补偿中）的订单"""
        sql = """
            SELECT * FROM subscription_orders
            WHERE status = %s AND err_code IN ('GRANT_PENDING', 'GRANT_FAILED')
            ORDER BY update_at ASC
            LIMIT %s
        """
        try:
            results = execute_query(sql, (
                SubscriptionOrderStatus.PAID, limit,
            ), fetch_all=True)
            return [SubscriptionOrder(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get grant pending orders: {e}")
            raise

    @staticmethod
    def get_stale_confirming_orders(confirm_hours: int) -> List[SubscriptionOrder]:
        """取受理后长时间无回调的订单（CONFIRMING 超时），需主动查单"""
        sql = """
            SELECT * FROM subscription_orders
            WHERE status = %s
              AND next_retry_at IS NOT NULL
              AND next_retry_at <= NOW()
              AND update_at <= DATE_ADD(NOW(), INTERVAL %s HOUR)
            LIMIT 100
        """
        try:
            results = execute_query(sql, (
                SubscriptionOrderStatus.CONFIRMING, confirm_hours,
            ), fetch_all=True)
            return [SubscriptionOrder(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get stale confirming orders: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `subscription_orders` (
  `id` int NOT NULL AUTO_INCREMENT,
  `order_id` varchar(64) NOT NULL COMMENT '商户订单号(SUB_前缀)',
  `contract_code` varchar(64) NOT NULL COMMENT '关联签约协议号',
  `user_id` int NOT NULL COMMENT '用户ID',
  `subscription_plan_id` int NOT NULL COMMENT '本地订阅套餐ID',
  `period_index` int NOT NULL DEFAULT 1 COMMENT '第几期(1=首期签约支付)',
  `amount` decimal(10,2) NOT NULL COMMENT '本期扣款金额(元)',
  `computing_power` int NOT NULL COMMENT '本期发放算力',
  `period_start` datetime DEFAULT NULL COMMENT '本期覆盖周期开始(上一期结束日)',
  `period_end` datetime DEFAULT NULL COMMENT '本期覆盖周期结束',
  `status` tinyint NOT NULL DEFAULT 0 COMMENT '0-待支付/待扣款 1-已支付 2-扣款失败 3-已关闭 4-已受理待确认',
  `transaction_id` varchar(64) DEFAULT NULL COMMENT '微信支付订单号',
  `upgrade_from_contract_code` varchar(64) DEFAULT NULL COMMENT '套餐升级单：被替换的旧签约协议号(支付成功后自动解约)',
  `err_code` varchar(64) DEFAULT NULL COMMENT '最近一次失败错误码',
  `err_msg` varchar(255) DEFAULT NULL COMMENT '最近一次失败描述',
  `prenotify_sent_at` datetime DEFAULT NULL COMMENT '预扣费通知下发时间',
  `next_retry_at` datetime DEFAULT NULL COMMENT '下次扣款重试时间',
  `retry_count` int NOT NULL DEFAULT 0 COMMENT '已重试次数',
  `paid_at` datetime DEFAULT NULL COMMENT '支付完成时间',
  `create_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_order_id` (`order_id`),
  KEY `idx_contract_period` (`contract_code`,`period_index`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_status_retry` (`status`,`next_retry_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='月度订阅订单表(每周期一条)';
"""
