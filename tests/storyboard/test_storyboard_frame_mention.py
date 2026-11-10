"""故事板 @首帧图 / @尾帧图 排图与按实现方裁图。

首帧参考混合实现方挂在类型 37 参考生下（见 docs/video/h3_keyframe_ref_as_reference_impl_design.md）：
排图（prepare_frame_mentions）产出「图N是首帧/尾帧」锚点句，实现方选出后由
trim_reference_images_for_implementation 按上限裁中间参考并重排图例序号。
"""
from services.storyboard_frame_mention import (
    FrameMentionError,
    effective_frame_flags,
    is_h3_reference_model,
    prepare_frame_mentions,
    prompt_has_frame_mention,
    trim_reference_images_for_implementation,
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


def test_prepare_places_frames_at_both_ends_and_rewrites_prompt():
    """排图不裁：点名帧移两端、去重、改写提示词；上限裁剪延后到选出实现方"""
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
    )
    # 排图后全量保留（未裁）：首帧 + 3 中间 + 尾帧
    assert urls == [
        "https://cdn.test/first.png",
        "https://cdn.test/lin.png",
        "https://cdn.test/alley.png",
        "https://cdn.test/style.png",
        "https://cdn.test/last.png",
    ]
    assert [item["type"] for item in items] == ["首帧", "角色", "场景", "全局画风参考图", "尾帧"]
    assert items[0]["source_type"] == "asset"
    assert items[-1]["source_type"] == "asset"
    assert "@首帧图" not in prompt and "@尾帧图" not in prompt
    assert "图1" in prompt and "图5" in prompt


def test_trim_keeps_both_ends_and_renumbers_legend_sentences():
    """KFR 裁 3：两端保留裁中间；被裁图例句删除、保留序号重排为连续

    prompt 是排图产物：auto 句「@首帧图是首帧/@尾帧图是尾帧」改写后含锚点句
    （图N是首帧/尾帧），中间图例句由图例 suffix 拼接生成。
    """
    prepared_prompt = (
        "图1是首帧。从这一格开始推进剧情。\n"
        "图2是角色Lin。\n图3是场景Alley。\n图4是画风。\n"
        "图5是尾帧。"
    )
    urls = [
        "https://cdn.test/first.png",
        "https://cdn.test/lin.png",
        "https://cdn.test/alley.png",
        "https://cdn.test/style.png",
        "https://cdn.test/last.png",
    ]
    prompt, out_urls, out_items = trim_reference_images_for_implementation(
        prepared_prompt, urls, None, max_images=3,
    )
    assert out_urls == [
        "https://cdn.test/first.png",
        "https://cdn.test/lin.png",
        "https://cdn.test/last.png",
    ]
    # 中间只留 1 张（图2 角色），被裁的图3/图4 图例句整句删除
    assert "图3是场景" not in prompt
    assert "图4是画风" not in prompt
    assert "图2是角色Lin" in prompt
    # 首尾锚点句保留且序号重排为 1/3
    assert "图1是首帧" in prompt
    assert "图3是尾帧" in prompt
    assert len(out_items) == 3


def test_trim_first_only_keeps_head_and_budget_middle():
    prepared_prompt = "图1是首帧。图2是角色Lin。图3是场景Alley。"
    urls = [
        "https://cdn.test/first.png",
        "https://cdn.test/lin.png",
        "https://cdn.test/alley.png",
    ]
    prompt, out_urls, _ = trim_reference_images_for_implementation(
        prepared_prompt, urls, None, max_images=2,
    )
    assert out_urls == ["https://cdn.test/first.png", "https://cdn.test/lin.png"]
    assert "图1是首帧" in prompt
    assert "图2是角色Lin" in prompt
    assert "图3是场景" not in prompt


def test_trim_accepts_mention_token_form_for_agent_chain():
    """agent 链路提交原文保留 @首帧图 token（排图改写不回传）：同样两端保留"""
    urls = [
        "https://cdn.test/first.png",
        "https://cdn.test/lin.png",
        "https://cdn.test/alley.png",
        "https://cdn.test/last.png",
    ]
    prompt, out_urls, _ = trim_reference_images_for_implementation(
        "从 @首帧图 走到 @尾帧图", urls, None, max_images=3,
    )
    assert out_urls == [
        "https://cdn.test/first.png",
        "https://cdn.test/lin.png",
        "https://cdn.test/last.png",
    ]
    # @token 不做序号改写（该链路无图例句），保持原文
    assert prompt == "从 @首帧图 走到 @尾帧图"


