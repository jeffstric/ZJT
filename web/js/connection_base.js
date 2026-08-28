// ============================
// connection_base.js - 统一连接渲染系统
// 封装贝塞尔曲线计算、SVG元素创建、统一渲染逻辑
// ============================

/**
 * 获取端口的世界坐标位置
 * @param {HTMLElement} portEl - 端口DOM元素
 * @returns {{x: number, y: number}} 世界坐标
 */
function getPortWorldPos(portEl) {
  if (!portEl || !canvasContainer) return { x: 0, y: 0 };
  var rect = portEl.getBoundingClientRect();
  var containerRect = canvasContainer.getBoundingClientRect();
  return {
    x: (rect.left + rect.width / 2 - containerRect.left - state.panX) / state.zoom,
    y: (rect.top + rect.height / 2 - containerRect.top - state.panY) / state.zoom
  };
}

/**
 * 计算鼠标位置到端口的距离
 * @param {HTMLElement} portEl - 端口DOM元素
 * @param {number} mouseX - 鼠标X坐标（世界坐标）
 * @param {number} mouseY - 鼠标Y坐标（世界坐标）
 * @returns {{dist: number, x: number, y: number}} 距离和端口世界坐标
 */
function getPortDistance(portEl, mouseX, mouseY) {
  var pos = getPortWorldPos(portEl);
  var dx = mouseX - pos.x;
  var dy = mouseY - pos.y;
  return { dist: Math.sqrt(dx * dx + dy * dy), x: pos.x, y: pos.y };
}

/**
 * 计算两个端口之间的贝塞尔曲线路径
 * @param {HTMLElement} fromPort - 起始端口（输出端口）
 * @param {HTMLElement} toPort - 目标端口（输入端口）
 * @returns {{fromX: number, fromY: number, toX: number, toY: number, dx: number, pathD: string}}
 */
function calcBezierPath(fromPort, toPort) {
  var from = getPortWorldPos(fromPort);
  var to = getPortWorldPos(toPort);
  var dx = Math.abs(to.x - from.x) * 0.5;
  var pathD = 'M' + from.x + ',' + from.y + ' C' + (from.x + dx) + ',' + from.y + ' ' + (to.x - dx) + ',' + to.y + ' ' + to.x + ',' + to.y;
  return { fromX: from.x, fromY: from.y, toX: to.x, toY: to.y, dx: dx, pathD: pathD };
}

/**
 * 创建连接线SVG组元素（hitbox + visible path）
 * @param {string} groupClass - SVG group的CSS类名
 * @param {number} connId - 连接ID
 * @param {string} pathD - 贝塞尔曲线路径字符串
 * @param {string} [datasetKey] - dataset属性名，默认 'connId'
 * @returns {SVGGElement} SVG group元素
 */
function createConnectionSvgGroup(groupClass, connId, pathD, datasetKey) {
  var group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  group.setAttribute('class', groupClass);
  group.dataset[datasetKey || 'connId'] = String(connId);

  var hitbox = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  hitbox.setAttribute('d', pathD);
  hitbox.setAttribute('class', 'hitbox');
  hitbox.style.fill = 'none';
  hitbox.style.stroke = 'transparent';
  hitbox.style.strokeWidth = '20';
  hitbox.style.cursor = 'pointer';

  var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', pathD);
  path.setAttribute('class', 'visible');
  path.style.fill = 'none';
  path.style.pointerEvents = 'none';

  group.appendChild(hitbox);
  group.appendChild(path);

  return group;
}

/**
 * 在贝塞尔曲线中点显示删除按钮
 * @param {number} fromX - 起点X
 * @param {number} fromY - 起点Y
 * @param {number} toX - 终点X
 * @param {number} toY - 终点Y
 * @param {number} dx - 控制点偏移量
 */
function showConnDeleteBtnAtMidpoint(fromX, fromY, toX, toY, dx) {
  var cx1 = fromX + dx, cy1 = fromY;
  var cx2 = toX - dx, cy2 = toY;
  var t = 0.5, mt = 0.5;
  var bezierX = mt*mt*mt*fromX + 3*mt*mt*t*cx1 + 3*mt*t*t*cx2 + t*t*t*toX;
  var bezierY = mt*mt*mt*fromY + 3*mt*mt*t*cy1 + 3*mt*t*t*cy2 + t*t*t*toY;
  var screenX = bezierX * state.zoom + state.panX;
  var screenY = bezierY * state.zoom + state.panY;
  if (!connDeleteBtn) return;
  connDeleteBtn.style.display = 'flex';
  connDeleteBtn.style.left = (screenX - 12) + 'px';
  connDeleteBtn.style.top = (screenY - 12) + 'px';
}

