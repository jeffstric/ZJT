"""
角色形象图历史归档单元测试

测试 _archive_character_image_history 及 save_character 的自动归档行为：
- reference_image 被替换时，旧图 unshift 进 image_history（最新在前）
- 旧图为空/新旧一致时不归档
- 历史去重并截断到 CHARACTER_IMAGE_HISTORY_MAX_ENTRIES
- location/prop 不做归档

不依赖数据库，使用临时目录模拟文件系统。
"""
import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path

# 添加项目根目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from config.constant import (
    CHARACTER_IMAGE_HISTORY_FIELD,
    CHARACTER_IMAGE_HISTORY_MAX_ENTRIES,
)
from script_writer_core.file_manager import FileManager
from script_writer_core import mcp_tool as mcp_tool_module
from script_writer_core.mcp_tool import create_character_json


class TestCharacterImageHistory(unittest.TestCase):
    """测试角色形象图历史归档"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_history_")
        self.fm = FileManager(base_dir=self.tmp_dir)
        self.user_id = "1"
        self.world_id = "1"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _chars_dir(self) -> Path:
        return (Path(self.tmp_dir) / "files" / "script_writer"
                / self.user_id / self.world_id / "characters")

    def _read_char(self, name: str) -> dict:
        fp = self._chars_dir() / f"character_{name}.json"
        return json.loads(fp.read_text(encoding='utf-8'))

    def _save_char(self, name: str, data: dict) -> bool:
        return self.fm.save_character(name, json.dumps(data, ensure_ascii=False),
                                      self.user_id, self.world_id)

    def test_replaced_image_archived_to_history(self):
        """替换 reference_image 时旧图进入 image_history 头部"""
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/old.png"})
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/new.png"})
        data = self._read_char("alice")
        self.assertEqual(data["reference_image"], "http://img/new.png")
        self.assertEqual(data.get(CHARACTER_IMAGE_HISTORY_FIELD), ["http://img/old.png"])

    def test_multiple_replacements_keep_newest_first(self):
        """多次替换后历史按最新在前排序"""
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/1.png"})
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/2.png"})
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/3.png"})
        data = self._read_char("alice")
        self.assertEqual(data[CHARACTER_IMAGE_HISTORY_FIELD],
                         ["http://img/2.png", "http://img/1.png"])

    def test_no_archive_when_old_empty(self):
        """旧图为空（首次生成）不归档"""
        self._save_char("alice", {"name": "alice"})
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/first.png"})
        data = self._read_char("alice")
        self.assertIsNone(data.get(CHARACTER_IMAGE_HISTORY_FIELD))

    def test_no_archive_when_same_image(self):
        """新旧图片一致不归档、不产生重复历史"""
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/same.png"})
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/same.png"})
        data = self._read_char("alice")
        self.assertIsNone(data.get(CHARACTER_IMAGE_HISTORY_FIELD))

    def test_history_inherited_when_image_unchanged(self):
        """图片未变时（agent/编辑重建 JSON 不带历史字段），历史从旧文件继承不丢失"""
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/1.png"})
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/2.png"})
        # 第三次保存：图片保持 2.png 不变，但 content 不带 image_history
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/2.png"})
        data = self._read_char("alice")
        self.assertEqual(data["reference_image"], "http://img/2.png")
        self.assertEqual(data.get(CHARACTER_IMAGE_HISTORY_FIELD), ["http://img/1.png"])

    def test_history_dedup_and_cap(self):
        """历史去重并截断到上限"""
        # 构造已有历史接近上限的角色文件
        char = {
            "name": "alice",
            "reference_image": "http://img/a.png",
            CHARACTER_IMAGE_HISTORY_FIELD: [f"http://img/h{i}.png" for i in range(CHARACTER_IMAGE_HISTORY_MAX_ENTRIES)],
        }
        fp = self._chars_dir() / "character_alice.json"
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(char, ensure_ascii=False), encoding='utf-8')

        # 替换新图：旧图 a.png 归档；随后再换回 a.png：a.png 不应重复
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/b.png"})
        data = self._read_char("alice")
        self.assertEqual(data[CHARACTER_IMAGE_HISTORY_FIELD][0], "http://img/a.png")
        self.assertLessEqual(len(data[CHARACTER_IMAGE_HISTORY_FIELD]),
                             CHARACTER_IMAGE_HISTORY_MAX_ENTRIES)
        self.assertNotIn("http://img/b.png", data[CHARACTER_IMAGE_HISTORY_FIELD])

        self._save_char("alice", {"name": "alice", "reference_image": "http://img/a.png"})
        data = self._read_char("alice")
        self.assertEqual(data["reference_image"], "http://img/a.png")
        # b.png 归档进历史且 a.png 不重复
        self.assertEqual(data[CHARACTER_IMAGE_HISTORY_FIELD].count("http://img/a.png"), 0)
        self.assertEqual(data[CHARACTER_IMAGE_HISTORY_FIELD].count("http://img/b.png"), 1)

    def test_clearing_image_archives_old(self):
        """清空图片（新图为空/缺失）：旧图同样归档进历史"""
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/old.png"})
        self._save_char("alice", {"name": "alice"})
        data = self._read_char("alice")
        self.assertEqual(data.get(CHARACTER_IMAGE_HISTORY_FIELD), ["http://img/old.png"])

    def test_history_inherited_after_clear_and_regen(self):
        """删除图片后再生成新图：历史从旧文件继承不丢失"""
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/1.png"})
        self._save_char("alice", {"name": "alice"})  # 删除图片 → 1.png 归档
        self._save_char("alice", {"name": "alice", "reference_image": "http://img/2.png"})
        data = self._read_char("alice")
        self.assertEqual(data["reference_image"], "http://img/2.png")
        self.assertEqual(data.get(CHARACTER_IMAGE_HISTORY_FIELD), ["http://img/1.png"])

    def test_location_not_archived(self):
        """location 替换 reference_image 不产生 image_history"""
        loc = {"name": "L1", "reference_image": "http://img/old.png"}
        self.fm.save_location("L1", json.dumps(loc, ensure_ascii=False),
                              self.user_id, self.world_id)
        loc["reference_image"] = "http://img/new.png"
        self.fm.save_location("L1", json.dumps(loc, ensure_ascii=False),
                              self.user_id, self.world_id)
        loc_dir = (Path(self.tmp_dir) / "files" / "script_writer"
                   / self.user_id / self.world_id / "locations")
        data = json.loads((loc_dir / "location_L1.json").read_text(encoding='utf-8'))
        self.assertIsNone(data.get(CHARACTER_IMAGE_HISTORY_FIELD))


class TestCreateCharacterJsonArchive(unittest.TestCase):
    """MCP 工具 create_character_json（agent 保存角色的真实路径）的归档行为。

    回归背景：该路径走 save_json_content 直接覆盖文件，曾绕过
    _safe_write_entity_json 的归档逻辑，导致「重新生成形象图后历史为空」。
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_mcp_history_")
        self.fm = FileManager(base_dir=self.tmp_dir)
        self._orig_fm = mcp_tool_module._file_manager
        mcp_tool_module.set_file_manager(self.fm)
        self.user_id = "1"
        self.world_id = "1"

    def tearDown(self):
        mcp_tool_module.set_file_manager(self._orig_fm)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _read_char(self, name: str) -> dict:
        fp = (Path(self.tmp_dir) / "files" / "script_writer"
              / self.user_id / self.world_id / "characters" / f"character_{name}.json")
        return json.loads(fp.read_text(encoding='utf-8'))

    def test_regen_via_mcp_tool_archives_old_image(self):
        """agent 经 create_character_json 重新保存角色（新图替换旧图）：旧图进入历史"""
        r1 = create_character_json(self.user_id, self.world_id, "token",
                                   "alice", appearance="a", reference_image="http://img/old.png",
                                   _skip_image_validation=True)
        self.assertTrue(r1['success'])
        r2 = create_character_json(self.user_id, self.world_id, "token",
                                   "alice", appearance="a", reference_image="http://img/new.png",
                                   _skip_image_validation=True)
        self.assertTrue(r2['success'])
        data = self._read_char("alice")
        self.assertEqual(data["reference_image"], "http://img/new.png")
        self.assertEqual(data.get(CHARACTER_IMAGE_HISTORY_FIELD), ["http://img/old.png"])

    def test_mcp_tool_inherits_history_when_image_unchanged(self):
        """agent 重建 JSON（不带历史字段）且图片未变：历史继承不丢失"""
        create_character_json(self.user_id, self.world_id, "token",
                              "alice", reference_image="http://img/1.png",
                              _skip_image_validation=True)
        create_character_json(self.user_id, self.world_id, "token",
                              "alice", reference_image="http://img/2.png",
                              _skip_image_validation=True)
        # 第三次：图片不变，content 不带 image_history
        create_character_json(self.user_id, self.world_id, "token",
                              "alice", reference_image="http://img/2.png",
                              _skip_image_validation=True)
        data = self._read_char("alice")
        self.assertEqual(data.get(CHARACTER_IMAGE_HISTORY_FIELD), ["http://img/1.png"])

    def test_mcp_tool_delete_image_archives(self):
        """agent 经 create_character_json 保存不含 reference_image 的角色（删除图片）：旧图归档"""
        create_character_json(self.user_id, self.world_id, "token",
                              "alice", reference_image="http://img/old.png",
                              _skip_image_validation=True)
        create_character_json(self.user_id, self.world_id, "token",
                              "alice", appearance="a",
                              _skip_image_validation=True)
        data = self._read_char("alice")
        self.assertIsNone(data.get("reference_image"))
        self.assertEqual(data.get(CHARACTER_IMAGE_HISTORY_FIELD), ["http://img/old.png"])


