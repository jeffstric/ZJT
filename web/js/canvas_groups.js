// ============================
// canvas_groups.js - 画布分组（视觉编组）
// 组框是纯视觉容器（Miro 风格）：节点拖动落点在组框内自动加入、拖出自动移出。
// 数据挂在 state.groups，随 serializeWorkflow 整图持久化，撤销/重载均走既有快照链路。
// 不支持嵌套：节点加入新组时自动从原组移出。
// ============================
(function(){
  'use strict';

  var GROUP_PADDING = 28;       // 包围盒四周留白（顶部留白与标题栏等高，避免遮挡成员）
  var TITLE_BAR_HEIGHT = 28;
  var EMPTY_GROUP_W = 400;
  var EMPTY_GROUP_H = 300;
  var DEFAULT_TITLE = '分组';

  function getCanvasEl(){
    return document.getElementById('canvas');
  }

  function findGroup(groupId){
    return state.groups.find(function(g){ return g.id === groupId; }) || null;
  }

  function groupArea(g){
    return (g.w || 0) * (g.h || 0);
  }

  function pointInGroup(g, x, y){
    return x >= g.x && x <= g.x + g.w && y >= g.y && y <= g.y + g.h;
  }

  // ─── 组框 DOM ───────────────────────────

  function getGroupEl(groupId){
    return getCanvasEl().querySelector('.node-group[data-group-id="' + groupId + '"]');
  }

  function createGroupEl(group){
    var el = document.createElement('div');
    el.className = 'node-group';
    el.dataset.groupId = String(group.id);
    el.innerHTML =
      '<div class="node-group-titlebar">' +
        '<span class="node-group-title"></span>' +
        '<input class="node-group-title-input" style="display:none" />' +
        '<button class="node-group-close" title="解散分组">\u00d7</button>' +
      '</div>';
    bindGroupElEvents(el, group);
    var canvas = getCanvasEl();
    canvas.insertBefore(el, canvas.firstChild);
    return el;
  }

  function updateGroupEl(group){
    var el = getGroupEl(group.id) || createGroupEl(group);
    el.style.left = group.x + 'px';
    el.style.top = group.y + 'px';
    el.style.width = group.w + 'px';
    el.style.height = group.h + 'px';
    var titleEl = el.querySelector('.node-group-title');
    if(titleEl){
      var title = group.title || (DEFAULT_TITLE + ' ' + group.id);
      titleEl.textContent = title;
      titleEl.title = title;
    }
  }

  function removeGroupEl(groupId){
    var el = getGroupEl(groupId);
    if(el) el.remove();
  }

  function bindGroupElEvents(el, group){
    var groupId = group.id;
    var titlebar = el.querySelector('.node-group-titlebar');
    var titleEl = el.querySelector('.node-group-title');
    var inputEl = el.querySelector('.node-group-title-input');
    var closeBtn = el.querySelector('.node-group-close');

    closeBtn.addEventListener('click', function(e){
      e.stopPropagation();
      dissolveGroup(groupId);
      if(typeof showToast === 'function') showToast('已解散分组（节点已保留）', 'info');
    });

    titlebar.addEventListener('mousedown', function(e){
      if(e.button !== 0) return;
      if(e.target === inputEl || e.target === closeBtn) return;
      e.preventDefault();
      e.stopPropagation();
      var g = findGroup(groupId);
      if(!g) return;
      selectGroup(groupId);
      startGroupDrag(g, e);
    });

    titlebar.addEventListener('dblclick', function(e){
      e.preventDefault();
      e.stopPropagation();
      startRename(groupId, titleEl, inputEl);
    });
  }

  // ─── 组整体拖动（复用 events.js 的 state.drag 传动，groupId 分支）───

  function startGroupDrag(g, e){
    var positions = {};
    var firstId = null;
    for(var i = 0; i < g.nodeIds.length; i++){
      var n = state.nodes.find(function(x){ return x.id === g.nodeIds[i]; });
      if(!n) continue;
      if(firstId === null) firstId = n.id;
      positions[n.id] = { x: n.x, y: n.y };
    }
    if(firstId === null){
      // 空组：直接拖组框本身
      state.drag = {
        nodeId: null,
        startX: e.clientX,
        startY: e.clientY,
        origX: g.x,
        origY: g.y,
        nodePositions: {},
        moved: false,
        groupId: g.id,
        emptyGroup: true,
        groupOrig: { x: g.x, y: g.y }
      };
      return;
    }
    var first = state.nodes.find(function(x){ return x.id === firstId; });
    if(!first) return;
    state.drag = {
      nodeId: first.id,
      startX: e.clientX,
      startY: e.clientY,
      origX: first.x,
      origY: first.y,
      nodePositions: positions,
      moved: false,
      groupId: g.id
    };
  }

  // 拖动过程中同步组框（mousemove 高频调用，仅做样式更新）。
  // 只有整组拖动（标题栏发起）需要框跟随成员平移；
  // 普通节点拖动时组框必须保持静止——成员中心移出框边界才算脱离分组，
  // 若框跟着被拖节点扩张，节点永远不会"离开"框，拖出判定随之失效。
  function updateGroupFramesDuringDrag(drag, dx, dy){
    if(!drag || !drag.groupId) return;
    var g = findGroup(drag.groupId);
    if(!g) return;
    if(drag.emptyGroup && drag.groupOrig){
      g.x = Math.max(20, drag.groupOrig.x + dx);
      g.y = Math.max(MIN_NODE_Y, drag.groupOrig.y + dy);
      updateGroupEl(g);
      return;
    }
    recalcGroupBounds(g);
  }

  // ─── 包围盒 ───────────────────────────

  function recalcGroupBounds(group){
    if(!group.nodeIds.length) return false;
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for(var i = 0; i < group.nodeIds.length; i++){
      var n = state.nodes.find(function(x){ return x.id === group.nodeIds[i]; });
      if(!n) continue;
      var size = getNodeSize(n);
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + size.w);
      maxY = Math.max(maxY, n.y + size.h);
    }
    if(minX === Infinity) return false;
    group.x = minX - GROUP_PADDING;
    group.y = minY - GROUP_PADDING;
    group.w = (maxX - minX) + GROUP_PADDING * 2;
    group.h = (maxY - minY) + GROUP_PADDING * 2;
    updateGroupEl(group);
    return true;
  }

  function recalcAllGroupsBounds(){
    for(var i = 0; i < state.groups.length; i++){
      recalcGroupBounds(state.groups[i]);
    }
  }

  // ─── 成员归属判定（节点拖动/放置结束时调用）───
  // 拖动普通节点期间组框保持静止（见 updateGroupFramesDuringDrag），
  // 因此这里直接用节点中心与组框本身的相对位置判定即可：
  // 中心在框内 = 保持/加入成员；在框外 = 脱离。重叠组取面积最小者。
  function updateNodeGroupMembership(nodeId){
    var node = state.nodes.find(function(x){ return x.id === nodeId; });
    if(!node) return false;
    var size = getNodeSize(node);
    var cx = node.x + size.w / 2;
    var cy = node.y + size.h / 2;
    var target = null;
    for(var i = 0; i < state.groups.length; i++){
      var g = state.groups[i];
      if(pointInGroup(g, cx, cy)){
        if(!target || groupArea(g) < groupArea(target)) target = g;
      }
    }
    var changed = false;
    for(var j = 0; j < state.groups.length; j++){
      var gg = state.groups[j];
      var idx = gg.nodeIds.indexOf(nodeId);
      if(idx !== -1 && gg !== target){
        gg.nodeIds.splice(idx, 1);
        recalcGroupBounds(gg);
        changed = true;
      }
    }
    if(target && target.nodeIds.indexOf(nodeId) === -1){
      target.nodeIds.push(nodeId);
      recalcGroupBounds(target);
      changed = true;
    }
    if(changed) safeAutoSave();
    return changed;
  }

  function removeNodeIdFromGroups(nodeId, opts){
    var changed = false;
    for(var i = 0; i < state.groups.length; i++){
      var g = state.groups[i];
      var idx = g.nodeIds.indexOf(nodeId);
      if(idx !== -1){
        g.nodeIds.splice(idx, 1);
        recalcGroupBounds(g);
        changed = true;
      }
    }
    if(changed && !(opts && opts.skipSave)) safeAutoSave();
    return changed;
  }

  function nodeIdInAnyGroup(nodeId){
    return state.groups.some(function(g){ return g.nodeIds.indexOf(nodeId) !== -1; });
  }

  // ─── 编组 / 解散 ───────────────────────────

  function createGroupFromNodes(nodeIds, opts){
    opts = opts || {};
    var members = [];
    (nodeIds || []).forEach(function(id){
      var n = state.nodes.find(function(x){ return x.id === id; });
      if(n && members.indexOf(n.id) === -1) members.push(n.id);
    });
    // 不支持嵌套：先从原组移出
    members.forEach(function(id){ removeNodeIdFromGroups(id, { skipSave: true }); });

    var id = state.nextGroupId++;
    var group = {
      id: id,
      title: opts.title || (DEFAULT_TITLE + ' ' + id),
      x: 0, y: 0, w: EMPTY_GROUP_W, h: EMPTY_GROUP_H,
      nodeIds: members
    };
    state.groups.push(group);
    if(members.length){
      recalcGroupBounds(group);
    } else {
      var pos = (typeof getViewportNodePosition === 'function') ? getViewportNodePosition() : { x: 100, y: 120 };
      group.x = (typeof opts.x === 'number') ? opts.x : pos.x;
      group.y = (typeof opts.y === 'number') ? opts.y : pos.y;
    }
    updateGroupEl(group);
    return group;
  }

  function groupSelectedNodes(){
    var ids = (state.selectedNodeIds || []).slice();
    if(ids.length < 2){
      showToast('请至少选中 2 个节点再编组', 'warning');
      return null;
    }
    var g = createGroupFromNodes(ids);
    selectGroup(g.id);
    safeAutoSave();
    showToast('已创建「' + g.title + '」，拖动节点进/出框可调整成员', 'info');
    return g;
  }

  function ungroupSelection(){
    if(state.selectedGroupId != null){
      var g = findGroup(state.selectedGroupId);
      if(g && dissolveGroup(g.id)){
        showToast('已解散分组（节点已保留）', 'info');
        return true;
      }
    }
    var changed = false;
    state.selectedNodeIds.slice().forEach(function(id){
      if(removeNodeIdFromGroups(id)) changed = true;
    });
    if(changed) showToast('已将选中节点移出分组', 'info');
    else showToast('请先选中一个分组或组内节点', 'warning');
    return changed;
  }

  function dissolveGroup(groupId){
    var idx = state.groups.findIndex(function(g){ return g.id === groupId; });
    if(idx === -1) return false;
    state.groups.splice(idx, 1);
    removeGroupEl(groupId);
    if(state.selectedGroupId === groupId) state.selectedGroupId = null;
    safeAutoSave();
    return true;
  }

  function createEmptyGroup(opts){
    var g = createGroupFromNodes([], opts);
    selectGroup(g.id);
    safeAutoSave();
    return g;
  }

  // ─── 选中态（组选中与节点选中互斥）───

  function selectGroup(groupId){
    if(typeof clearSelection === 'function') clearSelection();
    for(var i = 0; i < state.groups.length; i++){
      var el = getGroupEl(state.groups[i].id);
      if(el) el.classList.toggle('selected', state.groups[i].id === groupId);
    }
    state.selectedGroupId = groupId;
  }

  function deselectGroup(){
    var el = getCanvasEl().querySelector('.node-group.selected');
    if(el) el.classList.remove('selected');
    state.selectedGroupId = null;
  }

  // ─── 重命名 ───────────────────────────

  function startRename(groupId, titleEl, inputEl){
    var g = findGroup(groupId);
    if(!g) return;
    inputEl.value = g.title || '';
    titleEl.style.display = 'none';
    inputEl.style.display = '';
    inputEl.focus();
    inputEl.select();

    function cleanup(){
      inputEl.removeEventListener('blur', commit);
      inputEl.removeEventListener('keydown', onKey);
      inputEl.style.display = 'none';
      titleEl.style.display = '';
    }
    function commit(){
      var gg = findGroup(groupId);
      if(gg){
        var v = inputEl.value.trim();
        var newTitle = v || (DEFAULT_TITLE + ' ' + groupId);
        if(newTitle !== gg.title){
          gg.title = newTitle;
          updateGroupEl(gg);
          safeAutoSave();
        }
      }
      cleanup();
    }
    function onKey(ev){
      if(ev.key === 'Enter'){
        ev.preventDefault();
        commit();
      } else if(ev.key === 'Escape'){
        cleanup();
      }
    }
    inputEl.addEventListener('blur', commit);
    inputEl.addEventListener('keydown', onKey);
  }

  // ─── 工作流恢复 ───────────────────────────

  function restoreGroups(groups, nextGroupId){
    var canvas = getCanvasEl();
    var oldEls = Array.prototype.slice.call(canvas.querySelectorAll('.node-group'));
    oldEls.forEach(function(el){ el.remove(); });
    state.groups = [];
    state.selectedGroupId = null;

    var list = Array.isArray(groups) ? groups : [];
    var maxId = 0;
    list.forEach(function(gd){
      if(!gd || typeof gd.id !== 'number') return;
      var memberIds = (gd.nodeIds || []).filter(function(nid){
        return state.nodes.some(function(n){ return n.id === nid; });
      });
      var g = {
        id: gd.id,
        title: gd.title || (DEFAULT_TITLE + ' ' + gd.id),
        x: (typeof gd.x === 'number') ? gd.x : 0,
        y: (typeof gd.y === 'number') ? gd.y : 0,
        w: (typeof gd.w === 'number' && gd.w > 0) ? gd.w : EMPTY_GROUP_W,
        h: (typeof gd.h === 'number' && gd.h > 0) ? gd.h : EMPTY_GROUP_H,
        nodeIds: memberIds
      };
      state.groups.push(g);
      maxId = Math.max(maxId, g.id);
      if(g.nodeIds.length) recalcGroupBounds(g);
      else updateGroupEl(g);
    });
    state.nextGroupId = (typeof nextGroupId === 'number' && nextGroupId > 0) ? nextGroupId : maxId + 1;
  }

  window.createGroupFromNodes = createGroupFromNodes;
  window.groupSelectedNodes = groupSelectedNodes;
  window.ungroupSelection = ungroupSelection;
  window.dissolveGroup = dissolveGroup;
  window.createEmptyGroup = createEmptyGroup;
  window.restoreGroups = restoreGroups;
  window.removeNodeIdFromGroups = removeNodeIdFromGroups;
  window.updateNodeGroupMembership = updateNodeGroupMembership;
  window.nodeIdInAnyGroup = nodeIdInAnyGroup;
  window.recalcAllGroupsBounds = recalcAllGroupsBounds;
  window.selectGroup = selectGroup;
  window.deselectGroup = deselectGroup;
  window.updateGroupFramesDuringDrag = updateGroupFramesDuringDrag;
  window.findGroupById = findGroup;
})();
