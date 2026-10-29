/**
 * 视频高清修复页轮询契约（refactor 7634a6aa：驱动模式迁移）。
 *
 * 迁移要点：
 * - 轮询端点由 /api/runninghub-status/{id} 切换为通用 /api/get-status/{id}
 * - 响应形状为 v1 包装：{ tasks: [payload] }，取 tasks[0]
 * - SUCCESS → results 落值 + loading 收尾 + 清 interval；FAILED → 展示 reason
 * - tasks 空数组/缺 status 时不得抛错
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { describe, expect, it, vi } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const source = fs.readFileSync(path.join(root, 'web/js/pages/video_enhance.js'), 'utf8');

function loadComponent({ axios } = {}) {
  const context = {
    window: {}, console, axios,
    localStorage: { getItem: vi.fn(() => null) },
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return context.window.VideoEnhance;
}

const okCtx = (axios, overrides = {}) => ({
  projectId: 'proj-1',
  status: '',
  results: [],
  error: '',
  loading: true,
  statusInterval: 12345,
  $t: (key) => key,
  clearStatusCheck() {
    this.statusInterval = null;
  },
  ...overrides,
});

describe('checkStatus 轮询契约', () => {
  it('轮询通用端点 /api/get-status/{projectId}', async () => {
    const axios = { get: vi.fn().mockResolvedValue({ data: { tasks: [] } }) };
    const comp = loadComponent({ axios });

    await comp.methods.checkStatus.call(okCtx(axios));

    expect(axios.get.mock.calls[0][0]).toBe('/api/get-status/proj-1');
  });

  it('读取 tasks[0] 的 status/results（v1 包装形状）', async () => {
    const axios = {
      get: vi.fn().mockResolvedValue({
        data: { tasks: [{ status: 'SUCCESS', results: ['https://cdn/x.mp4'] }] },
      }),
    };
    const comp = loadComponent({ axios });
    const ctx = okCtx(axios);

    await comp.methods.checkStatus.call(ctx);

    expect(ctx.status).toBe('SUCCESS');
    expect(ctx.results).toEqual(['https://cdn/x.mp4']);
    expect(ctx.loading).toBe(false);
    expect(ctx.statusInterval).toBeNull(); // clearStatusCheck 已清
  });

  it('FAILED 状态展示后端 reason', async () => {
    const axios = {
      get: vi.fn().mockResolvedValue({
        data: { tasks: [{ status: 'FAILED', reason: '算力不足' }] },
      }),
    };
    const comp = loadComponent({ axios });
    const ctx = okCtx(axios);

    await comp.methods.checkStatus.call(ctx);

    expect(ctx.error).toBe('算力不足');
    expect(ctx.loading).toBe(false);
    expect(ctx.statusInterval).toBeNull();
  });

  it('RUNNING 状态继续轮询不清 interval', async () => {
    const axios = {
      get: vi.fn().mockResolvedValue({
        data: { tasks: [{ status: 'RUNNING' }] },
      }),
    };
    const comp = loadComponent({ axios });
    const ctx = okCtx(axios);

    await comp.methods.checkStatus.call(ctx);

    expect(ctx.status).toBe('RUNNING');
    expect(ctx.loading).toBe(true);
    expect(ctx.statusInterval).toBe(12345);
  });

  it('tasks 空数组不抛错、状态不变', async () => {
    const axios = { get: vi.fn().mockResolvedValue({ data: { tasks: [] } }) };
    const comp = loadComponent({ axios });
    const ctx = okCtx(axios);

    await expect(comp.methods.checkStatus.call(ctx)).resolves.toBeUndefined();
    expect(ctx.statusInterval).toBe(12345);
  });

  it('轮询网络异常不外抛（吞错继续下一轮）', async () => {
    const axios = { get: vi.fn().mockRejectedValue(new Error('network')) };
    const comp = loadComponent({ axios });
    const ctx = okCtx(axios);

    await expect(comp.methods.checkStatus.call(ctx)).resolves.toBeUndefined();
  });

  it('无 projectId 时直接返回不发请求', async () => {
    const axios = { get: vi.fn() };
    const comp = loadComponent({ axios });

    await comp.methods.checkStatus.call(okCtx(axios, { projectId: '' }));

    expect(axios.get).not.toHaveBeenCalled();
  });
});

describe('端点迁移契约（源码断言）', () => {
  it('不再调用旧 runninghub-status 端点', () => {
    expect(source).not.toContain('runninghub-status');
  });

  it('提交端点与计费走 /api/video-enhance', () => {
    expect(source).toContain("axios.post('/api/video-enhance'");
  });
});
