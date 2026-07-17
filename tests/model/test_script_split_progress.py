"""script_split 生成进度：段表实时 completed + 只增不减。"""
from types import SimpleNamespace

from model.script_split_task import ScriptSplitTask, ScriptSplitTaskModel
from config.constant import ScriptSplitConstants


def test_compute_generation_progress_from_completed_ratio(monkeypatch):
    monkeypatch.setattr(
        ScriptSplitTaskModel,
        "count_completed_segments",
        staticmethod(lambda task_id: 3),
    )
    progress, completed = ScriptSplitTaskModel.compute_generation_progress(
        task_id=1,
        total_segments=6,
        previous_progress=None,
    )
    # 10 + int(75 * 3/6) = 47
    assert completed == 3
    assert progress == 47


def test_compute_generation_progress_is_monotonic(monkeypatch):
    monkeypatch.setattr(
        ScriptSplitTaskModel,
        "count_completed_segments",
        staticmethod(lambda task_id: 2),
    )
    # 实时只有 2/6 → 公式 35，但历史已到 82 时不得回退
    progress, completed = ScriptSplitTaskModel.compute_generation_progress(
        task_id=1,
        total_segments=6,
        previous_progress=82,
    )
    assert completed == 2
    assert progress == 82


def test_live_generation_progress_view_uses_first_uncompleted(monkeypatch):
    monkeypatch.setattr(
        ScriptSplitTaskModel,
        "count_completed_segments",
        staticmethod(lambda task_id: 4),
    )
    monkeypatch.setattr(
        ScriptSplitTaskModel,
        "compute_generation_progress",
        staticmethod(lambda *a, **k: (60, 4)),
    )

    class _Seg:
        segment_index = 2

    import model.script_split_segment as seg_mod

    monkeypatch.setattr(
        seg_mod.ScriptSplitSegmentModel,
        "get_first_uncompleted",
        staticmethod(lambda task_id: _Seg()),
    )
    progress, completed, current = ScriptSplitTaskModel.live_generation_progress_view(
        task_id=44,
        total_segments=6,
        previous_progress=47,
        fallback_current=6,
    )
    assert progress == 60
    assert completed == 4
    assert current == 2  # 不是陈旧的 6


def test_to_public_status_generation_uses_live_view(monkeypatch):
    task = ScriptSplitTask(
        id=44,
        status=ScriptSplitConstants.STATUS_GENERATING,
        phase="segment_generation",
        progress=47,
        completed_segment_count=3,
        total_segment_count=6,
        current_segment_index=6,
    )
    monkeypatch.setattr(
        ScriptSplitTaskModel,
        "live_generation_progress_view",
        staticmethod(lambda *a, **k: (72, 5, 2)),
    )
    public = task.to_public_status()
    assert public["progress"] == 72
    assert public["completed_segments"] == 5
    assert public["current_segment"] == 2
    assert "2/6" in public["message"]
