    // ============ Debug 模式功能 ============
    
    // 为节点添加调试按钮
    function addDebugButtonToNode(nodeEl, node) {
      const headerEl = nodeEl.querySelector('.node-header');
      if (!headerEl) return;
      
      // 检查是否已存在调试按钮
      let debugBtn = headerEl.querySelector('.node-debug-btn');
      if (!debugBtn) {
        debugBtn = document.createElement('button');
        debugBtn.className = 'icon-btn node-debug-btn';
        debugBtn.title = '调试：输出节点内容';
        debugBtn.textContent = '🐛';
        debugBtn.style.marginRight = '4px';
        debugBtn.style.display = state.debugMode ? 'block' : 'none';
        
        // 点击输出节点信息
        debugBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          console.log('%c[Node Debug] 节点信息:', 'color: #22c55e; font-weight: bold; font-size: 14px;');
          console.log('ID:', node.id);
          console.log('Type:', node.type);
          console.log('Title:', node.title);
          console.log('Position:', { x: node.x, y: node.y });
          console.log('Data:', node.data);
          console.log('完整节点对象:', node);
          showToast(`节点 ${node.title} 信息已输出到控制台`, 'info');
        });
        
        // 查找按钮容器（场景节点等有按钮容器的情况）
        const btnContainer = headerEl.querySelector('div[style*="display: flex"]');
        if (btnContainer) {
          // 插入到按钮容器的第一个位置
          btnContainer.insertBefore(debugBtn, btnContainer.firstChild);
        } else {
          // 没有按钮容器，查找第一个按钮并插入其前面
          const firstBtn = headerEl.querySelector('.icon-btn');
          if (firstBtn && firstBtn.parentNode === headerEl) {
            headerEl.insertBefore(debugBtn, firstBtn);
          } else {
            headerEl.appendChild(debugBtn);
          }
        }
      }
      
      return debugBtn;
    }
    
    // ============ Debug 模式功能结束 ============
    
    // 收集分镜节点中所有参考图片URL（角色、场景、道具）用于宫格生图
    // 返回 URL 列表而非 File 对象，避免不必要的下载和上传
    async function collectReferenceImagesForGrid(allShotFrameNodes) {
      const referenceImageUrls = [];  // 存储URL而非File
      const promptSuffix = [];
      let imageIndex = 1;
      const collectedCharacters = new Set();
      const collectedLocations = new Set();
      const collectedProps = new Set();

      if (!state.defaultWorldId) {
        console.warn('[宫格生图] 未选择世界，无法获取参考图片');
        return { referenceImageUrls, promptSuffix };
      }

      const worldId = state.defaultWorldId;
      const userId = localStorage.getItem('user_id') || '1';
      const authToken = localStorage.getItem('auth_token') || '';

      for (const shotNode of allShotFrameNodes) {
        const imagePrompt = shotNode.data.imagePrompt || '';
        const shotData = shotNode.data.shotJson || {};

        // 1. 提取角色名并获取参考图URL
        const characterPattern = /【【([^】]+)】】/g;
        let match;
        while ((match = characterPattern.exec(imagePrompt)) !== null) {
          const characterName = match[1].trim();
          if (characterName && !collectedCharacters.has(characterName)) {
            collectedCharacters.add(characterName);
            try {
              const response = await fetch(`/api/characters?world_id=${worldId}&page=1&page_size=100&keyword=${encodeURIComponent(characterName)}`, {
                headers: {
                  'Authorization': authToken,
                  'X-User-Id': userId
                }
              });
              if (response.ok) {
                const result = await response.json();
                if (result.code === 0 && result.data && Array.isArray(result.data.data) && result.data.data.length > 0) {
                  const matchedChar = result.data.data.find(c => c.name === characterName) || result.data.data[0];
                  if (matchedChar && matchedChar.reference_image) {
                    referenceImageUrls.push(matchedChar.reference_image);
                    promptSuffix.push(`图${imageIndex}是${characterName}`);
                    imageIndex++;
                    console.log(`[宫格生图] 收集角色参考图URL: ${characterName}`);
                  }
                }
              }
            } catch (error) {
              console.error(`[宫格生图] 获取角色 ${characterName} 参考图失败:`, error);
            }
          }
        }

        // 2. 添加场景参考图URL
        if (shotData.db_location_id && !collectedLocations.has(shotData.db_location_id)) {
          collectedLocations.add(shotData.db_location_id);
          try {
            const response = await fetch(`/api/location/${shotData.db_location_id}`, {
              headers: {
                'Authorization': authToken,
                'X-User-Id': userId
              }
            });
            if (response.ok) {
              const result = await response.json();
              if (result.code === 0 && result.data && result.data.reference_image) {
                referenceImageUrls.push(result.data.reference_image);
                const locationName = result.data.name || shotData.location_name || '场景';
                promptSuffix.push(`图${imageIndex}是${locationName}`);
                imageIndex++;
                console.log(`[宫格生图] 收集场景参考图URL: ${locationName}`);
              }
            }
          } catch (error) {
            console.error(`[宫格生图] 获取场景参考图失败:`, error);
          }
        }

        // 3. 添加道具参考图URL
        const propsPresent = shotData.props_present || [];
        if (propsPresent.length > 0 && shotData.scriptData && shotData.scriptData.props) {
          const scriptProps = shotData.scriptData.props;
          for (const propId of propsPresent) {
            if (collectedProps.has(propId)) continue;
            collectedProps.add(propId);
            const prop = scriptProps.find(p => p.id === propId);
            if (prop && prop.props_db_id) {
              try {
                const response = await fetch(`/api/props/${prop.props_db_id}`, {
                  headers: {
                    'Authorization': authToken,
                    'X-User-Id': userId
                  }
                });
                if (response.ok) {
                  const result = await response.json();
                  if (result.code === 0 && result.data && result.data.reference_image) {
                    referenceImageUrls.push(result.data.reference_image);
                    promptSuffix.push(`图${imageIndex}是${prop.name}`);
                    imageIndex++;
                    console.log(`[宫格生图] 收集道具参考图URL: ${prop.name}`);
                  }
                }
              } catch (error) {
                console.error(`[宫格生图] 获取道具 ${prop.name} 参考图失败:`, error);
              }
            }
          }
        }
      }

      console.log(`[宫格生图] 总共收集到 ${referenceImageUrls.length} 张参考图片URL`);
      return { referenceImageUrls, promptSuffix };
    }

    function createVideoNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = opts && typeof opts.y === 'number' ? opts.y : viewportPos.y;
      const node = {
        id,
        type: 'video',
        title: '视频',
        x,
        y,
        data: {
          file: null,
          url: '',
          name: '',
          project_id: null,
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';

      el.innerHTML = `
        <div class="port input" title="输入（连接图生视频节点或角色节点）"></div>
        <div class="port output" title="输出（连接到对话组节点作为情感参考）"></div>
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="4" y="6" width="16" height="12" rx="2"/><path d="M10 9.5V14.5L14.5 12L10 9.5Z" fill="currentColor"/></svg>${node.title}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field field-collapsible">
            <div class="label">视频</div>
            <input class="video-file" type="file" accept="video/*" />
          </div>
          <div class="field field-always-visible video-preview-field" style="display:none;">
            <div class="label">预览</div>
            <div class="video-preview">
              <video class="video-thumb" playsinline></video>
              <div class="video-preview-actions">
                <button class="vp-btn vp-play" type="button" aria-label="播放">▶</button>
                <button class="vp-btn vp-zoom" type="button" aria-label="放大">⤢</button>
              </div>
            </div>
            <div class="gen-meta video-name"></div>
          </div>
          <div class="field field-collapsible video-preview-actions-field" style="display:none;">
            <div class="preview-row" style="margin-top: 8px; justify-content: space-between;">
              <div style="display: flex; gap: 8px;">
                <button class="mini-btn video-add-timeline" type="button">加时间轴</button>
                <button class="mini-btn video-download" type="button">下载</button>
                <button class="mini-btn video-clear" type="button">清除</button>
              </div>
            </div>
          </div>
          <div class="field field-always-visible video-status-field" style="display:none;">
            <div class="gen-meta video-status"></div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const fileEl = el.querySelector('.video-file');
      const inputPort = el.querySelector('.port.input');
      const outputPort = el.querySelector('.port.output');
      const previewField = el.querySelector('.video-preview-field');
      const previewActionsField = el.querySelector('.video-preview-actions-field');
      const thumbVideo = el.querySelector('.video-thumb');
      const playBtn = el.querySelector('.vp-play');
      const zoomBtn = el.querySelector('.vp-zoom');
      const nameEl = el.querySelector('.video-name');
      const addTimelineBtn = el.querySelector('.video-add-timeline');
      const downloadBtn = el.querySelector('.video-download');
      const clearBtn = el.querySelector('.video-clear');
      const statusField = el.querySelector('.video-status-field');
      const statusEl = el.querySelector('.video-status');

      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });

      el.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        setSelected(id);
        bringNodeToFront(id);
      });

      headerEl.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        // 如果节点不在选中列表中，才调用setSelected（这会清空其他选中）
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        bringNodeToFront(id);
        initNodeDrag(id, e.clientX, e.clientY);
      });

      inputPort.addEventListener('mouseup', (e) => {
        if(state.connecting && state.connecting.fromId !== id){
          const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
          if(fromNode && (fromNode.type === 'image_to_video' || fromNode.type === 'character')){
            const exists = state.connections.some(c => c.to === id);
            if(!exists){
              state.connections.push({
                id: state.nextConnId++,
                from: state.connecting.fromId,
                to: id
              });
              renderConnections();
              renderImageConnections();
              renderFirstFrameConnections();
              renderVideoConnections();
              
              // 如果连接涉及角色节点，更新角色卡按钮状态
              if(fromNode.type === 'character'){
                updateCharacterCardButtonState(state.connecting.fromId);
              }
            }
          }
        }
        state.connecting = null;
      });

      outputPort.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
      });

      function setVideoFromFile(file){
        if(node.data.url){
          try{ URL.revokeObjectURL(node.data.url); } catch(e){}
        }
        node.data.file = file;
        node.data.name = file ? file.name : '';
        node.data.url = file ? URL.createObjectURL(file) : '';
        if(node.data.url){
          thumbVideo.src = node.data.url;
          thumbVideo.muted = true;
          thumbVideo.loop = true;
          thumbVideo.controls = false;
          const displayName = node.data.name.length > 10 ? node.data.name.substring(0, 10) + '...' : node.data.name;
          nameEl.textContent = displayName;
          nameEl.title = node.data.name;
          previewField.style.display = 'block';
          previewActionsField.style.display = 'block';
          
          // 获取视频时长
          thumbVideo.addEventListener('loadedmetadata', () => {
            if(thumbVideo.duration && isFinite(thumbVideo.duration)){
              node.data.duration = Math.round(thumbVideo.duration);
            }
          }, { once: true });
        } else {
          thumbVideo.removeAttribute('src');
          thumbVideo.load();
          previewField.style.display = 'none';
          previewActionsField.style.display = 'none';
        }
      }

      fileEl.addEventListener('change', async () => {
        const file = fileEl.files && fileEl.files[0];
        if(!file) return;
        
        // 先显示本地预览
        setVideoFromFile(file);
        fileEl.value = '';
        
        // 立即上传到服务器获取永久URL
        try {
          showToast('正在上传视频...', 'info');
          const permanentUrl = await uploadFile(file);
          if(permanentUrl){
            // 更新为服务器URL
            node.data.url = permanentUrl;
            thumbVideo.src = proxyDownloadUrl(permanentUrl);
            showToast('视频上传成功', 'success');
            
            // 自动保存工作流
            try{ autoSaveWorkflow(); } catch(e){}
          }
        } catch(error){
          console.error('视频上传失败:', error);
          showToast('视频上传失败，刷新页面后将丢失', 'error');
        }
      });

      playBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if(!thumbVideo.src) return;
        if(thumbVideo.paused){
          const p = thumbVideo.play();
          if(p && typeof p.catch === 'function') p.catch(() => {});
          playBtn.textContent = '❚❚';
        } else {
          thumbVideo.pause();
          playBtn.textContent = '▶';
        }
      });

      zoomBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if(!node.data.url) return;
        openVideoModal(node.data.url);
      });

      addTimelineBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        addToTimeline(id);
      });

      clearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        try{ thumbVideo.pause(); } catch(err){}
        playBtn.textContent = '▶';
        setVideoFromFile(null);
      });

      downloadBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if(!node.data.url){
          showToast('没有可下载的视频', 'error');
          return;
        }
        
        // 生成文件名
        const now = new Date();
        const dateStr = now.getFullYear().toString() + 
                       (now.getMonth() + 1).toString().padStart(2, '0') + 
                       now.getDate().toString().padStart(2, '0');
        const timeStr = now.getHours().toString().padStart(2, '0') + 
                       now.getMinutes().toString().padStart(2, '0');
        const filename = `workflow_video_${dateStr}_${timeStr}.mp4`;
        
        // 使用后端代理下载，绕过CORS
        const downloadUrl = `/api/download?url=${encodeURIComponent(node.data.url)}&filename=${encodeURIComponent(filename)}`;
        window.open(downloadUrl, '_blank');
        showToast('开始下载', 'success');
      });

      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);
      setSelected(id);
      return id;
    }

    function readFileAsDataUrl(file){
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
      });
    }

    function openVideoModal(src){
      if(!src) return;
      videoModalPlayer.src = src;
      videoModal.classList.add('show');
      videoModal.setAttribute('aria-hidden', 'false');
      const p = videoModalPlayer.play();
      if(p && typeof p.catch === 'function') p.catch(() => {});
    }

    function closeVideoModal(){
      videoModal.classList.remove('show');
      videoModal.setAttribute('aria-hidden', 'true');
      try{ videoModalPlayer.pause(); } catch(e){}
      videoModalPlayer.removeAttribute('src');
      videoModalPlayer.load();
    }

    function openImageModal(src, title){
      if(!src) return;
      imageModalImg.src = src;
      if(typeof title === 'string' && title){
        imageModalTitle.textContent = title;
      } else {
        imageModalTitle.textContent = '图片预览';
      }
      imageModal.classList.add('show');
      imageModal.setAttribute('aria-hidden', 'false');
    }

    function closeImageModal(){
      imageModal.classList.remove('show');
      imageModal.setAttribute('aria-hidden', 'true');
      imageModalImg.removeAttribute('src');
    }

    videoModalClose.addEventListener('click', (e) => {
      e.stopPropagation();
      closeVideoModal();
    });
    videoModal.addEventListener('mousedown', (e) => {
      if(e.target === videoModal) closeVideoModal();
    });

    imageModalClose.addEventListener('click', (e) => {
      e.stopPropagation();
      closeImageModal();
    });
    imageModal.addEventListener('mousedown', (e) => {
      if(e.target === imageModal) closeImageModal();
    });

    const shotGroupModal = document.getElementById('shotGroupModal');
    const shotGroupModalClose = document.getElementById('shotGroupModalClose');
    const shotGroupModalContent = document.getElementById('shotGroupModalContent');
    const shotGroupModalTitle = document.getElementById('shotGroupModalTitle');
    const shotGroupModalEditBtn = document.getElementById('shotGroupModalEditBtn');
    let currentShotGroupNodeId = null;
    
    const shotDetailModal = document.getElementById('shotDetailModal');
    const shotDetailModalClose = document.getElementById('shotDetailModalClose');
    const shotDetailModalContent = document.getElementById('shotDetailModalContent');
    const shotDetailModalTitle = document.getElementById('shotDetailModalTitle');
    let currentShotDetailContext = null;

    function openShotGroupModal(shotGroupData, nodeId){
      currentShotGroupNodeId = nodeId;
      shotGroupModalTitle.textContent = `分镜组详情 - ${shotGroupData.groupName || '未命名'}`;
      shotGroupModalContent.innerHTML = renderShotGroupTable(shotGroupData, nodeId);
      shotGroupModal.classList.add('show');
      shotGroupModal.setAttribute('aria-hidden', 'false');
    }

    function closeShotGroupModal(){
      shotGroupModal.classList.remove('show');
      shotGroupModal.setAttribute('aria-hidden', 'true');
      currentShotGroupNodeId = null;
    }

    function openShotDetailModal(shot, nodeId, shotIndex){
      currentShotDetailContext = { nodeId, shotIndex };
      shotDetailModalTitle.textContent = `分镜详情 - ${shot.shot_id || ''}`;
      shotDetailModalContent.innerHTML = renderShotDetail(shot, nodeId, shotIndex);
      shotDetailModal.classList.add('show');
      shotDetailModal.setAttribute('aria-hidden', 'false');
    }

    function closeShotDetailModal(){
      shotDetailModal.classList.remove('show');
      shotDetailModal.setAttribute('aria-hidden', 'true');
      currentShotDetailContext = null;
    }

    shotGroupModalClose.addEventListener('click', (e) => {
      e.stopPropagation();
      closeShotGroupModal();
    });
    shotGroupModal.addEventListener('mousedown', (e) => {
      if(e.target === shotGroupModal) closeShotGroupModal();
    });

    shotGroupModalEditBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      if(currentShotGroupNodeId !== null){
        const node = state.nodes.find(n => n.id === currentShotGroupNodeId);
        if(node){
          const nodeId = currentShotGroupNodeId;
          const nodeData = node.data;
          closeShotGroupModal();
          // 延迟打开编辑弹窗，确保详情弹窗完全关闭
          setTimeout(() => {
            openShotGroupEditModal(nodeId, nodeData);
          }, 100);
        }
      }
    });

    shotDetailModalClose.addEventListener('click', (e) => {
      e.stopPropagation();
      closeShotDetailModal();
    });
    shotDetailModal.addEventListener('mousedown', (e) => {
      if(e.target === shotDetailModal) closeShotDetailModal();
    });

    const shotGroupEditModal = document.getElementById('shotGroupEditModal');
    const shotGroupEditModalContent = document.getElementById('shotGroupEditModalContent');
    const shotGroupEditModalClose = document.getElementById('shotGroupEditModalClose');
    const shotGroupEditSaveBtn = document.getElementById('shotGroupEditSaveBtn');
    const shotGroupEditCancelBtn = document.getElementById('shotGroupEditCancelBtn');
    let currentEditingNodeId = null;

    function openShotGroupEditModal(nodeId, shotGroupData){
      currentEditingNodeId = nodeId;
      const node = state.nodes.find(n => n.id === nodeId);
      let maxGroupDuration = 15;
      if(node){
        const incomingConns = state.connections.filter(c => c.to === nodeId);
        if(incomingConns.length > 0){
          const scriptNode = state.nodes.find(n => n.id === incomingConns[0].from);
          if(scriptNode && scriptNode.type === 'script' && scriptNode.data.maxGroupDuration){
            maxGroupDuration = scriptNode.data.maxGroupDuration;
          }
        }
      }
      shotGroupEditModalContent.innerHTML = renderShotGroupEditForm(shotGroupData, maxGroupDuration);
      shotGroupEditModal.classList.add('show');
      shotGroupEditModal.setAttribute('aria-hidden', 'false');
      bindShotEditEvents();
    }

    function closeShotGroupEditModal(){
      shotGroupEditModal.classList.remove('show');
      shotGroupEditModal.setAttribute('aria-hidden', 'true');
      currentEditingNodeId = null;
    }

    shotGroupEditModalClose.addEventListener('click', (e) => {
      e.stopPropagation();
      closeShotGroupEditModal();
    });
    shotGroupEditCancelBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      closeShotGroupEditModal();
    });
    shotGroupEditModal.addEventListener('mousedown', (e) => {
      if(e.target === shotGroupEditModal) closeShotGroupEditModal();
    });

    shotGroupEditSaveBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      saveShotGroupEdit();
    });

    // 场景选择弹窗事件监听
    const locationModalClose = document.getElementById('locationModalClose');
    const locationModal = document.getElementById('locationModal');
    const locationWorldSelect = document.getElementById('locationWorldSelect');
    const locationSearchInput = document.getElementById('locationSearchInput');

    if(locationModalClose){
      locationModalClose.addEventListener('click', (e) => {
        e.stopPropagation();
        closeLocationModal();
      });
    }

    if(locationModal){
      locationModal.addEventListener('mousedown', (e) => {
        if(e.target === locationModal) closeLocationModal();
      });
    }

    if(locationWorldSelect){
      locationWorldSelect.addEventListener('change', (e) => {
        const worldId = e.target.value;
        loadLocationsForWorld(worldId);
      });
    }

    if(locationSearchInput){
      let searchTimeout;
      locationSearchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
          const keyword = e.target.value.trim();
          const worldId = locationWorldSelect ? locationWorldSelect.value : '';
          if(worldId){
            loadLocationsForWorld(worldId, keyword);
          }
        }, 300);
      });
    }

    function renderShotGroupEditForm(shotGroupData, maxGroupDuration){
      const groupId = shotGroupData.groupId || shotGroupData.group_id || '';
      const shots = shotGroupData.shots || [];
      maxGroupDuration = maxGroupDuration || 15;

      let html = `
        <div style="margin-bottom: 20px;">
          <div style="margin-bottom: 12px;">
            <label style="display: block; font-weight: 600; margin-bottom: 6px; font-size: 13px;">分镜组ID</label>
            <input type="text" id="editGroupId" value="${escapeHtml(groupId)}" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px;" />
          </div>
          <div style="margin-bottom: 12px;">
            <label style="display: block; font-weight: 600; margin-bottom: 6px; font-size: 13px;">镜头组最长时长（来自剧本节点）</label>
            <input type="text" value="${maxGroupDuration}秒" readonly style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px; background: #f3f4f6; color: #6b7280; cursor: not-allowed;" />
          </div>
        </div>
        <div style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
          <h3 style="margin: 0; font-size: 14px; font-weight: 600;">分镜列表</h3>
        </div>
        <div id="shotsEditContainer">
      `;

      const insertBtnHtml = (insertIndex) => {
        return `
          <div style="display:flex; justify-content:center; margin: 10px 0;">
            <button class="mini-btn secondary insert-shot-btn" data-insert-index="${insertIndex}" type="button">在此处添加分镜</button>
          </div>
        `;
      };

      if(shots.length === 0){
        html += '<div class="shot-group-empty">暂无分镜，你可以在任意位置添加</div>';
        html += insertBtnHtml(0);
      } else {
        html += insertBtnHtml(0);
        shots.forEach((shot, idx) => {
          html += renderShotEditItem(shot, idx);
          html += insertBtnHtml(idx + 1);
        });
      }

      html += '</div>';
      return html;
    }

    function renderShotEditItem(shot, index){
      const dialogue = shot.dialogue || [];
      const dialogueText = dialogue.map(d => `${d.character_name}: ${d.text}`).join('; ');
      
      return `
        <div class="shot-edit-item" data-shot-index="${index}" style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; margin-bottom: 12px; background: #fafafa;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <h4 style="margin: 0; font-size: 13px; font-weight: 600;">分镜 #${index + 1}</h4>
            <button class="mini-btn secondary delete-shot-btn" data-shot-index="${index}" type="button">删除</button>
          </div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <div>
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">镜头ID</label>
              <input type="text" class="shot-field" data-field="shot_id" value="${escapeHtml(shot.shot_id || '')}" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
            </div>
            <div>
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">时长(秒)</label>
              <input type="text" class="shot-field" data-field="duration" value="${escapeHtml(shot.duration || '')}" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
            </div>
            <div>
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">时间段</label>
              <input type="text" class="shot-field" data-field="time_of_day" value="${escapeHtml(shot.time_of_day || '')}" placeholder="如：下午3点、傍晚日落时分" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
            </div>
            <div>
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">天气</label>
              <input type="text" class="shot-field" data-field="weather" value="${escapeHtml(shot.weather || '')}" placeholder="如：晴朗、阴云密布" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
            </div>
            <div>
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">场景ID</label>
              <input type="text" class="shot-field" data-field="location_id" value="${escapeHtml(shot.location_id || '')}" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
            </div>
            <div>
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">参考场景</label>
              <div style="display: flex; gap: 4px; align-items: center;">
                <input type="text" data-field="db_location_id" value="${escapeHtml(shot.db_location_id || '')}" placeholder="数据库场景ID" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px; background: #f3f4f6;" readonly />
                <button class="mini-btn secondary select-location-btn" data-shot-index="${index}" type="button" style="white-space: nowrap;">选择</button>
              </div>
              ${shot.db_location_pic ? `<div style="margin-top: 4px;"><img src="${escapeHtml(shot.db_location_pic)}" style="width: 100%; height: 60px; object-fit: cover; border-radius: 4px; border: 1px solid #e5e7eb;" alt="参考场景" /><div style="font-size: 11px; color: #6b7280; margin-top: 2px;">${escapeHtml(shot.location_name || '场景')}</div></div>` : '<div style="margin-top: 4px; padding: 8px; background: #f3f4f6; border-radius: 4px; font-size: 11px; color: #6b7280; text-align: center;">未选择参考场景</div>'}
              <input type="hidden" data-field="db_location_pic" value="${escapeHtml(shot.db_location_pic || '')}" />
              <input type="hidden" data-field="location_name" value="${escapeHtml(shot.location_name || '')}" />
            </div>
            <div>
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">镜头类型</label>
              <input type="text" class="shot-field" data-field="shot_type" value="${escapeHtml(shot.shot_type || '')}" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
            </div>
            <div>
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">运镜方式</label>
              <input type="text" class="shot-field" data-field="camera_movement" value="${escapeHtml(shot.camera_movement || '')}" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
            </div>
            <div style="grid-column: 1 / -1;">
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">描述</label>
              <textarea class="shot-field" data-field="description" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px; min-height: 50px; resize: vertical;">${escapeHtml(shot.description || '')}</textarea>
            </div>
            <div style="grid-column: 1 / -1;">
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">起始画面描述</label>
              <textarea class="shot-field" data-field="opening_frame_description" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px; min-height: 60px; resize: vertical;">${escapeHtml(shot.opening_frame_description || '')}</textarea>
            </div>
            <div style="grid-column: 1 / -1;">
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">场景细节</label>
              <textarea class="shot-field" data-field="scene_detail" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px; min-height: 50px; resize: vertical;">${escapeHtml(shot.scene_detail || '')}</textarea>
            </div>
            <div style="grid-column: 1 / -1;">
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">动作</label>
              <textarea class="shot-field" data-field="action" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px; min-height: 50px; resize: vertical;">${escapeHtml(shot.action || '')}</textarea>
            </div>
            <div>
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">情绪</label>
              <input type="text" class="shot-field" data-field="mood" value="${escapeHtml(shot.mood || '')}" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
            </div>
            <div>
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">音频备注</label>
              <input type="text" class="shot-field" data-field="audio_notes" value="${escapeHtml(shot.audio_notes || '')}" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
            </div>
            <div>
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">环境音</label>
              <input type="text" class="shot-field" data-field="environment_sound" value="${escapeHtml(shot.environment_sound || '')}" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
            </div>
            <div>
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">背景音乐</label>
              <input type="text" class="shot-field" data-field="background_music" value="${escapeHtml(shot.background_music || '')}" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
            </div>
            <div style="grid-column: 1 / -1;">
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">出场角色（逗号分隔ID）</label>
              <input type="text" class="shot-field" data-field="characters_present" value="${escapeHtml(Array.isArray(shot.characters_present) ? shot.characters_present.join(', ') : (shot.characters_present || ''))}" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
            </div>
            <div style="grid-column: 1 / -1;">
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">对话（JSON格式）</label>
              <textarea class="shot-field" data-field="dialogue" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px; min-height: 80px; resize: vertical; font-family: monospace;">${escapeHtml(Array.isArray(shot.dialogue) ? JSON.stringify(shot.dialogue, null, 2) : (shot.dialogue || '[]'))}</textarea>
            </div>
            <div style="grid-column: 1 / -1;">
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">参考道具</label>
              <div style="display: flex; gap: 4px; align-items: center; margin-bottom: 8px;">
                <button class="mini-btn secondary add-props-btn" data-shot-index="${index}" type="button">添加道具</button>
              </div>
              <div class="shot-props-container" data-shot-index="${index}" style="display: flex; flex-wrap: wrap; gap: 8px;">
                ${(shot.props && shot.props.length > 0) ? shot.props.map((prop, propIdx) => `
                  <div style="display: flex; gap: 6px; align-items: center; padding: 6px; background: #fff; border: 1px solid #e5e7eb; border-radius: 4px;">
                    ${prop.reference_image ? `<img src="${escapeHtml(prop.reference_image)}" style="width: 32px; height: 32px; object-fit: cover; border-radius: 3px;" alt="${escapeHtml(prop.name || '道具')}" />` : '<div style="width: 32px; height: 32px; background: #f3f4f6; border-radius: 3px; display: flex; align-items: center; justify-content: center; color: #9ca3af; font-size: 9px;">无图</div>'}
                    <span style="font-size: 11px; color: #374151;">${escapeHtml(prop.name || '未命名')}</span>
                    <button class="remove-props-btn" data-shot-index="${index}" data-props-index="${propIdx}" type="button" style="padding: 2px 6px; font-size: 10px; color: #ef4444; background: none; border: 1px solid #fca5a5; border-radius: 3px; cursor: pointer;">x</button>
                  </div>
                `).join('') : '<div style="padding: 8px; background: #f3f4f6; border-radius: 4px; font-size: 11px; color: #6b7280; text-align: center; width: 100%;">未选择参考道具</div>'}
              </div>
              <input type="hidden" class="shot-field" data-field="props" value="${escapeHtml(JSON.stringify(shot.props || []))}" />
            </div>
          </div>
        </div>
      `;
    }

    function bindShotEditEvents(){
      const insertBtns = shotGroupEditModalContent.querySelectorAll('.insert-shot-btn');
      insertBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const idx = parseInt(btn.dataset.insertIndex);
          addNewShot(idx);
        });
      });

      const deleteBtns = shotGroupEditModalContent.querySelectorAll('.delete-shot-btn');
      deleteBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const index = parseInt(btn.dataset.shotIndex);
          deleteShot(index);
        });
      });

      const selectLocationBtns = shotGroupEditModalContent.querySelectorAll('.select-location-btn');
      selectLocationBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const shotIndex = parseInt(btn.dataset.shotIndex);
          openLocationSelectorModal(shotIndex);
        });
      });
      
      // 绑定添加道具按钮事件
      const addPropsBtns = shotGroupEditModalContent.querySelectorAll('.add-props-btn');
      addPropsBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const shotIndex = parseInt(btn.dataset.shotIndex);
          openPropsSelectorForEditModal(shotIndex);
        });
      });
      
      // 绑定移除道具按钮事件
      const removePropsBtns = shotGroupEditModalContent.querySelectorAll('.remove-props-btn');
      removePropsBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const shotIndex = parseInt(btn.dataset.shotIndex);
          const propsIndex = parseInt(btn.dataset.propsIndex);
          removePropsFromEditModal(shotIndex, propsIndex);
        });
      });
    }

    function renumberShots(shots){
      if(!Array.isArray(shots)) return;
      shots.forEach((s, i) => {
        if(s && typeof s === 'object'){
          s.shot_number = i + 1;
        }
      });
    }
    
    // 为编辑弹窗打开道具选择
    function openPropsSelectorForEditModal(shotIndex){
      window.currentPropsSelectionContext = {
        nodeId: currentEditingNodeId,
        shotIndex,
        fromEditModal: true
      };
      
      if(typeof window.openPropsModalForShot === 'function'){
        window.openPropsModalForShot();
      } else {
        showToast('道具选择功能未初始化', 'error');
      }
    }
    
    // 从编辑弹窗中移除道具
    function removePropsFromEditModal(shotIndex, propsIndex){
      const node = state.nodes.find(n => n.id === currentEditingNodeId);
      if(!node || !node.data.shots || !node.data.shots[shotIndex]) return;
      
      const shot = node.data.shots[shotIndex];
      if(!shot.props || !Array.isArray(shot.props)) return;
      
      shot.props.splice(propsIndex, 1);
      
      // 更新编辑弹窗
      shotGroupEditModalContent.innerHTML = renderShotGroupEditForm(node.data);
      bindShotEditEvents();
      
      showToast('已移除道具', 'success');
    }

    function addNewShot(insertIndex){
      const node = state.nodes.find(n => n.id === currentEditingNodeId);
      if(!node) return;

      if(!Array.isArray(node.data.shots)) node.data.shots = [];
      
      const idx = (typeof insertIndex === 'number' && !Number.isNaN(insertIndex))
        ? Math.max(0, Math.min(insertIndex, node.data.shots.length))
        : node.data.shots.length;

      const newShot = {
        shot_id: `s${Date.now()}`,
        shot_number: idx + 1,
        duration: 5.0,
        location_id: '',
        shot_type: '中景',
        camera_movement: '固定',
        description: '',
        opening_frame_description: '',
        scene_detail: '',
        characters_present: [],
        dialogue: null,
        action: '',
        mood: '',
        environment_sound: '',
        background_music: '',
        props: []
      };

      node.data.shots.splice(idx, 0, newShot);
      renumberShots(node.data.shots);
      shotGroupEditModalContent.innerHTML = renderShotGroupEditForm(node.data);
      bindShotEditEvents();
    }

    function deleteShot(index){
      const node = state.nodes.find(n => n.id === currentEditingNodeId);
      if(!node) return;

      node.data.shots.splice(index, 1);
      renumberShots(node.data.shots);
      shotGroupEditModalContent.innerHTML = renderShotGroupEditForm(node.data);
      bindShotEditEvents();
    }

    let currentLocationSelectionContext = null;
    window.currentLocationSelectionContext = null;

    async function openLocationSelectorModal(shotIndex){
      const node = state.nodes.find(n => n.id === currentEditingNodeId);
      if(!node || !node.data.shots[shotIndex]) return;

      // 保存上下文信息
      currentLocationSelectionContext = {
        nodeId: currentEditingNodeId,
        shotIndex: shotIndex,
        isEditModal: true
      };
      window.currentLocationSelectionContext = currentLocationSelectionContext;

      // 打开场景选择弹窗
      openLocationModal();
    }

    function openLocationModal(){
      const locationModal = document.getElementById('locationModal');
      const locationWorldSelect = document.getElementById('locationWorldSelect');
      const locationList = document.getElementById('locationList');
      
      if(!locationModal) return;

      // 加载世界列表
      loadWorldsForLocationModal();

      locationModal.classList.add('show');
      locationModal.setAttribute('aria-hidden', 'false');
    }

    function closeLocationModal(){
      const locationModal = document.getElementById('locationModal');
      if(locationModal){
        locationModal.classList.remove('show');
        locationModal.setAttribute('aria-hidden', 'true');
      }
      currentLocationSelectionContext = null;
      window.currentLocationSelectionContext = null;
    }

    async function loadWorldsForLocationModal(){
      const locationWorldSelect = document.getElementById('locationWorldSelect');
      if(!locationWorldSelect) return;

      try{
        const response = await fetch('/api/worlds?page=1&page_size=100', {
          headers: {
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
          }
        });

        if(!response.ok) throw new Error('获取世界列表失败');

        const result = await response.json();
        if(result.code === 0 && result.data && result.data.data){
          locationWorldSelect.innerHTML = '<option value="">请选择世界...</option>';
          result.data.data.forEach(world => {
            const option = document.createElement('option');
            option.value = world.id;
            option.textContent = world.name;
            locationWorldSelect.appendChild(option);
          });
        }
      } catch(e){
        console.error('加载世界列表失败:', e);
        showToast('加载世界列表失败', 'error');
      }
    }

    async function loadLocationsForWorld(worldId, keyword = ''){
      const locationList = document.getElementById('locationList');
      if(!locationList) return;

      if(!worldId){
        locationList.innerHTML = '<div style="text-align: center; color: #9ca3af; padding: 40px 20px;">请先选择世界</div>';
        return;
      }

      locationList.innerHTML = '<div style="text-align: center; color: #9ca3af; padding: 40px 20px;">加载中...</div>';

      try{
        let url = `/api/locations?world_id=${worldId}&page=1&page_size=100`;
        if(keyword){
          url += `&keyword=${encodeURIComponent(keyword)}`;
        }

        const response = await fetch(url, {
          headers: {
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || '1'
          }
        });

        if(!response.ok) throw new Error('获取场景列表失败');

        const result = await response.json();
        if(result.code === 0 && result.data && result.data.data){
          const locations = result.data.data;
          
          if(locations.length === 0){
            locationList.innerHTML = `<div style="text-align: center; color: #9ca3af; padding: 40px 20px;">${keyword ? '未找到匹配的场景' : '该世界暂无场景'}</div>`;
            return;
          }

          locationList.innerHTML = '';
          locations.forEach(location => {
            const locationCard = document.createElement('div');
            locationCard.className = 'location-card';
            locationCard.style.cssText = 'display: flex; gap: 12px; padding: 12px; border: 1px solid #e5e7eb; border-radius: 8px; margin-bottom: 8px; cursor: pointer; transition: background 0.2s;';
            
            locationCard.innerHTML = `
              ${location.reference_image ? `<img src="${location.reference_image}" style="width: 80px; height: 80px; object-fit: cover; border-radius: 6px; flex-shrink: 0;" alt="${escapeHtml(location.name)}" />` : '<div style="width: 80px; height: 80px; background: #f3f4f6; border-radius: 6px; display: flex; align-items: center; justify-content: center; color: #9ca3af; font-size: 12px; flex-shrink: 0;">无图片</div>'}
              <div style="flex: 1; min-width: 0;">
                <div style="font-weight: 600; color: #111827; margin-bottom: 4px;">${escapeHtml(location.name)}</div>
                <div style="font-size: 12px; color: #6b7280; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(location.description || '暂无描述')}</div>
                <div style="font-size: 11px; color: #9ca3af; margin-top: 4px;">ID: ${location.id}</div>
              </div>
            `;

            locationCard.addEventListener('mouseenter', () => {
              locationCard.style.background = '#f9fafb';
            });
            locationCard.addEventListener('mouseleave', () => {
              locationCard.style.background = '';
            });
            locationCard.addEventListener('click', () => {
              selectLocation(location);
            });

            locationList.appendChild(locationCard);
          });
        }
      } catch(e){
        console.error('加载场景列表失败:', e);
        locationList.innerHTML = '<div style="text-align: center; color: #ef4444; padding: 40px 20px;">加载失败，请重试</div>';
      }
    }

    function selectLocation(location){
      if(!currentLocationSelectionContext) return;

      const { nodeId, shotIndex, isEditModal, fromDetailModal } = currentLocationSelectionContext;
      const node = state.nodes.find(n => n.id === nodeId);
      if(!node || !node.data.shots[shotIndex]) return;

      // 更新分镜的场景信息
      node.data.shots[shotIndex].db_location_id = location.id;
      node.data.shots[shotIndex].db_location_pic = location.reference_image;
      node.data.shots[shotIndex].location_name = location.name;

      // 关闭场景选择弹窗
      closeLocationModal();

      // 清空上下文
      currentLocationSelectionContext = null;
      window.currentLocationSelectionContext = null;

      // 根据上下文重新渲染对应的界面
      if(isEditModal){
        shotGroupEditModalContent.innerHTML = renderShotGroupEditForm(node.data);
        bindShotEditEvents();
      } else if(fromDetailModal){
        // 如果是从分镜详情弹窗选择的场景，更新分镜详情弹窗
        const updatedShot = node.data.shots[shotIndex];
        shotDetailModalContent.innerHTML = renderShotDetail(updatedShot, nodeId, shotIndex);
        // 同时更新分镜组详情弹窗（如果它是打开的）
        if(shotGroupModal.classList.contains('show')){
          shotGroupModalContent.innerHTML = renderShotGroupTable(node.data, nodeId);
        }
      } else {
        shotGroupModalContent.innerHTML = renderShotGroupTable(node.data, nodeId);
      }

      showToast('场景设置成功', 'success');
      try{ autoSaveWorkflow(); } catch(e){}
    }
    
    // 将 selectLocation 暴露到全局作用域
    window.selectLocation = selectLocation;

    function saveShotGroupEdit(){
      const node = state.nodes.find(n => n.id === currentEditingNodeId);
      if(!node) return;

      const groupId = document.getElementById('editGroupId').value.trim();

      node.data.groupId = groupId;
      node.data.group_id = groupId;
      node.title = groupId || '分镜组';

      const shotItems = shotGroupEditModalContent.querySelectorAll('.shot-edit-item');
      shotItems.forEach((item, idx) => {
        if(idx < node.data.shots.length){
          const shot = node.data.shots[idx];
          const fields = item.querySelectorAll('.shot-field, input[data-field], textarea[data-field]');
          fields.forEach(field => {
            const fieldName = field.dataset.field;
            if(!fieldName) return;
            let value = field.value.trim();
            if(fieldName === 'characters_present'){
              shot[fieldName] = value ? value.split(',').map(s => s.trim()).filter(s => s) : [];
            } else if(fieldName === 'dialogue'){
              try{
                shot[fieldName] = value ? JSON.parse(value) : [];
              } catch(e){
                shot[fieldName] = [];
              }
            } else if(fieldName === 'db_location_id'){
              shot[fieldName] = value ? parseInt(value) : null;
            } else if(fieldName === 'props'){
              try{
                shot[fieldName] = value ? JSON.parse(value) : [];
              } catch(e){
                shot[fieldName] = [];
              }
            } else {
              shot[fieldName] = value;
            }
          });
        }
      });

      updateShotGroupNodeDisplay(currentEditingNodeId);
      closeShotGroupEditModal();
      try{ autoSaveWorkflow(); } catch(e){}
    }

    function updateShotGroupNodeDisplay(nodeId){
      const node = state.nodes.find(n => n.id === nodeId);
      if(!node) return;

      const el = canvasEl.querySelector(`.node[data-node-id="${nodeId}"]`);
      if(!el) return;

      const shotsHtml = node.data.shots.map((shot, idx) => {
        const duration = shot.duration ? `${shot.duration}秒` : '未知';
        return `
          <div style="padding: 8px; background: #f8f9fa; border-radius: 6px; margin-bottom: 6px; font-size: 12px;">
            <div style="font-weight: 700; margin-bottom: 4px;">${escapeHtml(shot.shot_id || `镜头${idx+1}`)} - ${escapeHtml(shot.description || '')}</div>
            <div style="color: #666; font-size: 11px;">时长: ${escapeHtml(duration)} | ${escapeHtml(shot.shot_type || '')} | ${escapeHtml(shot.camera_movement || '')}</div>
            <div style="color: #666; font-size: 11px; margin-top: 2px;">起始画面: ${escapeHtml((shot.opening_frame_description || '').slice(0, 60))}...</div>
          </div>
        `;
      }).join('');

      const nodeBody = el.querySelector('.node-body');
      if(nodeBody){
        nodeBody.innerHTML = `
          <div class="field field-always-visible">
            <div class="label">分镜组: ${escapeHtml(node.data.groupId || node.data.group_id)}</div>
            <div class="gen-meta">共 ${node.data.shots.length} 个分镜</div>
          </div>
          <div class="field field-always-visible" style="max-height: 300px; overflow-y: auto;">
            ${shotsHtml || '<div class="shot-group-empty">暂无分镜</div>'}
          </div>
          <div class="field field-collapsible">
            <div class="label">分镜模型</div>
            <select class="shot-group-model">
              <option value="gemini-2.5-pro-image-preview" ${node.data.model === 'gemini-2.5-pro-image-preview' ? 'selected' : ''}>标准版</option>
              <option value="gemini-3-pro-image-preview" ${node.data.model === 'gemini-3-pro-image-preview' ? 'selected' : ''}>加强版</option>
            </select>
          </div>
          <div class="field field-collapsible btn-row">
            <button class="mini-btn secondary shot-group-detail-btn" type="button" style="flex: 1;">查看/编辑</button>
            <button class="mini-btn gen-btn-white shot-group-generate-btn" type="button">生成分镜</button>
          </div>
        `;

        const newDetailBtn = nodeBody.querySelector('.shot-group-detail-btn');
        const newGenerateBtn = nodeBody.querySelector('.shot-group-generate-btn');
        const newModelSelect = nodeBody.querySelector('.shot-group-model');

        if(newDetailBtn){
          newDetailBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            openShotGroupModal(node.data, nodeId);
          });
        }

        if(newModelSelect){
          newModelSelect.addEventListener('change', () => {
            node.data.model = newModelSelect.value;
          });
        }

        if(newGenerateBtn){
          newGenerateBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            generateShotFramesIndependent(nodeId, node);
          });
        }
      }

      const titleEl = el.querySelector('.node-title');
      if(titleEl){
        titleEl.textContent = node.title;
      }
    }

    function renderShotGroupTable(shotGroupData, nodeId){
      const shots = shotGroupData.shots || [];
      if(shots.length === 0){
        return '<p style="text-align: center; color: #999;">暂无分镜数据</p>';
      }

      // 收集所有参考场景
      const referenceLocations = new Map();
      shots.forEach(shot => {
        if(shot.db_location_id && shot.db_location_pic){
          const locationName = shot.location_name || shot.location_id || '未命名场景';
          if(!referenceLocations.has(shot.db_location_id)){
            referenceLocations.set(shot.db_location_id, {
              id: shot.db_location_id,
              name: locationName,
              pic: shot.db_location_pic
            });
          }
        }
      });

      // 收集所有匹配到的道具
      const referenceProps = new Map();
      const node = state.nodes.find(n => n.id === nodeId);
      if(node && node.data.scriptData && node.data.scriptData.props){
        const propsData = node.data.scriptData.props;
        propsData.forEach(prop => {
          if(prop.props_db_id){
            referenceProps.set(prop.props_db_id, {
              id: prop.props_db_id,
              name: prop.name || '未命名道具',
              description: prop.description || '',
              category: prop.category || ''
            });
          }
        });
      }

      let html = '';

      // 参考场景区域
      if(referenceLocations.size > 0){
        html += `
          <div style="margin-bottom: 20px; padding: 16px; background: #f9fafb; border-radius: 8px; border: 1px solid #e5e7eb;">
            <h3 style="margin: 0 0 12px 0; font-size: 14px; font-weight: 600; color: #374151;">参考场景</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px;">
        `;
        
        referenceLocations.forEach(loc => {
          html += `
            <div style="border: 1px solid #e5e7eb; border-radius: 6px; overflow: hidden; background: white;">
              ${loc.pic ? `<img src="${escapeHtml(loc.pic)}" style="width: 100%; height: 120px; object-fit: cover;" alt="${escapeHtml(loc.name)}" />` : '<div style="width: 100%; height: 120px; background: #e5e7eb; display: flex; align-items: center; justify-content: center; color: #9ca3af;">无图片</div>'}
              <div style="padding: 8px;">
                <div style="font-size: 13px; font-weight: 500; color: #111827;">${escapeHtml(loc.name)}</div>
                <div style="font-size: 11px; color: #6b7280; margin-top: 2px;">ID: ${loc.id}</div>
              </div>
            </div>
          `;
        });
        
        html += `
            </div>
          </div>
        `;
      }

      // 分镜列表
      html += `
        <h3 style="margin: 0 0 12px 0; font-size: 14px; font-weight: 600; color: #374151;">分镜列表</h3>
        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
          <thead>
            <tr style="background: #f5f5f5; border-bottom: 2px solid #ddd;">
              <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">镜头ID</th>
              <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">时长(秒)</th>
              <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">时间</th>
              <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">天气</th>
              <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">镜头类型</th>
              <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">运镜</th>
              <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">参考场景</th>
              <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">道具</th>
              <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">描述</th>
              <th style="padding: 10px; text-align: center; border: 1px solid #ddd; width: 100px;">操作</th>
            </tr>
          </thead>
          <tbody>
      `;

      shots.forEach((shot, index) => {
        const shotId = shot.shot_id || `shot_${index + 1}`;
        const duration = shot.duration ? shot.duration : '-';
        const timeOfDay = shot.time_of_day || '-';
        const weather = shot.weather || '-';
        const shotType = shot.shot_type || '-';
        const cameraMovement = shot.camera_movement || '-';
        const description = shot.description || '-';
        const locationDisplay = shot.db_location_id 
          ? `<div style="display: flex; align-items: center; gap: 4px;">${shot.db_location_pic ? `<img src="${escapeHtml(shot.db_location_pic)}" style="width: 30px; height: 30px; object-fit: cover; border-radius: 4px;" alt="场景" />` : ''}<span style="font-size: 11px;">${escapeHtml(shot.location_name || 'ID:' + shot.db_location_id)}</span></div>`
          : '<span style="color: #9ca3af; font-size: 11px;">未匹配</span>';
        
        // 生成道具显示内容 - 显示该分镜中涉及的道具（包括脚本道具和参考道具）
        let propsDisplay = '<span style="color: #9ca3af; font-size: 11px;">无</span>';
        const shotPropsList = [];
        
        // 显示来自脚本的道具 (props_present)
        const propsPresent = shot.props_present || [];
        if(propsPresent.length > 0 && node && node.data.scriptData && node.data.scriptData.props){
          const scriptProps = node.data.scriptData.props;
          propsPresent.forEach(propId => {
            const prop = scriptProps.find(p => p.id === propId);
            if(prop && prop.props_db_id){
              shotPropsList.push(`<div style="display: inline-block; background: #fef3c7; border: 1px solid #fbbf24; border-radius: 4px; padding: 2px 6px; margin: 2px; font-size: 11px; color: #92400e;" title="${escapeHtml(prop.description || '')}">${escapeHtml(prop.name)}</div>`);
            }
          });
        }
        
        // 显示参考道具 (shot.props) - 带删除按钮
        const refProps = shot.props || [];
        if(refProps.length > 0){
          refProps.forEach((prop, propIdx) => {
            shotPropsList.push(`<div style="display: inline-flex; align-items: center; gap: 4px; background: #dbeafe; border: 1px solid #3b82f6; border-radius: 4px; padding: 2px 6px; margin: 2px; font-size: 11px; color: #1e40af;">${prop.reference_image ? `<img src="${escapeHtml(prop.reference_image)}" style="width: 16px; height: 16px; object-fit: cover; border-radius: 2px;" />` : ''}${escapeHtml(prop.name)}<button class="remove-shot-props-btn" data-shot-index="${index}" data-props-index="${propIdx}" type="button" style="margin-left: 4px; padding: 0 4px; background: none; border: none; color: #ef4444; cursor: pointer; font-size: 12px; line-height: 1;" title="删除道具">×</button></div>`);
          });
        }
        
        if(shotPropsList.length > 0){
          propsDisplay = `<div style="display: flex; flex-wrap: wrap; gap: 4px;">${shotPropsList.join('')}</div>`;
        }
        
        html += `
          <tr style="border-bottom: 1px solid #eee;">
            <td style="padding: 10px; border: 1px solid #ddd; font-weight: 600;">${shotId}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${duration}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${escapeHtml(timeOfDay)}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${escapeHtml(weather)}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${shotType}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${cameraMovement}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${locationDisplay}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${propsDisplay}</td>
            <td style="padding: 10px; border: 1px solid #ddd; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${description}</td>
            <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">
              <button class="mini-btn view-shot-detail" data-shot-index="${index}" style="padding: 4px 8px; font-size: 12px; margin-right: 4px;">查看</button>
              <button class="mini-btn secondary select-shot-location" data-shot-index="${index}" style="padding: 4px 8px; font-size: 12px; margin-right: 4px;">选择场景</button>
              <button class="mini-btn secondary select-shot-props" data-shot-index="${index}" style="padding: 4px 8px; font-size: 12px;">选择道具</button>
            </td>
          </tr>
        `;
      });

      html += `
          </tbody>
        </table>
      `;

      setTimeout(() => {
        document.querySelectorAll('.view-shot-detail').forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.shotIndex);
            if(shots[index]){
              openShotDetailModal(shots[index], nodeId, index);
            }
          });
        });

        document.querySelectorAll('.select-shot-location').forEach(btn => {
          btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.shotIndex);
            if(shots[index]){
              await selectLocationForShot(currentShotGroupNodeId, index);
            }
          });
        });
        
        document.querySelectorAll('.select-shot-props').forEach(btn => {
          btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.shotIndex);
            if(shots[index]){
              await selectPropsForShot(currentShotGroupNodeId, index);
            }
          });
        });
        
        // 绑定删除道具按钮事件
        document.querySelectorAll('.remove-shot-props-btn').forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const shotIndex = parseInt(btn.dataset.shotIndex);
            const propsIndex = parseInt(btn.dataset.propsIndex);
            removePropsFromShotTable(currentShotGroupNodeId, shotIndex, propsIndex);
          });
        });
      }, 0);

      return html;
    }

    async function selectLocationForShot(nodeId, shotIndex){
      const node = state.nodes.find(n => n.id === nodeId);
      if(!node || !node.data.shots[shotIndex]) return;

      // 保存上下文信息
      currentLocationSelectionContext = {
        nodeId: nodeId,
        shotIndex: shotIndex,
        isEditModal: false
      };
      window.currentLocationSelectionContext = currentLocationSelectionContext;

      // 打开场景选择弹窗
      openLocationModal();
    }
    
    // 从分镜组预览表格选择道具
    async function selectPropsForShot(nodeId, shotIndex){
      const node = state.nodes.find(n => n.id === nodeId);
      if(!node || !node.data.shots[shotIndex]) return;

      // 设置道具选择上下文
      window.currentPropsSelectionContext = {
        nodeId: nodeId,
        shotIndex: shotIndex,
        fromGroupTable: true
      };

      // 打开道具选择弹窗
      if(typeof window.openPropsModalForShot === 'function'){
        await window.openPropsModalForShot();
      } else {
        showToast('道具选择功能未初始化', 'error');
      }
    }
    
    // 从分镜组预览表格删除道具
    function removePropsFromShotTable(nodeId, shotIndex, propsIndex){
      const node = state.nodes.find(n => n.id === nodeId);
      if(!node || !node.data.shots || !node.data.shots[shotIndex]) return;
      
      const shot = node.data.shots[shotIndex];
      if(!shot.props || !Array.isArray(shot.props)) return;
      
      shot.props.splice(propsIndex, 1);
      
      // 更新分镜组预览表格
      if(shotGroupModal.classList.contains('show')){
        shotGroupModalContent.innerHTML = renderShotGroupTable(node.data, nodeId);
      }
      
      try{ autoSaveWorkflow(); } catch(e){}
      showToast('已删除道具', 'success');
    }

    async function selectLocationForShotDetail(nodeId, shotIndex){
      const node = state.nodes.find(n => n.id === nodeId);
      if(!node || !node.data.shots[shotIndex]) return;

      // 保存上下文信息，标记为从详情弹窗打开
      currentLocationSelectionContext = {
        nodeId: nodeId,
        shotIndex: shotIndex,
        isEditModal: false,
        fromDetailModal: true
      };
      window.currentLocationSelectionContext = currentLocationSelectionContext;

      // 打开场景选择弹窗
      openLocationModal();
    }

    function renderShotDetail(shot, nodeId, shotIndex){
      const fieldMap = {
        'shot_id': '镜头ID',
        'shot_number': '镜头编号',
        'duration': '时长(秒)',
        'location_id': '场景ID',
        'shot_type': '镜头类型',
        'camera_movement': '运镜方式',
        'description': '描述',
        'opening_frame_description': '起始画面描述',
        'scene_detail': '场景细节',
        'characters_present': '出场角色',
        'dialogue': '对话',
        'action': '动作',
        'mood': '情绪',
        'environment_sound': '环境音',
        'background_music': '背景音乐'
      };

      let html = '<div style="font-size: 14px;">';

      // 添加参考场景区域（放在最前面）
      if(nodeId !== undefined && shotIndex !== undefined){
        html += `
          <div style="margin-bottom: 20px; padding: 16px; background: #f9fafb; border-radius: 8px; border: 1px solid #e5e7eb;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
              <div style="font-weight: 600; color: #374151; font-size: 14px;">参考场景</div>
              <button class="mini-btn shot-detail-select-location" type="button" style="padding: 6px 12px; font-size: 13px;">选择场景</button>
            </div>
        `;
        
        if(shot.db_location_id && shot.db_location_pic){
          html += `
            <div style="display: flex; gap: 12px; align-items: center;">
              <img src="${escapeHtml(shot.db_location_pic)}" style="width: 120px; height: 120px; object-fit: cover; border-radius: 6px; border: 1px solid #e5e7eb;" alt="${escapeHtml(shot.location_name || '场景')}" />
              <div>
                <div style="font-size: 14px; font-weight: 500; color: #111827; margin-bottom: 4px;">${escapeHtml(shot.location_name || '未命名场景')}</div>
                <div style="font-size: 12px; color: #6b7280;">ID: ${shot.db_location_id}</div>
              </div>
            </div>
          `;
        } else {
          html += `
            <div style="text-align: center; padding: 20px; color: #9ca3af; font-size: 13px;">
              未选择参考场景
            </div>
          `;
        }
        
        html += `</div>`;

        // 添加参考道具区域（支持多选）
        html += `
          <div style="margin-bottom: 20px; padding: 16px; background: #f9fafb; border-radius: 8px; border: 1px solid #e5e7eb;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
              <div style="font-weight: 600; color: #374151; font-size: 14px;">参考道具</div>
              <button class="mini-btn shot-detail-add-props" type="button" style="padding: 6px 12px; font-size: 13px;">添加道具</button>
            </div>
        `;
        
        const propsArray = shot.props || [];
        if(propsArray.length > 0){
          html += `<div style="display: flex; flex-wrap: wrap; gap: 12px;">`;
          propsArray.forEach((prop, propIndex) => {
            html += `
              <div style="display: flex; gap: 8px; align-items: center; padding: 8px; background: #fff; border: 1px solid #e5e7eb; border-radius: 6px;">
                ${prop.reference_image ? `<img src="${escapeHtml(prop.reference_image)}" style="width: 50px; height: 50px; object-fit: cover; border-radius: 4px; border: 1px solid #e5e7eb;" alt="${escapeHtml(prop.name || '道具')}" />` : '<div style="width: 50px; height: 50px; background: #f3f4f6; border-radius: 4px; display: flex; align-items: center; justify-content: center; color: #9ca3af; font-size: 10px;">无图</div>'}
                <div style="flex: 1;">
                  <div style="font-size: 13px; font-weight: 500; color: #111827;">${escapeHtml(prop.name || '未命名道具')}</div>
                  <div style="font-size: 11px; color: #6b7280;">ID: ${prop.id}</div>
                </div>
                <button class="mini-btn secondary shot-detail-remove-props" data-props-index="${propIndex}" type="button" style="padding: 4px 8px; font-size: 11px; color: #ef4444;">移除</button>
              </div>
            `;
          });
          html += `</div>`;
        } else {
          html += `
            <div style="text-align: center; padding: 20px; color: #9ca3af; font-size: 13px;">
              未选择参考道具
            </div>
          `;
        }
        
        html += `</div>`;
      }

      for(const [key, label] of Object.entries(fieldMap)){
        if(shot[key] !== undefined && shot[key] !== null){
          let value = shot[key];
          
          if(key === 'characters_present' && Array.isArray(value)){
            value = value.join(', ');
          } else if(key === 'dialogue' && Array.isArray(value)){
            value = value.map(d => {
              return `<div style="margin: 5px 0; padding: 8px; background: #f8f9fa; border-radius: 4px;">
                <strong>${d.character_name || d.character_id}:</strong> ${d.text || ''} 
                <span style="color: #666; font-size: 12px;">(${d.timestamp || ''})</span>
              </div>`;
            }).join('');
          } else if(typeof value === 'object'){
            value = JSON.stringify(value, null, 2);
          }

          html += `
            <div style="margin-bottom: 15px; padding-bottom: 15px; border-bottom: 1px solid #eee;">
              <div style="font-weight: 600; color: #333; margin-bottom: 5px;">${label}</div>
              <div style="color: #666; line-height: 1.6;">${value}</div>
            </div>
          `;
        }
      }

      html += '</div>';
      
      // 绑定选择场景按钮事件
      if(nodeId !== undefined && shotIndex !== undefined){
        setTimeout(() => {
          const selectBtn = document.querySelector('.shot-detail-select-location');
          if(selectBtn){
            selectBtn.addEventListener('click', async (e) => {
              e.stopPropagation();
              await selectLocationForShotDetail(nodeId, shotIndex);
            });
          }
          
          // 绑定添加道具按钮事件
          const addPropsBtn = document.querySelector('.shot-detail-add-props');
          if(addPropsBtn){
            addPropsBtn.addEventListener('click', async (e) => {
              e.stopPropagation();
              await selectPropsForShotDetail(nodeId, shotIndex);
            });
          }
          
          // 绑定移除道具按钮事件
          const removePropsBtn = document.querySelectorAll('.shot-detail-remove-props');
          removePropsBtn.forEach(btn => {
            btn.addEventListener('click', (e) => {
              e.stopPropagation();
              const propsIndex = parseInt(btn.dataset.propsIndex);
              removePropsFromShot(nodeId, shotIndex, propsIndex);
            });
          });
        }, 0);
      }
      
      return html;
    }
    
    // 为分镜详情选择道具
    async function selectPropsForShotDetail(nodeId, shotIndex){
      window.currentPropsSelectionContext = {
        nodeId,
        shotIndex,
        fromDetailModal: true
      };
      
      // 打开道具选择弹窗
      if(typeof window.openPropsModalForShot === 'function'){
        await window.openPropsModalForShot();
      } else {
        showToast('道具选择功能未初始化', 'error');
      }
    }
    
    // 从分镜中移除道具
    function removePropsFromShot(nodeId, shotIndex, propsIndex){
      const node = state.nodes.find(n => n.id === nodeId);
      if(!node || !node.data.shots || !node.data.shots[shotIndex]) return;
      
      const shot = node.data.shots[shotIndex];
      if(!shot.props || !Array.isArray(shot.props)) return;
      
      shot.props.splice(propsIndex, 1);
      
      // 更新分镜详情弹窗
      shotDetailModalContent.innerHTML = renderShotDetail(shot, nodeId, shotIndex);
      
      // 同时更新分镜组详情弹窗（如果它是打开的）
      if(shotGroupModal.classList.contains('show')){
        shotGroupModalContent.innerHTML = renderShotGroupTable(node.data, nodeId);
      }
      
      try{ autoSaveWorkflow(); } catch(e){}
      showToast('已移除道具', 'success');
    }
    
    // 添加道具到分镜（供 events.js 调用）
    window.addPropsToShot = function(props){
      const context = window.currentPropsSelectionContext;
      if(!context) return;
      
      const { nodeId, shotIndex, fromDetailModal, fromEditModal } = context;
      const node = state.nodes.find(n => n.id === nodeId);
      if(!node || !node.data.shots || !node.data.shots[shotIndex]) return;
      
      const shot = node.data.shots[shotIndex];
      if(!shot.props) shot.props = [];
      
      // 检查是否已存在该道具
      const exists = shot.props.some(p => p.id === props.id);
      if(exists){
        showToast('该道具已添加', 'warning');
        return;
      }
      
      // 添加道具
      shot.props.push({
        id: props.id,
        name: props.name,
        reference_image: props.reference_image || ''
      });
      
      // 更新UI
      if(fromDetailModal){
        shotDetailModalContent.innerHTML = renderShotDetail(shot, nodeId, shotIndex);
        if(shotGroupModal.classList.contains('show')){
          shotGroupModalContent.innerHTML = renderShotGroupTable(node.data, nodeId);
        }
      } else if(fromEditModal){
        // 更新编辑弹窗
        shotGroupEditModalContent.innerHTML = renderShotGroupEditForm(node.data);
        bindShotEditEvents();
      } else if(context.fromGroupTable){
        // 更新分镜组预览表格
        if(shotGroupModal.classList.contains('show')){
          shotGroupModalContent.innerHTML = renderShotGroupTable(node.data, nodeId);
        }
      }
      
      // 关闭道具选择弹窗
      document.getElementById('propsModal').classList.remove('show');
      window.currentPropsSelectionContext = null;
      
      try{ autoSaveWorkflow(); } catch(e){}
      showToast('已添加道具', 'success');
    };

    function escapeHtml(value){
      if(value === null || value === undefined) return '';
      return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function getNodeCenter(nodeId){
      const node = state.nodes.find(n => n.id === nodeId);
      if(!node) return {x:0, y:0};
      const el = canvasEl.querySelector(`.node[data-node-id="${nodeId}"]`);
      if(!el) return {x: node.x, y: node.y};
      return {
        x: node.x + el.offsetWidth / 2,
        y: node.y + el.offsetHeight / 2
      };
    }

    function getOutputPortPos(nodeId){
      const nid = Number(nodeId);
      const node = state.nodes.find(n => n.id === nid);
      if(!node) return {x:0, y:0};
      const el = canvasEl.querySelector(`.node[data-node-id="${nid}"]`);
      if(!el) return {x: node.x, y: node.y};
      const portEl = el.querySelector('.port.output');
      if(portEl){
        // 获取端口相对于节点的偏移位置
        const portRect = portEl.getBoundingClientRect();
        const nodeRect = el.getBoundingClientRect();
        const offsetX = (portRect.left - nodeRect.left + portRect.width / 2) / state.zoom;
        const offsetY = (portRect.top - nodeRect.top + portRect.height / 2) / state.zoom;
        return {
          x: node.x + offsetX,
          y: node.y + offsetY
        };
      }
      return {
        x: node.x + el.offsetWidth,
        y: node.y + el.offsetHeight / 2
      };
    }

    function getInputPortPos(nodeId){
      const nid = Number(nodeId);
      const node = state.nodes.find(n => n.id === nid);
      if(!node) return {x:0, y:0};
      const el = canvasEl.querySelector(`.node[data-node-id="${nid}"]`);
      if(!el) return {x: node.x, y: node.y};
      const portEl = el.querySelector('.port.input');
      if(portEl){
        // 获取端口相对于节点的偏移位置
        const portRect = portEl.getBoundingClientRect();
        const nodeRect = el.getBoundingClientRect();
        const offsetX = (portRect.left - nodeRect.left + portRect.width / 2) / state.zoom;
        const offsetY = (portRect.top - nodeRect.top + portRect.height / 2) / state.zoom;
        return {
          x: node.x + offsetX,
          y: node.y + offsetY
        };
      }
      return {
        x: node.x,
        y: node.y + el.offsetHeight / 2
      };
    }

    function selectConnection(connId){
      state.selectedConnId = connId;
      state.selectedImgConnId = null;
      state.selectedNodeId = null;
      for(const nodeEl of canvasEl.querySelectorAll('.node')){
        nodeEl.classList.remove('selected');
      }
      for(const lineEl of connectionsSvg.querySelectorAll('path.line')){
        const cid = Number(lineEl.dataset.connId);
        lineEl.classList.toggle('selected', cid === connId);
      }
      // 显示删除按钮并定位到连接线中点
      if(connId !== null){
        const conn = state.connections.find(c => c.id === connId);
        if(conn){
          const from = getOutputPortPos(conn.from);
          const to = getInputPortPos(conn.to);
          const midX = ((from.x + to.x) / 2) * state.zoom + state.panX;
          const midY = ((from.y + to.y) / 2) * state.zoom + state.panY;
          connDeleteBtn.style.left = (midX - 12) + 'px';
          connDeleteBtn.style.top = (midY - 12) + 'px';
          connDeleteBtn.style.display = 'flex';
        }
      } else {
        connDeleteBtn.style.display = 'none';
      }
      renderImageConnections();
    }

    function hideConnDeleteBtn(){
      connDeleteBtn.style.display = 'none';
    }

    function removeConnection(connId){
      const conn = state.connections.find(c => c.id === connId);
      state.connections = state.connections.filter(c => c.id !== connId);
      if(state.selectedConnId === connId) state.selectedConnId = null;
      hideConnDeleteBtn();
      renderConnections();
      renderImageConnections();
      renderFirstFrameConnections();
      renderVideoConnections();
      renderReferenceConnections();
      
      // 如果删除的连接涉及分镜节点，更新其预览图和选择菜单
      if(conn){
        const fromNode = state.nodes.find(n => n.id === conn.from);
        const toNode = state.nodes.find(n => n.id === conn.to);
        
        // 如果删除的连接涉及角色节点，更新角色卡按钮状态
        if(fromNode && fromNode.type === 'character' && typeof updateCharacterCardButtonState === 'function'){
          updateCharacterCardButtonState(conn.from);
        }
        
        // 如果是分镜节点连接到图片节点，或图片节点连接到分镜节点
        if(fromNode && fromNode.type === 'shot_frame' && fromNode.updatePreview){
          fromNode.updatePreview();
        }
        if(toNode && toNode.type === 'shot_frame' && toNode.updatePreview){
          toNode.updatePreview();
        }
      }
    }

    function removeFirstFrameConnection(connId){
      const conn = state.firstFrameConnections.find(c => c.id === connId);
      state.firstFrameConnections = state.firstFrameConnections.filter(c => c.id !== connId);
      if(state.selectedFirstFrameConnId === connId) state.selectedFirstFrameConnId = null;
      hideConnDeleteBtn();
      renderFirstFrameConnections();
      
      // 如果删除的连接涉及分镜节点，更新其预览图
      if(conn){
        const toNode = state.nodes.find(n => n.id === conn.to);
        if(toNode && toNode.type === 'shot_frame'){
          toNode.data.previewImageUrl = '';
          const nodeEl = canvasEl.querySelector(`.node[data-node-id="${conn.to}"]`);
          if(nodeEl){
            const previewImageEl = nodeEl.querySelector('.shot-frame-preview-image');
            if(previewImageEl){
              previewImageEl.style.display = 'none';
              previewImageEl.src = '';
            }
          }
          // 刷新父分镜组的宫格预览
          const parentConn = state.connections.find(c => c.to === conn.to);
          if(parentConn){
            const parentNode = state.nodes.find(n => n.id === parentConn.from && n.type === 'shot_group');
            if(parentNode && parentNode.refreshGridPreview){
              parentNode.refreshGridPreview();
            }
          }
        }
      }
    }

    function renderConnections(tempLine){
      updateCanvasSize();
      
      let pathsHtml = '';
      for(const conn of state.connections){
        const from = getOutputPortPos(conn.from);
        const to = getInputPortPos(conn.to);
        const dx = Math.abs(to.x - from.x) * 0.5;
        const pathD = `M${from.x},${from.y} C${from.x+dx},${from.y} ${to.x-dx},${to.y} ${to.x},${to.y}`;
        const selected = state.selectedConnId === conn.id ? ' selected' : '';
        // 透明的hitbox用于点击
        pathsHtml += `<path class="hitbox" d="${pathD}" data-conn-id="${conn.id}"/>`;
        // 可见的线条
        pathsHtml += `<path class="line${selected}" d="${pathD}" data-conn-id="${conn.id}"/>`;
      }
      // 添加拖拽时的虚线预览
      if(tempLine){
        const dx = Math.abs(tempLine.toX - tempLine.fromX) * 0.5;
        pathsHtml += `<path class="temp" d="M${tempLine.fromX},${tempLine.fromY} C${tempLine.fromX+dx},${tempLine.fromY} ${tempLine.toX-dx},${tempLine.toY} ${tempLine.toX},${tempLine.toY}"/>`;
      }
      connectionsSvg.innerHTML = pathsHtml;
      
      // 重新绑定hitbox事件
      for(const hitbox of connectionsSvg.querySelectorAll('path.hitbox')){
        const connId = Number(hitbox.dataset.connId);
        const line = connectionsSvg.querySelector(`path.line[data-conn-id="${connId}"]`);
        
        hitbox.addEventListener('click', (e) => {
          e.stopPropagation();
          selectConnection(connId);
        });
        hitbox.addEventListener('mouseenter', () => {
          if(line && state.selectedConnId !== connId) line.classList.add('hover');
        });
        hitbox.addEventListener('mouseleave', () => {
          if(line) line.classList.remove('hover');
        });
      }
      
      // 更新删除按钮位置（如果有选中的连接线）
      if(state.selectedConnId !== null){
        const conn = state.connections.find(c => c.id === state.selectedConnId);
        if(conn){
          const from = getOutputPortPos(conn.from);
          const to = getInputPortPos(conn.to);
          const midX = ((from.x + to.x) / 2) * state.zoom + state.panX;
          const midY = ((from.y + to.y) / 2) * state.zoom + state.panY;
          connDeleteBtn.style.left = (midX - 12) + 'px';
          connDeleteBtn.style.top = (midY - 12) + 'px';
        }
      }
    }

    function getImageNodes(){
      return state.nodes.filter(n => n.type === 'image');
    }

    function renderImageConnections(){
      // 清除旧的图片连接线
      const oldLines = document.querySelectorAll('.image-conn-group');
      oldLines.forEach(l => l.remove());
      
      // 隐藏删除按钮（如果选中的连接已被删除）
      if(state.selectedImgConnId !== null){
        const stillExists = state.imageConnections.some(c => c.id === state.selectedImgConnId);
        if(!stillExists){
          state.selectedImgConnId = null;
          connDeleteBtn.style.display = 'none';
        }
      }
      
      // 绘制图片连接线
      for(const conn of state.imageConnections){
        const fromEl = canvasEl.querySelector(`.node[data-node-id="${conn.from}"]`);
        const toEl = canvasEl.querySelector(`.node[data-node-id="${conn.to}"]`);
        if(!fromEl || !toEl) continue;
        
        const outputPort = fromEl.querySelector('.port.output');
        const imagePort = toEl.querySelector(`.${conn.portType}-image-port`);
        if(!outputPort || !imagePort) continue;
        
        const fromRect = outputPort.getBoundingClientRect();
        const toRect = imagePort.getBoundingClientRect();
        const containerRect = canvasContainer.getBoundingClientRect();
        
        const fromX = (fromRect.left + fromRect.width/2 - containerRect.left - state.panX) / state.zoom;
        const fromY = (fromRect.top + fromRect.height/2 - containerRect.top - state.panY) / state.zoom;
        const toX = (toRect.left + toRect.width/2 - containerRect.left - state.panX) / state.zoom;
        const toY = (toRect.top + toRect.height/2 - containerRect.top - state.panY) / state.zoom;
        
        const dx = Math.abs(toX - fromX) * 0.5;
        const pathD = `M${fromX},${fromY} C${fromX+dx},${fromY} ${toX-dx},${toY} ${toX},${toY}`;
        
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.setAttribute('class', 'image-conn-group');
        group.dataset.imgConnId = String(conn.id);
        
        // hitbox（透明宽线，方便点击）
        const hitbox = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        hitbox.setAttribute('d', pathD);
        hitbox.setAttribute('class', 'hitbox');
        hitbox.style.fill = 'none';
        hitbox.style.stroke = 'transparent';
        hitbox.style.strokeWidth = '20';
        hitbox.style.cursor = 'pointer';
        
        // 可见线
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', pathD);
        path.setAttribute('class', 'visible');
        path.style.fill = 'none';
        path.style.stroke = '#3b82f6';
        path.style.strokeWidth = '2';
        path.style.pointerEvents = 'none';
        
        if(state.selectedImgConnId === conn.id){
          path.style.stroke = '#1d4ed8';
          path.style.strokeWidth = '3';
        }
        
        group.appendChild(hitbox);
        group.appendChild(path);
        connectionsSvg.appendChild(group);
        
        // 点击选中
        hitbox.addEventListener('click', (e) => {
          e.stopPropagation();
          state.selectedConnId = null;
          state.selectedImgConnId = conn.id;
          renderConnections();
          renderImageConnections();
          renderFirstFrameConnections();
          renderVideoConnections();
        });
        
        // 显示删除按钮（计算贝塞尔曲线t=0.5处的实际位置）
        if(state.selectedImgConnId === conn.id){
          // 控制点
          const cx1 = fromX + dx;
          const cy1 = fromY;
          const cx2 = toX - dx;
          const cy2 = toY;
          // 三次贝塞尔曲线 t=0.5 时的点
          const t = 0.5;
          const mt = 1 - t;
          const bezierX = mt*mt*mt*fromX + 3*mt*mt*t*cx1 + 3*mt*t*t*cx2 + t*t*t*toX;
          const bezierY = mt*mt*mt*fromY + 3*mt*mt*t*cy1 + 3*mt*t*t*cy2 + t*t*t*toY;
          // 转换为屏幕坐标
          const screenX = bezierX * state.zoom + state.panX;
          const screenY = bezierY * state.zoom + state.panY;
          connDeleteBtn.style.display = 'flex';
          connDeleteBtn.style.left = (screenX - 12) + 'px';
          connDeleteBtn.style.top = (screenY - 12) + 'px';
        }
      }
    }

    function renderVideoConnections(){
      try {
        // 检查必要的元素是否存在
        if(!connectionsSvg || !canvasEl || !canvasContainer) {
          return;
        }
        
        // 确保init化videoConnections数组
        if(!state.videoConnections) {
          state.videoConnections = [];
        }
        
        // 清除旧的视频连接线
        const oldLines = document.querySelectorAll('.video-conn-group');
        oldLines.forEach(l => l.remove());
        
        // 隐藏删除按钮（如果选中的连接已被删除）
        if(state.selectedVideoConnId !== null){
          const stillExists = state.videoConnections.some(c => c.id === state.selectedVideoConnId);
          if(!stillExists){
            state.selectedVideoConnId = null;
            if(connDeleteBtn) connDeleteBtn.style.display = 'none';
          }
        }
        
        // 绘制视频连接线
        for(const conn of state.videoConnections){
        const fromEl = canvasEl.querySelector(`.node[data-node-id="${conn.from}"]`);
        const toEl = canvasEl.querySelector(`.node[data-node-id="${conn.to}"]`);
        if(!fromEl || !toEl) continue;
        
        const outputPort = fromEl.querySelector('.port.output');
        const videoInputPort = toEl.querySelector('.port.video-input-port');
        if(!outputPort || !videoInputPort) continue;
        
        const fromRect = outputPort.getBoundingClientRect();
        const toRect = videoInputPort.getBoundingClientRect();
        const containerRect = canvasContainer.getBoundingClientRect();
        
        const fromX = (fromRect.left + fromRect.width/2 - containerRect.left - state.panX) / state.zoom;
        const fromY = (fromRect.top + fromRect.height/2 - containerRect.top - state.panY) / state.zoom;
        const toX = (toRect.left + toRect.width/2 - containerRect.left - state.panX) / state.zoom;
        const toY = (toRect.top + toRect.height/2 - containerRect.top - state.panY) / state.zoom;
        
        const dx = Math.abs(toX - fromX) * 0.5;
        const pathD = `M${fromX},${fromY} C${fromX+dx},${fromY} ${toX-dx},${toY} ${toX},${toY}`;
        
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.setAttribute('class', 'video-conn-group');
        group.dataset.videoConnId = String(conn.id);
        
        // hitbox（透明宽线，方便点击）
        const hitbox = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        hitbox.setAttribute('d', pathD);
        hitbox.setAttribute('class', 'hitbox');
        hitbox.style.fill = 'none';
        hitbox.style.stroke = 'transparent';
        hitbox.style.strokeWidth = '20';
        hitbox.style.cursor = 'pointer';
        
        // 可见线
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', pathD);
        path.setAttribute('class', 'visible');
        path.style.fill = 'none';
        path.style.stroke = '#3b82f6';
        path.style.strokeWidth = '2';
        path.style.pointerEvents = 'none';
        
        if(state.selectedVideoConnId === conn.id){
          path.style.stroke = '#1d4ed8';
          path.style.strokeWidth = '3';
        }
        
        group.appendChild(hitbox);
        group.appendChild(path);
        connectionsSvg.appendChild(group);
        
        // 点击选中
        hitbox.addEventListener('click', (e) => {
          e.stopPropagation();
          state.selectedConnId = null;
          state.selectedImgConnId = null;
          state.selectedFirstFrameConnId = null;
          state.selectedVideoConnId = conn.id;
          renderConnections();
          renderImageConnections();
          renderFirstFrameConnections();
          renderVideoConnections();
        });
        
        // 显示删除按钮（计算贝塞尔曲线t=0.5处的实际位置）
        if(state.selectedVideoConnId === conn.id){
          // 控制点
          const cx1 = fromX + dx;
          const cy1 = fromY;
          const cx2 = toX - dx;
          const cy2 = toY;
          // 三次贝塞尔曲线 t=0.5 时的点
          const t = 0.5;
          const mt = 1 - t;
          const bezierX = mt*mt*mt*fromX + 3*mt*mt*t*cx1 + 3*mt*t*t*cx2 + t*t*t*toX;
          const bezierY = mt*mt*mt*fromY + 3*mt*mt*t*cy1 + 3*mt*t*t*cy2 + t*t*t*toY;
          // 转换为屏幕坐标
          const screenX = bezierX * state.zoom + state.panX;
          const screenY = bezierY * state.zoom + state.panY;
          if(connDeleteBtn){
            connDeleteBtn.style.display = 'flex';
            connDeleteBtn.style.left = (screenX - 12) + 'px';
            connDeleteBtn.style.top = (screenY - 12) + 'px';
          }
        }
      }
      } catch(error) {
        console.error('[renderVideoConnections] Error:', error);
      }
    }

    function renderReferenceConnections(){
      // 清除旧的参考连接线
      const oldLines = document.querySelectorAll('.reference-conn-group');
      oldLines.forEach(l => l.remove());
      
      // 隐藏删除按钮（如果选中的连接已被删除）
      if(state.selectedReferenceConnId !== null){
        const stillExists = state.referenceConnections.some(c => c.id === state.selectedReferenceConnId);
        if(!stillExists){
          state.selectedReferenceConnId = null;
          connDeleteBtn.style.display = 'none';
        }
      }
      
      // 绘制参考连接线
      for(const conn of state.referenceConnections){
        const fromEl = canvasEl.querySelector(`.node[data-node-id="${conn.from}"]`);
        const toEl = canvasEl.querySelector(`.node[data-node-id="${conn.to}"]`);
        if(!fromEl || !toEl) continue;
        
        const outputPort = fromEl.querySelector('.port.output');
        const referencePort = toEl.querySelector('.port.reference');
        if(!outputPort || !referencePort) continue;
        
        const fromRect = outputPort.getBoundingClientRect();
        const toRect = referencePort.getBoundingClientRect();
        const containerRect = canvasContainer.getBoundingClientRect();
        
        const fromX = (fromRect.left + fromRect.width/2 - containerRect.left - state.panX) / state.zoom;
        const fromY = (fromRect.top + fromRect.height/2 - containerRect.top - state.panY) / state.zoom;
        const toX = (toRect.left + toRect.width/2 - containerRect.left - state.panX) / state.zoom;
        const toY = (toRect.top + toRect.height/2 - containerRect.top - state.panY) / state.zoom;
        
        const dx = Math.abs(toX - fromX) * 0.5;
        const pathD = `M${fromX},${fromY} C${fromX+dx},${fromY} ${toX-dx},${toY} ${toX},${toY}`;
        
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.setAttribute('class', 'reference-conn-group');
        group.dataset.referenceConnId = String(conn.id);
        
        // hitbox（透明宽线，方便点击）
        const hitbox = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        hitbox.setAttribute('d', pathD);
        hitbox.setAttribute('class', 'hitbox');
        hitbox.style.fill = 'none';
        hitbox.style.stroke = 'transparent';
        hitbox.style.strokeWidth = '20';
        hitbox.style.cursor = 'pointer';
        
        // 可见线（紫色虚线）
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', pathD);
        path.setAttribute('class', 'reference-line');
        
        if(state.selectedReferenceConnId === conn.id){
          path.classList.add('selected');
        }
        
        group.appendChild(hitbox);
        group.appendChild(path);
        connectionsSvg.appendChild(group);
        
        // 点击选中
        hitbox.addEventListener('click', (e) => {
          e.stopPropagation();
          state.selectedConnId = null;
          state.selectedImgConnId = null;
          state.selectedFirstFrameConnId = null;
          state.selectedVideoConnId = null;
          state.selectedReferenceConnId = conn.id;
          renderConnections();
          renderImageConnections();
          renderFirstFrameConnections();
          renderVideoConnections();
          renderReferenceConnections();
        });
        
        // 显示删除按钮（计算贝塞尔曲线t=0.5处的实际位置）
        if(state.selectedReferenceConnId === conn.id){
          // 控制点
          const cx1 = fromX + dx;
          const cy1 = fromY;
          const cx2 = toX - dx;
          const cy2 = toY;
          // 三次贝塞尔曲线 t=0.5 时的点
          const t = 0.5;
          const mt = 1 - t;
          const bezierX = mt*mt*mt*fromX + 3*mt*mt*t*cx1 + 3*mt*t*t*cx2 + t*t*t*toX;
          const bezierY = mt*mt*mt*fromY + 3*mt*mt*t*cy1 + 3*mt*t*t*cy2 + t*t*t*toY;
          // 转换为屏幕坐标
          const screenX = bezierX * state.zoom + state.panX;
          const screenY = bezierY * state.zoom + state.panY;
          connDeleteBtn.style.display = 'flex';
          connDeleteBtn.style.left = (screenX - 12) + 'px';
          connDeleteBtn.style.top = (screenY - 12) + 'px';
        }
      }
    }

    function renderFirstFrameConnections(){
      // 清除旧的首帧连接线
      const oldLines = document.querySelectorAll('.first-frame-conn-group');
      oldLines.forEach(l => l.remove());
      
      // 隐藏删除按钮（如果选中的连接已被删除）
      if(state.selectedFirstFrameConnId !== null){
        const stillExists = state.firstFrameConnections.some(c => c.id === state.selectedFirstFrameConnId);
        if(!stillExists){
          state.selectedFirstFrameConnId = null;
          connDeleteBtn.style.display = 'none';
        }
      }
      
      // 绘制首帧连接线（蓝色）
      for(const conn of state.firstFrameConnections){
        const fromEl = canvasEl.querySelector(`.node[data-node-id="${conn.from}"]`);
        const toEl = canvasEl.querySelector(`.node[data-node-id="${conn.to}"]`);
        if(!fromEl || !toEl) continue;
        
        const outputPort = fromEl.querySelector('.port.output');
        const firstFramePort = toEl.querySelector('.first-frame-port');
        if(!outputPort || !firstFramePort) continue;
        
        const fromRect = outputPort.getBoundingClientRect();
        const toRect = firstFramePort.getBoundingClientRect();
        const containerRect = canvasContainer.getBoundingClientRect();
        
        const fromX = (fromRect.left + fromRect.width/2 - containerRect.left - state.panX) / state.zoom;
        const fromY = (fromRect.top + fromRect.height/2 - containerRect.top - state.panY) / state.zoom;
        const toX = (toRect.left + toRect.width/2 - containerRect.left - state.panX) / state.zoom;
        const toY = (toRect.top + toRect.height/2 - containerRect.top - state.panY) / state.zoom;
        
        const dx = Math.abs(toX - fromX) * 0.5;
        const pathD = `M${fromX},${fromY} C${fromX+dx},${fromY} ${toX-dx},${toY} ${toX},${toY}`;
        
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.setAttribute('class', 'first-frame-conn-group');
        group.dataset.firstFrameConnId = String(conn.id);
        
        // hitbox（透明宽线，方便点击）
        const hitbox = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        hitbox.setAttribute('d', pathD);
        hitbox.setAttribute('class', 'hitbox');
        hitbox.style.fill = 'none';
        hitbox.style.stroke = 'transparent';
        hitbox.style.strokeWidth = '20';
        hitbox.style.cursor = 'pointer';
        
        // 可见线（蓝色）
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', pathD);
        path.setAttribute('class', 'visible');
        path.style.fill = 'none';
        path.style.stroke = '#3b82f6';
        path.style.strokeWidth = '2';
        path.style.pointerEvents = 'none';
        
        if(state.selectedFirstFrameConnId === conn.id){
          path.style.stroke = '#1d4ed8';
          path.style.strokeWidth = '3';
        }
        
        group.appendChild(hitbox);
        group.appendChild(path);
        connectionsSvg.appendChild(group);
        
        // 点击选中
        hitbox.addEventListener('click', (e) => {
          e.stopPropagation();
          state.selectedConnId = null;
          state.selectedImgConnId = null;
          state.selectedFirstFrameConnId = conn.id;
          renderConnections();
          renderImageConnections();
          renderFirstFrameConnections();
          renderVideoConnections();
        });
        
        // 显示删除按钮
        if(state.selectedFirstFrameConnId === conn.id){
          const cx1 = fromX + dx;
          const cy1 = fromY;
          const cx2 = toX - dx;
          const cy2 = toY;
          const t = 0.5;
          const mt = 1 - t;
          const bezierX = mt*mt*mt*fromX + 3*mt*mt*t*cx1 + 3*mt*t*t*cx2 + t*t*t*toX;
          const bezierY = mt*mt*mt*fromY + 3*mt*mt*t*cy1 + 3*mt*t*t*cy2 + t*t*t*toY;
          const screenX = bezierX * state.zoom + state.panX;
          const screenY = bezierY * state.zoom + state.panY;
          connDeleteBtn.style.display = 'flex';
          connDeleteBtn.style.left = (screenX - 12) + 'px';
          connDeleteBtn.style.top = (screenY - 12) + 'px';
        }
      }
    }

    function createImageToVideoNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = opts && typeof opts.y === 'number' ? opts.y : viewportPos.y;
      const node = {
        id,
        type: 'image_to_video',
        title: '图生视频',
        x,
        y,
        data: {
          prompt: '',
          duration: 5,
          ratio: state.ratio || '16:9',
          videoModel: 'wan22',
          drawCount: 1,
          motionEnabled: false,
          motion: '',
          startFile: null,
          endFile: null,
          startPreview: '',
          endPreview: '',
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';

      el.innerHTML = `
        <div class="port start-image-port" data-port-type="start" title="连接图片节点（首帧）"></div>
        <div class="port end-image-port" data-port-type="end" title="连接图片节点（尾帧）"></div>
        <div class="port output" title="输出（连接到视频节点）"></div>
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="3" y="6" width="14" height="12" rx="2"/><path d="M17 10L21 8V16L17 14V10Z" fill="currentColor"/></svg>${node.title}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field field-always-visible">
            <div class="preview-row start-preview-row" style="display:none;">
              <img class="preview start-preview" />
            </div>
          </div>
          <div class="field field-always-visible">
            <div class="preview-row end-preview-row" style="display:none;">
              <img class="preview end-preview" />
            </div>
          </div>
          <div class="field field-always-visible">
            <div class="gen-meta prompt-preview" style="font-size: 12px; color: #666;"></div>
          </div>
          <div class="field field-collapsible">
            <div class="label">首帧画面<span class="req">*</span></div>
            <input class="start-file" type="file" accept="image/*" />
            <button class="mini-btn start-clear" type="button" style="margin-top: 4px;">清除</button>
          </div>
          <div class="field field-collapsible">
            <div class="label">尾帧画面（可选）</div>
            <input class="end-file" type="file" accept="image/*" />
            <button class="mini-btn end-clear" type="button" style="margin-top: 4px;">清除</button>
          </div>
          <div class="field field-collapsible">
            <div class="label">视频长度</div>
            <select class="duration-select">
              <option value="5" selected>5秒</option>
              <option value="10">10秒</option>
            </select>
          </div>
          <div class="field field-collapsible">
            <div class="label">视频比例</div>
            <select class="ratio-select">
              <option value="9:16">9:16</option>
              <option value="3:4">3:4</option>
              <option value="1:1">1:1</option>
              <option value="4:3">4:3</option>
              <option value="16:9">16:9</option>
            </select>
          </div>
          <div class="field field-collapsible">
            <div class="label">视频模型</div>
            <select class="video-model-select">
              <option value="wan22" selected>Wan2.2</option>
              <option value="sora2">Sora2</option>
              <option value="ltx2">LTX2.0</option>
              <option value="kling">可灵</option>
              <option value="vidu">Vidu</option>
              <option value="veo3">VEO3.1</option>
            </select>
          </div>
          <div class="field field-collapsible">
            <div class="label">提示词</div>
            <textarea class="prompt" placeholder="请输入提示词..." rows="3"></textarea>
          </div>
          <div class="field field-collapsible computing-power-field" style="padding: 6px; border-radius: 6px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span style="color: #9ca3af; font-size: 12px;">算力消耗：</span>
              <span class="computing-power-value" style="color: #60a5fa; font-weight: bold; font-size: 14px;">0 算力</span>
            </div>
            <div class="computing-power-detail" style="margin-top: 4px; font-size: 11px; color: #6b7280;">
              单个 0 算力 × 1 个 = 0 算力
            </div>
          </div>
          <div class="field field-collapsible">
            <div class="label">生成视频</div>
            <div class="gen-container">
              <button class="gen-btn gen-btn-main" type="button">生成视频</button>
              <button class="gen-btn gen-btn-caret" type="button" aria-label="选择抽卡次数">▾</button>
              <div class="gen-menu">
                <div class="gen-item" data-count="1">X1</div>
                <div class="gen-item" data-count="2">X2</div>
                <div class="gen-item" data-count="3">X3</div>
                <div class="gen-item" data-count="4">X4</div>
              </div>
            </div>
            <div class="gen-meta gen-count-label"></div>
            <div class="gen-meta gen-status" style="display:none;"></div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const promptEl = el.querySelector('.prompt');
      const promptPreview = el.querySelector('.prompt-preview');
      const durationSelect = el.querySelector('.duration-select');
      const ratioSelect = el.querySelector('.ratio-select');
      const videoModelSelect = el.querySelector('.video-model-select');
      const genBtnMain = el.querySelector('.gen-btn-main');
      const genBtnCaret = el.querySelector('.gen-btn-caret');
      const genMenu = el.querySelector('.gen-menu');
      const genCountLabel = el.querySelector('.gen-count-label');
      const genStatus = el.querySelector('.gen-status');
      const computingPowerValue = el.querySelector('.computing-power-value');
      const computingPowerDetail = el.querySelector('.computing-power-detail');
      const outputPort = el.querySelector('.port.output');
      const startImagePort = el.querySelector('.start-image-port');
      const endImagePort = el.querySelector('.end-image-port');

      outputPort.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
      });

      // 初始化videoModel
      if(!node.data.videoModel){
        node.data.videoModel = 'wan22';
      }
      
      // 计算算力消耗
      function calculateComputingPower() {
        const config = getTaskComputingPowerConfig();
        if(!config || Object.keys(config).length === 0) {
          return 0;
        }
        
        let power = 0;
        const videoModel = node.data.videoModel || 'sora2';
        const duration = node.data.duration || 10;
        
        if(videoModel === 'sora2') {
          power = config[3] || 0;  // type=3: Sora2 图生视频
        } else if(videoModel === 'ltx2') {
          power = config[10] || 0;  // type=10: LTX2.0 图生视频
        } else if(videoModel === 'wan22') {
          // type=11: Wan2.2根据时长区分算力
          const wan22Power = config[11];
          if(typeof wan22Power === 'object') {
            power = wan22Power[duration] || wan22Power[5] || 0;
          } else {
            power = wan22Power || 0;
          }
        } else if(videoModel === 'kling') {
          // type=12: 可灵根据时长区分算力
          const klingPower = config[12];
          if(typeof klingPower === 'object') {
            power = klingPower[duration] || klingPower[5] || 0;
          } else {
            power = klingPower || 0;
          }
        } else if(videoModel === 'vidu') {
          // type=14: Vidu根据时长区分算力
          const viduPower = config[14];
          if(typeof viduPower === 'object') {
            power = viduPower[duration] || viduPower[5] || 0;
          } else {
            power = viduPower || 0;
          }
        } else if(videoModel === 'veo3') {
          // type=15: VEO3固定算力
          power = config[15] || 0;
        }
        
        return power;
      }
      
      // 更新算力显示
      function updateComputingPowerDisplay() {
        const singlePower = calculateComputingPower();
        const count = node.data.drawCount || 1;
        const totalPower = singlePower * count;
        
        if(computingPowerValue) {
          computingPowerValue.textContent = `${totalPower} 算力`;
        }
        if(computingPowerDetail) {
          computingPowerDetail.textContent = `单个 ${singlePower} 算力 × ${count} 个 = ${totalPower} 算力`;
        }
      }
      
      durationSelect.addEventListener('change', () => {
        node.data.duration = Number(durationSelect.value);
        updateComputingPowerDisplay();
      });

      ratioSelect.value = node.data.ratio;
      ratioSelect.addEventListener('change', () => {
        node.data.ratio = ratioSelect.value;
      });

      // 根据模型更新时长选项
      function updateDurationOptions(videoModel) {
        const currentDuration = durationSelect.value;
        durationSelect.innerHTML = '';
        
        if(videoModel === 'ltx2') {
          // LTX2.0: 5, 8, 10秒
          durationSelect.innerHTML = `
            <option value="5">5秒 (121帧)</option>
            <option value="8">8秒 (201帧)</option>
            <option value="10">10秒 (241帧)</option>
          `;
          if(['5', '8', '10'].includes(currentDuration)) {
            durationSelect.value = currentDuration;
          } else {
            durationSelect.value = '5';
            node.data.duration = 5;
          }
        } else if(videoModel === 'wan22' || videoModel === 'kling') {
          // Wan2.2 和可灵: 5, 10秒
          durationSelect.innerHTML = `
            <option value="5">5秒</option>
            <option value="10">10秒</option>
          `;
          if(['5', '10'].includes(currentDuration)) {
            durationSelect.value = currentDuration;
          } else {
            durationSelect.value = '5';
            node.data.duration = 5;
          }
        } else if(videoModel === 'vidu') {
          // Vidu: 5, 8秒
          durationSelect.innerHTML = `
            <option value="5">5秒</option>
            <option value="8">8秒</option>
          `;
          if(['5', '8'].includes(currentDuration)) {
            durationSelect.value = currentDuration;
          } else {
            durationSelect.value = '5';
            node.data.duration = 5;
          }
        } else if(videoModel === 'veo3') {
          // VEO3: 固定8秒
          durationSelect.innerHTML = `
            <option value="8">8秒</option>
          `;
          durationSelect.value = '8';
          node.data.duration = 8;
        } else {
          // Sora2: 10, 15秒
          durationSelect.innerHTML = `
            <option value="10">10秒</option>
            <option value="15">15秒</option>
          `;
          if(['10', '15'].includes(currentDuration)) {
            durationSelect.value = currentDuration;
          } else {
            durationSelect.value = '10';
            node.data.duration = 10;
          }
        }
      }
      
      // 根据模型更新比例选项（所有模型都只支持16:9和9:16）
      function updateRatioOptions(videoModel) {
        const ratioField = ratioSelect.closest('.field');
        
        // vidu 模型隐藏比例选择器
        if(videoModel === 'vidu') {
          if(ratioField) ratioField.style.display = 'none';
          return;
        }
        
        // 其他模型显示比例选择器
        if(ratioField) ratioField.style.display = '';
        
        const currentRatio = ratioSelect.value;
        ratioSelect.innerHTML = `
          <option value="9:16">9:16 (竖屏)</option>
          <option value="16:9">16:9 (横屏)</option>
        `;
        // 如果当前比例不在支持列表中，默认使用16:9
        if(currentRatio !== '9:16' && currentRatio !== '16:9') {
          ratioSelect.value = '16:9';
          node.data.ratio = '16:9';
        } else {
          ratioSelect.value = currentRatio;
        }
      }
      
      videoModelSelect.value = node.data.videoModel;
      // 初始化时根据模型设置时长和比例选项
      updateDurationOptions(node.data.videoModel);
      updateRatioOptions(node.data.videoModel);
      
      videoModelSelect.addEventListener('change', () => {
        node.data.videoModel = videoModelSelect.value;
        // 模型改变时更新时长和比例选项
        updateDurationOptions(videoModelSelect.value);
        updateRatioOptions(videoModelSelect.value);
        // 更新算力显示
        updateComputingPowerDisplay();
      });

      /* 运镜功能暂时隐藏
      function setMotionHelp(val){
        if(val === 'pan_left'){
          motionHelpIllu.innerHTML = `
            <svg viewBox="0 0 120 44" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <rect x="6" y="8" width="84" height="28" rx="6" stroke="#9ca3af" stroke-width="2"/>
              <path d="M100 22H116" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round"/>
              <path d="M104 16L98 22L104 28" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M78 22H30" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round"/>
              <path d="M34 16L28 22L34 28" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          `;
          motionHelpText.textContent = '画面整体向左移动（横向平移），适合展示横向场景。';
        } else if(val === 'pan_right'){
          motionHelpIllu.innerHTML = `
            <svg viewBox="0 0 120 44" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <rect x="30" y="8" width="84" height="28" rx="6" stroke="#9ca3af" stroke-width="2"/>
              <path d="M4 22H20" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round"/>
              <path d="M16 16L22 22L16 28" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M42 22H90" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round"/>
              <path d="M86 16L92 22L86 28" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          `;
          motionHelpText.textContent = '画面整体向右移动（横向平移），适合跟随主体或扫景。';
        } else if(val === 'zoom_out'){
          motionHelpIllu.innerHTML = `
            <svg viewBox="0 0 120 44" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <rect x="40" y="12" width="40" height="20" rx="6" stroke="#22c55e" stroke-width="2.5"/>
              <rect x="26" y="8" width="68" height="28" rx="8" stroke="#9ca3af" stroke-width="2"/>
              <path d="M60 22L44 14" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round"/>
              <path d="M60 22L76 14" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round"/>
              <path d="M60 22L44 30" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round"/>
              <path d="M60 22L76 30" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round"/>
            </svg>
          `;
          motionHelpText.textContent = '镜头拉远（Zoom Out），视野变大，更强调环境与整体氛围。';
        } else {
          motionHelpIllu.innerHTML = `
            <svg viewBox="0 0 120 44" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <rect x="26" y="8" width="68" height="28" rx="8" stroke="#22c55e" stroke-width="2.5"/>
              <rect x="40" y="12" width="40" height="20" rx="6" stroke="#9ca3af" stroke-width="2"/>
              <path d="M44 14L60 22" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round"/>
              <path d="M76 14L60 22" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round"/>
              <path d="M44 30L60 22" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round"/>
              <path d="M76 30L60 22" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round"/>
            </svg>
          `;
          motionHelpText.textContent = '镜头推进（Zoom In），视野变小，更突出主体细节与情绪。';
        }
      }

      function updateMotionUI(){
        const enabled = !!node.data.motionEnabled;
        motionEnableEl.checked = enabled;
        motionOptionsEl.style.display = enabled ? 'block' : 'none';
        if(!enabled){
          node.data.motion = '';
          return;
        }
        if(!node.data.motion){
          node.data.motion = 'pan_left';
        }
        motionSelect.value = node.data.motion;
        setMotionHelp(node.data.motion);
      }

      motionEnableEl.addEventListener('change', () => {
        node.data.motionEnabled = motionEnableEl.checked;
        updateMotionUI();
      });

      motionSelect.addEventListener('change', () => {
        node.data.motion = motionSelect.value;
        setMotionHelp(node.data.motion);
      });

      updateMotionUI();
      */

      function updateGenMeta(){
        genCountLabel.textContent = `抽卡次数：X${node.data.drawCount}`;
        // 同时更新算力显示
        updateComputingPowerDisplay();
      }
      updateGenMeta();

      genBtnCaret.addEventListener('click', (e) => {
        e.stopPropagation();
        genMenu.classList.toggle('show');
      });

      for(const item of genMenu.querySelectorAll('.gen-item')){
        item.addEventListener('click', (e) => {
          e.stopPropagation();
          const count = Number(item.dataset.count || '1');
          node.data.drawCount = count;
          updateGenMeta();
          genMenu.classList.remove('show');
        });
      }
      
      // 初始化算力显示
      updateComputingPowerDisplay();

      document.addEventListener('click', (e) => {
        if(!e.target.closest('.gen-container')){
          genMenu.classList.remove('show');
        }
      });

      genBtnMain.addEventListener('click', async (e) => {
        e.stopPropagation();

        // 检查提示词是否存在
        const prompt = (node.data.prompt || '').trim();
        if(!prompt){
          genStatus.style.display = 'block';
          genStatus.style.color = '#dc2626';
          genStatus.textContent = '请先输入提示词';
          showToast('请先输入提示词', 'error');
          return;
        }

        // 获取首帧图片URL
        let startImageUrl = '';
        if(node.data.startUrl){
          startImageUrl = node.data.startUrl;
        } else {
          const startConn = state.imageConnections.find(c => c.to === id && c.portType === 'start');
          if(startConn){
            const fromNode = state.nodes.find(n => n.id === startConn.from);
            if(fromNode && fromNode.type === 'image' && fromNode.data && fromNode.data.url){
              startImageUrl = fromNode.data.url;
            }
          }
        }

        if(!startImageUrl){
          genStatus.style.display = 'block';
          genStatus.style.color = '#dc2626';
          genStatus.textContent = '请先上传首帧图片';
          return;
        }

        // 获取尾帧图片URL（可选）
        let endImageUrl = '';
        if(node.data.endUrl){
          endImageUrl = node.data.endUrl;
        } else {
          const endConn = state.imageConnections.find(c => c.to === id && c.portType === 'end');
          if(endConn){
            const fromNode = state.nodes.find(n => n.id === endConn.from);
            if(fromNode && fromNode.type === 'image' && fromNode.data && fromNode.data.url){
              endImageUrl = fromNode.data.url;
            }
          }
        }

        // 拼接图片URL：如果有尾帧，用逗号拼接；否则只传首帧
        const imageUrls = endImageUrl ? `${startImageUrl},${endImageUrl}` : startImageUrl;

        // 禁用按钮
        genBtnMain.disabled = true;
        genBtnMain.textContent = '生成中...';
        genStatus.style.color = '';
        genStatus.style.display = 'block';
        genStatus.textContent = '正在提交任务...';

        try {
          const desiredCount = Math.max(1, Number(node.data.drawCount) || 1);
          const duration = node.data.duration || 10;
          const prompt = node.data.prompt || '';
          const ratio = node.data.ratio || state.ratio || '9:16';
          const videoModel = node.data.videoModel || 'sora2';
          
          console.log('[DEBUG] 生成视频参数:', { drawCount: node.data.drawCount, desiredCount, duration, prompt, ratio, videoModel, imageUrls });

          // 调用生成API
          const result = await generateVideoFromImage(imageUrls, prompt, duration, desiredCount, ratio, videoModel);
          console.log('[DEBUG] API返回:', { projectIds: result.projectIds, count: result.projectIds?.length });
          
          genStatus.textContent = '任务已提交，正在生成视频...';
          node.data.projectIds = result.projectIds;

          // 创建对应数量的视频节点
          const connectedVideoIds = Array.from(new Set(
            state.connections
              .filter(c => c.from === id)
              .map(c => c.to)
              .filter(toId => {
                const toNode = state.nodes.find(n => n.id === toId);
                return toNode && toNode.type === 'video';
              })
          ));
          const missingCount = Math.max(0, desiredCount - connectedVideoIds.length);
          console.log('[DEBUG] 视频节点:', { connectedVideoIds, desiredCount, missingCount });
          const newVideoNodeIds = [];

          for(let i = 0; i < missingCount; i++){
            const newVideoId = createVideoNode({ x: node.x + 380, y: node.y + i * 260 });
            state.connections.push({ id: state.nextConnId++, from: id, to: newVideoId });
            newVideoNodeIds.push(newVideoId);
            
            // 立即为新创建的视频节点绑定 project_id
            const newVideoNode = state.nodes.find(n => n.id === newVideoId);
            if(newVideoNode && result.projectIds){
              const projectIdIndex = connectedVideoIds.length + i;
              newVideoNode.data.project_id = result.projectIds[projectIdIndex] || result.projectIds[0];
              console.log(`[图生视频] 新建视频节点 ${newVideoId} 绑定 project_id:`, newVideoNode.data.project_id);
            }
          }
          
          // 为已存在的连接视频节点也绑定 project_id
          connectedVideoIds.forEach((videoNodeId, idx) => {
            const videoNode = state.nodes.find(n => n.id === videoNodeId);
            if(videoNode && result.projectIds){
              videoNode.data.project_id = result.projectIds[idx] || result.projectIds[0];
              console.log(`[图生视频] 已存在视频节点 ${videoNodeId} 绑定 project_id:`, videoNode.data.project_id);
            }
          });
          
          // 合并所有视频节点ID
          const allVideoNodeIds = [...connectedVideoIds, ...newVideoNodeIds];
          
          renderConnections();
          renderImageConnections();
          renderFirstFrameConnections();
          renderVideoConnections();
          renderMinimap();

          // 为每个视频节点初始化状态显示
          allVideoNodeIds.forEach((videoNodeId, idx) => {
            const videoEl = canvasEl.querySelector(`.node[data-node-id="${videoNodeId}"]`);
            if(videoEl){
              const statusField = videoEl.querySelector('.video-status-field');
              const statusEl = videoEl.querySelector('.video-status');
              if(statusField && statusEl){
                statusField.style.display = 'block';
                statusEl.style.color = '';
                statusEl.textContent = '生成中...';
              }
            }
          });

          // 轮询状态
          pollVideoStatus(
            result.projectIds,
            (progressText) => {
              genStatus.textContent = progressText;
            },
            (statusResult) => {
              // 生成完成（可能部分成功部分失败）
              if(TEST_MODE){
                console.log('[TEST MODE] onComplete raw result:', statusResult);
              }

              genBtnMain.disabled = false;
              genBtnMain.textContent = '生成视频';
              
              const tasks = statusResult.tasks || [];
              let successCount = 0;
              let failedCount = 0;
              
              // 为每个视频节点独立处理结果
              tasks.forEach((task, idx) => {
                if(idx >= allVideoNodeIds.length) return;
                
                const videoNodeId = allVideoNodeIds[idx];
                const videoNode = state.nodes.find(n => n.id === videoNodeId);
                const videoEl = canvasEl.querySelector(`.node[data-node-id="${videoNodeId}"]`);
                
                if(!videoNode || !videoEl) return;
                
                const statusField = videoEl.querySelector('.video-status-field');
                const statusEl = videoEl.querySelector('.video-status');
                const previewField = videoEl.querySelector('.video-preview-field');
                const thumbVideo = videoEl.querySelector('.video-thumb');
                const nameEl = videoEl.querySelector('.video-name');
                
                if(task.status === 'SUCCESS' && task.result){
                  // 成功：显示视频
                  successCount++;
                  const videoUrl = normalizeVideoUrl(task.result);
                  
                  if(videoUrl){
                    videoNode.data.url = videoUrl;
                    videoNode.data.name = `视频${idx + 1}`;
                    videoNode.data.project_id = node.data.projectIds[idx] || node.data.projectIds[0];
                    console.log(`[图生视频] 视频节点 ${videoNodeId} 绑定 project_id:`, videoNode.data.project_id, '来源:', node.data.projectIds, 'index:', idx);
                    
                    if(previewField && thumbVideo && nameEl){
                      thumbVideo.src = proxyDownloadUrl(videoUrl);
                      thumbVideo.muted = true;
                      thumbVideo.loop = true;
                      thumbVideo.controls = false;
                      thumbVideo.preload = 'metadata';
                      thumbVideo.playsInline = true;
                      thumbVideo.onloadedmetadata = () => {
                        try{
                          if(isFinite(thumbVideo.duration) && thumbVideo.duration > 0){
                            thumbVideo.currentTime = Math.min(0.1, Math.max(0, thumbVideo.duration - 0.1));
                          }
                        } catch(e){}
                        try{
                          const p = thumbVideo.play();
                          if(p && typeof p.catch === 'function') p.catch(() => {});
                        } catch(e){}
                      };
                      try{ thumbVideo.load(); } catch(e){}
                      const displayName = videoNode.data.name.length > 10 ? videoNode.data.name.substring(0, 10) + '...' : videoNode.data.name;
                      nameEl.textContent = displayName;
                      nameEl.title = videoNode.data.name;
                      previewField.style.display = 'block';
                      const previewActionsField2 = videoEl.querySelector('.video-preview-actions-field');
                      if(previewActionsField2) previewActionsField2.style.display = 'block';
                    }
                    
                    if(statusField && statusEl){
                      statusEl.style.color = '#16a34a';
                      statusEl.textContent = '✓ 生成成功';
                    }
                  } else {
                    if(statusField && statusEl){
                      statusEl.style.color = '#dc2626';
                      statusEl.textContent = '✗ 生成成功但未返回视频地址';
                    }
                  }
                } else if(task.status === 'FAILED'){
                  // 失败：只统计失败数量，不修改状态显示（状态已在onTaskUpdate中设置）
                  failedCount++;
                  // 不再修改statusEl，保留onTaskUpdate中设置的详细错误信息
                }
              });
              
              // 更新图生视频节点的总体状态（智能判断）
              const totalCount = successCount + failedCount;
              if(successCount === totalCount && successCount > 0){
                // 全部成功
                genStatus.style.color = '#16a34a';
                genStatus.textContent = `全部成功！共${successCount}个视频`;
                showToast('视频生成成功！', 'success');
              } else if(failedCount === totalCount && failedCount > 0){
                // 全部失败
                genStatus.style.color = '#dc2626';
                genStatus.textContent = `全部失败：${failedCount}个任务失败`;
                showToast('视频生成失败', 'error');
              } else if(successCount > 0 && failedCount > 0){
                // 部分成功部分失败
                genStatus.style.color = '#f59e0b';
                genStatus.textContent = `部分成功：${successCount}个成功，${failedCount}个失败`;
                showToast(`部分成功：${successCount}个成功，${failedCount}个失败`, 'error');
              } else {
                genStatus.style.color = '#dc2626';
                genStatus.textContent = '生成完成但未获取到有效结果';
                showToast('生成完成但未获取到有效结果', 'error');
              }
              
              // 刷新用户算力显示
              if(typeof fetchComputingPower === 'function'){
                fetchComputingPower();
              }
            },
            (errorMsg) => {
              // 轮询或请求失败
              genStatus.style.color = '#dc2626';
              genStatus.textContent = errorMsg;
              genBtnMain.disabled = false;
              genBtnMain.textContent = '生成视频';
              
              // 更新所有视频节点状态为失败
              allVideoNodeIds.forEach((videoNodeId) => {
                const videoEl = canvasEl.querySelector(`.node[data-node-id="${videoNodeId}"]`);
                if(videoEl){
                  const statusField = videoEl.querySelector('.video-status-field');
                  const statusEl = videoEl.querySelector('.video-status');
                  if(statusField && statusEl){
                    statusField.style.display = 'block';
                    statusEl.style.color = '#dc2626';
                    statusEl.textContent = `✗ ${errorMsg}`;
                  }
                }
              });
              
              showToast('视频生成失败: ' + errorMsg, 'error');
            },
            // 实时更新每个任务的状态（新增的回调）
            (tasks) => {
              tasks.forEach((task, idx) => {
                if(idx >= allVideoNodeIds.length) return;
                
                const videoNodeId = allVideoNodeIds[idx];
                const videoEl = canvasEl.querySelector(`.node[data-node-id="${videoNodeId}"]`);
                
                if(!videoEl) return;
                
                const statusField = videoEl.querySelector('.video-status-field');
                const statusEl = videoEl.querySelector('.video-status');
                
                if(!statusField || !statusEl) return;
                
                // 只更新已经完成（成功或失败）的任务状态
                if(task.status === 'FAILED'){
                  statusField.style.display = 'block';
                  statusEl.style.color = '#dc2626';
                  statusEl.textContent = `✗ 生成失败: ${task.error || '未知错误'}`;
                } else if(task.status === 'SUCCESS' && task.result){
                  // 成功的任务在这里只更新状态文本，视频加载留给onComplete处理
                  statusField.style.display = 'block';
                  statusEl.style.color = '#16a34a';
                  statusEl.textContent = '✓ 生成成功，加载中...';
                } else if(task.status === 'RUNNING'){
                  // 运行中的任务保持"生成中..."状态
                  statusField.style.display = 'block';
                  statusEl.style.color = '';
                  statusEl.textContent = '生成中...';
                }
              });
            }
          );

        } catch(err){
          console.error('Generate error:', err);
          genStatus.style.color = '#dc2626';
          genStatus.textContent = err.message || '生成失败';
          genBtnMain.disabled = false;
          genBtnMain.textContent = '生成视频';
          showToast('视频生成失败: ' + err.message, 'error');
        }
      });

      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });

      el.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.stopPropagation();
        setSelected(id);
        bringNodeToFront(id);
      });

      headerEl.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.preventDefault();
        e.stopPropagation();
        setSelected(id);
        bringNodeToFront(id);
        initNodeDrag(id, e.clientX, e.clientY);
      });

      // 图片端口接收连接
      startImagePort.addEventListener('mouseup', (e) => {
        if(state.connecting && state.connecting.fromId !== id){
          const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
          if(fromNode && fromNode.type === 'image' && !node.data.startFile){
            const exists = state.imageConnections.some(c => c.to === id && c.portType === 'start');
            if(!exists){
              state.imageConnections.push({
                id: state.nextImgConnId++,
                from: state.connecting.fromId,
                to: id,
                portType: 'start'
              });
              renderImageConnections();
              renderVideoConnections();
            }
          }
        }

        // 如果从图生视频节点拖拽，查找视频节点输入端口
        const fromNodeForI2V = state.connecting ? state.nodes.find(n => n.id === state.connecting.fromId) : null;
        if(fromNodeForI2V && fromNodeForI2V.type === 'image_to_video'){
          for(const node of state.nodes){
            if(node.type !== 'video') continue;
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
        state.connecting = null;
      });

      endImagePort.addEventListener('mouseup', (e) => {
        if(state.connecting && state.connecting.fromId !== id){
          const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
          if(fromNode && fromNode.type === 'image' && !node.data.endFile){
            const exists = state.imageConnections.some(c => c.to === id && c.portType === 'end');
            if(!exists){
              state.imageConnections.push({
                id: state.nextImgConnId++,
                from: state.connecting.fromId,
                to: id,
                portType: 'end'
              });
              renderImageConnections();
              renderVideoConnections();
            }
          }
        }
        state.connecting = null;
      });

      promptEl.addEventListener('input', () => {
        node.data.prompt = promptEl.value;
        if(promptPreview) {
          const preview = node.data.prompt ? (node.data.prompt.length > 50 ? node.data.prompt.substring(0, 50) + '...' : node.data.prompt) : '';
          promptPreview.textContent = preview;
          promptPreview.style.display = preview ? 'block' : 'none';
        }
      });

      const startFileEl = el.querySelector('.start-file');
      const endFileEl = el.querySelector('.end-file');
      const startPreviewRow = el.querySelector('.start-preview-row');
      const endPreviewRow = el.querySelector('.end-preview-row');
      const startPreviewImg = el.querySelector('.start-preview');
      const endPreviewImg = el.querySelector('.end-preview');
      const startClearBtn = el.querySelector('.start-clear');
      const endClearBtn = el.querySelector('.end-clear');

      startPreviewImg.addEventListener('click', (e) => {
        e.stopPropagation();
        const src = startPreviewImg.getAttribute('src') || node.data.startPreview;
        if(!src) return;
        openImageModal(src, '首帧预览');
      });

      endPreviewImg.addEventListener('click', (e) => {
        e.stopPropagation();
        const src = endPreviewImg.getAttribute('src') || node.data.endPreview;
        if(!src) return;
        openImageModal(src, '尾帧预览');
      });

      startFileEl.addEventListener('change', async () => {
        const file = startFileEl.files && startFileEl.files[0];
        if(!file) return;
        
        // 先显示本地预览
        const localPreview = await readFileAsDataUrl(file);
        startPreviewImg.src = localPreview;
        startPreviewRow.style.display = 'flex';
        
        // 上传到服务器获取永久URL
        const uploadedUrl = await uploadFile(file);
        if(uploadedUrl){
          node.data.startUrl = uploadedUrl;
          node.data.startPreview = uploadedUrl;
          startPreviewImg.src = uploadedUrl;
          // 删除该端口的连接
          state.imageConnections = state.imageConnections.filter(c => !(c.to === id && c.portType === 'start'));
          startImagePort.classList.add('disabled');
          renderImageConnections();
          renderVideoConnections();
          showToast('首帧图片上传成功', 'success');
        } else {
          startPreviewRow.style.display = 'none';
          startPreviewImg.removeAttribute('src');
        }
        startFileEl.value = '';
      });

      endFileEl.addEventListener('change', async () => {
        const file = endFileEl.files && endFileEl.files[0];
        if(!file) return;
        
        // 先显示本地预览
        const localPreview = await readFileAsDataUrl(file);
        endPreviewImg.src = localPreview;
        endPreviewRow.style.display = 'flex';
        
        // 上传到服务器获取永久URL
        const uploadedUrl = await uploadFile(file);
        if(uploadedUrl){
          node.data.endUrl = uploadedUrl;
          node.data.endPreview = uploadedUrl;
          endPreviewImg.src = uploadedUrl;
          // 删除该端口的连接
          state.imageConnections = state.imageConnections.filter(c => !(c.to === id && c.portType === 'end'));
          endImagePort.classList.add('disabled');
          renderImageConnections();
          renderVideoConnections();
          showToast('尾帧图片上传成功', 'success');
        } else {
          endPreviewRow.style.display = 'none';
          endPreviewImg.removeAttribute('src');
        }
        endFileEl.value = '';
      });

      startClearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        node.data.startFile = null;
        node.data.startUrl = '';
        node.data.startPreview = '';
        startPreviewRow.style.display = 'none';
        startPreviewImg.removeAttribute('src');
        startImagePort.classList.remove('disabled');
      });

      endClearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        node.data.endFile = null;
        node.data.endUrl = '';
        node.data.endPreview = '';
        endPreviewRow.style.display = 'none';
        endPreviewImg.removeAttribute('src');
        endImagePort.classList.remove('disabled');
      });

      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);
      setSelected(id);
    }

    function createImageNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = opts && typeof opts.y === 'number' ? opts.y : viewportPos.y;
      const defaultRatio = state.ratio || ratioSelectEl.value || '9:16';
      const node = {
        id,
        type: 'image',
        title: '图片',
        x,
        y,
        data: {
          file: null,
          url: '',
          name: '',
          preview: '',
          prompt: '',
          ratio: defaultRatio,
          model: 'gemini-2.5-pro-image-preview',
          drawCount: 1,
          project_id: null,
          camera: {
            yaw: 0,
            dolly: 0,
            pitch: 0,
            modified: { yaw: false, dolly: false, pitch: false }
          }
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';

      el.innerHTML = `
        <div class="port reference" title="参考端口（接收其他图片作为参考）"></div>
        <div class="port input" title="输入（连接分镜节点）"></div>
        <div class="port output" title="输出（连接到图生视频节点）"></div>
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="4" y="5" width="16" height="14" rx="2"/><path d="M7 15L10 12L13 15L16 11L20 17H4L7 15Z" fill="currentColor" opacity="0.35"/></svg>${node.title}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field field-always-visible">
            <div class="preview-row image-preview-row" style="display:none;">
              <img class="preview image-preview" />
            </div>
          </div>
          <div class="reference-images-section" style="display:none;">
            <div class="reference-images-header">
              <span>参考图片 (<span class="reference-images-count">0</span>)</span>
            </div>
            <div class="reference-images-grid"></div>
          </div>
          <div class="field field-collapsible">
            <div class="label">上传图片</div>
            <input class="image-file" type="file" accept="image/*" />
            <div style="display: flex; gap: 8px; margin-top: 8px;">
              <button class="mini-btn image-clear" type="button">清除</button>
              <button class="mini-btn image-download-icon-btn" type="button">下载</button>
            </div>
          </div>
          <div class="field field-collapsible">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <div class="label" style="margin: 0;">编辑提示词（可选）</div>
              <button class="mini-btn image-prompt-expand-btn" type="button" style="font-size: 11px; padding: 4px 8px;" title="放大编辑">⤢</button>
            </div>
            <textarea class="image-prompt" rows="2" placeholder="输入提示词进行图片编辑"></textarea>
          </div>
          <div class="field field-collapsible">
            <div class="label">模型</div>
            <select class="image-model">
              <option value="gemini-2.5-pro-image-preview">标准版 (2算力)</option>
              <option value="gemini-3-pro-image-preview">加强版 (6算力)</option>
            </select>
          </div>
          <div class="field field-collapsible">
            <div class="label">图片比例</div>
            <select class="image-ratio">
              <option value="9:16">竖屏 (9:16)</option>
              <option value="16:9">横屏 (16:9)</option>
              <option value="1:1">正方形 (1:1)</option>
              <option value="3:4">竖屏 (3:4)</option>
              <option value="4:3">横屏 (4:3)</option>
            </select>
          </div>
          <div class="field field-collapsible camera-control-section">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <div class="label" style="margin: 0;">相机控制</div>
              <button class="mini-btn camera-control-toggle-btn" type="button" style="font-size: 11px; padding: 4px 8px;">展开</button>
            </div>
            <div class="camera-control-content" style="display: none; flex-direction: column; gap: 12px; padding: 12px; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; margin-top: 4px;">
              <div class="camera-param-row" data-param="yaw">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                  <label style="font-size: 11px; font-weight: 600; color: #374151;">左右旋转 (Yaw)</label>
                  <div style="display: flex; align-items: center; gap: 6px;">
                    <input type="number" class="camera-input image-camera-yaw" value="0" min="-90" max="90" step="1" style="width: 60px; padding: 4px 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 11px; text-align: center;" />
                    <span style="font-size: 11px; color: #6b7280;">°</span>
                    <button type="button" class="camera-reset-btn image-camera-reset-yaw" style="padding: 4px 8px; font-size: 10px; border: 1px solid #d1d5db; border-radius: 4px; background: #fff; color: #6b7280; cursor: pointer;">重置</button>
                  </div>
                </div>
                <input type="range" class="camera-slider image-camera-yaw-slider" min="-90" max="90" step="1" value="0" style="width: 100%;" />
                <div style="display: flex; justify-content: space-between; font-size: 10px; color: #9ca3af; margin-top: 2px;">
                  <span>-90° (左侧)</span>
                  <span>0° (正面)</span>
                  <span>+90° (右侧)</span>
                </div>
              </div>
              <div class="camera-param-row" data-param="dolly">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                  <label style="font-size: 11px; font-weight: 600; color: #374151;">镜头距离 (Dolly)</label>
                  <div style="display: flex; align-items: center; gap: 6px;">
                    <input type="number" class="camera-input image-camera-dolly" value="0" min="0" max="10" step="0.5" style="width: 60px; padding: 4px 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 11px; text-align: center;" />
                    <button type="button" class="camera-reset-btn image-camera-reset-dolly" style="padding: 4px 8px; font-size: 10px; border: 1px solid #d1d5db; border-radius: 4px; background: #fff; color: #6b7280; cursor: pointer;">重置</button>
                  </div>
                </div>
                <input type="range" class="camera-slider image-camera-dolly-slider" min="0" max="10" step="0.5" value="0" style="width: 100%;" />
                <div style="display: flex; justify-content: space-between; font-size: 10px; color: #9ca3af; margin-top: 2px;">
                  <span>0 (远景)</span>
                  <span>5 (中景)</span>
                  <span>10 (特写)</span>
                </div>
              </div>
              <div class="camera-param-row" data-param="pitch">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                  <label style="font-size: 11px; font-weight: 600; color: #374151;">垂直角度 (Pitch)</label>
                  <div style="display: flex; align-items: center; gap: 6px;">
                    <input type="number" class="camera-input image-camera-pitch" value="0" min="-60" max="60" step="1" style="width: 60px; padding: 4px 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 11px; text-align: center;" />
                    <span style="font-size: 11px; color: #6b7280;">°</span>
                    <button type="button" class="camera-reset-btn image-camera-reset-pitch" style="padding: 4px 8px; font-size: 10px; border: 1px solid #d1d5db; border-radius: 4px; background: #fff; color: #6b7280; cursor: pointer;">重置</button>
                  </div>
                </div>
                <input type="range" class="camera-slider image-camera-pitch-slider" min="-60" max="60" step="1" value="0" style="width: 100%;" />
                <div style="display: flex; justify-content: space-between; font-size: 10px; color: #9ca3af; margin-top: 2px;">
                  <span>-60° (仰视)</span>
                  <span>0° (平视)</span>
                  <span>+60° (俯视)</span>
                </div>
              </div>
              <div style="margin-top: 8px;">
                <label style="display: block; font-size: 11px; font-weight: 600; color: #374151; margin-bottom: 6px;">3D 预览</label>
                <canvas class="camera-preview-canvas image-camera-canvas" width="200" height="150" style="width: 100%; max-width: 200px; height: 150px; border: 1px solid #e5e7eb; border-radius: 4px; background: #ffffff;"></canvas>
              </div>
            </div>
          </div>
          <div class="field field-collapsible">
            <div class="btn-row" style="display: flex; gap: 8px;">
              <div class="gen-container">
                <button class="gen-btn gen-btn-main image-edit-btn" type="button">编辑图片</button>
                <button class="gen-btn gen-btn-caret" type="button" aria-label="选择抽卡次数">▾</button>
                <div class="gen-menu">
                  <div class="gen-item" data-count="1">X1</div>
                  <div class="gen-item" data-count="2">X2</div>
                  <div class="gen-item" data-count="3">X3</div>
                  <div class="gen-item" data-count="4">X4</div>
                </div>
              </div>
              <button class="mini-btn secondary image-coloring-btn" type="button" style="border-radius: 10px;">涂色编辑</button>
            </div>
            <div class="gen-meta image-draw-count-label"></div>
            <div class="muted image-edit-status" style="display:none;"></div>
          </div>
          <div class="field field-collapsible image-confirm-field" style="display:none;">
            <button class="mini-btn image-confirm-shot-btn" type="button" style="background: #10b981; color: white; width: 100%;">确认分镜图</button>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const inputPort = el.querySelector('.port.input');
      const outputPort = el.querySelector('.port.output');
      const referencePort = el.querySelector('.port.reference');
      const referenceSection = el.querySelector('.reference-images-section');
      const referenceGrid = el.querySelector('.reference-images-grid');
      const referenceCount = el.querySelector('.reference-images-count');

      // 更新参考图显示
      function updateReferenceImages(){
        const refConns = state.referenceConnections.filter(c => c.to === id);
        if(refConns.length === 0){
          referenceSection.style.display = 'none';
          return;
        }
        
        referenceSection.style.display = 'block';
        referenceCount.textContent = refConns.length;
        referenceGrid.innerHTML = '';
        
        refConns.forEach(conn => {
          const sourceNode = state.nodes.find(n => n.id === conn.from);
          if(!sourceNode) return;
          
          // 根据节点类型获取图片URL
          let imgUrl = null;
          let imgLabel = '参考图';
          if(sourceNode.type === 'image' && (sourceNode.data.url || sourceNode.data.preview)){
            imgUrl = sourceNode.data.url || sourceNode.data.preview;
          } else if((sourceNode.type === 'character' || sourceNode.type === 'location' || sourceNode.type === 'props') && sourceNode.data.reference_image){
            imgUrl = sourceNode.data.reference_image;
            const typeLabels = { character: '角色', location: '场景', props: '道具' };
            imgLabel = `${typeLabels[sourceNode.type]}: ${sourceNode.data.name || ''}`;
          }
          
          if(imgUrl){
            const item = document.createElement('div');
            item.className = 'reference-image-item';
            const index = refConns.indexOf(conn) + 2;
            item.innerHTML = `
              <img src="${imgUrl}" alt="${imgLabel}" title="${imgLabel}" />
              <span class="reference-image-label">图${index}</span>
              <button class="reference-image-remove" data-conn-id="${conn.id}">×</button>
            `;
            
            const imgEl = item.querySelector('img');
            const removeBtn = item.querySelector('.reference-image-remove');
            
            // 删除参考连接（先绑定删除按钮事件，优先级更高）
            removeBtn.addEventListener('click', (e) => {
              e.preventDefault();
              e.stopPropagation();
              const connId = parseInt(e.target.dataset.connId);
              const idx = state.referenceConnections.findIndex(c => c.id === connId);
              if(idx !== -1){
                state.referenceConnections.splice(idx, 1);
                renderReferenceConnections();
                updateReferenceImages();
                try{ autoSaveWorkflow(); } catch(err){}
              }
            });
            
            // 点击图片预览（使用 mousedown 而不是 click，避免与删除按钮冲突）
            imgEl.addEventListener('mousedown', (e) => {
              // 检查是否点击的是删除按钮区域
              if(e.target === removeBtn) return;
              e.stopPropagation();
            });
            
            imgEl.addEventListener('click', (e) => {
              // 检查是否点击的是删除按钮区域
              if(e.target === removeBtn) return;
              e.stopPropagation();
              if(window.imageModal){
                window.imageModalImg.src = imgUrl;
                window.imageModalTitle.textContent = sourceNode.title || '参考图';
                window.imageModal.classList.add('show');
                window.imageModal.setAttribute('aria-hidden', 'false');
              }
            });
            
            referenceGrid.appendChild(item);
          }
        });
      }

      // 参考端口接收连接
      referencePort.addEventListener('mouseup', (e) => {
        if(state.connecting && state.connecting.fromId !== id){
          const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
          const allowedTypes = ['image', 'character', 'location', 'props'];
          if(fromNode && allowedTypes.includes(fromNode.type)){
            // 检查是否已存在连接
            const exists = state.referenceConnections.some(c => c.from === state.connecting.fromId && c.to === id);
            if(!exists){
              // 检查循环引用（仅对图片节点需要检查）
              let isCircular = false;
              if(fromNode.type === 'image'){
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
                isCircular = hasCircularReference(state.connecting.fromId, id);
              }
              
              if(isCircular){
                showToast('不能创建循环参考', 'error');
              } else {
                // 检查参考图数量限制
                const currentRefCount = state.referenceConnections.filter(c => c.to === id).length;
                const maxRefs = node.data.model === 'gemini-3-pro-image-preview' ? 13 : 5;
                if(currentRefCount >= maxRefs){
                  showToast(`最多支持${maxRefs}张参考图`, 'error');
                } else {
                  state.referenceConnections.push({
                    id: state.nextReferenceConnId++,
                    from: state.connecting.fromId,
                    to: id
                  });
                  renderReferenceConnections();
                  updateReferenceImages();
                  try{ autoSaveWorkflow(); } catch(e){}
                }
              }
            }
          }
        }
      });

      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });

      el.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.stopPropagation();
        setSelected(id);
        bringNodeToFront(id);
      });

      headerEl.addEventListener('mousedown', (e) => {
        if(e.target.classList.contains('port')) return;
        e.preventDefault();
        e.stopPropagation();
        setSelected(id);
        bringNodeToFront(id);
        initNodeDrag(id, e.clientX, e.clientY);
      });

      inputPort.addEventListener('mouseup', (e) => {
        if(state.connecting && state.connecting.fromId !== id){
          const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
          if(fromNode && fromNode.type === 'shot_frame'){
            const exists = state.connections.some(c => c.from === state.connecting.fromId && c.to === id);
            if(!exists){
              state.connections.push({
                id: state.nextConnId++,
                from: state.connecting.fromId,
                to: id
              });
              renderConnections();
              renderImageConnections();
              renderFirstFrameConnections();
              renderVideoConnections();
              
              // 更新分镜节点的预览图和选择菜单
              if(fromNode.updatePreview){
                fromNode.updatePreview();
              }
              
              try{ autoSaveWorkflow(); } catch(e){}
            }
          }
        }
      });

      outputPort.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
      });

      const imageFileEl = el.querySelector('.image-file');
      const imagePreviewRow = el.querySelector('.image-preview-row');
      const imagePreviewImg = el.querySelector('.image-preview');
      const imageClearBtn = el.querySelector('.image-clear');
      const promptEl = el.querySelector('.image-prompt');
      const promptExpandBtn = el.querySelector('.image-prompt-expand-btn');
      const ratioEl = el.querySelector('.image-ratio');
      const modelEl = el.querySelector('.image-model');
      const editBtn = el.querySelector('.image-edit-btn');
      const downloadBtn = el.querySelector('.image-download-icon-btn');
      const coloringBtn = el.querySelector('.image-coloring-btn');
      const statusEl = el.querySelector('.image-edit-status');
      const drawCountLabel = el.querySelector('.image-draw-count-label');
      const genCaret = el.querySelector('.gen-btn-caret');
      const genMenu = el.querySelector('.gen-menu');
      const confirmFieldEl = el.querySelector('.image-confirm-field');
      const confirmShotBtn = el.querySelector('.image-confirm-shot-btn');

      if(ratioEl) ratioEl.value = node.data.ratio;

      // 检查是否连接到分镜节点，显示/隐藏确认按钮
      function updateConfirmButtonVisibility(){
        const connectedShotFrameNode = state.connections
          .filter(c => c.to === id)
          .map(c => state.nodes.find(n => n.id === c.from))
          .find(n => n && n.type === 'shot_frame');
        
        if(connectedShotFrameNode && node.data.url){
          confirmFieldEl.style.display = 'block';
        } else {
          confirmFieldEl.style.display = 'none';
        }
      }

      // 涂色编辑按钮
      if(coloringBtn){
        coloringBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          if(!node.data.url && !node.data.preview){
            showToast('请先上传或生成图片', 'error');
            return;
          }
          const imageUrl = node.data.url || node.data.preview;
          
          if(window.imageColoringEditor && window.imageColoringEditor.open){
            window.imageColoringEditor.open(imageUrl, id, async (result) => {
              try {
                coloringBtn.disabled = true;
                statusEl.style.display = 'block';
                statusEl.style.color = '#666';
                statusEl.textContent = '正在上传涂色图片...';
                
                const coloredImageBlob = await fetch(result.coloredImage).then(r => r.blob());
                const uploadFormData = new FormData();
                uploadFormData.append('file', coloredImageBlob, 'colored_image.png');
                
                const uploadRes = await fetch('/api/video-workflow/upload', {
                  method: 'POST',
                  headers: {
                    'Authorization': getAuthToken ? getAuthToken() : '',
                    'X-User-Id': getUserId ? getUserId() : localStorage.getItem('user_id') || ''
                  },
                  body: uploadFormData
                });
                
                if(!uploadRes.ok) throw new Error('上传涂色图片失败');
                const uploadData = await uploadRes.json();
                if(uploadData.code !== 0 || !uploadData.data || !uploadData.data.url){
                  throw new Error(uploadData.message || '上传失败');
                }
                const coloredImageUrl = uploadData.data.url;
                
                node.data.url = coloredImageUrl;
                node.data.preview = coloredImageUrl;
                imagePreviewImg.src = coloredImageUrl;
                imagePreviewRow.style.display = 'block';
                
                statusEl.style.color = '#22c55e';
                statusEl.textContent = '涂色完成！';
                showToast('涂色完成！', 'success');
                
                try{ autoSaveWorkflow(); } catch(e){}
                renderMinimap();
              } catch(err){
                console.error('涂色编辑失败:', err);
                statusEl.style.color = '#dc2626';
                statusEl.textContent = '涂色失败';
                showToast('涂色失败: ' + err.message, 'error');
              } finally {
                coloringBtn.disabled = false;
              }
            });
          } else {
            showToast('涂色编辑器未加载', 'error');
          }
        });
      }

      // 确认分镜图按钮
      confirmShotBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const connectedShotFrameNode = state.connections
          .filter(c => c.to === id)
          .map(c => state.nodes.find(n => n.id === c.from))
          .find(n => n && n.type === 'shot_frame');
        
        if(connectedShotFrameNode && node.data.url){
          connectedShotFrameNode.data.previewImageUrl = node.data.url;
          if(connectedShotFrameNode.updatePreview){
            connectedShotFrameNode.updatePreview();
          }
          showToast('已设置为视频首帧', 'success');
          try{ autoSaveWorkflow(); } catch(e){}
        }
      });

      // 初始化时检查确认按钮可见性
      updateConfirmButtonVisibility();

      function updateDrawCountLabel(){
        drawCountLabel.textContent = `抽卡次数：X${node.data.drawCount}`;
      }
      updateDrawCountLabel();

      genCaret.addEventListener('click', (e) => {
        e.stopPropagation();
        genMenu.classList.toggle('show');
      });

      const genItems = genMenu.querySelectorAll('.gen-item');
      for(const item of genItems){
        item.addEventListener('click', (e) => {
          e.stopPropagation();
          const count = Number(item.dataset.count || '1');
          node.data.drawCount = count;
          updateDrawCountLabel();
          genMenu.classList.remove('show');
        });
      }

      imagePreviewImg.addEventListener('click', (e) => {
        e.stopPropagation();
        const src = node.data.url ? proxyImageUrl(node.data.url) : (imagePreviewImg.getAttribute('src') || '');
        if(!src) return;
        openImageModal(src, '图片预览');
      });

      promptEl.addEventListener('input', () => {
        node.data.prompt = promptEl.value;
      });

      // 编辑提示词放大按钮
      promptExpandBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        showPromptExpandModal(promptEl, '编辑提示词', (newValue) => {
          node.data.prompt = newValue;
        });
      });

      ratioEl.addEventListener('change', () => {
        node.data.ratio = ratioEl.value;
      });
      modelEl.addEventListener('change', () => {
        node.data.model = modelEl.value;
      });

      imageFileEl.addEventListener('change', async () => {
        const file = imageFileEl.files && imageFileEl.files[0];
        if(!file) return;
        node.data.file = file;
        
        const localPreview = await readFileAsDataUrl(file);
        imagePreviewImg.src = localPreview;
        imagePreviewRow.style.display = 'flex';
        
        const uploadedUrl = await uploadFile(file);
        if(uploadedUrl){
          node.data.url = uploadedUrl;
          node.data.name = file.name;
          node.data.preview = uploadedUrl;
          imagePreviewImg.src = proxyImageUrl(uploadedUrl);
          showToast('图片上传成功', 'success');
          try{ autoSaveWorkflow(); } catch(e){}
        } else {
          imagePreviewRow.style.display = 'none';
          imagePreviewImg.removeAttribute('src');
        }
        imageFileEl.value = '';
      });

      imageClearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        node.data.file = null;
        node.data.url = '';
        node.data.name = '';
        node.data.preview = '';
        imagePreviewRow.style.display = 'none';
        imagePreviewImg.removeAttribute('src');
      });

      editBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if(!node.data.url && !node.data.file){
          statusEl.style.display = 'block';
          statusEl.style.color = '#dc2626';
          statusEl.textContent = '请先上传图片';
          return;
        }
        
        // 检查是否有相机参数修改
        const hasCameraModifications = node.data.camera && node.data.camera.modified && 
          (node.data.camera.modified.yaw || node.data.camera.modified.dolly || node.data.camera.modified.pitch);
        
        if(!node.data.prompt && !hasCameraModifications){
          statusEl.style.display = 'block';
          statusEl.style.color = '#dc2626';
          statusEl.textContent = '请先输入编辑提示词或调整相机参数';
          return;
        }

        editBtn.disabled = true;
        statusEl.style.display = 'block';
        statusEl.style.color = '';
        statusEl.textContent = '正在提交任务...';

        try{
          let submitData = node.data.file;
          if(!submitData && node.data.url){
            submitData = node.data.url;
          }

          let finalPrompt = node.data.prompt || '';
          
          // 添加相机视角描述
          if(node.data.camera && typeof convertCameraToPrompt === 'function'){
            const cameraDesc = convertCameraToPrompt(node.data.camera);
            if(cameraDesc){
              finalPrompt = `${finalPrompt}\n\n视角描述：${cameraDesc}`;
            }
          }
          
          if(state.style && state.style.name){
            finalPrompt = `${finalPrompt}\n\n图片风格：${state.style.name}`;
          }

          // 收集参考图URL和描述后缀
          // 注意：原图占据图1，参考图从图2开始编号
          const referenceImageUrls = [];
          const promptSuffix = [];
          let refImageIndex = 2;
          const referenceConns = state.referenceConnections.filter(c => c.to === node.id);
          for(const conn of referenceConns){
            const refNode = state.nodes.find(n => n.id === conn.from);
            if(!refNode || !refNode.data) continue;
            if(refNode.type === 'image' && refNode.data.url){
              referenceImageUrls.push(refNode.data.url);
              refImageIndex++;
            } else if(refNode.type === 'character' && refNode.data.reference_image){
              referenceImageUrls.push(refNode.data.reference_image);
              promptSuffix.push(`图${refImageIndex}是${refNode.data.name || '角色'}`);
              refImageIndex++;
            } else if(refNode.type === 'location' && refNode.data.reference_image){
              referenceImageUrls.push(refNode.data.reference_image);
              promptSuffix.push(`图${refImageIndex}是${refNode.data.name || '场景'}`);
              refImageIndex++;
            } else if(refNode.type === 'props' && refNode.data.reference_image){
              referenceImageUrls.push(refNode.data.reference_image);
              promptSuffix.push(`图${refImageIndex}是${refNode.data.name || '道具'}`);
              refImageIndex++;
            }
          }

          // 将参考图描述追加到提示词末尾
          if(promptSuffix.length > 0){
            finalPrompt = `${finalPrompt}\n\n${promptSuffix.join('，')}。`;
          }

          const desiredCount = Math.max(1, Number(node.data.drawCount) || 1);
          const submitRes = await generateEditedImage(submitData, finalPrompt, node.data.ratio, node.data.model, desiredCount, referenceImageUrls);
          statusEl.textContent = '任务已提交，正在生成图片...';
          node.data.projectIds = submitRes.projectIds;

          // 立即创建对应数量的图片节点并绑定 project_id
          const createdImageNodeIds = [];
          const projectIds = submitRes.projectIds || [];
          const imageCount = projectIds.length;

          for(let i = 0; i < imageCount; i++){
            const offsetY = i * 280;
            const newNodeId = createImageNode({ 
              x: node.x + 380, 
              y: node.y + offsetY 
            });
            const newNode = state.nodes.find(n => n.id === newNodeId);
            if(newNode){
              newNode.data.name = imageCount > 1 ? `编辑结果${i + 1}` : '编辑结果';
              newNode.data.project_id = projectIds[i] || projectIds[0];
              createdImageNodeIds.push(newNodeId);
              
              // 创建从原节点到新节点的连接
              const connectionId = `conn_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
              state.connections.push({
                id: connectionId,
                from: node.id,
                to: newNodeId
              });
            }
          }

          // 立即渲染连接线
          renderConnections();
          renderImageConnections();
          renderFirstFrameConnections();
          renderVideoConnections();
          renderReferenceConnections();

          try{ autoSaveWorkflow(); } catch(e){}
          renderMinimap();

          pollVideoStatus(
            submitRes.projectIds,
            (progressText) => { statusEl.textContent = progressText; },
            (statusResult) => {
              // 从 tasks 数组中提取结果
              let imageUrls = [];
              if(statusResult.tasks && Array.isArray(statusResult.tasks)){
                imageUrls = statusResult.tasks
                  .filter(task => task.status === 'SUCCESS' && task.result)
                  .map(task => normalizeVideoUrl(task.result))
                  .filter(Boolean);
              } else {
                const rawResults = extractResultsArray(statusResult);
                imageUrls = Array.isArray(rawResults)
                  ? rawResults.map(normalizeVideoUrl).filter(Boolean)
                  : [];
              }

              if(imageUrls.length === 0){
                statusEl.style.color = '#dc2626';
                statusEl.textContent = '生成成功，但未获取到图片地址';
                editBtn.disabled = false;
                showToast('生成成功但未返回图片地址', 'error');
                return;
              }

              statusEl.style.color = '#16a34a';
              statusEl.textContent = `生成完成！共${imageUrls.length}张图片`;
              editBtn.disabled = false;

              // 更新已创建的图片节点
              imageUrls.forEach((imageUrl, index) => {
                const nodeId = createdImageNodeIds[index];
                if(!nodeId) return;
                
                const imageNode = state.nodes.find(n => n.id === nodeId);
                if(imageNode){
                  const normalizedUrl = normalizeImageUrl(imageUrl);
                  imageNode.data.url = normalizedUrl;
                  imageNode.data.preview = normalizedUrl;
                  
                  const nodeEl = canvasEl.querySelector(`.node[data-node-id="${nodeId}"]`);
                  if(nodeEl){
                    const imgEl = nodeEl.querySelector('.image-preview');
                    const rowEl = nodeEl.querySelector('.image-preview-row');
                    if(imgEl) imgEl.src = proxyImageUrl(imageUrl);
                    if(rowEl) rowEl.style.display = 'flex';
                  }
                }
              });

              try{ autoSaveWorkflow(); } catch(e){}
              renderMinimap();
              showToast('图片编辑成功！', 'success');
              
              // 刷新用户算力显示
              if(typeof fetchComputingPower === 'function'){
                fetchComputingPower();
              }
            },
            (errMsg) => {
              statusEl.style.color = '#dc2626';
              statusEl.textContent = errMsg;
              editBtn.disabled = false;
              showToast(errMsg || '图片编辑失败', 'error');
            }
          );
        } catch(err){
          statusEl.style.color = '#dc2626';
          statusEl.textContent = err.message || '提交失败';
          editBtn.disabled = false;
          showToast('提交失败: ' + (err.message || ''), 'error');
        }
      });

      downloadBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if(!node.data.url && !node.data.preview){
          showToast('没有可下载的图片', 'error');
          return;
        }
        const downloadUrl = node.data.url || node.data.preview;
        const fileName = node.data.name || 'image.png';
        
        // 图片直接下载，不需要后端代理
        // 如果是跨域图片，使用fetch+blob方式下载
        try {
          if(downloadUrl.startsWith('data:') || downloadUrl.startsWith('blob:') || isSameOriginUrl(downloadUrl)){
            // data URL、blob URL 或同源图片，直接下载
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = fileName;
            a.style.display = 'none';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
          } else {
            // 跨域图片，使用fetch+blob方式下载
            const response = await fetch(proxyImageUrl(downloadUrl));
            const blob = await response.blob();
            const blobUrl = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = blobUrl;
            a.download = fileName;
            a.style.display = 'none';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(blobUrl);
          }
          showToast('开始下载图片', 'success');
        } catch(error) {
          console.error('下载图片失败:', error);
          showToast('下载图片失败', 'error');
        }
      });

      // 相机控制事件绑定
      const cameraYawSlider = el.querySelector('.image-camera-yaw-slider');
      const cameraYawInput = el.querySelector('.image-camera-yaw');
      const cameraYawReset = el.querySelector('.image-camera-reset-yaw');
      const cameraDollySlider = el.querySelector('.image-camera-dolly-slider');
      const cameraDollyInput = el.querySelector('.image-camera-dolly');
      const cameraDollyReset = el.querySelector('.image-camera-reset-dolly');
      const cameraPitchSlider = el.querySelector('.image-camera-pitch-slider');
      const cameraPitchInput = el.querySelector('.image-camera-pitch');
      const cameraPitchReset = el.querySelector('.image-camera-reset-pitch');
      const cameraCanvas = el.querySelector('.image-camera-canvas');
      const cameraControlToggleBtn = el.querySelector('.camera-control-toggle-btn');
      const cameraControlContent = el.querySelector('.camera-control-content');
      
      // 初始化相机数据（强制重置为默认值）
      node.data.camera = { 
        yaw: 0, 
        dolly: 0, 
        pitch: 0,
        modified: { yaw: false, dolly: false, pitch: false }
      };
      
      // 从数据恢复相机参数
      if(cameraYawSlider) cameraYawSlider.value = node.data.camera.yaw ?? 0;
      if(cameraYawInput) cameraYawInput.value = node.data.camera.yaw ?? 0;
      if(cameraDollySlider) cameraDollySlider.value = node.data.camera.dolly ?? 0;
      if(cameraDollyInput) cameraDollyInput.value = node.data.camera.dolly ?? 0;
      if(cameraPitchSlider) cameraPitchSlider.value = node.data.camera.pitch ?? 0;
      if(cameraPitchInput) cameraPitchInput.value = node.data.camera.pitch ?? 0;
      
      function updateImageCameraPreview(){
        if(cameraCanvas && typeof window.updateCameraPreview === 'function'){
          window.updateCameraPreview(cameraCanvas, node.data.camera);
        }
      }
      
      // 相机控制折叠切换
      if(cameraControlToggleBtn && cameraControlContent){
        cameraControlToggleBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const isHidden = cameraControlContent.style.display === 'none';
          if(isHidden){
            cameraControlContent.style.display = 'flex';
            cameraControlToggleBtn.textContent = '收起';
            // 展开时更新预览
            updateImageCameraPreview();
          } else {
            cameraControlContent.style.display = 'none';
            cameraControlToggleBtn.textContent = '展开';
          }
        });
      }

      // Yaw 滑块和输入框
      if(cameraYawSlider){
        cameraYawSlider.addEventListener('input', (e) => {
          const value = parseFloat(e.target.value);
          if(!node.data.camera) node.data.camera = { yaw: 0, dolly: 0, pitch: 0, modified: { yaw: false, dolly: false, pitch: false } };
          if(!node.data.camera.modified) node.data.camera.modified = { yaw: false, dolly: false, pitch: false };
          node.data.camera.yaw = value;
          node.data.camera.modified.yaw = true;
          if(cameraYawInput) cameraYawInput.value = value;
          updateImageCameraPreview();
        });
      }
      if(cameraYawInput){
        cameraYawInput.addEventListener('input', (e) => {
          const value = parseFloat(e.target.value);
          if(!node.data.camera) node.data.camera = { yaw: 0, dolly: 0, pitch: 0, modified: { yaw: false, dolly: false, pitch: false } };
          if(!node.data.camera.modified) node.data.camera.modified = { yaw: false, dolly: false, pitch: false };
          node.data.camera.yaw = value;
          node.data.camera.modified.yaw = true;
          if(cameraYawSlider) cameraYawSlider.value = value;
          updateImageCameraPreview();
        });
      }
      if(cameraYawReset){
        cameraYawReset.addEventListener('click', (e) => {
          e.stopPropagation();
          node.data.camera.yaw = 0;
          node.data.camera.modified.yaw = false;
          if(cameraYawSlider) cameraYawSlider.value = 0;
          if(cameraYawInput) cameraYawInput.value = 0;
          updateImageCameraPreview();
        });
      }
      
      // Dolly 滑块和输入框
      if(cameraDollySlider){
        cameraDollySlider.addEventListener('input', (e) => {
          const value = parseFloat(e.target.value);
          if(!node.data.camera) node.data.camera = { yaw: 0, dolly: 0, pitch: 0, modified: { yaw: false, dolly: false, pitch: false } };
          if(!node.data.camera.modified) node.data.camera.modified = { yaw: false, dolly: false, pitch: false };
          node.data.camera.dolly = value;
          node.data.camera.modified.dolly = true;
          if(cameraDollyInput) cameraDollyInput.value = value;
          updateImageCameraPreview();
        });
      }
      if(cameraDollyInput){
        cameraDollyInput.addEventListener('input', (e) => {
          const value = parseFloat(e.target.value);
          if(!node.data.camera) node.data.camera = { yaw: 0, dolly: 0, pitch: 0, modified: { yaw: false, dolly: false, pitch: false } };
          if(!node.data.camera.modified) node.data.camera.modified = { yaw: false, dolly: false, pitch: false };
          node.data.camera.dolly = value;
          node.data.camera.modified.dolly = true;
          if(cameraDollySlider) cameraDollySlider.value = value;
          updateImageCameraPreview();
        });
      }
      if(cameraDollyReset){
        cameraDollyReset.addEventListener('click', (e) => {
          e.stopPropagation();
          node.data.camera.dolly = 0;
          node.data.camera.modified.dolly = false;
          if(cameraDollySlider) cameraDollySlider.value = 0;
          if(cameraDollyInput) cameraDollyInput.value = 0;
          updateImageCameraPreview();
        });
      }
      
      // Pitch 滑块和输入框
      if(cameraPitchSlider){
        cameraPitchSlider.addEventListener('input', (e) => {
          const value = parseFloat(e.target.value);
          if(!node.data.camera) node.data.camera = { yaw: 0, dolly: 0, pitch: 0, modified: { yaw: false, dolly: false, pitch: false } };
          if(!node.data.camera.modified) node.data.camera.modified = { yaw: false, dolly: false, pitch: false };
          node.data.camera.pitch = value;
          node.data.camera.modified.pitch = true;
          if(cameraPitchInput) cameraPitchInput.value = value;
          updateImageCameraPreview();
        });
      }
      if(cameraPitchInput){
        cameraPitchInput.addEventListener('input', (e) => {
          const value = parseFloat(e.target.value);
          if(!node.data.camera) node.data.camera = { yaw: 0, dolly: 0, pitch: 0, modified: { yaw: false, dolly: false, pitch: false } };
          if(!node.data.camera.modified) node.data.camera.modified = { yaw: false, dolly: false, pitch: false };
          node.data.camera.pitch = value;
          node.data.camera.modified.pitch = true;
          if(cameraPitchSlider) cameraPitchSlider.value = value;
          updateImageCameraPreview();
        });
      }
      if(cameraPitchReset){
        cameraPitchReset.addEventListener('click', (e) => {
          e.stopPropagation();
          node.data.camera.pitch = 0;
          node.data.camera.modified.pitch = false;
          if(cameraPitchSlider) cameraPitchSlider.value = 0;
          if(cameraPitchInput) cameraPitchInput.value = 0;
          updateImageCameraPreview();
        });
      }
      
      // 初始化预览
      updateImageCameraPreview();

      // 暴露更新函数给节点对象
      node.updateReferenceImages = updateReferenceImages;
      
      // 初始化参考图显示
      updateReferenceImages();

      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);
      setSelected(id);
      return id;
    }

    // 剧本节点
    function createScriptNode(opts){
      const id = state.nextNodeId++;
      const scriptId = (opts && typeof opts.scriptId === 'number') ? opts.scriptId : state.nextScriptId++;
      if(opts && typeof opts.scriptId === 'number' && opts.scriptId >= state.nextScriptId) {
        state.nextScriptId = opts.scriptId + 1;
      }
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = opts && typeof opts.y === 'number' ? opts.y : viewportPos.y;
      const node = {
        id,
        type: 'script',
        title: `剧本 ${scriptId}`,
        x,
        y,
        data: {
          scriptId,
          file: null,
          url: '',
          name: '',
          scriptContent: '',
          parsedData: null,
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';

      el.innerHTML = `
        <div class="port output" title="输出（拆分为分镜组）"></div>
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M9 5H7C5.89543 5 5 5.89543 5 7V19C5 20.1046 5.89543 21 7 21H17C18.1046 21 19 20.1046 19 19V7C19 5.89543 18.1046 5 17 5H15"/><rect x="9" y="3" width="6" height="4" rx="1"/></svg>剧本 ${scriptId}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field field-always-visible script-info-field" style="display:none;">
            <div class="gen-meta script-name"></div>
            <div class="gen-meta script-length"></div>
            <span class="script-char-count" style="color: #666; font-size: 12px;">0/30000</span>
          </div>
          <div class="field field-collapsible">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <div class="label" style="margin: 0;">输入剧本内容</div>
              <button class="mini-btn script-expand-btn" type="button" style="font-size: 11px; padding: 4px 8px;" title="放大编辑">⤢</button>
            </div>
            <textarea class="script-textarea" rows="6" maxlength="30000" placeholder="在此输入剧本内容，或上传文件（最多30000字符）"></textarea>
          </div>
          <div class="field field-collapsible">
            <div class="label">或上传剧本文件</div>
            <input class="script-file" type="file" accept=".txt,.md" />
          </div>
          <div class="field field-collapsible">
            <div class="label">或从已保存剧本中选择</div>
            <button class="gen-btn script-load-btn" type="button" style="border-radius: 8px; width: 100%; background: #10b981; padding: 8px;">加载剧本</button>
          </div>
          <div class="field field-collapsible">
            <div class="label">镜头组最长时长</div>
            <select class="script-duration-select" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
              <option value="5">5秒</option>
              <option value="8">8秒</option>
              <option value="10">10秒</option>
              <option value="15" selected>15秒</option>
            </select>
            <div class="gen-meta" style="margin-top: 4px; font-size: 11px; color: #666;">每个镜头组内所有镜头的总时长不超过此值</div>
          </div>
          <div class="field field-collapsible">
            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
              <input type="checkbox" class="script-force-medium-shot" style="cursor: pointer;" checked />
              <span>对话禁止全景</span>
            </label>
            <div class="gen-meta" style="margin-top: 4px; font-size: 11px; color: #666;">对话镜头自动选择近景或中景，避免sora全景对话效果不佳</div>
          </div>
          <div class="field field-collapsible">
            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
              <input type="checkbox" class="script-no-bg-music" style="cursor: pointer;" checked />
              <span>不生成背景音乐</span>
            </label>
            <div class="gen-meta" style="margin-top: 4px; font-size: 11px; color: #666;">方便后期调音</div>
          </div>
          <div class="field field-collapsible">
            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
              <input type="checkbox" class="script-split-multi-dialogue" style="cursor: pointer;" />
              <span>拆分多人对话镜头</span>
            </label>
            <div class="gen-meta" style="margin-top: 4px; font-size: 11px; color: #666;">将多人对话镜头拆分为单人对话镜头，并注意画面不越轴</div>
          </div>
          <div class="field field-collapsible">
            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
              <input type="checkbox" class="script-narration-as-dialogue" style="cursor: pointer;" />
              <span>解说剧（仅旁白说话）</span>
            </label>
            <div class="gen-meta" style="margin-top: 4px; font-size: 11px; color: #666;">将有角色对话的剧本转换为仅旁白解说的剧本格式</div>
          </div>
          <div class="field field-always-visible script-warning-field" style="display:none;">
            <div class="gen-meta" style="color: #f59e0b;">文件内容超过30000字符，已自动截取前30000字符。建议将剧本分段处理。</div>
          </div>
          <div class="field field-collapsible">
            <button class="gen-btn gen-btn-white script-split-btn" type="button" style="border-radius: 10px; width: 100%;" disabled>拆分镜组</button>
            <div class="gen-meta script-status" style="display:none; margin-top: 8px;"></div>
          </div>
          <div class="field field-collapsible">
            <div class="label">宫格生图模型</div>
            <select class="script-grid-model" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
              <option value="auto" selected>智能模式 (根据分镜数自动选择)</option>
              <option value="gemini-2.5-pro-image-preview">标准版 (4宫格, 2算力/张)</option>
              <option value="gemini-3-pro-4grid">加强版 (4宫格, 6算力/张)</option>
              <option value="gemini-3-pro-image-preview">加强版 (9宫格, 6算力/张)</option>
            </select>
          </div>
          <div class="field field-collapsible">
            <button class="gen-btn gen-btn-green script-split-grid-btn" type="button" style="border-radius: 10px; width: 100%;">拆分分镜组 + 宫格生图</button>
            <div class="gen-meta script-grid-status" style="display:none; margin-top: 8px;"></div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const outputPort = el.querySelector('.port.output');
      const textareaEl = el.querySelector('.script-textarea');
      const fileEl = el.querySelector('.script-file');
      const loadBtn = el.querySelector('.script-load-btn');
      const expandBtn = el.querySelector('.script-expand-btn');
      const durationSelectEl = el.querySelector('.script-duration-select');
      const forceMediumShotEl = el.querySelector('.script-force-medium-shot');
      const noBgMusicEl = el.querySelector('.script-no-bg-music');
      const splitMultiDialogueEl = el.querySelector('.script-split-multi-dialogue');
      const narrationAsDialogueEl = el.querySelector('.script-narration-as-dialogue');
      const infoField = el.querySelector('.script-info-field');
      const nameEl = el.querySelector('.script-name');
      const lengthEl = el.querySelector('.script-length');
      const splitBtn = el.querySelector('.script-split-btn');
      const statusEl = el.querySelector('.script-status');
      const charCountEl = el.querySelector('.script-char-count');
      const warningField = el.querySelector('.script-warning-field');
      const gridModelSelect = el.querySelector('.script-grid-model');
      const splitGridBtn = el.querySelector('.script-split-grid-btn');
      const gridStatusEl = el.querySelector('.script-grid-status');
      
      // 初始化节点数据中的最大时长和选项
      node.data.maxGroupDuration = 15;
      node.data.forceMediumShot = true;
      node.data.noBgMusic = true;
      node.data.splitMultiDialogue = false;
      node.data.narrationAsDialogue = false;
      node.data.gridModel = 'gemini-2.5-pro-image-preview';

      // 更新字符计数器
      function updateCharCount(length) {
        charCountEl.textContent = `${length}/30000`;
        if(length > 28500) {
          charCountEl.style.color = '#dc2626';
        } else if(length > 25500) {
          charCountEl.style.color = '#f59e0b';
        } else {
          charCountEl.style.color = '#666';
        }
      }

      // 更新剧本内容和按钮状态
      function updateScriptContent(content, source) {
        node.data.scriptContent = content;
        updateCharCount(content.length);
        
        if(content && content.trim().length > 0) {
          splitBtn.disabled = false;
          nameEl.textContent = source;
          lengthEl.textContent = `长度: ${content.length} 字符`;
          infoField.style.display = 'block';
        } else {
          splitBtn.disabled = true;
          infoField.style.display = 'none';
        }
      }

      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });

      el.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        setSelected(id);
        bringNodeToFront(id);
      });

      headerEl.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        // 如果节点不在选中列表中，才调用setSelected（这会清空其他选中）
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        bringNodeToFront(id);
        initNodeDrag(id, e.clientX, e.clientY);
      });

      outputPort.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
      });

      // 时长选择监听
      durationSelectEl.addEventListener('change', () => {
        node.data.maxGroupDuration = parseInt(durationSelectEl.value);
      });

      // 对话强制中景选项监听
      forceMediumShotEl.addEventListener('change', () => {
        node.data.forceMediumShot = forceMediumShotEl.checked;
      });

      // 不生成背景音乐选项监听
      noBgMusicEl.addEventListener('change', () => {
        node.data.noBgMusic = noBgMusicEl.checked;
      });

      // 拆分多人对话选项监听
      splitMultiDialogueEl.addEventListener('change', () => {
        node.data.splitMultiDialogue = splitMultiDialogueEl.checked;
      });

      // 解说剧（仅旁白说话）选项监听
      narrationAsDialogueEl.addEventListener('change', () => {
        node.data.narrationAsDialogue = narrationAsDialogueEl.checked;
      });

      // 宫格模型选择监听
      gridModelSelect.addEventListener('change', () => {
        node.data.gridModel = gridModelSelect.value;
      });

      // 文本框输入监听
      textareaEl.addEventListener('input', () => {
        const content = textareaEl.value;
        updateScriptContent(content, '来源: 文本输入');
      });

      // 加载剧本按钮监听
      loadBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await showScriptSelectionModal(node, textareaEl, updateScriptContent, warningField);
      });

      // 放大按钮监听
      expandBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        showScriptExpandModal(textareaEl, updateScriptContent, charCountEl);
      });

      // 文件上传监听
      fileEl.addEventListener('change', async () => {
        const file = fileEl.files && fileEl.files[0];
        if(!file) return;
        
        try {
          let content = await file.text();
          node.data.file = file;
          node.data.name = file.name;
          
          // 检查是否超过30000字符
          const originalLength = content.length;
          const isTruncated = originalLength > 30000;
          if(isTruncated) {
            content = content.substring(0, 30000);
            warningField.style.display = 'block';
            showToast(`文件内容已截取至30000字符（原${originalLength}字符）`, 'warning');
          } else {
            warningField.style.display = 'none';
            showToast('剧本文件加载成功', 'success');
          }
          
          // 更新文本框内容
          textareaEl.value = content;
          updateScriptContent(content, `来源: ${file.name}${isTruncated ? ' (已截取)' : ''}`);
          
          fileEl.value = '';
        } catch(error) {
          console.error('读取文件失败:', error);
          showToast('读取文件失败', 'error');
        }
      });

      splitBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        
        if(!node.data.scriptContent) {
          showToast('请先上传剧本文件', 'error');
          return;
        }

        // 检查是否已有分镜组节点
        const existingShotGroups = state.connections.filter(c => c.from === id);
        if(existingShotGroups.length > 0) {
          const hasShotGroupNode = existingShotGroups.some(conn => {
            const targetNode = state.nodes.find(n => n.id === conn.to);
            return targetNode && targetNode.type === 'shot_group';
          });
          
          if(hasShotGroupNode) {
            showToast('已有分镜组，请勿重复点击', 'warning');
            return;
          }
        }

        if(!state.defaultWorldId){
          const confirmed = window.confirm('尚未在左上角选择世界，无法自动匹配场景和角色。确认继续拆分分镜图吗？');
          if(!confirmed){
            return;
          }
        }

        splitBtn.disabled = true;
        statusEl.style.display = 'block';
        statusEl.style.color = '#666';
        statusEl.textContent = node.data.narrationAsDialogue ? '正在将剧本转换为解说剧格式，再解析分镜...' : '正在调用LLM解析剧本...';

        try {
          const response = await fetch('/api/parse-script', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': getAuthToken(),
              'X-User-Id': getUserId()
            },
            body: JSON.stringify({
              script_content: node.data.scriptContent,
              max_group_duration: node.data.maxGroupDuration || 15,
              world_id: state.defaultWorldId,
              force_medium_shot: node.data.forceMediumShot || false,
              no_bg_music: node.data.noBgMusic || false,
              split_multi_dialogue: node.data.splitMultiDialogue || false,
              narration_as_dialogue: node.data.narrationAsDialogue || false
            })
          });

          const result = await response.json();
          
          if(result.code === 0 && result.data) {
            node.data.parsedData = result.data;
            
            statusEl.style.color = '#16a34a';
            statusEl.textContent = `解析成功！共${result.data.shot_groups?.length || 0}个分镜组`;
            
            // 创建分镜组节点
            if(result.data.shot_groups && result.data.shot_groups.length > 0) {
              // 预先创建所有柱子（基于剧本中的所有分镜）
              const scriptId = id;
              const maxGroupDuration = result.data.max_group_duration || 15;
              
              result.data.shot_groups.forEach((shotGroup) => {
                if(shotGroup.shots && Array.isArray(shotGroup.shots)) {
                  shotGroup.shots.forEach((shot) => {
                    if(shot.shot_number) {
                      // 为每个分镜预创建柱子
                      createOrUpdatePillar(scriptId, shot.shot_number, shot.duration || maxGroupDuration);
                    }
                  });
                }
              });
              
              const createdShotGroupNodes = [];
              let cumulativeY = 0;
              result.data.shot_groups.forEach((shotGroup, index) => {
                const offsetX = 400;
                const shotCount = (shotGroup.shots && shotGroup.shots.length) || 1;
                const shotGroupNodeId = createShotGroupNode({
                  x: node.x + offsetX,
                  y: node.y + cumulativeY,
                  shotGroupData: shotGroup,
                  scriptData: result.data
                });
                cumulativeY += shotCount * 700;
                
                // 创建从剧本节点到分镜组节点的连线
                if(shotGroupNodeId) {
                  state.connections.push({
                    id: state.nextConnId++,
                    from: id,
                    to: shotGroupNodeId
                  });
                  createdShotGroupNodes.push(shotGroupNodeId);
                }
              });
              
              // 自动显示时间轴（即使还没有片段）
              state.timeline.visible = true;
              renderTimeline();
              
              renderConnections();
              renderImageConnections();
              renderFirstFrameConnections();
              renderVideoConnections();
              renderMinimap();
              try{ autoSaveWorkflow(); } catch(e){}
              
              // 自动为每个分镜组生成分镜
              statusEl.textContent = '正在自动生成分镜...';
              for(const shotGroupNodeId of createdShotGroupNodes) {
                const shotGroupNode = state.nodes.find(n => n.id === shotGroupNodeId);
                if(shotGroupNode) {
                  await generateShotFramesIndependentAsync(shotGroupNodeId, shotGroupNode);
                }
              }
              statusEl.style.color = '#16a34a';
              statusEl.textContent = `已完成：${createdShotGroupNodes.length}个分镜组，所有分镜已自动生成`;
            }
            
            showToast('剧本拆分成功！所有分镜已自动生成', 'success');
          } else {
            throw new Error(result.message || '解析失败');
          }
        } catch(error) {
          console.error('剧本解析失败:', error);
          statusEl.style.color = '#dc2626';
          statusEl.textContent = '解析失败: ' + (error.message || '未知错误');
          showToast('剧本解析失败', 'error');
        } finally {
          splitBtn.disabled = false;
        }
      });

      // 宫格生图按钮监听
      console.log('[宫格生图] 正在绑定事件监听器，按钮元素:', splitGridBtn);
      console.log('[宫格生图] 按钮是否禁用:', splitGridBtn ? splitGridBtn.disabled : 'N/A');
      
      if(!splitGridBtn) {
        console.error('[宫格生图] 错误：找不到宫格生图按钮元素！');
      }
      
      splitGridBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        console.log('[宫格生图] 按钮被点击');
        
        if(!node.data.scriptContent) {
          console.log('[宫格生图] 没有剧本内容');
          showToast('请先上传剧本文件', 'error');
          return;
        }

        // 检查是否已有分镜组节点
        const existingShotGroupConnections = state.connections.filter(c => c.from === id);
        const existingShotGroupNodes = existingShotGroupConnections
          .map(conn => state.nodes.find(n => n.id === conn.to))
          .filter(n => n && n.type === 'shot_group');
        
        console.log(`[宫格生图] 找到 ${existingShotGroupNodes.length} 个已存在的分镜组节点`);
        
        // 检查这些分镜组是否已有分镜节点
        if(existingShotGroupNodes.length > 0) {
          const shotGroupsWithFrames = existingShotGroupNodes.filter(shotGroupNode => {
            const shotFrameConnections = state.connections.filter(c => c.from === shotGroupNode.id);
            const hasShotFrames = shotFrameConnections.some(c => {
              const targetNode = state.nodes.find(n => n.id === c.to);
              return targetNode && targetNode.type === 'shot_frame';
            });
            return hasShotFrames;
          });
          
          console.log(`[宫格生图] 其中 ${shotGroupsWithFrames.length} 个分镜组有分镜节点`);
          
          if(shotGroupsWithFrames.length > 0) {
            showToast('已有分镜组和分镜节点，请勿重复点击', 'warning');
            return;
          }
          
          // 如果分镜组存在但没有分镜节点，直接使用现有分镜组生成分镜节点
          if(existingShotGroupNodes.length > 0) {
            console.log(`[宫格生图] 分镜组已存在但无分镜节点，将复用现有分镜组`);
            gridStatusEl.style.display = 'block';
            gridStatusEl.style.color = '#666';
            gridStatusEl.textContent = '正在生成分镜节点...';
            
            try {
              const allShotFrameNodes = [];
              
              for(const shotGroupNode of existingShotGroupNodes) {
                console.log(`[宫格生图] 处理分镜组 ${shotGroupNode.id}`);
                const shotFrameNodeIds = await generateShotFramesIndependentAsync(shotGroupNode.id, shotGroupNode);
                console.log(`[宫格生图] 分镜组 ${shotGroupNode.id} 返回的节点ID: ${shotFrameNodeIds}`);
                if(shotFrameNodeIds && shotFrameNodeIds.length > 0) {
                  const shotNodes = shotFrameNodeIds.map(nid => state.nodes.find(n => n.id === nid)).filter(Boolean);
                  console.log(`[宫格生图] 找到 ${shotNodes.length} 个有效的分镜节点`);
                  allShotFrameNodes.push(...shotNodes);
                }
              }
              
              console.log(`[宫格生图] 总共收集到 ${allShotFrameNodes.length} 个分镜节点`);
              if(allShotFrameNodes.length === 0) {
                throw new Error('未生成分镜节点');
              }
              
              // 收集参考图片URL（角色、场景、道具）
              gridStatusEl.textContent = '正在收集参考图片...';
              const { referenceImageUrls, promptSuffix } = await collectReferenceImagesForGrid(allShotFrameNodes);
              console.log(`[宫格生图] 收集到 ${referenceImageUrls.length} 张参考图片URL`);
              
              // 跳转到第四步：根据分镜数量决定宫格大小
              const shotCount = allShotFrameNodes.length;
              if(shotCount === 1) {
                gridStatusEl.style.color = '#f59e0b';
                gridStatusEl.textContent = '只有1个分镜，无需宫格生图';
                showToast('只有1个分镜，无需宫格生图', 'warning');
                return;
              }

              const gridModel = node.data.gridModel || 'auto';
              let gridSize, gridLayout, finalModel;
              
              // 如果参考图片超过5张，必须使用增强版模型（支持13张参考图）
              const forceEnhancedModel = referenceImageUrls.length > 5;
              if(forceEnhancedModel) {
                console.log(`[宫格生图] 参考图片数量(${referenceImageUrls.length})超过5张，强制使用增强版模型`);
              }
              
              if(gridModel === 'auto') {
                // 智能模式：根据分镜数量和参考图片数量自动选择
                if(shotCount <= 5 && !forceEnhancedModel) {
                  gridSize = 4;
                  gridLayout = '2x2';
                  finalModel = 'gemini-2.5-pro-image-preview';
                } else {
                  gridSize = 9;
                  gridLayout = '3x3';
                  finalModel = 'gemini-3-pro-image-preview';
                }
              } else if(gridModel === 'gemini-2.5-pro-image-preview' && !forceEnhancedModel) {
                // 标准版：固定4宫格（但如果参考图超过5张则强制升级）
                gridSize = 4;
                gridLayout = '2x2';
                finalModel = gridModel;
              } else if(gridModel === 'gemini-3-pro-4grid') {
                // 加强版4宫格：4宫格但使用加强版模型
                gridSize = 4;
                gridLayout = '2x2';
                finalModel = 'gemini-3-pro-image-preview';
              } else {
                // 加强版9宫格，或因参考图数量强制升级
                gridSize = 9;
                gridLayout = '3x3';
                finalModel = 'gemini-3-pro-image-preview';
              }
              
              // 限制参考图片数量（标准版最多5张，增强版最多13张）
              const maxRefImages = finalModel === 'gemini-3-pro-image-preview' ? 13 : 5;
              if(referenceImageUrls.length > maxRefImages) {
                console.warn(`[宫格生图] 参考图片数量 ${referenceImageUrls.length} 超过限制 ${maxRefImages}，将只使用前 ${maxRefImages} 张`);
                referenceImageUrls.splice(maxRefImages);
                promptSuffix.splice(maxRefImages);
              }
              
              node.data.gridModel = finalModel;

              const imagePower = finalModel === 'gemini-3-pro-image-preview' ? 6 : 2;
              const imageCount = Math.ceil(shotCount / gridSize);
              const totalPower = imageCount * imagePower;

              const refImageInfo = referenceImageUrls.length > 0 ? `\n参考图片：${referenceImageUrls.length}张` : '';
              const confirmMsg = `即将生成${imageCount}张${gridLayout}宫格图片\n` +
                `分镜数量：${shotCount}个\n` +
                `模型：${finalModel === 'gemini-3-pro-image-preview' ? '加强版' : '标准版'}${refImageInfo}\n` +
                `预计消耗算力：${totalPower}\n\n` +
                `确认生成吗？`;
              
              if(!window.confirm(confirmMsg)) {
                gridStatusEl.style.color = '#666';
                gridStatusEl.textContent = '已取消';
                return;
              }

              // 第五步：拼接提示词并调用API
              gridStatusEl.textContent = `正在生成${imageCount}张${gridLayout}宫格图片...`;
              
              const gridTasks = [];
              for(let i = 0; i < imageCount; i++) {
                const startIdx = i * gridSize;
                const endIdx = Math.min(startIdx + gridSize, shotCount);
                const batchNodes = allShotFrameNodes.slice(startIdx, endIdx);
                
                const shots = [];
                for(let idx = 0; idx < gridSize; idx++){
                  // 如果分镜数量不足填满宫格，用最后一个分镜的提示词填充
                  const nodeIndex = idx < batchNodes.length ? idx : batchNodes.length - 1;
                  const shotNode = batchNodes[nodeIndex];
                  shots.push({
                    shot_number: `Shot ${startIdx + idx + 1}`,
                    prompt_text: shotNode.data.imagePrompt || ''
                  });
                }
                
                const gridPrompt = JSON.stringify({
                  grid_layout: gridLayout,
                  grid_aspect_ratio: state.ratio || '16:9',
                  global_watermark: '',
                  style_guidance: "NO TEXT, NO TITLE, NO LABELS, clean grid lines only.",
                  shots: shots
                });
                
                gridTasks.push({
                  batchNodes,
                  gridPrompt,
                  startIdx
                });
              }

              // 构建参考图片说明后缀
              const refSuffixText = promptSuffix.length > 0 ? `\n\n${promptSuffix.join('，')}。` : '';
              
              const apiPromises = gridTasks.map(async (task) => {
                const form = new FormData();
                
                // 添加参考图片说明到提示词
                let finalGridPrompt = task.gridPrompt;
                if(refSuffixText) {
                  try {
                    const promptObj = JSON.parse(task.gridPrompt);
                    promptObj.reference_images_description = promptSuffix.join('，') + '。';
                    finalGridPrompt = JSON.stringify(promptObj);
                  } catch(e) {
                    finalGridPrompt = task.gridPrompt + refSuffixText;
                  }
                }
                
                form.append('prompt', finalGridPrompt);
                form.append('count', '1');
                form.append('model', finalModel);
                form.append('user_id', getUserId());
                form.append('auth_token', getAuthToken());
                
                if(finalModel === 'gemini-3-pro-image-preview') {
                  form.append('image_size', '4K');
                }
                
                let apiUrl, res;
                if(referenceImageUrls.length > 0) {
                  // 有参考图片URL，使用图片编辑API，直接传URL
                  form.append('ref_image_urls', referenceImageUrls.join(','));
                  form.append('ratio', state.ratio || '16:9');
                  apiUrl = '/api/image-edit';
                } else {
                  // 无参考图片，使用文生图API
                  form.append('aspect_ratio', state.ratio || '16:9');
                  apiUrl = '/api/text-to-image';
                }
                
                res = await fetch(apiUrl, {
                  method: 'POST',
                  body: form
                });
                
                const data = await res.json();
                
                if(!res.ok) {
                  const errorMsg = typeof data.detail === 'string' ? data.detail : 
                                   typeof data.message === 'string' ? data.message :
                                   JSON.stringify(data.detail || data.message || '提交任务失败');
                  throw new Error(errorMsg);
                }
                
                if(!data.project_ids || data.project_ids.length === 0) {
                  throw new Error('提交任务失败：未返回项目ID');
                }
                
                return {
                  ...task,
                  aiToolsId: data.project_ids[0]
                };
              });

              const completedTasks = await Promise.all(apiPromises);
              
              gridStatusEl.textContent = '正在创建分镜图节点...';
              
              const aiToolsMap = {};
              completedTasks.forEach((task) => {
                aiToolsMap[String(task.aiToolsId)] = {
                  batchNodes: task.batchNodes,
                  gridSize: gridSize
                };
                
                task.batchNodes.forEach((shotFrameNode, idx) => {
                  const gridIndex = idx + 1;
                  const gridImageNodeId = createImageNode({
                    x: shotFrameNode.x + 380,
                    y: shotFrameNode.y
                  });
                  
                  const gridImageNode = state.nodes.find(n => n.id === gridImageNodeId);
                  if(gridImageNode) {
                    gridImageNode.data.name = `分镜图 ${gridIndex}/${gridSize}`;
                    gridImageNode.data.project_id = task.aiToolsId;
                    gridImageNode.data.aiToolsId = task.aiToolsId;
                    gridImageNode.data.gridIndex = gridIndex;
                    gridImageNode.data.gridSize = gridSize;
                    gridImageNode.data.shotFrameNodeId = shotFrameNode.id;
                    gridImageNode.data.isSplit = false;
                    gridImageNode.data.status = 'pending';
                    gridImageNode.title = gridImageNode.data.name;
                    
                    const nodeEl = canvasEl.querySelector(`.node[data-node-id="${gridImageNodeId}"]`);
                    if(nodeEl) {
                      const titleEl = nodeEl.querySelector('.node-title');
                      if(titleEl) titleEl.textContent = gridImageNode.title;
                    }
                    
                    state.connections.push({
                      id: state.nextConnId++,
                      from: shotFrameNode.id,
                      to: gridImageNodeId
                    });
                  }
                });
              });

              renderConnections();
              renderImageConnections();
              renderFirstFrameConnections();
              renderVideoConnections();
              renderMinimap();
              try{ autoSaveWorkflow(); } catch(e){}

              gridStatusEl.style.color = '#16a34a';
              gridStatusEl.textContent = `已提交${imageCount}张宫格图片生成任务，正在轮询状态...`;
              showToast(`已提交${imageCount}张宫格图片生成任务`, 'success');

              const allAiToolsIds = completedTasks.map(t => t.aiToolsId);
              
              pollVideoStatus(
                allAiToolsIds,
                (progressText) => {
                  gridStatusEl.textContent = progressText;
                },
                async (statusResult) => {
                  if(statusResult.tasks) {
                    for(const taskInfo of statusResult.tasks) {
                      const aiToolsId = String(taskInfo.project_id);
                      const taskData = aiToolsMap[aiToolsId];
                      
                      if(!taskData) continue;
                      
                      if(taskInfo.status === 'SUCCESS') {
                        console.log(`[宫格生图] AI工具 ${aiToolsId} 生成成功，开始拆分图片`);
                        
                        for(let idx = 0; idx < taskData.batchNodes.length; idx++) {
                          const gridIndex = idx + 1;
                          
                          try {
                            const splitResponse = await fetch(
                              `/api/ai-tools/${aiToolsId}/grid-split?grid_index=${gridIndex}&user_id=${getUserId()}&grid_size=${gridSize}`,
                              {
                                headers: {
                                  'Authorization': getAuthToken(),
                                  'X-User-Id': getUserId()
                                }
                              }
                            );
                            
                            if(splitResponse.ok) {
                              const splitData = await splitResponse.json();
                              if(splitData.code === 0 && splitData.data && splitData.data.image_url) {
                                const gridNode = state.nodes.find(n => 
                                  n.type === 'image' && 
                                  String(n.data.aiToolsId) === aiToolsId && 
                                  n.data.gridIndex === gridIndex
                                );
                                
                                if(gridNode) {
                                  const normalizedUrl = normalizeImageUrl(splitData.data.image_url);
                                  gridNode.data.url = normalizedUrl;
                                  gridNode.data.preview = normalizedUrl;
                                  gridNode.data.isSplit = true;
                                  gridNode.data.status = 'completed';
                                  
                                  const nodeEl = document.querySelector(`.node[data-node-id="${gridNode.id}"]`);
                                  if(nodeEl) {
                                    const previewImg = nodeEl.querySelector('.image-preview');
                                    const previewRow = nodeEl.querySelector('.image-preview-row');
                                    if(previewImg && previewRow) {
                                      previewImg.src = proxyImageUrl(splitData.data.image_url);
                                      previewRow.style.display = 'flex';
                                    }
                                  }
                                  
                                  // 触发连接的分镜节点更新视频首帧预览
                                  const connectedShotFrameNode = state.connections
                                    .filter(c => c.from === gridNode.id)
                                    .map(c => state.nodes.find(n => n.id === c.to && n.type === 'shot_frame'))
                                    .find(Boolean);
                                  
                                  if(connectedShotFrameNode && connectedShotFrameNode.updatePreview) {
                                    connectedShotFrameNode.updatePreview();
                                  }
                                }
                              }
                            }
                          } catch(error) {
                            console.error(`[宫格生图] 拆分图片失败 (${aiToolsId}, ${gridIndex}):`, error);
                          }
                        }
                      } else if(taskInfo.status === 'FAILED') {
                        console.warn(`[宫格生图] AI工具 ${aiToolsId} 生成失败: ${taskInfo.reason || '未知原因'}`);
                        
                        state.nodes.forEach(gridNode => {
                          if(gridNode.type === 'image' && String(gridNode.data.aiToolsId) === aiToolsId) {
                            gridNode.data.status = 'failed';
                          }
                        });
                      }
                    }
                  }
                  
                  try {
                    await autoSaveWorkflow();
                  } catch(e) {
                    console.error('[宫格生图] 自动保存失败:', e);
                  }
                  
                  gridStatusEl.style.color = '#16a34a';
                  gridStatusEl.textContent = '宫格图片生成完成';
                  showToast('宫格图片生成完成', 'success');
                },
                (errorMsg) => {
                  gridStatusEl.style.color = '#dc2626';
                  gridStatusEl.textContent = errorMsg;
                  showToast(errorMsg, 'error');
                }
              );
              
            } catch(error) {
              console.error('[宫格生图] 失败:', error);
              gridStatusEl.style.color = '#dc2626';
              gridStatusEl.textContent = '失败: ' + (error.message || '未知错误');
              showToast('宫格生图失败: ' + (error.message || '未知错误'), 'error');
            }
            return;
          }
        }

        if(!state.defaultWorldId){
          const confirmed = window.confirm('尚未在左上角选择世界，无法自动匹配场景和角色。确认继续拆分分镜图吗？');
          if(!confirmed){
            return;
          }
        }

        gridStatusEl.style.display = 'block';
        gridStatusEl.style.color = '#666';
        gridStatusEl.textContent = node.data.narrationAsDialogue ? '正在将剧本转换为解说剧格式，再解析分镜...' : '正在调用LLM解析剧本...';

        try {
          // 第一步：解析剧本
          const response = await fetch('/api/parse-script', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': getAuthToken(),
              'X-User-Id': getUserId()
            },
            body: JSON.stringify({
              script_content: node.data.scriptContent,
              max_group_duration: node.data.maxGroupDuration || 15,
              world_id: state.defaultWorldId,
              force_medium_shot: node.data.forceMediumShot || false,
              no_bg_music: node.data.noBgMusic || false,
              split_multi_dialogue: node.data.splitMultiDialogue || false,
              narration_as_dialogue: node.data.narrationAsDialogue || false
            })
          });

          const result = await response.json();
          
          if(result.code !== 0 || !result.data) {
            throw new Error(result.message || '解析失败');
          }

          node.data.parsedData = result.data;
          gridStatusEl.style.color = '#16a34a';
          gridStatusEl.textContent = `解析成功！共${result.data.shot_groups?.length || 0}个分镜组`;

          // 第二步：创建分镜组节点和分镜节点
          if(!result.data.shot_groups || result.data.shot_groups.length === 0) {
            throw new Error('未生成分镜组');
          }

          // 预先创建所有柱子
          const scriptId = id;
          const maxGroupDuration = result.data.max_group_duration || 15;
          
          result.data.shot_groups.forEach((shotGroup) => {
            if(shotGroup.shots && Array.isArray(shotGroup.shots)) {
              shotGroup.shots.forEach((shot) => {
                if(shot.shot_number) {
                  createOrUpdatePillar(scriptId, shot.shot_number, shot.duration || maxGroupDuration);
                }
              });
            }
          });

          // 创建分镜组节点
          const createdShotGroupNodes = [];
          let cumulativeY = 0;
          result.data.shot_groups.forEach((shotGroup, index) => {
            const offsetX = 400;
            const shotCount = (shotGroup.shots && shotGroup.shots.length) || 1;
            const shotGroupNodeId = createShotGroupNode({
              x: node.x + offsetX,
              y: node.y + cumulativeY,
              shotGroupData: shotGroup,
              scriptData: result.data
            });
            cumulativeY += shotCount * 700;
            
            if(shotGroupNodeId) {
              state.connections.push({
                id: state.nextConnId++,
                from: id,
                to: shotGroupNodeId
              });
              createdShotGroupNodes.push(shotGroupNodeId);
            }
          });

          // 自动显示时间轴
          state.timeline.visible = true;
          renderTimeline();
          
          renderConnections();
          renderImageConnections();
          renderFirstFrameConnections();
          renderVideoConnections();
          renderMinimap();

          // 第三步：生成分镜节点并收集提示词
          gridStatusEl.textContent = '正在生成分镜节点...';
          console.log(`[宫格生图] 开始生成分镜节点，分镜组数量: ${createdShotGroupNodes.length}`);
          const allShotFrameNodes = [];
          
          for(const shotGroupNodeId of createdShotGroupNodes) {
            const shotGroupNode = state.nodes.find(n => n.id === shotGroupNodeId);
            if(shotGroupNode) {
              console.log(`[宫格生图] 处理分镜组 ${shotGroupNodeId}`);
              const shotFrameNodeIds = await generateShotFramesIndependentAsync(shotGroupNodeId, shotGroupNode);
              console.log(`[宫格生图] 分镜组 ${shotGroupNodeId} 返回的节点ID: ${shotFrameNodeIds}`);
              if(shotFrameNodeIds && shotFrameNodeIds.length > 0) {
                const shotNodes = shotFrameNodeIds.map(nid => state.nodes.find(n => n.id === nid)).filter(Boolean);
                console.log(`[宫格生图] 找到 ${shotNodes.length} 个有效的分镜节点`);
                allShotFrameNodes.push(...shotNodes);
              } else {
                console.warn(`[宫格生图] 分镜组 ${shotGroupNodeId} 没有返回任何节点ID`);
              }
            }
          }

          console.log(`[宫格生图] 总共收集到 ${allShotFrameNodes.length} 个分镜节点`);
          if(allShotFrameNodes.length === 0) {
            throw new Error('未生成分镜节点');
          }

          // 收集参考图片URL（角色、场景、道具）
          gridStatusEl.textContent = '正在收集参考图片...';
          const { referenceImageUrls, promptSuffix } = await collectReferenceImagesForGrid(allShotFrameNodes);
          console.log(`[宫格生图] 收集到 ${referenceImageUrls.length} 张参考图片URL`);

          // 第四步：根据分镜数量决定宫格大小
          const shotCount = allShotFrameNodes.length;
          if(shotCount === 1) {
            gridStatusEl.style.color = '#f59e0b';
            gridStatusEl.textContent = '只有1个分镜，无需宫格生图';
            showToast('只有1个分镜，无需宫格生图', 'warning');
            return;
          }

          const gridModel = node.data.gridModel || 'auto';
          let gridSize, gridLayout, finalModel;
          
          // 如果参考图片超过5张，必须使用增强版模型（支持13张参考图）
          const forceEnhancedModel = referenceImageUrls.length > 5;
          if(forceEnhancedModel) {
            console.log(`[宫格生图] 参考图片数量(${referenceImageUrls.length})超过5张，强制使用增强版模型`);
          }
          
          if(gridModel === 'auto') {
            // 智能模式：根据分镜数量和参考图片数量自动选择
            if(shotCount <= 5 && !forceEnhancedModel) {
              gridSize = 4;
              gridLayout = '2x2';
              finalModel = 'gemini-2.5-pro-image-preview';
            } else {
              gridSize = 9;
              gridLayout = '3x3';
              finalModel = 'gemini-3-pro-image-preview';
            }
          } else if(gridModel === 'gemini-2.5-pro-image-preview' && !forceEnhancedModel) {
            // 标准版：固定4宫格（但如果参考图超过5张则强制升级）
            gridSize = 4;
            gridLayout = '2x2';
            finalModel = gridModel;
          } else if(gridModel === 'gemini-3-pro-4grid') {
            // 加强版4宫格：4宫格但使用加强版模型
            gridSize = 4;
            gridLayout = '2x2';
            finalModel = 'gemini-3-pro-image-preview';
          } else {
            // 加强版9宫格，或因参考图数量强制升级
            gridSize = 9;
            gridLayout = '3x3';
            finalModel = 'gemini-3-pro-image-preview';
          }
          
          // 限制参考图片数量（标准版最多5张，增强版最多10张）
          const maxRefImages = finalModel === 'gemini-3-pro-image-preview' ? 10 : 5;
          if(referenceImageUrls.length > maxRefImages) {
            console.warn(`[宫格生图] 参考图片数量 ${referenceImageUrls.length} 超过限制 ${maxRefImages}，将只使用前 ${maxRefImages} 张`);
            referenceImageUrls.splice(maxRefImages);
            promptSuffix.splice(maxRefImages);
          }
          
          node.data.gridModel = finalModel;
          const imagePower = finalModel === 'gemini-3-pro-image-preview' ? 6 : 2;
          const imageCount = Math.ceil(shotCount / gridSize);
          const totalPower = imageCount * imagePower;

          // 确认生成
          const refImageInfo = referenceImageUrls.length > 0 ? `\n参考图片：${referenceImageUrls.length}张` : '';
          const confirmMsg = `即将生成${imageCount}张${gridLayout}宫格图片\n` +
            `分镜数量：${shotCount}个\n` +
            `模型：${finalModel === 'gemini-3-pro-image-preview' ? '加强版' : '标准版'}${refImageInfo}\n` +
            `预计消耗算力：${totalPower}\n\n` +
            `确认生成吗？`;
          
          if(!window.confirm(confirmMsg)) {
            gridStatusEl.style.color = '#666';
            gridStatusEl.textContent = '已取消';
            return;
          }

          // 第五步：拼接提示词并调用API
          gridStatusEl.textContent = `正在生成${imageCount}张${gridLayout}宫格图片...`;
          
          const gridTasks = [];
          for(let i = 0; i < imageCount; i++) {
            const startIdx = i * gridSize;
            const endIdx = Math.min(startIdx + gridSize, shotCount);
            const batchNodes = allShotFrameNodes.slice(startIdx, endIdx);
            
            // 构建宫格JSON提示词
            const shots = [];
            for(let idx = 0; idx < gridSize; idx++){
              // 如果分镜数量不足填满宫格，用最后一个分镜的提示词填充
              const nodeIndex = idx < batchNodes.length ? idx : batchNodes.length - 1;
              const shotNode = batchNodes[nodeIndex];
              shots.push({
                shot_number: `Shot ${startIdx + idx + 1}`,
                prompt_text: shotNode.data.imagePrompt || ''
              });
            }
            
            const gridPrompt = JSON.stringify({
              grid_layout: gridLayout,
              grid_aspect_ratio: state.ratio || '16:9',
              global_watermark: '',
              style_guidance: "NO TEXT, NO TITLE, NO LABELS, clean grid lines only.",
              shots: shots
            });
            
            gridTasks.push({
              batchNodes,
              gridPrompt,
              startIdx
            });
          }

          // 构建参考图片说明后缀
          const refSuffixText = promptSuffix.length > 0 ? `\n\n${promptSuffix.join('，')}。` : '';
          
          // 并行调用图片编辑API
          const apiPromises = gridTasks.map(async (task) => {
            const form = new FormData();
            
            // 添加参考图片说明到提示词
            let finalGridPrompt = task.gridPrompt;
            if(refSuffixText) {
              try {
                const promptObj = JSON.parse(task.gridPrompt);
                promptObj.reference_images_description = promptSuffix.join('，') + '。';
                finalGridPrompt = JSON.stringify(promptObj);
              } catch(e) {
                finalGridPrompt = task.gridPrompt + refSuffixText;
              }
            }
            
            form.append('prompt', finalGridPrompt);
            form.append('count', '1');
            form.append('model', finalModel);
            form.append('user_id', getUserId());
            form.append('auth_token', getAuthToken());
            
            // 加强版模型需要传入4K图片大小
            if(finalModel === 'gemini-3-pro-image-preview') {
              form.append('image_size', '4K');
            }
            
            let apiUrl, res;
            if(referenceImageUrls.length > 0) {
              // 有参考图片URL，使用图片编辑API，直接传URL
              form.append('ref_image_urls', referenceImageUrls.join(','));
              form.append('ratio', state.ratio || '16:9');
              apiUrl = '/api/image-edit';
            } else {
              // 无参考图片，使用文生图API
              form.append('aspect_ratio', state.ratio || '16:9');
              apiUrl = '/api/text-to-image';
            }
            
            res = await fetch(apiUrl, {
              method: 'POST',
              body: form
            });
            
            const data = await res.json();
            
            if(!res.ok) {
              const errorMsg = typeof data.detail === 'string' ? data.detail : 
                               typeof data.message === 'string' ? data.message :
                               JSON.stringify(data.detail || data.message || '提交任务失败');
              throw new Error(errorMsg);
            }
            
            if(!data.project_ids || data.project_ids.length === 0) {
              throw new Error('提交任务失败：未返回项目ID');
            }
            
            return {
              ...task,
              aiToolsId: data.project_ids[0]
            };
          });

          const completedTasks = await Promise.all(apiPromises);
          
          // 第六步：为每个分镜节点创建分镜图子节点
          gridStatusEl.textContent = '正在创建分镜图节点...';
          
          // 创建节点映射：aiToolsId -> {batchNodes, gridSize}
          const aiToolsMap = {};
          completedTasks.forEach((task) => {
            // 确保key是字符串类型
            aiToolsMap[String(task.aiToolsId)] = {
              batchNodes: task.batchNodes,
              gridSize: gridSize
            };
            
            task.batchNodes.forEach((shotFrameNode, idx) => {
              const gridIndex = idx + 1;
              const gridImageNodeId = createImageNode({
                x: shotFrameNode.x + 380,
                y: shotFrameNode.y
              });
              
              const gridImageNode = state.nodes.find(n => n.id === gridImageNodeId);
              if(gridImageNode) {
                gridImageNode.data.name = `分镜图 ${gridIndex}/${gridSize}`;
                gridImageNode.data.project_id = task.aiToolsId;
                gridImageNode.data.aiToolsId = task.aiToolsId;
                gridImageNode.data.gridIndex = gridIndex;
                gridImageNode.data.gridSize = gridSize;
                gridImageNode.data.shotFrameNodeId = shotFrameNode.id;
                gridImageNode.data.isSplit = false;
                gridImageNode.data.status = 'pending';
                gridImageNode.title = gridImageNode.data.name;
                
                const nodeEl = canvasEl.querySelector(`.node[data-node-id="${gridImageNodeId}"]`);
                if(nodeEl) {
                  const titleEl = nodeEl.querySelector('.node-title');
                  if(titleEl) titleEl.textContent = gridImageNode.title;
                }
                
                state.connections.push({
                  id: state.nextConnId++,
                  from: shotFrameNode.id,
                  to: gridImageNodeId
                });
              }
            });
          });

          renderConnections();
          renderImageConnections();
          renderFirstFrameConnections();
          renderVideoConnections();
          renderMinimap();
          try{ autoSaveWorkflow(); } catch(e){}

          gridStatusEl.style.color = '#16a34a';
          gridStatusEl.textContent = `已提交${imageCount}张宫格图片生成任务，正在轮询状态...`;
          showToast(`已提交${imageCount}张宫格图片生成任务`, 'success');

          // 收集所有 aiToolsId 用于轮询
          const allAiToolsIds = completedTasks.map(t => t.aiToolsId);
          
          // 复用 pollVideoStatus 进行轮询
          pollVideoStatus(
            allAiToolsIds,
            (progressText) => {
              gridStatusEl.textContent = progressText;
            },
            async (statusResult) => {
              // 所有任务完成，处理每个任务
              if(statusResult.tasks) {
                for(const taskInfo of statusResult.tasks) {
                  // 确保类型一致（字符串）
                  const aiToolsId = String(taskInfo.project_id);
                  const taskData = aiToolsMap[aiToolsId];
                  
                  if(!taskData) continue;
                  
                  if(taskInfo.status === 'SUCCESS') {
                    // 成功：拆分图片并更新节点
                    console.log(`[宫格生图] AI工具 ${aiToolsId} 生成成功，开始拆分图片`);
                    
                    for(let idx = 0; idx < taskData.batchNodes.length; idx++) {
                      const gridIndex = idx + 1;
                      
                      try {
                        // 调用拆分接口
                        const splitResponse = await fetch(
                          `/api/ai-tools/${aiToolsId}/grid-split?grid_index=${gridIndex}&user_id=${getUserId()}&grid_size=${gridSize}`,
                          {
                            headers: {
                              'Authorization': getAuthToken(),
                              'X-User-Id': getUserId()
                            }
                          }
                        );
                        
                        if(splitResponse.ok) {
                          const splitData = await splitResponse.json();
                          if(splitData.code === 0 && splitData.data && splitData.data.image_url) {
                            const gridNode = state.nodes.find(n => 
                              n.type === 'image' && 
                              String(n.data.aiToolsId) === aiToolsId && 
                              n.data.gridIndex === gridIndex
                            );
                            
                            if(gridNode) {
                              const normalizedUrl = normalizeImageUrl(splitData.data.image_url);
                              gridNode.data.url = normalizedUrl;
                              gridNode.data.preview = normalizedUrl;
                              gridNode.data.isSplit = true;
                              gridNode.data.status = 'completed';
                              
                              const nodeEl = document.querySelector(`.node[data-node-id="${gridNode.id}"]`);
                              if(nodeEl) {
                                const previewImg = nodeEl.querySelector('.image-preview');
                                const previewRow = nodeEl.querySelector('.image-preview-row');
                                if(previewImg && previewRow) {
                                  previewImg.src = proxyImageUrl(splitData.data.image_url);
                                  previewRow.style.display = 'flex';
                                }
                              }
                              
                              // 触发连接的分镜节点更新视频首帧预览
                              if(gridNode.data.shotFrameNodeId) {
                                const shotFrameNode = state.nodes.find(n => n.id === gridNode.data.shotFrameNodeId);
                                if(shotFrameNode && shotFrameNode.updatePreview) {
                                  shotFrameNode.updatePreview();
                                  console.log(`[宫格生图] 分镜节点 ${shotFrameNode.id} 更新后 previewImageUrl:`, shotFrameNode.data.previewImageUrl);
                                }
                              }
                            }
                          }
                        }
                      } catch(error) {
                        console.error(`[宫格生图] 拆分图片失败 (${aiToolsId}, ${gridIndex}):`, error);
                      }
                    }
                  } else if(taskInfo.status === 'FAILED') {
                    console.warn(`[宫格生图] AI工具 ${aiToolsId} 生成失败: ${taskInfo.reason || '未知原因'}`);
                    
                    state.nodes.forEach(gridNode => {
                      if(gridNode.type === 'image' && String(gridNode.data.aiToolsId) === aiToolsId) {
                        gridNode.data.status = 'failed';
                      }
                    });
                  }
                }
              }
              
              // 保存工作流
              try {
                await autoSaveWorkflow();
              } catch(e) {
                console.error('[宫格生图] 自动保存失败:', e);
              }
              
              gridStatusEl.style.color = '#16a34a';
              gridStatusEl.textContent = '宫格图片生成完成';
              showToast('宫格图片生成完成', 'success');
            },
            (errorMsg) => {
              gridStatusEl.style.color = '#dc2626';
              gridStatusEl.textContent = errorMsg;
              showToast(errorMsg, 'error');
            }
          );

        } catch(error) {
          console.error('宫格生图失败:', error);
          gridStatusEl.style.color = '#dc2626';
          gridStatusEl.textContent = '失败: ' + (error.message || '未知错误');
          showToast('宫格生图失败: ' + (error.message || '未知错误'), 'error');
        }
      });

      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);
      setSelected(id);
      return id;
    }

    // ============ 宫格预览辅助函数 ============

    function calculateGridSize(shotCount) {
      if(shotCount <= 4) return 4;
      if(shotCount <= 9) return 9;
      if(shotCount <= 16) return 16;
      if(shotCount <= 25) return 25;
      return null;
    }

    function getConnectedShotFrameNodes(shotGroupNodeId) {
      const conns = state.connections.filter(c => c.from === shotGroupNodeId);
      return conns
        .map(conn => state.nodes.find(n => n.id === conn.to && n.type === 'shot_frame'))
        .filter(Boolean);
    }

    function updateGridPreviewUI(nodeEl, shotGroupNode) {
      const container = nodeEl.querySelector('.shot-grid-preview-container');
      const labelEl = nodeEl.querySelector('.shot-grid-preview-label');
      if(!container) return;

      const shotFrameNodes = getConnectedShotFrameNodes(shotGroupNode.id);
      const shotCount = shotFrameNodes.length;

      if(shotCount === 0) {
        container.innerHTML = '<div style="padding: 16px; text-align: center; color: #666; font-size: 11px; grid-column: 1/-1;">暂无分镜节点</div>';
        if(labelEl) labelEl.textContent = '分镜预览（0个分镜）';
        return;
      }

      const gridSize = calculateGridSize(shotCount);
      if(!gridSize) {
        container.innerHTML = '<div style="padding: 16px; text-align: center; color: #f59e0b; font-size: 11px; grid-column: 1/-1;">分镜数量超过25，不支持宫格预览</div>';
        return;
      }

      const n = Math.sqrt(gridSize);
      container.className = `shot-grid-preview-container grid-${n}x${n}`;

      if(labelEl) labelEl.textContent = `分镜预览（${shotCount}个分镜 → ${gridSize}宫格）`;

      // 更新节点数据
      shotGroupNode.data.gridPreview = shotGroupNode.data.gridPreview || {};
      shotGroupNode.data.gridPreview.currentGridSize = gridSize;
      shotGroupNode.data.gridPreview.shotFrameNodeIds = shotFrameNodes.map(n => n.id);

      let cellsHtml = '';
      for(let i = 0; i < gridSize; i++) {
        if(i < shotCount) {
          const sfNode = shotFrameNodes[i];
          const imgUrl = sfNode.data.previewImageUrl || sfNode.data.imageUrl || '';
          if(imgUrl) {
            cellsHtml += `<div class="grid-cell" data-index="${i}"><img src="${proxyImageUrl(imgUrl)}" /><span class="grid-cell-label">${i+1}</span></div>`;
          } else {
            cellsHtml += `<div class="grid-cell grid-cell-empty" data-index="${i}"><span class="grid-cell-label">${i+1}</span></div>`;
          }
        } else {
          cellsHtml += `<div class="grid-cell grid-cell-empty" data-index="${i}"><span class="grid-cell-label" style="color:#555;">${i+1}</span></div>`;
        }
      }
      container.innerHTML = cellsHtml;
    }

    // ============ 宫格预览辅助函数结束 ============

    // 分镜组节点
    function createShotGroupNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = opts && typeof opts.y === 'number' ? opts.y : viewportPos.y;
      const shotGroupData = opts && opts.shotGroupData ? opts.shotGroupData : {};
      const scriptData = opts && opts.scriptData ? opts.scriptData : {};
      
      const groupName = shotGroupData.groupName || shotGroupData.group_name || shotGroupData.group_id || '分镜组';
      const node = {
        id,
        type: 'shot_group',
        title: groupName,
        x,
        y,
        data: {
          groupId: shotGroupData.group_id || '',
          group_id: shotGroupData.group_id || '',
          groupName: groupName,
          shots: shotGroupData.shots || [],
          scriptData: scriptData,
          model: shotGroupData.model || 'gemini-2.5-pro-image-preview',
          videoModel: shotGroupData.videoModel || 'wan22',
          videoDuration: shotGroupData.videoDuration || 5,
          videoDrawCount: shotGroupData.videoDrawCount || 1,
          gridPreview: shotGroupData.gridPreview || {},
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';
      el.style.width = '360px';

      // 构建分镜列表HTML
      const shotsHtml = node.data.shots.map((shot, idx) => {
        const duration = shot.duration ? `${shot.duration}秒` : '未知';
        return `
          <div style="padding: 8px; background: #f8f9fa; border-radius: 6px; margin-bottom: 6px; font-size: 12px;">
            <div style="font-weight: 700; margin-bottom: 4px;">${escapeHtml(shot.shot_id || `镜头${idx+1}`)} - ${escapeHtml(shot.description || '')}</div>
            <div style="color: #666; font-size: 11px;">时长: ${escapeHtml(duration)} | ${escapeHtml(shot.shot_type || '')} | ${escapeHtml(shot.camera_movement || '')}</div>
            <div style="color: #666; font-size: 11px; margin-top: 2px;">起始画面: ${escapeHtml((shot.opening_frame_description || '').slice(0, 60))}...</div>
          </div>
        `;
      }).join('');

      el.innerHTML = `
        <div class="port input" title="输入（连接剧本节点）"></div>
        <div class="port output" title="输出"></div>
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M6 9H18M6 12H14M6 15H12" stroke="currentColor" stroke-linecap="round"/></svg>分镜组: ${escapeHtml(node.title)}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field field-always-visible">
            <div class="label">分镜组: ${escapeHtml(node.data.groupId || node.data.group_id)}</div>
            <div class="gen-meta">共 ${node.data.shots.length} 个分镜</div>
          </div>
          <div class="field field-always-visible" style="max-height: 200px; overflow-y: auto;">
            ${shotsHtml}
          </div>
          <div class="field field-always-visible">
            <div class="shot-grid-preview-label" style="font-size: 11px; color: #666; margin-bottom: 4px;">分镜预览（0个分镜）</div>
            <div class="shot-grid-preview-container grid-2x2">
              <div style="padding: 16px; text-align: center; color: #666; font-size: 11px; grid-column: 1/-1;">暂无分镜节点</div>
            </div>
            <div class="grid-merge-status"></div>
          </div>
          <div class="field field-collapsible">
            <div class="label">分镜模型</div>
            <select class="shot-group-model">
              <option value="gemini-2.5-pro-image-preview">标准版</option>
              <option value="gemini-3-pro-image-preview">加强版</option>
            </select>
          </div>
          <div class="field field-collapsible btn-row">
            <button class="mini-btn secondary shot-group-detail-btn" type="button" style="flex: 1;">查看/编辑</button>
            <button class="mini-btn gen-btn-white shot-group-generate-btn" type="button">生成分镜</button>
          </div>
          <hr style="margin: 12px 0; border: none; border-top: 1px solid #e5e7eb;">
          <div class="field field-collapsible">
            <div class="label">宫格生图模型</div>
            <select class="shot-group-grid-model" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
              <option value="auto">智能模式 (自动选择)</option>
              <option value="gemini-2.5-pro-image-preview">标准版 (4宫格, 2算力/张)</option>
              <option value="gemini-3-pro-4grid">加强版 (4宫格, 6算力/张)</option>
              <option value="gemini-3-pro-image-preview">加强版 (9宫格, 6算力/张)</option>
            </select>
          </div>
          <div class="field field-collapsible btn-row">
            <button class="mini-btn gen-btn-green shot-group-grid-btn" type="button" style="width: 100%;">宫格生图</button>
          </div>
          <div class="gen-meta shot-group-grid-status" style="display:none; margin-top: 8px;"></div>
          <hr style="margin: 12px 0; border: none; border-top: 1px solid #e5e7eb;">
          <div class="field field-collapsible">
            <div class="label">视频模型</div>
            <select class="shot-group-video-model">
              <option value="wan22" selected>Wan2.2</option>
              <option value="sora2">Sora2</option>
              <option value="ltx2">LTX2.0</option>
              <option value="kling">可灵</option>
              <option value="vidu">Vidu</option>
              <option value="veo3">VEO3.1</option>
            </select>
          </div>
          <div class="field field-collapsible">
            <div class="label">视频时长</div>
            <select class="shot-group-video-duration">
              <option value="5" selected>5秒</option>
              <option value="10">10秒</option>
            </select>
          </div>
          <div class="field field-collapsible">
            <div class="btn-row" style="display: flex; gap: 8px; justify-content: flex-start;">
              <div class="gen-container">
                <button class="gen-btn gen-btn-main shot-group-generate-video-btn" type="button" style="background: #22c55e; color: white;">生成视频</button>
                <button class="gen-btn gen-btn-caret shot-group-video-caret" type="button" aria-label="选择抽卡次数">▾</button>
                <div class="gen-menu shot-group-video-menu">
                  <div class="gen-item" data-count="1">X1</div>
                  <div class="gen-item" data-count="2">X2</div>
                  <div class="gen-item" data-count="3">X3</div>
                  <div class="gen-item" data-count="4">X4</div>
                </div>
              </div>
            </div>
            <div class="gen-meta shot-group-video-draw-count-label"></div>
            <div class="shot-group-computing-power" style="margin-top: 6px; padding: 6px; border-radius: 6px;">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #9ca3af; font-size: 11px;">算力消耗：</span>
                <span class="shot-group-computing-power-value" style="color: #60a5fa; font-weight: bold; font-size: 12px;">0 算力</span>
              </div>
              <div class="shot-group-computing-power-detail" style="margin-top: 2px; font-size: 10px; color: #6b7280;">
                单个 0 算力 × 1 个 = 0 算力
              </div>
            </div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const detailBtn = el.querySelector('.shot-group-detail-btn');
      const generateBtn = el.querySelector('.shot-group-generate-btn');
      const modelSelect = el.querySelector('.shot-group-model');
      const inputPort = el.querySelector('.port.input');
      const outputPort = el.querySelector('.port.output');

      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });

      el.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        setSelected(id);
        bringNodeToFront(id);
      });

      headerEl.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        // 如果节点不在选中列表中，才调用setSelected（这会清空其他选中）
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        bringNodeToFront(id);
        initNodeDrag(id, e.clientX, e.clientY);
      });

      inputPort.addEventListener('mouseup', (e) => {
        if(state.connecting && state.connecting.fromId !== id){
          const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
          if(fromNode && fromNode.type === 'script'){
            const exists = state.connections.some(c => c.from === state.connecting.fromId && c.to === id);
            if(!exists){
              state.connections.push({
                id: state.nextConnId++,
                from: state.connecting.fromId,
                to: id
              });
              renderConnections();
              renderImageConnections();
              renderFirstFrameConnections();
              renderVideoConnections();
              renderReferenceConnections();
              renderMinimap();
              try{ autoSaveWorkflow(); } catch(e){}
            }
          }
        }
        state.connecting = null;
      });

      outputPort.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
      });

      modelSelect.addEventListener('change', () => {
        node.data.model = modelSelect.value;
      });
      
      // 恢复保存的模型选择
      if(node.data.model){
        modelSelect.value = node.data.model;
      }

      generateBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        generateShotFramesIndependent(id, node);
      });

      detailBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openShotGroupModal(node.data, id);
      });

      // 宫格生图按钮和模型选择器
      const gridBtn = el.querySelector('.shot-group-grid-btn');
      const gridModelSelect = el.querySelector('.shot-group-grid-model');
      const gridStatusEl = el.querySelector('.shot-group-grid-status');
      
      // 初始化宫格模型选择（默认智能模式）
      if(!node.data.gridModel){
        node.data.gridModel = 'auto';
      }
      if(gridModelSelect){
        gridModelSelect.value = node.data.gridModel;
        gridModelSelect.addEventListener('change', () => {
          node.data.gridModel = gridModelSelect.value;
        });
      }
      
      // 宫格生图按钮点击事件
      if(gridBtn){
        gridBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          generateShotGroupGridImages(id, node, gridStatusEl);
        });
      }

      // 视频生成相关元素
      const videoModelEl = el.querySelector('.shot-group-video-model');
      const videoDurationEl = el.querySelector('.shot-group-video-duration');
      const generateVideoBtn = el.querySelector('.shot-group-generate-video-btn');
      const videoCaret = el.querySelector('.shot-group-video-caret');
      const videoMenu = el.querySelector('.shot-group-video-menu');
      const videoDrawCountLabel = el.querySelector('.shot-group-video-draw-count-label');
      const computingPowerValue = el.querySelector('.shot-group-computing-power-value');
      const computingPowerDetail = el.querySelector('.shot-group-computing-power-detail');

      // 初始化视频模型和时长
      if(videoModelEl) videoModelEl.value = node.data.videoModel;
      if(videoDurationEl) videoDurationEl.value = node.data.videoDuration;

      // 根据模型更新时长选项
      function updateVideoDurationOptions(videoModel) {
        const currentDuration = node.data.videoDuration;
        videoDurationEl.innerHTML = '';
        
        const durationConfig = getVideoModelDurationOptions();
        let durationOptions = durationConfig[videoModel];
        
        if(!durationOptions || durationOptions.length === 0) {
          const defaultOptions = {
            'ltx2': [5, 8, 10],
            'wan22': [5, 10],
            'kling': [5, 10],
            'vidu': [5, 8],
            'veo3': [8],
            'sora2': [10, 15]
          };
          durationOptions = defaultOptions[videoModel] || [5, 10];
        }
        
        durationOptions.forEach(d => {
          const opt = document.createElement('option');
          opt.value = d;
          opt.textContent = `${d}秒`;
          videoDurationEl.appendChild(opt);
        });
        
        const durationStrings = durationOptions.map(d => String(d));
        if(durationStrings.includes(String(currentDuration))) {
          videoDurationEl.value = currentDuration;
        } else {
          const firstOption = durationOptions[0];
          videoDurationEl.value = firstOption;
          node.data.videoDuration = firstOption;
        }
      }
      
      updateVideoDurationOptions(node.data.videoModel);

      // 计算视频生成算力消耗
      function calculateVideoComputingPower() {
        const config = getTaskComputingPowerConfig();
        if(!config || Object.keys(config).length === 0) {
          return 0;
        }
        
        let power = 0;
        const videoModel = node.data.videoModel || 'wan22';
        const duration = node.data.videoDuration || 5;
        
        if(videoModel === 'sora2') {
          power = config[3] || 0;
        } else if(videoModel === 'ltx2') {
          power = config[10] || 0;
        } else if(videoModel === 'wan22') {
          const wan22Power = config[11];
          if(typeof wan22Power === 'object') {
            power = wan22Power[duration] || wan22Power[5] || 0;
          } else {
            power = wan22Power || 0;
          }
        } else if(videoModel === 'kling') {
          const klingPower = config[12];
          if(typeof klingPower === 'object') {
            power = klingPower[duration] || klingPower[5] || 0;
          } else {
            power = klingPower || 0;
          }
        } else if(videoModel === 'vidu') {
          const viduPower = config[14];
          if(typeof viduPower === 'object') {
            power = viduPower[duration] || viduPower[5] || 0;
          } else {
            power = viduPower || 0;
          }
        } else if(videoModel === 'veo3') {
          power = config[15] || 0;
        }
        
        return power;
      }
      
      // 更新视频算力显示
      function updateVideoComputingPowerDisplay() {
        const singlePower = calculateVideoComputingPower();
        const count = node.data.videoDrawCount || 1;
        const totalPower = singlePower * count;
        
        if(computingPowerValue) {
          computingPowerValue.textContent = `${totalPower} 算力`;
        }
        if(computingPowerDetail) {
          computingPowerDetail.textContent = `单个 ${singlePower} 算力 × ${count} 个 = ${totalPower} 算力`;
        }
      }

      // 初始化抽卡次数显示
      function updateVideoDrawCountLabel(){
        videoDrawCountLabel.textContent = `抽卡次数：X${node.data.videoDrawCount}`;
        updateVideoComputingPowerDisplay();
      }
      updateVideoDrawCountLabel();
      updateVideoComputingPowerDisplay();

      // 视频模型选择事件
      videoModelEl.addEventListener('change', () => {
        node.data.videoModel = videoModelEl.value;
        updateVideoDurationOptions(videoModelEl.value);
        updateVideoComputingPowerDisplay();
      });

      // 视频时长选择事件
      videoDurationEl.addEventListener('change', () => {
        node.data.videoDuration = Number(videoDurationEl.value);
        updateVideoComputingPowerDisplay();
      });

      // 视频抽卡次数选择
      videoCaret.addEventListener('click', (e) => {
        e.stopPropagation();
        videoMenu.classList.toggle('show');
      });

      const videoGenItems = videoMenu.querySelectorAll('.gen-item');
      for(const item of videoGenItems){
        item.addEventListener('click', (e) => {
          e.stopPropagation();
          const count = Number(item.dataset.count || '1');
          node.data.videoDrawCount = count;
          updateVideoDrawCountLabel();
          videoMenu.classList.remove('show');
        });
      }

      // 生成视频按钮点击事件
      generateVideoBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        generateShotGroupVideo(id, node);
      });

      // 宫格预览刷新方法（挂到node对象上，供外部调用）
      node.refreshGridPreview = function() {
        updateGridPreviewUI(el, node);
      };

      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);

      // 初始化宫格预览（延迟执行，确保连接已建立）
      setTimeout(() => { updateGridPreviewUI(el, node); }, 100);

      setSelected(id);
      return id;
    }

    // 分镜组节点宫格生图功能
    async function generateShotGroupGridImages(shotGroupNodeId, shotGroupNode, gridStatusEl) {
      try {
        gridStatusEl.style.display = 'block';
        gridStatusEl.style.color = '#666';
        gridStatusEl.textContent = '正在检查分镜节点...';
        
        // 第一步：检查是否已有分镜节点
        const existingConnections = state.connections.filter(c => c.from === shotGroupNodeId);
        const existingShotFrameNodes = existingConnections
          .map(conn => state.nodes.find(n => n.id === conn.to && n.type === 'shot_frame'))
          .filter(Boolean);
        
        let allShotFrameNodes = [];
        
        if(existingShotFrameNodes.length === 0) {
          // 没有分镜节点，先生成分镜节点
          gridStatusEl.textContent = '正在生成分镜节点...';
          const shotFrameNodeIds = await generateShotFramesIndependentAsync(shotGroupNodeId, shotGroupNode);
          
          if(!shotFrameNodeIds || shotFrameNodeIds.length === 0) {
            throw new Error('生成分镜节点失败');
          }
          
          allShotFrameNodes = shotFrameNodeIds.map(nid => state.nodes.find(n => n.id === nid)).filter(Boolean);
        } else {
          // 已有分镜节点，直接使用
          allShotFrameNodes = existingShotFrameNodes;
        }
        
        console.log(`[宫格生图] 总共收集到 ${allShotFrameNodes.length} 个分镜节点`);
        
        if(allShotFrameNodes.length === 0) {
          throw new Error('未找到分镜节点');
        }
        
        // 第二步：收集参考图片URL（角色、场景、道具）
        gridStatusEl.textContent = '正在收集参考图片...';
        const { referenceImageUrls, promptSuffix } = await collectReferenceImagesForGrid(allShotFrameNodes);
        console.log(`[宫格生图] 收集到 ${referenceImageUrls.length} 张参考图片URL`);
        
        // 第三步：根据分镜数量决定宫格大小
        const shotCount = allShotFrameNodes.length;
        if(shotCount === 1) {
          gridStatusEl.style.color = '#f59e0b';
          gridStatusEl.textContent = '只有1个分镜，无需宫格生图';
          showToast('只有1个分镜，无需宫格生图', 'warning');
          return;
        }
        
        const gridModel = shotGroupNode.data.gridModel || 'auto';
        let gridSize, gridLayout, finalModel;
        
        // 如果参考图片超过5张，必须使用增强版模型（支持13张参考图）
        const forceEnhancedModel = referenceImageUrls.length > 5;
        if(forceEnhancedModel) {
          console.log(`[宫格生图] 参考图片数量(${referenceImageUrls.length})超过5张，强制使用增强版模型`);
        }
        
        if(gridModel === 'auto') {
          // 智能模式：根据分镜数量和参考图片数量自动选择
          if(shotCount <= 5 && !forceEnhancedModel) {
            gridSize = 4;
            gridLayout = '2x2';
            finalModel = 'gemini-2.5-pro-image-preview';
          } else {
            gridSize = 9;
            gridLayout = '3x3';
            finalModel = 'gemini-3-pro-image-preview';
          }
        } else if(gridModel === 'gemini-2.5-pro-image-preview' && !forceEnhancedModel) {
          // 标准版：固定4宫格（但如果参考图超过5张则强制升级）
          gridSize = 4;
          gridLayout = '2x2';
          finalModel = gridModel;
        } else if(gridModel === 'gemini-3-pro-4grid') {
          // 加强版4宫格：4宫格但使用加强版模型
          gridSize = 4;
          gridLayout = '2x2';
          finalModel = 'gemini-3-pro-image-preview';
        } else {
          // 加强版9宫格，或因参考图数量强制升级
          gridSize = 9;
          gridLayout = '3x3';
          finalModel = 'gemini-3-pro-image-preview';
        }
        
        // 限制参考图片数量（标准版最多5张，增强版最多13张）
        const maxRefImages = finalModel === 'gemini-3-pro-image-preview' ? 13 : 5;
        if(referenceImageUrls.length > maxRefImages) {
          console.warn(`[宫格生图] 参考图片数量 ${referenceImageUrls.length} 超过限制 ${maxRefImages}，将只使用前 ${maxRefImages} 张`);
          referenceImageUrls.splice(maxRefImages);
          promptSuffix.splice(maxRefImages);
        }
        
        shotGroupNode.data.gridModel = finalModel;
        
        const imagePower = finalModel === 'gemini-3-pro-image-preview' ? 6 : 2;
        const imageCount = Math.ceil(shotCount / gridSize);
        const totalPower = imageCount * imagePower;
        
        const refImageInfo = referenceImageUrls.length > 0 ? `\n参考图片：${referenceImageUrls.length}张` : '';
        const confirmMsg = `即将生成${imageCount}张${gridLayout}宫格图片\n` +
          `分镜数量：${shotCount}个\n` +
          `模型：${finalModel === 'gemini-3-pro-image-preview' ? '加强版' : '标准版'}${refImageInfo}\n` +
          `预计消耗算力：${totalPower}\n\n` +
          `确认生成吗？`;
        
        if(!window.confirm(confirmMsg)) {
          gridStatusEl.style.color = '#666';
          gridStatusEl.textContent = '已取消';
          return;
        }
        
        // 第四步：拼接提示词并调用API
        gridStatusEl.textContent = `正在生成${imageCount}张${gridLayout}宫格图片...`;
        
        const gridTasks = [];
        for(let i = 0; i < imageCount; i++) {
          const startIdx = i * gridSize;
          const endIdx = Math.min(startIdx + gridSize, shotCount);
          const batchNodes = allShotFrameNodes.slice(startIdx, endIdx);
          
          const shots = [];
          for(let idx = 0; idx < gridSize; idx++){
            // 如果分镜数量不足填满宫格，用最后一个分镜的提示词填充
            const nodeIndex = idx < batchNodes.length ? idx : batchNodes.length - 1;
            const shotNode = batchNodes[nodeIndex];
            shots.push({
              shot_number: `Shot ${startIdx + idx + 1}`,
              prompt_text: shotNode.data.imagePrompt || ''
            });
          }
          
          const gridPrompt = JSON.stringify({
            grid_layout: gridLayout,
            grid_aspect_ratio: state.ratio || '16:9',
            global_watermark: '',
            style_guidance: "NO TEXT, NO TITLE, NO LABELS, clean grid lines only.",
            shots: shots
          });
          
          gridTasks.push({
            batchNodes,
            gridPrompt,
            startIdx
          });
        }
        
        // 构建参考图片说明后缀
        const refSuffixText = promptSuffix.length > 0 ? `\n\n${promptSuffix.join('，')}。` : '';
        
        const apiPromises = gridTasks.map(async (task) => {
          const form = new FormData();
          
          // 添加参考图片说明到提示词
          let finalGridPrompt = task.gridPrompt;
          if(refSuffixText) {
            try {
              const promptObj = JSON.parse(task.gridPrompt);
              promptObj.reference_images_description = promptSuffix.join('，') + '。';
              finalGridPrompt = JSON.stringify(promptObj);
            } catch(e) {
              finalGridPrompt = task.gridPrompt + refSuffixText;
            }
          }
          
          form.append('prompt', finalGridPrompt);
          form.append('count', '1');
          form.append('model', finalModel);
          form.append('user_id', getUserId());
          form.append('auth_token', getAuthToken());
          
          if(finalModel === 'gemini-3-pro-image-preview') {
            form.append('image_size', '4K');
          }
          
          let apiUrl, res;
          if(referenceImageUrls.length > 0) {
            // 有参考图片URL，使用图片编辑API，直接传URL
            form.append('ref_image_urls', referenceImageUrls.join(','));
            form.append('ratio', state.ratio || '16:9');
            apiUrl = '/api/image-edit';
          } else {
            // 无参考图片，使用文生图API
            form.append('aspect_ratio', state.ratio || '16:9');
            apiUrl = '/api/text-to-image';
          }
          
          res = await fetch(apiUrl, {
            method: 'POST',
            body: form
          });
          
          const data = await res.json();
          
          if(!res.ok) {
            const errorMsg = typeof data.detail === 'string' ? data.detail :
                           typeof data.message === 'string' ? data.message :
                           JSON.stringify(data.detail || data.message || '提交任务失败');
            throw new Error(errorMsg);
          }
          
          if(!data.project_ids || data.project_ids.length === 0) {
            throw new Error('提交任务失败：未返回项目ID');
          }
          
          return {
            ...task,
            aiToolsId: data.project_ids[0]
          };
        });
        
        const completedTasks = await Promise.all(apiPromises);
        
        gridStatusEl.textContent = '正在创建分镜图节点...';
        
        const aiToolsMap = {};
        completedTasks.forEach((task) => {
          aiToolsMap[String(task.aiToolsId)] = {
            batchNodes: task.batchNodes,
            gridSize: gridSize
          };
          
          task.batchNodes.forEach((shotFrameNode, idx) => {
            const gridIndex = idx + 1;
            const gridImageNodeId = createImageNode({
              x: shotFrameNode.x + 380,
              y: shotFrameNode.y
            });
            
            const gridImageNode = state.nodes.find(n => n.id === gridImageNodeId);
            if(gridImageNode) {
              gridImageNode.data.name = `分镜图 ${gridIndex}/${gridSize}`;
              gridImageNode.data.project_id = task.aiToolsId;
              gridImageNode.data.aiToolsId = task.aiToolsId;
              gridImageNode.data.gridIndex = gridIndex;
              gridImageNode.data.gridSize = gridSize;
              gridImageNode.data.shotFrameNodeId = shotFrameNode.id;
              gridImageNode.data.isSplit = false;
              gridImageNode.data.status = 'pending';
              gridImageNode.title = gridImageNode.data.name;
              
              const nodeEl = canvasEl.querySelector(`.node[data-node-id="${gridImageNodeId}"]`);
              if(nodeEl) {
                const titleEl = nodeEl.querySelector('.node-title');
                if(titleEl) titleEl.textContent = gridImageNode.title;
              }
              
              const exists = state.connections.some(c => c.from === shotFrameNode.id && c.to === gridImageNodeId);
              if(!exists){
                state.connections.push({
                  id: state.nextConnId++,
                  from: shotFrameNode.id,
                  to: gridImageNodeId
                });
              }
            }
          });
        });
        
        renderConnections();
        renderImageConnections();
        renderFirstFrameConnections();
        renderVideoConnections();
        renderMinimap();
        
        if(!state.aiToolsMap) {
          state.aiToolsMap = {};
        }
        Object.assign(state.aiToolsMap, aiToolsMap);
        
        gridStatusEl.style.color = '#22c55e';
        gridStatusEl.textContent = `已提交${imageCount}张宫格图片生成任务，等待AI生成...`;
        showToast(`已提交${imageCount}张宫格图片生成任务`, 'success');
        
        try{ autoSaveWorkflow(); } catch(e){}
        
      } catch(error) {
        console.error('[宫格生图] 错误:', error);
        gridStatusEl.style.color = '#ef4444';
        gridStatusEl.textContent = `生成失败: ${error.message}`;
        showToast(`宫格生图失败: ${error.message}`, 'error');
      }
    }

    // 生成分镜图节点 - 独立分镜模式
    function generateShotFramesIndependent(shotGroupNodeId, shotGroupNode){
      const shots = shotGroupNode.data.shots || [];
      if(shots.length === 0){
        showToast('分镜组中没有分镜数据', 'warning');
        return;
      }

      // 获取已存在的分镜节点（通过连接关系查找）
      const existingConnections = state.connections.filter(c => c.from === shotGroupNodeId);
      const existingShotIds = new Set();
      let maxExistingY = shotGroupNode.y;
      
      existingConnections.forEach(conn => {
        const targetNode = state.nodes.find(n => n.id === conn.to);
        if(targetNode && targetNode.type === 'shot_frame'){
          // 收集已存在的 shotId
          const shotId = targetNode.data.shotId || (targetNode.data.shotJson && targetNode.data.shotJson.shot_id);
          if(shotId){
            existingShotIds.add(shotId);
          }
          // 记录最大的 Y 坐标
          if(targetNode.y > maxExistingY){
            maxExistingY = targetNode.y;
          }
        }
      });

      const createdNodeIds = [];
      const offsetX = 400;
      // 新节点从已有节点下方开始排列
      let nextY = existingShotIds.size > 0 ? maxExistingY + 700 : shotGroupNode.y;
      let skippedCount = 0;
      
      // 从第一个镜头获取场景信息（所有镜头使用同一个场景）
      const firstShot = shots[0];
      const locationInfo = [];
      if(firstShot.db_location_id && firstShot.location_name){
        locationInfo.push({
          name: firstShot.location_name,
          pic: firstShot.db_location_pic,
          id: firstShot.db_location_id
        });
      }

      shots.forEach((shot) => {
        // 检查该分镜是否已有对应的分镜节点
        if(existingShotIds.has(shot.shot_id)){
          skippedCount++;
          return;
        }
        
        // 为每个镜头添加场景信息和scriptData
        const shotDataWithLocation = {
          ...shot,
          allLocationInfo: locationInfo,
          scriptData: shotGroupNode.data.scriptData  // 传递scriptData以便获取道具信息
        };
        
        const shotFrameNodeId = createShotFrameNode({
          x: shotGroupNode.x + offsetX,
          y: nextY,
          shotData: shotDataWithLocation,
          model: shotGroupNode.data.model
        });
        createdNodeIds.push(shotFrameNodeId);
        nextY += 700;

        // 创建从分镜组到分镜图节点的连接
        state.connections.push({
          id: state.nextConnId++,
          from: shotGroupNodeId,
          to: shotFrameNodeId
        });
      });

      renderConnections();
      renderImageConnections();
      renderFirstFrameConnections();
      renderVideoConnections();
      try{ autoSaveWorkflow(); } catch(e){}
      
      // 显示合理的提示信息
      if(createdNodeIds.length === 0 && skippedCount > 0){
        showToast(`所有 ${skippedCount} 个分镜已存在对应节点，无需新增`, 'info');
      } else if(skippedCount > 0){
        showToast(`已生成 ${createdNodeIds.length} 个独立分镜节点，跳过 ${skippedCount} 个已存在的分镜`, 'success');
      } else {
        showToast(`已生成 ${createdNodeIds.length} 个独立分镜节点`, 'success');
      }
    }

    // 生成分镜图节点 - 独立分镜模式（异步版本，用于自动批量生成）
    async function generateShotFramesIndependentAsync(shotGroupNodeId, shotGroupNode){
      const shots = shotGroupNode.data.shots || [];
      if(shots.length === 0){
        console.log('[宫格生图] 分镜组没有分镜数据');
        return [];
      }

      // 按 shot_number 排序，确保分镜按顺序创建
      shots.sort((a, b) => (a.shot_number || 0) - (b.shot_number || 0));

      // 获取已存在的分镜节点（通过连接关系查找）
      // 注意：只查找真实存在的节点，忽略已删除节点的连接
      const existingConnections = state.connections.filter(c => c.from === shotGroupNodeId);
      const existingShotIds = new Set();
      let maxExistingY = shotGroupNode.y;
      
      console.log(`[宫格生图] 分镜组 ${shotGroupNodeId} 有 ${existingConnections.length} 个连接`);
      
      existingConnections.forEach(conn => {
        const targetNode = state.nodes.find(n => n.id === conn.to);
        if(targetNode && targetNode.type === 'shot_frame'){
          const shotId = targetNode.data.shotId || (targetNode.data.shotJson && targetNode.data.shotJson.shot_id);
          if(shotId){
            existingShotIds.add(shotId);
            console.log(`[宫格生图] 找到已存在的分镜节点: ${shotId}`);
          }
          if(targetNode.y > maxExistingY){
            maxExistingY = targetNode.y;
          }
        } else if(!targetNode) {
          console.log(`[宫格生图] 连接 ${conn.id} 指向的节点 ${conn.to} 不存在（可能已删除）`);
        }
      });
      
      console.log(`[宫格生图] 已存在的分镜ID: ${Array.from(existingShotIds).join(', ')}`);
      console.log(`[宫格生图] 需要生成的分镜总数: ${shots.length}`);

      const createdNodeIds = [];
      const offsetX = 400;
      let nextY = existingShotIds.size > 0 ? maxExistingY + 700 : shotGroupNode.y;
      
      const firstShot = shots[0];
      const locationInfo = [];
      if(firstShot.db_location_id && firstShot.location_name){
        locationInfo.push({
          name: firstShot.location_name,
          pic: firstShot.db_location_pic,
          id: firstShot.db_location_id
        });
      }

      let skippedCount = 0;
      shots.forEach((shot) => {
        if(existingShotIds.has(shot.shot_id)){
          console.log(`[宫格生图] 跳过已存在的分镜: ${shot.shot_id}`);
          skippedCount++;
          return;
        }
        
        console.log(`[宫格生图] 创建新分镜节点: ${shot.shot_id}`);
        
        const shotDataWithLocation = {
          ...shot,
          allLocationInfo: locationInfo,
          scriptData: shotGroupNode.data.scriptData
        };
        
        const shotFrameNodeId = createShotFrameNode({
          x: shotGroupNode.x + offsetX,
          y: nextY,
          shotData: shotDataWithLocation,
          model: shotGroupNode.data.model
        });
        createdNodeIds.push(shotFrameNodeId);
        nextY += 700;

        state.connections.push({
          id: state.nextConnId++,
          from: shotGroupNodeId,
          to: shotFrameNodeId
        });
      });
      
      console.log(`[宫格生图] 生成完成 - 新建: ${createdNodeIds.length}, 跳过: ${skippedCount}`);

      renderConnections();
      renderImageConnections();
      renderFirstFrameConnections();
      renderVideoConnections();
      try{ autoSaveWorkflow(); } catch(e){}
      
      // 返回创建的节点ID数组（供宫格生图等功能使用）
      return createdNodeIds;
    }

    // 将视频提示词JSON转换为可读文本格式
    function convertVideoPromptToText(jsonString){
      try {
        const data = JSON.parse(jsonString);
        
        let text = '';
        if(data.duration) text += `时长：${data.duration}秒\n`;
        if(data.time_of_day) text += `时间：${data.time_of_day}\n`;
        if(data.weather) text += `天气：${data.weather}\n`;
        if(data.location_name) text += `场景：${data.location_name}\n`;
        if(data.shot_type) text += `镜头类型：${data.shot_type}\n`;
        if(data.camera_movement) text += `运镜：${data.camera_movement}\n`;
        if(data.description) text += `描述：${data.description}\n`;
        if(data.scene_detail) text += `场景细节：${data.scene_detail}\n`;
        if(data.action) text += `动作：${data.action}\n`;
        if(data.mood) text += `情绪：${data.mood}\n`;
        if(data.dialogue && Array.isArray(data.dialogue) && data.dialogue.length > 0){
          text += `对话：${data.dialogue.map(d => `${d.character_name}: ${d.text}`).join('; ')}\n`;
        }
        if(data.audio_notes) text += `音频备注：${data.audio_notes}\n`;
        if(data.environment_sound) text += `环境音：${data.environment_sound}\n`;
        if(data.background_music) text += `背景音乐：${data.background_music}\n`;
        return text;
      } catch(e){
        console.error('Failed to convert video prompt to text:', e);
        return jsonString;
      }
    }

    // 分镜图节点
    function createShotFrameNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = opts && typeof opts.y === 'number' ? opts.y : viewportPos.y;
      const shotData = opts && opts.shotData ? opts.shotData : {};
      const inheritedModel = opts && opts.model ? opts.model : 'gemini-2.5-pro-image-preview';
      
      const shotTitle = shotData.shot_id || shotData.shot_number ? `镜头${shotData.shot_number || ''}` : '分镜图';
      
      // 构建图片提示词，包含时间和天气信息
      let imagePrompt = shotData.opening_frame_description || '';
      const timeOfDay = shotData.time_of_day;
      const weather = shotData.weather;
      
      if(timeOfDay || weather){
        const contextInfo = [];
        if(timeOfDay) contextInfo.push(`时间：${timeOfDay}`);
        if(weather) contextInfo.push(`天气：${weather}`);
        
        if(imagePrompt){
          imagePrompt = `${contextInfo.join('，')}。${imagePrompt}`;
        } else {
          imagePrompt = contextInfo.join('，');
        }
      }
      
      // 构建视频提示词JSON（用于API调用）
      const filteredShotData = {...shotData};
      delete filteredShotData.shot_id;
      delete filteredShotData.shot_number;
      delete filteredShotData.location_id;
      delete filteredShotData.opening_frame_description;
      delete filteredShotData.allCharacterNames;
      delete filteredShotData.allLocationInfo;
      delete filteredShotData.arrangement;
      delete filteredShotData.isMerged;
      delete filteredShotData.shots;
      delete filteredShotData.db_location_pic;
      delete filteredShotData.characters_present;
      delete filteredShotData.db_location_id;
      
      const videoPromptJson = JSON.stringify(filteredShotData, null, 2);
      
      // 将JSON转换为可读文本格式
      const videoPromptText = convertVideoPromptToText(videoPromptJson);
      
      const node = {
        id,
        type: 'shot_frame',
        title: shotTitle,
        x,
        y,
        data: {
          shotId: shotData.shot_id || '',
          imagePrompt: imagePrompt,
          videoPrompt: videoPromptJson,
          videoPromptText: videoPromptText,
          duration: shotData.duration || 0,
          shotType: shotData.shot_type || '',
          cameraMovement: shotData.camera_movement || '',
          description: shotData.description || '',
          generatedImage: null,
          imageUrl: '',
          shotJson: shotData,
          model: inheritedModel,
          drawCount: 1,
          previewImageUrl: '',
          videoDrawCount: 1,
          videoDuration: 5,
          videoModel: 'wan22',
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';
      el.style.width = '340px';

      el.innerHTML = `
        <div class="port input" title="输入（连接分镜组节点）"></div>
        <div class="port output" title="输出"></div>
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>分镜: ${node.title}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field field-always-visible">
            <div class="gen-meta">${escapeHtml(node.data.description)}</div>
            <div class="gen-meta" style="margin-top: 4px;">时长: ${node.data.duration}秒 | ${escapeHtml(node.data.shotType)} | ${escapeHtml(node.data.cameraMovement)}</div>
          </div>
          <div class="field field-always-visible shot-frame-preview-field" style="position: relative;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <div class="label" style="margin: 0;">视频首帧</div>
              <div class="gen-container shot-frame-image-selector-container" style="display: none;">
                <button class="mini-btn shot-frame-image-selector-btn" type="button" style="font-size: 11px; padding: 4px 8px; background: white; color: #333; border: 1px solid #ddd;">选择图片</button>
                <button class="gen-btn-caret" type="button" aria-label="选择图片" style="font-size: 11px; padding: 4px 6px;">▾</button>
                <div class="gen-menu shot-frame-image-menu"></div>
              </div>
            </div>
            <div class="port first-frame-port" title="连接图片节点（视频首帧）"></div>
            <img class="shot-frame-preview-image" src="${node.data.previewImageUrl || ''}" style="width: 100%; border-radius: 6px; cursor: pointer; display: ${node.data.previewImageUrl ? 'block' : 'none'};" />
          </div>
          <div class="field field-always-visible shot-frame-image-field" style="display:${node.data.imageUrl ? 'block' : 'none'};">
            <img class="shot-frame-image" src="${node.data.imageUrl}" style="width: 100%; border-radius: 6px; cursor: pointer;" />
          </div>
          <div class="field field-collapsible">
            <div class="shot-ref-section" style="position: relative;">
              <div class="shot-ref-row">
                <span class="shot-ref-label">场景</span>
                <div class="shot-ref-tags shot-ref-scene-tags"></div>
              </div>
              <div class="shot-ref-row">
                <span class="shot-ref-label">道具</span>
                <div class="shot-ref-tags shot-ref-prop-tags"></div>
              </div>
              <div class="shot-ref-row">
                <span class="shot-ref-label">角色</span>
                <div class="shot-ref-tags shot-ref-char-tags"></div>
              </div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <div class="label" style="margin: 0;">图片提示词</div>
              <span style="font-size: 10px; color: #9ca3af;">点击编辑 | 按 / 选择角色</span>
            </div>
            <textarea class="shot-frame-image-prompt" rows="3" readonly style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 6px; font-size: 12px; resize: none; cursor: pointer; background: #fafafa;">${escapeHtml(node.data.imagePrompt)}</textarea>
          </div>
          <div class="field field-collapsible">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <div class="label" style="margin: 0;">视频提示词</div>
              <button class="mini-btn secondary reduce-violation-btn" type="button" style="font-size: 11px; padding: 4px 8px;">视频生成失败，请点此次按钮</button>
            </div>
            <textarea class="shot-frame-video-prompt" rows="3" readonly style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 6px; font-size: 12px; resize: none; cursor: pointer; background: #fafafa;">${escapeHtml(node.data.videoPromptText || node.data.videoPrompt)}</textarea>
          </div>
          <div class="field field-collapsible">
            <div class="label">分镜模型</div>
            <select class="shot-frame-model">
              <option value="gemini-2.5-pro-image-preview">标准版 (2算力)</option>
              <option value="gemini-3-pro-image-preview">加强版 (6算力)</option>
            </select>
          </div>
          <div class="field field-collapsible">
            <div class="btn-row" style="display: flex; gap: 8px; justify-content: space-between; align-items: center;">
              <div class="gen-container">
                <button class="gen-btn gen-btn-main shot-frame-generate-btn" type="button">生成分镜图</button>
                <button class="gen-btn gen-btn-caret shot-frame-caret" type="button" aria-label="选择抽卡次数">▾</button>
                <div class="gen-menu shot-frame-menu">
                  <div class="gen-item" data-count="1">X1</div>
                  <div class="gen-item" data-count="2">X2</div>
                  <div class="gen-item" data-count="3">X3</div>
                  <div class="gen-item" data-count="4">X4</div>
                </div>
              </div>
              <button class="gen-btn shot-frame-generate-dialogue-btn" type="button" style="background: #22c55e; color: white;" disabled>生成对话音频</button>
            </div>
            <div class="gen-meta shot-frame-draw-count-label"></div>
          </div>
          <div class="field field-collapsible">
            <div class="label">视频模型</div>
            <select class="shot-frame-video-model">
              <option value="wan22" selected>Wan2.2</option>
              <option value="sora2">Sora2</option>
              <option value="ltx2">LTX2.0</option>
              <option value="kling">可灵</option>
              <option value="vidu">Vidu</option>
              <option value="veo3">VEO3.1</option>
            </select>
          </div>
          <div class="field field-collapsible">
            <div class="label">视频时长</div>
            <select class="shot-frame-video-duration">
              <option value="5" selected>5秒</option>
              <option value="10">10秒</option>
            </select>
          </div>
          <div class="field field-collapsible">
            <div class="btn-row" style="display: flex; gap: 8px; justify-content: flex-start;">
              <div class="gen-container">
                <button class="gen-btn gen-btn-main shot-frame-generate-video-btn" type="button" style="background: #22c55e; color: white;">生成视频</button>
                <button class="gen-btn gen-btn-caret shot-frame-video-caret" type="button" aria-label="选择抽卡次数">▾</button>
                <div class="gen-menu shot-frame-video-menu">
                  <div class="gen-item" data-count="1">X1</div>
                  <div class="gen-item" data-count="2">X2</div>
                  <div class="gen-item" data-count="3">X3</div>
                  <div class="gen-item" data-count="4">X4</div>
                </div>
              </div>
            </div>
            <div class="gen-meta shot-frame-video-draw-count-label"></div>
            <div class="shot-frame-computing-power" style="margin-top: 6px; padding: 6px; border-radius: 6px;">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #9ca3af; font-size: 11px;">算力消耗：</span>
                <span class="shot-frame-computing-power-value" style="color: #60a5fa; font-weight: bold; font-size: 12px;">0 算力</span>
              </div>
              <div class="shot-frame-computing-power-detail" style="margin-top: 2px; font-size: 10px; color: #6b7280;">
                单个 0 算力 × 1 个 = 0 算力
              </div>
            </div>
            <div class="shot-frame-video-error" style="display: none; margin-top: 8px; padding: 8px; background: #fee; border: 1px solid #fcc; border-radius: 6px; color: #c33; font-size: 12px; word-break: break-word;"></div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const imagePromptEl = el.querySelector('.shot-frame-image-prompt');
      const videoPromptEl = el.querySelector('.shot-frame-video-prompt');
      const generateBtn = el.querySelector('.shot-frame-generate-btn');
      const generateDialogueBtn = el.querySelector('.shot-frame-generate-dialogue-btn');
      const imageEl = el.querySelector('.shot-frame-image');
      const imageFieldEl = el.querySelector('.shot-frame-image-field');
      const inputPort = el.querySelector('.port.input');
      const outputPort = el.querySelector('.port.output');
      const genCaret = el.querySelector('.shot-frame-caret');
      const genMenu = el.querySelector('.shot-frame-menu');
      const drawCountLabel = el.querySelector('.shot-frame-draw-count-label');
      const modelEl = el.querySelector('.shot-frame-model');
      const previewFieldEl = el.querySelector('.shot-frame-preview-field');
      const previewImageEl = el.querySelector('.shot-frame-preview-image');
      const generateVideoBtn = el.querySelector('.shot-frame-generate-video-btn');
      const videoCaret = el.querySelector('.shot-frame-video-caret');
      const videoMenu = el.querySelector('.shot-frame-video-menu');
      const videoDrawCountLabel = el.querySelector('.shot-frame-video-draw-count-label');
      const imageSelectorContainer = el.querySelector('.shot-frame-image-selector-container');
      const imageSelectorBtn = el.querySelector('.shot-frame-image-selector-btn');
      const imageSelectorCaret = imageSelectorContainer ? imageSelectorContainer.querySelector('.gen-btn-caret') : null;
      const imageMenu = el.querySelector('.shot-frame-image-menu');
      const firstFramePort = el.querySelector('.first-frame-port');
      const videoDurationEl = el.querySelector('.shot-frame-video-duration');
      const videoModelEl = el.querySelector('.shot-frame-video-model');
      const computingPowerValue = el.querySelector('.shot-frame-computing-power-value');
      const computingPowerDetail = el.querySelector('.shot-frame-computing-power-detail');
      const refSectionEl = el.querySelector('.shot-ref-section');
      const sceneTagsEl = el.querySelector('.shot-ref-scene-tags');
      const propTagsEl = el.querySelector('.shot-ref-prop-tags');
      const charTagsEl = el.querySelector('.shot-ref-tags.shot-ref-char-tags');

      // ============ 引用匹配与显示逻辑 ============

      // 初始化引用数据（如果没有从保存数据恢复的话）
      if(!node.data.refScene) {
        // 从 shotJson.allLocationInfo 匹配场景
        const locInfo = shotData.allLocationInfo;
        if(Array.isArray(locInfo) && locInfo.length > 0) {
          node.data.refScene = { id: locInfo[0].id, name: locInfo[0].name, pic: locInfo[0].pic };
        } else if(locInfo && typeof locInfo === 'object' && !Array.isArray(locInfo) && locInfo.name) {
          node.data.refScene = { id: locInfo.id, name: locInfo.name, pic: locInfo.pic };
        } else {
          node.data.refScene = null;
        }
      }

      if(!node.data.refProps) {
        // 从 shotJson.props_present + shotJson.scriptData.props 匹配脚本道具
        const propsPresent = shotData.props_present || [];
        const scriptProps = (shotData.scriptData && shotData.scriptData.props) ? shotData.scriptData.props : [];
        node.data.refProps = [];
        propsPresent.forEach(propId => {
          const prop = scriptProps.find(p => p.id === propId);
          if(prop) {
            node.data.refProps.push({ id: prop.id, name: prop.name, props_db_id: prop.props_db_id || null });
          }
        });
        // 合并用户在分镜组中手动添加的道具 (shot.props)
        const userProps = shotData.props || [];
        userProps.forEach(up => {
          const alreadyExists = node.data.refProps.some(p => p.props_db_id === up.id || p.name === up.name);
          if(!alreadyExists) {
            node.data.refProps.push({ id: up.id, name: up.name, props_db_id: up.id || null });
          }
        });
      }

      if(!node.data.refCharacters) {
        node.data.refCharacters = [];
      }

      // 从图片提示词中提取角色名
      function extractCharacterNames(prompt) {
        const pattern = /【【([^】]+)】】/g;
        const names = [];
        let m;
        while((m = pattern.exec(prompt)) !== null) {
          const name = m[1].trim();
          if(name && !names.includes(name)) names.push(name);
        }
        return names;
      }

      // 初始匹配角色
      node.data.refCharacters = extractCharacterNames(node.data.imagePrompt || '');

      // 获取所有可用场景列表（从 state.worldLocations 获取）
      function getAvailableLocations() {
        return state.worldLocations || [];
      }

      // 获取所有可用道具列表（从 state.worldProps 获取）
      function getAvailableProps() {
        return state.worldProps || [];
      }

      // 关闭所有引用下拉菜单
      function closeRefDropdowns() {
        const dropdowns = refSectionEl.querySelectorAll('.shot-ref-dropdown');
        dropdowns.forEach(d => d.remove());
      }

      // 渲染场景标签
      function renderSceneTags() {
        sceneTagsEl.innerHTML = '';
        if(node.data.refScene && node.data.refScene.name) {
          const tag = document.createElement('span');
          tag.className = 'shot-ref-tag scene';
          tag.title = node.data.refScene.name;
          tag.innerHTML = `${escapeHtml(node.data.refScene.name)}<span class="ref-tag-remove" title="移除">×</span>`;
          tag.querySelector('.ref-tag-remove').addEventListener('click', (e) => {
            e.stopPropagation();
            node.data.refScene = null;
            renderSceneTags();
            try{ autoSaveWorkflow(); } catch(e){}
          });
          tag.addEventListener('click', (e) => {
            e.stopPropagation();
            showSceneDropdown();
          });
          sceneTagsEl.appendChild(tag);
        } else {
          const addBtn = document.createElement('button');
          addBtn.className = 'shot-ref-add-btn';
          addBtn.title = '选择场景';
          addBtn.textContent = '+';
          addBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            showSceneDropdown();
          });
          sceneTagsEl.appendChild(addBtn);
        }
      }

      // 显示场景选择下拉
      function showSceneDropdown() {
        closeRefDropdowns();
        const locations = getAvailableLocations();
        if(locations.length === 0) {
          showToast('没有可用的场景数据', 'info');
          return;
        }
        const dropdown = document.createElement('div');
        dropdown.className = 'shot-ref-dropdown';
        locations.forEach(loc => {
          const item = document.createElement('div');
          item.className = 'shot-ref-dropdown-item';
          if(node.data.refScene && node.data.refScene.name === loc.name) {
            item.classList.add('selected');
          }
          item.textContent = loc.name;
          item.addEventListener('click', (e) => {
            e.stopPropagation();
            node.data.refScene = { id: loc.id, name: loc.name, pic: loc.reference_image || '' };
            renderSceneTags();
            closeRefDropdowns();
            try{ autoSaveWorkflow(); } catch(e){}
          });
          dropdown.appendChild(item);
        });
        refSectionEl.appendChild(dropdown);

        // 点击外部关闭
        const closeHandler = (e) => {
          if(!dropdown.contains(e.target)) {
            dropdown.remove();
            document.removeEventListener('click', closeHandler, true);
          }
        };
        setTimeout(() => document.addEventListener('click', closeHandler, true), 0);
      }

      // 渲染道具标签
      function renderPropTags() {
        propTagsEl.innerHTML = '';
        // 过滤掉 state.worldProps 中不存在的道具
        const worldProps = state.worldProps || [];
        if(worldProps.length > 0) {
          node.data.refProps = (node.data.refProps || []).filter(p => {
            const dbId = p.props_db_id || p.id;
            return worldProps.some(wp => wp.id === dbId || wp.name === p.name);
          });
        }
        (node.data.refProps || []).forEach((prop, idx) => {
          const tag = document.createElement('span');
          tag.className = 'shot-ref-tag prop';
          tag.title = prop.name;
          tag.innerHTML = `${escapeHtml(prop.name)}<span class="ref-tag-remove" title="移除">×</span>`;
          tag.querySelector('.ref-tag-remove').addEventListener('click', (e) => {
            e.stopPropagation();
            node.data.refProps.splice(idx, 1);
            renderPropTags();
            try{ autoSaveWorkflow(); } catch(e){}
          });
          propTagsEl.appendChild(tag);
        });
        // 添加按钮
        const addBtn = document.createElement('button');
        addBtn.className = 'shot-ref-add-btn';
        addBtn.title = '添加道具';
        addBtn.textContent = '+';
        addBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          showPropDropdown();
        });
        propTagsEl.appendChild(addBtn);
      }

      // 显示道具选择下拉（多选）
      function showPropDropdown() {
        closeRefDropdowns();
        const allProps = getAvailableProps();
        if(allProps.length === 0) {
          showToast('没有可用的道具数据', 'info');
          return;
        }
        const selectedIds = (node.data.refProps || []).map(p => p.id);
        const dropdown = document.createElement('div');
        dropdown.className = 'shot-ref-dropdown';
        allProps.forEach(prop => {
          const isSelected = selectedIds.includes(prop.id);
          const item = document.createElement('div');
          item.className = 'shot-ref-dropdown-item' + (isSelected ? ' selected' : '');
          item.textContent = (isSelected ? '✓ ' : '') + prop.name;
          item.addEventListener('click', (e) => {
            e.stopPropagation();
            if(isSelected) {
              // 移除
              node.data.refProps = node.data.refProps.filter(p => p.id !== prop.id);
            } else {
              // 添加
              node.data.refProps.push({ id: prop.id, name: prop.name, props_db_id: prop.id, reference_image: prop.reference_image || '' });
            }
            renderPropTags();
            closeRefDropdowns();
            try{ autoSaveWorkflow(); } catch(e){}
          });
          dropdown.appendChild(item);
        });
        refSectionEl.appendChild(dropdown);

        const closeHandler = (e) => {
          if(!dropdown.contains(e.target)) {
            dropdown.remove();
            document.removeEventListener('click', closeHandler, true);
          }
        };
        setTimeout(() => document.addEventListener('click', closeHandler, true), 0);
      }

      // 渲染角色标签（只读，自动从提示词匹配，仅显示 state.worldCharacters 中存在的角色）
      function renderCharTags() {
        charTagsEl.innerHTML = '';
        const chars = node.data.refCharacters || [];
        // 过滤：只保留在 state.worldCharacters 中真正存在的角色
        const worldChars = state.worldCharacters || [];
        const validChars = chars.filter(name => worldChars.some(wc => wc.name === name));
        if(validChars.length === 0) {
          const empty = document.createElement('span');
          empty.className = 'shot-ref-tag empty';
          empty.textContent = '无（在提示词中用【【角色名】】引用）';
          charTagsEl.appendChild(empty);
        } else {
          validChars.forEach(name => {
            const wc = worldChars.find(c => c.name === name);
            const hasImage = wc && wc.reference_image;
            const tag = document.createElement('span');
            tag.className = 'shot-ref-tag character';
            if(!hasImage) {
              tag.style.cssText = 'border-color: #ef4444; color: #ef4444; background: #fef2f2;';
              tag.title = `${name}（该角色没有参考图片）`;
              tag.textContent = name + ' ⚠';
            } else {
              tag.title = name;
              tag.textContent = name;
            }
            charTagsEl.appendChild(tag);
          });
        }
      }

      // 触发全部引用匹配并渲染
      function updateShotReferences() {
        // 重新匹配角色
        node.data.refCharacters = extractCharacterNames(node.data.imagePrompt || '');
        renderSceneTags();
        renderPropTags();
        renderCharTags();
      }

      // 暴露更新引用的方法供外部调用
      node.updateReferences = updateShotReferences;

      // 初始渲染
      updateShotReferences();

      // ============ 引用匹配与显示逻辑结束 ============

      // 设置模型选择器的初始值
      if(modelEl) modelEl.value = node.data.model;
      
      // 设置视频模型选择器的初始值
      if(!node.data.videoModel){
        node.data.videoModel = 'wan22';
      }
      if(videoModelEl) videoModelEl.value = node.data.videoModel;
      
      // 根据模型更新时长选项（使用全局配置）
      function updateVideoDurationOptions(videoModel) {
        const currentDuration = node.data.videoDuration;  // 使用 node.data 中的值而非 DOM
        videoDurationEl.innerHTML = '';
        
        // 从全局配置获取时长选项
        const durationConfig = getVideoModelDurationOptions();
        let durationOptions = durationConfig[videoModel];
        
        // 如果配置未加载或不存在，使用默认值
        if(!durationOptions || durationOptions.length === 0) {
          const defaultOptions = {
            'ltx2': [5, 8, 10],
            'wan22': [5, 10],
            'kling': [5, 10],
            'vidu': [5, 8],
            'veo3': [8],
            'sora2': [10, 15]
          };
          durationOptions = defaultOptions[videoModel] || [5, 10];
        }
        
        // 生成选项
        durationOptions.forEach(d => {
          const opt = document.createElement('option');
          opt.value = d;
          opt.textContent = `${d}秒`;
          videoDurationEl.appendChild(opt);
        });
        
        // 检查当前时长是否在新选项中
        const durationStrings = durationOptions.map(d => String(d));
        if(durationStrings.includes(String(currentDuration))) {
          videoDurationEl.value = currentDuration;
        } else {
          // 使用第一个可用选项
          const firstOption = durationOptions[0];
          videoDurationEl.value = firstOption;
          node.data.videoDuration = firstOption;
        }
      }
      
      // 初始化时根据模型设置时长选项
      updateVideoDurationOptions(node.data.videoModel);
      
      // 设置视频时长选择器的初始值
      if(!node.data.videoDuration){
        node.data.videoDuration = 5;
      }
      if(videoDurationEl) videoDurationEl.value = node.data.videoDuration;
      
      // 计算视频生成算力消耗
      function calculateVideoComputingPower() {
        const config = getTaskComputingPowerConfig();
        if(!config || Object.keys(config).length === 0) {
          return 0;
        }
        
        let power = 0;
        const videoModel = node.data.videoModel || 'sora2';
        const duration = node.data.videoDuration || 10;
        
        if(videoModel === 'sora2') {
          power = config[3] || 0;  // type=3: Sora2 图生视频
        } else if(videoModel === 'ltx2') {
          power = config[10] || 0;  // type=10: LTX2.0 图生视频
        } else if(videoModel === 'wan22') {
          // type=11: Wan2.2根据时长区分算力
          const wan22Power = config[11];
          if(typeof wan22Power === 'object') {
            power = wan22Power[duration] || wan22Power[5] || 0;
          } else {
            power = wan22Power || 0;
          }
        } else if(videoModel === 'kling') {
          // type=12: 可灵根据时长区分算力
          const klingPower = config[12];
          if(typeof klingPower === 'object') {
            power = klingPower[duration] || klingPower[5] || 0;
          } else {
            power = klingPower || 0;
          }
        } else if(videoModel === 'vidu') {
          // type=14: Vidu根据时长区分算力
          const viduPower = config[14];
          if(typeof viduPower === 'object') {
            power = viduPower[duration] || viduPower[5] || 0;
          } else {
            power = viduPower || 0;
          }
        } else if(videoModel === 'veo3') {
          // type=15: VEO3固定算力
          power = config[15] || 0;
        }
        
        return power;
      }
      
      // 更新视频算力显示
      function updateVideoComputingPowerDisplay() {
        const singlePower = calculateVideoComputingPower();
        const count = node.data.videoDrawCount || 1;
        const totalPower = singlePower * count;
        
        if(computingPowerValue) {
          computingPowerValue.textContent = `${totalPower} 算力`;
        }
        if(computingPowerDetail) {
          computingPowerDetail.textContent = `单个 ${singlePower} 算力 × ${count} 个 = ${totalPower} 算力`;
        }
      }

      // 初始化抽卡次数
      if(!node.data.drawCount){
        node.data.drawCount = 1;
      }
      if(!node.data.videoDrawCount){
        node.data.videoDrawCount = 1;
      }

      function updateDrawCountLabel(){
        drawCountLabel.textContent = `抽卡次数：X${node.data.drawCount}`;
      }
      updateDrawCountLabel();

      function updateVideoDrawCountLabel(){
        videoDrawCountLabel.textContent = `抽卡次数：X${node.data.videoDrawCount}`;
        // 同时更新算力显示
        updateVideoComputingPowerDisplay();
      }
      updateVideoDrawCountLabel();
      
      // 初始化算力显示
      updateVideoComputingPowerDisplay();

      // 获取所有连接的图片节点（包括子图片和嵌套子图片，递归查找）
      function getConnectedImageNodes(){
        const visited = new Set();
        const result = [];
        
        // 从指定节点出发，查找所有相连的图片节点
        function collectImageNodes(nodeId) {
          if(visited.has(nodeId)) return;
          visited.add(nodeId);
          
          // 正向连接（from -> to）
          const outNodes = state.connections
            .filter(c => c.from === nodeId)
            .map(c => state.nodes.find(n => n.id === c.to))
            .filter(Boolean);
          
          // 反向连接（to <- from）
          const inNodes = state.connections
            .filter(c => c.to === nodeId)
            .map(c => state.nodes.find(n => n.id === c.from))
            .filter(Boolean);
          
          // 首帧连接
          const ffNodes = state.firstFrameConnections
            .filter(c => c.to === nodeId)
            .map(c => state.nodes.find(n => n.id === c.from))
            .filter(Boolean);
          
          const allConnected = [...outNodes, ...inNodes, ...ffNodes];
          
          for(const n of allConnected) {
            if(n.type === 'image' && n.data.url && !visited.has(n.id)) {
              result.push(n);
              // 递归查找该图片节点的子图片
              collectImageNodes(n.id);
            }
          }
        }
        
        collectImageNodes(id);
        return result;
      }

      // 更新图片选择菜单
      function updateImageSelectionMenu(){
        const connectedImageNodes = getConnectedImageNodes();
        
        if(connectedImageNodes.length > 0 && imageMenu){
          // 有图片节点时显示选择按钮
          imageSelectorContainer.style.display = 'flex';
          
          // 清空并重新填充菜单
          imageMenu.innerHTML = '';
          
          // 创建悬浮缩略图容器（共用一个）
          let thumbTooltip = imageMenu.parentElement.querySelector('.image-thumb-tooltip');
          if(!thumbTooltip){
            thumbTooltip = document.createElement('div');
            thumbTooltip.className = 'image-thumb-tooltip';
            thumbTooltip.style.cssText = 'position: absolute; left: calc(100% + 8px); top: 0; width: 120px; height: 120px; border-radius: 6px; border: 1px solid #ddd; background: #fff; box-shadow: 0 4px 12px rgba(0,0,0,0.15); overflow: hidden; display: none; z-index: 10001; pointer-events: none;';
            const thumbImg = document.createElement('img');
            thumbImg.style.cssText = 'width: 100%; height: 100%; object-fit: cover;';
            thumbTooltip.appendChild(thumbImg);
            imageMenu.parentElement.style.position = 'relative';
            imageMenu.parentElement.appendChild(thumbTooltip);
          }
          const thumbImg = thumbTooltip.querySelector('img');
          
          connectedImageNodes.forEach((imgNode, index) => {
            const menuItem = document.createElement('div');
            menuItem.className = 'gen-item';
            menuItem.style.cssText = 'position: relative; cursor: pointer;';
            menuItem.textContent = imgNode.title || imgNode.data.name || `图片${index + 1}`;
            menuItem.dataset.nodeId = imgNode.id;
            imageMenu.appendChild(menuItem);
            
            // hover 时显示缩略图
            menuItem.addEventListener('mouseenter', () => {
              thumbImg.src = proxyImageUrl(imgNode.data.url);
              thumbTooltip.style.display = 'block';
              // 计算 tooltip 位置跟随菜单项
              const itemRect = menuItem.getBoundingClientRect();
              const parentRect = imageMenu.parentElement.getBoundingClientRect();
              thumbTooltip.style.top = (itemRect.top - parentRect.top) + 'px';
            });
            menuItem.addEventListener('mouseleave', () => {
              thumbTooltip.style.display = 'none';
            });
            
            menuItem.addEventListener('click', (e) => {
              e.stopPropagation();
              node.data.previewImageUrl = imgNode.data.url;
              previewImageEl.src = proxyImageUrl(imgNode.data.url);
              previewImageEl.style.display = 'block';
              imageMenu.classList.remove('show');
              thumbTooltip.style.display = 'none';
              refreshParentShotGroupPreview();
              
              // 更新首帧连接：删除旧连接，创建新连接
              state.firstFrameConnections = state.firstFrameConnections.filter(c => c.to !== id);
              state.firstFrameConnections.push({
                id: state.nextFirstFrameConnId++,
                from: imgNode.id,
                to: id
              });
              renderFirstFrameConnections();
              
              try{ autoSaveWorkflow(); } catch(e){}
            });
          });
        } else {
          // 没有图片节点，隐藏选择按钮
          imageSelectorContainer.style.display = 'none';
        }
      }

      // 刷新父分镜组节点的宫格预览
      function refreshParentShotGroupPreview(){
        const parentConn = state.connections.find(c => c.to === id);
        if(parentConn){
          const parentNode = state.nodes.find(n => n.id === parentConn.from && n.type === 'shot_group');
          if(parentNode && parentNode.refreshGridPreview){
            parentNode.refreshGridPreview();
          }
        }
      }

      // 更新预览图
      function updatePreviewImage(){
        const connectedImageNodes = getConnectedImageNodes();

        if(connectedImageNodes.length > 0){
          // 如果分镜节点已有预览图，不自动替换
          if(!node.data.previewImageUrl){
            // 没有预览图时，自动选择一个
            const imageNode = connectedImageNodes.length === 1 
              ? connectedImageNodes[0]
              : connectedImageNodes[Math.floor(Math.random() * connectedImageNodes.length)];
            
            console.log(`[分镜节点 ${id}] 自动选择图片节点 ${imageNode.id}，URL:`, imageNode.data.url);
            node.data.previewImageUrl = imageNode.data.url;
          }
          
          previewImageEl.src = proxyImageUrl(node.data.previewImageUrl);
          previewImageEl.style.display = 'block';
          previewFieldEl.style.display = 'block';
        } else {
          node.data.previewImageUrl = '';
          previewImageEl.style.display = 'none';
          previewFieldEl.style.display = 'none';
        }
        
        // 更新图片选择菜单
        updateImageSelectionMenu();
        // 刷新父分镜组宫格预览
        refreshParentShotGroupPreview();
      }

      // 图片选择按钮事件
      if(imageSelectorCaret){
        imageSelectorCaret.addEventListener('click', (e) => {
          e.stopPropagation();
          imageMenu.classList.toggle('show');
        });
      }

      // 首帧端口事件 - 接受来自图片节点的连接
      firstFramePort.addEventListener('mouseup', (e) => {
        e.stopPropagation();
        if(state.connecting && state.connecting.fromId !== id){
          const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
          if(fromNode && fromNode.type === 'image' && fromNode.data.url){
            // 删除该分镜节点的旧首帧连接
            state.firstFrameConnections = state.firstFrameConnections.filter(c => c.to !== id);
            
            // 创建新的首帧连接
            state.firstFrameConnections.push({
              id: state.nextFirstFrameConnId++,
              from: state.connecting.fromId,
              to: id
            });
            
            // 更新视频首帧
            node.data.previewImageUrl = fromNode.data.url;
            previewImageEl.src = proxyImageUrl(fromNode.data.url);
            previewImageEl.style.display = 'block';
            previewFieldEl.style.display = 'block';
            refreshParentShotGroupPreview();
            
            renderFirstFrameConnections();
            try{ autoSaveWorkflow(); } catch(e){}
          }
        }
        state.connecting = null;
      });

      // 模型选择
      modelEl.addEventListener('change', () => {
        node.data.model = modelEl.value;
      });
      
      // 视频时长选择
      videoDurationEl.addEventListener('change', () => {
        node.data.videoDuration = Number(videoDurationEl.value);
        // 更新算力显示
        updateVideoComputingPowerDisplay();
      });
      
      // 视频模型选择
      videoModelEl.addEventListener('change', () => {
        node.data.videoModel = videoModelEl.value;
        // 模型改变时更新时长选项
        updateVideoDurationOptions(videoModelEl.value);
        // 更新算力显示
        updateVideoComputingPowerDisplay();
        // 更新按钮显示状态
        if(typeof updateReduceViolationBtnVisibility === 'function') {
          updateReduceViolationBtnVisibility();
        }
      });

      // 抽卡次数选择
      genCaret.addEventListener('click', (e) => {
        e.stopPropagation();
        genMenu.classList.toggle('show');
      });

      const genItems = genMenu.querySelectorAll('.gen-item');
      for(const item of genItems){
        item.addEventListener('click', (e) => {
          e.stopPropagation();
          const count = Number(item.dataset.count || '1');
          node.data.drawCount = count;
          updateDrawCountLabel();
          genMenu.classList.remove('show');
        });
      }

      // 视频抽卡次数选择
      videoCaret.addEventListener('click', (e) => {
        e.stopPropagation();
        videoMenu.classList.toggle('show');
      });

      const videoGenItems = videoMenu.querySelectorAll('.gen-item');
      for(const item of videoGenItems){
        item.addEventListener('click', (e) => {
          e.stopPropagation();
          const count = Number(item.dataset.count || '1');
          node.data.videoDrawCount = count;
          updateVideoDrawCountLabel();
          videoMenu.classList.remove('show');
        });
      }

      // 预览图点击放大
      previewImageEl.addEventListener('click', (e) => {
        e.stopPropagation();
        if(node.data.previewImageUrl){
          openImageModal(proxyImageUrl(node.data.previewImageUrl), '视频首帧');
        }
      });

      // 生成视频
      generateVideoBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if(!node.data.previewImageUrl){
          showToast('请先生成分镜图', 'warning');
          return;
        }
        generateShotFrameVideo(id, node);
      });

      // 初始化时更新预览图
      updatePreviewImage();

      // 暴露更新预览图的方法供外部调用
      node.updatePreview = updatePreviewImage;

      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });

      el.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        setSelected(id);
        bringNodeToFront(id);
      });

      headerEl.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        // 如果节点不在选中列表中，才调用setSelected（这会清空其他选中）
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        bringNodeToFront(id);
        initNodeDrag(id, e.clientX, e.clientY);
      });

      // 点击图片提示词textarea直接打开放大编辑窗口
      imagePromptEl.addEventListener('click', (e) => {
        e.stopPropagation();
        showPromptExpandModal(imagePromptEl, '图片提示词', (newValue) => {
          node.data.imagePrompt = newValue;
          updateShotReferences();
        }, { enableCharacterDropdown: true, nodeId: id });
      });

      // 点击视频提示词textarea直接打开放大编辑窗口
      videoPromptEl.addEventListener('click', (e) => {
        e.stopPropagation();
        showPromptExpandModal(videoPromptEl, '视频提示词', (newValue) => {
          node.data.videoPromptText = newValue;
        });
      });

      const reduceViolationBtn = el.querySelector('.reduce-violation-btn');
      
      // 控制按钮显示的函数
      function updateReduceViolationBtnVisibility() {
        if(reduceViolationBtn) {
          const videoModel = node.data.videoModel || 'sora2';
          if(videoModel === 'sora2') {
            reduceViolationBtn.style.display = 'inline-block';
          } else {
            reduceViolationBtn.style.display = 'none';
          }
        }
      }
      
      // 初始化按钮显示状态
      updateReduceViolationBtnVisibility();
      
      if(reduceViolationBtn){
        reduceViolationBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          
          const currentPrompt = videoPromptEl.value.trim();
          if(!currentPrompt){
            showToast('视频提示词为空', 'warning');
            return;
          }
          
          try {
            reduceViolationBtn.disabled = true;
            reduceViolationBtn.textContent = '改写提示词，修改违规内容...';
            
            const response = await fetch('/api/reduce-violation', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': getAuthToken(),
                'X-User-Id': getUserId()
              },
              body: JSON.stringify({ prompt: currentPrompt })
            });
            
            const result = await response.json();
            
            if(result.code === 0 && result.data && result.data.prompt){
              videoPromptEl.value = result.data.prompt;
              node.data.videoPromptText = result.data.prompt;
              showToast('提示词已改写', 'success');
            } else {
              throw new Error(result.message || '改写失败');
            }
          } catch(error){
            console.error('降低违规失败:', error);
            showToast('降低违规失败: ' + error.message, 'error');
          } finally {
            reduceViolationBtn.disabled = false;
            reduceViolationBtn.textContent = '提示词已优化，再次优化';
          }
        });
      }

      generateBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if(typeof generateShotFrameImage === 'function'){
          generateShotFrameImage(id, node);
        } else {
          console.error('generateShotFrameImage function is not loaded yet');
          showToast('功能加载中，请稍后再试', 'warning');
        }
      });

      // 检查是否有对话数据，更新生成对话音频按钮状态
      function updateDialogueButtonState(){
        if(generateDialogueBtn){
          const hasDialogue = node.data.shotJson && 
                             node.data.shotJson.dialogue && 
                             Array.isArray(node.data.shotJson.dialogue) && 
                             node.data.shotJson.dialogue.length > 0;
          generateDialogueBtn.disabled = !hasDialogue;
          generateDialogueBtn.title = hasDialogue ? '生成对话音频' : '该镜头没有对话';
          generateDialogueBtn.style.background = hasDialogue ? '#22c55e' : '#9ca3af';
          generateDialogueBtn.style.cursor = hasDialogue ? 'pointer' : 'not-allowed';
        }
      }
      updateDialogueButtonState();

      // 生成对话音频按钮点击事件
      if(generateDialogueBtn){
        generateDialogueBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          
          if(!node.data.shotJson || !node.data.shotJson.dialogue || node.data.shotJson.dialogue.length === 0){
            showToast('该分镜没有对话数据', 'warning');
            return;
          }
          
          // 创建对话组节点
          const dialogueGroupX = node.x + 450;
          const dialogueGroupY = node.y;
          const dialogueGroupId = createDialogueGroupNode({
            x: dialogueGroupX,
            y: dialogueGroupY,
            dialogueData: node.data.shotJson.dialogue,
            shotNumber: node.data.shotJson.shot_number
          });
          
          // 连接分镜节点到对话组节点
          const exists = state.connections.some(c => c.from === id && c.to === dialogueGroupId);
          if(!exists){
            state.connections.push({
              id: state.nextConnId++,
              from: id,
              to: dialogueGroupId
            });
            renderConnections();
          }
          
          // 获取对话组节点
          const dialogueGroupNode = state.nodes.find(n => n.id === dialogueGroupId);
          if(!dialogueGroupNode){
            showToast('创建对话组节点失败', 'error');
            return;
          }
          
          // 设置对话组节点的shotNumber（确保数据正确保存）
          if(node.data.shotJson.shot_number){
            dialogueGroupNode.data.shotNumber = node.data.shotJson.shot_number;
          }
          
          // 自动触发所有对话的音频生成
          const dialogueGroupEl = canvasEl.querySelector(`.node[data-node-id="${dialogueGroupId}"]`);
          if(dialogueGroupEl){
            const generateAllBtn = dialogueGroupEl.querySelector('.dialogue-generate-all-btn');
            if(generateAllBtn){
              // 延迟一下再点击，确保init化完成
              setTimeout(() => {
                generateAllBtn.click();
              }, 100);
            }
          }
          
          showToast('已创建对话组节点并开始生成音频', 'success');
          try{ autoSaveWorkflow(); } catch(e){}
        });
      }

      if(imageEl && node.data.imageUrl){
        imageEl.addEventListener('click', (e) => {
          e.stopPropagation();
          openImageModal(node.data.imageUrl, node.title);
        });
      }

      inputPort.addEventListener('mouseup', (e) => {
        if(state.connecting && state.connecting.fromId !== id){
          const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
          // 接受来自分镜组或图片节点的连接
          if(fromNode && (fromNode.type === 'shot_group' || fromNode.type === 'image')){
            const exists = state.connections.some(c => c.from === state.connecting.fromId && c.to === id);
            if(!exists){
              state.connections.push({
                id: state.nextConnId++,
                from: state.connecting.fromId,
                to: id
              });
              renderConnections();
              renderImageConnections();
              renderFirstFrameConnections();
              renderVideoConnections();
              
              // 如果是图片节点连接，更新预览图和选择菜单
              if(fromNode.type === 'image'){
                updatePreviewImage();
              }
              
              try{ autoSaveWorkflow(); } catch(e){}
            }
          }
        }
        state.connecting = null;
      });

      outputPort.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
      });

      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);
      setSelected(id);
      return id;
    }

    async function showScriptSelectionModal(node, textareaEl, updateScriptContent, warningField) {
      const defaultWorldId = state.defaultWorldId;
      
      if (!defaultWorldId) {
        showToast('请先在页面顶部选择默认世界', 'error');
        return;
      }

      const modal = document.createElement('div');
      modal.className = 'modal-overlay';
      modal.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 10000;';
      
      const modalContent = document.createElement('div');
      modalContent.style.cssText = 'background: white; border-radius: 12px; padding: 24px; max-width: 600px; width: 90%; max-height: 80vh; overflow: auto;';
      
      modalContent.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
          <h3 style="margin: 0; font-size: 18px; font-weight: 600;">选择剧本</h3>
          <button class="modal-close-btn" style="background: none; border: none; font-size: 24px; cursor: pointer; color: #666;">&times;</button>
        </div>
        <div class="script-list-container" style="min-height: 200px;">
          <div style="text-align: center; padding: 40px; color: #666;">加载中...</div>
        </div>
      `;
      
      modal.appendChild(modalContent);
      document.body.appendChild(modal);

      const closeBtn = modalContent.querySelector('.modal-close-btn');
      const listContainer = modalContent.querySelector('.script-list-container');

      closeBtn.addEventListener('click', () => {
        document.body.removeChild(modal);
      });

      modal.addEventListener('click', (e) => {
        if (e.target === modal) {
          document.body.removeChild(modal);
        }
      });

      try {
        const response = await fetch(`/api/scripts?world_id=${defaultWorldId}&page=1&page_size=50`, {
          headers: {
            'Authorization': localStorage.getItem('auth_token') || '',
            'X-User-Id': localStorage.getItem('user_id') || ''
          }
        });

        if (!response.ok) {
          throw new Error('获取剧本列表失败');
        }

        const result = await response.json();
        
        if (result.code !== 0) {
          throw new Error(result.message || '获取剧本列表失败');
        }

        const scripts = result.data.data || [];

        // 按集数排序（升序）
        scripts.sort((a, b) => {
          const epA = a.episode_number || 0;
          const epB = b.episode_number || 0;
          return epA - epB;
        });

        if (scripts.length === 0) {
          listContainer.innerHTML = `
            <div style="text-align: center; padding: 40px; color: #666;">
              <p>当前世界下暂无保存的剧本</p>
            </div>
          `;
          return;
        }

        listContainer.innerHTML = scripts.map(script => `
          <div class="script-item" data-script-id="${script.id}" style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 12px; cursor: pointer; transition: all 0.2s;">
            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 8px;">
              <div style="font-weight: 600; font-size: 14px; color: #111827;">${escapeHtml(script.title || '无标题')}</div>
              ${script.episode_number ? `<div style="background: #dbeafe; color: #1e40af; padding: 2px 8px; border-radius: 4px; font-size: 12px;">第${script.episode_number}集</div>` : ''}
            </div>
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 8px;">
              创建时间: ${new Date(script.create_time).toLocaleString('zh-CN')}
            </div>
            <div style="font-size: 13px; color: #374151; max-height: 60px; overflow: hidden; text-overflow: ellipsis;">
              ${escapeHtml((script.content || '').substring(0, 100))}${(script.content || '').length > 100 ? '...' : ''}
            </div>
          </div>
        `).join('');

        const scriptItems = listContainer.querySelectorAll('.script-item');
        scriptItems.forEach(item => {
          item.addEventListener('mouseenter', () => {
            item.style.background = '#f3f4f6';
            item.style.borderColor = '#10b981';
          });
          
          item.addEventListener('mouseleave', () => {
            item.style.background = 'white';
            item.style.borderColor = '#e5e7eb';
          });

          item.addEventListener('click', () => {
            const scriptId = parseInt(item.dataset.scriptId);
            const script = scripts.find(s => s.id === scriptId);
            
            if (script && script.content) {
              let content = script.content;
              const originalLength = content.length;
              const isTruncated = originalLength > 30000;
              
              if (isTruncated) {
                content = content.substring(0, 30000);
                warningField.style.display = 'block';
                showToast(`剧本内容已截取至30000字符（原${originalLength}字符）`, 'warning');
              } else {
                warningField.style.display = 'none';
              }

              textareaEl.value = content;
              updateScriptContent(content, `来源: ${script.title || '剧本'} ${isTruncated ? '(已截取)' : ''}`);
              
              showToast('剧本加载成功', 'success');
              document.body.removeChild(modal);
            }
          });
        });

      } catch (error) {
        console.error('加载剧本列表失败:', error);
        listContainer.innerHTML = `
          <div style="text-align: center; padding: 40px; color: #ef4444;">
            <p>加载失败: ${error.message}</p>
          </div>
        `;
        showToast('加载剧本列表失败', 'error');
      }
    }

    function showScriptExpandModal(textareaEl, updateScriptContent, charCountEl) {
      const modal = document.createElement('div');
      modal.className = 'modal-overlay';
      modal.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 10000;';
      
      const modalContent = document.createElement('div');
      modalContent.style.cssText = 'background: white; border-radius: 12px; padding: 24px; max-width: 900px; width: 90%; max-height: 85vh; display: flex; flex-direction: column;';
      
      const currentContent = textareaEl.value;
      const currentLength = currentContent.length;
      
      modalContent.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
          <h3 style="margin: 0; font-size: 18px; font-weight: 600;">编辑剧本内容</h3>
          <div style="display: flex; align-items: center; gap: 12px;">
            <span class="expand-char-count" style="color: #666; font-size: 14px;">${currentLength}/30000</span>
            <button class="modal-close-btn" style="background: none; border: none; font-size: 24px; cursor: pointer; color: #666;">&times;</button>
          </div>
        </div>
        <textarea class="expand-textarea" maxlength="30000" placeholder="在此输入剧本内容（最多30000字符）" style="flex: 1; width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; font-family: inherit; resize: none; min-height: 400px;">${escapeHtml(currentContent)}</textarea>
        <div style="display: flex; justify-content: flex-end; gap: 12px; margin-top: 16px;">
          <button class="modal-cancel-btn" style="padding: 8px 20px; border: 1px solid #ddd; border-radius: 6px; background: white; cursor: pointer; font-size: 14px;">取消</button>
          <button class="modal-confirm-btn" style="padding: 8px 20px; border: none; border-radius: 6px; background: #3b82f6; color: white; cursor: pointer; font-size: 14px;">确定</button>
        </div>
      `;
      
      modal.appendChild(modalContent);
      document.body.appendChild(modal);

      const closeBtn = modalContent.querySelector('.modal-close-btn');
      const cancelBtn = modalContent.querySelector('.modal-cancel-btn');
      const confirmBtn = modalContent.querySelector('.modal-confirm-btn');
      const expandTextarea = modalContent.querySelector('.expand-textarea');
      const expandCharCount = modalContent.querySelector('.expand-char-count');

      // 更新字符计数
      function updateExpandCharCount() {
        const length = expandTextarea.value.length;
        expandCharCount.textContent = `${length}/30000`;
        if(length > 28500) {
          expandCharCount.style.color = '#dc2626';
        } else if(length > 25500) {
          expandCharCount.style.color = '#f59e0b';
        } else {
          expandCharCount.style.color = '#666';
        }
      }

      expandTextarea.addEventListener('input', updateExpandCharCount);

      // 关闭模态框
      function closeModal() {
        document.body.removeChild(modal);
      }

      closeBtn.addEventListener('click', closeModal);
      cancelBtn.addEventListener('click', closeModal);

      modal.addEventListener('click', (e) => {
        if (e.target === modal) {
          closeModal();
        }
      });

      // 确定按钮
      confirmBtn.addEventListener('click', () => {
        const newContent = expandTextarea.value;
        textareaEl.value = newContent;
        
        // 更新字符计数
        const length = newContent.length;
        charCountEl.textContent = `${length}/30000`;
        if(length > 28500) {
          charCountEl.style.color = '#dc2626';
        } else if(length > 25500) {
          charCountEl.style.color = '#f59e0b';
        } else {
          charCountEl.style.color = '#666';
        }
        
        // 调用更新函数
        updateScriptContent(newContent, '来源: 文本输入');
        
        closeModal();
        showToast('剧本内容已更新', 'success');
      });

      // 自动聚焦到文本框末尾
      expandTextarea.focus();
      expandTextarea.setSelectionRange(expandTextarea.value.length, expandTextarea.value.length);
    }

    function showPromptExpandModal(textareaEl, title, onUpdate, opts) {
      const modal = document.createElement('div');
      modal.className = 'modal-overlay';
      modal.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 10000;';
      
      const modalContent = document.createElement('div');
      modalContent.style.cssText = 'background: white; border-radius: 12px; padding: 24px; max-width: 900px; width: 90%; max-height: 85vh; display: flex; flex-direction: column;';
      
      const currentContent = textareaEl.value;
      
      modalContent.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
          <h3 style="margin: 0; font-size: 18px; font-weight: 600;">编辑${escapeHtml(title)}</h3>
          <button class="modal-close-btn" style="background: none; border: none; font-size: 24px; cursor: pointer; color: #666;">&times;</button>
        </div>
        <textarea class="expand-textarea" placeholder="在此输入${escapeHtml(title)}" style="flex: 1; width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; font-family: inherit; resize: none; min-height: 400px;">${escapeHtml(currentContent)}</textarea>
        ${opts && opts.enableCharacterDropdown ? '<div style="margin-top: 8px; font-size: 12px; color: #9ca3af;">💡 按 <kbd style="background: #f3f4f6; padding: 1px 6px; border-radius: 4px; border: 1px solid #d1d5db; font-size: 11px;">/</kbd> 可选择角色插入到提示词中</div>' : ''}
        <div style="display: flex; justify-content: flex-end; gap: 12px; margin-top: 16px;">
          <button class="modal-cancel-btn" style="padding: 8px 20px; border: 1px solid #ddd; border-radius: 6px; background: white; cursor: pointer; font-size: 14px;">取消</button>
          <button class="modal-confirm-btn" style="padding: 8px 20px; border: none; border-radius: 6px; background: #3b82f6; color: white; cursor: pointer; font-size: 14px;">确定</button>
        </div>
      `;
      
      modal.appendChild(modalContent);
      document.body.appendChild(modal);

      const closeBtn = modalContent.querySelector('.modal-close-btn');
      const cancelBtn = modalContent.querySelector('.modal-cancel-btn');
      const confirmBtn = modalContent.querySelector('.modal-confirm-btn');
      const expandTextarea = modalContent.querySelector('.expand-textarea');

      // 关闭模态框
      function closeModal() {
        document.body.removeChild(modal);
      }

      closeBtn.addEventListener('click', closeModal);
      cancelBtn.addEventListener('click', closeModal);

      modal.addEventListener('click', (e) => {
        if (e.target === modal) {
          closeModal();
        }
      });

      // 确定按钮
      confirmBtn.addEventListener('click', () => {
        const newContent = expandTextarea.value;
        textareaEl.value = newContent;
        
        // 调用更新回调函数
        if (onUpdate) {
          onUpdate(newContent);
        }
        
        closeModal();
        showToast(`${title}已更新`, 'success');
      });

      // 支持 / 键触发角色列表（仅分镜节点图片提示词放大窗口）
      if(opts && opts.enableCharacterDropdown && opts.nodeId != null){
        expandTextarea.addEventListener('keydown', (e) => {
          if(e.key === '/') {
            e.preventDefault();
            showCharacterDropdownForImagePrompt(opts.nodeId, expandTextarea, expandTextarea.selectionStart);
          }
        });
        expandTextarea.addEventListener('input', () => {
          hideCharacterDropdownForImagePrompt(opts.nodeId);
        });
        expandTextarea.addEventListener('blur', () => {
          setTimeout(() => hideCharacterDropdownForImagePrompt(opts.nodeId), 200);
        });
      }

      // 自动聚焦到文本框末尾
      expandTextarea.focus();
      expandTextarea.setSelectionRange(expandTextarea.value.length, expandTextarea.value.length);
    }

    // 分镜组节点生成视频功能
    async function generateShotGroupVideo(shotGroupNodeId, shotGroupNode) {
      try {
        // 获取所有子分镜节点
        const shotFrameConnections = state.connections.filter(c => c.from === shotGroupNodeId);
        const shotFrameNodes = shotFrameConnections
          .map(conn => state.nodes.find(n => n.id === conn.to && n.type === 'shot_frame'))
          .filter(Boolean);
        
        if(shotFrameNodes.length === 0) {
          showToast('请先生成分镜节点', 'warning');
          return;
        }
        
        // 检查所有分镜节点是否都有首帧图片
        const nodesWithImage = shotFrameNodes.filter(n => n.data.previewImageUrl || n.data.imageUrl);
        if(nodesWithImage.length === 0) {
          showToast('分镜节点没有首帧图片，请先生成分镜图', 'warning');
          return;
        }
        
        const generateBtn = document.querySelector(`.node[data-node-id="${shotGroupNodeId}"] .shot-group-generate-video-btn`);
        const mergeStatusEl = document.querySelector(`.node[data-node-id="${shotGroupNodeId}"] .grid-merge-status`);
        if(!generateBtn) return;
        
        generateBtn.disabled = true;
        generateBtn.textContent = '生成中...';
        
        const firstShotFrame = shotFrameNodes[0];
        const duration = shotGroupNode.data.videoDuration || 5;
        const count = shotGroupNode.data.videoDrawCount || 1;
        const videoModel = shotGroupNode.data.videoModel || 'wan22';
        const userId = localStorage.getItem('user_id') || '1';
        const authToken = localStorage.getItem('auth_token') || '';
        
        // ===== 宫格合并模式：多分镜时先合并为宫格图 =====
        let imageUrl;
        
        if(shotFrameNodes.length > 1) {
          // 多分镜：合并为宫格图
          if(mergeStatusEl) {
            mergeStatusEl.style.color = '#3b82f6';
            mergeStatusEl.textContent = '正在合并宫格图片...';
          }
          generateBtn.textContent = '合并宫格...';
          
          const gridSize = calculateGridSize(shotFrameNodes.length);
          if(!gridSize) {
            throw new Error('分镜数量超过25，不支持宫格合并');
          }
          
          // 收集图片URL和黑色位置
          const imageUrls = [];
          const blackIndices = [];
          for(let i = 0; i < gridSize; i++) {
            if(i < shotFrameNodes.length) {
              const imgUrl = shotFrameNodes[i].data.previewImageUrl || shotFrameNodes[i].data.imageUrl || '';
              if(imgUrl) {
                imageUrls.push(imgUrl);
              } else {
                imageUrls.push('');
                blackIndices.push(i);
              }
            } else {
              imageUrls.push('');
              blackIndices.push(i);
            }
          }
          
          console.log(`[分镜组视频] 合并宫格: ${shotFrameNodes.length}个分镜 → ${gridSize}宫格, 黑色位置:`, blackIndices);
          
          // 调用合并API
          const mergeRes = await fetch('/api/images/merge-grid', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-User-Id': userId,
              'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
              image_urls: imageUrls,
              black_indices: blackIndices,
              grid_size: gridSize
            })
          });
          
          const mergeData = await mergeRes.json();
          if(mergeData.code !== 0 || !mergeData.data || !mergeData.data.image_url) {
            throw new Error(mergeData.message || '宫格图片合并失败');
          }
          
          imageUrl = mergeData.data.image_url;
          console.log(`[分镜组视频] 宫格合并成功:`, imageUrl);
          
          // 保存合并结果到节点数据
          shotGroupNode.data.gridPreview = shotGroupNode.data.gridPreview || {};
          shotGroupNode.data.gridPreview.mergedImageUrl = imageUrl;
          
          if(mergeStatusEl) {
            mergeStatusEl.style.color = '#22c55e';
            mergeStatusEl.textContent = '宫格合并完成，正在生成视频...';
          }
        } else {
          // 单分镜：直接使用首帧图
          imageUrl = firstShotFrame.data.previewImageUrl || firstShotFrame.data.imageUrl;
          if(!imageUrl) {
            throw new Error('分镜节点没有首帧图片');
          }
        }
        
        // 拼接所有分镜的视频提示词，每个镜头标明时间范围
        let cumulativeTime = 0;
        const videoPromptParts = [];
        
        shotFrameNodes.forEach((shotNode, index) => {
          const shotDuration = shotNode.data.duration || 5;
          const startTime = cumulativeTime;
          const endTime = cumulativeTime + shotDuration;
          
          // 使用分镜节点的视频提示词文本
          let shotPrompt = shotNode.data.videoPromptText || shotNode.data.videoPrompt || '';
          
          // 如果是JSON格式，尝试转换为文本
          if(shotPrompt.startsWith('{')) {
            try {
              const promptObj = JSON.parse(shotPrompt);
              shotPrompt = convertVideoPromptToText(shotPrompt);
            } catch(e) {
              // 保持原样
            }
          }
          
          videoPromptParts.push(`镜头${index + 1}：${startTime}~${endTime}S，${shotPrompt}`);
          cumulativeTime = endTime;
        });
        
        const combinedVideoPrompt = videoPromptParts.join('；');
        
        // 添加视频提示词后缀
        let finalVideoPrompt = combinedVideoPrompt;
        if(typeof getVideoPromptWithSuffix === 'function'){
          finalVideoPrompt = getVideoPromptWithSuffix(combinedVideoPrompt);
        }
        
        generateBtn.textContent = '提交视频...';
        showToast(`正在生成 ${count} 个视频...`, 'info');
        
        // 调用图生视频API
        const form = new FormData();
        
        form.append('image_urls', imageUrl);
        form.append('prompt', finalVideoPrompt);
        form.append('duration_seconds', duration);
        form.append('count', count);
        form.append('ratio', state.ratio || '9:16');
        form.append('video_model', videoModel);
        
        if(userId){
          form.append('user_id', userId);
        }
        if(authToken){
          form.append('auth_token', authToken);
        }
        
        const res = await fetch('/api/ai-app-run-image', {
          method: 'POST',
          body: form
        });
        
        const data = await res.json();
        
        if(!data.project_ids || data.project_ids.length === 0){
          throw new Error(data.detail || data.message || '提交任务失败');
        }
        
        const projectIds = data.project_ids;
        showToast(`视频生成任务已提交，正在处理...`, 'info');
        
        // 立即创建对应数量的视频节点并绑定 project_id
        const createdVideoNodeIds = [];
        const videoCount = projectIds.length;
        
        for(let i = 0; i < videoCount; i++){
          const offsetY = i * 280;
          const newVideoNodeId = createVideoNode({ 
            x: firstShotFrame.x + 380, 
            y: firstShotFrame.y + offsetY 
          });
          
          const newVideoNode = state.nodes.find(n => n.id === newVideoNodeId);
          if(newVideoNode){
            newVideoNode.data.name = videoCount > 1 ? `分镜组视频${i + 1}` : '分镜组视频';
            newVideoNode.data.project_id = projectIds[i] || projectIds[0];
            newVideoNode.title = newVideoNode.data.name;
            
            // 更新节点标题显示
            const canvasEl = document.getElementById('canvas');
            const newNodeEl = canvasEl ? canvasEl.querySelector(`.node[data-node-id="${newVideoNodeId}"]`) : null;
            if(newNodeEl){
              const titleEl = newNodeEl.querySelector('.node-title');
              if(titleEl) titleEl.textContent = newVideoNode.title;
              
              const nameEl = newNodeEl.querySelector('.video-name');
              if(nameEl) nameEl.textContent = newVideoNode.data.name;
            }
            
            // 创建从第一个分镜节点到视频节点的连接
            state.connections.push({
              id: state.nextConnId++,
              from: firstShotFrame.id,
              to: newVideoNodeId
            });
            
            createdVideoNodeIds.push(newVideoNodeId);
            console.log(`[分镜组视频] 创建视频节点 ${newVideoNodeId} 并绑定 project_id:`, newVideoNode.data.project_id);
          }
        }
        
        // 重新渲染连接线
        renderConnections();
        renderImageConnections();
        renderFirstFrameConnections();
        renderVideoConnections();
        renderMinimap();
        
        // 轮询视频生成状态,更新视频URL
        pollVideoStatus(
          projectIds,
          (msg) => {
            generateBtn.textContent = msg;
          },
          (statusResult) => {
            console.log('Shot group video generation status result:', statusResult);
            
            // 从 tasks 数组中提取结果
            let videoUrls = [];
            if(statusResult.tasks && Array.isArray(statusResult.tasks)){
              videoUrls = statusResult.tasks
                .filter(task => task.status === 'SUCCESS' && task.result)
                .map(task => normalizeVideoUrl(task.result))
                .filter(Boolean);
            } else {
              const rawResults = extractResultsArray(statusResult);
              videoUrls = Array.isArray(rawResults)
                ? rawResults.map(normalizeVideoUrl).filter(Boolean)
                : [];
            }

            
            if(videoUrls.length === 0){
              const errorMsg = '视频生成失败，未获取到结果';
              showToast(errorMsg, 'error');
              generateBtn.textContent = '生成视频';
              generateBtn.disabled = false;
              return;
            }
            
            // 更新视频节点的URL
            createdVideoNodeIds.forEach((videoNodeId, index) => {
              const videoNode = state.nodes.find(n => n.id === videoNodeId);
              if(videoNode && videoUrls[index]){
                videoNode.data.url = videoUrls[index];
                
                // 更新视频节点的显示
                const canvasEl = document.getElementById('canvas');
                const videoNodeEl = canvasEl ? canvasEl.querySelector(`.node[data-node-id="${videoNodeId}"]`) : null;
                if(videoNodeEl){
                  const previewField = videoNodeEl.querySelector('.video-preview-field');
                  const thumbVideo = videoNodeEl.querySelector('.video-thumb');
                  const nameEl = videoNodeEl.querySelector('.video-name');
                  if(previewField && thumbVideo){
                    thumbVideo.src = proxyDownloadUrl(videoUrls[index]);
                    thumbVideo.muted = true;
                    thumbVideo.loop = true;
                    if(nameEl){
                      const displayName = (videoNode.data.name || '').length > 10 ? videoNode.data.name.substring(0, 10) + '...' : (videoNode.data.name || '');
                      nameEl.textContent = displayName;
                    }
                    previewField.style.display = 'block';
                  }
                  const previewActionsField = videoNodeEl.querySelector('.video-preview-actions-field');
                  if(previewActionsField) previewActionsField.style.display = 'block';
                }
                
                console.log(`[分镜组视频] 视频节点 ${videoNodeId} 更新URL:`, videoUrls[index]);
              }
            });
            
            showToast(`分镜组视频生成成功！`, 'success');
            generateBtn.textContent = '生成视频';
            generateBtn.disabled = false;
            
            try{ autoSaveWorkflow(); } catch(e){}
          },
          (error) => {
            console.error('Shot group video generation error:', error);
            showToast(`视频生成失败: ${error}`, 'error');
            generateBtn.textContent = '生成视频';
            generateBtn.disabled = false;
          }
        );
        
      } catch(error) {
        console.error('Generate shot group video error:', error);
        showToast(`生成视频失败: ${error.message}`, 'error');
        
        const generateBtn = document.querySelector(`.node[data-node-id="${shotGroupNodeId}"] .shot-group-generate-video-btn`);
        if(generateBtn){
          generateBtn.textContent = '生成视频';
          generateBtn.disabled = false;
        }
        const mergeStatusEl = document.querySelector(`.node[data-node-id="${shotGroupNodeId}"] .grid-merge-status`);
        if(mergeStatusEl){
          mergeStatusEl.style.color = '#ef4444';
          mergeStatusEl.textContent = `失败: ${error.message}`;
        }
      }
    }

    // 显示角色选择下拉框（用于图片提示词，使用 state.worldCharacters）
    function showCharacterDropdownForImagePrompt(nodeId, textarea, cursorPos) {
      const dropdownId = `character-dropdown-imageprompt-${nodeId}`;
      let dropdown = document.getElementById(dropdownId);
      
      // 如果下拉框不存在，创建一个
      if (!dropdown) {
        dropdown = document.createElement('div');
        dropdown.id = dropdownId;
        dropdown.className = 'character-dropdown';
        dropdown.style.cssText = 'display: none; position: absolute; background: white; border: 1px solid #e5e7eb; border-radius: 6px; max-height: 200px; overflow-y: auto; z-index: 1000; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); width: 100%;';
        textarea.parentNode.style.position = 'relative';
        textarea.parentNode.appendChild(dropdown);
      }
      
      const worldId = state.defaultWorldId;
      if (!worldId) {
        dropdown.innerHTML = '<div style="padding: 8px; color: #6b7280; font-size: 12px;">请先选择世界</div>';
        dropdown.style.display = 'block';
        return;
      }
      
      const characters = state.worldCharacters || [];
      if (characters.length > 0) {
        dropdown.innerHTML = characters.map(char => {
          const hasImage = !!char.reference_image;
          const warningStyle = hasImage ? '' : 'background: #fef2f2; border-left: 3px solid #ef4444;';
          const nameStyle = hasImage ? 'color: #374151;' : 'color: #ef4444;';
          const warningText = hasImage ? '' : '<span style="font-size: 10px; color: #ef4444; margin-left: 4px;">无参考图</span>';
          return `
            <div class="character-dropdown-item" data-character-name="${escapeHtml(char.name)}" style="padding: 8px 12px; cursor: pointer; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #f3f4f6; ${warningStyle}">
              ${hasImage ? `<img src="${char.reference_image}" style="width: 24px; height: 24px; object-fit: cover; border-radius: 3px;" />` : '<div style="width: 24px; height: 24px; background: #fee2e2; border-radius: 3px; display: flex; align-items: center; justify-content: center; font-size: 10px; color: #ef4444;">!</div>'}
              <span style="font-size: 12px; ${nameStyle}">${escapeHtml(char.name)}${warningText}</span>
            </div>
          `;
        }).join('');
        
        // 绑定点击事件
        dropdown.querySelectorAll('.character-dropdown-item').forEach(item => {
          item.addEventListener('click', () => {
            const charName = item.dataset.characterName;
            insertCharacterAtCursorForImagePrompt(textarea, charName);
            hideCharacterDropdownForImagePrompt(nodeId);
          });
          
          item.addEventListener('mouseenter', () => {
            item.style.background = item.style.borderLeft ? '#fef2f2' : '#f8fafc';
          });
          item.addEventListener('mouseleave', () => {
            item.style.background = item.style.borderLeft ? '#fef2f2' : '';
          });
        });
        
        // 定位下拉框在textarea下方
        dropdown.style.top = (textarea.offsetHeight) + 'px';
        dropdown.style.left = '0';
        dropdown.style.right = '0';
        dropdown.style.display = 'block';
      } else {
        dropdown.innerHTML = '<div style="padding: 8px; color: #6b7280; font-size: 12px;">暂无角色</div>';
        dropdown.style.display = 'block';
      }
    }

    // 隐藏角色选择下拉框（图片提示词用）
    function hideCharacterDropdownForImagePrompt(nodeId) {
      const dropdown = document.getElementById(`character-dropdown-imageprompt-${nodeId}`);
      if (dropdown) {
        dropdown.style.display = 'none';
      }
    }

    // 在光标位置插入角色名（包裹在【【】】中）
    function insertCharacterAtCursorForImagePrompt(textarea, charName) {
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const value = textarea.value;
      
      // / 已被 keydown 拦截不会出现在文本中，直接在光标位置插入
      const before = value.substring(0, start);
      const after = value.substring(end);
      const insertText = '【【' + charName + '】】';
      const newValue = before + insertText + after;
      
      textarea.value = newValue;
      
      // 设置光标位置到插入的角色名之后
      const newCursorPos = start + insertText.length;
      textarea.setSelectionRange(newCursorPos, newCursorPos);
      textarea.focus();
      
      // 手动触发 input 事件，以更新 node.data 和引用标签
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    }
