"""MiniMax H3 AutoDL.Art 驱动：素材槽位构造、分辨率映射、提交/轮询协议。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from task.visual_drivers.minimax_h3_autodl_v1_driver import (
    MinimaxH3AutodlV1Driver,
    MinimaxH3FirstLastAutodlV1Driver,
    MinimaxH3ReferenceAutodlV1Driver,
)

MODULE = "task.visual_drivers.minimax_h3_autodl_v1_driver"


def make_driver(cls=MinimaxH3ReferenceAutodlV1Driver, workflow_id="minimax_h3_zm_u24", driver_type=37):
    """绕过 __init__（避免触发配置校验/DB），直接注入依赖"""
    driver = cls.__new__(cls)
    driver._workflow_id = workflow_id
    driver._base_url = "https://autodl.art"
    driver._api_key = "test-token"
    driver._timeout = 30
    driver._config = {}
    driver._test_mode_enabled = False
    driver._mock_video_url = None
    driver.logger = MagicMock()
    return driver


def make_ai_tool(**overrides):
    base = {
        "id": 1,
        "type": 37,
        "image_path": None,
        "image_path_2": None,
        "reference_images": '["img1.png", "img2.png", "img3.png"]',
        "audio_path": None,
        "video_path": None,
        "prompt": "两个人在跳舞",
        "duration": 8,
        "ratio": "9:16",
        "extra_config": '{"image_mode": "multi_reference"}',
        "message": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def fake_upload_factory():
    """图片/音频转公网 URL 的统一 fake：路径 → https://cdn.example/<文件名>"""
    def _fake(path, *args, **kwargs):
        name = str(path).rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return True, f"https://cdn.example/{name}", None
    return _fake


# ==================== 参考生视频（zm_u24）请求构造 ====================

def test_reference_build_request_maps_image_and_audio_slots():
    driver = make_driver()
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake), \
         patch(f"{MODULE}.upload_media_to_cdn_sync", side_effect=fake):
        request = driver.build_create_request(make_ai_tool(
            prompt='李明环视众人后说："今天天气真好。"',
            audio_path="voice1.wav,voice2.wav,voice3.wav,voice4.wav",
        ))

    assert request["url"] == "https://autodl.art/api/v1/comfyui/comfyui_workflow/minimax_h3_zm_u24"
    assert request["method"] == "POST"
    # 裸 token（无 Bearer 前缀）
    assert request["headers"]["Authorization"] == "test-token"
    payload = request["json"]
    # 3 张参考图 → ref_image_0~2
    assert payload["ref_image_0"] == "https://cdn.example/img1.png"
    assert payload["ref_image_1"] == "https://cdn.example/img2.png"
    assert payload["ref_image_2"] == "https://cdn.example/img3.png"
    assert "ref_image_3" not in payload
    # 有对白（引号台词）→ 音频上传，超出 3 段截断
    assert payload["ref_audio_0"] == "https://cdn.example/voice1.wav"
    assert payload["ref_audio_1"] == "https://cdn.example/voice2.wav"
    assert payload["ref_audio_2"] == "https://cdn.example/voice3.wav"
    assert "ref_audio_3" not in payload
    # 基础字段：9:16 竖屏 + 默认 768p → 768p竖
    assert payload["prompt"] == '李明环视众人后说："今天天气真好。"'
    assert payload["duration"] == 8
    assert payload["resolution"] == "768p竖"


def test_reference_build_request_no_dialogue_skips_audio_and_strips_voice_note():
    driver = make_driver()
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake), \
         patch(f"{MODULE}.upload_media_to_cdn_sync", side_effect=fake):
        request = driver.build_create_request(make_ai_tool(
            prompt="两人对视。参考音频说明：角色说话时请保持相同音色",
            audio_path="voice1.wav",
        ))

    payload = request["json"]
    # 无对白：音频跳过、音色说明句剥除
    assert "ref_audio_0" not in payload
    assert "参考音频说明" not in payload["prompt"]
    assert payload["prompt"] == "两人对视。"


def test_reference_build_request_requires_at_least_one_image():
    driver = make_driver()
    result = driver.build_create_request(make_ai_tool(reference_images=None, extra_config="{}"))
    assert result["success"] is False
    assert result["error_type"] == "USER"
    assert "参考图" in result["error"]


