"""
Wan2.2 RunningHub 驱动数据库集成测试
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['runninghub_request'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.wan22_runninghub_v1_driver import Wan22RunninghubV1Driver


class TestWan22DriverWithDB(BaseVideoDriverTest):
    """Wan2.2 驱动数据库集成测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.driver = Wan22RunninghubV1Driver()
        
        self.test_ai_tool_id = self.create_test_ai_tool(
            ai_tool_type=13,
            prompt='生成动画视频',
            image_path='https://example.com/wan22_image.jpg',
            duration=5
        )
    
    def test_driver_initialization(self):
        """测试驱动初始化"""
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'wan22_runninghub_v1')
    
    def test_create_wan22_task(self):
        """测试创建 Wan2.2 任务记录"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=13,
            prompt='测试 Wan2.2',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=0
        )
        
        result = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE id = %s AND type = %s",
            (task_id, 13)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['type'], 13)


if __name__ == '__main__':
    import unittest
    unittest.main()
