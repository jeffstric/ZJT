"""用户媒体模块 v1 协议 DTO 与 Python SDK 接口。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Protocol, Set, Union
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MediaKind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class ExecutionModel(str, Enum):
    NATIVE_ASYNC = "native_async"
    BLOCKING_IO = "blocking_io"
    CPU_BOUND = "cpu_bound"


class CompletionMode(str, Enum):
    IMMEDIATE = "immediate"
    POLLING = "polling"
    WEBHOOK = "webhook"


class JobStatus(str, Enum):
    QUEUED = "queued"
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    PAUSED = "paused"
    INCOMPATIBLE = "incompatible"


TERMINAL_JOB_STATUSES: Set[JobStatus] = {
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
    JobStatus.TIMED_OUT,
}


class DriverError(StrictModel):
    code: str = Field(min_length=1, max_length=100, pattern=r"^[A-Z][A-Z0-9_]*$")
    message: str = Field(min_length=1, max_length=4000)
    retryable: bool = False
    retry_after_seconds: Optional[float] = Field(default=None, ge=0, le=86400)
    details: Dict[str, Any] = Field(default_factory=dict)


class MediaRef(StrictModel):
    media_kind: MediaKind
    asset_id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    url: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    mime_type: Optional[str] = Field(default=None, max_length=255)
    size_bytes: Optional[int] = Field(default=None, ge=0)
    sha256: Optional[str] = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    width: Optional[int] = Field(default=None, ge=1)
    height: Optional[int] = Field(default=None, ge=1)
    duration_seconds: Optional[float] = Field(default=None, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reference(self) -> "MediaRef":
        if not self.asset_id and not self.url:
            raise ValueError("MediaRef 必须提供 asset_id 或 url")
        if self.url:
            parsed = urlparse(self.url)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
                raise ValueError("MediaRef.url 只允许完整的 http/https URL")
        return self


class DriverContext(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    job_id: str = Field(min_length=1, max_length=64)
    user_id: Optional[str] = Field(default=None, max_length=64)
    module_id: str = Field(min_length=3, max_length=128)
    module_version: str = Field(min_length=1, max_length=64)
    code_digest: str = Field(min_length=8, max_length=80)
    deadline_unix_ms: int = Field(gt=0)
    trace_id: Optional[str] = Field(default=None, max_length=128)
    # Supervisor 每次 RPC 按 Manifest 白名单解析后写入；任务表不保存密钥值。
    secrets: Dict[str, str] = Field(default_factory=dict, max_length=32, repr=False)


class MediaRequest(StrictModel):
    media_kind: MediaKind
    operation: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    prompt: Optional[str] = Field(default=None, max_length=100000)
    inputs: List[MediaRef] = Field(default_factory=list, max_length=32)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=128)
    deadline_unix_ms: int = Field(gt=0)


class TaskHandle(StrictModel):
    external_job_id: str = Field(min_length=1, max_length=512)
    opaque_data: Dict[str, Any] = Field(default_factory=dict)


class Completed(StrictModel):
    result_type: Literal["completed"] = "completed"
    outputs: List[MediaRef] = Field(default_factory=list, max_length=64)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Accepted(StrictModel):
    result_type: Literal["accepted"] = "accepted"
    handle: TaskHandle
    next_poll_after_seconds: Optional[float] = Field(default=None, ge=0, le=86400)


class Rejected(StrictModel):
    result_type: Literal["rejected"] = "rejected"
    error: DriverError


SubmitResult = Union[Completed, Accepted, Rejected]


class PollResult(StrictModel):
    status: JobStatus
    progress: Optional[float] = Field(default=None, ge=0, le=1)
    outputs: List[MediaRef] = Field(default_factory=list, max_length=64)
    error: Optional[DriverError] = None
    retry_after_seconds: Optional[float] = Field(default=None, ge=0, le=86400)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_terminal_payload(self) -> "PollResult":
        if self.status == JobStatus.FAILED and self.error is None:
            raise ValueError("FAILED 状态必须包含 error")
        return self


class CancelResult(StrictModel):
    cancelled: bool
    status: JobStatus


class CallbackEvent(StrictModel):
    headers: Dict[str, str] = Field(default_factory=dict)
    payload: Dict[str, Any] = Field(default_factory=dict)


class HealthResult(StrictModel):
    healthy: bool
    message: Optional[str] = Field(default=None, max_length=1000)
    details: Dict[str, Any] = Field(default_factory=dict)


class MediaConnectorV1(Protocol):
    """模块 SDK 接口；核心只依赖其 RPC 映射，不直接 import 实现。"""

    async def initialize(self, ctx: DriverContext) -> None: ...

    async def health(self, ctx: DriverContext) -> HealthResult: ...

    async def submit(self, ctx: DriverContext, request: MediaRequest) -> SubmitResult: ...

    async def poll(self, ctx: DriverContext, handle: TaskHandle) -> PollResult: ...

    async def cancel(self, ctx: DriverContext, handle: TaskHandle) -> CancelResult: ...

    async def handle_callback(
        self,
        ctx: DriverContext,
        handle: TaskHandle,
        event: CallbackEvent,
    ) -> PollResult: ...
