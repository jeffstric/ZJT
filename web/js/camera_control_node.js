/**
 * 相机控制节点模块
 *
 * 独立的相机控制节点，接收图片节点输入，
 * 使用 Qwen 多角度 API 生成新视角图片，输出为标准图片节点。
 */

// 根据相机参数生成提示词（与 ComfyUI-qwenmultiangle 插件逻辑一致）
function generateCameraPrompt(camera){
  if(!camera) return '<sks> 多角度视角变换';

  const hAngle = (camera.horizontal_angle || 0) % 360;

  // 水平角度 → 方向
  let hDirection;
  if(hAngle < 22.5 || hAngle >= 337.5){
    hDirection = 'front view';
  } else if(hAngle < 67.5){
    hDirection = 'front-right quarter view';
  } else if(hAngle < 112.5){
    hDirection = 'right side view';
  } else if(hAngle < 157.5){
    hDirection = 'back-right quarter view';
  } else if(hAngle < 202.5){
    hDirection = 'back view';
  } else if(hAngle < 247.5){
    hDirection = 'back-left quarter view';
  } else if(hAngle < 292.5){
    hDirection = 'left side view';
  } else {
    hDirection = 'front-left quarter view';
  }

  // 垂直角度 → 镜头类型
  const vAngle = camera.vertical_angle || 0;
  let vDirection;
  if(vAngle < -15){
    vDirection = 'low-angle shot';
  } else if(vAngle < 15){
    vDirection = 'eye-level shot';
  } else if(vAngle < 45){
    vDirection = 'elevated shot';
  } else {
    vDirection = 'high-angle shot';
  }

  // 缩放 → 距离
  const zoom = camera.zoom !== undefined ? camera.zoom : 5.0;
  let distance;
  if(zoom < 2){
    distance = 'wide shot';
  } else if(zoom < 6){
    distance = 'medium shot';
  } else {
    distance = 'close-up';
  }

  return `<sks> ${hDirection} ${vDirection} ${distance}`;
}

