// ============ 垃圾桶（回收站）模块 ============
// 删除的节点/时间轴片段在此暂存，随 workflow_data 持久化（serializeWorkflow 的 trash 字段），
// 跨会话可恢复。服务端媒体文件本就永不删除（上传素材 policy=never_expire），
// 恢复只需重建数据引用，无需任何后端配合。
// 依赖：state.js（state/canvasEl/showToast）、timeline.js（renderTimeline/柱子函数）、
//       workflow.js（restoreNode/stripLargeDataUrls）、canvas.js（renderAllConnections/renderMinimap/focusOnNode）。

const TRASH_ITEM_LIMIT = 50;          // 上限，超出 FIFO 淘汰最旧
const TRASH_TRACK_LIMIT = 6;          // 与时间轴多轨上限一致（timeline_tracks.js TT_MAX_TRACKS）
const TRASH_KIND_NODE = 'node';                       // 整节点删除（含连线/片段快照）
const TRASH_KIND_CLIPS = 'timeline-clips';            // 时间轴片段删除
const TRASH_KIND_CLEAR = 'timeline-clear';            // 清空时间轴

// ---- 序列化辅助（与 serializeWorkflow 相同口径清洗节点 data）----

function _trashSafeClone(value){
  try { return JSON.parse(JSON.stringify(value)); } catch(e){ return null; }
}

// 剔除 File 对象与 blob: 临时地址（与 workflow.js serializeWorkflow 的节点 data 清洗一致）
function _trashCleanNodeData(data){
  if(!data || typeof data !== 'object') return {};
  const cleaned = { ...data };
  ['file','startFile','endFile','videoFile','refAudioFile'].forEach(k => {
    if(cleaned[k]) delete cleaned[k];
  });
  ['url','startUrl','endUrl','lastFrameUrl','videoUrl'].forEach(k => {
    if(typeof cleaned[k] === 'string' && cleaned[k].startsWith('blob:')) cleaned[k] = '';
  });
  ['audioUrls','videoUrls'].forEach(k => {
    if(Array.isArray(cleaned[k])){
      cleaned[k] = cleaned[k].map(item =>
        (item && item.url && item.url.startsWith('blob:')) ? { ...item, url: '' } : item);
    }
  });
  if(typeof stripLargeDataUrls === 'function') return stripLargeDataUrls(cleaned, 0);
  return cleaned;
}

function _trashSerializeNode(node){
  return {
    id: node.id,
    type: node.type,
    title: node.title,
    x: node.x,
    y: node.y,
    data: _trashCleanNodeData(node.data)
  };
}

// ---- 删除副作用补丁 ----
// removeNode 会连带清掉"邻居节点"上的字段（清首尾帧/参考图/音色/水印输入等）。
// 删除前把原值抓下来，恢复节点时回填，保证撤销后邻居节点的引用一并还原。

function _trashPatchField(patch, node, key){
  if(node.data && node.data[key] !== undefined) patch.fields[key] = node.data[key];
}

