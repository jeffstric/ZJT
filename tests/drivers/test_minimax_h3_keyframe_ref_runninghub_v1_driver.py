"""MiniMax H3 首帧参考混合驱动：按原文槽位填 Picture 1/2/3，音频最多两路。"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from task.visual_drivers.minimax_h3_keyframe_ref_runninghub_v1_driver import (
    MinimaxH3KeyframeRefRunninghubV1Driver,
)
from utils.file_storage.base import UploadResult


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
    driver = MinimaxH3KeyframeRefRunninghubV1Driver.__new__(MinimaxH3KeyframeRefRunninghubV1Driver)
    driver._storage = FakeRunningHubStorage()
    driver._is_local = False
    driver._host = "https://www.runninghub.cn"
    driver._webapp_id = "2108549232725680129"
    driver._api_key = "test-key"
    driver.logger = MagicMock()
    return driver


def make_ai_tool(**overrides):
    base = {
        "id": 1,
        "type": 50,
        "image_path": None,
        "reference_images": '["first.png", "ref.png", "last.png"]',
        "audio_path": None,
        "video_path": None,
        "prompt": "图1是首帧，图2是林月，图3是尾帧。",
        "duration": 8,
        "ratio": "9:16",
        "extra_config": '{"image_mode": "multi_reference"}',
        "message": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def node_map(request):
    result = {}
    for node in request["json"]["nodeInfoList"]:
        result[(node["nodeId"], node["fieldName"])] = node
    return result


def test_both_markers_fill_start_reference_end():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool()))

    assert request["url"] == "https://www.runninghub.cn/openapi/v2/run/ai-app/2108549232725680129"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["json"]["instanceType"] == "default"
    assert request["json"]["usePersonalQueue"] == "false"

    nodes = node_map(request)
    assert nodes[("137", "image")]["fieldValue"] == "https://rh.example/first.png"
    assert nodes[("156", "image")]["fieldValue"] == "https://rh.example/ref.png"
    assert nodes[("187", "image")]["fieldValue"] == "https://rh.example/last.png"
    assert nodes[("157", "audio")]["fieldValue"] == "None"
    assert nodes[("188", "audio")]["fieldValue"] == "None"
    assert nodes[("138", "value")]["fieldValue"] == "图1是首帧，图2是林月，图3是尾帧。"
    assert nodes[("132", "value")]["fieldValue"] == "8"
    assert nodes[("115", "aspect_ratio")]["fieldValue"] == "9:16 (Portrait Widescreen)"
    assert "fieldData" in nodes[("115", "aspect_ratio")]
    assert nodes[("115", "megapixels")]["fieldValue"] == "0.9"
    node_ids = {node["nodeId"] for node in request["json"]["nodeInfoList"]}
    assert node_ids.isdisjoint({"165", "166", "167", "168"})
    assert all(node["fieldName"] != "video" for node in request["json"]["nodeInfoList"])
    assert all(node["fieldName"] != "select" for node in request["json"]["nodeInfoList"])


def test_only_last_reads_original_prompt_not_optimized_text():
    driver = make_driver()
    extra = {
        "image_mode": "multi_reference",
        "h3_prompt_optimize": {
            "variant": "KFRef",
            "original_prompt": "停在结尾\n\n图2是尾帧。",
            "optimized_prompt": "subject_definitions: rewritten without frame marks",
        },
    }
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        reference_images='["ref.png", "last.png"]',
        prompt="subject_definitions: rewritten without frame marks",
        extra_config=json.dumps(extra, ensure_ascii=False),
    )))
    nodes = node_map(request)
    assert nodes[("137", "image")]["fieldValue"] == "https://rh.example/ref.png"
    assert nodes[("156", "image")]["fieldValue"] == ""
    assert nodes[("187", "image")]["fieldValue"] == "https://rh.example/last.png"
    assert nodes[("138", "value")]["fieldValue"] == "subject_definitions: rewritten without frame marks"


def test_only_first_puts_second_reference_on_picture_3():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        reference_images='["first.png", "ref1.png", "ref2.png"]',
        prompt="图1是首帧，图2是甲，图3是乙。",
    )))
    nodes = node_map(request)
    assert nodes[("137", "image")]["fieldValue"] == "https://rh.example/first.png"
    assert nodes[("156", "image")]["fieldValue"] == "https://rh.example/ref1.png"
    assert nodes[("187", "image")]["fieldValue"] == "https://rh.example/ref2.png"


def test_two_audios_fill_both_nodes_and_extra_audio_and_video_are_dropped():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        audio_path="voice1.wav,voice2.wav",
        video_path="clip.mp4",
        # 有引号台词的镜头维持上传音色 + lip-sync pacing 现状
        prompt="图1是首帧，图2是林月，图3是尾帧。林月说「今天到此为止」。",
    )))
    nodes = node_map(request)
    assert nodes[("157", "audio")]["fieldValue"] == "openapi/voice1.wav"
    assert nodes[("157", "audio")]["description"] == "<Audio 1>"
    assert nodes[("188", "audio")]["fieldValue"] == "openapi/voice2.wav"
    assert nodes[("188", "audio")]["description"] == "<Audio 2>"
    assert "clip.mp4" not in driver._storage.calls
    driver.logger.warning.assert_called()

    extra = make_driver()
    extra_request = asyncio.run(extra.build_create_request(make_ai_tool(
        audio_path="a.wav,b.wav,c.wav",
        prompt="图1是首帧，图2是林月，图3是尾帧。林月说「今天到此为止」。",
    )))
    extra_nodes = node_map(extra_request)
    assert extra_nodes[("157", "audio")]["fieldValue"] == "openapi/a.wav"
    assert extra_nodes[("188", "audio")]["fieldValue"] == "openapi/b.wav"
    assert "c.wav" not in extra._storage.calls
    extra.logger.warning.assert_called()


def test_no_dialogue_skips_audio_upload_and_fills_none():
    """无对白镜头不上传音色：两个音频槽都填 None，音频文件根本不传 RunningHub。"""
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        audio_path="voice1.wav,voice2.wav",
        prompt="图1是首帧，图2是林月，图3是尾帧。无对白，只有扫帚和脚步声。",
    )))
    nodes = node_map(request)
    assert nodes[("157", "audio")]["fieldValue"] == "None"
    assert nodes[("188", "audio")]["fieldValue"] == "None"
    assert "voice1.wav" not in driver._storage.calls
    assert "voice2.wav" not in driver._storage.calls
    driver.logger.info.assert_called()


def test_no_dialogue_judgment_reads_original_prompt_not_optimized_text():
    """台词判断以优化前原文为准：旧优化结果里残留 <Audio 1> 也不影响跳过上传。"""
    driver = make_driver()
    extra = {
        "image_mode": "multi_reference",
        "h3_prompt_optimize": {
            "variant": "KFRef",
            "original_prompt": "图1是首帧，图2是林月，图3是尾帧。无对白。",
            "optimized_prompt": "[keyframe completion + audio reference] <Audio 1> legacy",
        },
    }
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        audio_path="voice1.wav",
        prompt="[keyframe completion + audio reference] <Audio 1> legacy",
        extra_config=json.dumps(extra, ensure_ascii=False),
    )))
    nodes = node_map(request)
    assert nodes[("157", "audio")]["fieldValue"] == "None"
    assert nodes[("188", "audio")]["fieldValue"] == "None"
    assert "voice1.wav" not in driver._storage.calls


def test_requires_at_least_one_picture():
    driver = make_driver()
    try:
        asyncio.run(driver.build_create_request(make_ai_tool(reference_images=None, prompt="没有图")))
    except ValueError:
        return
    raise AssertionError("没有图片时应抛 ValueError")
