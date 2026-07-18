/**
 * 图片节点上传门禁：大图上传未完成前禁止编辑/涂色。
 * 覆盖 canEditImageNode / resolveImageEditSubmitData / getImageUploadBlockMessage。
 */

// image_node.js 依赖若干全局符号；门禁函数本身是纯函数，这里仅提供最小 stub
globalThis.window = globalThis;
globalThis.state = {
  nextNodeId: 1,
  nodes: [],
  ratio: '9:16',
  imageConnections: [],
  referenceConnections: [],
  connections: [],
};
globalThis.ratioSelectEl = { value: '9:16' };
globalThis.MIN_NODE_Y = 0;
globalThis.getViewportNodePosition = () => ({ x: 0, y: 0 });
globalThis.findNearestAvailablePosition = (x, y) => ({ x, y });
globalThis.canvasEl = {
  appendChild: () => {},
  querySelector: () => null,
};
globalThis.setSelected = () => {};
globalThis.addDebugButtonToNode = () => {};
globalThis.initNodeDrag = () => {};
globalThis.bringNodeToFront = () => {};
globalThis.removeNode = () => {};
globalThis.showToast = () => {};
globalThis.safeAutoSave = () => {};
globalThis.proxyImageUrl = (u) => u;
globalThis.uploadFile = async () => null;
globalThis.readFileAsDataUrl = async () => 'data:image/png;base64,xx';
globalThis.setStatusEl = () => {};
globalThis.TaskConfig = {
  isLoaded: () => false,
  getModelOptionsForCategory: () => [],
  getTaskIdByKey: () => null,
};
globalThis.t = (key) => key;

const {
  canEditImageNode,
  resolveImageEditSubmitData,
  getImageUploadBlockMessage,
} = require('../js/image_node.js');

describe('canEditImageNode', () => {
  test('空 data 不允许编辑', () => {
    expect(canEditImageNode(null)).toEqual({ allowed: false, reason: 'no_image' });
    expect(canEditImageNode(undefined)).toEqual({ allowed: false, reason: 'no_image' });
    expect(canEditImageNode({})).toEqual({ allowed: false, reason: 'no_image' });
  });

  test('仅有本地 file、尚无 url 时不允许编辑（上传中/未完成）', () => {
    expect(
      canEditImageNode({
        file: { name: 'big.png' },
        url: '',
        uploading: false,
      })
    ).toEqual({ allowed: false, reason: 'no_image' });
  });

  test('uploading=true 时即使有旧 url 也不允许编辑', () => {
    expect(
      canEditImageNode({
        url: 'https://cdn.example.com/old.png',
        uploading: true,
      })
    ).toEqual({ allowed: false, reason: 'uploading' });
  });

  test('仅有本地 preview、无服务器 url 时不允许编辑', () => {
    expect(
      canEditImageNode({
        preview: 'data:image/png;base64,abc',
        url: '',
        uploading: false,
      })
    ).toEqual({ allowed: false, reason: 'no_image' });
  });

  test('上传完成后有 url 允许编辑', () => {
    expect(
      canEditImageNode({
        url: 'https://cdn.example.com/a.png',
        uploading: false,
        file: null,
      })
    ).toEqual({ allowed: true, reason: 'ok' });
  });

  test('url 仅空白字符视为无图', () => {
    expect(canEditImageNode({ url: '   ', uploading: false })).toEqual({
      allowed: false,
      reason: 'no_image',
    });
  });
});

