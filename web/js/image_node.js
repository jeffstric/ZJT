    /**
     * 图片节点是否允许发起编辑/涂色。
     * 必须等到服务器上传完成（有 url）且不在 uploading 状态。
     * 仅有本地 file / 本地预览不够，避免大图上传中途误点编辑。
     *
     * @param {object|null|undefined} data node.data
     * @returns {{ allowed: boolean, reason: 'ok'|'no_image'|'uploading' }}
     */
    function canEditImageNode(data) {
      if (!data) {
        return { allowed: false, reason: 'no_image' };
      }
      if (data.uploading) {
        return { allowed: false, reason: 'uploading' };
      }
      const url = typeof data.url === 'string' ? data.url.trim() : '';
      if (url) {
        return { allowed: true, reason: 'ok' };
      }
      return { allowed: false, reason: 'no_image' };
    }

    /**
     * 解析编辑提交数据：始终优先使用服务器 URL，禁止上传中途用本地 File 绕过。
     *
     * @param {object|null|undefined} data node.data
     * @returns {{ ok: boolean, reason?: string, submitData?: string }}
     */
    function resolveImageEditSubmitData(data) {
      const gate = canEditImageNode(data);
      if (!gate.allowed) {
        return { ok: false, reason: gate.reason };
      }
      return { ok: true, submitData: String(data.url).trim() };
    }

    /**
     * 上传/编辑门禁失败时的提示文案。
     * @param {'no_image'|'uploading'|string} reason
     * @param {(key: string, fallback: string) => string} [t]
     */
    function getImageUploadBlockMessage(reason, t) {
      const translate = typeof t === 'function'
        ? t
        : (key, fallback) => (window.t ? (window.t(key) || fallback) : fallback);
      if (reason === 'uploading') {
        return translate('image_node_uploading_wait', '图片上传中，请稍候...');
      }
      return translate('upload_or_generate_image_first', '请先上传或生成图片');
    }

    function createImageNode(opts){
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
      const defaultRatio = state.ratio || ratioSelectEl.value || '9:16';
      
      // 默认图片模型：优先使用 gpt-image-2
      let defaultImageModel = 'gpt-image-2';
      if(window.TaskConfig && window.TaskConfig.isLoaded()) {
        const options = window.TaskConfig.getModelOptionsForCategory('image_edit');
        const gptImage2 = options.find(o => o.value === 'gpt-image-2');
        if(gptImage2) {
          defaultImageModel = gptImage2.value;
        } else if(options.length > 0) {
          defaultImageModel = options[0].value;
        }
      }
      
      const node = {
        id,
        type: 'image',
        title: window.t ? window.t('image') : '图片',
        x,
        y,
        data: {
          file: null,
          url: '',
          name: '',
          preview: '',
          prompt: '',
          ratio: defaultRatio,
          model: defaultImageModel,
          drawCount: 1,
          project_id: null,
          uploading: false,
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';

      el.innerHTML = `
        <div class="port reference" title="${window.t ? window.t('image_node_reference_port') : '参考端口（接收其他图片作为参考）'}"></div>
        <div class="port input" title="${window.t ? window.t('image_node_input_port') : '输入（连接分镜节点）'}"></div>
        <div class="port output" title="${window.t ? window.t('image_node_output_port') : '输出（连接到图生视频节点）'}"></div>
        <div class="node-header">
          <div class="node-title" data-i18n="image"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="4" y="5" width="16" height="14" rx="2"/><path d="M7 15L10 12L13 15L16 11L20 17H4L7 15Z" fill="currentColor" opacity="0.35"/></svg>${window.t ? window.t('image') : '图片'}</div>
          <button class="icon-btn" title="${window.t ? window.t('node_delete_btn') : '删除'}">×</button>
        </div>
        <div class="node-body">
          <div class="field field-always-visible">
            <div class="preview-row image-preview-row" style="display:none;">
              <img class="preview image-preview" />
            </div>
          </div>
          <div class="reference-images-section" style="display:none;">
            <div class="reference-images-header">
              <span data-i18n="image_node_reference_images">${window.t ? window.t('image_node_reference_images') : '参考图片'} (<span class="reference-images-count">0</span>)</span>
            </div>
            <div class="reference-images-grid"></div>
          </div>
          <div class="field field-collapsible">
            <div class="label" data-i18n="image_node_upload_label">${window.t ? window.t('image_node_upload_label') : '上传图片'}</div>
            <input class="image-file" type="file" accept="image/*" />
            <div style="display: flex; gap: 8px; margin-top: 8px;">
              <button class="mini-btn image-clear" type="button" data-i18n="image_node_clear_btn">${window.t ? window.t('image_node_clear_btn') : '清除'}</button>
              <button class="mini-btn image-download-icon-btn" type="button" data-i18n="image_node_download_btn">${window.t ? window.t('image_node_download_btn') : '下载'}</button>
            </div>
          </div>
          <div class="field field-collapsible">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <div class="label" style="margin: 0;" data-i18n="image_node_prompt_label">${window.t ? window.t('image_node_prompt_label') : '编辑提示词（可选）'}</div>
              <button class="mini-btn image-prompt-expand-btn" type="button" style="font-size: 11px; padding: 4px 8px;" title="${window.t ? window.t('script_expand_btn') : '放大编辑'}" data-i18n="script_expand_btn:title">⤢</button>
            </div>
            <textarea class="image-prompt" rows="2" placeholder="${window.t ? window.t('image_node_prompt_placeholder') : '输入提示词进行图片编辑'}" data-i18n="image_node_prompt_placeholder:placeholder"></textarea>
          </div>
          <div class="field field-collapsible">
            <div class="label" data-i18n="image_node_model_label">${window.t ? window.t('image_node_model_label') : '模型'}</div>
            <select class="image-model"></select>
          </div>
          <div class="field field-collapsible image-ratio-field">
            <div class="label" data-i18n="image_node_ratio_label">${window.t ? window.t('image_node_ratio_label') : '图片比例'}</div>
            <select class="image-ratio">
              <option value="9:16" data-i18n="image_ratio_portrait_9_16">${window.t ? window.t('image_ratio_portrait_9_16') : '竖屏 (9:16)'}</option>
              <option value="16:9" data-i18n="image_ratio_landscape_16_9">${window.t ? window.t('image_ratio_landscape_16_9') : '横屏 (16:9)'}</option>
              <option value="1:1" data-i18n="image_ratio_square_1_1">${window.t ? window.t('image_ratio_square_1_1') : '正方形 (1:1)'}</option>
              <option value="3:4" data-i18n="image_ratio_portrait_3_4">${window.t ? window.t('image_ratio_portrait_3_4') : '竖屏 (3:4)'}</option>
              <option value="4:3" data-i18n="image_ratio_landscape_4_3">${window.t ? window.t('image_ratio_landscape_4_3') : '横屏 (4:3)'}</option>
            </select>
          </div>
          <div class="field field-collapsible">
            <button class="mini-btn image-camera-control-btn" type="button" style="width:100%;background:#f0fdf4;color:#15803d;border:1px solid #bbf7d0;" data-i18n="image_node_camera_control_btn">${window.t ? window.t('image_node_camera_control_btn') : '相机控制'}</button>
          </div>
          <div class="field field-collapsible">
            <div class="btn-row" style="display: flex; gap: 8px;">
              <div class="gen-container">
                <button class="gen-btn gen-btn-main image-edit-btn" type="button" data-i18n="image_node_edit_btn">${window.t ? window.t('image_node_edit_btn') : '编辑图片'}</button>
                <button class="gen-btn gen-btn-caret" type="button" aria-label="${window.t ? window.t('draw_count_menu') : '选择抽卡次数'}" data-i18n="draw_count_menu:aria-label">▾</button>
                <div class="gen-menu">
                  <div class="gen-item" data-count="1">X1</div>
                  <div class="gen-item" data-count="2">X2</div>
                  <div class="gen-item" data-count="3">X3</div>
                  <div class="gen-item" data-count="4">X4</div>
                </div>
              </div>
              <button class="mini-btn secondary image-coloring-btn" type="button" style="border-radius: 10px;" data-i18n="image_node_coloring_btn">${window.t ? window.t('image_node_coloring_btn') : '涂色编辑'}</button>
              <button class="mini-btn secondary image-doodle-btn" type="button" style="border-radius: 10px;" data-i18n="image_node_doodle_btn">${window.t ? window.t('image_node_doodle_btn') : '涂鸦编辑'}</button>
            </div>
            <div class="gen-meta image-draw-count-label"></div>
            <div class="muted image-edit-status" style="display:none;"></div>
          </div>
          <div class="field field-collapsible image-confirm-field" style="display:none;">
            <button class="mini-btn image-confirm-shot-btn" type="button" style="background: #10b981; color: white; width: 100%;" data-i18n="image_node_confirm_shot_btn">${window.t ? window.t('image_node_confirm_shot_btn') : '确认分镜图'}</button>
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
            const index = refConns.indexOf(conn) + 1;
            item.innerHTML = `
              <img src="${escapeHtml(imgUrl)}" alt="${escapeHtml(imgLabel)}" title="${escapeHtml(imgLabel)}" />
              <span class="reference-image-label">图${index}</span>
              <button class="reference-image-remove" data-conn-id="${escapeHtml(conn.id)}">×</button>
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
                safeAutoSave()
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
                showToast(window.t ? window.t('circular_reference_error') : '不能创建循环参考', 'error');
              } else {
                // 检查参考图数量限制
                const currentRefCount = state.referenceConnections.filter(c => c.to === id).length;
                const maxRefs = node.data.model === 'gemini-2.5-flash-image-preview' ? 5 : 13;
                if(currentRefCount >= maxRefs){
                  showToast(window.t ? window.t('max_reference_images_msg').replace('${maxRefs}', maxRefs) : `最多支持${maxRefs}张参考图`, 'error');
                } else {
                  state.referenceConnections.push({
                    id: state.nextReferenceConnId++,
                    from: state.connecting.fromId,
                    to: id
                  });
                  renderReferenceConnections();
                  updateReferenceImages();
                  safeAutoSave()
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
              renderAllConnections();
              
              // 更新分镜节点的预览图和选择菜单
              if(fromNode.updatePreview){
                fromNode.updatePreview();
              }
              
              safeAutoSave()
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
      const doodleBtn = el.querySelector('.image-doodle-btn');
      const statusEl = el.querySelector('.image-edit-status');
      const drawCountLabel = el.querySelector('.image-draw-count-label');
      const genCaret = el.querySelector('.gen-btn-caret');
      const genMenu = el.querySelector('.gen-menu');
      const confirmFieldEl = el.querySelector('.image-confirm-field');
      const confirmShotBtn = el.querySelector('.image-confirm-shot-btn');
      const cameraControlBtn = el.querySelector('.image-camera-control-btn');

      // 动态填充图片模型选项（从 TaskConfig 获取）
      let firstImageModelValue = 'gpt-image-2';
      function populateImageModelOptions() {
        if(!modelEl) return;
        modelEl.innerHTML = '';
        if(window.TaskConfig && window.TaskConfig.isLoaded()) {
          const options = window.TaskConfig.getModelOptionsForCategory('image_edit');
          const gptImage2 = options.find(o => o.value === 'gpt-image-2');
          if(gptImage2) {
            firstImageModelValue = gptImage2.value;
          } else if(options.length > 0) {
            firstImageModelValue = options[0].value;
          }
          options.forEach(opt => {
            const optEl = document.createElement('option');
            optEl.value = opt.value;
            optEl.dataset.shortKey = opt.value;
            optEl.textContent = opt.label;
            modelEl.appendChild(optEl);
          });
          if (window.ModelCatalog && modelEl.parentElement) {
            window.ModelCatalog.bindSelectTrack(modelEl.parentElement, modelEl, 'image.image_edit', 'task');
          }
        } else {
          // 回退：硬编码选项
          const fallbackOptions = [
            { value: 'gemini', label: '标准版 (2算力)' },
            { value: 'gemini_pro', label: '加强版 (6算力)' },
            { value: 'seedream-5.0', label: 'Seedream 5.0 (6算力)' }
          ];
          fallbackOptions.forEach(opt => {
            const optEl = document.createElement('option');
            optEl.value = opt.value;
            optEl.textContent = opt.label;
            modelEl.appendChild(optEl);
          });
        }
        // 设置默认值为第一个选项
        if(!node.data.model) {
          node.data.model = firstImageModelValue;
        }
        // 确保已保存的模型值在下拉框中可见
        if(modelEl) {
          ensureSelectHasSavedOption(modelEl, node.data.model);
          modelEl.value = node.data.model;
        }
      }
      populateImageModelOptions();

      // 根据模型更新图片比例选项（从后端配置获取）
      function updateImageRatioOptions(model) {
        if(!ratioEl) return;
        const currentRatio = ratioEl.value;
        const modelConfigs = getModelConfigs();
        const config = modelConfigs[model];
        const ratioField = el.querySelector('.image-ratio-field') || ratioEl.closest('.field');

        const labelMap = {
          '9:16': '竖屏 (9:16)',
          '16:9': '横屏 (16:9)',
          '1:1': '正方形 (1:1)',
          '3:4': '竖屏 (3:4)',
          '4:3': '横屏 (4:3)',
          '2:3': '竖屏 (2:3)',
          '3:2': '横屏 (3:2)'
        };

        if(config && Array.isArray(config.ratios) && config.ratios.length === 0) {
          if(ratioField) ratioField.style.display = 'none';
          return;
        }
        if(ratioField) ratioField.style.display = '';

        if(config && config.ratios && config.ratios.length > 0) {
          ratioEl.innerHTML = '';
          config.ratios.forEach(ratio => {
            ratioEl.innerHTML += `<option value="${ratio}">${labelMap[ratio] || ratio}</option>`;
          });
          if(config.ratios.includes(currentRatio)) {
            ratioEl.value = currentRatio;
          } else {
            const defaultRatio = config.default_ratio || config.ratios[0];
            ratioEl.value = defaultRatio;
            node.data.ratio = defaultRatio;
          }
        } else {
          // 降级：使用默认选项
          ratioEl.innerHTML = `
            <option value="9:16">竖屏 (9:16)</option>
            <option value="16:9">横屏 (16:9)</option>
            <option value="1:1">正方形 (1:1)</option>
            <option value="3:4">竖屏 (3:4)</option>
            <option value="4:3">横屏 (4:3)</option>
          `;
          ratioEl.value = currentRatio || '9:16';
        }
      }
      
      // 初始化比例选项
      updateImageRatioOptions(node.data.model);
      if(ratioEl) ratioEl.value = node.data.ratio;
      
      // 应用驱动状态禁用未配置的图片模型选项
      if(modelEl) applyDriverStatusToSelect(modelEl);

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

      function setImageEditActionsDisabled(disabled) {
        if (editBtn) editBtn.disabled = !!disabled;
        if (coloringBtn) coloringBtn.disabled = !!disabled;
        if (doodleBtn) doodleBtn.disabled = !!disabled;
      }

      // 涂色编辑按钮
      if(coloringBtn){
        coloringBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const gate = canEditImageNode(node.data);
          if(!gate.allowed){
            const msg = getImageUploadBlockMessage(gate.reason);
            showToast(msg, gate.reason === 'uploading' ? 'warning' : 'error');
            if (statusEl) {
              statusEl.style.display = 'block';
              setStatusEl(statusEl, msg, gate.reason === 'uploading' ? '#d97706' : '#dc2626');
            }
            return;
          }
          const imageUrl = node.data.url;

          if(window.imageColoringEditor && window.imageColoringEditor.open){
            // Use proxied URL to avoid cross-origin canvas taint
            const safeImageUrl = (typeof proxyImageUrl === 'function') ? proxyImageUrl(imageUrl) : imageUrl;
            window.imageColoringEditor.open(safeImageUrl, id, async (result) => {
              try {
                coloringBtn.disabled = true;
                statusEl.style.display = 'block';
                setStatusEl(statusEl, window.t ? window.t('uploading_image') : '正在上传涂色图片...', '#666');
                
                const coloredImageBlob = await fetch(result.coloredImage).then(r => r.blob());
                const uploadFormData = new FormData();
                uploadFormData.append('file', coloredImageBlob, 'colored_image.png');
                
                const uploadRes = await fetch('/api/video-workflow/upload', {
                  method: 'POST',
                  headers: getAuthHeaders(),
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
                
                setStatusEl(statusEl, window.t ? window.t('fill_complete_msg') : '涂色完成！', '#22c55e');
                showToast(window.t ? window.t('fill_complete_msg') : '涂色完成！', 'success');

                safeAutoSave()
                renderMinimap();
              } catch(err){
                console.error('涂色编辑失败:', err);
                setStatusEl(statusEl, window.t ? window.t('fill_error_msg') : '涂色失败', '#dc2626');
                showToast((window.t ? window.t('fill_error_msg') : '涂色失败: ') + err.message, 'error');
              } finally {
                coloringBtn.disabled = false;
              }
            });
          } else {
            showToast(window.t ? window.t('fill_editor_not_loaded') : '涂色编辑器未加载', 'error');
          }
        });
      }

      // 涂鸦编辑按钮：合成底图+涂鸦上传回填，复用涂色编辑的确认链路
      if(doodleBtn){
        doodleBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const gate = canEditImageNode(node.data);
          if(!gate.allowed){
            const msg = getImageUploadBlockMessage(gate.reason);
            showToast(msg, gate.reason === 'uploading' ? 'warning' : 'error');
            if (statusEl) {
              statusEl.style.display = 'block';
              setStatusEl(statusEl, msg, gate.reason === 'uploading' ? '#d97706' : '#dc2626');
            }
            return;
          }
          if(!(window.imageDoodleEditor && window.imageDoodleEditor.open)){
            showToast(window.t ? window.t('doodle_editor_not_loaded') : '涂鸦编辑器未加载', 'error');
            return;
          }

          const safeImageUrl = (typeof proxyImageUrl === 'function') ? proxyImageUrl(node.data.url) : node.data.url;
          window.imageDoodleEditor.open(safeImageUrl, {
            nodeId: id,
            onComplete: async ({ blob }) => {
              try {
                doodleBtn.disabled = true;
                statusEl.style.display = 'block';
                setStatusEl(statusEl, window.t ? window.t('doodle_uploading') : '正在上传涂鸦图片...', '#666');

                const file = new File([blob], `doodle_${Date.now()}.png`, { type: 'image/png' });
                const uploadedUrl = await uploadFile(file);
                if(!uploadedUrl) throw new Error(window.t ? window.t('image_node_upload_failed') : '图片上传失败');

                node.data.url = uploadedUrl;
                node.data.preview = uploadedUrl;
                imagePreviewImg.src = proxyImageUrl(uploadedUrl);
                imagePreviewRow.style.display = 'block';

                setStatusEl(statusEl, window.t ? window.t('doodle_done') : '涂鸦已应用！', '#22c55e');
                showToast(window.t ? window.t('doodle_done') : '涂鸦已应用！', 'success');

                safeAutoSave()
                renderMinimap();
              } catch(err){
                console.error('涂鸦编辑失败:', err);
                setStatusEl(statusEl, window.t ? window.t('doodle_upload_fail') : '涂鸦上传失败', '#dc2626');
                showToast((window.t ? window.t('doodle_upload_fail') : '涂鸦上传失败: ') + (err.message || ''), 'error');
              } finally {
                doodleBtn.disabled = false;
              }
            }
          });
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
          showToast(window.t ? window.t('set_as_first_frame_msg') : '已设置为视频首帧', 'success');
          safeAutoSave()
        }
      });

      // 初始化时检查确认按钮可见性
      updateConfirmButtonVisibility();

      function updateDrawCountLabel(){
        { const _t = window.t ? window.t('draw_count_x', { count: node.data.drawCount }) : null; drawCountLabel.textContent = (_t && _t !== 'draw_count_x') ? _t : `抽卡次数：X${node.data.drawCount}`; }
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
        // 模型切换时更新比例选项
        updateImageRatioOptions(modelEl.value);
      });

      imageFileEl.addEventListener('change', async () => {
        const file = imageFileEl.files && imageFileEl.files[0];
        if(!file) return;
        if(!file.type.startsWith('image/')){
          showToast(window.t ? window.t('image_node_select_image') : '请选择图片文件', 'error');
          imageFileEl.value = '';
          return;
        }

        const previousUrl = node.data.url || '';
        const previousPreview = node.data.preview || '';
        const previousName = node.data.name || '';

        node.data.file = file;
        node.data.uploading = true;
        // 上传中清空 url，避免仍用旧图发起编辑
        node.data.url = '';
        setImageEditActionsDisabled(true);
        if (statusEl) {
          statusEl.style.display = 'block';
          setStatusEl(
            statusEl,
            window.t ? window.t('uploading_image') : '正在上传图片...',
            '#666'
          );
        }

        try {
          const localPreview = await readFileAsDataUrl(file);
          imagePreviewImg.src = localPreview;
          imagePreviewRow.style.display = 'flex';

          const uploadedUrl = await uploadFile(file);
          if(uploadedUrl){
            node.data.url = uploadedUrl;
            node.data.name = file.name;
            node.data.preview = uploadedUrl;
            // 成功后清掉本地 file，强制后续编辑走服务器 URL
            node.data.file = null;
            imagePreviewImg.src = proxyImageUrl(uploadedUrl);

            // 通知所有连接到此图片节点的图生视频节点更新算力显示
            const imageConnections = state.imageConnections.filter(c => c.from === id);
            for(const conn of imageConnections){
              const targetNode = state.nodes.find(n => n.id === conn.to);
              if(targetNode && targetNode.type === 'image_to_video'){
                const targetEl = canvasEl.querySelector(`.node[data-node-id="${conn.to}"]`);
                if(targetEl){
                  // 更新目标节点的URL
                  if(conn.portType === 'start'){
                    targetNode.data.startUrl = uploadedUrl;
                  } else if(conn.portType === 'end'){
                    targetNode.data.endUrl = uploadedUrl;
                  } else if(conn.portType === 'ref-image'){
                    // 更新 referenceUrls 中对应的URL
                    if(!targetNode.data.referenceUrls) targetNode.data.referenceUrls = [];
                    const idx = targetNode.data.referenceUrls.indexOf(previousUrl);
                    if(idx >= 0){
                      targetNode.data.referenceUrls[idx] = uploadedUrl;
                    }
                  }

                  // 触发目标节点的算力更新
                  const updateFn = targetEl._updateComputingPowerDisplay;
                  if(typeof updateFn === 'function') {
                    updateFn();
                  }
                }
              }
            }

            if (statusEl) {
              statusEl.style.display = 'none';
              setStatusEl(statusEl, '', '#666');
            }
            showToast('图片上传成功', 'success');
            safeAutoSave()
          } else {
            // 上传失败：清理本地 file；若有旧图则恢复，否则收起预览
            node.data.file = null;
            if (previousUrl) {
              node.data.url = previousUrl;
              node.data.preview = previousPreview || previousUrl;
              node.data.name = previousName;
              imagePreviewImg.src = proxyImageUrl(previousUrl);
              imagePreviewRow.style.display = 'flex';
            } else {
              node.data.url = '';
              node.data.preview = '';
              node.data.name = '';
              imagePreviewRow.style.display = 'none';
              imagePreviewImg.removeAttribute('src');
            }
            if (statusEl) {
              statusEl.style.display = 'block';
              setStatusEl(
                statusEl,
                window.t ? window.t('image_node_upload_failed') : '图片上传失败',
                '#dc2626'
              );
            }
          }
        } finally {
          node.data.uploading = false;
          setImageEditActionsDisabled(false);
          imageFileEl.value = '';
        }
      });

      imageClearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        node.data.file = null;
        node.data.url = '';
        node.data.name = '';
        node.data.preview = '';
        node.data.uploading = false;
        setImageEditActionsDisabled(false);
        imagePreviewRow.style.display = 'none';
        imagePreviewImg.removeAttribute('src');
      });

      editBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const gate = canEditImageNode(node.data);
        if(!gate.allowed){
          statusEl.style.display = 'block';
          const msg = getImageUploadBlockMessage(gate.reason);
          setStatusEl(statusEl, msg, gate.reason === 'uploading' ? '#d97706' : '#dc2626');
          if (gate.reason === 'uploading') {
            showToast(msg, 'warning');
          }
          return;
        }
        
        if(!node.data.prompt){
          statusEl.style.display = 'block';
          setStatusEl(statusEl, '请先输入编辑提示词或调整相机参数', '#dc2626');
          return;
        }

        editBtn.disabled = true;
        statusEl.style.display = 'block';
        setStatusEl(statusEl, '正在提交任务...');

        try{
          const resolved = resolveImageEditSubmitData(node.data);
          if (!resolved.ok) {
            const msg = getImageUploadBlockMessage(resolved.reason);
            setStatusEl(statusEl, msg, '#dc2626');
            showToast(msg, 'warning');
            editBtn.disabled = false;
            return;
          }
          let submitData = resolved.submitData;

          let finalPrompt = node.data.prompt || '';

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
              y: node.y + offsetY,
              checkCollision: true
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


          renderAllConnections();
          renderReferenceConnections();
          renderMinimap();

          safeAutoSave()

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
                setStatusEl(statusEl, '生成成功，但未获取到图片地址', '#dc2626');
                editBtn.disabled = false;
                showToast('生成成功但未返回图片地址', 'error');
                return;
              }

              setStatusEl(statusEl, `生成完成！共${imageUrls.length}张图片`, '#16a34a');
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

              safeAutoSave()
              renderMinimap();
              showToast('图片编辑成功！', 'success');
              
              // 刷新用户算力显示
              if(typeof fetchComputingPower === 'function'){
                fetchComputingPower();
              }
            },
            (errMsg) => {
              setStatusEl(statusEl, errMsg, '#dc2626');
              editBtn.disabled = false;
              showToast(errMsg || '图片编辑失败', 'error');
            }
          );
        } catch(err){
          setStatusEl(statusEl, err.message || '提交失败', '#dc2626');
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
          showToast(window.t ? window.t('start_download_image') : '开始下载图片', 'success');
        } catch(error) {
          console.error('下载图片失败:', error);
          showToast(window.t ? window.t('download_image_failed') : '下载图片失败', 'error');
        }
      });

      // 相机控制按钮：自动创建相机控制节点并连接
      if(cameraControlBtn){
        cameraControlBtn?.addEventListener('click', (e) => {
          e.stopPropagation();
          if(!node.data.url && !node.data.preview){
            showToast('请先上传或生成图片', 'warning');
            return;
          }
          const cameraNodeId = createCameraControlNode({
            x: node.x + 380,
            y: node.y,
            checkCollision: true
          });
          // 自动连接: image → camera_control
          state.connections.push({
            id: state.nextConnId++,
            from: node.id,
            to: cameraNodeId
          });
          renderConnections();
          renderAllConnections();
          renderMinimap();
          showToast('已创建相机控制节点', 'success');
          safeAutoSave()
        });
      }

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

    // ES Module exports（供 Vitest 测试使用，不影响浏览器全局变量）
    if (typeof module !== 'undefined') {
      module.exports = {
        canEditImageNode,
        resolveImageEditSubmitData,
        getImageUploadBlockMessage,
      };
    }
