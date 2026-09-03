// 场景候选资产列表（分镜右栏候选区数据源）：加载 + 规整。
// 从 events.js 抽出，供 events 与 polling 共用（避免 events ↔ polling 循环引用）。
import state from './state.js';
import * as api from './api.js';

export function isRenderableCandidateUrl(url) {
    if (url == null) return false;
    const value = String(url).trim();
    if (!value) return false;
    // 逗号拼接多图是输入参考图，不是单张结果图
    if (value.includes(',')) return false;
    return true;
}

export function getSceneAssetCandidateUrl(asset) {
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

export function mapSceneAssetCandidates(response, assetType) {
    const selectedId = response?.selected?.[assetType];
    const assets = response?.assets || response?.data || [];
    return assets.map(asset => ({
        id: asset.id,
        url: getSceneAssetCandidateUrl(asset),
        posterUrl: asset.poster_url || asset.thumbnail_url || '',
        status: asset.status ?? asset.ai_tool?.status ?? asset.tool?.status ?? null,
        selected: selectedId !== null && selectedId !== undefined && String(asset.id) === String(selectedId),
    }));
}

export async function loadSceneCandidates(sceneId) {
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
