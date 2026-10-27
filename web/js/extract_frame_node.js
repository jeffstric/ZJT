// ============================
// extract_frame_node.js - 提取帧节点
// 使用 createNodeBase 基类工厂
// 帧类型：first=首帧 / last=尾帧 / custom=时间轴选帧 / keyframes=关键帧候选（场景切换自动截取）
// ============================

(function() {

  var EXTRACT_FRAME_PORTS = [
    { direction: 'input', titleI18nKey: 'extract_frame_input_port', acceptType: 'video', connectionType: 'connections' },
    { direction: 'output', titleI18nKey: 'extract_frame_output_port' }
  ];

  // 浏览器本地临时地址（blob:/data:）：服务端无法访问，不可作为 video_url 提交
  function isTemporaryVideoUrl(url) {
    return !!url && (url.indexOf('blob:') === 0 || url.indexOf('data:') === 0);
  }

  // 查找输入端口当前连接的视频源节点（无连接返回 null）
  function findConnectedVideoNode(node) {
    if (typeof state === 'undefined' || !state.connections || !state.nodes) return null;
    var conn = state.connections.find(function(c) { return c.to === node.id; });
    if (!conn) return null;
    return state.nodes.find(function(n) { return n.id === conn.from; }) || null;
  }

  // 秒 → "mm:ss.cc" 时间码
  function formatTimecode(sec) {
    if (!isFinite(sec) || sec < 0) sec = 0;
    var m = Math.floor(sec / 60);
    var s = Math.floor(sec % 60);
    var cs = Math.floor((sec % 1) * 100);
    return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s + '.' + (cs < 10 ? '0' : '') + cs;
  }

  // 关键帧候选网格渲染（onCreated 与重载恢复共用）
  function renderKeyframeGrid(gridEl, frames, selectedTime, onSelect) {
    gridEl.innerHTML = '';
    frames.forEach(function(fr) {
      var cell = document.createElement('div');
      cell.className = 'keyframe-cell';
      cell.setAttribute('data-time', String(fr.time_sec));

      var img = document.createElement('img');
      img.className = 'keyframe-img';
      img.src = fr.url;
      img.loading = 'lazy';
      img.alt = '';

      var label = document.createElement('div');
      label.className = 'keyframe-time';
      label.textContent = formatTimecode(fr.time_sec);

      cell.appendChild(img);
      cell.appendChild(label);
      if (selectedTime !== null && selectedTime !== undefined && Math.abs(fr.time_sec - selectedTime) < 0.001) {
        cell.classList.add('selected');
      }
      cell.addEventListener('click', function() {
        gridEl.querySelectorAll('.keyframe-cell').forEach(function(c) { c.classList.remove('selected'); });
        cell.classList.add('selected');
        if (typeof onSelect === 'function') onSelect(fr);
      });
      gridEl.appendChild(cell);
    });
  }

  function createExtractFrameNode(opts) {
    return createNodeBase({
      type: 'extract_frame',
      title: function() { return window.t ? window.t('extract_frame_title') : '提取帧'; },
      defaultData: {
        videoFile: null,
        videoUrl: '',
        videoName: '',
        frameType: 'first',
        timeSec: null,
        keyframeStartSec: 0,
        candidateFrames: null,
        selectedFrameTime: null,
        extractedImageNodeId: null,
        status: 'idle'
      },
      ports: EXTRACT_FRAME_PORTS,
      width: 280,
      height: 250,
      titleIcon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><rect x="4" y="6" width="16" height="12" rx="2"/><path d="M10 9.5V14.5L14.5 12L10 9.5Z" fill="currentColor" /><rect x="6" y="2" width="6" height="4" rx="1" stroke="currentColor" stroke-width="2" /></svg>',
      bodyHtml: function() {
        return '<div class="field field-collapsible">' +
          '<div class="label" data-i18n="video">视频</div>' +
          '<input class="video-file" type="file" accept="video/*" />' +
        '</div>' +
        '<div class="field field-always-visible video-preview-field" style="display:none;">' +
          '<div class="label" data-i18n="video_preview">预览</div>' +
          '<div class="video-preview"><video class="video-thumb" playsinline muted></video></div>' +
          '<div class="gen-meta video-name"></div>' +
        '</div>' +
        '<div class="field field-always-visible frame-type-field">' +
          '<div class="label" data-i18n="frame_type">帧类型</div>' +
          '<select class="frame-type-select">' +
            '<option value="first" data-i18n="frame_first">首帧</option>' +
            '<option value="last" data-i18n="frame_last">尾帧</option>' +
            '<option value="custom" data-i18n="frame_custom">自定义时间</option>' +
            '<option value="keyframes" data-i18n="frame_keyframes">关键帧（自动）</option>' +
          '</select>' +
        '</div>' +
        '<div class="field field-always-visible time-picker-field" style="display:none;">' +
          '<div class="label time-label" data-i18n="extract_frame_time_label">时间点</div>' +
          '<input class="time-slider" type="range" min="0" max="100" step="0.01" value="0" />' +
          '<div class="time-display"><span class="time-current">00:00.00</span> / <span class="time-total">--:--.--</span></div>' +
          '<button class="gen-btn keyframe-extract-btn" type="button" style="display:none; margin-top:6px;" data-i18n="extract_frame_extract_list">提取关键帧列表</button>' +
        '</div>' +
        '<div class="field field-always-visible keyframe-grid-field" style="display:none;">' +
          '<div class="label" data-i18n="extract_frame_keyframe_grid_label">候选帧（点击选择）</div>' +
          '<div class="keyframe-grid"></div>' +
          '<button class="gen-btn use-keyframe-btn" type="button" style="display:none; margin-top:6px;" data-i18n="extract_frame_use_selected">使用选中帧</button>' +
        '</div>' +
        '<div class="field field-always-visible extract-actions-field">' +
          '<button class="gen-btn" type="button" data-i18n="extract_frame_btn" title="提取帧">提取帧</button>' +
        '</div>' +
        '<div class="field field-always-visible status-field" style="display:none;">' +
          '<div class="gen-meta status"></div>' +
        '</div>';
      },
      onCreated: function(node, el) {
        var fileEl = el.querySelector('.video-file');
        var previewField = el.querySelector('.video-preview-field');
        var thumbVideo = el.querySelector('.video-thumb');
        var nameEl = el.querySelector('.video-name');
        var frameTypeSelect = el.querySelector('.frame-type-select');
        var timePickerField = el.querySelector('.time-picker-field');
        var timeSlider = el.querySelector('.time-slider');
        var timeCurrentEl = el.querySelector('.time-current');
        var timeTotalEl = el.querySelector('.time-total');
        var keyframeGridField = el.querySelector('.keyframe-grid-field');
        var keyframeGrid = el.querySelector('.keyframe-grid');
        var useKeyframeBtn = el.querySelector('.use-keyframe-btn');
        var keyframeExtractBtn = el.querySelector('.keyframe-extract-btn');
        // 注意：use-keyframe-btn 同为 .gen-btn 且在 DOM 中靠前，必须按容器限定才能取到提取按钮
        var extractActionsField = el.querySelector('.extract-actions-field');
        var extractBtn = el.querySelector('.extract-actions-field .gen-btn');
        var statusField = el.querySelector('.status-field');
        var statusEl = el.querySelector('.status');

        // 绑定输入端口连接事件
        bindInputPortEvents(el, node, {
          cssClass: null,
          acceptType: 'video',
          connectionType: 'connections',
          onConnect: function(fromNode) {
            applySourceVideo(fromNode);
          }
        });

        // 从源视频节点同步地址与预览（onConnect 与提取前回读共用）
        function applySourceVideo(fromNode) {
          node.data.videoUrl = fromNode.data.url || '';
          node.data.videoName = fromNode.data.name || '视频';
          if (node.data.videoUrl) {
            thumbVideo.src = proxyDownloadUrl(node.data.videoUrl);
            previewField.style.display = '';
            nameEl.textContent = node.data.videoName;
          }
        }

        // 设置视频
        function setVideoFromUrl(url, name) {
          node.data.videoUrl = url || '';
          node.data.videoName = name || '';
          thumbVideo.src = url ? proxyDownloadUrl(url) : '';
          previewField.style.display = url ? '' : 'none';
          nameEl.textContent = name || '';
        }

        // 提取动作按钮（通用"提取帧" / 关键帧"提取关键帧列表"）统一置忙/就绪
        function setActionButtonsBusy(busy, busyLabel) {
          var busyText = busyLabel || (window.t ? window.t('extract_frame_extracting') : '提取中...');
          [extractBtn, keyframeExtractBtn].forEach(function(b) {
            if (!b) return;
            if (busy) {
              setBtnLoading(b, busyText);
            } else {
              var readyText = (b === keyframeExtractBtn)
                ? (window.t ? window.t('extract_frame_extract_list') : '提取关键帧列表')
                : (window.t ? window.t('extract_frame_btn') : '提取帧');
              setBtnReady(b, readyText);
            }
          });
        }

        function clearResult() {
          node.data.extractedImageNodeId = null;
          node.data.candidateFrames = null;
          node.data.selectedFrameTime = null;
          node.data.keyframeStartSec = 0;
          node.data.status = 'idle';
          statusField.style.display = 'none';
          keyframeGridField.style.display = 'none';
          keyframeGrid.innerHTML = '';
          useKeyframeBtn.style.display = 'none';
          setActionButtonsBusy(false);
        }

        // 视频文件上传
        fileEl.addEventListener('change', async function(e) {
          var file = e.target.files[0];
          if (!file) return;
          if (!file.type.startsWith('video/')) {
            showToast(window.t ? window.t('extract_frame_select_video') : '请选择视频文件', 'error');
            return;
          }
          try {
            showToast('正在处理视频...', 'info');
            var dataUrl = await readFileAsDataUrl(file);
            node.data.videoFile = file;
            node.data.videoName = file.name;
            node.data.videoUrl = dataUrl;
            node.data.timeSec = null;
            thumbVideo.src = dataUrl;
            previewField.style.display = '';
            nameEl.textContent = file.name;
            clearResult();
            showToast(window.t ? window.t('extract_frame_loaded') : '视频已加载，点击"提取帧"按钮提取', 'success');
            safeAutoSave();
          } catch (error) {
            console.error('视频处理失败:', error);
            showToast(window.t ? window.t('extract_frame_failed') : '视频处理失败', 'error');
          }
        });

        // ===== 时间轴（custom=提取时间点 / keyframes=翻页起始时间，复用同一滑杆） =====
        function syncTimeDisplay(sec) {
          timeCurrentEl.textContent = formatTimecode(sec);
        }

        // 当前模式写入/读取的时间字段
        function activeTimeField() {
          return node.data.frameType === 'custom' ? 'timeSec' : 'keyframeStartSec';
        }

        // 把滑杆与时间码同步到当前模式保存的时间值（元数据未就绪时由 loadedmetadata 补做）
        function syncSliderToData() {
          var dur = thumbVideo.duration;
          if (!isFinite(dur) || dur <= 0) return;
          var v = node.data[activeTimeField()];
          var t = Math.min(Math.max(0, (v === null || v === undefined) ? 0 : v), dur);
          timeSlider.value = String(t);
          syncTimeDisplay(t);
        }

        function applyFrameTypeUi() {
          var isCustom = node.data.frameType === 'custom';
          var isKeyframes = node.data.frameType === 'keyframes';
          var showPicker = isCustom || isKeyframes;
          timePickerField.style.display = showPicker ? '' : 'none';
          thumbVideo.controls = isCustom;
          // 关键帧专属控件只在该模式下可见（提取列表按钮 / 候选网格 / 使用选中帧）；
          // 其余模式下通用"提取帧"按钮回归
          if (keyframeExtractBtn) keyframeExtractBtn.style.display = isKeyframes ? '' : 'none';
          extractActionsField.style.display = isKeyframes ? 'none' : '';
          var hasGrid = !!(node.data.candidateFrames && node.data.candidateFrames.length);
          keyframeGridField.style.display = (isKeyframes && hasGrid) ? '' : 'none';
          useKeyframeBtn.style.display = (isKeyframes && hasGrid
            && node.data.selectedFrameTime !== null && node.data.selectedFrameTime !== undefined) ? '' : 'none';
          var timeLabel = el.querySelector('.time-label');
          if (timeLabel) {
            // 标签文本随模式切换：移除 data-i18n，防止页面 i18n 扫描覆盖动态文本
            timeLabel.removeAttribute('data-i18n');
            timeLabel.textContent = isCustom
              ? (window.t ? window.t('extract_frame_time_label') : '时间点')
              : (window.t ? window.t('extract_frame_start_label') : '起始时间');
          }
          if (showPicker) {
            syncSliderToData();
            if (isKeyframes && isFinite(thumbVideo.duration) && thumbVideo.duration > 0) {
              // 关键帧模式：预览 seek 到起始位置，直观展示下一批从哪里开始
              try { thumbVideo.currentTime = parseFloat(timeSlider.value) || 0; } catch (err) { /* 忽略 */ }
            }
          }
        }

        frameTypeSelect.addEventListener('change', function(e) {
          node.data.frameType = e.target.value;
          applyFrameTypeUi();
          safeAutoSave();
        });

        // 视频元数据就绪：设置时间轴范围并恢复当前模式保存的时间（含工作流重载恢复）
        thumbVideo.addEventListener('loadedmetadata', function() {
          var dur = thumbVideo.duration;
          if (!isFinite(dur) || dur <= 0) return;
          timeSlider.max = String(dur);
          timeTotalEl.textContent = formatTimecode(dur);
          syncSliderToData();
          if (node.data.frameType === 'custom' && node.data.timeSec !== null && node.data.timeSec !== undefined) {
            try { thumbVideo.currentTime = Math.min(Math.max(0, node.data.timeSec), dur); } catch (err) { /* 部分格式 seek 失败不影响 */ }
          }
        });

        timeSlider.addEventListener('input', function(e) {
          var t = parseFloat(e.target.value);
          if (!isFinite(t)) return;
          node.data[activeTimeField()] = t;
          syncTimeDisplay(t);
          if (node.data.frameType === 'custom') {
            try { thumbVideo.currentTime = t; } catch (err) { /* 忽略 seek 异常 */ }
          }
        });
        // 松手才落自动保存，避免拖动高频触发
        timeSlider.addEventListener('change', function() {
          safeAutoSave();
        });

        // 播放/拖动原生进度条时同步时间轴与显示
        thumbVideo.addEventListener('timeupdate', function() {
          if (node.data.frameType !== 'custom') return;
          timeSlider.value = String(thumbVideo.currentTime);
          node.data.timeSec = thumbVideo.currentTime;
          syncTimeDisplay(thumbVideo.currentTime);
        });
        thumbVideo.addEventListener('seeked', function() {
          if (node.data.frameType !== 'custom') return;
          timeSlider.value = String(thumbVideo.currentTime);
          node.data.timeSec = thumbVideo.currentTime;
          syncTimeDisplay(thumbVideo.currentTime);
        });

        // ===== 关键帧候选网格（keyframes 模式） =====
        function showKeyframeGrid(frames) {
          node.data.candidateFrames = frames;
          node.data.selectedFrameTime = null;
          useKeyframeBtn.style.display = 'none';
          renderKeyframeGrid(keyframeGrid, frames, null, function(fr) {
            node.data.selectedFrameTime = fr.time_sec;
            useKeyframeBtn.style.display = '';
            safeAutoSave();
          });
          keyframeGridField.style.display = '';
        }

        useKeyframeBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          var fr = (node.data.candidateFrames || []).find(function(f) {
            return node.data.selectedFrameTime !== null
              && Math.abs(f.time_sec - node.data.selectedFrameTime) < 0.001;
          });
          if (!fr) return;
          var nameBase = node.data.videoName ? node.data.videoName.replace(/\.[^.]+$/, '') : 'keyframe';
          createImageNodeFromExtracted(fr.url, nameBase + '_' + fr.time_sec.toFixed(2) + 's.jpg');
        });

        // 提取成功后创建图片节点并连线（首/尾/自定义/关键帧选中共用）
        function createImageNodeFromExtracted(imageUrl, imageName) {
          var imageNodeId = createImageNode({ x: node.x + 280, y: node.y, checkCollision: true });
          var imageNode = state.nodes.find(function(n) { return n.id === imageNodeId; });
          if (imageNode) {
            imageNode.data.url = imageUrl;
            imageNode.data.preview = imageUrl;
            imageNode.data.name = imageName;

            var imageNodeEl = canvasEl.querySelector('.node[data-node-id="' + imageNodeId + '"]');
            if (imageNodeEl) {
              var previewRow = imageNodeEl.querySelector('.image-preview-row');
              var previewImg = imageNodeEl.querySelector('.image-preview');
              if (previewRow && previewImg) {
                previewRow.style.display = 'flex';
                previewImg.src = imageUrl;
              }
            }

            state.imageConnections.push({
              id: state.nextImgConnId++,
              from: node.id,
              to: imageNodeId,
              portType: 'extracted'
            });

            node.data.extractedImageNodeId = imageNodeId;

            requestAnimationFrame(function() {
              renderAllConnections();
            });
          }
          renderMinimap();
          safeAutoSave();
        }

        // 提取帧按钮（首帧/尾帧/自定义时间）
        extractBtn.addEventListener('click', async function(e) {
          e.stopPropagation();
          await extractFrame();
        });

        // 提取关键帧列表按钮（关键帧模式专属，基于起始时间提取下一批）
        if (keyframeExtractBtn) {
          keyframeExtractBtn.addEventListener('click', async function(e) {
            e.stopPropagation();
            await extractFrame();
          });
        }

        async function extractFrame() {
          // 连线场景下 videoUrl 可能复制于源节点上传完成前（blob: 临时地址），
          // 提交前实时回读源节点最新地址；源节点仍在上传/无视频时给出明确提示，
          // 避免把临时地址发给后端报"不支持外部视频URL"
          var connectedVideoNode = (!node.data.videoFile) ? findConnectedVideoNode(node) : null;
          if (connectedVideoNode) {
            var liveUrl = (connectedVideoNode.data && connectedVideoNode.data.url) || '';
            if (!liveUrl) {
              showToast(window.t ? window.t('extract_frame_source_no_video') : '源视频节点还没有视频，请先上传', 'warning');
              return;
            }
            if (isTemporaryVideoUrl(liveUrl)) {
              showToast(window.t ? window.t('extract_frame_source_uploading') : '源视频还在上传中，请稍候再试', 'warning');
              return;
            }
            if (liveUrl !== node.data.videoUrl) {
              applySourceVideo(connectedVideoNode);
              safeAutoSave();
            }
          }

          var hasVideoFile = node.data.videoFile !== null;
          var hasVideoUrl = node.data.videoUrl && node.data.videoUrl.length > 0;

          if (!hasVideoFile && !hasVideoUrl) {
            showToast(window.t ? window.t('extract_frame_no_video') : '请先上传视频或连接视频节点', 'error');
            return;
          }

          var frameType = node.data.frameType || 'first';
          var frameTypeName = frameType === 'last' ? '尾帧' : (frameType === 'custom' ? '自定义帧' : (frameType === 'keyframes' ? '关键帧' : '首帧'));

          if (frameType === 'custom' && (node.data.timeSec === null || node.data.timeSec === undefined)) {
            showToast(window.t ? window.t('extract_frame_time_required') : '请先在时间轴上选择时间点', 'error');
            return;
          }

          node.data.status = 'extracting';
          statusField.style.display = '';
          statusEl.textContent = '正在提取' + frameTypeName + '...';
          statusEl.style.color = '';
          setActionButtonsBusy(true);

          try {
            var formData = new FormData();
            var isServerUrl = node.data.videoUrl && (node.data.videoUrl.startsWith('/upload/') || node.data.videoUrl.includes('/upload/'));

            if (hasVideoFile && !isServerUrl) {
              formData.append('file', node.data.videoFile);
            } else if (node.data.videoUrl) {
              formData.append('video_url', node.data.videoUrl);
            } else {
              showToast('没有可提取的视频', 'error');
              setActionButtonsBusy(false);
              return;
            }

            formData.append('frame_type', frameType);
            if (frameType === 'custom') {
              formData.append('time_sec', String(node.data.timeSec));
            }
            if (frameType === 'keyframes') {
              formData.append('start_time', String(node.data.keyframeStartSec || 0));
            }

            var response = await fetch('/api/video-workflow/extract-frame', {
              method: 'POST',
              headers: {
                'Authorization': localStorage.getItem('auth_token') || '',
                'X-User-Id': localStorage.getItem('user_id') || '1'
              },
              body: formData
            });

            var result = await response.json();

            if (result.code === 0 && result.data) {
              // 关键帧模式：渲染候选网格，等待用户选择
              if (frameType === 'keyframes') {
                var frames = result.data.frames || [];
                if (!frames.length) {
                  node.data.status = 'error';
                  statusEl.textContent = window.t ? window.t('extract_frame_no_more') : '已到视频末尾，没有更多关键帧';
                  statusEl.style.color = '#ef4444';
                  showToast(window.t ? window.t('extract_frame_no_more') : '已到视频末尾，没有更多关键帧', 'error');
                  // 起点已推进到末尾：回退到本批起点之前不再自动变化，保留已展示的网格
                  return;
                }
                node.data.status = 'success';
                statusEl.textContent = '提取到 ' + frames.length + ' 个关键帧，点击选择后使用';
                statusEl.style.color = '#22c55e';
                showKeyframeGrid(frames);
                // 起始时间推进到本批最后一帧：继续点击"提取帧"即提取下一批
                if (result.data.last_time_sec !== null && result.data.last_time_sec !== undefined) {
                  node.data.keyframeStartSec = result.data.last_time_sec;
                  syncSliderToData();
                }
                showToast('关键帧提取成功，起始时间已推进，可继续提取下一批', 'success');
                safeAutoSave();
                return;
              }

              // 单帧模式（first / last / custom）
              var imageUrl = result.data.url;
              node.data.status = 'success';
              statusEl.textContent = '提取成功，正在创建图片节点...';
              statusEl.style.color = '#22c55e';

              var ext = '.jpg';
              var nameBase = node.data.videoName ? node.data.videoName.replace(/\.[^.]+$/, '') : '';
              var imageName;
              if (frameType === 'custom') {
                imageName = (nameBase || 'frame') + '_' + Number(node.data.timeSec).toFixed(2) + 's' + ext;
              } else {
                imageName = (nameBase ? nameBase + '_' : '') + frameTypeName + ext;
              }

              createImageNodeFromExtracted(imageUrl, imageName);

              setTimeout(function() { statusField.style.display = 'none'; }, 2000);
              showToast(frameTypeName + '提取成功，已创建图片节点', 'success');
            } else {
              node.data.status = 'error';
              statusEl.textContent = result.message || '提取失败';
              statusEl.style.color = '#ef4444';
              showToast(result.message || '提取' + frameTypeName + '失败', 'error');
            }
          } catch (error) {
            console.error('提取帧失败:', error);
            node.data.status = 'error';
            statusEl.textContent = '网络错误';
            statusEl.style.color = '#ef4444';
            showToast('提取' + frameTypeName + '失败，请检查网络连接', 'error');
          } finally {
            setActionButtonsBusy(false);
          }
        }

        // 重载恢复：帧类型对应的 UI（时间轴显隐、原生 controls）
        applyFrameTypeUi();
      }
    }, opts);
  }

  var createExtractFrameNodeWithData = createNodeWithDataFactory(
    createExtractFrameNode,
    function(el, node) {
      var previewField = el.querySelector('.video-preview-field');
      var thumbVideo = el.querySelector('.video-thumb');
      var nameEl = el.querySelector('.video-name');

      if (node.data.videoUrl) {
        thumbVideo.src = proxyDownloadUrl(node.data.videoUrl);
        previewField.style.display = '';
        nameEl.textContent = node.data.videoName;
      } else {
        // 连线来源的视频地址不入库（blob: 地址保存时被清空）：连接恢复晚于节点创建，
        // 延迟一拍等连接就位后从源节点回读，保证重载后提取帧节点能复原预览与提取能力
        setTimeout(function() {
          var fromNode = findConnectedVideoNode(node);
          if (!fromNode) return;
          var liveUrl = (fromNode.data && fromNode.data.url) || '';
          if (!liveUrl || isTemporaryVideoUrl(liveUrl)) return;
          node.data.videoUrl = liveUrl;
          if (!node.data.videoName) node.data.videoName = fromNode.data.name || '视频';
          thumbVideo.src = proxyDownloadUrl(liveUrl);
          previewField.style.display = '';
          nameEl.textContent = node.data.videoName;
        }, 0);
      }

      if (node.data.frameType) {
        var frameTypeSelect = el.querySelector('.frame-type-select');
        if (frameTypeSelect) {
          frameTypeSelect.value = node.data.frameType;
          // onCreated 先于数据合并执行，applyFrameTypeUi 当时看到的是默认帧类型；
          // 数据合并完成后重发 change，让模式相关的显隐（时间轴/关键帧按钮/网格）统一按恢复值刷新。
          // select 值不匹配任何选项（脏数据）时不动，保持 defaultData
          if (frameTypeSelect.value) {
            frameTypeSelect.dispatchEvent(new Event('change'));
          }
        }
      }

      // 关键帧候选网格重建（容器显隐已由 applyFrameTypeUi 处理）
      if (node.data.candidateFrames && node.data.candidateFrames.length) {
        var keyframeGrid = el.querySelector('.keyframe-grid');
        renderKeyframeGrid(keyframeGrid, node.data.candidateFrames, node.data.selectedFrameTime, function(fr) {
          node.data.selectedFrameTime = fr.time_sec;
          var useBtn = el.querySelector('.use-keyframe-btn');
          if (useBtn) useBtn.style.display = '';
          safeAutoSave();
        });
      }
    }
  );

  // 注册到全局
  window.createExtractFrameNode = createExtractFrameNode;
  window.createExtractFrameNodeWithData = createExtractFrameNodeWithData;

  // 注册到节点注册表
  registerNodeType('extract_frame', {
    createFn: createExtractFrameNode,
    createWithDataFn: createExtractFrameNodeWithData
  });

})();
