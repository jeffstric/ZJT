import { beforeEach, describe, expect, it } from 'vitest';

import state from '../js/storyboard/state.js';
import { updateSceneThumb } from '../js/storyboard/render.js';

describe('故事板视频类型时间轴角标', () => {
    beforeEach(() => {
        state.autoImageBatch = null;
        document.body.innerHTML = `
            <button class="scene-timeline-thumb" data-scene="12"></button>
        `;
    });

    it('从对口型切换为普通视频后移除时间轴角标', () => {
        const scene = {
            id: 12,
            title: '分镜12',
            durationLabel: '00:02.2',
            firstFrameUrl: '/upload/storyboard/frame.png',
            videoType: 'digital_human',
        };

        expect(updateSceneThumb(scene)).toBe(true);
        const thumb = document.querySelector('.scene-timeline-thumb[data-scene="12"]');
        expect(thumb.querySelector('.scene-video-type-badge')?.textContent).toBe('对口型');
        const digitalHumanSig = thumb.dataset.mediaSig;

        scene.videoType = 'video';
        expect(updateSceneThumb(scene)).toBe(true);

        expect(thumb.dataset.mediaSig).not.toBe(digitalHumanSig);
        expect(thumb.querySelector('.scene-video-type-badge')).toBeNull();
    });
});
