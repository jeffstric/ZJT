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
        nameKey: 'provider_huoshan_name',
        descKey: 'provider_huoshan_desc',
        category: 'llm',
        icon: '🔥',
        docUrl: 'https://console.volcengine.com/ark',
        lazyRecommended: false,
        displayOrder: 4,
        baseName: 'huoshan',
        isOfficialAPI: false,
        impactsKey: 'provider_huoshan_impacts',
        fields: [
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true, helpTextKey: 'field_api_key_help_volcengine' }
        ],
        configKeyMap: { api_key: 'volcengine.api_key' },
        testEndpoint: null
    },
    {
        id: 'ywapi',
        nameKey: 'provider_ywapi_name',
        descKey: 'provider_ywapi_desc',
        category: 'llm',
        icon: '☁️',
        docUrl: 'https://yw.perseids.cn/register?aff=hE0h',
        docUrlLabelKey: 'btn_legacy_user_login',
        // 智剧通API 逐步下线，不再作为推荐供应商，也不再展示「ZJT官方API」徽章
        lazyRecommended: false,
        displayOrder: 1,
        baseName: 'ywapi',
        isOfficialAPI: false,
        showInCategories: ['llm', 'image', 'video'],
        impactsKey: 'provider_ywapi_impacts',
        fields: [
            { id: 'name', labelKey: 'field_ywapi_name_label', type: 'text', placeholderKey: 'field_ywapi_name_placeholder', required: false, readOnly: true, defaultValue: '智剧通API' },
            { id: 'base_url', label: 'Base URL', type: 'text', placeholder: 'https://yw.perseids.cn', required: true, readOnly: true, defaultValue: 'https://yw.perseids.cn' },
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_0.name', base_url: 'api_aggregator.site_0.base_url', api_key: 'api_aggregator.site_0.api_key' },
        testEndpoint: null
    },
    {
        id: 'google',
        nameKey: 'provider_google_name',
        descKey: 'provider_google_desc',
        category: 'llm',
        icon: '✨',
        docUrl: 'https://jiekou.ai/user/register?invited_code=119T5V',
        lazyRecommended: false,
        displayOrder: 5,
        baseName: 'google',
        isOfficialAPI: false,
        impactsKey: 'provider_google_impacts',
        fields: [
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder_google', required: true, helpTextKey: 'field_api_key_help_third_party' },
            { id: 'base_url', labelKey: 'field_base_url_label_optional', type: 'url', placeholder: 'https://api.jiekou.ai', required: false, helpTextKey: 'field_base_url_placeholder' }
        ],
        configKeyMap: { api_key: 'llm.google.api_key', base_url: 'llm.google.gemini_base_url' },
        testEndpoint: 'google'
    },
    {
        id: 'claude',
        nameKey: 'provider_claude_name',
        descKey: 'provider_claude_desc',
        category: 'llm',
        icon: '🟣',
        docUrl: 'https://jiekou.ai/user/register?invited_code=119T5V',
        lazyRecommended: false,
        displayOrder: 6,
        baseName: 'claude',
        isOfficialAPI: false,
        impactsKey: 'provider_claude_impacts',
        fields: [
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder_claude', required: true, helpTextKey: 'field_api_key_help_third_party' },
            { id: 'base_url', labelKey: 'field_base_url_label_optional', type: 'url', placeholder: 'https://api.jiekou.ai/openai', required: false, helpTextKey: 'field_base_url_placeholder' }
        ],
        configKeyMap: { api_key: 'llm.claude.api_key', base_url: 'llm.claude.base_url' },
        testEndpoint: null
    },
    {
        id: 'qwen',
        nameKey: 'provider_qwen_name',
        descKey: 'provider_qwen_desc',
        category: 'llm',
        icon: '🧠',
        docUrl: 'https://dashscope.console.aliyun.com/apiKey',
        lazyRecommended: false,
        displayOrder: 3,
        baseName: 'qwen',
        isOfficialAPI: false,
        impactsKey: 'provider_qwen_impacts',
        fields: [
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder_qwen', required: true },
            { id: 'base_url', labelKey: 'field_base_url_label_optional', type: 'url', placeholder: 'https://dashscope.aliyuncs.com/compatible-mode/v1', required: false, helpTextKey: 'field_base_url_placeholder' }
        ],
        configKeyMap: { api_key: 'llm.qwen.api_key', base_url: 'llm.qwen.base_url' },
        testEndpoint: 'qwen'
    },
    {
        id: 'deepseek',
        nameKey: 'provider_deepseek_name',
        descKey: 'provider_deepseek_desc',
        category: 'llm',
        icon: '🔍',
        docUrl: 'https://platform.deepseek.com/api_keys',
        lazyRecommended: true,
        displayOrder: 2,
        baseName: 'deepseek',
        isOfficialAPI: false,
        impactsKey: 'provider_deepseek_impacts',
        fields: [
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder_deepseek', required: true },
            { id: 'base_url', labelKey: 'field_base_url_label_optional', type: 'url', placeholder: 'https://api.deepseek.com', required: false, helpTextKey: 'field_base_url_placeholder' }
        ],
        configKeyMap: { api_key: 'llm.deepseek.api_key', base_url: 'llm.deepseek.base_url' },
        testEndpoint: null
    },

    // ===== 生图服务商 =====
    {
        id: 'duomi',
        nameKey: 'provider_duomi_name',
        descKey: 'provider_duomi_image_desc',
        category: 'image',
        icon: '🎨',
        docUrl: 'https://duomiapi.com/user/register?cps=U4GgW1Fx',
        // 快速选择推荐方案：DeepSeek 大模型 + 多米（生图/生视频）
        lazyRecommended: true,
        displayOrder: 4,
        baseName: 'duomi',
        isOfficialAPI: false,
        impactsKey: 'provider_duomi_image_impacts',
        fields: [
            { id: 'token', label: 'Token', type: 'text', placeholderKey: 'field_token_placeholder_duomi', required: true, helpTextKey: 'field_token_help_quick_register' }
        ],
        configKeyMap: { token: 'duomi.token' },
        testEndpoint: null
    },
    {
        id: 'huoshan_image',
        nameKey: 'provider_huoshan_name',
        descKey: 'provider_huoshan_image_desc',
        category: 'image',
        icon: '🔥',
        docUrl: 'https://console.volcengine.com/ark',
        lazyRecommended: true,
        displayOrder: 1,
        baseName: 'huoshan',
        isOfficialAPI: false,
        impactsKey: 'provider_huoshan_image_impacts',
        fields: [
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true, helpTextKey: 'field_api_key_help_volcengine' }
        ],
        configKeyMap: { api_key: 'volcengine.api_key' },
        testEndpoint: null,
        _sharedWith: 'huoshan'
    },
    {
        id: 'huoshan_oversea_image',
        nameKey: 'provider_huoshan_oversea_name',
        descKey: 'provider_huoshan_oversea_image_desc',
        category: 'image',
        icon: '🌍',
        docUrl: 'https://console.volcengine.com/ark',
        lazyRecommended: false,
        displayOrder: 2,
        baseName: 'huoshan_oversea',
        isOfficialAPI: false,
        impactsKey: 'provider_huoshan_oversea_image_impacts',
        fields: [
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://ark.ap-southeast.bytepluses.com', required: false }
        ],
        configKeyMap: { api_key: 'volcengine_oversea.api_key', base_url: 'volcengine_oversea.base_url' },
        testEndpoint: null,
        _sharedWith: 'huoshan_oversea'
    },
    {
        id: 'site_1_image',
        nameKey: 'provider_site_name',
        nameKeyParams: { n: 1 },
        descKey: 'provider_site_image_desc',
        descKeyParams: { n: 1 },
        category: 'image',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 10,
        baseName: 'site_1',
        isOfficialAPI: false,
        impactsKey: 'provider_site_image_impacts',
        fields: [
            { id: 'name', labelKey: 'field_site_name_label', type: 'text', placeholderKey: 'field_site_name_placeholder', placeholderParams: { n: 1 }, required: false, helpTextKey: 'field_site_name_help' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_1.name', base_url: 'api_aggregator.site_1.base_url', api_key: 'api_aggregator.site_1.api_key' },
        testEndpoint: null
    },
    {
        id: 'site_2_image',
        nameKey: 'provider_site_name',
        nameKeyParams: { n: 2 },
        descKey: 'provider_site_image_desc',
        descKeyParams: { n: 2 },
        category: 'image',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 11,
        baseName: 'site_2',
        isOfficialAPI: false,
        impactsKey: 'provider_site_image_impacts',
        fields: [
            { id: 'name', labelKey: 'field_site_name_label', type: 'text', placeholderKey: 'field_site_name_placeholder', placeholderParams: { n: 2 }, required: false, helpTextKey: 'field_site_name_help' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_2.name', base_url: 'api_aggregator.site_2.base_url', api_key: 'api_aggregator.site_2.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },
    {
        id: 'site_3_image',
        nameKey: 'provider_site_name',
        nameKeyParams: { n: 3 },
        descKey: 'provider_site_image_desc',
        descKeyParams: { n: 3 },
        category: 'image',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 12,
        baseName: 'site_3',
        isOfficialAPI: false,
        impactsKey: 'provider_site_image_impacts',
        fields: [
            { id: 'name', labelKey: 'field_site_name_label', type: 'text', placeholderKey: 'field_site_name_placeholder', placeholderParams: { n: 3 }, required: false, helpTextKey: 'field_site_name_help' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_3.name', base_url: 'api_aggregator.site_3.base_url', api_key: 'api_aggregator.site_3.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },
    {
        id: 'site_4_image',
        nameKey: 'provider_site_name',
        nameKeyParams: { n: 4 },
        descKey: 'provider_site_image_desc',
        descKeyParams: { n: 4 },
        category: 'image',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 13,
        baseName: 'site_4',
        isOfficialAPI: false,
        impactsKey: 'provider_site_image_impacts',
        fields: [
            { id: 'name', labelKey: 'field_site_name_label', type: 'text', placeholderKey: 'field_site_name_placeholder', placeholderParams: { n: 4 }, required: false, helpTextKey: 'field_site_name_help' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_4.name', base_url: 'api_aggregator.site_4.base_url', api_key: 'api_aggregator.site_4.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },
    {
        id: 'site_5_image',
        nameKey: 'provider_site_name',
        nameKeyParams: { n: 5 },
        descKey: 'provider_site_image_desc',
        descKeyParams: { n: 5 },
        category: 'image',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 14,
        baseName: 'site_5',
        isOfficialAPI: false,
        impactsKey: 'provider_site_image_impacts',
        fields: [
            { id: 'name', labelKey: 'field_site_name_label', type: 'text', placeholderKey: 'field_site_name_placeholder', placeholderParams: { n: 5 }, required: false, helpTextKey: 'field_site_name_help' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_5.name', base_url: 'api_aggregator.site_5.base_url', api_key: 'api_aggregator.site_5.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },

    // ===== 生视频服务商 =====
    {
        id: 'duomi_video',
        nameKey: 'provider_duomi_name',
        descKey: 'provider_duomi_video_desc',
        category: 'video',
        icon: '🎨',
        docUrl: 'https://duomiapi.com/user/register?cps=U4GgW1Fx',
        lazyRecommended: true,
        displayOrder: 1,
        baseName: 'duomi',
        isOfficialAPI: false,
        impactsKey: 'provider_duomi_video_impacts',
        fields: [
            { id: 'token', label: 'Token', type: 'text', placeholderKey: 'field_token_placeholder_duomi', required: true }
        ],
        configKeyMap: { token: 'duomi.token' },
        testEndpoint: null,
        _sharedWith: 'duomi'
    },
    {
        id: 'runninghub',
        nameKey: 'provider_runninghub_name',
        descKey: 'provider_runninghub_desc',
        category: 'video',
        icon: '🚀',
        docUrl: 'https://www.runninghub.cn/?inviteCode=quacwnzc',
        lazyRecommended: true,
        displayOrder: 2,
        baseName: 'runninghub',
        isOfficialAPI: false,
        impactsKey: 'provider_runninghub_impacts',
        fields: [
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder_runninghub', required: true, helpTextKey: 'field_token_help_quick_register' }
        ],
        configKeyMap: { api_key: 'runninghub.api_key' },
        testEndpoint: null
    },
    {
        id: 'huoshan_video',
        nameKey: 'provider_huoshan_name',
        descKey: 'provider_huoshan_video_desc',
        category: 'video',
        icon: '🔥',
        docUrl: 'https://console.volcengine.com/ark',
        lazyRecommended: false,
        displayOrder: 4,
        baseName: 'huoshan',
        isOfficialAPI: false,
        impactsKey: 'provider_huoshan_video_impacts',
        fields: [
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true, helpTextKey: 'field_api_key_help_volcengine' }
        ],
        configKeyMap: { api_key: 'volcengine.api_key' },
        testEndpoint: null,
        _sharedWith: 'huoshan'
    },
    {
        id: 'huoshan_oversea_video',
        nameKey: 'provider_huoshan_oversea_name',
        descKey: 'provider_huoshan_oversea_video_desc',
        category: 'video',
        icon: '🌍',
        docUrl: 'https://console.volcengine.com/ark',
        lazyRecommended: false,
        displayOrder: 5,
        baseName: 'huoshan_oversea',
        isOfficialAPI: false,
        impactsKey: 'provider_huoshan_oversea_video_impacts',
        fields: [
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://ark.ap-southeast.bytepluses.com', required: false }
        ],
        configKeyMap: { api_key: 'volcengine_oversea.api_key', base_url: 'volcengine_oversea.base_url' },
        testEndpoint: null,
        _sharedWith: 'huoshan_oversea'
    },
    {
        id: 'kkidc_video',
        nameKey: 'provider_kkidc_name',
        descKey: 'provider_kkidc_video_desc',
        category: 'video',
        icon: '🔌',
        docUrl: 'https://ai.kkidc.com',
        lazyRecommended: false,
        displayOrder: 6,
        baseName: 'kkidc',
        isOfficialAPI: false,
        impactsKey: 'provider_kkidc_video_impacts',
        fields: [
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true }
        ],
        configKeyMap: { api_key: 'kkidc.api_key' },
        testEndpoint: null
    },
    {
        id: 'huimengi_video',
        nameKey: 'provider_huimengi_name',
        descKey: 'provider_huimengi_video_desc',
        category: 'video',
        icon: '🔌',
        docUrl: 'https://api.huimengi.com',
        lazyRecommended: false,
        displayOrder: 7,
        baseName: 'huimengi',
        isOfficialAPI: false,
        impactsKey: 'provider_huimengi_video_impacts',
        fields: [
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true }
        ],
        configKeyMap: { api_key: 'huimengi.api_key' },
        testEndpoint: null
    },
    {
        id: 'site_1_video',
        nameKey: 'provider_site_name',
        nameKeyParams: { n: 1 },
        descKey: 'provider_site_video_desc',
        descKeyParams: { n: 1 },
        category: 'video',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 10,
        baseName: 'site_1',
        isOfficialAPI: false,
        impactsKey: 'provider_site_video_impacts',
        fields: [
            { id: 'name', labelKey: 'field_site_name_label', type: 'text', placeholderKey: 'field_site_name_placeholder', placeholderParams: { n: 1 }, required: false, helpTextKey: 'field_site_name_help' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_1.name', base_url: 'api_aggregator.site_1.base_url', api_key: 'api_aggregator.site_1.api_key' },
        testEndpoint: null
    },
    {
        id: 'site_2_video',
        nameKey: 'provider_site_name',
        nameKeyParams: { n: 2 },
        descKey: 'provider_site_video_desc',
        descKeyParams: { n: 2 },
        category: 'video',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 11,
        baseName: 'site_2',
        isOfficialAPI: false,
        impactsKey: 'provider_site_video_impacts',
        fields: [
            { id: 'name', labelKey: 'field_site_name_label', type: 'text', placeholderKey: 'field_site_name_placeholder', placeholderParams: { n: 2 }, required: false, helpTextKey: 'field_site_name_help' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_2.name', base_url: 'api_aggregator.site_2.base_url', api_key: 'api_aggregator.site_2.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },
    {
        id: 'site_3_video',
        nameKey: 'provider_site_name',
        nameKeyParams: { n: 3 },
        descKey: 'provider_site_video_desc',
        descKeyParams: { n: 3 },
        category: 'video',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 12,
        baseName: 'site_3',
        isOfficialAPI: false,
        impactsKey: 'provider_site_video_impacts',
        fields: [
            { id: 'name', labelKey: 'field_site_name_label', type: 'text', placeholderKey: 'field_site_name_placeholder', placeholderParams: { n: 3 }, required: false, helpTextKey: 'field_site_name_help' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_3.name', base_url: 'api_aggregator.site_3.base_url', api_key: 'api_aggregator.site_3.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },
    {
        id: 'site_4_video',
        nameKey: 'provider_site_name',
        nameKeyParams: { n: 4 },
        descKey: 'provider_site_video_desc',
        descKeyParams: { n: 4 },
        category: 'video',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 13,
        baseName: 'site_4',
        isOfficialAPI: false,
        impactsKey: 'provider_site_video_impacts',
        fields: [
            { id: 'name', labelKey: 'field_site_name_label', type: 'text', placeholderKey: 'field_site_name_placeholder', placeholderParams: { n: 4 }, required: false, helpTextKey: 'field_site_name_help' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_4.name', base_url: 'api_aggregator.site_4.base_url', api_key: 'api_aggregator.site_4.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },
    {
        id: 'site_5_video',
        nameKey: 'provider_site_name',
        nameKeyParams: { n: 5 },
        descKey: 'provider_site_video_desc',
        descKeyParams: { n: 5 },
        category: 'video',
        icon: '🔗',
        lazyRecommended: false,
        displayOrder: 14,
        baseName: 'site_5',
        isOfficialAPI: false,
        impactsKey: 'provider_site_video_impacts',
        fields: [
            { id: 'name', labelKey: 'field_site_name_label', type: 'text', placeholderKey: 'field_site_name_placeholder', placeholderParams: { n: 5 }, required: false, helpTextKey: 'field_site_name_help' },
            { id: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://api.example.com', required: true },
            { id: 'api_key', labelKey: 'field_api_key_label', type: 'text', placeholderKey: 'field_api_key_placeholder', required: true }
        ],
        configKeyMap: { name: 'api_aggregator.site_5.name', base_url: 'api_aggregator.site_5.base_url', api_key: 'api_aggregator.site_5.api_key' },
        testEndpoint: null,
        commercialOnly: true
    },

    // ===== 其他推荐服务 =====
    {
        id: 'vidu',
        nameKey: 'provider_vidu_name',
        descKey: 'provider_vidu_desc',
        category: 'other',
        icon: '🎬',
        docUrl: 'https://platform.vidu.cn/api-keys',
        lazyRecommended: false,
        displayOrder: 1,
        baseName: 'vidu',
        isOfficialAPI: false,
        impactsKey: 'provider_vidu_impacts',
        fields: [
            { id: 'token', label: 'Token', type: 'text', placeholderKey: 'field_token_placeholder_vidu', required: true, helpTextKey: 'field_token_help_quick_register' }
        ],
        configKeyMap: { token: 'vidu.token' },
        testEndpoint: null
    }
];

// 翻译 provider 定义中的 i18n key
function translateProvider(p, tFn) {
    const translated = { ...p };
    translated.name = p.nameKey ? tFn(p.nameKey, p.nameKeyParams || {}) : (p.name || '');
    translated.description = p.descKey ? tFn(p.descKey, p.descKeyParams || {}) : (p.description || '');
    translated.impacts = p.impactsKey ? tFn(p.impactsKey).split(',').map(s => s.trim()) : (p.impacts || []);
    translated.docUrlLabel = p.docUrlLabelKey ? tFn(p.docUrlLabelKey) : (p.docUrlLabel || '');
    translated.fields = p.fields.map(f => ({
        ...f,
        label: f.labelKey ? tFn(f.labelKey) : (f.label || ''),
        placeholder: f.placeholderKey ? tFn(f.placeholderKey, f.placeholderParams || {}) : (f.placeholder || ''),
        helpText: f.helpTextKey ? tFn(f.helpTextKey) : (f.helpText || '')
    }));
    return translated;
}

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

            // i18n locale (reactive for computed properties)
            locale: localStorage.getItem('zjt_locale') || 'zh-CN',

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
                },
                modelAnalysis: {
                    days: 7,
                    startDate: '',
                    endDate: '',
                    selectedTypes: [],
                    chartMode: 'rate',
                    loading: false,
                    models: [],
                    daily: [],
                    expandedTypes: {},
                    charts: {
                        trend: null,
                        stacked: null,
                        rose: null
                    }
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

            // 敏感字段可见性控制（手机号、邮箱的小眼睛切换）
            visibleFields: {},

            marketingPublications: {
                list: [],
                total: 0,
                page: 1,
                pageSize: 20,
                statusFilter: 'pending',
                mediaTypeFilter: '',
                loading: false
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

            // 任务时间线（管理员排查用）
            taskTimeline: {
                queryType: 'project_id',  // project_id | ai_tool_id
                keyword: '',
                list: [],
                meta: null,
                expandedIdx: null,
                loading: false,
                error: ''
            },

            // 品牌定制（仅商业版）
            branding: {
                loading: false,
                saving: false,
                resetting: false,
                uploadingLogo: false,
                uploadingFavicon: false,
                uploadingTermsZh: false,
                uploadingTermsEn: false,
                uploadingWxGroupQr: false,
                isLogoCustom: false,
                isFaviconCustom: false,
                isTermsZhCustom: false,
                isTermsEnCustom: false,
                isWxGroupQrCustom: false,
                form: {
                    siteName: '',
                    logoUrl: '',
                    faviconUrl: '',
                    termsUrlZh: '',
                    termsUrlEn: '',
                    wxGroupQrUrl: ''
                }
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

            // RunningHub 密钥池
            runninghubKeyPool: {
                list: [],
                loading: false,
                globalApiKeyConfigured: true
            },

            // RunningHub 密钥编辑弹窗
            rhKeyEditModal: {
                show: false,
                index: null,
                apiKey: '',
                apiKeyMasked: '',
                label: '',
                maxSlots: 1,
                enabled: true,
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
                show: false,
                showWxGroup: false
            },

            // 官方微信群引导（来自 server-config）
            wxGroupGuideEnabled: false,
            wxGroupQrUrl: '',
            wxGroupQrProxyPath: '/api/system/wx-group-qr',

            // 实现方管理
            implementations: {
                groups: [],  // 分组数据
                loading: false,
                keyword: '',
                updating: null,  // 正在更新的实现方名称
                retryGlobalEnabled: false  // 供应商自动切换总开关
            },

            // 模型管理
            models: {
                list: [],
                loading: false,
                expanded: {},          // { modelId: true }
                billing: {},           // { modelId: billingPayload }
                billingLoading: {},    // { modelId: true }
                vendors: [],           // 供应商列表（添加档位用）
                updating: null         // 'tier-{id}'
            },

            // 大模型分段计费档位弹窗（主输入：元/百万）
            billingTierModal: {
                show: false,
                loading: false,
                modelId: null,
                modelName: '',
                tierId: null,
                vendor_id: null,
                unlimited: true,
                raw_token_threshold: null,
                input_yuan_per_m: 1,
                out_yuan_per_m: 2,
                cache_yuan_per_m: 0.2,
                commission_percent: 0
            },

            // AI 改档
            billingAi: {
                instruction: '',
                filterVendorId: null,
                llmKey: '',
                llmOptions: [],
                loading: false,
                applying: false,
                confirmShow: false,
                proposal: null,
                targetModelId: null
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

            // 媒体缓存管理（缓存目录 media_cache.cache_dir 不开放给用户配置）
            mediaCache: {
                enabled: false,
                maxDays: 30,
                maxSizeGb: 10,
                cleanupOnStartup: false,
                cleanupIntervalHours: 24,
                loading: false
            },

            // 默认按社区版处理，避免 dashboard 尚未返回时闪现商业入口。
            isCommunityEdition: true,
            runninghubKeyPoolAvailable: false,
            brandingAvailable: false,

            // 商业包状态与许可证状态分离：包成功导入决定是否展示卡片，
            // 完整注册决定是否允许提交 Token、刷新、恢复或注销。
            enterpriseStatus: {
                package_available: false,
                registration_ready: false,
                license_control_available: false,
                registration_failed: false,
                failure_reason: '',
                enterprise_version: null,
            },

            // 许可证状态轮询：仅用于改善前端显示及时性，不是安全边界。
            // 真正的权限边界由品牌 Provider 和品牌 API 的后端 403 保证。
            licensePollTimer: null,
            licenseStatusInFlight: false,

            // 许可证状态卡片（dashboard 顶部）：展示后端派生的 state/edition/revision，
            // 让管理员能自助诊断"为什么企业版却看不到品牌入口"等问题。
            licenseStatus: {
                loading: false,
                state: null,
                reason: '',
                enforcement_mode: '',
                capabilities: null,
                license: null,
                credential_configured: false,
            },
            // 激活表单输入框（激活成功后清空，失败时保留方便重试）。
            activateTokenInput: '',

            // 通知中心
            notifications: [],
            versionUpdate: null,
            missingBinaries: [],
            unreadCount: 0,
            typeLabels: {
                announcement: '公告',
                maintenance: '维护',
                feature: '新功能',
                security: '安全'
            },
            notificationsPollTimer: null,

            // 常量参考
            constants: {
                groups: [],
                mappings: [],
                loading: false,
                searchKeyword: '',
                groupFilter: '',
                typeFilter: ''
            },

            // 佣金管理
            commission: {
                list: [],
                total: 0,
                page: 1,
                pageSize: 20,
                loading: false,
                statusFilter: null  // null=全部, 0=待审核, 1=已打款, 2=已驳回
            },

            // 佣金审核弹窗
            commissionReviewModal: {
                show: false,
                action: '',  // 'approve' or 'reject'
                withdrawNo: '',
                amount: 0,
                method: '',
                account: '',
                rejectReason: '',
                loading: false
            },

            // 佣金比例上限
            commissionMaxRate: 0.5,
            commissionMaxRateModal: {
                show: false,
                newRate: 50,
                loading: false,
                affectedCount: null
            }
        };
    },
    
    computed: {
        totalPages() {
            return Math.ceil(this.users.total / this.users.pageSize);
        },

        enterprisePackageAvailable() {
            return Boolean(this.enterpriseStatus.package_available);
        },

        licenseControlAvailable() {
            return Boolean(this.enterpriseStatus.license_control_available);
        },

        // 激活表单显示条件：未配置凭据，或状态属于需要重新激活的异常态。
        // 已正常激活（credential_configured=true 且状态正常）时折叠隐藏。
        showActivateForm() {
            if (!this.licenseControlAvailable) return false;
            if (!this.licenseStatus.credential_configured) return true;
            return ['auth_required', 'denied', 'uninitialized'].includes(
                this.licenseStatus.state
            );
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

        // 顶部全局「负责模型」当前展示名
        billingAiCurrentLabel() {
            const opts = this.billingAi.llmOptions || [];
            const cur = opts.find(o => o.key === this.billingAi.llmKey);
            return cur ? cur.label : (this.billingAi.llmKey || 'deepseek-v4-pro');
        },

        filteredConstantsClasses() {
            let allClasses = [];
            for (const group of this.constants.groups) {
                if (this.constants.groupFilter && group.group_id !== this.constants.groupFilter) continue;
                for (const cls of group.classes) {
                    if (this.constants.typeFilter) {
                        const hasType = cls.members.some(m => m.type === this.constants.typeFilter);
                        if (!hasType) continue;
                    }
                    if (this.constants.searchKeyword) {
                        const kw = this.constants.searchKeyword.toLowerCase();
                        const match = cls.class_name.toLowerCase().includes(kw)
                            || cls.description.toLowerCase().includes(kw)
                            || cls.members.some(m => m.name.toLowerCase().includes(kw) || String(m.value).toLowerCase().includes(kw) || (m.label && m.label.toLowerCase().includes(kw)));
                        if (!match) continue;
                    }
                    allClasses.push(cls);
                }
            }
            return allClasses;
        },

        minDate() {
            const today = new Date();
            const year = today.getFullYear();
            const month = String(today.getMonth() + 1).padStart(2, '0');
            const day = String(today.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        },

        /**
         * HTTPS 页面 + HTTP 外链图 → 走后端同源代理，避免混合内容拦截
         */
        wxGroupQrDisplayUrl() {
            const url = this.wxGroupQrUrl;
            if (!url) return '';
            if (url.startsWith('/')) return url;
            try {
                const isHttpsPage = window.location && window.location.protocol === 'https:';
                if (isHttpsPage && /^http:\/\//i.test(url)) {
                    return this.wxGroupQrProxyPath || '/api/system/wx-group-qr';
                }
            } catch (e) {
                // ignore
            }
            return url;
        },

        // ===== 快速配置相关计算属性 =====

        providersByCategory() {
            const sortByOrder = (items) => [...items].sort((a, b) => (a.displayOrder || 999) - (b.displayOrder || 999));
            const result = {};
            Object.keys(CATEGORY_LABELS).forEach(cat => {
                // 支持 showInCategories 属性，让一个 provider 可以在多个分类中显示
                result[cat] = sortByOrder(PROVIDER_DEFINITIONS.filter(p =>
                    p.category === cat || (p.showInCategories && p.showInCategories.includes(cat))
                ).map(p => translateProvider(p, this.t.bind(this))));
            });
            return result;
        },

        lazyRecommendedProviderIds() {
            return PROVIDER_DEFINITIONS.filter(p => p.lazyRecommended).map(p => p.id);
        },

        selectedProvidersDetail() {
            // 依赖 locale 使其在语言切换时响应式更新
            const _ = this.locale;
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
                    impactSets[base] = new Set(p.impactsKey ? this.t(p.impactsKey).split(',').map(s => s.trim()) : (p.impacts || []));
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
                    const pImpacts = p.impactsKey ? this.t(p.impactsKey).split(',').map(s => s.trim()) : (p.impacts || []);
                    pImpacts.forEach(imp => impactSets[base].add(imp));
                    groups[base].impacts = [...impactSets[base]];
                }
            });

            // 翻译并返回
            const tFn = this.t.bind(this);
            return Object.values(groups).map(g => translateProvider(g, tFn)).sort((a, b) =>
                (a.displayOrder || 999) - (b.displayOrder || 999)
            );
        },

        categoryStatus() {
            const status = {};
            Object.keys(CATEGORY_LABELS).forEach(cat => { status[cat] = false; });
            this.quickConfigModal.selectedProviderIds.forEach(id => {
                const provider = PROVIDER_DEFINITIONS.find(p => p.id === id);
                if (provider) {
                    // 支持 showInCategories 属性
                    if (provider.showInCategories && provider.showInCategories.length > 0) {
                        provider.showInCategories.forEach(cat => {
                            if (cat !== 'other') status[cat] = true;
                        });
                    } else if (provider.category !== 'other') {
                        status[provider.category] = true;
                    }
                }
            });
            return status;
        },

        // 与右侧配置卡片一致：按 baseName 去重（多米生图+生视频、火山多分类等只算 1 个）
        selectedCount() {
            return this.selectedProvidersDetail.length;
        },

        configuredCount() {
            return this.selectedProvidersDetail.filter(p => this.isProviderConfigured(p.id)).length;
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
        categoryLabels() {
            // 依赖 locale 使其在语言切换时响应式更新
            const _ = this.locale;
            return {
                llm: this.t('category_llm'),
                image: this.t('category_image'),
                video: this.t('category_video'),
                other: this.t('category_other')
            };
        },
        categoryDescriptions() {
            const _ = this.locale;
            return {
                llm: this.t('category_llm_desc'),
                image: this.t('category_image_desc'),
                video: this.t('category_video_desc'),
                other: this.t('category_other_desc')
            };
        },

        commissionTotalPages() {
            return Math.ceil(this.commission.total / this.commission.pageSize);
        }
    },
    
    mounted() {
        this.initI18n().then(() => {
            this.initModelAnalysisDates();
            window.addEventListener('resize', this.resizeModelAnalysisCharts);
            this.initAuth();
            this.fetchServerConfig();
            this.pollNotifications();
            this.notificationsPollTimer = setInterval(() => this.pollNotifications(), 30000);
            // 许可证状态轮询：管理员身份验证在 initAuth 内完成，
            // 这里仅启动定时器；首次拉取在 initAuth 成功后触发。
            this.licensePollTimer = setInterval(() => this.pollLicenseStatus(), 60000);
        });
    },

    unmounted() {
        window.removeEventListener('resize', this.resizeModelAnalysisCharts);
        if (this.notificationsPollTimer) clearInterval(this.notificationsPollTimer);
        if (this.licensePollTimer) clearInterval(this.licensePollTimer);
        Object.values(this.dashboard.modelAnalysis.charts || {}).forEach(chart => {
            if (chart) chart.dispose();
        });
    },

    methods: {
        // 认证错误处理（401 清除本地存储并跳转登录；403 为"已登录但非管理员"，保留登录态仅跳转）
        handleAuthError(status) {
            if (status === 401) {
                localStorage.removeItem('auth_token');
                localStorage.removeItem('phone');
                localStorage.removeItem('email');
                localStorage.removeItem('user_id');
                localStorage.removeItem('invite_code');
                window.location.href = '/index.html';
            } else if (status === 403) {
                window.location.href = '/index.html';
            }
        },

        // i18n 翻译方法（引用 this.locale 使其响应式）
        t(key, params = {}) {
            // this.locale 是响应式依赖，语言切换时会触发模板重新渲染
            const _ = this.locale;
            if (window.ZJTi18n) {
                return window.ZJTi18n.t(key, params) || key;
            }
            return key;
        },

        // 初始化 i18n
        async initI18n() {
            if (window.ZJTi18n) {
                const locale = localStorage.getItem('zjt_locale') || 'zh-CN';
                await window.ZJTi18n.setLocale(locale, ['admin', 'common']);
                this.locale = locale;

                // 监听语言变化事件（由切换器触发）
                window.ZJTi18n.on('locale-changed', (data) => {
                    this.locale = data.locale || window.ZJTi18n.getLocale();
                    this.$nextTick(() => {
                        if (window.ZJTi18nDOM) {
                            window.ZJTi18nDOM.scanDOM(document.body);
                        }
                    });
                });

                this.$nextTick(() => {
                    if (window.ZJTi18nDOM) {
                        window.ZJTi18nDOM.scanDOM(document.body);
                    }
                    if (window.ZJTi18nSwitcher) {
                        window.ZJTi18nSwitcher.render('i18nSwitcher');
                    }
                });
            }
        },

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
                    this.wxGroupGuideEnabled = !!response.data.data.wx_group_guide_enabled;
                    this.wxGroupQrUrl = response.data.data.wx_group_qr_url || '';
                    this.wxGroupQrProxyPath = response.data.data.wx_group_qr_proxy_path
                        || '/api/system/wx-group-qr';
                }
            } catch (error) {
                console.error('Failed to fetch server config:', error);
            }
        },

        // 初始化认证
        initAuth() {
            this.authToken = localStorage.getItem('auth_token') || '';
            
            if (!this.authToken) {
                this.showToast(this.t('toast_login_required'), 'error');
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

                    this.isCommunityEdition = Boolean(
                        response.data.data.is_community_edition
                    );
                    this.applyEnterpriseStatus(response.data.data.enterprise);
                    this.runninghubKeyPoolAvailable = Boolean(
                        response.data.data.features?.runninghub_key_pool
                    );
                    // 品牌定制可用性由后端 features.branding 派生，前端不重复实现授权规则。
                    this.applyBrandingAvailability(response.data.data.features?.branding);

                    // 默认加载用户列表
                    this.loadUsers();

                    // 默认加载模型成功率分析
                    this.loadModelAnalysis();

                    // 检查 URL 参数，是否需要自动打开快速配置
                    this.checkQuickConfigParam();

                    // 首次拉取许可证状态（不等待第一个 60 秒），
                    // 用于在管理员打开页面后立即同步最新的品牌权限。
                    this.pollLicenseStatus();
                }
            } catch (error) {
                console.error('Admin verification failed:', error);
                const detail = error?.response?.data?.detail || '';
                if (detail.includes('管理员权限') || error?.response?.status === 403) {
                    this.showToast(this.t('toast_no_admin_permission'), 'error');
                    setTimeout(() => {
                        window.location.href = '/';
                    }, 1500);
                } else if (error?.response?.status === 401) {
                    this.showToast(this.t('toast_login_expired'), 'error');
                    setTimeout(() => {
                        window.location.href = '/?login=1&redirect_url=/admin';
                    }, 1500);
                } else {
                    this.showToast(this.t('toast_load_failed') + ': ' + detail, 'error');
                }
            }
        },

        // 统一应用品牌定制可用性。dashboard 接口和许可证状态轮询都调用它，
        // 避免在不同入口重复实现授权判断。当可用性从 true 变 false 且用户
        // 正停留在品牌页时，自动切回仪表盘并提示。
        applyBrandingAvailability(available) {
            const wasAvailable = this.brandingAvailable;
            this.brandingAvailable = Boolean(available);

            if (
                wasAvailable &&
                !this.brandingAvailable &&
                this.currentPage === 'branding'
            ) {
                this.currentPage = 'dashboard';
                this.loadDashboard();
                this.showToast(this.t('branding_permission_revoked'), 'warning');
            }
        },

        applyEnterpriseStatus(data) {
            this.enterpriseStatus = {
                package_available: Boolean(data?.package_available),
                registration_ready: Boolean(data?.registration_ready),
                license_control_available: Boolean(
                    data?.license_control_available
                ),
                registration_failed: Boolean(data?.registration_failed),
                failure_reason: data?.failure_reason || '',
                enterprise_version: data?.enterprise_version || null,
            };

            // 控制面不可用时不得保留旧的许可证/品牌可用状态，也不得继续轮询。
            if (!this.enterpriseStatus.license_control_available) {
                this.licenseStatus = {
                    loading: false,
                    state: null,
                    reason: '',
                    enforcement_mode: '',
                    capabilities: null,
                    license: null,
                    credential_configured: false,
                };
                this.applyBrandingAvailability(false);
            }
        },

        // 统一把后端 status 响应应用到本地：同时刷新状态卡片和品牌可用性，
        // 保证 dashboard 卡片、菜单可见性、轮询三者数据一致。
        applyLicenseStatus(data) {
            this.licenseStatus = {
                loading: false,
                state: data?.state || null,
                reason: data?.reason || '',
                enforcement_mode: data?.enforcement_mode || '',
                capabilities: data?.capabilities || null,
                license: data?.license || null,
                credential_configured: Boolean(data?.credential_configured),
            };
            this.applyBrandingAvailability(data?.capabilities?.branding);
        },

        // 许可证状态卡片样式类（按 state 着色）：直接用 licenseStatus.state，
        // 模板里 :class="licenseStatus.state || 'uninitialized'"，无需此方法。

        // 显式加载一次许可证状态（用于切到 dashboard 时刷新卡片）。
        async loadLicenseStatus() {
            if (!this.licenseControlAvailable) return;
            if (!this.authToken) return;
            this.licenseStatus.loading = true;
            try {
                const response = await axios.get(
                    '/api/admin/commercial-license/status',
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                if (response.data?.code === 0) {
                    this.applyLicenseStatus(response.data.data);
                }
            } catch (error) {
                const status = error?.response?.status;
                if (status === 401 || status === 403) {
                    this.handleAuthError(status);
                }
            } finally {
                this.licenseStatus.loading = false;
            }
        },

        // 许可证状态轮询：读取后端派生的 capabilities.branding（单一数据源），
        // 不在前端解析 edition/claims。临时网络错误保持上次结果；
        // 401/403 走现有认证失效流程。
        async pollLicenseStatus() {
            // 许可证控制面未完整注册时跳过，避免社区版和注册失败状态打 404。
            if (!this.licenseControlAvailable) return;
            if (this.licenseStatusInFlight) return;
            if (!this.authToken) return;
            this.licenseStatusInFlight = true;
            try {
                const response = await axios.get(
                    '/api/admin/commercial-license/status',
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                if (response.data?.code === 0) {
                    this.applyLicenseStatus(response.data.data);
                }
            } catch (error) {
                const status = error?.response?.status;
                if (status === 401 || status === 403) {
                    this.handleAuthError(status);
                }
                // 其它（网络/超时/5xx）保持上次结果，安全边界由品牌 API 403 兜底。
            } finally {
                this.licenseStatusInFlight = false;
            }
        },

        // 立即刷新租约（不等后台 60s 轮询）。用于确认是否已取得新 revision。
        async refreshLicense() {
            await this._postLicenseAction('/api/admin/commercial-license/refresh', 'license_btn_refresh');
        },

        // 恢复许可证：清除本地注销标记并重新 lease。
        // 这是解决"企业版却看不到品牌入口（因本地已注销）"问题的关键入口。
        async reactivateLicense() {
            await this._postLicenseAction('/api/admin/commercial-license/reactivate', 'license_btn_reactivate');
        },

        // 注销许可证：本地注销并停止后台刷新。会再次触发"看不到品牌入口"现象，
        // 因此需要二次确认。
        async confirmDeactivateLicense() {
            if (!confirm(this.t('license_deactivate_confirm'))) return;
            await this._postLicenseAction('/api/admin/commercial-license/deactivate', 'license_btn_deactivate');
        },

        // 三个操作的公共实现：POST 后用最新 status 覆盖本地状态并提示。
        async _postLicenseAction(url, actionKey) {
            if (!this.licenseControlAvailable) return;
            if (!this.authToken || this.licenseStatusInFlight) return;
            this.licenseStatusInFlight = true;
            try {
                const response = await axios.post(url, null, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` },
                });
                if (response.data?.code === 0) {
                    this.applyLicenseStatus(response.data.data);
                    this.showToast(this.t('license_action_done'), 'success');
                }
            } catch (error) {
                const status = error?.response?.status;
                if (status === 401 || status === 403) {
                    this.handleAuthError(status);
                } else {
                    this.showToast(
                        this.t('license_action_failed') + ': ' + (error?.response?.data?.detail || ''),
                        'error'
                    );
                }
            } finally {
                this.licenseStatusInFlight = false;
            }
        },

        // 用候选 Token 原子化激活许可证。后端会先试 lease+验签（不落盘），
        // 成功后才落盘、清注销标记、刷新状态；失败时保留旧凭据、不清空输入框。
        async activateLicense() {
            if (!this.licenseControlAvailable) return;
            const token = (this.activateTokenInput || '').trim();
            if (!token) {
                this.showToast(this.t('license_activate_empty'), 'warning');
                return;
            }
            if (!this.authToken || this.licenseStatusInFlight) return;
            this.licenseStatusInFlight = true;
            try {
                const response = await axios.post(
                    '/api/admin/commercial-license/activate',
                    { account_token: token },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                if (response.data?.code === 0) {
                    this.applyLicenseStatus(response.data.data);
                    // 成功后清空输入框（敏感信息不应在前端残留）。
                    this.activateTokenInput = '';
                    // 按 edition 区分提示，避免 studio 用户以为激活失败。
                    const edition = response.data.data?.license?.edition;
                    if (edition === 'studio') {
                        this.showToast(this.t('license_activate_success_studio'), 'warning');
                    } else {
                        this.showToast(this.t('license_activate_success_enterprise'), 'success');
                    }
                }
            } catch (error) {
                const status = error?.response?.status;
                if (status === 401 || status === 403) {
                    this.handleAuthError(status);
                } else {
                    // 失败不清空输入框，方便用户修改后重试；不改动本地状态。
                    this.showToast(
                        this.t('license_activate_failed') + ': ' + (error?.response?.data?.detail || ''),
                        'error'
                    );
                }
            } finally {
                this.licenseStatusInFlight = false;
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
                    this.showToast(this.t('toast_welcome_admin'), 'success');
                }, 500);
                // 清除 URL 参数
                window.history.replaceState({}, document.title, '/admin');
            }
        },
        
        // 切换页面
        switchPage(page) {
            // 品牌页前置拒绝：避免缓存残留导致无权限用户进入品牌页。
            // 真正的安全边界仍由品牌 API 的 403 保证。
            if (page === 'branding' && !this.brandingAvailable) {
                this.currentPage = 'dashboard';
                return;
            }
            this.currentPage = page;
            if (page === 'dashboard') {
                this.loadDashboard();
                // 切到仪表盘时刷新许可证状态卡片（商业版才有数据）。
                this.loadLicenseStatus();
            } else if (page === 'users') {
                this.loadUsers();
            } else if (page === 'config') {
                this.loadConfigs();
            } else if (page === 'checkin') {
                this.loadCheckinConfig();
            } else if (page === 'mediaCache') {
                this.loadMediaCacheConfig();
            } else if (page === 'implementations') {
                this.loadImplementations();
            } else if (page === 'runninghubKeyPool') {
                if (this.runninghubKeyPoolAvailable) {
                    this.loadRunninghubKeyPool();
                }
            } else if (page === 'marketingPublications') {
                this.loadMarketingPublications();
            } else if (page === 'models') {
                this.loadModels();
            } else if (page === 'constants') {
                this.loadConstants();
            } else if (page === 'commission') {
                if (!this.isCommunityEdition) {
                    this.loadCommissionWithdrawals();
                    this.loadCommissionMaxRate();
                }
            } else if (page === 'taskTimeline') {
                // 任务时间线：按需手动查询，不自动加载
            } else if (page === 'branding') {
                if (this.brandingAvailable) {
                    this.loadBranding();
                }
            }
        },

        async loadTaskTimeline() {
            const kw = (this.taskTimeline.keyword || '').trim();
            if (!kw) {
                this.taskTimeline.error = this.t('timeline_input_required');
                this.taskTimeline.list = [];
                this.taskTimeline.meta = null;
                return;
            }
            this.taskTimeline.loading = true;
            this.taskTimeline.error = '';
            this.taskTimeline.expandedIdx = null;
            try {
                const params = {};
                if (this.taskTimeline.queryType === 'project_id') {
                    params.project_id = kw;
                } else {
                    const id = parseInt(kw, 10);
                    if (isNaN(id) || id <= 0) {
                        this.taskTimeline.error = this.t('timeline_invalid_ai_tool_id');
                        this.taskTimeline.list = [];
                        this.taskTimeline.meta = null;
                        return;
                    }
                    params.ai_tool_id = id;
                }
                const response = await axios.get('/api/admin/ai-tools/timeline', {
                    params,
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                const data = (response.data && response.data.data) || {};
                this.taskTimeline.list = data.timeline || [];
                this.taskTimeline.meta = {
                    ai_tool_id: data.ai_tool_id,
                    project_id: data.project_id,
                    status: data.status
                };
            } catch (err) {
                this.taskTimeline.error = (err && err.response && err.response.data && (err.response.data.detail || err.response.data.message)) || this.t('timeline_load_failed');
                this.taskTimeline.list = [];
                this.taskTimeline.meta = null;
            } finally {
                this.taskTimeline.loading = false;
            }
        },
        toggleTimelineDetail(idx) {
            this.taskTimeline.expandedIdx = (this.taskTimeline.expandedIdx === idx) ? null : idx;
        },
        timelineEventLabel(type) {
            const map = {
                record_created: '记录创建', task_started: '开始处理', slot_delayed: '槽位延迟',
                implementation_selected: '选定实现方', submitted: '已提交', status_check: '状态轮询',
                upstream_succeeded: '上游成功', upstream_failed: '上游失败', download_started: '开始下载',
                download_completed: '下载完成', cdn_uploaded: 'CDN上传', retry_scheduled: '安排重试',
                max_retry_exceeded: '重试上限', task_completed: '任务完成', exception: '异常', pipeline_step: '流水线步骤'
            };
            return map[type] || type;
        },

        // ==================== 品牌定制（仅商业版） ====================

        async loadBranding() {
            this.branding.loading = true;
            try {
                const response = await axios.get('/api/admin/branding', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data && response.data.code === 0) {
                    const d = response.data.data;
                    this.branding.form.siteName = d.site_name || '';
                    this.branding.form.logoUrl = d.logo_url || '';
                    this.branding.form.faviconUrl = d.favicon_url || '';
                    this.branding.form.termsUrlZh = d.terms_url_zh || '';
                    this.branding.form.termsUrlEn = d.terms_url_en || '';
                    this.branding.form.wxGroupQrUrl = d.wx_group_qr_url || '';
                    this.branding.isLogoCustom = !!d.is_logo_custom;
                    this.branding.isFaviconCustom = !!d.is_favicon_custom;
                    this.branding.isTermsZhCustom = !!d.is_terms_zh_custom;
                    this.branding.isTermsEnCustom = !!d.is_terms_en_custom;
                    this.branding.isWxGroupQrCustom = !!d.is_wx_group_qr_custom;
                }
            } catch (err) {
                const msg = (err && err.response && err.response.data && (err.response.data.detail || err.response.data.message)) || this.t('branding_load_failed');
                this.showToast(msg, 'error');
            } finally {
                this.branding.loading = false;
            }
        },

        async saveBranding() {
            this.branding.saving = true;
            try {
                const response = await axios.put('/api/admin/branding', {
                    site_name: this.branding.form.siteName
                }, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data && response.data.code === 0) {
                    this.showToast(response.data.message || this.t('branding_save_success'), 'success');
                } else {
                    this.showToast((response.data && response.data.message) || this.t('branding_save_failed'), 'error');
                }
            } catch (err) {
                const msg = (err && err.response && err.response.data && (err.response.data.detail || err.response.data.message)) || this.t('branding_save_failed');
                this.showToast(msg, 'error');
            } finally {
                this.branding.saving = false;
            }
        },

        async uploadBrandingAsset(assetType, event) {
            const file = event.target.files && event.target.files[0];
            if (!file) return;
            // 清空 input value 以便重复选择同一文件
            event.target.value = '';

            // 设置对应上传中状态
            const uploadingKey = {
                logo: 'uploadingLogo',
                favicon: 'uploadingFavicon',
                terms_zh: 'uploadingTermsZh',
                terms_en: 'uploadingTermsEn',
                wx_group_qr: 'uploadingWxGroupQr'
            }[assetType];
            if (uploadingKey) this.branding[uploadingKey] = true;

            const formData = new FormData();
            formData.append('file', file);
            formData.append('asset_type', assetType);

            try {
                const response = await axios.post('/api/admin/branding/upload', formData, {
                    headers: {
                        'Authorization': `Bearer ${this.authToken}`,
                        'Content-Type': 'multipart/form-data'
                    }
                });
                if (response.data && response.data.code === 0) {
                    // 刷新全部配置（拿到新的 URL 和 is_*_custom 标志）
                    await this.loadBranding();
                    this.showToast(response.data.message || this.t('branding_upload_success'), 'success');
                } else {
                    this.showToast((response.data && response.data.message) || this.t('branding_upload_failed'), 'error');
                }
            } catch (err) {
                const msg = (err && err.response && err.response.data && (err.response.data.detail || err.response.data.message)) || this.t('branding_upload_failed');
                this.showToast(msg, 'error');
            } finally {
                if (uploadingKey) this.branding[uploadingKey] = false;
            }
        },

        async resetBranding() {
            if (!confirm(this.t('branding_reset_confirm'))) return;
            this.branding.resetting = true;
            try {
                const response = await axios.post('/api/admin/branding/reset', {}, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data && response.data.code === 0) {
                    await this.loadBranding();
                    this.showToast(response.data.message || this.t('branding_reset_success'), 'success');
                } else {
                    this.showToast((response.data && response.data.message) || this.t('branding_reset_failed'), 'error');
                }
            } catch (err) {
                const msg = (err && err.response && err.response.data && (err.response.data.detail || err.response.data.message)) || this.t('branding_reset_failed');
                this.showToast(msg, 'error');
            } finally {
                this.branding.resetting = false;
            }
        },

        async loadMarketingPublications(page = 1) {
            this.marketingPublications.loading = true;
            this.marketingPublications.page = page;
            try {
                const response = await axios.get('/api/admin/marketing-publications', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` },
                    params: {
                        page: this.marketingPublications.page,
                        page_size: this.marketingPublications.pageSize,
                        status: this.marketingPublications.statusFilter || undefined,
                        media_type: this.marketingPublications.mediaTypeFilter || undefined
                    }
                });
                if (response.data.code === 0) {
                    const data = response.data.data || {};
                    this.marketingPublications.list = data.data || [];
                    this.marketingPublications.total = data.total || 0;
                }
            } catch (error) {
                this.showToast(error.response?.data?.detail || this.t('marketing_review_load_failed'), 'error');
            } finally {
                this.marketingPublications.loading = false;
            }
        },

        async reviewMarketingPublication(item, action) {
            const note = action === 'reject' ? window.prompt(this.t('marketing_review_reject_reason'), '') : '';
            if (action === 'reject' && note === null) return;
            try {
                const response = await axios.post(
                    `/api/admin/marketing-publications/${item.id}/${action}`,
                    { review_note: note || '' },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                if (response.data.code === 0) {
                    this.showToast(this.t('operation_success'), 'success');
                    this.loadMarketingPublications(this.marketingPublications.page);
                }
            } catch (error) {
                this.showToast(error.response?.data?.detail || this.t('operation_failed'), 'error');
            }
        },

        getMarketingStatusText(status) {
            const map = {
                pending: this.t('marketing_status_pending'),
                approved: this.t('marketing_status_approved'),
                rejected: this.t('marketing_status_rejected'),
                hidden: this.t('marketing_status_hidden'),
                cancelled: this.t('marketing_status_cancelled')
            };
            return map[status] || status;
        },
        
        // 加载仪表盘
        async loadDashboard() {
            this.dashboard.loading = true;
            try {
                const response = await axios.get('/api/admin/dashboard', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    this.isCommunityEdition = Boolean(
                        response.data.data.is_community_edition
                    );
                    this.applyEnterpriseStatus(response.data.data.enterprise);
                    this.dashboard.totalUsers = response.data.data.total_users;
                    this.dashboard.activeWorkflows3d = response.data.data.active_workflows_3d;
                    // dashboard 的 features.branding 由后端动态派生，这里同步一次
                    // 品牌可用性，避免在许可证状态轮询暂时失败时菜单停留在旧状态。
                    // 安全边界仍由品牌 API 的后端 403 保证，此处仅为缩短前端陈旧窗口。
                    this.applyBrandingAvailability(response.data.data.features?.branding);
                }
            } catch (error) {
                console.error('Load dashboard failed:', error);
                this.showToast(this.t('toast_load_dashboard_failed'), 'error');
            } finally {
                this.dashboard.loading = false;
            }

            // 同步加载模型成功率分析
            this.loadModelAnalysis();
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
                this.showToast(this.t('toast_query_monthly_failed'), 'error');
            } finally {
                this.dashboard.monthlyActiveUsers.loading = false;
            }
        },

        // 加载模型分析数据
        async loadModelAnalysis() {
            this.dashboard.modelAnalysis.loading = true;
            let shouldRenderCharts = false;
            try {
                const params = { days: this.dashboard.modelAnalysis.days };
                if (this.dashboard.modelAnalysis.startDate) {
                    params.start_date = this.dashboard.modelAnalysis.startDate;
                }
                if (this.dashboard.modelAnalysis.endDate) {
                    params.end_date = this.dashboard.modelAnalysis.endDate;
                }

                const response = await axios.get('/api/admin/dashboard/model-analysis', {
                    params,
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    const models = response.data.data.models || [];
                    this.dashboard.modelAnalysis.models = models;
                    this.dashboard.modelAnalysis.daily = response.data.data.daily || [];

                    const availableTypes = models.map(model => model.type);
                    const selectedTypes = (this.dashboard.modelAnalysis.selectedTypes || [])
                        .filter(type => availableTypes.includes(type));
                    this.dashboard.modelAnalysis.selectedTypes = selectedTypes.length ? selectedTypes : availableTypes;
                    shouldRenderCharts = true;
                }
            } catch (error) {
                console.error('Load model analysis failed:', error);
                this.showToast(this.t('toast_load_model_failed'), 'error');
            } finally {
                this.dashboard.modelAnalysis.loading = false;
            }

            // 在 loading 设为 false 之后渲染图表，使用 setTimeout 确保 v-else-if 的 DOM 已完全就绪
            if (shouldRenderCharts) {
                setTimeout(() => this.renderModelAnalysisCharts(), 100);
            }
        },

        // 切换模型分析时间范围
        setModelAnalysisDays(days) {
            this.dashboard.modelAnalysis.days = days;
            this.setModelAnalysisDateRangeFromDays(days);
            this.dashboard.modelAnalysis.expandedTypes = {};
            this.dashboard.modelAnalysis.daily = [];
            this.loadModelAnalysis();
        },

        initModelAnalysisDates() {
            this.setModelAnalysisDateRangeFromDays(this.dashboard.modelAnalysis.days || 1);
        },

        setModelAnalysisDateRangeFromDays(days) {
            const end = new Date();
            const start = new Date();
            start.setDate(end.getDate() - Math.max(days - 1, 0));
            this.dashboard.modelAnalysis.startDate = this.formatDateInput(start);
            this.dashboard.modelAnalysis.endDate = this.formatDateInput(end);
        },

        formatDateInput(date) {
            const year = date.getFullYear();
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const day = String(date.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        },

        handleModelAnalysisDateChange() {
            const { startDate, endDate } = this.dashboard.modelAnalysis;
            if (startDate && endDate) {
                const start = new Date(startDate);
                const end = new Date(endDate);
                if (start > end) {
                    this.dashboard.modelAnalysis.endDate = startDate;
                } else {
                    const diffMs = end.getTime() - start.getTime();
                    this.dashboard.modelAnalysis.days = Math.min(Math.floor(diffMs / 86400000) + 1, 30);
                }
            }
            this.dashboard.modelAnalysis.expandedTypes = {};
            this.loadModelAnalysis();
        },

        setModelAnalysisChartMode(mode) {
            this.dashboard.modelAnalysis.chartMode = mode;
            this.$nextTick(() => this.renderModelTrendChart());
        },

        selectAllModelAnalysisTypes() {
            this.dashboard.modelAnalysis.selectedTypes = (this.dashboard.modelAnalysis.models || []).map(model => model.type);
            this.$nextTick(() => this.renderModelAnalysisCharts());
        },

        clearModelAnalysisTypes() {
            this.dashboard.modelAnalysis.selectedTypes = [];
            this.$nextTick(() => this.renderModelAnalysisCharts());
        },

        toggleModelAnalysisType(type) {
            const selected = new Set(this.dashboard.modelAnalysis.selectedTypes || []);
            if (selected.has(type)) {
                selected.delete(type);
            } else {
                selected.add(type);
            }
            this.dashboard.modelAnalysis.selectedTypes = Array.from(selected);
            this.$nextTick(() => this.renderModelAnalysisCharts());
        },

        isModelAnalysisTypeSelected(type) {
            return (this.dashboard.modelAnalysis.selectedTypes || []).includes(type);
        },

        // 展开/折叠模型供应商详情
        toggleModelExpand(type) {
            this.dashboard.modelAnalysis.expandedTypes[type] = !this.dashboard.modelAnalysis.expandedTypes[type];
        },

        // 成功率颜色类
        getRateClass(rate) {
            if (rate >= 90) return 'rate-high';
            if (rate >= 70) return 'rate-medium';
            return 'rate-low';
        },

        getModelAnalysisSummary() {
            const models = this.dashboard.modelAnalysis.models || [];
            const total = models.reduce((sum, model) => sum + (model.total || 0), 0);
            const success = models.reduce((sum, model) => sum + (model.success || 0), 0);
            const fail = models.reduce((sum, model) => sum + (model.fail || 0), 0);
            return {
                total,
                success,
                fail,
                successRate: total > 0 ? (success / total) * 100 : 0
            };
        },

        sortedModelAnalysisModels() {
            return [...(this.dashboard.modelAnalysis.models || [])]
                .filter(model => (model.total || 0) > 0)
                .sort((a, b) => (b.total || 0) - (a.total || 0));
        },

        getDailyTrendItems() {
            return this.dashboard.modelAnalysis.daily || [];
        },

        getSelectedModelAnalysisModels() {
            const selected = new Set(this.dashboard.modelAnalysis.selectedTypes || []);
            return this.sortedModelAnalysisModels().filter(model => selected.has(model.type));
        },

        getModelColor(index) {
            const colors = ['#2563eb', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316', '#14b8a6', '#e11d48', '#64748b'];
            return colors[index % colors.length];
        },

        getDailyModelValue(day, type, field) {
            const item = (day.models || []).find(model => model.type === type);
            return item ? (item[field] || 0) : 0;
        },

        getModelChartBaseOption() {
            return {
                backgroundColor: 'transparent',
                textStyle: {
                    color: '#334155',
                    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
                },
                tooltip: {
                    trigger: 'axis',
                    backgroundColor: 'rgba(15, 23, 42, 0.92)',
                    borderWidth: 0,
                    textStyle: { color: '#fff' },
                    axisPointer: { type: 'cross' }
                },
                legend: {
                    type: 'scroll',
                    top: 0,
                    textStyle: { color: '#475569' }
                },
                grid: {
                    left: 48,
                    right: 58,
                    top: 58,
                    bottom: 36,
                    containLabel: true
                }
            };
        },

        ensureModelChart(refName, key) {
            if (!window.echarts) {
                this.showToast(this.t('model_chart_dependency_missing'), 'error');
                return null;
            }
            const el = this.$refs[refName];
            if (!el) return null;
            const cached = this.dashboard.modelAnalysis.charts[key];
            if (cached && cached.getDom() !== el) {
                cached.dispose();
                this.dashboard.modelAnalysis.charts[key] = null;
            }
            if (!this.dashboard.modelAnalysis.charts[key]) {
                const chart = window.echarts.init(el);
                this.dashboard.modelAnalysis.charts[key] = Vue.markRaw ? Vue.markRaw(chart) : chart;
            }
            return this.dashboard.modelAnalysis.charts[key];
        },

        renderModelAnalysisCharts() {
            if (!this.dashboard.modelAnalysis.models.length) return;
            this.renderModelTrendChart();
            this.renderModelStackedChart();
            this.renderModelRoseChart();
        },

        renderModelTrendChart() {
            const chart = this.ensureModelChart('modelTrendChart', 'trend');
            if (!chart) return;
            const daily = this.getDailyTrendItems();
            const models = this.getSelectedModelAnalysisModels();
            const dates = daily.map(day => day.date);
            const mode = this.dashboard.modelAnalysis.chartMode;
            const series = [];

            console.log('[TrendChart] mode:', mode, 'models:', models.length, 'daily:', daily.length);

            models.forEach((model, index) => {
                const color = this.getModelColor(index);
                if (mode === 'rate' || mode === 'both') {
                    const rateData = daily.map(day => this.getDailyModelValue(day, model.type, 'success_rate'));
                    console.log('[TrendChart] Rate series for', model.name, ':', rateData);
                    series.push({
                        name: `${model.name} ${this.t('model_chart_mode_rate')}`,
                        type: 'line',
                        smooth: true,
                        yAxisIndex: 0,
                        symbolSize: 7,
                        lineStyle: { width: 3, color },
                        itemStyle: { color },
                        data: rateData
                    });
                }
                if (mode === 'count' || mode === 'both') {
                    const countData = daily.map(day => this.getDailyModelValue(day, model.type, 'total'));
                    console.log('[TrendChart] Count series for', model.name, ':', countData);
                    series.push({
                        name: `${model.name} ${this.t('model_chart_mode_count')}`,
                        type: 'line',
                        smooth: true,
                        yAxisIndex: 1,
                        symbolSize: 6,
                        lineStyle: { width: 2, type: 'dashed', color },
                        itemStyle: { color },
                        data: countData
                    });
                }
            });

            console.log('[TrendChart] Total series count:', series.length);

            chart.setOption({
                ...this.getModelChartBaseOption(),
                xAxis: {
                    type: 'category',
                    data: dates,
                    boundaryGap: false,
                    axisLine: { lineStyle: { color: '#cbd5e1' } },
                    axisLabel: { color: '#64748b' }
                },
                yAxis: [
                    {
                        type: 'value',
                        name: this.t('model_chart_mode_rate'),
                        min: 0,
                        max: 100,
                        axisLabel: { formatter: '{value}%' },
                        splitLine: { lineStyle: { color: '#e2e8f0' } }
                    },
                    {
                        type: 'value',
                        name: this.t('model_chart_mode_count'),
                        min: 0,
                        axisLabel: { formatter: '{value}' },
                        splitLine: { show: false }
                    }
                ],
                series
            }, true);
        },

        renderModelStackedChart() {
            const chart = this.ensureModelChart('modelStackedChart', 'stacked');
            if (!chart) return;
            const daily = this.getDailyTrendItems();
            const models = this.getSelectedModelAnalysisModels();
            chart.setOption({
                ...this.getModelChartBaseOption(),
                tooltip: {
                    trigger: 'axis',
                    axisPointer: { type: 'shadow' },
                    backgroundColor: 'rgba(15, 23, 42, 0.92)',
                    borderWidth: 0,
                    textStyle: { color: '#fff' }
                },
                xAxis: {
                    type: 'category',
                    data: daily.map(day => day.date),
                    axisLine: { lineStyle: { color: '#cbd5e1' } },
                    axisLabel: { color: '#64748b' }
                },
                yAxis: {
                    type: 'value',
                    name: this.t('model_chart_mode_count'),
                    splitLine: { lineStyle: { color: '#e2e8f0' } }
                },
                series: models.map((model, index) => ({
                    name: model.name,
                    type: 'bar',
                    stack: 'models',
                    barMaxWidth: 42,
                    itemStyle: { color: this.getModelColor(index), borderRadius: [3, 3, 0, 0] },
                    data: daily.map(day => this.getDailyModelValue(day, model.type, 'total'))
                }))
            }, true);
        },

        renderModelRoseChart() {
            const chart = this.ensureModelChart('modelRoseChart', 'rose');
            if (!chart) return;
            const models = this.getSelectedModelAnalysisModels();
            chart.setOption({
                backgroundColor: 'transparent',
                tooltip: {
                    trigger: 'item',
                    backgroundColor: 'rgba(15, 23, 42, 0.92)',
                    borderWidth: 0,
                    textStyle: { color: '#fff' }
                },
                legend: {
                    type: 'scroll',
                    orient: 'vertical',
                    right: 10,
                    top: 20,
                    bottom: 20,
                    textStyle: { color: '#475569' }
                },
                series: [{
                    name: this.t('model_chart_rose_volume'),
                    type: 'pie',
                    roseType: 'radius',
                    radius: ['24%', '72%'],
                    center: ['42%', '52%'],
                    label: {
                        formatter: '{b}: {c}',
                        color: '#334155'
                    },
                    itemStyle: {
                        borderColor: '#fff',
                        borderWidth: 2
                    },
                    data: models.map((model, index) => ({
                        name: model.name,
                        value: model.total || 0,
                        itemStyle: { color: this.getModelColor(index) }
                    }))
                }]
            }, true);
        },

        resizeModelAnalysisCharts() {
            const charts = this.dashboard?.modelAnalysis?.charts || {};
            Object.values(charts).forEach(chart => {
                if (chart) chart.resize();
            });
        },

        // 格式化耗时（毫秒 → 可读字符串）
        formatDuration(ms) {
            if (ms < 1000) return ms + 'ms';
            const seconds = Math.round(ms / 1000);
            if (seconds < 60) return seconds + 's';
            const minutes = Math.floor(seconds / 60);
            const remainSeconds = seconds % 60;
            return minutes + 'm' + (remainSeconds > 0 ? remainSeconds + 's' : '');
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
                this.showToast(this.t('toast_load_users_failed'), 'error');
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
                this.showToast(this.t('toast_load_user_detail_failed'), 'error');
                this.userDetailModal.show = false;
            } finally {
                this.userDetailModal.loading = false;
            }
        },
        
        // 关闭用户详情弹窗
        closeUserDetailModal() {
            this.userDetailModal.show = false;
            this.userDetailModal.user = null;
            // 清理详情弹窗的可见性状态
            delete this.visibleFields['detail_phone'];
            delete this.visibleFields['detail_email'];
        },
        
        // 更新用户状态
        // 审批用户（允许待审核用户登录）
        async approveUser(userId) {
            if (!confirm(this.t('confirm_approve_login'))) {
                return;
            }

            try {
                const response = await axios.put(`/api/admin/users/${userId}/status`,
                    { status: 1 },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );

                if (response.data.code === 0) {
                    this.showToast(this.t('toast_login_approved'), 'success');
                    this.loadUsers();
                }
            } catch (error) {
                console.error('Approve user failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_operation_failed');
                this.showToast(detail, 'error');
            }
        },

        async updateUserStatus(userId, currentStatus) {
            const newStatus = currentStatus === 1 ? 0 : 1;
            const actionKey = newStatus === 0 ? 'btn_disable' : 'btn_enable';
            const successKey = newStatus === 0 ? 'toast_disable_success' : 'toast_enable_success';

            if (!confirm(this.t('confirm_user_action', { action: this.t(actionKey) }))) {
                return;
            }

            try {
                const response = await axios.put(`/api/admin/users/${userId}/status`,
                    { status: newStatus },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );

                if (response.data.code === 0) {
                    this.showToast(this.t(successKey), 'success');
                    this.loadUsers();
                }
            } catch (error) {
                console.error('Update user status failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_operation_failed');
                this.showToast(detail, 'error');
            }
        },
        
        // 更新用户角色
        async updateUserRole(userId, currentRole) {
            const newRole = currentRole === 'admin' ? 'user' : 'admin';
            const actionKey = newRole === 'admin' ? 'btn_set_admin' : 'btn_set_user';

            if (!confirm(this.t('confirm_action', { action: this.t(actionKey) }))) {
                return;
            }

            try {
                const response = await axios.put(`/api/admin/users/${userId}/role`,
                    { role: newRole },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );

                if (response.data.code === 0) {
                    this.showToast(this.t('toast_adjust_success'), 'success');
                    if (this.userDetailModal.user && this.userDetailModal.user.user_id === userId) {
                        this.userDetailModal.user.role = newRole;
                    }
                    await this.loadUsers();
                }
            } catch (error) {
                console.error('Update user role failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_operation_failed');
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
                this.showToast(this.t('toast_fill_reason'), 'error');
                return;
            }
            
            if (this.powerModal.amount === 0) {
                this.showToast(this.t('toast_amount_cannot_be_zero'), 'error');
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
                    this.showToast(this.t('toast_power_adjusted') + `: ${data.old_power} → ${data.new_power}`, 'success');
                    this.closePowerModal();
                    this.loadUsers();
                }
            } catch (error) {
                console.error('Adjust power failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_adjust_failed');
                this.showToast(detail, 'error');
            } finally {
                this.powerModal.loading = false;
            }
        },

        // 切换用户智剧通Token启用状态
        async toggleZjtToken(user) {
            const newEnabled = !user.zjt_token_enabled;
            const actionKey = newEnabled ? 'btn_enable' : 'btn_disable';

            if (!confirm(this.t('confirm_zjt_token_action', { action: this.t(actionKey) }))) {
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
                    this.showToast(this.t('toast_zjt_token_action', { action: this.t(actionKey) }), 'success');
                    this.loadUsers();
                }
            } catch (error) {
                console.error('Toggle ZJT token failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_action_failed', { action: this.t(actionKey) });
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
                        this.zjtExpireModal.currentExpireAtDisplay = this.t('status_expire_never');
                        this.zjtExpireModal.newExpireAt = '';
                    }
                }
            } catch (error) {
                console.error('Get ZJT token config failed:', error);
                this.zjtExpireModal.currentExpireAtDisplay = this.t('status_not_set');
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
            if (!confirm(this.t('confirm_adjust_zjt_expire'))) {
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
                    this.showToast(response.data.message || this.t('toast_zjt_expire_adjusted'), 'success');
                    this.closeZjtExpireModal();
                    this.loadUsers();
                }
            } catch (error) {
                console.error('Adjust ZJT expire failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_save_failed');
                this.showToast(detail, 'error');
            } finally {
                this.zjtExpireModal.loading = false;
            }
        },

        // 退出登录
        logout() {
            if (!confirm(this.t('confirm_logout'))) {
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
            const locale = this.locale === 'en' ? 'en-US' : 'zh-CN';
            return date.toLocaleString(locale, {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        },

        formatDateOnly(dateStr) {
            if (!dateStr) return '-';
            const date = new Date(dateStr);
            const locale = this.locale === 'en' ? 'en-US' : 'zh-CN';
            return date.toLocaleDateString(locale, {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit'
            });
        },
        
        // 格式化手机号
        formatPhone(phone) {
            if (!phone || phone.length !== 11) return phone || '-';
            return phone.substring(0, 3) + '****' + phone.substring(7);
        },

        // 格式化邮箱（掩码处理）
        formatEmail(email) {
            if (!email) return '-';
            const atIndex = email.indexOf('@');
            if (atIndex <= 1) return email;
            const prefix = email.substring(0, Math.min(2, atIndex));
            const suffix = email.substring(atIndex);
            return prefix + '***' + suffix;
        },

        // 切换敏感字段的可见性
        toggleFieldVisibility(fieldKey) {
            this.visibleFields[fieldKey] = !this.visibleFields[fieldKey];
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
                this.showToast(this.t('toast_load_config_failed'), 'error');
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
            if (!confirm(this.t('confirm_init_config'))) {
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
                const detail = error?.response?.data?.detail || this.t('error_init_failed');
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
                    this.showToast(this.t('toast_cache_refreshed'), 'success');
                }
            } catch (error) {
                console.error('Reload configs failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_refresh_failed');
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
                this.showToast(this.t('toast_load_checkin_failed'), 'error');
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
                        this.showToast(this.t('toast_partial_save_failed') + `: ${errors.join(', ')}`, 'error');
                    } else {
                        this.showToast(this.t('toast_checkin_saved'), 'success');
                    }
                }
            } catch (error) {
                console.error('Save checkin config failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_save_failed');
                this.showToast(detail, 'error');
            } finally {
                this.checkin.loading = false;
            }
        },

        // ==================== 媒体缓存管理方法 ====================

        async loadMediaCacheConfig() {
            this.mediaCache.loading = true;
            try {
                const response = await axios.get('/api/admin/config', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` },
                    params: { keyword: 'media_cache.', page: 1, page_size: 50 }
                });

                if (response.data.code === 0) {
                    const list = response.data.data.data || [];
                    const map = {};
                    list.forEach(item => { map[item.config_key] = item.config_value; });

                    this.mediaCache.enabled = String(map['media_cache.enabled']).toLowerCase() === 'true';
                    this.mediaCache.maxDays = parseInt(map['media_cache.max_days'] || '30', 10);
                    this.mediaCache.maxSizeGb = parseInt(map['media_cache.max_size_gb'] || '10', 10);
                    this.mediaCache.cleanupOnStartup = String(map['media_cache.cleanup_on_startup']).toLowerCase() === 'true';
                    this.mediaCache.cleanupIntervalHours = parseInt(map['media_cache.cleanup_interval_hours'] || '24', 10);
                }
            } catch (error) {
                console.error('Load media cache config failed:', error);
                this.showToast(this.t('toast_load_media_cache_failed'), 'error');
            } finally {
                this.mediaCache.loading = false;
            }
        },

        async saveMediaCacheConfig() {
            const configs = [];
            configs.push({ key: 'media_cache.enabled', value: this.mediaCache.enabled ? 'true' : 'false' });
            // 故意不写入 media_cache.cache_dir：缓存目录不开放给用户配置
            configs.push({ key: 'media_cache.max_days', value: String(this.mediaCache.maxDays || 0) });
            configs.push({ key: 'media_cache.max_size_gb', value: String(this.mediaCache.maxSizeGb || 0) });
            configs.push({ key: 'media_cache.cleanup_on_startup', value: this.mediaCache.cleanupOnStartup ? 'true' : 'false' });
            configs.push({ key: 'media_cache.cleanup_interval_hours', value: String(this.mediaCache.cleanupIntervalHours || 24) });

            this.mediaCache.loading = true;
            try {
                const response = await axios.put('/api/admin/config/batch',
                    { configs },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );

                if (response.data.code === 0) {
                    const errors = response.data.data.errors || [];
                    if (errors.length > 0) {
                        this.showToast(this.t('toast_partial_save_failed') + `: ${errors.join(', ')}`, 'error');
                    } else {
                        this.showToast(this.t('toast_media_cache_saved'), 'success');
                    }
                }
            } catch (error) {
                console.error('Save media cache config failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_save_failed');
                this.showToast(detail, 'error');
            } finally {
                this.mediaCache.loading = false;
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
                this.showToast(this.t('toast_commercial_only_modify'), 'error');
                return;
            }

            // test_mode 配置仅允许通过脚本修改，禁止在管理后台修改（防止生产环境误开启挡板）
            if (this.isTestModeConfig(item.config_key)) {
                this.showToast(this.t('toast_test_mode_modify_forbidden'), 'error');
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

        /**
         * 判断是否为 test_mode 配置（E2E 挡板配置，仅允许脚本修改）
         */
        isTestModeConfig(configKey) {
            return configKey && configKey.startsWith('test_mode');
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
                    this.showToast(this.t('toast_json_invalid'), 'error');
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
                    this.showToast(this.t('toast_config_updated'), 'success');
                    this.closeConfigEditModal();
                    this.loadConfigs();
                }
            } catch (error) {
                console.error('Update config failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_update_failed');
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
                this.showToast(this.t('toast_load_history_failed'), 'error');
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

        // ==================== RunningHub 密钥池 ====================

        // 加载密钥池聚合视图
        async loadRunninghubKeyPool() {
            this.runninghubKeyPool.loading = true;
            try {
                const response = await axios.get('/api/admin/runninghub-key-pool', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data.code === 0) {
                    this.runninghubKeyPool.list = response.data.data.pool || [];
                    this.runninghubKeyPool.globalApiKeyConfigured = response.data.data.global_api_key_configured;
                }
            } catch (error) {
                console.error('Load runninghub key pool failed:', error);
                this.showToast(error?.response?.data?.detail || this.t('operation_failed'), 'error');
            } finally {
                this.runninghubKeyPool.loading = false;
            }
        },

        // 熔断状态文案映射
        circuitStatusText(status) {
            // 1-正常 0-手动停(此处已单独处理) -1-熔断中 -2-半开探测
            const map = {
                1: this.t('rh_status_enabled'),
                '-1': this.t('rh_status_circuit_open'),
                '-2': this.t('rh_status_half_open')
            };
            return map[String(status)] || this.t('rh_status_enabled');
        },

        // 熔断状态样式映射
        circuitStatusClass(status) {
            const map = {
                1: 'active',
                '-1': 'failed',
                '-2': 'pending'
            };
            return map[String(status)] || 'active';
        },

        // 查看密钥明文
        async viewRunninghubKeyRaw(index) {
            try {
                const response = await axios.get(`/api/admin/runninghub-key-pool/${index}/raw`, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data.code === 0) {
                    alert(response.data.data.api_key);
                }
            } catch (error) {
                this.showToast(error?.response?.data?.detail || this.t('operation_failed'), 'error');
            }
        },

        // 打开密钥编辑弹窗
        openRhKeyEditModal(item) {
            this.rhKeyEditModal.index = item.index;
            this.rhKeyEditModal.apiKey = ''; // 编辑时不回显明文，留空表示不修改
            this.rhKeyEditModal.apiKeyMasked = item.api_key_masked;
            this.rhKeyEditModal.label = item.label || '';
            this.rhKeyEditModal.maxSlots = item.max_slots || 1;
            this.rhKeyEditModal.enabled = item.enabled !== false;
            this.rhKeyEditModal.show = true;
        },

        // 关闭密钥编辑弹窗
        closeRhKeyEditModal() {
            this.rhKeyEditModal.show = false;
            this.rhKeyEditModal.index = null;
        },

        // 提交密钥编辑
        async submitRhKeyEdit() {
            if (!this.rhKeyEditModal.maxSlots || this.rhKeyEditModal.maxSlots < 1) {
                this.showToast(this.t('rh_max_slots_invalid'), 'error');
                return;
            }
            this.rhKeyEditModal.loading = true;
            try {
                // 仅传需要更新的字段；apiKey 留空则不修改
                const payload = {
                    max_slots: this.rhKeyEditModal.maxSlots,
                    label: this.rhKeyEditModal.label,
                    enabled: this.rhKeyEditModal.enabled
                };
                if (this.rhKeyEditModal.apiKey.trim()) {
                    payload.api_key = this.rhKeyEditModal.apiKey.trim();
                }
                const response = await axios.put(
                    `/api/admin/runninghub-key-pool/${this.rhKeyEditModal.index}`,
                    payload,
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                if (response.data.code === 0) {
                    this.showToast(this.t('operation_success'), 'success');
                    this.closeRhKeyEditModal();
                    this.loadRunninghubKeyPool();
                }
            } catch (error) {
                this.showToast(error?.response?.data?.detail || this.t('operation_failed'), 'error');
            } finally {
                this.rhKeyEditModal.loading = false;
            }
        },

        // 删除密钥槽位
        async deleteRunninghubKey(index) {
            if (!confirm(this.t('rh_confirm_delete'))) return;
            try {
                const response = await axios.delete(`/api/admin/runninghub-key-pool/${index}`, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data.code === 0) {
                    this.showToast(this.t('operation_success'), 'success');
                    this.loadRunninghubKeyPool();
                }
            } catch (error) {
                this.showToast(error?.response?.data?.detail || this.t('operation_failed'), 'error');
            }
        },

        // 重置熔断状态
        async resetRunninghubCircuit(index) {
            try {
                const response = await axios.post(
                    `/api/admin/runninghub-key-pool/${index}/reset-circuit`, {},
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                if (response.data.code === 0) {
                    this.showToast(this.t('operation_success'), 'success');
                    this.loadRunninghubKeyPool();
                }
            } catch (error) {
                this.showToast(error?.response?.data?.detail || this.t('operation_failed'), 'error');
            }
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
                this.showToast(this.t('toast_get_config_value_failed'), 'error');
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
                this.showToast(this.t('toast_copied'), 'success');
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
            this.quickConfigModal.quickSelected = false;

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

                                    // 自动选中已有配置的服务商（仅当必填字段有值时才选中）
                                    if (value && !this.quickConfigModal.selectedProviderIds.includes(providerId) && !this.quickConfigModal.quickSelected) {
                                        const provider = PROVIDER_DEFINITIONS.find(p => p.id === providerId);
                                        const field = provider && provider.fields.find(f => f.id === fieldId);
                                        // 只有必填字段（如 api_key）有值才自动选中，忽略 base_url 等可选字段
                                        if (field && field.required) {
                                            this.quickConfigModal.selectedProviderIds.push(providerId);
                                        }
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
                this.showToast(this.t('toast_commercial_only_use'), 'error');
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

        // 快速设置：选择 DeepSeek 大模型 + 多米（生图/生视频共享 Token）
        // 注意：duomi_video 需排在 duomi 前，使右侧合并卡片的 id 与 CONFIG_KEY 反向映射一致
        handleQuickSetup() {
            this.quickConfigModal.quickSelected = true;
            const ids = ['deepseek', 'duomi_video', 'duomi'];
            this.quickConfigModal.selectedProviderIds = [...ids];
            this.quickConfigModal.originalValues = this.quickConfigModal.originalValues || {};
            ids.forEach(id => {
                if (!this.quickConfigModal.providerFormData[id]) {
                    this.quickConfigModal.providerFormData[id] = {};
                }
                if (!this.quickConfigModal.originalValues[id]) {
                    this.quickConfigModal.originalValues[id] = {};
                }
            });
            this.quickConfigModal.activeCategory = 'llm';
            this.showToast(this.t('toast_auto_selected_recommended'), 'success');
        },

        // 移除已选服务商（同 baseName 的合并项一并取消，如 多米 生图/生视频）
        removeProvider(providerId) {
            const provider = PROVIDER_DEFINITIONS.find(p => p.id === providerId);
            const base = provider ? (provider.baseName || provider.id) : providerId;
            this.quickConfigModal.selectedProviderIds = this.quickConfigModal.selectedProviderIds.filter(id => {
                const p = PROVIDER_DEFINITIONS.find(d => d.id === id);
                return !p || (p.baseName || p.id) !== base;
            });
        },

        // 获取服务商 baseName（同 token/api_key 的生图/生视频等归为一组）
        getProviderBaseName(providerId) {
            const provider = PROVIDER_DEFINITIONS.find(p => p.id === providerId);
            return provider ? (provider.baseName || provider.id) : providerId;
        },

        // 同 baseName 下所有 provider id（含未选中的兄弟项，便于读取已加载的配置）
        getProviderIdsByBaseName(baseName) {
            return PROVIDER_DEFINITIONS
                .filter(p => (p.baseName || p.id) === baseName)
                .map(p => p.id);
        },

        // 获取表单字段值（同 baseName 兄弟项共享，如多米 token 只填一份）
        getFormField(providerId, fieldId) {
            const provider = PROVIDER_DEFINITIONS.find(p => p.id === providerId);
            if (provider) {
                const field = provider.fields.find(f => f.id === fieldId);
                if (field && field.readOnly && field.defaultValue) {
                    return field.defaultValue;
                }
            }
            const direct = (this.quickConfigModal.providerFormData[providerId] || {})[fieldId];
            if (direct) return direct;
            const base = this.getProviderBaseName(providerId);
            for (const id of this.getProviderIdsByBaseName(base)) {
                if (id === providerId) continue;
                const v = (this.quickConfigModal.providerFormData[id] || {})[fieldId];
                if (v) return v;
            }
            return '';
        },

        // 更新表单字段值（写入当前 id，并同步到同 baseName 的已选兄弟项，保证计数/保存一致）
        updateFormField(providerId, fieldId, value) {
            if (!this.quickConfigModal.providerFormData[providerId]) {
                this.quickConfigModal.providerFormData[providerId] = {};
            }
            this.quickConfigModal.providerFormData[providerId][fieldId] = value;

            const base = this.getProviderBaseName(providerId);
            this.quickConfigModal.selectedProviderIds.forEach(id => {
                if (id === providerId) return;
                if (this.getProviderBaseName(id) !== base) return;
                if (!this.quickConfigModal.providerFormData[id]) {
                    this.quickConfigModal.providerFormData[id] = {};
                }
                this.quickConfigModal.providerFormData[id][fieldId] = value;
            });
        },

        // 判断服务商是否已配置：同 baseName 任一兄弟有值即算已配置
        isProviderConfigured(providerId) {
            const base = this.getProviderBaseName(providerId);
            return this.getProviderIdsByBaseName(base).some(id => {
                const formData = this.quickConfigModal.providerFormData[id];
                if (!formData) return false;
                return Object.values(formData).some(v => v && String(v).trim());
            });
        },

        // 保存单个服务商的配置
        async saveProviderConfig(providerId) {
            const provider = PROVIDER_DEFINITIONS.find(p => p.id === providerId);
            if (!provider) return;

            const configs = [];
            const formData = this.quickConfigModal.providerFormData[providerId] || {};
            const origData = this.quickConfigModal.originalValues[providerId] || {};

            // ai.comfly.chat 只允许填在聚合站2中
            const baseUrl = (formData['base_url'] || '').trim().toLowerCase();
            if (baseUrl.includes('ai.comfly.chat')) {
                if (provider.baseName !== 'site_2') {
                    this.showToast(this.t('toast_aggregator_site2_only'), 'error');
                    return;
                }
            }

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
                this.showToast(this.t('toast_config_unchanged'), 'success');
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
                    this.showToast(this.t('toast_config_saved') + ` (${updatedCount} 项更新)`, 'success');
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
                const detail = error?.response?.data?.detail || this.t('error_save_failed');
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
                const detail = error?.response?.data?.detail || this.t('error_test_failed');
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
                this.showToast(this.t('toast_config_unchanged'), 'success');
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
                        this.showToast(this.t('toast_partial_update_failed') + `: ${errors.join(', ')}`, 'error');
                    } else if (updatedCount > 0) {
                        this.showToast(this.t('toast_success_updated', { count: updatedCount }), 'success');
                    } else {
                        this.showToast(this.t('toast_config_unchanged'), 'success');
                    }

                    this.closeQuickConfigModal();
                    this.loadConfigs();

                    // 显示使用手册引导弹窗；首管注册后可附带官方微信群（次要区块）
                    const pendingWx = sessionStorage.getItem('pending_wx_group_guide');
                    const showWxGroup = this.wxGroupGuideEnabled
                        && !!this.wxGroupQrDisplayUrl
                        && pendingWx === 'admin_after_config';
                    if (pendingWx === 'admin_after_config') {
                        sessionStorage.removeItem('pending_wx_group_guide');
                    }
                    this.guideModal.showWxGroup = showWxGroup;
                    this.guideModal.show = true;
                }
            } catch (error) {
                console.error('Submit quick config failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_save_failed');
                this.showToast(detail, 'error');
            } finally {
                this.quickConfigModal.loading = false;
            }
        },

        // 显示 jiekou 注册提示（保留兼容）
        showJiekouTip() {
            const confirmed = confirm(this.t('confirm_jiekou_tip'));
            if (confirmed) {
                window.open('https://jiekou.ai/user/register?invited_code=119T5V', '_blank');
            }
        },

        // ==================== 模型管理方法 ====================

        // 格式化上下文窗口大小
        formatContextWindow(tokens) {
            if (tokens >= 1000000) {
                return (tokens / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
            } else if (tokens >= 1000) {
                return (tokens / 1000).toFixed(0) + 'K';
            }
            return tokens.toString();
        },

        // 加载模型列表
        async loadModels() {
            this.models.loading = true;
            try {
                const response = await axios.get('/api/admin/models', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    this.models.list = response.data.data;
                    this.refreshBillingAiLlmOptions();
                    // 刷新后若已展开，同步更新摘要；明细按需重新加载
                    const expandedIds = Object.keys(this.models.expanded).filter(id => this.models.expanded[id]);
                    for (const id of expandedIds) {
                        const model = this.models.list.find(m => String(m.id) === String(id));
                        if (model) {
                            await this.loadModelBilling(model, true);
                        }
                    }
                }
            } catch (error) {
                console.error('加载模型列表失败:', error);
                if (error.response?.status === 401 || error.response?.status === 403) {
                    this.handleAuthError(error.response.status);
                } else {
                    this.showToast(this.t('toast_load_models_failed'), 'error');
                }
            } finally {
                this.models.loading = false;
            }
        },

        // 格式化计费摘要
        formatBillingSummary(summary) {
            if (!summary || !summary.tier_count) {
                return this.t('models_billing_not_configured');
            }
            return this.t('models_billing_summary', {
                tiers: summary.tier_count,
                vendors: summary.vendor_count || 0
            });
        },

        // 展开/收起模型计费配置
        async toggleModelBilling(model) {
            const id = model.id;
            if (this.models.expanded[id]) {
                this.models.expanded[id] = false;
                return;
            }
            this.models.expanded[id] = true;
            await this.loadModelBilling(model);
        },

        // 加载模型计费明细
        async loadModelBilling(model, silent = false) {
            const id = model.id;
            this.models.billingLoading[id] = true;
            try {
                const response = await axios.get(`/api/admin/models/${id}/billing`, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data.code === 0) {
                    this.models.billing[id] = response.data.data;
                    // 同步列表摘要
                    const tiers = (response.data.data.vendors || []).reduce(
                        (sum, v) => sum + (v.tiers ? v.tiers.length : 0), 0
                    );
                    const vendors = (response.data.data.vendors || []).length;
                    model.billing_summary = { tier_count: tiers, vendor_count: vendors };
                }
            } catch (error) {
                console.error('加载模型计费配置失败:', error);
                if (!silent) {
                    if (error.response?.status === 401 || error.response?.status === 403) {
                        this.handleAuthError(error.response.status);
                    } else {
                        this.showToast(this.t('toast_load_billing_failed'), 'error');
                    }
                }
            } finally {
                this.models.billingLoading[id] = false;
            }
        },

        // 加载供应商列表（缓存）
        async ensureVendorsLoaded() {
            if (this.models.vendors && this.models.vendors.length > 0) return;
            try {
                const response = await axios.get('/api/admin/vendors', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data.code === 0) {
                    this.models.vendors = response.data.data || [];
                }
            } catch (error) {
                console.error('加载供应商列表失败:', error);
                this.showToast(this.t('toast_load_vendors_failed'), 'error');
            }
        },

        formatYuan(v) {
            if (v == null || v === '' || isNaN(Number(v))) return '—';
            const n = Number(v);
            if (n >= 1) return n.toFixed(2);
            if (n >= 0.01) return n.toFixed(4);
            return n.toFixed(6);
        },

        // 打开档位弹窗（主填元/百万）
        async openBillingTierModal(model, vendor, tier = null) {
            await this.ensureVendorsLoaded();
            this.billingTierModal.show = true;
            this.billingTierModal.modelId = model.id;
            this.billingTierModal.modelName = model.model_name;
            this.billingTierModal.tierId = tier ? tier.id : null;
            this.billingTierModal.vendor_id = vendor ? vendor.vendor_id : null;
            if (tier) {
                if (!this.billingTierModal.vendor_id && this.models.billing[model.id]) {
                    for (const v of this.models.billing[model.id].vendors || []) {
                        if ((v.tiers || []).some(t => t.id === tier.id)) {
                            this.billingTierModal.vendor_id = v.vendor_id;
                            break;
                        }
                    }
                }
                this.billingTierModal.unlimited = tier.raw_token_threshold == null;
                this.billingTierModal.raw_token_threshold = tier.raw_token_threshold;
                this.billingTierModal.input_yuan_per_m = tier.input_yuan_per_m || tier.money?.input?.cost_yuan_per_m || 1;
                this.billingTierModal.out_yuan_per_m = tier.out_yuan_per_m || tier.money?.output?.cost_yuan_per_m || 2;
                this.billingTierModal.cache_yuan_per_m = tier.cache_yuan_per_m || tier.money?.cache?.cost_yuan_per_m || 0.2;
                this.billingTierModal.commission_percent = Math.round((tier.commission_rate || 0) * 100);
            } else {
                this.billingTierModal.vendor_id = vendor ? vendor.vendor_id : null;
                this.billingTierModal.unlimited = true;
                this.billingTierModal.raw_token_threshold = null;
                this.billingTierModal.input_yuan_per_m = 1;
                this.billingTierModal.out_yuan_per_m = 2;
                this.billingTierModal.cache_yuan_per_m = 0.2;
                this.billingTierModal.commission_percent = 0;
            }
            this.billingTierModal.loading = false;
        },

        closeBillingTierModal() {
            this.billingTierModal.show = false;
            this.billingTierModal.loading = false;
            this.billingTierModal.tierId = null;
            this.billingTierModal.modelId = null;
        },

        async submitBillingTier() {
            const modal = this.billingTierModal;
            if (!modal.vendor_id) {
                this.showToast(this.t('toast_select_vendor'), 'error');
                return;
            }
            if (!modal.unlimited && (!modal.raw_token_threshold || modal.raw_token_threshold <= 0)) {
                this.showToast(this.t('toast_invalid_raw_threshold'), 'error');
                return;
            }
            for (const [key, labelKey] of [
                ['input_yuan_per_m', 'models_billing_col_input_price'],
                ['out_yuan_per_m', 'models_billing_col_output_price'],
                ['cache_yuan_per_m', 'models_billing_col_cache_price']
            ]) {
                if (!modal[key] || modal[key] <= 0) {
                    this.showToast(this.t('toast_invalid_price_field', { field: this.t(labelKey) }), 'error');
                    return;
                }
            }
            const commission_rate = Math.min(1, Math.max(0, (modal.commission_percent || 0) / 100));

            modal.loading = true;
            const modelId = modal.modelId;
            const tierId = modal.tierId;
            try {
                const raw = modal.unlimited ? null : modal.raw_token_threshold;
                const basePayload = {
                    input_yuan_per_m: modal.input_yuan_per_m,
                    out_yuan_per_m: modal.out_yuan_per_m,
                    cache_yuan_per_m: modal.cache_yuan_per_m,
                    commission_rate,
                };
                if (tierId) {
                    const payload = {
                        ...basePayload,
                        clear_raw_token_threshold: !!modal.unlimited,
                    };
                    if (!modal.unlimited) payload.raw_token_threshold = raw;
                    const response = await axios.put(`/api/admin/vendor-models/${tierId}`, payload, {
                        headers: { 'Authorization': `Bearer ${this.authToken}` }
                    });
                    if (response.data.code === 0) {
                        this.showToast(this.t('toast_billing_tier_saved'), 'success');
                        this.closeBillingTierModal();
                        this.models.expanded[modelId] = true;
                        await this.loadModels();
                    }
                } else {
                    const payload = {
                        vendor_id: modal.vendor_id,
                        model_id: modelId,
                        raw_token_threshold: raw,
                        ...basePayload,
                    };
                    const response = await axios.post('/api/admin/vendor-models', payload, {
                        headers: { 'Authorization': `Bearer ${this.authToken}` }
                    });
                    if (response.data.code === 0) {
                        this.showToast(this.t('toast_billing_tier_created'), 'success');
                        this.closeBillingTierModal();
                        this.models.expanded[modelId] = true;
                        await this.loadModels();
                    }
                }
            } catch (error) {
                console.error('保存计费档位失败:', error);
                const detail = error?.response?.data?.detail || this.t('error_update_failed');
                this.showToast(detail, 'error');
            } finally {
                this.billingTierModal.loading = false;
            }
        },

        async updateBillingTierYuan(model, tier, field, value) {
            const num = parseFloat(value);
            if (isNaN(num) || num <= 0) {
                this.showToast(this.t('toast_invalid_price'), 'error');
                await this.loadModelBilling(model);
                return;
            }
            if (this.models.updating === `tier-${tier.id}`) return;
            this.models.updating = `tier-${tier.id}`;
            try {
                const response = await axios.put(`/api/admin/vendor-models/${tier.id}`, { [field]: num }, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data.code === 0) {
                    const d = response.data.data || {};
                    Object.assign(tier, {
                        input_token_threshold: d.input_token_threshold ?? tier.input_token_threshold,
                        out_token_threshold: d.out_token_threshold ?? tier.out_token_threshold,
                        cache_read_threshold: d.cache_read_threshold ?? tier.cache_read_threshold,
                        input_yuan_per_m: d.input_yuan_per_m ?? tier.input_yuan_per_m,
                        out_yuan_per_m: d.out_yuan_per_m ?? tier.out_yuan_per_m,
                        cache_yuan_per_m: d.cache_yuan_per_m ?? tier.cache_yuan_per_m,
                        money: d.money || tier.money,
                        commission_rate: d.commission_rate ?? tier.commission_rate,
                    });
                    this.showToast(this.t('toast_billing_tier_saved'), 'success');
                } else {
                    await this.loadModelBilling(model);
                }
            } catch (error) {
                console.error('更新单价失败:', error);
                this.showToast(error?.response?.data?.detail || this.t('error_update_failed'), 'error');
                await this.loadModelBilling(model);
            } finally {
                this.models.updating = null;
            }
        },

        async updateBillingTierCommission(model, tier, percentVal) {
            const p = parseFloat(percentVal);
            if (isNaN(p) || p < 0 || p > 100) {
                this.showToast(this.t('toast_invalid_commission'), 'error');
                await this.loadModelBilling(model);
                return;
            }
            if (this.models.updating === `tier-${tier.id}`) return;
            this.models.updating = `tier-${tier.id}`;
            try {
                const rate = p / 100;
                const response = await axios.put(`/api/admin/vendor-models/${tier.id}`, {
                    commission_rate: rate
                }, { headers: { 'Authorization': `Bearer ${this.authToken}` } });
                if (response.data.code === 0) {
                    const d = response.data.data || {};
                    tier.commission_rate = d.commission_rate ?? rate;
                    tier.money = d.money || tier.money;
                    this.showToast(this.t('toast_billing_tier_saved'), 'success');
                } else {
                    await this.loadModelBilling(model);
                }
            } catch (error) {
                this.showToast(error?.response?.data?.detail || this.t('error_update_failed'), 'error');
                await this.loadModelBilling(model);
            } finally {
                this.models.updating = null;
            }
        },

        async deleteBillingTier(model, tier) {
            const range = tier.range_label || (tier.raw_token_threshold == null
                ? this.t('models_billing_unlimited')
                : String(tier.raw_token_threshold));
            if (!confirm(this.t('confirm_delete_billing_tier', { range }))) {
                return;
            }
            this.models.updating = `tier-${tier.id}`;
            try {
                const response = await axios.delete(`/api/admin/vendor-models/${tier.id}`, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data.code === 0) {
                    this.showToast(this.t('toast_billing_tier_deleted'), 'success');
                    await this.loadModelBilling(model);
                    await this.loadModels();
                }
            } catch (error) {
                console.error('删除计费档位失败:', error);
                const detail = error?.response?.data?.detail || this.t('error_update_failed');
                this.showToast(detail, 'error');
            } finally {
                this.models.updating = null;
            }
        },

        /**
         * 还原代码默认计费档位。
         * @param {object} model
         * @param {object|null} vendor 传入则只还原该供应商
         */
        async resetBillingDefaults(model, vendor = null) {
            if (!model || !model.id) return;
            const billing = this.models.billing[model.id];
            const hasDefaults = billing && (
                billing.has_defaults
                || (billing.default_vendor_names && billing.default_vendor_names.length)
                || (vendor && (vendor.has_defaults
                    || (billing.default_vendor_names || []).includes(vendor.vendor_name)))
            );
            if (!hasDefaults && !vendor) {
                this.showToast(this.t('models_billing_reset_no_defaults'), 'error');
                return;
            }
            if (vendor) {
                if (!confirm(this.t('models_billing_reset_vendor_confirm', {
                    model: model.model_name,
                    vendor: vendor.vendor_name,
                }))) {
                    return;
                }
            } else if (!confirm(this.t('models_billing_reset_confirm', {
                model: model.model_name,
            }))) {
                return;
            }

            const updatingKey = vendor
                ? `reset-${model.id}-${vendor.vendor_id}`
                : `reset-${model.id}`;
            this.models.updating = updatingKey;
            try {
                const params = {};
                if (vendor && vendor.vendor_id != null) {
                    params.vendor_id = vendor.vendor_id;
                }
                const response = await axios.post(
                    `/api/admin/models/${model.id}/billing/reset-defaults`,
                    null,
                    {
                        headers: { 'Authorization': `Bearer ${this.authToken}` },
                        params,
                    }
                );
                if (response.data.code === 0) {
                    if (response.data.data && response.data.data.billing) {
                        this.models.billing[model.id] = response.data.data.billing;
                    } else {
                        await this.loadModelBilling(model);
                    }
                    await this.loadModels();
                    this.showToast(response.data.message || this.t('toast_billing_reset_ok'), 'success');
                } else {
                    this.showToast(response.data.message || this.t('toast_billing_reset_failed'), 'error');
                }
            } catch (error) {
                console.error('还原默认档位失败:', error);
                this.showToast(
                    error?.response?.data?.detail || this.t('toast_billing_reset_failed'),
                    'error'
                );
            } finally {
                this.models.updating = null;
            }
        },

        // 构建 AI 负责模型下拉：供应商 + 模型（默认 deepseek / deepseek-v4-pro）
        refreshBillingAiLlmOptions() {
            const opts = [];
            let defaultKey = '';
            for (const m of this.models.list || []) {
                if (!m.enabled) continue;
                const vendors = (m.vendors && m.vendors.length)
                    ? m.vendors
                    : [{ vendor_id: null, vendor_name: 'unknown' }];
                for (const v of vendors) {
                    if (v.vendor_id == null) continue;
                    const key = `${v.vendor_id}:${m.id}`;
                    const label = `${v.vendor_name} / ${m.model_name}`;
                    opts.push({
                        key,
                        label,
                        model_id: m.id,
                        model_name: m.model_name,
                        vendor_id: v.vendor_id,
                        vendor_name: v.vendor_name,
                    });
                    // 默认：deepseek 供应商 + deepseek-v4-pro
                    if (
                        m.model_name === 'deepseek-v4-pro'
                        && String(v.vendor_name || '').toLowerCase() === 'deepseek'
                    ) {
                        defaultKey = key;
                    }
                }
            }
            // 若无 deepseek 官方，回退任意 deepseek-v4-pro
            if (!defaultKey) {
                const pro = opts.find(o => o.model_name === 'deepseek-v4-pro');
                if (pro) defaultKey = pro.key;
            }
            this.billingAi.llmOptions = opts;
            // 若当前选中已失效（模型禁用/无供应商），重置
            const stillValid = opts.some(o => o.key === this.billingAi.llmKey);
            if (!this.billingAi.llmKey || !stillValid) {
                this.billingAi.llmKey = defaultKey || (opts[0] && opts[0].key) || '';
            }
        },

        async runBillingAiPropose(model) {
            const instruction = (this.billingAi.instruction || '').trim();
            if (!instruction) {
                this.showToast(this.t('toast_billing_ai_need_instruction'), 'error');
                return;
            }
            this.refreshBillingAiLlmOptions();
            this.billingAi.loading = true;
            this.billingAi.targetModelId = model.id;
            try {
                const selected = (this.billingAi.llmOptions || []).find(o => o.key === this.billingAi.llmKey);
                if (!selected || !selected.model_id || !selected.vendor_id) {
                    this.showToast(this.t('toast_billing_ai_need_llm'), 'error');
                    return;
                }
                const payload = {
                    instruction,
                    // 被改价目标模型的供应商筛选（与 AI 引擎供应商无关）
                    vendor_id: this.billingAi.filterVendorId || null,
                    llm_model_id: selected.model_id,
                    llm_vendor_id: selected.vendor_id,
                };
                const response = await axios.post(
                    `/api/admin/models/${model.id}/billing/ai-propose`,
                    payload,
                    { headers: { 'Authorization': `Bearer ${this.authToken}` }, timeout: 90000 }
                );
                if (response.data.code === 0) {
                    this.billingAi.proposal = response.data.data;
                    this.billingAi.confirmShow = true;
                } else {
                    this.showToast(response.data.message || this.t('error_update_failed'), 'error');
                }
            } catch (error) {
                console.error('AI propose failed:', error);
                this.showToast(error?.response?.data?.detail || this.t('toast_billing_ai_failed'), 'error');
            } finally {
                this.billingAi.loading = false;
            }
        },

        async applyBillingAiProposal() {
            const proposal = this.billingAi.proposal;
            if (!proposal || !proposal.ops || !proposal.ops.length) return;
            const hasDelete = proposal.ops.some(o => o.op === 'delete');
            if (hasDelete && !confirm(this.t('confirm_billing_ai_apply_delete'))) {
                return;
            }
            this.billingAi.applying = true;
            try {
                const response = await axios.post(
                    `/api/admin/models/${proposal.model_id}/billing/ai-apply`,
                    { ops: proposal.ops },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );
                if (response.data.code === 0) {
                    this.showToast(response.data.message || this.t('toast_billing_ai_applied'), 'success');
                    this.billingAi.confirmShow = false;
                    this.billingAi.proposal = null;
                    this.billingAi.instruction = '';
                    this.models.expanded[proposal.model_id] = true;
                    await this.loadModels();
                }
            } catch (error) {
                console.error('AI apply failed:', error);
                this.showToast(error?.response?.data?.detail || this.t('error_update_failed'), 'error');
            } finally {
                this.billingAi.applying = false;
            }
        },

        // 加载常量参考
        async loadConstants() {
            if (this.constants.groups.length > 0) return; // 已加载过，不重复请求
            this.constants.loading = true;
            try {
                const response = await axios.get('/api/admin/constants', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data.code === 0) {
                    this.constants.groups = response.data.data.groups || [];
                    this.constants.mappings = response.data.data.mappings || [];
                }
            } catch (error) {
                console.error('加载常量定义失败:', error);
                if (error.response?.status === 401 || error.response?.status === 403) {
                    this.handleAuthError(error.response.status);
                } else {
                    this.showToast(this.t('constants_load_failed'), 'error');
                }
            } finally {
                this.constants.loading = false;
            }
        },

        // 切换模型启用/禁用状态
        async toggleModelEnabled(model) {
            const newEnabled = model.enabled ? 0 : 1;
            try {
                const response = await axios.put(`/api/admin/models/${model.id}/enabled`,
                    { enabled: newEnabled },
                    { headers: { 'Authorization': `Bearer ${this.authToken}` } }
                );

                if (response.data.code === 0) {
                    model.enabled = newEnabled;
                    this.showToast(
                        newEnabled ? this.t('toast_model_enabled') : this.t('toast_model_disabled'),
                        'success'
                    );
                }
            } catch (error) {
                console.error('切换模型状态失败:', error);
                if (error.response?.status === 401 || error.response?.status === 403) {
                    this.handleAuthError(error.response.status);
                } else {
                    this.showToast(this.t('toast_model_toggle_failed'), 'error');
                }
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
                    // 读取重试总开关状态
                    this.implementations.retryGlobalEnabled = response.data.retry_global_enabled !== false;
                    console.log('更新后的 groups:', this.implementations.groups);

                    // 强制触发 Vue 响应式更新
                    this.$forceUpdate();
                }
            } catch (error) {
                console.error('Load implementations failed:', error);
                this.showToast(this.t('toast_load_impl_failed'), 'error');
            } finally {
                this.implementations.loading = false;
            }
        },

        // 切换供应商自动切换总开关
        async toggleRetryGlobal() {
            // 社区版限制
            if (this.isCommunityEdition) {
                this.showToast(this.t('toast_community_feature_locked'), 'warning');
                this.implementations.retryGlobalEnabled = false;
                return;
            }

            try {
                const response = await axios.put('/api/admin/retry-global-enabled', {
                    enabled: this.implementations.retryGlobalEnabled
                }, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    this.showToast(response.data.message, 'success');
                } else {
                    this.showToast(response.data.detail || this.t('toast_save_failed'), 'error');
                    this.implementations.retryGlobalEnabled = !this.implementations.retryGlobalEnabled;
                }
            } catch (error) {
                console.error('Toggle retry global failed:', error);
                if (error.response && error.response.status === 403) {
                    this.showToast(error.response.data.detail || this.t('toast_community_feature_locked'), 'warning');
                    this.implementations.retryGlobalEnabled = false;
                } else {
                    this.showToast(this.t('toast_save_failed'), 'error');
                    this.implementations.retryGlobalEnabled = !this.implementations.retryGlobalEnabled;
                }
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
                this.showToast(this.t('toast_invalid_sort_value'), 'error');
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
                    this.showToast(this.t('toast_sort_updated'), 'success');
                } else {
                    this.showToast(response.data.message || this.t('error_update_failed'), 'error');
                    this.loadImplementations();
                }
            } catch (error) {
                console.error('Update sort order failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_update_failed');
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
                'gemini_3_1_flash_image_edit': 'Gemini 3.1 Flash 图片编辑',
                'veo3_image_to_video': 'VEO3 图生视频',
                'ltx2_image_to_video': 'LTX2 图生视频',
                'ltx2_3_image_to_video': 'LTX2.3 图生视频',
                'wan22_image_to_video': 'Wan22 图生视频',
                'digital_human': '数字人',
                'digital_human_ltx2_3_voice': '数字人 LTX2.3 With Voice',
                'vidu_image_to_video': 'Vidu 图生视频',
                'vidu_q2_image_to_video': 'Vidu Q2 图生视频',
                'seedream_text_to_image': 'Seedream 文生图',
                'gpt_image_2': 'GPT Image 2',
                'seedance_1_5_pro_image_to_video': 'Seedance 1.5 Pro 图生视频',
                'seedance_2_0_fast_image_to_video': 'Seedance 2.0 Fast 图生视频',
                'seedance_2_0_image_to_video': 'Seedance 2.0 图生视频',
                'seedance_2_0_mini_image_to_video': 'Seedance 2.0 Mini 图生视频',
                'grok_image_to_video': 'Grok 图生视频',
                'happy_horse_image_to_video': 'Happy Horse 图生视频',
                'happy_horse_reference_to_video': 'Happy Horse 参考生视频',
                'qwen_multi_angle_image_edit': 'Qwen 多角度图片编辑'
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
                    this.showToast(this.t('toast_config_updated'), 'success');
                    this.closeImplEditModal();
                    this.loadImplementations();
                }
            } catch (error) {
                console.error('Update implementation failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_update_failed');
                this.showToast(detail, 'error');
            } finally {
                this.implEditModal.loading = false;
            }
        },

        // 快速切换实现方启用状态
        async toggleImplementation(impl, group) {
            const actionKey = impl.enabled ? 'btn_disable' : 'btn_enable';
            const newEnabled = !impl.enabled;

            try {
                const response = await axios.put('/api/admin/implementation-config', {
                    implementation_name: impl.name,
                    driver_key: group.driver_key,
                    enabled: newEnabled
                }, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });

                if (response.data.code === 0) {
                    impl.enabled = newEnabled;
                    this.showToast(this.t('toast_impl_toggled', { action: this.t(actionKey) }), 'success');
                } else {
                    this.showToast(response.data.message || this.t('toast_impl_action_failed'), 'error');
                }
            } catch (error) {
                console.error('Toggle implementation failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_operation_failed');
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
                this.showToast(this.t('toast_power_cannot_be_negative'), 'error');
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
                    this.showToast(this.t('toast_power_saved'), 'success');
                    this.closeImplPowerModal();
                    this.loadImplementations();
                }
            } catch (error) {
                console.error('Update power failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_update_failed');
                this.showToast(detail, 'error');
            } finally {
                this.implPowerModal.loading = false;
            }
        },

        // 内联更新时长算力配置
        async updateDurationPower(implementation, duration, value, group) {
            const computingPower = parseInt(value);
            if (isNaN(computingPower) || computingPower < 0) {
                this.showToast(this.t('toast_invalid_power_value'), 'error');
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
                    this.showToast(this.t('toast_duration_power_updated', { duration: duration, power: computingPower }), 'success');
                } else {
                    // 更新失败，恢复原值
                    this.showToast(response.data.message || this.t('error_update_failed'), 'error');
                    this.loadImplementations();
                }
            } catch (error) {
                console.error('Update duration power failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_update_failed');
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
                this.showToast(this.t('toast_invalid_power_value'), 'error');
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
                    this.showToast(this.t('toast_default_power_updated', { power: computingPower }), 'success');
                } else {
                    // 更新失败，恢复原值
                    this.showToast(response.data.message || this.t('error_update_failed'), 'error');
                    this.loadImplementations();
                }
            } catch (error) {
                console.error('Update default power failed:', error);
                const detail = error?.response?.data?.detail || this.t('error_update_failed');
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
                if (!confirm(this.t('confirm_restore_power', { name: implementation.display_name, power: defaultPower }))) {
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
                    this.showToast(this.t('toast_restored_default_power', { power: defaultPower }), 'success');

                } catch (error) {
                    console.error('Reset default power failed:', error);
                    const detail = error?.response?.data?.detail || this.t('error_restore_failed');
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
                if (!confirm(this.t('confirm_restore_duration_power', { name: implementation.display_name, duration: duration, power: defaultPower }))) {
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
                    this.showToast(this.t('toast_duration_power_restored', { duration: duration, power: defaultPower }), 'success');

                } catch (error) {
                    console.error('Reset duration power failed:', error);
                    const detail = error?.response?.data?.detail || this.t('error_restore_failed');
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
        },

        // ============ 通知中心 ============

        async pollNotifications() {
            try {
                const response = await axios.get('/api/notifications/poll');
                if (response.data.code === 0) {
                    const data = response.data.data;
                    this.versionUpdate = data.version_update || null;
                    this.notifications = data.notifications || [];
                    this.missingBinaries = data.missing_binaries || [];
                    this.unreadCount = data.unread_count || 0;
                }
            } catch (error) {
                console.error('Poll notifications failed:', error);
            }
        },

        async markNotificationRead(id) {
            try {
                const n = this.notifications.find(n => n.id === id);
                if (!n || n.is_read) return;
                const response = await axios.post(`/api/notifications/${id}/read`);
                if (response.data.code === 0) {
                    n.is_read = true;
                    this.unreadCount = Math.max(0, this.unreadCount - 1);
                }
            } catch (error) {
                console.error('Mark read failed:', error);
            }
        },

        async markAllNotificationsRead() {
            try {
                const response = await axios.post('/api/notifications/read-all');
                if (response.data.code === 0) {
                    this.notifications.forEach(n => n.is_read = true);
                    this.unreadCount = 0;
                }
            } catch (error) {
                console.error('Mark all read failed:', error);
            }
        },

        // ==================== 佣金管理 ====================

        // 加载提现单列表
        async loadCommissionWithdrawals() {
            this.commission.loading = true;
            try {
                let url = `/api/admin/commission/withdrawals?page=${this.commission.page}&page_size=${this.commission.pageSize}`;
                if (this.commission.statusFilter !== null) {
                    url += `&status=${this.commission.statusFilter}`;
                }
                const response = await axios.get(url, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data.code === 0) {
                    const data = response.data.data;
                    this.commission.list = data.withdrawals || [];
                    this.commission.total = data.total || 0;
                }
            } catch (error) {
                console.error('Load commission withdrawals failed:', error);
                this.showToast(this.t('toast_commission_load_failed'), 'error');
            } finally {
                this.commission.loading = false;
            }
        },

        // 切换状态筛选
        setCommissionStatusFilter(status) {
            this.commission.statusFilter = status;
            this.commission.page = 1;
            this.loadCommissionWithdrawals();
        },

        // 分页
        goToCommissionPage(page) {
            if (page < 1 || page > this.commissionTotalPages) return;
            this.commission.page = page;
            this.loadCommissionWithdrawals();
        },

        // 打开审核弹窗
        openCommissionReviewModal(item, action) {
            this.commissionReviewModal.show = true;
            this.commissionReviewModal.action = action;
            this.commissionReviewModal.withdrawNo = item.withdraw_no;
            this.commissionReviewModal.amount = item.amount;
            this.commissionReviewModal.method = item.method;
            this.commissionReviewModal.account = this.getCommissionAccount(item);
            this.commissionReviewModal.rejectReason = '';
            this.commissionReviewModal.loading = false;
        },

        // 提交审核
        async submitCommissionReview() {
            this.commissionReviewModal.loading = true;
            try {
                const action = this.commissionReviewModal.action;
                let url = `/api/admin/commission/withdraw/${this.commissionReviewModal.withdrawNo}/${action}`;
                let config = { headers: { 'Authorization': `Bearer ${this.authToken}` } };

                let response;
                if (action === 'approve') {
                    response = await axios.post(url, {}, config);
                } else {
                    // reject: 通过 query 参数传递驳回原因
                    const reason = this.commissionReviewModal.rejectReason || '';
                    response = await axios.post(url + (reason ? `?reject_reason=${encodeURIComponent(reason)}` : ''), {}, config);
                }

                if (response.data.code === 0) {
                    this.showToast(
                        action === 'approve' ? this.t('toast_commission_approve_success') : this.t('toast_commission_reject_success'),
                        'success'
                    );
                    this.commissionReviewModal.show = false;
                    this.loadCommissionWithdrawals();
                } else {
                    this.showToast(response.data.detail || this.t('toast_commission_action_failed'), 'error');
                }
            } catch (error) {
                console.error('Commission review failed:', error);
                this.showToast(error.response?.data?.detail || this.t('toast_commission_action_failed'), 'error');
            } finally {
                this.commissionReviewModal.loading = false;
            }
        },

        // 获取提现方式文本
        getCommissionMethodText(method) {
            if (method === 'alipay') return this.t('commission_method_alipay');
            if (method === 'bank') return this.t('commission_method_bank');
            return method || '-';
        },

        // 获取状态文本
        getCommissionStatusText(status) {
            if (status === 0) return this.t('commission_status_pending');
            if (status === 1) return this.t('commission_status_paid');
            if (status === 2) return this.t('commission_status_rejected');
            return '-';
        },

        // 获取收款账号展示
        getCommissionAccount(item) {
            if (item.method === 'alipay') {
                return item.alipay_account || this.t('commission_no_account');
            }
            if (item.method === 'bank') {
                const parts = [];
                if (item.bank_card_no) parts.push(item.bank_card_no);
                if (item.bank_account_name) parts.push(item.bank_account_name);
                if (item.bank_name) parts.push(item.bank_name);
                return parts.length > 0 ? parts.join(' / ') : this.t('commission_no_account');
            }
            return this.t('commission_no_account');
        },

        // ==================== 佣金比例上限 ====================

        // 加载佣金比例上限
        async loadCommissionMaxRate() {
            try {
                const response = await axios.get('/api/admin/commission/max-rate', {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data.code === 0) {
                    this.commissionMaxRate = response.data.data.max_rate;
                }
            } catch (error) {
                console.error('Load commission max rate failed:', error);
                this.showToast(this.t('toast_max_rate_load_failed'), 'error');
            }
        },

        // 打开修改上限弹窗
        openCommissionMaxRateModal() {
            this.commissionMaxRateModal.show = true;
            this.commissionMaxRateModal.newRate = Math.round(this.commissionMaxRate * 100);
            this.commissionMaxRateModal.affectedCount = null;
            this.commissionMaxRateModal.loading = false;
        },

        // 提交修改上限
        async submitCommissionMaxRate() {
            const newRate = this.commissionMaxRateModal.newRate;
            if (!newRate || newRate < 1 || newRate > 100) {
                this.showToast('请输入 1-100 之间的整数', 'error');
                return;
            }

            this.commissionMaxRateModal.loading = true;
            try {
                const response = await axios.put(`/api/admin/commission/max-rate?rate=${(newRate / 100).toFixed(2)}`, {}, {
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                });
                if (response.data.code === 0) {
                    this.commissionMaxRate = response.data.data.max_rate;
                    this.commissionMaxRateModal.affectedCount = response.data.data.affected_count;
                    this.showToast(this.t('toast_max_rate_updated'), 'success');
                } else {
                    this.showToast(response.data.detail || '设置失败', 'error');
                }
            } catch (error) {
                console.error('Set commission max rate failed:', error);
                this.showToast(error.response?.data?.detail || '设置失败', 'error');
            } finally {
                this.commissionMaxRateModal.loading = false;
            }
        }
    }
};

// 初始化Vue应用
Vue.createApp(AdminApp).mount('#app');
