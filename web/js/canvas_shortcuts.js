// ============================
// canvas_shortcuts.js - 画布快捷键说明弹窗
// 进入画布自动打开；工具栏「快捷键」也可再打开。
// 关闭方式：× 按钮 / 点击遮罩 / Esc。
// 滚轮模式记在本机：默认 pan（滚轮上下平移，Ctrl+滚轮缩放）。
// 只有点「滚轮缩放画布」后才是 zoom（滚轮缩放，Ctrl+滚轮上下平移）。
// ============================
(function(root){
  'use strict';

  var WHEEL_MODE_KEY = 'canvasWheelMode';

  function getCanvasWheelMode(){
    try {
      return root.localStorage && root.localStorage.getItem(WHEEL_MODE_KEY) === 'zoom' ? 'zoom' : 'pan';
    } catch (e) {
      return 'pan';
    }
  }

  function fillWheelKeys(container, withCtrl){
    if(!container || !root.document) return;
    while(container.firstChild) container.removeChild(container.firstChild);
    var combo = root.document.createElement('span');
    combo.className = 'shortcut-combo';
    if(withCtrl){
      var kbd = root.document.createElement('kbd');
      kbd.textContent = 'Ctrl';
      var plus = root.document.createElement('span');
      plus.className = 'plus';
      plus.textContent = '+';
      combo.appendChild(kbd);
      combo.appendChild(plus);
    }
    var mouse = root.document.createElement('span');
    mouse.className = 'shortcut-mouse';
    mouse.textContent = '滚轮';
    combo.appendChild(mouse);
    container.appendChild(combo);
  }

  function applyCanvasWheelModeUi(mode){
    var doc = root.document;
    if(!doc) return;
    var zoomMode = mode === 'zoom';
    var panBtn = doc.getElementById('shortcutWheelModePan');
    var zoomBtn = doc.getElementById('shortcutWheelModeZoom');
    var hint = doc.getElementById('shortcutWheelModeHint');
    if(panBtn){
      panBtn.setAttribute('aria-pressed', zoomMode ? 'false' : 'true');
      panBtn.classList.toggle('is-selected', !zoomMode);
    }
    if(zoomBtn){
      zoomBtn.setAttribute('aria-pressed', zoomMode ? 'true' : 'false');
      zoomBtn.classList.toggle('is-selected', zoomMode);
    }
    if(hint){
      hint.textContent = zoomMode
        ? '当前：滚轮缩放画布，Ctrl + 滚轮上下平移。点击「滚轮上下平移」可改回去。'
        : '当前：滚轮上下平移，Ctrl + 滚轮缩放。只有点击「滚轮缩放画布」后，滚轮才会缩放。';
    }
    fillWheelKeys(doc.getElementById('shortcutWheelZoomKeys'), !zoomMode);
    fillWheelKeys(doc.getElementById('shortcutWheelPanKeys'), zoomMode);
  }

  function setCanvasWheelMode(mode){
    var next = mode === 'zoom' ? 'zoom' : 'pan';
    try {
      if(root.localStorage) root.localStorage.setItem(WHEEL_MODE_KEY, next);
    } catch (e) {}
    applyCanvasWheelModeUi(next);
    return next;
  }

  root.getCanvasWheelMode = getCanvasWheelMode;
  root.setCanvasWheelMode = setCanvasWheelMode;

  function init(){
    var doc = root.document;
    if(!doc) return;
    var btn = doc.getElementById('shortcutHelpBtn');
    var modal = doc.getElementById('shortcutHelpModal');
    if(!modal) return;
    var closeBtn = doc.getElementById('shortcutHelpModalClose');

    function open(){
      applyCanvasWheelModeUi(getCanvasWheelMode());
      modal.classList.add('show');
      modal.setAttribute('aria-hidden', 'false');
    }
    function close(){
      modal.classList.remove('show');
      modal.setAttribute('aria-hidden', 'true');
    }

    if(btn){
      btn.addEventListener('click', function(e){
        e.stopPropagation();
        open();
      });
    }
    if(closeBtn){
      closeBtn.addEventListener('click', function(e){
        e.stopPropagation();
        close();
      });
    }
    var panBtn = doc.getElementById('shortcutWheelModePan');
    var zoomBtn = doc.getElementById('shortcutWheelModeZoom');
    if(panBtn){
      panBtn.addEventListener('click', function(e){
        e.stopPropagation();
        setCanvasWheelMode('pan');
      });
    }
    if(zoomBtn){
      zoomBtn.addEventListener('click', function(e){
        e.stopPropagation();
        setCanvasWheelMode('zoom');
      });
    }
    // 点击遮罩空白处关闭（点在卡片上不关）
    modal.addEventListener('click', function(e){
      if(e.target === modal) close();
    });
    root.addEventListener('keydown', function(e){
      if(e.key === 'Escape' && modal.classList.contains('show')) close();
    });

    // 每次进入画布都弹出，提醒确认滚轮操作。关掉不改变当前模式。
    open();
  }

  if(root.document){
    if(root.document.readyState === 'loading'){
      root.document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  }
})(typeof window !== 'undefined' ? window : globalThis);
