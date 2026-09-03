# -*- coding: utf-8 -*-
"""导演台环境估参服务（director_stage_env_fit）测试。

两组合并而来：
- 安全组（develop 加固版）：用户目录隔离、URL 编码穿越、扩展白名单；
- 行为组（vl_gateway 重构后）：估参成功链路、无模型/坏图/解析失败降级。
模型挑选/图片压缩/VL 调用走 services/vl_gateway.py 共享网关，行为组打桩
目标为 vl_gateway 命名空间。
"""
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import services.director_stage_env_fit as env_fit  # noqa: E402
from services.director_stage_env_fit import (  # noqa: E402
    fit_environment_from_image,
    parse_fit_json,
    pick_vl_model,
)

_VL_MODELS = {"models": [
    {"name": "gemini-3-pro", "vendor_id": 7, "vendor_name": "jiekou", "supports_vl": True, "model_id": 71},
    {"name": "doubao-seed-2-0-lite", "vendor_id": 3, "vendor_name": "volcengine", "supports_vl": True, "model_id": 31},
]}


def _llm_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


async def _wait_for_passthrough(coro, timeout=None, **kwargs):
    """直通 wait_for：不超时，直接执行被包装协程（供打桩用）。"""
    return await coro


# ─── 安全组（用户隔离与穿越防护）─────────────────────────────


def test_resolve_upload_path_limits_file_to_authenticated_user(tmp_path, monkeypatch):
    upload_root = tmp_path / "upload"
    own_file = upload_root / "workflow" / "7" / "preview.jpg"
    own_file.parent.mkdir(parents=True)
    own_file.write_bytes(b"image")
    monkeypatch.setattr(env_fit, "get_upload_dir", lambda: str(upload_root))

    resolved, error = env_fit.resolve_upload_path(
        "/upload/workflow/7/preview.jpg",
        user_id=7,
    )

    assert error is None
    assert Path(resolved) == own_file.resolve()


def test_resolve_upload_path_rejects_another_users_file(tmp_path, monkeypatch):
    upload_root = tmp_path / "upload"
    other_file = upload_root / "workflow" / "8" / "preview.jpg"
    other_file.parent.mkdir(parents=True)
    other_file.write_bytes(b"image")
    monkeypatch.setattr(env_fit, "get_upload_dir", lambda: str(upload_root))

    resolved, error = env_fit.resolve_upload_path(
        "/upload/workflow/8/preview.jpg",
        user_id=7,
    )

    assert resolved is None
    assert error == "非法的图片路径"


def test_resolve_upload_path_reports_missing_owned_image(tmp_path, monkeypatch):
    upload_root = tmp_path / "upload"
    upload_root.mkdir()
    monkeypatch.setattr(env_fit, "get_upload_dir", lambda: str(upload_root))

    resolved, error = env_fit.resolve_upload_path(
        "/upload/workflow/7/missing.jpg",
        user_id=7,
    )

    assert resolved is None
    assert error == "图片文件不存在"


@pytest.mark.parametrize(
    "image_url",
    [
        "/upload/../config.yml",
        "/upload/%2e%2e/config.yml",
        r"/upload/..\config.yml",
    ],
)
def test_resolve_upload_path_rejects_traversal(image_url, tmp_path, monkeypatch):
    upload_root = tmp_path / "upload"
    upload_root.mkdir()
    monkeypatch.setattr(env_fit, "get_upload_dir", lambda: str(upload_root))

    resolved, error = env_fit.resolve_upload_path(image_url, user_id=7)

    assert resolved is None
    assert error == "非法的图片路径"


def test_resolve_upload_path_rejects_remote_url():
    # env_fit 仅支持本站 upload 路径：远程 URL 一律拒绝
    resolved, error = env_fit.resolve_upload_path("https://cdn.example.com/a.jpg")
    assert resolved is None
    assert error == "非法的图片路径"


# ─── 行为组（vl_gateway 链路与降级）─────────────────────────


