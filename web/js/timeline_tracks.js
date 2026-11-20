// ============ 时间轴 v2 多轨模块（剪映式） ============
// 渲染与交互：多轨（视频/音频各最多 6 轨）、绝对定位拖拽、边缘裁剪、播放头分割、
// Ctrl 多选、缩放（Ctrl+滚轮/按钮）、播放预览（预览窗 + raf 播放头 + 音视频调度）、
// 插入素材（节点按钮/工具栏导入/OS 文件拖入）。
// 数据层（clip.start/track、迁移、放置算法）在 timeline.js；垃圾桶在 timeline_trash.js。
// 该模块通过 renderTimeline() -> window.TimelineTracks.render() 被调用。

const TT_MAX_TRACKS = 6;      // 视频/音频各自的最大轨数
const TT_LABEL_W = 72;        // 左侧轨标签宽度（与 CSS --tt-label-w 保持一致）
const TT_SNAP_PX = 8;         // 吸附阈值（像素）
const TT_PANEL_H_DEFAULT = 340;  // 面板默认高度（px）
const TT_PANEL_H_MIN = 200;      // 面板最小高度
const TT_PANEL_H_KEY = 'tt_panel_height_px';  // localStorage 键（本机 UI 偏好，不进 workflow_data）

// ---- 面板高度（拖拉把手） ----
// 高度收口在 CSS 变量 --tt-panel-h：面板本体、画布让位、minimap/zoom 浮层都引用它
function ttApplyPanelHeight(h) {
  document.documentElement.style.setProperty('--tt-panel-h', Math.round(h) + 'px');
}

function ttClampPanelHeight(h) {
  const max = Math.max(TT_PANEL_H_MIN + 80, window.innerHeight - 160);
  return Math.min(Math.max(TT_PANEL_H_MIN, Math.round(h)), max);
}

function ttInitPanelHeight() {
  const saved = Number(localStorage.getItem(TT_PANEL_H_KEY));
  if (saved >= TT_PANEL_H_MIN) ttApplyPanelHeight(ttClampPanelHeight(saved));
}

function ttBindResizeHandle() {
  const handle = document.getElementById('ttResizeHandle');
  const container = document.getElementById('timelineContainer');
  if (!handle || !container || handle._ttBound) return;
  handle._ttBound = true;

  handle.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const startY = e.clientY;
    const startH = container.getBoundingClientRect().height;
    handle.classList.add('dragging');
    document.body.classList.add('tt-resizing');

    const onMove = (ev) => {
      // 向上拖 = 变高（面板贴屏底）
      ttApplyPanelHeight(ttClampPanelHeight(startH + (startY - ev.clientY)));
    };
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      handle.classList.remove('dragging');
      document.body.classList.remove('tt-resizing');
      ttHideContextMenu();
      const h = ttClampPanelHeight(container.getBoundingClientRect().height);
      ttApplyPanelHeight(h);
      localStorage.setItem(TT_PANEL_H_KEY, String(h));
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, { once: true });
  });

  // 双击恢复默认高度
  handle.addEventListener('dblclick', (e) => {
    e.stopPropagation();
    ttApplyPanelHeight(TT_PANEL_H_DEFAULT);
    localStorage.setItem(TT_PANEL_H_KEY, String(TT_PANEL_H_DEFAULT));
  });
}

// 页面加载即应用上次的面板高度（脚本在 body 底部，DOM 已就绪）
ttInitPanelHeight();
ttBindResizeHandle();

// ---- 几何/数据辅助 ----

function ttGetZoom() {
  return state.timeline.zoom || 40;
}

function ttSetZoom(newPx) {
  state.timeline.zoom = Math.min(200, Math.max(10, Math.round(newPx)));
}

// 吸附候选点：0、播放头、所有片段的起止（跨轨收集）
function ttSnapCandidates() {
  const pts = [0, state.timeline.playhead || 0];
  const collect = (arr) => arr.forEach(c => {
    if (typeof c.start !== 'number') return;
    pts.push(c.start, c.start + clipVisualDuration(c));
  });
  collect(state.timeline.clips);
  collect(state.timeline.audioClips);
  return pts;
}

// 计算吸附：返回 {start, snapAt}——snapAt 为命中的吸附线时间点（未命中为 null）。
// 音频片段对"视频片段边缘"的吸附给更大的阈值（磁吸优先，方便对齐视频分段口）。
function ttComputeSnap(startSec, durationSec, type, excludeId) {
  const px = ttGetZoom();
  let threshold = TT_SNAP_PX / px;
  if (type === 'audio') threshold = Math.max(threshold, 12 / px); // 音频磁吸阈值放宽到 12px
  const cands = ttSnapCandidates();
  let best = null;
  cands.forEach(pt => {
    // 片段起点对齐候选点
    const d1 = Math.abs(startSec - pt);
    if (d1 < threshold && (best === null || d1 < best.d)) best = { d: d1, v: pt, snapAt: pt };
    // 片段终点对齐候选点
    const endSec = startSec + durationSec;
    const d2 = Math.abs(endSec - pt);
    if (d2 < threshold && (best === null || d2 < best.d)) best = { d: d2, v: pt - durationSec, snapAt: pt };
  });
  if (best && best.v >= -0.01) return { start: Math.max(0, best.v), snapAt: best.snapAt };
  return { start: startSec, snapAt: null };
}

// 吸附指示线（磁吸命中时的垂直参考线）
function ttShowSnapIndicator(snapAt) {
  let line = document.getElementById('ttSnapIndicator');
  if (!line) {
    line = document.createElement('div');
    line.id = 'ttSnapIndicator';
    line.className = 'tt-snap-indicator';
    document.getElementById('ttTracksInner').appendChild(line);
  }
  line.style.display = 'block';
  line.style.left = (TT_LABEL_W + snapAt * ttGetZoom()) + 'px';
}

function ttHideSnapIndicator() {
  const line = document.getElementById('ttSnapIndicator');
  if (line) line.style.display = 'none';
}