class TestUpdateCharacterJsonArchive(unittest.TestCase):
    """MCP 工具 update_character_json（生图任务完成回调 cron_task_manager 的真实写入
    路径，也是 agent 可直接调用的工具）的归档行为。

    回归背景：该函数直接 open/json.dump 写回文件，曾绕过所有归档逻辑——
    「重新生成形象图后历史始终为空」的 s0 根因。
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_upd_history_")
        self.fm = FileManager(base_dir=self.tmp_dir)
        self._orig_fm = mcp_tool_module._file_manager
        mcp_tool_module.set_file_manager(self.fm)
        self.user_id = "1"
        self.world_id = "1"
        # 先用 create_character_json 建角色（跳过 URL 校验，便于测试任意值）
        create_character_json(self.user_id, self.world_id, "token",
                              "alice", appearance="a",
                              reference_image="http://img/old.png",
                              _skip_image_validation=True)

    def tearDown(self):
        mcp_tool_module.set_file_manager(self._orig_fm)
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _read_char(self) -> dict:
        fp = (Path(self.tmp_dir) / "files" / "script_writer"
              / self.user_id / self.world_id / "characters" / "character_alice.json")
        return json.loads(fp.read_text(encoding='utf-8'))

    def test_image_regen_callback_archives_old(self):
        """生图完成回调场景：update_character_json 替换主图 → 旧图进历史"""
        result = mcp_tool_module.update_character_json(
            self.user_id, self.world_id, "token", "alice",
            reference_image="http://img/new.png")
        self.assertTrue(result['success'])
        data = self._read_char()
        self.assertEqual(data["reference_image"], "http://img/new.png")
        self.assertEqual(data.get(CHARACTER_IMAGE_HISTORY_FIELD), ["http://img/old.png"])

    def test_repeated_regen_keeps_full_history(self):
        """连续两次重生成：历史按最新在前累计"""
        mcp_tool_module.update_character_json(self.user_id, self.world_id, "token",
                                              "alice", reference_image="http://img/2.png")
        mcp_tool_module.update_character_json(self.user_id, self.world_id, "token",
                                              "alice", reference_image="http://img/3.png")
        data = self._read_char()
        self.assertEqual(data["reference_image"], "http://img/3.png")
        self.assertEqual(data.get(CHARACTER_IMAGE_HISTORY_FIELD),
                         ["http://img/2.png", "http://img/old.png"])


if __name__ == "__main__":
    unittest.main()
