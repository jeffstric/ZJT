"""唯一 Module Supervisor：管理版本化 Runner 并代理异步 RPC。"""

from __future__ import annotations

import argparse
import asyncio
import hmac
import logging
import os
import secrets
import socket
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request

from config.constant import (
    USER_MODULE_MAX_RPC_MESSAGE_BYTES,
    USER_MODULE_RPC_CONNECT_TIMEOUT_SECONDS,
    USER_MODULE_RPC_REQUEST_TIMEOUT_SECONDS,
    USER_MODULE_RUNNER_HEALTH_TIMEOUT_SECONDS,
    USER_MODULE_RUNNER_SHUTDOWN_TIMEOUT_SECONDS,
    USER_MODULE_SUPERVISOR_HOST,
    USER_MODULE_SUPERVISOR_PORT_ENV_NAME,
    USER_MODULE_SUPERVISOR_TOKEN_ENV_NAME,
    USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
)
from module_runtime.manifest import compute_release_digest, load_manifest
from module_runtime.compatibility import assert_manifest_compatible
from module_runtime.health_security import (
    release_validation_safe_message,
    sanitize_health_details,
)
from module_runtime.paths import ensure_user_module_layout, resolve_within_root
from module_runtime.protocol import DriverContext, HealthResult
from module_runtime.secret_resolver import resolve_declared_secrets
from module_runtime.rpc import (
    RpcRequest,
    RpcResponse,
    SupervisorRpcRequest,
    ValidateReleaseRequest,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunnerKey:
    module_id: str
    module_version: str
    code_digest: str


@dataclass(frozen=True)
class ReleaseDescriptor:
    release_id: int
    module_id: str
    version: str
    code_digest: str
    release_path: str

    @property
    def key(self) -> RunnerKey:
        return RunnerKey(self.module_id, self.version, self.code_digest)

    @classmethod
    def from_entity(cls, entity) -> "ReleaseDescriptor":
        return cls(
            release_id=entity.id,
            module_id=entity.module_id,
            version=entity.version,
            code_digest=entity.code_digest,
            release_path=entity.release_path,
        )


@dataclass
class RunnerHandle:
    descriptor: ReleaseDescriptor
    process: asyncio.subprocess.Process
    port: int
    token: str
    log_file: object
    declared_secret_names: tuple[str, ...] = ()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class CandidateValidationFailure(RuntimeError):
    """仅携带核心生成的固定错误码和白名单安全字段。"""

    def __init__(self, code: str, *, safe_details: Optional[dict] = None):
        super().__init__(release_validation_safe_message(code))
        self.code = code
        self.safe_details = dict(safe_details or {})


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _build_runner_env(token: str) -> Dict[str, str]:
    allowed_names = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "PYTHONIOENCODING",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed_names}
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["ZJT_MODULE_RUNNER_TOKEN"] = token
    # Runner 与用户模块代码以裸名 `module_runtime.*` 导入协议与 comfyui 助手（与生成
    # 合同、已发布模块一致）。运行时目录位于主仓根下，把项目根加入子进程模块搜索
    # 路径后裸名可正常解析，存量发布无需重新生成。
    project_root = str(Path(__file__).resolve().parents[1])
    existing_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{project_root}{os.pathsep}{existing_path}" if existing_path else project_root
    return env


def _context_with_secrets(
    params: Optional[Mapping[str, object]],
    resolved_secrets: Mapping[str, str],
) -> Dict[str, object]:
    """把本次解析的密钥写入 RPC context；调用方传入的 secrets 一律丢弃。"""

    merged = dict(params or {})
    raw_context = merged.get("context")
    context = dict(raw_context) if isinstance(raw_context, Mapping) else {}
    context["secrets"] = dict(resolved_secrets)
    merged["context"] = context
    return merged


