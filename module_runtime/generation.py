"""大模型用户模块生成的 staging、校验、审批和不可变发布。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from filelock import FileLock, Timeout as FileLockTimeout

from config.constant import (
    USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
    USER_MODULE_GENERATION_LOCK_TIMEOUT_SECONDS,
    USER_MODULE_GENERATION_MAX_FILE_BYTES,
    USER_MODULE_GENERATION_MAX_SEARCH_RESULTS,
    USER_MODULE_GENERATION_REVISION_TIMEOUT_SECONDS,
    USER_MODULE_GENERATION_VALIDATION_TIMEOUT_SECONDS,
    USER_MODULE_REVIEW_ENABLED,
    USER_MODULE_REVIEW_MAX_CODE_CHARS,
    USER_MODULE_REVIEW_MAX_CONCURRENCY,
    USER_MODULE_REVIEW_MODEL,
    USER_MODULE_REVIEW_MODEL_ID,
    USER_MODULE_REVIEW_OPERATION_TIMEOUT_SECONDS,
    USER_MODULE_REVIEW_POLICY_VERSION,
    USER_MODULE_REVIEW_REQUIRED,
    USER_MODULE_REVIEW_TIMEOUT_SECONDS,
    USER_MODULE_REVIEW_VENDOR_ID,
)
from config.version import get_app_version
from module_runtime.client import (
    SupervisorClient,
    sanitize_release_validation_error,
)
from module_runtime.health_security import (
    normalize_release_validation_code,
    release_validation_safe_message,
    sanitize_health_details,
)
from module_runtime.manifest import ModuleManifest, compute_release_digest
from module_runtime.paths import (
    atomic_write_json,
    atomic_write_text,
    ensure_user_module_layout,
    resolve_within_root,
)
from module_runtime.validation import validate_staging
from module_runtime.rpc import ValidateReleaseRequest


logger = logging.getLogger(__name__)


GENERATION_STATE_FILE = ".generation-state.json"
# 运行时与合同已随用户模块子系统迁入主仓（develop_f1214 起）。
# 根路径失效会让生成智能体的检索永远空结果，LLM 反复换词死循环后放弃写码
# （runninghub.image2videov9 真实事故），新增根时务必确认路径存在。
ALLOWED_SEARCH_ROOTS = (
    "module_runtime",
    "pyproject.toml",
    "docs/backend/user_modules.md",
    "script_writer_core/skills/generate-user-api-module",
)
BLOCKED_SEARCH_PARTS = {
    ".git",
    ".venv",
    "config_prod.yml",
    "config_dev.yml",
    "data",
    "logs",
    "upload",
}
PUBLIC_REVISION_SUFFIXES = {".py", ".md", ".json", ".toml", ".yaml", ".yml"}


class UserModuleReviewBusyError(RuntimeError):
    """同一草稿已有审核请求在执行。"""


class UserModuleReviewCapacityError(RuntimeError):
    """系统级审核并发槽已用尽。"""


def _public_source_files(project_root: Path):
    files = []
    for configured in ALLOWED_SEARCH_ROOTS:
        root = (project_root / configured).resolve(strict=False)
        candidates = [root] if root.is_file() else root.rglob("*") if root.exists() else []
        files.extend(
            path
            for path in candidates
            if path.is_file()
            and path.suffix.lower() in PUBLIC_REVISION_SUFFIXES
            and "__pycache__" not in path.parts
        )
    return sorted(set(files))


def current_core_revision(project_root: Path) -> str:
    git_revision = "unknown"
    try:
        from scripts.upgrade_check import find_git_binary

        git_binary = find_git_binary()
        if not git_binary:
            raise OSError("git binary not found")
        completed = subprocess.run(
            [git_binary, "-c", "credential.helper=", "rev-parse", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=USER_MODULE_GENERATION_REVISION_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            git_revision = completed.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass

    # HEAD 不足以覆盖尚未提交的 SDK 改动；审批基线同时绑定实际公开协议内容。
    digest = hashlib.sha256(git_revision.encode("utf-8"))
    for path in _public_source_files(project_root):
        digest.update(path.relative_to(project_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class GenerationWorkspace:
    def __init__(
        self,
        module_root: Optional[Path] = None,
        project_root: Optional[Path] = None,
        registry=None,
    ):
        self.module_root = ensure_user_module_layout(module_root)
        self.project_root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
        self._registry = registry
        self.review_lock_root = resolve_within_root(self.module_root, "state", "review-locks")
        self.review_lock_root.mkdir(parents=True, exist_ok=True)
        self.review_slot_root = resolve_within_root(self.module_root, "state", "review-slots")
        self.review_slot_root.mkdir(parents=True, exist_ok=True)

    @property
    def registry(self):
        if self._registry is None:
            from model.user_modules import UserModulesModel

            self._registry = UserModulesModel
        return self._registry

    def create(
        self,
        *,
        module_id: str,
        requirement: str,
        created_by: str,
        review_model: Optional[str] = None,
        review_model_id: Optional[int] = None,
        review_vendor_id: Optional[int] = None,
    ) -> Dict:
        generation_id = str(uuid.uuid4())
        staging = resolve_within_root(self.module_root, "staging", generation_id)
        staging.mkdir(parents=True, exist_ok=False)
        state = {
            "generation_id": generation_id,
            "module_id": module_id,
            "requirement": requirement,
            "created_by": created_by,
            "status": "draft",
            "base_revision": current_core_revision(self.project_root),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "validated_at": None,
            "validation": None,
            "validation_digest": None,
            "review_required": bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
            "review_policy_version": USER_MODULE_REVIEW_POLICY_VERSION,
            "review_target": None,
            "review": None,
            "review_cache": None,
            "review_attempt": None,
            "reviewed_at": None,
            "review_gate": {
                "required": bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                "publishable": not bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                "reason_code": (
                    "review_missing"
                    if USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED
                    else None
                ),
            },
            "approved_at": None,
            "release_id": None,
        }
        normalized_review_model = str(review_model or "").strip()
        if normalized_review_model:
            if not review_model_id or int(review_model_id) <= 0:
                raise ValueError("审核模型 ID 无效")
            if not review_vendor_id or int(review_vendor_id) <= 0:
                raise ValueError("审核模型供应商 ID 无效")
            state["review_target"] = {
                "model": normalized_review_model,
                "model_id": int(review_model_id),
                "vendor_id": int(review_vendor_id),
                "source": "generation_model",
            }
        self._ensure_release_metadata(state)
        atomic_write_json(staging / GENERATION_STATE_FILE, state)
        return state

    def _ensure_release_metadata(self, state: Dict) -> bool:
        """为旧草稿补齐服务端拥有的发布元数据，返回是否发生变更。"""

        changed = False
        core_version = str(state.get("core_version") or get_app_version(self.project_root))
        generation_id = str(state.get("generation_id") or uuid.uuid4())
        major_version = core_version.split(".", 1)[0]
        defaults = {
            "core_version": core_version,
            "suggested_release_version": (
                f"{core_version}+gen.{generation_id.replace('-', '')[:8]}"
            ),
            "suggested_core_compat": (
                f">={core_version},<{int(major_version) + 1}.0.0"
                if major_version.isdigit()
                else f">={core_version}"
            ),
        }
        for key, value in defaults.items():
            if not state.get(key):
                state[key] = value
                changed = True
        return changed

    def staging_path(self, generation_id: str) -> Path:
        return resolve_within_root(
            self.module_root,
            "staging",
            generation_id,
            must_exist=True,
        )

    def read_state(self, generation_id: str) -> Dict:
        path = self.staging_path(generation_id) / GENERATION_STATE_FILE
        return json.loads(path.read_text(encoding="utf-8"))

    def assert_owner(self, generation_id: str, requester_id: str) -> None:
        state = self.read_state(generation_id)
        if str(state.get("created_by")) != str(requester_id):
            raise PermissionError("generation 不属于当前管理员")

    def list_generations(
        self,
        *,
        module_id: Optional[str] = None,
        status: Optional[str] = None,
        created_by: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """列出后台可见的生成工作区，不暴露锁文件或任意磁盘路径。"""

        normalized_module_id = (module_id or "").strip()
        normalized_status = (status or "").strip()
        normalized_created_by = (created_by or "").strip()
        max_results = max(1, min(int(limit), USER_MODULE_GENERATION_MAX_SEARCH_RESULTS))
        staging_root = resolve_within_root(self.module_root, "staging", must_exist=True)
        states = []
        for candidate in staging_root.iterdir():
            if not candidate.is_dir():
                continue
            try:
                staging = resolve_within_root(
                    staging_root,
                    candidate.name,
                    must_exist=True,
                )
                state_path = staging / GENERATION_STATE_FILE
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if not isinstance(state, dict):
                    continue
                if normalized_module_id and state.get("module_id") != normalized_module_id:
                    continue
                if normalized_status and state.get("status") != normalized_status:
                    continue
                if normalized_created_by and str(state.get("created_by")) != normalized_created_by:
                    continue
                item = dict(state)
                item["updated_at"] = datetime.fromtimestamp(
                    state_path.stat().st_mtime,
                    tz=timezone.utc,
                ).isoformat()
                states.append(item)
            except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
                # 单个损坏或并发删除的草稿不应使整个后台列表不可用。
                continue
        states.sort(
            key=lambda item: item.get("updated_at") or item.get("created_at") or "",
            reverse=True,
        )
        return states[:max_results]

    @contextmanager
    def _generation_lock(self, generation_id: str):
        staging = self.staging_path(generation_id)
        lock_path = staging / ".generation.lock"
        deadline = time.monotonic() + USER_MODULE_GENERATION_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                with lock_path.open("x", encoding="ascii") as lock_file:
                    lock_file.write(f"{os.getpid()}\n")
                break
            except FileExistsError:
                try:
                    age = time.time() - lock_path.stat().st_mtime
                    stale_after = max(
                        USER_MODULE_GENERATION_LOCK_TIMEOUT_SECONDS * 3,
                        USER_MODULE_GENERATION_VALIDATION_TIMEOUT_SECONDS * 2,
                    )
                    if age > stale_after:
                        lock_path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError("generation 正被另一个请求修改")
                time.sleep(0.05)
        try:
            yield staging
        finally:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    @contextmanager
    def review_singleflight(self, generation_id: str):
        """跨进程单航班锁；锁位于 state 目录，不参与草稿代码摘要。"""

        # staging_path 同时校验 generation_id 必须落在受控目录中。
        self.staging_path(generation_id)
        lock_path = resolve_within_root(self.review_lock_root, f"{generation_id}.lock")
        lock = FileLock(str(lock_path), timeout=0, thread_local=False)
        try:
            lock.acquire()
        except FileLockTimeout as exc:
            raise UserModuleReviewBusyError("该草稿的 AI 安全审核正在进行，请稍后刷新") from exc
        try:
            yield
        finally:
            if lock.is_locked:
                lock.release()

    @contextmanager
    def review_execution_slot(self):
        """跨进程全局并发槽，避免审核请求无限占满 LLM/线程资源。"""

        acquired: Optional[FileLock] = None
        for index in range(max(1, int(USER_MODULE_REVIEW_MAX_CONCURRENCY))):
            candidate = FileLock(
                str(resolve_within_root(self.review_slot_root, f"slot-{index}.lock")),
                timeout=0,
                thread_local=False,
            )
            try:
                candidate.acquire()
                acquired = candidate
                break
            except FileLockTimeout:
                continue
        if acquired is None:
            raise UserModuleReviewCapacityError("AI 安全审核繁忙，请稍后重新校验")
        try:
            yield
        finally:
            if acquired.is_locked:
                acquired.release()

    def write_file(self, generation_id: str, relative_path: str, content: str) -> Dict:
        with self._generation_lock(generation_id) as staging:
            state = self.read_state(generation_id)
            if state["status"] not in {
                "draft",
                "validation_failed",
                "validated",
                "runtime_validation_failed",
            }:
                raise ValueError("当前 generation 状态不允许写文件")
            data = content.encode("utf-8")
            if len(data) > USER_MODULE_GENERATION_MAX_FILE_BYTES:
                raise ValueError("文件超过大小限制")
            path = resolve_within_root(staging, relative_path)
            if path.name in {GENERATION_STATE_FILE, ".generation.lock"}:
                raise ValueError("不能直接修改 generation 状态文件")
            atomic_write_text(path, content)
            state["status"] = "draft"
            state["validation"] = None
            state["validation_digest"] = None
            state["validated_at"] = None
            state["review"] = None
            state["review_cache"] = None
            state["review_attempt"] = None
            state["reviewed_at"] = None
            state["review_gate"] = {
                "required": bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                "publishable": not bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                "reason_code": (
                    "review_missing"
                    if USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED
                    else None
                ),
            }
            atomic_write_json(staging / GENERATION_STATE_FILE, state)
            return {"path": path.relative_to(staging).as_posix(), "size": len(data)}

    def read_file(self, generation_id: str, relative_path: str) -> Dict:
        staging = self.staging_path(generation_id)
        path = resolve_within_root(staging, relative_path, must_exist=True)
        if not path.is_file() or path.name in {GENERATION_STATE_FILE, ".generation.lock"}:
            raise ValueError("generation 文件不存在或不可读取")
        if path.stat().st_size > USER_MODULE_GENERATION_MAX_FILE_BYTES:
            raise ValueError("generation 文件超过读取大小限制")
        return {
            "path": path.relative_to(staging).as_posix(),
            "size": path.stat().st_size,
            "content": path.read_text(encoding="utf-8"),
        }

    def list_files(self, generation_id: str) -> List[Dict]:
        staging = self.staging_path(generation_id)
        return [
            {"path": path.relative_to(staging).as_posix(), "size": path.stat().st_size}
            for path in sorted(staging.rglob("*"))
            if path.is_file() and path.name not in {GENERATION_STATE_FILE, ".generation.lock"}
        ]

    def read_manifest(self, generation_id: str) -> Optional[Dict]:
        """读取 staging 的 manifest.json（审核需要看声明）。"""
        manifest_path = self.staging_path(generation_id) / "manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    def prepare_review_snapshot(
        self,
        generation_id: str,
        *,
        max_code_chars: int = USER_MODULE_REVIEW_MAX_CODE_CHARS,
    ) -> Dict:
        """在 generation 锁内原子采集审核输入与摘要，避免审核内容和摘要错配。"""

        with self._generation_lock(generation_id) as staging:
            state = self.read_state(generation_id)
            if state.get("status") != "validated" or not (state.get("validation") or {}).get("ok"):
                raise ValueError("generation 尚未通过静态校验，不能执行 AI 安全审核")
            digest_before = compute_release_digest(staging)
            manifest_path = resolve_within_root(staging, "manifest.json", must_exist=True)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("manifest.json 必须是 JSON 对象")

            parts: List[str] = []
            total = 0
            for candidate in sorted(staging.rglob("*.py")):
                if not candidate.is_file():
                    continue
                relative = candidate.relative_to(staging).as_posix()
                path = resolve_within_root(staging, relative, must_exist=True)
                if path.is_symlink() or path.stat().st_size > USER_MODULE_GENERATION_MAX_FILE_BYTES:
                    raise ValueError(f"待审核代码文件不安全或超过单文件限制: {relative}")
                content = path.read_text(encoding="utf-8")
                if total + len(content) > max_code_chars:
                    raise ValueError(f"待审核 Python 代码超过 {max_code_chars} 字符上限")
                parts.append(f"===== {relative} =====\n{content}")
                total += len(content)
            if not parts:
                raise ValueError("没有可供 AI 安全审核的 Python 代码")
            digest_after = compute_release_digest(staging)
            if digest_before != digest_after:
                raise ValueError("采集 AI 安全审核输入时草稿发生变化")
            return {
                "manifest": manifest,
                "code": "\n\n".join(parts),
                "code_digest": digest_after,
            }

    def generation_digest(self, generation_id: str) -> str:
        """计算当前草稿摘要，用于把审核报告绑定到确切代码。"""

        return compute_release_digest(self.staging_path(generation_id))

    def write_review(
        self,
        generation_id: str,
        report: Dict,
        *,
        expected_digest: Optional[str] = None,
    ) -> Dict:
        """把审核智能体的报告写入 generation 状态（审批接口据此硬拦截）。"""
        with self._generation_lock(generation_id) as staging:
            state = self.read_state(generation_id)
            stored_report = dict(report)
            stored_report["required"] = bool(
                USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED
            )
            stored_report["review_policy_version"] = USER_MODULE_REVIEW_POLICY_VERSION
            current_digest = compute_release_digest(staging)
            if expected_digest:
                if current_digest != expected_digest:
                    stored_report = {
                        "status": "error",
                        "verdict": None,
                        "risk_level": "unknown",
                        "summary": "代码在自动审核期间发生变化，请重新校验并审核",
                        "findings": [],
                        "error_code": "review_input_changed",
                        "required": bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                        "review_policy_version": USER_MODULE_REVIEW_POLICY_VERSION,
                        "code_digest": current_digest,
                    }
            state["review"] = stored_report
            if stored_report.get("status") == "completed":
                state["review_cache"] = dict(stored_report)
            attempt = state.get("review_attempt")
            if isinstance(attempt, dict) and attempt.get("status") == "running":
                state["review_attempt"] = {
                    **attempt,
                    "status": "completed",
                    "outcome": str(stored_report.get("status") or "unknown"),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
            state["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            state["review_policy_version"] = USER_MODULE_REVIEW_POLICY_VERSION
            state["review_gate"] = build_review_gate(
                stored_report,
                required=bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                expected_digest=current_digest,
                expected_target=resolve_review_target(state)[0],
                require_target=bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
            )
            atomic_write_json(staging / GENERATION_STATE_FILE, state)
            return stored_report

    def mark_review_running(
        self,
        generation_id: str,
        *,
        expected_digest: str,
        cache_key: Dict,
    ) -> Dict:
        """在调用供应商前落盘 attempt，进程崩溃后禁止无提示地自动二次计费。"""

        with self._generation_lock(generation_id) as staging:
            current_digest = compute_release_digest(staging)
            if current_digest != expected_digest:
                raise ValueError("代码在启动 AI 安全审核前发生变化")
            state = self.read_state(generation_id)
            attempt = {
                "attempt_id": str(uuid.uuid4()),
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                **cache_key,
            }
            state["review_attempt"] = attempt
            state["review"] = {
                "status": "running",
                "verdict": None,
                "risk_level": "unknown",
                "summary": "AI 安全审核正在执行",
                "findings": [],
                "required": bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                **cache_key,
            }
            state["review_gate"] = build_review_gate(
                state["review"],
                required=bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                expected_digest=current_digest,
                expected_target=resolve_review_target(state)[0],
                require_target=bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
            )
            atomic_write_json(staging / GENERATION_STATE_FILE, state)
            return attempt

    def _normalize_manifest_for_generation(self, staging: Path, state: Dict) -> None:
        """写入由核心掌管的发布标识与兼容范围，页面和智能体均无需手填。"""

        manifest_path = staging / "manifest.json"
        if not manifest_path.is_file():
            return
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        payload["version"] = state["suggested_release_version"]
        payload["core_compat"] = state["suggested_core_compat"]
        # python_compat 由服务端按当前解释器版本生成，避免硬编码默认值与运行环境不一致
        # （见 docs/backend/user_modules_review.md M7）。用户模块在哪个解释器上构建，
        # 就约束为只在该 major.minor 下运行。
        payload["python_compat"] = f">={sys.version_info.major}.{sys.version_info.minor},<{sys.version_info.major}.{sys.version_info.minor + 1}"
        payload.pop("code_digest", None)
        atomic_write_json(manifest_path, payload)

    def validate(self, generation_id: str) -> Dict:
        with self._generation_lock(generation_id) as staging:
            state = self.read_state(generation_id)
            previous_reviews = [state.get("review"), state.get("review_cache")]
            revision_before = current_core_revision(self.project_root)
            if self._ensure_release_metadata(state):
                atomic_write_json(staging / GENERATION_STATE_FILE, state)
            self._normalize_manifest_for_generation(staging, state)
            result = validate_staging(staging)
            revision_after = current_core_revision(self.project_root)
            if revision_before != revision_after:
                result["ok"] = False
                result["findings"].append(
                    {
                        "level": "error",
                        "code": "CORE_REVISION_CHANGED",
                        "message": "智剧通公开模块 SDK 在校验期间发生变化，请重新校验",
                        "path": "",
                        "line": 0,
                    }
                )
            elif result["ok"]:
                # base_revision 表示“最近一次成功校验所针对的核心版本”，而不是
                # generation 创建时的永久快照。核心升级或公开 SDK 修改后，管理员
                # 重新校验即可安全恢复发布流程。
                state["base_revision"] = revision_after
                for stale_key in (
                    "runtime_validation_error",
                    "runtime_validation_error_code",
                    "runtime_validation_details",
                    "release_path",
                    "code_digest",
                    "approved_by",
                ):
                    state.pop(stale_key, None)
                state["release_id"] = None
                state["approved_at"] = None
            state["status"] = "validated" if result["ok"] else "validation_failed"
            state["validated_at"] = datetime.now(timezone.utc).isoformat()
            state["validation_digest"] = compute_release_digest(staging) if result["ok"] else None
            if state["validation_digest"]:
                result["code_digest"] = state["validation_digest"]
                retained_review = next(
                    (
                        dict(candidate)
                        for candidate in previous_reviews
                        if isinstance(candidate, dict)
                        and candidate.get("status") == "completed"
                        and candidate.get("code_digest") == state["validation_digest"]
                    ),
                    None,
                )
                state["review_cache"] = retained_review
                state["review"] = retained_review
                if retained_review is None:
                    state["reviewed_at"] = None
                state["review_gate"] = build_review_gate(
                    retained_review,
                    required=bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                    expected_digest=state["validation_digest"],
                    expected_target=resolve_review_target(state)[0],
                    require_target=bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                )
            else:
                state["review"] = None
                state["review_cache"] = None
                state["reviewed_at"] = None
                state["review_gate"] = {
                    "required": bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                    "publishable": False,
                    "reason_code": "static_validation_failed",
                }
            state["validation"] = result
            atomic_write_json(staging / GENERATION_STATE_FILE, state)
            return result

    def search_project(self, query: str, *, limit: int = 50) -> List[Dict]:
        normalized = query.strip().lower()
        if not normalized:
            raise ValueError("查询内容不能为空")
        results: List[Dict] = []
        max_results = min(limit, USER_MODULE_GENERATION_MAX_SEARCH_RESULTS)
        for configured in ALLOWED_SEARCH_ROOTS:
            root = (self.project_root / configured).resolve()
            candidates = [root] if root.is_file() else root.rglob("*") if root.exists() else []
            for path in candidates:
                if len(results) >= max_results:
                    return results
                if not path.is_file() or path.suffix.lower() not in PUBLIC_REVISION_SUFFIXES:
                    continue
                if any(part in BLOCKED_SEARCH_PARTS for part in path.parts):
                    continue
                if path.stat().st_size > USER_MODULE_GENERATION_MAX_FILE_BYTES:
                    continue
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except UnicodeDecodeError:
                    continue
                for line_number, line in enumerate(lines, 1):
                    if normalized in line.lower():
                        results.append(
                            {
                                "path": path.relative_to(self.project_root).as_posix(),
                                "line": line_number,
                                "text": line[:500],
                            }
                        )
                        if len(results) >= max_results:
                            return results
        return results

    def _resolve_project_source(self, relative_path: str) -> Path:
        requested = resolve_within_root(self.project_root, relative_path, must_exist=True)
        allowed = False
        for configured in ALLOWED_SEARCH_ROOTS:
            configured_path = self.project_root / configured
            if not configured_path.exists():
                continue
            configured_path = configured_path.resolve(strict=True)
            if configured_path.is_file():
                allowed = requested == configured_path
            else:
                try:
                    requested.relative_to(configured_path)
                    allowed = True
                except ValueError:
                    pass
            if allowed:
                break
        if not allowed or not requested.is_file():
            raise ValueError("项目文件不在用户模块公开 SDK 范围内")
        if any(part in BLOCKED_SEARCH_PARTS for part in requested.parts):
            raise ValueError("项目文件属于受保护路径")
        if requested.suffix.lower() not in PUBLIC_REVISION_SUFFIXES:
            raise ValueError("不支持读取该文件类型")
        if requested.stat().st_size > USER_MODULE_GENERATION_MAX_FILE_BYTES:
            raise ValueError("项目文件超过读取大小限制")
        return requested

    def read_project_file(
        self,
        relative_path: str,
        *,
        start_line: int = 1,
        end_line: int = 400,
    ) -> Dict:
        path = self._resolve_project_source(relative_path)
        if start_line < 1 or end_line < start_line or end_line - start_line > 999:
            raise ValueError("源码行范围无效或超过 1000 行")
        lines = path.read_text(encoding="utf-8").splitlines()
        selected = lines[start_line - 1 : end_line]
        return {
            "path": path.relative_to(self.project_root).as_posix(),
            "start_line": start_line,
            "end_line": start_line + len(selected) - 1 if selected else start_line,
            "total_lines": len(lines),
            "content": "\n".join(selected),
        }

    def _prepare_release(self, generation_id: str) -> tuple[Path, ModuleManifest, str]:
        staging = self.staging_path(generation_id)
        state = self.read_state(generation_id)
        if state["status"] != "validated" or not state.get("validation", {}).get("ok"):
            raise ValueError("generation 尚未通过校验")
        if state["base_revision"] != current_core_revision(self.project_root):
            raise ValueError("核心 revision 已变化，必须重新校验")
        manifest_path = staging / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload.pop("code_digest", None)
        manifest = ModuleManifest.model_validate(payload)
        if manifest.module_id != state["module_id"]:
            raise ValueError("manifest.module_id 与 generation.module_id 不一致")
        if manifest.version != state.get("suggested_release_version"):
            raise ValueError("模块内部发布标识已变化，必须重新校验")
        if manifest.core_compat != state.get("suggested_core_compat"):
            raise ValueError("智剧通兼容范围已变化，必须重新校验")
        digest = compute_release_digest(staging)
        review_block_reason = should_block_publish(
            state.get("review"),
            required=bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
            expected_digest=digest,
            expected_policy_version=USER_MODULE_REVIEW_POLICY_VERSION,
            expected_target=resolve_review_target(state)[0],
            require_target=bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
        )
        if review_block_reason:
            raise ValueError(review_block_reason)
        payload["code_digest"] = digest
        manifest = ModuleManifest.model_validate(payload)
        release_name = f"{manifest.version}-{digest.split(':', 1)[1][:16]}"
        release = resolve_within_root(
            self.module_root,
            "modules",
            manifest.module_id,
            "releases",
            release_name,
        )
        return release, manifest, digest

    def publish_staged(self, generation_id: str) -> Dict:
        with self._generation_lock(generation_id) as staging:
            return self._publish_locked(generation_id, staging)

    def _publish_locked(self, generation_id: str, staging: Path) -> Dict:
        release, manifest, digest = self._prepare_release(generation_id)
        if release.exists():
            existing_manifest = ModuleManifest.model_validate_json(
                (release / "manifest.json").read_text(encoding="utf-8")
            )
            if existing_manifest.code_digest != digest or compute_release_digest(release) != digest:
                raise ValueError("已存在的同名 Release 内容与摘要不一致")
        else:
            release.parent.mkdir(parents=True, exist_ok=True)
            temporary_release = release.parent / f".{release.name}.{uuid.uuid4().hex}.tmp"
            temporary_release.mkdir(parents=True, exist_ok=False)
            try:
                for source in staging.rglob("*"):
                    if not source.is_file() or source.name in {
                        GENERATION_STATE_FILE,
                        ".generation.lock",
                        "manifest.json",
                    }:
                        continue
                    relative = source.relative_to(staging)
                    target = temporary_release / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                atomic_write_json(
                    temporary_release / "manifest.json",
                    manifest.model_dump(mode="json", round_trip=True),
                )
                if compute_release_digest(temporary_release) != digest:
                    raise ValueError("发布复制后的内容摘要不一致")
                os.replace(temporary_release, release)
            finally:
                if temporary_release.exists():
                    shutil.rmtree(temporary_release)

        relative_path = release.relative_to(self.module_root).as_posix()
        release_id = self.registry.register_release(
            manifest.model_dump(mode="json", round_trip=True),
            relative_path,
        )
        state = self.read_state(generation_id)
        state["status"] = "runtime_validation"
        state["release_id"] = release_id
        state["release_path"] = relative_path
        state["code_digest"] = digest
        atomic_write_json(staging / GENERATION_STATE_FILE, state)
        return {
            **state,
            "manifest": manifest.model_dump(mode="json", round_trip=True),
        }

    def finalize_approval(self, generation_id: str, approved_by: str) -> Dict:
        with self._generation_lock(generation_id) as staging:
            state = self.read_state(generation_id)
            if state["status"] != "runtime_validation" or not state.get("release_id"):
                raise ValueError("Release 尚未进入运行时校验状态")
            if self.registry.mark_release_ready(state["release_id"]) != 1:
                raise RuntimeError("Release 状态已变化，无法标记为 ready")
            state["status"] = "approved"
            state["approved_at"] = datetime.now(timezone.utc).isoformat()
            state["approved_by"] = approved_by
            atomic_write_json(staging / GENERATION_STATE_FILE, state)
            return state

    def fail_approval(
        self,
        generation_id: str,
        error_code: str,
        safe_details: Optional[Dict] = None,
    ) -> Dict:
        normalized_code = normalize_release_validation_code(error_code)
        error = release_validation_safe_message(normalized_code)
        normalized_details = sanitize_health_details(safe_details)
        with self._generation_lock(generation_id) as staging:
            state = self.read_state(generation_id)
            release_id = state.get("release_id")
            if release_id:
                self.registry.mark_release_failed(release_id, error)
            state["status"] = "runtime_validation_failed"
            state["runtime_validation_error_code"] = normalized_code
            state["runtime_validation_error"] = error
            state["runtime_validation_details"] = normalized_details or None
            atomic_write_json(staging / GENERATION_STATE_FILE, state)
            return state


def resolve_review_target(state: Dict) -> tuple[Optional[Dict], Optional[str]]:
    """解析当前核心认可的精确审核模型路由。"""

    if USER_MODULE_REVIEW_MODEL and (
        int(USER_MODULE_REVIEW_VENDOR_ID or 0) > 0
        and int(USER_MODULE_REVIEW_MODEL_ID or 0) > 0
    ):
        return {
            "model": USER_MODULE_REVIEW_MODEL,
            "vendor_id": int(USER_MODULE_REVIEW_VENDOR_ID),
            "model_id": int(USER_MODULE_REVIEW_MODEL_ID),
            "source": "dedicated_review_model",
        }, None
    if USER_MODULE_REVIEW_MODEL:
        return None, "专用审核模型配置不完整，请同时配置 model、model_id 与 vendor_id"

    candidate = state.get("review_target")
    if isinstance(candidate, dict):
        try:
            model = str(candidate.get("model") or "").strip()
            vendor_id = int(candidate.get("vendor_id") or 0)
            model_id = int(candidate.get("model_id") or 0)
        except (TypeError, ValueError):
            model, vendor_id, model_id = "", 0, 0
        if model and vendor_id > 0 and model_id > 0:
            return {
                "model": model,
                "vendor_id": vendor_id,
                "model_id": model_id,
                "source": str(candidate.get("source") or "generation_model"),
            }, None
    return None, None


def review_matches_target(review: object, target: object) -> bool:
    if not isinstance(review, dict) or not isinstance(target, dict):
        return False
    try:
        return bool(
            review.get("model") == target["model"]
            and int(review.get("vendor_id") or 0) == int(target["vendor_id"])
            and int(review.get("model_id") or 0) == int(target["model_id"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def should_block_publish(
    review: Optional[Dict],
    *,
    required: bool = False,
    expected_digest: Optional[str] = None,
    expected_policy_version: Optional[str] = None,
    expected_target: Optional[Dict] = None,
    require_target: bool = False,
) -> Optional[str]:
    """审核硬拦截判定；启用强制审核时采用 fail-closed。

    纯逻辑函数，刻意放在 module_runtime 层（不依赖 services/llm），让 approve 能直接用，
    避免 module_runtime 反向依赖 services 层。审核报告由 ReviewService（services 层）产出。
    """
    if not review or review.get("status") != "completed":
        if required:
            return str(
                (review or {}).get("summary")
                or "AI 安全审核尚未完成，请重新校验草稿后再发布"
            )
        return None
    if review.get("verdict") == "reject" or review.get("risk_level") == "high":
        return str(review.get("summary") or "审核智能体判定为高风险，禁止发布")
    if expected_digest and review.get("code_digest") != expected_digest:
        return "AI 安全审核报告与当前代码不一致，请重新校验草稿后再发布"
    if expected_policy_version and review.get("review_policy_version") != expected_policy_version:
        return "AI 安全审核策略已更新，请重新校验草稿后再发布"
    if require_target and expected_target is None:
        return "当前草稿未绑定可用审核模型，请重新生成或配置专用审核模型"
    if expected_target is not None and not review_matches_target(review, expected_target):
        return "AI 安全审核模型路由已变化，请重新校验草稿后再发布"
    if required and (
        review.get("verdict") != "approve"
        or review.get("risk_level") not in {"low", "medium"}
    ):
        return "AI 安全审核结果无效，请重新校验草稿后再发布"
    return None


def build_review_gate(
    review: Optional[Dict],
    *,
    required: bool,
    expected_digest: Optional[str] = None,
    expected_policy_version: Optional[str] = None,
    expected_target: Optional[Dict] = None,
    require_target: bool = False,
) -> Dict:
    """返回前后端共用的审核发布门状态，服务端仍会在 approve 时重新判断。"""

    policy_version = expected_policy_version or USER_MODULE_REVIEW_POLICY_VERSION
    reason = should_block_publish(
        review,
        required=required,
        expected_digest=expected_digest,
        expected_policy_version=policy_version,
        expected_target=expected_target,
        require_target=require_target,
    )
    reason_code = None
    if reason:
        status = str((review or {}).get("status") or "missing")
        if status != "completed":
            reason_code = str((review or {}).get("error_code") or f"review_{status}")
        elif (review or {}).get("verdict") == "reject" or (review or {}).get("risk_level") == "high":
            reason_code = "review_rejected"
        elif expected_digest and (review or {}).get("code_digest") != expected_digest:
            reason_code = "review_digest_mismatch"
        elif policy_version and (review or {}).get("review_policy_version") != policy_version:
            reason_code = "review_policy_mismatch"
        elif require_target and expected_target is None:
            reason_code = "review_model_unavailable"
        elif expected_target is not None and not review_matches_target(review, expected_target):
            reason_code = "review_model_route_mismatch"
        else:
            reason_code = "review_invalid_result"
    return {
        "required": bool(required),
        "publishable": reason is None,
        "reason_code": reason_code,
        "reason": reason,
    }


class AsyncGenerationService:
    def __init__(self, workspace: Optional[GenerationWorkspace] = None, supervisor_client=None):
        self.workspace = workspace or GenerationWorkspace()
        self.supervisor_client = supervisor_client or SupervisorClient()

    async def create(self, **kwargs):
        return await asyncio.wait_for(
            asyncio.to_thread(self.workspace.create, **kwargs),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )

    async def get(self, generation_id: str):
        return await asyncio.wait_for(
            asyncio.to_thread(self.workspace.read_state, generation_id),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )

    async def assert_owner(self, generation_id: str, requester_id: str):
        return await asyncio.wait_for(
            asyncio.to_thread(self.workspace.assert_owner, generation_id, requester_id),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )

    async def list_generations(
        self,
        *,
        module_id: Optional[str] = None,
        status: Optional[str] = None,
        created_by: Optional[str] = None,
        limit: int = 100,
    ):
        return await asyncio.wait_for(
            asyncio.to_thread(
                self.workspace.list_generations,
                module_id=module_id,
                status=status,
                created_by=created_by,
                limit=limit,
            ),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )

    async def write_file(self, generation_id: str, relative_path: str, content: str):
        return await asyncio.wait_for(
            asyncio.to_thread(self.workspace.write_file, generation_id, relative_path, content),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )

    async def list_files(self, generation_id: str):
        return await asyncio.wait_for(
            asyncio.to_thread(self.workspace.list_files, generation_id),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )

    async def read_file(self, generation_id: str, relative_path: str):
        return await asyncio.wait_for(
            asyncio.to_thread(self.workspace.read_file, generation_id, relative_path),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )

    async def validate(self, generation_id: str, *, auth_token: Optional[str] = None):
        result = await asyncio.wait_for(
            asyncio.to_thread(self.workspace.validate, generation_id),
            timeout=USER_MODULE_GENERATION_VALIDATION_TIMEOUT_SECONDS,
        )
        if result.get("ok"):
            # AST 通过后自动触发审核智能体；审核门状态独立表达是否可发布。
            result["review"] = await self._run_review(generation_id, auth_token)
            persisted = await self.get(generation_id)
            result["review_gate"] = persisted.get("review_gate") or build_review_gate(
                result["review"],
                required=bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                expected_digest=result.get("code_digest"),
                expected_target=resolve_review_target(persisted)[0],
                require_target=bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
            )
        return result

    @staticmethod
    def _resolve_review_target(state: Dict) -> tuple[Optional[Dict], Optional[str]]:
        """兼容私有调用点；实现由模块级函数统一供审批门复用。"""

        return resolve_review_target(state)

    @staticmethod
    def _cached_review_matches(report: object, target: Dict, code_digest: str) -> bool:
        if not isinstance(report, dict) or report.get("status") != "completed":
            return False
        return bool(
            review_matches_target(report, target)
            and report.get("code_digest") == code_digest
            and report.get("review_policy_version") == USER_MODULE_REVIEW_POLICY_VERSION
        )

    @staticmethod
    def _review_cache_key(target: Dict, code_digest: str) -> Dict:
        return {
            "code_digest": code_digest,
            "model": target["model"],
            "model_id": int(target["model_id"]),
            "vendor_id": int(target["vendor_id"]),
            "review_policy_version": USER_MODULE_REVIEW_POLICY_VERSION,
        }

    @staticmethod
    def _attempt_matches_key(attempt: object, cache_key: Dict) -> bool:
        if not isinstance(attempt, dict) or attempt.get("status") != "running":
            return False
        return all(attempt.get(key) == value for key, value in cache_key.items())

    def _run_review_sync(self, generation_id: str, auth_token: Optional[str]) -> Dict:
        """锁、快照、缓存复查、LLM 和落盘均在同一 worker 线程内完成。"""

        required = bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED)
        with self.workspace.review_singleflight(generation_id):
            state = self.workspace.read_state(generation_id)
            target, target_configuration_error = self._resolve_review_target(state)
            review_digest = str(state.get("validation_digest") or "")

            if not USER_MODULE_REVIEW_ENABLED:
                review_digest = self.workspace.generation_digest(generation_id)
                report = {
                    "status": "skipped",
                    "verdict": None,
                    "risk_level": "unknown",
                    "summary": "系统管理员已关闭 AI 安全审核",
                    "findings": [],
                    "error_code": "review_disabled",
                }
            elif target is None:
                review_digest = self.workspace.generation_digest(generation_id)
                report = {
                    "status": "error",
                    "verdict": None,
                    "risk_level": "unknown",
                    "summary": target_configuration_error
                    or "当前草稿未绑定可用审核模型，请使用接口模块智能体重新生成或配置专用审核模型",
                    "findings": [],
                    "error_code": (
                        "review_model_configuration_invalid"
                        if target_configuration_error
                        else "review_model_unavailable"
                    ),
                }
            else:
                try:
                    # manifest、全部 Python 源码和摘要在 generation 锁内一次性采集。
                    snapshot = self.workspace.prepare_review_snapshot(generation_id)
                    review_digest = snapshot["code_digest"]
                    refreshed_state = self.workspace.read_state(generation_id)
                    cache_key = self._review_cache_key(target, review_digest)
                    for candidate in (
                        refreshed_state.get("review"),
                        refreshed_state.get("review_cache"),
                    ):
                        if self._cached_review_matches(candidate, target, review_digest):
                            return self.workspace.write_review(
                                generation_id,
                                dict(candidate),
                                expected_digest=review_digest,
                            )

                    if self._attempt_matches_key(
                        refreshed_state.get("review_attempt"),
                        cache_key,
                    ):
                        report = {
                            "status": "error",
                            "verdict": None,
                            "risk_level": "unknown",
                            "summary": (
                                "上次 AI 安全审核在结果落盘前中断；为避免重复计费，"
                                "本次未自动重试。请再次执行校验以确认重新调用审核模型"
                            ),
                            "findings": [],
                            "error_code": "review_attempt_interrupted",
                        }
                    else:
                        from services.user_module_review_service import UserModuleReviewService

                        with self.workspace.review_execution_slot():
                            self.workspace.mark_review_running(
                                generation_id,
                                expected_digest=review_digest,
                                cache_key=cache_key,
                            )
                            report = UserModuleReviewService(self.workspace).review(
                                generation_id,
                                model=target["model"],
                                vendor_id=target["vendor_id"],
                                model_id=target["model_id"],
                                auth_token=auth_token or "",
                                snapshot=snapshot,
                            )
                except UserModuleReviewCapacityError:
                    report = {
                        "status": "error",
                        "verdict": None,
                        "risk_level": "unknown",
                        "summary": "AI 安全审核繁忙，请稍后重新校验草稿",
                        "findings": [],
                        "error_code": "review_capacity_busy",
                    }
                except Exception as exc:
                    logger.warning(
                        "用户模块 AI 安全审核执行失败 generation_id=%s error_type=%s",
                        generation_id,
                        type(exc).__name__,
                    )
                    report = {
                        "status": "error",
                        "verdict": None,
                        "risk_level": "unknown",
                        "summary": "AI 安全审核执行失败，请检查审核模型配置后重新校验",
                        "findings": [],
                        "error_code": "review_execution_failed",
                    }

            report = {
                **report,
                "required": required,
                "code_digest": review_digest,
                "review_policy_version": USER_MODULE_REVIEW_POLICY_VERSION,
            }
            if target is not None:
                report.setdefault("model", target["model"])
                report["model_id"] = target["model_id"]
                report["vendor_id"] = target["vendor_id"]
                report["model_source"] = target["source"]
            return self.workspace.write_review(
                generation_id,
                report,
                expected_digest=review_digest,
            )

    async def _run_review(self, generation_id: str, auth_token: Optional[str]) -> Dict:
        """非阻塞等待同步审核 worker；超时不释放其文件锁或覆盖其最终结果。"""

        task = asyncio.create_task(
            asyncio.to_thread(self._run_review_sync, generation_id, auth_token)
        )
        try:
            return await asyncio.wait_for(
                asyncio.shield(task),
                timeout=USER_MODULE_REVIEW_OPERATION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("用户模块 AI 安全审核超过接口挂钟上限 generation_id=%s", generation_id)

            def _consume_background_result(done_task):
                if done_task.cancelled():
                    return
                exc = done_task.exception()
                if exc is not None:  # 只记录类型，禁止把模型回显或源码写日志。
                    logger.warning(
                        "后台用户模块审核最终失败 generation_id=%s error_type=%s",
                        generation_id,
                        type(exc).__name__,
                    )

            task.add_done_callback(_consume_background_result)
            state = await self.get(generation_id)
            return {
                "status": "running",
                "verdict": None,
                "risk_level": "unknown",
                "summary": "AI 安全审核仍在后台执行，请稍后刷新草稿状态",
                "findings": [],
                "error_code": "review_continuing_after_timeout",
                "required": bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                "code_digest": state.get("validation_digest"),
                "review_policy_version": USER_MODULE_REVIEW_POLICY_VERSION,
            }

    async def search_project(self, query: str, limit: int = 50):
        return await asyncio.wait_for(
            asyncio.to_thread(self.workspace.search_project, query, limit=limit),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )

    async def read_project_file(self, relative_path: str, start_line: int = 1, end_line: int = 400):
        return await asyncio.wait_for(
            asyncio.to_thread(
                self.workspace.read_project_file,
                relative_path,
                start_line=start_line,
                end_line=end_line,
            ),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )

    async def approve(self, generation_id: str, approved_by: str):
        # 审核硬拦截：启用 required 时未完成也禁止发布（fail-closed）。
        state = await self.get(generation_id)
        current_digest = await asyncio.wait_for(
            asyncio.to_thread(self.workspace.generation_digest, generation_id),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )
        block_reason = should_block_publish(
            state.get("review"),
            required=bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
            expected_digest=current_digest,
            expected_policy_version=USER_MODULE_REVIEW_POLICY_VERSION,
            expected_target=resolve_review_target(state)[0],
            require_target=bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
        )
        if block_reason:
            raise ValueError(block_reason)
        published = None
        manifest = None
        try:
            published = await asyncio.wait_for(
                asyncio.to_thread(
                    self.workspace.publish_staged,
                    generation_id,
                ),
                timeout=USER_MODULE_GENERATION_VALIDATION_TIMEOUT_SECONDS,
            )
            manifest = ModuleManifest.model_validate(published["manifest"])
            await self.supervisor_client.validate_release(
                ValidateReleaseRequest(
                    release_id=published["release_id"],
                    module_id=manifest.module_id,
                    module_version=manifest.version,
                    code_digest=manifest.code_digest,
                )
            )
            return await asyncio.wait_for(
                asyncio.to_thread(self.workspace.finalize_approval, generation_id, approved_by),
                timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            if published is not None:
                safe_exc = sanitize_release_validation_error(exc)
                safe_exc.safe_details = sanitize_health_details(
                    safe_exc.safe_details,
                    declared_secret_names=(
                        manifest.permissions.secret_names if manifest is not None else ()
                    ),
                )
                await asyncio.wait_for(
                    asyncio.to_thread(
                        self.workspace.fail_approval,
                        generation_id,
                        safe_exc.code,
                        safe_exc.safe_details,
                    ),
                    timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
                )
                raise safe_exc from exc
            raise
