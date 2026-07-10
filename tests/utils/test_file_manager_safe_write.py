"""
FileManager 实体文件安全写入单元测试

测试 _safe_write_entity_json 及 save_character/save_location/save_prop 的安全写入行为：
- 文件名始终与内容 name 一致（避免幽灵道具）
- 元数据字段（world_id/user_id/created_at/updated_at）保留与补全
- 坏 JSON 拒绝写入；非 JSON 内容原样兼容
- 重命名场景自动清理旧名文件

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

from script_writer_core.file_manager import FileManager


class TestSafeWriteEntityJson(unittest.TestCase):
    """测试 _safe_write_entity_json 安全写入逻辑"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_safe_")
        self.fm = FileManager(base_dir=self.tmp_dir)
        self.user_id = "1"
        self.world_id = "1"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _props_dir(self) -> Path:
        return (Path(self.tmp_dir) / "files" / "script_writer"
                / self.user_id / self.world_id / "props")

    def _read_prop(self, name: str) -> dict:
        fp = self._props_dir() / f"prop_{name}.json"
        return json.loads(fp.read_text(encoding='utf-8'))

    # -------------------- name 一致性 --------------------

    def test_filename_follows_content_name(self):
        """文件名以内容 name 为准：传 prop_name=A、内容 name=B → 生成 prop_B.json"""
        content = json.dumps({"name": "B", "type": "t", "description": "d"}, ensure_ascii=False)
        ok = self.fm.save_prop("A", content, self.user_id, self.world_id)
        self.assertTrue(ok)
        self.assertTrue((self._props_dir() / "prop_B.json").exists())
        # 旧名文件不应被创建
        self.assertFalse((self._props_dir() / "prop_A.json").exists())

    def test_rename_cleans_old_file(self):
        """重命名场景：先建 prop_A.json，再用 name=A+内容name=B 覆盖 → 旧文件 prop_A.json 被清理"""
        # 1. 先建立 A
        content_a = json.dumps({
            "name": "A", "world_id": 1, "user_id": 1,
            "created_at": "2026-01-01T00:00:00", "description": "a"
        }, ensure_ascii=False)
        self.assertTrue(self.fm.save_prop("A", content_a, self.user_id, self.world_id))
        self.assertTrue((self._props_dir() / "prop_A.json").exists())

        # 2. 改名为 B（prop_name 仍是 A，内容 name 改成 B）
        content_b = json.dumps({"name": "B", "description": "b-new"}, ensure_ascii=False)
        self.assertTrue(self.fm.save_prop("A", content_b, self.user_id, self.world_id))

        self.assertTrue((self._props_dir() / "prop_B.json").exists())
        self.assertFalse((self._props_dir() / "prop_A.json").exists(),
                         "重命名后旧名文件应被清理")

    # -------------------- 元数据保留/补全 --------------------

    def test_metadata_preserved_on_partial_overwrite(self):
        """用仅含业务字段的 content 覆盖时，原有元数据应保留、updated_at 刷新、created_at 不变"""
        full = {
            "name": "X", "world_id": 1, "user_id": 9,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-02T00:00:00",
            "type": "t", "description": "d",
        }
        self.fm.save_prop("X", json.dumps(full, ensure_ascii=False), self.user_id, self.world_id)

        # 仅 4 个业务字段（模拟历史上丢失元数据的脏写入场景）
        partial = {"name": "X", "type": "t2", "description": "d2",
                   "reference_image": "http://x/y.png"}
        ok = self.fm.save_prop("X", json.dumps(partial, ensure_ascii=False),
                               self.user_id, self.world_id)
        self.assertTrue(ok)

        data = self._read_prop("X")
        # 业务字段以新内容为准
        self.assertEqual(data["type"], "t2")
        self.assertEqual(data["description"], "d2")
        self.assertEqual(data["reference_image"], "http://x/y.png")
        # 元数据保留
        self.assertEqual(data["world_id"], 1)
        self.assertEqual(data["user_id"], 9)
        self.assertEqual(data["created_at"], "2026-01-01T00:00:00")  # 创建时间不变
        # 更新时间被刷新（不再等于旧值）
        self.assertNotEqual(data["updated_at"], "2026-01-02T00:00:00")
        self.assertTrue(data["updated_at"])  # 且非空

    def test_metadata_backfilled_when_missing(self):
        """全新文件且 content 无任何时间字段时，应补全 created_at/updated_at"""
        partial = {"name": "New", "description": "d"}
        ok = self.fm.save_prop("New", json.dumps(partial, ensure_ascii=False),
                               self.user_id, self.world_id)
        self.assertTrue(ok)
        data = self._read_prop("New")
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)
        self.assertTrue(data["created_at"])
        self.assertTrue(data["updated_at"])

    # -------------------- 坏 JSON 拒绝 / 非 JSON 兼容 --------------------

    def test_reject_malformed_json(self):
        """以 { 开头但解析失败的坏 JSON 应拒绝写入"""
        bad = '{"name": "Y", "type": t}'  # 值缺少引号，非法 JSON
        ok = self.fm.save_prop("Y", bad, self.user_id, self.world_id)
        self.assertFalse(ok)
        self.assertFalse((self._props_dir() / "prop_Y.json").exists())

    def test_non_json_passthrough(self):
        """纯文本（非 JSON）内容应原样写入，文件名沿用 prop_name"""
        text = "这是一段纯文本角色卡描述，不是 JSON"
        ok = self.fm.save_prop("Z", text, self.user_id, self.world_id)
        self.assertTrue(ok)
        fp = self._props_dir() / "prop_Z.json"
        self.assertTrue(fp.exists())
        self.assertEqual(fp.read_text(encoding='utf-8'), text)

    # -------------------- 通用性（character） --------------------

    def test_character_uses_same_safe_write(self):
        """character 同样适用：文件名跟随内容 name"""
        content = json.dumps({"name": "Hero2", "description": "d"}, ensure_ascii=False)
        ok = self.fm.save_character("Hero1", content, self.user_id, self.world_id)
        self.assertTrue(ok)
        chars_dir = (Path(self.tmp_dir) / "files" / "script_writer"
                     / self.user_id / self.world_id / "characters")
        self.assertTrue((chars_dir / "character_Hero2.json").exists())
        self.assertFalse((chars_dir / "character_Hero1.json").exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
