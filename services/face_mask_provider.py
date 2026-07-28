"""人脸遮盖商业能力的公共 Provider 门面。"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, Tuple

logger = logging.getLogger(__name__)

ImageGridConvertResult = Tuple[bool, Optional[str], Optional[str]]


class VideoPostprocessStatus(str, Enum):
    """生成视频网格后处理的稳定对外状态。"""

    TRIMMED = "trimmed"
    NO_GRID = "no_grid"
    SKIPPED = "skipped"
    FAILED_OPEN = "failed_open"


@dataclass(frozen=True)
class VideoPostprocessResult:
    result_url: str
    status: VideoPostprocessStatus
    trim_start_seconds: Optional[float] = None
    last_grid_frame_index: Optional[int] = None
    scanned_frame_count: Optional[int] = None
    last_grid_frame_timestamp: Optional[float] = None
    detection_ms: Optional[float] = None
    transcode_ms: Optional[float] = None
    message: Optional[str] = None


class FaceMaskProvider(Protocol):
    """Enterprise 人脸处理实现需要满足的最小协议。"""

    available: bool

    def convert_black_face_masks_to_red_grids(
        self,
        original_image_path: str,
        masked_image_path: str,
        output_image_path: str,
    ) -> ImageGridConvertResult: ...

    async def maybe_trim_generated_face_grid_prefix(
        self,
        ai_tool_id: int,
        result_url: str,
        media_type: str,
    ) -> VideoPostprocessResult: ...

    def maybe_trim_generated_face_grid_prefix_sync(
        self,
        ai_tool_id: int,
        result_url: str,
        media_type: str,
    ) -> VideoPostprocessResult: ...


class CommunityFaceMaskProvider:
    """社区默认实现不包含或执行任何商业人脸处理算法。"""

    available = False

    def convert_black_face_masks_to_red_grids(
        self,
        original_image_path: str,
        masked_image_path: str,
        output_image_path: str,
    ) -> ImageGridConvertResult:
        return False, None, "商业版人脸处理 Provider 未加载"

    async def maybe_trim_generated_face_grid_prefix(
        self,
        ai_tool_id: int,
        result_url: str,
        media_type: str,
    ) -> VideoPostprocessResult:
        return self._skipped_video_result(result_url)

    def maybe_trim_generated_face_grid_prefix_sync(
        self,
        ai_tool_id: int,
        result_url: str,
        media_type: str,
    ) -> VideoPostprocessResult:
        return self._skipped_video_result(result_url)

    @staticmethod
    def _skipped_video_result(result_url: str) -> VideoPostprocessResult:
        return VideoPostprocessResult(
            result_url=result_url,
            status=VideoPostprocessStatus.SKIPPED,
            message="商业版人脸处理 Provider 未加载",
        )


_community_provider = CommunityFaceMaskProvider()
_provider: FaceMaskProvider = _community_provider


def register_provider(provider: FaceMaskProvider) -> None:
    """由已通过版本校验的 Enterprise 模块注册真实实现。"""
    if provider is None or not getattr(provider, "available", False):
        raise ValueError("人脸处理 Provider 必须声明 available=True")
    global _provider
    _provider = provider
    logger.info("[Enterprise] Face mask provider registered")


def reset_provider() -> None:
    """恢复社区默认实现，用于 Enterprise 加载失败回滚和测试隔离。"""
    global _provider
    _provider = _community_provider


def is_available() -> bool:
    return bool(getattr(_provider, "available", False))


def convert_black_face_masks_to_red_grids(
    original_image_path: str,
    masked_image_path: str,
    output_image_path: str,
) -> ImageGridConvertResult:
    return _provider.convert_black_face_masks_to_red_grids(
        original_image_path,
        masked_image_path,
        output_image_path,
    )


async def maybe_trim_generated_face_grid_prefix(
    ai_tool_id: int,
    result_url: str,
    media_type: str,
) -> VideoPostprocessResult:
    return await _provider.maybe_trim_generated_face_grid_prefix(
        ai_tool_id,
        result_url,
        media_type,
    )


def maybe_trim_generated_face_grid_prefix_sync(
    ai_tool_id: int,
    result_url: str,
    media_type: str,
) -> VideoPostprocessResult:
    return _provider.maybe_trim_generated_face_grid_prefix_sync(
        ai_tool_id,
        result_url,
        media_type,
    )


__all__ = [
    "FaceMaskProvider",
    "ImageGridConvertResult",
    "VideoPostprocessResult",
    "VideoPostprocessStatus",
    "convert_black_face_masks_to_red_grids",
    "is_available",
    "maybe_trim_generated_face_grid_prefix",
    "maybe_trim_generated_face_grid_prefix_sync",
    "register_provider",
    "reset_provider",
]
