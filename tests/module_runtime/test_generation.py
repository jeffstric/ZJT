import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from module_runtime.client import SupervisorClientError
from module_runtime.generation import AsyncGenerationService, GenerationWorkspace, should_block_publish
from module_runtime.validation import validate_staging


DRIVER_SOURCE = """
from module_runtime.protocol import CancelResult, Completed, HealthResult, JobStatus, PollResult


class Driver:
    async def initialize(self, ctx):
        return None

    async def health(self, ctx):
        return HealthResult(healthy=True)

    async def submit(self, ctx, request):
        return Completed(outputs=[])

    async def poll(self, ctx, handle):
        return PollResult(status=JobStatus.RUNNING)

    async def cancel(self, ctx, handle):
        return CancelResult(cancelled=True, status=JobStatus.CANCELLED)

    async def handle_callback(self, ctx, handle, event):
        return PollResult(status=JobStatus.SUCCEEDED)
"""


def manifest_payload():
    return {
        "manifest_schema_version": 1,
        "module_id": "demo.generated",
        "name": "Generated demo",
        "version": "1.0.0",
        "entrypoint": "src.driver:Driver",
        "rpc_protocol": "user-module-rpc/v1",
        "driver_protocol": "media-driver/v1",
        "sdk_version": "1.0.0",
        "execution_model": "native_async",
        "capabilities": [
            {
                "operation": "text_to_image",
                "media_kind": "image",
                "completion_modes": ["immediate"],
            }
        ],
    }


class FakeRegistry:
    next_id = 41
    statuses = {}

    @classmethod
    def register_release(cls, manifest, release_path):
        cls.manifest = manifest
        cls.release_path = release_path
        return cls.next_id

    @classmethod
    def mark_release_ready(cls, release_id):
        cls.statuses[release_id] = "ready"
        return 1

    @classmethod
    def mark_release_failed(cls, release_id, error):
        cls.statuses[release_id] = "failed"
        cls.error = error
        return 1


class HealthySupervisor:
    async def validate_release(self, request):
        self.request = request
        return {"ok": True}


class FailedSupervisor:
    async def validate_release(self, request):
        raise SupervisorClientError(
            "RELEASE_HEALTH_UNHEALTHY",
            "candidate unhealthy; secret=hm-generation-leaked-value",
            status_code=422,
            safe_details={
                "missing_secrets": ["EXAMPLE_API_KEY"],
                "debug": "hm-generation-leaked-value",
            },
        )


def _create_valid_generation(tmp_path: Path, supervisor):
    module_root = tmp_path / "module-data"
    project_root = tmp_path / "project"
    (project_root / "module_runtime").mkdir(parents=True)
    (project_root / "pyproject.toml").write_text(
        '[project]\nname = "test-project"\nversion = "2.1.5"\n',
        encoding="utf-8",
    )
    (project_root / "module_runtime" / "protocol.py").write_text("class MediaRequest: pass\n", encoding="utf-8")
    workspace = GenerationWorkspace(module_root, project_root, registry=FakeRegistry)
    state = workspace.create(
        module_id="demo.generated",
        requirement="create a generated image driver",
        created_by="admin-1",
        review_model="test-review-model",
        review_model_id=1,
        review_vendor_id=1,
    )
    generation_id = state["generation_id"]
    workspace.write_file(generation_id, "manifest.json", json.dumps(manifest_payload()))
    workspace.write_file(generation_id, "src/__init__.py", "")
    workspace.write_file(generation_id, "src/driver.py", DRIVER_SOURCE)
    validation = workspace.validate(generation_id)
    assert validation["ok"] is True
    workspace.write_review(
        generation_id,
        {
            "status": "completed",
            "verdict": "approve",
            "risk_level": "low",
            "summary": "测试审核通过",
            "findings": [],
            "required": True,
            "code_digest": validation["code_digest"],
            "model": "test-review-model",
            "model_id": 1,
            "vendor_id": 1,
        },
        expected_digest=validation["code_digest"],
    )
    return workspace, generation_id, AsyncGenerationService(workspace, supervisor)


def test_generation_rejects_path_escape_and_blocking_code(tmp_path: Path):
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    with pytest.raises(ValueError, match="路径"):
        workspace.write_file(generation_id, "../outside.py", "value = 1")
    workspace.write_file(generation_id, "src/driver.py", DRIVER_SOURCE + "\nasync def bad():\n    time.sleep(1)\n")
    result = workspace.validate(generation_id)
    assert result["ok"] is False
    assert any(item["code"] == "BLOCKING_CALL" for item in result["findings"])


def test_generation_rejects_aliased_blocking_call(tmp_path: Path):
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/driver.py",
        DRIVER_SOURCE + "\nfrom time import sleep as pause\nasync def bad():\n    pause(1)\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is False
    assert any(item["code"] == "BLOCKING_CALL" for item in result["findings"])


def test_generation_rejects_module_runtime_internals(tmp_path: Path):
    """仅允许 module_runtime.protocol，禁止其它子模块（中转 os/subprocess，S2 绕过A）。"""
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/driver.py",
        DRIVER_SOURCE + "\nimport module_runtime.runner\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is False
    assert any(item["code"] == "IMPORT_BLOCKED" for item in result["findings"])


