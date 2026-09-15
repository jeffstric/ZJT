"""旁白解说剧自动补建"旁白"角色卡的单元测试。

覆盖 ensure_narrator_character 硬保证逻辑，以及 read_world /
list_character_jsons 两个触发挂载点的行为。
"""
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constant import StoryType
from script_writer_core import mcp_tool


def _make_manager(world_data):
    fake_manager = Mock()
    fake_manager.get_world_json.return_value = world_data
    return fake_manager


def test_ensure_narrator_creates_missing_narrator():
    fake_manager = _make_manager({"name": "测试世界", "story_type": StoryType.NARRATION})
    fake_manager.resolve_character_file_path.return_value = None

    with patch("script_writer_core.mcp_tool.get_file_manager", return_value=fake_manager), \
         patch("script_writer_core.mcp_tool.create_character_json", return_value={"success": True}) as create_char:
        result = mcp_tool.ensure_narrator_character("7", "1", "token")

    assert result["triggered"] is True
    assert result["created"] is True
    create_char.assert_called_once()
    kwargs = create_char.call_args.kwargs
    assert kwargs["name"] == mcp_tool.NARRATOR_CHARACTER_NAME
    assert kwargs["identity"]
    assert kwargs["personality"]
    assert kwargs["behavior"]


def test_ensure_narrator_skips_when_already_exists():
    fake_manager = _make_manager({"name": "测试世界", "story_type": StoryType.NARRATION})
    fake_manager.resolve_character_file_path.return_value = Path("/tmp/character_旁白.json")

    with patch("script_writer_core.mcp_tool.get_file_manager", return_value=fake_manager), \
         patch("script_writer_core.mcp_tool.create_character_json") as create_char:
        result = mcp_tool.ensure_narrator_character("7", "1", "token")

    assert result["triggered"] is True
    assert result["created"] is False
    create_char.assert_not_called()


def test_ensure_narrator_skips_dialogue_world():
    fake_manager = _make_manager({"name": "测试世界", "story_type": StoryType.DIALOGUE})

    with patch("script_writer_core.mcp_tool.get_file_manager", return_value=fake_manager), \
         patch("script_writer_core.mcp_tool.create_character_json") as create_char:
        result = mcp_tool.ensure_narrator_character("7", "1", "token")

    assert result["triggered"] is False
    assert result["created"] is False
    create_char.assert_not_called()


def test_ensure_narrator_handles_missing_world():
    fake_manager = _make_manager(None)

    with patch("script_writer_core.mcp_tool.get_file_manager", return_value=fake_manager):
        result = mcp_tool.ensure_narrator_character("7", "1", "token")

    assert result["triggered"] is False
    assert result["created"] is False


def test_ensure_narrator_swallows_internal_exception():
    fake_manager = Mock()
    fake_manager.get_world_json.side_effect = RuntimeError("磁盘故障")

    with patch("script_writer_core.mcp_tool.get_file_manager", return_value=fake_manager):
        result = mcp_tool.ensure_narrator_character("7", "1", "token")

    assert result["triggered"] is False
    assert result["created"] is False
    assert "异常" in result["reason"]


def test_read_world_triggers_ensure_for_narration():
    fake_manager = _make_manager({"name": "测试世界", "story_type": StoryType.NARRATION})

    with patch("script_writer_core.mcp_tool.get_file_manager", return_value=fake_manager), \
         patch("script_writer_core.mcp_tool.ensure_narrator_character") as ensure:
        result = mcp_tool.read_world("7", "1", "token")

    assert result["success"] is True
    assert result["story_type"] == StoryType.NARRATION
    ensure.assert_called_once_with("7", "1", "token")


def test_read_world_skips_ensure_for_dialogue():
    fake_manager = _make_manager({"name": "测试世界", "story_type": StoryType.DIALOGUE})

    with patch("script_writer_core.mcp_tool.get_file_manager", return_value=fake_manager), \
         patch("script_writer_core.mcp_tool.ensure_narrator_character") as ensure:
        result = mcp_tool.read_world("7", "1", "token")

    assert result["success"] is True
    ensure.assert_not_called()


def test_read_world_survives_ensure_failure():
    fake_manager = _make_manager({"name": "测试世界", "story_type": StoryType.NARRATION})

    with patch("script_writer_core.mcp_tool.get_file_manager", return_value=fake_manager), \
         patch("script_writer_core.mcp_tool.ensure_narrator_character", side_effect=RuntimeError("boom")):
        result = mcp_tool.read_world("7", "1", "token")

    assert result["success"] is True


def test_list_character_jsons_triggers_ensure_before_listing():
    # 不用 pytest tmp_path 工厂（部分 Windows 环境基目录拒绝访问），自建临时目录
    tmp_dir = Path(tempfile.mkdtemp(prefix="narrator_test_"))
    try:
        characters_dir = tmp_dir / "characters"
        characters_dir.mkdir()
        (characters_dir / "character_主角.json").write_text(
            '{"name": "主角"}', encoding="utf-8"
        )

        fake_manager = Mock()
        fake_manager.get_content_dir_path.return_value = str(characters_dir)

        with patch("script_writer_core.mcp_tool.get_file_manager", return_value=fake_manager), \
             patch("script_writer_core.mcp_tool.ensure_narrator_character") as ensure:
            result = mcp_tool.list_character_jsons("7", "1", "token")

        assert result["success"] is True
        ensure.assert_called_once_with("7", "1", "token")
        # ensure 在列目录之前执行，后续创建的旁白文件必然纳入本次列表
        assert result["data"] == ["character_主角.json"]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