/**
 * 清除所有非主连接的选中状态
 */
function clearAllConnSelections() {
  state.selectedConnId = null;
  state.selectedImgConnId = null;
  state.selectedFirstFrameConnId = null;
  state.selectedVideoConnId = null;
  state.selectedReferenceConnId = null;
  state.selectedAudioConnId = null;
}

/**
 * 统一连接渲染函数
 * 替代 renderImageConnections / renderVideoConnections / renderAudioConnections / renderReferenceConnections / renderFirstFrameConnections
 *
 * @param {Object} cfg - 连接类型配置
 * @param {Function} cfg.connections - 返回连接数组的函数
 * @param {string} cfg.selectedKey - state中选中连接ID的key
 * @param {string} cfg.groupClass - SVG group的CSS类名
 * @param {string|Function} cfg.toPortSelector - 目标端口CSS选择器，可以是函数(conn)
 * @param {string} cfg.stroke - 连接线颜色
 * @param {string} cfg.strokeWidth - 连接线宽度
 * @param {string} [cfg.strokeDasharray] - 虚线样式
 * @param {string} cfg.selectedStroke - 选中时的颜色
 * @param {string} [cfg.cssClass] - 使用CSS class而非内联样式（如 'reference-line'）
 * @param {string} [cfg.datasetKey] - dataset属性名
 */
function renderConnectionType(cfg) {
  try {
    if (!connectionsSvg || !canvasEl || !canvasContainer) return;

    var conns = cfg.connections();
    if (!conns) return;

    // 清除旧线
    var oldLines = document.querySelectorAll('.' + cfg.groupClass);
    for (var i = 0; i < oldLines.length; i++) oldLines[i].remove();

    // 检查选中状态
    var selKey = cfg.selectedKey;
    if (state[selKey] !== null) {
      var stillExists = conns.some(function(c) { return c.id === state[selKey]; });
      if (!stillExists) {
        state[selKey] = null;
        if (connDeleteBtn) connDeleteBtn.style.display = 'none';
      }
    }

    for (var ci = 0; ci < conns.length; ci++) {
      var conn = conns[ci];
      var fromEl = canvasEl.querySelector('.node[data-node-id="' + conn.from + '"]');
      var toEl = canvasEl.querySelector('.node[data-node-id="' + conn.to + '"]');
      if (!fromEl || !toEl) continue;

      var outputPort = fromEl.querySelector('.port.output');
      var toSelector = typeof cfg.toPortSelector === 'function'
        ? cfg.toPortSelector(conn)
        : cfg.toPortSelector;
      var inputPort = toEl.querySelector(toSelector);
      if (!outputPort || !inputPort) continue;

      var bezier = calcBezierPath(outputPort, inputPort);
      var group = createConnectionSvgGroup(cfg.groupClass, conn.id, bezier.pathD, cfg.datasetKey);

      // 应用样式
      var visiblePath = group.querySelector('.visible');
      var isSelected = state[selKey] === conn.id;

      if (cfg.cssClass) {
        // 使用CSS class（如 reference-line）
        visiblePath.setAttribute('class', cfg.cssClass);
        if (isSelected) visiblePath.classList.add('selected');
      } else {
        visiblePath.style.stroke = isSelected ? cfg.selectedStroke : cfg.stroke;
        visiblePath.style.strokeWidth = isSelected ? '3' : cfg.strokeWidth;
        if (cfg.strokeDasharray) {
          visiblePath.style.strokeDasharray = isSelected ? 'none' : cfg.strokeDasharray;
        }
      }

      connectionsSvg.appendChild(group);

      // 点击选中
      var connId = conn.id;
      (function(cId) {
        group.querySelector('.hitbox').addEventListener('click', function(e) {
          e.stopPropagation();
          clearAllConnSelections();
          state[selKey] = cId;
          renderAllConnections();
        });
      })(connId);

      // 删除按钮
      if (isSelected) {
        showConnDeleteBtnAtMidpoint(bezier.fromX, bezier.fromY, bezier.toX, bezier.toY, bezier.dx);
      }
    }

    // 如果没有连接被选中，隐藏删除按钮
    if (state[selKey] === null && connDeleteBtn) {
      connDeleteBtn.style.display = 'none';
    }
  } catch (error) {
    console.error('[renderConnectionType] Error:', error);
  }
}

