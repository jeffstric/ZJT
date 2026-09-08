"""smart 逐句字幕单元测试。

覆盖：
- ``split_text_by_asr_sentences``：占比切分、切点吸附标点、时间缩放、异常回退
- ``split_long_seg_by_inner_punct``：单条 ASR 句超行时按标点二级细分
- ``build_subtitle_cues`` smart/block 两种模式与 ASR 缺失回退
- ``write_ass_file`` side_margin_ratio 透传
"""
import os
import tempfile

import pytest

from config.constant import StoryboardSubtitleConstants
from services.storyboard_subtitle import (
    SubtitleCue,
    build_subtitle_cues,
    split_long_seg_by_inner_punct,
    split_text_by_asr_sentences,
    wrap_subtitle_lines,
    write_ass_file,
)


class _Audio:
    def __init__(self, dialogue_id, text, duration):
        self.dialogue_id = dialogue_id
        self.text = text
        self.duration = duration
        self.file = "a.wav"
        self.url = "http://x/a.wav"


class _Scene:
    def __init__(self, duration, audios):
        self.duration = duration
        self.audios = audios


class _Plan:
    def __init__(self, scenes):
        self.scenes = scenes


# ---------------- split_text_by_asr_sentences ----------------

def test_split_by_asr_basic_punctuation_snap():
    """3 句 ASR：原文按占比切成 3 段，切点吸附标点，时间按比例缩放。"""
    text = "今天天气真好，我们一起去公园散步吧。下午还要开会呢，记得带上笔记本。晚上早点休息吧。"
    asr = [
        {"start": 0.0, "end": 4.0, "text": "今天天气真好，我们一起去公园散步吧。"},
        {"start": 4.0, "end": 8.0, "text": "下午还要开会呢，记得带上笔记本。"},
        {"start": 8.0, "end": 12.0, "text": "晚上早点休息吧。"},
    ]
    out = split_text_by_asr_sentences(text, asr, window_start=10.0, window_dur=12.0)
    assert out is not None
    assert len(out) == 3
    # 时间缩放 scale = 12/12 = 1，绝对时间从 10 起
    assert out[0][0] == pytest.approx(10.0, abs=1e-6)
    assert out[-1][1] == pytest.approx(22.0, abs=1e-6)
    # 每段以原文标点结尾（吸附成功）
    for _, _, seg in out:
        assert seg[-1] in "，。！？；、"


def test_split_by_asr_scales_time_when_asr_longer():
    """ASR 末句 end 超出音频时长时按比例缩放到窗口。"""
    text = "第一句话。第二句话。"
    asr = [
        {"start": 0.0, "end": 1.0, "text": "第一句话。"},
        {"start": 1.0, "end": 2.0, "text": "第二句话。"},
    ]
    out = split_text_by_asr_sentences(text, asr, window_start=5.0, window_dur=1.0)
    assert out is not None
    assert out[-1][1] <= 5.0 + 1.0 + 1e-6
    assert out[0][0] == pytest.approx(5.0, abs=1e-6)


def test_split_by_asr_returns_none_on_bad_input():
    """空句/空窗/比例超限均回退 None。"""
    text = "一些文本。"
    assert split_text_by_asr_sentences(text, [], window_start=0, window_dur=5) is None
    assert split_text_by_asr_sentences(text, [{"start": 0, "end": 1, "text": "x"}],
                                       window_start=0, window_dur=0) is None
    # scale 超限：ASR 末 end=100 但窗口仅 5s
    asr = [{"start": 0.0, "end": 50.0, "text": "一半。"}, {"start": 50.0, "end": 100.0, "text": "另一半。"}]
    assert split_text_by_asr_sentences(text, asr, window_start=0, window_dur=5) is None


# ---------------- split_long_seg_by_inner_punct ----------------

# 真实案例（对白 204）：SenseVoice 把句末感叹号转写成逗号，前 6.45s 成了
# 一条 30 字 ASR 句，竖屏（每行 16 字）折 3 行同屏
_LONG_SEG_TEXT = "我说了，那个方案不可行！账上就剩30万了，下个月工资都发不出来……"


def test_split_long_seg_by_inner_punct_basic():
    """超行长句按标点细分为多条，每条不超行，时间按占比内插且覆盖原窗口。"""
    pieces = split_long_seg_by_inner_punct(
        _LONG_SEG_TEXT, 10.0, 16.47, max_lines=2, max_chars=16
    )
    assert pieces is not None
    assert len(pieces) >= 2
    for s, e, seg in pieces:
        assert e > s
        assert len(wrap_subtitle_lines(seg, 16)) <= 2
    # 时间单调、无缝覆盖原窗口
    assert pieces[0][0] == pytest.approx(10.0, abs=1e-6)
    assert pieces[-1][1] == pytest.approx(16.47, abs=1e-6)
    assert all(pieces[i][1] <= pieces[i + 1][0] + 1e-6 for i in range(len(pieces) - 1))
    # 内容不丢（拼接后忽略空白与末尾差异应还原原文）
    assert "".join(seg for _, _, seg in pieces).replace(" ", "") == \
           _LONG_SEG_TEXT.replace(" ", "")


