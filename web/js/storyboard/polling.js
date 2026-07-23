// 任务状态轮询：生成后轮询 GET /scene/{id}/task-status，更新选中资产 url/状态并刷新画面。
// ai_tools/ai_audio 状态：0=PENDING, 1=PROCESSING, 2=COMPLETED, -1=FAILED（进行中=0或1）。
// 渲染策略：某分镜产出/状态变化时，只局部更新该分镜相关的 UI（缩略图、主预览、候选、单条对话行），
//          不再全量 renderApp()——避免对话框焦点被销毁、DevTools 选中节点失效。
import state, { refreshSceneFirstFrameSlot } from './state.js';
import * as api from './api.js';
import { formatDuration } from './adapters.js';
import {
    captureAssetSelection,
    isPollAssetSelectionCurrent,
} from './candidate_selection_state.js';
import {
    updateAutoCompleteHeader,
    updateSceneThumb,
    updateCurrentSceneDetail,
    updateDigitalHumanAudioHint,
    updateDialogueRow,
    updateTimelineProgress,
} from './render.js';

const POLL_INTERVAL = 4000;
const pollTimers = {};
const batchPollTimers = {};

function isRenderableCandidateUrl(url) {
    if (url == null) return false;
    const value = String(url).trim();
    if (!value) return false;
    // 逗号拼接多图是输入参考图，不是单张结果图
    if (value.includes(',')) return false;
    return true;
}

/**
 * 宫格整图（quality 模式未拆分前）路径特征。
 * 拆分后的单格首帧在 first_frame/ 下；若用宫格整图覆盖单格 URL，缩略图会在「整图/单格」间闪烁。
 */
function isStoryboardGridCompositeUrl(url) {
    const value = String(url || '').toLowerCase();
    if (!value) return false;
    if (value.includes('/storyboard/temp/')) return true;
    if (value.includes('/grid/') || value.includes('grid_result') || value.includes('grid-image')) return true;
    return false;
}

/** 合并首帧/视频 URL：禁止用宫格整图覆盖已有单格结果 */
function preferSceneMediaUrl(current, next) {
    if (!isRenderableCandidateUrl(next)) return current || '';
    const nextUrl = String(next).trim();
    const curUrl = current ? String(current).trim() : '';
    if (!curUrl) return nextUrl;
    if (curUrl === nextUrl) return curUrl;
    if (isStoryboardGridCompositeUrl(nextUrl) && !isStoryboardGridCompositeUrl(curUrl)) {
        return curUrl;
    }
    return nextUrl;
}

function upsertSceneCandidateFromTask(sceneId, assetType, taskInfo) {
    if (!taskInfo || !taskInfo.asset_id) return;
    if (!state.sceneCandidates) state.sceneCandidates = {};
    if (!state.sceneCandidates[sceneId]) state.sceneCandidates[sceneId] = { images: [], videos: [] };
    const listKey = assetType === 'video' ? 'videos' : 'images';
    const list = state.sceneCandidates[sceneId][listKey] || [];
    const assetId = taskInfo.asset_id;
    let candidate = list.find(item => String(item.id) === String(assetId));
    if (!candidate) {
        candidate = { id: assetId, url: '', status: null, selected: true };
        list.unshift(candidate);
    }
    const nextUrl = taskInfo.result_url;
    if (isRenderableCandidateUrl(nextUrl)) {
        candidate.url = String(nextUrl).trim();
    } else if (nextUrl === '' || nextUrl == null) {
        // 任务尚未产出：保留已有合法 URL；非法多图 URL 清空为 loading
        if (!isRenderableCandidateUrl(candidate.url)) candidate.url = '';
    } else if (!isRenderableCandidateUrl(candidate.url)) {
        candidate.url = '';
    }
    if (taskInfo.status !== undefined && taskInfo.status !== null) {
        candidate.status = taskInfo.status;
    }
    list.forEach(item => {
        item.selected = String(item.id) === String(assetId);
    });
    state.sceneCandidates[sceneId][listKey] = list;
}

// 记录 dialogue 的 audio 签名快照，用于 applyTaskStatus 后对比哪些行的 audio 变化、需单独刷新。
function snapshotDialogueAudio(scene) {
    const map = {};
    (scene?.dialogues || []).forEach(d => {
        map[d.id] = `${d.audioUrl || ''}|${d.audioStatus ?? ''}`;
    });
    return map;
}