/**
 * 统一连接类型配置
 */
var CONNECTION_TYPES = {
  image: {
    connections: function() { return state.imageConnections; },
    selectedKey: 'selectedImgConnId',
    groupClass: 'image-conn-group',
    datasetKey: 'imgConnId',
    toPortSelector: function(conn) {
      if (conn.portType === 'extracted') return '.port.input';
      if (conn.portType === 'ref-image') return '.ref-image-input-port';
      return '.' + conn.portType + '-image-port';
    },
    stroke: '#3b82f6',
    strokeWidth: '2',
    selectedStroke: '#1d4ed8'
  },
  firstFrame: {
    connections: function() { return state.firstFrameConnections; },
    selectedKey: 'selectedFirstFrameConnId',
    groupClass: 'first-frame-conn-group',
    datasetKey: 'firstFrameConnId',
    toPortSelector: '.first-frame-port',
    stroke: '#3b82f6',
    strokeWidth: '2',
    selectedStroke: '#1d4ed8'
  },
  video: {
    connections: function() { return state.videoConnections; },
    selectedKey: 'selectedVideoConnId',
    groupClass: 'video-conn-group',
    datasetKey: 'videoConnId',
    toPortSelector: '.port.video-ref-input-port',
    stroke: '#3b82f6',
    strokeWidth: '2',
    selectedStroke: '#1d4ed8'
  },
  audio: {
    connections: function() { return state.audioConnections; },
    selectedKey: 'selectedAudioConnId',
    groupClass: 'audio-conn-group',
    datasetKey: 'audioConnId',
    toPortSelector: '.port.audio-input-port',
    stroke: '#8b5cf6',
    strokeWidth: '2',
    strokeDasharray: '6,3',
    selectedStroke: '#6d28d9'
  },
  reference: {
    connections: function() { return state.referenceConnections; },
    selectedKey: 'selectedReferenceConnId',
    groupClass: 'reference-conn-group',
    datasetKey: 'referenceConnId',
    toPortSelector: '.port.reference',
    stroke: '#8b5cf6',
    strokeWidth: '2',
    selectedStroke: '#6d28d9',
    cssClass: 'reference-line'
  }
};

/**
 * 渲染所有连接类型（统一入口）
 * @param {Object} [opts] - 渲染选项
 * @param {boolean} [opts.skipSizeUpdate] - 跳过 updateCanvasSize（拖拽过程中调用方负责在结束时补偿）
 */
function renderAllConnections(opts) {
  renderConnections(null, opts && opts.skipSizeUpdate);
  renderConnectionType(CONNECTION_TYPES.image);
  renderConnectionType(CONNECTION_TYPES.firstFrame);
  renderConnectionType(CONNECTION_TYPES.video);
  renderConnectionType(CONNECTION_TYPES.reference);
  renderConnectionType(CONNECTION_TYPES.audio);
}

// ============================
// 连接渲染调度（性能优化）
// 高频交互路径（拖拽/平移/缩放过程中的 mousemove、滚轮）通过 rAF 合帧，
// 同一帧内多次请求只做一次全量渲染，避免主线程被打满导致页面卡死
// ============================
var _connRenderRafId = null;
var _connRenderPendingOpts = null;

/**
 * 调度一次全量连接渲染（rAF 合帧，幂等）
 * @param {Object} [opts] - 透传给 renderAllConnections 的选项
 * @param {boolean} [opts.skipSizeUpdate] - 拖拽过程中跳过 updateCanvasSize，避免高频 layout 读取
 */
function scheduleConnectionsRender(opts) {
  _connRenderPendingOpts = _connRenderPendingOpts || opts || {};
  if (_connRenderRafId !== null) return;
  _connRenderRafId = requestAnimationFrame(function() {
    _connRenderRafId = null;
    var pendingOpts = _connRenderPendingOpts;
    _connRenderPendingOpts = null;
    renderAllConnections(pendingOpts);
  });
}

/**
 * 取消挂起的调度并立即全量渲染
 * 供拖拽结束、删除连线等需要同步拿到最终状态的场景调用
 */
