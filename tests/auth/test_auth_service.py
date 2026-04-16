"""
AuthService 认证服务单元测试
测试注册、登录等功能的算力分配逻辑
"""
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock
from ..base.base_db_test import DatabaseTestCase


# Mock类 - 定义在类之前供 patch 使用
class MockVerifyCodesModel:
    @staticmethod
    def verify(phone, code, code_type):
        return True

    @staticmethod
    def delete_by_phone(phone):
        pass


class MockUsersModel:
    @staticmethod
    def get_total_count():
        return 0

    @staticmethod
    def get_by_phone(phone):
        return None

    @staticmethod
    def get_by_invite_code(code):
        return None

    @staticmethod
    def generate_unique_invite_code():
        return 'TEST001'


class MockLoginLogModel:
    @staticmethod
    def create(user_id, ip_address, user_agent, status):
        pass


class TestAuthServiceComputingPower(DatabaseTestCase):
    """AuthService 算力分配测试"""

    def setUp(self):
        """每个测试用例开始前：开启事务并初始化数据"""
        super().setUp()
        # 清空相关表，确保测试独立性
        self.clear_table('computing_power')
        self.clear_table('user_tokens')
        self.clear_table('verify_codes')
        self.clear_table('users')

    def test_first_admin_user_gets_100000_power(self):
        """测试首个管理员用户获得100000算力"""
        from perseids_server.services.auth_service import AuthService

        # Mock execute_insert 返回一个假的 user_id
        mock_execute_insert = MagicMock(return_value=999)
        # Mock ComputingPowerModel.create 来捕获调用参数
        mock_computing_power_create = MagicMock(return_value=1)

        with patch('perseids_server.services.auth_service.VerifyCodesModel', MockVerifyCodesModel), \
             patch('perseids_server.services.auth_service.UsersModel', MockUsersModel), \
             patch('perseids_server.services.auth_service.LoginLogModel', MockLoginLogModel), \
             patch('perseids_server.services.auth_service.ComputingPowerModel') as mock_cp_model, \
             patch('perseids_server.services.auth_service.generate_secret_key', return_value='secret123'), \
             patch('model.database.execute_insert', mock_execute_insert):

            mock_cp_model.create = mock_computing_power_create

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

        # 验证 ComputingPowerModel.create 被调用，且算力为 100000
        mock_computing_power_create.assert_called_once()
        call_args = mock_computing_power_create.call_args
        self.assertEqual(call_args[0][1], 100000)  # 第二个参数是算力值

    def test_normal_user_gets_default_power(self):
        """测试普通用户获得默认50算力"""
        from perseids_server.services.auth_service import AuthService

        # 模拟第二个用户注册（非首个用户）
        mock_users_model = MagicMock()
        mock_users_model.get_total_count.return_value = 1  # 已有1个用户
        mock_users_model.get_by_phone.return_value = None
        mock_users_model.generate_unique_invite_code.return_value = 'USER001'
        mock_execute_insert = MagicMock(return_value=1000)
        mock_computing_power_create = MagicMock(return_value=1)

        with patch('perseids_server.services.auth_service.VerifyCodesModel', MockVerifyCodesModel), \
             patch('perseids_server.services.auth_service.UsersModel', mock_users_model), \
             patch('perseids_server.services.auth_service.LoginLogModel', MockLoginLogModel), \
             patch('perseids_server.services.auth_service.ComputingPowerModel') as mock_cp_model, \
             patch('perseids_server.services.auth_service.generate_secret_key', return_value='user_secret'), \
             patch('model.database.execute_insert', mock_execute_insert):

            mock_cp_model.create = mock_computing_power_create

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

        # 验证 ComputingPowerModel.create 被调用，且算力为默认 50
        mock_computing_power_create.assert_called_once()
        call_args = mock_computing_power_create.call_args
        self.assertEqual(call_args[0][1], 50)  # 第二个参数是算力值

    def test_invited_user_gets_75_power(self):
        """测试被邀请用户获得75算力"""
        from perseids_server.services.auth_service import AuthService

        # 模拟被邀请用户注册（使用邀请码）
        admin_id = 100  # 模拟的邀请人ID
        mock_users_model = MagicMock()
        mock_users_model.get_total_count.return_value = 1  # 已有1个用户
        mock_users_model.get_by_phone.return_value = None
        mock_users_model.get_by_invite_code.return_value = MagicMock(id=admin_id)
        mock_users_model.generate_unique_invite_code.return_value = 'USER002'
        mock_execute_insert = MagicMock(return_value=1001)
        mock_computing_power_create = MagicMock(return_value=1)

        with patch('perseids_server.services.auth_service.VerifyCodesModel', MockVerifyCodesModel), \
             patch('perseids_server.services.auth_service.UsersModel', mock_users_model), \
             patch('perseids_server.services.auth_service.LoginLogModel', MockLoginLogModel), \
             patch('perseids_server.services.auth_service.ComputingPowerModel') as mock_cp_model, \
             patch('perseids_server.services.auth_service.ComputingPowerLogModel', MagicMock()), \
             patch('perseids_server.services.auth_service.generate_secret_key', return_value='user_secret'), \
             patch('model.database.execute_insert', mock_execute_insert):

            mock_cp_model.create = mock_computing_power_create
            mock_cp_model.get_by_user_id.return_value = MagicMock(computing_power=100000)
            mock_cp_model.update = MagicMock()

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

        # 验证 ComputingPowerModel.create 被调用，且算力为被邀请人算力 75
        mock_computing_power_create.assert_called_once()
        call_args = mock_computing_power_create.call_args
        self.assertEqual(call_args[0][1], 75)  # 第二个参数是算力值


if __name__ == '__main__':
    unittest.main()
