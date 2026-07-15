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
    applyVideoBatchStatus,
    clearAutoVideoBatchSession,
    getMissingVideoScenes,
    isAutoVideoBatchActive,
    isAutoVideoBatchTerminal,
    persistAutoVideoBatchSession,
    readAutoVideoBatchSession,
    resetAutoVideoBatchState,
    setAutoVideoBatchSubmitting,
} from './auto_missing_videos_state.js';

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
    applyVideoBatchStatus(batchStatus);
    refreshBatchAffectedScenes(batchStatus);
    const batchId = batchStatus?.batch_id || batchStatus?.batchId;
    if (batchId && !isAutoVideoBatchTerminal(batchStatus.status)) {
        persistAutoVideoBatchSession(batchId, state.autoVideoBatch?.itemsBySceneId
            ? Object.keys(state.autoVideoBatch.itemsBySceneId)
            : []);
    }
}

function handleBatchTerminal(batchStatus) {
    handleBatchUpdate(batchStatus);
    clearAutoVideoBatchSession();
    if (isAutoVideoBatchTerminal(batchStatus?.status)) {
        state.autoVideoBatch.status = batchStatus.status;
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
        applyVideoBatchStatus(status);
        refreshBatchAffectedScenes(status);
        if (status.status === 'pending' || status.status === 'running') {
            persistAutoVideoBatchSession(batchId, Object.keys(state.autoVideoBatch.itemsBySceneId || {}));
            pollBatch(batchId);
            return true;
        }
        clearAutoVideoBatchSession();
        return true;
    } catch (error) {
        if (error.status === 404 || error.code === 'not_found') {
            clearAutoVideoBatchSession();
            resetAutoVideoBatchState();
            updateAutoCompleteHeader();
            return false;
        }
        throw error;
    }
}

async function submitMissingVideoBatch({ manual = false } = {}) {
    if (!state.storyboardId || !state.authToken || !state.scenes.length) return null;
    if (isAutoVideoBatchActive()) return null;

    const missing = getMissingVideoScenes();
    if (!missing.length) {
        resetAutoVideoBatchState();
        updateAutoCompleteHeader();
        if (manual) {
            const noFrame = !(state.scenes || []).some(s => s.firstFrameUrl);
            throw new Error(noFrame ? '请先补全分镜首帧，再批量生成视频' : '当前没有待生成视频的分镜');
        }
        return null;
    }

    setAutoVideoBatchSubmitting(true);
    updateAutoCompleteHeader();

    try {
        const result = await api.autoGenerateMissingVideos(state.storyboardId, {
            limit: missing.length,
            ratio: state.workflowRatio,
            task_type: state.selectedVideoTaskId,
            sequence_mode: 'speed',
            continue_on_error: true,
            image_mode: state.videoImageMode || 'first_last_frame',
        });
        applyVideoBatchStatus(result);
        refreshBatchAffectedScenes(result);
        for (const item of result.items || []) {
            if (item.status === 'submitted' || item.status === 'already_running' || item.status === 'running') {
                pollSceneTaskStatus(item.scene_id);
            }
        }
        if (result.batch_id) {
            persistAutoVideoBatchSession(result.batch_id, missing.map(scene => scene.id));
            pollBatch(result.batch_id);
        }
        refreshComputingPower();
        return result;
    } catch (error) {
        if (error.status === 409 && error.code === 'active_batch_exists' && error.payload?.active_batch_id) {
            const activeBatchId = error.payload.active_batch_id;
            setAutoVideoBatchSubmitting(false);
            state.autoVideoBatch.status = 'running';
            state.autoVideoBatch.batchId = activeBatchId;
            updateAutoCompleteHeader();
            await recoverBatch(activeBatchId);
            return null;
        }
        setAutoVideoBatchSubmitting(false);
        clearAutoVideoBatchSession();
        updateAutoCompleteHeader();
        if (manual) throw error;
        console.warn('auto generate missing storyboard videos failed', error);
        return null;
    }
}

export function resetAutoMissingVideosFlag(storyboardId = state.storyboardId) {
    if (!storyboardId) return;
    clearAutoVideoBatchSession(storyboardId);
    resetAutoVideoBatchState();
    updateAutoCompleteHeader();
}

/** 页面加载时恢复进行中的视频批次 */
export async function resumeAutoMissingVideos() {
    if (!state.storyboardId || !state.authToken) return;
    const recoverable = readAutoVideoBatchSession(state.storyboardId);
    if (recoverable?.batchId) {
        await recoverBatch(recoverable.batchId);
    }
}

export async function autoCompleteMissingVideos() {
    return submitMissingVideoBatch({ manual: true });
}
