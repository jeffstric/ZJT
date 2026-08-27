"""MiniMax H3 图生视频「加速版」驱动：nodeInfoList 构造（尾帧节点 146）+ 状态查询。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from task.visual_drivers.minimax_h3_turbo_runninghub_v1_driver import (
    MinimaxH3TurboRunninghubV1Driver,
)
from utils.file_storage.base import UploadResult

TURBO_WEBAPP_ID = "2092199541612306434"


class FakeRunningHubStorage:
    def __init__(self):
        self.calls = []

    async def upload_file(self, key, file_path, content_type=None):
        self.calls.append(file_path)
        return UploadResult(
            success=True,
            key=f"openapi/{file_path}",
            url=f"https://rh.example/{file_path}",
        )


def make_driver():
    driver = MinimaxH3TurboRunninghubV1Driver.__new__(MinimaxH3TurboRunninghubV1Driver)
    driver._storage = FakeRunningHubStorage()
    driver._is_local = False
    driver._host = "https://www.runninghub.cn"
    driver._webapp_id = TURBO_WEBAPP_ID
    driver._api_key = "test-key"
    driver.logger = MagicMock()
    return driver


def make_ai_tool(**overrides):
    base = {
        "id": 1,
        "type": 34,
        "image_path": "img1.png",
        "reference_images": None,
        "audio_path": None,
        "video_path": None,
        "prompt": "战术小队突入房间",
        "duration": 8,
        "ratio": "16:9",
        "extra_config": None,
        "message": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def node_map(request):
    result = {}
    for n in request["json"]["nodeInfoList"]:
        result[(n["nodeId"], n["fieldName"])] = n["fieldValue"]
    return result


def test_build_create_request_node_mapping_with_last_frame():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        image_path="img1.png,img2.png",
    )))

    assert request["url"] == f"https://www.runninghub.cn/openapi/v2/run/ai-app/{TURBO_WEBAPP_ID}"
    assert request["method"] == "POST"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["json"]["instanceType"] == "default"
    assert request["json"]["usePersonalQueue"] == "false"

    nodes = node_map(request)
    # 提示词 / 首帧 / 尾帧（加速版尾帧节点为 146，区别于标准版 145）
    assert nodes[("143", "text")] == "战术小队突入房间"
    assert nodes[("114", "image")] == "https://rh.example/img1.png"
    assert nodes[("146", "image")] == "https://rh.example/img2.png"
    # 分辨率 / 比例 / 时长
    assert nodes[("115", "megapixels")] == "0.9"
    assert nodes[("115", "aspect_ratio")] == "16:9 (Widescreen)"
    assert nodes[("136", "value")] == "8"


def test_build_create_request_no_last_frame_keeps_node146_empty():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(image_path="img1.png")))

    nodes = node_map(request)
    assert nodes[("114", "image")] == "https://rh.example/img1.png"
    # 无尾帧时节点 146 始终传且留空（避免 RunningHub 用节点默认值）
    assert nodes[("146", "image")] == ""
    # 只上传了首帧
    assert driver._storage.calls == ["img1.png"]


def test_ratio_and_megapixels_mapping():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        ratio="9:16",
        extra_config='{"video_resolution": "480P"}',
    )))

    nodes = node_map(request)
    assert nodes[("115", "aspect_ratio")] == "9:16 (Portrait Widescreen)"
    assert nodes[("115", "megapixels")] == "0.4"

    # 未开放的比例回落到默认 9:16
    request = asyncio.run(driver.build_create_request(make_ai_tool(ratio="2:3")))
    assert node_map(request)[("115", "aspect_ratio")] == "9:16 (Portrait Widescreen)"


def test_build_create_request_prefers_optimized_prompt():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        extra_config=(
            '{"image_mode": "first_last_frame", '
            '"original_prompt": "战术小队突入房间", '
            '"h3_prompt_optimize": {"variant": "FL2VA", "optimized_prompt": "integrated_multimodal_description: ..."}}'
        ),
    )))

    nodes = node_map(request)
    assert nodes[("143", "text")] == "integrated_multimodal_description: ..."


def test_build_create_request_requires_first_frame():
    driver = make_driver()
    try:
        asyncio.run(driver.build_create_request(make_ai_tool(image_path=None)))
    except ValueError:
        return
    raise AssertionError("无首帧图片时应抛 ValueError")


def _run_check_status(driver, status_resp, outputs_resp=None):
    driver._request = MagicMock(side_effect=[status_resp, outputs_resp] if outputs_resp else [status_resp])
    return driver.check_status("task-123")


def test_check_status_success():
    driver = make_driver()
    result = _run_check_status(
        driver,
        {"code": 0, "data": "SUCCESS"},
        {"code": 0, "data": [{"fileUrl": "https://rh.example/out.mp4"}]},
    )
    assert result["status"] == "SUCCESS"
    assert result["result_url"] == "https://rh.example/out.mp4"


def test_check_status_failed():
    driver = make_driver()
    result = _run_check_status(driver, {"code": 0, "data": "FAILED"})
    assert result["status"] == "FAILED"
    assert result["error_type"] == "USER"


def test_check_status_running():
    driver = make_driver()
    for data in ("PENDING", "RUNNING"):
        driver = make_driver()
        result = _run_check_status(driver, {"code": 0, "data": data})
        assert result["status"] == "RUNNING"


def test_check_status_query_error():
    driver = make_driver()
    result = _run_check_status(driver, {"code": 1, "msg": "参数错误"})
    assert result["status"] == "FAILED"
    assert result["error"] == "参数错误"


def test_check_status_invalid_response_format():
    driver = make_driver()
    driver._send_alert = MagicMock()
    result = _run_check_status(driver, {"unexpected": True})
    assert result["status"] == "FAILED"
    assert result["error_type"] == "SYSTEM"
    driver._send_alert.assert_called()


def test_validate_submit_response():
    driver = make_driver()
    # 正常响应
    assert driver._validate_submit_response({"taskId": "123", "status": "RUNNING"}) == (True, None)
    # 缺 taskId
    valid, err = driver._validate_submit_response({"status": "RUNNING"})
    assert not valid and "taskId" in err
    # 缺 status
    valid, err = driver._validate_submit_response({"taskId": "123"})
    assert not valid and "status" in err
    # 非字典
    valid, _ = driver._validate_submit_response([1, 2])
    assert not valid
