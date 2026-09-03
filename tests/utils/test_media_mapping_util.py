"""
media_mapping_util 单元测试

测试 extract_local_path_from_url 的纯函数逻辑，
以及 ensure_entity_image_mapping、ensure_character_image_mapping 等映射创建逻辑。
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock 依赖模块
_saved_modules = {
    'utils.project_path': sys.modules.get('utils.project_path'),
    'model.database': sys.modules.get('model.database'),
    'config.config_util': sys.modules.get('config.config_util'),
    'config.media_file_policy': sys.modules.get('config.media_file_policy'),
    'model.media_file_mapping': sys.modules.get('model.media_file_mapping'),
    'model.character': sys.modules.get('model.character'),
    'utils.cdn_util': sys.modules.get('utils.cdn_util'),
    'utils.mime_type': sys.modules.get('utils.mime_type'),
}

sys.modules['utils.project_path'] = MagicMock()
sys.modules['model.database'] = MagicMock()
sys.modules['config.config_util'] = MagicMock()
sys.modules['config.media_file_policy'] = MagicMock()
sys.modules['model.media_file_mapping'] = MagicMock()
sys.modules['model.character'] = MagicMock()
sys.modules['utils.cdn_util'] = MagicMock()
sys.modules['utils.mime_type'] = MagicMock()

from utils.media_mapping_util import (
    extract_local_path_from_url,
    ensure_entity_image_mapping,
    ensure_character_image_mapping,
)


class TestExtractLocalPathFromUrl(unittest.TestCase):
    """测试 extract_local_path_from_url()"""

    def test_localhost_url(self):
        """本地 URL 提取路径"""
        result = extract_local_path_from_url("http://localhost:8000/upload/character/pic/abc.png")
        self.assertEqual(result, "upload/character/pic/abc.png")

    def test_ip_url(self):
        """IP 地址 URL 提取路径"""
        result = extract_local_path_from_url("http://192.168.1.1:9000/upload/character/voice/rh_voice.wav")
        self.assertEqual(result, "upload/character/voice/rh_voice.wav")

    def test_relative_path(self):
        """以 /upload/ 开头的相对路径"""
        result = extract_local_path_from_url("/upload/character/pic/abc.png")
        self.assertEqual(result, "upload/character/pic/abc.png")

    def test_external_cdn_url(self):
        """外部 CDN URL 返回 None"""
        result = extract_local_path_from_url("https://external-cdn.com/image.png")
        self.assertIsNone(result)

    def test_http_external_url(self):
        """HTTP 外部 URL（不含 /upload/ 前缀）返回 None"""
        result = extract_local_path_from_url("http://example.com/other/path/image.png")
        self.assertIsNone(result)

    def test_empty_string(self):
        """空字符串返回 None"""
        result = extract_local_path_from_url("")
        self.assertIsNone(result)

    def test_none_input(self):
        """None 输入返回 None"""
        result = extract_local_path_from_url(None)
        self.assertIsNone(result)

    def test_non_string_input(self):
        """非字符串输入返回 None"""
        result = extract_local_path_from_url(12345)
        self.assertIsNone(result)

    def test_url_with_query_params(self):
        """带查询参数的本地 URL"""
        result = extract_local_path_from_url("http://localhost:8000/upload/img/a.png?v=1&t=2")
        self.assertEqual(result, "upload/img/a.png")

    def test_upload_only_path(self):
        """只有 /upload/ 前缀但无后续路径"""
        result = extract_local_path_from_url("/upload/")
        self.assertEqual(result, "upload/")

    def test_rejects_parent_directory_traversal(self):
        self.assertIsNone(extract_local_path_from_url("/upload/../pyproject.toml"))

    def test_rejects_encoded_parent_directory_traversal(self):
        self.assertIsNone(extract_local_path_from_url("/upload/%2e%2e/pyproject.toml"))

    def test_rejects_windows_separator_traversal(self):
        self.assertIsNone(extract_local_path_from_url(r"/upload/..\pyproject.toml"))

    def test_path_not_starting_with_upload(self):
        """路径不以 /upload/ 开头返回 None"""
        result = extract_local_path_from_url("http://localhost:8000/static/image.png")
        self.assertIsNone(result)

    def test_deep_nested_path(self):
        """深层嵌套路径"""
        result = extract_local_path_from_url("http://localhost:8000/upload/a/b/c/d/file.jpg")
        self.assertEqual(result, "upload/a/b/c/d/file.jpg")


class TestEnsureEntityImageMapping(unittest.TestCase):
    """测试 ensure_entity_image_mapping()"""

    @patch('config.config_util.get_config')
    def test_cdn_disabled_returns_none(self, mock_get_config):
        """CDN 未启用时返回 None"""
        mock_get_config.return_value = {'server': {'auto_upload_to_cdn': False}}

        result = ensure_entity_image_mapping(
            user_id=1, image_url='http://localhost:8000/upload/char/pic/a.png',
            entity_type=1, entity_id=10
        )
        self.assertIsNone(result)

    @patch('config.config_util.get_config')
    def test_external_url_returns_none(self, mock_get_config):
        """外部 URL（无法提取本地路径）返回 None"""
        mock_get_config.return_value = {'server': {'auto_upload_to_cdn': True}}

        result = ensure_entity_image_mapping(
            user_id=1, image_url='https://external-cdn.com/img.png',
            entity_type=1, entity_id=10
        )
        self.assertIsNone(result)

    @patch('utils.cdn_util.CDNUtil')
    @patch('utils.mime_type.get_mime_type_from_extension', return_value='image/png')
    @patch('model.media_file_mapping.MediaFileMappingModel')
    @patch('config.config_util.get_config')
    def test_same_path_skips(self, mock_get_config, MockMapping, mock_mime, MockCDN):
        """已有 mapping 且 local_path 相同时跳过，返回已有 ID"""
        mock_get_config.return_value = {'server': {'auto_upload_to_cdn': True}}

        existing = MagicMock()
        existing.id = 42
        existing.local_path = 'upload/char/pic/a.png'
        MockMapping.get_by_entity_and_label.return_value = existing

        result = ensure_entity_image_mapping(
            user_id=1,
            image_url='http://localhost:8000/upload/char/pic/a.png',
            entity_type=1, entity_id=10, label='image'
        )
        self.assertEqual(result, 42)
        MockMapping.create.assert_not_called()

    @patch('utils.cdn_util.CDNUtil')
    @patch('utils.mime_type.get_mime_type_from_extension', return_value='image/png')
    @patch('model.media_file_mapping.MediaFileMappingModel')
    @patch('config.media_file_policy.MediaFilePolicy', NEVER_EXPIRE='never_expire')
    @patch('config.config_util.get_config')
    def test_different_path_deletes_old_creates_new(
        self, mock_get_config, MockPolicy, MockMapping, mock_mime, MockCDN
    ):
        """已有 mapping 但 local_path 不同时，删旧建新"""
        mock_get_config.return_value = {'server': {'auto_upload_to_cdn': True}}

        existing = MagicMock()
        existing.id = 10
        existing.local_path = 'upload/char/pic/old.png'
        MockMapping.get_by_entity_and_label.return_value = existing
        MockMapping.create.return_value = 99

        result = ensure_entity_image_mapping(
            user_id=1,
            image_url='http://localhost:8000/upload/char/pic/new.png',
            entity_type=1, entity_id=10, label='image'
        )
        self.assertEqual(result, 99)
        MockMapping.delete_by_local_path.assert_called_once_with('upload/char/pic/old.png')
        MockMapping.create.assert_called_once()
        MockCDN.trigger_cdn_upload.assert_called_once()

    @patch('utils.cdn_util.CDNUtil')
    @patch('utils.mime_type.get_mime_type_from_extension', return_value='image/png')
    @patch('model.media_file_mapping.MediaFileMappingModel')
    @patch('config.media_file_policy.MediaFilePolicy', NEVER_EXPIRE='never_expire')
    @patch('config.config_util.get_config')
    def test_no_existing_mapping_creates_new(
        self, mock_get_config, MockPolicy, MockMapping, mock_mime, MockCDN
    ):
        """无已有 mapping 时直接创建新的"""
        mock_get_config.return_value = {'server': {'auto_upload_to_cdn': True}}
        MockMapping.get_by_entity_and_label.return_value = None
        MockMapping.create.return_value = 55

        result = ensure_entity_image_mapping(
            user_id=1,
            image_url='http://localhost:8000/upload/char/pic/first.png',
            entity_type=1, entity_id=10, label='image'
        )
        self.assertEqual(result, 55)
        MockMapping.delete_by_local_path.assert_not_called()

    @patch('utils.cdn_util.CDNUtil')
    @patch('utils.mime_type.get_mime_type_from_extension', return_value='image/png')
    @patch('model.media_file_mapping.MediaFileMappingModel')
    @patch('config.media_file_policy.MediaFilePolicy', NEVER_EXPIRE='never_expire')
    @patch('config.config_util.get_config')
    def test_user_id_none(self, mock_get_config, MockPolicy, MockMapping, mock_mime, MockCDN):
        """user_id 为 None 时 uid 设为 None"""
        mock_get_config.return_value = {'server': {'auto_upload_to_cdn': True}}
        MockMapping.get_by_entity_and_label.return_value = None
        MockMapping.create.return_value = 77

        result = ensure_entity_image_mapping(
            user_id=None,
            image_url='http://localhost:8000/upload/char/pic/a.png',
            entity_type=1, entity_id=10, label='image'
        )
        self.assertEqual(result, 77)
        call_kwargs = MockMapping.create.call_args.kwargs
        self.assertIsNone(call_kwargs['user_id'])


class TestEnsureCharacterImageMapping(unittest.TestCase):
    """测试 ensure_character_image_mapping()"""

    @patch('model.character.CharacterModel')
    def test_invalid_world_id_returns_none(self, MockCharModel):
        """无效 world_id 返回 None"""
        result = ensure_character_image_mapping(
            user_id=1, world_id='not_a_number',
            character_name='Alice', image_url='http://localhost/upload/char/pic/a.png'
        )
        self.assertIsNone(result)
        MockCharModel.get_by_name.assert_not_called()

    @patch('model.character.CharacterModel')
    def test_character_not_found_returns_none(self, MockCharModel):
        """角色不存在返回 None"""
        MockCharModel.get_by_name.return_value = None

        result = ensure_character_image_mapping(
            user_id=1, world_id=1,
            character_name='NonExistent', image_url='http://localhost/upload/char/pic/a.png'
        )
        self.assertIsNone(result)

    @patch('utils.media_mapping_util.ensure_entity_image_mapping')
    @patch('model.character.CharacterModel')
    def test_character_found_delegates_to_entity(self, MockCharModel, mock_ensure):
        """角色存在时委托给 ensure_entity_image_mapping"""
        char = MagicMock()
        char.id = 42
        MockCharModel.get_by_name.return_value = char
        mock_ensure.return_value = 100

        result = ensure_character_image_mapping(
            user_id=1, world_id=1,
            character_name='Alice', image_url='http://localhost/upload/char/pic/a.png'
        )
        self.assertEqual(result, 100)
        mock_ensure.assert_called_once()


# 恢复 sys.modules
for _key, _orig in _saved_modules.items():
    if _orig is not None:
        sys.modules[_key] = _orig
    else:
        sys.modules.pop(_key, None)


if __name__ == '__main__':
    unittest.main()
