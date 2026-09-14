
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
      // 兼容期双写：登录态以 localStorage.auth_token 为准
      const hasSession = !!token;
      if(!hasSession){
        updateComputingPowerLabel('未登录');
        computingPowerRefreshBtn?.setAttribute('disabled', 'true');
        redirectToLogin();
        return;
      }

      computingPowerRefreshBtn?.setAttribute('disabled', 'true');
      updateComputingPowerLabel('加载中...');

      try{
        const response = await fetch('/api/user/computing_power', {
          headers: token ? {
            'Authorization': `Bearer ${token}`
          } : {}
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
              refreshVideoModelSelectsAfterDriverStatus();
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
              refreshVideoModelSelectsAfterDriverStatus();
            }
          }
        }
      } catch(error){
        console.error('[算力配置] 加载失败:', error);
      }
    }
    
    function refreshVideoModelSelectsAfterDriverStatus() {
      if (typeof refreshShotGroupNodesModels === 'function') {
        refreshShotGroupNodesModels();
      }
      if (typeof refreshShotFrameNodesModels === 'function') {
        refreshShotFrameNodesModels();
      }
      if (typeof updateAllImageToVideoNodesSelects === 'function') {
        updateAllImageToVideoNodesSelects();
      }
      if (state && state.nodes) {
        state.nodes.forEach((node) => {
          if (node.type === 'script' && typeof node.populateScriptVideoModelOptions === 'function') {
            node.populateScriptVideoModelOptions();
          }
        });
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
    function calculateVideoGenerationPower(videoModel, duration, context = {}){
      if(window.TaskConfig){
        return window.TaskConfig.getComputingPower(videoModel, duration, context);
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
              const context = {};
              const imageMode = node.data.imageMode || 'first_last_frame';
              if(imageMode === 'first_last_frame') {
                const hasStartImage = !!node.data.startFile || !!node.data.startUrl ||
                  state.imageConnections.some(c => c.to === node.id && c.portType === 'start');
                const hasEndImage = !!node.data.endFile || !!node.data.endUrl ||
                  state.imageConnections.some(c => c.to === node.id && c.portType === 'end');
                context.image_mode = hasStartImage && hasEndImage ? 'first_last_with_tail' : 'first_last_frame';
              } else if(imageMode) {
                context.image_mode = imageMode;
              }
              if(node.data.videoResolution) {
                context.resolution = node.data.videoResolution;
              }
              const singlePower = calculateVideoGenerationPower(videoModel, duration, context);
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

      if(typeof node.updateResolutionOptions === 'function') {
        node.updateResolutionOptions(node.data.videoModel);
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
              const context = {};
              if(node.data.videoMode) {
                context.image_mode = node.data.videoMode;
              }
              if(node.data.videoResolution) {
                context.resolution = node.data.videoResolution;
              }
              const singlePower = calculateVideoGenerationPower(videoModel, duration, context);
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
    // 两阶段轮询策略：前20分钟每10秒一次(120次)，后40分钟每30秒一次(80次)，总计60分钟
    function pollVideoStatus(projectIds, onProgress, onComplete, onError, onTaskUpdate){
      let pollCount = 0;
      const stage1Polls = 120; // 阶段一最大轮询次数：120次 × 10秒 = 20分钟
      const maxPolls = 200;    // 总最大轮询次数：120 + 80 = 200，合计60分钟

      // 根据当前已轮询次数返回下一次轮询的间隔(ms)：阶段一10秒，阶段二30秒
      const getNextInterval = () => pollCount < stage1Polls ? 10000 : 30000;

      // 根据当前已轮询次数返回累计已等待的秒数(用于进度展示)
      const getElapsedSeconds = () => {
        if(pollCount <= stage1Polls){
          return pollCount * 10;
        }
        return stage1Polls * 10 + (pollCount - stage1Polls) * 30;
      };

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
            onProgress(`生成中... (${getElapsedSeconds()}秒)`);
            if(pollCount < maxPolls){
              setTimeout(poll, getNextInterval());
            } else {
              onError('等待超时，但视频仍在生成中。你可以通过刷新页面后查看是否生成成功。');
            }
          }
        } catch(e){
          console.error('Poll error:', e);
          if(pollCount < maxPolls){
            setTimeout(poll, getNextInterval());
          } else {
            onError('查询状态失败');
          }
        }
      };

      poll();
    }

    // 序列化工作流数据（用于保存）
    // 性能优化：data:URL base64 大字符串剔除阈值（字节），超过则不进入快照/保存数据
    const DATA_URL_STRIP_THRESHOLD = 4096;
    // preview 类字段 -> 已上传 url 字段（注意 preview 为小写，不能用正则统一推导）
    const PREVIEW_URL_KEY_MAP = {
      preview: 'url',
      startPreview: 'startUrl',
      endPreview: 'endUrl'
    };

    /**
     * 深度剔除 data:URL base64 大字符串（性能优化，不可变实现）
     * 这些 base64 串会随快照进入 undo 历史（最多 historyLimit 份全量 JSON 字符串）
     * 并随每次自动保存整体上传，是节点多时内存暴涨的主因。
     * preview 类字段优先用对应的已上传 url 回填（preview→url、startPreview→startUrl），
     * 未命中映射或无对应 url 时一律置空——绝不能把原始 base64 写回（否则优化失效）
     * @param {*} value - 待处理的值
     * @param {number} depth - 递归深度保护
     * @returns {*} 处理后的新值
     */
    function stripLargeDataUrls(value, depth){
      if(typeof value === 'string'){
        return (value.startsWith('data:') && value.length > DATA_URL_STRIP_THRESHOLD) ? '' : value;
      }
      if(value === null || typeof value !== 'object' || depth > 6) return value;
      if(Array.isArray(value)){
        return value.map(v => stripLargeDataUrls(v, depth + 1));
      }
      const out = {};
      for(const key in value){
        const v = value[key];
        if(typeof v === 'string' && v.startsWith('data:') && v.length > DATA_URL_STRIP_THRESHOLD){
          const urlKey = PREVIEW_URL_KEY_MAP[key];
          out[key] = (urlKey && value[urlKey]) ? value[urlKey] : '';
        } else {
          out[key] = stripLargeDataUrls(v, depth + 1);
        }
      }
      return out;
    }

    function serializeWorkflow(){
      // 只保存必要的数据，排除File对象和临时URL
      const serializableNodes = state.nodes.map(node => {
        let nodeData = { ...node.data };
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

        // 性能优化：剔除 data:URL base64 大字符串（含 preview 类字段的 url 回填）
        nodeData = stripLargeDataUrls(nodeData, 0);

        // 瘦身 workflow_data（去重而非压缩）：
        // 1) shot_frame.data.videoPrompt 是 shotJson 的 JSON.stringify 美化版（纯重复，
        //    实测占大工作流体积的一半以上），不落库；展示/生成用 videoPromptText
        //   （用户可编辑），缺失时各消费点可由 shotJson 现场格式化兜底。
        // 2) shot_frame 的 shotJson.scriptData 与 shot_group 的 scriptData 是同一份剧本
        //    解析数据的逐字拷贝（每节点一份），只保留各消费点实际读取的轻量引用
        //   （props/characters/剧本元信息），世界数据由 state.worldXxx 全局加载兜底。
        // 兼容性：旧工作流加载后内存保持完整数据，此处仅在序列化时精简，重新保存即瘦身；
        // buildSlimScriptData 为不可变实现（nodes.js），不会污染运行态 state。
        if(typeof buildSlimScriptData === 'function'){
          if(node.type === 'shot_frame'){
            if(nodeData.videoPrompt !== undefined) delete nodeData.videoPrompt;
            if(nodeData.shotJson && typeof nodeData.shotJson === 'object'){
              nodeData.shotJson = {
                ...nodeData.shotJson,
                scriptData: buildSlimScriptData(nodeData.shotJson.scriptData, nodeData.shotJson)
              };
            }
          } else if(node.type === 'shot_group'){
            if(nodeData.scriptData && typeof nodeData.scriptData === 'object'){
              nodeData.scriptData = buildSlimScriptData(nodeData.scriptData);
            }
          }
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
        groups: state.groups.map(g => ({
          id: g.id,
          title: g.title,
          x: g.x,
          y: g.y,
          w: g.w,
          h: g.h,
          nodeIds: g.nodeIds.slice()
        })),
        nextGroupId: state.nextGroupId,
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

    // 保存按钮环绕 loading（参考剧本页提交按钮）：conic-gradient 亮点沿边框
    // 旋转。手动/自动保存可能并发，用计数器避免一方结束提前关掉另一方的动画。
    let saveBtnSavingCount = 0;
    function saveBtnSavingStart(){
      saveBtnSavingCount++;
      const saveBtn = document.getElementById('saveBtn');
      if(saveBtn) saveBtn.classList.add('is-saving');
    }
    function saveBtnSavingEnd(){
      saveBtnSavingCount = Math.max(0, saveBtnSavingCount - 1);
      if(saveBtnSavingCount === 0){
        const saveBtn = document.getElementById('saveBtn');
        if(saveBtn) saveBtn.classList.remove('is-saving');
      }
    }

    /**
     * 409 冲突（工作流已被其他会话覆盖）：保存按钮变黄并弹出冲突解决对话框，
     * 由用户选择「用本地版本覆盖」或「使用服务器版本」（见 resolveSaveConflict）。
     * 本地修改已写入 IndexedDB 恢复快照兜底。冲突状态随解决/刷新解除。
     */
    function markSaveConflict(){
      const saveBtn = document.getElementById('saveBtn');
      const saveBtnText = document.getElementById('saveBtnText');
      if(!saveBtn) return;
      const alreadyConflict = saveBtn.classList.contains('save-conflict');
      saveBtn.classList.add('save-conflict');
      saveBtn.classList.remove('is-saving');
      saveBtn.disabled = false;
      if(saveBtn.dataset.origTitle === undefined){
        saveBtn.dataset.origTitle = saveBtn.title || '';
      }
      saveBtn.title = '工作流已被其他会话覆盖，点击选择如何处理（本地修改已保留）';
      if(saveBtnText) saveBtnText.textContent = '⚠ 保存冲突';
      // 仅首次进入冲突态时自动弹出选择对话框；重复 409 不重复弹
      if(!alreadyConflict) showSaveConflictDialog();
    }

    /** 解除保存按钮的冲突黄色态（用本地版本覆盖成功后调用）。 */
    function clearSaveConflict(){
      const saveBtn = document.getElementById('saveBtn');
      const saveBtnText = document.getElementById('saveBtnText');
      if(!saveBtn) return;
      saveBtn.classList.remove('save-conflict');
      if(saveBtn.dataset.origTitle !== undefined){
        saveBtn.title = saveBtn.dataset.origTitle;
        delete saveBtn.dataset.origTitle;
      }
      if(saveBtnText) saveBtnText.textContent = '保存';
    }

    function showSaveConflictDialog(){
      const modal = document.getElementById('saveConflictModal');
      if(!modal) return;
      modal.classList.add('show');
      modal.setAttribute('aria-hidden', 'false');
    }

    function hideSaveConflictDialog(){
      const modal = document.getElementById('saveConflictModal');
      if(!modal) return;
      modal.classList.remove('show');
      modal.setAttribute('aria-hidden', 'true');
    }

    // 冲突解决中标志：防止重复点击
    let saveConflictResolving = false;
    // 用户已选择「使用服务器版本」、等待刷新：beforeunload 的熔断分支不得再重写冲突快照
    let acceptServerVersionPending = false;

    /**
     * 冲突解决：useLocal=true 用本地画布内容强制覆盖服务器（不携带
     * X-Base-Hash，服务端跳过 CAS）；useLocal=false 丢弃本地未保存修改，
     * 刷新加载服务器最新版本。
     */
    async function resolveSaveConflict(useLocal){
      if(saveConflictResolving) return;
      const workflowId = getWorkflowIdFromUrl();
      if(!workflowId) return;
      const useLocalBtn = document.getElementById('saveConflictUseLocalBtn');
      const useServerBtn = document.getElementById('saveConflictUseServerBtn');
      saveConflictResolving = true;
      if(useLocalBtn) useLocalBtn.disabled = true;
      if(useServerBtn) useServerBtn.disabled = true;
      try {
        if(useLocal){
          saveBtnSavingStart();
          const body = buildAutoSaveBody();
          const response = await fetch(`/api/video-workflow/${workflowId}`, {
            method: 'PUT',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': getAuthToken(),
              'X-User-Id': getUserId()
              // 不携带 X-Base-Hash：服务端跳过 CAS，强制覆盖。
              // 对方会话下轮 poll 感知哈希漂移，其保存会被 CAS 409 拦截，
              // 进入同样的冲突选择流程，不会被静默互覆。
            },
            body: body
          });
          const result = await response.json();
          if(result.code !== 0){
            showToast(result.message || '覆盖服务器失败，请重试', 'error');
            return;
          }
          if(typeof autoSaveState !== 'undefined'){
            // setConfirmedBody 同时解除冲突熔断（成功保存 = 已与服务端重新同步）
            autoSaveState.setConfirmedBody(
              workflowId, body, result.data && result.data.content_hash);
          }
          if(typeof WorkflowRecovery !== 'undefined'){
            await WorkflowRecovery.discardOwnSnapshot({
              workflowId: workflowId,
              userId: getUserId()
            }).catch(() => false);
          }
          clearSaveConflict();
          hideSaveConflictDialog();
          showToast('已用本地版本覆盖服务器内容', 'success');
        } else {
          acceptServerVersionPending = true;
          if(typeof WorkflowRecovery !== 'undefined'){
            await WorkflowRecovery.discardOwnSnapshot({
              workflowId: workflowId,
              userId: getUserId()
            }).catch(() => false);
          }
          location.reload();
        }
      } catch(error){
        console.error('解决保存冲突失败:', error);
        showToast('操作失败: ' + error.message, 'error');
      } finally {
        if(useLocal) saveBtnSavingEnd();
        saveConflictResolving = false;
        if(useLocalBtn) useLocalBtn.disabled = false;
        if(useServerBtn) useServerBtn.disabled = false;
      }
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

      // 手动保存是当前最新的用户意图：取消尚未触发的防抖保存，并在下方
      // 中止旧在途自动保存，避免旧 payload 晚到覆盖手动保存。
      if(typeof cancelPendingAutoSave === 'function') cancelPendingAutoSave();

      let sentVersion = 0;
      let recoveryMeta = null;

      try {
        saveBtnSavingStart();
        const body = buildAutoSaveBody();

        // 与自动保存共用的去重门：本地内容未变且服务端未漂移时跳过 PUT。
        // 无变化的手动保存若落库，serialize/restore 的往返差异（含各端不同的
        // viewport 视口状态）会改变服务端内容哈希，导致其他在线用户被
        // CAS 409 误伤（双方都"什么都没改"却互相冲突）。
        if(typeof autoSaveState !== 'undefined'
            && autoSaveState.isConfirmedBody(workflowId, body)){
          showToast('内容没有变化，无需保存', 'success');
          return;
        }

        const controller = new AbortController();

        if(typeof autoSaveState !== 'undefined'){
          autoSaveState.markDirty();
          autoSaveState.abortInFlight();
          sentVersion = autoSaveState.beginSend(controller, false);
        }

        // CAS 基值：本次编辑所基于的服务端内容哈希（无基线时为空，不做 CAS）
        const baseHash = (typeof autoSaveState !== 'undefined')
          ? autoSaveState.getConfirmedHash(workflowId)
          : null;

        if(typeof WorkflowRecovery !== 'undefined'){
          recoveryMeta = {
            version: sentVersion,
            workflowId: workflowId,
            userId: getUserId(),
            baseHash: baseHash,
            ...WorkflowRecovery.createWriteIdentity()
          };
          // 用手动保存的最新 body 覆盖旧自动保存快照；否则下次打开
          // 可能重放旧快照，把已手动保存的内容覆盖掉。
          await WorkflowRecovery.saveSnapshot(body, recoveryMeta).catch(() => null);
        }

        const headers = {
          'Content-Type': 'application/json',
          'Authorization': getAuthToken(),
          'X-User-Id': getUserId()
        };
        if(baseHash) headers['X-Base-Hash'] = baseHash;

        const responsePromise = fetch(`/api/video-workflow/${workflowId}`, {
          method: 'PUT',
          signal: controller.signal,
          headers: headers,
          body: body
        });
        if(typeof autoSaveState !== 'undefined'){
          autoSaveState.markRequestStarted(sentVersion);
        }
        const response = await responsePromise;

        const result = await response.json();

        if(result.code === 0){
          // 手动保存成功：与自动保存共用去重门基线（body 同构），
          // 并以服务端返回的最新内容哈希滚动 CAS 基值
          if(typeof autoSaveState !== 'undefined'){
            autoSaveState.setConfirmedBody(
              workflowId, body, result.data && result.data.content_hash);
          }
          let confirmed = true;
          if(typeof autoSaveState !== 'undefined'){
            confirmed = autoSaveState.endSend(sentVersion, true);
          }
          if(confirmed && recoveryMeta && typeof WorkflowRecovery !== 'undefined'){
            await WorkflowRecovery.clearConfirmedSnapshot(recoveryMeta).catch(() => false);
          }
          showToast('保存成功', 'success');
        } else if(result.code === 409){
          // CAS 冲突：内容已被其他会话修改。本地修改已通过恢复快照兜底，
          // 不静默丢失；熔断自动保存避免周期性无效重试。保存按钮变黄提示
          // 刷新页面读取最新数据（按钮点击语义切换为刷新，见 events.js）
          if(typeof autoSaveState !== 'undefined'){
            autoSaveState.endSend(sentVersion, false);
            if(result.data && result.data.content_hash){
              autoSaveState.noteServerHash(workflowId, result.data.content_hash);
            }
            autoSaveState.noteConflict(workflowId);
          }
          markSaveConflict();
          showToast(result.message || '工作流内容已被其他会话修改，本次保存被拒绝，请刷新页面', 'warning');
        } else {
          if(typeof autoSaveState !== 'undefined'){
            autoSaveState.endSend(sentVersion, false);
          }
          showToast(result.message || '保存失败', 'error');
        }
      } catch(error){
        if(typeof autoSaveState !== 'undefined'){
          autoSaveState.endSend(sentVersion, false);
        }
        console.error('Save error:', error);
        showToast('保存失败: ' + error.message, 'error');
      } finally {
        saveBtnSavingEnd();
        saveBtn.disabled = false;
        // 冲突态保持黄色提示与文案，由用户点击按钮刷新页面后解除
        if(!saveBtn.classList.contains('save-conflict')){
          saveBtnText.textContent = '保存';
        }
      }
    }

    // 自动/手动保存共用的 PUT body 构造。两处必须严格同构：上传去重门按
    // body 全文比较，任何字段差异都会导致基线永不命中（退化为总是上传）。
    function buildAutoSaveBody(){
      return JSON.stringify({
        workflow_data: serializeWorkflow(),
        default_world_id: state.defaultWorldId,
        workflow_ratio: state.ratio
      });
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

      // 直接调用点（undo/redo、shot_group 模型切换/人脸选项等）不经过
      // safeAutoSave 的 markDirty：发起 PUT 本身就是"有未确认修改"，统一在此
      // 标记，保证关页时 isDirty() 能捕获并补发
      if(typeof autoSaveState !== 'undefined') autoSaveState.markDirty();

      // 声明在 try 外：catch 分支也需要用它收尾状态机
      let sentVersion = 0;
      // 保存按钮环绕 loading 是否由本次调用开启（提前 return 的分支不得误关）
      let ringStarted = false;

      try {
        const body = typeof opts.serializedBody === 'string'
          ? opts.serializedBody
          : buildAutoSaveBody();

        // 上传去重门：body 与服务端最近确认内容逐字节一致时跳过本次 PUT。
        // 典型触发：poll-status 对失败/CDN PENDING 节点每轮重复返回相同的
        // updated_nodes，前端内容实际未变却全量上传——大工作流可达十余 MB，
        // 经 frp 转发会周期性打满 ECS 公网出带宽。基线只在 PUT 成功或
        // loadWorkflow 成功时建立，上传失败不会记录（下次照常重传）。
        if(typeof autoSaveState !== 'undefined'
            && autoSaveState.isConfirmedBody(workflowId, body)){
          // 尽力中止可能在途的旧请求（其 payload 与当前内容不同）。
          // 注意：abort 只是降低旧 payload 落库概率的防御层，不是正确性
          // 依据——请求已到达服务端时不可撤回；该窗口由服务端哈希感知
          // （下轮 poll 哈希漂移 → 门失效 → 重传收敛）与 PUT CAS 兜底。
          autoSaveState.abortInFlight();
          autoSaveState.confirmSkipped();
          // 清除本页此前失败/被取代发送留下的残留恢复快照：服务端已持有
          // 当前内容，残留快照若被下次会话重放会把已撤销的内容复活
          if(typeof WorkflowRecovery !== 'undefined'){
            WorkflowRecovery.discardOwnSnapshot({
              workflowId: workflowId,
              userId: getUserId()
            }).catch(() => false);
          }
          console.log('[自动保存] 内容与服务端一致，跳过上传');
          return;
        }

        // CAS 409 冲突熔断：冲突未解决前不再发 PUT——base_hash 不变必然再冲突，
        // 周期性全量重试会重新打满带宽。本地修改必须落 IndexedDB 恢复快照兜底
        // （不 PUT），避免熔断期间的编辑在浏览器崩溃时丢失。
        // 快照 baseHash 必须保留【过期的确认基线】（getConfirmedHash），绝不能取
        // 409 响应下发的最新服务端哈希：后者会让刷新后的重放 CAS 必然通过，
        // 本地旧内容静默覆盖他人已保存的新内容（最后写者胜，他人数据丢失）。
        // 取过期基线则重放 CAS 必然 409 → 走放弃重放 + 清除快照路径，
        // 刷新后以服务端最新数据为准（toast 告知）。崩溃恢复场景（无他人写入）
        // 不受影响：普通快照 baseHash 本就是 confirmedHash，服务端未变则正常恢复。
        if(typeof autoSaveState !== 'undefined'
            && autoSaveState.isConflictBlocked(workflowId)){
          // 用户已在冲突对话框中选择「使用服务器版本」、等待刷新：
          // 不得再把本地内容写回快照（尤其是 beforeunload 的卸载保存），
          // 否则刷新后重放会抵消 discardOwnSnapshot 的清理。
          if(acceptServerVersionPending) return;
          console.warn('[自动保存] 存在未解决的内容冲突，暂停自动保存（本地修改已写入恢复快照，刷新后以服务端数据为准）');
          if(typeof WorkflowRecovery !== 'undefined'){
            const conflictMeta = {
              workflowId: workflowId,
              userId: getUserId(),
              baseHash: (autoSaveState.getConfirmedHash
                && autoSaveState.getConfirmedHash(workflowId))
                || null,
              ...WorkflowRecovery.createWriteIdentity()
            };
            // beforeunload 同步上下文不能等 IDB 事务：先 best-effort 同步排队，
            // 未就绪再异步补写（与 startUnloadSend 同哲学）
            if(opts.unload === true){
              if(!WorkflowRecovery.saveSnapshotSync(body, conflictMeta)){
                WorkflowRecovery.saveSnapshot(body, conflictMeta).catch(() => null);
              }
            } else {
              await WorkflowRecovery.saveSnapshot(body, conflictMeta).catch(() => null);
            }
          }
          return;
        }

        const keepalive = !!opts.keepalive;
        const unload = opts.unload === true;

        // 实际发起 PUT 才显示保存按钮环绕 loading（门命中/冲突熔断等早退不显示）
        saveBtnSavingStart();
        ringStarted = true;

        // 跟踪在途请求，并在发起新请求前中止本页旧请求，降低过期
        // payload 晚到的概率。已到达服务端的请求不可撤回，由服务端
        // X-Base-Hash CAS 与下轮 poll 的哈希感知保证收敛。
        const controller = new AbortController();
        if(typeof autoSaveState !== 'undefined'){
          autoSaveState.abortInFlight();
          sentVersion = autoSaveState.beginSend(controller, keepalive);
        }

        // CAS 基值：本次编辑所基于的服务端内容哈希（无基线时为空，不做 CAS）
        const baseHash = (typeof autoSaveState !== 'undefined')
          ? autoSaveState.getConfirmedHash(workflowId)
          : null;

        const recoveryMeta = (typeof WorkflowRecovery !== 'undefined') ? {
          version: sentVersion,
          workflowId: workflowId,
          userId: getUserId(),
          baseHash: baseHash,
          ...WorkflowRecovery.createWriteIdentity()
        } : null;

        const requestUrl = `/api/video-workflow/${workflowId}`;
        const requestHeaders = {
            'Content-Type': 'application/json',
            'Authorization': getAuthToken(),
            'X-User-Id': getUserId()
          };
        if(baseHash) requestHeaders['X-Base-Hash'] = baseHash;
        const requestOptions = {
            method: 'PUT',
            // 页面卸载（beforeunload）触发的保存需要 keepalive，
            // 否则请求会在页面销毁时被浏览器取消
            keepalive: keepalive,
            signal: controller.signal,
            headers: requestHeaders,
            body: body
          };

        let responsePromise;
        let recoveryWritePromise = Promise.resolve(null);
        if(unload && recoveryMeta){
          // beforeunload 的关键不变式：fetch 必须在本次同步调用栈、任何 await 之前启动。
          // startUnloadSend 先同步尽力排队 IDB put，随后立即调用 sendRequest；若连接
          // 尚未打开，再在 fetch 已启动后异步补写快照。
          const started = WorkflowRecovery.startUnloadSend(
            body,
            recoveryMeta,
            requestUrl,
            requestOptions
          );
          responsePromise = started.sendPromise;
          if(typeof autoSaveState !== 'undefined'){
            autoSaveState.markRequestStarted(sentVersion);
          }
          recoveryWritePromise = started.snapshotPromise.catch(() => null);
        } else {
          // 常规自动保存先等待本地快照事务提交，再发网络请求。
          if(recoveryMeta){
            await WorkflowRecovery.saveSnapshot(body, recoveryMeta).catch(() => null);
          }
          responsePromise = fetch(requestUrl, requestOptions);
          if(typeof autoSaveState !== 'undefined'){
            autoSaveState.markRequestStarted(sentVersion);
          }
        }

        const response = await responsePromise;

        const result = await response.json();

        if(result.code === 0){
          console.log('自动保存成功:', new Date().toLocaleTimeString(), 'defaultWorldId:', state.defaultWorldId);
          // 服务端已确认这份 body，以响应返回的最新内容哈希滚动去重门基线
          // 与 CAS 基值。若这是被更新发送取代的迟到 ack，服务端可能随后被
          // 更新请求覆盖——下轮 poll 的哈希漂移会使门失效并重传收敛
          if(typeof autoSaveState !== 'undefined'){
            autoSaveState.setConfirmedBody(
              workflowId, body, result.data && result.data.content_hash);
          }
          // 仅当"该请求是最新发送且成功"才清除恢复记录：被新请求取代的旧请求
          // 的成功 ack（endSend 返回 false）不得清掉新请求的恢复快照——否则
          // 新请求随后失败时，兜底记录已被误清，数据丢失
          if(typeof autoSaveState !== 'undefined'){
            const confirmed = autoSaveState.endSend(sentVersion, true);
            if(confirmed && recoveryMeta && typeof WorkflowRecovery !== 'undefined'){
              // unload 冷启动时可能在 fetch 之后异步补写快照；先等写入结束，再按
              // snapshotId/version 条件删除，避免清理先发生后又写回陈旧记录。
              await recoveryWritePromise;
              await WorkflowRecovery.clearConfirmedSnapshot(recoveryMeta).catch(() => false);
            }
          }
        } else if(result.code === 409){
          // CAS 冲突：内容已被其他会话修改。保持 dirty（恢复快照已在发送前
          // 写入，本地修改不丢），更新已知服务端哈希使去重门立即失效，
          // 并熔断后续自动保存（不再周期性全量重试）；toast 仅首次提示
          console.warn('自动保存冲突:', result.message);
          if(typeof autoSaveState !== 'undefined'){
            const alreadyBlocked = autoSaveState.isConflictBlocked(workflowId);
            autoSaveState.endSend(sentVersion, false);
            if(result.data && result.data.content_hash){
              autoSaveState.noteServerHash(workflowId, result.data.content_hash);
            }
            autoSaveState.noteConflict(workflowId);
            if(!alreadyBlocked){
              showToast(result.message || '工作流内容已被其他会话修改，自动保存已暂停；本地修改已保留，刷新页面后将自动恢复', 'warning');
            }
          }
          markSaveConflict();
        } else {
          console.warn('自动保存失败:', result.message);
          if(typeof autoSaveState !== 'undefined'){
            autoSaveState.endSend(sentVersion, false);
          }
        }
      } catch(error){
        console.error('自动保存错误:', error);
        if(typeof autoSaveState !== 'undefined'){
          autoSaveState.endSend(sentVersion, false);
        }
      } finally {
        if(ringStarted) saveBtnSavingEnd();
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
    /**
     * 重放上次的自动保存恢复记录（大工作流关页丢失的兜底）。
     *
     * autoSaveWorkflow 在常规 PUT 发送前把 payload 写入 IndexedDB（WorkflowRecovery），
     * 确认成功后按 snapshotId/version 条件清除。页面卸载导致请求丢失时记录仍在：
     * 此处把当前用户 + 当前工作流独立 key 下的未确认 payload 重放给服务器。
     * 重放前仍经 matchesReplayContext 做 fail-closed 二次校验。
     * 重放成功后 reload 一次让 UI 展示恢复状态，且显式跳过二次恢复，
     * 避免记录删除失败或被另一标签页替换时发生无界递归。
     */
    async function maybeRecoverPendingAutoSave(workflowId){
      if(typeof WorkflowRecovery === 'undefined' || !workflowId) return;
      let record = null;
      try {
        record = await WorkflowRecovery.loadSnapshot({
          workflowId: workflowId,
          userId: getUserId()
        });
      } catch(e) {
        return;
      }
      if(!record || !record.payload) return;

      // 双重门控：loadSnapshot 已按 userId/workflowId 读取独立 key，此处再次校验
      // 记录内容，损坏或缺少身份字段时 fail-closed，绝不跨工作流/账号重放。
      if(!WorkflowRecovery.matchesReplayContext(record, {
        workflowId: workflowId,
        userId: getUserId()
      })){
        console.warn('[自动保存恢复] 恢复记录不属于当前工作流/用户，跳过重放以避免跨工作流覆盖');
        return;
      }

      try {
        // 重放携带快照写入时的服务端哈希做 CAS：若服务端已被其他会话推进，
        // 强制重放会把别人的新内容覆盖掉。冲突时放弃重放并清除该快照
        // （服务端已有更新的权威版本）。无 baseHash 的存量快照维持强制重放。
        const replayHeaders = {
          'Content-Type': 'application/json',
          'Authorization': getAuthToken(),
          'X-User-Id': getUserId()
        };
        if(record.baseHash) replayHeaders['X-Base-Hash'] = record.baseHash;
        const response = await fetch(`/api/video-workflow/${workflowId}`, {
          method: 'PUT',
          headers: replayHeaders,
          body: record.payload
        });
        const result = await response.json();
        if(result.code === 0){
          const cleared = await WorkflowRecovery.clearSnapshot(record).catch(() => false);
          console.warn('[自动保存恢复] 未确认的自动保存已重放到服务器，重新加载工作流');
          showToast('已恢复上次未送达的自动保存', 'success');
          if(!cleared){
            // 可能是另一标签页已写入更新快照，也可能是 IDB 删除失败。
            // 本次只重新加载 UI，不再递归重放，避免 GET → PUT → reload 无界循环。
            console.warn('[自动保存恢复] 恢复记录已变更或未能清除，保留供后续页面处理');
          }
          await loadWorkflow(workflowId, { skipAutoSaveRecovery: true });
        } else if(result.code === 409){
          // CAS 冲突：服务器已有更新版本，重放会覆盖他人内容——放弃并清除
          console.warn('[自动保存恢复] 服务器版本较新，放弃重放:', result.message);
          await WorkflowRecovery.clearSnapshot(record).catch(() => false);
          showToast('服务器上的工作流已有更新版本，未恢复本地未送达的修改', 'warning');
        } else {
          console.warn('[自动保存恢复] 重放失败:', result.message);
          showToast('上次自动保存可能未送达，恢复失败，请手动保存', 'error');
        }
      } catch(error){
        console.error('[自动保存恢复] 重放异常:', error);
        showToast('上次自动保存可能未送达，恢复失败，请手动保存', 'error');
      }
    }

    async function loadWorkflow(workflowId, options){
      if(!workflowId) return false;
      const loadOptions = options || {};
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
              // select option.value 始终是字符串，显式转换避免 number/string 匹配失败
              defaultWorldSelect.value = String(workflow.default_world_id);
              // 更新视觉状态（移除红色警告、同步自定义可搜索下拉的触发器文本）
              if(typeof updateWorldSelectorState === 'function'){
                updateWorldSelectorState();
              }
              // 兜底：若世界缓存还没加载完导致 updateWorldSelectorState 取不到世界名，
              // 主动刷新一次世界选择器（populateWorldSelector 内部会恢复 state.defaultWorldId）
              const cachedWorld = (typeof getCachedWorld === 'function') ? getCachedWorld(workflow.default_world_id) : null;
              if(!cachedWorld && typeof populateWorldSelector === 'function'){
                console.log('[加载工作流] 世界缓存未就绪，重新填充世界选择器');
                await populateWorldSelector();
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

          // 加载成功即建立上传去重基线：此刻的序列化 == 服务端已确认内容，
          // 基线同时记录服务端权威内容哈希（GET 返回），供去重门双条件比对
          // 与后续 PUT 的 CAS（X-Base-Hash）使用。
          // 恢复重放（maybeRecoverPendingAutoSave）成功后会重新 loadWorkflow，
          // 基线随重放后的最新服务端内容重建，语义保持一致。
          try {
            if(typeof autoSaveState !== 'undefined'){
              autoSaveState.setConfirmedBody(
                workflowId, buildAutoSaveBody(), workflow.content_hash);
              autoSaveState.noteServerHash(workflowId, workflow.content_hash);
            }
          } catch(e) {
            console.warn('[加载工作流] 建立保存去重基线失败:', e);
          }
        } else {
          showToast(result.message || '加载工作流失败', 'error');
        }
      } catch(error){
        console.error('Load error:', error);
        showToast('加载工作流失败', 'error');
      }

      // 加载成功后检查未确认的自动保存恢复记录（大工作流关页丢失的兜底）
      if(success && !loadOptions.skipAutoSaveRecovery){
        await maybeRecoverPendingAutoSave(workflowId);
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
          const filteredByDriver = (window.TaskConfig.filterAvailableModelOptions
            ? window.TaskConfig.filterAvailableModelOptions(allVideoOptions, getDriverStatusConfig())
            : allVideoOptions);
          const videoOptions = filteredByDriver.filter(opt => {
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
            if (!videoOptions.find(o => o.value === node.data.videoModel)) {
              if (node.data.videoModel && typeof ensureSelectHasSavedOption === 'function') {
                ensureSelectHasSavedOption(videoModelEl, node.data.videoModel);
                videoModelEl.value = node.data.videoModel;
              } else {
                node.data.videoModel = videoOptions[0].value;
                videoModelEl.value = node.data.videoModel;
              }
            }
            if (typeof applyDriverStatusToSelect === 'function') {
              applyDriverStatusToSelect(videoModelEl, node.data.videoModel);
            }
          }
        }

        // 刷新视频分辨率选项（配置加载后模型支持情况可能变化）
        if (typeof node.updateShotGroupResolutionOptions === 'function') {
          node.updateShotGroupResolutionOptions(node.data.videoModel);
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
          const filteredByDriver = (window.TaskConfig.filterAvailableModelOptions
            ? window.TaskConfig.filterAvailableModelOptions(allVideoOptions, getDriverStatusConfig())
            : allVideoOptions);
          const videoOptions = filteredByDriver.filter(opt => {
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
            if (!videoOptions.find(o => o.value === currentVideoModel)) {
              if (currentVideoModel && typeof ensureSelectHasSavedOption === 'function') {
                ensureSelectHasSavedOption(videoModelEl, currentVideoModel);
                videoModelEl.value = currentVideoModel;
              } else {
                node.data.videoModel = videoOptions[0].value;
                videoModelEl.value = node.data.videoModel;
              }
            }
            if (typeof applyDriverStatusToSelect === 'function') {
              applyDriverStatusToSelect(videoModelEl, node.data.videoModel);
            }
          }
        }

        // 刷新视频分辨率选项（配置加载后模型支持情况可能变化）
        if (typeof node.updateShotFrameResolutionOptions === 'function') {
          node.updateShotFrameResolutionOptions(node.data.videoModel);
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
        // 清理节点级持有资源（如全景查看器的 WebGL 上下文），避免跨工作流泄漏
        if(window.PanoramaViewerRegistry) window.PanoramaViewerRegistry.destroyAll();
        
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
        
        // 恢复分组（重算包围盒依赖节点尺寸，需在节点恢复之后执行）
        if(typeof restoreGroups === 'function'){
          restoreGroups(data.groups || [], data.nextGroupId);
        } else {
          state.groups = [];
          if(data.nextGroupId) state.nextGroupId = data.nextGroupId;
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
        if(typeof restoreGroups === 'function'){
          restoreGroups([], 1);
        } else {
          state.groups = [];
        }
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
        // 恢复上次失败原因（失败状态持久化）
        node.data.lastError = nodeData.data.lastError || '';

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
          
          // 更新算力显示（复用节点内实时计算，感知生成模式/分辨率等算力上下文）
          if(typeof el._updateComputingPowerDisplay === 'function'){
            el._updateComputingPowerDisplay();
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

          // 更新图片模式UI：复用节点内暴露的同一份实现（updateImageModeUI），
          // 统一处理 首尾帧容器/端口/参考图/参考音频 显隐、提示文案与尾帧可用性。
          // 历史教训：此处曾手写复制一份显隐逻辑，选择器写错（.first-last-fields 不存在）
          // 且与节点内行为漂移（video 字段显隐不一致），导致刷新后 UI 错乱。
          const imageModeSelect = el.querySelector('.image-mode-select');
          const imageMode = node.data.imageMode || 'first_last_frame';
          if(imageModeSelect) imageModeSelect.value = imageMode;
          if(typeof el._updateImageModeUI === 'function'){
            el._updateImageModeUI();
          }

          // 渲染参考图预览
          const referencePreviewList = el.querySelector('.reference-preview-list');
          if(referencePreviewList && node.data.referenceUrls && node.data.referenceUrls.length > 0) {
            referencePreviewList.innerHTML = '';
            node.data.referenceUrls.forEach((url, idx) => {
              const item = document.createElement('div');
              item.style.cssText = 'position: relative; width: 50px; height: 50px;';
              item.innerHTML = `
                <img src="${escapeHtml(url)}" style="width: 100%; height: 100%; object-fit: cover; border-radius: 4px; cursor: pointer;" />
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
                    newItem.innerHTML = `<img src="${escapeHtml(u)}" style="width: 100%; height: 100%; object-fit: cover; border-radius: 4px;" /><div style="position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.6); color: white; font-size: 10px; text-align: center; border-radius: 0 0 4px 4px; padding: 1px 0;">图${i + 1}</div>`;
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

          // 恢复上次失败原因（失败状态持久化，重载后重新渲染）
          if(node.data.lastError){
            const genStatus = el.querySelector('.gen-status');
            if(genStatus){
              genStatus.style.display = 'block';
              genStatus.style.color = '#dc2626';
              genStatus.textContent = node.data.lastError;
            }
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
        // 恢复上次失败原因（失败状态持久化）
        node.data.lastError = nodeData.data.lastError || '';
        // 如果有URL，显示预览
        if(node.data.url){
          const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
          if(el){
            const previewField = el.querySelector('.video-preview-field');
            const previewActionsField = el.querySelector('.video-preview-actions-field');
            const thumbVideo = el.querySelector('.video-thumb');
            const nameEl = el.querySelector('.video-name');
            if(previewField && thumbVideo && nameEl){
              // 封面帧与悬停播放逻辑已内置于 setupVideoThumbnail（工作流重载后同样生效）
              setupVideoThumbnail(thumbVideo, node.data.url);
              const name = node.data.name || '';
              const displayName = name.length > 10 ? name.substring(0, 10) + '...' : name;
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

        // 恢复上次失败原因（失败状态持久化，重载后重新渲染）
        if(node.data.lastError){
          const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
          if(el){
            const statusField = el.querySelector('.video-status-field');
            const statusEl = el.querySelector('.video-status');
            if(statusField && statusEl){
              statusField.style.display = 'block';
              setStatusEl(statusEl, `✗ 生成失败: ${node.data.lastError}`, '#dc2626');
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
            const ratioField = el.querySelector('.image-ratio-field') || ratioEl.closest('.field');
            const labelMap = { '9:16': '竖屏 (9:16)', '16:9': '横屏 (16:9)', '1:1': '正方形 (1:1)', '3:4': '竖屏 (3:4)', '4:3': '横屏 (4:3)' };
            if(config && Array.isArray(config.ratios) && config.ratios.length === 0) {
              if(ratioField) ratioField.style.display = 'none';
            } else {
              if(ratioField) ratioField.style.display = '';
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

          // 恢复上次失败原因（失败状态持久化，重载后重新渲染）
          if(node.data.lastError){
            const statusEl = el.querySelector('.image-edit-status');
            if(statusEl){
              statusEl.style.display = 'block';
              setStatusEl(statusEl, node.data.lastError, '#dc2626');
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
        // 总分镜时长控制倍率（旧工作流缺省 0=不限制）
        const savedTotalDurationMultiplier = Number(nodeData.data.totalDurationMultiplier);
        node.data.totalDurationMultiplier = [0, 1, 2, 3].includes(savedTotalDurationMultiplier)
          ? savedTotalDurationMultiplier
          : 0;
        // 分镜拆分模式 + 质检（与故事板对齐；旧工作流缺省 balanced / 关闭质检）
        const savedSequenceMode = nodeData.data.sequenceMode;
        node.data.sequenceMode = ['speed', 'balanced', 'quality'].includes(savedSequenceMode)
          ? savedSequenceMode
          : 'balanced';
        node.data.enableScriptSplitQc = nodeData.data.enableScriptSplitQc === true;
        const savedQcRounds = Number(nodeData.data.scriptSplitQcMaxRounds);
        node.data.scriptSplitQcMaxRounds = [1, 2, 3, 4, 5].includes(savedQcRounds) ? savedQcRounds : 2;
        // 参数区分组折叠态（旧数据缺省全折叠；开启质检时 advanced 展开）
        const savedSections = nodeData.data.uiSections || {};
        node.data.uiSections = {
          gridVideo: savedSections.gridVideo === true,
          language: savedSections.language === true,
          advanced: savedSections.advanced === true || node.data.enableScriptSplitQc === true,
        };
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
        node.data.enableThinking = nodeData.data.enableThinking !== undefined ? nodeData.data.enableThinking : false;
        node.data.thinkingEffort = nodeData.data.thinkingEffort || 'medium';
        node.data.thinkingExplicitlyDisabled = nodeData.data.thinkingExplicitlyDisabled !== undefined ? nodeData.data.thinkingExplicitlyDisabled : false;

        // 恢复分段拆分任务状态（见设计文档 §14）
        // 刷新后若有未完成的 splitTaskId，恢复轮询；已应用结果则不重复创建节点。
        node.data.splitTaskId = nodeData.data.splitTaskId || null;
        node.data.splitTaskMode = nodeData.data.splitTaskMode || null;
        node.data.splitTaskResultApplied = nodeData.data.splitTaskResultApplied === true;
        node.data.splitTaskPostActionStarted = nodeData.data.splitTaskPostActionStarted === true;

        const el = canvasEl.querySelector(`.node[data-node-id="${node.id}"]`);
        if(el){
          const textareaEl = el.querySelector('.script-textarea');
          const durationSelectEl = el.querySelector('.script-duration-select');
          const forceMediumShotEl = el.querySelector('.script-force-medium-shot');
          const noBgMusicEl = el.querySelector('.script-no-bg-music');
          const splitMultiDialogueEl = el.querySelector('.script-split-multi-dialogue');
          const splitBtn = el.querySelector('.script-split-btn');
          const infoField = el.querySelector('.script-info-field');
          const nameEl = el.querySelector('.script-name');
          const lengthEl = el.querySelector('.script-length');
          const charCountEl = el.querySelector('.script-char-count');

          if(textareaEl) textareaEl.value = node.data.scriptContent;
          if(durationSelectEl) durationSelectEl.value = String(node.data.maxGroupDuration);
          const totalDurationSelectRestoreEl = el.querySelector('.script-total-duration-select');
          if(totalDurationSelectRestoreEl) totalDurationSelectRestoreEl.value = String(node.data.totalDurationMultiplier);
          if(typeof node.updateTotalDurationHint === 'function') node.updateTotalDurationHint();
          if(forceMediumShotEl) forceMediumShotEl.checked = node.data.forceMediumShot;
          if(noBgMusicEl) noBgMusicEl.checked = node.data.noBgMusic;
          if(splitMultiDialogueEl) splitMultiDialogueEl.checked = node.data.splitMultiDialogue;
          const sequenceModeEl = el.querySelector('.script-sequence-mode');
          if(sequenceModeEl) {
            const isEnterprise = state.editionInfo && state.editionInfo.mode === 'enterprise';
            if(node.data.sequenceMode === 'quality' && !isEnterprise) {
              node.data.sequenceMode = 'balanced';
            }
            sequenceModeEl.value = node.data.sequenceMode || 'balanced';
            const qualityOpt = sequenceModeEl.querySelector('option[value="quality"]');
            if(qualityOpt) qualityOpt.disabled = !isEnterprise;
          }
          const enableSplitQcEl = el.querySelector('.script-enable-split-qc');
          const qcRoundsFieldEl = el.querySelector('.script-qc-rounds-field');
          const qcMaxRoundsEl = el.querySelector('.script-qc-max-rounds');
          if(enableSplitQcEl) enableSplitQcEl.checked = node.data.enableScriptSplitQc === true;
          if(qcMaxRoundsEl) qcMaxRoundsEl.value = String(node.data.scriptSplitQcMaxRounds || 2);
          if(qcRoundsFieldEl) {
            qcRoundsFieldEl.style.display = node.data.enableScriptSplitQc === true ? 'block' : 'none';
          }
          // 恢复参数分组折叠
          if(typeof node.setParamGroupOpen === 'function' && node.data.uiSections) {
            ['gridVideo', 'language', 'advanced'].forEach((key) => {
              node.setParamGroupOpen(key, node.data.uiSections[key] === true);
            });
          }

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
          const enableThinkingEl = el.querySelector('.script-enable-thinking');
          const thinkingEffortEl = el.querySelector('.script-thinking-effort');
          if(enableThinkingEl) enableThinkingEl.checked = node.data.enableThinking === true;
          if(thinkingEffortEl) thinkingEffortEl.value = node.data.thinkingEffort || 'medium';
          if(splitModelEl) splitModelEl.dispatchEvent(new Event('change', { bubbles: true }));

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

          if(typeof node.updateParamGroupSummaries === 'function') {
            node.updateParamGroupSummaries();
          }

          // 恢复未完成的分段拆分任务轮询（见设计文档 §14 createScriptNodeWithData）
          // 任务已应用结果或已无活跃任务则不恢复。
          if (window.ScriptSplitTask && node.data.splitTaskId && !node.data.splitTaskResultApplied) {
            const statusEl2 = el.querySelector('.script-status');
            const splitBtn2 = el.querySelector('.script-split-btn');
            const splitGridBtn2 = el.querySelector('.script-split-grid-btn');
            const gridStatusEl2 = el.querySelector('.script-grid-status');
            if (splitBtn2) splitBtn2.disabled = true;
            if (splitGridBtn2) splitGridBtn2.disabled = true;
            window.ScriptSplitTask.pollScriptSplitTask(node.data.splitTaskId, {
              onUpdate: (status) => {
                const targetEl = node.data.splitTaskMode === 'split_and_generate_grid' ? gridStatusEl2 : statusEl2;
                if (targetEl) { targetEl.style.display = 'block'; targetEl.style.color = '#666'; targetEl.textContent = status.message || '拆分中…'; }
              },
              onComplete: async (parsedData) => {
                if (node.data.splitTaskMode === 'split_and_generate_grid') {
                  if (node.data.splitTaskPostActionStarted) { if (splitGridBtn2) splitGridBtn2.disabled = false; if (splitBtn2) splitBtn2.disabled = false; return; }
                  node.data.splitTaskPostActionStarted = true;
                  // 宫格模式：交给节点的 runGridFlow（通过模拟无法直接调用，降级为先应用结果）
                  if (node.applyParsedData) { await node.applyParsedData(parsedData, { autoGenerateFrames: false }); }
                  node.data.splitTaskResultApplied = true;
                  if (window.safeAutoSave) window.safeAutoSave();
                } else {
                  if (node.applyParsedData) { await node.applyParsedData(parsedData); }
                  node.data.splitTaskResultApplied = true;
                  if (window.safeAutoSave) window.safeAutoSave();
                }
                if (splitBtn2) splitBtn2.disabled = false;
                if (splitGridBtn2) splitGridBtn2.disabled = false;
              },
              onPaused: (status) => {
                const targetEl = node.data.splitTaskMode === 'split_and_generate_grid' ? gridStatusEl2 : statusEl2;
                if (targetEl) { targetEl.style.display = 'block'; targetEl.style.color = '#d97706'; targetEl.textContent = status.message || '任务暂停'; }
                if (splitBtn2) splitBtn2.disabled = false;
                if (splitGridBtn2) splitGridBtn2.disabled = false;
              },
              onError: (error) => {
                const targetEl = node.data.splitTaskMode === 'split_and_generate_grid' ? gridStatusEl2 : statusEl2;
                if (targetEl) { targetEl.style.display = 'block'; targetEl.style.color = '#dc2626'; targetEl.textContent = '拆分失败: ' + (error.message || ''); }
                if (splitBtn2) splitBtn2.disabled = false;
                if (splitGridBtn2) splitGridBtn2.disabled = false;
              },
            });
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
        // 从 URL 参数中获取 workflowId（与 getWorkflowIdFromUrl 保持一致）
        const workflowId = (typeof getWorkflowIdFromUrl === 'function')
          ? getWorkflowIdFromUrl()
          : new URLSearchParams(window.location.search).get('id');
        if(!workflowId) return;
        
        const userId = localStorage.getItem('user_id');
        // 兼容期双写：登录态以 localStorage.auth_token 为准
        const loggedIn = userId && !!localStorage.getItem('auth_token');

        if(!loggedIn){
          return;
        }

        const response = await fetch(`/api/video-workflow/${workflowId}/poll-status`, {
          method: 'GET',
          headers: {
            'X-User-Id': userId,
            'Authorization': `Bearer ${localStorage.getItem('auth_token') || ''}`
          }
        });
        
        const result = await response.json();
        
        if(result.code === 0 && result.data){
          // 记录服务端权威内容哈希：去重门的第二条件。服务端内容一旦被其他
          // 会话/迟到请求改写，该值与基线哈希不一致，门即失效并重传收敛
          if(typeof autoSaveState !== 'undefined' && result.data.content_hash){
            autoSaveState.noteServerHash(workflowId, result.data.content_hash);
          }
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
          // 性能优化：世界数据指纹比对 + 无节点更新时跳过——原实现每 60s 轮询
          // 都对所有分镜节点执行 3 组 innerHTML 重建，节点多时造成周期性卡顿
          const updatedNodes = result.data.updated_nodes || [];
          const worldFingerprint = JSON.stringify([
            state.worldCharacters, state.worldProps, state.worldLocations
          ]);
          if(worldFingerprint !== state._lastWorldFingerprint || updatedNodes.length > 0){
            state._lastWorldFingerprint = worldFingerprint;
            state.nodes.forEach(node => {
              if(node.updateReferences) {
                node.updateReferences();
              }
            });
          }

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
      
      errorEl.innerHTML = `<strong>生成失败:</strong> ${escapeHtml(errorMessage)}`;
      
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
          // 封面帧与悬停播放逻辑已内置于 setupVideoThumbnail（不再自动循环播放）
          setupVideoThumbnail(thumbVideo, url);
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
            if (typeof nodeEl._syncVideoModeButtons === 'function') {
              nodeEl._syncVideoModeButtons(nodeData.data.videoMode);
            } else {
              const modeBtns = nodeEl.querySelectorAll('.video-mode-btn');
              modeBtns.forEach(btn => {
                btn.classList.toggle('is-active', btn.dataset.mode === nodeData.data.videoMode);
              });
            }
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

          // 恢复视频分辨率选项（基于已恢复的视频模型与保存的分辨率）
          if(node.updateShotFrameResolutionOptions) {
            node.updateShotFrameResolutionOptions(node.data.videoModel);
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
