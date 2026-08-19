from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]

VIDEO_CLONE_DOCS = [
    ROOT_DIR / "enterprise" / "skills" / "marketing-video" / "SKILL.md",
    ROOT_DIR / "enterprise" / "sops" / "sop-video-clone.md",
    ROOT_DIR / "docs" / "marketing_agent.md",
]

OLD_SEEDANCE_ONLY_PHRASES = [
    "仅支持 Seedance2.0 和 Seedance2.0 Fast",
    "不是 Seedance2.0 或 Seedance2.0 Fast",
    "仅支持 Seedance2.0、Seedance2.0 Fast 和 Seedance2.0 Mini（seedance2.0-mini）模型",
]


def test_enterprise_video_clone_docs_include_seedance_mini_model():
    for path in VIDEO_CLONE_DOCS:
        text = path.read_text(encoding="utf-8")

        assert "seedance2.0-mini" in text, f"{path} should mention seedance2.0-mini"
        assert "Seedance2.0 Mini" in text, f"{path} should mention the display name"

        for old_phrase in OLD_SEEDANCE_ONLY_PHRASES:
            assert old_phrase not in text, f"{path} still contains old model limit: {old_phrase}"


def test_enterprise_video_clone_docs_include_seedance_2_5_model():
    for path in VIDEO_CLONE_DOCS:
        text = path.read_text(encoding="utf-8")

        assert "seedance2.5" in text, f"{path} should mention seedance2.5"
        assert "Seedance 2.5" in text, f"{path} should mention the display name"


def test_enterprise_video_clone_docs_include_minimax_h3_model():
    for path in VIDEO_CLONE_DOCS:
        text = path.read_text(encoding="utf-8")

        assert "MiniMax H3" in text, f"{path} should mention MiniMax H3"
        assert "minimax_h3" in text.lower() or "参考生视频" in text, (
            f"{path} should mention MiniMax H3 reference-to-video"
        )
