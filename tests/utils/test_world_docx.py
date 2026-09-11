"""
世界数据 Word 文档导出功能单元测试

测试 FileManager.export_world_docx 及 script_writer_core.world_docx 构建器。
不依赖数据库，使用临时目录模拟文件系统（与 test_file_manager_export.py 同套路）。
"""
import os
import sys
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

# 添加项目根目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from PIL import Image

from script_writer_core.file_manager import FileManager
from script_writer_core.world_docx import build_world_docx


def _make_png(path: Path) -> Path:
    """生成一张 1x1 的真实 PNG（仅写 magic bytes 无法被 PIL 解析）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1, 1), (200, 30, 30)).save(str(path))
    return path


class TestExportWorldDocx(unittest.TestCase):
    """测试 FileManager.export_world_docx"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="test_fm_docx_")
        self.fm = FileManager(base_dir=self.tmp_dir)
        self._make_world_data()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _make_world_data(self):
        """构造一个最小完整世界：world/character/location/prop/script 各 1 个 + 图片"""
        base = Path(self.tmp_dir) / "files" / "script_writer" / "1" / "1"
        for sub in ("worlds", "characters", "locations", "props", "scripts"):
            (base / sub).mkdir(parents=True, exist_ok=True)

        _make_png(Path(self.tmp_dir) / "upload" / "character" / "pic" / "char1.png")
        _make_png(Path(self.tmp_dir) / "upload" / "location" / "pic" / "loc1.png")
        _make_png(Path(self.tmp_dir) / "upload" / "location" / "pic" / "loc1_90.png")
        _make_png(Path(self.tmp_dir) / "upload" / "props" / "pic" / "prop1.png")

        world = {
            "id": 1, "world_id": "1", "user_id": "1",
            "name": "测试世界",
            "story_outline": "# 《测试剧》故事大纲\n\n## 故事概述\n快递小哥的远方。\n\n## 角色发展线\n- 甲：从迷茫到坚定\n",
            "story_type": "dialogue",
            "visual_style": "电影级写实",
            "era_environment": "2023年中国现代城市",
            "composition_preference": "三分法构图",
        }
        (base / "worlds" / "world_1.json").write_text(
            json.dumps(world, ensure_ascii=False), encoding="utf-8")

        character = {
            "id": 1, "world_id": "1", "user_id": "1",
            "name": "甲", "age": "28岁", "identity": "快递员",
            "appearance": "中等身材，皮肤黝黑",
            "personality": "核心特质：积极进取\n优点：\n1. 勤奋好学\n缺陷：\n1. 偶尔理想主义",
            "behavior": "说话方式：语气温和\n肢体语言：习惯整理快递箱",
            "other_info": "背景故事：2022年入职\n核心动机：证明职业价值\n角色弧线：起点 → 转变 → 终点",
            "default_voice": "http://localhost:9003/upload/character/voice/v1.mp3",
            "reference_image": "http://localhost:9003/upload/character/pic/char1.png",
        }
        (base / "characters" / "character_甲.json").write_text(
            json.dumps(character, ensure_ascii=False), encoding="utf-8")

        location = {
            "id": 1, "world_id": "1", "user_id": "1",
            "name": "分享舞台",
            "description": "类型：室内场所\n功能：分享会现场\n规模：中等\n布局：舞台中央设演讲台\n特征：专业灯光\n环境：灯光由暗转亮\n氛围：庄重而温馨\n剧情作用：核心开场场景",
            "reference_image": "http://localhost:9003/upload/location/pic/loc1.png",
            "reference_images": [
                {"angle": "right", "label": "90°", "url": "http://localhost:9003/upload/location/pic/loc1_90.png"},
            ],
        }
        (base / "locations" / "location_分享舞台.json").write_text(
            json.dumps(location, ensure_ascii=False), encoding="utf-8")

        prop = {
            "id": 1, "world_id": "1", "user_id": "1",
            "name": "快递箱", "type": "工具类",
            "description": "外观：旧顺丰快递箱\n规格：40×30×25厘米\n功能：装三件宝贝\n特殊性：百宝箱\n背景：入职以来使用\n剧情作用：核心道具\n象征意义：平凡中孕育不平凡",
            "reference_image": "http://localhost:9003/upload/props/pic/prop1.png",
        }
        (base / "props" / "prop_快递箱.json").write_text(
            json.dumps(prop, ensure_ascii=False), encoding="utf-8")

        script = {
            "id": 1, "world_id": "1", "user_id": "1",
            "title": "测试剧", "episode_number": 1,
            "content": (
                "# 短剧剧本《测试剧》第1集\n\n---\n\n"
                "## 第一场 分享舞台 · 日 · 内\n场景编号：A1\n\n"
                "灯光亮起。甲上台。\n\n"
                "**甲**：大家好，我叫甲。\n\n"
                "【字幕】测试字幕内容。\n\n【转场】\n\n"
                "## 第二场 舞台（续）\n\n"
                "**（剧终）**\n"
            ),
        }
        (base / "scripts" / "1.json").write_text(
            json.dumps(script, ensure_ascii=False), encoding="utf-8")

    def test_export_world_docx_basic(self):
        """正常导出：docx 存在、结构完整、图片嵌入"""
        path = self.fm.export_world_docx("1", "1")
        try:
            self.assertTrue(os.path.exists(path))
            self.assertTrue(path.endswith(".docx"))
            self.assertIn("测试世界", os.path.basename(path))

            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                self.assertIn("word/document.xml", names)
                # 4 张占位 PNG 内容相同，python-docx 按哈希去重，实际嵌入 1 张
                media = [n for n in names if n.startswith("word/media/")]
                self.assertGreaterEqual(len(media), 1, f"应嵌入图片: {media}")

                doc_xml = zf.read("word/document.xml").decode("utf-8")
                # 各章节都在
                for section in ["一、故事大纲", "二、角色说明", "三、场景设计",
                                "四、道具设定", "五、完整剧本", "目录"]:
                    self.assertIn(section, doc_xml, f"缺少章节: {section}")
                # 内容抽查
                self.assertIn("甲", doc_xml)
                self.assertIn("角色：甲", doc_xml)
                self.assertIn("场景：分享舞台", doc_xml)
                self.assertIn("道具：快递箱", doc_xml)
                self.assertIn("大家好，我叫甲", doc_xml)
                self.assertIn("【字幕】测试字幕内容。", doc_xml)
                self.assertIn("（剧终）", doc_xml)
                # 封面标题取大纲剧名
                self.assertIn("测试剧", doc_xml)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_export_world_docx_missing_image(self):
        """图片缺失：不抛异常，docx 中含缺失图片占位"""
        base = Path(self.tmp_dir) / "files" / "script_writer" / "1" / "1"
        char_file = base / "characters" / "character_甲.json"
        char = json.loads(char_file.read_text(encoding="utf-8"))
        char["reference_image"] = "http://localhost:9003/upload/character/pic/not_exist.png"
        char_file.write_text(json.dumps(char, ensure_ascii=False), encoding="utf-8")

        path = self.fm.export_world_docx("1", "1")
        try:
            with zipfile.ZipFile(path) as zf:
                doc_xml = zf.read("word/document.xml").decode("utf-8")
                self.assertIn("缺失图片", doc_xml)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_export_world_docx_corrupt_image(self):
        """图片文件损坏/格式不支持：不抛异常，docx 中含占位文字"""
        base = Path(self.tmp_dir) / "files" / "script_writer" / "1" / "1"
        bad = Path(self.tmp_dir) / "upload" / "character" / "pic" / "bad.png"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("this is not a png", encoding="utf-8")  # 伪 .png
        char_file = base / "characters" / "character_甲.json"
        char = json.loads(char_file.read_text(encoding="utf-8"))
        char["reference_image"] = "http://localhost:9003/upload/character/pic/bad.png"
        char_file.write_text(json.dumps(char, ensure_ascii=False), encoding="utf-8")

        path = self.fm.export_world_docx("1", "1")
        try:
            with zipfile.ZipFile(path) as zf:
                doc_xml = zf.read("word/document.xml").decode("utf-8")
                self.assertIn("缺失图片", doc_xml)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_export_world_docx_unsupported_ext(self):
        """图片扩展名不受 python-docx 支持（.svg）：不抛异常，降级占位"""
        base = Path(self.tmp_dir) / "files" / "script_writer" / "1" / "1"
        svg = Path(self.tmp_dir) / "upload" / "props" / "pic" / "p.svg"
        svg.parent.mkdir(parents=True, exist_ok=True)
        svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
        prop_file = base / "props" / "prop_快递箱.json"
        prop = json.loads(prop_file.read_text(encoding="utf-8"))
        prop["reference_image"] = "http://localhost:9003/upload/props/pic/p.svg"
        prop_file.write_text(json.dumps(prop, ensure_ascii=False), encoding="utf-8")

        path = self.fm.export_world_docx("1", "1")
        try:
            with zipfile.ZipFile(path) as zf:
                doc_xml = zf.read("word/document.xml").decode("utf-8")
                self.assertIn("缺失图片", doc_xml)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_export_world_docx_malformed_json_types(self):
        """脏数据：字段类型异常（非字符串/非列表）不抛异常"""
        base = Path(self.tmp_dir) / "files" / "script_writer" / "1" / "1"
        char_file = base / "characters" / "character_甲.json"
        char = json.loads(char_file.read_text(encoding="utf-8"))
        char["reference_image"] = 12345            # 非字符串
        char["reference_images"] = "not-a-list"     # 非列表
        char_file.write_text(json.dumps(char, ensure_ascii=False), encoding="utf-8")
        loc_file = base / "locations" / "location_分享舞台.json"
        loc = json.loads(loc_file.read_text(encoding="utf-8"))
        loc["description"] = 999
        loc_file.write_text(json.dumps(loc, ensure_ascii=False), encoding="utf-8")

        path = self.fm.export_world_docx("1", "1")
        try:
            self.assertTrue(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_export_world_docx_no_world(self):
        """世界目录不存在：抛 FileNotFoundError"""
        with self.assertRaises(FileNotFoundError):
            self.fm.export_world_docx("999", "999")

    def test_build_world_docx_empty_world(self):
        """空世界：不抛异常，docx 可生成"""
        tmp = tempfile.mkdtemp(prefix="test_fm_docx_empty_")
        try:
            out = os.path.join(tmp, "empty.docx")
            build_world_docx({"world": None, "characters": [], "locations": [],
                              "props": [], "scripts": [], "images": {}}, out)
            self.assertTrue(os.path.exists(out))
            with zipfile.ZipFile(out) as zf:
                self.assertIn("word/document.xml", zf.namelist())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
