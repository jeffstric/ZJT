"""核心、Supervisor 与 Runner 之间的稳定 JSON-RPC 信封。"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RpcModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RpcRequest(RpcModel):
    request_id: str = Field(min_length=1, max_length=128)
    method: Literal["health", "submit", "poll", "cancel", "handle_callback"]
    params: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=120, gt=0, le=1800)


class SupervisorRpcRequest(RpcRequest):
    release_id: int = Field(gt=0)
    module_id: str = Field(min_length=3, max_length=128)
    module_version: str = Field(min_length=1, max_length=64)
    code_digest: str = Field(min_length=8, max_length=80)


class ValidateReleaseRequest(RpcModel):
    release_id: int = Field(gt=0)
    module_id: str = Field(min_length=3, max_length=128)
    module_version: str = Field(min_length=1, max_length=64)
    code_digest: str = Field(min_length=8, max_length=80)


class RpcError(RpcModel):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)
    retryable: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)


class RpcResponse(RpcModel):
    request_id: str
    ok: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[RpcError] = None

    @classmethod
    def success(cls, request_id: str, result: Dict[str, Any]) -> "RpcResponse":
        return cls(request_id=request_id, ok=True, result=result)

    @classmethod
    def failure(
        cls,
        request_id: str,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> "RpcResponse":
        return cls(
            request_id=request_id,
            ok=False,
            error=RpcError(
                code=code,
                message=message,
                retryable=retryable,
                details=details or {},
            ),
        )
