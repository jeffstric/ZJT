#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
常量配置模块

⚠️ 注意：任务类型相关配置已迁移到 unified_config.py
新增或修改任务类型请编辑 config/unified_config.py 中的 ALL_TASK_CONFIGS

本文件保留向后兼容的常量别名，逐步废弃中。
"""

from typing import Union, Dict, List

# 从统一配置系统导入（新系统）
from config.unified_config import (
    TaskTypeId,
    TaskCategory,
    TaskProvider,
    DriverKey,
    DriverImplementation,
    UnifiedConfigRegistry,
    UnifiedTaskConfig,
)


# ============ 向后兼容：使用 UnifiedConfigRegistry 提供旧 API ============

class TaskTypeRegistry:
    """
    向后兼容的任务类型注册表
    
    ⚠️ 已废弃：请使用 UnifiedConfigRegistry
    """
    
    @classmethod
    def get(cls, task_type: int):
        """获取指定任务类型的配置"""
        return UnifiedConfigRegistry.get_by_id(task_type)
    
    @classmethod
    def get_all(cls) -> Dict[int, UnifiedTaskConfig]:
        """获取所有任务类型配置"""
        return {c.id: c for c in UnifiedConfigRegistry.get_all()}
    
    @classmethod
    def get_by_category(cls, category: str) -> List[int]:
        """获取指定分类的所有任务类型ID"""
        return UnifiedConfigRegistry.get_ids_by_category(category)
    
    @classmethod
    def get_by_provider(cls, provider: str) -> List[int]:
        """获取指定供应商的所有任务类型ID"""
        return UnifiedConfigRegistry.get_ids_by_provider(provider)
    
    @classmethod
    def get_name_map(cls) -> Dict[int, str]:
        """获取任务类型ID到名称的映射"""
        return UnifiedConfigRegistry.get_name_map()
    
    @classmethod
    def get_driver_mapping(cls) -> Dict[int, str]:
        """获取任务类型ID到业务驱动名称的映射"""
        return UnifiedConfigRegistry.get_driver_mapping()
    
    @classmethod
    def get_computing_power_map(cls) -> Dict[int, Union[int, Dict[int, int]]]:
        """获取任务类型ID到算力消耗的映射"""
        return UnifiedConfigRegistry.get_computing_power_map()


class Action:
    """资源操作类型常量"""
    VIEW = "view"      # 查看权限
    EDIT = "edit"      # 编辑权限
    DELETE = "delete"  # 删除权限


class Edition:
    """版本模式管理类"""
    
    # 版本模式常量
    COMMUNITY = "community"
    ENTERPRISE = "enterprise"
    
    @staticmethod
    def get_mode() -> str:
        """获取当前版本模式"""
        from config.config_util import get_config_value
        return get_config_value("edition", "mode", default=Edition.COMMUNITY)
    
    @staticmethod
    def is_community() -> bool:
        """判断是否为开源/社区版"""
        return Edition.get_mode() == Edition.COMMUNITY
    
    @staticmethod
    def is_enterprise() -> bool:
        """判断是否为商业版"""
        return not Edition.is_community()
    
    @staticmethod
    def get_label() -> str:
        """获取版本模式标签"""
        mode = Edition.get_mode()
        return "社区版" if mode == Edition.COMMUNITY else "商业版"


class TaskType:
    """任务类型常量"""
    GENERATE_VIDEO = 'generate_video'
    GENERATE_AUDIO = 'generate_audio'


# 向后兼容别名
TASK_TYPE_GENERATE_VIDEO = TaskType.GENERATE_VIDEO
TASK_TYPE_GENERATE_AUDIO = TaskType.GENERATE_AUDIO

# ============ 从 TaskTypeRegistry 动态生成的向后兼容常量 ============
# 
# 新代码请直接使用 TaskTypeRegistry 的方法，参见文件末尾的替代方案说明
#

# 算力配置（已废弃，请使用 TaskTypeRegistry.get_computing_power_map()）
TASK_COMPUTING_POWER = TaskTypeRegistry.get_computing_power_map()

# 视频驱动映射配置（已废弃，请使用 TaskTypeRegistry.get_driver_mapping()）
# 任务类型 -> 业务驱动名称
VIDEO_DRIVER_MAPPING = TaskTypeRegistry.get_driver_mapping()

# 业务驱动名称到具体实现驱动的映射
# 修改这里可以切换不同的供应商或驱动版本
# 格式：业务驱动名称 -> 实现驱动类名
DRIVER_IMPLEMENTATION_MAPPING = {
    # Sora2 相关驱动
    DriverKey.SORA2_TEXT_TO_VIDEO: DriverImplementation.SORA2_DUOMI_V1,      # 使用多米供应商的 Sora2 v1 版本
    DriverKey.SORA2_IMAGE_TO_VIDEO: DriverImplementation.SORA2_DUOMI_V1,     # 使用多米供应商的 Sora2 v1 版本
    
    # Kling 相关驱动
    DriverKey.KLING_IMAGE_TO_VIDEO: DriverImplementation.KLING_DUOMI_V1,     # 使用多米供应商的 Kling v1 版本
    
    # Gemini 相关驱动
    DriverKey.GEMINI_IMAGE_EDIT: DriverImplementation.GEMINI_DUOMI_V1,       # 使用多米供应商的 Gemini v1 版本（标准版）
    DriverKey.GEMINI_IMAGE_EDIT_PRO: DriverImplementation.GEMINI_DUOMI_V1,   # 使用多米供应商的 Gemini v1 版本（Pro模型）
    
    # VEO3 相关驱动
    DriverKey.VEO3_IMAGE_TO_VIDEO: DriverImplementation.VEO3_DUOMI_V1,       # 使用多米供应商的 VEO3 v1 版本
    
    # RunningHub 相关驱动
    DriverKey.LTX2_IMAGE_TO_VIDEO: DriverImplementation.LTX2_RUNNINGHUB_V1,  # 使用 RunningHub 的 LTX2 v1 版本
    DriverKey.WAN22_IMAGE_TO_VIDEO: DriverImplementation.WAN22_RUNNINGHUB_V1, # 使用 RunningHub 的 Wan22 v1 版本
    DriverKey.DIGITAL_HUMAN: DriverImplementation.DIGITAL_HUMAN_RUNNINGHUB_V1, # 使用 RunningHub 的数字人 v1 版本
    
    # Vidu 相关驱动
    DriverKey.VIDU_IMAGE_TO_VIDEO: DriverImplementation.VIDU_DEFAULT,         # 使用 Vidu 官方 API
    
    # Seedream 相关驱动
    DriverKey.SEEDREAM_TEXT_TO_IMAGE: DriverImplementation.SEEDREAM5_VOLCENGINE_V1,  # 使用火山引擎 Seedream 5.0 v1 版本
}

# 视频模型时长选项配置
# 注意：时长选项从算力配置中自动获取
def _build_duration_options():
    """构建视频模型时长选项"""
    power = TASK_COMPUTING_POWER
    return {
        'ltx2': [5, 8, 10],  # LTX2.0 固定算力，支持5/8/10秒
        'wan22': list(power[11].keys()) if isinstance(power.get(11), dict) else [5, 10],
        'kling': list(power[12].keys()) if isinstance(power.get(12), dict) else [5, 10],
        'vidu': list(power[14].keys()) if isinstance(power.get(14), dict) else [5, 8],
        'sora2': [15, 10],  # Sora2 固定算力
        'veo3': [8],  # VEO3 固定算力
    }

VIDEO_MODEL_DURATION_OPTIONS = _build_duration_options()

# ============ 向后兼容常量（已废弃，请使用新 API） ============
# 
# 以下常量保留仅为向后兼容，新代码请使用 TaskTypeRegistry 的方法：
#
# 替代方案：
#   IMAGE_TO_VIDEO_TYPES  -> TaskTypeRegistry.get_by_category(TaskCategory.IMAGE_TO_VIDEO)
#   IMAGE_EDIT_TYPES      -> TaskTypeRegistry.get_by_category(TaskCategory.IMAGE_EDIT)
#   RUNNINGHUB_TASK_TYPES -> TaskTypeRegistry.get_by_provider(TaskProvider.RUNNINGHUB)
#   TASK_TYPE_NAME_MAP    -> TaskTypeRegistry.get_name_map()
#   TASK_COMPUTING_POWER  -> TaskTypeRegistry.get_computing_power_map()
#   VIDEO_DRIVER_MAPPING  -> TaskTypeRegistry.get_driver_mapping()
#
# 查询单个任务类型：
#   TaskTypeRegistry.get(task_type_id)  -> TaskTypeConfig 对象
#

# 图生视频任务类型列表（已废弃）
IMAGE_TO_VIDEO_TYPES = TaskTypeRegistry.get_by_category(TaskCategory.IMAGE_TO_VIDEO)

# 图片编辑任务类型列表（已废弃）
IMAGE_EDIT_TYPES = TaskTypeRegistry.get_by_category(TaskCategory.IMAGE_EDIT)

# RunningHub 平台任务类型列表（已废弃）
RUNNINGHUB_TASK_TYPES = TaskTypeRegistry.get_by_provider(TaskProvider.RUNNINGHUB)

# 任务类型名称映射（已废弃）
TASK_TYPE_NAME_MAP = TaskTypeRegistry.get_name_map()

class AIToolStatus:
    """AI工具状态常量"""
    PENDING = 0       # 未处理
    PROCESSING = 1    # 正在处理
    FAILED = -1       # 处理失败
    COMPLETED = 2     # 处理完成


class TaskStatus:
    """任务状态常量"""
    QUEUED = 0        # 队列中
    PROCESSING = 1    # 处理中
    COMPLETED = 2     # 处理完成
    FAILED = -1       # 处理失败


class AIAudioStatus:
    """AI音频状态常量"""
    PENDING = 0       # 未处理
    PROCESSING = 1    # 处理中
    FAILED = -1       # 处理失败
    COMPLETED = 2     # 处理完成


# 向后兼容别名 - AI Tools 状态
AI_TOOL_STATUS_PENDING = AIToolStatus.PENDING
AI_TOOL_STATUS_PROCESSING = AIToolStatus.PROCESSING
AI_TOOL_STATUS_FAILED = AIToolStatus.FAILED
AI_TOOL_STATUS_COMPLETED = AIToolStatus.COMPLETED

# 向后兼容别名 - Tasks 状态
TASK_STATUS_QUEUED = TaskStatus.QUEUED
TASK_STATUS_PROCESSING = TaskStatus.PROCESSING
TASK_STATUS_COMPLETED = TaskStatus.COMPLETED
TASK_STATUS_FAILED = TaskStatus.FAILED

# 向后兼容别名 - AI Audio 状态
AI_AUDIO_STATUS_PENDING = AIAudioStatus.PENDING
AI_AUDIO_STATUS_PROCESSING = AIAudioStatus.PROCESSING
AI_AUDIO_STATUS_FAILED = AIAudioStatus.FAILED
AI_AUDIO_STATUS_COMPLETED = AIAudioStatus.COMPLETED

class GridConfig:
    """宫格拆分配置常量"""
    SIZE_2X2 = 4                          # 2x2 宫格（标准版）
    SIZE_3X3 = 9                          # 3x3 宫格（加强版）
    VALID_SIZES = (4, 9)                  # 允许的宫格大小
    DEFAULT_SIZE_BY_TYPE = {1: 4, 7: 9}   # AI工具类型 → 默认宫格大小
    LOCK_TIMEOUT_SECONDS = 120            # 文件锁超时（秒）
    IMAGE_DOWNLOAD_TIMEOUT = 60.0         # 下载原图超时（秒）


# 向后兼容别名 - 宫格拆分
GRID_SIZE_2X2 = GridConfig.SIZE_2X2
GRID_SIZE_3X3 = GridConfig.SIZE_3X3
GRID_VALID_SIZES = GridConfig.VALID_SIZES
GRID_DEFAULT_SIZE_BY_TYPE = GridConfig.DEFAULT_SIZE_BY_TYPE
GRID_LOCK_TIMEOUT_SECONDS = GridConfig.LOCK_TIMEOUT_SECONDS
GRID_IMAGE_DOWNLOAD_TIMEOUT = GridConfig.IMAGE_DOWNLOAD_TIMEOUT

class FilePathConstants:
    """文件路径相关常量 - 兼容Windows的跨平台路径配置"""
    
    # 路径常量（相对路径）
    _TTS_AUDIO_SUBDIR = "files/tmp/tts/tmp_ref_audio"
    _JIANYING_EXPORT_SUBDIR = "files/tmp/jianying_export"
    _PIC_TMP_SUBDIR = "files/tmp/pic"
    _SCRIPT_WRITER_USER_DATA_SUBDIR = "files/script_writer"  # 剧本创作系统用户数据根目录

    @staticmethod
    def get_pic_tmp_dir(app_dir: str) -> str:
        """
        获取图片临时目录的完整路径（自动按年月日分组，自动创建目录）

        Args:
            app_dir: 应用根目录路径

        Returns:
            完整的图片临时目录路径，格式：files/tmp/pic/2026-02-26/
        """
        import os
        from datetime import datetime
        date_folder = datetime.now().strftime('%Y-%m-%d')
        path = os.path.join(app_dir, FilePathConstants._PIC_TMP_SUBDIR, date_folder)
        os.makedirs(path, exist_ok=True)
        return path
    
    @staticmethod
    def get_tts_audio_dir(app_dir: str) -> str:
        """
        获取TTS音频目录的完整路径（自动按当前日期分组，自动创建目录）
        
        Args:
            app_dir: 应用根目录路径
            
        Returns:
            完整的TTS音频目录路径，格式：files/tmp/tts/tmp_ref_audio/2026-02-24/
        """
        import os
        from datetime import datetime
        date_folder = datetime.now().strftime('%Y-%m-%d')
        path = os.path.join(app_dir, FilePathConstants._TTS_AUDIO_SUBDIR, date_folder)
        os.makedirs(path, exist_ok=True)
        return path
    
    @staticmethod
    def get_jianying_export_dir(app_dir: str, draft_name: str) -> str:
        """
        获取剪映导出目录的完整路径（自动按当前日期分组，自动创建目录）
        
        Args:
            app_dir: 应用根目录路径
            draft_name: 草稿名称
            
        Returns:
            完整的剪映导出目录路径，格式：files/tmp/jianying_export/2026-02-24/草稿名/
        """
        import os
        from datetime import datetime
        date_folder = datetime.now().strftime('%Y-%m-%d')
        path = os.path.join(app_dir, FilePathConstants._JIANYING_EXPORT_SUBDIR, date_folder, draft_name)
        os.makedirs(path, exist_ok=True)
        return path

RECHARGE_PACKAGES = [
    {
        "package_id": 1,
        "computing_power": 100,
        "price": 0.1,
        "description": "首充福利"
    },
    {
        "package_id": 2,
        "computing_power": 200,
        "price": 9.9,
        "description": "标准套餐"
    },
    {
        "package_id": 3,
        "computing_power": 1250,
        "price": 49.9,
        "description": "进阶套餐"
    }
]


# 系统配置相关常量
class SystemConfigConstants:
    """系统配置相关常量"""
    CONFIG_KEY_MAX_LENGTH = 256  # 配置键最大长度


# 向后兼容别名
CONFIG_KEY_MAX_LENGTH = SystemConfigConstants.CONFIG_KEY_MAX_LENGTH


# Gemini API URL 格式常量
GEMINI_URL_FORMATS = {
    "proxy": "/gemini/v1/models/{model}:generateContent",      # 第三方代理格式（如 jiekou.ai）
    "official": "/v1beta/models/{model}:generateContent"       # Google 官方格式
}


# 外部链接常量
class ExternalLinks:
    """外部链接常量"""
    USER_MANUAL_URL = 'https://bq3mlz1jiae.feishu.cn/wiki/W1h2wCK3mi1CgDk36LEcVqggnLe'  # 使用手册