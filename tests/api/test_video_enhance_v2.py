"""视频高清修复（visual_task 驱动模式）防回归测试。

架构：/api/video-enhance 只落库并入队（模式同视频去水印），RunningHub 上传
与 OpenAPI v2 AI App 提交由调度进程的 video_enhance_runninghub_v1 驱动完成
（app 2064116518987845634：node 46 视频 / 108 模型切换 / 112 最大分辨率）；
状态由后台驱动轮询回写 ai_tools，前端改轮询 /api/get-status/{ai_tool_id}。

历史背景：曾长期在 server.py 端点内同步提交（旧 webappId + 硬编码 apiKey，
必失败），2026-10-28 重构为驱动模式；算力按 ffprobe 探测的视频秒数向上
取整吸附 4-15 档计费。

红线：
- 算力表必须等于 MINIMAX_H3_DIGITAL_HUMAN_COMPUTING_POWER（4-15 档）的 2 倍；
- 端点只落库入队（type 统一 TaskTypeId.VIDEO_ENHANCE、duration=档位、
  status=PENDING），不得在请求线程内触达 RunningHub；
- 驱动提交必须带新 AI App 三节点参数，状态轮询走 v1 /task/openapi/*。
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient


# ==================== 算力表梯度 ====================

def test_power_table_is_double_h3_gradient():
    """高清修复算力 = MiniMax H3 梯度（4-15 档）的 2 倍。"""
    from config.unified_config import (
        MINIMAX_H3_720P_COMPUTING_POWER,
        MINIMAX_H3_DIGITAL_HUMAN_COMPUTING_POWER,
        VIDEO_ENHANCE_COMPUTING_POWER,
    )

    for seconds, power in MINIMAX_H3_DIGITAL_HUMAN_COMPUTING_POWER.items():
        assert VIDEO_ENHANCE_COMPUTING_POWER[seconds] == power * 2
    # 4-10 档锚点：H3 720P 表的 2 倍
    for seconds, power in MINIMAX_H3_720P_COMPUTING_POWER.items():
        assert VIDEO_ENHANCE_COMPUTING_POWER[seconds] == power * 2


def test_power_table_extends_11_to_15_and_caps_at_15():
    """11-15 档按 H3 既有梯度外推后 ×2，且档位（表的键）不得出现 >15。"""
    from config.constant import VIDEO_ENHANCE_MAX_DURATION_SECONDS
    from config.unified_config import VIDEO_ENHANCE_COMPUTING_POWER

    assert sorted(VIDEO_ENHANCE_COMPUTING_POWER) == list(range(4, 16))
    assert VIDEO_ENHANCE_COMPUTING_POWER[12] == 32
    assert VIDEO_ENHANCE_COMPUTING_POWER[15] == 40
    assert max(VIDEO_ENHANCE_COMPUTING_POWER) <= VIDEO_ENHANCE_MAX_DURATION_SECONDS


def test_task_config_charges_by_duration():
    from config.constant import TaskTypeRegistry, TaskTypeId

    config = TaskTypeRegistry.get(TaskTypeId.VIDEO_ENHANCE)
    assert config.get_computing_power(4) == 10
    assert config.get_computing_power(10) == 26
    assert config.get_computing_power(15) == 40


def test_task_registered_as_runninghub_driver():
    """任务必须挂在 RUNNINGHUB 供应商 + 驱动映射上（密钥池/槽位管理依赖此归类）。

    注册链路：TaskTypeRegistry.get_driver_mapping()[type_id] -> driver_name，
    DRIVER_IMPLEMENTATION_MAPPING[driver_name] -> 实现方名（驱动工厂按此创建）。
    """
    from config.constant import (
        DRIVER_IMPLEMENTATION_MAPPING,
        RUNNINGHUB_TASK_TYPES,
        TaskProvider,
        TaskTypeRegistry,
        TaskTypeId,
    )
    from config.unified_config import DriverImplementation, DriverKey, get_implementation_id

    config = TaskTypeRegistry.get(TaskTypeId.VIDEO_ENHANCE)
    assert config.provider == TaskProvider.RUNNINGHUB
    assert TaskTypeId.VIDEO_ENHANCE in RUNNINGHUB_TASK_TYPES
    assert TaskTypeRegistry.get_driver_mapping()[TaskTypeId.VIDEO_ENHANCE] == DriverKey.VIDEO_ENHANCE
    assert DRIVER_IMPLEMENTATION_MAPPING[DriverKey.VIDEO_ENHANCE] == DriverImplementation.VIDEO_ENHANCE_RUNNINGHUB_V1
    assert get_implementation_id('video_enhance_runninghub_v1') > 0


# ==================== 参数 schema（配置驱动） ====================

def test_params_schema_defined_and_exposed_to_frontend():
    """schema 唯一定义在 unified_config；video_enhance 任务配置透出 params_schema。"""
    from config.constant import TaskTypeRegistry, TaskTypeId
    from config.unified_config import VIDEO_ENHANCE_PARAMS_SCHEMA, validate_video_enhance_params

    # 本期只开放 max_resolution（node 112）；node 108/instanceType 不开放
    assert [item["key"] for item in VIDEO_ENHANCE_PARAMS_SCHEMA] == ["max_resolution"]
    item = VIDEO_ENHANCE_PARAMS_SCHEMA[0]
    assert item["type"] == "select"
    assert item["node_id"] == "112"
    assert item["field_name"] == "value"
    assert item["default"] == "1920"
    assert {opt["value"] for opt in item["options"]} == {"720", "1080", "1440", "1920"}

    config = TaskTypeRegistry.get(TaskTypeId.VIDEO_ENHANCE)
    assert config.params_schema == VIDEO_ENHANCE_PARAMS_SCHEMA

    # 透出到前端任务配置（to_frontend_dict 含 params_schema）
    frontend = config.to_frontend_dict()
    assert frontend["params_schema"] == VIDEO_ENHANCE_PARAMS_SCHEMA

    # 校验函数：合法通过 / 非法拒绝
    assert validate_video_enhance_params({"max_resolution": "1080"}) == {"max_resolution": "1080"}
    with pytest.raises(ValueError):
        validate_video_enhance_params({"max_resolution": "9999"})
    with pytest.raises(ValueError):
        validate_video_enhance_params({"unknown_key": "1080"})
    with pytest.raises(ValueError):
        validate_video_enhance_params("not-a-dict")


# ==================== 提交端点（只落库入队） ====================

def _enhance_client(monkeypatch, probed_duration, created, queued):
    import server as server_mod

    monkeypatch.setattr(
        "model.user_tokens.UserTokensModel.get_user_id_by_token",
        staticmethod(lambda token: 1 if token == "valid-token" else None),
    )
    monkeypatch.setattr(server_mod, "CHECK_AUTH_TOKEN", False)
    # 远程 URL 分支：不解析本地缓存，不触达 RunningHubFileStorage
    monkeypatch.setattr(
        server_mod, "_resolve_local_upload_path", lambda url, prefix: None
    )

    async def _probe(source):
        return probed_duration

    monkeypatch.setattr(server_mod, "_probe_video_duration_seconds", _probe)
    monkeypatch.setattr(
        server_mod.VideoDriverFactory, "get_implementation_for_user",
        staticmethod(lambda task_type, user_id: "video_enhance_runninghub_v1"),
    )

    def _create(**kwargs):
        created.append(kwargs)
        return 321

    def _enqueue(**kwargs):
        queued.append(kwargs)

    monkeypatch.setattr(server_mod.AIToolsModel, "create", staticmethod(_create))
    monkeypatch.setattr(server_mod.TasksModel, "create", staticmethod(_enqueue))
    return TestClient(server_mod.app)


def _post_enhance(client, **extra):
    data = {"video_url": "https://example.com/video.mp4", "user_id": "1", **extra}
    return client.post(
        "/api/video-enhance",
        data=data,
        headers={"Authorization": "Bearer valid-token", "X-User-Id": "1"},
    )


def test_submit_only_queues_task_with_duration_tier(monkeypatch):
    """7.3s 吸附到 8 秒档（算力 20）；端点只落库入队，不触达 RunningHub。"""
    created, queued = [], []
    client = _enhance_client(monkeypatch, 7.3, created, queued)

    resp = _post_enhance(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["duration"] == 8
    assert body["computing_power"] == 20
    # project_id 是 ai_tools 主键（前端轮询 /api/get-status/{project_id}）
    assert body["project_id"] == 321

    assert created, "必须创建 ai_tools 记录"
    record = created[0]
    assert record["type"] == 5  # TaskTypeId.VIDEO_ENHANCE（不再 5/6 混用）
    assert record["duration"] == 8
    assert record["video_path"] == "https://example.com/video.mp4"
    assert record["status"] == 0  # AI_TOOL_STATUS_PENDING，待驱动提交
    assert record["implementation"] > 0

    assert queued, "必须入队等待调度器驱动"
    assert queued[0]["task_id"] == 321
    assert queued[0]["status"] == 0  # TASK_STATUS_QUEUED


def test_submit_marks_history_source_for_legacy_param(monkeypatch):
    """营销页旧参数 enhance_type=6：落库 type 仍统一为 5，来源标记进 extra_config。"""
    created, queued = [], []
    client = _enhance_client(monkeypatch, 5.0, created, queued)

    resp = _post_enhance(client, enhance_type="6")
    assert resp.status_code == 200, resp.text
    assert created[0]["type"] == 5
    assert json.loads(created[0]["extra_config"]) == {"source": "history"}


def test_submit_with_valid_params_stored_in_extra_config(monkeypatch):
    """合法 params 按 schema 校验后并入 extra_config["params"] 落库。"""
    created, queued = [], []
    client = _enhance_client(monkeypatch, 5.0, created, queued)

    resp = _post_enhance(client, params='{"max_resolution":"1080"}')
    assert resp.status_code == 200, resp.text
    extra_config = json.loads(created[0]["extra_config"])
    assert extra_config["params"] == {"max_resolution": "1080"}


def test_submit_with_invalid_param_value_rejected(monkeypatch):
    """值不在 options 白名单：400 拒绝，不静默丢弃，不落库不入队。"""
    created, queued = [], []
    client = _enhance_client(monkeypatch, 5.0, created, queued)

    resp = _post_enhance(client, params='{"max_resolution":"9999"}')
    assert resp.status_code == 400
    assert "max_resolution" in resp.json()["detail"]
    assert not created
    assert not queued


def test_submit_with_unknown_param_key_rejected(monkeypatch):
    """未知参数名：400 拒绝（schema 之外的 key 一律不收）。"""
    created, queued = [], []
    client = _enhance_client(monkeypatch, 5.0, created, queued)

    resp = _post_enhance(client, params='{"foo":"bar"}')
    assert resp.status_code == 400
    assert not created
    assert not queued


def test_submit_with_malformed_params_rejected(monkeypatch):
    """params 不是合法 JSON：400 拒绝。"""
    created, queued = [], []
    client = _enhance_client(monkeypatch, 5.0, created, queued)

    resp = _post_enhance(client, params='not-a-json')
    assert resp.status_code == 400
    assert not created
    assert not queued


@pytest.mark.parametrize("probed,expected_tier,expected_power", [
    (3.2, 4, 10),     # 低于下限吸附到 4 秒档
    (15.0, 15, 40),   # 恰好 15 秒（浮点边界）
])
def test_submit_duration_snapping(monkeypatch, probed, expected_tier, expected_power):
    created, queued = [], []
    client = _enhance_client(monkeypatch, probed, created, queued)
    resp = _post_enhance(client)
    assert resp.status_code == 200, resp.text
    assert resp.json()["duration"] == expected_tier
    assert resp.json()["computing_power"] == expected_power


def test_submit_over_15s_rejected(monkeypatch):
    """超过 15 秒上限必须 400 拒绝（不落库、不入队、不扣费）。"""
    created, queued = [], []
    client = _enhance_client(monkeypatch, 16.0, created, queued)
    resp = _post_enhance(client)
    assert resp.status_code == 400
    assert "15" in resp.json()["detail"]
    assert not created
    assert not queued


def test_submit_probe_failure_falls_back_to_form_duration(monkeypatch):
    """ffprobe 探测失败：回退调用方时长档位（12 秒 -> 算力 32）。"""
    created, queued = [], []
    client = _enhance_client(monkeypatch, None, created, queued)
    resp = _post_enhance(client, duration_seconds="12")
    assert resp.status_code == 200, resp.text
    assert resp.json()["duration"] == 12
    assert resp.json()["computing_power"] == 32
    assert created[0]["duration"] == 12


def test_submit_probe_failure_without_fallback_rejected(monkeypatch):
    created, queued = [], []
    client = _enhance_client(monkeypatch, None, created, queued)
    resp = _post_enhance(client)
    assert resp.status_code == 400
    assert not created
    assert not queued


# ==================== 驱动（v2 提交 + v1 轮询） ====================

_DRIVER_MODULE = "task.visual_drivers.video_enhance_runninghub_v1_driver"


def _driver():
    from task.visual_drivers.video_enhance_runninghub_v1_driver import (
        VideoEnhanceRunninghubV1Driver,
    )

    with patch(
        f"{_DRIVER_MODULE}.get_dynamic_config_value",
        side_effect=lambda section, key, default="": {
            ("runninghub", "host"): "https://www.runninghub.cn",
            ("runninghub", "api_key"): "test-api-key",
            ("timeout", "request_timeout"): 30,
        }.get((section, key), default),
    ), patch(
        f"{_DRIVER_MODULE}.get_config", return_value={"timeout": {}},
    ), patch(f"{_DRIVER_MODULE}.RunningHubFileStorage"):
        return VideoEnhanceRunninghubV1Driver()


def _ai_tool(duration=8, video_path="/upload/temp/video.mp4", extra_config=None):
    return SimpleNamespace(
        id=77,
        video_path=video_path,
        duration=duration,
        prompt="视频高清修复",
        extra_config=extra_config,
    )


def _build_request(driver, ai_tool):
    async def _upload(path):
        return "abc123.mp4"

    driver._upload_video = _upload
    return asyncio.run(driver.build_create_request(ai_tool))


def test_driver_build_create_request_nodes():
    """提交请求必须带新 AI App 的三节点参数与 Bearer 认证。"""
    driver = _driver()

    async def _upload(path):
        assert path == "/upload/temp/video.mp4"
        return "abc123.mp4"

    driver._upload_video = _upload
    request = asyncio.run(driver.build_create_request(_ai_tool(duration=8)))

    assert request["url"] == "https://www.runninghub.cn/openapi/v2/run/ai-app/2064116518987845634"
    assert request["headers"]["Authorization"] == "Bearer test-api-key"
    # SeedVR2 超分在 default(24G) 实测必 OOM，必须提交 plus(48G) 实例
    assert request["json"]["instanceType"] == "plus"
    nodes = {n["nodeId"]: n for n in request["json"]["nodeInfoList"]}
    assert nodes["46"]["fieldName"] == "video"
    assert nodes["46"]["fieldValue"] == "abc123.mp4"
    assert nodes["108"]["fieldName"] == "select"
    assert nodes["108"]["fieldValue"] == "1"
    assert nodes["112"]["fieldName"] == "value"
    assert nodes["112"]["fieldValue"] == "1920"


def test_driver_build_create_request_with_max_resolution_param():
    """用户经 extra_config.params 传入合法 max_resolution=1080 → node 112 取用户值。"""
    driver = _driver()
    ai_tool = _ai_tool(extra_config=json.dumps({"params": {"max_resolution": "1080"}}))
    request = _build_request(driver, ai_tool)

    nodes = {n["nodeId"]: n for n in request["json"]["nodeInfoList"]}
    assert nodes["112"]["fieldValue"] == "1080"


def test_driver_build_create_request_param_not_passed_uses_default():
    """不传 params（extra_config 无 params 字段）→ node 112 回落 schema default 1920。"""
    driver = _driver()
    request = _build_request(driver, _ai_tool(extra_config=json.dumps({"source": "direct"})))

    nodes = {n["nodeId"]: n for n in request["json"]["nodeInfoList"]}
    assert nodes["112"]["fieldValue"] == "1920"


@pytest.mark.parametrize("raw_params", [
    {"max_resolution": "9999"},   # 不在 options 白名单
    {"max_resolution": 1080},     # 类型不符（int 不在 str 白名单）
    "not-a-dict",                 # params 不是对象
])
def test_driver_build_create_request_invalid_param_falls_back_to_default(raw_params):
    """驱动不信任库数据：非法 params 告警后回落 default，不影响三节点提交。"""
    driver = _driver()
    ai_tool = _ai_tool(extra_config=json.dumps({"params": raw_params}))
    request = _build_request(driver, ai_tool)

    nodes = {n["nodeId"]: n for n in request["json"]["nodeInfoList"]}
    assert nodes["46"]["fieldName"] == "video"
    assert nodes["108"]["fieldValue"] == "1"
    assert nodes["112"]["fieldValue"] == "1920"


def test_driver_rejects_invalid_duration():
    driver = _driver()
    with pytest.raises(ValueError):
        driver._resolve_duration(16)
    with pytest.raises(ValueError):
        driver._resolve_duration(None)
    assert driver._resolve_duration(15) == 15


def test_driver_submit_task_success():
    driver = _driver()
    driver._upload_video = AsyncMock(return_value="abc123.mp4")
    driver._request = MagicMock(return_value={"taskId": "rh-100", "status": "RUNNING"})

    result = asyncio.run(driver.submit_task(_ai_tool()))
    assert result == {"success": True, "project_id": "rh-100"}


def test_driver_submit_task_upstream_error():
    driver = _driver()
    driver._upload_video = AsyncMock(return_value="abc123.mp4")
    driver._request = MagicMock(return_value={
        "taskId": "", "errorCode": "APIKEY_EXPIRED", "errorMessage": "api key invalid",
    })

    result = asyncio.run(driver.submit_task(_ai_tool()))
    assert result["success"] is False
    assert "api key invalid" in result["error"]
    assert result["retry"] is False


def test_driver_submit_upload_transient_error_is_retryable():
    """上传瞬态失败（网络抖动）必须可重试，不消耗用户一次任务。"""
    driver = _driver()
    driver._upload_video = AsyncMock(side_effect=RuntimeError("503"))

    result = asyncio.run(driver.submit_task(_ai_tool()))
    assert result["success"] is False
    assert result["retry"] is True


def test_driver_check_status_running_and_success():
    driver = _driver()
    # RUNNING：v1 /task/openapi/status
    driver._request = MagicMock(return_value={"code": 0, "data": "RUNNING"})
    assert driver.check_status("rh-100")["status"] == "RUNNING"

    # SUCCESS：v1 /task/openapi/outputs，视频扩展名优先于中间图片
    outputs = [
        {"fileUrl": "https://rh/mid.png", "fileType": "png", "nodeId": "2"},
        {"fileUrl": "https://rh/out.mp4?sign=x", "fileType": "mp4", "nodeId": "46"},
    ]
    driver._request = MagicMock(side_effect=[
        {"code": 0, "data": "SUCCESS"},   # status
        {"code": 0, "data": outputs},     # outputs
    ])
    result = driver.check_status("rh-100")
    assert result["status"] == "SUCCESS"
    assert result["result_url"] == "https://rh/out.mp4?sign=x"


def test_driver_check_status_failed():
    driver = _driver()
    driver._request = MagicMock(return_value={"code": 0, "data": "FAILED"})
    result = driver.check_status("rh-100")
    assert result["status"] == "FAILED"


def test_driver_registered_in_factory():
    from task.visual_drivers.driver_factory import VideoDriverFactory
    from config.unified_config import DriverImplementation

    registered = VideoDriverFactory._registered_drivers
    assert DriverImplementation.VIDEO_ENHANCE_RUNNINGHUB_V1 in registered
