/**
 * 主预览逻辑画布：按 workflow_ratio + previewResolution 固定监视器框，
 * 媒体 object-fit:scale-down（仅缩不放）。
 */
import state from './state.js';

/** 预览分辨率档位（短边像素） */
export const PREVIEW_RESOLUTION_OPTIONS = [
    { value: '480p', shortSide: 480, label: '480p' },
    { value: '720p', shortSide: 720, label: '720p' },
    { value: '1080p', shortSide: 1080, label: '1080p' },
];

const SHORT_SIDE_MAP = {
    '480p': 480,
    '720p': 720,
    '1080p': 1080,
};

const DEFAULT_PREVIEW_RESOLUTION = '720p';

let resizeObserver = null;
let observedWrapper = null;

export function normalizePreviewResolution(value) {
    const key = String(value || '').trim().toLowerCase();
    if (SHORT_SIDE_MAP[key]) return key;
    // 兼容 720P / 720
    const compact = key.replace(/\s+/g, '');
    if (SHORT_SIDE_MAP[compact]) return compact;
    if (compact === '480' || compact === '720' || compact === '1080') {
        return `${compact}p`;
    }
    return DEFAULT_PREVIEW_RESOLUTION;
}

export function parseWorkflowRatio(ratio = '16:9') {
    const parts = String(ratio || '16:9').split(':').map((x) => Number(x));
    const rw = parts[0];
    const rh = parts[1];
    if (!Number.isFinite(rw) || !Number.isFinite(rh) || rw <= 0 || rh <= 0) {
        return { rw: 16, rh: 9 };
    }
    return { rw, rh };
}

/**
 * 逻辑画布像素：Np = 短边 N。
 * 16:9 + 720p → 1280×720；9:16 + 720p → 720×1280
 */
export function resolveLogicalCanvas(ratio, previewResolution = DEFAULT_PREVIEW_RESOLUTION) {
    const res = normalizePreviewResolution(previewResolution);
    const shortSide = SHORT_SIDE_MAP[res] || 720;
    const { rw, rh } = parseWorkflowRatio(ratio);
    if (rw >= rh) {
        const height = shortSide;
        const width = Math.round((shortSide * rw) / rh);
        return { width, height, shortSide, ratio: `${rw}:${rh}`, previewResolution: res };
    }
    const width = shortSide;
    const height = Math.round((shortSide * rh) / rw);
    return { width, height, shortSide, ratio: `${rw}:${rh}`, previewResolution: res };
}

/**
 * 媒体装入 box：仅当超出时缩小（max-scale=1）。
 * scale = min(1, boxW/mediaW, boxH/mediaH)
 */
export function fitLongestSide(mediaW, mediaH, boxW, boxH) {
    const mw = Number(mediaW) || 0;
    const mh = Number(mediaH) || 0;
    const bw = Number(boxW) || 0;
    const bh = Number(boxH) || 0;
    if (mw <= 0 || mh <= 0 || bw <= 0 || bh <= 0) {
        return { w: 0, h: 0, scale: 1 };
    }
    const scale = Math.min(1, bw / mw, bh / mh);
    return {
        w: Math.round(mw * scale),
        h: Math.round(mh * scale),
        scale,
    };
}

/** 时间轴拇指尺寸（CSS px），与主预览比例一致 */
export function resolveTimelineThumbSize(ratio = '16:9') {
    const { rw, rh } = parseWorkflowRatio(ratio);
    const BASE = 96;
    if (rw > rh) {
        // 横屏：固定高度
        return { width: Math.round((BASE * rw) / rh), height: BASE };
    }
    if (rw < rh) {
        // 竖屏：固定宽度，避免细条
        const width = 72;
        return { width, height: Math.round((width * rh) / rw) };
    }
    return { width: BASE, height: BASE };
}

export function applyTimelineRatioVars(listEl, ratio) {
    if (!listEl) return;
    const r = String(ratio || state.workflowRatio || '16:9');
    const { width, height } = resolveTimelineThumbSize(r);
    listEl.dataset.ratio = r;
    listEl.style.setProperty('--timeline-thumb-width', `${width}px`);
    listEl.style.setProperty('--timeline-thumb-height', `${height}px`);
}

