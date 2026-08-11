#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
常量配置模块

⚠️ 注意：任务类型相关配置已迁移到 unified_config.py
新增或修改任务类型请编辑 config/unified_config.py 中的 ALL_TASK_CONFIGS

本文件保留向后兼容的常量别名，逐步废弃中。
"""

from typing import Union, Dict, List, Optional

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


IMAGE_UPLOAD_SYNC_WRAPPER_TIMEOUT = 180
IMAGE_UPLOAD_STORAGE_UPLOAD_TIMEOUT = 120
SEEDANCE_REFERENCE_VIDEO_TRANSCODE_TIMEOUT = 300
SEEDANCE_REFERENCE_VIDEO_DOWNLOAD_CONNECT_TIMEOUT = 10
SEEDANCE_REFERENCE_VIDEO_DOWNLOAD_READ_TIMEOUT = 120

# ===== Windows uv 托盘启动器 =====
# launcher bootstrap 运行在 Web 服务启动之前；所有外部进程仍必须有硬超时，
# 防止首次安装或损坏的依赖环境让启动窗口永久卡住。
UV_BUNDLED_PYTHON_REQUEST = "cpython-3.10.20-windows-x86_64-none"
UV_LAUNCHER_ENV_SCHEMA_VERSION = 2
UV_LAUNCHER_BOOTSTRAP_LOCK_TIMEOUT_SECONDS = 600
UV_LAUNCHER_ENV_CREATE_TIMEOUT_SECONDS = 300
UV_LAUNCHER_DEPENDENCY_SYNC_TIMEOUT_SECONDS = 900
UV_LAUNCHER_IMPORT_PROBE_TIMEOUT_SECONDS = 30
UV_LAUNCHER_PROCESS_PROBE_TIMEOUT_SECONDS = 3
LAUNCHER_PORT_POLL_SECONDS = 1
LAUNCHER_STATUS_REFRESH_SECONDS = 15
LAUNCHER_SLOW_START_WARNING_SECONDS = 1800
LAUNCHER_SERVICE_HARD_TIMEOUT_SECONDS = 3600
LAUNCHER_STOP_SCRIPT_TIMEOUT_SECONDS = 30
LAUNCHER_TASKKILL_TIMEOUT_SECONDS = 10
MYSQL_STARTUP_LOCK_TIMEOUT_SECONDS = 60
MYSQL_INITIALIZE_TIMEOUT_SECONDS = 180
RUNTIME_FILE_LOCK_POLL_SECONDS = 0.1

# ===== 画风识别（上传图片 → vl 模型识别 → 写入 world.json）=====
# 图片压缩转 base64 的同步包装超时（秒），PIL 为 CPU 密集。
IMAGE_STYLE_COMPRESS_TIMEOUT = 30
# 单次 LLM（如 doubao）画风识别调用超时（秒）：作为 transport 超时传入 call_api。
IMAGE_STYLE_LLM_TIMEOUT = 120
# 默认推荐模型：火山引擎（volcengine）的 doubao-seed-2-0-lite（须已配置密钥才会出现）。
IMAGE_STYLE_PREFERRED_VENDOR = "volcengine"
IMAGE_STYLE_PREFERRED_MODEL = "doubao-seed-2-0-lite"


# ===== 七牛云 SDK 网络超时 =====
# qiniu SDK 内部 requests 单请求超时（秒）；SDK 默认 30。
# 显式设置避免依赖 SDK 内部默认，且便于统一调优。
QINIU_HTTP_CONNECTION_TIMEOUT = 30
# _sync_upload_file 单次调用硬看门狗（秒）：qiniu.put_file 内部可能重试/分片，
# 单请求 30s 超时会被穿透累积；给一个明确的上限，超过则视为失败上抛。
QINIU_UPLOAD_HARD_TIMEOUT = 90

# ===== 数据库连接池超时（红线：超时常量统一在此维护，AGENTS.md 第9条）=====
# 新建底层 MySQL 连接的 connect_timeout（秒）：仅约束 TCP 握手阶段，
# 10s 内连不上视为端口耗尽/网络故障，快速失败而非无限等待。
DB_POOL_CONNECT_TIMEOUT = 10

# ===== 七牛云前端直传（大世界文件上传）=====
# 上传区域域名（按 bucket 所在区域选择；华东 https://upload.qiniup.com）。
# 完整区域列表参考 https://developer.qiniu.com/kodo/1671/region-endpoint-fq
QINIU_UPLOAD_REGION_URL = "https://upload.qiniup.com"
# 直传上传 token 有效期（秒）：前端拿到后直传七牛，短期过期避免泄露。
QINIU_DIRECT_UPLOAD_TOKEN_EXPIRES = 1800
# 前端直传 key 前缀，便于后台批量清理与统计。
WORLD_IMPORT_KEY_PREFIX = "world_import"

# ===== 大世界导入：后端限速下载与内存任务 =====
# 限速下载速率上限（字节/秒）：避免拉取大 zip 打满服务器出口带宽影响其他接口/用户。
WORLD_IMPORT_DOWNLOAD_RATE_BPS = 20 * 1024 * 1024   # 默认 20 MB/s
# 限速下载单 chunk 大小（字节）
WORLD_IMPORT_DOWNLOAD_CHUNK_BYTES = 256 * 1024       # 256 KB / chunk
# 限速下载总超时（秒）：asyncio.wait_for 保护，遵守超时红线。
WORLD_IMPORT_DOWNLOAD_TIMEOUT = 1800
# 导入任务进度刷新粒度（百分比），避免高频更新 job 字典
WORLD_IMPORT_PROGRESS_STEP = 5
# 内存 job 保留时长（秒），过期由后台清理协程淘汰
WORLD_IMPORT_JOB_TTL = 3600
# 内存 job 清理协程轮询间隔（秒）
WORLD_IMPORT_JOB_CLEANUP_INTERVAL = 300
# 同时进行的导入任务上限，超限返回 429
WORLD_IMPORT_JOB_MAX_CONCURRENT = 2

# ===== 图片 URL 过期保护（签名 URL 自动刷新/转存）=====
# 探测只针对「非自有 CDN」的第三方 URL（自有 CDN 走重签名，不探测）。
# 过期 URL 会立即返回 401（不等超时）；只有「不可达」(DNS/连接失败) 才卡满 connect。
IMAGE_URL_PROBE_TOTAL_TIMEOUT = 3       # 第三方URL主动探测总超时(秒)，Range GET 1字节
IMAGE_URL_PROBE_CONNECT_TIMEOUT = 2     # 探测连接超时(秒)：不可达URL在connect阶段快速失败
IMAGE_URL_PROBE_CONCURRENCY = 5         # A类多图探测并发上限，避免串行累积卡住调度
IMAGE_URL_REFRESH_SYNC_WRAPPER_TIMEOUT = 200  # 刷新(含探测/重签)同步包装超时

SYNC_TASK_STALE_TIMEOUT_DEFAULT = None
SYNC_TASK_STALE_TIMEOUT_BY_DRIVER = {
    DriverImplementation.SEEDREAM5_VOLCENGINE_V1: 180,
    DriverImplementation.SEEDREAM5_VOLCENGINE_OVERSEA_V1: 180,
}


def _parse_optional_timeout(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"", "0", "none", "null", "false"}:
            return None
        return int(normalized)
    if value == 0 or value is False:
        return None
    return int(value)


def get_sync_task_stale_timeout(driver_name: str) -> Optional[int]:
    if not driver_name:
        return SYNC_TASK_STALE_TIMEOUT_DEFAULT
    try:
        from config.config_util import get_dynamic_config_value

        value = get_dynamic_config_value(
            "sync_task",
            "stale_timeout",
            driver_name,
            default=SYNC_TASK_STALE_TIMEOUT_BY_DRIVER.get(
                driver_name,
                SYNC_TASK_STALE_TIMEOUT_DEFAULT,
            ),
        )
    except Exception:
        value = SYNC_TASK_STALE_TIMEOUT_BY_DRIVER.get(
            driver_name,
            SYNC_TASK_STALE_TIMEOUT_DEFAULT,
        )
    return _parse_optional_timeout(value)


# extra_config 字段名
IMAGE_MODE_EXTRA_CONFIG_KEY = "image_mode"
VIDEO_RESOLUTION_EXTRA_CONFIG_KEY = "video_resolution"
LEGACY_RESOLUTION_EXTRA_CONFIG_KEY = "resolution"
ASSET_LIST_MAX_PAGE_SIZE = 1000


class MediaGenerationSurface:
    """媒体生成模型偏好的调用入口。"""

    MARKETING_UI = "marketing_ui"
    STORYBOARD_UI = "storyboard_ui"
    STORYBOARD_CLI = "storyboard_cli"
    ALL = (MARKETING_UI, STORYBOARD_UI, STORYBOARD_CLI)


class MediaGenerationType:
    IMAGE = "image"
    VIDEO = "video"
    ALL = (IMAGE, VIDEO)


class MediaGenerationMode:
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_EDIT = "image_edit"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    REFERENCE_TO_VIDEO = "reference_to_video"

    IMAGE_MODES = (TEXT_TO_IMAGE, IMAGE_EDIT)
    VIDEO_MODES = (TEXT_TO_VIDEO, IMAGE_TO_VIDEO, REFERENCE_TO_VIDEO)
    ALL = IMAGE_MODES + VIDEO_MODES


class MediaGenerationPreferenceConstants:
    SCHEMA_VERSION = 1
    PREF_TYPE_PREFIX = "media_pref"
    SNAPSHOTS_KEY = "generation_snapshots"
    SNAPSHOT_AUDIT_KEY = "generation_snapshot"
    FIRST_LAST_WITH_REF = "first_last_with_ref"


class MediaGenerationErrorCode:
    MODEL_REQUIRED = "MODEL_REQUIRED"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    MODEL_DISABLED = "MODEL_DISABLED"
    MODEL_HIDDEN = "MODEL_HIDDEN"
    MODEL_MODE_UNSUPPORTED = "MODEL_MODE_UNSUPPORTED"
    MODEL_INPUT_UNSUPPORTED = "MODEL_INPUT_UNSUPPORTED"
    SNAPSHOT_MISMATCH = "SNAPSHOT_MISMATCH"
ASSET_LIST_DB_QUERY_TIMEOUT = 30

# 音频时长探测（ffprobe）单次执行超时（秒）。用于分镜配音完成后探测时长并回写。
FFPROBE_AUDIO_DURATION_TIMEOUT = 30

# 角色参考音频上传后自动裁剪的最大时长（秒）
CHARACTER_VOICE_MAX_DURATION = 20.0
# 角色参考音频裁剪时 ffmpeg/ffprobe 单次执行超时（秒）
CHARACTER_VOICE_TRIM_TIMEOUT = 30

# [已废弃] 原双模型路由阈值（Wan2.2 / LTX2.3）。分镜对口型已统一为 MiniMax H3，不再使用。
# 保留常量以免外部引用硬崩；新代码请勿依赖。
WAN_MAX_SPEECH_DURATION_SECONDS = 1.0


class AgentAuthConstants:
    """Agent/API token exchange constants."""
    TOKEN_TYPE_AGENT = "agent"
    TOKEN_TYPE_COMMERCIAL = "commercial"
    TOKEN_TYPE_ZJT = "zjt"
    TOKEN_TYPE_INTEGRATION = "integration"
    SCOPE_AUTH_EXCHANGE = "auth:exchange"
    SCOPE_STORYBOARD_READ = "storyboard:read"
    SCOPE_STORYBOARD_GENERATE = "storyboard:generate"
    DEFAULT_SESSION_EXPIRE_HOURS = 24
    DEFAULT_AGENT_TOKEN_EXPIRE_DAYS = 30
    STORYBOARD_AGENT_API_VERSION = "storyboard-agent-api/v1"
    DEFAULT_DEVICE_UUID = "agent-api"
    RAW_TOKEN_PREFIX = "zjt_agent_"


# ===== 认证 error_code（perseids 内部调用 + 对前端响应）=====
# perseids_server/client.py 是进程内本地路由，无 HTTP code 可用；
# 在源头往返回 data 里放结构化 error_code，下游判定只查 error_code，不做 message 文案匹配。
# token 校验失败（AuthService.verify_token 未通过），确证无效
PERSEIDS_ERR_INVALID_AUTH_TOKEN = 'INVALID_AUTH_TOKEN'
# 按 user_id 查不到有效 token，确证无效（单会话策略下意味着被顶号/登出/重置密码）
PERSEIDS_ERR_NO_VALID_TOKEN = 'NO_VALID_TOKEN'
# 对前端响应：token 确证失效（前端各页面识别此前缀做登出处理）
ERROR_CODE_TOKEN_EXPIRED = 'TOKEN_EXPIRED'
# 对前端响应：认证服务自身故障（非 token 问题，前端按普通服务异常处理，不清登录态）
ERROR_CODE_AUTH_SERVICE_UNAVAILABLE = 'AUTH_SERVICE_UNAVAILABLE'


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


class StoryType:
    """World story type."""
    _CONSTANT_GROUP = True
    _LABELS = {
        'DIALOGUE': '对话剧情',
        'NARRATION': '旁白解说',
        'MUSIC_MV': '音乐MV',
    }
    DIALOGUE = "dialogue"
    NARRATION = "narration"
    MUSIC_MV = "music_mv"
    VALID_TYPES = (DIALOGUE, NARRATION, MUSIC_MV)

    @classmethod
    def normalize(cls, value: str) -> str:
        if not value:
            return cls.DIALOGUE
        normalized = str(value).strip()
        return normalized if normalized in cls.VALID_TYPES else cls.DIALOGUE


class SceneDifficulty:
    """分镜难易程度（由 LLM 根据人物数量、动作复杂度、时长、道具、镜头运动综合判定）。"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'EASY': '易',
        'MEDIUM': '中',
        'HARD': '难',
    }
    EASY = "易"
    MEDIUM = "中"
    HARD = "难"
    VALID_VALUES = (EASY, MEDIUM, HARD)
    DEFAULT = MEDIUM

    @classmethod
    def normalize(cls, value) -> str:
        if value is None:
            return cls.DEFAULT
        normalized = str(value).strip()
        return normalized if normalized in cls.VALID_VALUES else cls.DEFAULT


