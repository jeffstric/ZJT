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
    applyThinkingDefaultsForModel,
    applyGenerateProgressStatus,
    saveThinkingStateToStorage,
    getThinkingParams,
    syncVideoMediaFromScene,
    refreshSceneFirstFrameSlot,
    ensureVideoImageModeSupported,
    ensureVideoGenerationPrefsSupported,
    buildVideoSlotUrls,
    buildVideoGenerationPayloadExtras,
    canAddVideoMedia,
    createVideoMediaItem,
    syncReferenceImagesCompat,
    getMaxVideoMediaCount,
    videoModelSupportsLastFrame,
    getSupportedVideoImageModes,
    setAgentChatFontStep,
    isSceneAgentRunning,
    startSceneAgentRun,
    setSceneAgentTaskId,
    finishSceneAgentRun,
    setSceneAgentMessages,
    appendSceneAgentMessage,
    activateSceneAgentMessages,
} from './state.js';
import * as api from './api.js';
import { sceneToPromptPayload, sceneToUpdatePayload } from './adapters.js';
import {
    refresh,
    renderPromptWithInlineRoles,
    getThumbnailUrl,
    Region,
} from './render.js';
import {
    REGIONS_ON_SCENE_CHANGE,
    REGIONS_ON_SCENE_STRUCT,
    REGIONS_AGENT_STREAM,
    REGIONS_MODAL,
} from './ui_regions.js';
import { pollSceneTaskStatus, pollScriptSplitTask, stopScriptSplitTaskPolling } from './polling.js';
import {
    togglePlayback,
    stopPlayback,
    syncSelectionToTimeline,
    scrollTimelineToScene,
} from './playback.js';
import {
    autoCompleteMissingFirstFrames,
    autoGenerateMissingFirstFrames,
    resetAutoMissingImagesFlag,
} from './auto_missing_images.js';
import { getAutoCompleteSummary } from './auto_missing_images_state.js';
import { autoCompleteMissingVideos } from './auto_missing_videos.js';
import {
    applyVideoTypeSwitchResult,
    canSwitchToDigitalHuman,
} from './video_type_switch_state.js';
import {
    clearLocationReferenceSelection,
    closeReferenceVariantSelector,
    openReferenceVariantSelector,
} from './reference_variant_selector.js';
import {
    applyVideoCandidateSelection,
    captureVideoCandidateSelection,
    restoreVideoCandidateSelection,
} from './candidate_selection_state.js';

let generateProgressTimer = null;
let isTimelineHovered = false;

function notify(message) {
    window.alert(message);
}

function resetRechargeState() {
    state.showRechargeModal = false;
    state.rechargeState = 'loading';
    state.rechargePackages = [];
    state.selectedRechargePackage = null;
    state.rechargeQrCodeUrl = '';
    state.rechargeError = '';
}

async function loadRechargePackages() {
    state.showRechargeModal = true;
    state.rechargeState = 'loading';
    state.selectedRechargePackage = null;
    state.rechargeQrCodeUrl = '';
    state.rechargeError = '';
    rerenderModals();
    try {
        const packages = await api.fetchRechargePackages();
        state.rechargePackages = packages;
        state.rechargeState = 'packages';
    } catch (error) {
        state.rechargeError = error.message || '加载套餐失败';
        state.rechargeState = 'error';
    }
    rerenderModals();
}

async function openRechargeModal() {
    try {
        const config = await api.fetchServerConfig();
        if (config && config.is_local) {
            notify('只有云端环境才能开启二维码支付。本地模式下，管理员用户请进入后台增加算力，非管理员用户请通知管理员。');
            return;
        }
    } catch (e) {
        console.error('获取配置失败:', e);
    }
    await loadRechargePackages();
}

