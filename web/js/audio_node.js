    // ===== 音频节点 =====
    function createAudioNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      let x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      let y = Math.max(MIN_NODE_Y, opts && typeof opts.y === 'number' ? opts.y : viewportPos.y);

      if (opts && opts.checkCollision) {
        const avail = findNearestAvailablePosition(x, y, 200, 150);
        x = avail.x;
        y = Math.max(MIN_NODE_Y, avail.y);
      }

      const node = {
        id,
        type: 'audio',
        title: opts?.title || '音频',
        x,
        y,
        data: {
          url: opts?.data?.url || '',
          name: opts?.data?.name || '',
          file: null,
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node audio-node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';

      el.innerHTML = `
        <div class="port audio-input-port" data-port-type="audio" title="${window.t ? window.t('audio') : '音频输入'}"></div>
        <div class="port output" title="${window.t ? window.t('node_output_port_video') : '输出（连接到图生视频节点）'}"></div>
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>${escapeHtml(node.title)}</div>
          <button class="icon-btn" title="${window.t ? window.t('node_delete_btn') : '删除'}">×</button>
        </div>
        <div class="node-body">
          <div class="field field-collapsible">
            <div class="label" data-i18n="node_audio_file_label">${window.t ? window.t('node_audio_file_label') : '音频文件'}</div>
            <input class="audio-file" type="file" accept="audio/*" />
          </div>
          <div class="field field-always-visible audio-preview-field" style="display:none;">
            <div class="audio-node-preview">
              <span class="audio-node-name"></span>
            </div>
            <audio class="audio-node-player" controls style="width: 100%; height: 32px; margin-top: 4px;"></audio>
          </div>
          <div class="field field-collapsible audio-preview-actions-field" style="display:none;">
            <div class="preview-row" style="margin-top: 4px;">
              <button class="mini-btn audio-clear" type="button" data-i18n="node_clear_btn">${window.t ? window.t('node_clear_btn') : '清除'}</button>
              <button class="mini-btn audio-add-timeline-btn" type="button" style="display:none; background:#10b981; color:white;" data-i18n="dialogue_add_timeline">${window.t ? window.t('dialogue_add_timeline') : '添加到时间轴'}</button>
            </div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const fileEl = el.querySelector('.audio-file');
      const outputPort = el.querySelector('.port.output');
      const previewField = el.querySelector('.audio-preview-field');
      const previewActionsField = el.querySelector('.audio-preview-actions-field');
      const nameEl = el.querySelector('.audio-node-name');
      const playerEl = el.querySelector('.audio-node-player');
      const clearBtn = el.querySelector('.audio-clear');
      const addTimelineBtn = el.querySelector('.audio-add-timeline-btn');

      // 显示"添加到时间轴"按钮（当音频来自对话组时）
      if(node.data.sourceNodeId !== undefined && node.data.sourceNodeId !== null){
        addTimelineBtn.style.display = 'inline-block';
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

      function setAudioFromFile(file, serverUrl){
        node.data.file = file;
        node.data.name = file ? file.name : '';
        if(node.data.url && node.data.url.startsWith('blob:')) URL.revokeObjectURL(node.data.url);
        node.data.url = serverUrl || (file ? URL.createObjectURL(file) : '');
        if(node.data.url){
          playerEl.src = serverUrl || node.data.url;
          const displayName = node.data.name.length > 15 ? node.data.name.substring(0, 15) + '...' : node.data.name;
          nameEl.textContent = '🎵 ' + displayName;
          nameEl.title = node.data.name;
          previewField.style.display = 'block';
          previewActionsField.style.display = 'block';
        } else {
          playerEl.removeAttribute('src');
          playerEl.load();
          previewField.style.display = 'none';
          previewActionsField.style.display = 'none';
          nameEl.textContent = '';
        }
      }

      fileEl.addEventListener('change', async () => {
        const file = fileEl.files && fileEl.files[0];
        if(!file) return;
        setAudioFromFile(file);
        fileEl.value = '';
        try {
          showToast(window.t ? window.t('uploading_audio') : '正在上传音频...', 'info');
          const permanentUrl = await uploadFile(file);
          if(permanentUrl){
            node.data.url = permanentUrl;
            playerEl.src = permanentUrl;
            showToast(window.t ? window.t('audio_upload_success') : '音频上传成功', 'success');
            safeAutoSave()
          }
        } catch(error){
          console.error('音频上传失败:', error);
          showToast(window.t ? window.t('audio_upload_failed') : '音频上传失败', 'error');
        }
      });

      clearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        try{ playerEl.pause(); } catch(err){}
        setAudioFromFile(null);
      });

      // "添加到时间轴"按钮点击事件
      addTimelineBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if(!node.data.url){
          showToast(window.t ? window.t('dialogue_no_audio_to_add') : '没有可添加的音频', 'error');
          return;
        }
        const audioName = node.data.name || '音频';
        try {
          const duration = await getAudioDuration(node.data.url);
          addAudioToTimeline(node.id, node.data.dialogueIndex != null ? node.data.dialogueIndex : 0, node.data.url, audioName, duration);
        } catch(err) {
          console.warn('获取音频时长失败，使用默认时长:', err);
          addAudioToTimeline(node.id, node.data.dialogueIndex != null ? node.data.dialogueIndex : 0, node.data.url, audioName, 5);
        }
      });

      // 恢复已保存的数据
      if(node.data.url){
        setAudioFromFile(null, node.data.url);
      }

      addDebugButtonToNode(el, node);
      canvasEl.appendChild(el);
      setSelected(id);
      return id;
    }
