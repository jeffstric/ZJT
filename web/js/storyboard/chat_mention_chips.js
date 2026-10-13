/**
 * 分镜助手输入框的图片提及渲染：
 * - textarea 内无法内嵌图片，用同字距镜像层把 @首帧图/@尾帧图 文本盖成
 *   「缩略图 + 唯一短id」胶囊；底层文本仍是标记本身，提交链路（服务端
 *   services/storyboard_frame_mention.py 按标记解析）不变；
 * - 胶囊与提及菜单条目统一支持 data-hover-preview 悬停大图预览。
 */
import state, { mentionableVideoFrameUrls } from './state.js';
import { getThumbnailUrl } from './render.js';

const escapeHtml = (typeof window !== 'undefined' && typeof window.escapeHtml === 'function')
    ? window.escapeHtml
    : (s) => String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');

const escapeHtmlAttr = (typeof window !== 'undefined' && typeof window.escapeHtmlAttr === 'function')
    ? window.escapeHtmlAttr
    : escapeHtml;

const FRAME_TOKEN_RES = [
    { key: 'first', re: /@首帧图(?![\u4e00-\u9fff])/g },
    { key: 'last', re: /@尾帧图(?![\u4e00-\u9fff])/g },
];

/** 扫描提示词里的首尾帧标记，返回 {key, token, start, end}（按出现序）。 */
export function scanFrameMentionTokens(text) {
    const value = text == null ? '' : String(text);
    const found = [];
    FRAME_TOKEN_RES.forEach(({ key, re }) => {
        re.lastIndex = 0;
        let m;
        while ((m = re.exec(value)) !== null) {
            found.push({ key, token: m[0], start: m.index, end: m.index + m[0].length });
        }
    });
    return found.sort((a, b) => a.start - b.start);
}

/** 由图片 URL 生成稳定短 id：十六进制文件名直接截取，否则 FNV-1a 哈希 8 位。
 *  胶囊宽度需贴近标记占位（约 47px），id 过长会盖住标记后的正文。 */
export function shortImageId(url) {
    const clean = String(url || '').split('?')[0].split('#')[0];
    const base = clean.substring(clean.lastIndexOf('/') + 1).replace(/\.[a-z0-9]+$/i, '');
    if (/^[0-9a-f]{8,}$/i.test(base)) return base.slice(0, 8).toLowerCase();
    let h = 0x811c9dc5;
    for (let i = 0; i < clean.length; i++) {
        h = Math.imul(h ^ clean.charCodeAt(i), 0x01000193) >>> 0;
    }
    return h.toString(16).padStart(8, '0');
}

function frameUrlByKey() {
    if (state.videoImageMode !== 'multi_reference') return {};
    const frames = mentionableVideoFrameUrls();
    return { first: frames.frame_first_url || '', last: frames.frame_last_url || '' };
}

const syncedTextareas = new WeakSet();
let resizeObserver = null;

/**
 * 把 textarea 里的首尾帧标记同步成镜像层胶囊。
 * 幂等：输入、滚动、重绘后调用；textarea/镜像层不存在（对口型直连）时直接返回。
 */
export function syncChatMentionChips() {
    const ta = document.getElementById('chat-textarea');
    const mirror = document.querySelector('[data-chat-textarea-mirror]');
    if (!ta || !mirror) return;
    ensureSyncListeners(ta);
    const urlByKey = frameUrlByKey();
    const text = String(ta.value ?? '');
    const tokens = scanFrameMentionTokens(text).filter((t) => urlByKey[t.key]);
    if (!tokens.length) {
        mirror.innerHTML = '';
        return;
    }
    // 滚动条出现时 textarea 内容宽变窄，镜像内容宽必须同步收窄，否则换行错位
    const scrollbar = ta.offsetWidth - ta.clientWidth - 2;
    mirror.style.paddingRight = scrollbar > 0 ? `${11 + scrollbar}px` : '';
    const parts = [];
    let cursor = 0;
    tokens.forEach(({ key, token, start, end }) => {
        const url = urlByKey[key];
        parts.push(escapeHtml(text.slice(cursor, start)));
        parts.push(
            `<span class="chip-anchor">${escapeHtml(token)}<span class="chat-mention-chip" data-hover-preview="${escapeHtmlAttr(url)}">`
            + `<img src="${escapeHtml(getThumbnailUrl(url, 28))}" alt="">`
            + `<span class="chat-mention-chip-id">${escapeHtml(shortImageId(url))}</span>`
            + `</span></span>`,
        );
        cursor = end;
    });
    parts.push(escapeHtml(text.slice(cursor)));
    mirror.innerHTML = parts.join('');
    mirror.scrollTop = ta.scrollTop;
}

