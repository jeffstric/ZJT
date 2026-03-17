# -*- coding: utf-8 -*-
"""
剧本创作系统常量配置
"""


class ItemType:
    """item_type 类型定义，用于标识生成图片的项目类型"""

    # 单图类型 (1-3)
    CHARACTER = 1       # 角色
    LOCATION = 2        # 场景
    PROP = 3            # 道具

    # 宫格类型 (4-6) = 单图类型 + 3
    CHARACTER_GRID = 4  # 角色四宫格
    LOCATION_GRID = 5   # 场景四宫格
    PROP_GRID = 6       # 道具四宫格

    # 类型列表
    SINGLE_TYPES = [1, 2, 3]
    GRID_TYPES = [4, 5, 6]
    ALL_TYPES = [1, 2, 3, 4, 5, 6]

    # 完整映射表
    MAP = {
        # 单图
        1: {'name': 'character', 'name_cn': '角色', 'is_grid': False},
        2: {'name': 'location', 'name_cn': '场景', 'is_grid': False},
        3: {'name': 'prop', 'name_cn': '道具', 'is_grid': False},
        # 宫格
        4: {'name': 'character_grid', 'name_cn': '角色四宫格', 'is_grid': True, 'base_type': 1},
        5: {'name': 'location_grid', 'name_cn': '场景四宫格', 'is_grid': True, 'base_type': 2},
        6: {'name': 'prop_grid', 'name_cn': '道具四宫格', 'is_grid': True, 'base_type': 3},
    }

    # 宫格专用映射
    GRID_MAP = {
        4: {'name': 'character_grid', 'name_cn': '角色四宫格', 'base_type': 1},
        5: {'name': 'location_grid', 'name_cn': '场景四宫格', 'base_type': 2},
        6: {'name': 'prop_grid', 'name_cn': '道具四宫格', 'base_type': 3},
    }

    @classmethod
    def is_grid(cls, item_type: int) -> bool:
        """判断是否为宫格类型"""
        return item_type in cls.GRID_TYPES

    @classmethod
    def is_single(cls, item_type: int) -> bool:
        """判断是否为单图类型"""
        return item_type in cls.SINGLE_TYPES

    @classmethod
    def get_base_type(cls, grid_type: int) -> int:
        """从宫格类型获取基础单图类型 (4->1, 5->2, 6->3)"""
        if grid_type in cls.GRID_MAP:
            return cls.GRID_MAP[grid_type]['base_type']
        return grid_type

    @classmethod
    def get_grid_type(cls, base_type: int) -> int:
        """从基础单图类型获取宫格类型 (1->4, 2->5, 3->6)"""
        return base_type + 3 if base_type in cls.SINGLE_TYPES else base_type

    @classmethod
    def get_name(cls, item_type: int, lang: str = 'cn') -> str:
        """获取 item_type 的名称"""
        if item_type in cls.MAP:
            return cls.MAP[item_type]['name_cn'] if lang == 'cn' else cls.MAP[item_type]['name']
        return 'unknown'

    @classmethod
    def is_valid(cls, item_type: int) -> bool:
        """判断 item_type 是否有效"""
        return item_type in cls.ALL_TYPES
