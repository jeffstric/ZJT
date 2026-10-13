/**
 * 故事板分镜首帧涂鸦编辑适配层。
 * 复用全局 window.imageDoodleEditor（涂鸦编辑器，open() 时自注入 DOM）；
 * 上传/落库走 storyboard asset API。
 */
import state, {
    getCurrentScene,
    refreshSceneFirstFrameSlot,
} from './state.js';
import * as api from './api.js';
import { showToast } from './utils.js';
import { choosePreviewMedia } from './candidate_selection_state.js';
import { Region } from './ui_regions.js';

// 本地 t：web/tests/first_frame_coloring.test.js 对 utils.js 做了部分 vi.mock（仅导出 showToast），
// 静态引入共享 t 会在测试中触发 Vitest 缺导出错误，故内置与 utils.js 等价的实现。
function t(key, fallback) {
    if (typeof window !== 'undefined' && window.ZJTi18n && window.ZJTi18n.t) {
        const translated = window.ZJTi18n.t(key);
        if (translated !== key) return translated;
    }
    return fallback || key;
}

/**
 * 是否允许对当前分镜首帧涂鸦。
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
            return t('msg_coloring_stop_preview_first', '请先停止预览播放再编辑');
        case 'not_image':
            return t('msg_coloring_not_scene_image', '当前预览不是分镜图，请先切换到首帧图');
        case 'no_image':
        case 'no_scene':
            return t('msg_coloring_need_scene_image', '请先生成或选择分镜图');
        default:
            return t('msg_coloring_unavailable', '当前无法涂鸦编辑');
    }
}

/**
 * 跨域图片 URL 转同源代理地址，避免涂鸦编辑器 canvas 跨域污染
 * （storyboard 页无全局 proxyImageUrl，逻辑与 video_workflow state.js 一致）。
 * @param {string} url
 * @returns {string}
 */
function toSameOriginImageUrl(url) {
    const str = String(url || '');
    if (!str || str.startsWith('data:') || str.startsWith('blob:')) return str;
    try {
        const u = new URL(str, window.location.href);
        if (u.origin === window.location.origin) return str;
    } catch (e) {
        return str;
    }
    return `/api/proxy-image?url=${encodeURIComponent(str)}`;
}

/**
 * 将涂鸦结果写入场景 state + 候选列表（不请求网络）。
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
            label: t('label_colored', '涂鸦'),
        });
        state.sceneCandidates[scene.id] = {
            ...bucket,
            images,
        };
    }
}

/**
 * 打开涂鸦编辑器；确认后上传并刷新 UI。
 * @param {(regions: any, options?: object) => void} rerender
 */
export async function openFirstFrameColoring(rerender) {
    const scene = getCurrentScene();
    const gate = canColorFirstFrame(scene, { isPlaying: Boolean(state.isPlaying) });
    if (!gate.allowed) {
        showToast(getColorFirstFrameBlockMessage(gate.reason), 'warning');
        return;
    }

    const editor = window.imageDoodleEditor;
    if (!editor || typeof editor.open !== 'function') {
        showToast(t('msg_coloring_editor_not_loaded', '涂鸦编辑器未加载'), 'error');
        return;
    }

    const context = {
        type: 'storyboard_scene',
        sceneId: scene.id,
        assetId: scene.selectedFirstFrameId || null,
    };

    await editor.open(toSameOriginImageUrl(gate.url), {
        context,
        onComplete: async ({ blob }) => {
            try {
                showToast(t('msg_saving_coloring_result', '正在保存涂鸦结果…'), 'info');
                const file = new File([blob], `doodle_scene_${scene.id}.png`, { type: 'image/png' });
                const resp = await api.uploadSceneAsset(scene.id, file, {
                    assetType: 'first_frame',
                    setSelected: true,
                });
                if (!resp || resp.success === false) {
                    throw new Error(resp?.error || resp?.message || t('msg_upload_failed', '上传失败'));
                }
                const assetId = resp.asset_id;
                const resultUrl = resp.result_url;
                if (!resultUrl) {
                    throw new Error(t('msg_upload_no_image_url', '上传成功但未返回图片地址'));
                }

                // 若用户已切到别的分镜，仍写对应 scene 对象
                const target = (state.scenes || []).find((s) => String(s.id) === String(scene.id)) || scene;
                applyColoredAssetToScene(target, {
                    assetId,
                    resultUrl,
                    assetType: 'first_frame',
                });
                if (state.chatMode === 'video' || state.chatMode === 'aivideo') {
                    refreshSceneFirstFrameSlot(target);
                }

                if (typeof rerender === 'function') {
                    rerender(
                        [Region.PREVIEW, Region.CANDIDATES, Region.TIMELINE_LIST, Region.AGENT_PANEL],
                        { forcePreview: true },
                    );
                }
                showToast(t('msg_coloring_saved_as_candidate', '已保存为新的分镜图候选'), 'success');
            } catch (err) {
                console.error('first frame doodle save failed', err);
                showToast(err?.message || t('msg_coloring_save_failed', '涂鸦保存失败'), 'error');
            }
        },
    });
}
