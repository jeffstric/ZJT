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
      renderReferenceConnections();
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
        if(typeof renderReferenceConnections === 'function') renderReferenceConnections();
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

    function focusOnNode(nodeId){
      const node = state.nodes.find(n => n.id === nodeId);
      if(!node) return;
      const el = canvasEl.querySelector(`.node[data-node-id="${nodeId}"]`);
      const nodeW = el ? el.offsetWidth : 300;
      const nodeH = el ? el.offsetHeight : 200;
      const containerRect = canvasContainer.getBoundingClientRect();
      const centerX = node.x + nodeW / 2;
      const centerY = node.y + nodeH / 2;
      state.panX = containerRect.width / 2 - centerX * state.zoom;
      state.panY = containerRect.height / 2 - centerY * state.zoom;
      applyTransform();
      setSelected(nodeId);
      bringNodeToFront(nodeId);
      renderConnections();
      renderImageConnections();
      renderFirstFrameConnections();
      renderVideoConnections();
      renderReferenceConnections();
      renderMinimap();
      // 添加闪烁动画提示
      if(el){
        el.style.transition = 'box-shadow 0.3s';
        el.style.boxShadow = '0 0 20px 6px rgba(59,130,246,0.7)';
        setTimeout(() => {
          el.style.boxShadow = '';
          setTimeout(() => { el.style.transition = ''; }, 300);
        }, 800);
      }
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
        if(typeof renderReferenceConnections === 'function') renderReferenceConnections();
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
        if(typeof renderReferenceConnections === 'function') renderReferenceConnections();
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
          if(typeof renderReferenceConnections === 'function') renderReferenceConnections();
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
        if(typeof renderReferenceConnections === 'function') renderReferenceConnections();
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

    function startNodePlacing(nodeId){
      // 先隐藏节点，等鼠标移动时再在鼠标位置显示
      const el = canvasEl.querySelector(`.node[data-node-id="${nodeId}"]`);
      if(el) el.style.visibility = 'hidden';
      // 延迟启动，避免当前菜单点击事件触发放置
      setTimeout(() => {
        state.placing = { nodeId: nodeId, visible: false };
        canvasContainer.classList.add('placing');
      }, 0);
    }

    function finalizeNodePlacing(){
      if(!state.placing) return;
      state.placing = null;
      canvasContainer.classList.remove('placing');
      renderMinimap();
      captureHistorySnapshot();
    }

    function getViewportNodePosition(){
      const containerRect = canvasContainer.getBoundingClientRect();
      const viewportWidth = containerRect.width / state.zoom;
      const viewportHeight = containerRect.height / state.zoom;
      const viewportLeft = -state.panX / state.zoom;
      const viewportTop = -state.panY / state.zoom;
      
      const marginLeft = 100;
      const marginTop = MIN_NODE_Y + 80;
      
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

    // 重新计算指定图生视频节点的算力显示
    function updateImageToVideoComputingPower(videoNodeId) {
      // 找到图生视频节点的元素
      const videoEl = canvasEl.querySelector(`.node[data-node-id="${videoNodeId}"]`);
      if(!videoEl) return;

      const videoNode = state.nodes.find(n => n.id === videoNodeId);
      if(!videoNode || videoNode.type !== 'image_to_video') return;

      // 尝试调用保存的函数
      if(videoEl._updateComputingPowerDisplay) {
        try {
          videoEl._updateComputingPowerDisplay();
          console.log(`[updateImageToVideoComputingPower] 成功更新节点 ${videoNodeId}`);
          return;
        } catch(e) {
          console.error(`[updateImageToVideoComputingPower] 调用保存的函数失败:`, e);
        }
      }

      // 备用方案：手动重新计算算力（如果无法调用保存的函数）
      if(!window.TaskConfig || !window.TaskConfig.isLoaded()) {
        console.log(`[updateImageToVideoComputingPower] TaskConfig未加载，跳过`);
        return;
      }

      try {
        const videoModel = videoNode.data.videoModel || 'sora2';
        const duration = videoNode.data.duration || 10;
        const imageMode = videoNode.data.imageMode || 'first_last_frame';

        // 构建context
        const context = {};
        if(imageMode === 'first_last_frame') {
          const hasStartFile = !!videoNode.data.startFile;
          const hasStartUrl = !!videoNode.data.startUrl;
          const hasStartConnection = state.imageConnections.some(c => c.to === videoNodeId && c.portType === 'start');
          const hasStartImage = hasStartFile || hasStartUrl || hasStartConnection;

          const hasEndFile = !!videoNode.data.endFile;
          const hasEndUrl = !!videoNode.data.endUrl;
          const hasEndConnection = state.imageConnections.some(c => c.to === videoNodeId && c.portType === 'end');
          const hasEndImage = hasEndFile || hasEndUrl || hasEndConnection;

          console.log(`[updateImageToVideoComputingPower] 节点${videoNodeId} - 计算算力:`, {
            hasStartImage, hasEndImage, imageMode
          });

          if(hasStartImage && hasEndImage) {
            context['image_mode'] = 'first_last_with_tail';
          } else {
            context['image_mode'] = 'first_last_frame';
          }
        } else {
          context['image_mode'] = imageMode;
        }

        // 获取算力
        const singlePower = window.TaskConfig.getComputingPower(videoModel, duration, context);
        const count = videoNode.data.drawCount || 1;
        const totalPower = singlePower * count;

        // 更新DOM
        const computingPowerValue = videoEl.querySelector('.computing-power-value');
        const computingPowerDetail = videoEl.querySelector('.computing-power-detail');

        if(computingPowerValue) {
          computingPowerValue.textContent = `${totalPower} 算力`;
          console.log(`[updateImageToVideoComputingPower] 节点${videoNodeId} 更新为 ${totalPower} 算力`);
        }
        if(computingPowerDetail) {
          computingPowerDetail.textContent = `单个 ${singlePower} 算力 × ${count} 个 = ${totalPower} 算力`;
        }
      } catch(e) {
        console.error(`[updateImageToVideoComputingPower] 手动计算失败:`, e);
      }
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
      // 如果删除的是图片节点，需要清除连接的图生视频节点的URL和更新算力
      if(node && node.type === 'image') {
        const imageConns = state.imageConnections.filter(c => c.from === id);
        const affectedVideoNodes = new Set();

        for(const conn of imageConns) {
          const targetNode = state.nodes.find(n => n.id === conn.to);
          if(targetNode && targetNode.type === 'image_to_video') {
            if(conn.portType === 'start') {
              targetNode.data.startUrl = '';
            } else if(conn.portType === 'end') {
              targetNode.data.endUrl = '';
            }
            affectedVideoNodes.add(conn.to);
            console.log(`[删除图片节点 ${id}] 清除图生视频节点 ${conn.to} 的 ${conn.portType} URL`);
          }
        }

        // 删除连接
        state.imageConnections = state.imageConnections.filter(c => c.from !== id && c.to !== id);

        // 更新所有受影响的图生视频节点的算力显示
        for(const videoNodeId of affectedVideoNodes) {
          updateImageToVideoComputingPower(videoNodeId);
        }
      } else {
        // 如果是其他类型的节点被删除，也需要清除图片连接（to = id）
        state.imageConnections = state.imageConnections.filter(c => c.from !== id && c.to !== id);
      }

      // 清除该节点相关的首帧连接
      state.firstFrameConnections = state.firstFrameConnections.filter(c => c.from !== id && c.to !== id);

      // 清除该节点相关的视频连接
      state.videoConnections = state.videoConnections.filter(c => c.from !== id && c.to !== id);

      // 清除该节点相关的参考连接
      const affectedNodes = new Set();
      state.referenceConnections.filter(c => c.from === id).forEach(c => affectedNodes.add(c.to));
      state.referenceConnections.filter(c => c.to === id).forEach(c => affectedNodes.add(c.to));
      state.referenceConnections = state.referenceConnections.filter(c => c.from !== id && c.to !== id);
      
      // 删除节点
      state.nodes = state.nodes.filter(n => n.id !== id);
      state.connections = state.connections.filter(c => c.from !== id && c.to !== id);
      const el = canvasEl.querySelector(`.node[data-node-id="${id}"]`);
      if(el) el.remove();
      if(state.selectedNodeId === id) state.selectedNodeId = null;
      
      // 更新受影响节点的参考图显示
      affectedNodes.forEach(nodeId => {
        const affectedNode = state.nodes.find(n => n.id === nodeId);
        if(affectedNode && affectedNode.updateReferenceImages){
          affectedNode.updateReferenceImages();
        }
      });
      
      renderConnections();
      renderMinimap();
      renderImageConnections();
      renderFirstFrameConnections();
      renderVideoConnections();
      renderReferenceConnections();
      
      // 自动保存
      try{ autoSaveWorkflow(); } catch(e){}
    }

