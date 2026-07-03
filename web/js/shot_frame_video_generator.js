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
  const mode = node.data.videoMode || 'first_last_frame';

  // 首帧模式需要分镜图，参考图模式不需要
  if(mode === 'first_last_frame' && !node.data.previewImageUrl){
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

  // 验证参考音频和视频的总时长（仅首帧模式，参考图模式下 ref audio/video 已隐藏）
  if(mode === 'first_last_frame' && (node.data.refAudioFile || node.data.refVideoFile)) {
    const validationForm = new FormData();
    if(node.data.refAudioFile) {
      validationForm.append('audio_files', node.data.refAudioFile);
    }
    if(node.data.refVideoFile) {
      validationForm.append('video_files', node.data.refVideoFile);
    }
    validationForm.append('max_duration_seconds', 15);

    try {
      const validationRes = await fetch('/api/media/validate-duration', {
        method: 'POST',
        body: validationForm
      });
      const validationData = await validationRes.json();
      if(!validationData.data.valid) {
        const errorMsg = validationData.data.message || '时长超过限制';
        showToast(errorMsg, 'error');
        if(errorEl){
          errorEl.textContent = errorMsg;
          errorEl.style.display = 'block';
        }
        return;
      }
    } catch(err) {
      console.error('媒体验证失败:', err);
      const errorMsg = '媒体验证失败，请检查上传的文件';
      showToast(errorMsg, 'error');
      if(errorEl){
        errorEl.textContent = errorMsg;
        errorEl.style.display = 'block';
      }
      return;
    }
  }

  try {
    generateBtn.disabled = true;
    generateBtn.textContent = '生成中...';

    // 使用节点中用户编辑的视频提示词文本，而不是JSON格式
    let videoPrompt = node.data.videoPromptText || node.data.videoPrompt || '';
    const duration = node.data.videoDuration || 15;
    const count = node.data.videoDrawCount || 1;
    const videoModel = node.data.videoModel || (mode === 'multi_reference' ? 'veo3' : 'sora2');

    // 添加视频提示词后缀
    if(typeof getVideoPromptWithSuffix === 'function'){
      videoPrompt = getVideoPromptWithSuffix(videoPrompt);
    }

    showToast(`正在生成 ${count} 个视频...`, 'info');

    const userId = localStorage.getItem('user_id') || '1';
    const authToken = localStorage.getItem('auth_token') || '';

    // === 构建公共字段 ===
    const form = new FormData();
    form.append('prompt', videoPrompt);
    form.append('ratio', state.ratio || '9:16');
    form.append('duration_seconds', duration);
    form.append('count', count);
    if(userId) form.append('user_id', userId);
    if(authToken) form.append('auth_token', authToken);
    if(typeof appendVideoResolutionToForm === 'function') {
      appendVideoResolutionToForm(form, videoModel, node.data.videoResolution);
    }

    let res;

    if(mode === 'multi_reference') {
      // === 参考图模式 ===
      // 收集角色/场景/道具参考图
      showToast('正在收集参考图...', 'info');
      const { referenceImageUrls, promptSuffix } = await collectShotFrameRefImages(node);

      // 将 promptSuffix 追加到视频提示词
      if(promptSuffix.length > 0) {
        videoPrompt = videoPrompt + '\n\n' + promptSuffix.join('，') + '。';
        form.set('prompt', videoPrompt);
      }

      // 参考模式下追加画风描述（首帧模式不添加，保持原状）
      if(state.style && state.style.name) {
        videoPrompt = videoPrompt + '\n\n视频风格：' + state.style.name;
        if(state.style.compositionPreference) {
          videoPrompt = videoPrompt + '\n构图倾向：' + state.style.compositionPreference;
        }
        form.set('prompt', videoPrompt);
      }

      if(referenceImageUrls.length > 0) {
        // 有参考图 → image_to_video + multi_reference
        const taskId = TaskConfig.getTaskIdByKey(videoModel, 'image_to_video');
        if(!taskId) {
          throw new Error(`未找到视频模型 ${videoModel} 对应的图生视频任务配置`);
        }
        form.append('task_id', taskId);
        form.append('image_urls', referenceImageUrls.join(','));
        form.append('image_mode', 'multi_reference');

        showToast(`使用 ${referenceImageUrls.length} 张参考图生成视频...`, 'info');
        res = await fetch('/api/ai-app-run-image', { method: 'POST', body: form });
      } else {
        // 无参考图 → 回退 text_to_video
        const t2vTaskId = TaskConfig.getTaskIdByKey(videoModel, 'text_to_video');
        if(!t2vTaskId) {
          throw new Error(`模型 ${videoModel} 不支持文生视频回退，请添加参考图（角色/场景/道具）或切换支持文生视频的模型`);
        }

        // 仅在 text_to_video 回退时启用角色标记替换
        const replacedPrompt = await replaceCharacterMarkers(videoPrompt);
        form.set('prompt', replacedPrompt);

        form.append('task_id', t2vTaskId);
        showToast('无参考图，回退为文生视频模式...', 'info');
        res = await fetch('/api/ai-app-run', { method: 'POST', body: form });
      }
    } else {
      // === 首帧模式（原有逻辑） ===
      const imageUrl = node.data.previewImageUrl;
      const taskId = TaskConfig.getTaskIdByKey(videoModel || 'wan22', 'image_to_video');
      if(!taskId) {
        throw new Error(`未找到视频模型 ${videoModel} 对应的任务配置`);
      }
      form.append('task_id', taskId);
      form.append('image_urls', imageUrl);
      form.append('image_mode', 'first_last_frame');

      // 添加参考音频和视频文件
      if(node.data.refAudioFile) {
        form.append('audio_files', node.data.refAudioFile);
      }
      if(node.data.refVideoFile) {
        form.append('video_files', node.data.refVideoFile);
      }

      res = await fetch('/api/ai-app-run-image', { method: 'POST', body: form });
    }

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
    
    // 使用源节点实际宽度计算偏移
    const sourceNodeEl = document.querySelector(`.node[data-node-id="${nodeId}"]`);
    const sourceWidth = sourceNodeEl ? sourceNodeEl.offsetWidth : 300;
    for(let i = 0; i < videoCount; i++){
      const offsetY = i * 280;
      const newVideoNodeId = createVideoNode({
        x: node.x + sourceWidth + 60,
        y: node.y + offsetY,
        checkCollision: true
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
    
    renderAllConnections();
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
        renderAllConnections();
        
        generateBtn.disabled = false;
        generateBtn.textContent = '生成视频';
        showToast(`分镜视频生成成功！已创建 ${videoUrls.length} 个视频节点`, 'success');
        
        // 刷新用户算力显示
        if(typeof fetchComputingPower === 'function'){
          fetchComputingPower();
        }
        
        safeAutoSave()
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
