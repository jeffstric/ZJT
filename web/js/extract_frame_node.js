    // ============ 提取首帧节点 ============

    function createExtractFrameNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = opts && typeof opts.y === 'number' ? opts.y : viewportPos.y;

      const node = {
        id,
        type: 'extract_frame',
        title: '提取首帧',
        x,
        y,
        data: {
          videoFile: null,
          videoUrl: '',
          videoName: '',
          imageUrl: '',
          status: 'idle'  // idle, extracting, success, error
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';

      el.innerHTML = `
        <div class="port input" title="输入（连接视频节点）"></div>
        <div class="port output" title="输出（提取的首帧图片）"></div>
        <div class="node-header">
          <div class="node-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;">
              <rect x="4" y="6" width="16" height="12" rx="2"/>
              <path d="M10 9.5V14.5L14.5 12L10 9.5Z" fill="currentColor" />
              <rect x="6" y="2" width="6" height="4" rx="1" stroke="currentColor" stroke-width="2" />
            </svg>
            ${node.title}
          </div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field field-collapsible">
            <div class="label">视频</div>
            <input class="video-file" type="file" accept="video/*" />
          </div>
          <div class="field field-always-visible video-preview-field" style="display:none;">
            <div class="label">预览</div>
            <div class="video-preview">
              <video class="video-thumb" playsinline muted></video>
            </div>
            <div class="gen-meta video-name"></div>
          </div>
          <div class="field field-always-visible extract-actions-field">
            <button class="gen-btn" type="button" title="提取首帧">提取首帧</button>
          </div>
          <div class="field field-always-visible image-result-field" style="display:none;">
            <div class="label">提取结果</div>
            <div class="image-result">
              <img class="result-image" style="max-width: 100%; max-height: 150px; object-fit: contain; border-radius: 4px;" />
            </div>
            <div class="preview-row" style="margin-top: 8px;">
              <button class="mini-btn" type="button" title="下载">下载</button>
              <button class="mini-btn secondary clear-result-btn" type="button" title="清除">清除</button>
            </div>
          </div>
          <div class="field field-always-visible status-field" style="display:none;">
            <div class="gen-meta status"></div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const fileEl = el.querySelector('.video-file');
      const inputPort = el.querySelector('.port.input');
      const outputPort = el.querySelector('.port.output');
      const previewField = el.querySelector('.video-preview-field');
      const thumbVideo = el.querySelector('.video-thumb');
      const nameEl = el.querySelector('.video-name');
      const extractBtn = el.querySelector('.gen-btn');
      const resultField = el.querySelector('.image-result-field');
      const resultImage = el.querySelector('.result-image');
      const downloadBtn = el.querySelector('.preview-row button:first-of-type');
      const clearResultBtn = el.querySelector('.clear-result-btn');
      const statusField = el.querySelector('.status-field');
      const statusEl = el.querySelector('.status');

      // 删除按钮
      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });

      // 节点选择和拖拽
      el.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        setSelected(id);
        bringNodeToFront(id);
      });

      headerEl.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        bringNodeToFront(id);
        initNodeDrag(id, e.clientX, e.clientY);
      });

      // 输入端口 - 接收视频节点连接
      inputPort.addEventListener('mouseup', (e) => {
        if(state.connecting && state.connecting.fromId !== id){
          const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
          if(fromNode && fromNode.type === 'video'){
            const exists = state.connections.some(c => c.to === id);
            if(!exists){
              state.connections.push({
                id: state.nextConnId++,
                from: state.connecting.fromId,
                to: id
              });
              renderConnections();
              // 接收视频URL
              node.data.videoUrl = fromNode.data.url;
              node.data.videoName = fromNode.data.name || '视频';
              thumbVideo.src = proxyDownloadUrl(fromNode.data.url);
              previewField.style.display = '';
              nameEl.textContent = node.data.videoName;
              renderImageConnections();  // 更新图片连接
            }
          }
        }
        state.connecting = null;
      });

      // 输出端口
      outputPort.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
      });

      // 视频文件上传
      fileEl.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if(!file) return;

        if(!file.type.startsWith('video/')){
          showToast('请选择视频文件', 'error');
          return;
        }

        try {
          showToast('正在处理视频...', 'info');
          const dataUrl = await readFileAsDataUrl(file);
          node.data.videoFile = file;
          node.data.videoName = file.name;
          node.data.videoUrl = dataUrl;
          thumbVideo.src = dataUrl;
          previewField.style.display = '';
          nameEl.textContent = file.name;

          // 清除之前的提取结果
          clearResult();
          showToast('视频已加载，点击"提取首帧"按钮提取', 'success');

          // 自动保存工作流
          try{ autoSaveWorkflow(); } catch(e){}
        } catch(error){
          console.error('视频处理失败:', error);
          showToast('视频处理失败', 'error');
        }
      });

      // 提取首帧按钮
      extractBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await extractFirstFrame();
      });

      // 下载提取的图片
      downloadBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if(!node.data.imageUrl){
          showToast('没有可下载的图片', 'error');
          return;
        }
        window.open(node.data.imageUrl, '_blank');
      });

      // 清除结果
      clearResultBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        clearResult();
      });

      // 设置视频（从连接或上传）
      function setVideoFromUrl(url, name = ''){
        if(node.data.url){
          try{ URL.revokeObjectURL(node.data.url); } catch(e){}
        }
        node.data.videoUrl = url;
        node.data.videoName = name;
        thumbVideo.src = url ? proxyDownloadUrl(url) : '';
        previewField.style.display = url ? '' : 'none';
        nameEl.textContent = name;
      }

      function setVideoFromFile(file){
        node.data.videoFile = file;
        node.data.videoName = file ? file.name : '';
        node.data.videoUrl = file ? URL.createObjectURL(file) : '';
        if(node.data.videoUrl){
          thumbVideo.src = node.data.videoUrl;
        }
        previewField.style.display = file ? '' : 'none';
        nameEl.textContent = file ? file.name : '';
      }

      function clearResult(){
        node.data.imageUrl = '';
        node.data.status = 'idle';
        resultField.style.display = 'none';
        resultImage.src = '';
        statusField.style.display = 'none';
        extractBtn.disabled = false;
        extractBtn.textContent = '提取首帧';
      }

      async function extractFirstFrame(){
        // 检查是否有视频（来自上传或连接）
        const hasVideoFile = node.data.videoFile !== null;
        const hasVideoUrl = node.data.videoUrl && node.data.videoUrl.length > 0;

        if(!hasVideoFile && !hasVideoUrl){
          showToast('请先上传视频或连接视频节点', 'error');
          return;
        }

        // 如果是URL，需要上传到服务器
        let fileToExtract = null;
        if(node.data.videoFile){
          fileToExtract = node.data.videoFile;
        } else if(node.data.videoUrl){
          // 从连接的视频节点获取
          try {
            // 尝试从URL获取文件对象
            showToast('正在下载视频...', 'info');
            const response = await fetch(proxyDownloadUrl(node.data.videoUrl));
            const blob = await response.blob();
            fileToExtract = new File([blob], node.data.videoName || 'video.mp4', { type: 'video/mp4' });
          } catch(error){
            console.error('下载视频失败:', error);
            showToast('下载视频失败', 'error');
            return;
          }
        }

        if(!fileToExtract){
          showToast('没有可提取的视频', 'error');
          return;
        }

        // 显示处理状态
        node.data.status = 'extracting';
        statusField.style.display = '';
        statusEl.textContent = '正在提取首帧...';
        extractBtn.disabled = true;
        extractBtn.textContent = '提取中...';

        try {
          // 构建FormData
          const formData = new FormData();
          formData.append('file', fileToExtract);

          // 调用API提取首帧
          const response = await fetch('/api/video-workflow/extract-first-frame', {
            method: 'POST',
            headers: {
              'Authorization': localStorage.getItem('auth_token') || '',
              'X-User-Id': localStorage.getItem('user_id') || '1'
            },
            body: formData
          });

          const result = await response.json();

          if(result.code === 0 && result.data && result.data.url){
            // 提取成功
            node.data.imageUrl = result.data.url;
            node.data.status = 'success';
            resultField.style.display = '';
            resultImage.src = result.data.url;
            statusEl.textContent = '提取成功';
            statusEl.style.color = '#22c55e';

            // 1秒后隐藏状态
            setTimeout(() => {
              statusField.style.display = 'none';
            }, 2000);

            showToast('首帧提取成功', 'success');

            // 自动保存工作流
            try{ autoSaveWorkflow(); } catch(e){}
          } else {
            // 提取失败
            node.data.status = 'error';
            statusEl.textContent = result.message || '提取失败';
            statusEl.style.color = '#ef4444';
            showToast(result.message || '提取首帧失败', 'error');
          }
        } catch(error){
          console.error('提取首帧失败:', error);
          node.data.status = 'error';
          statusEl.textContent = '网络错误';
          statusEl.style.color = '#ef4444';
          showToast('提取首帧失败，请检查网络连接', 'error');
        } finally {
          extractBtn.disabled = false;
          extractBtn.textContent = '提取首帧';
        }
      }

      canvasEl.appendChild(el);
      setSelected(id);
      return id;
    }
