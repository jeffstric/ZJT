/**
 * 故事板↔工作流画布互转·前端侧（d957af0ed）。
 *
 * 契约：
 * - 画布→故事板：无 id 拦截不发请求；先 flushAutoSave 再 POST /api/storyboard/from-workflow；
 *   成功跳 /storyboard?id=…；失败恢复按钮并 toast
 * - 故事板→画布：转换中防重入（_convertingCanvas）
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { describe, expect, it, vi } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const switchSource = fs.readFileSync(
    path.join(root, 'web/js/workflow_storyboard_switch.js'), 'utf8');
const apiSource = fs.readFileSync(path.join(root, 'web/js/storyboard/api.js'), 'utf8');
const eventsSource = fs.readFileSync(
    path.join(root, 'web/js/storyboard/events.js'), 'utf8');

function loadSwitch({ workflowId = '42' } = {}) {
    const clicks = [];
    const fetchMock = vi.fn();
    const btn = {
        disabled: false,
        dataset: {},
        addEventListener: (ev, fn) => clicks.push([ev, fn]),
    };
    const document = {
        readyState: 'complete',
        getElementById: (id) => (id === 'toStoryboardBtn' ? btn : null),
        addEventListener: vi.fn(),
    };
    const context = {
        window: {
            location: { search: workflowId ? `?id=${workflowId}` : '' },
            alert: vi.fn(),
        },
        document,
        localStorage: {
            getItem: (k) => (k === 'auth_token' ? 'tok' : '7'),
        },
        fetch: fetchMock,
        URLSearchParams,
        setTimeout,
        Promise,
    };
    context.showToast = vi.fn();
    context.globalThis = context;
    context.flushAutoSave = vi.fn();
    vm.createContext(context);
    vm.runInContext(switchSource, context);
    return { context, btn, clicks, fetchMock, toast: context.showToast, flush: context.flushAutoSave };
}

const resp = (ok, data) => ({
    ok,
    status: ok ? 200 : 500,
    json: async () => data,
});

describe('画布 → 故事板 转换', () => {
    it('按钮点击绑定一次（防重复绑定）', () => {
        const { btn, clicks } = loadSwitch();
        expect(clicks).toHaveLength(1);
        expect(btn.dataset.conversionBound).toBe('1');
    });

    it('无 workflow id：提示且不发请求', () => {
        const { context, clicks, fetchMock } = loadSwitch({ workflowId: '' });
        clicks[0][1]();
        expect(fetchMock).not.toHaveBeenCalled();
        expect(context.showToast).toHaveBeenCalled();
        expect(context.showToast.mock.calls[0][0]).toContain('保存');
    });

    it('成功：先 flushAutoSave，POST 带 Bearer 头，跳转 storyboard 编辑器', async () => {
        const { context, clicks, fetchMock, flush } = loadSwitch({ workflowId: '42' });
        fetchMock.mockResolvedValue(resp(true, { success: true, storyboard_id: 88 }));

        await clicks[0][1]();
        await new Promise((r) => setTimeout(r, 900)); // 等待 FLUSH_WAIT_MS=800

        expect(flush).toHaveBeenCalled();
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe('/api/storyboard/from-workflow');
        expect(init.method).toBe('POST');
        expect(init.headers.Authorization).toBe('Bearer tok');
        expect(init.headers['X-User-Id']).toBe('7');
        expect(JSON.parse(init.body)).toEqual({ workflow_id: 42 });
        expect(context.window.location.href).toBe('/storyboard?id=88');
    });

    it('失败：按钮恢复可点并展示后端 detail', async () => {
        const { btn, clicks, fetchMock } = loadSwitch({ workflowId: '42' });
        fetchMock.mockResolvedValue(resp(false, { success: false, error: '画布为空' }));

        await clicks[0][1]();
        await new Promise((r) => setTimeout(r, 900));

        expect(btn.disabled).toBe(false);
        expect(fetchMock).toHaveBeenCalled();
    });

    it('裸 token 自动补 Bearer 前缀', async () => {
        const { clicks, fetchMock } = loadSwitch({ workflowId: '42' });
        fetchMock.mockResolvedValue(resp(true, { success: true, storyboard_id: 1 }));
        await clicks[0][1]();
        await new Promise((r) => setTimeout(r, 900));
        // localStorage stub 返回 'tok'（无 Bearer），请求头应补全
        expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer tok');
    });
});

describe('故事板 → 画布 转换（api/events 侧）', () => {
    it('convertStoryboardToWorkflow 存在且调用 to-workflow 端点', () => {
        expect(apiSource).toContain('convertStoryboardToWorkflow');
        expect(apiSource).toContain('/to-workflow');
    });

    it('转换中防重入（_convertingCanvas 守卫）', () => {
        expect(eventsSource).toContain('_convertingCanvas');
        expect(eventsSource).toContain('convertStoryboardToWorkflow');
    });
});
