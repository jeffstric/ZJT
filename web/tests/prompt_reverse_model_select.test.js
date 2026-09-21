/**
 * 提示词反推节点「模型列表选择」测试。
 *
 * 需求：反推节点下拉里只能显示 VL 视觉模型（非 VL 模型一律不显示），
 * 用户可选模型并随工作流保存/重载，反推请求回传 model/model_id/vendor_id
 * （后端 DescribeImageRequest 已支持，services/vl_gateway.pick_vl_model 降级挑选）。
 * 模式参考 marketing_agent.js 的 /api/models 用法。
 *
 * 覆盖两层：
 * 1. 行为层：以真实 prompt_reverse_node.js 源码 + jsdom 验证
 *    - 下拉只渲染 supports_vl 模型；
 *    - change 事件写入 node.data（name + model_id + vendor_id）；
 *    - 反推请求体携带 model/model_id/vendor_id；
 *    - 重载按 model_id+vendor_id 回填选中项；已下架模型回落自动模式。
 * 2. 接线层：源码断言关键接线存在（防回退）。
 */

import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

// ─── 行为层：执行 prompt_reverse_node.js 真实源码 ───────────────

const VL_MODELS_RESPONSE = {
  success: true,
  models: [
    // 故意乱序：验证按 vendor_name 排序，且非 VL 模型被过滤
    { name: 'vl-b', model_id: 12, vendor_id: 3, vendor_name: 'zeta', supports_vl: true },
    { name: 'text-only', model_id: 22, vendor_id: 4, vendor_name: 'openai', supports_vl: false },
    { name: 'vl-a', model_id: 11, vendor_id: 2, vendor_name: 'volcengine', supports_vl: true },
  ],
};

function loadPromptReverseModuleOnce() {
  if (typeof globalThis.createPromptReverseNode === 'function') return;

  globalThis.window = globalThis;
  globalThis.registerNodeType = () => {};
  globalThis.registerInputPorts = () => {};
  globalThis.safeAutoSave = vi.fn();
  globalThis.showToast = vi.fn();
  globalThis.getAuthHeaders = () => ({ Authorization: 'Bearer test' });
  // state 是页面全局（state.js）：onCreated 的 updateSourceThumbnail 立即读取
  globalThis.state = { connections: [], nodes: [], nextConnId: 1000 };
  // createNodeBase 桩：按 bodyHtml 建真实 DOM，手动触发 onCreated，
  // 暴露 __makeNode 供用例构造节点实例
  globalThis.createNodeBase = function(opts) {
    return {
      type: opts.type,
      __opts: opts,
      __makeNode(nodeData) {
        const el = document.createElement('div');
        el.innerHTML = opts.bodyHtml();
        const node = {
          id: 1,
          type: opts.type,
          x: 0,
          y: 0,
          data: Object.assign({}, opts.defaultData, nodeData || {}),
        };
        opts.onCreated(node, el);
        return { node, el };
      },
    };
  };
  globalThis.createNodeWithDataFactory = function(createFn, restoreFn) {
    return function(data, pos) {
      const base = createFn(pos || {});
      const made = base.__makeNode(data);
      if (restoreFn) restoreFn(made.el);
      return made;
    };
  };

  // 间接 eval 让经典 script 顶层声明落在全局作用域
  (0, eval)(readSource('web/js/prompt_reverse_node.js'));
}

const flushMicrotasks = async () => {
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
};

function makeNode(nodeData) {
  const base = globalThis.createPromptReverseNode({});
  return base.__makeNode(nodeData);
}

