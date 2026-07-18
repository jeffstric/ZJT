import state from './state.js';
import * as api from './api.js';
import {
    patchHeaderPower,
    updateAutoCompleteHeader,
    updateCurrentSceneDetail,
    updateSceneThumb,
} from './render.js';
import { pollImageBatchStatus, pollSceneTaskStatus } from './polling.js';
import {
    applyLocationReferencePreflight,
    applyImageBatchStatus,
    clearLocationReferencePreflight,
    clearAutoImageBatchSession,
    getMissingFirstFrameScenes,
    isAutoImageBatchActive,
    isAutoImageBatchTerminal,
    persistAutoImageBatchSession,
    readAutoImageBatchSession,
    resetAutoImageBatchState,
    setAutoImageBatchSubmitting,
} from './auto_missing_images_state.js';

const LOCATION_REFERENCE_GATE_CODES = new Set([
    'waiting_location_references',
    'quality_parent_reference_missing',
    'location_reference_generation_failed',
]);
let locationReferenceRetryTimer = null;

function cancelLocationReferenceRetry() {
    if (locationReferenceRetryTimer !== null) {
        clearTimeout(locationReferenceRetryTimer);
        locationReferenceRetryTimer = null;
    }
}

function scheduleLocationReferenceRetry(delay = 3000) {
    cancelLocationReferenceRetry();
    locationReferenceRetryTimer = setTimeout(() => {
        locationReferenceRetryTimer = null;
        submitMissingFirstFrameBatch({ manual: false });
    }, Math.max(1000, Number(delay || 3000)));
}

function refreshLocationGateScenes(payload = {}) {
    const ids = new Set(payload.affected_scene_ids || []);
    for (const collection of [payload.blockers, payload.failures, payload.running_tasks]) {
        for (const item of collection || []) {
            for (const sceneId of item.affected_scene_ids || []) ids.add(sceneId);
        }
    }
    const targets = ids.size
        ? state.scenes.filter(scene => [...ids].some(id => String(id) === String(scene.id)))
        : state.scenes;
    targets.forEach(scene => updateSceneThumb(scene));
    if (targets.some(scene => String(scene.id) === String(state.currentSceneId))) {
        const current = targets.find(scene => String(scene.id) === String(state.currentSceneId));
        if (current) updateCurrentSceneDetail(current);
    }
    updateAutoCompleteHeader();
}

function handleLocationReferencePreflight(payload = {}) {
    setAutoImageBatchSubmitting(false);
    clearAutoImageBatchSession();
    applyLocationReferencePreflight(payload);
    refreshLocationGateScenes(payload);
    cancelLocationReferenceRetry();
    if ((payload.error_code || payload.code) === 'waiting_location_references') {
        scheduleLocationReferenceRetry(payload.retry_after_ms);
    }
}

function refreshBatchAffectedScenes(batchStatus) {
    const sceneIds = new Set((batchStatus?.items || []).map(item => item.scene_id).filter(Boolean));
    sceneIds.forEach(sceneId => {
        const scene = state.scenes.find(item => String(item.id) === String(sceneId));
        if (!scene) return;
        updateSceneThumb(scene);
        if (String(state.currentSceneId) === String(scene.id)) {
            updateCurrentSceneDetail(scene);
        }
    });
    updateAutoCompleteHeader();
}

function handleBatchUpdate(batchStatus) {
    applyImageBatchStatus(batchStatus);
    refreshBatchAffectedScenes(batchStatus);
    const batchId = batchStatus?.batch_id || batchStatus?.batchId;
    if (batchId && !isAutoImageBatchTerminal(batchStatus.status)) {
        persistAutoImageBatchSession(batchId, state.autoImageBatch?.itemsBySceneId
            ? Object.keys(state.autoImageBatch.itemsBySceneId)
            : []);
    }
}

function handleBatchTerminal(batchStatus) {
    handleBatchUpdate(batchStatus);
    clearAutoImageBatchSession();
    if (isAutoImageBatchTerminal(batchStatus?.status)) {
        state.autoImageBatch.status = batchStatus.status;
    }
}

function pollBatch(batchId) {
    pollImageBatchStatus(batchId, {
        onUpdate: handleBatchUpdate,
        onTerminal: handleBatchTerminal,
        onRecoverableError: updateAutoCompleteHeader,
    });
}

async function refreshComputingPower() {
    try {
        const power = await api.fetchComputingPower();
        state.computingPower = power.computing_power ?? power.balance ?? state.computingPower;
        // 禁止 renderApp：批量生成时若用户正在预览，全量重建会打断视频
        patchHeaderPower();
    } catch {}
}

