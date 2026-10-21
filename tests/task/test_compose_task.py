"""compose_task 状态机单测（不连 DB、不跑 ffmpeg）。

覆盖方案 4.4 状态机的关键分支：
  - 段全部在途 → 只重排 next_trigger，不消耗 try_count
  - 段失败 → 补段并按 seg_index 原位替换
  - 段 COMPLETED 但结果为远端地址 → 有限次自愈后降级补段（并退费）
  - 段全部就绪 → 拼接 + 编排终态收尾（tasks 行同步终态）
  - 编排已终态 → 只补收尾 tasks 行（防重复拼接）
"""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from config.constant import (
    AI_TOOL_STATUS_COMPLETED,
    AI_TOOL_STATUS_FAILED,
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_TYPE_GENERATE_VIDEO,
    TaskTypeId,
    ComposeJobStatus,
    ComposeJobConstants,
)
from task import compose_task


def _task(**overrides):
    base = {
        "id": 1,
        "task_id": 7,          # = compose_jobs.id
        "try_count": 0,
        "status": 1,
        "next_trigger": None,
        "created_at": datetime.now(),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _job(**overrides):
    base = {
        "id": 7,
        "user_id": 3,
        "status": ComposeJobStatus.PENDING,
        "is_terminal": False,
        "segment_ai_tool_ids": [101, 102],
        "params": {"segment_durations": [10, 10], "segment_paths": ["/a.wav", "/b.wav"]},
        "result_url": None,
        "message": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _seg(seg_id, status, result_url=None, extra_config=None, message=None):
    return SimpleNamespace(
        id=seg_id,
        status=status,
        result_url=result_url,
        extra_config=extra_config,
        message=message,
        user_id=3,
        type=35,
        duration=10,
        transaction_id="txn-1",
    )


@pytest.fixture
def captured(monkeypatch):
    """统一打桩模型层与外部副作用，返回调用记录。"""
    store = {
        "tasks_update": [],
        "job_update": [],
        "job_segment_ids": [],
        "ai_update": [],
        "concat": [],
        "refund": [],
        "refill": [],
        # 计费相关（补段：扣费 / 建记录 / 回滚 / 事件日志）
        "charge": [],
        "refund_txn": [],
        "ai_create": [],
        "task_create": [],
        "events": [],
    }

    monkeypatch.setattr(compose_task, "_check_task_expiration", lambda task: False)
    # 补段前置校验（真实实现查 upload/temp 落盘文件，单测无文件系统，统一视为可用）
    monkeypatch.setattr(compose_task, "_segment_audio_available", lambda job, idx: True)
    monkeypatch.setattr(compose_task, "_segment_image_available", lambda job: True)
    monkeypatch.setattr(
        compose_task.TasksModel, "update",
        lambda record_id, **fields: store["tasks_update"].append((record_id, fields)) or 1,
    )
    monkeypatch.setattr(
        compose_task.ComposeJobModel, "update",
        lambda compose_id, **fields: store["job_update"].append((compose_id, fields)) or 1,
    )
    monkeypatch.setattr(
        compose_task.ComposeJobModel, "update_segment_ids",
        lambda compose_id, ids: store["job_segment_ids"].append((compose_id, list(ids))) or 1,
    )
    monkeypatch.setattr(
        compose_task.AIToolsModel, "update",
        lambda record_id, **fields: store["ai_update"].append((record_id, fields)) or 1,
    )
    monkeypatch.setattr(
        compose_task, "_refund_segment",
        lambda ai_tool, reason: store["refund"].append((ai_tool.id, reason)),
    )
    monkeypatch.setattr(
        compose_task, "_concat_with_timeout",
        lambda project_id, files: store["concat"].append((project_id, list(files))) or "/upload/cache/x.mp4",
    )
    monkeypatch.setattr(compose_task, "_attach_cdn_mapping", lambda job, url: None)
    # 事件日志：真实实现会连库，单测只记录
    monkeypatch.setattr(
        compose_task.AIToolsLogModel, "log",
        staticmethod(lambda *a, **kw: store["events"].append((a[1] if len(a) > 1 else kw.get('event_type'), kw))),
    )
    # 补段扣费/回滚默认走桩（真实实现依赖 perseids 与用户 token）
    monkeypatch.setattr(
        compose_task, "_charge_segment",
        lambda user_id, power, transaction_id: store["charge"].append(
            (user_id, power, transaction_id)) or True,
    )
    monkeypatch.setattr(
        compose_task, "_refund_by_transaction",
        lambda user_id, transaction_id, power, reason: store["refund_txn"].append(
            (user_id, transaction_id, power, reason)),
    )
    monkeypatch.setattr(
        compose_task.AIToolsModel, "create",
        lambda **kwargs: store["ai_create"].append(kwargs) or 900,
    )
    monkeypatch.setattr(
        compose_task.TasksModel, "create",
        lambda **kwargs: store["task_create"].append(kwargs) or 1,
    )
    monkeypatch.setattr(compose_task, "_segment_power", lambda duration: 55)
    return store


def _patch_job(monkeypatch, job):
    monkeypatch.setattr(compose_task.ComposeJobModel, "get_by_id", lambda cid: job)


def _patch_segments(monkeypatch, segments):
    table = {seg.id: seg for seg in segments}
    monkeypatch.setattr(compose_task.AIToolsModel, "get_by_id", lambda sid: table.get(int(sid)))


# ==================== 1. 在途等待不消耗重试预算 ====================

def test_waiting_does_not_consume_try_count(monkeypatch, captured):
    task = _task(try_count=5)
    _patch_job(monkeypatch, _job())
    _patch_segments(monkeypatch, [
        _seg(101, AI_TOOL_STATUS_PROCESSING),
        _seg(102, AI_TOOL_STATUS_PROCESSING),
    ])

    compose_task._process_one_compose(task)

    assert captured["concat"] == []
    updates = [fields for _, fields in captured["tasks_update"]]
    assert any("next_trigger" in f for f in updates)
    # 关键：等待分支绝不动 try_count（否则长任务未跑完就被判死）
    assert all("try_count" not in f for f in updates)


# ==================== 2. 缺口补段：原位替换保顺序 ====================

def test_gap_refill_replaces_in_place(monkeypatch, captured):
    task = _task(try_count=0)
    _patch_job(monkeypatch, _job())
    _patch_segments(monkeypatch, [
        _seg(101, AI_TOOL_STATUS_COMPLETED, "/upload/cache/a.mp4"),
        _seg(102, AI_TOOL_STATUS_FAILED),
    ])
    monkeypatch.setattr(
        compose_task, "_segment_local_path",
        lambda seg: "/tmp/a.mp4" if seg.id == 101 else None,
    )
    monkeypatch.setattr(
        compose_task, "_refill_segment",
        lambda job, task, idx: captured["refill"].append(idx) or 999,
    )

    compose_task._process_one_compose(task)

    # 第 1 槽位（seg_index=1）被新段替换，顺序不被打乱、不追加到尾部
    assert captured["job_segment_ids"] == [(7, [101, 999])]
    assert captured["refill"] == [1]
    updates = [fields for _, fields in captured["tasks_update"]]
    assert any(f.get("try_count") == 1 for f in updates)


# ==================== 3. 远端兜底残留：有限次自愈后降级补段 ====================

def test_remote_fallback_downgrades_after_max_attempts(monkeypatch, captured):
    task = _task(try_count=1)
    _patch_job(monkeypatch, _job(segment_ai_tool_ids=[101]))
    _patch_segments(monkeypatch, [
        _seg(
            101, AI_TOOL_STATUS_COMPLETED,
            result_url="https://runninghub.test/out.mp4",
            extra_config=json.dumps({
                "dh_segment": True,
                "compose_download_attempts": ComposeJobConstants.SEGMENT_REMOTE_DOWNLOAD_MAX_ATTEMPTS,
            }),
        ),
    ])
    monkeypatch.setattr(compose_task, "_segment_local_path", lambda seg: None)
    monkeypatch.setattr(compose_task, "_self_download_segment", lambda seg: None)
    monkeypatch.setattr(
        compose_task, "_refill_segment",
        lambda job, task, idx: captured["refill"].append(idx) or 500,
    )

    compose_task._process_one_compose(task)

    # 段被降级为 FAILED + 退费
    seg_updates = [f for rid, f in captured["ai_update"] if rid == 101]
    assert any(f.get("status") == AI_TOOL_STATUS_FAILED for f in seg_updates)
    assert captured["refund"] and captured["refund"][0][0] == 101
    # 随后进入补段闭环，而不是空转到整单失败
    assert captured["refill"] == [0]
    assert captured["job_segment_ids"] == [(7, [500])]


# ==================== 4. 全部就绪：拼接 + 双终态收尾 ====================

def test_all_ready_concats_and_finishes(monkeypatch, captured):
    task = _task(try_count=2)
    _patch_job(monkeypatch, _job())
    _patch_segments(monkeypatch, [
        _seg(101, AI_TOOL_STATUS_COMPLETED, "/upload/cache/a.mp4"),
        _seg(102, AI_TOOL_STATUS_COMPLETED, "/upload/cache/b.mp4"),
    ])
    monkeypatch.setattr(
        compose_task, "_segment_local_path",
        lambda seg: f"/tmp/{seg.id}.mp4",
    )

    compose_task._process_one_compose(task)

    assert captured["concat"] and captured["concat"][0][0] == "compose_7"
    assert captured["concat"][0][1] == ["/tmp/101.mp4", "/tmp/102.mp4"]

    job_updates = [f for _, f in captured["job_update"]]
    assert any(f.get("status") == ComposeJobStatus.COMPLETED
               and f.get("result_url") == "/upload/cache/x.mp4" for f in job_updates)
    task_updates = [f for _, f in captured["tasks_update"]]
    assert any(f.get("status") == TASK_STATUS_COMPLETED for f in task_updates)


# ==================== 5. 已终态编排单：只补收尾，不重复拼接 ====================

def test_terminal_job_only_syncs_tasks_row(monkeypatch, captured):
    task = _task(try_count=0)
    _patch_job(monkeypatch, _job(status=ComposeJobStatus.COMPLETED, is_terminal=True))
    _patch_segments(monkeypatch, [])

    compose_task._process_one_compose(task)

    assert captured["concat"] == []
    assert captured["tasks_update"] == [(1, {"status": TASK_STATUS_COMPLETED})]


# ==================== 6. 补段次数超限：整单失败 ====================

def test_max_retry_exceeded_fails_job(monkeypatch, captured):
    task = _task(try_count=ComposeJobConstants.MAX_RETRY_COUNT)
    _patch_job(monkeypatch, _job())
    _patch_segments(monkeypatch, [
        _seg(101, AI_TOOL_STATUS_FAILED),
        _seg(102, AI_TOOL_STATUS_COMPLETED, "/upload/cache/b.mp4"),
    ])
    monkeypatch.setattr(compose_task, "_segment_local_path", lambda seg: None)

    compose_task._process_one_compose(task)

    job_updates = [f for _, f in captured["job_update"]]
    assert any(f.get("status") == ComposeJobStatus.FAILED for f in job_updates)
    task_updates = [f for _, f in captured["tasks_update"]]
    assert any(f.get("status") == TASK_STATUS_FAILED for f in task_updates)


# ==================== 7. 编排单记录缺失：调度行置失败 ====================

def test_missing_compose_job_fails_schedule_row(monkeypatch, captured):
    task = _task()
    monkeypatch.setattr(compose_task.ComposeJobModel, "get_by_id", lambda cid: None)

    compose_task._process_one_compose(task)

    assert captured["tasks_update"] == [(1, {"status": TASK_STATUS_FAILED})]


# ==================== 8. 补段前置校验：段音频已失效则快速失败 ====================

def test_missing_segment_audio_fails_fast(monkeypatch, captured):
    """段音频（upload/temp 临时文件）被清理后，补段只会「扣费→失败→退费」空转。"""
    task = _task(try_count=0)
    _patch_job(monkeypatch, _job())
    _patch_segments(monkeypatch, [
        _seg(101, AI_TOOL_STATUS_COMPLETED, "/upload/cache/a.mp4"),
        _seg(102, AI_TOOL_STATUS_FAILED),
    ])
    monkeypatch.setattr(compose_task, "_segment_local_path", lambda seg: "/tmp/a.mp4")
    monkeypatch.setattr(compose_task, "_segment_audio_available", lambda job, idx: False)
    monkeypatch.setattr(
        compose_task, "_refill_segment",
        lambda job, task, idx: captured["refill"].append(idx) or 999,
    )

    compose_task._process_one_compose(task)

    assert captured["refill"] == []                      # 不产生新的计费段
    job_updates = [f for _, f in captured["job_update"]]
    assert any(f.get("status") == ComposeJobStatus.FAILED for f in job_updates)
    assert any("音频文件缺失" in (f.get("message") or "") for f in job_updates)


# ==================== 9/10. 拼接失败独立熔断（不占补段预算）====================

def _patch_all_ready(monkeypatch):
    _patch_segments(monkeypatch, [
        _seg(101, AI_TOOL_STATUS_COMPLETED, "/upload/cache/a.mp4"),
        _seg(102, AI_TOOL_STATUS_COMPLETED, "/upload/cache/b.mp4"),
    ])
    monkeypatch.setattr(compose_task, "_segment_local_path", lambda seg: f"/tmp/{seg.id}.mp4")


def test_concat_failure_backs_off_without_touching_try_count(monkeypatch, captured):
    task = _task(try_count=4)
    _patch_job(monkeypatch, _job(concat_attempts=0))
    _patch_all_ready(monkeypatch)
    monkeypatch.setattr(
        compose_task, "_concat_with_timeout",
        lambda project_id, files: (_ for _ in ()).throw(RuntimeError("ffmpeg boom")),
    )

    compose_task._process_one_compose(task)

    job_updates = [f for _, f in captured["job_update"]]
    assert any(f.get("concat_attempts") == 1
               and f.get("status") == ComposeJobStatus.PENDING for f in job_updates)
    updates = [f for _, f in captured["tasks_update"]]
    assert any("next_trigger" in f for f in updates)
    # 补段预算不被拼接失败消耗
    assert all("try_count" not in f for f in updates)


def test_concat_failure_trips_breaker(monkeypatch, captured):
    task = _task(try_count=4)
    _patch_job(
        monkeypatch,
        _job(concat_attempts=ComposeJobConstants.CONCAT_MAX_ATTEMPTS - 1),
    )
    _patch_all_ready(monkeypatch)
    monkeypatch.setattr(
        compose_task, "_concat_with_timeout",
        lambda project_id, files: (_ for _ in ()).throw(RuntimeError("ffmpeg boom")),
    )

    compose_task._process_one_compose(task)

    job_updates = [f for _, f in captured["job_update"]]
    assert any(f.get("status") == ComposeJobStatus.FAILED for f in job_updates)
    task_updates = [f for _, f in captured["tasks_update"]]
    assert any(f.get("status") == TASK_STATUS_FAILED for f in task_updates)


# ==================== 11. 补段计费：先扣费，再建段 ====================

def test_refill_charges_then_creates_segment(monkeypatch, captured):
    """补段必须「先扣费、再建记录」，且扣费流水号写进段记录（退费依据）。"""
    job = _job()
    seg_id = compose_task._refill_segment(job, _task(), 1)

    assert seg_id == 900

    # 1) 扣费：用户、算力、独立流水号
    assert len(captured["charge"]) == 1
    user_id, power, transaction_id = captured["charge"][0]
    assert (user_id, power) == (3, 55)
    assert transaction_id and len(transaction_id) > 10

    # 2) 建段：参数取自 compose 快照的对应下标，流水号与扣费一致
    assert len(captured["ai_create"]) == 1
    created = captured["ai_create"][0]
    assert created["duration"] == 10                       # segment_durations[1]
    assert created["audio_path"] == "/b.wav"               # segment_paths[1]
    assert created["type"] == TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3
    assert created["status"] == AI_TOOL_STATUS_PENDING
    assert created["transaction_id"] == transaction_id
    extra = json.loads(created["extra_config"])
    assert extra["dh_segment"] is True
    assert extra["seg_index"] == 2                         # 1-based，供后续排查
    assert extra["compose_id"] == job.id
    assert extra["compose_refill"] is True

    # 3) 入队（与普通视频任务同一队列）
    assert captured["task_create"][0]["task_id"] == 900
    assert captured["task_create"][0]["task_type"] == TASK_TYPE_GENERATE_VIDEO

    assert any(ev[0] == "pipeline_step" for ev in captured["events"])


def test_refill_charge_failure_creates_no_record(monkeypatch, captured):
    """扣费失败 → 不建段、不入队、不触发回滚（根本没扣到钱）。"""
    monkeypatch.setattr(compose_task, "_charge_segment", lambda *a, **kw: False)

    assert compose_task._refill_segment(_job(), _task(), 0) is None

    assert captured["ai_create"] == []
    assert captured["task_create"] == []
    assert captured["refund_txn"] == []
    assert any(ev[0] == "exception" and "扣费" in (ev[1].get("message") or "")
               for ev in captured["events"])


def test_refill_create_failure_refunds_same_transaction(monkeypatch, captured):
    """扣费成功但建记录失败 → 按**原扣费流水号**原额退回（refund-<tid> 幂等）。"""
    def _boom(**kwargs):
        captured["ai_create"].append(kwargs)
        raise RuntimeError("db down")

    monkeypatch.setattr(compose_task.AIToolsModel, "create", _boom)

    assert compose_task._refill_segment(_job(), _task(), 0) is None

    assert len(captured["refund_txn"]) == 1
    user_id, transaction_id, power, reason = captured["refund_txn"][0]
    assert (user_id, power) == (3, 55)
    assert transaction_id == captured["charge"][0][2]      # 与扣费同一流水号
    assert "建记录失败" in reason
    assert captured["task_create"] == []                   # 未建调度行


def test_refill_missing_params_skips_charging(captured):
    """参数快照缺该段 → 直接返回，不产生任何扣费。"""
    job = _job(params={"segment_durations": [10], "segment_paths": ["/a.wav"]})

    assert compose_task._refill_segment(job, _task(), 2) is None

    assert captured["charge"] == []
    assert captured["ai_create"] == []


# ==================== 12. 扣费/回滚接口契约 ====================

def test_charge_segment_deducts_with_transaction_id(monkeypatch):
    calls = []

    def fake_request(endpoint=None, method=None, headers=None, data=None, **kw):
        calls.append({"endpoint": endpoint, "headers": headers, "data": data})
        if endpoint == "get_auth_token_by_user_id":
            return True, "ok", {"token": "tk"}
        return True, "ok", {}

    monkeypatch.setattr(compose_task, "make_perseids_request", fake_request)

    assert compose_task._charge_segment(3, 55, "txn-a") is True

    assert calls[0]["endpoint"] == "get_auth_token_by_user_id"
    assert calls[1]["endpoint"] == "user/calculate_computing_power"
    assert calls[1]["data"] == {
        "computing_power": 55, "behavior": "deduct", "transaction_id": "txn-a"}
    assert calls[1]["headers"] == {"Authorization": "Bearer tk"}


def test_charge_segment_token_failure_skips_deduction(monkeypatch):
    calls = []

    def fake_request(endpoint=None, **kw):
        calls.append(endpoint)
        return False, "no token", None

    monkeypatch.setattr(compose_task, "make_perseids_request", fake_request)

    assert compose_task._charge_segment(3, 55, "txn-a") is False
    assert calls == ["get_auth_token_by_user_id"]          # 未发起扣费


def test_charge_segment_skips_when_power_zero(monkeypatch):
    monkeypatch.setattr(
        compose_task, "make_perseids_request",
        lambda **kw: pytest.fail("零算力不应调用计费接口"),
    )
    assert compose_task._charge_segment(3, 0, "txn-a") is True


def test_refund_by_transaction_uses_refund_prefix(monkeypatch):
    calls = []

    def fake_request(endpoint=None, method=None, headers=None, data=None, **kw):
        calls.append({"endpoint": endpoint, "data": data})
        if endpoint == "get_auth_token_by_user_id":
            return True, "ok", {"token": "tk"}
        return True, "ok", {}

    monkeypatch.setattr(compose_task, "make_perseids_request", fake_request)

    compose_task._refund_by_transaction(3, "txn-a", 55, "补段建记录失败")

    assert calls[1]["data"] == {
        "computing_power": 55, "behavior": "increase",
        "transaction_id": "refund-txn-a"}


# ==================== 13. 审核类确定性失败：整单快速失败，不补段 ====================

def test_moderation_failed_segment_fails_compose_fast(monkeypatch, captured):
    """段因内容审核失败（message 以友好前缀开头）→ 相同输入补段必然再败，
    必须整单 FAILED 并透传原因，不得产生任何补段扣费。"""
    task = _task(try_count=0)
    _patch_job(monkeypatch, _job())
    moderation_msg = "内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试"
    _patch_segments(monkeypatch, [
        _seg(101, AI_TOOL_STATUS_COMPLETED, "/upload/cache/a.mp4"),
        _seg(102, AI_TOOL_STATUS_FAILED, message=moderation_msg),
    ])
    monkeypatch.setattr(compose_task, "_segment_local_path", lambda seg: "/tmp/a.mp4")

    compose_task._process_one_compose(task)

    assert captured["refill"] == []                       # 不补段
    assert captured["charge"] == []                       # 不扣费
    job_updates = [f for _, f in captured["job_update"]]
    assert any(f.get("status") == ComposeJobStatus.FAILED
               and f.get("message") == moderation_msg for f in job_updates)
    task_updates = [f for _, f in captured["tasks_update"]]
    assert any(f.get("status") == TASK_STATUS_FAILED for f in task_updates)


def test_moderation_detected_from_raw_upstream_message(monkeypatch, captured):
    """段 message 未经友好改写（原始上游文案）时，靠分类器兜底识别。"""
    task = _task(try_count=0)
    _patch_job(monkeypatch, _job())
    _patch_segments(monkeypatch, [
        _seg(102, AI_TOOL_STATUS_FAILED,
             message='{"code":"moderation_blocked","message":"content rejected"}'),
    ])

    compose_task._process_one_compose(task)

    assert captured["refill"] == []
    assert captured["charge"] == []
    job_updates = [f for _, f in captured["job_update"]]
    assert any(f.get("status") == ComposeJobStatus.FAILED for f in job_updates)


def test_normal_failure_still_refills(monkeypatch, captured):
    """非审核类失败（普通上游异常）→ 仍走补段流程（回归保护）。"""
    task = _task(try_count=0)
    _patch_job(monkeypatch, _job())
    _patch_segments(monkeypatch, [
        _seg(101, AI_TOOL_STATUS_COMPLETED, "/upload/cache/a.mp4"),
        _seg(102, AI_TOOL_STATUS_FAILED, message="服务异常，请联系技术支持"),
    ])
    monkeypatch.setattr(compose_task, "_segment_local_path", lambda seg: "/tmp/a.mp4")
    monkeypatch.setattr(
        compose_task, "_refill_segment",
        lambda job, task, idx: captured["refill"].append(idx) or 900,
    )

    compose_task._process_one_compose(task)

    assert captured["refill"] == [1]
    job_updates = [f for _, f in captured["job_update"]]
    assert not any(f.get("status") == ComposeJobStatus.FAILED for f in job_updates)
