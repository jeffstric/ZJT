"""
供应商切换差价结算测试（"贵扣便宜用"修复，2026-08-20）

场景：任务按供应商A价格扣费（如 site1 10秒=55分），失败切换到供应商B
后成功（如慧梦 10秒=14分），settle_task_success_diff 应双向结算：
  - 多扣退差：diff-refund-{原扣费流水号}，behavior=increase
  - 少扣补收：diff-charge-{原扣费流水号}，behavior=deduct（best-effort）
  - 未切换 / 无差价 / 已结算（幂等）/ 实扣缺失 / 开关关闭 → 跳过
  - 补收失败不抛异常
"""
import unittest
from unittest.mock import patch, MagicMock


def _make_ai_tool(implementation=70, transaction_id='txn-sw-1', duration=10,
                  user_id=1534, task_id=28928, ai_tool_type=27):
    """构造切换后成功的任务记录

    默认值还原事故现场：按 site1(43, 10秒=55) 扣费，切换慧梦(70)后成功
    （慧梦 10秒=14），应退差 55-14=41。
    """
    m = MagicMock()
    m.id = task_id
    m.user_id = user_id
    m.type = ai_tool_type  # GROK_IMAGE_TO_VIDEO
    m.implementation = implementation  # 最终完成供应商
    m.transaction_id = transaction_id
    m.duration = duration
    m.extra_config = None
    m.image_path = 'img.jpg'
    return m


def _mock_perseids():
    """perseids 两步调用 mock：取 token + 结算"""
    req = MagicMock()
    req.side_effect = [
        (True, 'ok', {'token': 'fake-token'}),
        (True, 'ok', {}),
    ]
    return req


