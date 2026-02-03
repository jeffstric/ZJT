// 计算合并分镜的最佳比例
function calculateMergedShotRatio(shotCount, canvasRatio) {
  if (!shotCount || shotCount <= 0) {
    return '1:1';
  }

  const availableRatios = [
    { name: '16:9', width: 16, height: 9 },
    { name: '4:3', width: 4, height: 3 },
    { name: '1:1', width: 1, height: 1 },
    { name: '3:4', width: 3, height: 4 },
    { name: '9:16', width: 9, height: 16 }
  ];

  const canvasRatioObj = availableRatios.find(r => r.name === canvasRatio) || { width: 16, height: 9 };
  
  const isVerticalStacking = canvasRatioObj.width >= canvasRatioObj.height;
  
  let mergedWidth, mergedHeight;
  if (isVerticalStacking) {
    mergedWidth = canvasRatioObj.width;
    mergedHeight = canvasRatioObj.height * shotCount;
  } else {
    mergedWidth = canvasRatioObj.width * shotCount;
    mergedHeight = canvasRatioObj.height;
  }
  
  const mergedAspectRatio = mergedWidth / mergedHeight;
  
  let closestRatio = availableRatios[0];
  let minDifference = Math.abs(mergedAspectRatio - (closestRatio.width / closestRatio.height));
  
  for (const ratio of availableRatios) {
    const ratioValue = ratio.width / ratio.height;
    const difference = Math.abs(mergedAspectRatio - ratioValue);
    
    if (difference < minDifference) {
      minDifference = difference;
      closestRatio = ratio;
    }
  }
  
  return closestRatio.name;
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
    
    // 2. 匹配角色并获取参考图
    const referenceImages = [];
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
                
                if(matchedChar && matchedChar.reference_image){
                  // 将参考图URL转换为File对象
                  const imageFile = await fetchFileFromUrl(matchedChar.reference_image);
                  if(imageFile){
                    referenceImages.push(imageFile);
                    promptSuffix.push(`图${imageIndex}是${characterName}`);
                    imageIndex++;
                  }
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
    
    // 3. 添加场景参考图
    const shotData = node.data.shotJson || {};
    
    // 检查是否是合并分镜模式
    const isMerged = node.data.isMerged || false;
    
    if(isMerged){
      // 合并分镜模式：收集所有场景的参考图
      const allLocationInfo = shotData.allLocationInfo || [];
      for(const locInfo of allLocationInfo){
        if(locInfo.id){
          try {
            const userId = localStorage.getItem('user_id') || '1';
            const authToken = localStorage.getItem('auth_token') || '';
            
            const response = await fetch(`/api/location/${locInfo.id}`, {
              headers: {
                'Authorization': authToken,
                'X-User-Id': userId
              }
            });
            
            if(response.ok){
              const result = await response.json();
              if(result.code === 0 && result.data && result.data.reference_image){
                console.log(`[场景匹配] 场景有参考图: ${result.data.reference_image}`);
                const locationFile = await fetchFileFromUrl(result.data.reference_image);
                if(locationFile){
                  referenceImages.push(locationFile);
                  const locationName = result.data.name || locInfo.name || '场景';
                  promptSuffix.push(`图${imageIndex}是${locationName}所在地点`);
                  imageIndex++;
                } else {
                  console.warn(`[场景匹配] fetchFileFromUrl 返回空`);
                }
              } else {
                console.warn(`[场景匹配] 数据结构不符合预期或无参考图`);
              }
            } else {
              console.error(`[场景匹配] API调用失败: ${response.status}`);
            }
          } catch(error){
            console.error('添加场景参考图失败:', error);
          }
        }
      }
    } else {
      // 独立分镜模式：只添加单个场景参考图
      if(shotData.db_location_id){
        try {
          const userId = localStorage.getItem('user_id') || '1';
          const authToken = localStorage.getItem('auth_token') || '';
          
          console.log(`[场景匹配] 开始调用API获取场景 (ID: ${shotData.db_location_id})`);
          const response = await fetch(`/api/location/${shotData.db_location_id}`, {
            headers: {
              'Authorization': authToken,
              'X-User-Id': userId
            }
          });
          
          console.log(`[场景匹配] API响应状态: ${response.status}, ok: ${response.ok}`);
          if(response.ok){
            const result = await response.json();
            console.log(`[场景匹配] 场景查询结果:`, result);
            if(result.code === 0 && result.data && result.data.reference_image){
              console.log(`[场景匹配] 场景有参考图: ${result.data.reference_image}`);
              const locationFile = await fetchFileFromUrl(result.data.reference_image);
              if(locationFile){
                referenceImages.push(locationFile);
                const locationName = result.data.name || shotData.location_name || '场景';
                promptSuffix.push(`图${imageIndex}是${locationName}所在地点`);
                imageIndex++;
                console.log(`[场景匹配] 成功添加场景参考图: ${locationName}`);
              } else {
                console.warn(`[场景匹配] fetchFileFromUrl 返回空`);
              }
            } else {
              console.warn(`[场景匹配] 数据结构不符合预期或无参考图`);
            }
          } else {
            console.error(`[场景匹配] API调用失败: ${response.status}`);
          }
        } catch(error){
          console.error('添加场景参考图失败:', error);
        }
      }
    }
    
    // 4. 添加道具参考图
    const propsPresent = shotData.props_present || [];
    if(propsPresent.length > 0){
      console.log('[生成分镜图] 检测到道具列表:', propsPresent);
      console.log('[生成分镜图] shotData.scriptData 存在:', !!shotData.scriptData);
      console.log('[生成分镜图] shotData.scriptData.props:', shotData.scriptData?.props);
      
      if(!shotData.scriptData || !shotData.scriptData.props){
        console.warn('[生成分镜图] 警告: shotData.scriptData 或 scriptData.props 不存在，无法获取道具信息');
      }
    }
    
    if(propsPresent.length > 0 && shotData.scriptData && shotData.scriptData.props){
      console.log('[生成分镜图] 进入道具处理逻辑');
      const scriptProps = shotData.scriptData.props;
      console.log('[生成分镜图] scriptProps:', scriptProps);
      
      for(const propId of propsPresent){
        console.log(`[生成分镜图] 处理道具ID: ${propId}`);
        const prop = scriptProps.find(p => p.id === propId);
        console.log(`[生成分镜图] 找到的道具:`, prop);
        if(prop && prop.props_db_id){
          console.log(`[生成分镜图] 道具有 props_db_id: ${prop.props_db_id}`);
          // 从数据库获取道具的参考图
          try {
            const userId = localStorage.getItem('user_id') || '1';
            const authToken = localStorage.getItem('auth_token') || '';
            
            console.log(`[道具匹配] 开始调用API获取道具 ${prop.name} (ID: ${prop.props_db_id})`);
            const response = await fetch(`/api/props/${prop.props_db_id}`, {
              headers: {
                'Authorization': authToken,
                'X-User-Id': userId
              }
            });
            
            console.log(`[道具匹配] API响应状态: ${response.status}, ok: ${response.ok}`);
            if(response.ok){
              const result = await response.json();
              console.log(`[道具匹配] 道具"${prop.name}"查询结果:`, result);
              if(result.code === 0 && result.data && result.data.reference_image){
                console.log(`[道具匹配] 道具有参考图: ${result.data.reference_image}`);
                const propsFile = await fetchFileFromUrl(result.data.reference_image);
                if(propsFile){
                  referenceImages.push(propsFile);
                  promptSuffix.push(`图${imageIndex}是${prop.name}`);
                  imageIndex++;
                  console.log(`[道具匹配] 成功添加道具参考图: ${prop.name}`);
                } else {
                  console.warn(`[道具匹配] fetchFileFromUrl 返回空`);
                }
              } else {
                console.warn(`[道具匹配] 数据结构不符合预期或无参考图`);
              }
            } else {
              console.error(`[道具匹配] API调用失败: ${response.status}`);
            }
          } catch(error){
            console.error(`[道具匹配] 添加道具 ${prop.name} 参考图失败:`, error);
          }
        }
      }
    }
    
    // 4. 构建最终提示词
    let finalPrompt = imagePrompt;
    
    // 4.5. 如果是合并分镜模式，添加角色和场景说明
    if(isMerged && promptSuffix.length > 0){
      finalPrompt = `${imagePrompt}\n\n${promptSuffix.join('。')}。`;
    } else if(!isMerged && promptSuffix.length > 0){
      // 独立分镜模式，使用逗号分隔
      finalPrompt = `${imagePrompt}\n\n${promptSuffix.join('，')}。`;
    }
    
    // 4.6. 添加画风文字描述
    if(state.style && state.style.name){
      finalPrompt = `${finalPrompt}\n\n图片风格：${state.style.name}`;
    }
    
    // 5. 确定使用哪个API（图片编辑或文生图）
    const userId = localStorage.getItem('user_id');
    const authToken = localStorage.getItem('auth_token') || '';
    let ratio;
    if (isMerged) {
      const canvasRatio = state.ratio || '16:9';
      const mergedShots = shotData.mergedShots || [];
      const shotCount = mergedShots.length || 1;
      ratio = calculateMergedShotRatio(shotCount, canvasRatio);
      console.log(`Merged shot frame: ${shotCount} shots with canvas ratio ${canvasRatio} -> using ratio ${ratio}`);
    } else {
      const canvasRatio = state.ratio || '16:9';
      ratio = canvasRatio;
    }
    
    let res;
    if(referenceImages.length === 0){
      // 没有参考图，使用文生图API
      generateBtn.textContent = '生成中...';
      showToast('未找到参考图，使用文生图模式生成...', 'info');
      
      const form = new FormData();
      form.append('prompt', finalPrompt);
      form.append('model', node.data.model || 'gemini-2.5-pro-image-preview');
      form.append('aspect_ratio', ratio);
      form.append('count', node.data.drawCount || 1);
      
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
      // 有参考图，使用图片编辑API
      // 5.5. 限制参考图数量不超过5个
      const MAX_REFERENCE_IMAGES = 5;
      if(referenceImages.length > MAX_REFERENCE_IMAGES){
        console.warn(`参考图数量 ${referenceImages.length} 超过限制 ${MAX_REFERENCE_IMAGES}，将只使用前 ${MAX_REFERENCE_IMAGES} 张`);
        referenceImages.splice(MAX_REFERENCE_IMAGES);
        promptSuffix.splice(MAX_REFERENCE_IMAGES);
        showToast(`参考图数量超过${MAX_REFERENCE_IMAGES}张，已自动限制为${MAX_REFERENCE_IMAGES}张`, 'warning');
      }
      
      generateBtn.textContent = '生成中...';
      showToast(`找到${referenceImages.length}张参考图，开始生成...`, 'info');
      
      const form = new FormData();
      
      // 添加所有参考图
      referenceImages.forEach(file => {
        form.append('image', file);
      });
      
      form.append('prompt', finalPrompt);
      form.append('ratio', ratio);
      form.append('count', node.data.drawCount || 1);
      form.append('model', node.data.model || 'gemini-2.5-pro-image-preview');
      
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
        y: node.y + offsetY 
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
            imageNode.data.url = imageUrl;
            imageNode.data.preview = imageUrl;
            
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