function applyTaskStatus(scene, data, requestSelection) {
    if (!scene) return;
    const firstFrameCurrent = isPollAssetSelectionCurrent(scene, 'first_frame', requestSelection);
    const videoCurrent = isPollAssetSelectionCurrent(scene, 'video', requestSelection);
    if (firstFrameCurrent && data.first_frame && data.first_frame.asset_id) scene.selectedFirstFrameId = data.first_frame.asset_id;
    if (firstFrameCurrent && data.first_frame && isRenderableCandidateUrl(data.first_frame.result_url)) {
        scene.firstFrameUrl = preferSceneMediaUrl(scene.firstFrameUrl, data.first_frame.result_url);
    }
    if (data.last_frame && isRenderableCandidateUrl(data.last_frame.result_url)) {
        scene.lastFrameUrl = preferSceneMediaUrl(scene.lastFrameUrl, data.last_frame.result_url);
    }
    if (videoCurrent && data.video && data.video.asset_id) scene.selectedVideoId = data.video.asset_id;
    if (videoCurrent && data.video && isRenderableCandidateUrl(data.video.result_url)) {
        scene.videoUrl = preferSceneMediaUrl(scene.videoUrl, data.video.result_url);
    }
    if (firstFrameCurrent) upsertSceneCandidateFromTask(scene.id, 'first_frame', data.first_frame);
    if (videoCurrent) upsertSceneCandidateFromTask(scene.id, 'video', data.video);
    // 视频助手模式下，首帧生成完成后同步到输入区首帧槽
    if ((state.chatMode === 'video' || state.chatMode === 'aivideo') && state.currentSceneId === scene.id) {
        refreshSceneFirstFrameSlot(scene);
    }
    (data.dialogues || []).forEach(d => {
        const dialogue = (scene.dialogues || []).find(item => item.id === d.dialogue_id);
        if (dialogue) {
            if (d.audio_url) dialogue.audioUrl = d.audio_url;
            dialogue.audioStatus = d.status;
        }
    });
    scene.taskStatus = {
        first_frame: firstFrameCurrent && data.first_frame ? data.first_frame.status : scene.taskStatus?.first_frame ?? null,
        last_frame: data.last_frame ? data.last_frame.status : null,
        video: videoCurrent && data.video ? data.video.status : scene.taskStatus?.video ?? null,
    };
    // 后端在分镜下所有配音完成后，会把 scene.duration 同步为音频求和（浮点秒），
    // 此处即时同步到本地 state，并标记 _durationChanged 供 applySceneUpdate 刷新进度行。
    if (data.scene_duration != null) {
        const newDuration = Number(data.scene_duration);
        if (Number.isFinite(newDuration) && Math.abs(newDuration - Number(scene.duration)) > 1e-9) {
            scene.duration = newDuration;
            scene.durationLabel = formatDuration(newDuration);
            scene._durationChanged = true;
        }
    }
}

function hasRunning(data) {
    const vals = [
        data.first_frame ? data.first_frame.status : null,
        data.last_frame ? data.last_frame.status : null,
        data.video ? data.video.status : null,
        ...(data.dialogues || []).map(d => d.status),
    ];
    return vals.some(v => v === 0 || v === 1);
}

// 局部更新某分镜变化波及的 UI 区域，替代全量 renderApp。
function applySceneUpdate(scene, changedDialogueIds) {
    if (!scene) return;
    // 1. 时间线/grid 中该分镜的缩略图（durationLabel 变化会随此重渲）
    updateSceneThumb(scene);
    updateAutoCompleteHeader();
    // 2 & 3. 当前选中分镜的主预览 + 右侧候选网格（预览 caption 含 durationLabel）
    updateCurrentSceneDetail(scene);
    updateDigitalHumanAudioHint(scene);
    // 4. audio 发生变化的单条对话行（按行粒度，避免触碰正在编辑的其他行）
    (changedDialogueIds || []).forEach(did => updateDialogueRow(scene, did));
    // 5. 若本分镜 duration 被音频同步刷新过，进度行总时长需单独更新（其余局部更新不触碰该 span）
    if (scene._durationChanged) {
        updateTimelineProgress();
        scene._durationChanged = false;
    }
}

