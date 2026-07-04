// 任务状态轮询：生成后轮询 GET /scene/{id}/task-status，更新选中资产 url/状态并刷新画面。
// ai_tools/ai_audio 状态：0=PENDING, 1=PROCESSING, 2=COMPLETED, -1=FAILED（进行中=0或1）。
import state from './state.js';
import * as api from './api.js';
import { renderApp } from './render.js';

const POLL_INTERVAL = 4000;
const pollTimers = {};
const batchPollTimers = {};

function upsertSceneCandidateFromTask(sceneId, assetType, taskInfo) {
    if (!taskInfo || !taskInfo.asset_id) return;
    if (!state.sceneCandidates) state.sceneCandidates = {};
    if (!state.sceneCandidates[sceneId]) state.sceneCandidates[sceneId] = { images: [], videos: [] };
    const listKey = assetType === 'video' ? 'videos' : 'images';
    const list = state.sceneCandidates[sceneId][listKey] || [];
    const assetId = taskInfo.asset_id;
    let candidate = list.find(item => String(item.id) === String(assetId));
    if (!candidate) {
        candidate = { id: assetId, url: '', selected: true };
        list.unshift(candidate);
    }
    candidate.url = taskInfo.result_url || candidate.url || '';
    list.forEach(item => {
        item.selected = String(item.id) === String(assetId);
    });
    state.sceneCandidates[sceneId][listKey] = list;
}

function applyTaskStatus(scene, data) {
    if (!scene) return;
    if (data.first_frame && data.first_frame.asset_id) scene.selectedFirstFrameId = data.first_frame.asset_id;
    if (data.first_frame && data.first_frame.result_url) scene.firstFrameUrl = data.first_frame.result_url;
    if (data.last_frame && data.last_frame.result_url) scene.lastFrameUrl = data.last_frame.result_url;
    if (data.video && data.video.asset_id) scene.selectedVideoId = data.video.asset_id;
    if (data.video && data.video.result_url) scene.videoUrl = data.video.result_url;
    upsertSceneCandidateFromTask(scene.id, 'first_frame', data.first_frame);
    upsertSceneCandidateFromTask(scene.id, 'video', data.video);
    (data.dialogues || []).forEach(d => {
        const dialogue = (scene.dialogues || []).find(item => item.id === d.dialogue_id);
        if (dialogue) {
            if (d.audio_url) dialogue.audioUrl = d.audio_url;
            dialogue.audioStatus = d.status;
        }
    });
    scene.taskStatus = {
        first_frame: data.first_frame ? data.first_frame.status : null,
        last_frame: data.last_frame ? data.last_frame.status : null,
        video: data.video ? data.video.status : null,
    };
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

export function pollSceneTaskStatus(sceneId) {
    if (pollTimers[sceneId]) return;
    const poll = async () => {
        try {
            const data = await api.getSceneTaskStatus(sceneId);
            const scene = state.scenes.find(item => item.id === sceneId);
            if (!scene) {
                delete pollTimers[sceneId];
                return;
            }
            applyTaskStatus(scene, data);
            renderApp();
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

export function pollImageBatchStatus(batchId) {
    if (!batchId || batchPollTimers[batchId]) return;
    const poll = async () => {
        try {
            const data = await api.getStoryboardImageBatchStatus(batchId);
            for (const item of data.items || []) {
                if (item.scene_id && (item.status === 'running' || item.status === 'completed')) {
                    pollSceneTaskStatus(item.scene_id);
                }
            }
            if (data.status === 'pending' || data.status === 'running') {
                batchPollTimers[batchId] = setTimeout(poll, POLL_INTERVAL);
            } else {
                delete batchPollTimers[batchId];
            }
        } catch (e) {
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
