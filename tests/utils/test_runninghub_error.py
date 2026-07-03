"""
RunningHub 上游拥堵错误识别单元测试

验证 is_upstream_congested_error 通过 errorCode == '421' 精确识别上游并发超限（队列上限），
且对其他 errorCode 不误判。识别正确性是「自动延迟重试」机制的基础。
"""
import unittest

from utils.runninghub_error import is_upstream_congested_error


class TestIsUpstreamCongestedError(unittest.TestCase):
    """测试 is_upstream_congested_error()"""

    # ---- errorCode == 421 应识别为上游拥堵（返回 True）----
    def test_error_code_421_string(self):
        """errorCode='421'（字符串）应命中"""
        self.assertTrue(is_upstream_congested_error('421'))

    def test_error_code_421_int(self):
        """errorCode=421（数字）也应命中（内部 str() 兼容）"""
        self.assertTrue(is_upstream_congested_error(421))

    def test_real_upstream_congested(self):
        """上游并发超限场景（errorCode=421）命中"""
        self.assertTrue(is_upstream_congested_error('421'))

    # ---- 其他 errorCode 不应误判（返回 False）----
    def test_other_error_codes(self):
        """其他 errorCode 不命中"""
        self.assertFalse(is_upstream_congested_error('INVALID_PARAM'))
        self.assertFalse(is_upstream_congested_error('TASK_QUEUE_MAXED'))  # 不再按旧码/关键词识别
        self.assertFalse(is_upstream_congested_error('500'))
        self.assertFalse(is_upstream_congested_error('0'))

    def test_empty_or_none(self):
        """空值不命中"""
        self.assertFalse(is_upstream_congested_error(''))
        self.assertFalse(is_upstream_congested_error(None))


if __name__ == '__main__':
    unittest.main()
