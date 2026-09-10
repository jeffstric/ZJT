"""台词 ↔ ASR 有序切分。"""
import unittest

from config.constant import VoiceReplaceConstants as C
from services.voice_replace.aligner import (
    AsrSegment,
    DialogueLine,
    align_dialogues,
    normalize_text,
    score_pair,
)


def _d(text, character_id=1, name="甲", dialogue_id=None, sort_order=0.0):
    return DialogueLine(
        text=text,
        character_id=character_id,
        character_name=name,
        id=dialogue_id,
        sort_order=sort_order,
    )


def _a(start, end, text):
    return AsrSegment(start=start, end=end, text=text)


class TestNormalizeAndScore(unittest.TestCase):
    def test_normalize_strips_punct_and_width(self):
        self.assertEqual(normalize_text("【【赵志高】】：「去，把仓库搬了！」"), "赵志高去把仓库搬了")
        self.assertEqual(normalize_text("Hello, WORLD"), "helloworld")

    def test_exact_and_near_substring_scores(self):
        self.assertEqual(score_pair("去把仓库杂物搬了", "去把仓库杂物搬了"), 1.0)
        self.assertGreaterEqual(score_pair("去把仓库杂物搬了", "去把仓库那堆杂物搬了"), 0.8)
        # 长 ASR 包含短对白必须明显低于紧窗口，否则会吞掉后面的台词
        self.assertLess(
            score_pair("再见", "限时广告买一送一再见"),
            score_pair("再见", "再见"),
        )
        self.assertLess(score_pair("再见", "限时广告买一送一再见"), 0.75)

    def test_empty_scores_zero(self):
        self.assertEqual(score_pair("", "你好"), 0.0)
        self.assertEqual(score_pair("你好", ""), 0.0)


