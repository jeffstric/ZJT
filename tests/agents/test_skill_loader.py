"""
SopLoader 单元测试

测试 SOP 加载器的核心逻辑方法。
"""
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestParseFrontMatter(unittest.TestCase):
    """测试 SopLoader._parse_front_matter()"""

    def setUp(self):
        """每个测试前重置类级别状态"""
        from agents.skill_loader import SopLoader
        SopLoader._extra_sops_dirs = []

    def test_valid_front_matter(self):
        """解析有效的 front matter"""
        from agents.skill_loader import SopLoader
        content = """---
name: test-sop
description: 这是一个测试 SOP
---

# 测试内容
"""
        mock_path = MagicMock()
        mock_path.read_text.return_value = content

        loader = SopLoader.__new__(SopLoader)
        result = loader._parse_front_matter(mock_path)

        self.assertEqual(result['name'], 'test-sop')
        self.assertEqual(result['description'], '这是一个测试 SOP')

    def test_no_front_matter(self):
        """没有 front matter 返回 None"""
        from agents.skill_loader import SopLoader
        content = """# 测试内容
没有 front matter
"""
        mock_path = MagicMock()
        mock_path.read_text.return_value = content

        loader = SopLoader.__new__(SopLoader)
        result = loader._parse_front_matter(mock_path)

        self.assertIsNone(result)

    def test_empty_front_matter(self):
        """空 front matter 返回 None（正则不匹配）"""
        from agents.skill_loader import SopLoader
        content = """---
---

# 测试内容
"""
        mock_path = MagicMock()
        mock_path.read_text.return_value = content

        loader = SopLoader.__new__(SopLoader)
        result = loader._parse_front_matter(mock_path)

        # 空 front matter 不匹配正则，返回 None
        self.assertIsNone(result)

    def test_exception_returns_none(self):
        """读取异常返回 None"""
        from agents.skill_loader import SopLoader
        mock_path = MagicMock()
        mock_path.read_text.side_effect = Exception("文件读取失败")

        loader = SopLoader.__new__(SopLoader)
        result = loader._parse_front_matter(mock_path)

        self.assertIsNone(result)


class TestListSops(unittest.TestCase):
    """测试 SopLoader.list_sops()"""

    def setUp(self):
        """每个测试前重置类级别状态"""
        from agents.skill_loader import SopLoader
        SopLoader._extra_sops_dirs = []

    def test_returns_sop_names(self):
        """返回所有 SOP 名称列表"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {
            'sop-a': {'name': 'sop-a', 'description': 'A'},
            'sop-b': {'name': 'sop-b', 'description': 'B'},
        }

        result = loader.list_sops()
        self.assertEqual(set(result), {'sop-a', 'sop-b'})

    def test_empty_metadata(self):
        """空元数据返回空列表"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {}

        result = loader.list_sops()
        self.assertEqual(result, [])


class TestGetSopMetadata(unittest.TestCase):
    """测试 SopLoader.get_sop_metadata()"""

    def setUp(self):
        """每个测试前重置类级别状态"""
        from agents.skill_loader import SopLoader
        SopLoader._extra_sops_dirs = []

    def test_existing_sop(self):
        """获取存在的 SOP 元数据"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {
            'test-sop': {'name': 'test-sop', 'description': '测试'}
        }

        result = loader.get_sop_metadata('test-sop')
        self.assertEqual(result['name'], 'test-sop')
        self.assertEqual(result['description'], '测试')

    def test_non_existing_sop(self):
        """获取不存在的 SOP 返回 None"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {}

        result = loader.get_sop_metadata('non-existing')
        self.assertIsNone(result)


class TestBuildSopsIndex(unittest.TestCase):
    """测试 SopLoader.build_sops_index()"""

    def setUp(self):
        """每个测试前重置类级别状态"""
        from agents.skill_loader import SopLoader
        SopLoader._extra_sops_dirs = []

    def test_build_index_with_sops(self):
        """构建包含多个 SOP 的索引"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {
            'sop-a': {'name': 'sop-a', 'description': '描述A'},
            'sop-b': {'name': 'sop-b', 'description': '描述B'},
        }

        result = loader.build_sops_index()

        self.assertIn('| SOP 名称 | 描述 |', result)
        self.assertIn('| sop-a | 描述A |', result)
        self.assertIn('| sop-b | 描述B |', result)

    def test_build_index_empty(self):
        """空元数据返回空字符串"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {}

        result = loader.build_sops_index()
        self.assertEqual(result, '')

    def test_build_index_missing_description(self):
        """缺少描述时显示默认文本"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {
            'sop-a': {'name': 'sop-a'}
        }

        result = loader.build_sops_index()
        self.assertIn('| sop-a | 无描述 |', result)


class TestGetSopContent(unittest.TestCase):
    """测试 SopLoader.get_sop_content()"""

    def setUp(self):
        """每个测试前重置类级别状态"""
        from agents.skill_loader import SopLoader
        SopLoader._extra_sops_dirs = []

    def test_load_content_with_front_matter(self):
        """加载包含 front matter 的 SOP 内容"""
        from agents.skill_loader import SopLoader
        content = """---
