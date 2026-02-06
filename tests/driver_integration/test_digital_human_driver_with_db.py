"""
Digital Human RunningHub 驱动数据库集成测试
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['runninghub_request'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.digital_human_runninghub_v1_driver import DigitalHumanRunninghubV1Driver


class TestDigitalHumanDriverWithDB(BaseVideoDriverTest):
    """Digital Human 驱动数据库集成测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.driver = DigitalHumanRunninghubV1Driver()
        
        self.test_ai_tool_id = self.create_test_ai_tool(
            ai_tool_type=11,
            prompt='生成数字人视频',
            image_path='https://example.com/digital_human.jpg',
            duration=5
        )
    
    def test_driver_initialization(self):
        """测试驱动初始化"""
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'digital_human_runninghub_v1')
    
    def test_create_digital_human_task(self):
        """测试创建数字人任务记录"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=11,
            prompt='测试数字人',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=0
        )
        
        result = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE id = %s AND type = %s",
            (task_id, 11)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['type'], 11)


if __name__ == '__main__':
    import unittest
    unittest.main()
