"""
剧本编辑器 API 测试。
覆盖文件列表、同步、提交、模型列表等接口。
"""
import httpx
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


# ═══════════════════════════════════════════════════════════════
# 世界 Word 文档导出（2026-09 新增 /api/export-world-doc）
# ═══════════════════════════════════════════════════════════════


def _export(api_client, **params):
    return api_client.get("/api/export-world-doc", params=params)


@pytest.mark.script_writer
def test_export_world_doc_requires_login(base_url):
    """sw_api_exp_001 - 未登录导出 401（属主断言前置 require_permission）"""
    resp = httpx.get(
        f"{base_url}/api/export-world-doc",
        params={"user_id": "1", "world_id": "1"},
        timeout=15,
    )
    assert resp.status_code == 401
    assert resp.json().get("error_code") == "missing_auth_token"


@pytest.mark.script_writer
def test_export_world_doc_owner_mismatch(api_client, base_url, e2e_config, user_id):
    """sw_api_exp_002 - 用他人 token + 主账号 user_id 导出 403（防跨用户越权）

    必须用副账号 fresh token：本文件在 test_auth 之后执行，单会话策略
    （delete_by_user_id）已把 session 级 secondary_auth_token 顶掉（见
    test_auth.py::test_logout_success 同因说明），直接复用会 401。
    """
    creds = e2e_config["credentials"]["secondary"]
    login_resp = httpx.post(
        f"{base_url}/api/auth/login",
        json={"phone": creds["phone"], "password": creds["password"]},
        timeout=15,
    )
    assert login_resp.status_code == 200, f"副账号登录失败: {login_resp.text}"
    login_data = login_resp.json()
    token = (login_data.get("data") or login_data).get("token")
    assert token, f"登录响应缺 token: {login_data}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = api_client.get(
        "/api/export-world-doc",
        params={"user_id": str(user_id), "world_id": "1"},
        headers=headers,
    )
    assert resp.status_code == 403, f"跨用户导出应 403: {resp.status_code} {resp.text}"
    assert "user_id 与登录用户不一致" in resp.json().get("error", "")


@pytest.mark.script_writer
def test_export_world_doc_malformed_ids(api_client, user_id):
    """sw_api_exp_003 - 非数值 world_id 400（user_id 合法以先通过属主校验）"""
    resp = _export(api_client, user_id=str(user_id), world_id="xyz")
    assert resp.status_code == 400
    assert resp.json().get("error") == "user_id/world_id 格式错误"


@pytest.mark.script_writer
def test_export_world_doc_world_without_files(api_client, user_id, test_world):
    """sw_api_exp_004 - 空世界（无任何剧本/角色文件）导出 404"""
    resp = _export(api_client, user_id=str(user_id), world_id=str(test_world["id"]))
    assert resp.status_code == 404, f"空世界导出应 404: {resp.status_code} {resp.text}"
    assert resp.json().get("success") is False


@pytest.mark.script_writer
def test_export_world_doc_success(api_client, user_id):
    """sw_api_exp_005 - 有文件的世界导出 200 + download_url + .docx 文件名（best-effort）"""
    resp = api_client.get("/api/worlds")
    if resp.status_code != 200:
        pytest.skip(f"获取世界列表失败: {resp.status_code}")
    inner = resp.json().get("data", resp.json())
    worlds = inner.get("data", []) if isinstance(inner, dict) else inner
    # /api/worlds 按 id 倒序：最新世界多为空测试世界，老世界（id 小）才含文件。
    # 遍历全部（上限 15 控制成本）；空世界快速 404，仅含文件的世界才真正生成 docx
    for w in (worlds or [])[:15]:
        wid = w.get("id")
        if not wid:
            continue
        r = _export(api_client, user_id=str(user_id), world_id=str(wid))
        if r.status_code == 200:
            data = r.json()
            assert data.get("success") is True, f"导出响应异常: {data}"
            assert data.get("download_url"), f"缺下载链接: {data}"
            assert data.get("filename", "").endswith(".docx"), f"文件名应为 .docx: {data}"
            return
    pytest.skip("环境中没有含文件可导出的世界")


# ---------------------------------------------------------------------------
# 会话列表鉴权收紧 + task 404（34e987ce6）：跨用户会话枚举漏洞回归
# ---------------------------------------------------------------------------

@pytest.mark.script_writer
def test_session_list_cross_user_not_leaked(base_url, e2e_config, user_id):
    """sw_api_exp_003 - 副账号（不同登录身份）无法枚举主账号会话列表：
    会话列表鉴权已收紧为登录身份，body/params 里的他人 user_id 不得放行。"""
    creds = e2e_config["credentials"]["secondary"]
    login_resp = httpx.post(
        f"{base_url}/api/auth/login",
        json={"phone": creds["phone"], "password": creds["password"]},
        timeout=15,
    )
    assert login_resp.status_code == 200, f"副账号登录失败: {login_resp.text}"
    token = (login_resp.json().get("data") or login_resp.json()).get("token")
    assert token
    secondary_user_id = (login_resp.json().get("data") or login_resp.json()).get("user_id")

    resp = httpx.get(
        f"{base_url}/api/script-writer/sessions",
        params={"user_id": str(user_id)},  # 试图枚举主账号会话
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    # 收紧后只返回副账号自己的会话（不携带主账号数据）；任何形态的主账号
    # 会话泄露（200 + 他人 session）都算回归
    assert resp.status_code in (200, 401, 403), f"异常状态: {resp.status_code} {resp.text}"
    if resp.status_code == 200:
        data = resp.json()
        sessions = data.get("sessions") or data.get("data") or []
        for s in sessions if isinstance(sessions, list) else []:
            owner = str(s.get("user_id", ""))
            assert owner == "" or owner == str(secondary_user_id), \
                f"会话列表泄露他人会话: {s}"


@pytest.mark.script_writer
def test_task_status_404_for_unknown_task(api_client):
    """sw_api_exp_004 - 未知任务轮询返回 404 而非 500/挂死（前端据此触发
    自愈重建，vitest script_writer_session_404_self_heal 已测前端侧）。"""
    resp = api_client.get("/api/script-writer/task-status/nonexistent-task-id-xyz")
    assert resp.status_code == 404, f"未知任务应 404: {resp.status_code} {resp.text}"
