// ============================
// canvas_shortcuts.js - 画布快捷键说明弹窗
// 首次进入画布自动打开（用户尚未确认过滚轮操作时）；
// 用户点选过「滚轮上下平移 / 滚轮缩放画布」任一项后记在本机，后续进入不再自动弹。
// 任何形式的关闭（× 按钮 / 点击遮罩 / Esc）同样视为已确认，下次进入不再自动弹。
// 工具栏「快捷键」按钮仍可随时手动打开。
// 滚轮模式记在本机：默认 pan（滚轮上下平移，Ctrl+滚轮缩放）。
// 只有点「滚轮缩放画布」后才是 zoom（滚轮缩放，Ctrl+滚轮上下平移）。
// ============================
(function(root){
  'use strict';

  var WHEEL_MODE_KEY = 'canvasWheelMode';
  var WHEEL_MODE_ACK_KEY = 'canvasWheelModeAcked';

  function getCanvasWheelMode(){
    try {
      return root.localStorage && root.localStorage.getItem(WHEEL_MODE_KEY) === 'zoom' ? 'zoom' : 'pan';
    } catch (e) {
      return 'pan';
    }
  }

  // 用户是否已确认过（点选过弹窗里的任一模式按钮，或以任何方式关闭过弹窗）
  function hasWheelModeAck(){
    try {
      return !!(root.localStorage && root.localStorage.getItem(WHEEL_MODE_ACK_KEY) === '1');
    } catch (e) {
      return false;
    }
  }

  function ackWheelMode(){
    try {
      if(root.localStorage) root.localStorage.setItem(WHEEL_MODE_ACK_KEY, '1');
    } catch (e) {}
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
      // 任何形式的关闭都视为已确认，后续进入不再自动弹
      ackWheelMode();
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
        // 明确选择过滚轮操作，后续进入画布不再自动弹窗
        ackWheelMode();
      });
    }
    if(zoomBtn){
      zoomBtn.addEventListener('click', function(e){
        e.stopPropagation();
        setCanvasWheelMode('zoom');
        ackWheelMode();
      });
    }
    // 点击遮罩空白处关闭（点在卡片上不关）
    modal.addEventListener('click', function(e){
      if(e.target === modal) close();
    });
    root.addEventListener('keydown', function(e){
      if(e.key === 'Escape' && modal.classList.contains('show')) close();
    });

    // 首次（未确认过）进入画布时弹出提醒；点选过任一模式、或以任何方式
    // 关闭过弹窗后记在本机，后续进入不再自动弹。手动点「快捷键」按钮仍可打开。
    if(!hasWheelModeAck()) open();
  }

  if(root.document){
    if(root.document.readyState === 'loading'){
      root.document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  }
})(typeof window !== 'undefined' ? window : globalThis);
