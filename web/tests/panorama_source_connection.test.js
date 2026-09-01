/**
 * 360全景图参考图输入端口连接修复回归测试。
 *
 * 背景 BUG：图片节点拖线到全景节点附近松手时静默失败——panorama 未注册进
 * 连接吸附注册表（registerInputPorts），events.js 的 image 分支三条 fallback
 * 全部落空；仅剩"精确释放在 18px 端口圆点"的直落路径，用户几乎无法连上。
 *
 * 覆盖两层：
 * 1. 行为层：以真实 node_base.js 源码验证注册表吸附 + connectToRegisteredImagePort
 *    对 connectionType:'connections' 端口的连接落库（数组/id 计数器/onConnect/渲染）；
 * 2. 接线层：源码断言 panorama_node.js / events.js / nodes.js / i18n 的修复接线存在。
 */

import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi, beforeEach } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

// ─── 行为层：执行 node_base.js 真实源码 ───────────────────────

function loadNodeBaseOnce() {
  if (typeof globalThis.registerInputPorts === 'function') return;

  globalThis.window = globalThis;
  globalThis.escapeHtml = (s) => String(s);
  globalThis.showToast = vi.fn();
  globalThis.safeAutoSave = vi.fn();
  globalThis.renderAllConnections = vi.fn();
  globalThis.renderImageConnections = vi.fn();
  globalThis.renderMinimap = vi.fn();
  globalThis.getNodeImageUrl = (n) =>
    (n.data && (n.data.url || n.data.reference_image)) || '';
  globalThis.getPortDistance = (portEl, x, y) => {
    const r = portEl.getBoundingClientRect();
    const px = r.left + r.width / 2;
    const py = r.top + r.height / 2;
    return { dist: Math.hypot(x - px, y - py), x: px, y: py };
  };

  const canvasHost = document.createElement('div');
  canvasHost.id = 'canvas';
  document.body.appendChild(canvasHost);
  globalThis.canvasEl = canvasHost;

  // node_base.js 以经典 script 运行；间接 eval 让顶层声明落在全局作用域
  (0, eval)(readSource('web/js/node_base.js'));

  // safeAutoSave 是 node_base.js 自身定义的顶层函数，eval 后需重新替换为 spy
  globalThis.safeAutoSave = vi.fn();
}

// 与 panorama_node.js 末尾注册保持一致的端口配置
const PANORAMA_PORT_CFG = [{
  selector: '.port.input.panorama-source-port',
  portType: 'panorama-source',
  accepts: ['image', 'location'],
  connectionType: 'connections',
  allowMissingImage: true,
  onConnect: vi.fn(),
}];

function buildPanoramaNodeEl(nodeId) {
  const el = document.createElement('div');
  el.className = 'node panorama-node';
  el.dataset.nodeId = String(nodeId);
  el.innerHTML = '<div class="port input panorama-source-port"></div>';
  globalThis.canvasEl.appendChild(el);
  return el;
}

function freshState() {
  globalThis.state = {
    nodes: [],
    connections: [],
    imageConnections: [],
    nextConnId: 100,
    nextImgConnId: 5,
  };
}

