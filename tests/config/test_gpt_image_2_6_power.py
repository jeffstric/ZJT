"""
GPT Image 2.6（sunburst / flare）算力定价单元测试

定价分流（业务决定）：任务级 computing_power=0，基准按实现方——
- 多米（duomi_gpt_image_2_6_*）：2 点（渠道定价，不校验成本覆盖）；
- 通用站点（gpt_image_2_6_common_*_siteN，走 openlux 网关）：7 点基准 × 修饰符。

本文件校验站点侧两条红线：
1. 不倒挂：对 2026-11-20 openlux 网关消费导出（consumption_export_by_key_20261120）
   的每个实测样本，按定价公式得出的算力必须 ≥ 该样本的真实成本
   （成本 = 美元 × 汇率 7.2 ÷ 0.04 元/算力 = 美元 × 180）；
2. 单调性：画质 / 分辨率 / GIF 帧数三个维度各自严格递增，不出现低档比高档贵。
"""
import math
import unittest

from config.unified_config import (
    TaskTypeId,
    UnifiedConfigRegistry,
)

# 通用站点实现方（openlux 网关链路，成本基准 7）；多米实现方见 TestDuomiPricing
SITE_IMPL = 'gpt_image_2_6_common_sunburst_site0_v1'
DUOMI_IMPL = 'duomi_gpt_image_2_6_sunburst_v1'

_patches = []


def setUpModule():
    """测试环境无数据库（conftest stub 指向 localhost:3306 空库，每次连接 ~4s 超时）。

    本文件每个用例都会触发实现方算力 DB 查询，stub 掉返回空（等价无 DB 覆盖），
    让用例毫秒级完成；语义不变——DB 无覆盖时走代码默认基准。
    """
    from unittest.mock import patch
    from model.implementation_power import ImplementationPowerModel
    for method, ret in (
        ('get_all_powers_for_implementation', {}),
        ('get_modifiers', {}),
        ('get_power', None),
    ):
        p = patch.object(ImplementationPowerModel, method, return_value=ret)
        p.start()
        _patches.append(p)


def tearDownModule():
    for p in _patches:
        p.stop()
    _patches.clear()


def _power(extra_config=None, image_size='1k', implementation=SITE_IMPL):
    """按任务 55（sunburst）配置计算算力，与 server.py 图片端点扣费路径
    同入口（真实 build_image_task_billing_context + get_computing_power）。"""
    from utils.computing_power import build_image_task_billing_context
    config = UnifiedConfigRegistry.get_by_id(TaskTypeId.GPT_IMAGE_2_6_SUNBURST)
    context = build_image_task_billing_context(
        extra_config or {},
        image_size=image_size,
        implementation=implementation,
    )
    return config.get_computing_power(implementation=implementation, context=context)


class TestRealCostCoverage(unittest.TestCase):
    """openlux 实测样本零倒挂：定价 ≥ 真实成本（美元 × 180 换算为算力成本）"""

    # (extra_config, image_size, 实测美元成本) —— 数据来源：
    # consumption_export_by_key_20261120_000000_to_20261120_235959_task4060.xlsx
    # （dev2 分组，模型/补全/分组倍率 2.5×6.0×0.59，$1.766e-5/输出 token；
    #   全部样本均为 openlux 网关流水，对应通用站点实现方）
    SAMPLES = [
        # PNG 1024² 默认品质（不传 quality），sunburst / flare 各一条
        ({}, '1k', 0.031012),
        ({}, '1k', 0.031048),
        # GIF 512x928 未传帧数（按默认 2 帧计）
        ({'output_format': 'gif'}, '1k', 0.034720),
        # GIF 928² auto 2 帧
        ({'output_format': 'gif', 'frame_count': '2', 'quality': 'auto'}, '1k', 0.045298),
        # GIF 928² 默认品质、未传帧数（上游默认 2 帧，5617 token 为该帧数最差样本）
        ({'output_format': 'gif'}, '1k', 0.099242),
        # GIF 928² max 6 帧（三条实测：两条 10241 token、一条 22466 token 最差样本）
        ({'output_format': 'gif', 'frame_count': '6', 'quality': 'max'}, '1k', 0.180836),
        ({'output_format': 'gif', 'frame_count': '6', 'quality': 'max'}, '1k', 0.180864),
        ({'output_format': 'gif', 'frame_count': '6', 'quality': 'max'}, '1k', 0.396564),
    ]

    def test_no_price_inversion_against_real_cost(self):
        for extra, size, usd in self.SAMPLES:
            cost_power = usd * 180  # 汇率 7.2 ÷ 0.04 元/算力
            charged = _power(extra, size)
            self.assertGreaterEqual(
                charged, math.ceil(cost_power),
                f"倒挂: extra={extra} size={size} 实收 {charged} 算力 "
                f"< 成本 {cost_power:.2f} 算力 (${usd})",
            )

    def test_static_size_estimates_covered(self):
        """2K/4K 无实测，按像素量估算成本（2K medium≈12.7、4K medium≈26 上限）同样被覆盖"""
        self.assertGreaterEqual(_power({}, '2k'), math.ceil(12.7))
        self.assertGreaterEqual(_power({}, '4k'), 26)


