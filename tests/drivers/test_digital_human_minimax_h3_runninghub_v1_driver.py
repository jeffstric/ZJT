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
