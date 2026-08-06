"""
FaceMaskUtil 模块导入与基础功能单元测试

该模块依赖 cv2、numpy、subprocess 等重量级外部库，
本测试验证模块在 mock 环境下能正确导入，
并测试 _log_ffmpeg_error 的基本行为。

注意：
- 不要在模块级长期替换 sys.modules['numpy']/['cv2']，会污染后续依赖真实 numpy 的测试
  （例如 image_grid_validator）。
- overlay_face_mask 的完整逻辑需要集成测试覆盖。
"""
import sys
import unittest
from unittest.mock import MagicMock, patch

from utils.face_mask_util import (
    _log_ffmpeg_error,
    _map_mask_frame_index,
    _normalize_video_to_cfr,
    _save_debug_artifacts,
    _split_mask_video,
    overlay_face_mask,
)


class TestFaceMaskUtilImport(unittest.TestCase):
    """测试 face_mask_util 模块能否正常导入"""

    def test_module_imports_successfully(self):
        """模块在 mock 依赖下可正常导入"""
        from utils import face_mask_util
        self.assertTrue(hasattr(face_mask_util, 'overlay_face_mask'))
        self.assertTrue(hasattr(face_mask_util, '_log_ffmpeg_error'))

    def test_overlay_face_mask_is_callable(self):
        """overlay_face_mask 函数可调用"""
        self.assertTrue(callable(overlay_face_mask))

    def test_log_ffmpeg_error_is_callable(self):
        """_log_ffmpeg_error 函数可调用"""
        self.assertTrue(callable(_log_ffmpeg_error))


class TestLogFFmpegError(unittest.TestCase):
    """测试 _log_ffmpeg_error() 的错误日志记录"""

    @patch('utils.face_mask_util.logger')
    def test_closes_stdin_and_waits(self, mock_logger):
        """关闭 proc.stdin 并等待进程结束"""
        proc = MagicMock()
        proc.returncode = 1
        stderr_chunks = [b"error line 1\n", b"error line 2\n"]

        _log_ffmpeg_error(proc, stderr_chunks)

        proc.stdin.close.assert_called_once()
        proc.wait.assert_called_once_with(timeout=5)

    @patch('utils.face_mask_util.logger')
    def test_logs_stderr_content(self, mock_logger):
        """将 stderr 内容记录到错误日志"""
        proc = MagicMock()
        proc.returncode = 1
        stderr_chunks = [b"Encoding failed"]

        _log_ffmpeg_error(proc, stderr_chunks)

        mock_logger.error.assert_called_once()
        log_msg = mock_logger.error.call_args[0][0]
        self.assertIn("ffmpeg", log_msg)
        self.assertIn("1", log_msg)

    @patch('utils.face_mask_util.logger')
    def test_stdin_close_exception_handled(self, mock_logger):
        """proc.stdin.close 抛出异常时不崩溃"""
        proc = MagicMock()
        proc.returncode = 1
        proc.stdin.close.side_effect = BrokenPipeError("pipe closed")
        stderr_chunks = [b"error"]

        # 不应抛出异常
        _log_ffmpeg_error(proc, stderr_chunks)

        proc.wait.assert_called_once_with(timeout=5)

    @patch('utils.face_mask_util.logger')
    def test_empty_stderr(self, mock_logger):
        """stderr 为空时仍然正常执行"""
        proc = MagicMock()
        proc.returncode = 0
        stderr_chunks = []

        _log_ffmpeg_error(proc, stderr_chunks)

        mock_logger.error.assert_called_once()


