"""
VEO3 Duomi 驱动数据库集成测试
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['duomi_api_requset'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.veo3_duomi_v1_driver import Veo3DuomiV1Driver


class TestVEO3DriverWithDB(BaseVideoDriverTest):
    """VEO3 驱动数据库集成测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.driver = Veo3DuomiV1Driver()
        
        self.test_ai_tool_id = self.create_test_ai_tool(
            ai_tool_type=17,
            prompt='生成专业视频',
            image_path='https://example.com/veo3_image.jpg',
            duration=5
        )
    
    def test_driver_initialization(self):
        """测试驱动初始化"""
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'veo3_duomi_v1')
    
    def test_create_veo3_task(self):
        """测试创建 VEO3 任务记录"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=17,
            prompt='测试 VEO3',
            image_path='https://example.com/test.jpg',
            duration=8,
            status=0
        )
        
        result = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE id = %s AND type = %s",
            (task_id, 17)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['type'], 17)
        self.assertEqual(result[0]['duration'], 8)


if __name__ == '__main__':
    import unittest
    unittest.main()
