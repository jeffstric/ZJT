import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from task.visual_drivers.digital_human_minimax_h3_runninghub_v1_driver import (
    DigitalHumanMinimaxH3RunninghubV1Driver,
)
from utils.file_storage.base import UploadResult


class FakeRunningHubStorage:
    def __init__(self):
        self.calls = []

    async def upload_file(self, key, file_path, content_type=None):
        self.calls.append((key, file_path, content_type))
        if "audio" in file_path:
            return UploadResult(success=True, key="openapi/audio1.wav", url="https://rh.example/audio1.wav")
        return UploadResult(success=True, key="openapi/image1.png", url="https://rh.example/image1.png")


def make_driver():
    driver = DigitalHumanMinimaxH3RunninghubV1Driver.__new__(DigitalHumanMinimaxH3RunninghubV1Driver)
    driver._storage = FakeRunningHubStorage()
    driver._is_local = False
    driver._host = "https://www.runninghub.cn"
    driver._webapp_id = "2087200340012785665"
    driver._api_key = "test-key"
    driver.logger = MagicMock()
    return driver


def make_ai_tool(**overrides):
    base = {
        "audio_path": "/tmp/audio.wav",
        "message": None,
        "image_path": "/tmp/person.png",
        "prompt": "图片1中的角色在唱歌。",
        "duration": 10,
        "extra_config": '{"max_edge": 1280, "start_second": 0}',
        "id": 1,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def node_map(request):
    result = {}
    for n in request["json"]["nodeInfoList"]:
        result[(n["nodeId"], n["fieldName"])] = n["fieldValue"]
    return result


def test_build_create_request_node_mapping():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool()))

    assert request["url"] == "https://www.runninghub.cn/openapi/v2/run/ai-app/2087200340012785665"
    assert request["json"]["instanceType"] == "default"
    assert request["headers"]["Authorization"] == "Bearer test-key"

    nodes = node_map(request)
    assert nodes[("214", "value")] == "图片1中的角色在唱歌。"
    assert nodes[("215", "audio")] == "openapi/audio1.wav"
    assert nodes[("209", "image")] == "https://rh.example/image1.png"
    assert nodes[("212", "value")] == "10"
    assert nodes[("213", "value")] == "1280"
    assert nodes[("229", "value")] == "0"


def test_build_create_request_custom_params():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        duration=6,
        extra_config='{"max_edge": 1920, "start_second": 2}',
    )))
    nodes = node_map(request)
    assert nodes[("212", "value")] == "6"
    assert nodes[("213", "value")] == "1920"
    assert nodes[("229", "value")] == "2"


def test_build_create_request_invalid_duration_falls_back():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(duration=99)))
    nodes = node_map(request)
    assert nodes[("212", "value")] == "10"


def test_build_create_request_resolution_maps_to_max_edge():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        extra_config='{"resolution": "480P"}',
    )))
    nodes = node_map(request)
    assert nodes[("213", "value")] == "720"



# ==================== submit_task / check_status 状态机 ====================
# 背景（c5d637f85、13347a6fc）：421 上游拥堵须转为回队延迟重试（retry=True、
# 不消耗用户重试次数），断点续跑依赖该语义；此前只测 build_create_request。


def _stub_request(driver, responses):
    """按调用顺序出队响应；ConnectionError/TimeoutError 直接抛出。"""
    queue = list(responses)
    calls = []

    def _request(**params):
        calls.append(params)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    driver._request = _request
    return calls


def test_submit_congested_error_returns_retry():
    driver = make_driver()
    _stub_request(driver, [{"taskId": "t", "status": "ERROR", "errorCode": "421", "errorMessage": "api queue limit reached"}])
    result = asyncio.run(driver.submit_task(make_ai_tool()))
    assert result["success"] is False
    assert result["retry"] is True
    assert result.get("retry_reason") == "UPSTREAM_CONGESTED"


def test_submit_user_error_no_retry():
    driver = make_driver()
    _stub_request(driver, [{"taskId": "t", "status": "ERROR", "errorCode": "401", "errorMessage": "余额不足"}])
    result = asyncio.run(driver.submit_task(make_ai_tool()))
    assert result["success"] is False
    assert result["retry"] is False
    assert result["error_type"] == "USER"
    assert "余额不足" in result["error"]


def test_submit_network_error_retries():
    driver = make_driver()
    _stub_request(driver, [TimeoutError("timed out")])
    result = asyncio.run(driver.submit_task(make_ai_tool()))
    assert result["success"] is False
    assert result["retry"] is True


def test_submit_success_returns_project_id():
    driver = make_driver()
    _stub_request(driver, [{"taskId": "rh-task-1", "status": "OK"}])
    result = asyncio.run(driver.submit_task(make_ai_tool()))
    assert result == {"success": True, "project_id": "rh-task-1"}


def test_submit_missing_task_id_is_system_failure():
    driver = make_driver()
    _stub_request(driver, [{"status": "OK"}])
    result = asyncio.run(driver.submit_task(make_ai_tool()))
    assert result["success"] is False
    assert result["error_type"] == "SYSTEM"
    assert result["retry"] is False


def test_check_status_running():
    driver = make_driver()
    _stub_request(driver, [{"code": 0, "data": "RUNNING"}])
    result = driver.check_status("pid-1")
    assert result == {"status": "RUNNING", "message": "任务处理中..."}


def test_check_status_failed_user_error():
    driver = make_driver()
    _stub_request(driver, [{"code": 500, "msg": "任务不存在"}])
    result = driver.check_status("pid-1")
    assert result["status"] == "FAILED"
    assert result["error_type"] == "USER"


def test_check_status_network_error_keeps_running():
    """网络抖动不得把任务判死：保持 RUNNING 等下一轮。"""
    driver = make_driver()
    _stub_request(driver, [ConnectionError("reset")])
    result = driver.check_status("pid-1")
    assert result == {"status": "RUNNING", "message": "网络连接异常，稍后将重试"}


def test_check_status_success_picks_first_mp4():
    driver = make_driver()
    _stub_request(driver, [
        {"code": 0, "data": "SUCCESS"},
        {"code": 0, "data": [
            {"fileType": "png", "fileUrl": "https://rh/x.png"},
            {"fileType": "mp4", "fileUrl": "https://rh/a.mp4"},
            {"fileType": "mp4", "fileUrl": "https://rh/b.mp4"},
        ]},
    ])
    result = driver.check_status("pid-1")
    assert result["status"] == "SUCCESS"
    assert result["result_url"] == "https://rh/a.mp4"


def test_check_status_success_without_mp4_returns_null_url():
    driver = make_driver()
    _stub_request(driver, [
        {"code": 0, "data": "SUCCESS"},
        {"code": 0, "data": [{"fileType": "png", "fileUrl": "https://rh/x.png"}]},
    ])
    result = driver.check_status("pid-1")
    assert result["status"] == "SUCCESS"
    assert result["result_url"] is None


def test_check_status_invalid_response_format_is_system_failure():
    driver = make_driver()
    driver._send_alert = MagicMock()
    _stub_request(driver, ["not-a-dict"])
    result = driver.check_status("pid-1")
    assert result["status"] == "FAILED"
    assert result["error_type"] == "SYSTEM"
    driver._send_alert.assert_called_once()