class TestNormalizeVideoToCfr(unittest.TestCase):
    """测试 _normalize_video_to_cfr() 的 CFR 重采样调用"""

    @staticmethod
    def _run_ok(mocker_returncode=0):
        result = MagicMock()
        result.returncode = mocker_returncode
        result.stderr = ""
        return result

    @patch('utils.face_mask_util.os.path.exists', return_value=True)
    @patch('utils.face_mask_util.subprocess.run')
    def test_command_uses_fps_filter_and_strips_audio(self, mock_run, _mock_exists):
        """命令应使用 fps 滤镜按 PTS 重采样，并丢弃音轨"""
        mock_run.return_value = self._run_ok()

        ok = _normalize_video_to_cfr('ffmpeg', '/in.webm', '/out.mp4', 24)

        self.assertTrue(ok)
        cmd = mock_run.call_args[0][0]
        self.assertIn('fps=24', cmd)
        self.assertIn('-an', cmd)
        self.assertEqual(mock_run.call_args[1].get('timeout'), 300)

    @patch('utils.face_mask_util.os.path.exists', return_value=True)
    @patch('utils.face_mask_util.subprocess.run')
    def test_max_short_side_adds_scale_filter(self, mock_run, _mock_exists):
        """设置 max_short_side 时命令应包含按比例缩放滤镜"""
        mock_run.return_value = self._run_ok()

        ok = _normalize_video_to_cfr('ffmpeg', '/in.mp4', '/out.mp4', 24, max_short_side=512)

        self.assertTrue(ok)
        cmd = mock_run.call_args[0][0]
        vf = cmd[cmd.index('-vf') + 1]
        self.assertIn('fps=24', vf)
        self.assertIn('scale=', vf)
        self.assertIn('min(iw,512)', vf)

    @patch('utils.face_mask_util.os.path.exists', return_value=True)
    @patch('utils.face_mask_util.subprocess.run')
    def test_no_scale_filter_by_default(self, mock_run, _mock_exists):
        """默认不加缩放滤镜（本地融合保持原分辨率）"""
        mock_run.return_value = self._run_ok()

        _normalize_video_to_cfr('ffmpeg', '/in.mp4', '/out.mp4', 24)

        cmd = mock_run.call_args[0][0]
        vf = cmd[cmd.index('-vf') + 1]
        self.assertNotIn('scale=', vf)

    @patch('utils.face_mask_util.os.path.exists', return_value=True)
    @patch('utils.face_mask_util.subprocess.run')
    def test_returns_false_on_ffmpeg_failure(self, mock_run, _mock_exists):
        """ffmpeg 返回非零时返回 False"""
        mock_run.return_value = self._run_ok(mocker_returncode=1)

        self.assertFalse(_normalize_video_to_cfr('ffmpeg', '/in.webm', '/out.mp4', 24))

    @patch('utils.face_mask_util.os.path.exists', return_value=False)
    @patch('utils.face_mask_util.subprocess.run')
    def test_returns_false_when_output_missing(self, mock_run, _mock_exists):
        """ffmpeg 成功但未产出文件时返回 False"""
        mock_run.return_value = self._run_ok()

        self.assertFalse(_normalize_video_to_cfr('ffmpeg', '/in.webm', '/out.mp4', 24))

    @patch('utils.face_mask_util.subprocess.run', side_effect=Exception('boom'))
    def test_returns_false_on_exception(self, _mock_run):
        """异常时返回 False 而不抛出"""
        self.assertFalse(_normalize_video_to_cfr('ffmpeg', '/in.webm', '/out.mp4', 24))


class TestMapMaskFrameIndex(unittest.TestCase):
    """测试 _map_mask_frame_index() 的帧数比例映射"""

    def test_equal_counts_degenerate_to_identity(self):
        """帧数一致时退化为 1:1"""
        for i in (0, 1, 100, 268):
            self.assertEqual(_map_mask_frame_index(i, 269, 269), i)

    def test_stretched_mask_scales_up(self):
        """遮罩时间轴被拉伸（帧数更多）时按比例映射，结尾人脸不丢失"""
        # 事故数据：原视频归一化 269 帧，RH 遮罩 285 帧
        self.assertEqual(_map_mask_frame_index(0, 269, 285), 0)
        self.assertEqual(_map_mask_frame_index(256, 269, 285), 271)
        self.assertEqual(_map_mask_frame_index(268, 269, 285), 284)

    def test_shorter_mask_scales_down(self):
        """遮罩帧数更少时按比例缩小"""
        self.assertEqual(_map_mask_frame_index(200, 300, 240), 160)

    def test_invalid_counts_fallback_to_identity(self):
        """帧数未知时退化为 1:1"""
        self.assertEqual(_map_mask_frame_index(5, 0, 285), 5)
        self.assertEqual(_map_mask_frame_index(5, 269, -1), 5)


class TestSaveDebugArtifacts(unittest.TestCase):
    """测试 _save_debug_artifacts() 的调试产物保留"""

    def test_copies_sources_and_moves_intermediates(self):
        """源视频/遮罩源被复制，CFR 中间产物被移动到调试目录"""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            def _mk(name):
                p = os.path.join(tmp, name)
                with open(p, 'wb') as f:
                    f.write(b'x')
                return p

            src = _mk('a.webm')
            mask = _mk('mask.mp4')
            temp_orig = _mk('o.orig_cfr.mp4')
            temp_mask = _mk('o.mask_cfr.mp4')
            debug_dir = os.path.join(tmp, 'debug')

            _save_debug_artifacts(debug_dir, src, mask, temp_orig, temp_mask)

            self.assertTrue(os.path.exists(os.path.join(debug_dir, 'source_input.webm')))
            self.assertTrue(os.path.exists(os.path.join(debug_dir, 'mask_source.mp4')))
            self.assertTrue(os.path.exists(os.path.join(debug_dir, 'original_cfr.mp4')))
            self.assertTrue(os.path.exists(os.path.join(debug_dir, 'mask_cfr.mp4')))
            # 中间产物是 move 而非 copy
            self.assertFalse(os.path.exists(temp_orig))
            self.assertFalse(os.path.exists(temp_mask))
            # 源文件保留
            self.assertTrue(os.path.exists(src))
            self.assertTrue(os.path.exists(mask))

    def test_missing_intermediates_tolerated(self):
        """中间产物缺失时不抛异常"""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'a.mp4')
            mask = os.path.join(tmp, 'm.mp4')
            for p in (src, mask):
                with open(p, 'wb') as f:
                    f.write(b'x')
            # 不应抛出
            _save_debug_artifacts(
                os.path.join(tmp, 'debug'), src, mask,
                os.path.join(tmp, 'nonexistent1'), os.path.join(tmp, 'nonexistent2'),
            )
            self.assertTrue(os.path.exists(os.path.join(tmp, 'debug', 'source_input.mp4')))


