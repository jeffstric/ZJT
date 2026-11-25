import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx

from module_runtime.client import (
    _release_validation_failure,
    _release_validation_safe_details,
    _release_validation_success,
)
from module_runtime.manifest import compute_release_digest
from module_runtime.protocol import DriverContext, MediaRequest
from module_runtime.rpc import RpcRequest, RpcResponse
from module_runtime.supervisor import (
    ReleaseDescriptor,
    RunnerManager,
    create_supervisor_app,
)


DRIVER_SOURCE = '''
from module_runtime.protocol import (
    CancelResult, Completed, HealthResult, JobStatus, MediaRef, PollResult
)


class Driver:
    async def initialize(self, ctx):
        return None

    async def health(self, ctx):
        return HealthResult(healthy=True)

    async def submit(self, ctx, request):
        return Completed(outputs=[MediaRef(
            media_kind=request.media_kind,
            url="https://example.invalid/echo.png",
        )])

    async def poll(self, ctx, handle):
        return PollResult(status=JobStatus.RUNNING, progress=0.5)

    async def cancel(self, ctx, handle):
        return CancelResult(cancelled=True, status=JobStatus.CANCELLED)

    async def handle_callback(self, ctx, handle, event):
        return PollResult(status=JobStatus.SUCCEEDED)
'''


