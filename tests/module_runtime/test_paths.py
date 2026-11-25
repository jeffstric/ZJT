import os
from pathlib import Path

import pytest

from module_runtime.paths import (
    atomic_write_json,
    ensure_user_module_layout,
    get_user_module_root,
    resolve_within_root,
)


def test_default_root_is_under_project(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("ZJT_USER_MODULES_DIR", raising=False)
    root = get_user_module_root(tmp_path)
    assert root == (tmp_path / "data" / "user_modules").resolve()


def test_environment_root_can_be_outside_project(monkeypatch, tmp_path: Path):
    external = tmp_path.parent / f"{tmp_path.name}-modules"
    monkeypatch.setenv("ZJT_USER_MODULES_DIR", str(external))
    assert get_user_module_root(tmp_path) == external.resolve()


def test_layout_and_atomic_json(tmp_path: Path):
    root = ensure_user_module_layout(tmp_path / "modules-root")
    assert (root / "staging").is_dir()
    assert (root / "modules").is_dir()
    target = root / "runtime" / "current.json"
    atomic_write_json(target, {"module_id": "demo.echo"})
    assert target.read_text(encoding="utf-8").endswith("\n")


def test_path_traversal_is_rejected(tmp_path: Path):
    root = ensure_user_module_layout(tmp_path / "modules-root")
    with pytest.raises(ValueError, match="非法模块路径"):
        resolve_within_root(root, "..", "outside")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="platform has no symlink support")
def test_symlink_is_rejected_when_supported(tmp_path: Path):
    root = ensure_user_module_layout(tmp_path / "modules-root")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "modules" / "linked"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("current user cannot create symlinks")
    with pytest.raises(ValueError, match="链接|reparse"):
        resolve_within_root(root, "modules", "linked", must_exist=True)
