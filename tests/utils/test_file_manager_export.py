"""
文件管理器导出/导入功能单元测试

测试 FileManager 新增的 export_world / import_world 及相关辅助方法。
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
from unittest.mock import patch, MagicMock

# 添加项目根目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from script_writer_core.file_manager import FileManager


class TestCollectImageFromUrl(unittest.TestCase):
    """测试 _collect_image_from_url 方法"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_collect_")
        self.fm = FileManager(base_dir=self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_upload_file(self, image_type: str, filename: str) -> Path:
        """在 upload 目录创建一个假图片文件"""
        file_path = Path(self.tmp_dir) / "upload" / image_type / "pic" / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b'\x89PNG\r\n\x1a\n')  # PNG magic bytes
        return file_path

    def test_valid_character_url(self):
        """测试解析角色图片 URL"""
        self._create_upload_file("character", "abc-123.png")
        url = "http://localhost:9003/upload/character/pic/abc-123.png"
        result = self.fm._collect_image_from_url(url)
        self.assertIsNotNone(result)
        image_type, filename, file_path = result
        self.assertEqual(image_type, "character")
        self.assertEqual(filename, "abc-123.png")
        self.assertTrue(file_path.exists())

    def test_valid_location_url(self):
        """测试解析场景图片 URL"""
        self._create_upload_file("location", "loc-456.jpg")
        url = "http://example.com/upload/location/pic/loc-456.jpg"
        result = self.fm._collect_image_from_url(url)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "location")
        self.assertEqual(result[1], "loc-456.jpg")

    def test_valid_props_url(self):
        """测试解析道具图片 URL"""
        self._create_upload_file("props", "prop-789.webp")
        url = "https://cdn.example.com/upload/props/pic/prop-789.webp"
        result = self.fm._collect_image_from_url(url)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "props")
        self.assertEqual(result[1], "prop-789.webp")

    def test_file_not_exists(self):
        """测试文件不存在时返回 None"""
        url = "http://localhost:9003/upload/character/pic/nonexistent.png"
        result = self.fm._collect_image_from_url(url)
        self.assertIsNone(result)

    def test_invalid_url_no_match(self):
        """测试不匹配的 URL 返回 None"""
        result = self.fm._collect_image_from_url("http://example.com/other/path.png")
        self.assertIsNone(result)

    def test_empty_url(self):
        """测试空 URL 返回 None"""
        self.assertIsNone(self.fm._collect_image_from_url(""))
        self.assertIsNone(self.fm._collect_image_from_url(None))

    def test_url_with_query_params(self):
        """测试带查询参数的 URL（文件名包含查询参数，文件不存在返回 None）"""
        # 当前正则会将查询参数作为 filename 的一部分
        # 文件系统上不存在 "test.png?width=100"，所以返回 None
        self._create_upload_file("character", "test.png")
        url = "http://localhost:9003/upload/character/pic/test.png?width=100"
        result = self.fm._collect_image_from_url(url)
        # 文件名包含查询参数，实际文件不存在
        self.assertIsNone(result)


