// Image Coloring Editor Module
// Provides canvas-based drawing/coloring functionality for image editing.
// Page-agnostic: auto-injects modal DOM if missing (video_workflow / storyboard).

(function() {
  'use strict';

  const coloringState = {
    canvas: null,
    ctx: null,
    cursorEl: null,
    isDrawing: false,
    brushSize: 50,
    brushColor: '#ff0000',
    brushOpacity: 0.5,
    history: [],
    historyStep: -1,
    maxHistory: 20,
    originalImage: null,
    /** @type {any} legacy nodeId or free-form context object */
    context: null,
    onComplete: null
  };

  var _coloringInitialized = false;
  var _listenersBound = false;

  function updateCursorPreview() {
    const el = coloringState.cursorEl;
    if (!el) return;
    const displaySize = Math.max(coloringState.brushSize, 4);
    el.style.width = displaySize + 'px';
    el.style.height = displaySize + 'px';
    el.style.borderColor = coloringState.brushColor;
  }

  function buildModalHtml() {
    return (
      '<div class="modal coloring-editor-modal" id="coloringEditorModal" aria-hidden="true">' +
        '<div class="modal-card coloring-modal-card" role="dialog" aria-modal="true">' +
          '<div class="modal-header coloring-modal-header">' +
            '<div class="modal-title coloring-modal-title" data-i18n="coloring_edit_modal">图片涂色编辑</div>' +
            '<button class="modal-close coloring-modal-close" id="coloringEditorModalClose" type="button" aria-label="关闭">×</button>' +
          '</div>' +
          '<div class="modal-body coloring-modal-body">' +
            '<div class="coloring-canvas-container">' +
              '<canvas id="coloringCanvas"></canvas>' +
            '</div>' +
            '<div class="coloring-tools">' +
              '<div class="coloring-field field">' +
                '<label class="coloring-label label">画笔大小</label>' +
                '<input type="range" id="coloringBrushSize" min="20" max="200" value="50" />' +
                '<div class="coloring-value"><span id="coloringBrushSizeValue">50</span>px</div>' +
              '</div>' +
              '<div class="coloring-field field">' +
                '<label class="coloring-label label">颜色</label>' +
                '<input type="color" id="coloringColor" value="#ff0000" />' +
              '</div>' +
              '<div class="coloring-field field">' +
                '<label class="coloring-label label">透明度</label>' +
                '<input type="range" id="coloringOpacity" min="0" max="100" value="50" />' +
                '<div class="coloring-value"><span id="coloringOpacityValue">50</span>%</div>' +
              '</div>' +
            '</div>' +
            '<div class="coloring-action-row">' +
              '<button class="coloring-btn mini-btn secondary" id="coloringUndoBtn" type="button">撤销</button>' +
              '<button class="coloring-btn mini-btn secondary" id="coloringClearBtn" type="button">清空</button>' +
            '</div>' +
          '</div>' +
          '<div class="modal-footer coloring-modal-footer">' +
            '<button class="coloring-btn mini-btn secondary" id="coloringCancelBtn" type="button">取消</button>' +
            '<button class="coloring-btn primary mini-btn" id="coloringConfirmBtn" type="button">确认</button>' +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  function ensureModalDom() {
    let modal = document.getElementById('coloringEditorModal');
    if (!modal) {
      const host = document.createElement('div');
      host.innerHTML = buildModalHtml();
      modal = host.firstElementChild;
      document.body.appendChild(modal);
    } else if (!modal.classList.contains('coloring-editor-modal')) {
      modal.classList.add('coloring-editor-modal');
    }
    return modal;
  }

  function initImageColoringEditor() {
    if (typeof document === 'undefined') return;
    ensureModalDom();
    setupModal();
    if (!_listenersBound) {
      setupEventListeners();
      _listenersBound = true;
    }
    _coloringInitialized = true;
  }

  function setupModal() {
    coloringState.canvas = document.getElementById('coloringCanvas');
    if (coloringState.canvas) {
      coloringState.ctx = coloringState.canvas.getContext('2d');
    }

    const container = coloringState.canvas ? coloringState.canvas.parentElement : null;
    if (container && !coloringState.cursorEl) {
      const existing = container.querySelector('.coloring-brush-cursor');
      if (existing) {
        coloringState.cursorEl = existing;
      } else {
        const cursorEl = document.createElement('div');
        cursorEl.className = 'coloring-brush-cursor';
        cursorEl.style.cssText = 'position:absolute;border-radius:50%;border:2px solid #ff0000;pointer-events:none;display:none;transform:translate(-50%,-50%);z-index:10;mix-blend-mode:difference;';
        container.appendChild(cursorEl);
        coloringState.cursorEl = cursorEl;
      }
    }
  }

  function setupEventListeners() {
    const canvas = coloringState.canvas;
    if (!canvas) return;

    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('mouseup', handleMouseUp);
    canvas.addEventListener('mouseleave', () => {
      handleMouseUp();
      if (coloringState.cursorEl) coloringState.cursorEl.style.display = 'none';
    });
    canvas.addEventListener('mouseenter', () => {
      if (coloringState.cursorEl) coloringState.cursorEl.style.display = 'block';
    });

    canvas.addEventListener('touchstart', handleTouchStart, { passive: false });
    canvas.addEventListener('touchmove', handleTouchMove, { passive: false });
    canvas.addEventListener('touchend', handleMouseUp);

    const brushSizeSlider = document.getElementById('coloringBrushSize');
    const brushSizeValue = document.getElementById('coloringBrushSizeValue');
    const colorPicker = document.getElementById('coloringColor');
    const opacitySlider = document.getElementById('coloringOpacity');
    const opacityValue = document.getElementById('coloringOpacityValue');

    if (brushSizeSlider) {
      brushSizeSlider.addEventListener('input', (e) => {
        coloringState.brushSize = parseInt(e.target.value, 10);
        if (brushSizeValue) brushSizeValue.textContent = e.target.value;
        updateCursorPreview();
      });
    }

    if (colorPicker) {
      colorPicker.addEventListener('input', (e) => {
        coloringState.brushColor = e.target.value;
        updateCursorPreview();
      });
    }

    if (opacitySlider) {
      opacitySlider.addEventListener('input', (e) => {
        coloringState.brushOpacity = parseInt(e.target.value, 10) / 100;
        if (opacityValue) opacityValue.textContent = e.target.value;
      });
    }

    const undoBtn = document.getElementById('coloringUndoBtn');
    const clearBtn = document.getElementById('coloringClearBtn');
    const cancelBtn = document.getElementById('coloringCancelBtn');
    const confirmBtn = document.getElementById('coloringConfirmBtn');
    const closeBtn = document.getElementById('coloringEditorModalClose');

    if (undoBtn) undoBtn.addEventListener('click', undo);
    if (clearBtn) clearBtn.addEventListener('click', clearCanvas);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
    if (confirmBtn) confirmBtn.addEventListener('click', confirmEdit);
    if (closeBtn) closeBtn.addEventListener('click', closeModal);

    const presetColors = document.querySelectorAll('.coloring-preset-color');
    presetColors.forEach(btn => {
      btn.addEventListener('click', () => {
        const color = btn.dataset.color;
        coloringState.brushColor = color;
        if (colorPicker) colorPicker.value = color;
        updateCursorPreview();
      });
    });
  }

  function handleMouseDown(e) {
    if (!coloringState.ctx) return;
    coloringState.isDrawing = true;
    const rect = coloringState.canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) * (coloringState.canvas.width / rect.width);
    const y = (e.clientY - rect.top) * (coloringState.canvas.height / rect.height);

    saveHistory();
    draw(x, y);
  }

  function handleMouseMove(e) {
    const rect = coloringState.canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) * (coloringState.canvas.width / rect.width);
    const y = (e.clientY - rect.top) * (coloringState.canvas.height / rect.height);

    if (coloringState.cursorEl) {
      coloringState.cursorEl.style.left = (e.clientX - rect.left) + 'px';
      coloringState.cursorEl.style.top = (e.clientY - rect.top) + 'px';
    }

    if (!coloringState.isDrawing || !coloringState.ctx) return;
    draw(x, y);
  }

  function handleMouseUp() {
    if (coloringState.isDrawing) {
      coloringState.isDrawing = false;
      if (coloringState.ctx) coloringState.ctx.beginPath();
    }
  }

  function handleTouchStart(e) {
    e.preventDefault();
    if (!coloringState.ctx) return;
    const touch = e.touches[0];
    const rect = coloringState.canvas.getBoundingClientRect();
    const x = (touch.clientX - rect.left) * (coloringState.canvas.width / rect.width);
    const y = (touch.clientY - rect.top) * (coloringState.canvas.height / rect.height);

    coloringState.isDrawing = true;
    saveHistory();
    draw(x, y);
  }

  function handleTouchMove(e) {
    e.preventDefault();
    if (!coloringState.isDrawing || !coloringState.ctx) return;
    const touch = e.touches[0];
    const rect = coloringState.canvas.getBoundingClientRect();
    const x = (touch.clientX - rect.left) * (coloringState.canvas.width / rect.width);
    const y = (touch.clientY - rect.top) * (coloringState.canvas.height / rect.height);

    draw(x, y);
  }

  function draw(x, y) {
    const ctx = coloringState.ctx;
    const canvas = coloringState.canvas;
    const rect = canvas.getBoundingClientRect();
    const scale = canvas.width / rect.width;
    ctx.lineWidth = coloringState.brushSize * scale;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    const color = coloringState.brushColor;
    const opacity = coloringState.brushOpacity;
    const r = parseInt(color.slice(1, 3), 16);
    const g = parseInt(color.slice(3, 5), 16);
    const b = parseInt(color.slice(5, 7), 16);

    ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${opacity})`;
    ctx.globalCompositeOperation = 'source-over';

    ctx.lineTo(x, y);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x, y);
  }

  function saveHistory() {
    if (!coloringState.canvas) return;

    if (coloringState.historyStep < coloringState.history.length - 1) {
      coloringState.history = coloringState.history.slice(0, coloringState.historyStep + 1);
    }

    coloringState.history.push(coloringState.canvas.toDataURL());

    if (coloringState.history.length > coloringState.maxHistory) {
      coloringState.history.shift();
    } else {
      coloringState.historyStep++;
    }

    updateUndoButton();
  }

  function undo() {
    if (coloringState.historyStep > 0) {
      coloringState.historyStep--;
      restoreFromHistory();
    }
  }

  function restoreFromHistory() {
    if (!coloringState.canvas || !coloringState.ctx) return;

    const img = new Image();
    img.onload = () => {
      coloringState.ctx.clearRect(0, 0, coloringState.canvas.width, coloringState.canvas.height);
      coloringState.ctx.drawImage(img, 0, 0);
    };
    img.src = coloringState.history[coloringState.historyStep];

    updateUndoButton();
  }

  function updateUndoButton() {
    const undoBtn = document.getElementById('coloringUndoBtn');
    if (undoBtn) {
      undoBtn.disabled = coloringState.historyStep <= 0;
      undoBtn.style.opacity = coloringState.historyStep <= 0 ? '0.5' : '1';
    }
  }

  function clearCanvas() {
    if (!coloringState.canvas || !coloringState.ctx) return;

    saveHistory();
    coloringState.ctx.clearRect(0, 0, coloringState.canvas.width, coloringState.canvas.height);

    if (coloringState.originalImage) {
      coloringState.ctx.drawImage(coloringState.originalImage, 0, 0);
    }
  }

  /**
   * Open coloring editor.
   * @param {string} imageUrl
   * @param {any} contextOrId nodeId (workflow) or context object (storyboard)
   * @param {(result: object) => void} onCompleteCallback
   */
  async function openImageColoringModal(imageUrl, contextOrId, onCompleteCallback) {
    initImageColoringEditor();

    const modal = document.getElementById('coloringEditorModal');
    const canvas = document.getElementById('coloringCanvas');

    if (!modal || !canvas || !coloringState.ctx) {
      console.error('Coloring modal elements not found');
      return;
    }

    coloringState.context = contextOrId;
    coloringState.onComplete = onCompleteCallback;
    coloringState.history = [];
    coloringState.historyStep = -1;

    let loadUrl = imageUrl;
    const img = new Image();
    // fetch → blob URL 避免跨域污染 canvas
    if (loadUrl && !loadUrl.startsWith('data:') && !loadUrl.startsWith('blob:')) {
      try {
        const response = await fetch(loadUrl);
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const blob = await response.blob();
        loadUrl = URL.createObjectURL(blob);
      } catch (e) {
        console.error('Failed to fetch image for coloring editor:', e);
      }
    }
    img.onload = () => {
      if (img.src.startsWith('blob:')) {
        URL.revokeObjectURL(img.src);
      }

      coloringState.originalImage = img;

      canvas.width = img.width;
      canvas.height = img.height;

      coloringState.ctx.clearRect(0, 0, canvas.width, canvas.height);
      coloringState.ctx.drawImage(img, 0, 0);

      saveHistory();
      updateCursorPreview();

      modal.classList.add('show');
      modal.setAttribute('aria-hidden', 'false');
    };
    img.onerror = () => {
      if (img.src.startsWith('blob:')) {
        URL.revokeObjectURL(img.src);
      }
      if (window.showToast) {
        window.showToast('图片加载失败', 'error');
      } else {
        alert('图片加载失败');
      }
    };
    img.src = loadUrl;
  }

  function closeModal() {
    const modal = document.getElementById('coloringEditorModal');
    if (modal) {
      modal.classList.remove('show');
      modal.setAttribute('aria-hidden', 'true');
    }
    coloringState.context = null;
    coloringState.onComplete = null;
    coloringState.originalImage = null;
    coloringState.history = [];
    coloringState.historyStep = -1;
  }

  function confirmEdit() {
    if (!coloringState.canvas || !coloringState.onComplete) {
      closeModal();
      return;
    }

    const coloredImageData = coloringState.canvas.toDataURL('image/png');
    const context = coloringState.context;
    const legacyNodeId = (context && typeof context === 'object')
      ? (context.nodeId != null ? context.nodeId : context.id)
      : context;

    coloringState.onComplete({
      nodeId: legacyNodeId,
      context: context,
      coloredImage: coloredImageData,
      originalImage: coloringState.originalImage
    });

    closeModal();
  }

  window.imageColoringEditor = {
    init: initImageColoringEditor,
    open: openImageColoringModal,
    close: closeModal,
    ensureModal: ensureModalDom
  };

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initImageColoringEditor);
    } else {
      initImageColoringEditor();
    }
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      initImageColoringEditor,
      openImageColoringModal,
      ensureModalDom,
      buildModalHtml,
    };
  }
})();
