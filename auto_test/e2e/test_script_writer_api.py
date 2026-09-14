"""
剧本编辑器 API 测试。
覆盖文件列表、同步、提交、模型列表等接口。
"""
import pytest


@pytest.mark.marketing_agent
@pytest.mark.script_writer
def test_api_get_models(api_client):
    """sw_api_008 - GET /api/models 返回模型列表"""
    resp = api_client.get("/api/models")
    assert resp.status_code == 200, f"获取模型列表失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("success") is True, f"响应异常: {data}"
    models = data.get("models", [])
    assert isinstance(models, list), f"models 应为列表: {data}"
    assert len(models) > 0, "模型列表不应为空"
    # commit 1619353a：/api/models 的 id 已统一为数值库 ID 字符串，
    # 不再对本地服务供应商（ollama/vllm）下发 "vendor:模型名" 复合串
    for m in models:
        mid = m.get("id")
        assert isinstance(mid, str) and mid, f"模型 id 应为非空字符串: {m}"
        assert ":" not in mid, f"模型 id 不应再为复合串: {m}"
        assert mid.isdigit(), f"模型 id 应为数值库 ID 字符串: {m}"
    # 前端模型记忆契约 {model, model_id, vendor_id}（commit e4d54994）所需字段
    for m in models:
        assert m.get("name") is not None, f"模型条目缺模型名: {m}"
        assert "vendor_id" in m and m["vendor_id"] is not None, f"模型条目缺 vendor_id: {m}"


@pytest.mark.marketing_agent
@pytest.mark.script_writer
def test_api_get_vendors(api_client):
    """sw_api_009 - GET /api/vendors 返回供应商列表"""
    resp = api_client.get("/api/vendors")
    assert resp.status_code == 200, f"获取供应商列表失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("success") is True, f"响应异常: {data}"


@pytest.mark.marketing_agent
@pytest.mark.script_writer
def test_api_get_scripts_files(api_client, user_id, auth_token, test_world):
    """sw_api_001 - GET /api/scripts-files 返回剧本文件列表"""
    world_id = test_world["id"]
    resp = api_client.get(
        "/api/scripts-files",
        params={
            "user_id": str(user_id),
            "world_id": str(world_id),
            "auth_token": auth_token,
            "raw_json": "true",
        },
    )
    assert resp.status_code == 200, f"获取剧本文件失败: {resp.status_code} {resp.text}"


@pytest.mark.marketing_agent
@pytest.mark.script_writer
def test_api_get_characters_files(api_client, user_id, auth_token, test_world):
    """sw_api_002 - GET /api/characters-files 返回角色文件列表"""
    world_id = test_world["id"]
    resp = api_client.get(
        "/api/characters-files",
        params={
            "user_id": str(user_id),
            "world_id": str(world_id),
            "auth_token": auth_token,
            "raw_json": "true",
        },
    )
    assert resp.status_code == 200, f"获取角色文件失败: {resp.status_code} {resp.text}"


@pytest.mark.marketing_agent
@pytest.mark.script_writer
def test_api_get_locations_files(api_client, user_id, auth_token, test_world):
    """sw_api_003 - GET /api/locations-files 返回场景文件列表"""
    world_id = test_world["id"]
    resp = api_client.get(
        "/api/locations-files",
        params={
            "user_id": str(user_id),
            "world_id": str(world_id),
            "auth_token": auth_token,
            "raw_json": "true",
        },
    )
    assert resp.status_code == 200, f"获取场景文件失败: {resp.status_code} {resp.text}"


@pytest.mark.marketing_agent
@pytest.mark.script_writer
def test_api_get_props_files(api_client, user_id, auth_token, test_world):
    """sw_api_004 - GET /api/props-files 返回道具文件列表"""
    world_id = test_world["id"]
    resp = api_client.get(
        "/api/props-files",
        params={
            "user_id": str(user_id),
            "world_id": str(world_id),
            "auth_token": auth_token,
            "raw_json": "true",
        },
    )
    assert resp.status_code == 200, f"获取道具文件失败: {resp.status_code} {resp.text}"


@pytest.mark.marketing_agent
@pytest.mark.script_writer
def test_api_get_worlds_list(api_client):
    """sw_api_005 - GET /api/worlds 返回世界列表"""
    resp = api_client.get("/api/worlds", params={"page": 1, "page_size": 100})
    assert resp.status_code == 200, f"获取世界列表失败: {resp.status_code} {resp.text}"
    data = resp.json()
    inner = data.get("data", data)
    if isinstance(inner, dict):
        items = inner.get("data", [])
    else:
        items = inner
    assert isinstance(items, list), f"返回数据格式异常: {data}"


@pytest.mark.marketing_agent
@pytest.mark.script_writer
def test_api_sync_files(api_client, user_id, auth_token, test_world):
    """sw_api_006 - POST /api/sync-files 同步文件"""
    world_id = test_world["id"]
    resp = api_client.post(
        "/api/sync-files",
        json={
            "user_id": str(user_id),
            "world_id": str(world_id),
            "auth_token": auth_token,
        },
    )
    # 同步可能返回 200 或 204
    assert resp.status_code in (200, 201, 204), (
        f"同步文件失败: {resp.status_code} {resp.text}"
    )


@pytest.mark.marketing_agent
@pytest.mark.script_writer
def test_api_submit_to_database(api_client, user_id, auth_token, test_world):
    """sw_api_007 - POST /api/submit-to-database 提交数据"""
    world_id = test_world["id"]
    resp = api_client.post(
        "/api/submit-to-database",
        json={
            "user_id": str(user_id),
            "world_id": str(world_id),
            "auth_token": auth_token,
        },
    )
    # 提交可能成功或因无数据返回空结果
    assert resp.status_code in (200, 201, 204, 400), (
        f"提交数据: {resp.status_code} {resp.text}"
    )


@pytest.mark.marketing_agent
@pytest.mark.script_writer
def test_api_text_to_image_models(api_client):
    """验证 GET /api/text-to-image-models 返回生图模型列表"""
    resp = api_client.get("/api/text-to-image-models")
    assert resp.status_code == 200, f"获取生图模型失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("success") is True, f"响应异常: {data}"


@pytest.mark.marketing_agent
@pytest.mark.script_writer
def test_api_computing_power_config(api_client):
    """验证 GET /api/computing-power-config 返回算力配置"""
    resp = api_client.get("/api/computing-power-config")
    assert resp.status_code == 200, f"获取算力配置失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("success") is True, f"响应异常: {data}"


@pytest.mark.marketing_agent
@pytest.mark.script_writer
def test_api_edition(api_client):
    """验证 GET /api/edition 返回版本信息"""
    resp = api_client.get("/api/edition")
    assert resp.status_code == 200, f"获取版本信息失败: {resp.status_code} {resp.text}"


@pytest.mark.marketing_agent
@pytest.mark.script_writer
def test_api_task_configs(api_client):
    """验证 GET /api/system/task-configs 返回任务配置"""
    resp = api_client.get("/api/system/task-configs")
    assert resp.status_code == 200, f"获取任务配置失败: {resp.status_code} {resp.text}"
