import state from './state.js';
import { normalizePagedList } from './adapters.js';

const API_BASE = '/api/storyboard';

/**
 * 统一认证错误处理。
 * 检测到 401 或 TOKEN_EXPIRED 时清理本地凭证并跳转首页登录页，登录后可回到当前页面。
 * @param {number} status HTTP 状态码
 * @param {object} data 响应体
 * @returns {boolean} 是否已按认证错误处理
 */
export function handleAuthError(status, data = {}) {
    const isAuthError = status === 401
        || data.token_expired
        || data.error_code === 'TOKEN_EXPIRED'
        || (data.error && String(data.error).toUpperCase() === 'TOKEN_EXPIRED');
    if (!isAuthError) return false;

    try {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('token');
        localStorage.removeItem('user_id');
    } catch (_) { /* ignore */ }

    const message = window.t ? window.t('alert_login_expired') : '登录已过期\n\n您的登录信息已过期，请重新登录。';
    alert('⚠️ ' + message);

    const redirectUrl = window.location.pathname + window.location.search;
    window.location.href = '/?login=1&redirect_url=' + encodeURIComponent(redirectUrl);
    return true;
}

function authHeaders(json = true) {
    const headers = {};
    if (json) headers['Content-Type'] = 'application/json';
    // 只在 userId 是有效数字时发送，避免后端 int 解析失败导致 422
    if (state.userId && typeof state.userId === 'number' && !isNaN(state.userId) && state.userId > 0) {
        headers['X-User-Id'] = state.userId;
    }
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
        handleAuthError(resp.status, data);
        const error = new Error(data.message || data.error || `HTTP ${resp.status}`);
        error.status = resp.status;
        error.code = data.error_code || data.error || data.code || '';
        error.payload = data.payload || data || {};
        error.response = data;
        throw error;
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

export async function getEditionInfo() {
    try {
        const resp = await fetch('/api/edition', { headers: authHeaders(false) });
        if (!resp.ok) return { mode: 'community', mode_label: '社区版' };
        const data = await resp.json().catch(() => ({}));
        return data.data || data || { mode: 'community', mode_label: '社区版' };
    } catch {
        return { mode: 'community', mode_label: '社区版' };
    }
}

// ==================== 故事板 ====================
export async function createStoryboard(data) {
    return request('/create', { method: 'POST', body: JSON.stringify(data) });
}

/** 新建前探测默认画幅：是否需要弹窗确认、可继承的比例 */
export async function getStoryboardCreateDefaults(worldId) {
    const qs = worldId != null && worldId !== ''
        ? `?world_id=${encodeURIComponent(worldId)}`
        : '';
    return request(`/create-defaults${qs}`);
}

/** 当前用户在某世界下的「集」文件夹（剧本 + 故事板），含尚未创建故事板的集 */
export async function listStoryboardFolders(worldId) {
    const qs = worldId != null && worldId !== ''
        ? `?world_id=${encodeURIComponent(worldId)}`
        : '';
    const data = await request(`/folders${qs}`);
    if (Array.isArray(data?.folders)) return data.folders;
    if (Array.isArray(data?.data?.folders)) return data.data.folders;
    if (Array.isArray(data)) return data;
    return [];
}
export async function getStoryboard(storyboardId) {
    return request(`/${storyboardId}`);
}
export async function updateStoryboard(storyboardId, data) {
    return request(`/${storyboardId}`, { method: 'PUT', body: JSON.stringify(data) });
}
export async function generateFromScript(storyboardId, data = {}) {
    return request(`/${storyboardId}/generate-from-script`, { method: 'POST', body: JSON.stringify(data) });
}

// 剧本分段拆分任务接口（前缀 /api/script-split，与 storyboard 独立）
async function requestSplit(path, options = {}) {
    const resp = await fetch(`/api/script-split${path}`, {
        ...options,
        headers: {
            ...authHeaders(options.body !== undefined),
            ...(options.headers || {}),
        },
    });
    return readJson(resp);
}
export async function getScriptSplitTaskStatus(taskId) {
    const result = await requestSplit(`/tasks/${taskId}`);
    return result.data;
}
export async function getScriptSplitTaskResult(taskId) {
    const result = await requestSplit(`/tasks/${taskId}/result`);
    return result.data;
}
export async function getActiveScriptSplitTask(sourceType, sourceId) {
    const result = await requestSplit(`/active-task?source_type=${encodeURIComponent(sourceType)}&source_id=${encodeURIComponent(sourceId)}`);
    return result.data;
}
export async function resumeScriptSplitTask(taskId) {
    const result = await requestSplit(`/tasks/${taskId}/resume`, { method: 'POST' });
    return result.data;
}
export async function cancelScriptSplitTask(taskId) {
    const result = await requestSplit(`/tasks/${taskId}/cancel`, { method: 'POST' });
    return result.data;
}

// ==================== 分镜 ====================
export async function addScene(storyboardId, data) {
    return request(`/${storyboardId}/scene`, { method: 'POST', body: JSON.stringify(data) });
}
export async function updateScene(sceneId, data) {
    return request(`/scene/${sceneId}`, { method: 'PUT', body: JSON.stringify(data) });
}
export async function switchSceneVideoType(sceneId, videoType, expectedVideoType) {
    return request(`/scene/${sceneId}/video-type`, {
        method: 'PUT',
        body: JSON.stringify({
            video_type: videoType,
            expected_video_type: expectedVideoType,
        }),
    });
}
export async function updateScenePrompt(sceneId, promptJson) {
    return request(`/scene/${sceneId}/prompt`, { method: 'PUT', body: JSON.stringify({ prompt_json: promptJson }) });
}
export async function deleteScene(sceneId) {
    return request(`/scene/${sceneId}`, { method: 'DELETE' });
}
export async function batchDeleteScenes(storyboardId, sceneIds) {
    return request(`/${storyboardId}/scenes/batch-delete`, {
        method: 'POST',
        body: JSON.stringify({ scene_ids: sceneIds }),
    });
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
export async function batchGenerateMissingVoiceovers(storyboardId, sceneIds) {
    return request(`/${storyboardId}/batch-generate-missing-voiceovers`, {
        method: 'POST',
        body: JSON.stringify({ scene_ids: sceneIds, skip_existing: true }),
    });
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
export async function deleteSceneAsset(sceneId, assetId) {
    return request(`/scene/${encodeURIComponent(sceneId)}/asset/${encodeURIComponent(assetId)}`, {
        method: 'DELETE',
    });
}

/**
 * 上传图片或视频并登记为分镜资产（候选区手工上传、涂色编辑等）。
 * FormData 不可设 Content-Type，由浏览器自动填充 boundary。
 * @returns {Promise<{success:boolean, asset_id?:number, result_url?:string, asset_type?:string, selected?:boolean, error?:string}>}
 */
export async function uploadSceneAsset(sceneId, file, {
    assetType = 'first_frame',
    setSelected = true,
} = {}) {
    const form = new FormData();
    form.append('file', file);
    form.append('asset_type', assetType);
    form.append('set_selected', setSelected ? 'true' : 'false');
    const resp = await fetch(`${API_BASE}/scene/${encodeURIComponent(sceneId)}/asset/upload`, {
        method: 'POST',
        headers: authHeaders(false),
        body: form,
    });
    return readJson(resp);
}

// ==================== 生成 / 任务状态 ====================
export async function generateSceneImage(sceneId, config = {}) {
    return request(`/scene/${sceneId}/generate-image`, { method: 'POST', body: JSON.stringify(config) });
}
export async function autoGenerateMissingImages(storyboardId, config = {}) {
    return request(`/${storyboardId}/auto-generate-missing-images`, {
        method: 'POST',
        body: JSON.stringify(config),
    });
}
export async function autoGenerateMissingVideos(storyboardId, config = {}) {
    return request(`/${storyboardId}/auto-generate-missing-videos`, {
        method: 'POST',
        body: JSON.stringify(config),
    });
}
export async function generateSceneVideo(sceneId, config = {}) {
    return request(`/scene/${sceneId}/generate-video`, { method: 'POST', body: JSON.stringify(config) });
}
export async function getSceneTaskStatus(sceneId) {
    return request(`/scene/${sceneId}/task-status`);
}
export async function getStoryboardTaskStatus(storyboardId, assetType = 'first_frame') {
    const qs = assetType ? `?asset_type=${encodeURIComponent(assetType)}` : '';
    return request(`/${storyboardId}/task-status${qs}`);
}
export async function getStoryboardImageBatchStatus(batchId) {
    return request(`/image-batches/${batchId}/status`);
}

export async function startSceneAgentChat(sceneId, data = {}) {
    return request(`/scene/${sceneId}/ai-chat`, { method: 'POST', body: JSON.stringify(data) });
}
export async function fetchSceneAgentChatHistory(sceneId) {
    return request(`/scene/${sceneId}/ai-chat/history`);
}

export function streamStoryboardAgentTask(taskId, handlers = {}) {
    const controller = new AbortController();
    const stream = async () => {
        const resp = await fetch(`${API_BASE}/agent-task/${encodeURIComponent(taskId)}/stream`, {
            headers: authHeaders(false),
            signal: controller.signal,
        });
        if (!resp.ok || !resp.body) {
            throw new Error(`HTTP ${resp.status}`);
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split(/\r?\n\r?\n/);
            buffer = parts.pop() || '';
            for (const part of parts) {
                const dataLine = part.split('\n').find(line => line.startsWith('data:'));
                if (!dataLine) continue;
                let data = {};
                try {
                    data = JSON.parse(dataLine.slice(5).trim() || '{}');
                } catch {
                    data = { type: 'message', content: dataLine.slice(5).trim() };
                }
                if (handlers.onMessage) await handlers.onMessage(data);
                if (data.type === 'done' || data.type === 'error') {
                    if (handlers.onClose) handlers.onClose(data);
                    controller.abort();
                    return;
                }
            }
        }
        if (handlers.onClose) handlers.onClose({ type: 'done' });
    };
    stream().catch((error) => {
        if (error.name === 'AbortError') return;
        if (handlers.onError) handlers.onError(error);
    });
    return { close: () => controller.abort() };
}

export async function bindAgentImageTask(sceneId, data = {}) {
    return request(`/scene/${sceneId}/bind-agent-image-task`, { method: 'POST', body: JSON.stringify(data) });
}

// 模型列表（图片 / 图生视频 / 数字人）
export async function fetchStoryboardModels() {
    return request('/models');
}

export async function fetchMediaPreferences(storyboardId) {
    return request(`/media-preferences?storyboard_id=${encodeURIComponent(storyboardId)}`);
}

export async function updateMediaPreference(storyboardId, mediaType, mode, profile) {
    return request('/media-preferences', {
        method: 'PUT',
        body: JSON.stringify({
            storyboard_id: storyboardId,
            media_type: mediaType,
            mode,
            profile,
        }),
    });
}

// ==================== 导出 ====================
export async function exportFullVideo(storyboardId, options = {}) {
    const body = {
        include_subtitles: options.include_subtitles !== false,
    };
    return request(`/${storyboardId}/export-full-video`, {
        method: 'POST',
        body: JSON.stringify(body),
    });
}
export async function exportAllScenes(storyboardId) {
    return request(`/${storyboardId}/export-all-scenes`, { method: 'POST' });
}
/** 查询异步导出任务（完整视频） */
export async function getExportJob(jobId) {
    return request(`/export-job/${encodeURIComponent(jobId)}`);
}

// ==================== 资产（@提及）/ 算力 ====================
async function fetchPaged(path) {
    const resp = await fetch(path, { headers: authHeaders(false) });
    return normalizePagedList(await readJson(resp));
}

export async function fetchCharacters(worldId) {
    return fetchPaged(`/api/characters?world_id=${encodeURIComponent(worldId)}&page_size=1000`);
}
export async function fetchLocations(worldId) {
    return fetchPaged(`/api/locations?world_id=${encodeURIComponent(worldId)}&page_size=1000`);
}
export async function fetchProps(worldId) {
    return fetchPaged(`/api/props?world_id=${encodeURIComponent(worldId)}&page_size=1000`);
}

export async function fetchComputingPower() {
    // 始终尝试请求；后端支持 token 优先 + X-User-Id 兜底（处理 localStorage 过期 token 场景）
    const resp = await fetch('/api/user/computing_power', { headers: authHeaders(false) });
    if (!resp.ok) return { computing_power: null };
    const data = await resp.json().catch(() => ({}));
    return data.data || data;
}

/** 系统配置（含 is_local，用于限制本地环境扫码充值） */
export async function fetchServerConfig() {
    try {
        const resp = await fetch('/api/system/server-config');
        if (!resp.ok) return {};
        const data = await resp.json().catch(() => ({}));
        return data.data || data || {};
    } catch {
        return {};
    }
}

/** 充值套餐列表 */
export async function fetchRechargePackages() {
    const token = state.authToken || localStorage.getItem('auth_token') || '';
    const resp = await fetch(`/api/recharge/packages?auth_token=${encodeURIComponent(token)}`);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        const err = new Error(data.error || data.message || `HTTP ${resp.status}`);
        err.status = resp.status;
        throw err;
    }
    return Array.isArray(data.packages) ? data.packages : [];
}

/**
 * 创建微信扫码支付订单
 * @param {{ package_id: number|string, payment_ip?: string }} payload
 */
export async function createWechatPayOrder(payload = {}) {
    const token = state.authToken || localStorage.getItem('auth_token') || '';
    const userId = state.userId
        || parseInt(localStorage.getItem('user_id') || '0', 10)
        || 0;
    const resp = await fetch('/api/recharge/wechat-pay', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            user_id: userId,
            package_id: payload.package_id,
            auth_token: token,
            is_wechat_browser: false,
            payment_ip: payload.payment_ip || '0.0.0.0',
        }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        const err = new Error(data.error || data.message || `HTTP ${resp.status}`);
        err.status = resp.status;
        throw err;
    }
    return data;
}

/**
 * 加载对话模型（LLM 列表），参考 script_writer 的 /api/models
 * 第一版仅用于 UI 展示选择，实际对话改图能力待后端接入。
 */
export async function fetchLlmModels() {
    // /api/models 不强制需要 Authorization（参考 script_writer），但尽量带上 X-User-Id / token
    try {
        const resp = await fetch('/api/models', { headers: authHeaders(false) });
        if (!resp.ok) return { success: false, models: [] };
        const data = await resp.json().catch(() => ({}));
        if (data.success && Array.isArray(data.models)) {
            return { success: true, models: data.models };
        }
        return { success: false, models: [] };
    } catch {
        return { success: false, models: [] };
    }
}

export async function fetchVendors() {
    try {
        const resp = await fetch('/api/vendors', { headers: authHeaders(false) });
        if (!resp.ok) return { success: false, vendors: [] };
        const data = await resp.json().catch(() => ({}));
        if (data.success && Array.isArray(data.vendors)) {
            return { success: true, vendors: data.vendors };
        }
        return { success: false, vendors: [] };
    } catch {
        return { success: false, vendors: [] };
    }
}

/**
 * 上传视频生成的补充参考图。复用 marketing_agent 的上传端点，
 * 返回 { success, url, thumbnail_url }。FormData 不可设 Content-Type，由浏览器自动填充 boundary。
 */
export async function uploadReferenceImage(file) {
    const form = new FormData();
    form.append('file', file);
    form.append('session_id', 'storyboard');
    const resp = await fetch('/api/upload-agent-image', {
        method: 'POST',
        headers: authHeaders(false),
        body: form,
    });
    return resp.json().catch(() => ({ success: false, error: '上传响应解析失败' }));
}
