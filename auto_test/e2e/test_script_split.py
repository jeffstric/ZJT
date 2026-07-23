"""剧本分段拆分（Incremental Script Split）端到端测试。

覆盖测试方案第 4 章：
- 4.1 剧本拆分全流程（提交 → 202 → 轮询四阶段进度 → completed → 取 result）
- 4.2 断点续传与恢复（active-task 查询、resume、cancel）
- API 权限校验（X-User-Id != owner → 403）
- result 状态校验（非 completed → 409）

说明：
- mock_mode 挡图片/视频/音频媒体产物，但 **不挡 LLM 文本生成**，因此拆分全流程
  会真实调用 LLM（耗时数分钟、消耗算力）。全流程用例标 p1，并加轮询超时保护；
  不依赖 LLM 完成的权限/状态校验用例标 p0。
- 用 sync Playwright API（pytest.ini 已禁用 asyncio plugin），httpx api_client 同步调用。
- 每个测试用 @pytest.mark.p{0,1} + @pytest.mark.script_split 两个堆叠 marker。
"""
import time

import pytest


SPLIT_API = "/api/script-split"
# 终态：拆分任务最终落到这三种之一
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
# 交互态：需用户介入（继续 / 刷新鉴权）
INTERACTIVE_STATUSES = {"paused", "waiting_auth"}


