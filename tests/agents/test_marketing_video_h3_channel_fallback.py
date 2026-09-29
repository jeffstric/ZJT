"""
图文转视频 MiniMax H3 通道适配测试（2026-09-29 会话 09a5cb93 事故回归）

背景：H3 按输入形态拆成三个独立任务条目（34=首尾帧、37=参考生，均仅图生；
45=文生）。营销包装工具白名单曾只收录 34/37，LLM 按用户"用 MiniMax H3"传入
37 且未带参考图时，走文生通道撞 category 校验，被底层防降级防线误报
"指定视频模型(task_type=37)不可用，已阻止降级到其他模型"，诱导用户换模型。

本文件验证包装层的同族通道适配：
  - 34/37 无参考图 → 自动落到文生版 45 走 generate_text_to_video；
  - 45 不可用时给出"仅支持参考图输入"的明确错误（而非误导性"不可用"）；
  - 45 带参考图 → 自动落到参考生 37 走 image_to_video（对称防线）；
  - 37 不可用时丢弃参考图走文生，保证同族内部适配永不因 force 锁定而失败；
  - 白名单/偏好序/目录提示收录 45；_availability_hint 按真实调用方探测。
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

from config.unified_config import TaskCategory  # noqa: E402


class _StubCfg:
    """模拟 UnifiedConfigRegistry.get_by_id 返回的任务配置。"""

    def __init__(self, tid, name, category, categories=None):
        self.id = tid
        self.name = name
        self.category = category
        self.categories = categories or []
        self.enabled = True
        self.hidden = False
        # H3 全系与 Seedance 2.0 系均覆盖 6s
        self.supported_durations = [4, 5, 6, 7, 8, 9, 10]


# 与 config/unified_config.py 中的真实条目主类保持一致
_CATALOG = {
    22: _StubCfg(22, "Seedance 2.0 Fast", TaskCategory.IMAGE_TO_VIDEO, [TaskCategory.TEXT_TO_VIDEO]),
    23: _StubCfg(23, "Seedance 2.0", TaskCategory.IMAGE_TO_VIDEO, [TaskCategory.TEXT_TO_VIDEO]),
    31: _StubCfg(31, "Seedance 2.0 Mini", TaskCategory.IMAGE_TO_VIDEO, [TaskCategory.TEXT_TO_VIDEO]),
    36: _StubCfg(36, "Seedance 2.5", TaskCategory.IMAGE_TO_VIDEO, [TaskCategory.TEXT_TO_VIDEO]),
    34: _StubCfg(34, "MiniMax H3 首尾帧", TaskCategory.IMAGE_TO_VIDEO),
    37: _StubCfg(37, "MiniMax H3 参考生视频", TaskCategory.IMAGE_TO_VIDEO),
    45: _StubCfg(45, "MiniMax H3 (文生)", TaskCategory.TEXT_TO_VIDEO),
}


@pytest.fixture
def marketing_flow(monkeypatch):
    """补齐 generate_marketing_video 的外部依赖，捕获底层提交调用。"""
    from enterprise.tools import marketing_video_tools, video_tools
    from enterprise.tools import content_tools
    import enterprise.services.license.runtime as license_runtime_module

    captured = {
        'text_calls': [],      # generate_text_to_video 收到的 kwargs
        'image_calls': [],     # image_to_video 收到的 kwargs
        'impl_uids': [],       # get_implementation_for_user 收到的 (task_id, uid)
        'available': set(range(22, 46)),  # 可用实现方集合（测试可改写）
    }

    monkeypatch.setattr(license_runtime_module, 'require_commercial_license', lambda *a, **k: None)
    monkeypatch.setattr(content_tools, 'enterprise_edition_gate_error', lambda: None)
    # 用户偏好走空（显式传 task_type 的用例不依赖偏好；白名单外探测同理）
    monkeypatch.setattr(
        'script_writer_core.mcp_tool._get_video_preferences', lambda uid, wid: {}
    )
    monkeypatch.setattr(
        'config.unified_config.UnifiedConfigRegistry.get_by_id',
        lambda tid: _CATALOG.get(tid),
    )

    def _impl_for_user(tid, uid):
        captured['impl_uids'].append((tid, str(uid)))
        return 'fake_impl' if int(tid) in captured['available'] else None

    monkeypatch.setattr(
        'task.visual_drivers.driver_factory.VideoDriverFactory.get_implementation_for_user',
        _impl_for_user,
    )
    # 参考图存在性校验放行（用例传的是假 /upload 路径）
    monkeypatch.setattr(marketing_video_tools, '_validate_image_urls', lambda urls: None)

    def fake_text_to_video(user_id, world_id, auth_token, **kwargs):
        captured['text_calls'].append(kwargs)
        return {'success': True, 'project_ids': [f't{len(captured["text_calls"])}']}

    def fake_image_to_video(user_id, world_id, auth_token, **kwargs):
        captured['image_calls'].append(kwargs)
        return {'success': True, 'project_ids': [f'i{len(captured["image_calls"])}']}

    monkeypatch.setattr(video_tools, 'generate_text_to_video', fake_text_to_video)
    monkeypatch.setattr(video_tools, 'image_to_video', fake_image_to_video)

    return captured


def _call(captured, **kwargs):
    from enterprise.tools.marketing_video_tools import generate_marketing_video

    base = dict(user_id='55', world_id='1', auth_token='t', prompt='p', duration_seconds=6)
    base.update(kwargs)
    return generate_marketing_video(**base)


# -----------------------------
# 常量与校验入口
# -----------------------------

def test_whitelist_and_preference_include_h3_text_variant():
    from enterprise.tools.marketing_video_tools import (
        MARKETING_ARTICLE_ALLOWED_TASK_IDS,
        MARKETING_ARTICLE_TASK_ID_PREFERENCE,
        MODEL_CATALOG_HINT,
    )

    assert 45 in MARKETING_ARTICLE_ALLOWED_TASK_IDS
    assert 45 in MARKETING_ARTICLE_TASK_ID_PREFERENCE
    assert "45=minimax_h3文生" in MODEL_CATALOG_HINT


def test_validate_task_type_accepts_text_only_video_entry(marketing_flow):
    """45 主类是 TEXT_TO_VIDEO，不能被误判为"不是视频生成模型"。"""
    from enterprise.tools.marketing_video_tools import _validate_task_type

    assert _validate_task_type(45, user_id='55') is None
    assert _validate_task_type(37, user_id='55') is None


def test_availability_hint_probes_with_real_user_id(marketing_flow):
    """可用性探测必须用真实调用方 uid，而非历史遗留的硬编码 "1"。"""
    from enterprise.tools.marketing_video_tools import _availability_hint

    _availability_hint("前缀。", user_id='55')

    uids = {uid for _tid, uid in marketing_flow['impl_uids']}
    assert uids == {'55'}


# -----------------------------
# H3 图生条目（34/37）无参考图 → 落到文生版 45
# -----------------------------

def test_h3_reference_without_images_falls_back_to_text_variant(marketing_flow):
    """事故场景回归：37 + 无参考图必须走 45 的文生通道，而非撞 force 防线。"""
    result = _call(marketing_flow, task_type=37, image_urls=None)

    assert result['success'] is True
    assert len(marketing_flow['text_calls']) == 1
    assert marketing_flow['image_calls'] == []
    assert marketing_flow['text_calls'][0]['force_task_type'] == 45
    assert marketing_flow['text_calls'][0]['task_type'] == 45


def test_h3_first_last_frame_without_images_falls_back_to_text_variant(marketing_flow):
    result = _call(marketing_flow, task_type=34, image_urls=[])

    assert result['success'] is True
    assert marketing_flow['text_calls'][0]['force_task_type'] == 45


def test_h3_image_only_without_images_reports_clear_error_when_text_unavailable(marketing_flow):
    """45 不可用时报"仅支持参考图输入"的明确错误，不得再出现误导性"不可用，已阻止降级"。"""
    marketing_flow['available'].discard(45)

    result = _call(marketing_flow, task_type=37, image_urls=None)

    assert result['success'] is False
    assert "仅支持参考图输入" in result['error']
    assert "task_type=45" in result['error']
    assert "已阻止降级" not in result['error']


def test_h3_reference_with_images_keeps_reference_channel(marketing_flow):
    """带参考图时保持 37 参考生通道（multi_reference），行为不变。"""
    result = _call(marketing_flow, task_type=37, image_urls=['/upload/marketing_fetched/a.jpg'])

    assert result['success'] is True
    assert len(marketing_flow['image_calls']) == 1
    assert marketing_flow['text_calls'] == []
    assert marketing_flow['image_calls'][0]['force_task_type'] == 37
    assert marketing_flow['image_calls'][0]['image_mode'] == 'multi_reference'


# -----------------------------
# 对称防线：45 带参考图 → 落到参考生 37
# -----------------------------

def test_h3_text_with_images_falls_back_to_reference_variant(marketing_flow):
    """偏好跟随得到 45 而 LLM 带了参考图时，须落到 37 图生通道而非撞 force 防线。"""
    result = _call(marketing_flow, task_type=45, image_urls=['/upload/marketing_fetched/a.jpg'])

    assert result['success'] is True
    assert len(marketing_flow['image_calls']) == 1
    assert marketing_flow['text_calls'] == []
    assert marketing_flow['image_calls'][0]['force_task_type'] == 37


def test_h3_text_with_images_drops_images_when_reference_unavailable(marketing_flow):
    """37 不可用时丢弃参考图走 45 文生，保证同族适配不因 force 锁定而失败。"""
    marketing_flow['available'].discard(37)

    result = _call(marketing_flow, task_type=45, image_urls=['/upload/marketing_fetched/a.jpg'])

    assert result['success'] is True
    assert marketing_flow['image_calls'] == []
    assert marketing_flow['text_calls'][0]['force_task_type'] == 45
    assert marketing_flow['text_calls'][0].get('image_urls') in (None, '')


def test_h3_text_without_images_uses_text_channel_directly(marketing_flow):
    result = _call(marketing_flow, task_type=45, image_urls=None)

    assert result['success'] is True
    assert marketing_flow['text_calls'][0]['force_task_type'] == 45
    assert marketing_flow['image_calls'] == []
