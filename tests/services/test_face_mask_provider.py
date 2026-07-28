import asyncio
import importlib
from unittest.mock import patch

from services import generated_video_face_grid_service
from utils import image_face_grid_util
from utils.enterprise_loader import EnterpriseLoader


def _provider_module():
    return importlib.import_module("services.face_mask_provider")


def test_community_provider_keeps_video_result_unchanged():
    provider = _provider_module()
    provider.reset_provider()

    async_result = asyncio.run(
        provider.maybe_trim_generated_face_grid_prefix(
            ai_tool_id=7,
            result_url="/upload/result.mp4",
            media_type="video",
        )
    )
    sync_result = provider.maybe_trim_generated_face_grid_prefix_sync(
        ai_tool_id=7,
        result_url="/upload/result.mp4",
        media_type="video",
    )

    assert provider.is_available() is False
    assert async_result.result_url == "/upload/result.mp4"
    assert async_result.status is provider.VideoPostprocessStatus.SKIPPED
    assert sync_result.result_url == "/upload/result.mp4"
    assert sync_result.status is provider.VideoPostprocessStatus.SKIPPED


def test_registered_provider_receives_image_and_video_calls():
    provider = _provider_module()
    calls = []

    class EnterpriseProvider:
        available = True

        def convert_black_face_masks_to_red_grids(
            self,
            original_image_path,
            masked_image_path,
            output_image_path,
        ):
            calls.append(
                (
                    "image",
                    original_image_path,
                    masked_image_path,
                    output_image_path,
                )
            )
            return True, output_image_path, None

        async def maybe_trim_generated_face_grid_prefix(
            self,
            ai_tool_id,
            result_url,
            media_type,
        ):
            calls.append(("async_video", ai_tool_id, result_url, media_type))
            return provider.VideoPostprocessResult(
                result_url="/upload/async-trimmed.mp4",
                status=provider.VideoPostprocessStatus.TRIMMED,
            )

        def maybe_trim_generated_face_grid_prefix_sync(
            self,
            ai_tool_id,
            result_url,
            media_type,
        ):
            calls.append(("sync_video", ai_tool_id, result_url, media_type))
            return provider.VideoPostprocessResult(
                result_url="/upload/sync-trimmed.mp4",
                status=provider.VideoPostprocessStatus.TRIMMED,
            )

    provider.register_provider(EnterpriseProvider())
    try:
        image_result = provider.convert_black_face_masks_to_red_grids(
            "original.png",
            "masked.png",
            "output.png",
        )
        async_result = asyncio.run(
            provider.maybe_trim_generated_face_grid_prefix(
                11,
                "/upload/source.mp4",
                "video",
            )
        )
        sync_result = provider.maybe_trim_generated_face_grid_prefix_sync(
            12,
            "/upload/source-2.mp4",
            "video",
        )
    finally:
        provider.reset_provider()

    assert image_result == (True, "output.png", None)
    assert async_result.result_url == "/upload/async-trimmed.mp4"
    assert sync_result.result_url == "/upload/sync-trimmed.mp4"
    assert calls == [
        ("image", "original.png", "masked.png", "output.png"),
        ("async_video", 11, "/upload/source.mp4", "video"),
        ("sync_video", 12, "/upload/source-2.mp4", "video"),
    ]
    assert provider.is_available() is False


def test_image_compatibility_facade_delegates_to_provider(monkeypatch):
    provider = _provider_module()
    calls = []

    def fake_convert(original, masked, output):
        calls.append((original, masked, output))
        return True, output, None

    monkeypatch.setattr(
        provider,
        "convert_black_face_masks_to_red_grids",
        fake_convert,
    )

    result = image_face_grid_util.convert_black_face_masks_to_red_grids(
        "original.png",
        "masked.png",
        "output.png",
    )

    assert result == (True, "output.png", None)
    assert calls == [("original.png", "masked.png", "output.png")]


def test_video_compatibility_facade_delegates_to_provider(monkeypatch):
    provider = _provider_module()
    calls = []

    async def fake_async(ai_tool_id, result_url, media_type):
        calls.append(("async", ai_tool_id, result_url, media_type))
        return provider.VideoPostprocessResult(
            result_url="/upload/async-provider.mp4",
            status=provider.VideoPostprocessStatus.TRIMMED,
        )

    def fake_sync(ai_tool_id, result_url, media_type):
        calls.append(("sync", ai_tool_id, result_url, media_type))
        return provider.VideoPostprocessResult(
            result_url="/upload/sync-provider.mp4",
            status=provider.VideoPostprocessStatus.TRIMMED,
        )

    monkeypatch.setattr(
        provider,
        "maybe_trim_generated_face_grid_prefix",
        fake_async,
    )
    monkeypatch.setattr(
        provider,
        "maybe_trim_generated_face_grid_prefix_sync",
        fake_sync,
    )

    async_result = asyncio.run(
        generated_video_face_grid_service.maybe_trim_generated_face_grid_prefix(
            21,
            "/upload/source.mp4",
            "video",
        )
    )
    sync_result = (
        generated_video_face_grid_service
        .maybe_trim_generated_face_grid_prefix_sync(
            22,
            "/upload/source-2.mp4",
            "video",
        )
    )

    assert async_result.result_url == "/upload/async-provider.mp4"
    assert sync_result.result_url == "/upload/sync-provider.mp4"
    assert calls == [
        ("async", 21, "/upload/source.mp4", "video"),
        ("sync", 22, "/upload/source-2.mp4", "video"),
    ]


def test_failed_enterprise_load_resets_face_mask_provider():
    provider = _provider_module()

    class RegisteredProvider:
        available = True

    class BrokenEnterpriseModule:
        @staticmethod
        def register(app):
            provider.register_provider(RegisteredProvider())
            raise RuntimeError("register failed")

    loader = EnterpriseLoader()
    with patch(
        "utils.enterprise_loader.importlib.import_module",
        return_value=BrokenEnterpriseModule,
    ):
        loader.load(app=object())

    assert loader.loaded is False
    assert provider.is_available() is False
