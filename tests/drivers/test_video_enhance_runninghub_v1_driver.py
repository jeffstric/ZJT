from unittest.mock import MagicMock

from utils.content_moderation_error import FRIENDLY_PREFIX
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


# 2026-11-16/17 生产实测样本（任务 13579/13908）：RunningHub v2 /query 返回的
# 审核拒绝 failedReason 形状
AUDIT_QUERY_RESPONSE = {
    "taskId": "rh-1",
    "status": "FAILED",
    "errorCode": "805",
    "errorMessage": "工作流运行失败",
    "failedReason": {
        "current_outputs": "{}",
        "exception_type": "audit.RHAuditException",
        "node_name": "VHS_VideoCombine",
        "exception_message": "Porn",
        "traceback": ["RunningHub平台禁止以下内容:", " * 色情"],
    },
}


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

    # v1 status FAILED 后补查 v2 /query；该响应无 failedReason 细节 → 回落通用文案
    driver._request = MagicMock(side_effect=[
        {"code": 0, "data": "FAILED"},
        {"taskId": "rh-1", "status": "FAILED", "errorMessage": "工作流运行失败"},
    ])
    failed = driver.check_status("rh-1")
    assert failed["status"] == "FAILED"
    assert failed["error"] == "任务失败"
    assert failed["error_type"] == "USER"


def test_check_status_failed_surfaces_audit_reason():
    """审核拒绝：透出 FRIENDLY_PREFIX 审核文案（get-status 据此标 is_content_violation）。"""
    driver = make_driver()
    driver._request = MagicMock(side_effect=[
        {"code": 0, "data": "FAILED"},
        AUDIT_QUERY_RESPONSE,
    ])
    result = driver.check_status("rh-1")
    assert result["status"] == "FAILED"
    assert result["error"].startswith(FRIENDLY_PREFIX)
    assert "更换视频" in result["error"]
    assert result["error_type"] == "USER"
    # 原始细节保留在 error_detail（调度日志/排查用），不进用户文案
    assert "audit.RHAuditException" in result["error_detail"]
    assert "Porn" not in result["error"]


def test_check_status_failed_surfaces_oom_reason():
    """显存溢出：给用户可行动的提示，归类 SYSTEM。"""
    driver = make_driver()
    driver._request = MagicMock(side_effect=[
        {"code": 0, "data": "FAILED"},
        {
            "taskId": "rh-1", "status": "FAILED", "errorCode": "805",
            "errorMessage": "工作流运行失败",
            "failedReason": {
                "exception_type": "torch.OutOfMemoryError",
                "node_name": "SeedVR2",
                "exception_message": "CUDA out of memory",
            },
        },
    ])
    result = driver.check_status("rh-1")
    assert result["status"] == "FAILED"
    assert "显存不足" in result["error"]
    assert result["error_type"] == "SYSTEM"


def test_check_status_failed_surfaces_generic_reason():
    """非审核/非显存的上游异常：透传异常摘要（截断），不再是笼统「任务失败」。"""
    driver = make_driver()
    driver._request = MagicMock(side_effect=[
        {"code": 0, "data": "FAILED"},
        {
            "taskId": "rh-1", "status": "FAILED", "errorCode": "805",
            "errorMessage": "工作流运行失败",
            "failedReason": {
                "exception_type": "RuntimeError",
                "node_name": "VHS_LoadVideo",
                "exception_message": "invalid video file",
            },
        },
    ])
    result = driver.check_status("rh-1")
    assert result["status"] == "FAILED"
    assert result["error"] == "视频处理失败：VHS_LoadVideo: invalid video file"
    assert "invalid video file" in result["error_detail"]


def test_check_status_failed_v2_query_network_error_falls_back():
    """v2 补查网络抖动：不影响 FAILED 终态，回落通用文案。"""
    driver = make_driver()
    driver._request = MagicMock(side_effect=[
        {"code": 0, "data": "FAILED"},
        ConnectionError("v2 query timeout"),
    ])
    result = driver.check_status("rh-1")
    assert result["status"] == "FAILED"
    assert result["error"] == "任务失败"
    assert result["error_detail"] is None
    driver.logger.warning.assert_called()


def test_check_status_success_does_not_query_v2():
    """SUCCESS 路径不触发 v2 补查（outputs 之外不多打一次上游请求）。"""
    driver = make_driver()
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs["url"])
        if kwargs["url"].endswith("/status"):
            return {"code": 0, "data": "SUCCESS"}
        return {"code": 0, "data": [{"fileUrl": "https://cdn.example/out.mp4"}]}

    driver._request = fake_request
    result = driver.check_status("rh-1")
    assert result["status"] == "SUCCESS"
    assert all(url.endswith("/status") or url.endswith("/outputs") for url in calls)


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
