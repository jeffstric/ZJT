    function createShotGroupNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = Math.max(MIN_NODE_Y, opts && typeof opts.y === 'number' ? opts.y : viewportPos.y);
      const shotGroupData = opts && opts.shotGroupData ? opts.shotGroupData : {};
      const scriptData = opts && opts.scriptData ? opts.scriptData : {};
      
      // 默认模型：图片优先使用 gpt-image-2
      let defaultImageModel = 'gpt-image-2';
      let defaultVideoModel = 'wan22';
      if(window.TaskConfig && window.TaskConfig.isLoaded()) {
        const imageOptions = window.TaskConfig.getModelOptionsForCategory('image_edit');
        const gptImage2 = imageOptions.find(o => o.value === 'gpt-image-2');
        if(gptImage2) {
          defaultImageModel = gptImage2.value;
        } else if(imageOptions.length > 0) {
          defaultImageModel = imageOptions[0].value;
        }
        const videoOptions = window.TaskConfig.getModelOptionsForCategory('image_to_video');
        if(videoOptions.length > 0) defaultVideoModel = videoOptions[0].value;
      }
      
      const groupName = shotGroupData.groupName || shotGroupData.group_name || shotGroupData.group_id || '幕';
      const resolvedVideoModel = getVideoModelFromData(shotGroupData) || defaultVideoModel;
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
          scriptNodeId: opts.scriptNodeId || '',  // 关联的剧本节点 ID
          scriptContent: opts.scriptContent || '',  // 原始剧本内容
          model: shotGroupData.model || defaultImageModel,
          gridModel: normalizeGridImageModelValue(shotGroupData.gridModel || shotGroupData.grid_model),
          videoModel: resolvedVideoModel,
          videoResolution: pickFirstDefinedValue(shotGroupData.videoResolution, shotGroupData.video_resolution) || '',
          videoDuration: pickFirstDefinedValue(shotGroupData.videoDuration, shotGroupData.video_duration) || 5,
          videoDrawCount: pickFirstDefinedValue(shotGroupData.videoDrawCount, shotGroupData.video_draw_count) || 1,
          videoGenMode: shotGroupData.videoGenMode || 'first_last_frame',
          processFace: shotGroupData.processFace ?? false,  // 是否处理人脸（仅 seedance2.0 商业版生效）
          gridPreview: shotGroupData.gridPreview || {},
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';
      // 不设固定宽度，由CSS .node:has(.script-node-body) 控制

      // 构建分镜列表HTML
      const shotsHtml = node.data.shots.map((shot, idx) => {
        const duration = shot.duration ? `${shot.duration}秒` : '未知';
        return `
          <div style="padding: 8px; background: #f8f9fa; border-radius: 6px; margin-bottom: 6px; font-size: 12px;">
            <div style="font-weight: 700; margin-bottom: 4px;">${escapeHtml(shot.shot_id || `镜头${idx+1}`)} - ${escapeHtml(shot.description || '')}</div>
            <div style="color: #666; font-size: 11px;">时长: ${escapeHtml(duration)} | ${escapeHtml(shot.shot_type || '')} | ${escapeHtml(shot.camera_movement || '')}</div>
            <div style="color: #666; font-size: 11px; margin-top: 2px;">图片提示词: ${escapeHtml((shot.opening_frame_description || '').slice(0, 60))}...</div>
          </div>
        `;
      }).join('');

      el.innerHTML = `
        <div class="port input" data-i18n="shot_group_input_port:title"></div>
        <div class="port output" data-i18n="shot_group_output_port:title"></div>
        <div class="node-header">
          <div class="node-title" data-i18n="shot_group_title" data-i18n-params='${JSON.stringify({ title: escapeHtml(node.title) })}'><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M6 9H18M6 12H14M6 15H12" stroke="currentColor" stroke-linecap="round"/></svg>${window.t ? window.t('shot_group_title', { title: escapeHtml(node.title) }) : `幕: ${escapeHtml(node.title)}`}</div>
          <button class="icon-btn" data-i18n="node_delete_btn:title" title="${window.t ? window.t('node_delete_btn') : '删除'}">×</button>
        </div>
        <div class="node-body">
          <div class="script-node-body">
            <!-- 第1列: 分镜详情 -->
            <div class="script-section">
              <div class="script-section-header">
                <div class="script-section-number">1</div>
                <div class="script-section-title" data-i18n="shot_group_details_section">${window.t ? window.t('shot_group_details_section') : '分镜详情'}</div>
              </div>
              <div class="field field-always-visible">
                <div class="label" data-i18n="shot_group_label">${window.t ? window.t('shot_group_label') : '幕:'} ${escapeHtml(node.data.groupId || node.data.group_id)}</div>
                <div class="gen-meta shot-group-shot-count" data-i18n="shot_group_shot_count" data-i18n-params='${JSON.stringify({ count: node.data.shots.length })}'>${window.t ? window.t('shot_group_shot_count', { count: node.data.shots.length }) : `共 ${node.data.shots.length} 个分镜`}</div>
              </div>
              <div class="field field-always-visible shot-group-shots-list" style="flex: 1; max-height: 300px; overflow-y: auto;">
                ${shotsHtml}
              </div>
              <div class="field field-always-visible">
                <div class="label" data-i18n="shot_group_model_label">${window.t ? window.t('shot_group_model_label') : '分镜模型'}</div>
                <select class="shot-group-model"></select>
              </div>
              <div class="field field-always-visible btn-row" style="margin-top: 12px;">
                <button class="mini-btn secondary shot-group-detail-btn" type="button" style="flex: 1; padding: 9px 12px;" data-i18n="shot_group_detail_btn">${window.t ? window.t('shot_group_detail_btn') : '查看/编辑'}</button>
                <button class="mini-btn gen-btn-white shot-group-generate-btn" type="button" style="padding: 9px 12px;" data-i18n="shot_group_generate_shot_btn">${window.t ? window.t('shot_group_generate_shot_btn') : '生成分镜'}</button>
              </div>
            </div>
            <!-- 第2列: 分镜预览与生成 -->
            <div class="script-section">
              <div class="script-section-header">
                <div class="script-section-number">2</div>
                <div class="script-section-title" data-i18n="shot_group_preview_section">${window.t ? window.t('shot_group_preview_section') : '分镜预览与生成'}</div>
              </div>
              <div class="field field-always-visible">
                <div class="shot-grid-preview-label" style="font-size: 11px; color: #666; margin-bottom: 4px;" data-i18n="shot_group_preview_label" data-i18n-params='{"count":0}'>${window.t ? window.t('shot_group_preview_label', { count: 0 }) : '分镜预览（0个分镜）'}</div>
                <div class="shot-grid-preview-container grid-2x2">
                  <div style="padding: 16px; text-align: center; color: #666; font-size: 11px; grid-column: 1/-1;" data-i18n="shot_group_no_shot_node">${window.t ? window.t('shot_group_no_shot_node') : '暂无分镜节点'}</div>
                </div>
                <div class="grid-merge-status"></div>
              </div>
              <div class="field field-always-visible">
                <div class="label" data-i18n="shot_group_grid_model_label">${window.t ? window.t('shot_group_grid_model_label') : '宫格生图模型'}</div>
                <select class="shot-group-grid-model" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;"></select>
              </div>
              <div class="field field-always-visible">
                <div class="label" style="margin-top:5px" data-i18n="shot_group_grid_type_label">${window.t ? window.t('shot_group_grid_type_label') : '宫格类型'}</div>
                <select class="shot-group-grid-layout" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
                  <option value="auto" data-i18n="shot_group_grid_auto">${window.t ? window.t('shot_group_grid_auto') : '自动选择'}</option>
                  <option value="4" data-i18n="shot_group_grid_4">${window.t ? window.t('shot_group_grid_4') : '4宫格 (2x2)'}</option>
                  <option value="9" data-i18n="shot_group_grid_9">${window.t ? window.t('shot_group_grid_9') : '9宫格 (3x3)'}</option>
                </select>
              </div>
              <div class="field field-always-visible btn-row" style="margin-top: 12px;">
                <button class="mini-btn gen-btn-green shot-group-grid-btn" type="button" style="width: 100%; padding: 9px 12px;" data-i18n="shot_group_grid_btn">${window.t ? window.t('shot_group_grid_btn') : '宫格生图'}</button>
              </div>
              <div class="gen-meta shot-group-grid-status" style="display:none; margin-top: 8px;"></div>
            </div>
            <!-- 第3列: 视频生成 -->
            <div class="script-section" style="background: #f9fafb;">
              <div class="script-section-header">
                <div class="script-section-number">3</div>
                <div class="script-section-title" data-i18n="shot_group_video_section">${window.t ? window.t('shot_group_video_section') : '视频生成'}</div>
              </div>
              <div class="field field-always-visible">
                <div class="label" data-i18n="video_gen_mode_label">${window.t ? window.t('video_gen_mode_label') : '视频生成模式'}</div>
                <select class="shot-group-video-gen-mode">
                  <option value="first_last_frame" data-i18n="video_mode_first_frame">${window.t ? window.t('video_mode_first_frame') : '首帧模式'}</option>
                  <option value="multi_reference" data-i18n="video_mode_reference">${window.t ? window.t('video_mode_reference') : '参考模式'}</option>
                </select>
              </div>
              <div class="field field-always-visible" style="margin-top:5px">
                <div class="label" data-i18n="shot_group_video_model_label">${window.t ? window.t('shot_group_video_model_label') : '视频模型'}</div>
                <select class="shot-group-video-model"></select>
              </div>
              <div class="field field-always-visible shot-group-video-resolution-field" style="display:none;">
                <div class="label" data-i18n="video_resolution">${window.t ? window.t('video_resolution') : '分辨率'}</div>
                <select class="shot-group-video-resolution-select video-resolution-select"></select>
              </div>
              <div class="field field-always-visible" style="margin-top:5px">
                <div class="label" data-i18n="shot_group_video_duration_label">${window.t ? window.t('shot_group_video_duration_label') : '视频时长'}</div>
                <select class="shot-group-video-duration">
                  <option value="5" selected data-i18n="shot_group_video_duration_5s">${window.t ? window.t('shot_group_video_duration_5s') : '5秒'}</option>
                  <option value="10" data-i18n="shot_group_video_duration_10s">${window.t ? window.t('shot_group_video_duration_10s') : '10秒'}</option>
                </select>
              </div>
              <div class="shot-group-process-face-field field field-always-visible" style="margin-top: 8px; display: none;">
                <label class="shot-group-process-face-label" style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #374151; cursor: pointer;">
                  <input type="checkbox" class="shot-group-process-face-checkbox" style="cursor: pointer;" />
                  <span data-i18n="process_face_label">${window.t ? window.t('process_face_label') : '是否处理人脸'}</span>
                </label>
                <div class="shot-group-process-face-hint" style="margin-top: 4px; font-size: 11px; color: #d97706; display: none;" data-i18n="process_face_community_hint">${window.t ? window.t('process_face_community_hint') : '此功能为商业版功能，请联系购买商业版本后使用'}</div>
              </div>
              <div class="field field-always-visible" style="margin-top: 10px;">
                <div style="display: flex; flex-direction: column; gap: 8px;">
                  <div class="gen-container shot-group-merge-container" style="width: 100%;">
                    <button class="gen-btn gen-btn-main shot-group-generate-video-btn" type="button" style="background: #22c55e; color: white; padding: 10px; flex: 1;" data-i18n="shot_group_merge_generate_video_btn">${window.t ? window.t('shot_group_merge_generate_video_btn') : '合并生成视频'}</button>
                    <button class="gen-btn gen-btn-caret shot-group-video-caret" type="button" aria-label="${window.t ? window.t('draw_count_menu') : '选择抽卡次数'}">▾</button>
                    <div class="gen-menu shot-group-video-menu">
                      <div class="gen-item" data-count="1">X1</div>
                      <div class="gen-item" data-count="2">X2</div>
                      <div class="gen-item" data-count="3">X3</div>
                      <div class="gen-item" data-count="4">X4</div>
                    </div>
                  </div>
                  <button class="gen-btn gen-btn-main shot-group-batch-generate-btn" type="button" style="background: #3b82f6; color: white; padding: 10px;" data-i18n="shot_group_batch_generate_video_btn">${window.t ? window.t('shot_group_batch_generate_video_btn') : '逐个生成视频'}</button>
                </div>
              </div>
              <div style="font-size: 10px; color: #9ca3af; line-height: 1.4; margin-top: 4px;">
                <span style="color: #10b981;" data-i18n="shot_group_merge_info_title">${window.t ? window.t('shot_group_merge_info_title') : '● 合并生成'}</span><span data-i18n="shot_group_merge_info_desc">：${window.t ? window.t('shot_group_merge_info_desc') : '多个分镜合并为一个视频，节省算力'}</span><br>
                <span style="color: #3b82f6;" data-i18n="shot_group_batch_info_title">${window.t ? window.t('shot_group_batch_info_title') : '● 逐个生成'}</span><span data-i18n="shot_group_batch_info_desc">：${window.t ? window.t('shot_group_batch_info_desc') : '每个分镜独立生成，支持所有模型'}</span>
              </div>
              <div style="margin-top: auto; padding-top: 12px; border-top: 1px dashed #e5e7eb;">
                <div class="gen-meta shot-group-video-draw-count-label" data-i18n="shot_group_merge_draw_count"></div>
                <div class="shot-group-computing-power" style="padding: 6px; border-radius: 6px;">
                  <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="color: #9ca3af; font-size: 11px;" data-i18n="shot_group_computing_power">${window.t ? window.t('shot_group_computing_power') : '算力消耗：'}</span>
                    <span class="shot-group-computing-power-value" style="color: #3b82f6; font-weight: bold; font-size: 12px;" data-i18n="shot_group_computing_power_value" data-i18n-params='{"power":0}'>${window.t ? window.t('shot_group_computing_power_value', { power: 0 }) : '0 算力'}</span>
                  </div>
                  <div class="shot-group-computing-power-detail" style="margin-top: 2px; font-size: 10px; color: #6b7280; text-align: right;" data-i18n="shot_group_computing_power_detail" data-i18n-params='{"individual":0,"count":1,"total":0}'>${window.t ? window.t('shot_group_computing_power_detail', { individual: 0, count: 1, total: 0 }) : '单个 0 算力 × 1 个 = 0 算力'}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const detailBtn = el.querySelector('.shot-group-detail-btn');
      const generateBtn = el.querySelector('.shot-group-generate-btn');
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
              renderAllConnections();
              renderReferenceConnections();
              renderMinimap();
              safeAutoSave()
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

      generateBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        generateShotFramesIndependent(id, node);
      });

      detailBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openShotGroupModal(node.data, id);
      });

      // 分镜模型选择（第1列）—— 初始化选项 + 写回 node.data.model
      const shotGroupModelEl = el.querySelector('.shot-group-model');
      if(shotGroupModelEl){
        let firstModelValue = 'gpt-image-2';
        if(window.TaskConfig && window.TaskConfig.isLoaded()){
          const modelOptions = window.TaskConfig.getModelOptionsForCategory('image_edit');
          const gptImage2 = modelOptions.find(o => o.value === 'gpt-image-2');
          if(gptImage2) {
            firstModelValue = gptImage2.value;
          } else if(modelOptions.length > 0) {
            firstModelValue = modelOptions[0].value;
          }
          modelOptions.forEach(opt => {
            const optEl = document.createElement('option');
            optEl.value = opt.value;
            optEl.textContent = opt.label;
            if(opt.value === node.data.model) optEl.selected = true;
            shotGroupModelEl.appendChild(optEl);
          });
        } else {
          shotGroupModelEl.innerHTML = `
            <option value="gemini" ${node.data.model === 'gemini' ? 'selected' : ''}>标准版</option>
            <option value="gemini_pro" ${node.data.model === 'gemini_pro' ? 'selected' : ''}>加强版</option>
            <option value="seedream-5.0" ${node.data.model === 'seedream-5.0' ? 'selected' : ''}>Seedream 5.0</option>
          `;
        }
        if(!node.data.model){
          node.data.model = firstModelValue;
          shotGroupModelEl.value = firstModelValue;
        }
        ensureSelectHasSavedOption(shotGroupModelEl, node.data.model);
        applyDriverStatusToSelect(shotGroupModelEl);
        shotGroupModelEl.addEventListener('change', () => {
          node.data.model = shotGroupModelEl.value;
        });
      }

      // 宫格生图按钮和模型选择器
      const gridBtn = el.querySelector('.shot-group-grid-btn');
      const gridModelSelect = el.querySelector('.shot-group-grid-model');
      const gridStatusEl = el.querySelector('.shot-group-grid-status');
      
      // 动态填充宫格生图模型选项
      if(gridModelSelect) {
        node.data.gridModel = populateGridImageModelSelect(gridModelSelect, node.data.gridModel);
      }

      // 初始化宫格模型选择，兼容旧工作流中保存的 auto 智能模式
      if(!node.data.gridModel || node.data.gridModel === 'auto'){
        node.data.gridModel = DEFAULT_GRID_IMAGE_MODEL;
      }
      if(gridModelSelect){
        // 确保已保存的宫格模型值在下拉框中可见
        node.data.gridModel = normalizeGridImageModelValue(node.data.gridModel);
        ensureSelectHasSavedOption(gridModelSelect, node.data.gridModel);
        gridModelSelect.value = node.data.gridModel;
        // 应用驱动状态禁用未配置的宫格生图模型选项
        applyDriverStatusToSelect(gridModelSelect);
        gridModelSelect.addEventListener('change', () => {
          node.data.gridModel = gridModelSelect.value;
        });
      }

      // 初始化宫格类型选择（默认自动）
      const gridLayoutSelect = el.querySelector('.shot-group-grid-layout');
      if(!node.data.gridLayout){
        node.data.gridLayout = 'auto';
      }
      if(gridLayoutSelect){
        gridLayoutSelect.value = node.data.gridLayout;
        gridLayoutSelect.addEventListener('change', () => {
          node.data.gridLayout = gridLayoutSelect.value;
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
      const videoGenModeEl = el.querySelector('.shot-group-video-gen-mode');
      const videoModelEl = el.querySelector('.shot-group-video-model');
      const resolutionField = el.querySelector('.shot-group-video-resolution-field');
      const resolutionSelect = el.querySelector('.shot-group-video-resolution-select');
      const videoDurationEl = el.querySelector('.shot-group-video-duration');
      const generateVideoBtn = el.querySelector('.shot-group-generate-video-btn');
      const videoCaret = el.querySelector('.shot-group-video-caret');
      const videoMenu = el.querySelector('.shot-group-video-menu');
      const videoDrawCountLabel = el.querySelector('.shot-group-video-draw-count-label');
      const computingPowerValue = el.querySelector('.shot-group-computing-power-value');
      const computingPowerDetail = el.querySelector('.shot-group-computing-power-detail');

      // 动态填充视频模型选项（根据当前视频生成模式过滤）
      let firstShotGroupVideoModelValue = 'wan22';
      const shotGroupMode = node.data.videoGenMode || 'first_last_frame';
      if(videoModelEl) {
        videoModelEl.innerHTML = '';
        if(window.TaskConfig && window.TaskConfig.isLoaded()) {
          const allOptions = window.TaskConfig.getModelOptionsForCategory('image_to_video');
          const options = allOptions.filter(opt => {
            const modes = opt.supportedImageModes || ['first_last_frame'];
            return modes.includes(shotGroupMode);
          });
          if(options.length > 0) firstShotGroupVideoModelValue = options[0].value;
          options.forEach(opt => {
            const optEl = document.createElement('option');
            optEl.value = opt.value;
            optEl.textContent = opt.label;
            if(opt.value === node.data.videoModel) optEl.selected = true;
            videoModelEl.appendChild(optEl);
          });
        } else {
          if(shotGroupMode === 'multi_reference') {
            videoModelEl.innerHTML = `
              <option value="veo3">VEO3.1</option>
              <option value="seedance_2_0">Seedance 2.0</option>
              <option value="vidu_q2">Vidu-Q2</option>
            `;
            firstShotGroupVideoModelValue = 'veo3';
          } else {
            videoModelEl.innerHTML = `
              <option value="wan22" selected>Wan2.2</option>
              <option value="sora2">Sora2</option>
              <option value="ltx2">LTX2.0</option>
              <option value="kling">可灵</option>
              <option value="vidu">Vidu</option>
              <option value="veo3">VEO3.1</option>
            `;
          }
        }
      }

      // 初始化视频模型和时长（使用后端配置的第一个选项作为默认值）
      if(!node.data.videoModel) node.data.videoModel = firstShotGroupVideoModelValue;
      // 确保已保存的视频模型值在下拉框中可见
      if(videoModelEl) {
        ensureSelectHasSavedOption(videoModelEl, node.data.videoModel);
        videoModelEl.value = node.data.videoModel;
      }
      if(videoDurationEl) videoDurationEl.value = node.data.videoDuration;
      if(videoGenModeEl) videoGenModeEl.value = node.data.videoGenMode || 'first_last_frame';

      // 应用驱动状态禁用未配置的选项
      if(videoModelEl) applyDriverStatusToSelect(videoModelEl);

      function updateShotGroupResolutionOptions(videoModel) {
        if(!resolutionField || !resolutionSelect) return;
        const options = window.TaskConfig && typeof TaskConfig.getVideoResolutionOptions === 'function'
          ? TaskConfig.getVideoResolutionOptions(videoModel)
          : [];

        resolutionSelect.innerHTML = '';
        if(!options.length) {
          resolutionField.style.display = 'none';
          node.data.videoResolution = '';
          return;
        }

        resolutionField.style.display = '';
        options.forEach(option => {
          const optEl = document.createElement('option');
          optEl.value = option.value;
          optEl.textContent = option.label || option.value;
          resolutionSelect.appendChild(optEl);
        });

        const validValues = options.map(option => option.value);
        if(!node.data.videoResolution || !validValues.includes(node.data.videoResolution)) {
          node.data.videoResolution = (
            typeof TaskConfig.getDefaultVideoResolution === 'function'
              ? TaskConfig.getDefaultVideoResolution(videoModel)
              : null
          ) || options[0].value;
        }
        resolutionSelect.value = node.data.videoResolution;
      }

      node.updateShotGroupResolutionOptions = updateShotGroupResolutionOptions;

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
      updateShotGroupResolutionOptions(node.data.videoModel);

      // 根据当前视频生成模式重新填充视频模型选项
      function populateShotGroupVideoModelOptions() {
        if(!videoModelEl) return;
        const mode = node.data.videoGenMode || 'first_last_frame';
        let firstValue = mode === 'multi_reference' ? 'veo3' : 'wan22';
        let filteredOptions = [];

        videoModelEl.innerHTML = '';

        if(window.TaskConfig && window.TaskConfig.isLoaded()) {
          const allOptions = window.TaskConfig.getModelOptionsForCategory('image_to_video');
          filteredOptions = allOptions.filter(opt => {
            const modes = opt.supportedImageModes || ['first_last_frame'];
            return modes.includes(mode);
          });
          if(filteredOptions.length > 0) firstValue = filteredOptions[0].value;
          filteredOptions.forEach(opt => {
            const optEl = document.createElement('option');
            optEl.value = opt.value;
            optEl.textContent = opt.label;
            videoModelEl.appendChild(optEl);
          });
        } else {
          if(mode === 'multi_reference') {
            videoModelEl.innerHTML = `
              <option value="veo3">VEO3.1</option>
              <option value="seedance_2_0">Seedance 2.0</option>
              <option value="vidu_q2">Vidu-Q2</option>
            `;
            firstValue = 'veo3';
          } else {
            videoModelEl.innerHTML = `
              <option value="wan22">Wan2.2</option>
              <option value="sora2">Sora2</option>
              <option value="ltx2">LTX2.0</option>
              <option value="kling">可灵</option>
              <option value="vidu">Vidu</option>
              <option value="veo3">VEO3.1</option>
            `;
            firstValue = 'wan22';
          }
        }

        // 如果当前选择的模型不在新列表中，切换到第一个可用模型
        const validValues = filteredOptions.map(o => o.value);
        if(validValues.length > 0 && !validValues.includes(node.data.videoModel)) {
          node.data.videoModel = firstValue;
        }
        ensureSelectHasSavedOption(videoModelEl, node.data.videoModel);
        videoModelEl.value = node.data.videoModel || firstValue;
        applyDriverStatusToSelect(videoModelEl);
        // 模型变更后联动更新时长选项和算力显示
        updateVideoDurationOptions(videoModelEl.value);
        updateShotGroupResolutionOptions(videoModelEl.value);
        updateVideoComputingPowerDisplay();
      }

      // 计算视频生成算力消耗
      function calculateVideoComputingPower() {
        // 检查 TaskConfig 是否已加载
        if(!window.TaskConfig || !window.TaskConfig.isLoaded()) {
          return 0;
        }

        const videoModel = node.data.videoModel || 'wan22';
        const duration = node.data.videoDuration || 5;

        const context = {};
        if(node.data.videoGenMode) {
          context.image_mode = node.data.videoGenMode;
        }
        if(node.data.videoResolution) {
          context.resolution = node.data.videoResolution;
        }

        // 使用 TaskConfig API 动态获取算力（自动支持所有模型）
        return TaskConfig.getComputingPower(videoModel, duration, context);
      }

      // 更新视频算力显示
      function updateVideoComputingPowerDisplay() {
        const singlePower = calculateVideoComputingPower();
        const count = node.data.videoDrawCount || 1;
        const totalPower = singlePower * count;

        if(computingPowerValue) {
          const displayPower = typeof totalPower === 'number' ? totalPower : 0;
          computingPowerValue.textContent = window.t ? window.t('shot_group_computing_power_value', { power: displayPower }) : `${displayPower} 算力`;
          computingPowerValue.setAttribute('data-i18n-params', JSON.stringify({ power: displayPower }));
        }
        if(computingPowerDetail) {
          const displaySingle = typeof singlePower === 'number' ? singlePower : 0;
          const displayCount = typeof count === 'number' ? count : 1;
          const displayTotal = typeof totalPower === 'number' ? totalPower : 0;
          computingPowerDetail.textContent = window.t ? window.t('shot_group_computing_power_detail', { individual: displaySingle, count: displayCount, total: displayTotal }) : `单个 ${displaySingle} 算力 × ${displayCount} 个 = ${displayTotal} 算力`;
          computingPowerDetail.setAttribute('data-i18n-params', JSON.stringify({ individual: displaySingle, count: displayCount, total: displayTotal }));
        }
      }

      // 初始化抽卡次数显示
      function updateVideoDrawCountLabel(){
        { const _t = window.t ? window.t('draw_count_x', { count: node.data.videoDrawCount }) : null; videoDrawCountLabel.textContent = (_t && _t !== 'draw_count_x') ? _t : `抽卡次数：X${node.data.videoDrawCount}`; }
        updateVideoComputingPowerDisplay();
      }
      updateVideoDrawCountLabel();
      updateVideoComputingPowerDisplay();

      // 视频模型选择事件
      videoModelEl.addEventListener('change', () => {
        node.data.videoModel = videoModelEl.value;
        updateVideoDurationOptions(videoModelEl.value);
        updateShotGroupResolutionOptions(videoModelEl.value);
        updateVideoComputingPowerDisplay();
        updateMergeButtonVisibility(videoModelEl.value);
        updateShotGroupProcessFaceVisibility();
      });

      if(resolutionSelect) {
        resolutionSelect.addEventListener('change', () => {
          node.data.videoResolution = resolutionSelect.value;
          updateVideoComputingPowerDisplay();
        });
      }

      // 视频生成模式选择事件（切换模式时重新过滤视频模型列表）
      if(videoGenModeEl) {
        videoGenModeEl.addEventListener('change', () => {
          node.data.videoGenMode = videoGenModeEl.value;
          populateShotGroupVideoModelOptions();
          updateMergeButtonVisibility(videoModelEl.value);
          updateShotGroupProcessFaceVisibility();
          try { autoSaveWorkflow(); } catch(e) {}
        });
      }

      // 根据模型配置更新合并生成按钮的显示状态
      function updateMergeButtonVisibility(videoModel) {
        const mergeContainer = el.querySelector('.shot-group-merge-container');
        const currentMode = node.data.videoGenMode || 'first_last_frame';

        // 参考生视频模式下，合并按钮始终显示（不需要宫格合并支持）
        if(currentMode === 'multi_reference') {
          if(mergeContainer) mergeContainer.style.display = 'inline-flex';
          return;
        }

        // 首尾帧模式：从后端配置获取模型是否支持宫格合并
        const taskId = window.TaskConfig?.getTaskIdByKey(videoModel, 'image_to_video');
        const taskConfig = taskId ? window.TaskConfig?.getTaskById(taskId) : null;
        const isMergeSupported = taskConfig?.supports_grid_merge || false;

        if(mergeContainer) {
          mergeContainer.style.display = isMergeSupported ? 'inline-flex' : 'none';
        }
      }

      // 初始化「是否处理人脸」字段可见性（仅 seedance2.0 系列显示；社区版置灰提示）
      function updateShotGroupProcessFaceVisibility() {
        const faceField = el.querySelector('.shot-group-process-face-field');
        if(!faceField) return;
        const videoModel = videoModelEl ? videoModelEl.value : (node.data.videoModel || '');
        const hintEl = el.querySelector('.shot-group-process-face-hint');
        const checkboxEl = el.querySelector('.shot-group-process-face-checkbox');
        if(window.TaskConfig && window.TaskConfig.isLoaded()) {
          const modelConfig = window.TaskConfig.getModelConfigs()[videoModel];
          const needsFaceMask = modelConfig && modelConfig.needs_face_mask === true;
          faceField.style.display = needsFaceMask ? 'block' : 'none';
          if(needsFaceMask) {
            const isEnterprise = window.TaskConfig.isEnterprise();
            if(checkboxEl) {
              checkboxEl.checked = !!node.data.processFace;
              checkboxEl.disabled = !isEnterprise;
            }
            if(hintEl) hintEl.style.display = isEnterprise ? 'none' : 'block';
          }
        } else {
          faceField.style.display = 'none';
        }
      }

      // 初始化合并按钮显示状态
      if(window.TaskConfig?.isLoaded()) {
        updateMergeButtonVisibility(node.data.videoModel || 'wan22');
      } else {
        // 等待配置加载完成
        window.TaskConfig?.onLoaded(() => {
          updateMergeButtonVisibility(node.data.videoModel || 'wan22');
        });
      }

      // 初始化「是否处理人脸」字段显示状态
      if(window.TaskConfig?.isLoaded()) {
        updateShotGroupProcessFaceVisibility();
      } else {
        window.TaskConfig?.onLoaded(() => updateShotGroupProcessFaceVisibility());
      }

      // 视频时长选择事件
      videoDurationEl.addEventListener('change', () => {
        node.data.videoDuration = Number(videoDurationEl.value);
        updateVideoComputingPowerDisplay();
      });

      // 人脸处理复选框事件
      const processFaceCheckbox = el.querySelector('.shot-group-process-face-checkbox');
      if(processFaceCheckbox) {
        processFaceCheckbox.addEventListener('change', (e) => {
          node.data.processFace = !!e.target.checked;
          try { autoSaveWorkflow(); } catch(e) {}
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

      // 生成视频按钮点击事件
      generateVideoBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        generateShotGroupVideo(id, node);
      });

      // 批量生成视频按钮点击事件
      const batchGenerateBtn = el.querySelector('.shot-group-batch-generate-btn');
      if(batchGenerateBtn) {
        batchGenerateBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          generateAllShotFrameVideos(id, node);
        });
      }

      // 宫格预览刷新方法（挂到node对象上，供外部调用）
      node.refreshGridPreview = function() {
        updateGridPreviewUI(el, node);
      };

      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
      canvasEl.appendChild(el);

      // i18n: 翻译节点内 DOM
      if (typeof window.ZJTi18nDOM !== 'undefined') {
        setTimeout(() => window.ZJTi18nDOM.scanDOM(el), 0);
      }

      // 初始化宫格预览（延迟执行，确保连接已建立）
      setTimeout(() => { updateGridPreviewUI(el, node); }, 100);

      setSelected(id);
      return id;
    }
