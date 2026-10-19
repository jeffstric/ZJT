"""
_lock_scene_video_audio_on_first_voiceover 单元测试（音源口径 R1）。

口径：audio_embedded=0 仅在「有配音且用户显式选 TTS」时成立。首条配音落地时
（分镜此前无任何配音资产，资产总数==1），后端把 audio_embedded 锁定为 1（视频原声），
保证「配音生成后保持视频原声，不自动切 TTS」。重新生成配音时旧资产记录仍在
（总数≥2），保留用户显式选择。

测试通过 mock task/audio_task 的模型依赖来隔离真实 DB，
沿用 tests/task/test_recalc_scene_duration.py 的 stub 策略。
"""
import asyncio
import unittest
from unittest.mock import MagicMock, patch

from tests.base.test_isolation import module_stub, stub_modules

from config.constant import normalize_dialogue_tts_speed as _normalize_dialogue_tts_speed

# ---------- mock task/audio_task 重依赖（导入前） ----------
with stub_modules({
    'model': module_stub(
        'model',
        TasksModel=MagicMock(),
        AIAudioModel=MagicMock(),
        StoryboardModel=MagicMock(),
        StoryboardSceneModel=MagicMock(),
        StoryboardDialogueModel=MagicMock(),
    ),
    'model.storyboard': module_stub(
        'model.storyboard',
        StoryboardModel=MagicMock(),
        StoryboardSceneModel=MagicMock(),
    ),
    'model.storyboard_dialogue': module_stub(
        'model.storyboard_dialogue',
        StoryboardDialogueModel=MagicMock(),
    ),
    'model.storyboard_dialogue_audio': module_stub(
        'model.storyboard_dialogue_audio',
        StoryboardDialogueAudioModel=MagicMock(),
    ),
    'model.media_file_mapping': module_stub(
        'model.media_file_mapping',
        MediaFileEntity=MagicMock(),
    ),
    'utils.audio_duration_util': module_stub(
        'utils.audio_duration_util',
        probe_audio_duration=MagicMock(),
    ),
    'config.constant': module_stub(
        'config.constant',
        TASK_TYPE_GENERATE_AUDIO=10,
        AI_AUDIO_STATUS_PENDING=0,
        AI_AUDIO_STATUS_PROCESSING=1,
        AI_AUDIO_STATUS_COMPLETED=2,
        AI_AUDIO_STATUS_FAILED=-1,
        TASK_STATUS_QUEUED=0,
        TASK_STATUS_PROCESSING=1,
        TASK_STATUS_COMPLETED=2,
        TASK_STATUS_FAILED=-1,
        normalize_dialogue_tts_speed=_normalize_dialogue_tts_speed,
    ),
    'task.async_drivers.runninghub_audio_driver': module_stub(
        'task.async_drivers.runninghub_audio_driver',
        RunningHubAudioConfig=MagicMock(),
    ),
    'utils.index_tts_util': MagicMock(),
    'config.config_util': MagicMock(),
}):
    from task.audio_task import _lock_scene_video_audio_on_first_voiceover  # noqa: E402


def _run_async(coro):
    return asyncio.run(coro)


class TestLockSceneVideoAudioOnFirstVoiceover(unittest.TestCase):
    """首条配音落地锁定视频原声（R1）行为测试"""

    def setUp(self):
        def _fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        to_thread_patcher = patch(
            'task.audio_task.asyncio.to_thread', side_effect=_fake_to_thread
        )
        to_thread_patcher.start()
        self.addCleanup(to_thread_patcher.stop)

    def _patch_models(self, *, audio_embedded, asset_count):
        """按依赖链装填 mock：ai_audio → dialogue_audio → dialogue → scene。"""
        da_patcher = patch('task.audio_task.StoryboardDialogueAudioModel')
        dlg_patcher = patch('task.audio_task.StoryboardDialogueModel')
        scene_patcher = patch('task.audio_task.StoryboardSceneModel')
        MockDA = da_patcher.start()
        MockDlg = dlg_patcher.start()
        MockScene = scene_patcher.start()
        for patcher in (da_patcher, dlg_patcher, scene_patcher):
            self.addCleanup(patcher.stop)

        MockDA.get_by_ai_audio_id.return_value = MagicMock(dialogue_id=101)
        MockDlg.get_by_id.return_value = MagicMock(scene_id=7)
        MockScene.get_by_id.return_value = MagicMock(audio_embedded=audio_embedded)
        MockDA.count_assets_by_scene.return_value = asset_count
        return MockDA, MockScene

    def test_first_voiceover_locks_video_audio(self):
        """首条配音落地（此前无任何配音资产）→ audio_embedded 锁定 1"""
        MockDA, MockScene = self._patch_models(audio_embedded=0, asset_count=1)

        _run_async(_lock_scene_video_audio_on_first_voiceover(9001))

        MockScene.update.assert_called_once_with(7, audio_embedded=True)
        MockDA.count_assets_by_scene.assert_called_once_with(7)

    def test_regenerate_keeps_user_choice(self):
        """重新生成配音（旧资产记录仍在，总数≥2）→ 保留用户显式 TTS 选择，不翻转"""
        MockDA, MockScene = self._patch_models(audio_embedded=0, asset_count=2)

        _run_async(_lock_scene_video_audio_on_first_voiceover(9002))

        MockScene.update.assert_not_called()

    def test_already_locked_noop(self):
        """已是视频原声（audio_embedded=1）→ 不再查资产、不更新"""
        MockDA, MockScene = self._patch_models(audio_embedded=1, asset_count=1)

        _run_async(_lock_scene_video_audio_on_first_voiceover(9003))

        MockDA.count_assets_by_scene.assert_not_called()
        MockScene.update.assert_not_called()

    def test_missing_dialogue_audio_swallows(self):
        """反查不到配音记录 → 静默返回（best-effort，不影响配音任务结果）"""
        with patch('task.audio_task.StoryboardDialogueAudioModel') as MockDA:
            MockDA.get_by_ai_audio_id.return_value = None
            _run_async(_lock_scene_video_audio_on_first_voiceover(9004))
            MockDA.count_assets_by_scene.assert_not_called()


if __name__ == '__main__':
    unittest.main()
