// ============================
// node_base.js - 节点基类公共逻辑
// 封装所有节点的公共创建、事件绑定、端口生成逻辑
// ============================

// ─── 节点尺寸缓存（性能优化） ──────────────────
// updateCanvasSize / renderMinimap / 自动布局等路径原本每次遍历全部节点读取
// offsetWidth/offsetHeight（强制同步布局），节点多时是主要卡顿源之一。
// 这里用单一 ResizeObserver 维护脏标记，读取走缓存；
// 节点增删由 MutationObserver 自动纳入观察，覆盖所有节点创建路径
var _nodeSizeObserver = null;
var _nodeSizeObserverInit = false;
var _observedNodeEls = new WeakSet();

function _observeNodeSizeEl(el) {
  if(_nodeSizeObserver && !_observedNodeEls.has(el)) {
    _observedNodeEls.add(el);
    _nodeSizeObserver.observe(el);
  }
}

function _ensureNodeSizeObserver() {
  if(_nodeSizeObserverInit) return;
  _nodeSizeObserverInit = true;
  if(typeof ResizeObserver === 'undefined' || typeof MutationObserver === 'undefined') return;
  _nodeSizeObserver = new ResizeObserver(function(entries) {
    // 尺寸变化只标脏，数值延迟到 getNodeSize 时读取（offsetWidth 含边框，与原实现口径一致）
    for(const entry of entries) entry.target._sizeDirty = true;
  });
  // 观察已存在的节点（工作流加载时序下调用也安全）
  for(const el of canvasEl.querySelectorAll('.node')) _observeNodeSizeEl(el);
  // 画布上新挂载的节点自动纳入观察
  const mo = new MutationObserver(function(mutations) {
    if(!_nodeSizeObserver) return;
    for(const m of mutations) {
      for(const n of m.addedNodes) {
        if(n.nodeType === 1 && n.classList && n.classList.contains('node')) _observeNodeSizeEl(n);
      }
    }
  });
  mo.observe(canvasEl, { childList: true });
}

/**
 * 读取节点尺寸（带缓存；不支持 ResizeObserver 时降级为直读）
 * @param {Object} node - 节点数据对象
 * @returns {{w: number, h: number}}
 */
function getNodeSize(node) {
  _ensureNodeSizeObserver();
  const el = canvasEl.querySelector('.node[data-node-id="' + node.id + '"]');
  if(!el) return { w: 300, h: 200 };
  if(!_nodeSizeObserver) return { w: el.offsetWidth, h: el.offsetHeight };
  if(el._sizeDirty || !el._cachedSize) {
    el._cachedSize = { w: el.offsetWidth, h: el.offsetHeight };
    el._sizeDirty = false;
  }
  return el._cachedSize;
}

// ─── 输入端口注册表 ───────────────────────────────
// 全局注册表：nodeType → inputPortConfig[]
// 供 events.js 的连接系统自动发现所有可连接端口，无需硬编码节点类型
var _inputPortRegistry = {};
window._inputPortRegistry = _inputPortRegistry;

/**
 * 注册节点类型的输入端口配置
 * @param {string} nodeType - 节点类型标识
 * @param {Array} ports - 输入端口配置数组，每项包含:
 *   @param {string} ports[].selector   - 端口CSS选择器（用于DOM查找）
 *   @param {string} ports[].portType   - 端口类型标识（如 'start', 'end', 'audio'）
 *   @param {string[]} ports[].accepts  - 可接受的源节点类型数组（如 ['image']）
 *   @param {string} [ports[].connectionType] - 使用的连接数组名（默认 'imageConnections'）
 *   @param {Function} [ports[].guard]  - 判断端口当前是否可连接的函数(node) => bool
 *   @param {Function} [ports[].onConnect] - 连接成功后的回调(fromNode, targetNode)
 */
function registerInputPorts(nodeType, ports) {
  _inputPortRegistry[nodeType] = ports;
}

/**
 * 查询节点类型已注册的输入端口
 * @param {string} nodeType - 节点类型标识
 * @returns {Array} 端口配置数组，未注册则返回空数组
 */
function getInputPorts(nodeType) {
  return _inputPortRegistry[nodeType] || [];
}

