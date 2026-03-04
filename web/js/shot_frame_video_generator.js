// 替换提示词中的角色标记
async function replaceCharacterMarkers(prompt){
  if(!prompt) return prompt;
  
  // 匹配 【【角色名】】 格式
  const characterPattern = /【【([^】]+)】】/g;
  const matches = [...prompt.matchAll(characterPattern)];
  
  if(matches.length === 0) return prompt;
  
  // 获取当前选择的世界ID
  const defaultWorldSelect = document.getElementById('defaultWorldSelect');
  const worldId = defaultWorldSelect ? defaultWorldSelect.value : '';
  
  if(!worldId){
    showToast('请先选择世界', 'warning');
    return prompt;
  }
  
  // 获取用户ID
  const userId = localStorage.getItem('user_id') || '1';
  
  let replacedPrompt = prompt;
  
  // 遍历所有匹配的角色标记
  for(const match of matches){
    const fullMatch = match[0];
    const characterName = match[1];
    
    try {
      // 调用API查询角色
      const response = await fetch(`/api/character/search?user_id=${userId}&world_id=${worldId}&name=${encodeURIComponent(characterName)}`);
      
      if(!response.ok){
        console.warn(`Failed to fetch character: ${characterName}`);
        continue;
      }
      
      const data = await response.json();
      
      if(data && data.sora_character){
        // 替换角色标记为 @sora_character ID，并在末尾添加空格
        replacedPrompt = replacedPrompt.replace(fullMatch, '@' + data.sora_character + ' ');
        console.log(`Replaced ${fullMatch} with @${data.sora_character} `);
      } else {
        console.warn(`Character ${characterName} found but no sora_character ID`);
      }
    } catch(error){
      console.error(`Error fetching character ${characterName}:`, error);
    }
  }
  
  // 处理提示词中已存在的角色ID（如 patiencep.dragonenvo），在前面添加 @ 符号
  // 匹配格式：单词.单词（但不是已经有@的），确保前面是空格或开头
  const existingIdPattern = /(?<=^|\s)([a-z][a-z0-9]*\.[a-z][a-z0-9]*)/gi;
  replacedPrompt = replacedPrompt.replace(existingIdPattern, '@$1');
  
  return replacedPrompt;
}

