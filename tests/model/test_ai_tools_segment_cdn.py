"""段记录 CDN 抑制：分段数字人的单段是拼接中间产物，不建 CDN 映射。

见 docs/digital_human_compose_job_plan.md §4.7：
40 段 = 40 次无谓上传 + 40 条 media_file_mapping。判定集中在模型层，
download worker 与其它调用方零改动。
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from model.ai_tools import AIToolsModel, is_segment_ai_tool


def _tool(extra_config=None, media_mapping_id=None):
    return SimpleNamespace(
        id=321,
        user_id=3,
        extra_config=extra_config,
        media_mapping_id=media_mapping_id,
        result_url=None,
    )


# ==================== 判定函数 ====================

def test_is_segment_ai_tool_true_for_segment_record():
    assert is_segment_ai_tool(_tool(json.dumps({"dh_segment": True, "seg_index": 2}))) is True


def test_is_segment_ai_tool_false_for_regular_record():
    assert is_segment_ai_tool(_tool(json.dumps({"max_edge": 1280}))) is False
    assert is_segment_ai_tool(_tool(None)) is False
    # 脏 JSON 不得抛异常（编排主循环会依赖它）
    assert is_segment_ai_tool(_tool("not-json")) is False
    # dh_segment 显式为 false / 0 视为普通记录
    assert is_segment_ai_tool(_tool(json.dumps({"dh_segment": False}))) is False


# ==================== update_by_project_id_with_cdn_sync 早退 ====================

def test_segment_update_skips_cdn_mapping():
    tool = _tool(json.dumps({"dh_segment": True}))
    with patch.object(AIToolsModel, "get_by_project_id", return_value=tool), \
         patch.object(AIToolsModel, "update_by_project_id", return_value=1) as upd, \
         patch("model.media_file_mapping.MediaFileMappingModel.create") as mapping_create:
        affected = AIToolsModel.update_by_project_id_with_cdn_sync(
            project_id="rh-task-1",
            result_url="/upload/cache/2026-10-21/seg.mp4",
            status=2,
        )

    assert affected == 1
    mapping_create.assert_not_called()
    upd.assert_called_once()
    assert upd.call_args.kwargs["result_url"] == "/upload/cache/2026-10-21/seg.mp4"
    assert upd.call_args.kwargs["status"] == 2


def test_regular_record_still_creates_cdn_mapping():
    """非段记录的行为不变（回归保护：CDN 抑制不能误伤普通任务）。"""
    tool = _tool(json.dumps({"max_edge": 1280}))
    with patch.object(AIToolsModel, "get_by_project_id", return_value=tool), \
         patch.object(AIToolsModel, "update_by_project_id", return_value=1), \
         patch("model.ai_tools.get_config",
               return_value={"server": {"auto_upload_to_cdn": True}}), \
         patch("model.media_file_mapping.MediaFileMappingModel.create",
               return_value=77) as mapping_create, \
         patch("utils.cdn_util.CDNUtil.trigger_cdn_upload") as cdn:
        AIToolsModel.update_by_project_id_with_cdn_sync(
            project_id="rh-task-2",
            result_url="/upload/cache/2026-10-21/full.mp4",
            status=2,
        )

    mapping_create.assert_called_once()
    cdn.assert_called_once()
