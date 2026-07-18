"""
audio_task 纯函数单元测试

测试 build_character_audio_text 和 calculate_next_retry_delay。
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock 所有 task/audio_task.py 的重依赖
_saved_model = sys.modules.get('model')
_saved_config_constant = sys.modules.get('config.constant')
_saved_config_util = sys.modules.get('config.config_util')
_saved_rh_config = sys.modules.get('task.async_drivers.runninghub_audio_driver')
_saved_index_tts = sys.modules.get('utils.index_tts_util')

sys.modules['model'] = MagicMock()
sys.modules['model'].__dict__.update({
    'TasksModel': MagicMock(),
    'AIAudioModel': MagicMock(),
})
# 需要在 model 包存在后再 mock 子模块
import types
model_pkg = types.ModuleType('model')
model_pkg.TasksModel = MagicMock()
model_pkg.AIAudioModel = MagicMock()
model_pkg.StoryboardModel = MagicMock()
model_pkg.StoryboardSceneModel = MagicMock()
model_pkg.StoryboardDialogueModel = MagicMock()
sys.modules['model'] = model_pkg

# audio_task 新增了这些子模块的直接 import，需 mock 以避免触发真实 DB/配置加载
_sb_mod = types.ModuleType('model.storyboard')
_sb_mod.StoryboardModel = MagicMock()
_sb_mod.StoryboardSceneModel = MagicMock()
sys.modules['model.storyboard'] = _sb_mod
_sd_mod = types.ModuleType('model.storyboard_dialogue')
_sd_mod.StoryboardDialogueModel = MagicMock()
sys.modules['model.storyboard_dialogue'] = _sd_mod
# storyboard_dialogue_audio 已在真实模块中, 但测试里也 mock 掉避免 DB
_sda_mod = types.ModuleType('model.storyboard_dialogue_audio')
_sda_mod.StoryboardDialogueAudioModel = MagicMock()
sys.modules['model.storyboard_dialogue_audio'] = _sda_mod
# utils.audio_duration_util
_adu_mod = types.ModuleType('utils.audio_duration_util')
_adu_mod.probe_audio_duration = MagicMock()
sys.modules['utils.audio_duration_util'] = _adu_mod

# Mock config.constant
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

# Mock RunningHubAudioConfig
rh_config = types.ModuleType('task.async_drivers.runninghub_audio_driver')
rh_config.RunningHubAudioConfig = MagicMock()
rh_config.RunningHubAudioConfig.AUDIO_STYLE_DEFAULT_PROMPT = '声音自然清晰，语气平稳，适合角色旁白'
rh_config.RunningHubAudioConfig.AUDIO_STYLE_LLM_MAX_TOKENS = 256
rh_config.RunningHubAudioConfig.AUDIO_STYLE_LLM_TEMPERATURE = 0.7
sys.modules['task.async_drivers.runninghub_audio_driver'] = rh_config

sys.modules['utils.index_tts_util'] = MagicMock()
sys.modules['config.config_util'] = MagicMock()

from task.audio_task import build_character_audio_text, calculate_next_retry_delay

# 恢复被 mock 的 sys.modules，防止污染后续测试
for _key, _saved in [
    ('model', _saved_model),
    ('model.storyboard', None),
    ('model.storyboard_dialogue', None),
    ('model.storyboard_dialogue_audio', None),
    ('utils.audio_duration_util', None),
    ('config.constant', _saved_config_constant),
    ('config.config_util', _saved_config_util),
    ('task.async_drivers.runninghub_audio_driver', _saved_rh_config),
    ('utils.index_tts_util', _saved_index_tts),
]:
    if _saved is not None:
        sys.modules[_key] = _saved
    else:
        sys.modules.pop(_key, None)


def _run_async(coro):
    """辅助函数：在测试中运行异步函数"""
    return asyncio.run(coro)


class TestBuildCharacterAudioText(unittest.TestCase):
    """测试 build_character_audio_text()"""

    def test_custom_text_takes_priority(self):
        """自定义文本优先返回"""
        result = _run_async(build_character_audio_text(
            character_data={"name": "Alice"},
            custom_text="这是自定义的音频文本"
        ))
        self.assertEqual(result, "这是自定义的音频文本")

    def test_custom_text_with_whitespace(self):
        """自定义文本会被 strip"""
        result = _run_async(build_character_audio_text(
            character_data={"name": "Alice"},
            custom_text="  有内容的文本  "
        ))
        self.assertEqual(result, "有内容的文本")

    @patch('task.audio_task._analyze_character_voice_capability')
    def test_empty_custom_text_uses_llm(self, mock_analyze):
        """空 custom_text 时使用 LLM 生成的文本"""
        mock_analyze.return_value = {
            'sample_text': '大家好，我是张三，是勇士。很高兴在这个故事里与你相遇。'
        }
        result = _run_async(build_character_audio_text(
            character_data={"name": "张三", "identity": "勇士"},
            custom_text=""
        ))
        self.assertEqual(result, "大家好，我是张三，是勇士。很高兴在这个故事里与你相遇。")

    @patch('task.audio_task._analyze_character_voice_capability')
    def test_with_age_and_male_gender(self, mock_analyze):
        """包含年龄和男性性别信息（LLM 生成）"""
        mock_analyze.return_value = {
            'sample_text': '大家好，我是张伟，今年30岁，是一位男性，是程序员。很高兴在这个故事里与你相遇。'
        }
        result = _run_async(build_character_audio_text(
            character_data={"name": "张伟", "age": "30", "identity": "程序员", "appearance": "一位高大的男性"},
            custom_text=None
        ))
        self.assertEqual(result, "大家好，我是张伟，今年30岁，是一位男性，是程序员。很高兴在这个故事里与你相遇。")

    @patch('task.audio_task._analyze_character_voice_capability')
    def test_with_age_and_female_gender(self, mock_analyze):
        """包含年龄和女性性别信息（LLM 生成）"""
        mock_analyze.return_value = {
            'sample_text': '大家好，我是小美，今年25岁，是一位女性，是公主。很高兴在这个故事里与你相遇。'
        }
        result = _run_async(build_character_audio_text(
            character_data={"name": "小美", "age": "25", "identity": "公主", "appearance": "美丽的女子"},
            custom_text=None
        ))
        self.assertEqual(result, "大家好，我是小美，今年25岁，是一位女性，是公主。很高兴在这个故事里与你相遇。")

    @patch('task.audio_task._analyze_character_voice_capability')
    def test_no_character_data_at_all(self, mock_analyze):
        """完全无角色数据时使用默认值"""
        mock_analyze.return_value = {
            'sample_text': '大家好，我是我，是故事中的角色。很高兴在这个故事里与你相遇。'
        }
        result = _run_async(build_character_audio_text(
            character_data={},
            custom_text=None
        ))
        self.assertEqual(result, "大家好，我是我，是故事中的角色。很高兴在这个故事里与你相遇。")

    @patch('task.audio_task._analyze_character_voice_capability')
    def test_llm_returns_fallback_sample_text(self, mock_analyze):
        """LLM 未返回 sample_text 时使用默认模板"""
        mock_analyze.return_value = {}
        result = _run_async(build_character_audio_text(
            character_data={"name": "测试角色"},
            custom_text=None
        ))
        self.assertEqual(result, "大家好，我是测试角色。")

    def test_whitespace_only_custom_text_ignored(self):
        """仅含空格的 custom_text 被视为空，走 LLM 路径"""
        with patch('task.audio_task._analyze_character_voice_capability') as mock_analyze:
            mock_analyze.return_value = {
                'sample_text': '大家好，我是测试，是角色。很高兴在这个故事里与你相遇。'
            }
            result = _run_async(build_character_audio_text(
                character_data={"name": "测试", "identity": "角色"},
                custom_text="   "
            ))
            self.assertIn("我是测试", result)


class TestCalculateNextRetryDelay(unittest.TestCase):
    """测试 calculate_next_retry_delay()"""

    def test_first_retry(self):
        """第 1 次重试：3 * 2^0 = 3s"""
        self.assertEqual(calculate_next_retry_delay(1), 3)

    def test_second_retry(self):
        """第 2 次重试：3 * 2^1 = 6s"""
        self.assertEqual(calculate_next_retry_delay(2), 6)

    def test_third_retry(self):
        """第 3 次重试：3 * 2^2 = 12s"""
        self.assertEqual(calculate_next_retry_delay(3), 12)

    def test_fifth_retry(self):
        """第 5 次重试：3 * 2^4 = 48s"""
        self.assertEqual(calculate_next_retry_delay(5), 48)

    def test_seventh_retry(self):
        """第 7 次重试：3 * 2^6 = 192s"""
        self.assertEqual(calculate_next_retry_delay(7), 192)

    def test_capped_at_max_delay(self):
        """超过 360s 时截断"""
        # 3 * 2^7 = 384 > 360
        self.assertEqual(calculate_next_retry_delay(8), 360)

    def test_high_retry_count_still_capped(self):
        """很高重试次数仍然截断在 360s"""
        self.assertEqual(calculate_next_retry_delay(20), 360)

    def test_exact_boundary(self):
        """恰好不超限的边界：3 * 2^6 = 192 < 360"""
        self.assertEqual(calculate_next_retry_delay(7), 192)


if __name__ == '__main__':
    unittest.main()