async function recoverBatch(batchId) {
    if (!batchId) return false;
    try {
        const status = await api.getStoryboardImageBatchStatus(batchId);
        applyImageBatchStatus(status);
        refreshBatchAffectedScenes(status);
        if (status.status === 'pending' || status.status === 'running') {
            persistAutoImageBatchSession(batchId, Object.keys(state.autoImageBatch.itemsBySceneId || {}));
            pollBatch(batchId);
            return true;
        }
        clearAutoImageBatchSession();
        return true;
    } catch (error) {
        if (error.status === 404 || error.code === 'not_found') {
            clearAutoImageBatchSession();
            resetAutoImageBatchState();
            updateAutoCompleteHeader();
            return false;
        }
        throw error;
    }
}

async function submitMissingFirstFrameBatch({ manual = false } = {}) {
    if (!state.storyboardId || !state.authToken || !state.scenes.length) return null;
    if (isAutoImageBatchActive()) return null;

    const missing = getMissingFirstFrameScenes();
    if (!missing.length) {
        resetAutoImageBatchState();
        updateAutoCompleteHeader();
        return null;
    }

    setAutoImageBatchSubmitting(true);
    updateAutoCompleteHeader();

    try {
        const result = await api.autoGenerateMissingImages(state.storyboardId, {
            asset_type: 'first_frame',
            mode: 'auto',
            ratio: state.workflowRatio,
            task_type: state.selectedImageTaskId,
            sequence_mode: state.autoImageSequenceMode,
        });
        if (LOCATION_REFERENCE_GATE_CODES.has(result?.error_code || result?.code)) {
            handleLocationReferencePreflight(result);
            return result;
        }
        cancelLocationReferenceRetry();
        clearLocationReferencePreflight();
        applyImageBatchStatus(result);
        refreshBatchAffectedScenes(result);
        for (const item of result.items || []) {
            if (item.status === 'submitted' || item.status === 'already_running' || item.status === 'running') {
                pollSceneTaskStatus(item.scene_id);
            }
        }
        if (result.batch_id) {
            persistAutoImageBatchSession(result.batch_id, missing.map(scene => scene.id));
            pollBatch(result.batch_id);
        }
        refreshComputingPower();
        return result;
    } catch (error) {
        if (error.status === 409 && error.code === 'active_batch_exists' && error.payload?.active_batch_id) {
            const activeBatchId = error.payload.active_batch_id;
            setAutoImageBatchSubmitting(false);
            state.autoImageBatch.status = 'running';
            state.autoImageBatch.batchId = activeBatchId;
            updateAutoCompleteHeader();
            await recoverBatch(activeBatchId);
            return null;
        }
        if (LOCATION_REFERENCE_GATE_CODES.has(error.code)) {
            handleLocationReferencePreflight(error.payload || error.response || {
                error_code: error.code,
                error: error.message,
            });
            return null;
        }
        setAutoImageBatchSubmitting(false);
        clearAutoImageBatchSession();
        updateAutoCompleteHeader();
        if (manual) throw error;
        // 场景宫格仍在生成时，单次网络/服务异常不应永久终止自动推进。
        if (state.autoImageLocationGate?.status === 'waiting') {
            scheduleLocationReferenceRetry(state.autoImageLocationGate.retryAfterMs);
        }
        console.warn('auto generate missing storyboard images failed', error);
        return null;
    }
}

/**
 * 清除「自动生成缺失首帧」的一次性去重标志位。
 *
 * 场景：用户删除所有分镜后重新拆分，storyboardId 不变，但场景集合已重建，
 * 应当允许新一轮自动生成重新触发一次。因此拆分成功后需主动调用本函数。
 */
export function resetAutoMissingImagesFlag(storyboardId = state.storyboardId) {
    if (!storyboardId) return;
    clearAutoImageBatchSession(storyboardId);
    cancelLocationReferenceRetry();
    resetAutoImageBatchState();
    updateAutoCompleteHeader();
}

export async function autoGenerateMissingFirstFrames() {
    if (!state.storyboardId || !state.authToken || !state.scenes.length) return;
    const recoverable = readAutoImageBatchSession(state.storyboardId);
    if (recoverable?.batchId) {
        const recovered = await recoverBatch(recoverable.batchId);
        if (recovered) return;
    }
    await submitMissingFirstFrameBatch({ manual: false });
}

export async function autoCompleteMissingFirstFrames() {
    return submitMissingFirstFrameBatch({ manual: true });
}
