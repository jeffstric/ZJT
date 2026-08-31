"""VL 模型偏好单元测试。

覆盖：
- api 层 get_vl_model_preference / set_vl_model_preference 的存取与回落逻辑
- PM Agent use_config_model 专家的 VL 模型选择与路由解析
  （_get_vl_model_for_expert / _resolve_model_routing / _handle_agent_call 分支）
"""
from unittest.mock import MagicMock, patch

from script_writer_core.agents.pm_agent import PMAgent
from script_writer_core.agents.task_manager import AgentTask

VL_PREF_TYPE = "vl_model"


def _make_pref(value):
    pref = MagicMock()
    pref.config_value = value
    pref.get_value.return_value = value
    return pref


# ---------- api 层偏好读写 ----------

def test_get_vl_model_preference_returns_saved_dict(monkeypatch):
    from api import script_writer as sw

    saved = {"model": "deepseek-v4-flash-vision-exp", "model_id": 9, "vendor_id": 4}
    monkeypatch.setattr(
        sw.UserPreferencesModel, "get",
        lambda user_id, world_id, pref_type: _make_pref(saved),
    )
    assert sw.get_vl_model_preference("1", "101") == saved


def test_get_vl_model_preference_returns_none_when_absent(monkeypatch):
    from api import script_writer as sw

    monkeypatch.setattr(
        sw.UserPreferencesModel, "get", lambda *a: None
    )
    assert sw.get_vl_model_preference("1", "101") is None


def test_get_vl_model_preference_ignores_invalid_values(monkeypatch):
    from api import script_writer as sw

    for bad in (None, "deepseek-v4-flash-vision-exp", {}, {"model": ""}):
        monkeypatch.setattr(
            sw.UserPreferencesModel, "get",
            lambda *a, bad=bad: _make_pref(bad),
        )
        assert sw.get_vl_model_preference("1", "101") is None


def test_set_vl_model_preference_upserts_normalized_payload(monkeypatch):
    from api import script_writer as sw

    writes = []
    monkeypatch.setattr(
        sw.UserPreferencesModel, "upsert",
        lambda user_id, world_id, pref_type, value: writes.append(
            (user_id, world_id, pref_type, value)
        ),
    )
    ok = sw.set_vl_model_preference(
        "1", "101", "deepseek-v4-flash-vision-exp", model_id=9, vendor_id=4
    )
    assert ok is True
    assert writes == [(
        "1", "101", VL_PREF_TYPE,
        {"model": "deepseek-v4-flash-vision-exp", "model_id": 9, "vendor_id": 4},
    )]


def test_set_vl_model_preference_rejects_empty_model(monkeypatch):
    from api import script_writer as sw

    def _fail(*a, **k):
        raise AssertionError("upsert 不应被调用")

    monkeypatch.setattr(sw.UserPreferencesModel, "upsert", _fail)
    assert sw.set_vl_model_preference("1", "101", "") is False


# ---------- PM Agent VL 模型选择与路由 ----------

def _create_pm_agent(task_manager, expert_model="deepseek-v4-flash-vision-exp",
                     use_config_model=True):
    file_manager = MagicMock()
    file_manager.get_context_for_ai.return_value = ""
    return PMAgent(
        model="user-session-model",
        allowed_tools=["call_agent"],
        task_manager=task_manager,
        file_manager=file_manager,
        tool_executor=MagicMock(),
        agents_config={
            "pm_agent": {"skills": []},
            "expert_agents": {
                "asset-readiness-checker": {
                    "skills": [],
                    "allowed_tools": [],
                    "model": expert_model,
                    "use_config_model": use_config_model,
                }
            },
        },
        user_id="1",
        world_id="101",
        auth_token="token",
        base_prompt="test prompt",
        skip_env_context=True,
    )


def _make_task():
    return AgentTask(
        task_id="task-1",
        session_id="session-1",
        user_message="check assets",
        user_id="1",
        world_id="101",
        auth_token="token",
        vendor_id=1,
        model_id=11,
    )


def test_get_vl_model_for_expert_prefers_user_preference():
    agent = _create_pm_agent(task_manager=MagicMock())
    task = _make_task()
    with patch("model.user_preferences.UserPreferencesModel.get") as mock_get:
        mock_get.return_value = _make_pref(
            {"model": "user-vl-model", "model_id": 5, "vendor_id": 2}
        )
        assert agent._get_vl_model_for_expert(
            {"model": "config-vl-model"}, task
        ) == "user-vl-model"


