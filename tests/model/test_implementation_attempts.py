"""
ImplementationAttempt / ImplementationAttemptModel 单元测试

测试数据类初始化、常量、以及 Model 层的数据处理逻辑。
数据库操作（execute_query/execute_insert/execute_update）均使用 mock。
"""
import sys
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

# Mock 数据库依赖
_saved_db = sys.modules.get('model.database')
sys.modules['model.database'] = MagicMock()

from model.implementation_attempts import (
    ImplementationAttempt,
    ImplementationAttemptModel,
    ATTEMPT_STATUS_IN_PROGRESS,
    ATTEMPT_STATUS_SUCCESS,
    ATTEMPT_STATUS_FAILED,
)


class TestAttemptStatusConstants(unittest.TestCase):
    """测试状态常量值"""

    def test_in_progress_is_0(self):
        """进行中的状态码为 0"""
        self.assertEqual(ATTEMPT_STATUS_IN_PROGRESS, 0)

    def test_success_is_2(self):
        """成功的状态码为 2"""
        self.assertEqual(ATTEMPT_STATUS_SUCCESS, 2)

    def test_failed_is_minus_1(self):
        """失败的状态码为 -1"""
        self.assertEqual(ATTEMPT_STATUS_FAILED, -1)


class TestImplementationAttemptDataClass(unittest.TestCase):
    """测试 ImplementationAttempt 数据类"""

    def test_default_values(self):
        """默认值正确初始化"""
        attempt = ImplementationAttempt()
        self.assertIsNone(attempt.id)
        self.assertIsNone(attempt.ai_tool_id)
        self.assertIsNone(attempt.implementation)
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.status, ATTEMPT_STATUS_IN_PROGRESS)
        self.assertIsNone(attempt.error_message)
        self.assertIsNone(attempt.started_at)
        self.assertIsNone(attempt.completed_at)
        self.assertIsNone(attempt.create_at)

    def test_custom_values(self):
        """自定义值正确赋值"""
        now = datetime.now()
        attempt = ImplementationAttempt(
            id=100,
            ai_tool_id=50,
            implementation=3,
            attempt_number=2,
            status=ATTEMPT_STATUS_SUCCESS,
            error_message=None,
            started_at=now,
            completed_at=now,
            create_at=now,
        )
        self.assertEqual(attempt.id, 100)
        self.assertEqual(attempt.ai_tool_id, 50)
        self.assertEqual(attempt.implementation, 3)
        self.assertEqual(attempt.attempt_number, 2)
        self.assertEqual(attempt.status, ATTEMPT_STATUS_SUCCESS)


class TestImplementationAttemptModelCreate(unittest.TestCase):
    """测试 ImplementationAttemptModel.create()"""

    @patch('model.implementation_attempts.execute_insert')
    def test_create_returns_record_id(self, mock_insert):
        """创建成功返回记录 ID"""
        mock_insert.return_value = 42

        record_id = ImplementationAttemptModel.create(
            ai_tool_id=10,
            implementation=3,
            attempt_number=1,
            status=ATTEMPT_STATUS_IN_PROGRESS,
        )

        self.assertEqual(record_id, 42)
        mock_insert.assert_called_once()

    @patch('model.implementation_attempts.execute_insert')
    def test_create_with_custom_params(self, mock_insert):
        """自定义参数正确传递"""
        mock_insert.return_value = 1
        now = datetime.now()

        ImplementationAttemptModel.create(
            ai_tool_id=20,
            implementation=5,
            attempt_number=2,
            status=ATTEMPT_STATUS_FAILED,
            started_at=now,
            error_message='API 超时'
        )

        call_args = mock_insert.call_args
        params = call_args[0][1]
        self.assertEqual(params, (20, 5, 2, ATTEMPT_STATUS_FAILED, now, 'API 超时'))

    @patch('model.implementation_attempts.execute_insert')
    def test_create_db_error_raises(self, mock_insert):
        """数据库异常时抛出异常"""
        mock_insert.side_effect = Exception("DB connection lost")

        with self.assertRaises(Exception):
            ImplementationAttemptModel.create(ai_tool_id=1, implementation=1)