def test_generation_rejects_module_runtime_internal_from_import(tmp_path: Path):
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/driver.py",
        DRIVER_SOURCE + "\nfrom module_runtime.runner import os\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is False
    assert any(item["code"] == "IMPORT_BLOCKED" for item in result["findings"])


def test_generation_rejects_inner_import_name_shadow(tmp_path: Path):
    """函数内后置 import 会遮蔽模块导入，使用处 UnboundLocalError。"""
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/driver.py",
        DRIVER_SOURCE
        + "\nimport asyncio\n\nasync def bad(ctx):\n    await asyncio.sleep(0)\n    import asyncio\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is False
    assert any(item["code"] == "INNER_IMPORT_SHADOW" for item in result["findings"])


def test_generation_allows_inner_import_before_use(tmp_path: Path):
    """函数内先 import 再使用不是 UnboundLocalError，AST 不应误伤。"""
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/driver.py",
        DRIVER_SOURCE
        + "\nasync def ok(ctx):\n    import json\n    return json.dumps({})\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is True
    assert not any(item["code"] == "INNER_IMPORT_SHADOW" for item in result["findings"])


def test_generation_rejects_dunder_introspection(tmp_path: Path):
    """对象内省逃逸：纯属性访问顺出危险能力，AST 黑名单拦不住（S2 绕过B）。"""
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/driver.py",
        DRIVER_SOURCE + "\nasync def bad():\n    return ().__class__.__bases__[0].__subclasses__()\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is False
    assert any(item["code"] == "DUNDER_ESCAPE" for item in result["findings"])


def test_generation_rejects_business_kwarg_on_http_call(tmp_path: Path):
    """业务字段写成 httpx 调用关键字参数会运行时 TypeError，只剩笼统 MODULE_CALL_FAILED。"""
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/driver.py",
        DRIVER_SOURCE
        + "\nimport httpx\n\nasync def bad(ctx):\n"
        + "    async with httpx.AsyncClient() as client:\n"
        + "        return await client.post(\"https://example.com\", json={}, idempotency_key=\"abcdefgh\")\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is False
    assert any(item["code"] == "HTTP_CALL_INVALID_KWARG" for item in result["findings"])


def test_generation_accepts_standard_http_call_kwargs(tmp_path: Path):
    """httpx 标准关键字参数（json/headers/timeout 等）不受影响。"""
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/driver.py",
        DRIVER_SOURCE
        + "\nimport httpx\n\nasync def ok(ctx):\n"
        + "    async with httpx.AsyncClient() as client:\n"
        + "        return await client.post(\"https://example.com\", json={}, headers={}, timeout=10.0)\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is True


def test_generation_rejects_sync_with_async_client(tmp_path: Path):
    """同步 with httpx.AsyncClient 会 AttributeError: __enter__，必须 async with。"""
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    nl = chr(10)
    snippet = (
        "import httpx" + nl + nl
        + "async def bad(ctx):" + nl
        + "    with httpx.AsyncClient(timeout=60.0) as client:" + nl
        + "        return await client.get('https://example.com')" + nl
    )
    workspace.write_file(generation_id, "src/driver.py", DRIVER_SOURCE + nl + snippet)
    result = workspace.validate(generation_id)
    assert result["ok"] is False
    assert any(item["code"] == "SYNC_WITH_ASYNC_CLIENT" for item in result["findings"])


def test_generation_accepts_async_with_async_client(tmp_path: Path):
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    nl = chr(10)
    snippet = (
        "import httpx" + nl + nl
        + "async def ok(ctx):" + nl
        + "    async with httpx.AsyncClient(timeout=60.0) as client:" + nl
        + "        return await client.get('https://example.com')" + nl
    )
    workspace.write_file(generation_id, "src/driver.py", DRIVER_SOURCE + nl + snippet)
    result = workspace.validate(generation_id)
    assert result["ok"] is True


def test_generation_does_not_flag_dict_get_default_kwarg(tmp_path: Path):
    """dict.get(key, default=...) 是合法 Python 写法，不得误报为 HTTP 调用非法参数。"""
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/driver.py",
        DRIVER_SOURCE + "\nasync def ok(ctx):\n    return {}.get(\"k\", default=1)\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is True