function ensureSyncListeners(ta) {
    if (syncedTextareas.has(ta)) return;
    syncedTextareas.add(ta);
    ta.addEventListener('scroll', () => {
        const mirror = document.querySelector('[data-chat-textarea-mirror]');
        if (mirror) mirror.scrollTop = ta.scrollTop;
    });
    if (typeof ResizeObserver !== 'undefined') {
        if (!resizeObserver) resizeObserver = new ResizeObserver(() => syncChatMentionChips());
        // patchAgentPanel 会整体重建 textarea：先断开旧目标，避免持有已拆离元素
        resizeObserver.disconnect();
        resizeObserver.observe(ta);
    }
}

/* ---------- 悬停大图预览（胶囊 + 提及菜单共用） ---------- */

let previewEl = null;
let hoverBound = false;

function hoverPreviewEl() {
    if (previewEl) return previewEl;
    previewEl = document.createElement('div');
    previewEl.id = 'sb-hover-preview';
    previewEl.className = 'sb-hover-preview';
    document.body.appendChild(previewEl);
    return previewEl;
}

function positionPreview(pop, anchor) {
    if (!anchor.isConnected) return;
    const rect = anchor.getBoundingClientRect();
    pop.style.visibility = 'hidden';
    pop.style.display = 'block';
    const pw = pop.offsetWidth;
    const ph = pop.offsetHeight;
    let left = rect.left + rect.width / 2 - pw / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - pw - 8));
    let top = rect.top - ph - 8;
    if (top < 8) top = rect.bottom + 8;
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
    pop.style.visibility = 'visible';
}

export function showHoverPreview(url, anchor) {
    const pop = hoverPreviewEl();
    const cleaned = String(url || '');
    if (!cleaned || !anchor) {
        hideHoverPreview();
        return;
    }
    if (pop.dataset.url !== cleaned) {
        pop.dataset.url = cleaned;
        pop.innerHTML = `<img src="${escapeHtml(cleaned)}" alt="">`;
    }
    positionPreview(pop, anchor);
    const img = pop.querySelector('img');
    if (img && !img.complete) {
        img.addEventListener('load', () => {
            if (pop.dataset.url === cleaned) positionPreview(pop, anchor);
        }, { once: true });
    }
}

export function hideHoverPreview() {
    if (!previewEl || previewEl.style.display === 'none') return;
    previewEl.style.display = 'none';
    previewEl.dataset.url = '';
}

/** 文档级委托：带 data-hover-preview 的元素悬停即出大图，bindEvents 调用一次。 */
export function setupHoverPreview() {
    if (hoverBound) return;
    hoverBound = true;
    document.addEventListener('mouseover', (event) => {
        if (!(event.target instanceof Element)) return;
        const anchor = event.target.closest('[data-hover-preview]');
        if (anchor && anchor.dataset.hoverPreview) {
            showHoverPreview(anchor.dataset.hoverPreview, anchor);
        } else if (!event.target.closest('.sb-hover-preview')) {
            hideHoverPreview();
        }
    });
    document.addEventListener('scroll', hideHoverPreview, true);
    window.addEventListener('blur', hideHoverPreview);
}
