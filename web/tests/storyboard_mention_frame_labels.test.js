// 提及菜单首尾帧按钮：展示名按媒体槽顺序编号（图N），token 仍为 @首帧图/@尾帧图。
import { describe, expect, it } from 'vitest';
import state from '../js/storyboard/state.js';
import { frameMentionRowLabels } from '../js/storyboard/render.js';

function baseState() {
    state.error = '';
    state.ratioGateActive = false;
    state.chatMode = 'video';
    state.videoImageMode = 'multi_reference';
    state.scenes = [];
    state.currentSceneId = null;
    state.videoMediaItems = [];
}

describe('mention menu frame labels follow media stack numbering', () => {
    it('labels frame slots as 图N by stack position', () => {
        baseState();
        state.videoMediaItems = [
            { role: 'first_frame', url: 'https://cdn.test/first.png' },
            { role: 'last_frame', url: 'https://cdn.test/last.png' },
            { role: 'reference', url: 'https://cdn.test/ref.png' },
        ];
        expect(frameMentionRowLabels()).toEqual({ first: '图1', last: '图2' });
    });

    it('numbers a scene-fallback first frame as 图1 when its slot was removed', () => {
        baseState();
        state.scenes = [{ id: 7, firstFrameUrl: 'https://cdn.test/scene-first.png' }];
        state.currentSceneId = 7;
        state.videoMediaItems = [{ role: 'reference', url: 'https://cdn.test/ref.png' }];
        expect(frameMentionRowLabels().first).toBe('图1');
    });

    it('numbers a scene-fallback last frame after an existing first slot', () => {
        baseState();
        state.scenes = [{ id: 7, lastFrameUrl: 'https://cdn.test/scene-last.png' }];
        state.currentSceneId = 7;
        state.videoMediaItems = [{ role: 'first_frame', url: 'https://cdn.test/first.png' }];
        expect(frameMentionRowLabels().last).toBe('图2');
    });
});
