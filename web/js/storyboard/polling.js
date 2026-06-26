// 任务状态轮询：生成后轮询 GET /scene/{id}/task-status，更新选中资产 url/状态并刷新画面。
// ai_tools/ai_audio 状态：0=PENDING, 1=PROCESSING, 2=COMPLETED, -1=FAILED（进行中=0或1）。
import state from './state.js';
import * as api from './api.js';
import { renderApp } from './render.js';

const POLL_INTERVAL = 4000;
const pollTimers = {};

function applyTaskStatus(scene, data) {
    if (!scene) return;
    if (data.first_frame && data.first_frame.result_url) scene.firstFrameUrl = data.first_frame.result_url;
    if (data.last_frame && data.last_frame.result_url) scene.lastFrameUrl = data.last_frame.result_url;
    if (data.video && data.video.result_url) scene.videoUrl = data.video.result_url;
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

export function resumePollingTasks() {
    for (const scene of state.scenes) {
        pollSceneTaskStatus(scene.id);
    }
}
