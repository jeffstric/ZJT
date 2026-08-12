"""对白情感向量门面：社区 fail-closed 行为。"""
import unittest

from services import dialogue_emotion as facade


class TestDialogueEmotionFacade(unittest.TestCase):
    def setUp(self):
        facade.reset_provider()

    def tearDown(self):
        facade.reset_provider()

    def test_community_defaults_disabled(self):
        self.assertFalse(facade.is_available())
        self.assertFalse(facade.is_enabled())
        self.assertFalse(facade.parser_emotion_enabled())
        self.assertEqual(facade.build_parser_emotion_instructions(), "")
        # 社区允许规范化以便前端编辑入库，但不启用 TTS
        normalized = facade.normalize_emo_vec([0.5, 0, 0, 0, 0, 0, 0, 0])
        self.assertIsNotNone(normalized)
        self.assertTrue(normalized.startswith("0.5000"))
        self.assertEqual(
            facade.resolve_tts_emotion_kwargs(
                dialogue={"emo_vec": "0.5,0,0,0,0,0,0,0"},
                config={"emo_control_method": 2, "emo_vec": "0.5,0,0,0,0,0,0,0"},
            ),
            {},
        )

    def test_register_requires_available(self):
        class Bad:
            available = False

        with self.assertRaises(ValueError):
            facade.register_provider(Bad())


if __name__ == "__main__":
    unittest.main()
