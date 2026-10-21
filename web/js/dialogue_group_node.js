// ============================
// dialogue_group_node.js - 对话组节点
// 使用 createNodeBase 基类工厂
// ============================

(function() {

  // 转义统一收敛到 web/js/escape.js（window.escapeHtml，经 utils.js/escape.js 提供）
  const escapeHtml = window.escapeHtml;

  function tr(key, fallback) {
    if (typeof window.t !== 'function') return fallback;
    var value = window.t(key);
    if (!value || value === key) return fallback;
    return value;
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

  function renderDialogueConnections() {
    try {
      if (typeof renderAllConnections === 'function') renderAllConnections();
    } catch (err) {
      console.warn('刷新对话连线失败:', err);
    }
  }

  function dialogueVoicePortHtml(index, characterName) {
    var title = tr('dialogue_voice_output_port', '参考音色');
    if (characterName) title += ' · ' + characterName;
    return '<div class="port dialogue-voice-output" data-port="voice" data-line-index="' + index + '" title="' + escapeHtml(title) + '"></div>';
  }

  // 每句对话一个输出端口：该句生成的文字转语音节点由此端口引出关联线
  function dialogueItemOutputPortHtml(index) {
    var title = tr('dialogue_item_output_port', '输出（该句对话生成的语音节点）');
    return '<div class="port dialogue-item-output" data-port="dialogue-output" data-line-index="' + index + '" title="' + escapeHtml(title) + '"></div>';
  }

  // 对话组不挂节点级主输出端口：每句对话条目自带输出端口（见 dialogueItemOutputPortHtml），
  // 生成的文字转语音节点由对应条目的输出端口引出关联线
  var DIALOGUE_GROUP_PORTS = [
    { direction: 'input', titleI18nKey: 'dialogue_input_port_title', acceptType: 'shot_frame', connectionType: 'connections' },
    { direction: 'input', cssClass: 'video-input-port', titleI18nKey: 'dialogue_video_input_port_title' }
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
          referenceAudios: [],
          ttsNodeIds: {}
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
                dialogueItemOutputPortHtml(di) +
                dialogueVoicePortHtml(di, characterName) +
                '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">' +
                  '<div style="font-weight: 600; color: #374151; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="' + escapeHtml(characterName) + '">' + escapeHtml(truncateName(characterName)) + '</div>' +
                  '<button class="mini-btn dialogue-create-tts-btn" data-index="' + di + '" type="button" style="font-size: 11px; padding: 4px 8px;" data-i18n="dialogue_create_tts_btn">' + tr('dialogue_create_tts_btn', '创建语音节点') + '</button>' +
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

        return '<div class="field field-always-visible">' +
          '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">' +
            '<div class="label" style="margin: 0;" data-i18n="dialogue_list_label">' + (window.t ? window.t('dialogue_list_label') : '对话列表') + '</div>' +
          '</div>' +
          '<div class="dialogue-items-container">' + dialogueItemsHtml + '</div>' +
        '</div>' +
        '<div class="field">' +
          '<div class="gen-meta" style="margin-bottom: 8px;" data-i18n="dialogue_tts_hint">' + tr('dialogue_tts_hint', '音频在文字转语音节点中合成，可选择音色库或参考音频克隆。') + '</div>' +
          '<button class="mini-btn dialogue-create-tts-all-btn" type="button" style="font-size: 11px; padding: 4px 8px; width: 100%;" data-i18n="dialogue_create_tts_all">' + tr('dialogue_create_tts_all', '全部创建语音节点') + '</button>' +
        '</div>';
      },
      onCreated: function(node, el) {
        var createTtsAllBtn = el.querySelector('.dialogue-create-tts-all-btn');
        var videoInputPort = el.querySelector('.port.video-input-port');
        if (videoInputPort) videoInputPort.classList.add('disabled');

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
            renderDialogueConnections();
            return;
          }

          var html = '';
          for (var dli = 0; dli < node.data.dialogues.length; dli++) {
            var dialogue = node.data.dialogues[dli];
            // 列表标题兜底显示「未知角色」；编辑表单用原始值，空则留空走 placeholder 提示
            var rawCharacterName = dialogue.character_name || '';
            var characterName = rawCharacterName || '未知角色';
            var text = dialogue.text || '';
            var hasAudio = node.data.audioResults[dli] && node.data.audioResults[dli].audioUrl;
            var linkedId = node.data.ttsNodeIds && node.data.ttsNodeIds[dli];
            var ttsBtnKey = linkedId != null && linkedId !== '' ? 'dialogue_open_tts_btn' : 'dialogue_create_tts_btn';
            var ttsBtnFallback = linkedId != null && linkedId !== '' ? '打开语音节点' : '创建语音节点';
            var ttsBtnLabel = tr(ttsBtnKey, ttsBtnFallback);

            html += '<div class="dialogue-item" data-index="' + dli + '" style="margin-bottom: 12px; padding: 12px; background: #f9fafb; border-radius: 8px; border: 1px solid #e5e7eb;">' +
              dialogueItemOutputPortHtml(dli) +
              dialogueVoicePortHtml(dli, characterName) +
              '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">' +
                '<div style="font-weight: 600; color: #374151; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="' + escapeHtml(characterName) + '">' + escapeHtml(truncateName(characterName)) + '</div>' +
                '<div style="display: flex; gap: 4px;">' +
                  '<button class="mini-btn dialogue-edit-btn" data-index="' + dli + '" type="button" style="font-size: 11px; padding: 4px 8px;" title="' + (window.t ? window.t('dialogue_edit_btn') : '编辑') + '" data-i18n="dialogue_edit_btn">' + (window.t ? window.t('dialogue_edit_btn') : '编辑') + '</button>' +
                  '<button class="mini-btn dialogue-delete-btn" data-index="' + dli + '" type="button" style="font-size: 11px; padding: 4px 8px; background: #ef4444; color: white;" title="' + (window.t ? window.t('dialogue_delete_btn') : '删除') + '" data-i18n="dialogue_delete_btn">' + (window.t ? window.t('dialogue_delete_btn') : '删除') + '</button>' +
                  '<button class="mini-btn dialogue-create-tts-btn" data-index="' + dli + '" type="button" style="font-size: 11px; padding: 4px 8px;" data-i18n="' + ttsBtnKey + '">' + ttsBtnLabel + '</button>' +
                '</div>' +
              '</div>' +
              '<div class="dialogue-text-display" data-index="' + dli + '" style="color: #6b7280; font-size: 13px; margin-bottom: 8px;">"' + escapeHtml(text) + '"</div>' +
              '<div class="dialogue-edit-form" data-index="' + dli + '" style="display: none; margin-bottom: 8px;">' +
                '<div style="position: relative;">' +
                  '<input type="text" class="dialogue-edit-character" value="' + escapeHtml(rawCharacterName) + '" placeholder="' + (window.t ? window.t('dialogue_char_placeholder') : '角色名') + '" style="width: 100%; padding: 6px; margin-bottom: 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 12px;">' +
                  '<div class="dialogue-character-dropdown" style="display: none; position: absolute; top: 100%; left: 0; right: 0; background: #fff; border: 1px solid #e5e7eb; border-radius: 6px; max-height: 200px; overflow-y: auto; z-index: 1000; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);"></div>' +
                '</div>' +
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
          refreshLineVoices();
          renderDialogueConnections();

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
          var createTtsBtns = el.querySelectorAll('.dialogue-create-tts-btn');
          for (var gbi = 0; gbi < createTtsBtns.length; gbi++) {
            (function(btn) {
              btn.addEventListener('click', async function(e) {
                e.stopPropagation();
                var index = parseInt(btn.dataset.index, 10);
                await ensureDialogueTtsNode(index, { silent: false, focus: true });
              });
            })(createTtsBtns[gbi]);
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
                var generateBtnEl = item.querySelector('.dialogue-create-tts-btn');

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
                var linked = findLinkedTtsNode(index);
                if (linked && typeof linked.applyTtsPatch === 'function') {
                  linked.applyTtsPatch({ text: newText, characterName: newCharacter });
                }

                updateDialogueList();
                refreshConnectedLineVoice(index);
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

                // 「添加对话」产生的新条目尚未保存过：取消 = 不添加这条对话，直接移除
                if (item.dataset.isNew === '1') {
                  if (index >= 0 && index < node.data.dialogues.length) {
                    node.data.dialogues.splice(index, 1);
                  }
                  updateDialogueList();
                  safeAutoSave();
                  return;
                }

                var textDisplay = item.querySelector('.dialogue-text-display');
                var editForm = item.querySelector('.dialogue-edit-form');
                var editBtnEl = item.querySelector('.dialogue-edit-btn');
                var deleteBtnEl = item.querySelector('.dialogue-delete-btn');
                var generateBtnEl = item.querySelector('.dialogue-create-tts-btn');

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
                node.data.ttsNodeIds = reindexLinkedMap(node.data.ttsNodeIds, index);
                reindexDialogueVoiceConnections(index);

                updateDialogueList();
                safeAutoSave();
                showToast(window.t ? window.t('dialogue_deleted') : '对话已删除', 'success');
              });
            })(deleteBtns[dbi4]);
          }

          var voicePorts = el.querySelectorAll('.dialogue-voice-output');
          for (var vpi = 0; vpi < voicePorts.length; vpi++) {
            (function(port) {
              port.addEventListener('mousedown', function(e) {
                e.preventDefault();
                e.stopPropagation();
                var lineIndex = parseInt(port.dataset.lineIndex, 10);
                state.connecting = {
                  fromId: node.id,
                  startX: e.clientX,
                  startY: e.clientY,
                  fromPort: 'voice',
                  voiceLineIndex: lineIndex
                };
                if (typeof canvasEl !== 'undefined' && canvasEl) canvasEl.style.cursor = 'crosshair';
              });
            })(voicePorts[vpi]);
          }

          // 角色名输入：从角色库选择（自动补全下拉）或手动填写
          var characterInputs = el.querySelectorAll('.dialogue-edit-character');
          for (var cai = 0; cai < characterInputs.length; cai++) {
            (function(charInput) {
              var form = charInput.closest('.dialogue-edit-form');
              var dropdown = form ? form.querySelector('.dialogue-character-dropdown') : null;
              attachCharacterAutocomplete(charInput, dropdown);
            })(characterInputs[cai]);
          }

          var addBtn = el.querySelector('.dialogue-add-btn');
          if (addBtn) {
            addBtn.addEventListener('click', function(e) {
              e.stopPropagation();

              // 不预填默认内容：角色名/对话内容留空，输入框以 placeholder 作提示，
              // 聚焦即可直接填写；取消新增时整条移除
              var newDialogue = {
                character_name: '',
                text: ''
              };

              node.data.dialogues.push(newDialogue);
              updateDialogueList();
              safeAutoSave();
              showToast(window.t ? window.t('dialogue_added') : '已添加新对话', 'success');

              setTimeout(function() {
                var newIndex = node.data.dialogues.length - 1;
                var newItem = el.querySelector('.dialogue-item[data-index="' + newIndex + '"]');
                if (newItem) {
                  newItem.dataset.isNew = '1';
                  var editBtn = newItem.querySelector('.dialogue-edit-btn');
                  if (editBtn) editBtn.click();
                }
              }, 100);
            });
          }
        }

        function normalizeCharacterName(name) {
          if (!name) return '';
          return String(name).replace(/[【】\[\]]/g, '').trim();
        }

        function findLinkedTtsNode(index) {
          if (!node.data.ttsNodeIds) return null;
          var linkedId = node.data.ttsNodeIds[index];
          if (linkedId == null || linkedId === '') return null;
          return state.nodes.find(function(n) {
            return String(n.id) === String(linkedId) && n.type === 'text_to_speech';
          }) || null;
        }

        // 确保"对话组→文字转语音节点"的来源关联线存在（缺失时补建），
        // 画布上用于标识该文字转语音节点由本对话组的哪句对话生成；
        // "全部创建语音节点"时会逐个校验，有对话但缺线即重建
        function ensureDialogueTtsLink(index, ttsNodeId) {
          if (ttsNodeId == null) return;
          if (!state.audioConnections) state.audioConnections = [];
          var exists = state.audioConnections.some(function(c) {
            return String(c.from) === String(node.id) && String(c.to) === String(ttsNodeId) && c.portType === 'dialogue_link';
          });
          if (exists) return;
          state.audioConnections.push({
            id: state.nextAudioConnId++,
            from: node.id,
            to: ttsNodeId,
            portType: 'dialogue_link',
            voiceLineIndex: index
          });
          if (typeof renderAudioConnections === 'function') renderAudioConnections();
        }

        // 删除台词后只重排关联，不删除画布上的文字转语音节点
        function reindexLinkedMap(map, index) {
          var next = {};
          if (!map) return next;
          var keys = Object.keys(map);
          for (var rli = 0; rli < keys.length; rli++) {
            var idx = parseInt(keys[rli], 10);
            if (isNaN(idx)) continue;
            if (idx === index) {
              var detached = state.nodes.find(function(n) {
                return String(n.id) === String(map[keys[rli]]) && n.type === 'text_to_speech';
              });
              if (detached && detached.data) {
                detached.data.dialogueGroupId = null;
                detached.data.dialogueIndex = null;
              }
              continue;
            }
            var newIdx = idx > index ? idx - 1 : idx;
            next[newIdx] = map[keys[rli]];
            var linked = state.nodes.find(function(n) {
              return String(n.id) === String(map[keys[rli]]) && n.type === 'text_to_speech';
            });
            if (linked && linked.data) linked.data.dialogueIndex = newIdx;
          }
          return next;
        }

        async function resolveRefAudioUrl(characterName) {
          var normalized = normalizeCharacterName(characterName);
          if (node.data.referenceAudios && node.data.referenceAudios.length > 0) {
            for (var mri = 0; mri < node.data.referenceAudios.length; mri++) {
              var item = node.data.referenceAudios[mri];
              if (item && normalizeCharacterName(item.characterName) === normalized && item.url) {
                return item.url;
              }
            }
          }
          var worldId = state.defaultWorldId;
          if (!worldId) return '';
          var matched = await fetchAndMatchCharacter(worldId, characterName);
          if (matched && matched.default_voice) return matched.default_voice;
          return '';
        }

        // 音色已就绪（克隆引擎带参考音频）且尚未生成过音频时，自动开始合成，
        // 直接产出音频节点，无需用户再手动点击「生成语音」。
        // 音色库引擎需用户先选音色（且涉及算力扣费），不在此自动触发。
        function maybeAutoGenerateTts(ttsNode) {
          if (!ttsNode || !ttsNode.data) return;
          if (ttsNode.data.audioUrl) return; // 已有生成结果（含历史恢复）
          if (ttsNode.data.status && ttsNode.data.status !== 'FAILED') return; // 提交中/已成功
          if (ttsNode.data.engine !== 'clone') return;
          if (!ttsNode.data.refAudioUrl && !ttsNode.data.refAudioFile) return; // 音色未就绪
          if (typeof ttsNode.requestGenerate === 'function') ttsNode.requestGenerate();
        }

        async function ensureDialogueTtsNode(index, opts) {
          opts = opts || {};
          var dialogue = node.data.dialogues && node.data.dialogues[index];
          if (!dialogue || !String(dialogue.text || '').trim()) {
            if (!opts.silent) showToast(tr('dialogue_tts_empty_line', '这句对话没有文本，无法创建语音节点'), 'warning');
            return null;
          }
          if (typeof createTextToSpeechNode !== 'function') {
            showToast(tr('dialogue_tts_missing', '文字转语音节点未加载'), 'error');
            return null;
          }
          if (!node.data.ttsNodeIds) node.data.ttsNodeIds = {};
          var existing = findLinkedTtsNode(index);
          if (existing) {
            if (typeof existing.applyTtsPatch === 'function') {
              existing.applyTtsPatch({
                text: dialogue.text,
                characterName: dialogue.character_name || ''
              });
            }
            // 关联线可能被用户删除或历史数据缺失，打开时按需补建
            ensureDialogueTtsLink(index, existing.id);
            maybeAutoGenerateTts(existing);
            if (opts.focus) {
              if (typeof setSelected === 'function') setSelected(existing.id);
              if (typeof focusOnNode === 'function') focusOnNode(existing.id);
            }
            if (!opts.silent) showToast(tr('dialogue_tts_opened', '已打开对应的文字转语音节点'), 'success');
            return existing.id;
          }

          var refUrl = '';
          try {
            refUrl = (await resolveRefAudioUrl(dialogue.character_name)) || '';
          } catch (err) {
            console.warn('解析角色参考音频失败:', err);
            refUrl = '';
          }

          var newId = createTextToSpeechNode({
            x: node.x + 480,
            y: node.y + index * 220,
            checkCollision: true,
            text: dialogue.text,
            characterName: dialogue.character_name || '',
            engine: refUrl ? 'clone' : 'voice_library',
            refAudioUrl: refUrl,
            dialogueGroupId: node.id,
            dialogueIndex: index
          });
          var created = state.nodes.find(function(n) { return n.id === newId; });
          if (created && created.data) {
            created.data.dialogueGroupId = node.id;
            created.data.dialogueIndex = index;
          }
          node.data.ttsNodeIds[index] = newId;
          ensureDialogueTtsLink(index, newId);
          maybeAutoGenerateTts(created);
          if (opts.focus && typeof focusOnNode === 'function') focusOnNode(newId);
          if (!opts.silent) showToast(tr('dialogue_tts_created', '已创建文字转语音节点'), 'success');
          if (typeof safeAutoSave === 'function') safeAutoSave();
          updateDialogueList();
          return newId;
        }

        async function createDialogueTtsNodes() {
          if (!node.data.dialogues || node.data.dialogues.length === 0) {
            showToast(tr('dialogue_no_data', '暂无对话数据'), 'warning');
            return;
          }
          var ready = 0;
          for (var ci = 0; ci < node.data.dialogues.length; ci++) {
            try {
              var createdId = await ensureDialogueTtsNode(ci, { silent: true, focus: false });
              if (createdId != null) ready++;
            } catch (err) {
              console.error('创建文字转语音节点失败:', err);
            }
          }
          if (typeof setSelected === 'function') setSelected(node.id);
          if (ready > 0) {
            showToast(tr('dialogue_tts_all_created', '已为每句对话准备文字转语音节点'), 'success');
          } else {
            showToast(tr('dialogue_tts_empty_line', '这句对话没有文本，无法创建语音节点'), 'warning');
          }
          if (typeof safeAutoSave === 'function') safeAutoSave();
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

        // 从角色库搜索角色列表（角色名自动补全下拉用）
        async function searchWorldCharacters(keyword) {
          var worldId = state.defaultWorldId;
          if (!worldId) return [];
          try {
            var authToken = getAuthToken();
            var userId = getUserId();
            var response = await fetch('/api/characters?world_id=' + worldId + '&page=1&page_size=100&keyword=' + encodeURIComponent((keyword || '').replace(/【/g, '').replace(/】/g, '')), {
              headers: {
                'Authorization': authToken || '',
                'X-User-Id': userId || ''
              }
            });
            if (!response.ok) return [];
            var result = await response.json();
            if (result.code === 0 && result.data && Array.isArray(result.data.data)) {
              return result.data.data;
            }
          } catch (error) {
            console.error('搜索角色失败:', error);
          }
          return [];
        }

        // 角色名输入自动补全：优先用已加载到内存的世界角色（与提示词下拉同源），
        // 缓存为空时回退角色库 API 搜索；点选填入，也保留手动填写能力
        function attachCharacterAutocomplete(input, dropdown) {
          if (!input || !dropdown) return;
          var debounceTimer = null;

          function renderDropdown(items, keyword) {
            if (!input.isConnected) return;
            var worldId = state.defaultWorldId;
            if (!worldId) {
              dropdown.innerHTML = '<div style="padding: 8px; color: #6b7280; font-size: 12px;">' +
                escapeHtml(tr('dialogue_voice_no_world', '未选择世界，无法匹配角色')) + '</div>';
            } else if (!items || items.length === 0) {
              dropdown.innerHTML = '<div style="padding: 8px; color: #6b7280; font-size: 12px;">' +
                escapeHtml(tr('dialogue_no_character_match', '无匹配角色，可直接输入')) + '</div>';
            } else {
              var html = '';
              for (var ci = 0; ci < items.length; ci++) {
                var ch = items[ci];
                var name = (ch && ch.name) || '';
                var avatar = (ch && ch.reference_image) || '';
                html += '<div class="dialogue-character-option" data-character-name="' + escapeHtml(name) + '" style="padding: 8px 12px; cursor: pointer; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #f3f4f6;">' +
                  (avatar
                    ? '<img src="' + escapeHtml(avatar) + '" style="width: 24px; height: 24px; object-fit: cover; border-radius: 3px;" />'
                    : '<div style="width: 24px; height: 24px; background: #f3f4f6; border-radius: 3px; display: flex; align-items: center; justify-content: center; font-size: 11px; color: #9ca3af;">👤</div>') +
                  '<span style="font-size: 12px; color: #374151;">' + escapeHtml(name) + '</span>' +
                  '</div>';
              }
              dropdown.innerHTML = html;
              var options = dropdown.querySelectorAll('.dialogue-character-option');
              for (var oi = 0; oi < options.length; oi++) {
                (function(opt) {
                  opt.addEventListener('mousedown', function(e) {
                    e.preventDefault(); // 保持输入框焦点，blur 延迟隐藏前先完成选择
                    input.value = opt.getAttribute('data-character-name') || '';
                    dropdown.style.display = 'none';
                  });
                  opt.addEventListener('mouseenter', function() { opt.style.background = '#f8fafc'; });
                  opt.addEventListener('mouseleave', function() { opt.style.background = ''; });
                })(options[oi]);
              }
            }
            dropdown.style.display = 'block';
          }

          function refresh(keyword) {
            if (!input.isConnected) return;
            var worldId = state.defaultWorldId;
            var cached = worldId && Array.isArray(state.worldCharacters) ? state.worldCharacters : [];
            if (cached.length > 0) {
              var filtered = [];
              for (var fi = 0; fi < cached.length; fi++) {
                var name = (cached[fi] && cached[fi].name) || '';
                if (!keyword || name.indexOf(keyword) !== -1) filtered.push(cached[fi]);
              }
              renderDropdown(filtered.slice(0, 50), keyword);
              return;
            }
            searchWorldCharacters(keyword).then(function(items) {
              renderDropdown(items, keyword);
            });
          }

          input.addEventListener('focus', function() {
            refresh(input.value.trim());
          });
          input.addEventListener('input', function() {
            if (debounceTimer) clearTimeout(debounceTimer);
            var keyword = input.value.trim();
            debounceTimer = setTimeout(function() { refresh(keyword); }, 250);
          });
          input.addEventListener('blur', function() {
            // 延迟隐藏，保证 mousedown 选择先于 blur 触发
            setTimeout(function() { dropdown.style.display = 'none'; }, 150);
          });
        }

        function markLinePort(index, voice) {
          var port = el.querySelector('.dialogue-item[data-index="' + index + '"] .dialogue-voice-output');
          if (!port) return;
          var dialogue = node.data.dialogues && node.data.dialogues[index];
          var name = (dialogue && dialogue.character_name) || '';
          var ready = !!(voice && voice.url);
          port.classList.toggle('is-ready', ready);
          port.classList.toggle('disabled', !ready);
          if (ready) {
            port.title = tr('dialogue_voice_output_port', '参考音色') + ' · ' + (voice.name || name);
            return;
          }
          if (voice && voice.reason === 'no-world') {
            port.title = tr('dialogue_voice_no_world', '未选择世界，无法匹配角色参考音色');
            return;
          }
          if (voice && voice.matched) {
            port.title = tr('tts_voice_no_ref', '该节点没有可用的参考音色');
            return;
          }
          port.title = tr('dialogue_voice_unmatched', '当前世界没有角色「{name}」，无法连接参考音色').replace('{name}', name);
        }

        async function resolveWorldVoice(name) {
          var worldId = state.defaultWorldId;
          if (!worldId) return { matched: false, url: '', name: name, reason: 'no-world' };
          var matched = await fetchAndMatchCharacter(worldId, name);
          if (!matched || normalizeCharacterName(matched.name) !== normalizeCharacterName(name)) {
            return { matched: false, url: '', name: name, reason: 'unmatched' };
          }
          var url = String(matched.default_voice || '').trim();
          return { matched: true, url: url, name: matched.name || name, reason: url ? '' : 'no-voice' };
        }

        function ensureLineVoice(index) {
          var dialogue = node.data.dialogues && node.data.dialogues[index];
          var name = dialogue ? (dialogue.character_name || '') : '';
          var key = normalizeCharacterName(name);
          if (!key) return Promise.resolve({ matched: false, url: '', name: name, reason: 'empty' });
          if (!node._voiceByName) node._voiceByName = {};
          var cached = node._voiceByName[key];
          if (cached && typeof cached.then === 'function') return cached;
          if (cached && typeof cached === 'object') return Promise.resolve(cached);
          var task = resolveWorldVoice(name).then(function(voice) {
            node._voiceByName[key] = voice;
            return voice;
          }).catch(function() {
            var failed = { matched: false, url: '', name: name, reason: 'error' };
            node._voiceByName[key] = failed;
            return failed;
          });
          node._voiceByName[key] = task;
          return task;
        }

        function refreshLineVoices() {
          node._voiceByName = {};
          var dialogues = node.data.dialogues || [];
          for (var rvi = 0; rvi < dialogues.length; rvi++) {
            (function(index) {
              ensureLineVoice(index).then(function(voice) {
                markLinePort(index, voice);
              });
            })(rvi);
          }
        }

        function refreshConnectedLineVoice(index) {
          var conn = (state.audioConnections || []).find(function(c) {
            return String(c.from) === String(node.id) && c.portType === 'voice' && Number(c.voiceLineIndex) === Number(index);
          });
          if (!conn) return;
          ensureLineVoice(index).then(function(voice) {
            var target = state.nodes.find(function(n) { return String(n.id) === String(conn.to); });
            if (!target) return;
            if (!voice || !voice.url) {
              if (typeof target.clearConnectedVoice === 'function') target.clearConnectedVoice();
              return;
            }
            if (typeof target.applyConnectedVoice === 'function') {
              target.applyConnectedVoice({ url: voice.url, name: voice.name || '' });
            }
          });
        }

        function reindexDialogueVoiceConnections(deletedIndex) {
          var list = state.audioConnections || [];
          for (var dvi = 0; dvi < list.length; dvi++) {
            var outgoing = list[dvi];
            if (String(outgoing.from) !== String(node.id)) continue;
            if (outgoing.portType !== 'voice' && outgoing.portType !== 'dialogue_link') continue;
            if (outgoing.voiceLineIndex == null) continue;
            if (Number(outgoing.voiceLineIndex) !== Number(deletedIndex)) continue;
            if (outgoing.portType === 'voice') {
              var target = state.nodes.find(function(n) { return String(n.id) === String(outgoing.to); });
              if (target && typeof target.clearConnectedVoice === 'function') target.clearConnectedVoice();
            }
          }
          // 被删台词的来源关联线一并移除（"全部创建语音节点"时会按需重建）
          state.audioConnections = (state.audioConnections || []).filter(function(c) {
            if (String(c.from) !== String(node.id)) return true;
            if (c.portType !== 'dialogue_link') return true;
            if (c.voiceLineIndex == null) return true;
            return Number(c.voiceLineIndex) !== Number(deletedIndex);
          });
          var remaining = state.audioConnections || [];
          for (var rvi2 = 0; rvi2 < remaining.length; rvi2++) {
            var kept = remaining[rvi2];
            if (String(kept.from) !== String(node.id)) continue;
            if (kept.portType !== 'voice' && kept.portType !== 'dialogue_link') continue;
            if (kept.voiceLineIndex == null) continue;
            if (Number(kept.voiceLineIndex) > Number(deletedIndex)) kept.voiceLineIndex = Number(kept.voiceLineIndex) - 1;
          }
        }

        node.resolveLineVoice = ensureLineVoice;

        if (createTtsAllBtn) {
          createTtsAllBtn.addEventListener('click', async function(e) {
            e.stopPropagation();
            await createDialogueTtsNodes();
          });
        }

        updateDialogueList();

        if (videoInputPort) videoInputPort.classList.add('disabled');

        node.createDialogueTtsNodes = createDialogueTtsNodes;
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

      // 视频口保留在 DOM 中，但不再接受新的情感参考视频
      var videoInputPort = el.querySelector('.port.video-input-port');
      if (videoInputPort) videoInputPort.classList.add('disabled');

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
    }
  );

  window.resolveDialogueLineVoice = function(fromNode, lineIndex) {
    if (!fromNode || typeof fromNode.resolveLineVoice !== 'function') return Promise.resolve(null);
    return fromNode.resolveLineVoice(lineIndex);
  };

  window.attachDialogueLineVoice = async function(fromNode, voicePort, lineIndex) {
    var index = Number(lineIndex);
    if (!fromNode || fromNode.type !== 'dialogue_group' || !voicePort || !voicePort.node || isNaN(index)) return false;
    var voice = null;
    if (typeof fromNode.resolveLineVoice === 'function') {
      voice = await fromNode.resolveLineVoice(index);
    }
    if (!voice || !voice.url) {
      var dialogue = fromNode.data && fromNode.data.dialogues && fromNode.data.dialogues[index];
      var name = (dialogue && dialogue.character_name) || '';
      var msg;
      if (voice && voice.reason === 'no-world') {
        msg = tr('dialogue_voice_no_world', '未选择世界，无法匹配角色参考音色');
      } else if (voice && voice.matched) {
        msg = tr('tts_voice_no_ref', '该节点没有可用的参考音色');
      } else {
        msg = tr('dialogue_voice_unmatched', '当前世界没有角色「{name}」，无法连接参考音色').replace('{name}', name);
      }
      if (typeof showToast === 'function') showToast(msg, 'warning');
      return false;
    }
    if (typeof window.commitVoiceConnection !== 'function') return false;
    return window.commitVoiceConnection(fromNode, voicePort, { url: voice.url, name: voice.name || '' }, { voiceLineIndex: index });
  };

  // 注册到全局
  window.createDialogueGroupNode = createDialogueGroupNode;
  window.createDialogueGroupNodeWithData = createDialogueGroupNodeWithData;

  // 注册到节点注册表
  registerNodeType('dialogue_group', {
    createFn: createDialogueGroupNode,
    createWithDataFn: createDialogueGroupNodeWithData
  });

})();
