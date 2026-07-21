import {
    assetFromApi,
    buildStoryboardTitle,
    sceneFromApi,
    scenesFromApi,
    dialogueFromApi,
} from './adapters.js';

const state = {
    storyboardId: null,
    worldId: null,
    episodeNumber: 1,
    /** 当前世界下可切换的集列表（/api/storyboard/folders） */
    episodeFolders: [],
    episodeFoldersLoaded: false,
    episodeFoldersLoading: false,
    showEpisodePicker: false,
    scriptId: null,
    workflowId: null,
    userId: null,
    authToken: null,
    editionInfo: { mode: 'community', mode_label: '社区版' },

    title: '故事板',
    style: '',
    workflowRatio: '16:9',
    compositionPreference: '',
    computingPower: null,

    /**
     * 比例门禁：世界内首个故事板创建前为 true。
     * 为 true 时禁止拆分/生图/生视频/导出等一切业务操作。
     */
    ratioGateActive: false,
    showRatioConfirmDialog: false,
    pendingCreateRatio: '16:9',
    ratioConfirmError: '',
    isCreatingStoryboard: false,
    /** @type {{ needs_ratio_confirm?: boolean, workflow_ratio?: string|null, source_episode_number?: number|null, storyboard_count?: number }|null} */
    createDefaults: null,

    scenes: [],
    currentSceneId: null,
    activeTab: 'scene',          // 'scene' | 'dialogue'（音乐 Tab 已移除）
    viewMode: 'timeline',
    chatMode: 'dialogue',
    inputMessage: '',
    // 视频生成模式图片输入模式：first_last_frame | multi_reference（对齐 marketing_agent）
    videoImageMode: 'first_last_frame',
    // 视频槽位媒体：[{id, role:'first_frame'|'last_frame'|'reference', source:'scene'|'upload', url, thumbnailUrl, name, uploading}]
    videoMediaItems: [],
    // 用户手动移除首帧后，在当前分镜内不再自动注入（切换分镜清除）
    videoFirstFrameDismissedSceneId: null,
    showVideoModePanel: false,
    // 视频生成偏好（齿轮配置，故事板级 config_json）
    videoDurationMode: 'auto', // 'auto' | number
    videoResolution: null,
    clipToAudioDuration: true,
    // 兼容旧字段：同步自 videoMediaItems 中 role=reference 的上传项
    referenceImages: [],
    agentMessages: [],
    /** 按分镜隔离 Agent 运行态，避免一个分镜的任务锁住其他分镜。 */
    agentRunsBySceneId: {},
    /** 按分镜缓存对话消息，后台流不得写入当前其他分镜的消息列表。 */
    agentMessagesBySceneId: {},
    /** 分镜助手历史消息区是否展开 */
    agentChatHistoryOpen: true,
    /** 媒体栈多图展开（触控/点击兜底；桌面主要靠 hover） */
    mediaStackExpanded: false,
    /** 长消息展开 id 集合：Set 或普通对象 map */
    expandedAgentMessageIds: {},
    /**
     * 聊天历史浮层是否固定展开（点击「展开」完整内容时置 true，
     * 避免 rerender 丢失 :hover 导致浮层消失）
     */
    agentChatLogPinned: false,
    /**
     * 分镜助手正文字号档位：-2…+8，基准 12px，每档 ±1px（约 10–20px，照顾大龄用户）
     * 持久化 key: storyboard_agentChatFontStep
     */
    agentChatFontStep: 0,
    aiOptimize: true,
    subtitleEnabled: true,
    isPlaying: false,
    currentTime: 0,
    // 时间轴预览播放细粒度状态（由 playback.js 维护）
    playback: {
        sceneId: null,
        sceneLocalTime: 0,
        audioDialogueId: null,
        status: 'idle', // idle | playing | paused | ended
        generation: 0,
        buffering: false, // 本镜媒体预加载中，时钟未走
    },

    // 算力日志 / 充值弹窗
    showPowerLogsModal: false,
    showRechargeModal: false,
    rechargeState: 'loading', // loading | packages | qrcode | error
    rechargePackages: [],
    selectedRechargePackage: null,
    rechargeQrCodeUrl: '',
    rechargeError: '',
    showMentionPopup: false,
    showGlobalStyleDialog: false,
    // 分镜编辑弹框（grid 视图卡片「编辑」按钮触发；编辑 title/duration/difficulty/act_name）
    showSceneEditDialog: false,
    sceneEditTargetId: null,
    sceneEditSaving: false,
    sceneEditError: '',
    videoTypeSwitch: {
        saving: false,
        targetType: null,
        previousType: null,
    },
    mentionTab: 'character',
    isSaving: false,
    error: '',
    showGenerateFromScriptDialog: false,
    isGeneratingFromScript: false,
    generateFromScriptError: '',
    autoImageSequenceMode: 'balanced',
    autoImageBatch: {
        batchId: null,
        status: 'idle',
        totalCount: 0,
        completedCount: 0,
        runningCount: 0,
        pendingCount: 0,
        failedCount: 0,
        skippedCount: 0,
        itemsBySceneId: {},
        message: '',
        submitting: false,
    },
    autoImageLocationGate: {
        status: 'idle',
        errorCode: '',
        message: '',
        blockers: [],
        affectedSceneIds: [],
        retryAfterMs: 0,
    },
    /** 批量生成缺失视频（时间轴「批量生成视频」） */
    autoVideoBatch: {
        batchId: null,
        status: 'idle',
        totalCount: 0,
        completedCount: 0,
        runningCount: 0,
        pendingCount: 0,
        failedCount: 0,
        skippedCount: 0,
        itemsBySceneId: {},
        message: '',
        submitting: false,
    },
    // 剧本拆分参数（与 video_workflow 剧本节点保持一致：true/true/false/15）
    maxGroupDuration: 15,
    forceMediumShot: true,
    noBgMusic: true,
    splitMultiDialogue: false,
    /** 剧本拆分语言；空字符串表示中文（默认）。 */
    scriptDialogueLanguage: '',
    scriptPromptLanguage: '',
    /** 自定义输入和折叠面板仅用于弹窗交互，实际值由上面两个字段持久化。 */
    scriptDialogueLanguageCustom: false,
    scriptPromptLanguageCustom: false,
    scriptLanguageOptionsOpen: false,
    /** 是否开启拆分质检（开启后多轮拆分+质检，耗时与算力显著增加） */
    enableScriptSplitQc: false,
    /** 质检最大循环次数 1–5，超次强制用最后一轮结果 */
    scriptSplitQcMaxRounds: 2,

    // 生成分镜进度弹框
    showGenerateProgressDialog: false,
    generateProgressSteps: [],
    generateProgressStepIndex: -1,
    generateProgressError: '',
    /** 后端 script_split_task.progress 提供的真实总体进度（0～100） */
    generateProgressPercent: 0,
    /** 后端当前阶段文案，例如“正在拆分第 2/4 段” */
    generateProgressMessage: '正在准备任务',
    // 剧本分段拆分任务 ID（异步化后用于轮询恢复，见设计文档 §15）
    generateFromScriptTaskId: null,

    // 模型配置弹框
    showModelConfigModal: false,
    currentConfigTab: 'dialogue', // dialogue | image | video

    characters: [],
    locations: [],
    props: [],

    // 模型列表与选择（task_id 作为生成时的 task_type）
    // 旧字段保留向前兼容
    imageModels: [],
    videoModels: [],
    digitalHumanModels: [],
    selectedImageTaskId: null,
    selectedVideoTaskId: null,
    selectedDigitalHumanTaskId: null,

    // 新增分类（后端已返回，第一版前端仅消费 text_to_image + image_to_video）
    textToImageModels: [],
    imageEditModels: [],
    textToVideoModels: [],
    imageToVideoModels: [],

    // 对话模型（LLM），参考 script_writer，需要按供应商分组
    llmModels: [],
    llmVendors: [],
    selectedLlmModel: null,
    selectedScriptSplitLlmModel: null,

    // 思考模式（对齐 script_writer；与 localStorage lastThinkingState 共用）
    enableThinking: false,
    thinkingEffort: 'medium', // low | medium | high
    thinkingExplicitlyDisabled: false,
};

