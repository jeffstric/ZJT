"""Web/scheduler 使用的异步 Supervisor 客户端。"""

from __future__ import annotations

import asyncio
import os

import httpx

from config.constant import (
    USER_MODULE_RPC_CONNECT_TIMEOUT_SECONDS,
    USER_MODULE_MAX_RPC_MESSAGE_BYTES,
    USER_MODULE_RPC_REQUEST_TIMEOUT_SECONDS,
    USER_MODULE_SUPERVISOR_TOKEN_ENV_NAME,
    USER_MODULE_SUPERVISOR_URL_ENV_NAME,
)
from module_runtime.health_security import (
    normalize_release_validation_code,
    release_validation_safe_message,
    sanitize_health_details,
)
from module_runtime.rpc import RpcResponse, SupervisorRpcRequest, ValidateReleaseRequest


class SupervisorClientError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int = 503,
        safe_details: dict | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.safe_details = sanitize_health_details(safe_details)


def _release_validation_failure(response: httpx.Response) -> tuple[str, str]:
    """只接受已知错误码，并使用核心固定摘要；绝不信任远端 message。"""

    candidate_code = None
    try:
        payload = response.json()
    except ValueError:
        payload = None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        candidate_code = detail.get("code")
    code = normalize_release_validation_code(
        candidate_code,
        status_code=response.status_code,
    )
    return code, release_validation_safe_message(code, status_code=response.status_code)


