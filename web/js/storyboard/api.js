import state from './state.js';
import { normalizePagedList } from './adapters.js';

const API_BASE = '/api/storyboard';

function authHeaders(json = true) {
    const headers = {};
    if (json) headers['Content-Type'] = 'application/json';
    if (state.userId) headers['X-User-Id'] = state.userId;
    if (state.authToken) {
        headers.Authorization = state.authToken.startsWith('Bearer ')
            ? state.authToken
            : `Bearer ${state.authToken}`;
    }
    return headers;
}

async function readJson(resp) {
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        throw new Error(data.error || data.message || `HTTP ${resp.status}`);
    }
    return data;
}

async function request(path, options = {}) {
    const resp = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: {
            ...authHeaders(options.body !== undefined),
            ...(options.headers || {}),
        },
    });
    return readJson(resp);
}

// ==================== 故事板 ====================
export async function createStoryboard(data) {
    return request('/create', { method: 'POST', body: JSON.stringify(data) });
}
export async function getStoryboard(storyboardId) {
    return request(`/${storyboardId}`);
}
export async function updateStoryboard(storyboardId, data) {
    return request(`/${storyboardId}`, { method: 'PUT', body: JSON.stringify(data) });
}

// ==================== 分镜 ====================
export async function addScene(storyboardId, data) {
    return request(`/${storyboardId}/scene`, { method: 'POST', body: JSON.stringify(data) });
}
export async function updateScene(sceneId, data) {
    return request(`/scene/${sceneId}`, { method: 'PUT', body: JSON.stringify(data) });
}
export async function updateScenePrompt(sceneId, promptJson) {
    return request(`/scene/${sceneId}/prompt`, { method: 'PUT', body: JSON.stringify({ prompt_json: promptJson }) });
}
export async function deleteScene(sceneId) {
    return request(`/scene/${sceneId}`, { method: 'DELETE' });
}
export async function duplicateScene(sceneId) {
    return request(`/scene/${sceneId}/duplicate`, { method: 'POST' });
}
export async function reorderScene(storyboardId, data) {
    // 浮点二分：{scene_id, prev_id, next_id}
    return request(`/${storyboardId}/scene/reorder`, { method: 'PUT', body: JSON.stringify(data) });
}

// ==================== 对话 ====================
export async function listDialogues(sceneId) {
    return request(`/scene/${sceneId}/dialogues`);
}
export async function addDialogue(sceneId, data) {
    return request(`/scene/${sceneId}/dialogue`, { method: 'POST', body: JSON.stringify(data) });
}
export async function updateDialogue(dialogueId, data) {
    return request(`/dialogue/${dialogueId}`, { method: 'PUT', body: JSON.stringify(data) });
}
export async function deleteDialogue(dialogueId) {
    return request(`/dialogue/${dialogueId}`, { method: 'DELETE' });
}
export async function reorderDialogue(sceneId, data) {
    // 浮点二分：{dialogue_id, prev_id, next_id}
    return request(`/scene/${sceneId}/dialogue/reorder`, { method: 'PUT', body: JSON.stringify(data) });
}
export async function generateDialogueVoiceover(dialogueId, config = {}) {
    return request(`/dialogue/${dialogueId}/generate-voiceover`, { method: 'POST', body: JSON.stringify(config) });
}
export async function selectDialogueAudio(dialogueId, dialogueAudioId) {
    return request(`/dialogue/${dialogueId}/audio/select`, {
        method: 'POST', body: JSON.stringify({ dialogue_audio_id: dialogueAudioId }),
    });
}

// ==================== 资产 ====================
export async function listSceneAssets(sceneId, assetType) {
    const qs = assetType ? `?asset_type=${encodeURIComponent(assetType)}` : '';
    return request(`/scene/${sceneId}/assets${qs}`);
}
export async function selectSceneAsset(sceneId, assetType, assetId) {
    return request(`/scene/${sceneId}/asset/select`, {
        method: 'POST', body: JSON.stringify({ asset_type: assetType, asset_id: assetId }),
    });
}

// ==================== 生成 / 任务状态 ====================
export async function generateSceneImage(sceneId, config = {}) {
    return request(`/scene/${sceneId}/generate-image`, { method: 'POST', body: JSON.stringify(config) });
}
export async function generateSceneVideo(sceneId, config = {}) {
    return request(`/scene/${sceneId}/generate-video`, { method: 'POST', body: JSON.stringify(config) });
}
export async function getSceneTaskStatus(sceneId) {
    return request(`/scene/${sceneId}/task-status`);
}

// 模型列表（图片 / 图生视频 / 数字人）
export async function fetchStoryboardModels() {
    return request('/models');
}

// ==================== 导出 ====================
export async function exportFullVideo(storyboardId) {
    return request(`/${storyboardId}/export-full-video`, { method: 'POST' });
}
export async function exportAllScenes(storyboardId) {
    return request(`/${storyboardId}/export-all-scenes`, { method: 'POST' });
}

// ==================== 资产（@提及）/ 算力 ====================
async function fetchPaged(path) {
    const resp = await fetch(path, { headers: authHeaders(false) });
    return normalizePagedList(await readJson(resp));
}

export async function fetchCharacters(worldId) {
    return fetchPaged(`/api/characters?world_id=${encodeURIComponent(worldId)}&page_size=100`);
}
export async function fetchLocations(worldId) {
    return fetchPaged(`/api/locations?world_id=${encodeURIComponent(worldId)}&page_size=100`);
}
export async function fetchProps(worldId) {
    return fetchPaged(`/api/props?world_id=${encodeURIComponent(worldId)}&page_size=100`);
}

export async function fetchComputingPower() {
    if (!state.authToken) return { computing_power: null };
    const resp = await fetch('/api/user/computing_power', { headers: authHeaders(false) });
    if (!resp.ok) return { computing_power: null };
    const data = await resp.json().catch(() => ({}));
    return data.data || data;
}
