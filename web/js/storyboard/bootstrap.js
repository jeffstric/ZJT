import state, {
    initStateFromUrl,
    loadStoryboardData,
    restoreUiConfig,
    setAssets,
    setModels,
} from './state.js';
import * as api from './api.js';
import { bindEvents } from './events.js';
import { renderApp } from './render.js';
import { resumePollingTasks } from './polling.js';

async function loadStoryboard() {
    if (state.storyboardId) {
        return api.getStoryboard(state.storyboardId);
    }

    if (!state.worldId) {
        throw new Error('缺少 world_id，无法创建故事板');
    }

    return api.createStoryboard({
        world_id: state.worldId,
        episode_number: state.episodeNumber,
        script_id: state.scriptId,
        workflow_id: state.workflowId,
    });
}

async function loadAssets() {
    if (!state.worldId) return;
    const [characters, locations, props] = await Promise.all([
        api.fetchCharacters(state.worldId),
        api.fetchLocations(state.worldId),
        api.fetchProps(state.worldId),
    ]);
    setAssets({ characters, locations, props });
}

async function initI18n() {
    if (window.ZJTi18n && typeof window.ZJTi18n.init === 'function') {
        await window.ZJTi18n.init(['common', 'storyboard']).catch(() => {});
    }
}

function maybePromptGenerateFromScript() {
    if (!state.storyboardId || state.scenes.length > 0) return;
    state.showGenerateFromScriptDialog = true;
    state.generateFromScriptError = '';
}

async function main() {
    bindEvents();
    initStateFromUrl();

    if (!state.userId) {
        throw new Error('缺少用户信息，请从剧本策划页面重新进入故事板');
    }

    await initI18n();

    const data = await loadStoryboard();
    loadStoryboardData(data);
    restoreUiConfig(data.storyboard?.config_json || {});

    await Promise.all([
        loadAssets().catch(() => {}),
        api.fetchComputingPower().then((power) => {
            state.computingPower = power.computing_power ?? power.balance ?? null;
        }).catch(() => {}),
        api.fetchStoryboardModels().then(setModels).catch(() => {}),
    ]);

    maybePromptGenerateFromScript();
    renderApp();
    resumePollingTasks();
}

main().catch((error) => {
    state.error = error.message || '故事板初始化失败';
    renderApp();
});
