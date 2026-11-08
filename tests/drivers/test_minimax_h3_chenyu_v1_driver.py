"""MiniMax H3 晨羽智云驱动：inputs 构造、分辨率→MP 映射、提交/轮询协议、输入契约。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from task.visual_drivers.minimax_h3_chenyu_v1_driver import MinimaxH3ChenyuV1Driver

MODULE = "task.visual_drivers.minimax_h3_chenyu_v1_driver"


def make_driver():
    """绕过 __init__（避免触发配置校验/DB），直接注入依赖"""
    driver = MinimaxH3ChenyuV1Driver.__new__(MinimaxH3ChenyuV1Driver)
    driver.driver_name = "minimax_h3_chenyu_v1"
    driver._base_url = "https://www.chenyu.cn"
    driver._api_key = "test-key"
    driver._timeout = 30
    driver._config = {}
    driver._test_mode_enabled = False
    driver._mock_video_url = None
    driver.logger = MagicMock()
    return driver


def make_ai_tool(**overrides):
    base = {
        "id": 7,
        "type": 34,
        "image_path": "first.png",
        "reference_images": None,
        "audio_path": None,
        "video_path": None,
        "prompt": "一只猫跳起来",
        "duration": 4,
        "ratio": "16:9",
        "extra_config": '{"image_mode": "first_last_frame", "video_resolution": "480P"}',
        "message": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def fake_upload_factory():
    """图片转公网 URL 的 fake：路径 → https://cdn.example/<文件名>"""
    def _fake(path, *args, **kwargs):
        name = str(path).rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return True, f"https://cdn.example/{name}", None
    return _fake


# ==================== 请求构造 ====================

def test_build_create_request_maps_inputs():
    driver = make_driver()
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        request = driver.build_create_request(make_ai_tool())

    assert request["url"] == "https://www.chenyu.cn/api/open/v2/workflow/run/submit"
    assert request["method"] == "POST"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    payload = request["json"]
    assert payload["workflow_id"] == "wf_fe451b10caa4bf0a7c99"
    assert payload["revision_id"] == "wfr_9088e3367308ac1939d0"
    # 幂等键按任务生成
    assert payload["idempotency_key"] == "zjt_h3_chenyu_7"
    assert payload["accept_external_cost_risk"] is False
    inputs = payload["inputs"]
    assert inputs["n105_104_prompt"] == "一只猫跳起来"
    assert inputs["n114_image"] == "https://cdn.example/first.png"
    assert inputs["n105_111_value"] == 4
    # 480P → 0.5MP
    assert inputs["n119_megapixels"] == 0.5


def test_build_create_request_megapixels_by_resolution():
    driver = make_driver()
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        p720 = driver.build_create_request(
            make_ai_tool(extra_config='{"image_mode": "first_last_frame", "video_resolution": "720P"}'))
        none_res = driver.build_create_request(
            make_ai_tool(extra_config='{"image_mode": "first_last_frame"}'))
    assert p720["json"]["inputs"]["n119_megapixels"] == 1.0
    # 未声明分辨率回落 1.0MP
    assert none_res["json"]["inputs"]["n119_megapixels"] == 1.0


def test_build_create_request_prefers_optimized_prompt():
    driver = make_driver()
    fake = fake_upload_factory()
    extra = ('{"image_mode": "first_last_frame", "h3_prompt_optimize": '
             '{"optimized_prompt": "optimized text"}}')
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        request = driver.build_create_request(make_ai_tool(extra_config=extra))
    assert request["json"]["inputs"]["n105_104_prompt"] == "optimized text"


def test_build_create_request_requires_first_frame():
    driver = make_driver()
    result = driver.build_create_request(make_ai_tool(image_path=None))
    assert result["success"] is False
    assert result["error_type"] == "USER"
    assert "首帧" in result["error"]


def test_build_check_query():
    driver = make_driver()
    query = driver.build_check_query("wfr_123")
    assert query["url"] == "https://www.chenyu.cn/api/open/v2/workflow/run/info"
    assert query["method"] == "GET"
    assert query["params"] == {"run_order_id": "wfr_123"}
    assert query["headers"]["Authorization"] == "Bearer test-key"


# ==================== 提交协议 ====================

def _patched_request(driver, response):
    """driver._request → 直接返回 response 字典"""
    driver._request = MagicMock(return_value=response)


def test_submit_success_returns_run_order_id():
    driver = make_driver()
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        _patched_request(driver, {
            "code": 0, "msg": "提交成功",
            "data": {"run_order_id": "wfr_abc", "run_status": "queued"},
        })
        result = driver.submit_task(make_ai_tool())
    assert result == {"success": True, "project_id": "wfr_abc"}


