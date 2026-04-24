/**
 * 管理后台 JavaScript
 */

// ==================== 服务商配置定义 ====================

const CATEGORY_LABELS = {
    llm: '大模型',
    image: '生图模型',
    video: '生视频模型',
    other: '其他服务'
};

const CATEGORY_DESCRIPTIONS = {
    llm: '选择一个或多个大模型服务商',
    image: '选择一个或多个生图服务商',
    video: '选择一个或多个生视频服务商',
    other: '选择其他推荐的 AI 服务'
};

/**
 * 服务商配置定义
 * 每个服务商包含：基本信息、分类、字段定义、后端配置键映射
 */
const PROVIDER_DEFINITIONS = [
    // ===== 大模型服务商 =====
    {
        id: 'huoshan',
        name: '火山引擎',
        description: '火山引擎 Doubao 大模型，高性能、低延迟',
        category: 'llm',
        icon: '🔥',
        docUrl: 'https://console.volcengine.com/ark',
        lazyRecommended: false,
        displayOrder: 3,
        baseName: 'huoshan',
        isOfficialAPI: false,
        impacts: ['剧本创作', 'AI对话'],
        fields: [
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true, helpText: '从火山引擎控制台获取' }
        ],
        configKeyMap: { api_key: 'volcengine.api_key' },
        testEndpoint: null
    },
    {
        id: 'ywapi',
        name: '智剧通API',
        description: '智剧通API 官方平台，支持多种模型和服务',
        category: 'llm',
        icon: '☁️',
        docUrl: 'https://yw.perseids.cn/register?aff=hE0h',
        lazyRecommended: true,
        displayOrder: 2,
        baseName: 'ywapi',
        isOfficialAPI: true,
        impacts: ['剧本创作', 'AI对话'],
        fields: [
            { id: 'name', label: '站点名称', type: 'text', placeholder: '智剧通API', required: false, readOnly: true, defaultValue: '智剧通API' },
            { id: 'base_url', label: 'Base URL', type: 'text', placeholder: 'https://yw.perseids.cn', required: true, readOnly: true, defaultValue: 'https://yw.perseids.cn' },
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_0.name', base_url: 'api_aggregator.site_0.base_url', api_key: 'api_aggregator.site_0.api_key' },
        testEndpoint: null
    },
    {
        id: 'google',
        name: 'Google/Gemini',
        description: 'Google Gemini 大模型，支持多种 AI 能力',
        category: 'llm',
        icon: '✨',
        docUrl: 'https://jiekou.ai/user/register?invited_code=119T5V',
        lazyRecommended: false,
        displayOrder: 5,
        baseName: 'google',
        isOfficialAPI: false,
        impacts: ['剧本创作', 'AI对话', '剧本拆分'],
        fields: [
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 Google API Key', required: true, helpText: '支持第三方代理服务' },
            { id: 'base_url', label: 'Base URL (可选)', type: 'url', placeholder: 'https://api.jiekou.ai', required: false, helpText: '可使用第三方代理服务，留空使用默认值' }
        ],
        configKeyMap: { api_key: 'llm.google.api_key', base_url: 'llm.google.gemini_base_url' },
        testEndpoint: 'google'
    },
    {
        id: 'claude',
        name: 'Claude',
        description: 'Anthropic Claude 大模型，擅长长文本推理与创作',
        category: 'llm',
        icon: '🟣',
        docUrl: 'https://jiekou.ai/user/register?invited_code=119T5V',
        lazyRecommended: false,
        displayOrder: 6,
        baseName: 'claude',
        isOfficialAPI: false,
        impacts: ['剧本创作', 'AI对话', '剧本拆分'],
        fields: [
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 Claude API Key', required: true, helpText: '支持第三方代理服务' },
            { id: 'base_url', label: 'Base URL (可选)', type: 'url', placeholder: 'https://api.jiekou.ai/openai', required: false, helpText: '可使用第三方代理服务，留空使用默认值' }
        ],
        configKeyMap: { api_key: 'llm.claude.api_key', base_url: 'llm.claude.base_url' },
        testEndpoint: null
    },
    {
        id: 'qwen',
        name: 'Qwen',
        description: '通义千问大模型，阿里云百炼平台',
        category: 'llm',
        icon: '🧠',
        docUrl: 'https://dashscope.console.aliyun.com/apiKey',
        lazyRecommended: true,
        displayOrder: 1,
        baseName: 'qwen',
        isOfficialAPI: false,
        impacts: ['剧本创作', 'AI对话', '剧本拆分'],
        fields: [
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 Qwen API Key', required: true },
            { id: 'base_url', label: 'Base URL (可选)', type: 'url', placeholder: 'https://dashscope.aliyuncs.com/compatible-mode/v1', required: false, helpText: '可使用第三方代理服务，留空使用默认值' }
        ],
        configKeyMap: { api_key: 'llm.qwen.api_key', base_url: 'llm.qwen.base_url' },
        testEndpoint: 'qwen'
    },

    // ===== 生图服务商 =====
    {
        id: 'ywapi_image',
        name: '智剧通API',
        description: '智剧通API 生图服务',
        category: 'image',
        icon: '☁️',
        docUrl: 'https://yw.perseids.cn/register?aff=hE0h',
        lazyRecommended: true,
        displayOrder: 2,
        baseName: 'ywapi',
        isOfficialAPI: true,
        impacts: ['Nano Banana图片编辑'],
        fields: [
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true }
        ],
        configKeyMap: { api_key: 'api_aggregator.site_0.api_key' },
        testEndpoint: null,
        _sharedWith: 'ywapi'
    },
    {
        id: 'duomi',
        name: '多米',
        description: '多米 AI 生图平台，高质量图像生成',
        category: 'image',
        icon: '🎨',
        docUrl: 'https://duomiapi.com/user/register?cps=U4GgW1Fx',
        lazyRecommended: false,
        displayOrder: 4,
        baseName: 'duomi',
        isOfficialAPI: false,
        impacts: ['Nano Banana图片编辑', 'Sora2/Kling/Veo3视频生成'],
        fields: [
            { id: 'token', label: 'Token', type: 'text', placeholder: '请输入 Duomi API Token', required: true, helpText: '获取方式：快速注册' }
        ],
        configKeyMap: { token: 'duomi.token' },
        testEndpoint: null
    },
    {
        id: 'huoshan_image',
        name: '火山引擎',
        description: '火山引擎 AI 生图，支持文生图、图生图',
        category: 'image',
        icon: '🔥',
        docUrl: 'https://console.volcengine.com/ark',
        lazyRecommended: true,
        displayOrder: 1,
        baseName: 'huoshan',
        isOfficialAPI: false,
        impacts: ['Seedream 5.0 文生图'],
        fields: [
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true, helpText: '从火山引擎控制台获取' }
        ],
        configKeyMap: { api_key: 'volcengine.api_key' },
        testEndpoint: null,
        _sharedWith: 'huoshan'
    },
    {
        id: 'site_1_image',
        name: '聚合站 1',
        description: 'API 聚合站点 1，支持多种生图模型',
        category: 'image',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 10,
        baseName: 'site_1',
        isOfficialAPI: false,
        impacts: ['生图模型'],
        fields: [
            { id: 'name', label: '站点名称', type: 'text', placeholder: '如：聚合站1', required: false, helpText: '用于标识该聚合站点' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_1.name', base_url: 'api_aggregator.site_1.base_url', api_key: 'api_aggregator.site_1.api_key' },
        testEndpoint: null
    },
    {
        id: 'site_2_image',
        name: '聚合站 2',
        description: 'API 聚合站点 2，支持多种生图模型',
        category: 'image',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 11,
        baseName: 'site_2',
        isOfficialAPI: false,
        impacts: ['生图模型'],
        fields: [
            { id: 'name', label: '站点名称', type: 'text', placeholder: '如：聚合站2', required: false, helpText: '用于标识该聚合站点' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_2.name', base_url: 'api_aggregator.site_2.base_url', api_key: 'api_aggregator.site_2.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },
    {
        id: 'site_3_image',
        name: '聚合站 3',
        description: 'API 聚合站点 3，支持多种生图模型',
        category: 'image',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 12,
        baseName: 'site_3',
        isOfficialAPI: false,
        impacts: ['生图模型'],
        fields: [
            { id: 'name', label: '站点名称', type: 'text', placeholder: '如：聚合站3', required: false, helpText: '用于标识该聚合站点' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_3.name', base_url: 'api_aggregator.site_3.base_url', api_key: 'api_aggregator.site_3.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },
    {
        id: 'site_4_image',
        name: '聚合站 4',
        description: 'API 聚合站点 4，支持多种生图模型',
        category: 'image',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 13,
        baseName: 'site_4',
        isOfficialAPI: false,
        impacts: ['生图模型'],
        fields: [
            { id: 'name', label: '站点名称', type: 'text', placeholder: '如：聚合站4', required: false, helpText: '用于标识该聚合站点' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_4.name', base_url: 'api_aggregator.site_4.base_url', api_key: 'api_aggregator.site_4.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },
    {
        id: 'site_5_image',
        name: '聚合站 5',
        description: 'API 聚合站点 5，支持多种生图模型',
        category: 'image',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 14,
        baseName: 'site_5',
        isOfficialAPI: false,
        impacts: ['生图模型'],
        fields: [
            { id: 'name', label: '站点名称', type: 'text', placeholder: '如：聚合站5', required: false, helpText: '用于标识该聚合站点' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_5.name', base_url: 'api_aggregator.site_5.base_url', api_key: 'api_aggregator.site_5.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },

    // ===== 生视频服务商 =====
    {
        id: 'duomi_video',
        name: '多米',
        description: '多米 AI 生视频平台',
        category: 'video',
        icon: '🎨',
        docUrl: 'https://duomiapi.com/user/register?cps=U4GgW1Fx',
        lazyRecommended: true,
        displayOrder: 1,
        baseName: 'duomi',
        isOfficialAPI: false,
        impacts: ['Sora2/Kling/Veo3视频生成'],
        fields: [
            { id: 'token', label: 'Token', type: 'text', placeholder: '请输入 Duomi API Token', required: true }
        ],
        configKeyMap: { token: 'duomi.token' },
        testEndpoint: null,
        _sharedWith: 'duomi'
    },
    {
        id: 'runninghub',
        name: 'RunningHub',
        description: 'RunningHub AI 生视频服务',
        category: 'video',
        icon: '🚀',
        docUrl: 'https://www.runninghub.cn/?inviteCode=quacwnzc',
        lazyRecommended: true,
        displayOrder: 2,
        baseName: 'runninghub',
        isOfficialAPI: false,
        impacts: ['LTX2.0视频', 'Wan2.2视频', '数字人合成', '相机多角度控制'],
        fields: [
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '请输入 RunningHub API Key', required: true, helpText: '获取方式：快速注册' }
        ],
        configKeyMap: { api_key: 'runninghub.api_key' },
        testEndpoint: null
    },
    {
        id: 'ywapi_video',
        name: '智剧通API',
        description: '智剧通API 生视频服务',
        category: 'video',
        icon: '☁️',
        docUrl: 'https://yw.perseids.cn/register?aff=hE0h',
        lazyRecommended: true,
        displayOrder: 3,
        baseName: 'ywapi',
        isOfficialAPI: true,
        impacts: ['生视频模型'],
        fields: [
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true }
        ],
        configKeyMap: { api_key: 'api_aggregator.site_0.api_key' },
        testEndpoint: null,
        _sharedWith: 'ywapi'
    },
    {
        id: 'huoshan_video',
        name: '火山引擎',
        description: '火山引擎 AI 生视频，支持文生视频',
        category: 'video',
        icon: '🔥',
        docUrl: 'https://console.volcengine.com/ark',
        lazyRecommended: false,
        displayOrder: 4,
        baseName: 'huoshan',
        isOfficialAPI: false,
        impacts: ['Seedance 1.5 2.0 视频'],
        fields: [
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true, helpText: '从火山引擎控制台获取' }
        ],
        configKeyMap: { api_key: 'volcengine.api_key' },
        testEndpoint: null,
        _sharedWith: 'huoshan'
    },
    {
        id: 'site_1_video',
        name: '聚合站 1',
        description: 'API 聚合站点 1，支持多种生视频模型',
        category: 'video',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 10,
        baseName: 'site_1',
        isOfficialAPI: false,
        impacts: ['生视频模型'],
        fields: [
            { id: 'name', label: '站点名称', type: 'text', placeholder: '如：聚合站1', required: false, helpText: '用于标识该聚合站点' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_1.name', base_url: 'api_aggregator.site_1.base_url', api_key: 'api_aggregator.site_1.api_key' },
        testEndpoint: null
    },
    {
        id: 'site_2_video',
        name: '聚合站 2',
        description: 'API 聚合站点 2，支持多种生视频模型',
        category: 'video',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 11,
        baseName: 'site_2',
        isOfficialAPI: false,
        impacts: ['生视频模型'],
        fields: [
            { id: 'name', label: '站点名称', type: 'text', placeholder: '如：聚合站2', required: false, helpText: '用于标识该聚合站点' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_2.name', base_url: 'api_aggregator.site_2.base_url', api_key: 'api_aggregator.site_2.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },
    {
        id: 'site_3_video',
        name: '聚合站 3',
        description: 'API 聚合站点 3，支持多种生视频模型',
        category: 'video',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 12,
        baseName: 'site_3',
        isOfficialAPI: false,
        impacts: ['生视频模型'],
        fields: [
            { id: 'name', label: '站点名称', type: 'text', placeholder: '如：聚合站3', required: false, helpText: '用于标识该聚合站点' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_3.name', base_url: 'api_aggregator.site_3.base_url', api_key: 'api_aggregator.site_3.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },
    {
        id: 'site_4_video',
        name: '聚合站 4',
        description: 'API 聚合站点 4，支持多种生视频模型',
        category: 'video',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 13,
        baseName: 'site_4',
        isOfficialAPI: false,
        impacts: ['生视频模型'],
        fields: [
            { id: 'name', label: '站点名称', type: 'text', placeholder: '如：聚合站4', required: false, helpText: '用于标识该聚合站点' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_4.name', base_url: 'api_aggregator.site_4.base_url', api_key: 'api_aggregator.site_4.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },
    {
        id: 'site_5_video',
        name: '聚合站 5',
        description: 'API 聚合站点 5，支持多种生视频模型',
        category: 'video',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 14,
        baseName: 'site_5',
        isOfficialAPI: false,
        impacts: ['生视频模型'],
        fields: [
            { id: 'name', label: '站点名称', type: 'text', placeholder: '如：聚合站5', required: false, helpText: '用于标识该聚合站点' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', label: 'API Key', type: 'text', placeholder: '输入您的 API Key', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_5.name', base_url: 'api_aggregator.site_5.base_url', api_key: 'api_aggregator.site_5.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },

    // ===== 其他推荐服务 =====
    {
        id: 'vidu',
        name: 'Vidu',
        description: 'Vidu 视频生成平台',
        category: 'other',
        icon: '🎬',
        docUrl: 'https://platform.vidu.cn/api-keys',
        lazyRecommended: false,
        displayOrder: 1,
        baseName: 'vidu',
        isOfficialAPI: false,
        impacts: ['Vidu视频生成'],
        fields: [
            { id: 'token', label: 'Token', type: 'text', placeholder: '请输入 Vidu API Token', required: true, helpText: '获取方式：快速注册' }
        ],
        configKeyMap: { token: 'vidu.token' },
        testEndpoint: null
    }
];

// 构建 configKey -> { providerId, fieldId } 的反向映射
const CONFIG_KEY_TO_PROVIDER_FIELD = {};
PROVIDER_DEFINITIONS.forEach(provider => {
    Object.entries(provider.configKeyMap).forEach(([fieldId, configKey]) => {
        CONFIG_KEY_TO_PROVIDER_FIELD[configKey] = { providerId: provider.id, fieldId };
    });
});

const AdminApp = {
    data() {
        return {
            // 认证
            authToken: '',
            adminUser: null,

            // 版本号
            appVersion: '',

            // 当前页面
            currentPage: 'dashboard',
            
            // 仪表盘数据
            dashboard: {
                totalUsers: 0,
                activeWorkflows3d: 0,
                loading: true,
                monthlyActiveUsers: {
                    count: null,
                    year: null,
                    month: null,
                    loading: false
                }
            },
            
            // 用户列表
            users: {
                list: [],
                total: 0,
                page: 1,
                pageSize: 20,
                loading: false,
                keyword: '',
                statusFilter: '',
                roleFilter: ''
            },
            
            // 算力调整弹窗
            powerModal: {
                show: false,
                userId: null,
                userName: '',
                currentPower: 0,
                amount: 0,
                reason: '',
                loading: false
            },

            // 智剧通Token有效期调整弹窗
            zjtExpireModal: {
                show: false,
                userId: null,
                userName: '',
                currentExpireAt: null,
                currentExpireAtDisplay: '',
                newExpireAt: '',
                loading: false
            },
            zjtDatePicker: null,

            // 用户详情弹窗
            userDetailModal: {
                show: false,
                user: null,
                loading: false
            },
            
            // 系统配置列表
            config: {
                list: [],
                total: 0,
                page: 1,
                pageSize: 50,
                loading: false,
                keyword: '',
                initLoading: false,
                reloadLoading: false
            },
            
            // 配置编辑弹窗
            configEditModal: {
                show: false,
                configId: null,
                configKey: '',
                value: '',
                boolValue: false,
                valueType: 'string',
                description: '',
                isSensitive: false,
                loading: false
            },
            
            // 配置历史弹窗
            configHistoryModal: {
                show: false,
                configKey: '',
                list: [],
                loading: false
            },
            
            // 敏感配置值查看弹窗
            sensitiveValueModal: {
                show: false,
                configKey: '',
                value: ''
            },
            
            // 快速配置弹窗（两栏模式）
            quickConfigModal: {
                show: false,
                loading: false,
                activeCategory: 'llm',
                selectedProviderIds: [],
                providerFormData: {},    // { providerId: { fieldId: value } }
                originalValues: {},      // { providerId: { fieldId: originalValue } }
                testLoading: {},         // { providerId: boolean }
                testResults: {},         // { providerId: { success: boolean, message: string } }
                saveLoading: {},         // { providerId: boolean }
                leftPanelOpen: true
            },
            
            // 使用手册引导弹窗
            guideModal: {
                show: false
            },

            // 实现方管理
            implementations: {
                groups: [],  // 分组数据
                loading: false,
                keyword: '',
                updating: null  // 正在更新的实现方名称
            },

            // 实现方编辑弹窗
            implEditModal: {
                show: false,
                implementation: null,
                display_name: '',
                enabled: true,
                sort_order: 0,
                loading: false
            },

            // 实现方算力配置弹窗
            implPowerModal: {
                show: false,
                implementation: null,
                computing_power: 0,
                duration: null,
                loading: false,
                durationOptions: []  // 支持的时长选项
            },

            // 使用手册链接
            userManualUrl: 'https://bq3mlz1jiae.feishu.cn/wiki/W1h2wCK3mi1CgDk36LEcVqggnLe',
            
            // Toast消息
            toast: {
                show: false,
                message: '',
                type: 'success'
            },

            // 签到管理
            checkin: {
                enabled: false,
                baseReward: 10,
                streakBonusEnabled: false,
                streakBonuses: [], // { days, reward }
                loading: false
            },

            isCommunityEdition: false
        };
    },
    
    computed: {
        totalPages() {
            return Math.ceil(this.users.total / this.users.pageSize);
        },

        configTotalPages() {
            return Math.ceil(this.config.total / this.config.pageSize);
        },

        maskedPhone() {
            if (!this.adminUser || !this.adminUser.phone) return '';
            const phone = this.adminUser.phone;
            if (phone.length !== 11) return phone;
            return phone.substring(0, 3) + '****' + phone.substring(7);
        },

        filteredImplementationGroups() {
            let groups = this.implementations.groups;

            if (this.implementations.keyword) {
                const keyword = this.implementations.keyword.toLowerCase();
                groups = groups.map(group => ({
                    ...group,
                    implementations: group.implementations.filter(item =>
                        item.name.toLowerCase().includes(keyword) ||
                        item.display_name.toLowerCase().includes(keyword)
                    )
                })).filter(group => group.implementations.length > 0);
            }

            return groups;
        },

        minDate() {
            const today = new Date();
            const year = today.getFullYear();
            const month = String(today.getMonth() + 1).padStart(2, '0');
            const day = String(today.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        },

        // ===== 快速配置相关计算属性 =====

        providersByCategory() {
            const sortByOrder = (items) => [...items].sort((a, b) => (a.displayOrder || 999) - (b.displayOrder || 999));
            const result = {};
            Object.keys(CATEGORY_LABELS).forEach(cat => {
                result[cat] = sortByOrder(PROVIDER_DEFINITIONS.filter(p => p.category === cat));
            });
            return result;
        },

        lazyRecommendedProviderIds() {
            return PROVIDER_DEFINITIONS.filter(p => p.lazyRecommended).map(p => p.id);
        },

        selectedProvidersDetail() {
            // 按 baseName 分组，合并同组的字段和配置
            const groups = {};
            const fieldIds = {};
            const impactSets = {};

            this.quickConfigModal.selectedProviderIds.forEach(id => {
                const p = PROVIDER_DEFINITIONS.find(d => d.id === id);
                if (!p) return;
                const base = p.baseName || p.id;

                if (!groups[base]) {
                    groups[base] = { ...p, fields: [...p.fields], configKeyMap: { ...p.configKeyMap } };
                    fieldIds[base] = new Set(p.fields.map(f => f.id));
                    impactSets[base] = new Set(p.impacts || []);
                } else {
                    // 合并字段（按 field.id 去重）
                    p.fields.forEach(field => {
                        if (!fieldIds[base].has(field.id)) {
                            groups[base].fields.push(field);
                            groups[base].configKeyMap[field.id] = p.configKeyMap[field.id];
                            fieldIds[base].add(field.id);
                        }
                    });
                    // 合并 impacts
                    (p.impacts || []).forEach(imp => impactSets[base].add(imp));
                    groups[base].impacts = [...impactSets[base]];
                }
            });

            return Object.values(groups).sort((a, b) =>
                (a.displayOrder || 999) - (b.displayOrder || 999)
            );
        },

        categoryStatus() {
            const status = {};
            Object.keys(CATEGORY_LABELS).forEach(cat => { status[cat] = false; });
            this.quickConfigModal.selectedProviderIds.forEach(id => {
                const provider = PROVIDER_DEFINITIONS.find(p => p.id === id);
                if (provider && provider.category !== 'other') {
                    status[provider.category] = true;
                }
            });
            return status;
        },

        selectedCount() {
            return this.quickConfigModal.selectedProviderIds.length;
        },

        configuredCount() {
            return this.quickConfigModal.selectedProviderIds.filter(id => this.isProviderConfigured(id)).length;
        },

        configuredProgress() {
            const total = this.selectedCount;
            if (total === 0) return 0;
            return Math.round((this.configuredCount / total) * 100);
        },

        progressBarWidth() {
            return this.configuredProgress + '%';
        },

        // 暴露常量给模板
        categoryLabels() { return CATEGORY_LABELS; },
        categoryDescriptions() { return CATEGORY_DESCRIPTIONS; }
    },
    
    mounted() {
        this.initAuth();
        this.fetchServerConfig();
    },
    
    methods: {
        // 初始化智剧通日期选择器
        initZjtDatePicker() {
            const elem = document.getElementById("zjtExpireDatePicker");
            if (!elem) {
                console.error("zjtExpireDatePicker element not found");
                return;
            }

            // 如果已存在实例，先销毁
            if (this.zjtDatePicker) {
                this.zjtDatePicker.destroy();
                this.zjtDatePicker = null;
            }

            // 创建新实例，使用中文配置
            this.zjtDatePicker = flatpickr(elem, {
                dateFormat: "Y-m-d",
                allowInput: true,
                minDate: "today",
                disableMobile: true,
                locale: "zh",
                onChange: (selectedDates, dateStr) => {
                    this.zjtExpireModal.newExpireAt = dateStr || '';
                }
            });
        },
        // 获取服务器配置（版本号）
        async fetchServerConfig() {
            try {
                const response = await axios.get('/api/system/server-config');
                if (response.data.code === 0) {
                    this.appVersion = response.data.data.version || '';
                }
            } catch (error) {
                console.error('Failed to fetch server config:', error);
            }
        },

        // 初始化认证
        initAuth() {
            this.authToken = localStorage.getItem('auth_token') || '';
            
            if (!this.authToken) {
                this.showToast('请先登录', 'error');
                setTimeout(() => {
                    window.location.href = '/?login=1&redirect_url=/admin';
                }, 1500);
                return;
            }
            
            // 验证管理员权限
            this.verifyAdmin();
        },
        
        // 验证管理员权限
        async verifyAdmin() {
            try {
                const response = await axios.get('/api/admin/dashboard', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                
                if (response.data.code === 0) {
                    // 获取当前用户信息
                    const phone = localStorage.getItem('phone') || '';
                    this.adminUser = { phone };
                    
                    // 加载仪表盘数据
                    this.dashboard.totalUsers = response.data.data.total_users;
                    this.dashboard.activeWorkflows3d = response.data.data.active_workflows_3d;
                    this.dashboard.loading = false;

                    this.isCommunityEdition = response.data.data.is_community_edition || false;

                    // 默认加载用户列表
                    this.loadUsers();
                    
                    // 检查 URL 参数，是否需要自动打开快速配置
                    this.checkQuickConfigParam();
                }
            } catch (error) {
                console.error('Admin verification failed:', error);
                const detail = error?.response?.data?.detail || '';
                if (detail.includes('管理员权限') || error?.response?.status === 403) {
                    this.showToast('您没有管理员权限', 'error');
                    setTimeout(() => {
                        window.location.href = '/';
                    }, 1500);
                } else if (error?.response?.status === 401) {
                    this.showToast('登录已过期，请重新登录', 'error');
                    setTimeout(() => {
                        window.location.href = '/?login=1&redirect_url=/admin';
                    }, 1500);
                } else {
                    this.showToast('加载失败: ' + detail, 'error');
                }
            }
        },
        
        // 检查 URL 参数是否需要打开快速配置
        checkQuickConfigParam() {
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.get('quick_config') === '1') {
                // 切换到系统配置页面
                this.switchPage('config');
                // 延迟打开快速配置弹窗（等待配置列表加载）
                setTimeout(() => {
                    this.openQuickConfigModal();
                    // 显示欢迎提示
                    this.showToast('🎉 欢迎！您是系统首位管理员，请先完成快速配置', 'success');
                }, 500);
                // 清除 URL 参数
                window.history.replaceState({}, document.title, '/admin');
            }
        },
        
        // 切换页面
        switchPage(page) {
            this.currentPage = page;
            if (page === 'dashboard') {
                this.loadDashboard();
            } else if (page === 'users') {
                this.loadUsers();
            } else if (page === 'config') {
                this.loadConfigs();
            } else if (page === 'checkin') {
                this.loadCheckinConfig();
            } else if (page === 'implementations') {
                this.loadImplementations();
            }
        },
        
        // 加载仪表盘
        async loadDashboard() {
            this.dashboard.loading = true;
            try {
                const response = await axios.get('/api/admin/dashboard', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    this.dashboard.totalUsers = response.data.data.total_users;
                    this.dashboard.activeWorkflows3d = response.data.data.active_workflows_3d;
                }
            } catch (error) {
                console.error('Load dashboard failed:', error);
                this.showToast('加载仪表盘失败', 'error');
            } finally {
                this.dashboard.loading = false;
            }
        },

        // 加载月活跃用户
        async loadMonthlyActiveUsers() {
            this.dashboard.monthlyActiveUsers.loading = true;
            try {
                const response = await axios.get('/api/admin/dashboard/monthly-active-users', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    this.dashboard.monthlyActiveUsers.count = response.data.data.active_user_count;
                    this.dashboard.monthlyActiveUsers.year = response.data.data.year;
                    this.dashboard.monthlyActiveUsers.month = response.data.data.month;
                }
            } catch (error) {
                console.error('Load monthly active users failed:', error);
                this.showToast('查询月活跃用户失败', 'error');
            } finally {
                this.dashboard.monthlyActiveUsers.loading = false;
            }
        },

        // 加载用户列表
        async loadUsers() {
            this.users.loading = true;
            try {
                const params = {
                    page: this.users.page,
                    page_size: this.users.pageSize
                };
                
                if (this.users.keyword) {
                    params.keyword = this.users.keyword;
                }
                if (this.users.statusFilter !== '') {
                    params.status = parseInt(this.users.statusFilter);
                }
                if (this.users.roleFilter) {
                    params.role = this.users.roleFilter;
                }
                
                const response = await axios.get('/api/admin/users', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` },
                    params
                });
                
                if (response.data.code === 0) {
                    this.users.list = response.data.data.data;
                    this.users.total = response.data.data.total;
                }
            } catch (error) {
                console.error('Load users failed:', error);
                this.showToast('加载用户列表失败', 'error');
            } finally {
                this.users.loading = false;
            }
        },
        
        // 搜索用户
        searchUsers() {
            this.users.page = 1;
            this.loadUsers();
        },
        
        // 翻页
        goToPage(page) {
            if (page < 1 || page > this.totalPages) return;
            this.users.page = page;
            this.loadUsers();
        },
        
        // 查看用户详情
        async viewUserDetail(userId) {
            this.userDetailModal.loading = true;
            this.userDetailModal.show = true;
            
            try {
                const response = await axios.get(`/api/admin/users/${userId}`, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                
                if (response.data.code === 0) {
                    this.userDetailModal.user = response.data.data;
                }
            } catch (error) {
                console.error('Load user detail failed:', error);
                this.showToast('加载用户详情失败', 'error');
                this.userDetailModal.show = false;
            } finally {
                this.userDetailModal.loading = false;
            }
        },
        
        // 关闭用户详情弹窗
        closeUserDetailModal() {
            this.userDetailModal.show = false;
            this.userDetailModal.user = null;
        },
        
        // 更新用户状态
        async updateUserStatus(userId, currentStatus) {
            const newStatus = currentStatus === 1 ? 0 : 1;
            const action = newStatus === 0 ? '禁用' : '启用';
            
            if (!confirm(`确定要${action}该用户吗？`)) {
                return;
            }
            
            try {
                const response = await axios.put(`/api/admin/users/${userId}/status`, 
                    { status: newStatus },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                
                if (response.data.code === 0) {
                    this.showToast(`${action}成功`, 'success');
                    this.loadUsers();
                }
            } catch (error) {
                console.error('Update user status failed:', error);
                const detail = error?.response?.data?.detail || '操作失败';
                this.showToast(detail, 'error');
            }
        },
        
        // 更新用户角色
        async updateUserRole(userId, currentRole) {
            const newRole = currentRole === 'admin' ? 'user' : 'admin';
            const action = newRole === 'admin' ? '设为管理员' : '取消管理员';
            
            if (!confirm(`确定要${action}吗？`)) {
                return;
            }
            
            try {
                const response = await axios.put(`/api/admin/users/${userId}/role`, 
                    { role: newRole },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                
                if (response.data.code === 0) {
                    this.showToast(`${action}成功`, 'success');
                    this.loadUsers();
                }
            } catch (error) {
                console.error('Update user role failed:', error);
                const detail = error?.response?.data?.detail || '操作失败';
                this.showToast(detail, 'error');
            }
        },
        
        // 打开算力调整弹窗
        openPowerModal(user) {
            this.powerModal.userId = user.user_id;
            this.powerModal.userName = user.phone;
            this.powerModal.currentPower = user.computing_power || 0;
            this.powerModal.amount = 0;
            this.powerModal.reason = '';
            this.powerModal.show = true;
        },
        
        // 关闭算力调整弹窗
        closePowerModal() {
            this.powerModal.show = false;
            this.powerModal.userId = null;
            this.powerModal.userName = '';
            this.powerModal.currentPower = 0;
            this.powerModal.amount = 0;
            this.powerModal.reason = '';
        },
        
        // 提交算力调整
        async submitPowerAdjust() {
            if (!this.powerModal.reason.trim()) {
                this.showToast('请填写调整原因', 'error');
                return;
            }
            
            if (this.powerModal.amount === 0) {
                this.showToast('调整数量不能为0', 'error');
                return;
            }
            
            this.powerModal.loading = true;
            
            try {
                const response = await axios.post(
                    `/api/admin/users/${this.powerModal.userId}/power`,
                    {
                        amount: parseInt(this.powerModal.amount),
                        reason: this.powerModal.reason.trim()
                    },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                
                if (response.data.code === 0) {
                    const data = response.data.data;
                    this.showToast(`算力调整成功: ${data.old_power} → ${data.new_power}`, 'success');
                    this.closePowerModal();
                    this.loadUsers();
                }
            } catch (error) {
                console.error('Adjust power failed:', error);
                const detail = error?.response?.data?.detail || '调整失败';
                this.showToast(detail, 'error');
            } finally {
                this.powerModal.loading = false;
            }
        },

        // 切换用户智剧通Token启用状态
        async toggleZjtToken(user) {
            const newEnabled = !user.zjt_token_enabled;
            const action = newEnabled ? '启用' : '禁用';

            if (!confirm(`确定要${action}该用户的智剧通Token功能吗？`)) {
                return;
            }

            try {
                const response = await axios.put(
                    `/api/admin/users/${user.user_id}/zjt-token`,
                    { enabled: newEnabled },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );

                if (response.data.code === 0) {
                    // 启用时默认设置1年过期
                    if (newEnabled) {
                        const expireDate = new Date();
                        expireDate.setFullYear(expireDate.getFullYear() + 1);
                        const expireAt = expireDate.toISOString().split('T')[0];
                        await axios.put(
                            `/api/admin/users/${user.user_id}/zjt-token-expire`,
                            { expire_at: expireAt },
                            { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                        );
                    }
                    this.showToast(`智剧通Token已${action}，有效期1年`, 'success');
                    this.loadUsers();
                }
            } catch (error) {
                console.error('Toggle ZJT token failed:', error);
                const detail = error?.response?.data?.detail || `${action}失败`;
                this.showToast(detail, 'error');
            }
        },

        // 打开智剧通Token有效期调整弹窗
        async openZjtExpireModal(user) {
            this.zjtExpireModal.userId = user.user_id;
            this.zjtExpireModal.userName = user.phone;

            // 获取当前有效期配置
            try {
                const response = await axios.get(
                    `/api/admin/users/${user.user_id}/zjt-token`,
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );

                if (response.data.code === 0) {
                    const expireAt = response.data.data.zjt_token_expire_at;
                    this.zjtExpireModal.currentExpireAt = expireAt;

                    if (expireAt) {
                        // 格式化为日期字符串用于显示
                        const date = new Date(expireAt);
                        this.zjtExpireModal.currentExpireAtDisplay = date.toLocaleString('zh-CN');
                        // 默认新日期为当前过期日期
                        const year = date.getFullYear();
                        const month = String(date.getMonth() + 1).padStart(2, '0');
                        const day = String(date.getDate()).padStart(2, '0');
                        this.zjtExpireModal.newExpireAt = `${year}-${month}-${day}`;
                    } else {
                        this.zjtExpireModal.currentExpireAtDisplay = '永不过期';
                        this.zjtExpireModal.newExpireAt = '';
                    }
                }
            } catch (error) {
                console.error('Get ZJT token config failed:', error);
                this.zjtExpireModal.currentExpireAtDisplay = '未设置';
                this.zjtExpireModal.newExpireAt = '';
            }

            this.zjtExpireModal.show = true;

            // 等 DOM 渲染后再初始化 flatpickr
            setTimeout(() => {
                this.initZjtDatePicker();
                if (this.zjtDatePicker) {
                    if (this.zjtExpireModal.newExpireAt) {
                        this.zjtDatePicker.setDate(this.zjtExpireModal.newExpireAt);
                    } else {
                        this.zjtDatePicker.clear();
                    }
                }
            }, 100);
        },

        // 关闭智剧通Token有效期调整弹窗
        closeZjtExpireModal() {
            this.zjtExpireModal.show = false;
            this.zjtExpireModal.userId = null;
            this.zjtExpireModal.userName = '';
            this.zjtExpireModal.currentExpireAt = null;
            this.zjtExpireModal.currentExpireAtDisplay = '';
            this.zjtExpireModal.newExpireAt = '';
            this.zjtExpireModal.loading = false;
            if (this.zjtDatePicker) {
                this.zjtDatePicker.clear();
            }
        },

        // 提交智剧通Token有效期调整
        async submitZjtExpireAdjust() {
            if (!confirm('确定要调整智剧通Token有效期吗？')) {
                return;
            }

            this.zjtExpireModal.loading = true;

            try {
                const response = await axios.put(
                    `/api/admin/users/${this.zjtExpireModal.userId}/zjt-token-expire`,
                    { expire_at: this.zjtExpireModal.newExpireAt || null },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );

                if (response.data.code === 0) {
                    this.showToast(response.data.message || '智剧通Token有效期已调整', 'success');
                    this.closeZjtExpireModal();
                    this.loadUsers();
                }
            } catch (error) {
                console.error('Adjust ZJT expire failed:', error);
                const detail = error?.response?.data?.detail || '保存失败';
                this.showToast(detail, 'error');
            } finally {
                this.zjtExpireModal.loading = false;
            }
        },

        // 退出登录
        logout() {
            if (!confirm('确定要退出登录吗？')) {
                return;
            }
            
            localStorage.removeItem('auth_token');
            localStorage.removeItem('phone');
            localStorage.removeItem('user_id');
            localStorage.removeItem('admin_mode');
            window.location.href = '/';
        },
        
        // 显示Toast消息
        showToast(message, type = 'success') {
            this.toast.message = message;
            this.toast.type = type;
            this.toast.show = true;
            
            setTimeout(() => {
                this.toast.show = false;
            }, 3000);
        },
        
        // 格式化日期
        formatDate(dateStr) {
            if (!dateStr) return '-';
            const date = new Date(dateStr);
            return date.toLocaleString('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        },
        
        // 格式化手机号
        formatPhone(phone) {
            if (!phone || phone.length !== 11) return phone || '-';
            return phone.substring(0, 3) + '****' + phone.substring(7);
        },
        
        // ==================== 配置管理方法 ====================
        
        // 加载配置列表
        async loadConfigs() {
            this.config.loading = true;
            try {
                const params = {
                    page: this.config.page,
                    page_size: this.config.pageSize
                };
                
                if (this.config.keyword) {
                    params.keyword = this.config.keyword;
                }
                
                const response = await axios.get('/api/admin/config', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` },
                    params
                });
                
                if (response.data.code === 0) {
                    this.config.list = response.data.data.data;
                    this.config.total = response.data.data.total;
                }
            } catch (error) {
                console.error('Load configs failed:', error);
                this.showToast('加载配置列表失败', 'error');
            } finally {
                this.config.loading = false;
            }
        },
        
        // 搜索配置
        searchConfigs() {
            this.config.page = 1;
            this.loadConfigs();
        },
        
        // 配置翻页
        goToConfigPage(page) {
            if (page < 1 || page > this.configTotalPages) return;
            this.config.page = page;
            this.loadConfigs();
        },
        
        // 初始化配置
        async initConfigs() {
            if (!confirm('确定要初始化配置吗？这将从配置文件导入默认配置到数据库（仅新增，不覆盖已存在的配置）')) {
                return;
            }
            
            this.config.initLoading = true;
            try {
                const response = await axios.post('/api/admin/config/init', {}, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                
                if (response.data.code === 0) {
                    this.showToast(response.data.message, 'success');
                    this.loadConfigs();
                }
            } catch (error) {
                console.error('Init configs failed:', error);
                const detail = error?.response?.data?.detail || '初始化失败';
                this.showToast(detail, 'error');
            } finally {
                this.config.initLoading = false;
            }
        },
        
        // 刷新配置缓存
        async reloadConfigs() {
            this.config.reloadLoading = true;
            try {
                const response = await axios.post('/api/admin/config/reload', {}, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                
                if (response.data.code === 0) {
                    this.showToast('配置缓存已刷新', 'success');
                }
            } catch (error) {
                console.error('Reload configs failed:', error);
                const detail = error?.response?.data?.detail || '刷新失败';
                this.showToast(detail, 'error');
            } finally {
                this.config.reloadLoading = false;
            }
        },
        
        // ==================== 签到管理方法 ====================

        async loadCheckinConfig() {
            this.checkin.loading = true;
            try {
                const keys = [
                    'checkin.enabled',
                    'checkin.base_reward',
                    'checkin.streak_bonus_enabled',
                    'checkin.streak_bonus_config'
                ];
                // 逐个获取配置（或者通过搜索接口）
                const response = await axios.get('/api/admin/config', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` },
                    params: { keyword: 'checkin.', page: 1, page_size: 50 }
                });

                if (response.data.code === 0) {
                    const list = response.data.data.data || [];
                    const map = {};
                    list.forEach(item => { map[item.config_key] = item.config_value; });

                    this.checkin.enabled = String(map['checkin.enabled']).toLowerCase() === 'true';
                    this.checkin.baseReward = parseInt(map['checkin.base_reward'] || '10', 10);
                    this.checkin.streakBonusEnabled = String(map['checkin.streak_bonus_enabled']).toLowerCase() === 'true';

                    let streakConfig = map['checkin.streak_bonus_config'];
                    if (streakConfig) {
                        try {
                            const parsed = typeof streakConfig === 'string' ? JSON.parse(streakConfig) : streakConfig;
                            this.checkin.streakBonuses = Object.keys(parsed)
                                .map(k => ({ days: parseInt(k, 10), reward: parseInt(parsed[k], 10) }))
                                .sort((a, b) => a.days - b.days);
                        } catch (e) {
                            this.checkin.streakBonuses = [];
                        }
                    } else {
                        this.checkin.streakBonuses = [];
                    }
                }
            } catch (error) {
                console.error('Load checkin config failed:', error);
                this.showToast('加载签到配置失败', 'error');
            } finally {
                this.checkin.loading = false;
            }
        },

        addStreakBonus() {
            this.checkin.streakBonuses.push({ days: null, reward: null });
        },

        removeStreakBonus(index) {
            this.checkin.streakBonuses.splice(index, 1);
        },

        async saveCheckinConfig() {
            const configs = [];
            configs.push({ key: 'checkin.enabled', value: this.checkin.enabled ? 'true' : 'false' });
            configs.push({ key: 'checkin.base_reward', value: String(this.checkin.baseReward || 0) });
            configs.push({ key: 'checkin.streak_bonus_enabled', value: this.checkin.streakBonusEnabled ? 'true' : 'false' });

            const streakObj = {};
            for (const item of this.checkin.streakBonuses) {
                if (item.days && item.reward !== null && item.reward !== undefined) {
                    streakObj[String(item.days)] = item.reward;
                }
            }
            configs.push({ key: 'checkin.streak_bonus_config', value: JSON.stringify(streakObj) });

            this.checkin.loading = true;
            try {
                const response = await axios.put('/api/admin/config/batch',
                    { configs },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );

                if (response.data.code === 0) {
                    const errors = response.data.data.errors || [];
                    if (errors.length > 0) {
                        this.showToast(`部分配置保存失败: ${errors.join(', ')}`, 'error');
                    } else {
                        this.showToast('签到配置保存成功', 'success');
                    }
                }
            } catch (error) {
                console.error('Save checkin config failed:', error);
                const detail = error?.response?.data?.detail || '保存失败';
                this.showToast(detail, 'error');
            } finally {
                this.checkin.loading = false;
            }
        },

        // 格式化配置值显示
        formatConfigValue(value) {
            if (value === null || value === undefined) return '-';
            const str = String(value);
            if (str.length > 50) {
                return str.substring(0, 50) + '...';
            }
            return str;
        },
        
        // 打开配置编辑弹窗
        openConfigEditModal(item) {
            // 检查是否为社区版本且该配置为商业版专属
            if (this.isCommunityEdition && this.isCommercialOnlyConfig(item.config_key)) {
                this.showToast('该配置需要商业版本才能修改，请联系管理员升级', 'error');
                return;
            }

            this.configEditModal.configId = item.id;
            this.configEditModal.configKey = item.config_key;
            this.configEditModal.valueType = item.value_type;
            this.configEditModal.description = item.description || '';
            this.configEditModal.isSensitive = item.is_sensitive;

            // 根据类型设置值
            if (item.value_type === 'bool') {
                const val = String(item.config_value).toLowerCase();
                this.configEditModal.boolValue = val === 'true' || val === '1';
                this.configEditModal.value = '';
            } else {
                this.configEditModal.value = item.config_value !== null ? String(item.config_value) : '';
                this.configEditModal.boolValue = false;
            }

            this.configEditModal.show = true;
        },

        // 判断是否为商业版专属配置
        isCommercialOnlyConfig(configKey) {
            // 聚合站 2-5 为商业版专属配置
            const commercialPatterns = [
                'api_aggregator.site_2',
                'api_aggregator.site_3',
                'api_aggregator.site_4',
                'api_aggregator.site_5'
            ];
            return commercialPatterns.some(pattern => configKey.startsWith(pattern));
        },
        
        // 关闭配置编辑弹窗
        closeConfigEditModal() {
            this.configEditModal.show = false;
            this.configEditModal.configId = null;
            this.configEditModal.configKey = '';
            this.configEditModal.value = '';
            this.configEditModal.boolValue = false;
            this.configEditModal.valueType = 'string';
            this.configEditModal.description = '';
            this.configEditModal.isSensitive = false;
        },
        
        // 提交配置编辑
        async submitConfigEdit() {
            let value = this.configEditModal.value;
            
            // 布尔类型特殊处理
            if (this.configEditModal.valueType === 'bool') {
                value = this.configEditModal.boolValue ? 'true' : 'false';
            }
            
            // JSON类型校验
            if (this.configEditModal.valueType === 'json') {
                try {
                    JSON.parse(value);
                } catch (e) {
                    this.showToast('JSON格式不正确', 'error');
                    return;
                }
            }
            
            this.configEditModal.loading = true;
            try {
                const response = await axios.put(
                    `/api/admin/config/${this.configEditModal.configKey}`,
                    { value: value },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                
                if (response.data.code === 0) {
                    this.showToast('配置更新成功', 'success');
                    this.closeConfigEditModal();
                    this.loadConfigs();
                }
            } catch (error) {
                console.error('Update config failed:', error);
                const detail = error?.response?.data?.detail || '更新失败';
                this.showToast(detail, 'error');
            } finally {
                this.configEditModal.loading = false;
            }
        },
        
        // 查看配置历史
        async viewConfigHistory(item) {
            this.configHistoryModal.configKey = item.config_key;
            this.configHistoryModal.loading = true;
            this.configHistoryModal.show = true;
            
            try {
                const response = await axios.get(`/api/admin/config/${item.config_key}`, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                
                if (response.data.code === 0) {
                    this.configHistoryModal.list = response.data.data.history || [];
                }
            } catch (error) {
                console.error('Load config history failed:', error);
                this.showToast('加载配置历史失败', 'error');
                this.configHistoryModal.show = false;
            } finally {
                this.configHistoryModal.loading = false;
            }
        },
        
        // 关闭配置历史弹窗
        closeConfigHistoryModal() {
            this.configHistoryModal.show = false;
            this.configHistoryModal.configKey = '';
            this.configHistoryModal.list = [];
        },
        
        // 脱敏敏感配置值
        maskSensitiveValue(value) {
            if (!value || value.length <= 8) {
                return '********';
            }
            return value.substring(0, 4) + '****' + value.substring(value.length - 4);
        },
        
        // 弹框显示敏感配置值（从后端获取完整值）
        async showSensitiveValue(item) {
            try {
                const response = await axios.get('/api/admin/config/raw', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` },
                    params: { key: item.config_key }
                });
                
                if (response.data.code === 0) {
                    this.sensitiveValueModal.configKey = item.config_key;
                    this.sensitiveValueModal.value = response.data.data.config_value || '';
                    this.sensitiveValueModal.show = true;
                }
            } catch (error) {
                console.error('Failed to get raw config value:', error);
                this.showToast('获取配置值失败', 'error');
            }
        },
        
        // 关闭敏感配置值弹窗
        closeSensitiveValueModal() {
            this.sensitiveValueModal.show = false;
            this.sensitiveValueModal.configKey = '';
            this.sensitiveValueModal.value = '';
        },
        
        // 复制敏感配置值
        copySensitiveValue() {
            const input = document.getElementById('sensitiveValueInput');
            if (input) {
                input.select();
                document.execCommand('copy');
                this.showToast('已复制到剪贴板', 'success');
            }
        },
        
        // ==================== 快速配置方法（两栏模式） ====================

        // 打开快速配置弹窗
        async openQuickConfigModal() {
            this.quickConfigModal.show = true;
            this.quickConfigModal.activeCategory = 'llm';
            this.quickConfigModal.selectedProviderIds = [];
            this.quickConfigModal.providerFormData = {};
            this.quickConfigModal.originalValues = {};
            this.quickConfigModal.testLoading = {};
            this.quickConfigModal.testResults = {};
            this.quickConfigModal.saveLoading = {};
            this.quickConfigModal.leftPanelOpen = true;

            // 从后端加载现有配置值
            try {
                const quickConfigsResp = await axios.get('/api/admin/config/quick-configs', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (quickConfigsResp.data.code === 0) {
                    const configs = quickConfigsResp.data.data.configs || [];

                    for (const config of configs) {
                        try {
                            const response = await axios.get('/api/admin/config/raw', {
                                headers: { 'Authorization': `Bearer ${this.authToken}` },
                                params: { key: config.key }
                            });

                            if (response.data.code === 0) {
                                const value = response.data.data.config_value || '';
                                // 通过反向映射找到对应的 provider 和 field
                                const mapping = CONFIG_KEY_TO_PROVIDER_FIELD[config.key];
                                if (mapping) {
                                    const { providerId, fieldId } = mapping;
                                    // 初始化 provider 的 form data
                                    if (!this.quickConfigModal.providerFormData[providerId]) {
                                        this.quickConfigModal.providerFormData[providerId] = {};
                                    }
                                    if (!this.quickConfigModal.originalValues[providerId]) {
                                        this.quickConfigModal.originalValues[providerId] = {};
                                    }
                                    this.quickConfigModal.providerFormData[providerId][fieldId] = value;
                                    this.quickConfigModal.originalValues[providerId][fieldId] = value;

                                    // 自动选中已有配置的服务商
                                    if (value && !this.quickConfigModal.selectedProviderIds.includes(providerId)) {
                                        this.quickConfigModal.selectedProviderIds.push(providerId);
                                    }
                                }
                            }
                        } catch (e) {
                            console.log(`Config ${config.key} not found, will create on save`);
                        }
                    }

                    // 切换到第一个有选中服务商的分类
                    for (const cat of Object.keys(CATEGORY_LABELS)) {
                        const hasSelected = this.quickConfigModal.selectedProviderIds.some(id => {
                            const p = PROVIDER_DEFINITIONS.find(d => d.id === id);
                            return p && p.category === cat;
                        });
                        if (hasSelected) {
                            this.quickConfigModal.activeCategory = cat;
                            break;
                        }
                    }
                }
            } catch (error) {
                console.error('Failed to load quick config values:', error);
            }
        },

        // 关闭快速配置弹窗
        closeQuickConfigModal() {
            this.quickConfigModal.show = false;
            this.quickConfigModal.loading = false;
            this.quickConfigModal.selectedProviderIds = [];
            this.quickConfigModal.providerFormData = {};
            this.quickConfigModal.originalValues = {};
            this.quickConfigModal.testLoading = {};
            this.quickConfigModal.testResults = {};
            this.quickConfigModal.saveLoading = {};
        },

        // 切换服务商选中状态
        toggleProviderSelection(providerId) {
            const provider = PROVIDER_DEFINITIONS.find(p => p.id === providerId);
            if (provider && provider.commercialOnly && this.isCommunityEdition) {
                this.showToast('该配置需要商业版本才能使用，请联系管理员升级', 'error');
                return;
            }

            const idx = this.quickConfigModal.selectedProviderIds.indexOf(providerId);
            if (idx >= 0) {
                this.quickConfigModal.selectedProviderIds.splice(idx, 1);
            } else {
                this.quickConfigModal.selectedProviderIds.push(providerId);
                // 初始化 form data
                if (!this.quickConfigModal.providerFormData[providerId]) {
                    this.quickConfigModal.providerFormData[providerId] = {};
                }
                if (!this.quickConfigModal.originalValues[providerId]) {
                    this.quickConfigModal.originalValues[providerId] = {};
                }
            }
        },

        // 快速设置：自动选择推荐的服务商
        handleQuickSetup() {
            const recommendedIds = this.lazyRecommendedProviderIds;
            this.quickConfigModal.selectedProviderIds = [...recommendedIds];
            this.quickConfigModal.providerFormData = {};
            this.quickConfigModal.originalValues = this.quickConfigModal.originalValues || {};
            recommendedIds.forEach(id => {
                if (!this.quickConfigModal.providerFormData[id]) {
                    this.quickConfigModal.providerFormData[id] = {};
                }
                // 保留已加载的原始值
                if (!this.quickConfigModal.originalValues[id]) {
                    this.quickConfigModal.originalValues[id] = {};
                }
            });
            this.showToast(`已自动选择 ${recommendedIds.length} 个推荐服务商`, 'success');
        },

        // 移除已选服务商
        removeProvider(providerId) {
            const idx = this.quickConfigModal.selectedProviderIds.indexOf(providerId);
            if (idx >= 0) {
                this.quickConfigModal.selectedProviderIds.splice(idx, 1);
            }
        },

        // 获取表单字段值
        getFormField(providerId, fieldId) {
            const provider = PROVIDER_DEFINITIONS.find(p => p.id === providerId);
            if (provider) {
                const field = provider.fields.find(f => f.id === fieldId);
                if (field && field.readOnly && field.defaultValue) {
                    return field.defaultValue;
                }
            }
            return (this.quickConfigModal.providerFormData[providerId] || {})[fieldId] || '';
        },

        // 更新表单字段值
        updateFormField(providerId, fieldId, value) {
            if (!this.quickConfigModal.providerFormData[providerId]) {
                this.quickConfigModal.providerFormData[providerId] = {};
            }
            this.quickConfigModal.providerFormData[providerId][fieldId] = value;
        },

        // 判断服务商是否已配置（至少有一个字段有值）
        isProviderConfigured(providerId) {
            const formData = this.quickConfigModal.providerFormData[providerId];
            if (!formData) return false;
            return Object.values(formData).some(v => v && v.trim());
        },

        // 保存单个服务商的配置
        async saveProviderConfig(providerId) {
            const provider = PROVIDER_DEFINITIONS.find(p => p.id === providerId);
            if (!provider) return;

            const configs = [];
            const formData = this.quickConfigModal.providerFormData[providerId] || {};
            const origData = this.quickConfigModal.originalValues[providerId] || {};

            provider.fields.forEach(field => {
                if (field.readOnly) return;
                const configKey = provider.configKeyMap[field.id];
                if (!configKey) return;
                const currentValue = (formData[field.id] || '').trim();
                const originalValue = (origData[field.id] || '').trim();
                if (currentValue !== originalValue) {
                    configs.push({ key: configKey, value: currentValue });
                }
            });

            if (configs.length === 0) {
                this.showToast('配置未发生变化', 'success');
                return;
            }

            this.quickConfigModal.saveLoading[providerId] = true;

            try {
                const response = await axios.put('/api/admin/config/batch',
                    { configs },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );

                if (response.data.code === 0) {
                    const data = response.data.data;
                    const updatedCount = data.results.filter(r => r.status === 'updated').length;
                    this.showToast(`${provider.name} 配置已保存 (${updatedCount} 项更新)`, 'success');
                    // 更新原始值
                    configs.forEach(c => {
                        const mapping = CONFIG_KEY_TO_PROVIDER_FIELD[c.key];
                        if (mapping && mapping.providerId === providerId) {
                            if (!this.quickConfigModal.originalValues[providerId]) {
                                this.quickConfigModal.originalValues[providerId] = {};
                            }
                            this.quickConfigModal.originalValues[providerId][mapping.fieldId] = c.value;
                        }
                    });
                    this.loadConfigs();
                }
            } catch (error) {
                console.error('Save provider config failed:', error);
                const detail = error?.response?.data?.detail || '保存失败';
                this.showToast(detail, 'error');
            } finally {
                this.quickConfigModal.saveLoading[providerId] = false;
            }
        },

        // 测试服务商连接
        async testProviderConnection(providerId) {
            const provider = PROVIDER_DEFINITIONS.find(p => p.id === providerId);
            if (!provider || !provider.testEndpoint) return;

            const formData = this.quickConfigModal.providerFormData[providerId] || {};
            this.quickConfigModal.testLoading[providerId] = true;
            this.quickConfigModal.testResults[providerId] = null;

            try {
                const payload = {
                    api_key: formData.api_key || formData.token || '',
                    base_url: formData.base_url || null
                };

                const endpoint = provider.testEndpoint === 'google'
                    ? '/api/admin/config/test-google'
                    : '/api/admin/config/test-qwen';

                const response = await axios.post(endpoint, payload, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    this.quickConfigModal.testResults[providerId] = {
                        success: true,
                        message: response.data.message
                    };
                } else {
                    this.quickConfigModal.testResults[providerId] = {
                        success: false,
                        message: response.data.message
                    };
                }
            } catch (error) {
                console.error('Test connection failed:', error);
                const detail = error?.response?.data?.detail || '测试失败';
                this.quickConfigModal.testResults[providerId] = {
                    success: false,
                    message: detail
                };
            } finally {
                this.quickConfigModal.testLoading[providerId] = false;
            }
        },

        // 批量保存所有已选服务商的配置
        async submitQuickConfig() {
            const configs = [];

            this.quickConfigModal.selectedProviderIds.forEach(providerId => {
                const provider = PROVIDER_DEFINITIONS.find(p => p.id === providerId);
                if (!provider) return;

                const formData = this.quickConfigModal.providerFormData[providerId] || {};
                const origData = this.quickConfigModal.originalValues[providerId] || {};

                provider.fields.forEach(field => {
                    if (field.readOnly) return;
                    const configKey = provider.configKeyMap[field.id];
                    if (!configKey) return;
                    const currentValue = (formData[field.id] || '').trim();
                    const originalValue = (origData[field.id] || '').trim();
                    if (currentValue !== originalValue) {
                        configs.push({ key: configKey, value: currentValue });
                    }
                });
            });

            if (configs.length === 0) {
                this.showToast('配置未发生变化', 'success');
                this.closeQuickConfigModal();
                return;
            }

            this.quickConfigModal.loading = true;

            try {
                const response = await axios.put('/api/admin/config/batch',
                    { configs },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );

                if (response.data.code === 0) {
                    const data = response.data.data;
                    const updatedCount = data.results.filter(r => r.status === 'updated').length;
                    const errors = data.errors || [];

                    if (errors.length > 0) {
                        this.showToast(`部分配置更新失败: ${errors.join(', ')}`, 'error');
                    } else if (updatedCount > 0) {
                        this.showToast(`成功更新 ${updatedCount} 条配置`, 'success');
                    } else {
                        this.showToast('配置未发生变化', 'success');
                    }

                    this.closeQuickConfigModal();
                    this.loadConfigs();

                    // 显示使用手册引导弹窗
                    this.guideModal.show = true;
                }
            } catch (error) {
                console.error('Submit quick config failed:', error);
                const detail = error?.response?.data?.detail || '保存失败';
                this.showToast(detail, 'error');
            } finally {
                this.quickConfigModal.loading = false;
            }
        },

        // 显示 jiekou 注册提示（保留兼容）
        showJiekouTip() {
            const confirmed = confirm('💡 提示：\n\njiekou 注册需要 Google 或 GitHub 账号，但注册即送 $1 代金券！\n\n点击"确定"前往注册页面');
            if (confirmed) {
                window.open('https://jiekou.ai/user/register?invited_code=119T5V', '_blank');
            }
        },

        // ==================== 实现方管理方法 ====================

        // 加载实现方列表
        async loadImplementations() {
            this.implementations.loading = true;
            try {
                const response = await axios.get('/api/admin/implementation-configs', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    console.log('加载实现方数据:', response.data.data);
                    // 后端现在返回分组数据
                    this.implementations.groups = response.data.data;
                    console.log('更新后的 groups:', this.implementations.groups);

                    // 强制触发 Vue 响应式更新
                    this.$forceUpdate();
                }
            } catch (error) {
                console.error('Load implementations failed:', error);
                this.showToast('加载实现方列表失败', 'error');
            } finally {
                this.implementations.loading = false;
            }
        },

        // 搜索实现方
        searchImplementations() {
            // 前端过滤，无需重新加载
        },

        // ==================== 排序管理方法 ====================

        // 更新单个实现方的排序值
        async updateSortOrder(implementation, newSortOrder, group) {
            const sortOrder = parseInt(newSortOrder);
            if (isNaN(sortOrder) || sortOrder < 0) {
                this.showToast('请输入有效的排序值', 'error');
                // 恢复原值
                this.loadImplementations();
                return;
            }

            this.implementations.updating = implementation.name;

            try {
                const response = await axios.post('/api/admin/implementation-configs/sort-order', {
                    updates: [{
                        implementation_name: implementation.name,
                        driver_key: group.driver_key,
                        sort_order: sortOrder
                    }]
                }, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    // 更新本地数据
                    implementation.sort_order = sortOrder;
                    // 重新加载以获取排序后的数据
                    await this.loadImplementations();
                    this.showToast('排序已更新', 'success');
                } else {
                    this.showToast(response.data.message || '更新失败', 'error');
                    this.loadImplementations();
                }
            } catch (error) {
                console.error('Update sort order failed:', error);
                const detail = error?.response?.data?.detail || '更新失败';
                this.showToast(detail, 'error');
                this.loadImplementations();
            } finally {
                this.implementations.updating = null;
            }
        },

        // 格式化 DriverKey 显示
        formatDriverKey(driverKey) {
            const keyMap = {
                'sora2_text_to_video': 'Sora2 文生视频',
                'sora2_image_to_video': 'Sora2 图生视频',
                'kling_image_to_video': 'Kling 图生视频',
                'gemini_image_edit': 'Gemini 图片编辑 (标准版)',
                'gemini_image_edit_pro': 'Gemini 图片编辑 (Pro版)',
                'veo3_image_to_video': 'VEO3 图生视频',
                'ltx2_image_to_video': 'LTX2 图生视频',
                'wan22_image_to_video': 'Wan22 图生视频',
                'digital_human': '数字人',
                'vidu_image_to_video': 'Vidu 图生视频',
                'vidu_q2_image_to_video': 'Vidu Q2 图生视频',
                'seedream_text_to_image': 'Seedream 文生图'
            };
            return keyMap[driverKey] || driverKey;
        },

        // 判断是否为默认使用的实现方（排序最靠前的已启用实现方）
        isDefaultImplementation(implementation, group) {
            // 过滤出该组中所有已启用的实现方
            const enabledImplementations = group.implementations.filter(impl => impl.enabled);
            if (enabledImplementations.length === 0) {
                return false;
            }
            // 按 sort_order 排序，找到排序最靠前的
            enabledImplementations.sort((a, b) => {
                const orderA = a.sort_order ?? 999999;
                const orderB = b.sort_order ?? 999999;
                return orderA - orderB;
            });
            // 判断当前实现方是否是排序最靠前的
            return enabledImplementations[0].name === implementation.name;
        },

        // 打开实现方编辑弹窗
        openImplEditModal(impl, group) {
            this.implEditModal.implementation = impl;
            this.implEditModal.driver_key = group.driver_key;
            this.implEditModal.enabled = impl.enabled;
            this.implEditModal.sort_order = impl.sort_order || 0;
            this.implEditModal.show = true;
        },

        // 关闭实现方编辑弹窗
        closeImplEditModal() {
            this.implEditModal.show = false;
            this.implEditModal.implementation = null;
            this.implEditModal.driver_key = '';
            this.implEditModal.enabled = true;
            this.implEditModal.sort_order = 0;
        },

        // 提交实现方配置编辑
        async submitImplEdit() {
            this.implEditModal.loading = true;
            try {
                const response = await axios.put('/api/admin/implementation-config', {
                    implementation_name: this.implEditModal.implementation.name,
                    driver_key: this.implEditModal.driver_key,
                    enabled: this.implEditModal.enabled,
                    sort_order: this.implEditModal.sort_order
                }, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    this.showToast('配置更新成功', 'success');
                    this.closeImplEditModal();
                    this.loadImplementations();
                }
            } catch (error) {
                console.error('Update implementation failed:', error);
                const detail = error?.response?.data?.detail || '更新失败';
                this.showToast(detail, 'error');
            } finally {
                this.implEditModal.loading = false;
            }
        },

        // 快速切换实现方启用状态
        async toggleImplementation(impl, group) {
            const action = impl.enabled ? '禁用' : '启用';
            const newEnabled = !impl.enabled;
            console.log(`准备${action}实现方: ${impl.name}, 当前状态: ${impl.enabled}, 新状态: ${newEnabled}`);

            if (!confirm(`确定要${action}实现方 "${impl.display_name}" 吗？`)) {
                return;
            }

            try {
                const response = await axios.put('/api/admin/implementation-config', {
                    implementation_name: impl.name,
                    driver_key: group.driver_key,
                    enabled: newEnabled
                }, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                console.log('后端响应:', response.data);

                if (response.data.code === 0) {
                    this.showToast(`${action}成功`, 'success');
                    // 重新加载数据以获取最新状态
                    await this.loadImplementations();
                    console.log('数据重新加载完成');
                } else {
                    this.showToast(response.data.message || '操作失败', 'error');
                }
            } catch (error) {
                console.error('Toggle implementation failed:', error);
                const detail = error?.response?.data?.detail || '操作失败';
                this.showToast(detail, 'error');
            }
        },

        // 打开算力配置弹窗
        openImplPowerModal(impl) {
            this.implPowerModal.implementation = impl;
            
            // 获取当前有效的算力值（优先数据库配置，其次默认值）
            let currentPower = 0;
            
            // 如果有 duration_powers，使用第一个时长的算力值
            if (impl.duration_powers && impl.duration_powers.length > 0) {
                const firstDuration = impl.duration_powers[0];
                if (firstDuration.computing_power !== null && firstDuration.computing_power !== undefined) {
                    currentPower = firstDuration.computing_power;
                }
            } else {
                // 否则使用 default_computing_power
                let defaultPower = impl.default_computing_power;
                if (typeof defaultPower === 'object' && defaultPower !== null) {
                    currentPower = Object.values(defaultPower)[0] || 0;
                } else {
                    currentPower = defaultPower || 0;
                }
            }
            
            this.implPowerModal.computing_power = currentPower;
            // 从后端返回的数据中获取支持的时长列表
            this.implPowerModal.durationOptions = impl.supported_durations || [];
            this.implPowerModal.duration = null;
            this.implPowerModal.show = true;
        },

        // 关闭算力配置弹窗
        closeImplPowerModal() {
            this.implPowerModal.show = false;
            this.implPowerModal.implementation = null;
            this.implPowerModal.computing_power = 0;
            this.implPowerModal.duration = null;
            this.implPowerModal.durationOptions = [];
        },

        // 提交算力配置
        async submitImplPower() {
            if (this.implPowerModal.computing_power < 0) {
                this.showToast('算力值不能为负数', 'error');
                return;
            }

            this.implPowerModal.loading = true;
            try {
                const payload = {
                    implementation_name: this.implPowerModal.implementation.name,
                    computing_power: this.implPowerModal.computing_power
                };

                if (this.implPowerModal.duration) {
                    payload.duration = this.implPowerModal.duration;
                }

                const response = await axios.post('/api/admin/implementation-power', payload, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    this.showToast('算力配置更新成功', 'success');
                    this.closeImplPowerModal();
                    this.loadImplementations();
                }
            } catch (error) {
                console.error('Update power failed:', error);
                const detail = error?.response?.data?.detail || '更新失败';
                this.showToast(detail, 'error');
            } finally {
                this.implPowerModal.loading = false;
            }
        },

        // 内联更新时长算力配置
        async updateDurationPower(implementation, duration, value, group) {
            const computingPower = parseInt(value);
            if (isNaN(computingPower) || computingPower < 0) {
                this.showToast('请输入有效的算力值', 'error');
                // 恢复原值
                this.loadImplementations();
                return;
            }

            const updateKey = `${implementation.name}-${duration}`;
            this.implementations.updating = updateKey;

            try {
                const payload = {
                    implementation_name: implementation.name,
                    driver_key: group.driver_key,
                    computing_power: computingPower,
                    duration: duration
                };

                const response = await axios.post('/api/admin/implementation-power', payload, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    // 更新本地数据
                    const dp = implementation.duration_powers.find(d => d.duration === duration);
                    if (dp) {
                        dp.computing_power = computingPower;
                    }
                    this.showToast(`${duration}秒算力已更新为 ${computingPower}`, 'success');
                } else {
                    // 更新失败，恢复原值
                    this.showToast(response.data.message || '更新失败', 'error');
                    this.loadImplementations();
                }
            } catch (error) {
                console.error('Update duration power failed:', error);
                const detail = error?.response?.data?.detail || '更新失败';
                this.showToast(detail, 'error');
                // 出错时恢复原值
                this.loadImplementations();
            } finally {
                this.implementations.updating = null;
            }
        },

        // 更新默认算力配置（固定算力，不按时长区分）
        async updateDefaultPower(implementation, value, group) {
            const computingPower = parseInt(value);
            if (isNaN(computingPower) || computingPower < 0) {
                this.showToast('请输入有效的算力值', 'error');
                // 恢复原值
                this.loadImplementations();
                return;
            }

            this.implementations.updating = implementation.name;

            try {
                const payload = {
                    implementation_name: implementation.name,
                    driver_key: group.driver_key,
                    computing_power: computingPower
                    // 不传 duration，表示固定算力
                };

                const response = await axios.post('/api/admin/implementation-power', payload, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    // 更新本地数据
                    implementation.current_default_power = computingPower;
                    this.showToast(`默认算力已更新为 ${computingPower}`, 'success');
                } else {
                    // 更新失败，恢复原值
                    this.showToast(response.data.message || '更新失败', 'error');
                    this.loadImplementations();
                }
            } catch (error) {
                console.error('Update default power failed:', error);
                const detail = error?.response?.data?.detail || '更新失败';
                this.showToast(detail, 'error');
                // 出错时恢复原值
                this.loadImplementations();
            } finally {
                this.implementations.updating = null;
            }
        },

        // 恢复算力到代码默认值
        async resetToDefaultPower(implementation, duration, group) {
            // 获取默认算力值
            let defaultPower = 0;

            if (duration === null) {
                // 恢复默认算力（固定算力）
                defaultPower = implementation.default_computing_power;
                if (typeof defaultPower === 'object' && defaultPower !== null) {
                    defaultPower = Object.values(defaultPower)[0] || 0;
                } else {
                    defaultPower = defaultPower || 0;
                }

                // 确认操作
                if (!confirm(`确定要将 "${implementation.display_name}" 的算力恢复到默认值 ${defaultPower} 吗？\n这将删除当前的数据库配置。`)) {
                    return;
                }

                this.implementations.updating = implementation.name;

                try {
                    // 先删除数据库配置
                    await axios.delete('/api/admin/implementation-power', {
                        data: {
                            implementation_name: implementation.name,
                            driver_key: group.driver_key,
                            duration: null
                        },
                        headers: { 'Authorization': `Bearer ${this.authToken}` }
                    });

                    // 更新本地显示
                    implementation.current_default_power = defaultPower;
                    this.showToast(`已恢复到默认算力 ${defaultPower}`, 'success');

                } catch (error) {
                    console.error('Reset default power failed:', error);
                    const detail = error?.response?.data?.detail || '恢复失败';
                    this.showToast(detail, 'error');
                } finally {
                    this.implementations.updating = null;
                }

            } else {
                // 恢复特定时长的算力
                if (implementation.default_duration_powers && implementation.default_duration_powers[duration] !== undefined) {
                    defaultPower = implementation.default_duration_powers[duration];
                } else {
                    defaultPower = implementation.default_computing_power;
                    if (typeof defaultPower === 'object' && defaultPower !== null) {
                        defaultPower = Object.values(defaultPower)[0] || 0;
                    } else {
                        defaultPower = defaultPower || 0;
                    }
                }

                // 确认操作
                if (!confirm(`确定要将 "${implementation.display_name}" 的 ${duration}秒 算力恢复到默认值 ${defaultPower} 吗？\n这将删除当前的数据库配置。`)) {
                    return;
                }

                const updateKey = `${implementation.name}-${duration}`;
                this.implementations.updating = updateKey;

                try {
                    // 先删除数据库配置
                    await axios.delete('/api/admin/implementation-power', {
                        data: {
                            implementation_name: implementation.name,
                            driver_key: group.driver_key,
                            duration: duration
                        },
                        headers: { 'Authorization': `Bearer ${this.authToken}` }
                    });

                    // 更新本地显示
                    const dp = implementation.duration_powers.find(d => d.duration === duration);
                    if (dp) {
                        dp.computing_power = defaultPower;
                    }
                    this.showToast(`${duration}秒算力已恢复到默认值 ${defaultPower}`, 'success');

                } catch (error) {
                    console.error('Reset duration power failed:', error);
                    const detail = error?.response?.data?.detail || '恢复失败';
                    this.showToast(detail, 'error');
                } finally {
                    this.implementations.updating = null;
                }
            }
        },

        // 格式化算力显示
        formatComputingPower(power) {
            if (power === null || power === undefined || power === '') return '-';
            if (typeof power === 'object') {
                const values = Object.values(power);
                if (values.length === 0) return '-';
                if (values.length === 1) return values[0];
                return values.join(' / ');
            }
            return power;
        }
    }
};

// 初始化Vue应用
Vue.createApp(AdminApp).mount('#app');