const THINKING_STATE_KEY = 'lastThinkingState';

function normalizeNumericId(value) {
    if (value === null || value === undefined || value === '') return null;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : value;
}

function getLlmModelValue(model) {
    if (!model) return '';
    return model.model || model.name || model.id || model.model_id || '';
}

function getLlmModelId(model) {
    if (!model) return null;
    return model.model_id || model.id || null;
}

function sameOptionalVendor(left, right) {
    if (left === null || left === undefined || left === '') return true;
    if (right === null || right === undefined || right === '') return true;
    return String(left) === String(right);
}

function resolveLlmModelSelection(selection) {
    if (!selection) return null;

    const rawModel = typeof selection === 'object'
        ? (selection.model || selection.name || '')
        : String(selection || '');
    const rawModelId = typeof selection === 'object'
        ? (selection.model_id || selection.id || null)
        : null;
    const rawVendorId = typeof selection === 'object'
        ? (selection.vendor_id ?? selection.vendorId ?? null)
        : null;

    let matched = null;
    const models = state.llmModels || [];
    if (rawModelId !== null && rawModelId !== undefined && rawModelId !== '') {
        matched = models.find(model =>
            String(getLlmModelId(model)) === String(rawModelId)
            && sameOptionalVendor(rawVendorId, model.vendor_id)
        );
    }
    if (!matched && rawModel) {
        matched = models.find(model =>
            String(getLlmModelValue(model)) === String(rawModel)
            && sameOptionalVendor(rawVendorId, model.vendor_id)
        );
    }

    if (!matched && typeof selection === 'object' && rawModelId) {
        matched = selection;
    }
    if (!matched) return null;

    const resolved = {
        model: getLlmModelValue(matched) || rawModel,
        model_id: normalizeNumericId(getLlmModelId(matched) || rawModelId),
        vendor_id: normalizeNumericId(matched.vendor_id ?? rawVendorId),
    };
    if (matched.name) resolved.name = matched.name;
    return resolved;
}

export function resolveSelectedLlmModel(selection = state.selectedLlmModel) {
    const resolved = resolveLlmModelSelection(selection);
    if (resolved) state.selectedLlmModel = resolved;
    return resolved;
}

export function resolveSelectedScriptSplitLlmModel(selection = state.selectedScriptSplitLlmModel) {
    const resolved = resolveLlmModelSelection(selection || state.selectedLlmModel);
    if (resolved) state.selectedScriptSplitLlmModel = resolved;
    return resolved;
}

/**
 * 解析当前选中 LLM 的元信息（含 supports_thinking / vendor）。
 * @param {object|string|null} selection 默认 selectedLlmModel
 */
