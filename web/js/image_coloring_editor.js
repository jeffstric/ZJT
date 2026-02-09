// Image Coloring Editor Module
// Provides canvas-based drawing/coloring functionality for image editing

(function() {
  'use strict';

  // State for the coloring editor
  const coloringState = {
    canvas: null,
    ctx: null,
    isDrawing: false,
    brushSize: 20,
    brushColor: '#ff0000',
    brushOpacity: 0.5,
    history: [],
    historyStep: -1,
    maxHistory: 20,
    originalImage: null,
    currentNodeId: null,
    onComplete: null
  };

  // Initialize the coloring editor
  function initImageColoringEditor() {
    setupModal();
    setupEventListeners();
  }

  // Setup modal structure
  function setupModal() {
    // Modal is already in HTML, just get references
    coloringState.canvas = document.getElementById('coloringCanvas');
    if (coloringState.canvas) {
      coloringState.ctx = coloringState.canvas.getContext('2d');
    }
  }

  // Setup event listeners
  function setupEventListeners() {
    const canvas = coloringState.canvas;
    if (!canvas) return;

    // Mouse events for drawing
    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('mouseup', handleMouseUp);
    canvas.addEventListener('mouseleave', handleMouseUp);

    // Touch events for mobile support
    canvas.addEventListener('touchstart', handleTouchStart, { passive: false });
    canvas.addEventListener('touchmove', handleTouchMove, { passive: false });
    canvas.addEventListener('touchend', handleMouseUp);

    // Tool buttons
    const brushSizeSlider = document.getElementById('coloringBrushSize');
    const brushSizeValue = document.getElementById('coloringBrushSizeValue');
    const colorPicker = document.getElementById('coloringColor');
    const opacitySlider = document.getElementById('coloringOpacity');
    const opacityValue = document.getElementById('coloringOpacityValue');

    if (brushSizeSlider) {
      brushSizeSlider.addEventListener('input', (e) => {
        coloringState.brushSize = parseInt(e.target.value);
        if (brushSizeValue) brushSizeValue.textContent = e.target.value;
      });
    }

    if (colorPicker) {
      colorPicker.addEventListener('input', (e) => {
        coloringState.brushColor = e.target.value;
      });
    }

    if (opacitySlider) {
      opacitySlider.addEventListener('input', (e) => {
        coloringState.brushOpacity = parseInt(e.target.value) / 100;
        if (opacityValue) opacityValue.textContent = e.target.value;
      });
    }

    // Action buttons
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

    // Preset colors
    const presetColors = document.querySelectorAll('.coloring-preset-color');
    presetColors.forEach(btn => {
      btn.addEventListener('click', () => {
        const color = btn.dataset.color;
        coloringState.brushColor = color;
        if (colorPicker) colorPicker.value = color;
      });
    });
  }

  // Handle mouse down
  function handleMouseDown(e) {
    if (!coloringState.ctx) return;
    coloringState.isDrawing = true;
    const rect = coloringState.canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) * (coloringState.canvas.width / rect.width);
    const y = (e.clientY - rect.top) * (coloringState.canvas.height / rect.height);

    saveHistory();
    draw(x, y);
  }

  // Handle mouse move
  function handleMouseMove(e) {
    if (!coloringState.isDrawing || !coloringState.ctx) return;
    const rect = coloringState.canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) * (coloringState.canvas.width / rect.width);
    const y = (e.clientY - rect.top) * (coloringState.canvas.height / rect.height);

    draw(x, y);
  }

  // Handle mouse up
  function handleMouseUp() {
    if (coloringState.isDrawing) {
      coloringState.isDrawing = false;
      coloringState.ctx.beginPath();
    }
  }

  // Handle touch start
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

  // Handle touch move
  function handleTouchMove(e) {
    e.preventDefault();
    if (!coloringState.isDrawing || !coloringState.ctx) return;
    const touch = e.touches[0];
    const rect = coloringState.canvas.getBoundingClientRect();
    const x = (touch.clientX - rect.left) * (coloringState.canvas.width / rect.width);
    const y = (touch.clientY - rect.top) * (coloringState.canvas.height / rect.height);

    draw(x, y);
  }

  // Draw on canvas
  function draw(x, y) {
    const ctx = coloringState.ctx;
    ctx.lineWidth = coloringState.brushSize;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    // Parse color and apply opacity
    const color = coloringState.brushColor;
    const opacity = coloringState.brushOpacity;

    // Convert hex to rgba
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

  // Save canvas state to history
  function saveHistory() {
    if (!coloringState.canvas) return;

    // Remove any redo states
    if (coloringState.historyStep < coloringState.history.length - 1) {
      coloringState.history = coloringState.history.slice(0, coloringState.historyStep + 1);
    }

    // Save current state
    coloringState.history.push(coloringState.canvas.toDataURL());

    // Limit history size
    if (coloringState.history.length > coloringState.maxHistory) {
      coloringState.history.shift();
    } else {
      coloringState.historyStep++;
    }

    updateUndoButton();
  }

  // Undo last action
  function undo() {
    if (coloringState.historyStep > 0) {
      coloringState.historyStep--;
      restoreFromHistory();
    }
  }

  // Restore from history
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

  // Update undo button state
  function updateUndoButton() {
    const undoBtn = document.getElementById('coloringUndoBtn');
    if (undoBtn) {
      undoBtn.disabled = coloringState.historyStep <= 0;
      undoBtn.style.opacity = coloringState.historyStep <= 0 ? '0.5' : '1';
    }
  }

  // Clear canvas (but keep background image)
  function clearCanvas() {
    if (!coloringState.canvas || !coloringState.ctx) return;

    saveHistory();
    coloringState.ctx.clearRect(0, 0, coloringState.canvas.width, coloringState.canvas.height);

    // Redraw original image
    if (coloringState.originalImage) {
      coloringState.ctx.drawImage(coloringState.originalImage, 0, 0);
    }
  }

  // Open the coloring modal
  function openImageColoringModal(imageUrl, nodeId, onCompleteCallback) {
    const modal = document.getElementById('coloringEditorModal');
    const canvas = document.getElementById('coloringCanvas');

    if (!modal || !canvas) {
      console.error('Coloring modal elements not found');
      return;
    }

    coloringState.currentNodeId = nodeId;
    coloringState.onComplete = onCompleteCallback;
    coloringState.history = [];
    coloringState.historyStep = -1;

    // Load image
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      coloringState.originalImage = img;

      // Set canvas size to match image
      canvas.width = img.width;
      canvas.height = img.height;

      // Draw original image on canvas as background
      coloringState.ctx.clearRect(0, 0, canvas.width, canvas.height);
      coloringState.ctx.drawImage(img, 0, 0);
      
      // Save initial state
      saveHistory();

      // Show modal
      modal.classList.add('show');
      modal.setAttribute('aria-hidden', 'false');
    };
    img.onerror = () => {
      if (window.showToast) {
        window.showToast('图片加载失败', 'error');
      } else {
        alert('图片加载失败');
      }
    };
    img.src = imageUrl;
  }

  // Close the modal
  function closeModal() {
    const modal = document.getElementById('coloringEditorModal');
    if (modal) {
      modal.classList.remove('show');
      modal.setAttribute('aria-hidden', 'true');
    }
    coloringState.currentNodeId = null;
    coloringState.onComplete = null;
    coloringState.originalImage = null;
  }

  // Confirm and get the edited image
  function confirmEdit() {
    if (!coloringState.canvas || !coloringState.onComplete) {
      closeModal();
      return;
    }

    // Get the colored image as data URL
    const coloredImageData = coloringState.canvas.toDataURL('image/png');

    // Call the completion callback
    coloringState.onComplete({
      nodeId: coloringState.currentNodeId,
      coloredImage: coloredImageData,
      originalImage: coloringState.originalImage
    });

    closeModal();
  }

  // Expose public API
  window.imageColoringEditor = {
    init: initImageColoringEditor,
    open: openImageColoringModal,
    close: closeModal
  };

  // Auto-init when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initImageColoringEditor);
  } else {
    initImageColoringEditor();
  }
})();
