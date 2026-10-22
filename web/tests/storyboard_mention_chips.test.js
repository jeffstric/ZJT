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

    it('matches tokens with an embedded unique id', () => {
        expect(scanFrameMentionTokens('前面 @首帧图:1c88f7a9 中间 @尾帧图:0be032f5 结束')).toEqual([
            { key: 'first', token: '@首帧图:1c88f7a9', start: 3, end: 16 },
            { key: 'last', token: '@尾帧图:0be032f5', start: 20, end: 33 },
        ]);
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

    it('chips record token range, force-wrap straddling tokens, and previews open right', () => {
        const chipsSource = readSource('web/js/storyboard/chat_mention_chips.js');
        // 胶囊记录标记区间：点击定位到标记之后；跨行时强制换行独占一行
        expect(chipsSource).toContain('data-start="${start}"');
        expect(chipsSource).toContain('data-end="${end}"');
        expect(chipsSource).toContain('fixStraddlingTokens');
        expect(chipsSource).toContain("ta.value[start - 1] !== '\\n'");
        expect(chipsSource).toMatch(/closest\('\.chat-mention-chip'\)[\s\S]{0,600}setSelectionRange/);
        // 左侧提示词下拉与 @ 弹窗内的预览在右侧展开，不盖选项
        expect(chipsSource).toContain("anchor.closest('.asset-dropdown, .mention-popup') ? 'right' : 'top'");
        // 标记原子化：删除触及标记整枚删除、标记中间插入被阻止
        expect(chipsSource).toContain('handleTokenBeforeInput');
        expect(chipsSource).toMatch(/beforeinput[\s\S]{0,80}handleTokenBeforeInput/);
        expect(chipsSource).toContain("type.startsWith('delete')");
        expect(chipsSource).toContain("type.startsWith('insert')");
    });
});
