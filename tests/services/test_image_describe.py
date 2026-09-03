# -*- coding: utf-8 -*-
"""图片描述服务（VL 识图生成场景描述）单元测试。

重构后模型挑选/图片获取/VL 调用由 services/vl_gateway.py 共享网关提供
（网关自身的行为在 test_vl_gateway.py 覆盖），本文件聚焦：
描述清洗 + describe_image 业务编排（网关各环节的成功/失败映射）。
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.image_describe import _clean_description, describe_image  # noqa: E402

_PICKED = {"name": "doubao-seed-2-0-lite", "vendor_id": 3, "model_id": 31}


def _gateway_ok():
    """打桩网关三环节全部成功，VL 返回『湖边雪山』。"""
    return [
        patch("services.image_describe.pick_vl_model", return_value=_PICKED),
        patch("services.image_describe.image_url_to_base64",
              return_value=(True, "data:image/jpeg;base64,xx", None)),
        patch("services.image_describe.call_vl",
              return_value=(True, "湖边雪山", None)),
    ]


class TestCleanDescription(unittest.TestCase):
    """_clean_description: 模型回复容错清洗。"""

    def test_plain_text_passthrough(self):
        self.assertEqual(_clean_description("夕阳下的雪山湖泊，四周环山"), "夕阳下的雪山湖泊，四周环山")

    def test_strips_code_fence(self):
        self.assertEqual(_clean_description("```json\n湖边雪山\n```"), "湖边雪山")

    def test_strips_wrapping_quotes(self):
        self.assertEqual(_clean_description('"湖边雪山"'), "湖边雪山")

    def test_multiline_collapsed_to_single_paragraph(self):
        self.assertEqual(_clean_description("第一行\n第二行"), "第一行，第二行")

    def test_empty(self):
        self.assertEqual(_clean_description(""), "")
        self.assertEqual(_clean_description(None), "")


class TestDescribeImage(unittest.TestCase):
    """describe_image: 业务编排与网关失败映射。"""

    def _run(self, patches):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            return asyncio.run(describe_image("http://host/upload/a.png", auth_token="tok"))

    def test_missing_url_skips_gateway(self):
        result = asyncio.run(describe_image(""))
        self.assertFalse(result["success"])
        self.assertIn("缺少", result["error"])

    def test_success(self):
        result = self._run(_gateway_ok())
        self.assertTrue(result["success"], result)
        self.assertEqual(result["description"], "湖边雪山")
        self.assertEqual(result["model"], "doubao-seed-2-0-lite")
        self.assertEqual(result["vendor_id"], 3)

    def test_no_vl_model(self):
        result = self._run([
            patch("services.image_describe.pick_vl_model", return_value=None),
        ])
        self.assertFalse(result["success"])
        self.assertIn("未配置", result["error"])

    def test_model_list_timeout(self):
        async def raise_timeout(*args, **kwargs):
            raise asyncio.TimeoutError()

        result = self._run([
            patch("services.image_describe.pick_vl_model", side_effect=raise_timeout),
        ])
        self.assertFalse(result["success"])
        self.assertIn("超时", result["error"])

    def test_image_fetch_failure(self):
        result = self._run([
            patch("services.image_describe.pick_vl_model", return_value=_PICKED),
            patch("services.image_describe.image_url_to_base64",
                  return_value=(False, None, "图片下载超时")),
        ])
        self.assertFalse(result["success"])
        self.assertIn("图片处理失败", result["error"])

    def test_llm_timeout_mapped_to_friendly_error(self):
        result = self._run([
            patch("services.image_describe.pick_vl_model", return_value=_PICKED),
            patch("services.image_describe.image_url_to_base64",
                  return_value=(True, "data:image/jpeg;base64,xx", None)),
            patch("services.image_describe.call_vl",
                  return_value=(False, "", "视觉模型调用超时")),
        ])
        self.assertFalse(result["success"])
        self.assertIn("识图超时", result["error"])

    def test_unparseable_reply(self):
        result = self._run([
            patch("services.image_describe.pick_vl_model", return_value=_PICKED),
            patch("services.image_describe.image_url_to_base64",
                  return_value=(True, "data:image/jpeg;base64,xx", None)),
            patch("services.image_describe.call_vl",
                  return_value=(True, "   ", None)),
        ])
        self.assertFalse(result["success"])
        self.assertIn("无法解析", result["error"])


if __name__ == "__main__":
    unittest.main()