export function getSelectedLlmMeta(selection = state.selectedLlmModel) {
    const models = state.llmModels || [];
    const vendors = state.llmVendors || [];
    let matched = null;
    if (selection && typeof selection === 'object') {
        const mid = selection.model_id || selection.id;
        const vid = selection.vendor_id;
        const name = selection.model || selection.name || '';
        matched = models.find(m => {
            if (mid != null && String(m.model_id || m.id) === String(mid)) {
                if (vid == null || vid === '') return true;
                return String(m.vendor_id || '') === String(vid);
            }
            return name && String(m.model || m.name || '') === String(name);
        }) || null;
    } else if (selection) {
        matched = models.find(m => String(m.model || m.name || m.id) === String(selection)) || null;
    }
    if (!matched && models.length) matched = models[0];

    const vendorId = matched?.vendor_id;
    const vendor = vendors.find(v => String(v.id || v.vendor_name) === String(vendorId))
        || vendors.find(v => String(v.vendor_name) === String(matched?.vendor_name));
    const vendorName = String(
        vendor?.vendor_name || matched?.vendor_name || matched?.vendor || ''
    ).toLowerCase();
    const modelName = String(matched?.model || matched?.name || '').toLowerCase();
    const supportsThinking = Boolean(
        matched?.supports_thinking === true
        || matched?.supports_thinking === 1
        || matched?.supports_thinking === '1'
        || matched?.supports_thinking === 'true'
    );
    return {
        model: matched,
        vendorName,
        modelName,
        supportsThinking,
        isDeepSeek: vendorName === 'deepseek'
            || modelName.includes('deepseek'),
        isDoubaoEffort: vendorName === 'volcengine'
            || modelName.startsWith('doubao')
            || modelName.includes('doubao'),
    };
}

/** 从 localStorage 恢复思考开关（与 script_writer 共用 key） */
export function loadThinkingStateFromStorage() {
    try {
        const raw = localStorage.getItem(THINKING_STATE_KEY);
        if (!raw) return;
        const saved = JSON.parse(raw);
        if (typeof saved.enabled === 'boolean') state.enableThinking = saved.enabled;
        if (saved.effort && ['low', 'medium', 'high'].includes(saved.effort)) {
            state.thinkingEffort = saved.effort;
        }
        state.thinkingExplicitlyDisabled = Boolean(saved.explicitlyDisabled);
    } catch (_) { /* ignore */ }
}

/**
 * 按当前模型校正思考 UI 状态（DeepSeek 默认开等）。
 * @param {object|string|null} selection
 * @param {{ userToggled?: boolean }} [opts]
 */
export function applyThinkingDefaultsForModel(selection = state.selectedLlmModel, opts = {}) {
    const meta = getSelectedLlmMeta(selection);
    if (!meta.supportsThinking) {
        state.enableThinking = false;
        return meta;
    }
    if (opts.userToggled) {
        return meta;
    }
    // DeepSeek：用户未明确关过则默认开启
    if (meta.isDeepSeek && !state.thinkingExplicitlyDisabled) {
        state.enableThinking = true;
    } else if (!meta.isDeepSeek && !state.thinkingExplicitlyDisabled) {
        // 其它支持思考的模型：沿用 storage 中的 enabled，不强制开
        // loadThinkingStateFromStorage 已写入 enableThinking
    }
    return meta;
}

/** 持久化思考状态 */
export function saveThinkingStateToStorage(isUserAction = false) {
    if (isUserAction) {
        state.thinkingExplicitlyDisabled = !state.enableThinking;
    }
    try {
        localStorage.setItem(THINKING_STATE_KEY, JSON.stringify({
            enabled: Boolean(state.enableThinking),
            effort: state.thinkingEffort || 'medium',
            explicitlyDisabled: Boolean(state.thinkingExplicitlyDisabled),
        }));
    } catch (_) { /* ignore */ }
}

/** 请求体用的思考参数 */
export function getThinkingParams() {
    if (!state.enableThinking) {
        return { enable_thinking: false, thinking_effort: 'medium' };
    }
    const effort = ['low', 'medium', 'high'].includes(state.thinkingEffort)
        ? state.thinkingEffort
        : 'medium';
    return { enable_thinking: true, thinking_effort: effort };
}

export function initStateFromUrl() {
    const params = new URLSearchParams(window.location.search);
    state.storyboardId = params.get('id') ? parseInt(params.get('id'), 10) : null;
    state.worldId = params.get('world_id') ? parseInt(params.get('world_id'), 10) : null;
    state.episodeNumber = params.get('episode_number') ? parseInt(params.get('episode_number'), 10) : 1;
    state.scriptId = params.get('script_id') ? parseInt(params.get('script_id'), 10) : null;
    state.workflowId = params.get('workflow_id') ? parseInt(params.get('workflow_id'), 10) : null;

    // 规范化 userId：必须是有效正整数，否则置 null，避免发送非法 X-User-Id 导致后端 422
    state.userId = null;
    const rawUserId = params.get('user_id') || localStorage.getItem('user_id');
    if (rawUserId) {
        const parsed = parseInt(rawUserId, 10);
        if (!isNaN(parsed) && parsed > 0) {
            state.userId = parsed;
        }
    }

    // auth_token **只**从 localStorage 读取，绝不从 URL 获取（避免敏感 token 泄露在地址栏、referrer、日志、历史记录中）
    // 参考 web/script_writer.html 的实现方式：
    //   const AUTH_TOKEN = localStorage.getItem('auth_token') || '';
    // storyboard 页面与 script_writer 保持一致，不再依赖 ?auth_token= 传参
    state.authToken = localStorage.getItem('auth_token') || localStorage.getItem('token') || null;

    // 分镜助手字号档位（跨故事板）
    try {
        const raw = localStorage.getItem('storyboard_agentChatFontStep');
        if (raw != null && raw !== '') {
            const step = parseInt(raw, 10);
            if (Number.isFinite(step)) {
                state.agentChatFontStep = clampAgentChatFontStep(step);
            }
        }
    } catch (_) { /* ignore */ }
}

