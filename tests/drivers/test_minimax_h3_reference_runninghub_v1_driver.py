"""MiniMax H3 参考生视频驱动：nodeInfoList 构造（图/视频/音频参考 + 优化提示词优先级）。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from task.visual_drivers.minimax_h3_reference_runninghub_v1_driver import (
    MinimaxH3ReferenceRunninghubV1Driver,
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
    driver = MinimaxH3ReferenceRunninghubV1Driver.__new__(MinimaxH3ReferenceRunninghubV1Driver)
    driver._storage = FakeRunningHubStorage()
    driver._is_local = False
    driver._host = "https://www.runninghub.cn"
    driver._webapp_id = "2086470155902734337"
    driver._api_key = "test-key"
    driver.logger = MagicMock()
    return driver


def make_ai_tool(**overrides):
    base = {
        "id": 1,
        "type": 37,
        "image_path": None,
        "reference_images": '["img1.png", "img2.png"]',
        "audio_path": None,
        "video_path": None,
        "prompt": "两个人在跳舞",
        "duration": 8,
        "ratio": "9:16",
        "extra_config": '{"image_mode": "multi_reference"}',
        "message": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def node_map(request):
    result = {}
    for n in request["json"]["nodeInfoList"]:
        result[(n["nodeId"], n["fieldName"])] = n["fieldValue"]
    return result


def test_build_create_request_image_node_mapping():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool()))

    assert request["url"] == "https://www.runninghub.cn/openapi/v2/run/ai-app/2086470155902734337"
    assert request["headers"]["Authorization"] == "Bearer test-key"

    nodes = node_map(request)
    # 图片节点取 download_url，未使用的图节点留空
    assert nodes[("137", "image")] == "https://rh.example/img1.png"
    assert nodes[("139", "image")] == "https://rh.example/img2.png"
    for node_id in ("142", "147", "149", "150", "151", "152", "153"):
        assert nodes[(node_id, "image")] == ""
    # 未传音频/视频时节点留空（覆盖应用默认值），旁路开关全为 2（加载器不执行）
    assert nodes[("155", "audio")] == ""
    assert nodes[("163", "audio")] == ""
    assert nodes[("158", "video")] == ""
    assert nodes[("164", "video")] == ""
    assert nodes[("167", "select")] == "2"
    assert nodes[("168", "select")] == "2"
    assert nodes[("165", "select")] == "2"
    assert nodes[("166", "select")] == "2"
    # 基础参数
    assert nodes[("138", "value")] == "两个人在跳舞"
    assert nodes[("132", "value")] == "8"
    assert nodes[("115", "aspect_ratio")] == "9:16 (Portrait Widescreen)"
    assert nodes[("115", "megapixels")] == "0.9"


def test_build_create_request_audio_video_nodes_use_filename():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        # 音色参考必须绑台词：有对白镜头（引号台词）音频才会上传
        prompt='李明环视众人后说："今天天气真好。"',
        audio_path="voice1.wav",
        video_path="clip1.mp4,clip2.mp4",
    )))

    nodes = node_map(request)
    # 音频/视频节点取 fileName（与数字人 H3 驱动一致）
    assert nodes[("155", "audio")] == "openapi/voice1.wav"
    assert nodes[("163", "audio")] == ""
    assert nodes[("158", "video")] == "openapi/clip1.mp4"
    assert nodes[("164", "video")] == "openapi/clip2.mp4"
    # 旁路开关：有文件的槽位启用（1），无文件的旁路（2）
    assert nodes[("167", "select")] == "1"
    assert nodes[("168", "select")] == "2"
    assert nodes[("165", "select")] == "1"
    assert nodes[("166", "select") ] == "1"


def test_build_create_request_truncates_extra_audio_video():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        prompt='李明说："今天天气真好。"',
        audio_path="a1.wav,a2.wav,a3.wav",
        video_path="v1.mp4,v2.mp4,v3.mp4",
    )))

    nodes = node_map(request)
    assert nodes[("155", "audio")] == "openapi/a1.wav"
    assert nodes[("163", "audio")] == "openapi/a2.wav"
    assert nodes[("158", "video")] == "openapi/v1.mp4"
    assert nodes[("164", "video")] == "openapi/v2.mp4"
    # 两个槽位都有文件，开关全启用
    assert nodes[("167", "select")] == "1"
    assert nodes[("168", "select")] == "1"
    assert nodes[("165", "select")] == "1"
    assert nodes[("166", "select")] == "1"
    # 超量的第 3 个音频/视频不上传
    assert "a3.wav" not in driver._storage.calls
    assert "v3.mp4" not in driver._storage.calls


def test_build_create_request_prefers_optimized_prompt():
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        extra_config=(
            '{"image_mode": "multi_reference", '
            '"original_prompt": "两个人在跳舞", '
            '"h3_prompt_optimize": {"variant": "Ref2VA", "optimized_prompt": "subject_definitions: ..."}}'
        ),
    )))

    nodes = node_map(request)
    assert nodes[("138", "value")] == "subject_definitions: ..."


def test_build_create_request_requires_reference_image():
    driver = make_driver()
    tool = make_ai_tool(reference_images=None, video_path="clip1.mp4")
    try:
        asyncio.run(driver.build_create_request(tool))
    except ValueError:
        return
    raise AssertionError("无参考图时应抛 ValueError（仅有参考视频不够）")


def test_build_create_request_skips_audios_without_dialogue():
    """无对白镜头不上传参考音频（口径同 KFRef）：音频槽旁路，参考视频不受影响。"""
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        audio_path="voice1.wav",
        video_path="clip1.mp4",
    )))

    nodes = node_map(request)
    assert nodes[("155", "audio")] == ""
    assert nodes[("163", "audio")] == ""
    assert nodes[("167", "select")] == "2"
    assert nodes[("168", "select")] == "2"
    # 音频不上传，参考视频照常
    assert "voice1.wav" not in driver._storage.calls
    assert nodes[("158", "video")] == "openapi/clip1.mp4"
    assert nodes[("165", "select")] == "1"


def test_build_create_request_dialogue_flag_from_llm_takes_priority():
    """has_dialogue 语义标记优先：LLM 判有台词（正则无引号）时音频照传，判无台词时拦截。"""
    meta = '{"image_mode": "multi_reference", "h3_prompt_optimize": ' \
          '{"variant": "Ref2VA", "has_dialogue": true, "optimized_prompt": "ok"}}'
    driver = make_driver()
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        prompt="无引号但语义有台词",
        audio_path="voice1.wav",
        extra_config=meta,
    )))
    assert node_map(request)[("155", "audio")] == "openapi/voice1.wav"

    meta_false = meta.replace('"has_dialogue": true', '"has_dialogue": false')
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        prompt='他说："今天到此为止。"',  # 正则判有台词，但 LLM 标记 False 优先
        audio_path="voice1.wav",
        extra_config=meta_false,
    )))
    assert node_map(request)[("155", "audio")] == ""


def test_build_create_request_strips_voice_note_without_dialogue():
    """无对白回退原文时剥掉注入的音色说明句（1816：「角色说话时请保持相同音色」
    诱导发声）；说明剥除后音频门控/提示词均干净。"""
    driver = make_driver()
    prompt = "舞台远景，观众安静。" + "\n\n参考音频说明：音频1是角色：朱俊的音色样本，角色说话时请保持相同音色。"
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        prompt=prompt,
        audio_path="voice1.wav",
    )))

    nodes = node_map(request)
    # 音频不上传（无对白）
    assert nodes[("155", "audio")] == ""
    # 音色说明句已剥除，正文保留
    assert "参考音频说明" not in nodes[("138", "value")]
    assert "舞台远景，观众安静。" == nodes[("138", "value")]


def test_build_create_request_keeps_voice_note_with_dialogue():
    """有对白时说明句与音频照常保留。"""
    driver = make_driver()
    prompt = '朱俊说："今天到此为止。"' + "\n\n参考音频说明：音频1是角色：朱俊的音色样本，角色说话时请保持相同音色。"
    request = asyncio.run(driver.build_create_request(make_ai_tool(
        prompt=prompt,
        audio_path="voice1.wav",
    )))

    nodes = node_map(request)
    assert nodes[("155", "audio")] == "openapi/voice1.wav"
    assert "参考音频说明" in nodes[("138", "value")]
