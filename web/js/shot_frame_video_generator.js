// 替换提示词中的角色标记
async function replaceCharacterMarkers(prompt){
  if(!prompt) return prompt;
  
  // 匹配 【【角色名】】 格式
  const characterPattern = /【【([^】]+)】】/g;
  const matches = [...prompt.matchAll(characterPattern)];
  
  if(matches.length === 0) return prompt;
  
  // 获取当前选择的世界ID
  const defaultWorldSelect = document.getElementById('defaultWorldSelect');
  const worldId = defaultWorldSelect ? defaultWorldSelect.value : '';
  
  if(!worldId){
    showToast('请先选择世界', 'warning');
    return prompt;
  }
  
  // 获取用户ID
  const userId = localStorage.getItem('user_id') || '1';
  
  let replacedPrompt = prompt;
  
  // 遍历所有匹配的角色标记
  for(const match of matches){
    const fullMatch = match[0];
    const characterName = match[1];
    
    try {
      // 调用API查询角色
      const response = await fetch(`/api/character/search?user_id=${userId}&world_id=${worldId}&name=${encodeURIComponent(characterName)}`);
      
      if(!response.ok){
        console.warn(`Failed to fetch character: ${characterName}`);
        continue;
      }
      
      const data = await response.json();
      
      if(data && data.sora_character){
        // 替换角色标记为 @sora_character ID，并在末尾添加空格
        replacedPrompt = replacedPrompt.replace(fullMatch, '@' + data.sora_character + ' ');
        console.log(`Replaced ${fullMatch} with @${data.sora_character} `);
      } else {
        console.warn(`Character ${characterName} found but no sora_character ID`);
      }
    } catch(error){
      console.error(`Error fetching character ${characterName}:`, error);
    }
  }
  
  // 处理提示词中已存在的角色ID（如 patiencep.dragonenvo），在前面添加 @ 符号
  // 匹配格式：单词.单词（但不是已经有@的），确保前面是空格或开头
  const existingIdPattern = /(?<=^|\s)([a-z][a-z0-9]*\.[a-z][a-z0-9]*)/gi;
  replacedPrompt = replacedPrompt.replace(existingIdPattern, '@$1');
  
  return replacedPrompt;
}

// 把「图N是…」的序号整体后移。首帧占了图1时，角色/场景/道具后缀要跟着挪。
function shiftFigureSuffix(suffix, delta) {
  if (!suffix || !delta) return suffix || '';
  return String(suffix).replace(/^图(\d+)/, function(_, n) {
    return '图' + (parseInt(n, 10) + delta);
  });
}

// 参考模式提交前，把提示词里点名的首尾帧排到参考图两端。
// 没被 @ 到的帧不加入列表，避免把已有「图N是角色」序号打乱。
// 返回新的 prompt / 参考图 / 后缀，不修改入参数组。
function placeShotFrameMentionImages(prompt, referenceImageUrls, promptSuffix, firstUrl, lastUrl, maxRefImages) {
  const text = prompt == null ? '' : String(prompt);
  const firstRe = /@首帧图(?![\u4e00-\u9fff])/g;
  const lastRe = /@尾帧图(?![\u4e00-\u9fff])/g;
  const wantsFirst = firstRe.test(text);
  firstRe.lastIndex = 0;
  const wantsLast = lastRe.test(text);
  lastRe.lastIndex = 0;
  const first = String(firstUrl || '').trim();
  const last = String(lastUrl || '').trim();
  const urlsIn = Array.isArray(referenceImageUrls) ? referenceImageUrls.slice() : [];
  const suffixIn = Array.isArray(promptSuffix) ? promptSuffix.slice() : [];
  if (suffixIn.length > urlsIn.length) suffixIn.length = urlsIn.length;
  while (suffixIn.length < urlsIn.length) suffixIn.push('');
  if (!wantsFirst && !wantsLast) {
    return { prompt: text, referenceImageUrls: urlsIn, promptSuffix: suffixIn, error: '' };
  }
  if (wantsFirst && !first) {
    return { prompt: text, referenceImageUrls: urlsIn, promptSuffix: suffixIn, error: 'missing_first' };
  }
  if (wantsLast && !last) {
    return { prompt: text, referenceImageUrls: urlsIn, promptSuffix: suffixIn, error: 'missing_last' };
  }
  const reserved = (wantsFirst ? 1 : 0) + (wantsLast ? 1 : 0);
  const max = Number(maxRefImages);
  if (max > 0 && reserved > max) {
    return { prompt: text, referenceImageUrls: urlsIn, promptSuffix: suffixIn, error: 'over_capacity' };
  }
  const middleBudget = max > 0 ? max - reserved : urlsIn.length;
  const refs = urlsIn.slice(0, middleBudget);
  const suffixes = suffixIn.slice(0, refs.length);
  const delta = wantsFirst ? 1 : 0;
  const urls = [];
  const notes = [];
  if (wantsFirst) urls.push(first);
  refs.forEach(function(url, i) {
    urls.push(url);
    const note = shiftFigureSuffix(suffixes[i], delta);
    if (note) notes.push(note);
  });
  if (wantsLast) urls.push(last);
  if (wantsFirst) notes.unshift('图1是首帧');
  if (wantsLast) notes.push('图' + urls.length + '是尾帧');
  let out = text.replace(firstRe, '图1');
  out = out.replace(lastRe, '图' + urls.length);
  return { prompt: out, referenceImageUrls: urls, promptSuffix: notes, error: '' };
}

