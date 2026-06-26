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
    """资源操作类型"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'VIEW': '查看权限',
        'EDIT': '编辑权限',
        'DELETE': '删除权限',
    }
    VIEW = "view"
    EDIT = "edit"
    DELETE = "delete"


class Edition:
    """版本模式"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'COMMUNITY': '社区版',
        'ENTERPRISE': '企业版',
    }

    # 版本模式常量
    COMMUNITY = "community"
    ENTERPRISE = "enterprise"

    _enterprise_available = None  # 缓存：enterprise/ 目录是否存在

    @staticmethod
    def _is_enterprise_available() -> bool:
        """检查 enterprise/ 代码目录是否实际存在（结果缓存）"""
        if Edition._enterprise_available is None:
            import os
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            Edition._enterprise_available = os.path.isdir(
                os.path.join(project_root, "enterprise")
            )
        return Edition._enterprise_available

    @staticmethod
    def get_mode() -> str:
        """获取当前版本模式

        企业版需要同时满足：
        1. 配置文件 edition.mode = enterprise
        2. enterprise/ 目录实际存在
        """
        from config.config_util import get_config_value
        mode = get_config_value("edition", "mode", default=Edition.COMMUNITY)
        if mode == Edition.ENTERPRISE and not Edition._is_enterprise_available():
            return Edition.COMMUNITY
        return mode

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

    @staticmethod
    def is_space_isolated() -> bool:
        """
        判断是否为独立空间模式（用户数据隔离）

        - 社区版：始终为共享空间（返回 False）
        - 商业版：默认为独立空间（返回 True），
          但可通过 edition.shared_space=true 配置为共享空间（返回 False）
        """
        if Edition.is_community():
            return False
        from config.config_util import get_dynamic_config_value
        shared = get_dynamic_config_value('edition', 'shared_space', default=False)
        return not shared


