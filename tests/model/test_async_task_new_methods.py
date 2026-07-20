"""
AsyncTask 新增方法单元测试

测试 model/async_tasks.py 中新增的方法（带重试和状态管理逻辑）：
- create_and_schedule: 创建异步任务并立即可被调度器拾取
- schedule_retry: 安排任务重试（指数退避）
- get_ready_to_retry_tasks: 获取可重试的任务
- update_external_task_id: 更新外部任务 ID
- mark_submitted: 原子记录提交成功状态并退出重试队列
- update_status_with_retry: 更新状态并可选重置重试计数

注意：因为 model.async_tasks 可能已被其他模块缓存，
所以使用 importlib.reload 确保使用 mock 的 database。
"""
import importlib
import json
import sys
import unittest
from unittest.mock import MagicMock

# 保存原始模块引用，防止污染后续测试
_saved_model_database = sys.modules.get('model.database')

# Mock 数据库依赖（模块级 import 会触发）
mock_db = MagicMock()
sys.modules['model.database'] = mock_db

# 强制重新加载 async_tasks 模块，确保使用 mock 的 database
if 'model.async_tasks' in sys.modules:
    importlib.reload(sys.modules['model.async_tasks'])

from model.async_tasks import AsyncTasksModel, AsyncTaskStatus, AsyncTask

# 获取 async_tasks 模块内实际使用的 execute_insert/execute_update/execute_query 引用
_async_tasks_module = sys.modules['model.async_tasks']

# 恢复 model.database，防止污染后续测试
if _saved_model_database is not None:
    sys.modules['model.database'] = _saved_model_database
else:
    sys.modules.pop('model.database', None)


class TestAsyncTaskCreateAndSchedule(unittest.TestCase):
    """测试 AsyncTasksModel.create_and_schedule()"""

    def setUp(self):
        _async_tasks_module.execute_insert.reset_mock()
        _async_tasks_module.execute_insert.return_value = 1

    def test_creates_with_now_retry_time(self):
        """验证 SQL 使用 NOW() 设置 next_retry_at"""
        result = AsyncTasksModel.create_and_schedule(
            implementation=1,
            user_id=42,
            params={"video_path": "/tmp/test.mp4"},
        )

        self.assertEqual(result, 1)
        _async_tasks_module.execute_insert.assert_called_once()
        call_args = _async_tasks_module.execute_insert.call_args
        sql = call_args[0][0]
        db_params = call_args[0][1]

        self.assertIn('INSERT INTO async_tasks', sql)
        self.assertIn('NOW()', sql)
        self.assertEqual(db_params[0], 1)   # implementation
        self.assertEqual(db_params[1], 42)  # user_id
        self.assertEqual(db_params[2], json.dumps({"video_path": "/tmp/test.mp4"}))
        self.assertEqual(db_params[3], AsyncTaskStatus.QUEUED)
        self.assertEqual(db_params[4], 60)  # max_attempts

    def test_default_max_retries(self):
        """默认 max_retries 为 5"""
        AsyncTasksModel.create_and_schedule(implementation=1, user_id=1)

        call_args = _async_tasks_module.execute_insert.call_args
        db_params = call_args[0][1]
        self.assertEqual(db_params[5], 5)

    def test_custom_max_retries(self):
        """自定义 max_retries 传入后正确使用"""
        AsyncTasksModel.create_and_schedule(implementation=1, user_id=1, max_retries=10)

        call_args = _async_tasks_module.execute_insert.call_args
        db_params = call_args[0][1]
        self.assertEqual(db_params[5], 10)


class TestAsyncTaskScheduleRetry(unittest.TestCase):
    """测试 AsyncTasksModel.schedule_retry()"""

    def setUp(self):
        _async_tasks_module.execute_update.reset_mock()
        _async_tasks_module.execute_update.return_value = 1

    def test_increments_retry_count(self):
        """SQL 包含 retry_count = retry_count + 1"""
        AsyncTasksModel.schedule_retry(1, delay_seconds=60)

        call_args = _async_tasks_module.execute_update.call_args
        sql = call_args[0][0]
        self.assertIn('retry_count = retry_count + 1', sql)
        self.assertIn('next_retry_at = %s', sql)

    def test_sets_next_retry_at(self):
        """next_retry_at 参数基于当前时间加上 delay_seconds"""
        AsyncTasksModel.schedule_retry(record_id=5, delay_seconds=120)

        call_args = _async_tasks_module.execute_update.call_args
        params = call_args[0][1]
        self.assertEqual(params[1], 5)  # record_id


class TestAsyncTaskGetReadyToRetryTasks(unittest.TestCase):
    """测试 AsyncTasksModel.get_ready_to_retry_tasks()"""

    def setUp(self):
        _async_tasks_module.execute_query.reset_mock()

    def test_returns_matching_tasks(self):
        """返回符合条件的任务列表"""
        _async_tasks_module.execute_query.return_value = [
            {'id': 1, 'implementation': 1, 'external_task_id': None, 'user_id': 1,
             'params': None, 'status': 0, 'try_count': 0, 'max_attempts': 60,
             'error_message': None, 'result_url': None, 'result_data': None,
             'created_at': None, 'updated_at': None, 'completed_at': None,
             'failed_at': None, 'retry_count': 1, 'next_retry_at': None, 'max_retries': 5},
        ]

        result = AsyncTasksModel.get_ready_to_retry_tasks()

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AsyncTask)
        self.assertEqual(result[0].id, 1)
        call_args = _async_tasks_module.execute_query.call_args
        sql = call_args[0][0]
        self.assertIn('next_retry_at <= NOW()', sql)
        self.assertIn('retry_count < max_retries', sql)

    def test_returns_empty_list(self):
        """无匹配时返回空列表"""
        _async_tasks_module.execute_query.return_value = None

        result = AsyncTasksModel.get_ready_to_retry_tasks()

        self.assertEqual(result, [])


