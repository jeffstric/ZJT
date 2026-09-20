// ============================
// prompt_reverse_node.js - 提示词反推节点
// 输入图片 → VL 大模型反推文生图提示词 → 自动创建空的图片节点并填入提示词
// ============================
(function() {
  'use strict';

  var PROMPT_REVERSE_PORTS = [
    { direction: 'input', titleI18nKey: 'prompt_reverse_input_port', cssClass: 'prompt-reverse-source-port', acceptType: ['image'], connectionType: 'connections' },
    { direction: 'output', titleI18nKey: 'prompt_reverse_output_port' }
  ];

  function tr(key, fallback, params) {
    var v = window.t ? window.t(key, params) : null;
    return (v && v !== key) ? v : fallback;
  }

  function createPromptReverseNode(opts) {
    return createNodeBase({
      type: 'prompt_reverse',
      title: function() { return tr('prompt_reverse_title', '提示词反推'); },
      defaultData: {
        reversedPrompt: '',
        generatedImageNodeId: null,
        lastError: ''
      },
      ports: PROMPT_REVERSE_PORTS,
      width: 360,
      titleIcon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M5 19L9 15M15 9L19 5M7 11L5 9M13 5L11 3M13 19L11 17M19 13L17 11" stroke-linecap="round"/><path d="M9 15L15 9" stroke-linecap="round"/><circle cx="6" cy="6" r="1.2" fill="currentColor"/><circle cx="18" cy="18" r="1.2" fill="currentColor"/></svg>',
      bodyHtml: function() {
        return '<div class="field">' +
            '<div class="label" style="margin:0;" data-i18n="prompt_reverse_source_label">' + tr('prompt_reverse_source_label', '源图片') + '</div>' +
            '<div class="prompt-reverse-source-thumb" style="display:none;">' +
              '<img class="prompt-reverse-source-img" style="max-width:100%; max-height:80px; border-radius:4px; border:1px solid #e5e7eb;" />' +
            '</div>' +
            '<div class="muted prompt-reverse-source-placeholder" style="font-size:11px;">' + tr('prompt_reverse_source_hint', '连接图片节点后自动反推提示词，也可点击按钮手动反推') + '</div>' +
          '</div>' +
          '<div class="field">' +
            '<div class="label" data-i18n="prompt_reverse_result_label">' + tr('prompt_reverse_result_label', '反推结果（可编辑，同步到图片节点）') + '</div>' +
            '<textarea class="prompt-reverse-prompt" rows="4" readonly placeholder="' + tr('prompt_reverse_result_placeholder', '反推的文生图提示词将显示在这里') + '" style="resize:vertical; min-height:70px;"></textarea>' +
          '</div>' +
          '<div class="field">' +
            '<button type="button" class="gen-btn gen-btn-main prompt-reverse-btn" style="width:100%;" data-i18n="prompt_reverse_btn">' + tr('prompt_reverse_btn', '反推提示词') + '</button>' +
            '<div class="muted prompt-reverse-status" style="display:none; font-size:11px;"></div>' +
          '</div>';
      },
      onCreated: function(node, el) {
        var sourceThumb = el.querySelector('.prompt-reverse-source-thumb');
        var sourceImg = el.querySelector('.prompt-reverse-source-img');
        var sourcePlaceholder = el.querySelector('.prompt-reverse-source-placeholder');
        var promptEl = el.querySelector('.prompt-reverse-prompt');
        var reverseBtn = el.querySelector('.prompt-reverse-btn');
        var statusEl = el.querySelector('.prompt-reverse-status');
        // 反推进行中标记：仅运行期状态，不持久化
        var reversing = false;

        function updateStatus(text, color) {
          if (!statusEl) return;
          statusEl.style.display = text ? 'block' : 'none';
          statusEl.style.color = color || '';
          statusEl.textContent = text || '';
        }

        function getSourceNode() {
          var conn = state.connections.find(function(c) {
            return c.to === node.id && (!c.portType || c.portType === 'prompt-reverse-source');
          });
          return conn ? state.nodes.find(function(n) { return n.id === conn.from; }) : null;
        }

        function getSourceImageUrl(sourceNode) {
          if (!sourceNode || !sourceNode.data) return '';
          if (typeof getNodeImageUrl === 'function') return getNodeImageUrl(sourceNode) || '';
          return sourceNode.data.url || sourceNode.data.preview || '';
        }

        function updateSourceThumbnail() {
          var sourceNode = getSourceNode();
          var url = sourceNode ? getSourceImageUrl(sourceNode) : '';
          if (url) {
            sourceImg.src = proxyImageUrl(url);
            sourceThumb.style.display = 'block';
            sourcePlaceholder.style.display = 'none';
          } else {
            sourceThumb.style.display = 'none';
            sourcePlaceholder.style.display = 'block';
            sourcePlaceholder.textContent = sourceNode
              ? tr('prompt_reverse_source_no_image', '源图片节点没有图片，生成/上传后点击按钮反推')
              : tr('prompt_reverse_source_hint', '连接图片节点后自动反推提示词，也可点击按钮手动反推');
          }
        }

        // 查找/更新已生成的图片节点；不存在则新建空的图片节点并填入提示词
        function ensureGeneratedImageNode(promptText) {
          var existing = state.nodes.find(function(n) {
            return n.id === node.data.generatedImageNodeId && n.type === 'image';
          });
          if (existing) {
            existing.data.prompt = promptText;
            var existingEl = canvasEl.querySelector('.node[data-node-id="' + existing.id + '"]');
            if (existingEl) {
              var existingPromptEl = existingEl.querySelector('.image-prompt');
              if (existingPromptEl) existingPromptEl.value = promptText;
            }
            return;
          }
          var imageNodeId = createImageNode({
            x: node.x + 440,
            y: node.y,
            checkCollision: true,
            data: { prompt: promptText }
          });
          var imageNode = state.nodes.find(function(n) { return n.id === imageNodeId; });
          if (imageNode) {
            imageNode.data.name = tr('prompt_reverse_result_name', '反推结果');
            node.data.generatedImageNodeId = imageNodeId;
          }
          state.connections.push({
            id: state.nextConnId++,
            from: node.id,
            to: imageNodeId
          });
          if (typeof renderConnections === 'function') renderConnections();
          if (typeof renderAllConnections === 'function') renderAllConnections();
          if (typeof renderMinimap === 'function') renderMinimap();
        }

        // 编辑反推结果时同步到已生成的图片节点提示词
        promptEl.addEventListener('input', function() {
          node.data.reversedPrompt = promptEl.value;
          var target = state.nodes.find(function(n) {
            return n.id === node.data.generatedImageNodeId && n.type === 'image';
          });
          if (target) {
            target.data.prompt = promptEl.value;
            var targetEl = canvasEl.querySelector('.node[data-node-id="' + target.id + '"]');
            if (targetEl) {
              var targetPromptEl = targetEl.querySelector('.image-prompt');
              if (targetPromptEl) targetPromptEl.value = promptEl.value;
            }
          }
          safeAutoSave();
        });

        function reversePrompt() {
          if (reversing) return;
          var sourceNode = getSourceNode();
          var imgUrl = sourceNode ? getSourceImageUrl(sourceNode) : '';
          if (!imgUrl) {
            updateStatus(
              sourceNode
                ? tr('prompt_reverse_source_no_image', '源图片节点没有图片，生成/上传后点击按钮反推')
                : tr('prompt_reverse_no_source', '请先连接图片节点'),
              '#d97706'
            );
            return;
          }

          reversing = true;
          if (reverseBtn) reverseBtn.disabled = true;
          promptEl.removeAttribute('readonly');
          var dots = 0;
          updateStatus(tr('prompt_reverse_generating', '正在反推提示词'), '#666');
          var loadingTimer = setInterval(function() {
            dots = (dots + 1) % 4;
            updateStatus(tr('prompt_reverse_generating', '正在反推提示词') + '.'.repeat(dots), '#666');
          }, 400);

          var headers = { 'Content-Type': 'application/json' };
          if (typeof getAuthToken === 'function') headers['Authorization'] = getAuthToken();
          if (typeof getUserId === 'function') headers['X-User-Id'] = getUserId();
          fetch('/api/video-workflow/describe-image', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({ image_url: imgUrl, purpose: 'image_prompt' })
          })
            .then(function(r) { return r.json(); })
            .then(function(data) {
              clearInterval(loadingTimer);
              reversing = false;
              if (reverseBtn) reverseBtn.disabled = false;
              if (data && data.success && data.description) {
                node.data.reversedPrompt = data.description;
                node.data.lastError = '';
                promptEl.value = data.description;
                ensureGeneratedImageNode(data.description);
                updateStatus(tr('prompt_reverse_success', '反推成功，已在右侧创建图片节点并填入提示词'), '#22c55e');
                showToast(tr('prompt_reverse_success_toast', '提示词反推完成'), 'success');
                safeAutoSave();
              } else {
                var error = (data && data.error) || tr('prompt_reverse_failed_plain', '反推失败');
                node.data.lastError = String(error);
                updateStatus(tr('prompt_reverse_failed', '反推失败: {error}', { error: error }), '#dc2626');
              }
            })
            .catch(function() {
              clearInterval(loadingTimer);
              reversing = false;
              if (reverseBtn) reverseBtn.disabled = false;
              var error = tr('prompt_reverse_failed_plain', '反推失败');
              node.data.lastError = String(error);
              updateStatus(tr('prompt_reverse_failed', '反推失败: {error}', { error: error }), '#dc2626');
            });
        }

        reverseBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          reversePrompt();
        });

        // 重载恢复：回填文本域/缩略图/上次失败原因，不自动重新反推
        el._restorePromptReverseState = function() {
          promptEl.value = node.data.reversedPrompt || '';
          if (node.data.reversedPrompt) promptEl.removeAttribute('readonly');
          updateSourceThumbnail();
          if (node.data.lastError) {
            updateStatus(tr('prompt_reverse_failed', '反推失败: {error}', { error: node.data.lastError }), '#dc2626');
          }
        };
        el._updatePromptReverseSource = updateSourceThumbnail;
        el._autoReverseFromSource = function() {
          updateSourceThumbnail();
          // 新连线自动反推（要求源图已有 URL；无图时仅显示占位提示）
          var sourceNode = getSourceNode();
          if (sourceNode && getSourceImageUrl(sourceNode)) {
            reversePrompt();
          }
        };

        updateSourceThumbnail();
      }
    }, opts);
  }

  var createPromptReverseNodeWithData = createNodeWithDataFactory(
    createPromptReverseNode,
    function(el) {
      if (typeof el._restorePromptReverseState === 'function') el._restorePromptReverseState();
    }
  );

  // 注册到全局
  window.createPromptReverseNode = createPromptReverseNode;
  window.createPromptReverseNodeWithData = createPromptReverseNodeWithData;

  // 注册到节点注册表（工作流重载恢复）
  registerNodeType('prompt_reverse', {
    createFn: createPromptReverseNode,
    createWithDataFn: createPromptReverseNodeWithData
  });

  // 注册源图输入端口：图片节点拖线到附近即可吸附连接（50px），连上后自动反推
  if (typeof registerInputPorts === 'function') {
    registerInputPorts('prompt_reverse', [{
      selector: '.port.input.prompt-reverse-source-port',
      portType: 'prompt-reverse-source',
      accepts: ['image'],
      connectionType: 'connections',
      // 图片节点可能尚未生成图片：允许先连线，图到位后再点按钮反推
      allowMissingImage: true,
      onConnect: function(fromNode, targetNode) {
        var targetEl = canvasEl.querySelector('.node[data-node-id="' + targetNode.id + '"]');
        if (!targetEl) return;
        if (typeof targetEl._autoReverseFromSource === 'function') targetEl._autoReverseFromSource();
      }
    }]);
  }

})();