// 参考模式不看 supports_last_frame。尾帧 URL 优先用节点上保存的，否则取尾帧连线。
function resolveMentionLastFrameUrl(node) {
  if (!node || !node.data) return '';
  const saved = String(node.data.lastFrameUrl || '').trim();
  if (saved) return saved;
  if (typeof state === 'undefined' || !state || !Array.isArray(state.lastFrameConnections)) return '';
  const conn = state.lastFrameConnections.find(function(c) { return c && c.to === node.id; });
  if (!conn || !Array.isArray(state.nodes)) return '';
  const fromNode = state.nodes.find(function(n) { return n && n.id === conn.from; });
  return String((fromNode && fromNode.data && fromNode.data.url) || '').trim();
}

function shotFrameMentionErrorMessage(code) {
  const fallback = {
    missing_first: '视频提示词使用了 @首帧图，请先设置视频首帧',
    missing_last: '视频提示词使用了 @尾帧图，请先设置视频尾帧',
    over_capacity: '当前模型的参考图数量不够同时放入首帧和尾帧'
  };
  const key = {
    missing_first: 'shot_frame_mention_missing_first',
    missing_last: 'shot_frame_mention_missing_last',
    over_capacity: 'shot_frame_mention_over_capacity'
  }[code];
  if (key && typeof window !== 'undefined' && window.t) {
    const translated = window.t(key);
    if (translated && translated !== key) return translated;
  }
  return fallback[code] || code;
}

function shotFrameMultiRefLimit(videoModel) {
  let maxRefImages = 5;
  if (typeof window !== 'undefined' && window.TaskConfig && typeof window.TaskConfig.isLoaded === 'function' && window.TaskConfig.isLoaded()) {
    const configs = window.TaskConfig.getModelConfigs() || {};
    const config = configs[videoModel];
    if (config && config.max_multi_ref_images) maxRefImages = config.max_multi_ref_images;
  }
  return maxRefImages;
}

// 混合模型固定 3 个图片槽。不能用下拉里 H3 参考模型的 9 张上限，否则提示词序号会对不上。
const H3_KEYFRAME_REF_MAX_IMAGES = 3;
const H3_KEYFRAME_REF_SHORT_KEY = 'minimax_h3_kfr';

function promptHasShotFrameMention(prompt) {
  const text = prompt == null ? '' : String(prompt);
  return /@首帧图(?![\u4e00-\u9fff])/.test(text) || /@尾帧图(?![\u4e00-\u9fff])/.test(text);
}

function promptHasFirstFrameToken(prompt) {
  return /@首帧图(?![\u4e00-\u9fff])/.test(prompt == null ? '' : String(prompt));
}