def test_generation_accepts_test_file_imports(tmp_path: Path):
    """tests/ 的 pytest 与 src.driver 导入、driver 的 __future__ 均放行（白名单正项）。"""
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/driver.py",
        DRIVER_SOURCE.replace(
            "from module_runtime.protocol import",
            "from __future__ import annotations\nfrom module_runtime.protocol import",
            1,
        ),
    )
    workspace.write_file(
        generation_id,
        "tests/test_driver.py",
        "import pytest\nfrom src.driver import Driver\n\n\ndef test_driver_exists():\n    assert Driver is not None\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is True


def test_generation_rejects_private_url_literal_in_driver(tmp_path: Path):
    """driver 中硬编码内网/回环 URL 字面量直接拒绝（供应商公网拉不到）。"""
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/driver.py",
        DRIVER_SOURCE
        + "\nBASE = \"http://192.168.10.101:9003/upload/a.png\"\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is False
    assert any(item["code"] == "URL_PRIVATE_LITERAL" for item in result["findings"])


def test_generation_allows_private_url_in_settings_and_tests(tmp_path: Path):
    """本地 ComfyUI 的 src/settings.py 与 tests/ 内网地址字面量豁免。"""
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/settings.py",
        "COMFYUI_BASE_URL = \"http://192.168.10.187:8188\"\n",
    )
    workspace.write_file(
        generation_id,
        "tests/test_driver.py",
        "LAN_URL = \"http://192.168.10.101:9003/upload/a.png\"\n\n\ndef test_lan_params_not_passed_through():\n    assert \"192.168.\" not in \"\"\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is True
    assert not any(item["code"] == "URL_PRIVATE_LITERAL" for item in result["findings"])
    assert not any(item["code"] == "IMPORT_BLOCKED" for item in result["findings"])


def test_generation_accepts_protocol_only_import(tmp_path: Path):
    """合法 driver 只 import module_runtime.protocol，校验必须通过（不误伤）。"""
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    result = workspace.validate(generation_id)
    assert result["ok"] is True


def test_generation_accepts_comfyui_helper_import(tmp_path: Path):
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/driver.py",
        DRIVER_SOURCE + "\nfrom module_runtime.comfyui import LocalComfyUIClient, apply_mapping\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is True
    assert not any(item["code"] == "IMPORT_BLOCKED" for item in result["findings"])


@pytest.mark.parametrize(
    "source",
    [
        "import httpx\nasync def bad():\n    return httpx.Client()\n",
        "import httpx\nasync def bad():\n    return httpx.get('https://example.invalid')\n",
        "import urllib.request\nasync def bad():\n    return urllib.request.urlretrieve('https://example.invalid')\n",
        "import time\nasync def bad():\n    return time.time()\n",
    ],
)
def test_generation_rejects_sync_network_and_time_imports(tmp_path: Path, source: str):
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(generation_id, "src/driver.py", DRIVER_SOURCE + "\n" + source)
    result = workspace.validate(generation_id)
    assert result["ok"] is False
    assert any(item["code"] in {"BLOCKING_CALL", "IMPORT_BLOCKED"} for item in result["findings"])


def test_generation_rejects_direct_file_access(tmp_path: Path):
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(
        generation_id,
        "src/driver.py",
        DRIVER_SOURCE + "\nasync def bad():\n    return open('config_prod.yml').read()\n",
    )
    result = workspace.validate(generation_id)
    assert result["ok"] is False
    assert any(item["code"] == "DANGEROUS_CALL" for item in result["findings"])


def test_project_read_is_limited_to_public_sdk_roots(tmp_path: Path):
    workspace, _generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    result = workspace.read_project_file("module_runtime/protocol.py", start_line=1, end_line=10)
    assert result["content"] == "class MediaRequest: pass"
    protected = workspace.project_root / "config_prod.yml"
    protected.write_text("secret: value", encoding="utf-8")
    with pytest.raises(ValueError, match="公开 SDK"):
        workspace.read_project_file("config_prod.yml")


def test_generation_file_can_be_read_but_state_and_lock_are_private(tmp_path: Path):
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    result = workspace.read_file(generation_id, "src/driver.py")
    assert "class Driver" in result["content"]
    with pytest.raises(ValueError, match="不可读取"):
        workspace.read_file(generation_id, ".generation-state.json")


def test_generation_owner_is_enforced(tmp_path: Path):
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.assert_owner(generation_id, "admin-1")
    with pytest.raises(PermissionError, match="不属于"):
        workspace.assert_owner(generation_id, "another-admin")


def test_generation_uses_pyproject_version_for_server_owned_release_fields(tmp_path: Path):
    project_root = tmp_path / "project"
    (project_root / "module_runtime").mkdir(parents=True)
    (project_root / "module_runtime" / "protocol.py").write_text(
        "class MediaRequest: pass\n", encoding="utf-8"
    )
    (project_root / "pyproject.toml").write_text(
        '[project]\nversion = "7.4.2"\n', encoding="utf-8"
    )
    workspace = GenerationWorkspace(tmp_path / "module-data", project_root, registry=FakeRegistry)
    state = workspace.create(
        module_id="demo.generated",
        requirement="create a generated image driver",
        created_by="admin-1",
    )
    generation_id = state["generation_id"]
    payload = manifest_payload()
    payload.pop("version")
    payload["core_compat"] = ">=0.0.1"
    workspace.write_file(generation_id, "manifest.json", json.dumps(payload))
    workspace.write_file(generation_id, "src/__init__.py", "")
    workspace.write_file(generation_id, "src/driver.py", DRIVER_SOURCE)

    result = workspace.validate(generation_id)

    assert result["ok"] is True
    assert result["manifest"]["version"].startswith("7.4.2+gen.")
    assert result["manifest"]["core_compat"] == ">=7.4.2,<8.0.0"
    assert state["core_version"] == "7.4.2"


def test_generation_persists_review_model_route_without_credentials(tmp_path: Path):
    project_root = tmp_path / "project"
    (project_root / "module_runtime").mkdir(parents=True)
    (project_root / "module_runtime" / "protocol.py").write_text("class MediaRequest: pass\n", encoding="utf-8")
    (project_root / "pyproject.toml").write_text('[project]\nversion = "2.1.5"\n', encoding="utf-8")
    workspace = GenerationWorkspace(tmp_path / "module-data", project_root, registry=FakeRegistry)

    state = workspace.create(
        module_id="demo.generated",
        requirement="create a generated image driver",
        created_by="admin-1",
        review_model="deepseek-v4-pro",
        review_model_id=12,
        review_vendor_id=7,
    )

    assert state["review_target"] == {
        "model": "deepseek-v4-pro",
        "model_id": 12,
        "vendor_id": 7,
        "source": "generation_model",
    }
    assert "auth_token" not in json.dumps(state)


def test_approval_marks_ready_only_after_supervisor_validation(tmp_path: Path):
    FakeRegistry.statuses = {}
    supervisor = HealthySupervisor()
    workspace, generation_id, service = _create_valid_generation(tmp_path, supervisor)
    state = asyncio.run(service.approve(generation_id, "admin-1"))
    assert state["status"] == "approved"
    assert FakeRegistry.statuses[41] == "ready"
    assert supervisor.request.release_id == 41
    release_path = workspace.module_root / state["release_path"]
    assert not (release_path / ".generation.lock").exists()

    # 重复发布同一摘要是幂等的，不会覆盖不可变 Release。
    state["status"] = "validated"
    state["validation"] = {"ok": True}
    from module_runtime.paths import atomic_write_json

    atomic_write_json(workspace.staging_path(generation_id) / ".generation-state.json", state)
    republished = workspace.publish_staged(generation_id)
    assert republished["release_id"] == 41


def test_failed_runtime_validation_cannot_become_ready(tmp_path: Path):
    FakeRegistry.statuses = {}
    workspace, generation_id, service = _create_valid_generation(tmp_path, FailedSupervisor())
    with pytest.raises(SupervisorClientError) as exc_info:
        asyncio.run(service.approve(generation_id, "admin-1"))
    assert FakeRegistry.statuses[41] == "failed"
    state = workspace.read_state(generation_id)
    assert state["status"] == "runtime_validation_failed"
    assert state["runtime_validation_error_code"] == "RELEASE_HEALTH_UNHEALTHY"
    assert state["runtime_validation_error"] == "候选 Release 的 Driver health 返回不健康"
    assert state["runtime_validation_details"] is None
    serialized = json.dumps(state, ensure_ascii=False)
    assert "hm-generation-leaked-value" not in serialized
    assert "hm-generation-leaked-value" not in FakeRegistry.error
    assert "hm-generation-leaked-value" not in str(exc_info.value)


def test_revalidate_clears_stale_runtime_validation_metadata(tmp_path: Path):
    workspace, generation_id, service = _create_valid_generation(tmp_path, FailedSupervisor())
    with pytest.raises(SupervisorClientError):
        asyncio.run(service.approve(generation_id, "admin-1"))

    validation = workspace.validate(generation_id)
    state = workspace.read_state(generation_id)

    assert validation["ok"] is True
    assert state["status"] == "validated"
    assert state["release_id"] is None
    assert state["approved_at"] is None
    assert "release_path" not in state
    assert "code_digest" not in state
    assert "runtime_validation_error" not in state
    assert "runtime_validation_error_code" not in state
    assert "runtime_validation_details" not in state


def test_uncommitted_public_sdk_change_invalidates_generation_baseline(tmp_path: Path):
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    protocol = workspace.project_root / "module_runtime" / "protocol.py"
    protocol.write_text("class MediaRequest: pass\nclass Changed: pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="revision"):
        workspace.publish_staged(generation_id)


def test_revalidate_refreshes_generation_baseline_after_public_sdk_change(tmp_path: Path):
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    protocol = workspace.project_root / "module_runtime" / "protocol.py"
    protocol.write_text("class MediaRequest: pass\nclass Changed: pass\n", encoding="utf-8")

    validation = workspace.validate(generation_id)
    published = workspace.publish_staged(generation_id)

    assert validation["ok"] is True
    assert published["status"] == "runtime_validation"


def test_public_revision_hash_is_stable_with_overlapping_allowed_roots(tmp_path: Path):
    from module_runtime.generation import current_core_revision

    project = tmp_path / "project-hash"
    skill = project / "script_writer_core" / "skills" / "generate-user-api-module"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("stable\n", encoding="utf-8")
    first = current_core_revision(project)
    second = current_core_revision(project)
    assert first == second


def test_list_generations_filters_and_sorts_without_exposing_files(tmp_path: Path):
    workspace, first_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    second = workspace.create(
        module_id="demo.other",
        requirement="create a second generated media driver",
        created_by="admin-2",
    )

    listed = workspace.list_generations(limit=10)

    assert {item["generation_id"] for item in listed} == {first_id, second["generation_id"]}
    assert all("updated_at" in item for item in listed)
    assert all("files" not in item for item in listed)
    assert [item["updated_at"] for item in listed] == sorted(
        (item["updated_at"] for item in listed), reverse=True
    )
    assert workspace.list_generations(module_id="demo.other")[0]["generation_id"] == second["generation_id"]
    assert workspace.list_generations(created_by="admin-1")
    assert workspace.list_generations(created_by="another-admin") == []
    assert workspace.list_generations(status="approved") == []


def test_list_generations_skips_corrupt_state(tmp_path: Path):
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    corrupt = workspace.module_root / "staging" / "corrupt"
    corrupt.mkdir()
    (corrupt / ".generation-state.json").write_text("not-json", encoding="utf-8")

    listed = workspace.list_generations()

    assert [item["generation_id"] for item in listed] == [generation_id]


# ===== 方案七：审核智能体 =====


def test_should_block_publish_blocks_reject_and_high():
    """reject 或 high 风险必须硬拦截（方案七）。"""
    assert should_block_publish({"status": "completed", "verdict": "reject", "summary": "发现后门"}) == "发现后门"
    assert should_block_publish({"status": "completed", "verdict": "approve", "risk_level": "high", "summary": "高风险"}) == "高风险"


def test_should_block_publish_fails_closed_when_review_is_required():
    """required 模式只允许 completed + approve + low/medium。"""
    assert should_block_publish(None) is None
    assert should_block_publish({"status": "skipped"}) is None
    assert should_block_publish({"status": "error"}) is None
    assert should_block_publish(None, required=True)
    assert should_block_publish({"status": "skipped", "summary": "已跳过"}, required=True) == "已跳过"
    assert should_block_publish({"status": "error", "summary": "审核失败"}, required=True) == "审核失败"
    assert should_block_publish({"status": "completed", "verdict": "approve", "risk_level": "low"}) is None
    assert should_block_publish({"status": "completed", "verdict": "approve", "risk_level": "medium"}) is None


def test_should_block_publish_rejects_stale_review_digest():
    review = {
        "status": "completed",
        "verdict": "approve",
        "risk_level": "low",
        "code_digest": "sha256:old",
    }
    assert "不一致" in should_block_publish(
        review,
        required=True,
        expected_digest="sha256:new",
    )


def test_approve_blocked_by_high_risk_review(tmp_path: Path):
    """审核判定 high 时，approve 必须抛错，不进入发布流程。"""
    FakeRegistry.statuses = {}  # 类变量，需重置避免前序测试残留
    workspace, generation_id, service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_review(generation_id, {
        "status": "completed", "verdict": "reject", "risk_level": "high", "summary": "代码会把密钥外传"
    })
    with pytest.raises(ValueError, match="代码会把密钥外传"):
        asyncio.run(service.approve(generation_id, "admin-1"))
    # 确认没有进入发布流程（registry 未注册）
    assert 41 not in FakeRegistry.statuses


def test_review_service_parses_llm_report(tmp_path: Path):
    """ReviewService 调 LLM 并解析结构化报告（用 fake client 避免真实调用）。"""
    from services.user_module_review_service import UserModuleReviewService

    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    fake_content = json.dumps({
        "verdict": "reject", "risk_level": "high",
        "summary": "把密钥拼进了发往未声明域名的请求",
        "findings": [{"severity": "high", "location": "src/driver.py:42",
                      "issue": "外传密钥", "explanation": "代码访问了 evil.com"}],
    })

    seen_call_kwargs = {}

    def fake_factory(model, vendor_id=None):
        class FakeClient:
            def call_api(self, **kwargs):
                seen_call_kwargs.update(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=fake_content))])
        return FakeClient()

    review_service = UserModuleReviewService(workspace, llm_client_factory=fake_factory)
    report = review_service.review(generation_id, model="audit-model", vendor_id=1, model_id=1, auth_token="t")
    assert report["status"] == "completed"
    assert report["verdict"] == "reject"
    assert report["risk_level"] == "high"
    assert report["findings"][0]["location"] == "src/driver.py:42"
    assert report["model"] == "audit-model"
    assert seen_call_kwargs["suppress_payload_logging"] is True
    assert seen_call_kwargs["max_tokens"] > 0
    # 报告写入 state 由 _run_review 负责（AsyncGenerationService 层），此处只验证 report 本身