function _trashCaptureNeighborPatches(nodeId){
  const patches = [];
  const seen = new Set();

  const pushPatch = (targetNode, fields, hooks) => {
    if(!targetNode || seen.has(targetNode.id)) return;
    if(!fields || Object.keys(fields).length === 0) return;
    seen.add(targetNode.id);
    patches.push({ nodeId: targetNode.id, fields, hooks: hooks || [] });
  };

  // 图生视频节点：图片连接清掉的 start/end/ref 帧
  state.imageConnections.filter(c => c.from === nodeId || c.to === nodeId).forEach(c => {
    const t = state.nodes.find(n => n.id === (c.from === nodeId ? c.to : c.from));
    if(!t || t.type !== 'image_to_video') return;
    const fields = {};
    if(c.from === nodeId){
      if(c.portType === 'start'){ _trashPatchField(fields, t, 'startUrl'); _trashPatchField(fields, t, 'startPreview'); }
      else if(c.portType === 'end'){ _trashPatchField(fields, t, 'endUrl'); _trashPatchField(fields, t, 'endPreview'); }
      else if(c.portType === 'ref-image'){ fields.referenceUrls = (t.data.referenceUrls || []).slice(); }
    }
    pushPatch(t, fields, ['_updateStartFrame','_updateEndFrame','_updateReferencePreview']);
  });

  // 图生视频节点：视频/音频连接清掉的 videoUrls/audioUrls
  (state.videoConnections || []).filter(c => c.from === nodeId).forEach(c => {
    const t = state.nodes.find(n => n.id === c.to);
    if(t && t.type === 'image_to_video') pushPatch(t, { videoUrls: (t.data.videoUrls || []).slice() });
  });
  (state.audioConnections || []).filter(c => c.from === nodeId && !c.portType).forEach(c => {
    const t = state.nodes.find(n => n.id === c.to);
    if(t && t.type === 'image_to_video') pushPatch(t, { audioUrls: (t.data.audioUrls || []).slice() });
  });

  // 分镜节点：尾帧来源被删时清掉的 lastFrameUrl
  (state.lastFrameConnections || []).filter(c => c.from === nodeId).forEach(c => {
    const t = state.nodes.find(n => n.id === c.to);
    if(t && t.type === 'shot_frame') pushPatch(t, { lastFrameUrl: t.data.lastFrameUrl || '' }, ['_updateLastFrame']);
  });

  // 文字转语音节点：音色来源被删时清掉的引用音色（refAudioFile 是 File 对象无法持久化，恢复后为空可重新应用音色）
  (state.audioConnections || []).filter(c => c.from === nodeId && c.portType === 'voice').forEach(c => {
    const t = state.nodes.find(n => n.id === c.to);
    if(t && typeof t.clearConnectedVoice === 'function'){
      pushPatch(t, {
        voiceFromConnection: t.data.voiceFromConnection || false,
        voiceSourceName: t.data.voiceSourceName || '',
        refAudioUrl: t.data.refAudioUrl || '',
        engine: t.data.engine || 'voice_library'
      });
    }
  });

  // 去水印节点：上游视频节点被删时 clearVideoInput 清掉的输入
  state.connections.filter(c => c.from === nodeId).forEach(c => {
    const t = state.nodes.find(n => n.id === c.to);
    if(t && typeof t.clearVideoInput === 'function' && t.data && t.data.videoUrl !== undefined){
      pushPatch(t, {
        videoUrl: t.data.videoUrl || '',
        videoName: t.data.videoName || '',
        sourceNodeId: t.data.sourceNodeId !== undefined ? t.data.sourceNodeId : null,
        sourceDuration: t.data.sourceDuration !== undefined ? t.data.sourceDuration : null,
        durationOutOfRange: !!t.data.durationOutOfRange,
        durationUserSet: !!t.data.durationUserSet
      });
    }
  });

  return patches;
}

// ---- 入桶 ----

function _trashPush(kind, title, thumbUrl, payload){
  const item = {
    id: state.trash.nextItemId++,
    kind,
    title: String(title || ''),
    thumbUrl: thumbUrl || '',
    deletedAt: new Date().toISOString(),
    payload
  };
  state.trash.items.push(item);
  while(state.trash.items.length > TRASH_ITEM_LIMIT){
    state.trash.items.shift();
  }
  updateTrashBadge();
  return item;
}

