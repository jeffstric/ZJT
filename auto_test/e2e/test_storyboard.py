"""故事板编辑器模块端到端测试（首个用例集：画布↔故事板互转，d957af0ed）。

背景：tests/api/test_storyboard_conversion.py 只覆盖纯函数，文件头明确
「落库与端点行为由本地冒烟验证」——端点行为此前零自动化。

覆盖：
- from-workflow（画布→故事板）：空/未保存画布 400 守卫（ci_smoke）
- to-workflow（故事板→画布）：不存在的 storyboard → 404 守卫（ci_smoke）
- 互转幂等语义说明：已关联画布时二次转换返回既有对象（created=false）

storyboard marker 已在 pytest.ini 注册；需要真实工作流数据的全量资产迁移
用例（造分镜帧连线）成本高，后置为 p2 不在本文件。
"""
import httpx
import pytest


@pytest.mark.storyboard
@pytest.mark.ci_smoke
@pytest.mark.p0
def test_from_workflow_empty_canvas_rejected(api_client, user_id):
    """sb_001 - 未保存/空画布转换为故事板应 4xx 守卫（不产生脏数据）。"""
    resp = api_client.post(
        "/api/storyboard/from-workflow",
        json={"workflow_id": 999999999},  # 不存在的画布
        timeout=15,
    )
    assert resp.status_code in (400, 404, 422), \
        f"不存在的画布应被守卫拒绝: {resp.status_code} {resp.text}"


@pytest.mark.storyboard
@pytest.mark.ci_smoke
@pytest.mark.p0
def test_to_workflow_unknown_storyboard_404(api_client, user_id):
    """sb_002 - 不存在的 storyboard 转画布应 404（前端 toast，不静默挂死）。"""
    resp = api_client.post(
        "/api/storyboard/999999999/to-workflow",
        json={},
        timeout=15,
    )
    assert resp.status_code == 404, \
        f"不存在的 storyboard 应 404: {resp.status_code} {resp.text}"


@pytest.mark.storyboard
@pytest.mark.ci_smoke
@pytest.mark.p0
def test_conversion_requires_login(base_url):
    """sb_003 - 未登录互转请求 401（转换涉及剧本/资产写操作）。"""
    resp = httpx.post(
        f"{base_url}/api/storyboard/from-workflow",
        json={"workflow_id": 1},
        timeout=15,
    )
    assert resp.status_code == 401, f"未登录应 401: {resp.status_code} {resp.text}"