class TestMonotonicity(unittest.TestCase):
    """三个维度各自严格递增，无倒挂（站点实现方口径）"""

    def test_quality_ascending(self):
        prices = [_power({'quality': q}) for q in ('low', 'medium', 'auto', 'high', 'xhigh', 'max')]
        self.assertEqual(prices, sorted(prices))
        self.assertEqual(len(set(prices)), len(prices))

    def test_resolution_ascending(self):
        prices = [_power({}, s) for s in ('1k', '2k', '4k')]
        self.assertEqual(prices, sorted(prices))
        self.assertEqual(len(set(prices)), len(prices))

    def test_frame_count_ascending(self):
        prices = [_power({'output_format': 'gif', 'frame_count': f}) for f in ('2', '4', '6', '9')]
        self.assertEqual(prices, sorted(prices))
        self.assertEqual(len(set(prices)), len(prices))

    def test_gif_pricier_than_static_at_base(self):
        """同为基础档，GIF 2 帧应贵于静态图（上游帧间开销）"""
        self.assertGreater(
            _power({'output_format': 'gif', 'frame_count': '2'}),
            _power({}),
        )


class TestGifSizeIndependent(unittest.TestCase):
    """GIF 帧格被驱动收敛 ≤928，上游成本与分辨率档位无关，定价亦不计分辨率"""

    def test_gif_ignores_resolution(self):
        gif_1k = _power({'output_format': 'gif', 'frame_count': '2'}, '1k')
        gif_4k = _power({'output_format': 'gif', 'frame_count': '2'}, '4k')
        self.assertEqual(gif_1k, gif_4k)


class TestDuomiPricing(unittest.TestCase):
    """多米实现方：渠道基准价 2，不随画质维度上浮（多米不透传 quality）"""

    def test_duomi_base_2(self):
        self.assertEqual(_power({}, '1k', DUOMI_IMPL), 2)

    def test_duomi_quality_not_counted(self):
        self.assertEqual(
            _power({'quality': 'max'}, '1k', DUOMI_IMPL),
            _power({'quality': 'medium'}, '1k', DUOMI_IMPL),
        )

    def test_duomi_resolution_scaling(self):
        """分辨率修饰符对多米同样适用（基准 2：2K=4、4K=8）"""
        self.assertEqual(_power({}, '2k', DUOMI_IMPL), 4)
        self.assertEqual(_power({}, '4k', DUOMI_IMPL), 8)

    def test_common_site_quality_counted(self):
        self.assertGreater(
            _power({'quality': 'max'}, '1k', SITE_IMPL),
            _power({'quality': 'medium'}, '1k', SITE_IMPL),
        )


class TestBillingContextBuilder(unittest.TestCase):
    """build_image_task_billing_context 单测：GIF 特例 / 字符串解析 / 大小写"""

    def _context(self, extra, size='1k', impl=None):
        from utils.computing_power import build_image_task_billing_context
        return build_image_task_billing_context(extra, image_size=size, implementation=impl)

    def test_gif_omits_resolution_and_quality(self):
        ctx = self._context('{"output_format": "gif", "frame_count": 6, "quality": "max"}', '2k')
        self.assertEqual(ctx, {'output_format': 'gif', 'frame_count': '6'})

    def test_gif_defaults_frame_count_to_2(self):
        ctx = self._context({'output_format': 'gif'})
        self.assertEqual(ctx, {'output_format': 'gif', 'frame_count': '2'})

    def test_static_keeps_resolution_and_quality(self):
        ctx = self._context({'output_format': 'svg', 'quality': 'high'}, '2K')
        # 分辨率原样透传（大小写由修饰符双键兼容），画质统一小写（schema 合法值即小写）
        self.assertEqual(ctx, {'resolution': '2K', 'quality': 'high'})

    def test_invalid_extra_config_returns_empty(self):
        self.assertEqual(self._context('not-json{{'), {})

    def test_duomi_omits_quality(self):
        ctx = self._context({'quality': 'max'}, '1k', DUOMI_IMPL)
        self.assertNotIn('quality', ctx)
        self.assertEqual(ctx['resolution'], '1k')


class TestRefundContextFromRecord(unittest.TestCase):
    """退费重算路径（build_context_from_task_record）与扣费路径口径一致"""

    def _record(self, extra, size, impl=None):
        import json
        from types import SimpleNamespace
        return SimpleNamespace(
            extra_config=json.dumps(extra, ensure_ascii=False),
            image_path=None,
            image_size=size,
            implementation=impl,
        )

    def test_gif_record_has_no_resolution(self):
        from utils.computing_power import build_context_from_task_record
        ctx = build_context_from_task_record(
            self._record({'output_format': 'gif', 'frame_count': '6'}, '2k'))
        self.assertNotIn('resolution', ctx)
        self.assertEqual(ctx['frame_count'], '6')

    def test_static_record_resolved_from_image_size(self):
        from utils.computing_power import build_context_from_task_record
        ctx = build_context_from_task_record(self._record({'quality': 'max'}, '4K'))
        # 退费路径原样透传（宫格链路落库大写 "4K"），修饰符表提供大小写双键，扣返一致
        self.assertEqual(ctx['resolution'], '4K')
        config = UnifiedConfigRegistry.get_by_id(TaskTypeId.GPT_IMAGE_2_6_SUNBURST)
        charge = config.get_computing_power(
            implementation=SITE_IMPL,
            context={'resolution': '4k', 'quality': 'max'})
        refund = config.get_computing_power(
            implementation=SITE_IMPL,
            context=ctx)
        self.assertEqual(charge, refund)


if __name__ == '__main__':
    unittest.main()
