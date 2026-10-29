import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

function createFakeWindow() {
    const anchor = {
        href: '',
        download: '',
        style: {},
        click: vi.fn(),
        remove: vi.fn(),
        parentNode: null,
    };
    const win = {
        location: {
            origin: 'https://site.example.com',
            href: 'https://site.example.com/',
            assign: vi.fn(),
        },
        localStorage: { getItem: vi.fn(() => 'token-abc') },
        document: {
            body: { appendChild: vi.fn() },
            createElement: vi.fn(() => anchor),
        },
        redirectToLogin: vi.fn(),
        __anchor: anchor,
    };
    return win;
}

function loadDownloadModule(win) {
    const source = fs.readFileSync(path.resolve('web/js/download_attachment.js'), 'utf8');
    const factory = new Function('window', 'globalThis', `${source}\n;return window;`);
    return factory(win, win);
}

function jsonResponse(payload) {
    return {
        ok: true,
        status: 200,
        headers: {
            get: (name) => (String(name).toLowerCase() === 'content-type' ? 'application/json' : null),
        },
        json: async () => payload,
    };
}

describe('downloadWithAuth 下载通道选择', () => {
    beforeEach(() => {
        vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ success: true, redirect_url: 'https://cdn.example.com/signed?attname=a.png' })));
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    test('本站 /upload/workflow 相对路径走 /api/download，url 参数补全为绝对地址', async () => {
        const win = createFakeWindow();
        const mod = loadDownloadModule(win);

        await mod.downloadWithAuth('/upload/workflow/9/photo.jpg', 'photo.jpg');

        expect(win.__anchor.click).not.toHaveBeenCalled();
        expect(global.fetch).toHaveBeenCalledTimes(1);
        const calledUrl = global.fetch.mock.calls[0][0];
        expect(calledUrl.startsWith('/api/download?')).toBe(true);
        const params = new URLSearchParams(calledUrl.split('?')[1]);
        expect(params.get('url')).toBe('https://site.example.com/upload/workflow/9/photo.jpg');
        expect(params.get('filename')).toBe('photo.jpg');
        expect(params.get('format')).toBe('json');
        // 认证走 Authorization 头，token 不进 URL
        expect(global.fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer token-abc');
        expect(win.location.assign).toHaveBeenCalledWith('https://cdn.example.com/signed?attname=a.png');
    });

    test('本站 /upload/cache 相对路径走 /api/download 且保持相对路径', async () => {
        const win = createFakeWindow();
        const mod = loadDownloadModule(win);

        await mod.downloadWithAuth('/upload/cache/2026-10-01/a.png', 'a.png');

        const params = new URLSearchParams(global.fetch.mock.calls[0][0].split('?')[1]);
        expect(params.get('url')).toBe('/upload/cache/2026-10-01/a.png');
        expect(win.__anchor.click).not.toHaveBeenCalled();
    });

    test('非 /upload/ 的同源相对路径仍直接 <a download>', async () => {
        const win = createFakeWindow();
        const mod = loadDownloadModule(win);

        await mod.downloadWithAuth('/files/report.pdf', 'report.pdf');

        expect(global.fetch).not.toHaveBeenCalled();
        expect(win.__anchor.href).toBe('/files/report.pdf');
        expect(win.__anchor.download).toBe('report.pdf');
        expect(win.__anchor.click).toHaveBeenCalledTimes(1);
    });

    test('绝对 CDN URL 保持原样进入 /api/download', async () => {
        const win = createFakeWindow();
        const mod = loadDownloadModule(win);
        const cdnUrl = 'https://cdn.example.com/key-no-ext?e=123&token=x';

        await mod.downloadWithAuth(cdnUrl, '生成结果1.png');

        const params = new URLSearchParams(global.fetch.mock.calls[0][0].split('?')[1]);
        expect(params.get('url')).toBe(cdnUrl);
        expect(win.location.assign).toHaveBeenCalledWith('https://cdn.example.com/signed?attname=a.png');
    });

    test('blob URL 直接 <a download>，不走 /api/download', async () => {
        const win = createFakeWindow();
        const mod = loadDownloadModule(win);

        await mod.downloadWithAuth('blob:https://site.example.com/uuid', 'x.png');

        expect(global.fetch).not.toHaveBeenCalled();
        expect(win.__anchor.href).toBe('blob:https://site.example.com/uuid');
        expect(win.__anchor.click).toHaveBeenCalledTimes(1);
    });
});

describe('ensureDownloadExtension 下载文件名扩展名兜底', () => {
    test('名称已带图片扩展名时原样返回', () => {
        const win = createFakeWindow();
        const mod = loadDownloadModule(win);
        expect(mod.ensureDownloadExtension('photo.JPG', 'ignored', 'png')).toBe('photo.JPG');
    });

    test('生成结果名无扩展名时从 URL 路径提取', () => {
        const win = createFakeWindow();
        const mod = loadDownloadModule(win);
        expect(mod.ensureDownloadExtension('生成结果1', 'https://cdn.example.com/abc.jpg?e=1', 'png')).toBe('生成结果1.jpg');
    });

    test('URL 也无扩展名时按 fallback 兜底', () => {
        const win = createFakeWindow();
        const mod = loadDownloadModule(win);
        expect(mod.ensureDownloadExtension('生成结果', 'https://cdn.example.com/uuid-key', 'png')).toBe('生成结果.png');
    });

    test('名称为空时用 image.<ext> 兜底', () => {
        const win = createFakeWindow();
        const mod = loadDownloadModule(win);
        expect(mod.ensureDownloadExtension('', '/upload/workflow/1/a.webp', 'png')).toBe('image.webp');
        expect(mod.ensureDownloadExtension(null, '', 'png')).toBe('image.png');
    });
});
