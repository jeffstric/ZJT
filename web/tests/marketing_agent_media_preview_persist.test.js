/**
 * 营销智能体消息媒体入库持久化守卫（修复：blob: 预览地址入库后刷新丢图）。
 *
 * 契约：
 * - renderMediaPreview：url 不可持久化（blob:/data:）→ 占位文本，不输出媒体标签；
 *   http(s)/站内路径 → 正常 <img>（含 data-full-src）
 * - stripNonPersistentMediaTags：appendMessageToBackend 入库兜底清洗，src 为
 *   blob:/data: 的 img/video/audio 标签替换为占位文本，普通媒体标签原样保留
 * - handleSend image/video 分支与 submitVerificationAnswer：发送前限时等待上传
 * - zh-CN/en 两语言包均定义 media_not_persisted_hint
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/marketing_agent.js'), 'utf8');

const HINT = '（媒体上传未完成，未能保存）';
// 与 zh-CN/marketing_agent.json 同模板（getMediaPreviewLabel 依赖）
const zhTemplates = {
    media_not_persisted_hint: HINT,
    image_label: '[图片{num}]',
    video_label: '[视频{num}]',
    audio_tag: '[音频]',
};
const mockT = (key, params = {}) => {
    const tpl = zhTemplates[key] ?? key;
    return String(tpl).replace(/\{(\w+)\}/g, (_, name) => params[name] ?? `{${name}}`);
};

// 提取 isReusableMediaUrl（blob/data 排除的唯一权威实现）
function extractIsReusableMediaUrl() {
    const start = source.indexOf('function isReusableMediaUrl(');
    expect(start, 'isReusableMediaUrl 应存在于 marketing_agent.js').toBeGreaterThanOrEqual(0);
    const end = source.indexOf('function collectUrlOnlyImageUrls(', start);
    expect(end).toBeGreaterThan(start);
    const block = source.slice(start, end);
    return new Function(`${block}\nreturn isReusableMediaUrl;`)();
}

// 提取 getMediaPreviewLabel + renderMediaPreview（两者相邻，同片提取）
function createRenderMediaPreview() {
    const start = source.indexOf('function getMediaPreviewLabel(');
    expect(start, 'getMediaPreviewLabel 应存在于 marketing_agent.js').toBeGreaterThanOrEqual(0);
    const end = source.indexOf('function buildUserMessageContent(', start);
    expect(end).toBeGreaterThan(start);
    const block = source.slice(start, end);
    const window = { t: mockT };
    const escapeHtml = (s) => String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const factory = new Function(
        'window', 'escapeHtml', 'escapeHtmlAttr', 'proxyImageUrl', 'proxyDownloadUrl', 'isReusableMediaUrl',
        `${block};\nreturn { renderMediaPreview };`
    );
    return factory(
        window, escapeHtml, escapeHtml,
        (url) => url, (url) => url, extractIsReusableMediaUrl()
    );
}

function extractStripNonPersistentMediaTags() {
    const start = source.indexOf('function stripNonPersistentMediaTags(');
    expect(start, 'stripNonPersistentMediaTags 应存在于 marketing_agent.js').toBeGreaterThanOrEqual(0);
    const end = source.indexOf('async function appendMessageToBackend(', start);
    expect(end).toBeGreaterThan(start);
    const block = source.slice(start, end);
    const window = { t: mockT };
    return new Function('window', `${block}\nreturn stripNonPersistentMediaTags;`)(window);
}

const { renderMediaPreview } = createRenderMediaPreview();
const stripNonPersistentMediaTags = extractStripNonPersistentMediaTags();

describe('renderMediaPreview 持久化守卫', () => {
    it('blob: 图片 → 占位文本，不输出 <img>', () => {
        const html = renderMediaPreview({ type: 'image', url: 'blob:http://192.168.200.70:9003/abc', thumbnailUrl: 'blob:http://192.168.200.70:9003/abc' }, {});
        expect(html).not.toContain('<img');
        expect(html).toContain('[图片1]');
        expect(html).toContain(HINT);
    });

    it('data: 图片 → 占位文本，不输出 <img>', () => {
        const html = renderMediaPreview({ type: 'image', url: 'data:image/png;base64,iVBORw0KGgo=', thumbnailUrl: 'data:image/png;base64,iVBORw0KGgo=' }, {});
        expect(html).not.toContain('<img');
        expect(html).toContain(HINT);
    });

    it('http(s) 图片 → 正常 <img> 且含 data-full-src', () => {
        const html = renderMediaPreview({ type: 'image', url: 'https://cdn.example.com/a.png', thumbnailUrl: 'https://cdn.example.com/a_thumb.jpg' }, {});
        expect(html).toContain('<img');
        expect(html).toContain('data-full-src="https://cdn.example.com/a.png"');
        expect(html).toContain('src="https://cdn.example.com/a_thumb.jpg"');
    });

    it('站内路径图片（/upload/...）→ 正常 <img>', () => {
        const html = renderMediaPreview({ type: 'image', url: '/upload/marketing/pic/s1/a.png', thumbnailUrl: '/upload/marketing/pic/s1/thumb/a_thumb.jpg' }, {});
        expect(html).toContain('<img');
        expect(html).toContain('data-full-src="/upload/marketing/pic/s1/a.png"');
    });

    it('blob: 视频 → 占位文本，不输出 <video>', () => {
        const html = renderMediaPreview({ type: 'video', url: 'blob:http://localhost:9003/v1' }, {});
        expect(html).not.toContain('<video');
        expect(html).toContain(HINT);
    });

    it('http 视频 → 正常 <video>', () => {
        const html = renderMediaPreview({ type: 'video', url: 'https://cdn.example.com/v.mp4' }, {});
        expect(html).toContain('<video');
    });
});

describe('stripNonPersistentMediaTags 入库兜底清洗', () => {
    it('blob: img 被替换为占位文本，普通 img 原样保留', () => {
        const content = '<p>生成视频</p><img src="blob:http://x/b1" alt="[图片2]"><img src="/upload/a.png" alt="ok">';
        const cleaned = stripNonPersistentMediaTags(content);
        expect(cleaned).not.toContain('blob:');
        expect(cleaned).toContain(HINT);
        expect(cleaned).toContain('<img src="/upload/a.png" alt="ok">');
    });

    it('blob: video/audio 同样被清洗', () => {
        const content = '<video src="blob:http://x/v1" controls></video><audio src="data:audio/mp3;base64,AA" controls></audio>';
        const cleaned = stripNonPersistentMediaTags(content);
        expect(cleaned).not.toContain('<video');
        expect(cleaned).not.toContain('<audio');
        expect(cleaned).toContain(HINT);
    });

    it('无 blob:/data: 的内容原样返回（快速路径）', () => {
        const content = '<p>普通文本</p><img src="/upload/a.png">';
        expect(stripNonPersistentMediaTags(content)).toBe(content);
    });

    it('非字符串输入原样返回', () => {
        expect(stripNonPersistentMediaTags(undefined)).toBeUndefined();
        expect(stripNonPersistentMediaTags(null)).toBeNull();
    });
});

describe('发送路径契约（防回归）', () => {
    it('appendMessageToBackend 入口调用 stripNonPersistentMediaTags', () => {
        const start = source.indexOf('async function appendMessageToBackend(');
        const body = source.slice(start, start + 600);
        expect(body).toContain('stripNonPersistentMediaTags(content)');
    });

    it('handleSend image/video 分支发送前等待图片上传完成', () => {
        const guardRe = /if \(!isAgentMode && mediaItems\.value\.some\(m => m\.type === 'image' && m\.uploading\)\) \{\s*await waitForAgentImagesUploaded\(10000\);/;
        expect(source).toMatch(guardRe);
    });

    it('submitVerificationAnswer 发送前等待图片上传完成', () => {
        const start = source.indexOf('async function submitVerificationAnswer(');
        const body = source.slice(start, start + 900);
        expect(body).toContain('waitForAgentImagesUploaded(10000)');
    });
});

describe('i18n 契约', () => {
    it('zh-CN/en 语言包均定义 media_not_persisted_hint', () => {
        const zh = JSON.parse(fs.readFileSync(path.join(root, 'web/i18n/locales/zh-CN/marketing_agent.json'), 'utf8'));
        const en = JSON.parse(fs.readFileSync(path.join(root, 'web/i18n/locales/en/marketing_agent.json'), 'utf8'));
        expect(zh.media_not_persisted_hint).toBeTruthy();
        expect(en.media_not_persisted_hint).toBeTruthy();
    });
});
