import state from './state.js';
import * as api from './api.js';
import {
    renderApp,
    updateAutoCompleteHeader,
    updateCurrentSceneDetail,
    updateSceneThumb,
} from './render.js';
import { pollImageBatchStatus, pollSceneTaskStatus } from './polling.js';
import {
    applyImageBatchStatus,
    clearAutoImageBatchSession,
    getMissingFirstFrameScenes,
    isAutoImageBatchActive,
    isAutoImageBatchTerminal,
    persistAutoImageBatchSession,
    readAutoImageBatchSession,
    resetAutoImageBatchState,
    setAutoImageBatchSubmitting,
} from './auto_missing_images_state.js';

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
        renderApp();
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
            limit: missing.length,
            sequence_mode: state.autoImageSequenceMode,
        });
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
        setAutoImageBatchSubmitting(false);
        clearAutoImageBatchSession();
        updateAutoCompleteHeader();
        if (manual) throw error;
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
