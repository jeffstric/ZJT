/**
 * ZJT i18n 语言切换 UI 组件
 *
 * 使用方式：
 * 1. 在 HTML 中添加：<script src="/i18n/i18n-switcher.js"></script>
 * 2. 在需要的地方调用：ZJTi18nSwitcher.render(targetElement)
 * 3. 或自动挂载到顶部：ZJTi18nSwitcher.attachToHeader()
 */

window.ZJTi18nSwitcher = (() => {
  const i18n = window.ZJTi18n;

  const languages = [
    { code: 'zh-CN', name: '中文', nativeName: '中文' },
    { code: 'en', name: 'English', nativeName: 'English' }
  ];

  /**
   * 创建语言切换器 DOM
   */
  function createSwitcherElement() {
    const container = document.createElement('div');
    container.className = 'language-switcher';

    const btn = document.createElement('button');
    btn.className = 'language-switcher-btn';
    btn.type = 'button';
    btn.title = '切换语言 / Switch Language';
    btn.innerHTML = `
      <span class="language-icon">🌍</span>
      <span class="language-name">${getCurrentLanguageName()}</span>
    `;

    const dropdown = document.createElement('div');
    dropdown.className = 'language-dropdown';

    languages.forEach((lang) => {
      const option = document.createElement('div');
      option.className = 'language-option';
      if (lang.code === i18n.getLocale()) {
        option.classList.add('active');
      }
      option.textContent = lang.nativeName;
      option.dataset.locale = lang.code;
      option.addEventListener('click', () => {
        selectLanguage(lang.code, container);
      });
      dropdown.appendChild(option);
    });

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      dropdown.classList.toggle('show');
    });

    // 点击外部关闭下拉菜单
    document.addEventListener('click', () => {
      dropdown.classList.remove('show');
    });

    container.appendChild(btn);
    container.appendChild(dropdown);

    // 监听语言变化，更新按钮文本
    i18n.on('locale-changed', () => {
      const nameSpan = btn.querySelector('.language-name');
      if (nameSpan) {
        nameSpan.textContent = getCurrentLanguageName();
      }
      // 更新活跃状态
      dropdown.querySelectorAll('.language-option').forEach((opt) => {
        opt.classList.remove('active');
        if (opt.dataset.locale === i18n.getLocale()) {
          opt.classList.add('active');
        }
      });
    });

    return container;
  }

  /**
   * 获取当前语言的显示名称
   */
  function getCurrentLanguageName() {
    const current = languages.find((l) => l.code === i18n.getLocale());
    return current ? current.nativeName : '语言';
  }

  /**
   * 选择语言
   */
  async function selectLanguage(locale, container) {
    const dropdown = container.querySelector('.language-dropdown');
    dropdown.classList.remove('show');

    await i18n.setLocale(locale, ['common', 'video_workflow', 'index', 'marketing_agent', 'admin', 'workflow_list', 'storyboard']);

    // 重新扫描所有 data-i18n 属性
    if (window.ZJTi18nDOM) {
      window.ZJTi18nDOM.scanDOM(document);
    }

    // 更新 HTML lang 属性
    document.documentElement.lang = locale === 'en' ? 'en' : 'zh-CN';
  }

  /**
   * 将语言切换器渲染到指定元素
   * @param {Element|string} target - 目标元素或选择器
   */
  function render(target) {
    let targetEl = target;
    if (typeof target === 'string') {
      // 支持传入 id（不带#）或 CSS 选择器
      targetEl = target.startsWith('#') || target.startsWith('.')
        ? document.querySelector(target)
        : document.getElementById(target);
    }

    if (!targetEl) {
      console.warn('Language switcher target not found:', target);
      return;
    }

    const switcher = createSwitcherElement();
    targetEl.appendChild(switcher);
  }

  /**
   * 自动挂载到页面头部（查找常见的头部容器）
   */
  function attachToHeader() {
    const headerSelectors = [
      'header',
      '.header',
      '.navbar',
      '.top-bar',
      '.page-header',
      '[role="banner"]'
    ];

    for (const selector of headerSelectors) {
      const header = document.querySelector(selector);
      if (header) {
        render(header);
        return true;
      }
    }

    // 如果找不到头部，挂载到 body
    console.warn('No header found, appending language switcher to body');
    render(document.body);
    return false;
  }

  /**
   * 初始化语言切换器
   * @param {object} options - 配置选项
   *   - target: 挂载目标（选择器或元素）
   *   - autoAttach: 是否自动挂载到头部（默认 false）
   */
  function init(options = {}) {
    if (options.autoAttach) {
      attachToHeader();
    } else if (options.target) {
      render(options.target);
    }
  }

  return {
    render,
    attachToHeader,
    init,
    createSwitcherElement
  };
})();
