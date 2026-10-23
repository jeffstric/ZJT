    /**
     * 图片节点是否允许发起编辑/涂色。
     * 必须等到服务器上传完成（有 url）且不在 uploading 状态。
     * 仅有本地 file / 本地预览不够，避免大图上传中途误点编辑。
     *
     * @param {object|null|undefined} data node.data
     * @returns {{ allowed: boolean, reason: 'ok'|'no_image'|'uploading' }}
     */
    /**
     * 把一批抽卡任务对回各自的结果格子。
     * 必须按 project_id 对齐，不能先滤掉失败再按下标填：
     * 第一张失败、第二张成功时，成功图会进到第一格，失败格一直停在「生成中」。
     *
     * @param {Array<{project_id?: *, status?: string, result?: *, error?: string, reason?: string}>} tasks
     * @param {Array<{nodeId: *, projectId?: *}>} slots 与提交顺序一致
     * @returns {{ slots: Array<{nodeId: *, projectId: *, outcome: 'success'|'failed', url: *, error: string}>, successCount: number, failCount: number }}
     */
    function planImageBatchResults(tasks, slots) {
      const list = Array.isArray(tasks) ? tasks : [];
      const slotList = Array.isArray(slots) ? slots : [];
      const indexByProject = new Map();
      slotList.forEach((slot, index) => {
        const pid = slot && slot.projectId != null && slot.projectId !== '' ? String(slot.projectId) : '';
        if (pid && !indexByProject.has(pid)) indexByProject.set(pid, index);
      });
      const outcomes = slotList.map((slot) => ({
        nodeId: slot && slot.nodeId,
        projectId: slot && slot.projectId,
        outcome: 'failed',
        url: '',
        error: '生成失败',
      }));
      const claimed = new Set();
      list.forEach((task, index) => {
        if (!task || typeof task !== 'object') return;
        const pid = task.project_id != null && task.project_id !== '' ? String(task.project_id) : '';
        let slotIndex = pid && indexByProject.has(pid) ? indexByProject.get(pid) : -1;
        if (slotIndex < 0 && !pid && index < outcomes.length && !claimed.has(index)) {
          slotIndex = index;
        }
        if (slotIndex < 0 || claimed.has(slotIndex)) return;
        claimed.add(slotIndex);
        const succeeded = task.status === 'SUCCESS' && task.result;
        outcomes[slotIndex] = {
          nodeId: outcomes[slotIndex].nodeId,
          projectId: outcomes[slotIndex].projectId,
          outcome: succeeded ? 'success' : 'failed',
          url: succeeded ? task.result : '',
          error: succeeded
            ? ''
            : (task.error || task.reason || (task.status === 'SUCCESS' ? '生成成功，但未获取到图片地址' : '生成失败')),
        };
      });
      const successCount = outcomes.filter((item) => item.outcome === 'success').length;
      return {
        slots: outcomes,
        successCount,
        failCount: outcomes.length - successCount,
      };
    }

    /**
     * 收集参考图 URL，并按模型实际看到的顺序写「图N是…」。
     * 有底图时底图占图1，参考图从 2 起；无底图时参考图自己就是图1。
     * 纯图片参考只占序号、不写名字。
     *
     * @param {string} prompt
     * @param {Array<{type?: string, data?: object}>} refNodes
     * @param {boolean} hasBaseImage
     * @returns {{ referenceImageUrls: string[], finalPrompt: string }}
     */
    function collectImageReferencePrompt(prompt, refNodes, hasBaseImage) {
      const referenceImageUrls = [];
      const promptSuffix = [];
      let refImageIndex = hasBaseImage ? 2 : 1;
      (refNodes || []).forEach((refNode) => {
        if (!refNode || !refNode.data) return;
        let url = '';
        let label = '';
        if (refNode.type === 'image' && refNode.data.url) {
          url = refNode.data.url;
        } else if (refNode.type === 'character' && refNode.data.reference_image) {
          url = refNode.data.reference_image;
          label = refNode.data.name || '角色';
        } else if (refNode.type === 'location' && refNode.data.reference_image) {
          url = refNode.data.reference_image;
          label = refNode.data.name || '场景';
        } else if (refNode.type === 'props' && refNode.data.reference_image) {
          url = refNode.data.reference_image;
          label = refNode.data.name || '道具';
        }
        if (!url) return;
        referenceImageUrls.push(url);
        if (label) promptSuffix.push(`图${refImageIndex}是${label}`);
        refImageIndex += 1;
      });
      let finalPrompt = prompt || '';
      if (promptSuffix.length > 0) {
        finalPrompt = `${finalPrompt}\n\n${promptSuffix.join('，')}。`;
      }
      return { referenceImageUrls, finalPrompt };
    }

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
          imageSize: '',
          model: defaultImageModel,
          drawCount: 1,
          project_id: null,
          uploading: false,
        }
      };
      // 生成结果节点可通过 opts.data 携带初始数据（如生成时使用的提示词，
      // 供下游连线（360全景等）自动适配提示词）
      if (opts && opts.data) {
        Object.assign(node.data, opts.data);
      }
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node image-node';
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
            <div class="image-generating-placeholder">
              <span class="image-generating-spinner"></span>
              <span class="image-generating-label">生成中...</span>
              <button type="button" class="ai-task-timeline-btn" title="${window.t ? window.t('view_timeline') : '查看生成状态时间轴'}">${window.t ? window.t('timeline_btn_status') : '状态'}</button>
            </div>
          </div>
          <div class="reference-images-section" style="display:none;">
            <div class="reference-images-header">
              <span data-i18n="image_node_reference_images">${window.t ? window.t('image_node_reference_images') : '参考图片'} (<span class="reference-images-count">0</span>)</span>
            </div>
            <div class="reference-images-grid"></div>
          </div>
          <div class="image-node-form field-collapsible">
            <div class="image-form-upload field">
              <div class="label" data-i18n="image_node_upload_label">${window.t ? window.t('image_node_upload_label') : '上传图片'}</div>
              <div class="image-form-upload-row">
                <input class="image-file" type="file" accept="image/*,.tif,.tiff" />
                <button class="mini-btn image-clear" type="button" data-i18n="image_node_clear_btn">${window.t ? window.t('image_node_clear_btn') : '清除'}</button>
                <button class="mini-btn image-download-icon-btn" type="button" data-i18n="image_node_download_btn">${window.t ? window.t('image_node_download_btn') : '下载'}</button>
                <button class="mini-btn image-add-asset-lib-btn" type="button" data-i18n="image_node_add_asset_btn" title="${window.t ? window.t('image_node_add_asset_btn') : '入库'}">${window.t ? window.t('image_node_add_asset_btn') : '入库'}</button>
              </div>
            </div>
            <div class="image-form-prompt field">
              <div class="image-form-prompt-head">
                <div class="label image-prompt-label" data-i18n="image_node_prompt_label">${window.t ? window.t('image_node_prompt_label') : '编辑提示词（可选）'}</div>
                <button class="mini-btn image-prompt-expand-btn" type="button" title="${window.t ? window.t('script_expand_btn') : '放大编辑'}" data-i18n="script_expand_btn:title">⤢</button>
              </div>
              <textarea class="image-prompt" rows="2" placeholder="${window.t ? window.t('image_node_prompt_placeholder') : '输入提示词进行图片编辑'}" data-i18n="image_node_prompt_placeholder:placeholder">${escapeHtml(node.data.prompt || '')}</textarea>
            </div>
            <div class="image-form-options">
              <div class="field image-model-field">
                <div class="label" data-i18n="image_node_model_label">${window.t ? window.t('image_node_model_label') : '模型'}</div>
                <select class="image-model"></select>
              </div>
              <div class="field image-ratio-field">
                <div class="label" data-i18n="image_node_ratio_label">${window.t ? window.t('image_node_ratio_label') : '图片比例'}</div>
                <select class="image-ratio">
                  <option value="9:16" data-i18n="image_ratio_portrait_9_16">${window.t ? window.t('image_ratio_portrait_9_16') : '竖屏 (9:16)'}</option>
                  <option value="16:9" data-i18n="image_ratio_landscape_16_9">${window.t ? window.t('image_ratio_landscape_16_9') : '横屏 (16:9)'}</option>
                  <option value="1:1" data-i18n="image_ratio_square_1_1">${window.t ? window.t('image_ratio_square_1_1') : '正方形 (1:1)'}</option>
                  <option value="3:4" data-i18n="image_ratio_portrait_3_4">${window.t ? window.t('image_ratio_portrait_3_4') : '竖屏 (3:4)'}</option>
                  <option value="4:3" data-i18n="image_ratio_landscape_4_3">${window.t ? window.t('image_ratio_landscape_4_3') : '横屏 (4:3)'}</option>
                </select>
              </div>
              <div class="field image-size-field" style="display:none;">
                <div class="label" data-i18n="image_node_size_label">${window.t ? window.t('image_node_size_label') : '分辨率'}</div>
                <select class="image-size"></select>
              </div>
            </div>
            <div class="image-form-actions">
              <button class="mini-btn image-camera-control-btn" type="button" data-i18n="image_node_camera_control_btn">${window.t ? window.t('image_node_camera_control_btn') : '相机控制'}</button>
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
              <button class="gen-btn image-doodle-btn" type="button" data-i18n="image_node_doodle_btn">${window.t ? window.t('image_node_doodle_btn') : '涂鸦编辑'}</button>
              <div class="image-confirm-field" style="display:none;">
                <button class="mini-btn image-confirm-shot-btn" type="button" data-i18n="image_node_confirm_shot_btn">${window.t ? window.t('image_node_confirm_shot_btn') : '确认分镜图'}</button>
              </div>
            </div>
            <div class="image-form-meta">
              <div class="gen-meta image-draw-count-label"></div>
              <div class="muted image-edit-status" style="display:none;"></div>
            </div>
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
      const addAssetLibBtn = el.querySelector('.image-add-asset-lib-btn');
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
        if (node.data.model && window.TaskConfig && window.TaskConfig.canonicalModelKey) {
          node.data.model = window.TaskConfig.canonicalModelKey(node.data.model);
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

      // 根据模型更新分辨率选项（image_size 档位，与首页图片编辑一致；模型未配置时隐藏）
      function updateImageSizeOptions(model) {
        const sizeEl = el.querySelector('.image-size');
        if(!sizeEl) return;
        const sizeField = el.querySelector('.image-size-field') || sizeEl.closest('.field');
        const config = getModelConfigs()[model];

        if(!config || !Array.isArray(config.image_sizes) || config.image_sizes.length === 0) {
          if(sizeField) sizeField.style.display = 'none';
          return;
        }
        if(sizeField) sizeField.style.display = '';

        const current = node.data.imageSize || config.default_image_size || '';
        sizeEl.innerHTML = '';
        config.image_sizes.forEach(size => {
          sizeEl.innerHTML += `<option value="${size}">${size}</option>`;
        });
        if(current && config.image_sizes.includes(current)) {
          sizeEl.value = current;
          // 默认值也显式落盘，保证 UI 显示与提交/序列化的数据一致
          if(!node.data.imageSize) node.data.imageSize = current;
        } else {
          const fallbackDefault = config.default_image_size && config.image_sizes.includes(config.default_image_size)
            ? config.default_image_size
            : config.image_sizes[0];
          sizeEl.value = fallbackDefault;
          node.data.imageSize = fallbackDefault;
        }
      }

      // 初始化比例选项
      updateImageRatioOptions(node.data.model);
      if(ratioEl) ratioEl.value = node.data.ratio;
      // 初始化分辨率选项
      updateImageSizeOptions(node.data.model);
      
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
        if (doodleBtn) doodleBtn.disabled = !!disabled;
      }

      // 文生图/图生图模式切换：无底图时按钮为「生成图片」（纯文生图，
      // 参考图走 image-edit 无底图路径），有底图为「编辑图片」。
      // 提示词标签/占位同步切换，i18n 键跟随模式，语言重扫也不会串文案
      const promptLabelEl = el.querySelector('.image-prompt-label');
      function updateGenerateModeUI(){
        const hasBaseImage = !!(node.data.url && String(node.data.url).trim());
        if(editBtn){
          if(hasBaseImage){
            editBtn.setAttribute('data-i18n', 'image_node_edit_btn');
            editBtn.textContent = window.t ? window.t('image_node_edit_btn') : '编辑图片';
          } else {
            editBtn.setAttribute('data-i18n', 'image_node_generate_btn');
            editBtn.textContent = window.t ? window.t('image_node_generate_btn') : '生成图片';
          }
        }
        if(promptLabelEl){
          if(hasBaseImage){
            promptLabelEl.setAttribute('data-i18n', 'image_node_prompt_label');
            promptLabelEl.textContent = window.t ? window.t('image_node_prompt_label') : '编辑提示词（可选）';
          } else {
            promptLabelEl.setAttribute('data-i18n', 'image_node_t2i_prompt_label');
            promptLabelEl.textContent = window.t ? window.t('image_node_t2i_prompt_label') : '提示词';
          }
        }
        if(promptEl){
          if(hasBaseImage){
            promptEl.setAttribute('data-i18n', 'image_node_prompt_placeholder:placeholder');
            promptEl.setAttribute('placeholder', window.t ? window.t('image_node_prompt_placeholder') : '输入提示词进行图片编辑');
          } else {
            promptEl.setAttribute('data-i18n', 'image_node_t2i_prompt_placeholder:placeholder');
            promptEl.setAttribute('placeholder', window.t ? window.t('image_node_t2i_prompt_placeholder') : '输入提示词生成图片');
          }
        }
      }
      updateGenerateModeUI();
      el._updateImageGenerateMode = updateGenerateModeUI;

      // 涂鸦编辑按钮：合成底图+涂鸦上传回填
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
          connectedShotFrameNode.data.firstFrameDismissed = false;
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
      const imageSizeEl = el.querySelector('.image-size');
      if(imageSizeEl) {
        imageSizeEl.addEventListener('change', () => {
          node.data.imageSize = imageSizeEl.value;
        });
      }
      modelEl.addEventListener('change', () => {
        node.data.model = modelEl.value;
        // 模型切换时更新比例选项
        updateImageRatioOptions(modelEl.value);
        // 模型切换时更新分辨率选项
        updateImageSizeOptions(modelEl.value);
      });

      imageFileEl.addEventListener('change', async () => {
        let file = imageFileEl.files && imageFileEl.files[0];
        if(!file) return;
        // 部分环境 tif 无 image/* MIME，按扩展名兜底放行（后端会归一化为 PNG）
        const isTiff = window.isTiffFile && window.isTiffFile(file);
        if(!file.type.startsWith('image/') && !isTiff){
          showToast(window.t ? window.t('image_node_select_image') : '请选择图片文件', 'error');
          imageFileEl.value = '';
          return;
        }

        // 超过大小上限：先在前端压缩再上传（GIF 等不可压缩格式原样返回，由服务端兜底）
        const _sizeCfg = window.__wfUploadConfig;
        const _limitMb = _sizeCfg && typeof _sizeCfg.max_image_size_mb === 'number' ? _sizeCfg.max_image_size_mb : 10;
        if (file.size > _limitMb * 1024 * 1024 && typeof compressImageFile === 'function') {
          try {
            const compressed = await compressImageFile(file, _limitMb * 1024 * 1024);
            if (compressed && compressed !== file) {
              file = compressed;
              const _sizeMb = Math.max(0.1, compressed.size / 1024 / 1024).toFixed(1);
              showToast(window.t ? window.t('image_auto_compressed', { max: _limitMb, size: _sizeMb }) : `原图超过${_limitMb}MB，已自动压缩至${_sizeMb}MB`, 'success');
            }
          } catch (err) {
            console.warn('图片压缩失败，按原图上传:', err);
          }
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
          // 浏览器 <img> 不解码 TIFF：tif 跳过本地 base64 预览，
          // 上传成功后直接显示后端转码出的 PNG URL
          if(!isTiff){
            const localPreview = await readFileAsDataUrl(file);
            imagePreviewImg.src = localPreview;
          }
          imagePreviewRow.style.display = 'flex';

          const uploadedUrl = await uploadFile(file);
          if(uploadedUrl){
            node.data.url = uploadedUrl;
            node.data.name = file.name;
            node.data.preview = uploadedUrl;
            updateGenerateModeUI();
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
            updateGenerateModeUI();
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
        updateGenerateModeUI();
        imagePreviewRow.style.display = 'none';
        imagePreviewImg.removeAttribute('src');
      });

      editBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        // 上传中禁止提交（无论文生图/图生图，都等上传流程结束）
        if(node.data.uploading){
          statusEl.style.display = 'block';
          const msg = getImageUploadBlockMessage('uploading');
          setStatusEl(statusEl, msg, '#d97706');
          showToast(msg, 'warning');
          return;
        }
        // 有服务器底图走图生图；无底图走文生图（参考图由提交函数内部处理）
        const hasBaseImage = canEditImageNode(node.data).allowed;

        if(!node.data.prompt){
          statusEl.style.display = 'block';
          const msg = hasBaseImage
            ? (window.t ? window.t('image_node_need_edit_prompt') : '请先输入编辑提示词或调整相机参数')
            : (window.t ? window.t('image_node_need_t2i_prompt') : '请先输入提示词');
          setStatusEl(statusEl, msg, '#dc2626');
          return;
        }

        editBtn.disabled = true;
        statusEl.style.display = 'block';
        setStatusEl(statusEl, '正在提交任务...');
        // 新一轮生成开始，清除上次失败原因（避免重载后误显示过期错误）
        node.data.lastError = '';

        try{
          let submitData = '';
          if(hasBaseImage){
            const resolved = resolveImageEditSubmitData(node.data);
            if (!resolved.ok) {
              const msg = getImageUploadBlockMessage(resolved.reason);
              setStatusEl(statusEl, msg, '#dc2626');
              showToast(msg, 'warning');
              editBtn.disabled = false;
              return;
            }
            submitData = resolved.submitData;
          }

          let finalPrompt = node.data.prompt || '';

          // 共享资产库 @资产:{id} token 提交前还原为 markdown 图片
          // （见 web/js/asset_library.js），使资产图片进入生成上下文
          if (window.AssetLibrary && finalPrompt.indexOf(window.AssetLibrary.MENTION_PREFIX) >= 0) {
            finalPrompt = await window.AssetLibrary.resolveMentionTokens(finalPrompt);
          }

          if(state.style && state.style.name){
            finalPrompt = `${finalPrompt}\n\n图片风格：${state.style.name}`;
          }

          // 有底图时底图占图1；无底图时参考图从 1 起，否则模型会对不上第一张图
          const referenceConns = state.referenceConnections.filter(c => c.to === node.id);
          const refNodes = referenceConns
            .map(conn => state.nodes.find(n => n.id === conn.from))
            .filter(Boolean);
          const collectedRefs = collectImageReferencePrompt(finalPrompt, refNodes, hasBaseImage);
          const referenceImageUrls = collectedRefs.referenceImageUrls;
          finalPrompt = collectedRefs.finalPrompt;

          const desiredCount = Math.max(1, Number(node.data.drawCount) || 1);
          const submitRes = hasBaseImage
            ? await generateEditedImage(submitData, finalPrompt, node.data.ratio, node.data.model, desiredCount, referenceImageUrls, node.data.imageSize)
            : await generateImageFromText(finalPrompt, node.data.ratio, node.data.model, desiredCount, node.data.imageSize, referenceImageUrls);
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
              checkCollision: true,
              // 结果节点携带生成提示词：下游连线（如 360 全景）可自动适配提示词
              data: { prompt: node.data.prompt || '' }
            });
            const newNode = state.nodes.find(n => n.id === newNodeId);
            if(newNode){
              newNode.data.name = imageCount > 1
                ? (hasBaseImage ? `编辑结果${i + 1}` : `生成结果${i + 1}`)
                : (hasBaseImage ? '编辑结果' : '生成结果');
              newNode.data.project_id = projectIds[i] || projectIds[0];
              // 结果节点显示「生成中」占位（含查看状态时间轴按钮）
              if(window.AiToolTimeline) window.AiToolTimeline.markNodeGenerating(newNodeId);
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
              const slots = createdImageNodeIds.map((nodeId) => {
                const created = state.nodes.find(n => n.id === nodeId);
                return {
                  nodeId,
                  projectId: created && created.data ? created.data.project_id : null,
                };
              });
              // 无 tasks 的旧响应没有逐条 project_id，只在张数一致时按原顺序填，避免错位
              const tasks = (statusResult && Array.isArray(statusResult.tasks))
                ? statusResult.tasks
                : (Array.isArray(extractResultsArray(statusResult)) && extractResultsArray(statusResult).length === slots.length
                  ? extractResultsArray(statusResult).map((item) => ({ status: 'SUCCESS', result: item }))
                  : []);
              const plan = planImageBatchResults(tasks, slots);

              const fillSuccess = (nodeId, rawUrl) => {
                const imageUrl = normalizeVideoUrl(rawUrl);
                if (!imageUrl) return false;
                const imageNode = state.nodes.find(n => n.id === nodeId);
                if (!imageNode) return false;
                const normalizedUrl = normalizeImageUrl(imageUrl);
                imageNode.data.url = normalizedUrl;
                imageNode.data.preview = normalizedUrl;
                imageNode.data.lastError = '';
                const nodeEl = canvasEl.querySelector(`.node[data-node-id="${nodeId}"]`);
                if (nodeEl) {
                  const imgEl = nodeEl.querySelector('.image-preview');
                  const rowEl = nodeEl.querySelector('.image-preview-row');
                  const placeholder = nodeEl.querySelector('.image-generating-placeholder');
                  if (imgEl) imgEl.src = proxyImageUrl(imageUrl);
                  if (rowEl) rowEl.style.display = 'flex';
                  if (placeholder) placeholder.classList.remove('is-failed');
                  if (window.AiToolTimeline) window.AiToolTimeline.settleNodeResult(imageNode);
                }
                return true;
              };
              const fillFailure = (nodeId, reason) => {
                const imageNode = state.nodes.find(n => n.id === nodeId);
                const displayError = truncateErrorMessage(reason) || '生成失败';
                if (imageNode) {
                  imageNode.data.lastError = String(displayError);
                }
                if (window.AiToolTimeline) window.AiToolTimeline.failNode(nodeId, displayError);
              };

              let successCount = 0;
              let failCount = 0;
              plan.slots.forEach((slot) => {
                if (slot.outcome === 'success' && fillSuccess(slot.nodeId, slot.url)) {
                  successCount += 1;
                  return;
                }
                fillFailure(slot.nodeId, slot.outcome === 'success' ? '生成成功，但未获取到图片地址' : slot.error);
                failCount += 1;
              });

              editBtn.disabled = false;
              if (successCount === 0) {
                const failReason = plan.slots.map(slot => slot.error).find(Boolean) || '生成失败';
                const displayError = truncateErrorMessage(failReason) || '生成失败';
                setStatusEl(statusEl, displayError, '#dc2626');
                node.data.lastError = String(displayError);
                showToast(displayError, 'error');
              } else if (failCount > 0) {
                const partialText = `生成完成 ${successCount} 张，失败 ${failCount} 张`;
                setStatusEl(statusEl, partialText, '#d97706');
                node.data.lastError = '';
                showToast(partialText, 'warning');
              } else {
                setStatusEl(statusEl, `生成完成！共${successCount}张图片`, '#16a34a');
                node.data.lastError = '';
                showToast(hasBaseImage ? '图片编辑成功！' : '图片生成成功！', 'success');
              }

              safeAutoSave()
              renderMinimap();
              
              // 刷新用户算力显示
              if(typeof fetchComputingPower === 'function'){
                fetchComputingPower();
              }
            },
            (errMsg) => {
              setStatusEl(statusEl, errMsg, '#dc2626');
              // 持久化失败原因，工作流重载后可恢复显示
              node.data.lastError = String(truncateErrorMessage(errMsg) || '');
              editBtn.disabled = false;
              showToast(errMsg || '图片编辑失败', 'error');
            }
          );
        } catch(err){
          setStatusEl(statusEl, err.message || '提交失败', '#dc2626');
          // 持久化失败原因，工作流重载后可恢复显示
          node.data.lastError = String(err.message || '提交失败');
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
        // 生成结果名（"生成结果1"）无后缀，CDN attname 原样透传会下载出
        // 无扩展名文件，统一走扩展名兜底
        const fileName = window.ensureDownloadExtension(node.data.name, downloadUrl, 'png');
        
        // 图片直接下载，不需要后端代理
        // 如果是跨域图片，使用fetch+blob方式下载
        try {
          await window.downloadWithAuth(downloadUrl, fileName);
          showToast(window.t ? window.t('start_download_image') : '开始下载图片', 'success');
        } catch(error) {
          if (error && error.status === 401) return;
          console.error('下载图片失败:', error);
          showToast(window.t ? window.t('download_image_failed') : '下载图片失败', 'error');
        }
      });

      // 入库按钮：把节点当前图片加入共享资产库（弹窗见 web/js/asset_library.js）
      if (addAssetLibBtn) {
        addAssetLibBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (!window.AssetLibrary) return;
          const assetUrl = node.data.url || node.data.preview;
          if (!assetUrl) {
            showToast('请先生成或上传图片', 'warning');
            return;
          }
          window.AssetLibrary.promptAdd({
            sourceUrl: assetUrl,
            name: (node.data.name || '').slice(0, 60)
          });
        });
      }

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
        planImageBatchResults,
        collectImageReferencePrompt,
      };
    }
