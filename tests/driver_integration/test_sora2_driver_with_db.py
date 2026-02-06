"""
Sora2 Duomi 驱动数据库集成测试
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['duomi_api_requset'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.sora2_duomi_v1_driver import Sora2DuomiV1Driver


class TestSora2DriverWithDB(BaseVideoDriverTest):
    """Sora2 驱动数据库集成测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.driver = Sora2DuomiV1Driver()
        
        self.test_ai_tool_id = self.create_test_ai_tool(
            ai_tool_type=16,
            prompt='生成高质量视频',
            image_path='https://example.com/sora2_image.jpg',
            duration=5
        )
    
    def test_driver_initialization(self):
        """测试驱动初始化"""
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'sora2_duomi_v1')
    
    def test_create_sora2_task(self):
        """测试创建 Sora2 任务记录"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=16,
            prompt='测试 Sora2',
            image_path='https://example.com/test.jpg',
            duration=10,
            status=0
        )
        
        result = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE id = %s AND type = %s",
            (task_id, 16)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['type'], 16)
        self.assertEqual(result[0]['duration'], 10)


if __name__ == '__main__':
    import unittest
    unittest.main()
