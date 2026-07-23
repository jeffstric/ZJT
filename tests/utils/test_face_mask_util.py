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

from utils.face_mask_util import _log_ffmpeg_error, overlay_face_mask


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