function ttFindClip(type, id) {
  const arr = type === 'video' ? state.timeline.clips : state.timeline.audioClips;
  return arr.find(c => c.id === id);
}

function ttPauseIfPlaying() {
  if (state.timeline.playing) pauseTimelinePlayback();
}

// i18n 安全取值：key 未收录时 t() 会原样返回 key，此处回退到默认中文
function ttT(key, fallback) {
  if (window.t) {
    const v = window.t(key);
    if (v && v !== key) return v;
  }
  return fallback;
}

// ---- 选择 ----

function ttIsSelected(type, id) {
  return (state.timeline.selectedClipIds || []).some(s => s.type === type && s.id === id);
}

function ttSyncLegacySelection() {
  state.timeline.selectedClipId = null;
  state.timeline.selectedAudioClipId = null;
  (state.timeline.selectedClipIds || []).forEach(s => {
    if (s.type === 'video') state.timeline.selectedClipId = s.id;
    else state.timeline.selectedAudioClipId = s.id;
  });
}

function ttHandleSelectionClick(type, id, ctrlKey) {
  if (ctrlKey) {
    const idx = state.timeline.selectedClipIds.findIndex(s => s.type === type && s.id === id);
    if (idx >= 0) state.timeline.selectedClipIds.splice(idx, 1);
    else state.timeline.selectedClipIds.push({ type, id });
  } else {
    state.timeline.selectedClipIds = [{ type, id }];
  }
  ttSyncLegacySelection();
  ttUpdateSelectionUI();
}

function ttClearSelection() {
  state.timeline.selectedClipIds = [];
  ttSyncLegacySelection();
  ttUpdateSelectionUI();
}

function ttUpdateSelectionUI() {
  const inner = document.getElementById('ttTracksInner');
  if (!inner) return;
  inner.querySelectorAll('.tt-clip.selected').forEach(el => el.classList.remove('selected'));
  (state.timeline.selectedClipIds || []).forEach(s => {
    const el = inner.querySelector(`.tt-clip[data-clip-type="${s.type}"][data-clip-id="${s.id}"]`);
    if (el) el.classList.add('selected');
  });
}

// ---- 主渲染入口 ----

function ttRender() {
  ttPauseIfPlaying();
  const inner = document.getElementById('ttTracksInner');
  const ruler = document.getElementById('timelineRuler');
  const totalEl = document.getElementById('timelineTotalDuration');
  if (!inner || !ruler) return;

  if (!state.timeline.selectedClipIds) state.timeline.selectedClipIds = [];
  state.timeline.videoTrackCount = Math.min(TT_MAX_TRACKS, Math.max(1, state.timeline.videoTrackCount || 1));
  state.timeline.audioTrackCount = Math.min(TT_MAX_TRACKS, Math.max(1, state.timeline.audioTrackCount || 1));

  const px = ttGetZoom();
  const totalDur = getTimelineTotalDuration();
  const widthSec = Math.max(totalDur + 10, 30);
  const contentW = Math.round(widthSec * px);

  let html = ttRenderGroup('video', contentW);
  html += ttRenderGroup('audio', contentW);
  html += `<div class="tt-playhead" id="ttPlayhead"><div class="tt-playhead-line"></div><div class="tt-playhead-grip"></div></div>`;
  inner.innerHTML = html;
  inner.style.width = (TT_LABEL_W + contentW) + 'px';

  ttRenderRuler(ruler, px, widthSec);
  ttUpdateTotalDurationDisplay(totalEl, totalDur);
  ttUpdatePlayheadUI();
  ttUpdateTimecode();
  ttBindEvents();
  ttUpdatePlayBtnState();
  ttSyncPreviewAtPlayhead();
  ttCapturePillarGeometry();
}

function ttRenderGroup(type, contentW) {
  const px = ttGetZoom();
  const countKey = type === 'video' ? 'videoTrackCount' : 'audioTrackCount';
  const count = state.timeline[countKey];
  const labelName = type === 'video' ? '视频' : '音频';

  let html = `<div class="tt-group tt-group-${type}" data-group-type="${type}">`;
  for (let i = 0; i < count; i++) {

    const clips = (type === 'video' ? state.timeline.clips : state.timeline.audioClips)
      .filter(c => (c.track || 0) === i)
      .sort((a, b) => (a.start || 0) - (b.start || 0));
    const bands = ttComputePillarBands(clips);
    const bandHtml = bands.map(b => `
      <div class="tt-pillar-band ${b.isFree ? 'tt-band-free' : ''}"
           data-pillar-id="${escapeHtmlAttr(b.pillarId)}"
           data-script-id="${escapeHtmlAttr(b.scriptId != null ? String(b.scriptId) : '')}"
           data-shot-number="${b.shotNumber != null ? b.shotNumber : ''}"
           style="left:${b.start * px}px;width:${Math.max(2, (b.end - b.start) * px)}px;">
        <span class="tt-pillar-label">${escapeHtml(b.label)}</span>
      </div>
    `).join('');
    const clipsHtml = clips.map(c => ttRenderClip(c, type, px)).join('');
    html += `
      <div class="tt-lane tt-lane-${type}" data-track-type="${type}" data-track-index="${i}">
        <div class="tt-lane-label">${labelName} ${i + 1}${count > 1 ? `<button class="tt-lane-del" data-lane-del="${type}" data-track="${i}" title="删除此空轨道" aria-label="删除${labelName}轨道${i + 1}">×</button>` : ''}</div>
        <div class="tt-lane-content" style="width:${contentW}px">${bandHtml}${clipsHtml}</div>
      </div>
    `;
  }
  // 轨道未满时渲染"添加轨道"存根行：可点击加轨，也可作为拖放目标
  if (count < TT_MAX_TRACKS) {
    html += `
      <div class="tt-add-stub" data-add-stub="${type}" title="点击添加一轨，或把片段拖到这里">
        ＋ 添加${labelName}轨道
      </div>
    `;
  }
  html += `</div>`;
  return html;
}

