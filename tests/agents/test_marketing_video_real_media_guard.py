from pathlib import Path

import httpx


ROOT_DIR = Path(__file__).resolve().parents[2]


def test_image_to_video_rejects_placeholder_image_url():
    from enterprise.tools.video_tools import image_to_video

    result = image_to_video(
        user_id="u1",
        world_id="w1",
        auth_token="token",
        prompt="restaurant promotion video",
        image_urls="https://example.com/reference_restaurant.jpg",
        ratio="9:16",
        duration_seconds=10,
    )

    assert result["success"] is False
    assert "占位" in result["error"] or "请上传" in result["error"]


def test_image_url_validator_rejects_unreachable_image_url(monkeypatch):
    from enterprise.tools import video_tools

    def raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("dns lookup failed")

    monkeypatch.setattr(video_tools.httpx, "head", raise_connect_error)

    error = video_tools._validate_real_media_urls(
        "https://cdn.real-merchant.test/reference_restaurant.jpg",
        "图片URL",
        "上传图片",
        probe=True,
    )

    assert error is not None
    assert "无法访问" in error
    assert "请上传图片" in error


def test_video_sop_requires_real_media_url_before_claiming_injected_reference_images():
    sop = (ROOT_DIR / "enterprise" / "sops" / "sop-video-generation.md").read_text(encoding="utf-8")

    assert "image_urls 为非空" in sop
    assert "image_urls 为 null" in sop
    assert "不得写成“用户已提供参考图片”" in sop


def test_marketing_video_skill_forbids_image_to_video_without_real_image_urls():
    skill = (ROOT_DIR / "enterprise" / "skills" / "marketing-video" / "SKILL.md").read_text(encoding="utf-8")

    assert "image_urls 为空" in skill
    assert "必须先 ask_user" in skill
    assert "https://example.com" in skill


def test_auto_video_duration_resolves_to_model_maximum():
    from enterprise.tools.video_tools import _resolve_video_duration_seconds

    class Config:
        supported_durations = [5, 10, 15]
        name = "Seedance 2.0 Fast"

    result = _resolve_video_duration_seconds(
        duration_seconds=5,
        user_prefs={"duration": "auto"},
        config=Config(),
    )

    assert result == 15