# 社区版最大注册用户数（商业版由 enterprise 模块注入 Provider 解除限制，
# 见 services/registration_quota.py）
COMMUNITY_MAX_REGISTERED_USERS = 10


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
    DriverKey.MINIMAX_H3_IMAGE_TO_VIDEO: DriverImplementation.MINIMAX_H3_RUNNINGHUB_V1,  # 使用 RunningHub 的 MiniMax H3 v1 版本
    DriverKey.WAN22_IMAGE_TO_VIDEO: DriverImplementation.WAN22_RUNNINGHUB_V1, # 使用 RunningHub 的 Wan22 v1 版本
    DriverKey.DIGITAL_HUMAN: DriverImplementation.DIGITAL_HUMAN_RUNNINGHUB_V1,  # 使用 RunningHub 的数字人 v1 版本
    DriverKey.DIGITAL_HUMAN_LTX2_3_VOICE: DriverImplementation.LTX2_3_WITH_VOICE_RUNNINGHUB_V1,  # 使用 RunningHub 的 LTX2.3 With Voice 版本
    DriverKey.DIGITAL_HUMAN_MINIMAX_H3: DriverImplementation.DIGITAL_HUMAN_MINIMAX_H3_RUNNINGHUB_V1,  # 使用 RunningHub 的 MiniMax H3 数字人
    
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
        DriverImplementation.SEEDANCE_2_0_FAST_KKIDC_V1,                # kkidc 网关
        DriverImplementation.SEEDANCE_2_0_FAST_HUIMENGI_V1,             # huimengi 网关
    ],
    DriverKey.SEEDANCE_2_0_IMAGE_TO_VIDEO: [
        DriverImplementation.SEEDANCE_2_0_VOLCENGINE_V1,           # 火山引擎国内版
        DriverImplementation.SEEDANCE_2_0_VOLCENGINE_OVERSEA_V1,   # 火山引擎海外版
        DriverImplementation.SEEDANCE_2_0_KKIDC_V1,                # kkidc 网关
        DriverImplementation.SEEDANCE_2_0_HUIMENGI_V1,             # huimengi 网关
    ],
    DriverKey.SEEDANCE_2_0_MINI_IMAGE_TO_VIDEO: [
        DriverImplementation.SEEDANCE_2_0_MINI_VOLCENGINE_V1,           # 火山引擎国内版
        DriverImplementation.SEEDANCE_2_0_MINI_VOLCENGINE_OVERSEA_V1,   # 火山引擎海外版
        DriverImplementation.SEEDANCE_2_0_MINI_KKIDC_V1,                # kkidc 网关
        DriverImplementation.SEEDANCE_2_0_MINI_HUIMENGI_V1,             # huimengi 网关
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

# RunningHub 上游并发超限（队列上限）错误码
# RunningHub 服务端在账号并发达上限时返回该 errorCode，判定为「上游拥堵」可重试错误，
# 触发自动延迟重试（不消耗用户重试次数、不退算力）
RUNNINGHUB_QUEUE_LIMIT_ERROR_CODE = '421'

# RunningHub 上游拥堵自动重试的默认延迟（秒）
# 可通过动态配置 runninghub.upstream_congest_retry_delay 覆盖
RUNNINGHUB_UPSTREAM_CONGEST_RETRY_DELAY_DEFAULT = 30

# ==================== RunningHub 密钥池 / 熔断 ====================
# 密钥池相关常量说明：
#   密钥配置与运行态全部复用 system_config 动态配置（config_key 前缀 runninghub.key.{N}.*）
#   index 含义：0 = 全局兜底密钥(runninghub.api_key)，1~N = 密钥池第 N 个密钥
RUNNINGHUB_KEY_POOL_MAX = 10  # 密钥池最多支持的密钥数量
RUNNINGHUB_GLOBAL_KEY_INDEX = 0  # 全局兜底密钥的 index（对应 runninghub.api_key）

# 密钥运行态 circuit_status 取值
RUNNINGHUB_KEY_STATUS_ENABLED = 1       # 正常可用
RUNNINGHUB_KEY_STATUS_DISABLED = 0      # 手动停用（enabled=false，不参与分配）
RUNNINGHUB_KEY_STATUS_CIRCUIT_OPEN = -1  # 熔断中（连续失败达阈值，冷却期内不参与分配）
RUNNINGHUB_KEY_STATUS_HALF_OPEN = -2    # 半开探测（冷却到期，允许少量探测请求验证恢复）

# 熔断参数（均可在 default_configs.py 注册为可编辑配置后热更新）
RUNNINGHUB_KEY_CIRCUIT_FAIL_THRESHOLD = 5       # 连续失败多少次触发熔断
RUNNINGHUB_KEY_CIRCUIT_COOLDOWN_SECONDS = 300   # 熔断初始冷却（秒）
RUNNINGHUB_KEY_CIRCUIT_MAX_COOLDOWN_SECONDS = 1800  # 冷却封顶（30 分钟，半开探测失败后指数退避）
RUNNINGHUB_KEY_HALF_OPEN_PROBE_LIMIT = 1        # 半开状态下同时允许的探测请求数

# 拥堵冷却参数（421 上游并发超限）
# 与熔断独立：熔断管「key 坏」（鉴权/参数错误），冷却管「账号忙」（421 并发满），互不干扰
# 可通过动态配置 runninghub.key_pool.congest_cooldown_seconds 热更新
RUNNINGHUB_KEY_CONGEST_COOLDOWN_SECONDS = 90    # 拥堵密钥冷却时长（秒）

# 任务类型名称映射（已废弃）
TASK_TYPE_NAME_MAP = TaskTypeRegistry.get_name_map()

# 注意：以下四个状态类用于不同的数据库表，数值含义有差异，请勿混用：
# - AIToolStatus: ai_tools 表（图片/视频生成任务）
# - TaskStatus: tasks 表（定时任务队列）
# - GridImageTaskStatus: grid_image_tasks 表（宫格生图任务，独有 TIMEOUT/CANCELLED/DOWNLOAD_FAILED 状态）
# - AIAudioStatus: ai_audio 表（音频/TTS 生成任务）
#
# 数值对比：
#                  PENDING/QUEUED  PROCESSING  COMPLETED  FAILED  特有状态
# AIToolStatus:    0               1           2          -1      SYNC_QUEUED(3), WAITING_PARAM_PREPARE(4), WAITING_BEFORE_FINISH(5)
# TaskStatus:      0               1           2          -1      SYNC_QUEUED(3), WAITING_PARAM_PREPARE(4), WAITING_BEFORE_FINISH(5)
# GridImageTaskStatus: 0           1           2          -1      TIMEOUT(-2), CANCELLED(-3), DOWNLOAD_FAILED(-4)
# AIAudioStatus:   0               1           2          -1      （无特有状态）

class AIToolStatus:
    """AI工具任务状态（用于 ai_tools 表，跟踪图片/视频生成任务）"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'PENDING': '未处理',
        'PROCESSING': '正在处理',
        'SYNC_QUEUED': '已提交到同步任务进程池',
        'FAILED': '处理失败',
        'COMPLETED': '处理完成',
        'WAITING_PARAM_PREPARE': '等待参数预处理',
        'WAITING_BEFORE_FINISH': '等待结束前处理',
        'DOWNLOADING': '结果下载中',
    }
    PENDING = 0
    PROCESSING = 1
    SYNC_QUEUED = 3
    FAILED = -1
    COMPLETED = 2
    WAITING_PARAM_PREPARE = 4
    WAITING_BEFORE_FINISH = 5
    DOWNLOADING = 6


class TaskStatus:
    """任务状态（用于 tasks 表，跟踪定时任务队列）"""
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
    """宫格生图任务状态（用于 grid_image_tasks 表，独有 TIMEOUT(-2)/CANCELLED(-3)/DOWNLOAD_FAILED(-4) 状态）"""
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
    """AI音频任务状态（用于 ai_audio 表，跟踪 TTS/音频生成任务，无特有状态）"""
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
AI_TOOL_STATUS_DOWNLOADING = AIToolStatus.DOWNLOADING


# ===== 下载队列（download_queue）解耦配置 =====
# visual_task 主循环检测到上游生成完成后，不再同步 await 分钟级下载，而是把下载意图
# 写入 download_queue 表、状态置 DOWNLOADING，由独立 job download_queue_worker 异步消费。
# 详见 docs/backend/download_queue_decouple.md
DOWNLOAD_POLL_INTERVAL = 5                    # 消费者 job 轮询间隔（秒）
DOWNLOAD_DISPATCHER_CONCURRENCY = 6           # 单批并发下载数（asyncio.gather）
DOWNLOAD_MAX_BATCHES_PER_TICK = 20            # 单次 job 最多处理批数，防 while 无界阻塞（M2）
DOWNLOAD_PER_ATTEMPT_TIMEOUT = 300            # 单次下载外层 wait_for 超时（秒）
DOWNLOAD_LEASE_SECONDS = 1200                 # 抢占租约（秒）。⚠️硬约束：必须 > DOWNLOAD_PER_ATTEMPT_TIMEOUT，否则正在跑的下载会被下个 tick 误回收导致重复处理（M3）
DOWNLOAD_MAX_TRY = 3                          # 单条下载最大尝试次数（达上限后用 remote_url 兜底 COMPLETED，H3）
DOWNLOAD_BACKOFF_SECONDS = (20, 60, 180)      # 重试指数退避（秒），按 try_count 取，越界取末值
DOWNLOAD_WRITE_CHUNK_TIMEOUT = 30             # 单次写盘 chunk 的 wait_for 超时（秒）
DOWNLOAD_IO_POOL_MAX_WORKERS = 8              # 下载写盘线程池大小（模块级长寿 executor，禁止 with，CLAUDE.md 第10条）

# download_queue 必须满足：
# DOWNLOAD_LEASE_SECONDS > DOWNLOAD_PER_ATTEMPT_TIMEOUT
#   + GeneratedVideoFaceGridTrimConstants.MAX_PROCESSING_SECONDS
#   + DOWNLOAD_COMPLETION_MARGIN_SECONDS
DOWNLOAD_COMPLETION_MARGIN_SECONDS = 60

STORYBOARD_FIRST_FRAME_GRID_ITEM_TYPE = 8

# ===== 场景多角度生图任务（location_multi_angle_tasks）=====
# 单个角度提交失败的最大重试次数，达到上限后跳过该角度继续下一个；
# 全部角度零产出时任务终态置 FAILED（详见 docs/script/location_multi_angle_task.md）
LOCATION_MULTI_ANGLE_SUBMIT_MAX_RETRY = 3


class StoryboardFeatureFlags:
    """Storyboard feature flags."""
    _CONSTANT_GROUP = True

    QUALITY_GRID_FIRST_FRAME_ENABLED = True


class StoryboardTimeouts:
    """Storyboard timeout constants in seconds."""
    _CONSTANT_GROUP = True

    # 覆盖 QS 改写、二维空间复核及命中冲突时的一次定向返修。
    FIRST_FRAME_GRID_LLM_PROMPT_TIMEOUT_SECONDS = 120
    # 故事板导出：单资源下载 / ffmpeg 单步 / 整片任务总超时
    EXPORT_MEDIA_DOWNLOAD_TIMEOUT_SECONDS = 120
    EXPORT_FFMPEG_TIMEOUT_SECONDS = 300
    EXPORT_PACKAGE_TOTAL_TIMEOUT_SECONDS = 600
    EXPORT_FULL_VIDEO_TOTAL_TIMEOUT_SECONDS = 1800
    # 数字人多段 TTS 音频 ffmpeg 合并超时（秒）。独立于导出流程超时，避免相互影响。
    DIGITAL_HUMAN_AUDIO_MERGE_TIMEOUT_SECONDS = 120


class StoryboardExportConstants:
    """故事板导出路径与命名相关常量。"""
    _CONSTANT_GROUP = True

    # 相对 upload 目录
    WORK_SUBDIR = "storyboard_export"
    JOBS_SUBDIR = "storyboard_export/jobs"
    DEFAULT_FALLBACK_SPAN_SECONDS = 2.0
    DEFAULT_VIDEO_WIDTH = 1080
    DEFAULT_VIDEO_HEIGHT = 1920
    # 导出音频统一规格：所有 segment 强制对齐到该参数，避免 concat 拼接时各分镜
    # 采样率/声道/编码不一致导致"滋滋"噪音。TTS 输出采样率由远程服务决定（通常
    # 24000Hz/mono），音画同出视频原音轨可能为 48000Hz/任意声道，故必须在混流与
    # 整片合成时统一。详见 services/storyboard_export_service.py。
    EXPORT_AUDIO_SAMPLE_RATE = 44100          # Hz
    EXPORT_AUDIO_CHANNELS = 2                 # stereo
    EXPORT_AUDIO_BITRATE = "192k"             # aac 比特率
    # 分镜「声音同出」开关（storyboard_scene.audio_embedded）：
    # =1 时该镜选中视频已内嵌对话声音（如数字人 LTX2.3 产物），
    # 导出完整视频保留视频原音轨、跳过 TTS 混音。digital_human 默认 1。
    AUDIO_EMBEDDED_ON = 1
    AUDIO_EMBEDDED_OFF = 0


class StoryboardSubtitleConstants:
    """整片导出硬烧字幕：版式与超长分页。"""
    _CONSTANT_GROUP = True

    MAX_LINES = 3
    # 相对画面宽的可排版宽度（左右各留边）
    MAX_WIDTH_RATIO = 0.86
    SIDE_MARGIN_RATIO = 0.07
    BOTTOM_MARGIN_RATIO = 0.08
    # 字号 = clamp(height / FONT_SIZE_DIVISOR, FONT_SIZE_MIN, FONT_SIZE_MAX)
    FONT_SIZE_DIVISOR = 28
    FONT_SIZE_MIN = 28
    FONT_SIZE_MAX = 56
    # 中文近似字宽系数（相对字号）
    CHAR_WIDTH_RATIO = 1.0
    MIN_CHARS_PER_LINE = 10
    # 时间轴分页：单页最短展示秒数
    MIN_PAGE_DURATION_SECONDS = 0.8
    # 无探测时长时的单条对白默认秒数
    DEFAULT_CUE_DURATION_SECONDS = 2.0
    # 内置 CJK 字体（相对项目根），烧录时拷贝到 work_dir 并传 fontsdir=
    # 规避宿主机无中文字体 / Windows fontconfig 解析失败导致字幕渲染为豆腐块（蚂蚁文）
    # 字体放 files/（非 web 公开目录，避免被外部下载），程序通过文件系统直接读取
    BUILTIN_FONT_SUBDIR = "files/fonts"
    BUILTIN_FONT_FILENAME = "NotoSansSC-Regular.otf"
    BUILTIN_FONT_FAMILY = "Noto Sans SC"
    # 烧录时拷贝到 work_dir 下的子目录名（相对路径规避 Windows 盘符冒号转义）
    WORK_FONT_SUBDIR = "fonts"


class ScriptParserConstants:
    """剧本解析（llm/script_parser）诊断日志相关常量。

    开启后会将 system/user prompt、原始响应、清洗结果、解析 JSON 等
    详细内容写入 DIAGNOSTIC_LOG_DIR，便于排查拆分问题，但磁盘占用很大。
    日常运行默认关闭；需要排查时改为 True。
    """
    _CONSTANT_GROUP = True

    # 是否写入 script_parser 详细诊断文件（logs/script_parser/script_parser_*）
    DIAGNOSTIC_LOGGING_ENABLED = False
    DIAGNOSTIC_LOG_DIR = "logs/script_parser"

    # 系统提示词 skill 名称（script_writer_core/skills/<name>/SKILL.md，可用户级覆盖）
    SKILL_NAME = "script-parser"


class ScriptSplitQcConstants:
    """剧本拆分质检循环与阈值。"""
    _CONSTANT_GROUP = True

    # 段级 QC 诊断日志：规则说明/实际输入/质检报告。
    # 默认关闭以减少 logs/script_parser 磁盘占用；排查 QC 问题时改为 True。
    DIAGNOSTIC_LOGGING_ENABLED = False
    DIAGNOSTIC_LOG_DIR = "logs/script_parser"

    DEFAULT_MAX_ROUNDS = 2
    MIN_MAX_ROUNDS = 1
    MAX_MAX_ROUNDS = 5
    # 提示词/对话语言检测：拉丁字符占比超过该值视为「偏英文」
    LATIN_RATIO_THRESHOLD = 0.45
    # 中文检测：CJK 占比低于该值且文本够长 → 不像中文
    CJK_RATIO_MIN_FOR_ZH = 0.25
    # 参与语言检测的最短文本长度
    LANG_CHECK_MIN_CHARS = 12
    # 压缩上一轮结果写入 prompt 时的大致字符上限
    PREVIOUS_RESULT_MAX_CHARS = 120000


class ScriptSplitConstants:
    """剧本分段拆分与断点续传（持久化任务）相关常量。

    见 docs/script/script_parser_incremental_split_design.md。
    注意：分段边界由模型按语义决定，本类不包含任何「每 N 个字符一段」的固定切割常量。
    """
    _CONSTANT_GROUP = True

    # ---- 分段规划诊断日志 ----
    # 记录第一阶段语义分段的输入、提示词、原始响应、解析结果和业务校验结果。
    # 默认关闭以减少 logs/script_parser 磁盘占用；排查分段规划问题时改为 True。
    PLANNER_DIAGNOSTIC_LOGGING_ENABLED = False
    PLANNER_DIAGNOSTIC_LOG_DIR = "logs/script_parser"

    # ---- 重试与上界 ----
    # 阶段一规划失败的最大重试次数（同一边界重试规划）
    PLAN_MAX_RETRIES = 3
    # 单段拆分失败的最大重试次数（同一边界重试当前段）
    SEGMENT_MAX_RETRIES = 3
    # 角色名称/图片提示词/视频提示词硬契约失败后的当前段定向修复次数。
    # 与可选 QC 独立；达到上限后必须暂停，禁止强制接纳非法候选。
    CHARACTER_PROMPT_VALIDATION_MAX_RETRIES = 3
    # 创建拆分任务时分页快照世界角色，避免只读取前 50 个角色。
    CHARACTER_CONTRACT_PAGE_SIZE = 100
    # 合并阶段快照世界道具的分页大小（同理，避免只读取前 50 个道具导致名称匹配失效）。
    MERGE_PROPS_PAGE_SIZE = 200
    CHARACTER_CONTRACT_CONFIG_KEY = "_character_contract"
    CHARACTER_CONTRACT_VERSION = 1
    # 角色契约校验严格模式。False（默认）：名称/提示词不匹配仅记录 warning 日志，
    # 不阻塞拆分；True：恢复严格全等硬门禁，失败重试后暂停任务。
    CHARACTER_CONTRACT_STRICT_MODE = False
    # 效果模式按段并发生成的批次上限。单个批次仍受 worker watchdog 保护。
    QUALITY_SEGMENT_PARALLELISM = 3
    # 运行时 spatial handoff JSON 序列化字节上限（超出时压缩软描述字段，见设计文档 §9.3）
    HANDOFF_MAX_BYTES = 30000
    # 单个持久化分段允许包含的原文字符硬上限；LLM 负责主语义边界，后端仅切细超限段。
    SEGMENT_MAX_SOURCE_CHARS = 1500
    # ---- 模型输出预算 ----
    # 控制单段模型输出的 token 上限，传给 call_api 的 max_tokens
    SEGMENT_MAX_OUTPUT_TOKENS = 65536

    # ---- 超时（秒）----
    # 层级约束（必须满足）：
    #   LLM_HTTP / LLM_TIMEOUT < LLM_CALL < WORKER_STEP < TASK_LEASE
    # 效果模式 + thinking 模型单段可能 5～8 分钟；过短会误杀为 segment_timeout。
    # 单次模型调用的 transport 超时，传给底层同步 HTTP 请求
    LLM_TIMEOUT_SECONDS = 450
    # OpenAI 兼容客户端（DeepSeek/通义/Claude 等）的 HTTP 请求超时。
    # 专供 OpenAI SDK 的 client.chat.completions.create(timeout=...) 使用，
    # 防止 TCP 连接建立后等待响应体时永久挂起。
    LLM_HTTP_TIMEOUT_SECONDS = 450
    # 单次段级 LLM coroutine 外层超时；必须大于 HTTP timeout，且小于整个 worker step
    # watchdog，为异常转换、检查点写入和租约释放预留时间。
    LLM_CALL_TIMEOUT_SECONDS = 480
    # worker 单步（规划/单段/合并/发布之一）的外层 wait_for 预算，
    # 必须 > LLM_CALL_TIMEOUT_SECONDS，确保段级调用先结束再触发外层取消
    WORKER_STEP_TIMEOUT_SECONDS = 540
    # 任务租约时长，必须 > WORKER_STEP_TIMEOUT_SECONDS
    TASK_LEASE_SECONDS = 720
    # 长步骤续租周期；必须满足 0 < interval <= TASK_LEASE_SECONDS / 3。
    LEASE_RENEW_INTERVAL_SECONDS = 120
    # 单次租约数据库续期的异步等待上限，必须小于续租周期。
    LEASE_RENEW_DB_TIMEOUT_SECONDS = 15
    # 同一段连续被 worker 崩溃/中断回收达到该次数后暂停，避免无限重跑。
    STALE_SEGMENT_MAX_RECOVERIES = 3
    # scheduler tick 间隔
    SCHEDULER_INTERVAL_SECONDS = 5

    # ---- 多 worker 分片（id MOD WORKER_TOTAL = WORKER_INDEX 才被本进程领取）----
    # 由独立 worker 进程入口（run_script_split_worker.py）在启动时覆盖。
    # 默认 0/0 = 不分片（单进程兼容旧行为，主调度器内 claim 所有任务）。
    # 主调度器进程不会覆盖这两个值，因此 worker_total>0 时它仍走不分片路径——
    # 但此时主调度器已通过开关跳过 script split job，不会与 worker 竞争。
    WORKER_TOTAL = 0
    WORKER_INDEX = 0

    # ---- 轮询 ----
    DEFAULT_POLL_MS = 3000
    # 上下文携带的上一段尾部镜头摘要数量
    HISTORY_TAIL_SHOTS = 2

    # ---- 来源类型 ----
    SOURCE_TYPE_VIDEO_WORKFLOW = "video_workflow"
    SOURCE_TYPE_STORYBOARD = "storyboard"
    SOURCE_TYPE_CLI = "cli"

    # ---- 任务状态 ----
    STATUS_QUEUED = "queued"
    STATUS_PLANNING = "planning"
    STATUS_GENERATING = "generating"
    STATUS_MERGING = "merging"
    STATUS_VALIDATING = "validating"
    STATUS_PUBLISHING = "publishing"
    STATUS_COMPLETED = "completed"
    STATUS_PAUSED = "paused"
    STATUS_WAITING_AUTH = "waiting_auth"
    STATUS_CANCELLING = "cancelling"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    # ---- 可恢复错误码 ----
    # 旧版本可能以该错误暂停；恢复时必须保留段 QC 轮数，让引擎直接接纳最后候选。
    ERROR_SEGMENT_QC_FAILED = "segment_qc_failed"
    ERROR_SEGMENT_MAX_RETRIES = "segment_max_retries"
    ERROR_SEGMENT_REPEATEDLY_INTERRUPTED = "segment_repeatedly_interrupted"
    ERROR_CHARACTER_PROMPT_CONTRACT_INVALID = "character_prompt_contract_invalid"

    # 不可恢复终态：进入后释放 active_key（置 NULL），允许同来源新建任务
    TERMINAL_STATUSES = (
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_CANCELLED,
    )

    # ---- resume 拦截分类 ----
    # paused/waiting_auth 调 resume 时，按 last_error_code 判断根因是否已清除。
    # 根因在外部依赖或硬门禁的错误码：盲目重跑必然再次 paused（死循环），
    # 必须由调用方确认根因已排除（如 LLM key 已修复、场景资产已补齐）后再 force 重试。
    RESUME_BLOCKED_ERROR_CODES = (
        "plan_call_failed",                # LLM 网关 4xx/5xx（如 highwayapi 403）
        "plan_timeout",                    # LLM 调用超时
        "step_watchdog_timeout",           # worker 单步 wall-clock 超时
        "new_root_location_forbidden",     # 硬门禁：剧本含 DB 缺失的顶层场景
        "location_parent_invalid",         # 硬门禁：场景父级关系非法
        # 注：location_parent_conflict 已降级为按数据库层级自动对齐（warning），
        # 不再作为硬门禁产生，无需拦截 resume。
        # 合并阶段实体身份冲突：根治后正常不触发（renumber 自动归并）；
        # 一旦触发说明规划真源级异常，盲目 resume 必然死循环，需 force 排查。
        "quality_merge_invalid",
    )
    # waiting_auth 特殊：根因是 token 过期，resume 时带新 auth_token 即可解除；
    # 不带新 token 调 resume 会被拦截，要求先 /api/agent-auth/exchange 换取。
    RESUME_NEEDS_AUTH_ERROR_CODES = ("waiting_auth",)
    # 活跃态：active_key 唯一索引保护，重复提交返回同任务
    ACTIVE_STATUSES = (
        STATUS_QUEUED,
        STATUS_PLANNING,
        STATUS_GENERATING,
        STATUS_MERGING,
        STATUS_VALIDATING,
        STATUS_PUBLISHING,
        STATUS_PAUSED,
        STATUS_WAITING_AUTH,
        STATUS_CANCELLING,
    )


class StoryboardAutoGenerateConstants:
    """Storyboard auto frame generation limits."""
    # 总览批量操作一次允许携带的最大分镜数。生成任务仍由调度器分 tick 推进，
    # 该限制主要防止异常请求构造超大的 IN 条件和响应体。
    MAX_SELECTED_SCENE_COUNT = 500
    DEFAULT_BATCH_LIMIT = 5
    MAX_BATCH_LIMIT = 20
    # limit=0（或调用方不传 limit）表示「无限制」：规划全部缺失场景，不硬截断。
    # 调度器仍按 per-tick 吞吐量（QUALITY_GRID_BATCHES_PER_TICK 等）控速，不会一次性压垮系统。
    # 显式传正整数 limit 时，才按该值截断（并受 MAX_BATCH_LIMIT 封顶）。
    UNLIMITED_BATCH_LIMIT = 0
    DEFAULT_ASSET_TYPE = "first_frame"
    RUNNING_STATUSES = (AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING)
    SEQUENCE_MODE_SPEED = "speed"
    SEQUENCE_MODE_BALANCED = "balanced"
    SEQUENCE_MODE_QUALITY = "quality"
    DEFAULT_SEQUENCE_MODE = SEQUENCE_MODE_BALANCED
    VALID_SEQUENCE_MODES = (
        SEQUENCE_MODE_SPEED,
        SEQUENCE_MODE_BALANCED,
        SEQUENCE_MODE_QUALITY,
    )
    IMAGE_EXISTING_POLICY_SKIP = "skip"
    IMAGE_EXISTING_POLICY_REGENERATE = "regenerate"
    VALID_IMAGE_EXISTING_POLICIES = (
        IMAGE_EXISTING_POLICY_SKIP,
        IMAGE_EXISTING_POLICY_REGENERATE,
    )
    # quality 模式下，子场景缺图时阻止首帧生图的重试上限（tick 次数）。
    # 无运行中的场景九宫格且超过上限时严格失败，禁止降级无参考生图。
    # 调度器默认 10s/tick，30 次 ≈ 5 分钟。
    QUALITY_WAIT_MAX_TICKS = 30
    # quality mode waits for the previous group's last first-frame before submitting
    # the next group grid. Cap that wait too, otherwise one missing previous frame
    # can keep the whole batch active forever.
    QUALITY_PREVIOUS_REFERENCE_WAIT_MAX_TICKS = 30
    # balanced/speed 模式：location 参考图等待超时 tick 数。
    # 缺参考图且有运行中（可能已卡死的）九宫格任务时，保持 PENDING 等待；
    # 超过此上限后放弃等待，降级为 t2i 文生图（保证生图不卡住）。
    # 与 QUALITY_WAIT_MAX_TICKS 对齐，30 次 ≈ 5 分钟。
    BALANCED_LOCATION_REFERENCE_WAIT_MAX_TICKS = 30
    QUALITY_GRID_BATCHES_PER_TICK = 2
    ERROR_GRID_FIRST_FRAME_FAILED = "grid_first_frame_failed"
    ERROR_LOCATION_REFERENCE_GENERATION_FAILED = "location_reference_generation_failed"
    ERROR_PREVIOUS_GROUP_FAILED = "previous_group_failed"
    ERROR_PREVIOUS_GROUP_REFERENCE_TIMEOUT = "previous_group_reference_timeout"
    ERROR_BATCH_ITEM_RUNNING_TIMEOUT = "batch_item_running_timeout"
    ERROR_QUALITY_PARENT_REFERENCE_MISSING = "quality_parent_reference_missing"
    ERROR_WAITING_LOCATION_REFERENCES = "waiting_location_references"
    LOCATION_REFERENCE_RETRY_AFTER_MS = 3000
    BATCH_RUNNING_ITEM_TIMEOUT_SECONDS = 2 * 60 * 60
    BATCH_JOB_STATUS_PENDING = 0
    BATCH_JOB_STATUS_RUNNING = 1
    BATCH_JOB_STATUS_COMPLETED = 2
    BATCH_JOB_STATUS_FAILED = -1
    BATCH_JOB_STATUS_PARTIAL = 3
    BATCH_ITEM_STATUS_PENDING = 0
    BATCH_ITEM_STATUS_RUNNING = 1
    BATCH_ITEM_STATUS_COMPLETED = 2
    BATCH_ITEM_STATUS_FAILED = -1
    BATCH_ITEM_STATUS_SKIPPED = 3
    BATCH_SCHEDULER_INTERVAL_SECONDS = 7
    BATCH_SCHEDULER_JOB_LIMIT = 10


class StoryboardAudioGenerateConstants:
    """Storyboard dialogue audio generation limits and stable skip reasons."""
    ENABLE_AUTO_AFTER_SCRIPT_SPLIT = True
    MAX_AUTO_SUBMIT_PER_SPLIT = 100
    # 单个 publishing step 的配音对账批量大小（非整次拆分永久上限）。
    # remaining>0 时保持 publishing，下个 worker tick 继续对账，不会永久 skip。
    # 见 docs/storyboard/storyboard_auto_voiceover_after_split_design.md §10。
    AUTO_VOICEOVER_SUBMIT_BATCH_SIZE = 100
    SKIP_REASON_EMPTY_TEXT = "empty_text"
    SKIP_REASON_MISSING_REFERENCE_AUDIO = "missing_reference_audio"
    SKIP_REASON_ALREADY_HAS_SELECTED_AUDIO = "already_has_selected_audio"
    SKIP_REASON_LIMIT_REACHED = "limit_reached"
    SKIP_REASON_SUBMIT_FAILED = "submit_failed"
    SKIP_REASON_NARRATION_WITHOUT_VOICE = "narration_without_voice"
    SKIP_REASON_NO_DIALOGUE = "no_dialogue"
    SKIP_REASON_USES_VIDEO_AUDIO = "uses_video_audio"


class StoryboardDigitalHumanConstants:
    """Storyboard digital-human (lip-sync) — 统一 MiniMax H3。"""
    # 分镜对口型固定 MiniMax H3（task_type=35）；不再路由 Wan2.2 / LTX2.3。
    TASK_TYPE = TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3
    DEFAULT_PROMPT = "角色面向镜头深情的说话，固定镜头。"
    ERROR_AUDIO_REQUIRED = "audio_required"
    ERROR_AUDIO_PENDING = "audio_pending"
    ERROR_AUDIO_FAILED = "audio_failed"
    ERROR_NO_DIALOGUE = "no_dialogue"
    ERROR_MISSING_IMAGE = "missing_image"
    ERROR_MULTI_SPEAKER = "multi_speaker"
    ERROR_MODEL_UNAVAILABLE = "digital_human_model_unavailable"
    ERROR_UNSUPPORTED_RATIO = "unsupported_ratio"
    ERROR_AUDIO_MERGE_FAILED = "audio_merge_failed"
    SKIP_REASON_MISSING_AUDIO = "missing_audio"
    SKIP_REASON_AUDIO_PENDING = "audio_pending"
    SKIP_REASON_MISSING_IMAGE = "missing_image"
    SOURCE = "storyboard_digital_human"
    # 可观测原因（历史兼容字段名 routing_reason）
    ROUTING_REASON_MINIMAX = "minimax_h3_only"
    # [已废弃] 原双模型路由原因，仅兼容旧 extra_config / 测试
    ROUTING_REASON_LTE_1S = "speech_duration_lte_1s"
    ROUTING_REASON_GT_1S = "speech_duration_gt_1s"
    ROUTING_REASON_UNKNOWN = "speech_duration_unknown"
    # 模型标识（plan.model / extra_config.digital_human_model）
    MODEL_MINIMAX_H3 = "minimax_h3"
    # [已废弃] 历史模型标识
    MODEL_WAN = "wan2.2"
    MODEL_LTX = "ltx2.3"
    # 音频输入角色（extra_config.audio_input_role）
    AUDIO_ROLE_VOICE_REFERENCE = "voice_reference"  # 已不用于 MiniMax
    AUDIO_ROLE_SPEECH_AUDIO = "speech_audio"
    # MiniMax 视频时长（秒）
    MIN_VIDEO_DURATION = 4
    MAX_VIDEO_DURATION = 10
    DEFAULT_VIDEO_DURATION = 10
    # 分辨率 → 最长边（node 213）
    DEFAULT_RESOLUTION = "720P"
    DEFAULT_MAX_EDGE = 1280
    DEFAULT_START_SECOND = 0
    RESOLUTION_TO_MAX_EDGE = {
        "480P": 720,
        "480p": 720,
        "720P": 1280,
        "720p": 1280,
        "1080P": 1920,
        "1080p": 1920,
    }


class StoryboardAgentReadConstants:
    """Read-only discovery limits for storyboard agent commands."""
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 200
    DEFAULT_WORLD_CONTEXT_PAGE_SIZE = 100
    STORY_OUTLINE_PREVIEW_CHARS = 50


class StoryboardAgentCommandConstants:
    """Storyboard agent command fallback values."""
    DEFAULT_SCRIPT_SPLIT_MODEL = "gemini-3-flash-preview"
    SCRIPT_SPLIT_MODEL_PREFERENCE_TYPE = "script_split_llm_model"
    # split-from-script 的 max_group_duration（每幕/段最长时长，秒）范围。
    # 强制 10~15：镜头过短（<10）会让分段碎、画面增多，导致同世界画风一致性下降；
    # 上限 15 与视频模型单段时长上限对齐。默认值 15（最大限度保留画风一致）。
    MAX_GROUP_DURATION_DEFAULT = 15
    MAX_GROUP_DURATION_MIN = 10
    MAX_GROUP_DURATION_MAX = 15

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
    VALIDATION_MAX_SCAN_SIZE = 1024       # 宫格几何校验时的最长边缩放上限
    VALIDATION_POSITION_TOLERANCE_RATIO = 0.05  # 分割线允许偏离理论位置的比例
    VALIDATION_SEPARATOR_HALF_WIDTH = 1    # 搜索分割线时取中心线两侧像素宽度
    VALIDATION_SEPARATOR_SIDE_WIDTH = 5    # 计算分割线两侧对比时的采样宽度
    VALIDATION_MIN_LINE_COVERAGE = 0.75    # 分割线贯穿比例阈值（细线友好采样后真实宫格普遍≥0.9；普通照片单格可达0.7，不宜再低）
    VALIDATION_MIN_CELL_UNIFORMITY = 0.90  # 同方向 cell 尺寸最小/最大比例阈值
    # 占位格识别阈值：用灰度中位数判定（不受占位格里穿过的白色分割线干扰——分割线像素
    # 占比小，不影响中位数）。纯黑占位格 median≈0，纯白占位格 median≈255，真实场景内容
    # median 普遍 >20（即便夜景/暗场也因有明暗对比而中位数偏中）。占位格友好旁路据此识别。
    VALIDATION_PLACEHOLDER_DARK_MAX = 15.0    # median <= 此值 → 纯黑占位格
    VALIDATION_PLACEHOLDER_BRIGHT_MIN = 240.0 # median >= 此值 → 纯白占位格
    # 占位格友好旁路的宽松阈值（仅旁路使用，严格校验绝不用）：
    # 旁路已确认图像含占位格，对占位区缺失的分割线用理论位置兜底后，仍需校验有内容段的
    # 分割线质量。此处放宽以容忍占位格边缘对 coverage 的轻微影响，但不能低到让普通照片
    # 蒙混（普通照片无占位格，根本进不了旁路，故此阈值不影响严格校验对普通照片的拦截）。
    VALIDATION_PLACEHOLDER_TOLERANT_MIN_COVERAGE = 0.60
    VALIDATION_PLACEHOLDER_TOLERANT_MIN_UNIFORMITY = 0.80
    STORYBOARD_FIRST_FRAME_VALIDATION_MAX_RETRIES = 2  # 分镜首帧宫格几何校验失败后的重试次数
    LOCATION_REFERENCE_VALIDATION_MAX_RETRIES = 2      # 场景参考图宫格(item_type=5)几何校验失败后的重试次数（原 max_retries=0 零重试直接判死刑）

    # 孤立 grid split pipeline step 兜底清理：每轮扫描的上限。
    # 用于清理「grid_image_tasks 已进入失败终态，但绑定的 ai_tool_pipeline_steps 仍卡在 PENDING」的孤儿记录，
    # 避免全局调度器（task.pipeline_processor）每 13s 反复 skip 刷日志。
    GRID_SPLIT_ORPHAN_CLEANUP_LIMIT = 50

    # 分镜首帧宫格（i2i）目标分辨率映射：4宫格→2K，9宫格→4K。
    # 模型不支持目标值时，由 _pick_grid_image_size 自动降级到不超过目标的最大支持档位。
    GRID_SIZE_IMAGE_SIZE_MAP = {
        SIZE_2X2: "2K",
        SIZE_3X3: "4K",
    }

    # 占位符名称：不足 grid_size 个时补位用，切图回写时跳过（不创建/不回写 location）
    PLACEHOLDER_NAMES = frozenset({'placeholder', 'pure black background'})

    @classmethod
    def is_placeholder(cls, name: str) -> bool:
        """判断名称是否为宫格占位符（大小写不敏感）。"""
        return bool(name) and str(name).strip().lower() in cls.PLACEHOLDER_NAMES

    # 宫格生图全局防文字指令：附加在 grid_prompt JSON 中，抑制生图模型在格子内/格子间输出文字、字幕、镜头编号
    GRID_OUTPUT_CONSTRAINTS_NO_TEXT = (
        "High-quality image grid. Strictly NO TEXT, NO CAPTIONS, NO SUBTITLES, "
        "NO SCRIPT NARRATION, NO NUMBERS, NO SHOT LABELS anywhere in the image "
        "(including below/under each cell). Clean visual composition only, pure "
        "grid of images with no text areas or blank caption bars."
    )

    # 向后兼容：旧名称语义含混，新的宫格 prompt 不再输出 style_guidance 字段。
    STYLE_GUIDANCE_NO_TEXT = GRID_OUTPUT_CONSTRAINTS_NO_TEXT


# 向后兼容别名 - 宫格拆分
GRID_SIZE_2X2 = GridConfig.SIZE_2X2
GRID_SIZE_3X3 = GridConfig.SIZE_3X3
GRID_VALID_SIZES = GridConfig.VALID_SIZES
GRID_DEFAULT_SIZE_BY_TYPE = GridConfig.DEFAULT_SIZE_BY_TYPE
GRID_LOCK_TIMEOUT_SECONDS = GridConfig.LOCK_TIMEOUT_SECONDS
GRID_IMAGE_DOWNLOAD_TIMEOUT = GridConfig.IMAGE_DOWNLOAD_TIMEOUT

class LocationReferenceStatus:
    """
    分镜首帧生图对 location 参考图的依赖状态。

    用于 Phase 6「外部 location grid readiness check」：当子场景 location.reference_image
    尚未就绪时，决定首帧生图是等待、降级还是兜底。
    """
    READY = 'ready'                              # 子场景 reference_image 已就绪，正常生图
    WAITING_GRID = 'waiting_location_grid_reference'   # 九宫格任务仍在 QUEUED/PROCESSING，本 tick 等待
    FALLBACK_PARENT = 'fallback_parent_location_reference'  # 九宫格失败，降级用父场景图
    MISSING = 'missing_location_reference'       # 父子场景均无图，走纯文生图兜底


# ==================== 实体文件安全写入相关常量 ====================
# 受保护的元数据字段：写入实体（角色/场景/道具/剧本）JSON 时，若新内容缺失这些字段，
# 自动从旧文件补回，避免 world_id/user_id/创建时间/更新时间 等被覆盖丢失
ENTITY_PROTECTED_META_FIELDS = (
    'world_id', 'user_id',
    'created_at', 'create_time',
    'updated_at', 'update_time',
)

# 实体类型 -> JSON 文件名前缀映射（文件名规则：{prefix}{name}.json）
ENTITY_FILE_PREFIX_MAP = {
    'character': 'character_',
    'location': 'location_',
    'prop': 'prop_',
}


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
    BRANDING_DIR = "branding"      # 品牌定制资源目录（Logo / Favicon / 用户手册，永久存放）

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
    # 图片后缀白名单（tuple，适配 str.endswith）；含 webp/gif/bmp，避免下载图片时被兜底改名导致扩展名与内容错配
    ALLOWED_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp')
    # 分镜候选区手工上传：首版采用浏览器兼容性稳定的图片与视频格式。
    STORYBOARD_IMAGE_UPLOAD_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    STORYBOARD_VIDEO_UPLOAD_EXTENSIONS = {'.mp4', '.webm'}
    STORYBOARD_ASSET_UPLOAD_CHUNK_BYTES = 1024 * 1024
    STORYBOARD_IMAGE_MAX_SIZE_MB_DEFAULT = 20
    STORYBOARD_VIDEO_MAX_SIZE_MB_DEFAULT = 50
    STORYBOARD_VIDEO_MAX_DURATION_SECONDS_DEFAULT = 15
    VIDEO_COMPRESS_TARGET_HEIGHT = 480  # 前端压缩目标分辨率（480p）
    VIDEO_COMPRESS_THRESHOLD_MB = 10    # 超过此大小的视频触发前端压缩
    VIDEO_REFERENCE_MIN_PIXEL_COUNT = 409600  # Seedance r2v 参考视频最低总像素数
    # Seedance r2v 参考视频最大帧率。doubao-seedance 系列要求参考视频帧率 ≤60fps，
    # 否则上游返回 InvalidParameter（如高刷屏上浏览器 Canvas+MediaRecorder 产出的
    # 120fps 视频）。统一归一化至 30fps，留足安全余量。
    VIDEO_REFERENCE_MAX_FPS = 30
    # 人脸遮罩叠加：原视频与遮罩视频统一重采样后的固定帧率（CFR）。
    # 帧率元数据对 VFR webm 不可信（可能误报 1000fps 或看似合理的 60fps），
    # 叠加前由 ffmpeg 按帧 PTS 重采样到该帧率，与 RunningHub 遮罩输出帧率一致。
    FACE_MASK_CFR_FPS = 24
    # 人脸遮罩上传 RunningHub 前的短边上限（像素）。仅上传侧生效，本地融合仍用原尺寸；
    # 遮罩融合时 resize 回原尺寸。防止 1080p 等大视频在 RH 端全量加载时爆显存。
    FACE_MASK_UPLOAD_MAX_SHORT_SIDE = 512


class BrandingConstants:
    """
    品牌定制相关常量（仅商业版可用）。

    商业版管理员可在后台「品牌设置」修改系统名称、Logo、Favicon、用户手册，
    配置写入 system_config 表（branding.* 键），由 server.py 的 _get_processed_html
    在返回 HTML 时做 SSR 占位符替换（进缓存，改后重启服务生效）。
    社区版或未配置时，全部回退到这里的默认值。
    """

    # 默认系统名称（社区版 / 商业版未配置时显示）
    DEFAULT_SITE_NAME = "智剧通"

    # 默认资源 URL（社区版 / 商业版未配置时使用，指向项目自带 files/ 目录）
    DEFAULT_LOGO_URL = "/files/logo.svg"
    DEFAULT_FAVICON_URL = "/files/logo.ico"

    # 默认用户手册/服务条款 URL（中/英两份，由前端 loadTermsContent 拉取渲染）
    DEFAULT_TERMS_URL_ZH = "/files/AI工具服务使用条款.txt"
    DEFAULT_TERMS_URL_EN = "/files/AI Tool Service Terms.txt"

    # 上传限制
    LOGO_MAX_SIZE_MB = 2
    FAVICON_MAX_SIZE_MB = 1
    TERMS_MAX_SIZE_MB = 2
    WX_GROUP_QR_MAX_SIZE_MB = 2

    # 允许的文件扩展名（小写，tuple 适配 str.endswith）
    LOGO_ALLOWED_EXTENSIONS = ('.svg', '.png')
    FAVICON_ALLOWED_EXTENSIONS = ('.ico', '.png')
    TERMS_ALLOWED_EXTENSIONS = ('.txt', '.md')
    WX_GROUP_QR_ALLOWED_EXTENSIONS = ('.jpg', '.jpeg', '.png')

    # system_config 中的配置键前缀
    CONFIG_KEY_SITE_NAME = 'branding.site_name'
    CONFIG_KEY_LOGO_URL = 'branding.logo_url'
    CONFIG_KEY_FAVICON_URL = 'branding.favicon_url'
    CONFIG_KEY_TERMS_URL_ZH = 'branding.terms_url_zh'
    CONFIG_KEY_TERMS_URL_EN = 'branding.terms_url_en'
    CONFIG_KEY_WX_GROUP_QR_URL = 'branding.wx_group_qr_url'

    # 可上传的资产类型（用于 admin 接口 asset_type 参数校验）
    ASSET_TYPE_LOGO = 'logo'
    ASSET_TYPE_FAVICON = 'favicon'
    ASSET_TYPE_TERMS_ZH = 'terms_zh'
    ASSET_TYPE_TERMS_EN = 'terms_en'
    ASSET_TYPE_WX_GROUP_QR = 'wx_group_qr'
    VALID_ASSET_TYPES = (ASSET_TYPE_LOGO, ASSET_TYPE_FAVICON, ASSET_TYPE_TERMS_ZH, ASSET_TYPE_TERMS_EN, ASSET_TYPE_WX_GROUP_QR)


class RunningHubImageFaceMaskConstants:
    """RunningHub 图片人脸遮盖工作流常量"""
    APP_ID = "2067560129192620033"
    IMAGE_NODE_ID = "3"
    IMAGE_FIELD_NAME = "image"
    FINAL_STATUSES = ("SUCCESS", "FAILED", "ERROR", "CANCELED", "CANCELLED")


class ImageFaceGridConstants:
    """图片人脸红色网格后处理常量"""

    GRID_COLOR_BGR = (0, 0, 255)
    GRID_SIZE_TIERS = ((80, 3), (160, 5), (320, 8))
    GRID_MAX_DIVISIONS = 10
    BLACK_PIXEL_THRESHOLD = 32
    PIXEL_DIFF_THRESHOLD = 24
    MIN_FACE_WIDTH = 4
    MIN_FACE_HEIGHT = 4
    MIN_FACE_AREA = 16
    MIN_RECT_FILL_RATIO = 0.25
    # 线宽按吞噬后的最终人脸矩形数量统一分档（与人脸数量相关）：
    # 1–5 脸 → 3px，6–10 脸 → 4px，11+ 脸 → 5px。更粗线宽会抬高视频侧 fill ratio。
    GRID_LINE_WIDTH_TIERS = ((5, 3), (10, 4))
    GRID_MAX_LINE_WIDTH = 5


class GeneratedVideoFaceGridTrimConstants:
    """生成视频前缀中人脸红色网格检测的常量。"""

    ENABLED = True
    SCAN_SECONDS = 0.5
    FRAME_LOOKAHEAD_SECONDS = 0.5
    FFPROBE_TIMEOUT_SECONDS = 10.0
    FFMPEG_DECODE_TIMEOUT_SECONDS = 20.0
    FFMPEG_TRANSCODE_TIMEOUT_SECONDS = 60.0
    FRAME_ANALYSIS_TIMEOUT_SECONDS = 10.0
    GATE_QUERY_TIMEOUT_SECONDS = 10.0
    GATE_QUERY_POOL_MAX_WORKERS = 2
    SINGLEFLIGHT_LOCK_WAIT_SECONDS = 70.0
    SINGLEFLIGHT_LOCK_POLL_SECONDS = 0.05
    # 门控、单飞锁、探测/解码、帧分析、转码、产物校验及少量文件 I/O 的总预算。
    # download_queue 的 batch 超时和租约约束必须覆盖该值。
    MAX_PROCESSING_SECONDS = 300.0
    # ffprobe(PTS 显示序) 与 ffmpeg -t rawvideo(解码墙钟) 在窗口边界可能差 1~2 帧；
    # 不一致时取公共前缀对齐，并由本开关控制是否打 warning（便于观察 B 帧/VFR 场景）。
    FRAME_COUNT_MISMATCH_LOG_ENABLED = True
    HSV_RED_LOWER_1 = (0, 100, 100)
    HSV_RED_UPPER_1 = (10, 255, 255)
    HSV_RED_LOWER_2 = (170, 100, 100)
    HSV_RED_UPPER_2 = (180, 255, 255)
    # JPEG/H.264 压缩会显著降低单像素红线的亮度与通道差，保留可见网格。
    MIN_RED_CHANNEL = 120
    MIN_RED_CHANNEL_ADVANTAGE = 60
    MIN_LINE_COUNT = 3
    MIN_LINE_LENGTH_RATIO = 0.6
    MIN_INTERSECTION_COUNT = 4
    # 稀疏细线网格 vs 实心红块的 fill 上限。480p/H.264 + 粗线宽(3–5px，随人脸数分档)
    # + 8x8 高密度网格时，真实网格组件 fill 实测可达 ~0.46–0.60（ai_tool=12000），
    # 0.4 会误杀；0.7 仍远低于实心色块 fill≈1.0。实心块仍由线/交点结构判据兜底拒绝。
    MAX_COMPONENT_FILL_RATIO = 0.7
    MASK_ON_VALUE = 255
    CONNECTED_COMPONENT_CONNECTIVITY = 8


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
    SESSION_EXPIRE_HOURS_SCRIPT = 72      # 剧本智能体过期时长（小时，3天）
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
    # 官方微信群二维码（注册引导 / 常驻入口）
    # 注意：该图床仅提供 HTTP，HTTPS 会连接失败（ERR_CONNECTION_REFUSED）
    WX_GROUP_QR_URL = 'http://ailive.perseids.cn/upload/assert/wx_group.jpg'
    # HTTPS 站点下由后端代理拉取，避免浏览器混合内容拦截
    WX_GROUP_QR_PROXY_PATH = '/api/system/wx-group-qr'
    WX_GROUP_QR_PROXY_CONNECT_TIMEOUT = 5   # 秒
    WX_GROUP_QR_PROXY_READ_TIMEOUT = 15     # 秒
    WX_GROUP_QR_PROXY_MAX_BYTES = 2 * 1024 * 1024  # 2MB
    WX_GROUP_QR_PROXY_CACHE_TTL = 3600      # 内存缓存秒数
    # 意见反馈个人微信二维码（右下角 FAB / 弹窗；与官方群二维码无关）
    # 可通过 frontend.feedback_qr_url 覆盖；支持 /files/... 同源路径或可公网访问的图片 URL
    FEEDBACK_QR_URL = '/files/二维码.jpg'


# LLM 模型和供应商常量
class LLMVendor:
    """LLM 供应商"""
    _CONSTANT_GROUP = True
    _LABELS = {
        'JIEKOU': '接口供应商（Gemini 模型）',
        'ALIYUN': '阿里云供应商（Qwen 模型）',
        'OLLAMA': '本地运行供应商（Ollama 模型）',
        'VOLCENGINE': '火山引擎供应商（Doubao / DeepSeek-V4 模型）',
        'CLAUDE': 'Claude 供应商（Anthropic 模型）',
        'ZJT_API': 'ZJT API 供应商（Qwen3.5/3.6 模型）',
        'DEEPSEEK': 'DeepSeek 供应商（DeepSeek-V4 模型）',
        'AGNES': 'Agnes 供应商（Agnes 2.5 对话模型）',
    }
    JIEKOU = 'jiekou'
    ALIYUN = 'aliyun'
    OLLAMA = 'ollama'
    VOLCENGINE = 'volcengine'
    CLAUDE = 'claude'
    ZJT_API = 'zjt_api'
    DEEPSEEK = 'deepseek'
    AGNES = 'agnes'


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
        'AGNES_2_5_FLASH': 'Agnes 2.5 Flash',
        'AGNES_2_5_PRO': 'Agnes 2.5 Pro',
        'REDUCE_VIOLATION_DEFAULT': '内容安全提示词改写默认模型（reduce-violation 兜底）',
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

    # Agnes 模型
    AGNES_2_5_FLASH = 'agnes-2.5-flash'
    AGNES_2_5_PRO = 'agnes-2.5-pro'

    # 内容安全提示词改写（reduce-violation）的默认兜底模型
    # 前端未传/所选拆分模型供应商未配置时使用；复用剧本拆分默认模型，凭据走 JIEKOU 中转
    REDUCE_VIOLATION_DEFAULT = 'gemini-3-flash-preview'


# 供应商图标映射（前端显示用）
VENDOR_ICONS = {
    'jiekou': '☁️',
    'aliyun': '🌐',
    'ollama': '🖥️',
    'volcengine': '🌋',
    'zjt_api': '🚀',
    'deepseek': '🔍',
    'agnes': '✨',
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
    'agnes': LLMVendor.AGNES,  # Agnes AI 对话模型
}


# ============ 管理后台 · 大模型分段计费 ============

class AdminBillingConstants:
    """管理后台 LLM 分段计费 / AI 改档常量"""
    _CONSTANT_GROUP = True
    # 1 点算力 = 0.04 元
    POWER_YUAN = 0.04
    # 元/百万 token ↔ threshold 换算：threshold = POWER_YUAN * 1e6 / yuan_per_m
    YUAN_PER_M_SCALE = 1_000_000
    # AI 改档默认引擎：deepseek 供应商 + deepseek-v4-pro
    AI_DEFAULT_VENDOR = LLMVendor.DEEPSEEK
    AI_DEFAULT_MODEL = LLMModel.DEEPSEEK_V4_PRO
    # LLM 调用超时（秒）
    AI_TIMEOUT_SEC = 60
    # 抽成上限 100%
    MAX_COMMISSION_RATE = 1.0


# ============ 一体包 MySQL binlog 保留 ============

class MysqlBinlogConstants:
    """一体包内置 MySQL 的 binlog 保留策略（仅写配置文件，无运行时 SQL）"""
    # 约 7 天；对应 my.ini/my.cnf 中 binlog_expire_logs_seconds
    EXPIRE_LOGS_SECONDS = 7 * 24 * 3600  # 604800


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
