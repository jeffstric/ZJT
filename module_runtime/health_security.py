"""候选 Driver health 结果的跨进程安全归一化。"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Optional

from config.constant import (
    USER_MODULE_HEALTH_SAFE_MISSING_SECRETS_MAX_ITEMS,
    USER_MODULE_HEALTH_SAFE_SECRET_NAME_MAX_CHARS,
    USER_MODULE_RELEASE_VALIDATION_ERROR_MESSAGES,
)


_SECRET_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def release_validation_default_code(status_code: int) -> str:
    if status_code == 504:
        return "RELEASE_VALIDATION_TIMEOUT"
    if status_code == 422:
        return "RELEASE_RUNTIME_VALIDATION_FAILED"
    if status_code >= 500:
        return "RELEASE_VALIDATION_UNAVAILABLE"
    return "RELEASE_RUNTIME_VALIDATION_FAILED"


def normalize_release_validation_code(
    code: object,
    *,
    status_code: int = 422,
) -> str:
    candidate = str(code or "").strip()
    if candidate in USER_MODULE_RELEASE_VALIDATION_ERROR_MESSAGES:
        return candidate
    return release_validation_default_code(status_code)


def release_validation_safe_message(code: object, *, status_code: int = 422) -> str:
    normalized = normalize_release_validation_code(code, status_code=status_code)
    return USER_MODULE_RELEASE_VALIDATION_ERROR_MESSAGES[normalized]


def sanitize_health_details(
    details: object,
    *,
    declared_secret_names: Optional[Iterable[str]] = None,
) -> dict:
    """仅保留公开的缺失密钥名称，丢弃模块提供的任意值。"""

    if not isinstance(details, Mapping):
        return {}
    raw_missing = details.get("missing_secrets")
    if not isinstance(raw_missing, (list, tuple, set, frozenset)):
        return {}

    declared = None
    if declared_secret_names is not None:
        declared = {
            str(name).strip()
            for name in declared_secret_names
            if isinstance(name, str) and str(name).strip()
        }

    safe_names = []
    seen = set()
    for raw_name in raw_missing:
        if not isinstance(raw_name, str):
            continue
        name = raw_name.strip()
        if (
            not name
            or len(name) > USER_MODULE_HEALTH_SAFE_SECRET_NAME_MAX_CHARS
            or not _SECRET_NAME_PATTERN.fullmatch(name)
            or (declared is not None and name not in declared)
            or name in seen
        ):
            continue
        seen.add(name)
        safe_names.append(name)
        if len(safe_names) >= USER_MODULE_HEALTH_SAFE_MISSING_SECRETS_MAX_ITEMS:
            break

    return {"missing_secrets": safe_names} if safe_names else {}