// 节点删除前调用（removeNode 第一行）：快照节点+连线+时间轴片段+分组+邻居补丁
function pushNodeDeletionToTrash(node){
  if(!node) return null;
  const nodeId = node.id;
  const connections = {
    connections: state.connections.filter(c => c.from === nodeId || c.to === nodeId).map(_trashSafeClone),
    imageConnections: state.imageConnections.filter(c => c.from === nodeId || c.to === nodeId).map(_trashSafeClone),
    firstFrameConnections: (state.firstFrameConnections || []).filter(c => c.from === nodeId || c.to === nodeId).map(_trashSafeClone),
    lastFrameConnections: (state.lastFrameConnections || []).filter(c => c.from === nodeId || c.to === nodeId).map(_trashSafeClone),
    videoConnections: (state.videoConnections || []).filter(c => c.from === nodeId || c.to === nodeId).map(_trashSafeClone),
    referenceConnections: (state.referenceConnections || []).filter(c => c.from === nodeId || c.to === nodeId).map(_trashSafeClone),
    audioConnections: (state.audioConnections || []).filter(c => c.from === nodeId || c.to === nodeId).map(_trashSafeClone)
  };
  const videoClips = state.timeline.clips.filter(c => c.nodeId === nodeId).map(_trashSafeClone);
  const groupIds = state.groups.filter(g => g.nodeIds.includes(nodeId)).map(g => g.id);
  const thumb = (node.data && (node.data.url || node.data.videoUrl)) || (typeof getNodeImageUrl === 'function' ? getNodeImageUrl(node) : '') || '';
  const item = _trashPush(TRASH_KIND_NODE,
    node.title || (node.data && node.data.name) || `节点 ${nodeId}`,
    typeof proxyDownloadUrl === 'function' && thumb && !thumb.startsWith('blob:') ? thumb : '',
    {
      node: _trashSerializeNode(node),
      connections,
      videoClips,
      groupIds,
      neighborPatches: _trashCaptureNeighborPatches(nodeId)
    });
  showTrashUndoToast(`已删除「${item.title}」，可在垃圾桶恢复`, item.id);
  return item;
}

// 时间轴片段删除前调用（removeFromTimeline/removeAudioFromTimeline/清空）
function pushTimelineClipsToTrash(videoClips, audioClips, title){
  const clips = (videoClips || []).map(_trashSafeClone);
  const audio = (audioClips || []).map(_trashSafeClone);
  if(clips.length === 0 && audio.length === 0) return null;
  const item = _trashPush(
    clips.length + audio.length === 1 ? TRASH_KIND_CLIPS : TRASH_KIND_CLEAR,
    title || (clips.length + audio.length === 1
      ? (clips[0] || audio[0]).name
      : `${clips.length + audio.length} 个片段`),
    '',
    { videoClips: clips, audioClips: audio });
  showTrashUndoToast(`已删除时间轴片段，可在垃圾桶恢复`, item.id);
  return item;
}

// ---- 恢复 ----

const TRASH_CONN_ARRAYS = [
  ['connections', 'nextConnId'],
  ['imageConnections', 'nextImgConnId'],
  ['firstFrameConnections', 'nextFirstFrameConnId'],
  ['lastFrameConnections', 'nextLastFrameConnId'],
  ['videoConnections', 'nextVideoConnId'],
  ['referenceConnections', 'nextReferenceConnId'],
  ['audioConnections', 'nextAudioConnId']
];

function _trashRestoreConnections(saved){
  if(!saved) return 0;
  let restored = 0;
  TRASH_CONN_ARRAYS.forEach(([arrayName, counterName]) => {
    const list = saved[arrayName] || [];
    list.forEach(conn => {
      if(!conn || conn.id == null || conn.from == null || conn.to == null) return;
      const arr = state[arrayName];
      if(!Array.isArray(arr)) return;
      // 端点节点必须都存在（对端可能已被单独删除）
      if(!state.nodes.some(n => n.id === conn.from) || !state.nodes.some(n => n.id === conn.to)) return;
      if(arr.some(c => c.id === conn.id)) return;
      arr.push(_trashSafeClone(conn));
      restored++;
      if(state[counterName] != null && conn.id >= state[counterName]) state[counterName] = conn.id + 1;
    });
  });
  return restored;
}