async function selectRechargePackage(pkg) {
    if (!pkg) return;
    state.selectedRechargePackage = pkg;
    state.rechargeState = 'qrcode';
    state.rechargeQrCodeUrl = '';
    state.rechargeError = '';
    rerenderModals();

    try {
        let paymentIp = '0.0.0.0';
        try {
            const ipResponse = await fetch('https://api.ipify.org?format=json');
            const ipData = await ipResponse.json();
            paymentIp = ipData.ip || '0.0.0.0';
        } catch (e) {
            console.error('获取用户IP失败:', e);
        }

        const data = await api.createWechatPayOrder({
            package_id: pkg.package_id,
            payment_ip: paymentIp,
        });
        if (data.code_url) {
            state.rechargeQrCodeUrl = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(data.code_url)}`;
            state.rechargeState = 'qrcode';
        } else {
            throw new Error(data.error || '创建支付订单失败');
        }
    } catch (error) {
        console.error('创建支付订单失败:', error);
        state.rechargeError = error.message || '创建支付订单失败';
        state.rechargeState = 'error';
    }
    rerenderModals();
}

function handleAutoDialogueAudioPolling(response) {
    const summary = response && response.audio_auto_generate;
    if (!summary || !summary.enabled) return null;
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
        return `已提交 ${submitted} 条配音任务，${skipped} 条跳过`;
    }
    return null;
}

/**
 * 分区刷新入口。默认 all（仍受 preview busy 保护）。
 * 高频路径请传明确 regions，禁止依赖全量。
 * @param {string|string[]|'all'} [regions]
 * @param {{ forcePreview?: boolean }} [options]
 */
function rerender(regions = 'all', options = {}) {
    refresh(regions, options);
}

/** Agent 流式：只刷对话 log */
function rerenderAgentUi() {
    refresh(REGIONS_AGENT_STREAM);
}

/** 弹窗开闭：只刷 modal 层 */
function rerenderModals() {
    refresh(REGIONS_MODAL);
}

/** 助手面板（输入区/模式/字号等） */
function rerenderAgentPanel() {
    refresh([Region.AGENT_PANEL]);
}

function rerenderAgentUiForScene(sceneId) {
    if (String(state.currentSceneId) === String(sceneId)) rerenderAgentUi();
}

function rerenderAgentPanelForScene(sceneId) {
    if (String(state.currentSceneId) === String(sceneId)) rerenderAgentPanel();
}

function buildQuery(base, params) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value !== null && value !== undefined && value !== '') query.set(key, value);
    });
    const qs = query.toString();
    return qs ? `${base}?${qs}` : base;
}

/**
 * 候选媒体可展示 URL：必须是单条路径/URL。
 * 生成中的 ai_tools.image_path 常为逗号拼接的多张参考图，不能当作结果图。
 */
export function isRenderableCandidateUrl(url) {
    if (url == null) return false;
    const value = String(url).trim();
    if (!value) return false;
    if (value.includes(',')) return false;
    return true;
}

function getSceneAssetCandidateUrl(asset) {
    if (!asset) return '';
    const raw = asset.result_url
        || asset.url
        || asset.image_url
        || asset.video_url
        || asset.ai_tool?.result_url
        || asset.tool?.result_url
        || '';
    return isRenderableCandidateUrl(raw) ? String(raw).trim() : '';
}

function mapSceneAssetCandidates(response, assetType) {
    const selectedId = response?.selected?.[assetType];
    const assets = response?.assets || response?.data || [];
    return assets.map(asset => ({
        id: asset.id,
        url: getSceneAssetCandidateUrl(asset),
        status: asset.status ?? asset.ai_tool?.status ?? asset.tool?.status ?? null,
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
        scene.previewAssetType = 'first_frame';
    } else if (assetType === 'video') {
        scene.selectedVideoId = assetId;
        if (url) scene.videoUrl = url;
        scene.previewAssetType = 'video';
    }
}

async function selectSceneCandidate(target, { autoplay = false } = {}) {
    const current = getCurrentScene();
    if (!current) return;
    const candidateType = target.dataset.candidateType;
    const assetType = candidateType === 'video' ? 'video' : 'first_frame';
    const assetId = parseInt(target.dataset.candidateId, 10);
    if (!Number.isFinite(assetId)) return;

    const listKey = assetType === 'video' ? 'videos' : 'images';
    const candidates = state.sceneCandidates?.[current.id]?.[listKey] || [];
    const selected = candidates.find(item => String(item.id) === String(assetId));
    const shouldAutoplay = autoplay && assetType === 'video' && Boolean(selected?.url);
    const selectionSnapshot = shouldAutoplay
        ? captureVideoCandidateSelection(current, candidates)
        : null;

    if (shouldAutoplay) {
        applyVideoCandidateSelection(current, candidates, assetId, selected.url);
        rerender([Region.PREVIEW, Region.CANDIDATES, Region.TIMELINE_LIST], { forcePreview: true });
        const previewVideo = document.querySelector('.preview-wrapper video.preview-media');
        const playPromise = previewVideo?.play();
        if (playPromise?.catch) {
            playPromise.catch(error => {
                console.warn('主预览自动播放被浏览器拒绝，可使用原生 controls 手动播放', error);
            });
        }
    }

    try {
        await api.selectSceneAsset(current.id, assetType, assetId);
    } catch (error) {
        if (selectionSnapshot) {
            restoreVideoCandidateSelection(current, candidates, selectionSnapshot);
            rerender([Region.PREVIEW, Region.CANDIDATES, Region.TIMELINE_LIST], { forcePreview: true });
        }
        throw error;
    }

    if (!shouldAutoplay) {
        applySelectedCandidateToScene(current, assetType, assetId, selected?.url || '');
        candidates.forEach(item => {
            item.selected = String(item.id) === String(assetId);
        });
    }
    if (assetType === 'first_frame' && state.chatMode === 'video') {
        refreshSceneFirstFrameSlot(current);
    }
    pollSceneTaskStatus(current.id);
    // 候选选择：预览 + 右侧 +（视频模式时助手首帧槽）
    rerender([Region.PREVIEW, Region.CANDIDATES, Region.AGENT_PANEL, Region.TIMELINE_LIST], { forcePreview: true });
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

function pushAgentMessageForScene(sceneId, role, content, meta = {}) {
    if (!content && !meta.status) return;
    appendSceneAgentMessage(sceneId, {
        role,
        content: content || '',
        status: meta.status || '',
        createdAt: new Date().toISOString(),
    });
}

export async function loadSceneAgentMessages(sceneId, skipRerender = false) {
    if (!sceneId) {
        state.agentMessages = [];
        return;
    }
    try {
        const response = await api.fetchSceneAgentChatHistory(sceneId);
        const rows = Array.isArray(response.messages) ? response.messages : [];
        setSceneAgentMessages(sceneId, rows.map(item => ({
            role: item.role || 'assistant',
            content: typeof item.content === 'string'
                ? item.content
                : (item.content?.content || item.content?.message || ''),
            status: item.status || '',
            createdAt: item.timestamp || item.create_at || new Date().toISOString(),
        })));
        if (String(state.currentSceneId) !== String(sceneId)) return;
        // 只刷助手对话区，禁止全量 renderApp
        if (!skipRerender) rerenderAgentUi();
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

function resolveNextVideoUploadRole() {
    const items = state.videoMediaItems || [];
    if (state.videoImageMode === 'multi_reference') {
        if (!items.some(item => item.role === 'first_frame')) return 'first_frame';
        return 'reference';
    }
    if (!items.some(item => item.role === 'first_frame')) return 'first_frame';
    if (videoModelSupportsLastFrame() && !items.some(item => item.role === 'last_frame')) return 'last_frame';
    return null;
}

async function handleReferenceFileChange(input) {
    if (state.chatMode !== 'video') {
        input.value = '';
        return;
    }
    const files = Array.from(input.files || []);
    if (!files.length) return;
    for (const file of files) {
        if (!canAddVideoMedia()) {
            notify(`当前模式最多 ${getMaxVideoMediaCount()} 张图片`);
            break;
        }
        const role = resolveNextVideoUploadRole();
        if (!role) {
            notify(state.videoImageMode === 'first_last_frame'
                ? (videoModelSupportsLastFrame() ? '首尾帧已满（最多2张）' : '该模型仅支持1张首帧')
                : '参考图数量已达上限');
            break;
        }
        const tempId = `vm_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
        const item = createVideoMediaItem({
            id: tempId,
            role,
            source: 'upload',
            url: '',
            thumbnailUrl: '',
            name: file.name,
            uploading: true,
        });
        if (role === 'first_frame') {
            state.videoMediaItems = (state.videoMediaItems || []).filter(m => m.role !== 'first_frame');
            state.videoFirstFrameDismissedSceneId = null;
        }
        if (role === 'last_frame') {
            state.videoMediaItems = (state.videoMediaItems || []).filter(m => m.role !== 'last_frame');
        }
        state.videoMediaItems = [...(state.videoMediaItems || []), item];
        state.videoMediaItems.sort((a, b) => {
            const order = { first_frame: 0, last_frame: 1, reference: 2 };
            return (order[a.role] ?? 9) - (order[b.role] ?? 9);
        });
        syncReferenceImagesCompat();
        rerenderAgentPanel();
        try {
            const res = await api.uploadReferenceImage(file);
            const current = (state.videoMediaItems || []).find(r => r.id === tempId);
            if (res && res.success && res.url) {
                if (current) {
                    current.url = res.url;
                    current.thumbnailUrl = res.thumbnail_url || res.url;
                    current.uploading = false;
                }
            } else {
                state.videoMediaItems = (state.videoMediaItems || []).filter(r => r.id !== tempId);
                notify((res && res.error) || '参考图上传失败');
            }
        } catch (err) {
            state.videoMediaItems = (state.videoMediaItems || []).filter(r => r.id !== tempId);
            notify('参考图上传失败: ' + (err.message || err));
        }
        syncReferenceImagesCompat();
        rerenderAgentPanel();
    }
    // 重置以允许重复选择同一文件
    input.value = '';
}

