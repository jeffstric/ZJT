"""
世界导入 Zip Slip 防护单元测试

覆盖 FileManager.import_world 的三处 zip 解包通道（图片/音频/JSON）的
路径穿越防护、user_id/world_id 注入拦截、zip 炸弹（解压总量/单 entry 上限），
以及正常导入不受影响的回归验证。
不依赖数据库，使用临时目录模拟文件系统。
"""
import os
import sys
import json
import shutil
import tempfile
import zipfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 添加项目根目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

import script_writer_core.file_manager as fm_module
from script_writer_core.file_manager import FileManager


class TestIsSafePathComponent(unittest.TestCase):
    """测试 _is_safe_path_component：user_id / world_id 注入拦截"""

    def test_normal_ids_pass(self):
        """正常的 ID 格式应放行"""
        for value in ("1", "user_1", "test-world", "abc123", "16"):
            self.assertTrue(FileManager._is_safe_path_component(value), value)

    def test_traversal_ids_rejected(self):
        """含目录分隔符或父目录引用的 ID 应拒绝"""
        for value in ("..", "../x", "a/b", "a\\b", ".", "C:", "C:\\evil", "/abs", "a/b/c"):
            self.assertFalse(FileManager._is_safe_path_component(value), value)

    def test_empty_and_dot_rejected(self):
        self.assertFalse(FileManager._is_safe_path_component(""))
        self.assertFalse(FileManager._is_safe_path_component("."))
        self.assertFalse(FileManager._is_safe_path_component(".."))


