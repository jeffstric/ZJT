import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

import api.user_modules as module_api


class FakeService:
    def __init__(self):
        self.job = SimpleNamespace(
            job_id="job-1",
            module_id="demo.echo",
            module_version="1.0.0",
            code_digest="sha256:" + "a" * 64,
            operation="echo_image",
            media_kind="image",
            status="queued",
            progress=None,
            result=None,
            error=None,
            create_at=None,
            update_at=None,
            complete_at=None,
        )

    async def create_media_job(self, **kwargs):
        return self.job

    async def dispatch_job(self, job_id):
        return None

    async def get_job(self, job_id, requester_id=None):
        return self.job


def test_gateway_returns_202_without_importing_user_code(monkeypatch):
    async def scenario():
        fake_service = FakeService()

        async def authenticated(_authorization):
            return 42, None

        monkeypatch.setattr(module_api, "_resolve_requester_id", authenticated)
        monkeypatch.setattr(module_api, "get_user_module_service", lambda: fake_service)
        app = FastAPI()
        app.include_router(module_api.router)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/modules/demo.echo/media/echo_image/jobs",
                headers={"Authorization": "Bearer test", "Idempotency-Key": "idem-0001"},
                json={"media_kind": "image", "prompt": "hello"},
            )
        assert response.status_code == 202
        payload = response.json()
        assert payload["data"]["job_id"] == "job-1"
        assert payload["data"]["status"] == "queued"

    asyncio.run(scenario())


def test_gateway_rejects_short_idempotency_header(monkeypatch):
    async def scenario():
        fake_service = FakeService()

        async def authenticated(_authorization):
            return 42, None

        monkeypatch.setattr(module_api, "_resolve_requester_id", authenticated)
        monkeypatch.setattr(module_api, "get_user_module_service", lambda: fake_service)
        app = FastAPI()
        app.include_router(module_api.router)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/modules/demo.echo/media/echo_image/jobs",
                headers={"Authorization": "Bearer test", "Idempotency-Key": "short"},
                json={"media_kind": "image", "prompt": "hello"},
            )
        assert response.status_code == 400
        assert response.json()["error_code"] == "INVALID_IDEMPOTENCY_KEY"

    asyncio.run(scenario())
