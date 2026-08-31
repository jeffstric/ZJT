"""delete_asset_reference_image MCP 工具单元测试。

用临时目录构造角色/场景/道具 JSON，验证：
- 参数校验（asset_type / name）
- 资产不存在时的错误返回
- reference_image 本来为空时 already_empty
- 正常删除：置空、质检日志留痕（带 reason）；无 reason 不写日志
- JSON 写回保持原字段
"""
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from script_writer_core import mcp_tool
from script_writer_core.mcp_tool import delete_asset_reference_image


class _FakeFileManager:
    """只实现 delete_asset_reference_image 用到的两个方法。"""

    def __init__(self, base_dir):
        self._base = Path(base_dir)

    def resolve_character_file_path(self, name, user_id, world_id):
        return self._base / "characters" / f"character_{name}.json"

    def get_content_file_path(self, user_id, world_id, folder, filename):
        return str(self._base / folder / filename)


class DeleteAssetReferenceImageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        for folder in ("characters", "locations", "props"):
            (self.base / folder).mkdir(parents=True, exist_ok=True)

        self._original_fm = mcp_tool._file_manager
        mcp_tool.set_file_manager(_FakeFileManager(self.base))
        self.addCleanup(lambda: mcp_tool.set_file_manager(self._original_fm))

    def _write_json(self, folder, filename, payload):
        path = self.base / folder / filename
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    # ---------- 参数校验 ----------

    def test_empty_name_rejected(self):
        for bad in ("", None, 123):
            result = delete_asset_reference_image("1", "101", "t", "character", bad)
            self.assertFalse(result["success"])
            self.assertIn("资产名称", result["error"])

    def test_invalid_asset_type_rejected(self):
        result = delete_asset_reference_image("1", "101", "t", "scene", "alice")
        self.assertFalse(result["success"])
        self.assertIn("asset_type", result["error"])

    def test_asset_type_is_case_insensitive(self):
        result = delete_asset_reference_image("1", "101", "t", "  CHARACTER ", "")
        # 类型合法后因名称为空失败，而不是 asset_type 错误
        self.assertFalse(result["success"])
        self.assertNotIn("asset_type", result["error"])

    # ---------- 资产不存在 ----------

    def test_missing_character_returns_error(self):
        result = delete_asset_reference_image("1", "101", "t", "character", "alice")
        self.assertFalse(result["success"])
        self.assertIn("不存在", result["error"])

    def test_missing_location_returns_error(self):
        result = delete_asset_reference_image("1", "101", "t", "location", "森林")
        self.assertFalse(result["success"])
        self.assertIn("不存在", result["error"])

    def test_missing_prop_returns_error(self):
        result = delete_asset_reference_image("1", "101", "t", "prop", "宝剑")
        self.assertFalse(result["success"])
        self.assertIn("不存在", result["error"])

    # ---------- already empty ----------

    def test_already_empty_reference_image(self):
        path = self._write_json("locations", "location_森林.json", {
            "name": "森林", "reference_image": "",
        })
        result = delete_asset_reference_image("1", "101", "t", "location", "森林")
        self.assertTrue(result["success"])
        self.assertTrue(result["already_empty"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["reference_image"], "")

    # ---------- 正常删除 ----------

    def test_delete_character_reference_image_with_reason(self):
        path = self._write_json("characters", "character_alice.json", {
            "name": "alice", "reference_image": "http://cdn/alice.png", "age": 18,
        })
        result = delete_asset_reference_image(
            "1", "101", "t", "character", "alice",
            reason="宫格切分污染-图中出现两个角色",
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["deleted_image_url"], "http://cdn/alice.png")

        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["reference_image"], "")
        self.assertEqual(data["age"], 18)  # 原字段保留
        log = data["reference_image_quality_log"]
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["action"], "delete_reference_image")
        self.assertEqual(log[0]["reason"], "宫格切分污染-图中出现两个角色")
        self.assertEqual(log[0]["deleted_image_url"], "http://cdn/alice.png")
        self.assertIn("deleted_at", log[0])

    def test_delete_prop_without_reason_skips_quality_log(self):
        path = self._write_json("props", "prop_宝剑.json", {
            "name": "宝剑", "reference_image": "http://cdn/sword.png",
        })
        result = delete_asset_reference_image("1", "101", "t", "prop", "宝剑")
        self.assertTrue(result["success"])
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["reference_image"], "")
        self.assertNotIn("reference_image_quality_log", data)

    def test_repeated_delete_appends_to_quality_log(self):
        self._write_json("characters", "character_alice.json", {
            "name": "alice", "reference_image": "http://cdn/alice.png",
            "reference_image_quality_log": [
                {"action": "delete_reference_image", "reason": "old", "deleted_at": "2026-08-01"},
            ],
        })
        delete_asset_reference_image("1", "101", "t", "character", "alice", reason="again")
        data = json.loads(
            (self.base / "characters" / "character_alice.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(data["reference_image_quality_log"]), 2)

    def test_location_filename_is_sanitized(self):
        # 名称带空格/非法字符时按 _sanitize_filename 规则定位文件
        self._write_json("locations", "location_魔法_森林.json", {
            "name": "魔法 森林", "reference_image": "http://cdn/forest.png",
        })
        result = delete_asset_reference_image("1", "101", "t", "location", "魔法 森林")
        self.assertTrue(result["success"])
        data = json.loads(
            (self.base / "locations" / "location_魔法_森林.json").read_text(encoding="utf-8")
        )
        self.assertEqual(data["reference_image"], "")


if __name__ == "__main__":
    unittest.main()
