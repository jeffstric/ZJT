// ============================
// text_to_speech_node.js - 文字转语音节点
// 使用 createNodeBase 基类工厂
// ============================

(function() {

  var TTS_PORTS = [
    { direction: 'output', titleI18nKey: 'tts_output_port' }
  ];

  function createTextToSpeechNode(opts) {
    return createNodeBase({
      type: 'text_to_speech',
      title: function() { return window.t ? window.t('tts_title') : '文字转语音'; },
      defaultData: {
        text: '',
        refAudioFile: null,
        refAudioUrl: '',
        emoRefAudioFile: null,
        emoRefAudioUrl: '',
        emoWeight: 1.0,
        emoControlMethod: 0,
        audioUrl: '',
        audioId: null,
        status: ''
      },
      ports: TTS_PORTS,
      width: 280,
      height: 250,
      titleIcon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M12 2C13.1046 2 14 2.89543 14 4V12C14 13.1046 13.1046 14 12 14C10.8954 14 10 13.1046 10 12V4C10 2.89543 10.8954 2 12 2Z"/><path d="M17 10V12C17 14.7614 14.7614 17 12 17C9.23858 17 7 14.7614 7 12V10" stroke-linecap="round"/><path d="M12 17V21M12 21H8M12 21H16" stroke-linecap="round"/></svg>',
      bodyHtml: function() {
        return '<div class="field">' +
          '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">' +
            '<div class="label" style="margin: 0;">' + (window.t ? window.t('tts_text_label') : '生成文本') + ' <span style="color: red;">*</span></div>' +
            '<button class="mini-btn tts-text-expand-btn" type="button" style="font-size: 11px; padding: 4px 8px;" title="' + (window.t ? window.t('script_expand_btn') : '放大编辑') + '">\u2922</button>' +
          '</div>' +
          '<textarea class="tts-text" rows="3" placeholder="' + (window.t ? window.t('tts_text_placeholder') : '输入要转换为语音的文本') + '"></textarea>' +
        '</div>' +
        '<div class="field">' +
          '<div class="label">' + (window.t ? window.t('tts_ref_audio_label') : '参考音色音频（可选）') + '</div>' +
          '<input class="tts-ref-audio" type="file" accept="audio/*" />' +
          '<div class="tts-ref-preview" style="display:none; margin-top:4px;">' +
            '<audio class="tts-ref-audio-player" controls style="width:100%; max-height:32px;"></audio>' +
            '<button class="mini-btn tts-ref-clear" type="button" style="margin-top:4px;">' + (window.t ? window.t('tts_clear_btn') : '清除') + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="field">' +
          '<div class="label">' + (window.t ? window.t('tts_emo_method_label') : '情感控制方式') + '</div>' +
          '<select class="tts-emo-method">' +
            '<option value="0">' + (window.t ? window.t('tts_emo_same_as_ref') : '与参考音频相同') + '</option>' +
            '<option value="1">' + (window.t ? window.t('tts_emo_use_ref') : '使用情感参考音频') + '</option>' +
          '</select>' +
        '</div>' +
        '<div class="field tts-emo-ref-field" style="display:none;">' +
          '<div class="label">' + (window.t ? window.t('tts_emo_ref_label') : '情感参考音频') + '</div>' +
          '<input class="tts-emo-ref-audio" type="file" accept="audio/*" />' +
          '<div class="tts-emo-ref-preview" style="display:none; margin-top:4px;">' +
            '<audio class="tts-emo-ref-audio-player" controls style="width:100%; max-height:32px;"></audio>' +
            '<button class="mini-btn tts-emo-ref-clear" type="button" style="margin-top:4px;">' + (window.t ? window.t('tts_clear_btn') : '清除') + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="field tts-emo-weight-field" style="display:none;">' +
          '<div class="label">' + (window.t ? window.t('tts_emo_weight_label') : '情感权重') + ' (<span class="tts-emo-weight-value">1.0</span>)</div>' +
          '<input type="range" class="tts-emo-weight" min="0" max="1.6" step="0.1" value="1.0" style="width:100%;" />' +
          '<div class="gen-meta" style="margin-top:4px;">' + (window.t ? window.t('tts_emo_weight_hint') : '调整情感的强度，0为无情感，1.6为最强情感') + '</div>' +
        '</div>' +
        '<div class="field">' +
          '<button class="gen-btn tts-generate-btn" type="button">' + (window.t ? window.t('tts_generate_btn') : '生成语音') + '</button>' +
          '<div class="gen-meta tts-status" style="display:none;"></div>' +
        '</div>' +
        '<div class="field tts-result-field" style="display:none;">' +
          '<div class="label">' + (window.t ? window.t('tts_result_label') : '生成结果') + '</div>' +
          '<audio class="tts-result-audio" controls style="width:100%; margin-bottom:8px;"></audio>' +
          '<div style="display:flex; gap:8px;">' +
            '<button class="mini-btn tts-download-btn" type="button">' + (window.t ? window.t('tts_download_btn') : '下载音频') + '</button>' +
          '</div>' +
        '</div>';
      },
      onCreated: function(node, el) {
        var textEl = el.querySelector('.tts-text');
        var textExpandBtn = el.querySelector('.tts-text-expand-btn');
        var refAudioEl = el.querySelector('.tts-ref-audio');
        var refPreviewEl = el.querySelector('.tts-ref-preview');
        var refAudioPlayer = el.querySelector('.tts-ref-audio-player');
        var refClearBtn = el.querySelector('.tts-ref-clear');
        var emoMethodEl = el.querySelector('.tts-emo-method');
        var emoRefField = el.querySelector('.tts-emo-ref-field');
        var emoRefAudioEl = el.querySelector('.tts-emo-ref-audio');
        var emoRefPreviewEl = el.querySelector('.tts-emo-ref-preview');
        var emoRefAudioPlayer = el.querySelector('.tts-emo-ref-audio-player');
        var emoRefClearBtn = el.querySelector('.tts-emo-ref-clear');
        var emoWeightField = el.querySelector('.tts-emo-weight-field');
        var emoWeightEl = el.querySelector('.tts-emo-weight');
        var emoWeightValueEl = el.querySelector('.tts-emo-weight-value');
        var generateBtn = el.querySelector('.tts-generate-btn');
        var statusEl = el.querySelector('.tts-status');
        var resultField = el.querySelector('.tts-result-field');
        var resultAudio = el.querySelector('.tts-result-audio');
        var downloadBtn = el.querySelector('.tts-download-btn');

        // 文本输入
        textEl.addEventListener('input', function() {
          node.data.text = textEl.value;
        });

        // 文本放大按钮
        textExpandBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          showPromptExpandModal(textEl, window.t ? window.t('tts_text_label') : '生成文本', function(newValue) {
            node.data.text = newValue;
          });
        });

        // 参考音色音频上传
        refAudioEl.addEventListener('change', function() {
          var file = refAudioEl.files && refAudioEl.files[0];
          if (!file) return;
          node.data.refAudioFile = file;
          if (refAudioPlayer.src && refAudioPlayer.src.startsWith('blob:')) URL.revokeObjectURL(refAudioPlayer.src);
          var localUrl = URL.createObjectURL(file);
          refAudioPlayer.src = localUrl;
          refPreviewEl.style.display = 'block';
        });

        // 清除参考音色
        refClearBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          node.data.refAudioFile = null;
          refAudioPlayer.removeAttribute('src');
          refAudioPlayer.load();
          refPreviewEl.style.display = 'none';
          refAudioEl.value = '';
        });

        // 情感控制方式切换
        emoMethodEl.addEventListener('change', function() {
          node.data.emoControlMethod = parseInt(emoMethodEl.value);
          var showEmoRef = node.data.emoControlMethod === 1;
          emoRefField.style.display = showEmoRef ? 'block' : 'none';
          emoWeightField.style.display = showEmoRef ? 'block' : 'none';
        });

        // 情感参考音频上传
        emoRefAudioEl.addEventListener('change', function() {
          var file = emoRefAudioEl.files && emoRefAudioEl.files[0];
          if (!file) return;
          node.data.emoRefAudioFile = file;
          if (emoRefAudioPlayer.src && emoRefAudioPlayer.src.startsWith('blob:')) URL.revokeObjectURL(emoRefAudioPlayer.src);
          var localUrl = URL.createObjectURL(file);
          emoRefAudioPlayer.src = localUrl;
          emoRefPreviewEl.style.display = 'block';
        });

        // 清除情感参考
        emoRefClearBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          node.data.emoRefAudioFile = null;
          emoRefAudioPlayer.removeAttribute('src');
          emoRefAudioPlayer.load();
          emoRefPreviewEl.style.display = 'none';
          emoRefAudioEl.value = '';
        });

        // 情感权重滑块
        emoWeightEl.addEventListener('input', function() {
          node.data.emoWeight = parseFloat(emoWeightEl.value);
          emoWeightValueEl.textContent = node.data.emoWeight.toFixed(1);
        });

        // 生成语音按钮
        generateBtn.addEventListener('click', async function(e) {
          e.stopPropagation();

          if (!node.data.text.trim()) {
            showToast(window.t ? window.t('tts_no_text_error') : '请输入生成文本', 'warning');
            return;
          }

          var userId = getUserId();
          if (!userId) {
            showToast(window.t ? window.t('tts_login_required') : '请先登录后再使用语音生成功能', 'error');
            return;
          }

          try {
            setBtnLoading(generateBtn, window.t ? window.t('tts_generating') : '生成中...');
            statusEl.style.display = 'block';
            statusEl.style.color = '';
            statusEl.textContent = window.t ? window.t('tts_generating_audio') : '正在生成音频...';
            resultField.style.display = 'none';

            var form = new FormData();
            form.append('text', node.data.text);
            form.append('user_id', userId);
            form.append('emo_control_method', node.data.emoControlMethod);

            if (node.data.refAudioFile) {
              form.append('ref_audio', node.data.refAudioFile);
            }

            if (node.data.emoControlMethod === 1) {
              if (node.data.emoRefAudioFile) {
                form.append('emo_ref_audio', node.data.emoRefAudioFile);
              }
              form.append('emo_weight', node.data.emoWeight);
            }

            var authToken = getAuthToken();
            if (authToken) {
              form.append('auth_token', authToken);
            }

            var res = await fetch('/api/audio-generate', {
              method: 'POST',
              body: form
            });

            if (!res.ok) {
              var errorText = await res.text();
              throw new Error('服务器错误 (' + res.status + '): ' + (errorText || '请求失败'));
            }

            var result = await res.json();
            node.data.audioId = result.audio_id;
            node.data.status = result.status || 'submitted';

            if (node.data.audioId) {
              pollAudioStatus(node.id, node);
            }

          } catch (error) {
            console.error('语音生成失败:', error);
            statusEl.style.color = '#dc2626';
            statusEl.textContent = (window.t ? window.t('tts_generate_failed') : '生成失败') + ': ' + (error.message || '未知错误');
            setBtnReady(generateBtn, window.t ? window.t('tts_generate_btn') : '生成语音');
            showToast(window.t ? window.t('tts_generate_failed') : '语音生成失败', 'error');
          }
        });

        // 轮询音频状态
        function pollAudioStatus(nodeId, node) {
          pollTaskStatus({
            statusUrl: '/api/audio-status/' + node.data.audioId,
            onSuccess: function(payload) {
              if (payload.result_url) {
                node.data.audioUrl = payload.result_url;
                resultAudio.src = payload.result_url;
                resultField.style.display = 'block';
              }
              statusEl.style.color = '#16a34a';
              statusEl.textContent = window.t ? window.t('tts_generate_success') : '生成成功！';
              setBtnReady(generateBtn, window.t ? window.t('tts_generate_btn') : '生成语音');
              showToast(window.t ? window.t('tts_generate_success') : '语音生成成功', 'success');
            },
            onFailed: function(payload) {
              statusEl.style.color = '#dc2626';
              statusEl.textContent = (window.t ? window.t('tts_generate_failed') : '生成失败') + ': ' + (payload.reason || payload.message || '未知错误');
              setBtnReady(generateBtn, window.t ? window.t('tts_generate_btn') : '生成语音');
              showToast(window.t ? window.t('tts_generate_failed') : '语音生成失败', 'error');
            },
            onTimeout: function() {
              statusEl.style.color = '#dc2626';
              statusEl.textContent = window.t ? window.t('tts_generate_timeout_hint') : '等待超时，但音频仍在生成中。你可以通过刷新页面后查看是否生成成功。';
              setBtnReady(generateBtn, window.t ? window.t('tts_generate_btn') : '生成语音');
            }
          });
        }

        // 下载按钮
        downloadBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          if (!node.data.audioUrl) {
            showToast(window.t ? window.t('tts_no_audio_error') : '没有可下载的音频', 'error');
            return;
          }

          var now = new Date();
          var dateStr = now.getFullYear().toString() +
                        (now.getMonth() + 1).toString().padStart(2, '0') +
                        now.getDate().toString().padStart(2, '0');
          var timeStr = now.getHours().toString().padStart(2, '0') +
                        now.getMinutes().toString().padStart(2, '0');
          var filename = 'audio_' + dateStr + '_' + timeStr + '.wav';

          if (node.data.audioUrl.startsWith('blob:')) {
            var link = document.createElement('a');
            link.href = node.data.audioUrl;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
          } else {
            var downloadUrl = '/api/download?url=' + encodeURIComponent(node.data.audioUrl) + '&filename=' + encodeURIComponent(filename);
            window.open(downloadUrl, '_blank');
          }
          showToast(window.t ? window.t('tts_download_start') : '开始下载', 'success');
        });
      }
    }, opts);
  }

  var createTextToSpeechNodeWithData = createNodeWithDataFactory(
    createTextToSpeechNode,
    function(el, node) {
      var textEl = el.querySelector('.tts-text');
      var emoMethodEl = el.querySelector('.tts-emo-method');
      var emoRefField = el.querySelector('.tts-emo-ref-field');
      var emoWeightField = el.querySelector('.tts-emo-weight-field');
      var emoWeightEl = el.querySelector('.tts-emo-weight');
      var emoWeightValueEl = el.querySelector('.tts-emo-weight-value');
      var statusEl = el.querySelector('.tts-status');
      var resultField = el.querySelector('.tts-result-field');
      var resultAudio = el.querySelector('.tts-result-audio');

      if (textEl && node.data.text) {
        textEl.value = node.data.text;
      }

      if (emoMethodEl) {
        emoMethodEl.value = node.data.emoControlMethod || 0;
        var showEmoRef = node.data.emoControlMethod === 1;
        if (emoRefField) emoRefField.style.display = showEmoRef ? 'block' : 'none';
        if (emoWeightField) emoWeightField.style.display = showEmoRef ? 'block' : 'none';
      }

      if (emoWeightEl && node.data.emoWeight !== undefined) {
        emoWeightEl.value = node.data.emoWeight;
        if (emoWeightValueEl) emoWeightValueEl.textContent = node.data.emoWeight.toFixed(1);
      }

      if (node.data.audioUrl && resultAudio) {
        resultAudio.src = proxyDownloadUrl(node.data.audioUrl);
        if (resultField) resultField.style.display = 'block';
      }

      if (node.data.status && statusEl) {
        statusEl.style.display = 'block';
        if (node.data.status === 'SUCCESS') {
          statusEl.style.color = '#16a34a';
          statusEl.textContent = window.t ? window.t('tts_generate_success') : '生成成功！';
        } else if (node.data.status === 'FAILED') {
          statusEl.style.color = '#dc2626';
          statusEl.textContent = window.t ? window.t('tts_generate_failed') : '生成失败';
        }
      }
    }
  );

  // 注册到全局
  window.createTextToSpeechNode = createTextToSpeechNode;
  window.createTextToSpeechNodeWithData = createTextToSpeechNodeWithData;

  // 注册到节点注册表
  registerNodeType('text_to_speech', {
    createFn: createTextToSpeechNode,
    createWithDataFn: createTextToSpeechNodeWithData
  });

})();
