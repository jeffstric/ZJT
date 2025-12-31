"""
Payment Orders Model - Database operations for payment_orders table
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class PaymentOrder:
    """Payment Order model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.order_id = kwargs.get('order_id')
        self.user_id = kwargs.get('user_id')
        self.package_id = kwargs.get('package_id')
        self.computing_power = kwargs.get('computing_power')
        self.price = kwargs.get('price')
        self.platform = kwargs.get('platform', 'wechat')
        self.payment_type = kwargs.get('payment_type')
        self.status = kwargs.get('status', 0)
        self.transaction_id = kwargs.get('transaction_id')
        self.payment_ip = kwargs.get('payment_ip')
        self.note = kwargs.get('note')
        self.paid_at = kwargs.get('paid_at')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'order_id': self.order_id,
            'user_id': self.user_id,
            'package_id': self.package_id,
            'computing_power': self.computing_power,
            'price': self.price,
            'platform': self.platform,
            'payment_type': self.payment_type,
            'status': self.status,
            'transaction_id': self.transaction_id,
            'payment_ip': self.payment_ip,
            'note': self.note,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class PaymentOrdersModel:
    """Payment Orders database operations"""
    
    @staticmethod
    def create(
        order_id: str,
        user_id: int,
        package_id: int,
        computing_power: int,
        price: float,
        payment_type: str,
        platform: str = 'wechat',
        status: int = 0,
        payment_ip: Optional[str] = None,
        note: Optional[str] = None
    ) -> int:
        """
        Create a new payment order record
        
        Args:
            order_id: 商户订单号
            user_id: 用户ID
            package_id: 套餐ID
            computing_power: 算力值
            price: 支付金额
            payment_type: 支付类型（JSAPI/H5/NATIVE）
            platform: 支付平台（wechat/alipay等）
            status: 订单状态（0-待支付, 1-已支付, 2-已取消, 3-已退款）
            payment_ip: 支付IP地址
            note: 备注信息
        
        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO payment_orders 
            (order_id, user_id, package_id, computing_power, price, platform, payment_type, status, payment_ip, note, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """
        try:
            record_id = execute_insert(sql, (
                order_id,
                user_id,
                package_id,
                computing_power,
                price,
                platform,
                payment_type,
                status,
                payment_ip,
                note
            ))
            logger.info(f"Created payment order: {order_id}, platform: {platform}, record_id: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create payment order: {e}")
            raise
    
    @staticmethod
    def get_by_order_id(order_id: str) -> Optional[PaymentOrder]:
        """
        Get payment order by order_id
        
        Args:
            order_id: 商户订单号
        
        Returns:
            PaymentOrder object or None
        """
        sql = "SELECT * FROM payment_orders WHERE order_id = %s"
        try:
            result = execute_query(sql, (order_id,), fetch_one=True)
            if result:
                return PaymentOrder(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get payment order by order_id {order_id}: {e}")
            raise
    
    @staticmethod
    def get_by_id(record_id: int) -> Optional[PaymentOrder]:
        """
        Get payment order by ID
        
        Args:
            record_id: 记录ID
        
        Returns:
            PaymentOrder object or None
        """
        sql = "SELECT * FROM payment_orders WHERE id = %s"
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return PaymentOrder(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get payment order by id {record_id}: {e}")
            raise
    
    @staticmethod
    def get_by_user_id(user_id: int, limit: int = 10, offset: int = 0) -> List[PaymentOrder]:
        """
        Get payment orders by user_id
        
        Args:
            user_id: 用户ID
            limit: 返回记录数量限制
            offset: 偏移量
        
        Returns:
            List of PaymentOrder objects
        """
        sql = """
            SELECT * FROM payment_orders 
            WHERE user_id = %s 
            ORDER BY created_at DESC 
            LIMIT %s OFFSET %s
        """
        try:
            results = execute_query(sql, (user_id, limit, offset), fetch_all=True)
            return [PaymentOrder(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get payment orders by user_id {user_id}: {e}")
            raise
    
    @staticmethod
    def update_status(
        order_id: str,
        status: int,
        transaction_id: Optional[str] = None
    ) -> int:
        """
        Update payment order status
        
        Args:
            order_id: 商户订单号
            status: 新状态（0-待支付, 1-已支付, 2-已取消, 3-已退款）
            transaction_id: 微信支付交易号（可选）
        
        Returns:
            Number of affected rows
        """
        if transaction_id:
            sql = """
                UPDATE payment_orders 
                SET status = %s, transaction_id = %s, paid_at = NOW(), updated_at = NOW()
                WHERE order_id = %s
            """
            params = (status, transaction_id, order_id)
        else:
            sql = """
                UPDATE payment_orders 
                SET status = %s, updated_at = NOW()
                WHERE order_id = %s
            """
            params = (status, order_id)
        
        try:
            affected_rows = execute_update(sql, params)
            logger.info(f"Updated payment order {order_id} status to {status}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update payment order status: {e}")
            raise
    
    @staticmethod
    def update_paid(order_id: str, transaction_id: str) -> int:
        """
        Mark payment order as paid
        
        Args:
            order_id: 商户订单号
            transaction_id: 微信支付交易号
        
        Returns:
            Number of affected rows
        """
        return PaymentOrdersModel.update_status(order_id, 1, transaction_id)
    
    @staticmethod
    def update_computing_power(order_id: str, computing_power: int) -> int:
        """
        Update computing power for a specific payment order.
        """
        sql = """
            UPDATE payment_orders
            SET computing_power = %s, updated_at = NOW()
            WHERE order_id = %s
        """
        try:
            affected_rows = execute_update(sql, (computing_power, order_id))
            logger.info(f"Updated computing power for order {order_id} to {computing_power}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update computing power for order {order_id}: {e}")
            raise
    
    @staticmethod
    def cancel(order_id: str) -> int:
        """
        Cancel payment order
        
        Args:
            order_id: 商户订单号
        
        Returns:
            Number of affected rows
        """
        return PaymentOrdersModel.update_status(order_id, 2)
    
    @staticmethod
    def count_by_user_id(user_id: int) -> int:
        """
        Count payment orders by user_id
        
        Args:
            user_id: 用户ID
        
        Returns:
            Total count
        """
        sql = "SELECT COUNT(*) as count FROM payment_orders WHERE user_id = %s"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to count payment orders by user_id {user_id}: {e}")
            raise