export function pollSceneTaskStatus(sceneId) {
    if (pollTimers[sceneId]) return;
    const poll = async () => {
        try {
            const sceneAtRequest = state.scenes.find(item => item.id === sceneId);
            const requestSelection = captureAssetSelection(sceneAtRequest);
            const data = await api.getSceneTaskStatus(sceneId);
            const scene = state.scenes.find(item => item.id === sceneId);
            if (!scene) {
                delete pollTimers[sceneId];
                return;
            }
            // apply 前记录 dialogue audio 快照，apply 后对比出变化的行（仅这些行需局部刷新）
            const beforeAudio = snapshotDialogueAudio(scene);
            applyTaskStatus(scene, data, requestSelection);
            const changedDialogueIds = (scene.dialogues || [])
                .filter(d => beforeAudio[d.id] !== `${d.audioUrl || ''}|${d.audioStatus ?? ''}`)
                .map(d => d.id);
            // 局部更新该分镜相关 UI，不再全量重建
            applySceneUpdate(scene, changedDialogueIds);
            if (hasRunning(data)) {
                pollTimers[sceneId] = setTimeout(poll, POLL_INTERVAL);
            } else {
                delete pollTimers[sceneId];
            }
        } catch (e) {
            pollTimers[sceneId] = setTimeout(poll, POLL_INTERVAL * 2);
        }
    };
    poll();
}

export function pollImageBatchStatus(batchId, callbacks = {}) {
    if (!batchId || batchPollTimers[batchId]) return;
    const poll = async () => {
        try {
            const data = await api.getStoryboardImageBatchStatus(batchId);
            if (callbacks.onUpdate) callbacks.onUpdate(data);
            for (const item of data.items || []) {
                if (item.scene_id && (item.status === 'running' || item.status === 'completed')) {
                    pollSceneTaskStatus(item.scene_id);
                }
            }
            if (data.status === 'pending' || data.status === 'running') {
                batchPollTimers[batchId] = setTimeout(poll, POLL_INTERVAL);
            } else {
                delete batchPollTimers[batchId];
                if (callbacks.onTerminal) callbacks.onTerminal(data);
            }
        } catch (e) {
            if (callbacks.onRecoverableError) callbacks.onRecoverableError(e);
            batchPollTimers[batchId] = setTimeout(poll, POLL_INTERVAL * 2);
        }
    };
    poll();
}

export function resumePollingTasks() {
    for (const scene of state.scenes) {
        pollSceneTaskStatus(scene.id);
    }
}

// 剧本分段拆分任务轮询：见 docs/script/script_parser_incremental_split_design.md §13.3 §15。
// 复用 batch 轮询的去重 + 退避模式，驱动 state.generateProgressSteps 反映真实进度。
const generatePollTimers = {};
const SPLIT_TERMINAL_STATUSES = ['completed', 'failed', 'cancelled'];
const SPLIT_INTERACTIVE_STATUSES = ['paused', 'waiting_auth'];

export function pollScriptSplitTask(taskId, callbacks = {}) {
    if (!taskId || generatePollTimers[taskId]) return;
    let errorBackoff = 1;
    const poll = async () => {
        try {
            const data = await api.getScriptSplitTaskStatus(taskId);
            errorBackoff = 1;
            if (callbacks.onUpdate) callbacks.onUpdate(data);
            if (SPLIT_TERMINAL_STATUSES.indexOf(data.status) >= 0) {
                delete generatePollTimers[taskId];
                if (data.status === 'completed') {
                    try {
                        const result = await api.getScriptSplitTaskResult(taskId);
                        if (callbacks.onComplete) callbacks.onComplete(result, data);
                    } catch (e) {
                        if (callbacks.onError) callbacks.onError(e);
                    }
                } else {
                    if (callbacks.onError) callbacks.onError(new Error(data.message || `任务${data.status}`));
                }
                return;
            }
            if (SPLIT_INTERACTIVE_STATUSES.indexOf(data.status) >= 0) {
                delete generatePollTimers[taskId];
                if (callbacks.onPaused) callbacks.onPaused(data);
                return;
            }
            const interval = data.poll_after_ms || POLL_INTERVAL;
            generatePollTimers[taskId] = setTimeout(poll, interval);
        } catch (e) {
            errorBackoff = Math.min(errorBackoff * 2, 5);
            if (callbacks.onRecoverableError) callbacks.onRecoverableError(e);
            generatePollTimers[taskId] = setTimeout(poll, POLL_INTERVAL * errorBackoff);
        }
    };
    poll();
}

export function stopScriptSplitTaskPolling(taskId) {
    if (generatePollTimers[taskId]) {
        clearTimeout(generatePollTimers[taskId]);
        delete generatePollTimers[taskId];
    }
}
