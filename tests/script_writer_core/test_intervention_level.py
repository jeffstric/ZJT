"""AI 介入程度（intervention_level）单元测试。

覆盖：
- 常量定义：合法档位集合、默认档、指令注入表（balanced 不注入）
- TaskManager.create_task / AgentTask：intervention_level 传递与默认值
- API 层校验语义：非法值回落 balanced（通过常量集合模拟 create_agent_task 内联校验）
"""
from script_writer_core.agents.task_manager import AgentTask, TaskManager


def test_valid_intervention_levels_content():
    from config.constant import (
        VALID_INTERVENTION_LEVELS, INTERVENTION_LEVEL_DEFAULT, INTERVENTION_LEVEL_BALANCED,
    )
    assert VALID_INTERVENTION_LEVELS == {"balanced", "concise", "detailed"}
    assert INTERVENTION_LEVEL_DEFAULT == INTERVENTION_LEVEL_BALANCED == "balanced"


def test_instructions_only_for_non_default_levels():
    from config.constant import INTERVENTION_LEVEL_INSTRUCTIONS
    assert set(INTERVENTION_LEVEL_INSTRUCTIONS.keys()) == {"concise", "detailed"}
    # 指令须以系统指令标记开头且非空，随 user 消息注入
    for level, instruction in INTERVENTION_LEVEL_INSTRUCTIONS.items():
        assert instruction.strip(), f"{level} 指令不能为空"
        assert "[系统指令·AI介入程度" in instruction


def test_concise_instruction_targets_ask_user_reduction():
    from config.constant import INTERVENTION_LEVEL_INSTRUCTIONS
    assert "不使用 ask_user" in INTERVENTION_LEVEL_INSTRUCTIONS["concise"]


def test_concise_instruction_exempts_requirement_collection():
    """简洁档必须豁免需求收集项（题材/集数/时长/画风），不得跳过这些必答提问。"""
    from config.constant import INTERVENTION_LEVEL_INSTRUCTIONS
    instruction = INTERVENTION_LEVEL_INSTRUCTIONS["concise"]
    assert "需求收集" in instruction
    assert "集数" in instruction
    assert "画风" in instruction
    assert "仍须使用 ask_user" in instruction


def test_detailed_instruction_restores_confirmation_flow():
    from config.constant import INTERVENTION_LEVEL_INSTRUCTIONS
    instruction = INTERVENTION_LEVEL_INSTRUCTIONS["detailed"]
    assert "ask_user" in instruction
    assert "character-image-designer" in instruction
    assert "location-prop-image-designer" in instruction


def _normalize_level(raw):
    """复刻 api/script_writer.create_agent_task 的内联校验语义。"""
    from config.constant import VALID_INTERVENTION_LEVELS, INTERVENTION_LEVEL_DEFAULT
    level = raw
    if level not in VALID_INTERVENTION_LEVELS:
        level = INTERVENTION_LEVEL_DEFAULT
    return level


def test_normalize_level_accepts_valid_values():
    assert _normalize_level("balanced") == "balanced"
    assert _normalize_level("concise") == "concise"
    assert _normalize_level("detailed") == "detailed"


def test_normalize_level_rejects_dirty_values():
    for bad in (None, "", "Balanced", "aggressive", "balanced ", 1):
        assert _normalize_level(bad) == "balanced"


def test_injection_prefix_applies_only_when_instruction_present():
    """API 层拼接语义：仅非 balanced 档把指令前缀拼入 user_message。"""
    from config.constant import INTERVENTION_LEVEL_INSTRUCTIONS

    def build_user_message(raw, original):
        instruction = INTERVENTION_LEVEL_INSTRUCTIONS.get(_normalize_level(raw), "")
        return instruction + original if instruction else original

    assert build_user_message("balanced", "写个剧本") == "写个剧本"
    assert build_user_message("concise", "写个剧本").endswith("写个剧本")
    assert build_user_message("concise", "写个剧本").startswith("\n\n[系统指令·AI介入程度")
    assert build_user_message("bogus", "写个剧本") == "写个剧本"


def test_agent_task_defaults_to_balanced():
    task = AgentTask(
        task_id="t1", session_id="s1", user_message="msg",
        user_id="1", world_id="101", auth_token="token",
        vendor_id=1, model_id=11,
    )
    assert task.intervention_level == "balanced"
    assert task.to_dict()["intervention_level"] == "balanced"


def test_task_manager_create_task_forwards_intervention_level(monkeypatch):
    from script_writer_core.agents import task_manager as tm_module

    # 单测无数据库：拦截持久化，仅验证内存任务对象的字段传递
    monkeypatch.setattr(tm_module.AgentTasksModel, "create", lambda **kwargs: None)

    manager = TaskManager()
    manager.create_task(
        session_id="s1", user_message="msg", user_id="1", world_id="101",
        auth_token="token", vendor_id=1, model_id=11,
        intervention_level="detailed",
    )
    task = list(manager.tasks.values())[0]
    assert task.intervention_level == "detailed"

    manager.create_task(
        session_id="s2", user_message="msg", user_id="1", world_id="101",
        auth_token="token", vendor_id=1, model_id=11,
    )
    assert list(manager.tasks.values())[1].intervention_level == "balanced"
