import copy

import pytest

from module_runtime.compatibility import (
    assert_manifest_compatible,
    compatibility_errors,
    load_core_abi,
    version_satisfies,
)
from module_runtime.manifest import ModuleManifest
from tests.module_runtime.test_manifest import valid_manifest


def test_current_abi_accepts_current_manifest():
    manifest = ModuleManifest.model_validate(valid_manifest())
    abi = load_core_abi()
    assert compatibility_errors(manifest, abi) == []
    assert_manifest_compatible(manifest, abi)


def test_core_abi_version_comes_from_pyproject(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "user_module_abi.json").write_text(
        '{"abi_schema_version":1,"core_version":"0.0.1"}', encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "9.8.7"\n', encoding="utf-8"
    )

    assert load_core_abi(tmp_path)["core_version"] == "9.8.7"


def test_app_version_reads_only_project_table_and_fails_closed(tmp_path):
    from config.version import get_app_version

    (tmp_path / "pyproject.toml").write_text(
        '[tool.demo]\nversion = "99.0.0"\n[project]\nversion = "3.2.1"\n',
        encoding="utf-8",
    )
    assert get_app_version(tmp_path) == "3.2.1"
    (tmp_path / "pyproject.toml").write_text('[tool.demo]\nversion = "99.0.0"\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="project.*version"):
        get_app_version(tmp_path)


def test_runtime_rejects_manifest_outside_current_core_range():
    manifest = ModuleManifest.model_validate(valid_manifest(core_compat=">=9.0"))
    with pytest.raises(ValueError, match="core_compat"):
        assert_manifest_compatible(manifest, load_core_abi())


def test_runtime_rejects_abi_protocol_mismatch():
    manifest = ModuleManifest.model_validate(valid_manifest())
    abi = copy.deepcopy(load_core_abi())
    abi["rpc_protocol_versions"] = ["user-module-rpc/v2"]
    with pytest.raises(ValueError, match="RPC protocol"):
        assert_manifest_compatible(manifest, abi)


def test_version_constraints_match_supported_manifest_syntax():
    assert version_satisfies("3.10.20", ">=3.10,<3.11")
    assert not version_satisfies("3.11.0", ">=3.10,<3.11")


def test_runtime_python_check_uses_actual_interpreter_not_abi_claim():
    manifest = ModuleManifest.model_validate(valid_manifest(python_compat=">=9.0"))
    abi = copy.deepcopy(load_core_abi())
    abi["python_version"] = "9.1.0"
    with pytest.raises(ValueError, match="Python"):
        assert_manifest_compatible(manifest, abi)
