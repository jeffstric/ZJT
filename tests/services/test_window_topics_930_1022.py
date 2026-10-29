"""前 3 周（70bcc0a9..821d599f）遗漏分支的补测合集。

覆盖五个此前零测试的改动面：
1. 抖音笔记解析器（services/article_fetch/providers/douyin.py，TikHub 响应形状易变）
2. 微信抓取 VL 识图并发化（services/article_fetch/wechat_fetcher.py，信号量限 4——
   串行识图曾把 24 图抓取整体拖到超时，属线上事故修复）
3. 订阅 sign-pay 400/503 透传（api/subscription.py，a3dd5af7b 不再被 500 吞掉）
4. 剧本提取任务 TTL 判定（model/script_extract_task.py，多 worker 404 修复的模型层）
5. admin 每日算力统计（api/admin.py，47192efe7/27c5598e4/8f00f3d1d）
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.article_fetch.models import ArticleFetchNotFound, ArticleFetchUpstreamError
from services.article_fetch.providers.douyin import parse_douyin_note


# ==================== 1. 抖音笔记解析器 ====================

def _douyin_data(desc="第一行标题\n第二行正文", images=None, nickname="作者A"):
    detail = {"desc": desc, "author": {"nickname": nickname}}
    if images is not None:
        detail["images"] = images
    return {"aweme_detail": detail}


def test_parse_douyin_title_from_first_line():
    parsed = parse_douyin_note(_douyin_data(), "https://v.douyin.com/x")
    assert parsed["title"] == "第一行标题"
    assert parsed["author"] == "作者A"
    assert "第二行正文" in parsed["text"]


def test_parse_douyin_images_prefers_download_url_and_dedupes():
    images = [
        {"download_url_list": ["https://direct/a.webp"], "url_list": ["https://cdn/a.webp"]},
        {"url_list": ["https://cdn/b.webp"]},
        {"download_url_list": ["", "https://direct/c.webp"]},
        {"url_list": ["not-http", "https://direct/a.webp"]},  # 与第 1 张去重
    ]
    parsed = parse_douyin_note(_douyin_data(images=images), "https://v.douyin.com/x")
    assert parsed["image_urls"] == [
        "https://direct/a.webp", "https://cdn/b.webp", "https://direct/c.webp",
    ]


def test_parse_douyin_missing_detail_raises_not_found():
    with pytest.raises(ArticleFetchNotFound):
        parse_douyin_note({"aweme_detail": None}, "https://v.douyin.com/x")
    with pytest.raises(ArticleFetchNotFound):
        parse_douyin_note({}, "https://v.douyin.com/x")


def test_parse_douyin_empty_desc_falls_back_to_default_title():
    # desc 为空时 title 兜底"未命名笔记"（该分支早于"全空抛错"判定）
    parsed = parse_douyin_note(_douyin_data(desc="", images=[], nickname=""), "u")
    assert parsed["title"] == "未命名笔记"
    assert parsed["image_urls"] == []


# ==================== 2. VL 识图并发化（信号量限 4） ====================

def test_wechat_fetcher_image_describe_concurrency_capped(monkeypatch):
    from services.article_fetch import wechat_fetcher

    in_flight = {"now": 0, "peak": 0}

    async def fake_describe(url, user_id=None, purpose=None):
        in_flight["now"] += 1
        in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
        await asyncio.sleep(0.01)
        in_flight["now"] -= 1
        return {"success": True, "description": f"desc of {url}"}

    import services.image_describe as image_describe
    monkeypatch.setattr(image_describe, "describe_image", fake_describe)

    images = [SimpleNamespace(url=f"https://x/{i}.jpg", description=None) for i in range(12)]
    article = SimpleNamespace(images=images)
    asyncio.run(wechat_fetcher._attach_image_descriptions(article))

    assert in_flight["peak"] == 4, "并发必须被信号量限制在 4（串行曾拖爆整体超时）"
    assert all(img.description.startswith("desc of") for img in images)


def test_wechat_fetcher_single_image_failure_does_not_block_others(monkeypatch):
    from services.article_fetch import wechat_fetcher

    async def fake_describe(url, user_id=None, purpose=None):
        if "bad" in url:
            raise RuntimeError("vl down")
        return {"success": True, "description": "ok " + url}

    import services.image_describe as image_describe
    monkeypatch.setattr(image_describe, "describe_image", fake_describe)

    images = [
        SimpleNamespace(url="https://x/good1.jpg", description=None),
        SimpleNamespace(url="https://x/bad.jpg", description=None),
        SimpleNamespace(url="https://x/good2.jpg", description=None),
    ]
    article = SimpleNamespace(images=images)
    asyncio.run(wechat_fetcher._attach_image_descriptions(article))
    assert images[0].description == "ok https://x/good1.jpg"
    assert images[2].description == "ok https://x/good2.jpg"
    assert not images[1].description


def test_wechat_fetcher_description_truncated_to_200(monkeypatch):
    from services.article_fetch import wechat_fetcher

    async def fake_describe(url, user_id=None, purpose=None):
        return {"success": True, "description": "长" * 500}

    import services.image_describe as image_describe
    monkeypatch.setattr(image_describe, "describe_image", fake_describe)

    img = SimpleNamespace(url="https://x/a.jpg", description=None)
    asyncio.run(wechat_fetcher._attach_image_descriptions(SimpleNamespace(images=[img])))
    assert len(img.description) == 200


def test_wechat_fetcher_no_images_is_noop():
    from services.article_fetch import wechat_fetcher
    asyncio.run(wechat_fetcher._attach_image_descriptions(
        SimpleNamespace(images=[])))


# ==================== 3. sign-pay 400/503 透传 ====================

def _sign_pay_client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api import subscription as sub_api

    app = FastAPI()
    app.include_router(sub_api.router)
    client = TestClient(app, raise_server_exceptions=False)

    monkeypatch.setattr(
        sub_api, "_verify_auth_token", _async_ok)

    # require_permission 走真实 token 解析：mock 为登录用户 1
    from model.user_tokens import UserTokensModel
    import perseids_server.utils.permission as permission_utils
    monkeypatch.setattr(
        UserTokensModel, "get_user_id_by_token",
        staticmethod(lambda t: 1 if t else None))
    async def fake_resolve(auth_value):
        return 1, None
    monkeypatch.setattr(
        permission_utils, "resolve_authorization_user_id", fake_resolve)

    def fake_v2_key(*_a, **_k):
        return "  "  # 密钥缺失
    monkeypatch.setattr(sub_api, "get_dynamic_config_value", fake_v2_key)
    return client, sub_api


async def _async_ok(*_a, **_k):
    return None


def test_sign_pay_missing_v2_key_returns_503(monkeypatch):
    client, sub_api = _sign_pay_client(monkeypatch)
    resp = client.post("/api/subscription/wechat-sign-pay", json={
        "subscription_plan_id": 1, "user_id": 1, "auth_token": "tok",
    })
    assert resp.status_code == 503, "503 不得被通用 except 吞成 500（a3dd5af7b）"
    assert "密钥未配置" in resp.json()["detail"]


def test_sign_pay_missing_token_returns_400(monkeypatch):
    from api import subscription as sub_api
    client, _ = _sign_pay_client(monkeypatch)
    monkeypatch.setattr(
        sub_api, "get_dynamic_config_value",
        lambda *a, **k: "has-key")
    resp = client.post("/api/subscription/wechat-sign-pay", json={
        "subscription_plan_id": 1, "user_id": 1, "auth_token": "",
    })
    assert resp.status_code == 400


def test_sign_pay_unexpected_error_still_500(monkeypatch):
    client, sub_api = _sign_pay_client(monkeypatch)
    monkeypatch.setattr(
        sub_api, "get_dynamic_config_value",
        lambda *a, **k: "has-key")
    monkeypatch.setattr(
        sub_api.subscription_service, "create_sign_pay_order",
        _async_raise(RuntimeError("boom")))
    resp = client.post("/api/subscription/wechat-sign-pay", json={
        "subscription_plan_id": 1, "user_id": 1, "auth_token": "tok",
    })
    assert resp.status_code == 500


async def _async_raise(exc):
    async def _fn(*_a, **_k):
        raise exc
    return _fn


# ==================== 4. 剧本提取任务 TTL ====================

def _task(status="running", updated=None):
    from model.script_extract_task import ScriptExtractTask
    return ScriptExtractTask(status=status, updated_at=updated,
                             task_id="t", user_id=1)


def test_extract_task_expired_after_ttl():
    stale = datetime.now() - timedelta(seconds=1200)
    assert _task("running", stale).is_expired(900) is True


def test_extract_task_not_expired_within_ttl():
    fresh = datetime.now() - timedelta(seconds=60)
    assert _task("running", fresh).is_expired(900) is False


def test_extract_task_terminal_states_never_expired():
    stale = datetime.now() - timedelta(hours=5)
    assert _task("completed", stale).is_expired(900) is False
    assert _task("failed", stale).is_expired(900) is False


def test_extract_task_missing_timestamp_never_expired():
    assert _task("running", None).is_expired(900) is False


def test_extract_task_unparsable_timestamp_never_expired():
    assert _task("running", "not-a-date").is_expired(900) is False


def test_extract_task_string_timestamp_parsed():
    stale_str = (datetime.now() - timedelta(seconds=2000)).strftime("%Y-%m-%d %H:%M:%S")
    assert _task("running", stale_str).is_expired(900) is True


# ==================== 5. admin 每日算力统计 ====================

def _admin_client(monkeypatch, rows):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api import admin as admin_api

    app = FastAPI()
    app.include_router(admin_api.router)
    client = TestClient(app, raise_server_exceptions=False)

    async def fake_require_admin(_token):
        return SimpleNamespace(id=1, role="admin")
    monkeypatch.setattr(admin_api, "require_admin", fake_require_admin)
    monkeypatch.setattr(
        admin_api.ComputingPowerLogModel, "get_daily_user_power_stats",
        staticmethod(lambda start_date, end_date: rows))
    return client


def _row(date, user_id, nickname, power, count=1, remark=""):
    return {"stat_date": date, "user_id": user_id, "nickname": nickname,
            "total_power": power, "record_count": count, "remark": remark}


def test_daily_power_stats_groups_by_day_and_prefers_remark(monkeypatch):
    client = _admin_client(monkeypatch, [
        _row("2026-10-20", 7, "nickA", 50, 2, remark="VIP客户"),
        _row("2026-10-20", 8, "nickB", 30),
        _row(datetime(2026, 10, 21), 7, "nickA", 20),
    ])
    resp = client.get(
        "/api/admin/dashboard/daily-power-stats",
        headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    daily = resp.json()["data"]["daily"]
    assert [d["date"] for d in daily] == ["2026-10-20", "2026-10-21"]
    day1 = daily[0]
    assert day1["total_power"] == 80
    users = {u["user_id"]: u for u in day1["users"]}
    assert users[7]["display_name"] == "VIP客户"  # 管理员备注优先（27c5598e4）
    assert users[8]["display_name"] == "nickB"


def test_daily_power_stats_invalid_date_format_400(monkeypatch):
    client = _admin_client(monkeypatch, [])
    resp = client.get(
        "/api/admin/dashboard/daily-power-stats",
        params={"start_date": "20-10-01", "end_date": "2026-10-02"},
        headers={"Authorization": "Bearer t"})
    assert resp.status_code == 400


def test_daily_power_stats_start_after_end_400(monkeypatch):
    client = _admin_client(monkeypatch, [])
    resp = client.get(
        "/api/admin/dashboard/daily-power-stats",
        params={"start_date": "2026-10-05", "end_date": "2026-10-01"},
        headers={"Authorization": "Bearer t"})
    assert resp.status_code == 400
    assert "earlier" in resp.json()["detail"]


def test_daily_power_stats_empty_rows_returns_empty_daily(monkeypatch):
    """首次进入无数据时返回空 daily 而非报错（8f00f3d1d）。"""
    client = _admin_client(monkeypatch, [])
    resp = client.get(
        "/api/admin/dashboard/daily-power-stats",
        headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["daily"] == []
    assert data["start_date"] and data["end_date"]


def test_daily_power_stats_missing_nickname_falls_back(monkeypatch):
    client = _admin_client(monkeypatch, [
        _row("2026-10-20", 99, None, 10),
    ])
    resp = client.get(
        "/api/admin/dashboard/daily-power-stats",
        headers={"Authorization": "Bearer t"})
    user = resp.json()["data"]["daily"][0]["users"][0]
    assert user["nickname"] == "用户99"
    assert user["display_name"] == "用户99"
