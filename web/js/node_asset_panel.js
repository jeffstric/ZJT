/**
 * node_asset_panel.js — 画布节点管理面板（参考 libtv 节点列表交互）。
 *
 * 依赖（页面需先加载）：web/js/state.js（state/canvasEl/showToast/showConfirmModal 全局）、
 * web/js/utils.js（getNodeImageUrl）、web/js/canvas.js（focusOnNode）、
 * web/js/escape.js（window.escapeHtml，XSS 红线：节点标题等用户内容必须转义）、
 * web/css/node_asset_panel.css。
 *
 * 能力：
 *  - 入口：左下角小地图上方 #nodeAssetPanelBtn（节点管理），点击开合左侧面板
 *  - 列表：画布全部节点（标题字典序），缩略图 + 标题 + 类型徽标
 *  - 搜索：按标题/类型名过滤；类型筛选下拉只列出画布上实际存在的类型
 *  - 定位：点击行聚焦画布节点（focusOnNode，带闪烁高亮）
 *  - 删除：行内删除按钮，确认弹窗后 removeNode
 *  - 统计：底部"共 N 节点"；过滤时显示"M / N"
 *
 * 数据只读自 state.nodes（本地内存），不发起网络请求；节点增删通过
 * MutationObserver 监听画布 DOM 自动刷新列表，工作流重新加载（全量重建节点）
 * 后列表随之复原，无需持久化面板状态。
 */
