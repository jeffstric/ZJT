"""
E2E 测试核心 fixtures。
提供浏览器、认证、API 客户端、测试数据工厂等 fixtures。
"""
import json
import os
import re
import sys
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright

# 将项目根目录加入 sys.path
AUTO_TEST_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = AUTO_TEST_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 将 helpers 目录加入 sys.path
HELPERS_DIR = Path(__file__).resolve().parent / "helpers"
sys.path.insert(0, str(HELPERS_DIR))

from helpers.page_objects import (
    AdminPage,
    IndexPage,
    MarketingAgentPage,
    ScriptWriterPage,
    WorkflowEditorPage,
    WorkflowListPage,
)


# ──────────────────────────── 辅助函数 ────────────────────────────


def extract_id(data: dict, id_type: str = None) -> str:
    """从响应数据中提取 ID，兼容多种字段名

    Args:
        data: 响应数据
        id_type: 指定 ID 类型 ("world", "character", "location", "workflow", "session")
    """
    # 如果指定了类型，优先返回对应的 ID
    type_field_map = {
        "world": "world_id",
        "character": "character_id",
        "location": "location_id",
        "workflow": "workflow_id",
        "session": "session_id",
    }

    if id_type and id_type in type_field_map:
        field = type_field_map[id_type]
        if field in data:
            return data[field]
        if "data" in data and isinstance(data["data"], dict) and field in data["data"]:
            return data["data"][field]

    # 通用提取
    return (
        data.get("id")
        or data.get("data", {}).get("id")
        or data.get("session_id")
        or data.get("world_id")
        or data.get("character_id")
        or data.get("location_id")
        or data.get("workflow_id")
        or data.get("data", {}).get("session_id")
        or ""
    )


def get_worlds_list(api_client) -> list:
    """获取世界列表"""
    resp = api_client.get("/api/worlds")
    if resp.status_code != 200:
        return []
    data = resp.json()
    # 响应格式: {"code": 0, "data": {"data": [...], "total": ...}}
    inner = data.get("data", data)
    if isinstance(inner, dict):
        return inner.get("data", [])
    return inner if isinstance(inner, list) else []


def _skip_or_fail(message: str):
    """本地缺少外部环境时允许跳过；CI 必须失败，避免产生假绿。"""
    if os.getenv("E2E_STRICT", "").lower() in {"1", "true", "yes"}:
        pytest.fail(message)
    pytest.skip(message)


# ──────────────────────────── 配置 ────────────────────────────


@pytest.fixture(scope="session")
def e2e_config():
    """读取本地配置，并允许 CI 通过环境变量覆盖。

    CI 使用临时数据库中的一次性账号，不需要生成或提交 test_config.json。
    """
    config_path = AUTO_TEST_DIR / "test_config.json"
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    base_url = os.getenv("E2E_BASE_URL") or config.get("base_url")
    if not base_url:
        _skip_or_fail("未配置 E2E_BASE_URL，且本地 test_config.json 不存在或缺少 base_url")
    config["base_url"] = base_url

    credentials = config.setdefault("credentials", {})
    credential_envs = {
        "primary": ("E2E_TEST_PHONE", "E2E_TEST_PASSWORD"),
        "secondary": ("E2E_SECONDARY_PHONE", "E2E_SECONDARY_PASSWORD"),
    }
    for credential_name, (phone_env, password_env) in credential_envs.items():
        phone = os.getenv(phone_env)
        password = os.getenv(password_env)
        if phone or password:
            credentials[credential_name] = {
                "phone": phone or "",
                "password": password or "",
            }

    asset_dir_override = os.getenv("E2E_TEST_ASSET_DIR")
    asset_dir = Path(asset_dir_override or str(AUTO_TEST_DIR / "test_assets"))
    test_assets = config.setdefault("test_assets", {})
    asset_paths = {
        "test_image": str(asset_dir / "test_image.jpg"),
        "test_video": str(asset_dir / "test_video.mp4"),
        "test_voice": str(asset_dir / "test_voice.wav"),
    }
    for asset_name, asset_path in asset_paths.items():
        if asset_dir_override:
            test_assets[asset_name] = asset_path
        else:
            test_assets.setdefault(asset_name, asset_path)
    return config