describe('resolveImageEditSubmitData', () => {
  test('上传中返回 uploading', () => {
    expect(
      resolveImageEditSubmitData({
        url: 'https://cdn.example.com/a.png',
        uploading: true,
      })
    ).toEqual({ ok: false, reason: 'uploading' });
  });

  test('无 url 时即使有 file 也不提交本地 File', () => {
    const result = resolveImageEditSubmitData({
      file: { name: 'local.png' },
      url: '',
      uploading: false,
    });
    expect(result.ok).toBe(false);
    expect(result.reason).toBe('no_image');
    expect(result.submitData).toBeUndefined();
  });

  test('就绪时只返回服务器 URL（trim）', () => {
    expect(
      resolveImageEditSubmitData({
        url: '  https://cdn.example.com/ready.png  ',
        file: { name: 'should-not-use.png' },
        uploading: false,
      })
    ).toEqual({
      ok: true,
      submitData: 'https://cdn.example.com/ready.png',
    });
  });
});

describe('getImageUploadBlockMessage', () => {
  test('uploading 返回等待文案', () => {
    const msg = getImageUploadBlockMessage('uploading', (key, fallback) => fallback);
    expect(msg).toContain('上传');
  });

  test('no_image 返回请先上传文案', () => {
    const msg = getImageUploadBlockMessage('no_image', (key, fallback) => fallback);
    expect(msg).toMatch(/上传|生成/);
  });

  test('可使用自定义 t 翻译函数', () => {
    const msg = getImageUploadBlockMessage('uploading', (key) => `i18n:${key}`);
    expect(msg).toBe('i18n:image_node_uploading_wait');
  });
});

describe('上传生命周期状态机（模拟 change 处理）', () => {
  function simulateUploadLifecycle(data, { uploadResult }) {
    // 与 image_node 上传逻辑对齐的状态迁移
    const previousUrl = data.url || '';
    data.file = { name: 'big.png' };
    data.uploading = true;
    data.url = '';

    expect(canEditImageNode(data).allowed).toBe(false);
    expect(canEditImageNode(data).reason).toBe('uploading');
    expect(resolveImageEditSubmitData(data).ok).toBe(false);

    if (uploadResult) {
      data.url = uploadResult;
      data.preview = uploadResult;
      data.file = null;
      data.uploading = false;
      expect(canEditImageNode(data)).toEqual({ allowed: true, reason: 'ok' });
      expect(resolveImageEditSubmitData(data)).toEqual({
        ok: true,
        submitData: uploadResult,
      });
    } else {
      data.file = null;
      data.uploading = false;
      if (previousUrl) {
        data.url = previousUrl;
      }
      // 失败且无旧图：仍不可编辑
      if (!previousUrl) {
        expect(canEditImageNode(data).allowed).toBe(false);
      } else {
        expect(canEditImageNode(data).allowed).toBe(true);
      }
    }
    return data;
  }

  test('大图上传成功前不可编辑，成功后可编辑', () => {
    const data = { file: null, url: '', preview: '', uploading: false };
    simulateUploadLifecycle(data, {
      uploadResult: 'https://cdn.example.com/uploaded.png',
    });
  });

  test('替换大图上传中不可用旧 url 编辑', () => {
    const data = {
      file: null,
      url: 'https://cdn.example.com/old.png',
      preview: 'https://cdn.example.com/old.png',
      uploading: false,
    };
    // 进入上传：url 被清空 + uploading
    data.uploading = true;
    data.url = '';
    expect(canEditImageNode(data)).toEqual({ allowed: false, reason: 'uploading' });
  });

  test('上传失败且无旧图时恢复为不可编辑', () => {
    const data = { file: null, url: '', preview: '', uploading: false };
    simulateUploadLifecycle(data, { uploadResult: null });
    expect(data.url).toBe('');
    expect(data.file).toBe(null);
    expect(data.uploading).toBe(false);
  });

  test('上传失败有旧图时恢复旧 url 可继续编辑', () => {
    const data = {
      file: null,
      url: 'https://cdn.example.com/old.png',
      preview: 'https://cdn.example.com/old.png',
      uploading: false,
    };
    simulateUploadLifecycle(data, { uploadResult: null });
    expect(data.url).toBe('https://cdn.example.com/old.png');
    expect(canEditImageNode(data).allowed).toBe(true);
  });
});