def test_submit_business_error_is_user_error():
    driver = make_driver()
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        _patched_request(driver, {"code": 40001, "msg": "余额不足", "data": {}})
        result = driver.submit_task(make_ai_tool())
    assert result["success"] is False
    assert result["error_type"] == "USER"
    assert result["retry"] is False
    assert "余额不足" in result["error"]


def test_submit_http_429_retryable():
    driver = make_driver()
    fake = fake_upload_factory()
    response = requests.Response()
    response.status_code = 429
    http_error = requests.exceptions.HTTPError(response=response)
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        driver._request = MagicMock(side_effect=http_error)
        result = driver.submit_task(make_ai_tool())
    assert result["success"] is False
    assert result["retry"] is True
    assert result["error_type"] == "USER"


def test_submit_missing_run_order_id_is_system_error():
    driver = make_driver()
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake), \
         patch.object(driver, "_send_alert"):
        _patched_request(driver, {"code": 0, "msg": "提交成功", "data": {}})
        result = driver.submit_task(make_ai_tool())
    assert result["success"] is False
    assert result["error_type"] == "SYSTEM"


def test_submit_idempotent_replay_logged():
    driver = make_driver()
    fake = fake_upload_factory()
    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=fake):
        _patched_request(driver, {
            "code": 0, "msg": "提交成功",
            "data": {"run_order_id": "wfr_abc", "idempotent_replay": True},
        })
        result = driver.submit_task(make_ai_tool())
    assert result["success"] is True
    assert driver.logger.info.called


# ==================== 轮询协议 ====================

def test_check_status_running():
    driver = make_driver()
    _patched_request(driver, {"code": 0, "msg": "查询成功",
                              "data": {"run_status": "queued"}})
    assert driver.check_status("wfr_abc")["status"] == "RUNNING"

    _patched_request(driver, {"code": 0, "msg": "查询成功",
                              "data": {"run_status": "running"}})
    assert driver.check_status("wfr_abc")["status"] == "RUNNING"


def test_check_status_success_extracts_video():
    driver = make_driver()
    _patched_request(driver, {
        "code": 0, "msg": "查询成功",
        "data": {"run_status": "succeeded",
                 "outputs": {"n92_images": ["https://media.chenyu.cn/x/content"]}},
    })
    result = driver.check_status("wfr_abc")
    assert result["status"] == "SUCCESS"
    assert result["result_url"] == "https://media.chenyu.cn/x/content"


def test_check_status_failed_with_message():
    driver = make_driver()
    _patched_request(driver, {
        "code": 0, "msg": "查询成功",
        "data": {"run_status": "failed", "error_message": "显存不足"},
    })
    result = driver.check_status("wfr_abc")
    assert result["status"] == "FAILED"
    assert "显存不足" in result["message"]


def test_check_status_pending_review_keeps_running():
    """内容审核阶段（E2E 实测出现）不判死，继续轮询"""
    driver = make_driver()
    _patched_request(driver, {"code": 0, "msg": "查询成功",
                              "data": {"run_status": "pending_review"}})
    assert driver.check_status("wfr_abc")["status"] == "RUNNING"


def test_check_status_order_not_found_keeps_running():
    """订单不存在（刚提交传播延迟）不判死，继续轮询"""
    driver = make_driver()
    _patched_request(driver, {"code": 1, "msg": "运行记录不存在", "data": {}})
    assert driver.check_status("wfr_abc")["status"] == "RUNNING"


def test_check_status_unknown_status_keeps_running():
    driver = make_driver()
    _patched_request(driver, {"code": 0, "msg": "查询成功",
                              "data": {"run_status": "weird_state"}})
    assert driver.check_status("wfr_abc")["status"] == "RUNNING"
    assert driver.logger.warning.called


def test_check_status_success_without_output_is_failed():
    driver = make_driver()
    with patch.object(driver, "_send_alert"):
        _patched_request(driver, {"code": 0, "msg": "查询成功",
                                  "data": {"run_status": "succeeded", "outputs": {}}})
        result = driver.check_status("wfr_abc")
    assert result["status"] == "FAILED"


# ==================== 输入契约能力校验 ====================

def test_compat_with_last_frame_incompatible():
    """带尾帧任务判不兼容（工作流无尾帧槽，避免静默丢尾帧约束）"""
    driver = make_driver()
    compatible, reason = driver.validate_input_compatibility(
        make_ai_tool(image_path="first.png,last.png"))
    assert compatible is False
    assert "尾帧" in reason


def test_compat_single_first_frame_compatible():
    driver = make_driver()
    compatible, reason = driver.validate_input_compatibility(
        make_ai_tool(image_path="first.png"))
    assert compatible is True
    assert reason is None
