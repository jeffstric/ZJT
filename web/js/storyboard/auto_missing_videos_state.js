import state, { getSupportedVideoImageModes } from './state.js';

export const AUTO_VIDEO_BATCH_ACTIVE_STATUSES = new Set(['submitting', 'pending', 'running']);
const AUTO_VIDEO_BATCH_TERMINAL_STATUSES = new Set(['completed', 'partial', 'failed']);
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
    return storyboardId ? `storyboard_auto_missing_videos_${storyboardId}` : '';
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
        planStatus: String(item.plan_status || item.planStatus || item.extra_json?.plan_status || '').toLowerCase(),
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

function isVideoRunning(scene) {
    const status = scene?.taskStatus?.video;
    return status === 0 || status === 1;
}

export function resetAutoVideoBatchState() {
    state.autoVideoBatch = emptyBatchState();
}

export function setAutoVideoBatchSubmitting(submitting) {
    state.autoVideoBatch = {
        ...emptyBatchState(),
        ...state.autoVideoBatch,
        status: submitting ? 'submitting' : 'idle',
        submitting: Boolean(submitting),
        message: submitting ? '正在提交视频任务' : '',
    };
}

export function isAutoVideoBatchActive() {
    return AUTO_VIDEO_BATCH_ACTIVE_STATUSES.has(state.autoVideoBatch?.status);
}

export function isAutoVideoBatchTerminal(status = state.autoVideoBatch?.status) {
    return AUTO_VIDEO_BATCH_TERMINAL_STATUSES.has(status);
}

