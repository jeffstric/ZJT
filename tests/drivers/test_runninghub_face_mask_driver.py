"""
RunningHubFaceMaskDriver 静态方法单元测试

测试 _parse_submit_response、_handle_submit_error、_extract_result_url 三个静态方法，
以及 RunningHubFaceMaskConfig 常量。
依赖 stub 通过 tests/base/test_isolation.py 官方工具安装并恢复。
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from tests.base.test_isolation import stub_modules

# Mock 外部依赖（在 import 之前）
# 注意：不 mock httpx 和 utils.logger_config，让 base_async_driver 正常导入
# 只 mock 需要外部连接的依赖
# 注意：不能 mock task.async_drivers.base_async_driver，
# 否则 RunningHubFaceMaskDriver 会变成 Mock 对象，静态方法丢失
with stub_modules({
    'api.clients.runninghub_client': MagicMock(),
    'config.config_util': MagicMock(),
    'utils.file_storage': MagicMock(),
}):
    from task.async_drivers.runninghub_face_mask_driver import (
        RunningHubFaceMaskDriver,
        RunningHubFaceMaskConfig,
    )


class TestParseSubmitResponse(unittest.TestCase):
    """测试 _parse_submit_response 静态方法"""

    def test_valid_response_with_task_id(self):
        """正常响应包含 taskId 时返回成功结果"""
        response = {'taskId': 'abc-123-def'}
        result = RunningHubFaceMaskDriver._parse_submit_response(response)

        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'abc-123-def')

    def test_missing_task_id(self):
        """响应缺少 taskId 时返回失败结果，使用默认错误信息"""
        response = {'status': 'error'}
        result = RunningHubFaceMaskDriver._parse_submit_response(response)

        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'RunningHub 未返回任务 ID')
        self.assertEqual(result['error_type'], 'SYSTEM')
        self.assertFalse(result['retry'])

    def test_error_message_included(self):
        """响应包含 errorMessage 时使用该错误信息"""
        response = {'errorMessage': 'APP 不存在'}
        result = RunningHubFaceMaskDriver._parse_submit_response(response)

        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'APP 不存在')
        self.assertIn('error_detail', result)

    def test_empty_response(self):
        """空响应返回失败结果"""
        response = {}
        result = RunningHubFaceMaskDriver._parse_submit_response(response)

        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'RunningHub 未返回任务 ID')


class TestHandleSubmitError(unittest.TestCase):
    """测试 _handle_submit_error 静态方法"""

    def test_connection_error(self):
        """ConnectionError 返回网络连接异常，标记为 USER 错误且可重试"""
        e = ConnectionError("Connection refused")
        result = RunningHubFaceMaskDriver._handle_submit_error(e)

        self.assertFalse(result['success'])
        self.assertIn('网络连接异常', result['error'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertTrue(result['retry'])

    def test_timeout_error(self):
        """TimeoutError 返回请求超时，标记为 USER 错误且可重试"""
        e = TimeoutError("Request timed out after 30s")
        result = RunningHubFaceMaskDriver._handle_submit_error(e)

        self.assertFalse(result['success'])
        self.assertIn('请求超时', result['error'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertTrue(result['retry'])

    def test_generic_exception(self):
        """普通异常返回系统错误，包含异常信息，不可重试"""
        e = RuntimeError("Unexpected error")
        result = RunningHubFaceMaskDriver._handle_submit_error(e)

        self.assertFalse(result['success'])
        self.assertIn('提交人脸遮盖视频任务失败', result['error'])
        self.assertIn('Unexpected error', result['error'])
        self.assertEqual(result['error_type'], 'SYSTEM')
        self.assertFalse(result['retry'])
        self.assertIn('error_detail', result)


class TestExtractResultUrl(unittest.TestCase):
    """测试 _extract_result_url 静态方法"""

    def test_results_with_url(self):
        """results 列表包含 url 时返回第一个 url"""
        response_data = {
            'results': [
                {'url': 'https://example.com/video1.mp4'},
                {'url': 'https://example.com/video2.mp4'},
            ]
        }
        result = RunningHubFaceMaskDriver._extract_result_url(response_data)

        self.assertEqual(result, 'https://example.com/video1.mp4')

    def test_empty_results_list(self):
        """results 为空列表时返回 None"""
        response_data = {'results': []}
        result = RunningHubFaceMaskDriver._extract_result_url(response_data)

        self.assertIsNone(result)

    def test_none_results(self):
        """results 为 None 时返回 None"""
        response_data = {'results': None}
        result = RunningHubFaceMaskDriver._extract_result_url(response_data)

        self.assertIsNone(result)

    def test_results_without_url_key(self):
        """results 中的项不包含 url 键时返回 None"""
        response_data = {
            'results': [
                {'filename': 'video.mp4', 'size': 1024},
            ]
        }
        result = RunningHubFaceMaskDriver._extract_result_url(response_data)

        self.assertIsNone(result)

    def test_multiple_results_first_wins(self):
        """多个 results 时返回第一个包含非空 url 的项"""
        response_data = {
            'results': [
                {'url': ''},
                {'url': 'https://example.com/second.mp4'},
                {'url': 'https://example.com/third.mp4'},
            ]
        }
        result = RunningHubFaceMaskDriver._extract_result_url(response_data)

        # 第一个 url 为空字符串，falsy，应跳过，返回第二个
        self.assertEqual(result, 'https://example.com/second.mp4')


class TestRunningHubFaceMaskConfig(unittest.TestCase):
    """测试 RunningHubFaceMaskConfig 常量"""

    def test_app_id_is_string(self):
        """APP_ID 应为非空字符串"""
        self.assertIsInstance(RunningHubFaceMaskConfig.APP_ID, str)
        self.assertTrue(len(RunningHubFaceMaskConfig.APP_ID) > 0)

    def test_video_node_id(self):
        """VIDEO_NODE_ID 应为字符串 '3'"""
        self.assertEqual(RunningHubFaceMaskConfig.VIDEO_NODE_ID, '3')

    def test_video_field_name(self):
        """VIDEO_FIELD_NAME 应为字符串 'video'"""
        self.assertEqual(RunningHubFaceMaskConfig.VIDEO_FIELD_NAME, 'video')

    def test_final_statuses_contains_key_values(self):
        """FINAL_STATUSES 应包含 SUCCESS、FAILED、ERROR 等终态"""
        statuses = RunningHubFaceMaskConfig.FINAL_STATUSES
        self.assertIn('SUCCESS', statuses)
        self.assertIn('FAILED', statuses)
        self.assertIn('ERROR', statuses)
        self.assertIsInstance(statuses, tuple)


class TestNormalizeBeforeUpload(unittest.TestCase):
    """测试 _normalize_before_upload：上传 RunningHub 前的 CFR 归一化"""

    def _new_driver(self, local_path):
        # 绕过 __init__（避免依赖配置/客户端初始化），仅测试该方法
        driver = RunningHubFaceMaskDriver.__new__(RunningHubFaceMaskDriver)
        driver._storage = MagicMock()
        driver._storage.resolve_to_local_file.return_value = local_path
        return driver

    def test_returns_none_when_not_mappable(self):
        """URL/路径无法映射到本地文件时返回 None"""
        driver = self._new_driver(None)
        self.assertIsNone(driver._normalize_before_upload('http://example.com/a.webm'))

    @patch('utils.face_mask_util._normalize_video_to_cfr', return_value=True)
    def test_returns_temp_file_on_success(self, mock_normalize):
        """归一化成功时返回临时文件路径"""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as f:
            src = f.name
        driver = self._new_driver(src)
        try:
            temp_path = driver._normalize_before_upload(src)
            self.assertIsNotNone(temp_path)
            self.assertTrue(os.path.exists(temp_path))
            self.assertTrue(temp_path.endswith('.cfr.mp4'))
            os.remove(temp_path)
        finally:
            os.remove(src)

    @patch('utils.face_mask_util._normalize_video_to_cfr', return_value=False)
    def test_returns_none_and_cleans_up_on_failure(self, mock_normalize):
        """归一化失败时返回 None 且不留临时文件"""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as f:
            src = f.name
        driver = self._new_driver(src)
        try:
            self.assertIsNone(driver._normalize_before_upload(src))
        finally:
            os.remove(src)

    @patch('utils.face_mask_util._normalize_video_to_cfr', side_effect=Exception('boom'))
    def test_returns_none_on_exception(self, mock_normalize):
        """归一化异常时返回 None 而不抛出"""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as f:
            src = f.name
        driver = self._new_driver(src)
        try:
            self.assertIsNone(driver._normalize_before_upload(src))
        finally:
            os.remove(src)

    def test_returns_none_when_mapping_raises(self):
        """路径映射异常时返回 None 而不抛出"""
        driver = RunningHubFaceMaskDriver.__new__(RunningHubFaceMaskDriver)
        driver._storage = MagicMock()
        driver._storage.resolve_to_local_file.side_effect = Exception('boom')
        self.assertIsNone(driver._normalize_before_upload('/any/path.webm'))


if __name__ == '__main__':
    unittest.main()
