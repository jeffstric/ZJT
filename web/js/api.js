
    // 上传文件到服务器，返回永久URL
    async function uploadFile(file){
      const formData = new FormData();
      formData.append('file', file);
      
      try {
        const response = await fetch('/api/video-workflow/upload', {
          method: 'POST',
          headers: {
            'Authorization': getAuthToken(),
            'X-User-Id': getUserId()
          },
          body: formData
        });
        
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const result = await response.json();
        if(result.code === 0 && result.data && result.data.url){
          return result.data.url;
        } else {
          throw new Error(result.message || '上传失败');
        }
      } catch(error){
        console.error('Upload error:', error);
        showToast('文件上传失败: ' + error.message, 'error');
        return null;
      }
    }

    // 上传音频文件到TTS临时目录
    async function uploadAudioFile(file){
      const formData = new FormData();
      formData.append('file', file);
      
      try {
        const userId = getUserId();
        const timestamp = Date.now();
        const randomStr = Math.random().toString(36).substring(2, 8);
        const ext = file.name.split('.').pop() || 'wav';
        const filename = `${userId}_${timestamp}_${randomStr}.${ext}`;
        
        const response = await fetch('/api/upload-file', {
          method: 'POST',
          headers: {
            'Authorization': getAuthToken(),
            'X-User-Id': userId
          },
          body: formData
        });
        
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const result = await response.json();
        if(result.code === 0 && result.data && result.data.url){
          return result.data.url;
        } else {
          throw new Error(result.message || '上传失败');
        }
      } catch(error){
        console.error('Audio upload error:', error);
        showToast('音频上传失败: ' + error.message, 'error');
        return null;
      }
    }

    function getVideoResolutionForModel(videoModel, resolution) {
      if(resolution) return resolution;
      if(window.TaskConfig && typeof TaskConfig.getDefaultVideoResolution === 'function') {
        return TaskConfig.getDefaultVideoResolution(videoModel);
      }
      return null;
    }

    function appendVideoResolutionToForm(form, videoModel, resolution) {
      const resolvedResolution = getVideoResolutionForModel(videoModel, resolution);
      if(resolvedResolution) {
        form.append('resolution', resolvedResolution);
      }
      return resolvedResolution;
    }

    // 生成视频API调用
    async function generateVideoFromImage(imageUrl, prompt, duration, count, ratio, videoModel, imageMode, referenceImages, audioUrls, videoUrls, mediaReferences, resolution){
      // 测试模式：模拟API响应
      if(TEST_MODE){
        console.log('[TEST MODE] 模拟生成视频API调用', { imageUrl, prompt, duration, count, ratio, videoModel, imageMode, referenceImages, audioUrls, videoUrls, mediaReferences });
        await new Promise(r => setTimeout(r, 500)); // 模拟网络延迟
        const mockIds = [];
        for(let i = 0; i < (count || 1); i++){
          mockIds.push('mock_project_' + Date.now() + '_' + i);
        }
        return {
          projectIds: mockIds,
          status: 'submitted'
        };
      }

      const userId = localStorage.getItem('user_id');
      const authToken = getAuthToken();

      // 根据 videoModel 获取 task_id
      const taskId = TaskConfig.getTaskIdByKey(videoModel || 'wan22', 'image_to_video');
      if(!taskId){
        throw new Error(`未找到视频模型 ${videoModel} 对应的任务配置`);
      }

      const form = new FormData();

      // 直接使用image_urls，不需要重新上传
      form.append('image_urls', imageUrl || '');
      form.append('prompt', prompt || '');
      form.append('ratio', ratio || '9:16');
      form.append('duration_seconds', duration || 5);
      form.append('count', count || 1);
      form.append('task_id', taskId);
      appendVideoResolutionToForm(form, videoModel || 'wan22', resolution);

      // 图片模式和参考图
      if(imageMode){
        form.append('image_mode', imageMode);
      }
      if(referenceImages){
        form.append('reference_image_urls', referenceImages);
      }

      // 参考音频和视频（支持多个，逗号分隔）
      if(audioUrls){
        form.append('audio_urls', audioUrls);
      }
      if(videoUrls){
        form.append('video_urls', videoUrls);
      }
      // 媒体引用（用于 @ 提及解析）
      if(mediaReferences){
        form.append('media_references', mediaReferences);
      }

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

      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      if(data.project_ids && data.project_ids.length > 0){
        return {
          projectIds: data.project_ids,
          status: data.status
        };
      } else {
        throw new Error(data.detail || data.message || '提交任务失败');
      }
    }

    // 文生视频 API
    async function generateVideoFromText(prompt, duration, count, ratio, videoModel, resolution){
      if(TEST_MODE){
        console.log('[TEST MODE] 模拟文生视频API调用', { prompt, duration, count, ratio, videoModel });
        await new Promise(r => setTimeout(r, 500));
        const mockIds = [];
        for(let i = 0; i < (count || 1); i++){
          mockIds.push('mock_t2v_' + Date.now() + '_' + i);
        }
        return { projectIds: mockIds, status: 'submitted' };
      }

      const userId = localStorage.getItem('user_id');
      const authToken = getAuthToken();

      const taskId = TaskConfig.getTaskIdByKey(videoModel, 'text_to_video');
      if(!taskId){
        throw new Error(`未找到文生视频模型 ${videoModel} 对应的任务配置`);
      }

      const form = new FormData();
      form.append('prompt', prompt || '');
      form.append('ratio', ratio || '9:16');
      form.append('duration_seconds', duration || 5);
      form.append('count', count || 1);
      form.append('task_id', taskId);
      appendVideoResolutionToForm(form, videoModel, resolution);

      if(userId) form.append('user_id', userId);
      if(authToken) form.append('auth_token', authToken);

      const res = await fetch('/api/ai-app-run', {
        method: 'POST',
        body: form
      });

      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      if(data.project_ids && data.project_ids.length > 0){
        return { projectIds: data.project_ids, status: data.status };
      } else {
        throw new Error(data.detail || data.message || '提交任务失败');
      }
    }

    // 查询视频生成状态
    // 测试模式下的模拟状态计数器
    const mockStatusCounter = {};
    
    async function checkVideoStatus(projectIds){
      // 测试模式：模拟状态查询（第2次查询返回成功）
      if(TEST_MODE){
        const key = projectIds.join(',');
        mockStatusCounter[key] = (mockStatusCounter[key] || 0) + 1;
        console.log('[TEST MODE] 模拟查询状态，第', mockStatusCounter[key], '次');
        await new Promise(r => setTimeout(r, 300));
        
        if(mockStatusCounter[key] >= 2){
          // 第2次及以后返回成功，附带模拟视频URL
          const mockResults = projectIds.map((_, i) => 
            'http://ailive.perseids.cn/upload/test_video.mp4'
          );
          return { status: 'SUCCESS', results: mockResults };
        } else {
          return { status: 'RUNNING', results: [] };
        }
      }

      const authToken = getAuthToken();
      const projectIdsStr = projectIds.join(',');
      
      const url = `/api/get-status/${projectIdsStr}` + (authToken ? `?auth_token=${encodeURIComponent(authToken)}` : '');
      const res = await fetch(url);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();

      if(TEST_MODE){
        console.log('[TEST MODE] /api/get-status raw:', data);
      }
      
      if(data.tasks){
        // 多任务响应 - 返回每个任务的详细状态
        const tasks = data.tasks;
        const allSuccess = tasks.every(t => t.status === 'SUCCESS');
        const anyFailed = tasks.some(t => t.status === 'FAILED');
        const anyRunning = tasks.some(t => t.status === 'RUNNING');
        
        // 为每个任务提取结果和错误信息
        const taskDetails = tasks.map(task => {
          const results = extractResultsArray(task);
          return {
            project_id: task.project_id,
            status: task.status || 'RUNNING',
            result: results.length > 0 ? results[0] : null,
            error: task.reason || task.error || null
          };
        });
        
        // 全局状态判断
        let globalStatus = 'RUNNING';
        if(allSuccess){
          globalStatus = 'SUCCESS';
        } else if(anyFailed && !anyRunning){
          globalStatus = 'FAILED';
        }
        
        return { 
          status: globalStatus, 
          tasks: taskDetails,
          error: anyFailed ? '部分任务失败' : null
        };
      } else {
        // 单任务响应
        const results = extractResultsArray(data);
        return {
          status: data.status || 'RUNNING',
          tasks: [{
            status: data.status || 'RUNNING',
            result: results.length > 0 ? results[0] : null,
            error: data.reason || data.error || null
          }],
          error: data.reason || data.error
        };
      }
    }

    // 获取版本信息
    async function getEditionInfo() {
      try {
        const response = await fetch('/api/edition');
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const result = await response.json();
        if (result.code === 0 && result.data) {
          return result.data;
        }
        return { mode: 'community', mode_label: '社区版' };
      } catch (error) {
        console.error('Failed to get edition info:', error);
        return { mode: 'community', mode_label: '社区版' };
      }
    }

    /**
     * 统一轮询任务状态
     * @param {Object} opts
     * @param {string} opts.statusUrl - 状态查询URL（不含auth参数）
     * @param {number} [opts.maxAttempts=120] - 最大轮询次数
     * @param {number} [opts.interval=10000] - 轮询间隔(ms)
     * @param {function} opts.onSuccess - 成功回调(payload)
     * @param {function} opts.onFailed - 失败回调(payload)
     * @param {function} [opts.onTimeout] - 超时回调
     * @param {function} [opts.onPending] - 进行中回调(payload)，返回true可停止轮询
     */
    function pollTaskStatus(opts) {
      var maxAttempts = opts.maxAttempts || 120;
      var interval = opts.interval || 10000;
      var attempts = 0;

      var checkStatus = async function() {
        if (attempts >= maxAttempts) {
          if (opts.onTimeout) opts.onTimeout();
          return;
        }

        attempts++;

        try {
          var authToken = getAuthToken();
          var params = authToken ? '?auth_token=' + encodeURIComponent(authToken) : '';
          var res = await fetch(opts.statusUrl + params, { method: 'GET' });
          var text = await res.text();
          var payload = text ? JSON.parse(text) : null;

          if (!payload) {
            setTimeout(checkStatus, interval);
            return;
          }

          var status = typeof payload.status === 'string' ? payload.status.toUpperCase() : payload.status;

          if (status === 'SUCCESS' || status === 2) {
            opts.onSuccess(payload);
          } else if (status === 'FAILED' || status === -1) {
            opts.onFailed(payload);
          } else {
            if (opts.onPending && opts.onPending(payload) === true) return;
            setTimeout(checkStatus, interval);
          }
        } catch (error) {
          console.error('状态检查失败:', error);
          setTimeout(checkStatus, interval);
        }
      };

      checkStatus();
    }

    /**
     * 向 FormData 追加认证信息（user_id + auth_token）
     * @param {FormData} form
     */
    function appendAuthToForm(form) {
      var userId = getUserId();
      var authToken = getAuthToken();
      if (userId) form.append('user_id', userId);
      if (authToken) form.append('auth_token', authToken);
    }

    /**
     * 获取包含认证信息的请求头
     * @returns {{Authorization: string, 'X-User-Id': string}}
     */
    function getAuthHeaders() {
      return {
        'Authorization': getAuthToken(),
        'X-User-Id': getUserId()
      };
    }

    // ES Module exports（供 Vitest 测试使用，不影响浏览器全局变量）
    if (typeof module !== 'undefined') {
      module.exports = { getAuthHeaders, appendAuthToForm };
    }

