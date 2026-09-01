    // ============ 驱动状态检查 ============

    // 内容审核错误友好中文（与 utils/content_moderation_error.py / 设计文档 A 对齐；历史英文 reason 兜底）
    function friendlyContentModerationMessage(errorMsg) {
      // 委托共享模块 web/js/content_violation.js（video_workflow 页面已加载）；
      // 模块不存在时（如 Vitest 测试环境）走下方本地规则兜底
      if (typeof window !== 'undefined' && window.ContentViolation && typeof window.ContentViolation.describe === 'function') {
        return window.ContentViolation.describe(errorMsg);
      }
      if(!errorMsg) return null;
      const msg = String(errorMsg);
      if(msg.startsWith('内容审核未通过')) return msg;

      const lower = msg.toLowerCase();
      const isModeration = (
        lower.includes('safety system') ||
        lower.includes('safety policy') ||
        lower.includes('moderation_blocked') ||
        lower.includes('invalid_prompt') ||
        lower.includes('sensitivecontent') ||
        lower.includes('sensitive content') ||
        lower.includes('sensitive information') ||
        lower.includes('content policy') ||
        lower.includes('content_filter') ||
        lower.includes('safety_violations') ||
        lower.includes('image generation blocked') ||
        lower.includes('generation was stopped') ||
        lower.includes('prohibited content') ||
        lower.includes('prohibited material') ||
        lower.includes('copyright') ||
        lower.includes('trademark') ||
        lower.includes('policy violation') ||
        lower.includes('image_safety') ||
        lower.includes('image_other') ||
        msg.includes('内容审核') ||
        msg.includes('敏感内容') ||
        msg.includes('违禁')
      );
      if(!isModeration) return null;

      if(/copyright|trademark|IMAGE_OTHER/i.test(msg)) {
        return '内容审核未通过（版权/商标）：提示词或参考内容可能涉及受保护形象/标识，请修改后重试';
      }

      const map = {
        violence: '暴力', sexual: '色情', self_harm: '自残', 'self-harm': '自残',
        hate: '仇恨', harassment: '骚扰', illegal: '违法', drugs: '毒品',
        weapon: '武器', weapons: '武器', child: '未成年人相关', political: '政治敏感',
        safety: '安全策略', prohibited: '违禁内容', copyright: '版权/商标', trademark: '版权/商标'
      };
      const labels = [];
      const violMatch = msg.match(/safety_violations\s*=\s*\[([^\]]*)\]/i);
      if(violMatch) {
        violMatch[1].split(',')
          .map(s => s.trim().replace(/["']/g, '').toLowerCase())
          .filter(Boolean)
          .forEach(v => labels.push(map[v] || v));
      }
      const geminiMatch = msg.match(/image\s+generation\s+blocked\s*\[([^\]]+)\]/i);
      if(geminiMatch) {
        const reason = geminiMatch[1].toUpperCase();
        if(reason.includes('SAFETY')) labels.push('安全策略');
        else if(reason.includes('PROHIBITED')) labels.push('违禁内容');
      }
      const violationLabel = [...new Set(labels)].join('、');

      let action;
      if(
        /invalid_prompt/i.test(msg) ||
        /InputTextSensitive/i.test(msg) ||
        /IMAGE_PROHIBITED|PROHIBITED_CONTENT/i.test(msg) ||
        (/modify your prompt/i.test(msg) && !/generated image was blocked/i.test(msg))
      ) {
        action = '提示词包含敏感/违禁内容，请修改提示词后重试';
      } else if(
        /InputImageSensitive/i.test(msg) ||
        /reference image/i.test(msg)
      ) {
        action = '参考图片包含敏感内容，请更换参考图后重试';
      } else if(
        /OutputImageSensitive|OutputVideoSensitive|IMAGE_SAFETY/i.test(msg) ||
        /generated image was blocked|output image may contain/i.test(msg)
      ) {
        action = '生成结果可能包含敏感内容，请调整提示词或参考图后重试';
      } else {
        action = '请检查提示词和参考图后重试';
      }

      if(violationLabel) {
        return `内容审核未通过（${violationLabel}）：${action}`;
      }
      return `内容审核未通过：${action}`;
    }

    // 截断过长的错误信息，提取关键错误内容
    function truncateErrorMessage(errorMsg, maxLength = 120) {
      if(!errorMsg) return errorMsg;
      let msg = String(errorMsg);

      const moderationMsg = friendlyContentModerationMessage(msg);
      if(moderationMsg) {
        return moderationMsg.length > maxLength
          ? moderationMsg.substring(0, maxLength) + '...'
          : moderationMsg;
      }

      // 如果包含 JSON 错误响应，尝试提取关键错误信息
      if(msg.includes('"error"') || msg.includes('"message"')) {
        try {
          // 尝试提取 JSON 中的 message 或 failureReasons
          const messageMatch = msg.match(/"message"\s*:\s*"([^"]+)"/);
          if(messageMatch) {
            const nestedModeration = friendlyContentModerationMessage(messageMatch[1]);
            if(nestedModeration) return nestedModeration;
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

    // 通用函数：未配置供应商的模型从下拉移除；当前已保存值保留并标「未配置」
    function applyDriverStatusToSelect(selectEl, savedValue) {
      if(!selectEl) return;

      const driverStatus = typeof getDriverStatusConfig === 'function' ? getDriverStatusConfig() : {};

      if(!driverStatus || Object.keys(driverStatus).length === 0) return;

      const keepValue = savedValue != null && savedValue !== ''
        ? String(savedValue)
        : String(selectEl.value || '');

      selectEl.querySelectorAll('option').forEach(option => {
        const taskType = window.TaskConfig ? window.TaskConfig.getTaskIdByKey(option.value) : null;
        const available = window.TaskConfig && window.TaskConfig.isDriverAvailable
          ? window.TaskConfig.isDriverAvailable(taskType, driverStatus)
          : (!taskType || !driverStatus[taskType] || driverStatus[taskType].available !== false);
        if (available) return;
        if (String(option.value) === keepValue) {
          option.disabled = true;
          if(!option.textContent.includes('(未配置)')) {
            option.textContent += ' (未配置)';
          }
          return;
        }
        option.remove();
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
      const driverStatus = typeof getDriverStatusConfig === 'function' ? getDriverStatusConfig() : {};
      const taskType = window.TaskConfig ? window.TaskConfig.getTaskIdByKey(modelValue) : null;
      if (window.TaskConfig && window.TaskConfig.isDriverAvailable) {
        return window.TaskConfig.isDriverAvailable(taskType, driverStatus);
      }
      if(!driverStatus || Object.keys(driverStatus).length === 0) return true;
      if(!taskType) return true;
      return driverStatus[taskType]?.available !== false;
    }

    function filterVideoOptionsByDriver(options) {
      const list = options || [];
      if (window.TaskConfig && window.TaskConfig.filterAvailableModelOptions) {
        const driverStatus = typeof getDriverStatusConfig === 'function' ? getDriverStatusConfig() : {};
        return window.TaskConfig.filterAvailableModelOptions(list, driverStatus);
      }
      return list.filter((opt) => isModelAvailable(opt.value));
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
        const shotData = shotNode.data.shotJson || {};

        // 1. 提取角色名并获取参考图URL（图片提示词 ∪ 生视频提示词）
        const shotCharacterNames = typeof mergeShotCharacterNames === 'function'
          ? mergeShotCharacterNames(shotNode)
          : (function() {
              const names = [];
              const pattern = /【【([^】]+)】】/g;
              const texts = [
                shotNode.data.imagePrompt || '',
                shotNode.data.videoPromptText || shotNode.data.videoPrompt || ''
              ];
              texts.forEach(function(text) {
                pattern.lastIndex = 0;
                let match;
                while ((match = pattern.exec(text)) !== null) {
                  const name = match[1].trim();
                  if (name && names.indexOf(name) === -1) names.push(name);
                }
              });
              return names;
            })();
        for (const characterName of shotCharacterNames) {
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
    let shotGroupDetailHasNewShot = false;  // 查看详情弹窗内是否新建过分镜（关闭时提醒点击"生成分镜"）
    
    const shotDetailModal = document.getElementById('shotDetailModal');
    const shotDetailModalClose = document.getElementById('shotDetailModalClose');
    const shotDetailModalContent = document.getElementById('shotDetailModalContent');
    const shotDetailModalTitle = document.getElementById('shotDetailModalTitle');
    let currentShotDetailContext = null;

    function openShotGroupModal(shotGroupData, nodeId){
      currentShotGroupNodeId = nodeId;
      shotGroupDetailHasNewShot = false;
      shotGroupModalTitle.textContent = `幕详情 - ${shotGroupData.groupName || '未命名'}`;
      shotGroupModalContent.innerHTML = renderShotGroupTable(shotGroupData, nodeId);
      shotGroupModal.classList.add('show');
      shotGroupModal.setAttribute('aria-hidden', 'false');
    }

    function closeShotGroupModal(){
      // 新建过分镜时，提醒用户点击幕节点上的"生成分镜"按钮同步到画布（复用已有 flashing 特效）
      // 注意：必须在置空 currentShotGroupNodeId 之前查询按钮
      if(shotGroupDetailHasNewShot && currentShotGroupNodeId){
        const detailCanvasEl = document.getElementById('canvas');
        const genBtn = detailCanvasEl && detailCanvasEl.querySelector(`.node[data-node-id="${currentShotGroupNodeId}"] .shot-group-generate-btn`);
        if(genBtn){
          genBtn.classList.remove('flashing');
          void genBtn.offsetWidth;  // 强制 reflow，重启动画
          genBtn.classList.add('flashing');
          genBtn.addEventListener('animationend', () => {
            genBtn.classList.remove('flashing');
          }, { once: true });
        }
      }
      shotGroupDetailHasNewShot = false;
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
          <div style="display:flex; justify-content:center; align-items:center; gap: 8px; margin: 10px 0;">
            <button class="mini-btn secondary insert-shot-btn" data-insert-index="${insertIndex}" type="button" title="快速插入（继承相邻分镜共性字段）">+ 插入分镜</button>
            <button class="mini-btn primary insert-shot-smart-btn" data-insert-index="${insertIndex}" type="button" title="智能插入（AI 分析前后分镜自动填充）">✦ 智能插入</button>
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
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">视频提示词</label>
              <textarea class="shot-field" data-field="description" style="width: 100%; padding: 6px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px; min-height: 50px; resize: vertical;">${escapeHtml(shot.description || '')}</textarea>
            </div>
            <div style="grid-column: 1 / -1;">
              <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px;">图片提示词</label>
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

      // 绑定智能插入按钮事件
      const smartInsertBtns = shotGroupEditModalContent.querySelectorAll('.insert-shot-smart-btn');
      smartInsertBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const idx = parseInt(btn.dataset.insertIndex);
          addNewShotSmart(idx);
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

    // 智能插入核心：调用后端 API，返回 AI 生成的分镜数据（失败时抛错）
    async function requestSmartInsertShot(node, prevShot, nextShot){
      const requestBody = {
        prev_shot: prevShot,
        next_shot: nextShot,
        group_id: node.data.groupId || node.data.group_id || '',
        script_data: node.data.scriptData || node.data.script_data || {},
        script_content: node.data.scriptContent || '',  // 原始剧本内容
        world_id: state.defaultWorldId || ''  // 从工作流状态获取世界 ID
      };

      const response = await fetch('/api/video-workflow/smart-insert-shot', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(window.getAuthHeaders ? window.getAuthHeaders() : {})
        },
        body: JSON.stringify(requestBody)
      });

      const result = await response.json();
      if(result.success && result.shot) return result.shot;
      throw new Error(result.error || '智能插入失败');
    }

    // 基于 AI 返回组装新分镜对象（生成唯一 shot_id、继承相邻分镜共性字段）
    function buildSmartInsertNewShot(aiShot, shots, idx, prevShot, nextShot){
      const prevShotForId = shots[idx - 1];
      let base;
      if(prevShotForId){
        const prevId = String(prevShotForId.shot_id || '');
        const insertMatch = prevId.match(/^(\d+)_\d+$/);
        base = insertMatch ? insertMatch[1] : String(prevShotForId.shot_number || idx);
      } else {
        base = '0';
      }
      const idPrefix = base + '_';
      let maxSub = 0;
      shots.forEach(s => {
        const sid = String(s.shot_id || '');
        if(sid.startsWith(idPrefix)){
          const tail = sid.slice(idPrefix.length);
          if(/^\d+$/.test(tail)){
            const x = parseInt(tail, 10);
            if(x > maxSub) maxSub = x;
          }
        }
      });
      const newShotId = `${base}_smart_${maxSub + 1}`;

      return {
        ...aiShot,
        shot_id: newShotId,
        shot_number: aiShot.shot_number || (idx + 1),
        // 保留相邻分镜的共性字段（如果 AI 未返回）
        location_id: aiShot.location_id || prevShot?.location_id || nextShot?.location_id || '',
        db_location_id: aiShot.db_location_id || prevShot?.db_location_id || nextShot?.db_location_id || '',
        db_location_pic: aiShot.db_location_pic || prevShot?.db_location_pic || nextShot?.db_location_pic || '',
        location_name: aiShot.location_name || prevShot?.location_name || nextShot?.location_name || '',
        props: aiShot.props || []
      };
    }

    // 智能插入分镜：调用后端 API 自动生成新分镜属性
    async function addNewShotSmart(insertIndex){
      const node = state.nodes.find(n => n.id === currentEditingNodeId);
      if(!node) return;

      if(!Array.isArray(node.data.shots)) node.data.shots = [];
      const shots = node.data.shots;
      const idx = Math.max(0, Math.min(insertIndex, shots.length));
      const prevShot = shots[idx - 1] || null;
      const nextShot = shots[idx] || null;

      // 找到智能插入按钮并显示加载状态
      const smartBtn = shotGroupEditModalContent.querySelector(`.insert-shot-smart-btn[data-insert-index="${insertIndex}"]`);
      const originalText = smartBtn ? smartBtn.textContent : '';
      if(smartBtn){
        smartBtn.disabled = true;
        smartBtn.textContent = '⏳ AI 生成中...';
        smartBtn.style.opacity = '0.6';
      }

      try {
        const aiShot = await requestSmartInsertShot(node, prevShot, nextShot);
        const newShot = buildSmartInsertNewShot(aiShot, shots, idx, prevShot, nextShot);
        shots.splice(idx, 0, newShot);
        shotGroupEditModalContent.innerHTML = renderShotGroupEditForm(node.data);
        bindShotEditEvents();
        showToast(window.t ? window.t('smart_insert_success') : '智能插入成功', 'success');
      } catch (e) {
        console.error('智能插入失败:', e);
        showToast((window.t ? window.t('smart_insert_failed') : '智能插入失败') + ': ' + e.message, 'error');
        // 降级为普通插入
        addNewShot(insertIndex);
      } finally {
        // 恢复按钮状态（如果按钮还在 DOM 中）
        const currentSmartBtn = shotGroupEditModalContent.querySelector(`.insert-shot-smart-btn[data-insert-index="${insertIndex}"]`);
        if(currentSmartBtn){
          currentSmartBtn.disabled = false;
          currentSmartBtn.textContent = originalText;
          currentSmartBtn.style.opacity = '1';
        }
      }
    }

    // 表格快速创建分镜：在分镜组详情表格行间触发 AI 智能插入（与编辑弹窗共用 requestSmartInsertShot/buildSmartInsertNewShot）
    async function addNewShotSmartInTable(insertIndex){
      const nodeId = currentShotGroupNodeId;
      const node = state.nodes.find(n => n.id === nodeId);
      if(!node) return;

      if(!Array.isArray(node.data.shots)) node.data.shots = [];
      const shots = node.data.shots;
      const idx = Math.max(0, Math.min(insertIndex, shots.length));
      const prevShot = shots[idx - 1] || null;
      const nextShot = shots[idx] || null;

      const btn = shotGroupModalContent.querySelector(`.quick-insert-shot-btn[data-insert-index="${insertIndex}"]`);
      const originalText = btn ? btn.textContent : '';
      if(btn){
        btn.disabled = true;
        btn.textContent = '⏳ AI 生成中...';
        btn.style.opacity = '0.6';
      }

      try {
        const aiShot = await requestSmartInsertShot(node, prevShot, nextShot);
        const newShot = buildSmartInsertNewShot(aiShot, shots, idx, prevShot, nextShot);
        shots.splice(idx, 0, newShot);
        shotGroupDetailHasNewShot = true;  // 标记新建过分镜，关闭弹窗时闪烁"生成分镜"按钮
        // 刷新表格与幕节点卡片展示
        shotGroupModalContent.innerHTML = renderShotGroupTable(node.data, nodeId);
        updateShotGroupNodeDisplay(nodeId);
        safeAutoSave();
        showToast('智能创建分镜成功', 'success');
      } catch (e) {
        console.error('智能创建分镜失败:', e);
        showToast('智能创建分镜失败: ' + e.message, 'error');
        // 表格重新渲染前恢复按钮状态（按钮可能仍在 DOM 中）
        const currentBtn = shotGroupModalContent.querySelector(`.quick-insert-shot-btn[data-insert-index="${insertIndex}"]`);
        if(currentBtn){
          currentBtn.disabled = false;
          currentBtn.textContent = originalText;
          currentBtn.style.opacity = '1';
        }
      }
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
            locationCard.style.cssText = 'display: flex; gap: 12px; padding: 12px; margin-bottom: 8px;';
            
            locationCard.innerHTML = `
              ${location.reference_image ? `<img src="${escapeHtml(location.reference_image)}" style="width: 80px; height: 80px; object-fit: cover; border-radius: 6px; flex-shrink: 0;" alt="${escapeHtml(location.name)}" />` : '<div class="asset-item-placeholder" style="width: 80px; height: 80px; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 12px; flex-shrink: 0;">无图片</div>'}
              <div style="flex: 1; min-width: 0;">
                <div class="asset-item-title" style="font-weight: 600; margin-bottom: 4px;">${escapeHtml(location.name)}</div>
                <div class="asset-item-desc" style="font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(location.description || '暂无描述')}</div>
                <div class="asset-item-desc" style="font-size: 11px; margin-top: 4px;">ID: ${escapeHtml(String(location.id))}</div>
              </div>
            `;

            // hover 由 CSS .location-card:hover 处理，兼容暗色
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

      const editGroupIdEl = document.getElementById('editGroupId');
      if (!editGroupIdEl) return;
      const groupId = editGroupIdEl.value.trim();

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

      const shotsHtml = (node.data.shots || []).map((shot, idx) => {
        const duration = shot.duration ? `${shot.duration}秒` : '未知';
        return `
          <div style="padding: 8px; background: #f8f9fa; border-radius: 6px; margin-bottom: 6px; font-size: 12px;">
            <div style="font-weight: 700; margin-bottom: 4px;">${escapeHtml(shot.shot_id || `镜头${idx+1}`)} - ${escapeHtml(shot.description || '')}</div>
            <div style="color: #666; font-size: 11px;">时长: ${escapeHtml(duration)} | ${escapeHtml(shot.shot_type || '')} | ${escapeHtml(shot.camera_movement || '')}</div>
            <div style="color: #666; font-size: 11px; margin-top: 2px;">图片提示词: ${escapeHtml((shot.opening_frame_description || '').slice(0, 60))}...</div>
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
            const options = (typeof filterVideoOptionsByDriver === 'function'
              ? filterVideoOptionsByDriver(allOptions)
              : allOptions).filter(opt => {
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
          applyDriverStatusToSelect(shotGroupVideoModelEl, node.data.videoModel);
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
              <th style="padding: 10px; text-align: left; border: 1px solid #ddd;">视频提示词</th>
              <th style="padding: 10px; text-align: center; border: 1px solid #ddd; width: 100px;">操作</th>
            </tr>
          </thead>
          <tbody>
      `;

      // 行间快速创建分镜按钮（插入到当前行与下一行之间）
      const insertRowHtml = (insertIndex) => `
        <tr class="quick-insert-row">
          <td colspan="10" style="padding: 2px 10px; border: none; text-align: center;">
            <button class="mini-btn primary quick-insert-shot-btn" data-insert-index="${insertIndex}" type="button" title="AI 根据前后分镜上下文自动生成新分镜" style="padding: 2px 12px; font-size: 12px;">✦ 快速创建分镜</button>
          </td>
        </tr>
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
            <td style="padding: 10px; border: 1px solid #ddd; font-weight: 600;">${escapeHtml(shotId)}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${escapeHtml(duration)}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${escapeHtml(timeOfDay)}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${escapeHtml(weather)}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${escapeHtml(shotType)}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${escapeHtml(cameraMovement)}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${locationDisplay}</td>
            <td style="padding: 10px; border: 1px solid #ddd;">${propsDisplay}</td>
            <td style="padding: 10px; border: 1px solid #ddd; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(description)}</td>
            <td style="padding: 10px; border: 1px solid #ddd; text-align: center;">
              <button class="mini-btn view-shot-detail" data-shot-index="${index}" style="padding: 4px 8px; font-size: 12px; margin-right: 4px;">查看</button>
              <button class="mini-btn secondary select-shot-location" data-shot-index="${index}" style="padding: 4px 8px; font-size: 12px; margin-right: 4px;">选择场景</button>
              <button class="mini-btn secondary select-shot-props" data-shot-index="${index}" style="padding: 4px 8px; font-size: 12px;">选择道具</button>
            </td>
          </tr>
        `;
        // 在当前行与下一行之间插入快速创建分镜按钮
        if(index < shots.length - 1){
          html += insertRowHtml(index + 1);
        }
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

        // 绑定行间快速创建分镜按钮事件（AI 智能插入）
        document.querySelectorAll('.quick-insert-shot-btn').forEach(btn => {
          btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const insertIndex = parseInt(btn.dataset.insertIndex);
            await addNewShotSmartInTable(insertIndex);
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
        'description': '视频提示词',
        'opening_frame_description': '图片提示词',
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
                <div style="font-size: 12px; color: #6b7280;">ID: ${escapeHtml(String(shot.db_location_id))}</div>
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
                  <div style="font-size: 11px; color: #6b7280;">ID: ${escapeHtml(String(prop.id))}</div>
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
                <strong>${escapeHtml(d.character_name || d.character_id)}:</strong> ${escapeHtml(d.text || '')}
                <span style="color: #666; font-size: 12px;">(${escapeHtml(d.timestamp || '')})</span>
              </div>`;
            }).join('');
          } else if(typeof value === 'object'){
            value = escapeHtml(JSON.stringify(value, null, 2));
          } else {
            value = escapeHtml(value);
          }

          html += `
            <div style="margin-bottom: 15px; padding-bottom: 15px; border-bottom: 1px solid #eee;">
              <div style="font-weight: 600; color: #333; margin-bottom: 5px;">${escapeHtml(label)}</div>
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
      var propsModal = document.getElementById('propsModal');
      if (propsModal) propsModal.classList.remove('show');
      window.currentPropsSelectionContext = null;
      
      safeAutoSave()
      showToast(window.t ? window.t('prop_added') : '已添加道具', 'success');
    };

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
        // 断开 360全景 → 导演台 的环境连线时，清除导演台的全景环境
        if(conn && conn.portType === 'environment' && toNode && toNode.type === 'director_stage' && typeof window.handleDirectorStageEnvDisconnect === 'function'){
          window.handleDirectorStageEnvDisconnect(conn.from, toNode);
        }
        // 断开 图片/场景 → 360全景 的参考连线时，复位全景参考图缩略图（提示词保留不回滚）
        if(conn && conn.portType === 'panorama-source' && toNode && toNode.type === 'panorama'){
          const panoEl = canvasEl.querySelector(`.node[data-node-id="${conn.to}"]`);
          if(panoEl && typeof panoEl._updateSourceThumbnail === 'function'){
            panoEl._updateSourceThumbnail();
          }
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

    function renderConnections(tempLine, skipSizeUpdate){
      // 拖拽等高频路径通过 skipSizeUpdate 跳过画布尺寸重算（内部会遍历全部节点读取 offsetWidth），
      // 由调用方在交互结束时（mouseup / flushConnectionsRender）补偿一次
      if(!skipSizeUpdate) updateCanvasSize();

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



    // 剧本节点

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
            cellsHtml += `<div class="grid-cell" data-index="${i}"><img src="${escapeHtml(proxyImageUrl(imgUrl))}" /><span class="grid-cell-label">${i+1}</span></div>`;
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
            videoResolution: shotGroupNode.data.videoResolution,
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
            'video_prompt_description': '视频提示词：{value}',
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
        ${opts && opts.enableCharacterDropdown ? '<div style="margin-top: 8px; font-size: 12px; color: #9ca3af;">💡 按 <kbd style="background: #f3f4f6; padding: 1px 6px; border-radius: 4px; border: 1px solid #d1d5db; font-size: 11px;">/</kbd>、<kbd style="background: #f3f4f6; padding: 1px 6px; border-radius: 4px; border: 1px solid #d1d5db; font-size: 11px;">@</kbd> 或 <kbd style="background: #f3f4f6; padding: 1px 6px; border-radius: 4px; border: 1px solid #d1d5db; font-size: 11px;">、</kbd> 可选择角色插入到提示词中</div>' : ''}
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

      // 支持触发键唤起角色列表（分镜节点提示词放大窗口）
      // keydown 拦截：英文 '/'、英文 '@'、全角 '＠'（字符不入文本，直接弹下拉）；
      // 中文输入法下按 / 键会组合输入顿号 '、'、Shift+2 可能输入全角 '＠'，
      // 这类字符经 input 事件进入文本，检测后剔除触发符再弹下拉
      if(opts && opts.enableCharacterDropdown && opts.nodeId != null){
        const dropdownKey = opts.dropdownKey || 'imageprompt';
        const imeTriggerChars = ['、', '＠'];
        expandTextarea.addEventListener('keydown', (e) => {
          if(e.key === '/' || e.key === '@' || e.key === '＠') {
            e.preventDefault();
            showCharacterDropdownForImagePrompt(opts.nodeId, expandTextarea, expandTextarea.selectionStart, dropdownKey);
          }
        });
        expandTextarea.addEventListener('input', (e) => {
          // 中文输入法组合输入产生的触发符：剔除该字符后弹出下拉
          if(e.data && imeTriggerChars.includes(e.data)){
            const end = expandTextarea.selectionEnd;
            const start = Math.max(0, end - e.data.length);
            expandTextarea.value = expandTextarea.value.substring(0, start) + expandTextarea.value.substring(end);
            expandTextarea.setSelectionRange(start, start);
            showCharacterDropdownForImagePrompt(opts.nodeId, expandTextarea, start, dropdownKey);
            return;
          }
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
          if(typeof appendVideoResolutionToForm === 'function') {
            appendVideoResolutionToForm(form, videoModel || 'wan22', shotGroupNode.data.videoResolution);
          }
          // 是否处理人脸（仅 seedance2.0 商业版生效）
          if(shotGroupNode.data.processFace === true) {
            form.append('enable_face_mask', 'true');
          }
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
          if(typeof appendVideoResolutionToForm === 'function') {
            appendVideoResolutionToForm(form, videoModel || 'wan22', shotGroupNode.data.videoResolution);
          }
          // 是否处理人脸（仅 seedance2.0 商业版生效）
          if(shotGroupNode.data.processFace === true) {
            form.append('enable_face_mask', 'true');
          }
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
          if(typeof appendVideoResolutionToForm === 'function') {
            appendVideoResolutionToForm(form, videoModel || 'wan22', shotGroupNode.data.videoResolution);
          }
          // 是否处理人脸（仅 seedance2.0 商业版生效）
          if(shotGroupNode.data.processFace === true) {
            form.append('enable_face_mask', 'true');
          }
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
                    // 封面帧与悬停播放逻辑已内置于 setupVideoThumbnail（不再 loop 常驻解码）
                    setupVideoThumbnail(thumbVideo, videoUrls[index]);
                    if(nameEl){
                      const displayName = (videoNode.data.name || '').length > 10 ? (videoNode.data.name || '').substring(0, 10) + '...' : (videoNode.data.name || '');
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

            // 把分镜组的人脸处理设置同步到子节点（复用分镜节点提交逻辑）
            shotFrameNode.data.processFace = !!shotGroupNode.data.processFace;

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
              ${hasImage ? `<img src="${escapeHtml(char.reference_image)}" style="width: 24px; height: 24px; object-fit: cover; border-radius: 3px;" />` : '<div style="width: 24px; height: 24px; background: #fee2e2; border-radius: 3px; display: flex; align-items: center; justify-content: center; font-size: 10px; color: #ef4444;">!</div>'}
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
      
      // 触发符（/ @ ＠ 、）已被 keydown/input 拦截剔除，不会出现在文本中，直接在光标位置插入
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

    // ES Module exports（供 Vitest 测试使用，不影响浏览器全局变量）
    if (typeof module !== 'undefined') {
      module.exports = { truncateErrorMessage, resolveGridConfig, buildGridPrompt, normalizeGridImageModelValue, getDefaultGridImageModelValue };
    }
