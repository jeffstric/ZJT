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

    scenes: [],
    currentSceneId: null,
    activeTab: 'scene',          // 'scene' | 'dialogue'（音乐 Tab 已移除）
    viewMode: 'timeline',
    chatMode: 'dialogue',
    inputMessage: '',
    // 视频生成模式下用户上传的补充参考图：[{id, url, thumbnailUrl, name, uploading}]
    // 首帧图始终由 scene_context 提供（该分镜选中首帧），此处仅存补充参考图；切换分镜时清空。
    referenceImages: [],
    agentMessages: [],
    isAgentRunning: false,
    activeAgentTaskId: null,
    aiOptimize: true,
    subtitleEnabled: true,
    isPlaying: false,
    currentTime: 0,
    showExportDialog: false,
    showMentionPopup: false,
    showGlobalStyleDialog: false,
    mentionTab: 'character',
    isSaving: false,
    error: '',
    showGenerateFromScriptDialog: false,
    isGeneratingFromScript: false,
    generateFromScriptError: '',
    autoImageSequenceMode: 'balanced',
    // 剧本拆分参数（与 video_workflow 剧本节点保持一致：true/true/false/15）
    maxGroupDuration: 15,
    forceMediumShot: true,
    noBgMusic: true,
    splitMultiDialogue: false,

    // 生成分镜进度弹框
    showGenerateProgressDialog: false,
    generateProgressSteps: [],
    generateProgressStepIndex: -1,
    generateProgressError: '',

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
};

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
// 否则回退到列表第一个，并把回退值同步写回 localStorage 以固化默认。
function pickRememberedTaskId(models, storageKey) {
    const fallback = models[0].task_id;
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
    // 优先级：config_json（已在 restoreUiConfig 恢复）> localStorage 跨故事板兜底 > 列表第一个
    if (state.selectedImageTaskId == null && image_models && image_models.length) {
        state.selectedImageTaskId = pickRememberedTaskId(image_models, 'storyboard_lastSelectedImageTaskId');
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

export function getTotalDuration() {
    return state.scenes.reduce((total, scene) => total + (scene.duration || 0), 0);
}

export function serializeUiConfig() {
    return {
        activeTab: state.activeTab,
        viewMode: state.viewMode,
        chatMode: state.chatMode,
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
    };
}

export function restoreUiConfig(config = {}) {
    state.activeTab = config.activeTab === 'dialogue' ? 'dialogue' : (config.activeTab || state.activeTab);
    state.viewMode = config.viewMode === 'grid' ? 'grid' : (config.viewMode || state.viewMode);
    state.chatMode = config.chatMode === 'video' ? 'video' : 'dialogue';
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

    if (config.selectedLlmModel) {
        state.selectedLlmModel = config.selectedLlmModel;
        resolveSelectedLlmModel();
    }
    if (config.selectedScriptSplitLlmModel) {
        state.selectedScriptSplitLlmModel = config.selectedScriptSplitLlmModel;
        resolveSelectedScriptSplitLlmModel();
    }
}

export default state;
