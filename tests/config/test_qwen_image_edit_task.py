"""Qwen Image Edit 空壳任务类型配置。"""
import unittest

from config.constant import DRIVER_IMPLEMENTATION_MAPPING, TaskTypeRegistry
from config.model_catalog import get_model_family
from config.unified_config import (
    DriverKey,
    TaskCategory,
    TaskTypeId,
    UnifiedConfigRegistry,
    validate_configs,
)


class TestQwenImageEditTask(unittest.TestCase):
    def test_task_registered_by_id_and_key(self):
        by_id = UnifiedConfigRegistry.get_by_id(TaskTypeId.QWEN_IMAGE_EDIT)
        by_key = UnifiedConfigRegistry.get_by_key('qwen-image-edit')
        self.assertIsNotNone(by_id)
        self.assertIs(by_id, by_key)
        self.assertEqual(by_id.id, 38)
        self.assertEqual(by_id.key, 'qwen-image-edit')
        self.assertEqual(by_id.short_key, 'qwen-image-edit')
        self.assertEqual(by_id.name, 'Qwen Image Edit')

    def test_image_edit_only(self):
        task = UnifiedConfigRegistry.get_by_id(TaskTypeId.QWEN_IMAGE_EDIT)
        self.assertEqual(task.category, TaskCategory.IMAGE_EDIT)
        self.assertNotIn(TaskCategory.TEXT_TO_IMAGE, task.categories)
        self.assertIn(TaskTypeId.QWEN_IMAGE_EDIT, TaskTypeRegistry.get_by_category(TaskCategory.IMAGE_EDIT))
        self.assertNotIn(TaskTypeId.QWEN_IMAGE_EDIT, TaskTypeRegistry.get_by_category(TaskCategory.TEXT_TO_IMAGE))

    def test_visible_empty_shell(self):
        task = UnifiedConfigRegistry.get_by_id(TaskTypeId.QWEN_IMAGE_EDIT)
        self.assertFalse(task.hidden)
        self.assertTrue(task.enabled)
        self.assertEqual(task.implementation, 'qwen_image_edit_pending')
        self.assertEqual(task.driver_name, DriverKey.QWEN_IMAGE_EDIT)
        self.assertEqual(task.computing_power, 1)
        self.assertFalse(task.supports_grid_image)
        self.assertEqual(task.max_multi_ref_images, 3)
        self.assertEqual(task.supported_sizes, [])
        self.assertIsNone(task.default_size)
        self.assertEqual(task.supported_ratios, [])
        self.assertEqual(task.default_ratio, '')

    def test_get_computing_power_is_at_least_one(self):
        task = UnifiedConfigRegistry.get_by_id(TaskTypeId.QWEN_IMAGE_EDIT)
        self.assertGreaterEqual(task.get_computing_power(), 1)

    def test_validate_configs_still_passes(self):
        self.assertEqual(validate_configs(), [])

    def test_implementation_mapping_is_empty(self):
        self.assertEqual(DRIVER_IMPLEMENTATION_MAPPING[DriverKey.QWEN_IMAGE_EDIT], [])

    def test_model_family_is_qwen(self):
        self.assertEqual(get_model_family('qwen-image-edit'), 'Qwen')

    def test_frontend_dict_exposes_short_key(self):
        task = UnifiedConfigRegistry.get_by_id(TaskTypeId.QWEN_IMAGE_EDIT)
        payload = task.to_frontend_dict()
        self.assertEqual(payload['short_key'], 'qwen-image-edit')
        self.assertEqual(payload['category'], TaskCategory.IMAGE_EDIT)
        self.assertFalse(payload['hidden'])
        self.assertEqual(payload['implementations'], [])
        self.assertEqual(payload['supported_ratios'], [])
        self.assertEqual(payload['supported_sizes'], [])
        self.assertIn('supported_sizes', payload)


if __name__ == '__main__':
    unittest.main()
