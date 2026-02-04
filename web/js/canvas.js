    const MIN_ZOOM = 0.25;
    const MAX_ZOOM = 2;

    function renderMinimap(){
      updateCanvasSize();
      
      if(state.nodes.length === 0){
        minimapContent.innerHTML = '';
        return;
      }
      
      // 计算所有节点的边界
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for(const node of state.nodes){
        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        const w = el ? el.offsetWidth : 300;
        const h = el ? el.offsetHeight : 200;
        minX = Math.min(minX, node.x);
        minY = Math.min(minY, node.y);
        maxX = Math.max(maxX, node.x + w);
        maxY = Math.max(maxY, node.y + h);
      }
      
      // 添加边距
      minX -= 100;
      minY -= 100;
      maxX += 100;
      maxY += 100;
      
      const contentWidth = maxX - minX;
      const contentHeight = maxY - minY;
      
      // 计算缩放比例
      const scaleX = (MINIMAP_WIDTH - MINIMAP_PADDING * 2) / contentWidth;
      const scaleY = (MINIMAP_HEIGHT - MINIMAP_PADDING * 2) / contentHeight;
      const scale = Math.min(scaleX, scaleY, 0.15); // 最大缩放0.15
      
      let html = '';
      
      // 渲染节点
      for(const node of state.nodes){
        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        const w = el ? el.offsetWidth : 300;
        const h = el ? el.offsetHeight : 200;
        const x = (node.x - minX) * scale + MINIMAP_PADDING;
        const y = (node.y - minY) * scale + MINIMAP_PADDING;
        const mw = w * scale;
        const mh = h * scale;
        html += `<div class="minimap-node" style="left:${x}px;top:${y}px;width:${mw}px;height:${mh}px;"></div>`;
      }
      
      // 渲染视口框
      const containerRect = canvasContainer.getBoundingClientRect();
      const viewportX = (-state.panX / state.zoom - minX) * scale + MINIMAP_PADDING;
      const viewportY = (-state.panY / state.zoom - minY) * scale + MINIMAP_PADDING;
      const viewportW = (containerRect.width / state.zoom) * scale;
      const viewportH = (containerRect.height / state.zoom) * scale;
      html += `<div class="minimap-viewport" style="left:${viewportX}px;top:${viewportY}px;width:${viewportW}px;height:${viewportH}px;"></div>`;
      
      minimapContent.innerHTML = html;
      
      // 保存minimap状态用于点击导航
      state.minimapState = { minX, minY, scale };
    }

    function applyTransform(){
      canvasWorld.style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
    }

    function updateZoomLevel(){
      zoomLevelEl.textContent = Math.round(state.zoom * 100) + '%';
    }

    function setZoom(newZoom, focal){
      const clampedZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, newZoom));
      const oldZoom = state.zoom || 1;
      if(clampedZoom === oldZoom) return;

      const containerRect = canvasContainer.getBoundingClientRect();
      const focalX = focal && typeof focal.x === 'number' ? focal.x : containerRect.width / 2;
      const focalY = focal && typeof focal.y === 'number' ? focal.y : containerRect.height / 2;
      const worldX = (focalX - state.panX) / oldZoom;
      const worldY = (focalY - state.panY) / oldZoom;

      state.zoom = clampedZoom;
      state.panX = Math.min(0, focalX - worldX * clampedZoom);
      state.panY = Math.min(0, focalY - worldY * clampedZoom);

      applyTransform();
      updateZoomLevel();
      renderConnections();
      renderMinimap();
      renderImageConnections();
      renderFirstFrameConnections();
      renderVideoConnections();
    }

    function zoomIn(){
      setZoom(state.zoom + 0.1);
    }

    function zoomOut(){
      setZoom(state.zoom - 0.1);
    }

    function setSelected(id){
      state.selectedNodeId = id;
      state.selectedNodeIds = id ? [id] : [];
      for(const nodeEl of canvasEl.querySelectorAll('.node')){
        const nid = Number(nodeEl.dataset.nodeId);
        nodeEl.classList.toggle('selected', nid === id);
      }
      setTimeout(() => {
        if(typeof renderConnections === 'function') renderConnections();
        if(typeof renderImageConnections === 'function') renderImageConnections();
      }, 250);
    }

    function bringNodeToFront(nodeId){
      const nodeEl = canvasEl.querySelector(`.node[data-node-id="${nodeId}"]`);
      if(!nodeEl) return;
      if(typeof state.topZIndex !== 'number' || state.topZIndex < 21){
        state.topZIndex = 21;
      }
      state.topZIndex += 1;
      nodeEl.style.zIndex = state.topZIndex;
    }

    function clearSelection(){
      setSelected(null);
      state.selectedNodeIds = [];
      for(const nodeEl of canvasEl.querySelectorAll('.node')){
        nodeEl.classList.remove('selected');
      }
      setTimeout(() => {
        if(typeof renderConnections === 'function') renderConnections();
        if(typeof renderImageConnections === 'function') renderImageConnections();
      }, 250);
    }

    function setMultipleSelected(nodeIds){
      state.selectedNodeIds = nodeIds;
      state.selectedNodeId = nodeIds.length === 1 ? nodeIds[0] : null;
      for(const nodeEl of canvasEl.querySelectorAll('.node')){
        const nid = Number(nodeEl.dataset.nodeId);
        nodeEl.classList.toggle('selected', nodeIds.includes(nid));
      }
      setTimeout(() => {
        if(typeof renderConnections === 'function') renderConnections();
        if(typeof renderImageConnections === 'function') renderImageConnections();
      }, 250);
    }

    function addToSelection(nodeId){
      if(!state.selectedNodeIds.includes(nodeId)){
        state.selectedNodeIds.push(nodeId);
        const nodeEl = canvasEl.querySelector(`.node[data-node-id="${nodeId}"]`);
        if(nodeEl) nodeEl.classList.add('selected');
        setTimeout(() => {
          if(typeof renderConnections === 'function') renderConnections();
          if(typeof renderImageConnections === 'function') renderImageConnections();
        }, 250);
      }
    }

    function removeFromSelection(nodeId){
      state.selectedNodeIds = state.selectedNodeIds.filter(id => id !== nodeId);
      const nodeEl = canvasEl.querySelector(`.node[data-node-id="${nodeId}"]`);
      if(nodeEl) nodeEl.classList.remove('selected');
      setTimeout(() => {
        if(typeof renderConnections === 'function') renderConnections();
        if(typeof renderImageConnections === 'function') renderImageConnections();
      }, 250);
    }

    function initNodeDrag(nodeId, startX, startY){
      const node = state.nodes.find(n => n.id === nodeId);
      if(!node) return;
      
      // 如果拖动的节点在选中列表中，记录所有选中节点的初始位置
      if(state.selectedNodeIds.includes(nodeId)){
        const nodePositions = {};
        state.selectedNodeIds.forEach(id => {
          const n = state.nodes.find(x => x.id === id);
          if(n){
            nodePositions[id] = { x: n.x, y: n.y };
          }
        });
        state.drag = {
          nodeId: nodeId,
          startX: startX,
          startY: startY,
          origX: node.x,
          origY: node.y,
          nodePositions: nodePositions,
          moved: false
        };
      } else {
        // 单个节点拖动
        state.drag = {
          nodeId: nodeId,
          startX: startX,
          startY: startY,
          origX: node.x,
          origY: node.y,
          nodePositions: {},
          moved: false
        };
      }
    }

    function getViewportNodePosition(){
      const containerRect = canvasContainer.getBoundingClientRect();
      const viewportWidth = containerRect.width / state.zoom;
      const viewportHeight = containerRect.height / state.zoom;
      const viewportLeft = -state.panX / state.zoom;
      const viewportTop = -state.panY / state.zoom;
      
      const marginLeft = 100;
      const marginTop = 80;
      
      const x = Math.max(marginLeft, viewportLeft + marginLeft);
      const y = Math.max(marginTop, viewportTop + marginTop);
      
      return { x, y };
    }

    function updateCanvasSize(){
      if(state.nodes.length === 0){
        return;
      }
      
      let maxX = 0;
      let maxY = 0;
      
      for(const node of state.nodes){
        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        const w = el ? el.offsetWidth : 300;
        const h = el ? el.offsetHeight : 200;
        maxX = Math.max(maxX, node.x + w);
        maxY = Math.max(maxY, node.y + h);
      }
      
      const minWidth = 10000;
      const minHeight = 10000;
      const padding = 1000;
      
      const newWidth = Math.max(minWidth, maxX + padding);
      const newHeight = Math.max(minHeight, maxY + padding);
      
      canvasEl.style.width = newWidth + 'px';
      canvasEl.style.height = newHeight + 'px';
      connectionsSvg.style.width = newWidth + 'px';
      connectionsSvg.style.height = newHeight + 'px';
      connectionsSvg.setAttribute('width', newWidth);
      connectionsSvg.setAttribute('height', newHeight);
    }

    function removeNode(id){
      const node = state.nodes.find(n => n.id === id);
      
      // 检查视频节点是否在时间轴中
      if(node && node.type === 'video'){
        const clipsInTimeline = state.timeline.clips.filter(c => c.nodeId === id);
        
        if(clipsInTimeline.length > 0){
          // 有片段在时间轴中，需要确认
          const confirmMsg = `该视频节点在时间轴中有 ${clipsInTimeline.length} 个片段，删除节点将同时删除这些片段。确定要删除吗？`;
          if(!confirm(confirmMsg)){
            return; // 用户取消删除
          }
          
          // 用户确认删除，移除时间轴中的所有相关片段
          state.timeline.clips = state.timeline.clips.filter(c => c.nodeId !== id);
          state.timeline.clips.forEach((c, index) => {
            c.order = index;
          });
          renderTimeline();
        }
        
        // 清理视频URL
        if(node.data && node.data.url){
          try{ URL.revokeObjectURL(node.data.url); } catch(e){}
        }
      }
      
      // 清除该节点相关的图片连接
      state.imageConnections = state.imageConnections.filter(c => c.from !== id && c.to !== id);
      
      // 清除该节点相关的首帧连接
      state.firstFrameConnections = state.firstFrameConnections.filter(c => c.from !== id && c.to !== id);
      
      // 清除该节点相关的视频连接
      state.videoConnections = state.videoConnections.filter(c => c.from !== id && c.to !== id);
      
      // 删除节点
      state.nodes = state.nodes.filter(n => n.id !== id);
      state.connections = state.connections.filter(c => c.from !== id && c.to !== id);
      const el = canvasEl.querySelector(`.node[data-node-id="${id}"]`);
      if(el) el.remove();
      if(state.selectedNodeId === id) state.selectedNodeId = null;
      renderConnections();
      renderMinimap();
      renderImageConnections();
      renderFirstFrameConnections();
      renderVideoConnections();
      
      // 自动保存
      try{ autoSaveWorkflow(); } catch(e){}
    }

