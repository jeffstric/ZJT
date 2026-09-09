"""VoiceReplaceWorker 编排（全部外部依赖 mock）。"""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from config.constant import VoiceReplaceConstants as C, VoiceReplaceJobStatus
from config.unified_config import SceneVideoType
from services.voice_replace.aligner import AlignedSegment, AlignmentResult, AsrSegment, DialogueLine
from services.voice_replace.worker import VoiceReplaceWorker
from model.video_voice_replace import VideoVoiceReplaceJob


def _job(**kwargs):
    data = dict(
        id=7,
        user_id=1,
        source_type=C.SOURCE_STORYBOARD_SCENE,
        scene_id=99,
        source_video_url="/upload/temp/in.mp4",
        status=VoiceReplaceJobStatus.ASR,
    )
    data.update(kwargs)
    return VideoVoiceReplaceJob(**data)


class _FakeAsr:
    def __init__(self, segments):
        self.segments = segments
        self.calls = []

    async def transcribe_segments(self, audio, language="auto", filename=None):
        self.calls.append(audio)
        return self.segments


class _FakeVc:
    def __init__(self):
        self.calls = []

    async def convert(self, source_wav, reference_wav, dest_wav):
        self.calls.append((source_wav, reference_wav, dest_wav))
        with open(dest_wav, "wb") as fh:
            fh.write(b"vc")
        return dest_wav


class _FakeUvr:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    async def separate(self, source_wav, vocals_dest, instrumental_dest):
        self.calls.append((source_wav, vocals_dest, instrumental_dest))
        if self.fail:
            from services.voice_replace.uvr_driver import UvrError
            raise UvrError("uvr down")
        os.makedirs(os.path.dirname(vocals_dest) or ".", exist_ok=True)
        with open(vocals_dest, "wb") as fh:
            fh.write(b"vocals")
        with open(instrumental_dest, "wb") as fh:
            fh.write(b"inst")
        return vocals_dest, instrumental_dest


