import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from module_runtime.protocol import MediaKind, MediaRef
from module_runtime.rpc import RpcResponse
from module_runtime.client import SupervisorClientError
from services.user_module_service import (
    UserModuleService,
    UserModuleServiceError,
    declared_host_output_urls,
    replace_output_urls,
)


def manifest(version: str, digest_char: str):
    return {
        "manifest_schema_version": 1,
        "module_id": "demo.echo",
        "name": "Echo",
        "version": version,
        "code_digest": "sha256:" + digest_char * 64,
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
    }


def release(release_id: int, version: str, digest_char: str):
    payload = manifest(version, digest_char)
    return SimpleNamespace(
        id=release_id,
        module_id="demo.echo",
        version=version,
        code_digest=payload["code_digest"],
        driver_protocol="media-driver/v1",
        manifest=payload,
    )


class FakeModulesModel:
    active = release(1, "1.0.0", "a")

    @classmethod
    def get_active_release(cls, module_id):
        return cls.active if module_id == "demo.echo" else None


class FakeJobsModel:
    jobs = {}

    @classmethod
    def reset(cls):
        cls.jobs = {}

    @classmethod
    def create(cls, **kwargs):
        release_value = kwargs["release"]
        job = SimpleNamespace(
            job_id=kwargs["job_id"],
            release_id=release_value.id,
            module_id=release_value.module_id,
            module_version=release_value.version,
            code_digest=release_value.code_digest,
            protocol_version=release_value.driver_protocol,
            requester_id=kwargs["requester_id"],
            operation=kwargs["operation"],
            media_kind=kwargs["media_kind"],
            status="queued",
            idempotency_key=kwargs["idempotency_key"],
            completion_modes=kwargs["completion_modes"],
            request=kwargs["request"],
            external_job_id=None,
            handle=None,
            result=None,
            error=None,
            progress=None,
            next_poll_at=None,
            timeout_at=kwargs["timeout_at"],
            create_at=None,
            update_at=None,
            complete_at=None,
            callback_token_hash=kwargs.get("callback_token_hash"),
        )
        cls.jobs[job.job_id] = job
        return job

    @classmethod
    def get(cls, job_id):
        return cls.jobs.get(job_id)

    @classmethod
    def get_by_callback_token_hash(cls, token_hash):
        return next(
            (job for job in cls.jobs.values() if job.callback_token_hash == token_hash),
            None,
        )

    @classmethod
    def claim_queued(cls, job_id):
        job = cls.jobs[job_id]
        if job.status != "queued":
            return False
        job.status = "submitted"
        return True

    @classmethod
    def mark_completed(cls, job_id, result):
        job = cls.jobs[job_id]
        job.status = "succeeded"
        job.result = result
        return 1

    @classmethod
    def mark_accepted(cls, job_id, external_job_id, handle, next_poll_at):
        job = cls.jobs[job_id]
        job.status = "running"
        job.external_job_id = external_job_id
        job.handle = handle
        job.next_poll_at = next_poll_at
        return 1

    @classmethod
    def mark_failed(cls, job_id, error, timed_out=False):
        job = cls.jobs[job_id]
        job.status = "timed_out" if timed_out else "failed"
        job.error = error
        return 1

    @classmethod
    def retry_submission(cls, job_id, error):
        job = cls.jobs[job_id]
        job.status = "queued"
        job.error = error
        return 1

    @classmethod
    def retry_poll(cls, job_id, error, next_poll_at):
        job = cls.jobs[job_id]
        job.error = error
        job.next_poll_at = next_poll_at
        return 1

    @classmethod
    def update_running(cls, job_id, progress, next_poll_at):
        job = cls.jobs[job_id]
        job.status = "running"
        job.progress = progress
        job.next_poll_at = next_poll_at
        return 1

    @classmethod
    def cancel(cls, job_id):
        cls.jobs[job_id].status = "cancelled"
        return 1


class CapturingClient:
    def __init__(self, result):
        self.result = result
        self.requests = []

    async def call(self, request):
        self.requests.append(request)
        return RpcResponse.success(request.request_id, self.result)


class FailingClient:
    async def call(self, request):
        raise SupervisorClientError("SUPERVISOR_UNAVAILABLE", "temporary", retryable=True)