/** 分镜助手字号档位边界与计算（上限偏高，方便大龄用户） */
export const AGENT_CHAT_FONT_STEP_MIN = -2;
export const AGENT_CHAT_FONT_STEP_MAX = 8;
export const AGENT_CHAT_FONT_BASE_PX = 12;

export function clampAgentChatFontStep(step) {
    const n = Number(step);
    if (!Number.isFinite(n)) return 0;
    return Math.max(AGENT_CHAT_FONT_STEP_MIN, Math.min(AGENT_CHAT_FONT_STEP_MAX, Math.round(n)));
}

/** @returns {{ step: number, bodyPx: number, labelPx: number }} */
export function getAgentChatFontSizes(step = state.agentChatFontStep) {
    const s = clampAgentChatFontStep(step);
    const bodyPx = AGENT_CHAT_FONT_BASE_PX + s;
    const labelPx = Math.max(10, bodyPx - 1);
    return { step: s, bodyPx, labelPx };
}

export function setAgentChatFontStep(step) {
    const next = clampAgentChatFontStep(step);
    state.agentChatFontStep = next;
    try {
        localStorage.setItem('storyboard_agentChatFontStep', String(next));
    } catch (_) { /* ignore */ }
    return next;
}

export function loadStoryboardData(data) {
    const storyboard = data.storyboard || {};
    state.storyboardId = storyboard.id;
    state.worldId = storyboard.world_id || state.worldId;
    state.episodeNumber = storyboard.episode_number || state.episodeNumber;
    state.scriptId = storyboard.script_id || state.scriptId;
    state.workflowId = storyboard.workflow_id || state.workflowId;
    state.title = buildStoryboardTitle(storyboard);
    state.style = storyboard.style || '';
    state.workflowRatio = storyboard.workflow_ratio || '16:9';
    state.compositionPreference = storyboard.composition_preference || '';
    state.scenes = scenesFromApi(data.scenes || []);
    state.showGenerateFromScriptDialog = false;
    state.isGeneratingFromScript = false;
    state.generateFromScriptError = '';

    if (!state.currentSceneId && state.scenes.length > 0) {
        state.currentSceneId = state.scenes[0].id;
    }
    if (state.currentSceneId && !getCurrentScene()) {
        state.currentSceneId = state.scenes[0] ? state.scenes[0].id : null;
    }
}

export function addSceneToState(rawScene) {
    const scene = sceneFromApi(rawScene);
    state.scenes = [...state.scenes, scene].sort((left, right) => left.sortOrder - right.sortOrder);
    state.currentSceneId = scene.id;
}

export function replaceSceneInState(rawScene) {
    const scene = sceneFromApi(rawScene);
    state.scenes = state.scenes.map(item => item.id === scene.id ? scene : item);
    state.currentSceneId = scene.id;
}

export function removeSceneFromState(sceneId) {
    state.scenes = state.scenes.filter(scene => scene.id !== sceneId);
    if (state.currentSceneId === sceneId) {
        state.currentSceneId = state.scenes[0] ? state.scenes[0].id : null;
    }
}

// ==================== 对话状态 helpers ====================
export function addDialogueToState(sceneId, rawDialogue) {
    const scene = state.scenes.find(item => item.id === sceneId);
    if (!scene) return;
    scene.dialogues = [...scene.dialogues, dialogueFromApi(rawDialogue)]
        .sort((left, right) => (left.sortOrder || 0) - (right.sortOrder || 0));
}

export function replaceDialogueInState(rawDialogue) {
    const dialogue = dialogueFromApi(rawDialogue);
    for (const scene of state.scenes) {
        if (scene.dialogues.some(item => item.id === dialogue.id)) {
            scene.dialogues = scene.dialogues
                .map(item => (item.id === dialogue.id ? dialogue : item))
                .sort((left, right) => (left.sortOrder || 0) - (right.sortOrder || 0));
            return;
        }
    }
}

export function removeDialogueFromState(dialogueId) {
    for (const scene of state.scenes) {
        scene.dialogues = scene.dialogues.filter(item => item.id !== dialogueId);
    }
}

export function setAssets({ characters = [], locations = [], props = [] }) {
    state.characters = characters.map(assetFromApi);
    state.locations = locations.map(assetFromApi);
    state.props = props.map(assetFromApi);
}

// 跨故事板 task_id 记忆兜底：读取 localStorage 中上一次的选择，校验仍存在于当前可用模型列表后才采用；
// 否则优先采用指定模型，再回退到列表第一个，并把回退值同步写回 localStorage 以固化默认。
function pickRememberedTaskId(models, storageKey, preferredModelKey = null) {
    const preferredModel = preferredModelKey
        ? models.find(m => m.short_key === preferredModelKey)
            || models.find(m => m.key === preferredModelKey)
        : null;
    const fallback = preferredModel?.task_id ?? models[0].task_id;
    let remembered = null;
    try {
        remembered = localStorage.getItem(storageKey);
    } catch {}
    if (remembered != null && models.some(m => String(m.task_id) === String(remembered))) {
        return Number(remembered);
    }
    try {
        localStorage.setItem(storageKey, String(fallback));
    } catch {}
    return fallback;
}

