from unittest.mock import MagicMock

from task.visual_drivers.video_enhance_runninghub_v1_driver import (
    VideoEnhanceRunninghubV1Driver,
)


def make_driver():
    driver = VideoEnhanceRunninghubV1Driver.__new__(VideoEnhanceRunninghubV1Driver)
    driver._host = "https://www.runninghub.cn"
    driver._api_key = "test-key"
    driver.logger = MagicMock()
    driver._send_alert = MagicMock()
    return driver


def test_check_status_prefers_video_file():
    driver = make_driver()
    calls = {"n": 0}

    def fake_request(**kwargs):
        calls["n"] += 1
        if kwargs["url"].endswith("/status"):
            return {"code": 0, "data": "SUCCESS"}
        return {
            "code": 0,
            "data": [
                {"fileUrl": "https://cdn.example/frame.png"},
                {"fileUrl": "https://cdn.example/out.mp4?token=1"},
            ],
        }

    driver._request = fake_request
    result = driver.check_status("rh-1")
    assert result["status"] == "SUCCESS"
    assert result["result_url"] == "https://cdn.example/out.mp4?token=1"
    assert calls["n"] == 2


def test_check_status_running_and_failed():
    driver = make_driver()
    driver._request = lambda **_kwargs: {"code": 0, "data": {"status": "QUEUED"}}
    assert driver.check_status("rh-1")["status"] == "RUNNING"

    driver._request = lambda **_kwargs: {"code": 0, "data": "FAILED"}
    failed = driver.check_status("rh-1")
    assert failed["status"] == "FAILED"
    assert failed["error_type"] == "USER"


def test_outputs_network_error_returns_running():
    """上游已 SUCCESS 后 outputs 单次网络抖动：RUNNING 待重试，不得终态失败退费。"""
    driver = make_driver()
    driver._request = MagicMock(side_effect=[
        {"code": 0, "data": "SUCCESS"},
        ConnectionError("outputs timeout"),
    ])
    result = driver.check_status("task_12345")
    assert result["status"] == "RUNNING"
    assert result["preserve_retry_count"] is True


def test_outputs_api_error_returns_running():
    """上游已 SUCCESS 后 outputs 返回限流/5xx：RUNNING 且保留生成重试次数。"""
    driver = make_driver()
    driver._request = MagicMock(side_effect=[
        {"code": 0, "data": "SUCCESS"},
        {"code": 429, "msg": "rate limited"},
    ])
    result = driver.check_status("task_12345")
    assert result["status"] == "RUNNING"
    assert result["preserve_retry_count"] is True


def test_outputs_congested_error_returns_running():
    driver = make_driver()
    driver._request = MagicMock(side_effect=[
        {"code": 0, "data": "SUCCESS"},
        {"code": 421, "msg": "queue maxed"},
    ])
    result = driver.check_status("task_12345")
    assert result["status"] == "RUNNING"
    assert result["preserve_retry_count"] is True


def test_outputs_permanent_api_error_returns_failed():
    """永久业务错误不得伪装成网络抖动无限轮询。"""
    driver = make_driver()
    driver._request = MagicMock(side_effect=[
        {"code": 0, "data": "SUCCESS"},
        {"code": 404, "msg": "task not found"},
    ])
    result = driver.check_status("task_12345")
    assert result["status"] == "FAILED"
    assert result["error_type"] == "SYSTEM"
    assert "preserve_retry_count" not in result


def test_outputs_success_without_video_url_is_failed():
    """outputs 正常返回但没有视频地址：视频任务保持 FAILED 终态。"""
    driver = make_driver()
    driver._request = MagicMock(side_effect=[
        {"code": 0, "data": "SUCCESS"},
        {"code": 0, "data": []},
    ])
    result = driver.check_status("task_12345")
    assert result["status"] == "FAILED"
    assert result["error_type"] == "SYSTEM"
    driver._send_alert.assert_called()
