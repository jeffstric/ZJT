"""
short_key 唯一性测试
确保所有 UnifiedTaskConfig 的 short_key 全局唯一且非空
"""
import unittest
import unittest.mock


class TestShortKeyUniqueness(unittest.TestCase):
    """short_key 唯一性测试"""

    def setUp(self):
        from config.unified_config import UnifiedConfigRegistry
        self._registry_snapshot = UnifiedConfigRegistry.snapshot()
        UnifiedConfigRegistry.restore()

        from config.unified_config import init_unified_config
        init_unified_config()

    def tearDown(self):
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry.restore(getattr(self, "_registry_snapshot", None))

    def test_all_short_keys_are_unique(self):
        """所有 short_key 必须全局唯一"""
        from config.unified_config import ALL_TASK_CONFIGS

        short_keys = {}
        duplicates = []

        for config in ALL_TASK_CONFIGS:
            sk = config.short_key
            if sk in short_keys:
                duplicates.append((sk, short_keys[sk], config.key))
            else:
                short_keys[sk] = config.key

        self.assertEqual(len(duplicates), 0,
            f"存在重复的 short_key: {duplicates}")

    def test_all_short_keys_are_non_empty(self):
        """所有 short_key 必须非空"""
        from config.unified_config import ALL_TASK_CONFIGS

        empty_keys = [c.key for c in ALL_TASK_CONFIGS if not c.short_key]

        self.assertEqual(len(empty_keys), 0,
            f"以下配置的 short_key 为空: {empty_keys}")

    def test_short_key_count_equals_config_count(self):
        """short_key 数量必须等于配置数量（即无重复）"""
        from config.unified_config import ALL_TASK_CONFIGS

        short_keys = {c.short_key for c in ALL_TASK_CONFIGS}

        self.assertEqual(len(short_keys), len(ALL_TASK_CONFIGS),
            f"配置数 {len(ALL_TASK_CONFIGS)} != short_key 去重数 {len(short_keys)}，存在重复")

    def test_to_frontend_dict_includes_short_key(self):
        """to_frontend_dict 输出中包含 short_key 字段"""
        from config.unified_config import ALL_TASK_CONFIGS

        for config in ALL_TASK_CONFIGS:
            d = config.to_frontend_dict()
            self.assertIn('short_key', d,
                f"任务 {config.key} 的 to_frontend_dict 缺少 short_key 字段")
            self.assertTrue(d['short_key'],
                f"任务 {config.key} 的 short_key 为空")
            self.assertEqual(d['short_key'], config.short_key,
                f"任务 {config.key} 的 short_key 不匹配: 期望 {config.short_key}, 实际 {d['short_key']}")

    def test_no_short_key_collision_with_sora2(self):
        """验证 sora2 的文生视频和图生视频 short_key 不碰撞"""
        from config.unified_config import ALL_TASK_CONFIGS

        sora2_tasks = [c for c in ALL_TASK_CONFIGS
                       if c.key.startswith('sora2')]

        short_keys = [c.short_key for c in sora2_tasks]
        self.assertEqual(len(short_keys), len(set(short_keys)),
            f"sora2 系列的 short_key 存在碰撞: {short_keys}")

    def test_no_short_key_collision_with_happy_horse(self):
        """验证 happy_horse 系列的 short_key 不碰撞"""
        from config.unified_config import ALL_TASK_CONFIGS

        hh_tasks = [c for c in ALL_TASK_CONFIGS
                    if c.key.startswith('happy_horse')]

        short_keys = [c.short_key for c in hh_tasks]
        self.assertEqual(len(short_keys), len(set(short_keys)),
            f"happy_horse 系列的 short_key 存在碰撞: {short_keys}")

    def test_no_short_key_collision_with_seedance(self):
        """验证 seedance 系列的 short_key 不碰撞"""
        from config.unified_config import ALL_TASK_CONFIGS

        seedance_tasks = [c for c in ALL_TASK_CONFIGS
                         if c.key.startswith('seedance')]

        short_keys = [c.short_key for c in seedance_tasks]
        self.assertEqual(len(short_keys), len(set(short_keys)),
            f"seedance 系列的 short_key 存在碰撞: {short_keys}")

    def test_validate_configs_passes(self):
        """validate_configs 检查通过（包含 short_key 唯一性检查）"""
        from config.unified_config import validate_configs

        errors = validate_configs()
        self.assertEqual(len(errors), 0,
            f"配置验证失败: {errors}")


if __name__ == '__main__':
    unittest.main()
