/**
 * hover_preview.js — 工作流页面 @ 下拉条目悬停大图预览（video_workflow.html 专用）。
 *
 * 机制与 storyboard 页面一致（见 web/js/storyboard/chat_mention_chips.js）：
 * 文档级 mouseover 委托，命中 [data-hover-preview] 即弹出原图预览；
 * 在 .mention-dropdown / .character-dropdown 内时预览固定显示在条目右侧，
 * 避免盖住选项列表。下拉条目只需挂 data-hover-preview="<原图URL>"，无需其他接线。
 *
 * 暴露 window.WFHoverPreview.show/hide/setup，下拉框关闭时应主动 hide()。
 */
(function () {
    'use strict';

    let previewEl = null;
    let hoverBound = false;

    function hoverPreviewEl() {
        if (previewEl) return previewEl;
        previewEl = document.createElement('div');
        previewEl.id = 'wf-hover-preview';
        previewEl.className = 'wf-hover-preview';
        document.body.appendChild(previewEl);
        return previewEl;
    }

    function positionPreview(pop, anchor, placement) {
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

    function showHoverPreview(url, anchor, placement) {
        const pop = hoverPreviewEl();
        const cleaned = String(url || '');
        if (!cleaned || !anchor) {
            hideHoverPreview();
            return;
        }
        if (pop.dataset.url !== cleaned) {
            pop.dataset.url = cleaned;
            pop.innerHTML = `<img src="${window.escapeHtml(cleaned)}" alt="">`;
        }
        positionPreview(pop, anchor, placement);
        const img = pop.querySelector('img');
        if (img && !img.complete) {
            img.addEventListener('load', () => {
                if (pop.dataset.url === cleaned) positionPreview(pop, anchor, placement);
            }, { once: true });
        }
    }

    function hideHoverPreview() {
        if (!previewEl || previewEl.style.display === 'none') return;
        previewEl.style.display = 'none';
        previewEl.dataset.url = '';
    }

    /** 文档级委托：带 data-hover-preview 的元素悬停即出大图，页面加载时自动绑定一次。 */
    function setupHoverPreview() {
        if (hoverBound) return;
        hoverBound = true;
        document.addEventListener('mouseover', (event) => {
            if (!(event.target instanceof Element)) return;
            const anchor = event.target.closest('[data-hover-preview]');
            if (anchor && anchor.dataset.hoverPreview) {
                // @ 下拉框：预览放条目右侧，避免盖住选项列表；其他场景放上方
                const placement = anchor.closest('.mention-dropdown, .character-dropdown') ? 'right' : 'top';
                showHoverPreview(anchor.dataset.hoverPreview, anchor, placement);
            } else if (!event.target.closest('.wf-hover-preview')) {
                hideHoverPreview();
            }
        });
        document.addEventListener('scroll', hideHoverPreview, true);
        window.addEventListener('blur', hideHoverPreview);
    }

    setupHoverPreview();

    window.WFHoverPreview = { show: showHoverPreview, hide: hideHoverPreview, setup: setupHoverPreview };
})();
