    function escapeHtml(value){
      if(value === null || value === undefined) return '';
      return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    function createDialogueGroupNode(opts){
      const id = state.nextNodeId++;
      const viewportPos = getViewportNodePosition();
      const x = opts && typeof opts.x === 'number' ? opts.x : viewportPos.x;
      const y = opts && typeof opts.y === 'number' ? opts.y : viewportPos.y;
      const dialogueData = opts && opts.dialogueData ? opts.dialogueData : [];
      const shotNumber = opts && opts.shotNumber ? opts.shotNumber : null;
      
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
          emoRefAudioUrl: null,
          shotNumber: shotNumber,
          referenceAudios: []
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
                <button class="mini-btn dialogue-download-btn" data-index="${index}" type="button" style="font-size: 11px; padding: 4px 8px; display: none;">下载</button>
              </div>
            </div>
          `;
        });
      } else {
        dialogueItemsHtml = '<div class="gen-meta" style="text-align:center; padding: 20px;">暂无对话数据</div>';
      }

      el.innerHTML = `
        <div class="port input" title="输入（连接分镜节点）"></div>
        <div class="port video-input-port" title="视频输入（连接视频节点作为情感参考）"></div>
        <div class="port output" title="输出"></div>
        <div class="node-header">
          <div class="node-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><path d="M8 12H8.01M12 12H12.01M16 12H16.01" stroke-linecap="round"/><path d="M3 7C3 5.89543 3.89543 5 5 5H19C20.1046 5 21 5.89543 21 7V15C21 16.1046 20.1046 17 19 17H13L9 21V17H5C3.89543 17 3 16.1046 3 15V7Z"/></svg>${node.title}</div>
          <button class="icon-btn" title="删除">×</button>
        </div>
        <div class="node-body">
          <div class="field field-always-visible">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <div class="label" style="margin: 0;">对话列表</div>
            </div>
            <div class="dialogue-items-container">
              ${dialogueItemsHtml}
            </div>
          </div>
          
          <div class="field field-collapsible" style="margin-bottom: 12px;">
            <label class="label" style="font-size: 12px; margin-bottom: 4px;">情感控制方式</label>
            <select class="dialogue-emo-control-select" style="width: 100%; padding: 6px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 12px; background: #ffffff; color: #111827;">
              <option value="0">与参考音频相同</option>
              <option value="1">使用情感参考音频</option>
              <option value="2">使用情感向量</option>
            </select>
          </div>
          
          <div class="dialogue-emo-ref-audio-field field-collapsible" style="margin-bottom: 12px;">
            <label class="label" style="font-size: 12px; margin-bottom: 4px;">情感参考音频</label>
            <input type="file" class="dialogue-emo-ref-audio-input" accept="audio/*" style="width: 100%; padding: 4px; border: 1px solid #d1d5db; border-radius: 6px; font-size: 11px; background: #f9fafb;">
            <div class="dialogue-emo-ref-audio-preview" style="display: none; margin-top: 6px;">
              <audio controls style="width: 100%; max-height: 32px; margin-bottom: 4px;"></audio>
              <button class="mini-btn dialogue-emo-ref-audio-clear-btn" type="button" style="font-size: 11px; padding: 4px 8px;">清除音频</button>
            </div>
          </div>
          
          <div class="dialogue-emo-weight-field field-collapsible" style="display: none; margin-bottom: 12px;">
            <label class="label" style="font-size: 12px; margin-bottom: 4px;">情感权重: <span class="dialogue-emo-weight-value">1.0</span></label>
            <input type="range" class="dialogue-emo-weight-slider" min="0" max="1.6" step="0.1" value="1" style="width: 100%;">
            <div style="font-size: 11px; color: #6b7280; margin-top: 2px;">调整情感强度，0为无情感，1.6为最强情感</div>
          </div>
          
          <div class="dialogue-emo-vec-field field-collapsible" style="display: none; margin-bottom: 12px;">
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
          
          <div class="field field-collapsible" style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <label class="label" style="font-size: 12px; margin: 0;">参考音频</label>
              <button class="mini-btn dialogue-add-ref-audio-btn" type="button" style="font-size: 11px; padding: 4px 8px;">添加音频</button>
            </div>
            <div style="font-size: 11px; color: #6b7280; margin-bottom: 8px;">
              最多6个音频，每个不超过20秒、10MB
            </div>
            <div class="dialogue-ref-audios-list"></div>
          </div>
          
          <div class="field field-collapsible">
            <button class="mini-btn dialogue-generate-all-btn" type="button" style="font-size: 11px; padding: 4px 8px; width: 100%;">生成全部</button>
          </div>
        </div>
      `;

      const headerEl = el.querySelector('.node-header');
      const deleteBtn = el.querySelector('.icon-btn');
      const inputPort = el.querySelector('.port.input');
      const videoInputPort = el.querySelector('.port.video-input-port');
      const outputPort = el.querySelector('.port.output');
      const generateAllBtn = el.querySelector('.dialogue-generate-all-btn');
      
      const emoControlSelect = el.querySelector('.dialogue-emo-control-select');
      const emoRefAudioField = el.querySelector('.dialogue-emo-ref-audio-field');
      const emoRefAudioInput = el.querySelector('.dialogue-emo-ref-audio-input');
      const emoRefAudioPreview = el.querySelector('.dialogue-emo-ref-audio-preview');
      const emoRefAudioClearBtn = el.querySelector('.dialogue-emo-ref-audio-clear-btn');
      const emoWeightField = el.querySelector('.dialogue-emo-weight-field');
      const emoWeightSlider = el.querySelector('.dialogue-emo-weight-slider');
      const emoWeightValue = el.querySelector('.dialogue-emo-weight-value');
      const emoVecField = el.querySelector('.dialogue-emo-vec-field');
      const emoVecSliders = el.querySelectorAll('.dialogue-emo-vec-slider');
      const emoVecSum = el.querySelector('.dialogue-emo-vec-sum');
      const emoVecWarning = el.querySelector('.dialogue-emo-vec-warning');
      const addRefAudioBtn = el.querySelector('.dialogue-add-ref-audio-btn');
      const refAudiosList = el.querySelector('.dialogue-ref-audios-list');

      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeNode(id);
      });

      el.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        setSelected(id);
        bringNodeToFront(id);
        updateButtonsVisibility(true);
      });

      headerEl.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        if(!state.selectedNodeIds.includes(id)){
          setSelected(id);
        }
        bringNodeToFront(id);
        updateButtonsVisibility(true);
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
                // 使用深拷贝避免引用共享，防止修改对话组数据时影响分镜节点
                node.data.dialogues = JSON.parse(JSON.stringify(shotJson.dialogue));
                updateDialogueList();
              }
              
              try{ autoSaveWorkflow(); } catch(e){}
            }
          }
        }
        state.connecting = null;
      });

      videoInputPort.addEventListener('mouseup', (e) => {
        // 不要在这里清空 state.connecting，让 events.js 中的全局 mouseup 处理器来处理
        // state.connecting 会在 events.js 的 mouseup 事件中被清空
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
        
        // 情感参考音频区域始终显示，但在非情感参考音频模式下禁用
        const isEmoRefMode = method === 1;
        emoRefAudioField.style.opacity = isEmoRefMode ? '1' : '0.5';
        emoRefAudioField.style.pointerEvents = isEmoRefMode ? 'auto' : 'none';
        emoRefAudioInput.disabled = !isEmoRefMode;
        if(emoRefAudioClearBtn) emoRefAudioClearBtn.disabled = !isEmoRefMode;
        
        emoWeightField.style.display = method === 1 ? 'block' : 'none';
        emoVecField.style.display = method === 2 ? 'block' : 'none';
        
        // 视频输入端口始终显示，但在非情感参考音频模式下禁用
        if(videoInputPort){
          if(isEmoRefMode){
            videoInputPort.classList.remove('disabled');
          } else {
            videoInputPort.classList.add('disabled');
          }
        }
        
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
      
      emoRefAudioClearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        node.data.emoRefAudioUrl = null;
        emoRefAudioInput.value = '';
        emoRefAudioPreview.style.display = 'none';
        const audio = emoRefAudioPreview.querySelector('audio');
        if(audio){
          audio.src = '';
        }
        showToast('已清除情感参考音频', 'success');
        try{ autoSaveWorkflow(); } catch(e){}
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

      // 验证音频文件
      async function validateAudioFile(file){
        const maxSize = 10 * 1024 * 1024;
        const maxDuration = 20;
        
        if(file.size > maxSize){
          showToast('音频文件不能超过10MB', 'error');
          return false;
        }
        
        return new Promise((resolve) => {
          const audio = new Audio();
          const url = URL.createObjectURL(file);
          
          audio.addEventListener('loadedmetadata', () => {
            URL.revokeObjectURL(url);
            if(audio.duration > maxDuration){
              showToast(`音频时长不能超过${maxDuration}秒，当前时长：${audio.duration.toFixed(1)}秒`, 'error');
              resolve(false);
            } else {
              resolve(true);
            }
          });
          
          audio.addEventListener('error', () => {
            URL.revokeObjectURL(url);
            showToast('无法读取音频文件', 'error');
            resolve(false);
          });
          
          audio.src = url;
        });
      }

      // 渲染参考音频列表
      function renderRefAudiosList(){
        if(!node.data.referenceAudios){
          node.data.referenceAudios = [];
        }
        
        if(node.data.referenceAudios.length === 0){
          refAudiosList.innerHTML = '<div style="text-align: center; color: #9ca3af; padding: 12px; font-size: 12px;">暂无参考音频</div>';
          return;
        }
        
        let html = '';
        node.data.referenceAudios.forEach((item, index) => {
          html += `
            <div class="ref-audio-item" data-index="${index}" style="margin-bottom: 8px; padding: 8px; background: #f9fafb; border-radius: 6px; border: 1px solid #e5e7eb;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <div style="font-size: 12px; font-weight: 600; color: #374151;">${escapeHtml(item.characterName || '未命名角色')}</div>
                <button class="mini-btn ref-audio-delete-btn" data-index="${index}" type="button" style="font-size: 10px; padding: 2px 6px; background: #ef4444; color: white;">删除</button>
              </div>
              <audio controls style="width: 100%; max-height: 28px;" src="${item.url.startsWith('blob:') ? item.url : proxyDownloadUrl(item.url)}"></audio>
            </div>
          `;
        });
        
        refAudiosList.innerHTML = html;
        
        const deleteBtns = refAudiosList.querySelectorAll('.ref-audio-delete-btn');
        deleteBtns.forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            node.data.referenceAudios.splice(index, 1);
            renderRefAudiosList();
            showToast('已删除参考音频', 'success');
            try{ autoSaveWorkflow(); } catch(e){}
          });
        });
      }

      // 添加参考音频按钮事件
      addRefAudioBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        
        if(!node.data.referenceAudios){
          node.data.referenceAudios = [];
        }
        
        if(node.data.referenceAudios.length >= 6){
          showToast('最多只能添加6个参考音频', 'warning');
          return;
        }
        
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = 'audio/*';
        
        input.addEventListener('change', async (e) => {
          const file = e.target.files[0];
          if(!file) return;
          
          const isValid = await validateAudioFile(file);
          if(!isValid) return;
          
          const characterName = prompt('请输入该音频对应的角色名称：');
          if(!characterName || !characterName.trim()){
            showToast('角色名称不能为空', 'warning');
            return;
          }
          
          try {
            showToast('正在上传音频...', 'info');
            const uploadedUrl = await uploadFile(file);
            if(uploadedUrl){
              node.data.referenceAudios.push({
                characterName: characterName.trim(),
                url: uploadedUrl,
                fileName: file.name
              });
              renderRefAudiosList();
              showToast('参考音频添加成功', 'success');
              try{ autoSaveWorkflow(); } catch(e){}
            } else {
              showToast('音频上传失败', 'error');
            }
          } catch(error){
            console.error('上传音频失败:', error);
            showToast('音频上传失败: ' + error.message, 'error');
          }
        });
        
        input.click();
      });

      renderRefAudiosList();

      function updateButtonsVisibility(isSelected){
        const addDialogueBtns = el.querySelectorAll('.dialogue-add-btn');
        addDialogueBtns.forEach(btn => {
          const container = btn.parentElement;
          if(container){
            container.style.display = isSelected ? 'block' : 'none';
          }
        });
        
        const downloadBtns = el.querySelectorAll('.dialogue-download-btn');
        downloadBtns.forEach(btn => {
          btn.style.display = isSelected ? 'inline-block' : 'none';
        });
        
        const actionContainers = el.querySelectorAll('.dialogue-actions');
        actionContainers.forEach(container => {
          container.style.display = isSelected ? 'flex' : 'none';
        });
      }
      
      const nodeObserver = new MutationObserver(() => {
        const isSelected = el.classList.contains('selected');
        updateButtonsVisibility(isSelected);
      });
      
      nodeObserver.observe(el, {
        attributes: true,
        attributeFilter: ['class']
      });

      function updateDialogueList(){
        const container = el.querySelector('.dialogue-items-container');
        if(!container) return;
        
        if(!node.data.dialogues || node.data.dialogues.length === 0){
          container.innerHTML = `
            <div class="gen-meta" style="text-align:center; padding: 20px;">暂无对话数据</div>
            <div style="margin-top: 12px; text-align: center; display: none;">
              <button class="mini-btn dialogue-add-btn" type="button" style="font-size: 11px; padding: 6px 12px; background: #3b82f6; color: white;">+ 添加对话</button>
            </div>
          `;
          attachDialogueItemEvents();
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
                <div style="display: flex; gap: 4px;">
                  <button class="mini-btn dialogue-edit-btn" data-index="${index}" type="button" style="font-size: 11px; padding: 4px 8px;" title="编辑">编辑</button>
                  <button class="mini-btn dialogue-delete-btn" data-index="${index}" type="button" style="font-size: 11px; padding: 4px 8px; background: #ef4444; color: white;" title="删除">删除</button>
                  <button class="mini-btn dialogue-generate-btn" data-index="${index}" type="button" style="font-size: 11px; padding: 4px 8px;">生成音频</button>
                </div>
              </div>
              <div class="dialogue-text-display" data-index="${index}" style="color: #6b7280; font-size: 13px; margin-bottom: 8px;">"${escapeHtml(text)}"</div>
              <div class="dialogue-edit-form" data-index="${index}" style="display: none; margin-bottom: 8px;">
                <input type="text" class="dialogue-edit-character" value="${escapeHtml(characterName)}" placeholder="角色名" style="width: 100%; padding: 6px; margin-bottom: 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 12px;">
                <textarea class="dialogue-edit-text" placeholder="对话内容" style="width: 100%; padding: 6px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 12px; resize: vertical;" rows="3">${escapeHtml(text)}</textarea>
                <div style="display: flex; gap: 4px; margin-top: 6px;">
                  <button class="mini-btn dialogue-save-btn" data-index="${index}" type="button" style="font-size: 11px; padding: 4px 8px; background: #10b981; color: white;">保存</button>
                  <button class="mini-btn dialogue-cancel-btn" data-index="${index}" type="button" style="font-size: 11px; padding: 4px 8px;">取消</button>
                </div>
              </div>
              <div class="dialogue-status" data-index="${index}" style="display:none; font-size: 12px; color: #6b7280; margin-bottom: 8px;"></div>
              <div class="dialogue-result" data-index="${index}" style="display:${hasAudio ? 'block' : 'none'};">
                <audio controls style="width:100%; max-height:32px; margin-bottom: 6px;"></audio>
                <div class="dialogue-actions" style="display: none; gap: 4px;">
                  <button class="mini-btn dialogue-download-btn" data-index="${index}" type="button" style="font-size: 11px; padding: 4px 8px;">下载</button>
                  <button class="mini-btn dialogue-add-timeline-btn" data-index="${index}" type="button" style="font-size: 11px; padding: 4px 8px; background: #10b981; color: white;">添加到时间轴</button>
                </div>
              </div>
            </div>
          `;
        });
        
        html += `
          <div style="margin-top: 12px; text-align: center; display: none;">
            <button class="mini-btn dialogue-add-btn" type="button" style="font-size: 11px; padding: 6px 12px; background: #3b82f6; color: white;">+ 添加对话</button>
          </div>
        `;
        
        container.innerHTML = html;
        attachDialogueItemEvents();
        
        const isSelected = el.classList.contains('selected');
        updateButtonsVisibility(isSelected);
        
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
        
        const addTimelineBtns = el.querySelectorAll('.dialogue-add-timeline-btn');
        addTimelineBtns.forEach(btn => {
          btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            await addDialogueAudioToTimeline(index);
          });
        });
        
        const editBtns = el.querySelectorAll('.dialogue-edit-btn');
        editBtns.forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            const item = el.querySelector(`.dialogue-item[data-index="${index}"]`);
            if(!item) return;
            
            const textDisplay = item.querySelector('.dialogue-text-display');
            const editForm = item.querySelector('.dialogue-edit-form');
            const editBtn = item.querySelector('.dialogue-edit-btn');
            const deleteBtn = item.querySelector('.dialogue-delete-btn');
            const generateBtn = item.querySelector('.dialogue-generate-btn');
            
            if(textDisplay) textDisplay.style.display = 'none';
            if(editForm) editForm.style.display = 'block';
            if(editBtn) editBtn.style.display = 'none';
            if(deleteBtn) deleteBtn.style.display = 'none';
            if(generateBtn) generateBtn.style.display = 'none';
          });
        });
        
        const saveBtns = el.querySelectorAll('.dialogue-save-btn');
        saveBtns.forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            const item = el.querySelector(`.dialogue-item[data-index="${index}"]`);
            if(!item) return;
            
            const characterInput = item.querySelector('.dialogue-edit-character');
            const textInput = item.querySelector('.dialogue-edit-text');
            
            if(!characterInput || !textInput) return;
            
            const newCharacter = characterInput.value.trim();
            const newText = textInput.value.trim();
            
            if(!newCharacter || !newText){
              showToast('角色名和对话内容不能为空', 'warning');
              return;
            }
            
            node.data.dialogues[index].character_name = newCharacter;
            node.data.dialogues[index].text = newText;
            
            if(node.data.audioResults[index]){
              delete node.data.audioResults[index];
            }
            
            updateDialogueList();
            try{ autoSaveWorkflow(); } catch(e){}
            showToast('对话已更新', 'success');
          });
        });
        
        const cancelBtns = el.querySelectorAll('.dialogue-cancel-btn');
        cancelBtns.forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            const item = el.querySelector(`.dialogue-item[data-index="${index}"]`);
            if(!item) return;
            
            const textDisplay = item.querySelector('.dialogue-text-display');
            const editForm = item.querySelector('.dialogue-edit-form');
            const editBtn = item.querySelector('.dialogue-edit-btn');
            const deleteBtn = item.querySelector('.dialogue-delete-btn');
            const generateBtn = item.querySelector('.dialogue-generate-btn');
            
            if(textDisplay) textDisplay.style.display = 'block';
            if(editForm) editForm.style.display = 'none';
            if(editBtn) editBtn.style.display = 'inline-block';
            if(deleteBtn) deleteBtn.style.display = 'inline-block';
            if(generateBtn) generateBtn.style.display = 'inline-block';
          });
        });
        
        const deleteBtns = el.querySelectorAll('.dialogue-delete-btn');
        deleteBtns.forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            
            if(!confirm('确定要删除这条对话吗？')){
              return;
            }
            
            node.data.dialogues.splice(index, 1);
            
            const newAudioResults = {};
            Object.keys(node.data.audioResults).forEach(key => {
              const idx = parseInt(key);
              if(idx < index){
                newAudioResults[idx] = node.data.audioResults[idx];
              } else if(idx > index){
                newAudioResults[idx - 1] = node.data.audioResults[idx];
              }
            });
            node.data.audioResults = newAudioResults;
            
            updateDialogueList();
            try{ autoSaveWorkflow(); } catch(e){}
            showToast('对话已删除', 'success');
          });
        });
        
        const addBtn = el.querySelector('.dialogue-add-btn');
        if(addBtn){
          addBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            
            const newDialogue = {
              character_name: '新角色',
              text: '请输入对话内容'
            };
            
            node.data.dialogues.push(newDialogue);
            updateDialogueList();
            try{ autoSaveWorkflow(); } catch(e){}
            showToast('已添加新对话', 'success');
            
            setTimeout(() => {
              const newIndex = node.data.dialogues.length - 1;
              const newItem = el.querySelector(`.dialogue-item[data-index="${newIndex}"]`);
              if(newItem){
                const editBtn = newItem.querySelector('.dialogue-edit-btn');
                if(editBtn) editBtn.click();
              }
            }, 100);
          });
        }
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
          
          const form = new FormData();
          form.append('text', dialogue.text);
          form.append('user_id', userId);
          form.append('emo_control_method', node.data.emoControlMethod || 0);
          
          let refAudioFound = false;
          
          // 标准化角色名称：去除【】等特殊符号，用于匹配
          const normalizeCharacterName = (name) => {
            if(!name) return '';
            return name.replace(/[【】\[\]]/g, '').trim();
          };
          
          const normalizedCharacterName = normalizeCharacterName(characterName);
          
          // 优先从对话组节点的参考音频中查找匹配的角色音频
          if(node.data.referenceAudios && node.data.referenceAudios.length > 0){
            const matchedRefAudio = node.data.referenceAudios.find(
              audio => normalizeCharacterName(audio.characterName) === normalizedCharacterName
            );
            
            if(matchedRefAudio){
              console.log('从对话组参考音频中找到匹配:', matchedRefAudio);
              const voiceUrl = proxyDownloadUrl(matchedRefAudio.url);
              
              try {
                const voiceResponse = await fetch(voiceUrl);
                if(voiceResponse.ok){
                  const voiceBlob = await voiceResponse.blob();
                  console.log('对话组参考音频Blob大小:', voiceBlob.size, '类型:', voiceBlob.type);
                  form.append('ref_audio', voiceBlob, 'ref_audio.wav');
                  refAudioFound = true;
                }
              } catch(error){
                console.error('获取对话组参考音频失败:', error);
              }
            }
          }
          
          // 如果对话组中没有找到，则从角色库中查找
          if(!refAudioFound){
            const matchedCharacter = await fetchAndMatchCharacter(worldId, characterName);
            console.log('匹配到的角色:', matchedCharacter);
            
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
              refAudioFound = true;
            } else {
              console.warn('未找到匹配的角色或角色没有配置参考音频');
            }
          }
          
          // 如果最终还是没有找到参考音频，给出明确提示
          if(!refAudioFound){
            throw new Error(`角色"${characterName}"没有配置参考音频。请在对话组节点中添加该角色的参考音频，或在角色库中为该角色配置参考音频。`);
          }
          
          if(node.data.emoControlMethod === 1){
            const videoConn = state.videoConnections.find(c => c.to === id);
            if(videoConn){
              const videoNode = state.nodes.find(n => n.id === videoConn.from);
              if(videoNode && videoNode.data.url){
                form.append('emo_ref_video_url', videoNode.data.url);
              }
            } else if(node.data.emoRefAudioUrl){
              const emoAudioUrl = proxyDownloadUrl(node.data.emoRefAudioUrl);
              const emoAudioResponse = await fetch(emoAudioUrl);
              if(emoAudioResponse.ok){
                const emoAudioBlob = await emoAudioResponse.blob();
                form.append('emo_ref_audio', emoAudioBlob, 'emo_ref_audio.wav');
              }
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
          if(!res.ok){
            const errorText = await res.text();
            throw new Error(`服务器错误 (${res.status}): ${errorText || '请求失败'}`);
          }
          
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
            
            const text = await res.text();
            const payload = text ? JSON.parse(text) : null;
            
            if(!payload){
              setTimeout(checkStatus, 10000);
              return;
            }
            
            const status = typeof payload.status === 'string' ? payload.status.toUpperCase() : payload.status;
            
            if(status === 'SUCCESS' || status === 2){
              if(payload.result_url){
                // 直接使用返回的 result_url
                if(!node.data.audioResults) node.data.audioResults = {};
                node.data.audioResults[index] = { audioUrl: payload.result_url };
                
                const audio = resultDiv.querySelector('audio');
                if(audio) audio.src = payload.result_url;
                resultDiv.style.display = 'block';
                
                statusEl.textContent = '生成成功！';
                showToast('语音生成成功', 'success');
                
                try{ autoSaveWorkflow(); } catch(e){}
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
        
        const link = document.createElement('a');
        link.href = audioUrl;
        link.download = filename;
        link.target = '_blank';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showToast('开始下载', 'success');
      }

      async function addDialogueAudioToTimeline(index){
        if(!node.data.audioResults || !node.data.audioResults[index]){
          showToast('没有可添加的音频', 'error');
          return;
        }
        
        const audioUrl = node.data.audioResults[index].audioUrl;
        const dialogue = node.data.dialogues[index];
        const characterName = dialogue.character_name || '角色';
        const audioName = `${characterName}: ${dialogue.text.substring(0, 20)}...`;
        
        try {
          const duration = await getAudioDuration(audioUrl);
          addAudioToTimeline(id, index, audioUrl, audioName, duration);
        } catch(error) {
          console.warn('获取音频时长失败，使用默认时长:', error);
          addAudioToTimeline(id, index, audioUrl, audioName, 5);
        }
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

      updateDialogueList();
      
      // 初始化视频输入端口的禁用状态
      if(videoInputPort){
        if(node.data.emoControlMethod === 1){
          videoInputPort.classList.remove('disabled');
        } else {
          videoInputPort.classList.add('disabled');
        }
      }
      
      // 暴露渲染参考音频列表的方法，供恢复节点时使用
      node.renderRefAudiosList = renderRefAudiosList;
      
      // 添加调试按钮
      addDebugButtonToNode(el, node);
      
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
        dialogueData: nodeData.data.dialogues || [],
        shotNumber: nodeData.data.shotNumber || null
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
      const emoRefAudioInput = el.querySelector('.dialogue-emo-ref-audio-input');
      const emoRefAudioClearBtn = el.querySelector('.dialogue-emo-ref-audio-clear-btn');
      const emoRefAudioPreview = el.querySelector('.dialogue-emo-ref-audio-preview');
      const emoWeightField = el.querySelector('.dialogue-emo-weight-field');
      const emoWeightSlider = el.querySelector('.dialogue-emo-weight-slider');
      const emoWeightValue = el.querySelector('.dialogue-emo-weight-value');
      const emoVecField = el.querySelector('.dialogue-emo-vec-field');
      const emoVecSliders = el.querySelectorAll('.dialogue-emo-vec-slider');
      const videoInputPort = el.querySelector('.port.video-input-port');
      
      if(emoControlSelect && node.data.emoControlMethod !== undefined){
        emoControlSelect.value = node.data.emoControlMethod;
        
        // 情感参考音频区域始终显示，但在非情感参考音频模式下禁用
        const isEmoRefMode = node.data.emoControlMethod === 1;
        if(emoRefAudioField){
          emoRefAudioField.style.opacity = isEmoRefMode ? '1' : '0.5';
          emoRefAudioField.style.pointerEvents = isEmoRefMode ? 'auto' : 'none';
        }
        if(emoRefAudioInput) emoRefAudioInput.disabled = !isEmoRefMode;
        if(emoRefAudioClearBtn) emoRefAudioClearBtn.disabled = !isEmoRefMode;
        
        if(emoWeightField) emoWeightField.style.display = node.data.emoControlMethod === 1 ? 'block' : 'none';
        if(emoVecField) emoVecField.style.display = node.data.emoControlMethod === 2 ? 'block' : 'none';
        
        // 视频输入端口始终显示，但在非情感参考音频模式下禁用
        if(videoInputPort){
          if(isEmoRefMode){
            videoInputPort.classList.remove('disabled');
          } else {
            videoInputPort.classList.add('disabled');
          }
        }
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
      
      // 恢复参考音频列表
      if(node.renderRefAudiosList){
        node.renderRefAudiosList();
      }
    }