describe('connectToRegisteredImagePort · connections 类端口（全景参考口）', () => {
  beforeEach(() => {
    loadNodeBaseOnce();
    freshState();
    globalThis.canvasEl.innerHTML = '';
    PANORAMA_PORT_CFG[0].onConnect = vi.fn();
    globalThis.renderAllConnections.mockClear();
    globalThis.renderImageConnections.mockClear();
    globalThis.showToast.mockClear();
    globalThis.safeAutoSave.mockClear();
    registerInputPorts('panorama', PANORAMA_PORT_CFG);
  });

  function findPort(x, y, fromType) {
    return findNearestConnectablePort(x, y, fromType, 50);
  }

  it('findNearestConnectablePort 能发现注册后的全景参考端口（image/location 源）', () => {
    buildPanoramaNodeEl(2);
    globalThis.state.nodes.push({ id: 2, type: 'panorama', data: {} });

    // jsdom 中未布局元素 rect 全 0，端口中心即 (0,0)
    const hit = findPort(10, 10, 'image');
    expect(hit).toBeTruthy();
    expect(hit.nodeId).toBe(2);
    expect(hit.portType).toBe('panorama-source');
    expect(hit.portCfg.connectionType).toBe('connections');

    expect(findPort(10, 10, 'location')).toBeTruthy();
    // 类型不在 accepts 白名单（如 video 源）不得命中
    expect(findPort(10, 10, 'video')).toBeNull();
  });

  it('有参考图的图片节点连接：落入 state.connections 且 id 用 nextConnId 计数器', () => {
    buildPanoramaNodeEl(2);
    const panoNode = { id: 2, type: 'panorama', data: {} };
    const imageNode = { id: 1, type: 'image', data: { url: 'http://x/a.png' } };
    globalThis.state.nodes.push(imageNode, panoNode);

    const port = findPort(10, 10, 'image');
    const ok = connectToRegisteredImagePort(imageNode, port);

    expect(ok).toBe(true);
    expect(globalThis.state.connections).toHaveLength(1);
    expect(globalThis.state.connections[0]).toMatchObject({
      from: 1, to: 2, portType: 'panorama-source',
    });
    // 关键回归点：connections 数组的 id 必须来自 nextConnId（removeConnection 按 id 删线）
    expect(globalThis.state.connections[0].id).toBe(100);
    expect(globalThis.state.nextConnId).toBe(101);
    expect(globalThis.state.imageConnections).toHaveLength(0);
    // connections 由 renderAllConnections 渲染（renderImageConnections 不渲染该数组）
    expect(globalThis.renderAllConnections).toHaveBeenCalled();
    expect(globalThis.renderImageConnections).not.toHaveBeenCalled();
    expect(port.portCfg.onConnect).toHaveBeenCalledWith(imageNode, panoNode);
    expect(globalThis.safeAutoSave).toHaveBeenCalled();
  });

  it('allowMissingImage：无参考图也允许连接（场景节点仅提供描述的路径）', () => {
    buildPanoramaNodeEl(2);
    const imageNode = { id: 1, type: 'image', data: { url: '', prompt: '雪山湖泊' } };
    globalThis.state.nodes.push(imageNode, { id: 2, type: 'panorama', data: {} });

    const ok = connectToRegisteredImagePort(imageNode, findPort(10, 10, 'image'));
    expect(ok).toBe(true);
    expect(globalThis.showToast).not.toHaveBeenCalledWith(
      expect.stringContaining('没有参考图'), 'error');
  });

  it('未声明 allowMissingImage 的端口（图生视频等）：无参考图仍拒绝并提示', () => {
    buildPanoramaNodeEl(2);
    registerInputPorts('panorama', [{
      selector: '.port.input.panorama-source-port',
      portType: 'panorama-source',
      accepts: ['image'],
      connectionType: 'connections',
    }]);
    const imageNode = { id: 1, type: 'image', data: { url: '' } };
    globalThis.state.nodes.push(imageNode, { id: 2, type: 'panorama', data: {} });

    expect(connectToRegisteredImagePort(imageNode, findPort(10, 10, 'image'))).toBe(false);
    expect(globalThis.state.connections).toHaveLength(0);
  });

  it('同一源重复连接与端口占用均被拦截（单连接端口）', () => {
    buildPanoramaNodeEl(2);
    const n1 = { id: 1, type: 'image', data: { url: 'http://x/a.png' } };
    const n3 = { id: 3, type: 'image', data: { url: 'http://x/b.png' } };
    globalThis.state.nodes.push(n1, { id: 2, type: 'panorama', data: {} }, n3);

    expect(connectToRegisteredImagePort(n1, findPort(10, 10, 'image'))).toBe(true);
    // 同一源重复连接
    expect(connectToRegisteredImagePort(n1, findPort(10, 10, 'image'))).toBe(false);
    // 端口已被占用，第二个源也不得连入
    expect(connectToRegisteredImagePort(n3, findPort(10, 10, 'image'))).toBe(false);
    expect(globalThis.state.connections).toHaveLength(1);
  });

  it('回归：默认 imageConnections 端口仍用 nextImgConnId 且走 renderImageConnections', () => {
    buildPanoramaNodeEl(2);
    registerInputPorts('panorama', [{
      selector: '.port.input.panorama-source-port',
      portType: 'start',
      accepts: ['image'],
    }]);
    const n1 = { id: 1, type: 'image', data: { url: 'http://x/a.png' } };
    globalThis.state.nodes.push(n1, { id: 2, type: 'panorama', data: {} });

    const ok = connectToRegisteredImagePort(n1, findPort(10, 10, 'image'));
    expect(ok).toBe(true);
    expect(globalThis.state.imageConnections[0].id).toBe(5);
    expect(globalThis.state.nextImgConnId).toBe(6);
    expect(globalThis.renderImageConnections).toHaveBeenCalled();
  });
});