class TestSplitMaskVideo(unittest.TestCase):
    """测试 _split_mask_video() 的全白分隔帧解析与旧格式兼容"""

    @staticmethod
    def _make_cap(frames):
        """frames: np.ndarray 列表（BGR 三通道）"""
        reads = [(True, f) for f in frames] + [(False, None)]
        cap = MagicMock()
        cap.read.side_effect = reads
        return cap

    @staticmethod
    def _gray_frame(value, box=None):
        """生成 40x40 灰底 BGR 帧；box=(x,y,w,h) 处填白"""
        import numpy as np
        f = np.full((40, 40, 3), value, dtype=np.uint8)
        if box:
            x, y, w, h = box
            f[y:y+h, x:x+w] = 255
        return f

    def test_old_format_without_separator_returns_raw(self):
        """旧工作流（无分隔帧）原样逐帧返回"""
        import numpy as np
        frames = [self._gray_frame(0, box=(5, 5, 10, 10)), self._gray_frame(0)]
        result = _split_mask_video(self._make_cap(frames))
        self.assertEqual(len(result), 2)
        self.assertGreater(np.count_nonzero(result[0] > 128), 0)
        self.assertEqual(np.count_nonzero(result[1] > 128), 0)

    def test_new_format_groups_merged_by_separator(self):
        """新工作流：分隔帧切分，组内多框求并集"""
        import numpy as np
        white = self._gray_frame(255)  # 全白分隔帧
        frames = [
            self._gray_frame(0, box=(5, 5, 10, 10)),   # 帧0 框A
            self._gray_frame(0, box=(20, 20, 10, 10)),  # 帧0 框B
            white,
            self._gray_frame(0),                        # 帧1 无检测（黑帧）
            white,
            self._gray_frame(0, box=(0, 0, 8, 8)),      # 帧2 框C
            white,
        ]
        result = _split_mask_video(self._make_cap(frames))
        self.assertEqual(len(result), 3)
        # 帧0：框A 与框B 并集
        self.assertEqual(int(np.count_nonzero(result[0] > 128)), 200)
        # 帧1：全黑
        self.assertEqual(int(np.count_nonzero(result[1] > 128)), 0)
        # 帧2：框C
        self.assertEqual(int(np.count_nonzero(result[2] > 128)), 64)

    def test_trailing_group_without_separator_kept(self):
        """最后一组缺分隔帧时仍保留（容错）"""
        import numpy as np
        frames = [self._gray_frame(255), self._gray_frame(0, box=(5, 5, 10, 10))]
        result = _split_mask_video(self._make_cap(frames))
        self.assertEqual(len(result), 2)
        self.assertEqual(int(np.count_nonzero(result[0] > 128)), 0)
        self.assertEqual(int(np.count_nonzero(result[1] > 128)), 100)

    def test_empty_video_returns_empty(self):
        """无帧时返回空列表"""
        self.assertEqual(_split_mask_video(self._make_cap([])), [])


class TestOverlayFaceMaskValidation(unittest.TestCase):
    """测试 overlay_face_mask() 的参数校验逻辑"""

    def test_original_video_not_exists(self):
        """原始视频不存在时返回失败"""
        # overlay_face_mask 函数内会 import cv2/numpy；仅在本用例内临时 mock，用例结束后自动恢复
        mock_modules = {
            'cv2': MagicMock(),
            'numpy': MagicMock(),
        }
        with patch.dict(sys.modules, mock_modules):
            with patch('os.path.exists', return_value=False):
                success, output, error = overlay_face_mask(
                    original_video='/nonexistent/video.mp4',
                    mask_video='/nonexistent/mask.mp4',
                    output_video='/tmp/output.mp4',
                    ffmpeg_path='ffmpeg',
                    ffprobe_path='ffprobe',
                )
        self.assertFalse(success)
        self.assertIsNone(output)
        self.assertIn("原始视频不存在", error)


if __name__ == '__main__':
    unittest.main()
