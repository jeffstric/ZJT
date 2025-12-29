
    // 轮询视频状态
    function pollVideoStatus(projectIds, onProgress, onComplete, onError, onTaskUpdate){
      let pollCount = 0;
      const maxPolls = 60; // 最多轮询60次（10分钟）
      
      const poll = async () => {
        pollCount++;
        try {
          const result = await checkVideoStatus(projectIds);
          
          // 如果有任务更新回调，实时更新每个任务的状态
          if(onTaskUpdate && result.tasks){
            onTaskUpdate(result.tasks);
          }
          
          if(result.status === 'SUCCESS' || result.status === 'FAILED'){
            // SUCCESS或FAILED都表示所有任务已完成，调用onComplete处理
            // onComplete会根据每个任务的详细状态来更新视频节点
            onComplete(result);
          } else {
            onProgress(`生成中... (${pollCount * 10}秒)`);
            if(pollCount < maxPolls){
              setTimeout(poll, 10000);
            } else {
              onError('生成超时，请稍后查看结果');
            }
          }
        } catch(e){
          console.error('Poll error:', e);
          if(pollCount < maxPolls){
            setTimeout(poll, 10000);
          } else {
            onError('查询状态失败');
          }
        }
      };
      
      poll();
    }

    // 序列化工作流数据（用于保存）
    function serializeWorkflow(){
      // 只保存必要的数据，排除File对象和临时URL
      const serializableNodes = state.nodes.map(node => {
        const nodeData = { ...node.data };
        // 移除File对象
        if(nodeData.file) delete nodeData.file;
        if(nodeData.startFile) delete nodeData.startFile;
        if(nodeData.endFile) delete nodeData.endFile;
        // 对于本地blob URL，需要清除（这些是临时的）
        // 服务器URL（以http开头）保留
        if(nodeData.url && nodeData.url.startsWith('blob:')) nodeData.url = '';
        if(nodeData.startUrl && nodeData.startUrl.startsWith('blob:')) nodeData.startUrl = '';
        if(nodeData.endUrl && nodeData.endUrl.startsWith('blob:')) nodeData.endUrl = '';
        if(nodeData.preview && nodeData.preview.startsWith('data:') && nodeData.url) nodeData.preview = nodeData.url;
        if(nodeData.startPreview && nodeData.startPreview.startsWith('data:') && nodeData.startUrl) nodeData.startPreview = nodeData.startUrl;
        if(nodeData.endPreview && nodeData.endPreview.startsWith('data:') && nodeData.endUrl) nodeData.endPreview = nodeData.endUrl;
        
        return {
          id: node.id,
          type: node.type,
          title: node.title,
          x: node.x,
          y: node.y,
          data: nodeData
        };
      });

      return {
        version: '1.0',
        ratio: state.ratio,
        viewport: {
          panX: state.panX,
          panY: state.panY,
          zoom: state.zoom
        },
        nextNodeId: state.nextNodeId,
        nextConnId: state.nextConnId,
        nextImgConnId: state.nextImgConnId,
        nextFirstFrameConnId: state.nextFirstFrameConnId,
        nodes: serializableNodes,
        connections: state.connections.map(c => ({ id: c.id, from: c.from, to: c.to })),
        imageConnections: state.imageConnections.map(c => ({ id: c.id, from: c.from, to: c.to, portType: c.portType })),
        firstFrameConnections: state.firstFrameConnections.map(c => ({ id: c.id, from: c.from, to: c.to })),
        timeline: {
          clips: state.timeline.clips,
          nextClipId: state.timeline.nextClipId,
        }
      };
    }

    // 保存工作流
    async function saveWorkflow(){
      const saveBtn = document.getElementById('saveBtn');
      const saveBtnText = document.getElementById('saveBtnText');
      const workflowId = getWorkflowIdFromUrl();

      if(!workflowId){
        showToast('请先从列表创建或选择工作流', 'error');
        return;
      }

      saveBtn.disabled = true;
      saveBtnText.textContent = '保存中...';

      try {
        const workflowData = serializeWorkflow();
        
        const response = await fetch(`/api/video-workflow/${workflowId}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': getAuthToken(),
            'X-User-Id': getUserId()
          },
          body: JSON.stringify({
            workflow_data: workflowData
          })
        });

        const result = await response.json();
        
        if(result.code === 0){
          showToast('保存成功', 'success');
        } else {
          showToast(result.message || '保存失败', 'error');
        }
      } catch(error){
        console.error('Save error:', error);
        showToast('保存失败: ' + error.message, 'error');
      } finally {
        saveBtn.disabled = false;
        saveBtnText.textContent = '保存';
      }
    }

    // 自动保存（静默保存，不显示提示）
    async function autoSaveWorkflow(){
      const workflowId = getWorkflowIdFromUrl();
      if(!workflowId) return;
      
      // 如果没有节点，不自动保存
      if(state.nodes.length === 0) return;

      try {
        const workflowData = serializeWorkflow();
        
        const response = await fetch(`/api/video-workflow/${workflowId}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': getAuthToken(),
            'X-User-Id': getUserId()
          },
          body: JSON.stringify({
            workflow_data: workflowData
          })
        });

        const result = await response.json();
        
        if(result.code === 0){
          console.log('自动保存成功:', new Date().toLocaleTimeString());
        } else {
          console.warn('自动保存失败:', result.message);
        }
      } catch(error){
        console.error('自动保存错误:', error);
      }
    }

    // 启动自动保存定时器（每3分钟）
    let autoSaveTimer = null;
    function startAutoSave(){
      if(autoSaveTimer) clearInterval(autoSaveTimer);
      autoSaveTimer = setInterval(() => {
        autoSaveWorkflow();
      }, 3 * 60 * 1000); // 3分钟
    }

    // 停止自动保存
    function stopAutoSave(){
      if(autoSaveTimer){
        clearInterval(autoSaveTimer);
        autoSaveTimer = null;
      }
    }

    // 加载工作流
    async function loadWorkflow(workflowId){
      if(!workflowId) return;

      try {
        const response = await fetch(`/api/video-workflow/${workflowId}`, {
          headers: {
            'Authorization': getAuthToken(),
            'X-User-Id': getUserId()
          }
        });

        const result = await response.json();
        
        if(result.code === 0 && result.data){
          const workflow = result.data;
          
          // 更新页面标题
          if(workflow.name){
            document.querySelector('.brand-title').textContent = workflow.name;
            document.title = workflow.name + ' - 视频工作流';
          }
          
          // 加载画风信息
          if(workflow.style){
            state.style.name = workflow.style;
          }
          if(workflow.style_reference_image){
            state.style.referenceImageUrl = workflow.style_reference_image;
          }
          
          // 加载默认世界
          if(workflow.default_world_id){
            state.defaultWorldId = workflow.default_world_id;
            const defaultWorldSelect = document.getElementById('defaultWorldSelect');
            if(defaultWorldSelect){
              defaultWorldSelect.value = workflow.default_world_id;
              // 更新视觉状态（移除红色警告）
              if(typeof updateWorldSelectorState === 'function'){
                updateWorldSelectorState();
              }
            }
          }
          
          // 如果有workflow_data，恢复状态
          if(workflow.workflow_data){
            restoreWorkflow(workflow.workflow_data);
          }
        } else {
          showToast(result.message || '加载工作流失败', 'error');
        }
      } catch(error){
        console.error('Load error:', error);
        showToast('加载工作流失败', 'error');
      }
    }

    // 恢复工作流状态
    function restoreWorkflow(data){
      // 清除现有节点
      for(const node of [...state.nodes]){
        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        if(el) el.remove();
      }
      
      // 重置状态
      state.nodes = [];
      state.connections = [];
      state.imageConnections = [];
      state.firstFrameConnections = [];
      state.selectedNodeId = null;
      state.selectedConnId = null;
      state.selectedImgConnId = null;
      state.selectedFirstFrameConnId = null;
      
      // 恢复视口
      if(data.viewport){
        state.panX = data.viewport.panX || 0;
        state.panY = data.viewport.panY || 0;
        state.zoom = data.viewport.zoom || 1;
        applyTransform();
        updateZoomLevel();
      }
      
      // 恢复比例
      if(data.ratio){
        state.ratio = data.ratio;
        ratioSelectEl.value = data.ratio;
      }
      
      // 恢复ID计数器
      state.nextNodeId = data.nextNodeId || 1;
      state.nextConnId = data.nextConnId || 1;
      state.nextImgConnId = data.nextImgConnId || 1;
      state.nextFirstFrameConnId = data.nextFirstFrameConnId || 1;
      
      // 恢复节点
      if(data.nodes && Array.isArray(data.nodes)){
        for(const nodeData of data.nodes){
          restoreNode(nodeData);
        }
      }
      
      // 恢复连接
      if(data.connections && Array.isArray(data.connections)){
        state.connections = data.connections;
      }
      
      if(data.imageConnections && Array.isArray(data.imageConnections)){
        state.imageConnections = data.imageConnections;
      }
      
      if(data.firstFrameConnections && Array.isArray(data.firstFrameConnections)){
        state.firstFrameConnections = data.firstFrameConnections;
      }
      
      // 恢复时间轴
      if(data.timeline){
        state.timeline.clips = data.timeline.clips || [];
        state.timeline.nextClipId = data.timeline.nextClipId || 1;
        state.timeline.visible = state.timeline.clips.length > 0;
        renderTimeline();
      }
      
      // 重新渲染
      renderConnections();
      renderImageConnections();
      renderFirstFrameConnections();
      renderMinimap();
      
      // 恢复完成后，更新所有分镜节点的图片选择菜单
      setTimeout(() => {
        state.nodes.forEach(node => {
          if(node.type === 'shot_frame' && node.updatePreview){
            node.updatePreview();
          }
        });
      }, 100);
    }

    // 恢复单个节点
    function restoreNode(nodeData){
      if(nodeData.type === 'image_to_video'){
        createImageToVideoNodeWithData(nodeData);
      } else if(nodeData.type === 'video'){
        createVideoNodeWithData(nodeData);
      } else if(nodeData.type === 'image'){
        createImageNodeWithData(nodeData);
      } else if(nodeData.type === 'image_edit'){
        // 兼容旧的 image_edit 节点，转换为新的 image 节点
        nodeData.type = 'image';
        nodeData.data.url = nodeData.data.imageUrl || nodeData.data.url || '';
        createImageNodeWithData(nodeData);
      } else if(nodeData.type === 'script'){
        createScriptNodeWithData(nodeData);
      } else if(nodeData.type === 'shot_group'){
        createShotGroupNodeWithData(nodeData);
      } else if(nodeData.type === 'shot_frame'){
        createShotFrameNodeWithData(nodeData);
      } else if(nodeData.type === 'character'){
        createCharacterNodeWithData(nodeData);
      } else if(nodeData.type === 'location'){
        createLocationNodeWithData(nodeData);
      }
    }

    // ============ 画风管理功能 ============
    
    const styleModal = document.getElementById('styleModal');
    const styleModalClose = document.getElementById('styleModalClose');
    const styleNameInput = document.getElementById('styleNameInput');
    const styleImageInput = document.getElementById('styleImageInput');
    const styleImagePreview = document.getElementById('styleImagePreview');
    const styleImagePreviewImg = document.getElementById('styleImagePreviewImg');
    const styleImageRemoveBtn = document.getElementById('styleImageRemoveBtn');
    const styleSaveBtn = document.getElementById('styleSaveBtn');
    const styleCancelBtn = document.getElementById('styleCancelBtn');
    
    // 打开画风设置模态框
    function openStyleModal(){
      styleNameInput.value = state.style.name || '';
      
      if(state.style.referenceImageUrl){
        styleImagePreviewImg.src = state.style.referenceImageUrl;
        styleImagePreview.style.display = 'block';
      } else {
        styleImagePreview.style.display = 'none';
      }
      
      styleModal.classList.add('show');
      styleModal.setAttribute('aria-hidden', 'false');
    }
    
    // 关闭画风设置模态框
    function closeStyleModal(){
      styleModal.classList.remove('show');
      styleModal.setAttribute('aria-hidden', 'true');
      styleImageInput.value = '';
    }
    
    // 保存画风设置
    async function saveStyleSettings(){
      const workflowId = getWorkflowIdFromUrl();
      if(!workflowId){
        showToast('请先从列表创建或选择工作流', 'error');
        return;
      }
      
      const styleName = styleNameInput.value.trim();
      let styleImageUrl = state.style.referenceImageUrl;
      
      // 如果用户选择了新图片，先上传
      if(styleImageInput.files && styleImageInput.files.length > 0){
        const file = styleImageInput.files[0];
        styleImageUrl = await uploadFile(file);
        if(!styleImageUrl){
          showToast('参考图上传失败', 'error');
          return;
        }
      }
      
      styleSaveBtn.disabled = true;
      styleSaveBtn.textContent = '保存中...';
      
      try {
        const response = await fetch(`/api/video-workflow/${workflowId}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': getAuthToken(),
            'X-User-Id': getUserId()
          },
          body: JSON.stringify({
            style: styleName || null,
            style_reference_image: styleImageUrl || null
          })
        });
        
        const result = await response.json();
        
        if(result.code === 0){
          state.style.name = styleName;
          state.style.referenceImageUrl = styleImageUrl;
          showToast('画风设置已保存', 'success');
          closeStyleModal();
        } else {
          showToast(result.message || '保存失败', 'error');
        }
      } catch(error){
        console.error('Save style error:', error);
        showToast('保存失败: ' + error.message, 'error');
      } finally {
        styleSaveBtn.disabled = false;
        styleSaveBtn.textContent = '保存';
      }
    }
    
    // 画风图片选择事件
    styleImageInput.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if(file){
        const reader = new FileReader();
        reader.onload = (e) => {
          styleImagePreviewImg.src = e.target.result;
          styleImagePreview.style.display = 'block';
        };
        reader.readAsDataURL(file);
      }
    });
    
    // 移除画风参考图
    styleImageRemoveBtn.addEventListener('click', () => {
      styleImagePreview.style.display = 'none';
      styleImageInput.value = '';
      state.style.referenceImageUrl = '';
    });
    
    // 画风按钮点击事件
    document.getElementById('styleBtn').addEventListener('click', (e) => {
      e.stopPropagation();
      openStyleModal();
    });
    
    // 画风模态框关闭事件
    styleModalClose.addEventListener('click', () => {
      closeStyleModal();
    });
    
    styleCancelBtn.addEventListener('click', () => {
      closeStyleModal();
    });
    
    styleSaveBtn.addEventListener('click', () => {
      saveStyleSettings();
    });
    
    styleModal.addEventListener('click', (e) => {
      if(e.target === styleModal) closeStyleModal();
    });
    
    // ============ 画风管理功能结束 ============

    async function generateEditedImage(file, prompt, ratio, model, count){
      const userId = localStorage.getItem('user_id');
      const authToken = getAuthToken();
      const form = new FormData();

      form.append('image', file);
      form.append('prompt', prompt || '');
      form.append('ratio', ratio || '9:16');
      form.append('count', count || 1);
      form.append('model', model || 'gemini-2.5-pro-image-preview');
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
      if(data.project_ids && data.project_ids.length > 0){
        return {
          projectIds: data.project_ids,
          status: data.status
        };
      }
      throw new Error(data.detail || data.message || '提交任务失败');
    }

    async function fetchFileFromUrl(url){
      const res = await fetch(proxyImageUrl(url));
      if(!res.ok) throw new Error('无法获取图片内容');
      const blob = await res.blob();
      const name = 'image.png';
      try{
        return new File([blob], name, { type: blob.type || 'image/png' });
      } catch(e){
        // Fallback for older browsers
        blob.name = name;
        return blob;
      }
    }


    // 带数据创建图生视频节点（复用createImageToVideoNode的逻辑）
    function createImageToVideoNodeWithData(nodeData){
      // 临时保存nextNodeId
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;
      
      // 调用原有的创建函数
      createImageToVideoNode({ x: nodeData.x, y: nodeData.y });
      
      // 恢复nextNodeId为最大值
      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);
      
      // 更新节点数据
      const node = state.nodes.find(n => n.id === nodeData.id);
      if(node && nodeData.data){
        node.data.prompt = nodeData.data.prompt || '';
        node.data.startUrl = nodeData.data.startUrl || '';
        node.data.endUrl = nodeData.data.endUrl || '';
        node.data.duration = nodeData.data.duration || 15;
        node.data.ratio = nodeData.data.ratio || state.ratio || '16:9';
        node.data.model = nodeData.data.model || 'sora';
        node.data.drawCount = nodeData.data.drawCount || 1;
        node.data.motionLevel = nodeData.data.motionLevel || 5;
        node.data.useMotion = nodeData.data.useMotion || false;
        
        // 更新DOM显示
        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        if(el){
          // 更新提示词
          const promptEl = el.querySelector('.prompt');
          if(promptEl) promptEl.value = node.data.prompt;
          
          // 更新时长选择
          const durationSelect = el.querySelector('.duration-select');
          if(durationSelect) durationSelect.value = node.data.duration;
          
          // 先更新模型选择
          const modelSelect = el.querySelector('.model-select');
          if(modelSelect) modelSelect.value = node.data.model;
          
          // 根据模型更新比例选项，然后设置比例值
          const ratioSelect = el.querySelector('.ratio-select');
          if(ratioSelect && modelSelect) {
            const model = node.data.model;
            if(model === 'sora') {
              // sora只支持16:9和9:16
              ratioSelect.innerHTML = `
                <option value="9:16">9:16</option>
                <option value="16:9">16:9</option>
              `;
              // 如果保存的比例不在支持列表中，使用16:9
              if(node.data.ratio !== '9:16' && node.data.ratio !== '16:9') {
                node.data.ratio = '16:9';
              }
            } else {
              // 其他模型支持所有比例
              ratioSelect.innerHTML = `
                <option value="9:16">9:16</option>
                <option value="3:4">3:4</option>
                <option value="1:1">1:1</option>
                <option value="4:3">4:3</option>
                <option value="16:9">16:9</option>
              `;
            }
            ratioSelect.value = node.data.ratio;
          }
          
          // 更新抽卡次数标签
          const genCountLabel = el.querySelector('.gen-count-label');
          if(genCountLabel) genCountLabel.textContent = `抽卡次数：X${node.data.drawCount}`;
          
          // 更新首帧图片
          if(node.data.startUrl){
            const startPreviewRow = el.querySelector('.start-preview-row');
            const startPreview = el.querySelector('.start-preview');
            const startImagePort = el.querySelector('.start-image-port');
            if(startPreview){
              startPreview.src = proxyImageUrl(node.data.startUrl);
              node.data.startPreview = node.data.startUrl;
            }
            if(startPreviewRow) startPreviewRow.style.display = 'flex';
            if(startImagePort) startImagePort.classList.add('disabled');
          }
          
          // 更新尾帧图片
          if(node.data.endUrl){
            const endPreviewRow = el.querySelector('.end-preview-row');
            const endPreview = el.querySelector('.end-preview');
            const endImagePort = el.querySelector('.end-image-port');
            if(endPreview){
              endPreview.src = proxyImageUrl(node.data.endUrl);
              node.data.endPreview = node.data.endUrl;
            }
            if(endPreviewRow) endPreviewRow.style.display = 'flex';
            if(endImagePort) endImagePort.classList.add('disabled');
          }
        }
      }
    }

    // 带数据创建视频节点（复用createVideoNode的逻辑）
    function createVideoNodeWithData(nodeData){
      // 临时保存nextNodeId
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;
      
      // 调用原有的创建函数
      createVideoNode({ x: nodeData.x, y: nodeData.y });
      
      // 恢复nextNodeId为最大值
      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);
      
      // 更新节点数据
      const node = state.nodes.find(n => n.id === nodeData.id);
      if(node && nodeData.data){
        node.data.url = nodeData.data.url || '';
        node.data.name = nodeData.data.name || '';
        node.data.duration = nodeData.data.duration || 0;
        // 如果有URL，显示预览
        if(node.data.url){
          const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
          if(el){
            const previewField = el.querySelector('.video-preview-field');
            const thumbVideo = el.querySelector('.video-thumb');
            const nameEl = el.querySelector('.video-name');
            if(previewField && thumbVideo && nameEl){
              thumbVideo.src = proxyDownloadUrl(node.data.url);
              thumbVideo.muted = true;
              thumbVideo.loop = true;
              const displayName = node.data.name.length > 10 ? node.data.name.substring(0, 10) + '...' : node.data.name;
              nameEl.textContent = displayName;
              nameEl.title = node.data.name;
              previewField.style.display = 'block';
              
              // 如果没有时长，尝试从视频获取
              if(!node.data.duration){
                thumbVideo.addEventListener('loadedmetadata', () => {
                  if(thumbVideo.duration && isFinite(thumbVideo.duration)){
                    node.data.duration = Math.round(thumbVideo.duration);
                  }
                }, { once: true });
              }
            }
          }
        }
      }
    }

    // 带数据创建图片节点（复用createImageNode的逻辑）
    function createImageNodeWithData(nodeData){
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;
      
      createImageNode({ x: nodeData.x, y: nodeData.y });
      
      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);
      
      const node = state.nodes.find(n => n.id === nodeData.id);
      if(node && nodeData.data){
        node.data.url = nodeData.data.url || '';
        node.data.name = nodeData.data.name || '';
        node.data.preview = nodeData.data.preview || nodeData.data.url || '';
        node.data.prompt = nodeData.data.prompt || '';
        node.data.ratio = nodeData.data.ratio || '9:16';
        node.data.model = nodeData.data.model || 'gemini-2.5-pro-image-preview';
        node.data.drawCount = nodeData.data.drawCount || 1;
        
        // 恢复节点标题
        if(nodeData.title){
          node.title = nodeData.title;
        }
        
        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        if(el){
          const promptEl = el.querySelector('.image-prompt');
          const ratioEl = el.querySelector('.image-ratio');
          const modelEl = el.querySelector('.image-model');
          const drawCountLabel = el.querySelector('.image-draw-count-label');
          const titleEl = el.querySelector('.node-title');
          
          if(promptEl) promptEl.value = node.data.prompt;
          if(ratioEl) ratioEl.value = node.data.ratio;
          if(modelEl) modelEl.value = node.data.model;
          if(drawCountLabel) drawCountLabel.textContent = `抽卡次数：X${node.data.drawCount}`;
          if(titleEl && nodeData.title) titleEl.textContent = nodeData.title;
          
          if(node.data.url || node.data.preview){
            const previewImg = el.querySelector('.image-preview');
            const previewRow = el.querySelector('.image-preview-row');
            if(previewImg){
              const raw = node.data.url || node.data.preview;
              previewImg.src = proxyImageUrl(raw);
              if(previewRow) previewRow.style.display = 'flex';
            }
          }
        }
      }
    }

    // 带数据创建剧本节点
    function createScriptNodeWithData(nodeData){
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;
      
      createScriptNode({ x: nodeData.x, y: nodeData.y });
      
      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);
      
      const node = state.nodes.find(n => n.id === nodeData.id);
      if(node && nodeData.data){
        node.data.scriptContent = nodeData.data.scriptContent || '';
        node.data.name = nodeData.data.name || '';
        node.data.maxGroupDuration = nodeData.data.maxGroupDuration || 15;
        node.data.parsedData = nodeData.data.parsedData || null;
        
        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        if(el){
          const textareaEl = el.querySelector('.script-textarea');
          const durationSelectEl = el.querySelector('.script-duration-select');
          const splitBtn = el.querySelector('.script-split-btn');
          const infoField = el.querySelector('.script-info-field');
          const nameEl = el.querySelector('.script-name');
          const lengthEl = el.querySelector('.script-length');
          const charCountEl = el.querySelector('.script-char-count');
          
          if(textareaEl) textareaEl.value = node.data.scriptContent;
          if(durationSelectEl) durationSelectEl.value = String(node.data.maxGroupDuration);
          
          if(node.data.scriptContent && node.data.scriptContent.trim().length > 0){
            if(splitBtn) splitBtn.disabled = false;
            if(nameEl) nameEl.textContent = node.data.name || '来源: 已加载';
            if(lengthEl) lengthEl.textContent = `长度: ${node.data.scriptContent.length} 字符`;
            if(infoField) infoField.style.display = 'block';
            if(charCountEl) charCountEl.textContent = `${node.data.scriptContent.length}/2000`;
          }
        }
      }
    }

    // 带数据创建分镜组节点
    function createShotGroupNodeWithData(nodeData){
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;
      
      createShotGroupNode({ 
        x: nodeData.x, 
        y: nodeData.y,
        shotGroupData: nodeData.data || {},
        scriptData: nodeData.data.scriptData || {}
      });
      
      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);
    }

    // 带数据创建分镜节点
    function createShotFrameNodeWithData(nodeData){
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;
      
      createShotFrameNode({ 
        x: nodeData.x, 
        y: nodeData.y,
        shotData: nodeData.data.shotJson || {}
      });
      
      // 恢复节点数据
      const node = state.nodes.find(n => n.id === nodeData.id);
      if(node && nodeData.data){
        node.data = { ...node.data, ...nodeData.data };
        node.title = nodeData.title || node.title;
        
        const nodeEl = document.querySelector(`.node[data-node-id="${nodeData.id}"]`);
        if(nodeEl){
          // 如果有生成的图片URL，更新UI显示
          if(nodeData.data.imageUrl){
            const imageFieldEl = nodeEl.querySelector('.shot-frame-image-field');
            const imageEl = nodeEl.querySelector('.shot-frame-image');
            
            if(imageFieldEl && imageEl){
              imageEl.src = nodeData.data.imageUrl;
              imageFieldEl.style.display = 'block';
            }
          }
          
          // 恢复视频首帧
          if(nodeData.data.previewImageUrl){
            const previewFieldEl = nodeEl.querySelector('.shot-frame-preview-field');
            const previewImageEl = nodeEl.querySelector('.shot-frame-preview-image');
            
            if(previewFieldEl && previewImageEl){
              previewImageEl.src = proxyImageUrl(nodeData.data.previewImageUrl);
              previewImageEl.style.display = 'block';
              previewFieldEl.style.display = 'block';
            }
          }
          
          // 恢复抽卡次数显示
          if(nodeData.data.drawCount){
            const drawCountLabel = nodeEl.querySelector('.shot-frame-draw-count-label');
            if(drawCountLabel){
              drawCountLabel.textContent = `抽卡次数：X${nodeData.data.drawCount}`;
            }
          }
          
          // 恢复视频抽卡次数显示
          if(nodeData.data.videoDrawCount){
            const videoDrawCountLabel = nodeEl.querySelector('.shot-frame-video-draw-count-label');
            if(videoDrawCountLabel){
              videoDrawCountLabel.textContent = `抽卡次数：X${nodeData.data.videoDrawCount}`;
            }
          }
        }
      }
      
      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);
    }
