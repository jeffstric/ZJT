/**
 * 营销页「生成中」进度卡片（038e05131）与裸音频 URL 内联播放器（0163a57a1）。
 *
 * 契约：
 * - 进度文案由 i18n 模板动态构造正则（{done}→数字或?，{total}→数字），locale 变化重建
 * - done/total 均为数字 → 确定进度条（width:pct%，pct 上限 100）；'?'→不定进度
 * - 非 300 字内进度文案返回 null 走 Markdown 管线
 * - 裸音频 URL（含 TTS 试听链接）转 <audio controls>（旧前瞻过窄曾让 mp3。 粘连降级）
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/marketing_agent.js'), 'utf8');

const start = source.indexOf('let generatingPendingMatchers');
const end = source.indexOf('// 渲染 Markdown');
const block = source.slice(start, end);

const ICONS = {
    image: '<svg>img-icon</svg>',
    video: '<svg>video-icon</svg>',
    generic: '<svg>generic-icon</svg>',
};

// 与 zh-CN/marketing_agent.json 同模板
const zhTemplates = {
    image_generating_progress: '图片生成中... ({done}/{total})',
    video_generating_progress: '视频生成中... ({done}/{total})',
    generating_image: '正在生成图片，请稍候...',
    generating_video: '正在生成视频，请稍候...',
    generating_placeholder: '生成中...',
    image_task_suffix: '，图片生成中...',
    video_task_suffix: '，视频生成中...',
    image_generating_label: '图片生成中…',
    video_generating_label: '视频生成中…',
};

function createCardFn({ locale = 'zh-CN', escapeHtml = (s) => s } = {}) {
    const window = {
        t: (key) => zhTemplates[key] ?? key,
        ZJTi18n: { getLocale: () => locale },
    };
    const factory = new Function('window', 'escapeHtml', '__icons', `
        ${block};
        return { buildGeneratingPendingCard, getGeneratingPendingMatchers };
    `);
    return factory(window, escapeHtml, ICONS);
}

describe('buildGeneratingPendingCard 进度识别', () => {
    it('数字进度 → 确定进度条与 2/5 计数', () => {
        const { buildGeneratingPendingCard } = createCardFn();
        const html = buildGeneratingPendingCard('图片生成中... (2/5)');
        expect(html).toContain('data-gen-type="image"');
        expect(html).toContain('2/5');
        expect(html).toContain('width:40%');
    });

    it('进度百分比上限 100（done>total 不越界）', () => {
        const { buildGeneratingPendingCard } = createCardFn();
        const html = buildGeneratingPendingCard('视频生成中... (9/5)');
        expect(html).toContain('data-gen-type="video"');
        expect(html).toContain('width:100%');
    });

    it("轮询退避占位 '?' → 不定进度动画但保留计数", () => {
        const { buildGeneratingPendingCard } = createCardFn();
        const html = buildGeneratingPendingCard('视频生成中... (?/5)');
        expect(html).toContain('gen-pending-fill--indeterminate');
        expect(html).toContain('?/5');
    });

    it('初始提交气泡（后缀文案）→ 不定进度无计数', () => {
        const { buildGeneratingPendingCard } = createCardFn();
        const html = buildGeneratingPendingCard('已提交任务，图片生成中...');
        expect(html).toContain('data-gen-type="image"');
        expect(html).toContain('gen-pending-fill--indeterminate');
        expect(html).not.toContain('gen-pending-count');
    });

    it('等待中/占位文案各归其类', () => {
        const { buildGeneratingPendingCard } = createCardFn();
        expect(buildGeneratingPendingCard('正在生成图片，请稍候...')).toContain('data-gen-type="image"');
        expect(buildGeneratingPendingCard('正在生成视频，请稍候...')).toContain('data-gen-type="video"');
        expect(buildGeneratingPendingCard('生成中...')).toContain('data-gen-type="generic"');
    });

    it('非进度文案返回 null（继续走 Markdown 管线）', () => {
        const { buildGeneratingPendingCard } = createCardFn();
        expect(buildGeneratingPendingCard('这是普通回复内容')).toBeNull();
        expect(buildGeneratingPendingCard('')).toBeNull();
        expect(buildGeneratingPendingCard(null)).toBeNull();
    });

    it('超过 300 字的文案直接返回 null', () => {
        const { buildGeneratingPendingCard } = createCardFn();
        expect(buildGeneratingPendingCard('图片生成中... (2/5)' + '长'.repeat(300))).toBeNull();
    });

    it('locale 变化后匹配器重建', () => {
        const { getGeneratingPendingMatchers } = createCardFn({ locale: 'zh-CN' });
        const first = getGeneratingPendingMatchers();
        const second = createCardFn({ locale: 'en-US' }).getGeneratingPendingMatchers();
        expect(second).not.toBe(first);
        // 同 locale 命中缓存
        const fn = createCardFn({ locale: 'zh-CN' });
        expect(fn.getGeneratingPendingMatchers()).toBe(fn.getGeneratingPendingMatchers());
    });
});

describe('裸媒体 URL 内联播放器（0163a57a1 回归）', () => {
    const renderStart = source.indexOf('function renderMarkdown');
    const renderEnd = source.indexOf('// 步骤5');
    const renderSrc = source.slice(renderStart, renderEnd);

    it('音频 URL 正则存在且覆盖 mp3/wav/m4a（试听链接渲染为播放器）', () => {
        expect(renderSrc).toContain('audioUrlPattern');
        expect(renderSrc).toMatch(/mp3\|wav\|m4a\|ogg\|aac\|flac/);
    });

    it('视频/音频前瞻保守：扩展名后跟字母或路径符号不转换', () => {
        // 旧前瞻（空白/结尾）过窄曾让 "mp3。"/"mp33." 粘连形态静默失败
        expect(renderSrc).toContain('(?=$|[^\\w?=&%#+~./-]|\\d)');
    });
});