def test_review_service_forces_high_finding_to_reject(tmp_path: Path):
    from services.user_module_review_service import UserModuleReviewService

    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    fake_content = json.dumps({
        "verdict": "approve",
        "risk_level": "low",
        "summary": "字段互相矛盾",
        "findings": [{
            "severity": "high",
            "location": "src/driver.py:1",
            "issue": "发现高风险行为",
            "explanation": "必须按更严格结论处理",
        }],
    })

    def fake_factory(model, vendor_id=None):
        class FakeClient:
            def call_api(self, **kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=fake_content))])
        return FakeClient()

    report = UserModuleReviewService(workspace, llm_client_factory=fake_factory).review(
        generation_id,
        model="audit-model",
        vendor_id=1,
        model_id=1,
        auth_token="t",
    )
    assert report["verdict"] == "reject"
    assert report["risk_level"] == "high"


def test_review_service_reads_source_content_and_rejects_truncation(tmp_path: Path, monkeypatch):
    import services.user_module_review_service as review_module

    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    seen = {}

    def fake_factory(model, vendor_id=None):
        class FakeClient:
            def call_api(self, **kwargs):
                seen["prompt"] = kwargs["messages"][1]["content"]
                payload = {
                    "verdict": "approve",
                    "risk_level": "low",
                    "summary": "代码行为正常",
                    "findings": [],
                }
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
                )
        return FakeClient()

    reviewer = review_module.UserModuleReviewService(workspace, llm_client_factory=fake_factory)
    reviewer.review(
        generation_id,
        model="audit-model",
        vendor_id=1,
        model_id=1,
        auth_token="t",
    )
    assert "===== src/driver.py =====" in seen["prompt"]
    assert "class Driver:" in seen["prompt"]

    monkeypatch.setattr(review_module, "USER_MODULE_REVIEW_MAX_CODE_CHARS", 10)
    with pytest.raises(ValueError, match="超过"):
        reviewer.review(
            generation_id,
            model="audit-model",
            vendor_id=1,
            model_id=1,
            auth_token="t",
        )


