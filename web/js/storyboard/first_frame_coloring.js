/**
 * 故事板分镜首帧涂色适配层。
 * 复用全局 window.imageColoringEditor；上传/落库走 storyboard asset API。
 */
import state, {
    getCurrentScene,
    refreshSceneFirstFrameSlot,
} from './state.js';
import * as api from './api.js';
import { showToast } from './utils.js';
import { choosePreviewMedia } from './candidate_selection_state.js';
import { Region } from './ui_regions.js';

/**
 * 是否允许对当前分镜首帧涂色。
 * @param {object|null|undefined} scene
 * @param {{ isPlaying?: boolean }} [opts]
 * @returns {{ allowed: boolean, reason: string, url?: string }}
 */
export function canColorFirstFrame(scene, opts = {}) {
    if (!scene) {
        return { allowed: false, reason: 'no_scene' };
    }
    if (opts.isPlaying) {
        return { allowed: false, reason: 'playing' };
    }
    const media = choosePreviewMedia(scene);
    if (media.kind !== 'image') {
        return { allowed: false, reason: 'not_image' };
    }
    const url = String(media.url || '').trim();
    if (!url || url.includes(',')) {
        return { allowed: false, reason: 'no_image' };
    }
    return { allowed: true, reason: 'ok', url };
}

export function getColorFirstFrameBlockMessage(reason) {
    switch (reason) {
        case 'playing':
            return '请先停止预览播放再涂色';
        case 'not_image':
            return '当前预览不是分镜图，请先切换到首帧图';
        case 'no_image':
        case 'no_scene':
            return '请先生成或选择分镜图';
        default:
            return '当前无法涂色编辑';
    }
}

/**
 * dataURL → Blob（供 FormData 上传）
 * @param {string} dataUrl
 * @returns {Blob}
 */
export function dataUrlToBlob(dataUrl) {
    const parts = String(dataUrl || '').split(',');
    if (parts.length < 2) {
        throw new Error('无效的图片数据');
    }
    const header = parts[0] || '';
    const base64 = parts[1] || '';
    const mimeMatch = header.match(/data:([^;]+);/);
    const mime = (mimeMatch && mimeMatch[1]) || 'image/png';
    const binary = atob(base64);
    const len = binary.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return new Blob([bytes], { type: mime });
}

/**
 * 将涂色结果写入场景 state + 候选列表（不请求网络）。
 */
export function applyColoredAssetToScene(scene, {
    assetId,
    resultUrl,
    assetType = 'first_frame',
} = {}) {
    if (!scene || !resultUrl) return;
    if (assetType === 'first_frame') {
        scene.selectedFirstFrameId = assetId;
        scene.firstFrameUrl = resultUrl;
        scene.previewAssetType = 'first_frame';
        if (!state.sceneCandidates) state.sceneCandidates = {};
        const bucket = state.sceneCandidates[scene.id] || { images: [], videos: [] };
        const images = Array.isArray(bucket.images) ? bucket.images.slice() : [];
        images.forEach((item) => {
            item.selected = false;
        });
        images.unshift({
            id: assetId,
            url: resultUrl,
            status: null,
            selected: true,
            label: '涂色',
        });
        state.sceneCandidates[scene.id] = {
            ...bucket,
            images,
        };
    }
}

/**
 * 打开涂色编辑器；确认后上传并刷新 UI。
 * @param {(regions: any, options?: object) => void} rerender
 */
export async function openFirstFrameColoring(rerender) {
    const scene = getCurrentScene();
    const gate = canColorFirstFrame(scene, { isPlaying: Boolean(state.isPlaying) });
    if (!gate.allowed) {
        showToast(getColorFirstFrameBlockMessage(gate.reason), 'warning');
        return;
    }

    const editor = window.imageColoringEditor;
    if (!editor || typeof editor.open !== 'function') {
        showToast('涂色编辑器未加载', 'error');
        return;
    }

    if (typeof editor.init === 'function') {
        editor.init();
    }

    const context = {
        type: 'storyboard_scene',
        sceneId: scene.id,
        assetId: scene.selectedFirstFrameId || null,
    };

    await editor.open(gate.url, context, async (result) => {
        try {
            showToast('正在保存涂色结果…', 'info');
            const blob = dataUrlToBlob(result.coloredImage);
            const file = new File([blob], `colored_scene_${scene.id}.png`, { type: 'image/png' });
            const resp = await api.uploadSceneAsset(scene.id, file, {
                assetType: 'first_frame',
                setSelected: true,
            });
            if (!resp || resp.success === false) {
                throw new Error(resp?.error || resp?.message || '上传失败');
            }
            const assetId = resp.asset_id;
            const resultUrl = resp.result_url;
            if (!resultUrl) {
                throw new Error('上传成功但未返回图片地址');
            }

            // 若用户已切到别的分镜，仍写对应 scene 对象
            const target = (state.scenes || []).find((s) => String(s.id) === String(scene.id)) || scene;
            applyColoredAssetToScene(target, {
                assetId,
                resultUrl,
                assetType: 'first_frame',
            });
            if (state.chatMode === 'video') {
                refreshSceneFirstFrameSlot(target);
            }

            if (typeof rerender === 'function') {
                rerender(
                    [Region.PREVIEW, Region.CANDIDATES, Region.TIMELINE_LIST, Region.AGENT_PANEL],
                    { forcePreview: true },
                );
            }
            showToast('已保存为新的分镜图候选', 'success');
        } catch (err) {
            console.error('first frame coloring save failed', err);
            showToast(err?.message || '涂色保存失败', 'error');
        }
    });
}
