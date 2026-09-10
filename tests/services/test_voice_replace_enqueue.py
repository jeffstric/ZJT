"""enqueue_scene_job 入队规则。"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from config.constant import VoiceReplaceConstants as C, VoiceReplaceJobStatus
from config.unified_config import SceneVideoType
from model.video_voice_replace import VideoVoiceReplaceJob
from services.voice_replace.aligner import DialogueLine
from services.voice_replace.enqueue import enqueue_scene_job


def _job(**kwargs):
    data = dict(
        id=11,
        user_id=1,
        source_type=C.SOURCE_STORYBOARD_SCENE,
        scene_id=99,
        source_video_url="/upload/a.mp4",
        status=VoiceReplaceJobStatus.QUEUED,
    )
    data.update(kwargs)
    return VideoVoiceReplaceJob(**data)


class TestEnqueueSceneJob(unittest.TestCase):
    def test_skips_missing_scene(self):
        with patch("services.voice_replace.enqueue.StoryboardSceneModel.get_by_id", return_value=None):
            result = enqueue_scene_job(1, 99)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["skip_reason"], C.SKIP_NO_VIDEO)

    def test_skips_digital_human(self):
        scene = SimpleNamespace(video_type=SceneVideoType.DIGITAL_HUMAN)
        with patch("services.voice_replace.enqueue.StoryboardSceneModel.get_by_id", return_value=scene):
            result = enqueue_scene_job(1, 99)
        self.assertEqual(result["skip_reason"], C.SKIP_DIGITAL_HUMAN)
        self.assertFalse(result["queued"])

    def test_skips_no_video(self):
        scene = SimpleNamespace(video_type=SceneVideoType.VIDEO)
        with patch("services.voice_replace.enqueue.StoryboardSceneModel.get_by_id", return_value=scene), \
             patch("services.voice_replace.enqueue.resolve_scene_video_url", return_value=None):
            result = enqueue_scene_job(1, 99)
        self.assertEqual(result["skip_reason"], C.SKIP_NO_VIDEO)

    def test_skips_no_dialogue(self):
        scene = SimpleNamespace(video_type=SceneVideoType.VIDEO)
        with patch("services.voice_replace.enqueue.StoryboardSceneModel.get_by_id", return_value=scene), \
             patch("services.voice_replace.enqueue.resolve_scene_video_url", return_value="/upload/a.mp4"), \
             patch("services.voice_replace.enqueue.load_dialogues", return_value=[]):
            result = enqueue_scene_job(1, 99)
        self.assertEqual(result["skip_reason"], C.SKIP_NO_DIALOGUE)

    def test_skips_missing_reference(self):
        scene = SimpleNamespace(video_type=SceneVideoType.VIDEO)
        lines = [DialogueLine(text="你好", character_id=3, character_name="甲", id=1)]
        with patch("services.voice_replace.enqueue.StoryboardSceneModel.get_by_id", return_value=scene), \
             patch("services.voice_replace.enqueue.resolve_scene_video_url", return_value="/upload/a.mp4"), \
             patch("services.voice_replace.enqueue.load_dialogues", return_value=lines), \
             patch("services.voice_replace.enqueue.resolve_character_voice", return_value=None):
            result = enqueue_scene_job(1, 99)
        self.assertEqual(result["skip_reason"], C.SKIP_MISSING_REFERENCE_AUDIO)

    def test_reuses_in_flight(self):
        scene = SimpleNamespace(video_type=SceneVideoType.VIDEO)
        lines = [DialogueLine(text="你好", character_id=3, character_name="甲", id=1)]
        existing = _job(status=VoiceReplaceJobStatus.CONVERTING)
        with patch("services.voice_replace.enqueue.StoryboardSceneModel.get_by_id", return_value=scene), \
             patch("services.voice_replace.enqueue.resolve_scene_video_url", return_value="/upload/a.mp4"), \
             patch("services.voice_replace.enqueue.load_dialogues", return_value=lines), \
             patch("services.voice_replace.enqueue.resolve_character_voice", return_value="/v.wav"), \
             patch("services.voice_replace.enqueue.VideoVoiceReplaceJobModel.find_in_flight", return_value=existing), \
             patch("services.voice_replace.enqueue.VideoVoiceReplaceJobModel.create") as create:
            result = enqueue_scene_job(1, 99)
        self.assertTrue(result["reused"])
        self.assertFalse(result["queued"])
        create.assert_not_called()
        self.assertEqual(result["job"]["id"], 11)

    def test_skips_already_completed_without_force(self):
        scene = SimpleNamespace(video_type=SceneVideoType.VIDEO)
        lines = [DialogueLine(text="你好", character_id=3, character_name="甲", id=1)]
        done = _job(status=VoiceReplaceJobStatus.COMPLETED)
        with patch("services.voice_replace.enqueue.StoryboardSceneModel.get_by_id", return_value=scene), \
             patch("services.voice_replace.enqueue.resolve_scene_video_url", return_value="/upload/a.mp4"), \
             patch("services.voice_replace.enqueue.load_dialogues", return_value=lines), \
             patch("services.voice_replace.enqueue.resolve_character_voice", return_value="/v.wav"), \
             patch("services.voice_replace.enqueue.VideoVoiceReplaceJobModel.find_in_flight", return_value=None), \
             patch("services.voice_replace.enqueue.VideoVoiceReplaceJobModel.get_latest_by_scene", return_value=done), \
             patch("services.voice_replace.enqueue.VideoVoiceReplaceJobModel.create") as create:
            result = enqueue_scene_job(1, 99, force=False)
        self.assertEqual(result["skip_reason"], C.SKIP_ALREADY_COMPLETED)
        create.assert_not_called()

    def test_force_creates_after_completed(self):
        scene = SimpleNamespace(video_type=SceneVideoType.VIDEO)
        lines = [DialogueLine(text="你好", character_id=3, character_name="甲", id=1)]
        done = _job(status=VoiceReplaceJobStatus.COMPLETED)
        created = _job(id=22, status=VoiceReplaceJobStatus.QUEUED)
        with patch("services.voice_replace.enqueue.StoryboardSceneModel.get_by_id", return_value=scene), \
             patch("services.voice_replace.enqueue.resolve_scene_video_url", return_value="/upload/a.mp4"), \
             patch("services.voice_replace.enqueue.load_dialogues", return_value=lines), \
             patch("services.voice_replace.enqueue.resolve_character_voice", return_value="/v.wav"), \
             patch("services.voice_replace.enqueue.VideoVoiceReplaceJobModel.find_in_flight", return_value=None), \
             patch("services.voice_replace.enqueue.VideoVoiceReplaceJobModel.get_latest_by_scene", return_value=done), \
             patch("services.voice_replace.enqueue.VideoVoiceReplaceJobModel.create", return_value=22), \
             patch("services.voice_replace.enqueue.VideoVoiceReplaceJobModel.get_by_id", return_value=created):
            result = enqueue_scene_job(1, 99, force=True)
        self.assertTrue(result["queued"])
        self.assertEqual(result["job"]["id"], 22)


if __name__ == "__main__":
    unittest.main()
