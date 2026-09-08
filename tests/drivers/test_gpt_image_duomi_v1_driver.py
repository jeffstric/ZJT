import logging
import os
from types import SimpleNamespace

os.environ.setdefault("comfyui_env", "prod")

from task.visual_drivers.gpt_image_duomi_v1_driver import GptImageDuomiV1Driver


def _make_driver():
    driver = GptImageDuomiV1Driver.__new__(GptImageDuomiV1Driver)
    driver._base_url = "https://duomi.example.com"
    driver._token = "test-token"
    driver.logger = logging.getLogger("test_gpt_image_duomi")
    driver._timeout = 30
    driver._send_alert = lambda **kwargs: None
    driver.build_create_request = lambda ai_tool: {"url": "https://duomi.example.com/v1/images/generations", "method": "POST"}
    return driver


def _http_error_with_body(body):
    import requests

    err = requests.exceptions.HTTPError("400 Client Error: Bad Request for url: https://duomi.example.com")
    err.response_body = body
    return err


def test_submit_task_http_error_surfaces_moderation_friendly_message():
    """HTTP 4xx 响应体命中内容审核特征时返回中文友好文案，不再被"服务异常"掩盖。"""
    driver = _make_driver()
    driver._request = lambda **kwargs: (_ for _ in ()).throw(_http_error_with_body({
        "error": {"message": "sensitive_words detected in prompt", "code": "moderation_blocked"}
    }))

    ai_tool = SimpleNamespace(id=1, prompt="test", image_path="", ratio="1:1", image_size="1k")
    result = driver.submit_task(ai_tool)

    assert result["success"] is False
    assert result["error_type"] == "USER"
    assert result["error"].startswith("内容审核未通过")


def test_submit_task_http_error_without_body_keeps_generic_system_error():
    """异常未携带响应体时保持原有 SYSTEM 兜底行为。"""
    import requests

    driver = _make_driver()
    driver._request = lambda **kwargs: (_ for _ in ()).throw(
        requests.exceptions.HTTPError("500 Server Error")
    )

    ai_tool = SimpleNamespace(id=1, prompt="test", image_path="", ratio="1:1", image_size="1k")
    result = driver.submit_task(ai_tool)

    assert result["success"] is False
    assert result["error_type"] == "SYSTEM"
    assert result["error"] == "服务异常，请联系技术支持"


def test_check_status_error_state_surfaces_upstream_message():
    """上游 state=error 时透传 message，不再只返回写死的"图片生成失败"。"""
    driver = _make_driver()
    driver._request = lambda **kwargs: {
        "id": "p-1", "state": "error", "progress": 0,
        "message": "抱歉，任务处理遇到了一点小问题，请稍后重试",
    }

    result = driver.check_status("p-1")

    assert result["status"] == "FAILED"
    assert "抱歉，任务处理遇到了一点小问题" in result["error"]


def test_check_status_error_state_without_message_keeps_default():
    """上游 state=error 且无 message 时保持原默认文案。"""
    driver = _make_driver()
    driver._request = lambda **kwargs: {"id": "p-1", "state": "error", "progress": 0}

    result = driver.check_status("p-1")

    assert result["status"] == "FAILED"
    assert result["error"] == "图片生成失败"
