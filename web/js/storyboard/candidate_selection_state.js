const SELECTION_KEYS = {
    first_frame: 'selectedFirstFrameId',
    video: 'selectedVideoId',
};

function normalizeSelectionId(value) {
    return value === null || value === undefined || value === '' ? '' : String(value);
}

export function choosePreviewMedia(scene) {
    if (!scene) return { kind: '', url: '' };
    if (scene.previewAssetType === 'first_frame' && scene.firstFrameUrl) {
        return { kind: 'image', url: scene.firstFrameUrl };
    }
    if (scene.previewAssetType === 'video' && scene.videoUrl) {
        return { kind: 'video', url: scene.videoUrl };
    }
    if (scene.videoUrl) return { kind: 'video', url: scene.videoUrl };
    if (scene.firstFrameUrl) return { kind: 'image', url: scene.firstFrameUrl };
    return { kind: '', url: '' };
}

export function captureAssetSelection(scene) {
    return {
        selectedFirstFrameId: scene?.selectedFirstFrameId ?? null,
        selectedVideoId: scene?.selectedVideoId ?? null,
    };
}

export function isPollAssetSelectionCurrent(scene, assetType, requestSelection) {
    const key = SELECTION_KEYS[assetType];
    if (!key) return true;
    return normalizeSelectionId(scene?.[key]) === normalizeSelectionId(requestSelection?.[key]);
}

export function captureVideoCandidateSelection(scene, candidates = []) {
    return {
        selectedVideoId: scene?.selectedVideoId ?? null,
        videoUrl: scene?.videoUrl || '',
        previewAssetType: scene?.previewAssetType || '',
        selectedCandidateIds: candidates
            .filter(item => item?.selected)
            .map(item => String(item.id)),
    };
}

export function applyVideoCandidateSelection(scene, candidates = [], assetId, url = '') {
    if (!scene) return;
    scene.selectedVideoId = assetId;
    if (url) scene.videoUrl = url;
    scene.previewAssetType = 'video';
    candidates.forEach(item => {
        item.selected = String(item.id) === String(assetId);
    });
}

export function restoreVideoCandidateSelection(scene, candidates = [], snapshot = {}) {
    if (!scene) return;
    scene.selectedVideoId = snapshot.selectedVideoId ?? null;
    scene.videoUrl = snapshot.videoUrl || '';
    scene.previewAssetType = snapshot.previewAssetType || '';
    const selectedIds = new Set(snapshot.selectedCandidateIds || []);
    candidates.forEach(item => {
        item.selected = selectedIds.has(String(item.id));
    });
}