def _release_validation_safe_details(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(detail, dict):
        return {}
    return sanitize_health_details(detail.get("details"))


def _release_validation_success(payload: object) -> dict:
    """成功响应同样去掉 Supervisor/Driver 提供的 message 和任意 details 值。"""

    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ValueError("候选 Release 校验成功响应格式无效")
    health = payload.get("health")
    if not isinstance(health, dict) or health.get("healthy") is not True:
        raise ValueError("候选 Release 校验成功响应缺少健康状态")
    return {
        "ok": True,
        "health": {
            "healthy": True,
            "details": sanitize_health_details(health.get("details")),
        },
    }


def sanitize_release_validation_error(exc: Exception) -> SupervisorClientError:
    """在 API/持久化边界再次移除可能由替代 Client 注入的原始文本。"""

    try:
        status_code = int(getattr(exc, "status_code", 503) or 503)
    except (TypeError, ValueError):
        status_code = 503
    if status_code < 400 or status_code > 599:
        status_code = 503
    code = normalize_release_validation_code(
        getattr(exc, "code", None),
        status_code=status_code,
    )
    return SupervisorClientError(
        code,
        release_validation_safe_message(code, status_code=status_code),
        retryable=bool(getattr(exc, "retryable", status_code >= 500)),
        status_code=status_code,
        safe_details=sanitize_health_details(getattr(exc, "safe_details", None)),
    )


class SupervisorClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or os.environ.get(USER_MODULE_SUPERVISOR_URL_ENV_NAME, "")).rstrip("/")
        self.token = token or os.environ.get(USER_MODULE_SUPERVISOR_TOKEN_ENV_NAME, "")

    def _require_configuration(self) -> None:
        if not self.base_url or not self.token:
            raise SupervisorClientError(
                "SUPERVISOR_NOT_CONFIGURED",
                "用户模块 Supervisor 尚未启动",
                retryable=True,
            )

    async def call(self, request: SupervisorRpcRequest) -> RpcResponse:
        self._require_configuration()
        timeout_seconds = min(request.timeout_seconds, USER_MODULE_RPC_REQUEST_TIMEOUT_SECONDS)
        timeout = httpx.Timeout(timeout_seconds, connect=USER_MODULE_RPC_CONNECT_TIMEOUT_SECONDS)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async def send() -> bytes:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/v1/rpc",
                        headers={"X-Module-Token": self.token},
                        json=request.model_dump(mode="json"),
                    ) as response:
                        response.raise_for_status()
                        chunks = []
                        total = 0
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > USER_MODULE_MAX_RPC_MESSAGE_BYTES:
                                raise ValueError("Supervisor RPC 响应超过大小限制")
                            chunks.append(chunk)
                        return b"".join(chunks)

                raw_response = await asyncio.wait_for(
                    send(), timeout=timeout_seconds
                )
        except asyncio.TimeoutError as exc:
            raise SupervisorClientError(
                "SUPERVISOR_TIMEOUT",
                "用户模块 Supervisor 调用超时",
                retryable=True,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise SupervisorClientError(
                "SUPERVISOR_UNAVAILABLE",
                f"用户模块 Supervisor 不可用: {exc}",
                retryable=True,
            ) from exc
        result = RpcResponse.model_validate_json(raw_response)
        if not result.ok:
            error = result.error
            raise SupervisorClientError(
                error.code if error else "SUPERVISOR_CALL_FAILED",
                error.message if error else "Supervisor 调用失败",
                retryable=bool(error and error.retryable),
            )
        return result

    async def health(self) -> dict:
        self._require_configuration()
        timeout_seconds = max(
            USER_MODULE_RPC_CONNECT_TIMEOUT_SECONDS * 2,
            USER_MODULE_RPC_CONNECT_TIMEOUT_SECONDS + 0.5,
        )
        timeout = httpx.Timeout(
            timeout_seconds,
            connect=USER_MODULE_RPC_CONNECT_TIMEOUT_SECONDS,
        )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await asyncio.wait_for(
                    client.get(
                        f"{self.base_url}/health",
                        headers={"X-Module-Token": self.token},
                    ),
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                if not payload.get("healthy"):
                    raise ValueError("Supervisor 健康检查返回异常")
                return payload
        except (asyncio.TimeoutError, httpx.HTTPError, ValueError) as exc:
            raise SupervisorClientError(
                "SUPERVISOR_UNAVAILABLE",
                f"用户模块 Supervisor 健康检查失败: {exc}",
                retryable=True,
            ) from exc

    async def reload(self) -> dict:
        self._require_configuration()
        timeout = httpx.Timeout(
            USER_MODULE_RPC_REQUEST_TIMEOUT_SECONDS,
            connect=USER_MODULE_RPC_CONNECT_TIMEOUT_SECONDS,
        )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await asyncio.wait_for(
                    client.post(
                        f"{self.base_url}/v1/reload",
                        headers={"X-Module-Token": self.token},
                    ),
                    timeout=USER_MODULE_RPC_REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
                if not payload.get("ok"):
                    raise ValueError(f"部分 Runner 重载失败: {payload.get('failures', {})}")
                return payload
        except (asyncio.TimeoutError, httpx.HTTPError, ValueError) as exc:
            raise SupervisorClientError(
                "SUPERVISOR_RELOAD_FAILED",
                f"Supervisor 重载失败: {exc}",
                retryable=True,
            ) from exc

    async def validate_release(self, request: ValidateReleaseRequest) -> dict:
        self._require_configuration()
        timeout = httpx.Timeout(
            USER_MODULE_RPC_REQUEST_TIMEOUT_SECONDS,
            connect=USER_MODULE_RPC_CONNECT_TIMEOUT_SECONDS,
        )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await asyncio.wait_for(
                    client.post(
                        f"{self.base_url}/v1/releases/validate",
                        headers={"X-Module-Token": self.token},
                        json=request.model_dump(mode="json"),
                    ),
                    timeout=USER_MODULE_RPC_REQUEST_TIMEOUT_SECONDS,
                )
                if response.is_error:
                    code, message = _release_validation_failure(response)
                    raise SupervisorClientError(
                        code,
                        message,
                        retryable=response.status_code >= 500,
                        status_code=response.status_code,
                        safe_details=_release_validation_safe_details(response),
                    )
                return _release_validation_success(response.json())
        except SupervisorClientError:
            raise
        except asyncio.TimeoutError as exc:
            raise SupervisorClientError(
                "RELEASE_VALIDATION_TIMEOUT",
                "候选 Release 运行时校验超时",
                retryable=True,
                status_code=504,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise SupervisorClientError(
                "RELEASE_VALIDATION_UNAVAILABLE",
                release_validation_safe_message("RELEASE_VALIDATION_UNAVAILABLE"),
                retryable=True,
                status_code=503,
            ) from exc