class TestSafeZipEntryFile(unittest.TestCase):
    """测试 _safe_zip_entry_file：zip entry 文件名校验"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_zipslip_helper_")
        self.dest_dir = Path(self.tmp_dir) / "dest"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_normal_filename_returns_path(self):
        result = FileManager._safe_zip_entry_file(self.dest_dir, "img.png")
        self.assertEqual(result, self.dest_dir / "img.png")

    def test_nested_relative_filename_allowed(self):
        """允许目录内的相对子路径（不含 ..）"""
        result = FileManager._safe_zip_entry_file(self.dest_dir, "sub/img.png")
        self.assertEqual(result, self.dest_dir / "sub" / "img.png")

    def test_dotdot_rejected(self):
        for name in ("../../x.html", "a/../b.png", ".."):
            self.assertIsNone(FileManager._safe_zip_entry_file(self.dest_dir, name), name)

    def test_absolute_path_rejected(self):
        self.assertIsNone(FileManager._safe_zip_entry_file(self.dest_dir, "/etc/passwd"))

    def test_backslash_rejected(self):
        """zip 规范分隔符为 /，反斜杠一律拒绝（Windows 下的穿越变体）"""
        self.assertIsNone(FileManager._safe_zip_entry_file(self.dest_dir, "..\\x.html"))
        self.assertIsNone(FileManager._safe_zip_entry_file(self.dest_dir, "a\\b.png"))

    def test_windows_drive_prefix_rejected(self):
        """Windows 盘符前缀（PurePosixPath 不认为是绝对路径）"""
        self.assertIsNone(FileManager._safe_zip_entry_file(self.dest_dir, "C:/evil.png"))

    def test_dir_name_and_empty_rejected(self):
        self.assertIsNone(FileManager._safe_zip_entry_file(self.dest_dir, "sub/"))
        self.assertIsNone(FileManager._safe_zip_entry_file(self.dest_dir, ""))


class TestImportWorldZipSlip(unittest.TestCase):
    """端到端：恶意 zip 三条解包通道均不可逃逸目标目录"""

    def setUp(self):
        # 沙箱结构：sandbox/proj 为项目根，sandbox 根用于检测越界落盘
        self.sandbox = Path(tempfile.mkdtemp(prefix="test_fm_zipslip_e2e_"))
        self.proj = self.sandbox / "proj"
        self.proj.mkdir()
        self.fm = FileManager(base_dir=str(self.proj))
        self.user_id = "u1"
        self.world_id = "w1"

    def tearDown(self):
        shutil.rmtree(self.sandbox, ignore_errors=True)

    def _build_zip(self, entries, mappings=None):
        """entries: {entry_name: content}；mappings: 额外写入的 mapping json 内容"""
        zip_path = self.sandbox / "evil.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for name, content in entries.items():
                zf.writestr(name, content)
            for mapping_name, mapping_data in (mappings or {}).items():
                zf.writestr(mapping_name, json.dumps(mapping_data, ensure_ascii=False))
        return str(zip_path)

    def _assert_no_escape(self):
        """断言没有任何文件逃逸出项目根（落在沙箱根、proj 之外）"""
        escaped = [p.name for p in self.sandbox.iterdir()
                   if p.name not in ("proj", "evil.zip")]
        self.assertEqual(escaped, [], f"发现越界落盘文件: {escaped}")

    def test_image_traversal_blocked(self):
        """通道1：images/../../x.html 不得写入 upload 根（StaticFiles 直出范围）"""
        zip_path = self._build_zip(
            entries={"images/../../poc_xss.html": "<script>alert(1)</script>"},
            mappings={"image_mapping.json": {
                "../../poc_xss.html": "/upload/character/pic/poc_xss.html"
            }},
        )
        result = self.fm.import_world(self.user_id, self.world_id, zip_path)

        self.assertEqual(result["images"], 0)
        self.assertTrue(any("非法文件路径" in e for e in result["errors"]))
        self.assertFalse((self.proj / "upload" / "poc_xss.html").exists())
        self._assert_no_escape()

    def test_audio_traversal_blocked(self):
        """通道2：audios/../../evil.wav 不得逃逸项目根"""
        zip_path = self._build_zip(
            entries={"audios/../../../../poc_escape.wav": b"RIFF"},
            mappings={"audio_mapping.json": {
                "../../../../poc_escape.wav": "/upload/character/voice/poc_voice.wav"
            }},
        )
        result = self.fm.import_world(self.user_id, self.world_id, zip_path)

        self.assertEqual(result["audios"], 0)
        self.assertTrue(any("非法文件路径" in e for e in result["errors"]))
        self._assert_no_escape()

    def test_json_traversal_sanitized(self):
        """通道3：scripts/../.. 形式的 JSON entry 被 basename 截断收敛到白名单子目录内"""
        zip_path = self._build_zip(
            entries={"scripts/../../../../../../poc_escape.json": json.dumps({"poc": True})},
        )
        result = self.fm.import_world(self.user_id, self.world_id, zip_path)

        # 收敛写入 scripts/poc_escape.json，未逃逸
        self.assertEqual(result["scripts"], 1)
        base_path = self.fm._get_user_world_path(self.user_id, self.world_id)
        self.assertTrue((base_path / "scripts" / "poc_escape.json").exists())
        self._assert_no_escape()

    def test_json_backslash_traversal_sanitized(self):
        """通道3变体：反斜杠分隔的 entry 文件名被收敛，不逃逸（Windows 穿越变体）"""
        zip_path = self._build_zip(
            entries={"scripts/..\\..\\evil.json": json.dumps({"poc": True})},
        )
        result = self.fm.import_world(self.user_id, self.world_id, zip_path)

        self.assertEqual(result["scripts"], 1)
        base_path = self.fm._get_user_world_path(self.user_id, self.world_id)
        self.assertTrue((base_path / "scripts" / "evil.json").exists())
        self._assert_no_escape()

    def test_json_dotdot_sanitized_into_whitelist_subdir(self):
        """JSON 通道 basename 截断：越界文件名收敛到白名单子目录内，而非逃逸"""
        zip_path = self._build_zip(
            entries={"characters/../evil.json": json.dumps({"evil": True})},
        )
        result = self.fm.import_world(self.user_id, self.world_id, zip_path)

        # 内容被收敛写入 characters/evil.json，未逃逸
        self.assertEqual(result["characters"], 1)
        base_path = self.fm._get_user_world_path(self.user_id, self.world_id)
        self.assertTrue((base_path / "characters" / "evil.json").exists())
        self._assert_no_escape()

    def test_unsafe_user_id_rejected(self):
        """user_id 携带路径分量时整个导入被拒绝，且不创建任何目录"""
        zip_path = self._build_zip(entries={"characters/a.json": json.dumps({"name": "a"})})

        result = self.fm.import_world("../../evil_user", self.world_id, zip_path)

        self.assertEqual(result["characters"], 0)
        self.assertTrue(any("非法的 user_id/world_id" in e for e in result["errors"]))
        self.assertFalse((self.sandbox / "files" / "script_writer").exists())
        self._assert_no_escape()

    def test_unsafe_world_id_rejected(self):
        """world_id 携带路径分量时整个导入被拒绝"""
        zip_path = self._build_zip(entries={"characters/a.json": json.dumps({"name": "a"})})

        result = self.fm.import_world(self.user_id, "..\\..\\evil_world", zip_path)

        self.assertEqual(result["characters"], 0)
        self.assertTrue(any("非法的 user_id/world_id" in e for e in result["errors"]))
        self._assert_no_escape()


class TestImportWorldZipBomb(unittest.TestCase):
    """zip 炸弹防护：解压总量与单 entry 上限"""

    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="test_fm_zipslip_bomb_"))
        self.proj = self.sandbox / "proj"
        self.proj.mkdir()
        self.fm = FileManager(base_dir=str(self.proj))

    def tearDown(self):
        shutil.rmtree(self.sandbox, ignore_errors=True)

    def test_total_uncompressed_over_limit_rejected(self):
        """解压总量超上限：拒绝导入且不落盘任何文件"""
        zip_path = self.sandbox / "bomb.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 压缩后体积很小（重复字节），未压缩 2 MB
            zf.writestr("characters/big.json", json.dumps({"data": "A" * (2 * 1024 * 1024)}))

        with patch.object(fm_module, "WORLD_IMPORT_MAX_TOTAL_UNCOMPRESSED_BYTES", 1024 * 1024):
            result = self.fm.import_world("u1", "w1", str(zip_path))

        self.assertEqual(result["characters"], 0)
        self.assertTrue(any("超过上限" in e for e in result["errors"]))
        base_path = self.fm._get_user_world_path("u1", "w1")
        self.assertFalse((base_path / "characters" / "big.json").exists())

    def test_single_entry_over_limit_rejected(self):
        """单 entry 超上限：拒绝导入"""
        zip_path = self.sandbox / "bomb_entry.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("images/big.png", b"\x00" * (2 * 1024 * 1024))
            zf.writestr("image_mapping.json", json.dumps({
                "big.png": "/upload/character/pic/big.png"
            }))

        with patch.object(fm_module, "WORLD_IMPORT_MAX_ENTRY_UNCOMPRESSED_BYTES", 1024 * 1024):
            result = self.fm.import_world("u1", "w1", str(zip_path))

        self.assertEqual(result["images"], 0)
        self.assertTrue(any("单文件上限" in e for e in result["errors"]))
        self.assertFalse((self.proj / "upload" / "character" / "pic" / "big.png").exists())


class TestImportWorldLegitImportStillWorks(unittest.TestCase):
    """回归：正常导出 zip 导入行为不受安全校验影响"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_zipslip_reg_")
        self.fm = FileManager(base_dir=self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_legit_import(self):
        zip_path = os.path.join(self.tmp_dir, "legit.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("image_mapping.json", json.dumps({"img.png": "/upload/character/pic/img.png"}))
            zf.writestr("audio_mapping.json", json.dumps({"v.wav": "/upload/character/voice/v.wav"}))
            zf.writestr("images/img.png", b"\x89PNG")
            zf.writestr("audios/v.wav", b"RIFF")
            zf.writestr("characters/角色A.json", json.dumps({
                "name": "角色A",
                "reference_image": "images/img.png",
                "default_voice": "audios/v.wav",
            }, ensure_ascii=False))
            zf.writestr("worlds/world_6.json", json.dumps({"name": "世界"}))
            zf.writestr("script_problem.json", json.dumps({"verdict": True, "problem": ""}))

        result = self.fm.import_world("user_1", "1", zip_path)

        self.assertEqual(result["errors"], [], f"正常导入不应有错误: {result['errors']}")
        self.assertEqual(result["images"], 1)
        self.assertEqual(result["audios"], 1)
        self.assertEqual(result["characters"], 1)
        self.assertEqual(result["worlds"], 1)

        # 图片/音频落盘位置正确
        self.assertTrue((Path(self.tmp_dir) / "upload" / "character" / "pic" / "img.png").exists())
        self.assertTrue((Path(self.tmp_dir) / "upload" / "character" / "voice" / "v.wav").exists())

        base_path = self.fm._get_user_world_path("user_1", "1")
        self.assertTrue((base_path / "worlds" / "world_1.json").exists())
        with open(base_path / "characters" / "角色A.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["reference_image"], "/upload/character/pic/img.png")
            self.assertEqual(data["default_voice"], "/upload/character/voice/v.wav")

    def test_unicode_and_space_filenames_allowed(self):
        """含中文、空格的正常文件名不受校验误伤"""
        zip_path = os.path.join(self.tmp_dir, "unicode.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("image_mapping.json", json.dumps({
                "角色 图.png": "/upload/character/pic/角色 图.png"
            }))
            zf.writestr("images/角色 图.png", b"\x89PNG")

        result = self.fm.import_world("user_1", "1", zip_path)

        self.assertEqual(result["images"], 1)
        self.assertTrue(
            (Path(self.tmp_dir) / "upload" / "character" / "pic" / "角色 图.png").exists()
        )


if __name__ == "__main__":
    unittest.main()
