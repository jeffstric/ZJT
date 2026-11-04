
    // 前端直传七牛（CDN 开启时）：token → XHR 直传 → confirm 回源落盘入库。
    // 返回 {url}；任何不可用/失败环节返回 {fallback, reason} 交由调用方降级
    // 走服务器 multipart 上传，不打断上传主流程（CDN 未启用属常态，静默降级）。
    async function uploadFileDirectToCdn(file){
      // 1) 颁发直传凭证（token 绑定 key + fsizeLimit，30 分钟过期）
      const tokenForm = new FormData();
      tokenForm.append('filename', file.name || '');
      tokenForm.append('size', String(file.size || 0));
      const tokenResp = await fetch('/api/video-workflow/upload-token', {
        method: 'POST',
        headers: {
          'Authorization': getAuthToken(),
          'X-User-Id': getUserId()
        },
        body: tokenForm
      });
      if (!tokenResp.ok) return { fallback: true, reason: 'token_http_' + tokenResp.status };
      const tokenData = await tokenResp.json().catch(() => null);
      if (!tokenData || tokenData.code !== 0 || !tokenData.data) {
        return { fallback: true, reason: 'token_bad_response' };
      }
      const d = tokenData.data;
      if (!d.direct_upload) return { fallback: true, reason: d.reason || 'cdn_disabled' };

      // 2) XHR 直传七牛（fetch 无上传进度回调；form 协议与 world-import 直传一致）
      await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', d.upload_url, true);
        xhr.timeout = 600000; // 大视频直传保护（200MB 慢速链路留足余量）
        const fd = new FormData();
        fd.append('token', d.token);
        fd.append('key', d.key);
        fd.append('fname', file.name || 'file');
        fd.append('file', file);
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve();
          } else {
            reject(new Error('HTTP ' + xhr.status + ': ' + String(xhr.responseText || '').slice(0, 200)));
          }
        };
        xhr.onerror = () => reject(new Error('网络错误'));
        xhr.ontimeout = () => reject(new Error('超时'));
        xhr.send(fd);
      });

      // 3) 通知服务端回源下载到本地（大小+魔数校验）并入库，返回本站永久URL
      const confirmForm = new FormData();
      confirmForm.append('key', d.key);
      const confirmResp = await fetch('/api/video-workflow/upload-confirm', {
        method: 'POST',
        headers: {
          'Authorization': getAuthToken(),
          'X-User-Id': getUserId()
        },
        body: confirmForm
      });
      if (!confirmResp.ok) return { fallback: true, reason: 'confirm_http_' + confirmResp.status };
      const confirmData = await confirmResp.json().catch(() => null);
      if (confirmData && confirmData.code === 0 && confirmData.data && confirmData.data.url) {
        return { url: confirmData.data.url };
      }
      return { fallback: true, reason: 'confirm_bad_response' };
    }

    // 上传文件到服务器，返回永久URL
    // CDN 开启时优先前端直传七牛（上传流量不占服务器带宽；直传完成即 CDN 就绪，
    // 消除"本地 206→302"播放换源竞态）；直传不可用或任一环节失败自动降级走
    // 服务器 multipart 上传，行为与直传功能上线前完全一致。
    async function uploadFile(file){
      try {
        const direct = await uploadFileDirectToCdn(file);
        if (direct && direct.url) return direct.url;
        console.warn('CDN 直传不可用，降级服务器上传:', direct && direct.reason);
      } catch (err) {
        console.warn('CDN 直传失败，降级服务器上传:', err);
      }

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
    async function generateVideoFromImage(imageUrl, prompt, duration, count, ratio, videoModel, imageMode, referenceImages, audioUrls, videoUrls, mediaReferences, resolution, enableFaceMask, faceMaskReferenceUrls){
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
      // 是否处理人脸（仅 seedance2.0 商业版生效）
      if(enableFaceMask){
        form.append('enable_face_mask', 'true');
        // 人脸遮盖白名单：只对角色参考图做遮盖，道具/场景参考图不参与
        if(faceMaskReferenceUrls && faceMaskReferenceUrls.length){
          form.append('face_mask_reference_urls', (Array.isArray(faceMaskReferenceUrls) ? faceMaskReferenceUrls : [faceMaskReferenceUrls]).join(','));
        }
      }

      if(userId){
        form.append('user_id', userId);
      }
      if(authToken){
        form.append('auth_token', authToken);
      }

      const res = await authPostForm('/api/ai-app-run-image', form);

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

      const res = await authPostForm('/api/ai-app-run', form);

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

      // token 走 Authorization 头，不再拼进 URL（防 Referer/日志/历史记录泄漏）
      const url = `/api/get-status/${projectIdsStr}`;
      const reqHeaders = authToken ? { 'Authorization': `Bearer ${authToken}` } : {};
      const res = await fetch(url, { headers: reqHeaders });
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
        const anyCancelled = tasks.some(t => t.status === 'CANCELLED');
        const anyRunning = tasks.some(t => t.status === 'RUNNING' || t.status === 'QUEUED' || t.status === 'CANCELLING');

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

        // 全局状态判断（QUEUED / CANCELLING 与 RUNNING 同为未终态；CANCELLED 是终态）
        let globalStatus = 'RUNNING';
        if(allSuccess){
          globalStatus = 'SUCCESS';
        } else if(anyFailed && !anyRunning){
          globalStatus = 'FAILED';
        } else if(anyCancelled && !anyRunning){
          globalStatus = 'CANCELLED';
        }
        
        return { 
          status: globalStatus, 
          tasks: taskDetails,
          error: anyFailed ? '部分任务失败' : null
        };
      } else {
        // 单任务响应
        const results = extractResultsArray(data);
        const singleError = data.reason || data.error || null;
        return {
          status: data.status || 'RUNNING',
          tasks: [{
            status: data.status || 'RUNNING',
            result: results.length > 0 ? results[0] : null,
            error: singleError
          }],
          error: singleError
        };
      }
    }

    // 取消排队中的任务（仅后端认定的排队阶段可取消；已提交上游会返回 409）
    async function cancelQueuedAiTask(aiToolId){
      const authToken = getAuthToken();
      const headers = authToken ? { 'Authorization': `Bearer ${authToken}` } : {};
      const res = await fetch(`/api/ai-tool/${aiToolId}/cancel`, {
        method: 'POST',
        headers
      });
      let data = null;
      try { data = await res.json(); } catch(e) { /* 非 JSON 响应 */ }
      if(res.ok && data && data.code === 0){
        var payload = data.data || {};
        return { success: true, status: payload.status || 'CANCELLED', message: data.message || '' };
      }
      return {
        success: false,
        message: (data && data.message) || '取消任务失败',
        status: res.status
      };
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
          // token 走 Authorization 头，不再拼进 URL（防 Referer/日志/历史记录泄漏）
          var authToken = getAuthToken();
          var reqHeaders = authToken ? { 'Authorization': 'Bearer ' + authToken } : {};
          var res = await fetch(opts.statusUrl, { method: 'GET', headers: reqHeaders });
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
     * 带 Authorization 头提交 FormData（POST）。
     * require_permission 鉴权只认 Authorization 头 / cookie，读不到 form body 里的
     * auth_token；cookie 会话失效时裸 fetch 会 401，因此统一从 localStorage 补发
     * Bearer 头（token 不拼 URL，防 Referer/日志/历史泄漏）。
     */
    async function authPostForm(url, form) {
      var authToken = getAuthToken();
      var headers = authToken ? { 'Authorization': 'Bearer ' + authToken } : {};
      return fetch(url, { method: 'POST', headers: headers, body: form });
    }

    /**
     * 从非 2xx 响应体提取用户可读错误信息。
     * 401 时给出"重新登录"引导，避免显示含糊的"提交任务失败"
     * （认证失败响应体无 detail/message 字段时的兜底）。
     */
    function extractApiErrorMessage(data, res) {
      if (data && typeof data.detail === 'string') return data.detail;
      if (data && typeof data.message === 'string') return data.message;
      if (res && res.status === 401) return '登录已过期，请保存当前内容后重新登录';
      return (data && (data.detail || data.message)) || '提交任务失败';
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
      module.exports = { getAuthHeaders, appendAuthToForm, authPostForm, extractApiErrorMessage };
    }