def test_review_service_does_not_persist_raw_invalid_output(tmp_path: Path):
    from services.user_module_review_service import UserModuleReviewService

    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())

    def fake_factory(model, vendor_id=None):
        class FakeClient:
            def call_api(self, **kwargs):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="not-json-secret-like-output"))]
                )
        return FakeClient()

    report = UserModuleReviewService(workspace, llm_client_factory=fake_factory).review(
        generation_id,
        model="audit-model",
        vendor_id=1,
        model_id=1,
        auth_token="t",
    )
    assert report["status"] == "error"
    assert report["error_code"] == "review_invalid_response"
    assert "raw" not in report
    assert "not-json" not in json.dumps(report)


def test_review_service_rejects_more_than_one_hundred_findings(tmp_path: Path):
    from services.user_module_review_service import UserModuleReviewService

    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    fake_content = json.dumps({
        "verdict": "approve",
        "risk_level": "low",
        "summary": "试图把高风险发现放在截断位置之后",
        "findings": [
            {
                "severity": "low" if index < 100 else "high",
                "location": f"src/driver.py:{index + 1}",
                "issue": "发现",
                "explanation": "测试",
            }
            for index in range(101)
        ],
    })

    def fake_factory(model, vendor_id=None):
        class FakeClient:
            def call_api(self, **kwargs):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=fake_content))]
                )
        return FakeClient()

    report = UserModuleReviewService(workspace, llm_client_factory=fake_factory).review(
        generation_id,
        model="audit-model",
        vendor_id=1,
        model_id=1,
        auth_token="t",
    )
    assert report["status"] == "error"
    assert report["error_code"] == "review_invalid_schema"