class TestImplementationAttemptModelGetActiveAttempt(unittest.TestCase):
    """测试 ImplementationAttemptModel.get_active_attempt()"""

    @patch('model.implementation_attempts.execute_query')
    def test_found_returns_attempt(self, mock_query):
        """找到活跃尝试时返回 ImplementationAttempt 对象"""
        mock_query.return_value = {
            'id': 10,
            'ai_tool_id': 50,
            'implementation': 3,
            'attempt_number': 1,
            'status': 0,
            'error_message': None,
            'started_at': datetime.now(),
            'completed_at': None,
            'create_at': datetime.now(),
        }

        result = ImplementationAttemptModel.get_active_attempt(50)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, ImplementationAttempt)
        self.assertEqual(result.id, 10)
        self.assertEqual(result.ai_tool_id, 50)

    @patch('model.implementation_attempts.execute_query')
    def test_not_found_returns_none(self, mock_query):
        """未找到活跃尝试时返回 None"""
        mock_query.return_value = None

        result = ImplementationAttemptModel.get_active_attempt(999)
        self.assertIsNone(result)


class TestImplementationAttemptModelMarkCompleted(unittest.TestCase):
    """测试 ImplementationAttemptModel.mark_completed()"""

    @patch('model.implementation_attempts.execute_update')
    def test_mark_success(self, mock_update):
        """标记成功返回影响行数"""
        mock_update.return_value = 1

        affected = ImplementationAttemptModel.mark_completed(
            record_id=10,
            status=ATTEMPT_STATUS_SUCCESS,
        )

        self.assertEqual(affected, 1)
        mock_update.assert_called_once()

    @patch('model.implementation_attempts.execute_update')
    def test_mark_with_error_message(self, mock_update):
        """带 error_message 标记"""
        mock_update.return_value = 1

        ImplementationAttemptModel.mark_completed(
            record_id=10,
            status=ATTEMPT_STATUS_FAILED,
            error_message='超时'
        )

        call_args = mock_update.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        # SQL 应包含 error_message 字段
        self.assertIn('error_message', sql)
        self.assertIn('超时', params)

    @patch('model.implementation_attempts.execute_update')
    def test_mark_with_custom_completed_at(self, mock_update):
        """自定义 completed_at 时间"""
        mock_update.return_value = 1
        custom_time = datetime(2025, 1, 1, 12, 0, 0)

        ImplementationAttemptModel.mark_completed(
            record_id=10,
            status=ATTEMPT_STATUS_SUCCESS,
            completed_at=custom_time,
        )

        call_args = mock_update.call_args
        params = call_args[0][1]
        self.assertIn(custom_time, params)


class TestImplementationAttemptModelMarkActiveCompleted(unittest.TestCase):
    """测试 ImplementationAttemptModel.mark_active_attempt_completed()"""

    @patch('model.implementation_attempts.ImplementationAttemptModel.mark_completed')
    @patch('model.implementation_attempts.ImplementationAttemptModel.get_active_attempt')
    def test_found_and_marked(self, mock_get, mock_mark):
        """找到活跃尝试并标记完成"""
        attempt = ImplementationAttempt(id=10, ai_tool_id=50)
        mock_get.return_value = attempt
        mock_mark.return_value = 1

        result = ImplementationAttemptModel.mark_active_attempt_completed(
            ai_tool_id=50,
            status=ATTEMPT_STATUS_SUCCESS
        )

        self.assertTrue(result)
        mock_mark.assert_called_once_with(10, ATTEMPT_STATUS_SUCCESS, error_message=None)

    @patch('model.implementation_attempts.ImplementationAttemptModel.get_active_attempt')
    def test_not_found_returns_false(self, mock_get):
        """无活跃尝试返回 False"""
        mock_get.return_value = None

        result = ImplementationAttemptModel.mark_active_attempt_completed(
            ai_tool_id=999,
            status=ATTEMPT_STATUS_SUCCESS
        )

        self.assertFalse(result)


