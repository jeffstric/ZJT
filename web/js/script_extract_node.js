// ============================
// script_extract_node.js - 剧本提取节点
// 输入视频（连线视频节点或本地上传）→ 后端异步任务（关键帧 + ASR + 多模态智能体）→ 文字剧本
// 结果可编辑，支持一键写入画布"剧本节点"接入下游拆分链路。
// ============================
(function() {
  'use strict';

  var SCRIPT_EXTRACT_PORTS = [
    { direction: 'input', titleI18nKey: 'script_extract_input_port', acceptType: 'video', connectionType: 'connections' }
  ];

  // 轮询间隔与上限：3s × 400 次 = 20 分钟（与后端 TASK_TTL_SECONDS=1800 对齐）
  var POLL_INTERVAL_MS = 3000;
  var POLL_MAX_ATTEMPTS = 400;

  function tr(key, fallback, params) {
    var v = window.t ? window.t(key, params) : null;
    return (v && v !== key) ? v : fallback;
  }

  function authHeaders() {
    if (typeof getAuthHeaders === 'function') return getAuthHeaders();
    return {
      'Authorization': localStorage.getItem('auth_token') || '',
      'X-User-Id': localStorage.getItem('user_id') || '1'
    };
  }

  function isServerVideoUrl(url) {
    return !!url && String(url).indexOf('/upload/') !== -1;
  }

  function createScriptExtractNode(opts) {
    return createNodeBase({
      type: 'script_extract',
      title: function() { return tr('script_extract_title', '剧本提取'); },
      defaultData: {
        videoUrl: '',
        videoName: '',
        scriptContent: '',
        taskId: '',
        taskStage: '',
        taskDone: false,
        lastError: '',
        meta: null
      },
      ports: SCRIPT_EXTRACT_PORTS,
      width: 360,
      height: 320,
      titleIcon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H14l6 6v11.5a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 20.5v-15Z"/><path d="M14 3v6h6"/><path d="M8 13h8M8 16.5h5"/></svg>',
      bodyHtml: function() {
        return '<div class="field">' +
            '<div class="label" style="margin:0;" data-i18n="script_extract_source_label">' + tr('script_extract_source_label', '源视频') + '</div>' +
            '<div class="muted script-extract-source-hint" style="font-size:11px;">' + tr('script_extract_source_hint', '连接视频节点，或点击上方上传本地视频') + '</div>' +
            '<input class="script-extract-file" type="file" accept="video/*" />' +
            '<div class="video-preview-field" style="display:none;">' +
              '<div class="video-preview"><video class="script-extract-thumb" playsinline muted></video></div>' +
              '<div class="gen-meta script-extract-video-name"></div>' +
            '</div>' +
          '</div>' +
          '<div class="field">' +
            '<button type="button" class="gen-btn gen-btn-main script-extract-btn" style="width:100%;" data-i18n="script_extract_btn">' + tr('script_extract_btn', '提取剧本') + '</button>' +
            '<div class="muted script-extract-status" style="display:none; font-size:11px;"></div>' +
          '</div>' +
          '<div class="field">' +
            '<div class="label" data-i18n="script_extract_result_label">' + tr('script_extract_result_label', '剧本（可编辑）') + '</div>' +
            '<textarea class="script-extract-content" rows="10" maxlength="30000" placeholder="' + tr('script_extract_result_placeholder', '提取的文字剧本将显示在这里') + '" style="resize:vertical; min-height:120px; width:100%; box-sizing:border-box; padding:6px 8px; border:1px solid #e5e7eb; border-radius:6px; font-size:12px; line-height:1.6; background:#fff;"></textarea>' +
            '<div class="gen-meta script-extract-meta" style="display:none;"></div>' +
            '<div style="display:flex; gap:6px; margin-top:6px;">' +
              '<button type="button" class="gen-btn script-extract-copy-btn" style="flex:1;" data-i18n="script_extract_copy">' + tr('script_extract_copy', '复制') + '</button>' +
              '<button type="button" class="gen-btn gen-btn-main script-extract-write-btn" style="flex:2;" data-i18n="script_extract_write_node">' + tr('script_extract_write_node', '写入剧本节点') + '</button>' +
            '</div>' +
          '</div>';
      },
      onCreated: function(node, el) {
        var sourceHint = el.querySelector('.script-extract-source-hint');
        var fileEl = el.querySelector('.script-extract-file');
        var previewField = el.querySelector('.video-preview-field');
        var thumbVideo = el.querySelector('.script-extract-thumb');
        var nameEl = el.querySelector('.script-extract-video-name');
        var extractBtn = el.querySelector('.script-extract-btn');
        var statusEl = el.querySelector('.script-extract-status');
        var contentEl = el.querySelector('.script-extract-content');
        var metaEl = el.querySelector('.script-extract-meta');
        var copyBtn = el.querySelector('.script-extract-copy-btn');
        var writeBtn = el.querySelector('.script-extract-write-btn');
        var pollTimer = null;
        var uploading = false;

        function updateStatus(text, color) {
          if (!statusEl) return;
          statusEl.style.display = text ? 'block' : 'none';
          statusEl.style.color = color || '';
          statusEl.textContent = text || '';
        }

        function setBusy(busy) {
          if (extractBtn) extractBtn.disabled = busy;
          if (fileEl) fileEl.disabled = busy;
        }

        function updateMeta(meta) {
          if (!metaEl) return;
          if (!meta) {
            metaEl.style.display = 'none';
            metaEl.textContent = '';
            return;
          }
          var parts = [];
          if (meta.duration_label) parts.push('时长 ' + meta.duration_label);
          if (meta.frame_count !== undefined) parts.push(meta.frame_count + ' 关键帧');
          if (meta.transcript_available) parts.push(tr('script_extract_meta_transcript', '含语音转写'));
          if (meta.model) parts.push(String(meta.model));
          metaEl.textContent = parts.join(' ｜ ');
          metaEl.style.display = parts.length ? 'block' : 'none';
        }

        function showVideo(url, name) {
          if (!url) return;
          node.data.videoUrl = url;
          if (name) node.data.videoName = name;
          if (thumbVideo) thumbVideo.src = proxyDownloadUrl(url);
          if (previewField) previewField.style.display = '';
          if (nameEl) nameEl.textContent = node.data.videoName || '';
          if (sourceHint) sourceHint.style.display = 'none';
        }

        // 输入端口连线：直接接管连线视频节点的 URL（与提取帧节点同款交互）
        bindInputPortEvents(el, node, {
          cssClass: null,
          acceptType: 'video',
          connectionType: 'connections',
          onConnect: function(fromNode) {
            var url = (fromNode && fromNode.data && fromNode.data.url) || '';
            if (url) showVideo(url, (fromNode.data && fromNode.data.name) || '视频');
            safeAutoSave();
          }
        });

        // 本地上传：立即上传拿永久 URL（刷新/重试后仍可用）
        if (fileEl) {
          fileEl.addEventListener('change', async function() {
            var file = fileEl.files && fileEl.files[0];
            if (!file || uploading) return;
            uploading = true;
            setBusy(true);
            updateStatus(tr('script_extract_uploading', '视频上传中...'));
            try {
              var url = typeof uploadFile === 'function' ? await uploadFile(file) : null;
              if (url) {
                showVideo(url, file.name);
                node.data.lastError = '';
                updateStatus('');
              } else {
                updateStatus(tr('script_extract_upload_failed', '视频上传失败'), '#dc2626');
              }
            } catch (e) {
              updateStatus(tr('script_extract_upload_failed', '视频上传失败'), '#dc2626');
            } finally {
              uploading = false;
              setBusy(false);
              safeAutoSave();
            }
          });
        }

        // textarea 手工编辑同步（防抖保存由 safeAutoSave 自带）
        if (contentEl) {
          contentEl.addEventListener('input', function() {
            node.data.scriptContent = contentEl.value;
            safeAutoSave();
          });
        }

        function stopPolling() {
          if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
          }
        }

        function stageText(stage, progress) {
          if (stage === 'frames') return tr('script_extract_stage_frames', '正在提取关键帧...');
          if (stage === 'audio') return tr('script_extract_stage_audio', '正在提取音轨...');
          if (stage === 'asr') {
            var done = progress && progress.asr_done !== undefined ? progress.asr_done : 0;
            var total = progress && progress.asr_total !== undefined ? progress.asr_total : 0;
            if (total > 0) {
              return tr('script_extract_stage_asr', '正在转写语音 ({done}/{total})...', { done: done, total: total });
            }
            return tr('script_extract_extracting', '提取中...');
          }
          if (stage === 'llm') return tr('script_extract_stage_llm', '智能体正在撰写剧本...');
          return tr('script_extract_extracting', '提取中...');
        }

        function finishSuccess(result) {
          stopPolling();
          node.data.taskDone = true;
          node.data.taskStage = 'done';
          node.data.lastError = '';
          if (result && result.script) node.data.scriptContent = result.script;
          node.data.meta = (result && result.meta) || null;
          if (contentEl) contentEl.value = node.data.scriptContent;
          updateMeta(node.data.meta);
          updateStatus('');
          setBusy(false);
          safeAutoSave();
        }

        function finishFailed(error) {
          stopPolling();
          node.data.taskDone = true;
          node.data.taskStage = 'done';
          node.data.lastError = error || tr('script_extract_failed', '提取失败');
          updateStatus(tr('script_extract_failed', '提取失败') + '：' + node.data.lastError, '#dc2626');
          setBusy(false);
          safeAutoSave();
        }

        function pollStatus(taskId) {
          stopPolling();
          var attempts = 0;
          pollTimer = setInterval(async function() {
            attempts++;
            if (attempts > POLL_MAX_ATTEMPTS) {
              finishFailed(tr('script_extract_timeout', '提取超时，请重试'));
              return;
            }
            try {
              var resp = await fetch('/api/video-workflow/extract-script/status/' + encodeURIComponent(taskId), {
                method: 'GET',
                headers: authHeaders()
              });
              if (resp.status === 404) {
                node.data.taskId = '';
                finishFailed(tr('script_extract_task_lost', '任务已失效，请重新提取'));
                return;
              }
              var result = await resp.json();
              if (!result || result.code !== 0 || !result.data) return; // 偶发错误：继续轮询
              var data = result.data;
              node.data.taskStage = data.stage || '';
              if (data.status === 'success') {
                finishSuccess(data.result);
              } else if (data.status === 'failed') {
                finishFailed(data.error || '');
              } else {
                updateStatus(stageText(data.stage, data.progress));
              }
            } catch (e) {
              // 网络抖动：继续轮询
            }
          }, POLL_INTERVAL_MS);
        }

        async function startExtract() {
          var url = node.data.videoUrl;
          if (!isServerVideoUrl(url)) {
            showToast(tr('script_extract_no_video', '请先上传视频或连接视频节点'), 'error');
            return;
          }
          setBusy(true);
          node.data.lastError = '';
          node.data.taskDone = false;
          node.data.scriptContent = '';
          node.data.meta = null;
          if (contentEl) contentEl.value = '';
          updateMeta(null);
          updateStatus(tr('script_extract_extracting', '提取中...'));
          try {
            var resp = await fetch('/api/video-workflow/extract-script', {
              method: 'POST',
              headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
              body: JSON.stringify({ video_url: url })
            });
            var result = await resp.json();
            if (resp.status === 409 || (result && result.code === -1 && /已有剧本提取任务/.test(result.message || ''))) {
              updateStatus(result.message || tr('script_extract_conflict', '已有提取任务进行中'), '#d97706');
              setBusy(false);
              return;
            }
            if (result && result.code === 0 && result.data && result.data.task_id) {
              node.data.taskId = result.data.task_id;
              safeAutoSave();
              pollStatus(node.data.taskId);
            } else {
              finishFailed((result && result.message) || ('HTTP ' + resp.status));
            }
          } catch (e) {
            finishFailed(e && e.message ? e.message : 'network error');
          }
        }

        if (extractBtn) extractBtn.addEventListener('click', startExtract);

        // 复制到剪贴板
        if (copyBtn) copyBtn.addEventListener('click', async function() {
          var text = node.data.scriptContent || (contentEl && contentEl.value) || '';
          if (!text) return;
          try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
              await navigator.clipboard.writeText(text);
            } else {
              contentEl.select();
              document.execCommand('copy');
            }
            showToast(tr('script_extract_copied', '已复制'), 'success');
          } catch (e) {
            showToast(tr('script_extract_copy_failed', '复制失败'), 'error');
          }
        });

        // 写入画布"剧本节点"（script_node），复用下游拆分链路
        if (writeBtn) writeBtn.addEventListener('click', function() {
          var text = (contentEl && contentEl.value) || node.data.scriptContent || '';
          if (!text) {
            showToast(tr('script_extract_no_content', '没有可写入的剧本内容'), 'error');
            return;
          }
          if (typeof createScriptNode !== 'function') {
            showToast(tr('script_extract_write_failed', '写入剧本节点失败'), 'error');
            return;
          }
          var scriptNodeId = createScriptNode();
          var scriptNode = state.nodes.find(function(n) { return n.id === scriptNodeId; });
          if (!scriptNode) return;
          scriptNode.data.scriptContent = text;
          var scriptEl = document.querySelector('.node[data-node-id="' + scriptNodeId + '"]');
          var textarea = scriptEl && scriptEl.querySelector('.script-textarea');
          if (textarea) {
            textarea.value = text;
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
          }
          safeAutoSave();
          showToast(tr('script_extract_written', '已写入剧本节点'), 'success');
        });

        // 恢复：上次任务未完成（刷新后回来）→ 继续轮询
        if (node.data.taskId && !node.data.taskDone && !node.data.scriptContent) {
          setBusy(true);
          updateStatus(tr('script_extract_extracting', '提取中...'));
          pollStatus(node.data.taskId);
        } else if (node.data.lastError) {
          updateStatus(tr('script_extract_failed', '提取失败') + '：' + node.data.lastError, '#dc2626');
        }
      }
    });
  }

  // 恢复工厂：回填视频预览/结果文本/meta，并接续未完成任务的轮询
  var createScriptExtractNodeWithData = createNodeWithDataFactory(
    createScriptExtractNode,
    function(el, node) {
      var previewField = el.querySelector('.video-preview-field');
      var thumbVideo = el.querySelector('.script-extract-thumb');
      var nameEl = el.querySelector('.script-extract-video-name');
      var sourceHint = el.querySelector('.script-extract-source-hint');
      var contentEl = el.querySelector('.script-extract-content');
      var metaEl = el.querySelector('.script-extract-meta');

      if (node.data.videoUrl) {
        if (thumbVideo) thumbVideo.src = proxyDownloadUrl(node.data.videoUrl);
        if (previewField) previewField.style.display = '';
        if (nameEl) nameEl.textContent = node.data.videoName || '';
        if (sourceHint) sourceHint.style.display = 'none';
      }
      if (contentEl) contentEl.value = node.data.scriptContent || '';
      if (metaEl && node.data.meta) {
        var parts = [];
        var meta = node.data.meta;
        if (meta.duration_label) parts.push('时长 ' + meta.duration_label);
        if (meta.frame_count !== undefined) parts.push(meta.frame_count + ' 关键帧');
        if (meta.transcript_available) parts.push(tr('script_extract_meta_transcript', '含语音转写'));
        if (meta.model) parts.push(String(meta.model));
        metaEl.textContent = parts.join(' ｜ ');
        metaEl.style.display = parts.length ? 'block' : 'none';
      }
    }
  );

  // 注册到全局
  window.createScriptExtractNode = createScriptExtractNode;
  window.createScriptExtractNodeWithData = createScriptExtractNodeWithData;

  // 注册到节点注册表
  registerNodeType('script_extract', {
    createFn: createScriptExtractNode,
    createWithDataFn: createScriptExtractNodeWithData
  });

})();