def test_review_report_redacts_model_echoed_credentials(tmp_path: Path):
    from services.user_module_review_service import UserModuleReviewService

    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    echoed_secret = "hm-super-secret-value-123456"
    fake_content = json.dumps({
        "verdict": "reject",
        "risk_level": "high",
        "summary": f"发现 Authorization: Bearer {echoed_secret}",
        "findings": [{
            "severity": "high",
            "location": "src/driver.py:1",
            "issue": f"api_key={echoed_secret}",
            "explanation": f"代码疑似外传 {echoed_secret}",
        }],
    })

    def fake_factory(model, vendor_id=None):
        class FakeClient:
            def call_api(self, **kwargs):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=fake_content))]
                )
        return FakeClient()

    report = UserModuleReviewService(workspace, llm_client_factory=fake_factory).review(
        generation_id,
        model="audit-model",
        vendor_id=1,
        model_id=1,
        auth_token="t",
    )
    serialized = json.dumps(report, ensure_ascii=False)
    assert echoed_secret not in serialized
    assert "[REDACTED]" in serialized


def test_review_uses_generation_model_and_persists_gate(tmp_path: Path, monkeypatch):
    from module_runtime.paths import atomic_write_json
    from services.user_module_review_service import UserModuleReviewService

    workspace, generation_id, service = _create_valid_generation(tmp_path, HealthySupervisor())
    state = workspace.read_state(generation_id)
    state["review_target"] = {
        "model": "generation-model",
        "model_id": 12,
        "vendor_id": 7,
        "source": "generation_model",
    }
    atomic_write_json(workspace.staging_path(generation_id) / ".generation-state.json", state)
    seen = {}

    def fake_review(self, target_generation_id, **kwargs):
        seen.update(kwargs)
        return {
            "status": "completed",
            "verdict": "approve",
            "risk_level": "low",
            "summary": "审核通过",
            "findings": [],
        }

    monkeypatch.setattr(UserModuleReviewService, "review", fake_review)
    result = asyncio.run(service.validate(generation_id, auth_token="normalized-token"))
    stored = workspace.read_state(generation_id)

    assert seen["model"] == "generation-model"
    assert seen["vendor_id"] == 7
    assert seen["model_id"] == 12
    assert seen["auth_token"] == "normalized-token"
    assert seen["snapshot"]["code_digest"] == result["code_digest"]
    assert "class Driver:" in seen["snapshot"]["code"]
    assert result["review"]["status"] == "completed"
    assert result["review_gate"]["publishable"] is True
    assert stored["review"]["model_source"] == "generation_model"
    assert stored["review_gate"]["publishable"] is True


def test_writing_code_clears_previous_review(tmp_path: Path):
    workspace, generation_id, _service = _create_valid_generation(tmp_path, HealthySupervisor())
    assert workspace.read_state(generation_id)["review"]["status"] == "completed"

    workspace.write_file(generation_id, "src/driver.py", DRIVER_SOURCE + "\n# changed\n")
    state = workspace.read_state(generation_id)

    assert state["review"] is None
    assert state["reviewed_at"] is None
    assert state["review_gate"]["publishable"] is False


