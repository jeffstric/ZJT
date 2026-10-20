import asyncio
import os
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


def test_extract_last_frame_uses_configured_ffmpeg(monkeypatch, tmp_path):
    """末帧提取必须走配置 bin.ffmpeg（Linux 部署无 bin/ffmpeg/ffmpeg 相对路径）。"""
    from task.visual_drivers import digital_human_minimax_h3_runninghub_v1_driver as drv_mod

    seen = {}

    def fake_run(argv, *args, **kwargs):
        seen["ffmpeg"] = argv[0]
        with open(argv[-1], "wb") as f:
            f.write(b"x" * 2048)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(drv_mod, "_get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(drv_mod.subprocess, "run", fake_run)

    driver = make_driver()
    out_jpg = str(tmp_path / "last.jpg")
    assert driver._extract_last_frame(str(tmp_path / "seg1.mp4"), out_jpg) == out_jpg
    assert seen["ffmpeg"] == "/usr/bin/ffmpeg"
    assert seen["ffmpeg"] != "bin/ffmpeg/ffmpeg"


def test_extract_last_frame_degrades_when_ffmpeg_unlaunchable(monkeypatch, tmp_path):
    """ffmpeg 启动失败时返回 None（下一段回退角色图），不得抛异常炸整条流水线。"""
    import errno
    from task.visual_drivers import digital_human_minimax_h3_runninghub_v1_driver as drv_mod

    def boom(argv, *args, **kwargs):
        raise FileNotFoundError(errno.ENOENT, "No such file or directory", argv[0])

    monkeypatch.setattr(drv_mod, "_get_ffmpeg_path", lambda: "bin/ffmpeg/ffmpeg")
    monkeypatch.setattr(drv_mod.subprocess, "run", boom)

    driver = make_driver()
    assert driver._extract_last_frame(str(tmp_path / "v.mp4"), str(tmp_path / "o.jpg")) is None


def test_concat_and_store_uses_configured_ffprobe(monkeypatch, tmp_path):
    """拼接前探测首段尺寸的 ffprobe 也必须走配置 bin.ffprobe。"""
    from task.visual_drivers import digital_human_minimax_h3_runninghub_v1_driver as drv_mod

    calls = []

    def fake_run(argv, *args, **kwargs):
        calls.append(argv[0])
        if "-show_entries" in argv:
            return SimpleNamespace(
                returncode=0,
                stdout='{"streams": [{"width": 720, "height": 1280}]}',
                stderr="")
        out_path = argv[-1]
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(b"x" * 2048)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(drv_mod, "_get_ffprobe_path", lambda: "/usr/bin/ffprobe")
    monkeypatch.setattr(drv_mod.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)

    driver = make_driver()
    result_url = driver._concat_and_store(999, [str(tmp_path / "seg1.mp4"), str(tmp_path / "seg2.mp4")])
    assert calls[0] == "/usr/bin/ffprobe"
    assert calls[1] != "bin/ffmpeg/ffmpeg"
    assert result_url.startswith("/upload/cache/")
