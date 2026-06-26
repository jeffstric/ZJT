/* ============================================================
   营销智能体 — 灵感页面 JS (vanilla JS)
   ============================================================ */

'use strict';

let publishedInspirationData = [];
let inspirationPage = 1;
const INSPIRATION_PAGE_SIZE = 40;
let inspirationTotal = 0;

function getFeedData() {
  return publishedInspirationData;
}

function inferMediaTypeFromUrl(url) {
  const cleanUrl = String(url || '').split(/[?#]/)[0].toLowerCase();
  return /\.(mp4|webm|mov|m4v|avi|mkv)$/.test(cleanUrl) ? 'video' : 'image';
}

function mapPublicationToCard(item) {
  const params = item.params_snapshot || {};
  const mediaType = item.media_type || params.media_type || inferMediaTypeFromUrl(item.result_url || item.cover_url);
  return {
    publicationId: item.id,
    src: item.cover_url || item.result_url,
    resultUrl: item.result_url,
    mediaType,
    title: item.title || item.prompt_snapshot || 'AI creation',
    author: item.owner_phone || item.owner_email || 'AI创作者',
    authorInitial: 'A',
    authorColor: mediaType === 'video' ? '#059669' : '#0288d1',
    likes: item.like_count || 0,
    tags: item.tags || [],
    aspectRatio: mediaType === 'video' ? 0.5625 : 1.0,
    prompt: item.prompt_snapshot || params.prompt || '',
    model: params.model_name || params.model_key || '',
    ratio: params.ratio || '',
    paramsSnapshot: params,
  };
}

function hasMorePublishedInspirations() {
  return publishedInspirationData.length < inspirationTotal;
}

async function loadPublishedInspirations(page = 1, options = {}) {
  try {
    const resp = await fetch(`/api/marketing-inspirations?page=${page}&page_size=${INSPIRATION_PAGE_SIZE}`);
    if (!resp.ok) throw new Error('load failed');
    const result = await resp.json();
    const rows = result?.data?.data || [];
    const mappedRows = rows.map(mapPublicationToCard);
    inspirationPage = page;
    inspirationTotal = Number(result?.data?.total || 0);
    publishedInspirationData = options.append
      ? publishedInspirationData.concat(mappedRows)
      : mappedRows;
    return mappedRows;
  } catch (e) {
    console.warn('[Inspiration] Failed to load published inspirations:', e);
    if (!options.append) {
      publishedInspirationData = [];
      inspirationTotal = 0;
    }
    return [];
  }
}

// ── 工具函数
function formatLikes(n) {
  if (n >= 10000) return (n / 10000).toFixed(1) + 'w';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return String(n);
}

function _t(key, params) {
  return (typeof window.t === 'function' && window.t !== _t) ? window.t(key, params) : key;
}

function tOrFallback(key, fallback, params) {
  const translated = _t(key, params);
  return translated && translated !== key ? translated : fallback;
}

// ── 骨架屏
function renderSkeleton(count) {
  const grid = document.getElementById('masonryGrid');
  if (!grid) return;
  const heights = [180, 240, 200, 280, 220, 260, 190, 250, 210, 230];
  for (let i = 0; i < count; i++) {
    const sk = document.createElement('div');
    sk.className = 'skeleton';
    sk.style.height = heights[i % heights.length] + 'px';
    grid.appendChild(sk);
  }
}

function removeSkeleton() {
  const grid = document.getElementById('masonryGrid');
  if (!grid) return;
  grid.querySelectorAll('.skeleton').forEach(el => el.remove());
}

// ── 创建瀑布流卡片
function createMasonryItem(data, index) {
  const item = document.createElement('div');
  item.className = 'masonry-item';
  item.dataset.index = index;

  const mediaEl = document.createElement(data.mediaType === 'video' ? 'video' : 'img');
  mediaEl.src = data.mediaType === 'video' ? (data.resultUrl || data.src) : data.src;
  if (data.mediaType === 'video') {
    mediaEl.muted = true;
    mediaEl.playsInline = true;
    mediaEl.preload = 'metadata';
  } else {
    mediaEl.alt = data.title;
    mediaEl.loading = 'lazy';
    mediaEl.decoding = 'async';
  }

  const overlay = document.createElement('div');
  overlay.className = 'item-overlay';

  const titleEl = document.createElement('div');
  titleEl.className = 'item-title';
  titleEl.textContent = data.title;

  const meta = document.createElement('div');
  meta.className = 'item-meta';

  const authorEl = document.createElement('div');
  authorEl.className = 'item-author';

  const avatar = document.createElement('div');
  avatar.className = 'author-avatar';
  avatar.style.background = data.authorColor;
  avatar.textContent = data.authorInitial;

  const authorName = document.createElement('span');
  authorName.textContent = data.author;

  authorEl.appendChild(avatar);
  authorEl.appendChild(authorName);

  const likesEl = document.createElement('div');
  likesEl.className = 'item-likes';
  likesEl.innerHTML = `
    <svg viewBox="0 0 24 24" width="12" height="12" stroke="rgba(255,255,255,0.85)" fill="none" stroke-width="2">
      <path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z"/>
    </svg>
    <span>${formatLikes(data.likes)}</span>
  `;

  meta.appendChild(authorEl);
  meta.appendChild(likesEl);
  overlay.appendChild(titleEl);
  overlay.appendChild(meta);
  item.appendChild(mediaEl);
  item.appendChild(overlay);

  item.addEventListener('click', () => openLightbox(data));
  return item;
}

// ── 渲染瀑布流
function renderMasonry() {
  const grid = document.getElementById('masonryGrid');
  if (!grid) return;
  removeSkeleton();
  grid.innerHTML = '';
  getFeedData().forEach((data, i) => {
    grid.appendChild(createMasonryItem(data, i));
  });
}

// ── Lightbox
let currentLightboxData = null;

function openLightbox(data) {
  currentLightboxData = data;
  const lightbox = document.getElementById('lightbox');
  const lightboxImg = document.getElementById('lightboxImg');
  const lightboxMain = document.querySelector('.lightbox-main');
  const lightboxAvatar = document.getElementById('lightboxAvatar');
  const lightboxAuthorName = document.getElementById('lightboxAuthorName');
  const lightboxMediaType = document.getElementById('lightboxMediaType');
  const lightboxModel = document.getElementById('lightboxModel');
  const lightboxRatio = document.getElementById('lightboxRatio');
  const lightboxPromptLabel = document.getElementById('lightboxPromptLabel');
  const lightboxPrompt = document.getElementById('lightboxPrompt');
  const isVideo = data.mediaType === 'video';

  if (lightboxMain) {
    lightboxMain.innerHTML = '';
    if (isVideo) {
      const video = document.createElement('video');
      video.className = 'lightbox-img';
      video.src = data.resultUrl || data.src;
      video.controls = true;
      video.autoplay = true;
      video.playsInline = true;
      lightboxMain.appendChild(video);
    } else {
      const img = document.createElement('img');
      img.className = 'lightbox-img';
      img.id = 'lightboxImg';
      img.src = data.src;
      img.alt = data.title;
      lightboxMain.appendChild(img);
    }
  } else if (lightboxImg) {
    lightboxImg.src = data.src;
    lightboxImg.alt = data.title;
  }
  lightboxAvatar.textContent = data.authorInitial || data.author[0];
  lightboxAvatar.style.background = data.authorColor || 'var(--accent-light)';
  lightboxAvatar.style.color = data.authorColor ? '#fff' : 'var(--accent-color)';
  lightboxAuthorName.textContent = data.author;
  if (lightboxMediaType) {
    lightboxMediaType.textContent = isVideo
      ? tOrFallback('video', '视频')
      : tOrFallback('image', '图片');
  }
  lightboxModel.textContent = data.model || '3.1';
  lightboxRatio.textContent = data.ratio || '1:1';
  if (lightboxPromptLabel) {
    lightboxPromptLabel.textContent = isVideo
      ? tOrFallback('video_prompt_label', '视频提示词')
      : tOrFallback('image_prompt_label', '图片提示词');
  }
  lightboxPrompt.textContent = data.prompt || data.title;
  lightbox.classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeLightbox() {
  const lightbox = document.getElementById('lightbox');
  lightbox.classList.remove('active');
  document.body.style.overflow = '';
  setTimeout(() => {
    const mediaEl = document.querySelector('.lightbox-main video, .lightbox-main img');
    if (mediaEl) {
      if (mediaEl.tagName === 'VIDEO') mediaEl.pause();
      mediaEl.removeAttribute('src');
      if (typeof mediaEl.load === 'function') mediaEl.load();
    }
    currentLightboxData = null;
  }, 300);
}

// ── Toast 提示
function showToast(msg) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = msg;
  toast.style.cssText = `
    position: fixed;
    bottom: 32px;
    left: 50%;
    transform: translateX(-50%) translateY(20px);
    background: rgba(0,0,0,0.8);
    color: white;
    padding: 10px 22px;
    border-radius: 24px;
    font-size: 14px;
    z-index: 9999;
    opacity: 0;
    transition: all 0.3s ease;
    white-space: nowrap;
    backdrop-filter: blur(8px);
  `;
  document.body.appendChild(toast);

  requestAnimationFrame(() => {
    toast.style.opacity = '1';
    toast.style.transform = 'translateX(-50%) translateY(0)';
  });

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(-50%) translateY(10px)';
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}

// ── 无限滚动（仅加载已审核的真实灵感数据）
let loadingMore = false;

async function loadMoreImages() {
  if (loadingMore || !hasMorePublishedInspirations()) return;
  loadingMore = true;

  const grid = document.getElementById('masonryGrid');
  if (!grid) return;

  const loader = document.createElement('div');
  loader.className = 'load-indicator';
  loader.style.cssText = 'column-span: all; text-align: center; padding: 20px; color: var(--text-muted); font-size: 13px;';
  loader.textContent = _t('loading') || '加载中...';
  grid.appendChild(loader);

  try {
    const startIdx = publishedInspirationData.length;
    const rows = await loadPublishedInspirations(inspirationPage + 1, { append: true });
    loader.remove();
    rows.forEach((data, i) => {
      grid.appendChild(createMasonryItem(data, startIdx + i));
    });
  } finally {
    loader.remove();
    loadingMore = false;
  }
}

// ── 工具栏交互 — 模型数据（将从 API 加载，此处为默认值）
let IMAGE_MODELS = [
  { name: 'Seedream 5.0', desc: '最新图片模型，质量最佳', key: 'seedream_5', value: 'seedream_5' },
  { name: 'Seedream 3.0', desc: '均衡速度与质量', key: 'seedream_3', value: 'seedream_3' },
];

let VIDEO_MODELS = [
  { name: 'Seedance 1.0', desc: '最新视频模型', key: 'seedance_1', value: 'seedance_1' },
];

let LLM_MODELS = [];

const RATIOS = [
  { value: 'auto', label: '智能', w: 20, h: 20 },
  { value: '1:1', label: '1:1', w: 28, h: 28 },
  { value: '4:3', label: '4:3', w: 32, h: 24 },
  { value: '3:4', label: '3:4', w: 24, h: 32 },
  { value: '16:9', label: '16:9', w: 36, h: 20 },
  { value: '9:16', label: '9:16', w: 20, h: 36 },
  { value: '21:9', label: '21:9', w: 28, h: 12 },
  { value: '2:3', label: '2:3', w: 14, h: 22 },
  { value: '3:2', label: '3:2', w: 22, h: 15 },
];

const RESOLUTIONS = ['auto', '1K', '2K', '4K'];
const DURATIONS = [5, 10];

let toolbarState = {
  type: 'agent',
  // Agent 模式专属
  agentMediaType: 'image',
  agentRatio: '9:16',
  agentResolution: 'auto',
  agentDuration: 5,
  agentVideoMode: 'first_last_frame',
  agentModel: '',
  agentModelKey: '',
  agentLLMModel: '',
  agentLLMModelId: null,
  agentLLMVendorId: null,
  // 非 Agent 模式（图片/视频）
  model: '',
  modelKey: '',
  ratio: '1:1',
  resolution: 'auto',
  duration: 5,
};

// ── 上传媒体文件状态
let uploadedMediaItems = []; // [{ id, file, previewUrl, serverUrl, type, uploading, uploadFailed, thumbnailUrl }]
let mediaIdCounter = 0;

// ── 从 API 加载模型数据
async function loadModelsFromApi() {
  try {
    // 加载 LLM 模型
    const llmRes = await fetch('/api/models');
    if (llmRes.ok) {
      const llmData = await llmRes.json();
      if (llmData.success && llmData.models) {
        LLM_MODELS = llmData.models.map(m => ({
          id: m.model_id,
          name: m.name,
          vendor: m.vendor_name,
          vendor_id: m.vendor_id,
          supportsVl: m.supports_vl || false,
          supportsThinking: m.supports_thinking || false,
        }));
        // 默认选中
        if (LLM_MODELS.length > 0) {
          const preferred = LLM_MODELS.find(m => m.name === 'doubao-seed-2-0-lite') || LLM_MODELS[0];
          toolbarState.agentLLMModel = preferred.name;
          toolbarState.agentLLMModelId = preferred.id;
          toolbarState.agentLLMVendorId = preferred.vendor_id;
        }
      }
    }
  } catch (e) {
    console.warn('[Inspiration] Failed to load LLM models:', e);
  }

  // 加载 TaskConfig（图片/视频模型）
  try {
    if (window.TaskConfig && !window.TaskConfig.isLoaded()) {
      await window.TaskConfig.load();
    }
    if (window.TaskConfig && window.TaskConfig.isLoaded()) {
      // 图片模型
      const imgOpts = window.TaskConfig.getModelOptionsForCategory('text_to_image');
      if (imgOpts && imgOpts.length > 0) {
        IMAGE_MODELS = imgOpts.map(opt => ({
          name: opt.label.split(' (')[0],
          desc: opt.label,
          key: opt.key,
          value: opt.value,
        }));
      }
      // 视频模型
      const vidOpts = window.TaskConfig.getModelOptionsForCategory('text_to_video');
      if (vidOpts && vidOpts.length > 0) {
        VIDEO_MODELS = vidOpts.map(opt => ({
          name: opt.label.split(' (')[0],
          desc: opt.label,
          key: opt.key,
          value: opt.value,
        }));
      }
    }
  } catch (e) {
    console.warn('[Inspiration] Failed to load TaskConfig:', e);
  }

  // 设置默认模型
  if (IMAGE_MODELS.length > 0 && !toolbarState.agentModel) {
    toolbarState.agentModel = IMAGE_MODELS[0].name;
    toolbarState.agentModelKey = IMAGE_MODELS[0].key;
    toolbarState.model = IMAGE_MODELS[0].name;
    toolbarState.modelKey = IMAGE_MODELS[0].key;
  }
}

function initToolbar() {
  renderModelList();
  renderRatioGrid();
  renderResolutionList();
  renderDurationMenu();
  // Agent 设置面板渲染
  renderAgentRatioGrid();
  renderAgentResolutionList();
  renderAgentDurationList();
  renderAgentModelList();
  renderAgentLLMList();
  bindToolbarEvents();
  updateToolbarUI();
}

function renderModelList() {
  const container = document.getElementById('modelList');
  if (!container) return;
  const isVideo = toolbarState.type === 'video';
  const models = isVideo ? VIDEO_MODELS : IMAGE_MODELS;
  const selectedKey = isVideo ? toolbarState.modelKey : toolbarState.modelKey;
  container.innerHTML = models.map(m => {
    const isActive = m.key === selectedKey || m.name === toolbarState.model;
    const iconSvg = isVideo
      ? '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 9l5 3-5 3V9z"/>'
      : '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.5"/><path d="M21 15l-5-5L5 19"/>';
    return `
      <div class="mk-model ${isActive ? 'active' : ''}" data-model="${m.name}" data-key="${m.key || ''}" style="display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:10px;cursor:pointer;transition:background 0.2s;margin-bottom:4px;border:1px solid ${isActive ? 'var(--border-color)' : 'transparent'};background:${isActive ? '#fff' : 'transparent'};box-shadow:${isActive ? '0 1px 4px rgba(0,0,0,0.05)' : 'none'};">
        <div style="width:36px;height:36px;background:#f0f0f0;border-radius:8px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${iconSvg}</svg>
        </div>
        <div style="flex:1;min-width:0;">
          <div style="font-size:14px;font-weight:500;color:var(--text-primary);">${m.name}</div>
          <div style="font-size:12px;color:var(--text-muted);margin-top:2px;">${m.desc}</div>
        </div>
        ${isActive ? '<span style="color:var(--text-primary);font-size:18px;">✓</span>' : ''}
      </div>
    `;
  }).join('');
}

function renderRatioGrid() {
  const container = document.getElementById('ratioGrid');
  if (!container) return;
  container.innerHTML = RATIOS.map(r => {
    const isActive = r.value === toolbarState.ratio;
    return `
      <div class="mk-ratio ${isActive ? 'active' : ''}" data-ratio="${r.value}" style="display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 10px;border-radius:10px;cursor:pointer;transition:all 0.2s;border:2px solid ${isActive ? 'var(--accent-color)' : 'transparent'};background:${isActive ? 'var(--accent-light)' : '#f5f5f5'};">
        <div style="width:${r.w}px;height:${r.h}px;border:2px solid ${isActive ? 'var(--accent-color)' : '#ccc'};border-radius:3px;"></div>
        <span style="font-size:11px;color:var(--text-secondary);">${r.label}</span>
      </div>
    `;
  }).join('');
}

function renderResolutionList() {
  const container = document.getElementById('resolutionList');
  if (!container) return;
  container.innerHTML = RESOLUTIONS.map(res => {
    const isActive = res === toolbarState.resolution;
    return `
      <div class="mk-res ${isActive ? 'active' : ''}" data-resolution="${res}" style="flex:1;min-width:70px;text-align:center;padding:10px;border-radius:8px;cursor:pointer;transition:all 0.2s;font-size:14px;border:${isActive ? '2px solid var(--accent-color)' : '1px solid var(--border-color)'};background:${isActive ? 'var(--accent-light)' : '#f5f5f5'};color:${isActive ? 'var(--accent-color)' : 'var(--text-primary)'};">
        ${res === 'auto' ? '自动' : res}
      </div>
    `;
  }).join('');
}

function renderDurationMenu() {
  const container = document.getElementById('durationMenu');
  if (!container) return;
  container.innerHTML = DURATIONS.map(d => {
    const isActive = d === toolbarState.duration;
    return `
      <div class="mk-dur ${isActive ? 'active' : ''}" data-duration="${d}" style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-radius:8px;cursor:pointer;transition:background 0.2s;background:${isActive ? 'var(--accent-light)' : 'transparent'};">
        <span style="font-size:13px;font-weight:500;color:var(--text-primary);">${d}秒</span>
        ${isActive ? '<span style="color:var(--accent-color);font-weight:bold;">✓</span>' : ''}
      </div>
    `;
  }).join('');
}

function togglePanel(btn, panel, arrowId) {
  const isHidden = panel.classList.contains('hidden');
  if (!isHidden) {
    panel.classList.add('hidden');
    panel.style.top = '';
    panel.style.bottom = '';
  } else {
    const rect = btn.getBoundingClientRect();
    const vh = window.innerHeight;
    const isTopHalf = rect.top < vh / 2;
    if (isTopHalf) {
      panel.style.top = 'calc(100% + 8px)';
      panel.style.bottom = 'auto';
    } else {
      panel.style.bottom = 'calc(100% + 8px)';
      panel.style.top = 'auto';
    }
    panel.classList.remove('hidden');
  }
  if (arrowId) {
    const arrow = document.getElementById(arrowId);
    if (arrow) arrow.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
  }
}

function closeOthers(exceptId) {
  document.querySelectorAll('.marketing-dropdown-menu, .marketing-panel').forEach(el => {
    if (el.id !== exceptId) {
      el.classList.add('hidden');
      el.style.top = '';
      el.style.bottom = '';
    }
  });
}

function bindToolbarEvents() {
  const typeBtn = document.getElementById('typeBtn');
  const typeMenu = document.getElementById('typeMenu');
  if (typeBtn && typeMenu) {
    typeBtn.addEventListener('click', e => {
      e.stopPropagation();
      togglePanel(typeBtn, typeMenu, 'typeArrow');
      closeOthers('typeMenu');
    });
    typeMenu.addEventListener('click', e => {
      const item = e.target.closest('.mk-item');
      if (!item) return;
      toolbarState.type = item.dataset.type;
      // 非 Agent 模式时同步模型
      if (toolbarState.type !== 'agent') {
        const isVideo = toolbarState.type === 'video';
        const models = isVideo ? VIDEO_MODELS : IMAGE_MODELS;
        if (models.length > 0) {
          toolbarState.model = models[0].name;
          toolbarState.modelKey = models[0].key;
        }
        toolbarState.ratio = '1:1';
      }
      updateToolbarUI();
      renderModelList();
      renderRatioGrid();
      typeMenu.classList.add('hidden');
    });
  }

  // Agent 设置面板按钮
  const agentSettingsBtn = document.getElementById('agentSettingsBtn');
  const agentSettingsPanel = document.getElementById('agentSettingsPanel');
  if (agentSettingsBtn && agentSettingsPanel) {
    agentSettingsBtn.addEventListener('click', e => {
      e.stopPropagation();
      togglePanel(agentSettingsBtn, agentSettingsPanel);
      closeOthers('agentSettingsPanel');
    });
    // Agent 设置面板内部事件
    agentSettingsPanel.addEventListener('click', e => {
      e.stopPropagation(); // 阻止冒泡到 document 级别的全局关闭监听器
      // 媒体类型切换
      const mediaItem = e.target.closest('[data-media]');
      if (mediaItem) {
        toolbarState.agentMediaType = mediaItem.dataset.media;
        // 更新 toggle UI
        agentSettingsPanel.querySelectorAll('[data-media]').forEach(el => {
          el.classList.toggle('active', el.dataset.media === toolbarState.agentMediaType);
        });
        // 切换模型列表
        renderAgentModelList();
        // 显示/隐藏视频特有设置
        const isVid = toolbarState.agentMediaType === 'video';
        document.getElementById('agentDurationGroup').classList.toggle('hidden', !isVid);
        document.getElementById('agentVideoModeGroup').classList.toggle('hidden', !isVid);
        document.getElementById('agentResolutionGroup').classList.toggle('hidden', isVid);
        return;
      }
      // 视频生成方式切换
      const vidModeItem = e.target.closest('[data-vidmode]');
      if (vidModeItem) {
        toolbarState.agentVideoMode = vidModeItem.dataset.vidmode;
        agentSettingsPanel.querySelectorAll('[data-vidmode]').forEach(el => {
          el.classList.toggle('active', el.dataset.vidmode === toolbarState.agentVideoMode);
        });
        const descEl = document.getElementById('agentVideoModeDesc');
        if (descEl) {
          descEl.textContent = toolbarState.agentVideoMode === 'first_last_frame'
            ? _t('first_last_frame_desc') || '上传首帧和尾帧图片生成视频'
            : _t('multi_reference_desc') || '上传多张参考图生成视频';
        }
        return;
      }
      // 比例选择
      const ratioItem = e.target.closest('.mk-agent-ratio');
      if (ratioItem) {
        toolbarState.agentRatio = ratioItem.dataset.ratio;
        renderAgentRatioGrid();
        return;
      }
      // 分辨率选择
      const resItem = e.target.closest('.mk-agent-res');
      if (resItem) {
        toolbarState.agentResolution = resItem.dataset.resolution;
        renderAgentResolutionList();
        return;
      }
      // 时长选择
      const durItem = e.target.closest('.mk-agent-dur');
      if (durItem) {
        toolbarState.agentDuration = parseInt(durItem.dataset.duration);
        renderAgentDurationList();
        return;
      }
      // 模型选择
      const modelItem = e.target.closest('.mk-agent-model');
      if (modelItem) {
        toolbarState.agentModel = modelItem.dataset.model;
        toolbarState.agentModelKey = modelItem.dataset.key;
        renderAgentModelList();
        return;
      }
      // LLM 模型选择
      const llmItem = e.target.closest('.mk-agent-llm');
      if (llmItem) {
        toolbarState.agentLLMModel = llmItem.dataset.model;
        toolbarState.agentLLMModelId = parseInt(llmItem.dataset.id);
        toolbarState.agentLLMVendorId = llmItem.dataset.vendor ? parseInt(llmItem.dataset.vendor) : null;
        renderAgentLLMList();
        return;
      }
    });
  }

  const modelBtn = document.getElementById('modelBtn');
  const modelPanel = document.getElementById('modelPanel');
  if (modelBtn && modelPanel) {
    modelBtn.addEventListener('click', e => {
      e.stopPropagation();
      togglePanel(modelBtn, modelPanel);
      closeOthers('modelPanel');
    });
    modelPanel.addEventListener('click', e => {
      const item = e.target.closest('.mk-model');
      if (!item) return;
      toolbarState.model = item.dataset.model;
      toolbarState.modelKey = item.dataset.key || '';
      updateToolbarUI();
      renderModelList();
      modelPanel.classList.add('hidden');
    });
  }

  const ratioBtn = document.getElementById('ratioBtn');
  const ratioPanel = document.getElementById('ratioPanel');
  if (ratioBtn && ratioPanel) {
    ratioBtn.addEventListener('click', e => {
      e.stopPropagation();
      togglePanel(ratioBtn, ratioPanel);
      closeOthers('ratioPanel');
    });
    ratioPanel.addEventListener('click', e => {
      const item = e.target.closest('.mk-ratio');
      if (item) {
        toolbarState.ratio = item.dataset.ratio;
        renderRatioGrid();
        updateToolbarUI();
      }
      const resItem = e.target.closest('.mk-res');
      if (resItem) {
        toolbarState.resolution = resItem.dataset.resolution;
        renderResolutionList();
        updateToolbarUI();
      }
    });
  }

  const durationBtn = document.getElementById('durationBtn');
  const durationMenu = document.getElementById('durationMenu');
  if (durationBtn && durationMenu) {
    durationBtn.addEventListener('click', e => {
      e.stopPropagation();
      togglePanel(durationBtn, durationMenu);
      closeOthers('durationMenu');
    });
    durationMenu.addEventListener('click', e => {
      const item = e.target.closest('.mk-dur');
      if (!item) return;
      toolbarState.duration = parseInt(item.dataset.duration);
      updateToolbarUI();
      renderDurationMenu();
      durationMenu.classList.add('hidden');
    });
  }

  document.addEventListener('click', () => {
    document.querySelectorAll('.marketing-dropdown-menu, .marketing-panel').forEach(el => {
      el.classList.add('hidden');
      el.style.top = '';
      el.style.bottom = '';
    });
  });
}

function updateToolbarUI() {
  const typeLabel = document.getElementById('typeLabel');
  const modelLabel = document.getElementById('modelLabel');
  const ratioLabel = document.getElementById('ratioLabel');
  const durationLabel = document.getElementById('durationLabel');
  const durationDropdown = document.getElementById('durationDropdown');
  const resolutionGroup = document.getElementById('resolutionGroup');
  const modelIconImg = document.getElementById('modelIconImg');
  const modelIconVid = document.getElementById('modelIconVid');

  // Agent mode panels
  const agentSettingsDropdown = document.getElementById('agentSettingsDropdown');
  const modelDropdown = document.getElementById('modelDropdown');
  const ratioDropdown = document.getElementById('ratioDropdown');

  const isAgent = toolbarState.type === 'agent';
  const isVideo = toolbarState.type === 'video';

  // Type label
  if (typeLabel) {
    const labels = {
      agent: tOrFallback('mode_agent', 'Agent 模式'),
      image: tOrFallback('mode_image', '图片生成'),
      video: tOrFallback('mode_video', '视频生成'),
    };
    typeLabel.textContent = labels[toolbarState.type] || toolbarState.type;
  }

  // Show/hide Agent vs non-Agent controls
  if (agentSettingsDropdown) agentSettingsDropdown.classList.toggle('hidden', !isAgent);
  if (modelDropdown) modelDropdown.classList.toggle('hidden', isAgent);
  if (ratioDropdown) ratioDropdown.classList.toggle('hidden', isAgent);

  // Non-Agent toolbar
  if (modelLabel) modelLabel.textContent = toolbarState.model || '默认模型';
  if (ratioLabel) ratioLabel.textContent = toolbarState.ratio;
  if (durationLabel) durationLabel.textContent = toolbarState.duration + 's';
  if (durationDropdown) durationDropdown.classList.toggle('hidden', !isVideo);
  if (resolutionGroup) resolutionGroup.classList.toggle('hidden', isVideo);
  if (modelIconImg && modelIconVid) {
    modelIconImg.classList.toggle('hidden', isVideo);
    modelIconVid.classList.toggle('hidden', !isVideo);
  }
}

// ── Agent 设置面板渲染函数
function renderAgentRatioGrid() {
  const container = document.getElementById('agentRatioGrid');
  if (!container) return;
  container.innerHTML = RATIOS.map(r => {
    const isActive = r.value === toolbarState.agentRatio;
    return `
      <div class="mk-agent-ratio ${isActive ? 'active' : ''}" data-ratio="${r.value}" style="display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 10px;border-radius:10px;cursor:pointer;transition:all 0.2s;border:2px solid ${isActive ? 'var(--accent-color)' : 'transparent'};background:${isActive ? 'var(--accent-light)' : '#f5f5f5'};">
        <div style="width:${r.w}px;height:${r.h}px;border:2px solid ${isActive ? 'var(--accent-color)' : '#ccc'};border-radius:3px;${r.value === 'auto' ? 'display:flex;align-items:center;justify-content:center;font-size:10px;color:#666;' : ''}">${r.value === 'auto' ? '☆' : ''}</div>
        <span style="font-size:11px;color:var(--text-secondary);">${r.label}</span>
      </div>
    `;
  }).join('');
}

function renderAgentResolutionList() {
  const container = document.getElementById('agentResolutionList');
  if (!container) return;
  container.innerHTML = RESOLUTIONS.map(res => {
    const isActive = res === toolbarState.agentResolution;
    return `
      <div class="mk-agent-res ${isActive ? 'active' : ''}" data-resolution="${res}" style="flex:1;min-width:60px;text-align:center;padding:10px;border-radius:8px;cursor:pointer;transition:all 0.2s;font-size:14px;border:${isActive ? '2px solid var(--accent-color)' : '1px solid var(--border-color)'};background:${isActive ? 'var(--accent-light)' : '#f5f5f5'};color:${isActive ? 'var(--accent-color)' : 'var(--text-primary)'};">
        ${res === 'auto' ? '自动' : res}
      </div>
    `;
  }).join('');
}

function renderAgentDurationList() {
  const container = document.getElementById('agentDurationList');
  if (!container) return;
  container.innerHTML = DURATIONS.map(d => {
    const isActive = d === toolbarState.agentDuration;
    return `
      <div class="mk-agent-dur ${isActive ? 'active' : ''}" data-duration="${d}" style="flex:1;text-align:center;padding:10px;border-radius:8px;cursor:pointer;transition:all 0.2s;font-size:14px;border:${isActive ? '2px solid var(--accent-color)' : '1px solid var(--border-color)'};background:${isActive ? 'var(--accent-light)' : '#f5f5f5'};color:${isActive ? 'var(--accent-color)' : 'var(--text-primary)'};">
        ${d}秒
      </div>
    `;
  }).join('');
}

function renderAgentModelList() {
  const container = document.getElementById('agentModelList');
  if (!container) return;
  const isVideo = toolbarState.agentMediaType === 'video';
  const models = isVideo ? VIDEO_MODELS : IMAGE_MODELS;
  const selectedKey = toolbarState.agentModelKey;
  container.innerHTML = models.map(m => {
    const isActive = m.key === selectedKey;
    const iconSvg = isVideo
      ? '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 9l5 3-5 3V9z"/>'
      : '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.5"/><path d="M21 15l-5-5L5 19"/>';
    return `
      <div class="mk-agent-model ${isActive ? 'active' : ''}" data-model="${m.name}" data-key="${m.key || ''}" style="display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:10px;cursor:pointer;transition:background 0.2s;margin-bottom:4px;border:1px solid ${isActive ? 'var(--border-color)' : 'transparent'};background:${isActive ? '#fff' : 'transparent'};box-shadow:${isActive ? '0 1px 4px rgba(0,0,0,0.05)' : 'none'};">
        <div style="width:32px;height:32px;background:#f0f0f0;border-radius:6px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="1.5">${iconSvg}</svg>
        </div>
        <div style="flex:1;min-width:0;">
          <div style="font-size:13px;font-weight:500;color:var(--text-primary);">${m.name}</div>
          <div style="font-size:11px;color:var(--text-muted);">${m.desc}</div>
        </div>
        ${isActive ? '<span style="color:var(--accent-color);font-size:16px;">✓</span>' : ''}
      </div>
    `;
  }).join('');
}

function renderAgentLLMList() {
  const container = document.getElementById('agentLLMList');
  if (!container) return;
  if (LLM_MODELS.length === 0) {
    container.innerHTML = '<div style="font-size:12px;color:var(--text-muted);padding:8px;">暂无可用 LLM 模型</div>';
    return;
  }
  container.innerHTML = LLM_MODELS.map(m => {
    const isActive = m.id === toolbarState.agentLLMModelId;
    const badges = [];
    if (m.supportsVl) badges.push('<span style="font-size:10px;color:#7c3aed;background:#f3e8ff;padding:1px 6px;border-radius:4px;">VL</span>');
    if (m.supportsThinking) badges.push('<span style="font-size:10px;color:#059669;background:#d1fae5;padding:1px 6px;border-radius:4px;">深度思考</span>');
    return `
      <div class="mk-agent-llm ${isActive ? 'active' : ''}" data-model="${m.name}" data-id="${m.id}" data-vendor="${m.vendor_id || ''}" style="display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:10px;cursor:pointer;transition:background 0.2s;margin-bottom:4px;border:1px solid ${isActive ? 'var(--border-color)' : 'transparent'};background:${isActive ? '#fff' : 'transparent'};box-shadow:${isActive ? '0 1px 4px rgba(0,0,0,0.05)' : 'none'};">
        <div style="width:32px;height:32px;background:#f0f0f0;border-radius:6px;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:16px;">🤖</div>
        <div style="flex:1;min-width:0;">
          <div style="font-size:13px;font-weight:500;color:var(--text-primary);display:flex;align-items:center;gap:4px;flex-wrap:wrap;">${m.name} ${badges.join(' ')}</div>
          <div style="font-size:11px;color:var(--text-muted);">${m.vendor || ''}</div>
        </div>
        ${isActive ? '<span style="color:var(--accent-color);font-size:16px;">✓</span>' : ''}
      </div>
    `;
  }).join('');
}

// ── 媒体上传函数

function addMediaPreview(item) {
  const bar = document.getElementById('mediaPreviewBar');
  if (!bar) return;
  const el = document.createElement('div');
  el.className = 'media-preview-item';
  el.dataset.mediaId = item.id;

  if (item.type === 'video') {
    el.innerHTML = `
      <video src="${item.previewUrl}" muted playsinline></video>
      <div class="video-icon"><svg width="10" height="10" viewBox="0 0 24 24" fill="white"><polygon points="5 3 19 12 5 21 5 3"/></svg></div>
      ${item.uploading ? '<div class="upload-status"><div class="upload-status-bar" style="width:0%"></div></div>' : ''}
      <button class="media-preview-remove" data-remove-id="${item.id}">&times;</button>`;
  } else {
    el.innerHTML = `
      <img src="${item.previewUrl}" alt="">
      ${item.uploading ? '<div class="upload-status"><div class="upload-status-bar" style="width:0%"></div></div>' : ''}
      <button class="media-preview-remove" data-remove-id="${item.id}">&times;</button>`;
  }
  bar.appendChild(el);
}

function removeMediaPreview(id) {
  const bar = document.getElementById('mediaPreviewBar');
  if (!bar) return;
  const el = bar.querySelector(`[data-media-id="${id}"]`);
  if (el) el.remove();
}

function updateMediaUploadProgress(id, progress) {
  const bar = document.getElementById('mediaPreviewBar');
  if (!bar) return;
  const el = bar.querySelector(`[data-media-id="${id}"]`);
  if (!el) return;
  const barEl = el.querySelector('.upload-status-bar');
  if (barEl) barEl.style.width = progress + '%';
  if (progress >= 100) {
    const statusEl = el.querySelector('.upload-status');
    if (statusEl) statusEl.remove();
  }
}

async function uploadMediaFile(file) {
  const isVideo = file.type.startsWith('video/');
  const previewUrl = URL.createObjectURL(file);
  const item = {
    id: ++mediaIdCounter,
    file,
    previewUrl,
    serverUrl: null,
    thumbnailUrl: null,
    type: isVideo ? 'video' : 'image',
    uploading: true,
    uploadFailed: false,
  };
  uploadedMediaItems.push(item);
  addMediaPreview(item);

  try {
    if (isVideo) {
      // 视频：直接存本地 URL，不做上传
      item.serverUrl = null; // 视频需重新上传
      item.uploading = false;
      updateMediaUploadProgress(item.id, 100);
    } else {
      // 图片：上传到服务器
      const formData = new FormData();
      formData.append('file', file);
      formData.append('session_id', 'inspiration_temp');
      const token = localStorage.getItem('auth_token');
      if (token) formData.append('auth_token', token);

      const resp = await fetch('/api/upload-agent-image', { method: 'POST', body: formData });
      if (!resp.ok) throw new Error('Upload failed: ' + resp.status);
      const result = await resp.json();
      if (result.url) {
        item.serverUrl = result.url;
        item.thumbnailUrl = result.thumbnail_url || result.url;
      } else {
        throw new Error('No URL in response');
      }
      item.uploading = false;
      updateMediaUploadProgress(item.id, 100);
    }
  } catch (e) {
    console.error('[Inspiration] Upload failed:', e);
    item.uploading = false;
    item.uploadFailed = true;
    showToast('上传失败: ' + file.name);
  }
}

function handleFileSelect(files) {
  if (!files || files.length === 0) return;
  for (const file of files) {
    if (!file.type.startsWith('image/') && !file.type.startsWith('video/')) {
      showToast('不支持的文件类型: ' + file.name);
      continue;
    }
    if (file.size > 100 * 1024 * 1024) {
      showToast('文件过大: ' + file.name);
      continue;
    }
    uploadMediaFile(file);
  }
}

// ── 页面跳转：做同款 / 发送（携带完整参数）
function goToGenerate(prompt, options) {
  const params = new URLSearchParams();
  params.set('new_session', '1');
  if (prompt) params.set('prompt', prompt);

  if (options) {
    if (options.mode) params.set('mode', options.mode);
    if (options.media_type) params.set('media_type', options.media_type);
    if (options.model_key) params.set('model_key', options.model_key);
    if (options.model_name) params.set('model_name', options.model_name);
    if (options.ratio) params.set('ratio', options.ratio);
    if (options.resolution) params.set('resolution', options.resolution);
    if (options.duration) params.set('duration', String(options.duration));
    if (options.video_mode) params.set('video_mode', options.video_mode);
    if (options.llm_model_id) params.set('llm_model_id', String(options.llm_model_id));
    if (options.llm_vendor_id) params.set('llm_vendor_id', String(options.llm_vendor_id));
    if (options.has_media) params.set('has_media', String(options.has_media));
  }

  // 传递上传的媒体文件（通过 sessionStorage）
  const completedMedia = uploadedMediaItems.filter(m => !m.uploading && !m.uploadFailed);
  if (completedMedia.length > 0) {
    const mediaData = completedMedia.map(m => ({
      type: m.type,
      serverUrl: m.serverUrl,
      thumbnailUrl: m.thumbnailUrl,
      fileName: m.file ? m.file.name : '',
    }));
    try {
      sessionStorage.setItem('inspiration_media', JSON.stringify(mediaData));
      params.set('has_media', '1');
    } catch (e) {
      console.warn('sessionStorage 写入失败:', e);
    }
  }

  window.location.href = '/marketing-agent?' + params.toString();
}

async function goToGenerateFromPublication(publicationId) {
  const resp = await fetch(`/api/marketing-inspirations/${publicationId}/template`);
  if (!resp.ok) throw new Error('template failed');
  const result = await resp.json();
  const data = result.data || {};
  const params = data.params || {};
  const media = Array.isArray(data.media) ? data.media : [];
  if (media.length > 0) {
    sessionStorage.setItem('inspiration_media', JSON.stringify(media));
    params.has_media = '1';
  }
  await fetch(`/api/marketing-inspirations/${publicationId}/remix-count`, { method: 'POST' }).catch(() => {});
  goToGenerate(data.prompt || params.prompt || '', params);
}

// ── 初始化
async function initPage() {
  const grid = document.getElementById('masonryGrid');

  // 加载模型数据
  await loadModelsFromApi();
  await loadPublishedInspirations();

  // 骨架屏 → 延迟渲染真实内容
  renderSkeleton(12);
  setTimeout(() => {
    renderMasonry();
  }, 400);

  // 工具栏
  initToolbar();

  // Lightbox 事件
  const lightboxClose = document.getElementById('lightboxClose');
  const lightboxOverlay = document.getElementById('lightboxOverlay');
  if (lightboxClose) lightboxClose.addEventListener('click', closeLightbox);
  if (lightboxOverlay) lightboxOverlay.addEventListener('click', closeLightbox);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeLightbox();
  });

  // 做同款按钮
  const lbDoSameBtn = document.getElementById('lbDoSameBtn');
  if (lbDoSameBtn) {
    lbDoSameBtn.addEventListener('click', async () => {
      if (!currentLightboxData) return;
      if (currentLightboxData.publicationId) {
        const id = currentLightboxData.publicationId;
        closeLightbox();
        try {
          await goToGenerateFromPublication(id);
        } catch (e) {
          showToast('做同款失败');
        }
        return;
      }
      const prompt = currentLightboxData.prompt || currentLightboxData.title;
      const src = currentLightboxData.src;
      closeLightbox();

      // 将灵感图片加入媒体列表，让 goToGenerate 通过 sessionStorage 传递
      if (src) {
        const fullUrl = /^https?:\/\//.test(src) ? src : (window.location.origin + src);
        uploadedMediaItems.push({
          id: ++mediaIdCounter,
          file: null,
          previewUrl: fullUrl,
          serverUrl: fullUrl,
          thumbnailUrl: fullUrl,
          type: 'image',
          uploading: false,
          uploadFailed: false,
        });
      }

      goToGenerate(prompt, { mode: toolbarState.type });
    });
  }

  // 用作参考图按钮
  const lbRefBtn = document.getElementById('lbReferenceBtn');
  if (lbRefBtn) {
    lbRefBtn.addEventListener('click', () => {
      if (!currentLightboxData) return;
      const src = currentLightboxData.src;
      const prompt = currentLightboxData.prompt || currentLightboxData.title;
      closeLightbox();

      // 将灵感图片作为参考图加入媒体列表
      if (src) {
        const fullUrl = /^https?:\/\//.test(src) ? src : (window.location.origin + src);
        uploadedMediaItems.push({
          id: ++mediaIdCounter,
          file: null,
          previewUrl: fullUrl,
          serverUrl: fullUrl,
          thumbnailUrl: fullUrl,
          type: 'image',
          uploading: false,
          uploadFailed: false,
        });
      }

      // 以 Agent 模式跳转，携带参考图
      goToGenerate(prompt || '', { mode: 'agent', media_type: 'image' });
    });
  }

  // 输入框自动增高
  const promptInput = document.querySelector('.prompt-input');
  const sendBtn = document.querySelector('.marketing-send-btn');
  if (promptInput) {
    promptInput.addEventListener('input', function () {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 200) + 'px';
    });
    promptInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        if (sendBtn) sendBtn.click();
      }
    });
  }

  // 发送按钮
  if (sendBtn) {
    sendBtn.addEventListener('click', function () {
      const val = promptInput ? promptInput.value.trim() : '';
      const hasMedia = uploadedMediaItems.some(m => !m.uploading && !m.uploadFailed);
      if (!val && !hasMedia) {
        if (promptInput) {
          promptInput.focus();
          promptInput.style.borderBottom = '2px solid var(--accent-color)';
          setTimeout(() => { promptInput.style.borderBottom = ''; }, 800);
        }
        return;
      }

      // 构建跳转参数
      const opts = { mode: toolbarState.type };
      if (toolbarState.type === 'agent') {
        opts.media_type = toolbarState.agentMediaType;
        opts.model_key = toolbarState.agentModelKey;
        opts.model_name = toolbarState.agentModel;
        opts.ratio = toolbarState.agentRatio;
        if (toolbarState.agentMediaType === 'image') {
          opts.resolution = toolbarState.agentResolution;
        } else {
          opts.duration = toolbarState.agentDuration;
          opts.video_mode = toolbarState.agentVideoMode;
        }
        if (toolbarState.agentLLMModelId) {
          opts.llm_model_id = toolbarState.agentLLMModelId;
          if (toolbarState.agentLLMVendorId) opts.llm_vendor_id = toolbarState.agentLLMVendorId;
        }
      } else if (toolbarState.type === 'image') {
        opts.model_key = toolbarState.modelKey;
        opts.model_name = toolbarState.model;
        opts.ratio = toolbarState.ratio;
        opts.resolution = toolbarState.resolution;
      } else if (toolbarState.type === 'video') {
        opts.model_key = toolbarState.modelKey;
        opts.model_name = toolbarState.model;
        opts.ratio = toolbarState.ratio;
        opts.duration = toolbarState.duration;
      }
      goToGenerate(val, opts);
    });
  }

  // 功能卡片 - 点击跳转到 marketing_agent 对应模式
  document.querySelectorAll('.feature-card[data-mode]').forEach(card => {
    card.addEventListener('click', function () {
      const mode = this.dataset.mode;
      if (mode) {
        window.location.href = '/marketing-agent?mode=' + encodeURIComponent(mode);
      }
    });
  });

  // 添加素材按钮 → 触发文件输入
  const addBtn = document.getElementById('addMediaBtn');
  const fileInput = document.getElementById('inspirationFileInput');
  if (addBtn && fileInput) {
    addBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
      handleFileSelect(e.target.files);
      fileInput.value = ''; // 允许重复选择同一文件
    });
  }

  // 媒体预览删除按钮（事件委托）
  const previewBar = document.getElementById('mediaPreviewBar');
  if (previewBar) {
    previewBar.addEventListener('click', (e) => {
      const removeBtn = e.target.closest('[data-remove-id]');
      if (removeBtn) {
        const id = parseInt(removeBtn.dataset.removeId);
        uploadedMediaItems = uploadedMediaItems.filter(m => m.id !== id);
        removeMediaPreview(id);
      }
    });
  }

  // 无限滚动（监听 .main-content）
  const mainContent = document.querySelector('.main-content');
  if (mainContent) {
    mainContent.addEventListener('scroll', () => {
      const scrollBottom = mainContent.scrollHeight - mainContent.scrollTop - mainContent.clientHeight;
      if (scrollBottom < 300) loadMoreImages();
    }, { passive: true });
  }
}

// ── 入口
document.addEventListener('DOMContentLoaded', async () => {
  // i18n 初始化
  try {
    if (window.ZJTi18n) {
      await ZJTi18n.init(['common', 'marketing_inspiration']);
      if (window.ZJTi18nDOM) ZJTi18nDOM.scanDOM();
      if (window.ZJTi18nSwitcher) ZJTi18nSwitcher.attachToHeader();
    }
  } catch (e) {
    console.warn('i18n init failed:', e);
  }

  await initPage();
});
