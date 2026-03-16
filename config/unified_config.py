#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一配置系统 - 整合任务类型、驱动、算力、模型参数等配置

使用方法：
1. 新增任务类型：在 ALL_TASK_CONFIGS 列表中添加一个 UnifiedTaskConfig
2. 查询配置：使用 UnifiedConfigRegistry 的方法获取配置
3. 前端接口：调用 get_frontend_config() 获取前端需要的格式

示例：
    # 获取单个任务配置
    config = UnifiedConfigRegistry.get_by_id(3)
    
    # 获取某分类的所有任务
    video_tasks = UnifiedConfigRegistry.get_by_category(TaskCategory.IMAGE_TO_VIDEO)
    
    # 获取前端配置格式
    frontend_config = UnifiedConfigRegistry.get_frontend_config()
"""

from dataclasses import dataclass, field
from typing import Optional, Union, Dict, List, Any


class TaskCategory:
    """任务分类常量"""
    IMAGE_EDIT = 'image_edit'           # 图片编辑
    TEXT_TO_VIDEO = 'text_to_video'     # 文生视频
    IMAGE_TO_VIDEO = 'image_to_video'   # 图生视频
    TEXT_TO_IMAGE = 'text_to_image'     # 文生图
    VISUAL_ENHANCE = 'visual_enhance'   # 视觉增强
    AUDIO = 'audio'                     # 音频
    DIGITAL_HUMAN = 'digital_human'     # 数字人
    OTHER = 'other'                     # 其他


class ImageMode:
    """图片输入模式常量（用于图生视频任务）"""
    FIRST_LAST_FRAME = 'first_last_frame'     # 首尾帧模式
    MULTI_REFERENCE = 'multi_reference'       # 多参考图模式
    FIRST_LAST_WITH_REF = 'first_last_with_ref'  # 首尾帧+参考图模式
    
    ALL_MODES = [FIRST_LAST_FRAME, MULTI_REFERENCE, FIRST_LAST_WITH_REF]


class TaskProvider:
    """任务供应商常量"""
    DUOMI = 'duomi'           # 多米供应商
    RUNNINGHUB = 'runninghub' # RunningHub 供应商
    VIDU = 'vidu'             # Vidu 官方
    VOLCENGINE = 'volcengine' # 火山引擎
    LOCAL = 'local'           # 本地处理


@dataclass
class UnifiedTaskConfig:
    """
    统一任务配置类 - 整合所有任务相关配置
    
    Attributes:
        id: 任务类型ID（数据库中的 type 字段）
        key: 唯一标识符，用于代码引用（如 sora2_image_to_video）
        name: 显示名称
        category: 主分类，使用 TaskCategory 常量
        categories: 额外分类列表（可选），任务可同时属于多个分类
        provider: 供应商，使用 TaskProvider 常量
        driver_name: 业务驱动名称（用于 VIDEO_DRIVER_MAPPING）
        implementation: 实现驱动类名（用于 DRIVER_IMPLEMENTATION_MAPPING）
        computing_power: 算力消耗，整数或按时长的字典
        supported_ratios: 支持的比例列表
        supported_sizes: 支持的尺寸列表（图片类任务）
        supported_durations: 支持的时长列表（视频类任务）
        default_ratio: 默认比例
        default_size: 默认尺寸
        default_duration: 默认时长
        enabled: 是否启用
        sort_order: 排序顺序（用于前端展示）
        supports_grid_merge: 是否支持宫格合并生成视频（将多个分镜合并为一个视频）
    """
    id: int
    key: str
    name: str
    category: str
    provider: str
    driver_name: Optional[str] = None
    implementation: Optional[str] = None
    computing_power: Union[int, Dict[int, int]] = 0
    supported_ratios: List[str] = field(default_factory=lambda: ['9:16', '16:9'])
    supported_sizes: List[str] = field(default_factory=list)
    supported_durations: List[int] = field(default_factory=list)
    default_ratio: str = '9:16'
    default_size: Optional[str] = None
    default_duration: Optional[int] = None
    enabled: bool = True
    sort_order: int = 0
    categories: List[str] = field(default_factory=list)  # 额外分类列表
    supported_image_modes: List[str] = field(default_factory=lambda: ['first_last_frame'])  # 支持的图片模式（图生视频任务）
    default_image_mode: str = 'first_last_frame'  # 默认图片模式
    supports_grid_merge: bool = False  # 是否支持宫格合并生成视频
    supports_grid_image: bool = False  # 是否支持宫格生图（一次生成多张图片）
    
    def get_computing_power(self, duration: Optional[int] = None) -> int:
        """
        获取算力消耗
        
        Args:
            duration: 时长（秒），用于按时长计费的任务
            
        Returns:
            算力消耗值
        """
        if isinstance(self.computing_power, dict):
            if duration and duration in self.computing_power:
                return self.computing_power[duration]
            # 返回字典中的第一个值作为默认
            return list(self.computing_power.values())[0] if self.computing_power else 0
        return self.computing_power
    
    def to_frontend_dict(self) -> Dict[str, Any]:
        """
        转换为前端需要的格式
        """
        all_categories = [self.category] + self.categories
        result = {
            'id': self.id,
            'key': self.key,
            'name': self.name,
            'category': self.category,
            'categories': all_categories,  # 包含主分类和额外分类
            'provider': self.provider,
            'computing_power': self.computing_power,
            'supported_ratios': self.supported_ratios,
            'default_ratio': self.default_ratio,
            'enabled': self.enabled,
            'sort_order': self.sort_order,
        }
        
        if self.supported_sizes:
            result['supported_sizes'] = self.supported_sizes
            result['default_size'] = self.default_size
            
        if self.supported_durations:
            result['supported_durations'] = self.supported_durations
            result['default_duration'] = self.default_duration or (
                self.supported_durations[0] if self.supported_durations else None
            )
        
        # 图生视频任务添加图片模式配置
        if self.category == TaskCategory.IMAGE_TO_VIDEO:
            result['supported_image_modes'] = self.supported_image_modes
            result['default_image_mode'] = self.default_image_mode
            result['supports_grid_merge'] = self.supports_grid_merge

        # 文生图任务添加宫格生图配置
        if TaskCategory.TEXT_TO_IMAGE in [self.category] + self.categories:
            result['supports_grid_image'] = self.supports_grid_image

        return result


class UnifiedConfigRegistry:
    """
    统一配置注册表 - 管理所有任务类型配置
    
    提供多种查询方式：
    - 按 ID 查询
    - 按 key 查询
    - 按分类查询
    - 按供应商查询
    """
    
    _configs: Dict[str, UnifiedTaskConfig] = {}  # key -> config
    _id_map: Dict[int, str] = {}                 # id -> key
    
    @classmethod
    def register(cls, config: UnifiedTaskConfig) -> None:
        """注册任务配置"""
        if config.key in cls._configs:
            raise ValueError(f"任务配置 key '{config.key}' 已存在")
        if config.id in cls._id_map:
            raise ValueError(f"任务配置 id {config.id} 已存在")
        
        cls._configs[config.key] = config
        cls._id_map[config.id] = config.key
    
    @classmethod
    def register_all(cls, configs: List[UnifiedTaskConfig]) -> None:
        """批量注册任务配置"""
        for config in configs:
            cls.register(config)
    
    @classmethod
    def get_by_id(cls, task_id: int) -> Optional[UnifiedTaskConfig]:
        """按 ID 获取配置"""
        key = cls._id_map.get(task_id)
        return cls._configs.get(key) if key else None
    
    @classmethod
    def get_by_key(cls, key: str) -> Optional[UnifiedTaskConfig]:
        """按 key 获取配置"""
        return cls._configs.get(key)
    
    @classmethod
    def get_by_category(cls, category: str) -> List[UnifiedTaskConfig]:
        """获取指定分类的所有配置（支持多分类）"""
        return [c for c in cls._configs.values() 
                if c.category == category or category in c.categories]
    
    @classmethod
    def get_by_provider(cls, provider: str) -> List[UnifiedTaskConfig]:
        """获取指定供应商的所有配置"""
        return [c for c in cls._configs.values() if c.provider == provider]
    
    @classmethod
    def get_all(cls) -> List[UnifiedTaskConfig]:
        """获取所有配置"""
        return list(cls._configs.values())
    
    @classmethod
    def get_all_enabled(cls) -> List[UnifiedTaskConfig]:
        """获取所有启用的配置"""
        return [c for c in cls._configs.values() if c.enabled]
    
    @classmethod
    def get_ids_by_category(cls, category: str) -> List[int]:
        """获取指定分类的所有任务ID（支持多分类）"""
        return [c.id for c in cls._configs.values() 
                if c.category == category or category in c.categories]
    
    @classmethod
    def get_ids_by_provider(cls, provider: str) -> List[int]:
        """获取指定供应商的所有任务ID（向后兼容）"""
        return [c.id for c in cls._configs.values() if c.provider == provider]
    
    @classmethod
    def get_name_map(cls) -> Dict[int, str]:
        """获取 ID -> 名称 映射（向后兼容）"""
        return {c.id: c.name for c in cls._configs.values()}
    
    @classmethod
    def get_computing_power_map(cls) -> Dict[int, Union[int, Dict[int, int]]]:
        """获取 ID -> 算力 映射（向后兼容）"""
        return {c.id: c.computing_power for c in cls._configs.values()}
    
    @classmethod
    def get_driver_mapping(cls) -> Dict[int, str]:
        """获取 ID -> 业务驱动名称 映射（向后兼容）"""
        return {c.id: c.driver_name for c in cls._configs.values() if c.driver_name}
    
    @classmethod
    def get_implementation_mapping(cls) -> Dict[str, str]:
        """获取 业务驱动名称 -> 实现驱动 映射（向后兼容）"""
        return {c.driver_name: c.implementation for c in cls._configs.values() 
                if c.driver_name and c.implementation}
    
    @classmethod
    def get_duration_options(cls) -> Dict[str, List[int]]:
        """获取模型时长选项（向后兼容 VIDEO_MODEL_DURATION_OPTIONS）"""
        result = {}
        for config in cls._configs.values():
            if config.supported_durations:
                # 使用 key 的简化形式作为键
                model_key = config.key.split('_')[0]  # 如 sora2_image_to_video -> sora2
                if model_key not in result:
                    result[model_key] = config.supported_durations
        return result
    
    @classmethod
    def get_frontend_config(cls) -> Dict[str, Any]:
        """
        获取前端需要的完整配置
        
        Returns:
            {
                'tasks': [...],  # 所有任务配置
                'categories': {...},  # 分类信息
                'providers': {...},  # 供应商信息
            }
        """
        tasks = sorted(
            [c.to_frontend_dict() for c in cls._configs.values() if c.enabled],
            key=lambda x: (x['sort_order'], x['id'])
        )
        
        categories = {
            TaskCategory.IMAGE_EDIT: '图片编辑',
            TaskCategory.TEXT_TO_VIDEO: '文生视频',
            TaskCategory.IMAGE_TO_VIDEO: '图生视频',
            TaskCategory.TEXT_TO_IMAGE: '文生图',
            TaskCategory.VISUAL_ENHANCE: '视觉增强',
            TaskCategory.AUDIO: '音频',
            TaskCategory.DIGITAL_HUMAN: '数字人',
            TaskCategory.OTHER: '其他',
        }
        
        providers = {
            TaskProvider.DUOMI: '多米',
            TaskProvider.RUNNINGHUB: 'RunningHub',
            TaskProvider.VIDU: 'Vidu',
            TaskProvider.VOLCENGINE: '火山引擎',
            TaskProvider.LOCAL: '本地',
        }
        
        return {
            'tasks': tasks,
            'categories': categories,
            'providers': providers,
        }
    
    @classmethod
    def clear(cls) -> None:
        """清除所有注册（仅用于测试）"""
        cls._configs.clear()
        cls._id_map.clear()


# ============ 驱动实现类名常量 ============
class DriverImplementation:
    """驱动实现类名常量"""
    # Sora2
    SORA2_DUOMI_V1 = 'sora2_duomi_v1'
    
    # Kling
    KLING_DUOMI_V1 = 'kling_duomi_v1'
    
    # Gemini
    GEMINI_DUOMI_V1 = 'gemini_duomi_v1'
    
    # VEO3
    VEO3_DUOMI_V1 = 'veo3_duomi_v1'
    
    # LTX2
    LTX2_RUNNINGHUB_V1 = 'ltx2_runninghub_v1'
    
    # Wan22
    WAN22_RUNNINGHUB_V1 = 'wan22_runninghub_v1'
    
    # Digital Human
    DIGITAL_HUMAN_RUNNINGHUB_V1 = 'digital_human_runninghub_v1'
    
    # Vidu
    VIDU_DEFAULT = 'vidu_default'
    VIDU_Q2 = 'vidu_q2'
    
    # Seedream 5.0
    SEEDREAM5_VOLCENGINE_V1 = 'seedream5_volcengine_v1'


# ============ 业务驱动名称常量 ============
class DriverKey:
    """业务驱动名称常量"""
    # Sora2 相关
    SORA2_TEXT_TO_VIDEO = 'sora2_text_to_video'
    SORA2_IMAGE_TO_VIDEO = 'sora2_image_to_video'
    
    # Kling 相关
    KLING_IMAGE_TO_VIDEO = 'kling_image_to_video'
    
    # Gemini 相关
    GEMINI_IMAGE_EDIT = 'gemini_image_edit'
    GEMINI_IMAGE_EDIT_PRO = 'gemini_image_edit_pro'
    
    # VEO3 相关
    VEO3_IMAGE_TO_VIDEO = 'veo3_image_to_video'
    
    # LTX2 相关
    LTX2_IMAGE_TO_VIDEO = 'ltx2_image_to_video'
    
    # Wan22 相关
    WAN22_IMAGE_TO_VIDEO = 'wan22_image_to_video'
    
    # Vidu 相关
    VIDU_IMAGE_TO_VIDEO = 'vidu_image_to_video'
    VIDU_Q2_IMAGE_TO_VIDEO = 'vidu_q2_image_to_video'
    
    # 数字人
    DIGITAL_HUMAN = 'digital_human'
    
    # 文生图
    SEEDREAM_TEXT_TO_IMAGE = 'seedream_text_to_image'


# ============ 任务类型 ID 常量 ============
class TaskTypeId:
    """任务类型ID常量"""
    # 图片编辑
    GEMINI_2_5_FLASH_IMAGE = 1          # Gemini 2.5 Flash 图片编辑（标准版）
    GEMINI_3_PRO_IMAGE = 7              # Gemini 3 Pro 图片编辑（加强版）
    GEMINI_3_1_FLASH_IMAGE = 17         # Gemini 3.1 Flash 图片编辑
    SEEDREAM_TEXT_TO_IMAGE = 16         # Seedream 5.0 文生图/图片编辑
    SEEDREAM_4_5_IMAGE = 18             # Seedream 4.5 图片编辑
    
    # 文生视频
    SORA2_TEXT_TO_VIDEO = 2             # Sora2 文生视频
    
    # 图生视频
    SORA2_IMAGE_TO_VIDEO = 3            # Sora2 图生视频
    LTX2_IMAGE_TO_VIDEO = 10            # LTX2.0 图生视频
    WAN22_IMAGE_TO_VIDEO = 11           # Wan2.2 图生视频
    KLING_IMAGE_TO_VIDEO = 12           # 可灵图生视频
    VIDU_IMAGE_TO_VIDEO = 14            # Vidu 图生视频
    VEO3_IMAGE_TO_VIDEO = 15            # VEO3.1 图生视频
    VIDU_Q2_IMAGE_TO_VIDEO = 19         # Vidu Q2 图生视频
    
    # 图片/视频 增强
    IMAGE_ENHANCE = 4                   # 图片高清放大
    VIDEO_ENHANCE = 5                   # AI视频高清修复
    
    # 其他
    CHARACTER_CARD = 8                  # 创建角色卡
    
    # 音频
    AUDIO_GENERATE = 9                  # 音频生成
    
    # 数字人
    DIGITAL_HUMAN = 13                  # 数字人生成


# ============ 所有任务配置（声明式定义）============
ALL_TASK_CONFIGS: List[UnifiedTaskConfig] = [
    # ==================== 图片编辑 ====================
    UnifiedTaskConfig(
        id=TaskTypeId.GEMINI_2_5_FLASH_IMAGE,
        key='gemini-2.5-flash-image-preview',
        name='nano-banana',
        category=TaskCategory.IMAGE_EDIT,
        categories=[TaskCategory.TEXT_TO_IMAGE],  # 同时支持文生图
        provider=TaskProvider.DUOMI,
        driver_name=DriverKey.GEMINI_IMAGE_EDIT,
        implementation=DriverImplementation.GEMINI_DUOMI_V1,
        computing_power=2,
        supported_ratios=['9:16', '16:9', '1:1', '3:4', '4:3'],
        supported_sizes=['1K'],
        default_ratio='9:16',
        default_size='1K',
        sort_order=10,
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.GEMINI_3_PRO_IMAGE,
        key='gemini-3-pro-image-preview',
        name='nano-banana-Pro',
        category=TaskCategory.IMAGE_EDIT,
        categories=[TaskCategory.TEXT_TO_IMAGE],  # 同时支持文生图
        provider=TaskProvider.DUOMI,
        driver_name=DriverKey.GEMINI_IMAGE_EDIT_PRO,
        implementation=DriverImplementation.GEMINI_DUOMI_V1,
        computing_power=6,
        supported_ratios=['9:16', '16:9', '1:1', '3:4', '4:3'],
        supported_sizes=['1K', '2K', '4K'],
        default_ratio='9:16',
        default_size='1K',
        sort_order=11,
        supports_grid_image=True,  # 支持宫格生图
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.GEMINI_3_1_FLASH_IMAGE,
        key='gemini-3.1-flash-image-preview',
        name='nano-banana-2',
        category=TaskCategory.IMAGE_EDIT,
        categories=[TaskCategory.TEXT_TO_IMAGE],  # 同时支持文生图
        provider=TaskProvider.DUOMI,
        driver_name=DriverKey.GEMINI_IMAGE_EDIT,
        implementation=DriverImplementation.GEMINI_DUOMI_V1,
        computing_power=3,
        supported_ratios=['9:16', '16:9', '1:1', '3:4', '4:3', '21:9', '1:4', '4:1', '1:8', '8:1'],
        supported_sizes=['1K', '2K', '4K'],
        default_ratio='9:16',
        default_size='1K',
        sort_order=12,
        supports_grid_image=True,  # 支持宫格生图
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.SEEDREAM_TEXT_TO_IMAGE,
        key='seedream-5.0',
        name='Seedream 5.0',
        category=TaskCategory.IMAGE_EDIT,
        categories=[TaskCategory.TEXT_TO_IMAGE],  # 同时支持文生图
        provider=TaskProvider.VOLCENGINE,
        driver_name=DriverKey.SEEDREAM_TEXT_TO_IMAGE,
        implementation=DriverImplementation.SEEDREAM5_VOLCENGINE_V1,
        computing_power=6,
        supported_ratios=['1:1', '4:3', '3:4', '16:9', '9:16', '3:2', '2:3', '21:9'],
        supported_sizes=['2K', '3K'],
        default_ratio='9:16',
        default_size='2K',
        sort_order=13,
        supports_grid_image=True,  # 支持宫格生图
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.SEEDREAM_4_5_IMAGE,
        key='seedream-4.5',
        name='Seedream 4.5',
        category=TaskCategory.IMAGE_EDIT,
        categories=[TaskCategory.TEXT_TO_IMAGE],  # 同时支持文生图
        provider=TaskProvider.VOLCENGINE,
        driver_name=DriverKey.SEEDREAM_TEXT_TO_IMAGE,
        implementation=DriverImplementation.SEEDREAM5_VOLCENGINE_V1,
        computing_power=8,
        supported_ratios=['1:1', '4:3', '3:4', '16:9', '9:16', '3:2', '2:3', '21:9'],
        supported_sizes=['2K', '4K'],
        default_ratio='9:16',
        default_size='2K',
        sort_order=14,
        supports_grid_image=True,  # 支持宫格生图
    ),
    
    # ==================== 文生视频 ====================
    UnifiedTaskConfig(
        id=TaskTypeId.SORA2_TEXT_TO_VIDEO,
        key='sora2_text_to_video',
        name='Sora2文生视频',
        category=TaskCategory.TEXT_TO_VIDEO,
        provider=TaskProvider.DUOMI,
        driver_name=DriverKey.SORA2_TEXT_TO_VIDEO,
        implementation=DriverImplementation.SORA2_DUOMI_V1,
        computing_power=18,
        supported_ratios=['9:16', '16:9'],
        supported_durations=[10, 15],
        default_ratio='9:16',
        default_duration=10,
        sort_order=20,
    ),
    
    # ==================== 图生视频 ====================
    UnifiedTaskConfig(
        id=TaskTypeId.WAN22_IMAGE_TO_VIDEO,
        key='wan22_image_to_video',
        name='图片生成视频 (Wan2.2)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.RUNNINGHUB,
        driver_name=DriverKey.WAN22_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.WAN22_RUNNINGHUB_V1,
        computing_power={5: 6, 10: 12},
        supported_ratios=['9:16', '16:9'],
        supported_durations=[5, 10],
        default_ratio='9:16',
        default_duration=5,
        sort_order=30,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME],  # 支持首尾帧
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.SORA2_IMAGE_TO_VIDEO,
        key='sora2_image_to_video',
        name='图片生成视频 (Sora2)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.DUOMI,
        driver_name=DriverKey.SORA2_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.SORA2_DUOMI_V1,
        computing_power=18,
        supported_ratios=['9:16', '16:9'],
        supported_durations=[10, 15],
        default_ratio='9:16',
        default_duration=10,
        sort_order=31,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME],  # 支持首尾帧
        supports_grid_merge=True,  # 支持宫格合并生成视频
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.LTX2_IMAGE_TO_VIDEO,
        key='ltx2_image_to_video',
        name='图片生成视频 (LTX2.0)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.RUNNINGHUB,
        driver_name=DriverKey.LTX2_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.LTX2_RUNNINGHUB_V1,
        computing_power=6,
        supported_ratios=['9:16', '16:9'],
        supported_durations=[5, 8, 10],
        default_ratio='9:16',
        default_duration=5,
        sort_order=32,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME],  # 支持首尾帧
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.KLING_IMAGE_TO_VIDEO,
        key='kling_image_to_video',
        name='图片生成视频 (可灵v2.5-turbo)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.DUOMI,
        driver_name=DriverKey.KLING_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.KLING_DUOMI_V1,
        computing_power={5: 38, 10: 70},
        supported_ratios=['9:16', '16:9'],
        supported_durations=[5, 10],
        default_ratio='9:16',
        default_duration=5,
        sort_order=33,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME],  # 支持首尾帧
        supports_grid_merge=True,  # 支持宫格合并生成视频
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.VIDU_IMAGE_TO_VIDEO,
        key='vidu_image_to_video',
        name='图片生成视频 (Vidu-q2-pro-fast)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.VIDU,
        driver_name=DriverKey.VIDU_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.VIDU_DEFAULT,
        computing_power={5: 16, 8: 22},
        supported_ratios=['9:16', '16:9'],
        supported_durations=[5, 8],
        default_ratio='9:16',
        default_duration=5,
        sort_order=34,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME],  # 支持首尾帧（1-2张图片）
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.VIDU_Q2_IMAGE_TO_VIDEO,
        key='vidu_q2_image_to_video',
        name='图片生成视频 (Vidu-Q2)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.VIDU,
        driver_name=DriverKey.VIDU_Q2_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.VIDU_Q2,
        computing_power={5: 45, 8: 60},
        supported_ratios=['9:16', '16:9'],
        supported_durations=[5, 8],
        default_ratio='9:16',
        default_duration=5,
        sort_order=36,
        supported_image_modes=[ImageMode.MULTI_REFERENCE],  # 仅支持参考图模式
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.VEO3_IMAGE_TO_VIDEO,
        key='veo3_image_to_video',
        name='图片生成视频 (VEO3.1-fast)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.DUOMI,
        driver_name=DriverKey.VEO3_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.VEO3_DUOMI_V1,
        computing_power=6,
        supported_ratios=['9:16', '16:9'],
        supported_durations=[8],
        default_ratio='9:16',
        default_duration=8,
        sort_order=35,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME,ImageMode.MULTI_REFERENCE],  # 支持首尾帧
        supports_grid_merge=True,  # 支持宫格合并生成视频
    ),
    
    # ==================== 数字人 ====================
    UnifiedTaskConfig(
        id=TaskTypeId.DIGITAL_HUMAN,
        key='digital_human',
        name='wan2.2 数字人',
        category=TaskCategory.DIGITAL_HUMAN,
        provider=TaskProvider.RUNNINGHUB,
        driver_name=DriverKey.DIGITAL_HUMAN,
        implementation=DriverImplementation.DIGITAL_HUMAN_RUNNINGHUB_V1,
        computing_power=12,
        supported_ratios=['9:16', '16:9', '1:1', '3:2', '2:3', '3:4', '4:3'],
        default_ratio='9:16',
        sort_order=40,
    ),
    
    # ==================== 图片/视频增强 ====================
    UnifiedTaskConfig(
        id=TaskTypeId.IMAGE_ENHANCE,
        key='image_enhance',
        name='图片高清放大',
        category=TaskCategory.VISUAL_ENHANCE,
        provider=TaskProvider.LOCAL,
        computing_power=1,
        sort_order=50,
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.VIDEO_ENHANCE,
        key='video_enhance',
        name='AI视频高清修复',
        category=TaskCategory.VISUAL_ENHANCE,
        provider=TaskProvider.LOCAL,
        computing_power=10,
        sort_order=51,
    ),
    
    # ==================== 角色卡 ====================
    UnifiedTaskConfig(
        id=TaskTypeId.CHARACTER_CARD,
        key='character_card',
        name='创建角色卡',
        category=TaskCategory.OTHER,
        provider=TaskProvider.LOCAL,
        computing_power=20,
        sort_order=60,
    ),
    
    # ==================== 音频 ====================
    UnifiedTaskConfig(
        id=TaskTypeId.AUDIO_GENERATE,
        key='audio_generate',
        name='AI音频生成',
        category=TaskCategory.AUDIO,
        provider=TaskProvider.LOCAL,
        computing_power=5,
        sort_order=70,
    ),
]


def init_unified_config():
    """
    初始化统一配置系统
    在应用启动时调用
    """
    if not UnifiedConfigRegistry._configs:
        UnifiedConfigRegistry.register_all(ALL_TASK_CONFIGS)


def validate_configs() -> List[str]:
    """
    验证所有配置的完整性
    
    Returns:
        错误信息列表，空列表表示验证通过
    """
    errors = []
    
    for config in ALL_TASK_CONFIGS:
        # 视频类任务必须有时长配置
        if config.category in [TaskCategory.IMAGE_TO_VIDEO, TaskCategory.TEXT_TO_VIDEO]:
            if not config.supported_durations:
                errors.append(f"{config.key}: 视频任务必须配置 supported_durations")
        
        # 有驱动的任务必须有实现
        if config.driver_name and not config.implementation:
            errors.append(f"{config.key}: 配置了 driver_name 但缺少 implementation")
        
        # 默认值必须在支持列表中
        if config.default_ratio not in config.supported_ratios:
            errors.append(f"{config.key}: default_ratio '{config.default_ratio}' 不在 supported_ratios 中")
        
        if config.supported_sizes and config.default_size not in config.supported_sizes:
            errors.append(f"{config.key}: default_size '{config.default_size}' 不在 supported_sizes 中")
        
        if config.supported_durations and config.default_duration:
            if config.default_duration not in config.supported_durations:
                errors.append(f"{config.key}: default_duration {config.default_duration} 不在 supported_durations 中")
    
    return errors


# 模块加载时自动初始化
init_unified_config()
