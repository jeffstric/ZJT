"""用户模块媒体任务编排；所有 Web 可达操作均为异步非阻塞。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from urllib.parse import urlparse

from config.constant import (
    IMAGE_UPLOAD_SYNC_WRAPPER_TIMEOUT,
    USER_MODULE_CALLBACK_BASE_URL_ENV_NAME,
    USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
    USER_MODULE_MAX_OPERATION_TIMEOUT_SECONDS,
    USER_MODULE_SCHEDULER_BATCH_SIZE,
)
from module_runtime.client import SupervisorClient, SupervisorClientError
from module_runtime.callbacks import build_callback_token, hash_callback_token
from module_runtime.manifest import ModuleManifest
from module_runtime.protocol import (
    Accepted,
    CallbackEvent,
    Completed,
    DriverContext,
    JobStatus,
    MediaKind,
    MediaRef,
    MediaRequest,
    PollResult,
    Rejected,
    TaskHandle,
)
from module_runtime.rpc import SupervisorRpcRequest

logger = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _deadline_unix_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


class UserModuleServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def declared_host_output_urls(outputs: List[MediaRef], network_hosts: List[str]) -> List[str]:
    """选出 host 落在模块 network_hosts 内的输出 URL（局域网 Comfy /view 等）。"""

    hosts = {str(item).strip().lower() for item in network_hosts if str(item).strip()}
    urls: List[str] = []
    for output in outputs:
        url = str(getattr(output, "url", "") or "")
        if not url:
            continue
        netloc = urlparse(url).netloc.lower()
        if netloc and netloc in hosts:
            urls.append(url)
    return urls


def replace_output_urls(outputs: List[MediaRef], url_map: Dict[str, str]) -> List[MediaRef]:
    rewritten: List[MediaRef] = []
    for output in outputs:
        url = str(getattr(output, "url", "") or "")
        mapped = url_map.get(url)
        if mapped and mapped != url:
            rewritten.append(output.model_copy(update={"url": mapped}))
        else:
            rewritten.append(output)
    return rewritten


async def _db_call(function, *args, **kwargs):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(function, *args, **kwargs),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
    finally:
        pass


class UserModuleService:
    def __init__(self, *, client=None, modules_model=None, jobs_model=None):
        if modules_model is None or jobs_model is None:
            from model.user_modules import ModuleJobsModel, UserModulesModel

            modules_model = modules_model or UserModulesModel
            jobs_model = jobs_model or ModuleJobsModel
        self.client = client or SupervisorClient()
        self.modules_model = modules_model
        self.jobs_model = jobs_model

    async def get_active_manifest(self, module_id: str) -> ModuleManifest:
        release = await _db_call(self.modules_model.get_active_release, module_id)
        if release is None:
            raise UserModuleServiceError(
                "MODULE_UNAVAILABLE",
                "模块未启用或没有可用 Release",
                status_code=503,
            )
        try:
            return ModuleManifest.model_validate(release.manifest)
        except Exception as exc:
            raise UserModuleServiceError(
                "MODULE_MANIFEST_INVALID",
                f"模块 Manifest 无效: {exc}",
                status_code=503,
            ) from exc

    async def create_media_job(
        self,
        *,
        module_id: str,
        requester_id: str,
        operation: str,
        media_kind: MediaKind,
        prompt: Optional[str],
        inputs: List[MediaRef],
        parameters: Dict[str, Any],
        idempotency_key: str,
    ):
        normalized_media_kind = MediaKind(media_kind)
        release = await _db_call(self.modules_model.get_active_release, module_id)
        if release is None:
            raise UserModuleServiceError(
                "MODULE_UNAVAILABLE",
                "模块未启用或没有可用 Release",
                status_code=503,
            )
        manifest = ModuleManifest.model_validate(release.manifest)
        capability = next(
            (item for item in manifest.capabilities if item.operation == operation),
            None,
        )
        if capability is None:
            raise UserModuleServiceError("OPERATION_NOT_FOUND", "模块未声明该操作", status_code=404)
        if capability.media_kind != normalized_media_kind:
            raise UserModuleServiceError("MEDIA_KIND_MISMATCH", "媒体类型与模块能力不匹配")

        timeout_seconds = manifest.resource_limits.operation_timeout_seconds
        # module_job 使用无时区 DATETIME，但语义固定为 UTC；查询端使用 UTC_TIMESTAMP()。
        deadline = _utcnow_naive() + timedelta(seconds=timeout_seconds)
        request = MediaRequest(
            media_kind=normalized_media_kind,
            operation=operation,
            prompt=prompt,
            inputs=inputs,
            parameters=parameters,
            idempotency_key=idempotency_key,
            deadline_unix_ms=_deadline_unix_ms(deadline),
        )
        request_size = len(
            json.dumps(
                request.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if request_size > manifest.resource_limits.max_request_bytes:
            raise UserModuleServiceError(
                "MODULE_REQUEST_TOO_LARGE",
                f"模块请求超过 Manifest 限制: {request_size} bytes",
                status_code=413,
            )
        job_id = str(uuid.uuid4())
        callback_token_hash = None
        if any(mode.value == "webhook" for mode in capability.completion_modes):
            callback_token = await asyncio.wait_for(
                asyncio.to_thread(build_callback_token, job_id),
                timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
            )
            callback_token_hash = hash_callback_token(callback_token)
        job = await _db_call(
            self.jobs_model.create,
            job_id=job_id,
            release=release,
            requester_id=requester_id,
            operation=operation,
            media_kind=normalized_media_kind.value,
            idempotency_key=idempotency_key,
            completion_modes=sorted(mode.value for mode in capability.completion_modes),
            request=request.model_dump(mode="json"),
            timeout_at=deadline,
            callback_token_hash=callback_token_hash,
        )
        return job

    async def _callback_url(self, job_id: str) -> str:
        base_url = os.environ.get(USER_MODULE_CALLBACK_BASE_URL_ENV_NAME, "").strip()
        if not base_url:
            def load_base_url():
                from config.config_util import get_config_value

                return str(
                    get_config_value("user_modules", "callback_base_url", default="") or ""
                ).strip()

            base_url = await _db_call(load_base_url)
        if not base_url:
            raise UserModuleServiceError(
                "CALLBACK_BASE_URL_MISSING",
                "webhook 模块需要配置 user_modules.callback_base_url 或 ZJT_USER_MODULE_CALLBACK_BASE_URL",
                status_code=503,
            )
        callback_token = await asyncio.wait_for(
            asyncio.to_thread(build_callback_token, job_id),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        return f"{base_url.rstrip('/')}/api/modules/callbacks/{callback_token}"

    async def get_job(self, job_id: str, requester_id: Optional[str] = None):
        job = await _db_call(self.jobs_model.get, job_id)
        if job is None:
            raise UserModuleServiceError("JOB_NOT_FOUND", "模块任务不存在", status_code=404)
        if requester_id is not None and str(job.requester_id) != str(requester_id):
            raise UserModuleServiceError("JOB_FORBIDDEN", "无权访问该模块任务", status_code=403)
        return job

    def _context(self, job) -> DriverContext:
        deadline_ms = _deadline_unix_ms(job.timeout_at)
        return DriverContext(
            request_id=str(uuid.uuid4()),
            job_id=job.job_id,
            user_id=str(job.requester_id),
            module_id=job.module_id,
            module_version=job.module_version,
            code_digest=job.code_digest,
            deadline_unix_ms=deadline_ms,
        )

    @staticmethod
    def _validate_outputs(job, outputs) -> None:
        mismatched = [
            output.media_kind.value
            for output in outputs
            if output.media_kind.value != job.media_kind
        ]
        if mismatched:
            raise ValueError(
                f"模块返回媒体类型与任务不一致: expected={job.media_kind}, actual={mismatched}"
            )

    async def _network_hosts_for_job(self, job) -> List[str]:
        release = None
        getter = getattr(self.modules_model, "get_release", None)
        if callable(getter) and getattr(job, "release_id", None):
            release = await _db_call(getter, job.release_id)
        if release is None:
            release = await _db_call(self.modules_model.get_active_release, job.module_id)
        if release is None:
            return []
        try:
            manifest = ModuleManifest.model_validate(release.manifest)
        except Exception:
            return []
        return list(manifest.permissions.network_hosts or [])

    async def _ingest_declared_host_outputs(self, job, outputs: List[MediaRef]) -> List[MediaRef]:
        hosts = await self._network_hosts_for_job(job)
        local_urls = declared_host_output_urls(outputs, hosts)
        if not local_urls:
            return outputs
        try:
            from config.config_util import get_config
            from utils.image_upload_utils import upload_local_images_to_cdn

            config = await _db_call(get_config)
            cdn_urls = await asyncio.wait_for(
                upload_local_images_to_cdn(local_urls, config),
                timeout=IMAGE_UPLOAD_SYNC_WRAPPER_TIMEOUT,
            )
        except Exception as exc:
            logger.exception("收口模块局域网输出失败: job_id=%s", job.job_id)
            raise UserModuleServiceError(
                "MODULE_OUTPUT_INGEST_FAILED",
                "无法把本地生成结果上传到图床",
                status_code=502,
            ) from exc
        url_map: Dict[str, str] = {}
        for source, target in zip(local_urls, cdn_urls or []):
            if target:
                url_map[source] = target
        if any(url not in url_map for url in local_urls):
            raise UserModuleServiceError(
                "MODULE_OUTPUT_INGEST_FAILED",
                "本地生成结果未能上传到图床",
                status_code=502,
            )
        return replace_output_urls(outputs, url_map)

    async def _complete_job_with_outputs(self, job, result) -> None:
        ingested = await self._ingest_declared_host_outputs(job, list(result.outputs or []))
        stored = result.model_copy(update={"outputs": ingested})
        await _db_call(
            self.jobs_model.mark_completed,
            job.job_id,
            stored.model_dump(mode="json"),
        )

    async def _rpc(self, job, method: str, params: Dict[str, Any]):
        timeout_left = _deadline_unix_ms(job.timeout_at) / 1000 - time.time()
        if timeout_left <= 0:
            raise UserModuleServiceError(
                "MODULE_JOB_TIMEOUT",
                "模块任务已超过总 deadline",
                status_code=408,
            )
        request = SupervisorRpcRequest(
            request_id=str(uuid.uuid4()),
            method=method,
            params=params,
            # deadline 落库为 DATETIME 秒级精度，读回可能比协议上限多出亚秒级
            # 舍入误差；钳制到 RpcRequest.timeout_seconds 的校验上限内。
            timeout_seconds=min(timeout_left, USER_MODULE_MAX_OPERATION_TIMEOUT_SECONDS),
            release_id=job.release_id,
            module_id=job.module_id,
            module_version=job.module_version,
            code_digest=job.code_digest,
        )
        return await self.client.call(request)

    async def dispatch_job(self, job_id: str) -> None:
        if not await _db_call(self.jobs_model.claim_queued, job_id):
            return
        job = await self.get_job(job_id)
        try:
            context = self._context(job)
            request = MediaRequest.model_validate(job.request)
            if "webhook" in job.completion_modes:
                parameters = dict(request.parameters)
                try:
                    callback_url = await self._callback_url(job.job_id)
                except UserModuleServiceError as exc:
                    if "polling" in job.completion_modes:
                        # 回调地址未配置时，webhook+polling 模块降级为纯轮询；
                        # 本地/内网部署收不到公网回调也能正常完成
                        logger.warning(
                            "回调地址未配置，模块任务 %s 降级为纯 polling: %s",
                            job_id,
                            exc,
                        )
                        callback_url = None
                    else:
                        raise
                if callback_url:
                    parameters["callback"] = {
                        "url": callback_url,
                        "method": "POST",
                    }
                    request = request.model_copy(update={"parameters": parameters})
            response = await self._rpc(
                job,
                "submit",
                {
                    "context": context.model_dump(mode="json"),
                    "request": request.model_dump(mode="json"),
                },
            )
            result_type = (response.result or {}).get("result_type")
            if result_type == "completed":
                result = Completed.model_validate(response.result)
                self._validate_outputs(job, result.outputs)
                await self._complete_job_with_outputs(job, result)
            elif result_type == "accepted":
                result = Accepted.model_validate(response.result)
                modes = set(job.completion_modes)
                if not modes.intersection({"polling", "webhook"}):
                    raise ValueError("模块能力仅声明 immediate，但 submit 返回了 Accepted")
                poll_delay = result.next_poll_after_seconds or 2.0
                next_poll_at = (
                    _utcnow_naive() + timedelta(seconds=poll_delay)
                    if "polling" in modes
                    else None
                )
                await _db_call(
                    self.jobs_model.mark_accepted,
                    job_id,
                    result.handle.external_job_id,
                    result.handle.model_dump(mode="json"),
                    next_poll_at,
                )
            elif result_type == "rejected":
                result = Rejected.model_validate(response.result)
                await _db_call(
                    self.jobs_model.mark_failed,
                    job_id,
                    result.error.model_dump(mode="json"),
                )
            else:
                raise ValueError("模块 submit 返回了未知结果类型")
        except SupervisorClientError as exc:
            error = {"code": exc.code, "message": str(exc), "retryable": exc.retryable}
            if exc.retryable and hasattr(self.jobs_model, "retry_submission"):
                await _db_call(self.jobs_model.retry_submission, job_id, error)
            else:
                await _db_call(self.jobs_model.mark_failed, job_id, error)
        except Exception as exc:
            logger.exception("分发用户模块任务失败: %s", job_id)
            await _db_call(
                self.jobs_model.mark_failed,
                job_id,
                {"code": "MODULE_DISPATCH_FAILED", "message": str(exc), "retryable": False},
            )

    async def poll_job(self, job) -> None:
        if not job.handle:
            await _db_call(
                self.jobs_model.mark_failed,
                job.job_id,
                {"code": "MISSING_TASK_HANDLE", "message": "异步任务缺少 handle"},
            )
            return
        try:
            context = self._context(job)
            handle = TaskHandle.model_validate(job.handle)
            response = await self._rpc(
                job,
                "poll",
                {
                    "context": context.model_dump(mode="json"),
                    "handle": handle.model_dump(mode="json"),
                },
            )
            result = PollResult.model_validate(response.result)
            if result.status == JobStatus.SUCCEEDED:
                self._validate_outputs(job, result.outputs)
                await self._complete_job_with_outputs(job, result)
            elif result.status in {JobStatus.FAILED, JobStatus.TIMED_OUT}:
                error = result.error.model_dump(mode="json") if result.error else {
                    "code": "MODULE_TASK_FAILED",
                    "message": "模块任务失败",
                }
                await _db_call(
                    self.jobs_model.mark_failed,
                    job.job_id,
                    error,
                    timed_out=result.status == JobStatus.TIMED_OUT,
                )
            elif result.status == JobStatus.CANCELLED:
                await _db_call(self.jobs_model.cancel, job.job_id)
            else:
                delay = result.retry_after_seconds or 2.0
                await _db_call(
                    self.jobs_model.update_running,
                    job.job_id,
                    progress=result.progress,
                    next_poll_at=_utcnow_naive() + timedelta(seconds=delay),
                )
        except SupervisorClientError as exc:
            # Supervisor 瞬时抖动（超时/连接重置）应延后重试，而非直接判失败
            # （见 docs/backend/user_modules_review.md M1）。
            error = {"code": exc.code, "message": str(exc), "retryable": exc.retryable}
            if exc.retryable:
                logger.warning("轮询用户模块任务暂时失败，将重试: %s", job.job_id)
                await _db_call(
                    self.jobs_model.retry_poll,
                    job.job_id,
                    error,
                    _utcnow_naive() + timedelta(seconds=2),
                )
            else:
                await _db_call(self.jobs_model.mark_failed, job.job_id, error)
        except Exception as exc:
            logger.exception("轮询用户模块任务失败: %s", job.job_id)
            await _db_call(
                self.jobs_model.mark_failed,
                job.job_id,
                {"code": "MODULE_POLL_FAILED", "message": str(exc), "retryable": False},
            )

    async def cancel_job(self, job_id: str, requester_id: str):
        job = await self.get_job(job_id, requester_id)
        terminal = {"succeeded", "failed", "cancelled", "timed_out"}
        if job.status in terminal:
            return job
        if job.handle:
            try:
                context = self._context(job)
                handle = TaskHandle.model_validate(job.handle)
                await self._rpc(
                    job,
                    "cancel",
                    {
                        "context": context.model_dump(mode="json"),
                        "handle": handle.model_dump(mode="json"),
                    },
                )
            except Exception:
                logger.warning("模块任务取消 RPC 失败，仍将本地任务置为取消: %s", job_id)
        await _db_call(self.jobs_model.cancel, job_id)
        return await self.get_job(job_id, requester_id)

    async def handle_callback(
        self,
        callback_token: str,
        *,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ):
        token_hash = hash_callback_token(callback_token)
        job = await _db_call(self.jobs_model.get_by_callback_token_hash, token_hash)
        if job is None:
            raise UserModuleServiceError("CALLBACK_NOT_FOUND", "回调令牌无效", status_code=404)
        if job.status in {
            "succeeded",
            "failed",
            "cancelled",
            "timed_out",
            "paused",
            "incompatible",
        }:
            return job
        if not job.handle:
            raise UserModuleServiceError("CALLBACK_NOT_READY", "模块任务尚未建立回调句柄", status_code=409)
        try:
            context = self._context(job)
            event = CallbackEvent(headers=headers, payload=payload)
            response = await self._rpc(
                job,
                "handle_callback",
                {
                    "context": context.model_dump(mode="json"),
                    "handle": TaskHandle.model_validate(job.handle).model_dump(mode="json"),
                    "event": event.model_dump(mode="json"),
                },
            )
            result = PollResult.model_validate(response.result)
            if result.status == JobStatus.SUCCEEDED:
                self._validate_outputs(job, result.outputs)
                await self._complete_job_with_outputs(job, result)
            elif result.status in {JobStatus.FAILED, JobStatus.TIMED_OUT}:
                error = result.error.model_dump(mode="json") if result.error else {
                    "code": "MODULE_CALLBACK_FAILED",
                    "message": "模块回调处理失败",
                }
                await _db_call(
                    self.jobs_model.mark_failed,
                    job.job_id,
                    error,
                    timed_out=result.status == JobStatus.TIMED_OUT,
                )
            elif result.status == JobStatus.CANCELLED:
                await _db_call(self.jobs_model.cancel, job.job_id)
            else:
                delay = result.retry_after_seconds or 2.0
                next_poll_at = (
                    _utcnow_naive() + timedelta(seconds=delay)
                    if "polling" in job.completion_modes
                    else None
                )
                await _db_call(
                    self.jobs_model.update_running,
                    job.job_id,
                    progress=result.progress,
                    next_poll_at=next_poll_at,
                )
        except UserModuleServiceError:
            raise
        except SupervisorClientError as exc:
            raise UserModuleServiceError(
                exc.code,
                str(exc),
                status_code=503,
            ) from exc
        except Exception as exc:
            logger.exception("处理用户模块回调结果失败: %s", job.job_id)
            raise UserModuleServiceError(
                "MODULE_CALLBACK_INVALID",
                f"模块回调结果无效: {exc}",
                status_code=502,
            ) from exc
        return await self.get_job(job.job_id)

    async def process_pending_jobs(self) -> None:
        expired = await _db_call(
            self.jobs_model.list_expired,
            USER_MODULE_SCHEDULER_BATCH_SIZE,
        )
        for job in expired:
            await _db_call(
                self.jobs_model.mark_failed,
                job.job_id,
                {"code": "MODULE_JOB_TIMEOUT", "message": "模块任务超过总 deadline"},
                timed_out=True,
            )
        queued = await _db_call(
            self.jobs_model.list_queued,
            USER_MODULE_SCHEDULER_BATCH_SIZE,
        )
        await asyncio.gather(*(self.dispatch_job(job.job_id) for job in queued))
        due = await _db_call(
            self.jobs_model.list_due,
            USER_MODULE_SCHEDULER_BATCH_SIZE,
        )
        await asyncio.gather(*(self.poll_job(job) for job in due))


_service: Optional[UserModuleService] = None


def get_user_module_service() -> UserModuleService:
    global _service
    if _service is None:
        _service = UserModuleService()
    return _service


def module_job_to_dict(job) -> Dict[str, Any]:
    return {
        "job_id": job.job_id,
        "module_id": job.module_id,
        "module_version": job.module_version,
        "code_digest": job.code_digest,
        "operation": job.operation,
        "media_kind": job.media_kind,
        "status": job.status,
        "progress": float(job.progress) if job.progress is not None else None,
        "result": job.result,
        "error": job.error,
        "create_at": job.create_at.isoformat() if job.create_at else None,
        "update_at": job.update_at.isoformat() if job.update_at else None,
        "complete_at": job.complete_at.isoformat() if job.complete_at else None,
    }
