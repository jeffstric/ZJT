"""
Default configurations for dynamic config system
默认可热更新配置定义
"""
from typing import List, Dict, Any

# 默认配置列表
# 每个配置包含：key, value_type, description, editable, is_sensitive
# 可选字段：quick_config - 标记是否为快速配置项（在快速配置弹窗中显示）
DEFAULT_CONFIGS: List[Dict[str, Any]] = [
    # ==================== 任务队列配置 ====================
    {
        'key': 'task_queue.max_retry_count',
        'value_type': 'int',
        'description': '任务最大重试次数，超过后任务将被标记为失败',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'task_queue.task_expire_days',
        'value_type': 'int',
        'description': '任务过期天数，创建后超过此天数的任务将被自动失败',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'task_queue.enable_expire_check',
        'value_type': 'bool',
        'description': '是否启用任务过期检查',
        'editable': True,
        'is_sensitive': False
    },
    
    # ==================== 上传配置 ====================
    {
        'key': 'upload.max_image_size_mb',
        'value_type': 'int',
        'description': '角色、场景、道具的参考图片最大大小限制（MB）',
        'editable': True,
        'is_sensitive': False
    },
    
    # ==================== 前端配置 ====================
    {
        'key': 'frontend.debug_password',
        'value_type': 'string',
        'description': '前端 Debug 模式密码',
        'editable': True,
        'is_sensitive': True
    },
    
    # ==================== 工作流配置 ====================
    {
        'key': 'workflow.poll_status_interval',
        'value_type': 'int',
        'description': '工作流节点状态轮询间隔（秒），默认60秒',
        'editable': True,
        'is_sensitive': False
    },
    
    # ==================== 超时配置 ====================
    {
        'key': 'timeout.request_timeout',
        'value_type': 'int',
        'description': '请求超时时间（毫秒）',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'timeout.status_check_timeout',
        'value_type': 'int',
        'description': '状态检查超时时间（秒）',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'timeout.status_check_interval',
        'value_type': 'int',
        'description': '状态检查间隔时间（秒）',
        'editable': True,
        'is_sensitive': False
    },
    
    # ==================== 测试模式配置 ====================
    {
        'key': 'test_mode.enabled',
        'value_type': 'bool',
        'description': '是否启用测试模式',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'test_mode.mock_videos.image_to_video',
        'value_type': 'string',
        'description': '图生视频的测试视频URL',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'test_mode.mock_videos.text_to_video',
        'value_type': 'string',
        'description': '文生视频的测试视频URL',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'test_mode.mock_images.image_edit',
        'value_type': 'string',
        'description': '图片编辑的测试图片URL',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'test_mode.mock_images.text_to_image',
        'value_type': 'string',
        'description': '文生图的测试图片URL',
        'editable': True,
        'is_sensitive': False
    },
    
    # ==================== 图片配置 ====================
    {
        'key': 'image.enable_download',
        'value_type': 'bool',
        'description': '是否启用图片下载',
        'editable': True,
        'is_sensitive': False
    },
    
    # ==================== RunningHub 配置 ====================
    {
        'key': 'runninghub.host',
        'value_type': 'string',
        'description': 'RunningHub 服务地址',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'runninghub.api_key',
        'value_type': 'string',
        'description': 'RunningHub API Key',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'runninghub.max_concurrent_slots',
        'value_type': 'int',
        'description': 'RunningHub 最大并发槽位数量',
        'editable': True,
        'is_sensitive': False
    },
    
    # ==================== Duomi 配置 ====================
    {
        'key': 'duomi.token',
        'value_type': 'string',
        'description': '多米 API Token',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    
    # ==================== Vidu 配置 ====================
    {
        'key': 'vidu.token',
        'value_type': 'string',
        'description': 'Vidu API Token',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },

    # ==================== 火山引擎配置 ====================
    {
        'key': 'volcengine.api_key',
        'value_type': 'string',
        'description': '火山引擎 API Key（Seedream 5.0 文生图）',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },

    # ==================== 微信支付配置 ====================
    {
        'key': 'pay.wxpay.appId',
        'value_type': 'string',
        'description': '微信支付公众账号ID',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'pay.wxpay.mchId',
        'value_type': 'string',
        'description': '微信支付商户号',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'pay.wxpay.api_key',
        'value_type': 'string',
        'description': '微信支付商户API证书序列号',
        'editable': True,
        'is_sensitive': True
    },
    {
        'key': 'pay.wxpay.APIv3_key',
        'value_type': 'string',
        'description': '微信支付APIv3密钥',
        'editable': True,
        'is_sensitive': True
    },
    {
        'key': 'pay.wxpay.appSecret',
        'value_type': 'string',
        'description': '微信支付appSecret',
        'editable': True,
        'is_sensitive': True
    },
    
    # ==================== Google/Gemini 配置 ====================
    {
        'key': 'llm.google.api_key',
        'value_type': 'string',
        'description': 'Google Gemini API Key',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'llm.google.gemini_base_url',
        'value_type': 'string',
        'description': 'Gemini API 基础URL',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    
    # ==================== 七牛云存储配置 ====================
    {
        'key': 'file_storage.qiniu.access_key',
        'value_type': 'string',
        'description': '七牛云 Access Key',
        'editable': True,
        'is_sensitive': True
    },
    {
        'key': 'file_storage.qiniu.secret_key',
        'value_type': 'string',
        'description': '七牛云 Secret Key',
        'editable': True,
        'is_sensitive': True
    },
    {
        'key': 'file_storage.qiniu.bucket_name',
        'value_type': 'string',
        'description': '七牛云存储空间名称',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'file_storage.qiniu.cdn_domain',
        'value_type': 'string',
        'description': '七牛云 CDN 加速域名',
        'editable': True,
        'is_sensitive': False
    },
    
    # ==================== Sentry 配置 ====================
    {
        'key': 'sentry.dsn',
        'value_type': 'string',
        'description': 'Sentry DSN（含 token）',
        'editable': True,
        'is_sensitive': True
    },
    {
        'key': 'sentry.environment',
        'value_type': 'string',
        'description': 'Sentry 环境标识',
        'editable': True,
        'is_sensitive': False
    },
]


def get_default_config_by_key(key: str) -> Dict[str, Any]:
    """
    根据 key 获取默认配置定义
    
    Args:
        key: 配置键，如 'task_queue.max_retry_count'
        
    Returns:
        配置定义字典，未找到返回 None
    """
    for config in DEFAULT_CONFIGS:
        if config['key'] == key:
            return config
    return None


def get_all_config_keys() -> List[str]:
    """
    获取所有默认配置的 key 列表
    """
    return [config['key'] for config in DEFAULT_CONFIGS]


def get_quick_configs() -> List[Dict[str, Any]]:
    """
    获取快速配置项列表（用于快速配置弹窗）
    
    Returns:
        快速配置项列表，每项包含 key, description, is_sensitive
    """
    return [
        {
            'key': config['key'],
            'description': config['description'],
            'is_sensitive': config.get('is_sensitive', False)
        }
        for config in DEFAULT_CONFIGS
        if config.get('quick_config', False)
    ]


def init_default_configs(env: str, updated_by: int = None) -> int:
    """
    初始化默认配置到数据库
    仅插入数据库中不存在的配置
    
    Args:
        env: 环境标识
        updated_by: 操作人 user_id
        
    Returns:
        新插入的配置数量
    """
    from model.system_config import SystemConfigModel
    from config.config_util import get_config_value
    
    inserted_count = 0
    
    for config_def in DEFAULT_CONFIGS:
        key = config_def['key']
        
        # 检查是否已存在
        existing = SystemConfigModel.get_by_key(env, key)
        if existing:
            continue
        
        # 从 YAML 获取当前值
        keys = key.split('.')
        yaml_value = get_config_value(*keys, default=None)
        
        if yaml_value is None:
            continue
        
        # 转换值为字符串
        value_type = config_def['value_type']
        if value_type == 'bool':
            config_value = 'true' if yaml_value else 'false'
        elif value_type == 'json':
            import json
            config_value = json.dumps(yaml_value, ensure_ascii=False)
        else:
            config_value = str(yaml_value)
        
        # 插入配置
        SystemConfigModel.create(
            env=env,
            config_key=key,
            config_value=config_value,
            value_type=value_type,
            description=config_def['description'],
            editable=1 if config_def['editable'] else 0,
            is_sensitive=1 if config_def['is_sensitive'] else 0,
            updated_by=updated_by
        )
        inserted_count += 1
    
    return inserted_count
