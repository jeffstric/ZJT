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
        if "resume_last" in str(path):
            return SimpleNamespace(success=True, url="https://rh.example/relay.jpg",
                                   key="openapi/relay.jpg", error=None)
        return SimpleNamespace(success=True, url="https://rh.example/role.png",
                               key="openapi/role.png", error=None)

    driver._upload_to_runninghub_sync = MagicMock(side_effect=fake_upload)
    driver._upload_segment_audio = MagicMock(return_value="openapi/audio.wav")
    submit_mock = MagicMock(return_value=("rh-task-x", ""))
    driver._submit_one_segment = submit_mock
    wait_mock = MagicMock(return_value=(True, ""))
    driver._wait_and_download_segment = wait_mock
    extract_mock = MagicMock(return_value="temp/resume_last.png")
    driver._extract_last_frame = extract_mock
    concat_mock = MagicMock(return_value="/upload/cache/2026-01-01/x.mp4")
    driver._concat_and_store = concat_mock
    return submit_mock, extract_mock, concat_mock, wait_mock


_SEG_EXTRA = '{"dh_segments": ["/tmp/seg1.wav", "/tmp/seg2.wav"], ' \
             '"dh_segment_durations": [10, 10], "max_edge": 1280}'
_SEG_PATHS = ["/tmp/seg1.wav", "/tmp/seg2.wav"]
_SEG_CONFIG = {"dh_segment_durations": [10, 10], "max_edge": 1280}


def test_submit_segments_resumes_from_cached_segments(monkeypatch, tmp_path):
    """断点续跑：temp 已有上一轮完整下载的 seg_1 时，重试只提交 seg_2，
    且首帧取自已复用段的末帧（接力衔接），不得重复生成 seg_1。"""
    monkeypatch.chdir(tmp_path)
    _write_fake_ffprobe(monkeypatch, duration="10.0")
    os.makedirs('temp', exist_ok=True)
    with open('temp/h3seg_1_seg_1.mp4', 'wb') as f:
        f.write(b"x" * 70000)

    driver = make_driver()
    submit_mock, extract_mock, concat_mock, _ = _make_segment_pipeline_mocks(driver)
    ai_tool = make_ai_tool(extra_config=_SEG_EXTRA)

    result = driver._submit_segments_async(ai_tool, _SEG_PATHS, _SEG_CONFIG)

    assert result["success"] is True
    # seg_1 被复用：整轮只提交一次（seg_2）
    assert submit_mock.call_count == 1
    call = submit_mock.call_args[0]
    assert call[0] == "https://rh.example/relay.jpg"  # 首帧=复用段末帧，非角色图
    assert call[2] == 10  # seg_2 时长档位
    # 复用段末帧确实取自缓存的 seg_1 成片
    assert extract_mock.call_args_list[0][0][0] == 'temp/h3seg_1_seg_1.mp4'
    # 拼接输入 = 复用段 + 新生成段
    concat_mock.assert_called_once_with(
        1, ['temp/h3seg_1_seg_1.mp4', 'temp/h3seg_1_seg_2.mp4'])


def test_submit_segments_regenerates_when_cache_corrupt(monkeypatch, tmp_path):
    """缓存段成片校验不通过（ffprobe 时长与档位偏差过大，疑似截断残文件）时，
    必须从 seg_1 重新生成，不得复用损坏文件。"""
    monkeypatch.chdir(tmp_path)
    _write_fake_ffprobe(monkeypatch, duration="4.0")  # 期望 10s，偏差 >3s → 无效
    os.makedirs('temp', exist_ok=True)
    with open('temp/h3seg_1_seg_1.mp4', 'wb') as f:
        f.write(b"x" * 70000)

    driver = make_driver()
    submit_mock, _, concat_mock, _ = _make_segment_pipeline_mocks(driver)
    ai_tool = make_ai_tool(extra_config=_SEG_EXTRA)

    result = driver._submit_segments_async(ai_tool, _SEG_PATHS, _SEG_CONFIG)

    assert result["success"] is True
    assert submit_mock.call_count == 2  # seg_1、seg_2 全部重新提交
    # seg_1 首帧回退为角色图（无复用段）
    assert submit_mock.call_args_list[0][0][0] == "https://rh.example/role.png"
    concat_mock.assert_called_once_with(
        1, ['temp/h3seg_1_seg_1.mp4', 'temp/h3seg_1_seg_2.mp4'])


def test_submit_segments_all_cached_skips_submission(monkeypatch, tmp_path):
    """全部段成片已缓存时（如拼接前 worker 重启），直接拼接，不再提交任何上游任务。"""
    monkeypatch.chdir(tmp_path)
    _write_fake_ffprobe(monkeypatch, duration="10.0")
    os.makedirs('temp', exist_ok=True)
    for idx in (1, 2):
        with open(f'temp/h3seg_1_seg_{idx}.mp4', 'wb') as f:
            f.write(b"x" * 70000)

    driver = make_driver()
    submit_mock, _, concat_mock, _ = _make_segment_pipeline_mocks(driver)
    ai_tool = make_ai_tool(extra_config=_SEG_EXTRA)

    result = driver._submit_segments_async(ai_tool, _SEG_PATHS, _SEG_CONFIG)

    assert result["success"] is True
    submit_mock.assert_not_called()
    concat_mock.assert_called_once_with(
        1, ['temp/h3seg_1_seg_1.mp4', 'temp/h3seg_1_seg_2.mp4'])


