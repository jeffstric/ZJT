"""
Seedream 算力返还集成测试

测试场景：
1. Seedream 任务提交失败时，算力是否正确返还
2. Seedream 任务提交异常时，算力是否正确返还
3. 需要重试的网络错误不会触发返还
"""
import sys
import asyncio
from unittest.mock import patch, MagicMock

sys.modules['utils.sentry_util'] = MagicMock()
sys.modules['aiofiles'] = MagicMock()
sys.modules['aiohttp'] = MagicMock()

import task.visual_drivers.seedream_volcengine_v1_driver  # noqa: F401 — 使 mock 路径可解析
from tests.base.base_video_driver_test import BaseVideoDriverTest
from task.visual_task import _submit_new_task, _refund_computing_power
from model.ai_tools import AIToolsModel
from model.tasks import TasksModel
from config.constant import (
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_FAILED,
    TASK_STATUS_FAILED,
    TaskTypeId
)
from perseids_server.client import make_perseids_request

SEEDREAM_TEXT_TO_IMAGE_TYPE = TaskTypeId.SEEDREAM_TEXT_TO_IMAGE


class TestSeedreamComputingPowerRefund(BaseVideoDriverTest):
    """Seedream 算力返还集成测试"""

    def setUp(self):
        """测试前准备"""
        super().setUp()

    def _create_seedream_task(self):
        """
        创建 Seedream 测试任务

        Returns:
            int: AI 工具 ID
        """
        task_id = self.create_test_ai_tool(
            ai_tool_type=SEEDREAM_TEXT_TO_IMAGE_TYPE,
            prompt='测试提示词',
            status=AI_TOOL_STATUS_PENDING
        )
        # 创建 Task 记录（_submit_new_task 需要 task 记录存在）
        from config.constant import TASK_TYPE_GENERATE_VIDEO
        self.create_test_task(TASK_TYPE_GENERATE_VIDEO, task_id)
        return task_id

    def test_refund_on_submit_user_error(self):
        """测试提交失败（用户错误）时算力返还"""
        task_id = self._create_seedream_task()

        # 创建 Mock 驱动实例
        mock_driver = MagicMock()
        mock_driver.driver_name = 'seedream5_volcengine_v1'

        # Mock VideoDriverFactory.create_driver_by_type 返回 mock 驱动
        with patch('task.visual_drivers.driver_factory.VideoDriverFactory.create_driver_by_type') as mock_create:
            mock_create.return_value = mock_driver

            # Mock 驱动的 submit_task 返回失败（用户错误，不重试）
            mock_driver.submit_task.return_value = {
                "success": False,
                "error": "API 错误 [InvalidAPIKey]: Invalid API key provided",
                "error_type": "USER",
                "retry": False
            }

            # Mock perseids 请求以追踪返还调用
            with patch('task.visual_task.make_perseids_request') as mock_perseids:
                # 模拟获取 auth token 成功
                mock_perseids.return_value = (True, "success", {"token": "mock_token_123"})

                # 执行任务提交
                ai_tool = AIToolsModel.get_by_id(task_id)
                result = asyncio.run(_submit_new_task(ai_tool))

                # 验证任务被标记为已处理（失败）
                self.assertTrue(result, "任务应该被标记为已处理（失败）")

                # 验证任务状态为失败
                updated_tool = AIToolsModel.get_by_id(task_id)
                self.assertEqual(updated_tool.status, AI_TOOL_STATUS_FAILED)

                updated_task = TasksModel.get_by_task_id(task_id)
                self.assertEqual(updated_task.status, TASK_STATUS_FAILED)

                # 验证算力返还被调用（至少一次获取 token + 一次返还）
                # make_perseids_request 被调用次数应该 >= 2
                self.assertGreaterEqual(mock_perseids.call_count, 2,
                    "算力返还需要调用 get_auth_token_by_user_id 和 user/calculate_computing_power")

                # 验证返还调用的参数
                calls = mock_perseids.call_args_list
                # 第一次调用：获取 token
                self.assertEqual(calls[0][1]['endpoint'], 'get_auth_token_by_user_id')
                # 第二次调用：增加算力（返还）
                self.assertEqual(calls[1][1]['endpoint'], 'user/calculate_computing_power')
                self.assertEqual(calls[1][1]['data']['behavior'], 'increase')
                self.assertEqual(calls[1][1]['data']['computing_power'], 6)  # Seedream 5.0 算力

    def test_refund_on_submit_system_error(self):
        """测试提交失败（系统错误）时算力返还"""
        task_id = self._create_seedream_task()

        # 创建 Mock 驱动实例
        mock_driver = MagicMock()
        mock_driver.driver_name = 'seedream5_volcengine_v1'

        # Mock VideoDriverFactory.create_driver_by_type 返回 mock 驱动
        with patch('task.visual_drivers.driver_factory.VideoDriverFactory.create_driver_by_type') as mock_create:
            mock_create.return_value = mock_driver

            # Mock 驱动的 submit_task 返回系统错误
            mock_driver.submit_task.return_value = {
                "success": False,
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "retry": False
            }

            with patch('task.visual_task.make_perseids_request') as mock_perseids:
                mock_perseids.return_value = (True, "success", {"token": "mock_token_123"})

                # 执行任务提交
                ai_tool = AIToolsModel.get_by_id(task_id)
                result = asyncio.run(_submit_new_task(ai_tool))

                # 验证任务失败
                self.assertTrue(result, "任务应该被标记为已处理（失败）")

                updated_tool = AIToolsModel.get_by_id(task_id)
                self.assertEqual(updated_tool.status, AI_TOOL_STATUS_FAILED)

                # 验证算力返还被调用
                self.assertGreaterEqual(mock_perseids.call_count, 2)

    def test_refund_on_submit_exception(self):
        """测试提交异常时算力返还"""
        task_id = self._create_seedream_task()

        # 创建 Mock 驱动实例
        mock_driver = MagicMock()
        mock_driver.driver_name = 'seedream5_volcengine_v1'

        # Mock VideoDriverFactory.create_driver_by_type 返回 mock 驱动
        with patch('task.visual_drivers.driver_factory.VideoDriverFactory.create_driver_by_type') as mock_create:
            mock_create.return_value = mock_driver

            # Mock 驱动的 submit_task 抛出异常
            mock_driver.submit_task.side_effect = Exception("Network connection timeout")

            with patch('task.visual_task.make_perseids_request') as mock_perseids:
                mock_perseids.return_value = (True, "success", {"token": "mock_token_123"})

                # 执行任务提交
                ai_tool = AIToolsModel.get_by_id(task_id)
                result = asyncio.run(_submit_new_task(ai_tool))

                # 验证任务失败（返回 False 让上层处理重试逻辑）
                self.assertFalse(result, "异常时应该返回 False（重试）")

                updated_tool = AIToolsModel.get_by_id(task_id)
                self.assertEqual(updated_tool.status, AI_TOOL_STATUS_FAILED)

                # 验证算力返还被调用
                self.assertGreaterEqual(mock_perseids.call_count, 2)

    def test_no_refund_on_retry_error(self):
        """测试需要重试的网络错误不触发算力返还"""
        task_id = self._create_seedream_task()

        # 创建 Mock 驱动实例
        mock_driver = MagicMock()
        mock_driver.driver_name = 'seedream5_volcengine_v1'

        # Mock VideoDriverFactory.create_driver_by_type 返回 mock 驱动
        with patch('task.visual_drivers.driver_factory.VideoDriverFactory.create_driver_by_type') as mock_create:
            mock_create.return_value = mock_driver

            # Mock 驱动的 submit_task 返回需要重试的错误
            mock_driver.submit_task.return_value = {
                "success": False,
                "error": "网络连接异常，请稍后重试",
                "error_type": "USER",
                "retry": True
            }

            with patch('task.visual_task.make_perseids_request') as mock_perseids:
                # 执行任务提交
                ai_tool = AIToolsModel.get_by_id(task_id)
                result = asyncio.run(_submit_new_task(ai_tool))

                # 验证任务返回 False（需要重试）
                self.assertFalse(result, "需要重试的错误应该返回 False")

                # 验证任务状态未变化（仍然是 PENDING）
                updated_tool = AIToolsModel.get_by_id(task_id)
                self.assertEqual(updated_tool.status, AI_TOOL_STATUS_PENDING)

                # 验证算力返还没有被调用（因为任务还没正式开始处理）
                # 只应该有获取 token 的调用，不应该有返还算力的调用
                refund_calls = [c for c in mock_perseids.call_args_list
                               if c[1].get('endpoint') == 'user/calculate_computing_power']
                self.assertEqual(len(refund_calls), 0,
                    "需要重试的错误不应该触发算力返还")

    def test_refund_computing_power_function(self):
        """测试 _refund_computing_power 函数本身"""
        task_id = self._create_seedream_task()
        ai_tool = AIToolsModel.get_by_id(task_id)

        with patch('task.visual_task.make_perseids_request') as mock_perseids:
            mock_perseids.return_value = (True, "success", {"token": "mock_token_123"})

            # 调用 _refund_computing_power
            _refund_computing_power(ai_tool, "测试返还")

            # 验证调用
            self.assertEqual(mock_perseids.call_count, 2)

            # 验证返还参数
            calls = mock_perseids.call_args_list
            self.assertEqual(calls[0][1]['endpoint'], 'get_auth_token_by_user_id')
            self.assertEqual(calls[1][1]['endpoint'], 'user/calculate_computing_power')
            self.assertEqual(calls[1][1]['data']['behavior'], 'increase')
            self.assertEqual(calls[1][1]['data']['computing_power'], 6)  # Seedream 5.0

    def test_refund_on_submit_success_no_refund(self):
        """测试提交成功时不触发返还（成功情况下不返还算力）"""
        task_id = self._create_seedream_task()

        # 创建 Mock 驱动实例
        mock_driver = MagicMock()
        mock_driver.driver_name = 'seedream5_volcengine_v1'

        # Mock VideoDriverFactory.create_driver_by_type 返回 mock 驱动
        with patch('task.visual_drivers.driver_factory.VideoDriverFactory.create_driver_by_type') as mock_create:
            mock_create.return_value = mock_driver

            # Mock 驱动的 submit_task 返回成功
            mock_driver.submit_task.return_value = {
                "success": True,
                "sync_mode": True,
                "result_url": "https://example.com/result.png"
            }

            with patch('task.visual_task.make_perseids_request') as mock_perseids:
                # 模拟 download_and_cache 协程
                async def mock_download(*args):
                    return "https://cdn.example.com/cached.png"

                with patch('utils.media_cache.download_and_cache', side_effect=mock_download):
                    # 执行任务提交
                    ai_tool = AIToolsModel.get_by_id(task_id)
                    result = asyncio.run(_submit_new_task(ai_tool))

                    # 验证任务成功
                    self.assertTrue(result, "任务应该提交成功")

                    # 注意：提交成功时不应该调用 perseids 返还算力
                    # make_perseids_request 不应该被调用（因为成功不会返还）
                    refund_calls = [c for c in mock_perseids.call_args_list
                                   if 'calculate_computing_power' in str(c)]
                    self.assertEqual(len(refund_calls), 0,
                        "提交成功时不应该调用算力返还接口")


if __name__ == '__main__':
    import unittest
    unittest.main()