class TestRewriteImageUrls(unittest.TestCase):
    """测试 _rewrite_image_urls 方法"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_rewrite_")
        self.fm = FileManager(base_dir=self.tmp_dir)
        self.image_mapping = {}
        self.collected = set()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_upload_file(self, image_type: str, filename: str) -> Path:
        file_path = Path(self.tmp_dir) / "upload" / image_type / "pic" / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b'\x89PNG\r\n\x1a\n')
        return file_path

    def test_rewrite_single_reference_image(self):
        """测试替换单张 reference_image（无 zipf 时 collected 不更新）"""
        self._create_upload_file("character", "char-001.png")
        data = {
            "name": "角色A",
            "reference_image": "http://localhost:9003/upload/character/pic/char-001.png"
        }
        result = self.fm._rewrite_image_urls(data, self.image_mapping, self.collected)
        self.assertEqual(result["reference_image"], "images/char-001.png")
        # collected 只在 zipf 存在时更新
        self.assertEqual(len(self.collected), 0)
        self.assertIn("char-001.png", self.image_mapping)

    def test_rewrite_reference_images_list(self):
        """测试替换多角度参考图列表"""
        self._create_upload_file("location", "loc-001.png")
        self._create_upload_file("location", "loc-002.png")
        data = {
            "name": "场景A",
            "reference_images": [
                {"url": "http://localhost:9003/upload/location/pic/loc-001.png", "angle": "front"},
                {"url": "http://localhost:9003/upload/location/pic/loc-002.png", "angle": "side"},
            ]
        }
        result = self.fm._rewrite_image_urls(data, self.image_mapping, self.collected)
        self.assertEqual(result["reference_images"][0]["url"], "images/loc-001.png")
        self.assertEqual(result["reference_images"][1]["url"], "images/loc-002.png")
        self.assertEqual(result["reference_images"][0]["angle"], "front")
        # collected 只在 zipf 存在时更新
        self.assertEqual(len(self.collected), 0)
        self.assertEqual(len(self.image_mapping), 2)

    def test_no_image_fields(self):
        """测试没有图片字段的数据"""
        data = {"name": "测试", "description": "无图片"}
        result = self.fm._rewrite_image_urls(data, self.image_mapping, self.collected)
        self.assertEqual(result, data)
        self.assertEqual(len(self.collected), 0)

    def test_nested_dict(self):
        """测试嵌套字典"""
        self._create_upload_file("props", "prop-001.png")
        data = {
            "character": {
                "name": "角色",
                "reference_image": "http://localhost:9003/upload/props/pic/prop-001.png"
            }
        }
        result = self.fm._rewrite_image_urls(data, self.image_mapping, self.collected)
        self.assertEqual(result["character"]["reference_image"], "images/prop-001.png")

    def test_list_of_dicts(self):
        """测试字典列表"""
        self._create_upload_file("character", "c1.png")
        self._create_upload_file("character", "c2.png")
        data = [
            {"name": "角色1", "reference_image": "http://localhost:9003/upload/character/pic/c1.png"},
            {"name": "角色2", "reference_image": "http://localhost:9003/upload/character/pic/c2.png"},
        ]
        result = self.fm._rewrite_image_urls(data, self.image_mapping, self.collected)
        self.assertEqual(result[0]["reference_image"], "images/c1.png")
        self.assertEqual(result[1]["reference_image"], "images/c2.png")

    def test_deduplicate_images(self):
        """测试重复图片在 image_mapping 中只记录一次"""
        self._create_upload_file("character", "same.png")
        # _rewrite_image_urls 只处理 reference_image 和 reference_images 这两个 key
        data = {
            "char1": {"reference_image": "http://localhost:9003/upload/character/pic/same.png"},
            "char2": {"reference_image": "http://localhost:9003/upload/character/pic/same.png"},
        }
        result = self.fm._rewrite_image_urls(data, self.image_mapping, self.collected)
        # image_mapping 中只有一条记录（同一张图片）
        self.assertEqual(len(self.image_mapping), 1)
        self.assertIn("same.png", self.image_mapping)

    def test_empty_reference_image_string(self):
        """测试空字符串 reference_image 不处理"""
        data = {"reference_image": ""}
        result = self.fm._rewrite_image_urls(data, self.image_mapping, self.collected)
        self.assertEqual(result["reference_image"], "")

    def test_with_zipfile(self):
        """测试写入 zip 文件"""
        self._create_upload_file("character", "zip-test.png")
        zip_path = Path(self.tmp_dir) / "test.zip"
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            data = {"reference_image": "http://localhost:9003/upload/character/pic/zip-test.png"}
            self.fm._rewrite_image_urls(data, self.image_mapping, self.collected, zipf)

        with zipfile.ZipFile(zip_path, 'r') as zipf:
            self.assertIn("images/zip-test.png", zipf.namelist())


class TestRestoreImageUrls(unittest.TestCase):
    """测试 _restore_image_urls 方法"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_restore_")
        self.fm = FileManager(base_dir=self.tmp_dir)
        self.upload_base = Path(self.tmp_dir) / "upload"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_restore_single_reference_image(self):
        """测试还原单张 reference_image"""
        reverse_mapping = {"char-001.png": "/upload/character/pic/char-001.png"}
        uploaded = {}
        data = {"reference_image": "images/char-001.png"}
        result = self.fm._restore_image_urls(data, reverse_mapping, uploaded, self.upload_base)
        self.assertEqual(result["reference_image"], "/upload/character/pic/char-001.png")
        self.assertIn("char-001.png", uploaded)

    def test_restore_reference_images_list(self):
        """测试还原多角度参考图列表"""
        reverse_mapping = {
            "loc-001.png": "/upload/location/pic/loc-001.png",
            "loc-002.png": "/upload/location/pic/loc-002.png",
        }
        uploaded = {}
        data = {
            "reference_images": [
                {"url": "images/loc-001.png", "angle": "front"},
                {"url": "images/loc-002.png", "angle": "side"},
            ]
        }
        result = self.fm._restore_image_urls(data, reverse_mapping, uploaded, self.upload_base)
        self.assertEqual(result["reference_images"][0]["url"], "/upload/location/pic/loc-001.png")
        self.assertEqual(result["reference_images"][1]["url"], "/upload/location/pic/loc-002.png")
        self.assertEqual(result["reference_images"][0]["angle"], "front")

    def test_no_image_fields(self):
        """测试没有图片字段的数据"""
        reverse_mapping = {}
        uploaded = {}
        data = {"name": "测试", "description": "无图片"}
        result = self.fm._restore_image_urls(data, reverse_mapping, uploaded, self.upload_base)
        self.assertEqual(result, data)

    def test_nested_dict(self):
        """测试嵌套字典"""
        reverse_mapping = {"prop.png": "/upload/props/pic/prop.png"}
        uploaded = {}
        data = {"item": {"reference_image": "images/prop.png"}}
        result = self.fm._restore_image_urls(data, reverse_mapping, uploaded, self.upload_base)
        self.assertEqual(result["item"]["reference_image"], "/upload/props/pic/prop.png")

    def test_image_not_in_mapping(self):
        """测试图片不在映射中时保持原值"""
        reverse_mapping = {}
        uploaded = {}
        data = {"reference_image": "images/unknown.png"}
        result = self.fm._restore_image_urls(data, reverse_mapping, uploaded, self.upload_base)
        self.assertEqual(result["reference_image"], "images/unknown.png")


