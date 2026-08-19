"""
峰谷计费时段判断单元测试
测试 utils.billing_period 模块：北京时间高峰/空闲时段判断、时区转换、异常兜底。

DeepSeek 峰谷规则：高峰 9:00-12:00、14:00-18:00（左闭右开），其余空闲。
"""
import unittest
from datetime import datetime, timezone, timedelta

from utils.billing_period import get_billing_period, to_bjt_naive
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


if __name__ == '__main__':
    unittest.main()
