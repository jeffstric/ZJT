    function createImageToVideoNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = Math.max(MIN_NODE_Y, opts && typeof opts.y === 'number' ? opts.y : viewportPos.y);
      const tOr = (key, fallback, params) => {
        const translated = window.t ? window.t(key, params || {}) : '';
        return translated && translated !== key ? translated : fallback;
      };

      // 从后端配置获取第一个视频模型作为默认值
      let defaultVideoModel = 'wan22';
      if(window.TaskConfig && window.TaskConfig.isLoaded()) {
        const options = window.TaskConfig.getModelOptionsForCategory('image_to_video');
        if(options.length > 0) defaultVideoModel = options[0].value;
      }
      
      const node = {
        id,
        type: 'image_to_video',
        title: tOr('image_to_video', '生视频'),
        x,
        y,
        data: {
          prompt: opts?.data?.prompt || '',
          duration: opts?.data?.duration || 5,
          ratio: opts?.data?.ratio || state.ratio || '16:9',
          videoModel: opts?.data?.videoModel || defaultVideoModel,
          videoResolution: opts?.data?.videoResolution || opts?.videoResolution || '',
          drawCount: opts?.data?.drawCount || 1,
          motionEnabled: opts?.data?.motionEnabled || false,
          motion: opts?.data?.motion || '',
          imageMode: opts?.data?.imageMode || 'first_last_frame',  // first_last_frame | multi_reference
          processFace: opts?.data?.processFace ?? false,  // 是否处理人脸（仅 seedance2.0 商业版生效）
          startFile: null,
          endFile: null,
          startPreview: opts?.data?.startPreview || '',
          endPreview: opts?.data?.endPreview || '',
          referenceUrls: opts?.data?.referenceUrls || [],  // 多参考图模式的图片URL列表
          startUrl: opts?.data?.startUrl || '',
          endUrl: opts?.data?.endUrl || '',
          audioUrls: opts?.data?.audioUrls || [],  // [{name, url}] 参考音频列表
          videoUrls: opts?.data?.videoUrls || [],  // [{name, url}] 参考视频列表
        }
      };
      // 向后兼容：迁移旧格式的单值 audioUrl/videoUrl 到数组格式
      if(opts?.data?.audioUrl && !opts?.data?.audioUrls?.length){
        node.data.audioUrls = [{name: '已上传音频', url: opts.data.audioUrl}];
      }
      if(opts?.data?.videoUrl && !opts?.data?.videoUrls?.length){
        node.data.videoUrls = [{name: '已上传视频', url: opts.data.videoUrl}];
      }
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';

      el.innerHTML = `
        <div class="port output" title="${tOr('image_to_video_output_port', '输出（连接到视频节点）')}" data-i18n="image_to_video_output_port:title"></div>
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="3" y="6" width="14" height="12" rx="2"/><path d="M17 10L21 8V16L17 14V10Z" fill="currentColor"/></svg><span data-i18n="image_to_video">${node.title}</span></div>
          <button class="icon-btn" title="${tOr('node_delete_btn', '删除')}" data-i18n="node_delete_btn:title">×</button>
        </div>
        <div class="node-body">
          <div class="video-node-body">
            <!-- 左栏：输入源 -->
            <div class="video-section">
              <div class="field field-collapsible image-mode-field">
                <div class="label" data-i18n="image_mode_label">${tOr('image_mode_label', '图片模式')}</div>
                <select class="image-mode-select">
                  <option value="first_last_frame" data-i18n="image_mode_first_last">${tOr('image_mode_first_last', '首尾帧模式')}</option>
                  <option value="multi_reference" data-i18n="image_mode_multi_ref">${tOr('image_mode_multi_ref', '多参考图模式')}</option>
                  <option value="text_to_video" data-i18n="image_mode_text_to_video">${tOr('image_mode_text_to_video', '文生视频')}</option>
                </select>
                <div class="image-mode-hint" style="font-size: 11px; color: #6b7280; margin-top: 4px;"></div>
              </div>
              <!-- 首尾帧上下排列 -->
              <div class="field field-collapsible first-last-frame-tabs-container" style="display: none;">
                <!-- 首帧 -->
                <div class="video-frame-content active" data-frame="start">
                  <div class="label" style="margin-bottom: 4px;" data-i18n="first_frame_label">${window.t ? window.t('first_frame_label') : '首帧'}</div>
                  <div class="port start-image-port port-anchor-start" data-port-type="start" title="${window.t ? window.t('first_frame_label') : '连接图片节点（首帧）'}" style="position: relative; margin-bottom: 4px;"></div>
                  <input class="start-file" type="file" accept="image/*" />
                  <button class="mini-btn start-clear" type="button" data-i18n="node_clear_btn">${window.t ? window.t('node_clear_btn') : '清除'}</button>
                  <div class="preview-row start-preview-row" style="display:none; margin-top: 8px;">
                    <img class="preview start-preview" />
                  </div>
                </div>
                <!-- 尾帧 -->
                <div class="video-frame-content active" data-frame="end" style="margin-top: 8px;">
                  <div class="label" style="margin-bottom: 4px;" data-i18n="last_frame_label">${window.t ? window.t('last_frame_label') : '尾帧'}</div>
                  <div class="port end-image-port port-anchor-end" data-port-type="end" title="${window.t ? window.t('last_frame_label') : '连接图片节点（尾帧）'}" style="position: relative; margin-bottom: 4px;"></div>
                  <input class="end-file" type="file" accept="image/*" />
                  <button class="mini-btn end-clear" type="button" data-i18n="node_clear_btn">${window.t ? window.t('node_clear_btn') : '清除'}</button>
                  <div class="preview-row end-preview-row" style="display:none; margin-top: 8px;">
                    <img class="preview end-preview" />
                  </div>
                </div>
              </div>
              <!-- 参考图片（多参考模式） -->
              <div class="field field-collapsible reference-fields" style="display:none; position: relative;">
                <div class="port ref-image-input-port" data-port-type="ref-image" title="${window.t ? window.t('reference_frame_port') : '连接图片节点（参考图）'}"></div>
                <div class="label ref-images-label" data-i18n="reference_images_label">${window.t ? window.t('reference_images_label') : '参考图片 (1-5张)'}<span class="req">*</span></div>
                <input class="reference-file" type="file" accept="image/*" multiple />
                <button class="mini-btn reference-clear" type="button" style="margin-top: 4px;" data-i18n="clear_all_btn">${window.t ? window.t('clear_all_btn') : '清除全部'}</button>
                <div class="ref-images-counter" style="font-size: 11px; color: var(--muted); margin-top: 4px; display: none;"></div>
                <div class="reference-preview-list" style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;"></div>
              </div>
              <!-- 参考音频 -->
              <div class="field field-collapsible audio-field" style="position: relative;">
                <div class="port audio-input-port" data-port-type="audio" title="${window.t ? window.t('audio') : '连接音频节点'}"></div>
                <div class="label" data-i18n="reference_audio_label">${window.t ? window.t('reference_audio_label') : '参考音频（可选，支持多个）'}</div>
                <input class="audio-file" type="file" accept="audio/*" multiple />
                <button class="mini-btn audio-clear-all" type="button" style="margin-top: 4px;" data-i18n="clear_all_btn">${window.t ? window.t('clear_all_btn') : '清除全部'}</button>
                <div class="audio-preview-list"></div>
              </div>
              <!-- 参考视频 -->
              <div class="field field-collapsible video-field" style="position: relative;">
                <div class="port video-ref-input-port" data-port-type="video-ref" title="${window.t ? window.t('video') : '连接视频节点'}"></div>
                <div class="label" data-i18n="reference_video_label">${window.t ? window.t('reference_video_label') : '参考视频（可选，支持多个）'}</div>
                <input class="video-file" type="file" accept="video/*" multiple />
                <button class="mini-btn video-clear-all" type="button" style="margin-top: 4px;" data-i18n="clear_all_btn">${window.t ? window.t('clear_all_btn') : '清除全部'}</button>
                <div class="video-preview-list"></div>
              </div>
            </div>
            <!-- 右栏：配置参数与执行 -->
            <div class="video-section">
              <div class="field field-collapsible">
                <div class="label" data-i18n="video_length_label">${window.t ? window.t('video_length_label') : '视频长度'}</div>
                <select class="duration-select">
                  <option value="5" selected data-i18n="duration_5s">${window.t ? window.t('duration_5s') : '5秒'}</option>
                  <option value="10" data-i18n="duration_10s">${window.t ? window.t('duration_10s') : '10秒'}</option>
                </select>
              </div>
              <div class="field field-collapsible">
                <div class="label" data-i18n="video_ratio_label">${window.t ? window.t('video_ratio_label') : '视频比例'}</div>
                <select class="ratio-select">
                  <option value="9:16">9:16</option>
                  <option value="3:4">3:4</option>
                  <option value="1:1">1:1</option>
                  <option value="4:3">4:3</option>
                  <option value="16:9">16:9</option>
                </select>
              </div>
              <div class="field field-collapsible">
                <div class="label" data-i18n="video_model_label">${window.t ? window.t('video_model_label') : '视频模型'}</div>
                <select class="video-model-select"></select>
              </div>
              <div class="field field-collapsible video-resolution-field" style="display:none;">
                <div class="label" data-i18n="video_resolution">${window.t ? window.t('video_resolution') : '分辨率'}</div>
                <select class="video-resolution-select"></select>
              </div>
              <div class="field field-collapsible process-face-field" style="display:none;">
                <label style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #374151; cursor: pointer;">
                  <input type="checkbox" class="process-face-checkbox" style="cursor: pointer;" />
                  <span data-i18n="process_face_label">${window.t ? window.t('process_face_label') : '是否处理人脸'}</span>
                </label>
                <div class="process-face-hint" style="margin-top: 4px; font-size: 11px; color: #d97706; display: none;" data-i18n="process_face_community_hint">${window.t ? window.t('process_face_community_hint') : '此功能为商业版功能，请联系购买商业版本后使用'}</div>
              </div>
              <div class="field field-collapsible">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                  <div class="label" style="margin: 0;" data-i18n="prompt_label">${window.t ? window.t('prompt_label') : '提示词'}</div>
                  <button class="mini-btn prompt-expand-btn" type="button" style="font-size: 11px; padding: 4px 8px;" title="${window.t ? window.t('script_expand_btn') : '放大编辑'}" data-i18n="script_expand_btn:title">⤢</button>
                </div>
                <textarea class="prompt" placeholder="${window.t ? window.t('prompt_placeholder') : '请输入提示词，输入 @ 引用媒体文件...'}" data-i18n="prompt_placeholder:placeholder" rows="6" style="resize: vertical; min-height: 120px; font-size: 11px;"></textarea>
                <div style="font-size: 10px; color: var(--muted); margin-top: 4px;" data-i18n="prompt_tip">${window.t ? window.t('prompt_tip') : '💡 输入 @ 引用资源'}</div>
                <div class="prompt-char-count" style="text-align: right; font-size: 11px; color: var(--muted); margin-top: 2px;">0 字符</div>
              </div>
              <div class="field field-collapsible computing-power-field" style="padding: 6px; border-radius: 6px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <span style="color: #9ca3af; font-size: 12px;" data-i18n="computing_power_label">${window.t ? window.t('computing_power_label') : '算力消耗：'}</span>
                  <span class="computing-power-value" style="color: #60a5fa; font-weight: bold; font-size: 14px;" data-i18n="computing_power_value" data-i18n-params='{"power":0}'>${window.t ? window.t('computing_power_value', { power: 0 }) : '0 算力'}</span>
                </div>
                <div class="computing-power-detail" style="margin-top: 4px; font-size: 11px; color: #6b7280;" data-i18n="computing_power_detail" data-i18n-params='{"individual":0,"count":1,"total":0}'>
                  ${window.t ? window.t('computing_power_detail', { individual: 0, count: 1, total: 0 }) : '单个 0 算力 × 1 个 = 0 算力'}
                </div>
              </div>
              <div class="field field-collapsible">
                <div class="gen-container">
                  <button class="gen-btn gen-btn-main" type="button" data-i18n="generate_video_btn">${window.t ? window.t('generate_video_btn') : '生成视频'}</button>
                  <button class="gen-btn gen-btn-caret" type="button" aria-label="${window.t ? window.t('draw_count_menu') : '选择抽卡次数'}" data-i18n="draw_count_menu:aria-label">▾</button>
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
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const promptEl = el.querySelector('.prompt');
      const promptPreview = el.querySelector('.prompt-preview');
      const promptExpandBtn = el.querySelector('.prompt-expand-btn');
      const promptCharCount = el.querySelector('.prompt-char-count');
      const durationSelect = el.querySelector('.duration-select');
      const ratioSelect = el.querySelector('.ratio-select');
      const videoModelSelect = el.querySelector('.video-model-select');
      const resolutionField = el.querySelector('.video-resolution-field');
      const resolutionSelect = el.querySelector('.video-resolution-select');
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
      const imageModeSelect = el.querySelector('.image-mode-select');
      const imageModeHint = el.querySelector('.image-mode-hint');
      const firstLastFrameTabsContainer = el.querySelector('.first-last-frame-tabs-container');
      const referenceFields = el.querySelector('.reference-fields');
      const referenceFileEl = el.querySelector('.reference-file');
      const referenceClearBtn = el.querySelector('.reference-clear');
      const referencePreviewList = el.querySelector('.reference-preview-list');
      const refImagesLabel = el.querySelector('.ref-images-label');
      const refImagesCounter = el.querySelector('.ref-images-counter');
      const refImageInputPort = el.querySelector('.ref-image-input-port');
      const audioFileEl = el.querySelector('.audio-file');
      const audioClearAllBtn = el.querySelector('.audio-clear-all');
      const audioPreviewList = el.querySelector('.audio-preview-list');
      const audioInputPort = el.querySelector('.audio-input-port');
      const videoFileEl = el.querySelector('.video-file');
      const videoClearAllBtn = el.querySelector('.video-clear-all');
      const videoPreviewList = el.querySelector('.video-preview-list');
      const videoRefInputPort = el.querySelector('.video-ref-input-port');

      outputPort.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
      });

      // 动态填充视频模型选项（从 TaskConfig 获取，根据图片模式筛选）
      let firstVideoModelValue = 'wan22';
      function populateVideoModelOptions() {
        const currentMode = node.data.imageMode || 'first_last_frame';
        const modelConfigs = getModelConfigs();
        const currentValue = node.data.videoModel || videoModelSelect.value;
        videoModelSelect.innerHTML = '';

        if(window.TaskConfig && window.TaskConfig.isLoaded()) {
          const category = currentMode === 'text_to_video' ? 'text_to_video' : 'image_to_video';
          let options = window.TaskConfig.getModelOptionsForCategory(category);
          if (typeof filterVideoOptionsByDriver === 'function') {
            options = filterVideoOptionsByDriver(options);
          }
          let firstAvailable = null;

          options.forEach(opt => {
            const optEl = document.createElement('option');
            optEl.value = opt.value;
            optEl.dataset.shortKey = opt.value;

            if(currentMode === 'text_to_video') {
              // 文生视频模式：所有模型都可用
              optEl.textContent = opt.label;
              videoModelSelect.appendChild(optEl);
              if(!firstAvailable) firstAvailable = opt.value;
            } else {
              // 图生视频模式：检查 supported_image_modes
              const config = modelConfigs[opt.value];
              const supportedModes = config?.supported_image_modes || ['first_last_frame'];
              const supportsCurrentMode = supportedModes.includes(currentMode);
              optEl.textContent = supportsCurrentMode ? opt.label : opt.label + ' (不支持当前模式)';
              optEl.disabled = !supportsCurrentMode;
              videoModelSelect.appendChild(optEl);
              if(supportsCurrentMode && !firstAvailable) firstAvailable = opt.value;
            }
          });

          firstVideoModelValue = firstAvailable || options[0]?.value || 'wan22';
          if (window.ModelCatalog && videoModelSelect.parentElement) {
            const scene = window.ModelCatalog.sceneForVideoImageMode
              ? window.ModelCatalog.sceneForVideoImageMode(currentMode)
              : (currentMode === 'text_to_video' ? 'video.text_to_video' : 'video.image_to_video');
            const modeOptions = options.filter((opt) => {
              if (currentMode === 'text_to_video') return true;
              const config = modelConfigs[opt.value];
              const supportedModes = config?.supported_image_modes || ['first_last_frame'];
              return supportedModes.includes(currentMode);
            });
            const valueHit = window.ModelCatalog.findTaskByTrack(modeOptions, scene, null, 'value');
            if (valueHit && !valueHit.disabled) firstVideoModelValue = valueHit.value;
            window.ModelCatalog.bindSelectTrack(videoModelSelect.parentElement, videoModelSelect, scene, 'task');
          }
        } else {
          // 回退：硬编码选项
          const fallbackOptions = [
            { value: 'wan22', label: 'Wan2.2' },
            { value: 'sora2', label: 'Sora2' },
            { value: 'ltx2_3', label: 'LTX2.3' },
            { value: 'ltx2', label: 'LTX2.0' },
            { value: 'kling', label: '可灵' },
            { value: 'vidu', label: 'Vidu' },
            { value: 'veo3', label: 'VEO3.1' }
          ];
          fallbackOptions.forEach(opt => {
            const optEl = document.createElement('option');
            optEl.value = opt.value;
            optEl.textContent = opt.label;
            videoModelSelect.appendChild(optEl);
          });
        }
        
        // 确保已保存的视频模型值在下拉框中可见（防止TaskConfig未加载时硬编码选项不包含已保存值）
        ensureSelectHasSavedOption(videoModelSelect, currentValue);

        // 恢复之前的选择（如果仍然可用且支持当前模式）
        const selectedOption = videoModelSelect.querySelector(`option[value="${currentValue}"]:not([disabled])`);
        if(selectedOption) {
          videoModelSelect.value = currentValue;
        } else {
          // 如果保存的模型不支持当前模式，使用第一个可用的
          videoModelSelect.value = firstVideoModelValue;
          node.data.videoModel = firstVideoModelValue;
        }
      }

      // 初始化videoModel（使用后端配置的第一个选项作为默认值）
      if(!node.data.videoModel){
        node.data.videoModel = firstVideoModelValue;
      }
      
      // 先填充一次视频模型选项（使用默认的 first_last_frame 模式）
      populateVideoModelOptions();
      
      // 定义首尾帧字段选择器
      function updateResolutionOptions(videoModel) {
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

      updateResolutionOptions(node.data.videoModel);

      const firstLastFields = el.querySelectorAll('.video-frame-content');

      // 图片模式切换逻辑
      const imageModeHints = {
        'first_last_frame': '第一张为首帧，第二张（可选）为尾帧',
        'multi_reference': '所有图片作为参考',
        'text_to_video': '纯文本生成视频，无需上传图片'
      };

      // 获取当前模型的最大参考图数量
      function getMaxRefImages() {
        const modelConfigs = getModelConfigs();
        const modelKey = videoModelSelect.value;
        return modelConfigs[modelKey]?.max_multi_ref_images || 5;
      }

      // 更新参考图片标签和计数器显示
      function updateRefImagesLabel() {
        const maxCount = getMaxRefImages();
        const currentCount = (node.data.referenceUrls || []).length;
        if (refImagesLabel) {
          refImagesLabel.innerHTML = `参考图片 (1-${maxCount}张)<span class="req">*</span>`;
        }
        if (refImagesCounter) {
          if (currentCount > 0) {
            refImagesCounter.textContent = `已选择 ${currentCount}/${maxCount} 张图片`;
            refImagesCounter.style.display = '';
          } else {
            refImagesCounter.style.display = 'none';
          }
        }
      }

      function updateImageModeUI() {
        const mode = node.data.imageMode || 'first_last_frame';
        const modelConfigs = getModelConfigs();
        const config = modelConfigs[node.data.videoModel];
        const supportsLastFrame = config?.supports_last_frame !== false;

        imageModeSelect.value = mode;
        imageModeHint.textContent = imageModeHints[mode] || '';

        // 显示/隐藏首尾帧 Tab 容器
        firstLastFrameTabsContainer.style.display = mode === 'first_last_frame' ? '' : 'none';

        // 显示/隐藏参考图字段
        referenceFields.style.display = mode === 'multi_reference' ? '' : 'none';

        // 显示/隐藏端口
        startImagePort.style.display = mode === 'first_last_frame' ? '' : 'none';
        endImagePort.style.display = mode === 'first_last_frame' ? '' : 'none';

        // 显示/隐藏参考音频字段（仅在多参考图模式下显示）
        const audioField = el.querySelector('.audio-field');
        if(audioField) audioField.style.display = mode === 'multi_reference' ? '' : 'none';
        // 参考视频字段在所有模式下都显示（支持视频节点连线）

        // 根据 supports_last_frame 控制尾帧输入框的可用性
        const endFileInput = el.querySelector('.end-file');
        const endClearBtn = el.querySelector('.end-clear');
        const endPreviewRow = el.querySelector('.end-preview-row');
        // 尾帧字段是 first-last-fields 中的第二个（索引1）
        const endField = firstLastFields.length > 1 ? firstLastFields[1] : null;
        const endLabel = endField ? endField.querySelector('.label') : null;

        if (mode === 'first_last_frame') {
          if (!supportsLastFrame) {
            // 禁用尾帧输入
            if (endFileInput) endFileInput.disabled = true;
            if (endClearBtn) endClearBtn.disabled = true;
            if (endPreviewRow) endPreviewRow.style.opacity = '0.5';
            endImagePort.classList.add('disabled');
            // 修改提示文字
            if (endLabel) endLabel.textContent = '尾帧画面（该模型不支持）';
          } else {
            // 启用尾帧输入
            if (endFileInput) endFileInput.disabled = false;
            if (endClearBtn) endClearBtn.disabled = false;
            if (endPreviewRow) endPreviewRow.style.opacity = '1';
            endImagePort.classList.remove('disabled');
            // 恢复提示文字
            if (endLabel) endLabel.textContent = '尾帧画面（可选）';
          }
        }
        updateRefImagesLabel();
      }
      
      // 渲染参考图预览
      function renderReferencePreview() {
        referencePreviewList.innerHTML = '';
        (node.data.referenceUrls || []).forEach((url, idx) => {
          const item = document.createElement('div');
          item.style.cssText = 'position: relative; width: 50px; height: 50px;';
          item.innerHTML = `
            <img src="${escapeHtml(url)}" style="width: 100%; height: 100%; object-fit: cover; border-radius: 4px; cursor: pointer;" />
            <div style="position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.6); color: white; font-size: 10px; text-align: center; border-radius: 0 0 4px 4px; padding: 1px 0;">图${idx + 1}</div>
            <button class="ref-remove-btn" data-idx="${idx}" style="position: absolute; top: -4px; right: -4px; width: 16px; height: 16px; border-radius: 50%; background: #ef4444; border: none; color: white; font-size: 10px; cursor: pointer; line-height: 1;">×</button>
          `;
          item.querySelector('img').addEventListener('click', (e) => {
            e.stopPropagation();
            openImageModal(url, `图${idx + 1}`);
          });
          item.querySelector('.ref-remove-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            const removedUrl = node.data.referenceUrls[idx];
            node.data.referenceUrls.splice(idx, 1);
            // 同步删除对应的连接线
            const connIdx = state.imageConnections.findIndex(c =>
              c.to === id && c.portType === 'ref-image' &&
              state.nodes.find(n => n.id === c.from)?.data?.url === removedUrl
            );
            if(connIdx >= 0){
              state.imageConnections.splice(connIdx, 1);
              renderImageConnections();
            }
            renderReferencePreview();
          });
          referencePreviewList.appendChild(item);
        });
        updateRefImagesLabel();
      }
      
      imageModeSelect.addEventListener('change', () => {
        const oldMode = node.data.imageMode || 'first_last_frame';
        const newMode = imageModeSelect.value;
        node.data.imageMode = newMode;

        // 当模式切换时，清除不属于新模式的连接线和对应数据
        if(oldMode !== newMode){
          if(newMode === 'multi_reference'){
            // 从首位帧切换到多参考图：删除首尾帧的连接线和数据
            state.imageConnections = state.imageConnections.filter(c => {
              if(c.to === id && (c.portType === 'start' || c.portType === 'end')){
                return false;  // 删除
              }
              return true;
            });
            // 清除首尾帧数据
            node.data.startFile = null;
            node.data.startUrl = '';
            node.data.startPreview = '';
            node.data.endFile = null;
            node.data.endUrl = '';
            node.data.endPreview = '';

            // 隐藏首尾帧预览
            const startPreviewRow = el.querySelector('.start-preview-row');
            const endPreviewRow = el.querySelector('.end-preview-row');
            if(startPreviewRow) startPreviewRow.style.display = 'none';
            if(endPreviewRow) endPreviewRow.style.display = 'none';
            const startPreviewImg = el.querySelector('.start-preview-img');
            const endPreviewImg = el.querySelector('.end-preview-img');
            if(startPreviewImg) startPreviewImg.removeAttribute('src');
            if(endPreviewImg) endPreviewImg.removeAttribute('src');
            startImagePort.classList.remove('disabled');
            endImagePort.classList.remove('disabled');
          } else {
            // 从多参考图切换到首位帧：删除参考图、音频的连接线和数据（视频连接保留，视频端口在所有模式可用）
            state.imageConnections = state.imageConnections.filter(c => {
              if(c.to === id && c.portType === 'ref-image'){
                return false;  // 删除
              }
              return true;
            });
            // 清除音频连接线
            state.audioConnections = state.audioConnections.filter(c => c.to !== id);

            // 清除多参考图模式的数据（视频数据保留）
            node.data.referenceUrls = [];
            node.data.audioUrls = [];

            // 清除预览显示
            referencePreviewList.innerHTML = '';
            audioPreviewList.innerHTML = '';

            // 清除端口禁用状态
            refImageInputPort.classList.remove('disabled');
            audioInputPort.classList.remove('disabled');
            videoRefInputPort.classList.remove('disabled');
          }
        }

        updateImageModeUI();
        // 重新填充视频模型选项（根据新的图片模式筛选）
        populateVideoModelOptions();
        updateResolutionOptions(node.data.videoModel);
        // 更新时长和比例选项（新模型可能有不同的支持范围）
        updateDurationOptions(node.data.videoModel);
        updateRatioOptions(node.data.videoModel);
        // 更新算力显示
        updateComputingPowerDisplay();
        // 重新渲染连接线
        renderAllConnections();
      });
      
      // 多参考图上传处理
      referenceFileEl.addEventListener('change', async () => {
        const files = referenceFileEl.files;
        if(!files || files.length === 0) return;

        const currentCount = (node.data.referenceUrls || []).length;
        const maxCount = getMaxRefImages();
        const canAdd = maxCount - currentCount;

        if(canAdd <= 0) {
          showToast(window.t ? window.t('max_reference_images').replace('${maxCount}', maxCount) : `已达到最大数量${maxCount}张参考图，请先删除一些图片`, 'error');
          referenceFileEl.value = '';
          return;
        }

        const selectedFiles = Array.from(files);

        // 超出限制时提示还能添加几张
        if(selectedFiles.length > canAdd) {
          showToast(window.t ? window.t('auto_truncate_images').replace('${canAdd}', canAdd) : `最多还能添加${canAdd}张参考图，已自动截取前${canAdd}张`, 'info');
        }

        const filesToUpload = selectedFiles.slice(0, canAdd);
        const totalToUpload = filesToUpload.length;

        // 上传过程中禁用文件输入并显示进度
        referenceFileEl.disabled = true;
        showToast(window.t ? window.t('uploading_reference_image').replace('${totalToUpload}', totalToUpload) : `正在上传参考图 (0/${totalToUpload})...`, 'info');

        let uploadedCount = 0;
        for(const file of filesToUpload) {
          const uploadedUrl = await uploadFile(file);
          if(uploadedUrl) {
            if(!node.data.referenceUrls) node.data.referenceUrls = [];
            node.data.referenceUrls.push(uploadedUrl);
          }
          uploadedCount++;
          if(totalToUpload > 1 && uploadedCount < totalToUpload) {
            showToast(window.t ? window.t('uploading_reference_image_progress').replace('${uploadedCount}', uploadedCount).replace('${totalToUpload}', totalToUpload) : `正在上传参考图 (${uploadedCount}/${totalToUpload})...`, 'info');
          }
        }

        referenceFileEl.disabled = false;
        renderReferencePreview();
        referenceFileEl.value = '';

        const totalCount = (node.data.referenceUrls || []).length;
        showToast(window.t ? window.t('reference_images_uploaded').replace('${uploadedCount}', uploadedCount).replace('${totalCount}', totalCount).replace('${maxCount}', maxCount) : `已上传 ${uploadedCount} 张参考图，当前共 ${totalCount}/${maxCount} 张`, 'success');
      });
      
      referenceClearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        node.data.referenceUrls = [];
        // 清理所有连接到该节点的参考图片连接
        state.imageConnections = state.imageConnections.filter(c =>
          !(c.to === id && c.portType === 'ref-image')
        );
        renderReferencePreview();
        renderImageConnections();
      });

      // ===== 音频上传处理（多文件） =====
      function renderAudioPreview(){
        audioPreviewList.innerHTML = '';
        node.data.audioUrls.forEach((item, idx) => {
          const el = document.createElement('div');
          el.className = 'media-item';
          el.innerHTML = `<span class="media-name" title="${escapeHtml(item.name || '')}">🎵 音频${idx + 1}</span><span class="remove-btn">×</span>`;
          el.querySelector('.remove-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            const removedUrl = item.url;
            node.data.audioUrls.splice(idx, 1);
            // 清理对应的连接线
            state.audioConnections = state.audioConnections.filter(c => {
              if(c.to === id){
                const fromNode = state.nodes.find(n => n.id === c.from);
                if(fromNode && fromNode.data.url === removedUrl) return false;
              }
              return true;
            });
            renderAudioPreview();
            renderAudioConnections();
          });
          audioPreviewList.appendChild(el);
        });
      }

      audioFileEl.addEventListener('change', async () => {
        const files = audioFileEl.files;
        if(files && files.length > 0){
          for(const file of files){
            const url = await uploadFile(file);
            if(url){
              node.data.audioUrls.push({name: file.name, url});
            }
          }
          renderAudioPreview();
          showToast(window.t ? window.t('audio_file_upload_success') : '音频上传成功', 'success');
        }
        audioFileEl.value = '';
      });

      audioClearAllBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        node.data.audioUrls = [];
        // 清理所有连接到该节点的音频连接
        state.audioConnections = state.audioConnections.filter(c => c.to !== id);
        renderAudioPreview();
        renderAudioConnections();
      });

      // ===== 视频上传处理（多文件） =====
      function renderVideoPreview(){
        videoPreviewList.innerHTML = '';
        node.data.videoUrls.forEach((item, idx) => {
          const el = document.createElement('div');
          el.className = 'media-item';
          el.innerHTML = `<span class="media-name" title="${escapeHtml(item.name || '')}">🎬 ${window.t ? window.t('video') : '视频'}${idx + 1}</span><span class="remove-btn">×</span>`;
          el.querySelector('.remove-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            const removedUrl = item.url;
            node.data.videoUrls.splice(idx, 1);
            // 清理对应的连接线
            state.videoConnections = state.videoConnections.filter(c => {
              if(c.to === id){
                const fromNode = state.nodes.find(n => n.id === c.from);
                if(fromNode && fromNode.data.url === removedUrl) return false;
              }
              return true;
            });
            renderVideoPreview();
            renderVideoConnections();
          });
          videoPreviewList.appendChild(el);
        });
      }

      videoFileEl.addEventListener('change', async () => {
        const files = videoFileEl.files;
        if(files && files.length > 0){
          for(const file of files){
            const url = await uploadFile(file);
            if(url){
              node.data.videoUrls.push({name: file.name, url});
            }
          }
          renderVideoPreview();
          showToast(window.t ? window.t('video_file_upload_success') : '视频上传成功', 'success');
        }
        videoFileEl.value = '';
      });

      videoClearAllBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        node.data.videoUrls = [];
        // 清理所有连接到该节点的视频连接
        state.videoConnections = state.videoConnections.filter(c => c.to !== id);
        renderVideoPreview();
        renderVideoConnections();
      });

      // 恢复已保存的音频/视频预览
      renderAudioPreview();
      renderVideoPreview();

      // ===== 音频/视频/参考图输入端口：连接逻辑由全局 mouseup handler 统一处理（events.js） =====

      // 初始化图片模式UI（必须在这里调用，确保加载保存的模式）
      updateImageModeUI();
      renderReferencePreview();
      
      // 根据加载的图片模式重新填充视频模型选项
      if(opts && opts.data && opts.data.imageMode) {
        populateVideoModelOptions();
      }

      // TaskConfig 延迟加载时，更新参考图片标签
      if(window.TaskConfig) {
        window.TaskConfig.onLoaded(() => {
          updateRefImagesLabel();
          updateProcessFaceVisibility();
        });
      }
      
      // 计算算力消耗
      function calculateComputingPower() {
        // 检查 TaskConfig 是否已加载
        if(!window.TaskConfig || !window.TaskConfig.isLoaded()) {
          return 0;
        }

        const videoModel = node.data.videoModel || 'sora2';
        const duration = node.data.duration || 10;

        // 构建context，用于算力修饰符计算（支持首尾帧模式）
        const context = {};
        const imageMode = node.data.imageMode || 'first_last_frame';

        if (imageMode === 'first_last_frame') {
          // 判断是否同时存在首帧和尾帧（兼容直接上传和节点连接两种方式）
          const hasStartFile = !!node.data.startFile;
          const hasStartUrl = !!node.data.startUrl;
          const hasStartConnection = state.imageConnections.some(c => c.to === id && c.portType === 'start');
          const hasStartImage = hasStartFile || hasStartUrl || hasStartConnection;

          const hasEndFile = !!node.data.endFile;
          const hasEndUrl = !!node.data.endUrl;
          const hasEndConnection = state.imageConnections.some(c => c.to === id && c.portType === 'end');
          const hasEndImage = hasEndFile || hasEndUrl || hasEndConnection;

          if (hasStartImage && hasEndImage) {
            context['image_mode'] = 'first_last_with_tail';
          } else {
            context['image_mode'] = 'first_last_frame';
          }
        } else {
          context['image_mode'] = imageMode;
        }
        if(node.data.videoResolution) {
          context.resolution = node.data.videoResolution;
        }

        // 使用 TaskConfig API 动态获取算力，并传递context以应用修饰符
        return TaskConfig.getComputingPower(videoModel, duration, context);
      }
      
      // 更新算力显示
      function updateComputingPowerDisplay() {
        const singlePower = calculateComputingPower();
        const count = node.data.drawCount || 1;
        const totalPower = singlePower * count;

        if(computingPowerValue) {
          computingPowerValue.textContent = window.t ? window.t('computing_power_value', { power: totalPower }) : `${totalPower} 算力`;
          computingPowerValue.setAttribute('data-i18n-params', JSON.stringify({ power: totalPower }));
        }
        if(computingPowerDetail) {
          computingPowerDetail.textContent = window.t ? window.t('computing_power_detail', { individual: singlePower, count: count, total: totalPower }) : `单个 ${singlePower} 算力 × ${count} 个 = ${totalPower} 算力`;
          computingPowerDetail.setAttribute('data-i18n-params', JSON.stringify({ individual: singlePower, count: count, total: totalPower }));
        }
      }

      // 保存更新函数的引用到元素上，便于外部调用
      if(!el._updateComputingPowerDisplay) {
        el._updateComputingPowerDisplay = updateComputingPowerDisplay;
      }
      node.updateResolutionOptions = updateResolutionOptions;

      // 首帧预览更新函数
      function updateStartFrameDisplay(){
        if(node.data.startUrl && node.data.startPreview){
          startPreviewImg.src = node.data.startPreview;
          startPreviewRow.style.display = 'flex';
          startImagePort.classList.add('disabled');
        } else {
          startPreviewRow.style.display = 'none';
          startPreviewImg.removeAttribute('src');
          startImagePort.classList.remove('disabled');
        }
        adjustFramePreviewHeight();
      }

      // 尾帧预览更新函数
      function updateEndFrameDisplay(){
        if(node.data.endUrl && node.data.endPreview){
          endPreviewImg.src = node.data.endPreview;
          endPreviewRow.style.display = 'flex';
          endImagePort.classList.add('disabled');
        } else {
          endPreviewRow.style.display = 'none';
          endPreviewImg.removeAttribute('src');
          endImagePort.classList.remove('disabled');
        }
        adjustFramePreviewHeight();
      }

      // 首帧和尾帧同时存在时，预览图高度减半
      function adjustFramePreviewHeight(){
        const bothVisible = startPreviewRow.style.display !== 'none' && endPreviewRow.style.display !== 'none';
        const maxHeight = bothVisible ? '100px' : '200px';
        if(startPreviewImg) startPreviewImg.style.maxHeight = maxHeight;
        if(endPreviewImg) endPreviewImg.style.maxHeight = maxHeight;
      }

      // 保存预览更新函数的引用到元素上，便于外部调用
      if(!el._updateAudioPreview) {
        el._updateAudioPreview = renderAudioPreview;
      }
      if(!el._updateVideoPreview) {
        el._updateVideoPreview = renderVideoPreview;
      }
      if(!el._updateReferencePreview) {
        el._updateReferencePreview = renderReferencePreview;
      }
      if(!el._updateStartFrame) {
        el._updateStartFrame = updateStartFrameDisplay;
      }
      if(!el._updateEndFrame) {
        el._updateEndFrame = updateEndFrameDisplay;
      }

      durationSelect.addEventListener('change', () => {
        node.data.duration = Number(durationSelect.value);
        updateComputingPowerDisplay();
      });

      ratioSelect.value = node.data.ratio;
      ratioSelect.addEventListener('change', () => {
        node.data.ratio = ratioSelect.value;
      });

      // 根据模型更新时长选项（从后端配置获取）
      function updateDurationOptions(videoModel) {
        // 优先使用 node.data.duration，因为 durationSelect.value 可能还是 HTML 默认值
        const currentDuration = node.data.duration || durationSelect.value;
        durationSelect.innerHTML = '';
        
        const modelConfigs = getModelConfigs();
        const config = modelConfigs[videoModel];
        
        // LTX2 特殊标签
        const ltx2Labels = {
          5: '5秒 (121帧)',
          8: '8秒 (201帧)',
          10: '10秒 (241帧)'
        };
        
        if(config && config.durations && config.durations.length > 0) {
          // 从后端配置生成选项
          config.durations.forEach(duration => {
            const label = videoModel === 'ltx2' ? (ltx2Labels[duration] || `${duration}秒`) : `${duration}秒`;
            durationSelect.innerHTML += `<option value="${duration}">${label}</option>`;
          });
          
          // 检查当前值是否有效
          if(config.durations.includes(Number(currentDuration))) {
            durationSelect.value = currentDuration;
          } else {
            const defaultDuration = config.default_duration || config.durations[0];
            durationSelect.value = defaultDuration;
            node.data.duration = defaultDuration;
          }
        } else {
          // 降级：使用默认选项
          durationSelect.innerHTML = `
            <option value="5">5秒</option>
            <option value="10">10秒</option>
          `;
          durationSelect.value = '5';
          node.data.duration = 5;
        }
      }
      
      // 根据模型更新比例选项（从后端配置获取）
      function updateRatioOptions(videoModel) {
        const ratioField = ratioSelect.closest('.field');
        
        // vidu 模型隐藏比例选择器
        if(videoModel === 'vidu') {
          if(ratioField) ratioField.style.display = 'none';
          return;
        }
        
        // 其他模型显示比例选择器
        if(ratioField) ratioField.style.display = '';
        
        // 优先使用 node.data.ratio，因为 ratioSelect.value 可能还是 HTML 默认值
        const currentRatio = node.data.ratio || ratioSelect.value;
        const modelConfigs = getModelConfigs();
        const config = modelConfigs[videoModel];
        
        const labelMap = {
          '9:16': '9:16 (竖屏)',
          '16:9': '16:9 (横屏)',
          '1:1': '1:1 (方形)'
        };
        
        if(config && config.ratios && config.ratios.length > 0) {
          // 从后端配置生成选项
          ratioSelect.innerHTML = '';
          config.ratios.forEach(ratio => {
            const label = labelMap[ratio] || ratio;
            ratioSelect.innerHTML += `<option value="${ratio}">${label}</option>`;
          });
          
          // 检查当前值是否有效
          if(config.ratios.includes(currentRatio)) {
            ratioSelect.value = currentRatio;
          } else {
            const defaultRatio = config.default_ratio || config.ratios[0];
            ratioSelect.value = defaultRatio;
            node.data.ratio = defaultRatio;
          }
        } else {
          // 降级：使用默认选项
          ratioSelect.innerHTML = `
            <option value="9:16">9:16 (竖屏)</option>
            <option value="16:9">16:9 (横屏)</option>
          `;
          if(currentRatio !== '9:16' && currentRatio !== '16:9') {
            ratioSelect.value = '16:9';
            node.data.ratio = '16:9';
          } else {
            ratioSelect.value = currentRatio;
          }
        }
      }
      
      // 初始化「是否处理人脸」字段可见性（仅 seedance2.0 系列显示；社区版置灰提示）
      function updateProcessFaceVisibility() {
        const faceField = el.querySelector('.process-face-field');
        if(!faceField) return;
        const videoModel = videoModelSelect.value || node.data.videoModel || '';
        const hintEl = el.querySelector('.process-face-hint');
        const checkboxEl = el.querySelector('.process-face-checkbox');
        if(window.TaskConfig && window.TaskConfig.isLoaded()) {
          const modelConfig = window.TaskConfig.getModelConfigs()[videoModel];
          const needsFaceMask = modelConfig && modelConfig.needs_face_mask === true;
          faceField.style.display = needsFaceMask ? '' : 'none';
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

      videoModelSelect.value = node.data.videoModel;
      applyDriverStatusToSelect(videoModelSelect, node.data.videoModel);
      // 初始化时根据模型设置时长和比例选项
      updateDurationOptions(node.data.videoModel);
      updateRatioOptions(node.data.videoModel);
      updateResolutionOptions(node.data.videoModel);
      updateProcessFaceVisibility();
      
      videoModelSelect.addEventListener('change', () => {
        node.data.videoModel = videoModelSelect.value;
        // 模型改变时更新时长和比例选项
        updateDurationOptions(videoModelSelect.value);
        updateRatioOptions(videoModelSelect.value);
        updateResolutionOptions(videoModelSelect.value);
        // 更新图片模式UI（如尾帧是否支持）
        updateImageModeUI();
        // 更新「是否处理人脸」显隐
        updateProcessFaceVisibility();
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

      if(resolutionSelect) {
        resolutionSelect.addEventListener('change', () => {
          node.data.videoResolution = resolutionSelect.value;
          updateComputingPowerDisplay();
        });
      }

      // 人脸处理复选框事件
      const processFaceCheckbox = el.querySelector('.process-face-checkbox');
      if(processFaceCheckbox) {
        processFaceCheckbox.addEventListener('change', (e) => {
          node.data.processFace = !!e.target.checked;
          safeAutoSave();
        });
      }

      function updateGenMeta(){
        { const _t = window.t ? window.t('draw_count_x', { count: node.data.drawCount }) : null; genCountLabel.textContent = (_t && _t !== 'draw_count_x') ? _t : `抽卡次数：X${node.data.drawCount}`; }
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

      const _genMenuClickHandler = (e) => {
        if(!e.target.closest('.gen-container')){
          genMenu.classList.remove('show');
        }
      };
      document.addEventListener('click', _genMenuClickHandler);
      node._cleanupHandlers = node._cleanupHandlers || [];
      node._cleanupHandlers.push(() => document.removeEventListener('click', _genMenuClickHandler));

      genBtnMain.addEventListener('click', async (e) => {
        e.stopPropagation();

        // 检查提示词是否存在
        const prompt = (node.data.prompt || '').trim();
        if(!prompt){
          genStatus.style.display = 'block';
          genStatus.style.color = '#dc2626';
          genStatus.textContent = window.t ? window.t('input_prompt_first') : '请先输入提示词';
          showToast(window.t ? window.t('input_prompt_first') : '请先输入提示词', 'error');
          return;
        }

        // 根据图片模式获取图片URL
        let imageUrls = '';
        let referenceImages = '';
        const currentImageMode = node.data.imageMode || 'first_last_frame';

        if(currentImageMode === 'text_to_video') {
          // 文生视频模式：不需要图片，直接跳过
        } else if(currentImageMode === 'first_last_frame') {
          // 首尾帧模式
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
          imageUrls = endImageUrl ? `${startImageUrl},${endImageUrl}` : startImageUrl;
        } else if(currentImageMode === 'multi_reference') {
          // 多参考图模式
          const refUrls = node.data.referenceUrls || [];
          if(refUrls.length === 0){
            genStatus.style.display = 'block';
            genStatus.style.color = '#dc2626';
            genStatus.textContent = '请先上传参考图片';
            return;
          }
          // 参考图模式：reference_images 字段传参考图
          referenceImages = refUrls.join(',');
        }

        // 禁用按钮
        setBtnLoading(genBtnMain, '生成中...');
        genStatus.style.color = '';
        genStatus.style.display = 'block';
        genStatus.textContent = '正在提交任务...';

        try {
          const desiredCount = Math.max(1, Number(node.data.drawCount) || 1);
          const duration = node.data.duration || 10;
          const prompt = node.data.prompt || '';
          const ratio = node.data.ratio || state.ratio || '9:16';
          const videoModel = node.data.videoModel || 'sora2';
          
          console.log('[DEBUG] 生成视频参数:', { drawCount: node.data.drawCount, desiredCount, duration, prompt, ratio, videoModel, imageUrls, imageMode: currentImageMode, referenceImages });

          // 收集所有音频URL（上传 + 连接节点）
          let allAudioUrls = [...(node.data.audioUrls || []).map(a => a.url)];
          state.audioConnections.filter(c => c.to === id).forEach(c => {
            const fromNode = state.nodes.find(n => n.id === c.from);
            if(fromNode?.data?.url && !allAudioUrls.includes(fromNode.data.url)){
              allAudioUrls.push(fromNode.data.url);
            }
          });

          // 收集所有视频URL（上传 + 连接节点）
          let allVideoUrls = [...(node.data.videoUrls || []).map(v => v.url)];
          state.videoConnections.filter(c => c.to === id && c.portType === 'video-ref').forEach(c => {
            const fromNode = state.nodes.find(n => n.id === c.from);
            if(fromNode?.data?.url && !allVideoUrls.includes(fromNode.data.url)){
              allVideoUrls.push(fromNode.data.url);
            }
          });

          // 构建 media_references（用于 @ 提及解析）
          const mediaReferences = getMentionableItems().map(item => ({
            displayName: item.displayName,
            type: item.type,
            fileUrl: item.url
          }));

          // 调用生成API
          let result;
          if(currentImageMode === 'text_to_video') {
            result = await generateVideoFromText(prompt, duration, desiredCount, ratio, videoModel, node.data.videoResolution);
          } else {
            result = await generateVideoFromImage(imageUrls, prompt, duration, desiredCount, ratio, videoModel, currentImageMode, referenceImages, allAudioUrls.join(','), allVideoUrls.join(','), JSON.stringify(mediaReferences), node.data.videoResolution, node.data.processFace);
          }
          console.log('[DEBUG] API返回:', { projectIds: result.projectIds, count: result.projectIds?.length });
          
          genStatus.textContent = '任务已提交，正在生成视频...';
          node.data.projectIds = result.projectIds;

          const newVideoNodeIds = [];
          // 使用源节点实际宽度计算偏移，避免宽节点下视频节点被遮挡
          const sourceEl = canvasEl.querySelector(`.node[data-node-id="${id}"]`);
          const offsetX = (sourceEl ? sourceEl.offsetWidth : 300) + 60;
          for(let i = 0; i < desiredCount; i++){
            const newVideoId = createVideoNode({ x: node.x + offsetX, y: node.y + i * 260, checkCollision: true });
            const connId = state.nextConnId++;
            state.connections.push({ id: connId, from: id, to: newVideoId });
            console.log(`[图生视频] 添加连接: from=${id} to=${newVideoId} connId=${connId}`, {
              from: getOutputPortPos(id),
              to: getInputPortPos(newVideoId)
            });
            newVideoNodeIds.push(newVideoId);

            // 立即为新创建的视频节点绑定 project_id
            const newVideoNode = state.nodes.find(n => n.id === newVideoId);
            if(newVideoNode && result.projectIds){
              newVideoNode.data.project_id = result.projectIds[i] || result.projectIds[0];
              console.log(`[图生视频] 新建视频节点 ${newVideoId} 绑定 project_id:`, newVideoNode.data.project_id);
            }
          }
          
          // 所有视频节点ID（只包含新创建的节点）
          const allVideoNodeIds = [...newVideoNodeIds];

          renderAllConnections();
          renderMinimap();
          safeAutoSave()

          // 为每个视频节点初始化状态显示
          allVideoNodeIds.forEach((videoNodeId, idx) => {
            const videoEl = canvasEl.querySelector(`.node[data-node-id="${videoNodeId}"]`);
            if(videoEl){
              const statusField = videoEl.querySelector('.video-status-field');
              const statusEl = videoEl.querySelector('.video-status');
              if(statusField && statusEl){
                statusField.style.display = 'block';
                setStatusEl(statusEl, '生成中...');
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

              setBtnReady(genBtnMain, '生成视频');
              
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
                      // 封面帧与悬停播放逻辑已内置于 setupVideoThumbnail
                      setupVideoThumbnail(thumbVideo, videoUrl);
                      const displayName = videoNode.data.name.length > 10 ? videoNode.data.name.substring(0, 10) + '...' : videoNode.data.name;
                      nameEl.textContent = displayName;
                      nameEl.title = videoNode.data.name;
                      previewField.style.display = 'block';
                      const previewActionsField2 = videoEl.querySelector('.video-preview-actions-field');
                      if(previewActionsField2) previewActionsField2.style.display = 'block';
                    }
                    
                    if(statusField && statusEl){
                      setStatusEl(statusEl, '✓ 生成成功', '#16a34a');
                    }
                  } else {
                    if(statusField && statusEl){
                      setStatusEl(statusEl, '✗ 生成成功但未返回视频地址', '#dc2626');
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
                showToast(window.t ? window.t('video_generation_success') : '视频生成成功！', 'success');
              } else if(failedCount === totalCount && failedCount > 0){
                // 全部失败
                genStatus.style.color = '#dc2626';
                genStatus.textContent = `全部失败：${failedCount}个任务失败`;
                showToast(window.t ? window.t('video_generation_failed') : '视频生成失败', 'error');
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

              // 视频节点内容已更新，重新渲染连接线
              renderAllConnections();
              renderMinimap();

              // 刷新用户算力显示
              if(typeof fetchComputingPower === 'function'){
                fetchComputingPower();
              }
            },
            (errorMsg) => {
              // 轮询或请求失败
              // 截断过长的错误信息
              const truncatedError = truncateErrorMessage(errorMsg);
              genStatus.style.color = '#dc2626';
              genStatus.textContent = truncatedError;
              setBtnReady(genBtnMain, '生成视频');
              
              // 更新所有视频节点状态为失败
              allVideoNodeIds.forEach((videoNodeId) => {
                const videoEl = canvasEl.querySelector(`.node[data-node-id="${videoNodeId}"]`);
                if(videoEl){
                  const statusField = videoEl.querySelector('.video-status-field');
                  const statusEl = videoEl.querySelector('.video-status');
                  if(statusField && statusEl){
                    statusField.style.display = 'block';
                    setStatusEl(statusEl, `✗ ${truncatedError}`, '#dc2626');
                  }
                }
              });

              showToast('视频生成失败: ' + truncatedError, 'error');

              // 重新渲染连接线
              renderConnections();
              renderMinimap();
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
                  setStatusEl(statusEl, `✗ 生成失败: ${truncateErrorMessage(task.error) || '未知错误'}`, '#dc2626');
                } else if(task.status === 'SUCCESS' && task.result){
                  // 成功的任务在这里只更新状态文本，视频加载留给onComplete处理
                  statusField.style.display = 'block';
                  setStatusEl(statusEl, '✓ 生成成功，加载中...', '#16a34a');
                } else if(task.status === 'RUNNING'){
                  // 运行中的任务保持"生成中..."状态
                  statusField.style.display = 'block';
                  setStatusEl(statusEl, '生成中...');
                }
              });
            }
          );

        } catch(err){
          console.error('Generate error:', err);
          const truncatedErr = truncateErrorMessage(err.message);
          genStatus.style.color = '#dc2626';
          genStatus.textContent = truncatedErr || '生成失败';
          setBtnReady(genBtnMain, '生成视频');
          showToast('视频生成失败: ' + truncatedErr, 'error');
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

      // 图片端口：连接逻辑由全局 mouseup handler 统一处理（events.js）

      // 初始化提示词
      if(node.data.prompt) {
        promptEl.value = node.data.prompt;
        if(promptPreview) {
          const preview = node.data.prompt.length > 50 ? node.data.prompt.substring(0, 50) + '...' : node.data.prompt;
          promptPreview.textContent = preview;
          promptPreview.style.display = 'block';
        }
      }
      
      promptEl.addEventListener('input', () => {
        node.data.prompt = promptEl.value;
        if(promptPreview) {
          const preview = node.data.prompt ? (node.data.prompt.length > 50 ? node.data.prompt.substring(0, 50) + '...' : node.data.prompt) : '';
          promptPreview.textContent = preview;
          promptPreview.style.display = preview ? 'block' : 'none';
        }
        if(promptCharCount) {
          promptCharCount.textContent = `${promptEl.value.length} 字符`;
        }
        // @ 提及检测
        checkMentionTrigger();
      });

      // ===== @ 提及系统 =====
      let mentionState = { visible: false, query: '', queryStart: -1, selectedIndex: 0 };
      let mentionDropdownEl = null;

      function getMentionableItems(){
        const items = [];
        if(node.data.startUrl) items.push({displayName: '首帧图片', type: 'image', url: node.data.startUrl});
        if(node.data.endUrl) items.push({displayName: '尾帧图片', type: 'image', url: node.data.endUrl});
        (node.data.referenceUrls || []).forEach((url, i) => items.push({displayName: `Image${i+1}`, type: 'image', url}));
        (node.data.audioUrls || []).forEach((item, i) => items.push({displayName: `音频${i+1}`, type: 'audio', url: item.url}));
        (node.data.videoUrls || []).forEach((item, i) => items.push({displayName: `视频${i+1}`, type: 'video', url: item.url}));
        return items;
      }

      function checkMentionTrigger(){
        const cursorPos = promptEl.selectionStart;
        const textBefore = promptEl.value.substring(0, cursorPos);
        const match = textBefore.match(/@([^@\s]*)$/);
        if(match){
          mentionState.visible = true;
          mentionState.query = match[1];
          mentionState.queryStart = cursorPos - match[0].length;
          mentionState.selectedIndex = 0;
          showMentionDropdown();
        } else {
          hideMentionDropdown();
        }
      }

      function showMentionDropdown(){
        const items = getMentionableItems();
        const query = mentionState.query.toLowerCase();
        const filtered = items.filter(item =>
          item.displayName.toLowerCase().includes(query) ||
          (item.type === 'image' && '图片'.includes(query)) ||
          (item.type === 'audio' && '音频'.includes(query)) ||
          (item.type === 'video' && '视频'.includes(query))
        );
        if(filtered.length === 0){
          hideMentionDropdown();
          return;
        }
        if(!mentionDropdownEl){
          mentionDropdownEl = document.createElement('div');
          mentionDropdownEl.className = 'mention-dropdown';
          promptEl.parentElement.style.position = 'relative';
          promptEl.parentElement.appendChild(mentionDropdownEl);
        }
        const typeIcons = {image: '🖼️', audio: '🎵', video: '🎬'};
        const typeNames = {image: '图片', audio: '音频', video: '视频'};
        mentionDropdownEl.innerHTML = filtered.map((item, i) => {
          const isImage = item.type === 'image';
          const thumbHtml = isImage && item.url ? `<img src="${escapeHtml(item.url)}" class="mention-thumb" style="width:32px;height:32px;object-fit:cover;border-radius:4px;margin-right:8px;flex-shrink:0;" />` : '';
          return `<div class="mention-dropdown-item${i === mentionState.selectedIndex ? ' selected' : ''}" data-index="${i}" style="display:flex;align-items:center;padding:6px 10px;cursor:pointer;">` +
            thumbHtml +
            `<span class="mention-icon" style="margin-right:6px;">${typeIcons[item.type] || '📄'}</span>` +
            `<span class="mention-name" style="flex:1;">${escapeHtml(item.displayName || '')}</span>` +
            `<span class="mention-type" style="font-size:11px;color:#9ca3af;margin-left:8px;">${typeNames[item.type] || item.type}</span>` +
            `</div>`;
        }).join('');
        mentionDropdownEl.style.display = 'block';
        // 点击选择
        mentionDropdownEl.querySelectorAll('.mention-dropdown-item').forEach(el => {
          el.addEventListener('mousedown', (e) => {
            e.preventDefault();
            const idx = parseInt(el.dataset.index);
            insertMention(filtered[idx]);
          });
        });
      }

      function hideMentionDropdown(){
        mentionState.visible = false;
        if(mentionDropdownEl) mentionDropdownEl.style.display = 'none';
      }

      function insertMention(item){
        const before = promptEl.value.substring(0, mentionState.queryStart);
        const after = promptEl.value.substring(promptEl.selectionStart);
        promptEl.value = before + '@' + item.displayName + ' ' + after;
        node.data.prompt = promptEl.value;
        hideMentionDropdown();
        promptEl.focus();
        const newPos = mentionState.queryStart + item.displayName.length + 2;
        promptEl.setSelectionRange(newPos, newPos);
        if(promptPreview){
          const preview = node.data.prompt.length > 50 ? node.data.prompt.substring(0, 50) + '...' : node.data.prompt;
          promptPreview.textContent = preview;
        }
        if(promptCharCount) promptCharCount.textContent = `${promptEl.value.length} 字符`;
      }

      promptEl.addEventListener('keydown', (e) => {
        if(!mentionState.visible) return;
        const items = getMentionableItems();
        const query = mentionState.query.toLowerCase();
        const filtered = items.filter(item =>
          item.displayName.toLowerCase().includes(query) ||
          (item.type === 'image' && '图片'.includes(query)) ||
          (item.type === 'audio' && '音频'.includes(query)) ||
          (item.type === 'video' && '视频'.includes(query))
        );
        if(filtered.length === 0) return;
        if(e.key === 'ArrowDown'){
          e.preventDefault();
          mentionState.selectedIndex = Math.min(mentionState.selectedIndex + 1, filtered.length - 1);
          showMentionDropdown();
        } else if(e.key === 'ArrowUp'){
          e.preventDefault();
          mentionState.selectedIndex = Math.max(mentionState.selectedIndex - 1, 0);
          showMentionDropdown();
        } else if(e.key === 'Enter' || e.key === 'Tab'){
          e.preventDefault();
          insertMention(filtered[mentionState.selectedIndex]);
        } else if(e.key === 'Escape'){
          e.preventDefault();
          hideMentionDropdown();
        }
      });

      promptEl.addEventListener('blur', () => {
        setTimeout(hideMentionDropdown, 200);
      });

      // 放大编辑按钮点击事件
      if(promptExpandBtn) {
        promptExpandBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          showPromptExpandModal(promptEl, '提示词', (newValue) => {
            node.data.prompt = newValue;
            promptEl.value = newValue;
            if(promptCharCount) {
              promptCharCount.textContent = `${newValue.length} 字符`;
            }
            if(promptPreview) {
              const preview = newValue ? (newValue.length > 50 ? newValue.substring(0, 50) + '...' : newValue) : '';
              promptPreview.textContent = preview;
              promptPreview.style.display = preview ? 'block' : 'none';
            }
          });
        });
      }

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
          renderAllConnections();
          updateComputingPowerDisplay();  // 更新算力显示
          showToast(window.t ? window.t('first_frame_upload_success') : '首帧图片上传成功', 'success');
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
          renderAllConnections();
          updateComputingPowerDisplay();  // 更新算力显示
          showToast(window.t ? window.t('last_frame_upload_success') : '尾帧图片上传成功', 'success');
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
        // 清理对应的连接线
        state.imageConnections = state.imageConnections.filter(c => !(c.to === id && c.portType === 'start'));
        startPreviewRow.style.display = 'none';
        startPreviewImg.removeAttribute('src');
        startImagePort.classList.remove('disabled');
        adjustFramePreviewHeight();
        renderImageConnections();
        updateComputingPowerDisplay();  // 更新算力显示
        safeAutoSave()
      });

      endClearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        node.data.endFile = null;
        node.data.endUrl = '';
        node.data.endPreview = '';
        // 清理对应的连接线
        state.imageConnections = state.imageConnections.filter(c => !(c.to === id && c.portType === 'end'));
        endPreviewRow.style.display = 'none';
        endPreviewImg.removeAttribute('src');
        endImagePort.classList.remove('disabled');
        adjustFramePreviewHeight();
        renderImageConnections();
        updateComputingPowerDisplay();  // 更新算力显示
        safeAutoSave()
      });

      // 初始化：恢复已保存的图片预览
      if(node.data.startUrl && node.data.startPreview) {
        startPreviewImg.src = node.data.startPreview;
        startPreviewRow.style.display = 'flex';
        startImagePort.classList.add('disabled');
      }
      if(node.data.endUrl && node.data.endPreview) {
        endPreviewImg.src = node.data.endPreview;
        endPreviewRow.style.display = 'flex';
        endImagePort.classList.add('disabled');
      }

      // 添加调试按钮
      addDebugButtonToNode(el, node);

      canvasEl.appendChild(el);

      // i18n: 翻译节点内 DOM
      if (typeof window.ZJTi18nDOM !== 'undefined') {
        setTimeout(() => window.ZJTi18nDOM.scanDOM(el), 0);
      }

      setSelected(id);
      return id;
    }

    // ── 注册 image_to_video 输入端口（供连接系统自动发现）───
    if (typeof registerInputPorts === 'function') {
      registerInputPorts('image_to_video', [
        // 首帧端口（接受图片节点连接）
        PORT_PRESETS.IMAGE_INPUT({
          guard: function(n) { return !n.data.startFile; }
        }),
        // 尾帧端口
        {
          selector: '.end-image-port',
          portType: 'end',
          accepts: ['image'],
          connectionType: 'imageConnections',
          guard: function(n) { return !n.data.endFile; }
        },
        // 参考图端口（多参考模式，允许多连接）
        {
          selector: '.ref-image-input-port',
          portType: 'ref-image',
          accepts: ['image'],
          connectionType: 'imageConnections',
          allowMultiple: true,
          guard: function(n) {
            if (n.data.imageMode !== 'multi_reference') return false;
            if (window.TaskConfig && window.TaskConfig.isLoaded()) {
              var modelConfigs = window.TaskConfig.getModelConfigs();
              var maxCount = modelConfigs[n.data.videoModel] && modelConfigs[n.data.videoModel].max_multi_ref_images || 5;
              return (n.data.referenceUrls || []).length < maxCount;
            }
            return true;
          }
        },
        // 音频端口（接受音频节点连接）
        PORT_PRESETS.AUDIO_INPUT(),
        // 视频端口（接受视频节点连接，允许多连接）
        {
          selector: '.video-ref-input-port',
          portType: 'video-ref',
          accepts: ['video'],
          connectionType: 'videoConnections',
          allowMultiple: true,
          guard: function(n) {
            // 限制最多 3 个参考视频
            return (n.data.videoUrls || []).length < 3;
          }
        }
      ]);
    }
