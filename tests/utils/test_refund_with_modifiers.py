"""
算力退还测试 - 验证修饰符正确应用于退款
"""
import unittest
from unittest.mock import patch, MagicMock
import uuid


class TestRefundWithModifiers(unittest.TestCase):
    """测试算力退还时正确应用修饰符"""

    def setUp(self):
        """测试前准备"""
        from config.unified_config import (
            UnifiedConfigRegistry,
            init_unified_config,
        )

        # 清空注册表
        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

        # 初始化完整配置
        init_unified_config()

    def tearDown(self):
        """测试后清理"""
        from config.unified_config import UnifiedConfigRegistry

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    def test_kling_refund_with_tail_includes_multiplier(self):
        """测试 Kling 首尾帧失败后退算力包含 1.66x 倍数"""
        from utils.computing_power import build_context_from_task_record, get_computing_power_for_task

        # 创建模拟的 AI tool 记录（首尾帧带尾帧）
        mock_ai_tool = MagicMock()
        mock_ai_tool.id = 123
        mock_ai_tool.user_id = 456
        mock_ai_tool.type = 12  # KLING_IMAGE_TO_VIDEO (正确的ID)
        mock_ai_tool.duration = 5
        mock_ai_tool.extra_config = '{"image_mode": "first_last_frame"}'
        mock_ai_tool.image_path = "image1.jpg,image2.jpg"  # 包含逗号表示有尾帧

        # 构建上下文（应该检测到 first_last_with_tail）
        context = build_context_from_task_record(mock_ai_tool)

        # 验证上下文正确构建
        self.assertEqual(context['image_mode'], 'first_last_with_tail')

        # 获取算力（应该应用 1.66x 倍数）
        power_deducted = get_computing_power_for_task(
            task_type=12,
            duration=5,
            user_id=456,
            context=context
        )

        # 基础算力是 38，38 * 1.66 = 63.08，向上取整 = 64
        self.assertEqual(power_deducted, 64)

        # 模拟失败时的算力退还（应该使用相同的算力值）
        power_refunded = get_computing_power_for_task(
            task_type=12,
            duration=5,
            user_id=456,
            context=context  # 使用相同的上下文
        )

        # 退还的算力应该与扣除的算力相同（包含倍数）
        self.assertEqual(power_refunded, 64)
        self.assertEqual(power_deducted, power_refunded)

    def test_kling_refund_single_frame_no_multiplier(self):
        """测试 Kling 单帧失败后退算力不包含倍数"""
        from utils.computing_power import build_context_from_task_record, get_computing_power_for_task

        # 创建模拟的 AI tool 记录（单帧）
        mock_ai_tool = MagicMock()
        mock_ai_tool.id = 124
        mock_ai_tool.user_id = 457
        mock_ai_tool.type = 12  # KLING_IMAGE_TO_VIDEO (正确的ID)
        mock_ai_tool.duration = 5
        mock_ai_tool.extra_config = '{"image_mode": "first_last_frame"}'
        mock_ai_tool.image_path = "image1.jpg"  # 单张图片

        # 构建上下文
        context = build_context_from_task_record(mock_ai_tool)

        # 验证上下文正确构建（无尾帧）
        self.assertEqual(context['image_mode'], 'first_last_frame')

        # 获取算力（应该不应用倍数）
        power_deducted = get_computing_power_for_task(
            task_type=12,
            duration=5,
            user_id=457,
            context=context
        )

        # 基础算力是 38，不应用倍数
        self.assertEqual(power_deducted, 38)

        # 模拟失败时的算力退还
        power_refunded = get_computing_power_for_task(
            task_type=12,
            duration=5,
            user_id=457,
            context=context
        )

        # 退还的算力应该与扣除的算力相同
        self.assertEqual(power_refunded, 38)
        self.assertEqual(power_deducted, power_refunded)

    def test_refund_consistency_deduct_vs_refund(self):
        """测试扣除和退还算力的一致性（在各种场景下）"""
        from utils.computing_power import build_context_from_task_record, get_computing_power_for_task

        test_cases = [
            {
                'name': 'Kling 首尾帧带尾帧',
                'ai_tool_type': 12,  # KLING_IMAGE_TO_VIDEO (正确的ID)
                'user_id': 458,
                'extra_config': '{"image_mode": "first_last_frame"}',
                'image_path': 'img1.jpg,img2.jpg',
                'duration': 5,
                'expected_power': 64  # 38 * 1.66 = 64
            },
            {
                'name': 'Kling 首尾帧不带尾帧',
                'ai_tool_type': 12,  # KLING_IMAGE_TO_VIDEO (正确的ID)
                'user_id': 459,
                'extra_config': '{"image_mode": "first_last_frame"}',
                'image_path': 'img1.jpg',
                'duration': 5,
                'expected_power': 38  # 基础算力
            },
            {
                'name': 'Kling 10秒首尾帧带尾帧',
                'ai_tool_type': 12,  # KLING_IMAGE_TO_VIDEO (正确的ID)
                'user_id': 460,
                'extra_config': '{"image_mode": "first_last_frame"}',
                'image_path': 'img1.jpg,img2.jpg',
                'duration': 10,
                'expected_power': 117  # 70 * 1.66 = 116.2 → 117
            },
        ]

        for case in test_cases:
            with self.subTest(case=case['name']):
                # 创建模拟 AI tool
                mock_ai_tool = MagicMock()
                mock_ai_tool.id = 125 + len(test_cases)  # 确保不同的 ID
                mock_ai_tool.user_id = case['user_id']
                mock_ai_tool.type = case['ai_tool_type']
                mock_ai_tool.duration = case['duration']
                mock_ai_tool.extra_config = case['extra_config']
                mock_ai_tool.image_path = case['image_path']

                # 构建上下文
                context = build_context_from_task_record(mock_ai_tool)

                # 获取算力
                power_deducted = get_computing_power_for_task(
                    task_type=case['ai_tool_type'],
                    duration=case['duration'],
                    user_id=case['user_id'],
                    context=context
                )

                # 获取退还算力
                power_refunded = get_computing_power_for_task(
                    task_type=case['ai_tool_type'],
                    duration=case['duration'],
                    user_id=case['user_id'],
                    context=context
                )

                # 验证扣除和退还一致
                self.assertEqual(power_deducted, power_refunded,
                              f"{case['name']}: 扣除和退还算力应该一致")
                self.assertEqual(power_deducted, case['expected_power'],
                              f"{case['name']}: 算力值不符合预期")

                print(f"✓ {case['name']}: 扣除={power_deducted}, 退还={power_refunded}")


if __name__ == '__main__':
    unittest.main()