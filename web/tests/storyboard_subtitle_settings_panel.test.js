/**
 * 字幕设置面板开合只走 timelineChrome 局部刷新：
 * patchTimelineChrome 必须重挂 .subtitle-settings（齿轮按钮 + 面板），
 * 否则点击齿轮只翻转 state、DOM 不变，表现为"点击齿轮无反应"。
 */
import { beforeEach, describe, expect, it } from 'vitest';

import state from '../js/storyboard/state.js';
import { refresh, Region } from '../js/storyboard/render.js';

function mountTimelineChrome() {
    document.body.innerHTML = `
        <div id="app"><div class="app-shell">
            <section class="timeline-controls">
                <div class="timeline-progress-row">
                    <button class="play-btn"></button>
                    <span class="timeline-time">00:00 / 00:00</span>
                    <label class="subtitle-toggle"><input type="checkbox" data-action="toggle-subtitle"> 字幕</label>
                    <div class="subtitle-settings">
                        <button class="subtitle-settings-btn" data-action="toggle-subtitle-settings"></button>
                    </div>
                    <button class="timeline-view-toggle"></button>
                </div>
            </section>
        </div></div>`;
}

describe('storyboard subtitle settings panel', () => {
    beforeEach(() => {
        state.showSubtitleSettings = false;
        state.subtitleEnabled = true;
        state.error = null;
        mountTimelineChrome();
    });

    it('打开面板：refresh(timelineChrome) 后面板出现且齿轮高亮', () => {
        state.showSubtitleSettings = true;
        refresh(Region.TIMELINE_CHROME);
        expect(document.querySelector('.subtitle-settings-panel')).toBeTruthy();
        const btn = document.querySelector('.subtitle-settings-btn');
        expect(btn.classList.contains('active')).toBe(true);
        expect(btn.dataset.action).toBe('toggle-subtitle-settings');
    });

    it('关闭面板：refresh(timelineChrome) 后面板移除且 active 清除', () => {
        state.showSubtitleSettings = true;
        refresh(Region.TIMELINE_CHROME);
        state.showSubtitleSettings = false;
        refresh(Region.TIMELINE_CHROME);
        expect(document.querySelector('.subtitle-settings-panel')).toBeNull();
        expect(document.querySelector('.subtitle-settings-btn').classList.contains('active')).toBe(false);
    });

    it('重挂不丢齿轮按钮与边距滑杆（事件/input 委托依赖 data 属性）', () => {
        state.showSubtitleSettings = true;
        refresh(Region.TIMELINE_CHROME);
        expect(
            document.querySelector('.timeline-progress-row .subtitle-settings [data-action="toggle-subtitle-settings"]')
        ).toBeTruthy();
        expect(document.querySelector('[data-subtitle-margin]')).toBeTruthy();
        // 控制条其余部分不被重建
        expect(document.querySelectorAll('.timeline-progress-row').length).toBe(1);
        expect(document.querySelector('.timeline-progress-row .timeline-view-toggle')).toBeTruthy();
    });
});
