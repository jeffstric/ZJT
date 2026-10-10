import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
    findFrameMentionError,
    isH3ReferenceVideoModel,
    promptHasFrameMention,
    shouldUseH3KeyframeRef,
} from '../js/storyboard/frame_mention.js';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('storyboard frame mention tokens', () => {
    it('does not treat a longer Chinese word as the frame token', () => {
        expect(promptHasFrameMention('看 @首帧图片')).toBe(false);
        expect(promptHasFrameMention('从 @首帧图 到 @尾帧图')).toBe(true);
    });

    it('routes only H3 reference mode with a token to the mixed model', () => {
        const h3 = { short_key: 'minimax_h3_r2v', key: 'minimax_h3_reference_to_video' };
        expect(shouldUseH3KeyframeRef('multi_reference', h3, '@首帧图')).toBe(true);
        expect(shouldUseH3KeyframeRef('first_last_frame', h3, '@首帧图')).toBe(false);
        expect(shouldUseH3KeyframeRef('multi_reference', h3, '没有标记')).toBe(false);
        expect(isH3ReferenceVideoModel({ key: 'minimax_h3' })).toBe(false);
        expect(isH3ReferenceVideoModel({ short_key: 'minimax_h3_t2v' })).toBe(false);
        expect(findFrameMentionError({
            imageMode: 'multi_reference',
            prompt: '@尾帧图',
            firstUrl: 'https://cdn.test/first.png',
            lastUrl: '',
            model: h3,
        })).toBe('missing_last');
        expect(findFrameMentionError({
            imageMode: 'multi_reference',
            prompt: '@首帧图 @尾帧图',
            firstUrl: 'https://cdn.test/first.png',
            lastUrl: 'https://cdn.test/last.png',
            model: { key: 'seedance_2_0_image_to_video', max_multi_ref_images: 9 },
        })).toBe(null);
    });

    it('reference mode keeps a real last-frame slot and sends frame urls', () => {
        const stateSource = readSource('web/js/storyboard/state.js');
        const eventsSource = readSource('web/js/storyboard/events.js');
        const start = stateSource.indexOf('export function syncVideoMediaFromScene');
        const end = stateSource.indexOf('export function refreshSceneFirstFrameSlot', start);
        const fn = stateSource.slice(start, end);
        expect(fn).toContain("item.role === 'last_frame'");
        expect(fn).not.toContain("role: 'reference'");
        expect(eventsSource).toContain("if (!items.some(item => item.role === 'last_frame')) return 'last_frame';");
        expect(eventsSource).toContain('frame_first_url');
        expect(eventsSource).toContain('currentVideoFrameUrls()');
        const renderSource = readSource('web/js/storyboard/render.js');
        expect(renderSource).toContain('data-mention-item="首帧图"');
        expect(renderSource).toContain('data-mention-item="尾帧图"');
        expect(renderSource).toContain('可不生成分镜图，直接用角色/场景/道具参考图生视频');
        expect(renderSource).toContain('上传参考图；不上传时将使用分镜角色/场景/道具参考图');
    });
});
