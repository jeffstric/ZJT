"""
token 计费公式单元测试：锁定「缓存命中不按输入全价重复计费」语义

背景：2026-01-24 起计费公式曾把含缓存命中的全量 input_token 按未命中全价计费，
缓存部分又按缓存价加收一次（缓存命中率越高越吃亏，约多收 3 倍）。
修复后：输入项只按未命中部分(input_token - cache_read)计价。

用例数字来自 DeepSeek 官方接口实测（恒等式 prompt_tokens = hit + miss）：
  call2: prompt_tokens=3089, cached=3072, miss=17, completion=8
  deepseek-v4-flash 空闲档阈值 26667/8889/800000（输入/输出/缓存读取 token 每算力）
"""
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from task import token_task


def _vendor_model(commission='0.05'):
    return SimpleNamespace(
        input_token_threshold=26667,
        output_token_threshold=8889,
        cache_read_threshold=800000,
        commission_rate=Decimal(commission),
        time_period='off_peak',
    )


def _run(input_token, output_token, cache_read, existing_hundredths=0, commission='0.05'):
    """注入 mock 后调用 calculate_computing_power_from_tokens，返回 (扣减, note, upsert参数)"""
    existing = SimpleNamespace(accumulated_power=existing_hundredths) if existing_hundredths else None
    upsert_calls = []
    with mock.patch.object(token_task.VendorModelModel, 'get_by_vendor_model_for_billing',
                           return_value=_vendor_model(commission)), \
         mock.patch.object(token_task.UncalculatedPowerModel, 'get_by_user_id',
                           return_value=existing), \
         mock.patch.object(token_task.UncalculatedPowerModel, 'upsert',
                           side_effect=lambda uid, r: upsert_calls.append((uid, r))), \
         mock.patch.object(token_task, 'resolve_billing_period',
                           return_value=('off_peak', False)):
        deduct, note = token_task.calculate_computing_power_from_tokens(
            input_token=input_token, output_token=output_token, cache_read=cache_read,
            cache_creation=0, user_id=1, vendor_id=7, model_id=1005,
        )
    return deduct, note, upsert_calls


class TestCacheBillingSemantics(unittest.TestCase):
    """缓存命中部分只按缓存价计费，不得按输入全价重复计费"""

    def test_high_cache_hit_not_double_charged(self):
        """实测样本: 输入3089(含缓存3072)/输出8 → 基础算力≈0.0054 而非旧口径的0.1206"""
        deduct, note, upserts = _run(3089, 8, 3072)
        # 应收 = 17/26667 + 8/8889 + 3072/800000 ≈ 0.005378 → 1百分位内不扣减
        self.assertEqual(deduct, 0)
        self.assertIn('基础算力:0.0054', note)
        self.assertIn('输入未命中:17', note)
        # 旧口径(双重计费)为 0.1206,若回归会得到 0.1206 或 12/13 百分位
        self.assertNotIn('基础算力:0.1206', note)

    def test_accumulation_across_threshold(self):
        """已有累积90百分位 + 本次1百分位(0.0056算力) → 仍不足1算力不扣减,余91"""
        deduct, note, upserts = _run(3089, 8, 3072, existing_hundredths=90)
        self.assertEqual(deduct, 0)
        self.assertEqual(upserts, [(1, 91)])

    def test_accumulation_exact_threshold(self):
        """已有累积99百分位 + 本次1百分位 → 恰好100,扣减1算力,余0"""
        deduct, note, upserts = _run(3089, 8, 3072, existing_hundredths=99)
        self.assertEqual(deduct, 1)
        self.assertEqual(upserts, [(1, 0)])

    def test_full_input_without_cache(self):
        """无缓存时按全量输入计价: 26667输入=1算力基础(未计抽成)"""
        deduct, note, upserts = _run(26667, 0, 0)
        # 基础1.0 × 1.05 = 105百分位 → 扣1余5
        self.assertEqual(deduct, 1)
        self.assertEqual(upserts, [(1, 5)])

    def test_cache_hit_only_input(self):
        """极端防御: cache>input 时不产生负的未命中输入"""
        deduct, note, upserts = _run(100, 8, 200)
        # uncached = max(0, 100-200) = 0; base = 0 + 8/8889 + 200/800000 ≈ 0.00115
        self.assertEqual(deduct, 0)
        self.assertIn('输入未命中:0', note)

    def test_zero_commission_multiplier(self):
        """无抽成供应商: 倍率1.0, 基础=最终; 余0且无存量记录时不写upsert"""
        deduct, note, upserts = _run(26667, 0, 0, commission='0')
        self.assertEqual(deduct, 1)
        self.assertEqual(upserts, [])


if __name__ == '__main__':
    unittest.main()