class TestExportWorld(unittest.TestCase):
    """测试 export_world 方法"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_export_")
        self.fm = FileManager(base_dir=self.tmp_dir)
        self.user_id = "test_user"
        self.world_id = "test_world"
        # 创建世界目录结构
        self.fm._ensure_directories(self.user_id, self.world_id)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_character_json(self, name: str, image_url: str = None) -> Path:
        """创建角色 JSON 文件"""
        base_path = self.fm._get_user_world_path(self.user_id, self.world_id)
        char_dir = base_path / "characters"
        char_dir.mkdir(parents=True, exist_ok=True)
        data = {"name": name}
        if image_url:
            data["reference_image"] = image_url
        file_path = char_dir / f"{name}.json"
        file_path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return file_path

    def test_export_basic(self):
        """测试基本导出功能"""
        self._create_character_json("角色A")
        zip_path = self.fm.export_world(self.user_id, self.world_id)
        self.assertTrue(os.path.exists(zip_path))
        self.assertTrue(zip_path.endswith('.zip'))

        with zipfile.ZipFile(zip_path, 'r') as zipf:
            names = zipf.namelist()
            self.assertIn("metadata.json", names)
            self.assertIn("characters/角色A.json", names)
            # 验证 metadata
            metadata = json.loads(zipf.read("metadata.json"))
            self.assertEqual(metadata["world_id"], self.world_id)
            self.assertEqual(metadata["user_id"], self.user_id)
            self.assertEqual(metadata["export_version"], "1.0")

        os.unlink(zip_path)

    def test_export_filename_uses_world_name_and_timestamp(self):
        """测试导出文件名使用世界名称+时间戳"""
        base_path = self.fm._get_user_world_path(self.user_id, self.world_id)
        worlds_dir = base_path / "worlds"
        worlds_dir.mkdir(parents=True, exist_ok=True)
        world_data = {"id": 1, "name": "测试世界", "user_id": 1}
        (worlds_dir / f"world_{self.world_id}.json").write_text(
            json.dumps(world_data, ensure_ascii=False), encoding='utf-8'
        )

        self._create_character_json("角色A")
        zip_path = self.fm.export_world(self.user_id, self.world_id)
        self.assertTrue(os.path.exists(zip_path))

        zip_filename = os.path.basename(zip_path)
        # 文件名应以世界名称开头，并包含时间戳和 .zip 后缀
        self.assertTrue(zip_filename.startswith("测试世界_"), f"文件名应为世界名称+时间戳，实际为: {zip_filename}")
        self.assertTrue(zip_filename.endswith(".zip"), f"文件名应以 .zip 结尾，实际为: {zip_filename}")
        # 时间戳格式为 YYYYMMDD_HHMMSS，中间用下划线连接
        import re
        self.assertRegex(zip_filename, r"^测试世界_\d{8}_\d{6}\.zip$")

        os.unlink(zip_path)

    def test_export_filename_fallback_when_world_name_missing(self):
        """测试世界名称为空时回退到 world_export_{world_id}_{timestamp}.zip"""
        self._create_character_json("角色A")
        zip_path = self.fm.export_world(self.user_id, self.world_id)
        self.assertTrue(os.path.exists(zip_path))

        zip_filename = os.path.basename(zip_path)
        import re
        self.assertRegex(zip_filename, r"^world_export_test_world_\d{8}_\d{6}\.zip$")

        os.unlink(zip_path)

    def test_export_with_images(self):
        """测试导出包含图片"""
        # 创建图片文件
        base_path = self.fm._get_user_world_path(self.user_id, self.world_id)
        img_dir = Path(self.tmp_dir) / "upload" / "character" / "pic"
        img_dir.mkdir(parents=True, exist_ok=True)
        img_file = img_dir / "char-img.png"
        img_file.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)

        # 创建角色引用该图片
        self._create_character_json("有图角色", f"http://localhost:9003/upload/character/pic/char-img.png")

        zip_path = self.fm.export_world(self.user_id, self.world_id)

        with zipfile.ZipFile(zip_path, 'r') as zipf:
            names = zipf.namelist()
            self.assertIn("images/char-img.png", names)
            self.assertIn("image_mapping.json", names)
            # 验证 image_mapping
            mapping = json.loads(zipf.read("image_mapping.json"))
            self.assertIn("char-img.png", mapping)
            # 验证 metadata 中的图片计数
            metadata = json.loads(zipf.read("metadata.json"))
            self.assertEqual(metadata["image_count"], 1)

        os.unlink(zip_path)

    def test_export_with_script_problem(self):
        """测试导出包含 script_problem.json"""
        base_path = self.fm._get_user_world_path(self.user_id, self.world_id)
        problem_file = base_path / "script_problem.json"
        problem_data = {"verdict": False, "problem": "测试问题"}
        problem_file.write_text(json.dumps(problem_data), encoding='utf-8')

        zip_path = self.fm.export_world(self.user_id, self.world_id)

        with zipfile.ZipFile(zip_path, 'r') as zipf:
            self.assertIn("script_problem.json", zipf.namelist())
            content = json.loads(zipf.read("script_problem.json"))
            self.assertEqual(content["problem"], "测试问题")

        os.unlink(zip_path)

    def test_export_world_not_found(self):
        """测试导出不存在的世界"""
        with self.assertRaises(FileNotFoundError):
            self.fm.export_world("nonexistent_user", "nonexistent_world")


class TestImportWorld(unittest.TestCase):
    """测试 import_world 方法"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_import_")
        self.fm = FileManager(base_dir=self.tmp_dir)
        self.user_id = "import_user"
        self.world_id = "import_world"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_export_zip(self, characters=None, locations=None, images=None, script_problem=None) -> str:
        """创建一个模拟的导出 zip 文件"""
        zip_path = os.path.join(self.tmp_dir, "test_export.zip")
        image_mapping = {}

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 添加角色
            if characters:
                for char in characters:
                    zipf.writestr(f"characters/{char['name']}.json", json.dumps(char, ensure_ascii=False))

            # 添加场景
            if locations:
                for loc in locations:
                    zipf.writestr(f"locations/{loc['name']}.json", json.dumps(loc, ensure_ascii=False))

            # 添加图片
            if images:
                for img_name, img_data in images.items():
                    zipf.writestr(f"images/{img_name}", img_data)
                    image_mapping[img_name] = f"/upload/character/pic/{img_name}"

            # 添加 image_mapping
            if image_mapping:
                zipf.writestr("image_mapping.json", json.dumps(image_mapping, ensure_ascii=False))

            # 添加 script_problem
            if script_problem:
                zipf.writestr("script_problem.json", json.dumps(script_problem, ensure_ascii=False))

            # 添加 metadata
            metadata = {
                "export_version": "1.0",
                "world_id": "src_world",
                "user_id": "src_user",
                "image_count": len(images or {}),
                "subdirs": ["characters", "locations", "props", "scripts", "worlds"]
            }
            zipf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False))

        return zip_path

    def test_import_basic(self):
        """测试基本导入功能"""
        characters = [
            {"name": "导入角色A", "description": "测试角色"},
            {"name": "导入角色B", "description": "另一个角色"},
        ]
        zip_path = self._create_export_zip(characters=characters)

        result = self.fm.import_world(self.user_id, self.world_id, zip_path)

        self.assertEqual(result["characters"], 2)
        self.assertEqual(len(result["errors"]), 0)

        # 验证文件已写入
        base_path = self.fm._get_user_world_path(self.user_id, self.world_id)
        self.assertTrue((base_path / "characters" / "导入角色A.json").exists())
        self.assertTrue((base_path / "characters" / "导入角色B.json").exists())

        # 验证文件内容
        with open(base_path / "characters" / "导入角色A.json", 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(data["description"], "测试角色")

    def test_import_with_images(self):
        """测试导入包含图片"""
        images = {"test-img.png": b'\x89PNG\r\n\x1a\n' + b'\x00' * 50}
        characters = [
            {"name": "有图角色", "reference_image": "images/test-img.png"},
        ]
        zip_path = self._create_export_zip(characters=characters, images=images)

        result = self.fm.import_world(self.user_id, self.world_id, zip_path)

        self.assertEqual(result["images"], 1)
        self.assertEqual(result["characters"], 1)

        # 验证图片已复制到 upload 目录
        img_path = Path(self.tmp_dir) / "upload" / "character" / "pic" / "test-img.png"
        self.assertTrue(img_path.exists())

        # 验证角色 JSON 中的 URL 已还原
        base_path = self.fm._get_user_world_path(self.user_id, self.world_id)
        with open(base_path / "characters" / "有图角色.json", 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(data["reference_image"], "/upload/character/pic/test-img.png")

    def test_import_with_script_problem(self):
        """测试导入 script_problem.json"""
        script_problem = {"verdict": False, "problem": "导入的问题"}
        zip_path = self._create_export_zip(script_problem=script_problem)

        result = self.fm.import_world(self.user_id, self.world_id, zip_path)

        base_path = self.fm._get_user_world_path(self.user_id, self.world_id)
        problem_file = base_path / "script_problem.json"
        self.assertTrue(problem_file.exists())
        with open(problem_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(data["problem"], "导入的问题")

    def test_import_multiple_subdirs(self):
        """测试导入多个子目录"""
        characters = [{"name": "角色1"}]
        locations = [{"name": "场景1"}]
        zip_path = self._create_export_zip(characters=characters, locations=locations)

        result = self.fm.import_world(self.user_id, self.world_id, zip_path)

        self.assertEqual(result["characters"], 1)
        self.assertEqual(result["locations"], 1)

    def test_import_image_already_exists(self):
        """测试图片已存在时不覆盖"""
        # 预先创建图片
        img_dir = Path(self.tmp_dir) / "upload" / "character" / "pic"
        img_dir.mkdir(parents=True, exist_ok=True)
        existing_img = img_dir / "existing.png"
        existing_img.write_bytes(b'ORIGINAL')

        images = {"existing.png": b'NEW_DATA'}
        zip_path = self._create_export_zip(images=images)

        result = self.fm.import_world(self.user_id, self.world_id, zip_path)

        # 图片不应被覆盖
        self.assertEqual(existing_img.read_bytes(), b'ORIGINAL')
        # 但计数仍为 1（因为 uploaded_images 会记录）
        self.assertEqual(result["images"], 0)  # 已存在，不写入


class TestExportImportRoundTrip(unittest.TestCase):
    """测试导出→导入的完整往返"""

    def setUp(self):
        self.export_dir = tempfile.mkdtemp(prefix="test_fm_export_rt_")
        self.import_dir = tempfile.mkdtemp(prefix="test_fm_import_rt_")
        self.fm_export = FileManager(base_dir=self.export_dir)
        self.fm_import = FileManager(base_dir=self.import_dir)
        self.user_id = "rt_user"
        self.world_id = "rt_world"

    def tearDown(self):
        shutil.rmtree(self.export_dir, ignore_errors=True)
        shutil.rmtree(self.import_dir, ignore_errors=True)

    def test_roundtrip_with_images(self):
        """测试导出再导入后数据一致"""
        # 准备导出数据
        base_path = self.fm_export._get_user_world_path(self.user_id, self.world_id)
        self.fm_export._ensure_directories(self.user_id, self.world_id)

        # 创建图片
        img_dir = Path(self.export_dir) / "upload" / "character" / "pic"
        img_dir.mkdir(parents=True, exist_ok=True)
        img_file = img_dir / "roundtrip-img.png"
        img_content = b'\x89PNG\r\n\x1a\n' + b'\x00' * 200
        img_file.write_bytes(img_content)

        # 创建角色
        char_data = {
            "name": "往返角色",
            "description": "测试往返",
            "reference_image": "http://localhost:9003/upload/character/pic/roundtrip-img.png"
        }
        (base_path / "characters" / "往返角色.json").write_text(
            json.dumps(char_data, ensure_ascii=False), encoding='utf-8'
        )

        # 创建场景
        loc_data = {
            "name": "往返场景",
            "reference_images": [
                {"url": "http://localhost:9003/upload/character/pic/roundtrip-img.png", "angle": "front"}
            ]
        }
        (base_path / "locations" / "往返场景.json").write_text(
            json.dumps(loc_data, ensure_ascii=False), encoding='utf-8'
        )

        # 导出
        zip_path = self.fm_export.export_world(self.user_id, self.world_id)

        # 导入
        result = self.fm_import.import_world(self.user_id, self.world_id, zip_path)

        # 验证
        self.assertEqual(result["characters"], 1)
        self.assertEqual(result["locations"], 1)
        self.assertEqual(result["images"], 1)
        self.assertEqual(len(result["errors"]), 0)

        # 验证导入后的角色数据
        import_base = self.fm_import._get_user_world_path(self.user_id, self.world_id)
        with open(import_base / "characters" / "往返角色.json", 'r', encoding='utf-8') as f:
            imported_char = json.load(f)
            # URL 应该被还原为原始路径
            self.assertEqual(imported_char["reference_image"], "/upload/character/pic/roundtrip-img.png")
            self.assertEqual(imported_char["description"], "测试往返")

        # 验证图片已复制
        import_img = Path(self.import_dir) / "upload" / "character" / "pic" / "roundtrip-img.png"
        self.assertTrue(import_img.exists())
        self.assertEqual(import_img.read_bytes(), img_content)

        # 清理
        os.unlink(zip_path)


class TestStripDbIds(unittest.TestCase):
    """测试 _strip_db_ids 方法"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_strip_")
        self.fm = FileManager(base_dir=self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_strip_id_fields(self):
        """测试清除数据库 ID 字段"""
        data = {"id": 6, "name": "测试", "world_id": 16, "user_id": 1, "description": "描述"}
        result = self.fm._strip_db_ids(data)
        self.assertNotIn("id", result)
        self.assertNotIn("world_id", result)
        self.assertNotIn("user_id", result)
        self.assertEqual(result["name"], "测试")
        self.assertEqual(result["description"], "描述")

    def test_strip_timestamp_fields(self):
        """测试清除时间戳字段"""
        data = {"id": 1, "name": "测试", "create_time": "2026-01-01", "update_time": "2026-01-02"}
        result = self.fm._strip_db_ids(data)
        self.assertNotIn("id", result)
        self.assertNotIn("create_time", result)
        self.assertNotIn("update_time", result)
        self.assertEqual(result["name"], "测试")

    def test_non_dict_passthrough(self):
        """测试非 dict 数据直接返回"""
        self.assertEqual(self.fm._strip_db_ids("hello"), "hello")
        self.assertEqual(self.fm._strip_db_ids(42), 42)
        self.assertEqual(self.fm._strip_db_ids([1, 2]), [1, 2])

    def test_no_id_fields(self):
        """测试没有 ID 字段的数据不变"""
        data = {"name": "测试", "description": "描述"}
        result = self.fm._strip_db_ids(data)
        self.assertEqual(result, data)


class TestExportStripDbIds(unittest.TestCase):
    """测试导出时清除数据库 ID"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_export_strip_")
        self.fm = FileManager(base_dir=self.tmp_dir)
        self.user_id = "test_user"
        self.world_id = "test_world"
        self.fm._ensure_directories(self.user_id, self.world_id)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_export_strips_db_ids_from_character(self):
        """测试导出时角色 JSON 中不包含 id/world_id/user_id"""
        base_path = self.fm._get_user_world_path(self.user_id, self.world_id)
        char_data = {
            "id": 42, "name": "角色A", "world_id": 16, "user_id": 1,
            "description": "描述", "create_time": "2026-01-01"
        }
        (base_path / "characters" / "角色A.json").write_text(
            json.dumps(char_data, ensure_ascii=False), encoding='utf-8'
        )

        zip_path = self.fm.export_world(self.user_id, self.world_id)
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            content = json.loads(zipf.read("characters/角色A.json"))
            self.assertNotIn("id", content)
            self.assertNotIn("world_id", content)
            self.assertNotIn("user_id", content)
            self.assertNotIn("create_time", content)
            self.assertEqual(content["name"], "角色A")
            self.assertEqual(content["description"], "描述")
        os.unlink(zip_path)

    def test_export_strips_db_ids_from_world(self):
        """测试导出时世界 JSON 中不包含 id/user_id"""
        base_path = self.fm._get_user_world_path(self.user_id, self.world_id)
        world_data = {"id": 16, "name": "世界A", "user_id": 1, "story_outline": "大纲"}
        worlds_dir = base_path / "worlds"
        worlds_dir.mkdir(parents=True, exist_ok=True)
        (worlds_dir / f"world_{self.world_id}.json").write_text(
            json.dumps(world_data, ensure_ascii=False), encoding='utf-8'
        )

        zip_path = self.fm.export_world(self.user_id, self.world_id)
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            content = json.loads(zipf.read(f"worlds/world_{self.world_id}.json"))
            self.assertNotIn("id", content)
            self.assertNotIn("user_id", content)
            self.assertEqual(content["name"], "世界A")
        os.unlink(zip_path)


class TestImportWorldFilenameRewrite(unittest.TestCase):
    """测试导入时 worlds 文件名重写"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_import_rewrite_")
        self.fm = FileManager(base_dir=self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_import_world_filename_rewrite(self):
        """测试导入 world_6.json 到 world_1 时文件名正确重写"""
        # 创建包含 world_6.json 的 ZIP
        zip_path = os.path.join(self.tmp_dir, "test.zip")
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            world_data = {"name": "导出世界", "story_outline": "大纲"}
            zipf.writestr("worlds/world_6.json", json.dumps(world_data, ensure_ascii=False))
            zipf.writestr("metadata.json", json.dumps({
                "export_version": "1.0", "world_id": "6", "user_id": "1"
            }))

        result = self.fm.import_world("user_1", "1", zip_path)
        self.assertEqual(result["worlds"], 1)

        # 验证文件名已重写为 world_1.json
        base_path = self.fm._get_user_world_path("user_1", "1")
        self.assertTrue((base_path / "worlds" / "world_1.json").exists())
        # 原始文件名不应存在
        self.assertFalse((base_path / "worlds" / "world_6.json").exists())

        with open(base_path / "worlds" / "world_1.json", 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(data["name"], "导出世界")


class TestVoiceExportImport(unittest.TestCase):
    """测试角色音频导出/导入"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_voice_")
        self.fm = FileManager(base_dir=self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_voice_file(self, filename: str) -> Path:
        """创建假音频文件"""
        voice_dir = Path(self.tmp_dir) / "upload" / "character" / "voice"
        voice_dir.mkdir(parents=True, exist_ok=True)
        voice_file = voice_dir / filename
        voice_file.write_bytes(b'FAKE_AUDIO_DATA' + b'\x00' * 100)
        return voice_file

    def test_collect_voice_from_url(self):
        """测试解析音频 URL"""
        self._create_voice_file("voice_001.wav")
        url = "http://localhost:9003/upload/character/voice/voice_001.wav"
        result = self.fm._collect_voice_from_url(url)
        self.assertIsNotNone(result)
        filename, file_path = result
        self.assertEqual(filename, "voice_001.wav")
        self.assertTrue(file_path.exists())

    def test_collect_voice_invalid_url(self):
        """测试无效音频 URL"""
        result = self.fm._collect_voice_from_url("http://example.com/other/file.wav")
        self.assertIsNone(result)

    def test_collect_voice_non_audio_ext(self):
        """测试非音频扩展名"""
        result = self.fm._collect_voice_from_url("http://localhost:9003/upload/character/voice/file.txt")
        self.assertIsNone(result)

    def test_rewrite_default_voice(self):
        """测试导出时替换 default_voice URL"""
        self._create_voice_file("voice_test.wav")
        image_mapping = {}
        collected = set()
        audio_mapping = {}
        collected_audios = set()

        data = {
            "name": "角色A",
            "default_voice": "http://localhost:9003/upload/character/voice/voice_test.wav"
        }
        result = self.fm._rewrite_image_urls(
            data, image_mapping, collected,
            audio_mapping=audio_mapping, collected_audios=collected_audios
        )
        self.assertEqual(result["default_voice"], "audios/voice_test.wav")
        self.assertIn("voice_test.wav", audio_mapping)

    def test_rewrite_default_voice_without_audio_params(self):
        """测试不传 audio 参数时 default_voice 保持不变"""
        data = {
            "name": "角色A",
            "default_voice": "http://localhost:9003/upload/character/voice/voice_test.wav"
        }
        image_mapping = {}
        collected = set()
        result = self.fm._rewrite_image_urls(data, image_mapping, collected)
        # 没有传 audio_mapping/collected_audios，走 else 分支，值不变
        self.assertEqual(result["default_voice"], "http://localhost:9003/upload/character/voice/voice_test.wav")

    def test_restore_default_voice(self):
        """测试导入时还原 default_voice URL"""
        audio_mapping = {"voice_001.wav": "/upload/character/voice/voice_001.wav"}
        reverse_mapping = {}
        uploaded = {}
        upload_base = Path(self.tmp_dir) / "upload"

        data = {"name": "角色A", "default_voice": "audios/voice_001.wav"}
        result = self.fm._restore_image_urls(
            data, reverse_mapping, uploaded, upload_base,
            audio_mapping=audio_mapping
        )
        self.assertEqual(result["default_voice"], "/upload/character/voice/voice_001.wav")

    def test_restore_default_voice_without_mapping(self):
        """测试不传 audio_mapping 时 default_voice 保持不变"""
        reverse_mapping = {}
        uploaded = {}
        upload_base = Path(self.tmp_dir) / "upload"

        data = {"name": "角色A", "default_voice": "audios/voice_001.wav"}
        result = self.fm._restore_image_urls(data, reverse_mapping, uploaded, upload_base)
        self.assertEqual(result["default_voice"], "audios/voice_001.wav")

    def test_export_with_voice(self):
        """测试导出包含音频"""
        self._create_voice_file("export_voice.wav")
        user_id, world_id = "user_1", "world_1"
        self.fm._ensure_directories(user_id, world_id)
        base_path = self.fm._get_user_world_path(user_id, world_id)

        char_data = {
            "name": "音频角色",
            "default_voice": "http://localhost:9003/upload/character/voice/export_voice.wav"
        }
        (base_path / "characters" / "音频角色.json").write_text(
            json.dumps(char_data, ensure_ascii=False), encoding='utf-8'
        )

        zip_path = self.fm.export_world(user_id, world_id)
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            names = zipf.namelist()
            self.assertIn("audios/export_voice.wav", names)
            self.assertIn("audio_mapping.json", names)
            mapping = json.loads(zipf.read("audio_mapping.json"))
            self.assertIn("export_voice.wav", mapping)
            metadata = json.loads(zipf.read("metadata.json"))
            self.assertEqual(metadata["audio_count"], 1)
        os.unlink(zip_path)

    def test_import_with_voice(self):
        """测试导入包含音频"""
        zip_path = os.path.join(self.tmp_dir, "test_import_voice.zip")
        audio_content = b'FAKE_AUDIO_DATA'
        audio_mapping = {"import_voice.wav": "/upload/character/voice/import_voice.wav"}

        with zipfile.ZipFile(zip_path, 'w') as zipf:
            zipf.writestr("audios/import_voice.wav", audio_content)
            zipf.writestr("audio_mapping.json", json.dumps(audio_mapping))
            char_data = {"name": "导入音频角色", "default_voice": "audios/import_voice.wav"}
            zipf.writestr("characters/导入音频角色.json", json.dumps(char_data, ensure_ascii=False))
            zipf.writestr("metadata.json", json.dumps({"export_version": "1.0"}))

        result = self.fm.import_world("user_1", "world_1", zip_path)
        self.assertEqual(result["audios"], 1)
        self.assertEqual(result["characters"], 1)

        # 验证音频文件已复制
        voice_file = Path(self.tmp_dir) / "upload" / "character" / "voice" / "import_voice.wav"
        self.assertTrue(voice_file.exists())
        self.assertEqual(voice_file.read_bytes(), audio_content)

        # 验证角色 JSON 中 URL 已还原
        base_path = self.fm._get_user_world_path("user_1", "world_1")
        with open(base_path / "characters" / "导入音频角色.json", 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(data["default_voice"], "/upload/character/voice/import_voice.wav")

    def test_roundtrip_with_voice(self):
        """测试导出→导入包含音频的完整往返"""
        export_dir = tempfile.mkdtemp(prefix="test_fm_rt_v_export_")
        import_dir = tempfile.mkdtemp(prefix="test_fm_rt_v_import_")
        try:
            fm_export = FileManager(base_dir=export_dir)
            fm_import = FileManager(base_dir=import_dir)
            user_id, world_id = "rt_user", "rt_world"
            fm_export._ensure_directories(user_id, world_id)

            # 创建音频文件
            voice_dir = Path(export_dir) / "upload" / "character" / "voice"
            voice_dir.mkdir(parents=True, exist_ok=True)
            voice_content = b'ROUNDTRIP_AUDIO' + b'\x00' * 200
            (voice_dir / "rt_voice.wav").write_bytes(voice_content)

            # 创建角色
            base_path = fm_export._get_user_world_path(user_id, world_id)
            char_data = {
                "id": 99, "name": "往返音频角色", "user_id": 5,
                "default_voice": "http://localhost:9003/upload/character/voice/rt_voice.wav"
            }
            (base_path / "characters" / "往返音频角色.json").write_text(
                json.dumps(char_data, ensure_ascii=False), encoding='utf-8'
            )

            # 导出
            zip_path = fm_export.export_world(user_id, world_id)

            # 导入到不同世界
            result = fm_import.import_world(user_id, "different_world", zip_path)
            self.assertEqual(result["audios"], 1)
            self.assertEqual(result["characters"], 1)
            self.assertEqual(len(result["errors"]), 0)

            # 验证音频已复制
            import_voice = Path(import_dir) / "upload" / "character" / "voice" / "rt_voice.wav"
            self.assertTrue(import_voice.exists())
            self.assertEqual(import_voice.read_bytes(), voice_content)

            # 验证角色数据
            import_base = fm_import._get_user_world_path(user_id, "different_world")
            with open(import_base / "characters" / "往返音频角色.json", 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.assertEqual(data["default_voice"], "/upload/character/voice/rt_voice.wav")
                self.assertEqual(data["name"], "往返音频角色")
                # id 和 user_id 应该被清除
                self.assertNotIn("id", data)
                self.assertNotIn("user_id", data)

            os.unlink(zip_path)
        finally:
            shutil.rmtree(export_dir, ignore_errors=True)
            shutil.rmtree(import_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
