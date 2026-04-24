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
from typing import Optional, Union, Dict, List, Any, TYPE_CHECKING
import logging

logger = logging.getLogger(__name__)


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
    ZJT = 'zjt'


@dataclass
class PowerModifier:
    """
    算力修饰符 - 根据额外属性（如 image_mode、resolution）动态调整算力

    算力计算公式: final_power = base_power(duration) × modifier1 × modifier2 × ...

    Attributes:
        attribute: 属性名，如 'image_mode', 'resolution'
        values: 属性值 -> 乘数映射，如 {'first_last_with_tail': 1.66, 'first_last_frame': 1.0}
        default: 未匹配时的默认乘数
    """
    attribute: str
    values: Dict[str, float]
    default: float = 1.0


@dataclass
class ImplementationConfig:
    """
    实现方配置类 - 定义具体的实现方及其算力配置

    Attributes:
        name: 实现方名称（如 gemini_duomi_v1）
        display_name: 显示名称（如 "多米"）
        driver_class: 驱动类名
        default_computing_power: 默认算力（代码级后备值）
        enabled: 是否启用
        description: 描述
        driver_params: 驱动实例化参数（如 {'site_id': 'site_1'}）
        sort_order: 默认排序顺序（代码级后备值）
        site_number: 聚合站点编号（仅聚合站点有值，非聚合站点为 None）
        sync_mode: 是否为同步模式（同步API会阻塞，需要独立进程池处理）
    """
    name: str
    display_name: str
    driver_class: str
    default_computing_power: Union[int, Dict[int, int]] = 0
    enabled: bool = True
    description: str = ""
    driver_params: Dict[str, Any] = field(default_factory=dict)
    sort_order: float = 999999.0  # 默认排序到最后
    site_number: Optional[int] = None  # 仅聚合站点有值
    sync_mode: bool = False  # 是否为同步模式
    required_config_keys: List[str] = field(default_factory=list)  # 依赖的动态配置键，全部存在且有值时才算配置完整

    def get_computing_power(self, duration: Optional[int] = None, driver_key: Optional[str] = None, context: Optional[Dict[str, Any]] = None) -> int:
        """
        获取算力（优先数据库配置，其次代码默认值）

        Args:
            duration: 时长（秒），用于按时长计费的实现方
            driver_key: DriverKey，用于从数据库读取实现方算力配置
            context: 额外上下文参数（预留，用于修饰符计算）

        Returns:
            算力值
        """
        # 尝试从数据库读取（支持管理员热更新）
        try:
            from model.implementation_power import ImplementationPowerModel
            if driver_key:
                db_powers = ImplementationPowerModel.get_all_powers_for_implementation(self.name, driver_key)
                if db_powers:
                    if duration is not None and duration in db_powers:
                        return db_powers[duration]
                    if None in db_powers:
                        return db_powers[None]
                    if db_powers:
                        return list(db_powers.values())[0]
            else:
                # 兼容旧调用：未传 driver_key 时按原来的行为
                db_power = ImplementationPowerModel.get_power(self.name, duration)
                if db_power is not None:
                    return db_power
        except ImportError:
            pass
        except Exception:
            pass

        # 回退到代码默认值
        if isinstance(self.default_computing_power, dict):
            if duration and duration in self.default_computing_power:
                return self.default_computing_power[duration]
            return list(self.default_computing_power.values())[0] if self.default_computing_power else 0
        return self.default_computing_power

    def is_enabled(self) -> bool:
        """
        检查实现方是否启用（从数据库读取）

        Returns:
            True 如果启用，False 如果禁用
        """
        try:
            from model.implementation_power import ImplementationPowerModel
            return ImplementationPowerModel.is_enabled(self.name)
        except ImportError:
            pass
        except Exception:
            pass
        # 回退到代码默认值
        return self.enabled

    def get_display_name(self) -> str:
        """
        获取显示名称（优先数据库配置，其次代码默认值）

        Returns:
            显示名称
        """
        try:
            from model.implementation_power import ImplementationPowerModel
            config = ImplementationPowerModel.get_config(self.name)
            if config and config.get('display_name'):
                return config['display_name']
        except ImportError:
            pass
        except Exception:
            pass
        # 回退到代码默认值
        return self.display_name

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'name': self.name,
            'display_name': self.display_name,
            'default_computing_power': self.default_computing_power,
            'enabled': self.enabled,
            'description': self.description,
            'driver_params': self.driver_params,
            'sync_mode': self.sync_mode,
        }


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
        implementation: 默认实现驱动类名（用于 DRIVER_IMPLEMENTATION_MAPPING）
        implementations: 可选实现方列表（用户可选择），如果为空则只使用默认实现
        computing_power: 算力消耗覆盖值（优先使用），整数或按时长的字典。如果不设置则从实现方配置读取
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
    implementation: Optional[str] = None  # 默认实现方
    implementations: List[str] = field(default_factory=list)  # 可选实现方列表，注意，如果不配置，无法支持多实现方切换
    computing_power: Union[int, Dict[int, int]] = 0  # 算力覆盖值（优先使用）
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
    supports_last_frame: bool = True  # 是否支持尾帧（某些模型虽然支持首尾帧模式，但只使用首帧，忽略尾帧）
    hidden: bool = False  # 是否隐藏（隐藏的任务不在前端模型选择器中显示，仅通过API调用）
    power_modifiers: List[PowerModifier] = field(default_factory=list)  # 算力修饰符列表

    def get_computing_power(self, duration: Optional[int] = None, implementation: Optional[str] = None, context: Optional[Dict[str, Any]] = None) -> int:
        """
        获取算力消耗

        优先使用任务配置中的 computing_power，如果没有设置（或为0）则从实现方配置读取。
        先累积所有修饰符乘数，再进行一次向上取整（ceiling）。

        Args:
            duration: 时长（秒），用于按时长计费的任务
            implementation: 实现方名称，用于从实现方配置读取算力
            context: 额外上下文参数，用于修饰符计算（如 {'image_mode': 'first_last_with_tail'}）

        Returns:
            算力消耗值（整数）
        """
        import math

        # 优先使用任务配置中的算力覆盖值
        if self.computing_power:
            if isinstance(self.computing_power, dict):
                if duration and duration in self.computing_power:
                    base_power = self.computing_power[duration]
                else:
                    base_power = list(self.computing_power.values())[0] if self.computing_power else 0
            else:
                base_power = self.computing_power
        else:
            # 回退到实现方配置
            if not implementation:
                implementation = self.implementation

            if not implementation:
                return 0  # 没有实现方配置，返回0

            impl_config = UnifiedConfigRegistry.get_implementation(implementation)
            if not impl_config:
                return 0

            base_power = impl_config.get_computing_power(duration, self.driver_name)

        # 应用修饰符（累积乘数，最后一次向上取整）
        if context and self.power_modifiers:
            multiplier = 1.0
            for modifier in self.power_modifiers:
                attr_value = context.get(modifier.attribute)
                if attr_value and attr_value in modifier.values:
                    multiplier *= modifier.values[attr_value]
                else:
                    multiplier *= modifier.default
            base_power = math.ceil(base_power * multiplier)

        return int(base_power)
    
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
            'supported_ratios': self.supported_ratios,
            'default_ratio': self.default_ratio,
            'enabled': self.enabled,
            'hidden': self.hidden,
            'sort_order': self.sort_order,
            'implementation': self.implementation,  # 默认实现方
            'implementations': self._get_implementations_info(),  # 可选实现方列表
            'computing_power': self.computing_power,  # 算力配置（可能是固定值或按时长映射）
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
            result['supports_last_frame'] = self.supports_last_frame

        # 文生图任务添加宫格生图配置
        if TaskCategory.TEXT_TO_IMAGE in [self.category] + self.categories:
            result['supports_grid_image'] = self.supports_grid_image

        # 添加算力修饰符
        if self.power_modifiers:
            result['power_modifiers'] = [
                {
                    'attribute': m.attribute,
                    'values': m.values,
                    'default': m.default
                }
                for m in self.power_modifiers
            ]

        return result

    def _get_implementations_info(self) -> List[Dict[str, Any]]:
        """
        获取实现方列表及其算力信息

        对于支持 API 聚合器的任务，动态添加所有可用的聚合器实现方
        只返回 enabled=True 的实现方
        按 sort_order 排序（排序值小的在前）
        """
        result = []
        impl_names = self.implementations if self.implementations else ([self.implementation] if self.implementation else [])

        # 对于 Gemini 图片任务，动态添加 API 聚合器实现方
        if self.driver_name in [DriverKey.GEMINI_IMAGE_EDIT, DriverKey.GEMINI_IMAGE_EDIT_PRO]:
            # 获取所有已注册的 gemini_common_* 实现方
            for impl_name, impl_config in UnifiedConfigRegistry.get_all_implementations().items():
                if impl_name.startswith('gemini_common_') and impl_name not in impl_names:
                    impl_names.append(impl_name)

        for impl_name in impl_names:
            impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
            if impl_config:
                # 检查实现方是否启用（从数据库读取）
                if not impl_config.is_enabled():
                    continue

                # 获取排序值（从数据库读取，如果没有则使用默认值）
                try:
                    from model.implementation_power import ImplementationPowerModel
                    db_config = ImplementationPowerModel.get_config(impl_name, self.driver_name)
                    sort_order = db_config.get('sort_order') if db_config else None
                    if sort_order is None:
                        sort_order = impl_config.sort_order
                except Exception:
                    sort_order = impl_config.sort_order

                # 获取算力（从数据库读取，使用 driver_key 查询）
                try:
                    from model.implementation_power import ImplementationPowerModel
                    power_configs = ImplementationPowerModel.get_all_powers_for_implementation(impl_name, self.driver_name)
                    if power_configs:
                        duration_powers = {k: v for k, v in power_configs.items() if k is not None}
                        if duration_powers:
                            computing_power = duration_powers
                        elif None in power_configs:
                            computing_power = power_configs[None]
                        else:
                            computing_power = impl_config.default_computing_power
                    else:
                        computing_power = impl_config.default_computing_power
                except Exception:
                    computing_power = impl_config.default_computing_power

                result.append({
                    'name': impl_name,
                    'display_name': impl_config.get_display_name(),
                    'computing_power': computing_power,
                    'description': impl_config.description,
                    'is_default': impl_name == self.implementation,
                    'sort_order': sort_order,
                })

        # 按 sort_order 排序（排序值小的在前）
        result.sort(key=lambda x: x.get('sort_order', 999999) or 999999)
        return result


