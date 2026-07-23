import state from './state.js';
import * as api from './api.js';
import { autoCompleteMissingFirstFrames } from './auto_missing_images.js';
import { autoCompleteMissingVideos } from './auto_missing_videos.js';
import { pollSceneTaskStatus } from './polling.js';

export async function batchGenerateVoiceovers(sceneIds) {
    const result = await api.batchGenerateMissingVoiceovers(state.storyboardId, sceneIds);
    const submittedSceneIds = new Set(
        (result.items || [])
            .filter(item => item.status === 'submitted' && item.scene_id)
            .map(item => item.scene_id),
    );
    submittedSceneIds.forEach(sceneId => pollSceneTaskStatus(sceneId));
    return result;
}

export async function batchGenerateVideos(sceneIds) {
    return autoCompleteMissingVideos(sceneIds);
}

export async function batchGenerateFirstFrames(sceneIds) {
    const isCommunity = String(state.editionInfo?.mode || '').toLowerCase() === 'community';
    return autoCompleteMissingFirstFrames(sceneIds, {
        sequenceMode: isCommunity ? 'balanced' : 'quality',
        existingPolicy: 'regenerate',
    });
}

export function getBatchImageSelectionSummary(sceneIds) {
    const selected = new Set((sceneIds || []).map(String));
    const scenes = (state.scenes || []).filter(scene => selected.has(String(scene.id)));
    const existingCount = scenes.filter(scene => Boolean(String(scene.firstFrameUrl || '').trim())).length;
    return {
        selectedCount: scenes.length,
        existingCount,
        missingCount: scenes.length - existingCount,
    };
}

export async function batchDeleteScenes(sceneIds) {
    return api.batchDeleteScenes(state.storyboardId, sceneIds);
}

export function generationResultMessage(kind, result = {}) {
    if (!result) return `${kind}任务未提交`;
    if ((result.code || result.error_code) === 'active_batch_exists') {
        return '当前已有分镜图生成任务进行中，本次未重复提交';
    }
    const submitted = Number(result.submitted_count || 0);
    const skipped = Number(result.skipped_count || 0);
    const reused = Number(result.reused_count || 0);
    const regenerated = Number(result.regenerated_count || 0);
    const failed = Number(result.failed_count || 0);
    const parts = [`${kind}已提交 ${submitted} 项`];
    if (regenerated) parts.push(`重新生成 ${regenerated} 项`);
    if (reused) parts.push(`已有 ${reused} 项`);
    if (skipped) parts.push(`跳过 ${skipped} 项`);
    if (failed) parts.push(`失败 ${failed} 项`);
    return parts.join('，');
}
