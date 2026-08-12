"""
Default configurations for dynamic config system
默认可热更新配置定义
"""
from typing import List, Dict, Any

# 默认配置列表
# 每个配置包含：key, value_type, description, editable, is_sensitive
# 可选字段：quick_config - 标记是否为快速配置项（在快速配置弹窗中显示）
DEFAULT_CONFIGS: List[Dict[str, Any]] = [
    # ==================== 版本空间配置 ====================
    {
        'key': 'edition.shared_space',
        'value_type': 'bool',
        'description': '商业版是否使用共享空间模式（true=所有用户共享数据，false=按用户隔离）',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },

    # ==================== 用户注册配置 ====================
    {
        'key': 'user_registration.require_admin_approval',
        'value_type': 'bool',
        'description': '用户注册后是否需要管理员审核才能登录',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'email.enabled',
        'value_type': 'bool',
        'description': '是否启用邮箱注册/登录功能（关闭后仅支持手机号）',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'captcha.enabled',
        'value_type': 'bool',
        'description': '是否启用阿里云 CAPTCHA 2.0 人机验证（启用后发送邮箱验证码前需通过验证）',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },

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
    {
        'key': 'upload.max_video_size_mb',
        'value_type': 'int',
        'description': 'Agent 对话模式上传视频最大大小限制（MB）',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'upload.max_video_duration_seconds',
        'value_type': 'int',
        'description': 'Agent 对话模式上传视频最大时长限制（秒），超时长的视频将被截断',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'upload.max_audio_size_mb',
        'value_type': 'int',
        'description': 'Agent 对话模式上传音频最大大小限制（MB）',
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
        'key': 'timeout.sync_request_timeout',
        'value_type': 'int',
        'description': '同步请求超时时间（秒），用于火山引擎等同步接口',
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

    # ---- test_mode 行为开关 ----
    {
        'key': 'test_mode.inject_failure_rate',
        'value_type': 'int',
        'description': '失败注入概率(0-100)，0=不注入（Phase3 错误注入用）',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'test_mode.inject_failure_scenario',
        'value_type': 'string',
        'description': '失败注入场景，如 submit/poll/timeout（Phase3 错误注入用）',
        'editable': True,
        'is_sensitive': False
    },

    # ---- test_mode.mock_images 扩展 ----
    {
        'key': 'test_mode.mock_images.comfyui_text_to_image',
        'value_type': 'string',
        'description': 'ComfyUI 工具直调文生图预设URL',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'test_mode.mock_images.comfyui_image_edit',
        'value_type': 'string',
        'description': 'ComfyUI 工具直调图片编辑预设URL',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'test_mode.mock_images.grid_image',
        'value_type': 'string',
        'description': '四宫格整图预设URL(2x2真实图)',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'test_mode.mock_images.multi_angle_front',
        'value_type': 'string',
        'description': '多角度-正面图预设URL',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'test_mode.mock_images.multi_angle_side',
        'value_type': 'string',
        'description': '多角度-侧面图预设URL',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'test_mode.mock_images.multi_angle_back',
        'value_type': 'string',
        'description': '多角度-背面图预设URL',
        'editable': True,
        'is_sensitive': False
    },

    # ---- test_mode.mock_videos 扩展 ----
    {
        'key': 'test_mode.mock_videos.digital_human',
        'value_type': 'string',
        'description': '数字人预设视频URL',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'test_mode.mock_videos.face_mask',
        'value_type': 'string',
        'description': '人脸遮盖预设视频URL（必须本地真实mp4）',
        'editable': True,
        'is_sensitive': False
    },

    # ---- test_mode.mock_audio 扩展 ----
    {
        'key': 'test_mode.mock_audio.tts',
        'value_type': 'string',
        'description': 'Index TTS 预设音频URL',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'test_mode.mock_audio.character_audio',
        'value_type': 'string',
        'description': 'RunningHub 角色音频预设URL',
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
    {
        'key': 'image.max_retry_count',
        'value_type': 'int',
        'description': '图片生成失败后自动重试次数（ComfyUI返回FAILED时自动重新提交，0=不重试）',
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
        'description': 'RunningHub 最大并发槽位数量，该值根据runninghub账号的 并发数决定，可以查看 https://www.runninghub.cn/vip-rights/2 查看并发数，注意，必须支持api调用的套餐才能使用 26年3月 基础版为1 专业版为3 专业Plus版为5 Max 为20',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'runninghub.upstream_congest_retry_delay',
        'value_type': 'int',
        'description': 'RunningHub 上游并发超限(api queue limit reached / TASK_QUEUE_MAXED 等)时的自动重试延迟秒数，命中即不消耗用户重试次数、不退算力，仅延迟后重新排队提交。默认30秒。',
        'editable': True,
        'is_sensitive': False
    },

    {
        'key': 'pipeline.seedance_face_mask_enabled',
        'value_type': 'bool',
        'description': '是否启用 Seedance 2.0 / 2.0 Fast 图片和视频输入的人脸遮盖前置处理',
        'editable': True,
        'is_sensitive': False,
        'quick_config': False
    },
    {
        'key': 'pipeline.h3_prompt_optimize_enabled',
        'value_type': 'bool',
        'description': '是否在 MiniMax H3 图生视频提交前按 I2VA/FL2VA 规范优化提示词',
        'editable': True,
        'is_sensitive': False,
        'quick_config': False
    },
    {
        'key': 'pipeline.h3_prompt_optimize_model',
        'value_type': 'string',
        'description': 'H3 提示词优化使用的聊天模型名；空则回退 deepseek-v4-flash',
        'editable': True,
        'is_sensitive': False,
        'quick_config': False
    },
    {
        'key': 'pipeline.h3_prompt_optimize_vendor_id',
        'value_type': 'int',
        'description': 'H3 提示词优化使用的供应商 ID；0 或空则按模型名路由',
        'editable': True,
        'is_sensitive': False,
        'quick_config': False
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

    # ==================== 智剧通配置 ====================
    {
        'key': 'zjt.token',
        'value_type': 'string',
        'description': '智剧通 API Token',
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

    # ==================== 火山引擎海外版配置 ====================
    {
        'key': 'volcengine_oversea.api_key',
        'value_type': 'string',
        'description': '火山引擎海外版 API Key（Seedream/Seedance 海外版）',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'volcengine_oversea.base_url',
        'value_type': 'string',
        'description': '火山引擎海外版 API 基础 URL（代码自动拼接 /api/v3）',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },

    # ==================== kkidc 网关配置 ====================
    {
        'key': 'kkidc.api_key',
        'value_type': 'string',
        'description': 'kkidc 网关 API Key（Seedance 系列视频）',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'kkidc.base_url',
        'value_type': 'string',
        'description': 'kkidc API 基础 URL（默认 https://ai-api.kkidc.com/v1）',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },

    # ==================== huimengi 网关配置 ====================
    {
        'key': 'huimengi.api_key',
        'value_type': 'string',
        'description': 'huimengi 网关 API Key（Seedance 2.0 系列视频）',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'huimengi.base_url',
        'value_type': 'string',
        'description': 'huimengi API 基础 URL（默认 https://api.huimengi.com）',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },

    # ==================== API 聚合站配置（部分兼容comfly 等中转站）====================
    {
        'key': 'api_aggregator.site_0.api_key',
        'value_type': 'string',
        'description': 'YWAPI 官方站点 API Key',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_1.base_url',
        'value_type': 'string',
        'description': 'API 聚合站站点1基础URL',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_1.api_key',
        'value_type': 'string',
        'description': 'API 聚合站站点1 API Key',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_1.name',
        'value_type': 'string',
        'description': 'API 聚合站站点1名称',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_2.base_url',
        'value_type': 'string',
        'description': 'API 聚合站站点2基础URL',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_2.api_key',
        'value_type': 'string',
        'description': 'API 聚合站站点2 API Key',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_2.name',
        'value_type': 'string',
        'description': 'API 聚合站站点2名称',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_3.base_url',
        'value_type': 'string',
        'description': 'API 聚合站站点3基础URL',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_3.api_key',
        'value_type': 'string',
        'description': 'API 聚合站站点3 API Key',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_3.name',
        'value_type': 'string',
        'description': 'API 聚合站站点3名称',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'api_aggregator.site_4.base_url',
        'value_type': 'string',
        'description': 'API 聚合站站点4基础URL',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_4.api_key',
        'value_type': 'string',
        'description': 'API 聚合站站点4 API Key',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_4.name',
        'value_type': 'string',
        'description': 'API 聚合站站点4名称',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_5.base_url',
        'value_type': 'string',
        'description': 'API 聚合站站点5基础URL',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_5.api_key',
        'value_type': 'string',
        'description': 'API 聚合站站点5 API Key',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'api_aggregator.site_5.name',
        'value_type': 'string',
        'description': 'API 聚合站站点5名称',
        'editable': True,
        'is_sensitive': False,
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

    # ==================== Claude 配置 ====================
    {
        'key': 'llm.claude.api_key',
        'value_type': 'string',
        'description': 'Claude API Key',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'llm.claude.base_url',
        'value_type': 'string',
        'description': 'Claude API 基础URL（默认 https://api.jiekou.ai/openai）',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },

    # ==================== Qwen 配置 ====================
    {
        'key': 'llm.qwen.api_key',
        'value_type': 'string',
        'description': 'Qwen API Key（阿里通义千问）',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'llm.qwen.base_url',
        'value_type': 'string',
        'description': 'Qwen API 基础URL',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },

    # ==================== Ollama 配置 ====================
    {
        'key': 'llm.ollama.enabled',
        'value_type': 'bool',
        'description': '是否启用 Ollama 本地模型',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'llm.ollama.base_url',
        'value_type': 'string',
        'description': 'Ollama 服务地址',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'llm.ollama.temperature',
        'value_type': 'float',
        'description': 'Ollama 温度参数 (0.0-2.0)',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'llm.ollama.top_p',
        'value_type': 'float',
        'description': 'Ollama 核采样概率 (0.0-1.0)',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'llm.ollama.top_k',
        'value_type': 'int',
        'description': 'Ollama Top-K 采样',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'llm.ollama.min_p',
        'value_type': 'float',
        'description': 'Ollama 最小概率阈值',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'llm.ollama.presence_penalty',
        'value_type': 'float',
        'description': 'Ollama 存在惩罚',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'llm.ollama.repetition_penalty',
        'value_type': 'float',
        'description': 'Ollama 重复惩罚',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },
    {
        'key': 'llm.ollama.enable_thinking',
        'value_type': 'bool',
        'description': 'Ollama 是否启用思维链（部分模型支持）',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },

    # ==================== DeepSeek 配置 ====================
    {
        'key': 'llm.deepseek.api_key',
        'value_type': 'string',
        'description': 'DeepSeek API Key',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'llm.deepseek.base_url',
        'value_type': 'string',
        'description': 'DeepSeek API 基础URL（默认 https://api.deepseek.com）',
        'editable': True,
        'is_sensitive': False,
        'quick_config': True
    },

    # ==================== Agnes 配置 ====================
    {
        'key': 'llm.agnes.api_key',
        'value_type': 'string',
        'description': 'Agnes AI API Key',
        'editable': True,
        'is_sensitive': True,
        'quick_config': True
    },
    {
        'key': 'llm.agnes.base_url',
        'value_type': 'string',
        'description': 'Agnes API 基础URL（默认 https://api.agnes-ai.cn/v1）',
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

    # ==================== 七牛云长期存储配置（AI Tools 结果同步到 CDN）====================
    {
        'key': 'file_storage.qiniu_long_term.access_key',
        'value_type': 'string',
        'description': '七牛云长期存储 Access Key',
        'editable': True,
        'is_sensitive': True
    },
    {
        'key': 'file_storage.qiniu_long_term.secret_key',
        'value_type': 'string',
        'description': '七牛云长期存储 Secret Key',
        'editable': True,
        'is_sensitive': True
    },
    {
        'key': 'file_storage.qiniu_long_term.bucket_name',
        'value_type': 'string',
        'description': '七牛云长期存储空间名称',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'file_storage.qiniu_long_term.cdn_domain',
        'value_type': 'string',
        'description': '七牛云长期存储 CDN 加速域名',
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
    
    # ==================== 媒体文件缓存配置 ====================
    {
        'key': 'media_cache.enabled',
        'value_type': 'bool',
        'description': '是否启用媒体文件缓存',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'media_cache.cache_dir',
        'value_type': 'string',
        'description': '缓存目录（相对于项目根目录）',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'media_cache.max_days',
        'value_type': 'int',
        'description': '文件保留天数（0=不限制）',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'media_cache.max_size_gb',
        'value_type': 'int',
        'description': '最大缓存容量GB（0=不限制）',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'media_cache.cleanup_on_startup',
        'value_type': 'bool',
        'description': '启动时执行清理',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'media_cache.cleanup_interval_hours',
        'value_type': 'int',
        'description': '定时清理间隔（小时）',
        'editable': True,
        'is_sensitive': False
    },

    # ==================== CDN 存储配置（AI Tools 专用，已迁移到 file_storage.qiniu_long_term）====================

    # ==================== 同步任务进程池配置 ====================
    {
        'key': 'sync_task.max_workers',
        'value_type': 'int',
        'description': '同步任务进程池最大并发数',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'sync_task.check_interval',
        'value_type': 'int',
        'description': '同步任务结果检查间隔（秒）',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'sync_task.stale_detection_enabled',
        'value_type': 'bool',
        'description': '是否启用同步任务 stale future 检测与 worker 回收',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'sync_task.stale_timeout.seedream5_volcengine_v1',
        'value_type': 'int',
        'description': 'Seedream 国内同步任务 stale 超时时间（秒），0 表示禁用',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'sync_task.stale_timeout.seedream5_volcengine_oversea_v1',
        'value_type': 'int',
        'description': 'Seedream 海外同步任务 stale 超时时间（秒），0 表示禁用',
        'editable': True,
        'is_sensitive': False
    },

    # ==================== 剧本分段拆分多 worker 配置 ====================
    {
        'key': 'script_split.worker_total',
        'value_type': 'int',
        'description': '剧本分段拆分独立 worker 进程数；0=主调度器单进程(兼容旧行为)，>0=由 N 个独立 worker 进程分片接管(id MOD N = index)。⚠️修改后需重启服务生效：运行中的 worker 进程数在启动时固定，热更新 DB 不会自动增减进程',
        'editable': True,
        'is_sensitive': False
    },

    # ==================== 每日签到配置 ====================
    {
        'key': 'checkin.enabled',
        'value_type': 'bool',
        'description': '是否启用每日签到功能',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'checkin.base_reward',
        'value_type': 'int',
        'description': '每日签到基础奖励算力值',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'checkin.streak_bonus_enabled',
        'value_type': 'bool',
        'description': '是否启用连续签到额外奖励',
        'editable': True,
        'is_sensitive': False
    },
    {
        'key': 'checkin.streak_bonus_config',
        'value_type': 'json',
        'description': '连续签到奖励配置，格式: {"3": 5, "7": 15, "14": 30, "30": 50}',
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


def should_skip_history(config_key: str) -> bool:
    """
    判断某配置项是否应跳过 system_config_history 记录。

    用于纯运行态配置（如密钥池的 fail_count/circuit_status/next_probe_at/last_used_at），
    这些项更新频繁、无审计价值，写历史会污染审计日志。

    判定规则：满足以下任一即跳过
      1. default_configs 中该 key 定义了 'skip_history': True
      2. key 匹配运行态前缀模式（如 runninghub.key.{N}.fail_count 等）
         —— 兼容未在 default_configs 预注册的密钥槽位 (N=2~10)

    Args:
        config_key: 配置键，如 'runninghub.key.3.fail_count'

    Returns:
        True 表示跳过历史记录
    """
    # 规则1：default_configs 显式标记
    config_def = get_default_config_by_key(config_key)
    if config_def and config_def.get('skip_history', False):
        return True

    # 规则2：运行态前缀模式（兼容未预注册的密钥槽位）
    # 匹配 runninghub.key.{N}.(fail_count|circuit_status|next_probe_at|last_used_at|last_congested_at)
    rt_suffixes = (
        '.fail_count', '.circuit_status', '.next_probe_at',
        '.last_used_at', '.last_congested_at',
    )
    if config_key.startswith('runninghub.key.') and config_key.endswith(rt_suffixes):
        return True

    return False


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
