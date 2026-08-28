"""
峰谷计费时段判断单元测试
测试 utils.billing_period 模块：北京时间高峰/空闲时段判断、时区转换、异常兜底。

DeepSeek 峰谷规则：自 2026-08-23（北京时间）起，高峰为周一至周五 9:00-12:00、14:00-18:00
（左闭右开），其余（含周末全天）空闲；此前高峰窗口不区分星期。
"""
import unittest
from datetime import datetime, timezone, timedelta

from utils.billing_period import get_billing_period, to_bjt_naive, resolve_billing_period
from config.constant import PeakValleyBillingConstants


class TestGetBillingPeriod(unittest.TestCase):
    """测试 get_billing_period 高峰/空闲判断"""

    def _dt(self, hour, minute=0):
        return datetime(2026, 8, 13, hour, minute)

    def test_peak_morning_window(self):
        """9:00-12:00 为高峰（左闭右开）"""
        self.assertEqual(get_billing_period(self._dt(9, 0)), PeakValleyBillingConstants.PERIOD_PEAK)
        self.assertEqual(get_billing_period(self._dt(10, 30)), PeakValleyBillingConstants.PERIOD_PEAK)
        self.assertEqual(get_billing_period(self._dt(11, 59)), PeakValleyBillingConstants.PERIOD_PEAK)

    def test_peak_afternoon_window(self):
        """14:00-18:00 为高峰（左闭右开）"""
        self.assertEqual(get_billing_period(self._dt(14, 0)), PeakValleyBillingConstants.PERIOD_PEAK)
        self.assertEqual(get_billing_period(self._dt(15, 0)), PeakValleyBillingConstants.PERIOD_PEAK)
        self.assertEqual(get_billing_period(self._dt(17, 59)), PeakValleyBillingConstants.PERIOD_PEAK)

    def test_off_peak_noon_gap(self):
        """12:00-14:00 午间为空闲"""
        self.assertEqual(get_billing_period(self._dt(12, 0)), PeakValleyBillingConstants.PERIOD_OFF_PEAK)
        self.assertEqual(get_billing_period(self._dt(13, 0)), PeakValleyBillingConstants.PERIOD_OFF_PEAK)
        self.assertEqual(get_billing_period(self._dt(13, 59)), PeakValleyBillingConstants.PERIOD_OFF_PEAK)

    def test_off_peak_evening_and_night(self):
        """18:00 后至次日 9:00 前为空闲"""
        self.assertEqual(get_billing_period(self._dt(18, 0)), PeakValleyBillingConstants.PERIOD_OFF_PEAK)
        self.assertEqual(get_billing_period(self._dt(20, 0)), PeakValleyBillingConstants.PERIOD_OFF_PEAK)
        self.assertEqual(get_billing_period(self._dt(0, 0)), PeakValleyBillingConstants.PERIOD_OFF_PEAK)
        self.assertEqual(get_billing_period(self._dt(8, 59)), PeakValleyBillingConstants.PERIOD_OFF_PEAK)

    def test_boundaries(self):
        """边界值：高峰区间左闭右开"""
        # 9:00 进入高峰
        self.assertEqual(get_billing_period(self._dt(9, 0)), PeakValleyBillingConstants.PERIOD_PEAK)
        # 12:00 退出高峰
        self.assertEqual(get_billing_period(self._dt(12, 0)), PeakValleyBillingConstants.PERIOD_OFF_PEAK)
        # 14:00 再次进入高峰
        self.assertEqual(get_billing_period(self._dt(14, 0)), PeakValleyBillingConstants.PERIOD_PEAK)
        # 18:00 退出高峰
        self.assertEqual(get_billing_period(self._dt(18, 0)), PeakValleyBillingConstants.PERIOD_OFF_PEAK)


