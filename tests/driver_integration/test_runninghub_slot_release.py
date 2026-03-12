"""
RunningHub 槽位释放集成测试

测试场景：
1. 任务提交失败时，槽位是否正确释放
2. 任务提交成功但后续失败时，槽位是否正确释放
3. 任务完成时，槽位是否正确释放
"""
import sys
import asyncio
from unittest.mock import patch, MagicMock

sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.visual_task import _submit_new_task
from model.ai_tools import AIToolsModel
from model.tasks import TasksModel
from model.runninghub_slots import RunningHubSlotsModel
from config.constant import (
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
    AI_TOOL_STATUS_FAILED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_FAILED
)

LTX2_IMAGE_TO_VIDEO_TYPE = 10
WAN22_IMAGE_TO_VIDEO_TYPE = 11
DIGITAL_HUMAN_TYPE = 13


class TestRunningHubSlotRelease(BaseVideoDriverTest):
    """RunningHub 槽位释放集成测试"""

    def setUp(self):
        """测试前准备"""
        super().setUp()

    def _create_task_with_slot(self, ai_tool_type):
        """
        创建任务并获取槽位
        
        Returns:
            tuple: (task_id, task_table_id)
        """
        # 创建 AI Tool
        task_id = self.create_test_ai_tool(
            ai_tool_type=ai_tool_type,
            prompt='测试提示词',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PENDING
        )
        
        # 创建 Task
        task = TasksModel.get_by_task_id(task_id)
        task_table_id = task.id
        
        # 获取槽位
        slot_acquired = RunningHubSlotsModel.try_acquire_slot(
            task_table_id=task_table_id,
            task_id=task_id,
            task_type=ai_tool_type
        )
        
        self.assertTrue(slot_acquired, "槽位获取失败")
        
        # 验证槽位已被占用
        active_slots = RunningHubSlotsModel.count_active_slots()
        self.assertEqual(active_slots, 1, "活跃槽位数量应为1")
        
        return task_id, task_table_id

    def test_slot_release_on_submit_failure_ltx2(self):
        """测试 LTX2 任务提交失败时槽位释放"""
        task_id, task_table_id = self._create_task_with_slot(LTX2_IMAGE_TO_VIDEO_TYPE)
        
        # Mock 驱动的 submit_task 返回失败（用户错误，不重试）
        with patch('task.visual_drivers.ltx2_runninghub_v1_driver.Ltx2RunninghubV1Driver.submit_task') as mock_submit:
            mock_submit.return_value = {
                "success": False,
                "error": "API Key not supported for free users",
                "error_type": "USER",
                "retry": False
            }
            
            # 执行任务提交
            ai_tool = AIToolsModel.get_by_id(task_id)
            result = asyncio.run(_submit_new_task(ai_tool))
            
            # 验证任务失败
            self.assertTrue(result, "任务应该被标记为已处理（失败）")
            
            # 验证任务状态
            updated_tool = AIToolsModel.get_by_id(task_id)
            self.assertEqual(updated_tool.status, AI_TOOL_STATUS_FAILED)
            
            updated_task = TasksModel.get_by_task_id(task_id)
            self.assertEqual(updated_task.status, TASK_STATUS_FAILED)
            
            # 验证槽位已释放
            active_slots = RunningHubSlotsModel.count_active_slots()
            self.assertEqual(active_slots, 0, "槽位应该已被释放")

    def test_slot_release_on_submit_failure_wan22(self):
        """测试 Wan22 任务提交失败时槽位释放"""
        task_id, task_table_id = self._create_task_with_slot(WAN22_IMAGE_TO_VIDEO_TYPE)
        
        # Mock 驱动的 submit_task 返回失败
        with patch('task.visual_drivers.wan22_runninghub_v1_driver.Wan22RunninghubV1Driver.submit_task') as mock_submit:
            mock_submit.return_value = {
                "success": False,
                "error": "Invalid API Key",
                "error_type": "USER",
                "retry": False
            }
            
            # 执行任务提交
            ai_tool = AIToolsModel.get_by_id(task_id)
            result = asyncio.run(_submit_new_task(ai_tool))
            
            # 验证槽位已释放
            active_slots = RunningHubSlotsModel.count_active_slots()
            self.assertEqual(active_slots, 0, "槽位应该已被释放")

    def test_slot_release_on_submit_failure_digital_human(self):
        """测试数字人任务提交失败时槽位释放"""
        task_id, task_table_id = self._create_task_with_slot(DIGITAL_HUMAN_TYPE)
        
        # Mock 驱动的 submit_task 返回失败
        with patch('task.visual_drivers.digital_human_runninghub_v1_driver.DigitalHumanRunninghubV1Driver.submit_task') as mock_submit:
            mock_submit.return_value = {
                "success": False,
                "error": "Quota exceeded",
                "error_type": "USER",
                "retry": False
            }
            
            # 执行任务提交
            ai_tool = AIToolsModel.get_by_id(task_id)
            result = asyncio.run(_submit_new_task(ai_tool))
            
            # 验证槽位已释放
            active_slots = RunningHubSlotsModel.count_active_slots()
            self.assertEqual(active_slots, 0, "槽位应该已被释放")

    def test_slot_not_released_on_retry(self):
        """测试需要重试的失败不释放槽位"""
        task_id, task_table_id = self._create_task_with_slot(LTX2_IMAGE_TO_VIDEO_TYPE)
        
        # Mock 驱动的 submit_task 返回网络错误（需要重试）
        with patch('task.visual_drivers.ltx2_runninghub_v1_driver.Ltx2RunninghubV1Driver.submit_task') as mock_submit:
            mock_submit.return_value = {
                "success": False,
                "error": "网络连接异常，请稍后重试",
                "error_type": "USER",
                "retry": True
            }
            
            # 执行任务提交
            ai_tool = AIToolsModel.get_by_id(task_id)
            result = asyncio.run(_submit_new_task(ai_tool))
            
            # 验证任务未完成（需要重试）
            self.assertFalse(result, "任务应该返回 False 表示需要重试")
            
            # 验证槽位未释放（因为需要重试）
            active_slots = RunningHubSlotsModel.count_active_slots()
            self.assertEqual(active_slots, 1, "槽位不应该被释放（任务需要重试）")

    def test_slot_update_on_submit_success(self):
        """测试任务提交成功时槽位更新 project_id"""
        task_id, task_table_id = self._create_task_with_slot(LTX2_IMAGE_TO_VIDEO_TYPE)
        
        # Mock 驱动的 submit_task 返回成功
        project_id = "test_project_123"
        with patch('task.visual_drivers.ltx2_runninghub_v1_driver.Ltx2RunninghubV1Driver.submit_task') as mock_submit:
            mock_submit.return_value = {
                "success": True,
                "project_id": project_id
            }
            
            # 执行任务提交
            ai_tool = AIToolsModel.get_by_id(task_id)
            result = asyncio.run(_submit_new_task(ai_tool))
            
            # 验证任务成功
            self.assertTrue(result, "任务应该提交成功")
            
            # 验证任务状态
            updated_tool = AIToolsModel.get_by_id(task_id)
            self.assertEqual(updated_tool.status, AI_TOOL_STATUS_PROCESSING)
            self.assertEqual(updated_tool.project_id, project_id)
            
            # 验证槽位仍然活跃但已更新 project_id
            active_slots = RunningHubSlotsModel.count_active_slots()
            self.assertEqual(active_slots, 1, "槽位应该仍然活跃")
            
            # 验证槽位的 project_id 已更新
            from model.runninghub_slots import execute_query
            slot = execute_query(
                "SELECT * FROM runninghub_slots WHERE task_table_id = %s",
                (task_table_id,),
                fetch_one=True
            )
            self.assertEqual(slot['project_id'], project_id, "槽位的 project_id 应该已更新")

    def test_multiple_tasks_slot_management(self):
        """测试多个任务的槽位管理"""
        # 创建第一个任务并获取槽位
        task_id_1, _ = self._create_task_with_slot(LTX2_IMAGE_TO_VIDEO_TYPE)
        
        # 创建第二个任务并获取槽位
        task_id_2, _ = self._create_task_with_slot(WAN22_IMAGE_TO_VIDEO_TYPE)
        
        # 验证有2个活跃槽位
        active_slots = RunningHubSlotsModel.count_active_slots()
        self.assertEqual(active_slots, 2, "应该有2个活跃槽位")
        
        # Mock 第一个任务提交失败
        with patch('task.visual_drivers.ltx2_runninghub_v1_driver.Ltx2RunninghubV1Driver.submit_task') as mock_submit:
            mock_submit.return_value = {
                "success": False,
                "error": "API Key error",
                "error_type": "USER",
                "retry": False
            }
            
            ai_tool_1 = AIToolsModel.get_by_id(task_id_1)
            asyncio.run(_submit_new_task(ai_tool_1))
        
        # 验证只剩1个活跃槽位
        active_slots = RunningHubSlotsModel.count_active_slots()
        self.assertEqual(active_slots, 1, "应该只剩1个活跃槽位")
        
        # Mock 第二个任务提交成功
        with patch('task.visual_drivers.wan22_runninghub_v1_driver.Wan22RunninghubV1Driver.submit_task') as mock_submit:
            mock_submit.return_value = {
                "success": True,
                "project_id": "test_project_456"
            }
            
            ai_tool_2 = AIToolsModel.get_by_id(task_id_2)
            asyncio.run(_submit_new_task(ai_tool_2))
        
        # 验证仍然有1个活跃槽位
        active_slots = RunningHubSlotsModel.count_active_slots()
        self.assertEqual(active_slots, 1, "应该仍然有1个活跃槽位")


if __name__ == '__main__':
    import unittest
    unittest.main()
