import state from './state.js';
import * as api from './api.js';
import { renderApp } from './render.js';
import { pollImageBatchStatus, pollSceneTaskStatus } from './polling.js';

function isFirstFrameRunning(scene) {
    const status = scene?.taskStatus?.first_frame;
    return status === 0 || status === 1;
}

function scenesMissingFirstFrame() {
    return state.scenes.filter(scene => !scene.firstFrameUrl && !isFirstFrameRunning(scene));
}

export async function autoGenerateMissingFirstFrames() {
    if (!state.storyboardId || !state.authToken || !state.scenes.length) return;
    const missing = scenesMissingFirstFrame();
    if (!missing.length) return;

    const storageKey = `storyboard_auto_missing_images_${state.storyboardId}`;
    try {
        if (sessionStorage.getItem(storageKey)) return;
        sessionStorage.setItem(storageKey, '1');
    } catch {}

    try {
        const result = await api.autoGenerateMissingImages(state.storyboardId, {
            asset_type: 'first_frame',
            mode: 'auto',
            ratio: state.workflowRatio,
            task_type: state.selectedImageTaskId,
            limit: missing.length,
            sequence_mode: state.autoImageSequenceMode,
        });
        for (const item of result.items || []) {
            if (item.status === 'submitted' || item.status === 'already_running' || item.status === 'running') {
                pollSceneTaskStatus(item.scene_id);
            }
        }
        if (result.batch_id) {
            pollImageBatchStatus(result.batch_id);
        }
        api.fetchComputingPower().then((power) => {
            state.computingPower = power.computing_power ?? power.balance ?? state.computingPower;
            renderApp();
        }).catch(() => {});
    } catch (error) {
        try {
            sessionStorage.removeItem(storageKey);
        } catch {}
        console.warn('auto generate missing storyboard images failed', error);
    }
}
