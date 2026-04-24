"""
CheckinService 签到服务单元测试
测试每日签到、连续签到奖励、签到状态查询等核心逻辑
"""
import unittest
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from ..base.base_db_test import DatabaseTestCase


class TestCheckinService(DatabaseTestCase):
    """CheckinService 单元测试"""

    def setUp(self):
        """每个测试用例开始前：清空相关表"""
        super().setUp()
        self.clear_table('daily_checkin')
        self.clear_table('computing_power')
        self.clear_table('computing_power_log')
        self.clear_table('system_config')
        self.clear_table('users')
        self.clear_table('user_tokens')

        # 创建一个测试用户（用于需要真实 user_id 的场景）
        from model.users import UsersModel
        self.test_user_id = UsersModel.create(
            phone='13800138000',
            password='test_password',
            role='user',
            status=1
        )

    def _mock_config(self, enabled=True, base_reward=10, streak_bonus_enabled=True, streak_config=None):
        """辅助方法：mock 签到配置"""
        side_effects = {
            ('checkin', 'enabled'): enabled,
            ('checkin', 'base_reward'): base_reward,
            ('checkin', 'streak_bonus_enabled'): streak_bonus_enabled,
            ('checkin', 'streak_bonus_config'): streak_config or {"3": 5, "7": 15},
        }

        def mock_get(*keys, default=None):
            return side_effects.get(tuple(keys), default)

        return patch('services.checkin_service.get_dynamic_config_value', side_effect=mock_get)

    # ==================== 基础签到测试 ====================

    def test_first_checkin_success(self):
        """测试首次签到成功，获得基础奖励"""
        from services.checkin_service import CheckinService

        with self._mock_config():
            result = CheckinService.checkin(self.test_user_id)

        self.assertTrue(result['success'])
        self.assertEqual(result['data']['base_reward'], 10)
        self.assertEqual(result['data']['bonus_reward'], 0)
        self.assertEqual(result['data']['reward_amount'], 10)
        self.assertEqual(result['data']['streak_days'], 1)
        self.assertTrue(result['data']['checked_in_today'])

    def test_checkin_disabled(self):
        """测试签到功能关闭时无法签到"""
        from services.checkin_service import CheckinService

        with self._mock_config(enabled=False):
            result = CheckinService.checkin(self.test_user_id)

        self.assertFalse(result['success'])
        self.assertEqual(result['message'], '签到功能暂未开启')

    def test_checkin_twice_same_day(self):
        """测试同一天重复签到被拒绝"""
        from services.checkin_service import CheckinService

        with self._mock_config():
            first = CheckinService.checkin(self.test_user_id)
            self.assertTrue(first['success'])

            second = CheckinService.checkin(self.test_user_id)
            self.assertFalse(second['success'])
            self.assertEqual(second['message'], '今日已签到')
            self.assertEqual(second['data']['streak_days'], 1)

    # ==================== 连续签到测试 ====================

    def test_consecutive_checkin_3_days(self):
        """测试连续签到3天，第三天获得额外奖励"""
        from services.checkin_service import CheckinService
        from model.daily_checkin import DailyCheckinModel

        with self._mock_config(streak_config={"3": 5, "7": 15}):
            # 第1天
            day1 = date.today() - timedelta(days=2)
            DailyCheckinModel.create(
                user_id=self.test_user_id,
                checkin_date=day1,
                streak_days=1,
                base_reward=10,
                bonus_reward=0,
                reward_amount=10,
                transaction_id=f"checkin_{self.test_user_id}_{day1.strftime('%Y%m%d')}"
            )

            # 第2天
            day2 = date.today() - timedelta(days=1)
            DailyCheckinModel.create(
                user_id=self.test_user_id,
                checkin_date=day2,
                streak_days=2,
                base_reward=10,
                bonus_reward=0,
                reward_amount=10,
                transaction_id=f"checkin_{self.test_user_id}_{day2.strftime('%Y%m%d')}"
            )

            # 第3天（今天）
            result = CheckinService.checkin(self.test_user_id)

        self.assertTrue(result['success'])
        self.assertEqual(result['data']['streak_days'], 3)
        self.assertEqual(result['data']['base_reward'], 10)
        self.assertEqual(result['data']['bonus_reward'], 5)
        self.assertEqual(result['data']['reward_amount'], 15)

    def test_consecutive_checkin_7_days(self):
        """测试连续签到7天，获得更高阶梯奖励"""
        from services.checkin_service import CheckinService
        from model.daily_checkin import DailyCheckinModel

        with self._mock_config(streak_config={"3": 5, "7": 20, "14": 50}):
            # 连续签到6天历史记录
            for i in range(1, 7):
                checkin_date = date.today() - timedelta(days=7 - i)
                DailyCheckinModel.create(
                    user_id=self.test_user_id,
                    checkin_date=checkin_date,
                    streak_days=i,
                    base_reward=10,
                    bonus_reward=5 if i == 3 else (20 if i >= 7 else 0),
                    reward_amount=10 + (5 if i == 3 else (20 if i >= 7 else 0)),
                    transaction_id=f"checkin_{self.test_user_id}_{checkin_date.strftime('%Y%m%d')}"
                )

            # 第7天
            result = CheckinService.checkin(self.test_user_id)

        self.assertTrue(result['success'])
        self.assertEqual(result['data']['streak_days'], 7)
        self.assertEqual(result['data']['bonus_reward'], 20)
        self.assertEqual(result['data']['reward_amount'], 30)

    def test_streak_reset_after_missing_day(self):
        """测试断签后连续天数重置为1"""
        from services.checkin_service import CheckinService
        from model.daily_checkin import DailyCheckinModel

        with self._mock_config():
            # 3天前的签到
            old_date = date.today() - timedelta(days=3)
            DailyCheckinModel.create(
                user_id=self.test_user_id,
                checkin_date=old_date,
                streak_days=5,
                base_reward=10,
                bonus_reward=0,
                reward_amount=10,
                transaction_id=f"checkin_{self.test_user_id}_{old_date.strftime('%Y%m%d')}"
            )

            result = CheckinService.checkin(self.test_user_id)

        self.assertTrue(result['success'])
        self.assertEqual(result['data']['streak_days'], 1)
        self.assertEqual(result['data']['bonus_reward'], 0)

    def test_consecutive_checkin_14_days(self):
        """测试连续签到14天，获得最高阶梯奖励"""
        from services.checkin_service import CheckinService
        from model.daily_checkin import DailyCheckinModel

        with self._mock_config(streak_config={"3": 5, "7": 15, "14": 50}):
            # 连续签到13天
            for i in range(1, 14):
                checkin_date = date.today() - timedelta(days=14 - i)
                bonus = 0
                if i >= 3:
                    bonus = 5
                if i >= 7:
                    bonus = 15
                DailyCheckinModel.create(
                    user_id=self.test_user_id,
                    checkin_date=checkin_date,
                    streak_days=i,
                    base_reward=10,
                    bonus_reward=bonus,
                    reward_amount=10 + bonus,
                    transaction_id=f"checkin_{self.test_user_id}_{checkin_date.strftime('%Y%m%d')}"
                )

            result = CheckinService.checkin(self.test_user_id)

        self.assertTrue(result['success'])
        self.assertEqual(result['data']['streak_days'], 14)
        self.assertEqual(result['data']['bonus_reward'], 50)
        self.assertEqual(result['data']['reward_amount'], 60)

    def test_consecutive_checkin_30_days(self):
        """测试连续签到30天，获得30天阶梯奖励"""
        from services.checkin_service import CheckinService
        from model.daily_checkin import DailyCheckinModel

        with self._mock_config(streak_config={"7": 15, "14": 30, "30": 100}):
            # 连续签到29天
            for i in range(1, 30):
                checkin_date = date.today() - timedelta(days=30 - i)
                bonus = 0
                if i >= 7:
                    bonus = 15
                if i >= 14:
                    bonus = 30
                DailyCheckinModel.create(
                    user_id=self.test_user_id,
                    checkin_date=checkin_date,
                    streak_days=i,
                    base_reward=10,
                    bonus_reward=bonus,
                    reward_amount=10 + bonus,
                    transaction_id=f"checkin_{self.test_user_id}_{checkin_date.strftime('%Y%m%d')}"
                )

            result = CheckinService.checkin(self.test_user_id)

        self.assertTrue(result['success'])
        self.assertEqual(result['data']['streak_days'], 30)
        self.assertEqual(result['data']['bonus_reward'], 100)
        self.assertEqual(result['data']['reward_amount'], 110)

    def test_streak_bonus_disabled(self):
        """测试关闭连续签到奖励时，只获得基础奖励"""
        from services.checkin_service import CheckinService
        from model.daily_checkin import DailyCheckinModel

        with self._mock_config(streak_bonus_enabled=False, streak_config={"3": 5}):
            # 连续2天历史
            for i in range(1, 3):
                checkin_date = date.today() - timedelta(days=3 - i)
                DailyCheckinModel.create(
                    user_id=self.test_user_id,
                    checkin_date=checkin_date,
                    streak_days=i,
                    base_reward=10,
                    bonus_reward=0,
                    reward_amount=10,
                    transaction_id=f"checkin_{self.test_user_id}_{checkin_date.strftime('%Y%m%d')}"
                )

            result = CheckinService.checkin(self.test_user_id)

        self.assertTrue(result['success'])
        self.assertEqual(result['data']['streak_days'], 3)
        self.assertEqual(result['data']['bonus_reward'], 0)
        self.assertEqual(result['data']['reward_amount'], 10)

    # ==================== 幂等性测试 ====================

    def test_idempotent_after_deleting_daily_checkin_only(self):
        """测试只删除 daily_checkin 记录但 computing_power_log 仍存在时，算力不会重复发放"""
        from services.checkin_service import CheckinService
        from model.daily_checkin import DailyCheckinModel

        with self._mock_config():
            # 第一次签到
            first = CheckinService.checkin(self.test_user_id)
            self.assertTrue(first['success'])

            # 删除 daily_checkin 记录（模拟用户只删了这张表）
            today = date.today()
            record = DailyCheckinModel.get_by_user_and_date(self.test_user_id, today)
            self.assertIsNotNone(record)
            self.execute_update(
                "DELETE FROM daily_checkin WHERE user_id = %s AND checkin_date = %s",
                (self.test_user_id, today)
            )
            self._connection.commit()

            # 再次签到
            second = CheckinService.checkin(self.test_user_id)

        self.assertFalse(second['success'])
        self.assertIn('已签到', second['message'])

    # ==================== 签到状态查询测试 ====================

    def test_get_checkin_status_first_day(self):
        """测试获取首次签到前的状态"""
        from services.checkin_service import CheckinService

        with self._mock_config(streak_config={"3": 5}):
            result = CheckinService.get_checkin_status(self.test_user_id)

        self.assertTrue(result['success'])
        self.assertFalse(result['data']['checked_in_today'])
        self.assertEqual(result['data']['streak_days'], 0)
        self.assertEqual(result['data']['base_reward'], 10)
        self.assertEqual(result['data']['next_bonus'], 0)
        self.assertEqual(result['data']['days_to_next_reward'], 2)
        self.assertEqual(result['data']['next_reward_amount'], 5)

    def test_get_checkin_status_already_checked_in(self):
        """测试已签到当天的状态"""
        from services.checkin_service import CheckinService

        with self._mock_config(streak_config={"3": 5, "7": 15}):
            CheckinService.checkin(self.test_user_id)
            result = CheckinService.get_checkin_status(self.test_user_id)

        self.assertTrue(result['success'])
        self.assertTrue(result['data']['checked_in_today'])
        self.assertEqual(result['data']['streak_days'], 1)
        self.assertEqual(result['data']['days_to_next_reward'], 1)
        self.assertEqual(result['data']['next_reward_amount'], 5)

    def test_get_checkin_status_after_streak_5_days(self):
        """测试连续5天后的签到状态，预测距离7天奖励还有多久"""
        from services.checkin_service import CheckinService
        from model.daily_checkin import DailyCheckinModel

        with self._mock_config(streak_config={"3": 5, "7": 15, "14": 50}):
            # 模拟连续签到5天
            for i in range(1, 6):
                checkin_date = date.today() - timedelta(days=6 - i)
                bonus = 5 if i >= 3 else 0
                DailyCheckinModel.create(
                    user_id=self.test_user_id,
                    checkin_date=checkin_date,
                    streak_days=i,
                    base_reward=10,
                    bonus_reward=bonus,
                    reward_amount=10 + bonus,
                    transaction_id=f"checkin_{self.test_user_id}_{checkin_date.strftime('%Y%m%d')}"
                )

            result = CheckinService.get_checkin_status(self.test_user_id)

        self.assertTrue(result['success'])
        self.assertFalse(result['data']['checked_in_today'])
        self.assertEqual(result['data']['streak_days'], 5)
        # 明天签到是第6天，距离7天奖励还差1天
        self.assertEqual(result['data']['days_to_next_reward'], 1)
        self.assertEqual(result['data']['next_reward_amount'], 15)

    def test_get_checkin_status_no_more_rewards(self):
        """测试已达到最高阶梯奖励后，没有更高奖励可预测"""
        from services.checkin_service import CheckinService
        from model.daily_checkin import DailyCheckinModel

        with self._mock_config(streak_config={"3": 5}):
            # 连续签到5天（已超过最高阶梯3天）
            for i in range(1, 6):
                checkin_date = date.today() - timedelta(days=6 - i)
                bonus = 5 if i >= 3 else 0
                DailyCheckinModel.create(
                    user_id=self.test_user_id,
                    checkin_date=checkin_date,
                    streak_days=i,
                    base_reward=10,
                    bonus_reward=bonus,
                    reward_amount=10 + bonus,
                    transaction_id=f"checkin_{self.test_user_id}_{checkin_date.strftime('%Y%m%d')}"
                )

            result = CheckinService.get_checkin_status(self.test_user_id)

        self.assertTrue(result['success'])
        self.assertIsNone(result['data']['days_to_next_reward'])
        self.assertIsNone(result['data']['next_reward_amount'])

    # ==================== 数据库记录测试 ====================

    def test_checkin_creates_database_record(self):
        """测试签到后会正确创建 daily_checkin 和 computing_power_log 记录"""
        from services.checkin_service import CheckinService
        from model.daily_checkin import DailyCheckinModel

        with self._mock_config():
            result = CheckinService.checkin(self.test_user_id)

        self.assertTrue(result['success'])

        # 验证 daily_checkin 记录
        today = date.today()
        record = DailyCheckinModel.get_by_user_and_date(self.test_user_id, today)
        self.assertIsNotNone(record)
        self.assertEqual(record.streak_days, 1)
        self.assertEqual(record.base_reward, 10)
        self.assertEqual(record.reward_amount, 10)

        # 验证 computing_power_log 记录
        logs = self.execute_query(
            "SELECT * FROM computing_power_log WHERE user_id = %s AND transaction_id = %s",
            (self.test_user_id, f"checkin_{self.test_user_id}_{today.strftime('%Y%m%d')}")
        )
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['behavior'], 'increase')
        self.assertEqual(logs[0]['computing_power'], 10)


if __name__ == '__main__':
    unittest.main()
