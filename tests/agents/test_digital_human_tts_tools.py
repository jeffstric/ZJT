"""
digital_human_tts_tools 单元测试

覆盖：草案存储（TTL/一次性消费/容量淘汰）、VL 选音色 JSON 解析与降级、
clamp_h3_duration、时长模型路由（>10s 走 LTX2.3）、工具流程
（mock TTS/VL/H3/LTX2.3 HTTP，不连真实服务）。
"""
import asyncio
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.constant import TaskTypeId  # noqa: E402
from script_writer_core.digital_human_tts_tools import (  # noqa: E402
    SEGMENTED_MOTION_PROMPT,
    _DRAFT_STORE,
    _pick_voice_by_image,
    _store_draft,
    clamp_h3_duration,
    confirm_digital_human,
    consume_draft,
    get_draft,
    prepare_digital_human_draft,
    resolve_digital_human_model,
    split_audio_into_segments,
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
        self.assertEqual(clamp_h3_duration(14.2), 15)
        self.assertEqual(clamp_h3_duration(99), 15)


class TestResolveDigitalHumanModel(unittest.TestCase):
    """时长路由边界（2026-10-16 v2）：≤15s→H3 单段，15-30s→H3 分段拼接，>30s→拒绝"""

    def test_lte_15s_routes_h3_single(self):
        for sec in (0, 4.0, 10.0, 14.9, 15.0):
            r = resolve_digital_human_model(sec)
            self.assertEqual(r["model_task_type"], TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3,
                             f"{sec}s 应路由 H3")
            self.assertEqual(r["routing_reason"], "duration_lte_15s_h3_single")
            self.assertFalse(r["segment_mode"])

    def test_h3_billable_clamps_to_grid(self):
        self.assertEqual(resolve_digital_human_model(5.2)["billable_duration"], 6)
        self.assertEqual(resolve_digital_human_model(0)["billable_duration"], 4)
        self.assertEqual(resolve_digital_human_model(15.0)["billable_duration"], 15)

    def test_gt_15s_routes_segmented(self):
        r = resolve_digital_human_model(15.1)
        self.assertEqual(r["model_task_type"], TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3,
                         "15-30s 也走 H3（分段拼接），不再路由 LTX2.3")
        self.assertEqual(r["routing_reason"], "duration_gt_15s_h3_segmented")
        self.assertTrue(r["segment_mode"])
        self.assertEqual(r["billable_duration"], 20)  # 整数段口径 ceil(15.1/10)*10

    def test_30s_boundary_segmented(self):
        r = resolve_digital_human_model(30.0)
        self.assertTrue(r["segment_mode"])
        self.assertEqual(r["billable_duration"], 30)

    def test_gt_30s_rejected(self):
        for sec in (30.1, 60, 500):
            self.assertIsNone(resolve_digital_human_model(sec), f"{sec}s 应拒绝")


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
            return True, ('{"voice_id": 2, "reason": "男性角色", '
                          '"motion_prompt": "角色面向镜头深情的说话，固定镜头。"}'), None

        async def fake_base64(*a, **kw):
            return True, "data:image/png;base64,xxx", None

        with patch("script_writer_core.digital_human_tts_tools.pick_vl_model",
                   async_fn(lambda: {"name": "vl", "vendor_id": 1, "id": 9})), \
             patch("script_writer_core.digital_human_tts_tools.image_url_to_base64", fake_base64), \
             patch("script_writer_core.digital_human_tts_tools.call_vl", fake_call_vl):
            result = asyncio.run(_pick_voice_by_image("http://x/img.png", self.CANDIDATES, 1))

        self.assertEqual(result["voice_id"], 2)
        self.assertEqual(result["reason"], "男性角色")
        self.assertIn("固定镜头", result["motion_prompt"])

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

    def test_gender_mismatch_auto_corrects(self):
        """VL 输出音色与检测性别不符时，自动改选同性候选（防串音色）"""
        candidates = [
            {"voice_id": 1, "name": "Vivi 2.0", "gender": "female", "style": "治愈", "description": "d1"},
            {"voice_id": 2, "name": "阿虎 2.0", "gender": "male", "style": "温暖", "description": "d2"},
        ]

        async def fake_call_vl(system, user, img, **kw):
            return True, ('{"detected_gender": "male", "voice_id": 1, '
                          '"reason": "看错", "motion_prompt": "固定镜头。"}'), None

        async def fake_base64(*a, **kw):
            return True, "data:x", None

        with patch("script_writer_core.digital_human_tts_tools.pick_vl_model",
                   async_fn(lambda: {"name": "vl"})),              patch("script_writer_core.digital_human_tts_tools.image_url_to_base64", fake_base64),              patch("script_writer_core.digital_human_tts_tools.call_vl", fake_call_vl):
            result = asyncio.run(_pick_voice_by_image("http://x/img.png", candidates, 1))

        # detected=male 但选了女声 → 自动改选男声候选
        self.assertEqual(result["voice_id"], 2)
        self.assertIn("校正", result["reason"])

    def test_gender_match_keeps(self):
        """VL 选音色性别与检测一致时保持原选择"""
        candidates = [
            {"voice_id": 1, "name": "Vivi 2.0", "gender": "female", "style": "治愈", "description": "d1"},
            {"voice_id": 2, "name": "阿虎 2.0", "gender": "male", "style": "温暖", "description": "d2"},
        ]

        async def fake_call_vl(system, user, img, **kw):
            return True, ('{"detected_gender": "female", "voice_id": 1, '
                          '"reason": "匹配", "motion_prompt": "固定镜头。"}'), None

        async def fake_base64(*a, **kw):
            return True, "data:x", None

        with patch("script_writer_core.digital_human_tts_tools.pick_vl_model",
                   async_fn(lambda: {"name": "vl"})),              patch("script_writer_core.digital_human_tts_tools.image_url_to_base64", fake_base64),              patch("script_writer_core.digital_human_tts_tools.call_vl", fake_call_vl):
            result = asyncio.run(_pick_voice_by_image("http://x/img.png", candidates, 1))

        self.assertEqual(result["voice_id"], 1)

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
        self.assertIn("固定镜头", draft["motion_prompt"])
        # ≤15s 路由 H3 单段，新字段与旧字段一致
        self.assertEqual(draft["model_task_type"], TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3)
        self.assertEqual(draft["routing_reason"], "duration_lte_15s_h3_single")
        self.assertFalse(draft["segment_mode"])
        self.assertEqual(draft["billable_duration"], 6)
        self.assertEqual(draft["video_computing_power"], draft["h3_computing_power"])
        self.assertIn("MiniMax H3", result["message"])
        # 草案已入库存
        self.assertIsNotNone(get_draft(draft["draft_id"]))

    def test_long_speech_routes_segmented_h3(self):
        """TTS 实测 20s（>15s）→ H3 分段拼接模式，billable=ceil(20)"""
        voice = MagicMock(id=7, is_active=1, provider="volcengine", name="Vivi 2.0",
                          voice_type="zh_female_vv_uranus_bigtts")

        async def fake_tts(**kw):
            return {"success": True, "audio_url": "http://x/a.mp3", "duration": 20.0,
                    "computing_power": 8, "voice_name": "Vivi 2.0", "voice_type": "zh",
                    "voice_id": 7}

        with patch("script_writer_core.digital_human_tts_tools.VoiceModel") as vm, \
             patch("script_writer_core.digital_human_tts_tools.synthesize_speech_for_user", fake_tts):
            vm.get_by_id.return_value = voice
            result = asyncio.run(prepare_digital_human_draft(
                user_id="1", world_id="w", auth_token="t",
                image_url="http://x/img.png", script_text="长文案" * 30, voice_id=7))

        self.assertTrue(result["success"])
        draft = result["draft"]
        self.assertEqual(draft["model_task_type"], TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3)
        self.assertEqual(draft["routing_reason"], "duration_gt_15s_h3_segmented")
        self.assertTrue(draft["segment_mode"])
        self.assertEqual(draft["billable_duration"], 20)  # 整数段口径 ceil(20/10)*10
        self.assertEqual(draft["effective_motion_prompt"], SEGMENTED_MOTION_PROMPT,
                         "分段模式必须使用固定镜头统一提示词")
        self.assertIn("MiniMax H3", result["message"])
        self.assertIn("拼接", result["message"])

    def test_over_30s_rejected_with_split_hint(self):
        """TTS 实测 35s → 拒绝并提示拆分文案，不产生草案"""
        voice = MagicMock(id=7, is_active=1, provider="volcengine", name="Vivi 2.0",
                          voice_type="zh_female_vv_uranus_bigtts")

        async def fake_tts(**kw):
            return {"success": True, "audio_url": "http://x/a.mp3", "duration": 35.0,
                    "computing_power": 10, "voice_name": "Vivi 2.0", "voice_type": "zh",
                    "voice_id": 7}

        with patch("script_writer_core.digital_human_tts_tools.VoiceModel") as vm, \
             patch("script_writer_core.digital_human_tts_tools.synthesize_speech_for_user", fake_tts):
            vm.get_by_id.return_value = voice
            result = asyncio.run(prepare_digital_human_draft(
                user_id="1", world_id="w", auth_token="t",
                image_url="http://x/img.png", script_text="超长文案", voice_id=7))

        self.assertFalse(result["success"])
        self.assertIn("拆分", result["error"])
        self.assertIn("35", result["error"])
        self.assertEqual(len(_DRAFT_STORE), 0)

    def test_user_audio_duration_probed_for_routing(self):
        """用户直供音频缺时长时补 probe：15s → H3 单段（边界值）"""
        probed = {}

        async def fake_probe(url):
            probed["url"] = url
            return 15.0

        async def fake_pick(*a, **k):
            return {"voice_id": None, "reason": "r",
                    "motion_prompt": "角色面向镜头深情的说话，固定镜头。"}

        def fake_candidates(*a, **k):
            return []

        with patch("script_writer_core.digital_human_tts_tools.probe_audio_duration", fake_probe), \
             patch("script_writer_core.digital_human_tts_tools._pick_voice_by_image", fake_pick), \
             patch("script_writer_core.digital_human_tts_tools._load_voice_candidates", fake_candidates):
            result = asyncio.run(prepare_digital_human_draft(
                user_id="1", world_id="w", auth_token="t",
                image_url="http://x/img.png", script_text="文案",
                audio_url="http://x/user_audio.mp3"))

        self.assertTrue(result["success"])
        self.assertEqual(probed["url"], "http://x/user_audio.mp3")
        draft = result["draft"]
        self.assertEqual(draft["model_task_type"], TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3)
        self.assertFalse(draft["segment_mode"])
        self.assertEqual(draft["billable_duration"], 15)


class TestConfirmTool(_VoiceModelMockBase):

    def setUp(self):
        _DRAFT_STORE.clear()

    def test_unknown_draft_rejected(self):
        result = asyncio.run(confirm_digital_human(
            user_id="1", world_id="w", auth_token="t", draft_id="nonexistent"))
        self.assertFalse(result["success"])
        self.assertIn("不存在", result["error"])

    def test_prepare_with_user_audio_skips_tts(self):
        """场景2：用户提供驱动音频 → 跳过 TTS（不扣 TTS 算力）直接出草案"""
        tts_called = []

        async def fake_tts(**kw):
            tts_called.append(1)
            return {"success": True, "audio_url": "http://x/tts.mp3", "duration": 5,
                    "computing_power": 1, "voice_name": "v", "voice_type": "zh", "voice_id": 1}

        async def fake_pick(*a, **k):
            return {"voice_id": 1, "reason": "r",
                    "motion_prompt": "角色面向镜头深情的说话，固定镜头。"}

        async def fake_candidates(*a, **k):
            return [{"voice_id": 1, "name": "Vivi 2.0", "provider": "reference_audio",
                     "audio_url": "/voice_presets/preset_001.mp3"}]

        with patch("script_writer_core.digital_human_tts_tools.synthesize_speech_for_user", fake_tts),              patch("script_writer_core.digital_human_tts_tools._pick_voice_by_image", fake_pick),              patch("script_writer_core.digital_human_tts_tools._load_voice_candidates", fake_candidates):
            result = asyncio.run(prepare_digital_human_draft(
                user_id="1", world_id="w", auth_token="t",
                image_url="http://x/img.png", script_text="文案",
                audio_url="http://x/user_audio.mp3"))

        self.assertTrue(result["success"])
        self.assertEqual(result["draft"]["audio_url"], "http://x/user_audio.mp3")
        self.assertEqual(result["draft"]["tts_computing_power"], 0)
        self.assertIn("用户提供的驱动音频", result["draft"]["voice_selection_reason"])
        self.assertIn("固定镜头", result["draft"]["motion_prompt"])
        self.assertEqual(tts_called, [], "提供用户音频时不应调用 TTS")

    def test_tts_unconfigured_error_propagates(self):
        """TTS 未配置的引导错误会原样透传（含「未配置」字样供 LLM 触发降级规则）；
        失败时不产生草案。mock 查音色直接抛带标记的错误，验证透传机制本身。"""
        marker = "RuntimeError-MARKER-未配置火山语音合成，无法使用该音色"
        volcengine_voice = MagicMock(
            id=9, is_active=1, provider="volcengine", name="通用女声",
            voice_type="BV700_streaming", audio_url=None, language="zh")

        with patch("script_writer_core.digital_human_tts_tools.get_volcengine_tts_config",
                   return_value={"api_key": "", "resource_id": "seed-tts-2.0"}), \
             patch("script_writer_core.digital_human_tts_tools.is_tts_configured",
                   lambda cfg: bool(cfg.get("api_key"))), \
             patch("script_writer_core.digital_human_tts_tools.VoiceModel") as vm, \
             patch("script_writer_core.digital_human_tts_tools._load_voice_candidates",
                   return_value=[]):
            vm.get_by_id.side_effect = RuntimeError(marker)
            result = asyncio.run(prepare_digital_human_draft(
                user_id="1", world_id="w", auth_token="t",
                image_url="http://x/img.png", script_text="文案", voice_id=9))

        self.assertFalse(result["success"])
        self.assertIn(marker, result["error"])
        self.assertEqual(len(_DRAFT_STORE), 0)

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
        # 存量草案（无 model_task_type）缺省按 H3 提交，兼容升级前数据
        self.assertEqual(result["model_task_type"], TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3)
        # 真实 httpx multipart 编码（防 files 结构错误漏过 mock）
        import httpx as _httpx
        _httpx.Request("POST", captured["url"], data=captured["data"], files=captured["files"])
        # 草案一次性消费
        self.assertIsNone(get_draft(draft_id))

    def test_confirm_dispatches_segmented(self):
        """分段草案 → 提交 /api/digital-human-minimax-h3：
        text 强制固定镜头提示词、segment_durations JSON、segment_audio 文件随 multipart 上传"""
        draft_id = _store_draft({
            "script_text": "长文案", "image_url": "http://x/img.png",
            "audio_url": "/upload/character/voice/local.mp3", "voice_name": "v",
            "motion_prompt": "角色面向镜头深情的说话，缓慢推近。",
            "effective_motion_prompt": SEGMENTED_MOTION_PROMPT,
            "model_task_type": TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3,
            "routing_reason": "duration_gt_15s_h3_segmented",
            "segment_mode": True,
            "billable_duration": 30,
            "video_computing_power": 12,
            "h3_duration": 30, "h3_computing_power": 12,
            "max_edge": 720,
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
            return FakeResp({"success": True, "project_id": 777})

        fake_plan = {
            "segments": [
                {"path": "upload/dh/seg_1.wav", "duration": 10},
                {"path": "upload/dh/seg_2.wav", "duration": 10},
                {"path": "upload/dh/seg_3.wav", "duration": 10},
            ],
            "cuts": [9.5, 19.0], "total": 28.5,
        }

        cfg = MagicMock()
        cfg.get.return_value = {"host": "http://localhost:13003"}
        with patch("script_writer_core.digital_human_tts_tools.get_config", return_value=cfg), \
             patch("script_writer_core.digital_human_tts_tools.httpx.AsyncClient.get", fake_get), \
             patch("script_writer_core.digital_human_tts_tools.httpx.post", side_effect=fake_post), \
             patch("script_writer_core.digital_human_tts_tools._resolve_local_media_path",
                   return_value="/local/voice.mp3"), \
             patch("script_writer_core.digital_human_tts_tools.probe_audio_duration",
                   async_fn(lambda: 28.5)), \
             patch("script_writer_core.digital_human_tts_tools.split_audio_into_segments",
                   return_value=fake_plan), \
             patch("builtins.open", MagicMock()):
            result = asyncio.run(confirm_digital_human(
                user_id="1", world_id="w", auth_token="tok", draft_id=draft_id))

        self.assertTrue(result["success"])
        self.assertEqual(result["project_ids"], ["777"])
        self.assertIn("digital-human-minimax-h3", captured["url"])
        self.assertEqual(captured["data"]["duration"], "30")
        self.assertEqual(captured["data"]["text"], SEGMENTED_MOTION_PROMPT,
                         "分段模式提交的提示词必须是固定镜头统一版本，不用 VL 生成的推近镜头")
        self.assertEqual(json.loads(captured["data"]["segment_durations"]), [10, 10, 10])
        seg_files = [f for f in captured["files"] if f[0] == 'segment_audio']
        self.assertEqual(len(seg_files), 3, "三段音频文件应随 multipart 上传")
        self.assertEqual(result["model_used"], "MiniMax H3 数字人（分段拼接）")
        self.assertTrue(result["segment_mode"])
        # 真实 httpx multipart 编码（防 files 结构错误漏过 mock）
        import httpx as _httpx
        _httpx.Request("POST", captured["url"], data=captured["data"], files=captured["files"])
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


class TestSplitAudioSegments(unittest.TestCase):
    """split_audio_into_segments 真实 ffmpeg 切分：切点在句间静音、两段各 ≤15s 且对齐整数秒"""

    def test_split_28_5s_audio(self):
        import subprocess
        ff = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), 'bin', 'ffmpeg', 'ffmpeg.exe')
        if not os.path.isfile(ff):
            self.skipTest("bin/ffmpeg 不可用")
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_seg_src.wav')
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_seg_out')
        subprocess.run([ff, '-y', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=28.5',
                        '-ar', '44100', '-ac', '2', src], check=True, capture_output=True)
        try:
            plan = split_audio_into_segments(src, 28.5, out_dir)
            segs = plan["segments"]
            self.assertEqual(len(segs), 3, "28.5s 按段长 10s 应切成 3 段")
            total = 0
            for s in segs:
                self.assertLessEqual(s["duration"], 10, "每段不得超过段长上限 10s")
                self.assertGreaterEqual(s["duration"], 4, "每段不得低于 H3 最短 4s")
                self.assertTrue(os.path.isfile(s["path"]))
                total += s["duration"]
            self.assertEqual(total, 30, "三段整数秒之和应等于 ceil(28.5/10)*10=30")
            # 切点应落在均分点附近（±3s 窗口）
            self.assertAlmostEqual(plan["cuts"][0], 9.5, delta=3.0)
            self.assertAlmostEqual(plan["cuts"][1], 19.0, delta=3.0)
        finally:
            for p in (src,):
                if os.path.isfile(p):
                    os.remove(p)
            if os.path.isdir(out_dir):
                import shutil
                shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
