// ============================
// video_watermark_node.js - 视频去水印节点
// 输入：视频节点（state.connections）
// 输出：提交后在右侧新建视频节点，project_id 交给工作流 poll-status 回填成片
// 时长只接受 4-10 秒，算力与 MiniMax H3 720P 同一张表（任务类型 49）
// ============================

(function() {

  var WATERMARK_DURATIONS = [4, 5, 6, 7, 8, 9, 10];
  var WATERMARK_TASK_ID = 49;
  var FALLBACK_POWER = { 4: 5, 5: 6, 6: 8, 7: 9, 8: 10, 9: 11, 10: 13 };
  var MAX_PROMPT_CHARS = 2000;
  var DEFAULT_FPS = 24;

  var PORTS = [
    { direction: 'input', titleI18nKey: 'video_watermark_input_port', acceptType: 'video', connectionType: 'connections' },
    { direction: 'output', titleI18nKey: 'video_watermark_output_port' }
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

  /**
   * 把源视频秒数收成去水印可选时长。
   * 读不到时长时 duration 为 null，交给用户在 4-10 里选。
   * 读到了但不在表内时 outOfRange，禁止提交，避免接口回退到表内第一档少扣算力。
   */
  function resolveWatermarkDuration(sourceSeconds) {
    var rounded = null;
    var num = Number(sourceSeconds);
    if (sourceSeconds != null && sourceSeconds !== '' && isFinite(num) && num > 0) {
      rounded = Math.round(num);
    }
    var known = rounded != null;
    var inRange = known && WATERMARK_DURATIONS.indexOf(rounded) !== -1;
    return {
      sourceDuration: rounded,
      outOfRange: known && !inRange,
      duration: inRange ? rounded : null,
      canSubmit: !known || inRange
    };
  }

  function lookupWatermarkPower(durationSeconds, config) {
    var table = null;
    if (config) {
      table = config[String(WATERMARK_TASK_ID)] || config[WATERMARK_TASK_ID] || null;
    }
    var value = null;
    if (table) {
      value = table[String(durationSeconds)];
      if (value == null) value = table[durationSeconds];
    }
    if (value == null) value = FALLBACK_POWER[durationSeconds];
    return value == null ? null : value;
  }

  function isUsableVideoUrl(url) {
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

  function createVideoWatermarkNode(opts) {
    return createNodeBase({
      type: 'video_watermark',
      cssClass: 'video-watermark-node',
      title: function() { return textOf('video_watermark_title', '去水印'); },
      defaultData: {
        videoUrl: '',
        videoName: '',
        sourceNodeId: null,
        sourceDuration: null,
        durationOutOfRange: false,
        durationUserSet: false,
        duration: 5,
        prompt: '',
        status: 'idle',
        statusMessage: '',
        lastProjectId: null
      },
      ports: PORTS,
      width: 300,
      height: 320,
      titleIcon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M4 16l6-6 4 4-6 6H4v-4z"/><path d="M14 6l4 4"/><path d="M4 20h16"/></svg>',
      bodyHtml: function() {
        var options = WATERMARK_DURATIONS.map(function(sec) {
          return '<option value="' + sec + '">' + sec + '</option>';
        }).join('');
        return '<div class="field field-always-visible video-preview-field" style="display:none;">' +
            '<div class="label" data-i18n="video_watermark_preview">预览</div>' +
            '<div class="video-preview"><video class="video-thumb" playsinline muted></video></div>' +
            '<div class="gen-meta video-name"></div>' +
          '</div>' +
          '<div class="field field-always-visible">' +
            '<div class="label" data-i18n="video_watermark_duration">时长（秒）</div>' +
            '<select class="source-select watermark-duration">' + options + '</select>' +
            '<div class="gen-meta duration-hint"></div>' +
          '</div>' +
          '<div class="field field-always-visible">' +
            '<div class="label" data-i18n="video_watermark_power_label">算力</div>' +
            '<div class="gen-meta computing-power-value"></div>' +
          '</div>' +
          '<div class="field field-always-visible">' +
            '<div class="label" data-i18n="video_watermark_prompt">提示词（可选）</div>' +
            '<textarea class="watermark-prompt" rows="3" maxlength="2000" data-i18n="video_watermark_prompt_placeholder:placeholder" placeholder="留空使用默认去水印提示词"></textarea>' +
          '</div>' +
          '<div class="field field-always-visible">' +
            '<button class="gen-btn watermark-submit-btn" type="button" data-i18n="video_watermark_btn">去除水印</button>' +
          '</div>' +
          '<div class="field field-always-visible status-field" style="display:none;">' +
            '<div class="gen-meta status"></div>' +
          '</div>';
      },
      onCreated: function(node, el) {
        var previewField = el.querySelector('.video-preview-field');
        var thumbVideo = el.querySelector('.video-thumb');
        var nameEl = el.querySelector('.video-name');
        var durationSelect = el.querySelector('.watermark-duration');
        var hintEl = el.querySelector('.duration-hint');
        var powerEl = el.querySelector('.computing-power-value');
        var promptEl = el.querySelector('.watermark-prompt');
        var submitBtn = el.querySelector('.watermark-submit-btn');
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

        function refreshPower() {
          if (node.data.durationOutOfRange) {
            powerEl.textContent = textOf('video_watermark_duration_range', '仅支持 4–10 秒');
            return;
          }
          var seconds = Number(durationSelect.value);
          var config = typeof getTaskComputingPowerConfig === 'function' ? getTaskComputingPowerConfig() : null;
          var power = lookupWatermarkPower(seconds, config);
          powerEl.textContent = power == null
            ? ''
            : textOf('video_watermark_power', '预计消耗 {power} 算力', { power: power });
        }

        function refreshHint() {
          hintEl.classList.toggle('is-error', !!node.data.durationOutOfRange);
          if (node.data.durationOutOfRange) {
            hintEl.textContent = textOf('video_watermark_duration_range', '仅支持 4–10 秒');
            return;
          }
          if (node.data.sourceDuration != null) {
            hintEl.textContent = textOf('video_watermark_duration_detected', '已按视频时长 {seconds} 秒选择，可修改', {
              seconds: node.data.sourceDuration
            });
            return;
          }
          hintEl.textContent = textOf('video_watermark_duration_unknown', '未能读取时长，请选择 4–10 秒');
        }

        function refreshSubmitEnabled() {
          var busy = node.data.status === 'submitting';
          submitBtn.disabled = busy || !!node.data.durationOutOfRange;
          if (!busy) {
            submitBtn.textContent = textOf('video_watermark_btn', '去除水印');
          }
        }

        node.refreshPower = function() {
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
            var keepChoice = node.data.durationUserSet ? Number(node.data.duration) : null;
            node.applyDetectedDuration(thumbVideo.duration);
            if (keepChoice != null && !node.data.durationOutOfRange && WATERMARK_DURATIONS.indexOf(keepChoice) !== -1) {
              node.data.duration = keepChoice;
              durationSelect.value = String(keepChoice);
              refreshPower();
            }
          };
          try { thumbVideo.load(); } catch (e) {}
          previewField.style.display = '';
          nameEl.textContent = name || '';
        };

        node.applyDetectedDuration = function(sourceSeconds) {
          var resolved = resolveWatermarkDuration(sourceSeconds);
          node.data.sourceDuration = resolved.sourceDuration;
          node.data.durationOutOfRange = resolved.outOfRange;
          if (resolved.duration != null && !node.data.durationUserSet) {
            node.data.duration = resolved.duration;
            durationSelect.value = String(resolved.duration);
          }
          durationSelect.disabled = resolved.outOfRange;
          refreshPower();
          refreshHint();
          refreshSubmitEnabled();
        };

        node.applyVideoSource = function(fromNode) {
          node.data.durationUserSet = false;
          node.data.sourceNodeId = fromNode ? fromNode.id : null;
          var url = (fromNode && fromNode.data && fromNode.data.url) || '';
          var name = (fromNode && fromNode.data && fromNode.data.name) || '';
          node.showVideoPreview(url, name);
          var known = fromNode && fromNode.data ? fromNode.data.duration : null;
          if (known != null && known !== '' && isFinite(Number(known)) && Number(known) > 0) {
            node.applyDetectedDuration(known);
          } else if (!url) {
            node.applyDetectedDuration(null);
          } else {
            node.data.sourceDuration = null;
            node.data.durationOutOfRange = false;
            durationSelect.disabled = false;
            refreshHint();
            refreshSubmitEnabled();
          }
        };

        node.clearVideoInput = function(opts) {
          node.data.videoUrl = '';
          node.data.videoName = '';
          node.data.sourceNodeId = null;
          node.data.sourceDuration = null;
          node.data.durationOutOfRange = false;
          node.data.durationUserSet = false;
          durationSelect.disabled = false;
          node.showVideoPreview('', '');
          refreshHint();
          refreshPower();
          refreshSubmitEnabled();
          if (!opts || !opts.skipSave) safeAutoSave();
        };

        function findConnectedVideo() {
          var conn = state.connections.find(function(c) { return c.to === node.id; });
          if (!conn) return null;
          var fromNode = state.nodes.find(function(n) { return n.id === conn.from && n.type === 'video'; });
          return fromNode || null;
        }

        bindInputPortEvents(el, node, {
          acceptType: 'video',
          connectionType: 'connections',
          single: true,
          occupiedToastKey: 'video_watermark_one_video',
          onConnect: function(fromNode) {
            node.applyVideoSource(fromNode);
          }
        });

        durationSelect.addEventListener('change', function() {
          var seconds = Number(durationSelect.value);
          if (WATERMARK_DURATIONS.indexOf(seconds) === -1) return;
          node.data.duration = seconds;
          node.data.durationUserSet = true;
          refreshPower();
          safeAutoSave();
        });

        promptEl.addEventListener('input', function() {
          node.data.prompt = promptEl.value;
          safeAutoSave();
        });

        submitBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          submitWatermark();
        });

        async function submitWatermark() {
          if (node.data.status === 'submitting') return;
          var source = findConnectedVideo();
          if (!source) {
            showToast(textOf('video_watermark_no_video', '请先连接视频节点'), 'error');
            return;
          }
          var url = (source.data && source.data.url) || '';
          if (source.data && source.data.project_id && !url) {
            showToast(textOf('video_watermark_generating', '视频还在生成，请等成片后再去水印'), 'warning');
            return;
          }
          if (typeof url === 'string' && url.indexOf('blob:') === 0) {
            showToast(textOf('video_watermark_uploading', '视频还在上传，请稍候'), 'warning');
            return;
          }
          if (!isUsableVideoUrl(url)) {
            showToast(textOf('video_watermark_bad_url', '请使用已上传到服务器的视频'), 'error');
            return;
          }

          var sourceSeconds = (source.data && source.data.duration != null && source.data.duration !== '')
            ? source.data.duration
            : node.data.sourceDuration;
          var resolved = resolveWatermarkDuration(sourceSeconds);
          if (resolved.outOfRange) {
            node.applyDetectedDuration(sourceSeconds);
            showToast(textOf('video_watermark_duration_range', '仅支持 4–10 秒'), 'error');
            return;
          }
          var duration = Number(durationSelect.value);
          if (WATERMARK_DURATIONS.indexOf(duration) === -1) {
            showToast(textOf('video_watermark_duration_range', '仅支持 4–10 秒'), 'error');
            return;
          }

          var prompt = (promptEl.value || '').trim();
          if (prompt.length > MAX_PROMPT_CHARS) {
            showToast(textOf('video_watermark_prompt_too_long', '提示词不能超过 2000 字'), 'error');
            return;
          }

          node.data.videoUrl = url;
          node.data.videoName = (source.data && source.data.name) || node.data.videoName || '';
          node.data.duration = duration;
          node.data.prompt = prompt;
          node.data.status = 'submitting';
          node.data.statusMessage = '';
          setBtnLoading(submitBtn, textOf('video_watermark_submitting', '提交中...'));
          showStatus(textOf('video_watermark_submitting', '提交中...'), '');

          try {
            var formData = new FormData();
            formData.append('video_url', url);
            formData.append('duration_seconds', String(duration));
            formData.append('fps', String(DEFAULT_FPS));
            if (prompt) formData.append('prompt', prompt);
            if (typeof appendAuthToForm === 'function') appendAuthToForm(formData);

            var token = typeof getAuthToken === 'function' ? getAuthToken() : '';
            var response = await fetch('/api/video-watermark-remove', {
              method: 'POST',
              headers: token ? { 'Authorization': 'Bearer ' + token } : {},
              body: formData
            });
            var result = null;
            try { result = await response.json(); } catch (parseErr) { result = null; }

            if (!response.ok || !result || result.success !== true || !result.project_id) {
              var message = readErrorDetail(result) || textOf('video_watermark_failed', '去水印提交失败');
              if (response.status === 401) {
                message = textOf('video_watermark_login', '请先登录');
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
            showStatus(textOf('video_watermark_submitted', '已提交，结果视频生成中'), '#22c55e');
            createResultVideoNode(result.project_id);
            showToast(textOf('video_watermark_success', '已提交去水印，结果将出现在新的视频节点'), 'success');
          } catch (error) {
            console.error('视频去水印提交失败:', error);
            node.data.status = 'error';
            node.data.statusMessage = textOf('video_watermark_network', '网络错误，请稍后重试');
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
              setStatusEl(videoStatusEl, textOf('video_watermark_result_generating', '生成中...'));
            }
          }
          renderAllConnections();
          renderMinimap();
          safeAutoSave();
        }

        durationSelect.value = '5';
        node.refreshPower();
      }
    }, opts);
  }

  function restoreVideoWatermarkDom(el, node) {
    var promptEl = el.querySelector('.watermark-prompt');
    if (promptEl) promptEl.value = node.data.prompt || '';

    var savedDuration = Number(node.data.duration);
    if (typeof node.applyDetectedDuration === 'function') {
      node.applyDetectedDuration(node.data.sourceDuration);
    }
    var durationSelect = el.querySelector('.watermark-duration');
    if (!node.data.durationOutOfRange && durationSelect && WATERMARK_DURATIONS.indexOf(savedDuration) !== -1) {
      node.data.duration = savedDuration;
      durationSelect.value = String(savedDuration);
    }
    if (typeof node.refreshPower === 'function') node.refreshPower();

    if (node.data.videoUrl && typeof node.showVideoPreview === 'function') {
      node.showVideoPreview(node.data.videoUrl, node.data.videoName || '');
    }

    var statusField = el.querySelector('.status-field');
    var statusEl = el.querySelector('.status');
    if (node.data.status === 'error' && node.data.statusMessage) {
      statusField.style.display = '';
      setStatusEl(statusEl, node.data.statusMessage, '#ef4444');
    } else if (node.data.status === 'submitted') {
      statusField.style.display = '';
      setStatusEl(statusEl, textOf('video_watermark_submitted', '已提交，结果视频生成中'), '#22c55e');
    }
  }

  var createVideoWatermarkNodeWithData = typeof createNodeWithDataFactory === 'function'
    ? createNodeWithDataFactory(createVideoWatermarkNode, restoreVideoWatermarkDom)
    : null;

  if (typeof registerInputPorts === 'function') {
    registerInputPorts('video_watermark', [{
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
    }]);
  }

  function refreshVideoWatermarkNodesPower() {
    if (typeof state === 'undefined' || !state || !state.nodes) return;
    state.nodes.forEach(function(n) {
      if (n.type === 'video_watermark' && typeof n.refreshPower === 'function') n.refreshPower();
    });
  }

  if (typeof window !== 'undefined') {
    window.createVideoWatermarkNode = createVideoWatermarkNode;
    window.createVideoWatermarkNodeWithData = createVideoWatermarkNodeWithData;
    window.refreshVideoWatermarkNodesPower = refreshVideoWatermarkNodesPower;
  }

  if (typeof registerNodeType === 'function') {
    registerNodeType('video_watermark', {
      createFn: createVideoWatermarkNode,
      createWithDataFn: createVideoWatermarkNodeWithData
    });
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      resolveWatermarkDuration: resolveWatermarkDuration,
      lookupWatermarkPower: lookupWatermarkPower,
      isUsableVideoUrl: isUsableVideoUrl,
      readErrorDetail: readErrorDetail,
      WATERMARK_DURATIONS: WATERMARK_DURATIONS,
      WATERMARK_TASK_ID: WATERMARK_TASK_ID,
      FALLBACK_POWER: FALLBACK_POWER
    };
  }

})();
