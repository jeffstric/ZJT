from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]

LOCAL_LIFE_VIDEO_DOCS = [
    ROOT_DIR / "enterprise" / "skills" / "marketing-video" / "SKILL.md",
    ROOT_DIR / "enterprise" / "sops" / "sop-video-generation.md",
    ROOT_DIR / "docs" / "marketing_agent.md",
]


def test_local_life_video_docs_recommend_seedance_without_blocking_other_models():
    for path in LOCAL_LIFE_VIDEO_DOCS:
        text = path.read_text(encoding="utf-8")

        assert "本地生活" in text, f"{path} should document local-life video handling"
        assert "10~15秒" in text, f"{path} should recommend 10~15 seconds for local-life videos"
        assert "Seedance2.0" in text, f"{path} should recommend the Seedance2.0 series"
        assert "不能拒绝" in text or "不得拒绝" in text, f"{path} should keep non-Seedance models usable"


def test_local_life_video_docs_prioritize_business_info_over_generic_animation_style():
    sop = (ROOT_DIR / "enterprise" / "sops" / "sop-video-generation.md").read_text(encoding="utf-8")
    skill = (ROOT_DIR / "enterprise" / "skills" / "marketing-video" / "SKILL.md").read_text(encoding="utf-8")
    docs = (ROOT_DIR / "docs" / "marketing_agent.md").read_text(encoding="utf-8")

    assert "默认不主动询问非真实画风" in sop
    assert "店名" in sop
    assert "主推菜品" in sop
    assert "核心卖点" in sop
    assert "我要上传参考图片" in sop
    assert "真实探店感" in sop
    assert "暖色食欲感" in sop
    assert "动画风格" not in sop

    assert "本地生活默认真实实拍" in skill
    assert "动画风格" not in skill

    assert "优先收集店名、主推菜品、核心卖点和参考图片" in docs


def test_local_life_video_docs_warn_when_duration_is_too_short():
    sop = (ROOT_DIR / "enterprise" / "sops" / "sop-video-generation.md").read_text(encoding="utf-8")
    skill = (ROOT_DIR / "enterprise" / "skills" / "marketing-video" / "SKILL.md").read_text(encoding="utf-8")
    docs = (ROOT_DIR / "docs" / "marketing_agent.md").read_text(encoding="utf-8")

    assert "3秒、5秒或8秒" in sop
    assert "推荐改为 auto 或当前模型最长时长" in sop
    assert "不得直接按 5秒 生成" in sop

    assert "auto 时长" in skill
    assert "模型支持的最长时长" in skill

    assert "本地生活营销视频如果选择 3/5/8 秒" in docs
