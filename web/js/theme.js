/**
 * 视频工作流主题（浅色 / 暗色）
 *
 * - 默认浅色，不强制暗色
 * - 偏好：localStorage.video_workflow_theme = 'light' | 'dark'
 * - DOM：html.theme-dark（仅暗色时存在）
 */
(function (global) {
  'use strict';

  var STORAGE_KEY = 'video_workflow_theme';
  var THEME_LIGHT = 'light';
  var THEME_DARK = 'dark';
  var CLASS_DARK = 'theme-dark';

  var ICON_MOON =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>' +
    '</svg>';

  var ICON_SUN =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<circle cx="12" cy="12" r="4"></circle>' +
    '<path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"></path>' +
    '</svg>';

  function normalize(theme) {
    return theme === THEME_DARK ? THEME_DARK : THEME_LIGHT;
  }

  function getStored() {
    try {
      return normalize(localStorage.getItem(STORAGE_KEY));
    } catch (e) {
      return THEME_LIGHT;
    }
  }

  function setStored(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, normalize(theme));
    } catch (e) {
      /* ignore quota / private mode */
    }
  }

  function apply(theme) {
    var next = normalize(theme);
    var root = document.documentElement;
    if (next === THEME_DARK) {
      root.classList.add(CLASS_DARK);
    } else {
      root.classList.remove(CLASS_DARK);
    }
    try {
      root.style.colorScheme = next;
    } catch (e) {
      /* ignore */
    }
    return next;
  }

  function get() {
    if (document.documentElement.classList.contains(CLASS_DARK)) {
      return THEME_DARK;
    }
    return getStored();
  }

  function set(theme) {
    var next = apply(theme);
    setStored(next);
    syncToggleButtons();
    return next;
  }

  function toggle() {
    return set(get() === THEME_DARK ? THEME_LIGHT : THEME_DARK);
  }

  function labelFor(theme) {
    var toDark = '切换到暗色模式';
    var toLight = '切换到浅色模式';
    if (global.t) {
      try {
        toDark = global.t('theme_toggle_to_dark') || toDark;
        toLight = global.t('theme_toggle_to_light') || toLight;
      } catch (e) {
        /* ignore */
      }
    }
    return theme === THEME_DARK ? toLight : toDark;
  }

  function updateButton(btn) {
    if (!btn) return;
    var theme = get();
    var label = labelFor(theme);
    btn.setAttribute('aria-label', label);
    btn.setAttribute('title', label);
    btn.setAttribute('data-theme', theme);
    btn.innerHTML = theme === THEME_DARK ? ICON_SUN : ICON_MOON;
  }

  function syncToggleButtons() {
    var nodes = document.querySelectorAll('.theme-toggle-btn');
    for (var i = 0; i < nodes.length; i++) {
      updateButton(nodes[i]);
    }
  }

  function createToggleButton() {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'theme-toggle-btn mini-btn secondary';
    btn.setAttribute('data-theme-toggle', '1');
    updateButton(btn);
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      toggle();
    });
    return btn;
  }

  /**
   * @param {{ target?: string|Element }} opts
   */
  function initToggle(opts) {
    opts = opts || {};
    // 确保与 storage / FOUC 脚本一致
    apply(getStored());

    var target = opts.target;
    var container = null;
    if (typeof target === 'string') {
      container = document.querySelector(target);
    } else if (target && target.nodeType === 1) {
      container = target;
    }
    if (!container) {
      return null;
    }
    if (container.querySelector('[data-theme-toggle="1"]')) {
      syncToggleButtons();
      return container.querySelector('[data-theme-toggle="1"]');
    }
    var btn = createToggleButton();
    container.appendChild(btn);
    return btn;
  }

  // 若 head 未跑 FOUC 脚本，模块加载时补一次
  apply(getStored());

  global.WorkflowTheme = {
    STORAGE_KEY: STORAGE_KEY,
    get: get,
    set: set,
    toggle: toggle,
    apply: apply,
    initToggle: initToggle,
    syncToggleButtons: syncToggleButtons
  };
})(typeof window !== 'undefined' ? window : this);
