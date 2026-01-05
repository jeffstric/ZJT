    function createDialogueGroupNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = opts && typeof opts.y === 'number' ? opts.y : viewportPos.y;
      const dialogueData = opts && opts.dialogueData ? opts.dialogueData : [];
      
      const node = {
        id,
        type: 'dialogue_group',
        title: '对话组',
        x,
        y,
        data: {
          dialogues: dialogueData,
          audioResults: {},
          emoControlMethod: 0,
          emoVec: [0, 0, 0, 0, 0, 0, 0, 0],
          emoWeight: 1,
          emoRefAudioUrl: null
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';
      el.style.width = '400px';

      let dialogueItemsHtml = '';
      if(dialogueData && dialogueData.length > 0){
        dialogueData.forEach((dialogue, index) => {
          const characterName = dialogue.character_name || '未知角色';
          const text = dialogue.text || '';
          dialogueItemsHtml += `
            <div class="dialogue-item" data-index="${index}" style="margin-bottom: 12px; padding: 12px; background: #f9fafb; border-radius: 8px; border: 1px solid #e5e7eb;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="font-weight: 600; color: #374151;">${escapeHtml(characterName)}</div>
                <button class="mini-btn dialogue-generate-btn" data-index="${index}" type="button" style="font-size: 11px; padding: 4px 8px;">生成音频</button>
              </div>
              <div style="color: #6b7280; font-size: 13px; margin-bottom: 8px;">"${escapeHtml(text)}"</div>
              <div class="dialogue-status" data-index="${index}" style="display:none; font-size: 12px; color: #6b7280; margin-bottom: 8px;"></div>
              <div class="dialogue-result" data-index="${index}" style="display:none;">
                <audio controls style="width:100%; max-height:32px; margin-bottom: 6px;"></audio>
                <button class="mini-btn dialogue-download-btn" data-index="${index}" type="button" style="font-size: 11px; padding: 4px 8px;">下载</button>
              </div>
            </div>
          `;
        });
      } else {
        dialogueItemsHtml = '<div class="gen-meta" style="text-align:center; padding: 20px;">暂无对话数据</div>';
      }

      el.innerHTML = `
        <div class="port input" title="输入（连接分镜节点）"></div>
        <div class="port output" title="输出"></div>
        <div class="node-header">
          <div class="node-title">${node.title}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field" style="margin-bottom: 12px;">
            <label class="label" style="font-size: 12px; margin-bottom: 4px;">情感控制方式</label>
            <select class="dialogue-emo-control-select" style="width: 100%; padding: 6px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 12px; background: #ffffff; color: #111827;">
              <option value="0">与参考音频相同</option>
              <option value="1">使用情感参考音频</option>
              <option value="2">使用情感向量</option>
            </select>
          </div>
          
          <div class="dialogue-emo-ref-audio-field" style="display: none; margin-bottom: 12px;">
            <label class="label" style="font-size: 12px; margin-bottom: 4px;">情感参考音频</label>
            <input type="file" class="dialogue-emo-ref-audio-input" accept="audio/*" style="width: 100%; padding: 4px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 11px; background: #f9fafb;">
            <div class="dialogue-emo-ref-audio-preview" style="display: none; margin-top: 6px;">
              <audio controls style="width: 100%; max-height: 32px;"></audio>
            </div>
          </div>
          
          <div class="dialogue-emo-weight-field" style="display: none; margin-bottom: 12px;">
            <label class="label" style="font-size: 12px; margin-bottom: 4px;">情感权重: <span class="dialogue-emo-weight-value">1.0</span></label>
            <input type="range" class="dialogue-emo-weight-slider" min="0" max="1.6" step="0.1" value="1" style="width: 100%;">
            <div style="font-size: 11px; color: #6b7280; margin-top: 2px;">调整情感强度，0为无情感，1.6为最强情感</div>
          </div>
          
          <div class="dialogue-emo-vec-field" style="display: none; margin-bottom: 12px;">
            <label class="label" style="font-size: 12px; margin-bottom: 6px;">情感向量控制</label>
            <div class="dialogue-emo-vec-sliders" style="font-size: 11px;">
              ${['喜', '怒', '哀', '惧', '厌恶', '低落', '惊喜', '平静'].map((label, idx) => `
                <div style="margin-bottom: 8px;">
                  <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                    <span>${label}</span>
                    <span class="dialogue-emo-vec-value" data-index="${idx}">0.00</span>
                  </div>
                  <input type="range" class="dialogue-emo-vec-slider" data-index="${idx}" min="0" max="1.5" step="0.01" value="0" style="width: 100%;">
                </div>
              `).join('')}
            </div>
            <div style="font-size: 11px; margin-top: 4px;">
              总和: <span class="dialogue-emo-vec-sum" style="font-weight: bold;">0.00</span> / 1.5
              <span class="dialogue-emo-vec-warning" style="color: #dc2626; display: none; margin-left: 8px;">情感向量之和不能超过1.5</span>
            </div>
          </div>
          
          <div class="field">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <div class="label" style="margin: 0;">对话列表</div>
              <button class="mini-btn dialogue-generate-all-btn" type="button" style="font-size: 11px; padding: 4px 8px;">生成全部</button>
            </div>
            <div class="dialogue-items-container">
              ${dialogueItemsHtml}
            </div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const inputPort = el.querySelector('.port.input');
      const outputPort = el.querySelector('.port.output');
      const generateAllBtn = el.querySelector('.dialogue-generate-all-btn');
      
      const emoControlSelect = el.querySelector('.dialogue-emo-control-select');
      const emoRefAudioField = el.querySelector('.dialogue-emo-ref-audio-field');
      const emoRefAudioInput = el.querySelector('.dialogue-emo-ref-audio-input');
      const emoRefAudioPreview = el.querySelector('.dialogue-emo-ref-audio-preview');
      const emoWeightField = el.querySelector('.dialogue-emo-weight-field');
      const emoWeightSlider = el.querySelector('.dialogue-emo-weight-slider');
      const emoWeightValue = el.querySelector('.dialogue-emo-weight-value');
      const emoVecField = el.querySelector('.dialogue-emo-vec-field');
      const emoVecSliders = el.querySelectorAll('.dialogue-emo-vec-slider');
      const emoVecSum = el.querySelector('.dialogue-emo-vec-sum');
      const emoVecWarning = el.querySelector('.dialogue-emo-vec-warning');

      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });

      el.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        setSelected(id);
        bringNodeToFront(id);
      });

      headerEl.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        bringNodeToFront(id);
        initNodeDrag(id, e.clientX, e.clientY);
      });

      inputPort.addEventListener('mouseup', (e) => {
        if(state.connecting && state.connecting.fromId !== id){
          const fromNode = state.nodes.find(n => n.id === state.connecting.fromId);
          if(fromNode && fromNode.type === 'shot_frame'){
            const exists = state.connections.some(c => c.from === state.connecting.fromId && c.to === id);
            if(!exists){
              state.connections.push({
                id: state.nextConnId++,
                from: state.connecting.fromId,
                to: id
              });
              renderConnections();
              
              const shotJson = fromNode.data.shotJson;
              if(shotJson && shotJson.dialogue){
                node.data.dialogues = shotJson.dialogue;
                updateDialogueList();
              }
              
              try{ autoSaveWorkflow(); } catch(e){}
            }
          }
        }
        state.connecting = null;
      });

      outputPort.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
      });
      
      emoControlSelect.addEventListener('change', (e) => {
        e.stopPropagation();
        const method = parseInt(e.target.value);
        node.data.emoControlMethod = method;
        
        emoRefAudioField.style.display = method === 1 ? 'block' : 'none';
        emoWeightField.style.display = method === 1 ? 'block' : 'none';
        emoVecField.style.display = method === 2 ? 'block' : 'none';
        
        try{ autoSaveWorkflow(); } catch(e){}
      });
      
      emoRefAudioInput.addEventListener('change', async (e) => {
        e.stopPropagation();
        const file = e.target.files[0];
        if(!file) return;
        
        try {
          const uploadedUrl = await uploadFile(file);
          if(uploadedUrl){
            node.data.emoRefAudioUrl = uploadedUrl;
            const audio = emoRefAudioPreview.querySelector('audio');
            if(audio){
              audio.src = proxyDownloadUrl(uploadedUrl);
              emoRefAudioPreview.style.display = 'block';
            }
            showToast('情感参考音频上传成功', 'success');
            try{ autoSaveWorkflow(); } catch(e){}
          }
        } catch(error){
          console.error('情感参考音频上传失败:', error);
          showToast('情感参考音频上传失败', 'error');
        }
      });
      
      emoWeightSlider.addEventListener('input', (e) => {
        e.stopPropagation();
        const value = parseFloat(e.target.value);
        node.data.emoWeight = value;
        emoWeightValue.textContent = value.toFixed(1);
      });
      
      emoWeightSlider.addEventListener('change', (e) => {
        try{ autoSaveWorkflow(); } catch(e){}
      });
      
      function updateEmoVecSum(){
        const sum = node.data.emoVec.reduce((acc, val) => acc + val, 0);
        emoVecSum.textContent = sum.toFixed(2);
        if(sum > 1.5){
          emoVecSum.style.color = '#dc2626';
          emoVecWarning.style.display = 'inline';
        } else {
          emoVecSum.style.color = '#16a34a';
          emoVecWarning.style.display = 'none';
        }
      }
      
      emoVecSliders.forEach(slider => {
        slider.addEventListener('input', (e) => {
          e.stopPropagation();
          const index = parseInt(slider.dataset.index);
          const value = parseFloat(e.target.value);
          node.data.emoVec[index] = value;
          
          const valueSpan = el.querySelector(`.dialogue-emo-vec-value[data-index="${index}"]`);
          if(valueSpan) valueSpan.textContent = value.toFixed(2);
          
          updateEmoVecSum();
        });
        
        slider.addEventListener('change', (e) => {
          try{ autoSaveWorkflow(); } catch(e){}
        });
      });

      function updateDialogueList(){
        const container = el.querySelector('.dialogue-items-container');
        if(!container) return;
        
        if(!node.data.dialogues || node.data.dialogues.length === 0){
          container.innerHTML = '<div class="gen-meta" style="text-align:center; padding: 20px;">暂无对话数据</div>';
          return;
        }
        
        let html = '';
        node.data.dialogues.forEach((dialogue, index) => {
          const characterName = dialogue.character_name || '未知角色';
          const text = dialogue.text || '';
          const hasAudio = node.data.audioResults[index] && node.data.audioResults[index].audioUrl;
          
          html += `
            <div class="dialogue-item" data-index="${index}" style="margin-bottom: 12px; padding: 12px; background: #f9fafb; border-radius: 8px; border: 1px solid #e5e7eb;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="font-weight: 600; color: #374151;">${escapeHtml(characterName)}</div>
                <button class="mini-btn dialogue-generate-btn" data-index="${index}" type="button" style="font-size: 11px; padding: 4px 8px;">生成音频</button>
              </div>
              <div style="color: #6b7280; font-size: 13px; margin-bottom: 8px;">"${escapeHtml(text)}"</div>
              <div class="dialogue-status" data-index="${index}" style="display:none; font-size: 12px; color: #6b7280; margin-bottom: 8px;"></div>
              <div class="dialogue-result" data-index="${index}" style="display:${hasAudio ? 'block' : 'none'};">
                <audio controls style="width:100%; max-height:32px; margin-bottom: 6px;"></audio>
                <button class="mini-btn dialogue-download-btn" data-index="${index}" type="button" style="font-size: 11px; padding: 4px 8px;">下载</button>
              </div>
            </div>
          `;
        });
        
        container.innerHTML = html;
        attachDialogueItemEvents();
        
        node.data.dialogues.forEach((dialogue, index) => {
          if(node.data.audioResults[index] && node.data.audioResults[index].audioUrl){
            const resultDiv = container.querySelector(`.dialogue-result[data-index="${index}"]`);
            const audio = resultDiv ? resultDiv.querySelector('audio') : null;
            if(audio){
              const audioUrl = node.data.audioResults[index].audioUrl;
              audio.src = audioUrl.startsWith('blob:') ? audioUrl : proxyDownloadUrl(audioUrl);
            }
          }
        });
      }

      function attachDialogueItemEvents(){
        const generateBtns = el.querySelectorAll('.dialogue-generate-btn');
        generateBtns.forEach(btn => {
          btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            await generateDialogueAudio(index);
          });
        });
        
        const downloadBtns = el.querySelectorAll('.dialogue-download-btn');
        downloadBtns.forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            downloadDialogueAudio(index);
          });
        });
      }

      async function generateDialogueAudio(index){
        const dialogue = node.data.dialogues[index];
        if(!dialogue) return;
        
        const userId = getUserId();
        if(!userId){
          showToast('请先登录后再使用语音生成功能', 'error');
          return;
        }
        
        const statusEl = el.querySelector(`.dialogue-status[data-index="${index}"]`);
        const resultDiv = el.querySelector(`.dialogue-result[data-index="${index}"]`);
        const generateBtn = el.querySelector(`.dialogue-generate-btn[data-index="${index}"]`);
        
        if(!statusEl || !resultDiv || !generateBtn) return;
        
        try {
          generateBtn.disabled = true;
          generateBtn.textContent = '生成中...';
          statusEl.style.display = 'block';
          statusEl.style.color = '';
          statusEl.textContent = '正在生成音频...';
          resultDiv.style.display = 'none';
          
          const worldId = state.defaultWorldId;
          if(!worldId){
            throw new Error('请先选择世界');
          }
          
          const characterName = dialogue.character_name;
          console.log('当前对话角色名称:', characterName);
          
          const matchedCharacter = await fetchAndMatchCharacter(worldId, characterName);
          console.log('匹配到的角色:', matchedCharacter);
          
          const form = new FormData();
          form.append('text', dialogue.text);
          form.append('user_id', userId);
          form.append('emo_control_method', node.data.emoControlMethod || 0);
          
          if(matchedCharacter && matchedCharacter.default_voice){
            console.log('角色参考音频URL:', matchedCharacter.default_voice);
            const voiceUrl = proxyDownloadUrl(matchedCharacter.default_voice);
            console.log('代理后的音频URL:', voiceUrl);
            
            const voiceResponse = await fetch(voiceUrl);
            if(!voiceResponse.ok){
              throw new Error(`获取参考音频失败: ${voiceResponse.status} ${voiceResponse.statusText}`);
            }
            const voiceBlob = await voiceResponse.blob();
            console.log('参考音频Blob大小:', voiceBlob.size, '类型:', voiceBlob.type);
            
            form.append('ref_audio', voiceBlob, 'ref_audio.wav');
          } else {
            console.warn('未找到匹配的角色或角色没有配置参考音频');
          }
          
          if(node.data.emoControlMethod === 1 && node.data.emoRefAudioUrl){
            const emoAudioUrl = proxyDownloadUrl(node.data.emoRefAudioUrl);
            const emoAudioResponse = await fetch(emoAudioUrl);
            if(emoAudioResponse.ok){
              const emoAudioBlob = await emoAudioResponse.blob();
              form.append('emo_ref_audio', emoAudioBlob, 'emo_ref_audio.wav');
            }
            
            if(node.data.emoWeight !== null && node.data.emoWeight !== undefined){
              form.append('emo_weight', node.data.emoWeight);
            }
          }
          
          if(node.data.emoControlMethod === 2 && node.data.emoVec){
            const emoVecSum = node.data.emoVec.reduce((acc, val) => acc + val, 0);
            if(emoVecSum <= 1.5){
              form.append('emo_vec', node.data.emoVec.join(','));
            } else {
              throw new Error('情感向量之和不能超过1.5');
            }
          }
          
          const authToken = getAuthToken();
          if(authToken){
            form.append('auth_token', authToken);
          }
          
          console.log('发送音频生成请求...');
          const res = await fetch('/api/audio-generate', {
            method: 'POST',
            body: form
          });
          
          console.log('音频生成响应状态:', res.status);
          const result = await res.json();
          console.log('音频生成响应结果:', result);
          
          if(result.code !== 0 && result.code !== undefined){
            throw new Error(result.message || result.msg || '音频生成请求失败');
          }
          
          const audioId = result.audio_id;
          
          if(audioId){
            await pollDialogueAudioStatus(index, audioId, statusEl, resultDiv, generateBtn);
          }
          
        } catch(error){
          console.error('语音生成失败:', error);
          statusEl.style.color = '#dc2626';
          statusEl.textContent = '生成失败: ' + (error.message || '未知错误');
          generateBtn.disabled = false;
          generateBtn.textContent = '生成音频';
          showToast('语音生成失败: ' + error.message, 'error');
        }
      }

      async function pollDialogueAudioStatus(index, audioId, statusEl, resultDiv, generateBtn){
        const maxAttempts = 60;
        let attempts = 0;
        
        const checkStatus = async () => {
          if(attempts >= maxAttempts){
            statusEl.style.color = '#dc2626';
            statusEl.textContent = '生成超时';
            generateBtn.disabled = false;
            generateBtn.textContent = '生成音频';
            return;
          }
          
          attempts++;
          
          try {
            const authToken = getAuthToken();
            const params = authToken ? `?auth_token=${encodeURIComponent(authToken)}` : '';
            
            const res = await fetch(`/api/audio-status/${audioId}${params}`, {
              method: 'GET'
            });
            
            const contentType = (res.headers.get('content-type') || '').toLowerCase();
            const headerStatus = res.headers.get('x-audio-status');
            
            if(headerStatus === 'SUCCESS' || contentType.startsWith('audio/')){
              const blob = await res.blob();
              const blobUrl = URL.createObjectURL(blob);
              
              const audio = resultDiv.querySelector('audio');
              if(audio) audio.src = blobUrl;
              resultDiv.style.display = 'block';
              
              statusEl.style.color = '#16a34a';
              statusEl.textContent = '正在上传音频...';
              
              try {
                const dialogue = node.data.dialogues[index];
                const characterName = dialogue.character_name || '角色';
                const now = new Date();
                const dateStr = now.getFullYear().toString() + 
                               (now.getMonth() + 1).toString().padStart(2, '0') + 
                               now.getDate().toString().padStart(2, '0');
                const timeStr = now.getHours().toString().padStart(2, '0') + 
                               now.getMinutes().toString().padStart(2, '0') + 
                               now.getSeconds().toString().padStart(2, '0');
                const filename = `${characterName}_${dateStr}_${timeStr}.wav`;
                
                const audioFile = new File([blob], filename, { type: blob.type || 'audio/wav' });
                const permanentUrl = await uploadFile(audioFile);
                
                if(permanentUrl){
                  if(!node.data.audioResults) node.data.audioResults = {};
                  node.data.audioResults[index] = { audioUrl: permanentUrl };
                  
                  if(audio) audio.src = proxyDownloadUrl(permanentUrl);
                  
                  statusEl.textContent = '生成成功！';
                  showToast('语音生成并上传成功', 'success');
                  
                  try{ autoSaveWorkflow(); } catch(e){}
                } else {
                  if(!node.data.audioResults) node.data.audioResults = {};
                  node.data.audioResults[index] = { audioUrl: blobUrl };
                  statusEl.textContent = '生成成功（上传失败，使用临时URL）';
                  showToast('语音生成成功，但上传失败', 'warning');
                }
              } catch(uploadError){
                console.error('音频上传失败:', uploadError);
                if(!node.data.audioResults) node.data.audioResults = {};
                node.data.audioResults[index] = { audioUrl: blobUrl };
                statusEl.textContent = '生成成功（上传失败，使用临时URL）';
                showToast('语音生成成功，但上传失败', 'warning');
              }
              
              generateBtn.disabled = false;
              generateBtn.textContent = '生成音频';
              return;
            }
            
            const text = await res.text();
            const payload = text ? JSON.parse(text) : null;
            
            if(!payload){
              setTimeout(checkStatus, 10000);
              return;
            }
            
            const status = typeof payload.status === 'string' ? payload.status.toUpperCase() : payload.status;
            
            if(status === 'SUCCESS' || status === 2){
              if(payload.result_url){
                statusEl.textContent = '正在上传音频...';
                
                try {
                  const audioUrl = proxyDownloadUrl(payload.result_url);
                  const audioResponse = await fetch(audioUrl);
                  if(!audioResponse.ok){
                    throw new Error('获取音频失败');
                  }
                  const audioBlob = await audioResponse.blob();
                  
                  const dialogue = node.data.dialogues[index];
                  const characterName = dialogue.character_name || '角色';
                  const now = new Date();
                  const dateStr = now.getFullYear().toString() + 
                                 (now.getMonth() + 1).toString().padStart(2, '0') + 
                                 now.getDate().toString().padStart(2, '0');
                  const timeStr = now.getHours().toString().padStart(2, '0') + 
                                 now.getMinutes().toString().padStart(2, '0') + 
                                 now.getSeconds().toString().padStart(2, '0');
                  const filename = `${characterName}_${dateStr}_${timeStr}.wav`;
                  
                  const audioFile = new File([audioBlob], filename, { type: audioBlob.type || 'audio/wav' });
                  const permanentUrl = await uploadFile(audioFile);
                  
                  if(permanentUrl){
                    if(!node.data.audioResults) node.data.audioResults = {};
                    node.data.audioResults[index] = { audioUrl: permanentUrl };
                    
                    const audio = resultDiv.querySelector('audio');
                    if(audio) audio.src = proxyDownloadUrl(permanentUrl);
                    resultDiv.style.display = 'block';
                    
                    statusEl.textContent = '生成成功！';
                    showToast('语音生成并上传成功', 'success');
                    
                    try{ autoSaveWorkflow(); } catch(e){}
                  } else {
                    if(!node.data.audioResults) node.data.audioResults = {};
                    node.data.audioResults[index] = { audioUrl: payload.result_url };
                    
                    const audio = resultDiv.querySelector('audio');
                    if(audio) audio.src = proxyDownloadUrl(payload.result_url);
                    resultDiv.style.display = 'block';
                    
                    statusEl.textContent = '生成成功（上传失败，使用临时URL）';
                    showToast('语音生成成功，但上传失败', 'warning');
                  }
                } catch(uploadError){
                  console.error('音频上传失败:', uploadError);
                  if(!node.data.audioResults) node.data.audioResults = {};
                  node.data.audioResults[index] = { audioUrl: payload.result_url };
                  
                  const audio = resultDiv.querySelector('audio');
                  if(audio) audio.src = proxyDownloadUrl(payload.result_url);
                  resultDiv.style.display = 'block';
                  
                  statusEl.textContent = '生成成功（上传失败，使用临时URL）';
                  showToast('语音生成成功，但上传失败', 'warning');
                }
              }
              statusEl.style.color = '#16a34a';
              generateBtn.disabled = false;
              generateBtn.textContent = '生成音频';
            } else if(status === 'FAILED' || status === -1){
              statusEl.style.color = '#dc2626';
              statusEl.textContent = '生成失败: ' + (payload.reason || payload.message || '未知错误');
              generateBtn.disabled = false;
              generateBtn.textContent = '生成音频';
              showToast('语音生成失败', 'error');
            } else {
              setTimeout(checkStatus, 10000);
            }
          } catch(error){
            console.error('状态检查失败:', error);
            setTimeout(checkStatus, 10000);
          }
        };
        
        checkStatus();
      }

      function downloadDialogueAudio(index){
        if(!node.data.audioResults || !node.data.audioResults[index]){
          showToast('没有可下载的音频', 'error');
          return;
        }
        
        const audioUrl = node.data.audioResults[index].audioUrl;
        const dialogue = node.data.dialogues[index];
        const characterName = dialogue.character_name || '角色';
        
        const now = new Date();
        const dateStr = now.getFullYear().toString() + 
                       (now.getMonth() + 1).toString().padStart(2, '0') + 
                       now.getDate().toString().padStart(2, '0');
        const timeStr = now.getHours().toString().padStart(2, '0') + 
                       now.getMinutes().toString().padStart(2, '0');
        const filename = `${characterName}_${dateStr}_${timeStr}.wav`;
        
        if(audioUrl.startsWith('blob:')){
          const link = document.createElement('a');
          link.href = audioUrl;
          link.download = filename;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
        } else {
          const downloadUrl = `/api/download?url=${encodeURIComponent(audioUrl)}&filename=${encodeURIComponent(filename)}`;
          window.open(downloadUrl, '_blank');
        }
        showToast('开始下载', 'success');
      }

      async function fetchAndMatchCharacter(worldId, characterName){
        if(!worldId || !characterName) return null;
        
        try {
          const cleanName = characterName.replace(/【/g, '').replace(/】/g, '');
          console.log('清理后的角色名称:', cleanName);
          
          const authToken = getAuthToken();
          const userId = getUserId();
          const response = await fetch(`/api/characters?world_id=${worldId}&page=1&page_size=100&keyword=${encodeURIComponent(cleanName)}`, {
            headers: {
              'Authorization': authToken || '',
              'X-User-Id': userId || ''
            }
          });
          
          if(!response.ok){
            console.error('角色查询请求失败:', response.status);
            return null;
          }
          
          const result = await response.json();
          console.log(`角色"${cleanName}"查询结果:`, result);
          
          if(result.code === 0 && result.data && Array.isArray(result.data.data)){
            const characters = result.data.data;
            console.log(`找到${characters.length}个匹配角色:`, characters.map(c => c.name));
            
            if(characters.length > 0){
              const matchedChar = characters.find(c => c.name === cleanName) || characters[0];
              console.log('最终匹配角色:', matchedChar.name, 'default_voice:', matchedChar.default_voice);
              return matchedChar;
            }
          }
          
          return null;
        } catch(error){
          console.error('获取角色信息失败:', error);
          return null;
        }
      }

      generateAllBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        
        if(!node.data.dialogues || node.data.dialogues.length === 0){
          showToast('暂无对话数据', 'warning');
          return;
        }
        
        generateAllBtn.disabled = true;
        generateAllBtn.textContent = '生成中...';
        
        for(let i = 0; i < node.data.dialogues.length; i++){
          await generateDialogueAudio(i);
          await new Promise(resolve => setTimeout(resolve, 1000));
        }
        
        generateAllBtn.disabled = false;
        generateAllBtn.textContent = '生成全部';
        showToast('全部对话音频生成完成', 'success');
      });

      attachDialogueItemEvents();
      canvasEl.appendChild(el);
      setSelected(id);
      return id;
    }

    function createDialogueGroupNodeWithData(nodeData){
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;
      
      createDialogueGroupNode({ 
        x: nodeData.x, 
        y: nodeData.y,
        dialogueData: nodeData.data.dialogues || []
      });
      
      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);
      
      const node = state.nodes.find(n => n.id === nodeData.id);
      if(!node) return;
      
      node.title = nodeData.title || '对话组';
      Object.assign(node.data, nodeData.data);
      
      const el = canvasEl.querySelector(`.node[data-node-id="${nodeData.id}"]`);
      if(!el) return;
      
      const emoControlSelect = el.querySelector('.dialogue-emo-control-select');
      const emoRefAudioField = el.querySelector('.dialogue-emo-ref-audio-field');
      const emoRefAudioPreview = el.querySelector('.dialogue-emo-ref-audio-preview');
      const emoWeightField = el.querySelector('.dialogue-emo-weight-field');
      const emoWeightSlider = el.querySelector('.dialogue-emo-weight-slider');
      const emoWeightValue = el.querySelector('.dialogue-emo-weight-value');
      const emoVecField = el.querySelector('.dialogue-emo-vec-field');
      const emoVecSliders = el.querySelectorAll('.dialogue-emo-vec-slider');
      
      if(emoControlSelect && node.data.emoControlMethod !== undefined){
        emoControlSelect.value = node.data.emoControlMethod;
        
        if(emoRefAudioField) emoRefAudioField.style.display = node.data.emoControlMethod === 1 ? 'block' : 'none';
        if(emoWeightField) emoWeightField.style.display = node.data.emoControlMethod === 1 ? 'block' : 'none';
        if(emoVecField) emoVecField.style.display = node.data.emoControlMethod === 2 ? 'block' : 'none';
      }
      
      if(node.data.emoRefAudioUrl && emoRefAudioPreview){
        const audio = emoRefAudioPreview.querySelector('audio');
        if(audio){
          audio.src = proxyDownloadUrl(node.data.emoRefAudioUrl);
          emoRefAudioPreview.style.display = 'block';
        }
      }
      
      if(node.data.emoWeight !== undefined && emoWeightSlider && emoWeightValue){
        emoWeightSlider.value = node.data.emoWeight;
        emoWeightValue.textContent = node.data.emoWeight.toFixed(1);
      }
      
      if(node.data.emoVec && emoVecSliders){
        emoVecSliders.forEach((slider, idx) => {
          if(node.data.emoVec[idx] !== undefined){
            slider.value = node.data.emoVec[idx];
            const valueSpan = el.querySelector(`.dialogue-emo-vec-value[data-index="${idx}"]`);
            if(valueSpan) valueSpan.textContent = node.data.emoVec[idx].toFixed(2);
          }
        });
        
        const sum = node.data.emoVec.reduce((acc, val) => acc + val, 0);
        const emoVecSum = el.querySelector('.dialogue-emo-vec-sum');
        const emoVecWarning = el.querySelector('.dialogue-emo-vec-warning');
        if(emoVecSum){
          emoVecSum.textContent = sum.toFixed(2);
          if(sum > 1.5){
            emoVecSum.style.color = '#dc2626';
            if(emoVecWarning) emoVecWarning.style.display = 'inline';
          } else {
            emoVecSum.style.color = '#16a34a';
            if(emoVecWarning) emoVecWarning.style.display = 'none';
          }
        }
      }
      
      if(node.data.audioResults){
        Object.keys(node.data.audioResults).forEach(index => {
          const result = node.data.audioResults[index];
          if(result.audioUrl){
            const resultDiv = el.querySelector(`.dialogue-result[data-index="${index}"]`);
            const audio = resultDiv ? resultDiv.querySelector('audio') : null;
            if(audio && resultDiv){
              audio.src = result.audioUrl.startsWith('blob:') ? result.audioUrl : proxyDownloadUrl(result.audioUrl);
              resultDiv.style.display = 'block';
            }
          }
        });
      }
    }