function promptHasLastFrameToken(prompt) {
  return /@尾帧图(?![\u4e00-\u9fff])/.test(prompt == null ? '' : String(prompt));
}

// 参考模式只读字段的固定句子。后面紧跟汉字，现有 @ 标记认不出它们。
const SHOT_FRAME_AUTO_FIRST = '@首帧图是首帧';
const SHOT_FRAME_AUTO_LAST = '@尾帧图是尾帧';

function buildShotFrameAutoPrompt(hasFirst, hasLast) {
  const parts = [];
  if (hasFirst) parts.push(SHOT_FRAME_AUTO_FIRST);
  if (hasLast) parts.push(SHOT_FRAME_AUTO_LAST);
  return parts.join('，');
}

// 只接受四种整句。更长的文本不算，避免误伤用户原文。
function shotFrameAutoPromptFlags(text) {
  const value = text == null ? '' : String(text);
  if (value === SHOT_FRAME_AUTO_FIRST + '，' + SHOT_FRAME_AUTO_LAST) {
    return { wantsFirst: true, wantsLast: true };
  }
  if (value === SHOT_FRAME_AUTO_FIRST) return { wantsFirst: true, wantsLast: false };
  if (value === SHOT_FRAME_AUTO_LAST) return { wantsFirst: false, wantsLast: true };
  return { wantsFirst: false, wantsLast: false };
}

// 提交副本补上不带汉字的标记。原文已有对应标记时不补第二次。不写回节点。
function ensureShotFrameMentionTokens(prompt, firstUrl, lastUrl) {
  let text = prompt == null ? '' : String(prompt);
  const first = String(firstUrl || '').trim();
  const last = String(lastUrl || '').trim();
  if (first && !promptHasFirstFrameToken(text)) {
    text = text.replace(/\s*$/, '');
    text = text ? (text + '\n@首帧图') : '@首帧图';
  }
  if (last && !promptHasLastFrameToken(text)) {
    text = text.replace(/\s*$/, '');
    text = text ? (text + '\n@尾帧图') : '@尾帧图';
  }
  return text;
}

function shotFrameHasAutoFirst(node) {
  if (!node || !node.data || node.data.firstFrameDismissed) return false;
  return String(node.data.previewImageUrl || '').trim() !== '';
}

// 当时确实有首帧图，才记住「不要自动填回」。没有图时点清除不能把开关记死。
function shouldRememberShotFrameFirstDismiss(imageUrl) {
  return String(imageUrl || '').trim() !== '';
}

function syncShotFrameAutoPrompt(node) {
  if (!node || !node.data) return '';
  const text = buildShotFrameAutoPrompt(
    shotFrameHasAutoFirst(node),
    resolveMentionLastFrameUrl(node) !== ''
  );
  node.data.frameAutoPrompt = text;
  return text;
}

function isH3ReferenceVideoModel(videoModel) {
  const key = String(videoModel || '');
  return key === 'minimax_h3_r2v' || key === 'minimax_h3_reference_to_video';
}

// 只有参考模式、当前是 H3 参考模型、并且提示词点名了首帧或尾帧，才改提交混合模型。
// 首帧模式、其他参考模型、以及没有 @ 标记的 H3 参考提交都不改。
function shouldUseH3KeyframeRefModel(videoMode, videoModel, prompt) {
  return videoMode === 'multi_reference'
    && isH3ReferenceVideoModel(videoModel)
    && promptHasShotFrameMention(prompt);
}

function resolveShotFrameReferenceSubmitModel(videoMode, videoModel, prompt) {
  if (shouldUseH3KeyframeRefModel(videoMode, videoModel, prompt)) return H3_KEYFRAME_REF_SHORT_KEY;
  return videoModel;
}

function shotFrameMentionImageLimit(videoMode, videoModel, prompt) {
  if (shouldUseH3KeyframeRefModel(videoMode, videoModel, prompt)) return H3_KEYFRAME_REF_MAX_IMAGES;
  return shotFrameMultiRefLimit(videoModel);
}

