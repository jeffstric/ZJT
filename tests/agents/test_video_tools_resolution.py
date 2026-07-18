"""
视频工具分辨率透传测试（智能体模式 BUG2 回归）

背景：智能体模式下用户选择的视频分辨率曾无法到达实际生成接口。
链路应为：前端 video_preferences.resolution -> set_video_preferences 缓存
-> enterprise.tools.video_tools 的 _get_video_preferences 读取
-> 经 validate_video_resolution 校验 -> 透传到 /api/ai-app-run 请求体
-> 同时纳入 get_computing_power 的 context（与 server.py 端点扣费口径一致）。

本文件验证 video_tools 这一环：读偏好、校验降级、透传请求体、算力 context。
"""
import os

import pytest

# 必须在导入会触发 model/database 的模块前，给 config_unit.yml 塞进一个最小配置缓存。
os.environ.setdefault("comfyui_env", "unit")
from config import config_util  # noqa: E402

config_util._config_cache["config_unit.yml"] = {
    "database": {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "",
        "database": "unit",
    },
    "server": {},
    "file_storage": {},
}

from config.unified_config import ImplementationConfig, UnifiedConfigRegistry  # noqa: E402


SUPPORTED_IMPL_NAME = 'test_video_impl'


class _StubConfig:
    """模拟 UnifiedConfigRegistry.get_by_id 返回的 task 配置。"""

    name = "TestVideoModel"
    supported_durations = [5, 10, 15]

    def __init__(self):
        self.last_power_context = None
        self.last_power_impl = None

    def get_computing_power(self, duration=None, implementation=None, context=None):
        # 记录算力调用参数，供断言 resolution 是否进入 context
        self.last_power_context = context
        self.last_power_impl = implementation
        return 10


@pytest.fixture
def video_impl():
    """注册一个支持 480P/720P/1080P 的测试实现，供 validate_video_resolution 解析。"""
    UnifiedConfigRegistry._implementations.clear()
    UnifiedConfigRegistry.register_implementation(
        ImplementationConfig(
            name=SUPPORTED_IMPL_NAME,
            display_name='测试视频实现',
            driver_class='TestDriver',
            supported_video_resolutions=[
                {'value': '480P', 'label': '480P', 'driver_value': '480p'},
                {'value': '720P', 'label': '720P', 'driver_value': '720p'},
                {'value': '1080P', 'label': '1080P', 'driver_value': '1080p'},
            ],
            default_video_resolution='720P',
        )
    )
    yield SUPPORTED_IMPL_NAME
    UnifiedConfigRegistry._implementations.clear()


# -----------------------------
# 单元测试：_resolve_video_resolution
# -----------------------------

def test_resolve_video_resolution_uses_preference(video_impl):
    from enterprise.tools.video_tools import _resolve_video_resolution

    assert _resolve_video_resolution({'resolution': '480P'}, None, video_impl) == '480P'


def test_resolve_video_resolution_empty_falls_back_to_impl_default(video_impl):
    from enterprise.tools.video_tools import _resolve_video_resolution

    # 无偏好时返回 impl 默认（与 server.py 端点 validate_video_resolution(None, impl) 一致）
    assert _resolve_video_resolution({}, None, video_impl) == '720P'


def test_resolve_video_resolution_auto_falls_back_to_impl_default(video_impl):
    from enterprise.tools.video_tools import _resolve_video_resolution

    assert _resolve_video_resolution({'resolution': 'auto'}, None, video_impl) == '720P'


def test_resolve_video_resolution_invalid_falls_back(video_impl):
    from enterprise.tools.video_tools import _resolve_video_resolution

    # 模型不支持的值降级到 impl 默认
    assert _resolve_video_resolution({'resolution': '4K'}, None, video_impl) == '720P'


def test_resolve_video_resolution_unsupported_impl_returns_none():
    # impl 不支持分辨率选择时返回 None（端点与工具都不应下发 resolution）
    UnifiedConfigRegistry._implementations.clear()
    UnifiedConfigRegistry.register_implementation(
        ImplementationConfig(name='plain_impl', display_name='普通实现', driver_class='PlainDriver')
    )
    from enterprise.tools.video_tools import _resolve_video_resolution

    assert _resolve_video_resolution({'resolution': '1080P'}, None, 'plain_impl') is None
    UnifiedConfigRegistry._implementations.clear()