class TestImplementationAttemptModelGetAttemptedImplementations(unittest.TestCase):
    """测试 ImplementationAttemptModel.get_attempted_implementations()"""

    @patch('model.implementation_attempts.execute_query')
    def test_returns_set_of_impl_ids(self, mock_query):
        """返回已尝试的实现方 ID 集合"""
        mock_query.return_value = [
            {'implementation': 1},
            {'implementation': 3},
            {'implementation': 5},
        ]

        result = ImplementationAttemptModel.get_attempted_implementations(ai_tool_id=50)

        self.assertEqual(result, {1, 3, 5})

    @patch('model.implementation_attempts.execute_query')
    def test_empty_returns_empty_set(self, mock_query):
        """无记录返回空集合"""
        mock_query.return_value = []

        result = ImplementationAttemptModel.get_attempted_implementations(ai_tool_id=999)
        self.assertEqual(result, set())

    @patch('model.implementation_attempts.execute_query')
    def test_none_returns_empty_set(self, mock_query):
        """查询返回 None 时返回空集合"""
        mock_query.return_value = None

        result = ImplementationAttemptModel.get_attempted_implementations(ai_tool_id=999)
        self.assertEqual(result, set())

    @patch('model.implementation_attempts.execute_query')
    def test_exception_returns_empty_set(self, mock_query):
        """数据库异常时返回空集合"""
        mock_query.side_effect = Exception("DB error")

        result = ImplementationAttemptModel.get_attempted_implementations(ai_tool_id=50)
        self.assertEqual(result, set())


class TestImplementationAttemptModelGetRetryImplementationCount(unittest.TestCase):
    """测试备用供应商尝试数量统计。"""

    @patch('model.implementation_attempts.execute_query')
    def test_counts_distinct_retry_implementations(self, mock_query):
        mock_query.return_value = {'retry_count': 2}

        result = ImplementationAttemptModel.get_retry_implementation_count(50)

        self.assertEqual(result, 2)
        sql = mock_query.call_args[0][0]
        self.assertIn('COUNT(DISTINCT implementation)', sql)
        self.assertIn('attempt_number >= 2', sql)

    @patch('model.implementation_attempts.execute_query')
    def test_empty_count_returns_zero(self, mock_query):
        mock_query.return_value = {'retry_count': None}

        self.assertEqual(
            ImplementationAttemptModel.get_retry_implementation_count(999),
            0,
        )


class TestImplementationAttemptModelGetStats(unittest.TestCase):
    """测试 ImplementationAttemptModel.get_stats()"""

    @patch('model.implementation_attempts.execute_query')
    def test_stats_calculation(self, mock_query):
        """统计数据计算正确"""
        mock_query.return_value = [
            {
                'type': 1,
                'implementation': 3,
                'total_count': 100,
                'success_count': 80,
                'fail_count': 20,
                'avg_duration_ms': 5000.5,
            }
        ]

        stats = ImplementationAttemptModel.get_stats(days=7)

        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]['total_count'], 100)
        self.assertEqual(stats[0]['success_count'], 80)
        self.assertEqual(stats[0]['fail_count'], 20)
        self.assertAlmostEqual(stats[0]['success_rate'], 80.0)
        self.assertEqual(stats[0]['avg_duration_ms'], 5000)

    @patch('model.implementation_attempts.execute_query')
    def test_zero_total_success_rate_is_zero(self, mock_query):
        """总数为 0 时成功率为 0"""
        mock_query.return_value = [
            {
                'type': 1,
                'implementation': 3,
                'total_count': 0,
                'success_count': 0,
                'fail_count': 0,
                'avg_duration_ms': None,
            }
        ]

        stats = ImplementationAttemptModel.get_stats(days=7)

        self.assertEqual(stats[0]['success_rate'], 0.0)
        self.assertEqual(stats[0]['avg_duration_ms'], 0)

    @patch('model.implementation_attempts.execute_query')
    def test_exception_raises(self, mock_query):
        """数据库异常时抛出异常"""
        mock_query.side_effect = Exception("DB error")

        with self.assertRaises(Exception):
            ImplementationAttemptModel.get_stats(days=7)


# 恢复 sys.modules
if _saved_db is not None:
    sys.modules['model.database'] = _saved_db
else:
    sys.modules.pop('model.database', None)


if __name__ == '__main__':
    unittest.main()
