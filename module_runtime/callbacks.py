"""可重建且不落库明文的模块任务回调令牌。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from module_runtime.paths import ensure_user_module_layout, resolve_within_root


CALLBACK_KEY_FILE = "callback-signing.key"


def _load_or_create_callback_key() -> bytes:
    root = ensure_user_module_layout()
    key_path = resolve_within_root(root, "state", CALLBACK_KEY_FILE)
    try:
        key = key_path.read_bytes()
    except FileNotFoundError:
        candidate = secrets.token_bytes(32)
        try:
            with key_path.open("xb") as handle:
                handle.write(candidate)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                key_path.chmod(0o600)
            except OSError:
                pass
            key = candidate
        except FileExistsError:
            key = key_path.read_bytes()
    if len(key) != 32:
        raise ValueError("用户模块 callback signing key 无效")
    return key


def build_callback_token(job_id: str) -> str:
    digest = hmac.new(_load_or_create_callback_key(), job_id.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def hash_callback_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
