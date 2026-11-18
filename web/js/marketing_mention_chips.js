/**
 * marketing_mention_chips.js — 营销智能体输入框的资产提及胶囊渲染。
 *
 * 机制与 storyboard 页面一致（见 web/js/storyboard/chat_mention_chips.js）：
 * - textarea 内无法内嵌图片，用同字距透明镜像层把 `@资产:{id}` token
 *   盖成「缩略图 + 名称」胶囊；底层文本即 token 本身，提交链路不变
 *   （marketing_agent.js handleSend 经 AssetLibrary.resolveMentionTokens 还原）；
 * - token 是原子单位：光标不可落入 token 中间编辑，删除一律整枚删除；
 * - 胶囊支持 data-hover-preview 悬停大图预览，点击胶囊光标定位到 token 之后；
 * - 选中下拉条目时名称/缩略图现成，由 marketing_agent.js insertMention 调
 *   register 注入资产池（零请求）；历史恢复等场景的未知 id 走详情接口兜底，
 *   每 id 只尝试一次，失败退化为纯文本（无权限/已清除不重试）。
 *
 * 暴露 window.MAMentionChips：
 *   - scanAssetMentionTokens(text)     扫描 token（与 asset_library.js TOKEN_RE 同源语义）
 *   - register(assetId, name, thumb)   注入资产池
 *   - briefById(assetId)               查资产池（测试用）
 *   - sync(textarea, mirror)           幂等渲染（Vue watcher / onMounted 调用）
 *   - setupHoverPreview()              文档级悬停大图 + 胶囊点击委托（一次性）
 *   - hideHoverPreview()               关闭浮层
 *
 * 转义统一走 web/js/escape.js 的 window.escapeHtml / window.escapeHtmlAttr
 * （资产名是用户可控内容，禁止本地副本）。
 */
