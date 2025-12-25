// 分镜节点生成视频功能
async function generateShotFrameVideo(nodeId, node){
  if(!node.data.previewImageUrl){
    showToast('请先生成分镜图', 'warning');
    return;
  }

  const generateBtn = document.querySelector(`.node[data-node-id="${nodeId}"] .shot-frame-generate-video-btn`);
  if(!generateBtn) return;

  try {
    generateBtn.disabled = true;
    generateBtn.textContent = '生成中...';

    // 获取预览图的URL
    const imageUrl = node.data.previewImageUrl;
    
    // 解析视频提示词
    let videoPromptData = {};
    try {
      videoPromptData = JSON.parse(node.data.videoPrompt || '{}');
    } catch(e){
      console.error('Failed to parse video prompt:', e);
    }

    // 构建视频提示词文本
    const promptParts = [];
    if(videoPromptData.description) promptParts.push(videoPromptData.description);
    if(videoPromptData.shot_type) promptParts.push(`镜头类型: ${videoPromptData.shot_type}`);
    if(videoPromptData.camera_movement) promptParts.push(`镜头运动: ${videoPromptData.camera_movement}`);
    if(videoPromptData.time_of_day) promptParts.push(`时间: ${videoPromptData.time_of_day}`);
    if(videoPromptData.weather) promptParts.push(`天气: ${videoPromptData.weather}`);
    
    const videoPrompt = promptParts.join('，');
    const duration = node.data.duration || 5;
    const count = node.data.videoDrawCount || 1;

    showToast(`正在生成 ${count} 个视频...`, 'info');

    // 从URL获取图片文件
    const response = await fetch(proxyImageUrl(imageUrl));
    const blob = await response.blob();
    const file = new File([blob], 'shot_frame.png', { type: 'image/png' });

    // 调用图生视频API
    const userId = localStorage.getItem('user_id') || '1';
    const authToken = localStorage.getItem('auth_token') || '';
    const form = new FormData();
    
    form.append('image', file);
    form.append('prompt', videoPrompt);
    form.append('duration', duration);
    form.append('count', count);
    
    if(userId){
      form.append('user_id', userId);
    }
    if(authToken){
      form.append('auth_token', authToken);
    }

    const res = await fetch('/api/image-to-video', {
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
          showToast('视频生成失败，未获取到结果', 'error');
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
        showToast(`生成失败: ${error}`, 'error');
        generateBtn.disabled = false;
        generateBtn.textContent = '生成视频';
      }
    );
    
  } catch(error){
    console.error('生成分镜视频失败:', error);
    showToast(`生成失败: ${error.message || error}`, 'error');
    generateBtn.disabled = false;
    generateBtn.textContent = '生成视频';
  }
}
