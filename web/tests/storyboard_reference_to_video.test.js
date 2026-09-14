import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('storyboard reference-to-video without first frame', () => {
    it('direct video submit skips first-frame gate in multi_reference and sends image_mode', () => {
        const eventsSource = readSource('web/js/storyboard/events.js');
        const start = eventsSource.indexOf('async function sendDirectVideo(');
        const end = eventsSource.indexOf('function recordPowerSpend', start);
        expect(start).toBeGreaterThan(-1);
        expect(end).toBeGreaterThan(start);
        const fn = eventsSource.slice(start, end);
        expect(fn).toContain("imageMode === 'first_last_frame'");
        expect(fn).toContain('config.image_mode = imageMode');
        expect(fn).toContain('reference_image_urls');
        expect(fn).toContain("imageMode === 'multi_reference'");
        expect(fn).not.toMatch(/if \(!firstFrameUrl\) \{\s*notify\('请先生成并选中首帧/);
    });

    it('missing-video batch includes scenes without first frames in multi_reference', () => {
        const stateSource = readSource('web/js/storyboard/auto_missing_videos_state.js');
        expect(stateSource).toContain("state.videoImageMode === 'multi_reference'");
        expect(stateSource).toContain('if (!isMultiRef && !scene.firstFrameUrl) return false');
        expect(stateSource).toContain('全能参考逐个生成视频');
        expect(stateSource).not.toContain('（全能参考：首帧+角色/场景参考+画风参考）');
    });

    it('mode selector copy explains skipping storyboard images', () => {
        const renderSource = readSource('web/js/storyboard/render.js');
        expect(renderSource).toContain('可不生成分镜图，直接用角色/场景/道具参考图生视频');
        expect(renderSource).toContain('将使用分镜角色/场景/道具参考图');
    });
});
