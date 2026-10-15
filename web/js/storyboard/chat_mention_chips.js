/**
 * 分镜助手输入框的图片提及渲染：
 * - textarea 内无法内嵌图片，用同字距镜像层把 @首帧图[:id]/@尾帧图[:id]
 *   文本盖成「缩略图 + 唯一短id」胶囊；底层文本即标记本身（含 id 后缀，
 *   服务端 services/storyboard_frame_mention.py 按标记语义解析）；
 * - 标记是原子单位：光标不可落入标记中间编辑，删除一律整枚删除；
 * - 胶囊与提及菜单条目统一支持 data-hover-preview 悬停大图预览。
 */
import state, { mentionableVideoFrameUrls } from './state.js';
import { getThumbnailUrl } from './render.js';
import { scanFrameMentionTokenRanges } from './frame_mention.js';

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

/** 兼容旧导出名：token 扫描统一收敛到 frame_mention.js（与前端正则同源）。 */
export function scanFrameMentionTokens(text) {
    return scanFrameMentionTokenRanges(text);
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
        // 标记自带 id 后缀（@首帧图:xxxx）时以文本里的 id 为准，与底层文本一致
        const embedded = /:([0-9a-f]{8})$/.exec(token);
        const id = embedded ? embedded[1] : shortImageId(url);
        parts.push(escapeHtml(text.slice(cursor, start)));
        parts.push(
            `<span class="chip-anchor">${escapeHtml(token)}<span class="chat-mention-chip" data-hover-preview="${escapeHtmlAttr(url)}" data-end="${end}">`
            + `<img src="${escapeHtml(getThumbnailUrl(url, 28))}" alt="">`
            + `<span class="chat-mention-chip-id">${escapeHtml(id)}</span>`
            + `</span></span>`,
        );
        cursor = end;
    });
    parts.push(escapeHtml(text.slice(cursor)));
    mirror.innerHTML = parts.join('');
    mirror.scrollTop = ta.scrollTop;
}

/**
 * 标记是原子单位：删除触及标记 → 整枚删除；在标记中间插入 → 阻止。
 * 挂在 textarea 的 beforeinput 上（ensureSyncListeners）。
 */
function handleTokenBeforeInput(event) {
    const ta = event.target;
    if (!ta || ta.id !== 'chat-textarea') return;
    const spans = scanFrameMentionTokens(ta.value);
    if (!spans.length) return;
    const type = String(event.inputType || '');
    const start = typeof ta.selectionStart === 'number' ? ta.selectionStart : 0;
    const end = typeof ta.selectionEnd === 'number' ? ta.selectionEnd : start;
    if (type.startsWith('delete')) {
        let rangeStart = start;
        let rangeEnd = end;
        const touched = spans.filter((s) => {
            if (rangeStart < rangeEnd) return rangeStart < s.end && rangeEnd > s.start;
            if (type === 'deleteContentForward') return rangeStart >= s.start && rangeStart < s.end;
            return rangeStart > s.start && rangeStart <= s.end;
        });
        if (!touched.length) return;
        event.preventDefault();
        rangeStart = Math.min(rangeStart, ...touched.map((s) => s.start));
        rangeEnd = Math.max(rangeEnd, ...touched.map((s) => s.end));
        ta.setRangeText('', rangeStart, rangeEnd, 'end');
        state.inputMessage = ta.value;
        syncChatMentionChips();
        return;
    }
    if (type.startsWith('insert')) {
        // 光标或选区边缘落在标记内部：不允许分段修改，要改就整枚删掉重插
        const inside = spans.some((s) => (start > s.start && start < s.end) || (end > s.start && end < s.end));
        if (inside) event.preventDefault();
    }
}

function ensureSyncListeners(ta) {
    if (syncedTextareas.has(ta)) return;
    syncedTextareas.add(ta);
    ta.addEventListener('scroll', () => {
        const mirror = document.querySelector('[data-chat-textarea-mirror]');
        if (mirror) mirror.scrollTop = ta.scrollTop;
    });
    ta.addEventListener('beforeinput', handleTokenBeforeInput);
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

function positionPreview(pop, anchor, placement = 'top') {
    if (!anchor.isConnected) return;
    const rect = anchor.getBoundingClientRect();
    pop.style.visibility = 'hidden';
    pop.style.display = 'block';
    const pw = pop.offsetWidth;
    const ph = pop.offsetHeight;
    let left;
    let top;
    if (placement === 'right') {
        // 右侧优先；屏幕右缘放不下时翻到锚点左侧，垂直贴齐锚点并夹在视口内
        left = rect.right + 8;
        if (left + pw > window.innerWidth - 8) left = rect.left - pw - 8;
        left = Math.max(8, left);
        top = rect.top + rect.height / 2 - ph / 2;
        top = Math.max(8, Math.min(top, window.innerHeight - ph - 8));
    } else {
        left = rect.left + rect.width / 2 - pw / 2;
        left = Math.max(8, Math.min(left, window.innerWidth - pw - 8));
        top = rect.top - ph - 8;
        if (top < 8) top = rect.bottom + 8;
    }
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
    pop.style.visibility = 'visible';
}

export function showHoverPreview(url, anchor, placement = 'top') {
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
    positionPreview(pop, anchor, placement);
    const img = pop.querySelector('img');
    if (img && !img.complete) {
        img.addEventListener('load', () => {
            if (pop.dataset.url === cleaned) positionPreview(pop, anchor, placement);
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
            // 左侧提示词下拉与 @ 弹窗：预览放条目右侧，避免盖住选项列表
            const placement = anchor.closest('.asset-dropdown, .mention-popup') ? 'right' : 'top';
            showHoverPreview(anchor.dataset.hoverPreview, anchor, placement);
        } else if (!event.target.closest('.sb-hover-preview')) {
            hideHoverPreview();
        }
    });
    document.addEventListener('scroll', hideHoverPreview, true);
    window.addEventListener('blur', hideHoverPreview);
    // 点击胶囊：光标定位到标记之后（含尾随空格），不落进胶囊遮盖的区域
    document.addEventListener('mousedown', (event) => {
        if (!(event.target instanceof Element)) return;
        const chip = event.target.closest('.chat-mention-chip');
        if (!chip) return;
        const ta = document.getElementById('chat-textarea');
        if (!ta) return;
        event.preventDefault();
        const end = Number(chip.dataset.end);
        if (!Number.isFinite(end)) return;
        let pos = end;
        if (ta.value[pos] === ' ') pos += 1;
        pos = Math.min(Math.max(pos, 0), ta.value.length);
        ta.focus();
        ta.setSelectionRange(pos, pos);
    });
}
