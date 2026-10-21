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


def test_submit_task_segmented_congestion_returns_upstream_retry(monkeypatch):
    """分段链路命中上游 421 拥堵时，submit_task 必须转成 UPSTREAM_CONGESTED 延迟重试，
    不得落入通用异常分支被判为不可重试硬失败（会误报 Sentry 并退算力终态失败）。"""
    from task.visual_drivers import digital_human_minimax_h3_runninghub_v1_driver as drv_mod

    driver = make_driver()
    driver._send_alert = MagicMock()
    ai_tool = make_ai_tool(
        extra_config='{"dh_segments": ["/tmp/seg1.wav"], "dh_segment_durations": [10]}'
    )

    def _boom(ai_tool, segment_paths, extra_config):
        raise drv_mod._SegmentedCongestedError("api queue limit reached")

    monkeypatch.setattr(driver, "_submit_segments_async", _boom)

    result = asyncio.run(driver.submit_task(ai_tool))

    assert result == driver._build_upstream_congested_result()
    assert result["retry"] is True
    assert result["retry_reason"] == "UPSTREAM_CONGESTED"
    driver._send_alert.assert_not_called()


import json as _json


def _write_fake_ffprobe(monkeypatch, duration="10.0"):
    """伪造 ffprobe：所有调用都返回可解析的视频流与指定时长。"""
    from task.visual_drivers import digital_human_minimax_h3_runninghub_v1_driver as drv_mod

    def fake_run(argv, *args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=_json.dumps({
                "streams": [{"width": 720, "height": 1280}],
                "format": {"duration": duration},
            }),
            stderr="")

    monkeypatch.setattr(drv_mod.subprocess, "run", fake_run)


def _make_segment_pipeline_mocks(driver):
    """mock 掉流水线的外部交互，返回各 mock 便于断言。"""

    def fake_upload(path):
        return SimpleNamespace(success=True, url="https://rh.example/role.png",
                               key="openapi/role.png", error=None)

    driver._upload_to_runninghub_sync = MagicMock(side_effect=fake_upload)
    driver._upload_segment_audio = MagicMock(return_value="openapi/audio.wav")
    submit_mock = MagicMock(return_value=("rh-task-x", ""))
    driver._submit_one_segment = submit_mock
    wait_mock = MagicMock(return_value=(True, ""))
    driver._wait_and_download_segment = wait_mock
    concat_mock = MagicMock(return_value="/upload/cache/2026-01-01/x.mp4")
    driver._concat_and_store = concat_mock
    return submit_mock, concat_mock, wait_mock


_SEG_EXTRA = '{"dh_segments": ["/tmp/seg1.wav", "/tmp/seg2.wav"], ' \
             '"dh_segment_durations": [10, 10], "max_edge": 1280}'
_SEG_PATHS = ["/tmp/seg1.wav", "/tmp/seg2.wav"]
_SEG_CONFIG = {"dh_segment_durations": [10, 10], "max_edge": 1280}


def test_submit_segments_resumes_from_cached_segments(monkeypatch, tmp_path):
    """断点续跑：temp 已有上一轮完整下载的 seg_1 时，只提交缺失的 seg_2，
    且各段首帧统一为角色图（不做末帧接力），不得重复生成 seg_1。"""
    monkeypatch.chdir(tmp_path)
    _write_fake_ffprobe(monkeypatch, duration="10.0")
    os.makedirs('temp', exist_ok=True)
    with open('temp/h3seg_1_seg_1.mp4', 'wb') as f:
        f.write(b"x" * 70000)

    driver = make_driver()
    submit_mock, concat_mock, _ = _make_segment_pipeline_mocks(driver)
    ai_tool = make_ai_tool(extra_config=_SEG_EXTRA)

    result = driver._submit_segments_async(ai_tool, _SEG_PATHS, _SEG_CONFIG)

    assert result["success"] is True
    # seg_1 被复用：整轮只提交一次（seg_2）
    assert submit_mock.call_count == 1
    call = submit_mock.call_args[0]
    assert call[0] == "https://rh.example/role.png"  # 首帧=角色图（末帧接力已移除）
    assert call[2] == 10  # seg_2 时长档位
    # 拼接输入 = 复用段 + 新生成段
    concat_mock.assert_called_once_with(
        1, [os.path.join('temp', 'h3seg_1_seg_1.mp4'),
            os.path.join('temp', 'h3seg_1_seg_2.mp4')])


