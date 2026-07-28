"""
VideoCompressor 纯逻辑单元测试

测试 needs_compression() 的阈值判断逻辑。
"""
import sys
import unittest
from unittest.mock import MagicMock

# Mock config 模块（import 前置）
_saved_config_util = sys.modules.get('config.config_util')
_saved_project_path = sys.modules.get('utils.project_path')
sys.modules['config.config_util'] = MagicMock()
sys.modules['utils.project_path'] = MagicMock()

import utils.video_compressor as video_compressor
from utils.video_compressor import needs_compression

# 恢复 config.config_util 和 utils.project_path，防止污染后续测试
if _saved_config_util is not None:
    sys.modules['config.config_util'] = _saved_config_util
else:
    sys.modules.pop('config.config_util', None)
if _saved_project_path is not None:
    sys.modules['utils.project_path'] = _saved_project_path
else:
    sys.modules.pop('utils.project_path', None)


class TestNeedsCompression(unittest.TestCase):
    """测试 needs_compression() 的视频压缩判断逻辑"""

    def test_landscape_exceeds(self):
        """横屏视频最短边超过阈值，需要压缩"""
        info = {"width": 1280, "height": 720}
        self.assertTrue(needs_compression(info))

    def test_portrait_exceeds(self):
        """竖屏视频最短边超过阈值，需要压缩"""
        info = {"width": 720, "height": 1280}
        self.assertTrue(needs_compression(info))

    def test_square_exceeds(self):
        """方形视频边长超过阈值，需要压缩"""
        info = {"width": 1000, "height": 1000}
        self.assertTrue(needs_compression(info))

    def test_landscape_within(self):
        """横屏视频最短边等于阈值（480），不需要压缩"""
        info = {"width": 854, "height": 480}
        self.assertFalse(needs_compression(info))

    def test_square_exactly_threshold(self):
        """方形视频边长恰好等于阈值（480），不需要压缩"""
        info = {"width": 480, "height": 480}
        self.assertFalse(needs_compression(info))

    def test_none_returns_true(self):
        """None 输入视为需要压缩"""
        self.assertTrue(needs_compression(None))

    def test_empty_dict_returns_true(self):
        """空 dict 输入视为需要压缩（空 dict 为 falsy）"""
        self.assertTrue(needs_compression({}))

    def test_custom_threshold(self):
        """自定义阈值：720x1280 在 max=800 时不需压缩"""
        info = {"width": 720, "height": 1280}
        self.assertFalse(needs_compression(info, max_shortest_edge=800))

    def test_zero_dimensions(self):
        """宽高均为 0 时，最短边 0 不超过阈值，不需要压缩"""
        info = {"width": 0, "height": 0}
        self.assertFalse(needs_compression(info))

    def test_below_threshold(self):
        """小于阈值的视频不需要压缩"""
        info = {"width": 320, "height": 240}
        self.assertFalse(needs_compression(info))

    def test_missing_width_key(self):
        """缺少 width 键时，默认取 0，最短边 0 不超过阈值"""
        info = {"height": 720}
        self.assertFalse(needs_compression(info))

    def test_missing_height_key(self):
        """缺少 height 键时，默认取 0，最短边 0 不超过阈值"""
        info = {"width": 720}
        self.assertFalse(needs_compression(info))

    def test_custom_threshold_exceeds(self):
        """自定义阈值：视频最短边超过自定义阈值时需要压缩"""
        info = {"width": 1280, "height": 720}
        self.assertTrue(needs_compression(info, max_shortest_edge=360))

    def test_one_dimension_zero(self):
        """一个维度为 0，最短边为 0，不需要压缩"""
        info = {"width": 0, "height": 720}
        self.assertFalse(needs_compression(info))


class TestReferenceVideoPixelCount(unittest.TestCase):
    """测试参考视频像素下限校验逻辑"""

    def test_reference_video_pixel_validator_exists(self):
        """视频工具应提供参考视频像素下限校验函数"""
        self.assertTrue(hasattr(video_compressor, "is_reference_video_pixel_count_valid"))

    def test_rejects_640x368_below_seedance_minimum(self):
        """640x368 低于 409600 像素，不满足 Seedance r2v 参考视频要求"""
        validator = getattr(video_compressor, "is_reference_video_pixel_count_valid", lambda info: False)
        self.assertFalse(validator({"width": 640, "height": 368}))

    def test_accepts_even_dimensions_over_minimum_when_short_edge_exceeds_480(self):
        """846x486 虽然短边超过 480，但总像素满足参考视频下游要求，应允许上传"""
        validator = getattr(video_compressor, "is_reference_video_pixel_count_valid", lambda info: False)
        self.assertTrue(validator({"width": 846, "height": 486}))


class TestParseFrameRate(unittest.TestCase):
    """测试 _parse_frame_rate() 的 ffprobe avg_frame_rate 字符串解析"""

    def test_high_refresh_rate_integer(self):
        """高刷屏产出的 120fps（"120/1"）应解析为 120.0"""
        self.assertAlmostEqual(video_compressor._parse_frame_rate("120/1"), 120.0)

    def test_common_24fps(self):
        """影视常见 24fps（"24/1"）应解析为 24.0"""
        self.assertAlmostEqual(video_compressor._parse_frame_rate("24/1"), 24.0)

    def test_ntsc_fractional(self):
        """NTSC 29.97fps（"30000/1001"）应解析为约 29.97"""
        self.assertAlmostEqual(video_compressor._parse_frame_rate("30000/1001"), 29.97, places=2)

    def test_zero_denominator(self):
        """分母为 0（"0/0"，常见于无固定帧率视频）应返回 0.0，不抛异常"""
        self.assertEqual(video_compressor._parse_frame_rate("0/0"), 0.0)

    def test_plain_number_string(self):
        """纯数字字符串（无斜杠）应能解析"""
        self.assertAlmostEqual(video_compressor._parse_frame_rate("30"), 30.0)

    def test_empty_string(self):
        """空字符串返回 0.0"""
        self.assertEqual(video_compressor._parse_frame_rate(""), 0.0)

    def test_none_input(self):
        """None 输入返回 0.0，不抛异常"""
        self.assertEqual(video_compressor._parse_frame_rate(None), 0.0)

    def test_invalid_string(self):
        """无法解析的字符串返回 0.0，不抛异常"""
        self.assertEqual(video_compressor._parse_frame_rate("abc"), 0.0)


if __name__ == '__main__':
    unittest.main()
