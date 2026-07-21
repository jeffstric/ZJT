from io import BytesIO
from types import SimpleNamespace

import pytest

from api import storyboard


def test_store_storyboard_asset_file_copies_in_chunks(monkeypatch, tmp_path):
    monkeypatch.setattr(storyboard, "get_upload_subdir", lambda *args, ensure: str(tmp_path))
    monkeypatch.setattr(
        storyboard,
        "generate_upload_filename",
        lambda prefix, extension: SimpleNamespace(filename=f"{prefix}{extension}"),
    )

    stored = storyboard._store_storyboard_asset_file(
        BytesIO(b"storyboard-image"),
        "first_frame",
        ".png",
        max_bytes=1024,
    )

    assert stored["size_bytes"] == len(b"storyboard-image")
    assert stored["subdir_parts"] == ("storyboard", "first_frame")
    assert (tmp_path / "sb_first_frame.png").read_bytes() == b"storyboard-image"


def test_store_storyboard_asset_file_removes_partial_file_when_too_large(monkeypatch, tmp_path):
    monkeypatch.setattr(storyboard, "get_upload_subdir", lambda *args, ensure: str(tmp_path))
    monkeypatch.setattr(
        storyboard,
        "generate_upload_filename",
        lambda prefix, extension: SimpleNamespace(filename=f"{prefix}{extension}"),
    )
    monkeypatch.setattr(
        storyboard.MediaConstants,
        "STORYBOARD_ASSET_UPLOAD_CHUNK_BYTES",
        4,
    )

    with pytest.raises(storyboard.StoryboardAssetUploadTooLarge):
        storyboard._store_storyboard_asset_file(
            BytesIO(b"123456789"),
            "video",
            ".mp4",
            max_bytes=5,
        )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "http://localhost:9003/upload/storyboard/video/demo.mp4",
            "/upload/storyboard/video/demo.mp4",
        ),
        (
            "http://127.0.0.1:9003/upload/storyboard/first_frame/demo.png?v=1",
            "/upload/storyboard/first_frame/demo.png?v=1",
        ),
        (
            "https://cdn.example.com/upload/storyboard/video/demo.mp4",
            "https://cdn.example.com/upload/storyboard/video/demo.mp4",
        ),
        ("/upload/storyboard/video/demo.mp4", "/upload/storyboard/video/demo.mp4"),
    ],
)
def test_normalize_storyboard_upload_browser_url(value, expected):
    assert storyboard._normalize_storyboard_upload_browser_url(value) == expected


def test_remove_deleted_storyboard_asset_file_stays_inside_type_directory(monkeypatch, tmp_path):
    video_dir = tmp_path / "storyboard" / "video"
    video_dir.mkdir(parents=True)
    video_path = video_dir / "demo.mp4"
    video_path.write_bytes(b"video")

    monkeypatch.setattr(
        storyboard,
        "get_upload_subdir",
        lambda *parts, ensure=False: str(tmp_path.joinpath(*parts)),
    )
    monkeypatch.setattr(
        storyboard,
        "resolve_upload_url_to_local_path",
        lambda path: str(tmp_path / path.removeprefix("/upload/")),
    )

    assert storyboard._remove_deleted_storyboard_asset_file(
        "/upload/storyboard/video/demo.mp4",
        "video",
    ) is True
    assert video_path.exists() is False

    outside_path = tmp_path / "outside.mp4"
    outside_path.write_bytes(b"outside")
    assert storyboard._remove_deleted_storyboard_asset_file(
        "/upload/storyboard/video/../../../outside.mp4",
        "video",
    ) is False
    assert outside_path.exists() is True
