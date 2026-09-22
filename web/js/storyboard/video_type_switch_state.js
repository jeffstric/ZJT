/**
 * 与 web/js/storyboard/utils.js 的 t(key, fallback) 行为一致的本地实现。
 * 本模块被 tests/js/test_storyboard_video_type_switch_state.js 以 vm.runInNewContext
 * 沙箱执行源码(不支持静态 import,且沙箱无 window),故内置等价实现(带 window 守卫)。
 */
function t(key, fallback) {
    if (typeof window !== 'undefined' && window.ZJTi18n && window.ZJTi18n.t) {
        const translated = window.ZJTi18n.t(key);
        if (translated !== key) return translated;
    }
    return fallback || key;
}

export function canSwitchToDigitalHuman(scene) {
    const speakerIds = new Set(
        (scene?.dialogues || [])
            .map(dialogue => dialogue?.characterId ?? dialogue?.character_id)
            .filter(id => id !== null && id !== undefined && id !== '')
            .map(String)
    );
    if (speakerIds.size > 1) {
        return {
            allowed: false,
            reason: t('msg_digital_human_single_speaker', '对口型模式仅支持单个说话角色'),
        };
    }
    return { allowed: true, reason: '' };
}

export function applyVideoTypeSwitchResult(scene, response) {
    if (!scene || !response) return scene;
    scene.videoType = response.video_type || scene.videoType;
    scene.selectedVideoId = response.selected_video_id ?? null;
    scene.videoUrl = response.video_url || null;
    if (!scene.selectedVideoId && scene.previewAssetType === 'video') {
        scene.previewAssetType = 'first_frame';
    }
    return scene;
}