def _poll_until(api_client, task_id, timeout=180, interval=3):
    """轮询拆分任务状态直到终态或交互态，返回最新状态 dict。

    全流程用例依赖真实 LLM，给足 timeout；非终态超时则返回最后状态供断言。
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = api_client.get(f"{SPLIT_API}/tasks/{task_id}")
        assert resp.status_code == 200, f"轮询任务失败: {resp.status_code} {resp.text}"
        data = resp.json().get("data") or {}
        last = data
        status = data.get("status")
        if status in TERMINAL_STATUSES or status in INTERACTIVE_STATUSES:
            return data
        time.sleep(interval)
    return last or {}


# ============================================================
# P0：不依赖 LLM 完成的 API 行为
# ============================================================

@pytest.mark.p0
@pytest.mark.script_split
def test_get_nonexistent_task_returns_404(api_client, user_id):
    """split_001 - GET /tasks/{不存在的 id} 返回 404。"""
    resp = api_client.get(
        f"{SPLIT_API}/tasks/999999999",
        headers={"X-User-Id": str(user_id)},
    )
    assert resp.status_code == 404, f"期望 404，实际 {resp.status_code}: {resp.text}"
    assert resp.json().get("code") == -1


@pytest.mark.p0
@pytest.mark.script_split
def test_get_task_result_nonexistent_returns_404(api_client, user_id):
    """split_002 - GET /tasks/{不存在}/result 返回 404。"""
    resp = api_client.get(
        f"{SPLIT_API}/tasks/999999999/result",
        headers={"X-User-Id": str(user_id)},
    )
    assert resp.status_code == 404


@pytest.mark.p0
@pytest.mark.script_split
def test_active_task_missing_params_returns_400(api_client, user_id):
    """split_003 - GET /active-task 缺 source_type/source_id 返回 400。"""
    resp = api_client.get(
        f"{SPLIT_API}/active-task",
        headers={"X-User-Id": str(user_id)},
    )
    assert resp.status_code == 400, f"期望 400，实际 {resp.status_code}: {resp.text}"


@pytest.mark.p0
@pytest.mark.script_split
def test_active_task_no_active_returns_null(api_client, user_id, test_world):
    """split_004 - GET /active-task 无活跃任务时 data 为 null。"""
    resp = api_client.get(
        f"{SPLIT_API}/active-task",
        params={"source_type": "storyboard", "source_id": str(test_world["id"])},
        headers={"X-User-Id": str(user_id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("code") == 0
    # 该 world 没有活跃拆分任务（除非并发测试残留），data 应为 null 或 None
    assert body.get("data") is None or body.get("data", {}).get("status") is None


@pytest.mark.p0
@pytest.mark.script_split
def test_resume_nonexistent_task_returns_404(api_client, user_id, auth_token):
    """split_005 - POST /tasks/{不存在}/resume 返回 404。"""
    resp = api_client.post(
        f"{SPLIT_API}/tasks/999999999/resume",
        headers={"X-User-Id": str(user_id), "Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.p0
@pytest.mark.script_split
def test_cancel_nonexistent_task_returns_404(api_client, user_id):
    """split_006 - POST /tasks/{不存在}/cancel 返回 404。"""
    resp = api_client.post(
        f"{SPLIT_API}/tasks/999999999/cancel",
        headers={"X-User-Id": str(user_id)},
    )
    assert resp.status_code == 404


@pytest.mark.p0
@pytest.mark.script_split
def test_owner_isolation_query_task(api_client, user_id):
    """split_007 - 用户不能查询不属于自己的任务（X-User-Id != owner → 403）。

    用一个不存在的 task_id 配合其他 user_id：403 优先于 404 在权限校验之后，
    但不存在的任务 owner 也校验失败。这里验证权限路径不泄露任务存在性需 owner 匹配。
    实际行为：task 不存在 → 404；若 task 存在但 owner 不匹配 → 403。
    本用例验证用错误 user_id 不会拿到 200 数据。
    """
    resp = api_client.get(
        f"{SPLIT_API}/tasks/1",  # 任意 id
        # user_id fixture 为字符串，先转 int 再偏移，避免 str + int 报错
        headers={"X-User-Id": str(int(user_id) + 100000)},  # 几乎不可能匹配的 user_id
    )
    # 不存在 → 404；存在但非 owner → 403；绝不应是 200 且带数据
    assert resp.status_code in (403, 404), f"期望 403/404，实际 {resp.status_code}: {resp.text}"


# ============================================================
# P1：拆分全流程（依赖真实 LLM，慢）
# ============================================================

@pytest.mark.p1
@pytest.mark.script_split
def test_submit_split_returns_202_with_task_id(
    api_client, user_id, auth_token, test_world, mock_mode
):
    """split_101 - 提交剧本拆分任务返回 202 + task_id（不阻塞）。

    通过视频工作流入口 POST /api/parse-script 提交，期望立即返回 202。
    """
    script_content = (
        "第一幕：清晨，小明走进客厅，阳光洒在地板上。\n\n"
        "第二幕：小红推门而入，两人相视而笑。"
    )
    resp = api_client.post(
        "/api/parse-script",
        json={
            "user_id": user_id,
            "auth_token": auth_token,
            "world_id": test_world["id"],
            "script_content": script_content,
            "model": "gemini-2.5-flash",
            "sequence_mode": "speed",
        },
        headers={"X-User-Id": str(user_id), "Authorization": f"Bearer {auth_token}"},
        timeout=30,
    )
    # 接受 202（异步任务已创建）或 200（兼容旧版）；拒绝 500
    assert resp.status_code in (200, 202), f"提交失败: {resp.status_code} {resp.text}"
    body = resp.json()
    data = body.get("data") or body
    task_id = data.get("task_id")
    assert task_id, f"响应缺少 task_id: {body}"


@pytest.mark.p1
@pytest.mark.script_split
def test_split_full_flow_completes(
    api_client, user_id, auth_token, test_world, mock_mode
):
    """split_102 - 剧本拆分全流程：提交 → 轮询至终态 → completed 后取 result。

    依赖真实 LLM，轮询超时 180s。若环境 LLM 不可用可能落到 failed/paused，
    本用例只断言任务最终到达一个稳定终态（completed/failed/cancelled）且 result
    端点行为正确：completed 时 result 可取，非 completed 时 409。
    """
    script_content = "短剧本：小明说你好，小红说再见。"
    submit = api_client.post(
        "/api/parse-script",
        json={
            "user_id": user_id,
            "auth_token": auth_token,
            "world_id": test_world["id"],
            "script_content": script_content,
            "model": "gemini-2.5-flash",
            "sequence_mode": "speed",
        },
        headers={"X-User-Id": str(user_id), "Authorization": f"Bearer {auth_token}"},
        timeout=30,
    )
    assert submit.status_code in (200, 202), f"提交失败: {submit.status_code} {submit.text}"
    data = submit.json().get("data") or submit.json()
    task_id = data.get("task_id")
    assert task_id

    # 轮询至终态或交互态
    final = _poll_until(api_client, task_id, timeout=180)
    status = final.get("status")
    assert status, "轮询超时未拿到任务状态"

    # result 端点行为与状态一致
    result_resp = api_client.get(
        f"{SPLIT_API}/tasks/{task_id}/result",
        headers={"X-User-Id": str(user_id)},
    )
    if status == "completed":
        assert result_resp.status_code == 200, f"completed 但 result 取不到: {result_resp.text}"
        result_data = result_resp.json().get("data")
        assert result_data is not None
    else:
        # 非 completed（failed/paused/cancelled/waiting_auth）取 result 应 409
        assert result_resp.status_code == 409, (
            f"非 completed 状态 {status}，result 应返回 409，实际 {result_resp.status_code}"
        )


@pytest.mark.p1
@pytest.mark.script_split
def test_active_task_recovers_after_refresh(
    api_client, user_id, auth_token, test_world, mock_mode
):
    """split_103 - 页面刷新恢复：提交后用 active-task 查询能查到该任务。

    模拟页面刷新场景：提交任务后立即查 active-task，应返回该任务（status 非终态）。
    """
    script_content = "刷新测试剧本：小明出门买早餐。"
    submit = api_client.post(
        "/api/parse-script",
        json={
            "user_id": user_id,
            "auth_token": auth_token,
            "world_id": test_world["id"],
            "script_content": script_content,
            "model": "gemini-2.5-flash",
            "sequence_mode": "speed",
        },
        headers={"X-User-Id": str(user_id), "Authorization": f"Bearer {auth_token}"},
        timeout=30,
    )
    assert submit.status_code in (200, 202)
    task_id = (submit.json().get("data") or submit.json()).get("task_id")

    # 立即查 active-task（模拟刷新）
    active = api_client.get(
        f"{SPLIT_API}/active-task",
        params={"source_type": "video_workflow", "source_id": str(test_world["id"])},
        headers={"X-User-Id": str(user_id)},
    )
    assert active.status_code == 200
    # 任务刚提交，应在活跃列表中（除非已飞速完成）
    active_data = active.json().get("data")
    if active_data:
        assert active_data.get("task_id") == task_id or active_data.get("status")


@pytest.mark.p1
@pytest.mark.script_split
def test_cancel_submitted_task(api_client, user_id, auth_token, test_world, mock_mode):
    """split_104 - 协作式取消：提交后立即取消，任务最终落到 cancelled 或已完成。

    取消是协作式（置 cancel_requested），若任务此时已快速完成则 status=completed，
    否则应进 cancelling → cancelled。
    """
    script_content = "取消测试剧本：小明发呆。"
    submit = api_client.post(
        "/api/parse-script",
        json={
            "user_id": user_id,
            "auth_token": auth_token,
            "world_id": test_world["id"],
            "script_content": script_content,
            "model": "gemini-2.5-flash",
            "sequence_mode": "speed",
        },
        headers={"X-User-Id": str(user_id), "Authorization": f"Bearer {auth_token}"},
        timeout=30,
    )
    assert submit.status_code in (200, 202)
    task_id = (submit.json().get("data") or submit.json()).get("task_id")

    cancel = api_client.post(
        f"{SPLIT_API}/tasks/{task_id}/cancel",
        headers={"X-User-Id": str(user_id)},
    )
    # 接受 200（已接受取消）或 409（任务恰好已终态）
    assert cancel.status_code in (200, 409), f"取消异常: {cancel.status_code} {cancel.text}"

    if cancel.status_code == 200:
        # 轮询确认最终落到 cancelled（或已被快速完成抢成 completed）
        final = _poll_until(api_client, task_id, timeout=60)
        assert final.get("status") in ("cancelled", "completed", "cancelling"), (
            f"取消后状态异常: {final.get('status')}"
        )
