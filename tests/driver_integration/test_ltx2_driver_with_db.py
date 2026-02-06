"""
LTX2 RunningHub 驱动数据库集成测试
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['runninghub_request'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.ltx2_runninghub_v1_driver import Ltx2RunninghubV1Driver


class TestLTX2DriverWithDB(BaseVideoDriverTest):
    """LTX2 驱动数据库集成测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.driver = Ltx2RunninghubV1Driver()
        
        self.test_ai_tool_id = self.create_test_ai_tool(
            ai_tool_type=10,
            prompt='生成流畅的视频动画',
            image_path='https://example.com/ltx2_image.jpg',
            duration=5
        )
    
    @patch('task.video_drivers.ltx2_runninghub_v1_driver.create_ltx2_image_to_video')
    def test_submit_task_success(self, mock_create_video):
        """测试成功提交 LTX2 任务"""
        mock_create_video.return_value = {
            'taskId': 'ltx2_task_12345',
            'status': 'QUEUED'
        }
        
        ai_tool = self.get_ai_tool_from_db(self.test_ai_tool_id)
        result = self.driver.submit_task(ai_tool)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'ltx2_task_12345')
        
        mock_create_video.assert_called_once()
        call_kwargs = mock_create_video.call_args[1]
        self.assertEqual(call_kwargs['image_url'], 'https://example.com/ltx2_image.jpg')
        self.assertEqual(call_kwargs['duration'], 5)
    
    @patch('task.video_drivers.ltx2_runninghub_v1_driver.create_ltx2_image_to_video')
    def test_submit_task_queue_maxed(self, mock_create_video):
        """测试队列已满的情况"""
        mock_create_video.return_value = {
            'errorCode': 'TASK_QUEUE_MAXED',
            'errorMessage': 'TASK_QUEUE_MAXED'
        }
        
        ai_tool = self.get_ai_tool_from_db(self.test_ai_tool_id)
        result = self.driver.submit_task(ai_tool)
        
        self.assertFalse(result['success'])
        self.assertIn('error', result)
    
    @patch('task.video_drivers.ltx2_runninghub_v1_driver.check_ltx2_task_status')
    def test_check_status_success(self, mock_check_status):
        """测试检查任务状态 - 成功"""
        mock_check_status.return_value = {
            'status': 'SUCCESS',
            'results': [
                type('Result', (), {'file_url': 'https://example.com/ltx2_result.mp4'})()
            ]
        }
        
        result = self.driver.check_status('ltx2_task_12345')
        
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/ltx2_result.mp4')
    
    @patch('task.video_drivers.ltx2_runninghub_v1_driver.check_ltx2_task_status')
    def test_check_status_running(self, mock_check_status):
        """测试检查任务状态 - 运行中"""
        mock_check_status.return_value = {
            'status': 'RUNNING'
        }
        
        result = self.driver.check_status('ltx2_task_12345')
        
        self.assertEqual(result['status'], 'RUNNING')
    
    @patch('task.video_drivers.ltx2_runninghub_v1_driver.check_ltx2_task_status')
    def test_check_status_failed(self, mock_check_status):
        """测试检查任务状态 - 失败"""
        mock_check_status.return_value = {
            'status': 'FAILED'
        }
        
        result = self.driver.check_status('ltx2_task_12345')
        
        self.assertEqual(result['status'], 'FAILED')
    
    def test_create_and_query_ltx2_task(self):
        """测试创建和查询 LTX2 任务"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=10,
            prompt='测试 LTX2 任务',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=0
        )
        
        result = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE id = %s AND type = %s",
            (task_id, 10)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['type'], 10)
        self.assertEqual(result[0]['status'], 0)


if __name__ == '__main__':
    import unittest
    unittest.main()