def test_review_cache_reuses_only_exact_digest_route_and_policy(tmp_path: Path, monkeypatch):
    import module_runtime.generation as generation_module
    from module_runtime.paths import atomic_write_json
    from services.user_module_review_service import UserModuleReviewService

    workspace, generation_id, service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(generation_id, "src/driver.py", DRIVER_SOURCE + "\n# fresh review\n")
    calls = []

    def fake_review(self, target_generation_id, **kwargs):
        calls.append((target_generation_id, kwargs["model"], kwargs["model_id"], kwargs["vendor_id"]))
        return {
            "status": "completed",
            "verdict": "approve",
            "risk_level": "low",
            "summary": "审核通过",
            "findings": [],
        }

    monkeypatch.setattr(UserModuleReviewService, "review", fake_review)
    first = asyncio.run(service.validate(generation_id, auth_token="token"))
    second = asyncio.run(service.validate(generation_id, auth_token="token"))

    assert first["review_gate"]["publishable"] is True
    assert second["review_gate"]["publishable"] is True
    assert len(calls) == 1

    state = workspace.read_state(generation_id)
    state["review_target"] = {
        "model": "another-review-model",
        "model_id": 2,
        "vendor_id": 3,
        "source": "generation_model",
    }
    atomic_write_json(workspace.staging_path(generation_id) / ".generation-state.json", state)
    asyncio.run(service.validate(generation_id, auth_token="token"))
    assert len(calls) == 2

    monkeypatch.setattr(
        generation_module,
        "USER_MODULE_REVIEW_POLICY_VERSION",
        "user-module-security-review/test-v2",
    )
    asyncio.run(service.validate(generation_id, auth_token="token"))
    assert len(calls) == 3


def test_review_singleflight_rejects_concurrent_duplicate(tmp_path: Path, monkeypatch):
    from module_runtime.generation import UserModuleReviewBusyError
    from services.user_module_review_service import UserModuleReviewService

    workspace, generation_id, service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(generation_id, "src/driver.py", DRIVER_SOURCE + "\n# concurrent\n")
    started = threading.Event()
    release = threading.Event()
    calls = []

    def fake_review(self, target_generation_id, **kwargs):
        calls.append(target_generation_id)
        started.set()
        assert release.wait(timeout=5)
        return {
            "status": "completed",
            "verdict": "approve",
            "risk_level": "low",
            "summary": "审核通过",
            "findings": [],
        }

    monkeypatch.setattr(UserModuleReviewService, "review", fake_review)

    async def scenario():
        first = asyncio.create_task(service.validate(generation_id, auth_token="token"))
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 3), timeout=4)
        try:
            with pytest.raises(UserModuleReviewBusyError):
                await service.validate(generation_id, auth_token="token")
        finally:
            release.set()
        return await asyncio.wait_for(first, timeout=5)

    result = asyncio.run(scenario())
    assert result["review_gate"]["publishable"] is True
    assert calls == [generation_id]


def test_review_snapshot_change_during_llm_invalidates_report(tmp_path: Path, monkeypatch):
    from services.user_module_review_service import UserModuleReviewService

    workspace, generation_id, service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(generation_id, "src/driver.py", DRIVER_SOURCE + "\n# before review\n")
    started = threading.Event()
    release = threading.Event()

    def fake_review(self, target_generation_id, **kwargs):
        assert "# before review" in kwargs["snapshot"]["code"]
        started.set()
        assert release.wait(timeout=5)
        return {
            "status": "completed",
            "verdict": "approve",
            "risk_level": "low",
            "summary": "审核通过",
            "findings": [],
        }

    monkeypatch.setattr(UserModuleReviewService, "review", fake_review)

    async def scenario():
        review_task = asyncio.create_task(service.validate(generation_id, auth_token="token"))
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 3), timeout=4)
        await service.write_file(
            generation_id,
            "src/driver.py",
            DRIVER_SOURCE + "\n# changed during review\n",
        )
        release.set()
        return await asyncio.wait_for(review_task, timeout=5)

    result = asyncio.run(scenario())
    stored = workspace.read_state(generation_id)
    assert result["review"]["error_code"] == "review_input_changed"
    assert stored["review_gate"]["publishable"] is False


def test_publish_rejects_changed_review_route_and_policy(tmp_path: Path, monkeypatch):
    import module_runtime.generation as generation_module
    from module_runtime.paths import atomic_write_json

    workspace, generation_id, service = _create_valid_generation(tmp_path, HealthySupervisor())
    state = workspace.read_state(generation_id)
    state["review_target"] = {
        "model": "changed-model",
        "model_id": 9,
        "vendor_id": 9,
        "source": "generation_model",
    }
    atomic_write_json(workspace.staging_path(generation_id) / ".generation-state.json", state)
    with pytest.raises(ValueError, match="模型路由"):
        asyncio.run(service.approve(generation_id, "admin-1"))

    state["review_target"] = {
        "model": "test-review-model",
        "model_id": 1,
        "vendor_id": 1,
        "source": "generation_model",
    }
    atomic_write_json(workspace.staging_path(generation_id) / ".generation-state.json", state)
    monkeypatch.setattr(
        generation_module,
        "USER_MODULE_REVIEW_POLICY_VERSION",
        "user-module-security-review/test-v2",
    )
    with pytest.raises(ValueError, match="策略已更新"):
        asyncio.run(service.approve(generation_id, "admin-1"))