class TaskType:
    """任务类型"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'GENERATE_VIDEO': '生成视频',
        'GENERATE_AUDIO': '生成音频',
    }
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
    DriverKey.KLING_IMAGE_TO_VIDEO: [
        DriverImplementation.KLING_DUOMI_V1,          # 使用多米供应商的 Kling v1 版本
        DriverImplementation.KLING_COMMON_SITE0_V1,   # 智剧通API Kling
        DriverImplementation.KLING_COMMON_SITE1_V1,   # 通用聚合站点 1
        DriverImplementation.KLING_COMMON_SITE2_V1,   # 通用聚合站点 2
        DriverImplementation.KLING_COMMON_SITE3_V1,   # 通用聚合站点 3
        DriverImplementation.KLING_COMMON_SITE4_V1,   # 通用聚合站点 4
        DriverImplementation.KLING_COMMON_SITE5_V1,   # 通用聚合站点 5
    ],
    
    # Gemini 相关驱动
    DriverKey.GEMINI_IMAGE_EDIT: [
        DriverImplementation.GEMINI_DUOMI_V1,       # 使用多米供应商的 Gemini v1 版本（标准版）
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE0_V1,  # 智剧通API官方站点
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE1_V1,  # API聚合器站点 1
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE2_V1,  # API聚合器站点 2
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE3_V1,  # API聚合器站点 3
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE4_V1,  # API聚合器站点 4
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE5_V1,  # API聚合器站点 5
    ],
    DriverKey.GEMINI_IMAGE_EDIT_PRO: [
        DriverImplementation.GEMINI_DUOMI_V1,       # 使用多米供应商的 Gemini v1 版本（Pro模型）
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE0_V1,  # 智剧通API官方站点
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE1_V1,  # API聚合器站点 1
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE2_V1,  # API聚合器站点 2
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE3_V1,  # API聚合器站点 3
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE4_V1,  # API聚合器站点 4
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE5_V1,  # API聚合器站点 5
    ],
    DriverKey.GEMINI_3_1_FLASH_IMAGE_EDIT: [
        DriverImplementation.GEMINI_DUOMI_V1,       # 使用多米供应商的 Gemini 3.1 Flash 版本
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE0_V1,  # 智剧通API官方站点
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE1_V1,  # API聚合器站点 1
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE2_V1,  # API聚合器站点 2
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE3_V1,  # API聚合器站点 3
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE4_V1,  # API聚合器站点 4
        DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE5_V1,  # API聚合器站点 5
    ],

    # VEO3 相关驱动
    DriverKey.VEO3_IMAGE_TO_VIDEO: [
        DriverImplementation.VEO3_DUOMI_V1,       # 使用多米供应商的 VEO3 v1 版本
        DriverImplementation.VEO3_COMMON_SITE0_V1,  # 智剧通API VEO3
        DriverImplementation.VEO3_COMMON_SITE1_V1,  # 通用聚合站点 1
        DriverImplementation.VEO3_COMMON_SITE2_V1,  # 通用聚合站点 2
        DriverImplementation.VEO3_COMMON_SITE3_V1,  # 通用聚合站点 3
        DriverImplementation.VEO3_COMMON_SITE4_V1,  # 通用聚合站点 4
        DriverImplementation.VEO3_COMMON_SITE5_V1,  # 通用聚合站点 5
    ],

    # RunningHub 相关驱动
    DriverKey.LTX2_IMAGE_TO_VIDEO: DriverImplementation.LTX2_RUNNINGHUB_V1,  # 使用 RunningHub 的 LTX2 v1 版本
    DriverKey.LTX2_3_IMAGE_TO_VIDEO: DriverImplementation.LTX2_3_RUNNINGHUB_V1,  # 使用 RunningHub 的 LTX2.3 v1 版本
    DriverKey.WAN22_IMAGE_TO_VIDEO: DriverImplementation.WAN22_RUNNINGHUB_V1, # 使用 RunningHub 的 Wan22 v1 版本
    DriverKey.DIGITAL_HUMAN: DriverImplementation.DIGITAL_HUMAN_RUNNINGHUB_V1,  # 使用 RunningHub 的数字人 v1 版本
    DriverKey.DIGITAL_HUMAN_LTX2_3_VOICE: DriverImplementation.LTX2_3_WITH_VOICE_RUNNINGHUB_V1,  # 使用 RunningHub 的 LTX2.3 With Voice 版本
    
    # Vidu 相关驱动
    DriverKey.VIDU_IMAGE_TO_VIDEO: DriverImplementation.VIDU_DEFAULT,         # 使用 Vidu 官方 API
    
    # Seedream 相关驱动
    DriverKey.SEEDREAM_TEXT_TO_IMAGE: [
        DriverImplementation.SEEDREAM5_VOLCENGINE_V1,           # 火山引擎国内版
        DriverImplementation.SEEDREAM5_VOLCENGINE_OVERSEA_V1,   # 火山引擎海外版
    ],

    # Seedance 相关驱动
    DriverKey.SEEDANCE_1_5_PRO_IMAGE_TO_VIDEO: DriverImplementation.SEEDANCE_1_5_PRO_VOLCENGINE_V1,  # 使用火山引擎 Seedance 1.5 Pro
    DriverKey.SEEDANCE_2_0_FAST_IMAGE_TO_VIDEO: [
        DriverImplementation.SEEDANCE_2_0_FAST_VOLCENGINE_V1,           # 火山引擎国内版
        DriverImplementation.SEEDANCE_2_0_FAST_VOLCENGINE_OVERSEA_V1,   # 火山引擎海外版
    ],
    DriverKey.SEEDANCE_2_0_IMAGE_TO_VIDEO: [
        DriverImplementation.SEEDANCE_2_0_VOLCENGINE_V1,           # 火山引擎国内版
        DriverImplementation.SEEDANCE_2_0_VOLCENGINE_OVERSEA_V1,   # 火山引擎海外版
    ],
    DriverKey.SEEDANCE_2_0_MINI_IMAGE_TO_VIDEO: [
        DriverImplementation.SEEDANCE_2_0_MINI_VOLCENGINE_V1,           # 火山引擎国内版
        DriverImplementation.SEEDANCE_2_0_MINI_VOLCENGINE_OVERSEA_V1,   # 火山引擎海外版
    ],

    # GPT Image 相关驱动
    DriverKey.GPT_IMAGE_2: [
        DriverImplementation.DUOMI_GPT_IMAGE_V1,  # 使用多米供应商的 GPT Image 2 版本
        DriverImplementation.GPT_IMAGE_COMMON_SITE0_V1,  # ZJT API 站点0
        DriverImplementation.GPT_IMAGE_COMMON_SITE1_V1,  # ZJT API 站点1
        DriverImplementation.GPT_IMAGE_COMMON_SITE2_V1,  # ZJT API 站点2
        DriverImplementation.GPT_IMAGE_COMMON_SITE3_V1,  # ZJT API 站点3
        DriverImplementation.GPT_IMAGE_COMMON_SITE4_V1,  # ZJT API 站点4
        DriverImplementation.GPT_IMAGE_COMMON_SITE5_V1,  # ZJT API 站点5
    ],

    # Grok 相关驱动
    DriverKey.GROK_IMAGE_TO_VIDEO: [
        DriverImplementation.GROK_DUOMI_V1,         # 使用多米供应商的 Grok 版本
        DriverImplementation.GROK_COMMON_SITE0_V1,  # ZJT API 站点0
        DriverImplementation.GROK_COMMON_SITE1_V1,  # 通用聚合站点 1
        DriverImplementation.GROK_COMMON_SITE2_V1,  # 通用聚合站点 2
        DriverImplementation.GROK_COMMON_SITE3_V1,  # 通用聚合站点 3
        DriverImplementation.GROK_COMMON_SITE4_V1,  # 通用聚合站点 4
        DriverImplementation.GROK_COMMON_SITE5_V1,  # 通用聚合站点 5
    ],

    # Happy Horse 相关驱动
    DriverKey.HAPPY_HORSE_IMAGE_TO_VIDEO: DriverImplementation.HAPPY_HORSE_DASHSCOPE_V1,
    DriverKey.HAPPY_HORSE_REFERENCE_TO_VIDEO: DriverImplementation.HAPPY_HORSE_DASHSCOPE_R2V_V1,
    DriverKey.HAPPY_HORSE_TEXT_TO_VIDEO: DriverImplementation.HAPPY_HORSE_DASHSCOPE_T2V_V1,

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
    """AI工具任务状态"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'PENDING': '未处理',
        'PROCESSING': '正在处理',
        'SYNC_QUEUED': '已提交到同步任务进程池',
        'FAILED': '处理失败',
        'COMPLETED': '处理完成',
        'WAITING_PARAM_PREPARE': '等待参数预处理',
        'WAITING_BEFORE_FINISH': '等待结束前处理',
    }
    PENDING = 0
    PROCESSING = 1
    SYNC_QUEUED = 3
    FAILED = -1
    COMPLETED = 2
    WAITING_PARAM_PREPARE = 4
    WAITING_BEFORE_FINISH = 5