class TestAsyncTaskUpdateExternalTaskId(unittest.TestCase):
    """测试 AsyncTasksModel.update_external_task_id()"""

    def setUp(self):
        _async_tasks_module.execute_update.reset_mock()
        _async_tasks_module.execute_update.return_value = 1

    def test_updates_correctly(self):
        """正确更新 external_task_id"""
        result = AsyncTasksModel.update_external_task_id(1, 'ext-task-abc')

        self.assertEqual(result, 1)
        call_args = _async_tasks_module.execute_update.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        self.assertIn('external_task_id = %s', sql)
        self.assertEqual(params, ('ext-task-abc', 1))


class TestAsyncTaskMarkSubmitted(unittest.TestCase):
    """测试提交成功后的原子状态转换。"""

    def setUp(self):
        _async_tasks_module.execute_update.reset_mock()
        _async_tasks_module.execute_update.return_value = 1

    def test_marks_processing_and_clears_retry_schedule_atomically(self):
        """一次 UPDATE 同时写入外部 ID、PROCESSING 状态并退出重试队列。"""
        self.assertTrue(
            hasattr(AsyncTasksModel, 'mark_submitted'),
            'AsyncTasksModel.mark_submitted must atomically finalize submission',
        )

        result = AsyncTasksModel.mark_submitted(1, 'ext-task-abc')

        self.assertEqual(result, 1)
        _async_tasks_module.execute_update.assert_called_once()
        sql, params = _async_tasks_module.execute_update.call_args.args
        self.assertIn('external_task_id = %s', sql)
        self.assertIn('status = %s', sql)
        self.assertIn('next_retry_at = NULL', sql)
        self.assertEqual(params, ('ext-task-abc', AsyncTaskStatus.PROCESSING, 1))


class TestAsyncTaskUpdateStatusWithRetry(unittest.TestCase):
    """测试 AsyncTasksModel.update_status_with_retry()"""

    def setUp(self):
        _async_tasks_module.execute_update.reset_mock()
        _async_tasks_module.execute_update.return_value = 1

    def test_reset_retry_true(self):
        """reset_retry=True 时 SQL 包含 retry_count=0 和 next_retry_at=NULL"""
        AsyncTasksModel.update_status_with_retry(1, AsyncTaskStatus.QUEUED, reset_retry=True)

        call_args = _async_tasks_module.execute_update.call_args
        sql = call_args[0][0]
        self.assertIn('retry_count = 0', sql)
        self.assertIn('next_retry_at = NULL', sql)

    def test_reset_retry_false(self):
        """reset_retry=False 时不包含 retry 字段"""
        AsyncTasksModel.update_status_with_retry(1, AsyncTaskStatus.PROCESSING, reset_retry=False)

        call_args = _async_tasks_module.execute_update.call_args
        sql = call_args[0][0]
        self.assertNotIn('retry_count = 0', sql)
        self.assertNotIn('next_retry_at = NULL', sql)

    def test_completed_sets_completed_at(self):
        """状态为 COMPLETED 时设置 completed_at = NOW()"""
        AsyncTasksModel.update_status_with_retry(1, AsyncTaskStatus.COMPLETED)

        call_args = _async_tasks_module.execute_update.call_args
        sql = call_args[0][0]
        self.assertIn('completed_at = NOW()', sql)

    def test_failed_sets_failed_at(self):
        """状态为 FAILED 时设置 failed_at = NOW()"""
        AsyncTasksModel.update_status_with_retry(1, AsyncTaskStatus.FAILED)

        call_args = _async_tasks_module.execute_update.call_args
        sql = call_args[0][0]
        self.assertIn('failed_at = NOW()', sql)

    def test_timeout_sets_failed_at(self):
        """状态为 TIMEOUT 时也设置 failed_at = NOW()"""
        AsyncTasksModel.update_status_with_retry(1, AsyncTaskStatus.TIMEOUT)

        call_args = _async_tasks_module.execute_update.call_args
        sql = call_args[0][0]
        self.assertIn('failed_at = NOW()', sql)

    def test_with_error_message_and_result_url(self):
        """同时传入 error_message 和 result_url"""
        AsyncTasksModel.update_status_with_retry(
            1, AsyncTaskStatus.FAILED,
            error_message='Connection refused',
            result_url='http://example.com/result.mp4',
        )

        call_args = _async_tasks_module.execute_update.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        self.assertIn('error_message = %s', sql)
        self.assertIn('result_url = %s', sql)
        self.assertIn('Connection refused', params)
        self.assertIn('http://example.com/result.mp4', params)


if __name__ == '__main__':
    unittest.main()