(function () {
    'use strict';

    // 与 web/js/asset_library.js 的 TOKEN_RE 同源语义：`@资产:{id}`，数字前缀不误截
    var TOKEN_RE = /@资产:(\d+)(?!\d)/g;

    // 资产简报池：{id: {name, thumb}}
    var briefs = {};
    // 详情接口兜底记录：每 id 只尝试一次（失败保留纯文本）
    var detailTried = {};

    var activeTextarea = null;
    var activeMirror = null;
    var syncedTextareas = new WeakSet();
    var resizeObserver = null;

    /** 扫描文本中的 `@资产:{id}` token，返回 [{assetId, token, start, end}]（按出现序）。 */
    function scanAssetMentionTokens(text) {
        var value = text == null ? '' : String(text);
        var found = [];
        TOKEN_RE.lastIndex = 0;
        var m;
        while ((m = TOKEN_RE.exec(value)) !== null) {
            found.push({
                assetId: Number(m[1]),
                token: m[0],
                start: m.index,
                end: m.index + m[0].length
            });
        }
        return found;
    }

    /** 注入资产简报（insertMention 选中下拉条目时调用，条目自带缩略图/名称）。 */
    function register(assetId, name, thumb) {
        var key = Number(assetId);
        if (!key) return;
        briefs[key] = { name: String(name || '资产'), thumb: String(thumb || '') };
    }

    function briefById(assetId) {
        return briefs[Number(assetId)] || null;
    }

    /** 池中缺失的 id 经详情接口兜底拉取，入池后重渲染胶囊。 */
    function ensureBriefsByIds(assetIds) {
        if (!window.AssetLibrary || !window.AssetLibrary.api) return;
        assetIds.forEach(function (assetId) {
            var key = Number(assetId);
            if (!key || briefs[key] || detailTried[key]) return;
            detailTried[key] = true;
            window.AssetLibrary.api('/assets/' + key).then(function (res) {
                var d = res && res.data;
                if (!d || d.id == null) return;
                register(d.id, d.name, d.file_url || d.url || '');
                syncActive();
            }).catch(function () { /* 无权访问或已清除：token 维持纯文本 */ });
        });
    }

    function syncActive() {
        if (activeTextarea && activeMirror) sync(activeTextarea, activeMirror);
    }

    /**
     * 把 textarea 里的 `@资产:{id}` token 同步成镜像层胶囊（幂等）。
     * @param {HTMLTextAreaElement|null} textarea
     * @param {HTMLElement|null} mirror
     */
    function sync(textarea, mirror, depth) {
        depth = depth || 0;
        if (!textarea || !mirror) return;
        activeTextarea = textarea;
        activeMirror = mirror;
        ensureSyncListeners(textarea);

        var text = String(textarea.value == null ? '' : textarea.value);
        var all = scanAssetMentionTokens(text);
        // 历史/分页外的资产 token 先触发详情兜底（入池后本轮重跑渲染胶囊）
        ensureBriefsByIds(all.map(function (t) { return t.assetId; }));
        // 无简报数据的 token 渲染不了胶囊（退化为纯文本，不盖占位）
        var tokens = all.filter(function (t) { return briefById(t.assetId); });
        if (!tokens.length) {
            mirror.innerHTML = '';
            return;
        }

        // 滚动条出现时 textarea 内容宽变窄（字距同步会把它计入右侧内边距）
        var scrollbar = textarea.offsetWidth - textarea.clientWidth - 2;
        syncMirrorTypography(textarea, mirror, scrollbar);

        var parts = [];
        var cursor = 0;
        tokens.forEach(function (t) {
            var brief = briefById(t.assetId);
            parts.push(window.escapeHtml(text.slice(cursor, t.start)));
            parts.push(
                '<span class="ma-chip-anchor">' + window.escapeHtml(t.token)
                + '<span class="ma-mention-chip" data-hover-preview="' + window.escapeHtmlAttr(brief.thumb) + '" data-start="' + t.start + '" data-end="' + t.end + '">'
                + (brief.thumb
                    ? '<img src="' + window.escapeHtmlAttr(brief.thumb) + '" alt="">'
                    : '<span class="ma-mention-chip-noimg">🖼</span>')
                + '<span class="ma-mention-chip-name">' + window.escapeHtml(String(brief.name || '资产').slice(0, 8)) + '</span>'
                + '</span></span>'
            );
            cursor = t.end;
        });
        parts.push(window.escapeHtml(text.slice(cursor)));
        mirror.innerHTML = parts.join('');
        mirror.scrollTop = textarea.scrollTop;

        // token 被折行截断时（落在行尾），胶囊跨行定位被裁切、裸文本外露：强制换行让其独占一行
        if (depth < 3 && fixStraddlingTokens(textarea)) {
            sync(textarea, mirror, depth + 1);
        }
    }

    /**
     * 镜像层排版参数逐项复制 textarea 的 computedStyle（字体/行高/内边距含边框补偿）。
     * 折行点对像素级一致极其敏感，任何 CSS 漂移都会让胶囊盖错位置、裸文本外露。
     */
    function syncMirrorTypography(ta, mirror, scrollbar) {
        var cs = window.getComputedStyle(ta);
        var num = function (v) { return parseFloat(v) || 0; };
        mirror.style.fontSize = cs.fontSize;
        mirror.style.fontFamily = cs.fontFamily;
        mirror.style.fontWeight = cs.fontWeight;
        mirror.style.lineHeight = cs.lineHeight;
        mirror.style.letterSpacing = cs.letterSpacing;
        var scrollbarPad = scrollbar > 0 ? scrollbar : 0;
        mirror.style.padding = [
            num(cs.borderTopWidth) + num(cs.paddingTop),
            num(cs.borderRightWidth) + num(cs.paddingRight) + scrollbarPad,
            num(cs.borderBottomWidth) + num(cs.paddingBottom),
            num(cs.borderLeftWidth) + num(cs.paddingLeft)
        ].map(function (v) { return v + 'px'; }).join(' ');
    }

    /** token 跨行（锚点多于一个片段）时在 token 前插入换行，让其整体挪到下一行行首。 */
    function fixStraddlingTokens(ta) {
        var mirror = activeMirror;
        if (!mirror) return false;
        var jobs = [];
        mirror.querySelectorAll('.ma-chip-anchor').forEach(function (anchor) {
            if (anchor.getClientRects().length <= 1) return;
            var chip = anchor.querySelector('.ma-mention-chip');
            var start = Number(chip && chip.dataset.start);
            if (Number.isFinite(start) && start > 0 && ta.value[start - 1] !== '\n') {
                jobs.push(start);
            }
        });
        if (!jobs.length) return false;
        var selStart = typeof ta.selectionStart === 'number' ? ta.selectionStart : null;
        var selEnd = typeof ta.selectionEnd === 'number' ? ta.selectionEnd : null;
        // 从后往前插换行，靠前的偏移不受影响；恢复光标时按插入点数平移
        jobs.sort(function (a, b) { return b - a; });
        jobs.forEach(function (pos) { ta.setRangeText('\n', pos, pos, 'end'); });
        var shift = function (p) { return p + jobs.filter(function (s) { return s < p; }).length; };
        if (selStart != null) {
            ta.setSelectionRange(shift(selStart), shift(selEnd != null ? selEnd : selStart));
        }
        // 镜像层被动改写了 textarea 文本：派发 input 让 Vue v-model 跟上
        ta.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
    }

    /**
     * token 是原子单位：删除触及 token → 整枚删除；在 token 中间插入 → 阻止。
     * 挂在 textarea 的 beforeinput 上（ensureSyncListeners）。
     */
    function handleTokenBeforeInput(event) {
        var ta = event.target;
        if (!ta || ta !== activeTextarea) return;
        var spans = scanAssetMentionTokens(ta.value);
        if (!spans.length) return;
        var type = String(event.inputType || '');
        var start = typeof ta.selectionStart === 'number' ? ta.selectionStart : 0;
        var end = typeof ta.selectionEnd === 'number' ? ta.selectionEnd : start;
        if (type.indexOf('delete') === 0) {
            var rangeStart = start;
            var rangeEnd = end;
            var touched = spans.filter(function (s) {
                if (rangeStart < rangeEnd) return rangeStart < s.end && rangeEnd > s.start;
                if (type === 'deleteContentForward') return rangeStart >= s.start && rangeStart < s.end;
                return rangeStart > s.start && rangeStart <= s.end;
            });
            if (!touched.length) return;
            event.preventDefault();
            rangeStart = Math.min.apply(null, [rangeStart].concat(touched.map(function (s) { return s.start; })));
            rangeEnd = Math.max.apply(null, [rangeEnd].concat(touched.map(function (s) { return s.end; })));
            ta.setRangeText('', rangeStart, rangeEnd, 'end');
            ta.dispatchEvent(new Event('input', { bubbles: true }));
            sync(ta, activeMirror);
            return;
        }
        if (type.indexOf('insert') === 0) {
            // 光标或选区边缘落在 token 内部：不允许分段修改，要改就整枚删掉重插
            var inside = spans.some(function (s) {
                return (start > s.start && start < s.end) || (end > s.start && end < s.end);
            });
            if (inside) event.preventDefault();
        }
    }

    function ensureSyncListeners(ta) {
        if (syncedTextareas.has(ta)) return;
        syncedTextareas.add(ta);
        ta.addEventListener('scroll', function () {
            if (activeMirror) activeMirror.scrollTop = ta.scrollTop;
        });
        ta.addEventListener('beforeinput', handleTokenBeforeInput);
        if (typeof ResizeObserver !== 'undefined') {
            if (!resizeObserver) resizeObserver = new ResizeObserver(function () { syncActive(); });
            // 会话切换/模板重建会换 textarea 实例：先断开旧目标，避免持有已拆离元素
            resizeObserver.disconnect();
            resizeObserver.observe(ta);
        }
    }

    /* ---------- 悬停大图预览（胶囊共用） ---------- */

    var previewEl = null;
    var hoverBound = false;

    function hoverPreviewEl() {
        if (previewEl) return previewEl;
        previewEl = document.createElement('div');
        previewEl.id = 'ma-hover-preview';
        previewEl.className = 'ma-hover-preview';
        document.body.appendChild(previewEl);
        return previewEl;
    }

    function positionPreview(pop, anchor) {
        if (!anchor.isConnected) return;
        var rect = anchor.getBoundingClientRect();
        pop.style.visibility = 'hidden';
        pop.style.display = 'block';
        var pw = pop.offsetWidth;
        var ph = pop.offsetHeight;
        var left = rect.left + rect.width / 2 - pw / 2;
        left = Math.max(8, Math.min(left, window.innerWidth - pw - 8));
        var top = rect.top - ph - 8;
        if (top < 8) top = rect.bottom + 8;
        pop.style.left = left + 'px';
        pop.style.top = top + 'px';
        pop.style.visibility = 'visible';
    }

    function showHoverPreview(url, anchor) {
        var pop = hoverPreviewEl();
        var cleaned = String(url || '');
        if (!cleaned || !anchor) {
            hideHoverPreview();
            return;
        }
        if (pop.dataset.url !== cleaned) {
            pop.dataset.url = cleaned;
            pop.innerHTML = '<img src="' + window.escapeHtmlAttr(cleaned) + '" alt="">';
        }
        positionPreview(pop, anchor);
        var img = pop.querySelector('img');
        if (img && !img.complete) {
            img.addEventListener('load', function () {
                if (pop.dataset.url === cleaned) positionPreview(pop, anchor);
            }, { once: true });
        }
    }

    function hideHoverPreview() {
        if (!previewEl || previewEl.style.display === 'none') return;
        previewEl.style.display = 'none';
        previewEl.dataset.url = '';
    }

    /** 文档级委托：胶囊悬停出大图、点击定位光标；onMounted 调一次。 */
    function setupHoverPreview() {
        if (hoverBound) return;
        hoverBound = true;
        document.addEventListener('mouseover', function (event) {
            if (!(event.target instanceof Element)) return;
            var anchor = event.target.closest('[data-hover-preview]');
            if (anchor && anchor.dataset.hoverPreview) {
                showHoverPreview(anchor.dataset.hoverPreview, anchor);
            } else if (!event.target.closest('.ma-hover-preview')) {
                hideHoverPreview();
            }
        });
        document.addEventListener('scroll', hideHoverPreview, true);
        window.addEventListener('blur', hideHoverPreview);
        // 点击胶囊：光标定位到 token 之后（含尾随空格），不落进胶囊遮盖的区域
        document.addEventListener('mousedown', function (event) {
            if (!(event.target instanceof Element)) return;
            var chip = event.target.closest('.ma-mention-chip');
            if (!chip) return;
            var ta = activeTextarea;
            if (!ta) return;
            event.preventDefault();
            var end = Number(chip.dataset.end);
            if (!Number.isFinite(end)) return;
            var pos = end;
            if (ta.value[pos] === ' ') pos += 1;
            pos = Math.min(Math.max(pos, 0), ta.value.length);
            ta.focus();
            ta.setSelectionRange(pos, pos);
        });
    }

    window.MAMentionChips = {
        scanAssetMentionTokens: scanAssetMentionTokens,
        register: register,
        briefById: briefById,
        sync: sync,
        setupHoverPreview: setupHoverPreview,
        hideHoverPreview: hideHoverPreview
    };
})();
