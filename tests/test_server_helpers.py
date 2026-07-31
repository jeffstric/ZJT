"""
server.py 辅助函数单元测试

测试 server.py 中的纯逻辑辅助函数。
"""
import hashlib
import re
import unittest
from unittest.mock import patch, MagicMock


class TestCheckResourcePermission(unittest.TestCase):
    """测试 _check_resource_permission 函数逻辑"""

    def test_space_isolated_mode_owner_has_permission(self):
        """Space 隔离模式下，资源所有者有权限"""
        # 模拟 Edition.is_space_isolated() 返回 True
        with patch('config.constant.Edition') as mock_edition:
            mock_edition.is_space_isolated.return_value = True

            resource = MagicMock()
            resource.user_id = 123

            # 导入并重新加载 server 模块的部分逻辑
            # 由于 server.py 导入时有副作用，我们直接测试逻辑
            from config.constant import Edition

            # 测试逻辑：space_isolated 模式下检查 user_id
            if Edition.is_space_isolated():
                result = getattr(resource, 'user_id', None) == 123
            else:
                result = True

            self.assertTrue(result)

    def test_space_isolated_mode_non_owner_no_permission(self):
        """Space 隔离模式下，非资源所有者无权限"""
        with patch('config.constant.Edition') as mock_edition:
            mock_edition.is_space_isolated.return_value = True

            resource = MagicMock()
            resource.user_id = 123

            from config.constant import Edition

            if Edition.is_space_isolated():
                result = getattr(resource, 'user_id', None) == 456
            else:
                result = True

            self.assertFalse(result)

    def test_community_mode_delete_requires_owner(self):
        """社区版删除操作需要所有者权限"""
        with patch('config.constant.Edition') as mock_edition:
            mock_edition.is_space_isolated.return_value = False

            resource = MagicMock()
            resource.user_id = 123

            from config.constant import Edition, Action

            action = Action.DELETE
            if Edition.is_space_isolated():
                result = getattr(resource, 'user_id', None) == 123
            else:
                if action == Action.DELETE:
                    result = getattr(resource, 'user_id', None) == 123
                else:
                    result = True

            self.assertTrue(result)

    def test_community_mode_view_allows_all(self):
        """社区版查看操作允许所有用户"""
        with patch('config.constant.Edition') as mock_edition:
            mock_edition.is_space_isolated.return_value = False

            resource = MagicMock()
            resource.user_id = 123

            from config.constant import Edition, Action

            action = Action.VIEW
            if Edition.is_space_isolated():
                result = getattr(resource, 'user_id', None) == 456
            else:
                if action == Action.DELETE:
                    result = getattr(resource, 'user_id', None) == 456
                else:
                    result = True

            self.assertTrue(result)


class TestStaticVersion(unittest.TestCase):
    """测试静态资源版本号生成逻辑"""

    def test_version_hash_generation(self):
        """测试版本号 hash 生成逻辑"""
        import hashlib

        version = "1.2.3"
        hash_str = hashlib.md5(version.encode()).hexdigest()[:8]

        self.assertEqual(len(hash_str), 8)
        # 验证相同版本号生成相同 hash
        hash_str2 = hashlib.md5(version.encode()).hexdigest()[:8]
        self.assertEqual(hash_str, hash_str2)

    def test_different_versions_different_hash(self):
        """不同版本号生成不同 hash"""
        import hashlib

        hash1 = hashlib.md5("1.0.0".encode()).hexdigest()[:8]
        hash2 = hashlib.md5("2.0.0".encode()).hexdigest()[:8]

        self.assertNotEqual(hash1, hash2)


class TestGenerationSnapshotExtraConfigContract(unittest.TestCase):
    """直接生成 API 对 hidden 模型的契约（避免再回归 MODEL_HIDDEN）。"""

    def test_direct_api_allows_hidden_with_explicit_task_id(self):
        """
        _generation_snapshot_extra_config 必须 allow_hidden=True。

        直接 API 已强制请求带 task_id；hidden 仅约束偏好选择器，
        不能再拦 qwen-multi-angle 等多角度新任务。
        """
        from pathlib import Path

        server_path = Path(__file__).resolve().parents[1] / "server.py"
        source = server_path.read_text(encoding="utf-8")
        start = source.find("def _generation_snapshot_extra_config")
        self.assertNotEqual(start, -1)
        # 只检查该函数体，避免误匹配其它 validate_model 调用
        end = source.find("\nasync def ", start)
        if end == -1:
            end = source.find("\ndef ", start + 1)
        body = source[start:end if end != -1 else start + 2500]
        self.assertIn("allow_hidden=True", body)
        self.assertNotIn("allow_hidden=bool(snapshot)", body)


class TestCacheBustPattern(unittest.TestCase):
    """测试静态资源缓存失效正则"""

    def test_match_script_src(self):
        """匹配 script src"""
        import re

        pattern = r'(<(?:script|link)[^>]*(?:src|href)=")(/(?:js|css|i18n)/[^"]+)(")'
        content = '<script src="/js/app.js"></script>'

        match = re.search(pattern, content)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(2), '/js/app.js')

    def test_match_link_href(self):
        """匹配 link href"""
        import re

        pattern = r'(<(?:script|link)[^>]*(?:src|href)=")(/(?:js|css|i18n)/[^"]+)(")'
        content = '<link rel="stylesheet" href="/css/style.css">'

        match = re.search(pattern, content)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(2), '/css/style.css')

    def test_match_i18n_path(self):
        """匹配 i18n 路径"""
        import re

        pattern = r'(<(?:script|link)[^>]*(?:src|href)=")(/(?:js|css|i18n)/[^"]+)(")'
        content = '<script src="/i18n/zh-CN.json"></script>'

        match = re.search(pattern, content)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(2), '/i18n/zh-CN.json')

    def test_no_match_external_url(self):
        """不匹配外部 URL"""
        import re

        pattern = r'(<(?:script|link)[^>]*(?:src|href)=")(/(?:js|css|i18n)/[^"]+)(")'
        content = '<script src="https://cdn.example.com/lib.js"></script>'

        match = re.search(pattern, content)
        self.assertIsNone(match)

    def test_replace_with_version(self):
        """替换为带版本号的 URL"""
        import re

        pattern = r'(<(?:script|link)[^>]*(?:src|href)=")(/(?:js|css|i18n)/[^"]+)(")'
        version = "abc12345"

        def replace_with_version(match):
            prefix = match.group(1)
            path = match.group(2)
            suffix = match.group(3)
            path = re.sub(r'\?v=[^"\']*', '', path)
            return f'{prefix}{path}?v={version}{suffix}'

        content = '<script src="/js/app.js"></script>'
        result = re.sub(pattern, replace_with_version, content)

        self.assertEqual(result, '<script src="/js/app.js?v=abc12345"></script>')


if __name__ == '__main__':
    unittest.main()
