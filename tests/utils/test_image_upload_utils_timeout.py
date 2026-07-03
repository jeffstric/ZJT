import asyncio
import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("comfyui_env", "unit")
from config import config_util

config_util._config_cache["config_unit.yml"] = {
    "database": {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "",
        "database": "unit",
    },
    "server": {},
    "file_storage": {},
}

from utils import image_upload_utils


def test_upload_local_images_sync_returns_empty_on_timeout(monkeypatch):
    async def slow_upload(*args, **kwargs):
        await asyncio.sleep(0.2)
        return ["too-late"]

    monkeypatch.setattr(image_upload_utils, "IMAGE_UPLOAD_SYNC_WRAPPER_TIMEOUT", 0.01, raising=False)
    monkeypatch.setattr(image_upload_utils, "upload_local_images_to_cdn", slow_upload)

    started = time.monotonic()
    result = image_upload_utils.upload_local_images_to_cdn_sync(["local.png"], {}, ".")
    elapsed = time.monotonic() - started

    assert result == []
    assert elapsed < 0.15


def test_upload_local_images_to_cdn_wraps_storage_upload_timeout(tmp_path, monkeypatch):
    local_file = tmp_path / "image.png"
    local_file.write_bytes(b"fake")

    class SlowStorage:
        def generate_key_with_datetime(self, filename):
            return f"uploads/{filename}"

        async def upload_file(self, key, file_path):
            await asyncio.sleep(0.2)
            return SimpleNamespace(success=True, key=key, error=None)

        def get_download_url(self, key):
            return f"https://cdn.example/{key}"

    monkeypatch.setattr(image_upload_utils, "IMAGE_UPLOAD_STORAGE_UPLOAD_TIMEOUT", 0.01, raising=False)
    monkeypatch.setattr(image_upload_utils, "get_file_storage", lambda config: SlowStorage())

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="超时"):
        asyncio.run(image_upload_utils.upload_local_images_to_cdn([str(local_file)], {}, str(tmp_path)))
    elapsed = time.monotonic() - started

    assert elapsed < 0.15