def test_submit_segments_regenerates_when_cache_corrupt(monkeypatch, tmp_path):
    """缓存段成片校验不通过（ffprobe 时长与档位偏差过大，疑似截断残文件）时，
    必须从 seg_1 重新生成，不得复用损坏文件。"""
    monkeypatch.chdir(tmp_path)
    _write_fake_ffprobe(monkeypatch, duration="4.0")  # 期望 10s，偏差 >3s → 无效
    os.makedirs('temp', exist_ok=True)
    with open('temp/h3seg_1_seg_1.mp4', 'wb') as f:
        f.write(b"x" * 70000)

    driver = make_driver()
    submit_mock, concat_mock, _ = _make_segment_pipeline_mocks(driver)
    ai_tool = make_ai_tool(extra_config=_SEG_EXTRA)

    result = driver._submit_segments_async(ai_tool, _SEG_PATHS, _SEG_CONFIG)

    assert result["success"] is True
    assert submit_mock.call_count == 2  # seg_1、seg_2 全部重新提交
    # 各段首帧统一为角色图（并发下提交无序，用集合断言）
    assert {c[0][0] for c in submit_mock.call_args_list} == {"https://rh.example/role.png"}
    concat_mock.assert_called_once_with(
        1, [os.path.join('temp', 'h3seg_1_seg_1.mp4'),
            os.path.join('temp', 'h3seg_1_seg_2.mp4')])


def test_submit_segments_all_cached_skips_submission(monkeypatch, tmp_path):
    """全部段成片已缓存时（如拼接前 worker 重启），直接拼接，不再提交任何上游任务。"""
    monkeypatch.chdir(tmp_path)
    _write_fake_ffprobe(monkeypatch, duration="10.0")
    os.makedirs('temp', exist_ok=True)
    for idx in (1, 2):
        with open(f'temp/h3seg_1_seg_{idx}.mp4', 'wb') as f:
            f.write(b"x" * 70000)

    driver = make_driver()
    submit_mock, concat_mock, _ = _make_segment_pipeline_mocks(driver)
    ai_tool = make_ai_tool(extra_config=_SEG_EXTRA)

    result = driver._submit_segments_async(ai_tool, _SEG_PATHS, _SEG_CONFIG)

    assert result["success"] is True
    submit_mock.assert_not_called()
    concat_mock.assert_called_once_with(
        1, [os.path.join('temp', 'h3seg_1_seg_1.mp4'),
            os.path.join('temp', 'h3seg_1_seg_2.mp4')])


def test_submit_segments_resubmits_once_on_generation_failure(monkeypatch, tmp_path):
    """段上游生成失败时换新任务自动重提一次；重提成功则流水线继续完成。"""
    monkeypatch.chdir(tmp_path)
    driver = make_driver()
    submit_mock, concat_mock, wait_mock = _make_segment_pipeline_mocks(driver)

    def wait_side_effect(task_id, out_path, tag):
        if tag == "seg_1":
            return (False, "上游任务失败")
        return (True, "")

    wait_mock.side_effect = wait_side_effect
    ai_tool = make_ai_tool(extra_config=_SEG_EXTRA)

    result = driver._submit_segments_async(ai_tool, _SEG_PATHS, _SEG_CONFIG)

    assert result["success"] is True
    # seg_1 首次提交 + 失败后重提，seg_2 正常提交
    assert submit_mock.call_count == 3
    # seg_1 两轮等待（失败/成功）+ seg_2 一轮
    assert wait_mock.call_count == 3
    concat_mock.assert_called_once()


def test_submit_segments_brakes_when_generation_fails_twice(monkeypatch, tmp_path):
    """段生成双败必须立即抛 _SegmentedPipelineError（带真实根因）带刹车：
    不得走到拼接才报错。并发下其余段可能已提交（重跑时会被断点续跑复用），
    不影响失败语义。"""
    import pytest
    from task.visual_drivers import digital_human_minimax_h3_runninghub_v1_driver as drv_mod

    monkeypatch.chdir(tmp_path)
    driver = make_driver()
    submit_mock, concat_mock, wait_mock = _make_segment_pipeline_mocks(driver)

    def wait_side_effect(task_id, out_path, tag):
        if str(tag).startswith("seg_1"):
            return (False, "上游任务失败")
        return (True, "")

    wait_mock.side_effect = wait_side_effect
    ai_tool = make_ai_tool(extra_config=_SEG_EXTRA)

    with pytest.raises(drv_mod._SegmentedPipelineError) as exc_info:
        driver._submit_segments_async(ai_tool, _SEG_PATHS, _SEG_CONFIG)

    msg = str(exc_info.value)
    assert "第 1 段重试后仍失败" in msg
    assert "上游任务失败" in msg  # 根因如实上报，而非误导性的「拼接失败」
    assert submit_mock.call_count >= 2  # seg_1 首次提交 + 一次重提；seg_2 并发下可能已提交
    concat_mock.assert_not_called()  # 带刹车：不拼接
