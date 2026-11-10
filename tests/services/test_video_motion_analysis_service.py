# -*- coding: utf-8 -*-
"""运动信号分析服务（services/video_motion_analysis_service.py）单元测试。

用合成灰度帧直接覆盖纯函数（summarize_motion_signals /
format_motion_signal_lines / compute_motion_sample_fps），不依赖 ffmpeg：
- 静止视频：帧间差≈0、全片最静排名、无峰值、无位移
- 动作峰值定位：镜内动作定位到具体时间点（对标"镜尾闭眼"节拍捕捉）
- 相机上摇：首尾帧行投影互相关测出内容下移（dy>0）
- 平行镜头：同构图首帧对比低于阈值标注 similar_to
- 切点保护带：转场白闪帧不污染镜内帧间差均值
ffmpeg 抽帧链路（extract_motion_frames / analyze_motion_signals）为外部依赖，
不在此覆盖（与剧本提取主链路集成验证一致）。
"""
import sys
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constant import VideoScriptExtractConstants as C  # noqa: E402
from services.video_motion_analysis_service import (  # noqa: E402
    compute_motion_sample_fps,
    format_motion_signal_lines,
    summarize_motion_signals,
)

H, W = int(C.MOTION_FRAME_HEIGHT), int(C.MOTION_FRAME_WIDTH)
FPS = 8.0


def _gray(value: float) -> np.ndarray:
    return np.full((H, W), value, dtype=np.uint8)


def _band_frame(band_top: int, band_height: int = 12, bg: int = 40, fg: int = 200) -> np.ndarray:
    """横向亮带帧：band_top 行起一条 fg 亮带（用于摇镜位移测试）。"""
    frame = np.full((H, W), bg, dtype=np.uint8)
    frame[band_top: band_top + band_height, :] = fg
    return frame


def _signals(frames: np.ndarray, scene_points, duration):
    frame_times = np.arange(len(frames), dtype=np.float64) / FPS
    return summarize_motion_signals(frame_times, frames, scene_points, duration)


class TestComputeMotionSampleFps(unittest.TestCase):
    def test_short_video_keeps_default_fps(self):
        self.assertEqual(compute_motion_sample_fps(10.0), C.MOTION_SAMPLE_FPS)
        self.assertEqual(compute_motion_sample_fps(0.0), C.MOTION_SAMPLE_FPS)
        self.assertEqual(compute_motion_sample_fps(-5.0), C.MOTION_SAMPLE_FPS)

    def test_long_video_fps_reduced_to_frame_cap(self):
        fps = compute_motion_sample_fps(900.0)
        self.assertLess(fps, C.MOTION_SAMPLE_FPS)
        self.assertEqual(fps, max(1.0, C.MOTION_MAX_FRAMES / 900.0))


class TestSummarizeMotionSignals(unittest.TestCase):
    def test_empty_frames_return_empty(self):
        self.assertEqual(summarize_motion_signals(
            np.zeros(0), np.zeros((0, H, W), dtype=np.uint8), [], 10.0,
        ), [])
        self.assertEqual(format_motion_signal_lines([]), [])

    def test_static_video_quiet_rank_and_parallel_mark(self):
        # 两个完全静止的镜头：帧间差≈0、镜1全片最静、镜2 与镜1 构图相同被标平行
        frames = np.stack([_gray(100)] * 16)
        signals = _signals(frames, [1.0], 2.0)
        self.assertEqual(len(signals), 2)
        first, second = signals
        self.assertLess(first["mean_diff"], 0.5)
        self.assertEqual(first["diff_rank"], 1)
        self.assertEqual(second["diff_rank"], 2)
        self.assertIsNone(first["shift"])
        self.assertFalse(first["peak_notable"])
        self.assertEqual(second["similar_to"], 1)
        lines = format_motion_signal_lines(signals)
        self.assertIn("全片最静", lines[0])
        self.assertIn("疑似平行镜头", lines[1])

    def test_peak_time_located_and_notable(self):
        # 镜2 中段（t=1.5）有一次大幅动作突增：峰值时刻须定位到 00:01.5
        frames = [_gray(50)] * 8 + [_gray(60)] * 4 + [_gray(120)] * 4
        signals = _signals(np.stack(frames), [1.0], 2.0)
        shot1, shot2 = signals
        self.assertFalse(shot1["peak_notable"])
        self.assertTrue(shot2["peak_notable"])
        self.assertAlmostEqual(shot2["peak_time"], 1.5, places=2)
        line = format_motion_signal_lines([shot2])[0]
        self.assertIn("峰值 00:01.5", line)

    def test_pan_up_detected_via_row_projection(self):
        # 相机上摇 = 画面内容整体下移：亮带逐帧下移 2px，首尾净位移 dy=+14
        frames = [_band_frame(band_top=2 * k) for k in range(8)]
        signals = _signals(np.stack(frames), [], 1.0)
        self.assertEqual(len(signals), 1)
        shift = signals[0]["shift"]
        self.assertIsNotNone(shift)
        self.assertEqual(shift["dy"], 14)
        self.assertEqual(shift["dx"], 0)
        line = format_motion_signal_lines(signals)[0]
        self.assertIn("内容下移14px（相机上摇）", line)

    def test_cut_guard_excludes_transition_flash(self):
        # 切点前一帧白闪（转场尖峰）：保护带必须把它剔出镜内均值，镜1 仍判静止
        frames = [_gray(50)] * 7 + [_gray(255)] * 1 + [_gray(50)] * 8
        signals = _signals(np.stack(frames), [1.0], 2.0)
        shot1 = signals[0]
        self.assertIsNotNone(shot1["mean_diff"])
        self.assertLess(shot1["mean_diff"], 1.0)
        self.assertFalse(shot1["peak_notable"])

    def test_luma_rank_brightest_and_darkest(self):
        frames = [_gray(40)] * 8 + [_gray(200)] * 8
        signals = _signals(np.stack(frames), [1.0], 2.0)
        dark, bright = signals
        self.assertEqual(dark["luma_rank"], 2)
        self.assertEqual(bright["luma_rank"], 1)
        lines = format_motion_signal_lines(signals)
        self.assertIn("全片最暗", lines[0])
        self.assertIn("全片最亮", lines[1])


class TestFormatMotionSignalLines(unittest.TestCase):
    def test_static_line_mentions_fixed_camera_and_no_peak(self):
        frames = np.stack([_gray(80)] * 8)
        signals = _signals(frames, [], 1.0)
        line = format_motion_signal_lines(signals)[0]
        self.assertIn("位移 无（固定机位）", line)
        self.assertIn("峰值 无（无显著动作突增）", line)

    def test_time_labels_use_precise_format(self):
        frames = np.stack([_gray(80)] * 16)
        signals = _signals(frames, [1.0], 2.0)
        line = format_motion_signal_lines(signals)[1]
        # 镜2 起止时间必须是 0.1s 精度标签
        self.assertIn("镜2（00:01.0-00:02.0）", line)


if __name__ == "__main__":
    unittest.main()
