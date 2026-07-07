import state, {
    addSceneToState,
    addDialogueToState,
    getCurrentScene,
    removeSceneFromState,
    removeDialogueFromState,
    replaceSceneInState,
    resolveSelectedLlmModel,
    resolveSelectedScriptSplitLlmModel,
    serializeUiConfig,
    loadStoryboardData,
} from './state.js';
import * as api from './api.js';
import { sceneToPromptPayload, sceneToUpdatePayload } from './adapters.js';
import { renderApp, renderPromptWithInlineRoles, getThumbnailUrl } from './render.js';
import { pollSceneTaskStatus } from './polling.js';
import { autoGenerateMissingFirstFrames, resetAutoMissingImagesFlag } from './auto_missing_images.js';

let generateProgressTimer = null;
let isTimelineHovered = false;

function notify(message) {
    window.alert(message);
}

function handleAutoDialogueAudioPolling(response) {
    const summary = response && response.audio_auto_generate;
    if (!summary || !summary.enabled) return;
    const sceneIds = new Set();
    (summary.submitted || []).forEach(item => {
        const sceneId = parseInt(item.scene_id, 10);
        if (Number.isFinite(sceneId)) sceneIds.add(sceneId);
    });
    sceneIds.forEach(sceneId => {
        pollSceneTaskStatus(sceneId);
    });
    const submitted = Number(summary.submitted_count || 0);
    const skipped = Number(summary.skipped_count || 0);
    if (submitted > 0 || skipped > 0) {
        notify(`已提交 ${submitted} 条配音任务，${skipped} 条跳过`);
    }
}

function rerender() {
    renderApp();
}

function buildQuery(base, params) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value !== null && value !== undefined && value !== '') query.set(key, value);
    });
    const qs = query.toString();
    return qs ? `${base}?${qs}` : base;
}

function getSceneAssetCandidateUrl(asset) {
    if (!asset) return '';
    return asset.result_url
        || asset.url
        || asset.image_url
        || asset.video_url
        || asset.ai_tool?.result_url
        || asset.tool?.result_url
        || '';
}

function mapSceneAssetCandidates(response, assetType) {
    const selectedId = response?.selected?.[assetType];
    const assets = response?.assets || response?.data || [];
    return assets.map(asset => ({
        id: asset.id,
        url: getSceneAssetCandidateUrl(asset),
        selected: selectedId !== null && selectedId !== undefined && String(asset.id) === String(selectedId),
    }));
}

async function loadSceneCandidates(sceneId) {
    const [imageRes, videoRes] = await Promise.all([
        api.listSceneAssets(sceneId, 'first_frame').catch(() => null),
        api.listSceneAssets(sceneId, 'video').catch(() => null),
    ]);
    if (!state.sceneCandidates) state.sceneCandidates = {};
    state.sceneCandidates[sceneId] = {
        images: mapSceneAssetCandidates(imageRes, 'first_frame'),
        videos: mapSceneAssetCandidates(videoRes, 'video'),
    };
}

function applySelectedCandidateToScene(scene, assetType, assetId, url) {
    if (!scene) return;
    if (assetType === 'first_frame') {
        scene.selectedFirstFrameId = assetId;
        if (url) scene.firstFrameUrl = url;
    } else if (assetType === 'video') {
        scene.selectedVideoId = assetId;
        if (url) scene.videoUrl = url;
    }
}

async function selectSceneCandidate(target) {
    const current = getCurrentScene();
    if (!current) return;
    const candidateType = target.dataset.candidateType;
    const assetType = candidateType === 'video' ? 'video' : 'first_frame';
    const assetId = parseInt(target.dataset.candidateId, 10);
    if (!Number.isFinite(assetId)) return;

    await api.selectSceneAsset(current.id, assetType, assetId);

    const listKey = assetType === 'video' ? 'videos' : 'images';
    const candidates = state.sceneCandidates?.[current.id]?.[listKey] || [];
    const selected = candidates.find(item => String(item.id) === String(assetId));
    applySelectedCandidateToScene(current, assetType, assetId, selected?.url || '');
    candidates.forEach(item => {
        item.selected = String(item.id) === String(assetId);
    });
    pollSceneTaskStatus(current.id);
    rerender();
}

async function persistUiConfig() {
    if (!state.storyboardId) return;
    await api.updateStoryboard(state.storyboardId, { config_json: serializeUiConfig() }).catch(() => {});
}

function patchDialogueInState(dialogueId, patch) {
    for (const scene of state.scenes) {
        const dialogue = scene.dialogues.find(item => item.id === dialogueId);
        if (dialogue) {
            Object.assign(dialogue, patch);
            return true;
        }
    }
    return false;
}

function pushAgentMessage(role, content, meta = {}) {
    if (!content && !meta.status) return;
    state.agentMessages = [
        ...state.agentMessages.slice(-39),
        {
            role,
            content: content || '',
            status: meta.status || '',
            createdAt: new Date().toISOString(),
        },
    ];
}

export async function loadSceneAgentMessages(sceneId, skipRerender = false) {
    if (!sceneId) {
        state.agentMessages = [];
        return;
    }
    try {
        const response = await api.fetchSceneAgentChatHistory(sceneId);
        if (state.currentSceneId !== sceneId) return;
        const rows = Array.isArray(response.messages) ? response.messages : [];
        state.agentMessages = rows.map(item => ({
            role: item.role || 'assistant',
            content: typeof item.content === 'string'
                ? item.content
                : (item.content?.content || item.content?.message || ''),
            status: item.status || '',
            createdAt: item.timestamp || item.create_at || new Date().toISOString(),
        }));
        // 点击切换分镜时由调用方统一渲染一次，避免与候选加载竞态导致多次 rerender 闪烁
        if (!skipRerender) rerender();
    } catch (error) {
        console.warn('Failed to load storyboard agent chat history', error);
    }
}

function getAgentContent(data) {
    if (!data) return '';
    if (typeof data.content === 'string') return data.content;
    if (data.message) return data.message;
    if (data.error) return data.error;
    if (data.result && typeof data.result === 'string') return data.result;
    if (data.result && data.result.result) return data.result.result;
    return '';
}

