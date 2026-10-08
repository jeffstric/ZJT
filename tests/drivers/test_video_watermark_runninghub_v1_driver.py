import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from config.constant import DRIVER_IMPLEMENTATION_MAPPING, RUNNINGHUB_TASK_TYPES
from config.unified_config import (
    MINIMAX_H3_720P_COMPUTING_POWER,
    DriverImplementation,
    DriverKey,
    TaskTypeId,
    UnifiedConfigRegistry,
    get_implementation_id,
)
from task.visual_drivers.driver_factory import VideoDriverFactory, register_all_drivers
from task.visual_drivers.video_watermark_runninghub_v1_driver import (
    DEFAULT_FPS,
    DEFAULT_PROMPT,
    WEBAPP_ID,
    VideoWatermarkRunninghubV1Driver,
)
from utils.file_storage.base import UploadResult


class FakeRunningHubStorage:
    def __init__(self, key="openapi/clip.mp4", url="https://rh.example/clip.mp4", success=True):
        self.calls = []
        self.key = key
        self.url = url
        self.success = success

    async def upload_file(self, key, file_path, content_type=None):
        self.calls.append((key, file_path, content_type))
        if not self.success:
            return UploadResult(success=False, error="upload failed")
        return UploadResult(success=True, key=self.key, url=self.url)


def make_driver(storage=None):
    driver = VideoWatermarkRunninghubV1Driver.__new__(VideoWatermarkRunninghubV1Driver)
    driver._storage = storage or FakeRunningHubStorage()
    driver._host = "https://www.runninghub.cn"
    driver._webapp_id = WEBAPP_ID
    driver._api_key = "test-key"
    driver.logger = MagicMock()
    driver._send_alert = MagicMock()
    return driver


def make_ai_tool(**overrides):
    base = {
        "id": 7,
        "video_path": "/tmp/clip.mp4",
        "prompt": "",
        "duration": 5,
        "extra_config": '{"fps": 24}',
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def node_map(request):
    return {
        (node["nodeId"], node["fieldName"]): node["fieldValue"]
        for node in request["json"]["nodeInfoList"]
    }


def test_power_table_matches_h3_720p_and_task_is_hidden():
    impl = UnifiedConfigRegistry.get_implementation(DriverImplementation.VIDEO_WATERMARK_RUNNINGHUB_V1)
    h3 = UnifiedConfigRegistry.get_implementation(DriverImplementation.MINIMAX_H3_RUNNINGHUB_V1)
    task = UnifiedConfigRegistry.get_by_id(TaskTypeId.VIDEO_WATERMARK_REMOVE)

    assert MINIMAX_H3_720P_COMPUTING_POWER == {4: 5, 5: 6, 6: 8, 7: 9, 8: 10, 9: 11, 10: 13}
    assert impl.default_computing_power is MINIMAX_H3_720P_COMPUTING_POWER
    assert h3.default_computing_power is MINIMAX_H3_720P_COMPUTING_POWER
    assert task.hidden is True
    assert task.computing_power == 0
    assert task.supported_durations == [4, 5, 6, 7, 8, 9, 10]
    assert task.default_duration == 5
    assert task.provider == "runninghub"
    assert get_implementation_id("video_watermark_runninghub_v1") == 99
    assert TaskTypeId.VIDEO_WATERMARK_REMOVE in RUNNINGHUB_TASK_TYPES
    assert (
        DRIVER_IMPLEMENTATION_MAPPING[DriverKey.VIDEO_WATERMARK_REMOVE]
        == DriverImplementation.VIDEO_WATERMARK_RUNNINGHUB_V1
    )


def test_driver_is_registered():
    register_all_drivers()
    registered = VideoDriverFactory._registered_drivers[DriverImplementation.VIDEO_WATERMARK_RUNNINGHUB_V1]
    assert registered is VideoWatermarkRunninghubV1Driver


def test_build_create_request_uses_filename_and_defaults():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(prompt="  ", extra_config=None, duration=None)))

    assert request["url"].endswith(f"/openapi/v2/run/ai-app/{WEBAPP_ID}")
    assert request["json"]["instanceType"] == "default"
    assert request["json"]["usePersonalQueue"] == "false"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    nodes = node_map(request)
    assert nodes[("5099", "video")] == "openapi/clip.mp4"
    assert nodes[("5134", "text")] == DEFAULT_PROMPT
    assert nodes[("5145", "value")] == "5"
    assert nodes[("5146", "value")] == str(DEFAULT_FPS)
    assert len(DEFAULT_PROMPT) <= 2000