class TaskStatus:
    """任务状态"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'QUEUED': '队列中',
        'PROCESSING': '处理中',
        'SYNC_QUEUED': '已提交到同步任务进程池',
        'COMPLETED': '处理完成',
        'FAILED': '处理失败',
        'WAITING_PARAM_PREPARE': '等待参数预处理',
        'WAITING_BEFORE_FINISH': '等待结束前处理',
    }
    QUEUED = 0
    PROCESSING = 1
    SYNC_QUEUED = 3
    COMPLETED = 2
    FAILED = -1
    WAITING_PARAM_PREPARE = 4
    WAITING_BEFORE_FINISH = 5


class GridImageTaskStatus:
    """宫格生图任务状态"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'QUEUED': '队列中',
        'PROCESSING': '处理中',
        'COMPLETED': '完成',
        'FAILED': '失败',
        'TIMEOUT': '超时',
        'CANCELLED': '取消',
        'DOWNLOAD_FAILED': '下载失败',
    }
    QUEUED = 0
    PROCESSING = 1
    COMPLETED = 2
    FAILED = -1
    TIMEOUT = -2
    CANCELLED = -3
    DOWNLOAD_FAILED = -4


class AIAudioStatus:
    """AI音频任务状态"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'PENDING': '未处理',
        'PROCESSING': '处理中',
        'FAILED': '处理失败',
        'COMPLETED': '处理完成',
    }
    PENDING = 0
    PROCESSING = 1
    FAILED = -1
    COMPLETED = 2



# 向后兼容别名 - AI Tools 状态
AI_TOOL_STATUS_PENDING = AIToolStatus.PENDING
AI_TOOL_STATUS_PROCESSING = AIToolStatus.PROCESSING
AI_TOOL_STATUS_FAILED = AIToolStatus.FAILED
AI_TOOL_STATUS_COMPLETED = AIToolStatus.COMPLETED
AI_TOOL_STATUS_SYNC_QUEUED = AIToolStatus.SYNC_QUEUED
AI_TOOL_STATUS_WAITING_PARAM_PREPARE = AIToolStatus.WAITING_PARAM_PREPARE
AI_TOOL_STATUS_WAITING_BEFORE_FINISH = AIToolStatus.WAITING_BEFORE_FINISH

# 向后兼容别名 - Tasks 状态
TASK_STATUS_QUEUED = TaskStatus.QUEUED
TASK_STATUS_PROCESSING = TaskStatus.PROCESSING
TASK_STATUS_COMPLETED = TaskStatus.COMPLETED
TASK_STATUS_FAILED = TaskStatus.FAILED
TASK_STATUS_SYNC_QUEUED = TaskStatus.SYNC_QUEUED
TASK_STATUS_WAITING_PARAM_PREPARE = TaskStatus.WAITING_PARAM_PREPARE
TASK_STATUS_WAITING_BEFORE_FINISH = TaskStatus.WAITING_BEFORE_FINISH

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


class UploadPathConstants:
    """上传路径相关常量"""

    # 上传根目录名
    UPLOAD_ROOT = "upload"

    # 子目录名
    TEMP_DIR = "temp"           # 临时目录（每天定时清理，由 media_cache.cleanup_temp_dir 执行）
    DRAFT_DIR = "draft"         # 草稿目录
    CHARACTER_VOICE_DIR = "character/voice"
    FACE_MASK_DIR = "face_mask"     # 人脸遮盖视频结果目录

    # 文件名前缀
    MEDIA_PREFIX = "media"      # 媒体文件前缀（图生视频上传）
    UPLOAD_PREFIX = "upload"    # 通用上传文件前缀
    CONCAT_PREFIX = "concat"    # 拼接图片文件前缀

    # Agent 模式上传数量限制
    AGENT_IMAGE_MAX_COUNT = 9   # Agent 模式最多上传图片数
    AGENT_VIDEO_MAX_COUNT = 3   # Agent 模式最多上传视频数


class MediaConstants:
    """媒体处理相关常量"""
    ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.mov', '.webm', '.avi', '.mkv'}
    VIDEO_COMPRESS_TARGET_HEIGHT = 480  # 前端压缩目标分辨率（480p）
    VIDEO_COMPRESS_THRESHOLD_MB = 10    # 超过此大小的视频触发前端压缩


class RunningHubImageFaceMaskConstants:
    """RunningHub 图片人脸遮盖工作流常量"""
    APP_ID = "2067560129192620033"
    IMAGE_NODE_ID = "3"
    IMAGE_FIELD_NAME = "image"
    FINAL_STATUSES = ("SUCCESS", "FAILED", "ERROR", "CANCELED", "CANCELLED")


# ============ 剪映（CapCut）草稿导出常量 ============
# 画布比例 → 分辨率（宽, 高）映射，未知比例回退 JIANYING_DEFAULT_RATIO
JIANYING_RATIO_RESOLUTION = {
    '9:16': (1080, 1920),  # 竖屏
    '16:9': (1920, 1080),  # 横屏
    '1:1':  (1080, 1080),  # 正方形
    '3:4':  (1080, 1440),  # 竖屏（3:4）
    '4:3':  (1440, 1080),  # 横屏（4:3）
}
JIANYING_DEFAULT_RATIO = '16:9'


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


# ==================== 邀请佣金相关（商业版） ====================
class Commission:
    """邀请佣金配置（仅商业版启用；社区版由代码层 IS_COMMUNITY_EDITION 守卫跳过）"""
    MIN_RATE = 0.0                # 最低佣金比例（0=关闭抽佣）
    MAX_RATE = 0.5                # 最高佣金比例（50%）
    STEP = 0.01                   # 比例设置步长（1%）
    MIN_WITHDRAW_AMOUNT = 10.0    # 最低提现金额（元）
    FIRST_RECHARGE_PACKAGE_ID = 1  # 首充福利套餐ID（首充不抽佣）


class CommissionLogStatus:
    """佣金明细状态"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'AVAILABLE': '可用(未提现)',
        'WITHDRAWN': '已提现',
        'REVERSED': '已冲正',
    }
    AVAILABLE = 0   # 可用（未提现）
    WITHDRAWN = 1   # 已提现
    REVERSED = 2    # 已冲正（退款预留）


