/**
 * ZJT i18n 核心模块 - 轻量级国际化引擎
 *
 * 功能：
 * - JSON 翻译文件加载和管理
 * - t(key) 翻译函数
 * - 语言切换（自动保存到 localStorage）
 * - 事件通知（语言变化时触发回调）
 */

window.ZJTi18n = (() => {
  // 内部状态
  const state = {
    locale: localStorage.getItem('zjt_locale') || 'zh-CN',
    messages: {},
    listeners: [],
    loadedNamespaces: [] // 记录已加载的命名空间
  };

  /**
   * 加载翻译文件
   * @param {string} locale - 语言代码（如 'zh-CN', 'en'）
   * @param {string} namespace - 命名空间（如 'common', 'index'）
   * @returns {Promise}
   */
  async function loadMessages(locale, namespace) {
    if (!state.messages[locale]) {
      state.messages[locale] = {};
    }

    if (state.messages[locale][namespace]) {
      return; // 已加载
    }

    try {
      const response = await fetch(`/i18n/locales/${locale}/${namespace}.json?v=${window.__STATIC_VERSION || ''}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const messages = await response.json();
      state.messages[locale][namespace] = messages;
      // 记录已加载的命名空间
      if (!state.loadedNamespaces.includes(namespace)) {
        state.loadedNamespaces.push(namespace);
      }
      // 商业版品牌定制：用 window.__BRANDING_SITE_NAME__ 覆盖翻译中的品牌名，
      // 防止 data-i18n 在语言切换时用 JSON 默认值（智剧通/ZJT）覆盖 SSR 注入的品牌名。
      // 此处覆盖发生在翻译存入 state 之前，保证 t() 和 scanDOM 都返回正确品牌名。
      _applyBranding(messages);
    } catch (error) {
      console.error(`Failed to load i18n ${locale}/${namespace}:`, error);
      state.messages[locale][namespace] = {};
      // 即使加载失败也记录
      if (!state.loadedNamespaces.includes(namespace)) {
        state.loadedNamespaces.push(namespace);
      }
    }
  }

  /**
   * 用商业版品牌名覆盖翻译中包含品牌名的键值。
   *
   * 策略：识别「品牌名相关」的键（app_title/page_title/brand_title/copyright/
   * footer_text/wx_group_*），将其值中的默认品牌词（中文「智剧通」/英文「ZJT」）
   * 替换为 window.__BRANDING_SITE_NAME__。这样保留原句结构，仅替换品牌词，
   * 同时兼容中英文。社区版/未配置时 window.__BRANDING_SITE_NAME__ 不存在，
   * 此函数不做任何改动（保持默认「智剧通」）。
   */
  function _applyBranding(messages) {
    const siteName = window.__BRANDING_SITE_NAME__;
    if (!siteName || typeof messages !== 'object') return;

    // 含品牌名、需要做词汇替换的键（通配 wx_group_* 前缀）
    const brandingKeyTest = (key) =>
      key === 'app_title' ||
      key === 'page_title' ||
      key === 'brand_title' ||
      key === 'copyright' ||
      key === 'footer_text' ||
      key === 'subtitle' ||
      key.indexOf('wx_group_') === 0;

    // 默认品牌词（中/英），替换为商业版品牌名
    const defaultBrandWords = ['智剧通', 'ZJT'];

    for (const key of Object.keys(messages)) {
      if (!brandingKeyTest(key)) continue;
      let val = messages[key];
      if (typeof val !== 'string') continue;
      for (const w of defaultBrandWords) {
        if (val.indexOf(w) >= 0) {
          val = val.split(w).join(siteName);
        }
      }
      messages[key] = val;
    }
  }

  /**
   * 翻译函数
   * @param {string} key - 翻译键（支持嵌套，如 'page.title'）
   * @param {object} params - 占位符替换参数（如 { name: 'John' }）
   * @returns {string} 翻译文本或原键
   */
  function t(key, params = {}) {
    const [locale, messages] = [state.locale, state.messages[state.locale] || {}];

    if (!messages || Object.keys(messages).length === 0) {
      return key; // 未加载翻译文件时返回键
    }

    // 合并所有命名空间的消息
    const allMessages = Object.assign({}, ...Object.values(messages));

    // 支持点号分隔的嵌套键，如 'page.title.main'
    const keys = key.split('.');
    let value = allMessages;

    for (const k of keys) {
      if (value && typeof value === 'object' && k in value) {
        value = value[k];
      } else {
        return key; // 键不存在返回键本身
      }
    }

    // 如果是字符串，进行参数替换
    if (typeof value === 'string') {
      return value.replace(/\{\{?(\w+)\}?}/g, (match, paramKey) => {
        return params[paramKey] !== undefined ? params[paramKey] : match;
      });
    }

    return key;
  }

  /**
   * 获取当前语言
   */
  function getLocale() {
    return state.locale;
  }

  /**
   * 设置语言并触发更新
   * @param {string} locale - 语言代码
   * @param {Array<string>} namespaces - 需要加载的命名空间（可选，默认使用已加载的）
   */
  async function setLocale(locale, namespaces = null) {
    const localeChanged = state.locale !== locale;
    state.locale = locale;
    localStorage.setItem('zjt_locale', locale);

    // 使用已加载的命名空间，或使用传入的命名空间
    const namespacesToLoad = namespaces || state.loadedNamespaces || ['common'];

    // 加载相应语言的翻译文件（包括新传入的命名空间）
    for (const ns of namespacesToLoad) {
      await loadMessages(locale, ns);
    }

    // 语言变化时通知所有监听器
    if (localeChanged) {
      emit('locale-changed', { locale, namespaces: namespacesToLoad });
    }
  }

  /**
   * 监听语言变化事件
   * @param {string} event - 事件名称（如 'locale-changed'）
   * @param {function} callback - 回调函数
   */
  function on(event, callback) {
    if (!state.listeners[event]) {
      state.listeners[event] = [];
    }
    state.listeners[event].push(callback);
  }

  /**
   * 取消监听
   */
  function off(event, callback) {
    if (!state.listeners[event]) return;
    const index = state.listeners[event].indexOf(callback);
    if (index > -1) {
      state.listeners[event].splice(index, 1);
    }
  }

  /**
   * 触发事件
   */
  function emit(event, data) {
    if (!state.listeners[event]) return;
    state.listeners[event].forEach(callback => callback(data));
  }

  /**
   * 初始化 i18n（加载初始翻译文件）
   * @param {Array<string>} namespaces - 需要加载的命名空间
   */
  async function init(namespaces = ['common']) {
    // 从 localStorage 恢复保存的语言（已在状态初始化时完成）
    // 这里需要确保所有命名空间都以当前语言加载
    for (const ns of namespaces) {
      await loadMessages(state.locale, ns);
    }
  }

  // 公共 API
  return {
    t,
    loadMessages,
    getLocale,
    setLocale,
    on,
    off,
    init
  };
})();

// 全局快捷方式
window.t = window.ZJTi18n.t;
