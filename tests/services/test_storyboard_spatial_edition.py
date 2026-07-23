import pytest

from services.storyboard_spatial import (
    StoryboardEnterpriseFeatureRequired,
    build_spatial_prompt_context,
    derive_screen_projection,
    repair_spatial_layout_continuity,
)


def test_community_spatial_facade_rejects_enterprise_projection(monkeypatch):
    monkeypatch.setattr("config.constant.Edition.is_enterprise", lambda: False)

    with pytest.raises(StoryboardEnterpriseFeatureRequired) as exc:
        derive_screen_projection({}, {}, {})

    assert exc.value.error_code == "enterprise_only"
    assert "效果模式" in str(exc.value)


def test_community_spatial_prompt_context_keeps_legacy_layout_compatible(monkeypatch):
    monkeypatch.setattr("config.constant.Edition.is_enterprise", lambda: False)

    context = build_spatial_prompt_context(
        {
            "containers": [
                {
                    "name": "泡泡蒸汽车",
                    "slots": [
                        {
                            "occupant_type": "character",
                            "name": "奶昔_Milkshake",
                            "slot": "驾驶座",
                            "screen_position": "画面右侧",
                            "visibility": "visible",
                        }
                    ],
                }
            ]
        }
    )

    assert context["visible_entities"][0]["screen_position"] == "画面右侧"
    assert context["visible_entities"][0]["derived_screen_position"] is None


def test_community_spatial_repair_remains_compatible(monkeypatch):
    monkeypatch.setattr("config.constant.Edition.is_enterprise", lambda: False)

    parsed = {"characters": [], "shot_groups": []}

    assert repair_spatial_layout_continuity(parsed) is parsed
