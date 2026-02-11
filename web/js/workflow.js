
    const computingPowerValueEl = document.getElementById('computingPowerValue');
    const computingPowerRefreshBtn = document.getElementById('computingPowerRefreshBtn');
    const computingPowerChip = document.getElementById('computingPowerChip');

    function updateComputingPowerLabel(value){
      if(computingPowerValueEl){
        computingPowerValueEl.textContent = value;
      }
    }

    function redirectToLogin(){
      const currentUrl = window.location.href;
      localStorage.setItem('redirect_after_login', currentUrl);
      window.location.href = '/index.html';
    }

    async function fetchComputingPower(){
      const token = getAuthToken();
      if(!token){
        updateComputingPowerLabel('未登录');
        computingPowerRefreshBtn?.setAttribute('disabled', 'true');
        redirectToLogin();
        return;
      }

      computingPowerRefreshBtn?.setAttribute('disabled', 'true');
      updateComputingPowerLabel('加载中...');

      try{
        const response = await fetch('/api/user/computing_power', {
          headers: {
            'Authorization': `Bearer ${token}`
          }
        });
        
        if(!response.ok){
          if(response.status === 400 || response.status === 401 || response.status === 403){
            console.warn('认证失败，跳转到登录页');
            redirectToLogin();
            return;
          }
          throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        if(data.success && data.data){
          updateComputingPowerLabel(data.data.computing_power ?? 0);
        }else{
          console.warn('fetchComputingPower:', data.message);
          if(data.message && (data.message.includes('认证') || data.message.includes('登录'))){
            redirectToLogin();
          }else{
            updateComputingPowerLabel('0');
          }
        }
      }catch(error){
        console.error('fetchComputingPower error:', error);
        updateComputingPowerLabel('错误');
      }finally{
        computingPowerRefreshBtn?.removeAttribute('disabled');
      }
    }

    computingPowerRefreshBtn?.addEventListener('click', () => {
      fetchComputingPower();
    });

    let computingPowerTimer = null;

    function startComputingPowerTimer(){
      if(computingPowerTimer){
        clearInterval(computingPowerTimer);
      }
      computingPowerTimer = setInterval(() => {
        fetchComputingPower();
      }, 5 * 60 * 1000);
    }

    function stopComputingPowerTimer(){
      if(computingPowerTimer){
        clearInterval(computingPowerTimer);
        computingPowerTimer = null;
      }
    }

    // 算力配置（用于节点算力预估）
    let taskComputingPowerConfig = {};
    // 视频模型时长选项配置（全局缓存，只请求一次）
    let videoModelDurationOptions = {};
    
    async function fetchComputingPowerConfig(){
      try {
        const response = await fetch('/api/computing-power-config');
        if(response.ok){
          const data = await response.json();
          if(data.success && data.data){
            if(data.data.task_computing_power){
              taskComputingPowerConfig = data.data.task_computing_power;
              console.log('[算力配置] 已加载:', taskComputingPowerConfig);
              // 配置加载完成后，更新所有图生视频节点和分镜节点的算力显示
              updateAllImageToVideoNodesPower();
              updateAllShotFrameNodesPower();
            }
            if(data.data.video_model_duration_options){
              videoModelDurationOptions = data.data.video_model_duration_options;
              console.log('[视频模型时长配置] 已加载:', videoModelDurationOptions);
            }
          }
        }
      } catch(error){
        console.error('[算力配置] 加载失败:', error);
      }
    }
    
    // 获取算力配置的函数（供节点使用）
    function getTaskComputingPowerConfig(){
      return taskComputingPowerConfig;
    }
    
    // 获取视频模型时长选项配置（供节点使用）
    function getVideoModelDurationOptions(){
      return videoModelDurationOptions;
    }
    
    // 计算视频生成算力（公共函数）
    function calculateVideoGenerationPower(videoModel, duration){
      if(!taskComputingPowerConfig || Object.keys(taskComputingPowerConfig).length === 0){
        return 0;
      }
      
      let power = 0;
      
      if(videoModel === 'sora2'){
        power = taskComputingPowerConfig[3] || 0;
      } else if(videoModel === 'ltx2'){
        power = taskComputingPowerConfig[10] || 0;
      } else if(videoModel === 'wan22'){
        const wan22Power = taskComputingPowerConfig[11];
        if(typeof wan22Power === 'object'){
          power = wan22Power[duration] || wan22Power[5] || 0;
        } else {
          power = wan22Power || 0;
        }
      } else if(videoModel === 'kling'){
        const klingPower = taskComputingPowerConfig[12];
        if(typeof klingPower === 'object'){
          power = klingPower[duration] || klingPower[5] || 0;
        } else {
          power = klingPower || 0;
        }
      } else if(videoModel === 'vidu'){
        const viduPower = taskComputingPowerConfig[14];
        if(typeof viduPower === 'object'){
          power = viduPower[duration] || viduPower[5] || 0;
        } else {
          power = viduPower || 0;
        }
      } else if(videoModel === 'veo3'){
        power = taskComputingPowerConfig[15] || 0;
      }
      
      return power;
    }
    
    // 更新所有图生视频节点的算力显示
    function updateAllImageToVideoNodesPower(){
      if(!state || !state.nodes) return;
      
      state.nodes.forEach(node => {
        if(node.type === 'image_to_video'){
          const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
          if(el){
            const computingPowerValue = el.querySelector('.computing-power-value');
            const computingPowerDetail = el.querySelector('.computing-power-detail');
            if(computingPowerValue && computingPowerDetail){
              const videoModel = node.data.videoModel || 'sora2';
              const duration = node.data.duration || 10;
              const singlePower = calculateVideoGenerationPower(videoModel, duration);
              const count = node.data.drawCount || 1;
              const totalPower = singlePower * count;
              computingPowerValue.textContent = `${totalPower} 算力`;
              computingPowerDetail.textContent = `单个 ${singlePower} 算力 × ${count} 个 = ${totalPower} 算力`;
            }
          }
        }
      });
    }
    
    // 更新所有分镜节点的视频算力显示
    function updateAllShotFrameNodesPower(){
      if(!state || !state.nodes) return;
      
      state.nodes.forEach(node => {
        if(node.type === 'shot_frame'){
          const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
          if(el){
            const computingPowerValue = el.querySelector('.shot-frame-computing-power-value');
            const computingPowerDetail = el.querySelector('.shot-frame-computing-power-detail');
            if(computingPowerValue && computingPowerDetail){
              const videoModel = node.data.videoModel || 'sora2';
              const duration = node.data.videoDuration || 10;
              const singlePower = calculateVideoGenerationPower(videoModel, duration);
              const count = node.data.videoDrawCount || 1;
              const totalPower = singlePower * count;
              computingPowerValue.textContent = `${totalPower} 算力`;
              computingPowerDetail.textContent = `单个 ${singlePower} 算力 × ${count} 个 = ${totalPower} 算力`;
            }
          }
        }
      });
    }

    document.addEventListener('DOMContentLoaded', () => {
      if(computingPowerChip){
        fetchComputingPower();
        startComputingPowerTimer();
      }
      // 加载算力配置
      fetchComputingPowerConfig();
    });

    window.addEventListener('beforeunload', () => {
      stopComputingPowerTimer();
    });

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
        defaultWorldId: state.defaultWorldId,
        viewport: {
          panX: state.panX,
          panY: state.panY,
          zoom: state.zoom
        },
        nextNodeId: state.nextNodeId,
        nextConnId: state.nextConnId,
        nextImgConnId: state.nextImgConnId,
        nextFirstFrameConnId: state.nextFirstFrameConnId,
        nextVideoConnId: state.nextVideoConnId,
        nextReferenceConnId: state.nextReferenceConnId,
        nextScriptId: state.nextScriptId,
        nodes: serializableNodes,
        connections: state.connections.map(c => ({ id: c.id, from: c.from, to: c.to })),
        imageConnections: state.imageConnections.map(c => ({ id: c.id, from: c.from, to: c.to, portType: c.portType })),
        firstFrameConnections: state.firstFrameConnections.map(c => ({ id: c.id, from: c.from, to: c.to })),
        videoConnections: state.videoConnections.map(c => ({ id: c.id, from: c.from, to: c.to })),
        referenceConnections: state.referenceConnections.map(c => ({ id: c.id, from: c.from, to: c.to })),
        timeline: {
          clips: state.timeline.clips.map(c => ({ ...c })),
          audioClips: state.timeline.audioClips.map(c => ({ ...c })),
          pillars: state.timeline.pillars.map(p => ({ ...p })),
          nextClipId: state.timeline.nextClipId,
          nextAudioClipId: state.timeline.nextAudioClipId,
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
            workflow_data: workflowData,
            default_world_id: state.defaultWorldId
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
    async function autoSaveWorkflow(options){
      const opts = options || {};
      if(!opts.skipHistory){
        captureHistorySnapshot();
      }
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
            workflow_data: workflowData,
            default_world_id: state.defaultWorldId
          })
        });

        const result = await response.json();
        
        if(result.code === 0){
          console.log('自动保存成功:', new Date().toLocaleTimeString(), 'defaultWorldId:', state.defaultWorldId);
        } else {
          console.warn('自动保存失败:', result.message);
        }
      } catch(error){
        console.error('自动保存错误:', error);
      }
    }

    function captureHistorySnapshot(){
      if(state.isRestoringHistory) return;
      try{
        const snapshot = serializeWorkflow();
        const serialized = JSON.stringify(snapshot);
        const currentEntry = state.history[state.historyPointer] || null;
        if(currentEntry && currentEntry.serialized === serialized){
          return;
        }
        
        if(state.historyPointer < state.history.length - 1){
          state.history = state.history.slice(0, state.historyPointer + 1);
        }
        
        state.history.push({ serialized });
        if(state.history.length > state.historyLimit){
          state.history.splice(0, state.history.length - state.historyLimit);
        }
        state.historyPointer = state.history.length - 1;
      }catch(error){
        console.warn('captureHistorySnapshot failed:', error);
      }
    }
    
    function resetHistoryWithCurrentState(){
      try{
        const snapshot = serializeWorkflow();
        const serialized = JSON.stringify(snapshot);
        state.history = [{ serialized }];
        state.historyPointer = 0;
      }catch(error){
        console.warn('resetHistoryWithCurrentState failed:', error);
        state.history = [];
        state.historyPointer = -1;
      }
    }
    
    async function undoWorkflowChange(){
      if(state.historyPointer <= 0){
        showToast('没有更多可撤销的操作', 'warning');
        return;
      }
      const targetIndex = state.historyPointer - 1;
      const entry = state.history[targetIndex];
      if(!entry){
        showToast('撤销失败', 'error');
        return;
      }
      try{
        const snapshot = JSON.parse(entry.serialized);
        state.historyPointer = targetIndex;
        state.isRestoringHistory = true;
        restoreWorkflow(snapshot);
        state.isRestoringHistory = false;
        showToast('已撤销上一步操作', 'info');
        autoSaveWorkflow({ skipHistory: true });
      }catch(error){
        state.isRestoringHistory = false;
        console.error('undoWorkflowChange error:', error);
        showToast('撤销失败', 'error');
      }
    }
    
    // 启动自动保存定时器（每3分钟）
    let autoSaveTimer = null;
    function startAutoSave(){
      if(autoSaveTimer) clearInterval(autoSaveTimer);
      autoSaveTimer = setInterval(() => {
        autoSaveWorkflow({ skipHistory: true });
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
            console.log('[加载工作流] 从服务器加载 default_world_id:', workflow.default_world_id);
            const defaultWorldSelect = document.getElementById('defaultWorldSelect');
            if(defaultWorldSelect){
              defaultWorldSelect.value = workflow.default_world_id;
              // 更新视觉状态（移除红色警告）
              if(typeof updateWorldSelectorState === 'function'){
                updateWorldSelectorState();
              }
            }
          }
          
          // 在恢复节点之前，先获取世界数据（角色、道具、场景），避免节点创建时数据为空
          await pollWorkflowNodeStatus();
          
          // 如果有workflow_data，恢复状态
          if(workflow.workflow_data){
            console.log('[加载工作流] workflow_data.defaultWorldId:', workflow.workflow_data.defaultWorldId);
            restoreWorkflow(workflow.workflow_data);
            console.log('[加载工作流] 恢复后 state.defaultWorldId:', state.defaultWorldId);
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
      const wasRestoring = state.isRestoringHistory;
      state.isRestoringHistory = true;
      try{
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
        state.videoConnections = [];
        state.selectedNodeId = null;
        state.selectedConnId = null;
        state.selectedImgConnId = null;
        state.selectedFirstFrameConnId = null;
        state.selectedVideoConnId = null;
        
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
        
        // 恢复默认世界ID
        const defaultWorldSelect = document.getElementById('defaultWorldSelect');
        const syncDefaultWorldSelector = () => {
          if(!defaultWorldSelect){
            return;
          }
          defaultWorldSelect.value = state.defaultWorldId == null ? '' : state.defaultWorldId;
          if(typeof updateWorldSelectorState === 'function'){
            updateWorldSelectorState();
          }
        };
        if(data.defaultWorldId !== undefined && data.defaultWorldId !== null){
          console.log('[恢复工作流] 从 workflow_data 恢复 defaultWorldId:', data.defaultWorldId);
          state.defaultWorldId = data.defaultWorldId;
          syncDefaultWorldSelector();
        }else{
          console.log('[恢复工作流] workflow_data 中没有有效的 defaultWorldId，保持当前值:', state.defaultWorldId);
          syncDefaultWorldSelector();
        }
        
        // 恢复ID计数器
        state.nextNodeId = data.nextNodeId || 1;
        state.nextConnId = data.nextConnId || 1;
        state.nextImgConnId = data.nextImgConnId || 1;
        state.nextFirstFrameConnId = data.nextFirstFrameConnId || 1;
        state.nextVideoConnId = data.nextVideoConnId || 1;
        state.nextReferenceConnId = data.nextReferenceConnId || 1;
        state.nextScriptId = data.nextScriptId || 1;
        
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
        
        if(data.videoConnections && Array.isArray(data.videoConnections)){
          state.videoConnections = data.videoConnections;
        }
        
        if(data.referenceConnections && Array.isArray(data.referenceConnections)){
          state.referenceConnections = data.referenceConnections;
        }
        
        // 恢复时间轴
        if(data.timeline){
          state.timeline.clips = data.timeline.clips || [];
          state.timeline.audioClips = data.timeline.audioClips || [];
          state.timeline.pillars = data.timeline.pillars || [];
          state.timeline.nextClipId = data.timeline.nextClipId || 1;
          state.timeline.nextAudioClipId = data.timeline.nextAudioClipId || 1;
          state.timeline.visible = state.timeline.clips.length > 0 || state.timeline.audioClips.length > 0;
          
          // 如果没有柱子数据但有片段，尝试自动迁移
          if(state.timeline.pillars.length === 0 && (state.timeline.clips.length > 0 || state.timeline.audioClips.length > 0)){
            console.log('[恢复工作流] 检测到历史数据，尝试自动迁移柱子...');
            // 延迟执行迁移，确保所有节点都已恢复
            setTimeout(() => {
              if(typeof autoMigratePillars === 'function'){
                const migrated = autoMigratePillars();
                if(migrated){
                  console.log('[恢复工作流] 历史数据迁移成功');
                  renderTimeline();
                  try{ autoSaveWorkflow(); } catch(e){}
                }
              }
            }, 500);
          }
          
          console.log(`[恢复工作流] 恢复了 ${state.timeline.pillars.length} 个柱子`);
          renderTimeline();
        }
        
        // 重新渲染
        renderConnections();
        renderImageConnections();
        renderFirstFrameConnections();
        renderVideoConnections();
        renderReferenceConnections();
        renderMinimap();
        
        // 恢复完成后，更新所有分镜节点的图片选择菜单和角色节点的按钮状态
        setTimeout(() => {
          state.nodes.forEach(node => {
            if(node.type === 'shot_frame' && node.updatePreview){
              node.updatePreview();
            }
            // 更新角色节点的创建角色卡按钮状态
            if(node.type === 'character'){
              updateCharacterCardButtonState(node.id);
            }
            // 更新图片节点的参考图显示
            if(node.type === 'image' && node.updateReferenceImages){
              node.updateReferenceImages();
            }
          });
        }, 100);
      } finally {
        state.isRestoringHistory = wasRestoring;
        if(!wasRestoring){
          resetHistoryWithCurrentState();
        }
      }
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
      } else if(nodeData.type === 'props'){
        createPropsNodeWithData(nodeData);
      } else if(nodeData.type === 'text_to_speech'){
        createTextToSpeechNodeWithData(nodeData);
      } else if(nodeData.type === 'dialogue_group'){
        createDialogueGroupNodeWithData(nodeData);
      } else if(nodeData.type === 'text'){
        createTextNodeWithData(nodeData);
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

    async function generateEditedImage(fileOrUrl, prompt, ratio, model, count, referenceImageUrls){
      const userId = localStorage.getItem('user_id');
      const authToken = getAuthToken();
      const form = new FormData();

      // 判断是 File 对象还是 URL 字符串
      if(typeof fileOrUrl === 'string'){
        // 如果是 URL，使用 ref_image_urls 参数
        // 将被编辑的图片和参考图片URL拼接在一起
        const allUrls = [fileOrUrl];
        if(referenceImageUrls && Array.isArray(referenceImageUrls) && referenceImageUrls.length > 0){
          allUrls.push(...referenceImageUrls);
        }
        form.append('ref_image_urls', allUrls.join(','));
      } else {
        // 如果是 File 对象，使用 image 参数
        form.append('image', fileOrUrl);
        // 添加参考图URL（如果有）
        if(referenceImageUrls && Array.isArray(referenceImageUrls) && referenceImageUrls.length > 0){
          form.append('ref_image_urls', referenceImageUrls.join(','));
        }
      }
      
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
      
      if(!res.ok) {
        const errorMsg = typeof data.detail === 'string' ? data.detail : 
                         typeof data.message === 'string' ? data.message :
                         JSON.stringify(data.detail || data.message || '提交任务失败');
        throw new Error(errorMsg);
      }
      
      if(data.project_ids && data.project_ids.length > 0){
        return {
          projectIds: data.project_ids,
          status: data.status
        };
      }
      throw new Error('提交任务失败：未返回项目ID');
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
        // 兼容旧数据：如果有model字段，迁移到videoModel
        node.data.videoModel = nodeData.data.videoModel || nodeData.data.model || 'sora2';
        node.data.drawCount = nodeData.data.drawCount || 1;
        node.data.motionLevel = nodeData.data.motionLevel || 5;
        node.data.useMotion = nodeData.data.useMotion || false;
        
        // 更新DOM显示
        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        if(el){
          // 更新提示词
          const promptEl = el.querySelector('.prompt');
          if(promptEl) promptEl.value = node.data.prompt;
          
          // 先更新视频模型选择
          const videoModelSelect = el.querySelector('.video-model-select');
          if(videoModelSelect) videoModelSelect.value = node.data.videoModel;
          
          // 根据模型更新时长选项
          const durationSelect = el.querySelector('.duration-select');
          if(durationSelect && videoModelSelect) {
            const videoModel = node.data.videoModel;
            if(videoModel === 'ltx2') {
              durationSelect.innerHTML = `
                <option value="5">5秒 (121帧)</option>
                <option value="8">8秒 (201帧)</option>
                <option value="10">10秒 (241帧)</option>
              `;
              if(![5, 8, 10].includes(node.data.duration)) {
                node.data.duration = 5;
              }
            } else if(videoModel === 'wan22' || videoModel === 'kling') {
              durationSelect.innerHTML = `
                <option value="5">5秒</option>
                <option value="10">10秒</option>
              `;
              if(![5, 10].includes(node.data.duration)) {
                node.data.duration = 5;
              }
            } else if(videoModel === 'vidu') {
              durationSelect.innerHTML = `
                <option value="5">5秒</option>
                <option value="8">8秒</option>
              `;
              if(![5, 8].includes(node.data.duration)) {
                node.data.duration = 5;
              }
            } else {
              durationSelect.innerHTML = `
                <option value="10">10秒</option>
                <option value="15">15秒</option>
              `;
              if(![10, 15].includes(node.data.duration)) {
                node.data.duration = 10;
              }
            }
            durationSelect.value = node.data.duration;
          }
          
          // 根据模型更新比例选项
          const ratioSelect = el.querySelector('.ratio-select');
          if(ratioSelect) {
            const ratioField = ratioSelect.closest('.field');
            const videoModel = node.data.videoModel;
            
            // vidu 模型隐藏比例选择器
            if(videoModel === 'vidu') {
              if(ratioField) ratioField.style.display = 'none';
            } else {
              // 其他模型显示比例选择器
              if(ratioField) ratioField.style.display = '';
              
              ratioSelect.innerHTML = `
                <option value="9:16">9:16 (竖屏)</option>
                <option value="16:9">16:9 (横屏)</option>
              `;
              // 如果保存的比例不在支持列表中，使用16:9
              if(node.data.ratio !== '9:16' && node.data.ratio !== '16:9') {
                node.data.ratio = '16:9';
              }
              ratioSelect.value = node.data.ratio;
            }
          }
          
          // 更新抽卡次数标签
          const genCountLabel = el.querySelector('.gen-count-label');
          if(genCountLabel) genCountLabel.textContent = `抽卡次数：X${node.data.drawCount}`;
          
          // 更新算力显示
          const computingPowerValue = el.querySelector('.computing-power-value');
          const computingPowerDetail = el.querySelector('.computing-power-detail');
          if(computingPowerValue && computingPowerDetail) {
            // 计算算力
            const config = getTaskComputingPowerConfig();
            let singlePower = 0;
            if(config && Object.keys(config).length > 0) {
              const videoModel = node.data.videoModel || 'sora2';
              const duration = node.data.duration || 10;
              
              if(videoModel === 'sora2') {
                singlePower = config[3] || 0;
              } else if(videoModel === 'ltx2') {
                singlePower = config[10] || 0;
              } else if(videoModel === 'wan22') {
                const wan22Power = config[11];
                if(typeof wan22Power === 'object') {
                  singlePower = wan22Power[duration] || wan22Power[5] || 0;
                } else {
                  singlePower = wan22Power || 0;
                }
              } else if(videoModel === 'kling') {
                const klingPower = config[12];
                if(typeof klingPower === 'object') {
                  singlePower = klingPower[duration] || klingPower[5] || 0;
                } else {
                  singlePower = klingPower || 0;
                }
              } else if(videoModel === 'vidu') {
                const viduPower = config[14];
                if(typeof viduPower === 'object') {
                  singlePower = viduPower[duration] || viduPower[5] || 0;
                } else {
                  singlePower = viduPower || 0;
                }
              }
            }
            const count = node.data.drawCount || 1;
            const totalPower = singlePower * count;
            computingPowerValue.textContent = `${totalPower} 算力`;
            computingPowerDetail.textContent = `单个 ${singlePower} 算力 × ${count} 个 = ${totalPower} 算力`;
          }
          
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
        node.data.project_id = nodeData.data.project_id !== undefined ? nodeData.data.project_id : null;
        // 如果有URL，显示预览
        if(node.data.url){
          const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
          if(el){
            const previewField = el.querySelector('.video-preview-field');
            const previewActionsField = el.querySelector('.video-preview-actions-field');
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
              if(previewActionsField){
                previewActionsField.style.display = 'block';
              }
              
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
        // 直接使用保存的所有属性，确保包括 gridIndex、gridSize、isSplit 等分镜图相关属性都能被恢复
        Object.assign(node.data, nodeData.data);
        
        // 强制重置相机参数为默认值（用户需求：每次加载都重置）
        if(node.data.camera){
          node.data.camera.yaw = 0;
          node.data.camera.pitch = 0;
          node.data.camera.dolly = 0;
          node.data.camera.modified = { yaw: false, dolly: false, pitch: false };
        }
        
        // 规范化图片 URL
        if(node.data.url){
          node.data.url = normalizeImageUrl(node.data.url);
        }
        if(node.data.preview){
          node.data.preview = normalizeImageUrl(node.data.preview);
        }
        
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
          
          // 同步相机控制 UI 为重置后的值
          const cameraYawSlider = el.querySelector('.image-camera-yaw-slider');
          const cameraYawInput = el.querySelector('.image-camera-yaw');
          const cameraDollySlider = el.querySelector('.image-camera-dolly-slider');
          const cameraDollyInput = el.querySelector('.image-camera-dolly');
          const cameraPitchSlider = el.querySelector('.image-camera-pitch-slider');
          const cameraPitchInput = el.querySelector('.image-camera-pitch');
          
          if(cameraYawSlider) cameraYawSlider.value = 0;
          if(cameraYawInput) cameraYawInput.value = 0;
          if(cameraDollySlider) cameraDollySlider.value = 0;
          if(cameraDollyInput) cameraDollyInput.value = 0;
          if(cameraPitchSlider) cameraPitchSlider.value = 0;
          if(cameraPitchInput) cameraPitchInput.value = 0;
          
          // 更新 3D 预览
          const cameraCanvas = el.querySelector('.image-camera-canvas');
          if(cameraCanvas && typeof window.updateCameraPreview === 'function'){
            window.updateCameraPreview(cameraCanvas, node.data.camera);
          }
          
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
      
      createScriptNode({ 
        x: nodeData.x, 
        y: nodeData.y,
        scriptId: nodeData.data && nodeData.data.scriptId
      });
      
      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);
      
      const node = state.nodes.find(n => n.id === nodeData.id);
      if(node && nodeData.data){
        node.data.scriptContent = nodeData.data.scriptContent || '';
        node.data.name = nodeData.data.name || '';
        node.data.maxGroupDuration = nodeData.data.maxGroupDuration || 15;
        node.data.parsedData = nodeData.data.parsedData || null;
        node.data.forceMediumShot = nodeData.data.forceMediumShot !== undefined ? nodeData.data.forceMediumShot : true;
        node.data.noBgMusic = nodeData.data.noBgMusic !== undefined ? nodeData.data.noBgMusic : true;
        node.data.splitMultiDialogue = nodeData.data.splitMultiDialogue !== undefined ? nodeData.data.splitMultiDialogue : false;
        node.data.narrationAsDialogue = nodeData.data.narrationAsDialogue !== undefined ? nodeData.data.narrationAsDialogue : false;
        
        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        if(el){
          const textareaEl = el.querySelector('.script-textarea');
          const durationSelectEl = el.querySelector('.script-duration-select');
          const forceMediumShotEl = el.querySelector('.script-force-medium-shot');
          const noBgMusicEl = el.querySelector('.script-no-bg-music');
          const splitMultiDialogueEl = el.querySelector('.script-split-multi-dialogue');
          const narrationAsDialogueEl = el.querySelector('.script-narration-as-dialogue');
          const splitBtn = el.querySelector('.script-split-btn');
          const infoField = el.querySelector('.script-info-field');
          const nameEl = el.querySelector('.script-name');
          const lengthEl = el.querySelector('.script-length');
          const charCountEl = el.querySelector('.script-char-count');
          
          if(textareaEl) textareaEl.value = node.data.scriptContent;
          if(durationSelectEl) durationSelectEl.value = String(node.data.maxGroupDuration);
          if(forceMediumShotEl) forceMediumShotEl.checked = node.data.forceMediumShot;
          if(noBgMusicEl) noBgMusicEl.checked = node.data.noBgMusic;
          if(splitMultiDialogueEl) splitMultiDialogueEl.checked = node.data.splitMultiDialogue;
          if(narrationAsDialogueEl) narrationAsDialogueEl.checked = node.data.narrationAsDialogue;
          
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

    // ============ 节点状态轮询功能 ============
    
    let pollStatusTimer = null;
    
    // 轮询工作流节点状态
    async function pollWorkflowNodeStatus(){
      // 从 URL 参数中获取 workflowId
      const urlParams = new URLSearchParams(window.location.search);
      const workflowId = urlParams.get('id');
      if(!workflowId) return;
      
      try {
        const userId = localStorage.getItem('user_id');
        const authToken = localStorage.getItem('auth_token');
        
        if(!userId || !authToken){
          return;
        }
        
        const response = await fetch(`/api/video-workflow/${workflowId}/poll-status`, {
          method: 'GET',
          headers: {
            'X-User-Id': userId,
            'Authorization': `Bearer ${authToken}`
          }
        });
        
        const result = await response.json();
        
        if(result.code === 0 && result.data){
          // 保存世界数据到全局变量
          if(Array.isArray(result.data.characters)){
            state.worldCharacters = result.data.characters;
          }
          if(Array.isArray(result.data.props)){
            state.worldProps = result.data.props;
          }
          if(Array.isArray(result.data.locations)){
            state.worldLocations = result.data.locations;
          }
          
          const updatedNodes = result.data.updated_nodes || [];
          
          if(updatedNodes.length > 0){
            updatedNodes.forEach(updatedNode => {
              const node = state.nodes.find(n => n.id === updatedNode.node_id);
              
              if(node && node.data){
                if(updatedNode.status === 2 && updatedNode.url){
                  node.data.url = updatedNode.url;
                  updateNodePreview(node, updatedNode.url);
                } else if(updatedNode.status === -1){
                  // 失败状态:显示错误信息
                  const errorMessage = updatedNode.message || '生成失败';
                  node.data.error = errorMessage;
                  updateNodeErrorDisplay(node, errorMessage);
                }
              }
            });
            
            try {
              await autoSaveWorkflow();
            } catch(e){
              console.error('[轮询] 自动保存失败:', e);
            }
          }
        }
      } catch(error){
        console.error('[轮询] 查询节点状态失败:', error);
      }
    }
    
    // 更新节点错误显示
    function updateNodeErrorDisplay(node, errorMessage){
      const canvasEl = document.getElementById('canvas');
      const nodeEl = canvasEl ? canvasEl.querySelector(`.node[data-node-id="${node.id}"]`) : null;
      
      if(!nodeEl) return;
      
      // 检查是否已有错误提示元素
      let errorEl = nodeEl.querySelector('.node-error-message');
      
      if(!errorEl){
        // 创建错误提示元素
        errorEl = document.createElement('div');
        errorEl.className = 'node-error-message';
        errorEl.style.cssText = 'background: #fee; color: #c33; padding: 8px; margin: 8px 0; border-radius: 4px; font-size: 12px; border: 1px solid #fcc;';
        
        // 插入到 .node-body 的顶部
        const nodeBody = nodeEl.querySelector('.node-body');
        if(nodeBody){
          nodeBody.insertBefore(errorEl, nodeBody.firstChild);
        } else {
          // 如果没有 .node-body,直接插入到节点内部
          nodeEl.insertBefore(errorEl, nodeEl.firstChild);
        }
      }
      
      errorEl.innerHTML = `<strong>生成失败:</strong> ${errorMessage}`;
      
      // 给节点添加错误样式
      nodeEl.style.borderColor = '#f44';
    }
    
    // 更新节点预览显示
    function updateNodePreview(node, url){
      const canvasEl = document.getElementById('canvas');
      const nodeEl = canvasEl ? canvasEl.querySelector(`.node[data-node-id="${node.id}"]`) : null;
      
      if(!nodeEl) return;
      
      if(node.type === 'video'){
        // 更新视频节点预览
        const previewField = nodeEl.querySelector('.video-preview-field');
        const thumbVideo = nodeEl.querySelector('.video-thumb');
        
        if(previewField && thumbVideo){
          thumbVideo.src = proxyDownloadUrl(url);
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
        }
      } else if(node.type === 'image'){
        // 检查是否为宫格分镜图节点（有gridIndex但未拆分）
        if(node.data.gridIndex && node.data.gridSize && !node.data.isSplit){
          // 需要调用拆分接口获取单张图片
          const aiToolsId = node.data.aiToolsId || node.data.project_id;
          const gridIndex = node.data.gridIndex;
          
          if(aiToolsId){
            (async () => {
              try {
                console.log(`[轮询] 调用拆分接口: aiToolsId=${aiToolsId}, gridIndex=${gridIndex}`);
                const splitResponse = await fetch(
                  `/api/ai-tools/${aiToolsId}/grid-split?grid_index=${gridIndex}&user_id=${getUserId()}&grid_size=${node.data.gridSize}`,
                  {
                    headers: {
                      'Authorization': getAuthToken(),
                      'X-User-Id': getUserId()
                    }
                  }
                );
                
                if(splitResponse.ok){
                  const splitData = await splitResponse.json();
                  if(splitData.code === 0 && splitData.data && splitData.data.image_url){
                    const normalizedUrl = normalizeImageUrl(splitData.data.image_url);
                    node.data.url = normalizedUrl;
                    node.data.preview = normalizedUrl;
                    node.data.isSplit = true;
                    node.data.status = 'completed';
                    
                    console.log(`[轮询] 拆分成功: ${node.id} -> ${splitData.data.image_url}`);
                    
                    const previewImg = nodeEl.querySelector('.image-preview');
                    const previewRow = nodeEl.querySelector('.image-preview-row');
                    
                    if(previewImg && previewRow){
                      previewImg.src = proxyImageUrl(splitData.data.image_url);
                      previewRow.style.display = 'flex';
                    }
                    
                    // 触发连接的分镜节点更新视频首帧预览
                    if(node.data.shotFrameNodeId) {
                      const shotFrameNode = state.nodes.find(n => n.id === node.data.shotFrameNodeId);
                      if(shotFrameNode && shotFrameNode.updatePreview) {
                        shotFrameNode.updatePreview();
                        console.log(`[轮询] 分镜节点 ${shotFrameNode.id} 更新后 previewImageUrl:`, shotFrameNode.data.previewImageUrl);
                      }
                    }

                    try { await autoSaveWorkflow(); } catch(e){}
                  }
                }
              } catch(e){
                console.error('[轮询] 拆分宫格图片失败:', e);
              }
            })();
            return;
          }
        }
        
        // 更新图片节点预览
        node.data.preview = url;
        const previewImg = nodeEl.querySelector('.image-preview');
        const previewRow = nodeEl.querySelector('.image-preview-row');
        
        if(previewImg && previewRow){
          previewImg.src = proxyImageUrl(url);
          previewRow.style.display = 'flex';
        }
        
        // 检查该图片节点是否连接到分镜节点,如果是则同步更新分镜节点的视频首帧
        // 注意:连接方向是 分镜节点 -> 图片节点,所以要查找入站连接(to === node.id)
        const incomingConnections = state.connections.filter(c => c.to === node.id);
        const connectedNodes = incomingConnections.map(c => state.nodes.find(n => n.id === c.from));
        const connectedShotFrameNode = connectedNodes.find(n => n && n.type === 'shot_frame');
        
        if(connectedShotFrameNode && !connectedShotFrameNode.data.previewImageUrl){
          connectedShotFrameNode.data.previewImageUrl = url;
          
          const shotFrameNodeEl = canvasEl.querySelector(`.node[data-node-id="${connectedShotFrameNode.id}"]`);
          if(shotFrameNodeEl){
            const shotFramePreviewImg = shotFrameNodeEl.querySelector('.shot-frame-preview-image');
            const shotFramePreviewField = shotFrameNodeEl.querySelector('.shot-frame-preview-field');
            
            if(shotFramePreviewImg){
              shotFramePreviewImg.src = proxyImageUrl(url);
              shotFramePreviewImg.style.display = 'block';
            }
            if(shotFramePreviewField){
              shotFramePreviewField.style.display = 'block';
            }
          }
          
          // 刷新关联分镜组节点的宫格预览
          const parentGroupConn = state.connections.find(c => c.to === connectedShotFrameNode.id);
          if(parentGroupConn) {
            const parentGroupNode = state.nodes.find(n => n.id === parentGroupConn.from && n.type === 'shot_group');
            if(parentGroupNode && parentGroupNode.refreshGridPreview) {
              parentGroupNode.refreshGridPreview();
            }
          }
        }
      }
    }
    
    // 启动轮询定时器（loadWorkflow 中已 await 调用过一次，这里只启动定时器）
    function startPolling(){
      // 清除旧的定时器
      if(pollStatusTimer){
        clearInterval(pollStatusTimer);
      }
      
      // 每分钟执行一次 (60000 毫秒)
      pollStatusTimer = setInterval(pollWorkflowNodeStatus, 60000);
    }
    
    // 停止轮询定时器
    function stopPolling(){
      if(pollStatusTimer){
        clearInterval(pollStatusTimer);
        pollStatusTimer = null;
      }
    }
    
    // 页面加载完成后启动轮询
    if(typeof window !== 'undefined'){
      // 等待页面完全加载后启动
      if(document.readyState === 'complete'){
        startPolling();
      } else {
        window.addEventListener('load', startPolling);
      }
      
      // 页面卸载时停止轮询
      window.addEventListener('beforeunload', stopPolling);
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
        // 转换图片URL为完整HTTP地址
        if(node.data.imageUrl){
          node.data.imageUrl = normalizeImageUrl(node.data.imageUrl);
        }
        if(node.data.previewImageUrl){
          node.data.previewImageUrl = normalizeImageUrl(node.data.previewImageUrl);
        }
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
          
          // 恢复图片提示词和视频提示词的 textarea 显示
          if(nodeData.data.imagePrompt !== undefined){
            const imagePromptEl = nodeEl.querySelector('.shot-frame-image-prompt');
            if(imagePromptEl){
              imagePromptEl.value = nodeData.data.imagePrompt;
            }
          }
          if(nodeData.data.videoPromptText !== undefined){
            const videoPromptEl = nodeEl.querySelector('.shot-frame-video-prompt');
            if(videoPromptEl){
              videoPromptEl.value = nodeData.data.videoPromptText;
            }
          }
          
          // 恢复视频模型和视频时长选择器
          const videoModelEl = nodeEl.querySelector('.shot-frame-video-model');
          const videoDurationEl = nodeEl.querySelector('.shot-frame-video-duration');
          
          if(videoModelEl && nodeData.data.videoModel){
            videoModelEl.value = nodeData.data.videoModel;
          }
          
          // 先更新时长选项（基于视频模型），再设置时长值
          if(videoDurationEl){
            const videoModel = nodeData.data.videoModel || 'wan22';
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
            
            // 设置保存的时长值
            if(nodeData.data.videoDuration){
              videoDurationEl.value = nodeData.data.videoDuration;
            }
          }
          
          // 恢复引用显示（场景、道具、角色）
          if(node.updateReferences) {
            node.updateReferences();
          }
        }
      }
      
      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);
    }

    // ============ Debug 模式功能 ============
    
    // 从 URL 参数中检查是否需要启用 Debug 模式
    function initDebugMode(){
      const urlParams = new URLSearchParams(window.location.search);
      const debugParam = urlParams.get('debug');
      
      if(debugParam === '1' && !state.debugMode){
        // 开启 Debug 模式需要密码
        const password = prompt('请输入 Debug 模式密码:');
        if(!password){
          return;
        }
        
        // 验证密码
        fetch('/api/config/debug-password')
          .then(res => res.json())
          .then(data => {
            if(data.success && data.password === password){
              state.debugMode = true;
              updateDebugModeUI();
              showToast('Debug 模式已开启', 'success');
            } else {
              showToast('密码错误', 'error');
            }
          })
          .catch(err => {
            console.error('验证密码失败:', err);
            showToast('验证失败', 'error');
          });
      }
    }
    
    // 更新 Debug 模式 UI
    function updateDebugModeUI(){
      // 更新所有节点的调试按钮显示状态
      state.nodes.forEach(node => {
        const nodeEl = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        if(nodeEl){
          const debugBtn = nodeEl.querySelector('.node-debug-btn');
          if(debugBtn){
            debugBtn.style.display = state.debugMode ? 'block' : 'none';
          }
        }
      });
    }
    
    // 初始化 Debug 模式
    initDebugMode();
    
    // ============ Debug 模式功能结束 ============
