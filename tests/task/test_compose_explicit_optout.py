"""数字人成片明水印：只看用户设置和各段 ai_tools.id，不拿 compose_jobs.id 撞号。"""
from types import SimpleNamespace

from task import compose_task


def test_compose_opt_out_uses_segment_ids_not_compose_id(monkeypatch):
    seen = []

    def has_user(user_id):
        seen.append(("user", user_id))
        return False

    def has_tool(ai_tool_id):
        seen.append(("tool", ai_tool_id))
        return ai_tool_id == 202

    monkeypatch.setattr(compose_task.AigcExplicitOptOutModel, "has_opt_out_user", has_user)
    monkeypatch.setattr(compose_task.AigcExplicitOptOutModel, "has_opt_out", has_tool)
    job = SimpleNamespace(id=999, user_id=3, segment_ai_tool_ids=[201, "202", "bad", 0])

    assert compose_task.compose_explicit_label_opted_out(job) is True
    assert ("tool", 999) not in seen
    assert ("tool", 201) in seen
    assert ("tool", 202) in seen
    assert ("tool", 0) not in seen


def test_compose_opt_out_empty_segments_only_checks_user(monkeypatch):
    seen = []

    def has_user(user_id):
        seen.append(("user", user_id))
        return True

    def has_tool(ai_tool_id):
        seen.append(("tool", ai_tool_id))
        return True

    monkeypatch.setattr(compose_task.AigcExplicitOptOutModel, "has_opt_out_user", has_user)
    monkeypatch.setattr(compose_task.AigcExplicitOptOutModel, "has_opt_out", has_tool)
    job = SimpleNamespace(id=7, user_id=3, segment_ai_tool_ids=[])

    assert compose_task.compose_explicit_label_opted_out(job) is True
    assert seen == [("user", 3)]


def test_compose_opt_out_false_when_neither_user_nor_segment(monkeypatch):
    seen = []
    monkeypatch.setattr(
        compose_task.AigcExplicitOptOutModel, "has_opt_out_user", lambda user_id: False,
    )
    monkeypatch.setattr(
        compose_task.AigcExplicitOptOutModel,
        "has_opt_out",
        lambda ai_tool_id: seen.append(ai_tool_id) or False,
    )
    job = SimpleNamespace(id=7, user_id=3, segment_ai_tool_ids=[101])

    assert compose_task.compose_explicit_label_opted_out(job) is False
    assert 7 not in seen
    assert seen == [101]
