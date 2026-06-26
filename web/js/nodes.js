    // ============ 驱动状态检查 ============

    // 截断过长的错误信息，提取关键错误内容
    function truncateErrorMessage(errorMsg, maxLength = 120) {
      if(!errorMsg) return errorMsg;
      let msg = String(errorMsg);
      // 如果包含 JSON 错误响应，尝试提取关键错误信息
      if(msg.includes('"error"') || msg.includes('"message"')) {
        try {
          // 尝试提取 JSON 中的 message 或 failureReasons
          const messageMatch = msg.match(/"message"\s*:\s*"([^"]+)"/);
          if(messageMatch) {
            const failureMatch = msg.match(/"failureReasons"\s*:\s*\[("[^"]+")\]/);
            if(failureMatch) {
              return `${messageMatch[1]} (${failureMatch[1].replace(/"/g, '')})`;
            }
            return messageMatch[1];
          }
        } catch(e) {
          // 解析失败，继续截断
        }
      }
      // 如果包含 "check status failed:" 前缀，移除它
      if(msg.toLowerCase().startsWith('check status failed:')) {
        msg = msg.substring(20).trim();
      }
      // 截断过长的信息
      if(msg.length > maxLength) {
        return msg.substring(0, maxLength) + '...';
      }
      return msg;
    }

    // 通用函数：根据 driver 状态禁用 select 选项
    function applyDriverStatusToSelect(selectEl) {
      if(!selectEl) return;

      const driverStatus = getDriverStatusConfig();

      if(!driverStatus || Object.keys(driverStatus).length === 0) return;

      selectEl.querySelectorAll('option').forEach(option => {
        const taskType = window.TaskConfig ? window.TaskConfig.getTaskIdByKey(option.value) : null;
        if(taskType && driverStatus[taskType] && driverStatus[taskType].available === false) {
          option.disabled = true;
          if(!option.textContent.includes('(未配置)')) {
            option.textContent += ' (未配置)';
          }
        }
      });
    }

    /**
     * 确保select元素包含已保存的值作为选项
     * 当TaskConfig未加载时使用硬编码回退选项，但已保存的值可能不在回退列表中
     * 此函数将已保存的值作为临时选项添加，确保视觉显示正确
     * 后续 refreshShotGroupNodesModels/refreshShotFrameNodesModels 会用完整列表替换
     */
    function ensureSelectHasSavedOption(selectEl, savedValue) {
      if (!selectEl || !savedValue) return;
      // 检查已保存的值是否已在选项中
      for (let i = 0; i < selectEl.options.length; i++) {
        if (selectEl.options[i].value === savedValue) return;
      }
      // 值不在选项中，添加为临时选项并选中
      const optEl = document.createElement('option');
      optEl.value = savedValue;
      optEl.textContent = savedValue;
      optEl.selected = true;
      selectEl.insertBefore(optEl, selectEl.firstChild);
    }

    // 检查指定模型是否可用
    function isModelAvailable(modelValue) {
      const driverStatus = getDriverStatusConfig();

      if(!driverStatus || Object.keys(driverStatus).length === 0) return true;

      const taskType = window.TaskConfig ? window.TaskConfig.getTaskIdByKey(modelValue) : null;
      if(!taskType) return true;

      return driverStatus[taskType]?.available !== false;
    }
    
    // ============ 宫格提示词生成 ============

    const DEFAULT_GRID_IMAGE_MODEL = 'gpt-image-2';

    function getDefaultGridImageModelValue(options = null) {
      const imageOptions = options || ((window.TaskConfig && window.TaskConfig.isLoaded())
        ? window.TaskConfig.getModelOptionsForCategory('image_edit')
        : []);
      const gridOptions = imageOptions.filter(opt => opt.supportsGridImage);
      const gptImage2 = gridOptions.find(opt => opt.value === DEFAULT_GRID_IMAGE_MODEL);
      if(gptImage2) return gptImage2.value;
      return gridOptions[0]?.value || DEFAULT_GRID_IMAGE_MODEL;
    }

    function normalizeGridImageModelValue(modelValue, options = null) {
      if(!modelValue || modelValue === 'auto') return getDefaultGridImageModelValue(options);
      return modelValue;
    }

    function populateGridImageModelSelect(selectEl, savedValue) {
      if(!selectEl) return DEFAULT_GRID_IMAGE_MODEL;

      selectEl.innerHTML = '';
      let options = [];
      if(window.TaskConfig && window.TaskConfig.isLoaded()) {
        options = window.TaskConfig.getModelOptionsForCategory('image_edit').filter(opt => opt.supportsGridImage);
        options.forEach(opt => {
          const optEl = document.createElement('option');
          optEl.value = opt.value;
          optEl.textContent = opt.label;
          selectEl.appendChild(optEl);
        });
      } else {
        selectEl.innerHTML = `
          <option value="gpt-image-2">GPT Image 2</option>
          <option value="gemini-3-pro-4grid">加强版4宫格</option>
          <option value="gemini-3-pro-image-preview">加强版9宫格</option>
          <option value="seedream-5.0">Seedream 5.0</option>
        `;
      }

      const selectedValue = normalizeGridImageModelValue(savedValue, options);
      ensureSelectHasSavedOption(selectEl, selectedValue);
      selectEl.value = selectedValue;
      return selectedValue;
    }

    // 根据 gridModel 和 gridLayout 用户偏好，计算最终的 gridSize / gridLayout / finalModel
    function resolveGridConfig(gridModel, gridLayoutPref, shotCount, forceEnhancedModel) {
      let gridSize, gridLayout, finalModel;

      // 如果用户明确选择了宫格类型，以用户选择为准
      if(gridLayoutPref === '4') {
        gridSize = 4;
        gridLayout = '2x2';
      } else if(gridLayoutPref === '9') {
        gridSize = 9;
        gridLayout = '3x3';
      }

      if(gridModel === 'auto') {
        // 兼容旧工作流保存的 auto，实际统一使用 GPT Image 2。
        finalModel = DEFAULT_GRID_IMAGE_MODEL;
        if(gridLayoutPref === '4') {
          // 保持 4宫格配置
        } else if(gridLayoutPref === '9') {
          // 保持 9宫格配置
        } else {
          // auto: 根据分镜数量自动选择宫格大小
          if(shotCount <= 5) {
            gridSize = 4;
            gridLayout = '2x2';
          } else {
            gridSize = 9;
            gridLayout = '3x3';
          }
        }
      } else if(gridModel === 'gemini-2.5-flash-image-preview' && !forceEnhancedModel) {
        // 标准版（但如果参考图超过5张则强制升级）
        if(!gridLayoutPref || gridLayoutPref === 'auto') {
          gridSize = 4;
          gridLayout = '2x2';
        }
        finalModel = gridModel;
      } else if(gridModel === 'gemini-3-pro-4grid') {
        if(!gridLayoutPref || gridLayoutPref === 'auto') {
          gridSize = 4;
          gridLayout = '2x2';
        }
        finalModel = 'gemini-3-pro-image-preview';
      } else if(gridModel === 'gemini-3-pro-image-preview') {
        if(!gridLayoutPref || gridLayoutPref === 'auto') {
          gridSize = 9;
          gridLayout = '3x3';
        }
        finalModel = gridModel;
      } else {
        // 用户选择了其他模型（如 Seedream）
        if(!gridLayoutPref || gridLayoutPref === 'auto') {
          gridSize = 9;
          gridLayout = '3x3';
        }
        finalModel = gridModel;
      }

      return { gridSize, gridLayout, finalModel };
    }

    function buildGridPrompt(batchNodes, startIdx, gridLayout, gridSize) {
      const artStyleName = (state.style && state.style.name) ? state.style.name : '';
      const aspectRatio = state.ratio || '16:9';
      const [gridCols, gridRows] = gridLayout.split('x').map(Number);
      const [aw, ah] = aspectRatio.split(':').map(Number);
      const isPortrait = ah > aw;
      const totalPanels = gridSize;
      const formatLabel = isPortrait ? `Vertical ${aspectRatio} Poster` : `Cinematic ${aspectRatio} Wide`;
      const compositionHint = isPortrait ? `Vertical ${aspectRatio} framing` : `Cinematic ${aspectRatio} Wide framing`;
      const posLabels4 = ['Top-Left', 'Top-Right', 'Bottom-Left', 'Bottom-Right'];
      const posLabels9 = ['Top-Left', 'Top-Center', 'Top-Right', 'Middle-Left', 'Middle-Center', 'Middle-Right', 'Bottom-Left', 'Bottom-Center', 'Bottom-Right'];
      const posLabels = gridSize === 4 ? posLabels4 : posLabels9;

      const shots = [];
      for (let idx = 0; idx < gridSize; idx++) {
        let rawPrompt;
        if (idx < batchNodes.length) {
          rawPrompt = batchNodes[idx].data.imagePrompt || '';
        } else {
          const lastValid = batchNodes.length > 0 ? (batchNodes[batchNodes.length - 1].data.imagePrompt || '') : '';
          rawPrompt = lastValid || 'Empty background scene, detailed texture, ambient environment';
        }
        const panelNum = startIdx + idx + 1;
        const posLabel = posLabels[idx] || '';
        shots.push({
          shot_number: `${panelNum} (${posLabel})`,
          prompt_text: `**[Panel ${panelNum} of ${totalPanels}: ${posLabel} Quadrant]**\n<Subject>: ${rawPrompt}\n<Composition>: ${compositionHint}.`
        });
      }

      let styleGuidance = `Format: [${formatLabel}]. Layout: STRICT ${gridLayout} GRID (Total ${totalPanels} panels). Structure: ${gridRows === 2 ? 'Top row has 2 panels, Bottom row has 2 panels.' : `${gridRows} rows, each with ${gridCols} panels.`}`;
      styleGuidance += `\n\n[CRITICAL CONSTRAINTS]:\n1. Do NOT generate a comic strip.\n2. Do NOT generate ${totalPanels * 2} panels.\n3. STOP after row ${gridRows}.\n4. Distinct Separation: Use thin black lines to divide the ${totalPanels} panels.`;
      if (artStyleName) {
        styleGuidance += `\n\n[Art Style]: ${artStyleName}. Every panel must consistently use this exact art style.`;
      }

      const gridPromptObj = {
        grid_layout: gridLayout,
        grid_aspect_ratio: aspectRatio,
        grid_structure: `${gridRows} rows x ${gridCols} columns`,
        cell_aspect_ratio: aspectRatio,
        style_guidance: styleGuidance,
        shots: shots
      };
      if (artStyleName) { gridPromptObj.art_style = artStyleName; }
      return JSON.stringify(gridPromptObj);
    }

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
          showToast(window.t ? window.t('node_info_output').replace('${node.title}', node.title) : `节点 ${node.title} 信息已输出到控制台`, 'info');
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
                headers: getAuthHeaders()
              });
              if (response.ok) {
                const result = await response.json();
                if (result.code === 0 && result.data && Array.isArray(result.data.data) && result.data.data.length > 0) {
                  const matchedChar = result.data.data.find(c => c.name === characterName) || result.data.data[0];
                  if (matchedChar && matchedChar.reference_image) {
                    // 优先使用用户为该角色选择的特定图片，否则使用主图
                    const userSelectedUrl = (shotNode.data.selectedCharRefImages && shotNode.data.selectedCharRefImages[characterName]);
                    const charRefUrl = userSelectedUrl || matchedChar.reference_image;
                    referenceImageUrls.push(charRefUrl);
                    const labelSuffix = userSelectedUrl && userSelectedUrl !== matchedChar.reference_image
                      ? `的${(shotNode.data.selectedCharRefImageLabels && shotNode.data.selectedCharRefImageLabels[characterName]) || '已选择'}`
                      : '';
                    promptSuffix.push(`图${imageIndex}是${characterName}${labelSuffix}`);
                    imageIndex++;
                    console.log(`[宫格生图] 收集角色参考图URL: ${characterName}${labelSuffix ? '(' + labelSuffix + ')' : '(主图)'}`);
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
              headers: getAuthHeaders()
            });
            if (response.ok) {
              const result = await response.json();
              if (result.code === 0 && result.data) {
                const locData = result.data;
                // 优先使用用户选择的特定图片，否则使用主图
                const mainSceneRef = locData.reference_image;
                const sceneRefUrl = shotNode.data.selectedSceneRefUrl || mainSceneRef;
                if (sceneRefUrl) {
                  referenceImageUrls.push(sceneRefUrl);
                  const locationName = locData.name || shotData.location_name || '场景';
                  const isCustom = shotNode.data.selectedSceneRefUrl && shotNode.data.selectedSceneRefUrl !== mainSceneRef;
                  const angleSuffix = isCustom ? (shotNode.data.selectedSceneRefLabel || '已选角度') : '';
                  promptSuffix.push(`图${imageIndex}是${locationName}${angleSuffix ? '(' + angleSuffix + ')' : ''}`);
                  imageIndex++;
                  console.log(`[宫格生图] 收集场景参考图URL: ${locationName}${isCustom ? '(已选特定角度)' : '(主图)'}`);
                }
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
                  headers: getAuthHeaders()
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
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="4" y="6" width="16" height="12" rx="2"/><path d="M10 9.5V14.5L14.5 12L10 9.5Z" fill="currentColor"/></svg>${node.title}</div>
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
          showToast(window.t ? window.t('uploading_video') : '正在上传视频...', 'info');
          const permanentUrl = await uploadFile(file);
          if(permanentUrl){
            // 更新为服务器URL
            node.data.url = permanentUrl;
            thumbVideo.src = proxyDownloadUrl(permanentUrl);
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
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>${node.title}</div>
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
      videoModalPlayer.src = proxyDownloadUrl(src);
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
      shotGroupModalTitle.textContent = `幕详情 - ${shotGroupData.groupName || '未命名'}`;
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
            <label style="display: block; font-weight: 600; margin-bottom: 6px; font-size: 13px;">幕ID</label>
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
        showToast(window.t ? window.t('props_selector_not_init') : '道具选择功能未初始化', 'error');
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
      
      showToast(window.t ? window.t('prop_removed') : '已移除道具', 'success');
    }

    function addNewShot(insertIndex){
      const node = state.nodes.find(n => n.id === currentEditingNodeId);
      if(!node) return;

      if(!Array.isArray(node.data.shots)) node.data.shots = [];
      
      const idx = (typeof insertIndex === 'number' && !Number.isNaN(insertIndex))
        ? Math.max(0, Math.min(insertIndex, node.data.shots.length))
        : node.data.shots.length;

      // 选择参考分镜：优先取插入位置的上一个，否则取下一个（使"插到最前"也能继承共性字段）
      const refShot = node.data.shots[idx - 1] || node.data.shots[idx] || {};

      // 生成简短且唯一的 shot_id：基于插入位置的前一个分镜
      // 规则：在分镜 N 后插入 → N_1；再在 N_x 后插入 → N_{最大x+1}
      // 前一个是基础分镜 → base 用其 shot_number；前一个是 N_M 插入分镜 → base = N
      const prevShotForId = node.data.shots[idx - 1];
      let base;
      if(prevShotForId){
        const prevId = String(prevShotForId.shot_id || '');
        const insertMatch = prevId.match(/^(\d+)_\d+$/);
        base = insertMatch ? insertMatch[1] : String(prevShotForId.shot_number || idx);
      } else {
        base = '0';  // 插在最前（无前一个分镜），用虚拟前缀 0
      }
      const idPrefix = base + '_';
      let maxSub = 0;
      node.data.shots.forEach(s => {
        const sid = String(s.shot_id || '');
        if(sid.startsWith(idPrefix)){
          const tail = sid.slice(idPrefix.length);
          if(/^\d+$/.test(tail)){
            const x = parseInt(tail, 10);
            if(x > maxSub) maxSub = x;
          }
        }
      });
      const newShotId = `${base}_${maxSub + 1}`;

      const newShot = {
        shot_id: newShotId,
        shot_number: idx + 1,
        // 共性字段从相邻分镜继承（同一分镜组通常一致），无参考时用默认值
        duration: refShot.duration || 5.0,
        location_id: refShot.location_id || '',
        db_location_id: refShot.db_location_id || '',
        db_location_pic: refShot.db_location_pic || '',
        location_name: refShot.location_name || '',
        time_of_day: refShot.time_of_day || '',
        weather: refShot.weather || '',
        mood: refShot.mood || '',
        environment_sound: refShot.environment_sound || '',
        background_music: refShot.background_music || '',
        shot_type: refShot.shot_type || '中景',
        camera_movement: refShot.camera_movement || '固定',
        // 以下为每个分镜独有内容，留空由用户填写差异
        description: '',
        opening_frame_description: '',
        scene_detail: '',
        action: '',
        audio_notes: '',
        characters_present: [],
        dialogue: null,
        props: []
      };

      node.data.shots.splice(idx, 0, newShot);
      // 不再 renumberShots：它会把整组 shot_number 重排为 1,2,3...，破坏 LLM 生成的全局编号（如 5,6,7），
      // 导致标题显示错误。新分镜的标题用 shot_id（N_x），LLM 分镜的标题用其原始 shot_number，数组顺序即显示顺序。
      shotGroupEditModalContent.innerHTML = renderShotGroupEditForm(node.data);
      bindShotEditEvents();
    }

    function deleteShot(index){
      const node = state.nodes.find(n => n.id === currentEditingNodeId);
      if(!node) return;

      node.data.shots.splice(index, 1);
      // 不再 renumberShots：保留 LLM 生成的原始 shot_number（见 addNewShot 注释）
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
            ...getAuthHeaders()
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
        showToast(window.t ? window.t('load_world_list_failed') : '加载世界列表失败', 'error');
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
            ...getAuthHeaders()
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

      showToast(window.t ? window.t('location_set_success') : '场景设置成功', 'success');
      safeAutoSave()
    }
    
    // 将 selectLocation 暴露到全局作用域
    window.selectLocation = selectLocation;

    function saveShotGroupEdit(){
      const node = state.nodes.find(n => n.id === currentEditingNodeId);
      if(!node) return;

      const groupId = document.getElementById('editGroupId').value.trim();

      node.data.groupId = groupId;
      node.data.group_id = groupId;
      node.title = groupId || '幕';

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

      // 提醒用户点击"生成分镜"按钮，把新增/修改的分镜同步到画布（按钮闪烁 3 次后自动恢复）
      // 注意：必须在 closeShotGroupEditModal() 之前查询按钮——后者会把 currentEditingNodeId 置空
      const genBtn = canvasEl.querySelector(`.node[data-node-id="${currentEditingNodeId}"] .shot-group-generate-btn`);
      if(genBtn){
        genBtn.classList.remove('flashing');
        void genBtn.offsetWidth;  // 强制 reflow，重启动画
        genBtn.classList.add('flashing');
        genBtn.addEventListener('animationend', () => {
          genBtn.classList.remove('flashing');
        }, { once: true });
      }

      closeShotGroupEditModal();
      safeAutoSave();
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

      // 局部更新：只刷新分镜列表与计数，保留 createShotGroupNode 的原始 DOM 结构（.script-node-body 横向3列布局）、事件与 select 状态。
      // 不再重写整个 node-body（旧逻辑会丢失 .script-node-body，导致分镜组形状从横向坍塌为纵向）。
      const shotsListEl = el.querySelector('.shot-group-shots-list');
      if(shotsListEl){
        shotsListEl.innerHTML = shotsHtml || '<div class="shot-group-empty">暂无分镜</div>';
      }
      const shotCountEl = el.querySelector('.shot-group-shot-count');
      if(shotCountEl){
        const countText = window.t ? window.t('shot_group_shot_count', { count: node.data.shots.length }) : `共 ${node.data.shots.length} 个分镜`;
        shotCountEl.textContent = countText;
        shotCountEl.setAttribute('data-i18n-params', JSON.stringify({ count: node.data.shots.length }));
      }
      return;
      // 以下旧的全量重建逻辑已由上方局部更新取代（不会执行），保留备查。
      const nodeBody = el.querySelector('.node-body');
      if(nodeBody){
        nodeBody.innerHTML = `
          <div class="field field-always-visible">
            <div class="label">幕: ${escapeHtml(node.data.groupId || node.data.group_id)}</div>
            <div class="gen-meta">共 ${node.data.shots.length} 个分镜</div>
          </div>
          <div class="field field-always-visible" style="max-height: 300px; overflow-y: auto;">
            ${shotsHtml || '<div class="shot-group-empty">暂无分镜</div>'}
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
            <select class="shot-group-model"></select>
          </div>
          <div class="field field-collapsible btn-row">
            <button class="mini-btn secondary shot-group-detail-btn" type="button" style="flex: 1;">查看/编辑</button>
            <button class="mini-btn gen-btn-white shot-group-generate-btn" type="button">生成分镜</button>
          </div>
          <hr style="margin: 12px 0; border: none; border-top: 1px solid #e5e7eb;">
          <div class="field field-collapsible">
            <div class="label">宫格生图模型</div>
            <select class="shot-group-grid-model" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;"></select>
          </div>
          <div class="field field-collapsible">
            <div class="label">宫格类型</div>
            <select class="shot-group-grid-layout" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
              <option value="auto">自动选择</option>
              <option value="4">4宫格 (2x2)</option>
              <option value="9">9宫格 (3x3)</option>
            </select>
          </div>
          <div class="field field-collapsible btn-row">
            <button class="mini-btn gen-btn-green shot-group-grid-btn" type="button" style="width: 100%;">宫格生图</button>
          </div>
          <div class="gen-meta shot-group-grid-status" style="display:none; margin-top: 8px;"></div>
          <hr style="margin: 12px 0; border: none; border-top: 1px solid #e5e7eb;">
          <div class="field field-collapsible">
            <div class="label">视频模型</div>
            <select class="shot-group-video-model"></select>
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
                <button class="gen-btn gen-btn-caret shot-group-video-caret" type="button" aria-label="${window.t ? window.t('draw_count_menu') : '选择抽卡次数'}">▾</button>
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
        `;

        // 动态填充分镜模型选项
        const shotGroupModelEl = nodeBody.querySelector('.shot-group-model');
        let firstModelValue = 'gpt-image-2';
        if(shotGroupModelEl) {
          if(window.TaskConfig && window.TaskConfig.isLoaded()) {
            const options = window.TaskConfig.getModelOptionsForCategory('image_edit');
            const gptImage2 = options.find(o => o.value === 'gpt-image-2');
            if(gptImage2) {
              firstModelValue = gptImage2.value;
            } else if(options.length > 0) {
              firstModelValue = options[0].value;
            }
            options.forEach(opt => {
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
          // 如果没有设置默认值，使用后端配置的第一个选项
          if(!node.data.model) {
            node.data.model = firstModelValue;
            shotGroupModelEl.value = firstModelValue;
          }
          // 确保已保存的模型值在下拉框中可见（防止TaskConfig未加载时硬编码选项不包含已保存值）
          ensureSelectHasSavedOption(shotGroupModelEl, node.data.model);
        }

        const newDetailBtn = nodeBody.querySelector('.shot-group-detail-btn');
        const newGenerateBtn = nodeBody.querySelector('.shot-group-generate-btn');
        const newModelSelect = nodeBody.querySelector('.shot-group-model');
        
        // 应用驱动状态禁用未配置的分镜模型选项
        if(newModelSelect) applyDriverStatusToSelect(newModelSelect);

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

        // 宫格生图按钮和模型选择器
        const shotGroupGridModelEl = nodeBody.querySelector('.shot-group-grid-model');
        if(shotGroupGridModelEl) {
          node.data.gridModel = populateGridImageModelSelect(shotGroupGridModelEl, node.data.gridModel);
          // 应用驱动状态禁用未配置的宫格生图模型选项
          applyDriverStatusToSelect(shotGroupGridModelEl);
          shotGroupGridModelEl.addEventListener('change', () => {
            node.data.gridModel = shotGroupGridModelEl.value;
          });
        }

        // 宫格类型选择器
        const shotGroupGridLayoutEl = nodeBody.querySelector('.shot-group-grid-layout');
        if(shotGroupGridLayoutEl) {
          if(!node.data.gridLayout){
            node.data.gridLayout = 'auto';
          }
          shotGroupGridLayoutEl.value = node.data.gridLayout;
          shotGroupGridLayoutEl.addEventListener('change', () => {
            node.data.gridLayout = shotGroupGridLayoutEl.value;
          });
        }

        // 视频模型选择器和相关元素（根据当前视频生成模式过滤）
        const shotGroupVideoModelEl = nodeBody.querySelector('.shot-group-video-model');
        const shotGroupVideoGenMode = nodeBody.querySelector('.shot-group-video-gen-mode');
        if(shotGroupVideoModelEl) {
          const mode = node.data.videoGenMode || 'first_last_frame';
          if(window.TaskConfig && window.TaskConfig.isLoaded()) {
            const allOptions = window.TaskConfig.getModelOptionsForCategory('image_to_video');
            const options = allOptions.filter(opt => {
              const modes = opt.supportedImageModes || ['first_last_frame'];
              return modes.includes(mode);
            });
            options.forEach(opt => {
              const optEl = document.createElement('option');
              optEl.value = opt.value;
              optEl.textContent = opt.label;
              if(opt.value === node.data.videoModel) optEl.selected = true;
              shotGroupVideoModelEl.appendChild(optEl);
            });
          } else {
            shotGroupVideoModelEl.innerHTML = `
              <option value="wan22" ${node.data.videoModel === 'wan22' ? 'selected' : ''}>Wan2.2</option>
              <option value="sora2" ${node.data.videoModel === 'sora2' ? 'selected' : ''}>Sora2</option>
              <option value="ltx2" ${node.data.videoModel === 'ltx2' ? 'selected' : ''}>LTX2.0</option>
              <option value="kling" ${node.data.videoModel === 'kling' ? 'selected' : ''}>可灵</option>
              <option value="vidu" ${node.data.videoModel === 'vidu' ? 'selected' : ''}>Vidu</option>
              <option value="veo3" ${node.data.videoModel === 'veo3' ? 'selected' : ''}>VEO3.1</option>
            `;
          }
          if(!node.data.videoModel) node.data.videoModel = shotGroupVideoModelEl.value;
          // 确保已保存的视频模型值在下拉框中可见
          ensureSelectHasSavedOption(shotGroupVideoModelEl, node.data.videoModel);
          // 应用驱动状态禁用未配置的视频模型选项
          applyDriverStatusToSelect(shotGroupVideoModelEl);
        }

        const shotGroupGridBtn = nodeBody.querySelector('.shot-group-grid-btn');
        const shotGroupGenerateVideoBtn = nodeBody.querySelector('.shot-group-generate-video-btn');
        const shotGroupVideoCaret = nodeBody.querySelector('.shot-group-video-caret');
        const shotGroupVideoMenu = nodeBody.querySelector('.shot-group-video-menu');
        const shotGroupVideoDuration = nodeBody.querySelector('.shot-group-video-duration');
        const shotGroupDrawCountLabel = nodeBody.querySelector('.shot-group-video-draw-count-label');
        const shotGroupComputingPowerValue = nodeBody.querySelector('.shot-group-computing-power-value');
        const shotGroupComputingPowerDetail = nodeBody.querySelector('.shot-group-computing-power-detail');
        const shotGroupGridStatus = nodeBody.querySelector('.shot-group-grid-status');

        // 计算视频生成算力消耗的本地函数
        function calculateVideoComputingPower() {
          // 检查 TaskConfig 是否已加载
          if(!window.TaskConfig || !window.TaskConfig.isLoaded()) {
            return 0;
          }

          const videoModel = node.data.videoModel || 'wan22';
          const duration = node.data.videoDuration || 5;

          // 使用 TaskConfig API 动态获取算力（自动支持所有模型）
          return TaskConfig.getComputingPower(videoModel, duration);
        }

        // 更新视频算力显示的本地函数
        function updateVideoComputingPowerDisplay() {
          const singlePower = calculateVideoComputingPower();
          const count = node.data.videoDrawCount || 1;
          const totalPower = singlePower * count;

          if(shotGroupComputingPowerValue) {
            const displayPower = typeof totalPower === 'number' ? totalPower : 0;
            shotGroupComputingPowerValue.textContent = window.t ? window.t('shot_group_computing_power_value', { power: displayPower }) : `${displayPower} 算力`;
            shotGroupComputingPowerValue.setAttribute('data-i18n-params', JSON.stringify({ power: displayPower }));
          }
          if(shotGroupComputingPowerDetail) {
            const displaySingle = typeof singlePower === 'number' ? singlePower : 0;
            const displayCount = typeof count === 'number' ? count : 1;
            const displayTotal = typeof totalPower === 'number' ? totalPower : 0;
            shotGroupComputingPowerDetail.textContent = window.t ? window.t('shot_group_computing_power_detail', { individual: displaySingle, count: displayCount, total: displayTotal }) : `单个 ${displaySingle} 算力 × ${displayCount} 个 = ${displayTotal} 算力`;
            shotGroupComputingPowerDetail.setAttribute('data-i18n-params', JSON.stringify({ individual: displaySingle, count: displayCount, total: displayTotal }));
          }
        }

        // 视频时长选择
        if(shotGroupVideoDuration) {
          shotGroupVideoDuration.value = node.data.videoDuration || '5';
          shotGroupVideoDuration.addEventListener('change', () => {
            node.data.videoDuration = Number(shotGroupVideoDuration.value);
            updateVideoComputingPowerDisplay();
          });
        }

        // 抽卡次数菜单
        let videoDrawCount = node.data.videoDrawCount || 1;
        if(shotGroupGenerateVideoBtn) {
          if(shotGroupDrawCountLabel) shotGroupDrawCountLabel.textContent = window.t ? window.t('draw_count_simple', { count: videoDrawCount }) : `抽卡次数: ${videoDrawCount}`;
          updateVideoComputingPowerDisplay();
          shotGroupGenerateVideoBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            generateShotGroupVideo(nodeId, node);
          });
        }

        if(shotGroupVideoCaret && shotGroupVideoMenu) {
          shotGroupVideoCaret.addEventListener('click', (e) => {
            e.stopPropagation();
            shotGroupVideoMenu.style.display = shotGroupVideoMenu.style.display === 'block' ? 'none' : 'block';
          });
          const menuItems = shotGroupVideoMenu.querySelectorAll('.gen-item');
          menuItems.forEach(item => {
            item.addEventListener('click', (e) => {
              e.stopPropagation();
              videoDrawCount = parseInt(item.dataset.count);
              node.data.videoDrawCount = videoDrawCount;
              if(shotGroupDrawCountLabel) shotGroupDrawCountLabel.textContent = window.t ? window.t('draw_count_simple', { count: videoDrawCount }) : `抽卡次数: ${videoDrawCount}`;
              updateVideoComputingPowerDisplay();
              shotGroupVideoMenu.style.display = 'none';
            });
          });
        }

        // 宫格生图按钮点击事件
        if(shotGroupGridBtn) {
          shotGroupGridBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            generateShotGroupGridImages(nodeId, node, shotGroupGridStatus);
          });
        }

        // 初始化宫格预览
        if(el.querySelector('.shot-grid-preview-container')) {
          updateGridPreviewUI(el, node);
        }
      }

      const titleEl = el.querySelector('.node-title');
      if(titleEl){
        titleEl.setAttribute('data-i18n-params', JSON.stringify({ title: escapeHtml(node.title) }));
        if(window.ZJTi18nDOM) window.ZJTi18nDOM.scanDOM(titleEl);
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
        showToast(window.t ? window.t('props_selector_not_init') : '道具选择功能未初始化', 'error');
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
      
      safeAutoSave()
      showToast(window.t ? window.t('prop_removed') : '已删除道具', 'success');
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
        showToast(window.t ? window.t('props_selector_not_init') : '道具选择功能未初始化', 'error');
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
      
      safeAutoSave()
      showToast(window.t ? window.t('prop_removed') : '已移除道具', 'success');
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
        showToast(window.t ? window.t('prop_already_added') : '该道具已添加', 'warning');
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
      
      safeAutoSave()
      showToast(window.t ? window.t('prop_added') : '已添加道具', 'success');
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

    function pickFirstDefinedValue(...values){
      return values.find(value => value !== undefined && value !== null && value !== '');
    }

    function getVideoModelFromData(data){
      if(!data) return undefined;
      return pickFirstDefinedValue(data.videoModel, data.video_model, data.video_model_key, data.videoModelKey);
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
      renderAllConnections();
      renderReferenceConnections();
      
      // 如果删除的连接涉及分镜节点，更新其预览图和选择菜单
      if(conn){
        const fromNode = state.nodes.find(n => n.id === conn.from);
        const toNode = state.nodes.find(n => n.id === conn.to);
        
        // 如果删除的连接涉及角色节点，更新角色卡按钮状态
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

      // 只清除普通连接线，保留其他类型的连接线（视频、音频、参考图等）
      const oldNormalLines = connectionsSvg.querySelectorAll('path.hitbox, path.line, path.temp');
      oldNormalLines.forEach(l => l.remove());

      let pathsHtml = '';
      for(const conn of state.connections){
        const from = getOutputPortPos(conn.from);
        const to = getInputPortPos(conn.to);
        const dx = Math.abs(to.x - from.x) * 0.5;
        const pathD = `M${from.x},${from.y} C${from.x+dx},${from.y} ${to.x-dx},${to.y} ${to.x},${to.y}`;
        //console.log(`[renderConnections] 连接 ${conn.id}: from=(${from.x},${from.y}) to=(${to.x},${to.y}) path=${pathD}`);
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

      // 使用临时SVG元素解析，确保path元素在SVG命名空间下（div元素会在HTML命名空间解析，导致不渲染）
      if(pathsHtml){
        const tempSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        tempSvg.innerHTML = pathsHtml;
        while(tempSvg.firstChild){
          connectionsSvg.appendChild(tempSvg.firstChild);
        }
      }

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
        // 根据 portType 选择不同的目标端口
        let imagePort = null;
        if(conn.portType === 'extracted'){
          // extracted 类型连接到图片节点的 input 端口
          imagePort = toEl.querySelector('.port.input');
        } else if(conn.portType === 'ref-image'){
          // 参考图连接到图生视频节点的 ref-image-input-port
          imagePort = toEl.querySelector('.ref-image-input-port');
        } else {
          // 其他类型使用特定端口（start-image-port / end-image-port）
          imagePort = toEl.querySelector(`.${conn.portType}-image-port`);
        }
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

        // 保存连接ID到元素上，避免闭包问题
        const connId = conn.id;

        // 点击选中
        hitbox.addEventListener('click', (e) => {
          e.stopPropagation();
          state.selectedConnId = null;
          state.selectedImgConnId = connId;  // 使用保存的connId
          renderAllConnections();
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

      // 如果没有连接被选中，隐藏删除按钮
      if(state.selectedImgConnId === null) {
        connDeleteBtn.style.display = 'none';
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
        const videoInputPort = toEl.querySelector('.port.video-ref-input-port');
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
          renderAllConnections();
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

    // ===== 渲染音频连接线 =====
    function renderAudioConnections(){
      try {
        if(!connectionsSvg || !canvasEl || !canvasContainer) return;
        if(!state.audioConnections) state.audioConnections = [];

        const oldLines = document.querySelectorAll('.audio-conn-group');
        oldLines.forEach(l => l.remove());

        if(state.selectedAudioConnId !== null){
          const stillExists = state.audioConnections.some(c => c.id === state.selectedAudioConnId);
          if(!stillExists){
            state.selectedAudioConnId = null;
            if(connDeleteBtn) connDeleteBtn.style.display = 'none';
          }
        }

        for(const conn of state.audioConnections){
          const fromEl = canvasEl.querySelector(`.node[data-node-id="${conn.from}"]`);
          const toEl = canvasEl.querySelector(`.node[data-node-id="${conn.to}"]`);
          if(!fromEl || !toEl) continue;

          const outputPort = fromEl.querySelector('.port.output');
          const audioInputPort = toEl.querySelector('.port.audio-input-port');
          if(!outputPort || !audioInputPort) continue;

          const fromRect = outputPort.getBoundingClientRect();
          const toRect = audioInputPort.getBoundingClientRect();
          const containerRect = canvasContainer.getBoundingClientRect();

          const fromX = (fromRect.left + fromRect.width/2 - containerRect.left - state.panX) / state.zoom;
          const fromY = (fromRect.top + fromRect.height/2 - containerRect.top - state.panY) / state.zoom;
          const toX = (toRect.left + toRect.width/2 - containerRect.left - state.panX) / state.zoom;
          const toY = (toRect.top + toRect.height/2 - containerRect.top - state.panY) / state.zoom;

          const dx = Math.abs(toX - fromX) * 0.5;
          const pathD = `M${fromX},${fromY} C${fromX+dx},${fromY} ${toX-dx},${toY} ${toX},${toY}`;

          const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
          group.setAttribute('class', 'audio-conn-group');
          group.dataset.audioConnId = String(conn.id);

          const hitbox = document.createElementNS('http://www.w3.org/2000/svg', 'path');
          hitbox.setAttribute('d', pathD);
          hitbox.setAttribute('class', 'hitbox');
          hitbox.style.fill = 'none';
          hitbox.style.stroke = 'transparent';
          hitbox.style.strokeWidth = '20';
          hitbox.style.cursor = 'pointer';

          const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
          path.setAttribute('d', pathD);
          path.setAttribute('class', 'visible');
          path.style.fill = 'none';
          path.style.stroke = '#8b5cf6';
          path.style.strokeWidth = '2';
          path.style.strokeDasharray = '6,3';
          path.style.pointerEvents = 'none';

          if(state.selectedAudioConnId === conn.id){
            path.style.stroke = '#6d28d9';
            path.style.strokeWidth = '3';
            path.style.strokeDasharray = 'none';
          }

          group.appendChild(hitbox);
          group.appendChild(path);
          connectionsSvg.appendChild(group);

          hitbox.addEventListener('click', (e) => {
            e.stopPropagation();
            state.selectedConnId = null;
            state.selectedImgConnId = null;
            state.selectedFirstFrameConnId = null;
            state.selectedVideoConnId = null;
            state.selectedReferenceConnId = null;
            state.selectedAudioConnId = conn.id;
            renderAllConnections();
          });

          if(state.selectedAudioConnId === conn.id){
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
            if(connDeleteBtn){
              connDeleteBtn.style.display = 'flex';
              connDeleteBtn.style.left = (screenX - 12) + 'px';
              connDeleteBtn.style.top = (screenY - 12) + 'px';
            }
          }
        }
      } catch(error) {
        console.error('[renderAudioConnections] Error:', error);
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
          renderAllConnections();
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
          renderAllConnections();
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
          drawCount: opts?.data?.drawCount || 1,
          motionEnabled: opts?.data?.motionEnabled || false,
          motion: opts?.data?.motion || '',
          imageMode: opts?.data?.imageMode || 'first_last_frame',  // first_last_frame | multi_reference
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
          const options = window.TaskConfig.getModelOptionsForCategory(category);
          let firstAvailable = null;

          options.forEach(opt => {
            const optEl = document.createElement('option');
            optEl.value = opt.value;

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
        } else {
          // 回退：硬编码选项
          const fallbackOptions = [
            { value: 'wan22', label: 'Wan2.2' },
            { value: 'sora2', label: 'Sora2' },
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
            <img src="${url}" style="width: 100%; height: 100%; object-fit: cover; border-radius: 4px; cursor: pointer;" />
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
          el.innerHTML = `<span class="media-name" title="${item.name}">🎵 音频${idx + 1}</span><span class="remove-btn">×</span>`;
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
          el.innerHTML = `<span class="media-name" title="${item.name}">🎬 ${window.t ? window.t('video') : '视频'}${idx + 1}</span><span class="remove-btn">×</span>`;
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
      
      videoModelSelect.value = node.data.videoModel;
      // 应用驱动状态禁用未配置的选项
      applyDriverStatusToSelect(videoModelSelect);
      // 初始化时根据模型设置时长和比例选项
      updateDurationOptions(node.data.videoModel);
      updateRatioOptions(node.data.videoModel);
      
      videoModelSelect.addEventListener('change', () => {
        node.data.videoModel = videoModelSelect.value;
        // 模型改变时更新时长和比例选项
        updateDurationOptions(videoModelSelect.value);
        updateRatioOptions(videoModelSelect.value);
        // 更新图片模式UI（如尾帧是否支持）
        updateImageModeUI();
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
            result = await generateVideoFromText(prompt, duration, desiredCount, ratio, videoModel);
          } else {
            result = await generateVideoFromImage(imageUrls, prompt, duration, desiredCount, ratio, videoModel, currentImageMode, referenceImages, allAudioUrls.join(','), allVideoUrls.join(','), JSON.stringify(mediaReferences));
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
                      setupVideoThumbnail(thumbVideo, videoUrl);
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
          const thumbHtml = isImage && item.url ? `<img src="${item.url}" class="mention-thumb" style="width:32px;height:32px;object-fit:cover;border-radius:4px;margin-right:8px;flex-shrink:0;" />` : '';
          return `<div class="mention-dropdown-item${i === mentionState.selectedIndex ? ' selected' : ''}" data-index="${i}" style="display:flex;align-items:center;padding:6px 10px;cursor:pointer;">` +
            thumbHtml +
            `<span class="mention-icon" style="margin-right:6px;">${typeIcons[item.type] || '📄'}</span>` +
            `<span class="mention-name" style="flex:1;">${item.displayName}</span>` +
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
          <div class="field field-collapsible">
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
            optEl.textContent = opt.label;
            modelEl.appendChild(optEl);
          });
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
        
        const labelMap = {
          '9:16': '竖屏 (9:16)',
          '16:9': '横屏 (16:9)',
          '1:1': '正方形 (1:1)',
          '3:4': '竖屏 (3:4)',
          '4:3': '横屏 (4:3)',
          '2:3': '竖屏 (2:3)',
          '3:2': '横屏 (3:2)'
        };
        
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

      // 涂色编辑按钮
      if(coloringBtn){
        coloringBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          if(!node.data.url && !node.data.preview){
            showToast(window.t ? window.t('upload_or_generate_image_first') : '请先上传或生成图片', 'error');
            return;
          }
          const imageUrl = node.data.url || node.data.preview;

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
        node.data.file = file;

        const localPreview = await readFileAsDataUrl(file);
        imagePreviewImg.src = localPreview;
        imagePreviewRow.style.display = 'flex';

        const previousUrl = node.data.url;
        const uploadedUrl = await uploadFile(file);
        if(uploadedUrl){
          node.data.url = uploadedUrl;
          node.data.name = file.name;
          node.data.preview = uploadedUrl;
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

          showToast('图片上传成功', 'success');
          safeAutoSave()
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
          setStatusEl(statusEl, '请先上传图片', '#dc2626');
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
          let submitData = node.data.file;
          if(!submitData && node.data.url){
            submitData = node.data.url;
          }

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

    // 剧本节点
    function createScriptNode(opts){
      const id = state.nextNodeId++;
      const scriptId = (opts && typeof opts.scriptId === 'number') ? opts.scriptId : state.nextScriptId++;
      if(opts && typeof opts.scriptId === 'number' && opts.scriptId >= state.nextScriptId) {
        state.nextScriptId = opts.scriptId + 1;
      }
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = Math.max(MIN_NODE_Y, opts && typeof opts.y === 'number' ? opts.y : viewportPos.y);
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
        <div class="port output" title="${window.t ? window.t('script_output_port') : '输出（拆分为幕）'}"></div>
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M9 5H7C5.89543 5 5 5.89543 5 7V19C5 20.1046 5.89543 21 7 21H17C18.1046 21 19 20.1046 19 19V7C19 5.89543 18.1046 5 17 5H15"/><rect x="9" y="3" width="6" height="4" rx="1"/></svg>剧本 ${scriptId}</div>
          <button class="icon-btn" title="${window.t ? window.t('node_delete_btn') : '删除'}">×</button>
        </div>
        <div class="node-body script-node-body">
          <!-- 第1部分：剧本内容 -->
          <div class="script-section">
            <div class="script-section-header">
              <span class="script-section-number">1</span>
              <span class="script-section-title" data-i18n="script_section_1">${window.t ? window.t('script_section_1') : '剧本内容'}</span>
            </div>
            <div class="field field-always-visible script-info-field" style="display:none;">
              <div class="gen-meta script-name"></div>
              <div class="gen-meta script-length"></div>
            </div>
            <div class="field field-always-visible">
              <div style="display: flex; justify-content: flex-end; align-items: center; gap: 6px; margin-bottom: 4px;">
                <span class="script-char-count" style="color: #666; font-size: 12px;">0/30000</span>
                <button class="mini-btn script-expand-btn" type="button" style="font-size: 11px; padding: 4px 8px;" title="${window.t ? window.t('script_expand_btn') : '放大编辑'}" data-i18n="script_expand_btn:title">⤢</button>
              </div>
              <textarea class="script-textarea" rows="16" maxlength="30000" placeholder="${window.t ? window.t('script_placeholder') : '在此输入剧本内容，或上传文件（最多30000字符）'}" data-i18n="script_placeholder:placeholder"></textarea>
            </div>
            <div class="field field-always-visible" style="margin-top: auto; padding-top: 8px;">
              <div style="display: flex; gap: 6px;">
                <button class="gen-btn gen-btn-white script-upload-btn" type="button" style="border-radius: 8px; flex: 1; padding: 7px 0; font-size: 12px;" data-i18n="script_upload_btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>${window.t ? window.t('script_upload_btn') : '上传'}</button>
                <button class="gen-btn gen-btn-green script-load-btn" type="button" style="border-radius: 8px; flex: 1; padding: 7px 0; font-size: 12px;" data-i18n="script_load_btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>${window.t ? window.t('script_load_btn') : '加载'}</button>
              </div>
              <input class="script-file" type="file" accept=".txt,.md" style="display:none;" />
            </div>
            <div class="field field-always-visible script-warning-field" style="display:none;">
              <div class="gen-meta" style="color: #f59e0b;" data-i18n="script_file_truncated">${window.t ? window.t('script_file_truncated') : '文件内容超过30000字符，已自动截取前30000字符。建议将剧本分段处理。'}</div>
            </div>
          </div>

          <!-- 第2部分：参数配置 -->
          <div class="script-section">
            <div class="script-section-header">
              <span class="script-section-number">2</span>
              <span class="script-section-title" data-i18n="script_section_2">${window.t ? window.t('script_section_2') : '参数配置'}</span>
            </div>
            <div class="field field-always-visible">
              <div class="label" data-i18n="script_duration_label">${window.t ? window.t('script_duration_label') : '镜头组时长'}</div>
              <select class="script-duration-select" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
                <option value="5" data-i18n="duration_5s">${window.t ? window.t('duration_5s') : '5秒'}</option>
                <option value="8" data-i18n="duration_8s">${window.t ? window.t('duration_8s') : '8秒'}</option>
                <option value="10" data-i18n="duration_10s">${window.t ? window.t('duration_10s') : '10秒'}</option>
                <option value="15" selected data-i18n="duration_15s">${window.t ? window.t('duration_15s') : '15秒'}</option>
              </select>
            </div>
            <div class="field field-always-visible">
              <div class="label" data-i18n="script_grid_model_label">${window.t ? window.t('script_grid_model_label') : '宫格生图模型'}</div>
              <select class="script-grid-model" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;"></select>
            </div>
            <div class="field field-always-visible">
              <div class="label" data-i18n="script_grid_layout_label">${window.t ? window.t('script_grid_layout_label') : '宫格类型'}</div>
              <select class="script-grid-layout" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
                <option value="auto" data-i18n="script_grid_layout_auto">${window.t ? window.t('script_grid_layout_auto') : '自动选择'}</option>
                <option value="4" data-i18n="script_grid_layout_4">${window.t ? window.t('script_grid_layout_4') : '4宫格 (2x2)'}</option>
                <option value="9" data-i18n="script_grid_layout_9">${window.t ? window.t('script_grid_layout_9') : '9宫格 (3x3)'}</option>
              </select>
            </div>
            <div class="field field-always-visible">
              <div class="label" data-i18n="script_split_model_label">${window.t ? window.t('script_split_model_label') : '拆分模型'}</div>
              <select class="script-split-model" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
                <option value="" data-i18n="script_loading">${window.t ? window.t('script_loading') : '加载中...'}</option>
              </select>
            </div>
            <div class="field field-always-visible">
              <div class="label" data-i18n="script_video_model_label">${window.t ? window.t('script_video_model_label') : '视频生成模型'}</div>
              <select class="script-video-model" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;"></select>
            </div>
            <div class="field field-always-visible">
              <div class="label" data-i18n="script_dialogue_language_label">${window.t ? window.t('script_dialogue_language_label') : '对话语言'}</div>
              <select class="script-dialogue-language" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
                <option value="" data-i18n="script_language_default">${window.t ? window.t('script_language_default') : '中文（默认）'}</option>
                <option value="English">English</option>
                <option value="Deutsch">Deutsch</option>
                <option value="Français">Français</option>
                <option value="Русский">Русский</option>
                <option value="__custom__" data-i18n="script_language_custom">${window.t ? window.t('script_language_custom') : '自定义语言...'}</option>
              </select>
              <input type="text" class="script-dialogue-language-custom" placeholder="${window.t ? window.t('script_language_custom') : '或输入自定义语言...'}" style="display: none; width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white; margin-top: 4px;" />
            </div>
            <div class="field field-always-visible">
              <div class="label" data-i18n="script_prompt_language_label">${window.t ? window.t('script_prompt_language_label') : '提示词语言'}</div>
              <select class="script-prompt-language" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white;">
                <option value="" data-i18n="script_language_default">${window.t ? window.t('script_language_default') : '中文（默认）'}</option>
                <option value="English">English</option>
                <option value="Deutsch">Deutsch</option>
                <option value="Français">Français</option>
                <option value="Русский">Русский</option>
                <option value="__custom__" data-i18n="script_language_custom">${window.t ? window.t('script_language_custom') : '自定义语言...'}</option>
              </select>
              <input type="text" class="script-prompt-language-custom" placeholder="${window.t ? window.t('script_language_custom') : '或输入自定义语言...'}" style="display: none; width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: white; margin-top: 4px;" />
            </div>
            <div class="script-checkbox-group">
              <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
                <input type="checkbox" class="script-force-medium-shot" style="cursor: pointer;" checked />
                <span data-i18n="script_force_medium_shot">${window.t ? window.t('script_force_medium_shot') : '对话禁止全景'}</span>
              </label>
              <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
                <input type="checkbox" class="script-no-bg-music" style="cursor: pointer;" checked />
                <span data-i18n="script_no_bg_music">${window.t ? window.t('script_no_bg_music') : '不生成背景音乐'}</span>
              </label>
              <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
                <input type="checkbox" class="script-split-multi-dialogue" style="cursor: pointer;" />
                <span data-i18n="script_split_multi_dialogue">${window.t ? window.t('script_split_multi_dialogue') : '拆分多人对话镜头'}</span>
              </label>
              <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
                <input type="checkbox" class="script-narration-as-dialogue" style="cursor: pointer;" />
                <span data-i18n="script_narration_as_dialogue">${window.t ? window.t('script_narration_as_dialogue') : '解说剧（仅旁白说话）'}</span>
              </label>
            </div>
          </div>

          <!-- 第3部分：执行操作 -->
          <div class="script-section script-section-actions">
            <div class="script-section-header">
              <span class="script-section-number">3</span>
              <span class="script-section-title" data-i18n="script_section_3">${window.t ? window.t('script_section_3') : '执行操作'}</span>
            </div>
            <div class="field field-always-visible">
              <div style="display: flex; gap: 6px;">
                <button class="gen-btn gen-btn-white script-split-btn" type="button" style="border-radius: 8px; flex: 1; padding: 18px 0;" disabled data-i18n="script_split_btn">${window.t ? window.t('script_split_btn') : '拆分幕'}</button>
                <button class="gen-btn gen-btn-white script-grid-only-btn" type="button" style="border-radius: 8px; flex: 1; padding: 18px 0;" data-i18n="script_grid_only_btn">${window.t ? window.t('script_grid_only_btn') : '宫格生图'}</button>
              </div>
              <div class="gen-meta script-status" style="display:none; margin-top: 6px;"></div>
              <div class="gen-meta script-grid-only-status" style="display:none; margin-top: 6px;"></div>
            </div>
            <div class="field field-always-visible">
              <button class="gen-btn gen-btn-green script-split-grid-btn" type="button" style="border-radius: 8px; width: 100%; padding: 18px 0;" data-i18n="script_split_grid_btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>${window.t ? window.t('script_split_grid_btn') : '拆分幕 + 宫格生图'}</button>
              <div class="gen-meta script-grid-status" style="display:none; margin-top: 6px;"></div>
            </div>
            <div class="field field-always-visible">
              <button class="gen-btn gen-btn-blue script-batch-generate-btn" type="button" style="border-radius: 8px; width: 100%; background: #3b82f6; color: white; padding: 18px 0;" data-i18n="script_batch_generate_btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><polygon points="5 3 19 12 5 21 5 3"/></svg>${window.t ? window.t('script_batch_generate_btn') : '逐个生成视频'}</button>
              <div class="gen-meta" style="margin-top: 4px; font-size: 11px; color: #666;" data-i18n="script_batch_info">${window.t ? window.t('script_batch_info') : '支持所有模型，逐个生成可能浪费时长'}</div>
              <div class="gen-meta script-batch-status" style="display:none; margin-top: 6px;"></div>
            </div>
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
      const dialogueLanguageSelectEl = el.querySelector('.script-dialogue-language');
      const dialogueLanguageCustomEl = el.querySelector('.script-dialogue-language-custom');
      const promptLanguageSelectEl = el.querySelector('.script-prompt-language');
      const promptLanguageCustomEl = el.querySelector('.script-prompt-language-custom');
      const infoField = el.querySelector('.script-info-field');
      const nameEl = el.querySelector('.script-name');
      const lengthEl = el.querySelector('.script-length');
      const splitBtn = el.querySelector('.script-split-btn');
      const statusEl = el.querySelector('.script-status');
      const charCountEl = el.querySelector('.script-char-count');
      const warningField = el.querySelector('.script-warning-field');
      const videoModelSelect = el.querySelector('.script-video-model');
      const gridModelSelect = el.querySelector('.script-grid-model');
      const splitGridBtn = el.querySelector('.script-split-grid-btn');
      const gridStatusEl = el.querySelector('.script-grid-status');
      const gridOnlyBtn = el.querySelector('.script-grid-only-btn');
      const gridOnlyStatusEl = el.querySelector('.script-grid-only-status');
      const batchGenerateBtn = el.querySelector('.script-batch-generate-btn');
      const batchStatusEl = el.querySelector('.script-batch-status');
      const uploadBtn = el.querySelector('.script-upload-btn');
      const splitModelSelect = el.querySelector('.script-split-model');

      // 上传按钮点击时触发隐藏的文件输入框
      if(uploadBtn && fileEl) {
        uploadBtn.addEventListener('click', () => fileEl.click());
      }

      // 动态填充视频模型选项
      function populateScriptVideoModelOptions() {
        if(!videoModelSelect) return;

        function renderOptions() {
          if(!videoModelSelect) return;
          videoModelSelect.innerHTML = '';

          // 从后端配置获取第一个视频模型作为默认值
          let firstVideoModelValue = 'wan22';
          if(window.TaskConfig && window.TaskConfig.isLoaded()) {
            // 使用 getAllTasks 获取完整任务数据（含 provider 字段）
            const allTasks = window.TaskConfig.getAllTasks();
            const tasks = allTasks.filter(t =>
              !t.hidden &&
              (t.category === 'image_to_video' || t.categories?.includes('image_to_video'))
            );

            // 从 providers 获取显示名称映射（动态来自后端，无硬编码）
            const providers = window.TaskConfig.getProviders() || {};
            const providerIcons = { duomi: '☁️', runninghub: '🚀', vidu: '🎬', volcengine: '🌋', local: '💻' };

            // 按 provider 分组
            const providerGroups = {};
            const providerOrder = [];

            tasks.forEach(task => {
              const provider = task.provider || 'unknown';
              if (!providerGroups[provider]) {
                providerGroups[provider] = [];
                providerOrder.push(provider);
              }
              providerGroups[provider].push(task);
            });

            // 按 provider 分组渲染
            providerOrder.forEach(provider => {
              const optGroup = document.createElement('optgroup');
              const icon = providerIcons[provider] || '📦';
              const providerName = providers[provider] || provider;
              optGroup.label = `${icon} ${providerName}`;

              providerGroups[provider].forEach(task => {
                const shortKey = task.short_key || task.key;
                const power = typeof task.computing_power === 'object'
                  ? Object.values(task.computing_power)[0]
                  : task.computing_power;
                const optEl = document.createElement('option');
                optEl.value = shortKey;
                optEl.textContent = `${task.name} (${power}算力)`;
                optGroup.appendChild(optEl);
              });

              videoModelSelect.appendChild(optGroup);
            });

            // 获取第一个可用值
            if(providerOrder.length > 0 && providerGroups[providerOrder[0]].length > 0) {
              const firstTask = providerGroups[providerOrder[0]][0];
              const shortKey = firstTask.short_key || firstTask.key;
              firstVideoModelValue = shortKey;
            }
          } else {
            // 回退：硬编码选项
            const fallbackOptions = [
              { value: 'wan22', label: 'Wan2.2' },
              { value: 'sora2', label: 'Sora2' },
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

          // 恢复之前的选择，默认使用后端配置的第一个模型（与分镜组节点和图生图片节点一致）
          const currentValue = node.data.videoModel || firstVideoModelValue;
          // 确保已保存的视频模型值在下拉框中可见（防止TaskConfig未加载时硬编码选项不包含已保存值）
          ensureSelectHasSavedOption(videoModelSelect, currentValue);
          const selectedOption = videoModelSelect.querySelector(`option[value="${currentValue}"]`);
          if(selectedOption) {
            videoModelSelect.value = currentValue;
          } else {
            videoModelSelect.value = firstVideoModelValue;
            node.data.videoModel = firstVideoModelValue;
          }
        }

        if(window.TaskConfig && window.TaskConfig.isLoaded()) {
          renderOptions();
        } else if(window.TaskConfig) {
          videoModelSelect.innerHTML = '<option value="">加载中...</option>';
          window.TaskConfig.onLoaded(() => {
            renderOptions();
          });
        } else {
          renderOptions();
        }
      }

      // 初始化视频模型
      populateScriptVideoModelOptions();
      
      // 视频模型切换事件
      if(videoModelSelect) {
        videoModelSelect.addEventListener('change', () => {
          node.data.videoModel = videoModelSelect.value;
          console.log(`[剧本节点] 视频模型切换为: ${videoModelSelect.value}`);
        });
      }

      // 拆分模型：加载可用模型列表
      async function populateScriptSplitModelOptions() {
        if(!splitModelSelect) return;

        // 如果已经加载过（全局缓存），直接使用
        if(window._scriptSplitModels && window._scriptSplitModels.length > 0) {
          renderSplitModelOptions(window._scriptSplitModels, window._vendorIcons);
          return;
        }

        try {
          // 加载供应商列表及图标
          const vendorResponse = await fetch('/api/vendors');
          const vendorData = await vendorResponse.json();
          const vendorIcons = {};
          if(vendorData.success && vendorData.vendors) {
            vendorData.vendors.forEach(v => {
              vendorIcons[v.vendor_name.toLowerCase()] = v.icon || '📦';
            });
          }
          window._vendorIcons = vendorIcons;

          const response = await fetch('/api/models', {
            headers: getAuthHeaders()
          });
          const data = await response.json();

          if(!data.success || !data.models || data.models.length === 0) {
            // 加载失败时使用默认模型
            if(splitModelSelect) {
              splitModelSelect.innerHTML = '<option value="gemini-3-flash-preview">Gemini 3 Flash (默认)</option>';
            }
            return;
          }

          // 按指定顺序排序：deepseek-v4 > qwen3.5 > qwen3.6 > flash-3.0 > flash-3.5 > flash > gemini-3-flash > gemini-3.1-flash-lite > 其他
          const sortOrder = ['deepseek-v4', 'qwen3.5', 'qwen3.6', 'flash-3.0', 'flash-3.5', 'flash', 'gemini-3-flash', 'gemini-3.1-flash-lite'];
          const sortedModels = [...data.models].sort((a, b) => {
            const nameA = (a.model_name || a.name || '').toLowerCase();
            const nameB = (b.model_name || b.name || '').toLowerCase();
            const indexA = sortOrder.findIndex(k => nameA.startsWith(k.toLowerCase()));
            const indexB = sortOrder.findIndex(k => nameB.startsWith(k.toLowerCase()));
            if (indexA !== -1 && indexB !== -1) return indexA - indexB;
            if (indexA !== -1) return -1;
            if (indexB !== -1) return 1;
            return 0;
          });

          // 缓存到全局变量
          window._scriptSplitModels = sortedModels;
          renderSplitModelOptions(sortedModels, vendorIcons);

        } catch (error) {
          console.error('加载拆分模型列表失败:', error);
          if(splitModelSelect) {
            splitModelSelect.innerHTML = '<option value="gemini-3-flash-preview">Gemini 3 Flash (默认)</option>';
          }
        }
      }

      function renderSplitModelOptions(models, vendorIcons = {}) {
        if(!splitModelSelect) return;
        splitModelSelect.innerHTML = '';

        // 按供应商分组
        const vendorGroups = {};
        const vendorOrder = [];
        models.forEach(model => {
          const vendorId = model.vendor_id || 1;
          const vendorName = model.vendor_name || 'unknown';
          if (!vendorGroups[vendorId]) {
            vendorGroups[vendorId] = {
              vendorName: vendorName,
              models: []
            };
            vendorOrder.push(vendorId);
          }
          vendorGroups[vendorId].models.push(model);
        });

        let firstEnabled = null;

        // 按供应商分组添加选项
        vendorOrder.forEach(vendorId => {
          const group = vendorGroups[vendorId];
          const optGroup = document.createElement('optgroup');
          const icon = vendorIcons[group.vendorName.toLowerCase()] || '📦';
          optGroup.label = `${icon} ${group.vendorName}`;

          group.models.forEach(model => {
            const option = document.createElement('option');
            const modelName = model.model_name || model.name || '';
            const modelDesc = model.note || model.description || '';
            option.value = modelName;
            option.textContent = modelDesc ? `${modelName} - ${modelDesc}` : modelName;

            // 保存模型和供应商信息到 dataset
            const modelId = model.id ?? model.model_id ?? '';
            if(modelId) {
              option.dataset.modelId = modelId;
            }
            option.dataset.vendorId = model.vendor_id || 1;
            option.dataset.vendorName = model.vendor_name || 'unknown';
            option.dataset.supportsThinking = model.supports_thinking ? 'true' : 'false';
            if(model.context_window) {
              option.dataset.contextWindow = model.context_window;
            }

            if(!option.disabled && !firstEnabled) {
              firstEnabled = option;
            }
            optGroup.appendChild(option);
          });

          splitModelSelect.appendChild(optGroup);
        });

        // 恢复已保存的拆分模型选择，若无保存值则按优先级选择默认模型
        const savedSplitModel = node.data.splitModel;
        let restored = false;
        if(savedSplitModel) {
          const savedOption = splitModelSelect.querySelector(`option[value="${savedSplitModel}"]`);
          if(savedOption && !savedOption.disabled) {
            savedOption.selected = true;
            node.data.splitModelId = savedOption.dataset.modelId || '';
            node.data.splitModelVendorId = savedOption.dataset.vendorId || '';
            node.data.splitModelVendorName = savedOption.dataset.vendorName || '';
            restored = true;
          }
        }
        if(!restored) {
          // 优先级：deepseek供应商的deepseek-v4-flash → zjt_api供应商的qwen3.5-plus → 第一个启用的模型
          const allOptions = splitModelSelect.querySelectorAll('option');
          let defaultOption = null;

          // 第一轮：优先查找 deepseek 供应商下的 deepseek-v4-flash
          for (let i = 0; i < allOptions.length; i++) {
            const opt = allOptions[i];
            if (!opt.disabled && opt.value && opt.value.includes('deepseek-v4-flash')
                && opt.dataset.vendorName === 'deepseek') {
              defaultOption = opt;
              console.log('[剧本节点-拆分模型] 选择默认模型: deepseek-v4-flash (deepseek)');
              break;
            }
          }

          // 第二轮：查找 zjt_api 供应商下的 qwen3.5-plus
          if (!defaultOption) {
            for (let i = 0; i < allOptions.length; i++) {
              const opt = allOptions[i];
              if (!opt.disabled && opt.value && opt.value.includes('qwen3.5-plus')
                  && opt.dataset.vendorName === 'zjt_api') {
                defaultOption = opt;
                console.log('[剧本节点-拆分模型] 选择默认模型: qwen3.5-plus (zjt_api)');
                break;
              }
            }
          }

          // 第三轮：查找其他供应商的 qwen3.5-plus
          if (!defaultOption) {
            for (let i = 0; i < allOptions.length; i++) {
              const opt = allOptions[i];
              if (!opt.disabled && opt.value && opt.value.includes('qwen3.5-plus')) {
                defaultOption = opt;
                console.log(`[剧本节点-拆分模型] 未找到 zjt_api 的 qwen3.5-plus，选择其他供应商: ${opt.dataset.vendorName}`);
                break;
              }
            }
          }

          // 最终回退：使用第一个启用的模型
          if (!defaultOption && firstEnabled) {
            defaultOption = firstEnabled;
            console.log(`[剧本节点-拆分模型] 未找到推荐模型，选择第一个启用的模型: ${firstEnabled.value}`);
          }

          if (defaultOption) {
            defaultOption.selected = true;
            node.data.splitModel = defaultOption.value;
            node.data.splitModelId = defaultOption.dataset.modelId || '';
            node.data.splitModelVendorId = defaultOption.dataset.vendorId || '';
            node.data.splitModelVendorName = defaultOption.dataset.vendorName || '';
          }
        }
      }

      // 初始化拆分模型
      populateScriptSplitModelOptions();

      // 拆分模型切换事件
      if(splitModelSelect) {
        splitModelSelect.addEventListener('change', () => {
          const selected = splitModelSelect.options[splitModelSelect.selectedIndex];
          node.data.splitModel = splitModelSelect.value;
          node.data.splitModelId = selected.dataset.modelId || '';
          node.data.splitModelVendorId = selected.dataset.vendorId || '';
          node.data.splitModelVendorName = selected.dataset.vendorName || '';
          console.log(`[剧本节点] 拆分模型切换为: ${splitModelSelect.value}, modelId: ${node.data.splitModelId}, vendor: ${node.data.splitModelVendorName}`);
        });
      }

      // 动态填充宫格生图模型选项
      function populateScriptGridModelOptions() {
        if(!gridModelSelect) return;

        function renderOptions() {
          if(!gridModelSelect) return;
          node.data.gridModel = populateGridImageModelSelect(gridModelSelect, node.data.gridModel);
        }

        if(window.TaskConfig && window.TaskConfig.isLoaded()) {
          renderOptions();
        } else if(window.TaskConfig) {
          node.data.gridModel = populateGridImageModelSelect(gridModelSelect, node.data.gridModel);
          window.TaskConfig.onLoaded(() => {
            renderOptions();
          });
        } else {
          renderOptions();
        }
      }

      // 初始化宫格生图模型
      populateScriptGridModelOptions();
      
      // 初始化节点数据中的最大时长和选项（仅设置默认值，不覆盖已保存的值）
      if(node.data.maxGroupDuration === undefined) node.data.maxGroupDuration = 15;
      if(node.data.forceMediumShot === undefined) node.data.forceMediumShot = true;
      if(node.data.noBgMusic === undefined) node.data.noBgMusic = true;
      if(node.data.splitMultiDialogue === undefined) node.data.splitMultiDialogue = false;
      if(node.data.narrationAsDialogue === undefined) node.data.narrationAsDialogue = false;
      if(!node.data.dialogueLanguage) node.data.dialogueLanguage = node.data.language || '';
      if(!node.data.promptLanguage) node.data.promptLanguage = node.data.language || '';
      if(!node.data.gridModel) node.data.gridModel = 'auto';
      if(!node.data.splitModelVendorId) node.data.splitModelVendorId = '';
      if(!node.data.splitModelVendorName) node.data.splitModelVendorName = '';

      // 确保已保存的宫格模型值在下拉框中可见，并恢复选中状态
      if(gridModelSelect) {
        node.data.gridModel = normalizeGridImageModelValue(node.data.gridModel);
        ensureSelectHasSavedOption(gridModelSelect, node.data.gridModel);
        gridModelSelect.value = node.data.gridModel;
      }

      // 应用驱动状态禁用未配置的宫格生图模型选项
      if(gridModelSelect) applyDriverStatusToSelect(gridModelSelect);

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

      // 语言选择监听 - 对话语言
      function bindLanguageSelect(selectEl, customEl, dataKey) {
        if(!selectEl) return;
        selectEl.addEventListener('change', () => {
          if(selectEl.value === '__custom__') {
            customEl.style.display = 'block';
            customEl.focus();
            node.data[dataKey] = customEl.value;
          } else {
            customEl.style.display = 'none';
            node.data[dataKey] = selectEl.value;
          }
        });
        customEl.addEventListener('input', () => {
          node.data[dataKey] = customEl.value;
        });
        // 恢复之前的选择
        if(node.data[dataKey]) {
          const presetValues = ['', 'English', 'Deutsch', 'Français', 'Русский'];
          if(presetValues.includes(node.data[dataKey])) {
            selectEl.value = node.data[dataKey];
            customEl.style.display = 'none';
          } else {
            selectEl.value = '__custom__';
            customEl.style.display = 'block';
            customEl.value = node.data[dataKey];
          }
        }
      }
      bindLanguageSelect(dialogueLanguageSelectEl, dialogueLanguageCustomEl, 'dialogueLanguage');
      bindLanguageSelect(promptLanguageSelectEl, promptLanguageCustomEl, 'promptLanguage');

      // 监听右上角语言切换，联动更新剧本提示词语言
      if(window.ZJTi18n && promptLanguageSelectEl) {
        window.ZJTi18n.on('locale-changed', ({ locale }) => {
          // 根据界面语言自动设置提示词语言
          const localeToLanguage = {
            'en': 'English',
            'zh-CN': ''
          };
          const newLanguage = localeToLanguage[locale];
          if(newLanguage !== undefined) {
            // 更新节点数据
            node.data.promptLanguage = newLanguage;
            // 更新下拉框显示
            const presetValues = ['', 'English', 'Deutsch', 'Français', 'Русский'];
            if(presetValues.includes(newLanguage)) {
              promptLanguageSelectEl.value = newLanguage;
              promptLanguageCustomEl.style.display = 'none';
            } else {
              promptLanguageSelectEl.value = '__custom__';
              promptLanguageCustomEl.style.display = 'block';
              promptLanguageCustomEl.value = newLanguage;
            }
          }
        });
      }

      // 宫格模型选择监听
      gridModelSelect.addEventListener('change', () => {
        node.data.gridModel = gridModelSelect.value;
      });

      // 宫格类型选择监听
      const gridLayoutSelect = el.querySelector('.script-grid-layout');
      if(!node.data.gridLayout){
        node.data.gridLayout = 'auto';
      }
      if(gridLayoutSelect){
        gridLayoutSelect.value = node.data.gridLayout;
        gridLayoutSelect.addEventListener('change', () => {
          node.data.gridLayout = gridLayoutSelect.value;
        });
      }

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
            showToast(window.t ? window.t('file_content_truncated').replace('${originalLength}', originalLength) : `文件内容已截取至30000字符（原${originalLength}字符）`, 'warning');
          } else {
            warningField.style.display = 'none';
            showToast(window.t ? window.t('script_file_load_success') : '剧本文件加载成功', 'success');
          }

          // 更新文本框内容
          textareaEl.value = content;
          updateScriptContent(content, `来源: ${file.name}${isTruncated ? ' (已截取)' : ''}`);

          fileEl.value = '';
        } catch(error) {
          console.error('读取文件失败:', error);
          showToast(window.t ? window.t('file_read_error') : '读取文件失败', 'error');
        }
      });

      splitBtn.addEventListener('click', async (e) => {
        e.stopPropagation();

        if(!node.data.scriptContent) {
          showToast(window.t ? window.t('upload_script_file_first') : '请先上传剧本文件', 'error');
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
            showToast(window.t ? window.t('duplicate_shot_group_warning') : '已有幕，请勿重复点击', 'warning');
            return;
          }
        }

        if(!state.defaultWorldId){
          const confirmed = await showConfirmModal('尚未在左上角选择世界，无法自动匹配场景和角色。确认继续拆分分镜图吗？', { title: '提示' });
          if(!confirmed){
            return;
          }
        }

        splitBtn.disabled = true;
        splitGridBtn.disabled = true;
        statusEl.style.display = 'block';
        setStatusEl(statusEl, node.data.narrationAsDialogue ? '正在将剧本转换为解说剧格式，再解析分镜...' : '正在调用LLM解析剧本...', '#666');

        try {
          const response = await fetch('/api/parse-script', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...getAuthHeaders()
            },
            body: JSON.stringify({
              script_content: node.data.scriptContent,
              max_group_duration: node.data.maxGroupDuration || 15,
              world_id: state.defaultWorldId,
              force_medium_shot: node.data.forceMediumShot || false,
              no_bg_music: node.data.noBgMusic || false,
              split_multi_dialogue: node.data.splitMultiDialogue || false,
              narration_as_dialogue: node.data.narrationAsDialogue || false,
              dialogue_language: node.data.dialogueLanguage || '',
              prompt_language: node.data.promptLanguage || '',
              model: node.data.splitModel || 'gemini-3-flash-preview',
              model_id: node.data.splitModelId || '',
              vendor_id: node.data.splitModelVendorId || ''
            })
          });

          const result = await response.json();
          
          if(result.code === 0 && result.data) {
            node.data.parsedData = result.data;
            
            setStatusEl(statusEl, `解析成功！共${result.data.shot_groups?.length || 0}个幕`, '#16a34a');
            if(window.TaskConfig && !window.TaskConfig.isLoaded()) {
              await window.TaskConfig.load();
            }
            
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
              const SPLIT_NODE_GAP_Y = 120; // 分镜组节点之间的Y轴间距，与自动排列保持一致
              let cumulativeY = 0;
              result.data.shot_groups.forEach((shotGroup, index) => {
                // 横向排列：shot_group 在 script 右侧，x 固定，y 纵向堆叠
                const shotGroupNodeId = createShotGroupNode({
                  x: node.x + 800,  // script右侧 + 2/3 shot_group宽度(200px)，留足间隙
                  y: node.y + cumulativeY,
                  shotGroupData: shotGroup,
                  scriptData: result.data
                });
                // 获取实际渲染高度，避免估算不准导致节点堆叠
                const shotGroupEl = canvasEl.querySelector(`.node[data-node-id="${shotGroupNodeId}"]`);
                const actualHeight = shotGroupEl ? shotGroupEl.offsetHeight : 300;
                cumulativeY += actualHeight + SPLIT_NODE_GAP_Y;
                
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
              
              // 渲染时间轴（创建柱子结构），不自动展开
              renderTimeline();
              if (!state.timeline.visible) flashExpandButton();
              
              renderAllConnections();
              renderMinimap();
              safeAutoSave()
              
              // 自动为每个分镜组生成分镜
              statusEl.textContent = '正在自动生成分镜...';
              for(const shotGroupNodeId of createdShotGroupNodes) {
                const shotGroupNode = state.nodes.find(n => n.id === shotGroupNodeId);
                if(shotGroupNode) {
                  await generateShotFramesIndependentAsync(shotGroupNodeId, shotGroupNode);
                }
              }
              setStatusEl(statusEl, `已完成：${createdShotGroupNodes.length}个幕，所有分镜已自动生成`, '#16a34a');
            }
            
            showToast(window.t ? window.t('script_split_complete') : '剧本拆分成功！所有分镜已自动生成', 'success');
          } else {
            throw new Error(result.message || '解析失败');
          }
        } catch(error) {
          console.error('剧本解析失败:', error);
          setStatusEl(statusEl, '解析失败: ' + (error.message || '未知错误'), '#dc2626');
          showToast(window.t ? window.t('script_parse_error') : '剧本解析失败', 'error');
        } finally {
          splitBtn.disabled = false;
          splitGridBtn.disabled = false;
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

        if(splitGridBtn.disabled) return;
        splitGridBtn.disabled = true;
        splitBtn.disabled = true;

        console.log('[宫格生图] 按钮被点击');
        
        if(!node.data.scriptContent) {
          console.log('[宫格生图] 没有剧本内容');
          showToast('请先上传剧本文件', 'error');
          splitGridBtn.disabled = false;
          splitBtn.disabled = false;
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
            showToast('已有幕和分镜节点，请勿重复点击', 'warning');
            splitGridBtn.disabled = false;
            splitBtn.disabled = false;
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
                splitGridBtn.disabled = false;
                splitBtn.disabled = false;
                return;
              }

              const gridModel = normalizeGridImageModelValue(node.data.gridModel);
              const gridLayoutPref = node.data.gridLayout || 'auto';

              // 如果参考图片超过5张，必须使用增强版模型（支持13张参考图）
              const forceEnhancedModel = referenceImageUrls.length > 5;
              if(forceEnhancedModel) {
                console.log(`[宫格生图] 参考图片数量(${referenceImageUrls.length})超过5张，强制使用增强版模型`);
              }

              const { gridSize, gridLayout, finalModel } = resolveGridConfig(gridModel, gridLayoutPref, shotCount, forceEnhancedModel);

              // 限制参考图片数量（nano-banana最多5张，其他模型最多13张）
              const maxRefImages = finalModel === 'gemini-2.5-flash-image-preview' ? 5 : 13;
              if(referenceImageUrls.length > maxRefImages) {
                console.warn(`[宫格生图] 参考图片数量 ${referenceImageUrls.length} 超过限制 ${maxRefImages}，将只使用前 ${maxRefImages} 张`);
                referenceImageUrls.splice(maxRefImages);
                promptSuffix.splice(maxRefImages);
              }

              node.data.gridModel = finalModel;

              const imagePower = TaskConfig.getComputingPower(finalModel) || 2;
              const imageCount = Math.ceil(shotCount / gridSize);
              const totalPower = imageCount * imagePower;

              // 获取模型显示名称
              const taskInfo = TaskConfig.getTaskByKey(finalModel);
              const modelDisplayName = taskInfo ? taskInfo.name : finalModel;

              const refImageInfo = referenceImageUrls.length > 0 ? `\n参考图片：${referenceImageUrls.length}张` : '';
              const confirmMsg = `即将生成${imageCount}张${gridLayout}宫格图片\n` +
                `分镜数量：${shotCount}个\n` +
                `模型：${modelDisplayName}${refImageInfo}\n` +
                `预计消耗算力：${totalPower}\n\n` +
                `确认生成吗？`;
              
              if(!await showConfirmModal(confirmMsg, { title: '宫格生图确认', confirmText: '开始生成' })) {
                gridStatusEl.style.color = '#666';
                gridStatusEl.textContent = '已取消';
                splitGridBtn.disabled = false;
                splitBtn.disabled = false;
                return;
              }

              // 第五步：拼接提示词并调用API
              gridStatusEl.textContent = `正在生成${imageCount}张${gridLayout}宫格图片...`;
              
              const gridTasks = [];
              for(let i = 0; i < imageCount; i++) {
                const startIdx = i * gridSize;
                const endIdx = Math.min(startIdx + gridSize, shotCount);
                const batchNodes = allShotFrameNodes.slice(startIdx, endIdx);
                
                const gridPrompt = buildGridPrompt(batchNodes, startIdx, gridLayout, gridSize);
                
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
                appendAuthToForm(form);
                
                if(finalModel === 'gemini-3-pro-image-preview') {
                  form.append('image_size', '4K');
                }
                
                let apiUrl, res;
                console.log('[DEBUG-宫格生图] state.ratio:', state.ratio, 'ratioSelectEl.value:', ratioSelectEl.value, '发送比例:', state.ratio || '16:9', '模型:', finalModel);
                if(referenceImageUrls.length > 0) {
                  // 有参考图片URL，使用图片编辑API，直接传URL
                  const taskId1 = TaskConfig.getTaskIdByKey(finalModel, 'image_edit');
                  if(!taskId1) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
                  form.append('task_id', taskId1);
                  form.append('ref_image_urls', referenceImageUrls.join(','));
                  form.append('ratio', state.ratio || '16:9');
                  apiUrl = '/api/image-edit';
                } else {
                  // 无参考图片，使用文生图API
                  const taskId2 = TaskConfig.getTaskIdByKey(finalModel, 'text_to_image');
                  if(!taskId2) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
                  form.append('task_id', taskId2);
                  form.append('aspect_ratio', state.ratio || '16:9');
                  apiUrl = '/api/text-to-image';
                }
                
                res = await fetch(apiUrl, {
                  method: 'POST',
                  body: form
                });
                
                const resText = await res.text();
                let data;
                try { data = JSON.parse(resText); } catch(e) {
                  throw new Error(`API返回异常 (HTTP ${res.status}): ${resText.slice(0, 200) || '空响应'}`);
                }
                
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
                    y: shotFrameNode.y,
                    checkCollision: true
                  });
                  
                  const gridImageNode = state.nodes.find(n => n.id === gridImageNodeId);
                  if(gridImageNode) {
                    gridImageNode.data.name = `分镜图 ${gridIndex}/${gridSize}`;
                    gridImageNode.data.project_id = task.aiToolsId;
                    gridImageNode.data.aiToolsId = task.aiToolsId;
                    gridImageNode.data.gridIndex = gridIndex;
                    gridImageNode.data.gridSize = gridSize;
                    gridImageNode.data.shotFrameNodeId = shotFrameNode.id;
                    gridImageNode.data.isSplit = true;
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


              renderAllConnections();
              renderMinimap();

              safeAutoSave()

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
                        console.log(`[宫格生图] AI工具 ${aiToolsId} 生成成功，标记节点等待拆分`);
                        
                        for(let idx = 0; idx < taskData.batchNodes.length; idx++) {
                          const gridIndex = idx + 1;
                          const gridNode = state.nodes.find(n => 
                            n.type === 'image' && 
                            String(n.data.aiToolsId) === aiToolsId && 
                            n.data.gridIndex === gridIndex
                          );
                          if(gridNode) {
                            gridNode.data.status = 'splitting';
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
                  
                  safeAutoSave();
                  
                  gridStatusEl.style.color = '#16a34a';
                  gridStatusEl.textContent = '宫格图片生成完成，正在拆分...';
                  showToast('宫格图片生成完成，正在拆分', 'success');
                  
                  // 立即触发一次拆分（不等 60 秒轮询周期）
                  pollWorkflowNodeStatus();
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
            } finally {
              splitGridBtn.disabled = false;
              splitBtn.disabled = false;
            }
            return;
          }
        }

        if(!state.defaultWorldId){
          const confirmed = await showConfirmModal('尚未在左上角选择世界，无法自动匹配场景和角色。确认继续拆分分镜图吗？', { title: '提示' });
          if(!confirmed){
            splitGridBtn.disabled = false;
            splitBtn.disabled = false;
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
              ...getAuthHeaders()
            },
            body: JSON.stringify({
              script_content: node.data.scriptContent,
              max_group_duration: node.data.maxGroupDuration || 15,
              world_id: state.defaultWorldId,
              force_medium_shot: node.data.forceMediumShot || false,
              no_bg_music: node.data.noBgMusic || false,
              split_multi_dialogue: node.data.splitMultiDialogue || false,
              narration_as_dialogue: node.data.narrationAsDialogue || false,
              dialogue_language: node.data.dialogueLanguage || '',
              prompt_language: node.data.promptLanguage || '',
              model: node.data.splitModel || 'gemini-3-flash-preview',
              model_id: node.data.splitModelId || '',
              vendor_id: node.data.splitModelVendorId || ''
            })
          });

          const result = await response.json();
          
          if(result.code !== 0 || !result.data) {
            throw new Error(result.message || '解析失败');
          }

          node.data.parsedData = result.data;
          gridStatusEl.style.color = '#16a34a';
          gridStatusEl.textContent = `解析成功！共${result.data.shot_groups?.length || 0}个幕`;

          // 第二步：创建分镜组节点和分镜节点
          if(!result.data.shot_groups || result.data.shot_groups.length === 0) {
            throw new Error('未生成幕');
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
            const offsetX = 800;
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

          // 渲染时间轴（创建柱子结构），不自动展开
          renderTimeline();
          if (!state.timeline.visible) flashExpandButton();
          
          renderAllConnections();
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

          const gridModel = normalizeGridImageModelValue(node.data.gridModel);
          const gridLayoutPref = node.data.gridLayout || 'auto';

          // 如果参考图片超过5张，必须使用增强版模型（支持13张参考图）
          const forceEnhancedModel = referenceImageUrls.length > 5;
          if(forceEnhancedModel) {
            console.log(`[宫格生图] 参考图片数量(${referenceImageUrls.length})超过5张，强制使用增强版模型`);
          }

          const { gridSize, gridLayout, finalModel } = resolveGridConfig(gridModel, gridLayoutPref, shotCount, forceEnhancedModel);

          // 限制参考图片数量（nano-banana最多5张，其他模型最多13张）
          const maxRefImages = finalModel === 'gemini-2.5-flash-image-preview' ? 5 : 13;
          if(referenceImageUrls.length > maxRefImages) {
            console.warn(`[宫格生图] 参考图片数量 ${referenceImageUrls.length} 超过限制 ${maxRefImages}，将只使用前 ${maxRefImages} 张`);
            referenceImageUrls.splice(maxRefImages);
            promptSuffix.splice(maxRefImages);
          }
          
          node.data.gridModel = finalModel;
          const imagePower = TaskConfig.getComputingPower(finalModel) || 2;
          const imageCount = Math.ceil(shotCount / gridSize);
          const totalPower = imageCount * imagePower;

          // 获取模型显示名称
          const taskInfo = TaskConfig.getTaskByKey(finalModel);
          const modelDisplayName = taskInfo ? taskInfo.name : finalModel;

          // 确认生成
          const refImageInfo = referenceImageUrls.length > 0 ? `\n参考图片：${referenceImageUrls.length}张` : '';
          const confirmMsg = `即将生成${imageCount}张${gridLayout}宫格图片\n` +
            `分镜数量：${shotCount}个\n` +
            `模型：${modelDisplayName}${refImageInfo}\n` +
            `预计消耗算力：${totalPower}\n\n` +
            `确认生成吗？`;
          
          if(!await showConfirmModal(confirmMsg, { title: '宫格生图确认', confirmText: '开始生成' })) {
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
            
            const gridPrompt = buildGridPrompt(batchNodes, startIdx, gridLayout, gridSize);
            
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
            appendAuthToForm(form);
            
            // 加强版模型需要传入4K图片大小
            if(finalModel === 'gemini-3-pro-image-preview') {
              form.append('image_size', '4K');
            }
            
            let apiUrl, res;
            if(referenceImageUrls.length > 0) {
              // 有参考图片URL，使用图片编辑API，直接传URL
              const taskId3 = TaskConfig.getTaskIdByKey(finalModel, 'image_edit');
              if(!taskId3) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
              form.append('task_id', taskId3);
              form.append('ref_image_urls', referenceImageUrls.join(','));
              form.append('ratio', state.ratio || '16:9');
              apiUrl = '/api/image-edit';
            } else {
              // 无参考图片，使用文生图API
              const taskId4 = TaskConfig.getTaskIdByKey(finalModel, 'text_to_image');
              if(!taskId4) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
              form.append('task_id', taskId4);
              form.append('aspect_ratio', state.ratio || '16:9');
              apiUrl = '/api/text-to-image';
            }
            
            res = await fetch(apiUrl, {
              method: 'POST',
              body: form
            });
            
            const resText2 = await res.text();
            let data;
            try { data = JSON.parse(resText2); } catch(e) {
              throw new Error(`API返回异常 (HTTP ${res.status}): ${resText2.slice(0, 200) || '空响应'}`);
            }
            
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
                y: shotFrameNode.y,
                checkCollision: true
              });
              
              const gridImageNode = state.nodes.find(n => n.id === gridImageNodeId);
              if(gridImageNode) {
                gridImageNode.data.name = `分镜图 ${gridIndex}/${gridSize}`;
                gridImageNode.data.project_id = task.aiToolsId;
                gridImageNode.data.aiToolsId = task.aiToolsId;
                gridImageNode.data.gridIndex = gridIndex;
                gridImageNode.data.gridSize = gridSize;
                gridImageNode.data.shotFrameNodeId = shotFrameNode.id;
                gridImageNode.data.isSplit = true;
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

          renderAllConnections();
          renderMinimap();
          safeAutoSave()

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
                    console.log(`[宫格生图] AI工具 ${aiToolsId} 生成成功，标记节点等待拆分`);
                    
                    for(let idx = 0; idx < taskData.batchNodes.length; idx++) {
                      const gridIndex = idx + 1;
                      const gridNode = state.nodes.find(n => 
                        n.type === 'image' && 
                        String(n.data.aiToolsId) === aiToolsId && 
                        n.data.gridIndex === gridIndex
                      );
                      if(gridNode) {
                        gridNode.data.status = 'splitting';
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
              safeAutoSave();
              
              gridStatusEl.style.color = '#16a34a';
              gridStatusEl.textContent = '宫格图片生成完成，正在拆分...';
              showToast('宫格图片生成完成，正在拆分', 'success');
              
              // 立即触发一次拆分（不等 60 秒轮询周期）
              pollWorkflowNodeStatus();
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
        } finally {
          splitGridBtn.disabled = false;
          splitBtn.disabled = false;
        }
      });

      // 批量生成视频按钮监听
      batchGenerateBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        
        batchStatusEl.style.display = 'block';
        batchStatusEl.style.color = '#666';
        batchStatusEl.textContent = '正在检查分镜节点...';
        
        try {
          // 查找连接到此剧本节点的分镜组
          const shotGroupConnections = state.connections.filter(c => c.from === id);
          const shotGroupNodes = shotGroupConnections
            .map(conn => state.nodes.find(n => n.id === conn.to))
            .filter(n => n && n.type === 'shot_group');
          
          if(shotGroupNodes.length === 0) {
            batchStatusEl.style.color = '#dc2626';
            batchStatusEl.textContent = '未找到幕节点，请先拆分幕';
            showToast('未找到幕节点，请先拆分幕', 'error');
            return;
          }
          
          // 收集所有分镜节点并计算算力消耗
          let totalShotFrames = 0;
          let totalPower = 0;
          const shotGroupsWithFrames = [];
          
          for(const sgNode of shotGroupNodes) {
            const sfConnections = state.connections.filter(c => c.from === sgNode.id);
            const sfNodes = sfConnections
              .map(conn => state.nodes.find(n => n.id === conn.to))
              .filter(n => n && n.type === 'shot_frame');
            
            if(sfNodes.length > 0) {
              // 检查就绪的分镜（有预览图或启用参考图模式）
              const readyNodes = sfNodes.filter(n => {
                const nodeMode = n.data.videoMode || 'first_last_frame';
                return nodeMode === 'multi_reference' || n.data.previewImageUrl || n.data.imageUrl;
              });

              if(readyNodes.length > 0) {
                shotGroupsWithFrames.push({
                  shotGroupNode: sgNode,
                  shotFrameNodes: readyNodes
                });

                // 计算每个分镜的算力消耗
                // 模型优先级：分镜节点 > 分镜组 > 剧本节点 > 默认wan22
                readyNodes.forEach(sfNode => {
                  const videoModel = sfNode.data.videoModel || sgNode.data.videoModel || node.data.videoModel || 'wan22';
                  const duration = sfNode.data.videoDuration || sfNode.data.duration || 5;
                  const drawCount = sfNode.data.videoDrawCount || 1;
                  
                  const singlePower = calculateVideoGenerationPower(videoModel, duration);
                  totalPower += singlePower * drawCount;
                  totalShotFrames++;
                });
              }
            }
          }
          
          if(shotGroupsWithFrames.length === 0) {
            batchStatusEl.style.color = '#dc2626';
            batchStatusEl.textContent = '幕下未找到有预览图的分镜节点';
            showToast('幕下未找到有预览图的分镜节点，请先生成分镜图', 'error');
            return;
          }
          
          // 显示确认弹窗
          const confirmMsg = `即将为整个剧本的所有分镜生成视频\n` +
            `幕数量：${shotGroupsWithFrames.length}个\n` +
            `分镜数量：${totalShotFrames}个\n` +
            `预计消耗算力：${totalPower}\n\n` +
            `确认开始生成吗？`;
          
          if(!await showConfirmModal(confirmMsg, { title: '批量生成视频确认', confirmText: '开始生成' })) {
            batchStatusEl.style.color = '#666';
            batchStatusEl.textContent = '已取消';
            return;
          }
          
          // 首次使用提示
          const batchTipKey = 'script_batch_tip_shown';
          if(!localStorage.getItem(batchTipKey)) {
            showToast('逐个生成：为整个剧本的所有分镜生成视频，支持所有模型但可能浪费时长', 'info', 5000);
            localStorage.setItem(batchTipKey, 'true');
          }
          
          setBtnLoading(batchGenerateBtn, '批量生成中...');
          
          let successCount = 0;
          let failCount = 0;
          
          for(let i = 0; i < shotGroupsWithFrames.length; i++) {
            const { shotGroupNode, shotFrameNodes } = shotGroupsWithFrames[i];
            
            batchStatusEl.textContent = `正在生成 ${i + 1}/${shotGroupsWithFrames.length} 个幕的视频...`;
            showToast(`正在生成 ${i + 1}/${shotGroupsWithFrames.length} 个幕的视频...`, 'info');
            
            try {
              // 将剧本节点的视频模型同步到分镜组节点（修复剧本节点视频模型选择不生效的bug）
              if(node.data.videoModel) {
                shotGroupNode.data.videoModel = node.data.videoModel;
              }
              // 为每个分镜组调用批量生成函数
              await generateAllShotFrameVideos(shotGroupNode.id, shotGroupNode);
              successCount++;
            } catch(error) {
              console.error(`生成幕视频失败:`, error);
              failCount++;
            }
          }
          
          setBtnReady(batchGenerateBtn, '逐个生成视频');
          
          const resultMsg = `批量生成完成！成功 ${successCount} 个幕，失败 ${failCount} 个`;
          batchStatusEl.style.color = successCount > 0 ? '#22c55e' : '#dc2626';
          batchStatusEl.textContent = resultMsg;
          showToast(resultMsg, successCount > 0 ? 'success' : 'warning');
          
          safeAutoSave()
        } catch(error) {
          console.error('Generate script videos error:', error);
          showToast(`批量生成失败: ${error.message}`, 'error');
          
          setBtnReady(batchGenerateBtn, '逐个生成视频');
          batchStatusEl.style.color = '#dc2626';
          batchStatusEl.textContent = `失败: ${error.message}`;
        }
      });

      // 宫格生图（仅生图，不拆分）按钮监听
      gridOnlyBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        
        gridOnlyStatusEl.style.display = 'block';
        gridOnlyStatusEl.style.color = '#666';
        gridOnlyStatusEl.textContent = '正在检查分镜节点...';
        
        try {
          // 查找连接到此剧本节点的分镜组
          const shotGroupConnections = state.connections.filter(c => c.from === id);
          const shotGroupNodes = shotGroupConnections
            .map(conn => state.nodes.find(n => n.id === conn.to))
            .filter(n => n && n.type === 'shot_group');
          
          if(shotGroupNodes.length === 0) {
            gridOnlyStatusEl.style.color = '#dc2626';
            gridOnlyStatusEl.textContent = '未找到幕节点，请先拆分幕';
            showToast('未找到幕节点，请先拆分幕', 'error');
            return;
          }
          
          // 收集所有分镜节点
          const allShotFrameNodes = [];
          for(const sgNode of shotGroupNodes) {
            const sfConnections = state.connections.filter(c => c.from === sgNode.id);
            const sfNodes = sfConnections
              .map(conn => state.nodes.find(n => n.id === conn.to))
              .filter(n => n && n.type === 'shot_frame');
            allShotFrameNodes.push(...sfNodes);
          }
          
          if(allShotFrameNodes.length === 0) {
            gridOnlyStatusEl.style.color = '#dc2626';
            gridOnlyStatusEl.textContent = '幕下未找到分镜节点，请先拆分幕';
            showToast('幕下未找到分镜节点', 'error');
            return;
          }
          
          const shotCount = allShotFrameNodes.length;
          if(shotCount === 1) {
            gridOnlyStatusEl.style.color = '#f59e0b';
            gridOnlyStatusEl.textContent = '只有1个分镜，无需宫格生图';
            showToast('只有1个分镜，无需宫格生图', 'warning');
            return;
          }
          
          gridOnlyStatusEl.textContent = '正在收集参考图片...';
          
          // 收集参考图片
          const { referenceImageUrls, promptSuffix } = await collectReferenceImagesForGrid(allShotFrameNodes);
          console.log(`[宫格生图-仅生图] 收集到 ${referenceImageUrls.length} 张参考图片URL`);
          
          // 决定宫格大小和模型
          const gridModel = normalizeGridImageModelValue(node.data.gridModel);
          const gridLayoutPref = node.data.gridLayout || 'auto';
          const forceEnhancedModel = referenceImageUrls.length > 5;

          const { gridSize, gridLayout, finalModel } = resolveGridConfig(gridModel, gridLayoutPref, shotCount, forceEnhancedModel);

          // 限制参考图片数量（nano-banana最多5张，其他模型最多13张）
          const maxRefImages = finalModel === 'gemini-2.5-flash-image-preview' ? 5 : 13;
          if(referenceImageUrls.length > maxRefImages) {
            referenceImageUrls.splice(maxRefImages);
            promptSuffix.splice(maxRefImages);
          }
          
          node.data.gridModel = finalModel;

          const imagePower = TaskConfig.getComputingPower(finalModel) || 2;
          const imageCount = Math.ceil(shotCount / gridSize);
          const totalPower = imageCount * imagePower;

          // 获取模型显示名称
          const taskInfo = TaskConfig.getTaskByKey(finalModel);
          const modelDisplayName = taskInfo ? taskInfo.name : finalModel;

          const refImageInfo = referenceImageUrls.length > 0 ? `\n参考图片：${referenceImageUrls.length}张` : '';
          const confirmMsg = `即将生成${imageCount}张${gridLayout}宫格图片\n` +
            `分镜数量：${shotCount}个\n` +
            `模型：${modelDisplayName}${refImageInfo}\n` +
            `预计消耗算力：${totalPower}\n\n` +
            `确认生成吗？`;
          
          if(!await showConfirmModal(confirmMsg, { title: '宫格生图确认', confirmText: '开始生成' })) {
            gridOnlyStatusEl.style.color = '#666';
            gridOnlyStatusEl.textContent = '已取消';
            return;
          }
          
          // 拼接提示词并调用API
          gridOnlyStatusEl.textContent = `正在生成${imageCount}张${gridLayout}宫格图片...`;
          
          const gridTasks = [];
          for(let i = 0; i < imageCount; i++) {
            const startIdx = i * gridSize;
            const endIdx = Math.min(startIdx + gridSize, shotCount);
            const batchNodes = allShotFrameNodes.slice(startIdx, endIdx);
            
            const gridPrompt = buildGridPrompt(batchNodes, startIdx, gridLayout, gridSize);
            
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
            appendAuthToForm(form);
            
            if(finalModel === 'gemini-3-pro-image-preview') {
              form.append('image_size', '4K');
            }
            
            let apiUrl, res;
            if(referenceImageUrls.length > 0) {
              const taskId5 = TaskConfig.getTaskIdByKey(finalModel, 'image_edit');
              if(!taskId5) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
              form.append('task_id', taskId5);
              form.append('ref_image_urls', referenceImageUrls.join(','));
              form.append('ratio', state.ratio || '16:9');
              apiUrl = '/api/image-edit';
            } else {
              const taskId6 = TaskConfig.getTaskIdByKey(finalModel, 'text_to_image');
              if(!taskId6) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
              form.append('task_id', taskId6);
              form.append('aspect_ratio', state.ratio || '16:9');
              apiUrl = '/api/text-to-image';
            }
            
            res = await fetch(apiUrl, {
              method: 'POST',
              body: form
            });
            
            const resText3 = await res.text();
            let data;
            try { data = JSON.parse(resText3); } catch(e) {
              throw new Error(`API返回异常 (HTTP ${res.status}): ${resText3.slice(0, 200) || '空响应'}`);
            }
            
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
          
          gridOnlyStatusEl.textContent = '正在创建分镜图节点...';
          
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
                y: shotFrameNode.y,
                checkCollision: true
              });
              
              const gridImageNode = state.nodes.find(n => n.id === gridImageNodeId);
              if(gridImageNode) {
                gridImageNode.data.name = `分镜图 ${gridIndex}/${gridSize}`;
                gridImageNode.data.project_id = task.aiToolsId;
                gridImageNode.data.aiToolsId = task.aiToolsId;
                gridImageNode.data.gridIndex = gridIndex;
                gridImageNode.data.gridSize = gridSize;
                gridImageNode.data.shotFrameNodeId = shotFrameNode.id;
                gridImageNode.data.isSplit = true;
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
          
          renderAllConnections();
          renderMinimap();
          safeAutoSave()

          gridOnlyStatusEl.style.color = '#16a34a';
          gridOnlyStatusEl.textContent = `已提交${imageCount}张宫格图片生成任务，正在轮询状态...`;
          showToast(`已提交${imageCount}张宫格图片生成任务`, 'success');

          const allAiToolsIds = completedTasks.map(t => t.aiToolsId);

          pollVideoStatus(
            allAiToolsIds,
            (progressText) => {
              gridOnlyStatusEl.textContent = progressText;
            },
            async (statusResult) => {
              if(statusResult.tasks) {
                for(const taskInfo of statusResult.tasks) {
                  const aiToolsId = String(taskInfo.project_id);
                  const taskData = aiToolsMap[aiToolsId];
                  
                  if(!taskData) continue;
                  
                  if(taskInfo.status === 'SUCCESS') {
                    for(let idx = 0; idx < taskData.batchNodes.length; idx++) {
                      const gridIndex = idx + 1;
                      const gridNode = state.nodes.find(n => 
                        n.type === 'image' && 
                        String(n.data.aiToolsId) === aiToolsId && 
                        n.data.gridIndex === gridIndex
                      );
                      if(gridNode) {
                        gridNode.data.status = 'splitting';
                      }
                    }
                  } else if(taskInfo.status === 'FAILED') {
                    state.nodes.forEach(gridNode => {
                      if(gridNode.type === 'image' && String(gridNode.data.aiToolsId) === aiToolsId) {
                        gridNode.data.status = 'failed';
                      }
                    });
                  }
                }
              }
              
              safeAutoSave();

              gridOnlyStatusEl.style.color = '#16a34a';
              gridOnlyStatusEl.textContent = '宫格图片生成完成，正在拆分...';
              showToast('宫格图片生成完成，正在拆分', 'success');
              
              pollWorkflowNodeStatus();
            },
            (errorMsg) => {
              gridOnlyStatusEl.style.color = '#dc2626';
              gridOnlyStatusEl.textContent = errorMsg;
              showToast(errorMsg, 'error');
            }
          );
          
        } catch(error) {
          console.error('[宫格生图-仅生图] 失败:', error);
          gridOnlyStatusEl.style.color = '#dc2626';
          gridOnlyStatusEl.textContent = '失败: ' + (error.message || '未知错误');
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
        container.innerHTML = `<div style="padding: 16px; text-align: center; color: #666; font-size: 11px; grid-column: 1/-1;">${window.t ? window.t('shot_group_no_shot_node') : '暂无分镜节点'}</div>`;
        if(labelEl) {
          labelEl.textContent = window.t ? window.t('shot_group_preview_label', { count: 0 }) : '分镜预览（0个分镜）';
          labelEl.setAttribute('data-i18n-params', JSON.stringify({ count: 0 }));
        }
        return;
      }

      const gridSize = calculateGridSize(shotCount);
      if(!gridSize) {
        container.innerHTML = `<div style="padding: 16px; text-align: center; color: #f59e0b; font-size: 11px; grid-column: 1/-1;">${window.t ? window.t('shot_group_grid_overflow') : '分镜数量超过25，不支持宫格预览'}</div>`;
        return;
      }

      const n = Math.sqrt(gridSize);
      container.className = `shot-grid-preview-container grid-${n}x${n}`;

      if(labelEl) {
        const previewText = window.t ? window.t('shot_group_preview_label', { count: shotCount }) : `分镜预览（${shotCount}个分镜）`;
        labelEl.textContent = `${previewText} → ${gridSize}${window.t ? window.t('shot_group_grid_suffix') : '宫格'}`;
        labelEl.setAttribute('data-i18n-params', JSON.stringify({ count: shotCount }));
      }

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
          model: shotGroupData.model || defaultImageModel,
          gridModel: normalizeGridImageModelValue(shotGroupData.gridModel || shotGroupData.grid_model),
          videoModel: resolvedVideoModel,
          videoDuration: pickFirstDefinedValue(shotGroupData.videoDuration, shotGroupData.video_duration) || 5,
          videoDrawCount: pickFirstDefinedValue(shotGroupData.videoDrawCount, shotGroupData.video_draw_count) || 1,
          videoGenMode: shotGroupData.videoGenMode || 'first_last_frame',
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
            <div style="color: #666; font-size: 11px; margin-top: 2px;">起始画面: ${escapeHtml((shot.opening_frame_description || '').slice(0, 60))}...</div>
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
              <div class="field field-always-visible" style="margin-top:5px">
                <div class="label" data-i18n="shot_group_video_duration_label">${window.t ? window.t('shot_group_video_duration_label') : '视频时长'}</div>
                <select class="shot-group-video-duration">
                  <option value="5" selected data-i18n="shot_group_video_duration_5s">${window.t ? window.t('shot_group_video_duration_5s') : '5秒'}</option>
                  <option value="10" data-i18n="shot_group_video_duration_10s">${window.t ? window.t('shot_group_video_duration_10s') : '10秒'}</option>
                </select>
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
        updateVideoComputingPowerDisplay();
        updateMergeButtonVisibility(videoModelEl.value);
      });

      // 视频生成模式选择事件（切换模式时重新过滤视频模型列表）
      if(videoGenModeEl) {
        videoGenModeEl.addEventListener('change', () => {
          node.data.videoGenMode = videoGenModeEl.value;
          populateShotGroupVideoModelOptions();
          updateMergeButtonVisibility(videoModelEl.value);
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

      // 初始化合并按钮显示状态
      if(window.TaskConfig?.isLoaded()) {
        updateMergeButtonVisibility(node.data.videoModel || 'wan22');
      } else {
        // 等待配置加载完成
        window.TaskConfig?.onLoaded(() => {
          updateMergeButtonVisibility(node.data.videoModel || 'wan22');
        });
      }

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
        
        const gridModel = normalizeGridImageModelValue(shotGroupNode.data.gridModel);
        const gridLayoutPref = shotGroupNode.data.gridLayout || 'auto';

        // 如果参考图片超过5张，必须使用增强版模型（支持13张参考图）
        const forceEnhancedModel = referenceImageUrls.length > 5;
        if(forceEnhancedModel) {
          console.log(`[宫格生图] 参考图片数量(${referenceImageUrls.length})超过5张，强制使用增强版模型`);
        }

        const { gridSize, gridLayout, finalModel } = resolveGridConfig(gridModel, gridLayoutPref, shotCount, forceEnhancedModel);

        // 限制参考图片数量（nano-banana最多5张，其他模型最多13张）
        const maxRefImages = finalModel === 'gemini-2.5-flash-image-preview' ? 5 : 13;
        if(referenceImageUrls.length > maxRefImages) {
          console.warn(`[宫格生图] 参考图片数量 ${referenceImageUrls.length} 超过限制 ${maxRefImages}，将只使用前 ${maxRefImages} 张`);
          referenceImageUrls.splice(maxRefImages);
          promptSuffix.splice(maxRefImages);
        }
        
        shotGroupNode.data.gridModel = finalModel;

        const imagePower = TaskConfig.getComputingPower(finalModel) || 2;
        const imageCount = Math.ceil(shotCount / gridSize);
        const totalPower = imageCount * imagePower;

        // 获取模型显示名称
        const taskInfo = TaskConfig.getTaskByKey(finalModel);
        const modelDisplayName = taskInfo ? taskInfo.name : finalModel;

        const refImageInfo = referenceImageUrls.length > 0 ? `\n参考图片：${referenceImageUrls.length}张` : '';
        const confirmMsg = `即将生成${imageCount}张${gridLayout}宫格图片\n` +
          `分镜数量：${shotCount}个\n` +
          `模型：${modelDisplayName}${refImageInfo}\n` +
          `预计消耗算力：${totalPower}\n\n` +
          `确认生成吗？`;
        
        if(!await showConfirmModal(confirmMsg, { title: '宫格生图确认', confirmText: '开始生成' })) {
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
          
          const gridPrompt = buildGridPrompt(batchNodes, startIdx, gridLayout, gridSize);
          
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
          appendAuthToForm(form);
          
          if(finalModel === 'gemini-3-pro-image-preview') {
            form.append('image_size', '4K');
          }
          
          let apiUrl, res;
          if(referenceImageUrls.length > 0) {
            // 有参考图片URL，使用图片编辑API，直接传URL
            const taskId7 = TaskConfig.getTaskIdByKey(finalModel, 'image_edit');
            if(!taskId7) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
            form.append('task_id', taskId7);
            form.append('ref_image_urls', referenceImageUrls.join(','));
            form.append('ratio', state.ratio || '16:9');
            apiUrl = '/api/image-edit';
          } else {
            // 无参考图片，使用文生图API
            const taskId8 = TaskConfig.getTaskIdByKey(finalModel, 'text_to_image');
            if(!taskId8) throw new Error(`未找到模型 ${finalModel} 对应的任务配置`);
            form.append('task_id', taskId8);
            form.append('aspect_ratio', state.ratio || '16:9');
            apiUrl = '/api/text-to-image';
          }
          
          res = await fetch(apiUrl, {
            method: 'POST',
            body: form
          });
          
          const resText4 = await res.text();
          let data;
          try { data = JSON.parse(resText4); } catch(e) {
            throw new Error(`API返回异常 (HTTP ${res.status}): ${resText4.slice(0, 200) || '空响应'}`);
          }
          
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
              y: shotFrameNode.y,
              checkCollision: true
            });
            
            const gridImageNode = state.nodes.find(n => n.id === gridImageNodeId);
            if(gridImageNode) {
              gridImageNode.data.name = `分镜图 ${gridIndex}/${gridSize}`;
              gridImageNode.data.project_id = task.aiToolsId;
              gridImageNode.data.aiToolsId = task.aiToolsId;
              gridImageNode.data.gridIndex = gridIndex;
              gridImageNode.data.gridSize = gridSize;
              gridImageNode.data.shotFrameNodeId = shotFrameNode.id;
              gridImageNode.data.isSplit = true;
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
        renderAllConnections();
        renderMinimap();


        if(!state.aiToolsMap) {
          state.aiToolsMap = {};
        }
        Object.assign(state.aiToolsMap, aiToolsMap);

        gridStatusEl.style.color = '#22c55e';
        gridStatusEl.textContent = `已提交${imageCount}张宫格图片生成任务，等待AI生成...`;
        showToast(`已提交${imageCount}张宫格图片生成任务`, 'success');
        
        safeAutoSave()
        
      } catch(error) {
        console.error('[宫格生图] 错误:', error);
        gridStatusEl.style.color = '#ef4444';
        gridStatusEl.textContent = `生成失败: ${error.message}`;
        showToast(`宫格生图失败: ${error.message}`, 'error');
      }
    }

    // 就地更新已有 shot_frame 节点的基础信息（保守同步：保留生成结果与用户编辑的提示词）
    function updateShotFrameNodeBasic(shotFrameNode, shot){
      shotFrameNode.data.description = shot.description || '';
      shotFrameNode.data.duration = shot.duration || 0;
      shotFrameNode.data.shotType = shot.shot_type || '';
      shotFrameNode.data.cameraMovement = shot.camera_movement || '';
      // 更新 shotJson 快照，保留原有附加字段（allLocationInfo/scriptData 等）
      shotFrameNode.data.shotJson = {
        ...(shotFrameNode.data.shotJson || {}),
        ...shot
      };
      // 保留：imageUrl/generatedImage/previewImageUrl/videoMode/model/drawCount/videoDrawCount/videoDuration/videoModel/imagePrompt/videoPrompt/videoPromptText

      // 就地更新 DOM 显示（只改 textContent，不重建 DOM，避免破坏事件绑定与生成结果展示）
      const el = canvasEl.querySelector(`.node[data-node-id="${shotFrameNode.id}"]`);
      if(!el) return;
      const descEl = el.querySelector('.shot-frame-desc-display');
      if(descEl) descEl.textContent = shotFrameNode.data.description;
      const metaEl = el.querySelector('.shot-frame-meta');
      if(metaEl){
        const durLabel = window.t ? window.t('shot_frame_duration_label') : '时长:';
        const secLabel = window.t ? window.t('shot_frame_seconds') : '秒';
        metaEl.textContent = `${durLabel} ${shotFrameNode.data.duration}${secLabel} | ${shotFrameNode.data.shotType} | ${shotFrameNode.data.cameraMovement}`;
      }

      // 同步更新节点标题（shot_number 重排后避免与新节点标题重名）；保留 svg 图标，只更新文本
      // 标题：手动添加（N_x 格式）用 shot_id；LLM 生成的用 shot_number
      const _updSid = String(shot.shot_id || '');
      const newTitle = /^\d+_\d+$/.test(_updSid) ? _updSid : (shot.shot_number ? String(shot.shot_number) : (shotFrameNode.title || '分镜图'));
      if(newTitle !== shotFrameNode.title){
        shotFrameNode.title = newTitle;
        const titleEl = el.querySelector('.node-title');
        if(titleEl){
          const titleText = window.t ? window.t('shot_frame_title', { title: newTitle }) : `分镜: ${newTitle}`;
          titleEl.setAttribute('data-i18n-params', JSON.stringify({ title: newTitle }));
          const svg = titleEl.querySelector('svg');
          if(svg){
            let nxt = svg.nextSibling;
            while(nxt){ const n = nxt.nextSibling; nxt.remove(); nxt = n; }
            titleEl.appendChild(document.createTextNode(titleText));
          } else {
            titleEl.textContent = titleText;
          }
        }
      }
    }

    // 增量同步核心：按 shots 数组同步 shot_frame 节点
    // 新建缺失节点、就地更新已有节点（保留生成结果与提示词）、按 shots 顺序重排、孤儿节点保留并提示
    async function syncShotFramesToShots(shotGroupNodeId, shotGroupNode, options){
      const isAsync = options && options.isAsync;
      const shots = shotGroupNode.data.shots || [];
      if(shots.length === 0){
        if(!isAsync) showToast('幕中没有分镜数据', 'warning');
        return [];
      }

      // 按数组顺序处理（用户编辑后的显示顺序），不再按 shot_number 排序：
      // addNewShot/deleteShot 已不 renumber，LLM 生成的 shot_number（全局值如 5/6/7）需保留用于标题显示，
      // 数组顺序即正确顺序。
      const sortedShots = [...shots];

      // 建立 shot_id → 已有 shot_frame 节点 的映射，并收集所有关联节点（用于孤儿检测）
      const existingMap = new Map();
      const connectedNodes = [];
      const existingConnections = state.connections.filter(c => c.from === shotGroupNodeId);
      existingConnections.forEach(conn => {
        const targetNode = state.nodes.find(n => n.id === conn.to);
        if(targetNode && targetNode.type === 'shot_frame'){
          const shotId = targetNode.data.shotId || (targetNode.data.shotJson && targetNode.data.shotJson.shot_id);
          if(shotId){
            existingMap.set(shotId, targetNode);
          }
          connectedNodes.push(targetNode);
        }
      });

      const SHOT_FRAME_GAP_Y = 120;  // 分镜节点之间的Y轴间距，与自动排列保持一致
      const targetX = shotGroupNode.x + 1200;

      // 遍历 shots：就地更新已有节点 或 新建缺失节点，并记录顺序用于重排
      const orderedNodes = [];
      const createdNodeIds = [];
      const matchedNodeIds = new Set();
      let updatedCount = 0;

      sortedShots.forEach((shot) => {
        const existing = existingMap.get(shot.shot_id);
        if(existing){
          updateShotFrameNodeBasic(existing, shot);
          matchedNodeIds.add(existing.id);
          orderedNodes.push(existing);
          updatedCount++;
        } else {
          // 每个分镜用自己的场景信息（同一分镜组内可能含不同场景）
          const shotLocationInfo = [];
          if(shot.db_location_id && shot.location_name){
            shotLocationInfo.push({
              name: shot.location_name,
              pic: shot.db_location_pic,
              id: shot.db_location_id
            });
          }
          const shotDataWithLocation = {
            ...shot,
            allLocationInfo: shotLocationInfo,
            scriptData: shotGroupNode.data.scriptData
          };
          const shotFrameNodeId = createShotFrameNode({
            x: targetX,
            y: 0,  // 临时位置，后面重新定位
            shotData: shotDataWithLocation,
            model: shotGroupNode.data.model,
            videoModel: shotGroupNode.data.videoModel,
            checkCollision: false
          });
          createdNodeIds.push(shotFrameNodeId);
          matchedNodeIds.add(shotFrameNodeId);
          const newNode = state.nodes.find(n => n.id === shotFrameNodeId);
          if(newNode) orderedNodes.push(newNode);
          state.connections.push({
            id: state.nextConnId++,
            from: shotGroupNodeId,
            to: shotFrameNodeId
          });
        }
      });

      // 孤儿节点：关联但不在当前 shots 里的（用户已从列表移除），保留不删除
      const orphanNodes = connectedNodes.filter(n => !matchedNodeIds.has(n.id));

      // 等待布局（异步版用 rAF）或强制同步布局（同步版），确保能测量节点实际高度
      if(isAsync){
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      } else {
        void document.body.offsetHeight;
      }

      // 按 shots 顺序重排有效节点的 y 坐标，孤儿节点移到末尾避免重叠
      // 起点 nextY 的确定（关键：避免剧本拆分时多个分镜组的分镜节点重合）：
      //  - 增量同步（updatedCount>0，如"生成分镜"按钮就地更新已有节点）：在本分镜组旁边重排，从 group.y 起。
      //  - 全新建（updatedCount===0，如剧本拆分批量生成）：多个分镜组共享同一 targetX 列（x+1200），
      //    且 parse-script 给每组预留的纵向空间（shotCount*700）小于实际分镜节点堆叠高度，
      //    故需扫描同列已有 shot_frame 的最大底部，从其下方起排，避免覆盖前一组节点。
      let nextY;
      if(updatedCount > 0){
        nextY = shotGroupNode.y;
      } else {
        const processedIdSet = new Set();
        orderedNodes.forEach(n => { if(n) processedIdSet.add(n.id); });
        orphanNodes.forEach(n => { if(n) processedIdSet.add(n.id); });
        let globalMaxBottom = shotGroupNode.y;
        state.nodes.forEach(n => {
          if(n.type === 'shot_frame' && !processedIdSet.has(n.id) && Math.abs(n.x - targetX) < 200){
            const otherEl = canvasEl.querySelector(`.node[data-node-id="${n.id}"]`);
            const h = otherEl ? otherEl.offsetHeight : 500;
            const bottom = n.y + h;
            if(bottom > globalMaxBottom) globalMaxBottom = bottom;
          }
        });
        nextY = globalMaxBottom > shotGroupNode.y
          ? globalMaxBottom + SHOT_FRAME_GAP_Y
          : shotGroupNode.y;
      }
      const reposition = (node) => {
        if(!node) return;
        node.x = targetX;
        node.y = Math.max(MIN_NODE_Y, nextY);
        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        if(el){
          el.style.left = node.x + 'px';
          el.style.top = node.y + 'px';
          nextY = node.y + el.offsetHeight + SHOT_FRAME_GAP_Y;
        } else {
          nextY += 600 + SHOT_FRAME_GAP_Y;
        }
      };
      orderedNodes.forEach(reposition);
      orphanNodes.forEach(reposition);

      renderAllConnections();
      safeAutoSave();

      // 提示
      const parts = [];
      if(createdNodeIds.length > 0) parts.push(`新增 ${createdNodeIds.length} 个`);
      if(updatedCount > 0) parts.push(`更新 ${updatedCount} 个`);
      if(orphanNodes.length > 0) parts.push(`保留 ${orphanNodes.length} 个已从列表移除的节点`);
      const msg = parts.length > 0 ? `分镜已同步：${parts.join('、')}` : '分镜已是最新，无需同步';
      showToast(msg, (createdNodeIds.length > 0 || updatedCount > 0) ? 'success' : 'info');

      return createdNodeIds;
    }

    // 生成分镜图节点 - 独立分镜模式（增量同步；同步包装器，保留原签名）
    function generateShotFramesIndependent(shotGroupNodeId, shotGroupNode){
      // isAsync=false：核心内部用 void offsetHeight 强制同步布局，函数体内无 await，所有工作在本次调用中同步完成
      syncShotFramesToShots(shotGroupNodeId, shotGroupNode, { isAsync: false }).catch(err => {
        console.error('[分镜同步] 同步失败:', err);
        showToast('分镜同步失败: ' + (err && err.message || err), 'error');
      });
    }

    // 生成分镜图节点 - 独立分镜模式（异步版本，用于自动批量生成；增量同步）
    async function generateShotFramesIndependentAsync(shotGroupNodeId, shotGroupNode){
      return await syncShotFramesToShots(shotGroupNodeId, shotGroupNode, { isAsync: true });
    }

    // 将视频提示词JSON转换为可读文本格式
    function convertVideoPromptToText(jsonString){
      try {
        const data = JSON.parse(jsonString);
        const t = window.t || ((key, params) => {
          // 回退：从 key 中提取默认值
          const fallbacks = {
            'video_prompt_duration': '时长：{value}秒',
            'video_prompt_time': '时间：{value}',
            'video_prompt_weather': '天气：{value}',
            'video_prompt_scene': '场景：{value}',
            'video_prompt_shot_type': '镜头类型：{value}',
            'video_prompt_camera_movement': '运镜：{value}',
            'video_prompt_description': '描述：{value}',
            'video_prompt_scene_detail': '场景细节：{value}',
            'video_prompt_action': '动作：{value}',
            'video_prompt_mood': '情绪：{value}',
            'video_prompt_dialogue': '对话：{value}',
            'video_prompt_audio_notes': '音频备注：{value}',
            'video_prompt_environment_sound': '环境音：{value}',
            'video_prompt_background_music': '背景音乐：{value}'
          };
          let str = fallbacks[key] || key;
          if(params) Object.keys(params).forEach(k => { str = str.replace(`{${k}}`, params[k]); });
          return str;
        });

        let text = '';
        if(data.duration) text += t('video_prompt_duration', { value: data.duration }) + '\n';
        if(data.time_of_day) text += t('video_prompt_time', { value: data.time_of_day }) + '\n';
        if(data.weather) text += t('video_prompt_weather', { value: data.weather }) + '\n';
        if(data.location_name) text += t('video_prompt_scene', { value: data.location_name }) + '\n';
        if(data.shot_type) text += t('video_prompt_shot_type', { value: data.shot_type }) + '\n';
        if(data.camera_movement) text += t('video_prompt_camera_movement', { value: data.camera_movement }) + '\n';
        if(data.description) text += t('video_prompt_description', { value: data.description }) + '\n';
        if(data.scene_detail) text += t('video_prompt_scene_detail', { value: data.scene_detail }) + '\n';
        if(data.action) text += t('video_prompt_action', { value: data.action }) + '\n';
        if(data.mood) text += t('video_prompt_mood', { value: data.mood }) + '\n';
        if(data.dialogue && Array.isArray(data.dialogue) && data.dialogue.length > 0){
          text += t('video_prompt_dialogue', { value: data.dialogue.map(d => `${d.character_name}: ${d.text}`).join('; ') }) + '\n';
        }
        if(data.audio_notes) text += t('video_prompt_audio_notes', { value: data.audio_notes }) + '\n';
        if(data.environment_sound) text += t('video_prompt_environment_sound', { value: data.environment_sound }) + '\n';
        if(data.background_music) text += t('video_prompt_background_music', { value: data.background_music }) + '\n';
        return text;
      } catch(e){
        console.error('Failed to convert video prompt to text:', e);
        return jsonString;
      }
    }

    // 角色图片选择下拉的全局追踪（跨节点共享，确保同时只有一个实例）
    let _activeCharImgDropdown = null;
    let _activeCharImgCloseHandler = null;

    // 分镜图节点
    function createShotFrameNode(opts){
      const id = state.nextNodeId++;
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
                  <img class="shot-frame-preview-image" src="${node.data.previewImageUrl || ''}" style="max-width: 100%; max-height: 160px; object-fit: contain; border-radius: 6px; cursor: pointer; display: ${node.data.previewImageUrl ? 'block' : 'none'};" />
                </div>
              </div>
              <div class="field field-always-visible shot-frame-image-field" style="display:${node.data.imageUrl ? 'flex' : 'none'};">
                <img class="shot-frame-image" src="${node.data.imageUrl}" style="max-width: 100%; max-height: 160px; object-fit: contain; border-radius: 6px; cursor: pointer;" />
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
            item.innerHTML = `<img src="${opt.url}" style="width:16px;height:16px;object-fit:cover;border-radius:2px;margin-right:6px;vertical-align:middle;">${opt.label}${opt.angle !== 'custom' ? '(' + opt.angle + ')' : ''}`;
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
          }
        };
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
          }
        };
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
            mainItem.innerHTML = `<img src="${getThumbnailUrl(mainOpt.url, 40)}" style="width:16px;height:16px;object-fit:cover;border-radius:2px;margin-right:6px;vertical-align:middle;">主图（默认）`;
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
            item.innerHTML = `<img src="${getThumbnailUrl(opt.url, 40)}" style="width:16px;height:16px;object-fit:cover;border-radius:2px;margin-right:6px;vertical-align:middle;">${opt.label}`;
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

      // 支持 / 键触发角色列表（分镜节点提示词放大窗口）
      if(opts && opts.enableCharacterDropdown && opts.nodeId != null){
        const dropdownKey = opts.dropdownKey || 'imageprompt';
        expandTextarea.addEventListener('keydown', (e) => {
          if(e.key === '/') {
            e.preventDefault();
            showCharacterDropdownForImagePrompt(opts.nodeId, expandTextarea, expandTextarea.selectionStart, dropdownKey);
          }
        });
        expandTextarea.addEventListener('input', () => {
          hideCharacterDropdownForImagePrompt(opts.nodeId, dropdownKey);
        });
        expandTextarea.addEventListener('blur', () => {
          setTimeout(() => hideCharacterDropdownForImagePrompt(opts.nodeId, dropdownKey), 200);
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

        const videoGenMode = shotGroupNode.data.videoGenMode || 'first_last_frame';

        // 首尾帧模式下检查是否有首帧图片（参考模式不需要首帧图）
        if(videoGenMode === 'first_last_frame') {
          const nodesWithImage = shotFrameNodes.filter(n => n.data.previewImageUrl || n.data.imageUrl);
          if(nodesWithImage.length === 0) {
            showToast('分镜节点没有首帧图片，请先生成分镜图', 'warning');
            return;
          }
        }
        
        const generateBtn = document.querySelector(`.node[data-node-id="${shotGroupNodeId}"] .shot-group-generate-video-btn`);
        const mergeStatusEl = document.querySelector(`.node[data-node-id="${shotGroupNodeId}"] .grid-merge-status`);
        if(!generateBtn) return;
        
        setBtnLoading(generateBtn, '生成中...');
        
        const firstShotFrame = shotFrameNodes[0];
        const duration = shotGroupNode.data.videoDuration || 5;
        const count = shotGroupNode.data.videoDrawCount || 1;
        const videoModel = shotGroupNode.data.videoModel || 'wan22';
        const userId = localStorage.getItem('user_id') || '1';
        const authToken = localStorage.getItem('auth_token') || '';

        // ===== 根据视频生成模式收集图片 =====
        let imageUrl; // 首尾帧模式使用
        let referenceImageUrls = []; // 参考模式使用
        let refPromptSuffix = []; // 参考图描述文字
        let useTextToVideo = false; // 降级标记

        if(videoGenMode === 'multi_reference') {
          // ===== 参考生视频模式：收集角色/场景/道具参考图 =====
          if(mergeStatusEl) {
            mergeStatusEl.style.color = '#3b82f6';
            mergeStatusEl.textContent = '正在收集参考图片...';
          }
          generateBtn.textContent = '收集参考图...';

          const { referenceImageUrls: refUrls, promptSuffix: _refPromptSuffix } = await collectReferenceImagesForGrid(shotFrameNodes);
          referenceImageUrls = refUrls;
          refPromptSuffix = _refPromptSuffix || [];

          if(referenceImageUrls.length > 0) {
            console.log(`[分镜组视频] 参考模式：收集到 ${referenceImageUrls.length} 张参考图`);
            if(mergeStatusEl) {
              mergeStatusEl.style.color = '#22c55e';
              mergeStatusEl.textContent = `收集到 ${referenceImageUrls.length} 张参考图，正在生成视频...`;
            }
          } else {
            // 无参考图，降级为文生视频
            console.log('[分镜组视频] 参考模式：无参考图，降级为文生视频');
            useTextToVideo = true;
            if(mergeStatusEl) {
              mergeStatusEl.style.color = '#f59e0b';
              mergeStatusEl.textContent = '无参考图，回退为文生视频模式...';
            }
          }
        } else {
          // ===== 首尾帧模式：宫格合并 =====
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

        // 参考模式下追加参考图描述（如"图1是土豆仔，图2是绿色青椒帽。"）
        if(videoGenMode === 'multi_reference' && refPromptSuffix && refPromptSuffix.length > 0 && !useTextToVideo) {
          finalVideoPrompt = `${finalVideoPrompt}\n\n${refPromptSuffix.join('，')}。`;
        }

        // 参考模式下追加画风描述（首帧模式不添加，保持原状）
        if(videoGenMode === 'multi_reference' && state.style && state.style.name) {
          finalVideoPrompt = `${finalVideoPrompt}\n\n视频风格：${state.style.name}`;
          if(state.style.compositionPreference) {
            finalVideoPrompt = `${finalVideoPrompt}\n构图倾向：${state.style.compositionPreference}`;
          }
        }

        generateBtn.textContent = '提交视频...';
        showToast(`正在生成 ${count} 个视频...`, 'info');

        // 根据模式调用不同的API
        let res;

        if(useTextToVideo) {
          // ===== 降级：文生视频 =====
          const t2vTaskId = TaskConfig.getTaskIdByKey(videoModel || 'wan22', 'text_to_video');
          if(!t2vTaskId){
            throw new Error(`模型 ${videoModel} 不支持文生视频，请添加参考图（角色/场景/道具）或切换支持文生视频的模型`);
          }

          const form = new FormData();
          form.append('prompt', finalVideoPrompt);
          form.append('duration_seconds', duration);
          form.append('count', count);
          form.append('ratio', state.ratio || '9:16');
          form.append('task_id', t2vTaskId);
          appendAuthToForm(form);

          res = await fetch('/api/ai-app-run', { method: 'POST', body: form });
        } else if(videoGenMode === 'multi_reference') {
          // ===== 参考生视频模式 =====
          const refTaskId = TaskConfig.getTaskIdByKey(videoModel || 'wan22', 'image_to_video');
          if(!refTaskId){
            throw new Error(`未找到视频模型 ${videoModel} 对应的任务配置`);
          }

          const form = new FormData();
          form.append('image_urls', referenceImageUrls.join(','));
          form.append('image_mode', 'multi_reference');
          form.append('prompt', finalVideoPrompt);
          form.append('duration_seconds', duration);
          form.append('count', count);
          form.append('ratio', state.ratio || '9:16');
          form.append('task_id', refTaskId);
          appendAuthToForm(form);

          res = await fetch('/api/ai-app-run-image', { method: 'POST', body: form });
        } else {
          // ===== 首尾帧模式（原有逻辑） =====
          const taskId9 = TaskConfig.getTaskIdByKey(videoModel || 'wan22', 'image_to_video');
          if(!taskId9){
            throw new Error(`未找到视频模型 ${videoModel} 对应的任务配置`);
          }

          const form = new FormData();
          form.append('image_urls', imageUrl);
          form.append('prompt', finalVideoPrompt);
          form.append('duration_seconds', duration);
          form.append('count', count);
          form.append('ratio', state.ratio || '9:16');
          form.append('task_id', taskId9);
          appendAuthToForm(form);

          res = await fetch('/api/ai-app-run-image', { method: 'POST', body: form });
        }
        
        const resText5 = await res.text();
        let data;
        try { data = JSON.parse(resText5); } catch(e) {
          throw new Error(`API返回异常 (HTTP ${res.status}): ${resText5.slice(0, 200) || '空响应'}`);
        }
        
        if(!data.project_ids || data.project_ids.length === 0){
          throw new Error(data.detail || data.message || '提交任务失败');
        }
        
        const projectIds = data.project_ids;
        showToast(`视频生成任务已提交，正在处理...`, 'info');
        
        // 立即创建对应数量的视频节点并绑定 project_id
        const createdVideoNodeIds = [];
        const videoCount = projectIds.length;
        
        // 使用源节点实际宽度计算偏移
        const firstShotFrameEl = canvasEl.querySelector(`.node[data-node-id="${firstShotFrame.id}"]`);
        const firstShotFrameWidth = firstShotFrameEl ? firstShotFrameEl.offsetWidth : 300;
        for(let i = 0; i < videoCount; i++){
          const offsetY = i * 280;
          const newVideoNodeId = createVideoNode({
            x: firstShotFrame.x + firstShotFrameWidth + 60,
            y: firstShotFrame.y + offsetY,
            checkCollision: true
          });
          
          const newVideoNode = state.nodes.find(n => n.id === newVideoNodeId);
          if(newVideoNode){
            newVideoNode.data.name = videoCount > 1 ? `幕视频${i + 1}` : '幕视频';
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

        renderConnections();
        renderAllConnections();
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
            
            showToast(`幕视频生成成功！`, 'success');
            generateBtn.textContent = '生成视频';
            generateBtn.disabled = false;
            
            safeAutoSave()
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

    // 逐个生成所有分镜视频
    async function generateAllShotFrameVideos(shotGroupNodeId, shotGroupNode) {
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

        const groupGenMode = shotGroupNode.data.videoGenMode || 'first_last_frame';

        // 检查所有分镜节点是否就绪（首帧模式需要图片，参考模式不需要）
        const nodesReady = shotFrameNodes.filter(n => {
          return groupGenMode === 'multi_reference' || n.data.previewImageUrl || n.data.imageUrl;
        });
        if(nodesReady.length === 0) {
          showToast('分镜节点没有首帧图片，请先生成分镜图', 'warning');
          return;
        }

        const batchGenerateBtn = document.querySelector(`.node[data-node-id="${shotGroupNodeId}"] .shot-group-batch-generate-btn`);
        if(!batchGenerateBtn) return;

        // 首次使用提示
        const batchTipKey = 'shot_group_batch_tip_shown';
        if(!localStorage.getItem(batchTipKey)) {
          showToast('逐个生成：每个分镜独立生成视频，支持所有模型但可能浪费时长', 'info', 5000);
          localStorage.setItem(batchTipKey, 'true');
        }

        setBtnLoading(batchGenerateBtn, '批量生成中...');

        let successCount = 0;
        let failCount = 0;

        for(let i = 0; i < shotFrameNodes.length; i++) {
          const shotFrameNode = shotFrameNodes[i];

          // 使用分镜组的生成模式覆盖子节点的模式
          const effectiveMode = groupGenMode;

          // 首帧模式需要有预览图，参考模式不需要
          if(effectiveMode === 'first_last_frame' && !shotFrameNode.data.previewImageUrl && !shotFrameNode.data.imageUrl) {
            console.warn(`分镜节点 ${shotFrameNode.id} 没有预览图且为首帧模式，跳过`);
            failCount++;
            continue;
          }

          try {
            showToast(`正在生成 ${i + 1}/${shotFrameNodes.length} 分镜视频...`, 'info');

            // 将分镜组的生成模式同步到子节点
            shotFrameNode.data.videoMode = effectiveMode;

            // 首帧模式从分镜组继承视频模型；参考模式保持子节点自己的模型
            if(effectiveMode !== 'multi_reference') {
              shotFrameNode.data.videoModel = shotGroupNode.data.videoModel || shotFrameNode.data.videoModel;
            }

            await generateShotFrameVideo(shotFrameNode.id, shotFrameNode);
            successCount++;
          } catch(error) {
            console.error(`生成分镜视频失败:`, error);
            failCount++;
          }
        }

        setBtnReady(batchGenerateBtn, '逐个生成视频');

        if(successCount > 0) {
          showToast(`批量生成完成！成功 ${successCount} 个，失败 ${failCount} 个`, 'success');
        } else {
          showToast('批量生成失败，请检查分镜节点配置', 'error');
        }

      } catch(error) {
        console.error('Generate all shot frame videos error:', error);
        showToast(`批量生成失败: ${error.message}`, 'error');

        const batchGenerateBtn = document.querySelector(`.node[data-node-id="${shotGroupNodeId}"] .shot-group-batch-generate-btn`);
        if(batchGenerateBtn) {
          setBtnReady(batchGenerateBtn, '逐个生成视频');
        }
      }
    }

    // 显示角色选择下拉框（用于图片提示词，使用 state.worldCharacters）
    function showCharacterDropdownForImagePrompt(nodeId, textarea, cursorPos, dropdownKey = 'imageprompt') {
      const dropdownId = `character-dropdown-${dropdownKey}-${nodeId}`;
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
    function hideCharacterDropdownForImagePrompt(nodeId, dropdownKey = 'imageprompt') {
      const dropdown = document.getElementById(`character-dropdown-${dropdownKey}-${nodeId}`);
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
