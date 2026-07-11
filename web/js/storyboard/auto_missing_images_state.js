import state from './state.js';

export const AUTO_IMAGE_BATCH_ACTIVE_STATUSES = new Set(['submitting', 'pending', 'running']);
const AUTO_IMAGE_BATCH_TERMINAL_STATUSES = new Set(['completed', 'partial', 'failed']);
const TARGET_PLAN_STATUSES = new Set(['pending', 'already_running']);
const RUNNING_ITEM_STATUSES = new Set(['submitted', 'running']);
const PENDING_ITEM_STATUSES = new Set(['pending']);

function emptyBatchState() {
    return {
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
    };
}

function getStorageKey(storyboardId = state.storyboardId) {
    return storyboardId ? `storyboard_auto_missing_images_${storyboardId}` : '';
}

function numericId(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function normalizeItem(item = {}) {
    const sceneId = numericId(item.scene_id ?? item.sceneId);
    return {
        id: item.id,
        sceneId,
        status: String(item.status || '').toLowerCase(),
        planStatus: String(item.plan_status || item.planStatus || '').toLowerCase(),
        assetId: item.asset_id ?? item.assetId ?? null,
        resultUrl: item.result_url || item.resultUrl || '',
        errorCode: item.error_code || item.errorCode || '',
        errorMessage: item.error_message || item.errorMessage || '',
    };
}

function isTargetItem(item) {
    if (TARGET_PLAN_STATUSES.has(item.planStatus)) return true;
    return !item.planStatus && item.status && item.status !== 'skipped';
}

function isFirstFrameRunning(scene) {
    const status = scene?.taskStatus?.first_frame;
    return status === 0 || status === 1;
}

export function resetAutoImageBatchState() {
    state.autoImageBatch = emptyBatchState();
}

export function setAutoImageBatchSubmitting(submitting) {
    state.autoImageBatch = {
        ...emptyBatchState(),
        ...state.autoImageBatch,
        status: submitting ? 'submitting' : 'idle',
        submitting: Boolean(submitting),
        message: submitting ? '正在提交补全任务' : '',
    };
}

export function isAutoImageBatchActive() {
    return AUTO_IMAGE_BATCH_ACTIVE_STATUSES.has(state.autoImageBatch?.status);
}

export function isAutoImageBatchTerminal(status = state.autoImageBatch?.status) {
    return AUTO_IMAGE_BATCH_TERMINAL_STATUSES.has(status);
}

export function applyImageBatchStatus(batchStatus = {}) {
    const itemsBySceneId = {};
    const targetItems = [];

    for (const rawItem of batchStatus.items || []) {
        const item = normalizeItem(rawItem);
        if (!item.sceneId) continue;
        itemsBySceneId[item.sceneId] = item;
        if (isTargetItem(item)) targetItems.push(item);

        const scene = state.scenes.find(entry => String(entry.id) === String(item.sceneId));
        if (!scene) continue;
        if (item.resultUrl) scene.firstFrameUrl = item.resultUrl;
        if (item.assetId) scene.selectedFirstFrameId = item.assetId;
    }

    const completedCount = targetItems.filter(item => item.status === 'completed').length;
    const runningCount = targetItems.filter(item => RUNNING_ITEM_STATUSES.has(item.status)).length;
    const pendingCount = targetItems.filter(item => PENDING_ITEM_STATUSES.has(item.status)).length;
    const failedCount = targetItems.filter(item => item.status === 'failed').length;
    const skippedCount = targetItems.filter(item => item.status === 'skipped').length;

    state.autoImageBatch = {
        batchId: batchStatus.batch_id ?? batchStatus.batchId ?? state.autoImageBatch?.batchId ?? null,
        status: String(batchStatus.status || 'running').toLowerCase(),
        totalCount: targetItems.length,
        completedCount,
        runningCount,
        pendingCount,
        failedCount,
        skippedCount,
        itemsBySceneId,
        message: batchStatus.message || '',
        submitting: false,
    };
    return state.autoImageBatch;
}

export function getFirstFrameDisplayStatus(scene) {
    if (scene?.firstFrameUrl) return 'ready';
    const item = state.autoImageBatch?.itemsBySceneId?.[scene?.id];
    if (item) {
        if (RUNNING_ITEM_STATUSES.has(item.status)) return 'running';
        if (PENDING_ITEM_STATUSES.has(item.status)) return 'pending';
        if (item.status === 'failed') return 'failed';
    }
    if (isFirstFrameRunning(scene)) return 'running';
    return 'missing';
}

export function getMissingFirstFrameScenes() {
    return (state.scenes || []).filter(scene => {
        if (scene.firstFrameUrl) return false;
        const displayStatus = getFirstFrameDisplayStatus(scene);
        return displayStatus !== 'pending' && displayStatus !== 'running';
    });
}

export function getAutoCompleteSummary() {
    const totalScenes = (state.scenes || []).length;
    const missingScenes = getMissingFirstFrameScenes();
    const batch = state.autoImageBatch || emptyBatchState();
    return {
        totalScenes,
        missingCount: missingScenes.length,
        missingSceneIds: missingScenes.map(scene => scene.id),
        batch,
        active: AUTO_IMAGE_BATCH_ACTIVE_STATUSES.has(batch.status),
        terminal: AUTO_IMAGE_BATCH_TERMINAL_STATUSES.has(batch.status),
    };
}

export function getAutoCompleteButtonViewModel() {
    const summary = getAutoCompleteSummary();
    const batch = summary.batch;
    if (batch.submitting || batch.status === 'submitting') {
        return {
            icon: 'loading',
            label: '正在提交补全任务',
            locked: true,
            disabled: false,
            busy: true,
            className: 'auto-complete-button is-running',
        };
    }
    if (summary.active) {
        return {
            icon: 'loading',
            label: `补全中 ${batch.completedCount}/${batch.totalCount || summary.missingCount}`,
            locked: true,
            disabled: false,
            busy: true,
            className: 'auto-complete-button is-running',
        };
    }
    if (summary.missingCount > 0) {
        return {
            icon: 'wand',
            label: '自动补全未生成分镜',
            locked: false,
            disabled: false,
            busy: false,
            className: 'auto-complete-button',
        };
    }
    return {
        icon: 'success',
        label: '分镜已全部生成',
        locked: false,
        disabled: true,
        busy: false,
        className: 'auto-complete-button is-complete',
    };
}

export function getFirstFrameStatusLabel(status) {
    return {
        missing: '待生成',
        pending: '排队中',
        running: '生成中',
        failed: '生成失败',
        ready: '',
    }[status] || '待生成';
}

export function readAutoImageBatchSession(storyboardId = state.storyboardId) {
    const storageKey = getStorageKey(storyboardId);
    if (!storageKey) return null;
    try {
        const raw = sessionStorage.getItem(storageKey);
        if (!raw) return null;
        if (raw === '1') {
            sessionStorage.removeItem(storageKey);
            return null;
        }
        const parsed = JSON.parse(raw);
        if (parsed?.version !== 2 || Number(parsed.storyboardId) !== Number(storyboardId) || !parsed.batchId) {
            sessionStorage.removeItem(storageKey);
            return null;
        }
        return parsed;
    } catch {
        try {
            sessionStorage.removeItem(storageKey);
        } catch {}
        return null;
    }
}

export function persistAutoImageBatchSession(batchId, targetSceneIds = [], storyboardId = state.storyboardId) {
    const storageKey = getStorageKey(storyboardId);
    if (!storageKey || !batchId) return;
    try {
        sessionStorage.setItem(storageKey, JSON.stringify({
            version: 2,
            storyboardId,
            batchId,
            targetSceneIds,
            updatedAt: new Date().toISOString(),
        }));
    } catch {}
}

export function clearAutoImageBatchSession(storyboardId = state.storyboardId) {
    const storageKey = getStorageKey(storyboardId);
    if (!storageKey) return;
    try {
        sessionStorage.removeItem(storageKey);
    } catch {}
}