def _build_release(
    root: Path,
    *,
    driver_source: str = DRIVER_SOURCE,
    secret_names: list | None = None,
) -> ReleaseDescriptor:
    release = root / "modules" / "demo.echo" / "releases" / "1.0.0-test"
    source = release / "src"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("", encoding="utf-8")
    (source / "driver.py").write_text(driver_source, encoding="utf-8")
    manifest = {
        "manifest_schema_version": 1,
        "module_id": "demo.echo",
        "name": "Echo integration test",
        "version": "1.0.0",
        "entrypoint": "src.driver:Driver",
        "rpc_protocol": "user-module-rpc/v1",
        "driver_protocol": "media-driver/v1",
        "sdk_version": "1.0.0",
        "execution_model": "native_async",
        "capabilities": [
            {
                "operation": "echo_image",
                "media_kind": "image",
                "completion_modes": ["immediate"],
            }
        ],
        "permissions": {
            "network_hosts": [],
            "secret_names": list(secret_names or []),
            "asset_read": False,
            "asset_write": True,
        },
    }
    (release / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    digest = compute_release_digest(release)
    manifest["code_digest"] = digest
    (release / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return ReleaseDescriptor(
        release_id=1,
        module_id="demo.echo",
        version="1.0.0",
        code_digest=digest,
        release_path=str(release.relative_to(root)),
    )


def test_runner_process_executes_module_over_rpc(tmp_path: Path):
    async def scenario():
        manager = RunnerManager(tmp_path)
        descriptor = _build_release(tmp_path)
        handle = await manager.start_release(descriptor)
        context = DriverContext(
            request_id="request-1",
            job_id="job-1",
            user_id="user-1",
            module_id=descriptor.module_id,
            module_version=descriptor.version,
            code_digest=descriptor.code_digest,
            deadline_unix_ms=int((time.time() + 30) * 1000),
        )
        media_request = MediaRequest(
            media_kind="image",
            operation="echo_image",
            prompt="hello",
            idempotency_key="idem-0001",
            deadline_unix_ms=context.deadline_unix_ms,
        )
        response = await manager.call(
            handle,
            RpcRequest(
                request_id="request-1",
                method="submit",
                params={
                    "context": context.model_dump(mode="json"),
                    "request": media_request.model_dump(mode="json"),
                },
                timeout_seconds=10,
            ),
        )
        assert response.ok is True
        assert response.result["result_type"] == "completed"
        assert response.result["outputs"][0]["media_kind"] == "image"
        await manager.shutdown()
        assert handle.process.returncode is not None

    asyncio.run(scenario())


def test_supervisor_proxies_exact_release_identity(tmp_path: Path):
    async def scenario():
        manager = RunnerManager(tmp_path)
        descriptor = _build_release(tmp_path)
        await manager.start_release(descriptor)
        context = DriverContext(
            request_id="request-2",
            job_id="job-2",
            user_id="user-1",
            module_id=descriptor.module_id,
            module_version=descriptor.version,
            code_digest=descriptor.code_digest,
            deadline_unix_ms=int((time.time() + 30) * 1000),
        )
        media_request = MediaRequest(
            media_kind="image",
            operation="echo_image",
            prompt="hello",
            idempotency_key="idem-0002",
            deadline_unix_ms=context.deadline_unix_ms,
        )
        app = create_supervisor_app(manager, "supervisor-test-token", load_registry_on_start=False)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://supervisor") as client:
            unauthorized = await client.get("/health")
            assert unauthorized.status_code == 401
            response = await client.post(
                "/v1/rpc",
                headers={"X-Module-Token": "supervisor-test-token"},
                json={
                    "request_id": "request-2",
                    "method": "submit",
                    "params": {
                        "context": context.model_dump(mode="json"),
                        "request": media_request.model_dump(mode="json"),
                    },
                    "timeout_seconds": 10,
                    "release_id": descriptor.release_id,
                    "module_id": descriptor.module_id,
                    "module_version": descriptor.version,
                    "code_digest": descriptor.code_digest,
                },
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["ok"] is True
            assert payload["result"]["result_type"] == "completed"
        await manager.shutdown()

    asyncio.run(scenario())


SECRET_PROBE_DRIVER = '''
from module_runtime.protocol import (
    CancelResult, Completed, HealthResult, JobStatus, MediaRef, PollResult
)


class Driver:
    async def initialize(self, ctx):
        return None

    async def health(self, ctx):
        key = ctx.secrets.get("EXAMPLE_API_KEY") or ""
        return HealthResult(
            healthy=True,
            details={"configured": bool(key), "secret_len": len(key)},
        )

    async def submit(self, ctx, request):
        return Completed(outputs=[MediaRef(
            media_kind=request.media_kind,
            url="https://example.invalid/echo.png",
        )])

    async def poll(self, ctx, handle):
        return PollResult(status=JobStatus.RUNNING, progress=0.5)

    async def cancel(self, ctx, handle):
        return CancelResult(cancelled=True, status=JobStatus.CANCELLED)

    async def handle_callback(self, ctx, handle, event):
        return PollResult(status=JobStatus.SUCCEEDED)
'''


def test_supervisor_injects_fresh_secrets_on_each_rpc(tmp_path: Path, monkeypatch):
    current = {"EXAMPLE_API_KEY": "old-key"}

    def fake_resolve(secret_names, environ=None):
        return {
            name: current[name]
            for name in secret_names
            if name in current and current[name]
        }

    monkeypatch.setattr(
        "module_runtime.supervisor.resolve_declared_secrets",
        fake_resolve,
    )

    async def scenario():
        manager = RunnerManager(tmp_path)
        descriptor = _build_release(
            tmp_path,
            driver_source=SECRET_PROBE_DRIVER,
            secret_names=["EXAMPLE_API_KEY"],
        )
        handle = await manager.start_release(descriptor)
        assert handle.declared_secret_names == ("EXAMPLE_API_KEY",)
        context = DriverContext(
            request_id="secret-1",
            job_id="job-secret",
            module_id=descriptor.module_id,
            module_version=descriptor.version,
            code_digest=descriptor.code_digest,
            deadline_unix_ms=int((time.time() + 30) * 1000),
            secrets={"EXAMPLE_API_KEY": "caller-must-not-win", "UNDECLARED": "nope"},
        )

        first = await manager.call(
            handle,
            RpcRequest(
                request_id="secret-1",
                method="health",
                params={"context": context.model_dump(mode="json")},
                timeout_seconds=10,
            ),
        )
        assert first.ok is True
        assert first.result["details"]["secret_len"] == len("old-key")

        current["EXAMPLE_API_KEY"] = "rotated-secret-value"
        second = await manager.call(
            handle,
            RpcRequest(
                request_id="secret-2",
                method="health",
                params={"context": context.model_dump(mode="json")},
                timeout_seconds=10,
            ),
        )
        assert second.ok is True
        assert second.result["details"]["secret_len"] == len("rotated-secret-value")
        await manager.shutdown()

    asyncio.run(scenario())


def test_supervisor_validates_candidate_health_and_stops_runner(tmp_path: Path):
    async def scenario():
        manager = RunnerManager(tmp_path)
        descriptor = _build_release(tmp_path)
        await manager.start_release(descriptor)
        app = create_supervisor_app(manager, "supervisor-test-token", load_registry_on_start=False)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://supervisor") as client:
            response = await client.post(
                "/v1/releases/validate",
                headers={"X-Module-Token": "supervisor-test-token"},
                json={
                    "release_id": descriptor.release_id,
                    "module_id": descriptor.module_id,
                    "module_version": descriptor.version,
                    "code_digest": descriptor.code_digest,
                },
            )
            assert response.status_code == 200
            assert response.json()["ok"] is True
        assert descriptor.key not in manager._handles
        await manager.shutdown()

    asyncio.run(scenario())


def test_supervisor_redacts_module_controlled_unhealthy_message(caplog):
    leaked_secret = "hm-super-secret-health-value"

    class UnhealthyManager:
        def __init__(self):
            self._handles = {}
            self.stopped = False

        async def ensure_release(self, release_id, key):
            return SimpleNamespace(declared_secret_names=("EXAMPLE_API_KEY",))

        async def call(self, handle, request):
            return RpcResponse.success(
                request.request_id,
                {
                    "healthy": False,
                    "message": f"缺少密钥，实际值={leaked_secret}",
                    "details": {
                        "missing_secrets": ["EXAMPLE_API_KEY", leaked_secret],
                        "debug": leaked_secret,
                    },
                },
            )

        async def stop_release(self, key):
            self.stopped = True

        async def shutdown(self):
            return None

    async def scenario():
        manager = UnhealthyManager()
        app = create_supervisor_app(manager, "supervisor-test-token", load_registry_on_start=False)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://supervisor") as client:
            response = await client.post(
                "/v1/releases/validate",
                headers={"X-Module-Token": "supervisor-test-token"},
                json={
                    "release_id": 9,
                    "module_id": "demo.unhealthy",
                    "module_version": "1.0.0",
                    "code_digest": "sha256:" + "a" * 64,
                },
            )
        assert response.status_code == 422
        assert response.json()["detail"] == {
            "code": "RELEASE_HEALTH_UNHEALTHY",
            "message": "候选 Release 的 Driver health 返回不健康",
            "details": {"missing_secrets": ["EXAMPLE_API_KEY"]},
        }
        assert leaked_secret not in response.text
        assert leaked_secret not in caplog.text
        assert manager.stopped is True

    asyncio.run(scenario())


def test_supervisor_redacts_module_controlled_healthy_payload():
    leaked_secret = "hm-super-secret-healthy-value"

    class HealthyManager:
        def __init__(self):
            self._handles = {}

        async def ensure_release(self, release_id, key):
            return SimpleNamespace(declared_secret_names=("EXAMPLE_API_KEY",))

        async def call(self, handle, request):
            return RpcResponse.success(
                request.request_id,
                {
                    "healthy": True,
                    "message": leaked_secret,
                    "details": {
                        "missing_secrets": ["EXAMPLE_API_KEY"],
                        "debug": leaked_secret,
                    },
                },
            )

        async def stop_release(self, key):
            return None

        async def shutdown(self):
            return None

    async def scenario():
        manager = HealthyManager()
        app = create_supervisor_app(manager, "supervisor-test-token", load_registry_on_start=False)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://supervisor") as client:
            response = await client.post(
                "/v1/releases/validate",
                headers={"X-Module-Token": "supervisor-test-token"},
                json={
                    "release_id": 9,
                    "module_id": "demo.healthy",
                    "module_version": "1.0.0",
                    "code_digest": "sha256:" + "a" * 64,
                },
            )
        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "health": {
                "healthy": True,
                "details": {"missing_secrets": ["EXAMPLE_API_KEY"]},
            },
        }
        assert leaked_secret not in response.text

    asyncio.run(scenario())


def test_supervisor_client_ignores_remote_validation_message():
    leaked_secret = "hm-super-secret-client-value"
    response = httpx.Response(
        422,
        json={
            "detail": {
                "code": "RELEASE_HEALTH_UNHEALTHY",
                "message": leaked_secret,
                "details": {
                    "missing_secrets": ["EXAMPLE_API_KEY"],
                    "debug": leaked_secret,
                },
            }
        },
    )

    code, message = _release_validation_failure(response)

    assert code == "RELEASE_HEALTH_UNHEALTHY"
    assert message == "候选 Release 的 Driver health 返回不健康"
    assert leaked_secret not in message
    assert _release_validation_safe_details(response) == {
        "missing_secrets": ["EXAMPLE_API_KEY"]
    }


def test_supervisor_client_rejects_unknown_remote_error_code_and_text():
    leaked_secret = "hm-super-secret-unknown-code"
    response = httpx.Response(
        422,
        json={"detail": {"code": leaked_secret, "message": leaked_secret}},
    )

    code, message = _release_validation_failure(response)

    assert code == "RELEASE_RUNTIME_VALIDATION_FAILED"
    assert message == "候选 Release 未通过运行时健康校验"
    assert leaked_secret not in f"{code}{message}"


def test_supervisor_client_redacts_success_payload_again():
    leaked_secret = "hm-super-secret-client-success"

    result = _release_validation_success({
        "ok": True,
        "health": {
            "healthy": True,
            "message": leaked_secret,
            "details": {
                "missing_secrets": ["EXAMPLE_API_KEY"],
                "debug": leaked_secret,
            },
        },
    })

    assert result == {
        "ok": True,
        "health": {
            "healthy": True,
            "details": {"missing_secrets": ["EXAMPLE_API_KEY"]},
        },
    }
    assert leaked_secret not in json.dumps(result)