name: test-sop
description: 测试
---

# SOP 正文内容
这是正文
"""
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {
            'test-sop': {'name': 'test-sop', 'file': '/path/to/sop.md'}
        }

        with patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.read_text', return_value=content):
            result = loader.get_sop_content('test-sop')

        self.assertIn('# SOP 正文内容', result)
        self.assertIn('这是正文', result)
        self.assertNotIn('---', result)

    def test_load_content_without_front_matter(self):
        """加载没有 front matter 的 SOP 内容"""
        from agents.skill_loader import SopLoader
        content = """# SOP 正文内容
这是正文
"""
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {
            'test-sop': {'name': 'test-sop', 'file': '/path/to/sop.md'}
        }

        with patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.read_text', return_value=content):
            result = loader.get_sop_content('test-sop')

        self.assertEqual(result, content.strip())

    def test_non_existing_sop(self):
        """不存在的 SOP 返回 None"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {}

        result = loader.get_sop_content('non-existing')
        self.assertIsNone(result)

    def test_non_existing_file(self):
        """文件不存在返回 None"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {
            'test-sop': {'name': 'test-sop', 'file': '/path/to/non-existing.md'}
        }

        with patch('pathlib.Path.exists', return_value=False):
            result = loader.get_sop_content('test-sop')

        self.assertIsNone(result)


class TestGetSopTools(unittest.TestCase):
    """测试 SopLoader.get_sop_tools()"""

    def setUp(self):
        """每个测试前重置类级别状态"""
        from agents.skill_loader import SopLoader
        SopLoader._extra_sops_dirs = []

    def test_get_tools_from_config(self):
        """从配置获取工具列表"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_config = {
            'test-sop': {'allowed_tools': ['tool1', 'tool2']}
        }

        result = loader.get_sop_tools('test-sop')
        self.assertEqual(result, ['tool1', 'tool2'])

    def test_no_config_returns_empty(self):
        """无配置返回空列表"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_config = {}

        result = loader.get_sop_tools('test-sop')
        self.assertEqual(result, [])


class TestAddSopsDir(unittest.TestCase):
    """测试 SopLoader.add_sops_dir()"""

    def setUp(self):
        """每个测试前重置类级别状态"""
        from agents.skill_loader import SopLoader
        SopLoader._extra_sops_dirs = []

    @patch('pathlib.Path.exists', return_value=True)
    @patch('pathlib.Path.is_dir', return_value=True)
    def test_add_valid_dir(self, mock_is_dir, mock_exists):
        """添加有效目录"""
        from agents.skill_loader import SopLoader
        SopLoader.add_sops_dir('/path/to/extra/sops')
        self.assertEqual(len(SopLoader._extra_sops_dirs), 1)

    @patch('pathlib.Path.exists', return_value=False)
    def test_add_non_existing_dir(self, mock_exists):
        """添加不存在的目录不生效"""
        from agents.skill_loader import SopLoader
        SopLoader.add_sops_dir('/path/to/non-existing')
        self.assertEqual(len(SopLoader._extra_sops_dirs), 0)

    @patch('pathlib.Path.exists', return_value=True)
    @patch('pathlib.Path.is_dir', return_value=False)
    def test_add_file_path(self, mock_is_dir, mock_exists):
        """添加文件路径不生效"""
        from agents.skill_loader import SopLoader
        SopLoader.add_sops_dir('/path/to/file.txt')
        self.assertEqual(len(SopLoader._extra_sops_dirs), 0)

    @patch('pathlib.Path.exists', return_value=True)
    @patch('pathlib.Path.is_dir', return_value=True)
    def test_add_duplicate_dir(self, mock_is_dir, mock_exists):
        """重复添加同一目录不生效"""
        from agents.skill_loader import SopLoader
        SopLoader.add_sops_dir('/path/to/extra/sops')
        SopLoader.add_sops_dir('/path/to/extra/sops')
        self.assertEqual(len(SopLoader._extra_sops_dirs), 1)


class TestLoadSkillWithIndex(unittest.TestCase):
    """测试 SopLoader.load_skill_with_index()"""

    def setUp(self):
        """每个测试前重置类级别状态"""
        from agents.skill_loader import SopLoader
        SopLoader._extra_sops_dirs = []

    def test_replace_placeholder(self):
        """替换 {{SOP_INDEX}} 占位符"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {
            'sop-a': {'name': 'sop-a', 'description': '描述A'}
        }

        skill_content = """# 技能内容

可用的 SOP：
{{SOP_INDEX}}

请根据上述 SOP 执行任务。
"""
        result = loader.load_skill_with_index(skill_content)

        self.assertNotIn('{{SOP_INDEX}}', result)
        self.assertIn('| sop-a | 描述A |', result)

    def test_no_placeholder(self):
        """没有占位符时返回原内容"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {}

        skill_content = "# 技能内容\n没有占位符"
        result = loader.load_skill_with_index(skill_content)

        self.assertEqual(result, skill_content)

    def test_empty_metadata(self):
        """空元数据时替换为空字符串"""
        from agents.skill_loader import SopLoader
        loader = SopLoader.__new__(SopLoader)
        loader.sops_metadata = {}

        skill_content = "内容\n{{SOP_INDEX}}\n结束"
        result = loader.load_skill_with_index(skill_content)

        self.assertNotIn('{{SOP_INDEX}}', result)
        self.assertIn('内容', result)
        self.assertIn('结束', result)


class TestIncludeExtraSopsSwitch(unittest.TestCase):
    """测试 include_extra_sops 开关：剧本链路（False）与企业版额外 SOP 目录完全隔离"""

    def setUp(self):
        """每个测试前重置类级别状态"""
        from agents.skill_loader import SopLoader
        SopLoader._extra_sops_dirs = []

        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        base = Path(self._tmp.name)
        self.main_dir = base / 'main_sops'
        self.extra_dir = base / 'extra_sops'
        self.main_dir.mkdir()
        self.extra_dir.mkdir()

        (self.main_dir / 'sop-a.md').write_text(
            '---\nname: sop-a\ndescription: 主目录A\n---\n\n# 主目录A\n', encoding='utf-8'
        )
        # 额外目录：新增 sop-b + 覆盖同名 sop-a（模拟企业版）
        (self.extra_dir / 'sop-a.md').write_text(
            '---\nname: sop-a\ndescription: 企业版A\n---\n\n# 企业版A\n', encoding='utf-8'
        )
        (self.extra_dir / 'sop-b.md').write_text(
            '---\nname: sop-b\ndescription: 企业版B\n---\n\n# 企业版B\n', encoding='utf-8'
        )

        from agents.skill_loader import SopLoader
        SopLoader.add_sops_dir(str(self.extra_dir))

    def test_isolated_loader_excludes_extra_sops(self):
        """include_extra_sops=False 时不合并额外目录：索引/列表/内容均不可见"""
        from agents.skill_loader import SopLoader
        loader = SopLoader(str(self.main_dir), include_extra_sops=False)

        self.assertEqual(loader.list_sops(), ['sop-a'])
        self.assertNotIn('sop-b', loader.build_sops_index())
        self.assertIsNone(loader.get_sop_content('sop-b'))
        # 同名覆盖也不生效，保留主目录版本
        self.assertIn('主目录A', loader.get_sop_content('sop-a'))

    def test_default_loader_merges_extra_sops(self):
        """默认 include_extra_sops=True 保持原行为：额外目录新增与同名覆盖均生效"""
        from agents.skill_loader import SopLoader
        loader = SopLoader(str(self.main_dir))

        self.assertEqual(set(loader.list_sops()), {'sop-a', 'sop-b'})
        index = loader.build_sops_index()
        self.assertIn('sop-b', index)
        self.assertIn('企业版A', loader.get_sop_content('sop-a'))

    def test_isolated_loader_load_skill_with_index(self):
        """include_extra_sops=False 时 {{SOP_INDEX}} 不含额外目录 SOP"""
        from agents.skill_loader import SopLoader
        loader = SopLoader(str(self.main_dir), include_extra_sops=False)

        result = loader.load_skill_with_index('| SOP 名称 |\n{{SOP_INDEX}}')
        self.assertIn('sop-a', result)
        self.assertNotIn('sop-b', result)


if __name__ == '__main__':
    unittest.main()
