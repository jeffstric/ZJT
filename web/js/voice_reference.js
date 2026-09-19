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