class CommissionWithdrawStatus:
    """佣金提现申请状态"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'PENDING': '待审核',
        'PAID': '已打款',
        'REJECTED': '已驳回',
    }
    PENDING = 0     # 待审核
    PAID = 1        # 已打款
    REJECTED = 2    # 已驳回


# 系统配置相关常量
class SystemConfigConstants:
    """系统配置相关常量"""
    CONFIG_KEY_MAX_LENGTH = 256  # 配置键最大长度


# 向后兼容别名
CONFIG_KEY_MAX_LENGTH = SystemConfigConstants.CONFIG_KEY_MAX_LENGTH


# 营销智能体固定 world_id（营销场景不需要多世界概念）
MARKETING_WORLD_ID = "1"


# 会话历史配置相关常量
class SessionHistoryConstants:
    """会话历史配置相关常量"""
    MAX_HISTORY_MESSAGES = 100  # 最大历史消息数量（剧本创作需要较多上下文）
    MIN_HISTORY_MESSAGES = 10   # 最小保留的历史消息数量（确保上下文连续性）
    TRUNCATION_KEEP_SYSTEM = True  # 截断时保留系统提示
    SESSION_EXPIRE_HOURS_SCRIPT = 24      # 剧本智能体过期时长（小时）
    SESSION_EXPIRE_HOURS_MARKETING = 336  # 营销智能体过期时长（14天 = 336小时）


# 向后兼容别名
MAX_HISTORY_MESSAGES = SessionHistoryConstants.MAX_HISTORY_MESSAGES
MIN_HISTORY_MESSAGES = SessionHistoryConstants.MIN_HISTORY_MESSAGES


# Gemini API URL 格式常量
GEMINI_URL_FORMATS = {
    "proxy": "/gemini/v1/models/{model}:generateContent",      # 第三方代理格式（如 jiekou.ai）
    "official": "/v1beta/models/{model}:generateContent"       # Google 官方格式
}


# 外部链接常量
class ExternalLinks:
    """外部链接常量"""
    USER_MANUAL_URL = 'https://bq3mlz1jiae.feishu.cn/wiki/W1h2wCK3mi1CgDk36LEcVqggnLe'  # 使用手册


# LLM 模型和供应商常量
class LLMVendor:
    """LLM 供应商"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'JIEKOU': '接口供应商（Gemini 模型）',
        'ALIYUN': '阿里云供应商（Qwen 模型）',
        'OLLAMA': '本地运行供应商（Ollama 模型）',
        'VOLCENGINE': '火山引擎供应商（Doubao 模型）',
        'CLAUDE': 'Claude 供应商（Anthropic 模型）',
        'ZJT_API': 'ZJT API 供应商（Qwen3.5/3.6 模型）',
        'DEEPSEEK': 'DeepSeek 供应商（DeepSeek-V4 模型）',
    }
    JIEKOU = 'jiekou'
    ALIYUN = 'aliyun'
    OLLAMA = 'ollama'
    VOLCENGINE = 'volcengine'
    CLAUDE = 'claude'
    ZJT_API = 'zjt_api'
    DEEPSEEK = 'deepseek'


