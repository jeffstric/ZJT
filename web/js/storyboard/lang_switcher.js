/**
 * 故事板页语言切换器挂载（单例复用）。
 *
 * renderAppFull 每次全量重建 DOM，若每次都新建切换器元素，
 * ZJTi18nSwitcher 内部注册的 document click / locale-changed 监听会随重建累积。
 * 这里模块级持有同一个 DOM 节点：appendChild 到新 slot 时浏览器自动将其从旧位置移动，
 * 事件监听只注册一次。
 */
let switcherEl = null;

export function ensureLanguageSwitcher() {
    const slot = document.querySelector('[data-lang-switcher-slot]');
    if (!slot) return;
    if (!switcherEl) {
        if (window.ZJTi18nSwitcher && typeof window.ZJTi18nSwitcher.createSwitcherElement === 'function') {
            switcherEl = window.ZJTi18nSwitcher.createSwitcherElement();
        } else {
            return;
        }
    }
    if (switcherEl.parentElement !== slot) {
        slot.appendChild(switcherEl);
    }
}
