const fs = require('fs');
const path = require('path');
const wm = require('../js/video_watermark_node.js');

function installCanvasStubs() {
  if (typeof HTMLMediaElement !== 'undefined') {
    HTMLMediaElement.prototype.load = () => {};
  }
  document.body.innerHTML = '';
  const canvas = document.createElement('div');
  canvas.id = 'canvas';
  document.body.appendChild(canvas);

  globalThis.canvasEl = canvas;
  globalThis.state = {
    nodes: [],
    connections: [],
    nextNodeId: 1,
    nextConnId: 1,
    selectedNodeIds: [],
    connecting: null
  };
  globalThis.escapeHtml = (value) => String(value == null ? '' : value);
  globalThis.setSelected = () => {};
  globalThis.bringNodeToFront = () => {};
  globalThis.removeNode = () => {};
  globalThis.initNodeDrag = () => {};
  globalThis.scanNodeI18n = () => {};
  globalThis.safeAutoSave = vi.fn();
  globalThis.showToast = vi.fn();
  globalThis.renderAllConnections = vi.fn();
  globalThis.renderMinimap = vi.fn();
  globalThis.getViewportNodePosition = () => ({ x: 20, y: 20 });
  globalThis.getTaskComputingPowerConfig = () => ({ '49': { '4': 5, '5': 6, '6': 8, '7': 9, '8': 10, '9': 11, '10': 13 } });
  globalThis.getAuthToken = () => 'tok';
  globalThis.appendAuthToForm = (form) => {
    form.append('user_id', '7');
    form.append('auth_token', 'tok');
  };
  globalThis.proxyDownloadUrl = (url) => url;
  globalThis.setupVideoThumbnail = (video, url) => { video.src = url; };
  globalThis.setBtnLoading = (btn, text) => { btn.disabled = true; btn.textContent = text; };
  globalThis.setBtnReady = (btn, text) => { btn.disabled = false; btn.textContent = text; };
  globalThis.setStatusEl = (el, text, color) => {
    el.textContent = text;
    el.style.color = color || '';
  };
  globalThis.bindInputPortEvents = (_el, node, portCfg) => { node.__portCfg = portCfg; };
  globalThis.registerInputPorts = vi.fn();
  globalThis.registerNodeType = vi.fn();
  globalThis.createVideoNode = (opts) => {
    const id = globalThis.state.nextNodeId++;
    const node = { id, type: 'video', x: opts.x, y: opts.y, data: { url: '', name: '', project_id: null } };
    globalThis.state.nodes.push(node);
    const el = document.createElement('div');
    el.className = 'node';
    el.dataset.nodeId = String(id);
    el.innerHTML = '<div class="video-status-field" style="display:none"></div><div class="video-status"></div>';
    canvas.appendChild(el);
    return id;
  };
  globalThis.createNodeBase = function(config, opts) {
    const id = globalThis.state.nextNodeId++;
    const node = {
      id,
      type: config.type,
      x: opts && typeof opts.x === 'number' ? opts.x : 0,
      y: opts && typeof opts.y === 'number' ? opts.y : 0,
      data: JSON.parse(JSON.stringify(config.defaultData))
    };
    globalThis.state.nodes.push(node);
    const el = document.createElement('div');
    el.className = 'node' + (config.cssClass ? ' ' + config.cssClass : '');
    el.dataset.nodeId = String(id);
    el.dataset.type = config.type;
    el.innerHTML = '<div class="node-body">' + config.bodyHtml() + '</div>';
    canvas.appendChild(el);
    config.onCreated(node, el, opts);
    return id;
  };
  globalThis.createNodeWithDataFactory = function(createFn, restoreDomFn) {
    return function(nodeData) {
      const saved = globalThis.state.nextNodeId;
      globalThis.state.nextNodeId = nodeData.id;
      createFn({ x: nodeData.x, y: nodeData.y });
      globalThis.state.nextNodeId = Math.max(saved, nodeData.id + 1);
      const node = globalThis.state.nodes.find((n) => n.id === nodeData.id);
      if (nodeData.data) Object.assign(node.data, nodeData.data);
      const el = canvas.querySelector('.node[data-node-id="' + nodeData.id + '"]');
      if (restoreDomFn && el) restoreDomFn(el, node, nodeData);
      return nodeData.id;
    };
  };

  (0, eval)(fs.readFileSync(path.join(__dirname, '../js/video_watermark_node.js'), 'utf8'));
}

function nodeEls(id) {
  return {
    node: globalThis.state.nodes.find((n) => n.id === id),
    el: globalThis.canvasEl.querySelector('.node[data-node-id="' + id + '"]')
  };
}

