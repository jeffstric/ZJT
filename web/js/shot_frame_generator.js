// 将相机参数转换为多角度 API 参数
function convertCameraToQwenMultiAngleParams(camera) {
  if (!camera) return null;
  return {
    horizontal_angle: camera.horizontal_angle ?? 0,
    vertical_angle: camera.vertical_angle ?? 0,
    zoom: camera.zoom ?? 5.0
  };
}

// 移除不存在角色的【【】】标记
function removeMissingCharacterMarkers(prompt, missingCharacters){
  if(!prompt || !missingCharacters || missingCharacters.size === 0){
    return prompt;
  }

  return prompt.replace(/【【([^】]+)】】/g, (match, name) => {
    const trimmedName = name.trim();
    return missingCharacters.has(trimmedName) ? trimmedName : match;
  });
}

// 生成分镜图功能
async function generateShotFrameImage(nodeId, node){
  console.log('[生成分镜图] 函数被调用, nodeId:', nodeId, 'node:', node);
  console.log('[生成分镜图] 当前 state.defaultWorldId:', state.defaultWorldId);
  
  const generateBtn = document.querySelector(`.node[data-node-id="${nodeId}"] .shot-frame-generate-btn`);
  if(!generateBtn){
    console.error('[生成分镜图] 未找到生成按钮');
    return;
  }
  
  generateBtn.disabled = true;
  generateBtn.textContent = '处理中...';
  
  try {
    let imagePrompt = node.data.imagePrompt || '';
    console.log('[生成分镜图] 图片提示词:', imagePrompt);
    if(!imagePrompt){
      showToast('图片提示词不能为空', 'warning');
      return;
    }
    
    // 1. 提取角色名（用【【】】包裹）
    const characterPattern = /【【([^】]+)】】/g;
    const characterNames = [];
    const missingCharacters = new Set();
    let match;
    while((match = characterPattern.exec(imagePrompt)) !== null){
      const name = match[1].trim();
      if(name && !characterNames.includes(name)){
        characterNames.push(name);
      }
    }
    
    console.log('[生成分镜图] 提取到的角色列表:', characterNames);
    
    // 2. 匹配角色并获取参考图 URL
    const referenceImageUrls = [];
    const promptSuffix = [];
    let imageIndex = 1;
    
    if(characterNames.length > 0){
      showToast(`检测到${characterNames.length}个角色，正在匹配...`, 'info');
      
      // 获取 world_id
      if(!state.defaultWorldId){
        showToast('请先在左上角选择世界，以便正确匹配角色', 'warning');
        generateBtn.disabled = false;
        generateBtn.textContent = '生成分镜图';
        return;
      }
      const worldId = state.defaultWorldId;
      console.log(`[生成分镜图] 使用世界ID: ${worldId}, 角色列表:`, characterNames);
      
      for(const characterName of characterNames){
        try {
          const userId = localStorage.getItem('user_id') || '1';
          const authToken = localStorage.getItem('auth_token') || '';
          
          const response = await fetch(`/api/characters?world_id=${worldId}&page=1&page_size=100&keyword=${encodeURIComponent(characterName)}`, {
            headers: {
              'Authorization': authToken,
              'X-User-Id': userId
            }
          });
          
          if(response.ok){
            const result = await response.json();
            console.log(`[角色匹配] 角色"${characterName}"查询结果:`, result);
            if(result.code === 0 && result.data && Array.isArray(result.data.data)){
              const characters = result.data.data;
              console.log(`[角色匹配] 找到${characters.length}个匹配角色:`, characters.map(c => c.name));
              if(characters.length > 0){
                // 精确匹配或模糊匹配
                const matchedChar = characters.find(c => c.name === characterName) || characters[0];
                console.log(`[角色匹配] 最终匹配角色:`, matchedChar.name, '参考图:', matchedChar.reference_image);
                
                // 检查用户是否为该角色选择了特定图片
                const userSelectedCharUrl = (node.data.selectedCharRefImages && node.data.selectedCharRefImages[characterName]);
                const charRefUrl = userSelectedCharUrl || (matchedChar && matchedChar.reference_image);
                if(charRefUrl){
                  referenceImageUrls.push(charRefUrl);
                  const labelDesc = userSelectedCharUrl && userSelectedCharUrl !== matchedChar?.reference_image
                    ? `的${(node.data.selectedCharRefImageLabels && node.data.selectedCharRefImageLabels[characterName]) || '已选择'}` : '';
                  promptSuffix.push(`图${imageIndex}是${characterName}${labelDesc}`);
                  imageIndex++;
                  console.log(`[角色匹配] 成功添加角色参考图: ${characterName}${labelDesc ? '(' + labelDesc + ')' : '(主图)'}`);
                }
              } else {
                missingCharacters.add(characterName);
              }
            } else if(result.code === 0 && result.data && result.data.data === null){
              missingCharacters.add(characterName);
            }
          }
        } catch(error){
          console.error(`匹配角色 ${characterName} 失败:`, error);
        }
      }
    }

    const sanitizedPrompt = removeMissingCharacterMarkers(imagePrompt, missingCharacters);
    if(sanitizedPrompt !== imagePrompt){
      imagePrompt = sanitizedPrompt;
      node.data.imagePrompt = sanitizedPrompt;
      const promptTextarea = document.querySelector(`.node[data-node-id="${nodeId}"] .shot-frame-image-prompt`);
      if(promptTextarea){
        promptTextarea.value = sanitizedPrompt;
      }
    }
    
    // 3. 添加场景参考图（从 node.data.refScene + state.worldLocations 获取）
    if(node.data.refScene && node.data.refScene.id){
      const loc = (state.worldLocations || []).find(l => l.id === node.data.refScene.id);
      const mainRefImage = (loc && loc.reference_image) || node.data.refScene.pic || '';

      // 优先使用用户选择的特定图片，否则使用主图
      const sceneRefUrl = node.data.selectedSceneRefUrl || mainRefImage;
      if(sceneRefUrl){
        referenceImageUrls.push(sceneRefUrl);
        const locationName = (loc && loc.name) || node.data.refScene.name || '场景';
        const isCustomSelection = node.data.selectedSceneRefUrl && node.data.selectedSceneRefUrl !== mainRefImage;
        const angleLabel = isCustomSelection ? (node.data.selectedSceneRefLabel || '已选择角度') : '';
        promptSuffix.push(`图${imageIndex}是${locationName}所在地点${angleLabel ? '(' + angleLabel + ')' : ''}`);
        imageIndex++;
        console.log(`[场景匹配] 成功添加场景参考图: ${locationName}${isCustomSelection ? '(已选特定角度)' : '(主图)'}`);
      } else {
        console.warn(`[场景匹配] 场景”${node.data.refScene.name}”无参考图`);
      }
    }
    
    // 4. 添加道具参考图（从 node.data.refProps + state.worldProps 获取）
    const refProps = node.data.refProps || [];
    if(refProps.length > 0){
      console.log('[生成分镜图] 检测到引用道具:', refProps.map(p => p.name));
      for(const refProp of refProps){
        const propDbId = refProp.props_db_id || refProp.id;
        // 优先从 state.worldProps 获取最新数据（包含最新的 reference_image）
        const worldProp = (state.worldProps || []).find(p => p.id === propDbId);
        const refImage = (worldProp && worldProp.reference_image) || refProp.reference_image || '';
        if(refImage){
          referenceImageUrls.push(refImage);
          const propName = (worldProp && worldProp.name) || refProp.name;
          promptSuffix.push(`图${imageIndex}是${propName}`);
          imageIndex++;
          console.log(`[道具匹配] 成功添加道具参考图: ${propName}`);
        } else {
          console.warn(`[道具匹配] 道具“${refProp.name}”无参考图`);
        }
      }
    }
    
    // 4. 构建最终提示词
    let finalPrompt = imagePrompt;
    
    if(promptSuffix.length > 0){
      finalPrompt = `${imagePrompt}\n\n${promptSuffix.join('，')}。`;
    }
    
    // 4.5. 添加相机视角描述（从连接的图片节点或相机控制节点读取，使用多角度 API）
    const connectedImageNode = state.connections
      .filter(c => c.from === nodeId)
      .map(c => state.nodes.find(n => n.id === c.to))
      .find(n => n && n.type === 'image');

    let cameraParams = null;
    // 优先从图片节点的旧 camera 数据读取（兼容旧工作流）
    if(connectedImageNode && connectedImageNode.data.camera){
      cameraParams = convertCameraToQwenMultiAngleParams(connectedImageNode.data.camera);
    }
    // 其次查找连接到该图片节点的 camera_control 节点
    if(!cameraParams && connectedImageNode){
      const cameraCtrlNode = state.nodes.find(n => {
        if(n.type !== 'camera_control') return false;
        return state.connections.some(c => c.from === connectedImageNode.id && c.to === n.id);
      });
      if(cameraCtrlNode && cameraCtrlNode.data.camera){
        cameraParams = convertCameraToQwenMultiAngleParams(cameraCtrlNode.data.camera);
      }
    }
    
    // 4.6. 添加画风文字描述
    if(state.style && state.style.name){
      finalPrompt = `${finalPrompt}\n\n图片风格：${state.style.name}`;
    }

    // 4.7. 添加构图倾向
    if(state.style && state.style.compositionPreference){
      finalPrompt = `${finalPrompt}\n构图倾向：${state.style.compositionPreference}`;
    }

    // 5. 确定使用哪个API（图片编辑、多角度或文生图）
    const userId = localStorage.getItem('user_id');
    const authToken = localStorage.getItem('auth_token') || '';
    const canvasRatio = state.ratio || '16:9';
    const ratio = canvasRatio;

    let res;
    if(cameraParams && referenceImageUrls.length > 0){
      // 有相机参数且有参考图，使用多角度 API
      generateBtn.textContent = '生成中...';
      showToast(`找到${referenceImageUrls.length}张参考图，使用多角度模式生成...`, 'info');

      const form = new FormData();
      form.append('ref_image_urls', referenceImageUrls.join(','));
      form.append('prompt', finalPrompt);
      form.append('ratio', ratio);
      form.append('count', node.data.drawCount || 1);

      // 使用多角度 API 的 task_id
      const multiAngleTaskId = TaskConfig.getTaskIdByKey('qwen-multi-angle', 'image_edit');
      if(!multiAngleTaskId){
        throw new Error('未找到多角度图片编辑的任务配置');
      }
      form.append('task_id', multiAngleTaskId);
      form.append('extra_config', JSON.stringify(cameraParams));

      if(userId){
        form.append('user_id', userId);
      }
      if(authToken){
        form.append('auth_token', authToken);
      }

      res = await fetch('/api/image-edit', {
        method: 'POST',
        body: form
      });
    } else if(referenceImageUrls.length === 0){
      // 没有参考图，使用文生图API
      generateBtn.textContent = '生成中...';
      showToast('未找到参考图，使用文生图模式生成...', 'info');

      const form = new FormData();
      form.append('prompt', finalPrompt);
      form.append('aspect_ratio', ratio);
      form.append('count', node.data.drawCount || 1);

      // 根据 model 获取 task_id
      const modelKey = node.data.model || 'gemini-2.5-flash-image-preview';
      const taskId = TaskConfig.getTaskIdByKey(modelKey, 'text_to_image');
      if(!taskId){
        throw new Error(`未找到模型 ${modelKey} 对应的任务配置`);
      }
      form.append('task_id', taskId);

      if(userId){
        form.append('user_id', userId);
      }
      if(authToken){
        form.append('auth_token', authToken);
      }

      res = await fetch('/api/text-to-image', {
        method: 'POST',
        body: form
      });
    } else {
      // 有参考图但无相机参数，使用普通图片编辑API
      // 5.5. 根据模型限制参考图数量
      const modelKey2 = node.data.model || 'gemini-2.5-flash-image-preview';
      const MAX_REFERENCE_IMAGES = modelKey2 === 'nano-banana' ? 5 : 14;
      if(referenceImageUrls.length > MAX_REFERENCE_IMAGES){
        console.warn(`参考图数量 ${referenceImageUrls.length} 超过限制 ${MAX_REFERENCE_IMAGES}，将只使用前 ${MAX_REFERENCE_IMAGES} 张`);
        referenceImageUrls.splice(MAX_REFERENCE_IMAGES);
        promptSuffix.splice(MAX_REFERENCE_IMAGES);
        showToast(`参考图数量超过${MAX_REFERENCE_IMAGES}张，已自动限制为${MAX_REFERENCE_IMAGES}张`, 'warning');
      }

      generateBtn.textContent = '生成中...';
      showToast(`找到${referenceImageUrls.length}张参考图，开始生成...`, 'info');

      const form = new FormData();

      // 直接传递参考图 URL 列表
      form.append('ref_image_urls', referenceImageUrls.join(','));

      form.append('prompt', finalPrompt);
      form.append('ratio', ratio);
      form.append('count', node.data.drawCount || 1);

      // 根据 model 获取 task_id（modelKey2 已在上面声明）
      const taskId2 = TaskConfig.getTaskIdByKey(modelKey2, 'image_edit');
      if(!taskId2){
        throw new Error(`未找到模型 ${modelKey2} 对应的任务配置`);
      }
      form.append('task_id', taskId2);

      if(userId){
        form.append('user_id', userId);
      }
      if(authToken){
        form.append('auth_token', authToken);
      }

      res = await fetch('/api/image-edit', {
        method: 'POST',
        body: form
      });
    }
    
    const data = await res.json();
    if(!data.project_ids || data.project_ids.length === 0){
      throw new Error(data.detail || data.message || '提交任务失败');
    }
    
    // 7. 保存 project_ids 并立即创建图片节点
    node.data.projectIds = data.project_ids;
    showToast('任务已提交，正在生成分镜图...', 'info');
    
    // 立即创建对应数量的图片节点并绑定 project_id
    const createdImageNodeIds = [];
    const projectIds = data.project_ids;
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
        newNode.data.name = imageCount > 1 ? `分镜图${i + 1}` : '分镜图';
        newNode.data.project_id = projectIds[i] || projectIds[0];
        newNode.title = newNode.data.name;
        
        // 更新节点标题显示
        const canvasEl = document.getElementById('canvas');
        const newNodeEl = canvasEl ? canvasEl.querySelector(`.node[data-node-id="${newNodeId}"]`) : null;
        if(newNodeEl){
          const titleEl = newNodeEl.querySelector('.node-title');
          if(titleEl) titleEl.textContent = newNode.title;
        }
        
        // 创建从分镜节点到图片节点的连接
        state.connections.push({
          id: state.nextConnId++,
          from: nodeId,
          to: newNodeId
        });
        
        createdImageNodeIds.push(newNodeId);
        console.log(`[分镜图] 创建图片节点 ${newNodeId} 并绑定 project_id:`, newNode.data.project_id);
      }
    }
    
    // 重新渲染连接线
    renderConnections();
    renderImageConnections();
    renderFirstFrameConnections();
    renderMinimap();
    
    // 轮询任务状态,更新图片URL
    pollVideoStatus(
      data.project_ids,
      (progressText) => {
        generateBtn.textContent = progressText;
      },
      (statusResult) => {
        console.log('Shot frame generation status result:', statusResult);
        
        // 从 tasks 数组中提取结果
        let imageUrls = [];
        if(statusResult.tasks && Array.isArray(statusResult.tasks)){
          // 多任务或单任务包装格式
          imageUrls = statusResult.tasks
            .filter(task => task.status === 'SUCCESS' && task.result)
            .map(task => normalizeVideoUrl(task.result))
            .filter(Boolean);
        } else {
          // 直接从 statusResult 提取
          const rawResults = extractResultsArray(statusResult);
          imageUrls = Array.isArray(rawResults)
            ? rawResults.map(normalizeVideoUrl).filter(Boolean)
            : [];
        }
        
        console.log('Extracted image URLs:', imageUrls);
        
        if(imageUrls.length === 0){
          console.error('No image URLs found in result');
          showToast('生成成功，但未获取到图片地址', 'error');
          generateBtn.disabled = false;
          generateBtn.textContent = '生成分镜图';
          return;
        }
        
        // 更新已创建的图片节点的URL和预览
        imageUrls.forEach((imageUrl, index) => {
          if(index >= createdImageNodeIds.length) return;
          
          const imageNodeId = createdImageNodeIds[index];
          const imageNode = state.nodes.find(n => n.id === imageNodeId);
          
          if(imageNode){
            const normalizedUrl = normalizeImageUrl(imageUrl);
            imageNode.data.url = normalizedUrl;
            imageNode.data.preview = normalizedUrl;
            
            // 更新节点显示
            const canvasEl = document.getElementById('canvas');
            const imageNodeEl = canvasEl ? canvasEl.querySelector(`.node[data-node-id="${imageNodeId}"]`) : null;
            if(imageNodeEl){
              const previewImg = imageNodeEl.querySelector('.image-preview');
              const previewRow = imageNodeEl.querySelector('.image-preview-row');
              if(previewImg && previewRow){
                previewImg.src = proxyImageUrl(imageUrl);
                previewRow.style.display = 'flex';
              }
            }
            
            console.log(`[分镜图] 更新图片节点 ${imageNodeId} URL:`, imageUrl);
          }
        });
        
        // 自动为视频节点选择首帧图片（如果视频首帧不存在）
        const connectedVideoNodes = state.connections
          .filter(c => c.from === nodeId)
          .map(c => state.nodes.find(n => n.id === c.to))
          .filter(n => n && n.type === 'video');
        
        if(connectedVideoNodes.length > 0 && createdImageNodeIds.length > 0){
          connectedVideoNodes.forEach(videoNode => {
            // 检查该视频节点是否已有首帧连接
            const hasFirstFrame = state.firstFrameConnections.some(fc => fc.to === videoNode.id);
            if(!hasFirstFrame){
              // 随机选择一个图片节点作为首帧
              const randomImageNodeId = createdImageNodeIds[Math.floor(Math.random() * createdImageNodeIds.length)];
              state.firstFrameConnections.push({
                id: state.nextFirstFrameConnId++,
                from: randomImageNodeId,
                to: videoNode.id
              });
              console.log(`Auto-selected image node ${randomImageNodeId} as first frame for video node ${videoNode.id}`);
            }
          });
        }
        
        // 重新渲染连接线
        renderConnections();
        renderImageConnections();
        renderFirstFrameConnections();
        
        // 更新分镜节点的预览图
        if(node.updatePreview){
          node.updatePreview();
        }
        
        generateBtn.disabled = false;
        generateBtn.textContent = '生成分镜图';
        showToast(`分镜图生成成功！已创建 ${imageUrls.length} 个图片节点`, 'success');
        
        try{ autoSaveWorkflow(); } catch(e){ console.error('Auto save failed:', e); }
      },
      (error) => {
        showToast(`生成失败: ${error}`, 'error');
        generateBtn.disabled = false;
        generateBtn.textContent = '生成分镜图';
      }
    );
    
  } catch(error){
    console.error('生成分镜图失败:', error);
    showToast(`生成失败: ${error.message || error}`, 'error');
    generateBtn.disabled = false;
    generateBtn.textContent = '生成分镜图';
  }
}