def test_split_long_seg_by_inner_punct_sparse_or_short_returns_none():
    """无标点长段 / 无需细分的短句返回 None，调用方沿用原逻辑。"""
    # 标点太稀：单片段自身就超 2 行
    assert split_long_seg_by_inner_punct(
        "这是一段完全没有任何标点的超长文本仍然无法细分", 0.0, 5.0,
        max_lines=2, max_chars=16,
    ) is None
    # 短句 1 行，无需细分
    assert split_long_seg_by_inner_punct(
        "你好。", 0.0, 1.0, max_lines=2, max_chars=16,
    ) is None
    # 空文本 / 零时长
    assert split_long_seg_by_inner_punct("", 0.0, 1.0, max_lines=2, max_chars=16) is None
    assert split_long_seg_by_inner_punct("文本。", 0.0, 0.0, max_lines=2, max_chars=16) is None


# ---------------- build_subtitle_cues ----------------

def _make_plan():
    return _Plan([
        _Scene(12.0, [_Audio(101, "今天天气真好，我们一起去公园散步吧。下午还要开会呢。", 12.0)]),
    ])


def test_build_cues_smart_mode_uses_asr_sentences():
    """smart 模式：有 ASR 句 → 每句一条短 cue，而非整条 3 行分页。"""
    plan = _make_plan()
    asr = {
        101: [
            {"start": 0.0, "end": 6.0, "text": "今天天气真好，我们一起去公园散步吧。"},
            {"start": 6.0, "end": 12.0, "text": "下午还要开会呢。"},
        ]
    }
    cues = build_subtitle_cues(plan, width=1080, height=1920,
                               subtitle_mode="smart", asr_sents_by_dialogue=asr)
    assert cues, "smart 模式应产出 cue"
    # 至少每句一条 cue（单句超 max_chars 行宽时句内还会再折行/分页）
    assert len(cues) >= 2
    # 每条 cue 行数不超过 MAX_LINES
    for c in cues:
        assert len(c.text.split("\\N")) <= StoryboardSubtitleConstants.MAX_LINES
    # 覆盖窗口起点与终点
    assert cues[0].start == pytest.approx(0.0, abs=0.2)
    assert cues[-1].end <= 12.0 + 1e-6


def test_build_cues_smart_long_asr_sentence_splits_by_inner_punct():
    """端到端（分镜5真实场景）：单条 30 字 ASR 句不再 3 行同屏，按标点细分轮播。"""
    text = ("我说了，那个方案不可行！账上就剩30万了，下个月工资都发不出来……"
            "我知道，但研发不能停！")
    plan = _Plan([_Scene(9.0, [_Audio(204, text, 8.998)])])
    # ASR 实际返回：感叹号被转写成逗号，前 6.45s 一整句
    asr = {
        204: [
            {"start": 0.0, "end": 6.45,
             "text": "我说了，那个方案不可行，账上就剩30万了，下个月工资都发不出来。"},
            {"start": 6.45, "end": 8.97, "text": "我知道，但研发不能停。"},
        ]
    }
    cues = build_subtitle_cues(plan, width=1080, height=1920,
                               subtitle_mode="smart", asr_sents_by_dialogue=asr)
    assert cues
    for c in cues:
        assert len(c.text.split("\\N")) <= StoryboardSubtitleConstants.SMART_CUE_MAX_LINES
    # 时间轴覆盖整条对白窗口
    assert cues[0].start == pytest.approx(0.0, abs=0.2)
    assert cues[-1].end <= 9.0 + 1e-6


def test_build_cues_smart_without_asr_falls_back_to_block():
    """smart 模式但无 ASR 数据：回退 block 分页，不丢字幕。"""
    plan = _make_plan()
    cues = build_subtitle_cues(plan, width=1080, height=1920,
                               subtitle_mode="smart", asr_sents_by_dialogue={})
    assert cues
    assert isinstance(cues[0], SubtitleCue)


def test_build_cues_block_mode_matches_legacy():
    """显式 block 模式与旧逻辑一致：整条折行分页。"""
    plan = _make_plan()
    cues_block = build_subtitle_cues(plan, width=1080, height=1920, subtitle_mode="block")
    cues_legacy = build_subtitle_cues(plan, width=1080, height=1920)
    assert [(c.start, c.end, c.text) for c in cues_block] == \
           [(c.start, c.end, c.text) for c in cues_legacy]


# ---------------- write_ass_file side margin ----------------

def test_write_ass_file_side_margin_ratio():
    """side_margin_ratio 透传到 MarginL/MarginR，并做范围 clamp。"""
    cues = [SubtitleCue(start=0.0, end=1.0, text="你好")]
    with tempfile.TemporaryDirectory() as td:
        p1 = os.path.join(td, "a.ass")
        write_ass_file(cues, p1, 1080, 1920, side_margin_ratio=0.10)
        content = open(p1, encoding="utf-8-sig").read()
        # 1080*0.10 = 108
        assert ",108,108," in content

        p2 = os.path.join(td, "b.ass")
        write_ass_file(cues, p2, 1080, 1920, side_margin_ratio=0.9)  # 超 max → clamp 0.18
        content2 = open(p2, encoding="utf-8-sig").read()
        assert f",{int(1080 * StoryboardSubtitleConstants.SIDE_MARGIN_RATIO_MAX)},{int(1080 * StoryboardSubtitleConstants.SIDE_MARGIN_RATIO_MAX)}," in content2

        p3 = os.path.join(td, "c.ass")
        write_ass_file(cues, p3, 1080, 1920)  # 缺省 → 默认常量
        content3 = open(p3, encoding="utf-8-sig").read()
        assert f",{int(1080 * StoryboardSubtitleConstants.SIDE_MARGIN_RATIO)},{int(1080 * StoryboardSubtitleConstants.SIDE_MARGIN_RATIO)}," in content3
