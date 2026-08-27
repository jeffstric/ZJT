"""
退费金额一致性测试 - Grok 多供应商切换退费事故修复（2026-08-19）

事故复现：任务按 grok_duomi_v1（15秒=16分）扣费，重试切换到
grok_common_site0_v1（15秒=80分）时 ai_tools.implementation 被改写，
旧退费逻辑按切换后的实现方重算，出现「扣16分退80分」。

修复验证点：
  1. resolve_refund_amount 优先按 ai_tools.transaction_id 关联的扣费流水
     原额退还，不受 implementation 被切换影响
  2. 流水缺失时回退到按当前配置重算（保持旧行为兼容）
  3. 退费流水号 refund-{原扣费流水号}，幂等防重复退费
  4. _refund_computing_power 全链路使用实际扣减金额
"""
import unittest
from unittest.mock import patch, MagicMock


def _make_ai_tool(implementation=42, transaction_id='txn-grok-123', duration=15,
                  user_id=1534, task_id=28084, ai_tool_type=27):
    """构造 Grok 图生视频任务的 mock 记录

    默认值还原事故现场：任务按 duomi(48) 扣16分后 implementation 被
    切换为 site0(42)，transaction_id 是扣费流水。
    """
    mock_ai_tool = MagicMock()
    mock_ai_tool.id = task_id
    mock_ai_tool.user_id = user_id
    mock_ai_tool.type = ai_tool_type  # GROK_IMAGE_TO_VIDEO
    mock_ai_tool.implementation = implementation
    mock_ai_tool.transaction_id = transaction_id
    mock_ai_tool.duration = duration
    mock_ai_tool.extra_config = None
    mock_ai_tool.image_path = 'img1.jpg'
    return mock_ai_tool


class TestResolveRefundAmount(unittest.TestCase):
    """resolve_refund_amount 三级回退测试"""

    def setUp(self):
        from config.unified_config import UnifiedConfigRegistry, init_unified_config
        self._registry_snapshot = UnifiedConfigRegistry.snapshot()
        UnifiedConfigRegistry.restore()
        init_unified_config()

    def tearDown(self):
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry.restore(getattr(self, "_registry_snapshot", None))

    @patch('model.computing_power_log.ComputingPowerLogModel.get_deducted_power_by_transaction')
    def test_provider_switch_refunds_actual_deducted_amount(self, mock_get_deducted):
        """核心场景：实现方切换后仍按实际扣减流水原额退还

        事故中任务按 duomi(15秒=16分) 扣费、implementation 已被改写为
        site0(42)，退费必须返回 16 而非按 site0 重算的 80。
        """
        mock_get_deducted.return_value = 16
        from utils.computing_power import resolve_refund_amount

        ai_tool = _make_ai_tool(implementation=42)
        self.assertEqual(resolve_refund_amount(ai_tool), 16)
        mock_get_deducted.assert_called_once_with(1534, 'txn-grok-123')

    @patch('model.computing_power_log.ComputingPowerLogModel.get_deducted_power_by_transaction')
    def test_fallback_to_recalc_when_no_deduct_log(self, mock_get_deducted):
        """扣费流水缺失时回退按当前配置重算（site0 15秒=80）"""
        mock_get_deducted.return_value = None
        from utils.computing_power import resolve_refund_amount

        ai_tool = _make_ai_tool(implementation=42)
        self.assertEqual(resolve_refund_amount(ai_tool), 80)

    def test_fallback_to_recalc_when_no_transaction_id(self):
        """老数据无扣费流水号时回退按当前配置重算"""
        from utils.computing_power import resolve_refund_amount

        ai_tool = _make_ai_tool(implementation=48, transaction_id=None)
        # duomi 15秒 = 16
        self.assertEqual(resolve_refund_amount(ai_tool), 16)

    @patch('model.computing_power_log.ComputingPowerLogModel.get_deducted_power_by_transaction')
    def test_deduct_log_lookup_error_falls_back(self, mock_get_deducted):
        """流水查询异常时不阻断退费，回退重算"""
        mock_get_deducted.side_effect = Exception('db down')
        from utils.computing_power import resolve_refund_amount

        ai_tool = _make_ai_tool(implementation=42)
        self.assertEqual(resolve_refund_amount(ai_tool), 80)

    def test_missing_user_id_returns_none(self):
        """无 user_id 无法解析，返回 None"""
        from utils.computing_power import resolve_refund_amount

        ai_tool = _make_ai_tool(user_id=None)
        self.assertIsNone(resolve_refund_amount(ai_tool))


