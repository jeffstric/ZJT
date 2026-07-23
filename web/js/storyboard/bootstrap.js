import state, {
    initStateFromUrl,
    loadStoryboardData,
    restoreUiConfig,
    resolveSelectedLlmModel,
    resolveSelectedScriptSplitLlmModel,
    setAssets,
    setModels,
    setLlmVendors,
    ensureVideoImageModeSupported,
    ensureVideoGenerationPrefsSupported,
    syncVideoMediaFromScene,
    getCurrentScene,
    loadThinkingStateFromStorage,
    applyThinkingDefaultsForModel,
    applyGenerateProgressStatus,
    applyMediaPreferenceProfiles,
} from './state.js';
import * as api from './api.js';
import { handleAuthError } from './api.js';
import { bindEvents, loadSceneAgentMessages } from './events.js';
import { renderApp } from './render.js';
import { resumePollingTasks, pollScriptSplitTask, stopScriptSplitTaskPolling } from './polling.js';
import { autoGenerateMissingFirstFrames } from './auto_missing_images.js';
import { resumeAutoMissingVideos } from './auto_missing_videos.js';
import { stopPlayback, updatePlayheadPosition } from './playback.js';

let pageLifecycleBound = false;

/**
 * 加载或创建故事板。
 * 世界内无故事板时返回 { deferred: true }，由比例门禁弹窗确认后再 create。
 */
async function loadStoryboard() {
    if (state.storyboardId) {
        return api.getStoryboard(state.storyboardId);
    }

    if (!state.worldId) {
        throw new Error('缺少 world_id，无法创建故事板');
    }

    const defaults = await api.getStoryboardCreateDefaults(state.worldId);
    state.createDefaults = defaults || {};

    if (defaults?.needs_ratio_confirm) {
        // 关键：不 create、不 finishBootstrap、不开拆分弹窗
        return { deferred: true, needs_ratio_confirm: true };
    }

    return api.createStoryboard({
        world_id: state.worldId,
        episode_number: state.episodeNumber,
        script_id: state.scriptId,
        workflow_id: state.workflowId,
        // 可选显式带上继承比例，便于排查；后端也会再 resolve
        workflow_ratio: defaults?.workflow_ratio || undefined,
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

async function maybePromptGenerateFromScript() {
    // 比例门禁期间绝不弹拆分框
    if (state.ratioGateActive) return;
    if (!state.storyboardId || state.scenes.length > 0) return;
    // 无有效比例时也不拆分（后端会 400，前端提前拦截）
    if (!String(state.workflowRatio || '').trim()) return;

    // 异步化后：先查是否有进行中的拆分任务，有则恢复轮询而不是弹 config 框。
    // 见设计文档 §15「页面刷新后恢复真实进度」。
    try {
        const activeTask = await api.getActiveScriptSplitTask('storyboard', state.storyboardId);
        if (activeTask && activeTask.task_id) {
            state.generateFromScriptTaskId = activeTask.task_id;
            state.isGeneratingFromScript = true;
            state.showGenerateProgressDialog = true;
            state.generateProgressError = '';
            state.generateProgressSteps = [
                { name: '规划分段', status: 'pending', phase: 'planning' },
                { name: '逐段拆分', status: 'pending', phase: 'segment_generation' },
                { name: '合并校验', status: 'pending', phase: 'merging' },
                { name: '发布分镜', status: 'pending', phase: 'publishing' },
            ];
            applyGenerateProgressStatus(activeTask);
            renderApp();
            pollScriptSplitTaskForRecovery(activeTask.task_id);
            return;
        }
    } catch (e) {
        // 查询失败则降级为弹 config 框
    }
    state.showGenerateFromScriptDialog = true;
    state.generateFromScriptError = '';
}

/** 刷新恢复时的轮询：完成后重新加载故事板，失败/暂停则显示提示。 */
function pollScriptSplitTaskForRecovery(taskId) {
    const markRunningFailed = () => {
        const steps = state.generateProgressSteps || [];
        steps.forEach((s) => {
            if (s.status === 'running') s.status = 'failed';
        });
    };
    const updateStepsByStatus = (statusData) => {
        applyGenerateProgressStatus(statusData);
        const steps = state.generateProgressSteps || [];
        const phaseToStep = { planning: 0, segment_generation: 1, replan_segment: 1, merging: 2, global_qc: 2, publishing: 3, done: 4 };
        const targetStep = phaseToStep[statusData.phase] !== undefined ? phaseToStep[statusData.phase] : 0;
        const st = statusData.status;
        const isTerminalFail = st === 'failed' || st === 'cancelled' || st === 'paused' || st === 'waiting_auth';
        steps.forEach((s, i) => {
            if (statusData.status === 'completed') s.status = 'completed';
            else if (i < targetStep) s.status = 'completed';
            else if (i === targetStep) s.status = isTerminalFail ? 'failed' : 'running';
            else s.status = 'pending';
        });
        renderApp();
    };
    pollScriptSplitTask(taskId, {
        onUpdate: updateStepsByStatus,
        onComplete: async () => {
            const steps = state.generateProgressSteps || [];
            steps.forEach(s => s.status = 'completed');
            try {
                const sbResp = await api.getStoryboard(state.storyboardId);
                loadStoryboardData(sbResp);
            } catch (e) { /* ignore */ }
            state.showGenerateProgressDialog = false;
            state.isGeneratingFromScript = false;
            renderApp();
        },
        onPaused: (statusData) => {
            markRunningFailed();
            state.generateProgressError = statusData.message || '任务暂停，请刷新页面后继续';
            state.isGeneratingFromScript = false;
            renderApp();
        },
        onError: (error) => {
            markRunningFailed();
            state.generateProgressError = error.message || '生成分镜失败';
            state.isGeneratingFromScript = false;
            renderApp();
        },
    });
}

function bindPageLifecycleOnce() {
    if (pageLifecycleBound) return;
    pageLifecycleBound = true;
    // 页面隐藏/卸载时停播，避免后台继续出声
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) stopPlayback();
    });
    window.addEventListener('pagehide', () => stopPlayback());
    // 窗口尺寸变化后缩略图宽度可能变，重算播放头
    window.addEventListener('resize', () => {
        updatePlayheadPosition({ followScroll: false });
    });
}

