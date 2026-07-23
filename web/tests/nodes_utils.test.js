// nodes.js 共享工具函数测试
// 需要先设置全局环境，因为 nodes.js 中的函数引用了 state、canvasEl 等全局变量

// 创建 stub DOM 元素并挂载到 globalThis（nodes.js 直接引用全局变量）
function createStubEl(id) {
  const el = document.createElement('div');
  el.id = id;
  el.classList = { add: () => {}, remove: () => {}, contains: () => false };
  el.setAttribute = () => {};
  el.removeAttribute = () => {};
  el.addEventListener = () => {};
  el.querySelector = () => null;
  el.querySelectorAll = () => [];
  el.appendChild = () => {};
  el.style = {};
  el.src = '';
  el.textContent = '';
  el.value = '';
  document.body.appendChild(el);
  globalThis[id] = el;
  return el;
}

// 创建 nodes.js 引用的所有 DOM 元素
const modalIds = [
  'videoModal', 'videoModalClose', 'videoModalPlayer',
  'imageModal', 'imageModalClose', 'imageModalImg',
  'shotGroupModal', 'shotGroupModalClose', 'shotGroupModalContent', 'shotGroupModalTitle', 'shotGroupModalEditBtn',
  'shotDetailModal', 'shotDetailModalClose', 'shotDetailModalContent', 'shotDetailModalTitle',
  'shotGroupEditModal', 'shotGroupEditModalContent', 'shotGroupEditModalClose', 'shotGroupEditSaveBtn', 'shotGroupEditCancelBtn',
  'locationModal', 'locationModalClose', 'locationWorldSelect', 'locationSearchInput'
];
modalIds.forEach(id => createStubEl(id));

// 模拟 nodes.js 依赖的全局变量
globalThis.state = { nodes: [], connections: [], style: { name: '' }, ratio: '16:9', debugMode: false };
globalThis.canvasEl = { querySelector: () => null, getBoundingClientRect: () => ({ left: 0, top: 0, width: 1200, height: 800 }) };
globalThis.canvasContainer = { getBoundingClientRect: () => ({ left: 0, top: 0 }) };
globalThis.connectionsSvg = {};
globalThis.connDeleteBtn = { style: {} };
globalThis.getDriverStatusConfig = () => ({});
globalThis.showToast = () => {};
globalThis.safeAutoSave = () => {};
globalThis.renderAllConnections = () => {};
globalThis.getViewportNodePosition = () => ({ x: 100, y: 100 });
globalThis.findNearestAvailablePosition = (x, y) => ({ x, y });
globalThis.findPositionRightward = (x, y) => ({ x, y });
globalThis.bringNodeToFront = () => {};
globalThis.setSelected = () => {};
globalThis.removeNode = () => {};
globalThis.initNodeDrag = () => {};
globalThis.openVideoModal = () => {};
globalThis.addToTimeline = () => {};
globalThis.uploadFile = async () => '';
globalThis.proxyDownloadUrl = (url) => url;
globalThis.addDebugButtonToNode = () => {};
globalThis.getAudioDuration = async () => 5;
globalThis.addAudioToTimeline = () => {};
globalThis.proxyImageUrl = (url) => url;
globalThis.buildDownloadUrl = (url) => url;
globalThis.openImageModal = () => {};
globalThis.i18n = { t: (key) => key };
globalThis.getAuthToken = () => '';
globalThis.getUserId = () => '';
globalThis.TaskConfig = { getTaskIdByKey: () => null, isLoaded: () => false, getModelOptionsForCategory: () => [] };
globalThis.escapeHtml = (v) => String(v || '');

// 加载 nodes.js（通过 module.exports 获取纯函数引用）
const { truncateErrorMessage, resolveGridConfig } = require('../js/nodes.js');