class UnifiedConfigRegistry:
    """
    统一配置注册表 - 管理所有任务类型配置和实现方配置

    提供多种查询方式：
    - 按 ID 查询
    - 按 key 查询
    - 按分类查询
    - 按供应商查询
    - 按实现方查询
    """

    _configs: Dict[str, UnifiedTaskConfig] = {}  # key -> config
    _id_map: Dict[int, str] = {}                 # id -> key
    _implementations: Dict[str, ImplementationConfig] = {}  # 实现方配置

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
    def register_implementation(cls, impl: ImplementationConfig) -> None:
        """注册实现方配置"""
        if impl.name in cls._implementations:
            raise ValueError(f"实现方配置 '{impl.name}' 已存在")
        cls._implementations[impl.name] = impl

    @classmethod
    def register_all_implementations(cls, implementations: List[ImplementationConfig]) -> None:
        """批量注册实现方配置"""
        for impl in implementations:
            cls.register_implementation(impl)

    @classmethod
    def get_implementation(cls, name: str) -> Optional[ImplementationConfig]:
        """获取实现方配置"""
        return cls._implementations.get(name)

    @classmethod
    def get_all_implementations(cls) -> Dict[str, ImplementationConfig]:
        """获取所有实现方配置"""
        return cls._implementations.copy()

    @classmethod
    def get_enabled_implementations(cls) -> List[ImplementationConfig]:
        """获取所有启用的实现方配置"""
        return [impl for impl in cls._implementations.values() if impl.enabled]
    
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
        """
        获取 ID -> 默认算力 映射

        优先使用任务配置中的 computing_power，如果没有设置（或为0）则从实现方配置读取。

        Returns:
            Dict[int, Union[int, Dict[int, int]]]: 任务类型ID到算力的映射
            - 固定算力任务返回 int
            - 按时长计费任务返回 Dict[int, int]（时长->算力）
        """
        result = {}
        for c in cls._configs.values():
            # 优先使用任务配置中的算力覆盖值
            if c.computing_power:
                result[c.id] = c.computing_power
            elif c.implementation:
                impl_config = cls.get_implementation(c.implementation)
                if impl_config:
                    result[c.id] = impl_config.default_computing_power
                else:
                    result[c.id] = 0
            else:
                result[c.id] = 0
        return result

    @classmethod
    def get_power_modifiers_map(cls) -> Dict[int, List[Dict]]:
        """
        获取 ID -> 算力修饰符 映射

        Returns:
            Dict[int, List[Dict]]: 任务类型ID到修饰符列表的映射
        """
        result = {}
        for c in cls._configs.values():
            if c.power_modifiers:
                result[c.id] = [
                    {'attribute': m.attribute, 'values': m.values, 'default': m.default}
                    for m in c.power_modifiers
                ]
        return result

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
    def get_frontend_config(cls, user_id: int = None, user_prefs: Dict[str, str] = None) -> Dict[str, Any]:
        """
        获取前端需要的完整配置

        Args:
            user_id: 用户ID（可选，如果有则应用用户偏好）
            user_prefs: 用户实现方偏好字典（可选）

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

        # 根据用户偏好更新 computing_power
        # 1. 如果有用户偏好，使用偏好实现方的算力
        # 2. 如果没有用户偏好（或未传入），使用 implementations 中排序第一位的算力
        tasks = cls._apply_user_preferences_to_tasks(tasks, user_prefs or {})

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

        # 检查 runninghub 是否已配置（延迟导入以避免循环导入）
        runninghub_configured = False
        try:
            from config.config_util import get_dynamic_config_value
            runninghub_api_key = get_dynamic_config_value("runninghub", "api_key", default="")
            runninghub_configured = bool(runninghub_api_key)
        except Exception:
            pass

        return {
            'tasks': tasks,
            'categories': categories,
            'providers': providers,
            'runninghub_configured': runninghub_configured,
        }

    @classmethod
    def _apply_user_preferences_to_tasks(cls, tasks: List[Dict], user_prefs: Dict[str, str]) -> List[Dict]:
        """
        根据用户偏好更新 tasks 中的 computing_power

        逻辑：
        1. 如果用户有偏好，使用偏好实现方的算力
        2. 如果没有偏好，使用 implementations 中排序第一位的算力

        Args:
            tasks: 任务配置列表
            user_prefs: 用户实现方偏好字典 {task_key: implementation_name}

        Returns:
            更新后的 tasks 列表
        """
        from model.implementation_power import ImplementationPowerModel

        for task in tasks:
            task_key = task.get('key')
            user_pref_impl = user_prefs.get(task_key)
            implementations = task.get('implementations', [])

            if user_pref_impl:
                # 有用户偏好，使用偏好实现方的算力
                config = cls._configs.get(task_key)
                if not config:
                    continue

                driver_name = config.driver_name if hasattr(config, 'driver_name') else None
                impl_power = None

                try:
                    db_powers = ImplementationPowerModel.get_all_powers_for_implementation(user_pref_impl, driver_name)
                    if db_powers:
                        if None in db_powers:
                            impl_power = db_powers[None]
                        else:
                            impl_power = list(db_powers.values())[0]
                except Exception as e:
                    logger.debug(f"Failed to get implementation power for {user_pref_impl}: {e}")

                # 如果数据库中没有配置，从 implementations 列表中查找
                if impl_power is None or impl_power == 0:
                    for impl in implementations:
                        if impl.get('name') == user_pref_impl:
                            impl_power = impl.get('computing_power')
                            break

                # 更新算力
                if impl_power is not None and impl_power != 0:
                    task['computing_power'] = impl_power
                    task['user_preferred_implementation'] = user_pref_impl
            elif implementations and (task.get('computing_power') == 0 or not task.get('computing_power')):
                # 没有用户偏好，且任务的 computing_power 为 0 或未设置时，使用 implementations 中排序第一位的算力
                # implementations 已经按 sort_order 排序
                first_impl = implementations[0]
                impl_name = first_impl.get('name')
                impl_power = first_impl.get('computing_power')

                if impl_power is not None and impl_power != 0:
                    task['computing_power'] = impl_power
                    task['default_implementation'] = impl_name

        return tasks
    
    @classmethod
    def clear(cls) -> None:
        """清除所有注册（仅用于测试）"""
        cls._configs.clear()
        cls._id_map.clear()
        cls._implementations.clear()


# ============ 驱动实现类名常量 ============
class DriverImplementation:
    """驱动实现类名常量"""
    # Sora2
    SORA2_DUOMI_V1 = 'sora2_duomi_v1'

    # Kling
    KLING_DUOMI_V1 = 'kling_duomi_v1'
    KLING_COMMON_SITE0_V1 = 'kling_common_site0_v1'
    KLING_COMMON_SITE1_V1 = 'kling_common_site1_v1'
    KLING_COMMON_SITE2_V1 = 'kling_common_site2_v1'
    KLING_COMMON_SITE3_V1 = 'kling_common_site3_v1'
    KLING_COMMON_SITE4_V1 = 'kling_common_site4_v1'
    KLING_COMMON_SITE5_V1 = 'kling_common_site5_v1'

    # Gemini
    GEMINI_DUOMI_V1 = 'gemini_duomi_v1'
    GEMINI_IMAGE_PREVIEW_COMMON_V1 = 'gemini_image_preview_common_v1'
    GEMINI_IMAGE_PREVIEW_SITE0_V1 = 'gemini_image_preview_site0_v1'
    GEMINI_IMAGE_PREVIEW_SITE1_V1 = 'gemini_image_preview_site1_v1'
    GEMINI_IMAGE_PREVIEW_SITE2_V1 = 'gemini_image_preview_site2_v1'
    GEMINI_IMAGE_PREVIEW_SITE3_V1 = 'gemini_image_preview_site3_v1'
    GEMINI_IMAGE_PREVIEW_SITE4_V1 = 'gemini_image_preview_site4_v1'
    GEMINI_IMAGE_PREVIEW_SITE5_V1 = 'gemini_image_preview_site5_v1'

    # VEO3
    VEO3_DUOMI_V1 = 'veo3_duomi_v1'
    VEO3_COMMON_SITE0_V1 = 'veo3_common_site0_v1'
    VEO3_COMMON_SITE1_V1 = 'veo3_common_site1_v1'
    VEO3_COMMON_SITE2_V1 = 'veo3_common_site2_v1'
    VEO3_COMMON_SITE3_V1 = 'veo3_common_site3_v1'
    VEO3_COMMON_SITE4_V1 = 'veo3_common_site4_v1'
    VEO3_COMMON_SITE5_V1 = 'veo3_common_site5_v1'

    # LTX2
    LTX2_RUNNINGHUB_V1 = 'ltx2_runninghub_v1'
    LTX2_3_RUNNINGHUB_V1 = 'ltx2.3_runninghub_v1'

    # Wan22
    WAN22_RUNNINGHUB_V1 = 'wan22_runninghub_v1'

    # Digital Human
    DIGITAL_HUMAN_RUNNINGHUB_V1 = 'digital_human_runninghub_v1'

    # Vidu
    VIDU_DEFAULT = 'vidu_default'
    VIDU_Q2 = 'vidu_q2'

    # Seedream 5.0
    SEEDREAM5_VOLCENGINE_V1 = 'seedream5_volcengine_v1'

    # Seedance (图生视频)
    SEEDANCE_1_5_PRO_VOLCENGINE_V1 = 'seedance_1_5_pro_volcengine_v1'
    SEEDANCE_2_0_FAST_VOLCENGINE_V1 = 'seedance_2_0_fast_volcengine_v1'
    SEEDANCE_2_0_VOLCENGINE_V1 = 'seedance_2_0_volcengine_v1'

    # GPT Image
    DUOMI_GPT_IMAGE_V1 = 'duomi_gpt_image_v1'
    GPT_IMAGE_COMMON_SITE0_V1 = 'gpt_image_common_site0_v1'
    GPT_IMAGE_COMMON_SITE1_V1 = 'gpt_image_common_site1_v1'
    GPT_IMAGE_COMMON_SITE2_V1 = 'gpt_image_common_site2_v1'
    GPT_IMAGE_COMMON_SITE3_V1 = 'gpt_image_common_site3_v1'
    GPT_IMAGE_COMMON_SITE4_V1 = 'gpt_image_common_site4_v1'
    GPT_IMAGE_COMMON_SITE5_V1 = 'gpt_image_common_site5_v1'

    # Qwen Multi-Angle
    QWEN_MULTI_ANGLE_RUNNINGHUB_V1 = 'qwen_multi_angle_runninghub_v1'

    # Grok
    GROK_DUOMI_V1 = 'grok_duomi_v1'
    GROK_COMMON_SITE0_V1 = 'grok_common_site0_v1'
    GROK_COMMON_SITE1_V1 = 'grok_common_site1_v1'
    GROK_COMMON_SITE2_V1 = 'grok_common_site2_v1'
    GROK_COMMON_SITE3_V1 = 'grok_common_site3_v1'
    GROK_COMMON_SITE4_V1 = 'grok_common_site4_v1'
    GROK_COMMON_SITE5_V1 = 'grok_common_site5_v1'


# ============ 驱动实现 ID 常量（用于数据库存储） ============
class DriverImplementationId:
    """驱动实现 ID 常量，与 DriverImplementation 字符串一一对应"""
    UNKNOWN = 0
    SORA2_DUOMI_V1 = 1
    KLING_DUOMI_V1 = 2
    GEMINI_DUOMI_V1 = 3
    GEMINI_IMAGE_PREVIEW_COMMON_V1 = 4
    GEMINI_IMAGE_PREVIEW_SITE0_V1 = 27
    GEMINI_IMAGE_PREVIEW_SITE1_V1 = 5
    GEMINI_IMAGE_PREVIEW_SITE2_V1 = 6
    GEMINI_IMAGE_PREVIEW_SITE3_V1 = 7
    GEMINI_IMAGE_PREVIEW_SITE4_V1 = 8
    GEMINI_IMAGE_PREVIEW_SITE5_V1 = 9
    VEO3_DUOMI_V1 = 10
    LTX2_RUNNINGHUB_V1 = 11
    WAN22_RUNNINGHUB_V1 = 12
    DIGITAL_HUMAN_RUNNINGHUB_V1 = 13
    VIDU_DEFAULT = 14
    VIDU_Q2 = 15
    SEEDREAM5_VOLCENGINE_V1 = 16
    LTX2_3_RUNNINGHUB_V1 = 17
    SEEDANCE_1_5_PRO_VOLCENGINE_V1 = 18
    SEEDANCE_2_0_FAST_VOLCENGINE_V1 = 19
    SEEDANCE_2_0_VOLCENGINE_V1 = 20
    QWEN_MULTI_ANGLE_RUNNINGHUB_V1 = 21
    VEO3_COMMON_SITE1_V1 = 22
    DUOMI_GPT_IMAGE_V1 = 29
    GPT_IMAGE_COMMON_SITE0_V1 = 30
    GPT_IMAGE_COMMON_SITE1_V1 = 31
    GPT_IMAGE_COMMON_SITE2_V1 = 32
    GPT_IMAGE_COMMON_SITE3_V1 = 33
    GPT_IMAGE_COMMON_SITE4_V1 = 34
    GPT_IMAGE_COMMON_SITE5_V1 = 35
    VEO3_COMMON_SITE2_V1 = 23
    VEO3_COMMON_SITE3_V1 = 24
    VEO3_COMMON_SITE4_V1 = 25
    VEO3_COMMON_SITE5_V1 = 26
    VEO3_COMMON_SITE0_V1 = 28

    # Kling Common
    KLING_COMMON_SITE0_V1 = 36
    KLING_COMMON_SITE1_V1 = 37
    KLING_COMMON_SITE2_V1 = 38
    KLING_COMMON_SITE3_V1 = 39
    KLING_COMMON_SITE4_V1 = 40
    KLING_COMMON_SITE5_V1 = 41

    GROK_COMMON_SITE0_V1 = 42
    GROK_COMMON_SITE1_V1 = 43
    GROK_COMMON_SITE2_V1 = 44
    GROK_COMMON_SITE3_V1 = 45
    GROK_COMMON_SITE4_V1 = 46
    GROK_COMMON_SITE5_V1 = 47
    GROK_DUOMI_V1 = 48


# implementation 字符串到 ID 的映射
IMPLEMENTATION_TO_ID = {
    'sora2_duomi_v1': DriverImplementationId.SORA2_DUOMI_V1,
    'kling_duomi_v1': DriverImplementationId.KLING_DUOMI_V1,
    'gemini_duomi_v1': DriverImplementationId.GEMINI_DUOMI_V1,
    'gemini_image_preview_common_v1': DriverImplementationId.GEMINI_IMAGE_PREVIEW_COMMON_V1,
    'gemini_image_preview_site0_v1': DriverImplementationId.GEMINI_IMAGE_PREVIEW_SITE0_V1,
    'gemini_image_preview_site1_v1': DriverImplementationId.GEMINI_IMAGE_PREVIEW_SITE1_V1,
    'gemini_image_preview_site2_v1': DriverImplementationId.GEMINI_IMAGE_PREVIEW_SITE2_V1,
    'gemini_image_preview_site3_v1': DriverImplementationId.GEMINI_IMAGE_PREVIEW_SITE3_V1,
    'gemini_image_preview_site4_v1': DriverImplementationId.GEMINI_IMAGE_PREVIEW_SITE4_V1,
    'gemini_image_preview_site5_v1': DriverImplementationId.GEMINI_IMAGE_PREVIEW_SITE5_V1,
    'veo3_duomi_v1': DriverImplementationId.VEO3_DUOMI_V1,
    'veo3_common_site0_v1': DriverImplementationId.VEO3_COMMON_SITE0_V1,
    'ltx2_runninghub_v1': DriverImplementationId.LTX2_RUNNINGHUB_V1,
    'wan22_runninghub_v1': DriverImplementationId.WAN22_RUNNINGHUB_V1,
    'digital_human_runninghub_v1': DriverImplementationId.DIGITAL_HUMAN_RUNNINGHUB_V1,
    'vidu_default': DriverImplementationId.VIDU_DEFAULT,
    'vidu_q2': DriverImplementationId.VIDU_Q2,
    'seedream5_volcengine_v1': DriverImplementationId.SEEDREAM5_VOLCENGINE_V1,
    'ltx2.3_runninghub_v1': DriverImplementationId.LTX2_3_RUNNINGHUB_V1,
    'seedance_1_5_pro_volcengine_v1': DriverImplementationId.SEEDANCE_1_5_PRO_VOLCENGINE_V1,
    'seedance_2_0_fast_volcengine_v1': DriverImplementationId.SEEDANCE_2_0_FAST_VOLCENGINE_V1,
    'seedance_2_0_volcengine_v1': DriverImplementationId.SEEDANCE_2_0_VOLCENGINE_V1,
    'qwen_multi_angle_runninghub_v1': DriverImplementationId.QWEN_MULTI_ANGLE_RUNNINGHUB_V1,
    'veo3_common_site1_v1': DriverImplementationId.VEO3_COMMON_SITE1_V1,
    'duomi_gpt_image_v1': DriverImplementationId.DUOMI_GPT_IMAGE_V1,
    'gpt_image_common_site0_v1': DriverImplementationId.GPT_IMAGE_COMMON_SITE0_V1,
    'gpt_image_common_site1_v1': DriverImplementationId.GPT_IMAGE_COMMON_SITE1_V1,
    'gpt_image_common_site2_v1': DriverImplementationId.GPT_IMAGE_COMMON_SITE2_V1,
    'gpt_image_common_site3_v1': DriverImplementationId.GPT_IMAGE_COMMON_SITE3_V1,
    'gpt_image_common_site4_v1': DriverImplementationId.GPT_IMAGE_COMMON_SITE4_V1,
    'gpt_image_common_site5_v1': DriverImplementationId.GPT_IMAGE_COMMON_SITE5_V1,
    'kling_common_site0_v1': DriverImplementationId.KLING_COMMON_SITE0_V1,
    'kling_common_site1_v1': DriverImplementationId.KLING_COMMON_SITE1_V1,
    'kling_common_site2_v1': DriverImplementationId.KLING_COMMON_SITE2_V1,
    'kling_common_site3_v1': DriverImplementationId.KLING_COMMON_SITE3_V1,
    'kling_common_site4_v1': DriverImplementationId.KLING_COMMON_SITE4_V1,
    'kling_common_site5_v1': DriverImplementationId.KLING_COMMON_SITE5_V1,
    'veo3_common_site2_v1': DriverImplementationId.VEO3_COMMON_SITE2_V1,
    'veo3_common_site3_v1': DriverImplementationId.VEO3_COMMON_SITE3_V1,
    'veo3_common_site4_v1': DriverImplementationId.VEO3_COMMON_SITE4_V1,
    'veo3_common_site5_v1': DriverImplementationId.VEO3_COMMON_SITE5_V1,
    'grok_common_site0_v1': DriverImplementationId.GROK_COMMON_SITE0_V1,
    'grok_common_site1_v1': DriverImplementationId.GROK_COMMON_SITE1_V1,
    'grok_common_site2_v1': DriverImplementationId.GROK_COMMON_SITE2_V1,
    'grok_common_site3_v1': DriverImplementationId.GROK_COMMON_SITE3_V1,
    'grok_common_site4_v1': DriverImplementationId.GROK_COMMON_SITE4_V1,
    'grok_common_site5_v1': DriverImplementationId.GROK_COMMON_SITE5_V1,
    'grok_duomi_v1': DriverImplementationId.GROK_DUOMI_V1,
}

# implementation ID 到字符串的映射
IMPLEMENTATION_FROM_ID = {v: k for k, v in IMPLEMENTATION_TO_ID.items()}


def get_implementation_id(name: str) -> int:
    """获取 implementation 的 ID，不存在返回 0"""
    return IMPLEMENTATION_TO_ID.get(name, 0)


def get_implementation_name(id: int) -> str:
    """根据 ID 获取 implementation 名称，不存在返回 'unknown'"""
    return IMPLEMENTATION_FROM_ID.get(id, 'unknown')


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
    GEMINI_3_1_FLASH_IMAGE_EDIT = 'gemini_3_1_flash_image_edit'
    
    # VEO3 相关
    VEO3_IMAGE_TO_VIDEO = 'veo3_image_to_video'
    
    # LTX2 相关
    LTX2_IMAGE_TO_VIDEO = 'ltx2_image_to_video'
    LTX2_3_IMAGE_TO_VIDEO = 'ltx2_3_image_to_video'

    # Wan22 相关
    WAN22_IMAGE_TO_VIDEO = 'wan22_image_to_video'
    
    # Vidu 相关
    VIDU_IMAGE_TO_VIDEO = 'vidu_image_to_video'
    VIDU_Q2_IMAGE_TO_VIDEO = 'vidu_q2_image_to_video'
    
    # 数字人
    DIGITAL_HUMAN = 'digital_human'

    # Qwen Multi-Angle
    QWEN_MULTI_ANGLE_IMAGE_EDIT = 'qwen_multi_angle_image_edit'
    
    # 文生图
    SEEDREAM_TEXT_TO_IMAGE = 'seedream_text_to_image'
    GPT_IMAGE_2 = 'gpt_image_2'

    # Seedance 图生视频
    SEEDANCE_1_5_PRO_IMAGE_TO_VIDEO = 'seedance_1_5_pro_image_to_video'
    SEEDANCE_2_0_FAST_IMAGE_TO_VIDEO = 'seedance_2_0_fast_image_to_video'
    SEEDANCE_2_0_IMAGE_TO_VIDEO = 'seedance_2_0_image_to_video'

    # Grok 图生视频
    GROK_IMAGE_TO_VIDEO = 'grok_image_to_video'


# ============ 任务类型 ID 常量 ============
class TaskTypeId:
    """任务类型ID常量"""
    # 图片编辑
    GEMINI_2_5_FLASH_IMAGE = 1          # Gemini 2.5 Flash 图片编辑（标准版）
    GEMINI_3_PRO_IMAGE = 7              # Gemini 3 Pro 图片编辑（加强版）
    GEMINI_3_1_FLASH_IMAGE = 17         # Gemini 3.1 Flash 图片编辑
    SEEDREAM_TEXT_TO_IMAGE = 16         # Seedream 5.0 文生图/图片编辑
    SEEDREAM_4_5_IMAGE = 18             # Seedream 4.5 图片编辑
    QWEN_MULTI_ANGLE_IMAGE = 24         # Qwen 多角度图片编辑
    GPT_IMAGE_2 = 25                     # GPT Image 2 文生图
    GPT_IMAGE_2_EDIT = 26                # GPT Image 2 图片编辑

    # 文生视频
    SORA2_TEXT_TO_VIDEO = 2             # Sora2 文生视频
    
    # 图生视频
    SORA2_IMAGE_TO_VIDEO = 3            # Sora2 图生视频
    LTX2_IMAGE_TO_VIDEO = 10            # LTX2.0 图生视频
    LTX2_3_IMAGE_TO_VIDEO = 20          # LTX2.3 图生视频
    WAN22_IMAGE_TO_VIDEO = 11           # Wan2.2 图生视频
    KLING_IMAGE_TO_VIDEO = 12           # 可灵图生视频
    VIDU_IMAGE_TO_VIDEO = 14            # Vidu 图生视频
    VEO3_IMAGE_TO_VIDEO = 15            # VEO3.1 图生视频
    VIDU_Q2_IMAGE_TO_VIDEO = 19         # Vidu Q2 图生视频
    SEEDANCE_1_5_PRO_IMAGE_TO_VIDEO = 21  # Seedance 1.5 Pro 图生视频
    SEEDANCE_2_0_FAST_IMAGE_TO_VIDEO = 22 # Seedance 2.0 Fast 图生视频
    SEEDANCE_2_0_IMAGE_TO_VIDEO = 23      # Seedance 2.0 图生视频
    GROK_IMAGE_TO_VIDEO = 27             # Grok 图生视频

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
        implementations=[
            DriverImplementation.GEMINI_DUOMI_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE0_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE1_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE2_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE3_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE4_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE5_V1,
        ],
        computing_power=2,
        supported_ratios=['9:16', '16:9', '1:1', '3:4', '4:3'],
        supported_sizes=['1K'],
        default_ratio='9:16',
        default_size='1K',
        sort_order=10,
        supports_grid_image=False, 
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
        implementations=[
            DriverImplementation.GEMINI_DUOMI_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE0_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE1_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE2_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE3_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE4_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE5_V1,
        ],
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
        driver_name=DriverKey.GEMINI_3_1_FLASH_IMAGE_EDIT,
        implementation=DriverImplementation.GEMINI_DUOMI_V1,
        implementations=[
            DriverImplementation.GEMINI_DUOMI_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE0_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE1_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE2_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE3_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE4_V1,
            DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE5_V1,
        ],
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
    UnifiedTaskConfig(
        id=TaskTypeId.QWEN_MULTI_ANGLE_IMAGE,
        key='qwen-multi-angle',
        name='多角度图片编辑',
        category=TaskCategory.IMAGE_EDIT,
        provider=TaskProvider.RUNNINGHUB,
        driver_name=DriverKey.QWEN_MULTI_ANGLE_IMAGE_EDIT,
        implementation=DriverImplementation.QWEN_MULTI_ANGLE_RUNNINGHUB_V1,
        computing_power=2,
        supported_ratios=['9:16', '16:9'],
        supported_sizes=['1K'],
        default_ratio='16:9',
        default_size='1K',
        sort_order=15,
        hidden=True,  # 隐藏，前端不显示
    ),

    # ==================== 文生图/图片编辑 ====================
    UnifiedTaskConfig(
        id=TaskTypeId.GPT_IMAGE_2_EDIT,
        key='gpt-image-2-edit',
        name='GPT Image 2 图片编辑',
        category=TaskCategory.IMAGE_EDIT,
        categories=[TaskCategory.TEXT_TO_IMAGE],  # 同时支持文生图
        provider=TaskProvider.DUOMI,
        driver_name=DriverKey.GPT_IMAGE_2,
        implementation=DriverImplementation.DUOMI_GPT_IMAGE_V1,
        implementations=[
            DriverImplementation.DUOMI_GPT_IMAGE_V1,
            DriverImplementation.GPT_IMAGE_COMMON_SITE0_V1,
            DriverImplementation.GPT_IMAGE_COMMON_SITE1_V1,
            DriverImplementation.GPT_IMAGE_COMMON_SITE2_V1,
            DriverImplementation.GPT_IMAGE_COMMON_SITE3_V1,
            DriverImplementation.GPT_IMAGE_COMMON_SITE4_V1,
            DriverImplementation.GPT_IMAGE_COMMON_SITE5_V1,
        ],
        computing_power=2,
        supported_ratios=['1:1', '2:3', '3:2', '16:9', '9:16'],
        supported_sizes=['1k', '2k', '4k'],
        default_ratio='1:1',
        default_size='1k',
        sort_order=17,
        supports_grid_image=True,
        supports_grid_merge=False,
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
        sort_order=200,
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
        computing_power={5: 8, 10: 18},
        supported_ratios=['9:16', '16:9'],
        supported_durations=[5, 10],
        default_ratio='9:16',
        default_duration=5,
        sort_order=32,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME],  # 支持首尾帧
        supports_last_frame=False,  # 当前仅支持单图（忽略尾帧）
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
        supports_last_frame=False,  # 当前仅支持单图（忽略尾帧）
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
        sort_order=33,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME],  # 支持首尾帧
        supports_last_frame=False,  # 当前仅支持单图（忽略尾帧）
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.LTX2_3_IMAGE_TO_VIDEO,
        key='ltx2_3_image_to_video',
        name='图片生成视频 (LTX2.3)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.RUNNINGHUB,
        driver_name=DriverKey.LTX2_3_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.LTX2_3_RUNNINGHUB_V1,
        computing_power=6,
        supported_ratios=['9:16', '16:9'],
        supported_durations=[5, 8, 10],
        default_ratio='9:16',
        default_duration=5,
        sort_order=30,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME],  # 支持首尾帧
        supports_last_frame=False,  # 当前仅支持单图（忽略尾帧）
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.KLING_IMAGE_TO_VIDEO,
        key='kling_image_to_video',
        name='图片生成视频 (可灵v2.5-turbo)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.DUOMI,
        driver_name=DriverKey.KLING_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.KLING_DUOMI_V1,
        implementations=[
            DriverImplementation.KLING_DUOMI_V1,
            DriverImplementation.KLING_COMMON_SITE0_V1,
            DriverImplementation.KLING_COMMON_SITE1_V1,
            DriverImplementation.KLING_COMMON_SITE2_V1,
            DriverImplementation.KLING_COMMON_SITE3_V1,
            DriverImplementation.KLING_COMMON_SITE4_V1,
            DriverImplementation.KLING_COMMON_SITE5_V1,
        ],
        supported_ratios=['9:16', '16:9'],
        supported_durations=[5, 10],
        default_ratio='9:16',
        default_duration=5,
        sort_order=33,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME],  # 支持首尾帧
        supports_last_frame=True,  # 支持首尾帧
        supports_grid_merge=True,  # 支持宫格合并生成视频
        power_modifiers=[
            PowerModifier(
                attribute='image_mode',
                values={
                    'first_last_with_tail': 1.66,  # 前后帧（有2张图）比首帧贵 1.66 倍
                    'first_last_frame': 1.0,        # 仅首帧
                },
                default=1.0
            )
        ]
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.VIDU_IMAGE_TO_VIDEO,
        key='vidu_image_to_video',
        name='图片生成视频 (Vidu-q2-pro-fast)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.VIDU,
        driver_name=DriverKey.VIDU_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.VIDU_DEFAULT,
        supported_ratios=['9:16', '16:9'],
        supported_durations=[5, 8],
        default_ratio='9:16',
        default_duration=5,
        sort_order=34,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME],  # 支持首尾帧（1-2张图片）
        supports_last_frame=True,  # 真正支持尾帧
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.VIDU_Q2_IMAGE_TO_VIDEO,
        key='vidu_q2_image_to_video',
        name='图片生成视频 (Vidu-Q2)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.VIDU,
        driver_name=DriverKey.VIDU_Q2_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.VIDU_Q2,
        supported_ratios=['9:16', '16:9'],
        supported_durations=[5, 8],
        default_ratio='9:16',
        default_duration=5,
        sort_order=36,
        supported_image_modes=[ImageMode.MULTI_REFERENCE],  # 仅支持参考图模式
        supports_last_frame=False,  # 不支持尾帧（多参考图模式）
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.VEO3_IMAGE_TO_VIDEO,
        key='veo3_image_to_video',
        name='图片生成视频 (VEO3.1-fast)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.DUOMI,
        driver_name=DriverKey.VEO3_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.VEO3_DUOMI_V1,
        implementations=[
            DriverImplementation.VEO3_DUOMI_V1,
            DriverImplementation.VEO3_COMMON_SITE0_V1,
            DriverImplementation.VEO3_COMMON_SITE1_V1,
            DriverImplementation.VEO3_COMMON_SITE2_V1,
            DriverImplementation.VEO3_COMMON_SITE3_V1,
            DriverImplementation.VEO3_COMMON_SITE4_V1,
            DriverImplementation.VEO3_COMMON_SITE5_V1,
        ],
        supported_ratios=['9:16', '16:9'],
        supported_durations=[8],
        default_ratio='9:16',
        default_duration=8,
        sort_order=35,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME,ImageMode.MULTI_REFERENCE],  # 支持首尾帧
        supports_last_frame=True,  # 真正支持尾帧
        supports_grid_merge=True,  # 支持宫格合并生成视频
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.GROK_IMAGE_TO_VIDEO,
        key='grok_image_to_video',
        name='图片生成视频 (Grok)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.DUOMI,
        driver_name=DriverKey.GROK_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.GROK_DUOMI_V1,
        implementations=[
            DriverImplementation.GROK_DUOMI_V1,
            DriverImplementation.GROK_COMMON_SITE0_V1,
            DriverImplementation.GROK_COMMON_SITE1_V1,
            DriverImplementation.GROK_COMMON_SITE2_V1,
            DriverImplementation.GROK_COMMON_SITE3_V1,
            DriverImplementation.GROK_COMMON_SITE4_V1,
            DriverImplementation.GROK_COMMON_SITE5_V1,
        ],
        supported_ratios=['9:16', '16:9', '1:1', '2:3', '3:2'],
        supported_durations=[10],
        default_ratio='9:16',
        default_duration=10,
        sort_order=36,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME],
        supports_last_frame=False,  # 不支持尾帧
        supports_grid_merge=True,  # 支持宫格合并生成视频
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.SEEDANCE_1_5_PRO_IMAGE_TO_VIDEO,
        key='seedance_1_5_pro_image_to_video',
        name='图片生成视频 (Seedance 1.5 Pro)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.VOLCENGINE,
        driver_name=DriverKey.SEEDANCE_1_5_PRO_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.SEEDANCE_1_5_PRO_VOLCENGINE_V1,
        supported_ratios=['9:16', '16:9'],
        supported_durations=[5, 6, 7, 8, 9, 10, 11, 12],
        default_ratio='9:16',
        default_duration=5,
        sort_order=37,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME],  # 1.5 Pro 不支持多参考图
        supports_last_frame=True,  # 支持首尾帧
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.SEEDANCE_2_0_FAST_IMAGE_TO_VIDEO,
        key='seedance_2_0_fast_image_to_video',
        name='图片生成视频 (Seedance 2.0 Fast)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.VOLCENGINE,
        driver_name=DriverKey.SEEDANCE_2_0_FAST_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.SEEDANCE_2_0_FAST_VOLCENGINE_V1,
        supported_ratios=['9:16', '16:9'],
        supported_durations=[5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
        default_ratio='9:16',
        default_duration=5,
        sort_order=38,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME, ImageMode.MULTI_REFERENCE],
        supports_last_frame=True,  # 支持首尾帧
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.SEEDANCE_2_0_IMAGE_TO_VIDEO,
        key='seedance_2_0_image_to_video',
        name='图片生成视频 (Seedance 2.0)',
        category=TaskCategory.IMAGE_TO_VIDEO,
        provider=TaskProvider.VOLCENGINE,
        driver_name=DriverKey.SEEDANCE_2_0_IMAGE_TO_VIDEO,
        implementation=DriverImplementation.SEEDANCE_2_0_VOLCENGINE_V1,
        supported_ratios=['9:16', '16:9'],
        supported_durations=[5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
        default_ratio='9:16',
        default_duration=5,
        sort_order=39,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME, ImageMode.MULTI_REFERENCE],
        supports_last_frame=True,  # 支持首尾帧
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
        implementation='local_enhance',
        sort_order=50,
    ),
    UnifiedTaskConfig(
        id=TaskTypeId.VIDEO_ENHANCE,
        key='video_enhance',
        name='AI视频高清修复',
        category=TaskCategory.VISUAL_ENHANCE,
        provider=TaskProvider.LOCAL,
        implementation='local_video_enhance',
        sort_order=51,
    ),

    # ==================== 角色卡 ====================
    UnifiedTaskConfig(
        id=TaskTypeId.CHARACTER_CARD,
        key='character_card',
        name='创建角色卡',
        category=TaskCategory.OTHER,
        provider=TaskProvider.LOCAL,
        implementation='character_card',
        sort_order=60,
    ),

    # ==================== 音频 ====================
    UnifiedTaskConfig(
        id=TaskTypeId.AUDIO_GENERATE,
        key='audio_generate',
        name='AI音频生成',
        category=TaskCategory.AUDIO,
        provider=TaskProvider.LOCAL,
        computing_power=0,  # 音频生成不消耗算力
        sort_order=70,
    ),
]


# ============ 静态实现方配置 ============
ALL_IMPLEMENTATIONS: List[ImplementationConfig] = [
    # ==================== 多米供应商 ====================
    ImplementationConfig(
        name='sora2_duomi_v1',
        display_name='多米',
        driver_class='Sora2DuomiV1Driver',
        default_computing_power=18,
        enabled=True,
        description='多米平台 Sora2 接口',
        sort_order=1000.0,
        required_config_keys=['duomi.token']
    ),
    ImplementationConfig(
        name='kling_duomi_v1',
        display_name='多米',
        driver_class='KlingDuomiV1Driver',
        default_computing_power={5: 38, 10: 70},
        enabled=True,
        description='多米平台 Kling 接口',
        sort_order=2010.0,
        required_config_keys=['duomi.token']
    ),
    # ==================== Kling 通用聚合站点 ====================
    ImplementationConfig(
        name='kling_common_site0_v1',
        display_name='ZJTapi',
        driver_class='KlingCommonSite0V1Driver',
        default_computing_power={5: 38, 10: 70},
        enabled=True,
        description='ZJTapi Kling 接口',
        sort_order=2000.0,
        site_number=0,
        required_config_keys=['api_aggregator.site_0.api_key']
    ),
    ImplementationConfig(
        name='kling_common_site1_v1',
        display_name='聚合站点1',
        driver_class='KlingCommonSite1V1Driver',
        default_computing_power={5: 38, 10: 70},
        enabled=True,
        description='聚合站点1 Kling 接口',
        sort_order=2020.0,
        site_number=1,
        required_config_keys=['api_aggregator.site_1.api_key', 'api_aggregator.site_1.base_url']
    ),
    ImplementationConfig(
        name='kling_common_site2_v1',
        display_name='聚合站点2',
        driver_class='KlingCommonSite2V1Driver',
        default_computing_power={5: 38, 10: 70},
        enabled=True,
        description='聚合站点2 Kling 接口',
        sort_order=2030.0,
        site_number=2,
        required_config_keys=['api_aggregator.site_2.api_key', 'api_aggregator.site_2.base_url']
    ),
    ImplementationConfig(
        name='kling_common_site3_v1',
        display_name='聚合站点3',
        driver_class='KlingCommonSite3V1Driver',
        default_computing_power={5: 38, 10: 70},
        enabled=True,
        description='聚合站点3 Kling 接口',
        sort_order=2040.0,
        site_number=3,
        required_config_keys=['api_aggregator.site_3.api_key', 'api_aggregator.site_3.base_url']
    ),
    ImplementationConfig(
        name='kling_common_site4_v1',
        display_name='聚合站点4',
        driver_class='KlingCommonSite4V1Driver',
        default_computing_power={5: 38, 10: 70},
        enabled=True,
        description='聚合站点4 Kling 接口',
        sort_order=2050.0,
        site_number=4,
        required_config_keys=['api_aggregator.site_4.api_key', 'api_aggregator.site_4.base_url']
    ),
    ImplementationConfig(
        name='kling_common_site5_v1',
        display_name='聚合站点5',
        driver_class='KlingCommonSite5V1Driver',
        default_computing_power={5: 38, 10: 70},
        enabled=True,
        description='聚合站点5 Kling 接口',
        sort_order=2060.0,
        site_number=5,
        required_config_keys=['api_aggregator.site_5.api_key', 'api_aggregator.site_5.base_url']
    ),
    ImplementationConfig(
        name='gemini_duomi_v1',
        display_name='多米',
        driver_class='GeminiDuomiV1Driver',
        default_computing_power=2,
        enabled=True,
        description='多米平台 Gemini 接口',
        sort_order=3000.0,
        required_config_keys=['duomi.token']
    ),
    ImplementationConfig(
        name='duomi_gpt_image_v1',
        display_name='多米',
        driver_class='GptImageDuomiV1Driver',
        default_computing_power=2,
        enabled=True,
        description='多米平台 GPT Image 2 接口（仅支持1K分辨率）',
        sort_order=3200.0,
        required_config_keys=['duomi.token']
    ),
    # ==================== GPT Image 2 通用聚合站点 ====================
    ImplementationConfig(
        name='gpt_image_common_site0_v1',
        display_name='ZJTapi',
        driver_class='GptImageCommonSite0V1Driver',
        default_computing_power=2,
        enabled=True,
        description='ZJT官方',
        sort_order=3100.0,
        sync_mode=True,  # 同步模式
        site_number=0,
        required_config_keys=['api_aggregator.site_0.api_key']
    ),
    ImplementationConfig(
        name='gpt_image_common_site1_v1',
        display_name='gpt_site1',
        driver_class='GptImageCommonSite1V1Driver',
        default_computing_power=2,
        enabled=True,
        description='site 1',
        sort_order=3210.0,
        sync_mode=True,
        site_number=1,
        required_config_keys=['api_aggregator.site_1.api_key', 'api_aggregator.site_1.base_url']
    ),
    ImplementationConfig(
        name='gpt_image_common_site2_v1',
        display_name='gpt site2',
        driver_class='GptImageCommonSite2V1Driver',
        default_computing_power=2,
        enabled=True,
        description='site 2',
        sort_order=3220.0,
        sync_mode=True,
        site_number=2,
        required_config_keys=['api_aggregator.site_2.api_key', 'api_aggregator.site_2.base_url']
    ),
    ImplementationConfig(
        name='gpt_image_common_site3_v1',
        display_name='gpt site3',
        driver_class='GptImageCommonSite3V1Driver',
        default_computing_power=2,
        enabled=True,
        description='site3',
        sort_order=3230.0,
        sync_mode=True,
        site_number=3,
        required_config_keys=['api_aggregator.site_3.api_key', 'api_aggregator.site_3.base_url']
    ),
    ImplementationConfig(
        name='gpt_image_common_site4_v1',
        display_name='gpt site4',
        driver_class='GptImageCommonSite4V1Driver',
        default_computing_power=2,
        enabled=True,
        description='site 4',
        sort_order=3240.0,
        sync_mode=True,
        site_number=4,
        required_config_keys=['api_aggregator.site_4.api_key', 'api_aggregator.site_4.base_url']
    ),
    ImplementationConfig(
        name='gpt_image_common_site5_v1',
        display_name='gpt site5',
        driver_class='GptImageCommonSite5V1Driver',
        default_computing_power=2,
        enabled=True,
        description='site 5',
        sort_order=3250.0,
        sync_mode=True,
        site_number=5,
        required_config_keys=['api_aggregator.site_5.api_key', 'api_aggregator.site_5.base_url']
    ),

    # ==================== API 聚合器站点 ====================
    ImplementationConfig(
        name='gemini_image_preview_site0_v1',
        display_name='ZJTapi',
        driver_class='GeminiImagePreviewSite0V1Driver',
        default_computing_power=2,
        enabled=True,
        description='ZJT官方',
        sort_order=10500.0,
        site_number=0,
        sync_mode=True,  # 同步模式
        required_config_keys=['api_aggregator.site_0.api_key']
    ),
    ImplementationConfig(
        name='gemini_image_preview_site1_v1',
        display_name='Site 1',
        driver_class='GeminiImagePreviewSite1V1Driver',
        default_computing_power=2,
        enabled=True,
        description='API聚合器站点 1',
        sort_order=11000.0,
        site_number=1,
        sync_mode=True,  # 同步模式
        required_config_keys=['api_aggregator.site_1.api_key', 'api_aggregator.site_1.base_url']
    ),
    ImplementationConfig(
        name='gemini_image_preview_site2_v1',
        display_name='Site 2',
        driver_class='GeminiImagePreviewSite2V1Driver',
        default_computing_power=2,
        enabled=True,
        description='API聚合器站点 2',
        sort_order=12000.0,
        site_number=2,
        sync_mode=True,  # 同步模式
        required_config_keys=['api_aggregator.site_2.api_key', 'api_aggregator.site_2.base_url']
    ),
    ImplementationConfig(
        name='gemini_image_preview_site3_v1',
        display_name='Site 3',
        driver_class='GeminiImagePreviewSite3V1Driver',
        default_computing_power=2,
        enabled=True,
        description='API聚合器站点 3',
        sort_order=13000.0,
        site_number=3,
        sync_mode=True,  # 同步模式
        required_config_keys=['api_aggregator.site_3.api_key', 'api_aggregator.site_3.base_url']
    ),
    ImplementationConfig(
        name='gemini_image_preview_site4_v1',
        display_name='Site 4',
        driver_class='GeminiImagePreviewSite4V1Driver',
        default_computing_power=2,
        enabled=True,
        description='API聚合器站点 4',
        sort_order=14000.0,
        site_number=4,
        sync_mode=True,  # 同步模式
        required_config_keys=['api_aggregator.site_4.api_key', 'api_aggregator.site_4.base_url']
    ),
    ImplementationConfig(
        name='gemini_image_preview_site5_v1',
        display_name='Site 5',
        driver_class='GeminiImagePreviewSite5V1Driver',
        default_computing_power=2,
        enabled=True,
        description='API聚合器站点 5',
        sort_order=15000.0,
        site_number=5,
        sync_mode=False,  # 同步模式
        required_config_keys=['api_aggregator.site_5.api_key', 'api_aggregator.site_5.base_url']
    ),
    ImplementationConfig(
        name='veo3_duomi_v1',
        display_name='多米',
        driver_class='Veo3DuomiV1Driver',
        default_computing_power=6,
        enabled=True,
        description='多米平台 VEO3 接口',
        sort_order=4000.0,
        required_config_keys=['duomi.token']
    ),
    ImplementationConfig(
        name='veo3_common_site0_v1',
        display_name='ZJTapi',
        driver_class='Veo3CommonSite0V1Driver',
        default_computing_power=6,
        enabled=True,
        description='ZJTapi',
        sort_order=3900.0,
        site_number=0,
        required_config_keys=['api_aggregator.site_0.api_key']
    ),
    ImplementationConfig(
        name='veo3_common_site1_v1',
        display_name='聚合站点1',
        driver_class='Veo3CommonSite1V1Driver',
        default_computing_power=6,
        enabled=True,
        description='聚合站点1',
        sort_order=4510.0,
        site_number=1,
        required_config_keys=['api_aggregator.site_1.api_key', 'api_aggregator.site_1.base_url']
    ),
    ImplementationConfig(
        name='veo3_common_site2_v1',
        display_name='聚合站点2',
        driver_class='Veo3CommonSite2V1Driver',
        default_computing_power=6,
        enabled=True,
        description='聚合站点2',
        sort_order=4520.0,
        site_number=2,
        required_config_keys=['api_aggregator.site_2.api_key', 'api_aggregator.site_2.base_url']
    ),
    ImplementationConfig(
        name='veo3_common_site3_v1',
        display_name='聚合站点3',
        driver_class='Veo3CommonSite3V1Driver',
        default_computing_power=6,
        enabled=True,
        description='聚合站点3',
        sort_order=4530.0,
        site_number=3,
        required_config_keys=['api_aggregator.site_3.api_key', 'api_aggregator.site_3.base_url']
    ),
    ImplementationConfig(
        name='veo3_common_site4_v1',
        display_name='聚合站点4',
        driver_class='Veo3CommonSite4V1Driver',
        default_computing_power=6,
        enabled=True,
        description='聚合站点4',
        sort_order=4540.0,
        site_number=4,
        required_config_keys=['api_aggregator.site_4.api_key', 'api_aggregator.site_4.base_url']
    ),
    ImplementationConfig(
        name='veo3_common_site5_v1',
        display_name='聚合站点5',
        driver_class='Veo3CommonSite5V1Driver',
        default_computing_power=6,
        enabled=True,
        description='聚合站点5',
        sort_order=4550.0,
        site_number=5,
        required_config_keys=['api_aggregator.site_5.api_key', 'api_aggregator.site_5.base_url']
    ),
    ImplementationConfig(
        name='grok_duomi_v1',
        display_name='多米',
        driver_class='GrokDuomiV1Driver',
        default_computing_power=8,
        enabled=True,
        description='多米平台 Grok 接口',
        sort_order=4500.0,
        required_config_keys=['duomi.token']
    ),
    ImplementationConfig(
        name='grok_common_site0_v1',
        display_name='ZJTapi',
        driver_class='GrokCommonSite0V1Driver',
        default_computing_power=8,
        enabled=True,
        description='ZJTapi',
        sort_order=4450.0,
        required_config_keys=['api_aggregator.site_0.api_key']
    ),
    ImplementationConfig(
        name='grok_common_site1_v1',
        display_name='Grok 站点1',
        driver_class='GrokCommonSite1V1Driver',
        default_computing_power=8,
        enabled=True,
        description='Grok 站点1',
        sort_order=4560.0,
        required_config_keys=['api_aggregator.site_1.api_key', 'api_aggregator.site_1.base_url']
    ),
    ImplementationConfig(
        name='grok_common_site2_v1',
        display_name='Grok 站点2',
        driver_class='GrokCommonSite2V1Driver',
        default_computing_power=8,
        enabled=True,
        description='Grok 站点2',
        sort_order=4570.0,
        required_config_keys=['api_aggregator.site_2.api_key', 'api_aggregator.site_2.base_url']
    ),
    ImplementationConfig(
        name='grok_common_site3_v1',
        display_name='Grok 站点3',
        driver_class='GrokCommonSite3V1Driver',
        default_computing_power=8,
        enabled=True,
        description='Grok 站点3',
        sort_order=4580.0,
        required_config_keys=['api_aggregator.site_3.api_key', 'api_aggregator.site_3.base_url']
    ),
    ImplementationConfig(
        name='grok_common_site4_v1',
        display_name='Grok 站点4',
        driver_class='GrokCommonSite4V1Driver',
        default_computing_power=8,
        enabled=True,
        description='Grok 站点4',
        sort_order=4590.0,
        required_config_keys=['api_aggregator.site_4.api_key', 'api_aggregator.site_4.base_url']
    ),
    ImplementationConfig(
        name='grok_common_site5_v1',
        display_name='Grok 站点5',
        driver_class='GrokCommonSite5V1Driver',
        default_computing_power=8,
        enabled=True,
        description='Grok 站点5',
        sort_order=4600.0,
        required_config_keys=['api_aggregator.site_5.api_key', 'api_aggregator.site_5.base_url']
    ),

    # ==================== RunningHub 供应商 ====================
    ImplementationConfig(
        name='ltx2_runninghub_v1',
        display_name='RunningHub',
        driver_class='Ltx2RunninghubV1Driver',
        default_computing_power=6,
        enabled=True,
        description='RunningHub LTX2.0 接口',
        sort_order=5000.0,
        required_config_keys=['runninghub.api_key']
    ),
    ImplementationConfig(
        name='wan22_runninghub_v1',
        display_name='RunningHub',
        driver_class='Wan22RunninghubV1Driver',
        default_computing_power={5: 8, 10: 18},
        enabled=True,
        description='RunningHub Wan2.2 接口',
        sort_order=6000.0,
        required_config_keys=['runninghub.api_key']
    ),
    ImplementationConfig(
        name='qwen_multi_angle_runninghub_v1',
        display_name='RunningHub',
        driver_class='QwenMultiAngleRunninghubV1Driver',
        default_computing_power=4,
        enabled=True,
        description='RunningHub Qwen 多角度图片编辑接口',
        sort_order=7500.0,
        required_config_keys=['runninghub.api_key']
    ),
    ImplementationConfig(
        name='digital_human_runninghub_v1',
        display_name='RunningHub',
        driver_class='DigitalHumanRunninghubV1Driver',
        default_computing_power=12,
        enabled=True,
        description='RunningHub 数字人接口',
        sort_order=7000.0,
        required_config_keys=['runninghub.api_key']
    ),

    # ==================== Vidu 供应商 ====================
    ImplementationConfig(
        name='vidu_default',
        display_name='Vidu',
        driver_class='ViduDefaultDriver',
        default_computing_power={5: 16, 8: 22},
        enabled=True,
        description='Vidu 图生视频接口',
        sort_order=8000.0,
        required_config_keys=['vidu.token']
    ),
    ImplementationConfig(
        name='vidu_q2',
        display_name='Vidu Q2',
        driver_class='ViduQ2Driver',
        default_computing_power={5: 45, 8: 60},
        enabled=True,
        description='Vidu Q2 图生视频接口',
        sort_order=9000.0,
        required_config_keys=['vidu.token']
    ),

    # ==================== 火山引擎供应商 ====================
    ImplementationConfig(
        name='seedream5_volcengine_v1',
        display_name='火山引擎',
        driver_class='Seedream5VolcengineV1Driver',
        default_computing_power=6,
        enabled=True,
        description='火山引擎 Seedream 5.0 文生图接口',
        sort_order=10000.0,
        sync_mode=True,  # 同步模式
        required_config_keys=['volcengine.api_key']
    ),
    ImplementationConfig(
        name='seedance_1_5_pro_volcengine_v1',
        display_name='火山引擎',
        driver_class='Seedance15ProVolcengineV1Driver',
        default_computing_power={5: 46, 6: 56, 7: 66, 8: 76, 9: 85, 10: 94, 11: 103, 12: 112},
        enabled=True,
        description='火山引擎 Seedance 1.5 Pro 图生视频接口',
        sort_order=10500.0,
        required_config_keys=['volcengine.api_key']
    ),
    ImplementationConfig(
        name='seedance_2_0_fast_volcengine_v1',
        display_name='火山引擎',
        driver_class='Seedance20FastVolcengineV1Driver',
        default_computing_power={5: 105, 6: 126, 7: 147, 8: 168, 9: 189, 10: 210, 11: 231, 12: 252, 13: 273, 14: 294, 15: 315},
        enabled=True,
        description='火山引擎 Seedance 2.0 Fast 图生视频接口',
        sort_order=10600.0,
        required_config_keys=['volcengine.api_key']
    ),
    ImplementationConfig(
        name='seedance_2_0_volcengine_v1',
        display_name='火山引擎',
        driver_class='Seedance20VolcengineV1Driver',
        default_computing_power={5: 250, 6: 300, 7: 350, 8: 400, 9: 450, 10: 500, 11: 550, 12: 600, 13: 650, 14: 700, 15: 750},
        enabled=True,
        description='火山引擎 Seedance 2.0 图生视频接口',
        sort_order=10700.0,
        required_config_keys=['volcengine.api_key']
    ),

    # ==================== 本地处理 ====================
    ImplementationConfig(
        name='local_enhance',
        display_name='本地处理',
        driver_class='LocalEnhanceDriver',
        default_computing_power=1,
        enabled=True,
        description='本地图片增强'
    ),
    ImplementationConfig(
        name='local_video_enhance',
        display_name='本地处理',
        driver_class='LocalVideoEnhanceDriver',
        default_computing_power=10,
        enabled=True,
        description='本地视频增强'
    ),
    ImplementationConfig(
        name='character_card',
        display_name='本地处理',
        driver_class='CharacterCardDriver',
        default_computing_power=20,
        enabled=True,
        description='角色卡生成'
    ),
    ImplementationConfig(
        name='audio_generate',
        display_name='本地处理',
        driver_class='AudioGenerateDriver',
        default_computing_power=5,
        enabled=True,
        description='AI音频生成'
    ),
]


def init_unified_config():
    """
    初始化统一配置系统
    在应用启动时调用
    """
    if not UnifiedConfigRegistry._configs:
        UnifiedConfigRegistry.register_all(ALL_TASK_CONFIGS)
        UnifiedConfigRegistry.register_all_implementations(ALL_IMPLEMENTATIONS)


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


# 模块加载时自动初始化（基础配置）
init_unified_config()
# 注意：init_api_aggregator_implementations() 延迟到 register_all_drivers() 中调用
# 以避免循环导入问题（因为 get_dynamic_config_value -> model.system_config -> config.constant -> config.unified_config）
