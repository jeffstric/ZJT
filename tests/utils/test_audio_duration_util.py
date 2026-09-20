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
_const.SEEDANCE_R2V_AUDIO_TOTAL_DURATION_SAFETY_MARGIN = 0.5
_const.SEEDANCE_R2V_AUDIO_TRIM_TIMEOUT = 30
sys.modules['config.constant'] = _const

_proj = types.ModuleType('utils.project_path')
_proj.get_project_root = MagicMock(return_value='/project')
_proj.resolve_upload_url_to_local_path = MagicMock(side_effect=lambda p: f'/project/{p}')
sys.modules['utils.project_path'] = _proj

from utils.audio_duration_util import (
    get_audio_duration_seconds,
    probe_audio_duration,
    prepare_reference_audio_budget_sync,
    cleanup_prepared_reference_audio,
    trim_audio_to_duration,
)

# 立即恢复被 mock 的全局模块，避免 pytest 收集其它测试文件时导入到瘦身版 config.constant。
for _key, _saved in _saved_modules.items():
    if _saved is not None:
        sys.modules[_key] = _saved
    else:
        sys.modules.pop(_key, None)


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


class TestPrepareReferenceAudioBudget(unittest.TestCase):
    """测试 prepare_reference_audio_budget_sync() 均分配额与截断决策（mock 子进程）"""

    def test_empty_paths_returns_empty(self):
        """空输入返回空列表"""
        self.assertEqual(prepare_reference_audio_budget_sync([], 15.0), [])

    @patch('utils.audio_duration_util.trim_audio_to_duration')
    @patch('utils.audio_duration_util.get_audio_duration_seconds')
    def test_even_split_and_trim_over_limit(self, mock_probe, mock_trim):
        """两条音频（20s/3s）预算 15s：配额 (15-0.5)/2=7.25，超限条目截断到临时文件"""
        mock_probe.side_effect = lambda p: {'/a.mp3': 20.0, '/b.mp3': 3.0}.get(p)
        mock_trim.return_value = (True, '/tmp/trimmed.mp3', None)

        items = prepare_reference_audio_budget_sync(['/a.mp3', '/b.mp3'], 15.0)

        self.assertEqual(len(items), 2)
        # 第一条超配额：path 换成截断临时文件，cleanup 指向它
        self.assertEqual(items[0]['path'], '/tmp/trimmed.mp3')
        self.assertEqual(items[0]['cleanup_path'], '/tmp/trimmed.mp3')
        self.assertEqual(items[0]['duration'], 20.0)
        self.assertAlmostEqual(items[0]['limit_seconds'], 7.25, places=6)
        mock_trim.assert_called_once_with('/a.mp3', 7.25)
        # 第二条未超配额：原样放行，不产生临时文件
        self.assertEqual(items[1]['path'], '/b.mp3')
        self.assertIsNone(items[1]['cleanup_path'])

    @patch('utils.audio_duration_util.trim_audio_to_duration')
    @patch('utils.audio_duration_util.get_audio_duration_seconds')
    def test_three_items_budget_values(self, mock_probe, mock_trim):
        """用户场景数值：mini 3 条 → 配额 14.5/3；2.5 3 条 → 29.5/3"""
        mock_probe.return_value = 20.0
        mock_trim.return_value = (True, '/tmp/t.mp3', None)

        items_mini = prepare_reference_audio_budget_sync(
            ['/a.mp3', '/b.mp3', '/c.mp3'], 15.0)
        self.assertAlmostEqual(items_mini[0]['limit_seconds'],
                               (15.0 - 0.5) / 3, places=6)

        items_25 = prepare_reference_audio_budget_sync(
            ['/a.mp3', '/b.mp3', '/c.mp3'], 30.0)
        self.assertAlmostEqual(items_25[0]['limit_seconds'],
                               (30.0 - 0.5) / 3, places=6)

    @patch('utils.audio_duration_util.trim_audio_to_duration')
    @patch('utils.audio_duration_util.get_audio_duration_seconds')
    def test_under_budget_passthrough(self, mock_probe, mock_trim):
        """全部未超配额：原样放行，不触发截断"""
        mock_probe.return_value = 5.0
        items = prepare_reference_audio_budget_sync(['/a.mp3'], 15.0)
        self.assertEqual(items[0]['path'], '/a.mp3')
        self.assertIsNone(items[0]['cleanup_path'])
        mock_trim.assert_not_called()

    @patch('utils.audio_duration_util.trim_audio_to_duration')
    @patch('utils.audio_duration_util.get_audio_duration_seconds')
    def test_probe_failure_passthrough(self, mock_probe, mock_trim):
        """时长探测失败：原样放行（不截断、不扣预算）"""
        mock_probe.return_value = None
        items = prepare_reference_audio_budget_sync(['/a.mp3'], 15.0)
        self.assertEqual(items[0]['path'], '/a.mp3')
        self.assertIsNone(items[0]['cleanup_path'])
        mock_trim.assert_not_called()

    @patch('utils.audio_duration_util.trim_audio_to_duration')
    @patch('utils.audio_duration_util.get_audio_duration_seconds')
    def test_trim_failure_passthrough(self, mock_probe, mock_trim):
        """截断失败：原样放行（维持无预算时的行为）"""
        mock_probe.return_value = 20.0
        mock_trim.return_value = (False, None, 'ffmpeg error')
        items = prepare_reference_audio_budget_sync(['/a.mp3'], 15.0)
        self.assertEqual(items[0]['path'], '/a.mp3')
        self.assertIsNone(items[0]['cleanup_path'])