// 柱子背景色带：按该轨片段所属柱子聚合 min/max 范围
function ttComputePillarBands(laneClips) {
  const byPillar = new Map();
  laneClips.forEach(c => {
    const pid = c.pillarId;
    if (!pid) return;
    const start = c.start || 0;
    const end = start + clipVisualDuration(c);
    if (!byPillar.has(pid)) {
      const pillar = state.timeline.pillars.find(p => p.id === pid);
      byPillar.set(pid, {
        pillarId: pid,
        scriptId: pillar ? pillar.scriptId : null,
        shotNumber: pillar ? pillar.shotNumber : null,
        isFree: pid === '__free__',
        label: pid === '__free__' ? ttT('timeline_free_clips', '独立片段')
          : (pillar ? `镜头${pillar.shotNumber}` : ''),
        start, end
      });
    } else {
      const b = byPillar.get(pid);
      b.start = Math.min(b.start, start);
      b.end = Math.max(b.end, end);
    }
  });
  return [...byPillar.values()];
}

function ttRenderClip(clip, type, px) {
  const dur = clipVisualDuration(clip);
  const w = Math.max(10, Math.round(dur * px));
  const selected = ttIsSelected(type, clip.id) ? 'selected' : '';
  const name = clip.name || (type === 'video' ? '视频' : '音频');
  const thumb = type === 'video'
    ? `<video class="timeline-clip-thumb" src="${escapeHtmlAttr(proxyDownloadUrl(clip.url))}" muted preload="metadata"></video>`
    : `<div class="tt-audio-wave"><svg viewBox="0 0 100 40" preserveAspectRatio="none"><path d="M0,20 ${Array.from({ length: 20 }, (_, i) => {
        const x = i * 5;
        const h = 5 + ((clip.id * 7 + i * 13) % 15);
        return `L${x},${20 - h} L${x},${20 + h}`;
      }).join(' ')} L100,20" fill="none" stroke="rgba(255,255,255,0.75)" stroke-width="1"/></svg></div>`;
  return `
    <div class="tt-clip tt-clip-${type} ${selected}"
         data-clip-type="${type}" data-clip-id="${clip.id}"
         style="left:${clip.start * px}px;width:${w}px;">
      <div class="tt-trim tt-trim-l" data-dir="l" title="拖动裁剪起点"></div>
      ${thumb}
      <div class="timeline-clip-name" title="${escapeHtmlAttr(name)}">${escapeHtml(name)}</div>
      <div class="timeline-clip-duration">${dur.toFixed(1)}s</div>
      <div class="tt-trim tt-trim-r" data-dir="r" title="拖动裁剪终点"></div>
    </div>
  `;
}

