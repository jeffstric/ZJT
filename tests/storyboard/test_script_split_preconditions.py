"""剧本拆分前置校验单元测试（889bd923a）。

覆盖 api/script_split.py 的创建前拦截：
- _validate_script_content_precondition：正文 < 20 字（含空串）→
  script_content_insufficient，不查库、不调 LLM
- _validate_world_scene_precondition：world 无场景 → world_no_scene；
  有场景全无参考图 → world_no_scene_image；world_id 缺失/非数字跳过
- create_split_task：前置校验失败时不得触达任务创建（create_or_get_active
  不被调用）——重试也无法改变结论的输入在创建前拒绝

说明：这些校验在端点流程中位于算力检查（外部 perseids 平台调用）之后，
e2e 容器内外部平台认证不可用时永远到不了该分支，故以单元测试守护
（此前曾误放在 auto_test/e2e/test_script_split.py，CI 必失败，已移除）。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api.script_split import (
    ScriptSplitPreconditionError,
    _validate_script_content_precondition,
    _validate_world_scene_precondition,
    create_split_task,
)
from config.constant import ScriptSplitConstants


MIN_CHARS = ScriptSplitConstants.MIN_SCRIPT_SPLIT_CHARS


# ==================== 剧本正文长度 ====================

def test_short_script_rejected_with_code():
    with pytest.raises(ScriptSplitPreconditionError) as exc_info:
        _validate_script_content_precondition("太短了")
    assert exc_info.value.code == "script_content_insufficient"
    assert "剧本内容信息不足" in exc_info.value.message
    assert "3" in exc_info.value.message  # 报出实际字数


def test_script_at_boundary_length_accepted():
    # 恰好达到阈值通过（>= 语义）
    _validate_script_content_precondition("字" * MIN_CHARS)


def test_script_one_char_below_rejected():
    with pytest.raises(ScriptSplitPreconditionError):
        _validate_script_content_precondition("字" * (MIN_CHARS - 1))


def test_empty_and_none_script_rejected():
    with pytest.raises(ScriptSplitPreconditionError):
        _validate_script_content_precondition("")
    with pytest.raises(ScriptSplitPreconditionError):
        _validate_script_content_precondition(None)
    with pytest.raises(ScriptSplitPreconditionError):
        _validate_script_content_precondition("   \n  ")


# ==================== world 场景资产 ====================

def _patch_location_counts(monkeypatch, total, with_image):
    from model.location import LocationModel
    monkeypatch.setattr(
        LocationModel, "count_by_world",
        staticmethod(lambda world_id: total))
    monkeypatch.setattr(
        LocationModel, "count_with_image_by_world",
        staticmethod(lambda world_id: with_image))


def test_world_without_scene_rejected(monkeypatch):
    _patch_location_counts(monkeypatch, total=0, with_image=0)
    with pytest.raises(ScriptSplitPreconditionError) as exc_info:
        asyncio.run(_validate_world_scene_precondition(10))
    assert exc_info.value.code == "world_no_scene"
    assert "场景" in exc_info.value.message


def test_world_scenes_without_image_rejected(monkeypatch):
    _patch_location_counts(monkeypatch, total=3, with_image=0)
    with pytest.raises(ScriptSplitPreconditionError) as exc_info:
        asyncio.run(_validate_world_scene_precondition(10))
    assert exc_info.value.code == "world_no_scene_image"
    assert "参考图" in exc_info.value.message


def test_world_with_scene_image_passes(monkeypatch):
    _patch_location_counts(monkeypatch, total=2, with_image=1)
    asyncio.run(_validate_world_scene_precondition(10))  # 不抛即通过


def test_world_id_missing_skips_validation(monkeypatch):
    """world_id 缺失（cli 来源）时跳过，保持向后兼容。"""
    _patch_location_counts(monkeypatch, total=0, with_image=0)
    asyncio.run(_validate_world_scene_precondition(None))
    asyncio.run(_validate_world_scene_precondition(""))


def test_world_id_non_numeric_skips_validation(monkeypatch):
    _patch_location_counts(monkeypatch, total=0, with_image=0)
    asyncio.run(_validate_world_scene_precondition("not-a-number"))


# ==================== create_split_task 创建前拦截 ====================

def _patch_create_chain(monkeypatch):
    """mock 掉 create_split_task 在前置校验之后的全部依赖。"""
    monkeypatch.setattr(
        "api.script_split.build_character_contract_snapshot",
        lambda world_id: {"characters": []}, raising=False)
    model = MagicMock()
    model.create_or_get_active.return_value = (501, True)
    monkeypatch.setattr("api.script_split.ScriptSplitTaskModel", model)
    return model


def test_create_split_task_rejects_short_script_before_task_creation(monkeypatch):
    """短剧本在任务创建前被拒：不落库、不建快照。"""
    model = _patch_create_chain(monkeypatch)
    with pytest.raises(ScriptSplitPreconditionError) as exc_info:
        asyncio.run(create_split_task(
            user_id=7, source_type="script_writer", source_id=None,
            source_node_key=None, script_content="太短",
            request_config={"world_id": None},
        ))
    assert exc_info.value.code == "script_content_insufficient"
    model.create_or_get_active.assert_not_called()


def test_create_split_task_rejects_world_without_scene_before_creation(monkeypatch):
    _patch_location_counts(monkeypatch, total=0, with_image=0)
    model = _patch_create_chain(monkeypatch)
    with pytest.raises(ScriptSplitPreconditionError) as exc_info:
        asyncio.run(create_split_task(
            user_id=7, source_type="script_writer", source_id=None,
            source_node_key=None, script_content="足够长的剧本内容，" * 10,
            request_config={"world_id": 10},
        ))
    assert exc_info.value.code == "world_no_scene"
    model.create_or_get_active.assert_not_called()


def test_create_split_task_passes_preconditions_to_creation(monkeypatch):
    """前置校验通过 → 正常走到 create_or_get_active。"""
    _patch_location_counts(monkeypatch, total=1, with_image=1)
    model = _patch_create_chain(monkeypatch)

    import api.script_split as sp
    # to_thread 同步执行，隔离 DB
    import asyncio as _asyncio_mod
    async def _fake(fn, *a, **kw):
        return fn(*a, **kw)
    monkeypatch.setattr(_asyncio_mod, "to_thread", _fake)

    task_id, is_new = asyncio.run(create_split_task(
        user_id=7, source_type="script_writer", source_id=None,
        source_node_key=None, script_content="足够长的剧本内容，" * 10,
        request_config={"world_id": 10},
    ))
    assert (task_id, is_new) == (501, True)
    model.create_or_get_active.assert_called_once()
    # 角色契约快照在幂等键计算之后注入 request_config（args 顺序：
    # user_id, source_type, source_id, source_node_key, active_key,
    # script_sha256, script_content, request_config, auth_token）
    config_arg = model.create_or_get_active.call_args.args[7]
    assert sp.CHARACTER_CONTRACT_CONFIG_KEY in config_arg
