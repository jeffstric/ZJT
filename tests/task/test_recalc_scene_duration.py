"""
recalc_scene_duration_if_all_completed 单元测试

覆盖：
- 全部选中配音 COMPLETED + 有 duration → 返回求和浮点并更新 scene.duration（max(1.0, round(total,3))）。
- 任一未完成/无 duration/空 scene_id → 返回 None，不更新 scene.duration，不重算 total。
- sum 抛异常 → 返回 None（best-effort，不向上抛）。

测试通过 mock task/audio_task 的模型依赖来隔离真实 DB，沿用 test_audio_task_utils.py 的 mock 策略。
"""
import asyncio
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

# ---------- mock task/audio_task 重依赖（导入前） ----------
_saved = {key: sys.modules.get(key) for key in [
    'model', 'model.storyboard', 'model.storyboard_dialogue',
    'model.storyboard_dialogue_audio', 'utils.audio_duration_util',
    'config.constant', 'config.config_util',
    'task.async_drivers.runninghub_audio_driver', 'utils.index_tts_util',
]}

model_pkg = types.ModuleType('model')
model_pkg.TasksModel = MagicMock()
model_pkg.AIAudioModel = MagicMock()
model_pkg.StoryboardModel = MagicMock()
model_pkg.StoryboardSceneModel = MagicMock()
model_pkg.StoryboardDialogueModel = MagicMock()
sys.modules['model'] = model_pkg

_sb_mod = types.ModuleType('model.storyboard')
_sb_mod.StoryboardModel = MagicMock()
_sb_mod.StoryboardSceneModel = MagicMock()
sys.modules['model.storyboard'] = _sb_mod
_sd_mod = types.ModuleType('model.storyboard_dialogue')
_sd_mod.StoryboardDialogueModel = MagicMock()
sys.modules['model.storyboard_dialogue'] = _sd_mod
_sda_mod = types.ModuleType('model.storyboard_dialogue_audio')
_sda_mod.StoryboardDialogueAudioModel = MagicMock()
sys.modules['model.storyboard_dialogue_audio'] = _sda_mod
_adu_mod = types.ModuleType('utils.audio_duration_util')
_adu_mod.probe_audio_duration = MagicMock()
sys.modules['utils.audio_duration_util'] = _adu_mod

config_constant = types.ModuleType('config.constant')
config_constant.TASK_TYPE_GENERATE_AUDIO = 10
config_constant.AI_AUDIO_STATUS_PENDING = 0
config_constant.AI_AUDIO_STATUS_PROCESSING = 1
config_constant.AI_AUDIO_STATUS_COMPLETED = 2
config_constant.AI_AUDIO_STATUS_FAILED = -1
config_constant.TASK_STATUS_QUEUED = 0
config_constant.TASK_STATUS_PROCESSING = 1
config_constant.TASK_STATUS_COMPLETED = 2
config_constant.TASK_STATUS_FAILED = -1
sys.modules['config.constant'] = config_constant

rh_config = types.ModuleType('task.async_drivers.runninghub_audio_driver')
rh_config.RunningHubAudioConfig = MagicMock()
sys.modules['task.async_drivers.runninghub_audio_driver'] = rh_config
sys.modules['utils.index_tts_util'] = MagicMock()
sys.modules['config.config_util'] = MagicMock()

from task.audio_task import recalc_scene_duration_if_all_completed  # noqa: E402

# ---------- 恢复 sys.modules ----------
for key, saved in _saved.items():
    if saved is not None:
        sys.modules[key] = saved
    else:
        sys.modules.pop(key, None)


def _run_async(coro):
    return asyncio.run(coro)


