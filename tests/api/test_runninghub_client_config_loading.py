"""runninghub_client 的 v2 任务函数需要读取 YAML 配置文件。

回归：模块缺少 ``import os`` / ``import yaml``，导致 create_ltx2_image_to_video 等函数在读取配置时
抛出 NameError，而不是 FileNotFoundError 或正常请求。
"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from api.clients import runninghub_client as client


class TestRunningHubConfigLoading(unittest.TestCase):

    def test_missing_config_raises_file_not_found(self):
        missing = os.path.join(tempfile.gettempdir(), "runninghub-config-that-does-not-exist.yml")
        for func in (
            client.create_ltx2_image_to_video,
            client.create_wan22_image_to_video,
        ):
            with self.subTest(func=func.__name__):
                with self.assertRaises(FileNotFoundError):
                    func("https://example.com/a.png", "prompt", config_path=missing) \
                        if func is client.create_wan22_image_to_video \
                        else func("https://example.com/a.png", config_path=missing)

    def test_default_config_path_is_resolved_through_get_config_path(self):
        missing = os.path.join(tempfile.gettempdir(), "runninghub-config-that-does-not-exist.yml")
        with patch.object(client, "get_config_path", return_value=missing) as resolver:
            with self.assertRaises(FileNotFoundError):
                client.create_ltx2_image_to_video("https://example.com/a.png")
        resolver.assert_called_once_with()

    def test_ltx2_reads_yaml_config_and_posts_to_configured_host(self):
        config_text = (
            "runninghub:\n"
            "  api_key: key-from-config\n"
            "  host: https://rh.test\n"
            "timeout:\n"
            "  request_timeout: 5\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.yml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(config_text)
            response = MagicMock()
            response.json.return_value = {"code": 0}
            with patch.object(client.requests, "post", return_value=response) as post:
                result = client.create_ltx2_image_to_video(
                    "https://example.com/a.png", webapp_id="123", config_path=path
                )

        self.assertEqual(result, {"code": 0})
        url = post.call_args.args[0]
        self.assertEqual(url, "https://rh.test/openapi/v2/run/ai-app/123")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer key-from-config")


if __name__ == "__main__":
    unittest.main()
