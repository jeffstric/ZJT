/**
 * 拆分弹窗切换分镜图生成模式时，只改卡片选中态，避免整窗重建把滚动拉回顶部。
 */
import fs from 'node:fs';
import path from 'node:path';
import { beforeEach, describe, expect, it } from 'vitest';

import state from '../js/storyboard/state.js';
import { syncSequenceModeIntroCards } from '../js/storyboard/render.js';

const readSource = (relativePath) => fs.readFileSync(
    path.resolve(import.meta.dirname, '../..', relativePath),
    'utf8',
);

describe('storyboard sequence mode cards', () => {
    beforeEach(() => {
        state.autoImageSequenceMode = 'balanced';
        document.body.innerHTML = `
            <div class="gfs-body">
                <div data-action="set-auto-image-sequence-mode" data-auto-image-sequence-mode="balanced"
                     class="sequence-mode-intro-card active"></div>
                <div data-action="set-auto-image-sequence-mode" data-auto-image-sequence-mode="quality"
                     class="sequence-mode-intro-card"></div>
                <div data-action="set-auto-image-sequence-mode" data-auto-image-sequence-mode="speed"
                     class="sequence-mode-intro-card"></div>
            </div>
        `;
    });

    it('syncSequenceModeIntroCards 只切换 active，不重建节点', () => {
        const speed = document.querySelector('[data-auto-image-sequence-mode="speed"]');
        const balanced = document.querySelector('[data-auto-image-sequence-mode="balanced"]');
        state.autoImageSequenceMode = 'speed';
        syncSequenceModeIntroCards();
        expect(speed.classList.contains('active')).toBe(true);
        expect(balanced.classList.contains('active')).toBe(false);
        expect(document.querySelectorAll('[data-action="set-auto-image-sequence-mode"]').length).toBe(3);
    });

    it('点击分镜图生成模式不走 rerenderModals，syncModals 会恢复 gfs-body 滚动', () => {
        const eventsSource = readSource('web/js/storyboard/events.js');
        const renderSource = readSource('web/js/storyboard/render.js');
        const handler = eventsSource.match(
            /if \(action === 'set-auto-image-sequence-mode'\) \{[\s\S]*?\n    \}/,
        )?.[0] || '';
        expect(handler).toContain("syncSequenceModeIntroCards()");
        expect(handler).not.toContain('rerenderModals()');
        expect(renderSource).toContain('.generate-from-script-dialog .gfs-body');
        expect(renderSource).toContain('el.scrollTop = top');
    });
});
