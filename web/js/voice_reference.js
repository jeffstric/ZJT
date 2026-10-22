// 参考生视频角色音色注入（模型能力位 supports_voice_input 门控）
// 生视频节点 / 分镜节点 / 分镜组节点提交参考生视频（multi_reference）时复用：
// 把角色默认音色（default_voice 克隆源音频）并入参考音频，并在提示词尾部追加
// 音色说明；模型不支持（grok 等）时不注入音频与文字，行为不变。
// 纯提交期逻辑，不产生节点持久化状态，工作流重载复原不受影响。

// 与后端 config/constant.py MAX_VOICE_REFERENCE_AUDIOS 对齐（MiniMax H3 LoadAudio 硬上限 2）
const VOICE_REFERENCE_MAX_AUDIOS = 2;

// 读取模型能力位；TaskConfig 未加载或字段缺失时按不支持处理（不注入）
function modelSupportsVoiceInput(modelKey){
  if(!window.TaskConfig || !window.TaskConfig.isLoaded || !window.TaskConfig.isLoaded()) return false;
  const configs = window.TaskConfig.getModelConfigs();
  return !!(configs && configs[modelKey] && configs[modelKey].supports_voice_input === true);
}

// 角色音色 URL 兼容相对路径（如 /upload/character/voice/xx.wav），转绝对地址
function resolveVoiceUrl(voice){
  const raw = String(voice || '').trim();
  if(!raw) return '';
  try {
    return new URL(raw, location.origin).href;
  } catch(e) {
    return raw;
  }
}

// 提示词音色说明；序号从 startIndex 起（对齐最终参考音频列表中的位置）
function buildVoiceReferenceNote(entries, startIndex){
  const parts = [];
  (entries || []).forEach(function(entry, i){
    if(!entry || !entry.name) return;
    parts.push('音频' + (startIndex + i) + '是角色：' + entry.name + '的音色样本');
  });
  if(!parts.length) return '';
  return '参考音频说明：' + parts.join('，') + '，角色说话时请保持相同音色。';
}

// 幂等追加：提示词已含同一说明时不重复
function appendVoiceReferencePrompt(prompt, note){
  if(!note || prompt.indexOf(note) !== -1) return prompt;
  return (String(prompt || '').trim() + '\n\n' + note).trim();
}

// 收集角色音色参考。characterEntries 为角色对象数组（取 .name 与 .default_voice）。
// existingAudioUrls：用户已手动携带的参考音频（数组或逗号拼接串），用于去重与序号偏移。
// 返回 { enabled, voiceUrls, names, promptNote }；不满足条件时各项为空。
function collectVoiceReferences(modelKey, characterEntries, existingAudioUrls){
  const result = { enabled: false, voiceUrls: [], names: [], promptNote: '' };
  if(!modelSupportsVoiceInput(modelKey)) return result;

  const existing = [];
  const seen = {};
  String(existingAudioUrls || '')
    .split(',')
    .forEach(function(url){
      const trimmed = url.trim();
      if(trimmed && !seen[trimmed]){
        seen[trimmed] = true;
        existing.push(trimmed);
      }
    });

  const entries = [];
  (characterEntries || []).forEach(function(character){
    if(entries.length >= VOICE_REFERENCE_MAX_AUDIOS) return;
    if(!character) return;
    const name = String(character.name || '').trim();
    const url = resolveVoiceUrl(character.default_voice);
    if(!name || !url || seen[url]) return;
    seen[url] = true;
    entries.push({ name: name, url: url });
  });

  if(!entries.length) return result;
  result.enabled = true;
  result.voiceUrls = entries.map(function(entry){ return entry.url; });
  result.names = entries.map(function(entry){ return entry.name; });
  result.promptNote = buildVoiceReferenceNote(entries, existing.length + 1);
  return result;
}

// 轻量反馈：注入成功后 toast 提示（页面无 showToast 时静默）
function notifyVoiceReferences(count){
  if(count <= 0) return;
  if(typeof showToast === 'function'){
    showToast('已附带 ' + count + ' 个角色音色参考', 'info');
  }
}

// ==================== 角色声学音色指纹（voice_desc，仅 MiniMax H3） ====================
// H3 的参考音频只是弱微调，音色一致性主要由文字指纹承担（2026-10-14 消融实验结论）。
// 指纹随「角色音色说明」块注入提示词原文，由后端提示词优化 LLM 渲染为说话角色的
// 英文声音描述；情境语气（对下属严厉/对领导谄媚）由优化 LLM 按剧本现场叠加，不进指纹。

// MiniMax H3 提示词优化模型 key 清单（与后端 PipelineDriverFactory._H3_PROMPT_OPTIMIZE_KEYS
// 对齐，同时收录 UnifiedTaskConfig 的长 key 与 short_key——画布节点 modelKey 用的是
// short_key 如 minimax_h3_r2v）。注意不含数字人 digital_human_minimax_h3 与 t2v，
// 它们不走 H3 提示词优化
const H3_PROMPT_OPTIMIZE_MODEL_KEYS = [
  'minimax_h3_image_to_video', 'minimax_h3',      // I2VA 首帧生视频
  'minimax_h3_reference_to_video', 'minimax_h3_r2v', // Ref2VA 参考生视频
  'minimax_h3_keyframe_ref_to_video', 'minimax_h3_kfr', // KFRef 首帧参考混合
];

function modelIsH3OptimizeType(modelKey){
  return H3_PROMPT_OPTIMIZE_MODEL_KEYS.indexOf(String(modelKey || '')) !== -1;
}

// 「角色音色说明」块（与后端 storyboard_reference_prompt_service.build_voice_casting_note 同构）：
// 指纹句尾自带句号则不重复补，避免「命令。。描述」双句号
function buildVoiceCastingNote(characterEntries){
  const parts = [];
  (characterEntries || []).forEach(function(character){
    if(!character || !character.name) return;
    const desc = String(character.voice_desc || '').trim();
    if(!desc) return;
    parts.push(character.name + '的音色特征：' + desc + (/[。.!！?？]$/.test(desc) ? '' : '。'));
  });
  if(!parts.length) return '';
  return '角色音色说明：' + parts.join('；') + '描述这些角色说话的声音时必须遵循对应音色特征。';
}

// H3 系列任务（I2VA/Ref2VA/KFRef）：把角色音色指纹追加进提示词，幂等。
// 仅 H3 门控、不要求 multi_reference（首帧生视频同样靠指纹做音色一致性）；
// 不说话角色的指纹由后端优化 LLM 按模板规则忽略。其他模型零变化。
function appendVoiceCastingIfH3(modelKey, prompt, characterEntries){
  if(!modelIsH3OptimizeType(modelKey)) return prompt;
  const note = buildVoiceCastingNote(characterEntries);
  if(!note || String(prompt || '').indexOf(note) !== -1) return prompt;
  return (String(prompt || '').trim() + '\n\n' + note).trim();
}
