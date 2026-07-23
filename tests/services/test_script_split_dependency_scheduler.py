"""效果模式依赖调度：pending/failed 可调度，上游 failed 为 waiting 非 blocked。

Community CI does not ship the `enterprise` package (gitignored). Skip cleanly
when the module is unavailable so services discovery still succeeds.
"""
import importlib.util
import unittest

_HAS_ENTERPRISE_SCHEDULER = (
    importlib.util.find_spec("enterprise") is not None
    and importlib.util.find_spec(
        "enterprise.services.script_split_quality.dependency_scheduler"
    )
    is not None
)

if _HAS_ENTERPRISE_SCHEDULER:
    from enterprise.services.script_split_quality.dependency_scheduler import (
        classify_segments,
        select_ready_segments,
    )


def _plan_chain():
    """seg1 none → seg2 inherit(seg1) → seg3 inherit(seg2)。"""
    return {
        "segments": [
            {
                "segment_id": "seg_0001",
                "spatial_dependency": {
                    "mode": "none",
                    "reason": "开篇",
                },
            },
            {
                "segment_id": "seg_0002",
                "spatial_dependency": {
                    "mode": "inherit",
                    "from_segment_id": "seg_0001",
                    "reason": "同场景延续",
                    "camera_pose_policy": "reference",
                },
            },
            {
                "segment_id": "seg_0003",
                "spatial_dependency": {
                    "mode": "inherit",
                    "from_segment_id": "seg_0002",
                    "reason": "同场景延续",
                    "camera_pose_policy": "reference",
                },
            },
        ]
    }


def _seg(segment_id, index, status, parsed=None):
    row = {
        "segment_id": segment_id,
        "segment_index": index,
        "status": status,
    }
    if parsed is not None:
        row["parsed_result_json"] = parsed
    return row


class _Entity:
    """模拟 ScriptSplitSegment（含 get_parsed_result）。"""

    def __init__(self, segment_id, index, status, parsed=None):
        self.segment_id = segment_id
        self.segment_index = index
        self.status = status
        self._parsed = parsed

    def get_parsed_result(self):
        return self._parsed


@unittest.skipUnless(
    _HAS_ENTERPRISE_SCHEDULER,
    "enterprise.services.script_split_quality.dependency_scheduler not available",
)
class TestScriptSplitDependencyScheduler(unittest.TestCase):
    def test_failed_segment_is_ready_for_retry(self):
        """中间失败段必须再次进入 ready，否则质检第 2 轮/force-accept 永不执行。"""
        plan = _plan_chain()
        all_segments = [
            _seg("seg_0001", 1, "completed", parsed={"shot_groups": []}),
            _seg("seg_0002", 2, "failed", parsed={"shot_groups": [{"shots": []}]}),
            _seg("seg_0003", 3, "pending"),
        ]
        ready = select_ready_segments(plan, all_segments, limit=3)
        self.assertEqual([s["segment_id"] for s in ready], ["seg_0002"])

        ready2, waiting, blocked = classify_segments(plan, all_segments)
        self.assertEqual([s["segment_id"] for s in ready2], ["seg_0002"])
        self.assertEqual([w["segment"]["segment_id"] for w in waiting], ["seg_0003"])
        self.assertEqual(waiting[0]["from_status"], "failed")
        self.assertEqual(blocked, [])

    def test_upstream_failed_is_waiting_not_blocked(self):
        """下游 inherit 上游 failed 时应 waiting，不得 quality_dependency_blocked。"""
        plan = _plan_chain()
        all_segments = [
            _Entity("seg_0001", 1, "completed", parsed={"shot_groups": []}),
            _Entity("seg_0002", 2, "failed", parsed={"shot_groups": [{"shots": []}]}),
            _Entity("seg_0003", 3, "pending"),
        ]
        ready, waiting, blocked = classify_segments(plan, all_segments)
        self.assertEqual([s.segment_id for s in ready], ["seg_0002"])
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0]["segment"].segment_id, "seg_0003")
        self.assertEqual(waiting[0]["from_segment_id"], "seg_0002")
        self.assertEqual(waiting[0]["from_status"], "failed")
        self.assertEqual(blocked, [])

    def test_pending_with_completed_upstream_is_ready(self):
        plan = _plan_chain()
        all_segments = [
            _Entity("seg_0001", 1, "completed", parsed={"ok": True}),
            _Entity("seg_0002", 2, "pending"),
            _Entity("seg_0003", 3, "pending"),
        ]
        ready = select_ready_segments(plan, all_segments, limit=5)
        self.assertEqual([s.segment_id for s in ready], ["seg_0002"])

    def test_completed_and_generating_never_ready(self):
        plan = _plan_chain()
        all_segments = [
            _seg("seg_0001", 1, "completed", parsed={"ok": True}),
            _seg("seg_0002", 2, "generating"),
            _seg("seg_0003", 3, "pending"),
        ]
        ready, waiting, blocked = classify_segments(plan, all_segments)
        self.assertEqual(ready, [])
        self.assertEqual([w["segment"]["segment_id"] for w in waiting], ["seg_0003"])
        self.assertEqual(blocked, [])

    def test_missing_upstream_is_blocked(self):
        plan = {
            "segments": [
                {
                    "segment_id": "seg_0002",
                    "spatial_dependency": {
                        "mode": "inherit",
                        "from_segment_id": "seg_missing",
                        "reason": "坏依赖",
                        "camera_pose_policy": "reference",
                    },
                },
            ]
        }
        all_segments = [_seg("seg_0002", 2, "pending")]
        ready, waiting, blocked = classify_segments(plan, all_segments)
        self.assertEqual(ready, [])
        self.assertEqual(waiting, [])
        self.assertEqual([s["segment_id"] for s in blocked], ["seg_0002"])

    def test_completed_upstream_without_parsed_is_blocked(self):
        plan = _plan_chain()
        all_segments = [
            _Entity("seg_0001", 1, "completed", parsed=None),
            _Entity("seg_0002", 2, "pending"),
        ]
        ready, waiting, blocked = classify_segments(plan, all_segments)
        self.assertEqual(ready, [])
        self.assertEqual(waiting, [])
        self.assertEqual([s.segment_id for s in blocked], ["seg_0002"])

    def test_select_ready_respects_limit_and_order(self):
        plan = {
            "segments": [
                {"segment_id": "seg_a", "spatial_dependency": {"mode": "none", "reason": "a"}},
                {"segment_id": "seg_b", "spatial_dependency": {"mode": "none", "reason": "b"}},
                {"segment_id": "seg_c", "spatial_dependency": {"mode": "none", "reason": "c"}},
            ]
        }
        all_segments = [
            _seg("seg_c", 3, "pending"),
            _seg("seg_a", 1, "failed"),
            _seg("seg_b", 2, "pending"),
        ]
        ready = select_ready_segments(plan, all_segments, limit=2)
        self.assertEqual([s["segment_id"] for s in ready], ["seg_a", "seg_b"])
