"""VideoWorkflowModel.update 乐观锁（content_version）条件更新测试。

背景：PUT CAS 原由 check-then-act 实现，读哈希（to_thread，含 await 点）与
UPDATE 之间存在并发窗口，多 worker 部署会互相覆盖。收敛为
`UPDATE ... SET content_version = content_version + 1 WHERE id = ? AND
content_version = ?` 的原子 CAS（迁移 no_130，docs/web/video_workflow_upload_dedup.md）。
"""
from unittest.mock import patch

from model.video_workflow import VideoWorkflowModel


def _captured_sql(fake_execute):
    sql, params = fake_execute.call_args.args
    return sql, params


def test_update_without_expected_version_bumps_and_no_condition():
    with patch("model.video_workflow.execute_update", return_value=1) as fake:
        affected = VideoWorkflowModel.update(1, name="n")
    sql, params = _captured_sql(fake)
    assert affected == 1
    assert "content_version = content_version + 1" in sql
    # 无条件覆盖路径：只有 id 条件，不带版本号
    assert "AND content_version" not in sql
    assert params[-1] == 1


def test_update_with_expected_version_adds_cas_condition():
    with patch("model.video_workflow.execute_update", return_value=1) as fake:
        affected = VideoWorkflowModel.update(1, expected_content_version=5, name="n")
    sql, params = _captured_sql(fake)
    assert affected == 1
    assert "content_version = content_version + 1" in sql
    assert "AND content_version = %s" in sql
    assert params[-2:] == (1, 5)


def test_version_mismatch_returns_zero_rows():
    # 版本竞争失败（并发写已抢先）：affected=0，由调用方转 409
    with patch("model.video_workflow.execute_update", return_value=0) as fake:
        affected = VideoWorkflowModel.update(1, expected_content_version=4, name="n")
    assert affected == 0
    assert fake.call_args.args[1][-1] == 4


def test_dict_workflow_data_serialized():
    with patch("model.video_workflow.execute_update", return_value=1) as fake:
        VideoWorkflowModel.update(1, workflow_data={"nodes": []})
    sql, params = _captured_sql(fake)
    assert "workflow_data = %s" in sql
    assert isinstance(params[0], str)  # dict 已 json.dumps


def test_no_valid_fields_short_circuits():
    with patch("model.video_workflow.execute_update") as fake:
        affected = VideoWorkflowModel.update(1, unknown_field="x")
    assert affected == 0
    fake.assert_not_called()


def test_entity_defaults_content_version_for_premigration_rows():
    # 迁移前的行 SELECT * 不含 content_version 列，实体取默认 0
    from model.video_workflow import VideoWorkflow
    row = VideoWorkflow(id=1, name="n")
    assert row.content_version == 0
