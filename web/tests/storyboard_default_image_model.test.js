/**
 * 故事板默认生图模型：保留有效历史选择；无历史时优先 GPT Image 2。
 */
import { beforeEach, describe, expect, it } from 'vitest';

import state, { setModels } from '../js/storyboard/state.js';

describe('storyboard default image model', () => {
    const nanoBanana = {
        task_id: 1,
        key: 'gemini-2.5-flash-image-preview',
        short_key: 'gemini-2.5-flash',
        name: 'nano-banana',
    };
    const gptImage2 = {
        task_id: 26,
        key: 'gpt-image-2-edit',
        short_key: 'gpt-image-2',
        name: 'GPT Image 2 图片编辑',
    };

    beforeEach(() => {
        // 五槽位拆分后，legacy selectedImageTaskId 与 selectedTextToImageTaskId 都需清零，
        // 否则 resolveAvailableTaskId 会优先沿用上一个用例残留的 current 值。
        state.selectedImageTaskId = null;
        state.selectedTextToImageTaskId = null;
        state.selectedImageEditTaskId = null;
        state.imageModels = [];
        state.textToImageModels = [];
        state.imageEditModels = [];
        try {
            localStorage.removeItem('storyboard_lastSelectedImageTaskId');
            // 2026-08 图片编辑默认模型切换为 GPT Image 2 后，存储 key 升级为 _v2；
            // 旧 key 仅用于验证“强制切换”用例
            localStorage.removeItem('storyboard_lastSelectedImageEditTaskId');
            localStorage.removeItem('storyboard_lastSelectedImageEditTaskId_v2');
        } catch (_) { /* ignore */ }
    });

    it('无历史选择时优先选择 GPT Image 2', () => {
        setModels({ image_models: [nanoBanana, gptImage2] });

        expect(state.selectedImageTaskId).toBe(26);
        expect(localStorage.getItem('storyboard_lastSelectedImageTaskId')).toBe('26');
    });

    it('保留仍然有效的 nano-banana 历史选择', () => {
        localStorage.setItem('storyboard_lastSelectedImageTaskId', '1');

        setModels({ image_models: [nanoBanana, gptImage2] });

        expect(state.selectedImageTaskId).toBe(1);
    });

    it('GPT Image 2 不可用时回退模型列表第一项', () => {
        setModels({ image_models: [nanoBanana] });

        expect(state.selectedImageTaskId).toBe(1);
    });

    it('兼容 GPT Image 2 使用 key 标识的模型数据', () => {
        setModels({
            image_models: [
                nanoBanana,
                { task_id: 26, key: 'gpt-image-2', short_key: '', name: 'GPT Image 2' },
            ],
        });

        expect(state.selectedImageTaskId).toBe(26);
    });

    it('图片编辑：无历史选择时优先 GPT Image 2', () => {
        setModels({ image_edit_models: [nanoBanana, gptImage2] });

        expect(state.selectedImageEditTaskId).toBe(26);
        expect(localStorage.getItem('storyboard_lastSelectedImageEditTaskId_v2')).toBe('26');
    });

    it('图片编辑：旧 key 中的 nano-banana 记忆被强制作废', () => {
        // 旧 key（无 _v2）是切换默认模型前的遗留记忆，升级后不再读取
        localStorage.setItem('storyboard_lastSelectedImageEditTaskId', '1');

        setModels({ image_edit_models: [nanoBanana, gptImage2] });

        expect(state.selectedImageEditTaskId).toBe(26);
    });

    it('图片编辑：新 key 中仍然有效的历史选择保留', () => {
        localStorage.setItem('storyboard_lastSelectedImageEditTaskId_v2', '1');

        setModels({ image_edit_models: [nanoBanana, gptImage2] });

        expect(state.selectedImageEditTaskId).toBe(1);
    });

    it('图片编辑：GPT Image 2 不可用时回退模型列表第一项', () => {
        setModels({ image_edit_models: [nanoBanana] });

        expect(state.selectedImageEditTaskId).toBe(1);
    });
});