// ─── 接线层：修复点源码断言 ───────────────────────────────────

describe('全景参考端口修复接线（源码断言）', () => {
  it('panorama_node.js：注册端口 + 专属端口类 + 移除直落路径 + 提示词自动填充', () => {
    const src = readSource('web/js/panorama_node.js');

    // 端口注册进连接吸附注册表
    expect(src).toContain(`registerInputPorts('panorama'`);
    expect(src).toContain("selector: '.port.input.panorama-source-port'");
    expect(src).toContain("portType: 'panorama-source'");
    expect(src).toContain("accepts: ['image', 'location']");
    expect(src).toContain("connectionType: 'connections'");
    expect(src).toContain('allowMissingImage: true');

    // 端口 DOM 带专属类（供注册表选择器与 mousemove 高亮）
    expect(src).toMatch(/direction:\s*'input'[^}]*cssClass:\s*'panorama-source-port'/);

    // 不再使用 bindInputPortEvents 直落路径（两套路径并存会导致查重/占用失效）
    expect(src).not.toContain('bindInputPortEvents(');

    // 图片节点提示词自动填充：为空才填、不覆盖已有内容
    expect(src).toContain('function autoFillPromptFromSource');
    expect(src).toMatch(/已有提示词不覆盖/);
    expect(src).toMatch(/fromNode\.type === 'image'/);
    expect(src).toMatch(/fromNode\.data\.prompt/);
    expect(src).toContain("'panorama_image_prompt_filled'");
    // 连接后刷新缩略图/填提示词的钩子挂载（供注册表 onConnect 与断连清理调用）
    expect(src).toContain('el._updateSourceThumbnail = updateSourceThumbnail');
    expect(src).toContain('el._autoFillPromptFromSource = autoFillPromptFromSource');
  });

  it('events.js：拖线高亮循环覆盖全景参考端口', () => {
    const src = readSource('web/js/events.js');
    expect(src).toMatch(
      /querySelectorAll\('\.start-image-port, \.end-image-port, \.ref-image-input-port, \.panorama-source-port'\)/
    );
    expect(src).toMatch(/classList\.contains\('panorama-source-port'\)\) portType = 'panorama-source'/);
  });

  it('nodes.js：断开 panorama-source 连线时复位参考图缩略图', () => {
    const src = readSource('web/js/nodes.js');
    expect(src).toMatch(/portType === 'panorama-source'/);
    expect(src).toMatch(/panoEl\._updateSourceThumbnail/);
  });

  it('i18n：zh-CN / en 均有图片提示词填充文案', () => {
    const zh = JSON.parse(readSource('web/i18n/locales/zh-CN/video_workflow.json'));
    const en = JSON.parse(readSource('web/i18n/locales/en/video_workflow.json'));
    expect(zh.panorama_image_prompt_filled).toBeTruthy();
    expect(en.panorama_image_prompt_filled).toBeTruthy();
  });
});

// ─── 结果节点携带生成提示词（填充的数据来源）─────────────────