describe('resolveWatermarkDuration', () => {
  test('四舍五入后落在 4-10 时自动选中并可提交', () => {
    expect(wm.resolveWatermarkDuration(6.2)).toEqual({
      sourceDuration: 6,
      outOfRange: false,
      duration: 6,
      canSubmit: true
    });
    expect(wm.resolveWatermarkDuration(4)).toMatchObject({ duration: 4, canSubmit: true });
    expect(wm.resolveWatermarkDuration(10.4)).toMatchObject({ sourceDuration: 10, duration: 10, outOfRange: false });
  });

  test('超出 4-10 时禁止提交', () => {
    expect(wm.resolveWatermarkDuration(3)).toMatchObject({ sourceDuration: 3, outOfRange: true, duration: null, canSubmit: false });
    expect(wm.resolveWatermarkDuration(10.5)).toMatchObject({ sourceDuration: 11, outOfRange: true, canSubmit: false });
    expect(wm.resolveWatermarkDuration(15)).toMatchObject({ outOfRange: true, canSubmit: false });
  });

  test('读不到时长时交给用户选择', () => {
    [null, undefined, '', 0, -1, NaN].forEach((value) => {
      expect(wm.resolveWatermarkDuration(value)).toEqual({
        sourceDuration: null,
        outOfRange: false,
        duration: null,
        canSubmit: true
      });
    });
  });
});

describe('lookupWatermarkPower', () => {
  test('没有配置时使用 H3 720P 回退表', () => {
    expect(wm.lookupWatermarkPower(4, null)).toBe(5);
    expect(wm.lookupWatermarkPower(5, {})).toBe(6);
    expect(wm.lookupWatermarkPower(10, {})).toBe(13);
    expect(wm.lookupWatermarkPower(3, {})).toBe(null);
  });

  test('优先使用任务 49 的字符串键', () => {
    const config = { '49': { '6': 99 } };
    expect(wm.lookupWatermarkPower(6, config)).toBe(99);
    expect(wm.lookupWatermarkPower(7, config)).toBe(9);
  });
});

describe('isUsableVideoUrl', () => {
  test('只接受服务器地址', () => {
    expect(wm.isUsableVideoUrl('/upload/a.mp4')).toBe(true);
    expect(wm.isUsableVideoUrl('https://cdn.example/a.mp4')).toBe(true);
    expect(wm.isUsableVideoUrl('http://127.0.0.1/a.mp4')).toBe(true);
    expect(wm.isUsableVideoUrl('blob:http://local/uuid')).toBe(false);
    expect(wm.isUsableVideoUrl('data:video/mp4;base64,aaa')).toBe(false);
    expect(wm.isUsableVideoUrl('')).toBe(false);
  });
});

describe('readErrorDetail', () => {
  test('读取接口错误文案', () => {
    expect(wm.readErrorDetail({ detail: '视频时长仅支持' })).toBe('视频时长仅支持');
    expect(wm.readErrorDetail({ detail: [{ msg: '字段错误' }] })).toBe('字段错误');
    expect(wm.readErrorDetail({ error: 'Authorization is required' })).toBe('Authorization is required');
    expect(wm.readErrorDetail(null)).toBe('');
  });
});

