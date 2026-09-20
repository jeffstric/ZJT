"""video_frame_extract_service 回归：bundled ffmpeg 本地跑真实提取。

核心回归用例：音轨长于视频轨的视频（容器时长取最长流），旧实现
"-sseof -0.1 -vframes 1" 定位到视频流最后一帧之后 → "Output file is empty"。
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.constant import MediaConstants as C
from services import video_frame_extract_service as svc
from services.video_frame_extract_service import FrameExtractError

_FFMPEG = Path(__file__).resolve().parents[2] / "bin" / "ffmpeg" / "ffmpeg.exe"
_FFPROBE = Path(__file__).resolve().parents[2] / "bin" / "ffmpeg" / "ffprobe.exe"
_HAS_FFMPEG = _FFMPEG.is_file() and _FFPROBE.is_file()


class TestBuildKeyframePoints(unittest.TestCase):
    """纯函数：候选时间点构造（无需 ffmpeg）。"""

    def test_single_scene_uniform_samples(self):
        pts = svc.build_keyframe_points(10.0, [])
        self.assertEqual(len(pts), C.VIDEO_FRAME_KEYFRAME_UNIFORM_SAMPLES)
        self.assertEqual(pts[0], 0.0)
        self.assertGreater(pts[-1], 9.0)  # 尾点 = duration - eps

    def test_scene_cuts_included(self):
        pts = svc.build_keyframe_points(10.0, [2.0, 5.0])
        self.assertEqual(pts[0], 0.0)
        self.assertIn(2.0, pts)
        self.assertIn(5.0, pts)
        self.assertGreater(pts[-1], 9.0)

    def test_scene_cuts_clamped_into_range(self):
        pts = svc.build_keyframe_points(4.0, [-1.0, 2.0, 99.0])
        self.assertTrue(all(0.0 <= p <= 4.0 for p in pts))
        self.assertIn(2.0, pts)

    def test_over_limit_takes_earliest_cuts_keeps_paging(self):
        """切换点多于上限：每批按时间序取最早 N 个，不跨段抽稀（翻页不漏镜头）。"""
        cuts = [float(i) for i in range(1, 30)]  # 29 个切换点
        b1 = svc.build_keyframe_points(30.0, cuts, start_time=0.0)
        # 首批 = 首帧 + 前 8 个切换点，不补尾帧（还有剩余切换点）
        self.assertEqual(len(b1), C.VIDEO_FRAME_KEYFRAME_MAX_COUNT)
        self.assertEqual(b1[0], 0.0)
        self.assertEqual(b1[-1], 8.0)
        # 续批严格晚于上一批末帧，再取 9 个；直到切换点取尽的那批补上尾帧
        start = b1[-1]
        batches = []
        while True:
            b = svc.build_keyframe_points(30.0, cuts, start_time=start)
            if not b:
                break
            batches.append(b)
            self.assertTrue(all(p > start for p in b), f"批次未严格推进: {b}")
            start = b[-1]
            if len(batches) > 10:
                self.fail("翻页未收敛")
        # 最后一批应包含尾帧（≈ duration - eps）
        self.assertGreater(batches[-1][-1], 29.0)
        # 所有批次合起来不漏、不重（首帧 + 全部 29 个切换点）
        all_pts = [round(p, 2) for b in [b1] + batches for p in b]
        for c in cuts:
            self.assertIn(round(c, 2), all_pts, f"切换点 {c} 被翻页遗漏")

    def test_min_gap_merged(self):
        pts = svc.build_keyframe_points(10.0, [5.0, 5.05, 5.08])
        # 5.05/5.08 与前点间隔小于最小间隔阈值，应被合并掉
        self.assertNotIn(5.05, pts)
        self.assertNotIn(5.08, pts)

    def test_tiny_duration_returns_at_least_one_point(self):
        pts = svc.build_keyframe_points(0.05, [])
        self.assertGreaterEqual(len(pts), 1)

    # ===== start_time 翻页续批 =====

    def test_resume_excludes_start_and_prior_cuts(self):
        # start=5.0 之后：5.0 之前的切换点被丢弃，5.0 处的切换点也丢弃（与上一批末帧重复）
        pts = svc.build_keyframe_points(20.0, [2.0, 5.0, 8.0, 12.0], start_time=5.0)
        self.assertTrue(all(p > 5.0 for p in pts))
        self.assertNotIn(5.0, pts)
        self.assertIn(8.0, pts)
        self.assertIn(12.0, pts)
        self.assertGreater(pts[-1], 19.0)  # 尾帧仍在

    def test_resume_uniform_when_no_cuts_after_start(self):
        # 单镜头视频翻页：在 (5.0, 19.95] 内均匀取 6 点，不含 5.0 本身
        pts = svc.build_keyframe_points(20.0, [], start_time=5.0)
        self.assertEqual(len(pts), C.VIDEO_FRAME_KEYFRAME_UNIFORM_SAMPLES)
        self.assertTrue(all(p > 5.0 for p in pts))
        self.assertGreater(pts[-1], 19.0)

    def test_resume_first_batch_includes_zero(self):
        # 首批（start=0）保持旧行为：含首帧 0.0
        pts = svc.build_keyframe_points(20.0, [7.0], start_time=0.0)
        self.assertEqual(pts[0], 0.0)
        self.assertIn(7.0, pts)

    def test_resume_beyond_end_returns_empty(self):
        self.assertEqual(svc.build_keyframe_points(20.0, [1.0], start_time=19.98), [])
        self.assertEqual(svc.build_keyframe_points(20.0, [], start_time=25.0), [])


@unittest.skipUnless(_HAS_FFMPEG, "bundled ffmpeg not present")
class TestExtractFrames(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._patch = patch.multiple(
            svc,
            get_ffmpeg_path=lambda: str(_FFMPEG),
            get_ffprobe_path=lambda: str(_FFPROBE),
        )
        self._patch.start()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    async def _gen_av(self, name: str) -> str:
        """音轨(1.5s)长于视频轨(0.9s)的 mp4：旧尾帧实现的失败样本。"""
        path = os.path.join(self.tmp, name)
        await self._run_ffmpeg([
            "-f", "lavfi", "-i", "testsrc=duration=0.9:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-y", path,
        ])
        return path

    async def _gen_two_scenes(self, name: str) -> str:
        """两镜头拼接视频（2s testsrc + 2s smptebars），2.0s 处有场景切换。"""
        path = os.path.join(self.tmp, name)
        await self._run_ffmpeg([
            "-f", "lavfi", "-i", "testsrc=duration=2:rate=10",
            "-f", "lavfi", "-i", "smptebars=duration=2:rate=10",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-y", path,
        ])
        return path

    async def _run_ffmpeg(self, args):
        ok = await svc._ffmpeg_ok(args, timeout=60)
        if not ok:
            self.fail(f"生成测试视频失败: {args[-1]}")

    async def test_probe_stream_duration_prefers_video_stream(self):
        video = await self._gen_av("av.mp4")
        dur = await svc.probe_stream_duration(video, timeout=30)
        # 视频流 0.9s，容器（音频主导）1.5s：必须取视频流时长
        self.assertIsNotNone(dur)
        self.assertLess(dur, 1.2)
        self.assertGreater(dur, 0.5)

    async def test_last_frame_audio_longer_than_video(self):
        """核心回归：音轨长于视频轨时尾帧不再空输出。"""
        video = await self._gen_av("av.mp4")
        out = os.path.join(self.tmp, "last.jpg")
        await svc.extract_last_frame(video, out, timeout=30)
        self.assertTrue(svc._validate_image_file(out))

    async def test_first_frame(self):
        video = await self._gen_av("av.mp4")
        out = os.path.join(self.tmp, "first.jpg")
        await svc.extract_first_frame(video, out, timeout=30)
        self.assertTrue(svc._validate_image_file(out))

    async def test_extract_frame_at_head_middle_tail(self):
        video = await self._gen_two_scenes("scenes.mp4")
        for t in (0.0, 1.0, 3.5):
            out = os.path.join(self.tmp, f"at_{t}.jpg")
            await svc.extract_frame_at(video, out, t, timeout=30)
            self.assertTrue(svc._validate_image_file(out), f"t={t} 提取失败")

    async def test_extract_frame_at_beyond_stream_raises(self):
        video = await self._gen_av("av.mp4")
        out = os.path.join(self.tmp, "beyond.jpg")
        # 5s 远超视频流末尾（0.9s），两级提取链都取不到帧
        with self.assertRaises(FrameExtractError):
            await svc.extract_frame_at(video, out, 5.0, timeout=30)
        self.assertFalse(os.path.exists(out))

    async def test_detect_scene_cut_points(self):
        video = await self._gen_two_scenes("scenes.mp4")
        cuts = await svc.detect_scene_cut_points(video, timeout=30)
        self.assertTrue(any(abs(c - 2.0) < 0.3 for c in cuts), f"未检出 2.0s 切换点: {cuts}")

    async def test_keyframe_candidates_two_scenes(self):
        video = await self._gen_two_scenes("scenes.mp4")
        frames = await svc.extract_keyframe_candidates(video, self.tmp, "kf", timeout=30)
        self.assertGreaterEqual(len(frames), 3)
        self.assertEqual(frames[0]["time_sec"], 0.0)
        # 含切换点附近与尾帧
        times = [f["time_sec"] for f in frames]
        self.assertTrue(any(abs(t - 2.0) < 0.3 for t in times), f"候选缺切换点: {times}")
        self.assertGreater(times[-1], 3.5)
        for f in frames:
            self.assertTrue(svc._validate_image_file(f["path"]), f"候选帧无效: {f}")

    async def test_detect_scene_cut_points_offset_by_start(self):
        """-ss 跳段后 pts_time 为相对值，服务必须加回偏移得绝对时间。"""
        video = await self._gen_two_scenes("scenes.mp4")
        cuts = await svc.detect_scene_cut_points(video, timeout=30, start_time=1.0)
        # 切换点绝对位置 2.0s；若未加回偏移会误报为 ~1.0s
        self.assertTrue(any(abs(c - 2.0) < 0.3 for c in cuts), f"跳段检测未换算绝对时间: {cuts}")

    async def test_keyframe_candidates_resume_batch(self):
        """翻页续批：从段中起点提取，所有帧严格晚于 start_time 且含尾帧；
        起点推进到尾帧后（视频已取尽）返回空。"""
        video = await self._gen_two_scenes("scenes.mp4")
        resumed = await svc.extract_keyframe_candidates(video, self.tmp, "b2", timeout=30, start_time=1.0)
        self.assertGreaterEqual(len(resumed), 2)
        self.assertTrue(all(f["time_sec"] > 1.0 for f in resumed), f"续批未严格晚于起点: {[f['time_sec'] for f in resumed]}")
        self.assertGreater(resumed[-1]["time_sec"], 3.5)  # 尾帧仍在
        # 4s 视频首批末帧 = 尾帧，从尾帧续批 → 已取尽 → 空列表
        exhausted = await svc.extract_keyframe_candidates(
            video, self.tmp, "b3", timeout=30, start_time=resumed[-1]["time_sec"])
        self.assertEqual(exhausted, [])

    async def test_keyframe_candidates_resume_beyond_end_empty(self):
        video = await self._gen_two_scenes("scenes.mp4")
        frames = await svc.extract_keyframe_candidates(video, self.tmp, "b3", timeout=30, start_time=99.0)
        self.assertEqual(frames, [])

    async def test_keyframe_candidates_single_scene(self):
        video = await self._gen_av("av.mp4")
        frames = await svc.extract_keyframe_candidates(video, self.tmp, "kf1", timeout=30)
        # 0.9s 单镜头：均匀采样（点数受最小间隔合并影响可能少于默认值）
        self.assertGreaterEqual(len(frames), 2)
        self.assertEqual(frames[0]["time_sec"], 0.0)
        for f in frames:
            self.assertTrue(svc._validate_image_file(f["path"]))


if __name__ == "__main__":
    unittest.main()