describe('生成结果图片节点携带提示词', () => {
  it('image_node.js：createImageNode 支持 opts.data 初始数据，textarea 回显提示词', () => {
    const src = readSource('web/js/image_node.js');
    expect(src).toMatch(/if \(opts && opts\.data\) \{[\s\S]*?Object\.assign\(node\.data, opts\.data\)/);
    expect(src).toMatch(/\$\{escapeHtml\(node\.data\.prompt \|\| ''\)\}<\/textarea>/);
  });

  it('image_node.js / shot_frame_generator.js / panorama_node.js：结果节点创建时回填生成提示词', () => {
    // 图片编辑结果：携带原节点的编辑提示词
    const imgSrc = readSource('web/js/image_node.js');
    expect(imgSrc).toMatch(/data: \{ prompt: node\.data\.prompt \|\| '' \}/);

    // 分镜图结果：携带分镜生图的 finalPrompt
    const sfSrc = readSource('web/js/shot_frame_generator.js');
    expect(sfSrc).toMatch(/data: \{ prompt: finalPrompt \}/);

    // 全景结果节点：携带含 360° 后缀的 finalPrompt；全景截图：携带场景描述
    const panoSrc = readSource('web/js/panorama_node.js');
    const panoPromptCarries = panoSrc.match(/createImageNode\(\{[^}]*data: \{ prompt: ([^}]+) \}[^}]*\}\)/g) || [];
    expect(panoPromptCarries.length).toBeGreaterThanOrEqual(2);
    expect(panoSrc).toMatch(/data: \{ prompt: finalPrompt \}/);
    expect(panoSrc).toMatch(/data: \{ prompt: String\(node\.data\.prompt \|\| ''\)\.trim\(\) \}/);
  });

  it('panorama_node.js：图片无提示词时走 VL 识图（任意图片可生成描述）', () => {
    const src = readSource('web/js/panorama_node.js');

    // 无提示词分支：取源图 URL 触发识图
    expect(src).toMatch(/var imgUrl = getSourceImageUrl\(fromNode\);\s*\n\s*if \(imgUrl\) describeImageIntoPrompt\(imgUrl\);/);

    // 识图请求打向后端 VL 接口（带鉴权头），填入前仍检查不覆盖用户输入
    expect(src).toContain("fetch('/api/video-workflow/describe-image'");
    expect(src).toMatch(/headers\['Authorization'\] = getAuthToken\(\)/);
    expect(src).toMatch(/body: JSON\.stringify\(\{ image_url: imgUrl \}\)/);
    // 状态提示必须用文件内已定义的 updateStatus（曾误用不存在的 showStatus 导致 ReferenceError）
    expect(src).toMatch(/updateStatus\(tr\('panorama_describe_failed'/);
    expect(src).not.toContain('showStatus(');
    // 识图 loading：提示词框 placeholder 动态省略号（用户视线焦点处），
    // 所有出口（成功/失败/过期）都恢复 placeholder；节点销毁清理定时器
    expect(src).toMatch(/function setPromptLoading\(on\)/);
    expect(src).toMatch(/promptEl\.setAttribute\('placeholder', text\)/);
    expect(src).toMatch(/promptLoadingTimer = setInterval\(tick, 400\)/);
    expect(src).toMatch(/setPromptLoading\(true\);/);
    expect(src).toMatch(/setPromptLoading\(false\);\s*\n\s*if \(data && data\.success/);
    expect(src).toMatch(/onDestroy[\s\S]*?setPromptLoading\(false\)/);
    // 过期响应（token 不匹配）不清 loading：新调用已接管，避免竞态闪烁
    // 过期响应守卫（重新识图/换源后丢弃旧响应）+ 等待期间用户手动输入不覆盖
    expect(src).toMatch(/if \(token !== describeToken\) return;/);
    expect(src).toMatch(/if \(String\(node\.data\.prompt \|\| ''\)\.trim\(\) \|\| promptEl\.value\.trim\(\)\) return;/);
    // 识图文案（loading / 成功 / 失败降级）
    expect(src).toContain("'panorama_describing'");
    expect(src).toContain("'panorama_image_prompt_described'");
    expect(src).toContain("'panorama_describe_failed'");
  });

  it('server.py：VL 描述接口路由存在', () => {
    const src = readSource('server.py');
    expect(src).toContain("@app.post('/api/video-workflow/describe-image')");
    expect(src).toContain('from services.image_describe import describe_image');
  });
});