async function bindSubmittedAgentTasks(sceneId, projectIds, assetType = 'first_frame') {
    const ids = Array.isArray(projectIds) ? projectIds : [projectIds].filter(Boolean);
    if (!ids.length) return;
    const response = await api.bindAgentImageTask(sceneId, { project_ids: ids, asset_type: assetType });
    const scene = state.scenes.find(item => item.id === sceneId);
    if (response?.selected_asset_id) {
        applySelectedCandidateToScene(scene, assetType, response.selected_asset_id, '');
    }
    await loadSceneCandidates(sceneId).catch(() => {});
    pollSceneTaskStatus(sceneId);
}

async function handleReferenceFileChange(input) {
    const files = Array.from(input.files || []);
    if (!files.length) return;
    for (const file of files) {
        const tempId = `ref_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
        state.referenceImages = [...(state.referenceImages || []), {
            id: tempId, url: null, thumbnailUrl: null, name: file.name, uploading: true,
        }];
        rerender();
        try {
            const res = await api.uploadReferenceImage(file);
            const item = (state.referenceImages || []).find(r => r.id === tempId);
            if (res && res.success && res.url) {
                if (item) {
                    item.url = res.url;
                    item.thumbnailUrl = res.thumbnail_url || res.url;
                    item.uploading = false;
                }
            } else {
                state.referenceImages = (state.referenceImages || []).filter(r => r.id !== tempId);
                notify((res && res.error) || '参考图上传失败');
            }
        } catch (err) {
            state.referenceImages = (state.referenceImages || []).filter(r => r.id !== tempId);
            notify('参考图上传失败: ' + (err.message || err));
        }
        rerender();
    }
    // 重置以允许重复选择同一文件
    input.value = '';
}

async function sendStoryboardAgentMessage(current) {
    const message = (state.inputMessage || '').trim();
    if (!message) {
        notify('请输入要调整的内容');
        return;
    }
    const llm = resolveSelectedLlmModel();
    const model = typeof llm === 'string' ? llm : (llm?.model || llm?.name || '');
    const modelId = typeof llm === 'object' ? (llm.model_id || llm.id) : null;
    const vendorId = typeof llm === 'object' ? llm.vendor_id : null;
    if (!model || !modelId) {
        notify('请先在模型配置中选择对话模型');
        state.showModelConfigModal = true;
        state.currentConfigTab = 'dialogue';
        rerender();
        return;
    }

    state.isAgentRunning = true;
    pushAgentMessage('user', message);
    state.inputMessage = '';
    rerender();

    try {
        // 视频生成模式下，附上用户上传的补充参考图 URL（首帧图由后端 scene_context 自动提供）
        const referenceImageUrls = state.chatMode === 'video'
            ? (state.referenceImages || []).filter(r => r.url && !r.uploading).map(r => r.url)
            : [];
        const response = await api.startSceneAgentChat(current.id, {
            message,
            model,
            model_id: modelId,
            vendor_id: vendorId,
            generation_target: state.chatMode === 'video' ? 'video' : 'image',
            image_task_id: state.selectedImageTaskId,
            video_task_id: state.selectedVideoTaskId,
            language: localStorage.getItem('zjt_locale') || 'zh-CN',
            ...(referenceImageUrls.length ? { reference_image_urls: referenceImageUrls } : {}),
        });
        state.activeAgentTaskId = response.task_id;
        pushAgentMessage('status', state.chatMode === 'video' ? '分镜视频智能体已开始处理' : '分镜图片智能体已开始处理');
        rerender();

        api.streamStoryboardAgentTask(response.task_id, {
            onMessage: async (data) => {
                if (data.type === 'connected' || data.type === 'heartbeat') return;
                if (data.type === 'status') {
                    pushAgentMessage('status', getAgentContent(data) || data.status || '任务状态已更新');
                } else if (data.type === 'tool_call') {
                    const names = Array.isArray(data.tool_names) ? data.tool_names.join(', ') : '';
                    pushAgentMessage('status', names ? `正在调用工具：${names}` : '正在调用生成工具');
                } else if (data.type === 'image_task_submitted') {
                    const ids = data.project_ids || data.projectIds || [];
                    pushAgentMessage('status', getAgentContent(data) || '图片生成任务已提交，正在绑定到当前分镜');
                    try {
                        await bindSubmittedAgentTasks(current.id, ids, 'first_frame');
                        pushAgentMessage('status', '已绑定图片生成任务，右侧资产状态会自动刷新');
                    } catch (error) {
                        pushAgentMessage('assistant', `图片任务绑定失败：${error.message || error}`);
                    }
                } else if (data.type === 'video_task_submitted') {
                    const ids = data.project_ids || data.projectIds || [];
                    pushAgentMessage('status', getAgentContent(data) || '视频生成任务已提交，正在绑定到当前分镜');
                    try {
                        await bindSubmittedAgentTasks(current.id, ids, 'video');
                        pushAgentMessage('status', '已绑定视频生成任务，右侧资产状态会自动刷新');
                    } catch (error) {
                        pushAgentMessage('assistant', `视频任务绑定失败：${error.message || error}`);
                    }
                } else if (data.type === 'message') {
                    pushAgentMessage(data.role || 'assistant', getAgentContent(data));
                } else if (data.type === 'error') {
                    pushAgentMessage('assistant', getAgentContent(data) || (state.chatMode === 'video' ? '分镜视频智能体执行失败' : '分镜图片智能体执行失败'));
                    state.isAgentRunning = false;
                    state.activeAgentTaskId = null;
                } else if (data.type === 'done') {
                    const content = getAgentContent(data);
                    if (content) pushAgentMessage('assistant', content);
                    state.isAgentRunning = false;
                    state.activeAgentTaskId = null;
                    pollSceneTaskStatus(current.id);
                    loadSceneAgentMessages(current.id).catch(() => {});
                }
                rerender();
            },
            onError: () => {
                pushAgentMessage('assistant', '任务连接中断，请稍后查看生成结果或重新发送');
                state.isAgentRunning = false;
                state.activeAgentTaskId = null;
                rerender();
            },
            onClose: () => {
                state.isAgentRunning = false;
                state.activeAgentTaskId = null;
                rerender();
            },
        });
    } catch (error) {
        pushAgentMessage('assistant', `启动智能体失败：${error.message || error}`);
        state.isAgentRunning = false;
        state.activeAgentTaskId = null;
        rerender();
    }
}

async function handleAction(action, target) {
    const current = getCurrentScene();

    if (action === 'generate-from-script-cancel') {
        if (state.isGeneratingFromScript) return;
        state.showGenerateFromScriptDialog = false;
        state.generateFromScriptError = '';
        rerender();
        return;
    }

    if (action === 'close-generate-progress') {
        if (generateProgressTimer) {
            clearInterval(generateProgressTimer);
            generateProgressTimer = null;
        }
        state.showGenerateProgressDialog = false;
        state.generateProgressError = '';
        rerender();
        return;
    }

    if (action === 'retry-generate-progress') {
        if (generateProgressTimer) {
            clearInterval(generateProgressTimer);
            generateProgressTimer = null;
        }
        state.showGenerateProgressDialog = false;
        state.generateProgressError = '';
        state.showGenerateFromScriptDialog = true;
        rerender();
        return;
    }

    if (action === 'set-auto-image-sequence-mode') {
        const mode = target.dataset.autoImageSequenceMode;
        if (!['speed', 'balanced', 'quality'].includes(mode) || state.isGeneratingFromScript) return;
        state.autoImageSequenceMode = mode;
        rerender();
        if (state.storyboardId) {
            persistUiConfig().catch(() => {});
        }
        return;
    }

    if (action === 'generate-from-script-confirm') {
        if (state.isGeneratingFromScript || !state.storyboardId) return;
        const splitModel = resolveSelectedScriptSplitLlmModel();
        if (!splitModel || !splitModel.model || !splitModel.model_id) {
            state.generateFromScriptError = '请先选择拆分剧本模型';
            rerender();
            return;
        }
        state.isGeneratingFromScript = true;
        state.generateFromScriptError = '';
        state.showGenerateFromScriptDialog = false;
        state.showGenerateProgressDialog = true;
        state.generateProgressError = '';
        const progressSteps = [
            { name: '构思场景背景', status: 'pending' },
            { name: '设计画面构图', status: 'pending' },
            { name: '选择适合景别', status: 'pending' },
            { name: '调整色彩与灯光', status: 'pending' },
            { name: '最终细节确认', status: 'pending' },
        ];
        state.generateProgressSteps = progressSteps;
        state.generateProgressStepIndex = 0;
        progressSteps[0].status = 'running';
        rerender();

        const STEP_DELAY = 5000;
        if (generateProgressTimer) {
            clearInterval(generateProgressTimer);
            generateProgressTimer = null;
        }
        const advanceStep = () => {
            const idx = state.generateProgressStepIndex;
            if (idx >= 0 && idx < progressSteps.length) {
                progressSteps[idx].status = 'completed';
            }
            const nextIdx = idx + 1;
            if (nextIdx < progressSteps.length - 1) {
                progressSteps[nextIdx].status = 'running';
                state.generateProgressStepIndex = nextIdx;
                rerender();
            } else if (nextIdx === progressSteps.length - 1) {
                progressSteps[nextIdx].status = 'running';
                state.generateProgressStepIndex = nextIdx;
                rerender();
                clearInterval(generateProgressTimer);
                generateProgressTimer = null;
            } else {
                clearInterval(generateProgressTimer);
                generateProgressTimer = null;
            }
        };
        generateProgressTimer = setInterval(advanceStep, STEP_DELAY);

        try {
            const response = await api.generateFromScript(state.storyboardId, {
                max_group_duration: state.maxGroupDuration || 15,
                force_medium_shot: state.forceMediumShot !== false,
                no_bg_music: state.noBgMusic !== false,
                split_multi_dialogue: state.splitMultiDialogue === true,
                model: splitModel.model,
                model_id: splitModel.model_id,
                vendor_id: splitModel.vendor_id,
            });
            clearInterval(generateProgressTimer);
            generateProgressTimer = null;
            progressSteps.forEach(s => s.status = 'completed');
            state.generateProgressStepIndex = progressSteps.length;
            rerender();
            setTimeout(() => {
                state.showGenerateProgressDialog = false;
                loadStoryboardData(response);
                handleAutoDialogueAudioPolling(response);
                state.isGeneratingFromScript = false;
                // 拆分已重建分镜集合（含删除后重新拆分），清除旧的自动生成去重标志，
                // 让本轮新生成的缺失首帧能够重新触发一次自动生成。
                resetAutoMissingImagesFlag(state.storyboardId);
                autoGenerateMissingFirstFrames();
                notify(`已生成 ${response.generated_count || state.scenes.length} 个分镜`);
                rerender();
            }, 500);
        } catch (error) {
            clearInterval(generateProgressTimer);
            generateProgressTimer = null;
            const idx = state.generateProgressStepIndex;
            if (idx >= 0 && idx < progressSteps.length) {
                progressSteps[idx].status = 'failed';
            }
            state.generateProgressError = error.message || '生成分镜失败';
            state.isGeneratingFromScript = false;
            rerender();
        }
        return;
    }

    if (action === 'add-scene') {
        const response = await api.addScene(state.storyboardId, {
            title: `分镜${state.scenes.length + 1}`,
            duration: 5,
            prompt_json: {},
        });
        addSceneToState(response.scene);
        rerender();
        return;
    }

    if (action === 'insert-scene') {
        const prevId = target.dataset.prevId ? parseInt(target.dataset.prevId, 10) : null;
        const nextId = target.dataset.nextId ? parseInt(target.dataset.nextId, 10) : null;
        const response = await api.addScene(state.storyboardId, {
            title: `分镜${state.scenes.length + 1}`,
            duration: 5,
            prompt_json: {},
            prev_id: prevId,
            next_id: nextId,
        });
        addSceneToState(response.scene);
        rerender();
        return;
    }

    if (action === 'duplicate-scene') {
        const response = await api.duplicateScene(parseInt(target.dataset.id, 10));
        addSceneToState(response.scene);
        rerender();
        return;
    }

    if (action === 'delete-scene') {
        const sceneId = parseInt(target.dataset.id, 10);
        if (!window.confirm('确定删除这个分镜吗？')) return;
        await api.deleteScene(sceneId);
        removeSceneFromState(sceneId);
        rerender();
        return;
    }

    if (action === 'toggle-view') {
        state.viewMode = state.viewMode === 'grid' ? 'timeline' : 'grid';
        rerender();
        await persistUiConfig();
        return;
    }

    if (action === 'toggle-play') {
        state.isPlaying = !state.isPlaying;
        rerender();
        return;
    }

    if (action === 'toggle-subtitle') {
        state.subtitleEnabled = target.checked;
        await persistUiConfig();
        return;
    }

    if (action === 'toggle-force-medium-shot' || action === 'toggle-no-bg-music' || action === 'toggle-split-multi-dialogue') {
        if (state.isGeneratingFromScript) return;
        if (action === 'toggle-force-medium-shot') state.forceMediumShot = target.checked;
        else if (action === 'toggle-no-bg-music') state.noBgMusic = target.checked;
        else state.splitMultiDialogue = target.checked;
        await persistUiConfig();
        rerender();
        return;
    }

    if (action === 'toggle-ai') {
        state.aiOptimize = !state.aiOptimize;
        rerender();
        await persistUiConfig();
        return;
    }

    if (action === 'close-model-config') {
        state.showModelConfigModal = false;
        rerender();
        return;
    }

    if (action === 'save-prompt' && current) {
        const currentPrompt = current.promptJson || {};
        const sceneDescEl = document.querySelector('[data-edit-field="scene_desc"]');
        current.promptJson = {
            perspective: currentPrompt.perspective || '',
            style: currentPrompt.style || '',
            scene_desc: sceneDescEl ? sceneDescEl.value : (currentPrompt.scene_desc || ''),
            character_desc: currentPrompt.character_desc || '',
        };
        await api.updateScenePrompt(current.id, sceneToPromptPayload(current));
        rerender();
        return;
    }

    if (action === 'save-scene' && current) {
        const titleEl = document.querySelector('[data-scene-field="title"]');
        const videoPromptEl = document.querySelector('[data-scene-field="videoPrompt"]');
        if (titleEl) current.title = titleEl.value;
        if (videoPromptEl) current.videoPrompt = videoPromptEl.value;
        await api.updateScene(current.id, sceneToUpdatePayload(current));
        rerender();
        return;
    }

    if (action === 'switch-location' || action === 'add-prop' || action === 'remove-location' || action === 'remove-prop') {
        const sceneId = parseInt(target.dataset.sceneId || target.closest('[data-scene-id]')?.dataset.sceneId, 10);
        const sc = state.scenes.find(s => s.id === sceneId);
        if (!sc) return;

        if (action === 'remove-location') {
            sc.location = null;
            await persistSceneLocationProps(sc);
            return;
        }
        if (action === 'remove-prop') {
            const pid = parseInt(target.dataset.propId, 10);
            sc.props = (sc.props || []).filter(p => p.id !== pid);
            await persistSceneLocationProps(sc);
            return;
        }
        if (action === 'switch-location') {
            showLocationDropdown(sc, target);
            return;
        }
        if (action === 'add-prop') {
            showPropDropdown(sc, target);
            return;
        }
    }

    // ==================== 对话操作 ====================
    if (action === 'add-dialogue' && current) {
        const response = await api.addDialogue(current.id, {
            character_id: null, text: '', speed: 1.0, volume: 100,
        });
        addDialogueToState(current.id, response.dialogue);
        rerender();
        return;
    }

    if (action === 'save-dialogue') {
        const dialogueId = parseInt(target.dataset.dialogueId, 10);
        const row = target.closest('[data-dialogue-row]');
        const characterRaw = row.querySelector('[data-dialogue-field="characterId"]')?.value;
        const text = row.querySelector('[data-dialogue-field="text"]')?.value || '';
        const speed = parseFloat(row.querySelector('[data-dialogue-field="speed"]')?.value || 1.0);
        const volume = parseInt(row.querySelector('[data-dialogue-field="volume"]')?.value || 100, 10);
        const payload = {
            character_id: characterRaw ? parseInt(characterRaw, 10) : null,
            text, speed, volume,
        };
        await api.updateDialogue(dialogueId, payload);
        patchDialogueInState(dialogueId, {
            characterId: payload.character_id, text, speed, volume,
        });
        notify('对话已保存');
        return;
    }

    if (action === 'delete-dialogue') {
        const dialogueId = parseInt(target.dataset.dialogueId, 10);
        if (!window.confirm('确定删除这句对话吗？')) return;
        await api.deleteDialogue(dialogueId);
        removeDialogueFromState(dialogueId);
        rerender();
        return;
    }

    if (action === 'generate-voiceover') {
        const dialogueId = parseInt(target.dataset.dialogueId, 10);
        const response = await api.generateDialogueVoiceover(dialogueId);
        if (response.success) {
            const ownerScene = state.scenes.find(s => (s.dialogues || []).some(d => d.id === dialogueId));
            if (ownerScene) pollSceneTaskStatus(ownerScene.id);
        }
        notify(response.error || '配音任务已提交');
        return;
    }

    if (action === 'mention') {
        state.showMentionPopup = !state.showMentionPopup;
        rerender();
        return;
    }

    if (action === 'add-reference-image') {
        if (state.chatMode !== 'video') return;
        const fileInput = document.getElementById('reference-file-input');
        if (fileInput) fileInput.click();
        return;
    }

    if (action === 'remove-reference-image') {
        const refId = target.getAttribute('data-reference-id');
        if (refId) {
            state.referenceImages = (state.referenceImages || []).filter(r => r.id !== refId);
            rerender();
        }
        return;
    }

    if (action === 'open-model-config') {
        state.showModelConfigModal = true;
        // 默认根据当前助手模式
        const mode = state.chatMode;
        state.currentConfigTab = mode === 'video' ? 'video' : 'dialogue';
        rerender();
        return;
    }

    // 画风/构图全局编辑已移至 header .header-style-info 点击（data-action=edit-global-style）

    if (action === 'send-ai') {
        if (!current) return;
        await sendStoryboardAgentMessage(current);
        rerender();
        return;
    }

    if (action === 'open-export') {
        state.showExportDialog = true;
        rerender();
        return;
    }

    if (action === 'close-export') {
        state.showExportDialog = false;
        rerender();
        return;
    }

    if (action === 'export-full') {
        const response = await api.exportFullVideo(state.storyboardId);
        notify(response.error || '完整视频导出任务已提交');
        state.showExportDialog = false;
        rerender();
        return;
    }

    if (action === 'export-scenes') {
        const response = await api.exportAllScenes(state.storyboardId);
        notify(response.error || '分镜导出任务已提交');
        state.showExportDialog = false;
        rerender();
        return;
    }

    if (action === 'placeholder') {
        notify('该能力正在接入中');
    }

    if (action === 'edit-global-style') {
        state.showGlobalStyleDialog = true;
        rerender();
        return;
    }

    if (action === 'close-global-style') {
        state.showGlobalStyleDialog = false;
        rerender();
        return;
    }

    if (action === 'save-global-style') {
        const styleEl = document.querySelector('[data-global-field="style"]');
        const compEl = document.querySelector('[data-global-field="composition"]');
        const newStyle = styleEl ? styleEl.value.trim() : (state.style || '');
        const newComp = compEl ? compEl.value.trim() : (state.compositionPreference || '');
        try {
            if (state.storyboardId) {
                await api.updateStoryboard(state.storyboardId, {
                    style: newStyle,
                    composition_preference: newComp,
                });
            }
            state.style = newStyle;
            state.compositionPreference = newComp;
            state.showGlobalStyleDialog = false;
            rerender();
            notify('画风和构图倾向已更新');
        } catch (e) {
            notify('更新失败: ' + (e.message || e));
        }
        return;
    }
}

function handleRoute(route) {
    if (route === 'storyboard-list') {
        window.location.href = '/storyboard-list';
        return;
    }
    if (route === 'script') {
        window.location.href = buildQuery('/script-writer', {
            world_id: state.worldId,
            user_id: state.userId,
        });
        return;
    }
    if (route === 'canvas') {
        if (state.workflowId) {
            window.location.href = buildQuery('/video-workflow', {
                id: state.workflowId,
                from_world_id: state.worldId,
                auto_load_script: 'true',
            });
        } else {
            window.location.href = '/video-workflow-list';
        }
    }
}

export function bindEvents() {
    document.addEventListener('click', async (event) => {
        const routeTarget = event.target.closest('[data-route]');
        if (routeTarget) {
            handleRoute(routeTarget.dataset.route);
            return;
        }

        const sceneTarget = event.target.closest('[data-scene]');
        const actionTarget = event.target.closest('[data-action]');
        const candidateTarget = event.target.closest('[data-candidate-id][data-candidate-type]');
        if (candidateTarget) {
            event.preventDefault();
            try {
                await selectSceneCandidate(candidateTarget);
            } catch (error) {
                notify(error.message || '选择候选图失败');
            }
            return;
        }

        if (sceneTarget && !actionTarget) {
            const sceneId = parseInt(sceneTarget.dataset.scene, 10);
            state.currentSceneId = sceneId;
            state.currentTime = 0;
            state.agentMessages = [];
            state.referenceImages = [];
            rerender();
            // 异步加载该 scene 的候选资产
            (async () => {
                try {
                    // skipRerender=true：由本 IIFE 末尾统一渲染，避免渲染竞态
                    const historyPromise = loadSceneAgentMessages(sceneId, true).catch(() => {});
                    await loadSceneCandidates(sceneId);
                    await historyPromise;
                    rerender();
                } catch (e) {
                    // 静默失败，不影响主流程
                }
            })();
            return;
        }

        // Handle model config tabs (must be before action guard since tabs have no data-action)
        const configTabTarget = event.target.closest('[data-config-tab]');
        if (configTabTarget) {
            const tab = configTabTarget.dataset.configTab;
            state.currentConfigTab = tab;
            rerender();
            return;
        }

        if (!actionTarget) return;
        event.preventDefault();
        try {
            await handleAction(actionTarget.dataset.action, actionTarget);
        } catch (error) {
            notify(error.message || '操作失败');
        }
    });

    document.addEventListener('input', (event) => {
        const target = event.target;
        if (target.id === 'chat-textarea') {
            state.inputMessage = target.value;
        }
    });

    document.addEventListener('mouseenter', (event) => {
        if (event.target && typeof event.target.closest === 'function' && event.target.closest('.scene-timeline-list')) {
            isTimelineHovered = true;
        }
    }, true);

    document.addEventListener('mouseleave', (event) => {
        if (!event.target || typeof event.target.closest !== 'function') return;
        const list = event.target.closest('.scene-timeline-list');
        if (list && !list.contains(event.relatedTarget)) {
            isTimelineHovered = false;
        }
    }, true);

    document.addEventListener('keydown', (event) => {
        const target = event.target;
        if (target.id === 'chat-textarea' && event.key === 'Enter' && !event.ctrlKey && !event.shiftKey && !event.altKey && !event.metaKey) {
            event.preventDefault();
            const btn = document.querySelector('[data-action="send-ai"]');
            if (btn) btn.click();
            return;
        }
        if (!isTimelineHovered) return;
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;

        const currentIndex = state.scenes.findIndex(s => s.id === state.currentSceneId);
        if (currentIndex === -1) return;

        let newIndex = currentIndex;
        if (event.key === 'ArrowLeft' && currentIndex > 0) {
            newIndex = currentIndex - 1;
        } else if (event.key === 'ArrowRight' && currentIndex < state.scenes.length - 1) {
            newIndex = currentIndex + 1;
        }
        if (newIndex === currentIndex) return;

        event.preventDefault();
        state.currentSceneId = state.scenes[newIndex].id;
        state.currentTime = 0;
        state.agentMessages = [];
        state.referenceImages = [];
        rerender();

        requestAnimationFrame(() => {
            const activeThumb = document.querySelector('.scene-timeline-thumb.active');
            if (!activeThumb) return;
            const list = document.querySelector('.scene-timeline-list');
            if (!list) return;
            const thumbRect = activeThumb.getBoundingClientRect();
            const listRect = list.getBoundingClientRect();
            if (thumbRect.left < listRect.left + 8) {
                list.scrollLeft -= (listRect.left + 8 - thumbRect.left);
            } else if (thumbRect.right > listRect.right - 8) {
                list.scrollLeft += (thumbRect.right - (listRect.right - 8));
            }
        });
    });

    document.addEventListener('wheel', (event) => {
        const timelineList = event.target.closest('.scene-timeline-list');
        if (!timelineList) return;
        if (Math.abs(event.deltaY) > 0 && timelineList.scrollWidth > timelineList.clientWidth) {
            event.preventDefault();
            timelineList.scrollLeft += event.deltaY;
        }
    }, { passive: false });

    document.addEventListener('change', async (event) => {
        const target = event.target;
        if (target.id === 'chat-mode-select') {
            state.chatMode = target.value;
            rerender();
            await persistUiConfig();
            return;
        }

        if (target.id === 'reference-file-input') {
            await handleReferenceFileChange(target);
            return;
        }

        if (target.dataset.ratioSelect !== undefined) {
            state.workflowRatio = target.value;
            if (state.storyboardId) {
                api.updateStoryboard(state.storyboardId, { workflow_ratio: state.workflowRatio })
                    .then(() => notify('画面比例已更新'))
                    .catch(err => notify('比例更新失败: ' + (err.message || err)));
            }
            return;
        }

        // 工具栏的图片/视频模型 select 已移除，仅在弹框配置中选择（data-config-select）
        // 对话模型的 toolbar select 也已移除

        if (target.dataset.configSelect) {
            // 弹框内的模型选择，更新对应 state 并刷新
            const type = target.dataset.configSelect;
            const val = target.value;
            if (type === 'dialogue') {
                const selected = target.selectedOptions[0];
                const modelId = selected?.dataset?.modelId;
                const vendorId = selected?.dataset?.vendorId;
                state.selectedLlmModel = modelId ? {
                    model: val,
                    model_id: modelId,
                    vendor_id: vendorId ? parseInt(vendorId, 10) : null,
                } : val;
                resolveSelectedLlmModel();
                try {
                    localStorage.setItem('storyboard_lastSelectedLlmModel', JSON.stringify(state.selectedLlmModel));
                } catch {}
            } else if (type === 'scriptSplit') {
                const selected = target.selectedOptions[0];
                const modelId = selected?.dataset?.modelId;
                const vendorId = selected?.dataset?.vendorId;
                state.selectedScriptSplitLlmModel = modelId ? {
                    model: val,
                    model_id: modelId,
                    vendor_id: vendorId ? parseInt(vendorId, 10) : null,
                } : val;
                resolveSelectedScriptSplitLlmModel();
                try {
                    localStorage.setItem('storyboard_lastScriptSplitLlmModel', JSON.stringify(state.selectedScriptSplitLlmModel));
                } catch {}
            } else if (type === 'image') {
                state.selectedImageTaskId = parseInt(val, 10) || state.selectedImageTaskId;
                // 跨故事板记忆兜底（与 LLM 模型写法一致），新故事板/首次进入弹框时回显
                try {
                    localStorage.setItem('storyboard_lastSelectedImageTaskId', String(state.selectedImageTaskId));
                } catch {}
            } else if (type === 'video') {
                state.selectedVideoTaskId = parseInt(val, 10) || state.selectedVideoTaskId;
                // 跨故事板记忆兜底，新故事板/首次进入弹框时回显
                try {
                    localStorage.setItem('storyboard_lastSelectedVideoTaskId', String(state.selectedVideoTaskId));
                } catch {}
            } else if (type === 'maxGroupDuration') {
                const d = parseInt(val, 10);
                if ([5, 8, 10, 15].includes(d)) state.maxGroupDuration = d;
            }

            // 如果当前助手模式匹配，也可视为立即生效
            rerender();
            if (state.storyboardId) {
                persistUiConfig().catch(() => {});
            }
            return;
        }

        if (target.dataset.configTab) {
            const tab = target.dataset.configTab;
            state.currentConfigTab = tab;
            rerender();
            return;
        }
        // 画风/构图编辑入口已改为 header 点击（data-action="edit-global-style"）
    });

    document.addEventListener('click', (event) => {
        const overlay = event.target.closest('.modal-overlay');
        if (overlay && event.target === overlay) {
            if (generateProgressTimer) {
                clearInterval(generateProgressTimer);
                generateProgressTimer = null;
            }
            state.showModelConfigModal = false;
            state.showExportDialog = false;
            state.showGlobalStyleDialog = false;
            state.showGenerateFromScriptDialog = false;
            state.showGenerateProgressDialog = false;
            rerender();
            return;
        }

        const tab = event.target.closest('[data-tab]');
        if (tab) {
            state.activeTab = tab.dataset.tab;
            rerender();
            persistUiConfig();
        }

        const mentionTab = event.target.closest('[data-mention-tab]');
        if (mentionTab) {
            state.mentionTab = mentionTab.dataset.mentionTab;
            rerender();
        }

        const mentionItem = event.target.closest('[data-mention-item]');
        if (mentionItem) {
            state.inputMessage = `${state.inputMessage || ''}@${mentionItem.dataset.mentionItem} `;
            state.showMentionPopup = false;
            rerender();
        }

        // 提示词框点击切换为编辑 (直接在左侧，角色图片以 <img>角色名 格式内联在内容中)
        // 参考 video_workflow.html 分镜节点 prompt 显示
        const promptDisplay = event.target.closest('.prompt-display');
        if (promptDisplay && !promptDisplay.querySelector('textarea')) {
            closeAllDropdowns();
            const type = promptDisplay.dataset.promptType;
            const scene = getCurrentScene();
            if (!scene) return;
            let raw = '';
            if (type === 'scene') {
                raw = scene.promptJson ? scene.promptJson.scene_desc || '' : '';
            } else if (type === 'video') {
                raw = scene.videoPrompt || '';
            }
            const ta = document.createElement('textarea');
            ta.className = 'voice-textarea';
            ta.value = raw;
            ta.style.minHeight = '120px';
            promptDisplay.innerHTML = '';
            promptDisplay.appendChild(ta);
            ta.focus();
            ta.select();

            // 支持输入 @ 弹出角色/道具选择
            ta.addEventListener('keydown', (e) => {
                if (e.key === '@') {
                    e.preventDefault();
                    showMentionDropdownForPrompt(ta, promptDisplay, type, scene);
                }
            });

            // Do not use {once: true}. Dropdown clicks cause an early blur that we intentionally ignore
            // (to keep editing UI). A later real blur (click away or Esc) must still be able to save + rerender.
            const onFinish = async () => {
                if (!ta.parentNode) return;
                if (ta._skipPromptBlurRerender) {
                    ta._skipPromptBlurRerender = false;
                    return; // dropdown selection caused this blur; keep the textarea open
                }
                const val = ta.value;
                await persistPromptValue(scene, type, val);
                rerender();
            };
            ta.addEventListener('blur', () => {
                // tiny delay lets dropdown mousedown/insert run and set/clear skip flag first
                setTimeout(onFinish, 0);
            });
            ta.addEventListener('keydown', (ev) => {
                if (ev.key === 'Escape') {
                    ev.preventDefault();
                    ta._skipPromptBlurRerender = false;
                    ta.blur();
                }
                if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) {
                    ev.preventDefault();
                    ta._skipPromptBlurRerender = false;
                    ta.blur();
                }
            });
        }
    });
}

async function persistSceneLocationProps(sc) {
    const prompt = { ...(sc.promptJson || {}) };
    prompt.location = sc.location ? { id: sc.location.id, name: sc.location.name } : null;
    prompt.props = (sc.props || []).map(p => ({ id: p.id, name: p.name }));
    await api.updateScenePrompt(sc.id, prompt);
    sc.promptJson = prompt;
    rerender();
}

async function persistPromptValue(scene, type, value) {
    try {
        if (type === 'scene') {
            if (!scene.promptJson) scene.promptJson = {};
            scene.promptJson.scene_desc = value;
            await api.updateScenePrompt(scene.id, sceneToPromptPayload(scene));
        } else if (type === 'video') {
            scene.videoPrompt = value;
            await api.updateScene(scene.id, sceneToUpdatePayload(scene));
        }
    } catch (e) {
        console.error(e);
    }
}

function showLocationDropdown(sc, anchorEl) {
    closeAllDropdowns();
    const dropdown = document.createElement('div');
    dropdown.className = 'asset-dropdown';
    dropdown.style.cssText = 'position:absolute; background:#fff; border:1px solid #ccc; border-radius:4px; max-height:200px; overflow:auto; z-index:10000; font-size:12px; box-shadow:0 2px 8px rgba(0,0,0,0.15);';

    const locs = state.locations || [];
    if (locs.length === 0) {
        dropdown.innerHTML = '<div style="padding:8px;">暂无场景</div>';
    } else {
        locs.forEach(loc => {
            const isSel = sc.location && sc.location.id === loc.id;
            const item = document.createElement('div');
            item.className = 'asset-dropdown-item' + (isSel ? ' selected' : '');
            const img = loc.avatar || loc.reference_image ? `<img src="${getThumbnailUrl(loc.avatar || loc.reference_image, 20)}" style="width:20px;height:20px;border-radius:3px;margin-right:6px;">` : '';
            item.innerHTML = `${img}<span>${escapeHtml(loc.name)}</span>`;
            item.onclick = async (e) => {
                e.stopPropagation();
                sc.location = {
                    id: loc.id,
                    name: loc.name,
                    avatar: loc.avatar || loc.reference_image,
                    reference_image: loc.reference_image || loc.avatar
                };
                await persistSceneLocationProps(sc);
                dropdown.remove();
            };
            dropdown.appendChild(item);
        });
    }

    positionDropdown(dropdown, anchorEl);
    document.body.appendChild(dropdown);

    const closeH = (e) => {
        if (!dropdown.contains(e.target)) {
            dropdown.remove();
            document.removeEventListener('click', closeH, true);
        }
    };
    setTimeout(() => document.addEventListener('click', closeH, true), 0);
}

function showPropDropdown(sc, anchorEl) {
    closeAllDropdowns();
    const dropdown = document.createElement('div');
    dropdown.className = 'asset-dropdown';
    dropdown.style.cssText = 'position:absolute; background:#fff; border:1px solid #ccc; border-radius:4px; max-height:200px; overflow:auto; z-index:10000; font-size:12px; box-shadow:0 2px 8px rgba(0,0,0,0.15);';

    const allProps = state.props || [];
    const selectedIds = (sc.props || []).map(p => p.id);
    if (allProps.length === 0) {
        dropdown.innerHTML = '<div style="padding:8px;">暂无道具</div>';
    } else {
        allProps.forEach(prop => {
            const isSel = selectedIds.includes(prop.id);
            const item = document.createElement('div');
            item.className = 'asset-dropdown-item' + (isSel ? ' selected' : '');
            const img = prop.avatar || prop.reference_image ? `<img src="${getThumbnailUrl(prop.avatar || prop.reference_image, 20)}" style="width:20px;height:20px;border-radius:3px;margin-right:6px;">` : '';
            item.innerHTML = `${isSel ? '✓ ' : ''}${img}<span>${escapeHtml(prop.name)}</span>`;
            item.onclick = async (e) => {
                e.stopPropagation();
                sc.props = sc.props || [];
                if (isSel) {
                    sc.props = sc.props.filter(p => p.id !== prop.id);
                } else {
                    sc.props.push({
                        id: prop.id,
                        name: prop.name,
                        avatar: prop.avatar || prop.reference_image,
                        reference_image: prop.reference_image || prop.avatar
                    });
                }
                await persistSceneLocationProps(sc);
                dropdown.remove();
            };
            dropdown.appendChild(item);
        });
    }

    positionDropdown(dropdown, anchorEl);
    document.body.appendChild(dropdown);

    const closeH = (e) => {
        if (!dropdown.contains(e.target)) {
            dropdown.remove();
            document.removeEventListener('click', closeH, true);
        }
    };
    setTimeout(() => document.addEventListener('click', closeH, true), 0);
}

function positionDropdown(dropdown, anchor) {
    const rect = anchor.getBoundingClientRect();
    dropdown.style.position = 'fixed';
    let top = rect.bottom + 2;
    // 避免被固定高度的 .info-card / .sidebar-content 裁剪，确保完整可见（必要时上翻）
    const estHeight = 200;
    if (top + estHeight > window.innerHeight - 8) {
        top = Math.max(4, rect.top - 4 - 180);
    }
    dropdown.style.top = `${top}px`;
    dropdown.style.left = `${rect.left}px`;
    dropdown.style.minWidth = `${Math.max(140, rect.width)}px`;
    // 允许下拉框横向溢出左侧栏，完整显示
    dropdown.style.maxWidth = '360px';
}

function closeAllDropdowns() {
    document.querySelectorAll('.asset-dropdown').forEach(d => d.remove());
}

function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, function(m) {
        return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m];
    });
}

function insertAssetTag(textarea, name, kind) {
    const start = textarea.selectionStart || 0;
    const end = textarea.selectionEnd || 0;
    const value = textarea.value;
    const insert = kind === 'prop'
        ? '〖〖' + name + '〗〗'
        : '【【' + name + '】】';
    textarea.value = value.substring(0, start) + insert + value.substring(end);
    const pos = start + insert.length;
    textarea.setSelectionRange(pos, pos);
    textarea.focus();
}

function showMentionDropdownForPrompt(textarea, container, promptType, scene) {
    closeAllDropdowns();
    const dropdown = document.createElement('div');
    dropdown.className = 'asset-dropdown mention-dropdown';
    dropdown.style.cssText = 'position:absolute; background:#fff; border:1px solid #ccc; border-radius:4px; max-height:240px; overflow:hidden; z-index:10000; font-size:12px; box-shadow:0 2px 8px rgba(0,0,0,0.15); display:flex; flex-direction:column;';

    let currentTab = 'character';

    const buildTabs = () => {
        const tabsDiv = document.createElement('div');
        tabsDiv.className = 'asset-dropdown-tabs';
        tabsDiv.style.cssText = 'display:flex; gap:2px; padding:4px; border-bottom:1px solid #eee; background:#f8f9fa;';
        const tabs = [
            { key: 'character', label: '角色' },
            { key: 'prop', label: '道具' },
        ];
        tabs.forEach(t => {
            const btn = document.createElement('button');
            btn.textContent = t.label;
            btn.style.cssText = `flex:1; padding:5px 4px; border:none; border-radius:3px; background:${currentTab === t.key ? 'var(--primary)' : 'transparent'}; color:${currentTab === t.key ? '#fff' : 'var(--muted)'}; cursor:pointer; font-size:12px;`;
            btn.onmousedown = (e) => {
                e.preventDefault();
                e.stopPropagation();
                currentTab = t.key;
                renderList();
            };
            tabsDiv.appendChild(btn);
        });
        return tabsDiv;
    };

    const renderList = () => {
        const oldList = dropdown.querySelector('.mention-list');
        if (oldList) oldList.remove();

        const listDiv = document.createElement('div');
        listDiv.className = 'mention-list';
        listDiv.style.cssText = 'overflow:auto; max-height:180px; padding:4px;';

        const items = currentTab === 'character' ? (state.characters || []) : (state.props || []);
        if (!items.length) {
            listDiv.innerHTML = `<div style="padding:8px; color:var(--muted);">暂无${currentTab === 'character' ? '角色' : '道具'}</div>`;
        } else {
            items.forEach(item => {
                const row = document.createElement('div');
                row.className = 'asset-dropdown-item';
                const aurl = item.avatar || item.reference_image;
                const img = aurl ? `<img src="${escapeHtml(getThumbnailUrl(aurl, 20))}" style="width:20px;height:20px;border-radius:3px;margin-right:6px;object-fit:cover;">` : '';
                row.innerHTML = `${img}<span>${escapeHtml(item.name)}</span>`;
                row.onmousedown = (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    insertAssetTag(textarea, item.name, currentTab);
                    dropdown.remove();
                    persistPromptValue(scene, promptType, textarea.value).catch(console.error);
                    textarea._skipPromptBlurRerender = true;
                    setTimeout(() => {
                        if (textarea) textarea._skipPromptBlurRerender = false;
                    }, 120);
                };
                listDiv.appendChild(row);
            });
        }

        // 更新 tabs 按钮颜色
        const tabBtns = dropdown.querySelectorAll('.asset-dropdown-tabs button');
        tabBtns.forEach((btn, idx) => {
            const tabKey = idx === 0 ? 'character' : 'prop';
            btn.style.background = currentTab === tabKey ? 'var(--primary)' : 'transparent';
            btn.style.color = currentTab === tabKey ? '#fff' : 'var(--muted)';
        });

        dropdown.appendChild(listDiv);
    };

    dropdown.appendChild(buildTabs());
    renderList();

    positionDropdown(dropdown, textarea);
    document.body.appendChild(dropdown);

    const closeH = (e) => {
        if (!dropdown.contains(e.target)) {
            dropdown.remove();
            document.removeEventListener('click', closeH, true);
        }
    };
    setTimeout(() => document.addEventListener('click', closeH, true), 0);
}
