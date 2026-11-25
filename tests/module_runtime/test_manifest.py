import json
import sys
from pathlib import Path

import pytest

from module_runtime.manifest import ModuleManifest, compute_release_digest, load_manifest
from module_runtime.protocol import Completed, MediaRef


def valid_manifest(**overrides):
    payload = {
        "manifest_schema_version": 1,
        "module_id": "demo.echo",
        "name": "Echo demo",
        "version": "1.0.0",
        "code_digest": "sha256:" + "a" * 64,
        "entrypoint": "src.driver:Driver",
        "rpc_protocol": "user-module-rpc/v1",
        "driver_protocol": "media-driver/v1",
        "sdk_version": "1.0.0",
        "core_compat": ">=2.1.5",
        # 跟随当前解释器版本，与 GenerationWorkspace._normalize_manifest_for_generation
        # 保持一致（见 docs/backend/user_modules_review.md M7），避免测试与运行环境脱节。
        "python_compat": f">={sys.version_info.major}.{sys.version_info.minor},<{sys.version_info.major}.{sys.version_info.minor + 1}",
        "execution_model": "native_async",
        "capabilities": [
            {
                "operation": "echo_image",
                "media_kind": "image",
                "completion_modes": ["immediate"],
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_manifest_accepts_v1_contract():
    manifest = ModuleManifest.model_validate(valid_manifest())
    assert manifest.module_id == "demo.echo"
    assert manifest.capabilities[0].operation == "echo_image"


def test_manifest_rejects_duplicate_operations():
    capability = valid_manifest()["capabilities"][0]
    with pytest.raises(ValueError, match="不能重复"):
        ModuleManifest.model_validate(valid_manifest(capabilities=[capability, capability]))


def test_manifest_completion_modes_accept_multiple_modes():
    payload = valid_manifest()
    payload["capabilities"][0]["completion_modes"] = ["webhook", "polling", "webhook"]
    manifest = ModuleManifest.model_validate(payload)
    assert manifest.capabilities[0].completion_modes == {"webhook", "polling"}


def test_manifest_rejects_reserved_secret_names():
    with pytest.raises(ValueError, match="保留环境变量"):
        ModuleManifest.model_validate(
            valid_manifest(permissions={"secret_names": ["PATH"]})
        )


def test_manifest_rejects_unimplemented_execution_model():
    with pytest.raises(ValueError, match="native_async"):
        ModuleManifest.model_validate(valid_manifest(execution_model="blocking_io"))


def test_media_ref_rejects_local_file_scheme():
    with pytest.raises(ValueError, match="http/https"):
        MediaRef(media_kind="image", url="file:///etc/passwd")


def test_completed_output_count_is_bounded():
    outputs = [
        MediaRef(media_kind="image", url=f"https://example.invalid/{index}.png")
        for index in range(65)
    ]
    with pytest.raises(ValueError):
        Completed(outputs=outputs)


def test_load_manifest_requires_release_digest(tmp_path: Path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(valid_manifest(code_digest=None), ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="code_digest"):
        load_manifest(path)
    assert load_manifest(path, require_digest=False).code_digest is None


def test_compute_release_digest_covers_manifest_but_ignores_its_digest_field(tmp_path: Path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "driver.py").write_text("value = 1\n", encoding="utf-8")
    payload = valid_manifest(code_digest=None)
    (tmp_path / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    first = compute_release_digest(tmp_path)
    payload["code_digest"] = "sha256:" + "b" * 64
    (tmp_path / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8"
    )
    assert compute_release_digest(tmp_path) == first
    payload["permissions"] = {"secret_names": ["EXAMPLE_API_KEY"]}
    (tmp_path / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    assert compute_release_digest(tmp_path) != first


def test_compute_release_digest_changes_with_source(tmp_path: Path):
    source = tmp_path / "src"
    source.mkdir()
    driver_path = source / "driver.py"
    driver_path.write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps(valid_manifest(code_digest=None), ensure_ascii=False), encoding="utf-8"
    )
    first = compute_release_digest(tmp_path)
    driver_path.write_text("value = 2\n", encoding="utf-8")
    assert compute_release_digest(tmp_path) != first
