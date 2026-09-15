// ============================
// canvas_clipboard.js - 画布节点复制/粘贴/再制
// 页面内存剪贴板（state.clipboard）：分镜/分镜组/剧本节点与后端数据强绑定，不支持复制；
// 其余节点深拷贝 data + 选中集内部连线，粘贴时分配新 id 后走 restoreNode 复原
// （与工作流重载同一路径，保证粘贴结果可随工作流持久化、支持撤销）。
// ============================
(function(){
  'use strict';

  // 与后端记录强绑定的节点类型，不参与复制粘贴
  var COPY_EXCLUDED_TYPES = ['script', 'shot_group', 'shot_frame'];
  var EXCLUDED_TIP = '分镜、分镜组、剧本节点与后端数据绑定，不支持复制';

  var CONN_ARRAYS = ['connections', 'imageConnections', 'firstFrameConnections', 'videoConnections', 'referenceConnections', 'audioConnections'];
  var CONN_ID_KEYS = {
    connections: 'nextConnId',
    imageConnections: 'nextImgConnId',
    firstFrameConnections: 'nextFirstFrameConnId',
    videoConnections: 'nextVideoConnId',
    referenceConnections: 'nextReferenceConnId',
    audioConnections: 'nextAudioConnId'
  };

  function isCopyable(node){
    return node && COPY_EXCLUDED_TYPES.indexOf(node.type) === -1;
  }

  function collectSelectionForCopy(){
    var result = { copyable: [], excluded: 0 };
    var ids = (state.selectedNodeIds || []).slice();
    for(var i = 0; i < ids.length; i++){
      var node = state.nodes.find(function(n){ return n.id === ids[i]; });
      if(!node) continue;
      if(!isCopyable(node)){ result.excluded++; continue; }
      result.copyable.push(node);
    }
    return result;
  }

  // structuredClone 可保留 File 对象（同页面粘贴仍可上传）；失败时回退 JSON（丢失 File）
  function deepClone(value){
    try{
      if(typeof structuredClone === 'function') return structuredClone(value);
    }catch(e){}
    return JSON.parse(JSON.stringify(value));
  }

  // 粘贴副本需要重置的运行态字段（如上传中标记），避免与原节点共享瞬时状态
  function sanitizeData(data){
    if(!data || typeof data !== 'object') return data;
    if('uploading' in data) data.uploading = false;
    return data;
  }

  function copySelectedNodes(){
    var sel = collectSelectionForCopy();
    if(sel.copyable.length === 0){
      showToast(sel.excluded > 0 ? EXCLUDED_TIP : '请先选中要复制的节点', 'warning');
      return false;
    }
    var idSet = {};
    var nodeCopies = sel.copyable.map(function(node){
      idSet[node.id] = true;
      return {
        id: node.id,
        type: node.type,
        title: node.title,
        x: node.x,
        y: node.y,
        data: deepClone(node.data)
      };
    });
    // 只收集选中集内部的连线（端点都在选中集内的才可整体复刻）
    var connCopies = [];
    for(var i = 0; i < CONN_ARRAYS.length; i++){
      var arr = CONN_ARRAYS[i];
      var conns = state[arr] || [];
      for(var j = 0; j < conns.length; j++){
        var c = conns[j];
        if(idSet[c.from] && idSet[c.to]){
          connCopies.push({ array: arr, from: c.from, to: c.to, portType: c.portType });
        }
      }
    }
    state.clipboard = { nodes: nodeCopies, connections: connCopies, pasteCount: 0 };
    if(sel.excluded > 0){
      showToast('已复制 ' + nodeCopies.length + ' 个节点（' + EXCLUDED_TIP + '）', 'info');
    } else {
      showToast('已复制 ' + nodeCopies.length + ' 个节点', 'success');
    }
    return true;
  }

  /**
   * 粘贴剪贴板节点
   * @param {Object} [opts] - opts.anchor 指定粘贴锚点（再制用），缺省用最近鼠标位置
   * @returns {number[]|null} 新节点 id 列表
   */
  function pasteClipboard(opts){
    opts = opts || {};
    var clip = state.clipboard;
    if(!clip || !clip.nodes.length){
      showToast('剪贴板为空，请先复制节点', 'warning');
      return null;
    }
    // 锚点：优先调用方指定，其次最近鼠标所在画布坐标，最后视口左上
    var anchor = opts.anchor ||
      state.lastMouseWorldPos ||
      (typeof getViewportNodePosition === 'function' ? getViewportNodePosition() : { x: 100, y: 120 });

    // 剪贴板内容包围盒，保持相对布局
    var minX = Infinity, minY = Infinity;
    for(var k = 0; k < clip.nodes.length; k++){
      minX = Math.min(minX, clip.nodes[k].x);
      minY = Math.min(minY, clip.nodes[k].y);
    }
    // 连续粘贴向右下错开，避免完全重叠
    var step = 30 * (clip.pasteCount || 0);
    var baseX = anchor.x + step;
    var baseY = Math.max(MIN_NODE_Y, anchor.y + step);

    var idMap = {};
    var newIds = [];
    for(var i = 0; i < clip.nodes.length; i++){
      var c = clip.nodes[i];
      var newId = state.nextNodeId++;
      idMap[c.id] = newId;
      var nodeData = {
        id: newId,
        type: c.type,
        title: c.title,
        x: Math.max(20, baseX + (c.x - minX)),
        y: Math.max(MIN_NODE_Y, baseY + (c.y - minY)),
        data: sanitizeData(deepClone(c.data))
      };
      if(typeof restoreNode !== 'function'){
        state.nextNodeId--;
        continue;
      }
      restoreNode(nodeData);
      newIds.push(newId);
    }
    if(!newIds.length){
      showToast('粘贴失败：该节点类型不支持自动复原', 'error');
      return null;
    }

    // 按旧 id → 新 id 重映射，重建内部连线
    for(var j = 0; j < clip.connections.length; j++){
      var cc = clip.connections[j];
      var fromId = idMap[cc.from];
      var toId = idMap[cc.to];
      if(!fromId || !toId) continue;
      var connArray = state[cc.array] || (state[cc.array] = []);
      connArray.push({
        id: state[CONN_ID_KEYS[cc.array]]++,
        from: fromId,
        to: toId,
        portType: cc.portType
      });
    }

    clip.pasteCount = (clip.pasteCount || 0) + 1;
    if(typeof renderAllConnections === 'function') renderAllConnections();
    if(typeof renderMinimap === 'function') renderMinimap();
    if(typeof setMultipleSelected === 'function') setMultipleSelected(newIds);
    captureHistorySnapshot();
    safeAutoSave();
    showToast('已粘贴 ' + newIds.length + ' 个节点', 'success');
    return newIds;
  }

  function duplicateSelectedNodes(){
    var sel = collectSelectionForCopy();
    if(sel.copyable.length === 0){
      showToast(sel.excluded > 0 ? EXCLUDED_TIP : '请先选中要复制的节点', 'warning');
      return null;
    }
    var minX = Infinity, minY = Infinity;
    for(var i = 0; i < sel.copyable.length; i++){
      minX = Math.min(minX, sel.copyable[i].x);
      minY = Math.min(minY, sel.copyable[i].y);
    }
    if(!copySelectedNodes()) return null;
    // 再制在原位置右下错开 30px，不叠加连续粘贴偏移
    state.clipboard.pasteCount = 0;
    return pasteClipboard({ anchor: { x: minX + 30, y: minY + 30 } });
  }

  window.copySelectedNodes = copySelectedNodes;
  window.pasteClipboard = pasteClipboard;
  window.duplicateSelectedNodes = duplicateSelectedNodes;
  window.isNodeCopyable = isCopyable;
})();
