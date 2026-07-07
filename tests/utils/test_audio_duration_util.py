"""
audio_duration_util 单元测试

测试 ffprobe 音频时长探测的纯逻辑分支。
所有外部依赖（ffprobe 进程、config）均使用 mock，不依赖真实文件。
"""
import asyncio
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

# Mock 外部依赖（import 前置）
_saved_modules = {
    'config.config_util': sys.modules.get('config.config_util'),
    'config.constant': sys.modules.get('config.constant'),
    'utils.project_path': sys.modules.get('utils.project_path'),
}

_cfg = MagicMock()
_cfg.get_config_path = MagicMock(return_value='config_prod.yml')
import types
_cfg_util = types.ModuleType('config.config_util')
_cfg_util.get_config_path = MagicMock(return_value='config_prod.yml')
_cfg_util.resolve_bin_path = MagicMock(return_value='/usr/bin/ffprobe')
sys.modules['config.config_util'] = _cfg_util

_const = types.ModuleType('config.constant')
_const.FFPROBE_AUDIO_DURATION_TIMEOUT = 30
sys.modules['config.constant'] = _const

_proj = types.ModuleType('utils.project_path')
_proj.get_project_root = MagicMock(return_value='/project')
sys.modules['utils.project_path'] = _proj

from utils.audio_duration_util import get_audio_duration_seconds, probe_audio_duration


class TestGetAudioDurationSeconds(unittest.TestCase):
    """测试 get_audio_duration_seconds()"""

    def test_empty_input_returns_none(self):
        """空字符串输入返回 None"""
        self.assertIsNone(get_audio_duration_seconds(''))
        self.assertIsNone(get_audio_duration_seconds(None))

    @patch('utils.audio_duration_util.subprocess.run')
    def test_success_returns_duration(self, mock_run):
        """ffprobe 成功时返回解析后的秒数"""
        mock_run.return_value = MagicMock(returncode=0, stdout='9.523000\n', stderr='')
        result = get_audio_duration_seconds('http://example.com/a.wav')
        self.assertAlmostEqual(result, 9.523, places=3)

    @patch('utils.audio_duration_util.subprocess.run')
    def test_nonzero_returncode_returns_none(self, mock_run):
        """ffprobe 返回非零退出码时返回 None（不抛异常）"""
        mock_run.return_value = MagicMock(returncode=1, stdout='', stderr='Invalid data')
        result = get_audio_duration_seconds('/nonexist.wav')
        self.assertIsNone(result)

    @patch('utils.audio_duration_util.subprocess.run')
    def test_empty_stdout_returns_none(self, mock_run):
        """ffprobe 输出为空时返回 None"""
        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')
        result = get_audio_duration_seconds('/some.wav')
        self.assertIsNone(result)

    @patch('utils.audio_duration_util.subprocess.run')
    def test_unparseable_stdout_returns_none(self, mock_run):
        """ffprobe 输出无法解析为 float 时返回 None"""
        mock_run.return_value = MagicMock(returncode=0, stdout='N/A\n', stderr='')
        result = get_audio_duration_seconds('/some.wav')
        self.assertIsNone(result)

    @patch('utils.audio_duration_util.subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='ffprobe', timeout=30))
    def test_timeout_returns_none(self, mock_run):
        """ffprobe 超时返回 None"""
        result = get_audio_duration_seconds('http://slow/audio.wav')
        self.assertIsNone(result)

    @patch('utils.audio_duration_util.subprocess.run', side_effect=FileNotFoundError("ffprobe not found"))
    def test_ffprobe_not_found_returns_none(self, mock_run):
        """ffprobe 可执行文件找不到时返回 None"""
        result = get_audio_duration_seconds('/some.wav')
        self.assertIsNone(result)


class TestProbeAudioDuration(unittest.TestCase):
    """测试 probe_audio_duration() 异步包装"""

    def test_async_wraps_sync_result(self):
        """异步包装正确返回同步函数的结果"""
        with patch('utils.audio_duration_util.get_audio_duration_seconds', return_value=12.5):
            result = asyncio.run(probe_audio_duration('http://example.com/a.wav'))
            self.assertAlmostEqual(result, 12.5, places=3)

    def test_async_wraps_none(self):
        """同步函数返回 None 时异步包装也返回 None"""
        with patch('utils.audio_duration_util.get_audio_duration_seconds', return_value=None):
            result = asyncio.run(probe_audio_duration('http://example.com/a.wav'))
            self.assertIsNone(result)


# 恢复被 mock 的 sys.modules
import unittest as _ut


def tearDownModule():
    for _key, _saved in _saved_modules.items():
        if _saved is not None:
            sys.modules[_key] = _saved
        else:
            sys.modules.pop(_key, None)


if __name__ == '__main__':
    unittest.main()