(function () {
  'use strict';

  // ============ 节点类型元数据（labelKey 对应 video_workflow 语言包） ============
  var NODE_TYPE_META = {
    image:          { labelKey: 'image',               fallback: '图片' },
    image_edit:     { labelKey: 'image',               fallback: '图片' },   // 旧类型兼容
    video:          { labelKey: 'video',               fallback: '视频' },
    image_to_video: { labelKey: 'image_to_video',      fallback: '生视频' },
    audio:          { labelKey: 'audio',               fallback: '音频' },
    text:           { labelKey: 'text',                fallback: '文本' },
    script:         { labelKey: 'script',              fallback: '剧本' },
    text_to_speech: { labelKey: 'text_to_speech',      fallback: '文字转语音' },
    dialogue_group: { labelKey: 'dialogue_group',      fallback: '对话组' },
    shot_group:     { labelKey: 'shot_frame_group',    fallback: '幕' },
    shot_frame:     { labelKey: 'node_shot_frame_label', fallback: '分镜' },
    extract_frame:  { labelKey: 'extract_frame',       fallback: '提取帧' },
    script_extract: { labelKey: 'script_extract',      fallback: '剧本提取' },
    video_watermark:{ labelKey: 'video_watermark',     fallback: '去字幕水印' },
    digital_human:  { labelKey: 'digital_human',       fallback: '数字人' },
    camera_control: { labelKey: 'camera_control',      fallback: '相机控制' },
    panorama:       { labelKey: 'panorama',            fallback: '360全景图' },
    director_stage: { labelKey: 'director_stage',      fallback: '导演台' },
    prompt_reverse: { labelKey: 'prompt_reverse_title', fallback: '提示词反推' },
    character:      { labelKey: 'character',           fallback: '角色' },
    location:       { labelKey: 'scene',               fallback: '场景' },
    props:          { labelKey: 'prop',                fallback: '道具' }
  };

  // 视频类节点：缩略图用视频首帧（<video> seek）；其余图片类用 <img>
  var VIDEO_THUMB_TYPES = { video: 1, image_to_video: 1, video_watermark: 1, extract_frame: 1 };

  // ============ 模块状态 ============
  var panelEl = null;
  var listEl = null;
  var searchInput = null;
  var typeSelect = null;
  var footerEl = null;
  var canvasObserver = null;
  var refreshRafId = null;
  var thumbObserver = null;
  var activeRowId = null;

  function esc(value) {
    return window.escapeHtml ? window.escapeHtml(value) : String(value == null ? '' : value);
  }

  // t() 缺 key 时返回 key 本身，这里统一兜底中文
  function tr(key, fallback) {
    if (window.t) {
      var v = window.t(key);
      if (v && v !== key) return v;
    }
    return fallback;
  }

  function getNodes() {
    return (typeof state !== 'undefined' && state && Array.isArray(state.nodes)) ? state.nodes : [];
  }

  // ============ 缩略图解析 ============

  function firstUrlOf(item) {
    if (!item) return '';
    if (typeof item === 'string') return item;
    return item.url || item.video_url || item.videoUrl || '';
  }

  /**
   * 解析节点缩略图 { kind: 'image'|'video'|'none', url }
   * 图片地址统一走 normalizeImageUrl + proxyImageUrl（跨域图走服务端代理，与画布行为一致）
   */
  function getNodeThumb(node) {
    var d = (node && node.data) || {};
    var type = node && node.type;
    var raw = '';
    var kind = 'none';

    if (VIDEO_THUMB_TYPES[type]) {
      if (type === 'image_to_video') {
        raw = firstUrlOf(Array.isArray(d.videoUrls) && d.videoUrls[0]) || d.startUrl || d.endUrl || '';
        // 无成片时首/尾帧是图片
        if (!firstUrlOf(Array.isArray(d.videoUrls) && d.videoUrls[0]) && raw) return { kind: 'image', url: toImgUrl(raw) };
      } else if (type === 'video') {
        raw = d.url || '';
      } else {
        raw = d.videoUrl || '';
      }
      if (raw) return { kind: 'video', url: raw };
      return { kind: 'none', url: '' };
    }

    // 图片类：类型专属字段 → getNodeImageUrl 通用兜底
    if (type === 'shot_frame') raw = d.imageUrl || '';
    else if (type === 'digital_human') raw = d.imageUrl || d.imagePreview || '';
    else if (type === 'panorama') raw = d.url || d.preview || '';
    if (!raw && typeof getNodeImageUrl === 'function') raw = getNodeImageUrl(node) || '';
    if (!raw) {
      raw = d.preview || d.imageUrl || d.imagePreview || d.reference_image || '';
    }
    if (raw) return { kind: 'image', url: toImgUrl(raw) };
    return { kind: 'none', url: '' };
  }

  function toImgUrl(raw) {
    if (!raw) return '';
    if (typeof normalizeImageUrl === 'function') raw = normalizeImageUrl(raw);
    if (typeof proxyImageUrl === 'function') raw = proxyImageUrl(raw);
    return raw;
  }

  // ============ 面板骨架（首次打开时动态创建，降低主 HTML 体积） ============

  var ICON_LOCATE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="9"/></svg>';
  var ICON_TRASH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
  var ICON_SEARCH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>';
  var ICON_REFRESH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>';

  function ensurePanel() {
    if (panelEl) return panelEl;

    panelEl = document.createElement('aside');
    panelEl.className = 'node-asset-panel';
    panelEl.id = 'nodeAssetPanel';
    panelEl.setAttribute('aria-hidden', 'true');
    panelEl.innerHTML =
      '<div class="nap-header">' +
        '<div class="nap-title">' + esc(tr('node_asset_panel_title', '节点管理')) + '</div>' +
        '<button type="button" class="nap-refresh" title="' + esc(tr('node_asset_refresh', '刷新列表')) + '" aria-label="' + esc(tr('node_asset_refresh', '刷新列表')) + '">' + ICON_REFRESH + '</button>' +
        '<button type="button" class="nap-close" title="' + esc(tr('node_asset_close', '关闭')) + '" aria-label="' + esc(tr('node_asset_close', '关闭')) + '">×</button>' +
      '</div>' +
      '<div class="nap-toolbar">' +
        '<div class="nap-search-wrap">' +
          ICON_SEARCH +
          '<input type="text" class="nap-search" placeholder="' + esc(tr('node_asset_search_placeholder', '搜索节点...')) + '" />' +
        '</div>' +
        '<select class="nap-type-select" title="' + esc(tr('node_asset_filter_all', '全部类型')) + '"></select>' +
      '</div>' +
      '<div class="nap-list"></div>' +
      '<div class="nap-footer"></div>';

    document.body.appendChild(panelEl);

    listEl = panelEl.querySelector('.nap-list');
    searchInput = panelEl.querySelector('.nap-search');
    typeSelect = panelEl.querySelector('.nap-type-select');
    footerEl = panelEl.querySelector('.nap-footer');

    panelEl.querySelector('.nap-close').addEventListener('click', closePanel);
    panelEl.querySelector('.nap-refresh').addEventListener('click', renderList);
    searchInput.addEventListener('input', renderList);
    typeSelect.addEventListener('change', renderList);

    // 行点击代理：定位 / 删除
    listEl.addEventListener('click', function (e) {
      var item = e.target.closest('.nap-item');
      if (!item) return;
      var nodeId = Number(item.dataset.nodeId);
      var node = getNodes().find(function (n) { return n.id === nodeId; });
      if (!node) { renderList(); return; }

      if (e.target.closest('.nap-delete')) {
        deleteNodeWithConfirm(node);
        return;
      }
      locateNode(nodeId);
    });

    if ('IntersectionObserver' in window) {
      thumbObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          thumbObserver.unobserve(entry.target);
          fillThumb(entry.target);
        });
      }, { root: listEl, rootMargin: '120px' });
    }

    return panelEl;
  }

  // ============ 渲染 ============

  function isPanelOpen() {
    return panelEl && panelEl.classList.contains('open');
  }

  function typeLabel(type) {
    var meta = NODE_TYPE_META[type];
    if (!meta) return type || '未知';
    return tr(meta.labelKey, meta.fallback);
  }

  function collectTypes(nodes) {
    var seen = {};
    var types = [];
    nodes.forEach(function (n) {
      if (seen[n.type]) return;
      seen[n.type] = true;
      types.push(n.type);
    });
    types.sort(function (a, b) { return typeLabel(a).localeCompare(typeLabel(b), 'zh-CN'); });
    return types;
  }

  function renderTypeOptions(nodes) {
    var current = typeSelect.value || 'all';
    var types = collectTypes(nodes);
    var html = '<option value="all">' + esc(tr('node_asset_filter_all', '全部类型')) + '</option>';
    types.forEach(function (t) {
      html += '<option value="' + esc(t) + '">' + esc(typeLabel(t)) + '</option>';
    });
    typeSelect.innerHTML = html;
    // 当前选中类型仍在画布上则保留，否则重置为全部
    if (current !== 'all' && types.indexOf(current) === -1) current = 'all';
    typeSelect.value = current;
  }

  function renderList() {
    if (!panelEl) return;
    var nodes = getNodes();
    renderTypeOptions(nodes);

    var keyword = (searchInput.value || '').trim().toLowerCase();
    var typeFilter = typeSelect.value || 'all';

    var filtered = nodes.filter(function (n) {
      if (typeFilter !== 'all' && n.type !== typeFilter) return false;
      if (!keyword) return true;
      var title = String(n.title || '');
      if (title.toLowerCase().indexOf(keyword) !== -1) return true;
      return typeLabel(n.type).toLowerCase().indexOf(keyword) !== -1;
    });

    // 标题字典序（与 libtv 一致的混排观感），同标题按 id 稳定排序
    filtered.sort(function (a, b) {
      var cmp = String(a.title || '').localeCompare(String(b.title || ''), 'zh-CN');
      if (cmp !== 0) return cmp;
      return a.id - b.id;
    });

    if (!nodes.length) {
      listEl.innerHTML = '<div class="nap-empty">' + esc(tr('node_asset_empty', '画布上还没有节点')) + '</div>';
    } else if (!filtered.length) {
      listEl.innerHTML = '<div class="nap-empty">' + esc(tr('node_asset_no_match', '没有匹配的节点')) + '</div>';
    } else {
      listEl.innerHTML = filtered.map(renderItem).join('');
      listEl.querySelectorAll('.nap-thumb').forEach(function (el) {
        if (thumbObserver) thumbObserver.observe(el);
        else fillThumb(el);
      });
    }

    var totalText = tr('node_asset_total', '共 {n} 节点').replace('{n}', nodes.length);
    if (filtered.length !== nodes.length) {
      var filteredText = tr('node_asset_total_filtered', '{m} / {n}').replace('{m}', filtered.length).replace('{n}', nodes.length);
      footerEl.textContent = filteredText;
      footerEl.title = totalText;
    } else {
      footerEl.textContent = totalText;
      footerEl.title = '';
    }
  }

  function renderItem(node) {
    var thumb = getNodeThumb(node);
    var title = String(node.title || '');
    var selected = typeof state !== 'undefined' && node.id === activeRowId;
    return (
      '<div class="nap-item' + (selected ? ' active' : '') + '" data-node-id="' + node.id + '">' +
        '<div class="nap-thumb" data-kind="' + thumb.kind + '"' + (thumb.url ? ' data-url="' + esc(thumb.url) + '"' : '') + '>' +
          (thumb.kind === 'none' ? '<span class="nap-thumb-fallback">' + esc(typeLabel(node.type).slice(0, 2)) + '</span>' : '') +
        '</div>' +
        '<div class="nap-item-main">' +
          '<div class="nap-item-title" title="' + esc(title) + '">' + esc(title) + '</div>' +
          '<div class="nap-item-type">' + esc(typeLabel(node.type)) + '</div>' +
        '</div>' +
        '<div class="nap-item-actions">' +
          '<button type="button" class="nap-icon-btn nap-locate" title="' + esc(tr('node_asset_locate', '定位节点')) + '" aria-label="' + esc(tr('node_asset_locate', '定位节点')) + '">' + ICON_LOCATE + '</button>' +
          '<button type="button" class="nap-icon-btn nap-delete" title="' + esc(tr('node_asset_delete', '删除节点')) + '" aria-label="' + esc(tr('node_asset_delete', '删除节点')) + '">' + ICON_TRASH + '</button>' +
        '</div>' +
      '</div>'
    );
  }

  // 懒加载缩略图：进入视口才创建 img / video 元素，避免大画布一次性解码全部媒体
  function fillThumb(thumbEl) {
    if (thumbEl.dataset.filled === '1') return;
    thumbEl.dataset.filled = '1';
    var kind = thumbEl.dataset.kind;
    var url = thumbEl.dataset.url || '';
    if (kind === 'none' || !url) return;

    if (kind === 'video') {
      var video = document.createElement('video');
      video.className = 'nap-thumb-media';
      video.muted = true;
      video.controls = false;
      video.preload = 'metadata';
      video.playsInline = true;
      video.loop = false;
      video.src = typeof proxyDownloadUrl === 'function' ? proxyDownloadUrl(url) : url;
      video.onloadedmetadata = function () {
        try {
          if (isFinite(video.duration) && video.duration > 0) {
            video.currentTime = Math.min(0.1, Math.max(0, video.duration - 0.1));
          }
        } catch (e) { /* 部分格式 seek 失败时保留黑帧 */ }
      };
      thumbEl.appendChild(video);
      return;
    }

    var img = document.createElement('img');
    img.className = 'nap-thumb-media';
    img.alt = '';
    img.loading = 'lazy';
    img.decoding = 'async';
    img.src = url;
    img.onerror = function () {
      img.remove();
      thumbEl.dataset.filled = '0';
    };
    thumbEl.appendChild(img);
  }

  // ============ 交互 ============

  function syncEntryBtn(active) {
    var btn = document.getElementById('nodeAssetPanelBtn');
    if (btn) btn.classList.toggle('active', active);
  }

  function openPanel() {
    ensurePanel();
    panelEl.classList.add('open');
    panelEl.setAttribute('aria-hidden', 'false');
    syncEntryBtn(true);
    renderList();
    observeCanvas();
    searchInput.focus();
  }

  function closePanel() {
    if (!panelEl) return;
    panelEl.classList.remove('open');
    panelEl.setAttribute('aria-hidden', 'true');
    syncEntryBtn(false);
    activeRowId = null;
    stopObservingCanvas();
    if (thumbObserver) thumbObserver.disconnect();
  }

  function togglePanel() {
    if (isPanelOpen()) closePanel();
    else openPanel();
  }

  function locateNode(nodeId) {
    activeRowId = nodeId;
    listEl.querySelectorAll('.nap-item').forEach(function (el) {
      el.classList.toggle('active', Number(el.dataset.nodeId) === nodeId);
    });
    if (typeof focusOnNode === 'function') focusOnNode(nodeId);
  }

  function deleteNodeWithConfirm(node) {
    var message = tr('node_asset_delete_confirm', '确定删除该节点吗？删除后无法恢复。');
    if (typeof showConfirmModal === 'function') {
      showConfirmModal(message).then(function (ok) {
        if (!ok) return;
        if (typeof removeNode === 'function') {
          removeNode(node.id);
          // 画布 MutationObserver 会触发刷新；主动刷一次以覆盖观察降级环境
          if (isPanelOpen()) renderList();
        }
      });
    } else if (typeof removeNode === 'function') {
      removeNode(node.id);
      if (isPanelOpen()) renderList();
    }
  }

  // ============ 画布联动刷新 ============
  // 只监听画布子节点增删（.node 挂载/移除），覆盖所有节点创建与工作流重载路径

  function observeCanvas() {
    if (canvasObserver || typeof canvasEl === 'undefined') return;
    if (typeof MutationObserver === 'undefined') return;
    canvasObserver = new MutationObserver(function () {
      if (!isPanelOpen()) return;
      if (refreshRafId !== null) return;
      refreshRafId = requestAnimationFrame(function () {
        refreshRafId = null;
        renderList();
      });
    });
    canvasObserver.observe(canvasEl, { childList: true });
  }

  function stopObservingCanvas() {
    if (canvasObserver) {
      canvasObserver.disconnect();
      canvasObserver = null;
    }
    if (refreshRafId !== null) {
      cancelAnimationFrame(refreshRafId);
      refreshRafId = null;
    }
  }

  // ============ 初始化 ============

  function init() {
    var btn = document.getElementById('nodeAssetPanelBtn');
    if (!btn) return;
    btn.addEventListener('click', togglePanel);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && isPanelOpen()) closePanel();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // 供测试与外部调用
  window.NodeAssetPanel = {
    open: openPanel,
    close: closePanel,
    toggle: togglePanel,
    refresh: function () { if (isPanelOpen()) renderList(); },
    getNodeThumb: getNodeThumb,
    typeLabel: typeLabel
  };
})();