/**
 * 故事板已就绪后的后续初始化（资产/模型/拆分提示/自动任务）。
 * 比例门禁确认 create 成功后也会走这里。
 */
export async function finishBootstrapAfterStoryboardReady(data) {
    if (data?.storyboard) {
        restoreUiConfig(data.storyboard?.config_json || {});
    }

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

    if (state.storyboardId) {
        await api.fetchMediaPreferences(state.storyboardId)
            .then((res) => applyMediaPreferenceProfiles(res?.profiles || {}))
            .catch((error) => console.warn('load storyboard media preferences failed', error));
    }

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

    // 思考模式：与 script_writer 共用 lastThinkingState；DeepSeek 默认开
    loadThinkingStateFromStorage();
    applyThinkingDefaultsForModel(state.selectedLlmModel || state.selectedScriptSplitLlmModel);

    await maybePromptGenerateFromScript();
    // 视频生成模式：模型能力就绪后注入当前分镜首帧到首帧槽
    if (state.chatMode === 'video' || state.chatMode === 'aivideo') {
        ensureVideoImageModeSupported();
        ensureVideoGenerationPrefsSupported();
        syncVideoMediaFromScene(getCurrentScene(), { resetUploads: true });
    }
    // 直连「视频生成」模式：文本框预填当前分镜视频提示词（对口型分镜无文本框，置空）
    if (state.chatMode === 'video') {
        const bootScene = getCurrentScene();
        const bootIsDh = String(bootScene?.videoType || bootScene?.video_type || '').toLowerCase() === 'digital_human';
        state.inputMessage = bootIsDh ? '' : (bootScene?.videoPrompt || '');
    }
    renderApp();
    loadSceneAgentMessages(state.currentSceneId).catch(() => {});
    resumePollingTasks();
    autoGenerateMissingFirstFrames();
    resumeAutoMissingVideos().catch(() => {});
    bindPageLifecycleOnce();
}

/**
 * 比例门禁确认后：带 workflow_ratio 创建故事板并完成初始化。
 * 失败时保持门禁，错误写入 state.ratioConfirmError。
 */
export async function continueCreateWithRatio(ratio) {
    const allowed = new Set(['16:9', '9:16']);
    const workflowRatio = allowed.has(ratio) ? ratio : (state.pendingCreateRatio || '16:9');
    if (!allowed.has(workflowRatio)) {
        state.ratioConfirmError = '请选择视频比例 16:9 或 9:16';
        renderApp();
        return;
    }
    if (!state.worldId) {
        state.ratioConfirmError = '缺少 world_id，无法创建故事板';
        renderApp();
        return;
    }
    if (state.isCreatingStoryboard) return;

    state.isCreatingStoryboard = true;
    state.ratioConfirmError = '';
    state.pendingCreateRatio = workflowRatio;
    renderApp();

    try {
        const data = await api.createStoryboard({
            world_id: state.worldId,
            episode_number: state.episodeNumber,
            script_id: state.scriptId,
            workflow_id: state.workflowId,
            workflow_ratio: workflowRatio,
        });
        // 解除门禁后再加载业务数据
        state.ratioGateActive = false;
        state.showRatioConfirmDialog = false;
        state.isCreatingStoryboard = false;
        state.ratioConfirmError = '';
        loadStoryboardData(data);
        await finishBootstrapAfterStoryboardReady(data);
    } catch (error) {
        state.isCreatingStoryboard = false;
        state.ratioGateActive = true;
        state.showRatioConfirmDialog = true;
        state.ratioConfirmError = error.message || '创建故事板失败，请重试';
        renderApp();
    }
}

async function main() {
    bindEvents();
    initStateFromUrl();

    if (!state.userId) {
        throw new Error('缺少用户信息，请从剧本策划页面重新进入故事板');
    }

    await initI18n();
    state.editionInfo = await api.getEditionInfo().catch(() => ({ mode: 'community', mode_label: '社区版' }));

    const data = await loadStoryboard();

    // 世界内首个故事板：进入比例门禁，禁止 create / 拆分 / 其它业务
    if (data?.deferred && data.needs_ratio_confirm) {
        state.ratioGateActive = true;
        state.showRatioConfirmDialog = true;
        state.pendingCreateRatio = '16:9';
        state.ratioConfirmError = '';
        state.isCreatingStoryboard = false;
        renderApp();
        bindPageLifecycleOnce();
        return;
    }

    loadStoryboardData(data);
    await finishBootstrapAfterStoryboardReady(data);
}

main().catch((error) => {
    if (handleAuthError(error.status, error.response || error.payload || {})) {
        return;
    }
    state.error = error.message || '故事板初始化失败';
    state.ratioGateActive = false;
    state.showRatioConfirmDialog = false;
    renderApp();
});
