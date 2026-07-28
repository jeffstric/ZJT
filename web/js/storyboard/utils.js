/**
 * Storyboard Utility Functions
 */

/** IndexTTS 情感向量维度标签（与 web/js/pages/audio_generate.js 一致） */
export const EMO_VEC_LABELS = ['喜', '怒', '哀', '惧', '厌恶', '低落', '惊喜', '平静'];
export const EMO_VEC_DIM = 8;
export const EMO_VEC_MAX_SUM = 1.5;
export const EMO_VEC_MAX_EACH = 1.5;

/** 解析 emo_vec 为 8 维 number[] */
export function parseEmoVec(raw) {
    if (Array.isArray(raw) && raw.length === EMO_VEC_DIM) {
        return raw.map((v) => {
            const n = Number(v);
            return Number.isFinite(n) ? Math.max(0, Math.min(EMO_VEC_MAX_EACH, n)) : 0;
        });
    }
    if (typeof raw === 'string' && raw.trim()) {
        const parts = raw.split(',').map((s) => s.trim()).filter((s) => s !== '');
        if (parts.length === EMO_VEC_DIM) {
            return parts.map((p) => {
                const n = Number(p);
                return Number.isFinite(n) ? Math.max(0, Math.min(EMO_VEC_MAX_EACH, n)) : 0;
            });
        }
    }
    return Array(EMO_VEC_DIM).fill(0);
}

/** 规范化：单维钳制 + 总和>1.5 比例缩放；全 0 返回 null */
export function normalizeEmoVec(values) {
    const list = parseEmoVec(values);
    let sum = list.reduce((a, b) => a + b, 0);
    if (sum <= 0) return null;
    if (sum > EMO_VEC_MAX_SUM) {
        const scale = EMO_VEC_MAX_SUM / sum;
        for (let i = 0; i < list.length; i += 1) list[i] = Math.round(list[i] * scale * 10000) / 10000;
        sum = list.reduce((a, b) => a + b, 0);
        if (sum > EMO_VEC_MAX_SUM && sum > 0) {
            const scale2 = EMO_VEC_MAX_SUM / sum;
            for (let i = 0; i < list.length; i += 1) list[i] = Math.round(list[i] * scale2 * 10000) / 10000;
        }
    }
    return list.map((v) => v.toFixed(4)).join(',');
}

/** 摘要：非零维度「喜 0.40 · 怒 0.20」 */
export function formatEmoVecSummary(raw) {
    const list = parseEmoVec(raw);
    const parts = [];
    list.forEach((v, i) => {
        if (v > 0.001) parts.push(`${EMO_VEC_LABELS[i]} ${v.toFixed(2)}`);
    });
    return parts.length ? parts.join(' · ') : '未设置';
}

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
 * 格式化时长（秒 → mm:ss[.t]）。秒部分保留 1 位小数，以体现音频求和回写后的
 * 毫秒级时长；整数秒仍输出 mm:ss（不追加 .0）。与 adapters.formatDuration 行为一致。
 * 注：当前无调用方，保留以备复用。
 */
export function formatDuration(seconds) {
    const total = Number(seconds);
    if (!Number.isFinite(total)) return '00:00';
    const clamped = Math.max(0, total);
    const m = Math.floor(clamped / 60);
    const rem = clamped - m * 60;
    const intSecs = Math.floor(rem);
    const frac = Math.round((rem - intSecs) * 10);
    const sStr = frac > 0
        ? `${String(intSecs).padStart(2, '0')}.${frac}`
        : String(intSecs).padStart(2, '0');
    return `${String(m).padStart(2, '0')}:${sStr}`;
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