class TestPickVlModel(unittest.TestCase):
    def test_prefers_doubao_lite(self):
        with patch("services.vl_gateway.get_available_models", return_value=_VL_MODELS):
            picked = asyncio.run(pick_vl_model())
        self.assertEqual(picked["name"], "doubao-seed-2-0-lite")

    def test_no_vl_returns_none(self):
        with patch("services.vl_gateway.get_available_models", return_value={"models": []}):
            self.assertIsNone(asyncio.run(pick_vl_model()))


class TestParseFitJson(unittest.TestCase):
    def test_code_block_json(self):
        parsed = parse_fit_json('```json\n{"horizonY":1.2,"sceneScale":2.0,"groundY":-0.5,"reason":"ok"}\n```')
        self.assertEqual(parsed["horizonY"], 1.2)
        self.assertEqual(parsed["sceneScale"], 2.0)

    def test_invalid_returns_none(self):
        self.assertIsNone(parse_fit_json("not json at all"))


class TestFitEnvironment(unittest.TestCase):
    def _run_fit(self, llm_content, resolve_stub=("/srv/upload/p.png", None)):
        """统一打桩：本站图片解析成功 + 压缩成功 + VL 返回指定内容。"""
        from contextlib import ExitStack

        patches = [
            patch("services.director_stage_env_fit.resolve_upload_path", return_value=resolve_stub),
            patch("services.vl_gateway.get_available_models", return_value=_VL_MODELS),
            patch("services.vl_gateway.get_llm_client",
                  return_value=SimpleNamespace(call_api=lambda **kw: _llm_response(llm_content))),
            patch.object(asyncio, "wait_for", _wait_for_passthrough),
            patch("services.vl_gateway.compress_local_image_to_base64",
                  return_value=(True, "data:image/jpeg;base64,xx", None)),
        ]
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            return asyncio.run(fit_environment_from_image("upload/p.png", user_id=7))

    def test_success(self):
        result = self._run_fit('{"horizonY":1.5,"sceneScale":2.0,"groundY":-0.8,"reason":"ok"}')
        self.assertTrue(result["success"], result)
        self.assertEqual(result["horizonY"], 1.5)
        self.assertEqual(result["model"], "doubao-seed-2-0-lite")

    def test_no_vl_model_fallback_manual(self):
        with patch("services.director_stage_env_fit.resolve_upload_path",
                   return_value=("/srv/upload/p.png", None)), \
             patch("services.vl_gateway.get_available_models", return_value={"models": []}):
            result = asyncio.run(fit_environment_from_image("upload/p.png", user_id=7))
        self.assertFalse(result["success"])
        self.assertEqual(result.get("fallback"), "manual")

    def test_bad_image_fallback_manual(self):
        result = self._run_fit("ignored", resolve_stub=(None, "图片文件不存在"))
        self.assertFalse(result["success"])
        self.assertEqual(result.get("fallback"), "manual")

    def test_unparseable_reply_fallback_manual(self):
        result = self._run_fit(" garbage ")
        self.assertFalse(result["success"])
        self.assertEqual(result.get("fallback"), "manual")

    def test_llm_call_failure_fallback_manual(self):
        """VL 调用异常 → 降级人工（不再抛出）。"""
        from contextlib import ExitStack

        def raise_call(**kwargs):
            raise RuntimeError("boom")

        patches = [
            patch("services.director_stage_env_fit.resolve_upload_path",
                  return_value=("/srv/upload/p.png", None)),
            patch("services.vl_gateway.get_available_models", return_value=_VL_MODELS),
            patch("services.vl_gateway.get_llm_client",
                  return_value=SimpleNamespace(call_api=raise_call)),
            patch.object(asyncio, "wait_for", _wait_for_passthrough),
            patch("services.vl_gateway.compress_local_image_to_base64",
                  return_value=(True, "data:image/jpeg;base64,xx", None)),
        ]
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = asyncio.run(fit_environment_from_image("upload/p.png", user_id=7))
        self.assertFalse(result["success"])
        self.assertEqual(result.get("fallback"), "manual")
