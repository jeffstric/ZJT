from api import storyboard as storyboard_api


class _Script:
    def __init__(self, record_id):
        self.id = record_id


class _WorldWithoutReference:
    visual_style = "写实电影"


def test_resolve_storyboard_script_id_uses_explicit_script_id():
    assert storyboard_api.resolve_storyboard_script_id(42, 7, 3) == 42


def test_resolve_storyboard_script_id_falls_back_to_world_episode(monkeypatch):
    calls = []

    def fake_get_by_episode(world_id, episode_number):
        calls.append((world_id, episode_number))
        return _Script(88)

    monkeypatch.setattr(storyboard_api.ScriptModel, "get_by_episode", fake_get_by_episode)

    assert storyboard_api.resolve_storyboard_script_id(None, 7, 3) == 88
    assert calls == [(7, 3)]


def test_build_storyboard_defaults_tolerates_world_without_reference_image():
    defaults = storyboard_api.build_storyboard_defaults(
        _WorldWithoutReference(),
        {"workflow_ratio": "9:16"},
    )

    assert defaults["style"] == "写实电影"
    assert defaults["workflow_ratio"] == "9:16"
    assert defaults["style_reference_image"] is None
