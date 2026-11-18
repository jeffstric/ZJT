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


# ==================== 多米业务错误识别（403 密钥不正确等） ====================
# 修复背景：多米网关返回 {code:403, msg:"请求密钥KEY不正确！"} 这类结构有效的
# 业务错误时，曾被 _validate_submit_response 误判为格式错误，触发
# INVALID_RESPONSE_FORMAT Sentry 报警 + 笼统的"服务异常"，掩盖真实原因。

def _fake_alert_recorder():
    calls = []
    def _rec(**kwargs):
        calls.append(kwargs)
    return _rec, calls


def test_extract_business_error_403_is_fatal_with_config_hint():
    driver = _make_driver()
    biz = driver._extract_business_error({
        "code": 403, "data": None, "exec_time": 0.1,
        "ip": "125.125.130.168", "msg": "请求密钥KEY不正确！"
    })
    assert biz is not None
    msg, fatal = biz
    assert "请求密钥KEY不正确" in msg
    assert "duomi.token" in msg
    assert fatal is True


def test_extract_business_error_non_auth_code_is_transient():
    driver = _make_driver()
    biz = driver._extract_business_error({"code": 429, "msg": "too many requests"})
    assert biz is not None
    msg, fatal = biz
    assert "429" in msg
    assert fatal is False


def test_extract_business_error_success_response_returns_none():
    driver = _make_driver()
    assert driver._extract_business_error({"id": "task_1", "state": "pending"}) is None
    assert driver._extract_business_error("not a dict") is None
    assert driver._extract_business_error({"exec_time": 0.1}) is None  # 无 code+msg 不算业务错误


def test_submit_task_business_error_403_returns_user_error_without_alert():
    """密钥失效：USER 错误 + 不重试 + 不触发 Sentry 报警（结构有效非格式异常）。"""
    driver = _make_driver()
    _rec, calls = _fake_alert_recorder()
    driver._send_alert = _rec
    driver._request = lambda **kwargs: {
        "code": 403, "data": None, "exec_time": 0.1,
        "ip": "1.2.3.4", "msg": "请求密钥KEY不正确！"
    }

    ai_tool = SimpleNamespace(id=2, prompt="test", image_path="", ratio="1:1", image_size="1k")
    result = driver.submit_task(ai_tool)

    assert result["success"] is False
    assert result["error_type"] == "USER"
    assert result.get("retry") is False
    assert "请求密钥KEY不正确" in result["error"]
    assert calls == []  # 关键：不再触发 INVALID_RESPONSE_FORMAT 报警


def test_check_status_business_error_403_fails_without_alert():
    """轮询遇密钥失效：判 FAILED（USER）不报警，任务由过期/退费链路收尾。"""
    driver = _make_driver()
    _rec, calls = _fake_alert_recorder()
    driver._send_alert = _rec
    driver._request = lambda **kwargs: {
        "code": 403, "data": None, "exec_time": 0.1,
        "ip": "1.2.3.4", "msg": "请求密钥KEY不正确！"
    }

    result = driver.check_status("task_123")

    assert result["status"] == "FAILED"
    assert result["error_type"] == "USER"
    assert "请求密钥KEY不正确" in result["error"]
    assert calls == []


def test_check_status_transient_business_error_keeps_running():
    """轮询遇非致命业务错误（如限流）：保持 RUNNING 继续轮询。"""
    driver = _make_driver()
    driver._request = lambda **kwargs: {"code": 429, "msg": "too many requests"}

    result = driver.check_status("task_123")

    assert result["status"] == "RUNNING"