@pytest.fixture(scope="session")
def base_url(e2e_config):
    """服务器基础 URL"""
    return e2e_config["base_url"].rstrip("/")


# ──────────────────────────── 认证 ────────────────────────────


def _login_with_credentials(e2e_config, base_url, credential_name):
    """使用指定账号登录；每个账号在整轮测试中只能调用一次。"""
    creds = e2e_config.get("credentials", {}).get(credential_name, {})
    if not creds.get("phone") or not creds.get("password"):
        _skip_or_fail(f"未配置 E2E {credential_name} 测试账号")
    try:
        resp = httpx.post(
            f"{base_url}/api/auth/login",
            json={"phone": creds["phone"], "password": creds["password"]},
            timeout=10,
        )
    except (httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout) as e:
        _skip_or_fail(f"服务器不可用: {e}")
    if resp.status_code != 200:
        _skip_or_fail(f"登录失败，状态码: {resp.status_code}, 响应: {resp.text}")
    data = resp.json()
    inner = data.get("data", data)
    token = inner.get("token") or data.get("token") or data.get("access_token")
    uid = inner.get("user_id") or data.get("user_id")
    if not token:
        _skip_or_fail(f"登录响应中未找到 token: {data}")
    if not uid:
        _skip_or_fail(f"登录响应中未找到 user_id: {data}")
    return {"token": token, "user_id": str(uid)}


@pytest.fixture(scope="session")
def _login_data(e2e_config, base_url):
    """主账号认证信息：session 期间只登录一次。"""
    return _login_with_credentials(e2e_config, base_url, "primary")


@pytest.fixture(scope="session")
def _secondary_login_data(e2e_config, base_url):
    """次账号认证信息：供登出等破坏 token 的测试独立使用。"""
    return _login_with_credentials(e2e_config, base_url, "secondary")


@pytest.fixture(scope="session")
def auth_token(_login_data):
    """通过 API 登录获取 token（session scope，只登录一次）"""
    return _login_data["token"]


@pytest.fixture(scope="session")
def user_id(_login_data):
    """通过 API 登录获取 user_id"""
    return _login_data["user_id"]


@pytest.fixture(scope="session")
def secondary_auth_token(_secondary_login_data):
    return _secondary_login_data["token"]


@pytest.fixture(scope="session")
def secondary_user_id(_secondary_login_data):
    return _secondary_login_data["user_id"]