def test_build_create_request_custom_params_and_first_video_only():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        video_path="/tmp/a.mp4,/tmp/b.mp4",
        prompt="只去掉右下角台标",
        duration=10,
        extra_config='{"fps": 30}',
    )))
    nodes = node_map(request)
    assert driver._storage.calls[0][1] == "/tmp/a.mp4"
    assert nodes[("5134", "text")] == "只去掉右下角台标"
    assert nodes[("5145", "value")] == "10"
    assert nodes[("5146", "value")] == "30"


def test_build_create_request_falls_back_to_url_and_repairs_fps():
    driver = make_driver(FakeRunningHubStorage(key="", url="https://rh.example/only-url.mp4"))
    request = asyncio.run(driver.build_create_request(make_ai_tool(extra_config='{"fps": "fast"}')))
    nodes = node_map(request)
    assert nodes[("5099", "video")] == "https://rh.example/only-url.mp4"
    assert nodes[("5146", "value")] == "24"


def test_invalid_duration_and_missing_video_are_user_errors():
    driver = make_driver()
    duration_result = asyncio.run(driver.submit_task(make_ai_tool(duration=3)))
    missing_result = asyncio.run(driver.submit_task(make_ai_tool(video_path="")))
    upload_driver = make_driver(FakeRunningHubStorage(success=False))
    upload_result = asyncio.run(upload_driver.submit_task(make_ai_tool()))

    assert duration_result["success"] is False
    assert duration_result["error_type"] == "USER"
    assert "4" in duration_result["error"]
    assert missing_result["error_type"] == "USER"
    assert upload_result["error_type"] == "USER"
    assert "上传" in upload_result["error"]
    driver._send_alert.assert_not_called()
    upload_driver._send_alert.assert_not_called()


def test_submit_success_accepts_wrapped_task_id(monkeypatch):
    driver = make_driver()
    monkeypatch.setattr(
        driver,
        "_request",
        lambda **_kwargs: {"code": 0, "data": {"taskId": "rh-1", "status": "QUEUED"}},
    )
    result = asyncio.run(driver.submit_task(make_ai_tool()))
    assert result == {"success": True, "project_id": "rh-1"}
    driver._send_alert.assert_not_called()


def test_submit_congestion_retries_without_alert(monkeypatch):
    driver = make_driver()
    monkeypatch.setattr(
        driver,
        "_request",
        lambda **_kwargs: {"taskId": "", "status": "FAILED", "errorCode": "421", "errorMessage": "queue"},
    )
    result = asyncio.run(driver.submit_task(make_ai_tool()))
    assert result["retry"] is True
    assert result["retry_reason"] == "UPSTREAM_CONGESTED"
    driver._send_alert.assert_not_called()


def test_submit_bad_shape_is_system_error(monkeypatch):
    driver = make_driver()
    monkeypatch.setattr(driver, "_request", lambda **_kwargs: {"unexpected": True})
    result = asyncio.run(driver.submit_task(make_ai_tool()))
    assert result["success"] is False
    assert result["error_type"] == "SYSTEM"
    driver._send_alert.assert_called_once()


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

    driver._request = lambda **_kwargs: {"msg": "missing"}
    broken = driver.check_status("rh-1")
    assert broken["error_type"] == "SYSTEM"
    driver._send_alert.assert_called()
