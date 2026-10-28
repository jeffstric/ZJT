"""数字人（MiniMax H3）服务本体回归测试。

背景：70bcc0a9..821d599f 窗口内该服务多轮演进（TTS 时长聚合 → clamp 计费口径
→ 多段音频下载/合并 → 五态就绪判定 → 同步扣费），是 api/storyboard.py 两个
端点与 Agent 工具的共同底层。此前工具执行器层把 orchestrate/submit 全部
mock 掉，服务本体零直接测试。

覆盖：
- _sum_tts_duration 时长聚合与 unknown 语义
- clamp_minimax_video_duration 硬限制 4-10s（计费口径的根）
- resolve_max_edge_from_resolution 分辨率映射与非法值兜底
- build_digital_human_generation_plan 时长优先级（TTS 总时长 → scene.duration）
- orchestrate_digital_human_generation 错误码链
- plan_digital_human_ready 五态映射
- deduct_computing_power_sync 跳过/失败语义
- prepare_digital_human_audio_input 单段不合并、多段合并失败不扣费
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from config.constant import StoryboardDigitalHumanConstants as _DHC
from services import storyboard_digital_human_service as dh_svc
from services.storyboard_digital_human_service import (
    StoryboardDigitalHumanError,
    TtsSegment,
    clamp_minimax_video_duration,
    resolve_max_edge_from_resolution,
)


def _seg(duration, url="https://cdn.example.com/a.wav"):
    return TtsSegment(dialogue_id=1, audio_url=url, duration=duration)


# ---------------------------------------------------------------- 时长聚合
def test_sum_tts_duration_adds_known_segments():
    total, any_unknown = dh_svc._sum_tts_duration([_seg(3.0), _seg(2.5)])
    assert (total, any_unknown) == (5.5, False)


def test_sum_tts_duration_unknown_when_any_missing():
    total, any_unknown = dh_svc._sum_tts_duration([_seg(3.0), _seg(None), _seg(0)])
    assert total is None
    assert any_unknown is True


def test_sum_tts_duration_empty_is_zero():
    total, any_unknown = dh_svc._sum_tts_duration([])
    assert (total, any_unknown) == (0, False)


# ---------------------------------------------------------------- clamp（计费口径根）
def test_clamp_inside_range_returns_ceiled_seconds():
    assert clamp_minimax_video_duration(6.2) == (7, "none")


def test_clamp_floor_below_4():
    assert clamp_minimax_video_duration(1.0) == (4, "floor_to_4")


def test_clamp_ceil_above_10():
    assert clamp_minimax_video_duration(23.0) == (10, "ceil_to_10")


def test_clamp_invalid_or_none_falls_back_to_default():
    assert clamp_minimax_video_duration(None) == (
        int(_DHC.DEFAULT_VIDEO_DURATION), "none")
    assert clamp_minimax_video_duration("abc") == (
        int(_DHC.DEFAULT_VIDEO_DURATION), "none")
    assert clamp_minimax_video_duration(-3) == (
        int(_DHC.DEFAULT_VIDEO_DURATION), "none")


# ---------------------------------------------------------------- 分辨率映射
def test_resolution_maps_known_labels():
    assert resolve_max_edge_from_resolution("480P") == ("480P", 720)
    assert resolve_max_edge_from_resolution("720p") == ("720P", 1280)
    assert resolve_max_edge_from_resolution("1080P") == ("1080P", 1920)


def test_resolution_invalid_falls_back_to_default():
    normalized, edge = resolve_max_edge_from_resolution("8K")
    assert normalized == _DHC.DEFAULT_RESOLUTION
    assert edge == int(_DHC.DEFAULT_MAX_EDGE)


def test_resolution_empty_uses_default():
    normalized, edge = resolve_max_edge_from_resolution(None)
    assert normalized == _DHC.DEFAULT_RESOLUTION
    assert edge == int(_DHC.DEFAULT_MAX_EDGE)


# ---------------------------------------------------------------- 计划构建
def _make_plan_env(monkeypatch, *, tts_total=6.0, scene_duration=None):
    """monkeypatch UnifiedConfigRegistry/首帧解析，返回构建参数。"""
    cfg = MagicMock()
    cfg.get_computing_power.return_value = 100
    monkeypatch.setattr(
        dh_svc.UnifiedConfigRegistry, "get_by_id", staticmethod(lambda _tid: cfg))
    monkeypatch.setattr(
        dh_svc, "_resolve_first_frame_path",
        lambda scene: "/upload/first_frame.png")
    scene = SimpleNamespace(
        selected_first_frame_id=None, duration=scene_duration, workflow_ratio="16:9")
    storyboard = SimpleNamespace(workflow_ratio="16:9")
    dialogues = [{"text": " 你好，世界 "}]
    segments = [_seg(tts_total / 2), _seg(tts_total / 2)]
    return scene, storyboard, dialogues, segments


def test_build_plan_prefers_tts_total_over_scene_duration(monkeypatch):
    scene, storyboard, dialogues, segments = _make_plan_env(
        monkeypatch, tts_total=6.0, scene_duration=99.0)
    plan = dh_svc.build_digital_human_generation_plan(
        scene, storyboard, 5, dialogues, segments)
    # TTS 可用时优先 TTS 总时长，不吃 scene.duration
    assert plan.speech_duration == 6.0
    assert plan.billable_duration == 6
    assert plan.duration_clamp_reason == "none"
    assert plan.speech_text == "你好，世界"  # 拼接去空格
    assert plan.first_frame_path == "/upload/first_frame.png"
    assert plan.ratio == "16:9"


def test_build_plan_falls_back_to_scene_duration_when_tts_unknown(monkeypatch):
    scene, storyboard, dialogues, segments = _make_plan_env(
        monkeypatch, tts_total=0, scene_duration=8.0)
    segments = [_seg(None)]
    plan = dh_svc.build_digital_human_generation_plan(
        scene, storyboard, 5, dialogues, segments)
    assert plan.speech_duration is None  # unknown 不冒充 TTS 时长
    assert plan.billable_duration == 8


def test_build_plan_requires_model_config(monkeypatch):
    scene, storyboard, dialogues, segments = _make_plan_env(monkeypatch)
    # 后打 mock：_make_plan_env 内部会先打 get_by_id
    monkeypatch.setattr(
        dh_svc.UnifiedConfigRegistry, "get_by_id", staticmethod(lambda _tid: None))
    with pytest.raises(StoryboardDigitalHumanError) as exc_info:
        dh_svc.build_digital_human_generation_plan(
            scene, storyboard, 5, dialogues, segments)
    assert exc_info.value.code == _DHC.ERROR_MODEL_UNAVAILABLE


# ---------------------------------------------------------------- 编排错误码链
def test_orchestrate_rejects_missing_scene(monkeypatch):
    monkeypatch.setattr(
        dh_svc.StoryboardSceneModel, "get_by_id",
        staticmethod(lambda _sid: None), raising=False)
    with pytest.raises(StoryboardDigitalHumanError) as exc_info:
        dh_svc.orchestrate_digital_human_generation(999, prepare_audio=False)
    assert exc_info.value.code == "not_found"


def test_orchestrate_rejects_non_digital_human_scene(monkeypatch):
    from config.unified_config import SceneVideoType
    monkeypatch.setattr(
        dh_svc.StoryboardSceneModel, "get_by_id",
        staticmethod(lambda _sid: SimpleNamespace(video_type=SceneVideoType.VIDEO)),
        raising=False)
    with pytest.raises(StoryboardDigitalHumanError) as exc_info:
        dh_svc.orchestrate_digital_human_generation(1, prepare_audio=False)
    assert exc_info.value.code == "invalid_video_type"


def test_orchestrate_requires_tts_segments(monkeypatch):
    from config.unified_config import SceneVideoType
    monkeypatch.setattr(
        dh_svc.StoryboardSceneModel, "get_by_id",
        staticmethod(lambda _sid: SimpleNamespace(
            video_type=SceneVideoType.DIGITAL_HUMAN, storyboard_id=1)),
        raising=False)
    monkeypatch.setattr(
        dh_svc, "resolve_digital_human_dialogues", lambda *_a, **_k: (5, []))
    monkeypatch.setattr(
        dh_svc, "load_digital_human_tts_metadata", lambda _d: [])
    with pytest.raises(StoryboardDigitalHumanError) as exc_info:
        dh_svc.orchestrate_digital_human_generation(1, prepare_audio=False)
    assert exc_info.value.code == _DHC.ERROR_AUDIO_REQUIRED


# ---------------------------------------------------------------- 五态就绪映射
def _patch_scene(monkeypatch, exists=True):
    monkeypatch.setattr(
        dh_svc.StoryboardSceneModel, "get_by_id",
        staticmethod(lambda _sid: SimpleNamespace(id=_sid) if exists else None),
        raising=False)


def test_plan_ready_when_orchestrate_succeeds(monkeypatch):
    _patch_scene(monkeypatch)
    monkeypatch.setattr(
        dh_svc, "orchestrate_digital_human_generation",
        lambda *_a, **_k: (None, [], None, None))
    assert dh_svc.plan_digital_human_ready(1) == ("ready", "")


def test_plan_ready_maps_error_codes_to_statuses(monkeypatch):
    _patch_scene(monkeypatch)

    def raising(code):
        def _raise(*_a, **_k):
            raise StoryboardDigitalHumanError(code, "x")
        return _raise

    cases = {
        _DHC.ERROR_AUDIO_PENDING: "audio_pending",
        _DHC.ERROR_AUDIO_REQUIRED: "missing_audio",
        _DHC.ERROR_MISSING_IMAGE: "missing_image",
        "whatever": "invalid",
    }
    for code, expected_status in cases.items():
        monkeypatch.setattr(
            dh_svc, "orchestrate_digital_human_generation", raising(code))
        status, _reason = dh_svc.plan_digital_human_ready(1)
        assert status == expected_status, f"code={code}"


def test_plan_ready_invalid_when_scene_missing(monkeypatch):
    _patch_scene(monkeypatch, exists=False)
    assert dh_svc.plan_digital_human_ready(999) == ("invalid", "not_found")


# ---------------------------------------------------------------- 同步扣费
def test_deduct_skips_without_token_or_zero_power():
    assert dh_svc.deduct_computing_power_sync("", 10, "tx") == (True, "")
    assert dh_svc.deduct_computing_power_sync("tok", 0, "tx") == (True, "")
    assert dh_svc.deduct_computing_power_sync("tok", None, "tx") == (True, "")


def test_deduct_returns_failure_on_request_error(monkeypatch):
    import perseids_server.client as client
    monkeypatch.setattr(
        client, "make_perseids_request",
        MagicMock(side_effect=RuntimeError("connection refused")))
    ok, message = dh_svc.deduct_computing_power_sync("tok", 10, "tx-1")
    assert ok is False
    assert "connection refused" in message


def test_deduct_forwards_bearer_and_payload(monkeypatch):
    import perseids_server.client as client
    mock = MagicMock(return_value=(True, "ok", {}))
    monkeypatch.setattr(client, "make_perseids_request", mock)
    ok, _ = dh_svc.deduct_computing_power_sync("raw-token", 12.5, "tx-2")
    assert ok is True
    _args, kwargs = mock.call_args
    assert kwargs["headers"] == {"Authorization": "Bearer raw-token"}
    assert kwargs["data"]["computing_power"] == 12.5
    assert kwargs["data"]["behavior"] == "deduct"
    assert kwargs["data"]["transaction_id"] == "tx-2"


# ---------------------------------------------------------------- 音频准备
def test_prepare_single_segment_returns_plan_unchanged(monkeypatch):
    scene, storyboard, dialogues, segments = _make_plan_env(monkeypatch)
    plan = dh_svc.build_digital_human_generation_plan(
        scene, storyboard, 5, dialogues, segments)
    result = dh_svc.prepare_digital_human_audio_input(
        plan, segments[:1], scene_id=1)
    # 单段直接用原始 URL，不触发下载/合并
    assert result.audio_input == plan.audio_input


def test_prepare_merge_failure_raises_and_never_bills(monkeypatch):
    scene, storyboard, dialogues, segments = _make_plan_env(monkeypatch)
    plan = dh_svc.build_digital_human_generation_plan(
        scene, storyboard, 5, dialogues, segments)
    monkeypatch.setattr(
        dh_svc, "_download_audio", lambda *_a, **_k: "/tmp/fake.wav")
    monkeypatch.setattr(
        dh_svc, "_merge_audio_files", lambda *_a, **_k: False)
    monkeypatch.setattr(
        dh_svc, "_task_assets_dir", lambda *_a, **_k: "/tmp")
    with pytest.raises(StoryboardDigitalHumanError) as exc_info:
        dh_svc.prepare_digital_human_audio_input(plan, segments, scene_id=1)
    assert exc_info.value.code == _DHC.ERROR_AUDIO_MERGE_FAILED


def test_prepare_download_failure_raises(monkeypatch):
    scene, storyboard, dialogues, segments = _make_plan_env(monkeypatch)
    plan = dh_svc.build_digital_human_generation_plan(
        scene, storyboard, 5, dialogues, segments)
    monkeypatch.setattr(
        dh_svc, "_download_audio", lambda *_a, **_k: None)
    monkeypatch.setattr(
        dh_svc, "_task_assets_dir", lambda *_a, **_k: "/tmp")
    with pytest.raises(StoryboardDigitalHumanError) as exc_info:
        dh_svc.prepare_digital_human_audio_input(plan, segments, scene_id=1)
    assert exc_info.value.code == _DHC.ERROR_AUDIO_MERGE_FAILED


def test_prepare_merge_success_replaces_audio_input(monkeypatch, tmp_path):
    scene, storyboard, dialogues, segments = _make_plan_env(monkeypatch)
    plan = dh_svc.build_digital_human_generation_plan(
        scene, storyboard, 5, dialogues, segments)
    monkeypatch.setattr(
        dh_svc, "_download_audio", lambda *_a, **_k: str(tmp_path / "a.wav"))
    monkeypatch.setattr(
        dh_svc, "_task_assets_dir", lambda *_a, **_k: str(tmp_path))

    monkeypatch.setattr(
        dh_svc, "_merge_audio_files",
        lambda paths, dest: (open(dest, "wb").close() or True))
    result = dh_svc.prepare_digital_human_audio_input(plan, segments, scene_id=1)
    # 合并目标由服务生成（uuid.wav），落点必须在资产目录且替换掉原始 URL
    assert result.audio_input.startswith(str(tmp_path))
    assert result.audio_input.endswith(".wav")
    assert result.audio_input != plan.audio_input
