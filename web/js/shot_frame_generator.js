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

// 生成分镜图功能
async function generateShotFrameImage(nodeId, node){
  const generateBtn = document.querySelector(`.node[data-node-id="${nodeId}"] .shot-frame-generate-btn`);
  if(!generateBtn) return;
  
  generateBtn.disabled = true;
  generateBtn.textContent = '处理中...';
  
  try {
    const imagePrompt = node.data.imagePrompt || '';
    if(!imagePrompt){
      showToast('图片提示词不能为空', 'warning');
      return;
    }
    
    // 1. 提取角色名（用【【】】包裹）
    const characterPattern = /【【([^】]+)】】/g;
    const characterNames = [];
    let match;
    while((match = characterPattern.exec(imagePrompt)) !== null){
      const name = match[1].trim();
      if(name && !characterNames.includes(name)){
        characterNames.push(name);
      }
    }
    
    // 2. 匹配角色并获取参考图
    const referenceImages = [];
    const promptSuffix = [];
    let imageIndex = 1;
    
    if(characterNames.length > 0){
      showToast(`检测到${characterNames.length}个角色，正在匹配...`, 'info');
      
      // 获取 world_id
      const worldId = state.defaultWorldId || 1;
      
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
            if(result.code === 0 && result.data && result.data.data){
              const characters = result.data.data;
              // 精确匹配或模糊匹配
              const matchedChar = characters.find(c => c.name === characterName) || characters[0];
              
              if(matchedChar && matchedChar.reference_image){
                // 将参考图URL转换为File对象
                const imageFile = await fetchFileFromUrl(matchedChar.reference_image);
                if(imageFile){
                  referenceImages.push(imageFile);
                  promptSuffix.push(`图${imageIndex}是${characterName}`);
                  imageIndex++;
                }
              }
            }
          }
        } catch(error){
          console.error(`匹配角色 ${characterName} 失败:`, error);
        }
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
        if(locInfo.pic){
          try {
            const locationFile = await fetchFileFromUrl(locInfo.pic);
            if(locationFile){
              referenceImages.push(locationFile);
              promptSuffix.push(`图${imageIndex}是${locInfo.name}所在地点`);
              imageIndex++;
            }
          } catch(error){
            console.error('添加场景参考图失败:', error);
          }
        }
      }
    } else {
      // 独立分镜模式：只添加单个场景参考图
      if(shotData.db_location_id && shotData.db_location_pic){
        try {
          const locationFile = await fetchFileFromUrl(shotData.db_location_pic);
          if(locationFile){
            referenceImages.push(locationFile);
            const locationName = shotData.location_name || '场景';
            promptSuffix.push(`图${imageIndex}是${locationName}所在地点`);
            imageIndex++;
          }
        } catch(error){
          console.error('添加场景参考图失败:', error);
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
    
    // 5. 检查是否有参考图
    if(referenceImages.length === 0){
      showToast('未找到角色或场景参考图，无法生成', 'warning');
      generateBtn.disabled = false;
      generateBtn.textContent = '生成分镜图';
      return;
    }
    
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
    
    // 6. 调用图片编辑API
    const userId = localStorage.getItem('user_id');
    const authToken = localStorage.getItem('auth_token') || '';
    const form = new FormData();
    
    // 添加所有参考图
    referenceImages.forEach(file => {
      form.append('image', file);
    });
    
    form.append('prompt', finalPrompt);
    
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
    
    form.append('ratio', ratio);
    form.append('count', node.data.drawCount || 1);
    form.append('model', node.data.model || 'gemini-2.5-pro-image-preview');
    
    if(userId){
      form.append('user_id', userId);
    }
    if(authToken){
      form.append('auth_token', authToken);
    }
    
    const res = await fetch('/api/image-edit', {
      method: 'POST',
      body: form
    });
    
    const data = await res.json();
    if(!data.project_ids || data.project_ids.length === 0){
      throw new Error(data.detail || data.message || '提交任务失败');
    }
    
    // 7. 轮询任务状态
    node.data.projectIds = data.project_ids;
    showToast('任务已提交，正在生成分镜图...', 'info');
    
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
        
        console.log('Creating image node with URL:', imageUrls[0]);
        
        // 为每个生成的图片创建新的图片节点
        const createdImageNodeIds = [];
        imageUrls.forEach((imageUrl, index) => {
          const offsetY = index * 280; // 每个节点垂直间隔280px
          const newNodeId = createImageNode({ 
            x: node.x + 380, 
            y: node.y + offsetY 
          });
          
          const newNode = state.nodes.find(n => n.id === newNodeId);
          if(newNode){
            newNode.data.url = imageUrl;
            newNode.data.preview = imageUrl;
            newNode.data.name = imageUrls.length > 1 ? `分镜图${index + 1}` : '分镜图';
            newNode.title = newNode.data.name;
            
            // 更新节点显示
            const canvasEl = document.getElementById('canvas');
            const newNodeEl = canvasEl ? canvasEl.querySelector(`.node[data-node-id="${newNodeId}"]`) : null;
            if(newNodeEl){
              const titleEl = newNodeEl.querySelector('.node-title');
              if(titleEl) titleEl.textContent = newNode.title;
              
              const previewImg = newNodeEl.querySelector('.image-preview');
              const previewRow = newNodeEl.querySelector('.image-preview-row');
              if(previewImg && previewRow){
                previewImg.src = proxyImageUrl(imageUrl);
                previewRow.style.display = 'flex';
              }
            }
            
            // 创建从分镜节点到图片节点的连接
            state.connections.push({
              id: state.nextConnId++,
              from: nodeId,
              to: newNodeId
            });
            
            createdImageNodeIds.push(newNodeId);
            console.log(`Created image node ${newNodeId} with URL:`, imageUrl);
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
