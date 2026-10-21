// ============================
// text_to_speech_node.js - 文字转语音节点
// 使用 createNodeBase 基类工厂
// 引擎：voice_library=火山音色库快速合成（扣算力，秒级）；
//       clone=参考音频克隆 IndexTTS（免费，异步轮询，原有链路）
// ============================

(function() {

  var TTS_PORTS = [
    { direction: 'output', titleI18nKey: 'tts_output_port' }
  ];

  function tr(key, fallback) {
    // window.t 缺键时返回键名本身，不能把键名当成译文
    if (typeof window.t !== 'function') return fallback;
    var value = window.t(key);
    if (!value || value === key) return fallback;
    return value;
  }

  function createTextToSpeechNode(opts) {
    return createNodeBase({
      type: 'text_to_speech',
      title: function(o) {
        var base = tr('tts_title', '文字转语音');
        var name = o && o.characterName ? String(o.characterName).trim() : '';
        return name ? (name + ' · ' + base) : base;
      },
      defaultData: function(o) {
        return {
          engine: (o && o.engine) || 'voice_library',
          voiceId: null,
          voiceName: '',
          speedRatio: 1.0,
          text: (o && o.text) || '',
          refAudioFile: null,
          refAudioUrl: (o && o.refAudioUrl) || '',
          emoRefAudioFile: null,
          emoRefAudioUrl: '',
          emoWeight: 1.0,
          emoControlMethod: 0,
          audioUrl: '',
          audioId: null,
          status: '',
          voiceSourceName: '',
          voiceFromConnection: false,
          dialogueGroupId: o && o.dialogueGroupId != null ? o.dialogueGroupId : null,
          dialogueIndex: o && o.dialogueIndex != null ? o.dialogueIndex : null
        };
      },
      ports: TTS_PORTS,
      width: 280,
      height: 250,
      titleIcon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M12 2C13.1046 2 14 2.89543 14 4V12C14 13.1046 13.1046 14 12 14C10.8956 14 10 13.1046 10 12V4C10 2.89543 10.8956 2 12 2Z"/><path d="M17 10V12C17 14.7614 14.7614 17 12 17C9.23858 17 7 14.7614 7 12V10" stroke-linecap="round"/><path d="M12 17V21M12 21H8M12 21H16" stroke-linecap="round"/></svg>',
      bodyHtml: function() {
        return '<div class="port input tts-dialogue-link-port" data-i18n="tts_dialogue_link_port:title" title="' + tr('tts_dialogue_link_port', '对话来源（由对话组生成）') + '"></div>' +
        '<div class="field">' +
          '<div class="label">' + tr('tts_engine_label', '合成引擎') + '</div>' +
          '<select class="tts-engine">' +
            '<option value="voice_library">' + tr('tts_engine_voice_library', '音色库合成（快速）') + '</option>' +
            '<option value="clone">' + tr('tts_engine_clone', '参考音频克隆（免费）') + '</option>' +
          '</select>' +
        '</div>' +
        '<div class="field">' +
          '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">' +
            '<div class="label" style="margin: 0;">' + tr('tts_text_label', '生成文本') + ' <span style="color: red;">*</span></div>' +
            '<button class="mini-btn tts-text-expand-btn" type="button" style="font-size: 11px; padding: 4px 8px;" title="' + tr('script_expand_btn', '放大编辑') + '">\u2922</button>' +
          '</div>' +
          '<textarea class="tts-text" rows="3" placeholder="' + tr('tts_text_placeholder', '输入要转换为语音的文本') + '"></textarea>' +
        '</div>' +
        '<div class="field tts-voice-socket">' +
          '<div class="port input voice-input-port" data-i18n="tts_voice_input_port:title" title="' + tr('tts_voice_input_port', '音色输入') + '"></div>' +
          '<div class="label">' + tr('tts_voice_input_label', '音色输入') + '</div>' +
          '<div class="gen-meta tts-voice-source">' + tr('tts_voice_input_hint', '可从音色库选择，或连接角色音色、音频节点') + '</div>' +
        '</div>' +
        '<div class="field tts-voice-field">' +
          '<div class="label">' + tr('tts_voice_label', '选择音色') + ' <span style="color: red;">*</span></div>' +
          '<div style="display:flex; gap:6px; align-items:center;">' +
            '<select class="tts-voice-select" style="flex:1;"><option value="">' + tr('tts_voice_loading', '加载中...') + '</option></select>' +
            '<button class="mini-btn tts-voice-preview-btn" type="button" style="font-size: 11px; padding: 4px 8px; flex-shrink:0;">▶</button>' +
          '</div>' +
          '<audio class="tts-voice-preview-audio" controls style="width:100%; max-height:32px; display:none; margin-top:4px;"></audio>' +
          '<div class="tts-voice-meta gen-meta" style="display:none; margin-top:4px;"></div>' +
        '</div>' +
        '<div class="field tts-speed-field">' +
          '<div class="label">' + tr('tts_speed_label', '语速') + ' (<span class="tts-speed-value">1.0</span>x)</div>' +
          '<input type="range" class="tts-speed" min="0.5" max="2" step="0.1" value="1.0" style="width:100%;" />' +
        '</div>' +
        '<div class="tts-clone-fields">' +
          '<div class="field">' +
            '<div class="label">' + tr('tts_ref_audio_label', '参考音色音频（可选）') + '</div>' +
            '<input class="tts-ref-audio" type="file" accept="audio/*" />' +
            '<div class="tts-ref-preview" style="display:none; margin-top:4px;">' +
              '<audio class="tts-ref-audio-player" controls style="width:100%; max-height:32px;"></audio>' +
              '<button class="mini-btn tts-ref-clear" type="button" style="margin-top:4px;">' + tr('tts_clear_btn', '清除') + '</button>' +
            '</div>' +
          '</div>' +
          '<div class="field">' +
            '<div class="label">' + tr('tts_emo_method_label', '情感控制方式') + '</div>' +
            '<select class="tts-emo-method">' +
              '<option value="0">' + tr('tts_emo_same_as_ref', '与参考音频相同') + '</option>' +
              '<option value="1">' + tr('tts_emo_use_ref', '使用情感参考音频') + '</option>' +
            '</select>' +
          '</div>' +
          '<div class="field tts-emo-ref-field" style="display:none;">' +
            '<div class="label">' + tr('tts_emo_ref_label', '情感参考音频') + '</div>' +
            '<input class="tts-emo-ref-audio" type="file" accept="audio/*" />' +
            '<div class="tts-emo-ref-preview" style="display:none; margin-top:4px;">' +
              '<audio class="tts-emo-ref-audio-player" controls style="width:100%; max-height:32px;"></audio>' +
              '<button class="mini-btn tts-emo-ref-clear" type="button" style="margin-top:4px;">' + tr('tts_clear_btn', '清除') + '</button>' +
            '</div>' +
          '</div>' +
          '<div class="field tts-emo-weight-field" style="display:none;">' +
            '<div class="label">' + tr('tts_emo_weight_label', '情感权重') + ' (<span class="tts-emo-weight-value">1.0</span>)</div>' +
            '<input type="range" class="tts-emo-weight" min="0" max="1.6" step="0.1" value="1.0" style="width:100%;" />' +
            '<div class="gen-meta" style="margin-top:4px;">' + tr('tts_emo_weight_hint', '调整情感的强度，0为无情感，1.6为最强情感') + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="field">' +
          '<button class="gen-btn tts-generate-btn" type="button">' + tr('tts_generate_btn', '生成语音') + '</button>' +
          '<div class="gen-meta tts-status" style="display:none;"></div>' +
        '</div>' +
        '<div class="field tts-result-field" style="display:none;">' +
          '<div class="label">' + tr('tts_result_label', '生成结果') + '</div>' +
          '<audio class="tts-result-audio" controls style="width:100%; margin-bottom:8px;"></audio>' +
          '<div style="display:flex; gap:8px;">' +
            '<button class="mini-btn tts-download-btn" type="button">' + tr('tts_download_btn', '下载音频') + '</button>' +
            '<button class="mini-btn tts-timeline-btn" type="button">' + tr('dialogue_add_timeline', '添加到时间轴') + '</button>' +
          '</div>' +
        '</div>';
      },
      onCreated: function(node, el) {
        var engineEl = el.querySelector('.tts-engine');
        var textEl = el.querySelector('.tts-text');
        var textExpandBtn = el.querySelector('.tts-text-expand-btn');
        var voiceField = el.querySelector('.tts-voice-field');
        var voiceSourceEl = el.querySelector('.tts-voice-source');
        var voiceSelectEl = el.querySelector('.tts-voice-select');
        var voicePreviewBtn = el.querySelector('.tts-voice-preview-btn');
        var voicePreviewAudio = el.querySelector('.tts-voice-preview-audio');
        var voiceMetaEl = el.querySelector('.tts-voice-meta');
        var speedField = el.querySelector('.tts-speed-field');
        var speedEl = el.querySelector('.tts-speed');
        var speedValueEl = el.querySelector('.tts-speed-value');
        var cloneFields = el.querySelector('.tts-clone-fields');
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
        var timelineBtn = el.querySelector('.tts-timeline-btn');

        function setNodeTitle(title) {
          node.title = title;
          var titleEl = el.querySelector('.node-title');
          if (!titleEl) return;
          var svg = titleEl.querySelector('svg');
          titleEl.textContent = '';
          if (svg) titleEl.appendChild(svg);
          titleEl.appendChild(document.createTextNode(title));
        }

        function showStoredRefAudio(url) {
          if (!refPreviewEl || !refAudioPlayer || !url) return;
          refAudioPlayer.src = (typeof proxyDownloadUrl === 'function') ? proxyDownloadUrl(url) : url;
          refPreviewEl.style.display = 'block';
        }

        // 对话组创建的节点会在生成前写入台词、角色名和参考音频
        node.applyTtsPatch = function(patch) {
          if (!patch) return;
          if (patch.text != null) {
            var nextText = String(patch.text);
            var textChanged = nextText !== (node.data.text || '');
            node.data.text = nextText;
            if (textEl) textEl.value = nextText;
            updateVoiceMeta();
            if (textChanged) {
              node.data.audioUrl = '';
              node.data.audioId = null;
              node.data.status = '';
              if (resultField) resultField.style.display = 'none';
              if (resultAudio) {
                resultAudio.pause();
                resultAudio.removeAttribute('src');
              }
            }
          }
          if (patch.characterName) {
            setNodeTitle(String(patch.characterName).trim() + ' · ' + tr('tts_title', '文字转语音'));
          }
          if (patch.engine) {
            node.data.engine = patch.engine;
            if (engineEl) engineEl.value = patch.engine;
            applyEngineVisibility();
          }
          if (patch.refAudioUrl) {
            node.data.refAudioUrl = patch.refAudioUrl;
            node.data.refAudioFile = null;
            showStoredRefAudio(patch.refAudioUrl);
          }
          if (patch.voiceSourceName != null) {
            node.data.voiceSourceName = patch.voiceSourceName;
            node.data.voiceFromConnection = !!patch.voiceFromConnection;
            showVoiceSource(patch.voiceSourceName);
          }
        };

        function showVoiceSource(name) {
          if (!voiceSourceEl) return;
          if (!name) {
            voiceSourceEl.textContent = tr('tts_voice_input_hint', '可从音色库选择，或连接角色音色、音频节点');
            return;
          }
          voiceSourceEl.textContent = tr('tts_voice_connected', '已连接音色：{name}').replace('{name}', name);
        }

        // 生成成功后同步输出音频节点：
        // 已有关联音频节点（且确实由本节点生成）则更新其音频，否则在右侧新建音频节点并连线。
        // 结果落在画布音频节点上，而不是只显示在节点内的"生成结果"里。
        function ensureAudioOutputNode() {
          if (!node.data.audioUrl) return null;
          if (typeof createAudioNode !== 'function') return null;

          var audioNode = null;
          if (node.data.audioNodeId != null) {
            var candidate = state.nodes.find(function(n) {
              return n.id === node.data.audioNodeId && n.type === 'audio';
            });
            // 复制粘贴等场景可能残留指向其他节点的 id，校验回指关系避免误更新
            if (candidate && candidate.data && candidate.data.ttsNodeId === node.id) {
              audioNode = candidate;
            }
          }

          if (audioNode) {
            audioNode.data.url = node.data.audioUrl;
            audioNode.data.name = node.title || tr('tts_title', '文字转语音');
            var el = canvasEl.querySelector('.node[data-node-id="' + audioNode.id + '"]');
            if (el) {
              var player = el.querySelector('.audio-node-player');
              var nameEl = el.querySelector('.audio-node-name');
              var previewField = el.querySelector('.audio-preview-field');
              var previewActionsField = el.querySelector('.audio-preview-actions-field');
              if (player) player.src = (typeof proxyDownloadUrl === 'function') ? proxyDownloadUrl(audioNode.data.url) : audioNode.data.url;
              if (nameEl) {
                var displayName = audioNode.data.name.length > 15 ? audioNode.data.name.substring(0, 15) + '...' : audioNode.data.name;
                nameEl.textContent = '🎵 ' + displayName;
                nameEl.title = audioNode.data.name;
              }
              if (previewField) previewField.style.display = 'block';
              if (previewActionsField) previewActionsField.style.display = 'block';
            }
            return audioNode.id;
          }

          var audioId = createAudioNode({
            x: node.x + 340,
            y: node.y,
            checkCollision: true,
            title: tr('tts_audio_node_title', '语音'),
            data: {
              url: node.data.audioUrl,
              name: node.title || tr('tts_title', '文字转语音')
            }
          });
          var created = state.nodes.find(function(n) { return n.id === audioId; });
          if (created && created.data) {
            created.data.ttsNodeId = node.id;
            if (node.data.dialogueGroupId != null) created.data.sourceNodeId = node.data.dialogueGroupId;
            if (node.data.dialogueIndex != null) created.data.dialogueIndex = node.data.dialogueIndex;
          }
          node.data.audioNodeId = audioId;

          // 文字转语音 → 音频节点 的产出连线（普通音频连接）
          if (!state.audioConnections) state.audioConnections = [];
          var exists = state.audioConnections.some(function(c) {
            return c.from === node.id && c.to === audioId && !c.portType;
          });
          if (!exists) {
            state.audioConnections.push({
              id: state.nextAudioConnId++,
              from: node.id,
              to: audioId
            });
          }
          if (typeof renderAudioConnections === 'function') renderAudioConnections();
          return audioId;
        }

        node.ensureAudioOutputNode = ensureAudioOutputNode;

        function detachVoiceConnection() {
          if (state.audioConnections) {
            state.audioConnections = state.audioConnections.filter(function(c) {
              return !(String(c.to) === String(node.id) && c.portType === 'voice');
            });
          }
          if (typeof renderAudioConnections === 'function') renderAudioConnections();
        }

        node.applyConnectedVoice = function(voice) {
          if (!voice || !voice.url) return;
          node.applyTtsPatch({
            engine: 'clone',
            refAudioUrl: voice.url,
            voiceSourceName: voice.name || '',
            voiceFromConnection: true
          });
        };

        node.clearConnectedVoice = function() {
          detachVoiceConnection();
          if (!node.data.voiceFromConnection) {
            showVoiceSource('');
            return;
          }
          node.data.voiceFromConnection = false;
          node.data.voiceSourceName = '';
          node.data.refAudioUrl = '';
          node.data.refAudioFile = null;
          node.data.engine = 'voice_library';
          if (engineEl) engineEl.value = 'voice_library';
          applyEngineVisibility();
          if (refPreviewEl) refPreviewEl.style.display = 'none';
          if (refAudioPlayer) {
            refAudioPlayer.removeAttribute('src');
            refAudioPlayer.load();
          }
          showVoiceSource('');
        };

        node.updateVoiceSourceLabel = function() {
          showVoiceSource(node.data.voiceSourceName || '');
        };

        node.syncConnectedVoice = function() {
          var conn = (state.audioConnections || []).find(function(c) {
            return String(c.to) === String(node.id) && c.portType === 'voice';
          });
          if (!conn) {
            if (node.data.voiceFromConnection) node.clearConnectedVoice();
            return;
          }
          var fromNode = state.nodes.find(function(n) { return String(n.id) === String(conn.from); });
          if (fromNode && fromNode.type === 'dialogue_group' && conn.voiceLineIndex != null
              && typeof window.resolveDialogueLineVoice === 'function') {
            var lineIndex = conn.voiceLineIndex;
            window.resolveDialogueLineVoice(fromNode, lineIndex).then(function(voice) {
              var still = (state.audioConnections || []).some(function(c) {
                return String(c.to) === String(node.id) && c.portType === 'voice'
                  && String(c.from) === String(fromNode.id)
                  && Number(c.voiceLineIndex) === Number(lineIndex);
              });
              if (!still) return;
              if (!voice || !voice.url) {
                node.clearConnectedVoice();
                return;
              }
              node.applyConnectedVoice({ url: voice.url, name: voice.name || '' });
            });
            return;
          }
          var voice = resolveNodeVoice(fromNode);
          if (!voice) {
            node.clearConnectedVoice();
            return;
          }
          node.applyConnectedVoice(voice);
        };

        // 节点级音色缓存（voices + 计价档位）
        var voiceOptions = [];
        var powerTiers = [];

        function applyEngineVisibility() {
          var isLibrary = node.data.engine === 'voice_library';
          if (voiceField) voiceField.style.display = isLibrary ? 'block' : 'none';
          if (speedField) speedField.style.display = isLibrary ? 'block' : 'none';
          if (cloneFields) cloneFields.style.display = isLibrary ? 'none' : 'block';
        }

        function updateVoiceMeta() {
          if (!voiceMetaEl) return;
          var voice = voiceOptions.find(function(v) { return v.id === node.data.voiceId; });
          if (!voice || !node.data.text || !node.data.text.trim()) {
            voiceMetaEl.style.display = 'none';
            return;
          }
          var power = window.VoiceLibraryApi
            ? window.VoiceLibraryApi.estimatePower(node.data.text.trim().length, powerTiers)
            : 0;
          if (power > 0) {
            voiceMetaEl.style.display = 'block';
            voiceMetaEl.textContent = tr('tts_estimated_cost', '预计消耗 {power} 算力').replace('{power}', power);
          } else {
            voiceMetaEl.style.display = 'none';
          }
        }

        async function loadVoices() {
          if (!window.VoiceLibraryApi) return;
          try {
            // 快速合成只能用火山音色；reference_audio 是克隆参考，不能走这条链路
            var data = await window.VoiceLibraryApi.listVoices({ page_size: 300, provider: 'volcengine' });
            voiceOptions = data.voices || [];
            powerTiers = data.power_tiers || [];
            var esc = window.escapeHtml || function(s) { return String(s == null ? '' : s); };
            voiceSelectEl.innerHTML = '<option value="">' + esc(tr('tts_voice_placeholder', '请选择音色')) + '</option>' +
              voiceOptions.map(function(v) {
                return '<option value="' + v.id + '">' + esc(v.name) + '</option>';
              }).join('');
            if (node.data.voiceId) voiceSelectEl.value = String(node.data.voiceId);
          } catch (e) {
            console.error('音色库加载失败:', e);
            voiceSelectEl.innerHTML = '<option value="">' +
              esc2(tr('tts_voice_load_failed', '音色库加载失败')) + '</option>';
          }
        }

        function esc2(s) { return window.escapeHtml ? window.escapeHtml(s) : String(s); }

        // 引擎切换
        engineEl.addEventListener('change', function() {
          node.data.engine = engineEl.value;
          applyEngineVisibility();
        });

        // 文本输入
        textEl.addEventListener('input', function() {
          node.data.text = textEl.value;
          updateVoiceMeta();
        });

        // 文本放大按钮
        textExpandBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          showPromptExpandModal(textEl, tr('tts_text_label', '生成文本'), function(newValue) {
            node.data.text = newValue;
            updateVoiceMeta();
          });
        });

        // 音色选择
        voiceSelectEl.addEventListener('change', function() {
          node.data.voiceId = voiceSelectEl.value ? parseInt(voiceSelectEl.value, 10) : null;
          var voice = voiceOptions.find(function(v) { return v.id === node.data.voiceId; });
          node.data.voiceName = voice ? voice.name : '';
          updateVoiceMeta();
        });

        // 音色试听（服务端固定示例句 + 缓存，免费）
        voicePreviewBtn.addEventListener('click', async function(e) {
          e.stopPropagation();
          if (!node.data.voiceId || !window.VoiceLibraryApi) return;
          try {
            var data = await window.VoiceLibraryApi.previewVoice(node.data.voiceId);
            if (data.audio_url) {
              voicePreviewAudio.src = data.audio_url;
              voicePreviewAudio.style.display = 'block';
              voicePreviewAudio.play();
            }
          } catch (err) {
            showToast((err && err.message) || tr('tts_preview_failed', '试听失败'), 'error');
          }
        });

        // 语速滑块
        speedEl.addEventListener('input', function() {
          node.data.speedRatio = parseFloat(speedEl.value);
          speedValueEl.textContent = node.data.speedRatio.toFixed(1);
        });

        // 参考音色音频上传
        refAudioEl.addEventListener('change', function() {
          var file = refAudioEl.files && refAudioEl.files[0];
          if (!file) return;
          node.data.refAudioFile = file;
          if (node.data.voiceFromConnection) {
            node.data.voiceFromConnection = false;
            node.data.voiceSourceName = '';
            showVoiceSource('');
            detachVoiceConnection();
          }
          if (refAudioPlayer.src && refAudioPlayer.src.startsWith('blob:')) URL.revokeObjectURL(refAudioPlayer.src);
          var localUrl = URL.createObjectURL(file);
          refAudioPlayer.src = localUrl;
          refPreviewEl.style.display = 'block';
        });

        // 清除参考音色
        refClearBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          if (node.data.voiceFromConnection) {
            node.clearConnectedVoice();
            if (refAudioEl) refAudioEl.value = '';
            if (typeof safeAutoSave === 'function') safeAutoSave();
            return;
          }
          node.data.refAudioFile = null;
          node.data.refAudioUrl = '';
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

        // ============ 音色库（火山快速合成）路径 ============
        async function generateWithVoiceLibrary() {
          if (!node.data.voiceId) {
            showToast(tr('tts_voice_required', '请先选择音色'), 'warning');
            return;
          }
          try {
            setBtnLoading(generateBtn, tr('tts_generating', '生成中...'));
            statusEl.style.display = 'block';
            statusEl.style.color = '';
            statusEl.textContent = tr('tts_generating_audio', '正在生成音频...');
            resultField.style.display = 'none';

            var data = await window.VoiceLibraryApi.synthesize({
              text: node.data.text,
              voice_id: node.data.voiceId,
              speed_ratio: node.data.speedRatio || 1.0,
            });

            node.data.audioUrl = data.audio_url;
            node.data.audioId = data.audio_id || null;
            node.data.status = 'SUCCESS';
            // 生成结果输出为画布上的音频节点（保留节点内生成结果区域隐藏）
            ensureAudioOutputNode();
            statusEl.style.color = '#16a34a';
            statusEl.textContent = tr('tts_generate_success', '生成成功！');
            setBtnReady(generateBtn, tr('tts_generate_btn', '生成语音'));
            showToast(tr('tts_generate_success', '语音生成成功'), 'success');
          } catch (error) {
            console.error('火山TTS生成失败:', error);
            statusEl.style.color = '#dc2626';
            statusEl.textContent = tr('tts_generate_failed', '生成失败') + ': ' + (error.message || '未知错误');
            setBtnReady(generateBtn, tr('tts_generate_btn', '生成语音'));
            showToast(tr('tts_generate_failed', '语音生成失败'), 'error');
          }
        }

        // ============ 克隆（IndexTTS）路径（原有逻辑） ============
        async function generateWithClone() {
          try {
            setBtnLoading(generateBtn, tr('tts_generating', '生成中...'));
            statusEl.style.display = 'block';
            statusEl.style.color = '';
            statusEl.textContent = tr('tts_generating_audio', '正在生成音频...');
            resultField.style.display = 'none';

            var form = new FormData();
            form.append('text', node.data.text);
            form.append('user_id', userId);
            form.append('emo_control_method', node.data.emoControlMethod);

            if (node.data.refAudioFile) {
              form.append('ref_audio', node.data.refAudioFile);
            } else if (node.data.refAudioUrl) {
              var refRes = await fetch((typeof proxyDownloadUrl === 'function') ? proxyDownloadUrl(node.data.refAudioUrl) : node.data.refAudioUrl);
              if (!refRes.ok) {
                throw new Error('获取参考音频失败: ' + refRes.status);
              }
              var refBlob = await refRes.blob();
              form.append('ref_audio', refBlob, 'ref_audio.wav');
            }

            if (node.data.emoControlMethod === 1) {
              if (node.data.emoRefAudioFile) {
                form.append('emo_ref_audio', node.data.emoRefAudioFile);
              }
              form.append('emo_weight', node.data.emoWeight);
            }

            // 认证走 Authorization 头（服务端 require_permission 只读头/query，
            // 不读 form 字段；不带头的请求会落到 cookie 翻译，cookie 失效即 401）
            var headers = {};
            var authToken = getAuthToken();
            if (authToken) {
              headers['Authorization'] = 'Bearer ' + authToken;
            }

            var res = await fetch('/api/audio-generate', {
              method: 'POST',
              headers: headers,
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
            statusEl.textContent = tr('tts_generate_failed', '生成失败') + ': ' + (error.message || '未知错误');
            setBtnReady(generateBtn, tr('tts_generate_btn', '生成语音'));
            showToast(tr('tts_generate_failed', '语音生成失败'), 'error');
          }
        }

        var userId = null;

        // 统一生成入口：手动点击「生成语音」与对话组自动生成都走这里。
        // 生成中按钮处于 disabled，借此防重入（含自动触发的并发保护）。
        async function requestGenerate() {
          if (generateBtn.disabled) return;

          if (!node.data.text.trim()) {
            showToast(tr('tts_no_text_error', '请输入生成文本'), 'warning');
            return;
          }

          userId = getUserId();
          if (!userId) {
            showToast(tr('tts_login_required', '请先登录后再使用语音生成功能'), 'error');
            return;
          }

          if (node.data.engine === 'voice_library') {
            await generateWithVoiceLibrary();
          } else {
            await generateWithClone();
          }
        }
        node.requestGenerate = requestGenerate;

        // 生成语音按钮
        generateBtn.addEventListener('click', async function(e) {
          e.stopPropagation();
          await requestGenerate();
        });

        // 轮询音频状态（仅克隆引擎使用）
        function pollAudioStatus(nodeId, node) {
          pollTaskStatus({
            statusUrl: '/api/audio-status/' + node.data.audioId,
            onSuccess: function(payload) {
              if (payload.result_url) {
                node.data.audioUrl = payload.result_url;
                // 生成结果输出为画布上的音频节点（保留节点内生成结果区域隐藏）
                ensureAudioOutputNode();
              }
              statusEl.style.color = '#16a34a';
              statusEl.textContent = tr('tts_generate_success', '生成成功！');
              setBtnReady(generateBtn, tr('tts_generate_btn', '生成语音'));
              showToast(tr('tts_generate_success', '语音生成成功'), 'success');
            },
            onFailed: function(payload) {
              statusEl.style.color = '#dc2626';
              statusEl.textContent = tr('tts_generate_failed', '生成失败') + ': ' + (payload.reason || payload.message || '未知错误');
              setBtnReady(generateBtn, tr('tts_generate_btn', '生成语音'));
              showToast(tr('tts_generate_failed', '语音生成失败'), 'error');
            },
            onTimeout: function() {
              statusEl.style.color = '#dc2626';
              statusEl.textContent = tr('tts_generate_timeout_hint', '等待超时，但音频仍在生成中。你可以通过刷新页面后查看是否生成成功。');
              setBtnReady(generateBtn, tr('tts_generate_btn', '生成语音'));
            }
          });
        }

        if (timelineBtn) {
          timelineBtn.addEventListener('click', async function(e) {
            e.stopPropagation();
            if (!node.data.audioUrl) {
              showToast(tr('tts_no_audio_error', '没有可下载的音频'), 'error');
              return;
            }
            if (typeof addAudioToTimeline !== 'function') {
              showToast(tr('dialogue_no_audio_to_add', '没有可添加的音频'), 'error');
              return;
            }
            var targetId = node.data.dialogueGroupId != null ? node.data.dialogueGroupId : node.id;
            var lineIndex = node.data.dialogueIndex != null ? node.data.dialogueIndex : 0;
            var audioName = node.title || tr('tts_title', '文字转语音');
            var duration = 5;
            if (typeof getAudioDuration === 'function') {
              try {
                duration = await getAudioDuration(node.data.audioUrl);
              } catch (err) {
                duration = 5;
              }
            }
            addAudioToTimeline(targetId, lineIndex, node.data.audioUrl, audioName, duration);
          });
        }

        // 下载按钮
        downloadBtn.addEventListener('click', async function(e) {
          e.stopPropagation();
          if (!node.data.audioUrl) {
            showToast(tr('tts_no_audio_error', '没有可下载的音频'), 'error');
            return;
          }

          var now = new Date();
          var dateStr = now.getFullYear().toString() +
                        (now.getMonth() + 1).toString().padStart(2, '0') +
                        now.getDate().toString().padStart(2, '0');
          var timeStr = now.getHours().toString().padStart(2, '0') +
                        now.getMinutes().toString().padStart(2, '0');
          var ext = /\.(mp3|wav|aac|ogg|m4a)(\?|$)/i.exec(node.data.audioUrl || '') ?
            /\.(mp3|wav|aac|ogg|m4a)(\?|$)/i.exec(node.data.audioUrl)[1] : 'mp3';
          var filename = 'audio_' + dateStr + '_' + timeStr + '.' + ext;

          try {
            await window.downloadWithAuth(node.data.audioUrl, filename);
            showToast(tr('tts_download_start', '开始下载'), 'success');
          } catch (err) {
            if (err && err.status === 401) return;
            showToast((err && err.message) || '下载失败', 'error');
          }
        });

        // 初始化
        engineEl.value = node.data.engine || 'clone';
        applyEngineVisibility();
        if (textEl && node.data.text) textEl.value = node.data.text;
        if (node.data.refAudioUrl) showStoredRefAudio(node.data.refAudioUrl);
        showVoiceSource(node.data.voiceSourceName || '');
        loadVoices();
      }
    }, opts);
  }

  var createTextToSpeechNodeWithData = createNodeWithDataFactory(
    createTextToSpeechNode,
    function(el, node) {
      var engineEl = el.querySelector('.tts-engine');
      var voiceField = el.querySelector('.tts-voice-field');
      var speedField = el.querySelector('.tts-speed-field');
      var cloneFields = el.querySelector('.tts-clone-fields');
      var voiceSelectEl = el.querySelector('.tts-voice-select');
      var speedEl = el.querySelector('.tts-speed');
      var speedValueEl = el.querySelector('.tts-speed-value');
      var textEl = el.querySelector('.tts-text');
      var emoMethodEl = el.querySelector('.tts-emo-method');
      var emoRefField = el.querySelector('.tts-emo-ref-field');
      var emoWeightField = el.querySelector('.tts-emo-weight-field');
      var emoWeightEl = el.querySelector('.tts-emo-weight');
      var emoWeightValueEl = el.querySelector('.tts-emo-weight-value');
      var statusEl = el.querySelector('.tts-status');
      var resultField = el.querySelector('.tts-result-field');
      var resultAudio = el.querySelector('.tts-result-audio');

      var titleEl = el.querySelector('.node-title');
      if (titleEl && node.title) {
        var svg = titleEl.querySelector('svg');
        titleEl.textContent = '';
        if (svg) titleEl.appendChild(svg);
        titleEl.appendChild(document.createTextNode(node.title));
      }

      // 老节点（无 engine 字段）回退 clone，保持既有工作流行为不变
      node.data.engine = node.data.engine === 'voice_library' ? 'voice_library' : 'clone';
      if (engineEl) engineEl.value = node.data.engine;
      var isLibrary = node.data.engine === 'voice_library';
      if (voiceField) voiceField.style.display = isLibrary ? 'block' : 'none';
      if (speedField) speedField.style.display = isLibrary ? 'block' : 'none';
      if (cloneFields) cloneFields.style.display = isLibrary ? 'none' : 'block';

      if (voiceSelectEl && node.data.voiceId) {
        voiceSelectEl.value = String(node.data.voiceId);
        // onCreated 里的 loadVoices 是异步的，选项填充晚于恢复回调时再补一次
        setTimeout(function() {
          if (voiceSelectEl.querySelector('option[value="' + node.data.voiceId + '"]')) {
            voiceSelectEl.value = String(node.data.voiceId);
          }
        }, 1200);
      }

      if (speedEl && node.data.speedRatio !== undefined && node.data.speedRatio !== null) {
        speedEl.value = node.data.speedRatio;
        if (speedValueEl) speedValueEl.textContent = parseFloat(node.data.speedRatio).toFixed(1);
      }

      if (textEl && node.data.text) {
        textEl.value = node.data.text;
      }

      if (node.data.refAudioUrl) {
        var refPreviewEl = el.querySelector('.tts-ref-preview');
        var refAudioPlayer = el.querySelector('.tts-ref-audio-player');
        if (refPreviewEl && refAudioPlayer) {
          refAudioPlayer.src = (typeof proxyDownloadUrl === 'function') ? proxyDownloadUrl(node.data.refAudioUrl) : node.data.refAudioUrl;
          refPreviewEl.style.display = 'block';
        }
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
      if (typeof node.updateVoiceSourceLabel === 'function') node.updateVoiceSourceLabel();
    }
  );

  function resolveNodeVoice(fromNode) {
    if (!fromNode || !fromNode.data) return null;
    var url = '';
    var name = '';
    if (fromNode.type === 'character') {
      url = String(fromNode.data.default_voice || '').trim();
      name = fromNode.data.name || fromNode.title || '';
    } else if (fromNode.type === 'audio') {
      url = String(fromNode.data.url || '').trim();
      name = fromNode.data.name || fromNode.title || '';
    }
    if (!url) return null;
    return { url: url, name: name };
  }

  function commitVoiceConnection(fromNode, voicePort, voice, extra) {
    if (!fromNode || !voicePort || !voicePort.node || !voice || !voice.url) return false;
    if (!state.audioConnections) state.audioConnections = [];
    var lineIndex = extra && extra.voiceLineIndex != null ? Number(extra.voiceLineIndex) : null;
    var same = state.audioConnections.some(function(c) {
      if (String(c.from) !== String(fromNode.id) || String(c.to) !== String(voicePort.nodeId) || c.portType !== 'voice') return false;
      if (lineIndex == null) return c.voiceLineIndex == null;
      return Number(c.voiceLineIndex) === lineIndex;
    });
    if (!same) {
      state.audioConnections = state.audioConnections.filter(function(c) {
        return !(String(c.to) === String(voicePort.nodeId) && c.portType === 'voice');
      });
      var conn = {
        id: state.nextAudioConnId++,
        from: fromNode.id,
        to: voicePort.nodeId,
        portType: 'voice'
      };
      if (lineIndex != null && !isNaN(lineIndex)) conn.voiceLineIndex = lineIndex;
      state.audioConnections.push(conn);
    }
    if (typeof voicePort.node.applyConnectedVoice === 'function') {
      voicePort.node.applyConnectedVoice(voice);
    }
    if (typeof renderAudioConnections === 'function') renderAudioConnections();
    if (typeof safeAutoSave === 'function') safeAutoSave();
    return true;
  }

  function attachVoiceConnection(fromNode, voicePort) {
    if (!fromNode || !voicePort || !voicePort.node) return false;
    var voice = resolveNodeVoice(fromNode);
    if (!voice) {
      if (typeof showToast === 'function') {
        showToast(tr('tts_voice_no_ref', '该节点没有可用的参考音色'), 'warning');
      }
      return false;
    }
    return commitVoiceConnection(fromNode, voicePort, voice, null);
  }

  window.resolveNodeVoice = resolveNodeVoice;
  window.commitVoiceConnection = commitVoiceConnection;
  window.attachVoiceConnection = attachVoiceConnection;

  if (typeof registerInputPorts === 'function') {
    registerInputPorts('text_to_speech', [{
      selector: '.port.voice-input-port',
      portType: 'voice',
      accepts: ['voice', 'audio'],
      connectionType: 'audioConnections'
    }]);
  }

  // 注册到全局
  window.createTextToSpeechNode = createTextToSpeechNode;
  window.createTextToSpeechNodeWithData = createTextToSpeechNodeWithData;

  // 注册到节点注册表
  registerNodeType('text_to_speech', {
    createFn: createTextToSpeechNode,
    createWithDataFn: createTextToSpeechNodeWithData
  });

})();
