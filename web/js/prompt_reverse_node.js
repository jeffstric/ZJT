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
        lastError: '',
        // 反推模型选择：空值 = 自动（后端按偏好挑选）；仅保存 VL 视觉模型
        reverseModelName: '',
        reverseModelId: null,
        reverseVendorId: null
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
            '<div class="label" data-i18n="prompt_reverse_model_label">' + tr('prompt_reverse_model_label', '反推模型') + '</div>' +
            '<select class="prompt-reverse-model" style="width:100%; box-sizing:border-box; padding:4px 6px; border:1px solid #e5e7eb; border-radius:6px; background:#fff; font-size:12px;"></select>' +
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
        var modelSelect = el.querySelector('.prompt-reverse-model');
        // 反推进行中标记：仅运行期状态，不持久化
        var reversing = false;
        // 模型列表异步加载完成后再恢复选中项的标记
        var pendingRestoreModel = false;

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

        // 反推模型列表（仅 VL 视觉模型，参考 marketing_agent 的 /api/models 模式）：
        // 全局缓存供画布上多个反推节点复用；加载失败时保留下拉默认项（自动模式）
        function modelListHeaders() {
          if (typeof getAuthHeaders === 'function') return getAuthHeaders();
          var headers = { 'Content-Type': 'application/json' };
          if (typeof getAuthToken === 'function') headers['Authorization'] = getAuthToken();
          if (typeof getUserId === 'function') headers['X-User-Id'] = getUserId();
          return headers;
        }

        function applyModelSelection() {
          if (!modelSelect) return;
          var savedName = node.data.reverseModelName || '';
          var savedId = node.data.reverseModelId;
          var savedVendorId = node.data.reverseVendorId;
          var matchOpt = null;
          var i, opt, optModelId, optVendorId;
          // 优先按 model_id + vendor_id 双键精确匹配（同名校验归属供应商）
          if (savedId !== null && savedId !== undefined) {
            for (i = 0; i < modelSelect.options.length; i++) {
              opt = modelSelect.options[i];
              optModelId = parseInt(opt.dataset.modelId || '', 10);
              optVendorId = parseInt(opt.dataset.vendorId || '', 10);
              if (isNaN(optModelId) || optModelId !== Number(savedId)) continue;
              if (savedVendorId !== null && savedVendorId !== undefined &&
                  !isNaN(optVendorId) && optVendorId !== Number(savedVendorId)) continue;
              matchOpt = opt;
              break;
            }
          }
          // 兜底按名称匹配（兼容早期仅存名称的数据）
          if (!matchOpt && savedName) {
            for (i = 0; i < modelSelect.options.length; i++) {
              opt = modelSelect.options[i];
              if (opt.value && opt.value === savedName) { matchOpt = opt; break; }
            }
          }
          if (matchOpt) {
            modelSelect.value = matchOpt.value;
          } else if (savedName || (savedId !== null && savedId !== undefined)) {
            // 已保存的模型已不在 VL 列表（下架/改配）：回落自动模式并持久化
            modelSelect.value = '';
            node.data.reverseModelName = '';
            node.data.reverseModelId = null;
            node.data.reverseVendorId = null;
            safeAutoSave();
          } else {
            modelSelect.value = '';
          }
        }

        function renderModelOptions(models) {
          if (!modelSelect) return;
          modelSelect.innerHTML = '';
          var autoOpt = document.createElement('option');
          autoOpt.value = '';
          autoOpt.textContent = tr('prompt_reverse_model_auto', '自动（后端推荐）');
          modelSelect.appendChild(autoOpt);
          (models || []).forEach(function(m) {
            if (!m || !m.name) return;
            var opt = document.createElement('option');
            opt.value = m.name;
            opt.textContent = m.vendor_name ? (m.vendor_name + ' / ' + m.name) : m.name;
            if (m.model_id !== undefined && m.model_id !== null) opt.dataset.modelId = String(m.model_id);
            if (m.vendor_id !== undefined && m.vendor_id !== null) opt.dataset.vendorId = String(m.vendor_id);
            modelSelect.appendChild(opt);
          });
          if (pendingRestoreModel) {
            pendingRestoreModel = false;
            applyModelSelection();
          }
        }

        function loadVlModelOptions() {
          pendingRestoreModel = true;
          // 已有缓存（其他节点加载过）：直接渲染
          if (window._promptReverseVlModels && window._promptReverseVlModels.length) {
            renderModelOptions(window._promptReverseVlModels);
            return;
          }
          // 正在加载中：等共享 Promise 完成后渲染
          if (window._promptReverseVlModelsLoading) {
            window._promptReverseVlModelsLoading.then(function() {
              if (window._promptReverseVlModels) renderModelOptions(window._promptReverseVlModels);
            }).catch(function() {});
            return;
          }
          window._promptReverseVlModelsLoading = fetch('/api/models', { headers: modelListHeaders() })
            .then(function(r) { return r.json(); })
            .then(function(data) {
              // 只保留 VL 视觉模型：非 VL 模型一律不显示
              var models = (data && data.models) ? data.models.filter(function(m) {
                return m && m.supports_vl;
              }) : [];
              models.sort(function(a, b) {
                var va = (a.vendor_name || '').toLowerCase();
                var vb = (b.vendor_name || '').toLowerCase();
                if (va !== vb) return va < vb ? -1 : 1;
                var na = (a.name || '').toLowerCase();
                var nb = (b.name || '').toLowerCase();
                return na < nb ? -1 : (na > nb ? 1 : 0);
              });
              window._promptReverseVlModels = models;
              renderModelOptions(models);
            })
            .catch(function() {
              window._promptReverseVlModelsLoading = null;
              if (!node.data.lastError) {
                updateStatus(tr('prompt_reverse_model_failed', '模型列表加载失败，已使用自动模式'), '#d97706');
              }
            });
        }

        if (modelSelect) {
          modelSelect.addEventListener('change', function() {
            var opt = modelSelect.options[modelSelect.selectedIndex];
            if (opt && opt.value) {
              node.data.reverseModelName = opt.value;
              var mid = parseInt(opt.dataset.modelId || '', 10);
              var vid = parseInt(opt.dataset.vendorId || '', 10);
              node.data.reverseModelId = isNaN(mid) ? null : mid;
              node.data.reverseVendorId = isNaN(vid) ? null : vid;
            } else {
              node.data.reverseModelName = '';
              node.data.reverseModelId = null;
              node.data.reverseVendorId = null;
            }
            safeAutoSave();
          });
          loadVlModelOptions();
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
          var requestBody = { image_url: imgUrl, purpose: 'image_prompt' };
          if (node.data.reverseModelName) {
            requestBody.model = node.data.reverseModelName;
            if (node.data.reverseModelId !== null && node.data.reverseModelId !== undefined) {
              requestBody.model_id = node.data.reverseModelId;
            }
            if (node.data.reverseVendorId !== null && node.data.reverseVendorId !== undefined) {
              requestBody.vendor_id = node.data.reverseVendorId;
            }
          }
          fetch('/api/video-workflow/describe-image', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(requestBody)
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
          // 模型列表已加载则立即回填选中项；未加载完成时由 loadVlModelOptions 的
          // pendingRestoreModel 标记在渲染后补选
          if (window._promptReverseVlModels) applyModelSelection();
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