def test_submit_segments_resubmits_once_on_generation_failure(monkeypatch, tmp_path):
    """段上游生成失败时换新任务自动重提一次；重提成功则流水线继续完成。"""
    monkeypatch.chdir(tmp_path)
    driver = make_driver()
    submit_mock, _, concat_mock, wait_mock = _make_segment_pipeline_mocks(driver)

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
    不得带着不存在的段文件继续跑后续段，也不得走到拼接才报错。"""
    import pytest
    from task.visual_drivers import digital_human_minimax_h3_runninghub_v1_driver as drv_mod

    monkeypatch.chdir(tmp_path)
    driver = make_driver()
    submit_mock, _, concat_mock, wait_mock = _make_segment_pipeline_mocks(driver)
    wait_mock.side_effect = [(False, "上游任务失败"), (False, "上游任务失败")]
    ai_tool = make_ai_tool(extra_config=_SEG_EXTRA)

    with pytest.raises(drv_mod._SegmentedPipelineError) as exc_info:
        driver._submit_segments_async(ai_tool, _SEG_PATHS, _SEG_CONFIG)

    msg = str(exc_info.value)
    assert "第 1 段重试后仍失败" in msg
    assert "上游任务失败" in msg  # 根因如实上报，而非误导性的「拼接失败」
    assert submit_mock.call_count == 2  # 首次提交 + 一次重提，不再多跑
    concat_mock.assert_not_called()  # 带刹车：后续段与拼接均未执行


def test_extract_last_frame_png_two_stage_true_last(monkeypatch, tmp_path):
    """无损末帧：快路径 -sseof 窗口 + -update 1 覆盖写（禁 -frames:v 1，否则取到
    窗口第一帧而非真正末帧），快路径空输出时降级全片解码；输出为无损 PNG。"""
    from task.visual_drivers import digital_human_minimax_h3_runninghub_v1_driver as drv_mod

    calls = []

    def fake_run(argv, *args, **kwargs):
        calls.append(argv)
        if len(calls) == 1:
            # 快路径空输出（未写文件），触发兜底
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with open(argv[-1], "wb") as f:
            f.write(b"x" * 2048)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(drv_mod, "_get_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(drv_mod.subprocess, "run", fake_run)

    driver = make_driver()
    out_png = str(tmp_path / "last.png")
    assert driver._extract_last_frame(str(tmp_path / "seg.mp4"), out_png) == out_png
    assert len(calls) == 2  # 快路径 + 全片解码兜底
    assert "-sseof" in calls[0] and "-update" in calls[0]
    assert "-frames:v" not in calls[0]
    assert "-sseof" not in calls[1]  # 兜底为全片解码


def test_is_reanchor_segment():
    """回锚点：每接力 N=2 段后回锚一次 → 段 3/5/7，段 1 与接力段不回锚。"""
    from task.visual_drivers.digital_human_minimax_h3_runninghub_v1_driver import (
        DIGITAL_HUMAN_REANCHOR_SEGMENT_INTERVAL as N,
    )

    assert N == 2
    reanchors = [i for i in range(1, 11)
                 if DigitalHumanMinimaxH3RunninghubV1Driver._is_reanchor_segment(i)]
    assert reanchors == [3, 5, 7, 9]


def test_submit_segments_reanchors_to_role_image_every_2(monkeypatch, tmp_path):
    """每接力 2 段回锚角色原图：seg_2/seg_4 首帧接力末帧，seg_3 回锚角色图，
    阻断「抽帧→再生成」循环的亮度/噪声累积漂移。"""
    monkeypatch.chdir(tmp_path)
    driver = make_driver()

    def fake_upload(path):
        p = str(path)
        if p.endswith("_last.png") or "resume_last" in p:
            return SimpleNamespace(
                success=True, url=f"https://rh.example/relay_{os.path.basename(p)}",
                key="k", error=None)
        return SimpleNamespace(success=True, url="https://rh.example/role.png",
                               key="openapi/role.png", error=None)

    driver._upload_to_runninghub_sync = MagicMock(side_effect=fake_upload)
    driver._upload_segment_audio = MagicMock(return_value="openapi/audio.wav")
    submit_mock = MagicMock(return_value=("rh-task-x", ""))
    driver._submit_one_segment = submit_mock
    driver._wait_and_download_segment = MagicMock(return_value=(True, ""))
    driver._extract_last_frame = MagicMock(side_effect=lambda seg, out: out)
    driver._concat_and_store = MagicMock(return_value="/upload/cache/x.mp4")
    driver._measure_avg_brightness = MagicMock(return_value=150.0)

    paths = ["/tmp/s1.wav", "/tmp/s2.wav", "/tmp/s3.wav", "/tmp/s4.wav"]
    extra = {"dh_segment_durations": [10, 10, 10, 10], "max_edge": 1280}
    ai_tool = make_ai_tool(extra_config=_json.dumps({
        "dh_segments": paths, "dh_segment_durations": [10, 10, 10, 10],
        "max_edge": 1280}))

    result = driver._submit_segments_async(ai_tool, paths, extra)

    assert result["success"] is True
    images = [c[0][0] for c in submit_mock.call_args_list]
    assert images[0] == "https://rh.example/role.png"   # seg_1 角色图
    assert "relay" in images[1]                         # seg_2 接力末帧
    assert images[2] == "https://rh.example/role.png"   # seg_3 回锚角色原图
    assert "relay" in images[3]                         # seg_4 接力末帧


def test_submit_segments_resubmits_once_on_black_segment(monkeypatch, tmp_path):
    """黑段检测：段成片亮度低于下限视同生成失败，换新任务自动重提一次；
    重提后亮度恢复则流水线继续完成。"""
    monkeypatch.chdir(tmp_path)
    driver = make_driver()
    submit_mock, _, concat_mock, _ = _make_segment_pipeline_mocks(driver)

    state = {"n": 0}

    def fake_measure(path):
        if str(path).endswith("h3seg_1_seg_1.mp4"):
            state["n"] += 1
            return 30.0 if state["n"] == 1 else 150.0  # 首轮黑段，重提后恢复
        return 150.0

    driver._measure_avg_brightness = MagicMock(side_effect=fake_measure)
    ai_tool = make_ai_tool(extra_config=_SEG_EXTRA)

    result = driver._submit_segments_async(ai_tool, _SEG_PATHS, _SEG_CONFIG)

    assert result["success"] is True
    # seg_1 初提 + 黑段重提，seg_2 正常提交
    assert submit_mock.call_count == 3
    concat_mock.assert_called_once()


def test_submit_segments_falls_back_to_role_image_on_persistent_black(monkeypatch, tmp_path):
    """黑段双杀不判失败：回退数字人输入的角色原图作为该段首帧重新生成并放行；
    回退后整条链固定角色原图首帧（12811 实证：场景固有暗会被相对判据误判）。"""
    monkeypatch.chdir(tmp_path)
    driver = make_driver()
    submit_mock, extract_mock, concat_mock, _ = _make_segment_pipeline_mocks(driver)
    driver._measure_avg_brightness = MagicMock(return_value=30.0)  # 始终判黑
    ai_tool = make_ai_tool(extra_config=_SEG_EXTRA)

    result = driver._submit_segments_async(ai_tool, _SEG_PATHS, _SEG_CONFIG)

    assert result["success"] is True
    # seg_1 初提 + 黑段重提 + 回退角色原图重提，seg_2 黑段回退后固定角色图直接提交
    assert submit_mock.call_count == 4
    # 第 3 次起首帧均为角色图 URL（回退触发）
    assert submit_mock.call_args_list[2][0][0] == "https://rh.example/role.png"
    assert submit_mock.call_args_list[3][0][0] == "https://rh.example/role.png"
    # 回退后跳过末帧接力
    extract_mock.assert_not_called()
    concat_mock.assert_called_once()


def test_submit_segments_brakes_when_fallback_generation_fails(monkeypatch, tmp_path):
    """黑段回退后的角色原图重生成仍失败（上游/下载问题）才抛错带刹车，
    黑段本身永不作为失败理由。"""
    import pytest
    from task.visual_drivers import digital_human_minimax_h3_runninghub_v1_driver as drv_mod

    monkeypatch.chdir(tmp_path)
    driver = make_driver()
    submit_mock, _, concat_mock, wait_mock = _make_segment_pipeline_mocks(driver)
    driver._measure_avg_brightness = MagicMock(return_value=30.0)

    def wait_side_effect(task_id, out_path, tag):
        if tag == "seg_1_role":
            return (False, "上游任务失败")
        return (True, "")

    wait_mock.side_effect = wait_side_effect
    ai_tool = make_ai_tool(extra_config=_SEG_EXTRA)

    with pytest.raises(drv_mod._SegmentedPipelineError) as exc_info:
        driver._submit_segments_async(ai_tool, _SEG_PATHS, _SEG_CONFIG)

    msg = str(exc_info.value)
    assert "黑段回退后仍生成失败" in msg
    assert "上游任务失败" in msg
    concat_mock.assert_not_called()


def test_check_segment_brightness_degrades_on_measure_failure(monkeypatch, tmp_path):
    """亮度测量失败（ffmpeg 异常/无输出）时检测降级放行，不得阻塞流水线。"""
    driver = make_driver()
    driver._measure_avg_brightness = MagicMock(return_value=None)
    assert driver._check_segment_brightness(
        str(tmp_path / "seg.mp4"), 150.0, "seg_x") is False