// 片段恢复：重映射 id 防碰撞；柱子已清则落 __free__ 并追加到时间轴末尾
function _trashRestoreClips(clones, trackType){
  const isVideo = trackType === 'video';
  const clipsArr = isVideo ? state.timeline.clips : state.timeline.audioClips;
  const nextIdRef = isVideo ? 'nextClipId' : 'nextAudioClipId';
  let restored = 0;
  (clones || []).forEach(savedClip => {
    if(!savedClip || !savedClip.url) return;
    const clip = _trashSafeClone(savedClip);
    clip.id = state.timeline[nextIdRef]++;

    let pillar = state.timeline.pillars.find(p => p.id === clip.pillarId);
    if(!pillar){
      if(typeof getOrCreateFreePillar === 'function') pillar = getOrCreateFreePillar();
      clip.pillarId = pillar ? pillar.id : '__free__';
    }
    if(pillar){
      const idsKey = isVideo ? 'videoClipIds' : 'audioClipIds';
      if(!pillar[idsKey].includes(clip.id)) pillar[idsKey].push(clip.id);
      clip.order = pillar[idsKey].length - 1;
    }

    // v2 绝对定位：柱子未变则保留原位置；否则追加到时间轴末尾第一个空闲轨
    if(typeof clip.start !== 'number' || clip.pillarId !== savedClip.pillarId){
      if(typeof placeClipAtTimelineEnd === 'function') placeClipAtTimelineEnd(clip, isVideo ? 'video' : 'audio');
    }
    const trackCountKey = isVideo ? 'videoTrackCount' : 'audioTrackCount';
    if(typeof clip.track === 'number' && clip.track >= state.timeline[trackCountKey]){
      state.timeline[trackCountKey] = Math.min(clip.track + 1, TRASH_TRACK_LIMIT);
      clip.track = Math.min(clip.track, state.timeline[trackCountKey] - 1);
    }

    clipsArr.push(clip);
    restored++;
  });
  return restored;
}

function _trashApplyNeighborPatches(patches){
  (patches || []).forEach(patch => {
    const node = state.nodes.find(n => n.id === patch.nodeId);
    if(!node || !patch.fields) return;
    Object.assign(node.data, patch.fields);
    if(typeof node.updateReferenceImages === 'function') node.updateReferenceImages();
    const el = canvasEl.querySelector(`.node[data-node-id="${patch.nodeId}"]`);
    (patch.hooks || []).forEach(hook => {
      if(el && typeof el[hook] === 'function'){
        try { el[hook](); } catch(e) { console.warn('[垃圾桶] 邻居节点刷新钩子失败:', hook, e); }
      }
    });
  });
}

function restoreTrashItem(itemId){
  const idx = state.trash.items.findIndex(it => it.id === itemId);
  if(idx === -1) return false;
  const item = state.trash.items[idx];
  const payload = item.payload || {};

  try {
    if(item.kind === TRASH_KIND_NODE){
      const nodeData = _trashSafeClone(payload.node);
      if(!nodeData) throw new Error('快照数据损坏');
      if(state.nodes.some(n => n.id === nodeData.id)) {
        showToast('画布上已存在相同编号的节点，无法恢复', 'error');
        return false;
      }
      restoreNode(nodeData);
      if(nodeData.id >= state.nextNodeId) state.nextNodeId = nodeData.id + 1;

      _trashRestoreConnections(payload.connections);
      const restoredClips = _trashRestoreClips(payload.videoClips || [], 'video');

      (payload.groupIds || []).forEach(gid => {
        const g = state.groups.find(x => x.id === gid);
        if(g && !g.nodeIds.includes(nodeData.id)){
          g.nodeIds.push(nodeData.id);
          if(typeof recalcGroupBounds === 'function') recalcGroupBounds(g);
        }
      });

      _trashApplyNeighborPatches(payload.neighborPatches || []);

      renderTimeline();
      renderAllConnections();
      renderMinimap();
      safeAutoSave();
      if(typeof focusOnNode === 'function') focusOnNode(nodeData.id);
      showToast(`已恢复「${item.title}」${restoredClips ? `及 ${restoredClips} 个时间轴片段` : ''}`, 'success');
    } else {
      // 时间轴片段 / 清空恢复
      const restoredV = _trashRestoreClips(payload.videoClips || [], 'video');
      const restoredA = _trashRestoreClips(payload.audioClips || [], 'audio');
      state.timeline.visible = true;
      renderTimeline();
      safeAutoSave();
      showToast(`已恢复 ${restoredV} 个视频片段、${restoredA} 个音频片段`, 'success');
    }

    // 恢复成功后从垃圾桶移除
    state.trash.items.splice(idx, 1);
    updateTrashBadge();
    renderTrashModalIfOpen();
    return true;
  } catch(e) {
    console.error('[垃圾桶] 恢复失败:', e);
    showToast('恢复失败：' + (e.message || '未知错误'), 'error');
    return false;
  }
}

