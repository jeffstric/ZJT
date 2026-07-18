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


def test_normalize_storyboard_workflow_ratio():
    assert storyboard_api.normalize_storyboard_workflow_ratio("16:9") == "16:9"
    assert storyboard_api.normalize_storyboard_workflow_ratio("9:16") == "9:16"
    assert storyboard_api.normalize_storyboard_workflow_ratio(" 1:1 ") == "1:1"
    assert storyboard_api.normalize_storyboard_workflow_ratio("") is None
    assert storyboard_api.normalize_storyboard_workflow_ratio("21:9") is None
    assert storyboard_api.normalize_storyboard_workflow_ratio(None) is None


def test_resolve_storyboard_create_ratio_prefers_explicit(monkeypatch):
    monkeypatch.setattr(
        storyboard_api.StoryboardModel,
        "resolve_inherited_workflow_ratio",
        lambda user_id, world_id: {"workflow_ratio": "9:16", "source_episode_number": 1, "storyboard_count": 1},
    )
    assert storyboard_api.resolve_storyboard_create_ratio(1, 10, {"workflow_ratio": "16:9"}) == "16:9"


def test_resolve_storyboard_create_ratio_inherits_when_missing(monkeypatch):
    monkeypatch.setattr(
        storyboard_api.StoryboardModel,
        "resolve_inherited_workflow_ratio",
        lambda user_id, world_id: {"workflow_ratio": "9:16", "source_episode_number": 1, "storyboard_count": 2},
    )
    assert storyboard_api.resolve_storyboard_create_ratio(1, 10, {}) == "9:16"


def test_resolve_storyboard_create_ratio_defaults_when_empty_world(monkeypatch):
    monkeypatch.setattr(
        storyboard_api.StoryboardModel,
        "resolve_inherited_workflow_ratio",
        lambda user_id, world_id: None,
    )
    assert storyboard_api.resolve_storyboard_create_ratio(1, 10, {}) == "16:9"


def test_resolve_inherited_workflow_ratio_prefers_episode_one(monkeypatch):
    from model.storyboard import StoryboardModel

    rows = [
        {"id": 2, "episode_number": 2, "workflow_ratio": "16:9"},
        {"id": 1, "episode_number": 1, "workflow_ratio": "9:16"},
        {"id": 3, "episode_number": 3, "workflow_ratio": "1:1"},
    ]
    monkeypatch.setattr(StoryboardModel, "list_ratios_by_world", lambda user_id, world_id: rows)
    result = StoryboardModel.resolve_inherited_workflow_ratio(1, 10)
    assert result["workflow_ratio"] == "9:16"
    assert result["source_episode_number"] == 1
    assert result["storyboard_count"] == 3


def test_resolve_inherited_workflow_ratio_falls_back_to_min_episode(monkeypatch):
    from model.storyboard import StoryboardModel

    rows = [
        {"id": 5, "episode_number": 5, "workflow_ratio": "1:1"},
        {"id": 2, "episode_number": 2, "workflow_ratio": "9:16"},
    ]
    # list_ratios_by_world 约定已 ASC；此处模拟有序结果
    ordered = sorted(rows, key=lambda r: r["episode_number"])
    monkeypatch.setattr(StoryboardModel, "list_ratios_by_world", lambda user_id, world_id: ordered)
    result = StoryboardModel.resolve_inherited_workflow_ratio(1, 10)
    assert result["workflow_ratio"] == "9:16"
    assert result["source_episode_number"] == 2


def test_resolve_inherited_workflow_ratio_empty(monkeypatch):
    from model.storyboard import StoryboardModel

    monkeypatch.setattr(StoryboardModel, "list_ratios_by_world", lambda user_id, world_id: [])
    assert StoryboardModel.resolve_inherited_workflow_ratio(1, 10) is None
