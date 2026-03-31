"""
实现方统计功能单元测试
"""
import unittest
from datetime import datetime, timedelta
from .base_db_test import DatabaseTestCase


class TestImplementationIdMapping(unittest.TestCase):
    """Implementation ID 映射测试"""

    def test_implementation_name_to_id(self):
        """测试 implementation 名称转换为 ID"""
        from config.unified_config import get_implementation_id

        # 验证已知的 implementation 映射
        self.assertEqual(get_implementation_id('sora2_duomi_v1'), 1)
        self.assertEqual(get_implementation_id('kling_duomi_v1'), 2)
        self.assertEqual(get_implementation_id('gemini_duomi_v1'), 3)
        self.assertEqual(get_implementation_id('veo3_duomi_v1'), 10)
        self.assertEqual(get_implementation_id('ltx2_runninghub_v1'), 11)
        self.assertEqual(get_implementation_id('wan22_runninghub_v1'), 12)

    def test_implementation_id_to_name(self):
        """测试 implementation ID 转换为名称"""
        from config.unified_config import get_implementation_name

        # 验证已知的 ID 映射
        self.assertEqual(get_implementation_name(1), 'sora2_duomi_v1')
        self.assertEqual(get_implementation_name(2), 'kling_duomi_v1')
        self.assertEqual(get_implementation_name(3), 'gemini_duomi_v1')
        self.assertEqual(get_implementation_name(10), 'veo3_duomi_v1')
        self.assertEqual(get_implementation_name(11), 'ltx2_runninghub_v1')
        self.assertEqual(get_implementation_name(12), 'wan22_runninghub_v1')

    def test_unknown_implementation_returns_default(self):
        """测试未知的 implementation 返回默认值"""
        from config.unified_config import get_implementation_id, get_implementation_name

        # 不存在的名称返回 0
        self.assertEqual(get_implementation_id('nonexistent_impl'), 0)
        # 不存在的 ID 返回 'unknown'
        self.assertEqual(get_implementation_name(999), 'unknown')


class TestImplementationStatsCache(DatabaseTestCase):
    """统计缓存表测试"""

    def test_cache_upsert_and_get(self):
        """测试缓存的插入和查询"""
        from model.implementation_stats_cache import ImplementationStatsCacheModel

        # 插入缓存数据
        success = ImplementationStatsCacheModel.upsert(
            task_type=3,
            impl_id=1,
            days=7,
            total_count=100,
            success_count=95,
            fail_count=5,
            success_rate=95.0,
            avg_duration_ms=45000
        )
        self.assertTrue(success)

        # 查询缓存
        results = ImplementationStatsCacheModel.get_by_days(7)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['type'], 3)
        self.assertEqual(results[0]['impl_id'], 1)
        self.assertEqual(results[0]['total_count'], 100)
        self.assertEqual(results[0]['success_count'], 95)

    def test_cache_update_existing(self):
        """测试更新已有缓存"""
        from model.implementation_stats_cache import ImplementationStatsCacheModel

        # 第一次插入
        ImplementationStatsCacheModel.upsert(
            task_type=3,
            impl_id=1,
            days=7,
            total_count=100,
            success_count=95,
            fail_count=5,
            success_rate=95.0,
            avg_duration_ms=45000
        )

        # 更新数据
        ImplementationStatsCacheModel.upsert(
            task_type=3,
            impl_id=1,
            days=7,
            total_count=200,
            success_count=190,
            fail_count=10,
            success_rate=95.0,
            avg_duration_ms=50000
        )

        # 验证只保留一条记录且数据已更新
        results = ImplementationStatsCacheModel.get_by_days(7)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['total_count'], 200)
        self.assertEqual(results[0]['success_count'], 190)

    def test_cache_clear_by_days(self):
        """测试按天数清除缓存"""
        from model.implementation_stats_cache import ImplementationStatsCacheModel

        # 插入 7 天缓存
        ImplementationStatsCacheModel.upsert(
            task_type=3,
            impl_id=1,
            days=7,
            total_count=100,
            success_count=95,
            fail_count=5,
            success_rate=95.0,
            avg_duration_ms=45000
        )

        # 插入 30 天缓存
        ImplementationStatsCacheModel.upsert(
            task_type=3,
            impl_id=1,
            days=30,
            total_count=500,
            success_count=450,
            fail_count=50,
            success_rate=90.0,
            avg_duration_ms=60000
        )

        # 清除 7 天缓存
        deleted = ImplementationStatsCacheModel.clear_by_days(7)

        # 验证 7 天缓存已清除，30 天缓存仍在
        results_7 = ImplementationStatsCacheModel.get_by_days(7)
        results_30 = ImplementationStatsCacheModel.get_by_days(30)
        self.assertEqual(len(results_7), 0)
        self.assertEqual(len(results_30), 1)
        self.assertEqual(results_30[0]['total_count'], 500)