class TestWeekendRules(unittest.TestCase):
    """测试周末全天空闲规则（2026-08-23 00:00 北京时间起生效）"""

    def test_weekend_off_peak_after_effective(self):
        """生效后周六全天（含原高峰窗口 9-12 / 14-18）均为空闲"""
        # 2026-08-29 周六
        for hour, minute in ((0, 0), (9, 0), (11, 59), (12, 0), (14, 0), (17, 59), (23, 59)):
            self.assertEqual(
                get_billing_period(datetime(2026, 8, 29, hour, minute)),
                PeakValleyBillingConstants.PERIOD_OFF_PEAK,
                f"周六 {hour}:{minute:02d} 应为空闲",
            )

    def test_sunday_off_peak_after_effective(self):
        """生效后周日全天为空闲"""
        # 2026-08-30 周日
        self.assertEqual(get_billing_period(datetime(2026, 8, 30, 10, 0)),
                         PeakValleyBillingConstants.PERIOD_OFF_PEAK)
        self.assertEqual(get_billing_period(datetime(2026, 8, 30, 16, 30)),
                         PeakValleyBillingConstants.PERIOD_OFF_PEAK)

    def test_weekend_peak_before_effective(self):
        """生效前周末仍按小时窗口判高峰（历史补扣/对账按旧规则）"""
        # 2026-08-22 周六、2026-08-16 周日，均在生效时刻之前
        self.assertEqual(get_billing_period(datetime(2026, 8, 22, 10, 0)),
                         PeakValleyBillingConstants.PERIOD_PEAK)
        self.assertEqual(get_billing_period(datetime(2026, 8, 16, 15, 0)),
                         PeakValleyBillingConstants.PERIOD_PEAK)
        # 生效前周末夜间仍为空闲
        self.assertEqual(get_billing_period(datetime(2026, 8, 22, 20, 0)),
                         PeakValleyBillingConstants.PERIOD_OFF_PEAK)

    def test_effective_boundary(self):
        """生效时刻边界：2026-08-23 00:00（周日）起空闲"""
        # 边界前一刻（2026-08-22 23:59 周六夜间，旧规则本就是空闲）
        self.assertEqual(get_billing_period(datetime(2026, 8, 22, 23, 59)),
                         PeakValleyBillingConstants.PERIOD_OFF_PEAK)
        # 生效时刻本身（周日 00:00）
        self.assertEqual(get_billing_period(datetime(2026, 8, 23, 0, 0)),
                         PeakValleyBillingConstants.PERIOD_OFF_PEAK)
        # 对比：生效前一天周六 10:00 高峰 vs 生效后首个周末（8-29 周六）10:00 空闲
        self.assertEqual(get_billing_period(datetime(2026, 8, 22, 10, 0)),
                         PeakValleyBillingConstants.PERIOD_PEAK)
        self.assertEqual(get_billing_period(datetime(2026, 8, 29, 10, 0)),
                         PeakValleyBillingConstants.PERIOD_OFF_PEAK)

    def test_weekday_peak_still_applies_after_effective(self):
        """生效后工作日高峰窗口不变（2026-08-28 周五）"""
        self.assertEqual(get_billing_period(datetime(2026, 8, 28, 10, 0)),
                         PeakValleyBillingConstants.PERIOD_PEAK)
        self.assertEqual(get_billing_period(datetime(2026, 8, 28, 16, 0)),
                         PeakValleyBillingConstants.PERIOD_PEAK)
        # 工作日午间/夜间仍为空闲
        self.assertEqual(get_billing_period(datetime(2026, 8, 28, 13, 0)),
                         PeakValleyBillingConstants.PERIOD_OFF_PEAK)
        self.assertEqual(get_billing_period(datetime(2026, 8, 28, 21, 0)),
                         PeakValleyBillingConstants.PERIOD_OFF_PEAK)

    def test_weekend_rule_uses_bjt_weekday(self):
        """跨时区日期翻转后按北京星期/日期判定（UTC 16:00 后北京进入次日）"""
        # UTC 2026-08-28（周五）17:00 = BJT 2026-08-29（周六）01:00 → 周末空闲
        dt = datetime(2026, 8, 28, 17, 0, tzinfo=timezone.utc)
        self.assertEqual(get_billing_period(dt), PeakValleyBillingConstants.PERIOD_OFF_PEAK)
        # UTC 2026-08-29（周六）02:00 = BJT 周六 10:00（原高峰窗口）→ 生效后周末空闲
        dt_sat = datetime(2026, 8, 29, 2, 0, tzinfo=timezone.utc)
        self.assertEqual(get_billing_period(dt_sat), PeakValleyBillingConstants.PERIOD_OFF_PEAK)
        # 对照（生效前）：UTC 2026-08-22（周六）02:00 = BJT 周六 10:00 → 旧规则仍高峰
        dt_sat_old = datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc)
        self.assertEqual(get_billing_period(dt_sat_old), PeakValleyBillingConstants.PERIOD_PEAK)


