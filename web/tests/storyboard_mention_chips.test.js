// 输入框标记胶囊：标记扫描、短 id 生成，以及胶囊/悬停预览的挂载点存在性。
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
    scanFrameMentionTokens,
    shortImageId,
} from '../js/storyboard/chat_mention_chips.js';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('scanFrameMentionTokens', () => {
    it('finds tokens with offsets and keeps insertion order', () => {
        const text = '从 @首帧图 切到 @尾帧图 结束';
        expect(scanFrameMentionTokens(text)).toEqual([
            { key: 'first', token: '@首帧图', start: 2, end: 6 },
            { key: 'last', token: '@尾帧图', start: 10, end: 14 },
        ]);
    });

    it('does not match longer chinese words', () => {
        expect(scanFrameMentionTokens('看 @首帧图片')).toEqual([]);
        expect(scanFrameMentionTokens('没有标记')).toEqual([]);
    });
});

describe('shortImageId', () => {
    it('extracts hex basenames up to 16 chars', () => {
        expect(shortImageId('https://cdn.test/upload/21b39c5b1fe24486.png')).toBe('21b39c5b');
        expect(shortImageId('https://cdn.test/aabbccddeeff00112233.jpg?x=1')).toBe('aabbccdd');
    });

    it('hashes non-hex urls to a stable 16-hex id', () => {
        const a = shortImageId('https://cdn.test/scene_第一集.png');
        const b = shortImageId('https://cdn.test/scene_第一集.png');
        const c = shortImageId('https://cdn.test/scene_第二集.png');
        expect(a).toBe(b);
        expect(a).toMatch(/^[0-9a-f]{8}$/);
        expect(a).not.toBe(c);
    });
});

describe('chip mirror and hover preview mount points', () => {
    it('composer renders a mirror layer and chips module hooks panel patches', () => {
        const renderSource = readSource('web/js/storyboard/render.js');
        expect(renderSource).toContain('data-chat-textarea-mirror');
        expect(renderSource).toContain('syncChatMentionChips()');
    });

    it('mention popup entries and frame buttons carry hover preview urls', () => {
        const renderSource = readSource('web/js/storyboard/render.js');
        // 首尾帧按钮
        expect(renderSource).toMatch(/renderFrameMentionButton[\s\S]{0,200}data-hover-preview/);
        // 角色/场景/道具条目：有图才带预览属性
        expect(renderSource).toMatch(/item\.avatar \|\| item\.reference_image[\s\S]{0,120}data-hover-preview/);
        const eventsSource = readSource('web/js/storyboard/events.js');
        // 左侧提示词下拉的条目同样支持悬停预览
        expect(eventsSource).toContain('row.dataset.hoverPreview = frame.url');
        expect(eventsSource).toContain('row.dataset.hoverPreview = aurl');
    });

    it('chips record token end and left dropdown previews open to the right', () => {
        const chipsSource = readSource('web/js/storyboard/chat_mention_chips.js');
        // 胶囊记录标记结束位置：点击时光标定位到标记之后，不落进遮盖区
        expect(chipsSource).toContain('data-end="${end}"');
        expect(chipsSource).toMatch(/closest\('\.chat-mention-chip'\)[\s\S]{0,600}setSelectionRange/);
        // 左侧提示词下拉（asset-dropdown）内的预览在右侧展开
        expect(chipsSource).toContain("anchor.closest('.asset-dropdown') ? 'right' : 'top'");
    });
});
