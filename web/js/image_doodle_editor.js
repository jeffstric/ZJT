// Image Doodle Editor Module
// 仿火山引擎「涂鸦编辑」弹窗：为图片节点提供手绘标注能力。
// 架构要点：
//  - 对象模型：所有涂鸦元素（笔画/矩形/文字）是 plain object，canvas 每次全量重绘；
//  - 坐标系：元素几何存「图片自然像素系」，渲染乘显示缩放，确认时按原图分辨率合成导出；
//  - 撤销/重做：命令栈（{action, before, after} 快照），栈上限 MAX_UNDO；
//  - 橡皮擦为对象级删除（划过命中的元素整条删除），与对象模型自洽；
//  - Page-agnostic：open() 时动态注入 modal DOM，加载期无副作用（便于 Vitest 测纯函数）。
//  - 弹窗打开期间拦截 Ctrl+Z / Delete，避免触发工作流级撤销/删除节点（events.js 侧也有 isOpen 让位双保险）。

(function () {
  'use strict';

  // ===== 常量 =====
  const DOODLE_COLORS = ['#EE3F38', '#FAC515', '#16B364', '#387BFF', '#0B0B0F', '#787891', '#FFFFFF'];
  const DOODLE_RATIO_KEYS = ['original', '16:9', '4:3', '1:1', '3:4', '9:16'];
  const DOODLE_RATIO_VALUES = { '16:9': [16, 9], '4:3': [4, 3], '1:1': [1, 1], '3:4': [3, 4], '9:16': [9, 16] };
  const DEFAULT_COLOR = DOODLE_COLORS[0];
  const DEFAULT_LINE_WIDTH = 6;
  const MIN_LINE_WIDTH = 1;
  const MAX_LINE_WIDTH = 40;
  const MIN_OPACITY_PERCENT = 10;
  const DEFAULT_OPACITY_PERCENT = 100;
  const MAX_OPACITY_PERCENT = 100;
  const MIN_TEXT_FONT_CSS = 14;
  const MAX_TEXT_FONT_CSS = 96;
  const MAX_UNDO = 50;
  const IMAGE_ID = '__image__';
  const FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';
  const HANDLE_CSS = 8;        // 控制点边长（css px）
  const HANDLE_HIT_CSS = 12;   // 控制点命中半径（css px）
  const HIT_TOL_CSS = 6;       // 元素命中容差（css px）
  const MIN_RECT_CSS = 3;      // 矩形最小显示尺寸，小于视为误触
  const UPLOAD_ACCEPT = '.jpg,.jpeg,.png,.webp,.bmp,.tiff,.tif,.gif,.heic,.heif,image/*';

  function tr(key, fallback) {
    if (typeof window !== 'undefined' && typeof window.t === 'function') {
      const v = window.t(key);
      if (v && v !== key) return v;
    }
    return fallback;
  }

  function clamp(v, min, max) {
    return Math.min(max, Math.max(min, v));
  }

  // =====================================================================
  // 纯函数区（不依赖 DOM/运行态，供 Vitest 直接测试）
  // =====================================================================

  /**
   * 输出画布尺寸（自然像素）：original = 底图原尺寸；固定比例以原图最长边为基准扩展（底图 contain 不裁剪）。
   */
  function computeOutSize(naturalW, naturalH, ratio) {
    if (!ratio || ratio === 'original' || !DOODLE_RATIO_VALUES[ratio]) {
      return { w: Math.max(1, naturalW), h: Math.max(1, naturalH) };
    }
    const rw = DOODLE_RATIO_VALUES[ratio][0];
    const rh = DOODLE_RATIO_VALUES[ratio][1];
    const long = Math.max(naturalW, naturalH);
    if (rw >= rh) {
      return { w: long, h: Math.max(1, Math.round((long * rh) / rw)) };
    }
    return { w: Math.max(1, Math.round((long * rw) / rh)), h: long };
  }

  /** 矩形 w×h 在盒子 boxW×boxH 内 contain 居中。 */
  function containFit(boxW, boxH, w, h) {
    const scale = Math.min(boxW / w, boxH / h);
    return { scale, x: (boxW - w * scale) / 2, y: (boxH - h * scale) / 2 };
  }

  function pointToSegmentDistance(px, py, ax, ay, bx, by) {
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    let t = len2 === 0 ? 0 : ((px - ax) * dx + (py - ay) * dy) / len2;
    t = clamp(t, 0, 1);
    const cx = ax + t * dx;
    const cy = ay + t * dy;
    return Math.sqrt((px - cx) * (px - cx) + (py - cy) * (py - cy));
  }

  /** 文字近似测量（无需 canvas ctx；中文按全宽、西文按 0.56 宽估算，选中框/命中共用保持一致）。 */
  function measureApproxText(text, fontSize) {
    const lines = String(text).split('\n');
    let w = 0;
    for (const line of lines) {
      let lw = 0;
      for (const ch of line) lw += ch.charCodeAt(0) > 255 ? fontSize : fontSize * 0.56;
      w = Math.max(w, lw);
    }
    return { w: Math.max(fontSize * 0.56, w), h: lines.length * fontSize * 1.25, lines: lines.length };
  }

  /** 元素包围盒（图片自然像素系）；rect 含线宽外扩；eraser 擦除轨迹不参与选中。 */
  function elementBBox(el) {
    if (!el || el.type === 'eraser') return null;
    if (el.type === 'stroke') {
      if (!el.points || el.points.length === 0) return null;
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const p of el.points) {
        if (p.x < minX) minX = p.x;
        if (p.y < minY) minY = p.y;
        if (p.x > maxX) maxX = p.x;
        if (p.y > maxY) maxY = p.y;
      }
      const pad = (el.width || 1) / 2;
      return { x: minX - pad, y: minY - pad, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2 };
    }
    if (el.type === 'rect') {
      const pad = (el.width || 1) / 2;
      return { x: el.x - pad, y: el.y - pad, w: el.w + pad * 2, h: el.h + pad * 2 };
    }
    if (el.type === 'text') {
      const m = measureApproxText(el.text, el.fontSize);
      return { x: el.x, y: el.y, w: m.w, h: m.h };
    }
    return null;
  }

  /** 元素命中检测（坐标与 tol 均为图片自然像素）；eraser 擦除轨迹不参与命中。 */
  function hitTestElement(el, x, y, tol) {
    if (!el || el.type === 'eraser') return false;
    if (el.type === 'stroke') {
      const r = (el.width || 1) / 2 + tol;
      const pts = el.points || [];
      if (pts.length === 1) {
        const p = pts[0];
        return Math.sqrt((x - p.x) * (x - p.x) + (y - p.y) * (y - p.y)) <= r;
      }
      for (let i = 1; i < pts.length; i++) {
        if (pointToSegmentDistance(x, y, pts[i - 1].x, pts[i - 1].y, pts[i].x, pts[i].y) <= r) return true;
      }
      return false;
    }
    if (el.type === 'rect') {
      const r = (el.width || 1) / 2 + tol;
      const corners = [
        [el.x, el.y], [el.x + el.w, el.y],
        [el.x + el.w, el.y + el.h], [el.x, el.y + el.h],
      ];
      for (let i = 0; i < 4; i++) {
        const a = corners[i];
        const b = corners[(i + 1) % 4];
        if (pointToSegmentDistance(x, y, a[0], a[1], b[0], b[1]) <= r) return true;
      }
      return false;
    }
    if (el.type === 'text') {
      const b = elementBBox(el);
      if (!b) return false;
      return x >= b.x - tol && x <= b.x + b.w + tol && y >= b.y - tol && y <= b.y + b.h + tol;
    }
    return false;
  }

  /** bbox 的 8 控制点，顺序：0 nw, 1 n, 2 ne, 3 e, 4 se, 5 s, 6 sw, 7 w。 */
  function handlePointsForBbox(b) {
    const cx = b.x + b.w / 2;
    const cy = b.y + b.h / 2;
    return [
      { x: b.x, y: b.y }, { x: cx, y: b.y }, { x: b.x + b.w, y: b.y }, { x: b.x + b.w, y: cy },
      { x: b.x + b.w, y: b.y + b.h }, { x: cx, y: b.y + b.h }, { x: b.x, y: b.y + b.h }, { x: b.x, y: cy },
    ];
  }

  function hitHandleIndex(handlePts, px, py, tol) {
    for (let i = 0; i < handlePts.length; i++) {
      const p = handlePts[i];
      if (Math.abs(px - p.x) <= tol && Math.abs(py - p.y) <= tol) return i;
    }
    return -1;
  }

  /** 任意顺序拖出的矩形归一化为正 w/h。 */
  function normalizeRect(x1, y1, x2, y2) {
    return {
      x: Math.min(x1, x2),
      y: Math.min(y1, y2),
      w: Math.abs(x2 - x1),
      h: Math.abs(y2 - y1),
    };
  }

  /** 等比缩放因子：指针当前/起始到锚点的距离比，防 0 与极端值。 */
  function distFactor(anchor, start, cur) {
    const d0 = Math.max(1e-6, Math.hypot(start.x - anchor.x, start.y - anchor.y));
    const d1 = Math.hypot(cur.x - anchor.x, cur.y - anchor.y);
    return clamp(d1 / d0, 0.02, 60);
  }

  /**
   * 拖 handle 得到新 bbox（不翻转，minSize 兜底），供矩形 8 向缩放。
   */
  function dragBbox(b, handle, cur, minSize) {
    let x = b.x, y = b.y, w = b.w, h = b.h;
    const right = b.x + b.w;
    const bottom = b.y + b.h;
    switch (handle) {
      case 0: w = right - cur.x; h = bottom - cur.y; x = cur.x; y = cur.y; break; // nw
      case 1: h = bottom - cur.y; y = cur.y; break;                              // n
      case 2: w = cur.x - x; h = bottom - cur.y; y = cur.y; break;               // ne
      case 3: w = cur.x - x; break;                                              // e
      case 4: w = cur.x - x; h = cur.y - y; break;                               // se
      case 5: h = cur.y - y; break;                                              // s
      case 6: w = right - cur.x; h = cur.y - y; x = cur.x; break;                // sw
      case 7: w = right - cur.x; x = cur.x; break;                               // w
    }
    return { x, y, w: Math.max(minSize, w), h: Math.max(minSize, h) };
  }

  function cloneEl(el) {
    return JSON.parse(JSON.stringify(el));
  }

  function sameSnap(a, b) {
    try {
      return JSON.stringify(a) === JSON.stringify(b);
    } catch (_) {
      return false;
    }
  }

  /**
   * 命令栈应用（纯函数）：按 record 与方向返回新的 elements 数组。
   * record 形态：
   *  - {action:'add', element}
   *  - {action:'update', id, before, after}          // 底图更新由调用方处理（id === IMAGE_ID）
   *  - {action:'delete', items:[{index, element}]}
   *  - {action:'clear', items:[element...]}
   */
  function applyRecord(record, elements, useBefore) {
    if (!record) return elements;
    switch (record.action) {
      case 'add':
        if (useBefore) return elements.filter((el) => el.id !== record.element.id);
        return elements.concat([record.element]);
      case 'update':
        return elements.map((el) => (el.id === record.id ? cloneEl(useBefore ? record.before : record.after) : el));
      case 'delete': {
        if (useBefore) {
          const arr = elements.slice();
          record.items
            .slice()
            .sort((a, b) => a.index - b.index)
            .forEach((it) => arr.splice(Math.min(it.index, arr.length), 0, it.element));
          return arr;
        }
        const ids = new Set(record.items.map((it) => it.element.id));
        return elements.filter((el) => !ids.has(el.id));
      }
      case 'clear':
        return useBefore ? record.items.slice() : [];
      default:
        return elements;
    }
  }

  // =====================================================================
  // 运行态
  // =====================================================================
  const S = {
    modal: null,
    bodyEl: null,
    canvas: null,
    ctx: null,
    cursorEl: null,
    confirmBtn: null,
    open: false,
    busy: false,
    bound: false,
    tool: 'select',
    color: DEFAULT_COLOR,
    lineWidth: DEFAULT_LINE_WIDTH,
    opacity: DEFAULT_OPACITY_PERCENT / 100,
    ratio: 'original',
    out: { w: 1, h: 1 },
    cssScale: 1,   // css px / 输出画布自然 px
    dpr: 1,
    image: null,   // { img, naturalW, naturalH, x, y, scale }（x/y/scale 为输出画布自然像素系）
    elements: [],
    nextId: 1,
    selectedId: null,  // number | IMAGE_ID | null
    undoStack: [],
    redoStack: [],
    drag: null,        // 进行中的交互（pen/eraser/rect/move/scale-*）
    textEditor: null,  // { ta, anchor, fontSizeImg, fontSizeCss, color, committed }
    context: null,
    onComplete: null,
    objectUrl: null,
    onResize: null,
  };
  let rafId = 0;

  // =====================================================================
  // DOM 注入与一次性绑定
  // =====================================================================
  function svgIcon(name) {
    const paths = {
      select: '<path d="M5 3l6 16 2.4-6.6L20 10z"/>',
      pen: '<path d="M17 3l4 4L8 20l-5 1 1-5z"/><path d="M14.5 5.5l4 4"/>',
      eraser: '<path d="M8.5 20.5l-5-5a1.5 1.5 0 010-2.1l8.9-8.9a1.5 1.5 0 012.1 0l5 5a1.5 1.5 0 010 2.1l-8.9 8.9z"/><path d="M21 20.5H9"/><path d="M6 11.5l6.5 6.5"/>',
      text: '<path d="M5 6V4h14v2"/><path d="M12 4v16"/><path d="M9 20h6"/>',
      rect: '<rect x="4" y="6" width="16" height="12" rx="1"/>',
      undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 010 11H11"/>',
      redo: '<path d="M15 14l5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 000 11H13"/>',
      clear: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/><path d="M10 10v6M14 10v6"/>',
      upload: '<path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M4 20h16"/>',
    };
    return (
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (paths[name] || '') + '</svg>'
    );
  }

  function buildModalHtml() {
    const toolBtn = (tool, icon, labelKey, label) =>
      '<button class="doodle-tool-btn" type="button" data-tool="' + tool + '" title="' + tr(labelKey, label) + '" aria-label="' + tr(labelKey, label) + '">' + svgIcon(icon) + '</button>';
    return (
      '<div class="doodle-editor-modal" id="doodleEditorModal" aria-hidden="true">' +
        '<div class="doodle-modal-card" role="dialog" aria-modal="true" tabindex="-1">' +
          '<div class="doodle-modal-header">' +
            '<div class="doodle-modal-title">' + tr('doodle_modal_title', '涂鸦编辑') + '</div>' +
            '<button class="doodle-modal-close" id="doodleCloseBtn" type="button" aria-label="' + tr('close', '关闭') + '">×</button>' +
          '</div>' +
          '<div class="doodle-body" id="doodleBody">' +
            '<canvas id="doodleCanvas" class="doodle-canvas"></canvas>' +
            '<div class="doodle-cursor" id="doodleCursor"></div>' +
            '<div class="doodle-body-loading" id="doodleLoading" style="display:none;">' + tr('doodle_loading', '图片加载中…') + '</div>' +
            '<div class="doodle-ratio-wrap">' +
              '<button class="doodle-ratio-btn" id="doodleRatioBtn" type="button">' + tr('doodle_ratio_original', '原始比例') + ' ▾</button>' +
              '<div class="doodle-ratio-menu" id="doodleRatioMenu"></div>' +
            '</div>' +
          '</div>' +
          '<div class="doodle-modal-footer" id="doodleFooter">' +
            '<div class="doodle-toolbar" id="doodleToolbar">' +
              toolBtn('select', 'select', 'doodle_tool_select', '选择') +
              toolBtn('pen', 'pen', 'doodle_tool_pen', '画笔') +
              toolBtn('eraser', 'eraser', 'doodle_tool_eraser', '橡皮擦') +
              toolBtn('text', 'text', 'doodle_tool_text', '文字') +
              toolBtn('rect', 'rect', 'doodle_tool_rect', '矩形') +
              '<button class="doodle-tool-btn doodle-color-btn" id="doodleColorBtn" type="button" title="' + tr('doodle_tool_color', '颜色') + '"><span class="doodle-color-swatch" id="doodleColorSwatch"></span></button>' +
              '<div class="doodle-tool-sep"></div>' +
              '<button class="doodle-tool-btn" id="doodleUndoBtn" type="button" title="' + tr('doodle_undo', '撤销') + ' (Ctrl+Z)">' + svgIcon('undo') + '</button>' +
              '<button class="doodle-tool-btn" id="doodleRedoBtn" type="button" title="' + tr('doodle_redo', '重做') + ' (Ctrl+Shift+Z)">' + svgIcon('redo') + '</button>' +
              '<button class="doodle-tool-btn" id="doodleClearBtn" type="button" title="' + tr('doodle_clear', '清空') + '">' + svgIcon('clear') + '</button>' +
              '<div class="doodle-tool-sep"></div>' +
              '<button class="doodle-tool-btn" id="doodleUploadBtn" type="button" title="' + tr('doodle_upload', '上传替换底图') + '">' + svgIcon('upload') + '</button>' +
            '</div>' +
            '<button class="doodle-confirm-btn" id="doodleConfirmBtn" type="button">' + tr('doodle_confirm', '确认') + '</button>' +
            '<div class="doodle-panel doodle-size-panel" id="doodleSizePanel">' +
              '<div class="doodle-panel-row">' +
                '<input type="range" id="doodleSizeRange" min="' + MIN_LINE_WIDTH + '" max="' + MAX_LINE_WIDTH + '" step="1" value="' + DEFAULT_LINE_WIDTH + '" aria-label="' + tr('doodle_size', '粗细') + '" />' +
                '<span class="doodle-size-value"><span id="doodleSizeValue">' + DEFAULT_LINE_WIDTH + '</span>px</span>' +
              '</div>' +
              '<div class="doodle-panel-row">' +
                '<input type="range" id="doodleOpacityRange" min="' + MIN_OPACITY_PERCENT + '" max="' + MAX_OPACITY_PERCENT + '" step="5" value="' + DEFAULT_OPACITY_PERCENT + '" aria-label="' + tr('doodle_opacity', '透明度') + '" />' +
                '<span class="doodle-size-value"><span id="doodleOpacityValue">' + DEFAULT_OPACITY_PERCENT + '</span>%</span>' +
              '</div>' +
            '</div>' +
            '<div class="doodle-panel doodle-color-panel" id="doodleColorPanel"></div>' +
          '</div>' +
          '<input type="file" class="doodle-upload-input" id="doodleUploadInput" accept="' + UPLOAD_ACCEPT + '" />' +
        '</div>' +
      '</div>'
    );
  }

  function ensureModalDom() {
    if (S.modal) return S.modal;
    let modal = document.getElementById('doodleEditorModal');
    if (!modal) {
      const host = document.createElement('div');
      host.innerHTML = buildModalHtml();
      modal = host.firstElementChild;
      document.body.appendChild(modal);
    }
    S.modal = modal;
    S.bodyEl = document.getElementById('doodleBody');
    S.canvas = document.getElementById('doodleCanvas');
    S.ctx = S.canvas ? S.canvas.getContext('2d') : null;
    S.cursorEl = document.getElementById('doodleCursor');
    S.confirmBtn = document.getElementById('doodleConfirmBtn');
    buildColorPanel();
    buildRatioMenu();
    bindEvents();
    return modal;
  }

  function buildColorPanel() {
    const panel = document.getElementById('doodleColorPanel');
    if (!panel) return;
    panel.innerHTML = '';
    DOODLE_COLORS.forEach((c) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'doodle-swatch';
      btn.dataset.color = c;
      btn.style.background = c;
      btn.setAttribute('aria-label', c);
      btn.addEventListener('click', () => {
        S.color = c;
        updateColorUI();
        closePanels();
      });
      panel.appendChild(btn);
    });
  }

  function buildRatioMenu() {
    const menu = document.getElementById('doodleRatioMenu');
    if (!menu) return;
    menu.innerHTML = '';
    DOODLE_RATIO_KEYS.forEach((key) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'doodle-ratio-item';
      item.dataset.ratio = key;
      item.textContent = ratioLabel(key);
      item.addEventListener('click', () => setRatio(key));
      menu.appendChild(item);
    });
  }

  function ratioLabel(key) {
    if (key === 'original') return tr('doodle_ratio_original', '原始比例');
    return key;
  }

  function bindEvents() {
    if (S.bound) return;
    S.bound = true;

    S.canvas.addEventListener('pointerdown', onPointerDown);
    S.canvas.addEventListener('pointermove', onPointerMove);
    S.canvas.addEventListener('pointerup', onPointerUp);
    S.canvas.addEventListener('pointercancel', onPointerUp);
    S.canvas.addEventListener('mouseleave', () => {
      if (S.cursorEl) S.cursorEl.style.display = 'none';
    });
    S.canvas.addEventListener('mouseenter', () => {
      if (S.cursorEl && (S.tool === 'eraser' || S.tool === 'pen')) S.cursorEl.style.display = 'block';
    });

    document.getElementById('doodleCloseBtn').addEventListener('click', requestClose);
    S.confirmBtn.addEventListener('click', confirmEdit);

    document.getElementById('doodleUndoBtn').addEventListener('click', undo);
    document.getElementById('doodleRedoBtn').addEventListener('click', redo);
    document.getElementById('doodleClearBtn').addEventListener('click', clearAll);
    document.getElementById('doodleUploadBtn').addEventListener('click', () => {
      closePanels();
      document.getElementById('doodleUploadInput').click();
    });
    document.getElementById('doodleUploadInput').addEventListener('change', onUploadInputChange);

    document.getElementById('doodleColorBtn').addEventListener('click', (e) => {
      e.stopPropagation();
      const panel = document.getElementById('doodleColorPanel');
      const opening = !panel.classList.contains('show');
      closePanels();
      if (opening) {
        positionPanel(panel, e.currentTarget);
        panel.classList.add('show');
      }
    });

    document.querySelectorAll('#doodleToolbar [data-tool]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        setTool(btn.dataset.tool, e.currentTarget);
      });
    });

    const range = document.getElementById('doodleSizeRange');
    range.addEventListener('input', () => {
      S.lineWidth = clamp(parseInt(range.value, 10) || DEFAULT_LINE_WIDTH, MIN_LINE_WIDTH, MAX_LINE_WIDTH);
      range.value = String(S.lineWidth);
      document.getElementById('doodleSizeValue').textContent = String(S.lineWidth);
      updateCursorSize();
    });

    const opacityRange = document.getElementById('doodleOpacityRange');
    opacityRange.addEventListener('input', () => {
      S.opacity = clamp(parseInt(opacityRange.value, 10) || DEFAULT_OPACITY_PERCENT, MIN_OPACITY_PERCENT, MAX_OPACITY_PERCENT) / 100;
      opacityRange.value = String(Math.round(S.opacity * 100));
      document.getElementById('doodleOpacityValue').textContent = String(Math.round(S.opacity * 100));
    });

    document.getElementById('doodleRatioBtn').addEventListener('click', (e) => {
      e.stopPropagation();
      const menu = document.getElementById('doodleRatioMenu');
      menu.classList.toggle('show');
    });

    // 弹窗内快捷键：stopPropagation 阻断冒泡到 window 的工作流级快捷键
    S.modal.addEventListener('keydown', onModalKeydown);
  }

  function onModalKeydown(e) {
    if (!S.open) return;
    const inField = e.target && (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT');
    const isCtrl = e.ctrlKey || e.metaKey;
    if (isCtrl && !inField && e.key.toLowerCase() === 'z') {
      e.preventDefault();
      e.stopPropagation();
      if (e.shiftKey) redo();
      else undo();
      return;
    }
    if (isCtrl && !inField && e.key.toLowerCase() === 'y') {
      e.preventDefault();
      e.stopPropagation();
      redo();
      return;
    }
    if (!inField && (e.key === 'Delete' || e.key === 'Backspace')) {
      // 弹窗打开期间一律拦截，防止误删工作流节点
      e.preventDefault();
      e.stopPropagation();
      deleteSelected();
    }
  }

  // =====================================================================
  // 坐标换算（css px ↔ 输出画布自然像素 ↔ 图片自然像素）
  // =====================================================================
  function eventCss(e) {
    const r = S.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  function cssToImgPt(p) {
    const ox = p.x / S.cssScale - S.image.x;
    const oy = p.y / S.cssScale - S.image.y;
    return { x: ox / S.image.scale, y: oy / S.image.scale };
  }

  function imgToCssPt(p) {
    return {
      x: (p.x * S.image.scale + S.image.x) * S.cssScale,
      y: (p.y * S.image.scale + S.image.y) * S.cssScale,
    };
  }

  function cssLenToImg(len) {
    return len / (S.cssScale * S.image.scale);
  }

  function imgLenToCss(len) {
    return len * S.image.scale * S.cssScale;
  }

  function imgBboxToCss(b) {
    return {
      x: (b.x * S.image.scale + S.image.x) * S.cssScale,
      y: (b.y * S.image.scale + S.image.y) * S.cssScale,
      w: b.w * S.image.scale * S.cssScale,
      h: b.h * S.image.scale * S.cssScale,
    };
  }

  // =====================================================================
  // 布局与渲染
  // =====================================================================
  function recalcOutSize() {
    S.out = computeOutSize(S.image.naturalW, S.image.naturalH, S.ratio);
  }

  function relayoutImage() {
    const fit = containFit(S.out.w, S.out.h, S.image.naturalW, S.image.naturalH);
    S.image.scale = fit.scale;
    S.image.x = fit.x;
    S.image.y = fit.y;
  }

  function layoutCanvas() {
    if (!S.bodyEl || !S.image) return;
    const availW = S.bodyEl.clientWidth - 48;
    const availH = S.bodyEl.clientHeight - 48;
    if (availW <= 10 || availH <= 10) return;
    const fit = Math.min(availW / S.out.w, availH / S.out.h);
    const cssW = Math.max(1, Math.floor(S.out.w * fit));
    const cssH = Math.max(1, Math.floor(S.out.h * fit));
    S.dpr = Math.max(1, (typeof window !== 'undefined' && window.devicePixelRatio) || 1);
    S.canvas.style.width = cssW + 'px';
    S.canvas.style.height = cssH + 'px';
    S.canvas.width = Math.max(1, Math.round(cssW * S.dpr));
    S.canvas.height = Math.max(1, Math.round(cssH * S.dpr));
    S.cssScale = cssW / S.out.w;
    if (S.textEditor) repositionTextEditor();
    requestRender();
  }

  function requestRender() {
    if (rafId) return;
    rafId = requestAnimationFrame(() => {
      rafId = 0;
      render();
    });
  }

  function render() {
    const ctx = S.ctx;
    if (!ctx || !S.image) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, S.canvas.width, S.canvas.height);
    // 切到输出画布自然像素系（canvas px = 自然 px × cssScale × dpr）
    const k = S.cssScale * S.dpr;
    ctx.setTransform(k, 0, 0, k, 0, 0);
    drawContent(ctx);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    drawOverlay(ctx);
  }

  /**
   * 元素层 + 底图 + 白底。调用前 ctx 已处于输出画布自然像素系、画布已清空。
   * 顺序：按序画元素（eraser 笔画 destination-out 擦掉已画涂鸦）→ destination-over 垫底图 → destination-over 垫白底。
   * 橡皮擦除区域露出底图；底图透明像素处露出白底；导出与屏幕渲染共用本函数。
   */
  function drawContent(ctx) {
    const img = S.image;
    ctx.save();
    ctx.translate(img.x, img.y);
    ctx.scale(img.scale, img.scale);
    const applyOpacity = (el) => {
      // eraser 为 destination-out 全擦，不受透明度影响
      ctx.globalAlpha = (el && el.type !== 'eraser' && el.opacity != null) ? clamp(el.opacity, 0.05, 1) : 1;
    };
    for (const el of S.elements) {
      applyOpacity(el);
      drawElement(ctx, el);
    }
    if (S.drag && S.drag.kind === 'pen') { applyOpacity(S.drag.stroke); drawElement(ctx, S.drag.stroke); }
    if (S.drag && S.drag.kind === 'eraser') drawElement(ctx, S.drag.stroke);
    if (S.drag && S.drag.kind === 'rect') { applyOpacity(S.drag.draft); drawElement(ctx, S.drag.draft); }
    ctx.globalAlpha = 1;
    ctx.restore();
    ctx.globalCompositeOperation = 'destination-over';
    ctx.drawImage(img.img, img.x, img.y, img.naturalW * img.scale, img.naturalH * img.scale);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, S.out.w, S.out.h);
    ctx.globalCompositeOperation = 'source-over';
  }

  /** 单个元素绘制（处于图片自然像素系）。合成导出与屏幕渲染共用，保证所见即所得。 */
  function drawElement(ctx, el) {
    if (!el) return;
    if (el.type === 'stroke') {
      const pts = el.points || [];
      if (pts.length === 1) {
        ctx.beginPath();
        ctx.arc(pts[0].x, pts[0].y, Math.max(0.5, (el.width || 1) / 2), 0, Math.PI * 2);
        ctx.fillStyle = el.color;
        ctx.fill();
        return;
      }
      ctx.strokeStyle = el.color;
      ctx.lineWidth = el.width || 1;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
      ctx.stroke();
      return;
    }
    if (el.type === 'eraser') {
      // 圆头局部擦除：destination-out 只擦掉已画内容（白底+下方涂鸦），
      // 底图由 drawContent 最后 destination-over 垫底，故擦除区域露出底图
      const pts = el.points || [];
      ctx.globalCompositeOperation = 'destination-out';
      if (pts.length === 1) {
        ctx.beginPath();
        ctx.arc(pts[0].x, pts[0].y, Math.max(0.5, (el.width || 1) / 2), 0, Math.PI * 2);
        ctx.fillStyle = '#000';
        ctx.fill();
      } else {
        ctx.strokeStyle = '#000';
        ctx.lineWidth = el.width || 1;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
        ctx.stroke();
      }
      ctx.globalCompositeOperation = 'source-over';
      return;
    }
    if (el.type === 'rect') {
      ctx.strokeStyle = el.color;
      ctx.lineWidth = el.width || 1;
      ctx.strokeRect(el.x, el.y, el.w, el.h);
      return;
    }
    if (el.type === 'text') {
      ctx.fillStyle = el.color;
      ctx.font = '600 ' + el.fontSize + 'px ' + FONT_FAMILY;
      ctx.textBaseline = 'top';
      const lines = String(el.text).split('\n');
      const lh = el.fontSize * 1.25;
      lines.forEach((line, i) => ctx.fillText(line, el.x, el.y + i * lh));
    }
  }

  function currentSelection() {
    if (S.selectedId === null || S.selectedId === undefined) return null;
    if (S.selectedId === IMAGE_ID) return { kind: 'image' };
    const el = S.elements.find((e) => e.id === S.selectedId);
    return el ? { kind: 'element', el } : null;
  }

  function selectionBboxImg(sel) {
    if (!sel) return null;
    if (sel.kind === 'image') return { x: 0, y: 0, w: S.image.naturalW, h: S.image.naturalH };
    return elementBBox(sel.el);
  }

  function drawOverlay(ctx) {
    const sel = currentSelection();
    if (!sel) return;
    const bboxImg = selectionBboxImg(sel);
    if (!bboxImg) return;
    let b = imgBboxToCss(bboxImg);
    // 过小的选中框也要保证控制点可见
    if (b.w < 16) { b.x -= (16 - b.w) / 2; b.w = 16; }
    if (b.h < 16) { b.y -= (16 - b.h) / 2; b.h = 16; }
    ctx.save();
    ctx.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    ctx.strokeStyle = '#387bff';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(b.x, b.y, b.w, b.h);
    const pts = handlePointsForBbox(b);
    for (const p of pts) {
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(p.x - HANDLE_CSS / 2, p.y - HANDLE_CSS / 2, HANDLE_CSS, HANDLE_CSS);
      ctx.strokeRect(p.x - HANDLE_CSS / 2, p.y - HANDLE_CSS / 2, HANDLE_CSS, HANDLE_CSS);
    }
    ctx.restore();
  }

  // =====================================================================
  // 指针交互
  // =====================================================================
  function onPointerDown(e) {
    if (!S.open || S.busy || !S.image) return;
    if (e.button !== undefined && e.button !== 0) return;
    if (S.textEditor) commitTextEditor();
    closePanels();
    try { S.canvas.setPointerCapture(e.pointerId); } catch (_) { /* 旧浏览器忽略 */ }
    const css = eventCss(e);
    const imgPt = cssToImgPt(css);

    switch (S.tool) {
      case 'pen': {
        const width = Math.max(0.5, cssLenToImg(S.lineWidth));
        S.drag = {
          kind: 'pen',
          stroke: { id: S.nextId++, type: 'stroke', points: [{ x: imgPt.x, y: imgPt.y }], color: S.color, width, opacity: S.opacity },
        };
        break;
      }
      case 'eraser': {
        // 圆形局部擦除：与画笔同构收集轨迹，渲染时 destination-out 擦除
        S.drag = {
          kind: 'eraser',
          stroke: {
            id: S.nextId++,
            type: 'eraser',
            points: [{ x: imgPt.x, y: imgPt.y }],
            color: '#000000',
            width: Math.max(0.5, cssLenToImg(S.lineWidth)),
          },
        };
        break;
      }
      case 'rect': {
        const width = Math.max(0.5, cssLenToImg(S.lineWidth));
        S.drag = {
          kind: 'rect',
          start: imgPt,
          draft: { id: S.nextId++, type: 'rect', x: imgPt.x, y: imgPt.y, w: 0, h: 0, color: S.color, width, opacity: S.opacity },
        };
        break;
      }
      case 'text':
        startTextEditor(css, imgPt);
        break;
      case 'select':
      default:
        handleSelectDown(css, imgPt);
    }
    requestRender();
  }

  function handleSelectDown(css, imgPt) {
    // 1) 已选中对象的控制点 → 进入缩放
    const sel = currentSelection();
    if (sel) {
      const bboxImg = selectionBboxImg(sel);
      if (bboxImg) {
        const ptsCss = handlePointsForBbox(imgBboxToCss(bboxImg));
        const hi = hitHandleIndex(ptsCss, css.x, css.y, HANDLE_HIT_CSS);
        if (hi >= 0) {
          beginScale(sel, hi, css, imgPt, bboxImg);
          return;
        }
      }
    }
    // 2) 涂鸦元素（顶层优先）；eraser 擦除轨迹不可选中
    const tolImg = Math.max(cssLenToImg(HIT_TOL_CSS), 1);
    for (let i = S.elements.length - 1; i >= 0; i--) {
      if (S.elements[i].type === 'eraser') continue;
      if (hitTestElement(S.elements[i], imgPt.x, imgPt.y, tolImg)) {
        S.selectedId = S.elements[i].id;
        S.drag = { kind: 'move', startImg: imgPt, snapshot: cloneEl(S.elements[i]), moved: false };
        return;
      }
    }
    // 3) 底图本身可选中移动
    if (imgPt.x >= 0 && imgPt.y >= 0 && imgPt.x <= S.image.naturalW && imgPt.y <= S.image.naturalH) {
      S.selectedId = IMAGE_ID;
      // startCss：css 偏移在拖动中保持稳定；若用图片系坐标会随 image.x/y 更新形成反馈回路导致抖动
      S.drag = { kind: 'move', startImg: imgPt, startCss: css, snapshot: snapImage(), isImage: true, moved: false };
      return;
    }
    // 4) 空白取消选中
    S.selectedId = null;
  }

  function beginScale(sel, handleIdx, css, imgPt, bboxImg) {
    const ptsImg = handlePointsForBbox(bboxImg);
    const anchor = ptsImg[(handleIdx + 4) % 8]; // 对角固定点（0↔4, 1↔5, 2↔6, 3↔7）
    if (sel.kind === 'image') {
      // 锚点在输出画布上的投影基于 snapshot 预计算并保持不变，缩放因子用 css 距离计算
      const snapshot = snapImage();
      S.drag = {
        kind: 'scale-image',
        startCss: css,
        anchor,
        anchorCss: {
          x: (snapshot.x + anchor.x * snapshot.scale) * S.cssScale,
          y: (snapshot.y + anchor.y * snapshot.scale) * S.cssScale,
        },
        snapshot,
      };
    } else if (sel.el.type === 'rect') {
      S.drag = { kind: 'scale-rect', handle: handleIdx, bbox0: bboxImg, snapshot: cloneEl(sel.el) };
    } else {
      // stroke / text 用对角锚点等比缩放
      S.drag = { kind: 'scale-eq', start: imgPt, anchor, snapshot: cloneEl(sel.el) };
    }
  }

  function onPointerMove(e) {
    if (!S.open || !S.image) return;
    const css = eventCss(e);
    updateCursorPos(css);
    if (!S.drag) return;
    const imgPt = cssToImgPt(css);
    const d = S.drag;

    switch (d.kind) {
      case 'pen': {
        const pts = d.stroke.points;
        const last = pts[pts.length - 1];
        const dx = imgPt.x - last.x;
        const dy = imgPt.y - last.y;
        // 采样阈值：css 系 > 1px，避免大图上堆点
        if (imgLenToCss(Math.hypot(dx, dy)) > 1) pts.push({ x: imgPt.x, y: imgPt.y });
        break;
      }
      case 'eraser': {
        const pts = d.stroke.points;
        const last = pts[pts.length - 1];
        if (imgLenToCss(Math.hypot(imgPt.x - last.x, imgPt.y - last.y)) > 1) pts.push({ x: imgPt.x, y: imgPt.y });
        break;
      }
      case 'rect': {
        const n = normalizeRect(d.start.x, d.start.y, imgPt.x, imgPt.y);
        d.draft.x = n.x; d.draft.y = n.y; d.draft.w = n.w; d.draft.h = n.h;
        break;
      }
      case 'move': {
        d.moved = true;
        const dx = imgPt.x - d.startImg.x;
        const dy = imgPt.y - d.startImg.y;
        if (d.isImage) {
          // css 偏移直译为输出画布偏移并绝对定位于 snapshot，不经过随底图变化的 cssToImgPt
          S.image.x = d.snapshot.x + (css.x - d.startCss.x) / S.cssScale;
          S.image.y = d.snapshot.y + (css.y - d.startCss.y) / S.cssScale;
        } else {
          S.elements = S.elements.map((el) => el.id === d.snapshot.id ? moveElement(d.snapshot, dx, dy) : el);
        }
        break;
      }
      case 'scale-image': {
        // 因子基于纯 css 距离（锚点投影固定），与底图当前状态无关，避免缩放抖动
        const f = distFactor(d.anchorCss, d.startCss, css);
        applyImageScale(d.snapshot, d.anchor, clamp(d.snapshot.scale * f, 0.02, 60));
        break;
      }
      case 'scale-rect': {
        const nb = dragBbox(d.bbox0, d.handle, imgPt, Math.max(4, cssLenToImg(2)));
        const lw = d.snapshot.width || 1;
        const next = Object.assign({}, d.snapshot, {
          x: nb.x + lw / 2,
          y: nb.y + lw / 2,
          w: Math.max(1, nb.w - lw),
          h: Math.max(1, nb.h - lw),
        });
        S.elements = S.elements.map((el) => (el.id === next.id ? next : el));
        break;
      }
      case 'scale-eq': {
        const f = distFactor(d.anchor, d.start, imgPt);
        let next = null;
        if (d.snapshot.type === 'stroke') {
          next = Object.assign({}, d.snapshot, {
            width: Math.max(0.5, d.snapshot.width * f),
            points: d.snapshot.points.map((p) => ({
              x: d.anchor.x + (p.x - d.anchor.x) * f,
              y: d.anchor.y + (p.y - d.anchor.y) * f,
            })),
          });
        } else if (d.snapshot.type === 'text') {
          next = Object.assign({}, d.snapshot, {
            fontSize: Math.max(2, d.snapshot.fontSize * f),
            x: d.anchor.x + (d.snapshot.x - d.anchor.x) * f,
            y: d.anchor.y + (d.snapshot.y - d.anchor.y) * f,
          });
        }
        if (next) S.elements = S.elements.map((el) => (el.id === next.id ? next : el));
        break;
      }
    }
    requestRender();
  }

  function onPointerUp(e) {
    const d = S.drag;
    if (!d) return;
    S.drag = null;
    try { S.canvas.releasePointerCapture(e.pointerId); } catch (_) { /* 忽略 */ }

    switch (d.kind) {
      case 'pen': {
        S.elements.push(d.stroke);
        pushRecord({ action: 'add', element: d.stroke });
        break;
      }
      case 'rect': {
        const draft = d.draft;
        const visible = Math.max(imgLenToCss(draft.w), imgLenToCss(draft.h));
        if (visible >= MIN_RECT_CSS) {
          S.elements.push(draft);
          pushRecord({ action: 'add', element: draft });
        }
        break;
      }
      case 'eraser': {
        // 擦除轨迹作为一个 eraser 元素入栈，撤销即恢复被擦内容
        S.elements.push(d.stroke);
        pushRecord({ action: 'add', element: d.stroke });
        break;
      }
      case 'move': {
        if (!d.moved) break;
        if (d.isImage) {
          const after = snapImage();
          if (!sameSnap(d.snapshot, after)) pushRecord({ action: 'update', id: IMAGE_ID, before: d.snapshot, after });
        } else {
          const cur = S.elements.find((el) => el.id === d.snapshot.id);
          if (cur) {
            const after = cloneEl(cur);
            if (!sameSnap(d.snapshot, after)) pushRecord({ action: 'update', id: d.snapshot.id, before: d.snapshot, after });
          }
        }
        break;
      }
      case 'scale-image': {
        const after = snapImage();
        if (!sameSnap(d.snapshot, after)) pushRecord({ action: 'update', id: IMAGE_ID, before: d.snapshot, after });
        break;
      }
      case 'scale-rect':
      case 'scale-eq': {
        const cur = S.elements.find((el) => el.id === d.snapshot.id);
        if (cur) {
          const after = cloneEl(cur);
          if (!sameSnap(d.snapshot, after)) pushRecord({ action: 'update', id: d.snapshot.id, before: d.snapshot, after });
        }
        break;
      }
    }
    // 删除后选中失效
    if (S.selectedId !== IMAGE_ID && S.selectedId !== null && !S.elements.some((el) => el.id === S.selectedId)) {
      S.selectedId = null;
    }
    updateToolbarUI();
    requestRender();
  }

  function moveElement(snapshot, dx, dy) {
    if (snapshot.type === 'stroke') {
      return Object.assign({}, snapshot, {
        points: snapshot.points.map((p) => ({ x: p.x + dx, y: p.y + dy })),
      });
    }
    return Object.assign({}, snapshot, { x: snapshot.x + dx, y: snapshot.y + dy });
  }

  function snapImage() {
    return { x: S.image.x, y: S.image.y, scale: S.image.scale };
  }

  function snapImageFull() {
    return {
      img: S.image.img,
      naturalW: S.image.naturalW,
      naturalH: S.image.naturalH,
      x: S.image.x,
      y: S.image.y,
      scale: S.image.scale,
    };
  }

  /** 以图片自然像素系 anchor 为锚点缩放底图（anchor 在输出画布上的投影保持不动）。 */
  function applyImageScale(snapshot, anchorImg, newScale) {
    const anchorOutX = snapshot.x + anchorImg.x * snapshot.scale;
    const anchorOutY = snapshot.y + anchorImg.y * snapshot.scale;
    S.image.scale = newScale;
    S.image.x = anchorOutX - anchorImg.x * newScale;
    S.image.y = anchorOutY - anchorImg.y * newScale;
  }

  // =====================================================================
  // 文字工具（DOM textarea 覆盖输入）
  // =====================================================================
  function startTextEditor(cssPt, imgPt) {
    removeTextEditor();
    const fontSizeCss = clamp(S.lineWidth * 4, MIN_TEXT_FONT_CSS, MAX_TEXT_FONT_CSS);
    const ta = document.createElement('textarea');
    ta.className = 'doodle-text-input';
    ta.rows = 1;
    ta.wrap = 'off';
    ta.spellcheck = false;
    ta.placeholder = tr('doodle_text_placeholder', '输入文字');
    S.bodyEl.appendChild(ta);
    S.textEditor = {
      ta,
      anchor: { x: imgPt.x, y: imgPt.y },
      fontSizeImg: cssLenToImg(fontSizeCss),
      fontSizeCss,
      color: S.color,
      committed: false,
    };
    ta.style.color = S.color;
    ta.style.fontSize = fontSizeCss + 'px';
    repositionTextEditor();
    ta.addEventListener('keydown', onTextKeydown);
    ta.addEventListener('input', autosizeTextarea);
    ta.addEventListener('blur', onTextBlur);
    setTimeout(() => {
      ta.focus();
      autosizeTextarea();
    }, 0);
  }

  function repositionTextEditor() {
    const ed = S.textEditor;
    if (!ed) return;
    const p = imgToCssPt(ed.anchor);
    ed.ta.style.left = Math.round(S.canvas.offsetLeft + p.x) + 'px';
    ed.ta.style.top = Math.round(S.canvas.offsetTop + p.y - 2) + 'px';
    ed.ta.style.fontSize = ed.fontSizeCss + 'px';
  }

  function onTextKeydown(e) {
    e.stopPropagation();
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      commitTextEditor();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelTextEditor();
    }
  }

  function onTextBlur() {
    // 点击别处（画布/工具栏）即完成输入
    commitTextEditor();
  }

  function autosizeTextarea() {
    const ed = S.textEditor;
    if (!ed) return;
    ed.ta.style.width = 'auto';
    ed.ta.style.height = 'auto';
    ed.ta.style.width = Math.max(24, ed.ta.scrollWidth + 4) + 'px';
    ed.ta.style.height = Math.max(Math.ceil(ed.fontSizeCss * 1.4), ed.ta.scrollHeight + 2) + 'px';
  }

  function commitTextEditor() {
    const ed = S.textEditor;
    if (!ed || ed.committed) return;
    ed.committed = true;
    const text = ed.ta.value.replace(/\s+$/, '');
    removeTextEditor();
    if (text) {
      const el = {
        id: S.nextId++,
        type: 'text',
        x: ed.anchor.x,
        y: ed.anchor.y,
        text,
        color: ed.color,
        fontSize: ed.fontSizeImg,
        opacity: S.opacity,
      };
      S.elements.push(el);
      pushRecord({ action: 'add', element: el });
      requestRender();
    }
  }

  function cancelTextEditor() {
    if (!S.textEditor) return;
    S.textEditor.committed = true;
    removeTextEditor();
  }

  function removeTextEditor() {
    if (!S.textEditor) return;
    const ta = S.textEditor.ta;
    ta.removeEventListener('keydown', onTextKeydown);
    ta.removeEventListener('input', autosizeTextarea);
    ta.removeEventListener('blur', onTextBlur);
    if (ta.parentNode) ta.parentNode.removeChild(ta);
    S.textEditor = null;
  }

  // =====================================================================
  // 命令栈（撤销/重做/清空/删除）
  // =====================================================================
  function pushRecord(record) {
    S.undoStack.push(record);
    if (S.undoStack.length > MAX_UNDO) S.undoStack.shift();
    S.redoStack = [];
    updateToolbarUI();
  }

  function applyRecordToState(record, useBefore) {
    if (record.action === 'replaceImage') {
      const snap = useBefore ? record.before : record.after;
      S.image = Object.assign({}, snap.image);
      S.elements = snap.elements.slice();
      recalcOutSize();
      layoutCanvas();
      return;
    }
    if (record.action === 'update' && record.id === IMAGE_ID) {
      Object.assign(S.image, useBefore ? record.before : record.after);
      return;
    }
    S.elements = applyRecord(record, S.elements, useBefore);
  }

  function undo() {
    if (S.busy) return;
    if (S.textEditor) commitTextEditor();
    const rec = S.undoStack.pop();
    if (!rec) return;
    applyRecordToState(rec, true);
    S.redoStack.push(rec);
    afterHistoryChange();
  }

  function redo() {
    if (S.busy) return;
    if (S.textEditor) commitTextEditor();
    const rec = S.redoStack.pop();
    if (!rec) return;
    applyRecordToState(rec, false);
    S.undoStack.push(rec);
    afterHistoryChange();
  }

  function afterHistoryChange() {
    if (S.selectedId !== IMAGE_ID && S.selectedId !== null && !S.elements.some((el) => el.id === S.selectedId)) {
      S.selectedId = null;
    }
    updateToolbarUI();
    requestRender();
  }

  async function clearAll() {
    if (S.busy || S.elements.length === 0) return;
    const ok = await confirmDialog(
      tr('doodle_clear_confirm', '清空画板内容？清空后可以通过撤销恢复。'),
      { title: tr('doodle_clear_title', '清空画板'), confirmText: tr('doodle_clear_btn', '清空') }
    );
    if (!ok) return;
    const items = S.elements.slice();
    S.elements = [];
    S.selectedId = null;
    pushRecord({ action: 'clear', items });
    requestRender();
  }

  function deleteSelected() {
    if (S.busy || S.selectedId === null || S.selectedId === IMAGE_ID) return;
    const idx = S.elements.findIndex((el) => el.id === S.selectedId);
    if (idx < 0) return;
    const el = S.elements[idx];
    S.elements.splice(idx, 1);
    pushRecord({ action: 'delete', items: [{ index: idx, element: el }] });
    S.selectedId = null;
    requestRender();
  }

  // =====================================================================
  // 工具 / 面板 / 比例
  // =====================================================================
  function setTool(tool, btnEl) {
    if (!['select', 'pen', 'eraser', 'text', 'rect'].includes(tool)) return;
    if (S.tool === tool) {
      // 再次点击：画笔/橡皮切换粗细面板显隐（火山行为）
      if (tool === 'pen' || tool === 'eraser') toggleSizePanel(btnEl);
      else closePanels();
      return;
    }
    if (S.textEditor) commitTextEditor();
    S.tool = tool;
    if (tool !== 'select') S.selectedId = null;
    applyToolButtons();
    updateCursor();
    if (tool === 'pen' || tool === 'eraser') showSizePanel(btnEl);
    else closePanels();
  }

  function applyToolButtons() {
    S.modal.querySelectorAll('#doodleToolbar [data-tool]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.tool === S.tool);
    });
  }

  function updateCursor() {
    if (!S.canvas) return;
    // 画笔/橡皮隐藏系统光标，显示跟随鼠标的圆形轮廓（直径=粗细面板值）
    const map = { select: 'default', pen: 'none', eraser: 'none', rect: 'crosshair', text: 'text' };
    S.canvas.style.cursor = map[S.tool] || 'default';
    updateCursorSize();
  }

  /** 画笔/橡皮的圆形光标：直径跟随粗细面板，橡皮预示擦除范围、画笔预示笔画粗细。 */
  function updateCursorSize() {
    if (!S.cursorEl) return;
    const show = S.tool === 'eraser' || S.tool === 'pen';
    S.cursorEl.style.display = show ? 'block' : 'none';
    if (show) {
      const d = Math.max(S.lineWidth, 4);
      S.cursorEl.style.width = d + 'px';
      S.cursorEl.style.height = d + 'px';
    }
  }

  function updateCursorPos(css) {
    if (!S.cursorEl || !S.canvas) return;
    if (S.tool !== 'eraser' && S.tool !== 'pen') return;
    S.cursorEl.style.left = Math.round(S.canvas.offsetLeft + css.x) + 'px';
    S.cursorEl.style.top = Math.round(S.canvas.offsetTop + css.y) + 'px';
  }

  function positionPanel(panel, btn) {
    if (!panel || !btn) return;
    const left = btn.offsetLeft + btn.offsetWidth / 2;
    panel.style.left = left + 'px';
  }

  function showSizePanel(btnEl) {
    const panel = document.getElementById('doodleSizePanel');
    const range = document.getElementById('doodleSizeRange');
    const opacityRange = document.getElementById('doodleOpacityRange');
    closePanels();
    range.value = String(S.lineWidth);
    document.getElementById('doodleSizeValue').textContent = String(S.lineWidth);
    opacityRange.value = String(Math.round(S.opacity * 100));
    document.getElementById('doodleOpacityValue').textContent = String(Math.round(S.opacity * 100));
    let btn = btnEl;
    if (!btn) btn = S.modal.querySelector('#doodleToolbar [data-tool="' + S.tool + '"]');
    positionPanel(panel, btn);
    panel.classList.add('show');
  }

  function toggleSizePanel(btnEl) {
    const panel = document.getElementById('doodleSizePanel');
    if (panel.classList.contains('show')) closePanels();
    else showSizePanel(btnEl);
  }

  function closePanels() {
    ['doodleSizePanel', 'doodleColorPanel', 'doodleRatioMenu'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.classList.remove('show');
    });
  }

  function updateColorUI() {
    const sw = document.getElementById('doodleColorSwatch');
    if (sw) sw.style.background = S.color;
    S.modal.querySelectorAll('.doodle-swatch').forEach((b) => {
      b.classList.toggle('selected', b.dataset.color === S.color);
    });
  }

  function setRatio(ratio) {
    if (!DOODLE_RATIO_KEYS.includes(ratio)) return;
    closePanels();
    if (ratio === S.ratio) return;
    S.ratio = ratio;
    recalcOutSize();
    relayoutImage();
    layoutCanvas();
    updateRatioUI();
    requestRender();
  }

  function updateRatioUI() {
    const btn = document.getElementById('doodleRatioBtn');
    if (btn) btn.textContent = ratioLabel(S.ratio) + ' ▾';
    S.modal.querySelectorAll('.doodle-ratio-item').forEach((item) => {
      item.classList.toggle('selected', item.dataset.ratio === S.ratio);
    });
  }

  function updateToolbarUI() {
    const undoBtn = document.getElementById('doodleUndoBtn');
    const redoBtn = document.getElementById('doodleRedoBtn');
    const clearBtn = document.getElementById('doodleClearBtn');
    if (undoBtn) undoBtn.disabled = S.undoStack.length === 0;
    if (redoBtn) redoBtn.disabled = S.redoStack.length === 0;
    if (clearBtn) clearBtn.disabled = S.elements.length === 0;
    updateColorUI();
    updateRatioUI();
  }

  // =====================================================================
  // 上传替换底图
  // =====================================================================
  function onUploadInputChange(e) {
    const input = e.target;
    const file = input.files && input.files[0];
    input.value = '';
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      showToastMsg(tr('doodle_select_image', '请选择图片文件'), 'error');
      return;
    }
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      replaceBaseImage(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      showToastMsg(tr('doodle_load_fail', '图片加载失败'), 'error');
    };
    img.src = url;
  }

  /** 替换底图并清空涂鸦（一步可撤销恢复）。 */
  function replaceBaseImage(img) {
    if (!S.image || !S.open) return;
    if (S.textEditor) cancelTextEditor();
    const before = { image: snapImageFull(), elements: S.elements.slice() };
    S.image = { img, naturalW: img.naturalWidth || 1, naturalH: img.naturalHeight || 1, x: 0, y: 0, scale: 1 };
    S.elements = [];
    S.selectedId = null;
    recalcOutSize();
    relayoutImage();
    layoutCanvas();
    const after = { image: snapImageFull(), elements: [] };
    pushRecord({ action: 'replaceImage', before, after });
    requestRender();
  }

  // =====================================================================
  // 打开 / 关闭 / 确认合成
  // =====================================================================
  /**
   * 内置确认弹窗：不依赖宿主页面的 showConfirmModal——
   * 后者 z-index 为 10000，会被本弹窗（10050）遮挡，这里用 10100 独立实现。
   */
  function confirmDialog(message, opts) {
    const o = opts || {};
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.style.cssText =
        'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(15,23,42,0.55);' +
        'display:flex;align-items:center;justify-content:center;z-index:10100;';
      const card = document.createElement('div');
      card.style.cssText =
        'background:#ffffff;border-radius:12px;padding:22px;max-width:400px;width:88%;' +
        'box-shadow:0 20px 60px rgba(0,0,0,0.3);font-family:inherit;';
      const titleEl = document.createElement('div');
      titleEl.style.cssText = 'font-size:15px;font-weight:600;margin-bottom:12px;color:#111827;';
      titleEl.textContent = o.title || tr('doodle_confirm_title', '确认');
      const msgEl = document.createElement('div');
      msgEl.style.cssText = 'font-size:13px;color:#374151;white-space:pre-wrap;line-height:1.6;margin-bottom:20px;';
      msgEl.textContent = message;
      const btnRow = document.createElement('div');
      btnRow.style.cssText = 'display:flex;justify-content:flex-end;gap:12px;';
      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.style.cssText =
        'padding:8px 18px;border:1px solid #d1d5db;border-radius:8px;background:#fff;cursor:pointer;font-size:13px;color:#374151;';
      cancelBtn.textContent = o.cancelText || tr('doodle_cancel', '取消');
      const confirmBtn = document.createElement('button');
      confirmBtn.type = 'button';
      confirmBtn.style.cssText =
        'padding:8px 18px;border:none;border-radius:8px;background:#2563eb;color:#fff;cursor:pointer;font-size:13px;font-weight:600;';
      confirmBtn.textContent = o.confirmText || tr('doodle_confirm', '确认');
      function done(result) {
        document.body.removeChild(overlay);
        resolve(result);
      }
      cancelBtn.addEventListener('click', () => done(false));
      confirmBtn.addEventListener('click', () => done(true));
      overlay.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          done(false);
        }
      });
      overlay.tabIndex = -1;
      btnRow.appendChild(cancelBtn);
      btnRow.appendChild(confirmBtn);
      card.appendChild(titleEl);
      card.appendChild(msgEl);
      card.appendChild(btnRow);
      overlay.appendChild(card);
      document.body.appendChild(overlay);
      confirmBtn.focus();
    });
  }

  function showToastMsg(msg, type) {
    if (typeof showToast === 'function') showToast(msg, type);
    else if (typeof window !== 'undefined' && typeof window.showToast === 'function') window.showToast(msg, type);
  }

  function showLoading(show) {
    const el = document.getElementById('doodleLoading');
    if (el) el.style.display = show ? 'flex' : 'none';
  }

  /**
   * 打开涂鸦编辑器。
   * @param {string} imageUrl 底图 URL（建议先经 proxyImageUrl 防跨域污染 canvas）
   * @param {{ nodeId?: any, context?: any, onComplete?: (result: {blob: Blob, context: any, nodeId: any}) => void }} [opts]
   */
  async function open(imageUrl, opts) {
    if (!imageUrl) return;
    if (S.open && S.busy) return;
    const options = opts || {};
    ensureModalDom();
    S.modal.classList.add('show');
    S.modal.setAttribute('aria-hidden', 'false');
    showLoading(true);

    let loadUrl = imageUrl;
    if (!loadUrl.startsWith('data:') && !loadUrl.startsWith('blob:')) {
      try {
        const response = await fetch(loadUrl);
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const blob = await response.blob();
        if (S.objectUrl) URL.revokeObjectURL(S.objectUrl);
        loadUrl = URL.createObjectURL(blob);
        S.objectUrl = loadUrl;
      } catch (err) {
        console.error('Failed to fetch image for doodle editor:', err);
      }
    }

    const img = new Image();
    img.onload = () => {
      initSession(img, options);
    };
    img.onerror = () => {
      showLoading(false);
      closeModal();
      showToastMsg(tr('doodle_load_fail', '图片加载失败'), 'error');
    };
    img.src = loadUrl;
  }

  function initSession(img, options) {
    S.open = true;
    S.busy = false;
    // 聚焦弹窗卡片，让键盘事件经过 modal 的 keydown 拦截（否则 focus 停在 body 时快捷键直达 window）
    const card = S.modal.querySelector('.doodle-modal-card');
    if (card) card.focus();
    S.image = { img, naturalW: img.naturalWidth || 1, naturalH: img.naturalHeight || 1, x: 0, y: 0, scale: 1 };
    S.ratio = 'original';
    recalcOutSize();
    relayoutImage();
    S.elements = [];
    S.nextId = 1;
    S.selectedId = null;
    S.undoStack = [];
    S.redoStack = [];
    S.drag = null;
    S.tool = 'select';
    S.color = DEFAULT_COLOR;
    S.lineWidth = DEFAULT_LINE_WIDTH;
    S.opacity = DEFAULT_OPACITY_PERCENT / 100;
    S.context = options;
    S.onComplete = typeof options.onComplete === 'function' ? options.onComplete : null;

    if (S.confirmBtn) {
      S.confirmBtn.disabled = false;
      S.confirmBtn.textContent = tr('doodle_confirm', '确认');
    }
    applyToolButtons();
    updateCursor();
    updateToolbarUI();
    closePanels();
    showLoading(false);
    layoutCanvas();

    if (!S.onResize) {
      S.onResize = () => {
        if (S.open) layoutCanvas();
      };
      window.addEventListener('resize', S.onResize);
    }
    requestRender();
  }

  /** X / 外部关闭：有内容时二次确认。 */
  async function requestClose() {
    if (!S.open || S.busy) return;
    if (S.elements.length > 0) {
      const ok = await confirmDialog(
        tr('doodle_exit_confirm', '关闭后，本次涂鸦编辑内容将不会保存。'),
        { title: tr('doodle_exit_title', '确定退出吗？'), confirmText: tr('doodle_exit_confirm_btn', '确认退出') }
      );
      if (!ok) return;
    }
    closeModal();
  }

  function closeModal() {
    removeTextEditor();
    S.open = false;
    S.busy = false;
    S.drag = null;
    S.selectedId = null;
    S.elements = [];
    S.undoStack = [];
    S.redoStack = [];
    S.image = null;
    S.context = null;
    S.onComplete = null;
    if (S.objectUrl) {
      URL.revokeObjectURL(S.objectUrl);
      S.objectUrl = null;
    }
    if (S.onResize) {
      window.removeEventListener('resize', S.onResize);
      S.onResize = null;
    }
    closePanels();
    if (S.modal) {
      S.modal.classList.remove('show');
      S.modal.setAttribute('aria-hidden', 'true');
    }
    showLoading(false);
  }

  /** 按输出画布自然分辨率合成底图 + 涂鸦（PNG）；超大面积时等比降采样防浏览器 canvas 上限。 */
  function buildCompositeBlob() {
    const MAX_AREA = 64 * 1024 * 1024;
    return new Promise((resolve, reject) => {
      try {
        let w = S.out.w;
        let h = S.out.h;
        let scale = 1;
        if (w * h > MAX_AREA) {
          scale = Math.sqrt(MAX_AREA / (w * h));
          w = Math.max(1, Math.floor(w * scale));
          h = Math.max(1, Math.floor(h * scale));
        }
        const c = document.createElement('canvas');
        c.width = w;
        c.height = h;
        const g = c.getContext('2d');
        if (scale !== 1) g.scale(w / S.out.w, h / S.out.h);
        // drawContent 内部自行垫底图与白底（destination-over），此处不可预铺白底
        drawContent(g);
        c.toBlob((b) => (b ? resolve(b) : reject(new Error('toBlob failed'))), 'image/png');
      } catch (err) {
        reject(err);
      }
    });
  }

  async function confirmEdit() {
    if (!S.open || S.busy) return;
    S.busy = true;
    if (S.confirmBtn) {
      S.confirmBtn.disabled = true;
      S.confirmBtn.textContent = tr('doodle_confirming', '确认中…');
    }
    commitTextEditor();
    const cb = S.onComplete;
    const ctxInfo = S.context;
    let blob = null;
    let err = null;
    try {
      blob = await buildCompositeBlob();
    } catch (e) {
      err = e;
    }
    closeModal();
    if (err) {
      console.error('Doodle composite failed:', err);
      showToastMsg(tr('doodle_composite_fail', '合成涂鸦图片失败'), 'error');
      return;
    }
    if (typeof cb === 'function') {
      try {
        await cb({ blob, context: ctxInfo, nodeId: ctxInfo && ctxInfo.nodeId });
      } catch (e) {
        console.error('Doodle onComplete failed:', e);
      }
    }
  }

  function isOpen() {
    return !!S.open;
  }

  // =====================================================================
  // 全局暴露
  // =====================================================================
  if (typeof window !== 'undefined') {
    window.imageDoodleEditor = {
      open: open,
      close: requestClose,
      closeNow: closeModal,
      isOpen: isOpen,
    };
  }

  // ES Module exports（供 Vitest 测试使用，不影响浏览器全局变量）
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      DOODLE_COLORS,
      DOODLE_RATIO_KEYS,
      computeOutSize,
      containFit,
      pointToSegmentDistance,
      measureApproxText,
      elementBBox,
      hitTestElement,
      handlePointsForBbox,
      hitHandleIndex,
      normalizeRect,
      distFactor,
      dragBbox,
      applyRecord,
    };
  }
})();
