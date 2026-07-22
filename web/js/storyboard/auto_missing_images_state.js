import state from './state.js';

export const AUTO_IMAGE_BATCH_ACTIVE_STATUSES = new Set(['submitting', 'pending', 'running']);
const AUTO_IMAGE_BATCH_TERMINAL_STATUSES = new Set(['completed', 'partial', 'failed']);
const TARGET_PLAN_STATUSES = new Set(['pending', 'regenerate_pending', 'already_running']);
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
        existingPolicy: 'skip',
        itemsBySceneId: {},
        message: '',
        submitting: false,
    };
}

function emptyLocationGateState() {
    return {
        status: 'idle',
        errorCode: '',
        message: '',
        blockers: [],
        affectedSceneIds: [],
        retryAfterMs: 0,
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
    const extra = item.extra_json || item.extraJson || {};
    return {
        id: item.id,
        sceneId,
        status: String(item.status || '').toLowerCase(),
        planStatus: String(item.plan_status || item.planStatus || extra.plan_status || '').toLowerCase(),
        existingPolicy: String(item.existing_policy || item.existingPolicy || extra.existing_policy || 'skip').toLowerCase(),
        baseAssetId: item.base_asset_id ?? item.baseAssetId ?? extra.base_asset_id ?? null,
        waiting: String(item.waiting || extra.waiting || '').toLowerCase(),
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
    state.autoImageLocationGate = emptyLocationGateState();
}

export function clearLocationReferencePreflight() {
    state.autoImageLocationGate = emptyLocationGateState();
}

export function applyLocationReferencePreflight(payload = {}) {
    const errorCode = String(payload.error_code || payload.errorCode || payload.code || '');
    const blockers = Array.isArray(payload.blockers) ? payload.blockers : [];
    const sources = [
        ...blockers,
        ...(Array.isArray(payload.failures) ? payload.failures : []),
        ...(Array.isArray(payload.running_tasks) ? payload.running_tasks : []),
    ];
    const affected = new Set(
        (payload.affected_scene_ids || payload.affectedSceneIds || []).map(numericId).filter(Boolean),
    );
    for (const source of sources) {
        for (const sceneId of source?.affected_scene_ids || source?.affectedSceneIds || []) {
            const normalized = numericId(sceneId);
            if (normalized) affected.add(normalized);
        }
    }
    const status = errorCode === 'waiting_location_references'
        ? 'waiting'
        : (errorCode === 'location_reference_generation_failed' ? 'failed' : 'blocked');
    state.autoImageLocationGate = {
        status,
        errorCode,
        message: payload.message || payload.error || '场景参考图尚未就绪',
        blockers,
        affectedSceneIds: [...affected],
        retryAfterMs: Number(payload.retry_after_ms || payload.retryAfterMs || 0),
    };
    return state.autoImageLocationGate;
}

export function setAutoImageBatchSubmitting(submitting, existingPolicy = 'skip') {
    state.autoImageBatch = {
        ...emptyBatchState(),
        ...state.autoImageBatch,
        status: submitting ? 'submitting' : 'idle',
        submitting: Boolean(submitting),
        existingPolicy,
        message: submitting
            ? (existingPolicy === 'regenerate' ? '正在提交重新生成任务' : '正在提交补全任务')
            : '',
    };
}

export function isAutoImageBatchActive() {
    return AUTO_IMAGE_BATCH_ACTIVE_STATUSES.has(state.autoImageBatch?.status);
}

export function isAutoImageBatchTerminal(status = state.autoImageBatch?.status) {
    return AUTO_IMAGE_BATCH_TERMINAL_STATUSES.has(status);
}

/**
 * 是否允许 batch 轮询结果写回场景首帧。
 * 用户涂色/手动选候选后 selectedFirstFrameId 会指向新资产；batch item 仍挂着生成时的旧 asset，
 * 若无条件覆盖会出现「涂色后隔一会又变回原图」。
 */
export function shouldApplyBatchFirstFrameToScene(scene, item = {}) {
    if (!scene) return false;
    const curSel = scene.selectedFirstFrameId;
    const hasSelection = !(curSel === null || curSel === undefined || curSel === '');
    const batchAssetId = item.assetId;
    const hasBatchAsset = !(batchAssetId === null || batchAssetId === undefined || batchAssetId === '');
    const isRegeneration = item.planStatus === 'regenerate_pending';

    // 重生成成功前保留旧选中；仅当用户仍停留在发起任务时的旧资产上，才允许新结果接管。
    if (isRegeneration && item.baseAssetId != null && String(curSel) === String(item.baseAssetId)) {
        return true;
    }

    // 尚无选中：允许用 batch 结果补全缺失首帧
    if (!hasSelection) return true;
    // batch 还没落到 asset：仅当场景仍无图时可写 URL（不改 selected）
    if (!hasBatchAsset) return !String(scene.firstFrameUrl || '').trim();
    // 仅当当前选中仍是 batch 对应资产时才同步（URL 更新 / 宫格拆分回写）
    return String(curSel) === String(batchAssetId);
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

        // 用户已选其它候选（含涂色上传）时，禁止 batch 用旧 asset 覆盖
        if (!shouldApplyBatchFirstFrameToScene(scene, item)) {
            continue;
        }

        // 仅 completed/ready 写 URL；禁止用宫格整图覆盖已有单格首帧（避免缩略图/主预览闪烁）
        if (item.resultUrl) {
            const next = String(item.resultUrl).trim();
            const cur = String(scene.firstFrameUrl || '').trim();
            const nextIsGrid = /\/storyboard\/temp\//i.test(next) || /grid/i.test(next);
            const curIsGrid = /\/storyboard\/temp\//i.test(cur) || /grid/i.test(cur);
            const statusOk = !item.status || item.status === 'completed' || item.status === 'already_ready'
                || item.status === 'running' || item.status === 'submitted';
            if (statusOk && next && !(nextIsGrid && cur && !curIsGrid)) {
                scene.firstFrameUrl = next;
            }
        }
        const isRegeneration = item.planStatus === 'regenerate_pending';
        if (item.assetId && (!isRegeneration || item.status === 'completed')) {
            scene.selectedFirstFrameId = item.assetId;
        }
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
        existingPolicy: String(
            batchStatus.existing_policy
            || batchStatus.existingPolicy
            || state.autoImageBatch?.existingPolicy
            || 'skip',
        ).toLowerCase(),
        itemsBySceneId,
        message: batchStatus.message || '',
        submitting: false,
    };
    return state.autoImageBatch;
}

export function getFirstFrameDisplayStatus(scene) {
    const item = state.autoImageBatch?.itemsBySceneId?.[scene?.id];
    if (item?.planStatus === 'regenerate_pending') {
        if (RUNNING_ITEM_STATUSES.has(item.status)) return 'regenerating';
        if (PENDING_ITEM_STATUSES.has(item.status)) return 'regenerate_pending';
        if (item.status === 'failed') return 'regenerate_failed';
    }
    if (scene?.firstFrameUrl) return 'ready';
    const gate = state.autoImageLocationGate || emptyLocationGateState();
    const affected = (gate.affectedSceneIds || []).some(
        sceneId => String(sceneId) === String(scene?.id),
    );
    if (affected) {
        return gate.status === 'waiting' ? 'waiting_location' : 'blocked_location';
    }
    if (item) {
        if (RUNNING_ITEM_STATUSES.has(item.status)) return 'running';
        if (item.status === 'failed') return 'failed';
        if (PENDING_ITEM_STATUSES.has(item.status)) {
            if (item.waiting === 'location_grid_reference') return 'waiting_location';
            if (item.waiting === 'previous_group_first_frame') return 'waiting_prev';
            return 'pending';
        }
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
        const regenerating = batch.existingPolicy === 'regenerate';
        return {
            icon: 'loading',
            label: regenerating ? '正在提交重新生成任务' : '正在提交补全任务',
            locked: true,
            disabled: false,
            busy: true,
            className: 'auto-complete-button is-running',
        };
    }
    if (summary.active) {
        const regenerating = batch.existingPolicy === 'regenerate';
        return {
            icon: 'loading',
            label: `${regenerating ? '重新生成中' : '补全中'} ${batch.completedCount}/${batch.totalCount || summary.missingCount}`,
            locked: true,
            disabled: false,
            busy: true,
            className: 'auto-complete-button is-running',
        };
    }
    const gate = state.autoImageLocationGate || emptyLocationGateState();
    if (gate.status === 'waiting') {
        return {
            icon: 'loading',
            label: '等待场景参考图',
            locked: true,
            disabled: false,
            busy: true,
            className: 'auto-complete-button is-running',
        };
    }
    if (gate.status === 'blocked' || gate.status === 'failed') {
        return {
            icon: 'wand',
            label: '重新检查并生成',
            locked: false,
            disabled: false,
            busy: false,
            className: 'auto-complete-button is-location-blocked',
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
        waiting_location: '等场景参考',
        blocked_location: '依赖场景缺图',
        waiting_prev: '等前置分镜',
        running: '生成中',
        regenerating: '重新生成中',
        regenerate_pending: '重新生成排队中',
        regenerate_failed: '重新生成失败',
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
