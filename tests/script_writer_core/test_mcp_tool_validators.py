"""
MCP 工具校验函数单元测试

测试 validate_name_for_filename 和 validate_image_url 的纯函数逻辑，
以及 utils.media_mapping_util.normalize_site_upload_image_url 的归一化规则。

validate_image_url 语义（2026-11-14 13572 事故收敛）：LLM 图片参数只允许
本站 /upload/ 资源，校验通过时返回归一化后的相对路径（'url' 键）。
"""
import os
import sys
import unittest

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from script_writer_core.mcp_tool import validate_name_for_filename, validate_image_url
from utils.media_mapping_util import normalize_site_upload_image_url


class TestValidateNameForFilename(unittest.TestCase):
    """测试 validate_name_for_filename"""

    def test_valid_chinese_name(self):
        result = validate_name_for_filename("张三")
        self.assertTrue(result['valid'])
        self.assertEqual(result['cleaned_name'], '张三')
        self.assertIsNone(result['error'])

    def test_valid_english_name(self):
        result = validate_name_for_filename("Alice")
        self.assertTrue(result['valid'])
        self.assertEqual(result['cleaned_name'], 'Alice')

    def test_valid_mixed_name(self):
        result = validate_name_for_filename("Alice_张三.v2")
        self.assertTrue(result['valid'])
        self.assertEqual(result['cleaned_name'], 'Alice_张三.v2')

    def test_valid_with_underscore(self):
        result = validate_name_for_filename("user_name_001")
        self.assertTrue(result['valid'])
        self.assertEqual(result['cleaned_name'], 'user_name_001')

    def test_empty_name(self):
        result = validate_name_for_filename("")
        self.assertFalse(result['valid'])
        self.assertEqual(result['error'], '名称不能为空')
        self.assertEqual(result['cleaned_name'], '')

    def test_whitespace_only(self):
        result = validate_name_for_filename("   ")
        self.assertFalse(result['valid'])
        self.assertEqual(result['error'], '名称不能为空')

    def test_none_name(self):
        result = validate_name_for_filename(None)
        self.assertFalse(result['valid'])
        self.assertEqual(result['error'], '名称不能为空')

    def test_invalid_chars_with_suggestion(self):
        result = validate_name_for_filename("Alice@123")
        self.assertFalse(result['valid'])
        self.assertIn('只能包含中文', result['error'])
        self.assertEqual(result['cleaned_name'], 'Alice123')

    def test_all_invalid_chars(self):
        result = validate_name_for_filename("@#$%^")
        self.assertFalse(result['valid'])
        self.assertIn('必须包含至少一个', result['error'])
        self.assertEqual(result['cleaned_name'], '')

    def test_custom_field_name(self):
        result = validate_name_for_filename("", field_name="角色名称")
        self.assertIn('角色名称', result['error'])

    def test_space_in_name(self):
        result = validate_name_for_filename("Alice 123")
        self.assertFalse(result['valid'])
        self.assertEqual(result['cleaned_name'], 'Alice123')

    def test_number_only(self):
        result = validate_name_for_filename("12345")
        self.assertTrue(result['valid'])
        self.assertEqual(result['cleaned_name'], '12345')

    def test_chinese_number_mix(self):
        result = validate_name_for_filename("角色001")
        self.assertTrue(result['valid'])
        self.assertEqual(result['cleaned_name'], '角色001')


