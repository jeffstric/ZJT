// ============================
// camera_control_node.js - 相机控制节点
// 使用 createNodeBase 基类工厂
// ============================

(function() {

  // 根据相机参数生成提示词（与 ComfyUI-qwenmultiangle 插件逻辑一致）
  function generateCameraPrompt(camera) {
    if (!camera) return '<sks> 多角度视角变换';

    var hAngle = (camera.horizontal_angle || 0) % 360;

    // 水平角度 → 方向
    var hDirection;
    if (hAngle < 22.5 || hAngle >= 337.5) {
      hDirection = 'front view';
    } else if (hAngle < 67.5) {
      hDirection = 'front-right quarter view';
    } else if (hAngle < 112.5) {
      hDirection = 'right side view';
    } else if (hAngle < 157.5) {
      hDirection = 'back-right quarter view';
    } else if (hAngle < 202.5) {
      hDirection = 'back view';
    } else if (hAngle < 247.5) {
      hDirection = 'back-left quarter view';
    } else if (hAngle < 292.5) {
      hDirection = 'left side view';
    } else {
      hDirection = 'front-left quarter view';
    }

    // 垂直角度 → 镜头类型
    var vAngle = camera.vertical_angle || 0;
    var vDirection;
    if (vAngle < -15) {
      vDirection = 'low-angle shot';
    } else if (vAngle < 15) {
      vDirection = 'eye-level shot';
    } else if (vAngle < 45) {
      vDirection = 'elevated shot';
    } else {
      vDirection = 'high-angle shot';
    }

    // 缩放 → 距离
    var zoom = camera.zoom !== undefined ? camera.zoom : 5.0;
    var distance;
    if (zoom < 2) {
      distance = 'wide shot';
    } else if (zoom < 6) {
      distance = 'medium shot';
    } else {
      distance = 'close-up';
    }

    return '<sks> ' + hDirection + ' ' + vDirection + ' ' + distance;
  }

  // 导出到全局供其他模块使用
  window.generateCameraPrompt = generateCameraPrompt;

  var CAMERA_CONTROL_PORTS = [
    { direction: 'input', titleI18nKey: 'camera_input_port_title', acceptType: 'image', connectionType: 'connections' }
  ];

  function createCameraControlNode(opts) {
    return createNodeBase({
      type: 'camera_control',
      title: function() { return window.t ? window.t('camera_control_title') : '相机控制'; },
      defaultData: {
        camera: {
          horizontal_angle: 0,
          vertical_angle: 0,
          zoom: 5.0,
          modified: { horizontal_angle: false, vertical_angle: false, zoom: false }
        },
        drawCount: 1
      },
      ports: CAMERA_CONTROL_PORTS,
      width: 320,
      height: 300,
      titleIcon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="4" y="4" width="16" height="16" rx="2"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></svg>',
      bodyHtml: function() {
        return '<div class="field">' +
          '<div class="label" data-i18n="camera_source_label">' + (window.t ? window.t('camera_source_label') : '源图片') + '</div>' +
          '<div class="camera-ctrl-source-thumb" style="display:none; margin-top:4px;">' +
            '<img class="camera-ctrl-source-img" style="max-width:100%; max-height:120px; border-radius:4px; border:1px solid #e5e7eb;" />' +
          '</div>' +
          '<div class="camera-ctrl-source-placeholder muted" style="font-size:11px; margin-top:4px;" data-i18n="camera_source_connect">' + (window.t ? window.t('camera_source_connect') : '请连接图片节点') + '</div>' +
        '</div>' +
        '<div class="field field-collapsible camera-control-section">' +
          '<div class="label" style="margin-bottom: 4px;" data-i18n="camera_control_label">' + (window.t ? window.t('camera_control_label') : '相机控制') + '</div>' +
          '<div class="camera-ctrl-content" style="display: flex; flex-direction: column; gap: 12px; padding: 12px; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; margin-top: 4px;">' +
            '<div class="camera-param-row" data-param="horizontal_angle">' +
              '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">' +
                '<label style="font-size: 11px; font-weight: 600; color: #374151;" data-i18n="camera_h_angle_label">' + (window.t ? window.t('camera_h_angle_label') : '水平角度 (0~360°)') + '</label>' +
                '<div style="display: flex; align-items: center; gap: 6px;">' +
                  '<input type="number" class="camera-input camera-ctrl-horizontal-angle" value="0" min="0" max="360" step="1" style="width: 60px; padding: 4px 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 11px; text-align: center;" />' +
                  '<span style="font-size: 11px; color: #6b7280;">°</span>' +
                  '<button type="button" class="camera-reset-btn camera-ctrl-reset-horizontal-angle" style="padding: 4px 8px; font-size: 10px; border: 1px solid #d1d5db; border-radius: 4px; background: #fff; color: #6b7280; cursor: pointer;" data-i18n="camera_h_angle_reset">' + (window.t ? window.t('camera_h_angle_reset') : '重置') + '</button>' +
                '</div>' +
              '</div>' +
              '<input type="range" class="camera-slider camera-ctrl-horizontal-angle-slider" min="0" max="360" step="1" value="0" style="width: 100%;" />' +
              '<div style="display: flex; justify-content: space-between; font-size: 10px; color: #9ca3af; margin-top: 2px;">' +
                '<span data-i18n="camera_h_angle_front">0° (' + (window.t ? window.t('camera_h_angle_front_val') : '正面') + ')</span>' +
                '<span data-i18n="camera_h_angle_90">90°</span>' +
                '<span data-i18n="camera_h_angle_back">180° (' + (window.t ? window.t('camera_h_angle_back_val') : '背面') + ')</span>' +
                '<span data-i18n="camera_h_angle_270">270°</span>' +
                '<span data-i18n="camera_h_angle_360">360°</span>' +
              '</div>' +
            '</div>' +
            '<div class="camera-param-row" data-param="vertical_angle">' +
              '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">' +
                '<label style="font-size: 11px; font-weight: 600; color: #374151;" data-i18n="camera_v_angle_label">' + (window.t ? window.t('camera_v_angle_label') : '垂直角度 (-30°~60°)') + '</label>' +
                '<div style="display: flex; align-items: center; gap: 6px;">' +
                  '<input type="number" class="camera-input camera-ctrl-vertical-angle" value="0" min="-30" max="60" step="1" style="width: 60px; padding: 4px 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 11px; text-align: center;" />' +
                  '<span style="font-size: 11px; color: #6b7280;">°</span>' +
                  '<button type="button" class="camera-reset-btn camera-ctrl-reset-vertical-angle" style="padding: 4px 8px; font-size: 10px; border: 1px solid #d1d5db; border-radius: 4px; background: #fff; color: #6b7280; cursor: pointer;" data-i18n="camera_h_angle_reset">' + (window.t ? window.t('camera_h_angle_reset') : '重置') + '</button>' +
                '</div>' +
              '</div>' +
              '<input type="range" class="camera-slider camera-ctrl-vertical-angle-slider" min="-30" max="60" step="1" value="0" style="width: 100%;" />' +
              '<div style="display: flex; justify-content: space-between; font-size: 10px; color: #9ca3af; margin-top: 2px;">' +
                '<span data-i18n="camera_v_angle_low">-30° (' + (window.t ? window.t('camera_v_angle_low_val') : '仰视') + ')</span>' +
                '<span data-i18n="camera_v_angle_eye">0° (' + (window.t ? window.t('camera_v_angle_eye_val') : '平视') + ')</span>' +
                '<span data-i18n="camera_v_angle_high">+60° (' + (window.t ? window.t('camera_v_angle_high_val') : '俯视') + ')</span>' +
              '</div>' +
            '</div>' +
            '<div class="camera-param-row" data-param="zoom">' +
              '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">' +
                '<label style="font-size: 11px; font-weight: 600; color: #374151;" data-i18n="camera_zoom_label">' + (window.t ? window.t('camera_zoom_label') : '缩放距离 (0~10)') + '</label>' +
                '<div style="display: flex; align-items: center; gap: 6px;">' +
                  '<input type="number" class="camera-input camera-ctrl-zoom" value="5.0" min="0" max="10" step="0.1" style="width: 60px; padding: 4px 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 11px; text-align: center;" />' +
                  '<button type="button" class="camera-reset-btn camera-ctrl-reset-zoom" style="padding: 4px 8px; font-size: 10px; border: 1px solid #d1d5db; border-radius: 4px; background: #fff; color: #6b7280; cursor: pointer;" data-i18n="camera_h_angle_reset">' + (window.t ? window.t('camera_h_angle_reset') : '重置') + '</button>' +
                '</div>' +
              '</div>' +
              '<input type="range" class="camera-slider camera-ctrl-zoom-slider" min="0" max="10" step="0.1" value="5.0" style="width: 100%;" />' +
              '<div style="display: flex; justify-content: space-between; font-size: 10px; color: #9ca3af; margin-top: 2px;">' +
                '<span data-i18n="camera_zoom_wide">0 (' + (window.t ? window.t('camera_zoom_wide_val') : '远景') + ')</span>' +
                '<span data-i18n="camera_zoom_medium">5 (' + (window.t ? window.t('camera_zoom_medium_val') : '中景') + ')</span>' +
                '<span data-i18n="camera_zoom_close">10 (' + (window.t ? window.t('camera_zoom_close_val') : '特写') + ')</span>' +
              '</div>' +
            '</div>' +
            '<div style="margin-top: 8px;">' +
              '<label style="display: block; font-size: 11px; font-weight: 600; color: #374151; margin-bottom: 6px;" data-i18n="camera_preview_label">' + (window.t ? window.t('camera_preview_label') : '3D 预览') + '</label>' +
              '<canvas class="camera-preview-canvas camera-ctrl-canvas" width="200" height="150" style="width: 100%; max-width: 200px; height: 150px; border: 1px solid #e5e7eb; border-radius: 4px; background: #ffffff;"></canvas>' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="field">' +
          '<div class="btn-row" style="display: flex; gap: 8px;">' +
            '<div class="gen-container">' +
              '<button class="gen-btn gen-btn-main camera-ctrl-generate-btn" type="button" data-i18n="camera_generate_btn">' + (window.t ? window.t('camera_generate_btn') : '生成图片') + '</button>' +
              '<button class="gen-btn gen-btn-caret camera-ctrl-generate-caret" type="button" aria-label="X1" data-i18n="camera_generate_x1:aria-label">\u25be</button>' +
              '<div class="gen-menu camera-ctrl-gen-menu">' +
                '<div class="gen-item" data-count="1" data-i18n="camera_generate_x1">X1</div>' +
                '<div class="gen-item" data-count="2" data-i18n="camera_generate_x2">X2</div>' +
                '<div class="gen-item" data-count="3" data-i18n="camera_generate_x3">X3</div>' +
              '</div>' +
            '</div>' +
          '</div>' +
          '<div class="gen-meta camera-ctrl-draw-count-label"></div>' +
          '<div class="muted camera-ctrl-status" style="display:none;"></div>' +
        '</div>';
      },
      onCreated: function(node, el) {
        var sourceThumb = el.querySelector('.camera-ctrl-source-thumb');
        var sourceImg = el.querySelector('.camera-ctrl-source-img');
        var sourcePlaceholder = el.querySelector('.camera-ctrl-source-placeholder');
        var statusEl = el.querySelector('.camera-ctrl-status');
        var generateBtn = el.querySelector('.camera-ctrl-generate-btn');
        var genCaret = el.querySelector('.camera-ctrl-generate-caret');
        var genMenu = el.querySelector('.camera-ctrl-gen-menu');
        var drawCountLabel = el.querySelector('.camera-ctrl-draw-count-label');

        // Camera control elements
        var hSlider = el.querySelector('.camera-ctrl-horizontal-angle-slider');
        var hInput = el.querySelector('.camera-ctrl-horizontal-angle');
        var hReset = el.querySelector('.camera-ctrl-reset-horizontal-angle');
        var vSlider = el.querySelector('.camera-ctrl-vertical-angle-slider');
        var vInput = el.querySelector('.camera-ctrl-vertical-angle');
        var vReset = el.querySelector('.camera-ctrl-reset-vertical-angle');
        var zSlider = el.querySelector('.camera-ctrl-zoom-slider');
        var zInput = el.querySelector('.camera-ctrl-zoom');
        var zReset = el.querySelector('.camera-ctrl-reset-zoom');
        var cameraCanvas = el.querySelector('.camera-ctrl-canvas');

        // 绑定输入端口连接事件
        bindInputPortEvents(el, node, {
          cssClass: null,
          acceptType: 'image',
          connectionType: 'connections',
          onConnect: function() {
            updateSourceThumbnail();
          }
        });

        // 覆盖 mousedown 事件以触发相机预览更新
        el.addEventListener('mousedown', function() {
          setTimeout(function() { updateCameraPreview(); }, 50);
        });

        // 更新源图缩略图
        function updateSourceThumbnail() {
          var conn = state.connections.find(function(c) { return c.to === node.id; });
          if (!conn) {
            sourceThumb.style.display = 'none';
            sourcePlaceholder.style.display = 'block';
            sourcePlaceholder.textContent = window.t ? window.t('camera_source_connect') : '请连接图片节点';
            return;
          }
          var sourceNode = state.nodes.find(function(n) { return n.id === conn.from; });
          if (!sourceNode || sourceNode.type !== 'image' || (!sourceNode.data.url && !sourceNode.data.preview)) {
            sourceThumb.style.display = 'none';
            sourcePlaceholder.style.display = 'block';
            sourcePlaceholder.textContent = window.t ? window.t('camera_source_no_image') : '源图片节点没有图片';
            return;
          }
          var url = sourceNode.data.url || sourceNode.data.preview;
          sourceImg.src = proxyImageUrl(url);
          sourceThumb.style.display = 'block';
          sourcePlaceholder.style.display = 'none';
        }

        // 暴露到 DOM 元素供 workflow.js 恢复时调用
        el._updateSourceThumbnail = updateSourceThumbnail;

        // Initial check
        updateSourceThumbnail();

        // 相机参数 3D 预览
        function updateCameraPreview() {
          if (cameraCanvas && typeof window.updateCameraPreview === 'function') {
            window.updateCameraPreview(cameraCanvas, node.data.camera);
          }
        }

        // 确保 camera 数据结构完整
        function ensureCameraData() {
          if (!node.data.camera) {
            node.data.camera = { horizontal_angle: 0, vertical_angle: 0, zoom: 5.0, modified: { horizontal_angle: false, vertical_angle: false, zoom: false } };
          }
          if (!node.data.camera.modified) {
            node.data.camera.modified = { horizontal_angle: false, vertical_angle: false, zoom: false };
          }
        }

        // 水平角度
        if (hSlider) {
          hSlider.addEventListener('input', function(e) {
            var value = parseFloat(e.target.value);
            ensureCameraData();
            node.data.camera.horizontal_angle = value;
            node.data.camera.modified.horizontal_angle = true;
            if (hInput) hInput.value = value;
            updateCameraPreview();
          });
        }
        if (hInput) {
          hInput.addEventListener('input', function(e) {
            var value = parseFloat(e.target.value);
            ensureCameraData();
            node.data.camera.horizontal_angle = value;
            node.data.camera.modified.horizontal_angle = true;
            if (hSlider) hSlider.value = value;
            updateCameraPreview();
          });
        }
        if (hReset) {
          hReset.addEventListener('click', function(e) {
            e.stopPropagation();
            ensureCameraData();
            node.data.camera.horizontal_angle = 0;
            node.data.camera.modified.horizontal_angle = false;
            if (hSlider) hSlider.value = 0;
            if (hInput) hInput.value = 0;
            updateCameraPreview();
          });
        }

        // 垂直角度
        if (vSlider) {
          vSlider.addEventListener('input', function(e) {
            var value = parseFloat(e.target.value);
            ensureCameraData();
            node.data.camera.vertical_angle = value;
            node.data.camera.modified.vertical_angle = true;
            if (vInput) vInput.value = value;
            updateCameraPreview();
          });
        }
        if (vInput) {
          vInput.addEventListener('input', function(e) {
            var value = parseFloat(e.target.value);
            ensureCameraData();
            node.data.camera.vertical_angle = value;
            node.data.camera.modified.vertical_angle = true;
            if (vSlider) vSlider.value = value;
            updateCameraPreview();
          });
        }
        if (vReset) {
          vReset.addEventListener('click', function(e) {
            e.stopPropagation();
            ensureCameraData();
            node.data.camera.vertical_angle = 0;
            node.data.camera.modified.vertical_angle = false;
            if (vSlider) vSlider.value = 0;
            if (vInput) vInput.value = 0;
            updateCameraPreview();
          });
        }

        // 缩放
        if (zSlider) {
          zSlider.addEventListener('input', function(e) {
            var value = parseFloat(e.target.value);
            ensureCameraData();
            node.data.camera.zoom = value;
            node.data.camera.modified.zoom = true;
            if (zInput) zInput.value = value;
            updateCameraPreview();
          });
        }
        if (zInput) {
          zInput.addEventListener('input', function(e) {
            var value = parseFloat(e.target.value);
            ensureCameraData();
            node.data.camera.zoom = value;
            node.data.camera.modified.zoom = true;
            if (zSlider) zSlider.value = value;
            updateCameraPreview();
          });
        }
        if (zReset) {
          zReset.addEventListener('click', function(e) {
            e.stopPropagation();
            ensureCameraData();
            node.data.camera.zoom = 5.0;
            node.data.camera.modified.zoom = false;
            if (zSlider) zSlider.value = 5.0;
            if (zInput) zInput.value = 5.0;
            updateCameraPreview();
          });
        }

        // 抽卡次数
        function updateDrawCountLabel() {
          var t = window.t ? window.t('draw_count_x', { count: node.data.drawCount || 1 }) : null;
          drawCountLabel.textContent = (t && t !== 'draw_count_x') ? t : ('抽卡次数：X' + (node.data.drawCount || 1));
        }
        updateDrawCountLabel();

        if (genCaret) {
          genCaret.addEventListener('click', function(e) {
            e.stopPropagation();
            genMenu.classList.toggle('show');
          });
        }

        var genItems = genMenu.querySelectorAll('.gen-item');
        for (var gi = 0; gi < genItems.length; gi++) {
          (function(item) {
            item.addEventListener('click', function(e) {
              e.stopPropagation();
              var count = Number(item.dataset.count || '1');
              node.data.drawCount = count;
              updateDrawCountLabel();
              genMenu.classList.remove('show');
            });
          })(genItems[gi]);
        }

        // 检测 runninghub 配置状态
        function updateRunningHubBtnStatus() {
          if (window.TaskConfig) {
            var isConfigured = window.TaskConfig.isRunningHubConfigured();
            if (!isConfigured) {
              generateBtn.disabled = true;
              generateBtn.title = window.t ? window.t('runninghub_not_configured') : '该功能依赖runninghub接口，请配置密钥';
              generateBtn.textContent = (window.t ? window.t('camera_generate_btn') : '生成图片') + '(未配置)';
              statusEl.style.display = 'block';
              statusEl.style.color = '#ef4444';
              statusEl.textContent = window.t ? window.t('runninghub_not_configured') : '该功能依赖runninghub接口，请配置密钥';
            } else {
              generateBtn.disabled = false;
              generateBtn.title = '';
              generateBtn.textContent = window.t ? window.t('camera_generate_btn') : '生成图片';
              statusEl.style.display = 'none';
              statusEl.textContent = '';
            }
          }
        }

        updateRunningHubBtnStatus();

        if (window.TaskConfig && window.TaskConfig.onLoaded) {
          window.TaskConfig.onLoaded(function() { updateRunningHubBtnStatus(); });
        }

        // 生成图片按钮
        generateBtn.addEventListener('click', async function(e) {
          e.stopPropagation();

          // 0. 检查 runninghub 配置
          if (window.TaskConfig && !window.TaskConfig.isRunningHubConfigured()) {
            showToast(window.t ? window.t('camera_control_not_configured') : '该功能依赖runninghub接口，请配置密钥', 'error');
            return;
          }

          // 1. 验证源图片
          var conn = state.connections.find(function(c) { return c.to === node.id; });
          if (!conn) {
            showToast(window.t ? window.t('camera_control_connect_image') : '请先连接图片节点', 'warning');
            return;
          }
          var sourceNode = state.nodes.find(function(n) { return n.id === conn.from; });
          if (!sourceNode || sourceNode.type !== 'image') {
            showToast(window.t ? window.t('camera_control_connect_image') : '请连接图片节点', 'warning');
            return;
          }
          var sourceImageUrl = sourceNode.data ? sourceNode.data.url : null;
          if (!sourceImageUrl) {
            showToast(window.t ? window.t('camera_control_no_image') : '源图片节点没有图片', 'warning');
            return;
          }

          // 2. 检查相机参数是否修改
          var hasModifications = node.data.camera && node.data.camera.modified &&
            (node.data.camera.modified.horizontal_angle || node.data.camera.modified.vertical_angle || node.data.camera.modified.zoom);
          if (!hasModifications) {
            showToast(window.t ? window.t('camera_control_adjust_params') : '请先调整相机参数', 'warning');
            return;
          }

          // 3. 获取多角度 task_id 和算力
          var multiAngleTaskId = window.TaskConfig && window.TaskConfig.getTaskIdByKey('qwen-multi-angle', 'image_edit');
          if (!multiAngleTaskId) {
            showToast(window.t ? window.t('camera_control_task_config_not_found') : '未找到多角度任务配置', 'error');
            return;
          }

          var computingPower = 4; // QWEN_MULTI_ANGLE_IMAGE = 4
          var totalPower = computingPower * (node.data.drawCount || 1);

          // 4. 确认算力
          var userId = localStorage.getItem('user_id');
          var authToken = localStorage.getItem('auth_token') || '';
          var canvasRatio = state.ratio || (typeof ratioSelectEl !== 'undefined' ? ratioSelectEl.value : '') || '16:9';

          if (userId) {
            try {
              var headers = { 'Authorization': 'Bearer ' + authToken };
              var checkRes = await fetch('/api/user/computing_power', { headers: headers });
              var checkData = await checkRes.json();
              if (checkData.success && checkData.data) {
                var userPower = checkData.data.computing_power != null ? checkData.data.computing_power : 0;
                if (userPower < totalPower) {
                  var msg = window.t ? window.t('camera_control_insufficient_power', { need: totalPower, current: userPower }) : ('算力不足（需要 ' + totalPower + '，当前 ' + userPower + '）');
                  showToast(msg, 'error');
                  return;
                }
              }
            } catch (err) {
              console.warn('检查算力失败:', err);
            }
          }

          // 5. 提交任务
          setBtnLoading(generateBtn, window.t ? window.t('camera_control_generating', { progress: '0%' }) : '生成中...');
          statusEl.style.display = 'block';
          statusEl.style.color = '#666';
          statusEl.textContent = window.t ? window.t('camera_control_submitting', { count: node.data.drawCount, power: totalPower }) : ('正在提交任务（' + node.data.drawCount + '张，预计消耗 ' + totalPower + ' 算力）...');

          try {
            var cameraParams = convertCameraToQwenMultiAngleParams(node.data.camera);

            var form = new FormData();
            form.append('task_id', multiAngleTaskId);
            form.append('ref_image_urls', sourceImageUrl);
            form.append('prompt', generateCameraPrompt(node.data.camera));
            form.append('extra_config', JSON.stringify(cameraParams));
            form.append('count', node.data.drawCount || 1);
            form.append('ratio', canvasRatio);
            if (userId) form.append('user_id', userId);
            if (authToken) form.append('auth_token', authToken);

            var res = await fetch('/api/image-edit', {
              method: 'POST',
              body: form
            });

            if (!res.ok) {
              var errData = await res.json().catch(function() { return {}; });
              throw new Error(errData.detail || 'HTTP ' + res.status);
            }

            var data = await res.json();
            if (!data.project_ids || data.project_ids.length === 0) {
              throw new Error(data.detail || data.message || '提交任务失败');
            }

            showToast(window.t ? window.t('camera_control_submitted') : '任务已提交，正在生成图片...', 'info');
            statusEl.textContent = window.t ? window.t('camera_control_submitted') : '任务已提交，等待结果...';

            // 6. 创建图片节点
            var createdImageNodeIds = [];
            var projectIds = data.project_ids;

            for (var i = 0; i < projectIds.length; i++) {
              var offsetY = i * 280;
              var newNodeId = createImageNode({
                x: node.x + 380,
                y: node.y + offsetY,
                checkCollision: true
              });

              var newNode = state.nodes.find(function(n) { return n.id === newNodeId; });
              if (newNode) {
                newNode.data.name = projectIds.length > 1 ? ('相机图' + (i + 1)) : '相机图';
                newNode.data.project_id = projectIds[i] || projectIds[0];
                newNode.title = newNode.data.name;

                var newEl = canvasEl.querySelector('.node[data-node-id="' + newNodeId + '"]');
                if (newEl) {
                  var titleEl = newEl.querySelector('.node-title');
                  if (titleEl) titleEl.textContent = newNode.title;
                }

                // 连接: camera_control → 新图片节点
                state.connections.push({
                  id: state.nextConnId++,
                  from: node.id,
                  to: newNodeId
                });

                createdImageNodeIds.push(newNodeId);
              }
            }

            renderAllConnections();
            renderMinimap();

            // 7. 轮询结果
            pollVideoStatus(
              projectIds,
              function(progressText) {
                generateBtn.textContent = progressText;
                statusEl.textContent = progressText;
              },
              function(statusResult) {
                // 提取结果 URL
                var imageUrls = [];
                if (statusResult.tasks && Array.isArray(statusResult.tasks)) {
                  imageUrls = statusResult.tasks
                    .filter(function(task) { return task.status === 'SUCCESS' && task.result; })
                    .map(function(task) { return normalizeVideoUrl(task.result); })
                    .filter(Boolean);
                } else {
                  var rawResults = extractResultsArray(statusResult);
                  imageUrls = Array.isArray(rawResults)
                    ? rawResults.map(normalizeVideoUrl).filter(Boolean)
                    : [];
                }

                if (imageUrls.length === 0) {
                  showToast(window.t ? window.t('camera_control_no_image_result') : '生成成功，但未获取到图片地址', 'error');
                  generateBtn.disabled = false;
                  generateBtn.textContent = window.t ? window.t('camera_generate_btn') : '生成图片';
                  statusEl.textContent = '生成完成（未获取图片）';
                  return;
                }

                // 更新图片节点
                imageUrls.forEach(function(imageUrl, index) {
                  if (index >= createdImageNodeIds.length) return;
                  var imageNodeId = createdImageNodeIds[index];
                  var imageNode = state.nodes.find(function(n) { return n.id === imageNodeId; });

                  if (imageNode) {
                    var normalizedUrl = normalizeImageUrl(imageUrl);
                    imageNode.data.url = normalizedUrl;
                    imageNode.data.preview = normalizedUrl;

                    var imageNodeEl = canvasEl.querySelector('.node[data-node-id="' + imageNodeId + '"]');
                    if (imageNodeEl) {
                      var previewImg = imageNodeEl.querySelector('.image-preview');
                      var previewRow = imageNodeEl.querySelector('.image-preview-row');
                      if (previewImg && previewRow) {
                        previewImg.src = proxyImageUrl(imageUrl);
                        previewRow.style.display = 'flex';
                      }
                    }
                  }
                });

                renderAllConnections();

                setBtnReady(generateBtn, window.t ? window.t('camera_generate_btn') : '生成图片');
                statusEl.style.color = '#22c55e';
                statusEl.textContent = '生成成功！已创建 ' + imageUrls.length + ' 个图片节点';
                var successMsg = window.t ? window.t('camera_control_success', { count: imageUrls.length }) : ('相机控制生成成功！已创建 ' + imageUrls.length + ' 个图片节点');
                showToast(successMsg, 'success');

                safeAutoSave();
              },
              function(error) {
                var errMsg = window.t ? window.t('camera_control_generation_failed', { error: error }) : ('生成失败: ' + error);
                showToast(errMsg, 'error');
                setBtnReady(generateBtn, window.t ? window.t('camera_generate_btn') : '生成图片');
                statusEl.style.color = '#dc2626';
                statusEl.textContent = errMsg;
              }
            );

          } catch (error) {
            console.error('相机控制生成失败:', error);
            showToast('生成失败: ' + (error.message || error), 'error');
            generateBtn.disabled = false;
            generateBtn.textContent = window.t ? window.t('camera_generate_btn') : '生成图片';
            statusEl.style.color = '#dc2626';
            statusEl.textContent = '生成失败: ' + (error.message || error);
          }
        });

        // 初始化 3D 预览
        setTimeout(function() { updateCameraPreview(); }, 100);
      }
    }, opts);
  }

  var createCameraControlNodeWithData = createNodeWithDataFactory(
    createCameraControlNode,
    function(el, node) {
      // 恢复相机参数到 UI
      var hSlider = el.querySelector('.camera-ctrl-horizontal-angle-slider');
      var hInput = el.querySelector('.camera-ctrl-horizontal-angle');
      var vSlider = el.querySelector('.camera-ctrl-vertical-angle-slider');
      var vInput = el.querySelector('.camera-ctrl-vertical-angle');
      var zSlider = el.querySelector('.camera-ctrl-zoom-slider');
      var zInput = el.querySelector('.camera-ctrl-zoom');

      if (node.data.camera) {
        if (hSlider) hSlider.value = node.data.camera.horizontal_angle != null ? node.data.camera.horizontal_angle : 0;
        if (hInput) hInput.value = node.data.camera.horizontal_angle != null ? node.data.camera.horizontal_angle : 0;
        if (vSlider) vSlider.value = node.data.camera.vertical_angle != null ? node.data.camera.vertical_angle : 0;
        if (vInput) vInput.value = node.data.camera.vertical_angle != null ? node.data.camera.vertical_angle : 0;
        if (zSlider) zSlider.value = node.data.camera.zoom != null ? node.data.camera.zoom : 5.0;
        if (zInput) zInput.value = node.data.camera.zoom != null ? node.data.camera.zoom : 5.0;
      }

      // 恢复抽卡次数标签
      var drawCountLabel = el.querySelector('.camera-ctrl-draw-count-label');
      if (drawCountLabel) {
        var _t = window.t ? window.t('draw_count_x', { count: node.data.drawCount || 1 }) : null;
        drawCountLabel.textContent = (_t && _t !== 'draw_count_x') ? _t : ('抽卡次数：X' + (node.data.drawCount || 1));
      }

      // 更新源图缩略图
      var updateSourceThumbnail = el._updateSourceThumbnail;
      if (typeof updateSourceThumbnail === 'function') updateSourceThumbnail();
    }
  );

  // 注册到全局
  window.createCameraControlNode = createCameraControlNode;
  window.createCameraControlNodeWithData = createCameraControlNodeWithData;

  // 注册到节点注册表
  registerNodeType('camera_control', {
    createFn: createCameraControlNode,
    createWithDataFn: createCameraControlNodeWithData
  });

})();