async function sendStoryboardAgentMessage(current) {
    const streamSceneId = current.id;
    if (!streamSceneId || isSceneAgentRunning(streamSceneId)) return;
    const message = (state.inputMessage || '').trim();
    if (!message) {
        notify('请输入要调整的内容');
        return;
    }
    // 对口型分镜生成视频：必须先有成片配音（LTX 口型跟音频走）
    const isDh = String(current?.videoType || current?.video_type || '').toLowerCase() === 'digital_human';
    if (state.chatMode === 'video' && isDh) {
        const hasAudio = (current.dialogues || []).some(d => String(d.audioUrl || d.audio_url || '').trim());
        if (!hasAudio) {
            notify('对口型视频需先生成配音：请到「对话」Tab 生成角色配音后再试');
            state.activeTab = 'dialogue';
            rerender([Region.LEFT_SIDEBAR]);
            return;
        }
    }
    const llm = resolveSelectedLlmModel();
    const model = typeof llm === 'string' ? llm : (llm?.model || llm?.name || '');
    const modelId = typeof llm === 'object' ? (llm.model_id || llm.id) : null;
    const vendorId = typeof llm === 'object' ? llm.vendor_id : null;
    if (!model || !modelId) {
        notify('请先在模型配置中选择对话模型');
        state.showModelConfigModal = true;
        state.currentConfigTab = 'dialogue';
        rerenderModals();
        return;
    }

    startSceneAgentRun(streamSceneId);
    pushAgentMessageForScene(streamSceneId, 'user', message);
    state.inputMessage = '';
    // 清空输入 + running 态：只刷助手面板
    rerenderAgentPanel();

    try {
        // 视频模式：按首尾帧/全能参考组装有序槽位 URL + image_mode + 时长/分辨率/裁剪配置
        const isVideo = state.chatMode === 'video';
        const referenceImageUrls = isVideo ? buildVideoSlotUrls() : [];
        const videoExtras = isVideo ? buildVideoGenerationPayloadExtras(current) : {};
        const thinking = getThinkingParams();
        const response = await api.startSceneAgentChat(streamSceneId, {
            message,
            model,
            model_id: modelId,
            vendor_id: vendorId,
            generation_target: isVideo ? 'video' : 'image',
            image_task_id: state.selectedImageTaskId,
            video_task_id: state.selectedVideoTaskId,
            language: localStorage.getItem('zjt_locale') || 'zh-CN',
            enable_thinking: thinking.enable_thinking,
            thinking_effort: thinking.thinking_effort,
            ...(isVideo ? { image_mode: state.videoImageMode || 'first_last_frame', ...videoExtras } : {}),
            ...(referenceImageUrls.length ? { reference_image_urls: referenceImageUrls } : {}),
        });
        const streamTaskId = response.task_id;
        setSceneAgentTaskId(streamSceneId, streamTaskId);
        pushAgentMessageForScene(streamSceneId, 'status', isVideo ? '分镜视频智能体已开始处理' : '分镜图片智能体已开始处理');
        rerenderAgentUiForScene(streamSceneId);

        api.streamStoryboardAgentTask(streamTaskId, {
            onMessage: async (data) => {
                if (data.type === 'connected' || data.type === 'heartbeat') return;
                if (data.type === 'status') {
                    pushAgentMessageForScene(streamSceneId, 'status', getAgentContent(data) || data.status || '任务状态已更新');
                } else if (data.type === 'tool_call') {
                    const names = Array.isArray(data.tool_names) ? data.tool_names.join(', ') : '';
                    pushAgentMessageForScene(streamSceneId, 'status', names ? `正在调用工具：${names}` : '正在调用生成工具');
                } else if (data.type === 'image_task_submitted') {
                    const ids = data.project_ids || data.projectIds || [];
                    pushAgentMessageForScene(streamSceneId, 'status', getAgentContent(data) || '图片生成任务已提交，正在绑定到当前分镜');
                    try {
                        await bindSubmittedAgentTasks(streamSceneId, ids, 'first_frame');
                        pushAgentMessageForScene(streamSceneId, 'status', '已绑定图片生成任务，右侧资产状态会自动刷新');
                    } catch (error) {
                        pushAgentMessageForScene(streamSceneId, 'assistant', `图片任务绑定失败：${error.message || error}`);
                    }
                } else if (data.type === 'video_task_submitted') {
                    const ids = data.project_ids || data.projectIds || [];
                    pushAgentMessageForScene(streamSceneId, 'status', getAgentContent(data) || (data.already_bound
                        ? '数字人视频任务已提交，正在刷新当前分镜'
                        : '视频生成任务已提交，正在绑定到当前分镜'));
                    try {
                        if (data.already_bound) {
                            await loadSceneCandidates(streamSceneId);
                            pollSceneTaskStatus(streamSceneId);
                            pushAgentMessageForScene(streamSceneId, 'status', '数字人视频任务已关联当前分镜，右侧资产状态会自动刷新');
                        } else {
                            await bindSubmittedAgentTasks(streamSceneId, ids, 'video');
                            pushAgentMessageForScene(streamSceneId, 'status', '已绑定视频生成任务，右侧资产状态会自动刷新');
                        }
                    } catch (error) {
                        pushAgentMessageForScene(streamSceneId, 'assistant', `视频任务绑定失败：${error.message || error}`);
                    }
                } else if (data.type === 'message') {
                    pushAgentMessageForScene(streamSceneId, data.role || 'assistant', getAgentContent(data));
                } else if (data.type === 'error') {
                    pushAgentMessageForScene(streamSceneId, 'assistant', getAgentContent(data) || (isVideo ? '分镜视频智能体执行失败' : '分镜图片智能体执行失败'));
                    finishSceneAgentRun(streamSceneId, streamTaskId);
                } else if (data.type === 'done') {
                    const content = getAgentContent(data);
                    if (content) pushAgentMessageForScene(streamSceneId, 'assistant', content);
                    finishSceneAgentRun(streamSceneId, streamTaskId);
                    pollSceneTaskStatus(streamSceneId);
                    loadSceneAgentMessages(streamSceneId, true).catch(() => {});
                }
                // 流式过程只刷对话区，禁止全量 renderApp 打断预览播放
                if (data.type === 'done' || data.type === 'error') {
                    rerenderAgentPanelForScene(streamSceneId);
                } else {
                    rerenderAgentUiForScene(streamSceneId);
                }
            },
            onError: () => {
                pushAgentMessageForScene(streamSceneId, 'assistant', '任务连接中断，请稍后查看生成结果或重新发送');
                finishSceneAgentRun(streamSceneId, streamTaskId);
                rerenderAgentPanelForScene(streamSceneId);
            },
            onClose: () => {
                finishSceneAgentRun(streamSceneId, streamTaskId);
                rerenderAgentPanelForScene(streamSceneId);
            },
        });
    } catch (error) {
        pushAgentMessageForScene(streamSceneId, 'assistant', `启动智能体失败：${error.message || error}`);
        finishSceneAgentRun(streamSceneId);
        rerenderAgentPanelForScene(streamSceneId);
    }
}

