"""
audio_task 纯函数单元测试

测试 build_character_audio_text 和 calculate_next_retry_delay。
依赖 stub 通过 tests/base/test_isolation.py 官方工具安装，
import 中断也会在离开 with 时恢复 sys.modules 与父包属性。
"""
import asyncio
import unittest
from unittest.mock import MagicMock, patch

from tests.base.test_isolation import module_stub, stub_modules

_running_hub_cfg = MagicMock()
_running_hub_cfg.AUDIO_STYLE_DEFAULT_PROMPT = '声音自然清晰，语气平稳，适合角色旁白'
_running_hub_cfg.AUDIO_STYLE_LLM_MAX_TOKENS = 256
_running_hub_cfg.AUDIO_STYLE_LLM_TEMPERATURE = 0.7

with stub_modules({
    'model': module_stub(
        'model',
        TasksModel=MagicMock(),
        AIAudioModel=MagicMock(),
        StoryboardModel=MagicMock(),
        StoryboardSceneModel=MagicMock(),
        StoryboardDialogueModel=MagicMock(),
    ),
    # audio_task 直接 import 这些子模块，需 mock 以避免触发真实 DB/配置加载
    'model.storyboard': module_stub(
        'model.storyboard',
        StoryboardModel=MagicMock(),
        StoryboardSceneModel=MagicMock(),
    ),
    'model.storyboard_dialogue': module_stub(
        'model.storyboard_dialogue',
        StoryboardDialogueModel=MagicMock(),
    ),
    # storyboard_dialogue_audio 已在真实模块中, 但测试里也 mock 掉避免 DB
    'model.storyboard_dialogue_audio': module_stub(
        'model.storyboard_dialogue_audio',
        StoryboardDialogueAudioModel=MagicMock(),
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
    ),
    'task.async_drivers.runninghub_audio_driver': module_stub(
        'task.async_drivers.runninghub_audio_driver',
        RunningHubAudioConfig=_running_hub_cfg,
    ),
    'utils.index_tts_util': MagicMock(),
    'config.config_util': MagicMock(),
}):
    from task.audio_task import build_character_audio_text, calculate_next_retry_delay


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