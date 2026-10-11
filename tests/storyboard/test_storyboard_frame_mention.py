"""故事板 @首帧图 / @尾帧图 排图，以及隐藏混合任务可被显式选中。"""
from services.storyboard_frame_mention import (
    FrameMentionError,
    prepare_frame_mentions,
    prompt_has_frame_mention,
    should_use_h3_keyframe_ref,
)


def test_longer_token_does_not_match_frame_mention():
    assert prompt_has_frame_mention("看 @首帧图片 和 @尾帧图片") is False
    assert prompt_has_frame_mention("从 @首帧图 走到 @尾帧图") is True


def test_prepare_keeps_storyboard_image_when_no_token():
    prompt, urls, items = prepare_frame_mentions(
        "Slow dolly in.",
        ["https://cdn.test/first.png", "https://cdn.test/lin.png"],
        [
            {"type": "分镜图", "source_type": "asset", "name": "", "url": "https://cdn.test/first.png"},
            {"type": "角色", "source_type": "character", "name": "Lin", "url": "https://cdn.test/lin.png"},
        ],
        image_mode="multi_reference",
        first_url="https://cdn.test/first.png",
        last_url="https://cdn.test/last.png",
    )
    assert prompt == "Slow dolly in."
    assert urls[0] == "https://cdn.test/first.png"
    assert items[0]["type"] == "分镜图"
    assert "https://cdn.test/last.png" not in urls


def test_prepare_both_tokens_caps_middle_and_rewrites_prompt():
    prompt, urls, items = prepare_frame_mentions(
        "从 @首帧图 走到 @尾帧图",
        [
            "https://cdn.test/first.png",
            "https://cdn.test/lin.png",
            "https://cdn.test/alley.png",
            "https://cdn.test/style.png",
        ],
        [
            {"type": "分镜图", "source_type": "asset", "name": "", "url": "https://cdn.test/first.png"},
            {"type": "角色", "source_type": "character", "name": "Lin", "url": "https://cdn.test/lin.png"},
            {"type": "场景", "source_type": "location", "name": "Alley", "url": "https://cdn.test/alley.png"},
            {"type": "全局画风参考图", "source_type": "style", "name": "", "url": "https://cdn.test/style.png"},
        ],
        image_mode="multi_reference",
        first_url="https://cdn.test/first.png",
        last_url="https://cdn.test/last.png",
        max_images=3,
    )
    assert urls == [
        "https://cdn.test/first.png",
        "https://cdn.test/lin.png",
        "https://cdn.test/last.png",
    ]
    assert [item["type"] for item in items] == ["首帧", "角色", "尾帧"]
    assert items[0]["source_type"] == "asset"
    assert items[2]["source_type"] == "asset"
    assert "@首帧图" not in prompt and "@尾帧图" not in prompt
    assert "图1" in prompt and "图3" in prompt


def test_prepare_only_last_keeps_storyboard_image_in_the_middle():
    _prompt, urls, items = prepare_frame_mentions(
        "停在 @尾帧图",
        ["https://cdn.test/first.png", "https://cdn.test/lin.png"],
        [
            {"type": "分镜图", "source_type": "asset", "name": "", "url": "https://cdn.test/first.png"},
            {"type": "角色", "source_type": "character", "name": "Lin", "url": "https://cdn.test/lin.png"},
        ],
        image_mode="multi_reference",
        first_url="https://cdn.test/first.png",
        last_url="https://cdn.test/last.png",
        max_images=3,
    )
    assert urls[0] == "https://cdn.test/first.png"
    assert urls[-1] == "https://cdn.test/last.png"
    assert items[0]["type"] == "分镜图"
    assert items[-1]["type"] == "尾帧"


def test_prepare_missing_last_raises_and_same_url_can_fill_both_ends():
    try:
        prepare_frame_mentions(
            "停在 @尾帧图",
            ["https://cdn.test/first.png"],
            [{"type": "分镜图", "source_type": "asset", "name": "", "url": "https://cdn.test/first.png"}],
            image_mode="multi_reference",
            first_url="https://cdn.test/first.png",
            last_url="",
        )
    except FrameMentionError as exc:
        assert exc.code == "frame_mention_missing_last"
    else:
        raise AssertionError("missing last frame should fail")

    _prompt, urls, items = prepare_frame_mentions(
        "@首帧图 到 @尾帧图",
        ["https://cdn.test/same.png", "https://cdn.test/lin.png"],
        [
            {"type": "分镜图", "source_type": "asset", "name": "", "url": "https://cdn.test/same.png"},
            {"type": "角色", "source_type": "character", "name": "Lin", "url": "https://cdn.test/lin.png"},
        ],
        image_mode="multi_reference",
        first_url="https://cdn.test/same.png",
        last_url="https://cdn.test/same.png",
        max_images=3,
    )
    assert urls[0] == "https://cdn.test/same.png"
    assert urls[-1] == "https://cdn.test/same.png"
    assert items[0]["type"] == "首帧"
    assert items[-1]["type"] == "尾帧"
    assert urls.count("https://cdn.test/same.png") == 2


def test_h3_reference_keys_do_not_match_i2v_or_t2v():
    assert should_use_h3_keyframe_ref(
        "multi_reference", "从 @首帧图 出发", "minimax_h3_r2v"
    ) is True
    assert should_use_h3_keyframe_ref(
        "multi_reference", "从 @首帧图 出发", "minimax_h3_reference_to_video"
    ) is True
    assert should_use_h3_keyframe_ref(
        "multi_reference", "从 @首帧图 出发", "minimax_h3", "minimax_h3_image_to_video"
    ) is False
    assert should_use_h3_keyframe_ref(
        "multi_reference", "从 @首帧图 出发", "minimax_h3_t2v"
    ) is False
    assert should_use_h3_keyframe_ref(
        "first_last_frame", "从 @首帧图 出发", "minimax_h3_r2v"
    ) is False
    assert should_use_h3_keyframe_ref(
        "multi_reference", "没有标记", "minimax_h3_r2v"
    ) is False


def test_explicit_h3_keyframe_ref_task_is_accepted_when_hidden():
    from config.unified_config import TaskCategory, TaskTypeId
    from enterprise.tools.video_tools import _get_video_task_id

    task_id = int(TaskTypeId.MINIMAX_H3_KEYFRAME_REF_TO_VIDEO)
    assert _get_video_task_id(
        TaskCategory.IMAGE_TO_VIDEO,
        preferred_task_id=task_id,
    ) == task_id
