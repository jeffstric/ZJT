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
