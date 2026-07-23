import sys
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constant import StoryType
from model import world as world_model
from model.world import World, WorldModel
from script_writer_core import mcp_tool
from script_writer_core.file_manager import FileManager


def test_world_model_exposes_story_type_default_and_dict():
    world = World(id=1, name="测试世界", user_id=7)

    assert world.story_type == StoryType.DIALOGUE
    assert world.to_dict()["story_type"] == StoryType.DIALOGUE


def test_world_create_table_sql_contains_story_type_default():
    assert "`story_type` varchar(32)" in world_model.CREATE_TABLE_SQL
    assert f"DEFAULT '{StoryType.DIALOGUE}'" in world_model.CREATE_TABLE_SQL


def test_world_model_create_accepts_story_type():
    with patch("model.world.execute_insert", return_value=123) as execute_insert:
        world_id = WorldModel.create(
            name="测试世界",
            user_id=7,
            story_type=StoryType.NARRATION,
        )

    assert world_id == 123
    sql, params = execute_insert.call_args.args
    assert "story_type" in sql
    assert StoryType.NARRATION in params


def test_mcp_read_world_returns_story_type():
    fake_manager = Mock()
    fake_manager.get_world_json.return_value = {
        "name": "测试世界",
        "story_type": StoryType.MUSIC_MV,
    }

    with patch("script_writer_core.mcp_tool.get_file_manager", return_value=fake_manager):
        result = mcp_tool.read_world("7", "1", "token")

    assert result["success"] is True
    assert result["story_type"] == StoryType.MUSIC_MV


def test_mcp_update_world_accepts_story_type():
    fake_manager = Mock()
    fake_manager.get_world_json.return_value = {"id": 1, "name": "测试世界", "user_id": 7}
    fake_manager.save_world.return_value = True

    with patch("script_writer_core.mcp_tool.get_file_manager", return_value=fake_manager):
        result = mcp_tool.update_world("7", "1", "token", story_type=StoryType.NARRATION)

    saved_world = fake_manager.save_world.call_args.args[0]
    assert result["success"] is True
    assert saved_world["story_type"] == StoryType.NARRATION
    assert "story_type" in result["updated_fields"]


def test_script_node_no_longer_exposes_narration_split_toggle():
    script_node = (PROJECT_ROOT / "web" / "js" / "script_node.js").read_text(encoding="utf-8")
    workflow_js = (PROJECT_ROOT / "web" / "js" / "workflow.js").read_text(encoding="utf-8")

    assert "script-narration-as-dialogue" not in script_node
    assert "narration_as_dialogue" not in script_node
    assert "narrationAsDialogue" not in script_node
    assert "script-narration-as-dialogue" not in workflow_js


def test_backend_no_longer_supports_narration_split_mode():
    server_py = (PROJECT_ROOT / "server.py").read_text(encoding="utf-8")
    parser_py = (PROJECT_ROOT / "llm" / "script_parser.py").read_text(encoding="utf-8")

    assert "narration_as_dialogue" not in server_py
    assert "narration_as_dialogue" not in parser_py
    assert "convert_script_to_narration" not in parser_py
    assert "NARRATION_CONVERSION_SYSTEM_PROMPT" not in parser_py


def test_script_writer_world_ui_exposes_story_type_and_defaults_world_json():
    html = (PROJECT_ROOT / "web" / "script_writer.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "web" / "js" / "script_writer.js").read_text(encoding="utf-8")

    assert "world-story-type-view" in html
    assert "world-story-type" in html
    assert "edit-world-story-type" in html
    assert "new-world-story-type" in html
    assert "normalizeStoryType" in js
    assert "data.story_type = normalizeStoryType(data.story_type);" in js
    assert "story_type: normalizeStoryType(document.getElementById('world-story-type').value)" in js
    assert "const storyType = normalizeStoryType(document.getElementById('new-world-story-type').value);" in js
    assert "const storyType = normalizeStoryType(document.getElementById('edit-world-story-type').value);" in js


def test_storyboard_scene_model_module_is_importable():
    import model.storyboard_scene as storyboard_scene

    assert storyboard_scene.StoryboardScene is not None
    assert storyboard_scene.StoryboardSceneModel is not None


def test_file_manager_defaults_legacy_world_json_story_type(tmp_path):
    manager = FileManager(base_dir=str(tmp_path))
    worlds_dir = tmp_path / "files" / "script_writer" / "7" / "1" / "worlds"
    worlds_dir.mkdir(parents=True)
    (worlds_dir / "world_1.json").write_text('{"name": "legacy"}', encoding="utf-8")

    world_data = manager.get_world_json("7", "1")

    assert world_data["story_type"] == StoryType.DIALOGUE
