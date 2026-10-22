"""VideoWorkflowModel.list_by_user 的查看范围过滤。"""
from unittest.mock import patch

from model.video_workflow import VideoWorkflowModel


def _where(sql):
    upper = sql.upper()
    index = upper.find("WHERE")
    return sql[index:] if index >= 0 else sql


def _fake_execute(sql, params=None, fetch_one=False, fetch_all=False):
    if fetch_one:
        return {"total": 0}
    return []


def _wheres(fake):
    return [(_where(call.args[0]), call.args[1]) for call in fake.call_args_list]


def test_isolated_default_filters_current_user():
    with patch("model.video_workflow.Edition.is_space_isolated", return_value=True), \
         patch("model.video_workflow.execute_query", side_effect=_fake_execute) as fake:
        result = VideoWorkflowModel.list_by_user(14)
    wheres = _wheres(fake)
    assert wheres
    assert all("user_id = %s" in clause for clause, _params in wheres)
    assert wheres[0][1][0] == 14
    assert result["total"] == 0


def test_include_all_users_skips_user_filter_when_isolated():
    with patch("model.video_workflow.Edition.is_space_isolated", return_value=True), \
         patch("model.video_workflow.execute_query", side_effect=_fake_execute) as fake:
        VideoWorkflowModel.list_by_user(14, include_all_users=True)
    for clause, _params in _wheres(fake):
        assert "user_id = %s" not in clause
        assert "user_id IN" not in clause


def test_owner_user_ids_uses_in_clause():
    with patch("model.video_workflow.Edition.is_space_isolated", return_value=True), \
         patch("model.video_workflow.execute_query", side_effect=_fake_execute) as fake:
        VideoWorkflowModel.list_by_user(1, owner_user_ids=[14, "33", 14, "x"])
    clause, params = _wheres(fake)[0]
    assert "user_id IN (%s,%s)" in clause
    assert params[:2] == (14, 33)


def test_empty_owner_user_ids_returns_empty_without_query():
    with patch("model.video_workflow.execute_query") as fake:
        result = VideoWorkflowModel.list_by_user(14, owner_user_ids=[])
    fake.assert_not_called()
    assert result == {"total": 0, "page": 1, "page_size": 10, "data": []}


def test_shared_space_default_has_no_user_filter():
    with patch("model.video_workflow.Edition.is_space_isolated", return_value=False), \
         patch("model.video_workflow.execute_query", side_effect=_fake_execute) as fake:
        VideoWorkflowModel.list_by_user(14)
    for clause, _params in _wheres(fake):
        assert "user_id = %s" not in clause
        assert "user_id IN" not in clause
