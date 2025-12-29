    // ============ 时间轴功能 ============
    
    // 添加视频到时间轴
    function addToTimeline(nodeId) {
      const node = state.nodes.find(n => n.id === nodeId);
      if (!node || node.type !== 'video' || !node.data.url) {
        showToast('请先生成或上传视频', 'error');
        return;
      }
      
      // 如果没有时长，尝试获取
      if (!node.data.duration) {
        getVideoDuration(node.data.url).then(duration => {
          node.data.duration = duration;
          addClipToTimeline(nodeId, node, duration);
        }).catch(() => {
          addClipToTimeline(nodeId, node, 10);
        });
      } else {
        addClipToTimeline(nodeId, node, node.data.duration);
      }
    }
    
    // 添加片段到时间轴的辅助函数
    function addClipToTimeline(nodeId, node, duration) {
      const clip = {
        id: state.timeline.nextClipId++,
        nodeId: nodeId,
        url: node.data.url,
        name: node.data.name || '视频',
        duration: duration,
        startTime: 0,           // 剪切开始时间（秒）
        endTime: duration,      // 剪切结束时间（秒）
        order: state.timeline.clips.length,
      };
      
      state.timeline.clips.push(clip);
      state.timeline.visible = true;
      
      renderTimeline();
      showToast('已添加到时间轴', 'success');
      try{ autoSaveWorkflow(); } catch(e){}
    }
    
    // 获取视频时长
    function getVideoDuration(url) {
      return new Promise((resolve, reject) => {
        const video = document.createElement('video');
        video.preload = 'metadata';
        video.muted = true;
        
        video.addEventListener('loadedmetadata', () => {
          if (video.duration && isFinite(video.duration)) {
            resolve(Math.round(video.duration));
          } else {
            reject(new Error('Invalid duration'));
          }
          video.src = '';
        }, { once: true });
        
        video.addEventListener('error', () => {
          reject(new Error('Failed to load video'));
        }, { once: true });
        
        video.src = proxyDownloadUrl(url);
      });
    }
    
    // 从时间轴移除片段
    function removeFromTimeline(clipId) {
      state.timeline.clips = state.timeline.clips.filter(c => c.id !== clipId);
      state.timeline.clips.forEach((c, i) => c.order = i);
      renderTimeline();
      showToast('已从时间轴移除', 'success');
      try{ autoSaveWorkflow(); } catch(e){}
    }
    
    // 移动时间轴片段（拖拽排序）
    function moveTimelineClip(clipId, newOrder) {
      const clip = state.timeline.clips.find(c => c.id === clipId);
      if (!clip) return;
      
      const oldOrder = clip.order;
      if (oldOrder === newOrder) return;
      
      state.timeline.clips.forEach(c => {
        if (c.id === clipId) {
          c.order = newOrder;
        } else if (oldOrder < newOrder && c.order > oldOrder && c.order <= newOrder) {
          c.order--;
        } else if (oldOrder > newOrder && c.order >= newOrder && c.order < oldOrder) {
          c.order++;
        }
      });
      
      state.timeline.clips.sort((a, b) => a.order - b.order);
      renderTimeline();
      try{ autoSaveWorkflow(); } catch(e){}
    }
    
    // 渲染时间轴
    function renderTimeline() {
      const container = document.getElementById('timelineContainer');
      const track = document.getElementById('videoTrack');
      const ruler = document.getElementById('timelineRuler');
      const totalDurationEl = document.getElementById('timelineTotalDuration');
      const expandBtn = document.getElementById('timelineExpandBtn');
      
      if (!state.timeline.visible || state.timeline.clips.length === 0) {
        container.style.display = 'none';
        expandBtn.style.display = 'none';
        canvasContainer.classList.remove('timeline-visible');
        return;
      }
      
      container.style.display = 'flex';
      expandBtn.style.display = 'none';
      canvasContainer.classList.add('timeline-visible');
      
      // 计算总时长（考虑剪切后的实际播放时长）
      const totalDuration = state.timeline.clips.reduce((sum, c) => {
        const actualDuration = (c.endTime || c.duration) - (c.startTime || 0);
        return sum + actualDuration;
      }, 0);
      const minutes = Math.floor(totalDuration / 60);
      const seconds = (totalDuration % 60).toFixed(2);
      totalDurationEl.textContent = `总时长: ${minutes}:${seconds.padStart(5, '0')}`;
      
      renderTimelineRuler(ruler, totalDuration);
      
      const sortedClips = [...state.timeline.clips].sort((a, b) => a.order - b.order);
      
      // 计算每个片段的累计起始时间
      let accumulatedTime = 0;
      track.innerHTML = sortedClips.map(clip => {
        const startTime = accumulatedTime;
        // 计算剪切后的实际播放时长
        const clipStartTime = clip.startTime || 0;
        const clipEndTime = clip.endTime || clip.duration;
        const actualDuration = clipEndTime - clipStartTime;
        const width = actualDuration * 10;
        accumulatedTime += actualDuration;
        
        // 显示剪切信息
        const isTrimmed = clipStartTime > 0 || clipEndTime < clip.duration;
        const durationText = isTrimmed ? `${actualDuration.toFixed(1)}s (已剪切)` : `${actualDuration}s`;
        
        return `
          <div class="timeline-clip ${state.timeline.selectedClipId === clip.id ? 'selected' : ''}" 
               data-clip-id="${clip.id}" 
               draggable="true"
               style="position: absolute; left: ${startTime * 10}px; width: ${width}px;">
            <video class="timeline-clip-thumb" src="${proxyDownloadUrl(clip.url)}" muted preload="metadata"></video>
            <div class="timeline-clip-name" title="${clip.name}">${clip.name}</div>
            <div class="timeline-clip-duration">${durationText}</div>
            <div class="timeline-clip-actions">
              <button class="vp-btn clip-trim-btn" title="剪切">✂</button>
              <button class="vp-btn clip-remove-btn" title="移除">×</button>
            </div>
          </div>
        `;
      }).join('');
      
      // 设置轨道最小宽度以容纳所有片段
      track.style.minWidth = (totalDuration * 10 + 24) + 'px'; // 24px for padding
      
      bindTimelineClipEvents();
    }
    
    // 渲染时间刻度
    function renderTimelineRuler(ruler, totalDuration) {
      let html = '';
      const interval = totalDuration > 60 ? 10 : 5;
      for (let i = 0; i <= totalDuration; i += interval) {
        const minutes = Math.floor(i / 60);
        const seconds = i % 60;
        const label = `${minutes}:${seconds.toString().padStart(2, '0')}`;
        html += `<div class="ruler-mark" style="left:${i * 10}px;">${label}</div>`;
      }
      ruler.innerHTML = html;
    }
    
    // 替换时间轴片段
    function replaceTimelineClip(targetClipId, draggedClipId) {
      const targetClip = state.timeline.clips.find(c => c.id === targetClipId);
      const draggedClip = state.timeline.clips.find(c => c.id === draggedClipId);
      
      if (!targetClip || !draggedClip) return;
      
      // 用拖拽的片段内容替换目标片段
      targetClip.url = draggedClip.url;
      targetClip.name = draggedClip.name;
      targetClip.duration = draggedClip.duration;
      targetClip.startTime = draggedClip.startTime || 0;
      targetClip.endTime = draggedClip.endTime || draggedClip.duration;
      targetClip.nodeId = draggedClip.nodeId;
      
      // 删除被拖拽的片段
      state.timeline.clips = state.timeline.clips.filter(c => c.id !== draggedClipId);
      
      // 重新规范化order
      state.timeline.clips.sort((a, b) => a.order - b.order);
      state.timeline.clips.forEach((c, index) => {
        c.order = index;
      });
      
      renderTimeline();
      showToast('已替换视频片段', 'success');
      try{ autoSaveWorkflow(); } catch(e){}
    }
    
    // 绑定时间轴片段事件
    function bindTimelineClipEvents() {
      const track = document.getElementById('videoTrack');
      
      // 创建插入位置指示器
      let dropIndicator = track.querySelector('.timeline-drop-indicator');
      if (!dropIndicator) {
        dropIndicator = document.createElement('div');
        dropIndicator.className = 'timeline-drop-indicator';
        track.appendChild(dropIndicator);
      }
      
      let draggedClipId = null;
      let dropPosition = null; // { clipId, insertBefore: true/false }
      
      track.querySelectorAll('.timeline-clip').forEach(clipEl => {
        const clipId = Number(clipEl.dataset.clipId);
        
        clipEl.addEventListener('click', (e) => {
          if(e.target.classList.contains('clip-remove-btn')) return;
          if(e.target.classList.contains('clip-trim-btn')) return;
          state.timeline.selectedClipId = clipId;
          renderTimeline();
        });
        
        clipEl.addEventListener('dragstart', (e) => {
          draggedClipId = clipId;
          e.dataTransfer.setData('text/plain', clipId);
          e.dataTransfer.effectAllowed = 'move';
          clipEl.classList.add('dragging');
        });
        
        clipEl.addEventListener('dragend', () => {
          clipEl.classList.remove('dragging');
          dropIndicator.classList.remove('show');
          track.querySelectorAll('.timeline-clip').forEach(el => {
            el.classList.remove('drop-target');
          });
          draggedClipId = null;
          dropPosition = null;
        });
        
        clipEl.addEventListener('dragover', (e) => {
          e.preventDefault();
          if (!draggedClipId || draggedClipId === clipId) {
            dropIndicator.classList.remove('show');
            return;
          }
          
          e.dataTransfer.dropEffect = 'move';
          
          // 检测是否按住Shift键进行替换
          if (e.shiftKey) {
            // 替换模式：高亮整个片段
            clipEl.classList.add('drop-target');
            dropIndicator.classList.remove('show');
            dropPosition = { clipId, replace: true };
          } else {
            // 插入模式：显示插入位置指示器
            clipEl.classList.remove('drop-target');
            
            const rect = clipEl.getBoundingClientRect();
            const mouseX = e.clientX;
            const clipCenterX = rect.left + rect.width / 2;
            const insertBefore = mouseX < clipCenterX;
            
            // 计算指示器位置
            const trackRect = track.getBoundingClientRect();
            let indicatorLeft;
            if (insertBefore) {
              indicatorLeft = rect.left - trackRect.left - 2;
            } else {
              indicatorLeft = rect.right - trackRect.left - 2;
            }
            
            dropIndicator.style.left = indicatorLeft + 'px';
            dropIndicator.classList.add('show');
            dropPosition = { clipId, insertBefore };
          }
        });
        
        clipEl.addEventListener('dragleave', (e) => {
          if (!clipEl.contains(e.relatedTarget)) {
            clipEl.classList.remove('drop-target');
          }
        });
        
        clipEl.addEventListener('drop', (e) => {
          e.preventDefault();
          e.stopPropagation();
          clipEl.classList.remove('drop-target');
          dropIndicator.classList.remove('show');
          
          if (!draggedClipId || draggedClipId === clipId || !dropPosition) return;
          
          if (dropPosition.replace) {
            // 替换模式
            replaceTimelineClip(clipId, draggedClipId);
          } else {
            // 插入模式
            // 先排序获取当前实际顺序
            const sortedClips = [...state.timeline.clips].sort((a, b) => a.order - b.order);
            const targetIndex = sortedClips.findIndex(c => c.id === clipId);
            const draggedIndex = sortedClips.findIndex(c => c.id === draggedClipId);
            
            if (targetIndex !== -1 && draggedIndex !== -1) {
              // 计算光标位置对应的最终插入位置
              let finalPosition;
              if (dropPosition.insertBefore) {
                // 光标在目标元素前面
                finalPosition = targetIndex;
              } else {
                // 光标在目标元素后面
                finalPosition = targetIndex + 1;
              }
              
              // 如果被拖拽元素在光标位置之前，需要调整最终位置
              // 因为移除被拖拽元素后，后面的元素会前移
              if (draggedIndex < finalPosition) {
                finalPosition--;
              }
              
              moveTimelineClipToPosition(draggedClipId, finalPosition);
            }
          }
          
          dropPosition = null;
        });
        
        const removeBtn = clipEl.querySelector('.clip-remove-btn');
        if(removeBtn){
          removeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            removeFromTimeline(clipId);
          });
        }
        
        const trimBtn = clipEl.querySelector('.clip-trim-btn');
        if(trimBtn){
          trimBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            console.log('Trim button clicked, clipId:', clipId);
            openTrimDialog(clipId);
          });
        } else {
          console.warn('Trim button not found for clip:', clipId);
        }
      });
    }
    
    // 打开剪切对话框（带预览功能）
    function openTrimDialog(clipId) {
      const clip = state.timeline.clips.find(c => c.id === clipId);
      if(!clip) return;
      
      const startTime = clip.startTime || 0;
      const endTime = clip.endTime || clip.duration;
      
      // 创建模态框
      const dialog = document.createElement('div');
      dialog.className = 'modal show';
      dialog.id = 'trimDialog';
      dialog.innerHTML = `
        <div class="modal-card" style="max-width: 900px;">
          <div class="modal-header">
            <div class="modal-title">剪切视频片段 - ${clip.name}</div>
            <button class="modal-close" type="button" aria-label="关闭">×</button>
          </div>
          <div class="modal-body" style="padding: 20px;">
            <!-- 视频预览区域 -->
            <div style="margin-bottom: 20px; background: #000; border-radius: 8px; overflow: hidden; position: relative;">
              <video id="trimPreviewVideo" 
                     style="width: 100%; height: 450px; object-fit: contain;" 
                     preload="metadata"
                     muted></video>
              <!-- 加载提示 -->
              <div id="trimLoadingOverlay" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); display: flex; flex-direction: column; align-items: center; justify-content: center; color: #fff;">
                <div style="font-size: 16px; margin-bottom: 12px;">正在加载视频...</div>
                <div style="width: 200px; height: 4px; background: rgba(255,255,255,0.2); border-radius: 2px; overflow: hidden;">
                  <div id="trimLoadingProgress" style="width: 0%; height: 100%; background: #3b82f6; transition: width 0.3s;"></div>
                </div>
                <div id="trimLoadingText" style="font-size: 12px; margin-top: 8px; color: var(--muted);">准备中...</div>
              </div>
            </div>
            
            <!-- 时间轴滑块区域 -->
            <div style="margin-bottom: 20px;">
              <div id="trimTrackContainer" style="position: relative; height: 100px; background: #1a1a1a; border-radius: 8px; overflow: hidden; cursor: pointer; opacity: 0.5; pointer-events: none;">
                <!-- 视频缩略图轨道 -->
                <canvas id="trimThumbnailTrack" 
                        style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;"></canvas>
                
                <!-- 左侧遮罩 -->
                <div id="trimLeftMask" 
                     style="position: absolute; top: 0; left: 0; height: 100%; background: rgba(0, 0, 0, 0.7); pointer-events: none;"></div>
                
                <!-- 右侧遮罩 -->
                <div id="trimRightMask" 
                     style="position: absolute; top: 0; right: 0; height: 100%; background: rgba(0, 0, 0, 0.7); pointer-events: none;"></div>
                
                <!-- 选中区域边框 -->
                <div id="trimSelectedRange" 
                     style="position: absolute; top: 0; height: 100%; border: 3px solid #3b82f6; pointer-events: none; box-sizing: border-box;"></div>
                
                <!-- 开始时间滑块 -->
                <div id="trimStartHandle" 
                     style="position: absolute; top: 0; width: 16px; height: 100%; background: #3b82f6; cursor: ew-resize; z-index: 10; box-shadow: 0 0 8px rgba(59, 130, 246, 0.5);">
                  <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 3px; height: 50px; background: #fff; border-radius: 2px;"></div>
                </div>
                
                <!-- 结束时间滑块 -->
                <div id="trimEndHandle" 
                     style="position: absolute; top: 0; width: 16px; height: 100%; background: #3b82f6; cursor: ew-resize; z-index: 10; box-shadow: 0 0 8px rgba(59, 130, 246, 0.5);">
                  <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 3px; height: 50px; background: #fff; border-radius: 2px;"></div>
                </div>
              </div>
              
              <!-- 时间显示 -->
              <div style="display: flex; justify-content: space-between; margin-top: 12px; font-size: 13px; color: var(--text);">
                <span>开始: <strong id="trimStartTimeDisplay">0.0</strong>s</span>
                <span>剪辑时长: <strong id="trimDurationDisplay" style="color: #3b82f6;">0.0</strong>s</span>
                <span>结束: <strong id="trimEndTimeDisplay">0.0</strong>s</span>
              </div>
            </div>
            
            <!-- 播放控制和操作按钮 -->
            <div style="display: flex; gap: 12px; justify-content: space-between; align-items: center;">
              <div style="display: flex; gap: 12px;">
                <button class="btn btn-secondary" id="trimPlayBtn" type="button">▶ 预览剪辑效果</button>
                <button class="btn btn-secondary" id="trimResetBtn" type="button">重置</button>
              </div>
              <div style="display: flex; gap: 8px;">
                <button class="btn btn-secondary" id="trimCancelBtn" type="button">取消</button>
                <button class="btn btn-primary" id="confirmTrim" type="button">确定剪切</button>
              </div>
            </div>
          </div>
        </div>
      `;
      
      document.body.appendChild(dialog);
      
      // 获取DOM元素
      const video = dialog.querySelector('#trimPreviewVideo');
      const canvas = dialog.querySelector('#trimThumbnailTrack');
      const ctx = canvas.getContext('2d');
      const startHandle = dialog.querySelector('#trimStartHandle');
      const endHandle = dialog.querySelector('#trimEndHandle');
      const selectedRange = dialog.querySelector('#trimSelectedRange');
      const leftMask = dialog.querySelector('#trimLeftMask');
      const rightMask = dialog.querySelector('#trimRightMask');
      const startTimeDisplay = dialog.querySelector('#trimStartTimeDisplay');
      const endTimeDisplay = dialog.querySelector('#trimEndTimeDisplay');
      const durationDisplay = dialog.querySelector('#trimDurationDisplay');
      const playBtn = dialog.querySelector('#trimPlayBtn');
      const resetBtn = dialog.querySelector('#trimResetBtn');
      const trackContainer = dialog.querySelector('#trimTrackContainer');
      const loadingOverlay = dialog.querySelector('#trimLoadingOverlay');
      const loadingProgress = dialog.querySelector('#trimLoadingProgress');
      const loadingText = dialog.querySelector('#trimLoadingText');
      
      // 状态变量
      let currentStart = startTime;
      let currentEnd = endTime;
      let isDraggingStart = false;
      let isDraggingEnd = false;
      let isPlaying = false;
      let thumbnailsGenerated = false;
      let videoReady = false;
      
      // Blob URL（用于清理）
      let blobUrl = null;
      
      // 预下载视频为Blob，这样seek就能正常工作
      const preloadVideoAsBlob = () => {
        return new Promise((resolve, reject) => {
          loadingText.textContent = '正在下载视频以支持精确剪辑...';
          loadingProgress.style.width = '5%';
          
          const xhr = new XMLHttpRequest();
          xhr.open('GET', proxyDownloadUrl(clip.url), true);
          xhr.responseType = 'blob';
          
          xhr.onprogress = (e) => {
            if(e.lengthComputable){
              const percent = Math.round((e.loaded / e.total) * 70);
              loadingProgress.style.width = `${5 + percent}%`;
              const mb = (e.loaded / 1024 / 1024).toFixed(1);
              const totalMb = (e.total / 1024 / 1024).toFixed(1);
              loadingText.textContent = `下载视频中... ${mb}MB / ${totalMb}MB`;
            }
          };
          
          xhr.onload = () => {
            if(xhr.status === 200){
              const blob = xhr.response;
              blobUrl = URL.createObjectURL(blob);
              video.src = blobUrl;
              console.log('视频已下载为Blob，seek功能已启用');
              resolve();
            } else {
              reject(new Error(`下载失败: ${xhr.status}`));
            }
          };
          
          xhr.onerror = () => reject(new Error('网络错误'));
          xhr.ontimeout = () => reject(new Error('下载超时'));
          xhr.timeout = 120000; // 2分钟超时
          
          xhr.send();
        });
      };
      
      // 等待视频加载完成
      const waitForVideoReady = () => {
        return new Promise((resolve, reject) => {
          if(video.readyState >= 2 && video.duration && isFinite(video.duration)){
            videoReady = true;
            resolve();
            return;
          }
          
          const timeout = setTimeout(() => {
            reject(new Error('视频加载超时'));
          }, 30000);
          
          const onCanPlay = () => {
            if(video.duration && isFinite(video.duration) && video.duration > 0){
              clearTimeout(timeout);
              video.removeEventListener('canplay', onCanPlay);
              loadingText.textContent = '视频已就绪，正在生成缩略图...';
              loadingProgress.style.width = '80%';
              videoReady = true;
              resolve();
            }
          };
          
          video.addEventListener('canplay', onCanPlay);
          video.addEventListener('error', () => {
            clearTimeout(timeout);
            reject(new Error('视频加载失败'));
          });
        });
      };
      
      // 生成视频缩略图（使用seek方式，Blob URL支持精确seek）
      const generateThumbnails = async () => {
        if(thumbnailsGenerated) return;
        if(!videoReady) return;
        
        const containerWidth = trackContainer.offsetWidth;
        const containerHeight = trackContainer.offsetHeight;
        canvas.width = containerWidth;
        canvas.height = containerHeight;
        
        const thumbnailCount = 10;
        const thumbnailWidth = containerWidth / thumbnailCount;
        const videoDuration = video.duration;
        
        console.log('=== 开始生成缩略图（Seek模式）===');
        console.log('Video duration:', videoDuration, 'seconds');
        
        // 绘制帧到canvas指定位置
        const drawFrameAt = (index) => {
          const aspectRatio = video.videoWidth / video.videoHeight || 16/9;
          const drawHeight = containerHeight;
          const drawWidth = drawHeight * aspectRatio;
          const offsetX = (thumbnailWidth - drawWidth) / 2;
          
          ctx.drawImage(video, 
            index * thumbnailWidth + Math.max(0, offsetX), 0, 
            drawWidth, drawHeight);
        };
        
        // 等待seek完成并绘制
        const seekAndDraw = (index, time) => {
          return new Promise((resolve) => {
            const onSeeked = () => {
              video.removeEventListener('seeked', onSeeked);
              drawFrameAt(index);
              console.log(`✓ 缩略图 ${index + 1}/${thumbnailCount}: seek到=${time.toFixed(2)}s, 实际=${video.currentTime.toFixed(2)}s`);
              resolve();
            };
            video.addEventListener('seeked', onSeeked);
            video.currentTime = time;
          });
        };
        
        video.pause();
        
        // 按顺序生成每一帧
        for(let i = 0; i < thumbnailCount; i++){
          const time = thumbnailCount > 1 ? (i / (thumbnailCount - 1)) * videoDuration : 0;
          
          const progress = 80 + (i / thumbnailCount) * 20;
          loadingProgress.style.width = `${progress}%`;
          loadingText.textContent = `生成缩略图 ${i + 1}/${thumbnailCount}...`;
          
          await seekAndDraw(i, time);
        }
        
        thumbnailsGenerated = true;
        video.currentTime = currentStart;
        
        // 隐藏加载提示，启用时间轴
        loadingOverlay.style.display = 'none';
        trackContainer.style.opacity = '1';
        trackContainer.style.pointerEvents = 'auto';
        
        console.log('=== 缩略图生成完成 ===');
      };
      
      // 更新UI显示
      const updateUI = (updateVideoTime = false) => {
        const trackWidth = trackContainer.offsetWidth;
        const startPercent = (currentStart / clip.duration) * 100;
        const endPercent = (currentEnd / clip.duration) * 100;
        
        startHandle.style.left = `calc(${startPercent}% - 8px)`;
        endHandle.style.left = `calc(${endPercent}% - 8px)`;
        selectedRange.style.left = `${startPercent}%`;
        selectedRange.style.width = `${endPercent - startPercent}%`;
        
        // 更新遮罩
        leftMask.style.width = `${startPercent}%`;
        rightMask.style.width = `${100 - endPercent}%`;
        
        startTimeDisplay.textContent = currentStart.toFixed(1);
        endTimeDisplay.textContent = currentEnd.toFixed(1);
        durationDisplay.textContent = (currentEnd - currentStart).toFixed(1);
        
        // 只在明确指定时才更新视频时间
        if(updateVideoTime && !isPlaying){
          video.currentTime = currentStart;
        }
      };
      
      // 初始化：预下载视频为Blob，然后生成缩略图
      (async () => {
        try {
          // 先下载视频为Blob，这样seek才能正常工作
          await preloadVideoAsBlob();
          await waitForVideoReady();
          updateUI();
          await generateThumbnails();
        } catch(error) {
          console.error('视频加载或缩略图生成失败:', error);
          loadingText.textContent = '加载失败: ' + error.message;
          loadingText.style.color = '#ef4444';
          showToast('视频加载失败，请重试', 'error');
        }
      })();
      
      // 拖动开始滑块
      startHandle.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        isDraggingStart = true;
      });
      
      // 拖动结束滑块
      endHandle.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        isDraggingEnd = true;
      });
      
      // 点击时间轴跳转并播放
      trackContainer.addEventListener('click', (e) => {
        if(isDraggingStart || isDraggingEnd) return;
        if(e.target === startHandle || e.target === endHandle) return;
        if(e.target.parentElement === startHandle || e.target.parentElement === endHandle) return;
        
        const rect = trackContainer.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const percent = x / rect.width;
        const time = percent * clip.duration;
        
        // 限制在剪辑范围内
        const targetTime = Math.max(currentStart, Math.min(time, currentEnd));
        video.currentTime = targetTime;
        
        // 自动播放
        if(!isPlaying){
          video.play();
          isPlaying = true;
          playBtn.textContent = '⏸ 暂停';
        }
      });
      
      // 鼠标移动事件
      const handleMouseMove = (e) => {
        if(!isDraggingStart && !isDraggingEnd) return;
        
        const rect = trackContainer.getBoundingClientRect();
        const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
        const percent = x / rect.width;
        const time = percent * clip.duration;
        
        if(isDraggingStart){
          currentStart = Math.max(0, Math.min(time, currentEnd - 0.1));
          // 拖动起点时更新视频画面到起点
          if(!isPlaying){
            video.currentTime = currentStart;
          }
        } else if(isDraggingEnd){
          currentEnd = Math.max(currentStart + 0.1, Math.min(time, clip.duration));
          // 拖动终点时不更新视频画面
        }
        
        updateUI(false);
      };
      
      // 鼠标释放事件
      const handleMouseUp = () => {
        // 拖动结束，不自动播放，让用户手动点击播放按钮
        isDraggingStart = false;
        isDraggingEnd = false;
      };
      
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      
      // 预览播放（Blob URL支持精确seek）
      playBtn.addEventListener('click', () => {
        if(isPlaying){
          video.pause();
          isPlaying = false;
          playBtn.textContent = '▶ 预览剪辑效果';
        } else {
          // 从起点开始播放
          video.currentTime = currentStart;
          video.play();
          isPlaying = true;
          playBtn.textContent = '⏸ 暂停';
          console.log(`开始播放: 起点=${currentStart.toFixed(2)}s, 终点=${currentEnd.toFixed(2)}s`);
        }
      });
      
      // 视频播放时检查是否到达终点
      video.addEventListener('timeupdate', () => {
        if(isPlaying && video.currentTime >= currentEnd){
          video.pause();
          // 保留在终点画面，不回到起点
          isPlaying = false;
          playBtn.textContent = '▶ 预览剪辑效果';
          console.log(`到达终点: ${video.currentTime.toFixed(2)}s >= ${currentEnd.toFixed(2)}s, 已暂停并保留在终点画面`);
        }
      });
      
      // 重置按钮
      resetBtn.addEventListener('click', () => {
        currentStart = 0;
        currentEnd = clip.duration;
        updateUI();
      });
      
      // 关闭对话框
      const closeDialog = () => {
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
        video.pause();
        // 清理Blob URL，释放内存
        if(blobUrl){
          URL.revokeObjectURL(blobUrl);
          blobUrl = null;
        }
        dialog.classList.remove('show');
        setTimeout(() => dialog.remove(), 300);
      };
      
      // 取消按钮
      const cancelBtn = dialog.querySelector('#trimCancelBtn');
      if(cancelBtn){
        cancelBtn.addEventListener('click', closeDialog);
      }
      
      // 关闭按钮（右上角的×）
      dialog.querySelectorAll('.modal-close').forEach(btn => {
        btn.addEventListener('click', closeDialog);
      });
      
      // 确认剪切
      dialog.querySelector('#confirmTrim').addEventListener('click', () => {
        // 验证输入
        if(currentStart < 0 || currentStart >= clip.duration){
          showToast('开始时间无效', 'error');
          return;
        }
        if(currentEnd <= currentStart || currentEnd > clip.duration){
          showToast('结束时间必须大于开始时间且不超过视频时长', 'error');
          return;
        }
        
        // 更新片段的剪切时间
        clip.startTime = currentStart;
        clip.endTime = currentEnd;
        
        renderTimeline();
        showToast('剪切成功', 'success');
        try{ autoSaveWorkflow(); } catch(e){}
        
        closeDialog();
      });
      
      // 点击背景关闭
      dialog.addEventListener('click', (e) => {
        if(e.target === dialog){
          closeDialog();
        }
      });
    }
    
    // 移动片段到指定位置（简化版本）
    function moveTimelineClipToPosition(clipId, targetOrder) {
      const clipIndex = state.timeline.clips.findIndex(c => c.id === clipId);
      if (clipIndex === -1) return;
      
      // 先按当前order排序
      state.timeline.clips.sort((a, b) => a.order - b.order);
      
      // 移除元素
      const [clip] = state.timeline.clips.splice(clipIndex, 1);
      
      // 确保targetOrder在有效范围内
      targetOrder = Math.max(0, Math.min(targetOrder, state.timeline.clips.length));
      
      // 插入到新位置
      state.timeline.clips.splice(targetOrder, 0, clip);
      
      // 重新分配order
      state.timeline.clips.forEach((c, index) => {
        c.order = index;
      });
      
      renderTimeline();
      try{ autoSaveWorkflow(); } catch(e){}
    }
    
    // Cookie工具函数
    function setCookie(name, value, days) {
      const expires = new Date();
      expires.setTime(expires.getTime() + days * 24 * 60 * 60 * 1000);
      document.cookie = `${name}=${encodeURIComponent(value)};expires=${expires.toUTCString()};path=/`;
    }
    
    function getCookie(name) {
      const nameEQ = name + "=";
      const ca = document.cookie.split(';');
      for(let i = 0; i < ca.length; i++) {
        let c = ca[i];
        while (c.charAt(0) === ' ') c = c.substring(1, c.length);
        if (c.indexOf(nameEQ) === 0) return decodeURIComponent(c.substring(nameEQ.length, c.length));
      }
      return null;
    }
    
    // 导出时间轴到剪影草稿
    function exportTimelineToDraft() {
      if (!state.timeline.clips || state.timeline.clips.length === 0) {
        showToast('时间轴为空，无法导出', 'error');
        return;
      }
      
      // 从cookie获取上次保存的路径
      const savedPath = getCookie('jianying_draft_path') || '';
      
      // 创建输入对话框
      const dialog = document.createElement('div');
      dialog.className = 'modal show';
      dialog.innerHTML = `
        <div class="modal-card" style="max-width: 700px; background: white;">
          <div class="modal-header" style="background: white; border-bottom: 1px solid #e5e7eb;">
            <div class="modal-title" style="color: #111827;">导出剪影草稿</div>
            <button class="modal-close" type="button" aria-label="关闭">×</button>
          </div>
          <div class="modal-body" style="padding: 20px; background: white;">
            <div style="margin-bottom: 20px;">
              <label style="display: block; margin-bottom: 8px; font-weight: 500; color: #111827;">剪影草稿路径前缀</label>
              <input type="text" id="draftPathInput" class="input" 
                     value="${savedPath}"
                     placeholder="例如: C:\\Users\\Administrator\\AppData\\Local\\JianyingPro\\User Data\\Projects\\com.lveditor.draft"
                     style="width: 100%; padding: 8px; border: 1px solid #d1d5db; border-radius: 4px; background: white; color: #111827;">
              <div style="margin-top: 8px; font-size: 12px; color: #6b7280;">
                提示: 请输入剪影草稿的完整路径前缀，草稿将以此作为路径。后续你只需要将草稿导入该路径后，就可以直接打开使用。
              </div>
            </div>
            
            <div style="margin-bottom: 20px;">
              <div style="font-weight: 500; margin-bottom: 12px; color: #111827;">如何获取剪影草稿路径：</div>
              <div style="margin-bottom: 12px;">
                <img src="http://ailive.perseids.cn/upload/assert/how_to_get_jianying_draft_path.jpg" 
                     alt="如何获取剪影草稿路径" 
                     style="width: 60%; border-radius: 8px; border: 1px solid #e5e7eb; cursor: pointer;"
                     onclick="window.open(this.src, '_blank')">
              </div>
              <div style="margin-bottom: 12px;">
                <img src="http://ailive.perseids.cn/upload/assert/where_is_jianying_draft_path.png" 
                     alt="剪影草稿路径位置" 
                     style="width: 60%; border-radius: 8px; border: 1px solid #e5e7eb; cursor: pointer;"
                     onclick="window.open(this.src, '_blank')">
              </div>
            </div>
            
            <div style="display: flex; gap: 8px; justify-content: flex-end;">
              <button class="mini-btn btn-secondary" id="cancelExportBtn" type="button">取消</button>
              <button class="btn btn-primary" id="confirmExportBtn" type="button">开始导出</button>
            </div>
          </div>
        </div>
      `;
      
      document.body.appendChild(dialog);
      
      const pathInput = dialog.querySelector('#draftPathInput');
      const confirmBtn = dialog.querySelector('#confirmExportBtn');
      const cancelBtn = dialog.querySelector('#cancelExportBtn');
      
      const closeDialog = () => {
        dialog.classList.remove('show');
        setTimeout(() => dialog.remove(), 300);
      };
      
      cancelBtn.addEventListener('click', closeDialog);
      dialog.querySelectorAll('.modal-close').forEach(btn => {
        btn.addEventListener('click', closeDialog);
      });
      
      confirmBtn.addEventListener('click', async () => {
        const draftPath = pathInput.value.trim();
        if (!draftPath) {
          showToast('请输入草稿路径', 'error');
          return;
        }
        
        // 保存路径到cookie，有效期3个月（90天）
        setCookie('jianying_draft_path', draftPath, 90);
        
        closeDialog();
        
        // 准备时间轴数据
        const sortedClips = [...state.timeline.clips].sort((a, b) => a.order - b.order);
        const timelineData = sortedClips.map(clip => ({
          url: clip.url,
          name: clip.name,
          duration: clip.duration,
          startTime: clip.startTime || 0,
          endTime: clip.endTime || clip.duration
        }));
        
        // 获取工作流名称
        const workflowName = document.querySelector('.brand-title')?.textContent || '未命名工作流';
        
        try {
          showToast('正在导出草稿，请稍候...', 'info');
          
          const response = await fetch('/api/export_timeline_draft', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-User-Id': window.USER_ID || '1'
            },
            body: JSON.stringify({
              draft_path: draftPath,
              timeline_clips: timelineData,
              workflow_name: workflowName
            })
          });
          
          const result = await response.json();
          console.log('导出结果:', result);
          
          if (response.ok && result.success) {
            showToast('草稿导出成功，正在下载...', 'success');
            
            // 自动触发下载
            if (result.download_url) {
              console.log('下载URL:', result.download_url);
              console.log('文件名:', result.zip_filename);
              
              // 使用window.location.href直接下载，更可靠
              window.location.href = result.download_url;
              
              setTimeout(() => {
                showToast('草稿已下载: ' + result.zip_filename, 'success');
              }, 1000);
            } else {
              console.warn('没有返回下载URL');
              showToast('草稿导出成功，但未返回下载链接', 'warning');
            }
          } else {
            showToast('导出失败: ' + (result.error || '未知错误'), 'error');
          }
        } catch (error) {
          console.error('导出草稿失败:', error);
          showToast('导出失败: ' + error.message, 'error');
        }
      });
      
      dialog.addEventListener('click', (e) => {
        if (e.target === dialog) {
          closeDialog();
        }
      });
    }
    
    // ============ 时间轴功能结束 ============