function ttRenderRuler(ruler, px, widthSec) {
  let html = '<div class="tt-ruler-inner" style="width:' + (TT_LABEL_W + Math.round(widthSec * px)) + 'px;">';
  html += `<div class="tt-ruler-spacer"></div>`;
  html += `<div class="tt-ruler-content" style="width:${Math.round(widthSec * px)}px;">`;
  // 刻度密度随缩放自适应
  const interval = px >= 60 ? 1 : (px >= 24 ? 5 : 10);
  const minor = interval / 5;
  const fmt = (sec) => {
    const m = Math.floor(sec / 60);
    const s = Math.round(sec % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  };
  for (let i = 0; i <= widthSec; i += minor) {
    const isMajor = Math.abs(i / interval - Math.round(i / interval)) < 1e-6;
    if (isMajor) {
      html += `<div class="ruler-mark" style="left:${i * px}px;">
        <div class="ruler-tick ruler-tick-major"></div>
        <div class="ruler-label">${fmt(i)}</div>
      </div>`;
    } else {
      html += `<div class="ruler-mark-minor" style="left:${i * px}px;">
        <div class="ruler-tick ruler-tick-minor"></div>
      </div>`;
    }
  }
  html += '</div></div>';
  ruler.innerHTML = html;
}

function ttUpdateTotalDurationDisplay(totalEl, totalDur) {
  if (!totalEl) return;
  const m = Math.floor(totalDur / 60);
  const s = totalDur % 60;
  const str = `${m}:${s.toFixed(2).padStart(5, '0')}`;
  totalEl.textContent = (window.t ? window.t('timeline_total_duration', { duration: str }) : `总时长: ${str}`) + '（多轨模式）';
}

function ttFormatTimecode(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  const d = Math.floor((sec % 1) * 10);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${d}`;
}

function ttUpdateTimecode() {
  const el = document.getElementById('ttTimecode');
  if (!el) return;
  const total = getTimelineTotalDuration();
  el.textContent = `${ttFormatTimecode(state.timeline.playhead || 0)} / ${ttFormatTimecode(total)}`;
}

// ---- 播放头 ----

function ttUpdatePlayheadUI() {
  const ph = document.getElementById('ttPlayhead');
  if (!ph) return;
  ph.style.left = (TT_LABEL_W + (state.timeline.playhead || 0) * ttGetZoom()) + 'px';
  // 播放时自动横向跟随
  if (state.timeline.playing) {
    const scroll = document.getElementById('ttTracksScroll');
    if (scroll) {
      const target = (state.timeline.playhead || 0) * ttGetZoom();
      const viewLeft = scroll.scrollLeft;
      const viewRight = viewLeft + scroll.clientWidth - TT_LABEL_W;
      if (target > viewRight - 40 || target < viewLeft) {
        scroll.scrollLeft = Math.max(0, target - scroll.clientWidth * 0.3);
      }
    }
  }
}

function ttSetPlayhead(t) {
  ttPauseIfPlaying();
  state.timeline.playhead = Math.max(0, t);
  ttUpdatePlayheadUI();
  ttUpdateTimecode();
  ttSyncPreviewAtPlayhead();
}

// ---- 播放预览引擎 ----
// 用 setInterval(50ms) 驱动而非 rAF：后台/遮挡标签页 rAF 会被浏览器节流冻结，
// 定时器驱动保证播放头在任何环境下都推进（视频画面本身由 <video> 元素自行渲染）。

let ttPlayTimer = null;
let ttLastTick = null;
let ttCurrentVideoKey = null;
let ttCurrentVideoUrl = null;
const ttAudioPool = new Map(); // clipId -> audio element

function ttTogglePlay() {
  if (state.timeline.playing) {
    pauseTimelinePlayback();
  } else {
    ttStartPlayback();
  }
}

function ttStartPlayback() {
  const total = getTimelineTotalDuration();
  if (total <= 0) {
    showToast('时间轴为空，无法播放', 'info');
    return;
  }
  if ((state.timeline.playhead || 0) >= total - 0.05) {
    state.timeline.playhead = 0;
  }
  state.timeline.playing = true;
  ttUpdatePlayBtnState();
  ttLastTick = performance.now();
  ttActivateMediaAt(state.timeline.playhead, true);
  if (ttPlayTimer) clearInterval(ttPlayTimer);
  ttPlayTimer = setInterval(() => ttTick(performance.now()), 50);
}

function pauseTimelinePlayback() {
  state.timeline.playing = false;
  if (ttPlayTimer) { clearInterval(ttPlayTimer); ttPlayTimer = null; }
  const videoEl = document.getElementById('ttPreviewVideo');
  if (videoEl) videoEl.pause();
  ttAudioPool.forEach(el => el.pause());
  ttUpdatePlayBtnState();
  ttUpdateTimecode();
}

function ttStopPlayback() {
  pauseTimelinePlayback();
  ttSetPlayhead(0);
}

function ttTick(now) {
  if (!state.timeline.playing) return;
  const dt = Math.min(0.1, (now - ttLastTick) / 1000);
  ttLastTick = now;
  let t = (state.timeline.playhead || 0) + dt;
  const total = getTimelineTotalDuration();
  if (t >= total) {
    state.timeline.playhead = total;
    ttUpdatePlayheadUI();
    ttUpdateTimecode();
    pauseTimelinePlayback();
    ttSyncPreviewAtPlayhead();
    return;
  }
  state.timeline.playhead = t;
  ttUpdatePlayheadUI();
  ttUpdateTimecode();
  ttActivateMediaAt(t, true);
}

function ttUpdatePlayBtnState() {
  const btn = document.getElementById('ttPlayBtn');
  if (btn) btn.textContent = state.timeline.playing ? '⏸' : '▶';
}

// 预览窗同步到播放头位置（暂停/停止时显示该时刻帧）
function ttSyncPreviewAtPlayhead() {
  ttActivateMediaAt(state.timeline.playhead || 0, false);
}

// 调度预览媒体：视频取最上层活跃片段（轨号大的在上），音频多轨并行
function ttActivateMediaAt(t, playing) {
  const videoEl = document.getElementById('ttPreviewVideo');
  const emptyEl = document.getElementById('ttPreviewEmpty');
  if (!videoEl) return;

  const activeVideo = state.timeline.clips
    .filter(c => typeof c.start === 'number' && t >= c.start - 0.001 && t < c.start + clipVisualDuration(c))
    .sort((a, b) => (a.track || 0) - (b.track || 0));
  const top = activeVideo.length ? activeVideo[activeVideo.length - 1] : null;

  if (top) {
    if (emptyEl) emptyEl.style.display = 'none';
    videoEl.style.display = '';
    const key = `${top.id}:${top.url}`;
    const targetTime = Math.max(0, top.startTime + (t - top.start));
    if (ttCurrentVideoKey !== key) {
      ttCurrentVideoKey = key;
      const src = proxyDownloadUrl(top.url);
      // 同一源文件（如分割出的两段）不重复加载，只重新定位
      if (ttCurrentVideoUrl !== src) {
        ttCurrentVideoUrl = src;
        videoEl.src = src;
      }
      const onReady = () => {
        if (playing && videoEl.paused) videoEl.play().catch(() => {});
      };
      videoEl.addEventListener('seeked', onReady, { once: true });
      videoEl.addEventListener('loadeddata', onReady, { once: true });
      try { videoEl.currentTime = targetTime; } catch (e) {}
      if (!playing) videoEl.pause();
    } else {
      if (Math.abs(videoEl.currentTime - targetTime) > 0.35) {
        try { videoEl.currentTime = targetTime; } catch (e) {}
      }
      if (playing) {
        if (videoEl.paused) videoEl.play().catch(() => {});
      } else if (!videoEl.paused) {
        videoEl.pause();
      }
    }
  } else {
    ttCurrentVideoKey = null;
    ttCurrentVideoUrl = null;
    videoEl.pause();
    videoEl.style.display = 'none';
    if (emptyEl) emptyEl.style.display = '';
  }

  ttSyncAudioPool(t, playing);
}

function ttSyncAudioPool(t, playing) {
  const active = state.timeline.audioClips
    .filter(c => typeof c.start === 'number' && t >= c.start - 0.001 && t < c.start + clipVisualDuration(c));
  const activeIds = new Set(active.map(c => c.id));

  active.forEach(clip => {
    let el = ttAudioPool.get(clip.id);
    if (!el) {
      el = document.createElement('audio');
      el.src = proxyDownloadUrl(clip.url);
      el.preload = 'auto';
      ttAudioPool.set(clip.id, el);
    }
    const targetTime = Math.max(0, clip.startTime + (t - clip.start));
    if (Math.abs(el.currentTime - targetTime) > 0.35) {
      try { el.currentTime = targetTime; } catch (e) {}
    }
    if (playing && el.paused) el.play().catch(() => {});
    if (!playing && !el.paused) el.pause();
  });

  ttAudioPool.forEach((el, id) => {
    if (!activeIds.has(Number(id))) {
      el.pause();
      ttAudioPool.delete(id);
    }
  });
}

// ---- 事件绑定 ----

function ttBindEvents() {
  const inner = document.getElementById('ttTracksInner');
  const ruler = document.getElementById('timelineRuler');
  const scroll = document.getElementById('ttTracksScroll');
  if (!inner) return;

  // 片段：选中 / 拖拽移动 / 边缘裁剪 / 双击聚焦节点 / 右键菜单
  inner.querySelectorAll('.tt-clip').forEach(clipEl => {
    const type = clipEl.dataset.clipType;
    const id = Number(clipEl.dataset.clipId);
    const clip = ttFindClip(type, id);
    if (!clip) return;

    clipEl.querySelectorAll('.tt-trim').forEach(handle => {
      handle.addEventListener('pointerdown', (e) => ttStartTrim(e, clipEl, clip, handle.dataset.dir));
    });

    clipEl.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      if (e.target.classList.contains('tt-trim')) return;
      ttStartMove(e, clipEl, clip);
    });

    clipEl.addEventListener('dblclick', (e) => {
      e.stopPropagation();
      if (clip.nodeId && typeof focusOnNode === 'function') focusOnNode(clip.nodeId);
    });

    clipEl.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      e.stopPropagation();
      ttShowContextMenu(e.clientX, e.clientY, type, clip.id);
    });
  });

  // 柱子色带点击 → 跳转分镜节点（保留旧行为）
  inner.querySelectorAll('.tt-pillar-band').forEach(bandEl => {
    bandEl.addEventListener('click', (e) => {
      if (e.target.closest('.tt-clip')) return;
      const scriptId = Number(bandEl.dataset.scriptId);
      const shotNumber = Number(bandEl.dataset.shotNumber);
      if (!scriptId || !shotNumber || typeof getShotFrameNodeForPillar !== 'function') return;
      const shotFrameNode = getShotFrameNodeForPillar(scriptId, shotNumber);
      if (shotFrameNode && typeof focusOnNode === 'function') focusOnNode(shotFrameNode.id);
    });
  });

  // 轨道标签上的删除按钮（仅空轨可删，见 ttRemoveLane）
  inner.querySelectorAll('.tt-lane-del').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      ttRemoveLane(btn.dataset.laneDel, Number(btn.dataset.track));
    });
  });

  // "添加轨道"存根：点击直接加一轨
  inner.querySelectorAll('.tt-add-stub').forEach(stubEl => {
    stubEl.addEventListener('click', (e) => {
      e.stopPropagation();
      const type = stubEl.dataset.addStub;
      const countKey = type === 'video' ? 'videoTrackCount' : 'audioTrackCount';
      if (state.timeline[countKey] >= TT_MAX_TRACKS) return;
      state.timeline[countKey] += 1;
      renderTimeline();
      safeAutoSave();
    });
  });

  // 空白处点击：取消选择
  inner.querySelectorAll('.tt-lane-content').forEach(contentEl => {
    contentEl.addEventListener('pointerdown', (e) => {
      if (e.target === contentEl || e.target.classList.contains('tt-pillar-band')) {
        ttClearSelection();
      }
    });
  });

  // 刻度尺 / 滚动容器是持久元素：只绑定一次，避免每次渲染叠加监听
  if (ruler && !ruler._ttBound) {
    ruler._ttBound = true;
    ruler.addEventListener('pointerdown', (e) => {
      ttScrubFromEvent(e);
      const move = (ev) => ttScrubFromEvent(ev);
      const up = () => window.removeEventListener('pointermove', move);
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up, { once: true });
    });
  }

  if (scroll && !scroll._ttBound) {
    scroll._ttBound = true;
    // 轨道区横向滚动 → 同步刻度尺
    scroll.addEventListener('scroll', () => {
      const rulerInner = ruler ? ruler.querySelector('.tt-ruler-inner') : null;
      if (rulerInner) rulerInner.style.transform = `translateX(${-scroll.scrollLeft}px)`;
    });
    // Ctrl+滚轮缩放（以指针位置为锚点）
    scroll.addEventListener('wheel', (e) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const oldPx = ttGetZoom();
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      const newPx = Math.min(200, Math.max(10, Math.round(oldPx * factor)));
      if (newPx === oldPx) return;
      const rect = scroll.getBoundingClientRect();
      const pointerX = e.clientX - rect.left;
      const tAtPointer = (scroll.scrollLeft + pointerX - TT_LABEL_W) / oldPx;
      ttSetZoom(newPx);
      renderTimeline();
      const scrollEl = document.getElementById('ttTracksScroll');
      if (scrollEl) scrollEl.scrollLeft = Math.max(0, tAtPointer * newPx + TT_LABEL_W - pointerX);
    }, { passive: false });
  }
}

function ttScrubFromEvent(e) {
  const inner = document.getElementById('ttTracksInner');
  if (!inner) return;
  const rect = inner.getBoundingClientRect();
  const t = (e.clientX - rect.left - TT_LABEL_W) / ttGetZoom();
  ttSetPlayhead(t);
}

// ---- 片段拖拽移动 ----

function ttStartMove(e, clipEl, clip) {
  const type = clipEl.dataset.clipType;
  const px = ttGetZoom();
  const inner = document.getElementById('ttTracksInner');
  if (!inner) return;
  const innerRect = inner.getBoundingClientRect();
  const startX = e.clientX, startY = e.clientY;
  const grabOffsetSec = Math.max(0, (e.clientX - innerRect.left - TT_LABEL_W) / px - clip.start);

  // 选域互斥：先清画布节点选择（clearSelection 内部会同步清时间轴选择，
  // 故必须在其后再设置时间轴选择），否则 Delete 键两个选择域同时有值时
  // 用户预期混乱（画布 Delete 误删片段，反之亦然）
  if (typeof clearSelection === 'function' && (state.selectedNodeId != null || (state.selectedNodeIds && state.selectedNodeIds.length > 0))) {
    clearSelection();
  }
  // 按下即选中（剪映同款）：不等松手，误点邻轨也能立刻看到选中的是谁。
  // 选择只在这里处理一次；onUp 的纯点击分支不再重复处理（Ctrl toggle 会抵消）。
  ttHandleSelectionClick(type, clip.id, e.ctrlKey || e.metaKey);

  let dragging = false;
  let ghost = null;
  let targetInfo = null;

  const removeGhost = () => { if (ghost) { ghost.remove(); ghost = null; } };
  const clearLaneHighlight = () => {
    document.querySelectorAll('.tt-lane.drop-active').forEach(el => el.classList.remove('drop-active'));
  };

  const onMove = (ev) => {
    if (!dragging && Math.hypot(ev.clientX - startX, ev.clientY - startY) < 4) return;
    if (!dragging) {
      dragging = true;
      ttPauseIfPlaying();
      ghost = clipEl.cloneNode(true);
      ghost.className = 'tt-clip tt-ghost';
      ghost.style.width = clipEl.offsetWidth + 'px';
      document.body.appendChild(ghost);
      clipEl.classList.add('dragging');
    }
    ghost.style.left = (ev.clientX + 6) + 'px';
    ghost.style.top = (ev.clientY + 6) + 'px';

    targetInfo = ttGetDropTarget(ev.clientY, type);
    clearLaneHighlight();
    if (targetInfo && targetInfo.laneEl) targetInfo.laneEl.classList.add('drop-active');

    // 实时磁吸：吸附命中时显示垂直指示线（音频对视频分段口的对齐反馈）
    const rawStart = Math.max(0, ttPointerTimeX(ev.clientX) - grabOffsetSec);
    const snap = ttComputeSnap(rawStart, clipVisualDuration(clip), type, clip.id);
    if (snap.snapAt !== null) {
      ttShowSnapIndicator(snap.snapAt);
    } else {
      ttHideSnapIndicator();
    }
  };

  const onUp = (ev) => {
    window.removeEventListener('pointermove', onMove);
    removeGhost();
    clearLaneHighlight();
    ttHideSnapIndicator();
    if (!dragging) {
      // 纯点击：选择已在 pointerdown 处理，这里无需动作
      return;
    }
    clipEl.classList.remove('dragging');
    if (!targetInfo) {
      renderTimeline();
      return;
    }
    // 落点时间：指针当前位置对应的时间轴起点，磁吸 + 防重叠
    let finalStart = Math.max(0, ttPointerTimeX(ev.clientX) - grabOffsetSec);
    finalStart = ttComputeSnap(finalStart, clipVisualDuration(clip), type, clip.id).start;
    // 分镜柱子归属按"落点意图时间"（nudge 前）判定——nudge 防重叠可能把片段
    // 顶进相邻柱子的范围，不能用顶完的时间判定用户想放进哪个分镜
    const dropIntentStart = finalStart;
    finalStart = nudgeUntilFree(finalStart, clipVisualDuration(clip), targetInfo.type, targetInfo.track, clip.id);

    if (targetInfo.addNew) {
      const countKey = targetInfo.type === 'video' ? 'videoTrackCount' : 'audioTrackCount';
      state.timeline[countKey] = Math.min(TT_MAX_TRACKS, state.timeline[countKey] + 1);
    }
    clip.start = finalStart;
    clip.track = targetInfo.track;
    ttSyncClipPillarToDropTime(clip, type, dropIntentStart);
    renderTimeline();
    safeAutoSave();
  };

  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp, { once: true });
}

// 删除轨道（仅允许删除空轨；更高轨号片段下移补位保持紧凑）
function ttRemoveLane(type, trackIndex) {
  const countKey = type === 'video' ? 'videoTrackCount' : 'audioTrackCount';
  const arr = type === 'video' ? state.timeline.clips : state.timeline.audioClips;
  const onLane = arr.filter(c => (c.track || 0) === trackIndex);
  if (onLane.length > 0) {
    showToast(`「${type === 'video' ? '视频' : '音频'} ${trackIndex + 1}」轨道上还有 ${onLane.length} 个片段，请先移走或删除`, 'warning');
    return;
  }
  ttPauseIfPlaying();
  arr.forEach(c => {
    if ((c.track || 0) > trackIndex) c.track -= 1;
  });
  state.timeline[countKey] = Math.max(1, state.timeline[countKey] - 1);
  renderTimeline();
  safeAutoSave();
  showToast(`已删除空的${type === 'video' ? '视频' : '音频'}轨道`, 'success');
}

// 拖拽落位后，按落点时间把片段划入覆盖该位置的分镜柱子（pillarId + 柱内成员同步）。
// 用拖拽前的柱子几何快照判定（渲染时色带范围由片段聚合而来，拖动中已失真）；
// 无柱子覆盖时保留原 pillarId 不动（避免误改分镜归属）。
function ttSyncClipPillarToDropTime(clip, type, finalStart) {
  if (typeof window.__ttPillarGeometry !== 'object' || !window.__ttPillarGeometry) return;
  const geom = window.__ttPillarGeometry;
  const hit = geom.find(g => finalStart >= g.start - 0.01 && finalStart < g.end - 0.01);
  if (!hit || hit.pillarId === clip.pillarId) return;

  const arr = type === 'video' ? state.timeline.clips : state.timeline.audioClips;
  const oldPillar = state.timeline.pillars.find(p => p.id === clip.pillarId);
  const newPillar = state.timeline.pillars.find(p => p.id === hit.pillarId);
  if (!newPillar) return;

  // 从旧柱子成员移除
  if (oldPillar) {
    const idsKey = type === 'video' ? 'videoClipIds' : 'audioClipIds';
    oldPillar[idsKey] = oldPillar[idsKey].filter(id => id !== clip.id);
  }
  // 加入新柱子并重排柱内 order
  const idsKey = type === 'video' ? 'videoClipIds' : 'audioClipIds';
  if (!newPillar[idsKey].includes(clip.id)) newPillar[idsKey].push(clip.id);
  newPillar[idsKey].forEach((cid, i) => {
    const c = arr.find(x => x.id === cid);
    if (c) c.order = i;
  });
  clip.pillarId = newPillar.id;
}

// 每次渲染时记录柱子色带几何（拖拽落点判定分镜归属用）
function ttCapturePillarGeometry() {
  const bands = [];
  document.querySelectorAll('.tt-pillar-band').forEach(el => {
    const lane = el.closest('.tt-lane-content');
    if (!lane) return;
    const laneRect = lane.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    const px = ttGetZoom();
    const start = (r.left - laneRect.left) / px;
    bands.push({
      pillarId: el.dataset.pillarId,
      start,
      end: start + r.width / px,
    });
  });
  // 同一柱子跨轨多色带：合并同 pillarId 的范围
  const merged = new Map();
  bands.forEach(b => {
    if (!merged.has(b.pillarId)) merged.set(b.pillarId, { pillarId: b.pillarId, start: b.start, end: b.end });
    else {
      const m = merged.get(b.pillarId);
      m.start = Math.min(m.start, b.start);
      m.end = Math.max(m.end, b.end);
    }
  });
  window.__ttPillarGeometry = [...merged.values()];
}

// 指针当前位置对应的时间轴秒数
function ttPointerTimeX(clientX) {
  const inner = document.getElementById('ttTracksInner');
  if (!inner) return 0;
  const rect = inner.getBoundingClientRect();
  return (clientX - rect.left - TT_LABEL_W) / ttGetZoom();
}

// 由指针 Y 计算落点轨道：命中轨道；命中"添加轨道"存根 → 新增轨
function ttGetDropTarget(clientY, draggedType) {
  const inner = document.getElementById('ttTracksInner');
  if (!inner) return null;
  const innerRect = inner.getBoundingClientRect();
  const y = clientY - innerRect.top;

  // "添加轨道"存根行优先（位于组尾，可与轨道区无重叠）
  const stub = inner.querySelector(`[data-add-stub="${draggedType}"]`);
  if (stub) {
    const r = stub.getBoundingClientRect();
    const top = r.top - innerRect.top;
    const bottom = top + r.height;
    if (y >= top - 2 && y <= bottom + 2) {
      const countKey = draggedType === 'video' ? 'videoTrackCount' : 'audioTrackCount';
      return { type: draggedType, track: state.timeline[countKey], addNew: true, laneEl: null };
    }
  }

  const lanes = [...inner.querySelectorAll('.tt-lane')];
  for (const lane of lanes) {
    const r = lane.getBoundingClientRect();
    const top = r.top - innerRect.top;
    const bottom = top + r.height;
    if (y >= top - 4 && y <= bottom + 4) {
      if (lane.dataset.trackType !== draggedType) return null; // 类型不匹配（视频不能拖进音频轨）
      return {
        type: draggedType,
        track: Number(lane.dataset.trackIndex),
        addNew: false,
        laneEl: lane
      };
    }
  }
  return null;
}

// ---- 边缘裁剪 ----

function ttStartTrim(e, clipEl, clip, dir) {
  e.stopPropagation();
  e.preventDefault();
  ttPauseIfPlaying();
  const px = ttGetZoom();
  const startX = e.clientX;
  const origStartTime = clip.startTime || 0;
  const origEndTime = clip.endTime || clip.duration;
  const origStart = clip.start;
  const minLen = 0.1;

  const nameEl = clipEl.querySelector('.timeline-clip-duration');
  const apply = (ev) => {
    const deltaSec = (ev.clientX - startX) / px;
    if (dir === 'l') {
      const newST = Math.min(Math.max(0, origStartTime + deltaSec), origEndTime - minLen);
      const shift = newST - origStartTime;
      clip.startTime = newST;
      clip.start = origStart + shift; // 左缘裁剪：整体起点随源内偏移平移
    } else {
      clip.endTime = Math.min(Math.max(origStartTime + minLen, origEndTime + deltaSec), clip.duration);
    }
    const dur = clipVisualDuration(clip);
    clipEl.style.left = (clip.start * px) + 'px';
    clipEl.style.width = Math.max(10, Math.round(dur * px)) + 'px';
    if (nameEl) nameEl.textContent = `${dur.toFixed(1)}s`;
  };

  const onMove = (ev) => apply(ev);
  const onUp = () => {
    window.removeEventListener('pointermove', onMove);
    renderTimeline();
    safeAutoSave();
  };
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp, { once: true });
}

// ---- 分割 ----

function ttSplitSelectedAtPlayhead() {
  const sel = state.timeline.selectedClipIds || [];
  if (sel.length !== 1) {
    showToast('请先选中一个片段（播放头将作为分割点）', 'info');
    return;
  }
  const { type, id } = sel[0];
  const arr = type === 'video' ? state.timeline.clips : state.timeline.audioClips;
  const clip = arr.find(c => c.id === id);
  if (!clip) return;

  const localT = (state.timeline.playhead || 0) - clip.start;
  const visDur = clipVisualDuration(clip);
  if (localT <= 0.05 || localT >= visDur - 0.05) {
    showToast('播放头不在片段内部：请先点击刻度尺把播放头移到片段内', 'warning');
    return;
  }

  ttPauseIfPlaying();
  const cutSourceTime = (clip.startTime || 0) + localT;
  const nextIdKey = type === 'video' ? 'nextClipId' : 'nextAudioClipId';
  const second = { ...clip, id: state.timeline[nextIdKey]++, startTime: cutSourceTime, start: state.timeline.playhead };
  clip.endTime = cutSourceTime;
  arr.push(second);

  // 柱子成员同步：second 插到 clip 后，重排柱内 order
  const pillar = state.timeline.pillars.find(p => p.id === clip.pillarId);
  if (pillar) {
    const idsKey = type === 'video' ? 'videoClipIds' : 'audioClipIds';
    const idx = pillar[idsKey].indexOf(clip.id);
    if (idx !== -1) pillar[idsKey].splice(idx + 1, 0, second.id);
    else pillar[idsKey].push(second.id);
    pillar[idsKey].forEach((cid, i) => {
      const c = arr.find(x => x.id === cid);
      if (c) c.order = i;
    });
  }

  state.timeline.selectedClipIds = [{ type, id: second.id }];
  ttSyncLegacySelection();
  renderTimeline();
  showToast('已分割片段', 'success');
  safeAutoSave();
}

// 多选删除（仅删引用，不进垃圾桶——垃圾桶只存画布删除的节点；误删走撤销）
function ttDeleteSelectedClips() {
  const sel = state.timeline.selectedClipIds || [];
  if (!sel.length) return;
  ttPauseIfPlaying();
  const videoClips = sel.filter(s => s.type === 'video')
    .map(s => state.timeline.clips.find(c => c.id === s.id)).filter(Boolean);
  const audioClips = sel.filter(s => s.type === 'audio')
    .map(s => state.timeline.audioClips.find(c => c.id === s.id)).filter(Boolean);
  videoClips.forEach(c => removeClipFromPillar(c.id, 'video'));
  audioClips.forEach(c => removeClipFromPillar(c.id, 'audio'));
  const vIds = new Set(videoClips.map(c => c.id));
  const aIds = new Set(audioClips.map(c => c.id));
  state.timeline.clips = state.timeline.clips.filter(c => !vIds.has(c.id));
  state.timeline.audioClips = state.timeline.audioClips.filter(c => !aIds.has(c.id));
  ttClearSelection();
  renderTimeline();
  safeAutoSave();
}

// ---- 右键菜单 ----

let ttContextMenuEl = null;
function ttShowContextMenu(x, y, type, clipId) {
  ttHideContextMenu();
  // 右键即选中
  ttHandleSelectionClick(type, clipId, false);
  const menu = document.createElement('div');
  menu.className = 'tt-context-menu';
  const items = [];
  if (type === 'video') items.push({ label: '✂ 打开剪切对话框', fn: () => openTrimDialog(clipId) });
  items.push({ label: '✂ 在播放头处分割', fn: () => ttSplitSelectedAtPlayhead() });
  if (ttFindClip(type, clipId) && ttFindClip(type, clipId).nodeId) {
    items.push({ label: '↗ 跳转到节点', fn: () => focusOnNode(ttFindClip(type, clipId).nodeId) });
  }
  items.push({ label: '🗑 删除（进垃圾桶）', fn: () => ttDeleteSelectedClips() });
  menu.innerHTML = items.map((it, i) => `<div class="tt-context-item" data-idx="${i}">${escapeHtml(it.label)}</div>`).join('');
  document.body.appendChild(menu);
  const menuRect = menu.getBoundingClientRect();
  menu.style.left = Math.min(x, window.innerWidth - menuRect.width - 8) + 'px';
  menu.style.top = Math.min(y, window.innerHeight - menuRect.height - 8) + 'px';
  menu.querySelectorAll('.tt-context-item').forEach(itemEl => {
    itemEl.addEventListener('click', () => {
      const it = items[Number(itemEl.dataset.idx)];
      ttHideContextMenu();
      if (it && it.fn) it.fn();
    });
  });
  ttContextMenuEl = menu;
  setTimeout(() => {
    document.addEventListener('pointerdown', ttHideContextMenuOnDoc, { once: true });
  }, 0);
}

function ttHideContextMenuOnDoc(e) {
  if (ttContextMenuEl && !ttContextMenuEl.contains(e.target)) ttHideContextMenu();
  else if (ttContextMenuEl) {
    document.addEventListener('pointerdown', ttHideContextMenuOnDoc, { once: true });
  }
}

function ttHideContextMenu() {
  if (ttContextMenuEl) { ttContextMenuEl.remove(); ttContextMenuEl = null; }
}

// ---- 缩放按钮 ----

function ttZoomIn() {
  const anchor = state.timeline.playhead || 0;
  ttSetZoom(ttGetZoom() * 1.25);
  renderTimeline();
  const scroll = document.getElementById('ttTracksScroll');
  if (scroll) scroll.scrollLeft = Math.max(0, anchor * ttGetZoom() - scroll.clientWidth / 2);
}

function ttZoomOut() {
  const anchor = state.timeline.playhead || 0;
  ttSetZoom(ttGetZoom() / 1.25);
  renderTimeline();
  const scroll = document.getElementById('ttTracksScroll');
  if (scroll) scroll.scrollLeft = Math.max(0, anchor * ttGetZoom() - scroll.clientWidth / 2);
}

// ---- 键盘快捷键 ----

window.addEventListener('keydown', (e) => {
  const tag = document.activeElement ? document.activeElement.tagName : '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || document.activeElement && document.activeElement.isContentEditable) return;
  // 有模态框打开时不响应（剪切对话框/垃圾桶/各类编辑弹窗）
  if (document.querySelector('.modal.show')) return;
  // 时间轴未展开时不响应
  if (!state.timeline.visible) return;

  if (e.key === 's' || e.key === 'S') {
    if ((state.timeline.selectedClipIds || []).length === 0) return;
    e.preventDefault();
    ttSplitSelectedAtPlayhead();
  } else if (e.key === ' ') {
    e.preventDefault();
    ttTogglePlay();
  } else if (e.key === 'Escape') {
    ttClearSelection();
    ttHideContextMenu();
  } else if (e.key === 'Delete' || e.key === 'Backspace') {
    if ((state.timeline.selectedClipIds || []).length === 0) return;
    e.preventDefault();
    ttDeleteSelectedClips();
  }
});

// ---- 时间轴撤销（按钮/Ctrl+Z 共用）：暂停播放后回滚到上一份工作流快照 ----

function ttUndoTimelineChange() {
  ttPauseIfPlaying();
  if (typeof undoWorkflowChange === 'function') undoWorkflowChange();
}

// ---- 模块出口 ----

window.TimelineTracks = {
  render: ttRender,
  pause: pauseTimelinePlayback,
  zoomIn: ttZoomIn,
  zoomOut: ttZoomOut,
  split: ttSplitSelectedAtPlayhead,
  deleteSelected: ttDeleteSelectedClips,
  undo: ttUndoTimelineChange,
};
