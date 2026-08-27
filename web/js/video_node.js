    function createVideoNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      let x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      let y = Math.max(MIN_NODE_Y, opts && typeof opts.y === 'number' ? opts.y : viewportPos.y);

      // 如果启用了碰撞检测，则自动寻找最近的无重叠位置
      if (opts && opts.checkCollision) {
        const avail = findNearestAvailablePosition(x, y, 320, 220);
        x = avail.x;
        y = Math.max(MIN_NODE_Y, avail.y);
      }
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
        <div class="port input" data-i18n="node_input_port:title"></div>
        <div class="port output" data-i18n="node_output_port_dialogue:title"></div>
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="4" y="6" width="16" height="12" rx="2"/><path d="M10 9.5V14.5L14.5 12L10 9.5Z" fill="currentColor"/></svg>${escapeHtml(node.title)}</div>
          <button class="icon-btn" title="${window.t ? window.t('node_delete_btn') : '删除'}">×</button>
        </div>
        <div class="node-body">
          <div class="field field-collapsible">
            <div class="label" data-i18n="node_video_label">${window.t ? window.t('node_video_label') : '视频'}</div>
            <input class="video-file" type="file" accept="video/*" />
          </div>
          <div class="field field-always-visible video-preview-field" style="display:none;">
            <div class="label" data-i18n="node_preview_label">${window.t ? window.t('node_preview_label') : '预览'}</div>
            <div class="video-preview">
              <video class="video-thumb" playsinline></video>
              <div class="video-preview-actions">
                <button class="vp-btn vp-play" type="button" aria-label="${window.t ? window.t('node_play_btn') : '播放'}">▶</button>
                <button class="vp-btn vp-zoom" type="button" aria-label="${window.t ? window.t('node_zoom_btn') : '放大'}">⤢</button>
              </div>
            </div>
            <div class="gen-meta video-name"></div>
          </div>
          <div class="field field-collapsible video-preview-actions-field" style="display:none;">
            <div class="preview-row" style="margin-top: 8px; justify-content: space-between;">
              <div style="display: flex; gap: 8px;">
                <button class="mini-btn video-add-timeline" type="button" data-i18n="node_add_timeline_btn">${window.t ? window.t('node_add_timeline_btn') : '加时间轴'}</button>
                <button class="mini-btn video-download" type="button" data-i18n="node_download_btn">${window.t ? window.t('node_download_btn') : '下载'}</button>
                <button class="mini-btn video-clear" type="button" data-i18n="node_clear_btn">${window.t ? window.t('node_clear_btn') : '清除'}</button>
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
          if(fromNode && (fromNode.type === 'image_to_video' || fromNode.type === 'character' || fromNode.type === 'digital_human')){
            const exists = state.connections.some(c => c.to === id);
            if(!exists){
              state.connections.push({
                id: state.nextConnId++,
                from: state.connecting.fromId,
                to: id
              });
              renderAllConnections();
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
          // 封面帧与悬停播放逻辑已内置于 setupVideoThumbnail（blob: URL 原样透传）
          setupVideoThumbnail(thumbVideo, node.data.url);
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
          showToast(window.t ? window.t('uploading_video') : '正在上传视频...', 'info');
          const permanentUrl = await uploadFile(file);
          if(permanentUrl){
            // 更新为服务器URL（保持封面帧+悬停播放行为）
            node.data.url = permanentUrl;
            setupVideoThumbnail(thumbVideo, permanentUrl);
            showToast(window.t ? window.t('video_upload_success') : '视频上传成功', 'success');

            // 自动保存工作流
            safeAutoSave()
          }
        } catch(error){
          console.error('视频上传失败:', error);
          showToast(window.t ? window.t('video_upload_failed') : '视频上传失败，刷新页面后将丢失', 'error');
        }
      });

      playBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if(!thumbVideo.src) return;
        if(thumbVideo.paused){
          const p = thumbVideo.play();
          if(p && typeof p.catch === 'function') p.catch(() => {});
          playBtn.textContent = '❚❚';
          // 标记手动播放：悬停移开时不强制暂停
          thumbVideo.dataset.manualPlay = '1';
        } else {
          thumbVideo.pause();
          playBtn.textContent = '▶';
          delete thumbVideo.dataset.manualPlay;
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
        delete thumbVideo.dataset.manualPlay;
        setVideoFromFile(null);
      });

      downloadBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if(!node.data.url){
          showToast(window.t ? window.t('no_downloadable_video') : '没有可下载的视频', 'error');
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
        showToast(window.t ? window.t('start_download') : '开始下载', 'success');
      });

      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);
      setSelected(id);
      return id;
    }