def test_interrupted_review_attempt_requires_explicit_retry(tmp_path: Path, monkeypatch):
    from module_runtime.paths import atomic_write_json
    from services.user_module_review_service import UserModuleReviewService

    workspace, generation_id, service = _create_valid_generation(tmp_path, HealthySupervisor())
    workspace.write_file(generation_id, "src/driver.py", DRIVER_SOURCE + "\n# interrupted\n")
    validation = workspace.validate(generation_id)
    state = workspace.read_state(generation_id)
    state["review_attempt"] = {
        "attempt_id": "previous-process-attempt",
        "status": "running",
        "started_at": "2026-08-19T00:00:00+00:00",
        "code_digest": validation["code_digest"],
        "model": "test-review-model",
        "model_id": 1,
        "vendor_id": 1,
        "review_policy_version": state["review_policy_version"],
    }
    atomic_write_json(workspace.staging_path(generation_id) / ".generation-state.json", state)
    calls = []

    def fake_review(self, target_generation_id, **kwargs):
        calls.append(target_generation_id)
        return {
            "status": "completed",
            "verdict": "approve",
            "risk_level": "low",
            "summary": "审核通过",
            "findings": [],
        }

    monkeypatch.setattr(UserModuleReviewService, "review", fake_review)
    first = asyncio.run(service.validate(generation_id, auth_token="token"))
    assert first["review"]["error_code"] == "review_attempt_interrupted"
    assert calls == []

    second = asyncio.run(service.validate(generation_id, auth_token="token"))
    assert second["review_gate"]["publishable"] is True
    assert calls == [generation_id]


def test_extract_json_handles_markdown_and_noise():
    """LLM 输出可能带 markdown 围栏或多余文字，解析需容错。"""
    from services.user_module_review_service import _extract_json

    assert _extract_json('```json\n{"verdict": "approve"}\n```') == {"verdict": "approve"}
    assert _extract_json('好的，结果如下：\n{"verdict": "approve", "risk_level": "low"}\n以上。') == {
        "verdict": "approve", "risk_level": "low"}
    assert _extract_json("完全不是 json 的文字") is None
    assert _extract_json("") is None


def _write_minimal_staging(tmp_path: Path, manifest: dict, driver_source: str) -> Path:
    staging = tmp_path / "staging"
    (staging / "src").mkdir(parents=True)
    (staging / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (staging / "src" / "__init__.py").write_text("", encoding="utf-8")
    (staging / "src" / "driver.py").write_text(driver_source, encoding="utf-8")
    return staging


def test_validation_rejects_secret_names_outside_grantable_catalog(tmp_path: Path):
    """secret_names 只能取 user_module_grantable 自动生成的规范名。"""
    payload = manifest_payload()
    payload["permissions"] = {"secret_names": ["TOTALLY_UNKNOWN_API_KEY"]}
    staging = _write_minimal_staging(tmp_path, payload, DRIVER_SOURCE)

    result = validate_staging(staging)

    assert result["ok"] is False
    finding = next(
        item for item in result["findings"] if item["code"] == "SECRET_NAME_NOT_GRANTABLE"
    )
    assert "TOTALLY_UNKNOWN_API_KEY" in finding["message"]
    assert "RUNNINGHUB_API_KEY" in finding["message"]


def test_validation_accepts_grantable_secret_name(tmp_path: Path):
    payload = manifest_payload()
    payload["permissions"] = {"secret_names": ["RUNNINGHUB_API_KEY"]}
    staging = _write_minimal_staging(tmp_path, payload, DRIVER_SOURCE)

    result = validate_staging(staging)

    assert result["ok"] is True


def test_validation_rejects_direct_driver_error_return_in_submit(tmp_path: Path):
    """submit 直接 return DriverError 会让 Runner 端协议校验崩溃，必须包 Rejected。"""
    bad_source = DRIVER_SOURCE + """

class BadDriver:
    async def submit(self, ctx, request):
        return DriverError(code="MISSING_SECRET", message="x")
"""
    staging = _write_minimal_staging(tmp_path, manifest_payload(), bad_source)

    result = validate_staging(staging)

    assert result["ok"] is False
    assert any(
        item["code"] == "SUBMIT_RETURN_DRIVER_ERROR" for item in result["findings"]
    )


def test_validation_accepts_rejected_error_return_in_submit(tmp_path: Path):
    good_source = DRIVER_SOURCE.replace(
        "from module_runtime.protocol import CancelResult, Completed, HealthResult, JobStatus, PollResult",
        "from module_runtime.protocol import CancelResult, Completed, DriverError, HealthResult, JobStatus, PollResult, Rejected",
    ).replace(
        "    async def submit(self, ctx, request):\n        return Completed(outputs=[])",
        '    async def submit(self, ctx, request):\n        return Rejected(error=DriverError(code="MISSING_SECRET", message="x"))',
    )
    staging = _write_minimal_staging(tmp_path, manifest_payload(), good_source)

    result = validate_staging(staging)

    assert result["ok"] is True, result["findings"]
