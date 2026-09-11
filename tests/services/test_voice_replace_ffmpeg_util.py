"""ffmpeg helpers。采样率拼接用本机 bundled ffmpeg 回归。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.constant import VoiceReplaceConstants as C
from services.voice_replace import ffmpeg_util
from services.voice_replace.ffmpeg_util import FfmpegError, atempo_filter

_FFMPEG = Path(__file__).resolve().parents[2] / "bin" / "ffmpeg" / "ffmpeg.exe"
_FFPROBE = Path(__file__).resolve().parents[2] / "bin" / "ffmpeg" / "ffprobe.exe"
_HAS_FFMPEG = _FFMPEG.is_file() and _FFPROBE.is_file()


class TestAtempoFilter(unittest.TestCase):
    def test_near_one(self):
        self.assertIn("atempo=1.", atempo_filter(1.0))

    def test_chains_above_two(self):
        expr = atempo_filter(4.0)
        self.assertEqual(expr, "atempo=2.0,atempo=2.000000")

    def test_chains_below_half(self):
        expr = atempo_filter(0.25)
        self.assertTrue(expr.startswith("atempo=0.5"))

    def test_rejects_non_positive(self):
        with self.assertRaises(FfmpegError):
            atempo_filter(0)


@unittest.skipUnless(_HAS_FFMPEG, "bundled ffmpeg not present")
class TestSampleRateConcat(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._patch = patch.multiple(
            ffmpeg_util,
            get_ffmpeg_path=lambda: str(_FFMPEG),
            get_ffprobe_path=lambda: str(_FFPROBE),
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    async def test_concat_22050_and_44100_keeps_wall_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            low = os.path.join(tmp, "low.wav")
            high = os.path.join(tmp, "high.wav")
            mixed = os.path.join(tmp, "mixed.wav")
            await ffmpeg_util.run_ffmpeg(
                ["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-ar", "22050", "-ac", "1", low]
            )
            await ffmpeg_util.run_ffmpeg(
                ["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-ar", "44100", "-ac", "1", high]
            )
            await ffmpeg_util.concat_wavs([low, high], mixed)
            dur = await ffmpeg_util.probe_duration(mixed)
            rate = await ffmpeg_util.probe_sample_rate(mixed)
            self.assertEqual(rate, C.AUDIO_SAMPLE_RATE)
            self.assertAlmostEqual(dur, 3.0, delta=0.15)

    async def test_mux_pads_to_video_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "v.mp4")
            audio = os.path.join(tmp, "a.wav")
            out = os.path.join(tmp, "out.mp4")
            await ffmpeg_util.run_ffmpeg(
                [
                    "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=3",
                    "-f", "lavfi", "-i", "sine=d=3",
                    "-c:v", "libx264", "-t", "3", "-pix_fmt", "yuv420p", video,
                ]
            )
            await ffmpeg_util.run_ffmpeg(
                ["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-ar", "22050", "-ac", "1", audio]
            )
            await ffmpeg_util.mux_video_audio(video, audio, out)
            dur = await ffmpeg_util.probe_duration(out)
            self.assertAlmostEqual(dur, 3.0, delta=0.15)

    async def test_mix_wavs_keeps_longest_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            vocals = os.path.join(tmp, "v.wav")
            inst = os.path.join(tmp, "i.wav")
            mixed = os.path.join(tmp, "m.wav")
            await ffmpeg_util.run_ffmpeg(
                ["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-ar", "44100", "-ac", "1", vocals]
            )
            await ffmpeg_util.run_ffmpeg(
                ["-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=2", "-ar", "44100", "-ac", "1", inst]
            )
            await ffmpeg_util.mix_wavs(vocals, inst, mixed)
            dur = await ffmpeg_util.probe_duration(mixed)
            rate = await ffmpeg_util.probe_sample_rate(mixed)
            self.assertEqual(rate, C.AUDIO_SAMPLE_RATE)
            self.assertAlmostEqual(dur, 2.0, delta=0.15)


if __name__ == "__main__":
    unittest.main()