def test_declared_host_output_urls_only_rewrites_manifest_hosts():
    outputs = [
        MediaRef(media_kind=MediaKind.IMAGE, url="http://192.168.10.187:8188/view?filename=a.png"),
        MediaRef(media_kind=MediaKind.IMAGE, url="https://cdn.example/public.png"),
    ]
    local = declared_host_output_urls(outputs, ["192.168.10.187:8188"])
    assert local == ["http://192.168.10.187:8188/view?filename=a.png"]
    rewritten = replace_output_urls(outputs, {local[0]: "https://cdn.example/ingested.png"})
    assert rewritten[0].url == "https://cdn.example/ingested.png"
    assert rewritten[1].url == "https://cdn.example/public.png"


def test_dispatch_ingests_lan_output_url(monkeypatch):
    async def scenario():
        FakeJobsModel.reset()
        payload = manifest("1.0.0", "a")
        payload["permissions"] = {
            "network_hosts": ["192.168.10.187:8188"],
            "secret_names": [],
            "asset_read": False,
            "asset_write": True,
        }
        FakeModulesModel.active = SimpleNamespace(
            id=1,
            module_id="demo.echo",
            version="1.0.0",
            code_digest=payload["code_digest"],
            driver_protocol="media-driver/v1",
            manifest=payload,
        )
        lan_url = "http://192.168.10.187:8188/view?filename=out.png"
        client = CapturingClient(
            {
                "result_type": "completed",
                "outputs": [{"media_kind": "image", "url": lan_url}],
            }
        )

        async def fake_ingest(urls, config, project_root=None):
            return ["https://cdn.example/ingested.png" for _ in urls]

        monkeypatch.setattr(
            "utils.image_upload_utils.upload_local_images_to_cdn",
            fake_ingest,
        )
        monkeypatch.setattr("config.config_util.get_config", lambda: {})
        service = UserModuleService(
            client=client,
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        job = await service.create_media_job(
            module_id="demo.echo",
            requester_id="user-1",
            operation="echo_image",
            media_kind="image",
            prompt="hello",
            inputs=[],
            parameters={},
            idempotency_key="idem-lan",
        )
        await service.dispatch_job(job.job_id)
        stored = FakeJobsModel.jobs[job.job_id]
        assert stored.status == "succeeded"
        assert stored.result["outputs"][0]["url"] == "https://cdn.example/ingested.png"

    asyncio.run(scenario())


def test_job_stays_pinned_when_active_release_changes():
    async def scenario():
        FakeJobsModel.reset()
        FakeModulesModel.active = release(1, "1.0.0", "a")
        client = CapturingClient(
            {
                "result_type": "completed",
                "outputs": [
                    {
                        "media_kind": "image",
                        "url": "https://example.invalid/result.png",
                    }
                ],
            }
        )
        service = UserModuleService(
            client=client,
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        job = await service.create_media_job(
            module_id="demo.echo",
            requester_id="user-1",
            operation="echo_image",
            media_kind="image",
            prompt="hello",
            inputs=[],
            parameters={},
            idempotency_key="idem-0001",
        )
        FakeModulesModel.active = release(2, "2.0.0", "b")
        await service.dispatch_job(job.job_id)
        rpc_request = client.requests[0]
        assert rpc_request.release_id == 1
        assert rpc_request.module_version == "1.0.0"
        assert rpc_request.code_digest == "sha256:" + "a" * 64
        assert FakeJobsModel.jobs[job.job_id].status == "succeeded"

    asyncio.run(scenario())


def test_completed_output_media_kind_must_match_job():
    async def scenario():
        FakeJobsModel.reset()
        FakeModulesModel.active = release(1, "1.0.0", "a")
        client = CapturingClient(
            {
                "result_type": "completed",
                "outputs": [
                    {"media_kind": "video", "url": "https://example.invalid/result.mp4"}
                ],
            }
        )
        service = UserModuleService(
            client=client,
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        job = await service.create_media_job(
            module_id="demo.echo",
            requester_id="user-1",
            operation="echo_image",
            media_kind="image",
            prompt="hello",
            inputs=[],
            parameters={},
            idempotency_key="idem-kind",
        )
        await service.dispatch_job(job.job_id)
        assert FakeJobsModel.jobs[job.job_id].status == "failed"
        assert "媒体类型" in FakeJobsModel.jobs[job.job_id].error["message"]

    asyncio.run(scenario())


def test_retryable_supervisor_failure_returns_submission_to_queue():
    async def scenario():
        FakeJobsModel.reset()
        FakeModulesModel.active = release(1, "1.0.0", "a")
        service = UserModuleService(
            client=FailingClient(),
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        job = await service.create_media_job(
            module_id="demo.echo",
            requester_id="user-1",
            operation="echo_image",
            media_kind="image",
            prompt="hello",
            inputs=[],
            parameters={},
            idempotency_key="idem-retry",
        )
        await service.dispatch_job(job.job_id)
        stored = FakeJobsModel.jobs[job.job_id]
        assert stored.status == "queued"
        assert stored.error["retryable"] is True

    asyncio.run(scenario())


def test_retryable_supervisor_failure_during_poll_defers_next_poll():
    """轮询阶段遇到可重试的 Supervisor 抖动应延后重试，而非直接判失败（M1）。"""

    async def scenario():
        FakeJobsModel.reset()
        FakeModulesModel.active = release(1, "1.0.0", "a")
        FakeModulesModel.active.manifest["capabilities"][0]["completion_modes"] = ["polling"]
        # 先用一个返回 Accepted 的 client 把任务推进到 running + handle
        submit_service = UserModuleService(
            client=CapturingClient(
                {
                    "result_type": "accepted",
                    "handle": {"external_job_id": "external-poll", "opaque_data": {}},
                    "next_poll_after_seconds": 1,
                }
            ),
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        job = await submit_service.create_media_job(
            module_id="demo.echo",
            requester_id="user-1",
            operation="echo_image",
            media_kind="image",
            prompt="hello",
            inputs=[],
            parameters={},
            idempotency_key="idem-poll-retry",
        )
        await submit_service.dispatch_job(job.job_id)
        stored = FakeJobsModel.jobs[job.job_id]
        assert stored.status == "running"
        assert stored.handle is not None

        # 轮询阶段遇到可重试的 Supervisor 抖动，应走 retry_poll（保持 running）
        poll_service = UserModuleService(
            client=FailingClient(),
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        await poll_service.poll_job(stored)

        stored = FakeJobsModel.jobs[job.job_id]
        assert stored.status == "running"
        assert stored.error["retryable"] is True
        assert stored.next_poll_at is not None

    asyncio.run(scenario())


def test_job_deadline_uses_local_database_clock_semantics():
    async def scenario():
        FakeJobsModel.reset()
        FakeModulesModel.active = release(1, "1.0.0", "a")
        service = UserModuleService(
            client=CapturingClient({}),
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        job = await service.create_media_job(
            module_id="demo.echo",
            requester_id="user-1",
            operation="echo_image",
            media_kind="image",
            prompt="hello",
            inputs=[],
            parameters={},
            idempotency_key="idem-clock",
        )
        assert job.timeout_at > before
        assert 100 <= (job.timeout_at - before).total_seconds() <= 125

    asyncio.run(scenario())


def test_manifest_request_size_limit_is_enforced():
    async def scenario():
        FakeJobsModel.reset()
        FakeModulesModel.active = release(1, "1.0.0", "a")
        FakeModulesModel.active.manifest["resource_limits"] = {
            "max_request_bytes": 1024,
        }
        service = UserModuleService(
            client=CapturingClient({}),
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        try:
            await service.create_media_job(
                module_id="demo.echo",
                requester_id="user-1",
                operation="echo_image",
                media_kind="image",
                prompt="x" * 2000,
                inputs=[],
                parameters={},
                idempotency_key="idem-size",
            )
        except UserModuleServiceError as exc:
            assert exc.code == "MODULE_REQUEST_TOO_LARGE"
            assert exc.status_code == 413
        else:
            raise AssertionError("超过 Manifest 大小限制的请求未被拒绝")

    asyncio.run(scenario())


def test_async_submit_persists_task_handle_for_polling():
    async def scenario():
        FakeJobsModel.reset()
        FakeModulesModel.active = release(1, "1.0.0", "a")
        FakeModulesModel.active.manifest["capabilities"][0]["completion_modes"] = ["polling"]
        client = CapturingClient(
            {
                "result_type": "accepted",
                "handle": {"external_job_id": "external-1", "opaque_data": {}},
                "next_poll_after_seconds": 1,
            }
        )
        service = UserModuleService(
            client=client,
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        job = await service.create_media_job(
            module_id="demo.echo",
            requester_id="user-1",
            operation="echo_image",
            media_kind="image",
            prompt="hello",
            inputs=[],
            parameters={},
            idempotency_key="idem-0002",
        )
        await service.dispatch_job(job.job_id)
        stored = FakeJobsModel.jobs[job.job_id]
        assert stored.status == "running"
        assert stored.external_job_id == "external-1"
        assert stored.handle["external_job_id"] == "external-1"

    asyncio.run(scenario())


def test_immediate_capability_rejects_accepted_result():
    async def scenario():
        FakeJobsModel.reset()
        FakeModulesModel.active = release(1, "1.0.0", "a")
        client = CapturingClient(
            {
                "result_type": "accepted",
                "handle": {"external_job_id": "unexpected", "opaque_data": {}},
            }
        )
        service = UserModuleService(
            client=client,
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        job = await service.create_media_job(
            module_id="demo.echo",
            requester_id="user-1",
            operation="echo_image",
            media_kind="image",
            prompt="hello",
            inputs=[],
            parameters={},
            idempotency_key="idem-immediate",
        )
        await service.dispatch_job(job.job_id)
        assert FakeJobsModel.jobs[job.job_id].status == "failed"
        assert "immediate" in FakeJobsModel.jobs[job.job_id].error["message"]

    asyncio.run(scenario())


def test_webhook_callback_is_pinned_and_token_is_not_plaintext(monkeypatch, tmp_path):
    async def scenario():
        FakeJobsModel.reset()
        FakeModulesModel.active = release(1, "1.0.0", "a")
        FakeModulesModel.active.manifest["capabilities"][0]["completion_modes"] = ["webhook"]
        client = CapturingClient(
            {
                "result_type": "accepted",
                "handle": {"external_job_id": "external-webhook", "opaque_data": {}},
            }
        )
        service = UserModuleService(
            client=client,
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        job = await service.create_media_job(
            module_id="demo.echo",
            requester_id="user-1",
            operation="echo_image",
            media_kind="image",
            prompt="hello",
            inputs=[],
            parameters={},
            idempotency_key="idem-webhook",
        )
        assert len(job.callback_token_hash) == 64
        await service.dispatch_job(job.job_id)
        callback_url = client.requests[0].params["request"]["parameters"]["callback"]["url"]
        callback_token = callback_url.rsplit("/", 1)[-1]
        assert callback_token not in str(job.__dict__)

        client.result = {"status": "succeeded", "outputs": []}
        result = await service.handle_callback(
            callback_token,
            headers={"x-provider-signature": "test"},
            payload={"status": "done"},
        )
        assert result.status == "succeeded"
        callback_rpc = client.requests[-1]
        assert callback_rpc.release_id == 1
        assert callback_rpc.method == "handle_callback"

    monkeypatch.setenv("ZJT_USER_MODULES_DIR", str(tmp_path / "module-data"))
    monkeypatch.setenv("ZJT_USER_MODULE_CALLBACK_BASE_URL", "https://callback.example.invalid")
    asyncio.run(scenario())


def test_webhook_only_job_does_not_schedule_polling(monkeypatch, tmp_path):
    async def scenario():
        FakeJobsModel.reset()
        FakeModulesModel.active = release(1, "1.0.0", "a")
        FakeModulesModel.active.manifest["capabilities"][0]["completion_modes"] = ["webhook"]
        client = CapturingClient(
            {
                "result_type": "accepted",
                "handle": {"external_job_id": "webhook-only", "opaque_data": {}},
            }
        )
        service = UserModuleService(
            client=client,
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        job = await service.create_media_job(
            module_id="demo.echo",
            requester_id="user-1",
            operation="echo_image",
            media_kind="image",
            prompt="hello",
            inputs=[],
            parameters={},
            idempotency_key="idem-webhook-only",
        )
        await service.dispatch_job(job.job_id)
        stored = FakeJobsModel.jobs[job.job_id]
        assert stored.status == "running"
        assert stored.next_poll_at is None

    monkeypatch.setenv("ZJT_USER_MODULES_DIR", str(tmp_path / "module-data-webhook-only"))
    monkeypatch.setenv("ZJT_USER_MODULE_CALLBACK_BASE_URL", "https://callback.example.invalid")
    asyncio.run(scenario())


def test_webhook_polling_module_degrades_to_polling_without_callback_base(monkeypatch, tmp_path):
    """webhook+polling 模块在回调地址未配置时降级为纯轮询，不注入 callback。"""

    async def scenario():
        FakeJobsModel.reset()
        FakeModulesModel.active = release(1, "1.0.0", "a")
        FakeModulesModel.active.manifest["capabilities"][0]["completion_modes"] = [
            "webhook",
            "polling",
        ]
        client = CapturingClient(
            {
                "result_type": "accepted",
                "handle": {"external_job_id": "mixed-mode", "opaque_data": {}},
                "next_poll_after_seconds": 1.5,
            }
        )
        service = UserModuleService(
            client=client,
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        job = await service.create_media_job(
            module_id="demo.echo",
            requester_id="user-1",
            operation="echo_image",
            media_kind="image",
            prompt="hello",
            inputs=[],
            parameters={},
            idempotency_key="idem-mixed-no-base",
        )
        await service.dispatch_job(job.job_id)

        stored = FakeJobsModel.jobs[job.job_id]
        assert stored.status == "running"
        assert stored.next_poll_at is not None
        submit_parameters = client.requests[0].params["request"]["parameters"]
        assert "callback" not in submit_parameters

    monkeypatch.delenv("ZJT_USER_MODULE_CALLBACK_BASE_URL", raising=False)
    monkeypatch.setenv("ZJT_USER_MODULES_DIR", str(tmp_path / "module-data-mixed-no-base"))
    asyncio.run(scenario())


def test_webhook_only_module_fails_without_callback_base(monkeypatch, tmp_path):
    """纯 webhook 模块在回调地址未配置时仍失败（无轮询兜底）。"""

    async def scenario():
        FakeJobsModel.reset()
        FakeModulesModel.active = release(1, "1.0.0", "a")
        FakeModulesModel.active.manifest["capabilities"][0]["completion_modes"] = ["webhook"]
        client = CapturingClient(
            {
                "result_type": "accepted",
                "handle": {"external_job_id": "webhook-only-2", "opaque_data": {}},
            }
        )
        service = UserModuleService(
            client=client,
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        job = await service.create_media_job(
            module_id="demo.echo",
            requester_id="user-1",
            operation="echo_image",
            media_kind="image",
            prompt="hello",
            inputs=[],
            parameters={},
            idempotency_key="idem-webhook-only-2",
        )
        await service.dispatch_job(job.job_id)

        stored = FakeJobsModel.jobs[job.job_id]
        assert stored.status == "failed"
        assert stored.error["code"] == "MODULE_DISPATCH_FAILED"
        assert "callback_base_url" in stored.error["message"]

    monkeypatch.delenv("ZJT_USER_MODULE_CALLBACK_BASE_URL", raising=False)
    monkeypatch.setenv("ZJT_USER_MODULES_DIR", str(tmp_path / "module-data-webhook-only-2"))
    asyncio.run(scenario())


def test_rpc_timeout_is_clamped_to_protocol_limit(monkeypatch, tmp_path):
    """deadline 落库舍入可能使剩余时间微超 RpcRequest.timeout_seconds 上限（le=1800）。"""

    from datetime import datetime, timedelta, timezone

    async def scenario():
        FakeJobsModel.reset()
        FakeModulesModel.active = release(1, "1.0.0", "a")
        FakeModulesModel.active.manifest["capabilities"][0]["completion_modes"] = ["polling"]
        client = CapturingClient(
            {
                "result_type": "accepted",
                "handle": {"external_job_id": "clamped", "opaque_data": {}},
                "next_poll_after_seconds": 2.0,
            }
        )
        service = UserModuleService(
            client=client,
            modules_model=FakeModulesModel,
            jobs_model=FakeJobsModel,
        )
        job = await service.create_media_job(
            module_id="demo.echo",
            requester_id="user-1",
            operation="echo_image",
            media_kind="image",
            prompt="hello",
            inputs=[],
            parameters={},
            idempotency_key="idem-clamped",
        )
        # 模拟 DATETIME 秒级舍入：deadline 比协议上限多出亚秒
        FakeJobsModel.jobs[job.job_id].timeout_at = datetime.now(timezone.utc).replace(
            tzinfo=None
        ) + timedelta(seconds=USER_MODULE_MAX_OPERATION_TIMEOUT_SECONDS + 0.5)
        await service.dispatch_job(job.job_id)

        stored = FakeJobsModel.jobs[job.job_id]
        assert stored.status == "running"
        assert client.requests[0].timeout_seconds <= USER_MODULE_MAX_OPERATION_TIMEOUT_SECONDS

    from config.constant import USER_MODULE_MAX_OPERATION_TIMEOUT_SECONDS

    monkeypatch.setenv("ZJT_USER_MODULES_DIR", str(tmp_path / "module-data-clamped"))
    monkeypatch.delenv("ZJT_USER_MODULE_CALLBACK_BASE_URL", raising=False)
    asyncio.run(scenario())
