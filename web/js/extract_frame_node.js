    // ============ 提取帧节点 ============

    function createExtractFrameNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = Math.max(MIN_NODE_Y, opts && typeof opts.y === 'number' ? opts.y : viewportPos.y);

      const node = {
        id,
        type: 'extract_frame',
        title: '提取帧',
        x,
        y,
        data: {
          videoFile: null,
          videoUrl: '',
          videoName: '',
          frameType: 'first',  // first=首帧, last=尾帧
          extractedImageNodeId: null,  // 提取成功后创建的图片节点ID
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
        <div class="port output" title="输出（提取的帧图片）"></div>
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
          <div class="field field-always-visible frame-type-field">
            <div class="label">帧类型</div>
            <select class="frame-type-select">
              <option value="first">首帧</option>
              <option value="last">尾帧</option>
            </select>
          </div>
          <div class="field field-always-visible extract-actions-field">
            <button class="gen-btn" type="button" title="提取帧">提取帧</button>
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
      const frameTypeSelect = el.querySelector('.frame-type-select');
      const extractBtn = el.querySelector('.gen-btn');
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
              if(node.data.videoUrl){
                thumbVideo.src = proxyDownloadUrl(node.data.videoUrl);
                previewField.style.display = '';
                nameEl.textContent = node.data.videoName;
              }
              try{ autoSaveWorkflow(); } catch(e){}
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
          showToast('视频已加载，点击"提取帧"按钮提取', 'success');

          // 自动保存工作流
          try{ autoSaveWorkflow(); } catch(e){}
        } catch(error){
          console.error('视频处理失败:', error);
          showToast('视频处理失败', 'error');
        }
      });

      // 帧类型选择
      frameTypeSelect.addEventListener('change', (e) => {
        node.data.frameType = e.target.value;
        try{ autoSaveWorkflow(); } catch(e){}
      });

      // 提取帧按钮
      extractBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await extractFrame();
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
        node.data.extractedImageNodeId = null;
        node.data.status = 'idle';
        statusField.style.display = 'none';
        extractBtn.disabled = false;
        extractBtn.textContent = '提取帧';
      }

      async function extractFrame(){
        // 检查是否有视频（来自上传或连接）
        const hasVideoFile = node.data.videoFile !== null;
        const hasVideoUrl = node.data.videoUrl && node.data.videoUrl.length > 0;

        if(!hasVideoFile && !hasVideoUrl){
          showToast('请先上传视频或连接视频节点', 'error');
          return;
        }

        const frameType = node.data.frameType || 'first';
        const frameTypeName = frameType === 'last' ? '尾帧' : '首帧';

        // 显示处理状态
        node.data.status = 'extracting';
        statusField.style.display = '';
        statusEl.textContent = `正在提取${frameTypeName}...`;
        extractBtn.disabled = true;
        extractBtn.textContent = '提取中...';

        try {
          // 构建FormData
          const formData = new FormData();

          // 判断视频来源：如果有URL且是服务器URL，直接传URL；否则上传文件
          const isServerUrl = node.data.videoUrl && (node.data.videoUrl.startsWith('/upload/') || node.data.videoUrl.includes('/upload/'));

          if(hasVideoFile && !isServerUrl){
            // 本地上传的文件
            formData.append('file', node.data.videoFile);
          } else if(node.data.videoUrl){
            // 服务器上的视频URL
            formData.append('video_url', node.data.videoUrl);
          } else {
            showToast('没有可提取的视频', 'error');
            extractBtn.disabled = false;
            extractBtn.textContent = '提取帧';
            return;
          }

          formData.append('frame_type', frameType);

          // 调用API提取帧
          const response = await fetch('/api/video-workflow/extract-frame', {
            method: 'POST',
            headers: {
              'Authorization': localStorage.getItem('auth_token') || '',
              'X-User-Id': localStorage.getItem('user_id') || '1'
            },
            body: formData
          });

          const result = await response.json();

          if(result.code === 0 && result.data && result.data.url){
            // 提取成功 - 创建新的图片节点
            const imageUrl = result.data.url;
            node.data.status = 'success';
            statusEl.textContent = '提取成功，正在创建图片节点...';
            statusEl.style.color = '#22c55e';

            // 创建新的图片节点
            const imageNodeId = createImageNode({
              x: node.x + 280,
              y: node.y,
              checkCollision: true
            });
            const imageNode = state.nodes.find(n => n.id === imageNodeId);
            if(imageNode){
              // 设置图片节点的数据
              imageNode.data.url = imageUrl;
              imageNode.data.preview = imageUrl;
              imageNode.data.name = node.data.videoName ? node.data.videoName.replace(/\.[^.]+$/, `_${frameTypeName}.png`) : `${frameTypeName}.png`;

              // 更新图片节点的预览显示
              const imageNodeEl = canvasEl.querySelector(`.node[data-node-id="${imageNodeId}"]`);
              if(imageNodeEl){
                const previewRow = imageNodeEl.querySelector('.image-preview-row');
                const previewImg = imageNodeEl.querySelector('.image-preview');
                if(previewRow && previewImg){
                  previewRow.style.display = 'flex';
                  previewImg.src = imageUrl;
                }
              }

              // 创建图片连接（从提取帧节点到图片节点）
              state.imageConnections.push({
                id: state.nextImgConnId++,
                from: id,
                to: imageNodeId,
                portType: 'extracted'
              });

              // 记录创建的图片节点ID
              node.data.extractedImageNodeId = imageNodeId;

              // 渲染连接线（使用 requestAnimationFrame 确保 DOM 已更新）
              requestAnimationFrame(() => {
                renderImageConnections();
              });
            }

            // 隐藏状态
            setTimeout(() => {
              statusField.style.display = 'none';
            }, 2000);

            showToast(`${frameTypeName}提取成功，已创建图片节点`, 'success');
            renderMinimap();

            // 自动保存工作流
            try{ autoSaveWorkflow(); } catch(e){}
          } else {
            // 提取失败
            node.data.status = 'error';
            statusEl.textContent = result.message || '提取失败';
            statusEl.style.color = '#ef4444';
            showToast(result.message || `提取${frameTypeName}失败`, 'error');
          }
        } catch(error){
          console.error('提取帧失败:', error);
          node.data.status = 'error';
          statusEl.textContent = '网络错误';
          statusEl.style.color = '#ef4444';
          showToast(`提取${frameTypeName}失败，请检查网络连接`, 'error');
        } finally {
          extractBtn.disabled = false;
          extractBtn.textContent = '提取帧';
        }
      }

      canvasEl.appendChild(el);
      setSelected(id);
      return id;
    }

    // 带数据创建提取帧节点（用于恢复工作流）
    function createExtractFrameNodeWithData(nodeData){
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;

      createExtractFrameNode({ x: nodeData.x, y: nodeData.y });

      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);

      const node = state.nodes.find(n => n.id === nodeData.id);
      if(node && nodeData.data){
        // 恢复节点数据
        node.data.videoUrl = nodeData.data.videoUrl || '';
        node.data.videoName = nodeData.data.videoName || '';
        node.data.frameType = nodeData.data.frameType || 'first';
        node.data.extractedImageNodeId = nodeData.data.extractedImageNodeId || null;
        node.data.status = nodeData.data.status || 'idle';

        // 更新UI显示
        const nodeEl = canvasEl.querySelector(`.node[data-node-id="${nodeData.id}"]`);
        if(nodeEl){
          const previewField = nodeEl.querySelector('.video-preview-field');
          const thumbVideo = nodeEl.querySelector('.video-thumb');
          const nameEl = nodeEl.querySelector('.video-name');

          if(node.data.videoUrl){
            thumbVideo.src = proxyDownloadUrl(node.data.videoUrl);
            previewField.style.display = '';
            nameEl.textContent = node.data.videoName;
          }

          // 恢复帧类型选择
          if(nodeData.data.frameType){
            const frameTypeSelect = nodeEl.querySelector('.frame-type-select');
            if(frameTypeSelect){
              frameTypeSelect.value = nodeData.data.frameType;
            }
          }
        }
      }
    }