class TestVoiceReplaceWorker(unittest.IsolatedAsyncioTestCase):
    async def test_skips_digital_human(self):
        scene = SimpleNamespace(video_type=SceneVideoType.DIGITAL_HUMAN, selected_video_id=1)
        worker = VoiceReplaceWorker(asr=_FakeAsr([]), vc=_FakeVc(), uvr=_FakeUvr())
        with patch("services.voice_replace.worker.StoryboardSceneModel.get_by_id", return_value=scene), \
             patch("services.voice_replace.worker.VideoVoiceReplaceJobModel.update_status") as upd:
            status = await worker.process_job(_job())
        self.assertEqual(status, VoiceReplaceJobStatus.SKIPPED)
        upd.assert_called()
        self.assertEqual(upd.call_args.args[1], VoiceReplaceJobStatus.SKIPPED)

    async def test_skips_workflow(self):
        worker = VoiceReplaceWorker(asr=_FakeAsr([]), vc=_FakeVc(), uvr=_FakeUvr())
        with patch("services.voice_replace.worker.VideoVoiceReplaceJobModel.update_status") as upd:
            status = await worker.process_job(_job(source_type=C.SOURCE_WORKFLOW_NODE, scene_id=None))
        self.assertEqual(status, VoiceReplaceJobStatus.SKIPPED)
        self.assertEqual(upd.call_args.kwargs.get("skip_reason"), "workflow_not_supported")

    async def test_wait_confirm_does_not_convert(self):
        asr = _FakeAsr([AsrSegment(0.0, 1.0, "zzzz")])
        vc = _FakeVc()
        uvr = _FakeUvr()
        worker = VoiceReplaceWorker(asr=asr, vc=vc, uvr=uvr)
        alignment = AlignmentResult(
            status=C.STATUS_WAIT_CONFIRM,
            mean_score=0.1,
            unmatched_asr_ratio=0.0,
            segments=[
                AlignedSegment(
                    start=0, end=1, asr_text="zzzz", score=0.1,
                    method=C.METHOD_ORDER, character_id=1, dialogue_id=1,
                )
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "source.wav")
            open(wav, "wb").write(b"RIFF")
            with patch("services.voice_replace.worker._job_work_dir", return_value=tmp), \
                 patch("services.voice_replace.worker.StoryboardSceneModel.get_by_id", return_value=SimpleNamespace(video_type="video", selected_video_id=1)), \
                 patch("services.voice_replace.worker._resolve_media", new=AsyncMock(return_value=os.path.join(tmp, "in.mp4"))), \
                 patch("services.voice_replace.worker.extract_audio", new=AsyncMock()), \
                 patch("services.voice_replace.worker.load_dialogues", return_value=[DialogueLine("你好", 1, "甲", 1)]), \
                 patch("services.voice_replace.worker.align_dialogues", return_value=alignment), \
                 patch("services.voice_replace.worker._persist_segments"), \
                 patch("services.voice_replace.worker.VideoVoiceReplaceJobModel.update_status") as upd:
                open(os.path.join(tmp, "in.mp4"), "wb").write(b"mp4")
                status = await worker.process_job(_job())
        self.assertEqual(status, VoiceReplaceJobStatus.WAIT_CONFIRM)
        self.assertEqual(vc.calls, [])
        statuses = [c.args[1] for c in upd.call_args_list]
        self.assertIn(VoiceReplaceJobStatus.WAIT_CONFIRM, statuses)

    async def test_auto_converts_and_muxes(self):
        asr = _FakeAsr([AsrSegment(0.0, 1.0, "你好")])
        vc = _FakeVc()
        uvr = _FakeUvr()
        worker = VoiceReplaceWorker(asr=asr, vc=vc, uvr=uvr)
        alignment = AlignmentResult(
            status=C.STATUS_AUTO,
            mean_score=1.0,
            unmatched_asr_ratio=0.0,
            segments=[
                AlignedSegment(
                    start=0, end=1, asr_text="你好", score=1.0,
                    method=C.METHOD_SINGLE_SPEAKER, character_id=3, dialogue_id=1,
                )
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "in.mp4"), "wb").write(b"mp4")
            open(os.path.join(tmp, C.EXTRACTED_WAV), "wb").write(b"wav")
            with patch("services.voice_replace.worker._job_work_dir", return_value=tmp), \
                 patch("services.voice_replace.worker.StoryboardSceneModel.get_by_id", return_value=SimpleNamespace(video_type="video", selected_video_id=1)), \
                 patch("services.voice_replace.worker._resolve_media", new=AsyncMock(side_effect=lambda url, dest: dest if dest.endswith(".wav") else os.path.join(tmp, "in.mp4"))), \
                 patch("services.voice_replace.worker.extract_audio", new=AsyncMock()), \
                 patch("services.voice_replace.worker.load_dialogues", return_value=[DialogueLine("你好", 3, "甲", 1)]), \
                 patch("services.voice_replace.worker.align_dialogues", return_value=alignment), \
                 patch("services.voice_replace.worker._persist_segments"), \
                 patch("services.voice_replace.worker.probe_duration", new=AsyncMock(return_value=1.0)), \
                 patch("services.voice_replace.worker.slice_audio", new=AsyncMock()), \
                 patch("services.voice_replace.worker.stretch_to_duration", new=AsyncMock()), \
                 patch("services.voice_replace.worker.concat_wavs", new=AsyncMock()), \
                 patch("services.voice_replace.worker.mix_wavs", new=AsyncMock()) as mix, \
                 patch("services.voice_replace.worker.mux_video_audio", new=AsyncMock()) as mux, \
                 patch("services.voice_replace.worker.resolve_character_voice", return_value="/upload/character/voice/a.wav"), \
                 patch("services.voice_replace.worker.VideoVoiceReplaceJobModel.update_status"), \
                 patch.object(VoiceReplaceWorker, "_attach_scene_result"):
                status = await worker.process_job(_job())
        self.assertEqual(status, VoiceReplaceJobStatus.COMPLETED)
        self.assertEqual(len(vc.calls), 1)
        self.assertEqual(len(uvr.calls), 1)
        self.assertEqual(asr.calls[0].endswith(C.UVR_VOCALS_FILENAME), True)
        mix.assert_awaited()
        mux.assert_awaited()

    async def test_uvr_failure_falls_back_to_mixed_audio(self):
        asr = _FakeAsr([AsrSegment(0.0, 1.0, "你好")])
        vc = _FakeVc()
        uvr = _FakeUvr(fail=True)
        worker = VoiceReplaceWorker(asr=asr, vc=vc, uvr=uvr)
        alignment = AlignmentResult(
            status=C.STATUS_AUTO,
            mean_score=1.0,
            unmatched_asr_ratio=0.0,
            segments=[
                AlignedSegment(
                    start=0, end=1, asr_text="你好", score=1.0,
                    method=C.METHOD_SINGLE_SPEAKER, character_id=3, dialogue_id=1,
                )
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "in.mp4"), "wb").write(b"mp4")
            extracted = os.path.join(tmp, C.EXTRACTED_WAV)
            open(extracted, "wb").write(b"wav")
            with patch("services.voice_replace.worker._job_work_dir", return_value=tmp), \
                 patch("services.voice_replace.worker.StoryboardSceneModel.get_by_id", return_value=SimpleNamespace(video_type="video", selected_video_id=1)), \
                 patch("services.voice_replace.worker._resolve_media", new=AsyncMock(side_effect=lambda url, dest: dest if dest.endswith(".wav") else os.path.join(tmp, "in.mp4"))), \
                 patch("services.voice_replace.worker.extract_audio", new=AsyncMock()), \
                 patch("services.voice_replace.worker.load_dialogues", return_value=[DialogueLine("你好", 3, "甲", 1)]), \
                 patch("services.voice_replace.worker.align_dialogues", return_value=alignment), \
                 patch("services.voice_replace.worker._persist_segments"), \
                 patch("services.voice_replace.worker.probe_duration", new=AsyncMock(return_value=1.0)), \
                 patch("services.voice_replace.worker.slice_audio", new=AsyncMock()), \
                 patch("services.voice_replace.worker.stretch_to_duration", new=AsyncMock()), \
                 patch("services.voice_replace.worker.concat_wavs", new=AsyncMock()), \
                 patch("services.voice_replace.worker.mix_wavs", new=AsyncMock()) as mix, \
                 patch("services.voice_replace.worker.mux_video_audio", new=AsyncMock()), \
                 patch("services.voice_replace.worker.resolve_character_voice", return_value="/upload/character/voice/a.wav"), \
                 patch("services.voice_replace.worker.VideoVoiceReplaceJobModel.update_status"), \
                 patch.object(VoiceReplaceWorker, "_attach_scene_result"):
                status = await worker.process_job(_job())
        self.assertEqual(status, VoiceReplaceJobStatus.COMPLETED)
        self.assertEqual(asr.calls[0], extracted)
        mix.assert_not_awaited()

    async def test_swaps_uvr_stems_when_speech_is_on_instrumental(self):
        class _StemAsr:
            def __init__(self):
                self.calls = []

            async def transcribe_segments(self, audio, language="auto", filename=None):
                self.calls.append(audio)
                name = os.path.basename(str(audio))
                if name == C.UVR_VOCALS_FILENAME:
                    return []
                return [AsrSegment(0.7, 7.0, "大家好欢迎来到微课堂")]

        asr = _StemAsr()
        vc = _FakeVc()
        uvr = _FakeUvr()
        worker = VoiceReplaceWorker(asr=asr, vc=vc, uvr=uvr)
        alignment = AlignmentResult(
            status=C.STATUS_AUTO,
            mean_score=1.0,
            unmatched_asr_ratio=0.0,
            segments=[
                AlignedSegment(
                    start=0.7, end=7.0, asr_text="大家好欢迎来到微课堂", score=1.0,
                    method=C.METHOD_SINGLE_SPEAKER, character_id=3, dialogue_id=1,
                )
            ],
        )
        slice_srcs = []

        async def fake_slice(src, dest, start, end):
            slice_srcs.append(src)

        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "in.mp4"), "wb").write(b"mp4")
            open(os.path.join(tmp, C.EXTRACTED_WAV), "wb").write(b"wav")
            with patch("services.voice_replace.worker._job_work_dir", return_value=tmp), \
                 patch("services.voice_replace.worker.StoryboardSceneModel.get_by_id", return_value=SimpleNamespace(video_type="video", selected_video_id=1)), \
                 patch("services.voice_replace.worker._resolve_media", new=AsyncMock(side_effect=lambda url, dest: dest if dest.endswith(".wav") else os.path.join(tmp, "in.mp4"))), \
                 patch("services.voice_replace.worker.extract_audio", new=AsyncMock()), \
                 patch("services.voice_replace.worker.load_dialogues", return_value=[DialogueLine("大家好", 3, "谭老师", 1)]), \
                 patch("services.voice_replace.worker.align_dialogues", return_value=alignment), \
                 patch("services.voice_replace.worker._persist_segments"), \
                 patch("services.voice_replace.worker.probe_duration", new=AsyncMock(return_value=8.0)), \
                 patch("services.voice_replace.worker.slice_audio", new=fake_slice), \
                 patch("services.voice_replace.worker.stretch_to_duration", new=AsyncMock()), \
                 patch("services.voice_replace.worker.concat_wavs", new=AsyncMock()), \
                 patch("services.voice_replace.worker.mix_wavs", new=AsyncMock()), \
                 patch("services.voice_replace.worker.mux_video_audio", new=AsyncMock()), \
                 patch("services.voice_replace.worker.resolve_character_voice", return_value="/upload/character/voice/a.wav"), \
                 patch("services.voice_replace.worker.VideoVoiceReplaceJobModel.update_status"), \
                 patch.object(VoiceReplaceWorker, "_attach_scene_result"):
                status = await worker.process_job(_job())
        self.assertEqual(status, VoiceReplaceJobStatus.COMPLETED)
        self.assertEqual(len(asr.calls), 2)
        self.assertTrue(any(src.endswith(C.UVR_INSTRUMENTAL_FILENAME) for src in slice_srcs))


class TestSchedulerClaim(unittest.IsolatedAsyncioTestCase):
    async def test_process_skips_when_claim_fails(self):
        from task.voice_replace_task import process_voice_replace_jobs
        job = _job(status=VoiceReplaceJobStatus.QUEUED)
        with patch("task.voice_replace_task.VideoVoiceReplaceJobModel.list_queued", return_value=[job]), \
             patch("task.voice_replace_task.VideoVoiceReplaceJobModel.claim", return_value=False), \
             patch("task.voice_replace_task.VoiceReplaceWorker") as worker_cls:
            await process_voice_replace_jobs()
            worker_cls.return_value.process_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
