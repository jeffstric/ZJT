import state, {
    initStateFromUrl,
    loadStoryboardData,
    restoreUiConfig,
    resolveSelectedLlmModel,
    resolveSelectedScriptSplitLlmModel,
    setAssets,
    setModels,
    setLlmVendors,
} from './state.js';
import * as api from './api.js';
import { bindEvents, loadSceneAgentMessages } from './events.js';
import { renderApp } from './render.js';
import { resumePollingTasks } from './polling.js';
import { autoGenerateMissingFirstFrames } from './auto_missing_images.js';

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
    // 可选：扫描 DOM 中的 data-i18n 属性（与其他页面保持一致）
    if (window.ZJTi18nDOM && typeof window.ZJTi18nDOM.scanDOM === 'function') {
        window.ZJTi18nDOM.scanDOM(document);
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

    // LLM 模型恢复：优先 config_json（通过 restoreUiConfig），否则回退 localStorage
    // 使用专用 key 避免与 script_writer 冲突
    if (!state.selectedLlmModel) {
        try {
            const raw = localStorage.getItem('storyboard_lastSelectedLlmModel')
                || localStorage.getItem('lastSelectedLlmModel');
            if (raw) {
                state.selectedLlmModel = JSON.parse(raw);
            }
        } catch {}
    }
    if (!state.selectedScriptSplitLlmModel) {
        try {
            const raw = localStorage.getItem('storyboard_lastScriptSplitLlmModel');
            if (raw) {
                state.selectedScriptSplitLlmModel = JSON.parse(raw);
            }
        } catch {}
    }

    await Promise.all([
        loadAssets().catch(() => {}),
        api.fetchComputingPower().then((power) => {
            state.computingPower = power.computing_power ?? power.balance ?? null;
        }).catch(() => {}),
        api.fetchStoryboardModels().then(setModels).catch(() => {}),
        // 加载对话模型（LLM），第一版仅 UI 选择用
        api.fetchLlmModels().then((res) => {
            if (res && res.success) {
                setModels({ llm_models: res.models });
            }
        }).catch(() => {}),
        // 加载 LLM 供应商，用于对话模型分组显示（复用 script_writer 逻辑）
        api.fetchVendors().then((res) => {
            if (res && res.success) {
                setLlmVendors(res.vendors);
            }
        }).catch(() => {}),
    ]);

    // 设置对话模型（LLM）默认值，如果没有选中
    // 参考 script_writer 和 video_workflow 的默认选项逻辑：deepseek-v4-flash > qwen3.5-plus (zjt) > 其他 qwen > 第一个
    if (!state.selectedLlmModel && state.llmModels && state.llmModels.length > 0) {
        const models = state.llmModels;
        let defaultM = models.find(m => {
            const name = (m.model || m.name || '').toLowerCase();
            const vendor = (m.vendor_name || '').toLowerCase();
            return name.includes('deepseek-v4-flash') && vendor.includes('deepseek');
        });
        if (!defaultM) {
            defaultM = models.find(m => {
                const name = (m.model || m.name || '').toLowerCase();
                const vendor = (m.vendor_name || '').toLowerCase();
                return name.includes('qwen3.5-plus') && (vendor.includes('zjt') || vendor.includes('zjt_api'));
            });
        }
        if (!defaultM) {
            defaultM = models.find(m => (m.model || m.name || '').toLowerCase().includes('qwen3.5-plus'));
        }
        if (!defaultM) {
            defaultM = models[0];
        }
        if (defaultM) {
            const val = defaultM.model || defaultM.name || defaultM.id || '';
            const modelId = defaultM.model_id || defaultM.id || '';
            state.selectedLlmModel = modelId ? {
                model: val,
                model_id: modelId,
                vendor_id: defaultM.vendor_id || null,
            } : val;
            resolveSelectedLlmModel();
            try {
                localStorage.setItem('storyboard_lastSelectedLlmModel', JSON.stringify(state.selectedLlmModel));
            } catch (e) {}
        }
    }
    if (!state.selectedScriptSplitLlmModel && state.selectedLlmModel) {
        state.selectedScriptSplitLlmModel = typeof state.selectedLlmModel === 'object'
            ? { ...state.selectedLlmModel }
            : state.selectedLlmModel;
    }
    if (state.selectedScriptSplitLlmModel) {
        resolveSelectedScriptSplitLlmModel();
        try {
            localStorage.setItem('storyboard_lastScriptSplitLlmModel', JSON.stringify(state.selectedScriptSplitLlmModel));
        } catch (e) {}
    }

    maybePromptGenerateFromScript();
    renderApp();
    loadSceneAgentMessages(state.currentSceneId).catch(() => {});
    resumePollingTasks();
    autoGenerateMissingFirstFrames();
}

main().catch((error) => {
    state.error = error.message || '故事板初始化失败';
    renderApp();
});