export function setModels({
    image_models,
    video_models,
    digital_human_models,
    // 新分类（可选，未传则不覆盖）
    text_to_image_models,
    image_edit_models,
    text_to_video_models,
    image_to_video_models,
    // LLM（可选）
    llm_models,
} = {}) {
    if (image_models !== undefined) state.imageModels = image_models;
    if (video_models !== undefined) state.videoModels = video_models;
    if (digital_human_models !== undefined) state.digitalHumanModels = digital_human_models;

    if (text_to_image_models !== undefined) {
        state.textToImageModels = text_to_image_models;
    } else if (image_models !== undefined) {
        state.textToImageModels = image_models;
    }
    if (image_edit_models !== undefined) state.imageEditModels = image_edit_models;
    if (text_to_video_models !== undefined) state.textToVideoModels = text_to_video_models;
    if (image_to_video_models !== undefined) {
        state.imageToVideoModels = image_to_video_models;
    } else if (video_models !== undefined) {
        state.imageToVideoModels = video_models;
    }

    // 默认选中逻辑（仅在首次且提供了对应列表时设置）
    // 优先级：config_json（已在 restoreUiConfig 恢复）> localStorage 跨故事板兜底 > 指定默认模型 > 列表第一个
    if (state.selectedImageTaskId == null && image_models && image_models.length) {
        state.selectedImageTaskId = pickRememberedTaskId(
            image_models,
            'storyboard_lastSelectedImageTaskId',
            'gpt-image-2',
        );
    }
    if (state.selectedVideoTaskId == null && video_models && video_models.length) {
        state.selectedVideoTaskId = pickRememberedTaskId(video_models, 'storyboard_lastSelectedVideoTaskId');
    }
    if (state.selectedDigitalHumanTaskId == null && digital_human_models && digital_human_models.length) {
        state.selectedDigitalHumanTaskId = digital_human_models[0].task_id;
    }

    if (llm_models !== undefined) {
        state.llmModels = llm_models;
        if (state.selectedLlmModel) {
            resolveSelectedLlmModel();
        }
        if (state.selectedScriptSplitLlmModel) {
            resolveSelectedScriptSplitLlmModel();
        }
    }
}

export function setLlmVendors(vendors = []) {
    state.llmVendors = vendors;
}

export function getCurrentScene() {
    return state.scenes.find(scene => scene.id === state.currentSceneId) || null;
}

function agentSceneKey(sceneId) {
    return sceneId === null || sceneId === undefined ? '' : String(sceneId);
}

export function isSceneAgentRunning(sceneId = state.currentSceneId) {
    const key = agentSceneKey(sceneId);
    return Boolean(key && state.agentRunsBySceneId[key]?.running);
}

export function startSceneAgentRun(sceneId, taskId = null) {
    const key = agentSceneKey(sceneId);
    if (!key) return null;
    const previous = state.agentRunsBySceneId[key] || {};
    const run = {
        ...previous,
        running: true,
        taskId: taskId || previous.taskId || null,
    };
    state.agentRunsBySceneId = { ...state.agentRunsBySceneId, [key]: run };
    return run;
}

export function setSceneAgentTaskId(sceneId, taskId) {
    return startSceneAgentRun(sceneId, taskId);
}

export function finishSceneAgentRun(sceneId, expectedTaskId = null) {
    const key = agentSceneKey(sceneId);
    const current = key ? state.agentRunsBySceneId[key] : null;
    if (!current) return false;
    if (expectedTaskId && current.taskId && String(current.taskId) !== String(expectedTaskId)) {
        return false;
    }
    const next = { ...state.agentRunsBySceneId };
    delete next[key];
    state.agentRunsBySceneId = next;
    return true;
}

export function setSceneAgentMessages(sceneId, messages = []) {
    const key = agentSceneKey(sceneId);
    if (!key) return [];
    const normalized = Array.isArray(messages) ? messages.slice(-40) : [];
    state.agentMessagesBySceneId = {
        ...state.agentMessagesBySceneId,
        [key]: normalized,
    };
    if (String(state.currentSceneId) === key) {
        state.agentMessages = normalized;
    }
    return normalized;
}

export function appendSceneAgentMessage(sceneId, message) {
    const key = agentSceneKey(sceneId);
    if (!key || !message) return [];
    const previous = state.agentMessagesBySceneId[key] || [];
    return setSceneAgentMessages(sceneId, [...previous.slice(-39), message]);
}

export function activateSceneAgentMessages(sceneId) {
    const key = agentSceneKey(sceneId);
    state.agentMessages = key ? (state.agentMessagesBySceneId[key] || []) : [];
    return state.agentMessages;
}

export function getTotalDuration() {
    return state.scenes.reduce((total, scene) => total + (scene.duration || 0), 0);
}

/** 单条可展示媒体 URL（排除逗号拼接多图） */
export function isRenderableMediaUrl(url) {
    if (url == null) return false;
    const value = String(url).trim();
    if (!value) return false;
    if (value.includes(',')) return false;
    return true;
}

