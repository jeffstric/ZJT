from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model import storyboard as storyboard_model



def test_storyboard_scene_code_lives_in_dedicated_module():
    storyboard_py = (PROJECT_ROOT / "model" / "storyboard.py").read_text(encoding="utf-8")
    storyboard_scene_py = (PROJECT_ROOT / "model" / "storyboard_scene.py").read_text(encoding="utf-8")

    assert "class StoryboardScene:" not in storyboard_py
    assert "class StoryboardSceneModel:" not in storyboard_py
    assert "class StoryboardScene:" in storyboard_scene_py
    assert "class StoryboardSceneModel:" in storyboard_scene_py
    assert storyboard_model.StoryboardSceneModel is not None


def test_storyboard_related_tables_live_in_dedicated_modules():
    storyboard_py = (PROJECT_ROOT / "model" / "storyboard.py").read_text(encoding="utf-8")
    dialogue_py = (PROJECT_ROOT / "model" / "storyboard_dialogue.py").read_text(encoding="utf-8")
    audio_py = (PROJECT_ROOT / "model" / "storyboard_dialogue_audio.py").read_text(encoding="utf-8")
    asset_py = (PROJECT_ROOT / "model" / "storyboard_scene_asset.py").read_text(encoding="utf-8")

    for class_name in [
        "StoryboardDialogue",
        "StoryboardDialogueModel",
        "StoryboardDialogueAudio",
        "StoryboardDialogueAudioModel",
        "StoryboardSceneAsset",
        "StoryboardSceneAssetModel",
    ]:
        assert f"class {class_name}" not in storyboard_py

    assert "class StoryboardDialogue:" in dialogue_py
    assert "class StoryboardDialogueModel:" in dialogue_py
    assert "class StoryboardDialogueAudio:" in audio_py
    assert "class StoryboardDialogueAudioModel:" in audio_py
    assert "class StoryboardSceneAsset:" in asset_py
    assert "class StoryboardSceneAssetModel:" in asset_py

    assert storyboard_model.StoryboardDialogueModel is not None
    assert storyboard_model.StoryboardDialogueAudioModel is not None
    assert storyboard_model.StoryboardSceneAssetModel is not None


def test_storyboard_exposes_version_in_model_sql_and_migration():
    storyboard = storyboard_model.Storyboard(id=1)

    assert storyboard.version == 1
    assert storyboard.to_dict()["version"] == 1
    assert "`version` INT NOT NULL DEFAULT 1" in storyboard_model.CREATE_TABLE_SQL

    migration = PROJECT_ROOT / "alembic" / "versions" / "no_106_20260701_add_storyboard_version.py"
    assert migration.exists()
    migration_text = migration.read_text(encoding="utf-8")
    assert "ADD COLUMN `version` INT NOT NULL DEFAULT 1" in migration_text