describe('去水印节点交互', () => {
  beforeEach(() => {
    installCanvasStubs();
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test('默认 5 秒，显示 6 算力', () => {
    const id = globalThis.createVideoWatermarkNode();
    const { el } = nodeEls(id);
    expect(el.querySelector('.watermark-duration').value).toBe('5');
    expect(el.querySelector('.computing-power-value').textContent).toContain('6');
    expect(el.querySelector('.watermark-submit-btn').disabled).toBe(false);
  });

  test('连上 6 秒视频后自动选中并更新算力', () => {
    const id = globalThis.createVideoWatermarkNode();
    const { node, el } = nodeEls(id);
    node.applyVideoSource({ id: 9, type: 'video', data: { url: '/upload/a.mp4', name: 'a.mp4', duration: 6.2 } });
    expect(el.querySelector('.watermark-duration').value).toBe('6');
    expect(el.querySelector('.computing-power-value').textContent).toContain('8');
    expect(node.data.durationOutOfRange).toBe(false);
    expect(el.querySelector('.video-name').textContent).toBe('a.mp4');
  });

  test('超过 10 秒时禁用提交', () => {
    const id = globalThis.createVideoWatermarkNode();
    const { node, el } = nodeEls(id);
    node.applyVideoSource({ id: 9, type: 'video', data: { url: '/upload/long.mp4', name: 'long.mp4', duration: 15 } });
    const btn = el.querySelector('.watermark-submit-btn');
    expect(btn.disabled).toBe(true);
    expect(el.querySelector('.duration-hint').textContent).toContain('4');
    expect(el.querySelector('.duration-hint').classList.contains('is-error')).toBe(true);
  });

  test('未连接视频时提交给出提示', () => {
    const id = globalThis.createVideoWatermarkNode();
    const { el } = nodeEls(id);
    el.querySelector('.watermark-submit-btn').click();
    expect(globalThis.showToast).toHaveBeenCalled();
    expect(globalThis.showToast.mock.calls[0][0]).toContain('连接视频');
    expect(fetch).not.toHaveBeenCalled();
  });

  test('提交已上传视频后新建带 project_id 的结果节点', async () => {
    fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, project_id: 321, computing_power: 8, duration: 6 })
    });
    const id = globalThis.createVideoWatermarkNode();
    const { node, el } = nodeEls(id);
    const source = { id: 50, type: 'video', x: 0, y: 0, data: { url: '/upload/a.mp4', name: 'a.mp4', duration: 6 } };
    globalThis.state.nodes.push(source);
    globalThis.state.connections.push({ id: 1, from: 50, to: id });
    node.applyVideoSource(source);
    el.querySelector('.watermark-prompt').value = '去掉角标';
    el.querySelector('.watermark-submit-btn').click();
    await vi.waitFor(() => {
      expect(globalThis.state.nodes.some((n) => n.data && n.data.project_id === 321)).toBe(true);
    });

    const [url, opts] = fetch.mock.calls[0];
    expect(url).toBe('/api/video-watermark-remove');
    expect(opts.headers.Authorization).toBe('Bearer tok');
    expect(String(url)).not.toContain('auth_token');
    expect(opts.body.get('video_url')).toBe('/upload/a.mp4');
    expect(opts.body.get('duration_seconds')).toBe('6');
    expect(opts.body.get('fps')).toBe('24');
    expect(opts.body.get('prompt')).toBe('去掉角标');
    expect(opts.body.get('auth_token')).toBe('tok');

    const result = globalThis.state.nodes.find((n) => n.type === 'video' && n.data.project_id === 321);
    expect(result).toBeTruthy();
    expect(globalThis.state.connections.some((c) => c.from === id && c.to === result.id)).toBe(true);
    expect(el.querySelector('.status').textContent).toContain('已提交');
  });

  test('本地 blob 地址不能提交', () => {
    const id = globalThis.createVideoWatermarkNode();
    const { el } = nodeEls(id);
    globalThis.state.nodes.push({ id: 51, type: 'video', data: { url: 'blob:http://local/1', duration: 6 } });
    globalThis.state.connections.push({ id: 2, from: 51, to: id });
    el.querySelector('.watermark-submit-btn').click();
    expect(globalThis.showToast.mock.calls[0][0]).toContain('上传');
    expect(fetch).not.toHaveBeenCalled();
  });

  test('重载后恢复提示词，超时长仍然禁用', () => {
    const id = globalThis.createVideoWatermarkNodeWithData({
      id: 7,
      x: 30,
      y: 40,
      data: {
        prompt: '去掉logo',
        sourceDuration: 15,
        duration: 5,
        durationOutOfRange: true,
        videoUrl: '',
        status: 'idle'
      }
    });
    const { node, el } = nodeEls(id);
    expect(node.data.prompt).toBe('去掉logo');
    expect(el.querySelector('.watermark-prompt').value).toBe('去掉logo');
    expect(el.querySelector('.watermark-submit-btn').disabled).toBe(true);
    expect(node.type).toBe('video_watermark');
  });
});

describe('去水印节点接线', () => {
  test('页面、菜单和连线包含去水印节点', () => {
    const root = path.join(__dirname, '..');
    const html = fs.readFileSync(path.join(root, 'video_workflow.html'), 'utf8');
    const events = fs.readFileSync(path.join(root, 'js/events.js'), 'utf8');
    const videoNode = fs.readFileSync(path.join(root, 'js/video_node.js'), 'utf8');
    expect(html).toContain('id="menuAddVideoWatermark"');
    expect(html).toContain('/js/video_watermark_node.js');
    expect(html).toContain('/css/video_watermark_node.css');
    expect(events).toContain('createVideoWatermarkNode');
    expect(events).toContain("fromNode.type === 'video_watermark'");
    expect(videoNode).toContain("fromNode.type === 'video_watermark'");
  });
});