/**
 * 确保 .preview-stage 存在；字幕移入 stage，caption 留在 wrapper。
 */
export function ensurePreviewStage(wrapper) {
    if (!wrapper) return null;
    let stage = wrapper.querySelector(':scope > .preview-stage');
    if (!stage) {
        stage = document.createElement('div');
        stage.className = 'preview-stage';
        const caption = wrapper.querySelector(':scope > .preview-caption');
        if (caption) {
            wrapper.insertBefore(stage, caption);
        } else {
            wrapper.appendChild(stage);
        }
    }
    const sub = wrapper.querySelector(':scope > .preview-subtitle');
    if (sub) stage.appendChild(sub);
    return stage;
}

/**
 * 按当前 state 计算逻辑画布，写入 data/CSS，并 fit stage 到 wrapper 可用区（≤ 逻辑 1:1）。
 */
export function applyPreviewCanvas(root = document) {
    const wrapper = resolvePreviewWrapper(root);
    if (!wrapper) return null;

    const ratio = state.workflowRatio || wrapper.dataset.ratio || '16:9';
    const previewResolution = normalizePreviewResolution(
        state.previewResolution || wrapper.dataset.previewResolution
    );
    const canvas = resolveLogicalCanvas(ratio, previewResolution);

    // 保留用户选择的 workflow 字符串（含 9:16）
    wrapper.dataset.ratio = String(state.workflowRatio || ratio || '16:9');
    wrapper.dataset.previewResolution = canvas.previewResolution;
    wrapper.style.setProperty('--logical-w', String(canvas.width));
    wrapper.style.setProperty('--logical-h', String(canvas.height));
    wrapper.style.setProperty('--preview-ar', `${canvas.width} / ${canvas.height}`);

    const stage = ensurePreviewStage(wrapper);
    if (!stage) return canvas;

    const panelW = wrapper.clientWidth;
    const panelH = wrapper.clientHeight;
    if (panelW > 0 && panelH > 0) {
        const scale = Math.min(1, panelW / canvas.width, panelH / canvas.height);
        const cssW = Math.max(1, Math.floor(canvas.width * scale));
        const cssH = Math.max(1, Math.floor(canvas.height * scale));
        stage.style.width = `${cssW}px`;
        stage.style.height = `${cssH}px`;
    }

    // 同步时间轴拇指
    const list = document.querySelector('.scene-timeline-list');
    if (list) applyTimelineRatioVars(list, wrapper.dataset.ratio);

    return canvas;
}

function resolvePreviewWrapper(root) {
    if (!root) return document.querySelector('.preview-wrapper');
    if (root.classList?.contains('preview-wrapper')) return root;
    if (typeof root.querySelector === 'function') {
        return root.querySelector('.preview-wrapper');
    }
    return document.querySelector('.preview-wrapper');
}

/** 在 render 后绑定 ResizeObserver，窗口/中栏变化时重算 stage */
export function bindPreviewCanvasObserver() {
    const wrapper = document.querySelector('.preview-wrapper');
    if (!wrapper) {
        if (resizeObserver && observedWrapper) {
            try { resizeObserver.unobserve(observedWrapper); } catch { /* ignore */ }
            observedWrapper = null;
        }
        return;
    }
    if (!resizeObserver) {
        resizeObserver = new ResizeObserver(() => {
            applyPreviewCanvas();
        });
    }
    if (observedWrapper === wrapper) {
        applyPreviewCanvas(wrapper);
        return;
    }
    if (observedWrapper) {
        try { resizeObserver.unobserve(observedWrapper); } catch { /* ignore */ }
    }
    observedWrapper = wrapper;
    resizeObserver.observe(wrapper);
    applyPreviewCanvas(wrapper);
}

export function getPreviewMediaMountParent(wrapper) {
    if (!wrapper) return null;
    return ensurePreviewStage(wrapper) || wrapper;
}