function purgeTrashItem(itemId){
  const idx = state.trash.items.findIndex(it => it.id === itemId);
  if(idx === -1) return false;
  state.trash.items.splice(idx, 1);
  updateTrashBadge();
  renderTrashModalIfOpen();
  safeAutoSave();
  return true;
}

function clearTrashItems(){
  if(state.trash.items.length === 0) return;
  state.trash.items = [];
  state.trash.nextItemId = 1;
  updateTrashBadge();
  renderTrashModalIfOpen();
  safeAutoSave();
}

// 撤销最近一次删除（浮动提示条按钮调用）
function undoLastTrash(){
  const latest = state.trash.items[state.trash.items.length - 1];
  if(!latest){
    showToast('垃圾桶为空', 'info');
    return;
  }
  restoreTrashItem(latest.id);
}

// ---- 撤销浮动提示条 ----

let _trashUndoTimer = null;
function showTrashUndoToast(message, itemId){
  let bar = document.getElementById('trashUndoBar');
  if(!bar){
    bar = document.createElement('div');
    bar.id = 'trashUndoBar';
    bar.style.cssText = 'position:fixed;left:50%;bottom:76px;transform:translateX(-50%);' +
      'background:#111827;color:#fff;padding:10px 14px;border-radius:10px;font-size:13px;' +
      'display:flex;align-items:center;gap:12px;z-index:10000;box-shadow:0 8px 24px rgba(0,0,0,0.35);';
    const msg = document.createElement('span');
    msg.id = 'trashUndoMsg';
    bar.appendChild(msg);
    const btn = document.createElement('button');
    btn.id = 'trashUndoBtn';
    btn.textContent = '撤销';
    btn.style.cssText = 'background:#3b82f6;color:#fff;border:none;border-radius:6px;padding:4px 12px;cursor:pointer;font-size:12px;';
    btn.addEventListener('click', () => {
      hideTrashUndoToast();
      undoLastTrash();
    });
    bar.appendChild(btn);
    document.body.appendChild(bar);
  }
  const msg = bar.querySelector('#trashUndoMsg');
  if(msg) msg.textContent = message;
  bar.style.display = 'flex';
  if(_trashUndoTimer) clearTimeout(_trashUndoTimer);
  _trashUndoTimer = setTimeout(hideTrashUndoToast, 6000);
}

function hideTrashUndoToast(){
  const bar = document.getElementById('trashUndoBar');
  if(bar) bar.style.display = 'none';
  if(_trashUndoTimer){ clearTimeout(_trashUndoTimer); _trashUndoTimer = null; }
}

// ---- 垃圾桶弹窗 ----

const TRASH_KIND_LABELS = {
  [TRASH_KIND_NODE]: '节点',
  [TRASH_KIND_CLIPS]: '片段',
  [TRASH_KIND_CLEAR]: '批量'
};