class TestTrimAudioToDuration(unittest.TestCase):
    """测试 trim_audio_to_duration()（mock subprocess，临时文件用真实文件系统）"""

    @patch('utils.audio_duration_util.subprocess.run')
    def test_success_returns_trimmed_path(self, mock_run):
        """ffmpeg 成功：返回临时文件路径（内容非空），调用方负责清理"""
        def side_effect(cmd, **kwargs):
            # 模拟 ffmpeg 写出非空产物（trim 检查 size > 0）
            with open(cmd[-1], 'wb') as f:
                f.write(b'fake-audio-bytes')
            return MagicMock(returncode=0, stdout='', stderr='')

        mock_run.side_effect = side_effect
        success, trimmed, error = trim_audio_to_duration('/a.mp3', 4.83)
        self.assertTrue(success)
        self.assertIsNotNone(trimmed)
        self.assertIsNone(error)
        # -t 参数为配额值
        cmd = mock_run.call_args[0][0]
        self.assertIn('4.830', cmd)
        # 清理产物
        import os as _os
        _os.remove(trimmed)

    @patch('utils.audio_duration_util.subprocess.run')
    def test_failure_cleans_temp_file(self, mock_run):
        """ffmpeg 失败：清理半成品临时文件并返回失败"""
        def side_effect(cmd, **kwargs):
            with open(cmd[-1], 'wb') as f:
                f.write(b'partial')
            return MagicMock(returncode=1, stdout='', stderr='boom')

        mock_run.side_effect = side_effect
        import os as _os
        # 记录 mkstemp 产生的临时文件：通过首轮调用捕获再复现不可行，改为检查
        # 失败后系统临时目录中不存在 seedance_audio_trim_ 残留
        import glob as _glob
        import tempfile as _tempfile
        success, trimmed, error = trim_audio_to_duration('/a.mp3', 4.83)
        self.assertFalse(success)
        self.assertIsNone(trimmed)
        self.assertIn('boom', error)
        leftovers = _glob.glob(_os.path.join(_tempfile.gettempdir(), 'seedance_audio_trim_*'))
        self.assertEqual(leftovers, [])

    @patch('utils.audio_duration_util.subprocess.run')
    def test_timeout_cleans_temp_file(self, mock_run):
        """ffmpeg 超时：返回失败且不残留临时文件"""
        import os as _os
        import glob as _glob
        import tempfile as _tempfile
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='ffmpeg', timeout=30)
        success, trimmed, error = trim_audio_to_duration('/a.mp3', 4.83)
        self.assertFalse(success)
        self.assertIsNone(trimmed)
        leftovers = _glob.glob(_os.path.join(_tempfile.gettempdir(), 'seedance_audio_trim_*'))
        self.assertEqual(leftovers, [])

    def test_invalid_max_seconds(self):
        """max_seconds 非正：直接失败，不调用 ffmpeg"""
        with patch('utils.audio_duration_util.subprocess.run') as mock_run:
            success, trimmed, error = trim_audio_to_duration('/a.mp3', 0)
            self.assertFalse(success)
            self.assertIsNone(trimmed)
            mock_run.assert_not_called()


class TestCleanupPreparedReferenceAudio(unittest.TestCase):
    """测试 cleanup_prepared_reference_audio() 幂等清理"""

    def test_removes_temp_files(self):
        """删除 cleanup_path 指向的真实文件；None/缺失字段安全跳过"""
        import os as _os
        import tempfile as _tempfile
        fd, path = _tempfile.mkstemp(prefix='seedance_audio_trim_test_')
        _os.close(fd)
        with open(path, 'wb') as f:
            f.write(b'x')
        items = [
            {'cleanup_path': path},
            {'cleanup_path': None},
            {},
            None,
        ]
        cleanup_prepared_reference_audio(items)
        self.assertFalse(_os.path.exists(path))
        # 幂等：再次调用不抛异常
        cleanup_prepared_reference_audio(items)


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