// ─── 端口预设工厂 ────────────────────────────────
// 常用端口类型的快捷配置，新节点一行声明即可复用
window.PORT_PRESETS = {
  /**
   * 图片输入端口预设（接受 image 类型节点连接）
   * @param {Object} overrides - 覆盖默认配置（selector, guard, onConnect 等）
   */
  IMAGE_INPUT: function(overrides) {
    var base = {
      selector: '.start-image-port',
      portType: 'start',
      accepts: ['image'],
      connectionType: 'imageConnections'
    };
    return Object.assign(base, overrides || {});
  },

  /**
   * 音频输入端口预设（接受 text_to_speech / audio 类型节点连接）
   * @param {Object} overrides - 覆盖默认配置
   */
  AUDIO_INPUT: function(overrides) {
    var base = {
      selector: '.audio-input-port',
      portType: 'audio',
      accepts: ['text_to_speech', 'audio'],
      connectionType: 'audioConnections'
    };
    return Object.assign(base, overrides || {});
  }
};

// ─── 通用端口查找函数 ────────────────────────────
// 供 events.js 的 mousemove（高亮）和 mouseup（连接）共同使用
// 通过注册表自动发现所有可连接端口，新节点类型无需修改 events.js

/**
 * 在画布所有节点中，查找距离鼠标最近的、可接受指定源节点类型的输入端口
 * 替代原先 findNearestI2VPort 中硬编码的节点类型循环
 *
 * @param {number} mouseX - 鼠标在画布坐标系中的 X
 * @param {number} mouseY - 鼠标在画布坐标系中的 Y
 * @param {string} fromType - 源节点类型（如 'image', 'audio'）
 * @param {number} [proximity=50] - 最大吸附距离（像素）
 * @returns {{nodeId: number, portType: string, portCfg: Object, node: Object, x: number, y: number}|null}
 */
function findNearestConnectablePort(mouseX, mouseY, fromType, proximity) {
  proximity = proximity || 50;
  var best = null;
  var bestDist = proximity;

  for (var i = 0; i < state.nodes.length; i++) {
    var node = state.nodes[i];
    var inputPorts = getInputPorts(node.type);
    if (inputPorts.length === 0) continue;

    var toEl = canvasEl.querySelector('.node[data-node-id="' + node.id + '"]');
    if (!toEl) continue;

    for (var j = 0; j < inputPorts.length; j++) {
      var portCfg = inputPorts[j];

      // 检查端口是否接受该源节点类型
      if (portCfg.accepts.indexOf(fromType) === -1) continue;

      // 检查 guard（端口是否当前可用，如未被占用）
      if (portCfg.guard && !portCfg.guard(node)) continue;

      var portEl = toEl.querySelector(portCfg.selector);
      if (!portEl || portEl.classList.contains('disabled')) continue;

      var result = getPortDistance(portEl, mouseX, mouseY);
      if (result.dist < bestDist) {
        bestDist = result.dist;
        best = {
          nodeId: node.id,
          portType: portCfg.portType,
          portCfg: portCfg,
          node: node,
          x: result.x,
          y: result.y
        };
      }
    }
  }
  return best;
}

/**
 * 扫描节点DOM的i18n属性
 */
function scanNodeI18n(el) {
  if (typeof window.ZJTi18nDOM !== 'undefined') {
    setTimeout(() => window.ZJTi18nDOM.scanDOM(el), 0);
  }
}

/**
 * 根据端口配置数组生成HTML字符串
 * @param {Array} ports - 端口配置数组
 * @returns {string} HTML字符串
 */
function generatePortsHtml(ports) {
  if (!ports || ports.length === 0) return '';
  return ports.map(function(port) {
    var dir = port.direction;
    var extraClass = port.cssClass ? ' ' + port.cssClass : '';
    var title = escapeHtml(port.title || '');
    var i18nAttr = port.titleI18nKey
      ? ' data-i18n="' + port.titleI18nKey + ':title"'
      : '';
    return '<div class="port ' + dir + extraClass + '" title="' + title + '"' + i18nAttr + '></div>';
  }).join('\n');
}

