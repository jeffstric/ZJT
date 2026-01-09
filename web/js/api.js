
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

    // 生成视频API调用
    async function generateVideoFromImage(imageUrl, prompt, duration, count, ratio, videoModel){
      // 测试模式：模拟API响应
      if(TEST_MODE){
        console.log('[TEST MODE] 模拟生成视频API调用', { imageUrl, prompt, duration, count, ratio, videoModel });
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
      
      const form = new FormData();
      
      // 直接使用image_urls，不需要重新上传
      form.append('image_urls', imageUrl);
      form.append('prompt', prompt || '');
      form.append('ratio', ratio || '9:16');
      form.append('duration_seconds', duration || 10);
      form.append('count', count || 1);
      form.append('video_model', videoModel || 'sora2');
      
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
      if(data.project_ids && data.project_ids.length > 0){
        return {
          projectIds: data.project_ids,
          status: data.status
        };
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
      
      const url = `/api/get-status/${projectIdsStr}` + (authToken ? `?auth_token=${authToken}` : '');
      const res = await fetch(url);
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