describe('提示词反推节点：模型选择（行为层）', () => {
  let fetchMock;

  beforeEach(() => {
    loadPromptReverseModuleOnce();
    // 重置模块级模型缓存，隔离用例
    window._promptReverseVlModels = undefined;
    window._promptReverseVlModelsLoading = null;
    globalThis.safeAutoSave.mockClear();
    globalThis.state.connections = [];
    globalThis.state.nodes = [];

    fetchMock = vi.fn((url) => {
      if (url === '/api/models') {
        return Promise.resolve({ json: () => Promise.resolve(VL_MODELS_RESPONSE) });
      }
      if (url === '/api/video-workflow/describe-image') {
        return Promise.resolve({ json: () => Promise.resolve({ success: true, description: '反推结果提示词' }) });
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('下拉只渲染 VL 模型，非 VL 模型不出现', async () => {
    const { el } = makeNode();
    await flushMicrotasks();

    const select = el.querySelector('.prompt-reverse-model');
    expect(select).toBeTruthy();
    const values = Array.from(select.options).map((o) => o.value);
    // 首项为「自动」，其后按 vendor_name 排序只有 vl-a / vl-b
    expect(values).toEqual(['', 'vl-a', 'vl-b']);
    expect(values).not.toContain('text-only');
  });

  it('change 事件把 name/model_id/vendor_id 写入 node.data', async () => {
    const { node, el } = makeNode();
    await flushMicrotasks();

    const select = el.querySelector('.prompt-reverse-model');
    select.value = 'vl-a';
    select.dispatchEvent(new Event('change'));

    expect(node.data.reverseModelName).toBe('vl-a');
    expect(node.data.reverseModelId).toBe(11);
    expect(node.data.reverseVendorId).toBe(2);
    expect(globalThis.safeAutoSave).toHaveBeenCalled();
  });

  it('选择模型后反推请求体携带 model/model_id/vendor_id', async () => {
    const { el } = makeNode();
    await flushMicrotasks();

    const select = el.querySelector('.prompt-reverse-model');
    select.value = 'vl-a';
    select.dispatchEvent(new Event('change'));

    // 准备源图节点与相关全局桩
    globalThis.state = {
      connections: [{ from: 2, to: 1, portType: 'prompt-reverse-source' }],
      nodes: [{ id: 2, type: 'image', data: { url: '/uploads/a.png' } }],
      nextConnId: 100,
    };
    globalThis.getNodeImageUrl = (n) => (n.data && n.data.url) || '';
    globalThis.proxyImageUrl = (u) => u;
    globalThis.createImageNode = (opts) => {
      const id = 90;
      state.nodes.push({ id, type: 'image', data: Object.assign({}, opts.data) });
      return id;
    };

    el.querySelector('.prompt-reverse-btn').click();
    await flushMicrotasks();

    const call = fetchMock.mock.calls.find((c) => c[0] === '/api/video-workflow/describe-image');
    expect(call).toBeTruthy();
    const body = JSON.parse(call[1].body);
    expect(body.purpose).toBe('image_prompt');
    expect(body.image_url).toBe('/uploads/a.png');
    expect(body.model).toBe('vl-a');
    expect(body.model_id).toBe(11);
    expect(body.vendor_id).toBe(2);
    expect(globalThis.showToast).toHaveBeenCalled();
  });

  it('未选择模型时请求体不含 model 字段（保持自动模式）', async () => {
    const { el } = makeNode();
    await flushMicrotasks();

    globalThis.state = {
      connections: [{ from: 2, to: 1, portType: 'prompt-reverse-source' }],
      nodes: [{ id: 2, type: 'image', data: { url: '/uploads/a.png' } }],
      nextConnId: 100,
    };
    globalThis.getNodeImageUrl = (n) => (n.data && n.data.url) || '';
    globalThis.proxyImageUrl = (u) => u;
    globalThis.createImageNode = (opts) => {
      const id = 90;
      state.nodes.push({ id, type: 'image', data: Object.assign({}, opts.data) });
      return id;
    };

    el.querySelector('.prompt-reverse-btn').click();
    await flushMicrotasks();

    const call = fetchMock.mock.calls.find((c) => c[0] === '/api/video-workflow/describe-image');
    const body = JSON.parse(call[1].body);
    expect(body).not.toHaveProperty('model');
    expect(body).not.toHaveProperty('model_id');
    expect(body).not.toHaveProperty('vendor_id');
  });

  it('重载恢复：按 model_id + vendor_id 回填模型选中项', async () => {
    const { el } = makeNode({ reverseModelName: 'vl-a', reverseModelId: 11, reverseVendorId: 2 });
    await flushMicrotasks();

    const select = el.querySelector('.prompt-reverse-model');
    expect(select.value).toBe('vl-a');
  });

  it('已保存模型不在 VL 列表时回落自动模式并持久化清空', async () => {
    const { node, el } = makeNode({ reverseModelName: 'removed-model', reverseModelId: 99, reverseVendorId: 9 });
    await flushMicrotasks();

    const select = el.querySelector('.prompt-reverse-model');
    expect(select.value).toBe('');
    expect(node.data.reverseModelName).toBe('');
    expect(node.data.reverseModelId).toBeNull();
    expect(node.data.reverseVendorId).toBeNull();
    expect(globalThis.safeAutoSave).toHaveBeenCalled();
  });
});

// ─── 接线层：源码断言 ────────────────────────────────────────

describe('提示词反推节点：模型选择（接线层源码断言）', () => {
  const nodeSrc = readSource('web/js/prompt_reverse_node.js');
  const serverSrc = readSource('server.py');
  const zhI18n = readSource('web/i18n/locales/zh-CN/video_workflow.json');
  const enI18n = readSource('web/i18n/locales/en/video_workflow.json');

  it('节点从 /api/models 拉取列表并按 supports_vl 过滤', () => {
    expect(nodeSrc).toContain("fetch('/api/models'");
    expect(nodeSrc).toContain('supports_vl');
    expect(nodeSrc).toContain('prompt-reverse-model');
  });

  it('请求体回传 model/model_id/vendor_id 三件套', () => {
    expect(nodeSrc).toContain('requestBody.model = node.data.reverseModelName');
    expect(nodeSrc).toContain('requestBody.model_id');
    expect(nodeSrc).toContain('requestBody.vendor_id');
    expect(nodeSrc).toContain('reverseModelName:');
  });

  it('重载恢复函数回填模型选中项', () => {
    expect(nodeSrc).toContain('_restorePromptReverseState');
    expect(nodeSrc).toContain('applyModelSelection');
  });

  it('后端 DescribeImageRequest 支持 model/model_id/vendor_id（防回退）', () => {
    const idx = serverSrc.indexOf('class DescribeImageRequest(BaseModel):');
    expect(idx).toBeGreaterThan(-1);
    const block = serverSrc.slice(idx, idx + 700);
    expect(block).toContain('model: Optional[str] = None');
    expect(block).toContain('model_id: Optional[int] = None');
    expect(block).toContain('vendor_id: Optional[int] = None');
  });

  it('zh-CN / en i18n 均含模型选择文案', () => {
    for (const src of [zhI18n, enI18n]) {
      expect(src).toContain('prompt_reverse_model_label');
      expect(src).toContain('prompt_reverse_model_auto');
      expect(src).toContain('prompt_reverse_model_failed');
    }
  });
});