/**
 * 节点基类工厂函数 - 封装所有节点的公共创建逻辑
 *
 * @param {Object} config - 节点配置
 * @param {string} config.type - 节点类型标识，如 'image', 'video'
 * @param {string|Function} config.title - 默认标题或标题生成函数(opts)
 * @param {Object|Function} config.defaultData - 默认数据或数据生成函数(opts)
 * @param {Array} config.ports - 端口配置数组
 * @param {string} [config.cssClass] - 额外的CSS类名
 * @param {number} config.width - 节点宽度（用于碰撞检测）
 * @param {number} config.height - 节点高度（用于碰撞检测）
 * @param {string|Function} config.bodyHtml - 节点body的HTML字符串或函数(opts, node)
 * @param {string} [config.titleIcon] - 标题前的SVG图标HTML
 * @param {Function} [config.onCreated] - DOM创建后的自定义初始化回调(node, el, opts)
 * @param {Object} [opts] - 创建选项 { x, y, checkCollision, ... }
 * @returns {number} 节点ID
 */
function createNodeBase(config, opts) {
  // === 1. ID与位置 ===
  var id = state.nextNodeId++;
  var viewportPos = getViewportNodePosition();
  var x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
  var y = Math.max(MIN_NODE_Y, opts && typeof opts.y === 'number' ? opts.y : viewportPos.y);

  if (opts && opts.checkCollision && config.width && config.height) {
    var avail = findNearestAvailablePosition(x, y, config.width, config.height);
    x = avail.x;
    y = Math.max(MIN_NODE_Y, avail.y);
  }

  // === 2. 构建节点数据对象 ===
  var defaultData = typeof config.defaultData === 'function'
    ? config.defaultData(opts)
    : (config.defaultData || {});

  var title = typeof config.title === 'function' ? config.title(opts) : config.title;

  var node = {
    id: id,
    type: config.type,
    title: title,
    x: x,
    y: y,
    data: JSON.parse(JSON.stringify(defaultData))
  };
  state.nodes.push(node);

  // === 3. 创建DOM骨架 ===
  var el = document.createElement('div');
  el.className = 'node' + (config.cssClass ? ' ' + config.cssClass : '');
  el.dataset.nodeId = String(id);
  el.dataset.type = config.type;
  el.style.left = node.x + 'px';
  el.style.top = node.y + 'px';

  // === 4. 生成HTML ===
  var portsHtml = generatePortsHtml(config.ports);
  var bodyHtml = typeof config.bodyHtml === 'function'
    ? config.bodyHtml(opts, node)
    : (config.bodyHtml || '');
  var titleIcon = config.titleIcon || '';
  var deleteTitle = window.t ? window.t('node_delete_btn') : '删除';

  el.innerHTML =
    portsHtml +
    '<div class="node-header">' +
      '<div class="node-title">' + titleIcon + title + '</div>' +
      '<button class="icon-btn" title="' + deleteTitle + '">\u00d7</button>' +
    '</div>' +
    '<div class="node-body">' +
      bodyHtml +
    '</div>';

  // === 5. 绑定公共事件 ===
  bindNodeBaseEvents(el, node, config.ports);

  // === 6. 节点特定初始化 ===
  if (config.onCreated) {
    config.onCreated(node, el, opts);
  }

  // === 7. 调试按钮 ===
  if (typeof addDebugButtonToNode === 'function') {
    addDebugButtonToNode(el, node);
  }

  // === 8. 挂载到画布 ===
  canvasEl.appendChild(el);
  setSelected(id);

  // === 9. i18n扫描 ===
  scanNodeI18n(el);

  return id;
}

/**
 * 绑定节点的公共事件（删除、选中、拖拽、输出端口）
 * @param {HTMLElement} el - 节点DOM元素
 * @param {Object} node - 节点数据对象
 * @param {Array} ports - 端口配置数组
 */
function bindNodeBaseEvents(el, node, ports) {
  var id = node.id;
  var headerEl = el.querySelector('.node-header');
  var deleteBtn = el.querySelector('.icon-btn');

  // 1. 删除按钮
  if (deleteBtn) {
    deleteBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      removeNode(id);
    });
  }

  // 2. 节点mousedown选中
  el.addEventListener('mousedown', function(e) {
    if (e.target.classList && e.target.classList.contains('port')) return;
    e.stopPropagation();
    setSelected(id);
    bringNodeToFront(id);
  });

  // 3. header拖拽
  if (headerEl) {
    headerEl.addEventListener('mousedown', function(e) {
      if (e.target.classList && e.target.classList.contains('port')) return;
      e.preventDefault();
      e.stopPropagation();
      if (!state.selectedNodeIds.includes(id)) {
        setSelected(id);
      }
      bringNodeToFront(id);
      initNodeDrag(id, e.clientX, e.clientY);
    });
  }

  // 4. 输出端口 mousedown
  if (ports) {
    for (var i = 0; i < ports.length; i++) {
      (function(portCfg, index) {
        if (portCfg.direction !== 'output') return;
        var selector = portCfg.cssClass
          ? '.port.output.' + portCfg.cssClass
          : (index === 0 ? '.port.output' : '.port.output');
        // 如果有多个output端口，用nth-of-type可能不准确，用data属性更可靠
        var portEl = el.querySelector(selector);
        if (portEl) {
          portEl.addEventListener('mousedown', function(e) {
            e.preventDefault();
            e.stopPropagation();
            state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
          });
        }
      })(ports[i], i);
    }
  }
}