def test_trim_without_mention_cuts_tail_plainly():
    urls = [f"https://cdn.test/{i}.png" for i in range(5)]
    prompt, out_urls, _ = trim_reference_images_for_implementation(
        "没有点名标记的普通提交", urls, None, max_images=3,
    )
    assert out_urls == urls[:3]
    assert prompt == "没有点名标记的普通提交"


def test_trim_within_limit_is_noop():
    urls = ["https://cdn.test/a.png", "https://cdn.test/b.png"]
    prompt, out_urls, _ = trim_reference_images_for_implementation(
        "图1是首帧。图2是尾帧。", urls, None, max_images=3,
    )
    assert out_urls == urls
    assert prompt == "图1是首帧。图2是尾帧。"


def test_effective_frame_flags_matches_both_forms():
    assert effective_frame_flags("从 @首帧图 出发") == (True, False)
    assert effective_frame_flags("图1是首帧。图2是尾帧。") == (True, True)
    assert effective_frame_flags("没有任何标记") == (False, False)


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
    )
    assert urls[0] == "https://cdn.test/same.png"
    assert urls[-1] == "https://cdn.test/same.png"
    assert items[0]["type"] == "首帧"
    assert items[-1]["type"] == "尾帧"
    assert urls.count("https://cdn.test/same.png") == 2


def test_h3_reference_keys_do_not_match_i2v_or_t2v():
    assert is_h3_reference_model("minimax_h3_r2v") is True
    assert is_h3_reference_model("minimax_h3_reference_to_video") is True
    assert is_h3_reference_model("minimax_h3", "minimax_h3_image_to_video") is False
    assert is_h3_reference_model("minimax_h3_t2v") is False


def test_disabled_task50_falls_back_when_explicitly_requested():
    """类型 50 已 enabled=False：显式传 50 回退到偏好/默认（不再创建类型 50）"""
    from config.unified_config import TaskCategory, TaskTypeId, UnifiedConfigRegistry
    from enterprise.tools.video_tools import _get_video_task_id

    task_id = int(TaskTypeId.MINIMAX_H3_KEYFRAME_REF_TO_VIDEO)
    config = UnifiedConfigRegistry.get_by_id(task_id)
    assert config.enabled is False and config.hidden is True
    resolved = _get_video_task_id(TaskCategory.IMAGE_TO_VIDEO, preferred_task_id=task_id)
    assert resolved != task_id


def test_token_with_unique_id_suffix_is_consumed_without_residue():
    """前端插入的标记带唯一短 id 后缀：按同一语义解析，改写后不残留 :id。"""
    assert prompt_has_frame_mention("看 @首帧图:1c88f7a9 就行") is True
    assert prompt_has_frame_mention("从 @尾帧图:0be032f5 出发") is True
    prompt, urls, items = prepare_frame_mentions(
        "从 @首帧图:1c88f7a9 开始",
        [
            "https://cdn.test/first.png",
            "https://cdn.test/lin.png",
        ],
        [
            {"type": "分镜图", "source_type": "asset", "name": "", "url": "https://cdn.test/first.png"},
            {"type": "角色", "source_type": "character", "name": "Lin", "url": "https://cdn.test/lin.png"},
        ],
        image_mode="multi_reference",
        first_url="https://cdn.test/first.png",
        last_url="https://cdn.test/last.png",
    )
    assert prompt == "从 图1 开始"
    assert ":1c88f7a9" not in prompt
    assert urls[0] == "https://cdn.test/first.png"


def test_malformed_id_suffix_degrades_to_plain_text():
    """手改坏的非 8 位 id 不再命中标记：按普通文本提交，不误判点名。"""
    assert prompt_has_frame_mention("看 @首帧图:1c88f7") is False
    assert prompt_has_frame_mention("看 @首帧图1c88") is False
