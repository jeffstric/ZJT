"""[视频模型时长能力] 注入行构建测试。

智能体上下文注入（api/script_writer.py build_video_duration_capabilities）：
按当前用户可用实现方动态过滤 enabled 视频模型，输出 `id=名称(最长Ns)` 列表，
供 LLM 决定 clip 时长/分段数（拉长优先策略的能力依据）。
"""
from types import SimpleNamespace

import pytest


class _Cfg(SimpleNamespace):
    pass


def _make_cfg(tid, name, durations, *, enabled=True, hidden=False, variant=""):
    return _Cfg(id=tid, name=name, variant_label=variant, enabled=enabled,
                hidden=hidden, supported_durations=durations)


_CATALOG = [
    _make_cfg(22, "Seedance 2.0 Fast", [5, 10, 15]),
    _make_cfg(36, "Seedance 2.5", [5, 6, 30]),
    _make_cfg(37, "MiniMax H3 参考生视频", [4, 10], variant="多参考"),
    _make_cfg(50, "已禁用模型", [5, 20], enabled=False),
    _make_cfg(51, "已隐藏模型", [5, 20], hidden=True),
    _make_cfg(52, "无时长模型", None),
]


@pytest.fixture
def registry_env(monkeypatch):
    """mock Registry 视频类目与实现方可用性探测。"""
    from config.unified_config import TaskCategory
    from api import script_writer

    available = {22, 36, 37}  # 测试可改写

    monkeypatch.setattr(
        script_writer, 'UnifiedConfigRegistry', None, raising=False)

    import config.unified_config as uc

    monkeypatch.setattr(
        uc.UnifiedConfigRegistry, 'get_by_category',
        classmethod(lambda cls, category: _CATALOG),
    )
    monkeypatch.setattr(
        "task.visual_drivers.driver_factory.VideoDriverFactory.get_implementation_for_user",
        lambda tid, uid: 'impl' if int(tid) in available else None,
    )
    return available


def test_lists_available_models_with_max_duration(registry_env):
    from api.script_writer import build_video_duration_capabilities

    line = build_video_duration_capabilities('55')

    assert '36=Seedance 2.5(最长30s)' in line
    assert '22=Seedance 2.0 Fast(最长15s)' in line
    assert '37=MiniMax H3 参考生视频(多参考)(最长10s)' in line
    # 禁用/隐藏/无时长/无实现方 的模型不出现（50/51/52 不在 available 集合外还各有拦截）
    assert '50=' not in line and '51=' not in line and '52=' not in line


def test_excludes_models_without_implementation(registry_env):
    from api.script_writer import build_video_duration_capabilities

    registry_env.discard(36)

    line = build_video_duration_capabilities('55')

    assert '36=' not in line
    assert '22=' in line


def test_empty_when_nothing_available(registry_env):
    from api.script_writer import build_video_duration_capabilities

    registry_env.clear()

    assert build_video_duration_capabilities('55') == ''


def test_cached_line_hits_build_once(monkeypatch, registry_env):
    """60s TTL 缓存：同一用户连续两次取行走缓存，构建函数只执行一次。"""
    from api import script_writer

    calls = {'n': 0}
    real_build = script_writer.build_video_duration_capabilities

    def counting_build(user_id):
        calls['n'] += 1
        return real_build(user_id)

    monkeypatch.setattr(script_writer, 'build_video_duration_capabilities', counting_build)
    monkeypatch.setattr(script_writer, '_video_duration_caps_cache', {})

    first = script_writer.get_video_duration_capabilities_line('77')
    second = script_writer.get_video_duration_capabilities_line('77')

    assert calls['n'] == 1
    assert first == second and '36=Seedance 2.5(最长30s)' in first