# -----------------------------
# 集成测试：generate_text_to_video / image_to_video 透传 resolution
# -----------------------------

@pytest.fixture
def patched_video_flow(monkeypatch, video_impl):
    """补齐 video_tools 视频生成的所有外部依赖，捕获 httpx.post 的请求体。"""
    # 显式先导入 mcp_tool，避免 monkeypatch 字符串路径触发重新导入时
    # model/database 在 config 缓存就绪前被加载。
    from script_writer_core import mcp_tool
    from enterprise.tools import video_tools

    captured = {
        'prefs': {'resolution': '480P'},   # 测试可改写
        'request_data': None,
        'api_url': None,
    }
    stub_config = _StubConfig()

    monkeypatch.setattr(
        'config.config_util.get_config',
        lambda: {'server': {'comfyui_base_url_inner': 'http://localhost:8000'}},
    )
    # _get_video_preferences 包装器读取 mcp_tool._get_video_preferences_func
    monkeypatch.setattr(
        'script_writer_core.mcp_tool._get_video_preferences_func',
        lambda uid, wid: captured['prefs'],
    )
    monkeypatch.setattr(video_tools, '_get_video_task_id', lambda *a, **k: 999)
    monkeypatch.setattr(
        'config.unified_config.UnifiedConfigRegistry.get_by_id',
        lambda tid: stub_config,
    )
    monkeypatch.setattr(
        'task.visual_drivers.driver_factory.VideoDriverFactory.get_implementation_for_user',
        lambda tid, uid: video_impl,
    )
    # image_to_video 的媒体 URL 校验放行
    monkeypatch.setattr(video_tools, '_validate_real_media_urls', lambda *a, **k: None)

    class _FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {'project_ids': ['p1']}

    def fake_post(url, data=None, **kwargs):
        captured['request_data'] = dict(data or {})
        captured['api_url'] = url
        return _FakeResp()

    monkeypatch.setattr(video_tools.httpx, 'post', fake_post)

    captured['stub_config'] = stub_config
    return captured


def test_generate_text_to_video_forwards_user_resolution(patched_video_flow):
    from enterprise.tools.video_tools import generate_text_to_video

    captured = patched_video_flow
    captured['prefs'] = {'resolution': '480P'}

    result = generate_text_to_video(user_id='u1', world_id='w1', auth_token='t', prompt='a cat', task_type=999)

    assert result['success'] is True
    # 核心：用户选择的 480P 必须透传到 /api/ai-app-run 请求体
    assert captured['request_data']['resolution'] == '480P'
    assert captured['api_url'].endswith('/api/ai-app-run')
    # 算力 context 也应纳入 resolution
    assert captured['stub_config'].last_power_context == {'resolution': '480P'}


def test_generate_text_to_video_uses_impl_default_when_no_pref(patched_video_flow):
    from enterprise.tools.video_tools import generate_text_to_video

    captured = patched_video_flow
    captured['prefs'] = {}

    result = generate_text_to_video(user_id='u1', world_id='w1', auth_token='t', prompt='a cat', task_type=999)

    assert result['success'] is True
    # 无偏好时下发 impl 默认 720P（与端点默认一致，保证算力估算与扣费对齐）
    assert captured['request_data']['resolution'] == '720P'
    assert captured['stub_config'].last_power_context == {'resolution': '720P'}


def test_generate_text_to_video_downgrades_invalid_resolution(patched_video_flow):
    from enterprise.tools.video_tools import generate_text_to_video

    captured = patched_video_flow
    captured['prefs'] = {'resolution': '4K'}  # 模型不支持

    result = generate_text_to_video(user_id='u1', world_id='w1', auth_token='t', prompt='a cat', task_type=999)

    assert result['success'] is True
    assert captured['request_data']['resolution'] == '720P'


def test_image_to_video_forwards_resolution(patched_video_flow):
    from enterprise.tools.video_tools import image_to_video

    captured = patched_video_flow
    captured['prefs'] = {'resolution': '1080P'}

    result = image_to_video(
        user_id='u1',
        world_id='w1',
        auth_token='t',
        prompt='run',
        image_urls='http://example.com/a.jpg',
        task_type=999,
    )

    assert result['success'] is True
    assert captured['request_data']['resolution'] == '1080P'
    assert captured['api_url'].endswith('/api/ai-app-run-image')
    assert captured['stub_config'].last_power_context == {'resolution': '1080P'}
