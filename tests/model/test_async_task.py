"""
AsyncTask 数据模型单元测试

测试 AsyncTask 的纯数据方法（不涉及数据库操作）：
- get_params_dict: 解析 params 字段
- get_result_data_dict: 解析 result_data 字段
- to_dict: 序列化为字典
"""
import unittest
from datetime import datetime
from unittest.mock import MagicMock

from tests.base.test_isolation import stub_modules

# Mock 数据库依赖（AsyncTask 本身不需要，但模块级 import 会触发）
with stub_modules({'model.database': MagicMock()}):
    from model.async_tasks import AsyncTask, AsyncTaskStatus


class TestAsyncTaskGetParamsDict(unittest.TestCase):
    """测试 AsyncTask.get_params_dict()"""

    def test_dict_input(self):
        """params 已是 dict 时直接返回"""
        task = AsyncTask(params={"key": "value", "num": 42})
        result = task.get_params_dict()
        self.assertEqual(result, {"key": "value", "num": 42})

    def test_json_string_input(self):
        """params 是 JSON 字符串时解析为 dict"""
        task = AsyncTask(params='{"name": "test", "count": 3}')
        result = task.get_params_dict()
        self.assertEqual(result, {"name": "test", "count": 3})

    def test_invalid_json_string(self):
        """params 是非法 JSON 字符串时返回空 dict"""
        task = AsyncTask(params='not valid json {{{')
        result = task.get_params_dict()
        self.assertEqual(result, {})

    def test_none_input(self):
        """params 为 None 时返回空 dict"""
        task = AsyncTask(params=None)
        result = task.get_params_dict()
        self.assertEqual(result, {})

    def test_number_input(self):
        """params 为非 dict/str 类型时返回空 dict"""
        task = AsyncTask(params=12345)
        result = task.get_params_dict()
        self.assertEqual(result, {})

    def test_nested_json(self):
        """params 包含嵌套结构"""
        task = AsyncTask(params='{"character": {"name": "Alice", "age": 25}}')
        result = task.get_params_dict()
        self.assertEqual(result["character"]["name"], "Alice")


class TestAsyncTaskGetResultDataDict(unittest.TestCase):
    """测试 AsyncTask.get_result_data_dict()"""

    def test_dict_input(self):
        task = AsyncTask(result_data={"url": "http://example.com/a.wav"})
        result = task.get_result_data_dict()
        self.assertEqual(result, {"url": "http://example.com/a.wav"})

    def test_json_string_input(self):
        task = AsyncTask(result_data='{"url": "http://example.com/a.wav"}')
        result = task.get_result_data_dict()
        self.assertEqual(result, {"url": "http://example.com/a.wav"})

    def test_invalid_json_string(self):
        task = AsyncTask(result_data='broken{json}')
        result = task.get_result_data_dict()
        self.assertEqual(result, {})

    def test_none_input(self):
        task = AsyncTask(result_data=None)
        result = task.get_result_data_dict()
        self.assertEqual(result, {})


class TestAsyncTaskToDict(unittest.TestCase):
    """测试 AsyncTask.to_dict()"""

    def test_basic_fields(self):
        """基本字段序列化"""
        task = AsyncTask(
            id=1,
            implementation=1,
            external_task_id="ext_123",
            user_id=42,
            params={"key": "value"},
            status=AsyncTaskStatus.QUEUED,
            try_count=0,
            max_attempts=60,
        )
        result = task.to_dict()

        self.assertEqual(result['id'], 1)
        self.assertEqual(result['implementation'], 1)
        self.assertEqual(result['external_task_id'], "ext_123")
        self.assertEqual(result['user_id'], 42)
        self.assertEqual(result['params'], {"key": "value"})
        self.assertEqual(result['status'], AsyncTaskStatus.QUEUED)
        self.assertEqual(result['try_count'], 0)
        self.assertEqual(result['max_attempts'], 60)

    def test_datetime_fields_serialized(self):
        """datetime 字段序列化为 ISO 格式字符串"""
        now = datetime(2026, 5, 22, 10, 30, 0)
        task = AsyncTask(
            created_at=now,
            updated_at=now,
            completed_at=now,
            failed_at=None,
        )
        result = task.to_dict()

        self.assertEqual(result['created_at'], "2026-05-22T10:30:00")
        self.assertEqual(result['updated_at'], "2026-05-22T10:30:00")
        self.assertEqual(result['completed_at'], "2026-05-22T10:30:00")
        self.assertIsNone(result['failed_at'])

    def test_none_datetime_fields(self):
        """None 的 datetime 字段保持 None"""
        task = AsyncTask()
        result = task.to_dict()
        self.assertIsNone(result['created_at'])
        self.assertIsNone(result['updated_at'])
        self.assertIsNone(result['completed_at'])
        self.assertIsNone(result['failed_at'])

    def test_params_json_string_parsed(self):
        """params 为 JSON 字符串时，to_dict 返回解析后的 dict"""
        task = AsyncTask(params='{"character_id": 5, "text": "hello"}')
        result = task.to_dict()
        self.assertEqual(result['params'], {"character_id": 5, "text": "hello"})

    def test_error_message_field(self):
        """error_message 字段正确传递"""
        task = AsyncTask(error_message="Connection timeout")
        result = task.to_dict()
        self.assertEqual(result['error_message'], "Connection timeout")


class TestAsyncTaskStatusConstants(unittest.TestCase):
    """测试状态常量"""

    def test_status_values(self):
        self.assertEqual(AsyncTaskStatus.QUEUED, 0)
        self.assertEqual(AsyncTaskStatus.PROCESSING, 1)
        self.assertEqual(AsyncTaskStatus.COMPLETED, 2)
        self.assertEqual(AsyncTaskStatus.FAILED, -1)
        self.assertEqual(AsyncTaskStatus.TIMEOUT, -2)


if __name__ == '__main__':
    unittest.main()