class TestRefundIdempotency(unittest.TestCase):
    """退费流水号与幂等检查测试"""

    def test_build_refund_transaction_id(self):
        from utils.computing_power import build_refund_transaction_id

        ai_tool = _make_ai_tool(transaction_id='abc-123')
        self.assertEqual(build_refund_transaction_id(ai_tool), 'refund-abc-123')

    def test_build_refund_transaction_id_without_txn(self):
        from utils.computing_power import build_refund_transaction_id

        ai_tool = _make_ai_tool(transaction_id=None)
        self.assertIsNone(build_refund_transaction_id(ai_tool))

    @patch('model.computing_power_log.ComputingPowerLogModel.check_transaction_exists')
    def test_is_already_refunded_true(self, mock_exists):
        from utils.computing_power import is_already_refunded

        mock_exists.return_value = True
        ai_tool = _make_ai_tool()
        self.assertTrue(is_already_refunded(ai_tool))
        mock_exists.assert_called_once_with('refund-txn-grok-123')

    @patch('model.computing_power_log.ComputingPowerLogModel.check_transaction_exists')
    def test_is_already_refunded_false(self, mock_exists):
        from utils.computing_power import is_already_refunded

        mock_exists.return_value = False
        self.assertFalse(is_already_refunded(_make_ai_tool()))

    def test_is_already_refunded_without_txn(self):
        from utils.computing_power import is_already_refunded

        self.assertFalse(is_already_refunded(_make_ai_tool(transaction_id=None)))


class TestRefundComputingPowerIntegration(unittest.TestCase):
    """_refund_computing_power 全链路测试（mock DB 与 perseids 请求）"""

    def setUp(self):
        from config.unified_config import UnifiedConfigRegistry, init_unified_config
        self._registry_snapshot = UnifiedConfigRegistry.snapshot()
        UnifiedConfigRegistry.restore()
        init_unified_config()

    def tearDown(self):
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry.restore(getattr(self, "_registry_snapshot", None))

    def _mock_perseids(self):
        """mock perseids 请求：取 token + 退费两个调用"""
        mock_request = MagicMock()
        mock_request.side_effect = [
            (True, 'ok', {'token': 'fake-token'}),
            (True, 'ok', {'computing_power': 100}),
        ]
        return mock_request

    @patch('task.visual_task.make_perseids_request')
    @patch('model.computing_power_log.ComputingPowerLogModel.check_transaction_exists')
    @patch('model.computing_power_log.ComputingPowerLogModel.get_deducted_power_by_transaction')
    def test_refund_uses_actual_deducted_amount(self, mock_get_deducted, mock_exists, mock_request):
        """全链路：实现方已切换，退费金额=实际扣减16，流水号带 refund- 前缀"""
        from task.visual_task import _refund_computing_power

        mock_get_deducted.return_value = 16
        mock_exists.return_value = False
        mock_request.side_effect = [
            (True, 'ok', {'token': 'fake-token'}),
            (True, 'ok', {}),
        ]

        ai_tool = _make_ai_tool(implementation=42)
        _refund_computing_power(ai_tool, '服务异常，请联系技术支持')

        refund_call = mock_request.call_args_list[1]
        self.assertEqual(refund_call.kwargs['data']['computing_power'], 16)
        self.assertEqual(refund_call.kwargs['data']['behavior'], 'increase')
        self.assertEqual(
            refund_call.kwargs['data']['transaction_id'], 'refund-txn-grok-123'
        )

    @patch('task.visual_task.make_perseids_request')
    @patch('model.computing_power_log.ComputingPowerLogModel.check_transaction_exists')
    @patch('model.computing_power_log.ComputingPowerLogModel.get_deducted_power_by_transaction')
    def test_refund_skipped_when_already_refunded(self, mock_get_deducted, mock_exists, mock_request):
        """幂等：已退过费的任务不再发起退费请求"""
        from task.visual_task import _refund_computing_power

        mock_exists.return_value = True

        _refund_computing_power(_make_ai_tool(), '服务异常，请联系技术支持')

        mock_request.assert_not_called()
        mock_get_deducted.assert_not_called()


if __name__ == '__main__':
    unittest.main()