export function applyVideoBatchStatus(batchStatus = {}) {
    const itemsBySceneId = {};
    const targetItems = [];

    for (const rawItem of batchStatus.items || []) {
        const item = normalizeItem(rawItem);
        if (!item.sceneId) continue;
        itemsBySceneId[item.sceneId] = item;
        if (isTargetItem(item)) targetItems.push(item);

        const scene = state.scenes.find(entry => String(entry.id) === String(item.sceneId));
        if (!scene) continue;
        if (item.resultUrl) {
            const next = String(item.resultUrl).trim();
            if (next && (!scene.videoUrl || scene.videoUrl === next || item.status === 'completed')) {
                scene.videoUrl = next;
            }
        }
        if (item.assetId) scene.selectedVideoId = item.assetId;
    }

    const completedCount = targetItems.filter(item => item.status === 'completed').length;
    const runningCount = targetItems.filter(item => RUNNING_ITEM_STATUSES.has(item.status)).length;
    const pendingCount = targetItems.filter(item => PENDING_ITEM_STATUSES.has(item.status)).length;
    const failedCount = targetItems.filter(item => item.status === 'failed').length;
    const skippedCount = targetItems.filter(item => item.status === 'skipped').length;

    state.autoVideoBatch = {
        batchId: batchStatus.batch_id ?? batchStatus.batchId ?? state.autoVideoBatch?.batchId ?? null,
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
    return state.autoVideoBatch;
}

function isDigitalHumanScene(scene) {
    return String(scene?.videoType || scene?.video_type || '').toLowerCase() === 'digital_human';
}

function sceneHasReadyDialogueAudio(scene) {
    return (scene.dialogues || []).some(d => String(d.audioUrl || d.audio_url || '').trim());
}

/** 可批量提交的缺失视频分镜（图生视频需首帧；对口型需成片配音） */
export function getMissingVideoScenes() {
    return (state.scenes || []).filter(scene => {
        if (scene.videoUrl) return false;
        if (isVideoRunning(scene)) return false;
        const item = state.autoVideoBatch?.itemsBySceneId?.[scene.id];
        if (item && (RUNNING_ITEM_STATUSES.has(item.status) || PENDING_ITEM_STATUSES.has(item.status))) {
            return false;
        }
        if (isDigitalHumanScene(scene)) {
            // MiniMax 对口型：必须先有 TTS 成片音频；形象图由服务端解析（选中首帧）
            return sceneHasReadyDialogueAudio(scene);
        }
        if (!scene.firstFrameUrl) return false;
        return true;
    });
}

export function getDigitalHumanWaitingAudioCount() {
    return (state.scenes || []).filter(scene => {
        if (!isDigitalHumanScene(scene)) return false;
        if (scene.videoUrl) return false;
        return !sceneHasReadyDialogueAudio(scene);
    }).length;
}

export function getAutoVideoCompleteSummary() {
    const totalScenes = (state.scenes || []).length;
    const missingScenes = getMissingVideoScenes();
    const withFirstFrame = (state.scenes || []).filter(s => s.firstFrameUrl).length;
    const waitingAudioCount = getDigitalHumanWaitingAudioCount();
    const batch = state.autoVideoBatch || emptyBatchState();
    return {
        totalScenes,
        withFirstFrame,
        waitingAudioCount,
        missingCount: missingScenes.length,
        missingSceneIds: missingScenes.map(scene => scene.id),
        batch,
        active: AUTO_VIDEO_BATCH_ACTIVE_STATUSES.has(batch.status),
        terminal: AUTO_VIDEO_BATCH_TERMINAL_STATUSES.has(batch.status),
    };
}

export function getAutoVideoCompleteButtonViewModel() {
    const summary = getAutoVideoCompleteSummary();
    const batch = summary.batch;
    if (batch.submitting || batch.status === 'submitting') {
        return {
            icon: 'loading',
            label: '正在提交视频任务',
            locked: true,
            disabled: false,
            busy: true,
            className: 'auto-complete-button auto-video-button is-running',
        };
    }
    if (summary.active) {
        return {
            icon: 'loading',
            label: `视频生成中 ${batch.completedCount}/${batch.totalCount || summary.missingCount}`,
            locked: true,
            disabled: false,
            busy: true,
            className: 'auto-complete-button auto-video-button is-running',
        };
    }
    if (summary.missingCount > 0) {
        const audioHint = summary.waitingAudioCount > 0
            ? `，${summary.waitingAudioCount} 个对口型待配音`
            : '';
        // 根据当前视频图片模式调整文案与提示。
        const isMultiRef = state.videoImageMode === 'multi_reference';
        const modeSupported = !isMultiRef || getSupportedVideoImageModes().includes('multi_reference');
        const labelPrefix = isMultiRef ? '全能参考批量生成视频' : '批量生成视频';
        const modeHint = isMultiRef
            ? (modeSupported
                ? '（全能参考：首帧+角色/场景参考+画风参考）'
                : '（当前模型不支持全能参考，将使用首尾帧模式）')
            : '';
        return {
            icon: 'video',
            label: `${labelPrefix} (${summary.missingCount})`,
            locked: false,
            disabled: false,
            busy: false,
            className: 'auto-complete-button auto-video-button',
            title: `可提交 ${summary.missingCount} 个${audioHint}${modeHint}`,
        };
    }
    if (summary.waitingAudioCount > 0) {
        return {
            icon: 'video',
            label: `对口型待配音 (${summary.waitingAudioCount})`,
            locked: false,
            disabled: true,
            busy: false,
            className: 'auto-complete-button auto-video-button is-complete',
            title: '对口型分镜需先生成对话配音，再批量生成视频',
        };
    }
    if (summary.withFirstFrame === 0) {
        return {
            icon: 'video',
            label: '需先补全画面',
            locked: false,
            disabled: true,
            busy: false,
            className: 'auto-complete-button auto-video-button is-complete',
            title: '请先生成分镜首帧，再批量生成视频',
        };
    }
    return {
        icon: 'success',
        label: '视频已全部生成',
        locked: false,
        disabled: true,
        busy: false,
        className: 'auto-complete-button auto-video-button is-complete',
    };
}

export function readAutoVideoBatchSession(storyboardId = state.storyboardId) {
    const storageKey = getStorageKey(storyboardId);
    if (!storageKey) return null;
    try {
        const raw = sessionStorage.getItem(storageKey);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (parsed?.version !== 1 || Number(parsed.storyboardId) !== Number(storyboardId) || !parsed.batchId) {
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

export function persistAutoVideoBatchSession(batchId, targetSceneIds = [], storyboardId = state.storyboardId) {
    const storageKey = getStorageKey(storyboardId);
    if (!storageKey || !batchId) return;
    try {
        sessionStorage.setItem(storageKey, JSON.stringify({
            version: 1,
            storyboardId,
            batchId,
            targetSceneIds,
            updatedAt: new Date().toISOString(),
        }));
    } catch {}
}

export function clearAutoVideoBatchSession(storyboardId = state.storyboardId) {
    const storageKey = getStorageKey(storyboardId);
    if (!storageKey) return;
    try {
        sessionStorage.removeItem(storageKey);
    } catch {}
}