async function handleAction(action, target) {
    const current = getCurrentScene();

    if (action === 'request-video-type-switch' && current) {
        if (state.videoTypeSwitch.saving) return;
        const targetType = String(target.dataset.videoType || '');
        if (!['video', 'digital_human'].includes(targetType) || targetType === current.videoType) return;
        if (targetType === 'digital_human') {
            const availability = canSwitchToDigitalHuman(current);
            if (!availability.allowed) {
                notify(availability.reason);
                return;
            }
        }
        state.videoTypeSwitch.targetType = targetType;
        state.videoTypeSwitch.previousType = current.videoType || 'video';
        rerenderModals();
        return;
    }

    if (action === 'cancel-video-type-switch') {
        if (state.videoTypeSwitch.saving) return;
        state.videoTypeSwitch.targetType = null;
        state.videoTypeSwitch.previousType = null;
        rerenderModals();
        return;
    }

    if (action === 'confirm-video-type-switch' && current) {
        if (state.videoTypeSwitch.saving) return;
        const targetType = state.videoTypeSwitch.targetType;
        const previousType = state.videoTypeSwitch.previousType || current.videoType || 'video';
        if (!targetType) return;
        state.videoTypeSwitch.saving = true;
        rerender([Region.MODAL, Region.LEFT_TAB_BODY]);
        let switched = false;
        try {
            const response = await api.switchSceneVideoType(current.id, targetType, previousType);
            applyVideoTypeSwitchResult(current, response);
            await loadSceneCandidates(current.id);
            if (state.chatMode === 'video') {
                ensureVideoImageModeSupported();
                syncVideoMediaFromScene(current, { resetUploads: false });
            }
            switched = true;
            notify(targetType === 'video' ? '已切换为视频模式' : '已切换为对口型模式');
        } catch (error) {
            notify(error?.status === 409
                ? '分镜已被其他操作修改，请刷新后重试'
                : (error.message || '切换失败，当前模式未改变'));
        } finally {
            state.videoTypeSwitch.saving = false;
            if (switched) {
                state.videoTypeSwitch.targetType = null;
                state.videoTypeSwitch.previousType = null;
            }
            rerender([
                Region.MODAL,
                Region.LEFT_TAB_BODY,
                Region.PREVIEW,
                Region.CANDIDATES,
                Region.TIMELINE_LIST,
                Region.GRID,
                Region.AGENT_PANEL,
            ], { forcePreview: true });
        }
        return;
    }

    if (action === 'auto-complete-missing-frames') {
        if (target.dataset.batchLocked === 'true' || target.getAttribute('aria-disabled') === 'true') {
            const summary = getAutoCompleteSummary();
            const count = summary.batch.totalCount || summary.missingCount || 0;
            notify(`已有 ${count} 个分镜正在排队或生成，请等待当前任务完成。`);
            return;
        }
        if (target.disabled) return;
        await autoCompleteMissingFirstFrames();
        return;
    }

    if (action === 'auto-complete-missing-videos') {
        if (target.dataset.batchLocked === 'true' || target.getAttribute('aria-disabled') === 'true') {
            notify('视频批量任务进行中，请稍候。');
            return;
        }
        if (target.disabled) return;
        try {
            await autoCompleteMissingVideos();
        } catch (error) {
            notify(error.message || '批量生成视频失败');
        }
        return;
    }

    if (action === 'generate-from-script-cancel') {
        if (state.isGeneratingFromScript) return;
        state.showGenerateFromScriptDialog = false;
        state.generateFromScriptError = '';
        rerenderModals();
        return;
    }

    if (action === 'close-generate-progress') {
        if (state.generateFromScriptTaskId) {
            stopScriptSplitTaskPolling(state.generateFromScriptTaskId);
        }
        if (generateProgressTimer) {
            clearInterval(generateProgressTimer);
            generateProgressTimer = null;
        }
        state.showGenerateProgressDialog = false;
        state.generateProgressError = '';
        rerenderModals();
        return;
    }

    if (action === 'retry-generate-progress') {
        if (state.generateFromScriptTaskId) {
            stopScriptSplitTaskPolling(state.generateFromScriptTaskId);
            // 清理本地轮询 ID；再次确认时，同配置由后端恢复原任务，配置变化则创建新任务
            state.generateFromScriptTaskId = null;
        }
        if (generateProgressTimer) {
            clearInterval(generateProgressTimer);
            generateProgressTimer = null;
        }
        state.showGenerateProgressDialog = false;
        state.generateProgressError = '';
        state.isGeneratingFromScript = false;
        state.showGenerateFromScriptDialog = true;
        rerenderModals();
        return;
    }

    if (action === 'set-auto-image-sequence-mode') {
        const mode = target.dataset.autoImageSequenceMode;
        if (!['speed', 'balanced', 'quality'].includes(mode) || state.isGeneratingFromScript) return;
        if (mode === 'quality' && state.editionInfo?.mode !== 'enterprise') {
            notify('效果模式仅商业版支持，请购买商业版后使用');
            return;
        }
        state.autoImageSequenceMode = mode;
        rerenderModals();
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
            rerenderModals();
            return;
        }
        state.isGeneratingFromScript = true;
        state.generateFromScriptError = '';
        state.showGenerateFromScriptDialog = false;
        state.showGenerateProgressDialog = true;
        state.generateProgressError = '';
        state.generateProgressPercent = 0;
        state.generateProgressMessage = '正在提交任务';
        // 进度步骤对应后端真实阶段（见设计文档 §15 状态流程）。
        // 不再用固定 5 秒 setInterval 假进度，改由轮询真实状态驱动。
        const progressSteps = [
            { name: '规划分段', status: 'pending', phase: 'planning' },
            { name: '逐段拆分', status: 'pending', phase: 'segment_generation' },
            { name: '合并校验', status: 'pending', phase: 'merging' },
            { name: '发布分镜', status: 'pending', phase: 'publishing' },
        ];
        state.generateProgressSteps = progressSteps;
        state.generateProgressStepIndex = -1;
        rerenderModals();

        // 根据后端 status/phase 更新步骤状态
        const updateStepsByStatus = (statusData) => {
            applyGenerateProgressStatus(statusData);
            const phase = statusData.phase;
            const status = statusData.status;
            const phaseToStep = { planning: 0, segment_generation: 1, replan_segment: 1, merging: 2, global_qc: 2, publishing: 3, done: 4 };
            const targetStep = phaseToStep[phase] !== undefined ? phaseToStep[phase] : (phaseToStep[status] || 0);
            progressSteps.forEach((s, i) => {
                if (status === 'completed') {
                    s.status = 'completed';
                } else if (i < targetStep) {
                    s.status = 'completed';
                } else if (i === targetStep) {
                    s.status = 'running';
                } else {
                    s.status = 'pending';
                }
            });
            state.generateProgressStepIndex = Math.min(targetStep, progressSteps.length - 1);
            rerenderModals();
        };

        try {
            const thinking = getThinkingParams();
            const submitResp = await api.generateFromScript(state.storyboardId, {
                max_group_duration: state.maxGroupDuration || 15,
                force_medium_shot: state.forceMediumShot !== false,
                no_bg_music: state.noBgMusic !== false,
                split_multi_dialogue: state.splitMultiDialogue === true,
                model: splitModel.model,
                model_id: splitModel.model_id,
                vendor_id: splitModel.vendor_id,
                enable_thinking: thinking.enable_thinking,
                thinking_effort: thinking.thinking_effort,
                enable_script_split_qc: state.enableScriptSplitQc === true,
                script_split_qc_max_rounds: Number(state.scriptSplitQcMaxRounds) || 2,
                sequence_mode: state.autoImageSequenceMode,
            });
            // 后端返回 202 + { data: { task_id, status, status_url } }
            const taskId = (submitResp && submitResp.data && submitResp.data.task_id) || submitResp.task_id;
            if (!taskId) {
                throw new Error('未返回任务 ID');
            }
            state.generateFromScriptTaskId = taskId;

            pollScriptSplitTask(taskId, {
                onUpdate: (statusData) => {
                    updateStepsByStatus(statusData);
                },
                onComplete: async (_result, _statusData) => {
                    progressSteps.forEach(s => s.status = 'completed');
                    state.generateProgressStepIndex = progressSteps.length;
                    rerenderModals();
                    // 发布由 worker 完成，这里重新加载故事板拿到已创建的分镜
                    try {
                        const sbResp = await api.getStoryboard(state.storyboardId);
                        loadStoryboardData(sbResp);
                    } catch (e) { /* ignore */ }
                    state.showGenerateProgressDialog = false;
                    state.isGeneratingFromScript = false;
                    resetAutoMissingImagesFlag(state.storyboardId);
                    autoGenerateMissingFirstFrames();
                    const generatedMessage = `已生成 ${state.scenes.length} 个分镜`;
                    notify(generatedMessage);
                    rerender('all', { forcePreview: true });
                },
                onPaused: (statusData) => {
                    state.generateProgressError = statusData.message || '任务暂停，请刷新页面后继续';
                    state.isGeneratingFromScript = false;
                    rerenderModals();
                },
                onError: (error) => {
                    const idx = state.generateProgressStepIndex;
                    if (idx >= 0 && idx < progressSteps.length) {
                        progressSteps[idx].status = 'failed';
                    }
                    state.generateProgressError = error.message || '生成分镜失败';
                    state.isGeneratingFromScript = false;
                    rerenderModals();
                },
            });
        } catch (error) {
            const idx = state.generateProgressStepIndex;
            if (idx >= 0 && idx < progressSteps.length) {
                progressSteps[idx].status = 'failed';
            }
            state.generateProgressError = error.message || '生成分镜失败';
            state.isGeneratingFromScript = false;
            rerenderModals();
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
        // 结构变化：只重建 timeline/grid list，不拆 preview
        rerender(REGIONS_ON_SCENE_STRUCT, { forcePreview: true });
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
        rerender(REGIONS_ON_SCENE_STRUCT, { forcePreview: true });
        return;
    }

    if (action === 'duplicate-scene') {
        const response = await api.duplicateScene(parseInt(target.dataset.id, 10));
        addSceneToState(response.scene);
        rerender(REGIONS_ON_SCENE_STRUCT, { forcePreview: true });
        return;
    }

    if (action === 'delete-scene') {
        const sceneId = parseInt(target.dataset.id, 10);
        if (!window.confirm('确定删除这个分镜吗？')) return;
        stopPlayback();
        await api.deleteScene(sceneId);
        removeSceneFromState(sceneId);
        if (state.scenes.length === 0) {
            state.showGenerateFromScriptDialog = true;
            state.generateFromScriptError = '';
            rerender([...REGIONS_ON_SCENE_STRUCT, Region.MODAL], { forcePreview: true });
            return;
        }
        rerender(REGIONS_ON_SCENE_STRUCT, { forcePreview: true });
        return;
    }

    if (action === 'toggle-view') {
        stopPlayback();
        state.viewMode = state.viewMode === 'grid' ? 'timeline' : 'grid';
        rerender([Region.CENTER], { forcePreview: true });
        // Grid 返回时间轴后，中栏刚重建，需等布局稳定再将当前选中分镜滚入可见区。
        // 复用点击/键盘切镜的双 rAF，避免 26 等靠后分镜仍停留在时间轴右端。
        const targetSceneId = state.currentSceneId;
        if (state.viewMode === 'timeline' && targetSceneId != null) {
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    if (state.viewMode === 'timeline' && state.currentSceneId === targetSceneId) {
                        scrollTimelineToScene(targetSceneId);
                    }
                });
            });
        }
        await persistUiConfig();
        return;
    }

    if (action === 'toggle-play') {
        togglePlayback();
        return;
    }

    if (action === 'toggle-episode-picker') {
        state.showEpisodePicker = !state.showEpisodePicker;
        rerender([Region.HEADER]);
        if (state.showEpisodePicker) {
            ensureEpisodeFoldersLoaded().catch((e) => notify(e.message || '加载集列表失败'));
        }
        return;
    }

    if (action === 'switch-episode') {
        const ep = parseInt(target.dataset.episode, 10);
        if (!Number.isFinite(ep) || ep < 1) return;
        const scriptRaw = target.dataset.scriptId;
        const sbRaw = target.dataset.storyboardId;
        navigateToEpisode(ep, {
            scriptId: scriptRaw ? parseInt(scriptRaw, 10) : null,
            storyboardId: sbRaw ? parseInt(sbRaw, 10) : null,
        });
        return;
    }

    if (action === 'switch-episode-custom') {
        const input = document.querySelector('[data-episode-custom-input]');
        const ep = parseInt(input?.value, 10);
        if (!Number.isFinite(ep) || ep < 1) {
            notify('请输入有效的集数（正整数）');
            return;
        }
        // 自定义集：若列表中已有则带上 script/storyboard，否则纯新建
        const folder = (state.episodeFolders || []).find(f => Number(f.episode_number) === ep);
        navigateToEpisode(ep, {
            scriptId: folder?.script_id ? Number(folder.script_id) : null,
            storyboardId: folder?.storyboard_id ? Number(folder.storyboard_id) : null,
        });
        return;
    }

    if (action === 'toggle-subtitle') {
        state.subtitleEnabled = target.checked;
        // 播放中仅切换字幕层可见性，不 rerender
        const sub = document.querySelector('.preview-subtitle');
        if (sub) {
            if (!state.subtitleEnabled) {
                sub.hidden = true;
            } else if (state.playback?.audioDialogueId != null && sub.textContent) {
                sub.hidden = false;
            }
        }
        await persistUiConfig();
        return;
    }

    if (
        action === 'toggle-force-medium-shot'
        || action === 'toggle-no-bg-music'
        || action === 'toggle-split-multi-dialogue'
        || action === 'toggle-enable-script-split-qc'
    ) {
        if (state.isGeneratingFromScript) return;
        // click 路径有 preventDefault，checkbox 状态不可靠，按当前 state 翻转
        if (action === 'toggle-force-medium-shot') state.forceMediumShot = !state.forceMediumShot;
        else if (action === 'toggle-no-bg-music') state.noBgMusic = !state.noBgMusic;
        else if (action === 'toggle-split-multi-dialogue') state.splitMultiDialogue = !state.splitMultiDialogue;
        else state.enableScriptSplitQc = !state.enableScriptSplitQc;
        await persistUiConfig();
        rerenderModals();
        return;
    }

    if (action === 'toggle-ai') {
        state.aiOptimize = !state.aiOptimize;
        rerenderAgentPanel();
        await persistUiConfig();
        return;
    }

    if (action === 'close-model-config') {
        state.showModelConfigModal = false;
        rerenderModals();
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
        notify('画面提示词已保存');
        // 数据已在表单中，无需拆左栏；标题可能影响预览 caption
        rerender([Region.PREVIEW, Region.TIMELINE_LIST]);
        return;
    }

    if (action === 'save-scene' && current) {
        const titleEl = document.querySelector('[data-scene-field="title"]');
        const videoPromptEl = document.querySelector('[data-scene-field="videoPrompt"]');
        if (titleEl) current.title = titleEl.value;
        if (videoPromptEl) current.videoPrompt = videoPromptEl.value;
        await api.updateScene(current.id, sceneToUpdatePayload(current));
        notify('分镜已保存');
        rerender([Region.LEFT_TAB_BODY, Region.SCENE_CHROME, Region.PREVIEW, Region.TIMELINE_LIST, Region.GRID]);
        return;
    }

    if (action === 'select-character-reference' && current) {
        openReferenceVariantSelector({
            type: 'character',
            sceneId: current.id,
            characterId: target.dataset.characterId || '',
            characterName: target.dataset.characterName || target.textContent || '',
            anchor: target,
            notify,
        });
        return;
    }

    if (action === 'select-location-reference') {
        const sceneId = parseInt(target.dataset.sceneId || target.closest('[data-scene-id]')?.dataset.sceneId, 10);
        openReferenceVariantSelector({
            type: 'location',
            sceneId,
            locationId: target.dataset.locationId || '',
            anchor: target,
            notify,
            openLocationSwitcher: showLocationDropdown,
        });
        return;
    }

    if (action === 'switch-location' || action === 'add-prop' || action === 'remove-location' || action === 'remove-prop') {
        const sceneId = parseInt(target.dataset.sceneId || target.closest('[data-scene-id]')?.dataset.sceneId, 10);
        const sc = state.scenes.find(s => s.id === sceneId);
        if (!sc) return;

        if (action === 'remove-location') {
            sc.location = null;
            clearLocationReferenceSelection(sc);
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
        rerender([Region.LEFT_TAB_BODY]);
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
        rerender([Region.LEFT_TAB_BODY]);
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
        rerenderModals();
        return;
    }

    // add-reference-image 已在 bindEvents 顶部同步处理（保证文件选择器手势），此处兜底
    if (action === 'add-reference-image') {
        if (state.chatMode !== 'video') return;
        if (!canAddVideoMedia()) {
            notify(`当前模式最多 ${getMaxVideoMediaCount()} 张图片`);
            return;
        }
        const fileInput = document.getElementById('reference-file-input');
        if (fileInput) fileInput.click();
        return;
    }

    if (action === 'remove-reference-image' || action === 'remove-video-media') {
        const refId = target.getAttribute('data-video-media-id') || target.getAttribute('data-reference-id');
        if (refId) {
            const removed = (state.videoMediaItems || []).find(r => String(r.id) === String(refId));
            state.videoMediaItems = (state.videoMediaItems || []).filter(r => String(r.id) !== String(refId));
            if (removed?.role === 'first_frame') {
                const scene = getCurrentScene();
                state.videoFirstFrameDismissedSceneId = scene?.id ?? null;
            }
            syncReferenceImagesCompat();
            rerenderAgentPanel();
        }
        return;
    }

    if (action === 'restore-scene-first-frame') {
        const scene = getCurrentScene();
        if (!scene) return;
        state.videoFirstFrameDismissedSceneId = null;
        refreshSceneFirstFrameSlot(scene);
        if (!(state.videoMediaItems || []).some(item => item.role === 'first_frame')) {
            syncVideoMediaFromScene(scene, { resetUploads: false });
        }
        rerenderAgentPanel();
        return;
    }

    if (action === 'toggle-video-mode-panel') {
        if (isSceneAgentRunning(current?.id)) return;
        state.showVideoModePanel = !state.showVideoModePanel;
        rerenderAgentPanel();
        return;
    }

    if (action === 'toggle-agent-chat-history') {
        state.agentChatHistoryOpen = !(state.agentChatHistoryOpen !== false);
        rerenderAgentPanel();
        return;
    }

    if (action === 'agent-chat-font-up' || action === 'agent-chat-font-down') {
        const delta = action === 'agent-chat-font-up' ? 1 : -1;
        setAgentChatFontStep((state.agentChatFontStep || 0) + delta);
        // 固定展开态：避免局部刷新丢失 hover 后 textarea 缩回、按钮位置跳动
        state.agentChatLogPinned = true;
        rerenderAgentPanel();
        requestAnimationFrame(() => {
            const btn = document.querySelector(`.ai-chat-section [data-action="${action}"]:not([disabled])`)
                || document.querySelector(`.ai-chat-section [data-action="${action}"]`);
            if (btn && typeof btn.focus === 'function') btn.focus({ preventScroll: true });
        });
        return;
    }

    if (action === 'toggle-media-stack') {
        // 删除/上传按钮自带更具体的 data-action，closest 会优先命中它们，不会进入本分支
        state.mediaStackExpanded = !state.mediaStackExpanded;
        rerenderAgentPanel();
        return;
    }

    if (action === 'toggle-agent-message-expand') {
        const key = target.getAttribute('data-message-key');
        if (!key) return;
        const map = { ...(state.expandedAgentMessageIds || {}) };
        if (map[key]) {
            delete map[key];
        } else {
            map[key] = true;
        }
        // pin 住浮层，避免刷新后丢失 :hover
        state.agentChatLogPinned = true;
        state.expandedAgentMessageIds = map;
        rerenderAgentUi();
        requestAnimationFrame(() => {
            const log = document.querySelector('.agent-chat-log');
            if (!log) return;
            const safe = (window.CSS && typeof CSS.escape === 'function')
                ? CSS.escape(key)
                : String(key).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
            const row = log.querySelector(`[data-message-key="${safe}"]`);
            if (row) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            if (map[key]) log.scrollTop = Math.min(log.scrollHeight, row ? row.offsetTop : log.scrollHeight);
        });
        return;
    }

    if (action === 'set-video-image-mode') {
        if (isSceneAgentRunning(current?.id)) return;
        const mode = target.dataset.videoImageMode;
        const supported = getSupportedVideoImageModes();
        if (!supported.includes(mode)) return;
        state.videoImageMode = mode;
        state.showVideoModePanel = false;
        syncVideoMediaFromScene(getCurrentScene(), { resetUploads: false });
        await persistUiConfig();
        rerenderAgentPanel();
        return;
    }

    if (action === 'set-video-resolution') {
        const res = target.dataset.videoResolution;
        if (!res) return;
        state.videoResolution = res;
        // 选中态位于 modal 内：先即时刷新弹窗，再异步持久化，避免点击后仍显示旧分辨率。
        rerender([Region.MODAL, Region.AGENT_PANEL]);
        await persistUiConfig();
        return;
    }

    if (action === 'toggle-clip-to-audio') {
        // click 监听里对 action 做了 preventDefault，checkbox 不会自动翻转，这里手动取反
        state.clipToAudioDuration = !state.clipToAudioDuration;
        await persistUiConfig();
        rerenderAgentPanel();
        return;
    }

    if (action === 'toggle-audio-embedded') {
        // 分镜级「声音同出」开关：开启后导出完整视频时保留视频原声、跳过 TTS 混音。
        // click 路径上有 preventDefault，checkbox 原生翻转被取消，需按 scene 翻转后局部刷新。
        const scene = getCurrentScene();
        if (!scene) return;
        scene.audioEmbedded = !scene.audioEmbedded;
        try {
            await api.updateScene(scene.id, { audio_embedded: scene.audioEmbedded ? 1 : 0 });
        } catch (e) {
            // 回滚翻转，避免 UI 与后端不一致
            scene.audioEmbedded = !scene.audioEmbedded;
        }
        rerender([Region.LEFT_SIDEBAR]);
        return;
    }

    if (action === 'open-model-config') {
        state.showModelConfigModal = true;
        // 默认根据当前助手模式
        const mode = state.chatMode;
        state.currentConfigTab = mode === 'video' ? 'video' : 'dialogue';
        rerenderModals();
        return;
    }

    // 画风/构图全局编辑已移至 header .header-style-info 点击（data-action=edit-global-style）

    if (action === 'send-ai') {
        if (!current) return;
        await sendStoryboardAgentMessage(current);
        // send 内部已 refresh agent 面板
        return;
    }

    if (action === 'open-export') {
        state.showExportDialog = true;
        rerenderModals();
        return;
    }

    if (action === 'close-export') {
        state.showExportDialog = false;
        rerenderModals();
        return;
    }

    if (action === 'open-power-logs') {
        if (!state.authToken && !localStorage.getItem('auth_token')) {
            notify('请先登录后再查看算力日志');
            return;
        }
        state.showPowerLogsModal = true;
        rerenderModals();
        return;
    }

    if (action === 'close-power-logs') {
        state.showPowerLogsModal = false;
        try {
            const power = await api.fetchComputingPower();
            state.computingPower = power.computing_power ?? power.balance ?? state.computingPower;
        } catch (_) { /* ignore */ }
        rerender([Region.MODAL, Region.HEADER_POWER]);
        return;
    }

    if (action === 'open-recharge') {
        await openRechargeModal();
        return;
    }

    if (action === 'close-recharge') {
        resetRechargeState();
        rerenderModals();
        return;
    }

    if (action === 'select-recharge-package') {
        const packageId = target.dataset.packageId;
        if (!packageId) return;
        const pkg = (state.rechargePackages || []).find(
            (item) => String(item.package_id) === String(packageId)
        ) || {
            package_id: packageId,
            description: target.dataset.packageDesc || '',
            computing_power: Number(target.dataset.packagePower) || 0,
            price: Number(target.dataset.packagePrice) || 0,
        };
        await selectRechargePackage(pkg);
        return;
    }

    if (action === 'back-to-recharge-packages' || action === 'retry-recharge-packages') {
        await loadRechargePackages();
        return;
    }

    if (action === 'toggle-export-burn-subtitles') {
        // click 路径上有 preventDefault，checkbox 原生切换会被取消；
        // 不能读 target.checked（仍是旧值），需按 state 翻转后只刷 modal
        state.exportBurnSubtitles = !state.exportBurnSubtitles;
        rerenderModals();
        return;
    }

    if (action === 'toggle-enable-thinking' || action === 'toggle-enable-thinking-label') {
        // click 路径上有 preventDefault，checkbox 默认勾选可能被取消，统一按 state 翻转
        state.enableThinking = !state.enableThinking;
        saveThinkingStateToStorage(true);
        rerenderModals();
        return;
    }

    if (action === 'export-full') {
        try {
            const response = await api.exportFullVideo(state.storyboardId, {
                include_subtitles: state.exportBurnSubtitles !== false,
            });
            if (!response.success && response.error) {
                notify(response.error);
                return;
            }
            const jobId = response.job_id;
            if (!jobId) {
                notify(response.error || '导出任务提交失败');
                return;
            }
            state.showExportDialog = false;
            rerenderModals();
            notify('完整视频导出任务已提交，正在合成并上传…');
            // 轮询 job → CDN 链接下载（对齐剧本世界导出：不走本站带宽）
            const deadline = Date.now() + 30 * 60 * 1000;
            while (Date.now() < deadline) {
                await new Promise(r => setTimeout(r, 2000));
                const job = await api.getExportJob(jobId);
                if (job.status === 'completed' && job.download_url) {
                    const a = document.createElement('a');
                    a.href = job.download_url;
                    a.download = job.filename || 'storyboard_full.mp4';
                    a.target = '_blank';
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    notify('完整视频已生成，已打开下载链接');
                    return;
                }
                if (job.status === 'failed') {
                    notify(job.error || '完整视频导出失败');
                    return;
                }
            }
            notify('导出超时，请稍后重试或联系管理员');
        } catch (e) {
            notify(e.message || '完整视频导出失败');
        }
        return;
    }

    if (action === 'export-scenes') {
        try {
            notify('正在打包素材并上传图床…');
            const response = await api.exportAllScenes(state.storyboardId);
            if (!response.success || !response.download_url) {
                notify(response.error || '素材包导出失败');
                return;
            }
            const a = document.createElement('a');
            a.href = response.download_url;
            a.download = response.filename || 'storyboard_assets.zip';
            a.target = '_blank';
            document.body.appendChild(a);
            a.click();
            a.remove();
            state.showExportDialog = false;
            rerenderModals();
            notify('素材包导出成功，已打开图床下载链接');
        } catch (e) {
            notify(e.message || '素材包导出失败');
        }
        return;
    }

    if (action === 'placeholder') {
        notify('该能力正在接入中');
    }

    if (action === 'edit-global-style') {
        state.showGlobalStyleDialog = true;
        rerenderModals();
        return;
    }

    if (action === 'close-global-style') {
        state.showGlobalStyleDialog = false;
        rerenderModals();
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
            rerender([Region.MODAL, Region.HEADER]);
            notify('画风和构图倾向已更新');
        } catch (e) {
            notify('更新失败: ' + (e.message || e));
        }
        return;
    }

    if (action === 'edit-scene') {
        state.sceneEditTargetId = parseInt(target.dataset.id, 10);
        state.sceneEditError = '';
        state.sceneEditSaving = false;
        state.showSceneEditDialog = true;
        rerenderModals();
        return;
    }

    if (action === 'close-scene-edit') {
        state.showSceneEditDialog = false;
        state.sceneEditTargetId = null;
        state.sceneEditError = '';
        state.sceneEditSaving = false;
        rerenderModals();
        return;
    }

    if (action === 'save-scene-edit') {
        const sceneId = state.sceneEditTargetId;
        const scene = state.scenes.find(s => s.id === sceneId);
        if (!scene) return;
        const titleEl = document.querySelector('[data-scene-edit-field="title"]');
        const durEl = document.querySelector('[data-scene-edit-field="duration"]');
        const diffEl = document.querySelector('[data-scene-edit-field="difficulty"]');
        const actEl = document.querySelector('[data-scene-edit-field="act_name"]');
        const newTitle = titleEl ? titleEl.value.trim() : (scene.title || '');
        const newDuration = durEl ? parseFloat(durEl.value) : scene.duration;
        const newDifficulty = diffEl ? diffEl.value : (scene.difficulty || '');
        const newActName = actEl ? actEl.value.trim() : (scene.actName || '');
        // 时长校验（非数字或负数）
        if (!Number.isFinite(newDuration) || newDuration < 0) {
            state.sceneEditError = '时长必须为非负数字';
            rerenderModals();
            return;
        }
        state.sceneEditSaving = true;
        rerenderModals(); // 禁用按钮并显示「保存中…」
        try {
            await api.updateScene(sceneId, {
                title: newTitle,
                duration: newDuration,
                difficulty: newDifficulty,
                act_name: newActName,
            });
            // 写回本地 state
            scene.title = newTitle;
            scene.duration = newDuration;
            scene.difficulty = newDifficulty;
            scene.actName = newActName;
            // 关闭弹框 + 刷新 grid 卡片（CENTER 在 grid 视图含卡片网格）
            state.showSceneEditDialog = false;
            state.sceneEditTargetId = null;
            state.sceneEditError = '';
            rerender([Region.MODAL, Region.CENTER], { forcePreview: true });
            notify('分镜已更新');
        } catch (e) {
            state.sceneEditSaving = false;
            state.sceneEditError = e.message || String(e);
            rerenderModals();
        } finally {
            state.sceneEditSaving = false;
        }
        return;
    }
}

