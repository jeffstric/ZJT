    // ============ 时间轴功能 ============
    
    // ============ 柱子(Pillar)系统 ============
    // 柱子是时间轴的基本分区单位，每个柱子对应一个分镜(shot)
    // 柱子标识格式: {scriptId}_{shotNumber}
    // 视频和音频片段只能在对应的柱子内移动，不允许跨柱子
    
    /**
     * 创建或更新柱子
     * @param {number} scriptId - 剧本节点ID
     * @param {number} shotNumber - 分镜编号
     * @param {number} defaultDuration - 默认时长（来自分镜组最长时长）
     * @returns {object} 柱子对象
     */
    function createOrUpdatePillar(scriptId, shotNumber, defaultDuration) {
      const pillarId = `${scriptId}_${shotNumber}`;
      let pillar = state.timeline.pillars.find(p => p.id === pillarId);
      
      if (!pillar) {
        // 创建新柱子
        pillar = {
          id: pillarId,
          scriptId: scriptId,
          shotNumber: shotNumber,
          defaultDuration: defaultDuration || 15,
          videoClipIds: [],      // 该柱子内的视频片段ID列表
          audioClipIds: [],      // 该柱子内的音频片段ID列表
        };
        state.timeline.pillars.push(pillar);
        console.log(`[柱子系统] 创建柱子: ${pillarId}, 默认时长: ${defaultDuration}秒`);
      } else {
        // 更新现有柱子的默认时长
        pillar.defaultDuration = defaultDuration || pillar.defaultDuration;
      }
      
      return pillar;
    }
    
    /**
     * 获取柱子的实际时长（考虑内部片段）
     * @param {object} pillar - 柱子对象
     * @returns {number} 实际时长（秒）
     */
    function getPillarActualDuration(pillar) {
      if (!pillar) return 0;
      
      // 计算视频轨道的时长
      let videoTrackDuration = 0;
      pillar.videoClipIds.forEach(clipId => {
        const clip = state.timeline.clips.find(c => c.id === clipId);
        if (clip) {
          const actualDuration = (clip.endTime || clip.duration) - (clip.startTime || 0);
          videoTrackDuration += actualDuration;
        }
      });
      
      // 计算音频轨道的时长
      let audioTrackDuration = 0;
      pillar.audioClipIds.forEach(clipId => {
        const clip = state.timeline.audioClips.find(c => c.id === clipId);
        if (clip) {
          const actualDuration = (clip.endTime || clip.duration) - (clip.startTime || 0);
          audioTrackDuration += actualDuration;
        }
      });
      
      // 优先使用实际媒体时长（视频和音频的最大值）
      // 只有在完全没有媒体时，才使用默认时长作为占位
      if (videoTrackDuration > 0 || audioTrackDuration > 0) {
        return Math.max(videoTrackDuration, audioTrackDuration);
      }
      return pillar.defaultDuration;
    }
    
    /**
     * 根据节点信息获取对应的柱子
     * @param {number} nodeId - 节点ID
     * @returns {object|null} 柱子对象或null
     */
    function getPillarForNode(nodeId) {
      const node = state.nodes.find(n => n.id === nodeId);
      if (!node) {
        return null;
      }
      
      let scriptId = null;
      let shotNumber = null;
      
      // 如果是视频节点，需要找到它的父节点（分镜节点或图生视频节点）
      if (node.type === 'video') {
        // 优先查找普通连接（分镜节点生成视频时使用的是普通连接）
        const normalConn = state.connections.find(c => c.to === nodeId);
        if (normalConn) {
          const parentNode = state.nodes.find(n => n.id === normalConn.from);
          if (parentNode) {
            // 递归查找父节点的柱子
            return getPillarForNode(parentNode.id);
          }
        }
        
        // 查找视频连接（从分镜节点或图生视频节点到视频节点）
        const videoConn = state.videoConnections.find(c => c.to === nodeId);
        if (videoConn) {
          const parentNode = state.nodes.find(n => n.id === videoConn.from);
          if (parentNode) {
            // 递归查找父节点的柱子
            return getPillarForNode(parentNode.id);
          }
        }
        
        // 如果没有视频连接，尝试查找图片连接（图生视频的情况）
        const imageConn = state.imageConnections.find(c => c.to === nodeId);
        if (imageConn) {
          const parentNode = state.nodes.find(n => n.id === imageConn.from);
          if (parentNode) {
            return getPillarForNode(parentNode.id);
          }
        }
        
        return null;
      }
      
      // 如果是图生视频节点，查找它的父节点（分镜节点）
      if (node.type === 'image_to_video') {
        const imageConn = state.imageConnections.find(c => c.to === nodeId);
        if (imageConn) {
          const parentNode = state.nodes.find(n => n.id === imageConn.from);
          if (parentNode) {
            return getPillarForNode(parentNode.id);
          }
        }
        return null;
      }
      
      // 如果是分镜节点
      if (node.type === 'shot_frame') {
        // 兼容两种数据结构：shotData（新）和 shotJson（旧）
        const shotInfo = node.data.shotData || node.data.shotJson;
        
        if (shotInfo) {
          shotNumber = shotInfo.shot_number;
          
          // 查找父分镜组节点
          const parentConn = state.connections.find(c => c.to === nodeId);
          
          if (parentConn) {
            const shotGroupNode = state.nodes.find(n => n.id === parentConn.from);
            
            if (shotGroupNode && shotGroupNode.type === 'shot_group') {
              // 查找祖父剧本节点
              const grandParentConn = state.connections.find(c => c.to === shotGroupNode.id);
              
              if (grandParentConn) {
                const scriptNode = state.nodes.find(n => n.id === grandParentConn.from);
                
                if (scriptNode && scriptNode.type === 'script') {
                  scriptId = scriptNode.id;
                }
              }
            }
          }
        }
      }
      
      // 如果是对话组节点
      if (node.type === 'dialogue_group' && node.data.shotNumber) {
        shotNumber = node.data.shotNumber;
        // 查找关联的剧本节点（通过分镜节点连接）
        const incomingConns = state.connections.filter(c => c.to === nodeId);
        for (const conn of incomingConns) {
          const sourceNode = state.nodes.find(n => n.id === conn.from);
          if (sourceNode && sourceNode.type === 'shot_frame') {
            const pillar = getPillarForNode(sourceNode.id);
            if (pillar) return pillar;
          }
        }
      }
      
      if (scriptId && shotNumber) {
        const pillarId = `${scriptId}_${shotNumber}`;
        const pillar = state.timeline.pillars.find(p => p.id === pillarId);
        return pillar;
      }
      
      return null;
    }
    
    /**
     * 将片段添加到柱子
     * @param {object} pillar - 柱子对象
     * @param {number} clipId - 片段ID
     * @param {string} trackType - 轨道类型 ('video' 或 'audio')
     */
    function addClipToPillar(pillar, clipId, trackType) {
      if (!pillar) return;
      
      if (trackType === 'video') {
        if (!pillar.videoClipIds.includes(clipId)) {
          pillar.videoClipIds.push(clipId);
          console.log(`[柱子系统] 添加视频片段 ${clipId} 到柱子 ${pillar.id}`);
        }
      } else if (trackType === 'audio') {
        if (!pillar.audioClipIds.includes(clipId)) {
          pillar.audioClipIds.push(clipId);
          console.log(`[柱子系统] 添加音频片段 ${clipId} 到柱子 ${pillar.id}`);
        }
      }
    }
    
    /**
     * 从柱子移除片段
     * @param {number} clipId - 片段ID
     * @param {string} trackType - 轨道类型 ('video' 或 'audio')
     */
    function removeClipFromPillar(clipId, trackType) {
      state.timeline.pillars.forEach(pillar => {
        if (trackType === 'video') {
          pillar.videoClipIds = pillar.videoClipIds.filter(id => id !== clipId);
        } else if (trackType === 'audio') {
          pillar.audioClipIds = pillar.audioClipIds.filter(id => id !== clipId);
        }
      });
    }
    
    /**
     * 获取片段所属的柱子
     * @param {number} clipId - 片段ID
     * @param {string} trackType - 轨道类型 ('video' 或 'audio')
     * @returns {object|null} 柱子对象或null
     */
    function getPillarForClip(clipId, trackType) {
      return state.timeline.pillars.find(pillar => {
        if (trackType === 'video') {
          return pillar.videoClipIds.includes(clipId);
        } else if (trackType === 'audio') {
          return pillar.audioClipIds.includes(clipId);
        }
        return false;
      });
    }
    
    /**
     * 检查片段是否可以移动到目标位置（柱子约束检查）
     * @param {number} clipId - 片段ID
     * @param {number} targetClipId - 目标片段ID
     * @param {string} trackType - 轨道类型
     * @returns {boolean} 是否允许移动
     */
    function canMoveClipTo(clipId, targetClipId, trackType) {
      const sourcePillar = getPillarForClip(clipId, trackType);
      const targetPillar = getPillarForClip(targetClipId, trackType);
      
      // 如果没有柱子系统，允许自由移动（向后兼容）
      if (!sourcePillar && !targetPillar) return true;
      
      // 只能在同一个柱子内移动
      return sourcePillar && targetPillar && sourcePillar.id === targetPillar.id;
    }
    
    /**
     * 自动迁移历史数据：扫描画布上的剧本节点，创建缺失的柱子
     * 用于兼容旧版工作流
     */
    function autoMigratePillars() {
      // 如果已经有柱子，不需要迁移
      if (state.timeline.pillars.length > 0) {
        console.log('[柱子迁移] 已存在柱子数据，跳过迁移');
        return false;
      }
      
      // 查找所有剧本节点
      const scriptNodes = state.nodes.filter(n => n.type === 'script' && n.data.parsedData);
      
      if (scriptNodes.length === 0) {
        console.log('[柱子迁移] 未找到已解析的剧本节点');
        return false;
      }
      
      let totalPillarsCreated = 0;
      
      scriptNodes.forEach(scriptNode => {
        const scriptId = scriptNode.id;
        const parsedData = scriptNode.data.parsedData;
        const maxGroupDuration = parsedData.max_group_duration || 15;
        
        if (parsedData.shot_groups && Array.isArray(parsedData.shot_groups)) {
          parsedData.shot_groups.forEach((shotGroup) => {
            if (shotGroup.shots && Array.isArray(shotGroup.shots)) {
              shotGroup.shots.forEach((shot) => {
                if (shot.shot_number) {
                  createOrUpdatePillar(scriptId, shot.shot_number, shot.duration || maxGroupDuration);
                  totalPillarsCreated++;
                }
              });
            }
          });
        }
      });
      
      if (totalPillarsCreated > 0) {
        console.log(`[柱子迁移] 成功迁移：为 ${scriptNodes.length} 个剧本节点创建了 ${totalPillarsCreated} 个柱子`);
        state.timeline.visible = true;
        return true;
      }
      
      return false;
    }
    
    // ============ 柱子系统结束 ============
    
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
      // 尝试获取节点对应的柱子
      let pillar = getPillarForNode(nodeId);
      
      // 如果找不到柱子，尝试自动迁移历史数据
      if (!pillar) {
        const migrated = autoMigratePillars();
        
        if (migrated) {
          // 迁移成功后重新查找柱子
          pillar = getPillarForNode(nodeId);
          if (pillar) {
            showToast('已自动迁移历史数据到新时间轴结构', 'success');
          }
        }
      }
      
      // 如果还是找不到柱子，说明该节点不属于任何剧本
      if (!pillar) {
        showToast('该视频节点未关联到剧本分镜，请先解析剧本', 'warning');
        return;
      }
      
      // 计算该片段在柱子内的order（基于柱子内已有片段数量）
      const pillarClipCount = pillar.videoClipIds.length;
      
      const clip = {
        id: state.timeline.nextClipId++,
        nodeId: nodeId,
        url: node.data.url,
        name: node.data.name || '视频',
        duration: duration,
        startTime: 0,           // 剪切开始时间（秒）
        endTime: duration,      // 剪切结束时间（秒）
        order: pillarClipCount, // 在柱子内的顺序
        pillarId: pillar.id,    // 所属柱子ID
      };
      
      state.timeline.clips.push(clip);
      addClipToPillar(pillar, clip.id, 'video');
      state.timeline.visible = true;
      
      renderTimeline();
      showToast(`已添加到时间轴 - 镜头${pillar.shotNumber}`, 'success');
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
      // 从柱子中移除
      removeClipFromPillar(clipId, 'video');
      
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
      const audioTrack = document.getElementById('audioTrack');
      const ruler = document.getElementById('timelineRuler');
      const totalDurationEl = document.getElementById('timelineTotalDuration');
      const expandBtn = document.getElementById('timelineExpandBtn');
      
      // 如果有柱子系统，即使没有片段也显示时间轴（显示空柱子）
      const hasPillars = state.timeline.pillars.length > 0;
      const hasClips = state.timeline.clips.length > 0 || state.timeline.audioClips.length > 0;
      
      if (!state.timeline.visible) {
        container.style.display = 'none';
        expandBtn.style.display = 'flex';
        canvasContainer.classList.remove('timeline-visible');
        return;
      }
      
      container.style.display = 'flex';
      expandBtn.style.display = 'none';
      canvasContainer.classList.add('timeline-visible');

      if (!hasPillars && !hasClips) {
        track.innerHTML = '';
        audioTrack.innerHTML = '';
        ruler.innerHTML = '';
        totalDurationEl.textContent = '总时长: 0:00';
        return;
      }
      
      // 如果有柱子系统，按柱子渲染；否则按原有方式渲染
      if (hasPillars) {
        renderTimelineWithPillars(container, track, audioTrack, ruler, totalDurationEl);
      } else {
        renderTimelineClassic(container, track, audioTrack, ruler, totalDurationEl);
      }
      
      bindTimelineClipEvents();
      bindAudioClipEvents();
    }
    
    // 经典渲染模式（向后兼容）
    function renderTimelineClassic(container, track, audioTrack, ruler, totalDurationEl) {
      // 计算视频总时长（考虑剪切后的实际播放时长）
      const videoTotalDuration = state.timeline.clips.reduce((sum, c) => {
        const actualDuration = (c.endTime || c.duration) - (c.startTime || 0);
        return sum + actualDuration;
      }, 0);
      
      // 计算音频总时长
      const audioTotalDuration = state.timeline.audioClips.reduce((sum, c) => {
        const actualDuration = (c.endTime || c.duration) - (c.startTime || 0);
        return sum + actualDuration;
      }, 0);
      
      // 使用较长的时长作为总时长
      const totalDuration = Math.max(videoTotalDuration, audioTotalDuration);
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
      
      // 渲染音频轨道（经典模式）
      renderAudioTrackClassic(audioTrack, totalDuration);
    }
    
    // 基于柱子的渲染模式
    function renderTimelineWithPillars(container, track, audioTrack, ruler, totalDurationEl) {
      // 按shotNumber排序柱子
      const sortedPillars = [...state.timeline.pillars].sort((a, b) => {
        if (a.scriptId !== b.scriptId) return a.scriptId - b.scriptId;
        return a.shotNumber - b.shotNumber;
      });
      
      // 计算每个柱子的位置和总时长
      let accumulatedTime = 0;
      const pillarPositions = new Map(); // pillarId -> {startTime, duration}
      
      sortedPillars.forEach(pillar => {
        const duration = getPillarActualDuration(pillar);
        pillarPositions.set(pillar.id, {
          startTime: accumulatedTime,
          duration: duration
        });
        accumulatedTime += duration;
      });
      
      const totalDuration = accumulatedTime;
      const minutes = Math.floor(totalDuration / 60);
      const seconds = (totalDuration % 60).toFixed(2);
      totalDurationEl.textContent = `总时长: ${minutes}:${seconds.padStart(5, '0')} (柱子模式)`;
      
      renderTimelineRuler(ruler, totalDuration);
      
      // 渲染视频轨道（带柱子分隔）
      let videoTrackHTML = '';
      
      // 先渲染柱子背景
      sortedPillars.forEach((pillar, index) => {
        const pos = pillarPositions.get(pillar.id);
        const bgColor = index % 2 === 0 ? 'rgba(59, 130, 246, 0.05)' : 'rgba(99, 102, 241, 0.05)';
        const borderColor = index % 2 === 0 ? 'rgba(59, 130, 246, 0.2)' : 'rgba(99, 102, 241, 0.2)';
        
        videoTrackHTML += `
          <div class="timeline-pillar-bg" 
               data-pillar-id="${pillar.id}"
               style="position: absolute; 
                      left: ${pos.startTime * 10}px; 
                      width: ${pos.duration * 10}px; 
                      height: 100%; 
                      background: ${bgColor};
                      border-left: 2px solid ${borderColor};
                      border-right: 2px solid ${borderColor};
                      pointer-events: none;
                      z-index: 0;">
            <div style="position: absolute; top: 2px; left: 4px; font-size: 10px; color: rgba(100,100,100,0.6); pointer-events: none;">
              镜头${pillar.shotNumber} (${pos.duration.toFixed(1)}s)
            </div>
          </div>
        `;
      });
      
      // 渲染视频片段
      sortedPillars.forEach(pillar => {
        const pillarPos = pillarPositions.get(pillar.id);
        let pillarClipTime = 0;
        
        // 获取该柱子内的片段并按order排序
        const pillarClips = pillar.videoClipIds
          .map(id => state.timeline.clips.find(c => c.id === id))
          .filter(c => c)
          .sort((a, b) => a.order - b.order);
        
        pillarClips.forEach(clip => {
          const clipStartTime = clip.startTime || 0;
          const clipEndTime = clip.endTime || clip.duration;
          const actualDuration = clipEndTime - clipStartTime;
          const width = actualDuration * 10;
          const absoluteLeft = (pillarPos.startTime + pillarClipTime) * 10;
          pillarClipTime += actualDuration;
          
          const isTrimmed = clipStartTime > 0 || clipEndTime < clip.duration;
          const durationText = isTrimmed ? `${actualDuration.toFixed(1)}s (已剪切)` : `${actualDuration}s`;
          
          videoTrackHTML += `
            <div class="timeline-clip ${state.timeline.selectedClipId === clip.id ? 'selected' : ''}" 
                 data-clip-id="${clip.id}"
                 data-pillar-id="${pillar.id}"
                 draggable="true"
                 style="position: absolute; left: ${absoluteLeft}px; width: ${width}px; z-index: 1;">
              <video class="timeline-clip-thumb" src="${proxyDownloadUrl(clip.url)}" muted preload="metadata"></video>
              <div class="timeline-clip-name" title="${clip.name}">${clip.name}</div>
              <div class="timeline-clip-duration">${durationText}</div>
              <div class="timeline-clip-actions">
                <button class="vp-btn clip-trim-btn" title="剪切">✂</button>
                <button class="vp-btn clip-remove-btn" title="移除">×</button>
              </div>
            </div>
          `;
        });
      });
      
      track.innerHTML = videoTrackHTML;
      track.style.minWidth = (totalDuration * 10 + 24) + 'px';
      
      // 渲染音频轨道（带柱子分隔）
      renderAudioTrackWithPillars(audioTrack, sortedPillars, pillarPositions, totalDuration);
    }
    
    // 渲染音频轨道（经典模式）
    function renderAudioTrackClassic(audioTrack, totalDuration) {
      const sortedAudioClips = [...state.timeline.audioClips].sort((a, b) => a.order - b.order);
      let accumulatedAudioTime = 0;
      audioTrack.innerHTML = sortedAudioClips.map(clip => {
        const startTime = accumulatedAudioTime;
        const clipStartTime = clip.startTime || 0;
        const clipEndTime = clip.endTime || clip.duration;
        const actualDuration = clipEndTime - clipStartTime;
        const width = actualDuration * 10;
        accumulatedAudioTime += actualDuration;
        
        const durationText = `${actualDuration.toFixed(1)}s`;
        
        return `
          <div class="timeline-audio-clip ${state.timeline.selectedAudioClipId === clip.id ? 'selected' : ''}" 
               data-audio-clip-id="${clip.id}" 
               draggable="true"
               style="position: absolute; left: ${startTime * 10}px; width: ${width}px;">
            <div class="timeline-audio-clip-waveform">
              <svg viewBox="0 0 100 40" preserveAspectRatio="none">
                <path d="M0,20 ${Array.from({length: 20}, (_, i) => {
                  const x = i * 5;
                  const h = 5 + Math.random() * 15;
                  return `L${x},${20-h} L${x},${20+h}`;
                }).join(' ')} L100,20" fill="none" stroke="rgba(255,255,255,0.8)" stroke-width="1"/>
              </svg>
            </div>
            <div class="timeline-clip-name" title="${clip.name}">${clip.name}</div>
            <div class="timeline-clip-duration">${durationText}</div>
            <div class="timeline-clip-actions">
              <button class="vp-btn audio-clip-remove-btn" title="移除">×</button>
            </div>
          </div>
        `;
      }).join('');
      
      audioTrack.style.minWidth = (totalDuration * 10 + 24) + 'px';
    }
    
    // 渲染音频轨道（柱子模式）
    function renderAudioTrackWithPillars(audioTrack, sortedPillars, pillarPositions, totalDuration) {
      let audioTrackHTML = '';
      
      // 先渲染柱子背景
      sortedPillars.forEach((pillar, index) => {
        const pos = pillarPositions.get(pillar.id);
        const bgColor = index % 2 === 0 ? 'rgba(59, 130, 246, 0.05)' : 'rgba(99, 102, 241, 0.05)';
        const borderColor = index % 2 === 0 ? 'rgba(59, 130, 246, 0.2)' : 'rgba(99, 102, 241, 0.2)';
        
        audioTrackHTML += `
          <div class="timeline-pillar-bg" 
               data-pillar-id="${pillar.id}"
               style="position: absolute; 
                      left: ${pos.startTime * 10}px; 
                      width: ${pos.duration * 10}px; 
                      height: 100%; 
                      background: ${bgColor};
                      border-left: 2px solid ${borderColor};
                      border-right: 2px solid ${borderColor};
                      pointer-events: none;
                      z-index: 0;">
          </div>
        `;
      });
      
      // 渲染音频片段
      sortedPillars.forEach(pillar => {
        const pillarPos = pillarPositions.get(pillar.id);
        let pillarClipTime = 0;
        
        // 获取该柱子内的音频片段并按order排序
        const pillarClips = pillar.audioClipIds
          .map(id => state.timeline.audioClips.find(c => c.id === id))
          .filter(c => c)
          .sort((a, b) => a.order - b.order);
        
        pillarClips.forEach(clip => {
          const clipStartTime = clip.startTime || 0;
          const clipEndTime = clip.endTime || clip.duration;
          const actualDuration = clipEndTime - clipStartTime;
          const width = actualDuration * 10;
          const absoluteLeft = (pillarPos.startTime + pillarClipTime) * 10;
          pillarClipTime += actualDuration;
          
          const durationText = `${actualDuration.toFixed(1)}s`;
          
          audioTrackHTML += `
            <div class="timeline-audio-clip ${state.timeline.selectedAudioClipId === clip.id ? 'selected' : ''}" 
                 data-audio-clip-id="${clip.id}"
                 data-pillar-id="${pillar.id}"
                 draggable="true"
                 style="position: absolute; left: ${absoluteLeft}px; width: ${width}px; z-index: 1;">
              <div class="timeline-audio-clip-waveform">
                <svg viewBox="0 0 100 40" preserveAspectRatio="none">
                  <path d="M0,20 ${Array.from({length: 20}, (_, i) => {
                    const x = i * 5;
                    const h = 5 + Math.random() * 15;
                    return `L${x},${20-h} L${x},${20+h}`;
                  }).join(' ')} L100,20" fill="none" stroke="rgba(255,255,255,0.8)" stroke-width="1"/>
                </svg>
              </div>
              <div class="timeline-clip-name" title="${clip.name}">${clip.name}</div>
              <div class="timeline-clip-duration">${durationText}</div>
              <div class="timeline-clip-actions">
                <button class="vp-btn audio-clip-remove-btn" title="移除">×</button>
              </div>
            </div>
          `;
        });
      });
      
      audioTrack.innerHTML = audioTrackHTML;
      audioTrack.style.minWidth = (totalDuration * 10 + 24) + 'px';
    }
    
    // 渲染时间刻度
    function renderTimelineRuler(ruler, totalDuration) {
      // 添加左侧占位（60px，与轨道标签宽度一致）+ 刻度内容
      let html = '<div style="display: flex;">';
      html += '<div style="width: 60px; min-width: 60px; flex-shrink: 0;"></div>'; // 左侧占位
      html += '<div style="position: relative; flex: 1; min-width: max-content;">';
      
      const interval = totalDuration > 60 ? 10 : 5;
      
      // 渲染主刻度（带标签）
      for (let i = 0; i <= totalDuration; i += interval) {
        const minutes = Math.floor(i / 60);
        const seconds = i % 60;
        const label = `${minutes}:${seconds.toString().padStart(2, '0')}`;
        html += `
          <div class="ruler-mark" style="left:${i * 10}px;">
            <div class="ruler-tick ruler-tick-major"></div>
            <div class="ruler-label">${label}</div>
          </div>
        `;
      }
      
      // 渲染次刻度（小刻度线，无标签）
      const minorInterval = interval === 10 ? 2 : 1; // 主刻度10秒时，次刻度2秒；主刻度5秒时，次刻度1秒
      for (let i = minorInterval; i <= totalDuration; i += minorInterval) {
        // 跳过主刻度位置
        if (i % interval !== 0) {
          html += `
            <div class="ruler-mark-minor" style="left:${i * 10}px;">
              <div class="ruler-tick ruler-tick-minor"></div>
            </div>
          `;
        }
      }
      
      html += '</div></div>';
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
          
          // 柱子约束检查：只能在同一个柱子内移动
          if (!canMoveClipTo(draggedClipId, clipId, 'video')) {
            e.dataTransfer.dropEffect = 'none';
            clipEl.classList.remove('drop-target');
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
          
          // 柱子约束检查：只能在同一个柱子内移动
          if (!canMoveClipTo(draggedClipId, clipId, 'video')) {
            showToast('不能跨柱子移动视频片段', 'warning');
            dropPosition = null;
            return;
          }
          
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
        
        // 准备时间轴数据 - 包含视频和音频
        const sortedClips = [...state.timeline.clips].sort((a, b) => a.order - b.order);
        const videoClipsData = sortedClips.map(clip => ({
          url: clip.url,
          name: clip.name,
          duration: clip.duration,
          startTime: clip.startTime || 0,
          endTime: clip.endTime || clip.duration,
          pillarId: clip.pillarId || null
        }));
        
        // 准备音频数据
        const sortedAudioClips = [...state.timeline.audioClips].sort((a, b) => a.order - b.order);
        const audioClipsData = sortedAudioClips.map(clip => ({
          url: clip.url,
          name: clip.name,
          duration: clip.duration,
          startTime: clip.startTime || 0,
          endTime: clip.endTime || clip.duration,
          pillarId: clip.pillarId || null
        }));
        
        // 准备柱子数据（用于处理不连续的视频）
        const pillarsData = state.timeline.pillars.map(pillar => ({
          id: pillar.id,
          scriptId: pillar.scriptId,
          shotNumber: pillar.shotNumber,
          defaultDuration: pillar.defaultDuration,
          videoClipIds: pillar.videoClipIds,
          audioClipIds: pillar.audioClipIds
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
              video_clips: videoClipsData,
              audio_clips: audioClipsData,
              pillars: pillarsData,
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
    
    // 绑定音频片段事件
    function bindAudioClipEvents() {
      const audioTrack = document.getElementById('audioTrack');
      if (!audioTrack) return;
      
      audioTrack.querySelectorAll('.timeline-audio-clip').forEach(clipEl => {
        const clipId = Number(clipEl.dataset.audioClipId);
        
        clipEl.addEventListener('click', (e) => {
          if(e.target.classList.contains('audio-clip-remove-btn')) return;
          state.timeline.selectedAudioClipId = clipId;
          renderTimeline();
        });
        
        const removeBtn = clipEl.querySelector('.audio-clip-remove-btn');
        if(removeBtn){
          removeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            removeAudioFromTimeline(clipId);
          });
        }
      });
    }
    
    // ============ 音频时间轴功能 ============
    
    // 添加音频到时间轴
    function addAudioToTimeline(nodeId, dialogueIndex, audioUrl, audioName, duration) {
      if (!audioUrl) {
        showToast('音频URL无效', 'error');
        return;
      }
      
      // 尝试获取节点对应的柱子
      let pillar = getPillarForNode(nodeId);
      
      // 如果找不到柱子，尝试自动迁移历史数据
      if (!pillar) {
        const migrated = autoMigratePillars();
        
        if (migrated) {
          // 迁移成功后重新查找柱子
          pillar = getPillarForNode(nodeId);
          if (pillar) {
            showToast('已自动迁移历史数据到新时间轴结构', 'success');
          }
        }
      }
      
      // 如果还是找不到柱子，说明该节点不属于任何剧本
      if (!pillar) {
        showToast('该音频节点未关联到剧本分镜，请先解析剧本', 'warning');
        return;
      }
      
      // 计算该片段在柱子内的order（基于柱子内已有片段数量）
      const pillarClipCount = pillar.audioClipIds.length;
      
      const clip = {
        id: state.timeline.nextAudioClipId++,
        nodeId: nodeId,
        dialogueIndex: dialogueIndex,
        url: audioUrl,
        name: audioName || '音频',
        duration: duration || 5,
        startTime: 0,
        endTime: duration || 5,
        order: pillarClipCount, // 在柱子内的顺序
        pillarId: pillar.id,    // 所属柱子ID
      };
      
      state.timeline.audioClips.push(clip);
      addClipToPillar(pillar, clip.id, 'audio');
      state.timeline.visible = true;
      
      renderTimeline();
      showToast(`已添加音频到时间轴 - 镜头${pillar.shotNumber}`, 'success');
      try{ autoSaveWorkflow(); } catch(e){}
    }
    
    // 从时间轴移除音频片段
    function removeAudioFromTimeline(clipId) {
      // 从柱子中移除
      removeClipFromPillar(clipId, 'audio');
      
      state.timeline.audioClips = state.timeline.audioClips.filter(c => c.id !== clipId);
      state.timeline.audioClips.forEach((c, i) => c.order = i);
      renderTimeline();
      showToast('已从时间轴移除音频', 'success');
      try{ autoSaveWorkflow(); } catch(e){}
    }
    
    // 移动音频片段（拖拽排序）
    function moveAudioClip(clipId, newOrder) {
      const clip = state.timeline.audioClips.find(c => c.id === clipId);
      if (!clip) return;
      
      const oldOrder = clip.order;
      if (oldOrder === newOrder) return;
      
      state.timeline.audioClips.forEach(c => {
        if (c.id === clipId) {
          c.order = newOrder;
        } else if (oldOrder < newOrder && c.order > oldOrder && c.order <= newOrder) {
          c.order--;
        } else if (oldOrder > newOrder && c.order >= newOrder && c.order < oldOrder) {
          c.order++;
        }
      });
      
      state.timeline.audioClips.sort((a, b) => a.order - b.order);
      renderTimeline();
      try{ autoSaveWorkflow(); } catch(e){}
    }
    
    // 获取音频时长
    function getAudioDuration(url) {
      return new Promise((resolve, reject) => {
        const audio = document.createElement('audio');
        audio.preload = 'metadata';
        
        audio.addEventListener('loadedmetadata', () => {
          if (audio.duration && isFinite(audio.duration)) {
            resolve(Math.round(audio.duration * 10) / 10);
          } else {
            reject(new Error('Invalid duration'));
          }
          audio.src = '';
        }, { once: true });
        
        audio.addEventListener('error', () => {
          reject(new Error('Failed to load audio'));
        }, { once: true });
        
        audio.src = proxyDownloadUrl(url);
      });
    }
    
    // ============ 音频时间轴功能结束 ============
    
    // ============ 时间轴功能结束 ============
