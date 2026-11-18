"""视频提示词追加对白：整句逐字重复才跳过，动作里的子串不跳过。"""
from api.storyboard import _format_dialogues_for_video_prompt


def test_appends_when_action_only_contains_the_four_characters():
    out = _format_dialogues_for_video_prompt(
        [{"text": "欢迎回家", "character_name": ""}],
        existing_prompt="动作：他把欢迎回家四个字写在门口",
    )
    assert "欢迎回家" in out
    assert out.startswith("对话：")


def test_skips_when_prompt_already_quotes_the_utterance():
    out = _format_dialogues_for_video_prompt(
        [{"text": "欢迎回家"}],
        existing_prompt="他说：「欢迎回家」",
    )
    assert out == ""


def test_skips_when_utterance_is_its_own_line():
    out = _format_dialogues_for_video_prompt(
        [{"text": "欢迎回家"}],
        existing_prompt="欢迎回家",
    )
    assert out == ""
