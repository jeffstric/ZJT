/**
 * 弹窗公告（popup=1 的公告在页面加载时强弹窗展示，已读后不再弹）
 *
 * 与公告中心（announcement_center.js，仅首页铃铛）互补：本组件自包含、零模板依赖，
 * 在 index / marketing_agent / video_workflow 等主要页面引入即可，覆盖存量活跃用户
 * （无需重新登录）。已读状态走服务端 announcement_reads per-user 表（跨设备一致）。
 *
 * 触发时机：
 * - DOMContentLoaded 自动检测一次（覆盖携带 localStorage token 进入的所有场景，
 *   含 401 → 首页登录 → redirect 回原页面的链路）
 * - 首页登录成功后显式调用 window.AnnouncementPopup.maybeShow()（index_app.js）
 *
 * 多条未读弹窗公告：每次页面加载只弹最新一条（标记已读后下次进页再弹下一条，不轰炸）。
 * 安全：动态内容一律 textContent/属性赋值（不走 innerHTML），链接仅允许 http(s)。
 */
(function () {
  'use strict';

  var DISMISS_GUARD_MS = 60 * 1000;   // 会话内防重复：关闭后短时间内不再弹（含 SPA 路由）

  var _inPageVisible = false;
  var _lastClosedAt = 0;

  function getToken() {
    try { return localStorage.getItem('auth_token') || ''; } catch (e) { return ''; }
  }

  function safeHref(url) {
    // 与后端校验一致：http(s) 或站内相对路径（/ 开头，排除协议相对 //）
    var u = String(url || '').trim();
    if (/^https?:\/\//i.test(u)) return u;
    if (/^\//.test(u) && !/^\/\//.test(u)) return u;
    return '';
  }

  function ensureStyles() {
    if (document.getElementById('ann-popup-style')) return;
    var style = document.createElement('style');
    style.id = 'ann-popup-style';
    style.textContent = [
      '.annp-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:99999;',
      '  display:flex;align-items:center;justify-content:center;padding:16px;}',
      '.annp-modal{background:#fff;color:#1f2937;border-radius:12px;max-width:520px;width:100%;',
      '  max-height:82vh;overflow:auto;box-shadow:0 12px 48px rgba(0,0,0,.35);',
      '  font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;}',
      '.annp-head{padding:18px 22px 0;}',
      '.annp-badge{display:inline-block;font-size:12px;color:#2563eb;background:#eff6ff;',
      '  border:1px solid #bfdbfe;border-radius:4px;padding:2px 8px;margin-bottom:10px;}',
      '.annp-title{font-size:17px;font-weight:700;line-height:1.5;margin:0;}',
      '.annp-body{padding:12px 22px 4px;font-size:14px;line-height:1.75;',
      '  white-space:pre-wrap;word-break:break-word;}',
      '.annp-imgs{padding:4px 22px 0;}',
      '.annp-imgs img{max-width:100%;border-radius:8px;margin-top:10px;display:block;}',
      '.annp-foot{padding:16px 22px 20px;display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap;}',
      '.annp-btn{border-radius:8px;padding:9px 18px;font-size:14px;cursor:pointer;border:1px solid #d1d5db;',
      '  background:#fff;color:#374151;}',
      '.annp-btn:hover{background:#f3f4f6;}',
      '.annp-btn.primary{background:#2563eb;border-color:#2563eb;color:#fff;}',
      '.annp-btn.primary:hover{background:#1d4ed8;}'
    ].join('\n');
    document.head.appendChild(style);
  }

  function buildModal(item, onClose) {
    ensureStyles();
    var overlay = document.createElement('div');
    overlay.className = 'annp-overlay';

    var modal = document.createElement('div');
    modal.className = 'annp-modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');

    var head = document.createElement('div');
    head.className = 'annp-head';
    var badge = document.createElement('span');
    badge.className = 'annp-badge';
    badge.textContent = '通知';
    var title = document.createElement('h3');
    title.className = 'annp-title';
    title.textContent = item.title || '';   // textContent 防注入
    head.appendChild(badge);
    head.appendChild(title);

    var body = document.createElement('div');
    body.className = 'annp-body';
    body.textContent = item.content || '';

    modal.appendChild(head);
    modal.appendChild(body);

    var href = safeHref(item.link_url);
    var images = Array.isArray(item.images) ? item.images.slice(0, 4) : [];
    if (images.length) {
      var imgsWrap = document.createElement('div');
      imgsWrap.className = 'annp-imgs';
      images.forEach(function (src) {
        var u = safeHref(src);
        if (!u) return;
        var img = document.createElement('img');
        img.src = u;                 // 属性赋值（非 innerHTML），带尺寸约束
        img.alt = '';
        img.loading = 'lazy';
        imgsWrap.appendChild(img);
      });
      modal.appendChild(imgsWrap);
    }

    var foot = document.createElement('div');
    foot.className = 'annp-foot';
    if (href && item.link_text) {
      var linkBtn = document.createElement('button');
      linkBtn.className = 'annp-btn';
      linkBtn.textContent = String(item.link_text).slice(0, 30);
      linkBtn.addEventListener('click', function () {
        window.open(href, '_blank', 'noopener');
      });
      foot.appendChild(linkBtn);
    }
    var okBtn = document.createElement('button');
    okBtn.className = 'annp-btn primary';
    okBtn.textContent = '我知道了';
    foot.appendChild(okBtn);
    modal.appendChild(foot);

    function close() {
      if (!_inPageVisible) return;
      _inPageVisible = false;
      _lastClosedAt = Date.now();
      overlay.remove();
      if (typeof onClose === 'function') onClose();
    }
    okBtn.addEventListener('click', close);

    overlay.appendChild(modal);
    return { overlay: overlay, close: close };
  }

  function markRead(id) {
    var token = getToken();
    var headers = token ? { 'Authorization': 'Bearer ' + token } : {};
    try {
      fetch('/api/announcements/' + encodeURIComponent(id) + '/read', {
        method: 'POST', headers: headers, credentials: 'same-origin'
      }).catch(function () { /* 已读失败不影响关闭：下次进页会再提示一次 */ });
    } catch (e) { /* 忽略 */ }
  }

  function showLatestUnreadPopup(items) {
    if (_inPageVisible) return;
    if (Date.now() - _lastClosedAt < DISMISS_GUARD_MS) return;
    var target = null;
    for (var i = 0; i < (items || []).length; i++) {
      if (items[i] && Number(items[i].popup) === 1 && !items[i].is_read) { target = items[i]; break; }
    }
    if (!target) return;

    var built = buildModal(target, function () { markRead(target.id); });
    document.body.appendChild(built.overlay);
    _inPageVisible = true;
  }

  function maybeShow() {
    var token = getToken();
    if (!token) return;                       // 未登录：公告弹窗无从谈起
    try {
      fetch('/api/announcements?limit=20', {
        headers: { 'Authorization': 'Bearer ' + token }, credentials: 'same-origin'
      }).then(function (r) { return r.json(); }).then(function (d) {
        if (d && d.code === 0 && d.data && Array.isArray(d.data.items)) {
          showLatestUnreadPopup(d.data.items);
        }
      }).catch(function () { /* 公告失败静默，不影响页面主流程 */ });
    } catch (e) { /* 忽略 */ }
  }

  // DOMContentLoaded 自动检测一次（覆盖携带 token 进入页面的全部场景）
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', maybeShow);
  } else {
    maybeShow();
  }

  window.AnnouncementPopup = { maybeShow: maybeShow };
})();
