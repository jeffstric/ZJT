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
    const videoModel = node.data.videoModel || 'sora';
    
    // 如果是Sora模型，需要替换提示词中的角色标记
    if(videoModel === 'sora'){
      videoPrompt = await replaceCharacterMarkers(videoPrompt);
    }
    
    // 添加视频提示词后缀
    if(typeof getVideoPromptWithSuffix === 'function'){
      videoPrompt = getVideoPromptWithSuffix(videoPrompt);
    }

    showToast(`正在生成 ${count} 个视频...`, 'info');

    // 从URL获取图片文件
    const response = await fetch(proxyImageUrl(imageUrl));
    const blob = await response.blob();
    const file = new File([blob], 'shot_frame.png', { type: 'image/png' });

    // 调用图生视频API
    const userId = localStorage.getItem('user_id') || '1';
    const authToken = localStorage.getItem('auth_token') || '';
    const form = new FormData();
    
    form.append('image_urls', imageUrl);
    form.append('prompt', videoPrompt);
    form.append('duration_seconds', duration);
    form.append('count', count);
    form.append('ratio', '16:9');
    
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
    showToast(`视频生成任务已提交，正在处理...`, 'info');

    // 轮询视频生成状态
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

        // 为每个生成的视频创建新的视频节点
        videoUrls.forEach((videoUrl, index) => {
          const offsetY = index * 280;
          const newVideoNodeId = createVideoNode({ 
            x: node.x + 380, 
            y: node.y + offsetY 
          });
          
          const newVideoNode = state.nodes.find(n => n.id === newVideoNodeId);
          if(newVideoNode){
            newVideoNode.data.url = videoUrl;
            newVideoNode.data.name = videoUrls.length > 1 ? `分镜视频${index + 1}` : '分镜视频';
            newVideoNode.title = newVideoNode.data.name;
            
            // 更新节点显示
            const canvasEl = document.getElementById('canvas');
            const newNodeEl = canvasEl ? canvasEl.querySelector(`.node[data-node-id="${newVideoNodeId}"]`) : null;
            if(newNodeEl){
              const titleEl = newNodeEl.querySelector('.node-title');
              if(titleEl) titleEl.textContent = newVideoNode.title;
              
              const nameEl = newNodeEl.querySelector('.video-name');
              if(nameEl) nameEl.textContent = newVideoNode.data.name;
              
              const previewField = newNodeEl.querySelector('.video-preview-field');
              const thumbVideo = newNodeEl.querySelector('.video-thumb');
              if(previewField && thumbVideo){
                thumbVideo.src = proxyImageUrl(videoUrl);
                previewField.style.display = 'block';
              }
            }
            
            // 创建从分镜节点到视频节点的连接
            state.connections.push({
              id: state.nextConnId++,
              from: nodeId,
              to: newVideoNodeId
            });
            
            console.log(`Created video node ${newVideoNodeId} with URL:`, videoUrl);
          }
        });
        
        // 重新渲染连接线
        renderConnections();
        renderImageConnections();
        renderFirstFrameConnections();
        
        generateBtn.disabled = false;
        generateBtn.textContent = '生成视频';
        showToast(`分镜视频生成成功！已创建 ${videoUrls.length} 个视频节点`, 'success');
        
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
