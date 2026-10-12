"""
digital_human_tts_tools 单元测试

覆盖：草案存储（TTL/一次性消费/容量淘汰）、VL 选音色 JSON 解析与降级、
clamp_h3_duration、工具流程（mock TTS/VL/H3 HTTP，不连真实服务）。
"""
import asyncio
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from script_writer_core.digital_human_tts_tools import (  # noqa: E402
    _DRAFT_STORE,
    _pick_voice_by_image,
    _store_draft,
    clamp_h3_duration,
    confirm_digital_human,
    consume_draft,
    get_draft,
    prepare_digital_human_draft,
)


class TestDraftStore(unittest.TestCase):

    def setUp(self):
        _DRAFT_STORE.clear()

    def test_store_and_get(self):
        draft_id = _store_draft({"text": "hi"})
        got = get_draft(draft_id)
        self.assertEqual(got["text"], "hi")

    def test_consume_removes(self):
        draft_id = _store_draft({"text": "hi"})
        got = consume_draft(draft_id)
        self.assertEqual(got["text"], "hi")
        self.assertIsNone(get_draft(draft_id), "消费后应移除（防重复提交）")
        self.assertIsNone(consume_draft(draft_id), "重复消费返回 None")

    def test_expired_draft(self):
        draft_id = _store_draft({"text": "hi"})
        _DRAFT_STORE[draft_id]["expires_at"] = 0  # 置为过期
        self.assertIsNone(get_draft(draft_id))
        self.assertIsNone(consume_draft(draft_id))


class TestClampDuration(unittest.TestCase):

    def test_clamp(self):
        self.assertEqual(clamp_h3_duration(0), 4)
        self.assertEqual(clamp_h3_duration(3.2), 4)
        self.assertEqual(clamp_h3_duration(4), 4)
        self.assertEqual(clamp_h3_duration(5.6), 6)
        self.assertEqual(clamp_h3_duration(10), 10)
        self.assertEqual(clamp_h3_duration(99), 10)


class _VoiceModelMockBase(unittest.TestCase):
    """统一 mock 工具模块的 VoiceModel（避免真实 DB 连接）"""

    def setUp(self):
        super().setUp()
        self._vm_patcher = patch("script_writer_core.digital_human_tts_tools.VoiceModel")
        self.vm = self._vm_patcher.start()
        self.vm.get_by_id.return_value = MagicMock(
            id=7, is_active=1, provider="volcengine", name="Vivi 2.0")
        self.vm.get_by_voice_type.return_value = MagicMock(id=1, is_active=1)
        self.vm.list_all.return_value = {"data": [
            {"id": 1, "name": "Vivi 2.0", "gender": "female", "style": "治愈", "description": "d1"},
            {"id": 2, "name": "阿虎 2.0", "gender": "male", "style": "温暖", "description": "d2"},
        ]}
        self.addCleanup(self._vm_patcher.stop)


class TestPickVoiceByImage(_VoiceModelMockBase):

    CANDIDATES = [
        {"voice_id": 1, "name": "Vivi 2.0", "gender": "female", "style": "治愈", "description": "d1"},
        {"voice_id": 2, "name": "阿虎 2.0", "gender": "male", "style": "温暖", "description": "d2"},
    ]

    def test_valid_json_parsed(self):
        async def fake_call_vl(system, user, img, **kw):
            return True, '{"voice_id": 2, "reason": "男性角色"}', None

        async def fake_base64(*a, **kw):
            return True, "data:image/png;base64,xxx", None

        with patch("script_writer_core.digital_human_tts_tools.pick_vl_model",
                   async_fn(lambda: {"name": "vl", "vendor_id": 1, "id": 9})), \
             patch("script_writer_core.digital_human_tts_tools.image_url_to_base64", fake_base64), \
             patch("script_writer_core.digital_human_tts_tools.call_vl", fake_call_vl):
            result = asyncio.run(_pick_voice_by_image("http://x/img.png", self.CANDIDATES, 1))

        self.assertEqual(result["voice_id"], 2)
        self.assertEqual(result["reason"], "男性角色")

    def test_out_of_range_voice_falls_back(self):
        async def fake_call_vl(system, user, img, **kw):
            return True, '{"voice_id": 999, "reason": "x"}', None

        async def fake_base64(*a, **kw):
            return True, "data:x", None

        with patch("script_writer_core.digital_human_tts_tools.pick_vl_model",
                   async_fn(lambda: {"name": "vl"})), \
             patch("script_writer_core.digital_human_tts_tools.image_url_to_base64", fake_base64), \
             patch("script_writer_core.digital_human_tts_tools.call_vl", fake_call_vl):
            result = asyncio.run(_pick_voice_by_image("http://x/img.png", self.CANDIDATES, 1))

        self.assertEqual(result["voice_id"], _default_vid(), "候选外音色应降级默认")
        self.assertIn("候选之外", result["reason"])

    def test_no_vl_model_falls_back(self):
        async def fake_none(*a, **k):
            return None

        with patch("script_writer_core.digital_human_tts_tools.pick_vl_model", fake_none):
            result = asyncio.run(_pick_voice_by_image("http://x/img.png", self.CANDIDATES, 1))
        self.assertEqual(result["voice_id"], _default_vid())
        self.assertIn("视觉模型", result["reason"])


def _default_vid():
    from script_writer_core.digital_human_tts_tools import _default_voice_id
    return _default_voice_id()


def async_fn(return_value):
    """把同步返回值包装成 async 函数"""
    async def _fn(*a, **k):
        if callable(return_value):
            return return_value()
        return return_value
    return _fn