/**
 * 绑定输入端口的通用连接逻辑
 * @param {HTMLElement} el - 节点DOM元素
 * @param {Object} node - 节点数据对象
 * @param {Object} portCfg - 端口配置
 */
function bindInputPortEvents(el, node, portCfg) {
  var id = node.id;
  var selector = portCfg.cssClass
    ? '.port.input.' + portCfg.cssClass
    : '.port.input';
  var portEl = el.querySelector(selector);
  if (!portEl) return;

  portEl.addEventListener('mouseup', function(e) {
    if (!state.connecting || state.connecting.fromId === id) {
      state.connecting = null;
      return;
    }

    var fromNode = state.nodes.find(function(n) { return n.id === state.connecting.fromId; });
    if (!fromNode) {
      state.connecting = null;
      return;
    }

    // 类型验证
    if (portCfg.acceptType) {
      var acceptTypes = Array.isArray(portCfg.acceptType) ? portCfg.acceptType : [portCfg.acceptType];
      if (!acceptTypes.includes(fromNode.type)) {
        if (typeof showToast === 'function') {
          showToast(window.t ? window.t('camera_control_input_error') : '连接类型不匹配', 'warning');
        }
        state.connecting = null;
        return;
      }
    }

    // 获取连接数组
    var connArray = portCfg.connectionType ? state[portCfg.connectionType] : state.connections;
    if (!connArray) {
      state.connecting = null;
      return;
    }

    // 检查重复连接（同一目标端口只允许一条连接）
    var exists = connArray.some(function(c) { return c.from === state.connecting.fromId && c.to === id; });
    if (exists) {
      state.connecting = null;
      return;
    }

    // 确定连接ID的key
    var connIdKey = 'nextConnId';
    if (portCfg.connectionType === 'imageConnections') connIdKey = 'nextImgConnId';
    else if (portCfg.connectionType === 'videoConnections') connIdKey = 'nextVideoConnId';
    else if (portCfg.connectionType === 'referenceConnections') connIdKey = 'nextReferenceConnId';
    else if (portCfg.connectionType === 'firstFrameConnections') connIdKey = 'nextFirstFrameConnId';
    else if (portCfg.connectionType === 'audioConnections') connIdKey = 'nextAudioConnId';

    // 创建连接
    var conn = {
      id: state[connIdKey]++,
      from: state.connecting.fromId,
      to: id
    };
    connArray.push(conn);

    // 渲染连接线
    if (typeof renderAllConnections === 'function') renderAllConnections();
    if (typeof renderMinimap === 'function') renderMinimap();

    // 自定义回调
    if (portCfg.onConnect) {
      portCfg.onConnect(fromNode, conn);
    }

    safeAutoSave();

    state.connecting = null;
  });
}

/**
 * 通用节点恢复函数工厂
 * @param {Function} createFn - 对应的创建函数
 * @param {Function} [restoreDomFn] - 自定义DOM恢复逻辑(el, node, nodeData)
 * @returns {Function} 带数据创建函数
 */
/**
 * 安全调用 autoSaveWorkflow，吞掉异常避免影响调用方
 * 性能优化：防抖合并高频调用——PUT 上传（全量序列化 + 上传）节点多时成本很高，
 * 全页面有 100+ 处调用点，必须防抖合并。
 * 撤销语义：历史快照在每次调用时【立即】捕获（captureHistorySnapshot 内部有
 * 去重，无变化时开销小），防抖仅作用于 PUT 上传。否则 1.5s 内多次操作会被
 * 合并成一份快照，Ctrl+Z 一次撤销多个操作。
 * 删除节点、页面卸载等需要立即落盘的场景调用 flushAutoSave()
 */
