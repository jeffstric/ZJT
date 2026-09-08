"""MiniMax H3 文生视频驱动：nodeInfoList 构造（素材槽位全空 + 旁路开关 + 参数映射）。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from task.visual_drivers.minimax_h3_text_runninghub_v1_driver import (
    MinimaxH3TextRunninghubV1Driver,
    REFERENCE_IMAGE_NODE_IDS,
    REFERENCE_AUDIO_NODE_IDS,
    REFERENCE_VIDEO_NODE_IDS,
    REFERENCE_AUDIO_SWITCH_NODE_IDS,
    REFERENCE_VIDEO_SWITCH_NODE_IDS,
)


def make_driver():
    driver = MinimaxH3TextRunninghubV1Driver.__new__(MinimaxH3TextRunninghubV1Driver)
    driver._is_local = False
    driver._host = "https://www.runninghub.cn"
    driver._webapp_id = "2086470155902734337"
    driver._api_key = "test-key"
    driver.logger = MagicMock()
    return driver


def make_ai_tool(**overrides):
    base = {
        "id": 1,
        "type": 45,
        "image_path": None,
        "reference_images": None,
        "audio_path": None,
        "video_path": None,
        "prompt": "生成一个小猫的视频",
        "duration": 5,
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


def test_build_create_request_all_asset_slots_empty():
    """文生视频复用参考生工作流：所有素材槽位固定留空，音/视频开关全旁路。"""
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool()))

    assert request["url"] == "https://www.runninghub.cn/openapi/v2/run/ai-app/2086470155902734337"
    assert request["headers"]["Authorization"] == "Bearer test-key"

    nodes = node_map(request)
    for node_id in REFERENCE_IMAGE_NODE_IDS:
        assert nodes[(node_id, "image")] == ""
    for node_id in REFERENCE_AUDIO_NODE_IDS:
        assert nodes[(node_id, "audio")] == ""
    for node_id in REFERENCE_VIDEO_NODE_IDS:
        assert nodes[(node_id, "video")] == ""
    for node_id in REFERENCE_AUDIO_SWITCH_NODE_IDS + REFERENCE_VIDEO_SWITCH_NODE_IDS:
        assert nodes[(node_id, "select")] == "2"


def test_build_create_request_basic_params():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        duration=8,
        ratio="9:16",
        extra_config='{"video_resolution": "480P"}',
    )))

    nodes = node_map(request)
    assert nodes[("138", "value")] == "生成一个小猫的视频"
    assert nodes[("132", "value")] == "8"
    assert nodes[("115", "aspect_ratio")] == "9:16 (Portrait Widescreen)"
    assert nodes[("115", "megapixels")] == "0.4"


def test_build_create_request_ignores_uploaded_assets():
    """即使记录里残留素材路径（如模式误选），文生视频也不上传、不填槽位。"""
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        image_path="a.png",
        reference_images='["b.png"]',
        audio_path="c.wav",
        video_path="d.mp4",
    )))

    nodes = node_map(request)
    for node_id in REFERENCE_IMAGE_NODE_IDS:
        assert nodes[(node_id, "image")] == ""
    assert nodes[("155", "audio")] == ""
    assert nodes[("158", "video")] == ""
    for node_id in REFERENCE_AUDIO_SWITCH_NODE_IDS + REFERENCE_VIDEO_SWITCH_NODE_IDS:
        assert nodes[(node_id, "select")] == "2"


def test_build_create_request_prefers_optimized_prompt():
    """预留 T2VA 优化回读：extra_config.h3_prompt_optimize.optimized_prompt 优先于原文。"""
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        extra_config=(
            '{"original_prompt": "生成一个小猫的视频", '
            '"h3_prompt_optimize": {"variant": "T2VA", "optimized_prompt": "subject_definitions: ..."}}'
        ),
    )))

    nodes = node_map(request)
    assert nodes[("138", "value")] == "subject_definitions: ..."


def test_default_ratio_and_duration():
    """duration/ratio 缺省时回退 5 秒 / 9:16，不得提交空值。"""
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(duration=None, ratio=None)))

    nodes = node_map(request)
    assert nodes[("132", "value")] == "5"
    assert nodes[("115", "aspect_ratio")] == "9:16 (Portrait Widescreen)"
