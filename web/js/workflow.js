
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

    // 算力配置（用于节点算力预估）- 从 TaskConfig 模块获取
    let taskComputingPowerConfig = {};
    // 视频模型时长选项配置（全局缓存）- 从 TaskConfig 模块获取
    let videoModelDurationOptions = {};
    // 驱动可用状态（用于禁用未配置的功能）
    let driverStatusConfig = {};
    // 模型配置（比例、尺寸、时长等）- 从 TaskConfig 模块获取
    let modelConfigs = {};
    // 工作流配置（轮询间隔等，单位：毫秒）
    let workflowConfig = {
      poll_status_interval: 60000  // 默认60秒
    };
    
    // 使用统一配置模块更新本地缓存
    function syncFromTaskConfig() {
      if (window.TaskConfig && window.TaskConfig.isLoaded()) {
        taskComputingPowerConfig = window.TaskConfig.getTaskComputingPowerConfig();
        videoModelDurationOptions = window.TaskConfig.getVideoModelDurationOptions();
        modelConfigs = window.TaskConfig.getModelConfigs();
        console.log('[工作流] 已从 TaskConfig 同步配置');
      }
    }
    
    async function fetchWorkflowConfig(){
      try {
        const token = getAuthToken();
        const response = await fetch('/api/config/value?key=workflow.poll_status_interval', {
          headers: token ? { 'Authorization': `Bearer ${token}` } : {}
        });
        if(response.ok){
          const data = await response.json();
          if(data.code === 0 && data.data && data.data.value != null){
            // 后端配置单位为秒，前端转换为毫秒
            workflowConfig.poll_status_interval = data.data.value * 1000;
            console.log('[工作流配置] 轮询间隔:', data.data.value, '秒');
          }
        }
      } catch(e){
        console.warn('[工作流配置] 获取失败，使用默认值:', e);
      }
    }
    
    async function fetchComputingPowerConfig(){
      try {
        // 优先使用统一配置模块
        if (window.TaskConfig) {
          await window.TaskConfig.load();
          syncFromTaskConfig();
          // 配置加载完成后，更新所有图生视频节点和分镜节点的算力显示
          updateAllImageToVideoNodesPower();
          updateAllShotFrameNodesPower();
          // 刷新所有分镜组和分镜节点的视频模型选项，修复 TaskConfig 异步加载完成前
          // 节点已创建导致使用 hardcoded fallback 值的时序竞争问题
          if (typeof refreshShotGroupNodesModels === 'function') {
            refreshShotGroupNodesModels();
          }
          if (typeof refreshShotFrameNodesModels === 'function') {
            refreshShotFrameNodesModels();
          }
          // 同样刷新图生视频节点的 model/时长/比例 select，修复重新加载节点时
          // 配置未加载完导致 select 使用 hardcoded fallback（时长仅5/10、比例仅9:16/16:9、模型仅保存值）的时序竞争
          updateAllImageToVideoNodesSelects();

          // 驱动状态仍从原接口获取（暂未迁移）
          const response = await fetch('/api/computing-power-config');
          if(response.ok){
            const data = await response.json();
            if(data.success && data.data && data.data.driver_status){
              driverStatusConfig = data.data.driver_status;
              console.log('[驱动状态] 已加载:', driverStatusConfig);
            }
          }
          return;
        }
        
        // 回退：使用旧接口
        const response = await fetch('/api/computing-power-config');
        if(response.ok){
          const data = await response.json();
          if(data.success && data.data){
            if(data.data.task_computing_power){
              taskComputingPowerConfig = data.data.task_computing_power;
              console.log('[算力配置] 已加载:', taskComputingPowerConfig);
              updateAllImageToVideoNodesPower();
              updateAllShotFrameNodesPower();
            }
            if(data.data.video_model_duration_options){
              videoModelDurationOptions = data.data.video_model_duration_options;
              console.log('[视频模型时长配置] 已加载:', videoModelDurationOptions);
            }
            if(data.data.driver_status){
              driverStatusConfig = data.data.driver_status;
              console.log('[驱动状态] 已加载:', driverStatusConfig);
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
    
    // 获取驱动状态配置（供节点使用）
    function getDriverStatusConfig(){
      return driverStatusConfig;
    }
    
    // 获取模型配置（供节点使用）
    function getModelConfigs(){
      return modelConfigs;
    }
    
    // 获取模型配置
    async function fetchModelConfigs(){
      try {
        // 使用统一配置模块
        if (window.TaskConfig) {
          await window.TaskConfig.load();
          syncFromTaskConfig();
          // 配置加载完成后刷新图生视频节点 select（修复时序竞争）
          updateAllImageToVideoNodesSelects();
        }
      } catch(error){
        console.error('[模型配置] 加载失败:', error);
      }
    }
    
    // 计算视频生成算力（公共函数）
    function calculateVideoGenerationPower(videoModel, duration){
      if(window.TaskConfig){
        return window.TaskConfig.getComputingPower(videoModel, duration);
      }
      return 0;
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
              computingPowerValue.textContent = window.t ? window.t('computing_power_value', { power: totalPower }) : `${totalPower} 算力`;
              computingPowerValue.setAttribute('data-i18n-params', JSON.stringify({ power: totalPower }));
              computingPowerDetail.textContent = window.t ? window.t('computing_power_detail', { individual: singlePower, count: count, total: totalPower }) : `单个 ${singlePower} 算力 × ${count} 个 = ${totalPower} 算力`;
              computingPowerDetail.setAttribute('data-i18n-params', JSON.stringify({ individual: singlePower, count: count, total: totalPower }));
            }
          }
        }
      });
    }
    
    // 刷新单个图生视频节点的 model/duration/ratio select 选项
    // 配置未加载时走 fallback（硬编码默认项）；配置加载后用完整后端配置重填。
    // 修复 BUG：重新加载节点时若配置尚未加载完，select 会残缺（时长只有5/10、比例只有9:16/16:9、模型只有保存的那一个）。
    function refreshImageToVideoNodeSelects(node){
      if(!node || node.type !== 'image_to_video' || !node.data) return;
      const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
      if(!el) return;

      // ---- 视频模型 select ----
      const videoModelSelect = el.querySelector('.video-model-select');
      if(videoModelSelect) {
        const imageMode = node.data.imageMode || 'first_last_frame';
        const savedVideoModel = node.data.videoModel;
        videoModelSelect.innerHTML = '';

        if(window.TaskConfig && window.TaskConfig.isLoaded()) {
          const category = imageMode === 'text_to_video' ? 'text_to_video' : 'image_to_video';
          const options = window.TaskConfig.getModelOptionsForCategory(category);
          let firstAvailable = null;

          options.forEach(opt => {
            const optEl = document.createElement('option');
            optEl.value = opt.value;

            if(imageMode === 'text_to_video') {
              optEl.textContent = opt.label;
              videoModelSelect.appendChild(optEl);
              if(!firstAvailable) firstAvailable = opt.value;
            } else {
              const config = modelConfigs[opt.value];
              const supportedModes = config?.supported_image_modes || ['first_last_frame'];
              const supportsCurrentMode = supportedModes.includes(imageMode);
              optEl.textContent = supportsCurrentMode ? opt.label : opt.label + ' (不支持当前模式)';
              optEl.disabled = !supportsCurrentMode;
              videoModelSelect.appendChild(optEl);
              if(supportsCurrentMode && !firstAvailable) firstAvailable = opt.value;
            }
          });

          // 恢复之前的选择（如果仍然可用且支持当前模式）
          const selectedOption = videoModelSelect.querySelector(`option[value="${savedVideoModel}"]:not([disabled])`);
          if(selectedOption) {
            videoModelSelect.value = savedVideoModel;
          } else if(firstAvailable) {
            videoModelSelect.value = firstAvailable;
            node.data.videoModel = firstAvailable;
          }
        } else {
          // 回退：确保已保存的值在下拉框中可见
          ensureSelectHasSavedOption(videoModelSelect, savedVideoModel);
          videoModelSelect.value = savedVideoModel;
        }
      }

      // ---- 时长 select ----
      const durationSelect = el.querySelector('.duration-select');
      if(durationSelect) {
        const videoModel = node.data.videoModel;
        const config = modelConfigs[videoModel];
        const ltx2Labels = { 5: '5秒 (121帧)', 8: '8秒 (201帧)', 10: '10秒 (241帧)' };

        if(config && config.durations && config.durations.length > 0) {
          durationSelect.innerHTML = '';
          config.durations.forEach(duration => {
            const label = videoModel === 'ltx2' ? (ltx2Labels[duration] || `${duration}秒`) : `${duration}秒`;
            durationSelect.innerHTML += `<option value="${duration}">${label}</option>`;
          });
          if(!config.durations.includes(node.data.duration)) {
            node.data.duration = config.default_duration || config.durations[0];
          }
        } else {
          durationSelect.innerHTML = `<option value="5">5秒</option><option value="10">10秒</option>`;
          if(![5, 10].includes(node.data.duration)) node.data.duration = 5;
        }
        durationSelect.value = node.data.duration;
      }

      // ---- 比例 select ----
      const ratioSelect = el.querySelector('.ratio-select');
      if(ratioSelect) {
        const ratioField = ratioSelect.closest('.field');
        const videoModel = node.data.videoModel;
        const config = modelConfigs[videoModel];
        const labelMap = { '9:16': '9:16 (竖屏)', '16:9': '16:9 (横屏)', '1:1': '1:1 (方形)' };

        // vidu 模型隐藏比例选择器
        if(videoModel === 'vidu') {
          if(ratioField) ratioField.style.display = 'none';
        } else {
          if(ratioField) ratioField.style.display = '';

          if(config && config.ratios && config.ratios.length > 0) {
            ratioSelect.innerHTML = '';
            config.ratios.forEach(ratio => {
              ratioSelect.innerHTML += `<option value="${ratio}">${labelMap[ratio] || ratio}</option>`;
            });
            if(!config.ratios.includes(node.data.ratio)) {
              node.data.ratio = config.default_ratio || config.ratios[0];
            }
          } else {
            ratioSelect.innerHTML = `<option value="9:16">9:16 (竖屏)</option><option value="16:9">16:9 (横屏)</option>`;
            if(node.data.ratio !== '9:16' && node.data.ratio !== '16:9') node.data.ratio = '16:9';
          }
          ratioSelect.value = node.data.ratio;
        }
      }
    }

    // 配置加载完成后，刷新所有已存在图生视频节点的 model/duration/ratio select 选项
    function updateAllImageToVideoNodesSelects(){
      if(!state || !state.nodes) return;
      state.nodes.forEach(node => {
        if(node.type === 'image_to_video'){
          refreshImageToVideoNodeSelects(node);
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
              computingPowerValue.textContent = window.t ? window.t('shot_frame_computing_power_value', { power: totalPower }) : `${totalPower} 算力`;
              computingPowerValue.setAttribute('data-i18n-params', JSON.stringify({ power: totalPower }));
              computingPowerDetail.textContent = window.t ? window.t('shot_frame_computing_power_detail', { individual: singlePower, count: count, total: totalPower }) : `单个 ${singlePower} 算力 × ${count} 个 = ${totalPower} 算力`;
              computingPowerDetail.setAttribute('data-i18n-params', JSON.stringify({ individual: singlePower, count: count, total: totalPower }));
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
      // 加载模型配置
      fetchModelConfigs();
    });

    window.addEventListener('beforeunload', () => {
      stopComputingPowerTimer();
    });

    // 轮询视频状态
    function pollVideoStatus(projectIds, onProgress, onComplete, onError, onTaskUpdate){
      let pollCount = 0;
      const maxPolls = 120; // 最多轮询120次（20分钟）
      
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
              onError('等待超时，但视频仍在生成中。你可以通过刷新页面后查看是否生成成功。');
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
        if(nodeData.videoFile) delete nodeData.videoFile;  // 提取帧节点的视频文件
        // 对于本地blob URL，需要清除（这些是临时的）
        // 服务器URL（以http开头）保留
        if(nodeData.url && nodeData.url.startsWith('blob:')) nodeData.url = '';
        if(nodeData.startUrl && nodeData.startUrl.startsWith('blob:')) nodeData.startUrl = '';
        if(nodeData.endUrl && nodeData.endUrl.startsWith('blob:')) nodeData.endUrl = '';
        if(nodeData.videoUrl && nodeData.videoUrl.startsWith('blob:')) nodeData.videoUrl = '';  // 提取帧节点
        if(nodeData.preview && nodeData.preview.startsWith('data:') && nodeData.url) nodeData.preview = nodeData.url;
        if(nodeData.startPreview && nodeData.startPreview.startsWith('data:') && nodeData.startUrl) nodeData.startPreview = nodeData.startUrl;
        if(nodeData.endPreview && nodeData.endPreview.startsWith('data:') && nodeData.endUrl) nodeData.endPreview = nodeData.endUrl;

        // 清理音频/视频列表中的blob URL
        if(Array.isArray(nodeData.audioUrls)){
          nodeData.audioUrls = nodeData.audioUrls.map(item => {
            if(item && item.url && item.url.startsWith('blob:')) return { ...item, url: '' };
            return item;
          });
        }
        if(Array.isArray(nodeData.videoUrls)){
          nodeData.videoUrls = nodeData.videoUrls.map(item => {
            if(item && item.url && item.url.startsWith('blob:')) return { ...item, url: '' };
            return item;
          });
        }

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
        nextAudioConnId: state.nextAudioConnId,
        nextScriptId: state.nextScriptId,
        nodes: serializableNodes,
        connections: state.connections.map(c => ({ id: c.id, from: c.from, to: c.to })),
        imageConnections: state.imageConnections.map(c => ({ id: c.id, from: c.from, to: c.to, portType: c.portType })),
        firstFrameConnections: state.firstFrameConnections.map(c => ({ id: c.id, from: c.from, to: c.to })),
        videoConnections: state.videoConnections.map(c => ({ id: c.id, from: c.from, to: c.to })),
        referenceConnections: state.referenceConnections.map(c => ({ id: c.id, from: c.from, to: c.to })),
        audioConnections: state.audioConnections.map(c => ({ id: c.id, from: c.from, to: c.to })),
        timeline: {
          clips: state.timeline.clips.map(c => ({ ...c })),
          audioClips: state.timeline.audioClips.map(c => ({ ...c })),
          pillars: state.timeline.pillars.map(p => ({ ...p })),
          nextClipId: state.timeline.nextClipId,
          nextAudioClipId: state.timeline.nextAudioClipId,
        },
        style: {
          name: state.style.name,
          referenceImageUrl: state.style.referenceImageUrl,
          compositionPreference: state.style.compositionPreference
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

      // 工作流未就绪，不允许保存（新建空工作流 workflowReady=true，允许保存画风等元数据）
      if(!state.workflowReady){
        showToast('工作流尚未加载完成，无法保存', 'warning');
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
            default_world_id: state.defaultWorldId,
            workflow_ratio: state.ratio
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
      
      // 工作流未就绪或没有节点，不自动保存
      if(!state.workflowReady || state.nodes.length === 0) return;

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
            default_world_id: state.defaultWorldId,
            workflow_ratio: state.ratio
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
      if(!workflowId) return false;
      let success = false;

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

          // 从数据库主表加载 workflow_ratio
          if(workflow.workflow_ratio){
            console.log('[加载工作流] 从数据库加载 workflow_ratio:', workflow.workflow_ratio);
            window.__loadedWorkflowRatio = workflow.workflow_ratio;
          }

          // 检查是否从剧本智能体跳转过来，且带有世界ID
          const urlParams = new URLSearchParams(window.location.search);
          const fromWorldId = urlParams.get('from_world_id');

          // 判断工作流是否已配置世界
          const hasWorldConfigured = workflow.default_world_id || (workflow.workflow_data && workflow.workflow_data.defaultWorldId);

          // 如果工作流没有配置世界，且从剧本智能体跳转过来带有世界ID，则自动同步
          if(!hasWorldConfigured && fromWorldId){
            console.log('[加载工作流] 工作流未配置世界，从剧本智能体同步世界ID:', fromWorldId);
            // 更新工作流的默认世界
            await saveDefaultWorld(workflowId, parseInt(fromWorldId, 10));
            workflow.default_world_id = parseInt(fromWorldId, 10);
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
            state.workflowReady = true;  // 恢复成功才标记就绪
            console.log('[加载工作流] 恢复后 state.defaultWorldId:', state.defaultWorldId);
          } else {
            // 新建工作流，直接就绪
            state.workflowReady = true;
            // 新建工作流时，workflow_data为空，需要应用主表的workflow_ratio
            if(window.__loadedWorkflowRatio){
              state.ratio = window.__loadedWorkflowRatio;
              ratioSelectEl.value = window.__loadedWorkflowRatio;
              console.log('[加载工作流] 新工作流应用 workflow_ratio:', state.ratio);
              delete window.__loadedWorkflowRatio;
            }
          }

          // 自动继承世界画风：当工作流画风为空但关联的世界有画风时，自动填充
          if(!state.style.name && state.defaultWorldId){
            // 确保世界列表已加载
            if(typeof populateWorldSelector === 'function'){
              await populateWorldSelector();
            }
            if(typeof getCachedWorld === 'function'){
              const world = getCachedWorld(state.defaultWorldId);
              if(world && (world.visual_style || world.composition_preference)){
                console.log('[加载工作流] 工作流画风为空，自动继承世界画风:', world.visual_style, '构图倾向:', world.composition_preference);
                if(world.visual_style){
                  state.style.name = world.visual_style;
                }
                if(world.composition_preference){
                  state.style.compositionPreference = world.composition_preference;
                }
                // 保存继承的画风到工作流
                try {
                  await fetch(`/api/video-workflow/${workflowId}`, {
                    method: 'PUT',
                    headers: {
                      'Content-Type': 'application/json',
                      'Authorization': getAuthToken(),
                      'X-User-Id': getUserId()
                    },
                    body: JSON.stringify({
                      style: state.style.name || null,
                      style_reference_image: state.style.referenceImageUrl || null,
                      workflow_data: serializeWorkflow(),
                      workflow_ratio: state.ratio
                    })
                  });
                  console.log('[加载工作流] 已将世界画风保存到工作流');
                } catch(e){
                  console.error('[加载工作流] 保存世界画风失败:', e);
                }
              }
            }
          }
          success = true;
        } else {
          showToast(result.message || '加载工作流失败', 'error');
        }
      } catch(error){
        console.error('Load error:', error);
        showToast('加载工作流失败', 'error');
      }

      // ========== 自动创建剧本节点功能 ==========
      const urlParamsForAutoCreate = new URLSearchParams(window.location.search);
      const autoLoadScript = urlParamsForAutoCreate.get('auto_load_script') === 'true';

      if (autoLoadScript) {
        setTimeout(async () => {
          await checkAndAutoCreateScriptNode();
        }, 100);
      }

      return success;
    }

    // ========== 自动创建剧本节点 ==========
    /**
     * 检查并自动创建剧本节点
     */
    async function checkAndAutoCreateScriptNode() {
      // 检查是否已有剧本节点
      const hasScriptNode = state.nodes.some(n => n.type === 'script');
      if (hasScriptNode) {
        console.log('[自动创建剧本节点] 工作流已有剧本节点，跳过');
        return;
      }

      console.log('[自动创建剧本节点] 开始自动创建剧本节点');

      // 创建剧本节点
      const viewportPos = getViewportNodePosition();
      const nodeId = createScriptNode({
        x: viewportPos.x,
        y: viewportPos.y
      });

      // 延迟触发加载按钮，确保 DOM 已渲染
      setTimeout(() => {
        triggerScriptLoadButton(nodeId);
      }, 300);

      // 延迟刷新节点模型，确保剧本解析创建分镜组节点已完成
      setTimeout(() => {
        // 等待 TaskConfig 加载完成后刷新模型
        if (window.TaskConfig && window.TaskConfig.isLoaded()) {
          refreshShotGroupNodesModels();
          refreshShotFrameNodesModels();
        } else if (window.TaskConfig) {
          window.TaskConfig.onLoaded(() => {
            refreshShotGroupNodesModels();
            refreshShotFrameNodesModels();
          });
        }
      }, 800);
    }

    /**
     * 刷新所有分镜组节点的生图模型和生视频模型选择器
     */
    function refreshShotGroupNodesModels() {
      const shotGroupNodes = state.nodes.filter(n => n.type === 'shot_group');
      shotGroupNodes.forEach(node => {
        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        if (!el) return;

        const modelEl = el.querySelector('.shot-group-model');
        const gridModelEl = el.querySelector('.shot-group-grid-model');
        const videoModelEl = el.querySelector('.shot-group-video-model');

        // 刷新生图模型
        if (modelEl && window.TaskConfig) {
          const imageOptions = window.TaskConfig.getModelOptionsForCategory('image_edit');
          if (imageOptions.length > 0) {
            modelEl.innerHTML = '';
            imageOptions.forEach(opt => {
              const optEl = document.createElement('option');
              optEl.value = opt.value;
              optEl.textContent = opt.label;
              if (opt.value === node.data.model) optEl.selected = true;
              modelEl.appendChild(optEl);
            });
            // 如果当前值不在选项中，优先使用 GPT Image 2
            if (!imageOptions.find(o => o.value === node.data.model)) {
              node.data.model = imageOptions.find(o => o.value === 'gpt-image-2')?.value || imageOptions[0].value;
              modelEl.value = node.data.model;
            }
          }
        }

        // 刷新宫格生图模型，旧工作流中的 auto 智能模式迁移到 GPT Image 2
        if (gridModelEl && window.TaskConfig) {
          const gridOptions = window.TaskConfig
            .getModelOptionsForCategory('image_edit')
            .filter(opt => opt.supportsGridImage);
          if (gridOptions.length > 0) {
            gridModelEl.innerHTML = '';
            gridOptions.forEach(opt => {
              const optEl = document.createElement('option');
              optEl.value = opt.value;
              optEl.textContent = opt.label;
              if (opt.value === node.data.gridModel) optEl.selected = true;
              gridModelEl.appendChild(optEl);
            });
            if (!node.data.gridModel || node.data.gridModel === 'auto' || !gridOptions.find(o => o.value === node.data.gridModel)) {
              node.data.gridModel = gridOptions.find(o => o.value === 'gpt-image-2')?.value || gridOptions[0].value;
              gridModelEl.value = node.data.gridModel;
            }
          }
        }

        // 刷新生视频模型（根据当前视频生成模式过滤）
        if (videoModelEl && window.TaskConfig) {
          const allVideoOptions = window.TaskConfig.getModelOptionsForCategory('image_to_video');
          const mode = node.data.videoGenMode || 'first_last_frame';
          const videoOptions = allVideoOptions.filter(opt => {
            const modes = opt.supportedImageModes || ['first_last_frame'];
            return modes.includes(mode);
          });
          if (videoOptions.length > 0) {
            videoModelEl.innerHTML = '';
            videoOptions.forEach(opt => {
              const optEl = document.createElement('option');
              optEl.value = opt.value;
              optEl.textContent = opt.label;
              if (opt.value === node.data.videoModel) optEl.selected = true;
              videoModelEl.appendChild(optEl);
            });
            // 如果当前值不在选项中，更新为第一个选项
            if (!videoOptions.find(o => o.value === node.data.videoModel)) {
              node.data.videoModel = videoOptions[0].value;
              videoModelEl.value = node.data.videoModel;
            }
          }
        }
      });
      console.log('[刷新模型] 已刷新所有分镜组节点的模型选择器');
    }

    /**
     * 刷新所有分镜节点的生图模型和生视频模型选择器
     * 在 TaskConfig 延迟加载完成后调用，用于修复分镜节点创建时
     * TaskConfig 未就绪导致使用硬编码回退列表（缺少新模型选项）的问题。
     */
    function refreshShotFrameNodesModels() {
      if (!window.TaskConfig || !window.TaskConfig.isLoaded()) return;

      const shotFrameNodes = state.nodes.filter(n => n.type === 'shot_frame');
      shotFrameNodes.forEach(node => {
        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        if (!el) return;

        const modelEl = el.querySelector('.shot-frame-model');
        const videoModelEl = el.querySelector('.shot-frame-video-model');

        // 刷新生图模型
        if (modelEl) {
          const imageOptions = window.TaskConfig.getModelOptionsForCategory('image_edit');
          if (imageOptions.length > 0) {
            const currentModel = node.data.model;
            modelEl.innerHTML = '';
            imageOptions.forEach(opt => {
              const optEl = document.createElement('option');
              optEl.value = opt.value;
              optEl.textContent = opt.label;
              if (opt.value === currentModel) optEl.selected = true;
              modelEl.appendChild(optEl);
            });
            // 如果当前值不在选项中，优先使用 GPT Image 2
            if (!imageOptions.find(o => o.value === currentModel)) {
              node.data.model = imageOptions.find(o => o.value === 'gpt-image-2')?.value || imageOptions[0].value;
              modelEl.value = node.data.model;
            }
          }
        }

        // 刷新生视频模型（根据当前视频模式过滤）
        if (videoModelEl) {
          const allVideoOptions = window.TaskConfig.getModelOptionsForCategory('image_to_video');
          const mode = node.data.videoMode || 'first_last_frame';
          const videoOptions = allVideoOptions.filter(opt => {
            const modes = opt.supportedImageModes || ['first_last_frame'];
            return modes.includes(mode);
          });
          if (videoOptions.length > 0) {
            const currentVideoModel = node.data.videoModel;
            videoModelEl.innerHTML = '';
            videoOptions.forEach(opt => {
              const optEl = document.createElement('option');
              optEl.value = opt.value;
              optEl.textContent = opt.label;
              if (opt.value === currentVideoModel) optEl.selected = true;
              videoModelEl.appendChild(optEl);
            });
            // 如果当前值不在选项中，更新为第一个选项
            if (!videoOptions.find(o => o.value === currentVideoModel)) {
              node.data.videoModel = videoOptions[0].value;
              videoModelEl.value = node.data.videoModel;
            }
          }
        }
      });
      console.log('[刷新模型] 已刷新所有分镜节点的模型选择器');
    }

    /**
     * 触发剧本节点的加载按钮
     * @param {number} nodeId - 节点ID
     */
    function triggerScriptLoadButton(nodeId) {
      const el = canvasEl.querySelector(`.node[data-node-id="${nodeId}"]`);
      if (!el) {
        console.error('[触发加载按钮] 未找到节点DOM');
        return;
      }

      const loadBtn = el.querySelector('.script-load-btn');
      if (loadBtn) {
        console.log('[触发加载按钮] 模拟点击加载剧本按钮');
        loadBtn.click();
      } else {
        console.error('[触发加载按钮] 未找到加载按钮');
      }
    }

    // 迁移旧版相机参数 (yaw/pitch/dolly → horizontal_angle/vertical_angle/zoom)
    function migrateCameraParams(data){
      if(!data || !data.nodes) return;
      for(const node of data.nodes){
        if(node.data && node.data.camera){
          const cam = node.data.camera;
          // 检测旧格式：存在 yaw/pitch/dolly 但不存在 horizontal_angle
          if('yaw' in cam && !('horizontal_angle' in cam)){
            cam.horizontal_angle = cam.yaw || 0;
            cam.vertical_angle = cam.pitch || 0;
            cam.zoom = cam.dolly !== undefined ? cam.dolly : 5.0;
            if(cam.modified){
              cam.modified.horizontal_angle = cam.modified.yaw || false;
              cam.modified.vertical_angle = cam.modified.pitch || false;
              cam.modified.zoom = cam.modified.dolly !== undefined ? cam.modified.dolly : false;
            }
            delete cam.yaw;
            delete cam.pitch;
            delete cam.dolly;
            if(cam.modified){
              delete cam.modified.yaw;
              delete cam.modified.pitch;
              delete cam.modified.dolly;
            }
            console.log(`[相机迁移] 节点 ${node.id}: yaw=${cam.horizontal_angle}, pitch=${cam.vertical_angle}, dolly=${cam.zoom}`);
          }
        }
      }
    }

    // 恢复工作流状态
    function restoreWorkflow(data){
      // 迁移旧版相机参数
      migrateCameraParams(data);

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
        state.referenceConnections = [];
        state.audioConnections = [];
        state.selectedNodeId = null;
        state.selectedConnId = null;
        state.selectedImgConnId = null;
        state.selectedFirstFrameConnId = null;
        state.selectedVideoConnId = null;
        state.selectedReferenceConnId = null;
        state.selectedAudioConnId = null;
        
        // 恢复视口
        if(data.viewport){
          state.panX = data.viewport.panX || 0;
          state.panY = data.viewport.panY || 0;
          state.zoom = data.viewport.zoom || 1;
          applyTransform();
          updateZoomLevel();
        }
        
        // 恢复比例：优先使用主表 workflow_ratio，其次使用 workflow_data.ratio
        if(window.__loadedWorkflowRatio){
          state.ratio = window.__loadedWorkflowRatio;
          ratioSelectEl.value = window.__loadedWorkflowRatio;
          console.log('[恢复工作流] 从主表恢复 workflow_ratio:', state.ratio);
          delete window.__loadedWorkflowRatio;  // 清理临时变量
        } else if(data.ratio){
          state.ratio = data.ratio;
          ratioSelectEl.value = data.ratio;
          console.log('[恢复工作流] 从 workflow_data 恢复 ratio:', state.ratio);
        }
        
        // 恢复画风和构图倾向（从 workflow_data 中恢复）
        if(data.style){
          if(data.style.compositionPreference){
            state.style.compositionPreference = data.style.compositionPreference;
          }
          // name 和 referenceImageUrl 从 workflow 记录的 style/style_reference_image 字段恢复，这里仅做兜底
          if(data.style.name && !state.style.name){
            state.style.name = data.style.name;
          }
          if(data.style.referenceImageUrl && !state.style.referenceImageUrl){
            state.style.referenceImageUrl = data.style.referenceImageUrl;
          }
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
        state.nextAudioConnId = data.nextAudioConnId || 1;
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

        if(data.audioConnections && Array.isArray(data.audioConnections)){
          // 迁移旧连接方向：旧格式 from=audio → to=dialogue_group，修正为 from=dialogue_group → to=audio
          state.audioConnections = data.audioConnections.map(function(conn) {
            var fromNode = state.nodes.find(function(n) { return n.id === conn.from; });
            var toNode = state.nodes.find(function(n) { return n.id === conn.to; });
            if (fromNode && fromNode.type === 'audio' && toNode && toNode.type === 'dialogue_group') {
              return { id: conn.id, from: conn.to, to: conn.from };
            }
            return conn;
          });
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
                  safeAutoSave()
                }
              }
            }, 500);
          }
          
          console.log(`[恢复工作流] 恢复了 ${state.timeline.pillars.length} 个柱子`);
          renderTimeline();
        }
        
        // 重新渲染
        renderAllConnections();
        renderMinimap();
        
        // 恢复完成后，更新所有分镜节点的图片选择菜单和角色节点的按钮状态
        setTimeout(() => {
          state.nodes.forEach(node => {
            if(node.type === 'shot_frame' && node.updatePreview){
              node.updatePreview();
            }
            // 更新图片节点的参考图显示
            if(node.type === 'image' && node.updateReferenceImages){
              node.updateReferenceImages();
            }
          });
        }, 100);
      } catch(error) {
        console.error('[恢复工作流] 恢复失败:', error);
        // workflowReady 保持 false，所有保存路径都不会写入
        // 清理已创建的不完整 DOM 节点
        try {
          for(const node of [...state.nodes]){
            const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
            if(el) el.remove();
          }
        } catch(cleanupError) {
          console.error('[恢复工作流] 清理DOM失败:', cleanupError);
        }
        state.nodes = [];
        state.connections = [];
        state.imageConnections = [];
        state.firstFrameConnections = [];
        state.videoConnections = [];
        state.referenceConnections = [];
        state.audioConnections = [];
        showToast('工作流恢复失败，请刷新页面重试', 'error');
        throw error;  // 重新抛出，让 loadWorkflow 感知恢复失败
      } finally {
        state.isRestoringHistory = wasRestoring;
        if(!wasRestoring){
          resetHistoryWithCurrentState();
        }
      }
    }

    // 恢复单个节点（优先使用注册表，未注册的走旧逻辑）
    function restoreNode(nodeData){
      // 兼容旧的 image_edit 节点，转换为新的 image 节点
      if(nodeData.type === 'image_edit'){
        nodeData.type = 'image';
        nodeData.data.url = nodeData.data.imageUrl || nodeData.data.url || '';
      }

      // 优先从注册表查找
      if(typeof restoreNodeByRegistry === 'function' && restoreNodeByRegistry(nodeData)){
        return;
      }

      // 未注册的节点类型走旧逻辑
      if(nodeData.type === 'image_to_video'){
        createImageToVideoNodeWithData(nodeData);
      } else if(nodeData.type === 'video'){
        createVideoNodeWithData(nodeData);
      } else if(nodeData.type === 'image'){
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
      } else if(nodeData.type === 'audio'){
        createAudioNodeWithData(nodeData);
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
    const compositionInput = document.getElementById('compositionInput');
    const styleSyncBanner = document.getElementById('styleSyncBanner');
    const styleSyncBannerText = document.getElementById('styleSyncBannerText');
    const styleSyncBtn = document.getElementById('styleSyncBtn');

    // 打开画风设置模态框
    function openStyleModal(){
      styleNameInput.value = state.style.name || '';

      if(compositionInput){
        compositionInput.value = state.style.compositionPreference || '';
      }

      if(state.style.referenceImageUrl){
        styleImagePreviewImg.src = state.style.referenceImageUrl;
        styleImagePreview.style.display = 'block';
      } else {
        styleImagePreview.style.display = 'none';
      }

      // 检查世界画风与当前工作流是否一致
      _checkWorldStyleSync();

      styleModal.classList.add('show');
      styleModal.setAttribute('aria-hidden', 'false');
    }

    // 检查世界画风与当前工作流是否一致，不一致则显示同步按钮
    function _checkWorldStyleSync(){
      if (!styleSyncBanner) return;

      const worldId = state.defaultWorldId;
      if (!worldId || typeof getCachedWorld !== 'function') {
        styleSyncBanner.style.display = 'none';
        return;
      }

      const world = getCachedWorld(worldId);
      if (!world) {
        styleSyncBanner.style.display = 'none';
        return;
      }

      const worldStyle = world.visual_style || '';
      const worldComposition = world.composition_preference || '';
      const currentStyle = state.style.name || '';
      const currentComposition = state.style.compositionPreference || '';

      const styleDiffers = worldStyle && worldStyle !== currentStyle;
      const compositionDiffers = worldComposition && worldComposition !== currentComposition;

      if (styleDiffers || compositionDiffers) {
        styleSyncBanner.style.display = 'flex';
        const parts = [];
        if (styleDiffers) parts.push(`画风: "${worldStyle}"`);
        if (compositionDiffers) parts.push(`构图倾向: "${worldComposition}"`);
        if (styleSyncBannerText) styleSyncBannerText.textContent = `世界中的 ${parts.join('、')} 与当前工作流不一致`;
      } else {
        styleSyncBanner.style.display = 'none';
      }
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
      const compositionPreference = compositionInput ? compositionInput.value.trim() : '';
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
          state.style.compositionPreference = compositionPreference;
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

    // 同步世界画风按钮
    if(styleSyncBtn){
      styleSyncBtn.addEventListener('click', () => {
        const worldId = state.defaultWorldId;
        if (!worldId || typeof getCachedWorld !== 'function') return;
        const world = getCachedWorld(worldId);
        if (!world) return;
        if (world.visual_style && styleNameInput) {
          styleNameInput.value = world.visual_style;
        }
        if (world.composition_preference && compositionInput) {
          compositionInput.value = world.composition_preference;
        }
        styleSyncBanner.style.display = 'none';
        showToast('已同步世界的画风和构图倾向', 'success');
      });
    }
    
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
      
      // 根据 model 获取 task_id
      const taskId = TaskConfig.getTaskIdByKey(model || 'gemini-2.5-pro-image-preview', 'image_edit');
      if(!taskId){
        throw new Error(`未找到模型 ${model} 对应的任务配置`);
      }
      form.append('task_id', taskId);
      
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
        // 恢复图片模式和参考图
        node.data.imageMode = nodeData.data.imageMode || 'first_last_frame';
        node.data.referenceUrls = nodeData.data.referenceUrls || [];

        // 恢复音频/视频列表（兼容旧格式单值）
        if(Array.isArray(nodeData.data.audioUrls)){
          node.data.audioUrls = nodeData.data.audioUrls;
        } else if(nodeData.data.audioUrl && !nodeData.data.audioUrls){
          node.data.audioUrls = [{name: '已上传音频', url: nodeData.data.audioUrl}];
        }
        if(Array.isArray(nodeData.data.videoUrls)){
          node.data.videoUrls = nodeData.data.videoUrls;
        } else if(nodeData.data.videoUrl && !nodeData.data.videoUrls){
          node.data.videoUrls = [{name: '已上传视频', url: nodeData.data.videoUrl}];
        }
        
        // 更新DOM显示
        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        if(el){
          // 更新提示词
          const promptEl = el.querySelector('.prompt');
          if(promptEl) promptEl.value = node.data.prompt;
          
          // 更新提示词字符计数
          const promptCharCount = el.querySelector('.prompt-char-count');
          if(promptCharCount && node.data.prompt) {
            promptCharCount.textContent = `${node.data.prompt.length} 字符`;
          }
          
          // 根据图片模式筛选并填充视频模型/时长/比例选项（抽取为 refreshImageToVideoNodeSelects）
          // 重新加载节点时配置可能尚未加载完，此处先按 fallback 填充；
          // 配置加载完成后 updateAllImageToVideoNodesSelects() 会用完整配置再次刷新。
          refreshImageToVideoNodeSelects(node);

          // 更新抽卡次数标签
          const genCountLabel = el.querySelector('.gen-count-label');
          if(genCountLabel) { const _t = window.t ? window.t('draw_count_x', { count: node.data.drawCount }) : null; genCountLabel.textContent = (_t && _t !== 'draw_count_x') ? _t : `抽卡次数：X${node.data.drawCount}`; }
          
          // 更新算力显示
          const computingPowerValue = el.querySelector('.computing-power-value');
          const computingPowerDetail = el.querySelector('.computing-power-detail');
          if(computingPowerValue && computingPowerDetail) {
            // 计算算力
            const videoModel = node.data.videoModel || 'sora2';
            const duration = node.data.duration || 10;
            const singlePower = calculateVideoGenerationPower(videoModel, duration);
            const count = node.data.drawCount || 1;
            const totalPower = singlePower * count;
            computingPowerValue.textContent = window.t ? window.t('computing_power_value', { power: totalPower }) : `${totalPower} 算力`;
            computingPowerValue.setAttribute('data-i18n-params', JSON.stringify({ power: totalPower }));
            computingPowerDetail.textContent = window.t ? window.t('computing_power_detail', { individual: singlePower, count: count, total: totalPower }) : `单个 ${singlePower} 算力 × ${count} 个 = ${totalPower} 算力`;
            computingPowerDetail.setAttribute('data-i18n-params', JSON.stringify({ individual: singlePower, count: count, total: totalPower }));
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

          // 首尾帧同时存在时，预览图高度减半
          const _startRow = el.querySelector('.start-preview-row');
          const _endRow = el.querySelector('.end-preview-row');
          const _bothVisible = _startRow && _endRow && _startRow.style.display !== 'none' && _endRow.style.display !== 'none';
          const _maxH = _bothVisible ? '100px' : '200px';
          const _startImg = el.querySelector('.start-preview');
          const _endImg = el.querySelector('.end-preview');
          if(_startImg) _startImg.style.maxHeight = _maxH;
          if(_endImg) _endImg.style.maxHeight = _maxH;

          // 更新图片模式UI
          const imageModeSelect = el.querySelector('.image-mode-select');
          const imageModeHint = el.querySelector('.image-mode-hint');
          const firstLastFields = el.querySelectorAll('.first-last-fields');
          const referenceFields = el.querySelector('.reference-fields');
          const startImagePort = el.querySelector('.start-image-port');
          const endImagePort2 = el.querySelector('.end-image-port');
          const referencePreviewList = el.querySelector('.reference-preview-list');
          
          const imageMode = node.data.imageMode || 'first_last_frame';
          const imageModeHints = {
            'first_last_frame': '第一张为首帧，第二张（可选）为尾帧',
            'multi_reference': '所有图片作为风格参考',
            'text_to_video': '纯文本生成视频，无需上传图片'
          };
          
          if(imageModeSelect) imageModeSelect.value = imageMode;
          if(imageModeHint) imageModeHint.textContent = imageModeHints[imageMode] || '';
          
          // 显示/隐藏对应的上传区域
          firstLastFields.forEach(field => {
            field.style.display = imageMode === 'first_last_frame' ? '' : 'none';
          });
          if(referenceFields) referenceFields.style.display = imageMode === 'multi_reference' ? '' : 'none';

          // 显示/隐藏端口
          if(startImagePort) startImagePort.style.display = imageMode === 'first_last_frame' ? '' : 'none';
          if(endImagePort2) endImagePort2.style.display = imageMode === 'first_last_frame' ? '' : 'none';

          // 显示/隐藏参考音频和参考视频字段（仅在多参考图模式下显示）
          const audioField = el.querySelector('.audio-field');
          const videoField = el.querySelector('.video-field');
          if(audioField) audioField.style.display = imageMode === 'multi_reference' ? '' : 'none';
          if(videoField) videoField.style.display = imageMode === 'multi_reference' ? '' : 'none';

          // 根据 supports_last_frame 控制尾帧输入框的可用性
          if(imageMode === 'first_last_frame') {
            const modelConfigs = getModelConfigs();
            const config = modelConfigs[node.data.videoModel];
            const supportsLastFrame = config?.supports_last_frame !== false;

            const endFileInput = el.querySelector('.end-file');
            const endClearBtn = el.querySelector('.end-clear');
            const endPreviewRow = el.querySelector('.end-preview-row');
            // 尾帧字段是 first-last-fields 中的第二个（索引1）
            const endField = firstLastFields.length > 1 ? firstLastFields[1] : null;
            const endLabel = endField ? endField.querySelector('.label') : null;

            if (!supportsLastFrame) {
              // 禁用尾帧输入
              if (endFileInput) endFileInput.disabled = true;
              if (endClearBtn) endClearBtn.disabled = true;
              if (endPreviewRow) endPreviewRow.style.opacity = '0.5';
              if (endImagePort2) endImagePort2.classList.add('disabled');
              // 修改提示文字
              if (endLabel) endLabel.textContent = '尾帧画面（该模型不支持）';
            } else {
              // 启用尾帧输入
              if (endFileInput) endFileInput.disabled = false;
              if (endClearBtn) endClearBtn.disabled = false;
              if (endPreviewRow) endPreviewRow.style.opacity = '1';
              if (endImagePort2) endImagePort2.classList.remove('disabled');
              // 恢复提示文字
              if (endLabel) endLabel.textContent = '尾帧画面（可选）';
            }
          }

          // 渲染参考图预览
          if(referencePreviewList && node.data.referenceUrls && node.data.referenceUrls.length > 0) {
            referencePreviewList.innerHTML = '';
            node.data.referenceUrls.forEach((url, idx) => {
              const item = document.createElement('div');
              item.style.cssText = 'position: relative; width: 50px; height: 50px;';
              item.innerHTML = `
                <img src="${url}" style="width: 100%; height: 100%; object-fit: cover; border-radius: 4px; cursor: pointer;" />
                <div style="position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.6); color: white; font-size: 10px; text-align: center; border-radius: 0 0 4px 4px; padding: 1px 0;">图${idx + 1}</div>
                <button class="ref-remove-btn" data-idx="${idx}" style="position: absolute; top: -4px; right: -4px; width: 16px; height: 16px; border-radius: 50%; background: #ef4444; border: none; color: white; font-size: 10px; cursor: pointer; line-height: 1;">×</button>
              `;
              item.querySelector('img').addEventListener('click', (e) => {
                e.stopPropagation();
                openImageModal(url, `图${idx + 1}`);
              });
              item.querySelector('.ref-remove-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                node.data.referenceUrls.splice(idx, 1);
                // 重新渲染
                const newList = el.querySelector('.reference-preview-list');
                if(newList) {
                  newList.innerHTML = '';
                  node.data.referenceUrls.forEach((u, i) => {
                    const newItem = document.createElement('div');
                    newItem.style.cssText = 'position: relative; width: 50px; height: 50px;';
                    newItem.innerHTML = `<img src="${u}" style="width: 100%; height: 100%; object-fit: cover; border-radius: 4px;" /><div style="position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.6); color: white; font-size: 10px; text-align: center; border-radius: 0 0 4px 4px; padding: 1px 0;">图${i + 1}</div>`;
                    newList.appendChild(newItem);
                  });
                }
              });
              referencePreviewList.appendChild(item);
            });

            // 恢复参考图连接线
            node.data.referenceUrls.forEach(refUrl => {
              // 查找对应的图片节点
              const imageNode = state.nodes.find(n => n.type === 'image' && n.data.url === refUrl);
              if(imageNode && !state.imageConnections.some(c => c.from === imageNode.id && c.to === node.id && c.portType === 'ref-image')){
                state.imageConnections.push({
                  id: state.nextImgConnId++,
                  from: imageNode.id,
                  to: node.id,
                  portType: 'ref-image'
                });
              }
            });
          }

          // 渲染音频预览列表
          const audioPreviewList = el.querySelector('.audio-preview-list');
          if(audioPreviewList && Array.isArray(node.data.audioUrls) && node.data.audioUrls.length > 0){
            audioPreviewList.innerHTML = '';
            node.data.audioUrls.forEach((item, idx) => {
              const mediaEl = document.createElement('div');
              mediaEl.className = 'media-item';
              mediaEl.innerHTML = `🎵 音频${idx + 1} <span class="remove-btn" title="删除">×</span>`;
              mediaEl.querySelector('.remove-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                const removedUrl = item.url;
                node.data.audioUrls.splice(idx, 1);
                // 清理对应的连接线
                state.audioConnections = state.audioConnections.filter(c => {
                  if(c.to === node.id){
                    const fromNode = state.nodes.find(n => n.id === c.from);
                    if(fromNode && fromNode.data.url === removedUrl) return false;
                  }
                  return true;
                });
                // 重新渲染
                const newList = el.querySelector('.audio-preview-list');
                if(newList){
                  newList.innerHTML = '';
                  node.data.audioUrls.forEach((a, i) => {
                    const newEl = document.createElement('div');
                    newEl.className = 'media-item';
                    newEl.innerHTML = `🎵 音频${i + 1} <span class="remove-btn">×</span>`;
                    newEl.querySelector('.remove-btn').addEventListener('click', () => {
                      const removedUrl2 = a.url;
                      node.data.audioUrls.splice(i, 1);
                      // 清理对应的连接线
                      state.audioConnections = state.audioConnections.filter(c => {
                        if(c.to === node.id){
                          const fromNode = state.nodes.find(n => n.id === c.from);
                          if(fromNode && fromNode.data.url === removedUrl2) return false;
                        }
                        return true;
                      });
                      newEl.remove();
                    });
                    newList.appendChild(newEl);
                  });
                }
                renderAudioConnections();
              });
              audioPreviewList.appendChild(mediaEl);
            });
          }

          // 渲染视频预览列表
          const videoPreviewList = el.querySelector('.video-preview-list');
          if(videoPreviewList && Array.isArray(node.data.videoUrls) && node.data.videoUrls.length > 0){
            videoPreviewList.innerHTML = '';
            node.data.videoUrls.forEach((item, idx) => {
              const mediaEl = document.createElement('div');
              mediaEl.className = 'media-item';
              mediaEl.innerHTML = `🎬 视频${idx + 1} <span class="remove-btn" title="删除">×</span>`;
              mediaEl.querySelector('.remove-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                const removedUrl = item.url;
                node.data.videoUrls.splice(idx, 1);
                // 清理对应的连接线
                state.videoConnections = state.videoConnections.filter(c => {
                  if(c.to === node.id){
                    const fromNode = state.nodes.find(n => n.id === c.from);
                    if(fromNode && fromNode.data.url === removedUrl) return false;
                  }
                  return true;
                });
                // 重新渲染
                const newList = el.querySelector('.video-preview-list');
                if(newList){
                  newList.innerHTML = '';
                  node.data.videoUrls.forEach((v, i) => {
                    const newEl = document.createElement('div');
                    newEl.className = 'media-item';
                    newEl.innerHTML = `🎬 视频${i + 1} <span class="remove-btn">×</span>`;
                    newEl.querySelector('.remove-btn').addEventListener('click', () => {
                      const removedUrl2 = v.url;
                      node.data.videoUrls.splice(i, 1);
                      // 清理对应的连接线
                      state.videoConnections = state.videoConnections.filter(c => {
                        if(c.to === node.id){
                          const fromNode = state.nodes.find(n => n.id === c.from);
                          if(fromNode && fromNode.data.url === removedUrl2) return false;
                        }
                        return true;
                      });
                      newEl.remove();
                    });
                    newList.appendChild(newEl);
                  });
                }
                renderVideoConnections();
              });
              videoPreviewList.appendChild(mediaEl);
            });
          }

          // 恢复音频连接线
          if(Array.isArray(node.data.audioUrls)){
            node.data.audioUrls.forEach(audioItem => {
              // 查找对应的音频节点
              const audioNode = state.nodes.find(n => n.type === 'audio' && n.data.url === audioItem.url);
              if(audioNode && !state.audioConnections.some(c => c.from === audioNode.id && c.to === node.id)){
                state.audioConnections.push({
                  id: state.nextAudioConnId++,
                  from: audioNode.id,
                  to: node.id
                });
              }
            });
          }

          // 恢复视频连接线
          if(Array.isArray(node.data.videoUrls)){
            node.data.videoUrls.forEach(videoItem => {
              // 查找对应的视频节点
              const videoNode = state.nodes.find(n => n.type === 'video' && n.data.url === videoItem.url);
              if(videoNode && !state.videoConnections.some(c => c.from === videoNode.id && c.to === node.id && c.portType === 'video-ref')){
                state.videoConnections.push({
                  id: state.nextVideoConnId++,
                  from: videoNode.id,
                  to: node.id,
                  portType: 'video-ref'
                });
              }
            });
          }
        }
      }

      // 重新渲染所有连接线
      if(typeof renderAllConnections === 'function') renderAllConnections();
    }

    // 带数据创建视频节点（复用createVideoNode的逻辑）
    function createVideoNodeWithData(nodeData){
      // 临时保存nextNodeId
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;
      
      // 调用原有的创建函数
      createVideoNode({ x: nodeData.x, y: nodeData.y, checkCollision: true });
      
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
          if(modelEl) modelEl.value = node.data.model;
          // 根据模型动态更新比例选项
          if(ratioEl && node.data.model) {
            const config = modelConfigs[node.data.model];
            const labelMap = { '9:16': '竖屏 (9:16)', '16:9': '横屏 (16:9)', '1:1': '正方形 (1:1)', '3:4': '竖屏 (3:4)', '4:3': '横屏 (4:3)' };
            if(config && config.ratios && config.ratios.length > 0) {
              ratioEl.innerHTML = '';
              config.ratios.forEach(ratio => {
                ratioEl.innerHTML += `<option value="${ratio}">${labelMap[ratio] || ratio}</option>`;
              });
              if(!config.ratios.includes(node.data.ratio)) {
                node.data.ratio = config.default_ratio || config.ratios[0];
              }
            }
          }
          if(ratioEl) ratioEl.value = node.data.ratio;
          if(drawCountLabel) { const _t = window.t ? window.t('draw_count_x', { count: node.data.drawCount }) : null; drawCountLabel.textContent = (_t && _t !== 'draw_count_x') ? _t : `抽卡次数：X${node.data.drawCount}`; }
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

    // 带数据创建音频节点（复用createAudioNode的逻辑）
    function createAudioNodeWithData(nodeData){
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;

      createAudioNode({ x: nodeData.x, y: nodeData.y, title: nodeData.title });

      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);

      const node = state.nodes.find(n => n.id === nodeData.id);
      if(node && nodeData.data){
        node.data.url = nodeData.data.url || '';
        node.data.name = nodeData.data.name || '';
        // 恢复对话组溯源字段
        if(nodeData.data.sourceNodeId !== undefined){
          node.data.sourceNodeId = nodeData.data.sourceNodeId;
        }
        if(nodeData.data.dialogueIndex !== undefined){
          node.data.dialogueIndex = nodeData.data.dialogueIndex;
        }
        // 如果有URL，显示预览
        if(node.data.url){
          const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
          if(el){
            const previewField = el.querySelector('.audio-preview-field');
            const previewActionsField = el.querySelector('.audio-preview-actions-field');
            const audioPlayer = el.querySelector('.audio-node-player');
            const nameEl = el.querySelector('.audio-node-name');
            const addTimelineBtn = el.querySelector('.audio-add-timeline-btn');
            if(previewField && audioPlayer){
              audioPlayer.src = proxyDownloadUrl(node.data.url);
              if(nameEl){
                const displayName = (node.data.name || '').length > 10 ? node.data.name.substring(0, 10) + '...' : (node.data.name || '已上传音频');
                nameEl.textContent = displayName;
                nameEl.title = node.data.name || '';
              }
              previewField.style.display = 'block';
              if(previewActionsField) previewActionsField.style.display = 'block';
            }
            // 显示"添加到时间轴"按钮（当音频来自对话组时）
            if(addTimelineBtn && node.data.sourceNodeId !== undefined){
              addTimelineBtn.style.display = 'inline-block';
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
        // 恢复语言设置（兼容旧数据：旧的 language 字段作为两个新字段的默认值）
        const legacyLanguage = nodeData.data.language || '';
        node.data.dialogueLanguage = nodeData.data.dialogueLanguage !== undefined ? nodeData.data.dialogueLanguage : legacyLanguage;
        node.data.promptLanguage = nodeData.data.promptLanguage !== undefined ? nodeData.data.promptLanguage : legacyLanguage;
        // 恢复模型相关字段（防止被 createScriptNode 的默认值覆盖）
        if(nodeData.data.videoModel) node.data.videoModel = nodeData.data.videoModel;
        if(nodeData.data.gridModel) node.data.gridModel = nodeData.data.gridModel === 'auto' ? 'gpt-image-2' : nodeData.data.gridModel;
        if(nodeData.data.gridLayout) node.data.gridLayout = nodeData.data.gridLayout;
        if(nodeData.data.splitModel) node.data.splitModel = nodeData.data.splitModel;
        if(nodeData.data.splitModelId) node.data.splitModelId = nodeData.data.splitModelId;
        if(nodeData.data.splitModelVendorId) node.data.splitModelVendorId = nodeData.data.splitModelVendorId;
        if(nodeData.data.splitModelVendorName) node.data.splitModelVendorName = nodeData.data.splitModelVendorName;

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

          // 恢复模型选择器的显示状态
          const videoModelEl = el.querySelector('.script-video-model');
          if(videoModelEl && node.data.videoModel){
            ensureSelectHasSavedOption(videoModelEl, node.data.videoModel);
            videoModelEl.value = node.data.videoModel;
          }
          const gridModelEl = el.querySelector('.script-grid-model');
          if(gridModelEl && node.data.gridModel){
            ensureSelectHasSavedOption(gridModelEl, node.data.gridModel);
            gridModelEl.value = node.data.gridModel;
          }
          const gridLayoutEl = el.querySelector('.script-grid-layout');
          if(gridLayoutEl && node.data.gridLayout){
            gridLayoutEl.value = node.data.gridLayout;
          }
          const splitModelEl = el.querySelector('.script-split-model');
          if(splitModelEl && node.data.splitModel){
            ensureSelectHasSavedOption(splitModelEl, node.data.splitModel);
            splitModelEl.value = node.data.splitModel;
          }

          // 恢复语言选择器的UI显示
          const presetLanguageValues = ['', 'English', 'Deutsch', 'Français', 'Русский'];
          const dialogueLangSelect = el.querySelector('.script-dialogue-language');
          const dialogueLangCustom = el.querySelector('.script-dialogue-language-custom');
          if(dialogueLangSelect && node.data.dialogueLanguage) {
            if(presetLanguageValues.includes(node.data.dialogueLanguage)) {
              dialogueLangSelect.value = node.data.dialogueLanguage;
              if(dialogueLangCustom) dialogueLangCustom.style.display = 'none';
            } else {
              dialogueLangSelect.value = '__custom__';
              if(dialogueLangCustom) { dialogueLangCustom.style.display = 'block'; dialogueLangCustom.value = node.data.dialogueLanguage; }
            }
          }
          const promptLangSelect = el.querySelector('.script-prompt-language');
          const promptLangCustom = el.querySelector('.script-prompt-language-custom');
          if(promptLangSelect && node.data.promptLanguage) {
            if(presetLanguageValues.includes(node.data.promptLanguage)) {
              promptLangSelect.value = node.data.promptLanguage;
              if(promptLangCustom) promptLangCustom.style.display = 'none';
            } else {
              promptLangSelect.value = '__custom__';
              if(promptLangCustom) { promptLangCustom.style.display = 'block'; promptLangCustom.value = node.data.promptLanguage; }
            }
          }

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
    let _pollStatusRunning = false;
    
    // 轮询工作流节点状态
    async function pollWorkflowNodeStatus(){
      // 防止重叠执行（定时器 + 手动触发可能并发）
      if(_pollStatusRunning){
        console.log('[轮询] 上一次 pollWorkflowNodeStatus 尚未完成，跳过');
        return;
      }
      _pollStatusRunning = true;
      
      try {
        // 从 URL 参数中获取 workflowId
        const urlParams = new URLSearchParams(window.location.search);
        const workflowId = urlParams.get('id');
        if(!workflowId) return;
        
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

          // 刷新所有分镜节点的引用显示（角色、道具、场景）
          // 这样当世界数据加载完成后，节点中的引用标签会自动更新
          state.nodes.forEach(node => {
            if(node.updateReferences) {
              node.updateReferences();
            }
          });

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
          
          // 处理需要拆分的宫格节点（isSplit=true 且 url 为空，排除已失败的）
          const GRID_SPLIT_MAX_RETRIES = 20;
          const unsplitGridNodes = state.nodes.filter(n =>
            n.type === 'image' &&
            n.data.isSplit === true &&
            n.data.gridIndex &&
            !n.data.url &&
            n.data.status !== 'failed'
          );
          
          if(unsplitGridNodes.length > 0){
            console.log(`[轮询] 发现 ${unsplitGridNodes.length} 个待拆分宫格节点`);
            let splitUpdated = false;
            
            // 顺序处理（避免并发轰炸后端）
            for(const gridNode of unsplitGridNodes){
              const aiToolsId = gridNode.data.aiToolsId || gridNode.data.project_id;
              if(!aiToolsId) continue;
              
              try {
                const splitResp = await fetch(
                  `/api/ai-tools/${aiToolsId}/grid-split?grid_index=${gridNode.data.gridIndex}&user_id=${getUserId()}&grid_size=${gridNode.data.gridSize}`,
                  {
                    headers: {
                      'Authorization': getAuthToken(),
                      'X-User-Id': getUserId()
                    }
                  }
                );
                const splitData = await splitResp.json();
                
                if(splitData.code === 0 && splitData.data && splitData.data.image_url){
                  // 拆分成功，更新节点
                  const normalizedUrl = normalizeImageUrl(splitData.data.image_url);
                  gridNode.data.url = normalizedUrl;
                  gridNode.data.preview = normalizedUrl;
                  gridNode.data.status = 'completed';
                  delete gridNode.data._splitFailCount;
                  splitUpdated = true;
                  
                  // 更新 DOM 预览
                  updateNodePreview(gridNode, normalizedUrl);
                  
                  // 触发关联分镜节点更新首帧
                  if(gridNode.data.shotFrameNodeId){
                    const sfNode = state.nodes.find(n => n.id === gridNode.data.shotFrameNodeId);
                    if(sfNode && sfNode.updatePreview){
                      sfNode.updatePreview();
                    }
                  }
                  
                  console.log(`[轮询] 宫格拆分成功: ${gridNode.id} -> ${splitData.data.image_url}`);
                } else if(splitData.code === 1){
                  // 后端正在下载/拆分，下次轮询重试（不计入失败次数）
                  console.log(`[轮询] 宫格拆分处理中: ${gridNode.id}`);
                } else {
                  // code === -1 等错误：累计失败次数
                  gridNode.data._splitFailCount = (gridNode.data._splitFailCount || 0) + 1;
                  console.warn(`[轮询] 宫格拆分失败 (${gridNode.data._splitFailCount}/${GRID_SPLIT_MAX_RETRIES}): ${gridNode.id}`, splitData.message);
                  if(gridNode.data._splitFailCount >= GRID_SPLIT_MAX_RETRIES){
                    gridNode.data.status = 'failed';
                    gridNode.data.error = splitData.message || '拆分失败（原图可能已过期）';
                    updateNodeErrorDisplay(gridNode, gridNode.data.error);
                    splitUpdated = true;
                    console.error(`[轮询] 宫格拆分达到最大重试次数，标记为失败: ${gridNode.id}`);
                  }
                }
              } catch(e){
                // 网络错误也计入失败次数
                gridNode.data._splitFailCount = (gridNode.data._splitFailCount || 0) + 1;
                console.error(`[轮询] 宫格拆分请求失败 (${gridNode.data._splitFailCount}/${GRID_SPLIT_MAX_RETRIES}): ${gridNode.id}`, e);
                if(gridNode.data._splitFailCount >= GRID_SPLIT_MAX_RETRIES){
                  gridNode.data.status = 'failed';
                  gridNode.data.error = '拆分请求失败（网络异常）';
                  updateNodeErrorDisplay(gridNode, gridNode.data.error);
                  splitUpdated = true;
                }
              }
            }
            
            if(splitUpdated){
              try {
                await autoSaveWorkflow();
              } catch(e){
                console.error('[轮询] 拆分后自动保存失败:', e);
              }
            }
          }
        }
      } catch(error){
        console.error('[轮询] 查询节点状态失败:', error);
      } finally {
        _pollStatusRunning = false;
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
        const previewActionsField = nodeEl.querySelector('.video-preview-actions-field');
        const nameEl = nodeEl.querySelector('.video-name');
        
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
          // 同时显示加入时间轴按钮区域
          if(previewActionsField){
            previewActionsField.style.display = 'block';
          }
        }
      } else if(node.type === 'image'){
        // 宫格拆分节点的拆分逻辑已移至 pollWorkflowNodeStatus 统一驱动
        // 这里只处理已有 url 的图片节点预览更新
        
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
      
      // 使用后台配置的轮询间隔
      const interval = workflowConfig.poll_status_interval || 60000;
      pollStatusTimer = setInterval(pollWorkflowNodeStatus, interval);
      console.log('[轮询] 已启动，间隔:', interval, 'ms');
    }
    
    // 停止轮询定时器
    function stopPolling(){
      if(pollStatusTimer){
        clearInterval(pollStatusTimer);
        pollStatusTimer = null;
      }
    }
    
    // 轮询不再自动启动，改为 loadWorkflow 成功后由 events.js 调用 startPolling()
    // 页面卸载时停止轮询
    if(typeof window !== 'undefined'){
      window.addEventListener('beforeunload', stopPolling);
    }

    // 带数据创建分镜节点
    function createShotFrameNodeWithData(nodeData){
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;

      createShotFrameNode({
        x: nodeData.x,
        y: nodeData.y,
        shotData: nodeData.data.shotJson || {},
        model: nodeData.data.model,
        videoModel: nodeData.data.videoModel
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
              { const _t = window.t ? window.t('draw_count_x', { count: nodeData.data.drawCount }) : null; drawCountLabel.textContent = (_t && _t !== 'draw_count_x') ? _t : `抽卡次数：X${nodeData.data.drawCount}`; }
            }
          }

          // 恢复视频抽卡次数显示
          if(nodeData.data.videoDrawCount){
            const videoDrawCountLabel = nodeEl.querySelector('.shot-frame-video-draw-count-label');
            if(videoDrawCountLabel){
              { const _t = window.t ? window.t('draw_count_x', { count: nodeData.data.videoDrawCount }) : null; videoDrawCountLabel.textContent = (_t && _t !== 'draw_count_x') ? _t : `抽卡次数：X${nodeData.data.videoDrawCount}`; }
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
          
          // 恢复视频生成模式（先恢复模式，再填充模型列表）
          if(nodeData.data.videoMode) {
            node.data.videoMode = nodeData.data.videoMode;
            const modeBtns = nodeEl.querySelectorAll('.video-mode-btn');
            modeBtns.forEach(btn => {
              const isActive = btn.dataset.mode === nodeData.data.videoMode;
              btn.style.background = isActive ? '#3b82f6' : '#f3f4f6';
              btn.style.color = isActive ? 'white' : '#666';
            });
          }

          // 恢复分镜模型选择器（确保已保存的值在下拉框中可见）
          const modelEl = nodeEl.querySelector('.shot-frame-model');
          if(modelEl && nodeData.data.model){
            ensureSelectHasSavedOption(modelEl, nodeData.data.model);
            modelEl.value = nodeData.data.model;
          }

          // 根据模式重新填充视频模型列表，再恢复选中值
          if(node.populateVideoModelOptions) {
            node.populateVideoModelOptions();
          }
          if(videoModelEl && nodeData.data.videoModel){
            ensureSelectHasSavedOption(videoModelEl, nodeData.data.videoModel);
            videoModelEl.value = nodeData.data.videoModel;
          }

          // 恢复模式相关 UI 状态
          if(node.updateModeUI) {
            node.updateModeUI();
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
    // 使用方式: ?debug=你的密码
    function initDebugMode(){
      const urlParams = new URLSearchParams(window.location.search);
      const debugParam = urlParams.get('debug');
      
      if(!debugParam || state.debugMode){
        return;
      }
      
      // 将 debug 参数值作为密码验证
      const password = debugParam;
      
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