def test_reference_build_request_resolution_and_ratio_matrix():
    driver = make_driver()
    fake = fake_upload_factory()
    cases = [
        # (resolution标准值, ratio, 期望 autodl 值)
        ("480P", "9:16", "480p竖"),
        ("720P", "16:9", "768p横"),
        ("480P", "1:1", "480p(1:1)"),
        ("720P", "1:1", "768p(1:1)"),
        ("480P", "4:3", "480p横"),
        ("720P", "3:4", "768p竖"),
        (None, "9:16", "768p竖"),  # 未配置分辨率回落 768p
    ]
    for resolution, ratio, expected in cases:
        extra = '{"image_mode": "multi_reference"}'
        if resolution:
            extra = '{"image_mode": "multi_reference", "video_resolution": "%s"}' % resolution
        with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake), \
             patch(f"{MODULE}.upload_media_to_cdn_sync", side_effect=fake):
            request = driver.build_create_request(make_ai_tool(ratio=ratio, extra_config=extra))
        assert request["json"]["resolution"] == expected, f"{resolution} {ratio} -> {expected}"


# ==================== 首尾帧（lightx2v）请求构造 ====================

def make_first_last_tool(**overrides):
    base = {
        "id": 2,
        "type": 34,
        # 首尾帧经 image_path 逗号分隔解析（base.get_first_last_frames）
        "image_path": "first.png,last.png",
        "reference_images": None,
        "audio_path": None,
        "video_path": None,
        "prompt": "角色缓缓转身",
        "duration": 5,
        "ratio": "16:9",
        "extra_config": '{"image_mode": "first_last_frame"}',
        "message": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_first_last_build_request_maps_frames():
    driver = make_driver(MinimaxH3FirstLastAutodlV1Driver, "minimax_h3_lightx2v", 34)
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        request = driver.build_create_request(make_first_last_tool())

    assert request["url"] == "https://autodl.art/api/v1/comfyui/comfyui_workflow/minimax_h3_lightx2v"
    payload = request["json"]
    assert payload["first_frame"] == "https://cdn.example/first.png"
    assert payload["last_frame"] == "https://cdn.example/last.png"
    assert payload["duration"] == 5
    assert payload["resolution"] == "768p横"
    # lightx2v 无音频槽
    assert not any(k.startswith("ref_audio_") for k in payload)


def test_first_last_requires_last_frame():
    driver = make_driver(MinimaxH3FirstLastAutodlV1Driver, "minimax_h3_lightx2v", 34)
    # 单图 → 只有首帧无尾帧，官方 API 要求尾帧必填
    result = driver.build_create_request(make_first_last_tool(image_path="first.png"))
    assert result["success"] is False
    assert result["error_type"] == "USER"
    assert "尾帧" in result["error"]


def test_first_last_requires_first_frame():
    driver = make_driver(MinimaxH3FirstLastAutodlV1Driver, "minimax_h3_lightx2v", 34)
    result = driver.build_create_request(make_first_last_tool(image_path=None))
    assert result["success"] is False
    assert result["error_type"] == "USER"
    assert "首帧" in result["error"]


def test_duration_clamped_to_workflow_bounds():
    driver = make_driver()
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        # 超上限钳到 15
        request = driver.build_create_request(make_ai_tool(duration=99))
        assert request["json"]["duration"] == 15
        # 超下限钳到 1
        request = driver.build_create_request(make_ai_tool(duration=-3))
        assert request["json"]["duration"] == 1
        # 0/None 视为未设置 → 默认 5
        request = driver.build_create_request(make_ai_tool(duration=0))
        assert request["json"]["duration"] == 5
        request = driver.build_create_request(make_ai_tool(duration=None))
        assert request["json"]["duration"] == 5


# ==================== 提交任务协议 ====================

def test_submit_task_success_extracts_project_id():
    driver = make_driver()
    ai_tool = make_ai_tool()
    fake = fake_upload_factory()
    response = {
        "code": "Success",
        "data": {"task_id": "671ce5ca-80b3", "status": "QUEUED", "client_id": "c1"},
        "msg": "",
        "request_id": "r1",
    }
    driver._request = MagicMock(return_value=response)
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        result = driver.submit_task(ai_tool)

    assert result["success"] is True
    assert result["project_id"] == "671ce5ca-80b3"
    # 请求参数校验
    call = driver._request.call_args
    assert call.kwargs["url"].endswith("/minimax_h3_zm_u24")
    assert call.kwargs["headers"]["Authorization"] == "test-token"


def test_submit_task_business_error_returns_user_error():
    driver = make_driver()
    driver._request = MagicMock(return_value={"code": "PARAM_ERROR", "msg": "prompt 不能为空"})
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        result = driver.submit_task(make_ai_tool())

    assert result["success"] is False
    assert result["error_type"] == "USER"
    assert result["retry"] is False
    assert "prompt 不能为空" in result["error"]


def test_submit_task_invalid_response_format_alerts():
    driver = make_driver()
    driver._request = MagicMock(return_value={"unexpected": True})
    driver._send_alert = MagicMock()
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        result = driver.submit_task(make_ai_tool())

    assert result["success"] is False
    assert result["error_type"] == "SYSTEM"
    driver._send_alert.assert_called_once()


def test_submit_task_http_429_returns_retryable():
    driver = make_driver()
    response = MagicMock(status_code=429)
    response.json.return_value = {"code": "RATE_LIMIT", "msg": "请求过于频繁"}
    http_error = requests.exceptions.HTTPError(response=response)
    driver._request = MagicMock(side_effect=http_error)
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        result = driver.submit_task(make_ai_tool())

    assert result["success"] is False
    assert result["retry"] is True


def test_submit_task_network_error_returns_retryable():
    driver = make_driver()
    driver._request = MagicMock(side_effect=ConnectionError("refused"))
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        result = driver.submit_task(make_ai_tool())

    assert result["success"] is False
    assert result["retry"] is True


# ==================== 查询状态协议 ====================

def test_check_status_running_states():
    driver = make_driver()
    for raw in ("QUEUED", "RUNNING", "PENDING"):
        driver._request = MagicMock(return_value={
            "code": "Success",
            "data": {"status": raw, "results": []},
            "msg": "",
        })
        result = driver.check_status("t1")
        assert result["status"] == "RUNNING", raw


def test_check_status_success_extracts_result_url():
    driver = make_driver()
    driver._request = MagicMock(return_value={
        "code": "Success",
        "data": {
            "status": "completed",  # 工作流页输出示例为小写 completed
            "results": [{"url": "https://dl.autodl/v.mp4", "type": "video", "file_type": "mp4"}],
            "task_id": "t1",
        },
        "msg": "",
    })
    result = driver.check_status("t1")
    assert result["status"] == "SUCCESS"
    assert result["result_url"] == "https://dl.autodl/v.mp4"
    # 查询 URL 校验
    assert driver._request.call_args.kwargs["url"].endswith("/result/t1")


def test_check_status_success_without_url_fails():
    driver = make_driver()
    driver._send_alert = MagicMock()
    driver._request = MagicMock(return_value={
        "code": "Success",
        "data": {"status": "SUCCESS", "results": []},
        "msg": "",
    })
    result = driver.check_status("t1")
    assert result["status"] == "FAILED"
    assert result["error_type"] == "SYSTEM"


def test_check_status_failed_returns_user_error():
    driver = make_driver()
    driver._request = MagicMock(return_value={
        "code": "Success",
        "data": {"status": "FAILED", "message": "内容审核未通过"},
        "msg": "",
    })
    result = driver.check_status("t1")
    assert result["status"] == "FAILED"
    assert result["error_type"] == "USER"
    assert "内容审核未通过" in result["error"]


def test_check_status_unknown_state_keeps_running():
    driver = make_driver()
    driver._request = MagicMock(return_value={
        "code": "Success",
        "data": {"status": "WEIRD_STATE"},
        "msg": "",
    })
    result = driver.check_status("t1")
    assert result["status"] == "RUNNING"


def test_check_status_query_business_error_fails_as_system():
    driver = make_driver()
    driver._request = MagicMock(return_value={"code": "TASK_NOT_FOUND", "msg": "任务不存在"})
    result = driver.check_status("t1")
    assert result["status"] == "FAILED"
    assert result["error_type"] == "SYSTEM"
    assert "任务不存在" in result["error"]


def test_check_status_http_404_keeps_running():
    """任务刚提交存在上游传播延迟，404 不判死（任务过期检查兜底）"""
    driver = make_driver()
    response = MagicMock(status_code=404)
    http_error = requests.exceptions.HTTPError(response=response)
    driver._request = MagicMock(side_effect=http_error)
    result = driver.check_status("t1")
    assert result["status"] == "RUNNING"


def test_check_status_http_5xx_keeps_running():
    """上游 5xx 为临时故障：判死会误退款且上游任务可能仍在跑（计费），保持轮询"""
    driver = make_driver()
    for status in (500, 502, 503):
        response = MagicMock(status_code=status)
        http_error = requests.exceptions.HTTPError(response=response)
        driver._request = MagicMock(side_effect=http_error)
        result = driver.check_status("t1")
        assert result["status"] == "RUNNING", status


def test_check_status_http_4xx_still_fails():
    """非 404/429 的 4xx（如 401/403 认证失败）仍判失败"""
    driver = make_driver()
    driver._send_alert = MagicMock()
    response = MagicMock(status_code=403)
    http_error = requests.exceptions.HTTPError(response=response)
    driver._request = MagicMock(side_effect=http_error)
    result = driver.check_status("t1")
    assert result["status"] == "FAILED"


# ==================== 输入契约能力校验（validate_input_compatibility） ====================

def test_first_last_compat_single_first_frame_incompatible():
    """首尾帧双必填：单首帧任务切到本实现必然 USER 失败，判不兼容（重试换下一候选）"""
    driver = make_driver(MinimaxH3FirstLastAutodlV1Driver, "minimax_h3_lightx2v", 34)
    compatible, reason = driver.validate_input_compatibility(
        make_first_last_tool(image_path="first.png"))
    assert compatible is False
    assert "尾帧" in reason


def test_first_last_compat_both_frames_compatible():
    driver = make_driver(MinimaxH3FirstLastAutodlV1Driver, "minimax_h3_lightx2v", 34)
    compatible, reason = driver.validate_input_compatibility(make_first_last_tool())
    assert compatible is True
    assert reason is None


def test_first_last_compat_no_first_frame_not_blocked():
    """无首帧属参数错误（RunningHub 实现同样失败），不属能力差异，不在此拦截"""
    driver = make_driver(MinimaxH3FirstLastAutodlV1Driver, "minimax_h3_lightx2v", 34)
    compatible, _ = driver.validate_input_compatibility(make_first_last_tool(image_path=None))
    assert compatible is True


def test_reference_compat_with_video_incompatible():
    """zm_u24 无参考视频槽：带视频任务切到本实现会静默丢视频参考，判不兼容"""
    driver = make_driver()
    compatible, reason = driver.validate_input_compatibility(
        make_ai_tool(video_path="ref.mp4"))
    assert compatible is False
    assert "参考视频" in reason


def test_reference_compat_without_video_compatible():
    driver = make_driver()
    compatible, reason = driver.validate_input_compatibility(make_ai_tool(video_path=None))
    assert compatible is True
    assert reason is None


def test_check_status_network_error_keeps_running():
    driver = make_driver()
    driver._request = MagicMock(side_effect=TimeoutError("boom"))
    result = driver.check_status("t1")
    assert result["status"] == "RUNNING"


# ==================== 响应校验 ====================

def test_validate_submit_response_formats():
    driver = make_driver()
    # 成功
    ok, err = driver._validate_submit_response(
        {"code": "Success", "data": {"task_id": "x"}, "msg": ""})
    assert ok and err is None
    # 成功但缺 task_id → 格式错误
    ok, err = driver._validate_submit_response({"code": "Success", "data": {}})
    assert not ok and "task_id" in err
    # 业务错误（带 msg）→ 格式有效
    ok, err = driver._validate_submit_response({"code": "AUTH_FAIL", "msg": "token 无效"})
    assert ok and err is None
    # 非字典 → 格式错误
    ok, err = driver._validate_submit_response("bad")
    assert not ok


def test_validate_status_response_formats():
    driver = make_driver()
    ok, err = driver._validate_status_response(
        {"code": "Success", "data": {"status": "RUNNING"}})
    assert ok and err is None
    ok, err = driver._validate_status_response({"code": "Success", "data": {}})
    assert not ok
    ok, err = driver._validate_status_response({"code": "E", "msg": "x"})
    assert ok