function _trashFormatTime(iso){
  try {
    const d = new Date(iso);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch(e){ return ''; }
}

function renderTrashModalIfOpen(){
  const modal = document.getElementById('trashModal');
  if(modal && modal.classList.contains('show')) renderTrashModalList();
}

function renderTrashModalList(){
  const listEl = document.getElementById('trashModalList');
  const countEl = document.getElementById('trashModalCount');
  if(!listEl) return;
  const items = state.trash.items;
  if(countEl) countEl.textContent = `${items.length} 项`;

  if(items.length === 0){
    listEl.innerHTML = '<div class="trash-empty">垃圾桶是空的</div>';
    return;
  }

  // 最新的在上
  listEl.innerHTML = items.slice().reverse().map(item => `
    <div class="trash-item" data-item-id="${item.id}">
      <div class="trash-item-thumb">
        ${item.thumbUrl
          ? `<img src="${escapeHtmlAttr(proxyDownloadUrl(item.thumbUrl))}" alt="" onerror="this.style.display='none'">`
          : `<span class="trash-item-icon">${escapeHtml(TRASH_KIND_LABELS[item.kind] || '项')}</span>`}
      </div>
      <div class="trash-item-info">
        <div class="trash-item-title" title="${escapeHtmlAttr(item.title)}">${escapeHtml(item.title)}</div>
        <div class="trash-item-meta">${escapeHtml(TRASH_KIND_LABELS[item.kind] || '项')} · 删除于 ${escapeHtml(_trashFormatTime(item.deletedAt))}</div>
      </div>
      <div class="trash-item-actions">
        <button class="mini-btn btn-success trash-restore-btn" data-item-id="${item.id}">恢复</button>
        <button class="mini-btn btn-danger trash-purge-btn" data-item-id="${item.id}">彻底删除</button>
      </div>
    </div>
  `).join('');

  listEl.querySelectorAll('.trash-restore-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      restoreTrashItem(Number(btn.dataset.itemId));
    });
  });
  listEl.querySelectorAll('.trash-purge-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      purgeTrashItem(Number(btn.dataset.itemId));
    });
  });
}

function openTrashModal(){
  let modal = document.getElementById('trashModal');
  if(!modal){
    modal = document.createElement('div');
    modal.id = 'trashModal';
    modal.className = 'modal';
    modal.innerHTML = `
      <div class="modal-card" style="max-width: 560px;">
        <div class="modal-header">
          <div class="modal-title">垃圾桶</div>
          <span class="trash-count" id="trashModalCount"></span>
          <button class="modal-close" type="button" aria-label="关闭">×</button>
        </div>
        <div class="modal-body" style="padding: 12px 16px;">
          <div class="trash-hint">删除的节点和时间轴片段会暂存在这里（最多 ${TRASH_ITEM_LIMIT} 条，超出自动淘汰最早的），恢复后回到原位置；被恢复节点的原连线也会一并还原。</div>
          <div class="trash-list" id="trashModalList"></div>
          <div style="display:flex;justify-content:flex-end;margin-top:12px;">
            <button class="mini-btn btn-danger" id="trashClearAllBtn">清空垃圾桶</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.querySelector('.modal-close').addEventListener('click', () => modal.classList.remove('show'));
    modal.addEventListener('click', (e) => { if(e.target === modal) modal.classList.remove('show'); });
    modal.querySelector('#trashClearAllBtn').addEventListener('click', () => {
      if(state.trash.items.length === 0) return;
      showConfirmModal('确定要清空垃圾桶吗？清空后无法再恢复。', { confirmText: '清空' }).then(ok => {
        if(ok) clearTrashItems();
      });
    });
  }
  renderTrashModalList();
  modal.classList.add('show');
}

// ---- 角标 ----

function updateTrashBadge(){
  const count = state.trash.items.length;
  document.querySelectorAll('.trash-badge').forEach(badge => {
    badge.textContent = count > 99 ? '99+' : String(count);
    badge.style.display = count > 0 ? 'flex' : 'none';
  });
}

// ---- 持久化 ----

function serializeTrashForPersist(){
  const cloned = _trashSafeClone({ items: state.trash.items, nextItemId: state.trash.nextItemId });
  if(!cloned) return { items: [], nextItemId: 1 };
  cloned.items = cloned.items.slice(0, TRASH_ITEM_LIMIT);
  return cloned;
}

function restoreTrashData(data){
  const src = data && typeof data === 'object' ? data : {};
  state.trash.items = Array.isArray(src.items) ? src.items.slice(0, TRASH_ITEM_LIMIT) : [];
  state.trash.nextItemId = Number(src.nextItemId) || (state.trash.items.reduce((m, it) => Math.max(m, Number(it.id) || 0), 0) + 1);
  updateTrashBadge();
}