/** 将相对 /upload 路径转为绝对 http(s)，满足后端/Agent 校验 */
export function toAbsoluteMediaUrl(url) {
    if (!isRenderableMediaUrl(url)) return '';
    const value = String(url).trim();
    if (/^https?:\/\//i.test(value)) return value;
    if (value.startsWith('//') && typeof window !== 'undefined') {
        return `${window.location.protocol}${value}`;
    }
    if (typeof window === 'undefined') return value;
    if (value.startsWith('/')) return `${window.location.origin}${value}`;
    return `${window.location.origin}/${value}`;
}

export function getSelectedVideoModel() {
    const models = state.imageToVideoModels.length ? state.imageToVideoModels : state.videoModels;
    return models.find(m => String(m.task_id) === String(state.selectedVideoTaskId)) || models[0] || null;
}

export function getSupportedVideoImageModes(model = null) {
    const m = model || getSelectedVideoModel();
    const modes = m?.supported_image_modes || m?.supportedImageModes;
    if (Array.isArray(modes) && modes.length) {
        return modes.map(String).filter(mode => mode === 'first_last_frame' || mode === 'multi_reference');
    }
    return ['first_last_frame'];
}

export function videoModelSupportsLastFrame(model = null) {
    const m = model || getSelectedVideoModel();
    if (!m) return true;
    if (m.supports_last_frame === false || m.supportsLastFrame === false) return false;
    return true;
}

export function getMaxVideoMediaCount(model = null) {
    const m = model || getSelectedVideoModel();
    if (state.videoImageMode === 'first_last_frame') {
        return videoModelSupportsLastFrame(m) ? 2 : 1;
    }
    const maxRef = Number(m?.max_multi_ref_images ?? m?.maxMultiRefImages ?? 5);
    return Number.isFinite(maxRef) && maxRef > 0 ? maxRef : 5;
}

function makeVideoMediaItem({ role, source, url, thumbnailUrl = '', name = '', uploading = false, id = null }) {
    return {
        id: id || `vm_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        role,
        source,
        url: url || '',
        thumbnailUrl: thumbnailUrl || url || '',
        name: name || '',
        uploading: Boolean(uploading),
    };
}

/** 兼容旧 referenceImages：从 videoMediaItems 同步 role=reference */
export function syncReferenceImagesCompat() {
    state.referenceImages = (state.videoMediaItems || [])
        .filter(item => item.role === 'reference')
        .map(item => ({
            id: item.id,
            url: item.url,
            thumbnailUrl: item.thumbnailUrl,
            name: item.name,
            uploading: item.uploading,
        }));
}

/**
 * 切换分镜/进入视频模式/切换视频图模式时：按当前分镜与模式重建槽位。
 * @param {object|null} scene
 * @param {{ resetUploads?: boolean }} options  resetUploads=true 清空用户上传；false 尽量保留上传项
 */
export function syncVideoMediaFromScene(scene, options = {}) {
    const resetUploads = options.resetUploads !== false;
    const sceneId = scene?.id ?? null;

    if (resetUploads) {
        state.videoFirstFrameDismissedSceneId = null;
    }

    const dismissed = state.videoFirstFrameDismissedSceneId != null
        && String(state.videoFirstFrameDismissedSceneId) === String(sceneId);

    const firstUrl = isRenderableMediaUrl(scene?.firstFrameUrl) ? String(scene.firstFrameUrl).trim() : '';
    const lastUrl = isRenderableMediaUrl(scene?.lastFrameUrl) ? String(scene.lastFrameUrl).trim() : '';

    // 保留用户上传项（按目标模式过滤角色）
    let uploads = resetUploads
        ? []
        : (state.videoMediaItems || []).filter(item => item.source === 'upload');

    if (state.videoImageMode === 'multi_reference') {
        uploads = uploads
            .filter(item => item.role === 'first_frame' || item.role === 'reference')
            .map(item => (item.role === 'last_frame' ? { ...item, role: 'reference' } : item));
    } else {
        // 首尾帧：只保留 first/last 上传
        uploads = uploads.filter(item => item.role === 'first_frame' || item.role === 'last_frame');
    }

    const next = [];

    // 首帧：用户上传优先，否则 scene 注入
    const uploadedFirst = uploads.find(item => item.role === 'first_frame');
    if (uploadedFirst) {
        next.push(uploadedFirst);
    } else if (firstUrl && !dismissed) {
        next.push(makeVideoMediaItem({
            role: 'first_frame',
            source: 'scene',
            url: firstUrl,
            thumbnailUrl: firstUrl,
            name: '当前首帧',
        }));
    }

    if (state.videoImageMode === 'first_last_frame') {
        const uploadedLast = uploads.find(item => item.role === 'last_frame');
        if (uploadedLast && videoModelSupportsLastFrame()) {
            next.push(uploadedLast);
        } else if (lastUrl && videoModelSupportsLastFrame() && !uploads.some(item => item.role === 'last_frame')) {
            next.push(makeVideoMediaItem({
                role: 'last_frame',
                source: 'scene',
                url: lastUrl,
                thumbnailUrl: lastUrl,
                name: '当前尾帧',
            }));
        }
    } else {
        uploads.filter(item => item.role === 'reference').forEach(item => next.push(item));
    }

    // 截断到模型上限
    const maxCount = getMaxVideoMediaCount();
    state.videoMediaItems = next.slice(0, maxCount);
    syncReferenceImagesCompat();
}

/** 仅刷新 scene 来源的首帧 URL（用户切换候选图后） */
export function refreshSceneFirstFrameSlot(scene) {
    if (!scene) return;
    const firstUrl = isRenderableMediaUrl(scene.firstFrameUrl) ? String(scene.firstFrameUrl).trim() : '';
    const dismissed = state.videoFirstFrameDismissedSceneId != null
        && String(state.videoFirstFrameDismissedSceneId) === String(scene.id);
    let items = [...(state.videoMediaItems || [])];
    const idx = items.findIndex(item => item.role === 'first_frame' && item.source === 'scene');
    if (dismissed) {
        if (idx >= 0) items.splice(idx, 1);
    } else if (firstUrl) {
        if (idx >= 0) {
            items[idx] = { ...items[idx], url: firstUrl, thumbnailUrl: firstUrl };
        } else if (!items.some(item => item.role === 'first_frame')) {
            items.unshift(makeVideoMediaItem({
                role: 'first_frame',
                source: 'scene',
                url: firstUrl,
                thumbnailUrl: firstUrl,
                name: '当前首帧',
            }));
        }
    } else if (idx >= 0) {
        items.splice(idx, 1);
    }
    state.videoMediaItems = items;
    syncReferenceImagesCompat();
}

export function ensureVideoImageModeSupported() {
    const modes = getSupportedVideoImageModes();
    if (!modes.includes(state.videoImageMode)) {
        state.videoImageMode = modes[0] || 'first_last_frame';
    }
}

/** 组装发送用有序绝对 URL 列表 */
export function buildVideoSlotUrls() {
    const items = state.videoMediaItems || [];
    const ready = items.filter(item => !item.uploading && isRenderableMediaUrl(item.url));
    let ordered = [];
    if (state.videoImageMode === 'multi_reference') {
        const first = ready.find(item => item.role === 'first_frame');
        const refs = ready.filter(item => item.role === 'reference');
        ordered = [first, ...refs].filter(Boolean);
    } else {
        const first = ready.find(item => item.role === 'first_frame');
        const last = ready.find(item => item.role === 'last_frame');
        ordered = [first, last].filter(Boolean);
    }
    return ordered.map(item => toAbsoluteMediaUrl(item.url)).filter(Boolean);
}

export function canAddVideoMedia() {
    const count = (state.videoMediaItems || []).filter(item => !item.uploading || item.url).length;
    return count < getMaxVideoMediaCount();
}

export function createVideoMediaItem(opts) {
    return makeVideoMediaItem(opts);
}

/** 当前模型支持的视频时长列表（升序整数秒） */
export function getVideoSupportedDurations(model = null) {
    const m = model || getSelectedVideoModel();
    const list = m?.supported_durations || m?.supportedDurations || [];
    const nums = list
        .map(d => Number(d))
        .filter(d => Number.isFinite(d) && d > 0)
        .map(d => Math.round(d));
    return [...new Set(nums)].sort((a, b) => a - b);
}

/**
 * auto 时长：选 >= 分镜时长的最小支持秒数；若无则取最大支持秒数。
 * @param {object|null} scene
 * @param {object|null} model
 * @param {'auto'|number|string} mode
 */
export function resolveVideoDurationSeconds(scene = null, model = null, mode = null) {
    const options = getVideoSupportedDurations(model);
    const sc = scene || getCurrentScene();
    const target = Number(sc?.duration);
    const rawMode = mode == null ? state.videoDurationMode : mode;

    if (!options.length) {
        if (Number.isFinite(target) && target > 0) return Math.max(1, Math.ceil(target));
        return 5;
    }

    if (rawMode === 'auto' || rawMode === 'Auto' || rawMode == null || rawMode === '') {
        if (!Number.isFinite(target) || target <= 0) return options[0];
        const ge = options.filter(d => d >= target);
        return ge.length ? Math.min(...ge) : Math.max(...options);
    }

    const wanted = Number(rawMode);
    if (Number.isFinite(wanted) && options.includes(Math.round(wanted))) {
        return Math.round(wanted);
    }
    if (Number.isFinite(wanted)) {
        const ge = options.filter(d => d >= wanted);
        return ge.length ? Math.min(...ge) : Math.max(...options);
    }
    return options[0];
}

export function getVideoResolutionOptions(model = null) {
    const m = model || getSelectedVideoModel();
    const raw = m?.supported_video_resolutions || m?.supportedVideoResolutions || [];
    if (!Array.isArray(raw)) return [];
    return raw
        .map(item => {
            if (!item) return null;
            if (typeof item === 'string') return { value: item, label: item };
            const value = String(item.value || item.label || '').trim();
            if (!value) return null;
            return { value, label: String(item.label || value) };
        })
        .filter(Boolean);
}

export function getDefaultVideoResolution(model = null) {
    const m = model || getSelectedVideoModel();
    const def = m?.default_video_resolution || m?.defaultVideoResolution || '';
    if (def) return String(def);
    const opts = getVideoResolutionOptions(m);
    return opts[0]?.value || null;
}

/** 切换视频模型后校正时长模式与分辨率 */
export function ensureVideoGenerationPrefsSupported() {
    const model = getSelectedVideoModel();
    const durations = getVideoSupportedDurations(model);
    if (state.videoDurationMode !== 'auto') {
        const n = Number(state.videoDurationMode);
        if (!Number.isFinite(n) || !durations.includes(Math.round(n))) {
            state.videoDurationMode = 'auto';
        } else {
            state.videoDurationMode = Math.round(n);
        }
    }
    const resOpts = getVideoResolutionOptions(model);
    if (!resOpts.length) {
        state.videoResolution = null;
    } else {
        const values = resOpts.map(o => o.value);
        if (!state.videoResolution || !values.includes(state.videoResolution)) {
            state.videoResolution = getDefaultVideoResolution(model);
        }
    }
}

export function buildVideoGenerationPayloadExtras(scene = null) {
    const sc = scene || getCurrentScene();
    ensureVideoGenerationPrefsSupported();
    const durationSeconds = resolveVideoDurationSeconds(sc);
    return {
        duration: durationSeconds,
        duration_mode: state.videoDurationMode === 'auto' ? 'auto' : Number(state.videoDurationMode),
        resolution: state.videoResolution || undefined,
        clip_to_audio_duration: state.clipToAudioDuration !== false,
    };
}

export function serializeUiConfig() {
    return {
        activeTab: state.activeTab,
        viewMode: state.viewMode,
        chatMode: state.chatMode,
        videoImageMode: state.videoImageMode,
        videoDurationMode: state.videoDurationMode,
        videoResolution: state.videoResolution,
        clipToAudioDuration: state.clipToAudioDuration,
        aiOptimize: state.aiOptimize,
        subtitleEnabled: state.subtitleEnabled,
        selectedImageTaskId: state.selectedImageTaskId,
        selectedVideoTaskId: state.selectedVideoTaskId,
        selectedDigitalHumanTaskId: state.selectedDigitalHumanTaskId,
        autoImageSequenceMode: state.autoImageSequenceMode,
        // 第一版准备：对话模型记忆（画风/构图由后端 storyboard 主表承载）
        selectedLlmModel: state.selectedLlmModel,
        selectedScriptSplitLlmModel: state.selectedScriptSplitLlmModel,
        // 剧本拆分参数
        maxGroupDuration: state.maxGroupDuration,
        forceMediumShot: state.forceMediumShot,
        noBgMusic: state.noBgMusic,
        splitMultiDialogue: state.splitMultiDialogue,
        scriptDialogueLanguage: state.scriptDialogueLanguage,
        scriptPromptLanguage: state.scriptPromptLanguage,
        enableScriptSplitQc: state.enableScriptSplitQc === true,
        scriptSplitQcMaxRounds: state.scriptSplitQcMaxRounds,
    };
}

export function restoreUiConfig(config = {}) {
    state.activeTab = config.activeTab === 'dialogue' ? 'dialogue' : (config.activeTab || state.activeTab);
    state.viewMode = config.viewMode === 'grid' ? 'grid' : (config.viewMode || state.viewMode);
    state.chatMode = config.chatMode === 'video' ? 'video' : 'dialogue';
    if (config.videoImageMode === 'multi_reference' || config.videoImageMode === 'first_last_frame') {
        state.videoImageMode = config.videoImageMode;
    }
    if (config.videoDurationMode === 'auto' || Number.isFinite(Number(config.videoDurationMode))) {
        state.videoDurationMode = config.videoDurationMode === 'auto'
            ? 'auto'
            : Number(config.videoDurationMode);
    }
    if (config.videoResolution !== undefined) {
        state.videoResolution = config.videoResolution || null;
    }
    if (typeof config.clipToAudioDuration === 'boolean') {
        state.clipToAudioDuration = config.clipToAudioDuration;
    }
    state.aiOptimize = config.aiOptimize !== false;
    state.subtitleEnabled = config.subtitleEnabled !== false;
    if (config.selectedImageTaskId !== undefined && config.selectedImageTaskId !== null) {
        state.selectedImageTaskId = config.selectedImageTaskId;
    }
    if (config.selectedVideoTaskId !== undefined && config.selectedVideoTaskId !== null) {
        state.selectedVideoTaskId = config.selectedVideoTaskId;
    }
    if (config.selectedDigitalHumanTaskId !== undefined && config.selectedDigitalHumanTaskId !== null) {
        state.selectedDigitalHumanTaskId = config.selectedDigitalHumanTaskId;
    }
    if (['speed', 'balanced', 'quality'].includes(config.autoImageSequenceMode)) {
        if (config.autoImageSequenceMode === 'quality' && state.editionInfo?.mode === 'enterprise') {
            state.autoImageSequenceMode = 'quality';
        } else if (config.autoImageSequenceMode !== 'quality') {
            state.autoImageSequenceMode = config.autoImageSequenceMode;
        } else {
            state.autoImageSequenceMode = 'balanced';
        }
    }
    // 剧本拆分参数恢复（含取值合法性校验）
    if ([5, 8, 10, 15].includes(Number(config.maxGroupDuration))) {
        state.maxGroupDuration = Number(config.maxGroupDuration);
    }
    if (typeof config.forceMediumShot === 'boolean') {
        state.forceMediumShot = config.forceMediumShot;
    }
    if (typeof config.noBgMusic === 'boolean') {
        state.noBgMusic = config.noBgMusic;
    }
    if (typeof config.splitMultiDialogue === 'boolean') {
        state.splitMultiDialogue = config.splitMultiDialogue;
    }
    if (typeof config.scriptDialogueLanguage === 'string') {
        state.scriptDialogueLanguage = config.scriptDialogueLanguage;
        state.scriptDialogueLanguageCustom = !['', 'English', 'Deutsch', 'Français', 'Русский']
            .includes(config.scriptDialogueLanguage);
    }
    if (typeof config.scriptPromptLanguage === 'string') {
        state.scriptPromptLanguage = config.scriptPromptLanguage;
        state.scriptPromptLanguageCustom = !['', 'English', 'Deutsch', 'Français', 'Русский']
            .includes(config.scriptPromptLanguage);
    }
    if (typeof config.enableScriptSplitQc === 'boolean') {
        state.enableScriptSplitQc = config.enableScriptSplitQc;
    }
    if ([1, 2, 3, 4, 5].includes(Number(config.scriptSplitQcMaxRounds))) {
        state.scriptSplitQcMaxRounds = Number(config.scriptSplitQcMaxRounds);
    }

    if (config.selectedLlmModel) {
        state.selectedLlmModel = config.selectedLlmModel;
        resolveSelectedLlmModel();
    }
    if (config.selectedScriptSplitLlmModel) {
        state.selectedScriptSplitLlmModel = config.selectedScriptSplitLlmModel;
        resolveSelectedScriptSplitLlmModel();
    }
}

/** 把剧本拆分轮询状态同步到进度弹框。 */
export function applyGenerateProgressStatus(statusData = {}) {
    const progress = Number(statusData.progress);
    if (Number.isFinite(progress)) {
        state.generateProgressPercent = Math.round(Math.max(0, Math.min(100, progress)));
    }
    state.generateProgressMessage = String(statusData.message || '正在处理任务');
}

/** 比例门禁是否拦截业务操作（首建未确认比例）。 */
export function isRatioGateBlocking() {
    return !!state.ratioGateActive;
}

export default state;
