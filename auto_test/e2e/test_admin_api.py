"""
管理后台 API 测试。
覆盖仪表盘、用户管理、系统配置、实现方管理、通知等接口。
"""
import pytest


# ═══════════════════════════════════════════════════════════════
# 仪表盘 API
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
def test_api_admin_dashboard(api_client):
    """admin_api_001 - GET /api/admin/dashboard 返回仪表盘数据"""
    resp = api_client.get("/api/admin/dashboard")
    assert resp.status_code == 200, f"获取仪表盘失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"响应异常: {data}"
    assert "total_users" in data.get("data", {}), "应包含 total_users"


@pytest.mark.admin
def test_api_admin_monthly_active_users(api_client):
    """admin_api_002 - GET /api/admin/dashboard/monthly-active-users"""
    resp = api_client.get("/api/admin/dashboard/monthly-active-users")
    assert resp.status_code == 200, f"获取月活用户失败: {resp.status_code} {resp.text}"


@pytest.mark.admin
def test_api_admin_model_analysis(api_client):
    """admin_api_003 - GET /api/admin/dashboard/model-analysis"""
    resp = api_client.get("/api/admin/dashboard/model-analysis", params={"days": 7})
    assert resp.status_code == 200, f"获取模型分析失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"响应异常: {data}"


# ═══════════════════════════════════════════════════════════════
# 用户管理 API
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
def test_api_admin_list_users(api_client):
    """admin_api_004 - GET /api/admin/users 返回用户列表"""
    resp = api_client.get("/api/admin/users", params={"page": 1, "page_size": 10})
    assert resp.status_code == 200, f"获取用户列表失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"响应异常: {data}"
    users = data.get("data", {}).get("users", [])
    assert isinstance(users, list), "users 应为列表"


@pytest.mark.admin
def test_api_admin_list_users_with_filter(api_client):
    """admin_api_005 - GET /api/admin/users 带筛选参数"""
    resp = api_client.get(
        "/api/admin/users",
        params={"page": 1, "page_size": 10, "status": "1", "role": "admin"},
    )
    assert resp.status_code == 200, f"筛选用户失败: {resp.status_code} {resp.text}"


@pytest.mark.admin
def test_api_admin_get_user_detail(api_client, user_id):
    """admin_api_006 - GET /api/admin/users/{user_id} 返回用户详情"""
    resp = api_client.get(f"/api/admin/users/{user_id}")
    assert resp.status_code == 200, f"获取用户详情失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"响应异常: {data}"
    user = data.get("data", {})
    assert user.get("user_id"), "应包含 user_id"


@pytest.mark.admin
def test_api_admin_adjust_user_power(api_client, user_id):
    """admin_api_007 - POST /api/admin/users/{user_id}/power 调整算力"""
    resp = api_client.post(
        f"/api/admin/users/{user_id}/power",
        json={"amount": 0, "reason": "E2E测试调整"},
    )
    # 0 调整可能返回 200 或 400
    assert resp.status_code in (200, 400), f"调整算力: {resp.status_code} {resp.text}"


@pytest.mark.admin
def test_api_admin_update_user_role_noop(api_client, user_id):
    """admin_api_008 - PUT /api/admin/users/{user_id}/role 设置相同角色"""
    resp = api_client.put(
        f"/api/admin/users/{user_id}/role",
        json={"role": "admin"},
    )
    assert resp.status_code == 200, f"更新角色失败: {resp.status_code} {resp.text}"


# ═══════════════════════════════════════════════════════════════
# 系统配置 API
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
def test_api_admin_list_configs(api_client):
    """admin_api_009 - GET /api/admin/config 返回配置列表"""
    resp = api_client.get("/api/admin/config", params={"page": 1, "page_size": 10})
    assert resp.status_code == 200, f"获取配置列表失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"响应异常: {data}"


@pytest.mark.admin
def test_api_admin_get_config_detail(api_client):
    """admin_api_010 - GET /api/admin/config/{config_key} 获取单个配置"""
    # 先获取配置列表找到一个 key
    resp = api_client.get("/api/admin/config", params={"page": 1, "page_size": 1})
    data = resp.json()
    configs = data.get("data", {}).get("configs", [])
    if not configs:
        pytest.skip("没有配置数据")

    key = configs[0]["config_key"]
    resp2 = api_client.get(f"/api/admin/config/{key}")
    assert resp2.status_code == 200, f"获取配置详情失败: {resp2.status_code} {resp2.text}"


