// ============================
// digital_human_node.js - 数字人节点
// 使用 createNodeBase 基类工厂
// 输入：图片（可连接图片节点）、音频（可连接音频节点）、提示词
// 输出：视频（支持抽卡 1-4 个，结果在关联视频节点展示）
// ============================

(function() {

  // 默认提示词
  var DEFAULT_PROMPT = '角色面向镜头深情的说话，固定镜头。';

  // 固定参数（与提交任务逻辑保持一致）
  var DH_MODEL_KEY_PRIMARY = 'digital_human_ltx2_3_voice';
  var DH_MODEL_KEY_FALLBACK = 'digital_human';
  var DH_DURATION = 5;

  // 安全翻译函数：当 window.t 返回原始键名时（翻译未加载），使用 fallback
  function _t(key, fallback) {
    if (typeof window.t !== 'function') return fallback;
    var result = window.t(key);
    return result === key ? fallback : result;
  }

  // 带参数的安全翻译函数
  function _tp(key, params, fallback) {
    if (typeof window.t !== 'function') return fallback;
    var result = window.t(key, params);
    return result === key ? fallback : result;
  }

  // 取数字人 modelKey（优先 ltx2_3_voice，回退 digital_human）
  function getDigitalHumanModelKey() {
    if (typeof TaskConfig === 'undefined' || typeof TaskConfig.getTaskByKey !== 'function') {
      return DH_MODEL_KEY_PRIMARY;
    }
    return TaskConfig.getTaskByKey(DH_MODEL_KEY_PRIMARY) ? DH_MODEL_KEY_PRIMARY : DH_MODEL_KEY_FALLBACK;
  }

  function createDigitalHumanNode(opts) {
    return createNodeBase({
      type: 'digital_human',
      title: function() { return _t('dh_title', '数字人'); },
      defaultData: {
        prompt: opts?.data?.prompt || DEFAULT_PROMPT,
        imageFile: null,
        imageUrl: opts?.data?.imageUrl || '',
        imagePreview: opts?.data?.imagePreview || '',
        audioFile: null,
        audioUrl: opts?.data?.audioUrl || '',
        // 抽卡次数（重载复原）
        drawCount: opts?.data?.drawCount || 1,
        projectId: null,
        status: opts?.data?.status || ''
      },
      ports: [
        { direction: 'output', titleI18nKey: 'dh_output_port' }
      ],
      width: 300,
      height: 340,
      titleIcon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><circle cx="12" cy="8" r="4"/><path d="M6 21C6 17.6863 8.68629 15 12 15C15.3137 15 18 17.6863 18 21"/></svg>',
      bodyHtml: function() {
        return '<!-- 图片输入区 -->' +
          '<div class="field" style="position: relative;">' +
            '<div class="port dh-image-input-port start-image-port" data-port-type="start" title="' + _t('dh_image_port', '连接图片节点') + '"></div>' +
            '<div class="label">' + _t('dh_image_label', '角色图片') + ' <span style="color: red;">*</span></div>' +
            '<input class="dh-image" type="file" accept="image/*" />' +
            '<button class="mini-btn dh-image-clear" type="button" style="margin-top:4px; display:none;">' + _t('dh_clear_btn', '清除') + '</button>' +
            '<div class="dh-image-preview" style="display:none; margin-top:4px;">' +
              '<img class="dh-image-thumb" style="max-width:100%; max-height:80px; border-radius:4px;" />' +
            '</div>' +
          '</div>' +
          '<!-- 音频输入区 -->' +
          '<div class="field" style="position: relative;">' +
            '<div class="port dh-audio-input-port audio-input-port" data-port-type="audio" title="' + _t('dh_audio_port', '连接音频节点') + '"></div>' +
            '<div class="label">' + _t('dh_audio_label', '说话音频') + ' <span style="color: red;">*</span></div>' +
            '<input class="dh-audio" type="file" accept="audio/*" />' +
            '<button class="mini-btn dh-audio-clear" type="button" style="margin-top:4px; display:none;">' + _t('dh_clear_btn', '清除') + '</button>' +
            '<div class="dh-audio-preview" style="display:none; margin-top:4px;">' +
              '<audio class="dh-audio-player" controls style="width:100%; max-height:32px;"></audio>' +
            '</div>' +
          '</div>' +
          '<!-- 提示词 -->' +
          '<div class="field">' +
            '<div class="label">' + _t('dh_prompt_label', '提示词') + ' <span style="color: red;">*</span></div>' +
            '<textarea class="dh-prompt" rows="2" placeholder="' + _t('dh_prompt_placeholder', '输入视频生成的提示词') + '"></textarea>' +
          '</div>' +
          '<!-- 算力消耗 -->' +
          '<div class="field dh-power-field" style="padding: 6px; border-radius: 6px;">' +
            '<div style="display: flex; justify-content: space-between; align-items: center;">' +
              '<span style="color: #9ca3af; font-size: 12px;">' + _t('computing_power_label', '算力消耗：') + '</span>' +
              '<span class="dh-power-value" style="color: #60a5fa; font-weight: bold; font-size: 14px;">' + _tp('computing_power_value', { power: 0 }, '0 算力') + '</span>' +
            '</div>' +
            '<div class="dh-power-detail" style="margin-top: 4px; font-size: 11px; color: #6b7280;">' +
              _tp('computing_power_detail', { individual: 0, count: 1, total: 0 }, '单个 0 算力 × 1 个 = 0 算力') +
            '</div>' +
          '</div>' +
          '<!-- 抽卡选择器 + 状态 -->' +
          '<div class="field">' +
            '<div class="gen-container">' +
              '<button class="gen-btn gen-btn-main dh-generate-btn" type="button">' + _t('dh_generate_btn', '生成视频') + '</button>' +
              '<button class="gen-btn gen-btn-caret dh-draw-caret" type="button" aria-label="' + _t('draw_count_menu', '选择抽卡次数') + '">▾</button>' +
              '<div class="gen-menu">' +
                '<div class="gen-item" data-count="1">X1</div>' +
                '<div class="gen-item" data-count="2">X2</div>' +
                '<div class="gen-item" data-count="3">X3</div>' +
                '<div class="gen-item" data-count="4">X4</div>' +
              '</div>' +
            '</div>' +
            '<div class="gen-meta dh-count-label"></div>' +
            '<div class="gen-meta dh-status" style="display:none;"></div>' +
          '</div>';
      },
      onCreated: function(node, el) {
        var promptEl = el.querySelector('.dh-prompt');
        var imageEl = el.querySelector('.dh-image');
        var imagePreview = el.querySelector('.dh-image-preview');
        var imageThumb = el.querySelector('.dh-image-thumb');
        var imageClearBtn = el.querySelector('.dh-image-clear');
        var audioEl = el.querySelector('.dh-audio');
        var audioPreview = el.querySelector('.dh-audio-preview');
        var audioPlayer = el.querySelector('.dh-audio-player');
        var audioClearBtn = el.querySelector('.dh-audio-clear');
        var generateBtn = el.querySelector('.dh-generate-btn');
        var drawCaret = el.querySelector('.dh-draw-caret');
        var drawMenu = el.querySelector('.gen-menu');
        var countLabel = el.querySelector('.dh-count-label');
        var statusEl = el.querySelector('.dh-status');
        var powerValueEl = el.querySelector('.dh-power-value');
        var powerDetailEl = el.querySelector('.dh-power-detail');

        // 初始化：如果有已保存的图片URL，显示预览
        if (node.data.imageUrl) {
          imageThumb.src = typeof proxyDownloadUrl === 'function' ? proxyDownloadUrl(node.data.imageUrl) : node.data.imageUrl;
          imagePreview.style.display = 'block';
          imageClearBtn.style.display = 'inline-block';
        }

        // 初始化：如果有已保存的音频URL，显示播放器
        if (node.data.audioUrl) {
          audioPlayer.src = typeof proxyDownloadUrl === 'function' ? proxyDownloadUrl(node.data.audioUrl) : node.data.audioUrl;
          audioPreview.style.display = 'block';
          audioClearBtn.style.display = 'inline-block';
        }

        // 初始化：恢复状态
        if (node.data.status && statusEl) {
          statusEl.style.display = 'block';
          if (node.data.status === 'SUCCESS') {
            statusEl.style.color = '#16a34a';
            statusEl.textContent = _t('dh_generate_success', '生成成功！');
          } else if (node.data.status === 'FAILED') {
            statusEl.style.color = '#dc2626';
            statusEl.textContent = _t('dh_generate_failed', '生成失败');
          }
        }

        // 提示词输入：设置默认值并监听变更
        promptEl.value = node.data.prompt || DEFAULT_PROMPT;
        promptEl.addEventListener('input', function() {
          node.data.prompt = promptEl.value;
        });

        // === 算力计算与显示 ===
        function calculateDigitalHumanPower() {
          if (typeof TaskConfig === 'undefined' || typeof TaskConfig.isLoaded !== 'function' || !TaskConfig.isLoaded()) {
            return { single: 0, total: 0 };
          }
          var modelKey = getDigitalHumanModelKey();
          var single = TaskConfig.getComputingPower(modelKey, DH_DURATION);
          if (typeof single !== 'number') single = 0;
          var count = node.data.drawCount || 1;
          return { single: single, total: single * count };
        }

        function updateDigitalHumanPowerDisplay() {
          var info = calculateDigitalHumanPower();
          var single = info.single;
          var count = node.data.drawCount || 1;
          var total = info.total;
          if (powerValueEl) {
            powerValueEl.textContent = _tp('computing_power_value', { power: total }, total + ' 算力');
          }
          if (powerDetailEl) {
            powerDetailEl.textContent = _tp('computing_power_detail', { individual: single, count: count, total: total }, '单个 ' + single + ' 算力 × ' + count + ' 个 = ' + total + ' 算力');
          }
        }

        function updateGenMeta() {
          // 抽卡次数标签
          var dc = node.data.drawCount || 1;
          if (countLabel) {
            countLabel.textContent = _tp('draw_count_x', { count: dc }, '抽卡次数：X' + dc);
          }
          // 同时更新算力显示
          updateDigitalHumanPowerDisplay();
        }

        // TaskConfig 异步加载完成后更新算力
        if (typeof TaskConfig !== 'undefined' && typeof TaskConfig.onLoaded === 'function') {
          TaskConfig.onLoaded(function() {
            updateDigitalHumanPowerDisplay();
          });
        }

        updateGenMeta();

        // === 抽卡菜单事件 ===
        drawCaret.addEventListener('click', function(e) {
          e.stopPropagation();
          drawMenu.classList.toggle('show');
        });

        var drawItems = drawMenu.querySelectorAll('.gen-item');
        for (var di = 0; di < drawItems.length; di++) {
          (function(item) {
            item.addEventListener('click', function(e) {
              e.stopPropagation();
              var c = Number(item.dataset.count || '1');
              node.data.drawCount = c;
              updateGenMeta();
              drawMenu.classList.remove('show');
              safeAutoSave();
            });
          })(drawItems[di]);
        }

        // 点击外部关闭抽卡菜单
        document.addEventListener('click', function(e) {
          if (!e.target.closest || !e.target.closest('.gen-container')) {
            drawMenu.classList.remove('show');
          }
        });

        // 图片上传
        imageEl.addEventListener('change', function() {
          var file = imageEl.files && imageEl.files[0];
          if (!file) return;
          node.data.imageFile = file;
          var localUrl = URL.createObjectURL(file);
          imageThumb.src = localUrl;
          imagePreview.style.display = 'block';
          imageClearBtn.style.display = 'inline-block';
        });

        // 清除图片
        imageClearBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          node.data.imageFile = null;
          node.data.imageUrl = '';
          node.data.imagePreview = '';
          imageThumb.removeAttribute('src');
          imagePreview.style.display = 'none';
          imageClearBtn.style.display = 'none';
          imageEl.value = '';
          // 断开图片连接
          state.imageConnections = state.imageConnections.filter(function(c) {
            return !(c.to === node.id && c.portType === 'start');
          });
          if (typeof renderAllConnections === 'function') renderAllConnections();
          safeAutoSave();
        });

        // 音频上传
        audioEl.addEventListener('change', function() {
          var file = audioEl.files && audioEl.files[0];
          if (!file) return;
          node.data.audioFile = file;
          var localUrl = URL.createObjectURL(file);
          audioPlayer.src = localUrl;
          audioPreview.style.display = 'block';
          audioClearBtn.style.display = 'inline-block';
        });

        // 清除音频
        audioClearBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          node.data.audioFile = null;
          node.data.audioUrl = '';
          audioPlayer.removeAttribute('src');
          audioPlayer.load();
          audioPreview.style.display = 'none';
          audioClearBtn.style.display = 'none';
          audioEl.value = '';
          // 断开音频连接
          state.audioConnections = (state.audioConnections || []).filter(function(c) {
            return c.to !== node.id;
          });
          if (typeof renderAllConnections === 'function') renderAllConnections();
          safeAutoSave();
        });

        // === 暴露方法供连接线回调使用 ===

        // 当图片节点通过连接线连接时调用
        node._onImageConnected = function(imageUrl, imagePreviewUrl) {
          node.data.imageUrl = imageUrl;
          node.data.imagePreview = imagePreviewUrl || imageUrl;
          imageThumb.src = typeof proxyDownloadUrl === 'function' ? proxyDownloadUrl(imagePreviewUrl || imageUrl) : (imagePreviewUrl || imageUrl);
          imagePreview.style.display = 'block';
          imageClearBtn.style.display = 'inline-block';
        };

        // 当音频节点通过连接线连接时调用
        node._onAudioConnected = function(audioUrl, audioName) {
          node.data.audioUrl = audioUrl;
          audioPlayer.src = typeof proxyDownloadUrl === 'function' ? proxyDownloadUrl(audioUrl) : audioUrl;
          audioPreview.style.display = 'block';
          audioClearBtn.style.display = 'inline-block';
        };

        // 生成视频按钮
        generateBtn.addEventListener('click', async function(e) {
          e.stopPropagation();

          // 验证输入
          if (!node.data.prompt || !node.data.prompt.trim()) {
            showToast(_t('dh_no_prompt_error', '请输入提示词'), 'warning');
            return;
          }
          if (!node.data.imageFile && !node.data.imageUrl) {
            showToast(_t('dh_no_image_error', '请上传角色图片或连接图片节点'), 'warning');
            return;
          }
          if (!node.data.audioFile && !node.data.audioUrl) {
            showToast(_t('dh_no_audio_error', '请上传说话音频或连接音频节点'), 'warning');
            return;
          }

          var userId = getUserId();
          if (!userId) {
            showToast(_t('dh_login_required', '请先登录后再使用数字人功能'), 'error');
            return;
          }

          var drawCount = node.data.drawCount || 1;
          // 记录轮询进度，供 onProgress 复用（避免被默认文案覆盖）
          var lastDone = 0, lastTotal = 0;

          try {
            setBtnLoading(generateBtn, _t('dh_generating', '生成中...'));
            statusEl.style.display = 'block';
            statusEl.style.color = '';
            statusEl.textContent = _t('dh_uploading_files', '正在上传文件...');

            // 上传图片（如果需要）
            var imageUrl = node.data.imageUrl;
            if (node.data.imageFile && !imageUrl) {
              imageUrl = await uploadFile(node.data.imageFile);
              if (!imageUrl) {
                throw new Error('图片上传失败');
              }
              node.data.imageUrl = imageUrl;
            }

            // 上传音频（如果需要）
            var audioUrl = node.data.audioUrl;
            if (node.data.audioFile && !audioUrl) {
              audioUrl = await uploadAudioFile(node.data.audioFile);
              if (!audioUrl) {
                throw new Error('音频上传失败');
              }
              node.data.audioUrl = audioUrl;
            }

            statusEl.textContent = _t('dh_submitting_task', '正在提交任务...');

            // 获取数字人任务ID
            var taskId = TaskConfig.getTaskIdByKey(DH_MODEL_KEY_PRIMARY, 'digital_human');
            if (!taskId) {
              taskId = TaskConfig.getTaskIdByKey(DH_MODEL_KEY_FALLBACK, 'digital_human');
            }
            if (!taskId) {
              throw new Error('未找到数字人任务配置');
            }

            // 提交任务（按抽卡次数）
            var form = new FormData();
            form.append('image_urls', imageUrl);
            form.append('audio_urls', audioUrl);
            form.append('prompt', node.data.prompt);
            form.append('task_id', taskId);
            form.append('ratio', state.ratio || '9:16');
            form.append('duration_seconds', DH_DURATION);
            form.append('count', drawCount);
            form.append('user_id', userId);

            var authToken = getAuthToken();
            if (authToken) {
              form.append('auth_token', authToken);
            }

            var res = await fetch('/api/ai-app-run-image', {
              method: 'POST',
              body: form
            });

            var data = await res.json();

            if (!data.project_ids || data.project_ids.length === 0) {
              throw new Error(data.detail || data.message || '提交任务失败');
            }

            var projectIds = data.project_ids;
            node.data.projectId = projectIds[0];
            node.data.projectIds = projectIds;
            statusEl.textContent = _t('dh_task_submitted', '任务已提交，正在生成视频...');

            // === 创建关联视频节点 ===
            var sourceWidth = (el ? el.offsetWidth : 300);
            var createdVideoNodeIds = [];
            var pidToNodeId = {};

            for (var i = 0; i < projectIds.length; i++) {
              var newVideoId = createVideoNode({
                x: node.x + sourceWidth + 60,
                y: node.y + i * 280,
                checkCollision: true
              });

              var newVideoNode = state.nodes.find(function(n) { return n.id === newVideoId; });
              if (newVideoNode) {
                var vName;
                if (projectIds.length > 1) {
                  vName = _tp('dh_video_name_n', { n: (i + 1) }, '数字人视频' + (i + 1));
                } else {
                  vName = _t('dh_video_name', '数字人视频');
                }
                newVideoNode.data.name = vName;
                newVideoNode.title = vName;
                newVideoNode.data.project_id = projectIds[i];

                // 更新节点标题显示
                var newNodeEl = canvasEl.querySelector('.node[data-node-id="' + newVideoId + '"]');
                if (newNodeEl) {
                  var titleEl = newNodeEl.querySelector('.node-title');
                  if (titleEl) titleEl.textContent = vName;
                  var nameEl = newNodeEl.querySelector('.video-name');
                  if (nameEl) nameEl.textContent = vName;
                }

                // 创建连接
                var connId = state.nextConnId++;
                state.connections.push({ id: connId, from: node.id, to: newVideoId });

                // 显示"生成中..."状态
                if (newNodeEl) {
                  var vStatusField = newNodeEl.querySelector('.video-status-field');
                  var vStatusEl = newNodeEl.querySelector('.video-status');
                  if (vStatusField && vStatusEl) {
                    vStatusField.style.display = 'block';
                    setStatusEl(vStatusEl, _t('dh_generating', '生成中...'));
                  }
                }

                createdVideoNodeIds.push(newVideoId);
                pidToNodeId[projectIds[i]] = newVideoId;
              }
            }

            renderAllConnections();
            renderMinimap();
            safeAutoSave();

            node.data._linkedVideoNodeIds = (node.data._linkedVideoNodeIds || []).concat(createdVideoNodeIds);

            // === 轮询多个任务状态（全局 pollVideoStatus）===
            pollVideoStatus(
              projectIds,
              // onProgress
              function(msg) {
                if (lastTotal > 0 && lastDone < lastTotal) {
                  statusEl.textContent = _tp('dh_progress', { done: lastDone, total: lastTotal }, '生成中... ' + lastDone + '/' + lastTotal);
                } else {
                  statusEl.textContent = msg || _t('dh_task_submitted', '任务已提交，正在生成视频...');
                }
              },
              // onComplete（所有任务结束）
              function(result) {
                var tasks = (result && result.tasks) ? result.tasks : [];
                var successCount = 0;
                var hasVideo = false;

                tasks.forEach(function(t) {
                  var vid = pidToNodeId[t.project_id];
                  if (!vid) return;
                  var vn = state.nodes.find(function(n) { return n.id === vid; });
                  if (!vn) return;

                  var videoNodeEl = canvasEl.querySelector('.node[data-node-id="' + vid + '"]');
                  if (t.status === 'SUCCESS' && t.result) {
                    successCount++;
                    hasVideo = true;
                    vn.data.url = t.result;
                    updateNodePreview(vn, t.result);
                    if (videoNodeEl) {
                      var okEl = videoNodeEl.querySelector('.video-status');
                      if (okEl) setStatusEl(okEl, _t('dh_generate_success', '生成成功！'), '#16a34a');
                    }
                  } else {
                    // 失败
                    if (videoNodeEl) {
                      var failEl = videoNodeEl.querySelector('.video-status');
                      if (failEl) setStatusEl(failEl, _t('dh_generate_failed', '生成失败'), '#dc2626');
                    }
                  }
                });

                // 更新数字人节点状态
                if (hasVideo && successCount === tasks.length) {
                  node.data.status = 'SUCCESS';
                  statusEl.style.color = '#16a34a';
                  statusEl.textContent = _t('dh_generate_success', '生成成功！');
                } else if (hasVideo) {
                  node.data.status = 'PARTIAL';
                  statusEl.style.color = '#d97706';
                  statusEl.textContent = _t('dh_generate_success', '生成成功！') + ' (' + successCount + '/' + tasks.length + ')';
                } else {
                  node.data.status = 'FAILED';
                  statusEl.style.color = '#dc2626';
                  statusEl.textContent = _t('dh_generate_failed', '生成失败');
                }

                setBtnReady(generateBtn, _t('dh_generate_btn', '生成视频'));
                if (hasVideo) {
                  showToast(_t('dh_generate_success', '数字人视频生成成功'), 'success');
                } else {
                  showToast(_t('dh_generate_failed', '数字人视频生成失败'), 'error');
                }
                // 刷新用户算力显示
                if (typeof fetchComputingPower === 'function') {
                  fetchComputingPower();
                }
                safeAutoSave();
              },
              // onError
              function(msg) {
                node.data.status = 'FAILED';
                statusEl.style.color = '#dc2626';
                statusEl.textContent = msg || _t('dh_generate_failed', '生成失败');
                setBtnReady(generateBtn, _t('dh_generate_btn', '生成视频'));

                // 标记关联视频节点为失败
                createdVideoNodeIds.forEach(function(vid) {
                  var videoEl2 = canvasEl.querySelector('.node[data-node-id="' + vid + '"]');
                  if (videoEl2) {
                    var vStatusEl2 = videoEl2.querySelector('.video-status');
                    if (vStatusEl2) setStatusEl(vStatusEl2, _t('dh_generate_failed', '生成失败'), '#dc2626');
                  }
                });
              },
              // onTaskUpdate（实时逐任务更新）
              function(tasks) {
                if (!tasks || !tasks.length) return;
                var done = 0;
                tasks.forEach(function(t) {
                  var vid = pidToNodeId[t.project_id];
                  if (!vid) return;
                  if (t.status === 'SUCCESS' && t.result) {
                    done++;
                    var vn = state.nodes.find(function(n) { return n.id === vid; });
                    if (vn) {
                      vn.data.url = t.result;
                      updateNodePreview(vn, t.result);
                    }
                    var videoNodeEl = canvasEl.querySelector('.node[data-node-id="' + vid + '"]');
                    if (videoNodeEl) {
                      var okEl = videoNodeEl.querySelector('.video-status');
                      if (okEl) setStatusEl(okEl, _t('dh_generate_success', '生成成功！'), '#16a34a');
                    }
                  }
                });
                // 进度提示
                lastDone = done;
                lastTotal = tasks.length;
                if (done < tasks.length) {
                  statusEl.textContent = _tp('dh_progress', { done: done, total: tasks.length }, '生成中... ' + done + '/' + tasks.length);
                }
              }
            );
          } catch (error) {
            console.error('数字人视频生成失败:', error);
            statusEl.style.color = '#dc2626';
            statusEl.textContent = _t('dh_generate_failed', '生成失败') + ': ' + (error.message || '未知错误');
            setBtnReady(generateBtn, _t('dh_generate_btn', '生成视频'));
            showToast(_t('dh_generate_failed', '数字人视频生成失败'), 'error');
          }
        });
      }
    }, opts);
  }

  var createDigitalHumanNodeWithData = createNodeWithDataFactory(
    createDigitalHumanNode,
    function(el, node) {
      // createNodeWithDataFactory 会调用 onCreated，
      // 在 onCreated 中已经处理了数据恢复，这里不需要额外处理
    }
  );

  // 注册到全局
  window.createDigitalHumanNode = createDigitalHumanNode;
  window.createDigitalHumanNodeWithData = createDigitalHumanNodeWithData;

  // ─── 注册输入端口（供连接系统自动发现）───
  registerInputPorts('digital_human', [
    PORT_PRESETS.IMAGE_INPUT({
      guard: function(n) { return !n.data.imageUrl; },
      onConnect: function(fromNode, targetNode) {
        targetNode.data.imageUrl = fromNode.data.url || '';
        targetNode.data.imagePreview = fromNode.data.preview || fromNode.data.url || '';
        if (typeof targetNode._onImageConnected === 'function') {
          targetNode._onImageConnected(fromNode.data.url, fromNode.data.preview || fromNode.data.url);
        }
      }
    }),
    PORT_PRESETS.AUDIO_INPUT({
      guard: function(n) { return !n.data.audioUrl; },
      onConnect: function(fromNode, targetNode) {
        targetNode.data.audioUrl = fromNode.data.url;
        if (typeof targetNode._onAudioConnected === 'function') {
          targetNode._onAudioConnected(fromNode.data.url, fromNode.data.name || '连接的音频');
        }
      }
    })
  ]);

  // 注册到节点注册表
  registerNodeType('digital_human', {
    createFn: createDigitalHumanNode,
    createWithDataFn: createDigitalHumanNodeWithData
  });

})();
