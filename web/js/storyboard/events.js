import state, {
    addSceneToState,
    addDialogueToState,
    getCurrentScene,
    removeSceneFromState,
    removeDialogueFromState,
    replaceSceneInState,
    serializeUiConfig,
    loadStoryboardData,
} from './state.js';
import * as api from './api.js';
import { sceneToPromptPayload, sceneToUpdatePayload } from './adapters.js';
import { renderApp } from './render.js';
import { pollSceneTaskStatus } from './polling.js';

function notify(message) {
    window.alert(message);
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

async function handleAction(action, target) {
    const current = getCurrentScene();

    if (action === 'generate-from-script-cancel') {
        if (state.isGeneratingFromScript) return;
        state.showGenerateFromScriptDialog = false;
        state.generateFromScriptError = '';
        rerender();
        return;
    }

    if (action === 'generate-from-script-confirm') {
        if (state.isGeneratingFromScript || !state.storyboardId) return;
        state.isGeneratingFromScript = true;
        state.generateFromScriptError = '';
        rerender();
        try {
            const response = await api.generateFromScript(state.storyboardId, {
                max_group_duration: 15,
                split_multi_dialogue: false,
            });
            loadStoryboardData(response);
            state.showGenerateFromScriptDialog = false;
            notify(`已生成 ${response.generated_count || state.scenes.length} 个分镜`);
        } catch (error) {
            state.generateFromScriptError = error.message || '生成分镜失败';
        } finally {
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

    if (action === 'toggle-ai') {
        state.aiOptimize = !state.aiOptimize;
        rerender();
        await persistUiConfig();
        return;
    }

    if (action === 'open-edit') {
        state.showEditPrompt = true;
        rerender();
        return;
    }

    if (action === 'close-edit') {
        state.showEditPrompt = false;
        rerender();
        return;
    }

    if (action === 'save-prompt' && current) {
        current.promptJson = {
            perspective: document.querySelector('[data-edit-field="perspective"]')?.value || '',
            style: document.querySelector('[data-edit-field="style"]')?.value || '',
            scene_desc: document.querySelector('[data-edit-field="scene_desc"]')?.value || '',
            character_desc: document.querySelector('[data-edit-field="character_desc"]')?.value || '',
        };
        await api.updateScenePrompt(current.id, sceneToPromptPayload(current));
        state.showEditPrompt = false;
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

    if (action === 'send-ai') {
        if (!current) return;
        if (state.chatMode === 'image') {
            const response = await api.generateSceneImage(current.id, {
                prompt: state.inputMessage,
                task_type: state.selectedImageTaskId,
            });
            if (response.success) {
                state.inputMessage = '';
                pollSceneTaskStatus(current.id);
            }
            notify(response.error || '图片生成任务已提交');
        } else if (state.chatMode === 'video') {
            const isDigitalHuman = current.videoType === 'digital_human';
            const taskType = isDigitalHuman ? state.selectedDigitalHumanTaskId : state.selectedVideoTaskId;
            const response = await api.generateSceneVideo(current.id, {
                prompt: state.inputMessage,
                task_type: taskType,
            });
            if (response.success) {
                state.inputMessage = '';
                pollSceneTaskStatus(current.id);
            }
            notify(response.error || '视频生成任务已提交');
        } else {
            notify('对话改图能力正在接入中');
        }
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
}

function handleRoute(route) {
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
        if (sceneTarget && !actionTarget) {
            state.currentSceneId = parseInt(sceneTarget.dataset.scene, 10);
            state.currentTime = 0;
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

    document.addEventListener('change', async (event) => {
        const target = event.target;
        if (target.id === 'chat-mode-select') {
            state.chatMode = target.value;
            rerender();
            await persistUiConfig();
            return;
        }
        if (target.dataset.modelSelect) {
            const value = parseInt(target.value, 10);
            switch (target.dataset.modelSelect) {
                case 'image': state.selectedImageTaskId = value; break;
                case 'video': state.selectedVideoTaskId = value; break;
                case 'digital_human': state.selectedDigitalHumanTaskId = value; break;
            }
        }
    });

    document.addEventListener('click', (event) => {
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
    });
}