/**
 * 加载当前世界下的集列表（剧本 + 故事板 folders）
 */
async function ensureEpisodeFoldersLoaded(force = false) {
    if (!state.worldId) return;
    if (!force && state.episodeFoldersLoaded) return;
    if (state.episodeFoldersLoading) return;
    state.episodeFoldersLoading = true;
    try {
        const folders = await api.listStoryboardFolders(state.worldId);
        // 只保留当前世界
        state.episodeFolders = (folders || []).filter(
            f => !state.worldId || Number(f.world_id) === Number(state.worldId)
        );
        state.episodeFoldersLoaded = true;
        if (state.showEpisodePicker) rerender([Region.HEADER]);
    } finally {
        state.episodeFoldersLoading = false;
    }
}

/**
 * 跳转到指定集。无故事板时不传 id，由 bootstrap create get-or-create 新建。
 */
function navigateToEpisode(episodeNumber, options = {}) {
    const ep = parseInt(episodeNumber, 10);
    if (!Number.isFinite(ep) || ep < 1) {
        notify('集数无效');
        return;
    }
    if (ep === Number(state.episodeNumber) && !options.force) {
        state.showEpisodePicker = false;
        rerender([Region.HEADER]);
        return;
    }
    if (!state.worldId) {
        notify('缺少 world_id，无法切换集数');
        return;
    }

    stopPlayback();
    const params = new URLSearchParams();
    params.set('world_id', String(state.worldId));
    params.set('episode_number', String(ep));
    // 有故事板 id 时直接打开；没有则不传 id，进入页会 POST /create 幂等创建
    if (options.storyboardId) {
        params.set('id', String(options.storyboardId));
    }
    if (options.scriptId) {
        params.set('script_id', String(options.scriptId));
    }
    if (state.workflowId) {
        params.set('workflow_id', String(state.workflowId));
    }
    if (state.userId) {
        params.set('user_id', String(state.userId));
    }
    window.location.href = `/storyboard?${params.toString()}`;
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
    // 鼠标离开分镜助手区：解除浮层 pin，恢复「移出渐隐」
    document.addEventListener('mouseout', (event) => {
        const section = event.target?.closest?.('.ai-chat-section');
        if (!section) return;
        const related = event.relatedTarget;
        // related 为 null 常见于 rerender 拆 DOM 或离开窗口，不能当成「移出助手区」
        if (!related || !(related instanceof Node)) return;
        if (section.contains(related)) return;
        if (!state.agentChatLogPinned) return;
        state.agentChatLogPinned = false;
        section.classList.remove('is-chat-log-pinned');
    });

    document.addEventListener('click', async (event) => {
        // 集数切换面板：点外部关闭
        if (state.showEpisodePicker && !event.target.closest('[data-episode-switcher]')) {
            state.showEpisodePicker = false;
            rerender([Region.HEADER]);
            // 继续处理本次点击（例如点到分镜）
        }

        // 上传参考图：必须在同步用户手势内触发 fileInput.click()，
        // 且 stopPropagation，避免父级 toggle-media-stack + preventDefault 吞掉点击
        const addRefTarget = event.target.closest('[data-action="add-reference-image"]');
        if (addRefTarget) {
            event.preventDefault();
            event.stopPropagation();
            if (addRefTarget.disabled || addRefTarget.getAttribute('aria-disabled') === 'true') return;
            if (state.chatMode !== 'video') return;
            if (!canAddVideoMedia()) {
                notify(`当前模式最多 ${getMaxVideoMediaCount()} 张图片`);
                return;
            }
            const fileInput = document.getElementById('reference-file-input');
            if (fileInput) fileInput.click();
            return;
        }

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
            const candidatePlayTarget = event.target.closest('[data-candidate-play]');
            try {
                await selectSceneCandidate(candidateTarget, {
                    autoplay: Boolean(
                        candidatePlayTarget
                        && candidateTarget.dataset.candidateType === 'video'
                    ),
                });
            } catch (error) {
                notify(error.message || '选择候选图失败');
            }
            return;
        }

        if (sceneTarget && !actionTarget) {
            const sceneId = parseInt(sceneTarget.dataset.scene, 10);
            stopPlayback();
            state.currentSceneId = sceneId;
            // 选中 = 播放起点：对齐时间轴偏移，并清除 ended，避免再点播放从片头重来
            syncSelectionToTimeline(sceneId);
            activateSceneAgentMessages(sceneId);
            state.referenceImages = [];
            state.showVideoModePanel = false;
            state.mediaStackExpanded = false;
            state.expandedAgentMessageIds = {};
            const scene = state.scenes.find(s => s.id === sceneId) || null;
            if (state.chatMode === 'video') {
                ensureVideoImageModeSupported();
                syncVideoMediaFromScene(scene, { resetUploads: true });
            } else {
                state.videoMediaItems = [];
                state.videoFirstFrameDismissedSceneId = null;
            }
            // 分区刷新：左栏+预览+候选+时间轴，禁止整页 renderApp
            rerender(REGIONS_ON_SCENE_CHANGE, { forcePreview: true });
            // 布局稳定后滚到当前缩略图（点击切镜与键盘一致）
            requestAnimationFrame(() => {
                requestAnimationFrame(() => scrollTimelineToScene(sceneId));
            });
            // 异步加载该 scene 的候选资产
            (async () => {
                try {
                    const historyPromise = loadSceneAgentMessages(sceneId, true).catch(() => {});
                    await loadSceneCandidates(sceneId);
                    await historyPromise;
                    if (state.chatMode === 'video' && state.currentSceneId === sceneId) {
                        refreshSceneFirstFrameSlot(getCurrentScene());
                    }
                    if (state.currentSceneId !== sceneId) return;
                    rerender([Region.CANDIDATES, Region.AGENT_PANEL, Region.PREVIEW], { forcePreview: true });
                } catch (e) {
                    // 静默失败，不影响主流程
                }
            })();
            return;
        }

        // 点击空白关闭视频模式面板
        if (state.showVideoModePanel && !event.target.closest('[data-video-mode-panel]') && !event.target.closest('[data-action="toggle-video-mode-panel"]')) {
            state.showVideoModePanel = false;
            if (!actionTarget && !sceneTarget) {
                rerenderAgentPanel();
                return;
            }
        }

        // 点击媒体栈外部时收起展开态
        if (state.mediaStackExpanded && !event.target.closest('.media-stack')) {
            state.mediaStackExpanded = false;
            if (!actionTarget && !sceneTarget) {
                rerenderAgentPanel();
                return;
            }
            // 有其它 action 时只改状态，后续 handler 会 refresh
        }

        // Handle model config tabs (must be before action guard since tabs have no data-action)
        const configTabTarget = event.target.closest('[data-config-tab]');
        if (configTabTarget) {
            const tab = configTabTarget.dataset.configTab;
            state.currentConfigTab = tab;
            rerenderModals();
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
        // 集数自定义输入：Enter 进入
        if (event.key === 'Enter' && target && target.matches && target.matches('[data-episode-custom-input]')) {
            event.preventDefault();
            const btn = document.querySelector('[data-action="switch-episode-custom"]');
            if (btn) btn.click();
            return;
        }
        if (event.key === 'Escape' && state.showEpisodePicker) {
            state.showEpisodePicker = false;
            rerender([Region.HEADER]);
            return;
        }
        // 在输入框/可编辑区时不抢左右键
        const tag = (event.target && event.target.tagName) ? String(event.target.tagName).toUpperCase() : '';
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || event.target?.isContentEditable) {
            return;
        }
        // 悬停时间轴，或焦点不在表单时允许全局左右切镜
        if (!isTimelineHovered && event.target?.closest?.('.left-sidebar, .right-sidebar, .modal-overlay, .ai-chat-section')) {
            return;
        }
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        if (!state.scenes.length) return;

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
        stopPlayback();
        const nextScene = state.scenes[newIndex];
        state.currentSceneId = nextScene.id;
        syncSelectionToTimeline(state.currentSceneId);
        activateSceneAgentMessages(nextScene.id);
        state.referenceImages = [];
        state.showVideoModePanel = false;
        state.mediaStackExpanded = false;
        state.expandedAgentMessageIds = {};
        if (state.chatMode === 'video') {
            ensureVideoImageModeSupported();
            syncVideoMediaFromScene(nextScene, { resetUploads: true });
        } else {
            state.videoMediaItems = [];
            state.videoFirstFrameDismissedSceneId = null;
        }
        rerender(REGIONS_ON_SCENE_CHANGE, { forcePreview: true });

        // 双 rAF：等区域 patch 完成布局后再滚，避免 scrollLeft 算错 / 不滚动
        const targetId = nextScene.id;
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                scrollTimelineToScene(targetId);
            });
        });
        loadSceneAgentMessages(targetId, true).then(() => {
            rerenderAgentPanelForScene(targetId);
        }).catch(() => {});
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
            state.showVideoModePanel = false;
            if (state.chatMode === 'video') {
                ensureVideoImageModeSupported();
                syncVideoMediaFromScene(getCurrentScene(), { resetUploads: true });
            } else {
                state.videoMediaItems = [];
                state.videoFirstFrameDismissedSceneId = null;
                state.referenceImages = [];
            }
            rerenderAgentPanel();
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
                applyThinkingDefaultsForModel(state.selectedLlmModel);
                saveThinkingStateToStorage(false);
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
                applyThinkingDefaultsForModel(state.selectedScriptSplitLlmModel || state.selectedLlmModel);
                saveThinkingStateToStorage(false);
                try {
                    localStorage.setItem('storyboard_lastScriptSplitLlmModel', JSON.stringify(state.selectedScriptSplitLlmModel));
                } catch {}
            } else if (type === 'thinkingEffort') {
                if (['low', 'medium', 'high'].includes(val)) {
                    state.thinkingEffort = val;
                    saveThinkingStateToStorage(false);
                }
            } else if (type === 'scriptSplitQcMaxRounds') {
                const n = parseInt(val, 10);
                if (Number.isFinite(n) && n >= 1 && n <= 5) {
                    state.scriptSplitQcMaxRounds = n;
                }
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
                ensureVideoImageModeSupported();
                ensureVideoGenerationPrefsSupported();
                if (state.chatMode === 'video') {
                    syncVideoMediaFromScene(getCurrentScene(), { resetUploads: false });
                }
            } else if (type === 'videoDuration') {
                if (val === 'auto') {
                    state.videoDurationMode = 'auto';
                } else {
                    const n = parseInt(val, 10);
                    state.videoDurationMode = Number.isFinite(n) ? n : 'auto';
                }
            } else if (type === 'maxGroupDuration') {
                const d = parseInt(val, 10);
                if ([5, 8, 10, 15].includes(d)) state.maxGroupDuration = d;
            }

            // 模型配置在弹层内：只刷 modal；视频相关可能影响助手槽位
            if (type === 'video' || type === 'videoDuration') {
                rerender([Region.MODAL, Region.AGENT_PANEL]);
            } else {
                rerenderModals();
            }
            if (state.storyboardId) {
                persistUiConfig().catch(() => {});
            }
            return;
        }

        if (target.dataset.configTab) {
            const tab = target.dataset.configTab;
            state.currentConfigTab = tab;
            rerenderModals();
            return;
        }
        // 画风/构图编辑入口已改为 header 点击（data-action="edit-global-style"）
    });

    document.addEventListener('click', (event) => {
        const overlay = event.target.closest('.modal-overlay');
        if (overlay && event.target === overlay) {
            if (state.generateFromScriptTaskId) {
                stopScriptSplitTaskPolling(state.generateFromScriptTaskId);
            }
            if (generateProgressTimer) {
                clearInterval(generateProgressTimer);
                generateProgressTimer = null;
            }
            const modalKind = overlay.dataset.modal || '';
            if (modalKind === 'video-type-switch') {
                if (state.videoTypeSwitch.saving) return;
                state.videoTypeSwitch.targetType = null;
                state.videoTypeSwitch.previousType = null;
                rerenderModals();
                return;
            }
            // 充值弹窗叠在日志上：点遮罩只关充值
            if (modalKind === 'recharge' || state.showRechargeModal) {
                resetRechargeState();
                rerenderModals();
                return;
            }
            if (modalKind === 'power-logs' || state.showPowerLogsModal) {
                state.showPowerLogsModal = false;
                api.fetchComputingPower().then((power) => {
                    state.computingPower = power.computing_power ?? power.balance ?? state.computingPower;
                    rerender([Region.MODAL, Region.HEADER_POWER]);
                }).catch(() => rerenderModals());
                return;
            }
            state.showModelConfigModal = false;
            state.showExportDialog = false;
            state.showGlobalStyleDialog = false;
            state.showSceneEditDialog = false;
            state.sceneEditTargetId = null;
            state.sceneEditError = '';
            state.showGenerateFromScriptDialog = false;
            state.showGenerateProgressDialog = false;
            rerenderModals();
            return;
        }

        const tab = event.target.closest('[data-tab]');
        if (tab) {
            state.activeTab = tab.dataset.tab;
            // 只刷工作台 Tab 体，不碰助手与主预览
            rerender([Region.LEFT_TABS, Region.LEFT_TAB_BODY]);
            persistUiConfig();
        }

        // @ 角色/场景/道具选择框：点击框外自动隐藏（点 @ 按钮本身仍走 toggle）
        if (state.showMentionPopup) {
            const inPopup = event.target.closest('.mention-popup');
            const onMentionBtn = event.target.closest('[data-action="mention"]');
            if (!inPopup && !onMentionBtn) {
                state.showMentionPopup = false;
                rerenderModals();
                // 继续处理其它点击（如切分镜），不 return
            }
        }

        const mentionTab = event.target.closest('[data-mention-tab]');
        if (mentionTab) {
            state.mentionTab = mentionTab.dataset.mentionTab;
            rerenderModals();
            return;
        }

        const mentionItem = event.target.closest('[data-mention-item]');
        if (mentionItem) {
            state.inputMessage = `${state.inputMessage || ''}@${mentionItem.dataset.mentionItem} `;
            state.showMentionPopup = false;
            rerender([Region.MODAL, Region.AGENT_PANEL]);
            return;
        }

        // 提示词框点击切换为编辑 (直接在左侧，角色图片以 <img>角色名 格式内联在内容中)
        // 参考 video_workflow.html 分镜节点 prompt 显示
        if (event.target.closest('[data-reference-variant]')) {
            return;
        }
        const promptDisplay = event.target.closest('.prompt-display');
        if (promptDisplay && !promptDisplay.querySelector('textarea')) {
            closeAllDropdowns();
            closeReferenceVariantSelector();
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
                // 退出编辑态：只刷工作台展示层，不碰助手/主预览
                rerender([Region.LEFT_TAB_BODY]);
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
    const prompt = sceneToPromptPayload(sc);
    prompt.location = sc.location ? { id: sc.location.id, name: sc.location.name } : null;
    prompt.props = (sc.props || []).map(p => ({ id: p.id, name: p.name }));
    await api.updateScenePrompt(sc.id, prompt);
    sc.promptJson = prompt;
    sc.referenceSelections = prompt.reference_selections || sc.referenceSelections;
    sc._fullPrompt = prompt;
    if (sc.raw) sc.raw.prompt_json = prompt;
    rerender([Region.LEFT_TAB_BODY]);
}

async function persistPromptValue(scene, type, value) {
    try {
        if (type === 'scene') {
            if (!scene.promptJson) scene.promptJson = {};
            scene.promptJson.scene_desc = value;
            const payload = sceneToPromptPayload(scene);
            await api.updateScenePrompt(scene.id, payload);
            scene.promptJson = payload;
            scene._fullPrompt = payload;
            if (scene.raw) scene.raw.prompt_json = payload;
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
                clearLocationReferenceSelection(sc);
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