function flushConnectionsRender() {
  if (_connRenderRafId !== null) {
    cancelAnimationFrame(_connRenderRafId);
    _connRenderRafId = null;
  }
  _connRenderPendingOpts = null;
  renderAllConnections();
}

/**
 * 仅更新选中连线删除按钮的屏幕位置（不重画连线）
 * 画布平移时连线随 canvasWorld 的 CSS transform 整体移动、世界坐标不变，重画是多余的；
 * 但删除按钮挂在屏幕坐标系上，需要跟随平移重新定位
 */
function updateSelectedConnDeleteBtnPos() {
  if (!connDeleteBtn || connDeleteBtn.style.display === 'none') return;
  // 普通连接：删除按钮在直线中点
  if (state.selectedConnId !== null) {
    var conn = null;
    for (var i = 0; i < state.connections.length; i++) {
      if (state.connections[i].id === state.selectedConnId) { conn = state.connections[i]; break; }
    }
    if (conn) {
      var from = getOutputPortPos(conn.from);
      var to = getInputPortPos(conn.to);
      var midX = ((from.x + to.x) / 2) * state.zoom + state.panX;
      var midY = ((from.y + to.y) / 2) * state.zoom + state.panY;
      connDeleteBtn.style.left = (midX - 12) + 'px';
      connDeleteBtn.style.top = (midY - 12) + 'px';
    }
    return;
  }
  // 类型连接（图片/首帧/视频/参考/音频）：删除按钮在贝塞尔中点
  var typeKeys = Object.keys(CONNECTION_TYPES);
  for (var t = 0; t < typeKeys.length; t++) {
    var cfg = CONNECTION_TYPES[typeKeys[t]];
    var selId = state[cfg.selectedKey];
    if (selId === null) continue;
    var conns = cfg.connections();
    var selConn = null;
    for (var j = 0; j < conns.length; j++) {
      if (conns[j].id === selId) { selConn = conns[j]; break; }
    }
    if (!selConn) continue;
    var fromEl = canvasEl.querySelector('.node[data-node-id="' + selConn.from + '"]');
    var toEl = canvasEl.querySelector('.node[data-node-id="' + selConn.to + '"]');
    if (!fromEl || !toEl) continue;
    var outputPort = fromEl.querySelector('.port.output');
    var toSelector = typeof cfg.toPortSelector === 'function' ? cfg.toPortSelector(selConn) : cfg.toPortSelector;
    var inputPort = toEl.querySelector(toSelector);
    if (!outputPort || !inputPort) continue;
    var bezier = calcBezierPath(outputPort, inputPort);
    showConnDeleteBtnAtMidpoint(bezier.fromX, bezier.fromY, bezier.toX, bezier.toY, bezier.dx);
    return;
  }
}

// ============================
// 拖拽连线虚线预览（性能优化）
// 独立的常驻 path 元素，mousemove 时只更新 d 属性，
// 替代原先每帧全删全建普通连线的 renderConnections(tempLine) 方案
// ============================
var _tempConnLineEl = null;

/**
 * 更新拖拽连线时的虚线预览
 * @param {{fromX: number, fromY: number, toX: number, toY: number}} [line] - 起点/终点世界坐标；传 null 或 undefined 隐藏
 */
function updateTempConnLine(line) {
  if (!_tempConnLineEl) {
    _tempConnLineEl = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    _tempConnLineEl.setAttribute('class', 'temp');
    _tempConnLineEl.style.fill = 'none';
  }
  if (!line) {
    if (_tempConnLineEl.parentNode) _tempConnLineEl.remove();
    return;
  }
  var dx = Math.abs(line.toX - line.fromX) * 0.5;
  _tempConnLineEl.setAttribute('d', 'M' + line.fromX + ',' + line.fromY +
    ' C' + (line.fromX + dx) + ',' + line.fromY +
    ' ' + (line.toX - dx) + ',' + line.toY +
    ' ' + line.toX + ',' + line.toY);
  if (!_tempConnLineEl.parentNode) connectionsSvg.appendChild(_tempConnLineEl);
}

/**
 * 删除当前选中的连接（统一入口）
 * 按优先级检查 6 种连接类型，执行删除及类型特定的副作用
 * @returns {boolean} 是否删除了连接
 */
