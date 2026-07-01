    function createShotFrameNode(opts){
      const id = state.nextNodeId++;
      let _activeDropdownCloseHandler = null;
      const viewportPos = getViewportNodePosition();
      let x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      let y = Math.max(MIN_NODE_Y, opts && typeof opts.y === 'number' ? opts.y : viewportPos.y);

      // 如果启用了碰撞检测，则自动寻找最近的无重叠位置（优先向右/下扩展）
      if (opts && opts.checkCollision) {
        const avail = findPositionRightward(x, y, 320, 220);
        x = avail.x;
        y = Math.max(MIN_NODE_Y, avail.y);
      }
      const shotData = opts && opts.shotData ? opts.shotData : {};
      
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
      
      const inheritedModel = opts && opts.model ? opts.model : defaultImageModel;
      const inheritedVideoModel = (opts && opts.videoModel) || getVideoModelFromData(shotData) || defaultVideoModel;
      
      // 标题：手动添加的分镜（shot_id 为 N_x 格式，如 5_1）用 shot_id；LLM 生成的（s001 等）用 shot_number（位置序号）
      const _titleSid = String(shotData.shot_id || '');
      const shotTitle = /^\d+_\d+$/.test(_titleSid) ? _titleSid : (shotData.shot_number ? String(shotData.shot_number) : (shotData.shot_id || '分镜图'));
      
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
          videoModel: inheritedVideoModel,
          videoMode: 'first_last_frame',  // 'first_last_frame' | 'multi_reference'
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';
      el._cleanupHandlers = [];
      // 不设固定宽度，由CSS .node:has(.script-node-body) 控制

      el.innerHTML = `
        <div class="port input" data-i18n="shot_frame_input_port:title"></div>
        <div class="port output" data-i18n="shot_frame_output_port:title"></div>
        <div class="node-header">
          <div class="node-title" data-i18n="shot_frame_title" data-i18n-params='${JSON.stringify({ title: escapeHtml(node.title) })}'><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>${window.t ? window.t('shot_frame_title', { title: escapeHtml(node.title) }) : `分镜: ${escapeHtml(node.title)}`}</div>
          <button class="icon-btn" data-i18n="node_delete_btn:title" title="${window.t ? window.t('node_delete_btn') : '删除'}">×</button>
        </div>
        <div class="node-body">
          <div class="script-node-body">
            <!-- 第1列: 基础信息 -->
            <div class="script-section">
              <div class="script-section-header">
                <div class="script-section-number">1</div>
                <div class="script-section-title" data-i18n="shot_frame_basic_info_section">${window.t ? window.t('shot_frame_basic_info_section') : '基础信息'}</div>
              </div>
              <div class="field field-always-visible">
                <div class="shot-frame-desc-display" style="font-size: 13px; font-weight: 600; color: var(--text);">${escapeHtml(node.data.description)}</div>
                <div class="gen-meta shot-frame-meta" style="margin-top: 4px;" data-i18n="shot_frame_duration_label">${window.t ? window.t('shot_frame_duration_label') : '时长:'} ${node.data.duration}${window.t ? window.t('shot_frame_seconds') : '秒'} | ${escapeHtml(node.data.shotType)} | ${escapeHtml(node.data.cameraMovement)}</div>
              </div>
              <div class="field field-always-visible">
                <div class="shot-ref-section" style="position: relative;">
                  <div class="shot-ref-row">
                    <span class="shot-ref-label" data-i18n="shot_frame_scene_label">${window.t ? window.t('shot_frame_scene_label') : '场景'}</span>
                    <div class="shot-ref-tags shot-ref-scene-tags"></div>
                  </div>
                  <div class="shot-ref-row">
                    <span class="shot-ref-label" data-i18n="shot_frame_prop_label">${window.t ? window.t('shot_frame_prop_label') : '道具'}</span>
                    <div class="shot-ref-tags shot-ref-prop-tags"></div>
                  </div>
                </div>
              </div>
              <div class="field field-always-visible">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                  <div class="label" style="margin: 0;" data-i18n="shot_frame_video_first_frame_label">${window.t ? window.t('shot_frame_video_first_frame_label') : '视频首帧'}</div>
                  <div class="gen-container shot-frame-image-selector-container" style="display: none;">
                    <button class="mini-btn shot-frame-image-selector-btn" type="button" style="font-size: 11px; padding: 4px 8px; background: white; color: #333; border: 1px solid #ddd;" data-i18n="shot_frame_select_image_btn">${window.t ? window.t('shot_frame_select_image_btn') : '选择图片'}</button>
                    <button class="gen-btn-caret" type="button" aria-label="${window.t ? window.t('shot_frame_select_image_btn') : '选择图片'}" style="font-size: 11px; padding: 4px 6px;">▾</button>
                    <div class="gen-menu shot-frame-image-menu"></div>
                  </div>
                </div>
                <div class="port first-frame-port" data-i18n="shot_frame_first_frame_port:title"></div>
                <div class="shot-frame-preview-field" style="position: relative;">
                  <img class="shot-frame-preview-image" src="${escapeHtml(node.data.previewImageUrl || '')}" style="max-width: 100%; max-height: 160px; object-fit: contain; border-radius: 6px; cursor: pointer; display: ${node.data.previewImageUrl ? 'block' : 'none'};" />
                </div>
              </div>
              <div class="field field-always-visible shot-frame-image-field" style="display:${node.data.imageUrl ? 'flex' : 'none'};">
                <img class="shot-frame-image" src="${escapeHtml(node.data.imageUrl || '')}" style="max-width: 100%; max-height: 160px; object-fit: contain; border-radius: 6px; cursor: pointer;" />
              </div>
              <button class="gen-btn shot-frame-generate-dialogue-btn" type="button" style="background: #3b82f6; color: white; width: 100%; padding: 8px; border-radius: 6px; margin-top: auto;" disabled data-i18n="shot_frame_generate_dialogue_audio_btn">${window.t ? window.t('shot_frame_generate_dialogue_audio_btn') : '生成对话音频'}</button>
            </div>
            <!-- 第2列: 提示词编辑 -->
            <div class="script-section" style="background: #fcfcfc;">
              <div class="script-section-header">
                <div class="script-section-number">2</div>
                <div class="script-section-title" data-i18n="shot_frame_prompt_edit_section">${window.t ? window.t('shot_frame_prompt_edit_section') : '提示词编辑'}</div>
              </div>
              <div class="field field-always-visible" style="flex: 1; display: flex; flex-direction: column;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                  <div class="label" style="margin: 0;" data-i18n="shot_frame_image_prompt_label">${window.t ? window.t('shot_frame_image_prompt_label') : '图片提示词'}</div>
                  <span style="font-size: 10px; color: #9ca3af;" data-i18n="shot_frame_image_prompt_hint">${window.t ? window.t('shot_frame_image_prompt_hint') : '点击编辑 | 按 / 选择角色'}</span>
                </div>
                <div class="shot-prompt-display shot-frame-image-prompt-display" style="width: 100%; flex: 1; min-height: 60px; padding: 8px; border: 1px solid #ddd; border-radius: 6px; font-size: 12px; cursor: pointer; background: #fafafa; line-height: 1.6; overflow-y: auto; word-break: break-all;"></div>
              </div>
              <div class="field field-always-visible" style="flex: 1; display: flex; flex-direction: column;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                  <div class="label" style="margin: 0;" data-i18n="shot_frame_video_prompt_label">${window.t ? window.t('shot_frame_video_prompt_label') : '视频提示词'}</div>
                  <button class="mini-btn secondary reduce-violation-btn" type="button" style="font-size: 11px; padding: 4px 8px;" data-i18n="shot_frame_video_generation_failed_btn">${window.t ? window.t('shot_frame_video_generation_failed_btn') : '视频生成失败，请点此按钮'}</button>
                </div>
                <div class="shot-prompt-display shot-frame-video-prompt-display" style="width: 100%; flex: 1; min-height: 60px; padding: 8px; border: 1px solid #ddd; border-radius: 6px; font-size: 12px; cursor: pointer; background: #fafafa; line-height: 1.6; overflow-y: auto; word-break: break-all;"></div>
              </div>
            </div>
            <!-- 第3列: 模型与生成 -->
            <div class="script-section" style="background: #f9fafb;">
              <div class="script-section-header">
                <div class="script-section-number">3</div>
                <div class="script-section-title" data-i18n="shot_frame_model_generation_section">${window.t ? window.t('shot_frame_model_generation_section') : '模型与生成'}</div>
              </div>
              <div class="field field-always-visible">
                <div class="label" data-i18n="shot_frame_model_label">${window.t ? window.t('shot_frame_model_label') : '分镜模型'}</div>
                <select class="shot-frame-model"></select>
              </div>
              <div class="field field-always-visible" style="margin-bottom: 4px; margin-top: 12px;">
                <div class="gen-container" style="width: 100%;">
                  <button class="gen-btn gen-btn-main shot-frame-generate-btn" type="button" style="flex: 1; padding: 10px;" data-i18n="shot_frame_generate_btn">${window.t ? window.t('shot_frame_generate_btn') : '生成分镜图'}</button>
                  <button class="gen-btn gen-btn-caret shot-frame-caret" type="button" aria-label="${window.t ? window.t('shot_frame_select_draw_count') : '选择抽卡次数'}">▾</button>
                  <div class="gen-menu shot-frame-menu">
                    <div class="gen-item" data-count="1">X1</div>
                    <div class="gen-item" data-count="2">X2</div>
                    <div class="gen-item" data-count="3">X3</div>
                    <div class="gen-item" data-count="4">X4</div>
                  </div>
                </div>
                <div class="gen-meta shot-frame-draw-count-label"></div>
              </div>
              <div class="field field-always-visible shot-frame-video-mode-field" style="margin-top: 8px;">
                <div class="label" data-i18n="video_gen_mode_label">${window.t ? window.t('video_gen_mode_label') : '视频生成模式'}</div>
                <div class="shot-frame-video-mode-toggle" style="display:flex; border:1px solid #ddd; border-radius:6px; overflow:hidden;">
                  <button type="button" class="video-mode-btn" data-mode="first_last_frame" data-i18n="video_mode_first_frame" style="flex:1; padding:6px 8px; font-size:12px; border:none; cursor:pointer; background:#3b82f6; color:white;">${window.t ? window.t('video_mode_first_frame') : '首帧模式'}</button>
                  <button type="button" class="video-mode-btn" data-mode="multi_reference" data-i18n="video_mode_reference" style="flex:1; padding:6px 8px; font-size:12px; border:none; cursor:pointer; background:#f3f4f6; color:#666;">${window.t ? window.t('video_mode_reference') : '参考模式'}</button>
                </div>
                <div class="video-mode-hint" data-i18n="video_mode_hint_first_frame" style="font-size:11px; color:#6b7280; margin-top:4px;">${window.t ? window.t('video_mode_hint_first_frame') : '先生成分镜图作为视频首帧'}</div>
              </div>
              <div class="field field-always-visible" style="margin-top: 8px;">
                <div class="label" data-i18n="shot_group_video_model_label">${window.t ? window.t('shot_group_video_model_label') : '视频模型'}</div>
                <select class="shot-frame-video-model"></select>
              </div>
              <div class="field field-always-visible">
                <div class="label" data-i18n="shot_frame_video_duration_label">${window.t ? window.t('shot_frame_video_duration_label') : '视频时长'}</div>
                <select class="shot-frame-video-duration">
                  <option value="5" selected data-i18n="shot_frame_video_duration_5s">${window.t ? window.t('shot_frame_video_duration_5s') : '5秒'}</option>
                  <option value="10" data-i18n="shot_frame_video_duration_10s">${window.t ? window.t('shot_frame_video_duration_10s') : '10秒'}</option>
                </select>
              </div>
              <div class="shot-ref-audio-field field field-always-visible" style="margin-top: 8px; display: none;">
                <div class="label" data-i18n="shot_frame_reference_audio_label">${window.t ? window.t('shot_frame_reference_audio_label') : '参考音频（可选）'}</div>
                <input type="file" class="shot-ref-audio-input" accept="audio/*" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
                <div class="shot-ref-audio-name" style="margin-top: 4px; font-size: 11px; color: #666;"></div>
              </div>
              <div class="shot-ref-video-field field field-always-visible" style="margin-top: 8px; display: none;">
                <div class="label" data-i18n="shot_frame_reference_video_label">${window.t ? window.t('shot_frame_reference_video_label') : '参考视频（可选）'}</div>
                <input type="file" class="shot-ref-video-input" accept="video/*" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;" />
                <div class="shot-ref-video-name" style="margin-top: 4px; font-size: 11px; color: #666;"></div>
              </div>
              <div class="field field-always-visible" style="margin-top: 12px;">
                <div class="gen-container" style="width: 100%;">
                  <button class="gen-btn gen-btn-main shot-frame-generate-video-btn" type="button" style="background: #22c55e; color: white; flex: 1; padding: 10px;" data-i18n="shot_frame_generate_video_btn">${window.t ? window.t('shot_frame_generate_video_btn') : '生成视频'}</button>
                  <button class="gen-btn gen-btn-caret shot-frame-video-caret" type="button" aria-label="${window.t ? window.t('shot_frame_select_draw_count') : '选择抽卡次数'}">▾</button>
                  <div class="gen-menu shot-frame-video-menu">
                    <div class="gen-item" data-count="1">X1</div>
                    <div class="gen-item" data-count="2">X2</div>
                    <div class="gen-item" data-count="3">X3</div>
                    <div class="gen-item" data-count="4">X4</div>
                  </div>
                </div>
                <div class="gen-meta shot-frame-video-draw-count-label"></div>
              </div>
              <div class="shot-frame-video-error" style="display: none; margin-top: 8px; padding: 8px; background: #fee; border: 1px solid #fcc; border-radius: 6px; color: #c33; font-size: 12px; word-break: break-word;"></div>
              <div style="margin-top: auto; padding-top: 12px; border-top: 1px dashed #e5e7eb;">
                <div class="shot-frame-computing-power" style="padding: 6px; border-radius: 6px;">
                  <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="color: #9ca3af; font-size: 11px;" data-i18n="shot_frame_computing_power">${window.t ? window.t('shot_frame_computing_power') : '算力消耗：'}</span>
                    <span class="shot-frame-computing-power-value" style="color: #3b82f6; font-weight: bold; font-size: 12px;" data-i18n="shot_frame_computing_power_value" data-i18n-params='{"power":0}'>${window.t ? window.t('shot_frame_computing_power_value', { power: 0 }) : '0 算力'}</span>
                  </div>
                  <div class="shot-frame-computing-power-detail" style="margin-top: 2px; font-size: 10px; color: #6b7280; text-align: right;" data-i18n="shot_frame_computing_power_detail" data-i18n-params='{"individual":0,"count":1,"total":0}'>${window.t ? window.t('shot_frame_computing_power_detail', { individual: 0, count: 1, total: 0 }) : '单个 0 算力 × 1 个 = 0 算力'}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const imagePromptDisplay = el.querySelector('.shot-frame-image-prompt-display');
      const videoPromptDisplay = el.querySelector('.shot-frame-video-prompt-display');
      const imagePromptEl = imagePromptDisplay;
      const videoPromptEl = videoPromptDisplay;
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

      // 动态填充分镜模型选项
      if(modelEl) {
        modelEl.innerHTML = '';
        let firstImageModelValue = 'gpt-image-2';
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
            optEl.textContent = opt.label;
            if(opt.value === node.data.model) optEl.selected = true;
            modelEl.appendChild(optEl);
          });
        } else {
          modelEl.innerHTML = `
            <option value="gemini">标准版 (2算力)</option>
            <option value="gemini_pro">加强版 (6算力)</option>
            <option value="seedream-5.0">Seedream 5.0 (6算力)</option>
          `;
        }
        // 确保已保存的模型值在下拉框中可见
        ensureSelectHasSavedOption(modelEl, node.data.model);
        modelEl.value = node.data.model || firstImageModelValue;
        applyDriverStatusToSelect(modelEl);
      }

      // ============ 视频模型填充（根据 videoMode 动态过滤） ============

      // 根据当前 videoMode 填充视频模型选项
      function populateVideoModelOptions() {
        if(!videoModelEl) return;
        const mode = node.data.videoMode || 'first_last_frame';
        videoModelEl.innerHTML = '';
        let allOptions = [];
        let firstVideoModelValue = mode === 'multi_reference' ? 'veo3' : 'wan22';

        if(window.TaskConfig && window.TaskConfig.isLoaded()) {
          allOptions = window.TaskConfig.getModelOptionsForCategory('image_to_video');
          allOptions = allOptions.filter(opt => {
            const modes = opt.supportedImageModes || ['first_last_frame'];
            return modes.includes(mode);
          });
          if(allOptions.length > 0) firstVideoModelValue = allOptions[0].value;
          allOptions.forEach(opt => {
            const optEl = document.createElement('option');
            optEl.value = opt.value;
            optEl.textContent = opt.label;
            videoModelEl.appendChild(optEl);
          });
        } else {
          // fallback
          if(mode === 'multi_reference') {
            videoModelEl.innerHTML = `
              <option value="veo3">VEO3.1</option>
              <option value="grok">Grok</option>
              <option value="seedance_2_0">Seedance 2.0</option>
            `;
            firstVideoModelValue = 'veo3';
          } else {
            videoModelEl.innerHTML = `
              <option value="wan22">Wan2.2</option>
              <option value="sora2">Sora2</option>
              <option value="ltx2">LTX2.0</option>
              <option value="kling">可灵</option>
              <option value="vidu">Vidu</option>
              <option value="veo3">VEO3.1</option>
            `;
            firstVideoModelValue = 'wan22';
          }
        }

        // 如果当前选择的模型不在新列表中，切换到第一个
        const validValues = allOptions.map(o => o.value);
        if(validValues.length > 0 && !validValues.includes(node.data.videoModel)) {
          node.data.videoModel = firstVideoModelValue;
        }
        // 确保已保存的视频模型值在下拉框中可见
        ensureSelectHasSavedOption(videoModelEl, node.data.videoModel);
        videoModelEl.value = node.data.videoModel || firstVideoModelValue;
        applyDriverStatusToSelect(videoModelEl);
      }

      // ============ 模式切换 UI 更新 ============

      function updateModeUI() {
        const mode = node.data.videoMode || 'first_last_frame';
        const isRefMode = mode === 'multi_reference';

        // 更新提示文本
        const hintEl = el.querySelector('.video-mode-hint');
        if(hintEl) {
          const hintKey = isRefMode ? 'video_mode_hint_reference' : 'video_mode_hint_first_frame';
          hintEl.setAttribute('data-i18n', hintKey);
          hintEl.textContent = window.t ? window.t(hintKey) : (isRefMode ? '使用角色/场景/道具参考图直接生成视频（无参考图时将回退为文生视频，实际消耗以最终调用为准）' : '先生成分镜图作为视频首帧');
        }

        // 分镜模型/生成分镜图按钮降低透明度
        const generateImageBtn = el.querySelector('.shot-frame-generate-btn');
        const modelFieldEl = el.querySelector('.shot-frame-model')?.closest('.field');
        if(generateImageBtn) generateImageBtn.style.opacity = isRefMode ? '0.4' : '1';
        if(modelFieldEl) modelFieldEl.style.opacity = isRefMode ? '0.4' : '1';

        // 参考模式下，图片提示词和视频首帧区域显示为灰色/禁用
        const imagePromptFieldEl = el.querySelector('.shot-frame-image-prompt')?.closest('.field');
        const previewFieldEl = el.querySelector('.shot-frame-preview-field');
        const firstFramePortEl = el.querySelector('.first-frame-port');
        const imageFieldEl = el.querySelector('.shot-frame-image-field');
        if(imagePromptFieldEl) {
          imagePromptFieldEl.style.opacity = isRefMode ? '0.4' : '1';
          imagePromptFieldEl.style.pointerEvents = isRefMode ? 'none' : 'auto';
        }
        if(previewFieldEl) {
          previewFieldEl.style.opacity = isRefMode ? '0.4' : '1';
          previewFieldEl.style.pointerEvents = isRefMode ? 'none' : 'auto';
        }
        if(firstFramePortEl) {
          firstFramePortEl.style.opacity = isRefMode ? '0.4' : '1';
          firstFramePortEl.style.pointerEvents = isRefMode ? 'none' : 'auto';
        }
        if(imageFieldEl) {
          imageFieldEl.style.opacity = isRefMode ? '0.4' : '1';
          imageFieldEl.style.pointerEvents = isRefMode ? 'none' : 'auto';
        }

        // 参考模式下角色列表从视频提示词提取，切换模式时需刷新
        updateShotReferences();

        // 参考音视频字段可见性（参考图模式下由模型配置决定，首帧模式同理）
        updateRefAudioVideoVisibility();
      }

      // 初始化参考音视频字段可见性
      function updateRefAudioVideoVisibility() {
        const videoModel = videoModelEl ? videoModelEl.value : 'wan22';
        const mode = node.data.videoMode || 'first_last_frame';
        const refAudioField = el.querySelector('.shot-ref-audio-field');
        const refVideoField = el.querySelector('.shot-ref-video-field');

        // 参考图模式下，参考音视频始终隐藏（multi_reference 模型大多不支持）
        if(mode === 'multi_reference') {
          if(refAudioField) refAudioField.style.display = 'none';
          if(refVideoField) refVideoField.style.display = 'none';
          return;
        }

        if(window.TaskConfig && window.TaskConfig.isLoaded()) {
          const modelConfig = window.TaskConfig.getModelConfigs()[videoModel];
          const supportsRefAudioVideo = modelConfig && modelConfig.supports_ref_audio_video === true;
          if(refAudioField) refAudioField.style.display = supportsRefAudioVideo ? 'block' : 'none';
          if(refVideoField) refVideoField.style.display = supportsRefAudioVideo ? 'block' : 'none';
        } else {
          if(refAudioField) refAudioField.style.display = 'none';
          if(refVideoField) refVideoField.style.display = 'none';
        }
      }

      if(videoModelEl) {
        // 初始填充
        populateVideoModelOptions();
        updateRefAudioVideoVisibility();

        // ============ 模式切换事件 ============
        const modeBtns = el.querySelectorAll('.video-mode-btn');
        modeBtns.forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const newMode = btn.dataset.mode;
            if(newMode === node.data.videoMode) return;
            node.data.videoMode = newMode;

            // 更新切换按钮样式
            modeBtns.forEach(b => {
              const isActive = b === btn;
              b.style.background = isActive ? '#3b82f6' : '#f3f4f6';
              b.style.color = isActive ? 'white' : '#666';
            });

            // 重新填充视频模型列表
            populateVideoModelOptions();
            updateModeUI();
            // 触发算力重新计算（通过元素引用，因为函数定义在后面）
            if(el._updateVideoComputingPowerDisplay) {
              try { el._updateVideoComputingPowerDisplay(); } catch(e) {}
            }
            try{ autoSaveWorkflow(); } catch(e){}
          });
        });

        // 监听视频模型变化
        videoModelEl.addEventListener('change', () => {
          node.data.videoModel = videoModelEl.value;
          updateRefAudioVideoVisibility();
          safeAutoSave()
        });

        // 参考音频输入事件
        const refAudioInput = el.querySelector('.shot-ref-audio-input');
        if(refAudioInput) {
          refAudioInput.addEventListener('change', (e) => {
            const file = e.target.files?.[0];
            if(file) {
              node.data.refAudioFile = file;
              const nameEl = el.querySelector('.shot-ref-audio-name');
              if(nameEl) nameEl.textContent = '✓ ' + file.name;
            }
            safeAutoSave()
          });
        }

        // 参考视频输入事件
        const refVideoInput = el.querySelector('.shot-ref-video-input');
        if(refVideoInput) {
          refVideoInput.addEventListener('change', (e) => {
            const file = e.target.files?.[0];
            if(file) {
              node.data.refVideoFile = file;
              const nameEl = el.querySelector('.shot-ref-video-name');
              if(nameEl) nameEl.textContent = '✓ ' + file.name;
            }
            safeAutoSave()
          });
        }
      }

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

      // 优先使用后端返回的 db_character_info 匹配角色
      function getCharactersFromDbInfo() {
        const shotJson = node.data.shotJson || {};
        const dbCharInfo = shotJson.db_character_info;
        if(!dbCharInfo || !Array.isArray(dbCharInfo) || dbCharInfo.length === 0) {
          return null;
        }

        const worldChars = state.worldCharacters || [];
        const matchedNames = [];

        dbCharInfo.forEach(info => {
          if(info.db_character_id && info.db_character_name) {
            // 后端已匹配到数据库角色，使用 db_character_name
            if(!matchedNames.includes(info.db_character_name)) {
              matchedNames.push(info.db_character_name);
            }
          } else if(info.character_id) {
            // 后端未匹配到，尝试从 scriptData.characters 中查找名称
            const scriptData = node.data.shotJson?.scriptData || {};
            const characters = scriptData.characters || [];
            const charObj = characters.find(c => c.id === info.character_id);
            if(charObj && charObj.name) {
              // 检查该名称是否在 worldCharacters 中存在
              const existsInWorld = worldChars.some(wc => wc.name === charObj.name);
              if(existsInWorld && !matchedNames.includes(charObj.name)) {
                matchedNames.push(charObj.name);
              }
            }
          }
        });

        return matchedNames.length > 0 ? matchedNames : null;
      }

      // 初始匹配角色：优先使用 db_character_info，否则从提示词提取
      const dbMatchedChars = getCharactersFromDbInfo();
      if(dbMatchedChars) {
        node.data.refCharacters = dbMatchedChars;
      } else {
        const initMode = node.data.videoMode || 'first_last_frame';
        const initPromptSource = initMode === 'multi_reference'
          ? (node.data.videoPromptText || node.data.videoPrompt || '')
          : (node.data.imagePrompt || '');
        node.data.refCharacters = extractCharacterNames(initPromptSource);
      }

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
          const loc = (state.worldLocations || []).find(l => l.id === node.data.refScene.id);
          const hasMultiImages = loc && loc.reference_images && Array.isArray(loc.reference_images) && loc.reference_images.length > 0;
          const selectedSceneUrl = node.data.selectedSceneRefUrl;
          const tag = document.createElement('span');
          tag.className = 'shot-ref-tag scene';
          tag.title = node.data.refScene.name + (selectedSceneUrl ? '（已选特定角度）' : '（使用主图）');
          tag.innerHTML = `${escapeHtml(node.data.refScene.name)}${selectedSceneUrl ? ' ✓' : ''}<span class="ref-tag-remove" title="移除">×</span>`;
          tag.querySelector('.ref-tag-remove').addEventListener('click', (e) => {
            e.stopPropagation();
            node.data.refScene = null;
            node.data.selectedSceneRefUrl = null;
            node.data.selectedSceneRefLabel = null;
            renderSceneTags();
            safeAutoSave()
          });
          tag.addEventListener('click', (e) => {
            e.stopPropagation();
            showSceneDropdown();
          });
          sceneTagsEl.appendChild(tag);
          // 如果有多张参考图，显示角度选择按钮
          if(hasMultiImages || (loc && loc.reference_image)) {
            const selBtn = document.createElement('button');
            selBtn.className = 'scene-ref-img-btn';
            selBtn.type = 'button';
            selBtn.title = '选择角度';
            selBtn.textContent = '📷';
            selBtn.style.cssText = 'background: none; border: none; cursor: pointer; font-size: 10px; padding: 0 2px; vertical-align: middle;';
            selBtn.addEventListener('click', (e) => {
              e.stopPropagation();
              showSceneImageSelector(loc);
            });
            sceneTagsEl.appendChild(selBtn);
          }
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

      // 显示场景角度选择下拉
      function showSceneImageSelector(loc) {
        closeRefDropdowns();
        const dropdown = document.createElement('div');
        dropdown.className = 'shot-ref-dropdown scene-img-dropdown';
        dropdown.style.cssText = 'min-width: 200px; max-height: 280px; overflow-y: auto;';

        const options = [];
        if(loc.reference_image) {
          options.push({ url: loc.reference_image, label: '正面（主图）', angle: 'front', isMain: true });
        }
        if(loc.reference_images && Array.isArray(loc.reference_images)) {
          loc.reference_images.forEach(img => {
            if(img.url && (!loc.reference_image || img.url !== loc.reference_image)) {
              const label = img.label || img.angle || '其他';
              options.push({ url: img.url, label: label, angle: img.angle || 'custom', isMain: false });
            }
          });
        }

        if(options.length === 0) {
          const noImg = document.createElement('div');
          noImg.className = 'shot-ref-dropdown-item';
          noImg.textContent = '无参考图';
          dropdown.appendChild(noImg);
        } else {
          const mainItem = document.createElement('div');
          mainItem.className = 'shot-ref-dropdown-item';
          if(!node.data.selectedSceneRefUrl) mainItem.classList.add('selected');
          mainItem.innerHTML = `使用主图`;
          mainItem.addEventListener('click', (e) => {
            e.stopPropagation();
            node.data.selectedSceneRefUrl = null;
            node.data.selectedSceneRefLabel = null;
            renderSceneTags();
            closeRefDropdowns();
            safeAutoSave()
          });
          dropdown.appendChild(mainItem);

          options.filter(o => !o.isMain).forEach(opt => {
            const item = document.createElement('div');
            item.className = 'shot-ref-dropdown-item';
            if(node.data.selectedSceneRefUrl === opt.url) item.classList.add('selected');
            item.innerHTML = `<img src="${escapeHtml(opt.url)}" style="width:16px;height:16px;object-fit:cover;border-radius:2px;margin-right:6px;vertical-align:middle;">${escapeHtml(opt.label || '')}${opt.angle !== 'custom' ? '(' + escapeHtml(opt.angle) + ')' : ''}`;
            item.addEventListener('click', (e) => {
              e.stopPropagation();
              node.data.selectedSceneRefUrl = opt.url;
              node.data.selectedSceneRefLabel = opt.label;
              renderSceneTags();
              closeRefDropdowns();
              safeAutoSave()
            });
            dropdown.appendChild(item);
          });
        }

        refSectionEl.appendChild(dropdown);
        const closeHandler = (e) => {
          if(!dropdown.contains(e.target) && !e.target.classList.contains('scene-ref-img-btn')) {
            dropdown.remove();
            document.removeEventListener('click', closeHandler, true);
            _activeDropdownCloseHandler = null;
          }
        };
        if (_activeDropdownCloseHandler) document.removeEventListener('click', _activeDropdownCloseHandler, true);
        _activeDropdownCloseHandler = closeHandler;
        setTimeout(() => document.addEventListener('click', closeHandler, true), 0);
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
            safeAutoSave()
          });
          dropdown.appendChild(item);
        });
        refSectionEl.appendChild(dropdown);

        // 点击外部关闭
        const closeHandler = (e) => {
          if(!dropdown.contains(e.target)) {
            dropdown.remove();
            document.removeEventListener('click', closeHandler, true);
            _activeDropdownCloseHandler = null;
          }
        };
        if (_activeDropdownCloseHandler) document.removeEventListener('click', _activeDropdownCloseHandler, true);
        _activeDropdownCloseHandler = closeHandler;
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
            safeAutoSave()
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
            safeAutoSave()
          });
          dropdown.appendChild(item);
        });
        refSectionEl.appendChild(dropdown);

        const closeHandler = (e) => {
          if(!dropdown.contains(e.target)) {
            dropdown.remove();
            document.removeEventListener('click', closeHandler, true);
            _activeDropdownCloseHandler = null;
          }
        };
        if (_activeDropdownCloseHandler) document.removeEventListener('click', _activeDropdownCloseHandler, true);
        _activeDropdownCloseHandler = closeHandler;
        setTimeout(() => document.addEventListener('click', closeHandler, true), 0);
      }

      // 获取缩略图URL
      function getThumbnailUrl(imageUrl, size) {
        size = size || 40;
        if(!imageUrl) return '';
        if(imageUrl.startsWith('data:') || imageUrl.startsWith('blob:')) return imageUrl;
        return '/api/thumbnail?url=' + encodeURIComponent(imageUrl) + '&size=' + size;
      }

      // 渲染提示词（将【【角色名】】替换为内联角色图片）
      function renderPromptWithInlineChars(displayEl, promptText) {
        if(!displayEl) return;
        displayEl.innerHTML = '';

        const worldChars = state.worldCharacters || [];
        const pattern = /【【([^】]+)】】/g;
        let lastIndex = 0;
        let match;

        while((match = pattern.exec(promptText)) !== null) {
          // 添加匹配前的文本
          if(match.index > lastIndex) {
            const textNode = document.createTextNode(promptText.substring(lastIndex, match.index));
            displayEl.appendChild(textNode);
          }

          const charName = match[1].trim();
          const wc = worldChars.find(c => c.name === charName);

          // 如果角色不存在于数据库中，直接显示纯文本
          if(!wc) {
            const textNode = document.createTextNode(match[0]);
            displayEl.appendChild(textNode);
            lastIndex = match.index + match[0].length;
            continue;
          }

          const selectedUrl = (node.data.selectedCharRefImages && node.data.selectedCharRefImages[charName]);
          const imgUrl = selectedUrl || wc.reference_image;
          const hasImage = wc.reference_image || (wc.reference_images && wc.reference_images.length > 0);

          // 创建内联角色标签（只有存在的角色才渲染为标签）
          const chip = document.createElement('span');
          chip.className = 'shot-inline-char-chip' + (hasImage ? '' : ' no-image');
          chip.title = charName + (selectedUrl ? '（已选特定图片）' : hasImage ? '（使用主图）' : '（无参考图）');

          if(imgUrl) {
            const avatar = document.createElement('img');
            avatar.className = 'shot-inline-char-avatar';
            avatar.src = getThumbnailUrl(imgUrl, 40);
            avatar.alt = charName;
            avatar.loading = 'lazy';
            chip.appendChild(avatar);

            if(selectedUrl) {
              const check = document.createElement('span');
              check.className = 'shot-inline-char-check';
              check.textContent = '✓';
              chip.appendChild(check);
            }
          } else {
            const avatar = document.createElement('span');
            avatar.className = 'shot-inline-char-avatar no-image';
            avatar.textContent = '👤';
            chip.appendChild(avatar);
          }

          const nameSpan = document.createElement('span');
          nameSpan.className = 'shot-inline-char-name';
          nameSpan.textContent = charName;
          chip.appendChild(nameSpan);

          // 点击打开图片选择器
          chip.addEventListener('click', (e) => {
            e.stopPropagation();
            showCharImageSelector(wc, charName, chip);
          });

          displayEl.appendChild(chip);
          lastIndex = match.index + match[0].length;
        }

        // 添加剩余文本
        if(lastIndex < promptText.length) {
          const textNode = document.createTextNode(promptText.substring(lastIndex));
          displayEl.appendChild(textNode);
        }

        // 如果没有内容，显示占位文本
        if(displayEl.childNodes.length === 0) {
          displayEl.innerHTML = '<span style="color: #9ca3af;">点击编辑提示词...</span>';
        }
      }

      // 渲染角色图片（更新提示词显示）
      function renderCharImages() {
        renderPromptWithInlineChars(imagePromptDisplay, node.data.imagePrompt || '');
        renderPromptWithInlineChars(videoPromptDisplay, node.data.videoPromptText || node.data.videoPrompt || '');
      }

      // 显示角色参考图选择下拉
      function showCharImageSelector(wc, charName, anchorEl) {
        // 清理上一次的 char-img-dropdown（挂在 document.body 上，closeRefDropdowns 无法清理）
        if(_activeCharImgDropdown) {
          _activeCharImgDropdown.remove();
          _activeCharImgDropdown = null;
        }
        if(_activeCharImgCloseHandler) {
          document.removeEventListener('click', _activeCharImgCloseHandler, true);
          _activeCharImgCloseHandler = null;
        }
        closeRefDropdowns();

        console.log('[charImgSelector] charName:', charName, 'reference_image:', wc.reference_image, 'reference_images:', wc.reference_images);

        const dropdown = document.createElement('div');
        dropdown.className = 'shot-ref-dropdown char-img-dropdown';
        dropdown.style.cssText = 'min-width: 200px; max-height: 280px; overflow-y: auto; position: fixed; z-index: 10000;';

        // 关闭并清理 dropdown 的辅助函数
        function closeCharImgDropdown() {
          dropdown.remove();
          if(_activeCharImgCloseHandler) {
            document.removeEventListener('click', _activeCharImgCloseHandler, true);
          }
          _activeCharImgDropdown = null;
          _activeCharImgCloseHandler = null;
        }

        // 构建图片选项列表：主图 + reference_images
        const options = [];
        if(wc.reference_image) {
          options.push({ url: wc.reference_image, label: '默认主图', isMain: true });
        }
        if(wc.reference_images && Array.isArray(wc.reference_images)) {
          wc.reference_images.forEach(img => {
            if(img.url && img.url !== wc.reference_image) {
              options.push({ url: img.url, label: img.label || '其他', isMain: false });
            }
          });
        }

        console.log('[charImgSelector] options:', options.length, options.map(o => o.label));

        if(options.length === 0) {
          const noImg = document.createElement('div');
          noImg.className = 'shot-ref-dropdown-item';
          noImg.textContent = '无参考图';
          dropdown.appendChild(noImg);
        } else {
          // 使用主图选项
          const mainOpt = options.find(o => o.isMain);
          const otherOpts = options.filter(o => !o.isMain);
          if(mainOpt) {
            const mainItem = document.createElement('div');
            mainItem.className = 'shot-ref-dropdown-item';
            const currentSelected = (node.data.selectedCharRefImages && node.data.selectedCharRefImages[charName]);
            if(!currentSelected || currentSelected === mainOpt.url) {
              mainItem.classList.add('selected');
            }
            mainItem.innerHTML = `<img src="${escapeHtml(getThumbnailUrl(mainOpt.url, 40))}" style="width:16px;height:16px;object-fit:cover;border-radius:2px;margin-right:6px;vertical-align:middle;">主图（默认）`;
            mainItem.addEventListener('click', (e) => {
              e.stopPropagation();
              if(!node.data.selectedCharRefImages) node.data.selectedCharRefImages = {};
              delete node.data.selectedCharRefImages[charName];
              if(node.data.selectedCharRefImageLabels) delete node.data.selectedCharRefImageLabels[charName];
              closeCharImgDropdown();
              renderCharImages();
              safeAutoSave()
            });
            dropdown.appendChild(mainItem);
          }
          otherOpts.forEach(opt => {
            const item = document.createElement('div');
            item.className = 'shot-ref-dropdown-item';
            const currentSelected = (node.data.selectedCharRefImages && node.data.selectedCharRefImages[charName]);
            if(currentSelected === opt.url) {
              item.classList.add('selected');
            }
            item.innerHTML = `<img src="${escapeHtml(getThumbnailUrl(opt.url, 40))}" style="width:16px;height:16px;object-fit:cover;border-radius:2px;margin-right:6px;vertical-align:middle;">${escapeHtml(opt.label || '')}`;
            item.addEventListener('click', (e) => {
              e.stopPropagation();
              if(!node.data.selectedCharRefImages) node.data.selectedCharRefImages = {};
              if(!node.data.selectedCharRefImageLabels) node.data.selectedCharRefImageLabels = {};
              node.data.selectedCharRefImages[charName] = opt.url;
              node.data.selectedCharRefImageLabels[charName] = opt.label;
              closeCharImgDropdown();
              renderCharImages();
              safeAutoSave()
            });
            dropdown.appendChild(item);
          });
        }

        // 定位下拉框到锚点元素下方
        document.body.appendChild(dropdown);
        if(anchorEl) {
          const rect = anchorEl.getBoundingClientRect();
          dropdown.style.left = rect.left + 'px';
          dropdown.style.top = (rect.bottom + 4) + 'px';
        }

        // 注册全局引用和关闭监听
        _activeCharImgDropdown = dropdown;
        const closeHandler = (e) => {
          if(!dropdown.contains(e.target)) {
            closeCharImgDropdown();
          }
        };
        _activeCharImgCloseHandler = closeHandler;
        setTimeout(() => document.addEventListener('click', closeHandler, true), 0);
      }

      // 触发全部引用匹配并渲染
      function updateShotReferences() {
        // 重新匹配角色：优先使用 db_character_info，否则从提示词提取
        const dbMatchedChars = getCharactersFromDbInfo();
        if(dbMatchedChars) {
          node.data.refCharacters = dbMatchedChars;
        } else {
          const mode = node.data.videoMode || 'first_last_frame';
          const promptSource = mode === 'multi_reference'
            ? (node.data.videoPromptText || node.data.videoPrompt || '')
            : (node.data.imagePrompt || '');
          node.data.refCharacters = extractCharacterNames(promptSource);
        }
        renderSceneTags();
        renderPropTags();
        renderCharImages();
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
        // 检查 TaskConfig 是否已加载
        if(!window.TaskConfig || !window.TaskConfig.isLoaded()) {
          return 0;
        }

        const videoModel = node.data.videoModel || 'sora2';
        const duration = node.data.videoDuration || 10;

        // 使用 TaskConfig API 动态获取算力（自动支持所有模型）
        return TaskConfig.getComputingPower(videoModel, duration);
      }

      // 更新视频算力显示
      function updateVideoComputingPowerDisplay() {
        const singlePower = calculateVideoComputingPower();
        const count = node.data.videoDrawCount || 1;
        const totalPower = singlePower * count;

        if(computingPowerValue) {
          const displayPower = typeof totalPower === 'number' ? totalPower : 0;
          computingPowerValue.textContent = window.t ? window.t('shot_frame_computing_power_value', { power: displayPower }) : `${displayPower} 算力`;
          computingPowerValue.setAttribute('data-i18n-params', JSON.stringify({ power: displayPower }));
        }
        if(computingPowerDetail) {
          const displaySingle = typeof singlePower === 'number' ? singlePower : 0;
          const displayCount = typeof count === 'number' ? count : 1;
          const displayTotal = typeof totalPower === 'number' ? totalPower : 0;
          computingPowerDetail.textContent = window.t ? window.t('shot_frame_computing_power_detail', { individual: displaySingle, count: displayCount, total: displayTotal }) : `单个 ${displaySingle} 算力 × ${displayCount} 个 = ${displayTotal} 算力`;
          computingPowerDetail.setAttribute('data-i18n-params', JSON.stringify({ individual: displaySingle, count: displayCount, total: displayTotal }));
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
        const count = node.data.drawCount;
        const translated = window.t ? window.t('draw_count_x', { count }) : null;
        drawCountLabel.textContent = (translated && translated !== 'draw_count_x') ? translated : `抽卡次数：X${count}`;
      }
      updateDrawCountLabel();

      function updateVideoDrawCountLabel(){
        const count = node.data.videoDrawCount;
        const translated = window.t ? window.t('draw_count_x', { count }) : null;
        videoDrawCountLabel.textContent = (translated && translated !== 'draw_count_x') ? translated : `抽卡次数：X${count}`;
        // 同时更新算力显示
        updateVideoComputingPowerDisplay();
      }
      updateVideoDrawCountLabel();
      
      // 初始化算力显示，并存储引用供模式切换调用
      updateVideoComputingPowerDisplay();
      el._updateVideoComputingPowerDisplay = updateVideoComputingPowerDisplay;

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
          const ffNodes = (state.firstFrameConnections || [])
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
              
              safeAutoSave()
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
          // 不再控制 previewFieldEl 的显示，保持首帧端口始终可见
        } else {
          node.data.previewImageUrl = '';
          previewImageEl.style.display = 'none';
          // 不再控制 previewFieldEl 的显示，保持首帧端口始终可见
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
            refreshParentShotGroupPreview();
            
            renderFirstFrameConnections();
            safeAutoSave()
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
        const mode = node.data.videoMode || 'first_last_frame';
        if(mode === 'first_last_frame' && !node.data.previewImageUrl){
          showToast('请先生成分镜图', 'warning');
          return;
        }
        // multi_reference 模式不需要 previewImageUrl
        generateShotFrameVideo(id, node);
      });

      // 初始化时更新预览图
      updatePreviewImage();

      // 暴露方法供外部调用（工作流恢复时使用）
      node.updatePreview = updatePreviewImage;
      node.updateModeUI = updateModeUI;
      node.populateVideoModelOptions = populateVideoModelOptions;

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

      // 点击图片提示词区域打开放大编辑窗口
      imagePromptDisplay.addEventListener('click', (e) => {
        // 如果点击的是角色标签，不打开编辑窗口
        if(e.target.closest('.shot-inline-char-chip')) return;
        e.stopPropagation();
        // 创建一个模拟textarea的对象，提供value属性
        const mockTextarea = { value: node.data.imagePrompt || '' };
        showPromptExpandModal(mockTextarea, '图片提示词', (newValue) => {
          node.data.imagePrompt = newValue;
          updateShotReferences();
        }, { enableCharacterDropdown: true, nodeId: id });
      });

      // 点击视频提示词区域打开放大编辑窗口
      videoPromptDisplay.addEventListener('click', (e) => {
        // 如果点击的是角色标签，不打开编辑窗口
        if(e.target.closest('.shot-inline-char-chip')) return;
        e.stopPropagation();
        // 创建一个模拟textarea的对象，提供value属性
        const mockTextarea = { value: node.data.videoPromptText || node.data.videoPrompt || '' };
        showPromptExpandModal(mockTextarea, '视频提示词', (newValue) => {
          node.data.videoPromptText = newValue;
          updateShotReferences();
        }, { enableCharacterDropdown: true, nodeId: id, dropdownKey: 'videoprompt' });
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
          
          const currentPrompt = (node.data.videoPromptText || node.data.videoPrompt || '').trim();
          if(!currentPrompt){
            showToast('视频提示词为空', 'warning');
            return;
          }
          
          try {
            setBtnLoading(reduceViolationBtn, '改写提示词，修改违规内容...');
            
            const response = await fetch('/api/reduce-violation', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                ...getAuthHeaders()
              },
              body: JSON.stringify({ prompt: currentPrompt })
            });
            
            const result = await response.json();
            
            if(result.code === 0 && result.data && result.data.prompt){
              node.data.videoPromptText = result.data.prompt;
              updateShotReferences();
              showToast('提示词已改写', 'success');
            } else {
              throw new Error(result.message || '改写失败');
            }
          } catch(error){
            console.error('降低违规失败:', error);
            showToast('降低违规失败: ' + error.message, 'error');
          } finally {
            setBtnReady(reduceViolationBtn, '提示词已优化，再次优化');
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
            dialogueData: JSON.parse(JSON.stringify(node.data.shotJson.dialogue)),
            shotNumber: node.data.shotJson.shot_number,
            checkCollision: true
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
          safeAutoSave()
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
              renderAllConnections();
              
              // 如果是图片节点连接，更新预览图和选择菜单
              if(fromNode.type === 'image'){
                updatePreviewImage();
              }
              
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

      // 添加调试按钮
      addDebugButtonToNode(el, node);

      // 注册清理处理器：移除残留的 document 级事件监听器
      el._cleanupHandlers.push(function() {
        if (_activeDropdownCloseHandler) {
          document.removeEventListener('click', _activeDropdownCloseHandler, true);
          _activeDropdownCloseHandler = null;
        }
      });

      canvasEl.appendChild(el);

      // i18n: 翻译节点内 DOM
      if (typeof window.ZJTi18nDOM !== 'undefined') {
        setTimeout(() => window.ZJTi18nDOM.scanDOM(el), 0);
      }

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
        const pageSize = 50;
        const headers = {
          'Authorization': localStorage.getItem('auth_token') || '',
          'X-User-Id': localStorage.getItem('user_id') || ''
        };

        // 第一页请求
        const firstResponse = await fetch(`/api/scripts?world_id=${defaultWorldId}&page=1&page_size=${pageSize}`, { headers });
        if (!firstResponse.ok) {
          throw new Error('获取剧本列表失败');
        }
        const firstResult = await firstResponse.json();
        if (firstResult.code !== 0) {
          throw new Error(firstResult.message || '获取剧本列表失败');
        }

        let scripts = firstResult.data.data || [];
        const total = firstResult.data.total || 0;

        // 如果还有更多页，并发请求剩余页
        if (total > pageSize) {
          const totalPages = Math.ceil(total / pageSize);
          const remainingRequests = [];
          for (let p = 2; p <= totalPages; p++) {
            remainingRequests.push(
              fetch(`/api/scripts?world_id=${defaultWorldId}&page=${p}&page_size=${pageSize}`, { headers })
                .then(r => r.json())
            );
          }
          const remainingResults = await Promise.all(remainingRequests);
          for (const res of remainingResults) {
            if (res.code === 0 && res.data && res.data.data) {
              scripts = scripts.concat(res.data.data);
            }
          }
        }

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