class RunnerManager:
    def __init__(self, module_root: Optional[Path] = None):
        self.module_root = ensure_user_module_layout(module_root)
        self._handles: Dict[RunnerKey, RunnerHandle] = {}
        self._lock = asyncio.Lock()

    def _resolve_release_path(self, descriptor: ReleaseDescriptor) -> Path:
        configured = Path(descriptor.release_path)
        if configured.is_absolute():
            resolved = configured.resolve(strict=True)
            try:
                resolved.relative_to(self.module_root)
            except ValueError as exc:
                raise ValueError("Release 路径不在用户模块根目录内") from exc
            return resolved
        return resolve_within_root(
            self.module_root,
            *configured.parts,
            must_exist=True,
        )

    async def start_release(self, descriptor: ReleaseDescriptor) -> RunnerHandle:
        async with self._lock:
            existing = self._handles.get(descriptor.key)
            if existing and existing.process.returncode is None:
                return existing
            release_path = self._resolve_release_path(descriptor)
            manifest, digest = await asyncio.wait_for(
                asyncio.gather(
                    asyncio.to_thread(load_manifest, release_path / "manifest.json"),
                    asyncio.to_thread(compute_release_digest, release_path),
                ),
                timeout=USER_MODULE_RUNNER_HEALTH_TIMEOUT_SECONDS,
            )
            if manifest.module_id != descriptor.module_id or manifest.version != descriptor.version:
                raise ValueError("Release 描述与 manifest 身份不一致")
            if manifest.code_digest != descriptor.code_digest or digest != descriptor.code_digest:
                raise ValueError("Release 描述与文件摘要不一致")
            await asyncio.wait_for(
                asyncio.to_thread(assert_manifest_compatible, manifest),
                timeout=USER_MODULE_RUNNER_HEALTH_TIMEOUT_SECONDS,
            )

            port = await asyncio.to_thread(_find_free_port)
            token = secrets.token_urlsafe(32)
            log_path = resolve_within_root(
                self.module_root,
                "runtime",
                f"{descriptor.module_id}-{descriptor.code_digest[-12:]}.log",
            )
            log_file = await asyncio.to_thread(log_path.open, "ab", buffering=0)
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "module_runtime.runner",
                "--release-path",
                str(release_path),
                "--port",
                str(port),
                cwd=str(Path(__file__).resolve().parents[1]),
                env=_build_runner_env(token),
                stdout=log_file,
                stderr=log_file,
            )
            handle = RunnerHandle(
                descriptor,
                process,
                port,
                token,
                log_file,
                tuple(manifest.permissions.secret_names),
            )
            try:
                await self._wait_until_healthy(handle)
            except Exception:
                await self._stop_handle(handle)
                raise
            self._handles[descriptor.key] = handle
            return handle

    async def _wait_until_healthy(self, handle: RunnerHandle) -> None:
        deadline = asyncio.get_running_loop().time() + USER_MODULE_RUNNER_HEALTH_TIMEOUT_SECONDS
        timeout = httpx.Timeout(
            USER_MODULE_RUNNER_HEALTH_TIMEOUT_SECONDS,
            connect=USER_MODULE_RPC_CONNECT_TIMEOUT_SECONDS,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            while asyncio.get_running_loop().time() < deadline:
                if handle.process.returncode is not None:
                    raise RuntimeError(f"Runner 启动失败，退出码 {handle.process.returncode}")
                try:
                    response = await asyncio.wait_for(
                        client.get(
                            f"{handle.base_url}/health",
                            headers={"X-Module-Token": handle.token},
                        ),
                        timeout=USER_MODULE_RPC_CONNECT_TIMEOUT_SECONDS,
                    )
                    if response.status_code == 200:
                        payload = response.json()
                        if (
                            payload.get("module_id") == handle.descriptor.module_id
                            and payload.get("module_version") == handle.descriptor.version
                            and payload.get("code_digest") == handle.descriptor.code_digest
                        ):
                            return
                except (httpx.HTTPError, asyncio.TimeoutError):
                    pass
                await asyncio.sleep(0.1)
        raise TimeoutError("Runner 健康检查超时")

    async def ensure_release(
        self,
        release_id: int,
        key: RunnerKey,
    ) -> RunnerHandle:
        handle = self._handles.get(key)
        if handle and handle.process.returncode is None:
            return handle

        def load_release():
            from model.user_modules import UserModulesModel

            return UserModulesModel.get_release(release_id)

        entity = await asyncio.wait_for(
            asyncio.to_thread(load_release),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        if entity is None:
            raise KeyError(f"Release 不存在: {release_id}")
        descriptor = ReleaseDescriptor.from_entity(entity)
        if descriptor.key != key:
            raise ValueError("RPC Release 身份与数据库记录不一致")
        return await self.start_release(descriptor)

    async def load_required_releases(self) -> Dict[str, str]:
        def load_releases():
            from model.user_modules import UserModulesModel

            return UserModulesModel.list_required_releases()

        try:
            releases = await asyncio.wait_for(
                asyncio.to_thread(load_releases),
                timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning("无法读取用户模块注册表，Supervisor 将保持空载: %s", exc)
            return {}
        failures: Dict[str, str] = {}
        required_keys = {ReleaseDescriptor.from_entity(entity).key for entity in releases}
        failed_keys = set()
        for entity in releases:
            descriptor = ReleaseDescriptor.from_entity(entity)
            try:
                await self.start_release(descriptor)
            except Exception as exc:
                failed_keys.add(descriptor.key)
                message = str(exc)
                failures[f"{descriptor.module_id}@{descriptor.version}"] = message
                logger.exception("启动用户模块 Runner 失败: %s", descriptor.key)
                try:
                    from model.user_modules import UserModulesModel

                    updates = [
                        asyncio.to_thread(
                            UserModulesModel.mark_release_incompatible,
                            descriptor.release_id,
                            message,
                        ),
                        asyncio.to_thread(
                            UserModulesModel.mark_non_terminal_jobs_incompatible,
                            descriptor.release_id,
                            message,
                        ),
                    ]
                    if entity.status == "active":
                        updates.append(
                            asyncio.to_thread(
                                UserModulesModel.quarantine,
                                descriptor.module_id,
                                message,
                            )
                        )
                    await asyncio.wait_for(
                        asyncio.gather(*updates),
                        timeout=USER_MODULE_RPC_REQUEST_TIMEOUT_SECONDS,
                    )
                except Exception:
                    logger.exception("记录用户模块隔离状态失败: %s", descriptor.key)
        stale_keys = [
            key for key in self._handles if key not in required_keys or key in failed_keys
        ]
        for key in stale_keys:
            await self.stop_release(key)
        return failures

    async def _resolve_handle_secrets(self, handle: RunnerHandle) -> Dict[str, str]:
        return await asyncio.wait_for(
            asyncio.to_thread(
                resolve_declared_secrets,
                handle.declared_secret_names,
            ),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )

    async def call(self, handle: RunnerHandle, request: RpcRequest) -> RpcResponse:
        if handle.process.returncode is not None:
            self._handles.pop(handle.descriptor.key, None)
            raise RuntimeError("Runner 已退出")
        resolved_secrets = await self._resolve_handle_secrets(handle)
        request = request.model_copy(
            update={"params": _context_with_secrets(request.params, resolved_secrets)}
        )
        timeout_seconds = min(request.timeout_seconds, USER_MODULE_RPC_REQUEST_TIMEOUT_SECONDS)
        timeout = httpx.Timeout(timeout_seconds, connect=USER_MODULE_RPC_CONNECT_TIMEOUT_SECONDS)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async def send() -> bytes:
                    async with client.stream(
                        "POST",
                        f"{handle.base_url}/v1/rpc",
                        headers={"X-Module-Token": handle.token},
                        json=request.model_dump(mode="json"),
                    ) as response:
                        response.raise_for_status()
                        chunks = []
                        total = 0
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > USER_MODULE_MAX_RPC_MESSAGE_BYTES:
                                raise ValueError("Runner RPC 响应超过大小限制")
                            chunks.append(chunk)
                        return b"".join(chunks)

                raw_response = await asyncio.wait_for(
                    send(), timeout=timeout_seconds
                )
                result = RpcResponse.model_validate_json(raw_response)
                if not result.ok and result.error and result.error.code == "MODULE_TIMEOUT":
                    await self.stop_release(handle.descriptor.key)
                return result
        except (asyncio.TimeoutError, ValueError, httpx.HTTPError):
            await self.stop_release(handle.descriptor.key)
            raise

    async def stop_release(self, key: RunnerKey) -> None:
        async with self._lock:
            handle = self._handles.pop(key, None)
        if handle:
            await self._stop_handle(handle)

    async def _stop_handle(self, handle: RunnerHandle) -> None:
        if handle.process.returncode is None:
            handle.process.terminate()
            try:
                await asyncio.wait_for(
                    handle.process.wait(),
                    timeout=USER_MODULE_RUNNER_SHUTDOWN_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                handle.process.kill()
                await asyncio.wait_for(
                    handle.process.wait(),
                    timeout=USER_MODULE_RUNNER_SHUTDOWN_TIMEOUT_SECONDS,
                )
        await asyncio.to_thread(handle.log_file.close)

    async def shutdown(self) -> None:
        async with self._lock:
            handles = list(self._handles.values())
            self._handles.clear()
        await asyncio.gather(*(self._stop_handle(handle) for handle in handles), return_exceptions=True)


def create_supervisor_app(
    manager: RunnerManager,
    token: str,
    *,
    load_registry_on_start: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if load_registry_on_start:
            await manager.load_required_releases()
        yield
        await manager.shutdown()

    app = FastAPI(
        title="ZJT Module Supervisor",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > USER_MODULE_MAX_RPC_MESSAGE_BYTES:
                    raise HTTPException(status_code=413, detail="RPC 请求体过大")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Content-Length 无效") from exc
        return await call_next(request)

    def require_token(value: str | None) -> None:
        if not value or not hmac.compare_digest(value, token):
            raise HTTPException(status_code=401, detail="invalid supervisor token")

    @app.get("/health")
    async def health(x_module_token: str | None = Header(default=None)):
        require_token(x_module_token)
        return {
            "healthy": True,
            "runner_count": len(manager._handles),
            "modules": sorted({key.module_id for key in manager._handles}),
        }

    @app.post("/v1/reload")
    async def reload_registry(x_module_token: str | None = Header(default=None)):
        require_token(x_module_token)
        failures = await manager.load_required_releases()
        return {"ok": not failures, "failures": failures}

    @app.post("/v1/releases/validate")
    async def validate_release(
        request: ValidateReleaseRequest,
        x_module_token: str | None = Header(default=None),
    ):
        """在唯一 Supervisor 中启动候选版本并执行真实 Driver health 契约。"""

        require_token(x_module_token)
        key = RunnerKey(request.module_id, request.module_version, request.code_digest)
        handle = None
        try:
            handle = await manager.ensure_release(request.release_id, key)
            context = DriverContext(
                request_id=f"validate-{request.release_id}",
                job_id=f"validate-{request.release_id}",
                module_id=request.module_id,
                module_version=request.module_version,
                code_digest=request.code_digest,
                deadline_unix_ms=int((time.time() + USER_MODULE_RUNNER_HEALTH_TIMEOUT_SECONDS) * 1000),
            )
            rpc_request = RpcRequest(
                request_id=context.request_id,
                method="health",
                params={"context": context.model_dump(mode="json")},
                timeout_seconds=USER_MODULE_RUNNER_HEALTH_TIMEOUT_SECONDS,
            )
            response = await manager.call(handle, rpc_request)
            if not response.ok:
                raise CandidateValidationFailure("RELEASE_HEALTH_CALL_FAILED")
            health_result = HealthResult.model_validate(response.result)
            safe_details = sanitize_health_details(
                health_result.details,
                declared_secret_names=getattr(handle, "declared_secret_names", ()),
            )
            if not health_result.healthy:
                raise CandidateValidationFailure(
                    "RELEASE_HEALTH_UNHEALTHY",
                    safe_details=safe_details,
                )
            return {
                "ok": True,
                "health": {
                    "healthy": True,
                    "details": safe_details,
                },
            }
        except (asyncio.TimeoutError, TimeoutError) as exc:
            logger.warning(
                "候选用户模块运行时校验超时: module_id=%s release_id=%s",
                request.module_id,
                request.release_id,
            )
            raise HTTPException(
                status_code=504,
                detail={
                    "code": "RELEASE_VALIDATION_TIMEOUT",
                    "message": "候选 Release 运行时校验超时",
                },
            ) from exc
        except CandidateValidationFailure as exc:
            message = release_validation_safe_message(exc.code)
            logger.warning(
                "候选用户模块运行时校验失败: module_id=%s release_id=%s error_code=%s",
                request.module_id,
                request.release_id,
                exc.code,
            )
            detail = {
                "code": exc.code,
                "message": message,
            }
            if exc.safe_details:
                detail["details"] = exc.safe_details
            raise HTTPException(status_code=422, detail=detail) from exc
        except (KeyError, ValueError, RuntimeError) as exc:
            # 候选代码、Manifest 或 Driver health 不满足契约属于可修复的草稿错误，
            # 不应冒泡成 FastAPI 的裸 500。异常文本可能由模块间接控制，不记录、不返回。
            code = "RELEASE_RUNTIME_VALIDATION_FAILED"
            logger.warning(
                "候选用户模块运行时校验失败: module_id=%s release_id=%s error_code=%s error_type=%s",
                request.module_id,
                request.release_id,
                code,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "code": code,
                    "message": release_validation_safe_message(code),
                },
            ) from exc
        except Exception as exc:
            # logger.exception 会把模块可控异常文本写入日志，因此这里只记录固定元数据。
            logger.error(
                "候选用户模块运行时校验发生内部错误: module_id=%s release_id=%s error_type=%s",
                request.module_id,
                request.release_id,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "RELEASE_VALIDATION_INTERNAL_ERROR",
                    "message": release_validation_safe_message(
                        "RELEASE_VALIDATION_INTERNAL_ERROR"
                    ),
                },
            ) from exc
        finally:
            if handle is not None:
                await manager.stop_release(key)

    @app.post("/v1/rpc", response_model=RpcResponse)
    async def rpc(
        request: SupervisorRpcRequest,
        x_module_token: str | None = Header(default=None),
    ):
        require_token(x_module_token)
        # token 只做进程间鉴权（开源版无商业许可证门禁，主仓版本已移除执行检查点）
        key = RunnerKey(request.module_id, request.module_version, request.code_digest)
        try:
            handle = await manager.ensure_release(request.release_id, key)
            runner_request = RpcRequest(
                request_id=request.request_id,
                method=request.method,
                params=request.params,
                timeout_seconds=request.timeout_seconds,
            )
            return await manager.call(handle, runner_request)
        except asyncio.TimeoutError:
            return RpcResponse.failure(
                request.request_id,
                "RUNNER_TIMEOUT",
                "Runner 超时并已终止",
                retryable=True,
            )
        except Exception as exc:
            return RpcResponse.failure(
                request.request_id,
                "RUNNER_UNAVAILABLE",
                str(exc),
                retryable=True,
            )

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="ZJT user module supervisor")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get(USER_MODULE_SUPERVISOR_PORT_ENV_NAME, "19091")),
    )
    args = parser.parse_args()
    token = os.environ.get(USER_MODULE_SUPERVISOR_TOKEN_ENV_NAME, "")
    if not token:
        raise RuntimeError(f"{USER_MODULE_SUPERVISOR_TOKEN_ENV_NAME} is required")
    manager = RunnerManager()
    app = create_supervisor_app(manager, token)
    uvicorn.run(
        app,
        host=USER_MODULE_SUPERVISOR_HOST,
        port=args.port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
