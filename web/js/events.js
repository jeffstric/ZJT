    const addBtn = document.getElementById('addBtn');
    const addMenu = document.getElementById('addMenu');

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

    document.getElementById('menuAddAsset').addEventListener('click', () => {
      // 素材库 - 空实现
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

    // 点击其他地方关闭菜单
    document.addEventListener('click', (e) => {
      if(!e.target.closest('#addBtnContainer')){
        addMenu.classList.remove('show');
      }
    });

    ratioSelectEl.addEventListener('change', () => {
      state.ratio = ratioSelectEl.value;
    });


    canvasContainer.addEventListener('mousedown', (e) => {
      if(e.target === canvasEl || e.target === canvasContainer || e.target === canvasWorld){
        clearSelection();
        state.selectedConnId = null;
        state.selectedImgConnId = null;
        hideConnDeleteBtn();
        renderConnections();
        renderImageConnections();
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
      }
    });

    // 键盘删除连接线和时间轴片段
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
        } else if(state.timeline.selectedClipId !== null){
          e.preventDefault();
          removeFromTimeline(state.timeline.selectedClipId);
          state.timeline.selectedClipId = null;
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
      // 平移画布
      if(state.panning){
        const dx = e.clientX - state.panning.startX;
        const dy = e.clientY - state.panning.startY;
        state.panX = Math.min(0, state.panning.origPanX + dx);
        state.panY = Math.min(0, state.panning.origPanY + dy);
        applyTransform();
        renderImageConnections();
        // 更新删除按钮位置（如果有选中的连接线）
        if(state.selectedConnId !== null){
          renderConnections();
        }
      }
      // 拖动节点
      if(state.drag){
        const n = state.nodes.find(x => x.id === state.drag.nodeId);
        if(!n) return;
        const dx = e.clientX - state.drag.startX;
        const dy = e.clientY - state.drag.startY;
        n.x = Math.max(20, state.drag.origX + dx);
        n.y = Math.max(20, state.drag.origY + dy);
        const el = canvasEl.querySelector(`.node[data-node-id="${n.id}"]`);
        if(el){
          el.style.left = n.x + 'px';
          el.style.top = n.y + 'px';
        }
        renderConnections();
        renderImageConnections();
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
        
        // 如果从图片节点拖拽，查找图片输入端口
        if(fromNode && fromNode.type === 'image'){
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
        }

        
        // 如果从图生视频节点拖拽，查找视频节点输入端口
        // 如果从剧本节点拖拽，查找分镜组节点输入端口
        if(fromNode && (fromNode.type === 'image_to_video' || fromNode.type === 'script')){
          let nearestPort = null;
          let nearestDist = 50;
          const targetType = fromNode.type === 'image_to_video' ? 'video' : 'shot_group';
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
        
        renderConnections({
          fromX: fromPos.x,
          fromY: fromPos.y,
          toX: targetX,
          toY: targetY
        });
        renderImageConnections();
      }
    });

    window.addEventListener('mouseup', (e) => {
      if(state.drag){
        state.drag = null;
        renderMinimap();
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
        
        // 如果从图片节点拖拽，查找图片输入端口
        if(fromNode && fromNode.type === 'image'){
          let nearestImgPort = null;
          let nearestDist = 50;
          
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
                if(dist < nearestDist){
                  nearestDist = dist;
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
                if(dist < nearestDist){
                  nearestDist = dist;
                  nearestImgPort = { nodeId: node.id, portType: 'end' };
                }
              }
            }
          }
          
          // 如果找到目标端口，创建图片连接
          if(nearestImgPort){
            const exists = state.imageConnections.some(c => c.to === nearestImgPort.nodeId && c.portType === nearestImgPort.portType);
            if(!exists){
              state.imageConnections.push({
                id: state.nextImgConnId++,
                from: state.connecting.fromId,
                to: nearestImgPort.nodeId,
                portType: nearestImgPort.portType
              });
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
        state.timeline.selectedClipId = null;
        renderTimeline();
        showToast('时间轴已清空', 'success');
        try{ autoSaveWorkflow(); } catch(e){}
      }
    });

    // ========== 角色和场景选择功能 ==========
    
    // 打开角色选择模态框
    async function openCharacterModal() {
      const modal = document.getElementById('characterModal');
      const worldSelect = document.getElementById('characterWorldSelect');
      
      // 加载世界列表
      await loadWorlds(worldSelect);
      
      modal.classList.add('show');
      modal.setAttribute('aria-hidden', 'false');
    }
    
    // 打开场景选择模态框
    async function openLocationModal() {
      const modal = document.getElementById('locationModal');
      const worldSelect = document.getElementById('locationWorldSelect');
      
      // 加载世界列表
      await loadWorlds(worldSelect);
      
      modal.classList.add('show');
      modal.setAttribute('aria-hidden', 'false');
    }
    
    // 加载世界列表
    async function loadWorlds(selectElement) {
      try {
        const response = await fetch('/api/worlds', {
          headers: {
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
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
        }
      } catch (error) {
        console.error('加载世界列表失败:', error);
        showToast('加载世界列表失败', 'error');
      }
    }
    
    // 加载角色列表
    async function loadCharacters(worldId, keyword = '') {
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
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
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
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
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
                createLocationNode(location);
                document.getElementById('locationModal').classList.remove('show');
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
        console.error('加载场景列表失败:', error);
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
          <div class="node-title">角色: ${escapeHtml(character.name)}</div>
          <button class="icon-btn" data-action="delete" title="删除">×</button>
        </div>
        <div class="node-body">
          ${character.reference_image ? `
            <div class="field">
              <div class="label">参考图</div>
              <img src="${character.reference_image}" class="preview" style="width: 100%; height: auto; border-radius: 8px; cursor: zoom-in;" />
            </div>
          ` : ''}
          ${character.age ? `<div class="field"><div class="label">年龄</div><div>${escapeHtml(character.age)}</div></div>` : ''}
          ${character.identity ? `<div class="field"><div class="label">身份/职业</div><div>${escapeHtml(character.identity)}</div></div>` : ''}
          ${character.personality ? `<div class="field"><div class="label">性格</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.personality.slice(0, 100))}${character.personality.length > 100 ? '...' : ''}</div></div>` : ''}
          ${character.behavior ? `<div class="field"><div class="label">行为习惯</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.behavior.slice(0, 100))}${character.behavior.length > 100 ? '...' : ''}</div></div>` : ''}
          ${character.other_info ? `<div class="field"><div class="label">其他信息</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.other_info.slice(0, 100))}${character.other_info.length > 100 ? '...' : ''}</div></div>` : ''}
          <div class="field btn-row">
            <button class="mini-btn character-edit-btn" type="button">编辑</button>
          </div>
        </div>
        <div class="port output" data-port="output" title="输出"></div>
      `;
      
      canvasEl.appendChild(el);
      
      // 绑定事件
      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('[data-action="delete"]');
      const editBtn = el.querySelector('.character-edit-btn');
      const outputPort = el.querySelector('.port.output');
      
      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });
      
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openCharacterEditModal(id, character);
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
        setSelected(id);
        state.drag = {
          nodeId: id,
          startX: e.clientX,
          startY: e.clientY,
          origX: node.x,
          origY: node.y
        };
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
      const x = 60 + (state.nodes.length % 3) * 340;
      const y = 60 + Math.floor(state.nodes.length / 3) * 280;
      
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
          <div class="node-title">角色: ${escapeHtml(character.name)}</div>
          <button class="icon-btn" data-action="delete" title="删除">×</button>
        </div>
        <div class="node-body">
          ${character.reference_image ? `
            <div class="field">
              <div class="label">参考图</div>
              <img src="${character.reference_image}" class="preview" style="width: 100%; height: auto; border-radius: 8px; cursor: zoom-in;" />
            </div>
          ` : ''}
          ${character.age ? `<div class="field"><div class="label">年龄</div><div>${escapeHtml(character.age)}</div></div>` : ''}
          ${character.identity ? `<div class="field"><div class="label">身份/职业</div><div>${escapeHtml(character.identity)}</div></div>` : ''}
          ${character.personality ? `<div class="field"><div class="label">性格</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.personality.slice(0, 100))}${character.personality.length > 100 ? '...' : ''}</div></div>` : ''}
          ${character.behavior ? `<div class="field"><div class="label">行为习惯</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.behavior.slice(0, 100))}${character.behavior.length > 100 ? '...' : ''}</div></div>` : ''}
          ${character.other_info ? `<div class="field"><div class="label">其他信息</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(character.other_info.slice(0, 100))}${character.other_info.length > 100 ? '...' : ''}</div></div>` : ''}
          <div class="field btn-row">
            <button class="mini-btn character-edit-btn" type="button">编辑</button>
          </div>
        </div>
        <div class="port output" data-port="output" title="输出"></div>
      `;
      
      canvasEl.appendChild(el);
      
      // 绑定事件
      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('[data-action="delete"]');
      const editBtn = el.querySelector('.character-edit-btn');
      const outputPort = el.querySelector('.port.output');
      
      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });
      
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openCharacterEditModal(id, character);
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
        setSelected(id);
        state.drag = {
          nodeId: id,
          startX: e.clientX,
          startY: e.clientY,
          origX: node.x,
          origY: node.y
        };
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
          <div class="node-title">场景: ${escapeHtml(location.name)}</div>
          <button class="icon-btn" data-action="delete" title="删除">×</button>
        </div>
        <div class="node-body">
          ${location.reference_image ? `
            <div class="field">
              <div class="label">参考图</div>
              <img src="${location.reference_image}" class="preview" style="width: 100%; height: auto; border-radius: 8px; cursor: zoom-in;" />
            </div>
          ` : ''}
          ${location.description ? `<div class="field"><div class="label">描述</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(location.description)}</div></div>` : ''}
        </div>
        <div class="port output" data-port="output" title="输出"></div>
      `;
      
      canvasEl.appendChild(el);
      
      // 绑定事件
      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('[data-action="delete"]');
      const outputPort = el.querySelector('.port.output');
      
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
        setSelected(id);
        state.drag = {
          nodeId: id,
          startX: e.clientX,
          startY: e.clientY,
          origX: node.x,
          origY: node.y
        };
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
      const x = 60 + (state.nodes.length % 3) * 340;
      const y = 60 + Math.floor(state.nodes.length / 3) * 280;
      
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
          <div class="node-title">场景: ${escapeHtml(location.name)}</div>
          <button class="icon-btn" data-action="delete" title="删除">×</button>
        </div>
        <div class="node-body">
          ${location.reference_image ? `
            <div class="field">
              <div class="label">参考图</div>
              <img src="${location.reference_image}" class="preview" style="width: 100%; height: auto; border-radius: 8px; cursor: zoom-in;" />
            </div>
          ` : ''}
          ${location.description ? `<div class="field"><div class="label">描述</div><div style="font-size: 12px; line-height: 1.4;">${escapeHtml(location.description)}</div></div>` : ''}
        </div>
        <div class="port output" data-port="output" title="输出"></div>
      `;
      
      canvasEl.appendChild(el);
      
      // 绑定事件
      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('[data-action="delete"]');
      const outputPort = el.querySelector('.port.output');
      
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
        setSelected(id);
        state.drag = {
          nodeId: id,
          startX: e.clientX,
          startY: e.clientY,
          origX: node.x,
          origY: node.y
        };
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
          document.getElementById('createWorldModal').classList.remove('show');
          
          // 重新加载世界列表
          if (currentWorldSelectElement) {
            await loadWorlds(currentWorldSelectElement);
            // 自动选中新创建的世界
            currentWorldSelectElement.value = result.data.id;
            
            // 触发change事件以加载对应的角色或场景列表
            const event = new Event('change');
            currentWorldSelectElement.dispatchEvent(event);
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
    document.getElementById('createCharacterVoiceInput').addEventListener('change', (e) => {
      const file = e.target.files[0];
      const voicePreview = document.getElementById('createCharacterVoicePreview');
      const voicePreviewAudio = document.getElementById('createCharacterVoicePreviewAudio');
      
      if (file) {
        const url = URL.createObjectURL(file);
        voicePreviewAudio.src = url;
        voicePreview.style.display = 'block';
      } else {
        voicePreviewAudio.src = '';
        voicePreview.style.display = 'none';
      }
    });
    
    // 编辑角色音频文件选择预览
    document.getElementById('editCharacterVoiceInput').addEventListener('change', (e) => {
      const file = e.target.files[0];
      const voicePreview = document.getElementById('editCharacterVoicePreview');
      const voicePreviewAudio = document.getElementById('editCharacterVoicePreviewAudio');
      
      if (file) {
        const url = URL.createObjectURL(file);
        voicePreviewAudio.src = url;
        voicePreview.style.display = 'block';
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
    
    // ========== 创建场景功能 ==========
    
    // 打开创建场景模态框
    function openCreateLocationModal() {
      const worldId = document.getElementById('locationWorldSelect').value;
      if (!worldId) {
        showToast('请先选择世界', 'error');
        return;
      }
      
      document.getElementById('createLocationNameInput').value = '';
      document.getElementById('createLocationDescInput').value = '';
      document.getElementById('createLocationImageInput').value = '';
      document.getElementById('createLocationModal').classList.add('show');
    }
    
    // 创建场景
    async function createLocation() {
      const worldId = document.getElementById('locationWorldSelect').value;
      const nameInput = document.getElementById('createLocationNameInput');
      const descInput = document.getElementById('createLocationDescInput');
      const imageInput = document.getElementById('createLocationImageInput');
      const saveBtn = document.getElementById('createLocationSaveBtn');
      
      const name = nameInput.value.trim();
      if (!name) {
        showToast('请输入场景名称', 'error');
        nameInput.focus();
        return;
      }
      
      saveBtn.disabled = true;
      saveBtn.textContent = '创建中...';
      
      try {
        const formData = new FormData();
        formData.append('world_id', worldId);
        formData.append('name', name);
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
          
          document.getElementById('createLocationModal').classList.remove('show');
          
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
          
          const el = canvasEl.querySelector(`.node[data-node-id="${currentEditingCharacterNodeId}"]`);
          if (el) {
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

    // 页面加载时初始化
    (async function init(){
      const workflowId = getWorkflowIdFromUrl();
      if(workflowId){
        await loadWorkflow(workflowId);
        // 启动自动保存
        startAutoSave();
      }
    })();

    // 页面关闭前保存
    window.addEventListener('beforeunload', () => {
      stopAutoSave();
    });
