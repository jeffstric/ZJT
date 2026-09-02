"""宫格拆分白边/黑边清理商业能力的公共 Provider 门面。

社区版：使用 CommunityGridBorderCleanProvider，拆分链路行为与历史版本一致
（等分裁剪后不做任何清理），不包含商业清理算法。
商业版：由 Enterprise 启动时通过 register_provider 注入
enterprise.services.grid_border_clean.EnterpriseGridBorderCleanProvider，
在许可证放行时对宫格拆分单元图执行白边/黑边清理并拉伸回格子尺寸；
许可证未激活时同样降级为不清理（拆分是后台主链路，不因授权失败而中断）。

调用方：script_writer_core/image_grid_splitter.py 的 split_grid(trim_border=True)。
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol, Tuple

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class BorderCleanResult:
    """单张单元图的清理结果（用于日志与测试断言）"""

    trimmed: bool = False                        # 是否发生了实际裁剪
    bbox: Optional[Tuple[int, int, int, int]] = None  # 内容区域 (x0, y0, x1, y1)
    edge_trims: dict = field(default_factory=dict)   # 四边各自裁掉像素数 {top/bottom/left/right}
    interior_cuts: int = 0                       # 内部白线切割次数
    reason: str = ""                             # 未裁剪时的原因（license_denied/占位格/全内容等）


class GridBorderCleanProvider(Protocol):
    """Enterprise 白边清理实现需要满足的最小协议。"""

    available: bool

    def trim_border_and_stretch(
        self, image: Image.Image
    ) -> Tuple[Image.Image, BorderCleanResult]: ...


class CommunityGridBorderCleanProvider:
    """社区默认实现：不包含或执行任何商业清理算法。"""

    available = False

    def trim_border_and_stretch(
        self, image: Image.Image
    ) -> Tuple[Image.Image, BorderCleanResult]:
        return image, BorderCleanResult(reason="community_provider_not_loaded")


_community_provider = CommunityGridBorderCleanProvider()
_provider: GridBorderCleanProvider = _community_provider


def register_provider(provider: GridBorderCleanProvider) -> None:
    """由已通过版本校验的 Enterprise 模块注册真实实现。"""
    if provider is None or not getattr(provider, "available", False):
        raise ValueError("宫格白边清理 Provider 必须声明 available=True")
    global _provider
    _provider = provider
    logger.info("[Enterprise] Grid border clean provider registered")


def reset_provider() -> None:
    """恢复社区默认实现，用于 Enterprise 加载失败回滚和测试隔离。"""
    global _provider
    _provider = _community_provider


def is_available() -> bool:
    return bool(getattr(_provider, "available", False))


def trim_border_and_stretch(
    image: Image.Image,
) -> Tuple[Image.Image, BorderCleanResult]:
    """清理单元图白边/黑边并拉伸回原尺寸（社区版/未授权时原样返回）。"""
    return _provider.trim_border_and_stretch(image)


__all__ = [
    "BorderCleanResult",
    "CommunityGridBorderCleanProvider",
    "GridBorderCleanProvider",
    "is_available",
    "register_provider",
    "reset_provider",
    "trim_border_and_stretch",
]
