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

    title: '故事板',
    style: '',
    workflowRatio: '16:9',
    compositionPreference: '',
    computingPower: null,

    scenes: [],
    currentSceneId: null,
    activeTab: 'scene',          // 'scene' | 'dialogue'（音乐 Tab 已移除）
    viewMode: 'timeline',
    chatMode: 'image',
    inputMessage: '',
    aiOptimize: true,
    subtitleEnabled: true,
    isPlaying: false,
    currentTime: 0,
    showEditPrompt: false,
    showExportDialog: false,
    showMentionPopup: false,
    mentionTab: 'character',
    isSaving: false,
    error: '',

    characters: [],
    locations: [],
    props: [],

    // 模型列表与选择（task_id 作为生成时的 task_type）
    imageModels: [],
    videoModels: [],
    digitalHumanModels: [],
    selectedImageTaskId: null,
    selectedVideoTaskId: null,
    selectedDigitalHumanTaskId: null,
};

export function initStateFromUrl() {
    const params = new URLSearchParams(window.location.search);
    state.storyboardId = params.get('id') ? parseInt(params.get('id'), 10) : null;
    state.worldId = params.get('world_id') ? parseInt(params.get('world_id'), 10) : null;
    state.episodeNumber = params.get('episode_number') ? parseInt(params.get('episode_number'), 10) : 1;
    state.scriptId = params.get('script_id') ? parseInt(params.get('script_id'), 10) : null;
    state.workflowId = params.get('workflow_id') ? parseInt(params.get('workflow_id'), 10) : null;
    state.userId = params.get('user_id') || localStorage.getItem('user_id') || null;
    state.authToken = params.get('auth_token') || localStorage.getItem('auth_token') || localStorage.getItem('token') || null;
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

export function setModels({ image_models = [], video_models = [], digital_human_models = [] }) {
    state.imageModels = image_models;
    state.videoModels = video_models;
    state.digitalHumanModels = digital_human_models;
    if (state.selectedImageTaskId == null && image_models.length) state.selectedImageTaskId = image_models[0].task_id;
    if (state.selectedVideoTaskId == null && video_models.length) state.selectedVideoTaskId = video_models[0].task_id;
    if (state.selectedDigitalHumanTaskId == null && digital_human_models.length) {
        state.selectedDigitalHumanTaskId = digital_human_models[0].task_id;
    }
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
    };
}

export function restoreUiConfig(config = {}) {
    state.activeTab = config.activeTab === 'dialogue' ? 'dialogue' : (config.activeTab || state.activeTab);
    state.viewMode = config.viewMode === 'grid' ? 'grid' : (config.viewMode || state.viewMode);
    state.chatMode = config.chatMode || state.chatMode;
    state.aiOptimize = config.aiOptimize !== false;
    state.subtitleEnabled = config.subtitleEnabled !== false;
}

export default state;
