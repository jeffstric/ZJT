import pytest

from services import script_split_strategy
from services.storyboard_spatial.exceptions import StoryboardEnterpriseFeatureRequired


def test_standard_strategy_never_loads_enterprise(monkeypatch):
    imported = []
    monkeypatch.setattr(script_split_strategy.Edition, "is_community", lambda: True)
    monkeypatch.setattr(
        script_split_strategy.importlib,
        "import_module",
        lambda name: imported.append(name),
    )

    strategy = script_split_strategy.get_script_split_strategy("speed")

    assert strategy.mode == "speed"
    assert strategy.parallel_enabled is False
    assert imported == []


def test_quality_strategy_is_rejected_in_community(monkeypatch):
    monkeypatch.setattr(script_split_strategy.Edition, "is_community", lambda: True)

    with pytest.raises(StoryboardEnterpriseFeatureRequired):
        script_split_strategy.get_script_split_strategy("quality")


def test_quality_strategy_is_lazily_loaded_in_enterprise(monkeypatch):
    class FakeQualityStrategy:
        mode = "quality"
        parallel_enabled = True

    calls = []
    monkeypatch.setattr(script_split_strategy.Edition, "is_community", lambda: False)

    class FakeModule:
        QualityScriptSplitStrategy = FakeQualityStrategy

    monkeypatch.setattr(
        script_split_strategy.importlib,
        "import_module",
        lambda name: calls.append(name) or FakeModule,
    )

    strategy = script_split_strategy.get_script_split_strategy("quality")

    assert isinstance(strategy, FakeQualityStrategy)
    assert calls == ["enterprise.services.script_split_quality"]