// 声明全局函数
function createCameraControlNode(opts){
  const id = state.nextNodeId++;
  const viewportPos = getViewportNodePosition();
  let x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
  let y = Math.max(MIN_NODE_Y, opts && typeof opts.y === 'number' ? opts.y : viewportPos.y);

  if(opts && opts.checkCollision){
    const avail = findNearestAvailablePosition(x, y, 320, 300);
    x = avail.x;
    y = Math.max(MIN_NODE_Y, avail.y);
  }

  const node = {
    id,
    type: 'camera_control',
    title: '相机控制',
    x,
    y,
    data: {
      camera: {
        horizontal_angle: 0,
        vertical_angle: 0,
        zoom: 5.0,
        modified: { horizontal_angle: false, vertical_angle: false, zoom: false }
      },
      drawCount: 1
    }
  };
  state.nodes.push(node);

  const el = document.createElement('div');
  el.className = 'node';
  el.dataset.nodeId = String(id);
  el.style.left = node.x + 'px';
  el.style.top = node.y + 'px';

  el.innerHTML = `
    <div class="port input" title="输入（连接图片节点）"></div>
    <div class="node-header">
      <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="4" y="4" width="16" height="16" rx="2"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></svg>${node.title}</div>
      <button class="icon-btn" title="删除">×</button>
    </div>
    <div class="node-body">
      <div class="field">
        <div class="label">源图片</div>
        <div class="camera-ctrl-source-thumb" style="display:none; margin-top:4px;">
          <img class="camera-ctrl-source-img" style="max-width:100%; max-height:120px; border-radius:4px; border:1px solid #e5e7eb;" />
        </div>
        <div class="camera-ctrl-source-placeholder muted" style="font-size:11px; margin-top:4px;">请连接图片节点</div>
      </div>
      <div class="field field-collapsible camera-control-section">
        <div class="label" style="margin-bottom: 4px;">相机控制</div>
        <div class="camera-ctrl-content" style="display: flex; flex-direction: column; gap: 12px; padding: 12px; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; margin-top: 4px;">
          <div class="camera-param-row" data-param="horizontal_angle">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <label style="font-size: 11px; font-weight: 600; color: #374151;">水平角度 (0~360°)</label>
              <div style="display: flex; align-items: center; gap: 6px;">
                <input type="number" class="camera-input camera-ctrl-horizontal-angle" value="0" min="0" max="360" step="1" style="width: 60px; padding: 4px 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 11px; text-align: center;" />
                <span style="font-size: 11px; color: #6b7280;">°</span>
                <button type="button" class="camera-reset-btn camera-ctrl-reset-horizontal-angle" style="padding: 4px 8px; font-size: 10px; border: 1px solid #d1d5db; border-radius: 4px; background: #fff; color: #6b7280; cursor: pointer;">重置</button>
              </div>
            </div>
            <input type="range" class="camera-slider camera-ctrl-horizontal-angle-slider" min="0" max="360" step="1" value="0" style="width: 100%;" />
            <div style="display: flex; justify-content: space-between; font-size: 10px; color: #9ca3af; margin-top: 2px;">
              <span>0° (正面)</span>
              <span>90°</span>
              <span>180° (背面)</span>
              <span>270°</span>
              <span>360°</span>
            </div>
          </div>
          <div class="camera-param-row" data-param="vertical_angle">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <label style="font-size: 11px; font-weight: 600; color: #374151;">垂直角度 (-30°~60°)</label>
              <div style="display: flex; align-items: center; gap: 6px;">
                <input type="number" class="camera-input camera-ctrl-vertical-angle" value="0" min="-30" max="60" step="1" style="width: 60px; padding: 4px 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 11px; text-align: center;" />
                <span style="font-size: 11px; color: #6b7280;">°</span>
                <button type="button" class="camera-reset-btn camera-ctrl-reset-vertical-angle" style="padding: 4px 8px; font-size: 10px; border: 1px solid #d1d5db; border-radius: 4px; background: #fff; color: #6b7280; cursor: pointer;">重置</button>
              </div>
            </div>
            <input type="range" class="camera-slider camera-ctrl-vertical-angle-slider" min="-30" max="60" step="1" value="0" style="width: 100%;" />
            <div style="display: flex; justify-content: space-between; font-size: 10px; color: #9ca3af; margin-top: 2px;">
              <span>-30° (仰视)</span>
              <span>0° (平视)</span>
              <span>+60° (俯视)</span>
            </div>
          </div>
          <div class="camera-param-row" data-param="zoom">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <label style="font-size: 11px; font-weight: 600; color: #374151;">缩放距离 (0~10)</label>
              <div style="display: flex; align-items: center; gap: 6px;">
                <input type="number" class="camera-input camera-ctrl-zoom" value="5.0" min="0" max="10" step="0.1" style="width: 60px; padding: 4px 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 11px; text-align: center;" />
                <button type="button" class="camera-reset-btn camera-ctrl-reset-zoom" style="padding: 4px 8px; font-size: 10px; border: 1px solid #d1d5db; border-radius: 4px; background: #fff; color: #6b7280; cursor: pointer;">重置</button>
              </div>
            </div>
            <input type="range" class="camera-slider camera-ctrl-zoom-slider" min="0" max="10" step="0.1" value="5.0" style="width: 100%;" />
            <div style="display: flex; justify-content: space-between; font-size: 10px; color: #9ca3af; margin-top: 2px;">
              <span>0 (远景)</span>
              <span>5 (中景)</span>
              <span>10 (特写)</span>
            </div>
          </div>
          <div style="margin-top: 8px;">
            <label style="display: block; font-size: 11px; font-weight: 600; color: #374151; margin-bottom: 6px;">3D 预览</label>
            <canvas class="camera-preview-canvas camera-ctrl-canvas" width="200" height="150" style="width: 100%; max-width: 200px; height: 150px; border: 1px solid #e5e7eb; border-radius: 4px; background: #ffffff;"></canvas>
          </div>
        </div>
      </div>
      <div class="field">
        <div class="btn-row" style="display: flex; gap: 8px;">
          <div class="gen-container">
            <button class="gen-btn gen-btn-main camera-ctrl-generate-btn" type="button">生成图片</button>
            <button class="gen-btn gen-btn-caret camera-ctrl-generate-caret" type="button" aria-label="选择抽卡次数">▾</button>
            <div class="gen-menu camera-ctrl-gen-menu">
              <div class="gen-item" data-count="1">X1</div>
              <div class="gen-item" data-count="2">X2</div>
              <div class="gen-item" data-count="3">X3</div>
            </div>
          </div>
        </div>
        <div class="gen-meta camera-ctrl-draw-count-label"></div>
        <div class="muted camera-ctrl-status" style="display:none;"></div>
      </div>
    </div>
  `;

  const headerEl = el.querySelector('.node-header');
  const deleteBtn = el.querySelector('.icon-btn');
  const inputPort = el.querySelector('.port.input');

  const sourceThumb = el.querySelector('.camera-ctrl-source-thumb');
  const sourceImg = el.querySelector('.camera-ctrl-source-img');
  const sourcePlaceholder = el.querySelector('.camera-ctrl-source-placeholder');
  const statusEl = el.querySelector('.camera-ctrl-status');
  const generateBtn = el.querySelector('.camera-ctrl-generate-btn');
  const genCaret = el.querySelector('.camera-ctrl-generate-caret');
  const genMenu = el.querySelector('.camera-ctrl-gen-menu');
  const drawCountLabel = el.querySelector('.camera-ctrl-draw-count-label');

  // Camera control elements
  const cameraContent = el.querySelector('.camera-ctrl-content');
  const hSlider = el.querySelector('.camera-ctrl-horizontal-angle-slider');
  const hInput = el.querySelector('.camera-ctrl-horizontal-angle');
  const hReset = el.querySelector('.camera-ctrl-reset-horizontal-angle');
  const vSlider = el.querySelector('.camera-ctrl-vertical-angle-slider');
  const vInput = el.querySelector('.camera-ctrl-vertical-angle');
  const vReset = el.querySelector('.camera-ctrl-reset-vertical-angle');
  const zSlider = el.querySelector('.camera-ctrl-zoom-slider');
  const zInput = el.querySelector('.camera-ctrl-zoom');
  const zReset = el.querySelector('.camera-ctrl-reset-zoom');
  const cameraCanvas = el.querySelector('.camera-ctrl-canvas');

  // ========== 删除 ==========
  deleteBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    removeNode(id);
  });

  // ========== 选中/拖拽 ==========
  el.addEventListener('mousedown', (e) => {
    if(e.target.classList.contains('port')) return;
    e.stopPropagation();
    setSelected(id);
    bringNodeToFront(id);
    setTimeout(() => updateCameraPreview(), 50);
  });

  headerEl.addEventListener('mousedown', (e) => {
    if(e.target.classList.contains('port')) return;
    e.preventDefault();
    e.stopPropagation();
    setSelected(id);
    bringNodeToFront(id);
    setTimeout(() => updateCameraPreview(), 50);
    initNodeDrag(id, e.clientX, e.clientY);
  });

  // ========== 输入端口：只接受图片节点连接 ==========
  inputPort.addEventListener('mouseup', (e) => {
    if(state.connecting && state.connecting.fromId !== id){
      const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
      if(fromNode && fromNode.type === 'image'){
        const exists = state.connections.some(c => c.from === state.connecting.fromId && c.to === id);
        if(!exists){
          state.connections.push({
            id: state.nextConnId++,
            from: state.connecting.fromId,
            to: id
          });
          renderConnections();
          renderImageConnections();
          renderFirstFrameConnections();
          renderMinimap();
          updateSourceThumbnail();
          try{ autoSaveWorkflow(); } catch(err){}
        }
      } else {
        showToast('相机控制节点只能接收图片节点', 'warning');
      }
    }
  });

  // ========== 更新源图缩略图 ==========
  function updateSourceThumbnail(){
    const conn = state.connections.find(c => c.to === id);
    if(!conn){
      sourceThumb.style.display = 'none';
      sourcePlaceholder.style.display = 'block';
      sourcePlaceholder.textContent = '请连接图片节点';
      return;
    }
    const sourceNode = state.nodes.find(n => n.id === conn.from);
    if(!sourceNode || sourceNode.type !== 'image' || (!sourceNode.data.url && !sourceNode.data.preview)){
      sourceThumb.style.display = 'none';
      sourcePlaceholder.style.display = 'block';
      sourcePlaceholder.textContent = '源图片节点没有图片';
      return;
    }
    const url = sourceNode.data.url || sourceNode.data.preview;
    sourceImg.src = proxyImageUrl(url);
    sourceThumb.style.display = 'block';
    sourcePlaceholder.style.display = 'none';
  }

  // Initial check
  updateSourceThumbnail();

  // ========== 相机参数 3D 预览 ==========
  function updateCameraPreview(){
    if(cameraCanvas && typeof window.updateCameraPreview === 'function'){
      window.updateCameraPreview(cameraCanvas, node.data.camera);
    }
  }

  // ========== 水平角度 ==========
  if(hSlider){
    hSlider.addEventListener('input', (e) => {
      const value = parseFloat(e.target.value);
      ensureCameraData();
      node.data.camera.horizontal_angle = value;
      node.data.camera.modified.horizontal_angle = true;
      if(hInput) hInput.value = value;
      updateCameraPreview();
    });
  }
  if(hInput){
    hInput.addEventListener('input', (e) => {
      const value = parseFloat(e.target.value);
      ensureCameraData();
      node.data.camera.horizontal_angle = value;
      node.data.camera.modified.horizontal_angle = true;
      if(hSlider) hSlider.value = value;
      updateCameraPreview();
    });
  }
  if(hReset){
    hReset.addEventListener('click', (e) => {
      e.stopPropagation();
      ensureCameraData();
      node.data.camera.horizontal_angle = 0;
      node.data.camera.modified.horizontal_angle = false;
      if(hSlider) hSlider.value = 0;
      if(hInput) hInput.value = 0;
      updateCameraPreview();
    });
  }

  // ========== 垂直角度 ==========
  if(vSlider){
    vSlider.addEventListener('input', (e) => {
      const value = parseFloat(e.target.value);
      ensureCameraData();
      node.data.camera.vertical_angle = value;
      node.data.camera.modified.vertical_angle = true;
      if(vInput) vInput.value = value;
      updateCameraPreview();
    });
  }
  if(vInput){
    vInput.addEventListener('input', (e) => {
      const value = parseFloat(e.target.value);
      ensureCameraData();
      node.data.camera.vertical_angle = value;
      node.data.camera.modified.vertical_angle = true;
      if(vSlider) vSlider.value = value;
      updateCameraPreview();
    });
  }
  if(vReset){
    vReset.addEventListener('click', (e) => {
      e.stopPropagation();
      ensureCameraData();
      node.data.camera.vertical_angle = 0;
      node.data.camera.modified.vertical_angle = false;
      if(vSlider) vSlider.value = 0;
      if(vInput) vInput.value = 0;
      updateCameraPreview();
    });
  }

  // ========== 缩放 ==========
  if(zSlider){
    zSlider.addEventListener('input', (e) => {
      const value = parseFloat(e.target.value);
      ensureCameraData();
      node.data.camera.zoom = value;
      node.data.camera.modified.zoom = true;
      if(zInput) zInput.value = value;
      updateCameraPreview();
    });
  }
  if(zInput){
    zInput.addEventListener('input', (e) => {
      const value = parseFloat(e.target.value);
      ensureCameraData();
      node.data.camera.zoom = value;
      node.data.camera.modified.zoom = true;
      if(zSlider) zSlider.value = value;
      updateCameraPreview();
    });
  }
  if(zReset){
    zReset.addEventListener('click', (e) => {
      e.stopPropagation();
      ensureCameraData();
      node.data.camera.zoom = 5.0;
      node.data.camera.modified.zoom = false;
      if(zSlider) zSlider.value = 5.0;
      if(zInput) zInput.value = 5.0;
      updateCameraPreview();
    });
  }

  // 确保 camera 数据结构完整
  function ensureCameraData(){
    if(!node.data.camera){
      node.data.camera = { horizontal_angle: 0, vertical_angle: 0, zoom: 5.0, modified: { horizontal_angle: false, vertical_angle: false, zoom: false } };
    }
    if(!node.data.camera.modified){
      node.data.camera.modified = { horizontal_angle: false, vertical_angle: false, zoom: false };
    }
  }

  // ========== 抽卡次数 ==========
  function updateDrawCountLabel(){
    drawCountLabel.textContent = `抽卡次数：X${node.data.drawCount}`;
  }
  updateDrawCountLabel();

  if(genCaret){
    genCaret.addEventListener('click', (e) => {
      e.stopPropagation();
      genMenu.classList.toggle('show');
    });
  }

  const genItems = genMenu.querySelectorAll('.gen-item');
  for(const item of genItems){
    item.addEventListener('click', (e) => {
      e.stopPropagation();
      const count = Number(item.dataset.count || '1');
      node.data.drawCount = count;
      updateDrawCountLabel();
      genMenu.classList.remove('show');
    });
  }

  // ========== 生成图片 ==========
  // 检测 runninghub 配置状态，禁用/启用生成图片按钮
  if(window.TaskConfig) {
    const isConfigured = window.TaskConfig.isRunningHubConfigured();
    if(!isConfigured) {
      generateBtn.disabled = true;
      generateBtn.title = '该功能依赖runninghub接口，请配置密钥';
      generateBtn.textContent = '生成图片(未配置)';
      statusEl.style.display = 'block';
      statusEl.style.color = '#ef4444';
      statusEl.textContent = '该功能依赖runninghub接口，请配置密钥';
    }
  }

  generateBtn.addEventListener('click', async (e) => {
    e.stopPropagation();

    // 0. 检查 runninghub 配置
    if(window.TaskConfig && !window.TaskConfig.isRunningHubConfigured()) {
      showToast('该功能依赖runninghub接口，请配置密钥', 'error');
      return;
    }

    // 1. 验证源图片
    const conn = state.connections.find(c => c.to === id);
    if(!conn){
      showToast('请先连接图片节点', 'warning');
      return;
    }
    const sourceNode = state.nodes.find(n => n.id === conn.from);
    if(!sourceNode || sourceNode.type !== 'image'){
      showToast('请连接图片节点', 'warning');
      return;
    }
    const sourceImageUrl = sourceNode.data.url;
    if(!sourceImageUrl){
      showToast('源图片节点没有图片', 'warning');
      return;
    }

    // 2. 检查相机参数是否修改
    const hasModifications = node.data.camera && node.data.camera.modified &&
      (node.data.camera.modified.horizontal_angle || node.data.camera.modified.vertical_angle || node.data.camera.modified.zoom);
    if(!hasModifications){
      showToast('请先调整相机参数', 'warning');
      return;
    }

    // 3. 获取多角度 task_id 和算力
    const multiAngleTaskId = window.TaskConfig && window.TaskConfig.getTaskIdByKey('qwen-multi-angle', 'image_edit');
    if(!multiAngleTaskId){
      showToast('未找到多角度任务配置', 'error');
      return;
    }

    const computingPower = 4; // QWEN_MULTI_ANGLE_IMAGE = 4
    const totalPower = computingPower * (node.data.drawCount || 1);

    // 4. 确认算力
    const userId = localStorage.getItem('user_id');
    const authToken = localStorage.getItem('auth_token') || '';
    const canvasRatio = state.ratio || ratioSelectEl.value || '16:9';

    if(userId){
      try {
        const headers = { 'Authorization': `Bearer ${authToken}` };
        const checkRes = await fetch('/api/user/computing_power', { headers });
        const checkData = await checkRes.json();
        if(checkData.success && checkData.data){
          const userPower = checkData.data.computing_power ?? 0;
          if(userPower < totalPower){
            showToast(`算力不足（需要 ${totalPower}，当前 ${userPower}）`, 'error');
            return;
          }
        }
      } catch(err){
        console.warn('检查算力失败:', err);
      }
    }

    // 5. 提交任务
    generateBtn.disabled = true;
    generateBtn.textContent = '生成中...';
    statusEl.style.display = 'block';
    statusEl.style.color = '#666';
    statusEl.textContent = `正在提交任务（${node.data.drawCount}张，预计消耗 ${totalPower} 算力）...`;

    try {
      const cameraParams = convertCameraToQwenMultiAngleParams(node.data.camera);

      const form = new FormData();
      form.append('task_id', multiAngleTaskId);
      form.append('ref_image_urls', sourceImageUrl);
      form.append('prompt', generateCameraPrompt(node.data.camera));
      form.append('extra_config', JSON.stringify(cameraParams));
      form.append('count', node.data.drawCount || 1);
      form.append('ratio', canvasRatio);
      if(userId) form.append('user_id', userId);
      if(authToken) form.append('auth_token', authToken);

      const res = await fetch('/api/image-edit', {
        method: 'POST',
        body: form
      });

      if(!res.ok){
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      if(!data.project_ids || data.project_ids.length === 0){
        throw new Error(data.detail || data.message || '提交任务失败');
      }

      showToast('任务已提交，正在生成图片...', 'info');
      statusEl.textContent = '任务已提交，等待结果...';

      // 6. 创建图片节点
      const createdImageNodeIds = [];
      const projectIds = data.project_ids;

      for(let i = 0; i < projectIds.length; i++){
        const offsetY = i * 280;
        const newNodeId = createImageNode({
          x: node.x + 380,
          y: node.y + offsetY,
          checkCollision: true
        });

        const newNode = state.nodes.find(n => n.id === newNodeId);
        if(newNode){
          newNode.data.name = projectIds.length > 1 ? `相机图${i + 1}` : '相机图';
          newNode.data.project_id = projectIds[i] || projectIds[0];
          newNode.title = newNode.data.name;

          const newEl = canvasEl.querySelector(`.node[data-node-id="${newNodeId}"]`);
          if(newEl){
            const titleEl = newEl.querySelector('.node-title');
            if(titleEl) titleEl.textContent = newNode.title;
          }

          // 连接: camera_control → 新图片节点
          state.connections.push({
            id: state.nextConnId++,
            from: id,
            to: newNodeId
          });

          createdImageNodeIds.push(newNodeId);
        }
      }

      renderConnections();
      renderImageConnections();
      renderFirstFrameConnections();
      renderMinimap();

      // 7. 轮询结果
      pollVideoStatus(
        projectIds,
        (progressText) => {
          generateBtn.textContent = progressText;
          statusEl.textContent = progressText;
        },
        (statusResult) => {
          // 提取结果 URL
          let imageUrls = [];
          if(statusResult.tasks && Array.isArray(statusResult.tasks)){
            imageUrls = statusResult.tasks
              .filter(task => task.status === 'SUCCESS' && task.result)
              .map(task => normalizeVideoUrl(task.result))
              .filter(Boolean);
          } else {
            const rawResults = extractResultsArray(statusResult);
            imageUrls = Array.isArray(rawResults)
              ? rawResults.map(normalizeVideoUrl).filter(Boolean)
              : [];
          }

          if(imageUrls.length === 0){
            showToast('生成成功，但未获取到图片地址', 'error');
            generateBtn.disabled = false;
            generateBtn.textContent = '生成图片';
            statusEl.textContent = '生成完成（未获取图片）';
            return;
          }

          // 更新图片节点
          imageUrls.forEach((imageUrl, index) => {
            if(index >= createdImageNodeIds.length) return;
            const imageNodeId = createdImageNodeIds[index];
            const imageNode = state.nodes.find(n => n.id === imageNodeId);

            if(imageNode){
              const normalizedUrl = normalizeImageUrl(imageUrl);
              imageNode.data.url = normalizedUrl;
              imageNode.data.preview = normalizedUrl;

              const imageNodeEl = canvasEl.querySelector(`.node[data-node-id="${imageNodeId}"]`);
              if(imageNodeEl){
                const previewImg = imageNodeEl.querySelector('.image-preview');
                const previewRow = imageNodeEl.querySelector('.image-preview-row');
                if(previewImg && previewRow){
                  previewImg.src = proxyImageUrl(imageUrl);
                  previewRow.style.display = 'flex';
                }
              }
            }
          });

          renderConnections();
          renderImageConnections();

          generateBtn.disabled = false;
          generateBtn.textContent = '生成图片';
          statusEl.style.color = '#22c55e';
          statusEl.textContent = `生成成功！已创建 ${imageUrls.length} 个图片节点`;
          showToast(`相机控制生成成功！已创建 ${imageUrls.length} 个图片节点`, 'success');

          try{ autoSaveWorkflow(); } catch(err){}
        },
        (error) => {
          showToast(`生成失败: ${error}`, 'error');
          generateBtn.disabled = false;
          generateBtn.textContent = '生成图片';
          statusEl.style.color = '#dc2626';
          statusEl.textContent = `生成失败: ${error}`;
        }
      );

    } catch(error){
      console.error('相机控制生成失败:', error);
      showToast(`生成失败: ${error.message || error}`, 'error');
      generateBtn.disabled = false;
      generateBtn.textContent = '生成图片';
      statusEl.style.color = '#dc2626';
      statusEl.textContent = `生成失败: ${error.message || error}`;
    }
  });

  // ========== 调试按钮 ==========
  addDebugButtonToNode(el, node);

  canvasEl.appendChild(el);
  setSelected(id);

  // 初始化 3D 预览
  setTimeout(() => updateCameraPreview(), 100);

  return id;
}