// 分镜节点生成视频功能
async function generateShotFrameVideo(nodeId, node){
  const mode = node.data.videoMode || 'first_last_frame';

  // 首帧模式需要分镜图，参考图模式不需要
  if(mode === 'first_last_frame' && !node.data.previewImageUrl){
    showToast('请先生成分镜图', 'warning');
    return;
  }

  const generateBtn = document.querySelector(`.node[data-node-id="${nodeId}"] .shot-frame-generate-video-btn`);
  const errorEl = document.querySelector(`.node[data-node-id="${nodeId}"] .shot-frame-video-error`);
  if(!generateBtn) return;

  // 清除之前的错误信息
  if(errorEl){
    errorEl.style.display = 'none';
    errorEl.textContent = '';
  }

  // 验证参考音频和视频的总时长（仅首帧模式，参考图模式下 ref audio/video 已隐藏）
  if(mode === 'first_last_frame' && (node.data.refAudioFile || node.data.refVideoFile)) {
    const validationForm = new FormData();
    if(node.data.refAudioFile) {
      validationForm.append('audio_files', node.data.refAudioFile);
    }
    if(node.data.refVideoFile) {
      validationForm.append('video_files', node.data.refVideoFile);
    }
    validationForm.append('max_duration_seconds', 15);

    try {
      const validationRes = await fetch('/api/media/validate-duration', {
        method: 'POST',
        body: validationForm
      });
      const validationData = await validationRes.json();
      if(!validationData.data.valid) {
        const errorMsg = validationData.data.message || '时长超过限制';
        showToast(errorMsg, 'error');
        if(errorEl){
          errorEl.textContent = errorMsg;
          errorEl.style.display = 'block';
        }
        return;
      }
    } catch(err) {
      console.error('媒体验证失败:', err);
      const errorMsg = '媒体验证失败，请检查上传的文件';
      showToast(errorMsg, 'error');
      if(errorEl){
        errorEl.textContent = errorMsg;
        errorEl.style.display = 'block';
      }
      return;
    }
  }

  try {
    generateBtn.disabled = true;
    generateBtn.textContent = '生成中...';
    // 新一轮生成开始，清除上次失败原因（避免生成成功后重载，过期错误与新视频同显；
    // 与 image_node.js / image_to_video_node.js 同约定）
    if(node) node.data.lastError = '';

    // 使用节点中用户编辑的视频提示词文本，而不是JSON格式
    let videoPrompt = node.data.videoPromptText || node.data.videoPrompt || '';
    const duration = node.data.videoDuration || 15;
    const count = node.data.videoDrawCount || 1;
    const videoModel = node.data.videoModel || (mode === 'multi_reference' ? 'veo3' : 'sora2');

    // 添加视频提示词后缀
    if(typeof getVideoPromptWithSuffix === 'function'){
      videoPrompt = getVideoPromptWithSuffix(videoPrompt);
    }

    showToast(`正在生成 ${count} 个视频...`, 'info');

    const userId = localStorage.getItem('user_id') || '1';
    const authToken = localStorage.getItem('auth_token') || '';

    // 共享资产库 @资产:{id} token 提交前还原为 markdown 图片（见
    // web/js/asset_library.js），使资产图片进入视频生成上下文
    if (window.AssetLibrary && videoPrompt.indexOf(window.AssetLibrary.MENTION_PREFIX) >= 0) {
      videoPrompt = await window.AssetLibrary.resolveMentionTokens(videoPrompt);
    }

    // === 构建公共字段 ===
    const form = new FormData();
    form.append('prompt', videoPrompt);
    form.append('ratio', state.ratio || '9:16');
    form.append('duration_seconds', duration);
    form.append('count', count);
    if(userId) form.append('user_id', userId);
    if(authToken) form.append('auth_token', authToken);
    if(typeof appendVideoResolutionToForm === 'function') {
      appendVideoResolutionToForm(form, videoModel, node.data.videoResolution);
    }
    // 是否处理人脸（仅 seedance2.0 商业版生效）
    if(node.data.processFace === true) {
      form.append('enable_face_mask', 'true');
    }

    let res;

    if(mode === 'multi_reference') {
      // === 参考图模式 ===
      // 收集角色/场景/道具参考图。角色只取生视频提示词：视频里没点名的角色
      // 不得带参考图与音色（图片提示词的角色属于画面构成，ai_tools 13137 事故）
      showToast('正在收集参考图...', 'info');
      let { referenceImageUrls, promptSuffix, voiceCharacters, characterRefUrls } = await collectShotFrameRefImages(node, { characterSource: 'video' });

      // 只读字段按当前首尾帧重算。用户的 videoPromptText 不动。
      if (typeof node.syncFrameAutoPrompt === 'function') {
        node.syncFrameAutoPrompt();
      } else {
        syncShotFrameAutoPrompt(node);
      }
      const autoFlags = shotFrameAutoPromptFlags(node.data.frameAutoPrompt);
      const mentionLastUrl = resolveMentionLastFrameUrl(node);
      const autoFirstUrl = autoFlags.wantsFirst ? String(node.data.previewImageUrl || '').trim() : '';
      const autoLastUrl = autoFlags.wantsLast ? mentionLastUrl : '';
      videoPrompt = ensureShotFrameMentionTokens(videoPrompt, autoFirstUrl, autoLastUrl);

      // 必须在改写前提取 @ 标记。改写后标记会变成「图N」，不能再用来判断要不要换模型。
      const useH3KeyframeRef = shouldUseH3KeyframeRefModel(mode, videoModel, videoPrompt);
      // @首帧图 / @尾帧图 排到参考图两端。存储的提示词不动，只改这次提交的文本。
      const placedMentions = placeShotFrameMentionImages(
        videoPrompt,
        referenceImageUrls,
        promptSuffix,
        node.data.previewImageUrl,
        mentionLastUrl,
        shotFrameMentionImageLimit(mode, videoModel, videoPrompt)
      );
      if(placedMentions.error) {
        const errorMsg = shotFrameMentionErrorMessage(placedMentions.error);
        showToast(errorMsg, 'warning');
        generateBtn.disabled = false;
        generateBtn.textContent = '生成视频';
        return;
      }
      videoPrompt = placedMentions.prompt;
      referenceImageUrls = placedMentions.referenceImageUrls;
      promptSuffix = placedMentions.promptSuffix;
      form.set('prompt', videoPrompt);

      // 将 promptSuffix 追加到视频提示词
      if(promptSuffix.length > 0) {
        videoPrompt = videoPrompt + '\n\n' + promptSuffix.join('，') + '。';
        form.set('prompt', videoPrompt);
      }

      // 参考模式下追加画风描述（首帧模式不添加，保持原状）
      if(state.style && state.style.name) {
        videoPrompt = videoPrompt + '\n\n视频风格：' + state.style.name;
        if(state.style.compositionPreference) {
          videoPrompt = videoPrompt + '\n构图倾向：' + state.style.compositionPreference;
        }
        form.set('prompt', videoPrompt);
      }

      if(referenceImageUrls.length > 0) {
        // 有参考图 → image_to_video + multi_reference。
        // H3 参考模型点名了首尾帧时，task_id 换成隐藏的混合模型，画面模式仍是参考模式。
        const submitModel = useH3KeyframeRef ? H3_KEYFRAME_REF_SHORT_KEY : videoModel;
        const taskId = TaskConfig.getTaskIdByKey(submitModel, 'image_to_video');
        if(!taskId) {
          if(useH3KeyframeRef) {
            throw new Error('未找到 MiniMax H3 首帧参考混合模型 minimax_h3_kfr 的任务配置');
          }
          throw new Error(`未找到视频模型 ${videoModel} 对应的图生视频任务配置`);
        }
        form.append('task_id', taskId);
        form.append('image_urls', referenceImageUrls.join(','));
        form.append('image_mode', 'multi_reference');

        // 人脸遮盖白名单：勾选「是否处理人脸」时只对角色参考图做遮盖，
        // 道具/场景参考图不参与（后端 create_with_pipeline_steps 按白名单建步骤）
        if(node.data.processFace === true && characterRefUrls && characterRefUrls.length > 0) {
          form.append('face_mask_reference_urls', characterRefUrls.join(','));
        }

        // 音色仍按用户选中的参考模型判断。混合模型不在下拉里，不能拿它查 supports_voice_input。
        if(typeof collectVoiceReferences === 'function'){
          const voiceRefs = collectVoiceReferences(videoModel, voiceCharacters || [], '');
          if(voiceRefs.enabled){
            form.append('audio_urls', voiceRefs.voiceUrls.join(','));
            form.set('prompt', appendVoiceReferencePrompt(videoPrompt, voiceRefs.promptNote));
            notifyVoiceReferences(voiceRefs.voiceUrls.length);
          }
        }

        // H3 系列：先追加角色音色指纹（voice_desc），音频说明在其上叠加（两块共存，防覆盖）
        if(typeof appendVoiceCastingIfH3 === 'function'){
          videoPrompt = appendVoiceCastingIfH3(videoModel, videoPrompt, voiceCharacters || []);
        }
        if(typeof collectVoiceReferences === 'function'){
          const voiceRefs = collectVoiceReferences(videoModel, voiceCharacters || [], '');
          if(voiceRefs.enabled){
            form.append('audio_urls', voiceRefs.voiceUrls.join(','));
            form.set('prompt', appendVoiceReferencePrompt(videoPrompt, voiceRefs.promptNote));
            notifyVoiceReferences(voiceRefs.voiceUrls.length);
          } else {
            form.set('prompt', videoPrompt);
          }
        }

        if(useH3KeyframeRef) {
          showToast(`本次使用 MiniMax H3 首帧参考混合模型，共 ${referenceImageUrls.length} 张参考图`, 'info');
        } else {
          showToast(`使用 ${referenceImageUrls.length} 张参考图生成视频...`, 'info');
        }
        res = await authPostForm('/api/ai-app-run-image', form);
      } else {
        // 无参考图 → 回退 text_to_video
        const t2vTaskId = TaskConfig.getTaskIdByKey(videoModel, 'text_to_video');
        if(!t2vTaskId) {
          throw new Error(`模型 ${videoModel} 不支持文生视频回退，请添加参考图（角色/场景/道具）或切换支持文生视频的模型`);
        }

        // 仅在 text_to_video 回退时启用角色标记替换
        const replacedPrompt = await replaceCharacterMarkers(videoPrompt);
        form.set('prompt', replacedPrompt);

        form.append('task_id', t2vTaskId);
        showToast('无参考图，回退为文生视频模式...', 'info');
        res = await authPostForm('/api/ai-app-run', form);
      }
    } else {
      // === 首帧模式（原有逻辑） ===
      const imageUrl = node.data.previewImageUrl;
      const taskId = TaskConfig.getTaskIdByKey(videoModel || 'wan22', 'image_to_video');
      if(!taskId) {
        throw new Error(`未找到视频模型 ${videoModel} 对应的任务配置`);
      }
      form.append('task_id', taskId);
      const lastFrameUrl = typeof resolveShotFrameLastFrameUrl === 'function' ? resolveShotFrameLastFrameUrl(node) : '';
      form.append('image_urls', lastFrameUrl ? (imageUrl + ',' + lastFrameUrl) : imageUrl);
      form.append('image_mode', 'first_last_frame');

      // 添加参考音频和视频文件
      if(node.data.refAudioFile) {
        form.append('audio_files', node.data.refAudioFile);
      }
      if(node.data.refVideoFile) {
        form.append('video_files', node.data.refVideoFile);
      }

      res = await authPostForm('/api/ai-app-run-image', form);
    }

    const data = await res.json();

    if(!data.project_ids || data.project_ids.length === 0){
      throw new Error(extractApiErrorMessage(data, res));
    }

    const projectIds = data.project_ids;
    node.data.projectIds = projectIds;
    showToast(`视频生成任务已提交，正在处理...`, 'info');

    // 立即创建对应数量的视频节点并绑定 project_id
    const createdVideoNodeIds = [];
    const videoCount = projectIds.length;
    
    // 使用源节点实际宽度计算偏移
    const sourceNodeEl = document.querySelector(`.node[data-node-id="${nodeId}"]`);
    const sourceWidth = sourceNodeEl ? sourceNodeEl.offsetWidth : 300;
    for(let i = 0; i < videoCount; i++){
      const offsetY = i * 280;
      const newVideoNodeId = createVideoNode({
        x: node.x + sourceWidth + 60,
        y: node.y + offsetY,
        checkCollision: true
      });
      
      const newVideoNode = state.nodes.find(n => n.id === newVideoNodeId);
      if(newVideoNode){
        newVideoNode.data.name = videoCount > 1 ? `分镜视频${i + 1}` : '分镜视频';
        newVideoNode.data.project_id = projectIds[i] || projectIds[0];
        newVideoNode.title = newVideoNode.data.name;
        // 视频节点显示「生成中」状态行（含查看状态时间轴按钮）
        if(window.AiToolTimeline) window.AiToolTimeline.markNodeGenerating(newVideoNodeId);
        
        // 更新节点标题显示
        const canvasEl = document.getElementById('canvas');
        const newNodeEl = canvasEl ? canvasEl.querySelector(`.node[data-node-id="${newVideoNodeId}"]`) : null;
        if(newNodeEl){
          const titleEl = newNodeEl.querySelector('.node-title');
          if(titleEl) titleEl.textContent = newVideoNode.title;
          
          const nameEl = newNodeEl.querySelector('.video-name');
          if(nameEl) nameEl.textContent = newVideoNode.data.name;
        }
        
        // 创建从分镜节点到视频节点的连接
        state.connections.push({
          id: state.nextConnId++,
          from: nodeId,
          to: newVideoNodeId
        });
        
        createdVideoNodeIds.push(newVideoNodeId);
        console.log(`[分镜视频] 创建视频节点 ${newVideoNodeId} 并绑定 project_id:`, newVideoNode.data.project_id);
      }
    }
    
    renderAllConnections();
    renderMinimap();

    // 轮询视频生成状态,更新视频URL
    pollVideoStatus(
      projectIds,
      (msg) => {
        generateBtn.textContent = msg;
      },
      (statusResult) => {
        console.log('Shot frame video generation status result:', statusResult);
        
        // 从 tasks 数组中提取结果
        let videoUrls = [];
        if(statusResult.tasks && Array.isArray(statusResult.tasks)){
          videoUrls = statusResult.tasks
            .filter(task => task.status === 'SUCCESS' && task.result)
            .map(task => normalizeVideoUrl(task.result))
            .filter(Boolean);
        } else {
          const rawResults = extractResultsArray(statusResult);
          videoUrls = Array.isArray(rawResults)
            ? rawResults.map(normalizeVideoUrl).filter(Boolean)
            : [];
        }
        
        console.log('Extracted video URLs:', videoUrls);
        
        if(videoUrls.length === 0){
          const errorMsg = '视频生成失败，未获取到结果';
          showToast(errorMsg, 'error');
          if(node) node.data.lastError = errorMsg;
          if(errorEl){
            errorEl.textContent = errorMsg;
            errorEl.style.display = 'block';
          }
          generateBtn.disabled = false;
          generateBtn.textContent = '生成视频';
          return;
        }

        // 更新已创建的视频节点的URL和预览
        videoUrls.forEach((videoUrl, index) => {
          if(index >= createdVideoNodeIds.length) return;
          
          const videoNodeId = createdVideoNodeIds[index];
          const videoNode = state.nodes.find(n => n.id === videoNodeId);
          
          if(videoNode){
            videoNode.data.url = videoUrl;
            
            // 更新节点显示
            const canvasEl = document.getElementById('canvas');
            const videoNodeEl = canvasEl ? canvasEl.querySelector(`.node[data-node-id="${videoNodeId}"]`) : null;
            if(videoNodeEl){
              const previewField = videoNodeEl.querySelector('.video-preview-field');
              const thumbVideo = videoNodeEl.querySelector('.video-thumb');
              if(previewField && thumbVideo){
                thumbVideo.src = proxyDownloadUrl(videoUrl);
                thumbVideo.muted = true;
                thumbVideo.loop = true;
                thumbVideo.controls = false;
                thumbVideo.preload = 'metadata';
                thumbVideo.playsInline = true;
                thumbVideo.onloadedmetadata = () => {
                  try{
                    if(isFinite(thumbVideo.duration) && thumbVideo.duration > 0){
                      thumbVideo.currentTime = Math.min(0.1, Math.max(0, thumbVideo.duration - 0.1));
                    }
                  } catch(e){}
                  try{
                    const p = thumbVideo.play();
                    if(p && typeof p.catch === 'function') p.catch(() => {});
                  } catch(e){}
                };
                try{ thumbVideo.load(); } catch(e){}
                previewField.style.display = 'block';
                const previewActionsField = videoNodeEl.querySelector('.video-preview-actions-field');
                if(previewActionsField) previewActionsField.style.display = 'block';
              }
              // 视频已到位：状态行标记成功
              if(window.AiToolTimeline) window.AiToolTimeline.settleNodeResult(videoNode);
            }
            
            console.log(`[分镜视频] 更新视频节点 ${videoNodeId} URL:`, videoUrl);
          }
        });
        
        // 重新渲染连接线
        renderAllConnections();
        
        generateBtn.disabled = false;
        generateBtn.textContent = '生成视频';
        showToast(`分镜视频生成成功！已创建 ${videoUrls.length} 个视频节点`, 'success');
        
        // 刷新用户算力显示
        if(typeof fetchComputingPower === 'function'){
          fetchComputingPower();
        }
        
        safeAutoSave()
      },
      (error) => {
        const displayError = (typeof truncateErrorMessage === 'function')
          ? truncateErrorMessage(error)
          : error;
        const errorMsg = `生成失败: ${displayError}`;
        showToast(errorMsg, 'error');
        if(node) node.data.lastError = String(displayError || error || '');
        if(errorEl){
          errorEl.textContent = errorMsg;
          errorEl.style.display = 'block';
        }
        generateBtn.disabled = false;
        generateBtn.textContent = '生成视频';
      }
    );
    
  } catch(error){
    console.error('生成分镜视频失败:', error);
    const raw = error.message || error;
    const displayError = (typeof truncateErrorMessage === 'function')
      ? truncateErrorMessage(raw)
      : raw;
    const errorMsg = `生成失败: ${displayError}`;
    showToast(errorMsg, 'error');
    if(node) node.data.lastError = String(displayError || raw || '');
    if(errorEl){
      errorEl.textContent = errorMsg;
      errorEl.style.display = 'block';
    }
    generateBtn.disabled = false;
    generateBtn.textContent = '生成视频';
  }
}

if (typeof window !== 'undefined') {
  window.placeShotFrameMentionImages = placeShotFrameMentionImages;
  window.shouldUseH3KeyframeRefModel = shouldUseH3KeyframeRefModel;
  window.promptHasShotFrameMention = promptHasShotFrameMention;
  window.buildShotFrameAutoPrompt = buildShotFrameAutoPrompt;
  window.shotFrameAutoPromptFlags = shotFrameAutoPromptFlags;
  window.ensureShotFrameMentionTokens = ensureShotFrameMentionTokens;
  window.syncShotFrameAutoPrompt = syncShotFrameAutoPrompt;
  window.shouldRememberShotFrameFirstDismiss = shouldRememberShotFrameFirstDismiss;
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    placeShotFrameMentionImages,
    shouldUseH3KeyframeRefModel,
    promptHasShotFrameMention,
    resolveShotFrameReferenceSubmitModel,
    shotFrameMentionImageLimit,
    buildShotFrameAutoPrompt,
    shotFrameAutoPromptFlags,
    ensureShotFrameMentionTokens,
    syncShotFrameAutoPrompt,
    shouldRememberShotFrameFirstDismiss
  };
}