class TestRecalcSceneDurationIfAllCompleted(unittest.TestCase):
    """recalc_scene_duration_if_all_completed 行为测试"""

    def _patch_to_thread(self):
        """patch asyncio.to_thread 直接同步调用传入的同步函数（测试中无真实线程池）。"""
        async def _fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)
        return patch('task.audio_task.asyncio.to_thread', side_effect=_fake_to_thread)

    def test_all_completed_returns_sum_and_updates_scene(self):
        """全部完成 → 返回 max(1.0, round(total,3)) 并更新 scene.duration 与 total_duration"""
        with self._patch_to_thread() as mock_to_thread:
            with patch('task.audio_task.StoryboardDialogueAudioModel') as MockDA, \
                 patch('task.audio_task.StoryboardSceneModel') as MockScene, \
                 patch('task.audio_task.StoryboardModel') as MockSB:
                MockDA.sum_selected_durations_if_all_completed.return_value = 5.2367
                MockScene.update.return_value = 1
                MockScene.get_by_id.return_value = MagicMock(storyboard_id=42)
                MockSB.recalc_total_duration.return_value = 5.237

                result = _run_async(recalc_scene_duration_if_all_completed(7))

                # 写入 scene.duration = max(1.0, round(5.2367, 3)) = 5.237
                self.assertAlmostEqual(result, 5.237, places=3)
                MockScene.update.assert_called_once_with(7, duration=5.237)
                MockSB.recalc_total_duration.assert_called_once_with(42)

    def test_zero_total_floored_to_one(self):
        """全 0 duration 求和 → max(1.0, 0.0) = 1.0"""
        with self._patch_to_thread():
            with patch('task.audio_task.StoryboardDialogueAudioModel') as MockDA, \
                 patch('task.audio_task.StoryboardSceneModel') as MockScene, \
                 patch('task.audio_task.StoryboardModel') as MockSB:
                MockDA.sum_selected_durations_if_all_completed.return_value = 0.0
                MockScene.update.return_value = 1
                MockScene.get_by_id.return_value = MagicMock(storyboard_id=42)

                result = _run_async(recalc_scene_duration_if_all_completed(7))

                self.assertEqual(result, 1.0)
                MockScene.update.assert_called_once_with(7, duration=1.0)
                MockSB.recalc_total_duration.assert_called_once_with(42)

    def test_not_all_completed_returns_none_no_update(self):
        """sum 返回 None（未全部完成）→ 不更新 scene.duration，不重算 total"""
        with self._patch_to_thread() as mock_to_thread:
            with patch('task.audio_task.StoryboardDialogueAudioModel') as MockDA, \
                 patch('task.audio_task.StoryboardSceneModel') as MockScene, \
                 patch('task.audio_task.StoryboardModel') as MockSB:
                MockDA.sum_selected_durations_if_all_completed.return_value = None

                result = _run_async(recalc_scene_duration_if_all_completed(7))

                self.assertIsNone(result)
                MockScene.update.assert_not_called()
                MockSB.recalc_total_duration.assert_not_called()

    def test_empty_scene_id_returns_none(self):
        """空 scene_id（0/None）→ 直接返回 None，不查 DB"""
        with patch('task.audio_task.StoryboardDialogueAudioModel') as MockDA:
            self.assertIsNone(_run_async(recalc_scene_duration_if_all_completed(0)))
            self.assertIsNone(_run_async(recalc_scene_duration_if_all_completed(None)))
            MockDA.sum_selected_durations_if_all_completed.assert_not_called()

    def test_sum_raises_returns_none_no_update(self):
        """sum 抛异常 → best-effort 返回 None，不更新 scene.duration"""
        with self._patch_to_thread():
            with patch('task.audio_task.StoryboardDialogueAudioModel') as MockDA, \
                 patch('task.audio_task.StoryboardSceneModel') as MockScene:
                MockDA.sum_selected_durations_if_all_completed.side_effect = RuntimeError("db down")

                result = _run_async(recalc_scene_duration_if_all_completed(7))

                self.assertIsNone(result)
                MockScene.update.assert_not_called()

    def test_completed_constant_is_parameterized(self):
        """验证 SQL 参数化：sum 函数被调用即说明走通了 COMPLETED 常量注入路径
        （真实参数化逻辑在 model 层 SQL，此处仅断言 recalc 正确转发 scene_id）。"""
        with self._patch_to_thread():
            with patch('task.audio_task.StoryboardDialogueAudioModel') as MockDA, \
                 patch('task.audio_task.StoryboardSceneModel') as MockScene, \
                 patch('task.audio_task.StoryboardModel'):
                MockDA.sum_selected_durations_if_all_completed.return_value = None
                MockScene.update.return_value = 1

                _run_async(recalc_scene_duration_if_all_completed(99))

                MockDA.sum_selected_durations_if_all_completed.assert_called_once_with(99)


if __name__ == '__main__':
    unittest.main()
