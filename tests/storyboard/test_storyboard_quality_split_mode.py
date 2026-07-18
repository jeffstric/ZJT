from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_storyboard_generate_from_script_submits_selected_sequence_mode():
    events = (PROJECT_ROOT / "web/js/storyboard/events.js").read_text(encoding="utf-8")
    api_source = (PROJECT_ROOT / "api/storyboard.py").read_text(encoding="utf-8")

    assert "sequence_mode: state.autoImageSequenceMode" in events
    assert "sequence_mode = str(data.get('sequence_mode')" in api_source
    assert "'sequence_mode': sequence_mode" in api_source


def test_storyboard_backend_has_quality_enterprise_gate():
    api_source = (PROJECT_ROOT / "api/storyboard.py").read_text(encoding="utf-8")

    assert "sequence_mode == 'quality'" in api_source
    assert "Edition.is_community()" in api_source
    assert "enterprise_only" in api_source
