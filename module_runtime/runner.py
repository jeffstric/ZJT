"""独立用户模块 Runner；仅本文件所在进程会导入用户代码。"""

from __future__ import annotations

import argparse
import asyncio
import hmac
import importlib
import inspect
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import TypeAdapter, ValidationError

from config.constant import (
    MODULE_PROTOCOL_VIOLATION,
    USER_MODULE_MAX_OPERATION_TIMEOUT_SECONDS,
    USER_MODULE_MAX_RPC_MESSAGE_BYTES,
)

# Runner 进程以裸名 `-m module_runtime.runner` 启动（PYTHONPATH 指向主仓根，
# 与用户模块代码共享同一份 `module_runtime.protocol` 协议类——pydantic 对实例做
# 类身份判定，双模块键会让协议 union 整体拒绝）。主进程/测试进程直接导入本模块；
# 与用户模块实例的差异由 `_validate_result` 的结构化校验兜底。
from module_runtime.manifest import ModuleManifest, compute_release_digest, load_manifest
from module_runtime.protocol import (
    Accepted,
    CallbackEvent,
    CancelResult,
    Completed,
    DriverContext,
    HealthResult,
    MediaRequest,
    PollResult,
    Rejected,
    SubmitResult,
    TaskHandle,
)
from module_runtime.rpc import RpcRequest, RpcResponse


SUBMIT_RESULT_ADAPTER = TypeAdapter(SubmitResult)
logger = logging.getLogger(__name__)


def _validate_result(adapter, raw_result):
    """把模块返回值按结构契约校验（跨 RPC 边界语义）。

    先序列化为结构再校验：pydantic 对实例输入做类身份（isinstance）判定，
    同一协议类被不同模块键各加载一份时会整体拒绝（真实事故：Runner 内部
    module_runtime.* 与用户模块裸名 module_runtime.* 双份类，
    协议 union 三分支全拒）。按 dict + 判别字段校验天然免疫身份差异。
    """
    raw_payload = (
        raw_result.model_dump(mode="json") if hasattr(raw_result, "model_dump") else raw_result
    )
    if isinstance(adapter, TypeAdapter):
        return adapter.validate_python(raw_payload)
    return adapter.model_validate(raw_payload)


def _lifecycle_context(manifest: ModuleManifest) -> DriverContext:
    return DriverContext(
        request_id="runner-lifecycle",
        job_id="runner-lifecycle",
        module_id=manifest.module_id,
        module_version=manifest.version,
        code_digest=manifest.code_digest or "sha256:" + "0" * 64,
        deadline_unix_ms=int((time.time() + 60) * 1000),
    )


