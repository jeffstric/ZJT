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
    LOCKED_CAMERA_PROMPT_FALLBACK,
    SEGMENTED_MOTION_PROMPT,
    _DRAFT_STORE,
    _generate_locked_camera_prompt,
    _pick_voice_by_image,
    _resolve_preset_local_path,
    _store_draft,
    clamp_h3_duration,
    confirm_digital_human,
    consume_draft,
    get_draft,
    prepare_digital_human_draft,
    resolve_digital_human_model,
    split_audio_into_segments,
)


class TestPresetLocalPath(unittest.TestCase):

    def test_preset_mp3_resolves_under_web(self):
        path = _resolve_preset_local_path("/voice_presets/preset_001.mp3")
        self.assertTrue(path.endswith(os.path.join("web", "voice_presets", "preset_001.mp3")))
        self.assertTrue(os.path.isfile(path))

    def test_path_traversal_rejected(self):
        self.assertEqual(_resolve_preset_local_path("/voice_presets/../secret.mp3"), "")


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
    """时长路由边界（2026-10-16 v3 定稿）：≤15s→H3 单段，>15s→H3 分段拼接，>600s→拒绝"""

    def test_lte_15s_routes_h3_single(self):
        for sec in (0, 4.0, 10.0, 14.9, 15.0):
            r = resolve_digital_human_model(sec)
            self.assertEqual(r["model_task_type"], TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3,
                             f"{sec}s 应路由 H3 单段")
            self.assertEqual(r["routing_reason"], "duration_lte_15s_h3_single")
            self.assertFalse(r["segment_mode"])

    def test_h3_billable_clamps_to_grid(self):
        self.assertEqual(resolve_digital_human_model(5.2)["billable_duration"], 6)
        self.assertEqual(resolve_digital_human_model(0)["billable_duration"], 4)
        self.assertEqual(resolve_digital_human_model(10.0)["billable_duration"], 10)
        self.assertEqual(resolve_digital_human_model(15.0)["billable_duration"], 15)

    def test_gt_15s_routes_segmented(self):
        r = resolve_digital_human_model(15.1)
        self.assertEqual(r["model_task_type"], TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3,
                         ">15s 走 H3 分段拼接（段长 15s），不再路由 LTX2.3")
        self.assertEqual(r["routing_reason"], "duration_gt_15s_h3_segmented")
        self.assertTrue(r["segment_mode"])
        # 计费口径 = 预估各段档位之和（estimate: 2 段各 ceil(7.55)=8 → 8+8）
        self.assertEqual(r["billable_duration"], 16)
        self.assertEqual(r["segment_durations_est"], [8, 8])

    def test_30s_boundary_segmented(self):
        r = resolve_digital_human_model(30.0)
        self.assertTrue(r["segment_mode"])
        self.assertEqual(r["billable_duration"], 30)

    def test_gt_600s_rejected(self):
        for sec in (601, 1000):
            self.assertIsNone(resolve_digital_human_model(sec), f"{sec}s 应拒绝（异常兜底）")


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