def test_get_vl_model_for_expert_falls_back_to_config():
    agent = _create_pm_agent(task_manager=MagicMock())
    task = _make_task()
    with patch("model.user_preferences.UserPreferencesModel.get", return_value=None):
        assert agent._get_vl_model_for_expert(
            {"model": "config-vl-model"}, task
        ) == "config-vl-model"


def test_get_vl_model_for_expert_falls_back_on_db_error():
    agent = _create_pm_agent(task_manager=MagicMock())
    task = _make_task()
    with patch("model.user_preferences.UserPreferencesModel.get",
               side_effect=RuntimeError("db down")):
        assert agent._get_vl_model_for_expert(
            {"model": "config-vl-model"}, task
        ) == "config-vl-model"


def _mock_model_entity(model_id=9):
    entity = MagicMock()
    entity.id = model_id
    return entity


def test_resolve_model_routing_resolves_vendor_and_model_id():
    agent = _create_pm_agent(task_manager=MagicMock())
    with patch("model.model.ModelModel.get_by_name") as mock_by_name, \
         patch("model.vendor_model.VendorModelModel.get_vendor_id_by_model_id") as mock_vendor:
        mock_by_name.return_value = _mock_model_entity(9)
        mock_vendor.return_value = 4
        vendor_id, model_id = agent._resolve_model_routing("vl-model", 1, 11)
    assert (vendor_id, model_id) == (4, 9)


def test_resolve_model_routing_unknown_model_keeps_fallback_vendor():
    agent = _create_pm_agent(task_manager=MagicMock())
    with patch("model.model.ModelModel.get_by_name", return_value=None):
        vendor_id, model_id = agent._resolve_model_routing("vl-model", 1, 11)
    assert (vendor_id, model_id) == (1, None)


def test_resolve_model_routing_vendor_query_failure_uses_fallback_vendor():
    agent = _create_pm_agent(task_manager=MagicMock())
    with patch("model.model.ModelModel.get_by_name") as mock_by_name, \
         patch("model.vendor_model.VendorModelModel.get_vendor_id_by_model_id",
               side_effect=RuntimeError("vendor db down")):
        mock_by_name.return_value = _mock_model_entity(9)
        vendor_id, model_id = agent._resolve_model_routing("vl-model", 1, 11)
    assert (vendor_id, model_id) == (1, 9)


def test_handle_agent_call_uses_resolved_vl_model_for_config_model_expert():
    """use_config_model 专家：偏好 VL 模型可解析时，ExpertAgent 使用解析出的路由。"""
    task_manager = MagicMock()
    agent = _create_pm_agent(task_manager)
    task = _make_task()

    with patch("model.user_preferences.UserPreferencesModel.get") as mock_pref, \
         patch("model.model.ModelModel.get_by_name") as mock_by_name, \
         patch("model.vendor_model.VendorModelModel.get_vendor_id_by_model_id") as mock_vendor, \
         patch("script_writer_core.agents.pm_agent.ExpertAgent") as expert_cls:
        mock_pref.return_value = _make_pref({"model": "deepseek-v4-flash-vision-exp"})
        mock_by_name.return_value = _mock_model_entity(9)
        mock_vendor.return_value = 4
        expert_cls.return_value.execute_task.return_value = {
            "success": True, "result": "ok", "project_ids": [],
        }
        agent._handle_agent_call(
            {"AgentName": "asset-readiness-checker", "task_description": "check"},
            task, {},
        )

    kwargs = expert_cls.call_args.kwargs
    assert kwargs["vendor_id"] == 4
    assert kwargs["model_id"] == 9


def test_handle_agent_call_falls_back_to_session_model_when_vl_missing_in_db():
    """偏好与默认 VL 模型均未入库：回退用户会话模型路由。"""
    task_manager = MagicMock()
    agent = _create_pm_agent(task_manager)
    task = _make_task()

    with patch("model.user_preferences.UserPreferencesModel.get", return_value=None), \
         patch("model.model.ModelModel.get_by_name", return_value=None), \
         patch("script_writer_core.agents.pm_agent.ExpertAgent") as expert_cls:
        expert_cls.return_value.execute_task.return_value = {
            "success": True, "result": "ok", "project_ids": [],
        }
        agent._handle_agent_call(
            {"AgentName": "asset-readiness-checker", "task_description": "check"},
            task, {},
        )

    kwargs = expert_cls.call_args.kwargs
    assert kwargs["vendor_id"] == task.vendor_id
    assert kwargs["model_id"] == task.model_id
