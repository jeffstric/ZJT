/**
 * 营销智能体「重新生成/重新编辑」参考媒体相对路径兼容（事故回归）。
 *
 * 背景（da844815 水杯会话）：后端 13572 修复后参考图统一以本站 /upload/ 相对路径
 * 落库（host 无关存储），而前端重新生成链路用 isHttpUrl（要求 http 开头）过滤
 * get-status meta 返回的 frame_images/reference_images，相对路径全部被滤掉，
 * 重新生成退化成 /api/text-to-image 纯文生图——生成结果与参考图毫无关系。
 *
 * 契约：
 * - handleGeneratedResultRegenerate：/upload/ 相对路径参考图放行 → 走 /api/image-edit
 *   且 ref_image_urls 原样带上（后端 normalize_site_upload_image_url 直接消费相对路径）
 * - 存量绝对 URL（http/https）参考图不受影响
 * - blob:/data:/空仍被拦截（安全口径不放宽，与 isReusableMediaUrl 一致）
 * - 视频重新生成：相对路径 reference_images / reference_audio 同样放行
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/marketing_agent.js'), 'utf8');

// 提取 isHttpUrl（真实实现）
function extractIsHttpUrl() {
    const start = source.indexOf('function isHttpUrl(');
    expect(start, 'isHttpUrl 应存在于 marketing_agent.js').toBeGreaterThanOrEqual(0);
    const end = source.indexOf('function getCurrentImageServerUrl(', start);
    expect(end).toBeGreaterThan(start);
    return new Function(`${source.slice(start, end)}\nreturn isHttpUrl;`)();
}

// 提取 isReusableMediaUrl（blob/data 排除的唯一权威实现）
function extractIsReusableMediaUrl() {
    const start = source.indexOf('function isReusableMediaUrl(');
    expect(start, 'isReusableMediaUrl 应存在于 marketing_agent.js').toBeGreaterThanOrEqual(0);
    const end = source.indexOf('function collectUrlOnlyImageUrls(', start);
    expect(end).toBeGreaterThan(start);
    return new Function(`${source.slice(start, end)}\nreturn isReusableMediaUrl;`)();
}

// 提取 handleGeneratedResultRegenerate（→ submitRegeneratedTask 之前的完整函数体），
// 依赖全部注入以便观察提交目标与表单内容
function buildHarness({ meta, task, genType }) {
    const resolvedTask = task || { id: 26, category: 'image_edit', categories: ['text_to_image'] };
    const submittedUrls = [];
    const postedForms = [];
    const errors = [];
    const notices = [];
    const regenTasks = [];
    const window = {
        t: (key) => key,
        TaskConfig: { getTaskById: (id) => (id === resolvedTask.id ? resolvedTask : null) },
    };
    const deps = {
        window,
        isHttpUrl: extractIsHttpUrl(),
        isReusableMediaUrl: extractIsReusableMediaUrl(),
        currentSessionId: { value: 'sess-1' },
        userId: { value: 55 },
        authToken: { value: 'tok' },
        fetchGeneratedTaskMeta: async () => meta,
        uiResolutionToImageSize: (raw) => raw || '',
        imageResolutionLabels: () => [],
        FormData: class {
            constructor() { this.entries = {}; }
            append(key, value) { this.entries[key] = String(value); }
        },
        axios: {
            post: async (url, form) => {
                submittedUrls.push(url);
                postedForms.push(form);
                return { data: { project_ids: [13987] } };
            },
        },
        submitRegeneratedTask: (type, projectIds) => regenTasks.push({ type, projectIds }),
        showError: (msg) => errors.push(msg),
        showNotice: (msg) => notices.push(msg),
    };
    const factory = new Function(
        ...Object.keys(deps),
        `${source.slice(
            source.indexOf('async function handleGeneratedResultRegenerate('),
            source.indexOf('function submitRegeneratedTask(')
        )};\nreturn handleGeneratedResultRegenerate;`
    );
    const btn = {
        getAttribute: (name) => (name === 'data-tool-id' ? String(resolvedTask.id) : genType),
        disabled: false,
    };
    const run = () => factory(...Object.values(deps))(btn);
    return { run, submittedUrls, postedForms, errors, notices, regenTasks };
}

const REL = (n) => `/upload/marketing/pic/da844815-ebb3-4371-90e1-bd0791f2ee5e/2026111809563${n}_x.jpg`;

describe('重新生成：参考媒体相对路径兼容（da844815 事故回归）', () => {
    it('图片编辑任务（/upload/ 相对路径参考图）→ /api/image-edit 且 ref_image_urls 带全部参考图', async () => {
        const h = buildHarness({
            genType: 'image',
            meta: {
                task_type: 26,
                prompt: 'Double 11 poster',
                ratio: '16:9',
                image_size: '1K',
                frame_images: [REL(1), REL(2), REL(3), REL(4), REL(5)],
                reference_images: [],
                reference_video: null,
                reference_audio: null,
            },
        });
        await h.run();
        expect(h.submittedUrls).toEqual(['/api/image-edit']);
        expect(h.postedForms[0].entries.ref_image_urls.split(',')).toEqual([REL(1), REL(2), REL(3), REL(4), REL(5)]);
        expect(h.postedForms[0].entries.ratio).toBe('16:9');
        expect(h.postedForms[0].entries.task_id).toBe('26');
        expect(h.errors).toEqual([]);
        expect(h.regenTasks).toEqual([{ type: 'image', projectIds: [13987] }]);
    });

    it('存量绝对 URL 参考图 → 仍走 /api/image-edit（不回归旧数据）', async () => {
        const h = buildHarness({
            genType: 'image',
            meta: {
                task_type: 26,
                prompt: 'p',
                ratio: '1:1',
                frame_images: ['https://zjt-dev.perseids.cn/upload/a.jpg'],
                reference_images: [],
            },
        });
        await h.run();
        expect(h.submittedUrls).toEqual(['/api/image-edit']);
        expect(h.postedForms[0].entries.ref_image_urls).toBe('https://zjt-dev.perseids.cn/upload/a.jpg');
    });

    it('无参考图 → /api/text-to-image（不误带 ref_image_urls）', async () => {
        const h = buildHarness({
            genType: 'image',
            meta: { task_type: 26, prompt: 'p', ratio: '1:1', frame_images: [], reference_images: [] },
        });
        await h.run();
        expect(h.submittedUrls).toEqual(['/api/text-to-image']);
        expect(h.postedForms[0].entries.ref_image_urls).toBeUndefined();
        expect(h.postedForms[0].entries.aspect_ratio).toBe('1:1');
    });

    it('blob:/data: 参考图仍被拦截 → 退化为文生图（安全口径不放宽）', async () => {
        const h = buildHarness({
            genType: 'image',
            meta: {
                task_type: 26,
                prompt: 'p',
                ratio: '1:1',
                frame_images: ['blob:https://x/abc', 'data:image/png;base64,xx'],
                reference_images: [],
            },
        });
        await h.run();
        expect(h.submittedUrls).toEqual(['/api/text-to-image']);
        expect(h.postedForms[0].entries.ref_image_urls).toBeUndefined();
    });

    it('视频多参考（相对路径 reference_images + reference_audio）→ /api/ai-app-run-image 且参数齐全', async () => {
        const h = buildHarness({
            genType: 'video',
            task: { id: 30, category: 'image_to_video', categories: ['image_to_video'] },
            meta: {
                task_type: 30,
                prompt: 'v',
                ratio: '9:16',
                duration: 5,
                resolution: '720P',
                image_mode: 'multi_reference',
                frame_images: [],
                reference_images: [REL(1), REL(2)],
                reference_video: null,
                reference_audio: '/upload/marketing/audio/voice.mp3',
            },
        });
        await h.run();
        expect(h.submittedUrls).toEqual(['/api/ai-app-run-image']);
        expect(h.postedForms[0].entries.image_mode).toBe('multi_reference');
        expect(h.postedForms[0].entries.reference_image_urls.split(',')).toEqual([REL(1), REL(2)]);
        expect(h.postedForms[0].entries.audio_urls).toBe('/upload/marketing/audio/voice.mp3');
        expect(h.postedForms[0].entries.video_urls).toBeUndefined();
    });
});