class TestAlignDialogues(unittest.TestCase):
    def test_no_dialogue_skips(self):
        result = align_dialogues([], [_a(0, 1, "你好")])
        self.assertEqual(result.status, C.STATUS_SKIP)
        self.assertEqual(result.skip_reason, C.SKIP_NO_DIALOGUE)

    def test_empty_text_dialogue_skips(self):
        result = align_dialogues([_d("  …  ")], [_a(0, 1, "你好")])
        self.assertEqual(result.status, C.STATUS_SKIP)
        self.assertEqual(result.skip_reason, C.SKIP_NO_DIALOGUE)

    def test_no_speech_skips(self):
        result = align_dialogues([_d("你好")], [])
        self.assertEqual(result.status, C.STATUS_SKIP)
        self.assertEqual(result.skip_reason, C.SKIP_NO_SPEECH)

    def test_single_speaker_short_circuit(self):
        result = align_dialogues(
            [_d("去把仓库杂物搬了", character_id=9, name="赵志高", dialogue_id=1)],
            [_a(0.3, 2.8, "去把仓库那堆杂物搬了")],
        )
        self.assertEqual(result.status, C.STATUS_AUTO)
        self.assertEqual(len(result.segments), 1)
        seg = result.segments[0]
        self.assertEqual(seg.method, C.METHOD_SINGLE_SPEAKER)
        self.assertEqual(seg.character_id, 9)
        self.assertAlmostEqual(seg.start, 0.3)
        self.assertAlmostEqual(seg.end, 2.8)

    def test_single_speaker_multiple_lines_same_character(self):
        result = align_dialogues(
            [
                _d("你还好吗", character_id=2, name="甲", dialogue_id=1),
                _d("开门", character_id=2, name="甲", dialogue_id=2),
            ],
            [_a(0.0, 1.0, "你还好吗"), _a(1.2, 2.0, "开门")],
        )
        self.assertEqual(result.status, C.STATUS_AUTO)
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(result.segments[0].character_id, 2)
        self.assertEqual(result.segments[0].method, C.METHOD_SINGLE_SPEAKER)

    def test_two_speakers_exact_segments(self):
        result = align_dialogues(
            [
                _d("你还好吗", character_id=1, name="甲", dialogue_id=11),
                _d("我很好谢谢", character_id=2, name="乙", dialogue_id=12),
            ],
            [_a(0.2, 1.1, "你还好吗"), _a(1.3, 2.6, "我很好谢谢")],
        )
        self.assertEqual(result.status, C.STATUS_AUTO)
        self.assertEqual(len(result.segments), 2)
        self.assertEqual(result.segments[0].character_id, 1)
        self.assertEqual(result.segments[1].character_id, 2)
        self.assertGreaterEqual(result.segments[0].score, C.SCORE_AUTO)
        self.assertGreaterEqual(result.segments[1].score, C.SCORE_AUTO)
        self.assertLess(result.segments[0].end, result.segments[1].start + 0.05)
        self.assertAlmostEqual(result.segments[0].start, 0.2, places=1)
        self.assertAlmostEqual(result.segments[1].end, 2.6, places=1)

    def test_one_voice_two_roles_paraphrase_falls_back_to_order(self):
        result = align_dialogues(
            [
                _d("你还好吗", character_id=1, name="甲", dialogue_id=1),
                _d("我很好谢谢", character_id=2, name="乙", dialogue_id=2),
            ],
            [_a(0.2, 3.0, "哼哼哈哈今天天气不错出门玩")],
        )
        self.assertEqual(result.status, C.STATUS_WAIT_CONFIRM)
        self.assertEqual(len(result.segments), 2)
        self.assertTrue(all(s.method == C.METHOD_ORDER for s in result.segments))
        self.assertEqual(result.segments[0].character_id, 1)
        self.assertEqual(result.segments[1].character_id, 2)
        self.assertAlmostEqual(result.segments[0].start, 0.2)
        self.assertAlmostEqual(result.segments[-1].end, 3.0)
        self.assertLess(result.segments[0].end, result.segments[1].end)

    def test_rewritten_but_overlapping_text_still_splits_two_roles(self):
        result = align_dialogues(
            [
                _d("你还好吗", character_id=1, name="甲", dialogue_id=1),
                _d("我很好谢谢", character_id=2, name="乙", dialogue_id=2),
            ],
            [_a(0.0, 3.0, "你还好吗我很好谢谢")],
        )
        self.assertEqual(result.status, C.STATUS_AUTO)
        self.assertEqual(result.segments[0].character_id, 1)
        self.assertEqual(result.segments[1].character_id, 2)
        self.assertLess(result.segments[0].end, result.segments[1].end)

    def test_missing_middle_line_is_skipped(self):
        result = align_dialogues(
            [
                _d("早上好", character_id=1, name="甲", dialogue_id=1),
                _d("这句成片没说", character_id=2, name="乙", dialogue_id=2),
                _d("再见", character_id=1, name="甲", dialogue_id=3),
            ],
            [_a(0.0, 1.0, "早上好"), _a(1.5, 2.2, "再见")],
        )
        self.assertEqual(len(result.segments), 3)
        self.assertEqual(result.segments[1].method, C.METHOD_SKIPPED)
        self.assertEqual(result.segments[0].character_id, 1)
        self.assertEqual(result.segments[2].character_id, 1)
        self.assertGreater(result.segments[2].start, result.segments[0].end - 1e-6)

    def test_extra_speech_kept_as_leftover(self):
        result = align_dialogues(
            [
                _d("你好", character_id=1, name="甲", dialogue_id=1),
                _d("再见", character_id=2, name="乙", dialogue_id=2),
            ],
            [
                _a(0.0, 0.8, "你好"),
                _a(0.8, 1.2, "限时广告买一送一"),
                _a(1.2, 2.0, "再见"),
            ],
        )
        self.assertEqual(result.status, C.STATUS_AUTO)
        self.assertEqual(result.segments[0].character_id, 1)
        self.assertEqual(result.segments[1].character_id, 2)
        leftover_text = "".join(s.text for s in result.leftover_asr)
        self.assertIn("广告", leftover_text)
        self.assertGreater(result.unmatched_asr_ratio, 0.0)

    def test_all_narration_same_null_character_short_circuits(self):
        result = align_dialogues(
            [_d("夜幕降临", character_id=None, name="旁白", dialogue_id=1)],
            [_a(0.0, 2.0, "夜幕降临")],
        )
        self.assertEqual(result.status, C.STATUS_AUTO)
        self.assertEqual(result.segments[0].method, C.METHOD_SINGLE_SPEAKER)
        self.assertIsNone(result.segments[0].character_id)


if __name__ == "__main__":
    unittest.main()