class RunnerRuntime:
    def __init__(self, release_path: Path):
        self.release_path = Path(release_path).resolve(strict=True)
        self.manifest = load_manifest(self.release_path / "manifest.json")
        actual_digest = compute_release_digest(self.release_path)
        if actual_digest != self.manifest.code_digest:
            raise ValueError(
                f"Release 摘要不匹配: manifest={self.manifest.code_digest}, actual={actual_digest}"
            )
        self.driver = self._load_driver()
        self._concurrency = asyncio.Semaphore(self.manifest.resource_limits.max_concurrency)

    def _with_secrets(self, context: DriverContext) -> DriverContext:
        declared = {
            name
            for name in self.manifest.permissions.secret_names
            if isinstance(name, str) and name
        }
        secret_values = {
            name: value
            for name, value in (context.secrets or {}).items()
            if name in declared and isinstance(value, str) and value.strip()
        }
        return context.model_copy(update={"secrets": secret_values})

    def _load_driver(self):
        module_name, class_name = self.manifest.entrypoint.split(":", 1)
        sys.path.insert(0, str(self.release_path))
        module = importlib.import_module(module_name)
        driver_class = getattr(module, class_name)
        driver = driver_class()
        required = ("initialize", "health", "submit", "poll", "cancel", "handle_callback")
        missing = [name for name in required if not callable(getattr(driver, name, None))]
        if missing:
            raise TypeError(f"模块缺少协议方法: {', '.join(missing)}")
        if self.manifest.execution_model.value == "native_async":
            non_async = [
                name for name in required if not inspect.iscoroutinefunction(getattr(driver, name))
            ]
            if non_async:
                raise TypeError(f"native_async 模块包含非异步方法: {', '.join(non_async)}")
        return driver

    async def initialize(self) -> None:
        await asyncio.wait_for(
            self.driver.initialize(self._with_secrets(_lifecycle_context(self.manifest))),
            timeout=min(60, USER_MODULE_MAX_OPERATION_TIMEOUT_SECONDS),
        )

    async def invoke(self, request: RpcRequest) -> Dict[str, Any]:
        timeout = min(
            request.timeout_seconds,
            self.manifest.resource_limits.operation_timeout_seconds,
            USER_MODULE_MAX_OPERATION_TIMEOUT_SECONDS,
        )
        params = request.params
        context = self._with_secrets(DriverContext.model_validate(params.get("context")))
        if context.module_id != self.manifest.module_id:
            raise ValueError("RPC context.module_id 与 Runner 不匹配")
        if context.module_version != self.manifest.version:
            raise ValueError("RPC context.module_version 与 Runner 不匹配")
        if context.code_digest != self.manifest.code_digest:
            raise ValueError("RPC context.code_digest 与 Runner 不匹配")

        if request.method == "health":
            coroutine = self.driver.health(context)
            adapter = HealthResult
        elif request.method == "submit":
            coroutine = self.driver.submit(context, MediaRequest.model_validate(params.get("request")))
            adapter = SUBMIT_RESULT_ADAPTER
        elif request.method == "poll":
            coroutine = self.driver.poll(context, TaskHandle.model_validate(params.get("handle")))
            adapter = PollResult
        elif request.method == "cancel":
            coroutine = self.driver.cancel(context, TaskHandle.model_validate(params.get("handle")))
            adapter = CancelResult
        elif request.method == "handle_callback":
            coroutine = self.driver.handle_callback(
                context,
                TaskHandle.model_validate(params.get("handle")),
                CallbackEvent.model_validate(params.get("event")),
            )
            adapter = PollResult
        else:
            raise ValueError(f"不支持的 RPC 方法: {request.method}")

        async with self._concurrency:
            try:
                raw_result = await asyncio.wait_for(coroutine, timeout=timeout)
            finally:
                # 超时协程先取消；无法响应取消的 Runner 由 Supervisor 在进程层终止。
                pass
        validated = _validate_result(adapter, raw_result)
        return validated.model_dump(mode="json")


def create_runner_app(runtime: RunnerRuntime, token: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await runtime.initialize()
        yield

    app = FastAPI(title="ZJT User Module Runner", docs_url=None, redoc_url=None, lifespan=lifespan)

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
            raise HTTPException(status_code=401, detail="invalid runner token")

    @app.get("/health")
    async def health(x_module_token: str | None = Header(default=None)):
        require_token(x_module_token)
        return {
            "healthy": True,
            "module_id": runtime.manifest.module_id,
            "module_version": runtime.manifest.version,
            "code_digest": runtime.manifest.code_digest,
        }

    @app.post("/v1/rpc", response_model=RpcResponse)
    async def rpc(request: RpcRequest, x_module_token: str | None = Header(default=None)):
        require_token(x_module_token)
        try:
            result = await runtime.invoke(request)
            return RpcResponse.success(request.request_id, result)
        except asyncio.TimeoutError:
            return RpcResponse.failure(
                request.request_id,
                "MODULE_TIMEOUT",
                "模块调用超过 deadline",
                retryable=True,
            )
        except ValidationError as exc:
            logger.exception("用户模块返回不符合协议: method=%s", request.method)
            # 只透出 pydantic 的字段路径/错误类型概要（协议层结构信息），
            # 不携带模块自定义内容，遵循 health_security 固定摘要的安全模式。
            summary = "; ".join(
                f"{'.'.join(str(part) for part in err.get('loc', ())) or '<root>'}: {err.get('type')}"
                for err in exc.errors()[:5]
            )
            return RpcResponse.failure(
                request.request_id,
                MODULE_PROTOCOL_VIOLATION,
                f"模块返回不符合媒体模块协议（{summary}）",
            )
        except Exception as exc:
            logger.exception("用户模块调用失败: method=%s", request.method)
            return RpcResponse.failure(
                request.request_id,
                "MODULE_CALL_FAILED",
                "模块调用失败，请查看对应 Runner 日志",
            )

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="ZJT user module runner")
    parser.add_argument("--release-path", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    token = os.environ.get("ZJT_MODULE_RUNNER_TOKEN", "")
    if not token:
        raise RuntimeError("ZJT_MODULE_RUNNER_TOKEN is required")
    runtime = RunnerRuntime(Path(args.release_path))
    app = create_runner_app(runtime, token)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
