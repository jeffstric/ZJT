// ============================
// video_edit_node.js - 视频编辑节点（视频人物替换，任务类型 54）
// 输入：视频节点（参考视频，single）+ 图片节点（角色参考图 1-9 张，多连）
// 输出：提交后在右侧新建视频节点，project_id 交给工作流 poll-status 回填成片
// 时长 5-25 秒（缺省跟随参考视频），算力表 VIDEO_CHARACTER_REPLACE_COMPUTING_POWER
// 定价基准：autodl 高峰实测 0.132 元/秒（2026-11-18），ceil(秒×3.3)
// ============================

(function() {

  var EDIT_DURATIONS = [];
  for (var d = 5; d <= 25; d++) EDIT_DURATIONS.push(d);
  var EDIT_TASK_ID = 54;
  // 与 config/unified_config.py VIDEO_CHARACTER_REPLACE_COMPUTING_POWER 保持一致（task-configs 拉取失败时的兜底）
  var FALLBACK_POWER = {
    5: 17, 6: 20, 7: 24, 8: 27, 9: 30, 10: 33,
    11: 37, 12: 40, 13: 43, 14: 47, 15: 50,
    16: 53, 17: 57, 18: 60, 19: 63, 20: 66,
    21: 70, 22: 73, 23: 76, 24: 80, 25: 83
  };
  var MAX_PROMPT_CHARS = 2048;
  var MAX_REF_IMAGES = 9;

  var PORTS = [
    { direction: 'input', titleI18nKey: 'video_edit_input_port', acceptType: 'video', connectionType: 'connections' },
    // cssClass 必须为 {portType}-image-port：CONNECTION_TYPES.image.toPortSelector
    // 按该模板解析落点端口（portType='video-edit' → '.video-edit-image-port'），
    // 不匹配则连线渲染找不到端口（首版 'image-in' 的翻车原因）
    { direction: 'input', titleI18nKey: 'video_edit_images_port', acceptType: 'image', connectionType: 'imageConnections', cssClass: 'video-edit-image-port' },
    { direction: 'output', titleI18nKey: 'video_edit_output_port' }
  ];

  function textOf(key, fallback, params) {
    if (typeof window !== 'undefined' && typeof window.t === 'function') {
      var translated = window.t(key, params || {});
      if (translated && translated !== key) return translated;
    }
    if (!fallback) return key;
    if (!params) return fallback;
    return fallback.replace(/\{(\w+)\}/g, function(_m, name) {
      return params[name] !== undefined ? params[name] : _m;
    });
  }

  /** 输出时长吸附：向上取整钳 5-25（语义=成片取参考视频前 N 秒，用户可改） */
  function resolveEditDuration(sourceSeconds) {
    var num = Number(sourceSeconds);
    if (sourceSeconds == null || sourceSeconds === '' || !isFinite(num) || num <= 0) return null;
    return Math.max(5, Math.min(25, Math.ceil(num)));
  }

  function lookupEditPower(durationSeconds, config) {
    var table = null;
    if (config) {
      table = config[String(EDIT_TASK_ID)] || config[EDIT_TASK_ID] || null;
    }
    var value = null;
    if (table) {
      value = table[String(durationSeconds)];
      if (value == null) value = table[durationSeconds];
    }
    if (value == null) value = FALLBACK_POWER[durationSeconds];
    return value == null ? null : value;
  }

  function isUsableMediaUrl(url) {
    if (!url || typeof url !== 'string') return false;
    if (url.indexOf('blob:') === 0 || url.indexOf('data:') === 0) return false;
    return url.charAt(0) === '/' || url.indexOf('http://') === 0 || url.indexOf('https://') === 0;
  }

  function readErrorDetail(result) {
    if (!result) return '';
    if (typeof result.detail === 'string') return result.detail;
    if (Array.isArray(result.detail)) {
      return result.detail.map(function(item) {
        if (!item) return '';
        if (typeof item === 'string') return item;
        return item.msg || item.message || '';
      }).filter(Boolean).join('；');
    }
    if (typeof result.message === 'string') return result.message;
    if (typeof result.error === 'string') return result.error;
    return '';
  }

  function createVideoEditNode(opts) {
    return createNodeBase({
      type: 'video_edit',
      cssClass: 'video-edit-node',
      title: function() { return textOf('video_edit_title', '视频人物替换'); },
      defaultData: {
        videoUrl: '',
        videoName: '',
        sourceNodeId: null,
        sourceDuration: null,
        durationUserSet: false,
        duration: null,
        prompt: '',
        status: 'idle',
        statusMessage: '',
        lastProjectId: null
      },
      ports: PORTS,
      width: 300,
      height: 340,
      titleIcon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><circle cx="12" cy="8" r="3"/><path d="M6 21c0-3.3 2.7-6 6-6s6 2.7 6 6"/><path d="M3 3l18 18"/></svg>',
      bodyHtml: function() {
        var options = '<option value="">' + textOf('video_edit_duration_follow', '跟随视频') + '</option>' +
          EDIT_DURATIONS.map(function(sec) {
            return '<option value="' + sec + '">' + sec + '</option>';
          }).join('');
        return '<div class="field field-always-visible video-preview-field" style="display:none;">' +
            '<div class="label" data-i18n="video_edit_preview">参考视频</div>' +
            '<div class="video-preview" style="position: relative;">' +
              '<video class="video-thumb" playsinline muted></video>' +
              '<button class="edit-video-remove-btn" type="button" title="更换视频" data-i18n="video_edit_clear_video:title">×</button>' +
            '</div>' +
            '<div class="gen-meta video-name"></div>' +
          '</div>' +
          '<div class="field field-always-visible">' +
            '<div class="label" data-i18n="video_edit_images_label">角色参考图（1-9 张）</div>' +
            '<div class="edit-images-thumbs"></div>' +
            '<div class="gen-meta images-hint"></div>' +
          '</div>' +
          '<div class="field field-always-visible">' +
            '<div class="label" data-i18n="video_edit_duration">输出时长（秒）</div>' +
            '<select class="source-select edit-duration">' + options + '</select>' +
            '<div class="gen-meta duration-hint"></div>' +
          '</div>' +
          '<div class="field field-always-visible">' +
            '<div class="label" data-i18n="video_edit_power_label">算力</div>' +
            '<div class="gen-meta computing-power-value"></div>' +
          '</div>' +
          '<div class="field field-always-visible">' +
            '<div class="label" data-i18n="video_edit_prompt">替换说明（可选）</div>' +
            '<textarea class="edit-prompt" rows="3" maxlength="2048" data-i18n="video_edit_prompt_placeholder:placeholder" placeholder="把视频中的女人替换为图片中的女人"></textarea>' +
          '</div>' +
          '<div class="field field-always-visible">' +
            '<button class="gen-btn edit-submit-btn" type="button" data-i18n="video_edit_btn">开始替换</button>' +
          '</div>' +
          '<div class="field field-always-visible status-field" style="display:none;">' +
            '<div class="gen-meta status"></div>' +
          '</div>';
      },
      onCreated: function(node, el) {
        var previewField = el.querySelector('.video-preview-field');
        var thumbVideo = el.querySelector('.video-thumb');
        var nameEl = el.querySelector('.video-name');
        var imagesListEl = el.querySelector('.edit-images-thumbs');
        var imagesHintEl = el.querySelector('.images-hint');
        var durationSelect = el.querySelector('.edit-duration');
        var hintEl = el.querySelector('.duration-hint');
        var powerEl = el.querySelector('.computing-power-value');
        var promptEl = el.querySelector('.edit-prompt');
        var submitBtn = el.querySelector('.edit-submit-btn');
        var statusField = el.querySelector('.status-field');
        var statusEl = el.querySelector('.status');

        function showStatus(message, color) {
          if (!message) {
            statusField.style.display = 'none';
            statusEl.textContent = '';
            return;
          }
          statusField.style.display = '';
          setStatusEl(statusEl, message, color || '');
        }

        function findConnectedVideo() {
          var conn = state.connections.find(function(c) { return c.to === node.id; });
          if (!conn) return null;
          var fromNode = state.nodes.find(function(n) { return n.id === conn.from && n.type === 'video'; });
          return fromNode || null;
        }

        /**
         * 已连接的参考图列表：[{ node, connId }]（imageConnections 顺序 = 图 1..N，
         * 与上游"图 N 替换视频里第 N 个角色"口径一致）
         */
        function findConnectedImages() {
          return state.imageConnections
            .filter(function(c) { return c.to === node.id; })
            .map(function(c) {
              var imgNode = state.nodes.find(function(n) { return n.id === c.from && n.type === 'image'; });
              return imgNode ? { node: imgNode, connId: c.id } : null;
            })
            .filter(Boolean);
        }

        /** 参考图缩略预览（口径同图生视频节点 renderReferencePreview）：50x50 缩略 + 图N 角标 + × 删连接 */
        function renderImageThumbs() {
          imagesListEl.innerHTML = '';
          var images = findConnectedImages();
          if (!images.length) {
            var empty = document.createElement('div');
            empty.className = 'gen-meta';
            empty.textContent = textOf('video_edit_images_none', '未连接参考图');
            imagesListEl.appendChild(empty);
            return;
          }
          images.forEach(function(img, idx) {
            var url = (img.node.data && img.node.data.url) || '';
            var item = document.createElement('div');
            item.style.cssText = 'position: relative; width: 50px; height: 50px; display: inline-block; margin: 0 6px 6px 0;';
            var safeUrl = typeof escapeHtml === 'function' ? escapeHtml(url) : url;
            item.innerHTML =
              '<img src="' + safeUrl + '" style="width: 100%; height: 100%; object-fit: cover; border-radius: 4px; cursor: pointer;" />' +
              '<div style="position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.6); color: white; font-size: 10px; text-align: center; border-radius: 0 0 4px 4px; padding: 1px 0;">图' + (idx + 1) + '</div>' +
              '<button class="edit-ref-remove-btn" data-conn-id="' + img.connId + '" style="position: absolute; top: -4px; right: -4px; width: 16px; height: 16px; border-radius: 50%; background: #ef4444; border: none; color: white; font-size: 10px; cursor: pointer; line-height: 1;">×</button>';
            item.querySelector('img').addEventListener('click', function(e) {
              e.stopPropagation();
              if (typeof openImageModal === 'function') openImageModal(url, textOf('video_edit_image_unnamed', '图片') + (idx + 1));
            });
            item.querySelector('.edit-ref-remove-btn').addEventListener('click', function(e) {
              e.stopPropagation();
              // 删对应连接线并重渲染（口径同 i2v 参考图删除）
              var connId = Number(this.getAttribute('data-conn-id'));
              state.imageConnections = state.imageConnections.filter(function(c) {
                return !(c.to === node.id && c.id === connId);
              });
              if (typeof renderImageConnections === 'function') renderImageConnections();
              node.refreshPower();
              safeAutoSave();
            });
            imagesListEl.appendChild(item);
          });
        }

        function refreshImagesHint() {
          var images = findConnectedImages();
          var broken = images.filter(function(item) {
            var url = (item.node.data && item.node.data.url) || '';
            return !isUsableMediaUrl(url);
          });
          if (images.some(function(item) { return item.node.data && item.node.data.project_id && !(item.node.data && item.node.data.url); })) {
            imagesHintEl.textContent = textOf('video_edit_image_generating', '有参考图还在生成，请等成片后再提交');
            imagesHintEl.classList.add('is-error');
            return;
          }
          if (broken.length) {
            imagesHintEl.textContent = textOf('video_edit_image_not_ready', '有参考图还未上传到服务器');
            imagesHintEl.classList.add('is-error');
            return;
          }
          imagesHintEl.classList.remove('is-error');
          if (images.length) {
            imagesHintEl.textContent = textOf('video_edit_images_count', '已连接 {count} 张，图 N 替换视频里第 N 个角色', { count: images.length });
          } else {
            imagesHintEl.textContent = textOf('video_edit_images_hint', '从画布连接 1-9 张图片节点');
          }
        }

        function refreshPower() {
          renderImageThumbs();
          var seconds = durationSelect.value ? Number(durationSelect.value) : null;
          if (seconds == null) {
            var source = findConnectedVideo();
            var sourceSeconds = (source && source.data && source.data.duration != null && source.data.duration !== '')
              ? source.data.duration
              : node.data.sourceDuration;
            seconds = resolveEditDuration(sourceSeconds);
          }
          var config = typeof getTaskComputingPowerConfig === 'function' ? getTaskComputingPowerConfig() : null;
          var power = seconds != null ? lookupEditPower(seconds, config) : null;
          powerEl.textContent = (power == null)
            ? textOf('video_edit_power_unknown', '连接视频后按时长估算')
            : textOf('video_edit_power', '预计消耗 {power} 算力', { power: power });
        }

        function refreshHint() {
          if (node.data.sourceDuration != null) {
            hintEl.textContent = textOf('video_edit_duration_detected', '参考视频 {seconds} 秒，成片取前 N 秒，可修改', {
              seconds: node.data.sourceDuration
            });
          } else {
            hintEl.textContent = textOf('video_edit_duration_unknown', '未读取到视频时长，请选择 5–25 秒');
          }
        }

        function refreshSubmitEnabled() {
          var busy = node.data.status === 'submitting';
          submitBtn.disabled = busy;
          if (!busy) {
            submitBtn.textContent = textOf('video_edit_btn', '开始替换');
          }
        }

        // 「已提交」提示定时淡出：结果状态由下游视频节点展示（口径同去水印节点）
        function fadeOutSubmittedHint() {
          setTimeout(function() {
            if (node.data.status !== 'submitted') return;
            var field = el.querySelector('.status-field');
            var hintEl2 = el.querySelector('.status');
            if (field && hintEl2) {
              field.style.display = 'none';
              hintEl2.textContent = '';
            }
          }, 30000);
        }

        node.refreshPower = function() {
          refreshImagesHint();
          refreshPower();
          refreshHint();
          refreshSubmitEnabled();
        };

        node.showVideoPreview = function(url, name) {
          node.data.videoUrl = url || '';
          node.data.videoName = name || '';
          if (!url) {
            previewField.style.display = 'none';
            nameEl.textContent = '';
            try { thumbVideo.removeAttribute('src'); thumbVideo.load(); } catch (e) {}
            return;
          }
          setupVideoThumbnail(thumbVideo, url);
          var coverHandler = thumbVideo.onloadedmetadata;
          thumbVideo.onloadedmetadata = function() {
            if (typeof coverHandler === 'function') coverHandler();
            if (!isFinite(thumbVideo.duration) || thumbVideo.duration <= 0) return;
            node.applyDetectedDuration(thumbVideo.duration);
          };
          try { thumbVideo.load(); } catch (e) {}
          previewField.style.display = '';
          nameEl.textContent = name || '';
        };

        node.applyDetectedDuration = function(sourceSeconds) {
          var num = Number(sourceSeconds);
          node.data.sourceDuration = (sourceSeconds != null && sourceSeconds !== '' && isFinite(num) && num > 0)
            ? Math.round(num) : null;
          // 未手动选过时长时自动吸附视频时长（钳 5-25；视频超出 25s 取前 25 秒是合法用法）
          if (!node.data.durationUserSet) {
            var resolved = resolveEditDuration(node.data.sourceDuration);
            node.data.duration = resolved;
            durationSelect.value = resolved != null ? String(resolved) : '';
          }
          refreshPower();
          refreshHint();
        };

        node.applyVideoSource = function(fromNode) {
          node.data.durationUserSet = false;
          node.data.sourceNodeId = fromNode ? fromNode.id : null;
          var url = (fromNode && fromNode.data && fromNode.data.url) || '';
          var name = (fromNode && fromNode.data && fromNode.data.name) || '';
          node.showVideoPreview(url, name);
          var known = fromNode && fromNode.data ? fromNode.data.duration : null;
          node.applyDetectedDuration(known != null ? known : null);
        };

        node.clearVideoInput = function(opts) {
          node.data.videoUrl = '';
          node.data.videoName = '';
          node.data.sourceNodeId = null;
          node.data.sourceDuration = null;
          node.data.durationUserSet = false;
          node.showVideoPreview('', '');
          node.applyDetectedDuration(null);
          if (!opts || !opts.skipSave) safeAutoSave();
        };

        // 「换视频」按钮：删除视频连接线 + 清除输入（清除后即可直连新视频）
        var removeVideoBtn = el.querySelector('.edit-video-remove-btn');
        if (removeVideoBtn) {
          removeVideoBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            var conn = state.connections.find(function(c) { return c.to === node.id; });
            if (conn) {
              state.connections = state.connections.filter(function(c) { return c.to !== node.id; });
              if (typeof renderAllConnections === 'function') renderAllConnections();
              if (typeof renderMinimap === 'function') renderMinimap();
            }
            node.clearVideoInput();
            showToast(textOf('video_edit_video_cleared', '已移除视频，可连接新的视频'), 'success');
          });
        }

        bindInputPortEvents(el, node, {
          acceptType: 'video',
          connectionType: 'connections',
          single: true,
          occupiedToastKey: 'video_edit_one_video',  // 文案已含引导：点预览右上角 × 更换
          onConnect: function(fromNode) {
            node.applyVideoSource(fromNode);
          }
        });

        // 图片口：多连（single 不传），上限 9 在 onConnect 里校验——
        // bindInputPortEvents 先 push 连接再回调，超限时回调内自行移除刚建的连接
        bindInputPortEvents(el, node, {
          cssClass: 'video-edit-image-port',
          // portType 在连接创建时即写入（node_base 通用增强，渲染先于 onConnect），
          // 缺失时首次渲染找不到落点端口，连线要等下一次鼠标操作才出现
          portType: 'video-edit',
          acceptType: 'image',
          connectionType: 'imageConnections',
          onConnect: function(fromNode, conn) {
            // 兜底：portType 缺失时补上（正常路径已由 portCfg.portType 写入）
            if (conn && !conn.portType) conn.portType = 'video-edit';
            var count = state.imageConnections.filter(function(c) { return c.to === node.id; }).length;
            if (count > MAX_REF_IMAGES) {
              var idx = state.imageConnections.indexOf(conn);
              if (idx !== -1) state.imageConnections.splice(idx, 1);
              if (typeof renderImageConnections === 'function') renderImageConnections();
              showToast(textOf('video_edit_max_images', '角色参考图最多 9 张'), 'warning');
            }
            node.refreshPower();
            safeAutoSave();
          }
        });

        durationSelect.addEventListener('change', function() {
          node.data.durationUserSet = true;
          node.data.duration = durationSelect.value ? Number(durationSelect.value) : null;
          refreshPower();
          safeAutoSave();
        });

        promptEl.addEventListener('input', function() {
          node.data.prompt = promptEl.value;
          safeAutoSave();
        });

        submitBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          submitEdit();
        });

        async function submitEdit() {
          if (node.data.status === 'submitting') return;
          var source = findConnectedVideo();
          if (!source) {
            showToast(textOf('video_edit_no_video', '请先连接视频节点'), 'error');
            return;
          }
          var url = (source.data && source.data.url) || '';
          if (source.data && source.data.project_id && !url) {
            showToast(textOf('video_edit_generating', '视频还在生成，请等成片后再替换'), 'warning');
            return;
          }
          if (typeof url === 'string' && url.indexOf('blob:') === 0) {
            showToast(textOf('video_edit_uploading', '视频还在上传，请稍候'), 'warning');
            return;
          }
          if (!isUsableMediaUrl(url)) {
            showToast(textOf('video_edit_bad_url', '请使用已上传到服务器的视频'), 'error');
            return;
          }

          var images = findConnectedImages();
          if (!images.length) {
            showToast(textOf('video_edit_need_images', '请连接至少 1 张角色参考图'), 'error');
            return;
          }
          if (images.length > MAX_REF_IMAGES) {
            showToast(textOf('video_edit_max_images', '角色参考图最多 9 张'), 'error');
            return;
          }
          var imageUrls = [];
          for (var i = 0; i < images.length; i++) {
            var imgUrl = (images[i].node.data && images[i].node.data.url) || '';
            if (typeof imgUrl === 'string' && imgUrl.indexOf('blob:') === 0) {
              showToast(textOf('video_edit_image_uploading', '参考图还在上传，请稍候'), 'warning');
              return;
            }
            if (!isUsableMediaUrl(imgUrl)) {
              showToast(textOf('video_edit_image_not_ready', '有参考图还未上传到服务器'), 'error');
              return;
            }
            imageUrls.push(imgUrl);
          }

          var duration = durationSelect.value ? Number(durationSelect.value) : null;
          if (duration != null && EDIT_DURATIONS.indexOf(duration) === -1) {
            showToast(textOf('video_edit_duration_range', '输出时长仅支持 5–25 秒'), 'error');
            return;
          }

          var prompt = (promptEl.value || '').trim();
          if (prompt.length > MAX_PROMPT_CHARS) {
            showToast(textOf('video_edit_prompt_too_long', '替换说明不能超过 2048 字'), 'error');
            return;
          }

          node.data.videoUrl = url;
          node.data.videoName = (source.data && source.data.name) || node.data.videoName || '';
          node.data.duration = duration;
          node.data.prompt = prompt;
          node.data.status = 'submitting';
          node.data.statusMessage = '';
          setBtnLoading(submitBtn, textOf('video_edit_submitting', '提交中...'));
          showStatus(textOf('video_edit_submitting', '提交中...'), '');

          try {
            var formData = new FormData();
            formData.append('video_url', url);
            formData.append('image_urls', JSON.stringify(imageUrls));
            if (duration != null) formData.append('duration_seconds', String(duration));
            if (prompt) formData.append('prompt', prompt);
            if (typeof appendAuthToForm === 'function') appendAuthToForm(formData);

            var token = typeof getAuthToken === 'function' ? getAuthToken() : '';
            var response = await fetch('/api/video-character-replace', {
              method: 'POST',
              headers: token ? { 'Authorization': 'Bearer ' + token } : {},
              body: formData
            });
            var result = null;
            try { result = await response.json(); } catch (parseErr) { result = null; }

            if (!response.ok || !result || result.success !== true || !result.project_id) {
              var message = readErrorDetail(result) || textOf('video_edit_failed', '人物替换提交失败');
              if (response.status === 401) {
                message = textOf('video_edit_login', '请先登录');
              }
              node.data.status = 'error';
              node.data.statusMessage = message;
              showStatus(message, '#ef4444');
              showToast(message, 'error');
              return;
            }

            node.data.status = 'submitted';
            node.data.statusMessage = '';
            node.data.lastProjectId = result.project_id;
            showStatus(textOf('video_edit_submitted', '已提交，结果视频生成中'), '#22c55e');
            fadeOutSubmittedHint();
            createResultVideoNode(result.project_id);
            showToast(textOf('video_edit_success', '已提交替换，结果将出现在新的视频节点'), 'success');
          } catch (error) {
            console.error('视频人物替换提交失败:', error);
            node.data.status = 'error';
            node.data.statusMessage = textOf('video_edit_network', '网络错误，请稍后重试');
            showStatus(node.data.statusMessage, '#ef4444');
            showToast(node.data.statusMessage, 'error');
          } finally {
            if (node.data.status === 'submitting') node.data.status = 'idle';
            refreshSubmitEnabled();
          }
        }

        function createResultVideoNode(projectId) {
          var sourceEl = canvasEl.querySelector('.node[data-node-id="' + node.id + '"]');
          var offsetX = (sourceEl ? sourceEl.offsetWidth : 300) + 60;
          var newVideoId = createVideoNode({ x: node.x + offsetX, y: node.y, checkCollision: true });
          state.connections.push({
            id: state.nextConnId++,
            from: node.id,
            to: newVideoId
          });
          var newVideoNode = state.nodes.find(function(n) { return n.id === newVideoId; });
          if (newVideoNode) {
            newVideoNode.data.project_id = projectId;
            if (window.AiToolTimeline) window.AiToolTimeline.markNodeGenerating(newVideoId);
          }
          var videoEl = canvasEl.querySelector('.node[data-node-id="' + newVideoId + '"]');
          if (videoEl) {
            var videoStatusField = videoEl.querySelector('.video-status-field');
            var videoStatusEl = videoEl.querySelector('.video-status');
            if (videoStatusField && videoStatusEl) {
              videoStatusField.style.display = 'block';
              setStatusEl(videoStatusEl, textOf('video_edit_result_generating', '生成中...'));
            }
          }
          renderAllConnections();
          renderMinimap();
          safeAutoSave();
        }

        node.refreshPower();
      }
    }, opts);
  }

  function restoreVideoEditDom(el, node) {
    var promptEl = el.querySelector('.edit-prompt');
    if (promptEl) promptEl.value = node.data.prompt || '';

    var durationSelect = el.querySelector('.edit-duration');
    // 红线4（工作流重载复原）：先恢复用户手选的时长，再按已保存的视频时长补自动吸附
    if (node.data.durationUserSet && node.data.duration != null &&
        EDIT_DURATIONS.indexOf(Number(node.data.duration)) !== -1 && durationSelect) {
      durationSelect.value = String(Number(node.data.duration));
    } else if (durationSelect) {
      durationSelect.value = '';
    }
    if (node.data.videoUrl && typeof node.showVideoPreview === 'function') {
      node.showVideoPreview(node.data.videoUrl, node.data.videoName || '');
      // 重载路径不走 applyVideoSource（连接由工作流恢复逻辑回放 onConnect），
      // 这里兜底恢复时长吸附依据
      if (node.data.sourceDuration != null) {
        node.applyDetectedDuration(node.data.sourceDuration);
        if (node.data.durationUserSet && node.data.duration != null &&
            EDIT_DURATIONS.indexOf(Number(node.data.duration)) !== -1 && durationSelect) {
          durationSelect.value = String(Number(node.data.duration));
        }
      }
    }

    if (typeof node.refreshPower === 'function') node.refreshPower();

    var statusField = el.querySelector('.status-field');
    var statusEl = el.querySelector('.status');
    if (node.data.status === 'submitting') {
      // 红线4（工作流重载复原）：提交在途关页时自动保存把 submitting 落了盘，
      // 重载后无法找回该次提交的 project_id，必须归一为 idle 并提示重新提交
      node.data.status = 'idle';
      node.data.statusMessage = '';
      if (statusField && statusEl) {
        statusField.style.display = '';
        setStatusEl(statusEl, textOf('video_edit_interrupted', '上次提交已中断，结果无法找回，请重新提交'), '#f59e0b');
      }
    } else if (node.data.status === 'error' && node.data.statusMessage) {
      statusField.style.display = '';
      setStatusEl(statusEl, node.data.statusMessage, '#ef4444');
    } else if (node.data.status === 'submitted') {
      statusField.style.display = '';
      setStatusEl(statusEl, textOf('video_edit_submitted', '已提交，结果视频生成中'), '#22c55e');
      setTimeout(function() {
        if (node.data.status !== 'submitted') return;
        statusField.style.display = 'none';
        statusEl.textContent = '';
      }, 30000);
    }
  }

  var createVideoEditNodeWithData = typeof createNodeWithDataFactory === 'function'
    ? createNodeWithDataFactory(createVideoEditNode, restoreVideoEditDom)
    : null;

  if (typeof registerInputPorts === 'function') {
    registerInputPorts('video_edit', [
      {
        selector: '.port.input',
        portType: 'video-in',
        accepts: ['video'],
        connectionType: 'connections',
        guard: function(targetNode) {
          return !state.connections.some(function(c) { return c.to === targetNode.id; });
        },
        onConnect: function(fromNode, targetNode) {
          if (targetNode && typeof targetNode.applyVideoSource === 'function') {
            targetNode.applyVideoSource(fromNode);
          }
        }
      },
      {
        selector: '.port.input.video-edit-image-port',
        portType: 'video-edit',
        accepts: ['image'],
        connectionType: 'imageConnections',
        allowMultiple: true,
        guard: function(targetNode) {
          var count = state.imageConnections.filter(function(c) { return c.to === targetNode.id; }).length;
          return count < MAX_REF_IMAGES;
        },
        onConnect: function(fromNode, targetNode) {
          var count = state.imageConnections.filter(function(c) { return c.to === targetNode.id; }).length;
          if (count > MAX_REF_IMAGES) {
            showToast(textOf('video_edit_max_images', '角色参考图最多 9 张'), 'warning');
          }
          if (targetNode && typeof targetNode.refreshPower === 'function') {
            targetNode.refreshPower();
          }
        }
      }
    ]);
  }

  function refreshVideoEditNodesPower() {
    if (typeof state === 'undefined' || !state || !state.nodes) return;
    state.nodes.forEach(function(n) {
      if (n.type === 'video_edit' && typeof n.refreshPower === 'function') n.refreshPower();
    });
  }

  if (typeof window !== 'undefined') {
    window.createVideoEditNode = createVideoEditNode;
    window.createVideoEditNodeWithData = createVideoEditNodeWithData;
    window.refreshVideoEditNodesPower = refreshVideoEditNodesPower;
  }

  if (typeof registerNodeType === 'function') {
    registerNodeType('video_edit', {
      createFn: createVideoEditNode,
      createWithDataFn: createVideoEditNodeWithData
    });
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      resolveEditDuration: resolveEditDuration,
      lookupEditPower: lookupEditPower,
      isUsableMediaUrl: isUsableMediaUrl,
      readErrorDetail: readErrorDetail,
      EDIT_DURATIONS: EDIT_DURATIONS,
      EDIT_TASK_ID: EDIT_TASK_ID,
      FALLBACK_POWER: FALLBACK_POWER,
      MAX_REF_IMAGES: MAX_REF_IMAGES
    };
  }

})();
