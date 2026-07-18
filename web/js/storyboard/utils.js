/**
 * Storyboard Utility Functions
 */

/**
 * 防抖函数
 */
export function debounce(fn, delay = 300) {
    let timer = null;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

/**
 * 显示 Toast 提示
 */
export function showToast(message, type = 'info', duration = 3000) {
    const toast = document.createElement('div');
    toast.className = `sb-toast sb-toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    requestAnimationFrame(() => toast.classList.add('sb-toast-show'));
    setTimeout(() => {
        toast.classList.remove('sb-toast-show');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

/**
 * 显示确认对话框
 */
export function showConfirm(message) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'sb-confirm-overlay';
        overlay.innerHTML = `
            <div class="sb-confirm-dialog">
                <p class="sb-confirm-message">${message}</p>
                <div class="sb-confirm-actions">
                    <button class="sb-btn sb-btn-secondary" data-action="cancel">取消</button>
                    <button class="sb-btn sb-btn-danger" data-action="confirm">确认</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        overlay.addEventListener('click', (e) => {
            const action = e.target.dataset.action;
            if (action === 'confirm') {
                overlay.remove();
                resolve(true);
            } else if (action === 'cancel' || e.target === overlay) {
                overlay.remove();
                resolve(false);
            }
        });
    });
}

/**
 * 格式化时长（秒 → mm:ss）
 */
export function formatDuration(seconds) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/**
 * 生成唯一临时 ID（用于拖拽排序等场景）
 */
export function tempId() {
    return `temp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * 获取任务状态的 CSS 类名
 */
export function getStatusClass(status) {
    switch (status) {
        case 0: return 'status-not-started';
        case 1: return 'status-generating';
        case 2: return 'status-success';
        case 3: return 'status-failed';
        default: return '';
    }
}

/**
 * 获取任务状态的文本
 */
export function getStatusText(status) {
    const t = window.ZJTi18n?.t || ((key, fallback) => fallback);
    switch (status) {
        case 0: return t('status_not_started', '未开始');
        case 1: return t('status_generating', '生成中');
        case 2: return t('status_success', '成功');
        case 3: return t('status_failed', '失败');
        default: return '';
    }
}

/**
 * i18n 便捷函数
 */
export function t(key, fallback) {
    if (window.ZJTi18n && window.ZJTi18n.t) {
        return window.ZJTi18n.t(key, fallback);
    }
    return fallback || key;
}
