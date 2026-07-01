// ============================
// dialogue_group_node.js - 对话组节点
// 使用 createNodeBase 基类工厂
// ============================

(function() {

  function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // 截断过长的角色名称，超过 maxLen 只显示首尾
  function truncateName(name, maxLen) {
    maxLen = maxLen || 10;
    if (!name) return '';
    if (name.length <= maxLen) return name;
    var headLen = Math.ceil(maxLen * 0.4);
    var tailLen = Math.floor(maxLen * 0.3);
    return name.substring(0, headLen) + '...' + name.substring(name.length - tailLen);
  }

  var DIALOGUE_GROUP_PORTS = [
    { direction: 'input', titleI18nKey: 'dialogue_input_port_title', acceptType: 'shot_frame', connectionType: 'connections' },
    { direction: 'input', cssClass: 'video-input-port', titleI18nKey: 'dialogue_video_input_port_title' },
    { direction: 'output', titleI18nKey: 'dialogue_output_port_title' }
  ];

  function createDialogueGroupNode(opts) {
    var dialogueData = opts && opts.dialogueData ? opts.dialogueData : [];
    var shotNumber = opts && opts.shotNumber ? opts.shotNumber : null;

    return createNodeBase({
      type: 'dialogue_group',
      title: function() { return window.t ? window.t('dialogue_group_title') : '对话组'; },
      defaultData: function(o) {
        var dData = o && o.dialogueData ? o.dialogueData : [];
        var sNum = o && o.shotNumber ? o.shotNumber : null;
        return {
          dialogues: dData,
          audioResults: {},
          emoControlMethod: 0,
          emoVec: [0, 0, 0, 0, 0, 0, 0, 0],
          emoWeight: 1,
          emoRefAudioUrl: null,
          shotNumber: sNum,
          referenceAudios: []
        };
      },
      ports: DIALOGUE_GROUP_PORTS,
      width: 400,
      height: 300,
      titleIcon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M8 12H8.01M12 12H12.01M16 12H16.01" stroke-linecap="round"/><path d="M3 7C3 5.89543 3.89543 5 5 5H19C20.1046 5 21 5.89543 21 7V15C21 16.1046 20.1046 17 19 17H13L9 21V17H5C3.89543 17 3 16.1046 3 15V7Z"/></svg>',
      bodyHtml: function() {
        var dialogueItemsHtml = '';
        if (dialogueData && dialogueData.length > 0) {
          for (var di = 0; di < dialogueData.length; di++) {
            var dialogue = dialogueData[di];
            var characterName = dialogue.character_name || '未知角色';
            var text = dialogue.text || '';
            dialogueItemsHtml +=
              '<div class="dialogue-item" data-index="' + di + '" style="margin-bottom: 12px; padding: 12px; background: #f9fafb; border-radius: 8px; border: 1px solid #e5e7eb;">' +
                '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">' +
                  '<div style="font-weight: 600; color: #374151; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="' + escapeHtml(characterName) + '">' + escapeHtml(truncateName(characterName)) + '</div>' +
                  '<button class="mini-btn dialogue-generate-btn" data-index="' + di + '" type="button" style="font-size: 11px; padding: 4px 8px;" data-i18n="dialogue_generate_btn">' + (window.t ? window.t('dialogue_generate_btn') : '生成音频') + '</button>' +
                '</div>' +
                '<div style="color: #6b7280; font-size: 13px; margin-bottom: 8px;">"' + escapeHtml(text) + '"</div>' +
                '<div class="dialogue-status" data-index="' + di + '" style="display:none; font-size: 12px; color: #6b7280; margin-bottom: 8px;"></div>' +
                '<div class="dialogue-result" data-index="' + di + '" style="display:none;">' +
                  '<audio controls style="width:100%; max-height:32px; margin-bottom: 6px;"></audio>' +
                  '<button class="mini-btn dialogue-download-btn" data-index="' + di + '" type="button" style="font-size: 11px; padding: 4px 8px; display: none;" data-i18n="dialogue_download_btn">' + (window.t ? window.t('dialogue_download_btn') : '下载') + '</button>' +
                '</div>' +
              '</div>';
          }
        } else {
          dialogueItemsHtml = '<div class="gen-meta" style="text-align:center; padding: 20px;" data-i18n="dialogue_no_data">' + (window.t ? window.t('dialogue_no_data') : '暂无对话数据') + '</div>';
        }

        var emoVecHtml = [
          { key: 'emo_joy', cn: '喜' },
          { key: 'emo_anger', cn: '怒' },
          { key: 'emo_sadness', cn: '哀' },
          { key: 'emo_fear', cn: '惧' },
          { key: 'emo_disgust', cn: '厌恶' },
          { key: 'emo_depression', cn: '低落' },
          { key: 'emo_surprise', cn: '惊喜' },
          { key: 'emo_calm', cn: '平静' }
        ].map(function(item, idx) {
          return '<div style="margin-bottom: 8px;">' +
            '<div style="display: flex; justify-content: space-between; margin-bottom: 2px;">' +
              '<span data-i18n="' + item.key + '">' + (window.t ? window.t(item.key) : item.cn) + '</span>' +
              '<span class="dialogue-emo-vec-value" data-index="' + idx + '">0.00</span>' +
            '</div>' +
            '<input type="range" class="dialogue-emo-vec-slider" data-index="' + idx + '" min="0" max="1.5" step="0.01" value="0" style="width: 100%;">' +
          '</div>';
        }).join('');

        return '<div class="field field-always-visible">' +
          '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">' +
            '<div class="label" style="margin: 0;" data-i18n="dialogue_list_label">' + (window.t ? window.t('dialogue_list_label') : '对话列表') + '</div>' +
          '</div>' +
          '<div class="dialogue-items-container">' + dialogueItemsHtml + '</div>' +
        '</div>' +
        '<div class="field field-collapsible" style="margin-bottom: 12px;">' +
          '<label class="label" style="font-size: 12px; margin-bottom: 4px;" data-i18n="emo_control_method_label">' + (window.t ? window.t('emo_control_method_label') : '情感控制方式') + '</label>' +
          '<select class="dialogue-emo-control-select" style="width: 100%; padding: 6px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 12px; background: #ffffff; color: #111827;">' +
            '<option value="0" data-i18n="emo_control_same_ref">' + (window.t ? window.t('emo_control_same_ref') : '与参考音频相同') + '</option>' +
            '<option value="1" data-i18n="emo_control_ref_audio">' + (window.t ? window.t('emo_control_ref_audio') : '使用情感参考音频') + '</option>' +
            '<option value="2" data-i18n="emo_control_vector">' + (window.t ? window.t('emo_control_vector') : '使用情感向量') + '</option>' +
          '</select>' +
        '</div>' +
        '<div class="dialogue-emo-ref-audio-field field-collapsible" style="margin-bottom: 12px;">' +
          '<label class="label" style="font-size: 12px; margin-bottom: 4px;" data-i18n="emo_ref_audio_label">' + (window.t ? window.t('emo_ref_audio_label') : '情感参考音频') + '</label>' +
          '<input type="file" class="dialogue-emo-ref-audio-input" accept="audio/*" style="width: 100%; padding: 4px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 11px; background: #f9fafb;">' +
          '<div class="dialogue-emo-ref-audio-preview" style="display: none; margin-top: 6px;">' +
            '<audio controls style="width: 100%; max-height: 32px; margin-bottom: 4px;"></audio>' +
            '<button class="mini-btn dialogue-emo-ref-audio-clear-btn" type="button" style="font-size: 11px; padding: 4px 8px;" data-i18n="emo_ref_audio_clear">' + (window.t ? window.t('emo_ref_audio_clear') : '清除音频') + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="dialogue-emo-weight-field field-collapsible" style="display: none; margin-bottom: 12px;">' +
          '<label class="label" style="font-size: 12px; margin-bottom: 4px;" data-i18n="emo_weight_label">' + (window.t ? window.t('emo_weight_label') : '情感权重') + ': <span class="dialogue-emo-weight-value">1.0</span></label>' +
          '<input type="range" class="dialogue-emo-weight-slider" min="0" max="1.6" step="0.1" value="1" style="width: 100%;">' +
          '<div style="font-size: 11px; color: #6b7280; margin-top: 2px;" data-i18n="emo_weight_hint">' + (window.t ? window.t('emo_weight_hint') : '调整情感强度，0为无情感，1.6为最强情感') + '</div>' +
        '</div>' +
        '<div class="dialogue-emo-vec-field field-collapsible" style="display: none; margin-bottom: 12px;">' +
          '<label class="label" style="font-size: 12px; margin-bottom: 6px;" data-i18n="emo_vec_label">' + (window.t ? window.t('emo_vec_label') : '情感向量控制') + '</label>' +
          '<div class="dialogue-emo-vec-sliders" style="font-size: 11px;">' + emoVecHtml + '</div>' +
          '<div style="font-size: 11px; margin-top: 4px;">' +
            '<span data-i18n="emo_vec_sum">' + (window.t ? window.t('emo_vec_sum') : '总和') + '</span>: <span class="dialogue-emo-vec-sum" style="font-weight: bold;">0.00</span> / 1.5' +
            '<span class="dialogue-emo-vec-warning" style="color: #dc2626; display: none; margin-left: 8px;" data-i18n="emo_vec_warning">' + (window.t ? window.t('emo_vec_warning') : '情感向量之和不能超过1.5') + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="field field-collapsible" style="margin-bottom: 12px;">' +
          '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">' +
            '<label class="label" style="font-size: 12px; margin: 0;" data-i18n="ref_audio_label">' + (window.t ? window.t('ref_audio_label') : '参考音频') + '</label>' +
            '<button class="mini-btn dialogue-add-ref-audio-btn" type="button" style="font-size: 11px; padding: 4px 8px;" data-i18n="ref_audio_add">' + (window.t ? window.t('ref_audio_add') : '添加音频') + '</button>' +
          '</div>' +
          '<div style="font-size: 11px; color: #6b7280; margin-bottom: 8px;" data-i18n="ref_audio_hint">' + (window.t ? window.t('ref_audio_hint') : '最多6个音频，每个不超过20秒、10MB') + '</div>' +
          '<div class="dialogue-ref-audios-list"></div>' +
        '</div>' +
        '<div class="field field-collapsible">' +
          '<button class="mini-btn dialogue-generate-all-btn" type="button" style="font-size: 11px; padding: 4px 8px; width: 100%;" data-i18n="dialogue_generate_all">' + (window.t ? window.t('dialogue_generate_all') : '生成全部') + '</button>' +
        '</div>';
      },
      onCreated: function(node, el) {
        var generateAllBtn = el.querySelector('.dialogue-generate-all-btn');
        var emoControlSelect = el.querySelector('.dialogue-emo-control-select');
        var emoRefAudioField = el.querySelector('.dialogue-emo-ref-audio-field');
        var emoRefAudioInput = el.querySelector('.dialogue-emo-ref-audio-input');
        var emoRefAudioPreview = el.querySelector('.dialogue-emo-ref-audio-preview');
        var emoRefAudioClearBtn = el.querySelector('.dialogue-emo-ref-audio-clear-btn');
        var emoWeightField = el.querySelector('.dialogue-emo-weight-field');
        var emoWeightSlider = el.querySelector('.dialogue-emo-weight-slider');
        var emoWeightValue = el.querySelector('.dialogue-emo-weight-value');
        var emoVecField = el.querySelector('.dialogue-emo-vec-field');
        var emoVecSliders = el.querySelectorAll('.dialogue-emo-vec-slider');
        var emoVecSum = el.querySelector('.dialogue-emo-vec-sum');
        var emoVecWarning = el.querySelector('.dialogue-emo-vec-warning');
        var addRefAudioBtn = el.querySelector('.dialogue-add-ref-audio-btn');
        var refAudiosList = el.querySelector('.dialogue-ref-audios-list');
        var videoInputPort = el.querySelector('.port.video-input-port');

        // 绑定输入端口连接事件（shot_frame 类型）
        bindInputPortEvents(el, node, {
          cssClass: null,
          acceptType: 'shot_frame',
          connectionType: 'connections',
          onConnect: function(fromNode) {
            var shotJson = fromNode.data.shotJson;
            if (shotJson && shotJson.dialogue) {
              node.data.dialogues = JSON.parse(JSON.stringify(shotJson.dialogue));
              updateDialogueList();
            }
          }
        });

        // mousedown 时更新按钮可见性
        el.addEventListener('mousedown', function() {
          updateButtonsVisibility(true);
        });

        // 情感控制方式切换
        emoControlSelect.addEventListener('change', function(e) {
          e.stopPropagation();
          var method = parseInt(e.target.value);
          node.data.emoControlMethod = method;

          var isEmoRefMode = method === 1;
          emoRefAudioField.style.opacity = isEmoRefMode ? '1' : '0.5';
          emoRefAudioField.style.pointerEvents = isEmoRefMode ? 'auto' : 'none';
          emoRefAudioInput.disabled = !isEmoRefMode;
          if (emoRefAudioClearBtn) emoRefAudioClearBtn.disabled = !isEmoRefMode;

          emoWeightField.style.display = method === 1 ? 'block' : 'none';
          emoVecField.style.display = method === 2 ? 'block' : 'none';

          if (videoInputPort) {
            if (isEmoRefMode) {
              videoInputPort.classList.remove('disabled');
            } else {
              videoInputPort.classList.add('disabled');
            }
          }

          safeAutoSave();
        });

        // 情感参考音频上传
        emoRefAudioInput.addEventListener('change', async function(e) {
          e.stopPropagation();
          var file = e.target.files[0];
          if (!file) return;

          try {
            var uploadedUrl = await uploadFile(file);
            if (uploadedUrl) {
              node.data.emoRefAudioUrl = uploadedUrl;
              var audio = emoRefAudioPreview.querySelector('audio');
              if (audio) {
                audio.src = proxyDownloadUrl(uploadedUrl);
                emoRefAudioPreview.style.display = 'block';
              }
              showToast(window.t ? window.t('emo_ref_audio_uploaded') : '情感参考音频上传成功', 'success');
              safeAutoSave();
            }
          } catch (error) {
            console.error('情感参考音频上传失败:', error);
            showToast(window.t ? window.t('emo_ref_audio_upload_failed') : '情感参考音频上传失败', 'error');
          }
        });

        // 清除情感参考音频
        emoRefAudioClearBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          node.data.emoRefAudioUrl = null;
          emoRefAudioInput.value = '';
          emoRefAudioPreview.style.display = 'none';
          var audio = emoRefAudioPreview.querySelector('audio');
          if (audio) audio.src = '';
          showToast(window.t ? window.t('emo_ref_audio_cleared') : '已清除情感参考音频', 'success');
          safeAutoSave();
        });

        // 情感权重滑块
        emoWeightSlider.addEventListener('input', function(e) {
          e.stopPropagation();
          var value = parseFloat(e.target.value);
          node.data.emoWeight = value;
          emoWeightValue.textContent = value.toFixed(1);
        });
        emoWeightSlider.addEventListener('change', function() {
          safeAutoSave();
        });

        // 情感向量
        function updateEmoVecSum() {
          var sum = node.data.emoVec.reduce(function(acc, val) { return acc + val; }, 0);
          emoVecSum.textContent = sum.toFixed(2);
          if (sum > 1.5) {
            emoVecSum.style.color = '#dc2626';
            emoVecWarning.style.display = 'inline';
          } else {
            emoVecSum.style.color = '#16a34a';
            emoVecWarning.style.display = 'none';
          }
        }

        for (var vsi = 0; vsi < emoVecSliders.length; vsi++) {
          (function(slider) {
            slider.addEventListener('input', function(e) {
              e.stopPropagation();
              var index = parseInt(slider.dataset.index);
              var value = parseFloat(e.target.value);
              node.data.emoVec[index] = value;

              var valueSpan = el.querySelector('.dialogue-emo-vec-value[data-index="' + index + '"]');
              if (valueSpan) valueSpan.textContent = value.toFixed(2);

              updateEmoVecSum();
            });

            slider.addEventListener('change', function() {
              safeAutoSave();
            });
          })(emoVecSliders[vsi]);
        }

        // 验证音频文件
        function validateAudioFile(file) {
          var maxSize = 10 * 1024 * 1024;
          var maxDuration = 20;

          if (file.size > maxSize) {
            showToast(window.t ? window.t('audio_file_too_large') : '音频文件不能超过10MB', 'error');
            return Promise.resolve(false);
          }

          return new Promise(function(resolve) {
            var audio = new Audio();
            var url = URL.createObjectURL(file);

            audio.addEventListener('loadedmetadata', function() {
              URL.revokeObjectURL(url);
              if (audio.duration > maxDuration) {
                var msg = window.t ? window.t('audio_duration_exceeded', { max: maxDuration, current: audio.duration.toFixed(1) }) : ('音频时长不能超过' + maxDuration + '秒，当前时长：' + audio.duration.toFixed(1) + '秒');
                showToast(msg, 'error');
                resolve(false);
              } else {
                resolve(true);
              }
            });

            audio.addEventListener('error', function() {
              URL.revokeObjectURL(url);
              showToast(window.t ? window.t('audio_read_error') : '无法读取音频文件', 'error');
              resolve(false);
            });

            audio.src = url;
          });
        }

        // 渲染参考音频列表
        function renderRefAudiosList() {
          if (!node.data.referenceAudios) {
            node.data.referenceAudios = [];
          }

          if (node.data.referenceAudios.length === 0) {
            refAudiosList.innerHTML = '<div style="text-align: center; color: #9ca3af; padding: 12px; font-size: 12px;">' + (window.t ? window.t('no_ref_audio') : '暂无参考音频') + '</div>';
            return;
          }

          var html = '';
          for (var ri = 0; ri < node.data.referenceAudios.length; ri++) {
            var item = node.data.referenceAudios[ri];
            html += '<div class="ref-audio-item" data-index="' + ri + '" style="margin-bottom: 8px; padding: 8px; background: #f9fafb; border-radius: 6px; border: 1px solid #e5e7eb;">' +
              '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">' +
                '<div style="font-size: 12px; font-weight: 600; color: #374151;">' + escapeHtml(item.characterName || '未命名角色') + '</div>' +
                '<button class="mini-btn ref-audio-delete-btn" data-index="' + ri + '" type="button" style="font-size: 10px; padding: 2px 6px; background: #ef4444; color: white;" data-i18n="dialogue_delete_btn">' + (window.t ? window.t('dialogue_delete_btn') : '删除') + '</button>' +
              '</div>' +
              '<audio controls style="width: 100%; max-height: 28px;" src="' + escapeHtml(proxyDownloadUrl(item.url)) + '"></audio>' +
            '</div>';
          }

          refAudiosList.innerHTML = html;

          var deleteBtns = refAudiosList.querySelectorAll('.ref-audio-delete-btn');
          for (var dbi = 0; dbi < deleteBtns.length; dbi++) {
            (function(btn) {
              btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var index = parseInt(btn.dataset.index);
                node.data.referenceAudios.splice(index, 1);
                renderRefAudiosList();
                showToast(window.t ? window.t('ref_audio_deleted_msg') : '已删除参考音频', 'success');
                safeAutoSave();
              });
            })(deleteBtns[dbi]);
          }
        }

        // 添加参考音频按钮
        addRefAudioBtn.addEventListener('click', async function(e) {
          e.stopPropagation();

          if (!node.data.referenceAudios) {
            node.data.referenceAudios = [];
          }

          if (node.data.referenceAudios.length >= 6) {
            showToast(window.t ? window.t('ref_audio_max_reached') : '最多只能添加6个参考音频', 'warning');
            return;
          }

          var input = document.createElement('input');
          input.type = 'file';
          input.accept = 'audio/*';

          input.addEventListener('change', async function(e) {
            var file = e.target.files[0];
            if (!file) { input.remove(); return; }

            var isValid = await validateAudioFile(file);
            if (!isValid) return;

            var characterName = prompt(window.t ? window.t('ref_audio_enter_character') : '请输入该音频对应的角色名称：');
            if (!characterName || !characterName.trim()) {
              showToast(window.t ? window.t('ref_audio_character_required') : '角色名称不能为空', 'warning');
              return;
            }

            try {
              showToast(window.t ? window.t('ref_audio_uploading') : '正在上传音频...', 'info');
              var uploadedUrl = await uploadFile(file);
              if (uploadedUrl) {
                node.data.referenceAudios.push({
                  characterName: characterName.trim(),
                  url: uploadedUrl,
                  fileName: file.name
                });
                renderRefAudiosList();
                showToast(window.t ? window.t('ref_audio_added') : '参考音频添加成功', 'success');
                safeAutoSave();
              } else {
                showToast(window.t ? window.t('ref_audio_upload_failed') : '音频上传失败', 'error');
              }
            } catch (error) {
              console.error('上传音频失败:', error);
              showToast((window.t ? window.t('ref_audio_upload_failed') : '音频上传失败') + ': ' + error.message, 'error');
            } finally {
              input.remove();
            }
          });

          input.click();
        });

        renderRefAudiosList();

        // 按钮可见性更新
        function updateButtonsVisibility(isSelected) {
          var addDialogueBtns = el.querySelectorAll('.dialogue-add-btn');
          for (var abi = 0; abi < addDialogueBtns.length; abi++) {
            var container = addDialogueBtns[abi].parentElement;
            if (container) container.style.display = isSelected ? 'block' : 'none';
          }

          var downloadBtns = el.querySelectorAll('.dialogue-download-btn');
          for (var dbi2 = 0; dbi2 < downloadBtns.length; dbi2++) {
            downloadBtns[dbi2].style.display = isSelected ? 'inline-block' : 'none';
          }

          var actionContainers = el.querySelectorAll('.dialogue-actions');
          for (var aci = 0; aci < actionContainers.length; aci++) {
            actionContainers[aci].style.display = isSelected ? 'flex' : 'none';
          }
        }

        var nodeObserver = new MutationObserver(function() {
          var isSelected = el.classList.contains('selected');
          updateButtonsVisibility(isSelected);
        });

        nodeObserver.observe(el, {
          attributes: true,
          attributeFilter: ['class']
        });
        el._cleanupHandlers = el._cleanupHandlers || [];
        el._cleanupHandlers.push(function() { nodeObserver.disconnect(); });

        // 更新对话列表
        function updateDialogueList() {
          var container = el.querySelector('.dialogue-items-container');
          if (!container) return;

          if (!node.data.dialogues || node.data.dialogues.length === 0) {
            container.innerHTML =
              '<div class="gen-meta" style="text-align:center; padding: 20px;" data-i18n="dialogue_no_data">' + (window.t ? window.t('dialogue_no_data') : '暂无对话数据') + '</div>' +
              '<div style="margin-top: 12px; text-align: center; display: none;">' +
                '<button class="mini-btn dialogue-add-btn" type="button" style="font-size: 11px; padding: 6px 12px; background: #3b82f6; color: white;" data-i18n="dialogue_add_btn">+ ' + (window.t ? window.t('dialogue_add_btn') : '添加对话') + '</button>' +
              '</div>';
            attachDialogueItemEvents();
            return;
          }

          var html = '';
          for (var dli = 0; dli < node.data.dialogues.length; dli++) {
            var dialogue = node.data.dialogues[dli];
            var characterName = dialogue.character_name || '未知角色';
            var text = dialogue.text || '';
            var hasAudio = node.data.audioResults[dli] && node.data.audioResults[dli].audioUrl;

            html += '<div class="dialogue-item" data-index="' + dli + '" style="margin-bottom: 12px; padding: 12px; background: #f9fafb; border-radius: 8px; border: 1px solid #e5e7eb;">' +
              '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">' +
                '<div style="font-weight: 600; color: #374151; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="' + escapeHtml(characterName) + '">' + escapeHtml(truncateName(characterName)) + '</div>' +
                '<div style="display: flex; gap: 4px;">' +
                  '<button class="mini-btn dialogue-edit-btn" data-index="' + dli + '" type="button" style="font-size: 11px; padding: 4px 8px;" title="' + (window.t ? window.t('dialogue_edit_btn') : '编辑') + '" data-i18n="dialogue_edit_btn">' + (window.t ? window.t('dialogue_edit_btn') : '编辑') + '</button>' +
                  '<button class="mini-btn dialogue-delete-btn" data-index="' + dli + '" type="button" style="font-size: 11px; padding: 4px 8px; background: #ef4444; color: white;" title="' + (window.t ? window.t('dialogue_delete_btn') : '删除') + '" data-i18n="dialogue_delete_btn">' + (window.t ? window.t('dialogue_delete_btn') : '删除') + '</button>' +
                  '<button class="mini-btn dialogue-generate-btn" data-index="' + dli + '" type="button" style="font-size: 11px; padding: 4px 8px;" data-i18n="dialogue_generate_btn">' + (window.t ? window.t('dialogue_generate_btn') : '生成音频') + '</button>' +
                '</div>' +
              '</div>' +
              '<div class="dialogue-text-display" data-index="' + dli + '" style="color: #6b7280; font-size: 13px; margin-bottom: 8px;">"' + escapeHtml(text) + '"</div>' +
              '<div class="dialogue-edit-form" data-index="' + dli + '" style="display: none; margin-bottom: 8px;">' +
                '<input type="text" class="dialogue-edit-character" value="' + escapeHtml(characterName) + '" placeholder="' + (window.t ? window.t('dialogue_char_placeholder') : '角色名') + '" style="width: 100%; padding: 6px; margin-bottom: 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 12px;">' +
                '<textarea class="dialogue-edit-text" placeholder="' + (window.t ? window.t('dialogue_text_placeholder') : '对话内容') + '" style="width: 100%; padding: 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 12px; resize: vertical;" rows="3">' + escapeHtml(text) + '</textarea>' +
                '<div style="display: flex; gap: 4px; margin-top: 6px;">' +
                  '<button class="mini-btn dialogue-save-btn" data-index="' + dli + '" type="button" style="font-size: 11px; padding: 4px 8px; background: #10b981; color: white;" data-i18n="dialogue_save_btn">' + (window.t ? window.t('dialogue_save_btn') : '保存') + '</button>' +
                  '<button class="mini-btn dialogue-cancel-btn" data-index="' + dli + '" type="button" style="font-size: 11px; padding: 4px 8px;" data-i18n="dialogue_cancel_btn">' + (window.t ? window.t('dialogue_cancel_btn') : '取消') + '</button>' +
                '</div>' +
              '</div>' +
              '<div class="dialogue-status" data-index="' + dli + '" style="display:none; font-size: 12px; color: #6b7280; margin-bottom: 8px;"></div>' +
              '<div class="dialogue-result" data-index="' + dli + '" style="display:' + (hasAudio ? 'block' : 'none') + ';">' +
                '<audio controls style="width:100%; max-height:32px; margin-bottom: 6px;"></audio>' +
                '<div class="dialogue-actions" style="display: none; gap: 4px;">' +
                  '<button class="mini-btn dialogue-download-btn" data-index="' + dli + '" type="button" style="font-size: 11px; padding: 4px 8px;" data-i18n="dialogue_download_btn">' + (window.t ? window.t('dialogue_download_btn') : '下载') + '</button>' +
                  '<button class="mini-btn dialogue-add-timeline-btn" data-index="' + dli + '" type="button" style="font-size: 11px; padding: 4px 8px; background: #10b981; color: white;" data-i18n="dialogue_add_timeline">' + (window.t ? window.t('dialogue_add_timeline') : '添加到时间轴') + '</button>' +
                '</div>' +
              '</div>' +
            '</div>';
          }

          html += '<div style="margin-top: 12px; text-align: center; display: none;">' +
            '<button class="mini-btn dialogue-add-btn" type="button" style="font-size: 11px; padding: 6px 12px; background: #3b82f6; color: white;" data-i18n="dialogue_add_btn">+ ' + (window.t ? window.t('dialogue_add_btn') : '添加对话') + '</button>' +
          '</div>';

          container.innerHTML = html;
          attachDialogueItemEvents();

          var isSelected = el.classList.contains('selected');
          updateButtonsVisibility(isSelected);

          // 恢复音频结果
          for (var dli2 = 0; dli2 < node.data.dialogues.length; dli2++) {
            if (node.data.audioResults[dli2] && node.data.audioResults[dli2].audioUrl) {
              var resultDiv = container.querySelector('.dialogue-result[data-index="' + dli2 + '"]');
              var audio = resultDiv ? resultDiv.querySelector('audio') : null;
              if (audio) {
                var audioUrl = node.data.audioResults[dli2].audioUrl;
                audio.src = proxyDownloadUrl(audioUrl);
              }
            }
          }
        }

        // 绑定对话项事件
        function attachDialogueItemEvents() {
          var generateBtns = el.querySelectorAll('.dialogue-generate-btn');
          for (var gbi = 0; gbi < generateBtns.length; gbi++) {
            (function(btn) {
              btn.addEventListener('click', async function(e) {
                e.stopPropagation();
                var index = parseInt(btn.dataset.index);
                await generateDialogueAudio(index);
              });
            })(generateBtns[gbi]);
          }

          var downloadBtns = el.querySelectorAll('.dialogue-download-btn');
          for (var dbi3 = 0; dbi3 < downloadBtns.length; dbi3++) {
            (function(btn) {
              btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var index = parseInt(btn.dataset.index);
                downloadDialogueAudio(index);
              });
            })(downloadBtns[dbi3]);
          }

          var addTimelineBtns = el.querySelectorAll('.dialogue-add-timeline-btn');
          for (var ati = 0; ati < addTimelineBtns.length; ati++) {
            (function(btn) {
              btn.addEventListener('click', async function(e) {
                e.stopPropagation();
                var index = parseInt(btn.dataset.index);
                await addDialogueAudioToTimeline(index);
              });
            })(addTimelineBtns[ati]);
          }

          var editBtns = el.querySelectorAll('.dialogue-edit-btn');
          for (var edi = 0; edi < editBtns.length; edi++) {
            (function(btn) {
              btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var index = parseInt(btn.dataset.index);
                var item = el.querySelector('.dialogue-item[data-index="' + index + '"]');
                if (!item) return;

                var textDisplay = item.querySelector('.dialogue-text-display');
                var editForm = item.querySelector('.dialogue-edit-form');
                var editBtnEl = item.querySelector('.dialogue-edit-btn');
                var deleteBtnEl = item.querySelector('.dialogue-delete-btn');
                var generateBtnEl = item.querySelector('.dialogue-generate-btn');

                if (textDisplay) textDisplay.style.display = 'none';
                if (editForm) editForm.style.display = 'block';
                if (editBtnEl) editBtnEl.style.display = 'none';
                if (deleteBtnEl) deleteBtnEl.style.display = 'none';
                if (generateBtnEl) generateBtnEl.style.display = 'none';
              });
            })(editBtns[edi]);
          }

          var saveBtns = el.querySelectorAll('.dialogue-save-btn');
          for (var sbi = 0; sbi < saveBtns.length; sbi++) {
            (function(btn) {
              btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var index = parseInt(btn.dataset.index);
                var item = el.querySelector('.dialogue-item[data-index="' + index + '"]');
                if (!item) return;

                var characterInput = item.querySelector('.dialogue-edit-character');
                var textInput = item.querySelector('.dialogue-edit-text');

                if (!characterInput || !textInput) return;

                var newCharacter = characterInput.value.trim();
                var newText = textInput.value.trim();

                if (!newCharacter || !newText) {
                  showToast(window.t ? window.t('dialogue_fields_required') : '角色名和对话内容不能为空', 'warning');
                  return;
                }

                node.data.dialogues[index].character_name = newCharacter;
                node.data.dialogues[index].text = newText;

                if (node.data.audioResults[index]) {
                  delete node.data.audioResults[index];
                }

                updateDialogueList();
                safeAutoSave();
                showToast(window.t ? window.t('dialogue_updated') : '对话已更新', 'success');
              });
            })(saveBtns[sbi]);
          }

          var cancelBtns = el.querySelectorAll('.dialogue-cancel-btn');
          for (var cbi = 0; cbi < cancelBtns.length; cbi++) {
            (function(btn) {
              btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var index = parseInt(btn.dataset.index);
                var item = el.querySelector('.dialogue-item[data-index="' + index + '"]');
                if (!item) return;

                var textDisplay = item.querySelector('.dialogue-text-display');
                var editForm = item.querySelector('.dialogue-edit-form');
                var editBtnEl = item.querySelector('.dialogue-edit-btn');
                var deleteBtnEl = item.querySelector('.dialogue-delete-btn');
                var generateBtnEl = item.querySelector('.dialogue-generate-btn');

                if (textDisplay) textDisplay.style.display = 'block';
                if (editForm) editForm.style.display = 'none';
                if (editBtnEl) editBtnEl.style.display = 'inline-block';
                if (deleteBtnEl) deleteBtnEl.style.display = 'inline-block';
                if (generateBtnEl) generateBtnEl.style.display = 'inline-block';
              });
            })(cancelBtns[cbi]);
          }

          var deleteBtns = el.querySelectorAll('.dialogue-delete-btn');
          for (var dbi4 = 0; dbi4 < deleteBtns.length; dbi4++) {
            (function(btn) {
              btn.addEventListener('click', function(e) {
                e.stopPropagation();
                var index = parseInt(btn.dataset.index);

                if (!confirm(window.t ? window.t('dialogue_delete_confirm') : '确定要删除这条对话吗？')) {
                  return;
                }

                node.data.dialogues.splice(index, 1);

                var newAudioResults = {};
                var audioKeys = Object.keys(node.data.audioResults);
                for (var aki = 0; aki < audioKeys.length; aki++) {
                  var idx = parseInt(audioKeys[aki]);
                  if (idx < index) {
                    newAudioResults[idx] = node.data.audioResults[idx];
                  } else if (idx > index) {
                    newAudioResults[idx - 1] = node.data.audioResults[idx];
                  }
                }
                node.data.audioResults = newAudioResults;

                updateDialogueList();
                safeAutoSave();
                showToast(window.t ? window.t('dialogue_deleted') : '对话已删除', 'success');
              });
            })(deleteBtns[dbi4]);
          }

          var addBtn = el.querySelector('.dialogue-add-btn');
          if (addBtn) {
            addBtn.addEventListener('click', function(e) {
              e.stopPropagation();

              var newDialogue = {
                character_name: '新角色',
                text: '请输入对话内容'
              };

              node.data.dialogues.push(newDialogue);
              updateDialogueList();
              safeAutoSave();
              showToast(window.t ? window.t('dialogue_added') : '已添加新对话', 'success');

              setTimeout(function() {
                var newIndex = node.data.dialogues.length - 1;
                var newItem = el.querySelector('.dialogue-item[data-index="' + newIndex + '"]');
                if (newItem) {
                  var editBtn = newItem.querySelector('.dialogue-edit-btn');
                  if (editBtn) editBtn.click();
                }
              }, 100);
            });
          }
        }

        // 生成单个对话音频
        async function generateDialogueAudio(index) {
          var dialogue = node.data.dialogues[index];
          if (!dialogue) return;

          var userId = getUserId();
          if (!userId) {
            showToast(window.t ? window.t('tts_login_required') : '请先登录后再使用语音生成功能', 'error');
            return;
          }

          var statusEl = el.querySelector('.dialogue-status[data-index="' + index + '"]');
          var resultDiv = el.querySelector('.dialogue-result[data-index="' + index + '"]');
          var generateBtn = el.querySelector('.dialogue-generate-btn[data-index="' + index + '"]');

          if (!statusEl || !resultDiv || !generateBtn) return;

          try {
            setBtnLoading(generateBtn, window.t ? window.t('tts_generating') : '生成中...');
            statusEl.style.display = 'block';
            statusEl.style.color = '';
            statusEl.textContent = window.t ? window.t('tts_generating_audio') : '正在生成音频...';
            resultDiv.style.display = 'none';

            var worldId = state.defaultWorldId;
            if (!worldId) {
              throw new Error(window.t ? window.t('dialogue_select_world') : '请先选择世界');
            }

            var characterName = dialogue.character_name;

            var form = new FormData();
            form.append('text', dialogue.text);
            form.append('user_id', userId);
            form.append('emo_control_method', node.data.emoControlMethod || 0);

            var refAudioFound = false;

            // 标准化角色名称
            var normalizeCharacterName = function(name) {
              if (!name) return '';
              return name.replace(/[【】\[\]]/g, '').trim();
            };

            var normalizedCharacterName = normalizeCharacterName(characterName);

            // 优先从对话组节点的参考音频中查找
            if (node.data.referenceAudios && node.data.referenceAudios.length > 0) {
              var matchedRefAudio = null;
              for (var mri = 0; mri < node.data.referenceAudios.length; mri++) {
                if (normalizeCharacterName(node.data.referenceAudios[mri].characterName) === normalizedCharacterName) {
                  matchedRefAudio = node.data.referenceAudios[mri];
                  break;
                }
              }

              if (matchedRefAudio) {
                var voiceUrl = proxyDownloadUrl(matchedRefAudio.url);

                try {
                  var voiceResponse = await fetch(voiceUrl);
                  if (voiceResponse.ok) {
                    var voiceBlob = await voiceResponse.blob();
                    form.append('ref_audio', voiceBlob, 'ref_audio.wav');
                    refAudioFound = true;
                  }
                } catch (error) {
                  console.error('获取对话组参考音频失败:', error);
                }
              }
            }

            // 如果对话组中没有找到，则从角色库中查找
            if (!refAudioFound) {
              var matchedCharacter = await fetchAndMatchCharacter(worldId, characterName);

              if (matchedCharacter && matchedCharacter.default_voice) {
                var voiceUrl2 = proxyDownloadUrl(matchedCharacter.default_voice);

                var voiceResponse2 = await fetch(voiceUrl2);
                if (!voiceResponse2.ok) {
                  throw new Error('获取参考音频失败: ' + voiceResponse2.status + ' ' + voiceResponse2.statusText);
                }
                var voiceBlob2 = await voiceResponse2.blob();

                form.append('ref_audio', voiceBlob2, 'ref_audio.wav');
                refAudioFound = true;
              } else {
                console.warn('未找到匹配的角色或角色没有配置参考音频');
              }
            }

            if (!refAudioFound) {
              var errMsg = window.t ? window.t('dialogue_no_ref_audio', { character: characterName }) : ('角色"' + characterName + '"没有配置参考音频。请在对话组节点中添加该角色的参考音频，或在角色库中为该角色配置参考音频。');
              throw new Error(errMsg);
            }

            if (node.data.emoControlMethod === 1) {
              var videoConn = state.videoConnections.find(function(c) { return c.to === node.id; });
              if (videoConn) {
                var videoNode = state.nodes.find(function(n) { return n.id === videoConn.from; });
                if (videoNode && videoNode.data.url) {
                  form.append('emo_ref_video_url', videoNode.data.url);
                }
              } else if (node.data.emoRefAudioUrl) {
                var emoAudioUrl = proxyDownloadUrl(node.data.emoRefAudioUrl);
                var emoAudioResponse = await fetch(emoAudioUrl);
                if (emoAudioResponse.ok) {
                  var emoAudioBlob = await emoAudioResponse.blob();
                  form.append('emo_ref_audio', emoAudioBlob, 'emo_ref_audio.wav');
                }
              }

              if (node.data.emoWeight !== null && node.data.emoWeight !== undefined) {
                form.append('emo_weight', node.data.emoWeight);
              }
            }

            if (node.data.emoControlMethod === 2 && node.data.emoVec) {
              var emoVecSumVal = node.data.emoVec.reduce(function(acc, val) { return acc + val; }, 0);
              if (emoVecSumVal <= 1.5) {
                form.append('emo_vec', node.data.emoVec.join(','));
              } else {
                throw new Error(window.t ? window.t('emo_vec_sum_exceeded') : '情感向量之和不能超过1.5');
              }
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

            if (result.code !== 0 && result.code !== undefined) {
              throw new Error(result.message || result.msg || '音频生成请求失败');
            }

            var audioId = result.audio_id;

            if (audioId) {
              await pollDialogueAudioStatus(index, audioId, statusEl, resultDiv, generateBtn);
            }

          } catch (error) {
            console.error('语音生成失败:', error);
            statusEl.style.color = '#dc2626';
            statusEl.textContent = (window.t ? window.t('tts_generate_failed') : '生成失败') + ': ' + (error.message || '未知错误');
            setBtnReady(generateBtn, window.t ? window.t('dialogue_generate_btn') : '生成音频');
            showToast((window.t ? window.t('tts_generate_failed') : '语音生成失败') + ': ' + error.message, 'error');
          }
        }

        // 轮询对话音频状态
        function pollDialogueAudioStatus(index, audioId, statusEl, resultDiv, generateBtn) {
          pollTaskStatus({
            statusUrl: '/api/audio-status/' + audioId,
            onSuccess: function(payload) {
              if (payload.result_url) {
                if (!node.data.audioResults) node.data.audioResults = {};
                node.data.audioResults[index] = { audioUrl: payload.result_url };

                var audio = resultDiv.querySelector('audio');
                if (audio) audio.src = payload.result_url;
                resultDiv.style.display = 'block';

                // 创建或更新独立音频节点
                try {
                  var dialogue = node.data.dialogues[index];
                  var characterName = dialogue ? (dialogue.character_name || '角色') : '音频';
                  var audioName = characterName + ': ' + (dialogue ? dialogue.text.substring(0, 15) : '') + '...';
                  var existingAudioNodeId = node.data.audioResults[index].audioNodeId;
                  var existingAudioNode = existingAudioNodeId
                    ? state.nodes.find(function(n) { return n.id === existingAudioNodeId; })
                    : null;


                  if (existingAudioNode) {
                    // 更新已有音频节点的URL
                    existingAudioNode.data.url = payload.result_url;
                    existingAudioNode.data.name = audioName;
                    var existingEl = canvasEl.querySelector('.node[data-node-id="' + existingAudioNode.id + '"]');
                    if (existingEl) {
                      var playerEl = existingEl.querySelector('.audio-node-player');
                      var nameEl = existingEl.querySelector('.audio-node-name');
                      var previewField = existingEl.querySelector('.audio-preview-field');
                      var previewActionsField = existingEl.querySelector('.audio-preview-actions-field');
                      if (playerEl) playerEl.src = typeof proxyDownloadUrl === 'function' ? proxyDownloadUrl(payload.result_url) : payload.result_url;
                      if (nameEl) { nameEl.textContent = audioName; nameEl.title = audioName; }
                      if (previewField) previewField.style.display = 'block';
                      if (previewActionsField) previewActionsField.style.display = 'block';
                    }
                  } else {
                    // 创建新的独立音频节点
                    var newAudioId = createAudioNode({
                      x: node.x + 420,
                      y: node.y + index * 100,
                      title: characterName + ' - 音频',
                      data: {
                        url: payload.result_url,
                        name: audioName
                      }
                    });
                    var newAudioNode = state.nodes.find(function(n) { return n.id === newAudioId; });
                    if (newAudioNode) {
                      newAudioNode.data.sourceNodeId = node.id;
                      newAudioNode.data.dialogueIndex = index;
                      // 显示"添加到时间轴"按钮
                      var newEl = canvasEl.querySelector('.node[data-node-id="' + newAudioId + '"]');
                      if (newEl) {
                        var addTlBtn = newEl.querySelector('.audio-add-timeline-btn');
                        if (addTlBtn) addTlBtn.style.display = 'inline-block';
                      }
                      // 添加音频连接线：对话组 → 新音频节点
                      if (!state.audioConnections) state.audioConnections = [];
                      state.audioConnections.push({
                        id: state.nextAudioConnId++,
                        from: node.id,
                        to: newAudioId
                      });
                      if (typeof renderAudioConnections === 'function') renderAudioConnections();
                      // 记录音频节点ID，便于后续更新
                      node.data.audioResults[index].audioNodeId = newAudioId;
                    }
                  }
                } catch (err) {
                  console.error('[对话组] 创建独立音频节点失败:', err);
                }

                statusEl.textContent = window.t ? window.t('tts_generate_success') : '生成成功！';
                statusEl.style.color = '#16a34a';
                showToast(window.t ? window.t('tts_generate_success') : '语音生成成功', 'success');

                // 3秒后淡出隐藏状态提示
                setTimeout(function() {
                  statusEl.style.transition = 'opacity 0.5s ease';
                  statusEl.style.opacity = '0';
                  setTimeout(function() {
                    statusEl.style.display = 'none';
                    statusEl.style.opacity = '';
                    statusEl.style.transition = '';
                  }, 500);
                }, 3000);

                safeAutoSave();
              }
              setBtnReady(generateBtn, window.t ? window.t('dialogue_generate_btn') : '生成音频');
            },
            onFailed: function(payload) {
              statusEl.style.color = '#dc2626';
              statusEl.textContent = (window.t ? window.t('tts_generate_failed') : '生成失败') + ': ' + (payload.reason || payload.message || '未知错误');
              setBtnReady(generateBtn, window.t ? window.t('dialogue_generate_btn') : '生成音频');
              showToast(window.t ? window.t('tts_generate_failed') : '语音生成失败', 'error');
            },
            onTimeout: function() {
              statusEl.style.color = '#dc2626';
              statusEl.textContent = window.t ? window.t('tts_generate_timeout_hint') : '等待超时，但音频仍在生成中。你可以通过刷新页面后查看是否生成成功。';
              setBtnReady(generateBtn, window.t ? window.t('dialogue_generate_btn') : '生成音频');
            }
          });
        }

        // 下载对话音频
        function downloadDialogueAudio(index) {
          if (!node.data.audioResults || !node.data.audioResults[index]) {
            showToast(window.t ? window.t('tts_no_audio_error') : '没有可下载的音频', 'error');
            return;
          }

          var audioUrl = node.data.audioResults[index].audioUrl;
          var dialogue = node.data.dialogues[index];
          var characterName = dialogue.character_name || '角色';

          var now = new Date();
          var dateStr = now.getFullYear().toString() +
                        (now.getMonth() + 1).toString().padStart(2, '0') +
                        now.getDate().toString().padStart(2, '0');
          var timeStr = now.getHours().toString().padStart(2, '0') +
                        now.getMinutes().toString().padStart(2, '0');
          var filename = characterName + '_' + dateStr + '_' + timeStr + '.wav';

          var link = document.createElement('a');
          link.href = audioUrl;
          link.download = filename;
          link.target = '_blank';
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          showToast(window.t ? window.t('tts_download_start') : '开始下载', 'success');
        }

        // 添加对话音频到时间轴
        async function addDialogueAudioToTimeline(index) {
          if (!node.data.audioResults || !node.data.audioResults[index]) {
            showToast(window.t ? window.t('dialogue_no_audio_to_add') : '没有可添加的音频', 'error');
            return;
          }

          var audioUrl = node.data.audioResults[index].audioUrl;
          var dialogue = node.data.dialogues[index];
          var characterName = dialogue.character_name || '角色';
          var audioName = characterName + ': ' + dialogue.text.substring(0, 20) + '...';

          try {
            var duration = await getAudioDuration(audioUrl);
            addAudioToTimeline(node.id, index, audioUrl, audioName, duration);
          } catch (error) {
            console.warn('获取音频时长失败，使用默认时长:', error);
            addAudioToTimeline(node.id, index, audioUrl, audioName, 5);
          }
        }

        // 从角色库匹配角色
        async function fetchAndMatchCharacter(worldId, characterName) {
          if (!worldId || !characterName) return null;

          try {
            var cleanName = characterName.replace(/【/g, '').replace(/】/g, '');

            var authToken = getAuthToken();
            var userId = getUserId();
            var response = await fetch('/api/characters?world_id=' + worldId + '&page=1&page_size=100&keyword=' + encodeURIComponent(cleanName), {
              headers: {
                'Authorization': authToken || '',
                'X-User-Id': userId || ''
              }
            });

            if (!response.ok) {
              console.error('角色查询请求失败:', response.status);
              return null;
            }

            var result = await response.json();

            if (result.code === 0 && result.data && Array.isArray(result.data.data)) {
              var characters = result.data.data;

              if (characters.length > 0) {
                var matchedChar = characters.find(function(c) { return c.name === cleanName; }) || characters[0];
                return matchedChar;
              }
            }

            return null;
          } catch (error) {
            console.error('获取角色信息失败:', error);
            return null;
          }
        }

        // 生成全部按钮
        if (generateAllBtn) {
        generateAllBtn.addEventListener('click', async function(e) {
          e.stopPropagation();

          if (!node.data.dialogues || node.data.dialogues.length === 0) {
            showToast(window.t ? window.t('dialogue_no_data') : '暂无对话数据', 'warning');
            return;
          }

          setBtnLoading(generateAllBtn, window.t ? window.t('tts_generating') : '生成中...');

          for (var gai = 0; gai < node.data.dialogues.length; gai++) {
            await generateDialogueAudio(gai);
            await new Promise(function(resolve) { setTimeout(resolve, 1000); });
          }

          setBtnReady(generateAllBtn, window.t ? window.t('dialogue_generate_all') : '生成全部');
          showToast(window.t ? window.t('dialogue_all_generated') : '全部对话音频生成完成', 'success');
        });
        }

        updateDialogueList();

        // 初始化视频输入端口禁用状态
        if (videoInputPort) {
          if (node.data.emoControlMethod === 1) {
            videoInputPort.classList.remove('disabled');
          } else {
            videoInputPort.classList.add('disabled');
          }
        }

        // 暴露渲染参考音频列表的方法
        node.renderRefAudiosList = renderRefAudiosList;
        // 暴露更新对话列表的方法（用于数据恢复时重建DOM）
        node.updateDialogueList = updateDialogueList;
      }
    }, opts);
  }

  var createDialogueGroupNodeWithData = createNodeWithDataFactory(
    createDialogueGroupNode,
    function(el, node, nodeData) {
      // 先用已恢复的数据重新渲染对话列表（onCreated时dialogues为空，DOM中无对话条目）
      if (node.updateDialogueList && node.data.dialogues && node.data.dialogues.length > 0) {
        node.updateDialogueList();
      }

      // 恢复对话数据到DOM
      var emoControlSelect = el.querySelector('.dialogue-emo-control-select');
      var emoRefAudioField = el.querySelector('.dialogue-emo-ref-audio-field');
      var emoRefAudioInput = el.querySelector('.dialogue-emo-ref-audio-input');
      var emoRefAudioClearBtn = el.querySelector('.dialogue-emo-ref-audio-clear-btn');
      var emoRefAudioPreview = el.querySelector('.dialogue-emo-ref-audio-preview');
      var emoWeightField = el.querySelector('.dialogue-emo-weight-field');
      var emoWeightSlider = el.querySelector('.dialogue-emo-weight-slider');
      var emoWeightValue = el.querySelector('.dialogue-emo-weight-value');
      var emoVecField = el.querySelector('.dialogue-emo-vec-field');
      var emoVecSliders = el.querySelectorAll('.dialogue-emo-vec-slider');
      var videoInputPort = el.querySelector('.port.video-input-port');

      if (emoControlSelect && node.data.emoControlMethod !== undefined) {
        emoControlSelect.value = node.data.emoControlMethod;

        var isEmoRefMode = node.data.emoControlMethod === 1;
        if (emoRefAudioField) {
          emoRefAudioField.style.opacity = isEmoRefMode ? '1' : '0.5';
          emoRefAudioField.style.pointerEvents = isEmoRefMode ? 'auto' : 'none';
        }
        if (emoRefAudioInput) emoRefAudioInput.disabled = !isEmoRefMode;
        if (emoRefAudioClearBtn) emoRefAudioClearBtn.disabled = !isEmoRefMode;

        if (emoWeightField) emoWeightField.style.display = node.data.emoControlMethod === 1 ? 'block' : 'none';
        if (emoVecField) emoVecField.style.display = node.data.emoControlMethod === 2 ? 'block' : 'none';

        if (videoInputPort) {
          if (isEmoRefMode) {
            videoInputPort.classList.remove('disabled');
          } else {
            videoInputPort.classList.add('disabled');
          }
        }
      }

      if (node.data.emoRefAudioUrl && emoRefAudioPreview) {
        var audio = emoRefAudioPreview.querySelector('audio');
        if (audio) {
          audio.src = proxyDownloadUrl(node.data.emoRefAudioUrl);
          emoRefAudioPreview.style.display = 'block';
        }
      }

      if (node.data.emoWeight !== undefined && emoWeightSlider && emoWeightValue) {
        emoWeightSlider.value = node.data.emoWeight;
        emoWeightValue.textContent = node.data.emoWeight.toFixed(1);
      }

      if (node.data.emoVec && emoVecSliders) {
        for (var evi = 0; evi < emoVecSliders.length; evi++) {
          if (node.data.emoVec[evi] !== undefined) {
            emoVecSliders[evi].value = node.data.emoVec[evi];
            var valueSpan = el.querySelector('.dialogue-emo-vec-value[data-index="' + evi + '"]');
            if (valueSpan) valueSpan.textContent = node.data.emoVec[evi].toFixed(2);
          }
        }

        var sum = node.data.emoVec.reduce(function(acc, val) { return acc + val; }, 0);
        var emoVecSum = el.querySelector('.dialogue-emo-vec-sum');
        var emoVecWarning = el.querySelector('.dialogue-emo-vec-warning');
        if (emoVecSum) {
          emoVecSum.textContent = sum.toFixed(2);
          if (sum > 1.5) {
            emoVecSum.style.color = '#dc2626';
            if (emoVecWarning) emoVecWarning.style.display = 'inline';
          } else {
            emoVecSum.style.color = '#16a34a';
            if (emoVecWarning) emoVecWarning.style.display = 'none';
          }
        }
      }

      if (node.data.audioResults) {
        var audioKeys = Object.keys(node.data.audioResults);
        for (var aki = 0; aki < audioKeys.length; aki++) {
          var result = node.data.audioResults[audioKeys[aki]];
          if (result.audioUrl) {
            var resultDiv = el.querySelector('.dialogue-result[data-index="' + audioKeys[aki] + '"]');
            var audioEl = resultDiv ? resultDiv.querySelector('audio') : null;
            if (audioEl && resultDiv) {
              audioEl.src = proxyDownloadUrl(result.audioUrl);
              resultDiv.style.display = 'block';
            }
          }
        }
      }

      // 恢复参考音频列表
      if (node.renderRefAudiosList) {
        node.renderRefAudiosList();
      }
    }
  );

  // 注册到全局
  window.createDialogueGroupNode = createDialogueGroupNode;
  window.createDialogueGroupNodeWithData = createDialogueGroupNodeWithData;

  // 注册到节点注册表
  registerNodeType('dialogue_group', {
    createFn: createDialogueGroupNode,
    createWithDataFn: createDialogueGroupNodeWithData
  });

})();
