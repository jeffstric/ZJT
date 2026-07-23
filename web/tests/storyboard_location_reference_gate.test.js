import { beforeEach, describe, expect, it } from 'vitest';

import state from '../js/storyboard/state.js';
import {
    applyLocationReferencePreflight,
    getAutoCompleteButtonViewModel,
    getFirstFrameDisplayStatus,
    resetAutoImageBatchState,
} from '../js/storyboard/auto_missing_images_state.js';

describe('quality location reference preflight state', () => {
    beforeEach(() => {
        state.scenes = [{ id: 101, firstFrameUrl: '' }, { id: 102, firstFrameUrl: '' }];
        resetAutoImageBatchState();
    });

    it('marks affected scenes and exposes a recover button for manual blockers', () => {
        applyLocationReferencePreflight({
            error_code: 'quality_parent_reference_missing',
            error: '父场景缺少参考图',
            blockers: [{ affected_scene_ids: [101], parent_location_name: '城南酒店' }],
        });

        expect(getFirstFrameDisplayStatus(state.scenes[0])).toBe('blocked_location');
        expect(getFirstFrameDisplayStatus(state.scenes[1])).toBe('missing');
        expect(getAutoCompleteButtonViewModel().label).toBe('重新检查并生成');
    });

    it('keeps waiting preflight separate from batch state', () => {
        applyLocationReferencePreflight({
            error_code: 'waiting_location_references',
            error: '场景参考图生成中',
            affected_scene_ids: [102],
            retry_after_ms: 3000,
        });

        expect(state.autoImageBatch.batchId).toBeNull();
        expect(state.autoImageLocationGate.status).toBe('waiting');
        expect(getFirstFrameDisplayStatus(state.scenes[1])).toBe('waiting_location');
    });
});