let _autoSaveDebounceTimer = null;

function cancelPendingAutoSave(){
  if(_autoSaveDebounceTimer){
    clearTimeout(_autoSaveDebounceTimer);
    _autoSaveDebounceTimer = null;
  }
}
const AUTO_SAVE_DEBOUNCE_MS = 1500;

function safeAutoSave() {
  // 历史快照立即捕获（去重后无变化几乎零成本），保证每个操作都有独立撤销点
  try {
    if (typeof captureHistorySnapshot === 'function') captureHistorySnapshot();
  } catch(e) {}
  // 记录待确认版本：关页逻辑据此区分"全部已确认"与"有未确认修改
  // （定时器待发 / 请求在途 / 响应未达）"，而不是只看定时器是否存在
  if(typeof autoSaveState !== 'undefined') autoSaveState.markDirty();
  if(_autoSaveDebounceTimer) clearTimeout(_autoSaveDebounceTimer);
  _autoSaveDebounceTimer = setTimeout(() => {
    _autoSaveDebounceTimer = null;
    try { autoSaveWorkflow({ skipHistory: true }); } catch(e) {}
  }, AUTO_SAVE_DEBOUNCE_MS);
}

/**
 * 取消挂起的防抖并立即执行一次自动保存
 * 删除节点等场景调用前状态已变更，先补一个历史快照保证撤销链完整
 */
function flushAutoSave() {
  cancelPendingAutoSave();
  try {
    if (typeof captureHistorySnapshot === 'function') captureHistorySnapshot();
    if(typeof autoSaveState !== 'undefined') autoSaveState.markDirty();
    autoSaveWorkflow({ skipHistory: true });
  } catch(e) {}
}

// 页面卸载时补发未确认的自动保存。
//
// 只检查防抖定时器是不够的：定时器触发后 / flushAutoSave 已启动普通 fetch 时，
// 定时器为 null 而请求仍在途（或响应未达），普通 fetch 在卸载时可能被取消 →
// 丢最后一次修改。因此按 autoSaveState（version/confirmedVersion/inFlight）判断
// "是否有未确认修改"，而不是"定时器是否存在"。
//
// - 可 keepalive 的 body（≤64KiB，KEEPALIVE_BODY_MAX_BYTES 留余量）用 keepalive，
//   浏览器在卸载后继续发送（sendBeacon 无法携带 X-User-Id/Authorization 头，
//   端点依赖 X-User-Id，故不用）。
// - 大工作流超限无法 keepalive：best-effort 普通 fetch 尽力而为，同时由
//   IndexedDB 恢复记录降低丢失风险（下次加载时重放未确认记录）。
//   卸载时的同步 put 只表示事务入队，不能承诺已持久化。
// - 关页路径必须在事件同步调用栈内启动 fetch，不能先 await IndexedDB；
//   autoSaveWorkflow({ unload: true }) 会先尽力排队本地快照，随后在任何 await
//   之前同步创建 fetch。IndexedDB 仅作 best-effort 恢复，不能替代 keepalive。
//
// body 按 UTF-8 实际字节数度量（new Blob.size）：中文每字符 3 字节。
// 提前预热 IDB 连接，尽量使卸载时的同步 put 可以立即入队。
if(typeof WorkflowRecovery !== 'undefined'){
  WorkflowRecovery.prepare().catch(() => null);
}
window.addEventListener('beforeunload', () => {
  try {
    if(typeof WorkflowRecovery === 'undefined' || typeof autoSaveState === 'undefined') return;
    WorkflowRecovery.dispatchBeforeUnloadSave({
      saveState: autoSaveState,
      serializeBody: () => JSON.stringify({
        workflow_data: serializeWorkflow(),
        default_world_id: state.defaultWorldId,
        workflow_ratio: state.ratio
      }),
      measureBodyBytes: (body) => new Blob([body]).size,
      cancelPending: cancelPendingAutoSave,
      warnLargeBody: () => console.warn(
        'beforeunload save: body exceeds keepalive 64KiB limit, best-effort fetch + IndexedDB recovery fallback'
      ),
      // dispatch 保证这个回调同步调用；autoSaveWorkflow 的 unload 分支
      // 再由 startUnloadSend 直接同步调用 fetch。
      send: (saveOptions) => autoSaveWorkflow(saveOptions)
    });
  } catch(e) {}
});

