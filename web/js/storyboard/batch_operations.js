import state from './state.js';
import * as api from './api.js';
import { t } from './utils.js';
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
    if (!result) return t('msg_batch_tasks_not_submitted', '{kind}任务未提交').replace('{kind}', kind);
    if ((result.code || result.error_code) === 'active_batch_exists') {
        return t('msg_batch_already_running', '当前已有分镜图生成任务进行中，本次未重复提交');
    }
    const submitted = Number(result.submitted_count || 0);
    const skipped = Number(result.skipped_count || 0);
    const reused = Number(result.reused_count || 0);
    const regenerated = Number(result.regenerated_count || 0);
    const failed = Number(result.failed_count || 0);
    const parts = [
        t('msg_batch_submitted_n', '{kind}已提交 {n} 项').replace('{kind}', kind).replace('{n}', String(submitted)),
    ];
    if (regenerated) parts.push(t('msg_batch_regenerated_n', '重新生成 {n} 项').replace('{n}', String(regenerated)));
    if (reused) parts.push(t('msg_batch_reused_n', '已有 {n} 项').replace('{n}', String(reused)));
    if (skipped) parts.push(t('msg_batch_skipped_n', '跳过 {n} 项').replace('{n}', String(skipped)));
    if (failed) parts.push(t('msg_batch_failed_n', '失败 {n} 项').replace('{n}', String(failed)));
    return parts.join(t('msg_batch_result_separator', '，'));
}
