"""
Gemini Pro Duomi 驱动数据库集成测试
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['duomi_api_requset'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.gemini_pro_duomi_v1_driver import GeminiProDuomiV1Driver


class TestGeminiProDriverWithDB(BaseVideoDriverTest):
    """Gemini Pro 驱动数据库集成测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.driver = GeminiProDuomiV1Driver()
        
        self.test_ai_tool_id = self.create_test_ai_tool(
            ai_tool_type=7,
            prompt='生成专业级创意视频',
            image_path='https://example.com/gemini_pro_image.jpg',
            duration=5
        )
    
    def test_driver_initialization(self):
        """测试驱动初始化"""
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'gemini_pro_duomi_v1')
    
    def test_update_gemini_pro_task(self):
        """测试更新 Gemini Pro 任务"""
        project_id = 'gemini_pro_proj_test_123'
        
        self.update_ai_tool_status(
            self.test_ai_tool_id,
            status=1,
            project_id=project_id
        )
        
        result_project_id = self.assert_ai_tool_has_project_id(self.test_ai_tool_id)
        self.assertEqual(result_project_id, project_id)


if __name__ == '__main__':
    import unittest
    unittest.main()
