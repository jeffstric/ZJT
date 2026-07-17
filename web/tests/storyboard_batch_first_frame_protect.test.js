/**
 * 自动补全 batch 轮询不得覆盖用户涂色/手动选中的首帧。
 */
import { beforeEach, describe, expect, it } from 'vitest';

import state from '../js/storyboard/state.js';
import {
    applyImageBatchStatus,
    resetAutoImageBatchState,
    shouldApplyBatchFirstFrameToScene,
} from '../js/storyboard/auto_missing_images_state.js';

describe('shouldApplyBatchFirstFrameToScene', () => {
    it('无选中时允许 batch 写入', () => {
        expect(shouldApplyBatchFirstFrameToScene(
            { selectedFirstFrameId: null, firstFrameUrl: '' },
            { assetId: 10 },
        )).toBe(true);
    });

    it('选中与 batch asset 一致时允许同步 URL', () => {
        expect(shouldApplyBatchFirstFrameToScene(
            { selectedFirstFrameId: 10, firstFrameUrl: 'https://a.png' },
            { assetId: 10 },
        )).toBe(true);
    });

    it('用户已选其它资产（涂色）时禁止覆盖', () => {
        expect(shouldApplyBatchFirstFrameToScene(
            { selectedFirstFrameId: 99, firstFrameUrl: 'https://colored.png' },
            { assetId: 10 },
        )).toBe(false);
    });

    it('batch 尚无 asset 且场景已有图时禁止改写', () => {
        expect(shouldApplyBatchFirstFrameToScene(
            { selectedFirstFrameId: 99, firstFrameUrl: 'https://colored.png' },
            { assetId: null },
        )).toBe(false);
    });
});

describe('applyImageBatchStatus 保护涂色结果', () => {
    beforeEach(() => {
        resetAutoImageBatchState();
        state.scenes = [
            {
                id: 2,
                selectedFirstFrameId: 900, // 涂色后的资产
                firstFrameUrl: 'https://cdn.example.com/colored.png',
            },
            {
                id: 3,
                selectedFirstFrameId: null,
                firstFrameUrl: '',
            },
        ];
    });

    it('补全轮询的 already_ready/completed 不得把涂色图改回原图', () => {
        applyImageBatchStatus({
            batch_id: 1,
            status: 'running',
            items: [
                {
                    scene_id: 2,
                    status: 'already_ready',
                    asset_id: 100, // batch 仍挂着生成时的旧 asset
                    result_url: 'https://cdn.example.com/original.png',
                },
            ],
        });

        const scene = state.scenes[0];
        expect(scene.selectedFirstFrameId).toBe(900);
        expect(scene.firstFrameUrl).toBe('https://cdn.example.com/colored.png');
    });

    it('缺失首帧的分镜仍可由 batch 正常补全', () => {
        applyImageBatchStatus({
            batch_id: 1,
            status: 'running',
            items: [
                {
                    scene_id: 3,
                    status: 'completed',
                    asset_id: 200,
                    result_url: 'https://cdn.example.com/new.png',
                },
            ],
        });

        const scene = state.scenes[1];
        expect(scene.selectedFirstFrameId).toBe(200);
        expect(scene.firstFrameUrl).toBe('https://cdn.example.com/new.png');
    });

    it('选中仍是 batch asset 时允许 result_url 更新（宫格拆分等）', () => {
        state.scenes[0].selectedFirstFrameId = 100;
        state.scenes[0].firstFrameUrl = 'https://cdn.example.com/temp/grid.png';

        applyImageBatchStatus({
            batch_id: 1,
            status: 'running',
            items: [
                {
                    scene_id: 2,
                    status: 'completed',
                    asset_id: 100,
                    result_url: 'https://cdn.example.com/storyboard/first_frame/cell.png',
                },
            ],
        });

        const scene = state.scenes[0];
        expect(scene.selectedFirstFrameId).toBe(100);
        expect(scene.firstFrameUrl).toBe('https://cdn.example.com/storyboard/first_frame/cell.png');
    });
});