@pytest.mark.admin
def test_api_admin_config_reload(api_client):
    """admin_api_011 - POST /api/admin/config/reload 重载配置"""
    resp = api_client.post("/api/admin/config/reload")
    assert resp.status_code == 200, f"重载配置失败: {resp.status_code} {resp.text}"


@pytest.mark.admin
def test_api_admin_quick_configs(api_client):
    """admin_api_012 - GET /api/admin/config/quick-configs 获取快速配置"""
    resp = api_client.get("/api/admin/config/quick-configs")
    assert resp.status_code == 200, f"获取快速配置失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"响应异常: {data}"


@pytest.mark.admin
def test_api_admin_config_history(api_client):
    """admin_api_013 - GET /api/admin/config-history 配置历史"""
    resp = api_client.get("/api/admin/config-history", params={"page": 1, "page_size": 10})
    assert resp.status_code == 200, f"获取配置历史失败: {resp.status_code} {resp.text}"


# ═══════════════════════════════════════════════════════════════
# 实现方管理 API
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
def test_api_admin_implementation_configs(api_client):
    """admin_api_014 - GET /api/admin/implementation-configs 获取实现方配置"""
    resp = api_client.get("/api/admin/implementation-configs")
    assert resp.status_code == 200, f"获取实现方配置失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"响应异常: {data}"


@pytest.mark.admin
def test_api_admin_implementation_powers(api_client):
    """admin_api_015 - GET /api/admin/implementation-powers 获取算力配置"""
    resp = api_client.get("/api/admin/implementation-powers")
    assert resp.status_code == 200, f"获取算力配置失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"响应异常: {data}"


# ═══════════════════════════════════════════════════════════════
# 通知 API
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
def test_api_admin_notifications(api_client):
    """admin_api_016 - GET /api/notifications/admin/list 获取通知列表"""
    resp = api_client.get("/api/notifications/admin/list", params={"page": 1, "page_size": 10})
    assert resp.status_code == 200, f"获取通知列表失败: {resp.status_code} {resp.text}"


# ═══════════════════════════════════════════════════════════════
# 签到配置 API
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
def test_api_admin_checkin_config(api_client):
    """admin_api_017 - 签到配置读取（通过系统配置接口）"""
    resp = api_client.get(
        "/api/admin/config",
        params={"keyword": "checkin", "page": 1, "page_size": 10},
    )
    assert resp.status_code == 200, f"获取签到配置失败: {resp.status_code} {resp.text}"


# ═══════════════════════════════════════════════════════════════
# 版本信息 API
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
def test_api_admin_edition(api_client):
    """admin_api_018 - GET /api/edition 获取版本信息"""
    resp = api_client.get("/api/edition")
    assert resp.status_code == 200, f"获取版本信息失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"响应异常: {data}"


# ═══════════════════════════════════════════════════════════════
# 推荐模型档位 API（commit d6e57884：管理员可配场景推荐模型）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.admin
def test_api_admin_model_recos_get(api_client):
    """admin_api_019 - GET /api/admin/model-recos 返回各场景双档推荐+候选"""
    resp = api_client.get("/api/admin/model-recos")
    assert resp.status_code == 200, f"获取推荐模型档位失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"响应异常: {data}"
    scenes = data.get("data", {}).get("scenes", [])
    assert isinstance(scenes, list) and len(scenes) > 0, f"scenes 不应为空: {data}"
    for s in scenes:
        assert s.get("scene"), f"scene 缺少场景标识: {s}"
        assert "value" in s and "quality" in s, f"scene 应含 value/quality 双档: {s}"
        assert "overridden" in s and "candidates" in s, f"scene 应含 overridden/candidates: {s}"


@pytest.mark.admin
def test_api_admin_model_recos_reset_roundtrip(api_client):
    """admin_api_020 - PUT /api/admin/model-recos reset 回退代码默认（净变更为零）"""
    data = api_client.get("/api/admin/model-recos").json()
    assert data.get("code") == 0
    scenes = data.get("data", {}).get("scenes", [])
    assert scenes, "scenes 不应为空"
    scene = scenes[0]["scene"]

    resp = api_client.put("/api/admin/model-recos", json={"scene": scene, "reset": True})
    assert resp.status_code == 200, f"reset 推荐档位失败: {resp.status_code} {resp.text}"
    assert resp.json().get("code") == 0, f"reset 业务失败: {resp.text}"

    # 非法场景应 400
    resp = api_client.put(
        "/api/admin/model-recos", json={"scene": "not_a_scene", "reset": True}
    )
    assert resp.status_code == 400, f"未知场景应 400，实际 {resp.status_code}"