class TestPrepareTool(_VoiceModelMockBase):

    def setUp(self):
        _DRAFT_STORE.clear()

    def test_missing_text_rejected(self):
        result = asyncio.run(prepare_digital_human_draft(
            user_id="1", world_id="w", auth_token="t",
            image_url="http://x/img.png", script_text="  "))
        self.assertFalse(result["success"])
        self.assertIn("口播文案", result["error"])

    def test_missing_image_rejected(self):
        result = asyncio.run(prepare_digital_human_draft(
            user_id="1", world_id="w", auth_token="t",
            image_url="", script_text="文案"))
        self.assertFalse(result["success"])

    def test_success_flow(self):
        voice = MagicMock(id=7, is_active=1, provider="volcengine", name="Vivi 2.0",
                          voice_type="zh_female_vv_uranus_bigtts")

        async def fake_tts(**kw):
            return {"success": True, "audio_url": "http://x/a.mp3", "duration": 5.2,
                    "computing_power": 2, "voice_name": "Vivi 2.0", "voice_type": "zh",
                    "voice_id": 7}

        with patch("script_writer_core.digital_human_tts_tools.VoiceModel") as vm, \
             patch("script_writer_core.digital_human_tts_tools.synthesize_speech_for_user", fake_tts):
            vm.get_by_id.return_value = voice
            result = asyncio.run(prepare_digital_human_draft(
                user_id="1", world_id="w", auth_token="t",
                image_url="http://x/img.png", script_text="测试文案", voice_id=7))

        self.assertTrue(result["success"])
        draft = result["draft"]
        self.assertTrue(draft["draft_id"])
        self.assertEqual(draft["h3_duration"], 6)  # 5.2s → ceil 6
        self.assertEqual(draft["tts_computing_power"], 2)
        # 草案已入库存
        self.assertIsNotNone(get_draft(draft["draft_id"]))


class TestConfirmTool(_VoiceModelMockBase):

    def setUp(self):
        _DRAFT_STORE.clear()

    def test_unknown_draft_rejected(self):
        result = asyncio.run(confirm_digital_human(
            user_id="1", world_id="w", auth_token="t", draft_id="nonexistent"))
        self.assertFalse(result["success"])
        self.assertIn("不存在", result["error"])

    def test_confirm_submits_h3(self):
        draft_id = _store_draft({
            "script_text": "测试", "image_url": "http://x/img.png",
            "audio_url": "http://x/a.mp3", "voice_name": "Vivi 2.0",
            "h3_duration": 5, "h3_computing_power": 6, "max_edge": 1280,
        })

        class FakeResp:
            def __init__(self, payload, status=200):
                self._payload = payload
                self.status_code = status
                self.content = payload if isinstance(payload, bytes) else b'{}'
            def raise_for_status(self):
                pass
            def json(self):
                return self._payload

        async def fake_get(*a, **k):
            return FakeResp(b"file-bytes")

        captured = {}

        def fake_post(*a, **kw):
            captured["url"] = kw.get("url") or (a[0] if a else None)
            captured["data"] = kw.get("data")
            captured["files"] = kw.get("files")
            return FakeResp({"success": True, "project_id": 555})

        cfg = MagicMock()
        cfg.get.return_value = {"host": "http://localhost:13003"}
        with patch("script_writer_core.digital_human_tts_tools.get_config", return_value=cfg), \
             patch("script_writer_core.digital_human_tts_tools.httpx.AsyncClient.get", fake_get), \
             patch("script_writer_core.digital_human_tts_tools.httpx.post", side_effect=fake_post):
            result = asyncio.run(confirm_digital_human(
                user_id="1", world_id="w", auth_token="tok", draft_id=draft_id))

        self.assertTrue(result["success"])
        self.assertEqual(result["project_ids"], ["555"])
        self.assertIn("digital-human-minimax-h3", captured["url"])
        self.assertEqual(captured["data"]["duration"], "5")
        # 草案一次性消费
        self.assertIsNone(get_draft(draft_id))

    def test_confirm_h3_error_propagates(self):
        draft_id = _store_draft({
            "script_text": "测试", "image_url": "http://x/i.png",
            "audio_url": "http://x/a.mp3", "voice_name": "v",
            "h3_duration": 5, "h3_computing_power": 6, "max_edge": 1280,
        })

        class FakeErrResp:
            def __init__(self, payload=b""):
                self.content = payload
                self.status_code = 400
            def raise_for_status(self):
                import httpx
                resp_mock = MagicMock()
                resp_mock.json.return_value = {"detail": "算力不足"}
                raise httpx.HTTPStatusError("bad", request=MagicMock(), response=resp_mock)
            def json(self):
                return {"detail": "算力不足"}

        async def fake_get(*a, **k):
            return FakeErrResp(b"x")

        def fake_post(*a, **kw):
            return FakeErrResp()

        cfg = MagicMock()
        cfg.get.return_value = {"host": "http://localhost:13003"}
        with patch("script_writer_core.digital_human_tts_tools.get_config", return_value=cfg), \
             patch("script_writer_core.digital_human_tts_tools.httpx.AsyncClient.get", fake_get), \
             patch("script_writer_core.digital_human_tts_tools.httpx.post", side_effect=fake_post):
            result = asyncio.run(confirm_digital_human(
                user_id="1", world_id="w", auth_token="t", draft_id=draft_id))

        self.assertFalse(result["success"])
        self.assertIn("算力不足", result["error"])


if __name__ == '__main__':
    unittest.main()
