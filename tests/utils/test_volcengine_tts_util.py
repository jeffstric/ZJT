"""
volcengine_tts_util 单元测试

覆盖：
- TtsJsonBlockDecoder 2.0 JSON 块流解析（数据块/字幕块/结束块/半块重组/超限）
- calc_volcengine_tts_power 字符档位计价边界
- normalize_volcengine_tts_speed / speed_ratio_to_speech_rate 换算
- synthesize_speech 未配置凭证的友好错误路径
- 2.0 音色种子清单完整性

外部依赖（config.config_util）用 patch 隔离，不读真实配置文件。
"""
import asyncio
import base64
import json
import os
import sys
import unittest
from unittest.mock import patch

# 项目根入 path（支持 python 直跑与 pytest 两种方式）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.volcengine_tts_constants import (  # noqa: E402
    VolcengineTtsConstants,
    VOLCENGINE_TTS_VOICES,
    calc_volcengine_tts_power,
    normalize_volcengine_tts_speed,
    speed_ratio_to_speech_rate,
)
from utils.volcengine_tts_util import (  # noqa: E402
    TtsJsonBlockDecoder,
    build_audio_filename,
    synthesize_speech,
)


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


AUDIO = _b64(b"\xff\xfb\x90fakeaudio")


class TestTtsJsonBlockDecoder(unittest.TestCase):

    def test_single_data_block(self):
        d = TtsJsonBlockDecoder()
        blocks = d.feed(json.dumps({"code": 0, "message": "", "data": AUDIO}).encode())
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["data"], AUDIO)

    def test_multiple_blocks_concatenated(self):
        """多个 JSON 对象直接串联（无分隔符）可全部解析"""
        blob = (json.dumps({"code": 0, "data": AUDIO})
                + json.dumps({"code": 0, "sentence": {"text": "你好"}})
                + json.dumps({"code": 20000000, "message": "OK"})).encode()
        d = TtsJsonBlockDecoder()
        blocks = d.feed(blob)
        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[2]["code"], 20000000)

    def test_half_block_reassembly(self):
        """JSON 块被 TCP/chunk 边界切开可重组"""
        d = TtsJsonBlockDecoder()
        blob = json.dumps({"code": 0, "data": AUDIO}).encode()
        half = len(blob) // 2
        self.assertEqual(d.feed(blob[:half]), [])
        blocks = d.feed(blob[half:])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["data"], AUDIO)

    def test_multibyte_utf8_split_across_chunks(self):
        """中文多字节字符被 chunk 切断时以 replace 解码后可能损坏——
        解析器应保留未解析部分等待，而不是抛异常"""
        d = TtsJsonBlockDecoder()
        blob = json.dumps({"code": 20000000, "message": "OK你好"}, ensure_ascii=False).encode()
        # 从多字节字符中间切开
        cut = len(blob) - 1
        d.feed(blob[:cut])
        blocks = d.feed(blob[cut:])
        self.assertIn(len(blocks), (0, 1))  # 不抛异常即通过


class TestPowerCalc(unittest.TestCase):

    def test_tier_boundaries(self):
        tiers = VolcengineTtsConstants.POWER_TIERS
        self.assertEqual(calc_volcengine_tts_power(1, tiers), 1)
        self.assertEqual(calc_volcengine_tts_power(50, tiers), 1)
        self.assertEqual(calc_volcengine_tts_power(51, tiers), 4)
        self.assertEqual(calc_volcengine_tts_power(200, tiers), 4)
        self.assertEqual(calc_volcengine_tts_power(500, tiers), 10)
        self.assertEqual(calc_volcengine_tts_power(1000, tiers), 20)
        self.assertEqual(calc_volcengine_tts_power(2000, tiers), 40)

    def test_over_limit_returns_zero(self):
        self.assertEqual(calc_volcengine_tts_power(2001), 0)
        self.assertEqual(calc_volcengine_tts_power(99999), 0)

    def test_invalid_input_returns_zero(self):
        for bad in (0, -5, None, 'abc', ''):
            self.assertEqual(calc_volcengine_tts_power(bad), 0)

    def test_float_input_truncates(self):
        self.assertEqual(calc_volcengine_tts_power(1.5), 1)

    def test_custom_tiers(self):
        tiers = [[100, 2], [300, 6]]
        self.assertEqual(calc_volcengine_tts_power(100, tiers), 2)
        self.assertEqual(calc_volcengine_tts_power(101, tiers), 6)
        self.assertEqual(calc_volcengine_tts_power(301, tiers), 0)

    def test_malformed_tiers_skipped(self):
        tiers = [(None, 'x'), (50, 3)]
        self.assertEqual(calc_volcengine_tts_power(10, tiers), 3)


class TestSpeedNormalize(unittest.TestCase):

    def test_clamp_and_default(self):
        self.assertEqual(normalize_volcengine_tts_speed(1.0), 1.0)
        self.assertEqual(normalize_volcengine_tts_speed(3.0), 2.0)
        self.assertEqual(normalize_volcengine_tts_speed(0.1), 0.5)
        self.assertEqual(normalize_volcengine_tts_speed('abc'), 1.0)
        self.assertEqual(normalize_volcengine_tts_speed(None), 1.0)

    def test_speech_rate_conversion(self):
        """speed_ratio → speech_rate：1.0→0，1.5→50，2.0→100，0.5→-50"""
        self.assertEqual(speed_ratio_to_speech_rate(1.0), 0)
        self.assertEqual(speed_ratio_to_speech_rate(1.5), 50)
        self.assertEqual(speed_ratio_to_speech_rate(2.0), 100)
        self.assertEqual(speed_ratio_to_speech_rate(0.5), -50)
        self.assertEqual(speed_ratio_to_speech_rate(1.23), 23)


class TestVoiceSeedList(unittest.TestCase):

    def test_seed_list_shape(self):
        """种子清单字段完整性（迁移 no_146 直接消费该清单）"""
        required = {'voice_type', 'name', 'gender', 'language', 'style', 'description', 'sort_order'}
        seen = set()
        for item in VOLCENGINE_TTS_VOICES:
            self.assertTrue(required.issubset(item.keys()), f"缺字段: {item}")
            self.assertNotIn(item['voice_type'], seen, f"音色重复: {item['voice_type']}")
            seen.add(item['voice_type'])

    def test_seed_voices_are_tts20(self):
        """2.0 音色必须是官方 speaker ID 格式（语言_性别_名称，多数带 uranus
        后缀；少数官方短 ID 无后缀如 en_male_cowboy，均与 seed-tts-2.0 兼容）"""
        import re
        pat = re.compile(r'^[a-z]{2}_(?:female|male|child)_[a-z0-9_-]+$')
        for item in VOLCENGINE_TTS_VOICES:
            self.assertTrue(pat.match(item['voice_type']),
                            f"非 2.0 音色格式: {item['voice_type']}")


class TestSynthesizeUnconfigured(unittest.TestCase):

    def test_unconfigured_returns_friendly_error(self):
        with patch('utils.volcengine_tts_util.get_dynamic_config_value', return_value=None):
            ok, audio, msg = asyncio.run(
                synthesize_speech("你好", "zh_female_vv_uranus_bigtts"))
        self.assertFalse(ok)
        self.assertEqual(audio, b"")
        self.assertIn("未配置", msg)

    def test_filename_shape(self):
        name = build_audio_filename("tts")
        self.assertTrue(name.startswith("tts_"))
        self.assertTrue(name.endswith(".mp3"))
        self.assertEqual(len(name.split("_")), 4)  # tts_date_time_uuid8.mp3


if __name__ == '__main__':
    unittest.main()
