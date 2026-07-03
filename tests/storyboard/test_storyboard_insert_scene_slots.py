from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_storyboard_frontend_renders_insert_scene_slots():
    render_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "render.js").read_text(encoding="utf-8")

    assert "renderInsertSceneSlot" in render_js
    assert 'data-action="insert-scene"' in render_js
    assert "scene-timeline-insert-slot" in render_js
    assert "grid-insert-slot" in render_js


def test_storyboard_frontend_handles_insert_scene_action():
    events_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "events.js").read_text(encoding="utf-8")

    assert "action === 'insert-scene'" in events_js
    assert "prev_id" in events_js
    assert "next_id" in events_js