/**
 * 设置按钮为加载状态
 * @param {HTMLElement} btn - 按钮元素
 * @param {string} loadingText - 加载中显示的文本
 */
function setBtnLoading(btn, loadingText) {
  btn.disabled = true;
  btn.textContent = loadingText;
}

/**
 * 设置按钮为就绪状态
 * @param {HTMLElement} btn - 按钮元素
 * @param {string} readyText - 就绪时显示的文本
 */
function setBtnReady(btn, readyText) {
  btn.disabled = false;
  btn.textContent = readyText;
}

/**
 * 设置视频缩略图的通用属性（封面帧 + 悬停播放）
 * 性能优化：不再 loop 常驻解码——N 个视频节点同时循环播放会耗尽内存导致浏览器崩溃，
 * 改为加载 metadata 后 seek 到第一帧作为封面，鼠标悬停节点时才播放
 * @param {HTMLVideoElement} thumbVideo - 视频元素
 * @param {string} url - 视频URL
 */
function setupVideoThumbnail(thumbVideo, url) {
  thumbVideo.src = proxyDownloadUrl(url);
  thumbVideo.muted = true;
  thumbVideo.controls = false;
  thumbVideo.preload = 'metadata';
  thumbVideo.playsInline = true;
  thumbVideo.loop = false;
  // metadata 就绪后 seek 到第一帧显示封面
  thumbVideo.onloadedmetadata = function() {
    try{
      if(isFinite(thumbVideo.duration) && thumbVideo.duration > 0){
        thumbVideo.currentTime = Math.min(0.1, Math.max(0, thumbVideo.duration - 0.1));
      }
    } catch(e){}
  };
  try { thumbVideo.load(); } catch(e) {}
  attachVideoHoverPreview(thumbVideo);
}

/**
 * 绑定"悬停节点播放、移开暂停并回到封面帧"的视频预览交互
 * 手动播放状态（thumbVideo.dataset.manualPlay === '1'，由节点播放按钮维护）不受移开暂停影响
 * @param {HTMLVideoElement} thumbVideo - 节点内的视频缩略元素
 */
function attachVideoHoverPreview(thumbVideo) {
  if(!thumbVideo || thumbVideo._hoverPreviewBound) return;
  const nodeEl = thumbVideo.closest('.node');
  if(!nodeEl) return;
  thumbVideo._hoverPreviewBound = true;
  nodeEl.addEventListener('mouseenter', () => {
    if(!thumbVideo.src || thumbVideo.dataset.manualPlay === '1') return;
    try{
      const p = thumbVideo.play();
      if(p && typeof p.catch === 'function') p.catch(() => {});
    } catch(e){}
  });
  nodeEl.addEventListener('mouseleave', () => {
    if(thumbVideo.dataset.manualPlay === '1') return;
    try{
      thumbVideo.pause();
      if(isFinite(thumbVideo.duration) && thumbVideo.duration > 0){
        thumbVideo.currentTime = Math.min(0.1, Math.max(0, thumbVideo.duration - 0.1));
      }
    } catch(e){}
  });
}

/**
 * 设置状态元素的文本和颜色
 * @param {HTMLElement} el - 状态元素
 * @param {string} text - 状态文本
 * @param {string} [color] - 颜色值（如 '#16a34a'），不传则重置
 */
function setStatusEl(el, text, color) {
  if (!el) return;
  el.style.color = color || '';
  el.textContent = text;
}

function createNodeWithDataFactory(createFn, restoreDomFn) {
  return function(nodeData) {
    // 保存和恢复nextNodeId
    var savedNextNodeId = state.nextNodeId;
    state.nextNodeId = nodeData.id;

    createFn({ x: nodeData.x, y: nodeData.y });

    state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);

    // 查找节点
    var node = state.nodes.find(function(n) { return n.id === nodeData.id; });
    if (!node) return;

    // 恢复标题
    if (nodeData.title) node.title = nodeData.title;

    // 合并数据
    if (nodeData.data) {
      Object.assign(node.data, nodeData.data);
    }

    // DOM恢复
    if (restoreDomFn) {
      var el = canvasEl.querySelector('.node[data-node-id="' + nodeData.id + '"]');
      if (el) {
        restoreDomFn(el, node, nodeData);
      }
    }
  };
}
