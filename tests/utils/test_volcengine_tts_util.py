"""
volcengine_tts_util 单元测试

覆盖：
- V3ChunkDecoder 帧解析（官方布局/sequence/gzip/尾部size变体/半帧重组/error帧/缓冲超限）
- calc_volcengine_tts_power 字符档位计价边界
- normalize_volcengine_tts_speed 语速归一化
- synthesize_speech 未配置凭证的友好错误路径

外部依赖（config.config_util）用 stub 前置，不读真实配置文件。
"""
import asyncio
import base64
import gzip
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
)
from utils.volcengine_tts_util import (  # noqa: E402
    V3ChunkDecoder,
    build_audio_filename,
    synthesize_speech,
)


def make_frame(payload: dict, msg_type: int = 0x9, seq: bool = False,
               gzip_on: bool = False, protocol: int = 0x01) -> bytes:
    """构造官方 v3 协议帧"""
    p = json.dumps(payload).encode('utf-8')
    if gzip_on:
        p = gzip.compress(p)
    b0 = (protocol << 4) | (msg_type & 0x0F)
    b1 = 0x10 if seq else 0x00
    b2 = (0x01 << 4) | (0x01 if gzip_on else 0x00)  # JSON 序列化
    head = bytes([b0, b1, b2, 0x00]) + (b'\x00\x01' if seq else b'')
    return head + p


def make_tail_size_frame(payload: dict) -> bytes:
    """构造社区变体帧：4字节头 + payload + 尾部4字节 payload_size"""
    body = json.dumps(payload).encode('utf-8')
    return bytes([0x19, 0x00, 0x10, 0x00]) + body + len(body).to_bytes(4, 'big')


B64_AUDIO = base64.b64encode(b'\xff\xfb\x90fakeaudio').decode('ascii')


class TestV3ChunkDecoder(unittest.TestCase):

    def test_plain_json_frame(self):
        d = V3ChunkDecoder()
        msgs = d.feed(make_frame({"data": B64_AUDIO, "is_last": True, "code": 0}))
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0][0], 0x9)
        self.assertEqual(msgs[0][1]["is_last"], True)

    def test_frame_with_sequence_and_gzip(self):
        d = V3ChunkDecoder()
        msgs = d.feed(make_frame({"data": B64_AUDIO, "code": 0}, seq=True, gzip_on=True))
        self.assertEqual(msgs[0][1]["data"], B64_AUDIO)

    def test_half_frame_reassembly(self):
        """一个协议帧被 TCP/chunk 边界切开也能重组"""
        d = V3ChunkDecoder()
        frame = make_frame({"data": B64_AUDIO, "is_last": True, "code": 0})
        half = len(frame) // 2
        self.assertEqual(d.feed(frame[:half]), [])
        msgs = d.feed(frame[half:])
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0][1]["is_last"])

    def test_tail_size_layout(self):
        d = V3ChunkDecoder()
        msgs = d.feed(make_tail_size_frame({"data": B64_AUDIO, "is_last": True}))
        self.assertEqual(msgs[0][1]["data"], B64_AUDIO)

    def test_error_frame_type(self):
        d = V3ChunkDecoder()
        msgs = d.feed(make_frame({"code": 3001, "message": "bad voice"}, msg_type=0xF))
        self.assertEqual(msgs[0][0], 0xF)
        self.assertEqual(msgs[0][1]["code"], 3001)

    def test_multiple_frames_in_buffer(self):
        """布局 B 两帧拼在同一 chunk：长度不精确吻合时保守返回 0 条（等待
        更多数据），绝不产出错误消息。注：官方协议按消息边界 flush（每 chunk
        一帧），多帧拼接本身不会出现，此处仅锁定"不误判"行为。"""
        d = V3ChunkDecoder()
        blob = make_tail_size_frame({"data": B64_AUDIO}) + make_tail_size_frame({"is_last": True})
        msgs = d.feed(blob)
        self.assertEqual(len(msgs), 0)

    def test_buffer_limit_raises(self):
        d = V3ChunkDecoder()
        with self.assertRaises(ValueError):
            # 头部合法但 payload 永远不是 JSON → 缓冲累积至超限
            d.feed(bytes([0x19, 0x00, 0x10, 0x00]) + b'\x00' * (32 * 1024 * 1024))


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
        """浮点字符数按 int 截断处理（正常调用方传 len() 整数）"""
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

    def test_rounding(self):
        self.assertEqual(normalize_volcengine_tts_speed(1.234), 1.23)


class TestVoiceSeedList(unittest.TestCase):

    def test_seed_list_shape(self):
        """种子清单字段完整性（迁移直接消费该清单）"""
        required = {'voice_type', 'name', 'gender', 'language', 'style', 'description', 'sort_order'}
        seen = set()
        for item in VOLCENGINE_TTS_VOICES:
            self.assertTrue(required.issubset(item.keys()), f"缺字段: {item}")
            self.assertNotIn(item['voice_type'], seen, f"音色重复: {item['voice_type']}")
            seen.add(item['voice_type'])


class TestSynthesizeUnconfigured(unittest.TestCase):

    def test_unconfigured_returns_friendly_error(self):
        with patch('utils.volcengine_tts_util.get_dynamic_config_value', return_value=None):
            ok, audio, msg = asyncio.run(synthesize_speech("你好", "BV700_streaming"))
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
