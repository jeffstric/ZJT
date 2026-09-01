# -*- coding: utf-8 -*-
"""VL 共享网关（services/vl_gateway.py）单元测试。

覆盖三处 VL 链路（画风识别 / 导演台估参 / 图片描述）共用能力：
模型挑选排序、图片 URL → base64（本站/远程开关/非法来源）、VL 调用与超时。
"""
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services import vl_gateway  # noqa: E402

_VL_MODELS = {"models": [
    {"name": "gemini-3-pro", "vendor_id": 7, "vendor_name": "jiekou", "supports_vl": True, "model_id": 71},
    {"name": "doubao-seed-2-0-lite", "vendor_id": 3, "vendor_name": "volcengine", "supports_vl": True, "model_id": 31},
    {"name": "deepseek-chat", "vendor_id": 4, "vendor_name": "deepseek", "supports_vl": False, "model_id": 41},
]}


def _llm_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class TestPickVlModel(unittest.TestCase):
    def test_filters_non_vl_and_prefers_configured(self):
        with patch("services.vl_gateway.get_available_models", return_value=_VL_MODELS):
            picked = asyncio.run(vl_gateway.pick_vl_model("volcengine", "doubao-seed-2-0-lite"))
        self.assertEqual(picked["name"], "doubao-seed-2-0-lite")

    def test_no_vl_models_returns_none(self):
        with patch("services.vl_gateway.get_available_models", return_value={"models": _VL_MODELS["models"][2:]}):
            self.assertIsNone(asyncio.run(vl_gateway.pick_vl_model("volcengine", "doubao-seed-2-0-lite")))

    def test_explicit_model_exact_match(self):
        with patch("services.vl_gateway.get_available_models", return_value=_VL_MODELS):
            picked = asyncio.run(vl_gateway.pick_vl_model("volcengine", "doubao-seed-2-0-lite", model="gemini-3-pro"))
        self.assertEqual(picked["name"], "gemini-3-pro")

    def test_explicit_model_with_vendor_filter(self):
        # 指定模型存在但 vendor 不匹配 → 回落偏好模型
        with patch("services.vl_gateway.get_available_models", return_value=_VL_MODELS):
            picked = asyncio.run(vl_gateway.pick_vl_model(
                "volcengine", "doubao-seed-2-0-lite", model="gemini-3-pro", vendor_id=3))
        self.assertEqual(picked["name"], "doubao-seed-2-0-lite")


class TestImageUrlToBase64(unittest.TestCase):
    def test_local_upload_path_uses_local_compress(self):
        with patch("services.vl_gateway.resolve_upload_path",
                   return_value=("/srv/upload/a.png", None)), \
             patch("services.vl_gateway.compress_local_image_to_base64",
                   return_value=(True, "data:image/jpeg;base64,local", None)):
            ok, data_url, err = asyncio.run(vl_gateway.image_url_to_base64(
                "http://host/upload/a.png", compress_timeout=15))
        self.assertTrue(ok)
        self.assertEqual(data_url, "data:image/jpeg;base64,local")

    def test_remote_url_blocked_by_default(self):
        # allow_remote 默认 False：远程 URL 一律拒绝（画风识别的安全边界）
        with patch("services.vl_gateway.resolve_upload_path",
                   return_value=(None, "图片文件不存在")):
            ok, data_url, err = asyncio.run(vl_gateway.image_url_to_base64(
                "https://cdn.example.com/a.png", compress_timeout=15))
        self.assertFalse(ok)
        self.assertIn("不存在", err)

    def test_remote_url_allowed_when_opted_in(self):
        async def fake_download(url, max_mb, max_px):
            return (True, "data:image/jpeg;base64,remote", None)

        with patch("services.vl_gateway.resolve_upload_path",
                   return_value=(None, "图片文件不存在")), \
             patch("services.vl_gateway.async_download_and_compress_to_base64", fake_download):
            ok, data_url, err = asyncio.run(vl_gateway.image_url_to_base64(
                "https://cdn.example.com/a.png", compress_timeout=15, allow_remote=True))
        self.assertTrue(ok)
        self.assertEqual(data_url, "data:image/jpeg;base64,remote")

    def test_local_compress_timeout(self):
        with patch("services.vl_gateway.resolve_upload_path",
                   return_value=("/srv/upload/a.png", None)), \
             patch("services.vl_gateway.compress_local_image_to_base64",
                   side_effect=lambda *a: asyncio.sleep(30)):
            ok, data_url, err = asyncio.run(vl_gateway.image_url_to_base64(
                "upload/a.png", compress_timeout=0))
        self.assertFalse(ok)
        self.assertIn("压缩超时", err)


class TestCallVl(unittest.TestCase):
    def _run(self, client, llm_timeout=60):
        with patch("services.vl_gateway.get_llm_client", return_value=client):
            return asyncio.run(vl_gateway.call_vl(
                "SYS", "USER", "data:image/jpeg;base64,xx",
                model="doubao-seed-2-0-lite",
                llm_timeout=llm_timeout,
                vendor_id=3,
                model_id=31,
                auth_token="tok",
            ))

    def test_success_returns_content(self):
        client = SimpleNamespace(call_api=lambda **kw: _llm_response("一段描述"))
        ok, content, err = self._run(client)
        self.assertTrue(ok)
        self.assertEqual(content, "一段描述")
        self.assertIsNone(err)

    def test_call_kwargs_forwarded(self):
        captured = {}

        def call_api(**kwargs):
            captured.update(kwargs)
            return _llm_response("x")

        self._run(SimpleNamespace(call_api=call_api))
        self.assertEqual(captured["model"], "doubao-seed-2-0-lite")
        self.assertEqual(captured["vendor_id"], 3)
        self.assertEqual(captured["model_id"], 31)
        self.assertEqual(captured["auth_token"], "tok")
        self.assertEqual(captured["temperature"], 0.3)

    def test_timeout_returns_error(self):
        import time

        def slow(**kwargs):
            time.sleep(30)

        ok, content, err = self._run(SimpleNamespace(call_api=slow), llm_timeout=0)
        self.assertFalse(ok)
        self.assertIn("超时", err)

    def test_call_exception_returns_error(self):
        def boom(**kwargs):
            raise RuntimeError("boom")

        ok, content, err = self._run(SimpleNamespace(call_api=boom))
        self.assertFalse(ok)
        self.assertIn("调用失败", err)

    def test_empty_reply_returns_error(self):
        ok, content, err = self._run(SimpleNamespace(call_api=lambda **kw: _llm_response("  ")))
        self.assertFalse(ok)
        self.assertIn("为空", err)


if __name__ == "__main__":
    unittest.main()