function deleteSelectedConnection() {
  // 1. 普通连接
  if (state.selectedConnId !== null) {
    removeConnection(state.selectedConnId);
    return true;
  }

  // 2. 图片连接
  if (state.selectedImgConnId !== null) {
    var conn = state.imageConnections.find(function(c) { return c.id === state.selectedImgConnId; });
    state.imageConnections = state.imageConnections.filter(function(c) { return c.id !== state.selectedImgConnId; });
    state.selectedImgConnId = null;
    hideConnDeleteBtn();
    renderImageConnections();

    // extracted 类型：清除 extract_frame 节点引用
    if (conn && conn.portType === 'extracted') {
      var fromNode = state.nodes.find(function(n) { return n.id === conn.from; });
      if (fromNode && fromNode.type === 'extract_frame') {
        fromNode.data.extractedImageNodeId = null;
      }
    }

    // 图生视频节点的首尾帧/参考图连接：清除 URL 并更新算力
    if (conn && conn.to) {
      var targetNode = state.nodes.find(function(n) { return n.id === conn.to; });
      if (targetNode && targetNode.type === 'image_to_video') {
        if (conn.portType === 'start') {
          targetNode.data.startUrl = '';
        } else if (conn.portType === 'end') {
          targetNode.data.endUrl = '';
        } else if (conn.portType === 'ref-image') {
          var _fromNode = state.nodes.find(function(n) { return n.id === conn.from; });
          if (_fromNode && targetNode.data.referenceUrls) {
            var srcUrl = typeof getNodeImageUrl === 'function'
              ? getNodeImageUrl(_fromNode)
              : (_fromNode.data.url || _fromNode.data.reference_image);
            var idx = targetNode.data.referenceUrls.indexOf(srcUrl);
            if (idx >= 0) targetNode.data.referenceUrls.splice(idx, 1);
            var targetEl = document.querySelector('.node[data-node-id="' + conn.to + '"]');
            if (targetEl && typeof targetEl._updateReferencePreview === 'function') {
              targetEl._updateReferencePreview();
            }
          }
        }
        if (typeof updateImageToVideoComputingPower === 'function') {
          updateImageToVideoComputingPower(conn.to);
        }
      }
    }

    safeAutoSave();
    return true;
  }

  // 3. 首帧连接
  if (state.selectedFirstFrameConnId !== null) {
    removeFirstFrameConnection(state.selectedFirstFrameConnId);
    return true;
  }

  // 4. 视频连接
  if (state.selectedVideoConnId !== null) {
    state.videoConnections = state.videoConnections.filter(function(c) { return c.id !== state.selectedVideoConnId; });
    state.selectedVideoConnId = null;
    hideConnDeleteBtn();
    renderVideoConnections();
    return true;
  }

  // 5. 参考连接
  if (state.selectedReferenceConnId !== null) {
    var refConn = state.referenceConnections.find(function(c) { return c.id === state.selectedReferenceConnId; });
    state.referenceConnections = state.referenceConnections.filter(function(c) { return c.id !== state.selectedReferenceConnId; });
    state.selectedReferenceConnId = null;
    hideConnDeleteBtn();
    renderReferenceConnections();
    if (refConn) {
      var refTarget = state.nodes.find(function(n) { return n.id === refConn.to; });
      if (refTarget && refTarget.updateReferenceImages) {
        refTarget.updateReferenceImages();
      }
    }
    safeAutoSave();
    return true;
  }

  // 6. 音频连接
  if (state.selectedAudioConnId !== null) {
    var audioConn = state.audioConnections.find(function(c) { return c.id === state.selectedAudioConnId; });
    state.audioConnections = state.audioConnections.filter(function(c) { return c.id !== state.selectedAudioConnId; });
    state.selectedAudioConnId = null;
    hideConnDeleteBtn();
    renderAudioConnections();
    if (audioConn) {
      var audioFrom = state.nodes.find(function(n) { return n.id === audioConn.from; });
      var audioTarget = state.nodes.find(function(n) { return n.id === audioConn.to; });
      if (audioFrom && audioTarget && audioTarget.data.audioUrls) {
        var audioIdx = audioTarget.data.audioUrls.findIndex(function(a) { return a.url === audioFrom.data.url; });
        if (audioIdx >= 0) audioTarget.data.audioUrls.splice(audioIdx, 1);
      }
    }
    safeAutoSave();
    return true;
  }

  return false;
}