class TestLockedCameraPrompt(unittest.TestCase):
    """H3 锁镜头英文提示词生成：瞬时故障重试、本地映射兜底、兜底模板约束。

    背景（12815）：内网自访问 frp 公网地址瞬断导致角色图远程下载失败，
    单次失败即降级无约束兜底模板 → H3 逐段自由发挥、段间换装/换背景。
    """

    PROMPT = ("integrated_multimodal_description: [Shot 1] A static medium shot of "
              "a doctor, The camera is strictly locked.")

    def test_retry_until_success(self):
        """瞬时读取失败应重试并最终成功，不应首轮失败即降级"""
        from config.constant import DIGITAL_HUMAN_VL_PROMPT_MAX_ATTEMPTS
        calls = {"n": 0}

        async def fake_base64(*a, **kw):
            calls["n"] += 1
            if calls["n"] < DIGITAL_HUMAN_VL_PROMPT_MAX_ATTEMPTS:
                return False, None, "All connection attempts failed"
            return True, "data:x", None

        async def fake_call_vl(system, user, img, **kw):
            return True, self.PROMPT, None

        with patch("script_writer_core.digital_human_tts_tools.pick_vl_model",
                   async_fn(lambda: {"name": "vl"})), \
             patch("script_writer_core.digital_human_tts_tools.image_url_to_base64", fake_base64), \
             patch("script_writer_core.digital_human_tts_tools.call_vl", fake_call_vl), \
             patch("utils.image_upload_utils.try_map_url_to_local_file", lambda *a, **k: None), \
             patch("script_writer_core.digital_human_tts_tools.asyncio.sleep", async_fn(None)):
            result = asyncio.run(_generate_locked_camera_prompt("http://x/img.png", 1))

        self.assertTrue(result["success"])
        self.assertEqual(result["prompt"], self.PROMPT)
        self.assertEqual(calls["n"], DIGITAL_HUMAN_VL_PROMPT_MAX_ATTEMPTS)

    def test_remote_failure_uses_local_mapping(self):
        """远程下载失败时应改用本地映射文件直读（frp 自访问瞬断场景），直接成功"""
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        local_attempts = []

        async def fake_base64(*a, **kw):
            if kw.get("local_path"):
                local_attempts.append(kw["local_path"])
                return True, "data:x", None
            return False, None, "All connection attempts failed"

        async def fake_call_vl(system, user, img, **kw):
            return True, self.PROMPT, None

        with patch("script_writer_core.digital_human_tts_tools.pick_vl_model",
                   async_fn(lambda: {"name": "vl"})), \
             patch("script_writer_core.digital_human_tts_tools.image_url_to_base64", fake_base64), \
             patch("script_writer_core.digital_human_tts_tools.call_vl", fake_call_vl), \
             patch("utils.image_upload_utils.try_map_url_to_local_file",
                   lambda *a, **k: tmp.name):
            result = asyncio.run(_generate_locked_camera_prompt("http://x/img.png", 1))

        self.assertTrue(result["success"])
        self.assertEqual(local_attempts, [tmp.name])

    def test_exhausted_attempts_returns_failure(self):
        """重试耗尽后返回 success=False，由调用方使用兜底模板"""
        from config.constant import DIGITAL_HUMAN_VL_PROMPT_MAX_ATTEMPTS
        calls = {"n": 0}

        async def fake_base64(*a, **kw):
            calls["n"] += 1
            return False, None, "All connection attempts failed"

        with patch("script_writer_core.digital_human_tts_tools.pick_vl_model",
                   async_fn(lambda: {"name": "vl"})), \
             patch("script_writer_core.digital_human_tts_tools.image_url_to_base64", fake_base64), \
             patch("utils.image_upload_utils.try_map_url_to_local_file", lambda *a, **k: None), \
             patch("script_writer_core.digital_human_tts_tools.asyncio.sleep", async_fn(None)):
            result = asyncio.run(_generate_locked_camera_prompt("http://x/img.png", 1))

        self.assertFalse(result["success"])
        self.assertIn("角色图读取失败", result["error"])
        self.assertEqual(calls["n"], DIGITAL_HUMAN_VL_PROMPT_MAX_ATTEMPTS)

    def test_fallback_template_keeps_outfit_background_constraint(self):
        """兜底模板必须约束服装/发型/背景与参考图一致，防 H3 逐段自由发挥"""
        self.assertIn("same outfit", LOCKED_CAMERA_PROMPT_FALLBACK)
        self.assertIn("hairstyle", LOCKED_CAMERA_PROMPT_FALLBACK)
        self.assertIn("background", LOCKED_CAMERA_PROMPT_FALLBACK)
        self.assertIn("integrated_multimodal_description", LOCKED_CAMERA_PROMPT_FALLBACK)

    def test_locked_camera_template_hand_micro_motion_clause(self):
        """手部微动条件从句：可见手→小幅动作，无手→全身静止；防段间漂移的身体
        锁定约束必须保留，且 VL 指令要求看图判断有无手（零新增 LLM 调用）"""
        from script_writer_core.digital_human_tts_tools import (
            LOCKED_CAMERA_PROMPT_TEMPLATE,
            VL_LOCKED_CAMERA_INSTRUCTION,
        )
        for text in (LOCKED_CAMERA_PROMPT_TEMPLATE, LOCKED_CAMERA_PROMPT_FALLBACK):
            self.assertIn("If hands are visible", text)
            self.assertIn("subtle natural movements", text)
            # 身体/服装/背景锁定约束不得被手部例外削弱（12815 回归红线）
            self.assertIn("motionless", text)
            self.assertIn("zero camera movement", text)
        self.assertIn("手部", VL_LOCKED_CAMERA_INSTRUCTION)
        self.assertIn("手腕微转", VL_LOCKED_CAMERA_INSTRUCTION)
        # 指令内嵌模板与正式模板的手部从句一致（VL 逐字照抄内嵌模板输出）
        self.assertIn("If hands are visible", VL_LOCKED_CAMERA_INSTRUCTION)

    def test_storyboard_default_prompt_hand_clause(self):
        """分镜链 DEFAULT_PROMPT：条件从句（无手不生效）+ 身体其余部分锁定"""
        from config.constant import StoryboardDigitalHumanConstants
        prompt = StoryboardDigitalHumanConstants.DEFAULT_PROMPT
        self.assertIn("图片1中的角色在说话。", prompt)
        self.assertIn("如画面中可见手部", prompt)
        self.assertIn("身体其余部分保持不动", prompt)


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

    def test_resolution_maps_to_max_edge(self):
        """resolution 档位由服务端映射最长边：720P→1280（修复 720P 被误传 max_edge=720）"""
        voice = MagicMock(id=7, is_active=1, provider="volcengine", name="Vivi 2.0",
                          voice_type="zh_female_vv_uranus_bigtts")

        async def fake_tts(**kw):
            return {"success": True, "audio_url": "http://x/a.mp3", "duration": 5.2,
                    "computing_power": 2, "voice_name": "Vivi 2.0", "voice_type": "zh",
                    "voice_id": 7}

        cases = [
            ({"resolution": "720P"}, "720P", 1280),
            ({"resolution": "1080P"}, "1080P", 1920),
            ({"resolution": "480P"}, "480P", 720),
            ({"resolution": "720p"}, "720P", 1280),   # 小写归一
            ({"resolution": "4K"}, "720P", 1280),     # 非法档位回落默认
            ({"max_edge": 1920}, "1080P", 1920),      # 兼容旧像素值参数
            ({"max_edge": 720}, "480P", 720),         # 旧像素值按档归位
            ({}, "720P", 1280),                       # 缺省默认
        ]
        for kwargs, label, edge in cases:
            with self.subTest(kwargs=kwargs):
                with patch("script_writer_core.digital_human_tts_tools.VoiceModel") as vm, \
                     patch("script_writer_core.digital_human_tts_tools.synthesize_speech_for_user", fake_tts):
                    vm.get_by_id.return_value = voice
                    result = asyncio.run(prepare_digital_human_draft(
                        user_id="1", world_id="w", auth_token="t",
                        image_url="http://x/img.png", script_text="测试文案", voice_id=7,
                        **kwargs))
                self.assertTrue(result["success"])
                self.assertEqual(result["draft"]["resolution"], label)
                self.assertEqual(result["draft"]["max_edge"], edge)
                self.assertIn(f"{label}（最长边 {edge}）", result["message"])

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
        # 20s → 2 段，每段 4~10 分钟
        self.assertIn("8~20", result["message"])
        self.assertIn("每段约 4~10 分钟", result["message"])

    def test_35s_routes_multi_segment(self):
        """TTS 实测 35s → 分段拼接（4 段），不再有 30s 拒绝"""
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

        self.assertTrue(result["success"])
        draft = result["draft"]
        self.assertTrue(draft["segment_mode"])
        self.assertEqual(draft["billable_duration"], 36)  # estimate(35): 3 段各 ceil(11.67)=12
        self.assertEqual(len(draft["segment_durations_est"]), 3)
        self.assertEqual(len(_DRAFT_STORE), 1)
        # 35s → 3 段，每段 4~10 分钟
        self.assertIn("12~30", result["message"])

    def test_user_audio_duration_probed_for_routing(self):
        """用户直供音频缺时长时补 probe：15s → H3 单段（显存充裕恢复）"""
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
        self.assertFalse(draft["segment_mode"], "15s 显存充裕后恢复单段直出")
        self.assertEqual(draft["billable_duration"], 15)

    def test_motion_prompt_does_not_skip_vl_voice_picking(self):
        """回归 750aba96：传 motion_prompt 不应阻断 VL 看图选音色。

        旧条件 need_vl_analysis=(not motion_prompt) and ... 让专家按 SOP 传
        motion_prompt 时整体跳过 VL 选音色，voice_id 保持 None 流到下游
        int(None) 崩溃，异常文案被误判为"语音服务不可用"。
        """
        voice = MagicMock(id=7, is_active=1, provider="volcengine", name="Vivi 2.0",
                          voice_type="zh_female_vv_uranus_bigtts")
        picked_calls = []

        async def fake_tts(**kw):
            return {"success": True, "audio_url": "http://x/a.mp3", "duration": 5.2,
                    "computing_power": 2, "voice_name": "Vivi 2.0", "voice_type": "zh",
                    "voice_id": kw.get("voice_id")}

        async def fake_pick(image_url, candidates, user_id, requirement=""):
            picked_calls.append({"image_url": image_url, "candidates": candidates})
            return {"voice_id": 7, "reason": "女性角色",
                    "motion_prompt": "角色面向镜头深情的说话，固定镜头。"}

        def fake_candidates(*a, **k):
            return [{"id": 7, "name": "Vivi 2.0"}]

        async def fake_locked_prompt(image_url, user_id):
            return {"success": True, "prompt": "integrated_multimodal_description: shot"}

        with patch("script_writer_core.digital_human_tts_tools.VoiceModel") as vm, \
             patch("script_writer_core.digital_human_tts_tools.synthesize_speech_for_user", fake_tts), \
             patch("script_writer_core.digital_human_tts_tools._pick_voice_by_image", fake_pick), \
             patch("script_writer_core.digital_human_tts_tools._load_voice_candidates", fake_candidates), \
             patch("script_writer_core.digital_human_tts_tools._generate_locked_camera_prompt", fake_locked_prompt):
            vm.get_by_id.return_value = voice
            result = asyncio.run(prepare_digital_human_draft(
                user_id="1", world_id="w", auth_token="t",
                image_url="http://x/img.png", script_text="测试文案",
                motion_prompt="角色面向镜头专业讲解，手上有自然的手势动作，固定镜头"))

        self.assertTrue(result["success"], result.get("error"))
        # 传了 motion_prompt 也必须走了 VL 选音色（而非跳过）
        self.assertEqual(len(picked_calls), 1, "传 motion_prompt 不应跳过 VL 看图选音色")
        self.assertEqual(result["draft"]["voice_id"], 7)
        # 显式 motion_prompt 优先于 VL 生成的动作提示词
        self.assertIn("专业讲解", result["draft"]["motion_prompt"])

    def test_explicit_voice_and_motion_skip_vl_analysis(self):
        """音色与动作提示词都显式给出时走快速路径：不触发 VL 分析（省一次调用），
        显式参数原样保留"""
        voice = MagicMock(id=9, is_active=1, provider="volcengine", name="Vivi 2.0",
                          voice_type="zh_female_vv_uranus_bigtts")

        async def fake_tts(**kw):
            return {"success": True, "audio_url": "http://x/a.mp3", "duration": 5.2,
                    "computing_power": 2, "voice_name": "Vivi 2.0", "voice_type": "zh",
                    "voice_id": kw.get("voice_id")}

        async def fake_pick(*a, **k):
            raise AssertionError("音色与动作提示词均已显式指定，不应触发 VL 分析")

        async def fake_locked_prompt(image_url, user_id):
            return {"success": True, "prompt": "integrated_multimodal_description: shot"}

        with patch("script_writer_core.digital_human_tts_tools.VoiceModel") as vm, \
             patch("script_writer_core.digital_human_tts_tools.is_tts_configured", return_value=True), \
             patch("script_writer_core.digital_human_tts_tools.synthesize_speech_for_user", fake_tts), \
             patch("script_writer_core.digital_human_tts_tools._pick_voice_by_image", fake_pick), \
             patch("script_writer_core.digital_human_tts_tools._generate_locked_camera_prompt", fake_locked_prompt):
            vm.get_by_id.return_value = voice
            result = asyncio.run(prepare_digital_human_draft(
                user_id="1", world_id="w", auth_token="t",
                image_url="http://x/img.png", script_text="测试文案",
                voice_id=9, motion_prompt="角色面向镜头专业讲解，固定镜头"))

        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["draft"]["voice_id"], 9)
        self.assertIn("专业讲解", result["draft"]["motion_prompt"])

    def test_invalid_voice_id_rejected_with_clear_error(self):
        """LLM 工具调用可能传入非数字 voice_id（如 'abc'）：必须返回指向参数本身的
        明确错误，而不是在深处抛出 int() TypeError 被包装成"准备数字人草案异常"
        （750aba96 同类报错的加固）"""
        result = asyncio.run(prepare_digital_human_draft(
            user_id="1", world_id="w", auth_token="t",
            image_url="http://x/img.png", script_text="文案", voice_id="abc"))

        self.assertFalse(result["success"])
        self.assertIn("voice_id 必须是数字", result["error"])
        self.assertNotIn("准备数字人草案异常", result["error"])


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

    def test_confirm_long_locked_prompt_not_truncated(self):
        """12824 回归：VL 生成的锁镜头提示词超 1000 字符时，提交给 webapp 214 节点的
        text 必须完整下发——旧实现 [:1000] 把提示词切断在单词中间并丢掉
        overall_soundscape / non_diegetic_music 结构化结尾，诱发 H3 尾部淡出黑屏"""
        long_prompt = ("integrated_multimodal_description: [Shot 1] A static medium shot of "
                       + "a female Asian doctor with detailed scene description. " * 22
                       + "\noverall_soundscape: gentle ambient sounds.\n"
                         "non_diegetic_music: [leave empty]")
        self.assertGreater(len(long_prompt), 1000)
        draft_id = _store_draft({
            "script_text": "测试", "image_url": "http://x/img.png",
            "audio_url": "http://x/a.mp3", "voice_name": "Vivi 2.0",
            "h3_locked_prompt": long_prompt,
            "model_task_type": TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3,
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
            return FakeResp({"success": True, "project_id": 556})

        cfg = MagicMock()
        cfg.get.return_value = {"host": "http://localhost:13003"}
        with patch("script_writer_core.digital_human_tts_tools.get_config", return_value=cfg), \
             patch("script_writer_core.digital_human_tts_tools.httpx.AsyncClient.get", fake_get), \
             patch("script_writer_core.digital_human_tts_tools.httpx.post", side_effect=fake_post):
            result = asyncio.run(confirm_digital_human(
                user_id="1", world_id="w", auth_token="tok", draft_id=draft_id))

        self.assertTrue(result["success"])
        self.assertEqual(captured["data"]["text"], long_prompt,
                         "超 1000 字符的锁镜头提示词不得截断，须含结构化结尾")
        self.assertTrue(captured["data"]["text"].endswith("non_diegetic_music: [leave empty]"))

    def test_confirm_dispatches_segmented(self):
        """分段草案 → 提交 /api/digital-human-minimax-h3：
        text 强制固定镜头提示词、segment_durations JSON、segment_audio 文件随 multipart 上传"""
        draft_id = _store_draft({
            "script_text": "长文案", "image_url": "http://x/img.png",
            "audio_url": "/upload/character/voice/local.mp3", "voice_name": "v",
            "motion_prompt": "角色面向镜头深情的说话，缓慢推近。",
            "effective_motion_prompt": SEGMENTED_MOTION_PROMPT,
            "h3_locked_prompt": "integrated_multimodal_description: [Shot 1] A static medium shot of a test subject.",
            "model_task_type": TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3,
            "routing_reason": "duration_gt_10s_h3_segmented",
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
        self.assertEqual(
            captured["data"]["text"],
            "integrated_multimodal_description: [Shot 1] A static medium shot of a test subject.",
            "锁镜头 webapp 的 214 必须下发英文 integrated_multimodal_description 提示词")
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
        self.assertIsNotNone(get_draft(draft_id), "确认失败应放回草案，同一 draft_id 可再试")

    def test_confirm_missing_server_keeps_draft(self):
        draft_id = _store_draft({
            "script_text": "测试", "image_url": "http://x/i.png",
            "audio_url": "http://x/a.mp3", "h3_duration": 5,
            "h3_computing_power": 6, "max_edge": 1280,
        })
        cfg = MagicMock()
        cfg.get.return_value = {}
        with patch("script_writer_core.digital_human_tts_tools.get_config", return_value=cfg):
            result = asyncio.run(confirm_digital_human(
                user_id="1", world_id="w", auth_token="t", draft_id=draft_id))
        self.assertFalse(result["success"])
        self.assertIn("服务器地址", result["error"])
        self.assertEqual(get_draft(draft_id)["audio_url"], "http://x/a.mp3")


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
            plan = split_audio_into_segments(src, 28.5, out_dir, max_seg=10)
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