// 分镜节点生成视频功能
async function generateShotFrameVideo(nodeId, node){
  if(!node.data.previewImageUrl){
    showToast('请先生成分镜图', 'warning');
    return;
  }

  const generateBtn = document.querySelector(`.node[data-node-id="${nodeId}"] .shot-frame-generate-video-btn`);
  const errorEl = document.querySelector(`.node[data-node-id="${nodeId}"] .shot-frame-video-error`);
  if(!generateBtn) return;

  // 清除之前的错误信息
  if(errorEl){
    errorEl.style.display = 'none';
    errorEl.textContent = '';
  }

  try {
    generateBtn.disabled = true;
    generateBtn.textContent = '生成中...';

    // 获取预览图的URL
    const imageUrl = node.data.previewImageUrl;
    
    // 使用节点中用户编辑的视频提示词文本，而不是JSON格式
    let videoPrompt = node.data.videoPromptText || node.data.videoPrompt || '';
    const duration = node.data.videoDuration || 15;
    const count = node.data.videoDrawCount || 1;
    const videoModel = node.data.videoModel || 'sora2';
    
    // 如果是Sora模型,需要替换提示词中的角色标记
    // 注意: 图生视频模式下禁用角色卡替换,因为效果不佳。等后期支持文生视频时再启用
    // if(videoModel === 'sora2'){
    //   videoPrompt = await replaceCharacterMarkers(videoPrompt);
    // }
    
    // 添加视频提示词后缀
    if(typeof getVideoPromptWithSuffix === 'function'){
      videoPrompt = getVideoPromptWithSuffix(videoPrompt);
    }

    showToast(`正在生成 ${count} 个视频...`, 'info');

    // 调用图生视频API
    const userId = localStorage.getItem('user_id') || '1';
    const authToken = localStorage.getItem('auth_token') || '';
    const form = new FormData();
    
    form.append('image_urls', imageUrl);
    form.append('prompt', videoPrompt);
    form.append('duration_seconds', duration);
    form.append('count', count);
    form.append('ratio', state.ratio || '9:16');
    form.append('video_model', videoModel);
    
    if(userId){
      form.append('user_id', userId);
    }
    if(authToken){
      form.append('auth_token', authToken);
    }

    const res = await fetch('/api/ai-app-run-image', {
      method: 'POST',
      body: form
    });

    const data = await res.json();
    
    if(!data.project_ids || data.project_ids.length === 0){
      throw new Error(data.detail || data.message || '提交任务失败');
    }

    const projectIds = data.project_ids;
    node.data.projectIds = projectIds;
    showToast(`视频生成任务已提交，正在处理...`, 'info');

    // 立即创建对应数量的视频节点并绑定 project_id
    const createdVideoNodeIds = [];
    const videoCount = projectIds.length;
    
    for(let i = 0; i < videoCount; i++){
      const offsetY = i * 280;
      const newVideoNodeId = createVideoNode({ 
        x: node.x + 380, 
        y: node.y + offsetY 
      });
      
      const newVideoNode = state.nodes.find(n => n.id === newVideoNodeId);
      if(newVideoNode){
        newVideoNode.data.name = videoCount > 1 ? `分镜视频${i + 1}` : '分镜视频';
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
        
        // 创建从分镜节点到视频节点的连接
        state.connections.push({
          id: state.nextConnId++,
          from: nodeId,
          to: newVideoNodeId
        });
        
        createdVideoNodeIds.push(newVideoNodeId);
        console.log(`[分镜视频] 创建视频节点 ${newVideoNodeId} 并绑定 project_id:`, newVideoNode.data.project_id);
      }
    }
    
    // 重新渲染连接线
    renderConnections();
    renderImageConnections();
    renderFirstFrameConnections();
    renderMinimap();

    // 轮询视频生成状态,更新视频URL
    pollVideoStatus(
      projectIds,
      (msg) => {
        generateBtn.textContent = msg;
      },
      (statusResult) => {
        console.log('Shot frame video generation status result:', statusResult);
        
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
        
        console.log('Extracted video URLs:', videoUrls);
        
        if(videoUrls.length === 0){
          const errorMsg = '视频生成失败，未获取到结果';
          showToast(errorMsg, 'error');
          if(errorEl){
            errorEl.textContent = errorMsg;
            errorEl.style.display = 'block';
          }
          generateBtn.disabled = false;
          generateBtn.textContent = '生成视频';
          return;
        }

        // 更新已创建的视频节点的URL和预览
        videoUrls.forEach((videoUrl, index) => {
          if(index >= createdVideoNodeIds.length) return;
          
          const videoNodeId = createdVideoNodeIds[index];
          const videoNode = state.nodes.find(n => n.id === videoNodeId);
          
          if(videoNode){
            videoNode.data.url = videoUrl;
            
            // 更新节点显示
            const canvasEl = document.getElementById('canvas');
            const videoNodeEl = canvasEl ? canvasEl.querySelector(`.node[data-node-id="${videoNodeId}"]`) : null;
            if(videoNodeEl){
              const previewField = videoNodeEl.querySelector('.video-preview-field');
              const thumbVideo = videoNodeEl.querySelector('.video-thumb');
              if(previewField && thumbVideo){
                thumbVideo.src = proxyDownloadUrl(videoUrl);
                thumbVideo.muted = true;
                thumbVideo.loop = true;
                thumbVideo.controls = false;
                thumbVideo.preload = 'metadata';
                thumbVideo.playsInline = true;
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
                previewField.style.display = 'block';
                const previewActionsField = videoNodeEl.querySelector('.video-preview-actions-field');
                if(previewActionsField) previewActionsField.style.display = 'block';
              }
            }
            
            console.log(`[分镜视频] 更新视频节点 ${videoNodeId} URL:`, videoUrl);
          }
        });
        
        // 重新渲染连接线
        renderConnections();
        renderImageConnections();
        renderFirstFrameConnections();
        
        generateBtn.disabled = false;
        generateBtn.textContent = '生成视频';
        showToast(`分镜视频生成成功！已创建 ${videoUrls.length} 个视频节点`, 'success');
        
        // 刷新用户算力显示
        if(typeof fetchComputingPower === 'function'){
          fetchComputingPower();
        }
        
        try{ autoSaveWorkflow(); } catch(e){ console.error('Auto save failed:', e); }
      },
      (error) => {
        const errorMsg = `生成失败: ${error}`;
        showToast(errorMsg, 'error');
        if(errorEl){
          errorEl.textContent = errorMsg;
          errorEl.style.display = 'block';
        }
        generateBtn.disabled = false;
        generateBtn.textContent = '生成视频';
      }
    );
    
  } catch(error){
    console.error('生成分镜视频失败:', error);
    const errorMsg = `生成失败: ${error.message || error}`;
    showToast(errorMsg, 'error');
    if(errorEl){
      errorEl.textContent = errorMsg;
      errorEl.style.display = 'block';
    }
    generateBtn.disabled = false;
    generateBtn.textContent = '生成视频';
  }
}
