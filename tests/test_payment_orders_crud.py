"""
PaymentOrders 表 CRUD 测试
"""
import unittest
from datetime import datetime
from .base_db_test import DatabaseTestCase


class TestPaymentOrdersCRUD(DatabaseTestCase):
    """PaymentOrders 表增删改查测试"""
    
    def test_create_payment_order(self):
        """测试创建支付订单"""
        order_id = self.insert_fixture('payment_orders', {
            'order_id': 'ORD_20260206_001',
            'user_id': 1,
            'package_id': 101,
            'computing_power': 1000,
            'price': 99.00,
            'platform': 'wechat',
            'payment_type': 'NATIVE',
            'status': 0,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })
        
        self.assertIsNotNone(order_id)
        self.assertGreater(order_id, 0)
    
    def test_read_payment_order(self):
        """测试查询支付订单"""
        order_id = self.insert_fixture('payment_orders', {
            'order_id': 'ORD_20260206_002',
            'user_id': 1,
            'package_id': 102,
            'computing_power': 2000,
            'price': 199.00,
            'platform': 'wechat',
            'payment_type': 'JSAPI',
            'status': 1,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })
        
        result = self.execute_query(
            "SELECT * FROM `payment_orders` WHERE id = %s",
            (order_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['order_id'], 'ORD_20260206_002')
        self.assertEqual(result[0]['computing_power'], 2000)
        self.assertEqual(float(result[0]['price']), 199.00)
    
    def test_update_payment_order(self):
        """测试更新支付订单"""
        order_id = self.insert_fixture('payment_orders', {
            'order_id': 'ORD_20260206_003',
            'user_id': 1,
            'package_id': 103,
            'computing_power': 500,
            'price': 49.00,
            'platform': 'wechat',
            'payment_type': 'NATIVE',
            'status': 0,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })
        
        paid_time = datetime.now()
        affected_rows = self.execute_update(
            "UPDATE `payment_orders` SET status = %s, transaction_id = %s, paid_at = %s, updated_at = %s WHERE id = %s",
            (1, 'WX_TXN_12345', paid_time, datetime.now(), order_id)
        )
        
        self.assertEqual(affected_rows, 1)
        
        result = self.execute_query(
            "SELECT * FROM `payment_orders` WHERE id = %s",
            (order_id,)
        )
        
        self.assertEqual(result[0]['status'], 1)
        self.assertEqual(result[0]['transaction_id'], 'WX_TXN_12345')
        self.assertIsNotNone(result[0]['paid_at'])
    
    def test_delete_payment_order(self):
        """测试删除支付订单"""
        order_id = self.insert_fixture('payment_orders', {
            'order_id': 'ORD_20260206_004',
            'user_id': 1,
            'package_id': 104,
            'computing_power': 100,
            'price': 9.90,
            'platform': 'wechat',
            'payment_type': 'NATIVE',
            'status': -1,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })
        
        count_before = self.count_rows('payment_orders', 'id = %s', (order_id,))
        self.assertEqual(count_before, 1)
        
        affected_rows = self.execute_update(
            "DELETE FROM `payment_orders` WHERE id = %s",
            (order_id,)
        )
        
        self.assertEqual(affected_rows, 1)
        
        count_after = self.count_rows('payment_orders', 'id = %s', (order_id,))
        self.assertEqual(count_after, 0)
    
    def test_query_orders_by_user(self):
        """测试按用户查询订单"""
        self.insert_fixture('payment_orders', {
            'order_id': 'ORD_20260206_005',
            'user_id': 1,
            'package_id': 105,
            'computing_power': 1000,
            'price': 99.00,
            'platform': 'wechat',
            'payment_type': 'NATIVE',
            'status': 1,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })
        self.insert_fixture('payment_orders', {
            'order_id': 'ORD_20260206_006',
            'user_id': 1,
            'package_id': 106,
            'computing_power': 2000,
            'price': 199.00,
            'platform': 'wechat',
            'payment_type': 'NATIVE',
            'status': 1,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })
        
        result = self.execute_query(
            "SELECT * FROM `payment_orders` WHERE user_id = %s AND status = %s",
            (1, 1)
        )
        
        self.assertGreaterEqual(len(result), 2)
    
    def test_query_order_by_order_id(self):
        """测试按订单号查询（唯一键）"""
        unique_order_id = 'ORD_20260206_UNIQUE_001'
        
        order_id = self.insert_fixture('payment_orders', {
            'order_id': unique_order_id,
            'user_id': 1,
            'package_id': 107,
            'computing_power': 500,
            'price': 49.00,
            'platform': 'alipay',
            'payment_type': 'PAGE',
            'status': 0,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })
        
        result = self.execute_query(
            "SELECT * FROM `payment_orders` WHERE order_id = %s",
            (unique_order_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['order_id'], unique_order_id)
        self.assertEqual(result[0]['platform'], 'alipay')
    
    def test_query_orders_by_platform_and_status(self):
        """测试按平台和状态查询订单"""
        self.insert_fixture('payment_orders', {
            'order_id': 'ORD_20260206_007',
            'user_id': 1,
            'package_id': 108,
            'computing_power': 1000,
            'price': 99.00,
            'platform': 'wechat',
            'payment_type': 'NATIVE',
            'status': 1,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })
        self.insert_fixture('payment_orders', {
            'order_id': 'ORD_20260206_008',
            'user_id': 2,
            'package_id': 109,
            'computing_power': 1000,
            'price': 99.00,
            'platform': 'wechat',
            'payment_type': 'NATIVE',
            'status': 1,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })
        
        result = self.execute_query(
            "SELECT * FROM `payment_orders` WHERE platform = %s AND status = %s",
            ('wechat', 1)
        )
        
        self.assertGreaterEqual(len(result), 2)
        for row in result:
            self.assertEqual(row['platform'], 'wechat')
            self.assertEqual(row['status'], 1)


if __name__ == '__main__':
    unittest.main()