class TestAIToolsImplementationField(DatabaseTestCase):
    """AITools 表 implementation 字段测试"""

    def test_create_with_implementation(self):
        """测试创建带 implementation 的记录"""
        from model.ai_tools import AIToolsModel

        # 创建记录时指定 implementation
        tool_id = AIToolsModel.create(
            prompt='测试 prompt',
            user_id=1,
            type=3,
            implementation=1  # sora2_duomi_v1
        )

        # 验证记录已创建
        self.assertIsNotNone(tool_id)
        self.assertGreater(tool_id, 0)

        # 验证 implementation 字段
        result = self.execute_query(
            "SELECT implementation FROM `ai_tools` WHERE id = %s",
            (tool_id,)
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['implementation'], 1)

    def test_update_implementation(self):
        """测试更新 implementation 字段"""
        from model.ai_tools import AIToolsModel

        # 创建记录
        tool_id = AIToolsModel.create(
            prompt='测试 prompt',
            user_id=1,
            type=3
        )

        # 更新 implementation
        AIToolsModel.update(tool_id, implementation=2)

        # 验证更新
        result = self.execute_query(
            "SELECT implementation FROM `ai_tools` WHERE id = %s",
            (tool_id,)
        )
        self.assertEqual(result[0]['implementation'], 2)


class TestAIToolsStatsQuery(DatabaseTestCase):
    """AITools 统计查询测试"""

    def test_get_implementation_stats(self):
        """测试 implementation 统计数据查询"""
        from model.ai_tools import AIToolsModel
        from config.constant import AI_TOOL_STATUS_COMPLETED, AI_TOOL_STATUS_FAILED

        # 插入测试数据：3 个成功，1 个失败
        base_time = datetime.now()

        # 成功记录
        for i in range(3):
            tool_id = self.insert_fixture('ai_tools', {
                'prompt': f'测试 prompt {i}',
                'user_id': 1,
                'type': 3,
                'implementation': 1,
                'status': AI_TOOL_STATUS_COMPLETED,
                'create_time': base_time - timedelta(hours=i),
                'completed_time': base_time - timedelta(hours=i) + timedelta(seconds=45)
            })

        # 失败记录
        self.insert_fixture('ai_tools', {
            'prompt': '失败任务',
            'user_id': 1,
            'type': 3,
            'implementation': 1,
            'status': AI_TOOL_STATUS_FAILED,
            'create_time': base_time,
            'completed_time': base_time + timedelta(seconds=5)
        })

        # 提交事务，使数据对其他数据库连接可见（AIToolsModel 使用独立连接）
        self._connection.commit()

        # 查询统计
        stats = AIToolsModel.get_implementation_stats(days=7)

        # 验证统计结果
        self.assertGreater(len(stats), 0)

        # 找到 type=3, impl=1 的统计
        target_stat = None
        for s in stats:
            if s['type'] == 3 and s['implementation'] == 1:
                target_stat = s
                break

        self.assertIsNotNone(target_stat)
        self.assertEqual(target_stat['total_count'], 4)
        self.assertEqual(target_stat['success_count'], 3)
        self.assertEqual(target_stat['fail_count'], 1)
        self.assertGreater(target_stat['success_rate'], 0)


if __name__ == '__main__':
    unittest.main()
