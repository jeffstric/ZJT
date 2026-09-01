from pathlib import Path

import pytest

import services.director_stage_env_fit as env_fit


def test_resolve_upload_path_limits_file_to_authenticated_user(tmp_path, monkeypatch):
    upload_root = tmp_path / "upload"
    own_file = upload_root / "workflow" / "7" / "preview.jpg"
    own_file.parent.mkdir(parents=True)
    own_file.write_bytes(b"image")
    monkeypatch.setattr(env_fit, "get_upload_dir", lambda: str(upload_root))

    resolved, error = env_fit.resolve_upload_path(
        "/upload/workflow/7/preview.jpg",
        user_id=7,
    )

    assert error is None
    assert Path(resolved) == own_file.resolve()


def test_resolve_upload_path_rejects_another_users_file(tmp_path, monkeypatch):
    upload_root = tmp_path / "upload"
    other_file = upload_root / "workflow" / "8" / "preview.jpg"
    other_file.parent.mkdir(parents=True)
    other_file.write_bytes(b"image")
    monkeypatch.setattr(env_fit, "get_upload_dir", lambda: str(upload_root))

    resolved, error = env_fit.resolve_upload_path(
        "/upload/workflow/8/preview.jpg",
        user_id=7,
    )

    assert resolved is None
    assert error == "非法的图片路径"


def test_resolve_upload_path_reports_missing_owned_image(tmp_path, monkeypatch):
    upload_root = tmp_path / "upload"
    upload_root.mkdir()
    monkeypatch.setattr(env_fit, "get_upload_dir", lambda: str(upload_root))

    resolved, error = env_fit.resolve_upload_path(
        "/upload/workflow/7/missing.jpg",
        user_id=7,
    )

    assert resolved is None
    assert error == "图片文件不存在"


@pytest.mark.parametrize(
    "image_url",
    [
        "/upload/../config.yml",
        "/upload/%2e%2e/config.yml",
        r"/upload/..\config.yml",
    ],
)
def test_resolve_upload_path_rejects_traversal(image_url, tmp_path, monkeypatch):
    upload_root = tmp_path / "upload"
    upload_root.mkdir()
    monkeypatch.setattr(env_fit, "get_upload_dir", lambda: str(upload_root))

    resolved, error = env_fit.resolve_upload_path(image_url, user_id=7)

    assert resolved is None
    assert error == "非法的图片路径"
