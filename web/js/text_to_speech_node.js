    function createTextToSpeechNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = opts && typeof opts.y === 'number' ? opts.y : viewportPos.y;
      const node = {
        id,
        type: 'text_to_speech',
        title: '文字转语音',
        x,
        y,
        data: {
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
        }
      };
      state.nodes.push(node);

      const el = document.createElement('div');
      el.className = 'node';
      el.dataset.nodeId = String(id);
      el.style.left = node.x + 'px';
      el.style.top = node.y + 'px';

      el.innerHTML = `
        <div class="port output" title="输出音频"></div>
        <div class="node-header">
          <div class="node-title">${node.title}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field">
            <div class="label">生成文本 <span style="color: red;">*</span></div>
            <textarea class="tts-text" rows="3" placeholder="输入要转换为语音的文本"></textarea>
          </div>
          <div class="field">
            <div class="label">参考音色音频（可选）</div>
            <input class="tts-ref-audio" type="file" accept="audio/*" />
            <div class="tts-ref-preview" style="display:none; margin-top:4px;">
              <audio class="tts-ref-audio-player" controls style="width:100%; max-height:32px;"></audio>
              <button class="mini-btn tts-ref-clear" type="button" style="margin-top:4px;">清除</button>
            </div>
          </div>
          <div class="field">
            <div class="label">情感控制方式</div>
            <select class="tts-emo-method">
              <option value="0">与参考音频相同</option>
              <option value="1">使用情感参考音频</option>
            </select>
          </div>
          <div class="field tts-emo-ref-field" style="display:none;">
            <div class="label">情感参考音频</div>
            <input class="tts-emo-ref-audio" type="file" accept="audio/*" />
            <div class="tts-emo-ref-preview" style="display:none; margin-top:4px;">
              <audio class="tts-emo-ref-audio-player" controls style="width:100%; max-height:32px;"></audio>
              <button class="mini-btn tts-emo-ref-clear" type="button" style="margin-top:4px;">清除</button>
            </div>
          </div>
          <div class="field tts-emo-weight-field" style="display:none;">
            <div class="label">情感权重 (<span class="tts-emo-weight-value">1.0</span>)</div>
            <input type="range" class="tts-emo-weight" min="0" max="1.6" step="0.1" value="1.0" style="width:100%;" />
            <div class="gen-meta" style="margin-top:4px;">调整情感的强度，0为无情感，1.6为最强情感</div>
          </div>
          <div class="field">
            <button class="gen-btn tts-generate-btn" type="button">生成语音</button>
            <div class="gen-meta tts-status" style="display:none;"></div>
          </div>
          <div class="field tts-result-field" style="display:none;">
            <div class="label">生成结果</div>
            <audio class="tts-result-audio" controls style="width:100%; margin-bottom:8px;"></audio>
            <div style="display:flex; gap:8px;">
              <button class="mini-btn tts-download-btn" type="button">下载音频</button>
            </div>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const outputPort = el.querySelector('.port.output');
      const textEl = el.querySelector('.tts-text');
      const refAudioEl = el.querySelector('.tts-ref-audio');
      const refPreviewEl = el.querySelector('.tts-ref-preview');
      const refAudioPlayer = el.querySelector('.tts-ref-audio-player');
      const refClearBtn = el.querySelector('.tts-ref-clear');
      const emoMethodEl = el.querySelector('.tts-emo-method');
      const emoRefField = el.querySelector('.tts-emo-ref-field');
      const emoRefAudioEl = el.querySelector('.tts-emo-ref-audio');
      const emoRefPreviewEl = el.querySelector('.tts-emo-ref-preview');
      const emoRefAudioPlayer = el.querySelector('.tts-emo-ref-audio-player');
      const emoRefClearBtn = el.querySelector('.tts-emo-ref-clear');
      const emoWeightField = el.querySelector('.tts-emo-weight-field');
      const emoWeightEl = el.querySelector('.tts-emo-weight');
      const emoWeightValueEl = el.querySelector('.tts-emo-weight-value');
      const generateBtn = el.querySelector('.tts-generate-btn');
      const statusEl = el.querySelector('.tts-status');
      const resultField = el.querySelector('.tts-result-field');
      const resultAudio = el.querySelector('.tts-result-audio');
      const downloadBtn = el.querySelector('.tts-download-btn');

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

      outputPort.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.connecting = { fromId: id, startX: e.clientX, startY: e.clientY };
      });

      textEl.addEventListener('input', () => {
        node.data.text = textEl.value;
      });

      refAudioEl.addEventListener('change', () => {
        const file = refAudioEl.files && refAudioEl.files[0];
        if(!file) return;
        
        node.data.refAudioFile = file;
        const localUrl = URL.createObjectURL(file);
        refAudioPlayer.src = localUrl;
        refPreviewEl.style.display = 'block';
      });

      refClearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        node.data.refAudioFile = null;
        refAudioPlayer.removeAttribute('src');
        refAudioPlayer.load();
        refPreviewEl.style.display = 'none';
        refAudioEl.value = '';
      });

      emoMethodEl.addEventListener('change', () => {
        node.data.emoControlMethod = parseInt(emoMethodEl.value);
        const showEmoRef = node.data.emoControlMethod === 1;
        emoRefField.style.display = showEmoRef ? 'block' : 'none';
        emoWeightField.style.display = showEmoRef ? 'block' : 'none';
      });

      emoRefAudioEl.addEventListener('change', () => {
        const file = emoRefAudioEl.files && emoRefAudioEl.files[0];
        if(!file) return;
        
        node.data.emoRefAudioFile = file;
        const localUrl = URL.createObjectURL(file);
        emoRefAudioPlayer.src = localUrl;
        emoRefPreviewEl.style.display = 'block';
      });

      emoRefClearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        node.data.emoRefAudioFile = null;
        emoRefAudioPlayer.removeAttribute('src');
        emoRefAudioPlayer.load();
        emoRefPreviewEl.style.display = 'none';
        emoRefAudioEl.value = '';
      });

      emoWeightEl.addEventListener('input', () => {
        node.data.emoWeight = parseFloat(emoWeightEl.value);
        emoWeightValueEl.textContent = node.data.emoWeight.toFixed(1);
      });

      generateBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        
        if(!node.data.text.trim()){
          showToast('请输入生成文本', 'warning');
          return;
        }
        
        const userId = getUserId();
        if(!userId){
          showToast('请先登录后再使用语音生成功能', 'error');
          return;
        }
        
        try {
          generateBtn.disabled = true;
          generateBtn.textContent = '生成中...';
          statusEl.style.display = 'block';
          statusEl.style.color = '';
          statusEl.textContent = '正在生成音频...';
          resultField.style.display = 'none';
          
          const form = new FormData();
          form.append('text', node.data.text);
          form.append('user_id', userId);
          form.append('emo_control_method', node.data.emoControlMethod);
          
          if(node.data.refAudioFile){
            form.append('ref_audio', node.data.refAudioFile);
          }
          
          if(node.data.emoControlMethod === 1){
            if(node.data.emoRefAudioFile){
              form.append('emo_ref_audio', node.data.emoRefAudioFile);
            }
            form.append('emo_weight', node.data.emoWeight);
          }
          
          const authToken = getAuthToken();
          if(authToken){
            form.append('auth_token', authToken);
          }
          
          const res = await fetch('/api/audio-generate', {
            method: 'POST',
            body: form
          });
          
          const result = await res.json();
          node.data.audioId = result.audio_id;
          node.data.status = result.status || 'submitted';
          
          if(node.data.audioId){
            pollAudioStatus(id, node);
          }
          
        } catch(error){
          console.error('语音生成失败:', error);
          statusEl.style.color = '#dc2626';
          statusEl.textContent = '生成失败: ' + (error.message || '未知错误');
          generateBtn.disabled = false;
          generateBtn.textContent = '生成语音';
          showToast('语音生成失败', 'error');
        }
      });

      async function pollAudioStatus(nodeId, node){
        const maxAttempts = 60;
        let attempts = 0;
        
        const checkStatus = async () => {
          if(attempts >= maxAttempts){
            statusEl.style.color = '#dc2626';
            statusEl.textContent = '生成超时';
            generateBtn.disabled = false;
            generateBtn.textContent = '生成语音';
            return;
          }
          
          attempts++;
          
          try {
            const authToken = getAuthToken();
            const params = authToken ? `?auth_token=${encodeURIComponent(authToken)}` : '';
            
            const res = await fetch(`/api/audio-status/${node.data.audioId}${params}`, {
              method: 'GET'
            });
            
            const contentType = (res.headers.get('content-type') || '').toLowerCase();
            const headerStatus = res.headers.get('x-audio-status');
            
            if(headerStatus === 'SUCCESS' || contentType.startsWith('audio/')){
              const blob = await res.blob();
              const blobUrl = URL.createObjectURL(blob);
              node.data.audioUrl = blobUrl;
              resultAudio.src = blobUrl;
              resultField.style.display = 'block';
              statusEl.style.color = '#16a34a';
              statusEl.textContent = '生成成功！';
              generateBtn.disabled = false;
              generateBtn.textContent = '生成语音';
              showToast('语音生成成功', 'success');
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
                node.data.audioUrl = payload.result_url;
                resultAudio.src = proxyDownloadUrl(payload.result_url);
                resultField.style.display = 'block';
              }
              statusEl.style.color = '#16a34a';
              statusEl.textContent = '生成成功！';
              generateBtn.disabled = false;
              generateBtn.textContent = '生成语音';
              showToast('语音生成成功', 'success');
            } else if(status === 'FAILED' || status === -1){
              statusEl.style.color = '#dc2626';
              statusEl.textContent = '生成失败: ' + (payload.reason || payload.message || '未知错误');
              generateBtn.disabled = false;
              generateBtn.textContent = '生成语音';
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

      downloadBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if(!node.data.audioUrl){
          showToast('没有可下载的音频', 'error');
          return;
        }
        
        const now = new Date();
        const dateStr = now.getFullYear().toString() + 
                       (now.getMonth() + 1).toString().padStart(2, '0') + 
                       now.getDate().toString().padStart(2, '0');
        const timeStr = now.getHours().toString().padStart(2, '0') + 
                       now.getMinutes().toString().padStart(2, '0');
        const filename = `audio_${dateStr}_${timeStr}.wav`;
        
        if(node.data.audioUrl.startsWith('blob:')){
          const link = document.createElement('a');
          link.href = node.data.audioUrl;
          link.download = filename;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
        } else {
          const downloadUrl = `/api/download?url=${encodeURIComponent(node.data.audioUrl)}&filename=${encodeURIComponent(filename)}`;
          window.open(downloadUrl, '_blank');
        }
        showToast('开始下载', 'success');
      });

      canvasEl.appendChild(el);
      setSelected(id);
      return id;
    }

    function createTextToSpeechNodeWithData(nodeData){
      const savedNextNodeId = state.nextNodeId;
      state.nextNodeId = nodeData.id;
      
      createTextToSpeechNode({ x: nodeData.x, y: nodeData.y });
      
      state.nextNodeId = Math.max(savedNextNodeId, nodeData.id + 1);
      
      const node = state.nodes.find(n => n.id === nodeData.id);
      if(!node) return;
      
      node.title = nodeData.title || '文字转语音';
      Object.assign(node.data, nodeData.data);
      
      const el = canvasEl.querySelector(`.node[data-node-id="${nodeData.id}"]`);
      if(!el) return;
      
      const textEl = el.querySelector('.tts-text');
      const refPreviewEl = el.querySelector('.tts-ref-preview');
      const refAudioPlayer = el.querySelector('.tts-ref-audio-player');
      const emoMethodEl = el.querySelector('.tts-emo-method');
      const emoRefField = el.querySelector('.tts-emo-ref-field');
      const emoRefPreviewEl = el.querySelector('.tts-emo-ref-preview');
      const emoRefAudioPlayer = el.querySelector('.tts-emo-ref-audio-player');
      const emoWeightField = el.querySelector('.tts-emo-weight-field');
      const emoWeightEl = el.querySelector('.tts-emo-weight');
      const emoWeightValueEl = el.querySelector('.tts-emo-weight-value');
      const statusEl = el.querySelector('.tts-status');
      const resultField = el.querySelector('.tts-result-field');
      const resultAudio = el.querySelector('.tts-result-audio');
      
      if(textEl && node.data.text){
        textEl.value = node.data.text;
      }
      
      if(emoMethodEl){
        emoMethodEl.value = node.data.emoControlMethod || 0;
        const showEmoRef = node.data.emoControlMethod === 1;
        if(emoRefField) emoRefField.style.display = showEmoRef ? 'block' : 'none';
        if(emoWeightField) emoWeightField.style.display = showEmoRef ? 'block' : 'none';
      }
      
      if(emoWeightEl && node.data.emoWeight !== undefined){
        emoWeightEl.value = node.data.emoWeight;
        if(emoWeightValueEl) emoWeightValueEl.textContent = node.data.emoWeight.toFixed(1);
      }
      
      if(node.data.audioUrl && resultAudio){
        resultAudio.src = node.data.audioUrl.startsWith('blob:') ? node.data.audioUrl : proxyDownloadUrl(node.data.audioUrl);
        if(resultField) resultField.style.display = 'block';
      }
      
      if(node.data.status && statusEl){
        statusEl.style.display = 'block';
        if(node.data.status === 'SUCCESS'){
          statusEl.style.color = '#16a34a';
          statusEl.textContent = '生成成功！';
        } else if(node.data.status === 'FAILED'){
          statusEl.style.color = '#dc2626';
          statusEl.textContent = '生成失败';
        }
      }
    }
