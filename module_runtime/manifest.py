"""用户模块 manifest v1 校验与摘要计算。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config.constant import (
    USER_MODULE_MANIFEST_SCHEMA_VERSION,
    USER_MODULE_MAX_MANIFEST_BYTES,
    USER_MODULE_MEDIA_DRIVER_PROTOCOL,
    USER_MODULE_RPC_PROTOCOL_VERSION,
    USER_MODULE_SDK_VERSION,
)
from config.version import get_app_version
from module_runtime.protocol import CompletionMode, ExecutionModel, MediaKind


MODULE_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$"
VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$"
ENTRYPOINT_PATTERN = r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$"
DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
RESERVED_SECRET_NAMES = {
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
    "PYTHONPATH",
    "PYTHONHOME",
    "ZJT_MODULE_RUNNER_TOKEN",
}


class StrictManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CapabilityManifest(StrictManifestModel):
    operation: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    media_kind: MediaKind
    completion_modes: Set[CompletionMode] = Field(min_length=1)
    request_schema: Dict = Field(default_factory=dict)
    result_schema: Dict = Field(default_factory=dict)

    @field_validator("completion_modes", mode="before")
    @classmethod
    def normalize_completion_modes(cls, values):
        if isinstance(values, (list, tuple, set)):
            return sorted(set(values))
        return values


class PermissionManifest(StrictManifestModel):
    network_hosts: List[str] = Field(default_factory=list, max_length=64)
    secret_names: List[str] = Field(default_factory=list, max_length=32)
    asset_read: bool = False
    asset_write: bool = False

    @field_validator("network_hosts", "secret_names")
    @classmethod
    def unique_values(cls, values: List[str]) -> List[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("权限列表不能包含空值")
        if len(set(normalized)) != len(normalized):
            raise ValueError("权限列表不能包含重复值")
        if any(len(value) > 255 for value in normalized):
            raise ValueError("权限名称过长")
        return normalized

    @field_validator("secret_names")
    @classmethod
    def valid_secret_names(cls, values: List[str]) -> List[str]:
        import re

        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", value) for value in values):
            raise ValueError("secret_names 必须是大写环境变量名")
        if RESERVED_SECRET_NAMES.intersection(values):
            raise ValueError("secret_names 不能声明运行时保留环境变量")
        return values


class ResourceLimitsManifest(StrictManifestModel):
    operation_timeout_seconds: int = Field(default=120, ge=1, le=1800)
    max_concurrency: int = Field(default=4, ge=1, le=64)
    max_request_bytes: int = Field(default=1024 * 1024, ge=1024, le=2 * 1024 * 1024)


class ModuleManifest(StrictManifestModel):
    manifest_schema_version: int = USER_MODULE_MANIFEST_SCHEMA_VERSION
    module_id: str = Field(min_length=3, max_length=128, pattern=MODULE_ID_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(pattern=VERSION_PATTERN)
    code_digest: Optional[str] = Field(default=None, pattern=DIGEST_PATTERN)
    entrypoint: str = Field(pattern=ENTRYPOINT_PATTERN)
    rpc_protocol: str = USER_MODULE_RPC_PROTOCOL_VERSION
    driver_protocol: str = USER_MODULE_MEDIA_DRIVER_PROTOCOL
    sdk_version: str = USER_MODULE_SDK_VERSION
    core_compat: str = Field(
        default_factory=lambda: f">={get_app_version()}",
        min_length=1,
        max_length=128,
    )
    # 兜底默认值：按当前解释器动态生成（与 GenerationWorkspace._normalize_manifest_for_generation
    # 的覆写语义一致，见 docs/backend/user_modules.md）。此前写死 ">=3.10,<3.11" 会让
    # 不经工具链归一化的手写 manifest 在 Python 3.11+ 环境 ABI 校验必挂。
    python_compat: str = Field(
        default_factory=lambda: (
            f">={sys.version_info.major}.{sys.version_info.minor},"
            f"<{sys.version_info.major}.{sys.version_info.minor + 1}"
        ),
        min_length=1,
        max_length=128,
    )
    execution_model: ExecutionModel = ExecutionModel.NATIVE_ASYNC
    capabilities: List[CapabilityManifest] = Field(min_length=1, max_length=64)
    permissions: PermissionManifest = Field(default_factory=PermissionManifest)
    resource_limits: ResourceLimitsManifest = Field(default_factory=ResourceLimitsManifest)
    config_schema: Dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_protocol_and_capabilities(self) -> "ModuleManifest":
        if self.manifest_schema_version != USER_MODULE_MANIFEST_SCHEMA_VERSION:
            raise ValueError("不支持的 manifest_schema_version")
        if self.rpc_protocol != USER_MODULE_RPC_PROTOCOL_VERSION:
            raise ValueError("不支持的 rpc_protocol")
        if self.driver_protocol != USER_MODULE_MEDIA_DRIVER_PROTOCOL:
            raise ValueError("不支持的 driver_protocol")
        if self.execution_model != ExecutionModel.NATIVE_ASYNC:
            raise ValueError("MVP 仅支持 native_async 执行模型")
        operations = [item.operation for item in self.capabilities]
        if len(set(operations)) != len(operations):
            raise ValueError("capabilities.operation 不能重复")
        return self


def load_manifest(path: Path, *, require_digest: bool = True) -> ModuleManifest:
    """从磁盘加载 manifest，并在解析前限制文件大小。"""

    manifest_path = Path(path)
    size = manifest_path.stat().st_size
    if size > USER_MODULE_MAX_MANIFEST_BYTES:
        raise ValueError(f"manifest 超过大小限制: {size} bytes")
    raw = manifest_path.read_text(encoding="utf-8")
    manifest = ModuleManifest.model_validate_json(raw)
    if require_digest and not manifest.code_digest:
        raise ValueError("已安装模块必须包含 code_digest")
    return manifest


def compute_release_digest(release_dir: Path) -> str:
    """计算不可变 Release 摘要；Manifest 仅排除自身的 code_digest 字段。"""

    root = Path(release_dir).resolve(strict=True)
    digest = hashlib.sha256()
    ignored_names = {
        "checksums.json",
        ".generation-state.json",
        ".generation.lock",
    }
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name not in ignored_names
        and path.suffix != ".pyc"
        and "__pycache__" not in path.parts
    )
    for path in files:
        resolved_path = path.resolve(strict=True)
        try:
            resolved_path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Release 文件解析后越界: {path}") from exc
        if path.is_symlink():
            raise ValueError(f"Release 不允许软链接: {path}")
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if relative == "manifest.json":
            # 摘要字段不能参与自身计算，但入口、权限、能力等声明必须受完整性保护。
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("manifest.json 必须是 JSON 对象")
            # 展开协议默认值，保证草稿 Manifest 与发布后的规范化 Manifest 摘要一致。
            payload = ModuleManifest.model_validate(payload).model_dump(
                mode="json", round_trip=True
            )
            for capability in payload.get("capabilities", []):
                capability["completion_modes"] = sorted(capability["completion_modes"])
            payload.pop("code_digest", None)
            digest.update(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        else:
            with path.open("rb") as file_obj:
                for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                    digest.update(chunk)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def write_manifest_schema(path: Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(ModuleManifest.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
