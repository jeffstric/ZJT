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
            reason: '对口型模式仅支持单个说话角色',
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