class LLMModel:
    """LLM 模型名称"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'GEMINI_3_FLASH': 'Gemini 3 Flash Preview',
        'GEMINI_3_5_FLASH': 'Gemini 3.5 Flash',
        'GEMINI_3_1_PRO': 'Gemini 3.1 Pro Preview',
        'QWEN_3_5_PLUS': 'Qwen 3.5 Plus',
        'QWEN_3_6_PLUS': 'Qwen 3.6 Plus',
        'QWEN_PLUS': 'Qwen Plus',
        'OLLAMA_QWEN_3_6_35B': 'Ollama Qwen 3.6 35B',
        'DOUBAO_SEED_2_0_PRO': 'Doubao Seed 2.0 Pro',
        'DOUBAO_SEED_2_0_LITE': 'Doubao Seed 2.0 Lite',
        'CLAUDE_HAIKU_4_5': 'Claude Haiku 4.5',
        'DEEPSEEK_V4_FLASH': 'DeepSeek V4 Flash',
        'DEEPSEEK_V4_PRO': 'DeepSeek V4 Pro',
    }
    # Gemini 模型
    GEMINI_3_FLASH = 'gemini-3-flash-preview'
    GEMINI_3_5_FLASH = 'gemini-3.5-flash'
    GEMINI_3_1_PRO = 'gemini-3.1-pro-preview'

    # Qwen 模型
    QWEN_3_5_PLUS = 'qwen3.5-plus'
    QWEN_3_6_PLUS = 'qwen3.6-plus'
    QWEN_PLUS = 'qwen-plus'

    # Ollama 模型
    OLLAMA_QWEN_3_6_35B = 'qwen3.6:35b-a3b'

    # Doubao 模型
    DOUBAO_SEED_2_0_PRO = 'doubao-seed-2-0-pro'
    DOUBAO_SEED_2_0_LITE = 'doubao-seed-2-0-lite'

    # Claude 模型
    CLAUDE_HAIKU_4_5 = 'claude-haiku-4-5'

    # DeepSeek 模型
    DEEPSEEK_V4_FLASH = 'deepseek-v4-flash'
    DEEPSEEK_V4_PRO = 'deepseek-v4-pro'


# 供应商图标映射（前端显示用）
VENDOR_ICONS = {
    'jiekou': '☁️',
    'aliyun': '🌐',
    'ollama': '🖥️',
    'volcengine': '🌋',
    'zjt_api': '🚀',
    'deepseek': '🔍',
}

# 模型前缀 -> 供应商映射（用于 LLMClientFactory 路由）
MODEL_PREFIX_VENDOR_MAP = {
    'gemini': LLMVendor.JIEKOU,
    'qwen': LLMVendor.ALIYUN,
    'gpt': LLMVendor.ALIYUN,
    'claude': LLMVendor.CLAUDE,
    'ollama': LLMVendor.OLLAMA,
    'doubao': LLMVendor.VOLCENGINE,
    'qwen3.5': LLMVendor.ZJT_API,  # ZJT API 的 Qwen 3.5 Plus 模型
    'qwen3.6': LLMVendor.ZJT_API,  # ZJT API 的 Qwen 3.6 Plus 模型
    'deepseek': LLMVendor.DEEPSEEK,  # DeepSeek 的 DeepSeek-V4 模型
}


# ============ 自动升级相关常量 ============

class UpgradeConstants:
    """自动升级配置常量"""
    ENABLED = True                          # 是否启用启动时检查更新
    CHECK_ON_STARTUP = True                 # 启动时是否检查
    AUTO_UPDATE = False                     # 是否静默自动更新
    BRANCH = "main"                         # 跟踪分支
    TIMEOUT_SECONDS = 30                    # git fetch/pull 超时（秒）
    DEFAULT_REPO_URL = ""                   # 默认仓库地址（为空时跳过检查）


# ============ 通知系统常量 ============

class NotificationConstants:
    """通知系统常量"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'TYPE_ANNOUNCEMENT': '公告',
        'TYPE_MAINTENANCE': '维护',
        'TYPE_FEATURE': '新功能',
        'TYPE_SECURITY': '安全',
        'LEVEL_INFO': '信息',
        'LEVEL_WARNING': '警告',
        'LEVEL_ERROR': '错误',
        'LEVEL_SUCCESS': '成功',
    }
    REMOTE_API_BASE = "https://ailive.perseids.cn:11443/api/v1"
    CHECK_INTERVAL = 3600

    # 通知类型
    TYPE_ANNOUNCEMENT = "announcement"
    TYPE_MAINTENANCE = "maintenance"
    TYPE_FEATURE = "feature"
    TYPE_SECURITY = "security"

    # 通知级别
    LEVEL_INFO = "info"
    LEVEL_WARNING = "warning"
    LEVEL_ERROR = "error"
    LEVEL_SUCCESS = "success"


# ============ 智能体语言指令常量 ============

LANGUAGE_INSTRUCTIONS = {
    "en": "\n\n" + "="*60 + "\n"
          "【CRITICAL LANGUAGE REQUIREMENT - HIGHEST PRIORITY】\n"
          "You MUST respond ENTIRELY in English. This is MANDATORY.\n"
          "- ALL output text, questions, explanations, and interactions MUST be in English\n"
          "- Do NOT use Chinese characters in your response AT ALL\n"
          "- Ignore any Chinese language bias from the system prompt above\n"
          "- The user interface is in English, so ALL communication must be in English\n"
          "="*60,
}