class TestTimezoneConversion(unittest.TestCase):
    """测试 aware datetime 的时区转换"""

    def test_utc_to_bjt_peak(self):
        """UTC 01:00 = 北京 09:00 → 高峰"""
        dt = datetime(2026, 8, 13, 1, 0, tzinfo=timezone.utc)
        self.assertEqual(get_billing_period(dt), PeakValleyBillingConstants.PERIOD_PEAK)

    def test_utc_to_bjt_off_peak(self):
        """UTC 04:00 = 北京 12:00 → 空闲"""
        dt = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
        self.assertEqual(get_billing_period(dt), PeakValleyBillingConstants.PERIOD_OFF_PEAK)

    def test_other_timezone_to_bjt(self):
        """UTC-5 (纽约) 20:00 前一天 = 北京 09:00 → 高峰"""
        ny = timezone(timedelta(hours=-5))
        dt = datetime(2026, 8, 12, 20, 0, tzinfo=ny)  # = BJT 2026-08-13 09:00
        self.assertEqual(get_billing_period(dt), PeakValleyBillingConstants.PERIOD_PEAK)

    def test_to_bjt_naive_passthrough(self):
        """naive datetime 视为北京时间，原样返回"""
        dt = datetime(2026, 8, 13, 10, 0)
        self.assertEqual(to_bjt_naive(dt), dt)

    def test_to_bjt_naive_strips_tzinfo(self):
        """aware datetime 转换后去掉 tzinfo"""
        dt = datetime(2026, 8, 13, 1, 0, tzinfo=timezone.utc)
        result = to_bjt_naive(dt)
        self.assertIsNone(result.tzinfo)
        self.assertEqual(result.hour, 9)


class TestRobustness(unittest.TestCase):
    """测试异常输入兜底，确保扣费链路不中断"""

    def test_none_returns_current_period(self):
        """None 输入返回当前时段（不抛异常）"""
        result = get_billing_period(None)
        self.assertIn(result, (PeakValleyBillingConstants.PERIOD_PEAK,
                               PeakValleyBillingConstants.PERIOD_OFF_PEAK))

    def test_valid_string_parsed(self):
        """ISO 字符串能被解析"""
        self.assertEqual(get_billing_period('2026-08-13 10:30:00'), PeakValleyBillingConstants.PERIOD_PEAK)
        self.assertEqual(get_billing_period('2026-08-13T15:00:00'), PeakValleyBillingConstants.PERIOD_PEAK)

    def test_invalid_string_fallback(self):
        """无法解析的字符串回退当前时段（不抛异常）"""
        result = get_billing_period('not-a-date')
        self.assertIn(result, (PeakValleyBillingConstants.PERIOD_PEAK,
                               PeakValleyBillingConstants.PERIOD_OFF_PEAK))

    def test_to_bjt_naive_none(self):
        """to_bjt_naive(None) 返回当前北京时间"""
        result = to_bjt_naive(None)
        self.assertIsInstance(result, datetime)
        self.assertIsNone(result.tzinfo)


class TestResolveBillingPeriod(unittest.TestCase):
    """测试 resolve_billing_period 的兜底标记（区分调用时间判定 vs 当前时间估算）"""

    def test_valid_datetime_not_fallback(self):
        """正常 datetime：is_fallback=False"""
        period, is_fallback = resolve_billing_period(datetime(2026, 8, 13, 10, 0))
        self.assertEqual(period, PeakValleyBillingConstants.PERIOD_PEAK)
        self.assertFalse(is_fallback)

    def test_valid_string_not_fallback(self):
        """可解析的 ISO 字符串：is_fallback=False"""
        period, is_fallback = resolve_billing_period('2026-08-29 10:00:00')
        self.assertEqual(period, PeakValleyBillingConstants.PERIOD_OFF_PEAK)  # 周六
        self.assertFalse(is_fallback)

    def test_none_is_fallback(self):
        """None：按当前时间估算，is_fallback=True"""
        period, is_fallback = resolve_billing_period(None)
        self.assertIn(period, (PeakValleyBillingConstants.PERIOD_PEAK,
                               PeakValleyBillingConstants.PERIOD_OFF_PEAK))
        self.assertTrue(is_fallback)

    def test_invalid_string_is_fallback(self):
        """无法解析的字符串：is_fallback=True"""
        period, is_fallback = resolve_billing_period('not-a-date')
        self.assertIn(period, (PeakValleyBillingConstants.PERIOD_PEAK,
                               PeakValleyBillingConstants.PERIOD_OFF_PEAK))
        self.assertTrue(is_fallback)

    def test_non_datetime_type_is_fallback(self):
        """非日期类型（如 int）：is_fallback=True，不抛异常"""
        period, is_fallback = resolve_billing_period(20260829)
        self.assertIn(period, (PeakValleyBillingConstants.PERIOD_PEAK,
                               PeakValleyBillingConstants.PERIOD_OFF_PEAK))
        self.assertTrue(is_fallback)

    def test_consistent_with_get_billing_period(self):
        """get_billing_period 与 resolve_billing_period 的时段结果一致"""
        for dt in (datetime(2026, 8, 28, 10, 0), datetime(2026, 8, 29, 15, 0), None, 'bad'):
            self.assertEqual(get_billing_period(dt), resolve_billing_period(dt)[0])


if __name__ == '__main__':
    unittest.main()
