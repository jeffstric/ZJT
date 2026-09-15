// ============================
// canvas_context_menu.js - 画布右键菜单
// 按上下文（选中节点/选中组/剪贴板）启用或禁用菜单项；
// 输入框内右键保留浏览器原生菜单。
// ============================
(function(){
  'use strict';

  var COPY_EXCLUDED_TYPES = ['script', 'shot_group', 'shot_frame'];
  var menuEl = null;

  function ensureMenu(){
    if(menuEl) return menuEl;
    menuEl = document.createElement('div');
    menuEl.className = 'canvas-context-menu';
    menuEl.innerHTML =
      '<div class="canvas-context-menu-item" data-action="copy">复制<span class="shortcut">Ctrl+C</span></div>' +
      '<div class="canvas-context-menu-item" data-action="paste">粘贴<span class="shortcut">Ctrl+V</span></div>' +
      '<div class="canvas-context-menu-item" data-action="duplicate">再制<span class="shortcut">Ctrl+D</span></div>' +
      '<div class="canvas-context-menu-sep"></div>' +
      '<div class="canvas-context-menu-item" data-action="group">编组<span class="shortcut">Ctrl+G</span></div>' +
      '<div class="canvas-context-menu-item" data-action="ungroup">解散编组<span class="shortcut">Ctrl+Shift+G</span></div>' +
      '<div class="canvas-context-menu-sep"></div>' +
      '<div class="canvas-context-menu-item canvas-context-menu-danger" data-action="delete">删除<span class="shortcut">Delete</span></div>';
    document.body.appendChild(menuEl);

    menuEl.addEventListener('click', function(e){
      var item = e.target.closest('.canvas-context-menu-item');
      if(!item || item.classList.contains('disabled')) return;
      var action = item.dataset.action;
      hideMenu();
      runAction(action);
    });
    return menuEl;
  }

  function runAction(action){
    switch(action){
      case 'copy':       if(typeof copySelectedNodes === 'function') copySelectedNodes(); break;
      case 'paste':      if(typeof pasteClipboard === 'function') pasteClipboard(); break;
      case 'duplicate':  if(typeof duplicateSelectedNodes === 'function') duplicateSelectedNodes(); break;
      case 'group':      if(typeof groupSelectedNodes === 'function') groupSelectedNodes(); break;
      case 'ungroup':    if(typeof ungroupSelection === 'function') ungroupSelection(); break;
      case 'delete':     deleteSelection(); break;
    }
  }

  function deleteSelection(){
    if(state.selectedGroupId != null && typeof dissolveGroup === 'function'){
      dissolveGroup(state.selectedGroupId);
      showToast('已解散分组（节点已保留）', 'info');
      return;
    }
    if(!state.selectedNodeIds.length) return;
    if(window.confirm('确定要删除选中的 ' + state.selectedNodeIds.length + ' 个节点吗？')){
      state.selectedNodeIds.slice().forEach(function(id){ removeNode(id); });
      if(typeof clearSelection === 'function') clearSelection();
    }
  }

  function setItemEnabled(action, enabled){
    var item = menuEl.querySelector('.canvas-context-menu-item[data-action="' + action + '"]');
    if(item) item.classList.toggle('disabled', !enabled);
  }

  function updateMenuItems(){
    var hasClipboard = !!(state.clipboard && state.clipboard.nodes.length);
    var copyableCount = 0;
    var totalCount = 0;
    (state.selectedNodeIds || []).forEach(function(id){
      var n = state.nodes.find(function(x){ return x.id === id; });
      if(!n) return;
      totalCount++;
      if(COPY_EXCLUDED_TYPES.indexOf(n.type) === -1) copyableCount++;
    });
    var groupSelected = state.selectedGroupId != null;
    var someInGroup = (state.selectedNodeIds || []).some(function(id){
      return typeof nodeIdInAnyGroup === 'function' && nodeIdInAnyGroup(id);
    });
    setItemEnabled('copy', copyableCount > 0);
    setItemEnabled('duplicate', copyableCount > 0);
    setItemEnabled('paste', hasClipboard);
    setItemEnabled('group', totalCount >= 2);
    setItemEnabled('ungroup', groupSelected || someInGroup);
    setItemEnabled('delete', totalCount > 0 || groupSelected);
  }

  function showMenu(x, y){
    var menu = ensureMenu();
    updateMenuItems();
    menu.classList.add('show');
    var rect = menu.getBoundingClientRect();
    var left = Math.min(x, window.innerWidth - rect.width - 8);
    var top = Math.min(y, window.innerHeight - rect.height - 8);
    menu.style.left = Math.max(4, left) + 'px';
    menu.style.top = Math.max(4, top) + 'px';
  }

  function hideMenu(){
    if(menuEl) menuEl.classList.remove('show');
  }

  function isEditableTarget(e){
    return !!(e.target.closest && e.target.closest('input, textarea, select, [contenteditable="true"]'));
  }

  function init(){
    var container = document.getElementById('canvasContainer');
    if(!container) return;

    container.addEventListener('contextmenu', function(e){
      if(isEditableTarget(e)) return;
      // 内部组件（如全景查看器）已自行处理右键时不弹出画布菜单
      if(e.defaultPrevented) return;
      e.preventDefault();

      // 右键组标题栏：切换为选中该组
      var titlebarEl = e.target.closest ? e.target.closest('.node-group-titlebar') : null;
      if(titlebarEl && typeof selectGroup === 'function'){
        var groupBox = titlebarEl.closest('.node-group');
        var gid = groupBox ? Number(groupBox.dataset.groupId) : null;
        if(gid && state.selectedGroupId !== gid) selectGroup(gid);
      }

      // 右键节点且不在当前选中集：切换为单选该节点
      var nodeEl = e.target.closest ? e.target.closest('.node') : null;
      if(nodeEl){
        var nodeId = Number(nodeEl.dataset.nodeId);
        if(nodeId && state.selectedNodeIds.indexOf(nodeId) === -1 && typeof setSelected === 'function'){
          setSelected(nodeId);
        }
      }

      showMenu(e.clientX, e.clientY);
    });

    // 点击菜单外 / Esc / 滚轮时关闭
    document.addEventListener('mousedown', function(e){
      if(menuEl && menuEl.classList.contains('show') && !(e.target.closest && e.target.closest('.canvas-context-menu'))){
        hideMenu();
      }
    }, true);
    document.addEventListener('keydown', function(e){
      if(e.key === 'Escape') hideMenu();
    });
    window.addEventListener('wheel', function(){ hideMenu(); }, { passive: true });
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
