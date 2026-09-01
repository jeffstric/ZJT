// ============================
// panorama_node.js - 360度全景图节点
// 生成 equirectangular 等距圆柱全景图，内置 Pannellum 查看器：
// 拖拽旋转视角（yaw/pitch/hfov）、惯性、全屏查看、视角状态随工作流保存复原。
// 支持视角截图：任意比例/画质（默认1K）离屏渲染当前视角，自动上传并生成图片节点。
// 提示词侧内置 8 类场景模板 + 全景技术后缀自动拼接。
// 依赖：/js/vendor/pannellum.min.js（本地 vendor，零外部依赖）
// ============================

(function() {

  // Pannellum 的 WebGL 上下文默认不保留绘制缓冲（未传 preserveDrawingBuffer），
  // 渲染帧合成后 canvas.toDataURL() 会得到空白图像，截图前必须注入该选项。
  // 本页面除全景查看器外没有其他 WebGL 使用方，一次性补丁无副作用。
  if (!window.__panoGetContextPatched) {
    window.__panoGetContextPatched = true;
    var origGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, attrs) {
      if (type === 'webgl' || type === 'experimental-webgl') {
        attrs = Object.assign({}, attrs || {}, { preserveDrawingBuffer: true });
      }
      return origGetContext.call(this, type, attrs);
    };
  }

  // ---------- 提示词模板库 ----------
  // 结构遵循 equirectangular 提示词最佳实践：四周环绕式环境描述 + 光照一致性，
  // 投影格式关键词（360 degree equirectangular / spherical projection / seamless）
  // 由 buildPanoramaPrompt 统一追加，模板本身聚焦场景内容。
  var PANORAMA_PROMPT_TEMPLATES = [
    { key: 'natural_lake', text: 'A breathtaking 360 degree view of an alpine lake at golden hour, snow-capped peaks surrounding the viewer on all sides, mirror-still water reflecting warm orange and pink clouds, pine forests framing the horizon, soft volumetric light, photorealistic, ultra detailed' },
    { key: 'city_night', text: 'A cyberpunk megacity intersection at night seen from street level, neon signs and holographic advertisements wrapping around in every direction, rain-slicked asphalt reflecting magenta and cyan lights, dense urban skyline, light fog, cinematic lighting, ultra detailed' },
    { key: 'indoor', text: 'A modern Scandinavian living room interior, floor-to-ceiling windows on one side overlooking a city park, warm wooden floors, minimalist furniture, soft afternoon sunlight streaming in, plants and bookshelves along the surrounding walls, cozy atmosphere, architectural photography, ultra detailed' },
    { key: 'sci_fi', text: 'The interior of a futuristic space station observation deck, curved glass dome revealing a colorful nebula and distant planets, glowing control panels and holographic displays surrounding the viewer, sleek white and chrome surfaces, ambient blue lighting, science fiction concept art, ultra detailed' },
    { key: 'fantasy', text: 'An enchanted forest clearing ringed by ancient glowing trees, floating lanterns and fireflies drifting in every direction, a crystal stream winding through moss-covered stones, mystical fog, bioluminescent mushrooms along the horizon, fantasy concept art, ethereal lighting, ultra detailed' },
    { key: 'beach_sunset', text: 'A tropical beach at sunset, gentle waves lapping the shore in front, leaning palm trees curving overhead, warm golden sand stretching to both sides, dramatic orange and purple sky with scattered clouds, distant sailboats on the horizon, photorealistic, ultra detailed' },
    { key: 'desert_night', text: 'A vast desert under the Milky Way at night, towering sand dunes rolling away in every direction, brilliant star field with the galactic core overhead, a small campfire casting warm light near the viewer, deep blue and violet tones, astrophotography style, ultra detailed' },
    { key: 'snowy_village', text: 'A cozy alpine village square in winter, snow-covered chalets with warm glowing windows surrounding the viewer, festival lights strung between buildings, distant ski slopes and white peaks, gently falling snowflakes, twilight blue hour, photorealistic, ultra detailed' }
  ];

  var PANORAMA_CORE_RE = /equirectangular|360\s*degree|panorama|spherical/i;
  var PANORAMA_SEAMLESS_RE = /seamless/i;

  /**
   * 拼接最终全景提示词：用户描述 + 投影技术后缀（缺失时补）+ 工作流画风
   * @param {string} userPrompt 用户场景描述
   * @param {string} ratioStr 比例（如 21:9）
   * @param {string} [styleName] 工作流画风名
   * @returns {string}
   */
  function buildPanoramaPrompt(userPrompt, ratioStr, styleName) {
    var parts = [];
    var prompt = String(userPrompt || '').trim();
    if (prompt) parts.push(prompt);

    // 宽比 >= 2:1 才能水平完整 360°，否则按超宽全景措辞，避免渲染期出现明显接缝落差
    var wideEnough = false;
    var m = String(ratioStr || '').match(/^(\d+(?:\.\d+)?)[:x](\d+(?:\.\d+)?)$/i);
    if (m) wideEnough = parseFloat(m[1]) / parseFloat(m[2]) >= 2;

    var needCore = !PANORAMA_CORE_RE.test(prompt);
    if (needCore) {
      parts.push(wideEnough
        ? '360 degree equirectangular panorama, spherical projection, seamless horizontal wrap, horizon at the vertical center, VR ready'
        : 'ultra wide panoramic view, equirectangular projection, seamless horizontal wrap, VR ready');
    } else if (!PANORAMA_SEAMLESS_RE.test(prompt)) {
      parts.push('seamless horizontal wrap');
    }
    if (styleName) parts.push(styleName);
    return parts.join(', ');
  }

  // 根据比例计算 equirectangular 视场覆盖（等距投影：水平/垂直度/像素一致）
  function computePanoramaFov(ratioStr) {
    var w = 21, h = 9;
    var m = String(ratioStr || '').match(/^(\d+(?:\.\d+)?)[:x](\d+(?:\.\d+)?)$/i);
    if (m) { w = parseFloat(m[1]); h = parseFloat(m[2]); }
    if (w / h >= 2) {
      return { haov: 360, vaov: Math.round(Math.min(180, 360 * h / w) * 10) / 10 };
    }
    return { haov: Math.round(Math.min(360, 180 * w / h) * 10) / 10, vaov: 180 };
  }

  // 从轮询结果提取成功 URL 与首个失败原因（FAILED 任务必须透出 reason）
  // checkVideoStatus 已把任务归一化为 {status, result, error}；result 可能是对象（file_url 等）
  function extractPanoramaResults(statusResult) {
    var out = { urls: [], failReason: '' };
    var tasks = statusResult && Array.isArray(statusResult.tasks) ? statusResult.tasks : null;
    if (tasks) {
      tasks.forEach(function(task) {
        var ok = task.status === 2 || task.status === 'SUCCESS' || task.status === 'success';
        if (ok && task.result) {
          var url = normalizeVideoUrl(task.result);
          if (url) out.urls.push(url);
        } else if (!out.failReason && (task.status === -1 || task.status === 'FAILED' || task.status === 'failed')) {
          out.failReason = task.reason || task.error || '生成失败';
        }
      });
    } else {
      var raw = extractResultsArray(statusResult);
      out.urls = (Array.isArray(raw) ? raw : []).map(normalizeVideoUrl).filter(Boolean);
    }
    return out;
  }

  // ---------- 视角截图 ----------
  // 截图比例选项（透视视角常用比例，非全景展开比例）
  var SNAPSHOT_RATIOS = ['16:9', '9:16', '1:1', '4:3', '3:4', '2:1', '21:9'];

  // 画质 → 目标像素：1K/2K 均指长边像素，短边按比例推导
  function snapshotDimensions(size, ratio) {
    var long = size === '2K' ? 2048 : 1024;
    var w = 16, h = 9;
    var m = String(ratio || '').match(/^(\d+(?:\.\d+)?)[:x](\d+(?:\.\d+)?)$/);
    if (m) { w = parseFloat(m[1]); h = parseFloat(m[2]); }
    if (w >= h) return { width: long, height: Math.round(long * h / w) };
    return { width: Math.round(long * w / h), height: long };
  }

  function dataUrlToBlob(dataUrl) {
    var parts = String(dataUrl).split(',');
    var mime = (parts[0].match(/:(.*?);/) || [])[1] || 'image/jpeg';
    var bin = atob(parts[1]);
    var arr = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new Blob([arr], { type: mime });
  }

  /**
   * 离屏渲染指定视角并导出 JPEG dataURL。
   * 原理：用同一张全景图新建一个隐藏的 pannellum 查看器（容器尺寸=目标分辨率），
   * 复位 yaw/pitch/hfov 渲染首帧后 toDataURL——因此可输出任意比例/分辨率，
   * 而不受屏幕上查看器实际大小的限制。
   * @param {string} proxiedUrl 已走 proxyImageUrl 的同源全景图地址
   * @param {{haov:number, vaov:number}} fov 全景视场（与主查看器一致）
   * @param {{yaw:number, pitch:number, hfov:number}} view 要截取的视角
   * @param {number} width 目标宽度(px)
   * @param {number} height 目标高度(px)
   * @returns {Promise<string>} JPEG dataURL
   */
  function capturePanoramaView(proxiedUrl, fov, view, width, height) {
    return new Promise(function(resolve, reject) {
      if (typeof window.pannellum === 'undefined') {
        reject(new Error('pannellum not loaded'));
        return;
      }
      var container = document.createElement('div');
      container.className = 'panorama-snapshot-stage';
      container.style.width = width + 'px';
      container.style.height = height + 'px';
      document.body.appendChild(container);

      var viewer = null;
      var settled = false;
      var timer = null;
      var cleanup = function() {
        if (timer) { clearTimeout(timer); timer = null; }
        try { if (viewer) viewer.destroy(); } catch (e) { /* ignore */ }
        if (container.parentNode) container.parentNode.removeChild(container);
      };
      var fail = function(err) {
        if (settled) return;
        settled = true;
        cleanup();
        reject(err instanceof Error ? err : new Error(String(err || '截图失败')));
      };

      // 加载超时保护（正常 <2s，网络图代理较慢时放宽）
      timer = setTimeout(function() { fail(new Error('全景图加载超时')); }, 20000);

      try {
        viewer = window.pannellum.viewer(container, {
          type: 'equirectangular',
          panorama: proxiedUrl,
          autoLoad: true,
          haov: fov.haov, vaov: fov.vaov, vOffset: 0,
          // 历史保存的视角可能越界（启用防护前的数据），截图渲染同样约束，避免截出黑边图
          avoidShowingBackground: true,
          yaw: view.yaw || 0,
          pitch: view.pitch || 0,
          hfov: Math.min(120, Math.max(50, view.hfov || 100)),
          showControls: false,
          compass: false,
          mouseZoom: false,
          doubleClickZoom: false
        });
      } catch (e) {
        fail(e);
        return;
      }

      viewer.on('error', function(err) { fail(err); });
      viewer.on('load', function() {
        // 等待首帧渲染落盘（preserveDrawingBuffer 已由 getContext 补丁保证）
        setTimeout(function() {
          if (settled) return;
          try {
            var canvas = container.querySelector('canvas');
            if (!canvas) throw new Error('渲染画布未创建');
            var dataUrl = canvas.toDataURL('image/jpeg', 0.95);
            if (!dataUrl || dataUrl.length < 1000) throw new Error('截图内容为空');
            settled = true;
            cleanup();
            resolve(dataUrl);
          } catch (e) {
            fail(e);
          }
        }, 200);
      });
    });
  }

  // ---------- Pannellum 查看器管理 ----------
  var viewerRegistry = {}; // nodeId -> { viewer, containerId }

  function destroyPanoramaViewer(nodeId) {
    var entry = viewerRegistry[nodeId];
    if (!entry) return;
    try { entry.viewer.destroy(); } catch (e) { /* 容器可能已被移除 */ }
    delete viewerRegistry[nodeId];
  }

  function destroyAllPanoramaViewers() {
    Object.keys(viewerRegistry).forEach(destroyPanoramaViewer);
  }

  window.PanoramaViewerRegistry = {
    destroy: destroyPanoramaViewer,
    destroyAll: destroyAllPanoramaViewers
  };

  /**
   * 在容器内创建 equirectangular 查看器，并隔离事件冒泡（画布不平移/不缩放）
   * @param {HTMLElement} container 已插入 DOM 的容器
   * @param {string} proxiedUrl 经 proxyImageUrl 处理的同源图片地址
   * @param {{haov:number, vaov:number}} fov
   * @param {{yaw:number, pitch:number, hfov:number}} [initialView]
   * @param {{mouseZoom?: boolean, onViewChange?: Function, onReady?: Function}} [opts]
   * @returns {object|null} pannellum viewer 实例
   */
  function createPanoramaViewer(container, proxiedUrl, fov, initialView, opts) {
    if (typeof window.pannellum === 'undefined') return null;
    opts = opts || {};
    if (!container.id) container.id = 'pano-viewer-' + Math.random().toString(36).slice(2, 10);

    var config = {
      type: 'equirectangular',
      panorama: proxiedUrl,
      autoLoad: true,
      haov: fov.haov, vaov: fov.vaov, vOffset: 0,
      // 部分全景（vaov<180° 或 haov<360°）时约束视线/视野不超出图像覆盖，
      // 避免视线转到图像外显示黑色背景（如 21:9 图垂直仅覆盖约154°，仰/俯视到极区外即黑边）
      avoidShowingBackground: true,
      hfov: Math.min(120, Math.max(50, (initialView && initialView.hfov) || 100)),
      minHfov: 50, maxHfov: 120,
      yaw: (initialView && initialView.yaw) || 0,
      pitch: (initialView && initialView.pitch) || 0,
      showControls: false,
      compass: false,
      doubleClickZoom: false,
      mouseZoom: opts.mouseZoom !== false,
      friction: 0.15
    };
    var viewer = window.pannellum.viewer(container, config);

    // 阻断向画布冒泡：节点内拖全景不触发画布平移，滚轮只缩放全景
    container.addEventListener('mousedown', function(e) { e.stopPropagation(); });
    container.addEventListener('wheel', function(e) { e.stopPropagation(); }, { passive: false });
    container.addEventListener('touchstart', function(e) { e.stopPropagation(); }, { passive: true });
    container.addEventListener('contextmenu', function(e) { e.preventDefault(); e.stopPropagation(); });

    if (opts.onViewChange) {
      var report = function() {
        try {
          opts.onViewChange({ yaw: viewer.getYaw(), pitch: viewer.getPitch(), hfov: viewer.getHfov() });
        } catch (e) { /* viewer 可能已销毁 */ }
      };
      viewer.on('mouseup', report);
      viewer.on('animatefinished', report);
    }
    // 历史保存的视角可能越界（启用 avoidShowingBackground 前的数据）：
    // 加载完成后原地跳转一次，触发 pannellum 约束把 yaw/pitch/hfov 校正回图像覆盖内
    viewer.on('load', function() {
      try {
        viewer.setYaw(viewer.getYaw(), 0);
        viewer.setPitch(viewer.getPitch(), 0);
        viewer.setHfov(viewer.getHfov(), 0);
      } catch (e) { /* ignore */ }
    });
    if (opts.onReady) viewer.on('load', opts.onReady);
    viewer.on('error', function(err) {
      console.warn('[全景节点] 查看器加载失败:', err);
    });
    return viewer;
  }

  // ---------- 全屏查看弹层 ----------
  var fullscreenState = null;

  function closePanoramaFullscreen(saveView) {
    if (!fullscreenState) return;
    var st = fullscreenState;
    fullscreenState = null;
    if (st.opts && st.opts.onSaveView && saveView !== false) {
      try {
        st.opts.onSaveView({ yaw: st.viewer.getYaw(), pitch: st.viewer.getPitch(), hfov: st.viewer.getHfov() });
      } catch (e) { /* ignore */ }
    }
    try { st.viewer.destroy(); } catch (e) { /* ignore */ }
    document.removeEventListener('keydown', st.onKeydown);
    if (st.overlay && st.overlay.parentNode) st.overlay.parentNode.removeChild(st.overlay);
  }

  function snapshotSelectHtml(cls, sizeVal, ratioVal) {
    var ratioOpts = SNAPSHOT_RATIOS.map(function(r) {
      return '<option value="' + r + '"' + (r === ratioVal ? ' selected' : '') + '>' + r + '</option>';
    }).join('');
    return '<select class="panorama-fs-select ' + cls + '-size" title="' + tr('panorama_snapshot_size_label', '画质') + '">' +
        '<option value="1K"' + (sizeVal !== '2K' ? ' selected' : '') + '>1K</option>' +
        '<option value="2K"' + (sizeVal === '2K' ? ' selected' : '') + '>2K</option>' +
      '</select>' +
      '<select class="panorama-fs-select ' + cls + '-ratio" title="' + tr('panorama_snapshot_ratio_label', '图片比例') + '">' + ratioOpts + '</select>';
  }

  /**
   * 打开全屏 360 查看弹层
   * @param {string} imageUrl 原始图片地址（内部会走 proxyImageUrl）
   * @param {string} ratioStr 用于计算视场
   * @param {{yaw:number,pitch:number,hfov:number}} [initialView]
   * @param {{onSaveView?:Function, getSnapshot?:Function, setSnapshot?:Function, onSnapshot?:Function}} [opts]
   *   onSaveView 关闭时回传最终视角；getSnapshot/setSnapshot 读写截图设置；onSnapshot(view,size,ratio) 执行截图
   */
  function openPanoramaFullscreen(imageUrl, ratioStr, initialView, opts) {
    closePanoramaFullscreen(false);
    opts = opts || {};
    if (typeof window.pannellum === 'undefined') {
      showToast('全景查看器脚本未加载', 'error');
      return;
    }
    var snapDefaults = (opts.getSnapshot && opts.getSnapshot()) || { size: '1K', ratio: '16:9' };
    if (SNAPSHOT_RATIOS.indexOf(snapDefaults.ratio) === -1) snapDefaults.ratio = '16:9';

    var overlay = document.createElement('div');
    overlay.className = 'panorama-fullscreen-overlay';
    overlay.innerHTML =
      '<div class="panorama-fullscreen-panel">' +
        '<div class="panorama-fullscreen-header">' +
          '<div class="panorama-fullscreen-title">' + (window.t ? window.t('panorama_fullscreen_title') : '360° 全景查看') + '</div>' +
          '<div class="panorama-fullscreen-actions">' +
            snapshotSelectHtml('panorama-fs-snap', snapDefaults.size, snapDefaults.ratio) +
            '<button type="button" class="panorama-fs-btn panorama-fs-snapshot">' + (window.t ? window.t('panorama_snapshot_btn') : '截图') + '</button>' +
            '<button type="button" class="panorama-fs-btn panorama-fs-reset">' + (window.t ? window.t('panorama_reset_view') : '重置视角') + '</button>' +
            '<button type="button" class="panorama-fs-btn panorama-fs-rotate">' + (window.t ? window.t('panorama_auto_rotate') : '自动旋转') + '</button>' +
            '<button type="button" class="panorama-fs-btn panorama-fs-close">✕ ' + (window.t ? window.t('panorama_close') : '关闭') + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="panorama-fullscreen-body"><div class="panorama-fullscreen-viewer"></div></div>' +
        '<div class="panorama-fullscreen-hint">' +
          '<span class="panorama-fs-flash" style="display:none;"></span>' +
          '<span>' + (window.t ? window.t('panorama_fullscreen_hint') : '按住拖拽可环顾 360° 任意角度 · 滚轮缩放视野') + '</span>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);

    var viewerEl = overlay.querySelector('.panorama-fullscreen-viewer');
    var viewer = createPanoramaViewer(viewerEl, proxyImageUrl(imageUrl), computePanoramaFov(ratioStr), initialView, { mouseZoom: true });
    if (!viewer) {
      closePanoramaFullscreen(false);
      showToast('全景查看器脚本未加载', 'error');
      return;
    }
    var rotating = false;
    var flashEl = overlay.querySelector('.panorama-fs-flash');
    var flashTimer = null;
    function showFlash(text, autoHideMs) {
      if (!flashEl) return;
      flashEl.style.display = 'inline-block';
      flashEl.textContent = text;
      if (flashTimer) { clearTimeout(flashTimer); flashTimer = null; }
      if (autoHideMs) flashTimer = setTimeout(function() { flashEl.style.display = 'none'; }, autoHideMs);
    }

    overlay.querySelector('.panorama-fs-close').addEventListener('click', function() { closePanoramaFullscreen(true); });
    overlay.addEventListener('mousedown', function(e) { if (e.target === overlay) closePanoramaFullscreen(true); });
    overlay.querySelector('.panorama-fs-reset').addEventListener('click', function() {
      rotating = false;
      viewer.lookAt(0, 0, 100, 300);
    });
    overlay.querySelector('.panorama-fs-rotate').addEventListener('click', function() {
      if (rotating) { viewer.stopAutoRotate(); rotating = false; }
      else { viewer.startAutoRotate(-2.5); rotating = true; }
    });
    overlay.querySelector('.panorama-fs-snapshot').addEventListener('click', function() {
      if (!opts.onSnapshot) return;
      var sizeSel = overlay.querySelector('.panorama-fs-snap-size');
      var ratioSel = overlay.querySelector('.panorama-fs-snap-ratio');
      var settings = { size: sizeSel ? sizeSel.value : '1K', ratio: ratioSel ? ratioSel.value : '16:9' };
      if (opts.setSnapshot) opts.setSnapshot(settings);
      var view = { yaw: viewer.getYaw(), pitch: viewer.getPitch(), hfov: viewer.getHfov() };
      showFlash(tr('panorama_snapshot_processing', '正在截取当前视角...'));
      Promise.resolve(opts.onSnapshot(view, settings.size, settings.ratio))
        .then(function(result) {
          if (result && result.ok === false) showFlash(result.message || tr('panorama_snapshot_failed', '截图失败'), 3500);
          else showFlash(tr('panorama_snapshot_success', '视角截图已生成图片节点'), 2600);
        });
    });
    var snapSizeSel = overlay.querySelector('.panorama-fs-snap-size');
    var snapRatioSel = overlay.querySelector('.panorama-fs-snap-ratio');
    function syncSnapshotSettings() {
      if (!opts.setSnapshot) return;
      opts.setSnapshot({ size: snapSizeSel ? snapSizeSel.value : '1K', ratio: snapRatioSel ? snapRatioSel.value : '16:9' });
    }
    if (snapSizeSel) snapSizeSel.addEventListener('change', syncSnapshotSettings);
    if (snapRatioSel) snapRatioSel.addEventListener('change', syncSnapshotSettings);

    var onKeydown = function(e) { if (e.key === 'Escape') closePanoramaFullscreen(true); };
    document.addEventListener('keydown', onKeydown);
    fullscreenState = { overlay: overlay, viewer: viewer, onKeydown: onKeydown, opts: opts };
  }

  // ---------- 节点定义 ----------
  var PANORAMA_PORTS = [
    { direction: 'input', titleI18nKey: 'panorama_input_port', cssClass: 'panorama-source-port', acceptType: ['image', 'location'], connectionType: 'connections' },
    { direction: 'output', titleI18nKey: 'panorama_output_port' }
  ];

  // 全景友好的比例（宽优先）；运行时按所选模型 supported_ratios 过滤
  var PANORAMA_RATIO_ORDER = ['21:9', '16:9', '3:2', '4:3', '1:1'];

  function tr(key, fallback, params) {
    var v = window.t ? window.t(key, params) : null;
    return (v && v !== key) ? v : fallback;
  }

  function createPanoramaNode(opts) {
    return createNodeBase({
      type: 'panorama',
      title: function() { return tr('panorama_title', '360全景图'); },
      defaultData: {
        prompt: '',
        url: '',
        preview: '',
        model: '',
        ratio: '21:9',
        drawCount: 1,
        project_ids: null,  // 生成中任务（重载后恢复轮询）
        yaw: 0, pitch: 0, hfov: 100
      },
      ports: PANORAMA_PORTS,
      cssClass: 'panorama-node',
      width: 420,
      titleIcon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 3.5 5.5 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-5.5-3.5-9s1-6.5 3.5-9z"/></svg>',
      bodyHtml: function() {
        return '<div class="field">' +
            '<div class="label" style="margin:0;" data-i18n="panorama_source_label">' + tr('panorama_source_label', '参考图（可选）') + '</div>' +
            '<div class="panorama-source-thumb" style="display:none;">' +
              '<img class="panorama-source-img" style="max-width:100%; max-height:80px; border-radius:4px; border:1px solid #e5e7eb;" />' +
            '</div>' +
            '<div class="muted panorama-source-placeholder" style="font-size:11px;">' + tr('panorama_source_hint', '可连接图片节点作为参考图，不连接则纯文生全景') + '</div>' +
          '</div>' +
          '<div class="field">' +
            '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">' +
              '<div class="label" style="margin:0;" data-i18n="panorama_prompt_label">' + tr('panorama_prompt_label', '场景描述') + '</div>' +
              '<div style="display:flex; gap:6px;">' +
                // position:relative 锚点：模板菜单（absolute, top:100%）据此在模板按钮正下方弹出，
                // 否则会相对整个节点定位、落到节点底部
                '<div style="position:relative;">' +
                  '<button type="button" class="mini-btn panorama-tpl-btn" style="font-size:11px; padding:4px 8px;">' + tr('panorama_template_btn', '模板') + ' ▾</button>' +
                  '<div class="panorama-tpl-menu" style="display:none;">' + PANORAMA_PROMPT_TEMPLATES.map(function(tpl) {
                    return '<div class="panorama-tpl-item" data-tpl="' + tpl.key + '">' + tr('panorama_tpl_' + tpl.key, tpl.key) + '</div>';
                  }).join('') + '</div>' +
                '</div>' +
                '<button type="button" class="mini-btn panorama-prompt-expand-btn" style="font-size:11px; padding:4px 8px;" title="' + tr('script_expand_btn', '放大编辑') + '">\u2922</button>' +
              '</div>' +
            '</div>' +
            '<textarea class="panorama-prompt" rows="3" placeholder="' + tr('panorama_prompt_placeholder', '描述你想身临其境的360°环境，例如：夕阳下的雪山湖泊，四周环山…') + '" style="resize:vertical; min-height:60px;"></textarea>' +
          '</div>' +
          '<div class="field">' +
            '<div class="label" data-i18n="panorama_model_label">' + tr('panorama_model_label', '生成模型') + '</div>' +
            '<select class="panorama-model"></select>' +
          '</div>' +
          '<div class="field">' +
            '<div class="label" data-i18n="panorama_ratio_label">' + tr('panorama_ratio_label', '全景比例（越宽越接近完整360°）') + '</div>' +
            '<select class="panorama-ratio"></select>' +
          '</div>' +
          '<div class="field">' +
            '<div class="btn-row" style="display:flex; gap:8px;">' +
              '<div class="gen-container">' +
                '<button class="gen-btn gen-btn-main panorama-generate-btn" type="button" data-i18n="panorama_generate_btn">' + tr('panorama_generate_btn', '生成全景图') + '</button>' +
                '<button class="gen-btn gen-btn-caret panorama-generate-caret" type="button" aria-label="X1">\u25be</button>' +
                '<div class="gen-menu panorama-gen-menu">' +
                  '<div class="gen-item" data-count="1">X1</div>' +
                  '<div class="gen-item" data-count="2">X2</div>' +
                  '<div class="gen-item" data-count="3">X3</div>' +
                '</div>' +
              '</div>' +
            '</div>' +
            '<div class="gen-meta panorama-draw-count-label"></div>' +
            '<div class="muted panorama-status" style="display:none;"></div>' +
          '</div>' +
          '<div class="field panorama-viewer-field" style="display:none;">' +
            '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">' +
              '<div class="label" style="margin:0;" data-i18n="panorama_preview_label">' + tr('panorama_preview_label', '全景预览') + '</div>' +
              '<div class="panorama-viewer-actions" style="display:flex; gap:6px; position:relative;">' +
                '<button type="button" class="mini-btn panorama-reset-btn" style="font-size:11px; padding:4px 8px;" data-i18n="panorama_reset_view">' + tr('panorama_reset_view', '重置视角') + '</button>' +
                '<button type="button" class="mini-btn panorama-rotate-btn" style="font-size:11px; padding:4px 8px;" data-i18n="panorama_auto_rotate">' + tr('panorama_auto_rotate', '自动旋转') + '</button>' +
                '<button type="button" class="mini-btn panorama-fullscreen-btn" style="font-size:11px; padding:4px 8px;" data-i18n="panorama_fullscreen">' + tr('panorama_fullscreen', '全屏查看') + '</button>' +
                '<button type="button" class="mini-btn panorama-snapshot-btn" style="font-size:11px; padding:4px 8px;" data-i18n="panorama_snapshot_btn">' + tr('panorama_snapshot_btn', '截图') + '</button>' +
                '<div class="panorama-snapshot-menu" style="display:none;">' +
                  '<div class="pano-snap-row">' +
                    '<span class="pano-snap-label" data-i18n="panorama_snapshot_size_label">' + tr('panorama_snapshot_size_label', '画质') + '</span>' +
                    '<select class="panorama-snap-size">' +
                      '<option value="1K" selected>1K</option>' +
                      '<option value="2K">2K</option>' +
                    '</select>' +
                  '</div>' +
                  '<div class="pano-snap-row">' +
                    '<span class="pano-snap-label" data-i18n="panorama_snapshot_ratio_label">' + tr('panorama_snapshot_ratio_label', '图片比例') + '</span>' +
                    '<select class="panorama-snap-ratio">' + SNAPSHOT_RATIOS.map(function(r) {
                      var sel = r === (state.ratio || '16:9') ? ' selected' : '';
                      return '<option value="' + r + '"' + sel + '>' + r + '</option>';
                    }).join('') + '</select>' +
                  '</div>' +
                  '<button type="button" class="mini-btn panorama-snap-confirm" style="align-self:stretch; justify-content:center;" data-i18n="panorama_snapshot_confirm">' + tr('panorama_snapshot_confirm', '截图并生成图片') + '</button>' +
                '</div>' +
              '</div>' +
            '</div>' +
            '<div class="panorama-viewer"></div>' +
            '<div class="muted panorama-viewer-hint" style="font-size:11px;" data-i18n="panorama_view_hint">' + tr('panorama_view_hint', '按住拖拽可环顾四周任意角度') + '</div>' +
          '</div>';
      },
      onCreated: function(node, el) {
        var promptEl = el.querySelector('.panorama-prompt');
        var tplBtn = el.querySelector('.panorama-tpl-btn');
        var tplMenu = el.querySelector('.panorama-tpl-menu');
        var expandBtn = el.querySelector('.panorama-prompt-expand-btn');
        var modelEl = el.querySelector('.panorama-model');
        var ratioEl = el.querySelector('.panorama-ratio');
        var generateBtn = el.querySelector('.panorama-generate-btn');
        var genCaret = el.querySelector('.panorama-generate-caret');
        var genMenu = el.querySelector('.panorama-gen-menu');
        var drawCountLabel = el.querySelector('.panorama-draw-count-label');
        var statusEl = el.querySelector('.panorama-status');
        var viewerField = el.querySelector('.panorama-viewer-field');
        var viewerEl = el.querySelector('.panorama-viewer');
        var viewerHintEl = el.querySelector('.panorama-viewer-hint');
        var resetBtn = el.querySelector('.panorama-reset-btn');
        var rotateBtn = el.querySelector('.panorama-rotate-btn');
        var fullscreenBtn = el.querySelector('.panorama-fullscreen-btn');
        var snapshotBtn = el.querySelector('.panorama-snapshot-btn');
        var snapMenu = el.querySelector('.panorama-snapshot-menu');
        var snapSizeEl = el.querySelector('.panorama-snap-size');
        var snapRatioEl = el.querySelector('.panorama-snap-ratio');
        var snapConfirmBtn = el.querySelector('.panorama-snap-confirm');
        var snapshotBusy = false;
        var sourceThumb = el.querySelector('.panorama-source-thumb');
        var sourceImg = el.querySelector('.panorama-source-img');
        var sourcePlaceholder = el.querySelector('.panorama-source-placeholder');

        var modelOptionsCache = [];
        var rotating = false;

        // 参考图输入端口（支持图片节点；也支持场景节点——自动取场景参考图与描述）
        // 连接走模块级 registerInputPorts('panorama', ...) 注册表吸附路径（见文件末尾），
        // 不再用 bindInputPortEvents 端口直落：两套路径并存会导致查重/单连接限制失效

        function getSourceImageUrl(sourceNode) {
          // 图片节点用 data.url；场景节点用 data.reference_image（与 getNodeImageUrl 语义一致）
          if (!sourceNode || !sourceNode.data) return '';
          if (typeof getNodeImageUrl === 'function') return getNodeImageUrl(sourceNode) || '';
          return sourceNode.data.url || sourceNode.data.preview || sourceNode.data.reference_image || '';
        }

        // 源节点连线后：提示词为空时自动填入（不覆盖已有内容）
        // 场景节点填「场景名，场景描述」；图片节点优先用其编辑提示词，
        // 没有提示词的任意图片（上传图等）由 VL 识图生成场景描述
        function autoFillPromptFromSource(fromNode) {
          if (!fromNode || !fromNode.data) return;
          if (String(node.data.prompt || '').trim()) return; // 已有提示词不覆盖
          if (fromNode.type === 'location') {
            var parts = [];
            if (fromNode.data.name) parts.push(String(fromNode.data.name).trim());
            if (fromNode.data.description) parts.push(String(fromNode.data.description).trim());
            var scenePrompt = parts.filter(Boolean).join('，');
            if (!scenePrompt) return;
            node.data.prompt = scenePrompt;
            promptEl.value = scenePrompt;
            showToast(tr('panorama_scene_prompt_filled', '已按场景「{name}」填充描述，可直接生成该场景的 360 全景图', { name: fromNode.data.name || '' }), 'info');
            safeAutoSave();
          } else if (fromNode.type === 'image') {
            var imgPrompt = String(fromNode.data.prompt || '').trim();
            if (imgPrompt) {
              node.data.prompt = imgPrompt;
              promptEl.value = imgPrompt;
              showToast(tr('panorama_image_prompt_filled', '已按图片节点提示词填充描述，可按需修改'), 'info');
              safeAutoSave();
            } else {
              // 任意图片（上传图/无提示词）→ VL 识图生成场景描述
              var imgUrl = getSourceImageUrl(fromNode);
              if (imgUrl) describeImageIntoPrompt(imgUrl);
            }
          }
        }

        // VL 识图：调用后端视觉模型为图片生成场景描述并填入提示词。
        // 仅新连线触发（工作流重载恢复不会调用）；成功后 prompt 非空，重连不重复识图
        var describeToken = 0;
        // 识图 loading：提示词框 placeholder 动态省略号 + 节点状态行同步提示
        // （识图仅在提示词为空时触发，placeholder 恰好可见，用户视线焦点即在提示词框）
        var promptLoadingTimer = null;
        var promptOriginalPlaceholder = null;
        function setPromptLoading(on) {
          if (on) {
            if (promptLoadingTimer) clearInterval(promptLoadingTimer);
            if (promptOriginalPlaceholder === null) {
              promptOriginalPlaceholder = promptEl.getAttribute('placeholder') || '';
            }
            var base = tr('panorama_describing', '正在识图生成场景描述');
            var dots = 3;
            var tick = function() {
              dots = (dots + 1) % 4;
              var text = base + '.'.repeat(dots);
              promptEl.setAttribute('placeholder', text);
              updateStatus(text, '#666');
            };
            tick();
            promptLoadingTimer = setInterval(tick, 400);
          } else {
            if (promptLoadingTimer) { clearInterval(promptLoadingTimer); promptLoadingTimer = null; }
            if (promptOriginalPlaceholder !== null) {
              promptEl.setAttribute('placeholder', promptOriginalPlaceholder);
              promptOriginalPlaceholder = null;
            }
          }
        }
        function describeImageIntoPrompt(imgUrl) {
          var token = ++describeToken;
          setPromptLoading(true);
          var headers = { 'Content-Type': 'application/json' };
          if (typeof getAuthToken === 'function') headers['Authorization'] = getAuthToken();
          if (typeof getUserId === 'function') headers['X-User-Id'] = getUserId();
          fetch('/api/video-workflow/describe-image', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({ image_url: imgUrl })
          })
            .then(function(r) { return r.json(); })
            .then(function(data) {
              if (token !== describeToken) return; // 已重新识图/换源，新调用已接管 loading
              setPromptLoading(false);
              if (data && data.success && data.description) {
                statusEl.style.display = 'none';
                // 等待期间用户已手动输入则不覆盖
                if (String(node.data.prompt || '').trim() || promptEl.value.trim()) return;
                node.data.prompt = data.description;
                promptEl.value = data.description;
                showToast(tr('panorama_image_prompt_described', '已识图生成场景描述，可按需修改'), 'info');
                safeAutoSave();
              } else {
                updateStatus(tr('panorama_describe_failed', '识图生成描述失败，可手动输入'), '#d97706');
              }
            })
            .catch(function() {
              if (token !== describeToken) return;
              setPromptLoading(false);
              updateStatus(tr('panorama_describe_failed', '识图生成描述失败，可手动输入'), '#d97706');
            });
        }

        function updateSourceThumbnail() {
          var conn = state.connections.find(function(c) { return c.to === node.id; });
          var sourceNode = conn ? state.nodes.find(function(n) { return n.id === conn.from; }) : null;
          var url = sourceNode ? getSourceImageUrl(sourceNode) : null;
          if (url) {
            sourceImg.src = proxyImageUrl(url);
            sourceThumb.style.display = 'block';
            sourcePlaceholder.style.display = 'none';
          } else {
            sourceThumb.style.display = 'none';
            sourcePlaceholder.style.display = 'block';
            sourcePlaceholder.textContent = conn
              ? tr('panorama_source_no_image', '源图片节点没有图片')
              : tr('panorama_source_hint', '可连接图片/场景节点作为参考图，不连接则纯文生全景');
          }
        }
        el._updateSourceThumbnail = updateSourceThumbnail;
        el._autoFillPromptFromSource = autoFillPromptFromSource;
        updateSourceThumbnail();

        // 提示词输入
        promptEl.addEventListener('input', function() {
          node.data.prompt = promptEl.value;
          safeAutoSave();
        });
        expandBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          showPromptExpandModal(promptEl, tr('panorama_prompt_label', '场景描述'), function(newValue) {
            node.data.prompt = newValue;
            promptEl.value = newValue;
            safeAutoSave();
          });
        });

        // 模板菜单
        tplBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          tplMenu.style.display = tplMenu.style.display === 'none' ? 'block' : 'none';
        });
        Array.prototype.forEach.call(tplMenu.querySelectorAll('.panorama-tpl-item'), function(item) {
          item.addEventListener('click', function(e) {
            e.stopPropagation();
            var tpl = PANORAMA_PROMPT_TEMPLATES.find(function(t) { return t.key === item.dataset.tpl; });
            if (tpl) {
              promptEl.value = tpl.text;
              node.data.prompt = tpl.text;
              safeAutoSave();
            }
            tplMenu.style.display = 'none';
          });
        });
        // 点击模板按钮/菜单以外任意区域收起菜单（节点销毁时随 onDestroy 移除）
        var onTplMenuDismiss = function(e) {
          if (tplMenu.style.display === 'none') return;
          if (e.target && e.target.closest && e.target.closest('.panorama-tpl-btn, .panorama-tpl-menu')) return;
          tplMenu.style.display = 'none';
        };
        document.addEventListener('mousedown', onTplMenuDismiss);

        // 模型下拉（文生图分类；参考图模式复用同模型的 image_edit task_id）
        function populateModelOptions() {
          if (!modelEl) return;
          modelEl.innerHTML = '';
          if (window.TaskConfig && window.TaskConfig.isLoaded()) {
            modelOptionsCache = window.TaskConfig.getModelOptionsForCategory('text_to_image');
            if (modelOptionsCache.length === 0) {
              modelOptionsCache = window.TaskConfig.getModelOptionsForCategory('image_edit');
            }
          } else {
            modelOptionsCache = [];
          }
          if (modelOptionsCache.length === 0) {
            modelOptionsCache = [
              { value: 'seedream-5.0', label: 'Seedream 5.0', computingPower: 6 },
              { value: 'seedream-4.5', label: 'Seedream 4.5', computingPower: 8 },
              { value: 'gpt-image-2', label: 'GPT Image 2', computingPower: 4 }
            ];
          }
          modelOptionsCache.forEach(function(opt) {
            var optEl = document.createElement('option');
            optEl.value = opt.value;
            optEl.textContent = opt.label;
            modelEl.appendChild(optEl);
          });
          // 过滤未配置实现方的模型（保留已保存值但标注）
          if (typeof applyDriverStatusToSelect === 'function') {
            applyDriverStatusToSelect(modelEl, node.data.model);
            modelOptionsCache = modelOptionsCache.filter(function(o) {
              var optEl = modelEl.querySelector('option[value="' + o.value + '"]');
              return optEl && !optEl.disabled;
            });
          }
          // 默认模型：优先「可用 且 支持宽幅全景比例（宽比≥2:1）」，否则第一个可用项
          if (!node.data.model) {
            var preferred = modelOptionsCache.find(function(o) {
              if (o.value === 'seedream-5.0') return true;
              try {
                var ratios = window.TaskConfig.getRatioOptions(o.value) || [];
                return ratios.some(function(r) {
                  var m = String(r).match(/^(\d+(?:\.\d+)?)[:x](\d+(?:\.\d+)?)$/i);
                  return m && parseFloat(m[1]) / parseFloat(m[2]) >= 2;
                });
              } catch (e) { return false; }
            });
            if (!preferred && modelEl.options.length > 0) {
              var firstOpt = modelOptionsCache.find(function(o) { return o.value === modelEl.options[0].value; });
              preferred = firstOpt || modelOptionsCache[0];
            }
            if (preferred) node.data.model = preferred.value;
          }
          if (!node.data.model && modelOptionsCache.length > 0) node.data.model = modelOptionsCache[0].value;
          ensureSelectHasSavedOption(modelEl, node.data.model);
          modelEl.value = node.data.model;
          updateRatioOptions();
        }

        // 比例下拉：按模型 supported_ratios 过滤出宽比例
        // 宽比≥2:1 可水平完整 360°，其中越接近 2:1 垂直覆盖越大（21:9≈154° 优于 8:1=45°）；
        // 若模型无 ≥2:1 的比例，退化为超宽部分全景（宽比降序）
        function updateRatioOptions() {
          if (!ratioEl) return;
          var model = node.data.model;
          var supported = null;
          if (window.TaskConfig && window.TaskConfig.isLoaded()) {
            try { supported = window.TaskConfig.getRatioOptions(model); } catch (e) { supported = null; }
          }
          function ratioOf(r) {
            var m = String(r).match(/^(\d+(?:\.\d+)?)[:x](\d+(?:\.\d+)?)$/i);
            return m ? parseFloat(m[1]) / parseFloat(m[2]) : 0;
          }
          var candidates = (supported && supported.length)
            ? supported.filter(function(r) { return ratioOf(r) > 1; })
            : PANORAMA_RATIO_ORDER.slice();
          var hasFullWrap = candidates.some(function(r) { return ratioOf(r) >= 2; });
          // 两段排序：完整环绕组（≥2:1，越接近 2:1 垂直覆盖越大）在前，部分全景组按宽度降序在后
          candidates.sort(function(a, b) {
            var pa = ratioOf(a), pb = ratioOf(b);
            var fa = pa >= 2, fb = pb >= 2;
            if (fa !== fb) return fa ? -1 : 1;
            return fa ? Math.abs(pa - 2) - Math.abs(pb - 2) : pb - pa;
          });
          if (!hasFullWrap) candidates = candidates.filter(function(r) { return ratioOf(r) > 1; });
          if (candidates.length === 0) candidates = ['16:9'];
          ratioEl.innerHTML = '';
          candidates.forEach(function(r) {
            var optEl = document.createElement('option');
            optEl.value = r;
            var fov = computePanoramaFov(r);
            optEl.textContent = r + ' (' + (fov.haov >= 360
              ? tr('panorama_ratio_full', '水平360°完整环绕')
              : tr('panorama_ratio_coverage', '水平 {deg}°', { deg: Math.round(fov.haov) })) + ')';
            ratioEl.appendChild(optEl);
          });
          if (candidates.indexOf(node.data.ratio) === -1) {
            node.data.ratio = candidates[0];
          }
          ensureSelectHasSavedOption(ratioEl, node.data.ratio);
          ratioEl.value = node.data.ratio;
        }

        populateModelOptions();
        if (window.TaskConfig && window.TaskConfig.onLoaded) {
          window.TaskConfig.onLoaded(function() { populateModelOptions(); });
        }

        modelEl.addEventListener('change', function() {
          node.data.model = modelEl.value;
          updateRatioOptions();
          safeAutoSave();
        });
        ratioEl.addEventListener('change', function() {
          node.data.ratio = ratioEl.value;
          // 比例变化影响视场覆盖，已生成的图需要重建查看器
          if (node.data.url) showViewer(node.data.url, true);
          safeAutoSave();
        });

        // 抽卡次数
        function updateDrawCountLabel() {
          drawCountLabel.textContent = tr('draw_count_x', '抽卡次数：X{count}', { count: node.data.drawCount || 1 });
        }
        updateDrawCountLabel();
        genCaret.addEventListener('click', function(e) {
          e.stopPropagation();
          genMenu.classList.toggle('show');
        });
        Array.prototype.forEach.call(genMenu.querySelectorAll('.gen-item'), function(item) {
          item.addEventListener('click', function(e) {
            e.stopPropagation();
            node.data.drawCount = Number(item.dataset.count || '1');
            updateDrawCountLabel();
            genMenu.classList.remove('show');
          });
        });

        // ---------- 全景查看器 ----------
        function showViewer(imageUrl, resetView) {
          destroyPanoramaViewer(node.id);
          viewerField.style.display = 'flex';
          viewerEl.innerHTML = '';
          var initial = resetView ? { yaw: 0, pitch: 0, hfov: 100 } : {
            yaw: node.data.yaw || 0, pitch: node.data.pitch || 0, hfov: node.data.hfov || 100
          };
          var viewer = createPanoramaViewer(viewerEl, proxyImageUrl(imageUrl), computePanoramaFov(node.data.ratio), initial, {
            mouseZoom: false,
            onViewChange: function(view) {
              node.data.yaw = Math.round(view.yaw * 10) / 10;
              node.data.pitch = Math.round(view.pitch * 10) / 10;
              node.data.hfov = Math.round(view.hfov * 10) / 10;
              safeAutoSave();
            }
          });
          if (viewer) {
            viewerRegistry[node.id] = { viewer: viewer };
          } else {
            // pannellum 未加载时降级为平面预览
            viewerEl.innerHTML = '<img src="' + proxyImageUrl(imageUrl) + '" style="width:100%; border-radius:6px; display:block;" />';
            showToast(tr('panorama_viewer_missing', '全景查看器脚本未加载，已降级为平面预览'), 'warning');
          }
        }
        el._showPanoramaViewer = showViewer;

        function saveCurrentView() {
          var entry = viewerRegistry[node.id];
          if (!entry) return;
          try {
            node.data.yaw = Math.round(entry.viewer.getYaw() * 10) / 10;
            node.data.pitch = Math.round(entry.viewer.getPitch() * 10) / 10;
            node.data.hfov = Math.round(entry.viewer.getHfov() * 10) / 10;
          } catch (e) { /* ignore */ }
        }

        resetBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          var entry = viewerRegistry[node.id];
          rotating = false;
          if (entry) entry.viewer.lookAt(0, 0, 100, 300);
        });
        rotateBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          var entry = viewerRegistry[node.id];
          if (!entry) return;
          if (rotating) { entry.viewer.stopAutoRotate(); rotating = false; }
          else { entry.viewer.startAutoRotate(-2.5); rotating = true; }
        });
        fullscreenBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          if (!node.data.url) return;
          saveCurrentView();
          openPanoramaFullscreen(node.data.url, node.data.ratio, {
            yaw: node.data.yaw, pitch: node.data.pitch, hfov: node.data.hfov
          }, {
            onSaveView: function(view) {
              node.data.yaw = Math.round(view.yaw * 10) / 10;
              node.data.pitch = Math.round(view.pitch * 10) / 10;
              node.data.hfov = Math.round(view.hfov * 10) / 10;
              var entry = viewerRegistry[node.id];
              if (entry) entry.viewer.lookAt(view.pitch, view.yaw, view.hfov, 0);
              safeAutoSave();
            },
            getSnapshot: getSnapshotSettings,
            setSnapshot: persistSnapshotSettings,
            onSnapshot: function(view, size, ratio) { return runSnapshot(view, size, ratio); }
          });
        });

        // ---------- 视角截图 ----------
        function getSnapshotSettings() {
          return {
            size: (snapSizeEl && snapSizeEl.value) || '1K',
            ratio: (snapRatioEl && snapRatioEl.value) || state.ratio || '16:9'
          };
        }

        function persistSnapshotSettings() {
          node.data.snapshot = getSnapshotSettings();
          safeAutoSave();
        }

        // 截图管线：离屏渲染 → 上传 → 创建图片节点并连线
        // 始终 resolve（{ok, message}），失败不抛出——调用方（节点/全屏）按结果提示
        function runSnapshot(view, size, ratio) {
          if (!node.data.url) return Promise.resolve({ ok: false, message: 'no panorama' });
          if (snapshotBusy) return Promise.resolve({ ok: false, message: 'busy' });
          snapshotBusy = true;
          var dims = snapshotDimensions(size, ratio);
          setBtnLoading(snapConfirmBtn, tr('panorama_snapshot_processing', '正在截取当前视角...'));
          return capturePanoramaView(proxyImageUrl(node.data.url), computePanoramaFov(node.data.ratio), view, dims.width, dims.height)
            .then(function(dataUrl) {
              var blob = dataUrlToBlob(dataUrl);
              var file = new File([blob], 'panorama_snapshot_' + Date.now() + '.jpg', { type: 'image/jpeg' });
              return uploadFile(file);
            })
            .then(function(uploadedUrl) {
              if (!uploadedUrl) throw new Error(tr('panorama_snapshot_upload_failed', '截图上传失败'));
              var normalized = normalizeImageUrl(uploadedUrl);
              createSnapshotImageNode(normalized, ratio);
              showToast(tr('panorama_snapshot_success', '视角截图已生成图片节点'), 'success');
              safeAutoSave();
              if (typeof fetchComputingPower === 'function') fetchComputingPower();
              return { ok: true };
            })
            .catch(function(err) {
              var msg = tr('panorama_snapshot_failed', '截图失败: {error}', { error: (err && err.message) || err });
              showToast(msg, 'error');
              return { ok: false, message: msg };
            })
            .finally(function() {
              snapshotBusy = false;
              setBtnReady(snapConfirmBtn, tr('panorama_snapshot_confirm', '截图并生成图片'));
              if (snapMenu) snapMenu.style.display = 'none';
            });
        }

        // 截图落画布：创建标准图片节点（全景 → 图片 连线），供下游节点复用
        function createSnapshotImageNode(url, ratio) {
          // 携带全景场景描述：截图内容即该场景的某个视角，下游连线可自动适配提示词
          var newNodeId = createImageNode({ x: node.x + 460, y: node.y + 320, checkCollision: true, data: { prompt: String(node.data.prompt || '').trim() } });
          var newNode = state.nodes.find(function(n) { return n.id === newNodeId; });
          if (!newNode) return;
          newNode.data.name = tr('panorama_snapshot_name', '全景截图');
          newNode.data.url = url;
          newNode.data.preview = url;
          if (ratio) newNode.data.ratio = ratio;
          newNode.title = newNode.data.name;
          var newEl = canvasEl.querySelector('.node[data-node-id="' + newNodeId + '"]');
          if (newEl) {
            var titleEl = newEl.querySelector('.node-title');
            if (titleEl) titleEl.textContent = newNode.title;
            var previewImg = newEl.querySelector('.image-preview');
            var previewRow = newEl.querySelector('.image-preview-row');
            if (previewImg && previewRow) {
              previewImg.src = proxyImageUrl(url);
              previewRow.style.display = 'flex';
            }
          }
          state.connections.push({ id: state.nextConnId++, from: node.id, to: newNodeId });
          renderAllConnections();
          renderMinimap();
        }

        if (snapshotBtn) {
          snapshotBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            if (!node.data.url) return;
            if (!snapMenu) return;
            snapMenu.style.display = snapMenu.style.display === 'none' ? 'flex' : 'none';
          });
        }
        if (snapConfirmBtn) {
          snapConfirmBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            persistSnapshotSettings();
            saveCurrentView();
            var settings = getSnapshotSettings();
            runSnapshot(
              { yaw: node.data.yaw || 0, pitch: node.data.pitch || 0, hfov: node.data.hfov || 100 },
              settings.size, settings.ratio
            );
          });
        }
        Array.prototype.forEach.call([snapSizeEl, snapRatioEl], function(selEl) {
          if (selEl) {
            selEl.addEventListener('change', function() { persistSnapshotSettings(); });
            selEl.addEventListener('click', function(e) { e.stopPropagation(); });
            selEl.addEventListener('mousedown', function(e) { e.stopPropagation(); });
          }
        });

        // 节点删除时销毁 WebGL 上下文（由 canvas.js removeNode 钩子调用）
        node.onDestroy = function() {
          setPromptLoading(false);
          document.removeEventListener('mousedown', onTplMenuDismiss);
          destroyPanoramaViewer(node.id);
        };

        // ---------- 生成 ----------
        function updateStatus(text, color) {
          statusEl.style.display = 'block';
          statusEl.style.color = color || '#666';
          statusEl.textContent = text;
        }

        generateBtn.addEventListener('click', async function(e) {
          e.stopPropagation();
          var prompt = String(promptEl.value || '').trim();
          if (!prompt) {
            showToast(tr('panorama_no_prompt', '请先输入场景描述（可点击"模板"快速填充）'), 'warning');
            return;
          }

          // 参考图（可选，支持图片节点/场景节点）
          var conn = state.connections.find(function(c) { return c.to === node.id; });
          var sourceNode = conn ? state.nodes.find(function(n) { return n.id === conn.from; }) : null;
          var refImageUrl = sourceNode ? getSourceImageUrl(sourceNode) : '';
          var category = refImageUrl ? 'image_edit' : 'text_to_image';

          var model = node.data.model;
          var taskId = window.TaskConfig ? window.TaskConfig.getTaskIdByKey(model, category) : null;
          if (!taskId) {
            showToast(tr('panorama_task_config_missing', '未找到该模型的任务配置，请稍后重试'), 'error');
            return;
          }

          var styleName = state.style && state.style.name ? state.style.name : '';
          var finalPrompt = buildPanoramaPrompt(prompt, node.data.ratio, styleName);
          var ratio = node.data.ratio || '21:9';
          var drawCount = node.data.drawCount || 1;

          // 算力预检（可选，失败不阻塞）
          var userId = localStorage.getItem('user_id');
          var authToken = localStorage.getItem('auth_token') || '';
          var modelOpt = modelOptionsCache.find(function(o) { return o.value === model; });
          var powerValue = modelOpt && modelOpt.computingPower;
          if (powerValue && typeof powerValue === 'object') powerValue = Object.values(powerValue)[0];
          var totalPower = (typeof powerValue === 'number' ? powerValue : 0) * drawCount;
          if (userId && totalPower > 0) {
            try {
              var checkRes = await fetch('/api/user/computing_power', { headers: { 'Authorization': 'Bearer ' + authToken } });
              var checkData = await checkRes.json();
              if (checkData.success && checkData.data) {
                var userPower = checkData.data.computing_power != null ? checkData.data.computing_power : 0;
                if (userPower < totalPower) {
                  showToast(tr('panorama_insufficient_power', '算力不足（需要 {need}，当前 {current}）', { need: totalPower, current: userPower }), 'error');
                  return;
                }
              }
            } catch (err) {
              console.warn('[全景节点] 检查算力失败:', err);
            }
          }

          var form = new FormData();
          form.append('task_id', taskId);
          form.append('prompt', finalPrompt);
          form.append('count', String(drawCount));
          if (refImageUrl) {
            form.append('ref_image_urls', refImageUrl);
            form.append('ratio', ratio);
          } else {
            form.append('aspect_ratio', ratio);
          }
          if (userId) form.append('user_id', userId);
          if (authToken) form.append('auth_token', authToken);

          setBtnLoading(generateBtn, tr('panorama_generating', '生成中...'));
          updateStatus(tr('panorama_submitting', '正在提交任务（{count}张，预计消耗 {power} 算力）...', { count: drawCount, power: totalPower || '?' }));

          try {
            var res = await fetch(refImageUrl ? '/api/image-edit' : '/api/text-to-image', { method: 'POST', body: form });
            if (!res.ok) {
              var errData = await res.json().catch(function() { return {}; });
              throw new Error(errData.detail || errData.message || 'HTTP ' + res.status);
            }
            var data = await res.json();
            if (!data.project_ids || data.project_ids.length === 0) {
              throw new Error(data.detail || data.message || tr('panorama_submit_failed', '提交任务失败'));
            }
            var projectIds = data.project_ids;
            node.data.project_ids = projectIds;
            safeAutoSave();
            showToast(tr('panorama_submitted', '任务已提交，正在生成全景图...'), 'info');

            // 为每张结果创建标准图片节点（可被下游节点复用），并连接 全景 → 图片
            var createdImageNodeIds = [];
            for (var i = 0; i < projectIds.length; i++) {
              // 结果节点携带生成提示词（含 360° 全景后缀，忠实描述结果图），供下游连线适配
              var newNodeId = createImageNode({ x: node.x + 460, y: node.y + i * 280, checkCollision: true, data: { prompt: finalPrompt } });
              var newNode = state.nodes.find(function(n) { return n.id === newNodeId; });
              if (newNode) {
                newNode.data.name = projectIds.length > 1 ? ('全景图' + (i + 1)) : '全景图';
                newNode.data.project_id = projectIds[i] || projectIds[0];
                newNode.title = newNode.data.name;
                var newEl = canvasEl.querySelector('.node[data-node-id="' + newNodeId + '"]');
                if (newEl) {
                  var titleEl = newEl.querySelector('.node-title');
                  if (titleEl) titleEl.textContent = newNode.title;
                }
                state.connections.push({ id: state.nextConnId++, from: node.id, to: newNodeId });
                createdImageNodeIds.push(newNodeId);
              }
            }
            renderAllConnections();
            renderMinimap();

            pollVideoStatus(
              projectIds,
              function(progressText) {
                generateBtn.textContent = progressText;
                statusEl.textContent = progressText;
              },
              function(statusResult) {
                node.data.project_ids = null;
                var result = extractPanoramaResults(statusResult);
                var imageUrls = result.urls;
                if (imageUrls.length === 0) {
                  setBtnReady(generateBtn, tr('panorama_generate_btn', '生成全景图'));
                  updateStatus(tr('panorama_gen_failed', '生成失败: {error}', { error: result.failReason || tr('panorama_no_result', '生成完成，但未获取到图片地址') }), '#ef4444');
                  return;
                }

                // 全景节点展示第一张，其余留在图片节点
                node.data.url = normalizeImageUrl(imageUrls[0]);
                node.data.preview = node.data.url;
                showViewer(node.data.url, true);

                // 回填图片节点（若全局轮询尚未回填）
                imageUrls.forEach(function(imageUrl, index) {
                  if (index >= createdImageNodeIds.length) return;
                  var imageNode = state.nodes.find(function(n) { return n.id === createdImageNodeIds[index]; });
                  if (imageNode && !imageNode.data.url) {
                    var normalized = normalizeImageUrl(imageUrl);
                    imageNode.data.url = normalized;
                    imageNode.data.preview = normalized;
                    var imageNodeEl = canvasEl.querySelector('.node[data-node-id="' + imageNode.id + '"]');
                    if (imageNodeEl) {
                      var previewImg = imageNodeEl.querySelector('.image-preview');
                      var previewRow = imageNodeEl.querySelector('.image-preview-row');
                      if (previewImg && previewRow) {
                        previewImg.src = proxyImageUrl(imageUrl);
                        previewRow.style.display = 'flex';
                      }
                    }
                  }
                });

                renderAllConnections();
                setBtnReady(generateBtn, tr('panorama_generate_btn', '生成全景图'));
                updateStatus(tr('panorama_success', '全景图生成成功！拖拽预览图可环顾四周，或点击"全屏查看"'), '#22c55e');
                showToast(tr('panorama_success_toast', '360°全景图生成成功！'), 'success');
                safeAutoSave();
                if (typeof fetchComputingPower === 'function') fetchComputingPower();
              },
              function(error) {
                node.data.project_ids = null;
                var errMsg = tr('panorama_gen_failed', '生成失败: {error}', { error: error });
                showToast(errMsg, 'error');
                setBtnReady(generateBtn, tr('panorama_generate_btn', '生成全景图'));
                updateStatus(errMsg, '#dc2626');
                safeAutoSave();
              }
            );
          } catch (error) {
            console.error('[全景节点] 生成失败:', error);
            node.data.project_ids = null;
            setBtnReady(generateBtn, tr('panorama_generate_btn', '生成全景图'));
            updateStatus('生成失败: ' + (error.message || error), '#dc2626');
            showToast('生成失败: ' + (error.message || error), 'error');
          }
        });

        // ---------- 重载/恢复 ----------
        el._restorePanoramaState = function() {
          // createNodeWithDataFactory 在 onCreated 之后才回填 node.data，
          // 这里重新同步模型/比例下拉框为保存值
          populateModelOptions();
          if (node.data.prompt) promptEl.value = node.data.prompt;
          // 恢复截图设置（画质/比例）
          if (node.data.snapshot) {
            if (snapSizeEl && node.data.snapshot.size) snapSizeEl.value = node.data.snapshot.size;
            if (snapRatioEl && node.data.snapshot.ratio && SNAPSHOT_RATIOS.indexOf(node.data.snapshot.ratio) !== -1) {
              snapRatioEl.value = node.data.snapshot.ratio;
            }
          }
          updateDrawCountLabel();
          updateSourceThumbnail();
          if (node.data.url) {
            showViewer(node.data.url, false); // 复原保存的视角
          } else if (node.data.project_ids && node.data.project_ids.length) {
            // 生成中刷新页面：恢复轮询，完成后自动点亮查看器
            updateStatus(tr('panorama_resuming', '检测到生成中的任务，正在恢复轮询...'));
            setBtnLoading(generateBtn, tr('panorama_generating', '生成中...'));
            var pendingIds = node.data.project_ids.slice();
            pollVideoStatus(
              pendingIds,
              function(progressText) {
                generateBtn.textContent = progressText;
                statusEl.textContent = progressText;
              },
              function(statusResult) {
                node.data.project_ids = null;
                var result = extractPanoramaResults(statusResult);
                if (result.urls.length > 0) {
                  node.data.url = normalizeImageUrl(result.urls[0]);
                  node.data.preview = node.data.url;
                  showViewer(node.data.url, true);
                  updateStatus(tr('panorama_success', '全景图生成成功！拖拽预览图可环顾四周，或点击"全屏查看"'), '#22c55e');
                } else {
                  updateStatus(tr('panorama_gen_failed', '生成失败: {error}', { error: result.failReason || tr('panorama_no_result', '生成完成，但未获取到图片地址') }), '#ef4444');
                }
                setBtnReady(generateBtn, tr('panorama_generate_btn', '生成全景图'));
                safeAutoSave();
              },
              function(error) {
                node.data.project_ids = null;
                setBtnReady(generateBtn, tr('panorama_generate_btn', '生成全景图'));
                updateStatus(tr('panorama_gen_failed', '生成失败: {error}', { error: error }), '#dc2626');
                safeAutoSave();
              }
            );
          }
        };
      }
    }, opts);
  }

  var createPanoramaNodeWithData = createNodeWithDataFactory(
    createPanoramaNode,
    function(el, node) {
      if (typeof el._restorePanoramaState === 'function') el._restorePanoramaState();
    }
  );

  // 注册到全局
  window.createPanoramaNode = createPanoramaNode;
  window.createPanoramaNodeWithData = createPanoramaNodeWithData;
  window.buildPanoramaPrompt = buildPanoramaPrompt;
  window.computePanoramaFov = computePanoramaFov;
  window.PanoramaSnapshot = {
    capture: capturePanoramaView,
    dimensions: snapshotDimensions,
    ratios: SNAPSHOT_RATIOS
  };

  // 注册到节点注册表
  registerNodeType('panorama', {
    createFn: createPanoramaNode,
    createWithDataFn: createPanoramaNodeWithData
  });

  // ── 注册参考图输入端口（供连接系统自动发现）───
  // 图片/场景节点拖线到全景节点附近即可吸附连接（50px），不再要求精确落在端口圆点上
  if (typeof registerInputPorts === 'function') {
    registerInputPorts('panorama', [{
      selector: '.port.input.panorama-source-port',
      portType: 'panorama-source',
      accepts: ['image', 'location'],
      connectionType: 'connections',
      // 无参考图也允许连接：场景节点可仅提供描述（自动填提示词），生成时走纯文生全景
      allowMissingImage: true,
      onConnect: function(fromNode, targetNode) {
        var targetEl = canvasEl.querySelector('.node[data-node-id="' + targetNode.id + '"]');
        if (!targetEl) return;
        if (typeof targetEl._updateSourceThumbnail === 'function') targetEl._updateSourceThumbnail();
        if (typeof targetEl._autoFillPromptFromSource === 'function') targetEl._autoFillPromptFromSource(fromNode);
      }
    }]);
  }

})();
