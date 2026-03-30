"""
AuthService 认证服务单元测试
测试注册、登录等功能的算力分配逻辑
"""
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock
from .base_db_test import DatabaseTestCase


# Mock类 - 定义在类之前供 patch 使用
class MockVerifyCodesModel:
    @staticmethod
    def verify(phone, code, code_type):
        return True


class MockUsersModel:
    @staticmethod
    def get_total_count():
        return 0

    @staticmethod
    def get_by_invite_code(code):
        return None

    @staticmethod
    def generate_unique_invite_code():
        return 'TEST001'


class TestAuthServiceComputingPower(DatabaseTestCase):
    """AuthService 算力分配测试"""

    def setUp(self):
        """每个测试用例开始前：开启事务并初始化数据"""
        super().setUp()
        # 清空相关表，确保测试独立性
        self.clear_table('computing_power')
        self.clear_table('login_log')
        self.clear_table('user_tokens')
        self.clear_table('verify_codes')
        self.clear_table('users')

    def test_first_admin_user_gets_100000_power(self):
        """测试首个管理员用户获得100000算力"""
        from perseids_server.services.auth_service import AuthService

        # 模拟首个用户注册（无邀请码）
        with patch('perseids_server.services.auth_service.VerifyCodesModel', MockVerifyCodesModel), \
             patch('perseids_server.services.auth_service.UsersModel', MockUsersModel), \
             patch('perseids_server.services.auth_service.generate_secret_key', return_value='secret123'):

            result = AuthService.register(
                phone='13800138000',
                password='TestPass123!',
                verify_code='123456',
                invite_code=None,
                ip_address='127.0.0.1',
                user_agent='test'
            )

        self.assertTrue(result['success'])
        self.assertEqual(result['data']['role'], 'admin')
        self.assertTrue(result['data']['is_first_admin'])

        # 验证用户算力
        user_id = result['data']['user_id']
        power = self.execute_query(
            "SELECT * FROM `computing_power` WHERE user_id = %s",
            (user_id,)
        )
        self.assertEqual(len(power), 1)
        self.assertEqual(power[0]['computing_power'], 100000)

    def test_normal_user_gets_default_power(self):
        """测试普通用户获得默认50算力"""
        from perseids_server.services.auth_service import AuthService

        # 先插入一个管理员用户
        admin_id = self.insert_fixture('users', {
            'phone': '13900139000',
            'password_hash': 'hash123',
            'status': 1,
            'role': 'admin',
            'secret_key': 'admin_secret',
            'invite_code': 'ADMIN001',
            'inviter_id': None,
            'terms_agreed': 1,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })

        # 插入管理员的算力记录
        self.insert_fixture('computing_power', {
            'user_id': admin_id,
            'computing_power': 100000,
            'expiration_time': None,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })

        # 模拟第二个用户注册
        mock_users_model = MagicMock()
        mock_users_model.get_total_count.return_value = 1
        mock_users_model.generate_unique_invite_code.return_value = 'USER001'
        with patch('perseids_server.services.auth_service.VerifyCodesModel', MockVerifyCodesModel), \
             patch('perseids_server.services.auth_service.UsersModel', mock_users_model), \
             patch('perseids_server.services.auth_service.generate_secret_key', return_value='user_secret'):

            result = AuthService.register(
                phone='13800138001',
                password='TestPass123!',
                verify_code='123456',
                invite_code=None,
                ip_address='127.0.0.1',
                user_agent='test'
            )

        self.assertTrue(result['success'])
        self.assertEqual(result['data']['role'], 'user')
        self.assertFalse(result['data']['is_first_admin'])

        # 验证用户算力为默认50
        user_id = result['data']['user_id']
        power = self.execute_query(
            "SELECT * FROM `computing_power` WHERE user_id = %s",
            (user_id,)
        )
        self.assertEqual(len(power), 1)
        self.assertEqual(power[0]['computing_power'], 50)

    def test_invited_user_gets_75_power(self):
        """测试被邀请用户获得75算力"""
        from perseids_server.services.auth_service import AuthService

        # 先插入一个管理员用户
        admin_id = self.insert_fixture('users', {
            'phone': '13900139000',
            'password_hash': 'hash123',
            'status': 1,
            'role': 'admin',
            'secret_key': 'admin_secret',
            'invite_code': 'ADMIN001',
            'inviter_id': None,
            'terms_agreed': 1,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })

        # 插入管理员的算力记录
        self.insert_fixture('computing_power', {
            'user_id': admin_id,
            'computing_power': 100000,
            'expiration_time': None,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        })

        # 模拟第二个用户注册（使用邀请码）
        mock_users_model = MagicMock()
        mock_users_model.get_total_count.return_value = 1
        mock_users_model.get_by_invite_code.return_value = MagicMock(id=admin_id)
        mock_users_model.generate_unique_invite_code.return_value = 'USER002'
        with patch('perseids_server.services.auth_service.VerifyCodesModel', MockVerifyCodesModel), \
             patch('perseids_server.services.auth_service.UsersModel', mock_users_model), \
             patch('perseids_server.services.auth_service.generate_secret_key', return_value='user_secret'):

            result = AuthService.register(
                phone='13800138002',
                password='TestPass123!',
                verify_code='123456',
                invite_code='ADMIN001',
                ip_address='127.0.0.1',
                user_agent='test'
            )

        self.assertTrue(result['success'])
        self.assertEqual(result['data']['role'], 'user')
        self.assertFalse(result['data']['is_first_admin'])

        # 验证用户算力为被邀请人算力75
        user_id = result['data']['user_id']
        power = self.execute_query(
            "SELECT * FROM `computing_power` WHERE user_id = %s",
            (user_id,)
        )
        self.assertEqual(len(power), 1)
        self.assertEqual(power[0]['computing_power'], 75)


if __name__ == '__main__':
    unittest.main()
