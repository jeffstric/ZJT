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
]


def test_enterprise_video_clone_docs_include_seedance_mini_model():
    for path in VIDEO_CLONE_DOCS:
        text = path.read_text(encoding="utf-8")

        assert "seedance2.0-mini" in text, f"{path} should mention seedance2.0-mini"
        assert "Seedance2.0 Mini" in text, f"{path} should mention the display name"

        for old_phrase in OLD_SEEDANCE_ONLY_PHRASES:
            assert old_phrase not in text, f"{path} still contains old model limit: {old_phrase}"
