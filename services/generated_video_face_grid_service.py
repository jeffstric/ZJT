"""生成视频人脸网格后处理的兼容调用门面。"""

from services import face_mask_provider
from services.face_mask_provider import (
    VideoPostprocessResult,
    VideoPostprocessStatus,
)


async def maybe_trim_generated_face_grid_prefix(
    ai_tool_id: int,
    result_url: str,
    media_type: str,
) -> VideoPostprocessResult:
    return await face_mask_provider.maybe_trim_generated_face_grid_prefix(
        ai_tool_id,
        result_url,
        media_type,
    )


def maybe_trim_generated_face_grid_prefix_sync(
    ai_tool_id: int,
    result_url: str,
    media_type: str,
) -> VideoPostprocessResult:
    return face_mask_provider.maybe_trim_generated_face_grid_prefix_sync(
        ai_tool_id,
        result_url,
        media_type,
    )


__all__ = [
    "VideoPostprocessResult",
    "VideoPostprocessStatus",
    "maybe_trim_generated_face_grid_prefix",
    "maybe_trim_generated_face_grid_prefix_sync",
]
