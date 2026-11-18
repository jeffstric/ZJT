"""显式烧录取消后不得再替换目标文件。"""
import asyncio
import os
import shutil
import time
import uuid

import utils.aigc_explicit_marker as marker
from utils.aigc_explicit_marker import ExplicitBurnSession, await_explicit_burn


def _workdir():
    root = os.path.join(os.path.dirname(__file__), "..", "..", "temp", "explicit_burn_tests")
    path = os.path.abspath(os.path.join(root, uuid.uuid4().hex))
    os.makedirs(path, exist_ok=True)
    return path


def test_replace_after_cancel_leaves_dest():
    folder = _workdir()
    try:
        src = os.path.join(folder, "src.bin")
        dst = os.path.join(folder, "dst.bin")
        with open(src, "wb") as handle:
            handle.write(b"new")
        with open(dst, "wb") as handle:
            handle.write(b"old")
        session = ExplicitBurnSession()
        session.cancel()
        assert session.replace_file(src, dst) is False
        with open(dst, "rb") as handle:
            assert handle.read() == b"old"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_replace_before_cancel_updates_dest():
    folder = _workdir()
    try:
        src = os.path.join(folder, "src.bin")
        dst = os.path.join(folder, "dst.bin")
        with open(src, "wb") as handle:
            handle.write(b"new")
        with open(dst, "wb") as handle:
            handle.write(b"old")
        session = ExplicitBurnSession()
        assert session.replace_file(src, dst) is True
        with open(dst, "rb") as handle:
            assert handle.read() == b"new"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_await_explicit_burn_does_not_replace_after_timeout(monkeypatch):
    folder = _workdir()
    try:
        src = os.path.join(folder, "src.bin")
        dst = os.path.join(folder, "dst.bin")
        with open(src, "wb") as handle:
            handle.write(b"new")
        with open(dst, "wb") as handle:
            handle.write(b"old")

        def slow_burn(result_url, ai_tool_id, media_type, session=None):
            deadline = time.monotonic() + 5
            while session is not None and not session.is_cancelled() and time.monotonic() < deadline:
                time.sleep(0.02)
            if session is not None:
                session.replace_file(src, dst)
            return True

        monkeypatch.setattr(marker, "maybe_burn_generated_media", slow_burn)
        monkeypatch.setattr(marker, "AIGC_EXPLICIT_BURN_TIMEOUT_SECONDS", 0.15)
        monkeypatch.setattr(marker, "AIGC_EXPLICIT_BURN_CANCEL_JOIN_SECONDS", 5)

        assert asyncio.run(await_explicit_burn("/upload/x.mp4", 1, "video")) is False
        with open(dst, "rb") as handle:
            assert handle.read() == b"old"
    finally:
        shutil.rmtree(folder, ignore_errors=True)
