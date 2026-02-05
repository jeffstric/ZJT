    const addBtn = document.getElementById('addBtn');
    const addMenu = document.getElementById('addMenu');

    function applyFeedbackBtnState(isMinimized) {
        const wrapper = document.getElementById('feedbackBtnWrapper');
        const feedbackBtn = document.getElementById('feedbackBtn');
        const minimizeBtn = document.getElementById('feedbackMinimizeBtn');
        if (!wrapper || !feedbackBtn) return;

        wrapper.classList.toggle('minimized', !!isMinimized);
        if (minimizeBtn) {
            minimizeBtn.style.display = isMinimized ? 'none' : '';
        }

        feedbackBtn.textContent = isMinimized ? '?' : '意见反馈';
        feedbackBtn.setAttribute('aria-label', isMinimized ? '意见反馈（已最小化）' : '意见反馈');
        feedbackBtn.title = isMinimized ? '意见反馈' : '意见反馈';
    }

    // 最小化意见反馈按钮：变成一个很小的“?”
    function minimizeFeedbackBtn() {
        try {
            localStorage.setItem('feedbackBtnMinimized', 'true');
            localStorage.removeItem('feedbackBtnDeleted');
        } catch (e) {}
        applyFeedbackBtnState(true);
    }

    function restoreFeedbackBtn() {
        try {
            localStorage.setItem('feedbackBtnMinimized', 'false');
            localStorage.removeItem('feedbackBtnDeleted');
        } catch (e) {}
        applyFeedbackBtnState(false);
    }

    function handleFeedbackBtnClick(e) {
        if (e) {
            e.stopPropagation();
            e.preventDefault();
        }
        const minimized = (function () {
            try {
                return localStorage.getItem('feedbackBtnMinimized') === 'true';
            } catch (err) {
                return false;
            }
        })();
        if (minimized) {
            restoreFeedbackBtn();
        }
        const modal = document.getElementById('feedbackModal');
        if (modal) modal.classList.add('active');
    }

    function initFeedbackBtn() {
        let minimized = false;
        try {
            const legacyDeleted = localStorage.getItem('feedbackBtnDeleted') === 'true';
            const minimizedFlag = localStorage.getItem('feedbackBtnMinimized');
            minimized = legacyDeleted || minimizedFlag === 'true';
            if (legacyDeleted) {
                localStorage.setItem('feedbackBtnMinimized', 'true');
                localStorage.removeItem('feedbackBtnDeleted');
            }
        } catch (e) {}
        applyFeedbackBtnState(minimized);
    }

    // 页面加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initFeedbackBtn);
    } else {
        initFeedbackBtn();
    }

    // 上传配置
    let uploadConfig = {
      max_image_size_mb: 10 // 默认值
    };

    // 获取上传配置
    async function fetchUploadConfig() {
      try {
        const response = await fetch('/api/config/upload');
        const result = await response.json();
        if (result.code === 0 && result.data) {
          uploadConfig = result.data;
        }
      } catch (error) {
        console.error('获取上传配置失败:', error);
      }
    }

    // 页面加载时获取配置
    fetchUploadConfig();

    // 下载图片辅助函数
    async function downloadImage(imgUrl, fileName) {
      if (!imgUrl) {
        showToast('没有可下载的图片', 'error');
        return;
      }
      
      try {
        // 如果是 data URL、blob URL 或同源图片，直接下载
        if (imgUrl.startsWith('data:') || imgUrl.startsWith('blob:') || 
            (typeof isSameOriginUrl === 'function' && isSameOriginUrl(imgUrl))) {
          const a = document.createElement('a');
          a.href = imgUrl;
          a.download = fileName || 'image.png';
          a.style.display = 'none';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
        } else {
          // 跨域图片，使用 fetch+blob 方式下载
          const response = await fetch(typeof proxyImageUrl === 'function' ? proxyImageUrl(imgUrl) : imgUrl);
          const blob = await response.blob();
          const blobUrl = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = blobUrl;
          a.download = fileName || 'image.png';
          a.style.display = 'none';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(blobUrl);
        }
        showToast('开始下载图片', 'success');
      } catch (error) {
        console.error('下载图片失败:', error);
        showToast('下载图片失败', 'error');
      }
    }

    addBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      addMenu.classList.toggle('show');
    });

    document.getElementById('menuAddVideo').addEventListener('click', () => {
      createImageToVideoNode();
      renderMinimap();
      addMenu.classList.remove('show');
    });

    document.getElementById('menuAddVideoNode').addEventListener('click', () => {
      createVideoNode();
      renderMinimap();
      addMenu.classList.remove('show');
    });

    document.getElementById('menuAddImage').addEventListener('click', () => {
      createImageNode();
      renderMinimap();
      addMenu.classList.remove('show');
    });

    document.getElementById('menuAddScript').addEventListener('click', () => {
      createScriptNode();
      renderMinimap();
      addMenu.classList.remove('show');
    });

    document.getElementById('menuAddCharacter').addEventListener('click', () => {
      openCharacterModal();
      addMenu.classList.remove('show');
    });

    document.getElementById('menuAddLocation').addEventListener('click', () => {
      openLocationModal();
      addMenu.classList.remove('show');
    });

    document.getElementById('menuAddProps').addEventListener('click', () => {
      openPropsModal();
      addMenu.classList.remove('show');
    });

    document.getElementById('menuAddShotGroup').addEventListener('click', () => {
      const shotGroupData = {
        group_id: `grp_${Date.now()}`,
        group_name: '新分镜组',
        shots: []
      };
      createShotGroupNode(shotGroupData, null);
      renderMinimap();
      addMenu.classList.remove('show');
    });

    document.getElementById('menuAddTextToSpeech').addEventListener('click', () => {
      createTextToSpeechNode();
      renderMinimap();
      addMenu.classList.remove('show');
    });

    document.getElementById('menuAddDialogueGroup').addEventListener('click', () => {
      createDialogueGroupNode();
      renderMinimap();
      addMenu.classList.remove('show');
    });

    document.getElementById('menuAddText').addEventListener('click', () => {
      createTextNode();
      renderMinimap();
      addMenu.classList.remove('show');
    });

    // 点击其他地方关闭菜单
    document.addEventListener('click', (e) => {
      if(!e.target.closest('#addBtnContainer')){
        addMenu.classList.remove('show');
      }
    });

    ratioSelectEl.addEventListener('change', () => {
      state.ratio = ratioSelectEl.value;
    });

    // Ctrl键检测：进入/退出选择模式
    window.addEventListener('keydown', (e) => {
      if(e.key === 'Control' || e.key === 'Meta'){
        state.selectionMode = true;
        canvasContainer.style.cursor = 'crosshair';
      }
    });

    window.addEventListener('keyup', (e) => {
      if(e.key === 'Control' || e.key === 'Meta'){
        state.selectionMode = false;
        canvasContainer.style.cursor = 'grab';
      }
    });

    // 失去焦点时重置选择模式
    window.addEventListener('blur', () => {
      state.selectionMode = false;
      canvasContainer.style.cursor = 'grab';
    });

    canvasContainer.addEventListener('mousedown', (e) => {
      if(e.target === canvasEl || e.target === canvasContainer || e.target === canvasWorld){
        // 选择模式：开始绘制选择框
        if(state.selectionMode){
          const containerRect = canvasContainer.getBoundingClientRect();
          const startX = (e.clientX - containerRect.left - state.panX) / state.zoom;
          const startY = (e.clientY - containerRect.top - state.panY) / state.zoom;
          
          state.selecting = {
            startX: startX,
            startY: startY,
            currentX: startX,
            currentY: startY
          };
          
          // 创建选择框元素
          const selectionBox = document.createElement('div');
          selectionBox.id = 'selectionBox';
          selectionBox.className = 'selection-box';
          canvasEl.appendChild(selectionBox);
          
          return;
        }
        
        clearSelection();
        state.selectedConnId = null;
        state.selectedImgConnId = null;
        hideConnDeleteBtn();
        renderConnections();
        renderImageConnections();
        renderFirstFrameConnections();
        renderVideoConnections();
        renderReferenceConnections();
        // 开始平移画布
        state.panning = {
          startX: e.clientX,
          startY: e.clientY,
          origPanX: state.panX,
          origPanY: state.panY,
        };
        canvasContainer.classList.add('panning');
      }
    });

    // 删除按钮点击事件
    connDeleteBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if(state.selectedConnId !== null){
        removeConnection(state.selectedConnId);
      } else if(state.selectedImgConnId !== null){
        state.imageConnections = state.imageConnections.filter(c => c.id !== state.selectedImgConnId);
        state.selectedImgConnId = null;
        hideConnDeleteBtn();
        renderImageConnections();
      } else if(state.selectedFirstFrameConnId !== null){
        removeFirstFrameConnection(state.selectedFirstFrameConnId);
      } else if(state.selectedVideoConnId !== null){
        state.videoConnections = state.videoConnections.filter(c => c.id !== state.selectedVideoConnId);
        state.selectedVideoConnId = null;
        hideConnDeleteBtn();
        renderVideoConnections();
      } else if(state.selectedReferenceConnId !== null){
        const conn = state.referenceConnections.find(c => c.id === state.selectedReferenceConnId);
        state.referenceConnections = state.referenceConnections.filter(c => c.id !== state.selectedReferenceConnId);
        state.selectedReferenceConnId = null;
        hideConnDeleteBtn();
        renderReferenceConnections();
        // 更新目标节点的参考图显示
        if(conn){
          const targetNode = state.nodes.find(n => n.id === conn.to);
          if(targetNode && targetNode.updateReferenceImages){
            targetNode.updateReferenceImages();
          }
        }
        try{ autoSaveWorkflow(); } catch(e){}
      }
    });

    // Ctrl+Z 撤销
    window.addEventListener('keydown', (e) => {
      const isCtrl = e.ctrlKey || e.metaKey;
      if(!isCtrl) return;
      if(document.activeElement && (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA' || document.activeElement.isContentEditable)) return;
      if(e.key.toLowerCase() === 'z'){
        e.preventDefault();
        undoWorkflowChange();
      }
    });

    // 键盘删除连接线、时间轴片段和批量删除节点
    window.addEventListener('keydown', (e) => {
      if(e.key === 'Delete' || e.key === 'Backspace'){
        // 不在输入框内时才响应
        if(document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') return;
        
        if(state.selectedConnId !== null){
          e.preventDefault();
          removeConnection(state.selectedConnId);
        } else if(state.selectedImgConnId !== null){
          e.preventDefault();
          state.imageConnections = state.imageConnections.filter(c => c.id !== state.selectedImgConnId);
          state.selectedImgConnId = null;
          hideConnDeleteBtn();
          renderImageConnections();
        } else if(state.selectedFirstFrameConnId !== null){
          e.preventDefault();
          removeFirstFrameConnection(state.selectedFirstFrameConnId);
        } else if(state.selectedVideoConnId !== null){
          e.preventDefault();
          state.videoConnections = state.videoConnections.filter(c => c.id !== state.selectedVideoConnId);
          state.selectedVideoConnId = null;
          hideConnDeleteBtn();
          renderVideoConnections();
        } else if(state.selectedReferenceConnId !== null){
          e.preventDefault();
          const conn = state.referenceConnections.find(c => c.id === state.selectedReferenceConnId);
          state.referenceConnections = state.referenceConnections.filter(c => c.id !== state.selectedReferenceConnId);
          state.selectedReferenceConnId = null;
          hideConnDeleteBtn();
          renderReferenceConnections();
          // 更新目标节点的参考图显示
          if(conn){
            const targetNode = state.nodes.find(n => n.id === conn.to);
            if(targetNode && targetNode.updateReferenceImages){
              targetNode.updateReferenceImages();
            }
          }
          try{ autoSaveWorkflow(); } catch(e){}
        } else if(state.timeline.selectedClipId !== null){
          e.preventDefault();
          removeFromTimeline(state.timeline.selectedClipId);
          state.timeline.selectedClipId = null;
        } else if(state.selectedNodeIds.length > 0){
          e.preventDefault();
          // 批量删除节点
          const nodesToDelete = [...state.selectedNodeIds];
          if(confirm(`确定要删除选中的 ${nodesToDelete.length} 个节点吗？`)){
            nodesToDelete.forEach(nodeId => {
              removeNode(nodeId);
            });
            clearSelection();
          }
        }
      }
    });

    // 劫持浏览器缩放快捷键（Ctrl+/Ctrl- / Ctrl=）
    window.addEventListener('keydown', (e) => {
      const isCtrl = e.ctrlKey || e.metaKey;
      if(!isCtrl) return;
      // 不在输入框内时才响应
      if(document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') return;

      if(e.key === '+' || e.key === '=' ){
        e.preventDefault();
        zoomIn();
      } else if(e.key === '-'){
        e.preventDefault();
        zoomOut();
      }
    });

    // 劫持鼠标滚轮缩放（在画布区域内）
    canvasContainer.addEventListener('wheel', (e) => {
      // 仅当鼠标在画布区域内时生效
      // 允许正常滚动页面：当前页面没有滚动条，但仍做限定
      const isCtrl = e.ctrlKey || e.metaKey;
      // ctrl + wheel：浏览器默认会缩放页面，必须阻止
      if(isCtrl){
        e.preventDefault();
      }

      // 普通滚轮也作为画布缩放（用户需求）
      // 如果未来需要支持滚动，可把此判断改成 isCtrl
      e.preventDefault();

      if(e.deltaY < 0){
        zoomIn();
      } else if(e.deltaY > 0){
        zoomOut();
      }
    }, { passive: false });

    window.addEventListener('mousemove', (e) => {
      // 绘制选择框
      if(state.selecting){
        const containerRect = canvasContainer.getBoundingClientRect();
        const currentX = (e.clientX - containerRect.left - state.panX) / state.zoom;
        const currentY = (e.clientY - containerRect.top - state.panY) / state.zoom;
        
        state.selecting.currentX = currentX;
        state.selecting.currentY = currentY;
        
        const selectionBox = document.getElementById('selectionBox');
        if(selectionBox){
          const left = Math.min(state.selecting.startX, currentX);
          const top = Math.min(state.selecting.startY, currentY);
          const width = Math.abs(currentX - state.selecting.startX);
          const height = Math.abs(currentY - state.selecting.startY);
          
          selectionBox.style.left = left + 'px';
          selectionBox.style.top = top + 'px';
          selectionBox.style.width = width + 'px';
          selectionBox.style.height = height + 'px';
        }
        return;
      }
      
      // 平移画布
      if(state.panning){
        const zoom = state.zoom || 1;
        const dx = (e.clientX - state.panning.startX) / zoom;
        const dy = (e.clientY - state.panning.startY) / zoom;
        state.panX = Math.min(0, state.panning.origPanX + dx * zoom);
        state.panY = Math.min(0, state.panning.origPanY + dy * zoom);
        applyTransform();
        renderImageConnections();
        renderFirstFrameConnections();
        renderVideoConnections();
        renderReferenceConnections();
        // 更新删除按钮位置（如果有选中的连接线）
        if(state.selectedConnId !== null){
          renderConnections();
          renderImageConnections();
          renderFirstFrameConnections();
          renderVideoConnections();
          renderReferenceConnections();
        }
      }
      // 拖动节点（支持批量拖动）
      if(state.drag){
        const zoom = state.zoom || 1;
        const dx = (e.clientX - state.drag.startX) / zoom;
        const dy = (e.clientY - state.drag.startY) / zoom;
        
        // 如果拖动的节点在选中列表中，批量移动所有选中的节点
        if(state.selectedNodeIds.includes(state.drag.nodeId)){
          state.selectedNodeIds.forEach(nodeId => {
            const n = state.nodes.find(x => x.id === nodeId);
            if(!n) return;
            const origPos = state.drag.nodePositions[nodeId];
            if(!origPos) return;
            n.x = Math.max(20, origPos.x + dx);
            n.y = Math.max(20, origPos.y + dy);
            const el = canvasEl.querySelector(`.node[data-node-id="${n.id}"]`);
            if(el){
              el.style.left = n.x + 'px';
              el.style.top = n.y + 'px';
            }
          });
        } else {
          // 单个节点拖动
          const n = state.nodes.find(x => x.id === state.drag.nodeId);
          if(!n) return;
          n.x = Math.max(20, state.drag.origX + dx);
          n.y = Math.max(20, state.drag.origY + dy);
          const el = canvasEl.querySelector(`.node[data-node-id="${n.id}"]`);
          if(el){
            el.style.left = n.x + 'px';
            el.style.top = n.y + 'px';
          }
        }
        state.drag.moved = true;
        renderConnections();
        renderImageConnections();
        renderFirstFrameConnections();
        renderVideoConnections();
        renderReferenceConnections();
      }
      // 拖拽创建连接线时显示虚线预览
      if(state.connecting){
        const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
        const fromPos = getOutputPortPos(state.connecting.fromId);
        const containerRect = canvasContainer.getBoundingClientRect();
        const toX = (e.clientX - containerRect.left - state.panX) / state.zoom;
        const toY = (e.clientY - containerRect.top - state.panY) / state.zoom;
        
        let nearestPort = null;
        let nearestImgPort = null;
        let nearestDist = 50;
        
        // 如果从图片节点拖拽，查找图片输入端口和首帧端口
        let nearestFirstFramePort = null;
        if(fromNode && fromNode.type === 'image'){
          // 查找图生视频节点的图片端口
          for(const node of state.nodes){
            if(node.type !== 'image_to_video') continue;
            const toEl = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
            if(!toEl) continue;
            
            // 检查首帧端口
            if(!node.data.startFile){
              const startPort = toEl.querySelector('.start-image-port');
              if(startPort){
                const rect = startPort.getBoundingClientRect();
                const portX = (rect.left + rect.width/2 - containerRect.left - state.panX) / state.zoom;
                const portY = (rect.top + rect.height/2 - containerRect.top - state.panY) / state.zoom;
                const dist = Math.sqrt(Math.pow(toX - portX, 2) + Math.pow(toY - portY, 2));
                if(dist < nearestDist){
                  nearestDist = dist;
                  nearestImgPort = { nodeId: node.id, portType: 'start', x: portX, y: portY };
                }
              }
            }
            // 检查尾帧端口
            if(!node.data.endFile){
              const endPort = toEl.querySelector('.end-image-port');
              if(endPort){
                const rect = endPort.getBoundingClientRect();
                const portX = (rect.left + rect.width/2 - containerRect.left - state.panX) / state.zoom;
                const portY = (rect.top + rect.height/2 - containerRect.top - state.panY) / state.zoom;
                const dist = Math.sqrt(Math.pow(toX - portX, 2) + Math.pow(toY - portY, 2));
                if(dist < nearestDist){
                  nearestDist = dist;
                  nearestImgPort = { nodeId: node.id, portType: 'end', x: portX, y: portY };
                }
              }
            }
          }
          
          // 查找分镜节点的首帧端口
          let nearestFirstFrameDist = 50;
          for(const node of state.nodes){
            if(node.type !== 'shot_frame') continue;
            const toEl = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
            if(!toEl) continue;
            const portEl = toEl.querySelector('.first-frame-port');
            if(!portEl) continue;
            const rect = portEl.getBoundingClientRect();
            const portX = (rect.left + rect.width/2 - containerRect.left - state.panX) / state.zoom;
            const portY = (rect.top + rect.height/2 - containerRect.top - state.panY) / state.zoom;
            const dist = Math.sqrt(Math.pow(toX - portX, 2) + Math.pow(toY - portY, 2));
            if(dist < nearestFirstFrameDist){
              nearestFirstFrameDist = dist;
              nearestFirstFramePort = { nodeId: node.id, x: portX, y: portY };
            }
          }
        }

        
        // 如果从图生视频节点拖拽，查找视频节点输入端口
        // 如果从剧本节点拖拽，查找分镜组节点输入端口
        // 如果从角色节点拖拽，查找视频节点输入端口
        if(fromNode && (fromNode.type === 'image_to_video' || fromNode.type === 'script' || fromNode.type === 'character')){
          let nearestPort = null;
          let nearestDist = 50;
          const targetType = fromNode.type === 'script' ? 'shot_group' : 'video';
          for(const node of state.nodes){
            if(node.type !== targetType) continue;
            const toEl = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
            if(!toEl) continue;
            const portEl = toEl.querySelector('.port.input');
            if(!portEl) continue;
            const rect = portEl.getBoundingClientRect();
            const portX = (rect.left + rect.width/2 - containerRect.left - state.panX) / state.zoom;
            const portY = (rect.top + rect.height/2 - containerRect.top - state.panY) / state.zoom;
            const dist = Math.sqrt(Math.pow(toX - portX, 2) + Math.pow(toY - portY, 2));
            if(dist < nearestDist){
              nearestDist = dist;
              nearestPort = { nodeId: node.id, x: portX, y: portY };
            }
          }
        }
        
        // 如果从视频节点拖拽，查找对话组节点的视频输入端口
        let nearestVideoInputPort = null;
        if(fromNode && fromNode.type === 'video'){
          let nearestVideoDist = 50;
          for(const node of state.nodes){
            if(node.type !== 'dialogue_group') continue;
            const toEl = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
            if(!toEl) continue;
            const portEl = toEl.querySelector('.port.video-input-port');
            if(!portEl || portEl.classList.contains('disabled')) continue;
            const rect = portEl.getBoundingClientRect();
            const portX = (rect.left + rect.width/2 - containerRect.left - state.panX) / state.zoom;
            const portY = (rect.top + rect.height/2 - containerRect.top - state.panY) / state.zoom;
            const dist = Math.sqrt(Math.pow(toX - portX, 2) + Math.pow(toY - portY, 2));
            if(dist < nearestVideoDist){
              nearestVideoDist = dist;
              nearestVideoInputPort = { nodeId: node.id, x: portX, y: portY };
            }
          }
        }
        
        // 更新图片端口高亮状态
        for(const portEl of canvasEl.querySelectorAll('.start-image-port, .end-image-port')){
          const nodeEl = portEl.closest('.node');
          const nodeId = nodeEl ? Number(nodeEl.dataset.nodeId) : null;
          const portType = portEl.classList.contains('start-image-port') ? 'start' : 'end';
          const isNearest = nearestImgPort && nearestImgPort.nodeId === nodeId && nearestImgPort.portType === portType;
          portEl.classList.toggle('can-connect', isNearest);
        }

        // 更新视频输入端口高亮状态
        for(const portEl of canvasEl.querySelectorAll('.port.input')){
          const nodeEl = portEl.closest('.node');
          const nodeId = nodeEl ? Number(nodeEl.dataset.nodeId) : null;
          const isNearest = nearestPort && nearestPort.nodeId === nodeId;
          portEl.classList.toggle('can-connect', isNearest);
        }
        
        // 更新首帧端口高亮状态
        for(const portEl of canvasEl.querySelectorAll('.first-frame-port')){
          const nodeEl = portEl.closest('.node');
          const nodeId = nodeEl ? Number(nodeEl.dataset.nodeId) : null;
          const isNearest = nearestFirstFramePort && nearestFirstFramePort.nodeId === nodeId;
          portEl.classList.toggle('can-connect', isNearest);
        }
        
        // 更新视频输入端口高亮状态
        for(const portEl of canvasEl.querySelectorAll('.port.video-input-port')){
          const nodeEl = portEl.closest('.node');
          const nodeId = nodeEl ? Number(nodeEl.dataset.nodeId) : null;
          const isNearest = nearestVideoInputPort && nearestVideoInputPort.nodeId === nodeId;
          portEl.classList.toggle('can-connect', isNearest);
        }
        
        // 如果找到最近端口，虚线吸附到该端口
        let targetX = toX, targetY = toY;
        if(nearestImgPort){
          targetX = nearestImgPort.x;
          targetY = nearestImgPort.y;
        }
        if(nearestPort){
          targetX = nearestPort.x;
          targetY = nearestPort.y;
        }
        if(nearestFirstFramePort){
          targetX = nearestFirstFramePort.x;
          targetY = nearestFirstFramePort.y;
        }
        if(nearestVideoInputPort){
          targetX = nearestVideoInputPort.x;
          targetY = nearestVideoInputPort.y;
        }
        
        renderConnections({
          fromX: fromPos.x,
          fromY: fromPos.y,
          toX: targetX,
          toY: targetY
        });
        renderImageConnections();
        renderFirstFrameConnections();
        renderVideoConnections();
        renderReferenceConnections();
      }
    });

    window.addEventListener('mouseup', (e) => {
      // 完成选择框绘制
      if(state.selecting){
        const selectionBox = document.getElementById('selectionBox');
        if(selectionBox){
          const left = Math.min(state.selecting.startX, state.selecting.currentX);
          const top = Math.min(state.selecting.startY, state.selecting.currentY);
          const right = Math.max(state.selecting.startX, state.selecting.currentX);
          const bottom = Math.max(state.selecting.startY, state.selecting.currentY);
          
          // 查找选择框内的节点
          const selectedIds = [];
          for(const node of state.nodes){
            const nodeEl = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
            if(!nodeEl) continue;
            
            const nodeRight = node.x + nodeEl.offsetWidth;
            const nodeBottom = node.y + nodeEl.offsetHeight;
            
            // 检查节点是否与选择框相交
            if(node.x < right && nodeRight > left && node.y < bottom && nodeBottom > top){
              selectedIds.push(node.id);
            }
          }
          
          // 更新选中状态
          if(selectedIds.length > 0){
            setMultipleSelected(selectedIds);
          }
          
          selectionBox.remove();
        }
        state.selecting = null;
        return;
      }
      
      if(state.drag){
        const moved = state.drag.moved;
        state.drag = null;
        renderMinimap();
        if(moved){
          captureHistorySnapshot();
        }
      }
      if(state.panning){
        state.panning = null;
        canvasContainer.classList.remove('panning');
        renderMinimap();
      }
      if(state.connecting){
        const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
        const containerRect = canvasContainer.getBoundingClientRect();
        const mouseX = (e.clientX - containerRect.left - state.panX) / state.zoom;
        const mouseY = (e.clientY - containerRect.top - state.panY) / state.zoom;
        
        // 如果从图片节点拖拽，查找图片输入端口、分镜节点输入端口和参考端口
        if(fromNode && fromNode.type === 'image'){
          let nearestImgPort = null;
          let nearestShotFramePort = null;
          let nearestReferencePort = null;
          let nearestImgDist = 50;
          let nearestShotFrameDist = 50;
          let nearestReferenceDist = 50;
          
          // 查找其他图片节点的参考端口
          for(const node of state.nodes){
            if(node.type !== 'image' || node.id === fromNode.id) continue;
            const toEl = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
            if(!toEl) continue;
            const portEl = toEl.querySelector('.port.reference');
            if(!portEl) continue;
            const rect = portEl.getBoundingClientRect();
            const portX = (rect.left + rect.width/2 - containerRect.left - state.panX) / state.zoom;
            const portY = (rect.top + rect.height/2 - containerRect.top - state.panY) / state.zoom;
            const dist = Math.sqrt(Math.pow(mouseX - portX, 2) + Math.pow(mouseY - portY, 2));
            if(dist < nearestReferenceDist){
              nearestReferenceDist = dist;
              nearestReferencePort = { nodeId: node.id, node: node };
            }
          }
          
          // 查找图生视频节点的图片端口
          for(const node of state.nodes){
            if(node.type !== 'image_to_video') continue;
            const toEl = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
            if(!toEl) continue;
            
            // 检查首帧端口
            if(!node.data.startFile){
              const startPort = toEl.querySelector('.start-image-port');
              if(startPort){
                const rect = startPort.getBoundingClientRect();
                const portX = (rect.left + rect.width/2 - containerRect.left - state.panX) / state.zoom;
                const portY = (rect.top + rect.height/2 - containerRect.top - state.panY) / state.zoom;
                const dist = Math.sqrt(Math.pow(mouseX - portX, 2) + Math.pow(mouseY - portY, 2));
                if(dist < nearestImgDist){
                  nearestImgDist = dist;
                  nearestImgPort = { nodeId: node.id, portType: 'start' };
                }
              }
            }
            // 检查尾帧端口
            if(!node.data.endFile){
              const endPort = toEl.querySelector('.end-image-port');
              if(endPort){
                const rect = endPort.getBoundingClientRect();
                const portX = (rect.left + rect.width/2 - containerRect.left - state.panX) / state.zoom;
                const portY = (rect.top + rect.height/2 - containerRect.top - state.panY) / state.zoom;
                const dist = Math.sqrt(Math.pow(mouseX - portX, 2) + Math.pow(mouseY - portY, 2));
                if(dist < nearestImgDist){
                  nearestImgDist = dist;
                  nearestImgPort = { nodeId: node.id, portType: 'end' };
                }
              }
            }
          }
          
          // 查找分镜节点的首帧端口（蓝色端口）
          let nearestFirstFramePort = null;
          let nearestFirstFrameDist = 50;
          for(const node of state.nodes){
            if(node.type !== 'shot_frame') continue;
            const toEl = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
            if(!toEl) continue;
            const portEl = toEl.querySelector('.first-frame-port');
            if(!portEl) continue;
            const rect = portEl.getBoundingClientRect();
            const portX = (rect.left + rect.width/2 - containerRect.left - state.panX) / state.zoom;
            const portY = (rect.top + rect.height/2 - containerRect.top - state.panY) / state.zoom;
            const dist = Math.sqrt(Math.pow(mouseX - portX, 2) + Math.pow(mouseY - portY, 2));
            if(dist < nearestFirstFrameDist){
              nearestFirstFrameDist = dist;
              nearestFirstFramePort = { nodeId: node.id, node: node };
            }
          }
          
          // 优先连接到最近的端口
          const minDist = Math.min(nearestImgDist, nearestFirstFrameDist, nearestReferenceDist);
          
          if(nearestReferencePort && nearestReferenceDist === minDist){
            // 连接到图片节点的参考端口
            const exists = state.referenceConnections.some(c => c.from === state.connecting.fromId && c.to === nearestReferencePort.nodeId);
            if(!exists){
              // 检查循环引用
              function hasCircularReference(fromId, toId){
                const visited = new Set();
                function dfs(currentId){
                  if(currentId === fromId) return true;
                  if(visited.has(currentId)) return false;
                  visited.add(currentId);
                  const outgoing = state.referenceConnections.filter(c => c.from === currentId);
                  for(const conn of outgoing){
                    if(dfs(conn.to)) return true;
                  }
                  return false;
                }
                return dfs(toId);
              }
              
              if(hasCircularReference(state.connecting.fromId, nearestReferencePort.nodeId)){
                showToast('不能创建循环参考', 'error');
              } else {
                // 检查参考图数量限制
                const currentRefCount = state.referenceConnections.filter(c => c.to === nearestReferencePort.nodeId).length;
                const maxRefs = nearestReferencePort.node.data.model === 'gemini-3-pro-image-preview' ? 13 : 5;
                if(currentRefCount >= maxRefs){
                  showToast(`最多支持${maxRefs}张参考图`, 'error');
                } else {
                  state.referenceConnections.push({
                    id: state.nextReferenceConnId++,
                    from: state.connecting.fromId,
                    to: nearestReferencePort.nodeId
                  });
                  // 更新目标节点的参考图显示
                  if(nearestReferencePort.node.updateReferenceImages){
                    nearestReferencePort.node.updateReferenceImages();
                  }
                  renderReferenceConnections();
                  try{ autoSaveWorkflow(); } catch(e){}
                }
              }
            }
          } else if(nearestImgPort && nearestImgDist === minDist){
            // 连接到图生视频节点
            const exists = state.imageConnections.some(c => c.to === nearestImgPort.nodeId && c.portType === nearestImgPort.portType);
            if(!exists){
              state.imageConnections.push({
                id: state.nextImgConnId++,
                from: state.connecting.fromId,
                to: nearestImgPort.nodeId,
                portType: nearestImgPort.portType
              });
            }
          } else if(nearestFirstFramePort && nearestFirstFrameDist === minDist){
            // 连接到分镜节点的首帧端口
            const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
            if(fromNode && fromNode.data.url){
              // 删除该分镜节点的旧首帧连接
              state.firstFrameConnections = state.firstFrameConnections.filter(c => c.to !== nearestFirstFramePort.nodeId);
              
              // 创建新的首帧连接
              state.firstFrameConnections.push({
                id: state.nextFirstFrameConnId++,
                from: state.connecting.fromId,
                to: nearestFirstFramePort.nodeId
              });
              
              // 更新视频首帧
              nearestFirstFramePort.node.data.previewImageUrl = fromNode.data.url;
              const nodeEl = canvasEl.querySelector(`.node[data-node-id="${nearestFirstFramePort.nodeId}"]`);
              if(nodeEl){
                const previewImageEl = nodeEl.querySelector('.shot-frame-preview-image');
                const previewFieldEl = nodeEl.querySelector('.shot-frame-preview-field');
                if(previewImageEl){
                  previewImageEl.src = proxyImageUrl(fromNode.data.url);
                  previewImageEl.style.display = 'block';
                }
                if(previewFieldEl){
                  previewFieldEl.style.display = 'block';
                }
              }
              
              renderFirstFrameConnections();
              try{ autoSaveWorkflow(); } catch(e){}
            }
          }
        }

        // 如果从图生视频节点拖拽，查找视频节点输入端口
        if(fromNode && fromNode.type === 'image_to_video'){
          let nearestPort = null;
          let nearestDist = 50;
          for(const node of state.nodes){
            if(node.type !== 'video') continue;
            const toEl = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
            if(!toEl) continue;
            const portEl = toEl.querySelector('.port.input');
            if(!portEl) continue;
            const rect = portEl.getBoundingClientRect();
            const portX = (rect.left + rect.width/2 - containerRect.left - state.panX) / state.zoom;
            const portY = (rect.top + rect.height/2 - containerRect.top - state.panY) / state.zoom;
            const dist = Math.sqrt(Math.pow(mouseX - portX, 2) + Math.pow(mouseY - portY, 2));
            if(dist < nearestDist){
              nearestDist = dist;
              nearestPort = { nodeId: node.id };
            }
          }

          if(nearestPort){
            const exists = state.connections.some(c => c.from === state.connecting.fromId && c.to === nearestPort.nodeId);
            if(!exists){
              state.connections.push({
                id: state.nextConnId++,
                from: state.connecting.fromId,
                to: nearestPort.nodeId
              });
              
              // 如果连接涉及角色节点，更新角色卡按钮状态
              const sourceNode = state.nodes.find(n => n.id === state.connecting.fromId);
              if(sourceNode && sourceNode.type === 'character'){
                updateCharacterCardButtonState(state.connecting.fromId);
              }
            }
          }
        }
        
        // 如果从视频节点拖拽，查找对话组节点的视频输入端口
        if(fromNode && fromNode.type === 'video'){
          let nearestVideoInputPort = null;
          let nearestVideoDist = 50;
          for(const node of state.nodes){
            if(node.type !== 'dialogue_group') continue;
            const toEl = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
            if(!toEl) continue;
            const portEl = toEl.querySelector('.port.video-input-port');
            if(!portEl || portEl.classList.contains('disabled')) continue;
            const rect = portEl.getBoundingClientRect();
            const portX = (rect.left + rect.width/2 - containerRect.left - state.panX) / state.zoom;
            const portY = (rect.top + rect.height/2 - containerRect.top - state.panY) / state.zoom;
            const dist = Math.sqrt(Math.pow(mouseX - portX, 2) + Math.pow(mouseY - portY, 2));
            if(dist < nearestVideoDist){
              nearestVideoDist = dist;
              nearestVideoInputPort = { nodeId: node.id };
            }
          }
          
          if(nearestVideoInputPort){
            const exists = state.videoConnections.some(c => c.from === state.connecting.fromId && c.to === nearestVideoInputPort.nodeId);
            if(!exists){
              // 检查目标对话组节点是否已经有视频连接
              const existingConn = state.videoConnections.find(c => c.to === nearestVideoInputPort.nodeId);
              if(existingConn){
                showToast('该对话组节点已有视频连接，一个对话组只能连接一个情感参考视频', 'warning');
              } else {
                state.videoConnections.push({
                  id: state.nextVideoConnId++,
                  from: state.connecting.fromId,
                  to: nearestVideoInputPort.nodeId
                });
                renderVideoConnections();
                showToast('视频已连接作为情感参考', 'success');
                try{ autoSaveWorkflow(); } catch(e){}
              }
            }
          } else {
            // 检查是否有对话组节点但端口被禁用
            const hasDisabledPort = state.nodes.some(node => {
              if(node.type !== 'dialogue_group') return false;
              const toEl = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
              if(!toEl) return false;
              const portEl = toEl.querySelector('.port.video-input-port');
              return portEl && portEl.classList.contains('disabled');
            });
            if(hasDisabledPort){
              showToast('请先将对话组节点的“情感控制方式”切换为“使用情感参考音频”', 'warning');
            }
          }
        }

        
        // 清除所有端口高亮
        for(const portEl of canvasEl.querySelectorAll('.can-connect')){
          portEl.classList.remove('can-connect');
        }
        
        state.connecting = null;
        renderConnections();
        renderImageConnections();
        renderFirstFrameConnections();
        renderVideoConnections();
        renderReferenceConnections();
      }
    });

    // 缩放按钮事件
    zoomInBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      zoomIn();
    });

    zoomOutBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      zoomOut();
    });

    // 缩略图点击导航
    minimap.addEventListener('mousedown', (e) => {
      e.stopPropagation();
      if(!state.minimapState || state.nodes.length === 0) return;
      
      const rect = minimapContent.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const clickY = e.clientY - rect.top;
      
      const { minX, minY, scale } = state.minimapState;
      const containerRect = canvasContainer.getBoundingClientRect();
      
      // 计算点击位置对应的画布坐标
      const canvasX = (clickX - MINIMAP_PADDING) / scale + minX;
      const canvasY = (clickY - MINIMAP_PADDING) / scale + minY;
      
      // 将该位置移动到视口中心
      state.panX = Math.min(0, -(canvasX - containerRect.width / state.zoom / 2) * state.zoom);
      state.panY = Math.min(0, -(canvasY - containerRect.height / state.zoom / 2) * state.zoom);
      
      applyTransform();
      renderConnections();
      renderImageConnections();
      renderFirstFrameConnections();
      renderVideoConnections();
      renderReferenceConnections();
      renderMinimap();
    });

    // 保存按钮点击事件
    document.getElementById('saveBtn').addEventListener('click', (e) => {
      e.stopPropagation();
      saveWorkflow();
    });

    // 时间轴控制按钮事件
    document.getElementById('timelineToggleBtn').addEventListener('click', (e) => {
      e.stopPropagation();
      state.timeline.visible = false;
      renderTimeline();
      document.getElementById('timelineExpandBtn').style.display = 'flex';
    });

    document.getElementById('timelineExpandBtn').addEventListener('click', (e) => {
      e.stopPropagation();
      state.timeline.visible = true;
      renderTimeline();
    });

    document.getElementById('timelineClearBtn').addEventListener('click', (e) => {
      e.stopPropagation();
      if(confirm('确定要清空时间轴吗？')){
        state.timeline.clips = [];
        state.timeline.audioClips = [];
        state.timeline.selectedClipId = null;
        state.timeline.selectedAudioClipId = null;
        // 清空柱子中的片段引用
        state.timeline.pillars.forEach(pillar => {
          pillar.videoClipIds = [];
          pillar.audioClipIds = [];
        });
        renderTimeline();
        showToast('时间轴已清空', 'success');
        try{ autoSaveWorkflow(); } catch(e){}
      }
    });

    document.getElementById('timelineExportDraftBtn').addEventListener('click', (e) => {
      e.stopPropagation();
      exportTimelineToDraft();
    });

    // ========== 角色和场景选择功能 ==========
    
    // 打开角色选择模态框
    async function openCharacterModal() {
      const modal = document.getElementById('characterModal');
      const worldSelect = document.getElementById('characterWorldSelect');
      
      // 加载世界列表
      await loadWorldsToSelect(worldSelect);
      
      // 如果有默认世界，自动选择并加载角色
      if (state.defaultWorldId) {
        worldSelect.value = state.defaultWorldId;
        await loadCharacters(state.defaultWorldId);
      }
      
      modal.classList.add('show');
      modal.setAttribute('aria-hidden', 'false');
    }
    
    // 打开场景选择模态框
    async function openLocationModal() {
      const modal = document.getElementById('locationModal');
      const worldSelect = document.getElementById('locationWorldSelect');
      
      // 加载世界列表
      await loadWorldsToSelect(worldSelect);
      
      // 如果有默认世界，自动选择并加载场景
      if (state.defaultWorldId) {
        worldSelect.value = state.defaultWorldId;
        await loadLocations(state.defaultWorldId);
      }
      
      modal.classList.add('show');
      modal.setAttribute('aria-hidden', 'false');
    }
    
    // 打开道具选择模态框
    async function openPropsModal() {
      const modal = document.getElementById('propsModal');
      const worldSelect = document.getElementById('propsWorldSelect');
      
      // 加载世界列表
      await loadWorldsToSelect(worldSelect);
      
      // 如果有默认世界，自动选择并加载道具
      if (state.defaultWorldId) {
        worldSelect.value = state.defaultWorldId;
        await loadProps(state.defaultWorldId);
      }
      
      modal.classList.add('show');
      modal.setAttribute('aria-hidden', 'false');
    }
    
    // 为分镜选择道具打开模态框（供 nodes.js 调用）
    window.openPropsModalForShot = async function() {
      const modal = document.getElementById('propsModal');
      const worldSelect = document.getElementById('propsWorldSelect');
      
      // 加载世界列表
      await loadWorldsToSelect(worldSelect);
      
      // 如果有默认世界，自动选择并加载道具
      if (state.defaultWorldId) {
        worldSelect.value = state.defaultWorldId;
        await loadProps(state.defaultWorldId);
      }
      
      modal.classList.add('show');
      modal.setAttribute('aria-hidden', 'false');
    };
    
    // 加载世界列表到选择器
    async function loadWorldsToSelect(selectElement) {
      const authToken = getAuthToken();
      const userId = getUserId();
      
      if (!authToken || !userId) {
        showToast('请先登录后再操作', 'error');
        return;
      }
      
      try {
        const response = await fetch('/api/worlds?page=1&page_size=100', {
          headers: {
            'Authorization': authToken,
            'X-User-Id': userId
          }
        });
        
        const result = await response.json();
        
        if (result.code === 0 && result.data && result.data.data) {
          selectElement.innerHTML = '<option value="">请选择世界...</option>';
          result.data.data.forEach(world => {
            const option = document.createElement('option');
            option.value = world.id;
            option.textContent = world.name;
            selectElement.appendChild(option);
          });
        } else if (result.code === -1 && result.message === 'user_id is required') {
          showToast('登录状态已失效，请重新登录', 'error');
        }
      } catch (error) {
        console.error('加载世界列表失败:', error);
        showToast('加载世界列表失败', 'error');
      }
    }
    
    // 加载角色列表
    async function loadCharacters(worldId, keyword = '') {
      const authToken = getAuthToken();
      const userId = getUserId();
      
      if (!authToken || !userId) {
        showToast('请先登录后再操作', 'error');
        document.getElementById('characterModal')?.classList.remove('show');
        return;
      }
      
      const listEl = document.getElementById('characterList');
      
      if (!worldId) {
        listEl.innerHTML = '<div style="text-align: center; color: #9ca3af; padding: 40px 20px;">请先选择世界</div>';
        return;
      }
      
      listEl.innerHTML = '<div style="text-align: center; color: #9ca3af; padding: 40px 20px;">加载中...</div>';
      
      try {
        const url = new URL('/api/characters', window.location.origin);
        url.searchParams.append('world_id', worldId);
        if (keyword) url.searchParams.append('keyword', keyword);
        
        const response = await fetch(url, {
          headers: {
            'Authorization': authToken,
            'X-User-Id': userId
          }
        });
        
        const result = await response.json();
        
        if (result.code === 0 && result.data && result.data.data) {
          if (result.data.data.length === 0) {
            listEl.innerHTML = '<div style="text-align: center; color: #9ca3af; padding: 40px 20px;">暂无角色</div>';
            return;
          }
          
          listEl.innerHTML = result.data.data.map(character => `
            <div class="character-item" data-character-id="${character.id}" style="padding: 12px; border: 1px solid #e5e7eb; border-radius: 8px; margin-bottom: 10px; cursor: pointer; transition: all 0.15s;">
              <div style="display: flex; gap: 12px; align-items: start;">
                ${character.reference_image ? `<img src="${character.reference_image}" style="width: 60px; height: 60px; object-fit: cover; border-radius: 6px; border: 1px solid #e5e7eb;" />` : '<div style="width: 60px; height: 60px; background: #f3f4f6; border-radius: 6px; display: flex; align-items: center; justify-content: center; color: #9ca3af; font-size: 12px;">无图片</div>'}
                <div style="flex: 1;">
                  <div style="font-weight: 700; font-size: 14px; margin-bottom: 4px;">${escapeHtml(character.name)}</div>
                  ${character.age ? `<div style="font-size: 12px; color: #666; margin-bottom: 2px;">年龄: ${escapeHtml(character.age)}</div>` : ''}
                  ${character.identity ? `<div style="font-size: 12px; color: #666;">${escapeHtml(character.identity)}</div>` : ''}
                </div>
              </div>
            </div>
          `).join('');
          
          // 添加点击事件
          listEl.querySelectorAll('.character-item').forEach(item => {
            item.addEventListener('click', () => {
              const characterId = item.dataset.characterId;
              const character = result.data.data.find(c => c.id == characterId);
              if (character) {
                createCharacterNode(character);
                document.getElementById('characterModal').classList.remove('show');
                renderMinimap();
              }
            });
            
            item.addEventListener('mouseenter', () => {
              item.style.background = '#f8fafc';
              item.style.borderColor = '#22c55e';
            });
            
            item.addEventListener('mouseleave', () => {
              item.style.background = '';
              item.style.borderColor = '#e5e7eb';
            });
          });
        }
      } catch (error) {
        console.error('加载角色列表失败:', error);
        listEl.innerHTML = '<div style="text-align: center; color: #ef4444; padding: 40px 20px;">加载失败</div>';
      }
    }
    
    // 加载场景列表
    async function loadLocations(worldId, keyword = '') {
      const authToken = getAuthToken();
      const userId = getUserId();
      
      if (!authToken || !userId) {
        showToast('请先登录后再操作', 'error');
        document.getElementById('locationModal')?.classList.remove('show');
        return;
      }
      
      const listEl = document.getElementById('locationList');
      
      if (!worldId) {
        listEl.innerHTML = '<div style="text-align: center; color: #9ca3af; padding: 40px 20px;">请先选择世界</div>';
        return;
      }
      
      listEl.innerHTML = '<div style="text-align: center; color: #9ca3af; padding: 40px 20px;">加载中...</div>';
      
      try {
        const url = new URL('/api/locations', window.location.origin);
        url.searchParams.append('world_id', worldId);
        if (keyword) url.searchParams.append('keyword', keyword);
        
        const response = await fetch(url, {
          headers: {
            'Authorization': authToken,
            'X-User-Id': userId
          }
        });
        
        const result = await response.json();
        
        if (result.code === 0 && result.data && result.data.data) {
          if (result.data.data.length === 0) {
            listEl.innerHTML = '<div style="text-align: center; color: #9ca3af; padding: 40px 20px;">暂无场景</div>';
            return;
          }
          
          listEl.innerHTML = result.data.data.map(location => `
            <div class="location-item" data-location-id="${location.id}" style="padding: 12px; border: 1px solid #e5e7eb; border-radius: 8px; margin-bottom: 10px; cursor: pointer; transition: all 0.15s;">
              <div style="display: flex; gap: 12px; align-items: start;">
                ${location.reference_image ? `<img src="${location.reference_image}" style="width: 80px; height: 60px; object-fit: cover; border-radius: 6px; border: 1px solid #e5e7eb;" />` : '<div style="width: 80px; height: 60px; background: #f3f4f6; border-radius: 6px; display: flex; align-items: center; justify-content: center; color: #9ca3af; font-size: 12px;">无图片</div>'}
                <div style="flex: 1;">
                  <div style="font-weight: 700; font-size: 14px; margin-bottom: 4px;">${escapeHtml(location.name)}</div>
                  ${location.description ? `<div style="font-size: 12px; color: #666; line-height: 1.4;">${escapeHtml(location.description.slice(0, 100))}${location.description.length > 100 ? '...' : ''}</div>` : ''}
                </div>
              </div>
            </div>
          `).join('');
          
          // 添加点击事件
          listEl.querySelectorAll('.location-item').forEach(item => {
            item.addEventListener('click', () => {
              const locationId = item.dataset.locationId;
              const location = result.data.data.find(l => l.id == locationId);
              if (location) {
                // 检查是否有分镜选择上下文（从 nodes.js 传递过来）
                if (window.currentLocationSelectionContext) {
                  // 调用 nodes.js 中的 selectLocation 函数来更新分镜数据
                  if (typeof window.selectLocation === 'function') {
                    window.selectLocation(location);
                  }
                } else {
                  // 没有上下文，创建场景节点
                  createLocationNode(location);
                  document.getElementById('locationModal').classList.remove('show');
                  renderMinimap();
                }
              }
            });
            
            item.addEventListener('mouseenter', () => {
              item.style.background = '#f8fafc';
              item.style.borderColor = '#22c55e';
            });
            
            item.addEventListener('mouseleave', () => {
              item.style.background = '';
              item.style.borderColor = '#e5e7eb';
            });
          });
        }
      } catch (error) {
        console.error('加载场景列表失败:', error);
        listEl.innerHTML = '<div style="text-align: center; color: #ef4444; padding: 40px 20px;">加载失败</div>';
      }
    }
    
    // 加载道具列表
    async function loadProps(worldId, keyword = '') {
      const authToken = getAuthToken();
      const userId = getUserId();
      
      if (!authToken || !userId) {
        showToast('请先登录后再操作', 'error');
        document.getElementById('propsModal')?.classList.remove('show');
        return;
      }
      
      const listEl = document.getElementById('propsList');
      
      if (!worldId) {
        listEl.innerHTML = '<div style="text-align: center; color: #9ca3af; padding: 40px 20px;">请先选择世界</div>';
        return;
      }
      
      listEl.innerHTML = '<div style="text-align: center; color: #9ca3af; padding: 40px 20px;">加载中...</div>';
      
      try {
        const url = new URL('/api/props', window.location.origin);
        url.searchParams.append('world_id', worldId);
        if (keyword) url.searchParams.append('keyword', keyword);
        
        const response = await fetch(url, {
          headers: {
            'Authorization': authToken,
            'X-User-Id': userId
          }
        });
        
        const result = await response.json();
        
        if (result.code === 0 && result.data && result.data.data) {
          if (result.data.data.length === 0) {
            listEl.innerHTML = '<div style="text-align: center; color: #9ca3af; padding: 40px 20px;">暂无道具</div>';
            return;
          }
          
          listEl.innerHTML = result.data.data.map(props => `
            <div class="props-item" data-props-id="${props.id}" style="padding: 12px; border: 1px solid #e5e7eb; border-radius: 8px; margin-bottom: 10px; cursor: pointer; transition: all 0.15s;">
              <div style="display: flex; gap: 12px; align-items: start;">
                ${props.reference_image ? `<img src="${props.reference_image}" style="width: 60px; height: 60px; object-fit: cover; border-radius: 6px; border: 1px solid #e5e7eb;" />` : '<div style="width: 60px; height: 60px; background: #f3f4f6; border-radius: 6px; display: flex; align-items: center; justify-content: center; color: #9ca3af; font-size: 12px;">无图片</div>'}
                <div style="flex: 1;">
                  <div style="font-weight: 700; font-size: 14px; margin-bottom: 4px;">${escapeHtml(props.name)}</div>
                  ${props.content ? `<div style="font-size: 12px; color: #666; line-height: 1.4;">${escapeHtml(props.content.slice(0, 100))}${props.content.length > 100 ? '...' : ''}</div>` : ''}
                </div>
              </div>
            </div>
          `).join('');
          
          // 添加点击事件
          listEl.querySelectorAll('.props-item').forEach(item => {
            item.addEventListener('click', () => {
              const propsId = item.dataset.propsId;
              const props = result.data.data.find(p => p.id == propsId);
              if (props) {
                // 检查是否有分镜选择上下文（从 nodes.js 传递过来）
                if (window.currentPropsSelectionContext) {
                  // 调用 nodes.js 中的 addPropsToShot 函数来更新分镜数据
                  if (typeof window.addPropsToShot === 'function') {
                    window.addPropsToShot(props);
                  }
                } else {
                  // 没有上下文，创建道具节点
                  createPropsNode(props);
                  document.getElementById('propsModal').classList.remove('show');
                  renderMinimap();
                }
              }
            });
            
            item.addEventListener('mouseenter', () => {
              item.style.background = '#f8fafc';
              item.style.borderColor = '#22c55e';
            });
            
            item.addEventListener('mouseleave', () => {
              item.style.background = '';
              item.style.borderColor = '#e5e7eb';
            });
          });
        }
      } catch (error) {
        console.error('加载道具列表失败:', error);
        listEl.innerHTML = '<div style="text-align: center; color: #ef4444; padding: 40px 20px;">加载失败</div>';
      }
    }
    
    // 带数据创建角色节点（用于恢复工作流）
    function createCharacterNodeWithData(nodeData) {
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;
      
      const id = state.nextNodeId++;
      const node = {
        id,
        type: 'character',
        title: nodeData.title || nodeData.data.name,
        x: nodeData.x,
        y: nodeData.y,
        data: nodeData.data
      };
      state.nodes.push(node);
      
      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';
      
      const character = nodeData.data;
      el.innerHTML = `
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><circle cx="12" cy="8" r="3"/><path d="M6 21C6 17.6863 8.68629 15 12 15C15.3137 15 18 17.6863 18 21" stroke-linecap="round"/></svg>角色: ${escapeHtml(character.name)}</div>
          <button class="icon-btn" data-action="delete" title="删除">×</button>
        </div>
        <div class="node-body">
          ${character.reference_image ? `
            <div class="field">
              <div class="label">参考图</div>
              <img src="${character.reference_image}" class="preview character-preview-img" style="width: 100%; height: auto; border-radius: 8px; cursor: zoom-in;" />
              <div style="display: flex; gap: 8px; margin-top: 8px;">
                <button class="mini-btn character-download-btn" type="button" data-img-url="${character.reference_image}">下载图片</button>
              </div>
            </div>
          ` : ''}
          ${character.age ? `<div class="field"><div class="label">年龄</div><div>${escapeHtml(character.age)}</div></div>` : ''}
          ${character.identity ? `<div class="field"><div class="label">身份/职业</div><div>${escapeHtml(character.identity)}</div></div>` : ''}
          ${character.personality ? `<div class="field"><div class="label">性格</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.personality.slice(0, 100))}${character.personality.length > 100 ? '...' : ''}</div></div>` : ''}
          ${character.behavior ? `<div class="field"><div class="label">行为习惯</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.behavior.slice(0, 100))}${character.behavior.length > 100 ? '...' : ''}</div></div>` : ''}
          ${character.other_info ? `<div class="field"><div class="label">其他信息</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.other_info.slice(0, 100))}${character.other_info.length > 100 ? '...' : ''}</div></div>` : ''}
          <div class="field btn-row">
            <button class="mini-btn character-edit-btn" type="button">编辑</button>
            <button class="mini-btn character-sora-video-btn" type="button" style="${character.sora_character ? 'background: white; color: #111827; border: 1px solid #d1d5db;' : 'background: #8b5cf6; color: white;'}">${character.sora_character ? '重新生成sora角色视频' : '生成sora角色视频'}</button>
          </div>
          <div class="field btn-row" style="display: flex; align-items: center; gap: 8px;">
            <button class="mini-btn character-create-card-btn" type="button" style="${character.sora_character ? 'background: white; color: #111827; border: 1px solid #d1d5db;' : 'background: #10b981; color: white;'} opacity: 0.5; cursor: not-allowed;" data-can-click="false">${character.sora_character ? '重新生成sora角色卡' : '创建sora角色卡'}</button>
            <span class="character-card-help-icon" style="display: none; width: 16px; height: 16px; border-radius: 50%; background: #ef4444; color: white; font-size: 12px; line-height: 16px; text-align: center; cursor: help; flex-shrink: 0;" title="如果角色持续创建失败，请尝试更改角色图片 并 重新生成角色视频">?</span>
          </div>
          <div class="character-sora-video-error" style="display: none; color: #dc2626; font-size: 12px; margin-top: 8px; padding: 8px; background: #fee2e2; border-radius: 6px; border: 1px solid #fecaca;"></div>
        </div>
        <div class="port output" data-port="output" title="输出"></div>
      `;
      
      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);
      
      // 绑定事件
      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('[data-action="delete"]');
      const editBtn = el.querySelector('.character-edit-btn');
      const soraVideoBtn = el.querySelector('.character-sora-video-btn');
      const createCardBtn = el.querySelector('.character-create-card-btn');
      const helpIcon = el.querySelector('.character-card-help-icon');
      const outputPort = el.querySelector('.port.output');
      
      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });
      
      // 图片点击放大事件
      const characterImg = el.querySelector('.character-preview-img');
      if (characterImg) {
        characterImg.addEventListener('click', (e) => {
          e.stopPropagation();
          openImageModal(character.reference_image, `角色: ${character.name}`);
        });
      }
      
      // 下载图片按钮事件
      const downloadImgBtn = el.querySelector('.character-download-btn');
      if (downloadImgBtn) {
        downloadImgBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const imgUrl = downloadImgBtn.dataset.imgUrl;
          if (imgUrl) {
            downloadImage(imgUrl, `${character.name || '角色'}.png`);
          }
        });
      }
      
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openCharacterEditModal(id, character);
      });
      
      soraVideoBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        generateSoraCharacterVideo(id, character);
      });
      
      createCardBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const canClick = createCardBtn.getAttribute('data-can-click') === 'true';
        if (!canClick) {
          showToast('请先连接一个视频节点，或生成角色视频后再创建角色卡', 'warning');
          return;
        }
        createSoraCharacterCard(id, character);
      });
      
      // 初始化时检查是否已有连接的视频节点
      setTimeout(() => {
        updateCharacterCardButtonState(id);
      }, 100);
      
      if (helpIcon) {
        helpIcon.addEventListener('click', (e) => {
          e.stopPropagation();
          showToast('如果角色持续创建失败，请尝试更改角色图片并重新生成角色视频', 'info');
        });
      }
      
      el.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.stopPropagation();
        setSelected(id);
      });
      
      headerEl.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.preventDefault();
        e.stopPropagation();
        // 如果节点不在选中列表中，才调用setSelected（这会清空其他选中）
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        initNodeDrag(id, e.clientX, e.clientY);
      });
      
      if(outputPort) {
        outputPort.addEventListener('mousedown', (e) => {
          e.preventDefault();
          e.stopPropagation();
          state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
          canvasEl.style.cursor = 'crosshair';
        });
      }
      
      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);
    }
    
    // 创建角色节点
    function createCharacterNode(character) {
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = viewportPos.x;
      const y = viewportPos.y;
      
      const node = {
        id,
        type: 'character',
        title: character.name,
        x,
        y,
        data: character
      };
      state.nodes.push(node);
      
      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';
      
      el.innerHTML = `
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><circle cx="12" cy="8" r="3"/><path d="M6 21C6 17.6863 8.68629 15 12 15C15.3137 15 18 17.6863 18 21" stroke-linecap="round"/></svg>角色: ${escapeHtml(character.name)}</div>
          <button class="icon-btn" data-action="delete" title="删除">×</button>
        </div>
        <div class="node-body">
          ${character.reference_image ? `
            <div class="field field-always-visible">
              <div class="label">参考图</div>
              <img src="${character.reference_image}" class="preview character-preview-img" style="width: 100%; height: auto; border-radius: 8px; cursor: zoom-in;" />
            </div>
          ` : ''}
          ${character.age ? `<div class="field field-always-visible"><div class="label">年龄</div><div>${escapeHtml(character.age)}</div></div>` : ''}
          ${character.identity ? `<div class="field field-always-visible"><div class="label">身份/职业</div><div>${escapeHtml(character.identity)}</div></div>` : ''}
          ${character.personality ? `<div class="field field-always-visible"><div class="label">性格</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.personality.slice(0, 100))}${character.personality.length > 100 ? '...' : ''}</div></div>` : ''}
          ${character.behavior ? `<div class="field field-always-visible"><div class="label">行为习惯</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.behavior.slice(0, 100))}${character.behavior.length > 100 ? '...' : ''}</div></div>` : ''}
          ${character.other_info ? `<div class="field field-always-visible"><div class="label">其他信息</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.other_info.slice(0, 100))}${character.other_info.length > 100 ? '...' : ''}</div></div>` : ''}
          <div class="field field-collapsible">
            <button class="mini-btn character-download-btn" type="button" data-img-url="${character.reference_image}" style="width: 100%;">下载图片</button>
          </div>
          <div class="field field-collapsible btn-row">
            <button class="mini-btn character-edit-btn" type="button">编辑</button>
            <button class="mini-btn character-sora-video-btn" type="button" style="${character.sora_character ? 'background: white; color: #111827; border: 1px solid #d1d5db;' : 'background: #8b5cf6; color: white;'}">${character.sora_character ? '重新生成sora角色视频' : '生成sora角色视频'}</button>
          </div>
          <div class="field field-collapsible btn-row" style="display: flex; align-items: center; gap: 8px;">
            <button class="mini-btn character-create-card-btn" type="button" style="${character.sora_character ? 'background: white; color: #111827; border: 1px solid #d1d5db;' : 'background: #10b981; color: white;'} opacity: 0.5; cursor: not-allowed;" data-can-click="false">${character.sora_character ? '重新生成sora角色卡' : '创建sora角色卡'}</button>
            <span class="character-card-help-icon" style="display: none; width: 16px; height: 16px; border-radius: 50%; background: #ef4444; color: white; font-size: 12px; line-height: 16px; text-align: center; cursor: help; flex-shrink: 0;" title="如果角色持续创建失败，请尝试更改角色图片 并 重新生成角色视频">?</span>
          </div>
          <div class="character-sora-video-error" style="display: none; color: #dc2626; font-size: 12px; margin-top: 8px; padding: 8px; background: #fee2e2; border-radius: 6px; border: 1px solid #fecaca;"></div>
        </div>
        <div class="port output" data-port="output" title="输出"></div>
      `;
      
      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);
      
      // 绑定事件
      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('[data-action="delete"]');
      const editBtn = el.querySelector('.character-edit-btn');
      const soraVideoBtn = el.querySelector('.character-sora-video-btn');
      const createCardBtn = el.querySelector('.character-create-card-btn');
      const helpIcon = el.querySelector('.character-card-help-icon');
      const outputPort = el.querySelector('.port.output');
      
      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });
      
      // 图片点击放大事件
      const characterImg = el.querySelector('.character-preview-img');
      if (characterImg) {
        characterImg.addEventListener('click', (e) => {
          e.stopPropagation();
          openImageModal(character.reference_image, `角色: ${character.name}`);
        });
      }
      
      // 下载图片按钮事件
      const downloadImgBtn = el.querySelector('.character-download-btn');
      if (downloadImgBtn) {
        downloadImgBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const imgUrl = downloadImgBtn.dataset.imgUrl;
          if (imgUrl) {
            downloadImage(imgUrl, `${character.name || '角色'}.png`);
          }
        });
      }
      
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openCharacterEditModal(id, character);
      });
      
      soraVideoBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        generateSoraCharacterVideo(id, character);
      });
      
      createCardBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const canClick = createCardBtn.getAttribute('data-can-click') === 'true';
        if (!canClick) {
          showToast('请先连接一个视频节点，或生成角色视频后再创建角色卡', 'warning');
          return;
        }
        createSoraCharacterCard(id, character);
      });
      
      // 初始化时检查是否已有连接的视频节点
      setTimeout(() => {
        updateCharacterCardButtonState(id);
      }, 100);
      
      if (helpIcon) {
        helpIcon.addEventListener('click', (e) => {
          e.stopPropagation();
          showToast('如果角色持续创建失败，请尝试更改角色图片并重新生成角色视频', 'info');
        });
      }
      
      el.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.stopPropagation();
        setSelected(id);
      });
      
      headerEl.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.preventDefault();
        e.stopPropagation();
        // 如果节点不在选中列表中，才调用setSelected（这会清空其他选中）
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        initNodeDrag(id, e.clientX, e.clientY);
      });
      
      if(outputPort) {
        outputPort.addEventListener('mousedown', (e) => {
          e.preventDefault();
          e.stopPropagation();
          state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
          canvasEl.style.cursor = 'crosshair';
        });
      }
      
      setSelected(id);
      showToast('角色已添加', 'success');
      try { autoSaveWorkflow(); } catch(e) {}
    }
    
    // 带数据创建场景节点（用于恢复工作流）
    function createLocationNodeWithData(nodeData) {
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;
      
      const id = state.nextNodeId++;
      const node = {
        id,
        type: 'location',
        title: nodeData.title || nodeData.data.name,
        x: nodeData.x,
        y: nodeData.y,
        data: nodeData.data
      };
      state.nodes.push(node);
      
      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';
      
      const location = nodeData.data;
      el.innerHTML = `
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M12 2C8.13 2 5 5.13 5 9C5 14.25 12 22 12 22C12 22 19 14.25 19 9C19 5.13 15.87 2 12 2Z"/><circle cx="12" cy="9" r="2.5"/></svg>场景: ${escapeHtml(location.name)}</div>
          <div style="display: flex; gap: 4px;">
            <button class="icon-btn" data-action="edit" title="编辑" style="background: #3b82f6; color: white;">✎</button>
            <button class="icon-btn" data-action="delete" title="删除">×</button>
          </div>
        </div>
        <div class="node-body">
          ${location.reference_image ? `
            <div class="field">
              <div class="label">参考图</div>
              <img src="${location.reference_image}" class="preview location-preview-img" style="width: 100%; height: auto; border-radius: 8px; cursor: zoom-in;" />
              <div style="display: flex; gap: 8px; margin-top: 8px;">
                <button class="mini-btn location-download-btn" type="button" data-img-url="${location.reference_image}">下载图片</button>
              </div>
            </div>
          ` : ''}
          ${location.description ? `<div class="field"><div class="label">描述</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(location.description)}</div></div>` : ''}
        </div>
        <div class="port output" data-port="output" title="输出"></div>
      `;
      
      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);
      
      // 绑定事件
      const headerEl = el.querySelector('.node-header');
      const editBtn = el.querySelector('[data-action="edit"]');
      const deleteBtn = el.querySelector('[data-action="delete"]');
      const outputPort = el.querySelector('.port.output');
      
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openEditLocationModal(location.id);
      });
      
      // 图片点击放大事件
      const locationImg = el.querySelector('.location-preview-img');
      if (locationImg) {
        locationImg.addEventListener('click', (e) => {
          e.stopPropagation();
          openImageModal(location.reference_image, `场景: ${location.name}`);
        });
      }
      
      // 下载图片按钮事件
      const downloadImgBtn = el.querySelector('.location-download-btn');
      if (downloadImgBtn) {
        downloadImgBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const imgUrl = downloadImgBtn.dataset.imgUrl;
          if (imgUrl) {
            downloadImage(imgUrl, `${location.name || '场景'}.png`);
          }
        });
      }
      
      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });
      
      el.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.stopPropagation();
        setSelected(id);
      });
      
      headerEl.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.preventDefault();
        e.stopPropagation();
        // 如果节点不在选中列表中，才调用setSelected（这会清空其他选中）
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        initNodeDrag(id, e.clientX, e.clientY);
      });
      
      if(outputPort) {
        outputPort.addEventListener('mousedown', (e) => {
          e.preventDefault();
          e.stopPropagation();
          state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
          canvasEl.style.cursor = 'crosshair';
        });
      }
      
      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);
    }
    
    // 创建场景节点
    function createLocationNode(location) {
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = viewportPos.x;
      const y = viewportPos.y;
      
      const node = {
        id,
        type: 'location',
        title: location.name,
        x,
        y,
        data: location
      };
      state.nodes.push(node);
      
      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';
      
      el.innerHTML = `
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M12 2C8.13 2 5 5.13 5 9C5 14.25 12 22 12 22C12 22 19 14.25 19 9C19 5.13 15.87 2 12 2Z"/><circle cx="12" cy="9" r="2.5"/></svg>场景: ${escapeHtml(location.name)}</div>
          <div style="display: flex; gap: 4px;">
            <button class="icon-btn" data-action="edit" title="编辑" style="background: #3b82f6; color: white;">✎</button>
            <button class="icon-btn" data-action="delete" title="删除">×</button>
          </div>
        </div>
        <div class="node-body">
          ${location.reference_image ? `
            <div class="field">
              <div class="label">参考图</div>
              <img src="${location.reference_image}" class="preview location-preview-img" style="width: 100%; height: auto; border-radius: 8px; cursor: zoom-in;" />
              <div style="display: flex; gap: 8px; margin-top: 8px;">
                <button class="mini-btn location-download-btn" type="button" data-img-url="${location.reference_image}">下载图片</button>
              </div>
            </div>
          ` : ''}
          ${location.description ? `<div class="field"><div class="label">描述</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(location.description)}</div></div>` : ''}
        </div>
        <div class="port output" data-port="output" title="输出"></div>
      `;
      
      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);
      
      // 绑定事件
      const headerEl = el.querySelector('.node-header');
      const editBtn = el.querySelector('[data-action="edit"]');
      const deleteBtn = el.querySelector('[data-action="delete"]');
      const outputPort = el.querySelector('.port.output');
      
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openEditLocationModal(location.id);
      });
      
      // 图片点击放大事件
      const locationImg = el.querySelector('.location-preview-img');
      if (locationImg) {
        locationImg.addEventListener('click', (e) => {
          e.stopPropagation();
          openImageModal(location.reference_image, `场景: ${location.name}`);
        });
      }
      
      // 下载图片按钮事件
      const downloadImgBtn = el.querySelector('.location-download-btn');
      if (downloadImgBtn) {
        downloadImgBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const imgUrl = downloadImgBtn.dataset.imgUrl;
          if (imgUrl) {
            downloadImage(imgUrl, `${location.name || '场景'}.png`);
          }
        });
      }
      
      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });
      
      el.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.stopPropagation();
        setSelected(id);
      });
      
      headerEl.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.preventDefault();
        e.stopPropagation();
        // 如果节点不在选中列表中，才调用setSelected（这会清空其他选中）
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        initNodeDrag(id, e.clientX, e.clientY);
      });
      
      if(outputPort) {
        outputPort.addEventListener('mousedown', (e) => {
          e.preventDefault();
          e.stopPropagation();
          state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
          canvasEl.style.cursor = 'crosshair';
        });
      }
      
      setSelected(id);
      showToast('场景已添加', 'success');
      try { autoSaveWorkflow(); } catch(e) {}
    }
    
    function getPropsNodeBodyHtml(props) {
      return `
        ${props.reference_image ? `
          <div class="field">
            <div class="label">参考图</div>
            <img src="${props.reference_image}" class="preview props-preview-img" style="width: 100%; height: auto; border-radius: 8px; cursor: zoom-in;" />
            <div style="display: flex; gap: 8px; margin-top: 8px;">
              <button class="mini-btn props-download-btn" type="button" data-img-url="${props.reference_image}">下载图片</button>
            </div>
          </div>
        ` : ''}
        ${props.content ? `<div class="field"><div class="label">描述</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(props.content)}</div></div>` : ''}
        ${props.other_info ? `<div class="field"><div class="label">其他信息</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(props.other_info)}</div></div>` : ''}
      `;
    }

    // 创建道具节点
    function createPropsNode(props) {
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = viewportPos.x;
      const y = viewportPos.y;
      
      const node = {
        id,
        type: 'props',
        title: props.name,
        x,
        y,
        data: props
      };
      state.nodes.push(node);
      
      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';
      
      el.innerHTML = `
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9L15 15M15 9L9 15" stroke-linecap="round"/></svg>道具: ${escapeHtml(props.name)}</div>
          <div style="display: flex; gap: 4px;">
            <button class="icon-btn" data-action="edit" title="编辑" style="background: #3b82f6; color: white;">✎</button>
            <button class="icon-btn" data-action="delete" title="删除">×</button>
          </div>
        </div>
        <div class="node-body">
          ${getPropsNodeBodyHtml(props)}
        </div>
        <div class="port output" data-port="output" title="输出"></div>
      `;
      
      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);
      
      // 绑定事件
      const headerEl = el.querySelector('.node-header');
      const editBtn = el.querySelector('[data-action="edit"]');
      const deleteBtn = el.querySelector('[data-action="delete"]');
      const outputPort = el.querySelector('.port.output');
      
      if (editBtn) {
        editBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          openEditPropsModal(id, props);
        });
      }

      // 图片点击放大事件
      const propsImg = el.querySelector('.props-preview-img');
      if (propsImg) {
        propsImg.addEventListener('click', (e) => {
          e.stopPropagation();
          openImageModal(props.reference_image, `道具: ${props.name}`);
        });
      }

      // 下载图片按钮事件
      const downloadImgBtn = el.querySelector('.props-download-btn');
      if (downloadImgBtn) {
        downloadImgBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const imgUrl = downloadImgBtn.dataset.imgUrl;
          if (imgUrl) {
            downloadImage(imgUrl, `${props.name || '道具'}.png`);
          }
        });
      }

      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });
      
      el.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.stopPropagation();
        setSelected(id);
      });
      
      headerEl.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.preventDefault();
        e.stopPropagation();
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        initNodeDrag(id, e.clientX, e.clientY);
      });
      
      if(outputPort) {
        outputPort.addEventListener('mousedown', (e) => {
          e.preventDefault();
          e.stopPropagation();
          state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
          canvasEl.style.cursor = 'crosshair';
        });
      }
      
      setSelected(id);
      showToast('道具已添加', 'success');
      try { autoSaveWorkflow(); } catch(e) {}
    }
    
    // 带数据创建道具节点（用于恢复工作流）
    function createPropsNodeWithData(nodeData) {
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;
      
      const id = state.nextNodeId++;
      const node = {
        id,
        type: 'props',
        title: nodeData.title || nodeData.data.name,
        x: nodeData.x,
        y: nodeData.y,
        data: nodeData.data
      };
      state.nodes.push(node);
      
      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';

      const props = nodeData.data;
      el.innerHTML = `
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9L15 15M15 9L9 15" stroke-linecap="round"/></svg>道具: ${escapeHtml(props.name)}</div>
          <div style="display: flex; gap: 4px;">
            <button class="icon-btn" data-action="edit" title="编辑" style="background: #3b82f6; color: white;">✎</button>
            <button class="icon-btn" data-action="delete" title="删除">×</button>
          </div>
        </div>
        <div class="node-body">
          ${getPropsNodeBodyHtml(props)}
        </div>
        <div class="port output" data-port="output" title="输出"></div>
      `;
      
      canvasEl.appendChild(el);
      
      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);
      
      // 绑定事件
      const headerEl = el.querySelector('.node-header');
      const editBtn = el.querySelector('[data-action="edit"]');
      const deleteBtn = el.querySelector('[data-action="delete"]');
      const outputPort = el.querySelector('.port.output');

      if (editBtn) {
        editBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          openEditPropsModal(id, props);
        });
      }

      // 图片点击放大事件
      const propsImg = el.querySelector('.props-preview-img');
      if (propsImg) {
        propsImg.addEventListener('click', (e) => {
          e.stopPropagation();
          openImageModal(props.reference_image, `道具: ${props.name}`);
        });
      }

      // 下载图片按钮事件
      const downloadImgBtn = el.querySelector('.props-download-btn');
      if (downloadImgBtn) {
        downloadImgBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const imgUrl = downloadImgBtn.dataset.imgUrl;
          if (imgUrl) {
            downloadImage(imgUrl, `${props.name || '道具'}.png`);
          }
        });
      }

      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });
      
      el.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.stopPropagation();
        setSelected(id);
      });
      
      headerEl.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.preventDefault();
        e.stopPropagation();
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        initNodeDrag(id, e.clientX, e.clientY);
      });
      
      if(outputPort) {
        outputPort.addEventListener('mousedown', (e) => {
          e.preventDefault();
          e.stopPropagation();
          state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
          canvasEl.style.cursor = 'crosshair';
        });
      }
    }
    
    // 角色模态框事件
    document.getElementById('characterModalClose').addEventListener('click', () => {
      document.getElementById('characterModal').classList.remove('show');
    });
    
    document.getElementById('characterWorldSelect').addEventListener('change', (e) => {
      loadCharacters(e.target.value);
    });
    
    document.getElementById('characterSearchInput').addEventListener('input', (e) => {
      const worldId = document.getElementById('characterWorldSelect').value;
      if (worldId) {
        loadCharacters(worldId, e.target.value);
      }
    });
    
    // 场景模态框事件
    document.getElementById('locationModalClose').addEventListener('click', () => {
      document.getElementById('locationModal').classList.remove('show');
    });
    
    document.getElementById('locationWorldSelect').addEventListener('change', (e) => {
      loadLocations(e.target.value);
    });
    
    document.getElementById('locationSearchInput').addEventListener('input', (e) => {
      const worldId = document.getElementById('locationWorldSelect').value;
      if (worldId) {
        loadLocations(worldId, e.target.value);
      }
    });
    
    // 道具模态框事件
    document.getElementById('propsModalClose').addEventListener('click', () => {
      document.getElementById('propsModal').classList.remove('show');
    });
    
    document.getElementById('propsWorldSelect').addEventListener('change', (e) => {
      loadProps(e.target.value);
    });
    
    document.getElementById('propsSearchInput').addEventListener('input', (e) => {
      const worldId = document.getElementById('propsWorldSelect').value;
      if (worldId) {
        loadProps(worldId, e.target.value);
      }
    });
    
    // 点击模态框背景关闭
    document.getElementById('characterModal').addEventListener('click', (e) => {
      if (e.target.id === 'characterModal') {
        document.getElementById('characterModal').classList.remove('show');
      }
    });
    
    document.getElementById('locationModal').addEventListener('click', (e) => {
      if (e.target.id === 'locationModal') {
        document.getElementById('locationModal').classList.remove('show');
      }
    });
    
    document.getElementById('propsModal').addEventListener('click', (e) => {
      if (e.target.id === 'propsModal') {
        document.getElementById('propsModal').classList.remove('show');
      }
    });
    
    // ========== 创建世界功能 ==========
    
    let currentWorldSelectElement = null; // 记录当前是从哪个下拉框打开的创建世界
    
    // 打开创建世界模态框
    function openCreateWorldModal(selectElement) {
      currentWorldSelectElement = selectElement;
      document.getElementById('createWorldNameInput').value = '';
      document.getElementById('createWorldDescInput').value = '';
      document.getElementById('createWorldModal').classList.add('show');
    }
    
    // 创建世界
    async function createWorld() {
      const nameInput = document.getElementById('createWorldNameInput');
      const descInput = document.getElementById('createWorldDescInput');
      const saveBtn = document.getElementById('createWorldSaveBtn');
      
      const name = nameInput.value.trim();
      if (!name) {
        showToast('请输入世界名称', 'error');
        nameInput.focus();
        return;
      }
      
      saveBtn.disabled = true;
      saveBtn.textContent = '创建中...';
      
      try {
        const response = await fetch('/api/worlds', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
          },
          body: JSON.stringify({
            name: name,
            description: descInput.value.trim() || null
          })
        });
        
        const result = await response.json();
        
        if (result.code === 0 && result.data) {
          showToast('世界创建成功', 'success');
          
          // 关闭创建世界模态框
          const modalEl = document.getElementById('createWorldModal');
          modalEl.classList.remove('show');
          modalEl.dispatchEvent(new Event('worldCreateSuccess', { bubbles: true }));
          
          // 重新加载世界列表
          if (currentWorldSelectElement) {
            await loadWorldsToSelect(currentWorldSelectElement);
            // 自动选中新创建的世界
            currentWorldSelectElement.value = result.data.id;
            
            // 触发change事件以加载对应的角色或场景列表
            const event = new Event('change');
            currentWorldSelectElement.dispatchEvent(event);
          }
          
          // 同时更新左上角的世界选择器（如果从左上角创建的）
          if (typeof onWorldCreated === 'function') {
            await onWorldCreated(result.data.id);
          }
        } else {
          showToast(result.message || '创建失败', 'error');
        }
      } catch (error) {
        console.error('创建世界失败:', error);
        showToast('创建世界失败', 'error');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '创建';
      }
    }
    
    // 创建世界按钮事件
    document.getElementById('characterCreateWorldBtn').addEventListener('click', () => {
      openCreateWorldModal(document.getElementById('characterWorldSelect'));
    });
    
    document.getElementById('locationCreateWorldBtn').addEventListener('click', () => {
      openCreateWorldModal(document.getElementById('locationWorldSelect'));
    });
    
    document.getElementById('propsCreateWorldBtn').addEventListener('click', () => {
      openCreateWorldModal(document.getElementById('propsWorldSelect'));
    });
    
    // 创建世界模态框事件
    document.getElementById('createWorldModalClose').addEventListener('click', () => {
      document.getElementById('createWorldModal').classList.remove('show');
    });
    
    document.getElementById('createWorldCancelBtn').addEventListener('click', () => {
      document.getElementById('createWorldModal').classList.remove('show');
    });
    
    document.getElementById('createWorldSaveBtn').addEventListener('click', () => {
      createWorld();
    });
    
    // 点击模态框背景关闭
    document.getElementById('createWorldModal').addEventListener('click', (e) => {
      if (e.target.id === 'createWorldModal') {
        document.getElementById('createWorldModal').classList.remove('show');
      }
    });
    
    // 回车键创建世界
    document.getElementById('createWorldNameInput').addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        createWorld();
      }
    });
    
    // ========== 创建角色功能 ==========
    
    // 打开创建角色模态框
    function openCreateCharacterModal() {
      const worldId = document.getElementById('characterWorldSelect').value;
      if (!worldId) {
        showToast('请先选择世界', 'error');
        return;
      }
      
      document.getElementById('createCharacterNameInput').value = '';
      document.getElementById('createCharacterAgeInput').value = '';
      document.getElementById('createCharacterIdentityInput').value = '';
      document.getElementById('createCharacterPersonalityInput').value = '';
      document.getElementById('createCharacterBehaviorInput').value = '';
      document.getElementById('createCharacterOtherInfoInput').value = '';
      document.getElementById('createCharacterImageInput').value = '';
      document.getElementById('createCharacterVoiceInput').value = '';
      
      // 重置音频预览
      const voicePreview = document.getElementById('createCharacterVoicePreview');
      const voicePreviewAudio = document.getElementById('createCharacterVoicePreviewAudio');
      voicePreviewAudio.src = '';
      voicePreview.style.display = 'none';
      
      document.getElementById('createCharacterModal').classList.add('show');
    }
    
    // 创建角色
    async function createCharacter() {
      const worldId = document.getElementById('characterWorldSelect').value;
      const nameInput = document.getElementById('createCharacterNameInput');
      const ageInput = document.getElementById('createCharacterAgeInput');
      const identityInput = document.getElementById('createCharacterIdentityInput');
      const personalityInput = document.getElementById('createCharacterPersonalityInput');
      const behaviorInput = document.getElementById('createCharacterBehaviorInput');
      const otherInfoInput = document.getElementById('createCharacterOtherInfoInput');
      const imageInput = document.getElementById('createCharacterImageInput');
      const voiceInput = document.getElementById('createCharacterVoiceInput');
      const saveBtn = document.getElementById('createCharacterSaveBtn');
      
      const name = nameInput.value.trim();
      if (!name) {
        showToast('请输入角色名称', 'error');
        nameInput.focus();
        return;
      }
      
      // 验证图片文件大小
      if (imageInput.files.length > 0) {
        const maxSize = uploadConfig.max_image_size_mb * 1024 * 1024;
        if (imageInput.files[0].size > maxSize) {
          showToast(`图片文件不能超过${uploadConfig.max_image_size_mb}MB`, 'error');
          imageInput.value = '';
          return;
        }
      }
      
      saveBtn.disabled = true;
      saveBtn.textContent = '创建中...';
      
      try {
        const formData = new FormData();
        formData.append('world_id', worldId);
        formData.append('name', name);
        if (ageInput.value.trim()) formData.append('age', ageInput.value.trim());
        if (identityInput.value.trim()) formData.append('identity', identityInput.value.trim());
        if (personalityInput.value.trim()) formData.append('personality', personalityInput.value.trim());
        if (behaviorInput.value.trim()) formData.append('behavior', behaviorInput.value.trim());
        if (otherInfoInput.value.trim()) formData.append('other_info', otherInfoInput.value.trim());
        if (imageInput.files.length > 0) formData.append('reference_image', imageInput.files[0]);
        if (voiceInput.files.length > 0) formData.append('default_voice', voiceInput.files[0]);
        
        const response = await fetch('/api/characters', {
          method: 'POST',
          headers: {
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
          },
          body: formData
        });
        
        const result = await response.json();
        
        if (result.code === 0 && result.data) {
          showToast('角色创建成功', 'success');
          
          document.getElementById('createCharacterModal').classList.remove('show');
          
          loadCharacters(worldId);
        } else {
          showToast(result.message || '创建失败', 'error');
        }
      } catch (error) {
        console.error('创建角色失败:', error);
        showToast('创建角色失败', 'error');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '创建';
      }
    }
    
    // 创建角色按钮事件
    document.getElementById('createCharacterBtn').addEventListener('click', () => {
      openCreateCharacterModal();
    });
    
    // 创建角色模态框事件
    document.getElementById('createCharacterModalClose').addEventListener('click', () => {
      document.getElementById('createCharacterModal').classList.remove('show');
    });
    
    document.getElementById('createCharacterCancelBtn').addEventListener('click', () => {
      document.getElementById('createCharacterModal').classList.remove('show');
    });
    
    document.getElementById('createCharacterSaveBtn').addEventListener('click', () => {
      createCharacter();
    });
    
    document.getElementById('createCharacterModal').addEventListener('click', (e) => {
      if (e.target.id === 'createCharacterModal') {
        document.getElementById('createCharacterModal').classList.remove('show');
      }
    });
    
    // 创建角色音频文件选择预览
    document.getElementById('createCharacterVoiceInput').addEventListener('change', async (e) => {
      const file = e.target.files[0];
      const voicePreview = document.getElementById('createCharacterVoicePreview');
      const voicePreviewAudio = document.getElementById('createCharacterVoicePreviewAudio');
      const voiceInput = e.target;
      
      if (file) {
        // 验证文件大小
        const maxSize = 10 * 1024 * 1024; // 10MB
        if(file.size > maxSize){
          showToast('音频文件不能超过10MB', 'error');
          voiceInput.value = '';
          voicePreviewAudio.src = '';
          voicePreview.style.display = 'none';
          return;
        }
        
        // 显示音频预览（不再验证时长，后端会自动裁剪）
        const url = URL.createObjectURL(file);
        const audio = new Audio();
        
        audio.addEventListener('loadedmetadata', () => {
          voicePreviewAudio.src = url;
          voicePreview.style.display = 'block';
          
          // 如果音频超过20秒，提示用户会自动裁剪
          const maxDuration = 20;
          if(audio.duration > maxDuration){
            showToast(`音频时长为${audio.duration.toFixed(1)}秒，上传后将自动裁剪至${maxDuration}秒`, 'info');
          }
        });
        
        audio.addEventListener('error', () => {
          showToast('无法读取音频文件', 'error');
          voiceInput.value = '';
          voicePreviewAudio.src = '';
          voicePreview.style.display = 'none';
          URL.revokeObjectURL(url);
        });
        
        audio.src = url;
      } else {
        voicePreviewAudio.src = '';
        voicePreview.style.display = 'none';
      }
    });
    
    // 创建角色 - 如何获取参考音频指南链接
    document.getElementById('createCharacterVoiceGuideLink').addEventListener('click', (e) => {
      e.preventDefault();
      window.open('/reference_audio_guide.html', '_blank');
    });
    
    // 编辑角色音频文件选择预览
    document.getElementById('editCharacterVoiceInput').addEventListener('change', async (e) => {
      const file = e.target.files[0];
      const voicePreview = document.getElementById('editCharacterVoicePreview');
      const voicePreviewAudio = document.getElementById('editCharacterVoicePreviewAudio');
      const voiceInput = e.target;
      
      if (file) {
        // 验证文件大小
        const maxSize = 10 * 1024 * 1024; // 10MB
        if(file.size > maxSize){
          showToast('音频文件不能超过10MB', 'error');
          voiceInput.value = '';
          // 恢复原始音频
          const characterId = currentEditingCharacterNodeId;
          if (characterId) {
            const node = state.nodes.find(n => n.id === characterId);
            if (node && node.data && node.data.default_voice) {
              voicePreviewAudio.src = node.data.default_voice;
              voicePreview.style.display = 'block';
              return;
            }
          }
          voicePreviewAudio.src = '';
          voicePreview.style.display = 'none';
          return;
        }
        
        // 显示音频预览（不再验证时长，后端会自动裁剪）
        const url = URL.createObjectURL(file);
        const audio = new Audio();
        
        audio.addEventListener('loadedmetadata', () => {
          voicePreviewAudio.src = url;
          voicePreview.style.display = 'block';
          
          // 如果音频超过20秒，提示用户会自动裁剪
          const maxDuration = 20;
          if(audio.duration > maxDuration){
            showToast(`音频时长为${audio.duration.toFixed(1)}秒，上传后将自动裁剪至${maxDuration}秒`, 'info');
          }
        });
        
        audio.addEventListener('error', () => {
          showToast('无法读取音频文件', 'error');
          voiceInput.value = '';
          URL.revokeObjectURL(url);
          // 恢复原始音频
          const characterId = currentEditingCharacterNodeId;
          if (characterId) {
            const node = state.nodes.find(n => n.id === characterId);
            if (node && node.data && node.data.default_voice) {
              voicePreviewAudio.src = node.data.default_voice;
              voicePreview.style.display = 'block';
              return;
            }
          }
          voicePreviewAudio.src = '';
          voicePreview.style.display = 'none';
        });
        
        audio.src = url;
      } else {
        // 如果清空文件，检查是否有原始音频
        const characterId = currentEditingCharacterNodeId;
        if (characterId) {
          const node = state.nodes.find(n => n.id === characterId);
          if (node && node.data && node.data.default_voice) {
            voicePreviewAudio.src = node.data.default_voice;
            voicePreview.style.display = 'block';
            return;
          }
        }
        voicePreviewAudio.src = '';
        voicePreview.style.display = 'none';
      }
    });
    
    // 编辑角色 - 如何获取参考音频指南链接
    document.getElementById('editCharacterVoiceGuideLink').addEventListener('click', (e) => {
      e.preventDefault();
      window.open('/reference_audio_guide.html', '_blank');
    });
    
    // ========== 创建场景功能 ==========
    
    // 打开创建场景模态框
    async function openCreateLocationModal() {
      const worldId = document.getElementById('locationWorldSelect').value;
      if (!worldId) {
        showToast('请先选择世界', 'error');
        return;
      }
      
      document.getElementById('createLocationNameInput').value = '';
      document.getElementById('createLocationParentSelect').value = '';
      document.getElementById('createLocationDescInput').value = '';
      document.getElementById('createLocationImageInput').value = '';
      
      // 加载父场景列表
      await loadParentLocationOptions(worldId);
      
      document.getElementById('createLocationModal').classList.add('show');
    }
    
    // 加载父场景选项
    async function loadParentLocationOptions(worldId) {
      const parentSelect = document.getElementById('createLocationParentSelect');
      parentSelect.innerHTML = '<option value="">无（顶层场景）</option>';
      
      try {
        const response = await fetch(`/api/locations?world_id=${worldId}&page=1&page_size=100`, {
          headers: {
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
          }
        });
        
        const result = await response.json();
        if (result.code === 0 && result.data && result.data.data) {
          result.data.data.forEach(location => {
            const option = document.createElement('option');
            option.value = location.id;
            option.textContent = location.name;
            parentSelect.appendChild(option);
          });
        }
      } catch (error) {
        console.error('加载父场景列表失败:', error);
      }
    }
    
    // 创建场景
    async function createLocation() {
      const worldId = document.getElementById('locationWorldSelect').value;
      const nameInput = document.getElementById('createLocationNameInput');
      const parentSelect = document.getElementById('createLocationParentSelect');
      const descInput = document.getElementById('createLocationDescInput');
      const imageInput = document.getElementById('createLocationImageInput');
      const saveBtn = document.getElementById('createLocationSaveBtn');
      
      const name = nameInput.value.trim();
      if (!name) {
        showToast('请输入场景名称', 'error');
        nameInput.focus();
        return;
      }
      
      // 验证图片文件大小
      if (imageInput.files.length > 0) {
        const maxSize = uploadConfig.max_image_size_mb * 1024 * 1024;
        if (imageInput.files[0].size > maxSize) {
          showToast(`图片文件不能超过${uploadConfig.max_image_size_mb}MB`, 'error');
          imageInput.value = '';
          return;
        }
      }
      
      saveBtn.disabled = true;
      saveBtn.textContent = '创建中...';
      
      try {
        const formData = new FormData();
        formData.append('world_id', worldId);
        formData.append('name', name);
        
        // 添加父场景ID（如果选择了）
        const parentId = parentSelect.value;
        if (parentId) {
          formData.append('parent_id', parentId);
        }
        
        if (descInput.value.trim()) formData.append('description', descInput.value.trim());
        if (imageInput.files.length > 0) formData.append('reference_image', imageInput.files[0]);
        
        const response = await fetch('/api/locations', {
          method: 'POST',
          headers: {
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
          },
          body: formData
        });
        
        const result = await response.json();
        
        if (result.code === 0 && result.data) {
          showToast('场景创建成功', 'success');
          
          const modalEl = document.getElementById('createLocationModal');
          modalEl.classList.remove('show');
          modalEl.dispatchEvent(new Event('locationCreateSuccess', { bubbles: true }));
          
          loadLocations(worldId);
        } else {
          showToast(result.message || '创建失败', 'error');
        }
      } catch (error) {
        console.error('创建场景失败:', error);
        showToast('创建场景失败', 'error');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '创建';
      }
    }
    
    // ========== 创建道具功能 ==========
    
    // 打开创建道具模态框
    async function openCreatePropsModal() {
      const worldId = document.getElementById('propsWorldSelect').value;
      if (!worldId) {
        showToast('请先选择世界', 'error');
        return;
      }
      
      document.getElementById('createPropsNameInput').value = '';
      document.getElementById('createPropsContentInput').value = '';
      document.getElementById('createPropsOtherInfoInput').value = '';
      document.getElementById('createPropsImageInput').value = '';
      
      document.getElementById('createPropsModal').classList.add('show');
    }
    
    // 创建道具
    async function createPropsItem() {
      const worldId = document.getElementById('propsWorldSelect').value;
      const nameInput = document.getElementById('createPropsNameInput');
      const contentInput = document.getElementById('createPropsContentInput');
      const otherInfoInput = document.getElementById('createPropsOtherInfoInput');
      const imageInput = document.getElementById('createPropsImageInput');
      const saveBtn = document.getElementById('createPropsSaveBtn');
      
      const name = nameInput.value.trim();
      if (!name) {
        showToast('请输入道具名称', 'error');
        nameInput.focus();
        return;
      }
      
      // 验证图片文件大小
      if (imageInput.files.length > 0) {
        const maxSize = uploadConfig.max_image_size_mb * 1024 * 1024;
        if (imageInput.files[0].size > maxSize) {
          showToast(`图片文件不能超过${uploadConfig.max_image_size_mb}MB`, 'error');
          imageInput.value = '';
          return;
        }
      }
      
      saveBtn.disabled = true;
      saveBtn.textContent = '创建中...';
      
      try {
        const formData = new FormData();
        formData.append('world_id', worldId);
        formData.append('name', name);
        
        if (contentInput.value.trim()) formData.append('content', contentInput.value.trim());
        if (otherInfoInput.value.trim()) formData.append('other_info', otherInfoInput.value.trim());
        if (imageInput.files.length > 0) formData.append('reference_image', imageInput.files[0]);
        
        const response = await fetch('/api/props', {
          method: 'POST',
          headers: {
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
          },
          body: formData
        });
        
        const result = await response.json();
        
        if (result.code === 0 && result.data) {
          showToast('道具创建成功', 'success');
          
          const modalEl = document.getElementById('createPropsModal');
          modalEl.classList.remove('show');
          
          loadProps(worldId);
        } else {
          showToast(result.message || '创建失败', 'error');
        }
      } catch (error) {
        console.error('创建道具失败:', error);
        showToast('创建道具失败', 'error');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '创建';
      }
    }
    
    // ========== 编辑道具功能 ==========
    
    let currentEditingPropsNodeId = null;

    function openEditPropsModal(nodeId, props) {
      if (!props || !props.id) {
        showToast('无法获取道具信息', 'error');
        return;
      }

      currentEditingPropsNodeId = nodeId;

      document.getElementById('editPropsId').value = props.id;
      document.getElementById('editPropsNameInput').value = props.name || '';
      document.getElementById('editPropsContentInput').value = props.content || '';
      document.getElementById('editPropsOtherInfoInput').value = props.other_info || '';
      document.getElementById('editPropsImageInput').value = '';

      const contentCountEl = document.getElementById('editPropsContentCount');
      if (contentCountEl) {
        contentCountEl.textContent = (props.content || '').length;
      }

      const imagePreview = document.getElementById('editPropsImagePreview');
      const imagePreviewImg = document.getElementById('editPropsImagePreviewImg');
      if (props.reference_image) {
        imagePreviewImg.src = props.reference_image;
        imagePreview.style.display = 'block';
      } else {
        imagePreview.style.display = 'none';
      }

      document.getElementById('editPropsModal').classList.add('show');
    }

    async function savePropsEdit() {
      const nameInput = document.getElementById('editPropsNameInput');
      const contentInput = document.getElementById('editPropsContentInput');
      const otherInfoInput = document.getElementById('editPropsOtherInfoInput');
      const imageInput = document.getElementById('editPropsImageInput');
      const saveBtn = document.getElementById('editPropsSaveBtn');

      const name = nameInput.value.trim();
      if (!name) {
        showToast('请输入道具名称', 'error');
        nameInput.focus();
        return;
      }

      if (!currentEditingPropsNodeId) {
        showToast('未选择道具节点', 'error');
        return;
      }

      const node = state.nodes.find(n => n.id === currentEditingPropsNodeId);
      if (!node || !node.data || !node.data.id) {
        showToast('找不到道具信息', 'error');
        return;
      }

      const propsId = node.data.id;

      // 验证图片文件大小
      if (imageInput.files.length > 0) {
        const maxSize = uploadConfig.max_image_size_mb * 1024 * 1024;
        if (imageInput.files[0].size > maxSize) {
          showToast(`图片文件不能超过${uploadConfig.max_image_size_mb}MB`, 'error');
          imageInput.value = '';
          return;
        }
      }

      saveBtn.disabled = true;
      saveBtn.textContent = '保存中...';

      try {
        const formData = new FormData();
        formData.append('name', name);
        if (contentInput.value.trim()) formData.append('content', contentInput.value.trim());
        if (otherInfoInput.value.trim()) formData.append('other_info', otherInfoInput.value.trim());
        if (imageInput.files.length > 0) formData.append('reference_image', imageInput.files[0]);

        const response = await fetch(`/api/props/${propsId}`, {
          method: 'PUT',
          headers: {
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
          },
          body: formData
        });

        const result = await response.json();

        if (result.code === 0 && result.data) {
          showToast('道具更新成功', 'success');

          const updatedProps = result.data;
          Object.assign(node.data, updatedProps);
          node.title = updatedProps.name;

          const nodeEl = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
          if (nodeEl) {
            const titleEl = nodeEl.querySelector('.node-title');
            if (titleEl) {
              titleEl.textContent = `道具: ${updatedProps.name || ''}`;
            }
            const bodyEl = nodeEl.querySelector('.node-body');
            if (bodyEl) {
              bodyEl.innerHTML = getPropsNodeBodyHtml(updatedProps);
            }
          }

          try { autoSaveWorkflow(); } catch (e) {}

          const propsModalWorld = document.getElementById('propsWorldSelect');
          if (propsModalWorld && propsModalWorld.value) {
            const keyword = document.getElementById('propsSearchInput')?.value || '';
            loadProps(propsModalWorld.value, keyword);
          }

          document.getElementById('editPropsModal').classList.remove('show');
          currentEditingPropsNodeId = null;
        } else {
          showToast(result.message || '更新失败', 'error');
        }
      } catch (error) {
        console.error('更新道具失败:', error);
        showToast('更新道具失败', 'error');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '保存';
        imageInput.value = '';
      }
    }

    document.getElementById('editPropsModalClose').addEventListener('click', () => {
      document.getElementById('editPropsModal').classList.remove('show');
      currentEditingPropsNodeId = null;
    });

    document.getElementById('editPropsCancelBtn').addEventListener('click', () => {
      document.getElementById('editPropsModal').classList.remove('show');
      currentEditingPropsNodeId = null;
    });

    document.getElementById('editPropsSaveBtn').addEventListener('click', () => {
      savePropsEdit();
    });

    document.getElementById('editPropsModal').addEventListener('click', (e) => {
      if (e.target.id === 'editPropsModal') {
        document.getElementById('editPropsModal').classList.remove('show');
        currentEditingPropsNodeId = null;
      }
    });

    const editPropsContentInput = document.getElementById('editPropsContentInput');
    const editPropsContentCount = document.getElementById('editPropsContentCount');
    if (editPropsContentInput && editPropsContentCount) {
      editPropsContentInput.addEventListener('input', () => {
        editPropsContentCount.textContent = editPropsContentInput.value.length;
      });
    }

    // 编辑场景功能
    async function openEditLocationModal(locationId) {
      const worldId = document.getElementById('locationWorldSelect').value;
      if (!worldId) {
        showToast('请先选择世界', 'error');
        return;
      }
      
      try {
        // 获取场景详情
        const response = await fetch(`/api/locations?world_id=${worldId}&page=1&page_size=100`, {
          headers: {
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
          }
        });
        
        const result = await response.json();
        if (result.code === 0 && result.data && result.data.data) {
          const location = result.data.data.find(l => l.id == locationId);
          if (!location) {
            showToast('场景不存在', 'error');
            return;
          }
          
          // 填充表单
          document.getElementById('editLocationId').value = location.id;
          document.getElementById('editLocationNameInput').value = location.name || '';
          document.getElementById('editLocationDescInput').value = location.description || '';
          document.getElementById('editLocationImageInput').value = '';
          
          // 更新字数统计
          const descCount = document.getElementById('editLocationDescCount');
          if (descCount) {
            descCount.textContent = (location.description || '').length;
          }
          
          // 加载父场景选项
          await loadEditParentLocationOptions(worldId, locationId, location.parent_id);
          
          document.getElementById('editLocationModal').classList.add('show');
        }
      } catch (error) {
        console.error('获取场景详情失败:', error);
        showToast('获取场景详情失败', 'error');
      }
    }
    
    // 加载编辑时的父场景选项
    async function loadEditParentLocationOptions(worldId, currentLocationId, currentParentId) {
      const parentSelect = document.getElementById('editLocationParentSelect');
      parentSelect.innerHTML = '<option value="">无（顶层场景）</option>';
      
      try {
        const response = await fetch(`/api/locations?world_id=${worldId}&page=1&page_size=100`, {
          headers: {
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
          }
        });
        
        const result = await response.json();
        if (result.code === 0 && result.data && result.data.data) {
          result.data.data.forEach(location => {
            // 不能选择自己作为父场景
            if (location.id != currentLocationId) {
              const option = document.createElement('option');
              option.value = location.id;
              option.textContent = location.name;
              if (location.id == currentParentId) {
                option.selected = true;
              }
              parentSelect.appendChild(option);
            }
          });
        }
      } catch (error) {
        console.error('加载父场景列表失败:', error);
      }
    }
    
    // 更新场景
    async function updateLocation() {
      const locationId = document.getElementById('editLocationId').value;
      const nameInput = document.getElementById('editLocationNameInput');
      const parentSelect = document.getElementById('editLocationParentSelect');
      const descInput = document.getElementById('editLocationDescInput');
      const imageInput = document.getElementById('editLocationImageInput');
      const saveBtn = document.getElementById('editLocationSaveBtn');
      
      const name = nameInput.value.trim();
      if (!name) {
        showToast('请输入场景名称', 'error');
        nameInput.focus();
        return;
      }
      
      // 验证图片文件大小
      if (imageInput.files.length > 0) {
        const maxSize = uploadConfig.max_image_size_mb * 1024 * 1024;
        if (imageInput.files[0].size > maxSize) {
          showToast(`图片文件不能超过${uploadConfig.max_image_size_mb}MB`, 'error');
          imageInput.value = '';
          return;
        }
      }
      
      saveBtn.disabled = true;
      saveBtn.textContent = '保存中...';
      
      try {
        const formData = new FormData();
        formData.append('name', name);
        
        const parentId = parentSelect.value;
        if (parentId) {
          formData.append('parent_id', parentId);
        }
        
        if (descInput.value.trim()) formData.append('description', descInput.value.trim());
        if (imageInput.files.length > 0) formData.append('reference_image', imageInput.files[0]);
        
        const response = await fetch(`/api/locations/${locationId}`, {
          method: 'PUT',
          headers: {
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
          },
          body: formData
        });
        
        const result = await response.json();
        
        if (result.code === 0) {
          showToast('场景更新成功', 'success');
          document.getElementById('editLocationModal').classList.remove('show');
          
          const worldId = document.getElementById('locationWorldSelect').value;
          loadLocations(worldId);
        } else {
          showToast(result.message || '更新失败', 'error');
        }
      } catch (error) {
        console.error('更新场景失败:', error);
        showToast('更新场景失败', 'error');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '保存';
      }
    }
    
    // 编辑场景模态框事件
    document.getElementById('editLocationModalClose').addEventListener('click', () => {
      document.getElementById('editLocationModal').classList.remove('show');
    });
    
    document.getElementById('editLocationCancelBtn').addEventListener('click', () => {
      document.getElementById('editLocationModal').classList.remove('show');
    });
    
    document.getElementById('editLocationSaveBtn').addEventListener('click', () => {
      updateLocation();
    });
    
    document.getElementById('editLocationModal').addEventListener('click', (e) => {
      if (e.target.id === 'editLocationModal') {
        document.getElementById('editLocationModal').classList.remove('show');
      }
    });
    
    // 场景描述字数统计
    const createDescInput = document.getElementById('createLocationDescInput');
    const createDescCount = document.getElementById('createLocationDescCount');
    if (createDescInput && createDescCount) {
      createDescInput.addEventListener('input', () => {
        createDescCount.textContent = createDescInput.value.length;
      });
    }
    
    const editDescInput = document.getElementById('editLocationDescInput');
    const editDescCount = document.getElementById('editLocationDescCount');
    if (editDescInput && editDescCount) {
      editDescInput.addEventListener('input', () => {
        editDescCount.textContent = editDescInput.value.length;
      });
    }
    
    // 创建场景按钮事件
    document.getElementById('createLocationBtn').addEventListener('click', () => {
      openCreateLocationModal();
    });
    
    // 创建场景模态框事件
    document.getElementById('createLocationModalClose').addEventListener('click', () => {
      document.getElementById('createLocationModal').classList.remove('show');
    });
    
    document.getElementById('createLocationCancelBtn').addEventListener('click', () => {
      document.getElementById('createLocationModal').classList.remove('show');
    });
    
    document.getElementById('createLocationSaveBtn').addEventListener('click', () => {
      createLocation();
    });
    
    document.getElementById('createLocationModal').addEventListener('click', (e) => {
      if (e.target.id === 'createLocationModal') {
        document.getElementById('createLocationModal').classList.remove('show');
      }
    });
    
    // 创建道具按钮事件
    document.getElementById('createPropsBtn').addEventListener('click', () => {
      openCreatePropsModal();
    });
    
    // 创建道具模态框事件
    document.getElementById('createPropsModalClose').addEventListener('click', () => {
      document.getElementById('createPropsModal').classList.remove('show');
    });
    
    document.getElementById('createPropsCancelBtn').addEventListener('click', () => {
      document.getElementById('createPropsModal').classList.remove('show');
    });
    
    document.getElementById('createPropsSaveBtn').addEventListener('click', () => {
      createPropsItem();
    });
    
    document.getElementById('createPropsModal').addEventListener('click', (e) => {
      if (e.target.id === 'createPropsModal') {
        document.getElementById('createPropsModal').classList.remove('show');
      }
    });

    // ========== 编辑角色功能 ==========
    
    let currentEditingCharacterNodeId = null;
    
    // 打开角色编辑模态框
    function openCharacterEditModal(nodeId, character) {
      currentEditingCharacterNodeId = nodeId;
      
      document.getElementById('editCharacterNameInput').value = character.name || '';
      document.getElementById('editCharacterAgeInput').value = character.age || '';
      document.getElementById('editCharacterIdentityInput').value = character.identity || '';
      document.getElementById('editCharacterPersonalityInput').value = character.personality || '';
      document.getElementById('editCharacterBehaviorInput').value = character.behavior || '';
      document.getElementById('editCharacterOtherInfoInput').value = character.other_info || '';
      document.getElementById('editCharacterSoraCharacterInput').value = character.sora_character || '';
      
      const imagePreview = document.getElementById('editCharacterImagePreview');
      const imagePreviewImg = document.getElementById('editCharacterImagePreviewImg');
      if (character.reference_image) {
        imagePreviewImg.src = character.reference_image;
        imagePreview.style.display = 'block';
      } else {
        imagePreview.style.display = 'none';
      }
      
      const voicePreview = document.getElementById('editCharacterVoicePreview');
      const voicePreviewAudio = document.getElementById('editCharacterVoicePreviewAudio');
      if (character.default_voice) {
        voicePreviewAudio.src = character.default_voice;
        voicePreview.style.display = 'block';
      } else {
        voicePreview.style.display = 'none';
      }
      
      document.getElementById('editCharacterModal').classList.add('show');
    }
    
    // 保存角色编辑
    async function saveCharacterEdit() {
      const nameInput = document.getElementById('editCharacterNameInput');
      const ageInput = document.getElementById('editCharacterAgeInput');
      const identityInput = document.getElementById('editCharacterIdentityInput');
      const personalityInput = document.getElementById('editCharacterPersonalityInput');
      const behaviorInput = document.getElementById('editCharacterBehaviorInput');
      const otherInfoInput = document.getElementById('editCharacterOtherInfoInput');
      const soraCharacterInput = document.getElementById('editCharacterSoraCharacterInput');
      const imageInput = document.getElementById('editCharacterImageInput');
      const voiceInput = document.getElementById('editCharacterVoiceInput');
      const saveBtn = document.getElementById('editCharacterSaveBtn');
      
      const name = nameInput.value.trim();
      if (!name) {
        showToast('请输入角色名称', 'error');
        nameInput.focus();
        return;
      }
      
      const node = state.nodes.find(n => n.id === currentEditingCharacterNodeId);
      if (!node || !node.data || !node.data.id) {
        showToast('找不到角色信息', 'error');
        return;
      }
      
      // 验证图片文件大小
      if (imageInput.files.length > 0) {
        const maxSize = uploadConfig.max_image_size_mb * 1024 * 1024;
        if (imageInput.files[0].size > maxSize) {
          showToast(`图片文件不能超过${uploadConfig.max_image_size_mb}MB`, 'error');
          imageInput.value = '';
          return;
        }
      }
      
      saveBtn.disabled = true;
      saveBtn.textContent = '保存中...';
      
      try {
        const formData = new FormData();
        formData.append('character_id', node.data.id);
        formData.append('name', name);
        if (ageInput.value.trim()) formData.append('age', ageInput.value.trim());
        if (identityInput.value.trim()) formData.append('identity', identityInput.value.trim());
        if (personalityInput.value.trim()) formData.append('personality', personalityInput.value.trim());
        if (behaviorInput.value.trim()) formData.append('behavior', behaviorInput.value.trim());
        if (otherInfoInput.value.trim()) formData.append('other_info', otherInfoInput.value.trim());
        if (soraCharacterInput.value.trim()) formData.append('sora_character', soraCharacterInput.value.trim());
        if (imageInput.files.length > 0) formData.append('reference_image', imageInput.files[0]);
        if (voiceInput.files.length > 0) formData.append('default_voice', voiceInput.files[0]);
        
        const response = await fetch('/api/characters/update', {
          method: 'POST',
          headers: {
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
          },
          body: formData
        });
        
        const result = await response.json();
        
        if (result.code === 0) {
          showToast('角色更新成功', 'success');
          node.data = result.data;
          node.title = result.data.name;
          
          // 保存节点ID，因为稍后会清空 currentEditingCharacterNodeId
          const savedNodeId = currentEditingCharacterNodeId;
          
          // 完全重新渲染节点以显示所有更新的字段
          const el = canvasEl.querySelector(`.node[data-node-id="${savedNodeId}"]`);
          if (el) {
            const character = result.data;
            const nodeBody = el.querySelector('.node-body');
            if (nodeBody) {
              // 重新生成节点内容
              nodeBody.innerHTML = `
                ${character.reference_image ? `
                  <div class="field field-always-visible">
                    <div class="label">参考图</div>
                    <img src="${character.reference_image}" class="preview" style="width: 100%; height: auto; border-radius: 8px; cursor: zoom-in;" />
                  </div>
                ` : ''}
                ${character.age ? `<div class="field field-always-visible"><div class="label">年龄</div><div>${escapeHtml(character.age)}</div></div>` : ''}
                ${character.identity ? `<div class="field field-always-visible"><div class="label">身份/职业</div><div>${escapeHtml(character.identity)}</div></div>` : ''}
                ${character.personality ? `<div class="field field-always-visible"><div class="label">性格</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.personality.slice(0, 100))}${character.personality.length > 100 ? '...' : ''}</div></div>` : ''}
                ${character.behavior ? `<div class="field field-always-visible"><div class="label">行为习惯</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.behavior.slice(0, 100))}${character.behavior.length > 100 ? '...' : ''}</div></div>` : ''}
                ${character.other_info ? `<div class="field field-always-visible"><div class="label">其他信息</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.other_info.slice(0, 100))}${character.other_info.length > 100 ? '...' : ''}</div></div>` : ''}
                <div class="field field-collapsible">
                  <button class="mini-btn character-download-btn" type="button" data-img-url="${character.reference_image}" style="width: 100%;">下载图片</button>
                </div>
                <div class="field field-collapsible btn-row">
                  <button class="mini-btn character-edit-btn" type="button">编辑</button>
                  <button class="mini-btn character-sora-video-btn" type="button" style="${character.sora_character ? 'background: white; color: #111827; border: 1px solid #d1d5db;' : 'background: #8b5cf6; color: white;'}">${character.sora_character ? '重新生成sora角色视频' : '生成sora角色视频'}</button>
                </div>
                <div class="field field-collapsible btn-row" style="display: flex; align-items: center; gap: 8px;">
                  <button class="mini-btn character-create-card-btn" type="button" style="${character.sora_character ? 'background: white; color: #111827; border: 1px solid #d1d5db;' : 'background: #10b981; color: white;'} opacity: 0.5; cursor: not-allowed;" data-can-click="false">${character.sora_character ? '重新生成sora角色卡' : '创建sora角色卡'}</button>
                  <span class="character-card-help-icon" style="display: none; width: 16px; height: 16px; border-radius: 50%; background: #ef4444; color: white; font-size: 12px; line-height: 16px; text-align: center; cursor: help; flex-shrink: 0;" title="如果角色持续创建失败，请尝试更改角色图片 并 重新生成角色视频">?</span>
                </div>
                <div class="character-sora-video-error" style="display: none; color: #dc2626; font-size: 12px; margin-top: 8px; padding: 8px; background: #fee2e2; border-radius: 6px; border: 1px solid #fecaca;"></div>
              `;
              
              // 重新绑定按钮事件
              const editBtn = nodeBody.querySelector('.character-edit-btn');
              const soraVideoBtn = nodeBody.querySelector('.character-sora-video-btn');
              const createCardBtn = nodeBody.querySelector('.character-create-card-btn');
              
              if (editBtn) {
                editBtn.addEventListener('click', (e) => {
                  e.stopPropagation();
                  openCharacterEditModal(savedNodeId, character);
                });
              }
              
              if (soraVideoBtn) {
                soraVideoBtn.addEventListener('click', (e) => {
                  e.stopPropagation();
                  generateSoraCharacterVideo(savedNodeId, character);
                });
              }
              
              if (createCardBtn) {
                createCardBtn.addEventListener('click', (e) => {
                  e.stopPropagation();
                  const canClick = createCardBtn.getAttribute('data-can-click') === 'true';
                  if (!canClick) {
                    showToast('请先连接一个视频节点，或生成角色视频后再创建角色卡', 'warning');
                    return;
                  }
                  createSoraCharacterCard(savedNodeId, character);
                });
              }
              
              // 更新按钮状态
              updateCharacterCardButtonState(savedNodeId);
            }
            
            el.querySelector('.node-title').textContent = `角色: ${result.data.name}`;
          }
          
          document.getElementById('editCharacterModal').classList.remove('show');
          currentEditingCharacterNodeId = null;
          try { autoSaveWorkflow(); } catch(e) {}
        } else {
          showToast(result.message || '更新失败', 'error');
        }
      } catch (error) {
        console.error('更新角色失败:', error);
        showToast('更新失败', 'error');
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '保存';
      }
    }
    
    document.getElementById('editCharacterModalClose').addEventListener('click', () => {
      document.getElementById('editCharacterModal').classList.remove('show');
      currentEditingCharacterNodeId = null;
    });
    
    document.getElementById('editCharacterCancelBtn').addEventListener('click', () => {
      document.getElementById('editCharacterModal').classList.remove('show');
      currentEditingCharacterNodeId = null;
    });
    
    document.getElementById('editCharacterSaveBtn').addEventListener('click', saveCharacterEdit);
    
    document.getElementById('editCharacterModal').addEventListener('click', (e) => {
      if (e.target.id === 'editCharacterModal') {
        document.getElementById('editCharacterModal').classList.remove('show');
        currentEditingCharacterNodeId = null;
      }
    });

    // ========== 生成Sora角色视频功能 ==========
    
    async function generateSoraCharacterVideo(characterNodeId, character) {
      if (!character || !character.name) {
        showToast('角色信息不完整', 'error');
        return;
      }
      
      if (!character.reference_image) {
        showToast('角色缺少参考图，无法生成视频', 'error');
        return;
      }
      
      const characterNode = state.nodes.find(n => n.id === characterNodeId);
      if (!characterNode) {
        showToast('找不到角色节点', 'error');
        return;
      }
      
      const soraVideoBtn = document.querySelector(`.node[data-node-id="${characterNodeId}"] .character-sora-video-btn`);
      const errorEl = document.querySelector(`.node[data-node-id="${characterNodeId}"] .character-sora-video-error`);
      
      if (errorEl) {
        errorEl.style.display = 'none';
        errorEl.textContent = '';
      }
      
      if (soraVideoBtn) {
        soraVideoBtn.disabled = true;
        soraVideoBtn.textContent = '生成中...';
      }
      
      try {
        const characterName = character.name;
        const styleName = state.style.name || '默认风格';
        const prompt = `说话："我是${characterName}，欢迎大家，非常感谢大家，欢迎大家，非常感谢大家，谢谢！" 然后缓慢转一圈360度全方位展示身体。视频风格为 ${styleName}`;
        const imageUrl = character.reference_image;
        const duration = 10;
        const ratio = state.ratio || '16:9';
        
        showToast('正在生成Sora角色视频...', 'info');
        
        const userId = localStorage.getItem('user_id') || '1';
        const authToken = localStorage.getItem('auth_token') || '';
        const form = new FormData();
        
        form.append('image_urls', imageUrl);
        form.append('prompt', prompt);
        form.append('duration_seconds', duration);
        form.append('count', 1);
        form.append('ratio', ratio);
        
        if (userId) {
          form.append('user_id', userId);
        }
        if (authToken) {
          form.append('auth_token', authToken);
        }
        
        const res = await fetch('/api/ai-app-run-image', {
          method: 'POST',
          body: form
        });
        
        const data = await res.json();
        
        if (!data.project_ids || data.project_ids.length === 0) {
          throw new Error(data.detail || data.message || '提交任务失败');
        }
        
        const projectIds = data.project_ids;
        showToast('视频生成任务已提交，正在处理...', 'info');
        
        pollVideoStatus(
          projectIds,
          (msg) => {
            if (soraVideoBtn) {
              soraVideoBtn.textContent = msg;
            }
          },
          async (statusResult) => {
            console.log('Sora character video generation status result:', statusResult);
            
            let videoUrls = [];
            let videoProjectId = null;
            
            if (statusResult.tasks && Array.isArray(statusResult.tasks)) {
              const successTasks = statusResult.tasks.filter(task => task.status === 'SUCCESS' && task.result);
              videoUrls = successTasks.map(task => normalizeVideoUrl(task.result)).filter(Boolean);
            } else {
              const rawResults = extractResultsArray(statusResult);
              videoUrls = Array.isArray(rawResults)
                ? rawResults.map(normalizeVideoUrl).filter(Boolean)
                : [];
            }
            
            // 使用传入的 projectIds 作为 project_id
            if (projectIds && projectIds.length > 0) {
              videoProjectId = projectIds[0];
            }
            
            console.log('Extracted video URLs:', videoUrls);
            console.log('Video project ID:', videoProjectId);
            
            if (videoUrls.length === 0) {
              const errorMsg = 'Sora角色视频生成失败，未获取到结果';
              showToast(errorMsg, 'error');
              if (errorEl) {
                errorEl.textContent = errorMsg;
                errorEl.style.display = 'block';
              }
              if (soraVideoBtn) {
                soraVideoBtn.disabled = false;
                soraVideoBtn.textContent = '生成sora角色视频';
              }
              return;
            }
            
            const videoUrl = videoUrls[0];
            const offsetX = 350;
            const offsetY = 0;
            const videoNodeX = characterNode.x + offsetX;
            const videoNodeY = characterNode.y + offsetY;
            
            const newVideoNodeId = createVideoNode({ 
              x: videoNodeX, 
              y: videoNodeY 
            });
            
            const newVideoNode = state.nodes.find(n => n.id === newVideoNodeId);
            if (newVideoNode) {
              newVideoNode.data.url = videoUrl;
              newVideoNode.data.name = `${characterName}角色视频`;
              newVideoNode.data.project_id = videoProjectId;
              newVideoNode.title = newVideoNode.data.name;
              
              const newNodeEl = canvasEl.querySelector(`.node[data-node-id="${newVideoNodeId}"]`);
              if (newNodeEl) {
                const titleEl = newNodeEl.querySelector('.node-title');
                if (titleEl) titleEl.textContent = newVideoNode.title;
                
                const nameEl = newNodeEl.querySelector('.video-name');
                if (nameEl) nameEl.textContent = newVideoNode.data.name;
                
                const previewField = newNodeEl.querySelector('.video-preview-field');
                const thumbVideo = newNodeEl.querySelector('.video-thumb');
                if (previewField && thumbVideo) {
                  thumbVideo.src = proxyImageUrl(videoUrl);
                  previewField.style.display = 'block';
                }
              }
              
              state.connections.push({
                id: state.nextConnId++,
                from: characterNodeId,
                to: newVideoNodeId
              });
              
              // 更新角色卡按钮状态
              updateCharacterCardButtonState(characterNodeId);
              
              console.log(`Created Sora character video node ${newVideoNodeId} with project_id:`, videoProjectId);
              
              // 延迟渲染连接，确保DOM元素已完全加载（特别是在节点很多的情况下）
              setTimeout(() => {
                renderConnections();
                renderImageConnections();
                renderFirstFrameConnections();
                renderVideoConnections();
                renderMinimap();
              }, 100);
            }
            
            showToast('Sora角色视频生成成功！现在可以点击"创建sora角色卡"按钮', 'success');
            try { autoSaveWorkflow(); } catch(e) { console.error('Auto save failed:', e); }
            
            if (soraVideoBtn) {
              soraVideoBtn.disabled = false;
              soraVideoBtn.textContent = '生成sora角色视频';
            }
          },
          (error) => {
            const errorMsg = `生成失败: ${error}`;
            showToast(errorMsg, 'error');
            if (errorEl) {
              errorEl.textContent = errorMsg;
              errorEl.style.display = 'block';
            }
            if (soraVideoBtn) {
              soraVideoBtn.disabled = false;
              soraVideoBtn.textContent = '生成sora角色视频';
            }
          }
        );
        
      } catch (error) {
        console.error('生成Sora角色视频失败:', error);
        const errorMsg = `生成失败: ${error.message || error}`;
        showToast(errorMsg, 'error');
        if (errorEl) {
          errorEl.textContent = errorMsg;
          errorEl.style.display = 'block';
        }
        if (soraVideoBtn) {
          soraVideoBtn.disabled = false;
          soraVideoBtn.textContent = '生成sora角色视频';
        }
      }
    }

    // ========== 创建Sora角色卡功能 ==========
    
    async function createSoraCharacterCard(characterNodeId, character) {
      if (!character || !character.name) {
        showToast('角色信息不完整', 'error');
        return;
      }
      
      const characterNode = state.nodes.find(n => n.id === characterNodeId);
      if (!characterNode) {
        showToast('找不到角色节点', 'error');
        return;
      }
      
      const connectedVideoNode = findConnectedVideoNode(characterNodeId);
      if (!connectedVideoNode) {
        showToast('请先连接一个视频节点', 'error');
        return;
      }
      
      const videoProjectId = connectedVideoNode.data.project_id;
      if (!videoProjectId) {
        showToast('视频节点缺少project_id，无法创建角色卡', 'error');
        return;
      }
      
      const createCardBtn = document.querySelector(`.node[data-node-id="${characterNodeId}"] .character-create-card-btn`);
      if (createCardBtn) {
        createCardBtn.disabled = true;
        createCardBtn.textContent = '创建中...';
      }
      
      try {
        showToast('正在创建角色卡...', 'info');
        
        const userId = localStorage.getItem('user_id') || '1';
        const authToken = localStorage.getItem('auth_token') || '';
        
        // 从数据库记录ID获取实际的Duomi API任务ID
        // videoProjectId 是数据库记录ID，需要查询数据库获取实际的 project_id
        let actualTaskId = videoProjectId;
        try {
          // 调用后端接口获取数据库记录详情
          const detailUrl = `/api/ai-tools/detail/${videoProjectId}`;
          const detailRes = await fetch(detailUrl, {
            headers: {
              'Authorization': authToken ? `Bearer ${authToken}` : '',
              'X-User-Id': userId
            }
          });
          
          if (detailRes.ok) {
            const detailData = await detailRes.json();
            if (detailData.success && detailData.data && detailData.data.project_id) {
              actualTaskId = detailData.data.project_id;
              console.log(`Resolved database record ID ${videoProjectId} to actual task ID: ${actualTaskId}`);
            } else {
              console.warn('Database record has no project_id, using record ID as fallback');
            }
          } else {
            console.warn('Failed to fetch record detail, using record ID as fallback');
          }
        } catch (resolveError) {
          console.warn('Failed to resolve task ID, using original value:', resolveError);
        }
        
        const characterCardForm = new FormData();
        characterCardForm.append('timestamps', '1,3');
        characterCardForm.append('from_task', actualTaskId);
        
        if (userId) {
          characterCardForm.append('user_id', userId);
        }
        if (authToken) {
          characterCardForm.append('auth_token', authToken);
        }
        
        const characterCardRes = await fetch('/api/create-character', {
          method: 'POST',
          body: characterCardForm
        });
        
        const characterCardData = await characterCardRes.json();
        
        if (characterCardData.success && characterCardData.task_id) {
          const taskId = characterCardData.task_id;
          console.log('Character card creation task submitted:', taskId);
          
          showToast('角色卡创建任务已提交，正在处理...', 'info');
          
          if (createCardBtn) {
            createCardBtn.textContent = '处理中...';
          }
          
          // 轮询状态直到完成（10分钟超时）
          const maxAttempts = 600;
          let attempts = 0;
          
          while (attempts < maxAttempts) {
            await new Promise(resolve => setTimeout(resolve, 2000));
            attempts++;
            
            try {
              const statusUrl = `/api/character-status/${taskId}${authToken ? '?auth_token=' + authToken : ''}`;
              const statusRes = await fetch(statusUrl);
              const statusData = await statusRes.json();
              
              console.log(`Character card status check ${attempts}:`, statusData);
              
              if (statusData.status === 'SUCCESS') {
                // 获取角色卡ID
                if (statusData.characters && statusData.characters.length > 0) {
                  const characterCardId = statusData.characters[0].id;
                  console.log('Character card created successfully, ID:', characterCardId);
                  
                  // 保存角色卡ID到角色数据
                  characterNode.data.sora_character = characterCardId;
                  character.sora_character = characterCardId;
                  
                  // 更新数据库中的角色记录
                  if (character.id) {
                    try {
                      const updateForm = new FormData();
                      updateForm.append('character_id', character.id);
                      updateForm.append('name', character.name);
                      updateForm.append('sora_character', characterCardId);
                      
                      const updateResponse = await fetch('/api/characters/update', {
                        method: 'POST',
                        headers: {
                          'Authorization': localStorage.getItem('auth_token') || '',
                          'X-User-Id': localStorage.getItem('user_id') || '1'
                        },
                        body: updateForm
                      });
                      
                      if (updateResponse.ok) {
                        console.log('Character sora_character updated in database');
                      } else {
                        console.error('Failed to update character in database');
                      }
                    } catch (dbError) {
                      console.error('Error updating character in database:', dbError);
                    }
                  }
                  
                  showToast('角色卡创建成功！ID: ' + characterCardId, 'success');
                  
                  const helpIcon = document.querySelector(`.node[data-node-id="${characterNodeId}"] .character-card-help-icon`);
                  if (helpIcon) {
                    helpIcon.style.display = 'none';
                  }
                  
                  // 成功时更新按钮状态
                  if (createCardBtn) {
                    createCardBtn.disabled = false;
                    createCardBtn.textContent = '重新生成sora角色卡';
                    createCardBtn.style.background = 'white';
                    createCardBtn.style.color = '#111827';
                    createCardBtn.style.border = '1px solid #d1d5db';
                  }
                  
                  try { autoSaveWorkflow(); } catch(e) { console.error('Auto save failed:', e); }
                } else {
                  showToast('角色卡创建完成，但未获取到角色ID', 'warning');
                  // 即使没有获取到ID，也恢复按钮状态
                  if (createCardBtn) {
                    createCardBtn.disabled = false;
                    createCardBtn.textContent = '创建角色卡';
                  }
                }
                break;
              } else if (statusData.status === 'FAILED' || statusData.status === 'ERROR') {
                showToast('角色卡创建失败: ' + (statusData.error || '未知错误'), 'error');
                const helpIcon = document.querySelector(`.node[data-node-id="${characterNodeId}"] .character-card-help-icon`);
                if (helpIcon) {
                  helpIcon.style.display = 'block';
                }
                // 失败时恢复按钮状态，允许重试
                if (createCardBtn) {
                  createCardBtn.disabled = false;
                  createCardBtn.textContent = '创建角色卡';
                }
                break;
              } else {
                // 仍在处理中
                if (createCardBtn) {
                  createCardBtn.textContent = `处理中(${attempts}/${maxAttempts})...`;
                }
              }
            } catch (statusError) {
              console.error('Status check error:', statusError);
              if (attempts >= maxAttempts) {
                showToast('角色卡状态检查失败', 'error');
              }
            }
          }
          
          if (attempts >= maxAttempts) {
            showToast('角色卡创建超时，请稍后在编辑界面查看', 'warning');
            const helpIcon = document.querySelector(`.node[data-node-id="${characterNodeId}"] .character-card-help-icon`);
            if (helpIcon) {
              helpIcon.style.display = 'block';
            }
            // 超时时恢复按钮状态，允许重试
            if (createCardBtn) {
              createCardBtn.disabled = false;
              createCardBtn.textContent = '创建角色卡';
            }
          }
        } else {
          console.error('Character card creation failed:', characterCardData);
          const errorMsg = characterCardData.detail || characterCardData.message || '未知错误';
          showToast('角色卡创建失败: ' + errorMsg, 'error');
          const helpIcon = document.querySelector(`.node[data-node-id="${characterNodeId}"] .character-card-help-icon`);
          if (helpIcon) {
            helpIcon.style.display = 'block';
          }
          // 失败时恢复按钮状态，不要禁用，允许重试
          if (createCardBtn) {
            createCardBtn.disabled = false;
            createCardBtn.textContent = '创建角色卡';
          }
        }
      } catch (error) {
        console.error('创建角色卡失败:', error);
        showToast('创建角色卡失败: ' + (error.message || error), 'error');
        const helpIcon = document.querySelector(`.node[data-node-id="${characterNodeId}"] .character-card-help-icon`);
        if (helpIcon) {
          helpIcon.style.display = 'block';
        }
        // 失败时恢复按钮状态，不要禁用，允许重试
        if (createCardBtn) {
          createCardBtn.disabled = false;
          createCardBtn.textContent = '创建角色卡';
        }
      } finally {
        // 只在成功时才更新按钮状态为禁用
        // updateCharacterCardButtonState(characterNodeId);
      }
    }
    
    function findConnectedVideoNode(characterNodeId) {
      const connection = state.connections.find(conn => conn.from === characterNodeId);
      if (!connection) return null;
      
      const connectedNode = state.nodes.find(n => n.id === connection.to);
      if (connectedNode && connectedNode.type === 'video') {
        return connectedNode;
      }
      
      return null;
    }
    
    function updateCharacterCardButtonState(characterNodeId) {
      const createCardBtn = document.querySelector(`.node[data-node-id="${characterNodeId}"] .character-create-card-btn`);
      if (!createCardBtn) return;
      
      const characterNode = state.nodes.find(n => n.id === characterNodeId);
      const hasSoraCharacter = characterNode && characterNode.data && characterNode.data.sora_character;
      const connectedVideoNode = findConnectedVideoNode(characterNodeId);
      
      if (hasSoraCharacter) {
        createCardBtn.textContent = '重新生成sora角色卡';
        createCardBtn.style.background = 'white';
        createCardBtn.style.color = '#111827';
        createCardBtn.style.border = '1px solid #d1d5db';
      } else {
        createCardBtn.textContent = '创建sora角色卡';
        createCardBtn.style.background = '#10b981';
        createCardBtn.style.color = 'white';
        createCardBtn.style.border = 'none';
      }
      
      if (connectedVideoNode && connectedVideoNode.data.project_id) {
        createCardBtn.setAttribute('data-can-click', 'true');
        createCardBtn.style.opacity = '1';
        createCardBtn.style.cursor = 'pointer';
      } else {
        createCardBtn.setAttribute('data-can-click', 'false');
        createCardBtn.style.opacity = '0.5';
        createCardBtn.style.cursor = 'not-allowed';
      }
    }

    // 页面加载时初始化
    (async function init(){
      // 初始化世界选择器
      initWorldSelector();
      
      // 初始化视频提示词后缀
      if(typeof initVideoPromptSuffix === 'function'){
        initVideoPromptSuffix();
      }
      
      const workflowId = getWorkflowIdFromUrl();
      if(workflowId){
        await loadWorkflow(workflowId);
        startAutoSave();
      }
    })();

    // 页面关闭前保存
    window.addEventListener('beforeunload', () => {
      stopAutoSave();
    });

    // 一键生成素材按钮点击事件
    const agentBtnMaterial = document.getElementById('agentBtnMaterial');
    if (agentBtnMaterial) {
      agentBtnMaterial.addEventListener('click', async () => {
        const authToken = localStorage.getItem('auth_token') || '';
        const userId = localStorage.getItem('user_id') || '';
        
        if (!userId) {
          showToast('请先登录', 'error');
          return;
        }
        
        try {
          const response = await fetch('/api/script-writer-url', {
            headers: {
              'Authorization': authToken,
              'X-User-Id': userId
            }
          });
          const result = await response.json();
          
          if (result.code === 0 && result.data && result.data.url) {
            const baseUrl = result.data.url;
            let url = `${baseUrl}?auth_token=${encodeURIComponent(authToken)}&user_id=${encodeURIComponent(userId)}`;
            
            // 如果已选择世界，添加 world_id 参数
            if (state.defaultWorldId) {
              url += `&world_id=${encodeURIComponent(state.defaultWorldId)}`;
            }
            
            window.open(url, '_blank');
          } else {
            showToast(result.message || '获取服务地址失败', 'error');
          }
        } catch (error) {
          console.error('Failed to get script writer url:', error);
          showToast('网络错误', 'error');
        }
      });
    }