class TestSettleTaskSuccessDiff(unittest.TestCase):
    """settle_task_success_diff 双向结算"""

    def setUp(self):
        from config.unified_config import UnifiedConfigRegistry, init_unified_config
        self._registry_snapshot = UnifiedConfigRegistry.snapshot()
        UnifiedConfigRegistry.restore()
        init_unified_config()

    def tearDown(self):
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry.restore(getattr(self, "_registry_snapshot", None))

    def _patches(self, retry_count=1, deducted=55, settled_exists=False):
        """通用 patch 集：开关开、切换过、实扣55、未结算"""
        return [
            patch('config.config_util.get_dynamic_config_value',
                  return_value=True),
            patch('model.implementation_attempts.ImplementationAttemptModel.get_retry_implementation_count',
                  return_value=retry_count),
            patch('model.computing_power_log.ComputingPowerLogModel.check_transaction_exists',
                  return_value=settled_exists),
            patch('model.computing_power_log.ComputingPowerLogModel.get_deducted_power_by_transaction',
                  return_value=deducted),
        ]

    @patch('perseids_server.client.make_perseids_request')
    def test_overcharge_refunds_diff(self, mock_request):
        """多扣退差：扣55（site1价）、慧梦(70,10秒=14)完成 → 退41"""
        from utils.computing_power import settle_task_success_diff

        mock_request.side_effect = [
            (True, 'ok', {'token': 'fake-token'}),
            (True, 'ok', {}),
        ]
        for p in self._patches(deducted=55):
            p.start()
        try:
            result = settle_task_success_diff(_make_ai_tool(implementation=70, duration=10))
        finally:
            for p in self._patches():
                pass
            patch.stopall()

        self.assertEqual(result, 41)
        settle_call = mock_request.call_args_list[1]
        self.assertEqual(settle_call.kwargs['data']['computing_power'], 41)
        self.assertEqual(settle_call.kwargs['data']['behavior'], 'increase')
        self.assertEqual(settle_call.kwargs['data']['transaction_id'], 'diff-refund-txn-sw-1')

    @patch('perseids_server.client.make_perseids_request')
    def test_undercharge_charges_diff(self, mock_request):
        """少扣补收：扣16（duomi 15秒价）、site0(42,15秒=80)完成 → 补收64

        注：使用 site0 而非 site1，因 site1 的 {6:35,10:55,15:80} 是生产库
        热更新价格，测试环境回退代码默认 {6:6,10:8,15:12}；site0 代码默认即 80。
        """
        from utils.computing_power import settle_task_success_diff

        mock_request.side_effect = [
            (True, 'ok', {'token': 'fake-token'}),
            (True, 'ok', {}),
        ]
        for p in self._patches(deducted=16):
            p.start()
        try:
            result = settle_task_success_diff(_make_ai_tool(implementation=42, duration=15))
        finally:
            patch.stopall()

        self.assertEqual(result, -64)
        settle_call = mock_request.call_args_list[1]
        self.assertEqual(settle_call.kwargs['data']['computing_power'], 64)
        self.assertEqual(settle_call.kwargs['data']['behavior'], 'deduct')
        self.assertEqual(settle_call.kwargs['data']['transaction_id'], 'diff-charge-txn-sw-1')

    @patch('perseids_server.client.make_perseids_request')
    def test_no_switch_skipped(self, mock_request):
        """未切换任务跳过（不发起任何请求）"""
        from utils.computing_power import settle_task_success_diff

        for p in self._patches(retry_count=0):
            p.start()
        try:
            self.assertIsNone(settle_task_success_diff(_make_ai_tool()))
        finally:
            patch.stopall()
        mock_request.assert_not_called()

    @patch('perseids_server.client.make_perseids_request')
    def test_zero_diff_skipped(self, mock_request):
        """无差价跳过：扣16、duomi(48,15秒=16)完成 → diff=0"""
        from utils.computing_power import settle_task_success_diff

        for p in self._patches(deducted=16):
            p.start()
        try:
            self.assertIsNone(settle_task_success_diff(
                _make_ai_tool(implementation=48, duration=15)))
        finally:
            patch.stopall()
        mock_request.assert_not_called()

    @patch('perseids_server.client.make_perseids_request')
    def test_already_settled_skipped(self, mock_request):
        """幂等：任一方向流水已存在则跳过"""
        from utils.computing_power import settle_task_success_diff

        for p in self._patches(settled_exists=True):
            p.start()
        try:
            self.assertIsNone(settle_task_success_diff(_make_ai_tool()))
        finally:
            patch.stopall()
        mock_request.assert_not_called()

    @patch('perseids_server.client.make_perseids_request')
    def test_no_deduct_log_skipped(self, mock_request):
        """实扣流水缺失跳过"""
        from utils.computing_power import settle_task_success_diff

        for p in self._patches(deducted=None):
            p.start()
        try:
            self.assertIsNone(settle_task_success_diff(_make_ai_tool()))
        finally:
            patch.stopall()
        mock_request.assert_not_called()

    @patch('perseids_server.client.make_perseids_request')
    def test_switch_disabled_skipped(self, mock_request):
        """灰度开关关闭跳过"""
        from utils.computing_power import settle_task_success_diff

        with patch('config.config_util.get_dynamic_config_value', return_value=False):
            self.assertIsNone(settle_task_success_diff(_make_ai_tool()))
        mock_request.assert_not_called()

    @patch('perseids_server.client.make_perseids_request')
    def test_charge_failure_swallowed(self, mock_request):
        """补收失败（余额不足）不抛异常、返回 None（best-effort 让利）"""
        from utils.computing_power import settle_task_success_diff

        mock_request.side_effect = [
            (True, 'ok', {'token': 'fake-token'}),
            (False, 'insufficient balance', {}),
        ]
        for p in self._patches(deducted=16):
            p.start()
        try:
            result = settle_task_success_diff(_make_ai_tool(implementation=43, duration=15))
        finally:
            patch.stopall()

        self.assertIsNone(result)  # 不抛异常

    @patch('perseids_server.client.make_perseids_request')
    def test_charge_http_error_swallowed(self, mock_request):
        """结算过程 HTTP 异常不抛出"""
        from utils.computing_power import settle_task_success_diff

        mock_request.side_effect = Exception('network down')
        for p in self._patches(deducted=55):
            p.start()
        try:
            self.assertIsNone(settle_task_success_diff(_make_ai_tool()))
        finally:
            patch.stopall()

    @patch('perseids_server.client.make_perseids_request')
    def test_missing_fields_skipped(self, mock_request):
        """缺 transaction_id / user_id 直接跳过"""
        from utils.computing_power import settle_task_success_diff

        self.assertIsNone(settle_task_success_diff(_make_ai_tool(transaction_id=None)))
        self.assertIsNone(settle_task_success_diff(_make_ai_tool(user_id=None)))
        mock_request.assert_not_called()


class TestSettleWrapper(unittest.TestCase):
    """settle_success_diff_for_task 包装函数"""

    @patch('utils.computing_power.settle_task_success_diff')
    @patch('model.ai_tools.AIToolsModel.get_by_id')
    def test_wrapper_loads_and_settles(self, mock_get, mock_settle):
        from utils.computing_power import settle_success_diff_for_task

        mock_get.return_value = _make_ai_tool()
        mock_settle.return_value = 41

        self.assertEqual(settle_success_diff_for_task(28928), 41)
        mock_get.assert_called_once_with(28928)
        mock_settle.assert_called_once()

    @patch('model.ai_tools.AIToolsModel.get_by_id')
    def test_wrapper_task_not_found(self, mock_get):
        from utils.computing_power import settle_success_diff_for_task

        mock_get.return_value = None
        self.assertIsNone(settle_success_diff_for_task(404))

    @patch('model.ai_tools.AIToolsModel.get_by_id')
    def test_wrapper_db_error_swallowed(self, mock_get):
        from utils.computing_power import settle_success_diff_for_task

        mock_get.side_effect = Exception('db down')
        self.assertIsNone(settle_success_diff_for_task(28928))  # 不抛异常


if __name__ == '__main__':
    unittest.main()
