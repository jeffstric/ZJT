"""
宫格生图 image_size 解析与降级逻辑测试。

验证 _pick_grid_image_size 能按模型 supported_sizes 选出最接近且不超过目标的分辨率，
覆盖 4宫格→2K、9宫格→4K 以及模型不支持时降级的场景。
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _config(supported_sizes):
    return SimpleNamespace(supported_sizes=supported_sizes, default_size=supported_sizes[0] if supported_sizes else None)


class TestPickGridImageSize(unittest.TestCase):
    """_pick_grid_image_size: 选不超过目标的最大支持档位。"""

    def test_target_directly_supported(self):
        """目标值在 supported_sizes 中，直接返回。"""
        from script_writer_core.mcp_tool import _pick_grid_image_size

        self.assertEqual(_pick_grid_image_size(_config(['1K', '2K', '4K']), '2K'), '2K')
        self.assertEqual(_pick_grid_image_size(_config(['1K', '2K', '4K']), '4K'), '4K')

    def test_target_not_supported_downgrade_to_closest_below(self):
        """目标不在 supported 中，但有不超目标的档位 → 取其中最大者。"""
        from script_writer_core.mcp_tool import _pick_grid_image_size

        # seedream 支持 2K/3K，目标 4K → 选 3K（不超过 4K 的最大档）
        self.assertEqual(_pick_grid_image_size(_config(['2K', '3K']), '4K'), '3K')
        # 支持 1K/2K/3K，目标 4K → 选 3K
        self.assertEqual(_pick_grid_image_size(_config(['1K', '2K', '3K']), '4K'), '3K')

    def test_all_supported_exceed_target_pick_minimum(self):
        """所有支持值都超过目标 → 取最小支持值。"""
        from script_writer_core.mcp_tool import _pick_grid_image_size

        # 模型只有 3K/4K，目标 2K → 选 3K（最小支持值）
        self.assertEqual(_pick_grid_image_size(_config(['3K', '4K']), '2K'), '3K')

    def test_no_target_returns_lowest_supported(self):
        """target_size 为空时返回模型最低支持值。"""
        from script_writer_core.mcp_tool import _pick_grid_image_size

        self.assertEqual(_pick_grid_image_size(_config(['1K', '2K']), None), '1K')

    def test_no_config_returns_target(self):
        """config 为空时原样返回 target（交给端点处理）。"""
        from script_writer_core.mcp_tool import _pick_grid_image_size

        self.assertEqual(_pick_grid_image_size(None, '4K'), '4K')

    def test_config_without_supported_sizes_returns_target(self):
        """config 无 supported_sizes 时原样返回 target。"""
        from script_writer_core.mcp_tool import _pick_grid_image_size

        cfg = SimpleNamespace(supported_sizes=None)
        self.assertEqual(_pick_grid_image_size(cfg, '2K'), '2K')


class TestGridSizeImageSizeMap(unittest.TestCase):
    """GridConfig.GRID_SIZE_IMAGE_SIZE_MAP 映射正确。"""

    def test_2x2_maps_to_2k(self):
        from config.constant import GridConfig
        self.assertEqual(GridConfig.GRID_SIZE_IMAGE_SIZE_MAP[GridConfig.SIZE_2X2], '2K')

    def test_3x3_maps_to_4k(self):
        from config.constant import GridConfig
        self.assertEqual(GridConfig.GRID_SIZE_IMAGE_SIZE_MAP[GridConfig.SIZE_3X3], '4K')


if __name__ == '__main__':
    unittest.main()
