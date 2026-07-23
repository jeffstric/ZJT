import state from './state.js';

function selectedMap() {
    if (!state.batchSelection) {
        state.batchSelection = { active: false, selectedSceneIds: {}, submittingAction: '' };
    }
    if (!state.batchSelection.selectedSceneIds) state.batchSelection.selectedSceneIds = {};
    return state.batchSelection.selectedSceneIds;
}

export function isBatchSelectionActive() {
    return state.viewMode === 'grid' && Boolean(state.batchSelection?.active);
}

export function enterBatchSelection() {
    state.batchSelection.active = true;
    state.batchSelection.selectedSceneIds = {};
    state.batchSelection.submittingAction = '';
}

export function exitBatchSelection() {
    state.batchSelection.active = false;
    state.batchSelection.selectedSceneIds = {};
    state.batchSelection.submittingAction = '';
}

export function getSelectedSceneIds() {
    const map = selectedMap();
    return (state.scenes || [])
        .filter(scene => Boolean(map[String(scene.id)]))
        .map(scene => scene.id);
}

export function isSceneSelected(sceneId) {
    return Boolean(selectedMap()[String(sceneId)]);
}

export function setSceneSelected(sceneId, selected) {
    const key = String(sceneId);
    if (selected) selectedMap()[key] = true;
    else delete selectedMap()[key];
}

export function toggleSceneSelected(sceneId) {
    setSceneSelected(sceneId, !isSceneSelected(sceneId));
}

export function selectAllScenes() {
    state.batchSelection.selectedSceneIds = Object.fromEntries(
        (state.scenes || []).map(scene => [String(scene.id), true]),
    );
}

export function invertSceneSelection() {
    const previous = selectedMap();
    state.batchSelection.selectedSceneIds = Object.fromEntries(
        (state.scenes || [])
            .filter(scene => !previous[String(scene.id)])
            .map(scene => [String(scene.id), true]),
    );
}

export function clearSceneSelection() {
    state.batchSelection.selectedSceneIds = {};
}

export function pruneSceneSelection() {
    const validIds = new Set((state.scenes || []).map(scene => String(scene.id)));
    for (const key of Object.keys(selectedMap())) {
        if (!validIds.has(key)) delete state.batchSelection.selectedSceneIds[key];
    }
}

export function setBatchSubmittingAction(action = '') {
    state.batchSelection.submittingAction = action;
}
