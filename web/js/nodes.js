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
          <div class="node-title">${node.title}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field">
            <div class="label">视频</div>
            <input class="video-file" type="file" accept="video/*" />
            <div class="gen-meta" style="margin-top: 4px;">或</div>
            <button class="mini-btn video-from-asset" type="button">从素材库选择</button>
          </div>
          <div class="field video-preview-field" style="display:none;">
            <div class="label">预览</div>
            <div class="video-preview">
              <video class="video-thumb" playsinline></video>
              <div class="video-preview-actions">
                <button class="vp-btn vp-play" type="button" aria-label="播放">▶</button>
                <button class="vp-btn vp-zoom" type="button" aria-label="放大">⤢</button>
              </div>
            </div>
            <div class="preview-row" style="margin-top: 8px; justify-content: space-between;">
              <div class="gen-meta video-name"></div>
              <div style="display: flex; gap: 8px;">
                <button class="mini-btn video-add-timeline" type="button">加时间轴</button>
                <button class="mini-btn video-download" type="button">下载</button>
                <button class="mini-btn video-clear" type="button">清除</button>
              </div>
            </div>
          </div>
          <div class="field video-status-field" style="display:none;">
            <div class="gen-meta video-status"></div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const fileEl = el.querySelector('.video-file');
      const fromAssetBtn = el.querySelector('.video-from-asset');
      const inputPort = el.querySelector('.port.input');
      const outputPort = el.querySelector('.port.output');
      const previewField = el.querySelector('.video-preview-field');
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

      fromAssetBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        alert('素材库 - 空实现');
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
          <div class="field">
            <div class="label">分镜组: ${escapeHtml(node.data.groupId || node.data.group_id)}</div>
            <div class="gen-meta">共 ${node.data.shots.length} 个分镜</div>
          </div>
          <div class="field" style="max-height: 300px; overflow-y: auto;">
            ${shotsHtml || '<div class="shot-group-empty">暂无分镜</div>'}
          </div>
          <div class="field">
            <div class="label">分镜模型</div>
            <select class="shot-group-model">
              <option value="gemini-2.5-pro-image-preview" ${node.data.model === 'gemini-2.5-pro-image-preview' ? 'selected' : ''}>标准版</option>
              <option value="gemini-3-pro-image-preview" ${node.data.model === 'gemini-3-pro-image-preview' ? 'selected' : ''}>加强版</option>
            </select>
          </div>
          <div class="field btn-row">
            <button class="mini-btn secondary shot-group-detail-btn" type="button">详情</button>
            <div class="gen-container" style="flex: 1;">
              <button class="gen-btn gen-btn-main shot-group-generate-btn" type="button" style="background: #22c55e; color: white;">${node.data.generateMode === 'merged' ? '合并分镜' : '独立分镜'}</button>
              <button class="gen-btn gen-btn-caret" type="button" aria-label="选择模式">▾</button>
              <div class="gen-menu">
                <div class="gen-item" data-mode="independent">独立分镜</div>
                <div class="gen-item" data-mode="merged">合并分镜</div>
              </div>
            </div>
          </div>
        `;

        const newDetailBtn = nodeBody.querySelector('.shot-group-detail-btn');
        const newGenerateBtn = nodeBody.querySelector('.shot-group-generate-btn');
        const newGenCaretBtn = nodeBody.querySelector('.gen-btn-caret');
        const newGenMenu = nodeBody.querySelector('.gen-menu');
        const newGenItems = nodeBody.querySelectorAll('.gen-item');
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

        if(newGenCaretBtn){
          newGenCaretBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            newGenMenu.classList.toggle('show');
          });
        }

        if(newGenItems){
          newGenItems.forEach(item => {
            item.addEventListener('click', (e) => {
              e.stopPropagation();
              const mode = item.dataset.mode;
              node.data.generateMode = mode;
              newGenerateBtn.textContent = item.textContent;
              newGenMenu.classList.remove('show');
            });
          });
        }

        if(newGenerateBtn){
          newGenerateBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const mode = node.data.generateMode;
            if(mode === 'independent'){
              generateShotFramesIndependent(nodeId, node);
            } else {
              generateShotFramesMerged(nodeId, node);
            }
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
          <div class="node-title">${node.title}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field">
            <div class="label">首帧画面<span class="req">*</span></div>
            <input class="start-file" type="file" accept="image/*" />
            <div class="preview-row start-preview-row" style="display:none;">
              <img class="preview start-preview" />
              <button class="mini-btn start-clear" type="button">清除</button>
            </div>
          </div>
          <div class="field">
            <div class="label">尾帧画面（可选）</div>
            <input class="end-file" type="file" accept="image/*" />
            <div class="preview-row end-preview-row" style="display:none;">
              <img class="preview end-preview" />
              <button class="mini-btn end-clear" type="button">清除</button>
            </div>
          </div>
          <div class="field">
            <div class="label">视频长度</div>
            <select class="duration-select">
              <option value="5" selected>5秒</option>
              <option value="10">10秒</option>
            </select>
          </div>
          <div class="field">
            <div class="label">视频比例</div>
            <select class="ratio-select">
              <option value="9:16">9:16</option>
              <option value="3:4">3:4</option>
              <option value="1:1">1:1</option>
              <option value="4:3">4:3</option>
              <option value="16:9">16:9</option>
            </select>
          </div>
          <div class="field">
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
          <!-- 运镜功能暂时隐藏
          <div class="field">
            <div class="label">运镜</div>
            <label class="toggle-row"><input class="motion-enable" type="checkbox" />启用运镜</label>
            <div class="motion-options">
              <select class="motion-select">
                <option value="pan_left">向左横切</option>
                <option value="pan_right">向右横切</option>
                <option value="zoom_out">镜头拉</option>
                <option value="zoom_in">镜头推</option>
              </select>
              <div class="motion-help">
                <div class="motion-help-illu"></div>
                <div class="motion-help-text"></div>
              </div>
            </div>
          </div>
          -->
          <div class="field">
            <div class="label">提示词</div>
            <textarea class="prompt" placeholder="请输入提示词..." rows="3"></textarea>
          </div>
          <div class="field computing-power-field" style="padding: 6px; border-radius: 6px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span style="color: #9ca3af; font-size: 12px;">算力消耗：</span>
              <span class="computing-power-value" style="color: #60a5fa; font-weight: bold; font-size: 14px;">0 算力</span>
            </div>
            <div class="computing-power-detail" style="margin-top: 4px; font-size: 11px; color: #6b7280;">
              单个 0 算力 × 1 个 = 0 算力
            </div>
          </div>
          <div class="field">
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
      const durationSelect = el.querySelector('.duration-select');
      const ratioSelect = el.querySelector('.ratio-select');
      const videoModelSelect = el.querySelector('.video-model-select');
      // 运镜功能暂时隐藏，相关元素不存在
      // const motionEnableEl = el.querySelector('.motion-enable');
      // const motionOptionsEl = el.querySelector('.motion-options');
      // const motionSelect = el.querySelector('.motion-select');
      // const motionHelpIllu = el.querySelector('.motion-help-illu');
      // const motionHelpText = el.querySelector('.motion-help-text');
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
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';

      el.innerHTML = `
        <div class="port input" title="输入（连接分镜节点）"></div>
        <div class="port output" title="输出（连接到图生视频节点）"></div>
        <div class="node-header">
          <div class="node-title">${node.title}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field">
            <div class="label">上传图片</div>
            <input class="image-file" type="file" accept="image/*" />
            <div class="preview-row image-preview-row" style="display:none;">
              <img class="preview image-preview" />
              <button class="mini-btn image-clear" type="button">×</button>
            </div>
          </div>
          <div class="field">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <div class="label" style="margin: 0;">编辑提示词（可选）</div>
              <button class="mini-btn image-prompt-expand-btn" type="button" style="font-size: 11px; padding: 4px 8px;" title="放大编辑">⤢</button>
            </div>
            <textarea class="image-prompt" rows="2" placeholder="输入提示词进行图片编辑"></textarea>
          </div>
          <div class="field">
            <div class="label">模型</div>
            <select class="image-model">
              <option value="gemini-2.5-pro-image-preview">标准版 (2算力)</option>
              <option value="gemini-3-pro-image-preview">加强版 (6算力)</option>
            </select>
          </div>
          <div class="field">
            <div class="label">图片比例</div>
            <select class="image-ratio">
              <option value="9:16">竖屏 (9:16)</option>
              <option value="16:9">横屏 (16:9)</option>
              <option value="1:1">正方形 (1:1)</option>
              <option value="3:4">竖屏 (3:4)</option>
              <option value="4:3">横屏 (4:3)</option>
            </select>
          </div>
          <div class="field">
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
              <button class="mini-btn image-download-btn" type="button" style="border-radius: 10px;">下载图片</button>
            </div>
            <div class="gen-meta image-draw-count-label"></div>
            <div class="muted image-edit-status" style="display:none;"></div>
          </div>
          <div class="field image-confirm-field" style="display:none;">
            <button class="mini-btn image-confirm-shot-btn" type="button" style="background: #10b981; color: white; width: 100%;">确认分镜图</button>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const inputPort = el.querySelector('.port.input');
      const outputPort = el.querySelector('.port.output');

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
      const downloadBtn = el.querySelector('.image-download-btn');
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
        if(!node.data.prompt){
          statusEl.style.display = 'block';
          statusEl.style.color = '#dc2626';
          statusEl.textContent = '请先输入编辑提示词';
          return;
        }

        editBtn.disabled = true;
        statusEl.style.display = 'block';
        statusEl.style.color = '';
        statusEl.textContent = '正在提交任务...';

        try{
          let submitFile = node.data.file;
          if(!submitFile && node.data.url){
            submitFile = await fetchFileFromUrl(node.data.url);
          }

          let finalPrompt = node.data.prompt;
          if(state.style && state.style.name){
            finalPrompt = `${finalPrompt}\n\n图片风格：${state.style.name}`;
          }

          const desiredCount = Math.max(1, Number(node.data.drawCount) || 1);
          const submitRes = await generateEditedImage(submitFile, finalPrompt, node.data.ratio, node.data.model, desiredCount);
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
                  imageNode.data.url = imageUrl;
                  imageNode.data.preview = imageUrl;
                  
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
          <div class="node-title">剧本 ${scriptId}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <div class="label" style="margin: 0;">输入剧本内容</div>
              <div style="display: flex; align-items: center; gap: 8px;">
                <span class="script-char-count" style="color: #666; font-size: 12px;">0/30000</span>
                <button class="mini-btn script-expand-btn" type="button" style="font-size: 11px; padding: 4px 8px;" title="放大编辑">⤢</button>
              </div>
            </div>
            <textarea class="script-textarea" rows="6" maxlength="30000" placeholder="在此输入剧本内容，或上传文件（最多30000字符）"></textarea>
          </div>
          <div class="field">
            <div class="label">或上传剧本文件</div>
            <input class="script-file" type="file" accept=".txt,.md" />
          </div>
          <div class="field">
            <div class="label">或从已保存剧本中选择</div>
            <button class="gen-btn script-load-btn" type="button" style="border-radius: 8px; width: 100%; background: #10b981; padding: 8px;">加载剧本</button>
          </div>
          <div class="field">
            <div class="label">镜头组最长时长</div>
            <select class="script-duration-select" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
              <option value="5">5秒</option>
              <option value="8">8秒</option>
              <option value="10">10秒</option>
              <option value="15" selected>15秒</option>
            </select>
            <div class="gen-meta" style="margin-top: 4px; font-size: 11px; color: #666;">每个镜头组内所有镜头的总时长不超过此值</div>
          </div>
          <div class="field">
            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
              <input type="checkbox" class="script-force-medium-shot" style="cursor: pointer;" checked />
              <span>对话禁止全景</span>
            </label>
            <div class="gen-meta" style="margin-top: 4px; font-size: 11px; color: #666;">对话镜头自动选择近景或中景，避免sora全景对话效果不佳</div>
          </div>
          <div class="field">
            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
              <input type="checkbox" class="script-no-bg-music" style="cursor: pointer;" checked />
              <span>不生成背景音乐</span>
            </label>
            <div class="gen-meta" style="margin-top: 4px; font-size: 11px; color: #666;">方便后期调音</div>
          </div>
          <div class="field">
            <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
              <input type="checkbox" class="script-split-multi-dialogue" style="cursor: pointer;" />
              <span>拆分多人对话镜头</span>
            </label>
            <div class="gen-meta" style="margin-top: 4px; font-size: 11px; color: #666;">将多人对话镜头拆分为单人对话镜头，并注意画面不越轴</div>
          </div>
          <div class="field script-info-field" style="display:none;">
            <div class="gen-meta script-name"></div>
            <div class="gen-meta script-length"></div>
          </div>
          <div class="field script-warning-field" style="display:none;">
            <div class="gen-meta" style="color: #f59e0b;">文件内容超过30000字符，已自动截取前30000字符。建议将剧本分段处理。</div>
          </div>
          <div class="field">
            <button class="gen-btn script-split-btn" type="button" style="border-radius: 10px; width: 100%;" disabled>拆分镜组</button>
            <div class="gen-meta script-status" style="display:none; margin-top: 8px;"></div>
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
      const infoField = el.querySelector('.script-info-field');
      const nameEl = el.querySelector('.script-name');
      const lengthEl = el.querySelector('.script-length');
      const splitBtn = el.querySelector('.script-split-btn');
      const statusEl = el.querySelector('.script-status');
      const charCountEl = el.querySelector('.script-char-count');
      const warningField = el.querySelector('.script-warning-field');
      
      // 初始化节点数据中的最大时长和选项
      node.data.maxGroupDuration = 15;
      node.data.forceMediumShot = true;
      node.data.noBgMusic = true;
      node.data.splitMultiDialogue = false;

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

        if(!state.defaultWorldId){
          const confirmed = window.confirm('尚未在左上角选择世界，无法自动匹配场景和角色。确认继续拆分分镜图吗？');
          if(!confirmed){
            return;
          }
        }

        splitBtn.disabled = true;
        statusEl.style.display = 'block';
        statusEl.style.color = '#666';
        statusEl.textContent = '正在调用LLM解析剧本...';

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
              split_multi_dialogue: node.data.splitMultiDialogue || false
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
              
              result.data.shot_groups.forEach((shotGroup, index) => {
                const offsetX = 400;
                const offsetY = index * 465;
                const shotGroupNodeId = createShotGroupNode({
                  x: node.x + offsetX,
                  y: node.y + offsetY,
                  shotGroupData: shotGroup,
                  scriptData: result.data
                });
                
                // 创建从剧本节点到分镜组节点的连线
                if(shotGroupNodeId) {
                  state.connections.push({
                    id: state.nextConnId++,
                    from: id,
                    to: shotGroupNodeId
                  });
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
            }
            
            showToast('剧本拆分成功！时间轴已准备就绪', 'success');
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

      canvasEl.appendChild(el);
      setSelected(id);
      return id;
    }

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
          generateMode: shotGroupData.generateMode || 'independent',
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
          <div class="node-title">分镜组: ${escapeHtml(node.title)}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field">
            <div class="label">分镜组: ${escapeHtml(node.data.groupId || node.data.group_id)}</div>
            <div class="gen-meta">共 ${node.data.shots.length} 个分镜</div>
          </div>
          <div class="field" style="max-height: 300px; overflow-y: auto;">
            ${shotsHtml}
          </div>
          <div class="field">
            <div class="label">分镜模型</div>
            <select class="shot-group-model">
              <option value="gemini-2.5-pro-image-preview">标准版</option>
              <option value="gemini-3-pro-image-preview">加强版</option>
            </select>
          </div>
          <div class="field btn-row">
            <button class="mini-btn secondary shot-group-detail-btn" type="button">详情</button>
            <div class="gen-container" style="flex: 1;">
              <button class="gen-btn gen-btn-main shot-group-generate-btn" type="button" style="background: #22c55e; color: white;">独立分镜</button>
              <button class="gen-btn gen-btn-caret" type="button" aria-label="选择模式">▾</button>
              <div class="gen-menu">
                <div class="gen-item" data-mode="independent">独立分镜</div>
                <div class="gen-item" data-mode="merged">合并分镜</div>
              </div>
            </div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const detailBtn = el.querySelector('.shot-group-detail-btn');
      const generateBtn = el.querySelector('.shot-group-generate-btn');
      const genCaretBtn = el.querySelector('.gen-btn-caret');
      const genMenu = el.querySelector('.gen-menu');
      const genItems = el.querySelectorAll('.gen-item');
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

      genCaretBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        genMenu.classList.toggle('show');
      });

      genItems.forEach(item => {
        item.addEventListener('click', (e) => {
          e.stopPropagation();
          const mode = item.dataset.mode;
          node.data.generateMode = mode;
          generateBtn.textContent = item.textContent;
          genMenu.classList.remove('show');
          try{ autoSaveWorkflow(); } catch(e){}
        });
      });
      
      // 恢复保存的生成模式
      if(node.data.generateMode === 'merged'){
        generateBtn.textContent = '合并分镜';
      } else {
        generateBtn.textContent = '独立分镜';
      }

      generateBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const mode = node.data.generateMode;
        if(mode === 'independent'){
          generateShotFramesIndependent(id, node);
        } else {
          generateShotFramesMerged(id, node);
        }
      });

      detailBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openShotGroupModal(node.data, id);
      });

      canvasEl.appendChild(el);
      setSelected(id);
      return id;
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

    // 生成分镜图节点 - 合并分镜模式
    function generateShotFramesMerged(shotGroupNodeId, shotGroupNode){
      const shots = shotGroupNode.data.shots || [];
      if(shots.length === 0){
        showToast('分镜组中没有分镜数据', 'warning');
        return;
      }

      // 获取当前画布的视频比例
      const currentRatio = state.ratio || '16:9';
      
      // 判断是横屏还是竖屏
      const [width, height] = currentRatio.split(':').map(Number);
      const isLandscape = width > height;
      const arrangement = isLandscape ? '从上到下' : '从左到右';
      
      // 构建合并分镜的提示词
      const shotDescriptions = [];
      const allCharacterNames = new Set();
      const allLocationInfo = [];
      
      // 用于记录角色出现的顺序
      const characterOrder = [];
      const characterSet = new Set();
      
      shots.forEach((shot, index) => {
        // 构建镜头描述（从各个字段组合）
        const descParts = [];
        if(shot.opening_frame_description) descParts.push(shot.opening_frame_description);
        if(shot.description) descParts.push(shot.description);
        if(shot.action) descParts.push(shot.action);
        if(shot.scene_detail) descParts.push(shot.scene_detail);
        
        let imagePrompt = descParts.join('，');
        
        // 收集角色名（按出现顺序）
        const characterPattern = /【【([^】]+)】】/g;
        let match;
        while((match = characterPattern.exec(imagePrompt)) !== null){
          const name = match[1].trim();
          if(name && !characterSet.has(name)){
            characterSet.add(name);
            characterOrder.push(name);
          }
        }
        
        // 收集场景信息（去重）
        if(shot.db_location_id && shot.location_name){
          const exists = allLocationInfo.find(loc => loc.id === shot.db_location_id);
          if(!exists){
            allLocationInfo.push({
              name: shot.location_name,
              pic: shot.db_location_pic,
              id: shot.db_location_id
            });
          }
        }
        
        // 保留完整的镜头描述（包含角色标记）
        shotDescriptions.push(`第${index + 1}镜头：${imagePrompt.trim()}`);
      });
      
      // 构建图片提示词（不包含角色和场景说明，这部分在生成时动态添加）
      let imagePrompt = `**任务**：生成一张垂直排列的多格电影分镜图（Filmstrip Storyboard）。**要求**：按照${arrangement}的顺序排列排列，画面间有细微黑线分隔，严禁出现任何文字、数字或水印。\n\n`;
      imagePrompt += shotDescriptions.join('\n');
      
      // 计算合并分镜的总时长（所有镜头时长累加）
      const totalDuration = shots.reduce((sum, shot) => {
        const duration = parseFloat(shot.duration) || 0;
        return sum + duration;
      }, 0);

      // 收集所有镜头的对话数据
      const allDialogues = [];
      shots.forEach(shot => {
        if(shot.dialogue && Array.isArray(shot.dialogue) && shot.dialogue.length > 0){
          allDialogues.push(...shot.dialogue);
        }
      });
      
      // 使用第一个子节点的shot_number作为合并分镜的shot_number
      const firstShotNumber = shots.length > 0 ? shots[0].shot_number : 'merged';
      
      // 构建合并分镜的shotData
      const mergedShotData = {
        shot_id: 'merged',
        shot_number: firstShotNumber,
        description: `包含${shots.length}个镜头的合并分镜`,
        opening_frame_description: imagePrompt,
        duration: totalDuration,
        shot_type: '合并分镜',
        camera_movement: '',
        // 存储所有角色和场景信息，用于生成图片时使用
        allCharacterNames: characterOrder,
        allLocationInfo: allLocationInfo,
        arrangement: arrangement,
        isMerged: true,
        // 存储完整的shots数组，用于视频提示词
        shots: shots,
        // 合并所有镜头的对话数据，用于生成对话组节点
        dialogue: allDialogues
      };

      // 创建一个合并分镜节点
      const shotFrameNodeId = createShotFrameNode({
        x: shotGroupNode.x + 400,
        y: shotGroupNode.y,
        shotData: mergedShotData,
        model: shotGroupNode.data.model
      });

      // 创建从分镜组到分镜图节点的连接
      state.connections.push({
        id: state.nextConnId++,
        from: shotGroupNodeId,
        to: shotFrameNodeId
      });

      renderConnections();
      renderImageConnections();
      renderFirstFrameConnections();
      renderVideoConnections();
      try{ autoSaveWorkflow(); } catch(e){}
      showToast('已创建合并分镜节点', 'success');
    }

    // 将视频提示词JSON转换为可读文本格式
    function convertVideoPromptToText(jsonString){
      try {
        const data = JSON.parse(jsonString);
        
        // 如果是数组（合并分镜模式）
        if(Array.isArray(data)){
          return data.map((shot, index) => {
            let text = `【镜头${index + 1}】\n`;
            if(shot.duration) text += `时长：${shot.duration}秒\n`;
            if(shot.time_of_day) text += `时间：${shot.time_of_day}\n`;
            if(shot.weather) text += `天气：${shot.weather}\n`;
            if(shot.location_name) text += `场景：${shot.location_name}\n`;
            if(shot.shot_type) text += `镜头类型：${shot.shot_type}\n`;
            if(shot.camera_movement) text += `运镜：${shot.camera_movement}\n`;
            if(shot.description) text += `描述：${shot.description}\n`;
            if(shot.scene_detail) text += `场景细节：${shot.scene_detail}\n`;
            if(shot.action) text += `动作：${shot.action}\n`;
            if(shot.mood) text += `情绪：${shot.mood}\n`;
            if(shot.dialogue && Array.isArray(shot.dialogue) && shot.dialogue.length > 0){
              text += `对话：${shot.dialogue.map(d => `${d.character_name}: ${d.text}`).join('; ')}\n`;
            }
            if(shot.audio_notes) text += `音频备注：${shot.audio_notes}\n`;
            if(shot.environment_sound) text += `环境音：${shot.environment_sound}\n`;
            if(shot.background_music) text += `背景音乐：${shot.background_music}\n`;
            return text;
          }).join('\n');
        }
        
        // 如果是单个对象（独立分镜模式）
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
      let videoPromptJson;
      if(shotData.isMerged && shotData.shots){
        // 合并分镜模式：过滤每个shot的无用字段
        const filteredShots = shotData.shots.map(shot => {
          const filtered = {...shot};
          delete filtered.shot_id;
          delete filtered.shot_number;
          delete filtered.location_id;
          delete filtered.opening_frame_description;
          delete filtered.allCharacterNames;
          delete filtered.allLocationInfo;
          delete filtered.arrangement;
          delete filtered.isMerged;
          delete filtered.shots;
          delete filtered.db_location_pic;
          delete filtered.characters_present;
          delete filtered.db_location_id;
          return filtered;
        });
        videoPromptJson = JSON.stringify(filteredShots, null, 2);
      } else {
        // 独立分镜模式：过滤掉不需要的字段
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
        
        videoPromptJson = JSON.stringify(filteredShotData, null, 2);
      }
      
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
          isMerged: shotData.isMerged || false,
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
          <div class="node-title">分镜: ${node.title}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field">
            <div class="label">分镜信息</div>
            <div class="gen-meta">${escapeHtml(node.data.description)}</div>
            <div class="gen-meta" style="margin-top: 4px;">时长: ${node.data.duration}秒 | ${escapeHtml(node.data.shotType)} | ${escapeHtml(node.data.cameraMovement)}</div>
          </div>
          <div class="field">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <div class="label" style="margin: 0;">图片提示词</div>
              <button class="mini-btn shot-frame-image-expand-btn" type="button" style="font-size: 11px; padding: 4px 8px;" title="放大编辑">⤢</button>
            </div>
            <textarea class="shot-frame-image-prompt" rows="3" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 6px; font-size: 12px; resize: vertical;">${escapeHtml(node.data.imagePrompt)}</textarea>
          </div>
          <div class="field">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <div class="label" style="margin: 0;">视频提示词</div>
              <div style="display: flex; gap: 8px;">
                <button class="mini-btn secondary reduce-violation-btn" type="button" style="font-size: 11px; padding: 4px 8px;">视频生成失败，请点此次按钮</button>
                <button class="mini-btn shot-frame-video-expand-btn" type="button" style="font-size: 11px; padding: 4px 8px;" title="放大编辑">⤢</button>
              </div>
            </div>
            <textarea class="shot-frame-video-prompt" rows="3" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 6px; font-size: 12px; resize: vertical;">${escapeHtml(node.data.videoPromptText || node.data.videoPrompt)}</textarea>
          </div>
          <div class="field shot-frame-image-field" style="display:${node.data.imageUrl ? 'block' : 'none'};">
            <div class="label">生成的图片</div>
            <img class="shot-frame-image" src="${node.data.imageUrl}" style="width: 100%; border-radius: 6px; cursor: pointer;" />
          </div>
          <div class="field">
            <div class="label">分镜模型</div>
            <select class="shot-frame-model">
              <option value="gemini-2.5-pro-image-preview">标准版 (2算力)</option>
              <option value="gemini-3-pro-image-preview">加强版 (6算力)</option>
            </select>
          </div>
          <div class="field">
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
          <div class="field shot-frame-preview-field" style="position: relative;">
            <div class="port first-frame-port" title="连接图片节点（视频首帧）"></div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <div class="label" style="margin: 0;">视频首帧</div>
              <div class="gen-container shot-frame-image-selector-container" style="display: none;">
                <button class="mini-btn shot-frame-image-selector-btn" type="button" style="font-size: 11px; padding: 4px 8px; background: white; color: #333; border: 1px solid #ddd;">选择图片</button>
                <button class="gen-btn-caret" type="button" aria-label="选择图片" style="font-size: 11px; padding: 4px 6px;">▾</button>
                <div class="gen-menu shot-frame-image-menu">
                </div>
              </div>
            </div>
            <img class="shot-frame-preview-image" src="${node.data.previewImageUrl || ''}" style="width: 100%; border-radius: 6px; cursor: pointer; display: ${node.data.previewImageUrl ? 'block' : 'none'};" />
          </div>
          <div class="field">
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
          <div class="field">
            <div class="label">视频时长</div>
            <select class="shot-frame-video-duration">
              <option value="5" selected>5秒</option>
              <option value="10">10秒</option>
            </select>
          </div>
          <div class="field">
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
      const imageExpandBtn = el.querySelector('.shot-frame-image-expand-btn');
      const videoExpandBtn = el.querySelector('.shot-frame-video-expand-btn');
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

      // 获取所有连接的图片节点（包括输出端口连接的和首帧连接的）
      function getConnectedImageNodes(){
        // 从分镜节点的输出端口连接的图片节点（分镜节点 -> 图片节点）
        const outputConnectedImages = state.connections
          .filter(c => c.from === id)
          .map(c => state.nodes.find(n => n.id === c.to))
          .filter(n => n && n.type === 'image' && n.data.url);
        
        // 连接到分镜节点输出端口的图片节点（图片节点 -> 分镜节点右侧）
        const inputConnectedImages = state.connections
          .filter(c => c.to === id)
          .map(c => state.nodes.find(n => n.id === c.from))
          .filter(n => n && n.type === 'image' && n.data.url);
        
        // 通过首帧连接的图片节点
        const firstFrameConnectedImages = state.firstFrameConnections
          .filter(c => c.to === id)
          .map(c => state.nodes.find(n => n.id === c.from))
          .filter(n => n && n.type === 'image' && n.data.url);
        
        // 合并并去重
        const allImages = [...outputConnectedImages, ...inputConnectedImages, ...firstFrameConnectedImages];
        const uniqueImages = allImages.filter((img, index, self) => 
          index === self.findIndex(i => i.id === img.id)
        );
        
        return uniqueImages;
      }

      // 更新图片选择菜单
      function updateImageSelectionMenu(){
        const connectedImageNodes = getConnectedImageNodes();
        
        if(connectedImageNodes.length > 1 && imageMenu){
          // 有多个图片节点，显示选择按钮
          imageSelectorContainer.style.display = 'flex';
          
          // 清空并重新填充菜单
          imageMenu.innerHTML = '';
          connectedImageNodes.forEach((imgNode, index) => {
            const menuItem = document.createElement('div');
            menuItem.className = 'gen-item';
            menuItem.textContent = imgNode.title || imgNode.data.name || `图片${index + 1}`;
            menuItem.dataset.nodeId = imgNode.id;
            imageMenu.appendChild(menuItem);
            
            menuItem.addEventListener('click', (e) => {
              e.stopPropagation();
              node.data.previewImageUrl = imgNode.data.url;
              previewImageEl.src = proxyImageUrl(imgNode.data.url);
              previewImageEl.style.display = 'block';
              imageMenu.classList.remove('show');
              
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
          // 只有一个或没有图片节点，隐藏选择按钮
          imageSelectorContainer.style.display = 'none';
        }
      }

      // 更新预览图
      function updatePreviewImage(){
        const connectedImageNodes = getConnectedImageNodes();
        
        if(connectedImageNodes.length > 0){
          // 如果已有预览图URL且该图片仍然存在，保持不变
          const existingImage = connectedImageNodes.find(n => n.data.url === node.data.previewImageUrl);
          
          if(!existingImage){
            // 否则选择第一个或随机一个
            const imageNode = connectedImageNodes.length === 1 
              ? connectedImageNodes[0]
              : connectedImageNodes[Math.floor(Math.random() * connectedImageNodes.length)];
            
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

      imagePromptEl.addEventListener('input', () => {
        node.data.imagePrompt = imagePromptEl.value;
      });

      videoPromptEl.addEventListener('input', () => {
        node.data.videoPromptText = videoPromptEl.value;
      });

      // 图片提示词放大按钮
      imageExpandBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        showPromptExpandModal(imagePromptEl, '图片提示词', (newValue) => {
          node.data.imagePrompt = newValue;
        });
      });

      // 视频提示词放大按钮
      videoExpandBtn.addEventListener('click', (e) => {
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

    function showPromptExpandModal(textareaEl, title, onUpdate) {
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

      // 自动聚焦到文本框末尾
      expandTextarea.focus();
      expandTextarea.setSelectionRange(expandTextarea.value.length, expandTextarea.value.length);
    }
