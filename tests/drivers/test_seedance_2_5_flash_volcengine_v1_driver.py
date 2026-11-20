"""
Seedance 2.5 Flash 火山引擎驱动单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖

测试结构：
- 初始化（model_name / driver_type / impl_name）
- build_create_request 的 model 字段与 2.5 接口兼容性
- 2.5 音频预算类属性继承
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# 必须在导入会触发 model/database 的模块前，给 config_unit.yml 塞进一个最小配置缓存。
os.environ.setdefault("comfyui_env", "unit")
from config import config_util  # noqa: E402

config_util._config_cache["config_unit.yml"] = {
    "database": {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "",
        "database": "unit",
    },
    "server": {},
    "file_storage": {},
}

# Mock 外部依赖（必须在 import driver 之前）
sys.modules['utils.sentry_util'] = MagicMock()
sys.modules['utils.image_upload_utils'] = MagicMock()


def _create_flash_driver():
    """创建 Seedance25FlashVolcengineV1Driver 实例（mock 所有外部依赖）"""
    from task.visual_drivers.seedance_volcengine_v1_driver import Seedance25FlashVolcengineV1Driver

    with patch('task.visual_drivers.seedance_volcengine_v1_driver.get_dynamic_config_value') as mock_config, \
         patch('task.visual_drivers.seedance_volcengine_v1_driver.get_config', return_value={}):

        def side_effect(*keys, default=None):
            key_map = {
                ('volcengine', 'api_key'): 'test_api_key',
                ('timeout', 'request_timeout'): 30,
                ('server', 'is_local'): False,
                ('test_mode', 'enabled'): False,
                ('test_mode', 'mock_videos'): {},
            }
            return key_map.get(keys, default)

        mock_config.side_effect = side_effect
        return Seedance25FlashVolcengineV1Driver()


class TestSeedance25FlashDriverInit(unittest.TestCase):
    """Seedance 2.5 Flash 驱动初始化测试"""

    def test_init_constants(self):
        """模型名 / 任务类型 / 实现方应为 Flash 专属值"""
        from config.unified_config import TaskTypeId, DriverImplementation
        driver = _create_flash_driver()

        self.assertEqual(driver._model, 'doubao-seedance-2-5-flash-261115')
        self.assertEqual(driver.driver_type, TaskTypeId.SEEDANCE_2_5_FLASH_IMAGE_TO_VIDEO)
        self.assertEqual(driver.driver_name, DriverImplementation.SEEDANCE_2_5_FLASH_VOLCENGINE_V1)

    def test_inherits_25_audio_budget(self):
        """接口与 2.5 完全兼容：音频预算沿用 30s / 10 条"""
        driver = _create_flash_driver()

        self.assertEqual(driver.R2V_AUDIO_MAX_TOTAL_SECONDS, 30.0)
        self.assertEqual(driver.R2V_AUDIO_MAX_COUNT, 10)


class TestSeedance25FlashBuildRequest(unittest.TestCase):
    """Seedance 2.5 Flash 请求构建测试"""

    def test_build_create_request_uses_flash_model(self):
        """文生视频 payload 的 model 字段应为 flash 快照（接口与 2.5 兼容）"""
        driver = _create_flash_driver()

        tool = MagicMock()
        tool.id = 1001
        tool.prompt = '一只猫在草地上奔跑'
        tool.image_path = None
        tool.extra_config = None
        tool.duration = 5
        tool.reference_images = None
        tool.audio_path = None
        tool.video_path = None
        tool.ratio = '9:16'

        req = driver.build_create_request(tool)

        self.assertEqual(req['json']['model'], 'doubao-seedance-2-5-flash-261115')
        self.assertEqual(req['json']['duration'], 5)
        self.assertEqual(req['json']['ratio'], '9:16')


if __name__ == '__main__':
    unittest.main()
