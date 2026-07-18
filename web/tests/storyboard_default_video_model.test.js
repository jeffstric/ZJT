/**
 * 故事板默认视频模型：无记忆时取列表第一项（由后端 sort_order 决定顺序）。
 */
import { beforeEach, describe, expect, it } from 'vitest';

import state, { setModels } from '../js/storyboard/state.js';

describe('storyboard default video model', () => {
    beforeEach(() => {
        state.selectedVideoTaskId = null;
        state.selectedImageTaskId = null;
        state.selectedDigitalHumanTaskId = null;
        state.videoModels = [];
        try {
            localStorage.removeItem('storyboard_lastSelectedVideoTaskId');
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
});