class TestNormalizeSiteUploadImageUrl(unittest.TestCase):
    """测试 normalize_site_upload_image_url 归一化规则"""

    def test_relative_path_unchanged(self):
        self.assertEqual(
            normalize_site_upload_image_url("/upload/asset_library/55/asset_55_1b64.png"),
            "/upload/asset_library/55/asset_55_1b64.png",
        )

    def test_absolute_url_stripped_to_relative(self):
        self.assertEqual(
            normalize_site_upload_image_url("https://api.ai-arts.com/upload/asset_library/55/x.png"),
            "/upload/asset_library/55/x.png",
        )
        self.assertEqual(
            normalize_site_upload_image_url("http://zjt-dev.perseids.cn:9003/upload/character/pic/abc.png"),
            "/upload/character/pic/abc.png",
        )
        # 协议相对与 file:// 同样剥掉前缀（语义仍是本站资源）
        self.assertEqual(normalize_site_upload_image_url("//host/upload/x.png"), "/upload/x.png")
        self.assertEqual(normalize_site_upload_image_url("file:///upload/x.png"), "/upload/x.png")

    def test_bare_relative_prefixed(self):
        self.assertEqual(normalize_site_upload_image_url("upload/x.png"), "/upload/x.png")

    def test_query_and_fragment_dropped(self):
        self.assertEqual(
            normalize_site_upload_image_url("https://host/upload/x.png?token=abc#frag"),
            "/upload/x.png",
        )

    def test_external_link_rejected(self):
        self.assertIsNone(normalize_site_upload_image_url("https://cdn.example.com/img.png"))
        self.assertIsNone(normalize_site_upload_image_url("http://example.com/image.jpg"))

    def test_non_http_scheme_with_upload_path_still_site_resource(self):
        # ftp/file 协议指向 /upload/ path：按域名无关语义剥成相对路径
        self.assertEqual(normalize_site_upload_image_url("ftp://host/upload/x.png"), "/upload/x.png")

    def test_local_disk_path_rejected(self):
        self.assertIsNone(normalize_site_upload_image_url("C:\\data\\x.png"))
        self.assertIsNone(normalize_site_upload_image_url("/etc/passwd"))
        self.assertIsNone(normalize_site_upload_image_url("/uploadx.png"))

    def test_traversal_rejected(self):
        self.assertIsNone(normalize_site_upload_image_url("/upload/../secret.png"))
        self.assertIsNone(normalize_site_upload_image_url("https://host/upload/%2e%2e/etc.png"))
        self.assertIsNone(normalize_site_upload_image_url("/upload/a/../../b.png"))

    def test_empty_and_invalid_input(self):
        self.assertIsNone(normalize_site_upload_image_url(""))
        self.assertIsNone(normalize_site_upload_image_url("   "))
        self.assertIsNone(normalize_site_upload_image_url(None))
        self.assertIsNone(normalize_site_upload_image_url(123))
        self.assertIsNone(normalize_site_upload_image_url("upload"))


class TestValidateImageUrl(unittest.TestCase):
    """测试 validate_image_url（只允许本站 /upload/ 资源，成功返回归一化 'url'）"""

    def test_valid_relative_upload_path(self):
        result = validate_image_url("/upload/asset_library/55/asset_55_1b64.png")
        self.assertTrue(result['valid'])
        self.assertIsNone(result['error'])
        self.assertEqual(result['url'], "/upload/asset_library/55/asset_55_1b64.png")

    def test_absolute_site_url_normalized(self):
        result = validate_image_url("https://api.ai-arts.com/upload/asset_library/55/x.png")
        self.assertTrue(result['valid'])
        self.assertEqual(result['url'], "/upload/asset_library/55/x.png")

    def test_valid_ip_with_upload_path(self):
        result = validate_image_url("http://192.168.1.1:9000/upload/abc.png")
        self.assertTrue(result['valid'])
        self.assertEqual(result['url'], "/upload/abc.png")

    def test_bare_relative_normalized(self):
        result = validate_image_url("upload/abc.png")
        self.assertTrue(result['valid'])
        self.assertEqual(result['url'], "/upload/abc.png")

    def test_external_link_rejected(self):
        result = validate_image_url("http://example.com/image.jpg")
        self.assertFalse(result['valid'])
        self.assertIn('仅支持本站', result['error'])

    def test_external_link_with_query_rejected(self):
        result = validate_image_url("https://cdn.example.com/path/to/image.png?v=123")
        self.assertFalse(result['valid'])

    def test_missing_protocol(self):
        result = validate_image_url("example.com/image.jpg")
        self.assertFalse(result['valid'])
        self.assertIn('仅支持本站', result['error'])

    def test_empty_string(self):
        result = validate_image_url("")
        self.assertFalse(result['valid'])

    def test_none_value(self):
        result = validate_image_url(None)
        self.assertFalse(result['valid'])
        self.assertIn('字符串类型', result['error'])

    def test_non_string_value(self):
        result = validate_image_url(12345)
        self.assertFalse(result['valid'])
        self.assertIn('字符串类型', result['error'])

    def test_invalid_url_format(self):
        result = validate_image_url("http://")
        self.assertFalse(result['valid'])
        self.assertIn('仅支持本站', result['error'])

    def test_custom_field_name(self):
        result = validate_image_url("https://example.com/a.jpg", field_name="reference_image")
        self.assertIn('reference_image', result['error'])

    def test_traversal_rejected(self):
        result = validate_image_url("/upload/../secret.png")
        self.assertFalse(result['valid'])


if __name__ == '__main__':
    unittest.main()