@pytest.fixture(scope="session")
def auth_headers(auth_token, user_id):
    """构造认证 headers"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "X-User-Id": str(user_id),
    }


def refresh_login(e2e_config, base_url):
    """重新登录获取新 token（当 token 失效时使用）"""
    creds = e2e_config["credentials"]["primary"]
    resp = httpx.post(
        f"{base_url}/api/auth/login",
        json={"phone": creds["phone"], "password": creds["password"]},
        timeout=10,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    inner = data.get("data", data)
    token = inner.get("token") or data.get("token") or data.get("access_token")
    uid = inner.get("user_id") or data.get("user_id")
    if token and uid:
        return {"token": token, "user_id": str(uid)}
    return None


@pytest.fixture
def api_client_with_refresh(base_url, auth_headers, e2e_config):
    """httpx API 客户端，支持 token 失效时自动刷新"""
    import time

    client = httpx.Client(
        base_url=base_url,
        headers=auth_headers,
        timeout=httpx.Timeout(10.0),
    )
    yield client
    client.close()


# ──────────────────────────── 浏览器 ────────────────────────────


@pytest.fixture(scope="session")
def browser():
    """Playwright chromium 浏览器实例（CI 使用无头模式且关闭 slow_mo）。"""
    is_ci = os.getenv("CI", "").lower() in {"1", "true", "yes"}
    launch_options = {
        "headless": is_ci,
        "slow_mo": 0 if is_ci else 500,
    }
    browser_executable = os.getenv("E2E_BROWSER_EXECUTABLE")
    if browser_executable:
        executable_path = Path(browser_executable)
        if not executable_path.is_file():
            pytest.fail(
                f"E2E_BROWSER_EXECUTABLE 指向的浏览器不存在: {executable_path}"
            )
        launch_options["executable_path"] = str(executable_path)
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_options)
        yield browser
        browser.close()


@pytest.fixture
def browser_context(browser, auth_token, user_id, base_url, request):
    """浏览器上下文，注入 localStorage 认证信息"""
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        locale="zh-CN",
    )
    results_dir = os.getenv("E2E_RESULTS_DIR")
    if results_dir:
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
    # 注入 localStorage 认证信息，跳过 UI 登录
    context.add_init_script(f"""
        localStorage.setItem('auth_token', '{auth_token}');
        localStorage.setItem('user_id', '{user_id}');
    """)
    yield context
    if results_dir:
        try:
            trace_path = None
            report = getattr(request.node, "rep_call", None)
            if report and report.failed:
                trace_path = _artifact_path(
                    request.node.nodeid,
                    results_dir,
                    "trace.zip",
                )
            context.tracing.stop(path=trace_path)
        except Exception as e:
            print(f"[e2e artifacts] 保存 Trace 失败: {e}")
    context.close()


@pytest.fixture
def page(browser_context, request):
    """每个测试独立的页面实例"""
    p = browser_context.new_page()
    yield p
    results_dir = os.getenv("E2E_RESULTS_DIR")
    report = getattr(request.node, "rep_call", None)
    if results_dir and report and report.failed:
        try:
            screenshot_path = _artifact_path(
                request.node.nodeid,
                results_dir,
                "failure.png",
            )
            p.screenshot(path=screenshot_path, full_page=True)
        except Exception as e:
            print(f"[e2e artifacts] 保存失败截图失败: {e}")
    p.close()


def _artifact_path(nodeid: str, results_dir: str, filename: str) -> str:
    safe_nodeid = re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid).strip("_")
    artifact_dir = Path(results_dir) / safe_nodeid
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return str(artifact_dir / filename)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """把执行结果暴露给 fixture teardown，以便仅在失败时保存产物。"""
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture
def editor_page(browser, auth_token, user_id, base_url):
    """工作流编辑器专用页面，已注入认证信息。

    复用 session-scoped browser 实例，避免创建多个 sync_playwright 上下文导致 asyncio 冲突。
    通过 add_init_script 在页面脚本运行前注入 localStorage。
    """
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        locale="zh-CN",
    )
    # 在页面脚本运行前注入认证信息
    context.add_init_script(f"""
        localStorage.setItem('auth_token', '{auth_token}');
        localStorage.setItem('user_id', '{user_id}');
    """)
    page = context.new_page()

    yield page
    page.close()
    context.close()


# ──────────────────────────── API 客户端 ────────────────────────────


@pytest.fixture
def api_client(base_url, auth_headers):
    """httpx 异步 API 客户端（非阻塞）"""
    client = httpx.Client(
        base_url=base_url,
        headers=auth_headers,
        timeout=httpx.Timeout(10.0),
    )
    yield client
    client.close()


# ──────────────────────────── Page Objects ────────────────────────────


@pytest.fixture
def index_page(page, base_url):
    return IndexPage(page, base_url)


@pytest.fixture
def script_writer_page(page, base_url):
    return ScriptWriterPage(page, base_url)


@pytest.fixture
def sw_page(browser, auth_token, user_id, base_url, api_client):
    """剧本编辑器专用页面，URL 带 user_id 和 world_id。

    复用 session-scoped browser，注入认证信息，
    并自动获取 world_id 传入 URL 参数。
    """
    # 获取 world_id
    worlds_resp = api_client.get("/api/worlds")
    worlds_data = worlds_resp.json()
    inner = worlds_data.get("data", worlds_data)
    worlds = inner.get("data", []) if isinstance(inner, dict) else inner
    world_id = str(worlds[0]["id"]) if worlds else "1"

    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        locale="zh-CN",
    )
    context.add_init_script(f"""
        localStorage.setItem('auth_token', '{auth_token}');
        localStorage.setItem('user_id', '{user_id}');
    """)
    p = context.new_page()
    # 拦截算力 API 防止重定向到登录页
    import json as _json
    def _power_handler(route):
        route.fulfill(
            status=200, content_type="application/json",
            body=_json.dumps({"success": True, "data": {"computing_power": 9999}}),
        )
    p.route("**/api/user/computing_power", _power_handler)
    page_obj = ScriptWriterPage(p, base_url)
    # 将 world_id 附加到 page_obj 供测试使用
    page_obj.world_id = world_id
    page_obj.user_id = str(user_id)
    page_obj.auth_token = auth_token
    yield page_obj
    p.close()
    context.close()


@pytest.fixture
def workflow_list_page(page, base_url):
    return WorkflowListPage(page, base_url)


@pytest.fixture
def workflow_editor_page(page, base_url):
    return WorkflowEditorPage(page, base_url)


@pytest.fixture
def marketing_agent_page(page, base_url):
    return MarketingAgentPage(page, base_url)


@pytest.fixture
def admin_page(page, base_url):
    return AdminPage(page, base_url)


@pytest.fixture
def admin_browser_page(browser, auth_token, user_id, base_url):
    """管理后台专用页面，注入认证信息并 mock 所有 admin API。

    admin.js 使用 axios + Bearer token 认证，但 pytest 环境下
    add_init_script 的 token 在页面 API 调用时可能尚未就绪，
    导致 401 重定向。通过 page.route() mock 所有 admin API 绕过此问题。
    """
    import json as _json

    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        locale="zh-CN",
    )
    context.add_init_script(f"""
        localStorage.setItem('auth_token', '{auth_token}');
        localStorage.setItem('user_id', '{user_id}');
        localStorage.setItem('phone', '15088613226');
    """)
    p = context.new_page()

    # Mock 所有 admin API 端点
    def _mock_admin_api(route):
        url = route.request.url
        path = url.split(base_url)[-1].split("?")[0] if base_url in url else url

        mock_responses = {
            "/api/admin/dashboard": {
                "code": 0,
                "data": {
                    "total_users": 100,
                    "active_workflows_3d": 5,
                    "is_community_edition": False,
                },
            },
            "/api/admin/dashboard/monthly-active-users": {
                "code": 0,
                "data": {"monthly_active_users": 50},
            },
            "/api/admin/dashboard/model-analysis": {
                "code": 0,
                "data": {
                    "models": [
                        {"model_name": "gpt-4", "total": 100, "success": 95},
                        {"model_name": "claude-3", "total": 80, "success": 78},
                    ]
                },
            },
            "/api/admin/users": {
                "code": 0,
                "data": {
                    "data": [
                        {
                            "user_id": "1",
                            "phone": "15088613226",
                            "nickname": "测试用户",
                            "role": "admin",
                            "status": 1,
                            "computing_power": 9999,
                            "create_at": "2025-01-01",
                        },
                        {
                            "user_id": "2",
                            "phone": "13800138000",
                            "nickname": "普通用户",
                            "role": "user",
                            "status": 1,
                            "computing_power": 100,
                            "create_at": "2025-01-02",
                        },
                    ],
                    "total": 2,
                },
            },
            "/api/admin/config": {
                "code": 0,
                "data": {
                    "data": [
                        {
                            "config_key": "llm_model",
                            "config_value": "gpt-4",
                            "description": "LLM模型",
                            "is_public": True,
                            "editable": True,
                            "value_type": "str",
                        },
                        {
                            "config_key": "max_tokens",
                            "config_value": "4096",
                            "description": "最大token数",
                            "is_public": True,
                            "editable": True,
                            "value_type": "int",
                        },
                    ],
                    "total": 2,
                },
            },
            "/api/admin/config/quick-configs": {
                "code": 0,
                "data": {},
            },
            "/api/admin/config/raw": {
                "code": 0,
                "data": {},
            },
            "/api/admin/implementation-configs": {
                "code": 0,
                "data": [
                    {
                        "group_name": "text_to_image",
                        "implementations": [
                            {
                                "id": 1,
                                "name": "sd-webui",
                                "sort_order": 1,
                                "power_cost": 10,
                            }
                        ],
                    }
                ],
            },
            "/api/admin/implementation-powers": {
                "code": 0,
                "data": {"powers": []},
            },
            "/api/notifications/poll": {"code": 0, "data": {"notifications": [], "unread_count": 0, "version_update": None, "missing_binaries": []}},
            "/api/notifications/admin/list": {
                "code": 0,
                "data": {"notifications": [], "total": 0},
            },
            "/api/system/server-config": {"code": 0, "data": {}},
        }

        # 匹配路径
        for api_path, resp_data in mock_responses.items():
            if path == api_path or path.startswith(api_path + "/"):
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=_json.dumps(resp_data),
                )
                return

        # 用户详情等动态路径
        if path.startswith("/api/admin/users/") and "/power" in path:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"code": 0, "data": {}}),
            )
            return
        if path.startswith("/api/admin/users/") and "/role" in path:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"code": 0, "data": {}}),
            )
            return
        if path.startswith("/api/admin/users/") and "/status" in path:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"code": 0, "data": {}}),
            )
            return
        if path.startswith("/api/admin/users/"):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "user_id": "1",
                            "phone": "15088613226",
                            "nickname": "测试用户",
                            "role": "admin",
                            "status": 1,
                            "computing_power": 9999,
                        },
                    }
                ),
            )
            return

        # 配置详情
        if path.startswith("/api/admin/config/") and path != "/api/admin/config":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "config_key": "test_key",
                            "config_value": "test_value",
                        },
                    }
                ),
            )
            return

        # 其他 admin API 默认返回成功
        if "/api/admin/" in path or "/api/notifications/" in path:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"code": 0, "data": {}}),
            )
            return

        # 非 admin API 放行
        route.continue_()

    p.route("**/api/**", _mock_admin_api)

    page_obj = AdminPage(p, base_url)
    page_obj.user_id = str(user_id)
    page_obj.auth_token = auth_token
    yield page_obj
    p.close()
    context.close()


# ──────────────────────────── 测试数据工厂 ────────────────────────────


@pytest.fixture
def test_world(api_client):
    """创建测试世界，测试后清理"""
    resp = api_client.post(
        "/api/worlds",
        json={"name": "E2E测试世界", "description": "自动化测试创建的世界"},
    )
    if resp.status_code not in (200, 201):
        pytest.fail(f"创建测试世界失败: {resp.status_code} {resp.text}")
    data = resp.json()
    world_id = extract_id(data, "world")
    yield {"id": world_id, "data": data}
    # 清理
    try:
        api_client.delete(f"/api/worlds/{world_id}")
    except Exception:
        pass


@pytest.fixture
def test_character(api_client, test_world):
    """创建测试角色，测试后清理"""
    resp = api_client.post(
        "/api/characters",
        data={
            "world_id": test_world["id"],
            "name": "E2E测试角色",
        },
    )
    if resp.status_code not in (200, 201):
        pytest.fail(f"创建测试角色失败: {resp.status_code} {resp.text}")
    data = resp.json()
    char_id = extract_id(data, "character")
    yield {"id": char_id, "data": data}
    try:
        api_client.delete(f"/api/characters/{char_id}")
    except Exception:
        pass


@pytest.fixture
def test_location(api_client, test_world):
    """创建测试场景，测试后清理"""
    resp = api_client.post(
        "/api/locations",
        data={
            "world_id": test_world["id"],
            "name": "E2E测试场景",
        },
    )
    if resp.status_code not in (200, 201):
        pytest.fail(f"创建测试场景失败: {resp.status_code} {resp.text}")
    data = resp.json()
    loc_id = extract_id(data, "location")
    yield {"id": loc_id, "data": data}
    try:
        api_client.delete(f"/api/locations/{loc_id}")
    except Exception:
        pass


@pytest.fixture
def test_workflow(api_client):
    """创建测试工作流，测试后清理"""
    resp = api_client.post(
        "/api/video-workflow/create",
        json={"name": "E2E测试工作流", "description": "自动化测试创建的工作流"},
    )
    if resp.status_code not in (200, 201):
        pytest.fail(f"创建测试工作流失败: {resp.status_code} {resp.text}")
    data = resp.json()
    wf_id = extract_id(data, "workflow")
    yield {"id": wf_id, "data": data}
    try:
        api_client.delete(f"/api/video-workflow/{wf_id}")
    except Exception:
        pass


@pytest.fixture
def test_session_id(api_client, auth_token, user_id):
    """创建测试会话，测试后清理"""
    # 先获取一个世界 ID
    worlds = get_worlds_list(api_client)
    world_id = worlds[0]["id"] if worlds else "1"

    resp = api_client.post(
        "/api/session/create",
        json={
            "user_id": str(user_id),
            "world_id": str(world_id),
            "auth_token": auth_token,
            "session_type": 1,
        },
    )
    if resp.status_code not in (200, 201):
        pytest.fail(f"创建测试会话失败: {resp.status_code} {resp.text}")
    data = resp.json()
    sid = extract_id(data, "session")
    yield sid
    try:
        api_client.delete(f"/api/session/{sid}")
    except Exception:
        pass


@pytest.fixture
def marketing_session(api_client, auth_token, user_id):
    """创建营销会话（session_type=2），测试后清理"""
    worlds = get_worlds_list(api_client)
    world_id = worlds[0]["id"] if worlds else "1"

    resp = api_client.post(
        "/api/session/create",
        json={
            "user_id": str(user_id),
            "world_id": str(world_id),
            "auth_token": auth_token,
            "session_type": 2,
        },
    )
    if resp.status_code not in (200, 201):
        pytest.fail(f"创建营销会话失败: {resp.status_code} {resp.text}")
    data = resp.json()
    sid = extract_id(data, "session")
    yield {"id": sid, "data": data}
    try:
        api_client.delete(f"/api/session/{sid}")
    except Exception:
        pass


# ──────────────────────────── E2E Mock 挡板（§13）────────────────────────────


@pytest.fixture(scope="session")
def mock_mode(user_id):
    """开启 E2E 媒体生成挡板（opt-in）。

    需要在 mock 模式下跑的 E2E 用例声明本 fixture（作为参数，或
    ``@pytest.mark.usefixtures("mock_mode")``）。

    做三件事：
    1. 开启 ``test_mode.enabled``（传 Python bool，不可传 "false" 字符串，见 config_util.py:365）；
    2. 重置测试账户算力到高值（§6.1，算力/CDN/token 均【不绕过】，靠此重置防扣穿）；
    3. 重启 ``SyncTaskExecutor`` 进程池，使子进程重新 fork 后读到新 test_mode（§7 缓存一致性）。

    teardown 仅恢复 ``test_mode.enabled``（不清理数据，见 §14）。
    任一步失败都只告警不阻断，保证其它 E2E 用例可继续。
    """
    from config.config_util import (
        set_dynamic_config_value,
        get_dynamic_config_value,
        invalidate_dynamic_cache,
    )

    try:
        saved_enabled = get_dynamic_config_value("test_mode", "enabled", default=False)
    except Exception as e:
        # 配置不可用（如 config_dev.yml 缺失）时不阻断，按未开启处理（§14 只告警原则）
        print(f"[mock_mode] 读取 test_mode.enabled 失败（非致命，按 False 处理）: {e}")
        saved_enabled = False

    # 1) 开启挡板并写入完整 mock URL，避免只开开关时部分通道回落到真实外部服务
    try:
        from scripts.enable_test_mode import KV as MOCK_MODE_CONFIGS
        for keys, (val, vtype) in MOCK_MODE_CONFIGS.items():
            set_dynamic_config_value(*keys, value=val, value_type=vtype)
        invalidate_dynamic_cache()
    except Exception as e:
        print(f"[mock_mode] 写入 mock 配置失败（非致命）: {e}")
        try:
            set_dynamic_config_value("test_mode", "enabled", value=True, value_type="bool")
            invalidate_dynamic_cache("test_mode.enabled")
        except Exception as e2:
            # 兜底写库同样可能不可用（如 config 文件缺失导致 model 层 import 失败），不阻断
            print(f"[mock_mode] 兜底写入 test_mode.enabled 也失败（非致命）: {e2}")

    # 2) 重置测试账户算力
    try:
        uid = int(user_id)
        from model.computing_power import ComputingPowerModel
        ComputingPowerModel.create_or_update(user_id=uid, computing_power=1_000_000)
    except Exception as e:
        print(f"[mock_mode] 重置算力失败（非致命）: {e}")

    # 3) 重启同步任务进程池
    try:
        from task.sync_task_executor import get_sync_task_executor
        exe = get_sync_task_executor()
        if exe.is_running():
            exe.shutdown(wait=False)
            exe.start()
    except Exception as e:
        print(f"[mock_mode] 重启 SyncTaskExecutor 失败（非致命）: {e}")

    yield

    # teardown：恢复 test_mode.enabled
    try:
        set_dynamic_config_value(
            "test_mode", "enabled", value=bool(saved_enabled), value_type="bool"
        )
        invalidate_dynamic_cache("test_mode.enabled")
    except Exception as e:
        print(f"[mock_mode] 恢复 test_mode 失败: {e}")
