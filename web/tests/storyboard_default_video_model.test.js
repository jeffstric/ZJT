/**
 * 故事板默认视频模型：无记忆时取列表第一项（由后端 sort_order 决定顺序）。
 */
import fs from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, it } from 'vitest';

import state, {
    getImageToVideoSlotModels,
    getReferenceToVideoSlotModels,
    getSelectedImageToVideoModel,
    setModels,
} from '../js/storyboard/state.js';

describe('storyboard default video model', () => {
    beforeEach(() => {
        // 五槽位拆分后，legacy selectedVideoTaskId 与 image/text/reference 槽位都需清零，
        // 否则 resolveAvailableTaskId 会优先沿用上一个用例残留的 current 值。
        state.selectedVideoTaskId = null;
        state.selectedImageToVideoTaskId = null;
        state.selectedTextToVideoTaskId = null;
        state.selectedReferenceToVideoTaskId = null;
        state.selectedImageTaskId = null;
        state.selectedDigitalHumanTaskId = null;
        state.videoModels = [];
        state.imageToVideoModels = [];
        state.textToVideoModels = [];
        try {
            localStorage.removeItem('storyboard_lastSelectedVideoTaskId');
            localStorage.removeItem('storyboard_lastSelectedTextToVideoTaskId');
            localStorage.removeItem('storyboard_lastSelectedReferenceToVideoTaskId');
        } catch (_) { /* ignore */ }
    });

    it('无记忆时默认选中列表第一项（不硬编码 LTX key）', () => {
        // 模拟后端已按 sort_order 排好：LTX 在前
        setModels({
            video_models: [
                { task_id: 20, key: 'ltx2_3_image_to_video', short_key: 'ltx2_3', name: 'LTX2.3' },
                { task_id: 11, key: 'wan22_image_to_video', short_key: 'wan22', name: 'Wan2.2' },
            ],
        });
        expect(state.selectedVideoTaskId).toBe(20);
    });

    it('无记忆时若 Wan 在列表第一则默认 Wan（完全跟随列表顺序）', () => {
        setModels({
            video_models: [
                { task_id: 11, key: 'wan22_image_to_video', short_key: 'wan22', name: 'Wan2.2' },
                { task_id: 20, key: 'ltx2_3_image_to_video', short_key: 'ltx2_3', name: 'LTX2.3' },
            ],
        });
        expect(state.selectedVideoTaskId).toBe(11);
    });

    it('localStorage 有合法记忆时优先生效', () => {
        localStorage.setItem('storyboard_lastSelectedVideoTaskId', '11');
        setModels({
            video_models: [
                { task_id: 20, key: 'ltx2_3_image_to_video', short_key: 'ltx2_3', name: 'LTX2.3' },
                { task_id: 11, key: 'wan22_image_to_video', short_key: 'wan22', name: 'Wan2.2' },
            ],
        });
        expect(state.selectedVideoTaskId).toBe(11);
    });

    it('图生视频槽位排除仅参考图模型（如 Vidu-Q2），并把它留给参考槽位', () => {
        const ltx = {
            task_id: 20,
            key: 'ltx2_3_image_to_video',
            short_key: 'ltx2_3',
            name: 'LTX2.3',
            supported_image_modes: ['first_last_frame'],
        };
        const viduQ2 = {
            task_id: 19,
            key: 'vidu_q2_image_to_video',
            short_key: 'vidu_q2',
            name: 'Vidu-Q2',
            supported_image_modes: ['multi_reference'],
        };
        setModels({ image_to_video_models: [viduQ2, ltx] });

        expect(getImageToVideoSlotModels().map(m => m.task_id)).toEqual([20]);
        expect(getReferenceToVideoSlotModels().map(m => m.task_id)).toEqual([19]);
        expect(state.selectedImageToVideoTaskId).toBe(20);
        expect(getSelectedImageToVideoModel()?.task_id).toBe(20);
        expect(state.selectedReferenceToVideoTaskId).toBe(19);
    });

    it('localStorage 记住仅参考图模型时，图生视频槽位回退到首尾帧模型', () => {
        localStorage.setItem('storyboard_lastSelectedVideoTaskId', '19');
        setModels({
            image_to_video_models: [
                {
                    task_id: 19,
                    key: 'vidu_q2_image_to_video',
                    name: 'Vidu-Q2',
                    supported_image_modes: ['multi_reference'],
                },
                {
                    task_id: 14,
                    key: 'vidu_image_to_video',
                    name: 'Vidu-q2-pro-fast',
                    supported_image_modes: ['first_last_frame'],
                },
            ],
        });
        expect(state.selectedImageToVideoTaskId).toBe(14);
        expect(state.selectedReferenceToVideoTaskId).toBe(19);
    });

    it('拆分弹窗与齿轮图生视频下拉都按槽位能力过滤', () => {
        const renderSource = fs.readFileSync(
            path.resolve(import.meta.dirname, '../js/storyboard/render.js'),
            'utf8',
        );
        expect(renderSource).toContain('getImageToVideoSlotModels()');
        expect(renderSource).toContain('getReferenceToVideoSlotModels()');
        expect(renderSource).toMatch(/function renderDefaultVideoModelConfig[\s\S]*getImageToVideoSlotModels\(\)/);
        expect(renderSource).toMatch(/function renderVideoModelConfig[\s\S]*getImageToVideoSlotModels\(\)/);
    });
});