// ── truncateErrorMessage ──
describe('truncateErrorMessage', () => {
  test('null/undefined 直接返回', () => {
    expect(truncateErrorMessage(null)).toBe(null);
    expect(truncateErrorMessage(undefined)).toBe(undefined);
  });

  test('短消息原样返回', () => {
    expect(truncateErrorMessage('error')).toBe('error');
  });

  test('超长消息被截断并添加 ...', () => {
    const longMsg = 'a'.repeat(200);
    const result = truncateErrorMessage(longMsg, 120);
    expect(result.length).toBe(123); // 120 + '...'
    expect(result.endsWith('...')).toBe(true);
  });

  test('自定义 maxLength', () => {
    const result = truncateErrorMessage('a'.repeat(50), 20);
    expect(result.length).toBe(23); // 20 + '...'
  });

  test('提取 JSON 中的 message 字段', () => {
    const msg = 'Request failed: {"error":{"message":"Invalid API key","code":401}}';
    const result = truncateErrorMessage(msg);
    expect(result).toBe('Invalid API key');
  });

  test('提取 message 和 failureReasons', () => {
    const msg = '{"message":"Task failed","failureReasons":["timeout"]}';
    const result = truncateErrorMessage(msg);
    expect(result).toBe('Task failed (timeout)');
  });

  test('移除 "check status failed:" 前缀', () => {
    const msg = 'check status failed: connection timeout';
    const result = truncateErrorMessage(msg);
    expect(result).toBe('connection timeout');
  });

  test('"check status failed:" 不区分大小写', () => {
    const msg = 'Check Status Failed: something';
    const result = truncateErrorMessage(msg);
    expect(result).toBe('something');
  });

  test('非 JSON 格式的长消息正常截断', () => {
    const msg = 'a'.repeat(200);
    const result = truncateErrorMessage(msg);
    expect(result.length).toBe(123);
  });
});

// ── resolveGridConfig ──
describe('resolveGridConfig', () => {
  test('auto 模型 + 无偏好 + shotCount<=5 → 4格', () => {
    const result = resolveGridConfig('auto', null, 3, false);
    expect(result.gridSize).toBe(4);
    expect(result.gridLayout).toBe('2x2');
    expect(result.finalModel).toBe('gpt-image-2');
  });

  test('auto 模型 + 无偏好 + shotCount>5 → 9格', () => {
    const result = resolveGridConfig('auto', null, 8, false);
    expect(result.gridSize).toBe(9);
    expect(result.gridLayout).toBe('3x3');
    expect(result.finalModel).toBe('gpt-image-2');
  });

  test('auto 模型 + 用户选择 4 格 → 保持 4 格', () => {
    const result = resolveGridConfig('auto', '4', 8, false);
    expect(result.gridSize).toBe(4);
    expect(result.gridLayout).toBe('2x2');
  });

  test('auto 模型 + 用户选择 9 格 → 保持 9 格', () => {
    const result = resolveGridConfig('auto', '9', 3, false);
    expect(result.gridSize).toBe(9);
    expect(result.gridLayout).toBe('3x3');
  });

  test('gemini-2.5-flash + 无偏好 → 4格', () => {
    const result = resolveGridConfig('gemini-2.5-flash-image-preview', null, 5, false);
    expect(result.gridSize).toBe(4);
    expect(result.gridLayout).toBe('2x2');
    expect(result.finalModel).toBe('gemini-2.5-flash-image-preview');
  });

  test('gemini-3-pro-4grid + 无偏好 → 4格，模型映射', () => {
    const result = resolveGridConfig('gemini-3-pro-4grid', null, 5, false);
    expect(result.gridSize).toBe(4);
    expect(result.gridLayout).toBe('2x2');
    expect(result.finalModel).toBe('gemini-3-pro-image-preview');
  });

  test('gemini-3-pro-image-preview + 无偏好 → 9格', () => {
    const result = resolveGridConfig('gemini-3-pro-image-preview', null, 5, false);
    expect(result.gridSize).toBe(9);
    expect(result.gridLayout).toBe('3x3');
    expect(result.finalModel).toBe('gemini-3-pro-image-preview');
  });

  test('其他模型 + 无偏好 → 默认 9格', () => {
    const result = resolveGridConfig('seedream', null, 5, false);
    expect(result.gridSize).toBe(9);
    expect(result.gridLayout).toBe('3x3');
    expect(result.finalModel).toBe('seedream');
  });

  test('用户明确选择 4 格覆盖默认', () => {
    const result = resolveGridConfig('gemini-3-pro-image-preview', '4', 5, false);
    expect(result.gridSize).toBe(4);
    expect(result.gridLayout).toBe('2x2');
  });

  test('用户明确选择 9 格覆盖默认', () => {
    const result = resolveGridConfig('gemini-2.5-flash-image-preview', '9', 5, false);
    expect(result.gridSize).toBe(9);
    expect(result.gridLayout).toBe('3x3');
  });
});
